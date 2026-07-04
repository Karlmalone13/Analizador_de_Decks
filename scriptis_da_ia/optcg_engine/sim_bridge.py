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
from copy import deepcopy
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
        if getattr(c, 'just_played', False) and not getattr(c, 'rush', False):
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
                  allowed_types: Optional[set] = None) -> Optional[tuple]:
    """
    Pede ao engine a melhor ação para o estado atual.

    Retorna a tuple de ação (score, tipo, carta, ...) ou None se não há ação.
    O chamador usa action[1] (tipo: 'play'|'attack'|'activate'|...) e
    action[2] (carta) para executar no simulador.

    allowed_types: se dado, retorna a melhor ação de score >= 0 cujo TIPO o
    executor sabe realizar (ex: o plugin só executa play/attack/attach_don).
    A ordem de preferência continua sendo 100% do engine — isto só pula
    ações que o executor não tem como fazer, em vez de encerrar o turno.
    """
    import threading
    result: list = [None]

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
                if allowed_types is None or a[1] in allowed_types:
                    result[0] = a
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

    Com `match`, calcula o DON LIVRE do plano do turno: o que sobra do
    don_available depois (a) das jogadas que o engine ainda pretende fazer
    (ações 'play' com score >= 0, na ordem de preferência, enquanto o DON
    alcança) e (b) da reserva de defesa. A margem de counter do
    don_needed_for_attack só é paga com essa sobra — DON comprometido com o
    plano nunca vira margem.
    """
    from optcg_engine.decision_engine import (don_needed_for_attack,
                                              effective_hand_play_cost)
    if action is None or len(action) < 3 or action[1] != 'attack':
        return 0
    attacker = action[2]
    ttype = action[3] if len(action) > 3 else 'leader'
    tgt = action[4] if len(action) > 4 else None
    engine = DecisionEngine(gs, opp_gs)

    don_livre = None
    if match is not None:
        planejado = 0
        try:
            acts = match._generate_and_score_actions(gs, opp_gs, engine)
            for a in acts:
                if a[0] < 0:
                    break
                if a[1] == 'play':
                    custo = effective_hand_play_cost(gs, a[2])
                    if planejado + custo <= gs.don_available:
                        planejado += custo
            reserva = engine._don_reserve_for_defense()
        except Exception:
            planejado, reserva = 0, 0
        don_livre = max(0, gs.don_available - planejado - reserva)

    return don_needed_for_attack(attacker, ttype or 'leader', tgt,
                                 gs, opp_gs, engine, don_livre=don_livre)


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


def resolve_trigger_choice(gs: GameState, card_code: str | None) -> bool:
    """
    Decide se o bot deve usar o Trigger Effect de uma carta revelada da vida.

    Estrategia:
      - Sem codigo conhecido -> usa (melhor que perder o trigger)
      - Carta sem steps de trigger no effects_db -> nao usa (provavelmente e counter)
      - KO / bounce / draw / buff / give_don / play_card -> usa sempre
      - Trash da mao -> usa so se tiver carta na mao
      - Trash da vida -> usa so se vida > 1
      - Desconhecido -> usa por precaucao
    """
    if not card_code:
        return True

    # ATENCAO: efeitos ficam aninhados sob 'effects' no card_effects_db —
    # get_card_effects resolve isso (leitura direta de _effects_db[code]['trigger']
    # sempre devolvia {} e o bot NUNCA usava trigger; bug corrigido 04/07/2026)
    from optcg_engine.decision_engine import get_card_effects
    trigger_steps = get_card_effects(card_code).get('trigger', {}).get('steps', [])

    if not trigger_steps:
        return False  # sem trigger declarado (ex: carta com counter mas sem trigger)

    for step in trigger_steps:
        action = step.get('action', '')
        if action in ('ko', 'bounce', 'draw', 'draw_cards', 'buff_power',
                      'give_don', 'rest_opp', 'play_card', 'play_from_trash',
                      'debuff_power', 'activate_main_effect'):
            return True
        if action in ('trash', 'trash_from_hand', 'discard'):
            return len(gs.hand) > 0
        if action == 'trash_life':
            return len(gs.life) > 1

    return True  # default: usa


def select_counter_cards(gs: GameState, atk_power: int, def_power: int) -> list[int]:
    """
    Seleciona as cartas de counter (por _deck_uid) para defender um ataque.
    Mesma politica do DecisionEngine.use_counter: menores primeiro, minimo
    necessario — e so counteriza se realmente cobre o ataque.
    Retorna [] se o engine decidir nao counterizar.
    """
    opp_stub = GameState(leader=deepcopy(gs.leader))
    engine = DecisionEngine(gs, opp_stub)
    if not engine.should_use_counter(atk_power, def_power):
        return []
    needed = atk_power - def_power + 1
    # menor counter primeiro; empate = pitcha a carta de MENOR valor
    # situacional (nao jogar fora efeito bom junto com o counter)
    counters = sorted([c for c in gs.hand if c.counter > 0],
                      key=lambda c: (c.counter, engine.avaliar_carta(c)))
    total, ids = 0, []
    for c in counters:
        if total >= needed:
            break
        uid = getattr(c, '_deck_uid', 0)
        if uid:
            ids.append(uid)
            total += c.counter
    return ids if total >= needed else []


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
    paga o custo de 1 carta da mao (~25).

    Guardas: ataque precisa estar ganhando; mao >= 2 (a ultima carta vale
    mais que 1 vida, salvo vida critica) — bot ficou de mao vazia pagando
    reacao toda rodada em partida real.
    """
    from optcg_engine.decision_engine import (redirect_option_value,
                                              life_redirect_cost)
    engine = DecisionEngine(gs, opp_gs)
    my_life = gs.life_count()
    CUSTO_CARTA = 25.0

    if atk_power < def_power:
        return False   # o ataque ja perde sozinho — nao gasta nada
    if len(gs.hand) < 2 and my_life > 1:
        return False   # ultima carta vale mais que 1 vida (salvo vida critica)

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
        return False

    return max(opcoes) + salva >= CUSTO_CARTA


