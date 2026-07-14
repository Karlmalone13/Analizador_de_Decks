"""
sim_bridge.py — Ponte entre OPTCGSim e o engine de decisão.

Responsabilidades:
  1. Ler arquivos .deck do OPTCGSim (formato "NxCODE" por linha)
  2. Montar (leader, cards, None) compatível com OPTCGMatch
  3. Sincronizar o estado visual (mão/campo escaneados) → GameState
  4. Expor choose_action(game_state, opp_state) → ação para executar
"""
from __future__ import annotations
import os, sys
from copy import copy, deepcopy
from pathlib import Path
from typing import Optional

# Garante que o engine seja importável tanto de dentro quanto de fora do pacote
_ENGINE_DIR = Path(__file__).parent
_SCRIPTS_DIR = _ENGINE_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from optcg_engine.decision_engine import (
    _make_card,
    load_cards_db,
    GameState,
    Card,
    CardData,
    DecisionEngine,
    _load_effects_db,
    _load_analysis_db,
)
from optcg_engine.rules_facade import choose_highest_board_value

DECKS_DIR = Path(r"E:\Games\OnePieceSimulador\Builds_Windows\Decks")
CSV_PATH  = _SCRIPTS_DIR / "cards_rows.csv"

# ── Carrega banco de cartas uma vez ───────────────────────────────────────────
# _load_effects_db/_load_analysis_db populam globals do decision_engine e
# retornam None — ler o global depois de carregar (bug corrigido: _effects_db
# era sempre None aqui).
from optcg_engine import decision_engine as _de
_load_effects_db()
_load_analysis_db()
_effects_db  = getattr(_de, '_EFFECTS_DB', None) or {}
_analysis_db = getattr(_de, '_ANALYSIS_DB', None) or {}
_cards_db    = load_cards_db(str(CSV_PATH))


def list_decks() -> list[str]:
    """Retorna nomes dos decks disponíveis (sem extensão)."""
    return sorted(p.stem for p in DECKS_DIR.glob("*.deck"))


def load_sim_deck(deck_name: str) -> tuple:
    """
    Lê <deck_name>.deck e devolve (leader: Card, cards: list[Card], None).
    Formato do arquivo: cada linha = "NxCODE", primeira = líder (1x...).
    """
    path = DECKS_DIR / f"{deck_name}.deck"
    if not path.exists():
        raise FileNotFoundError(f"Deck não encontrado: {path}")

    leader: Optional[Card] = None
    cards: list[Card] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        qty_str, code = line.split("x", 1)
        qty  = int(qty_str)
        data = _cards_db.get(code)
        if not data:
            # Carta não está no banco — cria um stub básico
            data = {"name": code, "type": "CHARACTER", "cost": 0,
                    "power": 0, "text": "", "color": "", "sub_types": "",
                    "life": 0, "has_trigger": False}
        card = _make_card(code, data)
        if card.card_type == "LEADER":
            leader = card
        else:
            for _ in range(qty):
                cards.append(deepcopy(card))

    if leader is None:
        raise ValueError(f"Nenhum líder encontrado em {path}")

    return leader, cards, None


def build_game_state(leader: Card, deck_cards: list[Card]) -> GameState:
    """Cria um GameState inicial vazio (setup não executado) para o bridge."""
    return GameState(
        leader=deepcopy(leader),
        deck=[deepcopy(c) for c in deck_cards],
    )


def sync_hand(gs: GameState, scanned: list[dict]) -> None:
    """
    Atualiza gs.hand com as cartas escaneadas visualmente.

    scanned: lista de dicts {code, name, cost, power, x}
    Preserva objetos Card existentes se já estiverem na mão (por código).
    """
    # Índice rápido das cartas já na mão por código
    in_hand: dict[str, list[Card]] = {}
    for c in gs.hand:
        in_hand.setdefault(c.code, []).append(c)

    new_hand: list[Card] = []
    for info in scanned:
        code = info.get("code")
        if not code:
            continue
        # Reusa objeto existente se disponível
        existing = in_hand.get(code, [])
        if existing:
            card = existing.pop(0)
        else:
            data = _cards_db.get(code, {})
            card = _make_card(code, data) if data else None
            if card is None:
                continue
        # Guarda posição visual para o bot saber onde clicar
        card._sim_x = info.get("x", 0)
        new_hand.append(card)

    gs.hand = new_hand


def sync_field(gs: GameState, scanned: list[dict]) -> None:
    """Atualiza gs.field_chars com as cartas escaneadas no campo."""
    in_field: dict[str, list[Card]] = {}
    for c in gs.field_chars:
        in_field.setdefault(c.code, []).append(c)

    new_field: list[Card] = []
    for info in scanned:
        code = info.get("code")
        if not code:
            continue
        existing = in_field.get(code, [])
        if existing:
            card = existing.pop(0)
        else:
            data = _cards_db.get(code, {})
            card = _make_card(code, data) if data else None
            if card is None:
                continue
        card._sim_x = info.get("x", 0)
        card._sim_y = info.get("y", 0)
        new_field.append(card)

    gs.field_chars = new_field


def can_execute_action(action: tuple, gs: GameState) -> tuple[bool, str]:
    """
    Pre-validacao rapida antes de tentar executar uma acao no simulador.

    Filtra acoes que o engine gerou mas que o estado local mostra como
    invalidas (ex: carta nao esta mais na mao, personagem esta rested,
    DON insuficiente). Evita F em cascata sem precisar de rescan completo.

    Retorna (ok: bool, motivo: str).
    """
    if action is None:
        return False, "action=None"
    if len(action) < 3:
        return False, "action curta"

    score, atype, card = action[0], action[1], action[2]

    if atype == 'play':
        if card is None:
            return False, "card=None"
        cost = getattr(card, 'cost', 0) or 0
        if gs.don_available < cost:
            return False, f"DON insuf: {gs.don_available}<{cost}"
        # Carta deve estar na mao com posicao visual valida
        in_hand = any(c.code == card.code for c in gs.hand)
        if not in_hand:
            return False, f"{card.code} nao esta na mao"
        has_pos = any(c.code == card.code and getattr(c, '_sim_x', 0) > 0
                      for c in gs.hand)
        if not has_pos:
            return False, f"{card.code} sem _sim_x (mao stale?)"

    elif atype == 'attack':
        if card is None:
            return False, "card=None"
        c = next((c for c in gs.field_chars if c.code == card.code), None)
        if c is None:
            return False, f"{card.code} nao esta no campo"
        if getattr(c, 'rested', False):
            return False, f"{card.code} esta rested"
        has_rush = (
            getattr(c, 'has_rush', False)
            or getattr(c, 'rush_this_turn', False)
            or getattr(c, 'rush_character_only_this_turn', False)
            or (hasattr(c, 'is_rush') and c.is_rush())
            or (hasattr(c, 'is_rush_character') and c.is_rush_character())
        )
        if getattr(c, 'just_played', False) and not has_rush:
            return False, f"{card.code} just_played sem Rush"

    elif atype == 'activate':
        if card is None:
            return False, "card=None"
        ctype = getattr(card, 'card_type', '')
        if ctype not in ('LEADER', 'STAGE'):
            c = next((c for c in gs.field_chars if c.code == card.code), None)
            if c is None:
                return False, f"{card.code} nao esta no campo"

    return True, "ok"


