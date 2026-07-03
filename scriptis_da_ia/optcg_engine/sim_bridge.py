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
_effects_db  = _load_effects_db()
_analysis_db = _load_analysis_db()
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


def choose_action(gs: GameState, opp_gs: GameState,
                  match, timeout: float = 4.0) -> Optional[tuple]:
    """
    Pede ao engine a melhor ação para o estado atual.

    Retorna a tuple de ação (score, tipo, carta, ...) ou None se não há ação.
    O chamador usa action[1] (tipo: 'play'|'attack'|'activate'|...) e
    action[2] (carta) para executar no simulador.
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
            if actions and actions[0][0] >= 0:
                result[0] = actions[0]
        except Exception as e:
            import traceback
            print(f"[ENG-ERR] {e}\n{traceback.format_exc()}", flush=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


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
                          prompt_text: str) -> Optional[dict]:
    """
    Traduz um prompt visual do OPTCGSim em uma intencao clicavel.

    Logica puramente generica: detecta ZONA + ACAO + CONTAGEM pelo texto OCR.
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
