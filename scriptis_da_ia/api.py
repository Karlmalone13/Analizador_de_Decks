"""
api.py — API do analisador de decks OPTCG
==========================================
Expõe o motor de análise (deck_analyzer.analyze_deck) como endpoint HTTP.
Fonte ÚNICA de verdade: o front chama esta API, não reimplementa a lógica.
Busca manter esta camada o mais fina possível — só recebe a lista de cartas, chama o analisador, e devolve o resultado.
Rode localmente:
Rodar localmente:
    pip install fastapi uvicorn
    uvicorn api:app --reload --port 8000

Endpoint:
    POST /analyze
    body: { "cards": [ {"code": "OP15-001", "qty": 1}, {"code": "OP15-037", "qty": 4}, ... ] }
    resposta: análise completa (arquétipo, sinergias, coesão tribal, ratios, curva)
"""
import asyncio
import hashlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

import pandas as pd

from deck_analyzer import analyze_deck
import db
import simulation_worker
from simulation_worker import load_deck, DeckLoadError
from optcg_engine.decision_engine import (
    OPTCGMatch,
    build_real_deck,
    load_cards_db,
    validar_deck,
)
from hand_scorer import (
    card_to_handcard,
    deck_to_handcards,
    detect_archetype,
    searcher_quality,
    score_hand as hs_score,
)

# ── Carrega o card_analysis_db uma vez na inicialização ─────────────────────
_DB_PATH = os.path.join(os.path.dirname(__file__), 'card_analysis_db.json')
with open(_DB_PATH, encoding='utf-8') as f:
    CARD_DB = json.load(f)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # fecha o pool de conexões do Postgres de forma limpa no shutdown --
    # sem isto, conexões podem ficar penduradas no Supabase (free tier tem
    # limite baixo de conexões simultâneas).
    await db.close_pool()


app = FastAPI(title="OPTCG Deck Analyzer API", lifespan=lifespan)

# CORS: permite o front (em outro domínio) chamar a API.
# Em produção, troque "*" pela URL real do seu front.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class CardEntry(BaseModel):
    code: str
    qty: int = 1


class DeckRequest(BaseModel):
    cards: list[CardEntry]


class SimulateRequest(BaseModel):
    """
    Pedido de simulação. analysis_type define o que deck_b/n_meta_decks
    significam:
      - 'custom_opponent': deck_b obrigatório (decklist colada/escolhida)
      - 'own_decks': deck_b obrigatório (outro deck salvo do usuário)
      - 'meta': deck_b ignorado, n_meta_decks define quantas decklists de
        meta_decklists são usadas (limite de 20, acordado em sessão de
        23/06 para caber em tempo de processamento razoável)
    """
    analysis_type: str  # 'meta' | 'custom_opponent' | 'own_decks'
    deck_a: list[CardEntry]
    deck_b: Optional[list[CardEntry]] = None
    n_simulations: int = 10
    n_meta_decks: Optional[int] = None
    user_id: Optional[str] = None


MAX_N_SIMULATIONS = 10   # partidas por matchup -- limite acordado em 23/06
MAX_N_META_DECKS = 20    # decklists de meta por job -- limite acordado em 23/06


@app.get("/")
def health():
    return {"status": "ok", "cards_loaded": len(CARD_DB)}


def _flags_da_carta(info: dict) -> dict:
    """Recorte das classificacoes que o front precisa pra exibir, direto do
    `card_analysis_db.json` (gerado pelo pipeline de efeitos parseados).
    So repassa o que ja existe -- nao calcula nada novo aqui."""
    return {
        'name':        info.get('name'),
        'type':        info.get('type'),
        'cost':        info.get('cost'),
        'power':       info.get('power'),
        'counter':     info.get('counter'),
        'is_searcher': bool(info.get('is_searcher')),
        'is_blocker':  bool(info.get('is_blocker')),
        'is_removal':  bool(info.get('is_removal')),
        'draws':       bool(info.get('draws')),
        'has_rush':    bool(info.get('has_rush')),
        'has_trigger': bool(info.get('has_trigger')),
        'has_double_attack': bool(info.get('has_double_attack')),
        'has_unblockable':   bool(info.get('has_unblockable')),
        'has_banish':        bool(info.get('has_banish')),
        'has_counter_event': bool(info.get('has_counter_event')),
        'gives_don':   bool(info.get('gives_don')),
    }


