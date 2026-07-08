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
    powerAtk: int = 0        # CardPower(..., attacking=true), sem DON
    rested: bool
    justPlayed: bool
    deckUniqueId: int
    donAttached: int = 0     # DON anexados a carta (default 0 p/ plugin antigo)
    actionUsed: bool = False # acao da carta ja usada neste turno (lb_ActionsUsed)

class PlayerDto(BaseModel):
    hand: list[CardDto] = []
    board: list[CardDto] = []
    life: list[CardDto] = []
    leader: Optional[CardDto] = None
    stage: Optional[CardDto] = None   # carta STAGE em campo (zona propria)
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
        # Poder ATUAL vindo do jogo (CardPower sem DON): inclui buffs/debuffs
        # e passivas de campo que o banco nao tem como saber (ex: -2000 do
        # Krieg). Troca o CardData DESTA instancia por uma copia com o poder
        # vivo — nunca mexer no dict do banco nem no _CARD_DATA_CACHE do
        # _make_card (CardData e compartilhado entre todas as copias do
        # codigo; ja envenenou o cache numa versao anterior deste fix).
        # O DON anexado o engine soma por conta propria via don_attached.
        if dto.power != card.data.power:
            from dataclasses import replace
            # guarda o poder de BANCO antes do override: modificadores vivos
            # (ex: -2000 do Krieg/Morgan) = dto.power - base, e eles persistem
            # apos efeitos de set_base_power (copy da Devon)
            card._db_base_power = card.data.power
            card.data = replace(card.data, power=dto.power)
        # Poder vivo especificamente ao ATACAR, calculado pelo proprio jogo.
        # Nao troca card.data.power: fora do ataque o engine deve continuar
        # usando dto.power. attack_time_power soma DON e When Attacking.
        if dto.powerAtk != dto.power:
            card._attack_power_override = dto.powerAtk
            if not hasattr(card, '_db_base_power'):
                card._db_base_power = card.data.power
        card.rested       = dto.rested
        card.just_played  = dto.justPlayed
        card.don_attached = dto.donAttached
        card._deck_uid    = dto.deckUniqueId
        card._action_used = dto.actionUsed
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
    gs.field_stage   = _make(player.stage) if player.stage else None
    gs.life          = [c for c in (_make(d) for d in player.life) if c]
    gs.don_available = player.activeDon
    gs.don_rested    = player.restedDon
    # Estado REAL de once-per-turn vindo do jogo (lb_ActionsUsed): marca a
    # acao como ja usada NESTE turno para o engine nao reoferecer activate
    # (a gs e reconstruida a cada /decide — sem isso o _am_used_turn se perdia
    # e o engine loopava o mesmo activate ate o guarda encerrar o turno)
    for c in ([gs.leader] if gs.leader else []) + gs.field_chars + \
             ([gs.field_stage] if gs.field_stage else []):
        if getattr(c, '_action_used', False):
            c._am_used_turn = turn
    # Turno REAL do jogo: no turno 1 nao pode atacar (can_attack_this_turn),
    # e o engine nao deve gerar ataque/attach que o jogo vai recusar.
    # (o antigo max(2, turn) fazia o bot anexar DON num ataque impossivel)
    gs.turn          = turn
    gs.global_turn   = turn
    return gs


# ── Endpoints ─────────────────────────────────────────────────────────────────

class MulliganRequest(BaseModel):
    hand: list[CardDto] = []


class DefenseRequest(BaseModel):
    state: GameStateDto
    phase: str                    # "blocker" | "counter" | "trigger" | "reaction" | "optional"
    attackerPower: int = 0
    defenderPower: int = 0
    defenderId: int = 0           # uid do alvo atual do ataque (contexto p/ redirect)
    triggerCode: Optional[str] = None


class TargetCandidate(BaseModel):
    id: int
    zone: str        # own_hand | own_board | own_trash | opp_board | opp_trash |
                     # top_deck | own_leader | opp_leader | own_stage | opp_stage
    code: str = ""   # cardID p/ valorar cartas fora do DTO (trash/top deck)


class ChooseTargetRequest(BaseModel):
    state: GameStateDto
    candidates: list[TargetCandidate] = []
    actorCode: Optional[str] = None   # carta cujo efeito esta resolvendo (debug/futuro)
    attackerPower: int = 0            # > 0 = efeito resolvendo durante um ataque (redirect)
    defenderId: int = 0               # uid do alvo original do ataque (nunca redirecionar p/ ele)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/mulligan")
