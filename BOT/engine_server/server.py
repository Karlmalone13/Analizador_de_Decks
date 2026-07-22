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
import os
import threading
import time
from typing import Optional
from telemetry import new_decision_id, write_event, PATH as DECISION_LOG_PATH

# ── Log de sessao em arquivo (alem do console) ───────────────────────────────
# Duplica tudo que passa por print() (aqui e em sim_bridge.py, que roda no
# MESMO processo/stdout) pra um arquivo, alem do terminal. Sem isso, o unico
# jeito de investigar por que o bot parou de agir no meio de um turno era
# depender do usuario deixar o terminal aberto e rolar o scrollback -- o
# scrollback tem limite e a janela fecha; um arquivo persiste. Achado real
# 10/07: precisei pedir pro usuario "deixa o terminal aberto da proxima vez"
# porque nao tinha como investigar um loop ao vivo so pelo combat log.
import datetime as _dt

class _TeeStream:
    def __init__(self, *streams):
        self._streams = streams
    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data)
    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass
    def isatty(self):
        # uvicorn's default log config chama sys.stdout.isatty() pra decidir
        # cor no terminal -- sem esse metodo o startup quebra com
        # AttributeError. Repassa do stream original (o 1o = o real).
        try:
            return self._streams[0].isatty()
        except Exception:
            return False
    def __getattr__(self, name):
        # Qualquer outro atributo/metodo de arquivo que algo pergunte
        # (encoding, fileno, etc) repassa pro stream original.
        return getattr(self._streams[0], name)

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_PATH = _LOG_DIR / f"session_{_dt.datetime.now():%Y-%m-%dT%H.%M.%S}.log"
_log_file = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
sys.stdout = _TeeStream(sys.stdout, _log_file)
sys.stderr = _TeeStream(sys.stderr, _log_file)
print(f"[SERVER] log desta sessao (manda pra mim se algo der errado): {_LOG_PATH}", flush=True)

app = FastAPI(title="OPTCG Bot Engine Server")
_collection_status = {"status": "idle", "message": "nenhuma coleta iniciada",
                      "report": None, "receipt": None}


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
    cantAttack: bool = False # travado de atacar por efeito do oponente (CardCantAttack real do jogo)

class PlayerDto(BaseModel):
    hand: list[CardDto] = []
    board: list[CardDto] = []
    life: list[CardDto] = []
    leader: Optional[CardDto] = None
    stage: Optional[CardDto] = None   # carta STAGE em campo (zona propria)
    trash: list[CardDto] = []         # lixeira (publica) — trash_gte, GamePlan
    deckCount: int = 0                # tamanho do deck (0 = plugin antigo)
    activeDon: int = 0
    restedDon: int = 0

class GameStateDto(BaseModel):
    turnNumber: int
    bot: PlayerDto      # P2 = bot
    opp: PlayerDto      # P1 = humano


def _model_dict(model: BaseModel) -> dict:
    """Pydantic v1/v2 sem amarrar o servidor a uma versao."""
    dump = getattr(model, "model_dump", None)
    return dump() if dump else model.dict()


# ── Engine (lazy init) ────────────────────────────────────────────────────────

_bridge = None
_match  = None   # OPTCGMatch: maquinaria de regras usada por choose_action

# ── Ativacoes opcionais ja recusadas neste turno ──────────────────────────────
# Achado real 10/07 (log 23.19.23, turno 4): mesmo com resolve_optional_effect
# avaliando corretamente (fix anterior), quando a resposta e False o estado do
# jogo nao muda -- a MESMA acao 'activate' de score alto era reoferecida a
# cada /decide seguinte (GameState e reconstruido do zero por chamada, sem
# memoria própria), travando o turno em loop ate o retry do plugin desistir
# sem nunca tentar a jogada de score mais baixo que sobrava. (codigo, turno) ->
# marca que ESSA ativacao ja foi oferecida e recusada nesse turno; /decide
# passa a excluir do proximo /decide desse mesmo turno, deixando o Turn
# Planner cair pra proxima acao da lista.
_declined_optional: set[tuple[str, int]] = set()
_live_match_id = new_decision_id()