@app.post("/analyze")
def analyze(req: DeckRequest):
    if not req.cards:
        raise HTTPException(status_code=400, detail="deck vazio")

    leader = None
    main = []
    missing = []
    por_carta = {}
    for entry in req.cards:
        code = entry.code.split('_')[0]  # normaliza arte alternativa
        info = CARD_DB.get(code)
        if not info:
            missing.append(entry.code)
            continue
        if info.get('type') == 'LEADER':
            leader = info
        else:
            main.extend([info] * entry.qty)
        por_carta[entry.code] = _flags_da_carta(info)

    if leader is None:
        raise HTTPException(status_code=400, detail="deck sem líder")

    result = analyze_deck(leader, main)
    # Classificacao POR CARTA (achado 05/09): o front reimplementava isso em
    # TypeScript lendo `card_text` cru -- e errava. Exemplo real: as cartas de
    # busca deste banco dizem "Look at 5 cards from the top of your deck",
    # enquanto o TS procurava "look at the top", entao a tela mostrava 0%
    # de chance de searcher na abertura num deck com 8 deles. O motor nao le
    # texto: usa os EFEITOS PARSEADOS (`look_top_deck`/`add_to_hand`), a
    # gramatica construida ao longo de meses de auditorias.
    #
    # Devolver as flags aqui deixa o front EXIBIR sem reimplementar (regra do
    # projeto: "fonte UNICA de verdade: o front chama esta API, nao
    # reimplementa a logica"). A matematica de maos pode seguir no navegador
    # -- ela estava certa; o errado era a CLASSIFICACAO que a alimentava.
    result['cards'] = por_carta
    if missing:
        result['warnings'] = {'cards_nao_encontradas': missing}
    return result


@app.post("/simulate")
async def simulate(req: SimulateRequest, background_tasks: BackgroundTasks):
    """
    Cria um job de simulação e dispara a execução em background. Responde
    IMEDIATAMENTE com {job_id} -- a requisição HTTP nunca espera as
    partidas rodarem (padrão fila + polling, acordado em 23/06 para evitar
    timeout: ~10 partidas x 20 decklists de meta pode levar minutos).

    O cliente deve consultar GET /simulate/status/{job_id} periodicamente
    até status='done' ou 'error'.
    """
    if req.analysis_type not in ('meta', 'custom_opponent', 'own_decks'):
        raise HTTPException(status_code=400, detail="analysis_type inválido")

    if req.analysis_type in ('custom_opponent', 'own_decks') and not req.deck_b:
        raise HTTPException(status_code=400, detail=f"deck_b é obrigatório para analysis_type={req.analysis_type}")

    n_sim = min(req.n_simulations, MAX_N_SIMULATIONS)
    n_meta = min(req.n_meta_decks or MAX_N_META_DECKS, MAX_N_META_DECKS) if req.analysis_type == 'meta' else None

    deck_a_dicts = [{'code': c.code, 'qty': c.qty} for c in req.deck_a]
    deck_b_dicts = [{'code': c.code, 'qty': c.qty} for c in req.deck_b] if req.deck_b else None

    total_steps = n_sim * (n_meta if req.analysis_type == 'meta' else 1)

    job_id = await db.create_job(
        analysis_type=req.analysis_type,
        deck_a=deck_a_dicts,
        deck_b=deck_b_dicts,
        n_simulations=n_sim,
        n_meta_decks=n_meta,
        total_steps=total_steps,
        user_id=req.user_id,
    )

    background_tasks.add_task(simulation_worker.run_simulation_job, job_id)

    return {"job_id": job_id, "status": "pending", "total_steps": total_steps}