def mulligan(req: MulliganRequest):
    """
    Decide mulligan da mao inicial usando o engine (_mulligan_decision).
    Resposta: {"mulligan": bool, "reason": str}
    """
    try:
        match = _get_match()
        hand_cards = [c for c in (_make(d) for d in req.hand) if c]
        if not hand_cards:
            return {"mulligan": False, "reason": "mao vazia/desconhecida — keep"}
        deve_trocar, resumo = match._mulligan_decision(hand_cards, deck=None)
        return {"mulligan": bool(deve_trocar), "reason": resumo}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"mulligan": False, "reason": f"erro: {e} — keep por seguranca"}


@app.post("/defense")
def defense(req: DefenseRequest):
    """
    Decisoes de defesa quando o humano ataca o bot.
    Resposta: {"blockerId": int, "counterIds": [int], "useTrigger": bool}
    (campos nao usados pela fase vem zerados/vazios)
    """
    try:
        from optcg_engine.decision_engine import DecisionEngine
        bridge = _get_bridge()
        gs     = _dto_to_gs(req.state.bot, req.state.turnNumber)
        opp_gs = _dto_to_gs(req.state.opp, req.state.turnNumber)

        out = {"blockerId": 0, "counterIds": [], "useTrigger": False, "useReaction": False}

        if req.phase == "blocker":
            engine = DecisionEngine(gs, opp_gs)
            blocker = engine.should_use_blocker(req.attackerPower)
            if blocker is not None:
                out["blockerId"] = getattr(blocker, '_deck_uid', 0)
            print(f"[DEF] blocker atk={req.attackerPower} -> "
                  f"{blocker.name if blocker else 'NAO bloqueia'}", flush=True)

        elif req.phase == "counter":
            out["counterIds"] = bridge.select_counter_cards(
                gs, req.attackerPower, req.defenderPower)
            print(f"[DEF] counter atk={req.attackerPower} def={req.defenderPower} "
                  f"-> {len(out['counterIds'])} cartas", flush=True)

        elif req.phase == "trigger":
            out["useTrigger"] = bool(bridge.resolve_trigger_choice(gs, req.triggerCode, opp_gs))
            print(f"[DEF] trigger {req.triggerCode} -> {out['useTrigger']}", flush=True)

        elif req.phase == "reaction":
            out["useReaction"] = bridge.resolve_reaction(
                gs, opp_gs, req.attackerPower, req.defenderPower,
                defender_uid=req.defenderId)
            print(f"[DEF] reaction atk={req.attackerPower} def={req.defenderPower} "
                  f"defId={req.defenderId} -> {out['useReaction']}", flush=True)

        elif req.phase == "optional":
            # Efeito opcional com custo no proprio turno do bot
            out["useReaction"] = bridge.resolve_optional_effect(gs, opp_gs)
            print(f"[DEF] optional -> {out['useReaction']}", flush=True)

        return out

    except Exception as e:
        import traceback
        traceback.print_exc()
        # Defesa conservadora em erro: nao bloqueia, nao counteriza, nao reage
        return {"blockerId": 0, "counterIds": [], "useTrigger": False, "useReaction": False}