def resolve_optional_effect(gs: GameState, opp_gs: GameState) -> bool:
    """
    Efeito opcional com custo no PROPRIO turno (downside pos-play, ex:
    "you may trash 1 card: ..."). Usa se a mao tem carta dispensavel:
    mais de 1 carta e a pior delas tem valor situacional baixo.
    """
    if len(gs.hand) < 2:
        return False
    engine = DecisionEngine(gs, opp_gs)
    worst = engine.choose_to_trash(gs.hand)
    if worst is None:
        return False
    # Carta de valor baixo na mao -> o custo e barato, efeito compensa
    return engine.avaliar_carta(worst) <= 60


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
                                              get_card_effects, on_ko_value)

    # Redirect: o alvo original e um personagem NOSSO? (lider como escape)
    defender_is_own_char = (
        attacker_power > 0 and defender_uid
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

    def sort_key(cand: dict):
        card = card_of(cand)
        zone = cand.get('zone', '')
        # Contexto de ataque: alvo original sempre por ULTIMO, em qualquer zona
        if attacker_power > 0 and defender_uid and cand.get('id') == defender_uid:
            return (9, 0)
        if zone == 'top_deck':
            return (0, -(engine.avaliar_carta(card) if card else 0))
        if zone == 'own_hand':
            return (1, engine.avaliar_carta(card) if card else 0)
        if zone == 'own_trash':
            return (2, -(engine.avaliar_carta(card) if card else 0))
        if zone == 'own_board':
            if attacker_power > 0:
                # ganho liquido caso a caso; desempate: maior poder segura
                # golpes maiores
                valor = redirect_option_value(card, attacker_power, opp_gs,
                                              engine) if card else -999
                return (3, -valor, -(getattr(card, 'power', 0) if card else 0))
            return (3, engine.analyzer.char_value_score(card) if card else 0, 0)
        if zone == 'own_leader':
            if defender_is_own_char and gs.life_count() > 0:
                # mandar o golpe para o lider = pagar vida (mesma conta do
                # resolve_reaction) — compete de igual com os personagens
                return (3, life_redirect_cost(gs.life_count()), 0)
            return (6, 0, 0)
        if zone == 'opp_board':
            if actor_copia_poder:
                # copy-power: maior poder = maior ataque copiado
                return (4, -(getattr(card, 'power', 0) if card else 0))
            # remocao: valor do alvo DESCONTADO do on-KO dele (KO-zar um
            # personagem com on-KO rico presenteia o efeito ao oponente)
            valor = engine.analyzer.char_value_score(card) if card else 0
            ko_deles = on_ko_value(card.code, gs) if card else 0
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