class ReplayRequest(BaseModel):
    """Pedido de replay de uma única partida com log detalhado de eventos."""
    deck_a: list[CardEntry]
    deck_b: list[CardEntry]
    name_a: str = 'Player A'
    name_b: str = 'Player B'


@app.post("/replay")
async def replay(req: ReplayRequest):
    """
    Roda UMA partida completa e retorna log estruturado de eventos por turno.
    Usado pelo replay viewer no frontend para mostrar o que aconteceu em cada
    turno: cartas jogadas, ataques, dano na vida, efeitos disparados.

    Resposta: {winner, turns, events: [...], turns_detail: [{turn, events}]}
    Cada evento tem: {turn, player, player_name, phase, type, card, target, description}
    card/target: {code, name, image, cost, power, type, color}
    """
    from optcg_engine.decision_engine import OPTCGMatch
    from simulation_worker import load_deck, DeckLoadError

    def entries_to_dict(entries):
        return [{'code': e.code, 'qty': e.qty} for e in entries]

    try:
        deck_a = load_deck(entries_to_dict(req.deck_a))
        deck_b = load_deck(entries_to_dict(req.deck_b))
    except DeckLoadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Erro ao montar deck: {e}')

    try:
        match = OPTCGMatch(deck_a, deck_b)
        result = match.simulate_replay(name_a=req.name_a, name_b=req.name_b)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Erro na simulação: {e}')

    return result


@app.get("/replay/demo")
async def replay_demo(seed: int = 42):
    """
    Roda uma partida demo usando dois decks reais de decklists_raw.csv.
    Serve para validar visualmente o Replay Viewer sem exigir deck salvo.
    """
    import random
    import pandas as pd
    from optcg_engine.decision_engine import (
        OPTCGMatch,
        build_real_deck,
        load_cards_db,
        validar_deck,
    )

    try:
        rng = random.Random(seed)
        base_dir = os.path.dirname(__file__)
        cards_db = load_cards_db(os.path.join(base_dir, 'cards_rows.csv'))
        df_raw = pd.read_csv(os.path.join(base_dir, 'decklists_raw.csv'))
        urls = df_raw.groupby('deck_url')['deck_name'].first()

        decks = []
        for url, name in urls.items():
            built = build_real_deck(name, url, df_raw, cards_db)
            if not built:
                continue
            leader, cards, start_stage = built
            valido, _erros = validar_deck(leader, cards, cards_db)
            if valido and len(cards) >= 40:
                decks.append((name, (leader, cards, start_stage)))
            if len(decks) >= 16:
                break
        if len(decks) < 2:
            raise HTTPException(status_code=500, detail='Menos de 2 decks demo validos.')

        idx_a, idx_b = rng.sample(range(len(decks)), 2)
        name_a, deck_a = decks[idx_a]
        name_b, deck_b = decks[idx_b]
        match = OPTCGMatch(deck_a, deck_b)
        result = match.simulate_replay(name_a=name_a, name_b=name_b)
        result['demo'] = {
            'seed': seed,
            'deck_a': name_a,
            'deck_b': name_b,
        }
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Erro no replay demo: {e}')