@app.post("/choose_target")
def choose_target(req: ChooseTargetRequest):
    """
    Ordena candidatos de alvo de um efeito pendente por preferencia do engine.
    O plugin clica na ordem — o jogo valida cada clique (no-op se invalido).

    Heuristica por zona:
    - own_hand: pior carta primeiro (descarte — choose_to_trash)
    - own_board: menor valor primeiro (sacrificio)
    - opp_board: maior valor primeiro (remocao/bounce)
    - leaders/stages: por ultimo
    """
    try:
        bridge = _get_bridge()
        gs     = _dto_to_gs(req.state.bot, req.state.turnNumber)
        opp_gs = _dto_to_gs(req.state.opp, req.state.turnNumber)

        out = bridge.order_target_candidates(
            gs, opp_gs,
            [{"id": c.id, "zone": c.zone, "code": c.code} for c in req.candidates],
            attacker_power=req.attackerPower,
            defender_uid=req.defenderId,
            actor_code=req.actorCode)
        zonas = sorted({c.zone for c in req.candidates})
        print(f"[TGT] {len(req.candidates)} candidatos (actor={req.actorCode} "
              f"atk={req.attackerPower} def={req.defenderId} zonas={zonas}) -> ordem {out[:5]}",
              flush=True)
        # Diagnostico 07/07: confirmar se um redirect (attackerPower>0) esta
        # escolhendo o proprio alvo original (no-op) por falta de opcao —
        # ajuda a achar se a ability do Teach passa por /defense phase=reaction
        # antes disso ou vai direto pro choose_target sem gate de aceitar/recusar.
        if req.attackerPower > 0 and req.defenderId and out and out[0] == req.defenderId:
            print(f"[TGT][AVISO] top escolhido == alvo original (defId={req.defenderId}) "
                  f"-- possivel redirect sem efeito (no-op)", flush=True)
        return {"orderedIds": out}

    except Exception as e:
        import traceback
        traceback.print_exc()
        # Fallback: ordem original
        return {"orderedIds": [c.id for c in req.candidates]}


@app.post("/decide")
def decide(state: GameStateDto):
    """
    Recebe o estado do jogo e retorna a proxima acao do bot.
    Resposta: {"type": "play"|"attack"|"attach_don"|"end_turn",
               "cardId": int, "targetId": int, "donToAttach": int}
    """
    try:
        bridge = _get_bridge()
        match  = _get_match()
        gs     = _dto_to_gs(state.bot, state.turnNumber)
        opp_gs = _dto_to_gs(state.opp, state.turnNumber)

        # So tipos que o plugin sabe executar — os demais sao pulados pelo
        # bridge em vez de encerrar o turno.
        action = bridge.choose_action(gs, opp_gs, match, timeout=3.0,
                                      allowed_types={"play", "attack",
                                                     "attach_don", "activate"})

        if action is None:
            return {"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}

        # Formato da action: (score, tipo, card, ...)
        #   play:       (score, 'play',       card, None, None)
        #   attack:     (score, 'attack',     att, 'leader'|'character', tgt_card|None)
        #   attach_don: (score, 'attach_don', card, falta, keyword/trigger)
        action_type = action[1] if len(action) > 1 else "end_turn"
        card_id    = 0
        target_id  = 0
        don_attach = 0

        if action_type == "play" and len(action) > 2:
            card = action[2]
            # A carta veio do proprio gs.hand — tem _deck_uid direto
            card_id = getattr(card, '_deck_uid', 0)
            if card_id == 0:
                return {"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}

        elif action_type == "attack" and len(action) > 2:
            attacker = action[2]
            card_id = getattr(attacker, '_deck_uid', 0)
            if card_id == 0:
                # Lider do bot nao tem uid do board — usa o uid do proprio leader dto
                if attacker is gs.leader:
                    card_id = getattr(gs.leader, '_deck_uid', 0)
                if card_id == 0:
                    return {"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}

            ttype = action[3] if len(action) > 3 else 'leader'
            if ttype == 'character' and len(action) > 4 and action[4] is not None:
                target_id = getattr(action[4], '_deck_uid', 0)
                if target_id == 0:
                    return {"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}
            # ttype == 'leader' -> targetId = 0 (lider oponente)

            # DON a anexar ANTES de declarar. Deficit base sempre; margem de
            # counter so com DON ocioso no plano do turno (match da acesso as
            # jogadas planejadas + reserva de defesa)
            don_attach = bridge.don_for_attack(gs, opp_gs, action, match=match)

        elif action_type == "attach_don" and len(action) > 3:
            card = action[2]
            card_id    = getattr(card, '_deck_uid', 0)
            don_attach = int(action[3] or 0)
            if card_id == 0 or don_attach <= 0:
                return {"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}

        elif action_type == "activate" and len(action) > 2:
            # [Activate: Main] de lider/personagem/stage em campo (ex:
            # Laffitte OP09-095 — search). O jogo valida e paga o custo.
            card = action[2]
            card_id = getattr(card, '_deck_uid', 0)
            if card_id == 0:
                if card is gs.leader:
                    card_id = getattr(gs.leader, '_deck_uid', 0)
                if card_id == 0:
                    return {"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}

        else:
            return {"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}

        return {"type": action_type, "cardId": card_id,
                "targetId": target_id, "donToAttach": don_attach}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
