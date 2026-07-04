"""
engine_server/server.py
========================
Servidor HTTP local que recebe o estado do jogo do plugin C# (BepInEx)
e retorna a acao decidida pelo decision_engine.py.

Rodar antes de abrir o OPTCGSim:
    cd BOT/engine_server
    python server.py

Porta: 8765
"""
from __future__ import annotations
import sys
from pathlib import Path

# Adiciona scriptis_da_ia ao path para importar o engine
_ROOT = Path(__file__).parent.parent.parent / "scriptis_da_ia"
sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from typing import Optional

app = FastAPI(title="OPTCG Bot Engine Server")


# ── DTOs (espelham GameStateDto.cs) ──────────────────────────────────────────

class CardDto(BaseModel):
    code: str
    cost: int
    power: int
    rested: bool
    justPlayed: bool
    deckUniqueId: int

class PlayerDto(BaseModel):
    hand: list[CardDto] = []
    board: list[CardDto] = []
    life: list[CardDto] = []
    leader: Optional[CardDto] = None
    activeDon: int = 0
    restedDon: int = 0

class GameStateDto(BaseModel):
    turnNumber: int
    bot: PlayerDto      # P2 = bot
    opp: PlayerDto      # P1 = humano


# ── Engine (lazy init) ────────────────────────────────────────────────────────

_bridge = None
_match  = None   # OPTCGMatch: maquinaria de regras usada por choose_action


def _get_bridge():
    global _bridge
    if _bridge is None:
        from optcg_engine import sim_bridge
        _bridge = sim_bridge
    return _bridge


def _get_match():
    """
    Cria um OPTCGMatch uma unica vez, com qualquer deck disponivel.
    O match e so a maquinaria de _generate_and_score_actions — os GameStates
    reais sao reconstruidos a cada /decide a partir do DTO.
    """
    global _match
    if _match is None:
        from optcg_engine.decision_engine import OPTCGMatch
        bridge = _get_bridge()
        decks = bridge.list_decks()
        if not decks:
            raise RuntimeError("Nenhum .deck encontrado para inicializar o match")
        deck_tuple = bridge.load_sim_deck(decks[0])
        _match = OPTCGMatch(deck_tuple, deck_tuple)
        _match.setup()
    return _match


def _make(dto: CardDto):
    """CardDto -> Card do engine (None se o codigo nao esta no banco)."""
    from optcg_engine.decision_engine import _make_card
    bridge = _get_bridge()
    cards_db = getattr(bridge, '_cards_db', {})
    data = cards_db.get(dto.code)
    if not data:
        return None
    try:
        card = _make_card(dto.code, data)
        card.rested      = dto.rested
        card.just_played = dto.justPlayed
        card._deck_uid   = dto.deckUniqueId
        return card
    except Exception:
        return None


def _dto_to_gs(player: PlayerDto, turn: int):
    """Converte PlayerDto em GameState do engine."""
    from optcg_engine.decision_engine import GameState, _make_card
    bridge = _get_bridge()
    cards_db = getattr(bridge, '_cards_db', {})

    # Leader e obrigatorio no GameState
    leader = _make(player.leader) if player.leader else None
    if leader is None:
        # Stub minimo para nao quebrar (nao deve acontecer em jogo real)
        data = {"name": "?", "type": "LEADER", "cost": 0, "power": 5000,
                "text": "", "color": "", "sub_types": "", "life": 5,
                "has_trigger": False}
        leader = _make_card("STUB-000", data)

    gs = GameState(leader=leader)
    gs.hand          = [c for c in (_make(d) for d in player.hand) if c]
    gs.field_chars   = [c for c in (_make(d) for d in player.board) if c]
    gs.life          = [c for c in (_make(d) for d in player.life) if c]
    gs.don_available = player.activeDon
    gs.don_rested    = player.restedDon
    # can_attack_this_turn() exige turn > 1
    gs.turn          = max(2, turn)
    gs.global_turn   = turn
    return gs


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/decide")
def decide(state: GameStateDto):
    """
    Recebe o estado do jogo e retorna a proxima acao do bot.
    Resposta: {"type": "play"|"attack"|"end_turn", "cardId": int, "targetId": int}
    """
    try:
        bridge = _get_bridge()
        match  = _get_match()
        gs     = _dto_to_gs(state.bot, state.turnNumber)
        opp_gs = _dto_to_gs(state.opp, state.turnNumber)

        action = bridge.choose_action(gs, opp_gs, match, timeout=3.0)

        if action is None:
            return {"type": "end_turn", "cardId": 0, "targetId": 0}

        # Formato da action: (score, tipo, card, ttype, tgt)
        #   play:   (score, 'play',   card, None, None)
        #   attack: (score, 'attack', att, 'leader'|'character', tgt_card|None)
        action_type = action[1] if len(action) > 1 else "end_turn"
        card_id   = 0
        target_id = 0

        if action_type == "play" and len(action) > 2:
            card = action[2]
            # A carta veio do proprio gs.hand — tem _deck_uid direto
            card_id = getattr(card, '_deck_uid', 0)
            if card_id == 0:
                return {"type": "end_turn", "cardId": 0, "targetId": 0}

        elif action_type == "attack" and len(action) > 2:
            attacker = action[2]
            card_id = getattr(attacker, '_deck_uid', 0)
            if card_id == 0:
                # Lider do bot nao tem uid do board — usa o uid do proprio leader dto
                if attacker is gs.leader:
                    card_id = getattr(gs.leader, '_deck_uid', 0)
                if card_id == 0:
                    return {"type": "end_turn", "cardId": 0, "targetId": 0}

            ttype = action[3] if len(action) > 3 else 'leader'
            if ttype == 'character' and len(action) > 4 and action[4] is not None:
                target_id = getattr(action[4], '_deck_uid', 0)
                if target_id == 0:
                    return {"type": "end_turn", "cardId": 0, "targetId": 0}
            # ttype == 'leader' -> targetId = 0 (lider oponente)

        else:
            # Tipos ainda nao suportados no plugin (activate, attach_don...)
            return {"type": "end_turn", "cardId": 0, "targetId": 0}

        return {"type": action_type, "cardId": card_id, "targetId": target_id}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