@app.get("/leader-stats")
def leader_stats(leader_name: str):
    """
    Retorna estatísticas de partidas reais do banco de logs para um líder.
    Agrega: quais cartas foram jogadas em cada turno (tipo 'play') e com
    que frequência, baseado em todos os logs onde esse líder aparece.

    Query param: leader_name (parcial, case-insensitive — ex: "Krieg")
    Resposta: {
      total_games: int,
      turns: {
        "1": [{card_code, card_name, count, pct}],
        "2": [...],
        ...
      }
    }
    """
    import glob as _glob

    logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
    index_path = os.path.join(logs_dir, 'index.json')

    try:
        with open(index_path, encoding='utf-8') as f:
            index = json.load(f)
    except Exception:
        raise HTTPException(status_code=500, detail='Índice de logs não encontrado')

    needle = leader_name.lower().strip()

    # Encontra todos os logs onde o líder aparece (como p1 ou p2)
    matching = []
    for entry in index:
        p1_match = needle in entry.get('p1', {}).get('leader_name', '').lower()
        p2_match = needle in entry.get('p2', {}).get('leader_name', '').lower()
        if p1_match or p2_match:
            matching.append({
                'entry': entry,
                'player_name': entry['p1']['name'] if p1_match else entry['p2']['name'],
            })

    if not matching:
        return {'total_games': 0, 'turns': {}}

    # Agrega plays por turno
    from collections import defaultdict
    turn_plays: dict[int, dict[str, dict]] = defaultdict(dict)

    for m in matching:
        parsed_path = os.path.join(logs_dir, m['entry']['parsed_file'])
        try:
            with open(parsed_path, encoding='utf-8') as f:
                log = json.load(f)
        except Exception:
            continue

        player_name = m['player_name']
        for turn_data in log.get('turns', []):
            if turn_data.get('player') != player_name:
                continue
            turn_num = turn_data.get('turn', 0)
            for action in turn_data.get('actions', []):
                if action.get('type') != 'play':
                    continue
                code = action.get('card', '')
                name = action.get('card_name', code)
                if code not in turn_plays[turn_num]:
                    turn_plays[turn_num][code] = {'card_code': code, 'card_name': name, 'count': 0}
                turn_plays[turn_num][code]['count'] += 1

    total = len(matching)
    result_turns = {}
    for t_num in sorted(turn_plays.keys()):
        plays = sorted(turn_plays[t_num].values(), key=lambda x: -x['count'])
        for p in plays:
            p['pct'] = round(p['count'] / total, 3)
        result_turns[str(t_num)] = plays

    return {'total_games': total, 'turns': result_turns}


class _HandStatsInstrumentedMatch(OPTCGMatch):
    """Captura a mao de abertura pos-setup. Modulo-level (nao aninhada na
    rota) de proposito: ProcessPoolExecutor precisa reimportar a classe por
    nome em cada worker (spawn no Windows) -- uma classe local dentro de
    `hand_stats()` nao e picklable."""
    def setup(self):
        super().setup()
        self._opening_hand_a = list(self.state_a.hand)
        self._opening_hand_b = list(self.state_b.hand)


# Cache por PROCESSO worker (nao por task) -- carregar cards_db/decklists_raw
# custa ~7s sozinho (medido 05/09), e o ProcessPoolExecutor reusa os MESMOS
# poucos processos worker pra todas as tasks de um `.map()` (nao spawna um
# processo novo por task). Carregar 1x por worker e reusar nas tasks
# seguintes roteadas pra ele evita pagar 7s de novo em CADA partida.
_worker_cards_db = None
_worker_df_raw = None


def _hand_stats_worker_context():
    global _worker_cards_db, _worker_df_raw
    if _worker_cards_db is None:
        base_dir = os.path.dirname(__file__)
        _worker_cards_db = load_cards_db(os.path.join(base_dir, 'cards_rows.csv'))
        _worker_df_raw = pd.read_csv(os.path.join(base_dir, 'decklists_raw.csv'))
    return _worker_cards_db, _worker_df_raw