# Memoria de reveals DA PARTIDA (persistencia entre /decide -- ver
# match_memory.py e MEMORIA_REVEALS.md). Populada pelo /reveal, resetada no
# /mulligan, consumida por _dto_to_gs(hide_hidden=True).
from match_memory import MatchMemory
_match_memory = MatchMemory()


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
        # Lock de ataque REAL vindo do jogo (CardCantAttack, ex: Teach
        # OP09-093 "cannot attack until end of opponent's next turn").
        # Achado real 09/07: sem isso o bot oferecia esse personagem como
        # atacante mesmo travado -- StartAttack() nao valida sozinho, so a
        # camada de clique humano (que o bot pula via reflection). O filtro
        # de ataque (`_generate_and_score_actions`) ja checa
        # `cannot_attack_until` truthy; qualquer string nao-vazia basta.
        if dto.cantAttack:
            card.cannot_attack_until = 'live_lock'
        return card
    except Exception:
        return None


def _hidden_placeholder(dto: CardDto):
    """Carta UNKNOWN no lugar de informacao oculta (mao/vida do oponente).

    Mantem a CONTAGEM e o deckUniqueId (o uid e publico -- e a "costas da
    carta" que o bot ve e pode precisar clicar como alvo), mas nenhuma
    identidade: codigo/custo/poder/counter neutros. Igual ao padrao ja usado
    pro deck oculto (UNKNOWN-000 placeholders)."""
    from optcg_engine.decision_engine import _make_card
    data = {"name": "?", "type": "CHARACTER", "cost": 1, "power": 0,
            "text": "", "color": "", "sub_types": "", "life": 0,
            "has_trigger": False}
    card = _make_card("UNKNOWN-000", data)
    card._deck_uid = dto.deckUniqueId
    return card


