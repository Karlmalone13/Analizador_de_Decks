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

# ── Ações enviadas ao jogo e confirmadas SEM efeito neste turno ───────────────
# Achado real 26/07 (log 22.24.06, match b3484a93 -- Barba Negra OP09-093,
# turno 6): mesmo mecanismo do _declined_optional acima, mas para quando a
# ação FOI enviada (não recusada por custo) e o próximo estado estável do
# jogo real confirmou que nada mudou (ver /execution abaixo, status="failed").
# Sem isso, a mesma 'activate' (mesmo card_uid) era reoferecida com o MESMO
# score alto até o guard "ação repetida 3x" do BotDriver.cs encerrar o turno
# inteiro -- 1 ação quebrada queimava o turno todo (sem outros ataques/jogadas)
# em vez de só sair da lista de candidatos. Chave: (type, card_code, card_uid,
# target_uid, turno) -- inclui card_uid porque o bug real era a 2ª cópia da
# mesma carta (uid diferente) nunca chegar a ser tentada.
_failed_actions_this_turn: set[tuple] = set()
_live_match_id = new_decision_id()
_match_has_decisions = False
_match_has_outcome = False
_decision_context: dict[str, dict] = {}


def _resource_snapshot(state: dict | None) -> dict | None:
    """Ledger observavel de uma ponta da transicao; nao decide nada."""
    if not state:
        return None
    side = state.get("bot", state)
    board = side.get("board") or []
    leader = side.get("leader") or {}
    attached = sum(int(c.get("donAttached", 0) or 0) for c in board)
    attached += int(leader.get("donAttached", 0) or 0)
    active = int(side.get("activeDon", 0) or 0)
    rested = int(side.get("restedDon", 0) or 0)
    return {
        "active_don": active,
        "rested_don": rested,
        "attached_don": attached,
        "don_on_field": active + rested + attached,
        "hand": len(side.get("hand") or []),
        "board": len(board),
        "life": len(side.get("life") or []),
        "deck": side.get("deckCount"),
    }


def _transition_observation(before: dict | None, after: dict | None,
                            chosen: dict | None) -> dict | None:
    b, a = _resource_snapshot(before), _resource_snapshot(after)
    if b is None or a is None:
        return None
    delta = {key: a[key] - b[key] for key in
             ("active_don", "rested_don", "attached_don", "don_on_field",
              "hand", "board", "life")}
    action_type = (chosen or {}).get("type")
    useful_signals = {
        "drew_net_cards": max(0, delta["hand"]),
        "developed_board": max(0, delta["board"]),
        "spent_field_don": max(0, -delta["don_on_field"]),
        "attached_don": max(0, delta["attached_don"]),
        "life_lost": max(0, -delta["life"]),
    }
    return {"action_type": action_type, "before": b, "after": a,
            "delta": delta, "utility_signals": useful_signals}

# Memoria de reveals DA PARTIDA (persistencia entre /decide -- ver
# match_memory.py e MEMORIA_REVEALS.md). Populada pelo /reveal, resetada no
# /mulligan, consumida por _dto_to_gs(hide_hidden=True).
from match_memory import MatchMemory, ZONES as _MEMORY_ZONES
_match_memory = MatchMemory()


# ── Pondering (pensar no turno do oponente) ──────────────────────────────────
# Design aprovado no bloco HANDOFF 478 (sessao local, 09/08/2026), implementado
# aqui (bloco 479/480). NENHUM teste ao vivo ainda -- flag OFF por padrao,
# mesmo padrao de BOT_AUTO_COLLECT. Ideia: usar o tempo ocioso do bot durante
# o turno do OPONENTE (server.py ja recebe eventos nesse periodo via /defense)
# pra pre-calcular a decisao do PROXIMO turno do bot em background, e servir
# do cache em /decide se o estado real bater com o que foi ponderado.
import hashlib
import json

PONDER_ENABLED = os.environ.get("OPTCG_PONDER_ENABLED", "0") == "1"
PONDER_TIMEOUT_SECONDS = 9.0  # orcamento maior que /decide (3.0s) -- tempo ocioso real