def _run_one_hand_stats_game(task):
    """Roda 1 partida completa e devolve {score, going_first, won} ou None.

    `task` carrega só primitivos picklable (código/qty, nomes) -- nunca os
    objetos Card/GameState reconstruídos, mesmo padrão de
    gauntlet_matchup.py `_run_one_seed` (docstring lá explica o motivo:
    reconstruir do zero em cada worker é mais barato e sempre picklable,
    ao contrário de passar os objetos do motor prontos pela fila).
    """
    (user_cards_raw, opp_name, opp_url, going_first,
     arq, sq, bomb_code, mc_samples_override) = task
    try:
        cards_db, df_raw = _hand_stats_worker_context()
        user_deck = load_deck(user_cards_raw)
        built = build_real_deck(opp_name, opp_url, df_raw, cards_db)
        if not built:
            return None
        opp_deck = built

        if going_first:
            match = _HandStatsInstrumentedMatch(
                user_deck, opp_deck, mc_samples_override=mc_samples_override)
            match.state_a.is_first = True
            match.state_b.is_first = False
            result = match.simulate()
            initial_hand = match._opening_hand_a
            user_player = 'A'
        else:
            match = _HandStatsInstrumentedMatch(
                opp_deck, user_deck, mc_samples_override=mc_samples_override)
            match.state_a.is_first = True
            match.state_b.is_first = False
            result = match.simulate()
            initial_hand = match._opening_hand_b
            user_player = 'B'

        hand_hc = [card_to_handcard(c) for c in initial_hand]
        sc = hs_score(hand_hc, going_first=going_first, arq=arq, sq=sq, bomb_code=bomb_code)
        won = result.get('winner') == user_player
        return {'score': sc, 'going_first': going_first, 'won': won}
    except Exception:
        return None


# Amostras FIXAS e baixas pra busca offline -- so usado aqui (ver docstring
# de OPTCGMatch.mc_samples_override em decision_engine.py). Medido 05/09:
# reduz uma partida de ~88s pra ~11s (a busca ainda é REAL, só com 1
# amostra Monte Carlo por candidata em vez do piso/teto adaptativo 3-6).
_HAND_STATS_MC_OVERRIDE = (1, 1, 1)

_HAND_STATS_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'hand_stats_cache')


def _hand_stats_cache_key(cards: list[CardEntry]) -> str:
    """Hash estável da COMPOSIÇÃO do deck (líder + código/qty ordenados) --
    dois decks com o mesmo conteúdo (mesmo vindos de `deck.id` diferentes
    no Supabase) compartilham o cache."""
    payload = sorted((c.code, c.qty) for c in cards)
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def _hand_stats_pending_path(cache_key: str) -> str:
    return os.path.join(_HAND_STATS_CACHE_DIR, f'{cache_key}.pending.json')