def _dto_to_gs(player: PlayerDto, turn: int, hide_hidden: bool = False):
    """Converte PlayerDto em GameState do engine.

    hide_hidden=True (usado pro OPONENTE): mao e vida viram placeholders
    UNKNOWN -- o DTO traz as cartas reais (o cliente tem o estado inteiro em
    memoria), mas o bot deve jogar como humano vs humano (regra do usuario,
    21/07) e NAO pode ler informacao oculta. Excecao: uids registrados na
    MatchMemory (revelados durante a partida via /reveal) entram com a
    identidade real E marcados como conhecidos (revealed_to_opponent/
    revealed_life), alimentando o OpponentModel e o lethal conservador
    (opp_counter_chunks_for_lethal). E a persistencia ao vivo da memoria de
    reveals (MEMORIA_REVEALS.md, pendencia 1)."""
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
    if hide_hidden:
        # Mao oculta: identidade so das reveladas (MatchMemory), resto UNKNOWN
        gs.hand = []
        for d in player.hand:
            if _match_memory.is_known("opp_hand", d.deckUniqueId):
                card = _make(d) or _hidden_placeholder(d)
                if card.code != "UNKNOWN-000":
                    gs.revealed_to_opponent.add(id(card))
            else:
                card = _hidden_placeholder(d)
            gs.hand.append(card)
        # Vida oculta: mesma regra
        gs.life = []
        for d in player.life:
            if _match_memory.is_known("opp_life", d.deckUniqueId):
                card = _make(d) or _hidden_placeholder(d)
                if card.code != "UNKNOWN-000":
                    gs.revealed_life.add(id(card))
            else:
                card = _hidden_placeholder(d)
            gs.life.append(card)
    else:
        gs.hand = [c for c in (_make(d) for d in player.hand) if c]
        gs.life = [c for c in (_make(d) for d in player.life) if c]
    gs.field_chars   = [c for c in (_make(d) for d in player.board) if c]
    gs.field_stage   = _make(player.stage) if player.stage else None
    gs.don_available = player.activeDon
    gs.don_rested    = player.restedDon
    # Lixeira REAL (plugin novo, 12/07): informacao publica do jogo. Sem ela
    # gs.trash=[] fazia trash_gte (Ground Death [Counter], imunidade dos
    # Celestial Dragons) nunca ativar ao vivo e o progresso do GamePlan
    # (len(trash) < trash_target) ficar sempre em 0.
    gs.trash = [c for c in (_make(d) for d in player.trash) if c]
    # Deck oculto: o DTO nao traz o deck (informacao que o bot nao ve), mas
    # um GameState com deck=[] faz _step_is_viable de 'draw'/'look_top_deck'
    # dar False SEMPRE no caminho ao vivo -- achado real 11/07 (log 01.36.16):
    # o draw do lider Imu era recusado todo turno AO VIVO ([DEF] optional ->
    # False) enquanto o simulador interno (deck completo) funcionava; por
    # isso o auditor dava 0 e o jogo real falhava. Placeholders bastam pros
    # checks de "tem carta no deck?" -- em jogo real o deck nunca esta vazio
    # (deck vazio = derrota imediata), e nada no caminho ao vivo compra do
    # gs.deck de verdade (o jogo C# resolve as compras). Plugin novo (12/07)
    # manda deckCount real; 0 = plugin antigo, cai no fallback de 10.
    data_dummy = {"name": "?", "type": "CHARACTER", "cost": 1, "power": 0,
                  "text": "", "color": "", "sub_types": "", "life": 0,
                  "has_trigger": False}
    n_deck = player.deckCount if player.deckCount > 0 else 10
    gs.deck = [_make_card("UNKNOWN-000", data_dummy) for _ in range(n_deck)]
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

    # full_deck_census (curva completa, base do posture() aggressive/control/
    # midrange): achado 14/07 -- nunca era populado ao vivo, entao posture()
    # sempre caia no fallback 'midrange' pra QUALQUER deck (Kid, Imu, tanto
    # faz). Mesmo lookup lider->arquivo .deck ja usado pra OpponentModel
    # (bridge.opponent_model_for_leader) -- aproximacao (nao garante bater se
    # o usuario customizar a lista), mas e a MESMA decklist que ja usamos pra
    # tudo mais. Sem match (lider desconhecido) fica None -- posture() ja
    # degrada pra 'midrange' nesse caso, comportamento antigo preservado.
    if gs.leader is not None:
        cards = bridge.deck_cards_for_leader(gs.leader.code)
        if cards:
            from optcg_engine.decision_engine import (
                deck_census, compute_game_plan_from_cards)
            gs.full_deck_census = deck_census(cards)
            # full_deck_plan (win-con/trash_target) e full_deck_profile
            # (arquetipo+eixos+papeis) UMA VEZ do deck INTEIRO -- pedido do
            # usuario 14/07: o bot deve ler isso antes da partida e lembrar
            # em TODA decisao, como um jogador humano conhece o proprio
            # deck desde o T1 (nao so o que ja comprou). compute_game_plan/
            # deck_profile_for (decision_engine.py) preferem estes campos
            # quando presentes.
            gs.full_deck_plan = compute_game_plan_from_cards(cards)
            try:
                from deck_profile import build_profile_from_codes
                gs.full_deck_profile = build_profile_from_codes(
                    [c.code for c in cards] + [gs.leader.code])
            except Exception:
                gs.full_deck_profile = None

    return gs


# ── Endpoints ─────────────────────────────────────────────────────────────────

class RevealRequest(BaseModel):
    zone: str            # opp_hand | opp_life | own_life | opp_deck
    uids: list[int] = [] # deckUniqueId das cartas que o jogo MOSTROU ao bot