_ponder_match = None            # OPTCGMatch DEDICADO -- NUNCA o singleton de _get_match()
_ponder_lock = threading.Lock()
_ponder_result: Optional[dict] = None   # {trigger_turn, fingerprint, payload, reason, trace}
_ponder_generation = 0          # bump em /mulligan e a cada novo gatilho -- invalida threads velhas


def _get_ponder_match():
    """Instancia PROPRIA de OPTCGMatch pro pondering -- achado de concorrencia
    do bloco 478 (leitura direta do codigo): OPTCGMatch._simulate_sequence_
    values usa self._suppress_replay_log como flag mutavel de INSTANCIA: se
    a thread de pondering e a requisicao real ao vivo compartilhassem a
    MESMA instancia (_get_match(), singleton), seria uma corrida de verdade.
    Mesmo padrao de _get_match(), so que num singleton SEPARADO."""
    global _ponder_match
    if _ponder_match is None:
        from optcg_engine.decision_engine import OPTCGMatch
        bridge = _get_bridge()
        decks = bridge.list_decks()
        if not decks:
            raise RuntimeError("Nenhum .deck encontrado para inicializar o match de pondering")
        deck_tuple = bridge.load_sim_deck(decks[0])
        _ponder_match = OPTCGMatch(deck_tuple, deck_tuple)
        _ponder_match.setup()
    return _ponder_match


