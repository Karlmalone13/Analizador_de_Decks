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
from fastapi.responses import JSONResponse
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


# ── Bridge ao engine ──────────────────────────────────────────────────────────

_bridge = None

def _get_bridge():
    global _bridge
    if _bridge is None:
        from optcg_engine import sim_bridge
        _bridge = sim_bridge
    return _bridge

def _dto_to_gs(player: PlayerDto):
    """Converte PlayerDto em GameState do engine."""
    from optcg_engine.decision_engine import GameState, _make_card

    bridge = _get_bridge()
    cards_db = getattr(bridge, '_cards_db', {})

    def make(dto: CardDto):
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

    gs = GameState()
    gs.hand        = [c for c in (make(d) for d in player.hand) if c]
    gs.field_chars = [c for c in (make(d) for d in player.board) if c]
    gs.life        = [c for c in (make(d) for d in player.life) if c]
    gs.don_available = player.activeDon
    gs.don_rested    = player.restedDon

    if player.leader:
        ldr = make(player.leader)
        if ldr:
            gs.leader = ldr

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
        gs     = _dto_to_gs(state.bot)
        opp_gs = _dto_to_gs(state.opp)

        gs.turn = state.turnNumber

        action = bridge.choose_action(gs, opp_gs)

        if action is None:
            return {"type": "end_turn", "cardId": 0, "targetId": 0}

        action_type = action[1] if len(action) > 1 else "end_turn"
        card_id  = 0
        target_id = 0

        if action_type == "play" and len(action) > 2:
            code = action[2]
            card = next((c for c in gs.hand if c.code == code), None)
            card_id = getattr(card, '_deck_uid', 0) if card else 0

        elif action_type == "attack" and len(action) > 2:
            attacker_code = action[2]
            attacker = next((c for c in gs.field_chars if c.code == attacker_code), None)
            card_id = getattr(attacker, '_deck_uid', 0) if attacker else 0

            if len(action) > 3:
                target_code = action[3]
                if target_code == "leader":
                    target_id = 0
                else:
                    target = next((c for c in opp_gs.field_chars if c.code == target_code), None)
                    target_id = getattr(target, '_deck_uid', 0) if target else 0

        return {"type": action_type, "cardId": card_id, "targetId": target_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