@app.post("/reveal")
def reveal(req: RevealRequest):
    """Plugin reporta cartas cuja identidade o jogo revelou ao bot (Arlong
    revela mao, peek de vida/deck, ConfirmRevealedCard etc.). Fica na
    MatchMemory ate o fim da partida; _dto_to_gs re-injeta a identidade
    real dessas cartas nos /decide seguintes (persistencia da memoria de
    reveals -- ver match_memory.py). Chamada C# no plugin: pendente."""
    novos = _match_memory.note(req.zone, req.uids)
    write_event("reveal", new_decision_id(), match_id=_live_match_id,
                zone=req.zone, uids=req.uids, novos=novos,
                memory=_match_memory.snapshot())
    return {"ok": True, "novos": novos, "memory": _match_memory.snapshot()}


class MulliganRequest(BaseModel):
    hand: list[CardDto] = []


class TurnOrderRequest(BaseModel):
    deckCodes: list[str] = []


@app.post("/turn_order")
def turn_order(req: TurnOrderRequest):
    """Bot ganhou o dado: 1o ou 2o pela curva do deck (engine decide)."""
    try:
        bridge = _get_bridge()
        out = bridge.choose_turn_order(req.deckCodes)
        print(f"[DEF] turn_order -> {out}", flush=True)
        return out
    except Exception:
        import traceback
        traceback.print_exc()
        return {"goFirst": False, "reason": "erro -> segundo (conservador)"}


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
    return {"status": "ok", "decisionLog": str(DECISION_LOG_PATH)}


@app.get("/collection_status")
def collection_status():
    return dict(_collection_status)


class ExecutionReport(BaseModel):
    decisionId: str
    status: str                 # sent | confirmed | failed
    stateAfter: Optional[GameStateDto] = None
    error: Optional[str] = None


class OutcomeReport(BaseModel):
    result: str
    stateFinal: Optional[GameStateDto] = None
    reason: Optional[str] = None
    # Assento do bot no jogo: "p1" (label [You] do combat log) ou "p2"
    # ([Opponent]). Default p1 = plugin antigo. Sem isso o winner do index
    # saia invertido quando o bot controlava o outro lado (achado 22/07).
    botSeat: str = "p1"


@app.post("/execution")
def execution(report: ExecutionReport):
    if report.status not in {"sent", "confirmed", "failed"}:
        raise HTTPException(status_code=400, detail="status de execucao invalido")
    write_event(
        "execution",
        report.decisionId,
        status=report.status,
        state_after=_model_dict(report.stateAfter) if report.stateAfter else None,
        error=report.error,
    )
    if report.status == "failed":
        # Ao vivo (19/07): cobre os casos que o plugin C# ja detecta e
        # reporta (acao repetida 3x sem efeito, 2 falhas seguidas -- ver
        # BotDriver.cs), que antes so apareciam como LogWarning no console
        # da Unity, nunca no mesmo terminal do proxy.
        print(f"[ALERTA] execucao falhou (decisionId={report.decisionId[:8]}): "
              f"{report.error or 'sem motivo informado'}", flush=True)
    return {"ok": True}


class ClientTimeoutReport(BaseModel):
    endpoint: str
    turn: Optional[int] = None


@app.post("/client_timeout")
def client_timeout(report: ClientTimeoutReport):
    """
    Reportado pelo plugin C# quando o HttpClient estoura o timeout (10s)
    esperando resposta de QUALQUER endpoint (/decide, /defense, /choose_target,
    /mulligan, /turn_order). Achado 19/07: antes disso, um timeout de HTTP
    de verdade nao deixava rastro NENHUM em telemetria -- nem "decision" nem
    "execution" saiam pro JSONL (o request nunca completou), entao os gates
    de pending_decisions/timeout_pct do bot_efficiency_report.py nao tinham
    como enxergar isso. So mede o timeout INTERNO da busca Python (join com
    timeout=3s), nao o timeout de rede real do cliente.
    """
    write_event("client_timeout", new_decision_id(), match_id=_live_match_id,
                endpoint=report.endpoint, turn=report.turn)
    print(f"[ALERTA] cliente C# nao recebeu resposta a tempo de {report.endpoint} "
          f"(turno {report.turn})", flush=True)
    return {"ok": True}