def ponder_fingerprint(bot: "PlayerDto", opp: "PlayerDto", memory: MatchMemory) -> str:
    """Hash sha256 do estado que _dto_to_gs realmente consome pros DOIS
    lados, canonicalizado via json.dumps(sort_keys=True) -- EXCLUI
    turnNumber (bot/opp nao incluem o campo, e a checagem de turno vive
    separada em _try_consume_ponder, pra manter o motivo de miss
    diagnosticavel) e os exclude-sets (_declined_optional/_failed_actions_
    this_turn, tambem checados a parte). memory entra via known(zone) (o
    SET de uids revelados, nao so a contagem de MatchMemory.snapshot() --
    2 sets do MESMO tamanho mas uids DIFERENTES produziriam uma mascara
    diferente em hide_hidden e uma contagem-so nunca pegaria isso)."""
    payload = {
        "bot": _model_dict(bot),
        "opp": _model_dict(opp),
        "memory": {z: sorted(memory.known(z)) for z in _MEMORY_ZONES},
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _trigger_pondering(state: "GameStateDto") -> None:
    """Dispara o job de pondering em background. Chamado de /defense
    quando phase in (blocker, counter, trigger) -- unico sinal ja
    confiavel de "e o turno do OPONENTE" (server.py:702-704 ja usa o
    mesmo sinal pra is_active_turn). Cada chamada bump a generation
    (invalida qualquer job anterior ainda rodando -- sempre pondera
    contra o estado mais recente conhecido, nunca escreve por cima de um
    resultado mais novo)."""
    global _ponder_generation
    if not PONDER_ENABLED:
        return
    with _ponder_lock:
        _ponder_generation += 1
        generation = _ponder_generation
    fingerprint = ponder_fingerprint(state.bot, state.opp, _match_memory)
    proximo_turno = state.turnNumber + 1
    excluir = {code for (code, t) in _declined_optional if t == proximo_turno}
    excluir_falhas = {key for (key, t) in _failed_actions_this_turn if t == proximo_turno}
    t = threading.Thread(
        target=_ponder_worker,
        args=(state.bot, state.opp, state.turnNumber, generation, fingerprint,
              excluir, excluir_falhas),
        daemon=True)
    t.start()


def _ponder_worker(bot_dto, opp_dto, trigger_turn: int, generation: int,
                   fingerprint: str, excluir: set, excluir_falhas: set) -> None:
    """Roda em thread daemon separada. Copia PROFUNDA de estado: reconstroi
    gs/opp_gs do zero a partir dos DTOs (nunca reusa objetos Card/GameState
    da requisicao /defense real) -- nenhum objeto mutavel do engine e
    compartilhado entre a thread de pondering e a thread da requisicao ao
    vivo. Nunca deixa excecao vazar (mesmo padrao de choose_action._run).

    `fingerprint` (calculado em _trigger_pondering, SINCRONO, antes desta
    thread comecar) so serve pra detectar generation obsoleta cedo -- o
    valor de fato GRAVADO em _ponder_result e RECALCULADO logo abaixo, no
    MESMO instante em que gs/opp_gs sao construidos. Achado 09/08 (revisao
    apos a implementacao): _match_memory (usado por _dto_to_gs pro
    mascaramento hide_hidden) e um global mutavel -- se um /reveal chegar
    no intervalo entre o calculo em _trigger_pondering (thread principal)
    e o gs desta thread ser construido, o hash guardado ficaria
    DESCOLADO do que realmente foi usado pra computar o payload. Recalcular
    aqui garante que o fingerprint persistido SEMPRE reflete o estado
    realmente consumido -- fecha a janela sem precisar de lock extra em
    volta de _match_memory."""
    global _ponder_result
    try:
        bridge = _get_bridge()
        match = _get_ponder_match()
        proximo_turno = trigger_turn + 1
        fingerprint_real = ponder_fingerprint(bot_dto, opp_dto, _match_memory)
        if fingerprint_real != fingerprint:
            # Diagnostico (nao um erro): a memoria de reveals mudou entre o
            # gatilho (thread principal) e este calculo (thread do
            # pondering) -- ex: um /reveal concorrente. Nao invalida nada
            # aqui (fingerprint_real, o recalculado, e o que vale), so
            # exposto pra medir em partida real com que frequencia essa
            # janela e realmente atingida.
            print("[PONDER] fingerprint mudou entre gatilho e calculo "
                  "(memoria de reveals atualizada no meio) -- usando o recalculado",
                  flush=True)
        gs = _dto_to_gs(bot_dto, proximo_turno)
        opp_gs = _dto_to_gs(opp_dto, proximo_turno, hide_hidden=True)
        gs.is_active_turn = True
        opp_gs.is_active_turn = False
        trace: dict = {}
        action = bridge.choose_action(
            gs, opp_gs, match, timeout=PONDER_TIMEOUT_SECONDS,
            allowed_types={"play", "attack", "attach_don", "activate"},
            exclude_activate_codes=excluir, exclude_failed_actions=excluir_falhas,
            trace_out=trace)
        payload, reason, extra_trace = _package_action(action, gs, opp_gs, match, bridge)
        trace.update(extra_trace)
        with _ponder_lock:
            if generation != _ponder_generation:
                return  # invalidado por /mulligan ou gatilho mais novo enquanto calculava
            _ponder_result = {
                "trigger_turn": trigger_turn,
                "fingerprint": fingerprint_real,
                "payload": payload,
                "reason": reason,
                "trace": trace,
            }
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[PONDER-ERR] {e}", flush=True)


def _try_consume_ponder(state: "GameStateDto") -> Optional[dict]:
    """4 checagens em ordem, falha fechada (cai no caminho normal em
    qualquer uma): resultado pronto? exclude-sets do turno atual vazios
    (pondering nao sabia de recusas/falhas que so podem ter acontecido
    DEPOIS, no proprio turno do bot)? turno atual == turno do gatilho + 1?
    fingerprint recalculado bate com o salvo?"""
    if not PONDER_ENABLED:
        return None
    with _ponder_lock:
        cached = _ponder_result
    if cached is None:
        return None
    excluir = {code for (code, t) in _declined_optional if t == state.turnNumber}
    excluir_falhas = {key for (key, t) in _failed_actions_this_turn if t == state.turnNumber}
    if excluir or excluir_falhas:
        return None
    if state.turnNumber != cached["trigger_turn"] + 1:
        return None
    fingerprint = ponder_fingerprint(state.bot, state.opp, _match_memory)
    if fingerprint != cached["fingerprint"]:
        return None
    return cached


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
    # Sinal explicito para o bridge: este estado veio do caminho ao vivo e
    # contem informacao oculta mascarada. Impede inferir a decklist exata do
    # oponente apenas pelo lider (um humano nao conhece essa lista).
    gs.hidden_information_masked = hide_hidden
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

    # full_deck_census/full_deck_plan/full_deck_profile: achado 14/07 (lado
    # proprio) -- nunca era populado ao vivo, entao posture() sempre caia
    # no fallback 'midrange' pra QUALQUER deck (Kid, Imu, tanto faz) e
    # compute_game_plan recalculava do zero. Lado proprio usa a decklist
    # EXATA (bridge.deck_cards_for_leader). Sem match (lider desconhecido)
    # fica tudo None -- fallbacks antigos preservados (posture() degrada
    # pra 'midrange', compute_game_plan recalcula das zonas reveladas).
    #
    # Lado OCULTO (hide_hidden=True, o oponente): achado real 03/08
    # (usuario pediu pra investigar lentidao/timeout da busca ao vivo,
    # bloco HANDOFF 426) -- este lado NUNCA tentava popular nada (nem
    # aproximado), sempre None. Isso nao so forcava o fallback caro em
    # TODA simulacao do turno de resposta do oponente
    # (USE_OPPONENT_RESPONSE_SEARCH, ligado por padrao -- profiling real
    # mostrou 26% do tempo de uma partida so em compute_game_plan_from_cards
    # recalculado a cada clone), como fazia posture() do oponente simulado
    # sempre degradar pra 'midrange' (nunca aggressive/control), mesmo
    # quando ha um deck real conhecido pro lider/cor dele. Corrigido
    # reusando a MESMA decklist aproximada (fallback em 3 camadas: lider
    # exato -> mesma cor -> pool generico) que `opponent_model_for_leader`
    # ja constroi pro OpponentModel/Monte Carlo -- nenhuma informacao nova
    # exposta, so reaproveitando o que ja era permitido inferir.
    if gs.leader is not None:
        cards = None
        if not hide_hidden:
            cards = bridge.deck_cards_for_leader(gs.leader.code)
        else:
            model = bridge.opponent_model_for_leader(
                gs.leader.code, getattr(gs.leader, 'color', ''))
            if model is not None:
                cards = model.full_decklist
        if cards:
            from optcg_engine.decision_engine import populate_full_deck_knowledge
            populate_full_deck_knowledge(gs, cards, gs.leader.code)

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
    context = _decision_context.get(report.decisionId, {})
    state_after = _model_dict(report.stateAfter) if report.stateAfter else None
    write_event(
        "execution",
        report.decisionId,
        match_id=context.get("match_id", _live_match_id),
        status=report.status,
        state_after=state_after,
        transition_observation=_transition_observation(
            context.get("state_before"), state_after, context.get("chosen_action")),
        attack_quality=context.get("attack_quality"),
        error=report.error,
    )
    if report.status in {"confirmed", "failed"}:
        _decision_context.pop(report.decisionId, None)
    if report.status == "failed":
        # Ao vivo (19/07): cobre os casos que o plugin C# ja detecta e
        # reporta (acao repetida 3x sem efeito, 2 falhas seguidas -- ver
        # BotDriver.cs), que antes so apareciam como LogWarning no console
        # da Unity, nunca no mesmo terminal do proxy.
        print(f"[ALERTA] execucao falhou (decisionId={report.decisionId[:8]}): "
              f"{report.error or 'sem motivo informado'}", flush=True)
        # Achado real 26/07 (bloco HANDOFF 370, OP09-093): registra a acao
        # que FALHOU pra /decide excluir da proxima escolha ESTE turno (ver
        # _failed_actions_this_turn acima) -- sem isso o Turn Planner
        # reoferecia a mesma 'activate' ate o guard do BotDriver.cs
        # encerrar o turno inteiro. So se aplica a decisoes de main (com
        # "turn" no contexto -- decisoes auxiliares de mulligan/defense nao
        # usam esse mecanismo hoje).
        turn = context.get("turn")
        ca = context.get("chosen_action") or {}
        if turn is not None and ca.get("type"):
            fail_key = (ca.get("type"), ca.get("card_code"),
                       ca.get("card_uid", 0), ca.get("target_uid", 0))
            _failed_actions_this_turn.add((fail_key, turn))
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
    global _match_has_outcome
    if report.result not in {"win", "loss", "draw", "aborted"}:
        raise HTTPException(status_code=400, detail="resultado invalido")
    write_event("outcome", "match", match_id=_live_match_id, result=report.result,
                state_final=_model_dict(report.stateFinal) if report.stateFinal else None,
                reason=report.reason, bot_seat=report.botSeat)
    _match_has_outcome = True
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
                # Consequencia por decisao (bloco 549): o achado precisa
                # APARECER sozinho aqui. Um relatorio que so existe em
                # disco depende de alguem lembrar de abrir -- foi
                # exatamente a reclamacao do usuario ao criar isso.
                fortes = receipt.get("consequence_strong_findings")
                if fortes:
                    print(f"[AUTO-COLLECT][ATENCAO] {fortes} decisao(oes) com DON alto "
                          f"e retorno ZERO em todo horizonte -- ver "
                          f"{receipt.get('consequence_text')}", flush=True)
                elif fortes == 0:
                    print("[AUTO-COLLECT] consequencia por decisao: nenhuma decisao "
                          "cara sem retorno (bom sinal)", flush=True)
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
    global _match_has_decisions
    decision_id = new_decision_id()
    out = {**response, "decisionId": decision_id}
    write_event("decision", decision_id, match_id=_live_match_id, decision_kind=kind,
                phase=context.pop("phase", kind), state_before=state_before,
                scored_actions=legal_actions, chosen_action=chosen_action,
                response=out, **context)
    _match_has_decisions = True
    _decision_context[decision_id] = {
        "match_id": _live_match_id,
        "state_before": state_before,
        "chosen_action": chosen_action,
    }
    return out


def _package_action(action: Optional[tuple], gs, opp_gs, match, bridge) -> tuple[dict, str, dict]:
    """Traduz a tuple de acao do engine (score, tipo, carta, ...) pro
    payload {type, cardId, targetId, donToAttach} que o plugin C# executa.
    Extraida do corpo de /decide (achado do design do pondering, bloco
    478/479) pra ser a UNICA fonte de empacotamento -- tanto o caminho ao
    vivo (/decide) quanto o job de pondering chamam esta MESMA funcao,
    nunca duas versoes que podem divergir (regra "1 motor so"/sem
    duplicacao). Retorna (payload, reason, extra_trace) -- extra_trace so
    tem 'attack_quality' quando o tipo e attack (mesmo dado que /decide ja
    expunha em trace["attack_quality"])."""
    fim_generico = ({"type": "end_turn", "cardId": 0, "targetId": 0, "donToAttach": 0}, "", {})

    if action is None:
        payload, _, extra = fim_generico
        return payload, "sem acao elegivel", extra

    action_type = action[1] if len(action) > 1 else "end_turn"
    card_id = 0
    target_id = 0
    don_attach = 0
    extra_trace: dict = {}

    if action_type == "play" and len(action) > 2:
        card = action[2]
        # A carta veio do proprio gs.hand — tem _deck_uid direto
        card_id = getattr(card, '_deck_uid', 0)
        if card_id == 0:
            payload, _, extra = fim_generico
            return payload, "play sem uid executavel", extra

    elif action_type == "attack" and len(action) > 2:
        attacker = action[2]
        card_id = getattr(attacker, '_deck_uid', 0)
        if card_id == 0:
            # Lider do bot nao tem uid do board — usa o uid do proprio leader dto
            if attacker is gs.leader:
                card_id = getattr(gs.leader, '_deck_uid', 0)
            if card_id == 0:
                payload, _, extra = fim_generico
                return payload, "atacante sem uid executavel", extra

        ttype = action[3] if len(action) > 3 else 'leader'
        if ttype == 'character' and len(action) > 4 and action[4] is not None:
            target_id = getattr(action[4], '_deck_uid', 0)
            if target_id == 0:
                payload, _, extra = fim_generico
                return payload, "alvo sem uid executavel", extra
            # ttype == 'leader' -> targetId = 0 (lider oponente)

        # DON a anexar ANTES de declarar. Deficit base sempre; margem de
        # counter so com DON ocioso no plano do turno (match da acesso as
        # jogadas planejadas + reserva de defesa)
        don_attach = bridge.don_for_attack(gs, opp_gs, action, match=match)
        target_power = (opp_gs.leader.power if ttype == 'leader'
                        else getattr(action[4], 'power', 0))
        from optcg_engine.decision_engine import attack_time_power
        planned_power = attack_time_power(attacker, opp_gs) + don_attach * 1000
        extra_trace["attack_quality"] = {
            "attacker_code": attacker.code,
            "target_type": ttype,
            "target_code": getattr(action[4], 'code', None)
                if ttype == 'character' else getattr(opp_gs.leader, 'code', None),
            "power_before_attach": attack_time_power(attacker, opp_gs),
            "don_planned": don_attach,
            "power_planned": planned_power,
            "target_power_before": target_power,
            "planned_gap": planned_power - target_power,
        }

    elif action_type == "attach_don" and len(action) > 3:
        card = action[2]
        card_id    = getattr(card, '_deck_uid', 0)
        don_attach = int(action[3] or 0)
        if card_id == 0 or don_attach <= 0:
            payload, _, extra = fim_generico
            return payload, "attach_don invalido", extra

    elif action_type == "activate" and len(action) > 2:
        # [Activate: Main] de lider/personagem/stage em campo (ex:
        # Laffitte OP09-095 — search). O jogo valida e paga o custo.
        card = action[2]
        card_id = getattr(card, '_deck_uid', 0)
        if card_id == 0:
            if card is gs.leader:
                card_id = getattr(gs.leader, '_deck_uid', 0)
            if card_id == 0:
                payload, _, extra = fim_generico
                return payload, "activate sem uid executavel", extra

    else:
        payload, _, extra = fim_generico
        return payload, "tipo nao executavel", extra

    return ({"type": action_type, "cardId": card_id,
            "targetId": target_id, "donToAttach": don_attach},
           "acao escolhida", extra_trace)


@app.post("/mulligan")
def mulligan(req: MulliganRequest):
    """
    Decide mulligan da mao inicial usando o engine (_mulligan_decision).
    Resposta: {"mulligan": bool, "reason": str}
    """
    global _live_match_id, _match_has_decisions, _match_has_outcome
    global _ponder_result, _ponder_generation
    started = time.perf_counter()
    try:
        # Fecha explicitamente uma tentativa anterior que recebeu decisoes
        # mas nunca chegou a GameOver. Sem isso, a proxima partida criava um
        # novo match_id e deixava outcome coverage artificialmente em 50%.
        if _match_has_decisions and not _match_has_outcome:
            write_event("outcome", "match", match_id=_live_match_id,
                        result="aborted", state_final=None,
                        reason="nova partida iniciou antes de outcome")
        _live_match_id = new_decision_id()
        _match_has_decisions = False
        _match_has_outcome = False
        _decision_context.clear()
        # Partida nova: limpa recusas da partida anterior. Sem isso, uma
        # ativacao recusada no turno N da partida passada continuava
        # excluida no turno N de TODAS as partidas seguintes do mesmo
        # processo (o set e chaveado por (codigo, turno), sem nocao de jogo).
        _declined_optional.clear()
        _failed_actions_this_turn.clear()
        _match_memory.reset()  # reveals sao por partida
        # Pondering (design bloco 478, ponto 6): partida nova invalida
        # qualquer resultado/job em voo da partida ANTERIOR -- bump de
        # generation faz o worker que ainda estiver rodando descartar o
        # proprio resultado ao terminar (checagem em _ponder_worker).
        with _ponder_lock:
            _ponder_result = None
            _ponder_generation += 1
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
        # is_active_turn (ver /decide acima pro achado completo): blocker/
        # counter/trigger so existem quando o OPONENTE ataca (nunca meu
        # turno); optional e "custo no proprio turno do bot" (docstring da
        # fase, sempre meu turno). "reaction" cobre os dois sentidos (bot
        # atacando OU defendendo) -- fica com o default (True) aqui e
        # resolve_reaction/resolve_optional_effect corrigem via
        # actor_defending (defender_uid ja sabe distinguir, ver sim_bridge).
        if req.phase in ("blocker", "counter", "trigger"):
            gs.is_active_turn = False
            opp_gs.is_active_turn = True
            # Pondering (design bloco 478): blocker/counter/trigger so
            # existem quando e o turno do OPONENTE -- mesmo sinal ja usado
            # acima pra is_active_turn, e o unico gatilho confiavel de
            # "tempo ocioso" sem precisar de um endpoint novo. No-op
            # (retorna cedo) quando PONDER_ENABLED=False.
            _trigger_pondering(req.state)
        elif req.phase == "optional":
            gs.is_active_turn = True
            opp_gs.is_active_turn = False

        out = {"blockerId": 0, "counterIds": [], "useTrigger": False, "useReaction": False}
        decision_trace = {}

        if req.phase == "blocker":
            engine = DecisionEngine(gs, opp_gs)
            blocker = engine.should_use_blocker(req.attackerPower)
            if blocker is not None:
                out["blockerId"] = getattr(blocker, '_deck_uid', 0)
            print(f"[DEF] blocker atk={req.attackerPower} -> "
                  f"{blocker.name if blocker else 'NAO bloqueia'}", flush=True)
            # Telemetria 24/07 (usuario: "preparar o rastreamento pra
            # medir tambem as coisas que fizemos hoje"). O caminho
            # OFFLINE (decision_log de OPTCGMatch) nunca logou blocker/
            # counter (achado na fase C desta sessao) -- este endpoint
            # AO VIVO ja logava via _record_aux_decision, mas sem o
            # detalhe de custo/on_ko que decide QUAL blocker sacrificar.
            # Expoe char_value_score vs custo efetivo (com on_ko_value
            # descontado, fase B 24/07) por candidato -- permite medir
            # se/quando o credito do proprio [On K.O.] de fato mudou a
            # escolha numa partida real. on_ko_value e a MESMA funcao
            # reusada por should_use_blocker (decision_engine.py) --
            # nunca duplicar a conta aqui.
            from optcg_engine.decision_engine import on_ko_value
            decision_trace["blocker_candidates"] = [
                {
                    "card_uid": getattr(c, '_deck_uid', 0),
                    "card_code": c.code,
                    "char_value_score": round(float(engine.analyzer.char_value_score(c)), 4),
                    "on_ko_value": round(float(on_ko_value(c.code, opp_gs, owner=gs)), 4),
                }
                for c in gs.blockers_active()
            ]

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
            blocker_candidates=decision_trace.get("blocker_candidates", []),
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
    global _match_has_decisions
    decision_id = new_decision_id()
    trace = {}

    def finish(payload: dict, reason: str) -> dict:
        global _match_has_decisions
        out = {**payload, "decisionId": decision_id}
        state_before = _model_dict(state)
        write_event(
            "decision",
            decision_id,
            match_id=_live_match_id,
            decision_kind="main",
            phase="main",
            turn=state.turnNumber,
            state_before=state_before,
            scored_actions=trace.get("scored_actions", []),
            chosen_action=trace.get("chosen_action"),
            search_values=trace.get("search_values", []),
            line_search=trace.get("line_search"),
            resource_ledger_before=trace.get("resource_ledger_before"),
            latency_segments_ms=trace.get("latency_segments_ms"),
            attack_quality=trace.get("attack_quality"),
            counterfactual_basis=trace.get("counterfactual_basis"),
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
        _match_has_decisions = True
        _decision_context[decision_id] = {
            "match_id": _live_match_id,
            "state_before": state_before,
            "chosen_action": trace.get("chosen_action"),
            "attack_quality": trace.get("attack_quality"),
            "turn": state.turnNumber,
        }
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

        # Pondering (design bloco 478, consumo do ponto 5): checagem ANTES
        # da busca real -- resultado ready + exclude-sets vazios + turno
        # bate + fingerprint bate. Falha fechada em QUALQUER checagem (cai
        # pro caminho normal abaixo, igual sempre funcionou). Telemetria
        # continua sendo escrita normalmente (via finish()), so que com o
        # trace do JOB de pondering em vez de rodar a busca de novo -- o
        # state_before gravado e sempre o da requisicao REAL (nunca o do
        # gatilho), preservando a garantia de auditoria.
        cached = _try_consume_ponder(state)
        if cached is not None:
            trace.update(cached["trace"])
            trace["ponder_hit"] = True
            return finish(cached["payload"], cached["reason"])

        gs     = _dto_to_gs(state.bot, state.turnNumber)
        opp_gs = _dto_to_gs(state.opp, state.turnNumber, hide_hidden=True)
        # GameState.is_active_turn tem default True (classe pura, sem saber
        # de HTTP) -- achado real 27/07 (bloco HANDOFF 374, Katakuri
        # OP11-062 pagando don_minus toda vez que o oponente ataca, mesmo
        # ja vencendo o combate sem buff): _dto_to_gs NUNCA setava isso, e
        # nenhum outro caminho ao vivo tambem -- toda checagem de
        # `timing == 'your'/'opponent'` (ex: when_don_returned de ST34-001,
        # own_turn_only) sempre lia True pros DOIS lados, mesmo durante o
        # turno do oponente. /decide so roda no MEU turno.
        gs.is_active_turn = True
        opp_gs.is_active_turn = False

        # So tipos que o plugin sabe executar — os demais sao pulados pelo
        # bridge em vez de encerrar o turno. exclude_activate_codes: ativacoes
        # opcionais ja recusadas ESTE turno (ver _declined_optional acima) —
        # sem isso o Turn Planner reoferece a mesma 'activate' de score alto
        # pra sempre, sem nunca cair pra proxima acao da lista.
        excluir = {code for (code, t) in _declined_optional if t == state.turnNumber}
        # Acoes ja enviadas e confirmadas SEM efeito neste turno (ver
        # _failed_actions_this_turn acima) -- mesmo raciocinio do excluir
        # de cima, agora pra acoes que FORAM tentadas e nao mudaram o jogo.
        excluir_falhas = {key for (key, t) in _failed_actions_this_turn if t == state.turnNumber}
        # timeout 3.0 -> 5.0 (bloco 511, extensao AO VIVO da camada barata):
        # o limite REAL e o HttpClient do plugin C#, que desiste de QUALQUER
        # endpoint (/decide incluso) so depois de 10s -- confirmado lendo o
        # codigo do plugin, nao suposto. 3.0s era so a margem de seguranca
        # AUTOIMPOSTA aqui (thread.join, nao mata a busca -- so para de
        # ESPERAR e usa o fallback de score imediato ja calculado). Medido
        # em orcamento ao vivo real (N=403 pontos, 3 matchups): pior caso ja
        # passava de 3s MESMO SEM a camada barata (4.6s), e a camada barata
        # soma +36%/+266ms de media -- 5.0s mantem ~5s de folga sob o limite
        # real de 10s e reduz quanto a busca (Monte Carlo) cai pro fallback
        # de score imediato por estouro de tempo, sem chegar perto do teto
        # real. `trace_out["timed_out"]` ja audita isso em partida real.
        action = bridge.choose_action(gs, opp_gs, match, timeout=5.0,
                                      allowed_types={"play", "attack",
                                                     "attach_don", "activate"},
                                      exclude_activate_codes=excluir,
                                      exclude_failed_actions=excluir_falhas,
                                      trace_out=trace)

        payload, reason, extra_trace = _package_action(action, gs, opp_gs, match, bridge)
        trace.update(extra_trace)
        return finish(payload, reason)

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
