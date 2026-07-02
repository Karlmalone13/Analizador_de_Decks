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
                  match) -> Optional[tuple]:
    """
    Pede ao engine a melhor ação para o estado atual.

    Retorna a tuple de ação (score, tipo, carta, ...) ou None se não há ação.
    O chamador usa action[1] (tipo: 'play'|'attack'|'activate'|...) e
    action[2] (carta) para executar no simulador.
    """
    engine = DecisionEngine(gs, opp_gs)
    actions = match._generate_and_score_actions(gs, opp_gs, engine)
    if not actions or actions[0][0] < 0:
        return None
    return actions[0]