@app.post("/outcome")
def outcome(report: OutcomeReport):
    if report.result not in {"win", "loss", "draw", "aborted"}:
        raise HTTPException(status_code=400, detail="resultado invalido")
    write_event("outcome", "match", match_id=_live_match_id, result=report.result,
                state_final=_model_dict(report.stateFinal) if report.stateFinal else None,
                reason=report.reason, bot_seat=report.botSeat)
    if os.environ.get("BOT_AUTO_COLLECT", "1") != "0":
        _collection_status.update(status="running", message="salvando log no banco",
                                  report=None, receipt=None)
        def _collect() -> None:
            try:
                from collect_latest_match import collect_latest
                receipt = collect_latest(DECISION_LOG_PATH, match_id=_live_match_id,
                                          result=report.result,
                                          bot_seat=report.botSeat)
                _collection_status.update(
                    status="success", message="log capturado e salvo no banco",
                    report=receipt.get("report"), receipt=receipt.get("receipt"))
                print(f"[AUTO-COLLECT] OK -> {receipt['report']}", flush=True)
            except Exception as exc:
                _collection_status.update(status="failed", message=str(exc),
                                          report=None, receipt=None)
                print(f"[AUTO-COLLECT] falhou: {exc}", flush=True)
        threading.Thread(target=_collect, daemon=True).start()
    else:
        _collection_status.update(status="disabled", message="coleta automatica desativada",
                                  report=None, receipt=None)
    return {"ok": True}


def _record_aux_decision(kind: str, state_before: dict, legal_actions: list,
                         chosen_action: dict, response: dict, **context) -> dict:
    """Envelope comum para decisoes fora da Main Phase; nao decide nada."""
    decision_id = new_decision_id()
    out = {**response, "decisionId": decision_id}
    write_event("decision", decision_id, match_id=_live_match_id, decision_kind=kind,
                phase=context.pop("phase", kind), state_before=state_before,
                scored_actions=legal_actions, chosen_action=chosen_action,
                response=out, **context)
    return out