def choose_action(gs: GameState, opp_gs: GameState,
                  match, timeout: float = 4.0,
                  allowed_types: Optional[set] = None,
                  exclude_activate_codes: Optional[set] = None) -> Optional[tuple]:
    """
    Pede ao engine a melhor ação para o estado atual.

    Retorna a tuple de ação (score, tipo, carta, ...) ou None se não há ação.
    O chamador usa action[1] (tipo: 'play'|'attack'|'activate'|...) e
    action[2] (carta) para executar no simulador.

    allowed_types: se dado, retorna a melhor ação de score >= 0 cujo TIPO o
    executor sabe realizar (ex: o plugin só executa play/attack/attach_don).
    A ordem de preferência continua sendo 100% do engine — isto só pula
    ações que o executor não tem como fazer, em vez de encerrar o turno.

    exclude_activate_codes: códigos de carta cuja ativação já foi OFERECIDA
    e RECUSADA neste turno (via /defense fase "optional", ver
    _declined_optional em server.py). Achado real 10/07 (log 23.19.23): o
    GameState é reconstruído do zero a cada /decide — sem esse filtro, uma
    ativação recusada (custo opcional não vale a pena) continua com o MESMO
    score alto na próxima chamada, porque nada no estado mudou, e é
    reoferecida indefinidamente, travando o turno em loop sem nunca
    tentar a próxima ação da lista.
    """
    import threading
    result: list = [None]
    exclude_activate_codes = exclude_activate_codes or set()

    def _run() -> None:
        try:
            engine = DecisionEngine(gs, opp_gs)
            actions = match._generate_and_score_actions(gs, opp_gs, engine)
            print(f"[ENG] {len(actions)} acoes | hand={len(gs.hand)} don={gs.don_available} turn={gs.turn}", flush=True)
            if actions:
                print(f"[ENG] top3: {[(a[0],a[1]) for a in actions[:3]]}", flush=True)
            for a in actions:
                if a[0] < 0:
                    break
                if a[1] == 'activate' and len(a) > 2 and getattr(a[2], 'code', None) in exclude_activate_codes:
                    continue
                if allowed_types is None or a[1] in allowed_types:
                    result[0] = a
                    # Diagnostico de gerenciamento de mao (08/07: usuario
                    # reportou o bot jogando cartas de counter alto custo
                    # 1-2 ate ficar sem mao) -- so loga quando a mao ja
                    # esta fina (<=3 ANTES desta jogada), pra nao poluir o
                    # log em turnos normais. Numeros reais aqui permitem
                    # auditar se a régua de preservacao de mao (hand<=3 em
                    # _generate_and_score_actions) esta protegendo cartas
                    # de counter alto o suficiente, em vez de so contar
                    # cartas.
                    if a[1] == 'play' and len(gs.hand) <= 3:
                        c = a[2]
                        print(f"[PLAY] mao fina ({len(gs.hand)} cartas): "
                              f"jogou {c.code} custo={c.cost} counter={c.counter} "
                              f"score={a[0]:.1f}", flush=True)
                    break
        except Exception as e:
            import traceback
            print(f"[ENG-ERR] {e}\n{traceback.format_exc()}", flush=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


def don_for_attack(gs: GameState, opp_gs: GameState, action: tuple,
                   match=None) -> int:
    """
    Quantos DON o executor deve anexar ao atacante ANTES de declarar o
    ataque escolhido pelo engine. 0 = declara direto (ataque "seco" de
    pressão — o oponente que escolha entre counter e perder a carta/vida).

    Com `match`, calcula o DON LIVRE do plano do turno via
    `OPTCGMatch._don_livre_for_plan` (fonte única compartilhada com o
    simulador interno — achado real 10/07: essa conta existia SÓ aqui,
    duplicada; `_attach_don_for_attack` no simulador chamava
    don_needed_for_attack sem don_livre, tratando TODO o don_available
    como ocioso, o que inflava a margem de ataque muito além do
    necessário e esvaziava o DON que sobraria pra jogar outras cartas no
    mesmo turno).
    """
    from optcg_engine.decision_engine import don_needed_for_attack
    if action is None or len(action) < 3 or action[1] != 'attack':
        return 0
    attacker = action[2]
    ttype = action[3] if len(action) > 3 else 'leader'
    tgt = action[4] if len(action) > 4 else None
    engine = DecisionEngine(gs, opp_gs)

    don_livre = match._don_livre_for_plan(gs, opp_gs, engine) if match is not None else None

    return don_needed_for_attack(attacker, ttype or 'leader', tgt,
                                 gs, opp_gs, engine, don_livre=don_livre)


def choose_turn_order(deck_codes: list[str]) -> dict:
    """
    Decide ir de 1o ou 2o pelo PERFIL do deck pilotado (pedido do usuario
    12-13/07: nada de 50/50, e nao so a curva crua — usar o retrato completo
    que o bot ja deriva do deck: arquetipo + papeis + curva).

    Regra do jogo (por que importa pra CURVA DE DON): 1o ataca antes (tempo)
    mas NAO compra no t1 e abre com 1 DON; 2o compra no t1 e abre com 2 DON,
    chegando antes ao mid-game. Entao:
    - deck que converte tempo/pressao cedo (Aggro, curva baixa, Rush) quer
      ser PRIMEIRO;
    - deck que precisa de RECURSO/rampa/combo caro (Controle, Ramp, recursao,
      win-con de custo alto) quer ser SEGUNDO.

    Score transparente e UNIVERSAL (deriva do deck_profile, zero nome de
    carta). >0 = primeiro (tempo); <=0 = segundo (recurso).
    """
    prof = _profile_or_none(deck_codes)
    dados = [(_cards_db.get(c) or {}) for c in deck_codes]
    dados = [d for d in dados if d and (d.get('type') or '').upper() != 'LEADER']
    if not dados:
        return {'goFirst': False, 'reason': 'deck desconhecido -> segundo (recurso)'}
    media = sum(d.get('cost', 0) for d in dados) / len(dados)

    score = 0.0
    partes = []
    # curva: baixa empurra pra tempo, alta pra recurso (centro ~3.5)
    curva_term = (3.5 - media) * 2.0
    score += curva_term
    partes.append(f'curva {media:.1f}({curva_term:+.1f})')

    if prof:
        mix = prof.get('archetype', {}).get('mix', {})
        roles = prof.get('roles', {})
        # arquetipo: Aggro puxa tempo; Controle/Ramp puxam recurso; Vida leve recurso
        arch_term = (mix.get('Aggro', 0) - mix.get('Controle', 0)
                     - mix.get('Tempo/Ramp', 0) * 0.5 - mix.get('Vida/Triggers', 0) * 0.3) / 15.0
        score += arch_term
        partes.append(f"arq({arch_term:+.1f})")
        # papeis: rush/evasive/beater = tempo; ramp/recursion/finisher = recurso
        tempo_roles = roles.get('rush', 0) + roles.get('evasive', 0) + roles.get('beater', 0) * 0.5
        recurso_roles = (roles.get('ramp', 0) + roles.get('recursion', 0)
                         + roles.get('finisher', 0) + roles.get('don_recovery', 0))
        papel_term = (tempo_roles - recurso_roles) * 0.15
        score += papel_term
        partes.append(f"papeis({papel_term:+.1f})")
        # eixo de combo caro (reanimacao) reforca "segundo"
        if any(a.get('kind') == 'bottleneck' for a in prof.get('derived_axes', [])):
            score -= 1.0
            partes.append('combo(-1.0)')

    go_first = score > 0
    return {'goFirst': go_first,
            'reason': f"score {score:+.1f} [{', '.join(partes)}] -> "
                      + ('PRIMEIRO (tempo)' if go_first else 'SEGUNDO (recurso)')}


def _profile_or_none(deck_codes: list[str]):
    """Perfil do deck (deck_profile) ou None se indisponivel — guardado."""
    try:
        from deck_profile import build_profile_from_codes
        return build_profile_from_codes([c for c in deck_codes
                                         if (_cards_db.get(c) or {}).get('type', '').upper() != 'LEADER'])
    except Exception:
        return None


def _card_intent(zone: str, card: Card, reason: str) -> dict:
    return {
        "action": "click_card",
        "zone": zone,
        "code": getattr(card, "code", ""),
        "name": getattr(card, "name", ""),
        "reason": reason,
    }


_OCR_FIXES: list[tuple[str, str]] = [
    # erros de reconhecimento de letras em palavras-chave de prompt
    (r'\bTras\b',     'Trash'),
    (r'\bTrah\b',     'Trash'),
    (r'\bCaracter\b', 'Character'),
    (r'\bCharater\b', 'Character'),
    (r'\bChose\b',    'Choose'),
    (r'\bEnemys?\b',  'Opponent'),
    (r'\bOpponent\b', 'Opponent'),  # normaliza maiusculas
    (r'\bYours?\b',   'your'),
    (r'\b(\d+)\s+Cards?\b', r'\1 card'),  # "1 Cards" -> "1 card"
    (r'\bUp To\b',    'up to'),
]

import re as _re


def resolve_trigger_choice(gs: GameState, card_code: str | None,
                           opp_gs: GameState | None = None) -> bool:
    """
    Decide se o bot deve usar o Trigger Effect de uma carta revelada da vida.

    NAO usar o trigger = a carta vai para a MAO (counter/corpo garantido).
    Usar = efeito resolve e a carta vai pro trash. Entao o efeito precisa
    valer MAIS que a carta na mao:
      - KO / bounce / play_card / give_don / rest / debuff -> ganho real, usa
      - draw seco -> troca carta conhecida por carta aleatoria: NAO usa
        (partida 06/07: Sanjuan Wolf trigou por draw + buff situacional
        inutil naquela fase — era melhor +1 counter na mao)
      - activate_main_effect (trigga o proprio on-KO) -> usa so se o on-KO
        tem ganho real no campo atual (on_ko_value >= 25)
      - Trash da mao / da vida -> so se o custo cabe
      - Sem trigger declarado ou desconhecido -> NAO usa (carta na mao)
    """
    if not card_code:
        return True

    # ATENCAO: efeitos ficam aninhados sob 'effects' no card_effects_db —
    # get_card_effects resolve isso (leitura direta de _effects_db[code]['trigger']
    # sempre devolvia {} e o bot NUNCA usava trigger; bug corrigido 04/07/2026)
    from optcg_engine.decision_engine import get_card_effects, on_ko_value
    trigger_steps = get_card_effects(card_code).get('trigger', {}).get('steps', [])

    if not trigger_steps:
        return False  # sem trigger declarado (ex: carta com counter mas sem trigger)

    for step in trigger_steps:
        action = step.get('action', '')
        if action in ('ko', 'bounce', 'give_don', 'rest_opp',
                      'rest_opp_character', 'play_card', 'play_from_trash',
                      'debuff_power'):
            return True
        if action == 'activate_main_effect':
            # Em EVENTO, este trigger significa "jogue o [Main] de graça"
            # (ex: Are At Your Service — search). A régua antiga (on_ko_value,
            # feita pro padrão de PERSONAGEM que trigga o próprio on-KO) dá 0
            # pra evento → recusava sempre — achado real 12/07 (partida
            # 15.27.45): a busca grátis foi pra mão, onde um evento sem
            # [Counter] não é rede de segurança (sem stat de counter; usar
            # depois custa DON + main phase) e a carta usada ainda alimenta
            # o trash (recurso deste deck). Usa se o main PRODUZ algo agora
            # (mesma régua _step_is_viable do resto do motor); evento COM
            # bloco [Counter] continua indo pra mão (defesa futura > efeito
            # grátis agora).
            data_ev = _cards_db.get(card_code) or {}
            if (data_ev.get('type') or '').upper() == 'EVENT':
                effects_ev = get_card_effects(card_code)
                if effects_ev.get('counter'):
                    return False
                main_steps = effects_ev.get('main', {}).get('steps', [])
                if not main_steps:
                    return False
                from optcg_engine.decision_engine import EffectExecutor
                opp_stub = opp_gs if opp_gs is not None else GameState(leader=deepcopy(gs.leader))
                ee_trig = EffectExecutor(gs, opp_stub)
                card_obj = _make_card(card_code, data_ev)
                return any(ee_trig._step_is_viable(s, card_obj) for s in main_steps)
            return on_ko_value(card_code, opp_gs, owner=gs) >= 25
        if action in ('trash', 'trash_from_hand', 'discard'):
            return len(gs.hand) > 0
        if action == 'trash_life':
            return len(gs.life) > 1

    return False  # draw seco / buff situacional / desconhecido: carta na mao


def select_counter_cards(gs: GameState, atk_power: int, def_power: int,
                         opp_gs: GameState | None = None,
                         defender_uid: int = 0) -> list[int]:
    """
    Seleciona as cartas de counter (por _deck_uid) para defender um ataque.
    Mesma politica do DecisionEngine.use_counter: menores primeiro, minimo
    necessario — e so counteriza se realmente cobre o ataque.
    Retorna [] se o engine decidir nao counterizar.

    defender_uid: uid do alvo do ataque. Quando aponta pra um PERSONAGEM
    (nao o lider), a decisao de counterizar troca de eixo -- nao e sobre
    vida, e sobre TROCA de recursos: so vale gastar counter(s) se o valor
    do personagem defendido supera o valor das cartas de counter gastas.
    Achado real 09/07 (log 18.39.46): bot gastou 2 eventos [Counter] pra
    salvar 1 personagem de baixo valor de um unico ataque, esvaziando a
    mao por pouco ganho -- should_use_counter usava o MESMO gate baseado
    em vida do lider pra decidir defender um personagem qualquer, que nao
    tem nada a ver com a vida do jogador.

    Cobre DOIS tipos de counter, na MESMA regua (poder que a carta
    adiciona contra este ataque especifico):
    - Character com stat de Counter impresso (c.counter > 0) — ja existia.
    - EVENT com bloco [Counter] "gains +X power during this battle/turn"
      (ex: OP13-098 Imu "...Never Existed..." +4000) — achado real 09/07:
      o motor JA TEM toda a logica de avaliacao desses eventos
      (EffectExecutor.try_counter_event_power/_check_conditions/
      _counter_event_cost_payable), so nunca era chamada neste caminho AO
      VIVO — a IA jogando Imu nunca usava os proprios counters de evento,
      só os counters de personagem. Reaproveita os dados JA PARSEADOS
      (get_card_effects) em modo SO LEITURA (sem mutar estado — a mutacao
      de verdade acontece no jogo real quando o C# descarta a carta),
      diferente de try_counter_event_power (que muta o GameState pro
      simulador interno). Escopo: so o padrao mais comum, "Leader/
      Character ganha +X de poder" incondicional de QUAL personagem
      (leader/own_character/leader_or_character) — cobre o caso reportado
      sem precisar saber qual carta especifica esta sendo atacada (o
      /defense "counter" nao recebe esse contexto ainda).
    """
    opp_stub = opp_gs if opp_gs is not None else GameState(leader=deepcopy(gs.leader))
    engine = DecisionEngine(gs, opp_stub)

    from optcg_engine.decision_engine import (EffectExecutor, get_card_effects,
                                              effective_hand_play_cost)
    ee = EffectExecutor(gs, opp_stub)

    # (valor_counter, carta) — personagens (stat impresso) + eventos [Counter].
    # Montado ANTES do gate should_use_counter: esse gate decide "vale a
    # pena counterizar" a partir do total disponivel, que precisa incluir
    # os eventos tambem (senao rejeita ANTES de sequer considerar usar um
    # evento como unico counter disponivel — achado real 09/07).
    pool: list[tuple[int, 'Card']] = [(c.counter, c) for c in gs.hand if c.counter > 0]
    for event in gs.hand:
        if event.card_type != 'EVENT':
            continue
        block = get_card_effects(event.code).get('counter', {})
        if not block or not ee._check_conditions(block.get('conditions', {}), event):
            continue
        buff_step = next(
            (s for s in block.get('steps', [])
             if s.get('action') == 'buff_power'
             and s.get('duration') in ('battle_only', 'this_turn')
             and s.get('target') in ('leader', 'own_character', 'leader_or_character')),
            None)
        if buff_step is None:
            continue
        costs = block.get('costs', [])
        if not ee._counter_event_cost_payable(event, costs):
            continue
        # Custo da PROPRIA carta (DON ativo, o jogo resta ao ativar):
        # _counter_event_cost_payable so cobre custos extras do bloco.
        # O simulador interno (try_counter_event_power) ja checa e paga
        # isso; sem o espelho aqui o engine propunha o evento com 0 DON,
        # o jogo recusava o clique e o bot tomava o hit "achando que
        # defendeu" (classe do achado real 12/07, partida 14.30.52).
        if effective_hand_play_cost(gs, event) > gs.don_available:
            continue
        pool.append((buff_step.get('amount', 0), event))

    defender_char = None
    if defender_uid:
        defender_char = next((c for c in gs.field_chars
                              if getattr(c, '_deck_uid', 0) == defender_uid), None)

    needed = atk_power - def_power + 1
    if needed <= 0 or not pool:
        return []

    # Selecao unica pros dois casos (lider/personagem): cobre `needed`
    # minimizando o valor PERDIDO (pitch_cost_as_counter, que desconta o
    # papel de counter da carta — avaliar_carta puro deixava um Saturn
    # jogavel "barato" de pitchar e um evento counter "caro" de usar,
    # achado real 11/07).
    escolha, gasto, total = engine.pick_counters(needed, pool=pool)
    if total < needed:
        return []
    ids = [uid for c in escolha if (uid := getattr(c, '_deck_uid', 0))]

    if defender_char is not None:
        # Defendendo um PERSONAGEM: troca de recursos, nao vida. Sem
        # comparar com should_use_counter (que so faz sentido pro lider).
        valor_defendido = engine.analyzer.char_value_score(defender_char)
        return ids if valor_defendido > gasto else []

    if not engine.should_use_counter(atk_power, def_power,
                                     counter_avail=total, gasto=gasto):
        return []
    return ids


def resolve_reaction(gs: GameState, opp_gs: GameState,
                     atk_power: int, def_power: int,
                     defender_uid: int = 0) -> bool:
    """
    Efeito opcional com custo oferecido durante o ataque do oponente
    (ex: lider Teach — trash 1 carta da mao para REDIRECIONAR o ataque).

    Effect-aware, CASO A CASO (regra do usuario, 04/07/2026): nada de
    prioridade fixa — cada opcao de redirect e pontuada pelo GANHO LIQUIDO
    no campo atual (redirect_option_value):
    - sobrevivente = 0 (golpe anulado, nada perdido);
    - sacrificio = on_ko_value - valor da carta (Doc Q com on-KO rico pode
      valer MAIS que um sobrevivente — queremos o efeito);
    - lider = -life_redirect_cost (1 vida, pesa conforme a vida atual).
    Reage se [melhor opcao] + [o que o redirect SALVA no alvo original]
    paga o custo REAL da carta que seria trashada (nao mais um flat ~25 —
    achado 07/07: mao com personagens jogaveis bons vale MUITO mais que 25
    pelo `_trash_value` real, e o flat baixo fazia a reacao disparar fácil
    demais, esvaziando a mao ao longo da partida com cartas que valiam mais
    em campo).

    Guardas: ataque precisa estar ganhando; mao >= 2 (a ultima carta vale
    mais que 1 vida, salvo vida critica) — bot ficou de mao vazia pagando
    reacao toda rodada em partida real.
    """
    from optcg_engine.decision_engine import (redirect_option_value,
                                              life_redirect_cost, EffectExecutor)
    engine = DecisionEngine(gs, opp_gs)
    my_life = gs.life_count()

    # Log de diagnostico (07/07: auditoria manual offline nao e confiavel --
    # _trash_value depende de gs.don_available, que uma reconstrucao a
    # partir do Combat Log nao reproduz com precisao. Log ao vivo aqui e a
    # unica fonte confiavel dos numeros REAIS que levaram a decisao).
    def _log(motivo, resultado, **extra):
        partes = ' '.join(f'{k}={v}' for k, v in extra.items())
        print(f'[REACTION] atk={atk_power} def={def_power} life={my_life} '
              f'hand={len(gs.hand)} don_disp={gs.don_available} {partes} '
              f'-> {resultado} ({motivo})')
        return resultado

    if atk_power < def_power:
        return _log('ataque ja perde sozinho', False)

    # Se o custo do lider exige carta COM [Trigger] (ex: Teach OP16-080:
    # "trash 1 card with a [Trigger] from your hand"), so cartas com
    # has_trigger sao pagaveis de verdade -- sem isso o guard de "mao
    # pequena" e a estimativa de custo usavam a mao INTEIRA, subestimando
    # o custo real quando a carta mais barata da mao nao tinha Trigger
    # (nao seria nem opcao valida no jogo real). Achado real 10/07.
    from optcg_engine.decision_engine import get_card_effects
    leader_costs = get_card_effects(gs.leader.code).get('on_opp_attack', {}).get('costs', [])
    so_trigger = any(c.get('has_trigger') for c in leader_costs)
    pool = [c for c in gs.hand if c.has_trigger] if so_trigger else gs.hand

    if len(pool) < 2 and my_life > 1:
        return _log('mao pequena, vida nao critica', False)
    if not pool:
        return _log('sem carta elegivel pro custo', False)

    # Custo real: a carta mais barata de perder na mao (mesma régua usada
    # em _score_activate_main) — nao um numero fixo que ignora o que tem
    # na mao.
    ee = EffectExecutor(gs, opp_gs)
    custo_carta = min((ee._trash_value(c) for c in pool), default=25.0)

    # O que o redirect SALVA: o alvo original deixa de tomar o golpe
    defender_char = next((c for c in gs.field_chars
                          if getattr(c, '_deck_uid', 0) == defender_uid), None)
    if defender_char is not None:
        # personagem nosso ia morrer? salva o valor dele (se sobreviveria,
        # nao ha o que salvar)
        salva = (engine.analyzer.char_value_score(defender_char)
                 if atk_power >= defender_char.power else 0.0)
    else:
        salva = life_redirect_cost(my_life)   # alvo era o lider: salva 1 vida

    # Opcoes de redirect e seus ganhos liquidos
    opcoes = [redirect_option_value(c, atk_power, opp_gs, engine)
              for c in gs.field_chars
              if getattr(c, '_deck_uid', 0) != defender_uid]
    if defender_char is not None and my_life > 0:
        # mandar o golpe para o LIDER (so quando o alvo original e um char)
        opcoes.append(-life_redirect_cost(my_life))
    if not opcoes:
        return _log('sem alvo legal de redirect', False, custo_carta=round(custo_carta, 1))

    # Ataque no LIDER com a vida JA em 0: esse golpe ENCERRA O JOGO se
    # conectar (regra: tomar dano com vida 0 = derrota) -- nao e "perder
    # mais 1 vida", e perder a partida inteira. Nenhuma conta de ganho
    # liquido/custo de carta ou a guarda de "segurar a reacao pro ataque
    # maior" (abaixo) fazem sentido aqui -- nao existe "turno que vem" se
    # perdermos agora. Redireciona se existir QUALQUER alvo legal, mesmo
    # que va morrer sem on-KO bom. Achado em partida real 07/07: o bot
    # recusou o redirect exatamente no golpe que terminou o jogo, porque
    # life_redirect_cost(0) caia no mesmo teto (90) usado pra "custo de 1
    # carta" em vez de ser tratado como valor infinito/prioridade maxima.
    if defender_char is None and my_life == 0:
        return _log('vida 0, golpe letal -- redireciona sempre', True, opcoes=opcoes)

    ganho = max(opcoes) + salva
    if ganho < custo_carta:
        return _log('ganho < custo da carta', False,
                     custo_carta=round(custo_carta, 1), salva=round(salva, 1),
                     opcoes=[round(o, 1) for o in opcoes], ganho=round(ganho, 1))

    # A reacao e 1x POR TURNO: se ainda vem atacante MAIOR neste turno
    # (personagem ativo do oponente ou o lider dele em pe), gastar a reacao
    # num ataque pequeno de ganho marginal desperdica o uso no golpe grande
    # (visto em partida real 06/07: pagou no Jango 2000 e o Krieg 9000
    # entrou de graca). Ganho alto (ex: sacrificio de Doc Q com on-KO cheio)
    # continua valendo agora.
    por_vir = [c.power for c in opp_gs.field_chars if not getattr(c, 'rested', False)]
    if opp_gs.leader is not None and not getattr(opp_gs.leader, 'rested', False):
        por_vir.append(opp_gs.leader.power)
    maior_por_vir = max(por_vir, default=0)
    if maior_por_vir > atk_power and ganho < custo_carta * 2:
        return _log('segura reacao pro ataque maior que vem', False,
                     custo_carta=round(custo_carta, 1), ganho=round(ganho, 1),
                     maior_por_vir=maior_por_vir)

    return _log('aceita', True, custo_carta=round(custo_carta, 1),
                 salva=round(salva, 1), ganho=round(ganho, 1))


def resolve_optional_effect(gs: GameState, opp_gs: GameState,
                            actor_code: str | None = None) -> bool:
    """
    Efeito opcional com custo no PROPRIO turno (downside pos-play, ex:
    "you may trash 1 card: ..."). SEM heuristica propria -- delega pra
    `EffectExecutor._step_is_viable` + `_worth_paying_optional_costs`,
    exatamente o que `execute()` usa no simulador interno pra essa MESMA
    decisao. Achado real 09/07 (log 19.25.50): existiam DUAS reguas
    diferentes pra "vale pagar esse custo opcional" -- o caminho ao vivo
    nem sabia qual carta/efeito estava perguntando (aceitava sem checar
    se o beneficio tinha alvo, ex: Marcus Mars "K.O. cost<=5" sem nenhum
    personagem elegivel no campo do oponente) e ainda usava um corte de
    valor proprio, divergente do simulador. Violava a regra "sem dois
    motores" (memory/feedback_dois_motores.md) -- consolidado aqui.

    Achado real 10/07 (log 22.32.09, turno 4): a versao anterior deste fix
    so entrava no bloco de decisao se o custo fosse do tipo "sacrificio"
    (_SACRIFICE_COST_TYPES) -- custo SO de rest_don (ex: "...Never
    Existed..." OP13-098, "[Main] You may rest 1 DON: KO ate 1 Stage do
    oponente cost<=7") caia no fallback final e SEMPRE recusava, mesmo com
    alvo valido e efeito bom. Como nada muda no estado quando recusa, a
    MESMA ativacao de score alto era reoferecida a cada /decide seguinte
    -- travava o turno em loop (4x identico no log) sem nunca chegar nas
    jogadas de score mais baixo que sobravam na mao. execute() (linha
    ~1382) chama _worth_paying_optional_costs incondicionalmente pra
    on_play/main, sem filtrar por tipo de custo -- o filtro aqui era outra
    divergencia real dos dois motores, ja removido.

    actor_code: codigo da carta oferecendo o custo. Sem ele (contexto
    desconhecido), decide so pelo tamanho/qualidade da mao (fallback
    conservador — mesma regua de sacrificio, sem checar alvo do beneficio
    porque nao sabemos qual efeito e).
    """
    from optcg_engine.decision_engine import get_card_effects, EffectExecutor
    ee = EffectExecutor(gs, opp_gs)

    if not actor_code:
        return ee._worth_paying_optional_costs(
            [{'type': 'trash_from_hand'}], card=None)

    # Inclui lider e stage na busca: o prompt opcional mais frequente do Imu
    # e a habilidade do PROPRIO LIDER (activate_main, custo trash_char_or_hand)
    # -- achado real 11/07 (log 00.49.30): lider nunca aparecia em
    # hand+field_chars, caia no fallback generico que so olha a mao, e o bot
    # recusou o draw do lider TODOS os turnos apos o 1o (mao so com cartas
    # valiosas), mesmo tendo Shalria de 0 poder no campo pra pagar o custo.
    pool = list(gs.hand) + list(gs.field_chars) + [gs.leader]
    if getattr(gs, 'field_stage', None) is not None:
        pool.append(gs.field_stage)
    card_obj = next((c for c in pool if c is not None and c.code == actor_code), None)
    if card_obj is None:
        return ee._worth_paying_optional_costs(
            [{'type': 'trash_from_hand'}], card=None)

    effects = get_card_effects(actor_code)
    # 'activate_main' incluido -- e o gatilho do lider Imu e de stages; o loop
    # anterior (on_play/main) nao achava nada e retornava False sempre.
    for trig in ('on_play', 'main', 'activate_main'):
        ef = effects.get(trig)
        if not ef:
            continue
        custos = ef.get('costs', [])
        steps = ef.get('steps', [])
        if steps and not any(ee._step_is_viable(s, card_obj) for s in steps):
            return False
        return ee._worth_paying_optional_costs(custos, card_obj)

    return False


def order_target_candidates(gs: GameState, opp_gs: GameState,
                            candidates: list[dict],
                            attacker_power: int = 0,
                            defender_uid: int = 0,
                            actor_code: str | None = None) -> list[int]:
    """
    Ordena candidatos de alvo de um efeito pendente por preferencia.
    candidates: [{'id': uid, 'zone': 'own_hand'|'own_board'|'top_deck'|...,
                  'code': cardID (opcional)}]

    Heuristica por zona:
    - top_deck: melhor carta primeiro (search — vai para a mao)
    - own_hand: pior carta primeiro (descarte — choose_to_trash)
    - own_trash: melhor carta primeiro (recuperacao/play from trash)
    - own_board: menor valor primeiro (sacrificio/substituicao)
    - opp_board: maior valor primeiro (remocao/bounce)
    - opp_trash: melhor carta primeiro (negar recuperacao/exile)
    - leaders/stages: por ultimo

    attacker_power > 0 = efeito resolvendo DURANTE um ataque do oponente
    (ex: redirect do lider Teach). O proprio campo e o lider sao pontuados
    CASO A CASO pelo ganho liquido (redirect_option_value / custo de vida)
    — mesma conta do resolve_reaction, sem prioridade fixa: um Doc Q com
    on-KO rico pode vir antes de um sobrevivente, o lider pode vir antes de
    um sacrificio caro, etc. Alvo original SEMPRE por ultimo (redirecionar
    para ele e um no-op que paga o custo por nada).

    Cartas de trash/top_deck nao vem no DTO — o 'code' do candidato permite
    montar a carta do banco so para valorar.
    """
    engine = DecisionEngine(gs, opp_gs)

    # Engine "DON-neutro": mesma GameState, mas com don_available artificial
    # bem alto, so pra zerar o bonus/penalidade de jogabilidade imediata
    # dentro de avaliar_carta (+40 se pagavel agora / -15 se nao). Usado SO
    # pra valorar candidatos de BUSCA (zona top_deck, "olhe/pegue a melhor
    # carta"), onde nao existe custo diferencial entre as opcoes -- o
    # jogador so esta ESCOLHENDO, nao pagando por nenhuma delas ainda.
    # Achado real 09/07: Imu busca 1 stage [Mary Geoise] tipo de graca no
    # inicio do jogo (Empty Throne custo 7 vs Mary Geoise custo 1, 0 DON em
    # campo) -- avaliar_carta() penalizava Empty Throne por "nao pagavel
    # agora" numa escolha que nunca teve custo nenhum, entao o bot sempre
    # buscava a carta mais fraca e mais barata. Mesmo vies afeta QUALQUER
    # efeito de busca/look-and-play do jogo, nao so essa carta do Imu.
    gs_don_neutro = copy(gs)
    gs_don_neutro.don_available = 99
    engine_busca = DecisionEngine(gs_don_neutro, opp_gs)

    by_uid = {}
    for c in gs.hand + gs.field_chars + opp_gs.field_chars:
        uid = getattr(c, '_deck_uid', 0)
        if uid:
            by_uid[uid] = c

    def card_of(cand: dict):
        card = by_uid.get(cand.get('id'))
        if card is None and cand.get('code'):
            data = _cards_db.get(cand['code'])
            if data:
                card = _make_card(cand['code'], data)
        return card

    from optcg_engine.decision_engine import (redirect_option_value,
                                              life_redirect_cost,
                                              get_card_effects, on_ko_value,
                                              EffectExecutor)

    # O ATOR do efeito pendente e uma habilidade de REDIRECT de ataque de
    # verdade (redirect_attack_target em algum bloco dele)? Achado real
    # 08/07: attacker_power>0 so significa "estamos numa janela de ataque"
    # -- QUALQUER selecao de alvo que aconteca nessa janela (ex: um trigger
    # de vida como o Sanjuan Wolf, que so escolhe onde por +poder, nada a
    # ver com redirecionar o ataque) reutilizava as heuristicas de redirect
    # abaixo (own_hand/own_board/own_leader), tratando um efeito
    # completamente nao-relacionado como se fosse "quanto vale sacrificar
    # isso pra pagar o redirect" -- gerava escolha de alvo sem sentido pra
    # qualquer carta cujo prompt calhasse de aparecer durante um ataque.
    # Sem isto, so o CODIGO do ator sendo resolvido, nao o contexto de
    # janela, deve decidir se as heuristicas de redirect valem.
    actor_is_redirect = False
    if actor_code:
        for block in get_card_effects(actor_code).values():
            if any(s.get('action') == 'redirect_attack_target' for s in block.get('steps', [])):
                actor_is_redirect = True
                break

    # Redirect: o alvo original e um personagem NOSSO? (lider como escape)
    defender_is_own_char = (
        attacker_power > 0 and actor_is_redirect and defender_uid
        and any(getattr(c, '_deck_uid', 0) == defender_uid for c in gs.field_chars))

    # O efeito resolvendo e um COPY-POWER (ex: Devon OP16-104: "base power
    # becomes the same as the selected Character's")? Entao o alvo certo no
    # campo do oponente e o de MAIOR PODER, nao o de maior valor.
    actor_copia_poder = False
    if actor_code:
        wa = get_card_effects(actor_code).get('when_attacking', {})
        actor_copia_poder = any(
            s.get('action') == 'set_base_power'
            and s.get('source') == 'selected_opp_character'
            for s in wa.get('steps', []))

    # O efeito resolvendo e um debuff de poder no oponente (duration
    # tipicamente 'this_turn', ex: Van Augur on-KO)? A ordenacao generica de
    # opp_board (linha ~601) e feita pra REMOCAO (maior valor, sem olhar
    # rested) e opp_leader cai no catch-all de prioridade baixa -- pra esse
    # tipo de efeito o lider e um alvo tao valido quanto um personagem, e um
    # alvo JA RESTADO (ja atacou este turno) nunca aproveita o debuff.
    # Achado em partida real 07/07: Van Augur debuffou -3000 num personagem
    # que ja tinha atacado, quando o lider do oponente ainda estava ativo.
    actor_debuff_swing = False
    if actor_code and not actor_copia_poder:
        for block in get_card_effects(actor_code).values():
            if any(s.get('action') == 'debuff_power' for s in block.get('steps', [])):
                actor_debuff_swing = True
                break

    # O ator resolvendo e um AUTO-BUFF de poder fixo em "seu lider OU seu
    # personagem" (ex: Sanjuan Wolf on-KO: "up to 1 of your Leader or
    # Character's power becomes 7000")? Lider e personagem competem pelo
    # MESMO papel aqui (nao e remocao nem redirect). Guarda o AMOUNT (valor
    # fixo, ex: 7000) pra poder comparar contra o ataque em andamento.
    # Achado real 08/07: sem regra dedicada, o lider caia no catch-all
    # generico (baixa prioridade) e um personagem fraco de custo 1 quase
    # sempre "ganhava" por estar em own_board (prioridade 3) contra
    # own_leader (prioridade 6) -- nao porque fosse a melhor escolha, so
    # porque a zona dele tinha prioridade estrutural maior.
    # ('set', valor_fixo) pra "power becomes N" (Sanjuan Wolf) ou
    # ('delta', +1000*count) pra "give up to N DON!!" (Bartholomew Kuma —
    # cada DON anexado vale +1000 de poder permanente, mesmo restado).
    # Mesmo alvo estrutural nos dois casos (lider OU 1 personagem proprio),
    # so muda a conta de quanto poder resulta.
    actor_self_power_target = None
    if actor_code and not actor_copia_poder and not actor_debuff_swing:
        for block in get_card_effects(actor_code).values():
            for s in block.get('steps', []):
                if (s.get('action') == 'set_base_power'
                        and s.get('target') in ('leader_or_own_character', 'leader_or_character')):
                    actor_self_power_target = ('set', s.get('amount', 0))
                    break
                # buff_power e DELTA (+X), nao "vira X" — tratado como 'set'
                # fazia o Never Existed (+4000) parecer "power vira 4000" e
                # a regra preferia o alvo mais FRACO; ao vivo (12/07,
                # 23.41.50) o buff foi no Mars parado em vez do LIDER que
                # estava levando o golpe, e o bot pagou +2000 de counter
                # por cima pra sobreviver.
                if (s.get('action') == 'buff_power'
                        and s.get('target') in ('leader_or_own_character', 'leader_or_character')):
                    actor_self_power_target = ('delta', s.get('amount', 0))
                    break
                if s.get('action') == 'give_don':   # give_don_opp e acao distinta, ja exclusiva
                    actor_self_power_target = ('delta', s.get('count', 1) * 1000)
                    break
            if actor_self_power_target is not None:
                break

    # O ator so tem steps que miram o lado do OPONENTE (ex: OP09-093 Teach —
    # "negate the effect of up to 1 of your opponent's Character")? Entao
    # NENHUMA zona own_* e alvo valido nunca, pra QUALQUER carta com esse
    # padrao -- sem essa deteccao, o bot clicava candidato por candidato
    # (own_hand e own_board vem primeiro nas zonas genericas, prioridade
    # 1 e 3) so pra o jogo ignorar cada clique invalido, um por tick
    # (~0,8s), ate finalmente chegar num alvo opp_* valido. Achado real
    # 08/07: usuario reportou ter precisado escolher o alvo manualmente —
    # o bot NAO tinha travado, so estava visivelmente lento clicando lixo
    # primeiro. Generico: olha os targets declarados de TODOS os blocos do
    # ator: se todos comecam com 'opp', nenhuma zona own_* compete.
    actor_opp_only = False
    if actor_code and not (actor_copia_poder or actor_debuff_swing
                            or actor_self_power_target is not None):
        alvos = [s.get('target', '') for block in get_card_effects(actor_code).values()
                 for s in block.get('steps', []) if s.get('target')]
        if alvos and all(t.startswith('opp') for t in alvos):
            actor_opp_only = True

    # O ator tem CUSTO "trash 1 Character seu OU 1 carta da mao"
    # (trash_char_or_hand — ex: draw do lider Imu)? Entao own_board e
    # own_hand competem pelo MESMO papel (o que doi menos perder) e a
    # prioridade estrutural por zona (own_hand=1 < own_board=3) esta
    # ERRADA: o bot pagava o custo TODO turno com carta da MAO (ate
    # Saturn jogavel), com a Shalria de 0 poder ja usada parada no campo
    # — reclamacao real 12/07 (3a partida), "nao trashou a Shalria pro
    # draw". Independente das deteccoes acima (olha CUSTOS, nao steps).
    actor_trash_cost = False
    if actor_code:
        for block in get_card_effects(actor_code).values():
            if any((c.get('type') or '').startswith('trash_char')
                   for c in block.get('costs', [])):
                actor_trash_cost = True
                break

    # O ator resolvendo e um "JOGUE uma carta da mao" (ex: Empty Throne
    # OP13-099: play 1 black Five Elders da mao)? Entao o prompt de own_hand
    # e de INTENCAO OPOSTA a de descarte: a regua _trash_value (protege carta
    # boa = poe ela por ULTIMO) faria o plugin clicar primeiro na carta mais
    # DESCARTAVEL — achado real 11/07 (log 00.49.30): com um evento inelegivel
    # ranqueado primeiro, o jogo recusou o clique e o deploy fizzlou (3 DON +
    # stage restados por nada), mesmo com Ju Peter elegivel na mao. Aqui:
    # elegiveis primeiro, por valor de jogo DESCENDENTE; inelegiveis por
    # ultimo (nunca clicar neles).
    actor_play_step = None
    if actor_code and not (actor_copia_poder or actor_debuff_swing
                            or actor_self_power_target is not None or actor_opp_only):
        for block in get_card_effects(actor_code).values():
            for s in block.get('steps', []):
                if s.get('action') == 'play_card' and s.get('source') != 'self':
                    actor_play_step = s
                    break
            if actor_play_step is not None:
                break

    def _elegivel_para_play(card) -> bool:
        if card is None or actor_play_step is None:
            return False
        s = actor_play_step
        if card.card_type != (s.get('card_type') or 'CHARACTER').upper():
            return False
        ft = (s.get('filter_type') or '').lower()
        if ft and ft not in (card.sub_types or '').lower():
            return False
        fcolor = (s.get('color') or '').lower()
        if fcolor and fcolor not in (card.color or '').lower():
            return False
        cost_lte = s.get('cost_lte')
        if cost_lte == 'don_count_self':
            cost_lte = gs.don_available + gs.don_rested
        return cost_lte is None or card.cost <= cost_lte

    def sort_key(cand: dict):
        card = card_of(cand)
        zone = cand.get('zone', '')
        if actor_opp_only and zone.startswith('own'):
            return (9, 0)   # nunca e alvo valido pra essa habilidade
        if actor_copia_poder:
            if zone == 'opp_board':
                # copy-power: maior poder = maior ataque copiado. Precisa vir
                # antes de zonas genericas, mesmo durante a janela de ataque.
                return (0, -(card.effective_power(False) if card else 0))
            return (8, 0)
        if actor_debuff_swing and zone in ('opp_board', 'opp_leader'):
            rested = bool(getattr(card, 'rested', False)) if card else True
            valor = engine.analyzer.char_value_score(card) if card else 0
            return (0 if not rested else 1, -valor)
        if actor_self_power_target is not None and zone in ('own_board', 'own_leader'):
            # own_leader nao vem no by_uid (so hand/field_chars/opp field_chars)
            # -- usa o lider AO VIVO pra refletir DON/buffs atuais, nao uma
            # reconstrucao "de fabrica" a partir so do codigo da carta.
            live = gs.leader if zone == 'own_leader' else card
            p = live.effective_power(True) if live else 0
            kind, amount = actor_self_power_target
            resultante = amount if kind == 'set' else p + amount

            # JANELA DE DEFESA (buff resolvendo durante ataque do oponente,
            # ex: [Counter] do Never Existed): o alvo certo e quem esta
            # LEVANDO o golpe, se o buff o salva — buffar outro corpo nao
            # muda o combate em andamento (achado real 12/07: +4000 no Mars
            # parado com o lider sob ataque de 7000).
            if attacker_power > 0:
                eh_defensor = ((defender_uid and cand.get('id') == defender_uid)
                               or (not defender_uid and zone == 'own_leader'))
                # perdendo agora e salvo pelo buff -> regra de combate do MOTOR
                # unico (empate vai pro atacante), nao regua propria aqui
                if eh_defensor and engine.buff_wins_combat(p, attacker_power, resultante):
                    return (-2, 0)

            # O lider tem uma ameaca REAL no campo do oponente (personagem ou
            # lider dele ainda ATIVO, nao restado) que ele hoje NAO sobrevive
            # mas SOBREVIVERIA com o boost/delta? Isso vale mais que qualquer
            # outro criterio -- prioridade maxima. NAO usa `attacker_power>0`
            # aqui (tentativa anterior, 08/07 bloco 107): esse parametro so
            # vem preenchido pelo C# durante Attack_WaitOnBlocker/
            # BeforeBlocker/WaitOnCounters -- triggers de vida e on-plays
            # (os casos reais do Sanjuan Wolf e do Kuma) resolvem o alvo fora
            # dessa lista de estados, entao attacker_power chegava sempre 0 e
            # a regra nunca disparava (confirmado no log do plugin). Mesma
            # conta de `maior_por_vir` do resolve_reaction, mas lida direto
            # do estado do oponente em vez de um parametro que nem sempre
            # reflete o contexto real.
            if zone == 'own_leader':
                ameacas = [c.power for c in opp_gs.field_chars if not getattr(c, 'rested', False)]
                if opp_gs.leader is not None and not getattr(opp_gs.leader, 'rested', False):
                    ameacas.append(opp_gs.leader.power)
                maior_ameaca = max(ameacas, default=0)
                # EMPATE vai pro ATACANTE no OPTCG: um lider em poder IGUAL a
                # ameaca TOMA o golpe, e o buff so salva se ficar ESTRITAMENTE
                # acima -> MESMA regra de combate do motor (buff_wins_combat),
                # nao regua propria. Antes esta usava `p < ... <= ...` (empate
                # nos dois lados) e nao disparava no caso real (Kaido 5000 vs
                # lider 5000): o buff ia pro personagem ATIVO mais forte em vez
                # do lider sob ataque (achado ao vivo 13/07, log 21.01.22).
                if engine.buff_wins_combat(p, maior_ameaca, resultante):
                    return (-1, 0)

            if kind == 'set':
                # Fixar um valor alto beneficia mais quem estava mais fraco
                # (maior delta ganho) -- prefere MENOR poder atual.
                return (3, p)
            # 'delta' (ex: give_don): o ganho de poder e o MESMO (+1000*N)
            # em qualquer alvo -- nao ha "quem se beneficia mais". O que
            # importa e nao desperdicar num alvo que nem vai brigar este
            # turno. Achado real 09/07 (Kuma): o proprio ator, recem-jogado
            # (just_played, sem Rush, nao ataca este turno), "ganhava" so
            # por ser o unico candidato em own_board -- sem comparar com o
            # lider, que compete por ataques/defesas TODO turno. Prioriza
            # quem NAO acabou de entrar (lider nunca tem just_played) nem
            # ja atacou (restado = DON anexado volta no refresh sem nunca
            # ter valido nada). Desempate: MAIOR poder efetivo -- achado
            # real 11/07 (Kuma de novo): lider 5000 e Shalria 0 empatavam
            # em (3, 0) e a ordem dos candidatos decidia; o DON foi parar
            # na Shalria de 0 poder, cujo ataque buffado continua morrendo
            # pra qualquer corpo, em vez do lider.
            desperdicado = (getattr(live, 'just_played', False)
                            or getattr(live, 'rested', False))
            return (3, 1 if desperdicado else 0, -p)
        # Contexto de ataque: alvo original sempre por ULTIMO, em qualquer zona
        # (so faz sentido pra uma habilidade de redirect de verdade -- ver
        # actor_is_redirect acima)
        if attacker_power > 0 and actor_is_redirect and defender_uid and cand.get('id') == defender_uid:
            return (9, 0)
        if zone == 'top_deck':
            return (0, -(engine_busca.avaliar_carta(card) if card else 0))
        if zone == 'own_hand':
            # Prompt de JOGAR da mao (ver actor_play_step acima): melhor
            # carta ELEGIVEL primeiro; inelegivel nunca.
            if actor_play_step is not None:
                if _elegivel_para_play(card):
                    return (0, -(engine.avaliar_carta(card)))
                return (9, 0)
            # SEMPRE _trash_value (protege carta cara/jogavel em breve,
            # sacrificio real vs teorico), nunca avaliar_carta puro. Achado
            # 07/07 corrigiu isso so pro caso de redirect do lider Teach --
            # deixou o caso GERAL (ex: custo "trash 1 da mao" do lider Imu)
            # ainda usando avaliar_carta, que nao tem a protecao de carta
            # cara (cost>=7). Achado real 09/07, comparando logs do usuario
            # jogando Imu vs o bot jogando Imu: o bot trashava Five Elders
            # (custo 10, a carta MAIS importante do deck) no turno 1 do
            # proprio custo do lider, porque avaliar_carta(Five Elders)=45
            # < avaliar_carta(qualquer carta barata) -- o usuario NUNCA
            # trashava Five Elders pelo lider em nenhuma partida real.
            ee_tmp = EffectExecutor(gs, opp_gs)
            return (1, ee_tmp._trash_value(card) if card else 0)
        if zone == 'own_trash':
            return (2, -(engine.avaliar_carta(card) if card else 0))
        if zone == 'own_board':
            if attacker_power > 0 and actor_is_redirect:
                # ganho liquido caso a caso; desempate: maior poder segura
                # golpes maiores
                valor = redirect_option_value(card, attacker_power, opp_gs,
                                              engine) if card else -999
                return (3, -valor, -(getattr(card, 'power', 0) if card else 0))
            if actor_trash_cost:
                # custo trash_char_or_hand: MESMO tier da mao (1); a perda
                # situacional (dead-weight barato, recem-entrado/blocker/ultimo
                # defensor caros) e decidida pelo MOTOR UNICO, sem regua propria
                # aqui (achado real 12/07 + 14/07: ver trash_cost_board_perda).
                return (1, engine.trash_cost_board_perda(card, gs))
            return (3, engine.analyzer.char_value_score(card) if card else 0, 0)
        if zone == 'own_leader':
            if defender_is_own_char and gs.life_count() > 0:
                # mandar o golpe para o lider = pagar vida (mesma conta do
                # resolve_reaction) — compete de igual com os personagens
                return (3, life_redirect_cost(gs.life_count()), 0)
            return (6, 0, 0)
        if zone == 'opp_board':
            # remocao: valor do alvo DESCONTADO do on-KO dele (KO-zar um
            # personagem com on-KO rico presenteia o efeito ao oponente)
            valor = engine.analyzer.char_value_score(card) if card else 0
            ko_deles = on_ko_value(card.code, gs, owner=opp_gs) if card else 0
            return (4, -(valor - ko_deles))
        if zone == 'opp_trash':
            return (5, -(engine.avaliar_carta(card) if card else 0))
        return (6, 0)

    return [c.get('id') for c in sorted(candidates, key=sort_key)]


def get_card_on_play_steps(card_code: str) -> list[dict]:
    """
    Retorna a lista de steps do efeito on_play de uma carta a partir do
    card_effects_db.json. Cada step tem 'action', 'target', 'count' e filtros
    (cost_lte, cost_eq, power_lte, rested_only, etc.).

    Usado pelo bot para saber quais prompts esperar ANTES que apareçam, e
    para filtrar alvos corretamente ao responder cada prompt.
    """
    from optcg_engine.decision_engine import get_card_effects
    return get_card_effects(card_code).get('on_play', {}).get('steps', [])


def _step_matches_zone(step: dict, zone: str) -> bool:
    """Heuristica: o step corresponde à zona detectada pelo OCR?"""
    target = step.get('target', '')
    action = step.get('action', '')
    if zone == 'opp_field':
        return 'opp' in target or action in ('ko', 'bounce', 'rest_opp')
    if zone == 'own_field':
        return target in ('self', 'own_character', 'character') or action in ('buff_power', 'rest')
    if zone == 'hand':
        return 'hand' in target or action in ('trash', 'discard', 'return_to_hand')
    if zone == 'trash':
        return 'trash' in target or action in ('draw_from_trash', 'play_from_trash')
    if zone == 'don':
        return action in ('give_don', 'trash_don', 'rest_don')
    return False


def _choose_opp_target_filtered(candidates: list, step: dict):
    """
    Escolhe o melhor alvo oponente aplicando os filtros do step:
      - cost_lte / cost_gte / cost_eq
      - power_lte / power_gte
      - rested_only

    Para ação 'ko': prefere alvo de maior board_value (mais ameaçador).
    Para ação 'bounce': prefere alvo de maior custo (mais valor devolvido).
    """
    if not candidates:
        return None

    filtered = list(candidates)

    cost_lte = step.get('cost_lte')
    cost_gte = step.get('cost_gte')
    cost_eq  = step.get('cost_eq')
    pwr_lte  = step.get('power_lte')
    pwr_gte  = step.get('power_gte')
    rested   = step.get('rested_only', False)

    if cost_lte is not None:
        filtered = [c for c in filtered if getattr(c, 'cost', 0) <= cost_lte]
    if cost_gte is not None:
        filtered = [c for c in filtered if getattr(c, 'cost', 0) >= cost_gte]
    if cost_eq is not None:
        filtered = [c for c in filtered if getattr(c, 'cost', 0) == cost_eq]
    if pwr_lte is not None:
        filtered = [c for c in filtered if getattr(c, 'power', 0) <= pwr_lte]
    if pwr_gte is not None:
        filtered = [c for c in filtered if getattr(c, 'power', 0) >= pwr_gte]
    if rested:
        filtered = [c for c in filtered if getattr(c, 'rested', False)]

    if not filtered:
        return None  # nenhum alvo valido com os filtros → prompt vai ser cancelavel

    action = step.get('action', '')
    if action == 'bounce':
        return max(filtered, key=lambda c: getattr(c, 'cost', 0))
    # ko, rest_opp, debuff: prioriza maior ameaça
    return max(filtered, key=lambda c: c.board_value() if hasattr(c, 'board_value') else 0)


def _normalize_prompt(raw: str) -> str:
    """Corrige erros tipicos de OCR em textos de prompt do OPTCGSim."""
    text = raw
    for pattern, repl in _OCR_FIXES:
        text = _re.sub(pattern, repl, text, flags=_re.IGNORECASE)
    return " ".join(text.lower().split())


def _prompt_zone(text: str) -> str:
    """
    Detecta a zona/tipo do prompt a partir do texto OCR do painel direito.
    Ordem importa: mais especificos primeiro.
    """
    # DON: "Select/Rest 1 DON!! card"
    if _re.search(r'\bdon\b', text):
        return "don"
    # Deck order: "Drag to Choose Bottom of Deck Order", "Return Cards to Deck"
    if _re.search(r'(bottom of deck|deck order|return cards|drag to choose)', text):
        return "deck_order"
    # Trash area: "Choose X cards from your Trash"
    if _re.search(r'\btrash\b', text) and _re.search(r'(from|in|your)\s+(your\s+)?trash', text):
        return "trash"
    # Mao: "Trash/Choose 1 card from your hand"
    if _re.search(r'\b(from|in|your)\s+(your\s+)?hand\b', text):
        return "hand"
    # Campo oponente: "Choose opponent's Character"
    if _re.search(r'\bopponent\b', text) or _re.search(r'\benemy\b', text):
        return "opp_field"
    # Campo proprio: "Choose your Character" / "Select 1 More Friendly Targets"
    if _re.search(r'\b(your|own|friendly)\s+(character|field|target)\b', text):
        return "own_field"
    # Cartas reveladas: "Look at top 3", "Reveal up to 1"
    if _re.search(r'\b(reveal|top of (your )?deck|look at)\b', text):
        return "revealed"
    # Blocker step: "Blocker Step" — oponente atacou, decidir bloqueador
    if "blocker step" in text or "blocker" in text:
        return "blocker"
    # Counter step: "Counter Step" — decidir se joga counter
    if "counter step" in text:
        return "counter"
    # Vida: "Choose 1 life card"
    if _re.search(r'\blife\b', text):
        return "life"
    return "unknown"


def _prompt_count(text: str) -> int:
    """Extrai contagem numerica do prompt (0 = nenhum alvo valido)."""
    m = _re.search(r'\b(choose|select)\s+0\b', text)
    if m:
        return 0
    m = _re.search(r'\bup to\s+(\d+)\b', text)
    if m:
        return int(m.group(1))
    m = _re.search(r'\b(choose|select|trash|rest)\s+(\d+)\b', text)
    if m:
        return int(m.group(2))
    return 1  # default: 1 alvo


def resolve_prompt_choice(gs: GameState, opp_gs: GameState,
                          prompt_text: str,
                          steps: list[dict] | None = None) -> Optional[dict]:
    """
    Traduz um prompt visual do OPTCGSim em uma intencao clicavel.

    Logica generica: detecta ZONA + ACAO + CONTAGEM pelo texto OCR.
    Se `steps` for passado (lista de steps do on_play da carta recém-jogada),
    usa filtros de alvo mais precisos (cost_lte, rested_only, etc.) antes de
    cair no fallback genérico.
    Nenhuma referencia a carta especifica — toda decisao vai para o engine.
    """
    text = _normalize_prompt(prompt_text or "")
    if not text:
        return None

    engine = DecisionEngine(gs, opp_gs)

    # --- Nenhum alvo valido (count = 0) ----------------------------------
    if _prompt_count(text) == 0:
        return {"action": "click_button", "prefer": "main", "reason": "count=0 no targets"}

    zone = _prompt_zone(text)

    # --- Usa steps do on_play para filtrar alvos mais precisamente -------
    if steps:
        matched_step = next(
            (s for s in steps if _step_matches_zone(s, zone)),
            None
        )
        if matched_step:
            action = matched_step.get('action', '')
            if zone == 'opp_field':
                chosen = _choose_opp_target_filtered(opp_gs.field_chars, matched_step)
                if chosen:
                    return _card_intent("opp_board", chosen,
                                        f"step:{action} filtered")
                # Sem alvo valido com filtros → cancela (efeito opcional)
                return {"action": "click_button", "prefer": "main",
                        "reason": f"no valid opp target for {action}"}
            if zone == 'own_field':
                if action in ('trash', 'ko'):
                    chosen = (min(gs.field_chars, key=lambda c: c.board_value())
                              if gs.field_chars else None)
                else:
                    chosen = choose_highest_board_value(gs.field_chars)
                if chosen:
                    return _card_intent("own_board", chosen, f"step:{action}")
            if zone == 'hand':
                count = matched_step.get('count', 1)
                chosen = engine.choose_to_trash(gs.hand)
                if chosen:
                    return _card_intent("hand", chosen, f"step:{action} count={count}")

    # --- DON: pagar custo de Activate:Main ("Select/Rest 1 DON") --------
    if zone == "don":
        return {"action": "click_don", "reason": "pay activate don cost"}

    # --- Blocker Step: oponente atacou — sem bloqueador por ora -----------
    if zone == "blocker":
        return {"action": "click_button", "prefer": "main", "reason": "no blocker"}

    # --- Counter Step: engine decide se joga counter ----------------------
    if zone == "counter":
        # Tenta escolher melhor counter da mao (carta com counter value)
        counters = [c for c in gs.hand if getattr(c, 'counter', 0) > 0]
        if counters:
            best = max(counters, key=lambda c: getattr(c, 'counter', 0))
            return _card_intent("hand", best, "play counter")
        return {"action": "click_button", "prefer": "main", "reason": "no counter/resolve attack"}

    # --- Trash zone: usa gs.trash rastreado pelo log ---------------------
    if zone == "trash":
        if gs.trash:
            # Engine escolhe melhor carta do trash (maior board_value)
            best = max(gs.trash, key=lambda c: c.board_value())
            return _card_intent("trash", best, "choose from trash")
        return {"action": "click_button", "prefer": "main", "reason": "trash empty"}

    if zone == "revealed":
        return {"action": "click_button", "prefer": "main", "reason": "revealed zone confirm"}
    if zone == "life":
        return {"action": "click_button", "prefer": "main", "reason": "life confirm"}
    # Ordenar deck ("Drag to Choose Bottom of Deck Order" / "Return Cards to Deck")
    if zone == "deck_order":
        return {"action": "click_button", "prefer": "main", "reason": "accept deck order"}

    # --- Confirmacoes sem escolha real -----------------------------------
    _CONFIRM_KWS = ("draw", "confirm", "ok", "place on top", "place on bottom",
                    "add to hand", "remaining", "rest of", "use card action", "cancel")
    if any(kw in text for kw in _CONFIRM_KWS):
        return {"action": "click_button", "prefer": "main", "reason": "confirm prompt"}

    # --- Mao: descarte/trash da mao -------------------------------------
    if zone == "hand" or ("trash" in text and "hand" in text):
        chosen = engine.choose_to_trash(gs.hand)
        if chosen:
            return _card_intent("hand", chosen, "trash from hand")
        return {"action": "click_button", "prefer": "main", "reason": "hand empty"}

    # --- Campo do oponente ----------------------------------------------
    if zone == "opp_field":
        chosen = choose_highest_board_value(opp_gs.field_chars)
        if chosen:
            return _card_intent("opp_board", chosen, "choose opp char")
        return {"action": "click_button", "prefer": "main", "reason": "no opp chars"}

    # --- Campo proprio --------------------------------------------------
    if zone == "own_field":
        if "trash" in text:
            chosen = (min(gs.field_chars, key=lambda c: c.board_value())
                      if gs.field_chars else None)
        else:
            chosen = choose_highest_board_value(gs.field_chars)
        if chosen:
            return _card_intent("own_board", chosen, "choose own char")
        # Sem cartas no campo (field stale) -> confirma/cancela
        return {"action": "click_button", "prefer": "main", "reason": "no own chars"}

    # Prompt nao reconhecido: None para que o chamador use fallback
    return None
