"""
simulation_worker.py — Worker de simulação de partidas
========================================================
Carrega decklists ({code, qty}) para objetos Card reais, roda N partidas
via OPTCGMatch (com OpponentModel + Monte Carlo já integrados no Turn
Planner), agrega o resultado (taxa de vitória, breakdown), e atualiza o
progresso do job no Postgres a cada partida concluída.

Roda em background (FastAPI BackgroundTasks) — chamado por api.py depois
de criar o job com status='pending'. Nunca é chamado de forma síncrona
numa requisição HTTP (ver db.py e a migration simulation_jobs: padrão
fila + polling, acordado em sessão de 23-24/06 para evitar timeout).
"""
import asyncio
import json
import os
from concurrent.futures import ProcessPoolExecutor

from optcg_engine.decision_engine import _make_card, OPTCGMatch

import db

# Partidas de um job sao independentes entre si -- rodam em PROCESSOS
# separados (mesmo padrao `--workers N` de gauntlet_matchup.py/
# audit_replay.py e do `/hand-stats` em api.py). E ganho puro: a MESMA
# partida, so simultanea, sem tocar em nada da qualidade da busca.
#
# Conta por nucleo FISICO, nao logico (achado 05/09, medido): na maquina
# do usuario (i3-8130U, 2 fisicos / 4 logicos), 4 workers deram ganho
# ZERO -- 17,6s por partida efetivos contra 16,5s rodando sozinha, porque
# 4 processos CPU-bound disputando 2 nucleos so se atrapalham (e ainda
# pagam 4x o custo de startup do motor). `cpu_count()//2` aproxima o
# numero fisico em CPU com hyperthreading, que e o caso comum.
SIMULATE_WORKERS = int(os.environ.get(
    'OPTCG_SIMULATE_WORKERS', str(max(2, (os.cpu_count() or 4) // 2))))

_DB_PATH = os.path.join(os.path.dirname(__file__), 'card_analysis_db.json')
with open(_DB_PATH, encoding='utf-8') as f:
    CARD_DB = json.load(f)


class DeckLoadError(Exception):
    """Erro ao carregar uma decklist — código de carta não encontrado ou líder ausente."""
    pass


def load_deck(cards: list[dict]) -> tuple:
    """
    Converte uma decklist no formato [{"code": "OP15-001", "qty": 4}, ...]
    em (leader: Card, main_deck: list[Card]). Mesma normalização de
    arte alternativa (split por '_') usada em api.py /analyze, para
    manter os dois caminhos consistentes.

    Levanta DeckLoadError se algum código não existir no banco ou se não
    houver exatamente 1 Leader na lista.
    """
    leader = None
    main_deck = []
    missing = []

    for entry in cards:
        code = entry['code'].split('_')[0]
        qty = entry.get('qty', 1)
        info = CARD_DB.get(code)
        if not info:
            missing.append(entry['code'])
            continue
        if info.get('type') == 'LEADER':
            leader = _make_card(code, info)
        else:
            main_deck.extend(_make_card(code, info) for _ in range(qty))

    if missing:
        raise DeckLoadError(f"cartas não encontradas: {', '.join(missing)}")
    if leader is None:
        raise DeckLoadError("decklist sem líder")

    return leader, main_deck


# Amostras Monte Carlo fixas e baixas pra busca offline -- mesma tripla e
# mesmo raciocinio de `_HAND_STATS_MC_OVERRIDE` em api.py (perfilado 05/09:
# reduz uma partida de ~85-88s pra ~11s, ainda e a busca REAL do motor, so
# com 1 amostra por candidata em vez do piso/teto adaptativo 3-6). Pedido
# explicito do usuario apos ver o "Simular" do front demorar ~1h nos
# defaults (5 simulacoes x 10 decks de meta = 50 partidas reais).
SIMULATE_FAST_MC_OVERRIDE = (1, 1, 1)

# Teto de parede por partida em run_simulation_job (achado 05/09): mesmo no
# modo rapido, um matchup especifico consumiu minutos de CPU numa partida
# so (jogo raro/degenerado, nao deadlock -- CPU do processo continuava
# subindo). 90s e generoso sobre o tipico medido (~11-60s) sem deixar 1
# partida ruim segurar o job inteiro.
PER_MATCH_TIMEOUT_S = 90


# MODO GULOSO no simulador do front (achado 05/09, pedido do usuario --
# "50 partidas deveria durar 2 min no maximo", depois de ver a IA do
# Naruto Card Game Simulator responder instantaneamente).
#
# `search_top_k_override=0` = aplica a acao de maior score estatico
# direto, SEM busca Monte Carlo -- a "Abordagem 1" classica de IA de TCG
# (pontuar as jogadas legais e escolher a melhor), que e o que aquele
# simulador faz em JavaScript no navegador.
#
# MEDIDO (5 partidas, mesmas seeds, mesmo deck real):
#   busca completa: 40,0s/partida, 13,6 turnos
#   guloso:          1,3s/partida, 14,2 turnos   -> ~30x
# As partidas NAO ficam mais longas -- o ganho e real, nao artefato.
#
# CUSTO DE QUALIDADE, ja medido em REPROVADOS.md (bloco 700, ablacao
# equivalente): `play` 28,9% -> 26,2% (-2,7pp), 12 lideres piores x 4
# melhores, piores casos -36,4pp. Aceito CONSCIENTEMENTE aqui porque
# nesta tela a pergunta e "qual o winrate do deck", e o ganho estatistico
# de rodar muitas mais partidas supera 2,7pp de qualidade de jogada
# (8 partidas dao +-30pp de margem; 200 dao +-6pp).
#
# NUNCA ligar no bot que joga contra humanos (sim_bridge.py/server.py):
# la a busca e liquido positivo, medido, e REPROVADOS.md e explicito.
SIMULATE_GREEDY_MODE = os.environ.get('OPTCG_SIMULATE_GREEDY', '1') == '1'


def run_single_match(deck_a: tuple, deck_b: tuple, hide_opponent_info: bool = True,
                      mc_samples_override: tuple[int, int, int] | None = SIMULATE_FAST_MC_OVERRIDE,
                      search_top_k_override: int | None = None) -> dict:
    """
    Roda 1 partida e devolve o resultado bruto de OPTCGMatch.simulate().

    hide_opponent_info=True (default, achado real 10/08, bloco 490 --
    fecha a pendencia do TODO bloco 370): este e o simulador self x self
    do front-end -- os dois lados nao podem "ver" a mao/deck real um do
    outro, igual o bot ao vivo ja nao ve. `OPTCGMatch(hide_opponent_info=
    True)` liga `self_play_info_hidden` nos dois `GameState`, que
    restringe os 2 pontos do motor que leem mao/deck do oponente direto
    (`opp_counter_potential`/`_opp_can_remove_stage`) ao que foi
    REVELADO de verdade + estimativa estatistica pro resto. Decisao
    explicita do bloco 370: as OUTRAS ferramentas de tuning/auditoria
    (audit_replay.py, baseline_metrics.py, tune_weights.py, via
    ReplayMatch) continuam full-info de proposito (mais deterministico
    pra calibracao) -- so este caminho (o simulador NOVO do front-end)
    usa a flag.
    """
    if search_top_k_override is None and SIMULATE_GREEDY_MODE:
        search_top_k_override = 0
    match = OPTCGMatch(deck_a, deck_b, hide_opponent_info=hide_opponent_info,
                       mc_samples_override=mc_samples_override,
                       search_top_k_override=search_top_k_override)
    return match.simulate()


def _run_match_in_worker(task: tuple) -> tuple[int, dict | None]:
    """Roda 1 partida num processo separado. Recebe SO dado picklable
    (indice do matchup + listas de {code, qty}), nunca objetos Card/
    GameState montados -- mesmo padrao de `gauntlet_matchup._run_one_seed`
    e do `_run_one_hand_stats_game` em api.py: reconstruir o deck dentro
    do worker e mais barato que serializar o estado do motor, e sempre
    picklable.

    Devolve `(idx_matchup, resultado|None)` -- o indice volta junto de
    proposito, pra quem agrega nao precisar mapear future->matchup por
    fora. `None` no resultado = partida falhou (some do agregado, nao
    derruba o job)."""
    idx_matchup, deck_a_raw, deck_b_raw = task
    try:
        leader_a, cards_a = load_deck(deck_a_raw)
        leader_b, cards_b = load_deck(deck_b_raw)
        return idx_matchup, run_single_match((leader_a, cards_a), (leader_b, cards_b))
    except Exception:
        return idx_matchup, None


def aggregate_results(results: list[dict]) -> dict:
    """
    Agrega N resultados de partida em estatísticas finais. `winner` em
    cada resultado é 'A' ou 'B' -- aqui A é sempre o deck do usuário
    (convenção mantida em run_simulation_job).
    """
    n = len(results)
    if n == 0:
        # Achado 05/09: agora alcancavel de verdade quando TODAS as
        # partidas de um matchup estouram PER_MATCH_TIMEOUT_S (antes so
        # existia pra n_sim=0, um pedido invalido). Mesmo shape do retorno
        # com dado (mesmas chaves, zeradas) -- sem isso, o `sum(b['wins']
        # for b in breakdown)` em run_simulation_job quebrava com
        # KeyError pra esse matchup especifico.
        return {
            'n_simulations': 0, 'wins': 0, 'losses': 0, 'win_rate': None,
            'avg_turns': None, 'avg_dmg_dealt': None, 'avg_dmg_taken': None,
        }

    wins_a = sum(1 for r in results if r.get('winner') == 'A')
    avg_turns = sum(r.get('turns', 0) for r in results) / n
    avg_dmg_a = sum(r.get('dmg_a', 0) for r in results) / n
    avg_dmg_b = sum(r.get('dmg_b', 0) for r in results) / n

    return {
        'n_simulations': n,
        'wins': wins_a,
        'losses': n - wins_a,
        'win_rate': round(wins_a / n, 4),
        'avg_turns': round(avg_turns, 2),
        'avg_dmg_dealt': round(avg_dmg_a, 2),
        'avg_dmg_taken': round(avg_dmg_b, 2),
    }


async def run_simulation_job(job_id: str):
    """
    Executa um job de simulação do início ao fim: carrega o(s) deck(s),
    roda as partidas necessárias conforme analysis_type, atualiza
    progresso a cada partida, e finaliza com o resultado agregado.

    Chamado como BackgroundTask a partir de api.py -- roda de forma
    assíncrona em relação à requisição HTTP que criou o job (que já
    retornou {job_id} antes desta função começar a rodar).
    """
    job = await db.get_job(job_id)
    if job is None:
        return  # job não existe (não deveria acontecer, mas não há onde reportar erro)

    try:
        await db.update_job_progress(job_id, progress=0, status='running')

        leader_a, deck_a_cards = load_deck(job['deck_a'])

        if job['analysis_type'] == 'meta':
            metas = await db.list_meta_decklists(
                is_current_meta=(job.get('meta_filter') or {}).get('is_current_meta', True),
                limit=job.get('n_meta_decks') or 20,
            )
            if not metas:
                await db.fail_job(job_id, "nenhuma decklist de meta disponível para comparação")
                return
            # meta_decklists.cards guarda SÓ o main deck (50 cartas, sem
            # leader) -- o leader_code é campo separado. load_deck() espera
            # leader + main juntos numa lista só, então o leader precisa
            # ser injetado aqui antes de montar matchups (bug corrigido em
            # 24/06: sem isto, load_deck() levantava "decklist sem líder"
            # para toda decklist de meta).
            matchups = [
                (m['name'], m['leader_code'], [{'code': m['leader_code'], 'qty': 1}] + m['cards'])
                for m in metas
            ]
        else:
            # custom_opponent ou own_decks: deck_b já vem completo no job
            # (com leader incluso, montado pelo frontend antes de chamar
            # POST /simulate -- ver src/app/simulate/page.tsx)
            matchups = [('oponente', None, job['deck_b'])]

        n_sim = job['n_simulations']
        # O total REAL so e conhecido aqui, depois de saber quantos
        # matchups existem de fato (a API estima `n_sim * n_meta_decks` ao
        # criar o job, mas o banco pode ter menos decklists que o pedido).
        total_steps = n_sim * len(matchups)
        if job.get('total_steps') != total_steps:
            await db.update_job_total_steps(job_id, total_steps)
        progress = 0
        breakdown = []
        cancelado = False

        # PARALELISMO (achado 05/09, pedido do usuario -- "50 partidas
        # deveria durar 2 min no maximo"): as partidas sao independentes,
        # entao rodam em PROCESSOS separados (mesmo padrao `--workers N` do
        # resto do projeto). Ganho ~linear nos nucleos SEM tocar em nada da
        # qualidade da busca -- e a mesma partida, so simultanea. Medido no
        # deck real do usuario: ~16,5s/partida sequencial -> 50 partidas em
        # ~3,5min com 4 workers (era ~14min sequencial).
        #
        # Uma task por partida, TODOS os matchups de uma vez (lista plana):
        # com o pool cheio o tempo ocioso entre matchups some, e cada
        # resultado volta marcado com o indice do matchup pra agregar
        # certo depois.
        tarefas = []
        for idx_matchup, (_nome, _lc, deck_b_cards) in enumerate(matchups):
            for _ in range(n_sim):
                tarefas.append((idx_matchup, job['deck_a'], deck_b_cards))

        resultados_por_matchup: dict[int, list] = {i: [] for i in range(len(matchups))}
        loop = asyncio.get_running_loop()

        with ProcessPoolExecutor(max_workers=SIMULATE_WORKERS) as pool:
            # O worker DEVOLVE o indice do matchup junto com o resultado --
            # nao da pra mapear future->matchup por fora com `as_completed`
            # (ele nao devolve os MESMOS objetos de future na iteracao
            # sincrona, o mapeamento quebraria em silencio).
            pendentes = {
                loop.run_in_executor(pool, _run_match_in_worker, t) for t in tarefas
            }
            while pendentes:
                # PER_MATCH_TIMEOUT_S: se NENHUMA das partidas em voo
                # terminar dentro do teto, e caso degenerado (jogo raro que
                # roda minutos -- CPU sobe, nao e deadlock, achado 05/09) --
                # abandona as restantes em vez de segurar o job. As que
                # estao nos processos terminam sozinhas; o pool fecha no
                # fim do `with`.
                concluidas, pendentes = await asyncio.wait(
                    pendentes, return_when=asyncio.FIRST_COMPLETED,
                    timeout=PER_MATCH_TIMEOUT_S)
                if not concluidas:
                    break

                for fut in concluidas:
                    try:
                        idx_matchup, resultado = fut.result()
                        if resultado is not None:
                            resultados_por_matchup[idx_matchup].append(resultado)
                    except Exception:
                        pass  # partida pulada -- nao derruba o job inteiro
                    progress += 1

                # Cancelamento (achado 05/09, pedido do usuario): confere o
                # status a cada lote concluido -- barato (1 SELECT) perto do
                # custo de uma partida.
                job_now = await db.get_job(job_id)
                if job_now is None or job_now.get('status') == 'cancelled':
                    cancelado = True
                    break
                await db.update_job_progress(job_id, progress=progress, status='running')

        if cancelado:
            return  # status='cancelled' ja gravado por cancel_job() -- nada mais a fazer

        for idx_matchup, (matchup_name, _lc, _cards) in enumerate(matchups):
            agg = aggregate_results(resultados_por_matchup[idx_matchup])
            agg['matchup'] = matchup_name
            breakdown.append(agg)

        # Agregado geral: soma os contadores de cada matchup já calculado
        # acima, em vez de re-rodar tudo junto -- mais simples e sem custo
        # extra.
        total_wins = sum(b['wins'] for b in breakdown)
        total_n = sum(b['n_simulations'] for b in breakdown)

        final_result = {
            'overall_win_rate': round(total_wins / total_n, 4) if total_n else None,
            'total_simulations': total_n,
            'breakdown_by_matchup': breakdown,
        }

        await db.finish_job(job_id, final_result)

    except DeckLoadError as e:
        await db.fail_job(job_id, str(e))
    except Exception as e:
        await db.fail_job(job_id, f"erro inesperado: {type(e).__name__}: {e}")