@app.post("/mulligan")
def mulligan(req: MulliganRequest):
    """
    Decide mulligan da mao inicial usando o engine (_mulligan_decision).
    Resposta: {"mulligan": bool, "reason": str}
    """
    global _live_match_id
    started = time.perf_counter()
    _live_match_id = new_decision_id()
    try:
        # Partida nova: limpa recusas da partida anterior. Sem isso, uma
        # ativacao recusada no turno N da partida passada continuava
        # excluida no turno N de TODAS as partidas seguintes do mesmo
        # processo (o set e chaveado por (codigo, turno), sem nocao de jogo).
        _declined_optional.clear()
        _match_memory.reset()  # reveals sao por partida
        match = _get_match()
        hand_cards = [c for c in (_make(d) for d in req.hand) if c]
        if not hand_cards:
            return {"mulligan": False, "reason": "mao vazia/desconhecida — keep"}
        deve_trocar, resumo = match._mulligan_decision(hand_cards, deck=None)
        chosen = "mulligan" if deve_trocar else "keep"
        return _record_aux_decision(
            "mulligan", {"hand": [_model_dict(c) for c in req.hand]},
            [{"type": "keep", "eligible": True}, {"type": "mulligan", "eligible": True}],
            {"type": chosen}, {"mulligan": bool(deve_trocar), "reason": resumo},
            latency_ms=round((time.perf_counter() - started) * 1000, 3))
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
    started = time.perf_counter()
    try:
        from optcg_engine.decision_engine import DecisionEngine
        bridge = _get_bridge()
        gs     = _dto_to_gs(req.state.bot, req.state.turnNumber)
        opp_gs = _dto_to_gs(req.state.opp, req.state.turnNumber, hide_hidden=True)

        out = {"blockerId": 0, "counterIds": [], "useTrigger": False, "useReaction": False}
        decision_trace = {}

        if req.phase == "blocker":
            engine = DecisionEngine(gs, opp_gs)
            blocker = engine.should_use_blocker(req.attackerPower)
            if blocker is not None:
                out["blockerId"] = getattr(blocker, '_deck_uid', 0)
            print(f"[DEF] blocker atk={req.attackerPower} -> "
                  f"{blocker.name if blocker else 'NAO bloqueia'}", flush=True)

        elif req.phase == "counter":
            out["counterIds"] = bridge.select_counter_cards(
                gs, req.attackerPower, req.defenderPower, opp_gs=opp_gs,
                defender_uid=req.defenderId, trace_out=decision_trace)
            print(f"[DEF] counter atk={req.attackerPower} def={req.defenderPower} "
                  f"-> {len(out['counterIds'])} cartas", flush=True)

        elif req.phase == "trigger":
            out["useTrigger"] = bool(bridge.resolve_trigger_choice(gs, req.triggerCode, opp_gs))
            print(f"[DEF] trigger {req.triggerCode} -> {out['useTrigger']}", flush=True)

        elif req.phase == "reaction":
            out["useReaction"] = bridge.resolve_reaction(
                gs, opp_gs, req.attackerPower, req.defenderPower,
                defender_uid=req.defenderId, actor_code=req.triggerCode)
            print(f"[DEF] reaction atk={req.attackerPower} def={req.defenderPower} "
                  f"defId={req.defenderId} -> {out['useReaction']}", flush=True)

        elif req.phase == "optional":
            # Efeito opcional com custo no proprio turno do bot
            out["useReaction"] = bridge.resolve_optional_effect(
                gs, opp_gs, actor_code=req.triggerCode)
            if not out["useReaction"] and req.triggerCode:
                _declined_optional.add((req.triggerCode, req.state.turnNumber))
            print(f"[DEF] optional -> {out['useReaction']}", flush=True)

        if req.phase == "blocker":
            legal = [{"type": "no_blocker", "eligible": True}] + [
                {"type": "blocker", "card_uid": getattr(c, '_deck_uid', 0),
                 "card_code": c.code, "eligible": True}
                for c in gs.blockers_active()]
        elif req.phase == "counter":
            legal = ([{"type": "no_counter", "eligible": True}]
                     + decision_trace.get("legal_actions", []))
        else:
            legal = [{"type": "decline", "eligible": True},
                     {"type": "accept", "eligible": True}]
        chosen = {"type": req.phase, "blocker_id": out["blockerId"],
                  "counter_ids": out["counterIds"],
                  "accepted": out["useTrigger"] or out["useReaction"]}
        return _record_aux_decision(
            "defense", _model_dict(req.state), legal, chosen, out,
            phase=req.phase, turn=req.state.turnNumber,
            attacker_power=req.attackerPower, defender_power=req.defenderPower,
            defender_id=req.defenderId, actor_code=req.triggerCode,
            latency_ms=round((time.perf_counter() - started) * 1000, 3))

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
    started = time.perf_counter()
    try:
        bridge = _get_bridge()
        gs     = _dto_to_gs(req.state.bot, req.state.turnNumber)
        opp_gs = _dto_to_gs(req.state.opp, req.state.turnNumber, hide_hidden=True)

        # Cronometro proprio (nao so o `started` do endpoint inteiro):
        # achado real 20/07 (partida ao vivo) -- 2 chamadas de /choose_target
        # ficaram presas 162.7s e 169.6s (client_timeout disparou em uma
        # delas) enquanto outras dezenas de decisoes no MESMO intervalo
        # processaram normal, em milissegundos -- nao foi o processo/
        # maquina travando (nesse caso tudo ficaria preso junto), foi ALGO
        # ESPECIFICO nessas 2 chamadas. Sem instrumentacao dedicada na hora,
        # so da pra reconstruir isso post-mortem pelo timestamp (o que fiz
        # pra achar o episodio acima) -- essa medicao permite pegar o
        # PROXIMO caso ja com aviso na hora, no console/session log.
        tgt_started = time.perf_counter()
        out = bridge.order_target_candidates(
            gs, opp_gs,
            [{"id": c.id, "zone": c.zone, "code": c.code} for c in req.candidates],
            attacker_power=req.attackerPower,
            defender_uid=req.defenderId,
            actor_code=req.actorCode)
        tgt_ms = round((time.perf_counter() - tgt_started) * 1000, 3)
        zonas = sorted({c.zone for c in req.candidates})
        print(f"[TGT] {len(req.candidates)} candidatos (actor={req.actorCode} "
              f"atk={req.attackerPower} def={req.defenderId} zonas={zonas}) -> ordem {out[:5]}",
              flush=True)
        if tgt_ms > 2000:
            print(f"[ALERTA] order_target_candidates demorou {tgt_ms:.0f}ms "
                  f"(turno {req.state.turnNumber}, actor={req.actorCode}, "
                  f"{len(req.candidates)} candidatos, zonas={zonas})", flush=True)
        # Diagnostico 07/07: confirmar se um redirect (attackerPower>0) esta
        # escolhendo o proprio alvo original (no-op) por falta de opcao —
        # ajuda a achar se a ability do Teach passa por /defense phase=reaction
        # antes disso ou vai direto pro choose_target sem gate de aceitar/recusar.
        if req.attackerPower > 0 and req.defenderId and out and out[0] == req.defenderId:
            print(f"[TGT][AVISO] top escolhido == alvo original (defId={req.defenderId}) "
                  f"-- possivel redirect sem efeito (no-op)", flush=True)
        legal = [{"type": "target", "target_id": c.id, "zone": c.zone,
                  "card_code": c.code, "eligible": True} for c in req.candidates]
        return _record_aux_decision(
            "target", _model_dict(req.state), legal,
            {"type": "target_order", "ordered_ids": out}, {"orderedIds": out},
            phase="target", turn=req.state.turnNumber, actor_code=req.actorCode,
            attacker_power=req.attackerPower, defender_id=req.defenderId,
            latency_ms=round((time.perf_counter() - started) * 1000, 3))

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
    decision_id = new_decision_id()
    trace = {}

    def finish(payload: dict, reason: str) -> dict:
        out = {**payload, "decisionId": decision_id}
        write_event(
            "decision",
            decision_id,
            match_id=_live_match_id,
            decision_kind="main",
            phase="main",
            turn=state.turnNumber,
            state_before=_model_dict(state),
            scored_actions=trace.get("scored_actions", []),
            chosen_action=trace.get("chosen_action"),
            search_values=trace.get("search_values", []),
            selection=trace.get("selection", reason),
            timed_out=trace.get("timed_out", False),
            priority=trace.get("priority"),
            can_lethal=trace.get("can_lethal"),
            opp_combo_threat=trace.get("opp_combo_threat"),
            engine_error=trace.get("engine_error"),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            response=out,
            reason=reason,
        )
        # Marcadores AO VIVO (19/07): antes so apareciam rodando
        # bot_efficiency_report.py depois da partida. "sem acao elegivel"
        # e "engine_error" sao os 2 sinais reais de "bot nao sabe o que
        # fazer" -- imprimir na hora, no mesmo console/session log que
        # ja registra tudo (ver _TeeStream acima).
        if trace.get("engine_error"):
            print(f"[ALERTA] motor quebrou durante a busca (turno {state.turnNumber}): "
                  f"{trace['engine_error']}", flush=True)
        elif reason == "sem acao elegivel":
            print(f"[ALERTA] bot sem acao elegivel (turno {state.turnNumber}) "
                  f"-- hand={len(state.bot.hand)} don={state.bot.activeDon}", flush=True)
        if trace.get("timed_out"):
            print(f"[ALERTA] busca do Turn Planner nao terminou a tempo "
                  f"(turno {state.turnNumber}, timeout)", flush=True)
        # O limiar de "ameaca grande o suficiente" e decidido em
        # analysis_priority() (decision_engine.py), nao aqui -- so formata
        # pra print quando o engine ja decidiu que e PREVENT_COMBO, evita
        # duplicar o limiar (regra "sem dois motores").
        if trace.get("priority") == "PREVENT_COMBO":
            combo = trace.get("opp_combo_threat") or {}
            print(f"[ALERTA] oponente pode virar o jogo (turno {state.turnNumber}): "
                  f"reanima ate {combo.get('magnitude')} corpos do trash "
                  f"(threat_power={combo.get('threat_power')})", flush=True)
        return out

    started = time.perf_counter()
    try:
        bridge = _get_bridge()
        match  = _get_match()
        gs     = _dto_to_gs(state.bot, state.turnNumber)
        opp_gs = _dto_to_gs(state.opp, state.turnNumber, hide_hidden=True)

        # So tipos que o plugin sabe executar — os demais sao pulados pelo
        # bridge em vez de encerrar o turno. exclude_activate_codes: ativacoes
        # opcionais ja recusadas ESTE turno (ver _declined_optional acima) —
        # sem isso o Turn Planner reoferece a mesma 'activate' de score alto
        # pra sempre, sem nunca cair pra proxima acao da lista.
        excluir = {code for (code, t) in _declined_optional if t == state.turnNumber}
        action = bridge.choose_action(gs, opp_gs, match, timeout=3.0,
                                      allowed_types={"play", "attack",
                                                     "attach_don", "activate"},
                                      exclude_activate_codes=excluir,
                                      trace_out=trace)

        if action is None:
            return finish({"type": "end_turn", "cardId": 0, "targetId": 0,
                           "donToAttach": 0}, "sem acao elegivel")

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
                return finish({"type": "end_turn", "cardId": 0, "targetId": 0,
                               "donToAttach": 0}, "play sem uid executavel")

        elif action_type == "attack" and len(action) > 2:
            attacker = action[2]
            card_id = getattr(attacker, '_deck_uid', 0)
            if card_id == 0:
                # Lider do bot nao tem uid do board — usa o uid do proprio leader dto
                if attacker is gs.leader:
                    card_id = getattr(gs.leader, '_deck_uid', 0)
                if card_id == 0:
                    return finish({"type": "end_turn", "cardId": 0, "targetId": 0,
                                   "donToAttach": 0}, "atacante sem uid executavel")

            ttype = action[3] if len(action) > 3 else 'leader'
            if ttype == 'character' and len(action) > 4 and action[4] is not None:
                target_id = getattr(action[4], '_deck_uid', 0)
                if target_id == 0:
                    return finish({"type": "end_turn", "cardId": 0, "targetId": 0,
                                   "donToAttach": 0}, "alvo sem uid executavel")
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
                return finish({"type": "end_turn", "cardId": 0, "targetId": 0,
                               "donToAttach": 0}, "attach_don invalido")

        elif action_type == "activate" and len(action) > 2:
            # [Activate: Main] de lider/personagem/stage em campo (ex:
            # Laffitte OP09-095 — search). O jogo valida e paga o custo.
            card = action[2]
            card_id = getattr(card, '_deck_uid', 0)
            if card_id == 0:
                if card is gs.leader:
                    card_id = getattr(gs.leader, '_deck_uid', 0)
                if card_id == 0:
                    return finish({"type": "end_turn", "cardId": 0, "targetId": 0,
                                   "donToAttach": 0}, "activate sem uid executavel")

        else:
            return finish({"type": "end_turn", "cardId": 0, "targetId": 0,
                           "donToAttach": 0}, "tipo nao executavel")

        return finish({"type": action_type, "cardId": card_id,
                       "targetId": target_id, "donToAttach": don_attach},
                      "acao escolhida")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ALERTA] excecao no /decide (turno {state.turnNumber}): {e}", flush=True)
        write_event(
            "decision_error", decision_id, match_id=_live_match_id, turn=state.turnNumber,
            state_before=_model_dict(state), error=str(e),
            scored_actions=trace.get("scored_actions", []),
        )
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