def _compute_and_cache_hand_stats(user_cards_raw: list[dict], cache_key: str,
                                   n_games: int, workers: int) -> None:
    """Corpo pesado de `/hand-stats`, rodado em BACKGROUND (ver rota).

    Nunca levanta HTTPException (ninguém está esperando a resposta HTTP
    quando isto roda) -- em erro, apaga o marcador `.pending` e sai; o
    próximo GET/POST simplesmente tenta de novo (mesmo efeito de nunca ter
    ficado pronto, sem marcador travado achando que ainda está calculando).
    """
    cache_path = os.path.join(_HAND_STATS_CACHE_DIR, f'{cache_key}.json')
    pending_path = _hand_stats_pending_path(cache_key)
    try:
        user_deck = load_deck(user_cards_raw)
        user_leader, user_cards, *_ = user_deck

        hand_cards_all = deck_to_handcards(user_cards)
        arq = detect_archetype(hand_cards_all)
        sq  = searcher_quality(hand_cards_all)

        bomb_code = None
        if user_cards:
            bomb_cand = max(user_cards, key=lambda c: getattr(c, 'cost', 0))
            if getattr(bomb_cand, 'cost', 0) >= 7:
                bomb_code = getattr(bomb_cand, 'code', None)

        base_dir = os.path.dirname(__file__)
        cards_db = load_cards_db(os.path.join(base_dir, 'cards_rows.csv'))
        df_raw   = pd.read_csv(os.path.join(base_dir, 'decklists_raw.csv'))

        urls = df_raw.groupby('deck_url')['deck_name'].first()
        opponent_pool = []  # so (name, url) -- cada worker reconstroi o deck
        for url, name in urls.items():
            built = build_real_deck(name, url, df_raw, cards_db)
            if not built:
                continue
            opp_leader, opp_cards, opp_stage = built
            valido, _ = validar_deck(opp_leader, opp_cards, cards_db)
            if valido and len(opp_cards) >= 40:
                opponent_pool.append((name, url))
            if len(opponent_pool) >= 8:
                break

        if not opponent_pool:
            return

        n_per_opp = max(1, n_games // len(opponent_pool))
        tasks = [
            (user_cards_raw, opp_name, opp_url, (g % 2 == 0),
             arq, sq, bomb_code, _HAND_STATS_MC_OVERRIDE)
            for opp_name, opp_url in opponent_pool
            for g in range(n_per_opp)
        ]

        if workers <= 1:
            raw_records = [_run_one_hand_stats_game(t) for t in tasks]
        else:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                raw_records = list(ex.map(_run_one_hand_stats_game, tasks))
        records = [r for r in raw_records if r is not None]
        if not records:
            return

        BRACKETS = [
            {'label': 'Ruim',            'min': -9999, 'max': 50},
            {'label': 'Abaixo da média', 'min': 50,    'max': 80},
            {'label': 'Médio',           'min': 80,    'max': 110},
            {'label': 'Bom',             'min': 110,   'max': 140},
            {'label': 'Excelente',       'min': 140,   'max': 9999},
        ]
        score_brackets = []
        for b in BRACKETS:
            in_bracket = [r for r in records if b['min'] <= r['score'] < b['max']]
            if not in_bracket:
                continue
            wins = sum(1 for r in in_bracket if r['won'])
            score_brackets.append({
                'label':     b['label'],
                'min_score': b['min'] if b['min'] > -9999 else None,
                'max_score': b['max'] if b['max'] < 9999  else None,
                'n_games':   len(in_bracket),
                'wins':      wins,
                'win_rate':  round(wins / len(in_bracket), 3),
            })

        mulligan_threshold: int | None = None
        for b_info in score_brackets:
            if b_info['win_rate'] < 0.45 and b_info['max_score'] is not None:
                mulligan_threshold = b_info['max_score']
                break

        all_scores = [r['score'] for r in records]
        response = {
            'archetype':          arq,
            'n_games_ran':        len(records),
            'overall_win_rate':   round(sum(1 for r in records if r['won']) / len(records), 3),
            'avg_hand_score':     round(sum(all_scores) / len(all_scores)),
            'score_brackets':     score_brackets,
            'mulligan_threshold': mulligan_threshold,
            'from_cache':         False,
        }
        os.makedirs(_HAND_STATS_CACHE_DIR, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(response, f)
    except Exception as e:
        print(f'[hand-stats] calculo em background falhou pra {cache_key}: {e}')
    finally:
        try:
            os.remove(pending_path)
        except OSError:
            pass


@app.post("/hand-stats")
async def hand_stats(req: DeckRequest, background_tasks: BackgroundTasks,
                      n_games: int = 24, workers: int = 4):
    """
    Valida a heurística de scoring de mão simulando N partidas reais, cada
    uma jogada de verdade pelo motor (`OPTCGMatch`) contra um pool de decks
    de meta reais.

    Retorna (quando pronto):
    - score_brackets: win rate por faixa de score
    - mulligan_threshold: score abaixo do qual win rate < 45%
    - archetype: arquétipo detectado
    - n_games_ran: partidas efetivamente simuladas

    Assíncrono com cache (achado 05/09): o docstring antigo estimava
    ~1-3s/partida; medido de verdade, a busca padrão do motor gasta ~88s
    NUMA partida só (perfilado -- é o custo real da busca Monte Carlo que
    faz o bot jogar bem, não um bug). Mesmo com amostragem reduzida
    (`_HAND_STATS_MC_OVERRIDE`, ~11s/partida isolada) + paralelismo
    (`workers`), o LOTE inteiro (24 jogos contra 8 decks de meta variados)
    mediu ~6-7 minutos de parede -- variância grande entre matchups, longe
    de caber numa requisição HTTP síncrona.

    Por isso o endpoint NUNCA bloqueia esperando o cálculo:
    - cache-hit (`hand_stats_cache/<hash>.json`, chaveado pela COMPOSIÇÃO
      do deck -- líder + código/qty ordenados, não pelo id do deck salvo
      no Supabase) -> responde na hora, sem rodar nada.
    - cache-miss sem cálculo em andamento -> dispara o cálculo em
      BACKGROUND (`BackgroundTasks`, roda DEPOIS da resposta ser enviada)
      e responde imediatamente `{"status": "computing", ...}`.
    - cache-miss COM cálculo já em andamento (marcador `.pending.json`)
      -> responde `{"status": "computing", ...}` de novo, sem duplicar o
      trabalho.
    O front trata a ausência de `score_brackets` como "ainda não
    disponível" (mesmo catch que já tratava timeout) -- a run de fundo
    escreve o cache pronto pra próxima vez que a página for aberta.
    """
    cache_key = _hand_stats_cache_key(req.cards)
    cache_path = os.path.join(_HAND_STATS_CACHE_DIR, f'{cache_key}.json')
    if os.path.exists(cache_path):
        with open(cache_path, encoding='utf-8') as f:
            cached = json.load(f)
        cached['from_cache'] = True
        return cached

    # Validação rápida e síncrona do deck ANTES de aceitar a task em
    # background -- erro de deck malformado tem que voltar 400 na hora,
    # não silenciosamente sumir dentro de uma background task sem ninguém
    # ouvindo.
    user_cards_raw = [{'code': c.code, 'qty': c.qty} for c in req.cards]
    try:
        load_deck(user_cards_raw)
    except DeckLoadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Erro ao montar deck: {e}')

    # Marcador `.pending` travado (servidor derrubado/reiniciado no meio do
    # calculo -- o `finally` que apaga o marcador nunca roda) trataria
    # QUALQUER pedido futuro pra este deck como "já está calculando" pra
    # sempre. 20 min é generoso sobre o pior caso medido (~7 min o lote
    # inteiro) -- expira e deixa tentar de novo.
    pending_path = _hand_stats_pending_path(cache_key)
    pending_stale = False
    if os.path.exists(pending_path):
        try:
            with open(pending_path, encoding='utf-8') as f:
                pending_stale = (time.time() - json.load(f).get('started_at', 0)) > 1200
        except (OSError, ValueError):
            pending_stale = True
    if not os.path.exists(pending_path) or pending_stale:
        os.makedirs(_HAND_STATS_CACHE_DIR, exist_ok=True)
        with open(pending_path, 'w', encoding='utf-8') as f:
            json.dump({'started_at': time.time()}, f)
        background_tasks.add_task(
            _compute_and_cache_hand_stats, user_cards_raw, cache_key, n_games, workers)

    return {
        'status': 'computing',
        'from_cache': False,
        'message': 'Simulação rodando em segundo plano (leva alguns minutos na primeira '
                    'vez para este deck) -- reabra a análise depois.',
    }


@app.get("/simulate/status/{job_id}")
async def simulate_status(job_id: str):
    """
    Consulta rápida ao banco -- nunca espera nada, só lê o estado atual do
    job. O front faz polling neste endpoint a cada poucos segundos até
    status='done' ou 'error'.
    """
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


@app.post("/simulate/{job_id}/cancel")
async def simulate_cancel(job_id: str):
    """
    Cancela um job em andamento (pedido do usuário, 05/09 -- ver
    `db.cancel_job` e o loop em `simulation_worker.run_simulation_job`
    pra como isso interrompe as PRÓXIMAS partidas, não a que já estiver
    rodando naquele instante). Idempotente: chamar de novo num job já
    'done'/'error'/'cancelled' não faz nada (o UPDATE em `cancel_job` só
    afeta 'pending'/'running').
    """
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    await db.cancel_job(job_id)
    return {"status": "cancelling"}
