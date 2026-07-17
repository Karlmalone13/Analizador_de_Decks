"""
optcg_engine/decision_engine.py
================================
Motor de simulação OPTCG — sistema unificado.

Baseado nas 34k linhas do Assembly-CSharp.dll v1.40a.

Estrutura:
    Card          — carta (estado em jogo)
    GameState     — estado de um jogador
    EffectExecutor — executa efeitos do card_effects_db.json (único ponto)
    DecisionEngine — IA de decisão situacional
    OPTCGMatch    — motor de partida (fases, combate, turnos)
    simular_matchup — pipeline de N partidas

Fluxo de efeitos (baseado no DoV3ActionStep das 34k linhas):
    _play_card() → EffectExecutor.execute(card, trigger='on_play', p, opp)
    _execute_attack() → EffectExecutor.execute(card, trigger='when_attacking', p, opp)
    on_ko → EffectExecutor.execute(card, trigger='on_ko', p, opp)
    your_turn → EffectExecutor.apply_your_turn_buffs(p, opp)
"""

import re
import json
import os
import random
import pandas as pd
from copy import deepcopy as _deepcopy

# ── evaluate_state v2 (item 1 do PLANO_AVALIACAO_E_BUSCA.md) ──────────────────
# Régua ÚNICA de avaliação de estado: genéricos + eixos derivados do perfil do
# deck (deck_profile). Entra como DROP-IN no fim do Turn Planner atrás do flag
# abaixo, pra medir A/B com baseline_metrics antes de virar padrão. Import
# GUARDADO: se deck_profile/deck_analyzer não estiverem no path, cai no
# fallback (só termos genéricos) sem quebrar o motor.
USE_EVAL_V2 = True    # LIGADA 13/07: validação rigorosa (MC=6, n=50, Imu-v2 vs
#                       opp-v1) confirmou ganho SEM regressão nos 3 matchups —
#                       winrate Krieg 0.38→0.40, Kid 0.34→0.36, Teach 0.88→0.96;
#                       dano e %líder sobem nos três. Pesos tunados em
#                       eval_weights.json (dmg 120→180, counter_hand 6→9). Item 1
#                       CONCLUÍDO. (Pesos são globais/Imu-tunados por ora; cache
#                       per-deck = pipeline self-service do item 5, ainda a fazer.)

# Amostras Monte Carlo do Turn Planner por decisão. 6 no jogo real; a tunagem
# (tune_weights.py) baixa pra 4 pra acelerar a BUSCA (a validação final volta
# a 6). Knob global — não muda a régua, só o custo da simulação.
PLANNER_MC_SAMPLES = 6

# ── busca prof.2 / resposta do oponente (item 3 do PLANO_AVALIACAO_E_BUSCA.md) ─
# Depois de simular MINHA linha ate o fim do turno, simula o TURNO INTEIRO de
# resposta do oponente (proprio engine, modo GULOSO -- ver _play_turn_greedy,
# sem aninhar main_phase/Monte Carlo: evitaria explosao K x MC x K x MC) antes
# de avaliar. E o que torna visivel "ataquei seco -> ele countera barato e
# devolve" vs "anexei DON -> passa/drena counter", que a foto no fim do MEU
# turno sozinha nao capta. Knob global, mesmo padrao do USE_EVAL_V2 -- liga por
# padrao pro simulador OFFLINE (self-play/gauntlet/tunagem), onde o
# OpponentModel tem decklist REAL dos dois lados. NAO esta fiado no caminho AO
# VIVO ainda (choose_action/sim_bridge): o /decide hoje nao chama
# _simulate_sequence_once nenhuma vez (decide so pelo score imediato de
# _generate_and_score_actions) porque o OPTCGMatch ao vivo (server.py
# _get_match) usa um deck PLACEHOLDER pros dois lados (so pra ter a
# maquinaria) -- ligar a busca ali com esse deck errado geraria previsao de
# mao/vida do oponente LIXO, podendo piorar decisao ao vivo. Fio pendente
# documentado no TODO/HANDOFF: precisa de decklist REAL do oponente
# server-side (registro por partida ou lookup leader->arquivo .deck) antes de
# vale a pena religar ao vivo.
USE_OPPONENT_RESPONSE_SEARCH = True
try:
    from deck_profile import build_profile_from_codes as _build_profile_from_codes
except Exception:
    _build_profile_from_codes = None

# Pesos da evaluate_state_v2 — VETOR TUNÁVEL (item 5). O otimizador
# (tune_weights.py) varia estes valores por self-play e escreve o vencedor em
# eval_weights.json; aqui carregamos esse cache se existir. Defaults = os
# priors medidos em 13/07 (que regridem Krieg — por isso a tunagem).
EVAL_WEIGHTS = {
    'dmg': 120.0, 'life_mult': 1.0, 'board_mine': 1.0, 'board_opp': 0.8,
    'opp_blocker': 25.0, 'hand_first': 8.0, 'hand_extra': 3.0,
    'counter_hand': 6.0, 'don_field': 4.0, 'coverage': 7.0,
    'ax_trash': 0.05, 'ax_reanim': 12.0, 'ax_inversion': 0.5,
    # win-con JOGÁVEL (peça-motor na mão + fuel no trash + DON pro custo):
    # "arma carregada". Prior — a tunagem por self-play (item 5) ajusta.
    'wincon_ready': 20.0,
    # sobrevivencia ciente do plano: com win-con de combo caro ainda nao
    # disparavel E vida baixa (risco real de morrer antes), premio por ponto
    # de panico (vida<=3). Prior — tunagem (item 5) ajusta.
    'survival_premium': 25.0,
}
try:
    _wpath = os.path.join(os.path.dirname(__file__), '..', 'eval_weights.json')
    if os.path.exists(_wpath):
        with open(_wpath, encoding='utf-8') as _f:
            # ignora _meta (camada de confiança: procedência, não é peso)
            EVAL_WEIGHTS.update({k: v for k, v in json.load(_f).items()
                                 if k != '_meta'})
except Exception:
    pass


class _SimDeck(list):
    """Deck lazy para simulacao do Turn Planner: contem referencias rasas de
    Card (mesmos objetos do deck real), mas faz deepcopy sob demanda quando
    uma carta e REMOVIDA (pop). Garante que mutacoes aplicadas durante a
    simulacao (just_played, power_buff, etc.) nao contaminem o estado real.
    Insercoes (insert/append) aceitam cartas ja copiadas -- sem wrapper extra.
    Usado em _simulate_sequence_once para evitar deepcopiar ~82 Cards de uma
    vez, economizando ~0.5-0.7ms por chamada sem risco de corrupcao."""

    def pop(self, index=-1):
        return _deepcopy(list.pop(self, index))

    def __deepcopy__(self, memo):
        # Se o proprio _SimDeck for deepcopiado (improvavel no fluxo normal),
        # retorna lista normal -- evita recursao.
        return list(self)
from optcg_engine.opponent_model import OpponentModel
from optcg_engine.deck_census import deck_census
from dataclasses import dataclass, field
from typing import List, Optional
from copy import deepcopy


SIMULATED_WIN_SCORE = 50000.0


# ===========================================================================
# Carrega o banco de efeitos
# ===========================================================================

_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'card_effects_db.json')
_EFFECTS_DB: dict = {}
_EFFECTS_ENRICHED_CACHE: dict = {}

_ANALYSIS_PATH = os.path.join(os.path.dirname(__file__), '..', 'card_analysis_db.json')
_ANALYSIS_DB: dict = {}

_HUMAN_PATTERNS_PATH = os.path.join(os.path.dirname(__file__), '..', 'human_patterns.json')
_HUMAN_PATTERN_BONUS_BY_LEADER: dict = {}
_HUMAN_DEFENSE_BY_LEADER: dict = {}
_HUMAN_PATTERN_MIN_SUPPORT = 2
_HUMAN_PATTERN_MAX_BONUS = 30.0

def _load_effects_db():
    global _EFFECTS_DB
    if _EFFECTS_DB:
        return
    try:
        with open(_DB_PATH, 'r', encoding='utf-8') as f:
            _EFFECTS_DB = json.load(f)
    except FileNotFoundError:
        pass

_load_effects_db()


def _load_human_patterns():
    """Carrega sinais leves de pilotagem humana extraidos dos logs reais."""
    global _HUMAN_PATTERN_BONUS_BY_LEADER, _HUMAN_DEFENSE_BY_LEADER
    if _HUMAN_PATTERN_BONUS_BY_LEADER:
        return
    try:
        with open(_HUMAN_PATTERNS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        _HUMAN_PATTERN_BONUS_BY_LEADER = {}
        return

    by_leader: dict = {}
    defense_by_leader: dict = {}
    for row in data.get('heuristic_candidates', []):
        count = int(row.get('count') or 0)
        if count < _HUMAN_PATTERN_MIN_SUPPORT:
            continue
        leader = row.get('leader') or ''
        pattern = row.get('pattern') or ''
        if not leader or not pattern:
            continue
        leader_bonus = by_leader.setdefault(leader.split('|', 1)[0], {})
        for token in pattern.split(' > '):
            if ':' not in token:
                continue
            kind, code = token.split(':', 1)
            if kind not in ('play', 'activate', 'attack'):
                continue
            key = (kind, code)
            leader_bonus[key] = min(
                _HUMAN_PATTERN_MAX_BONUS,
                leader_bonus.get(key, 0.0) + min(4.0 + count * 2.0, 12.0),
            )
    for leader, rows in data.get('by_defender_response', {}).items():
        leader_code = leader.split('|', 1)[0]
        defense = defense_by_leader.setdefault(leader_code, {'counter': 0, 'blocker': 0})
        for row in rows:
            pattern = row.get('pattern') or ''
            count = int(row.get('count') or 0)
            if pattern.startswith('counter:'):
                defense['counter'] += count
            elif pattern.startswith('blocker:'):
                defense['blocker'] += count
    _HUMAN_PATTERN_BONUS_BY_LEADER = by_leader
    _HUMAN_DEFENSE_BY_LEADER = defense_by_leader


def _load_analysis_db():
    global _ANALYSIS_DB
    if _ANALYSIS_DB:
        return
    try:
        with open(_ANALYSIS_PATH, 'r', encoding='utf-8') as f:
            _ANALYSIS_DB = json.load(f)
    except FileNotFoundError:
        pass

_load_analysis_db()


def get_card_effects(code: str) -> dict:
    """Retorna os efeitos de uma carta pelo código."""
    return _EFFECTS_DB.get(code, {}).get('effects', {})


def _quoted_types_before_play_turn_attack(text: str) -> list[str]:
    marker = 'can attack characters on the turn in which it is played'
    low = (text or '').lower()
    idx = low.find(marker)
    if idx < 0:
        return []
    prefix = text[:idx]
    quoted = re.findall(r'["{]([^"}]+)["}]', prefix)
    out = []
    seen = set()
    for q in quoted:
        q = q.strip()
        key = q.lower()
        if q and key not in seen:
            out.append(q)
            seen.add(key)
    return out


def _enrich_effects_from_analysis_text(code: str, effects: dict) -> dict:
    """
    Corrige lacunas do card_effects_db usando texto ja presente no
    card_analysis_db. Caso real: OP11-031 Jinbe tinha Activate Main no texto,
    mas o effects_db so continha o On Play.
    """
    text = str(_ANALYSIS_DB.get(code, {}).get('text', '') or '')
    low = text.lower()
    if 'activate: main' in low and 'can attack characters on the turn in which it is played' in low:
        am = effects.setdefault('activate_main', {'steps': [], 'once_per_turn': True})
        am.setdefault('steps', [])
        has_step = any(s.get('action') == 'select_grant_can_attack_active_turn'
                       and s.get('allow_played_this_turn')
                       for s in am['steps'])
        if not has_step:
            step = {
                'action': 'select_grant_can_attack_active_turn',
                'allow_played_this_turn': True,
            }
            types = _quoted_types_before_play_turn_attack(text)
            if types:
                step['filter_types'] = types
            am['steps'].append(step)
        if 'may rest this character' in low:
            costs = am.setdefault('costs', [])
            if not any(c.get('type') == 'rest_self' for c in costs):
                costs.append({'type': 'rest_self'})
    return effects


def get_card_game_rules(code: str) -> list[dict]:
    """Regras estruturadas de construcao/setup/identidade da carta."""
    return get_card_effects(code).get('game_rules', {}).get('rules', [])


def get_card_effects(code: str) -> dict:
    """Retorna os efeitos de uma carta pelo codigo."""
    if code in _EFFECTS_ENRICHED_CACHE:
        return _EFFECTS_ENRICHED_CACHE[code]
    effects = deepcopy(_EFFECTS_DB.get(code, {}).get('effects', {}))
    effects = _enrich_effects_from_analysis_text(code, effects)
    _EFFECTS_ENRICHED_CACHE[code] = effects
    return effects


def get_card_flags(code: str) -> dict:
    """
    Retorna as flags estruturadas de classificação da carta (card_analysis_db):
    kos, is_removal, is_blocker, is_searcher, draws, bounces, rests_opponent,
    power_buff, gives_don, gains_life, has_trigger, etc. Fonte única de
    classificação de efeito -- preferir SEMPRE sobre substring no texto cru.
    Retorna dict vazio se a carta não está no banco (degrada sem quebrar).
    """
    return _ANALYSIS_DB.get(code, {})


def compute_game_plan_from_cards(cards: list) -> dict:
    """
    Nucleo puro de compute_game_plan: deriva trash_target/win_con_code/
    don_target de uma lista de Card (nao GameState). Extraido 14/07 pra ser
    compartilhado por `compute_game_plan(p)` (zonas REVELADAS -- muda
    conforme a partida progride, so sabe o que ja viu) e o "plano completo"
    calculado UMA VEZ a partir do deck INTEIRO conhecido (pedido do usuario
    14/07: o bot deve saber arquetipo/combo do proprio deck como um jogador
    humano sabe, nao so o que ja comprou -- ver full_deck_plan_for).

    - trash_target: maior `trash_gte` declarado em `conditions` de
      qualquer carta do deck (ex: Imu — 5 Celestial Dragons com "7+ no
      trash = imune a remoção"). 0 se o deck não tem esse padrão.
    - win_con_code / don_target: carta com maior valor de reanimação via
      `play_from_trash` no próprio `activate_main` (ex: Five Elders,
      reanima até 5). don_target = custo dela. None se o deck não tem
      combo desse tipo.
    """
    trash_gte_contagem: dict[int, int] = {}
    win_con_code = None
    win_con_value = 0
    win_con_cost = None
    vistos = set()
    for c in cards:
        if c.code in vistos:
            continue
        vistos.add(c.code)
        effects = get_card_effects(c.code)
        for trig_data in effects.values():
            conds = trig_data.get('conditions', {}) if isinstance(trig_data, dict) else {}
            if 'trash_gte' in conds:
                v = conds['trash_gte']
                trash_gte_contagem[v] = trash_gte_contagem.get(v, 0) + 1

        am = effects.get('activate_main', {})
        for step in am.get('steps', []):
            if step.get('action') == 'play_from_trash':
                valor = step.get('count', 1)
                if valor > win_con_value:
                    win_con_value = valor
                    win_con_code = c.code
                    win_con_cost = c.cost

    trash_target = 0
    if trash_gte_contagem:
        trash_target = max(trash_gte_contagem, key=lambda v: (trash_gte_contagem[v], -v))

    return {
        'trash_target': trash_target,
        'win_con_code': win_con_code,
        'don_target': win_con_cost,
    }


def compute_game_plan(p: 'GameState') -> dict:
    """
    Plano de jogo do deck. PREFERE o plano COMPLETO ja calculado uma vez do
    deck inteiro (`p.full_deck_plan`, ver full_deck_plan_for -- pedido do
    usuario 14/07: bot deve saber o proprio deck como um jogador humano
    sabe) -- se nao disponivel (contexto sem lookup de deck, ex: testes
    isolados), cai no fallback ANTIGO: escaneia as zonas REVELADAS
    (deck+mão+campo+trash+vida+stage — a união reconstrói a lista completa
    do deck a qualquer momento da partida, já que cartas próprias não saem
    dessas zonas em jogo normal), que só sabe o que já foi visto.
    """
    if getattr(p, 'full_deck_plan', None) is not None:
        return p.full_deck_plan

    zonas = list(p.deck) + list(p.hand) + list(p.field_chars) + list(p.trash) + list(p.life)
    if getattr(p, 'field_stage', None) is not None:
        zonas.append(p.field_stage)
    return compute_game_plan_from_cards(zonas)


def deck_profile_for(p: 'GameState') -> dict | None:
    """
    Perfil do deck (arquetipo + eixos derivados) do jogador p -- MODULE-LEVEL
    (nao metodo de OPTCGMatch) pra poder ser chamado tambem de DecisionEngine
    (avaliar_carta, etc.), que nao tem acesso ao cache que so existia em
    OPTCGMatch._turn_profile_for. Decisao 14/07 (pedido do usuario: parar de
    so consertar o Imu -- o arquetipo universal (deck_profile.py, ja provado
    em Imu/Krieg/Kid/Sakazuki/Moria) so era usado em turn_order e no
    simulador OFFLINE (_evaluate_state_v2); NUNCA nas funcoes que realmente
    decidem jogada/ataque AO VIVO (avaliar_carta etc.) -- por isso so decks
    de combo/reanimacao (o padrao que compute_game_plan reconhece) sentiam
    os consertos recentes.

    PREFERE o perfil COMPLETO ja calculado uma vez do deck inteiro
    (`p.full_deck_profile` -- pedido do usuario 14/07: bot deve saber
    arquetipo/papeis/eixos do proprio deck como um jogador humano sabe, nao
    so o que ja comprou). Sem isso disponivel, cai no fallback ANTIGO:
    identidade instavel = uniao das zonas REVELADAS (mesma logica de
    compute_game_plan; cartas proprias nao saem dessas zonas), cacheado por
    assinatura DIRETO no GameState (p._profile_cache) -- estavel entre as
    MUITAS instancias de DecisionEngine/OPTCGMatch criadas por decisao, mas
    ainda incompleto ate a partida revelar tudo.
    """
    full = getattr(p, 'full_deck_profile', None)
    if full is not None:
        return full
    if _build_profile_from_codes is None:
        return None
    zonas = list(p.deck) + list(p.hand) + list(p.field_chars) + \
        list(p.trash) + list(p.life)
    if getattr(p, 'field_stage', None) is not None:
        zonas.append(p.field_stage)
    if p.leader is not None:
        zonas.append(p.leader)
    codes = [c.code for c in zonas]
    sig = tuple(sorted(codes))
    cache = getattr(p, '_profile_cache', None)
    if cache is not None and cache[0] == sig:
        return cache[1]
    try:
        prof = _build_profile_from_codes(codes)
    except Exception:
        prof = None
    p._profile_cache = (sig, prof)
    return prof


# ===========================================================================
# Estruturas de dados
# ===========================================================================

@dataclass(frozen=True)
class CardData:
    """
    Dados FIXOS de uma carta -- idênticos para QUALQUER cópia física dela
    em qualquer GameState, NUNCA mutados durante uma partida (confirmado
    por levantamento de todas as atribuições do engine em 24/06: zero
    mutações para estes campos especificamente). Uma única instância de
    CardData é compartilhada (referenciada, nunca copiada) por todas as
    cópias da mesma carta -- isso é o que reduz o custo de deepcopy(Card)
    de "recriar um objeto grande" para "copiar uma referência + campos
    pequenos mutáveis" (ver Card abaixo).

    IMPORTANTE: has_rush/has_blocker/has_double_attack/has_banish/
    has_unblockable NÃO estão aqui, mesmo sendo "nativas" no banco --
    elas são MUTADAS em tempo de execução por efeitos de OUTRAS cartas
    (ex: OP10-099 Eustass"Captain"Kid concede Blocker a um Character via
    `card.has_blocker = True`) e são lidas diretamente (sem passar por
    is_blocker()/etc) em ~55 pontos do engine. Separar "nativo" de
    "concedido" exigiria migrar todos esses 55 pontos com risco real de
    regressão silenciosa -- mantidas em Card (mutável) por segurança,
    iguais ao comportamento já existente. has_trigger fica aqui porque
    nunca é concedida por outra carta (sem 'gain_trigger' no banco,
    confirmado em 24/06) -- é genuinamente fixa.
    """
    code: str
    name: str
    card_type: str       # LEADER, CHARACTER, EVENT, STAGE
    color: str
    cost: int = 0
    power: int = 0
    counter: int = 0
    life: int = 0
    sub_types: str = ''
    attribute: str = ''  # Slash, Special, Strike, Wisdom, Ranged (pode ser combinado, ex: "Slash Special")
    card_text: str = ''
    has_trigger: bool = False  # nunca concedida por outra carta -- genuinamente fixa
    is_searcher: bool = False
    draw_power: int = 0
    draw_then_trash: int = 0
    draw_condition: str = 'always'
    has_on_play_ko: bool = False
    has_bounce: bool = False
    don_cond_keywords: tuple = None  # tupla de (keyword, don_req) -- imutável, dict não é hashable/frozen-safe
    has_rest_effect: bool = False
    has_start_of_game: bool = False
    has_power_minus: bool = False
    trash_opp_char: bool = False
    alternate_names: tuple = ()  # aliases oficiais de identidade, imutaveis

    def don_cond_keywords_dict(self) -> dict:
        """Converte a tupla imutável de volta para dict, para uso em _kw_active."""
        return dict(self.don_cond_keywords) if self.don_cond_keywords else {}


@dataclass
class Card:
    """
    Estado MUTÁVEL de uma cópia física de carta nesta partida. `data`
    referencia um CardData COMPARTILHADO (nunca copiado por deepcopy --
    ver __deepcopy__) com os valores base e campos genuinamente fixos.
    Todo o resto aqui (incluindo keywords has_rush/has_blocker/etc, que
    podem ser concedidas por outras cartas) é copiado normalmente.
    """
    data: CardData
    # Keywords (nativas do banco OU concedidas por outra carta em tempo de
    # execução -- ver docstring de CardData sobre por que ficam aqui)
    has_rush: bool = False
    has_rush_character: bool = False  # [Rush: Character] -- so pode atacar Characters no turno em que entra, NUNCA o Leader (mecanica distinta de has_rush)
    has_blocker: bool = False
    has_double_attack: bool = False
    has_banish: bool = False
    has_unblockable: bool = False
    # Estado em jogo
    rested: bool = False
    just_played: bool = False
    rush_character_only_this_turn: bool = False  # True so na janela em que Rush: Character libera o ataque (reseta junto com just_played)
    don_attached: int = 0
    cannot_attack_until: str = ''   # '', 'opp_turn_end', 'opp_end_phase', 'my_next_turn_start' -- trava de ataque (lock_opp_character_attack)
    cannot_block_until: str = ''    # mesma semantica de duracao, para lock_opp_blocker_turn (Limejuice OP09-014, Kuzan OP16-063) -- trava PERSISTENTE de 1 character especifico, DISTINTA de blocker_lock_battle (transitoria, campo todo/filtrado, so 1 batalha)
    unblockable_this_turn: bool = False  # Unblockable CONCEDIDO so neste turno (Sanji ST21-003, Diable Jambe ST01-016, OP13-057) -- DISTINTO de has_unblockable (nativo ou gain_unblockable permanente). Resetado no refresh_phase do DONO. Regra 10-1-7-1 confirma equivalencia: "[Unblockable] prevents the opponent from activating [Blocker] when attacked" -- mesma semantica, so com expiracao.
    rush_this_turn: bool = False  # Rush CONCEDIDO so neste turno (39 cards, ex: EB01-045 Brook, OP01-008 Cavendish) -- mesma logica de unblockable_this_turn. has_rush continua sendo o permanente/nativo (NUNCA tocar -- decisao de 24/06 contra unificar nativo/concedido por risco de regressao em 17 pontos; este campo PARALELO evita o risco). Resetado no refresh_phase.
    double_attack_this_turn: bool = False  # Double Attack CONCEDIDO so neste turno (12 cards) -- mesma logica. has_double_attack permanente intocado.
    blocker_this_turn: bool = False  # Blocker CONCEDIDO so neste turno (6 cards) -- mesma logica. has_blocker permanente intocado.
    can_attack_active: bool = False  # "This Character can also attack active Characters" PERMANENTE (Cavendish OP04-081, Luffy OP04-090) -- keyword nunca implementada antes (achado 27/06, 9 cartas).
    can_attack_active_this_turn: bool = False  # mesma habilidade, mas CONCEDIDA so neste turno via select (Hibari, Gyats, Borsalino, Aramaki, Kuzan, Koby) -- resetada no refresh_phase.
    cannot_be_rested_until: str = ''  # mesma semantica de duracao, para lock_opp_cannot_be_rested (mecanica DISTINTA de cannot_attack)
    effects_negated_until: str = ''  # mesma semantica de duracao, para negate_effect (OP09-093 etc: "negate the effect of up to N of your opponent's Leader/Character"). Serve tanto pra Character quanto pra Leader (p.leader e um Card). Checado no topo de EffectExecutor.execute() -- bloqueia QUALQUER trigger disparado via execute() enquanto ativo (on_play ja resolvido nao e afetado retroativamente, so triggers futuros: activate_main, when_attacking, on_ko, your_turn/opp_turn, trigger). NAO cobre passivas lidas fora de execute() (is_blocker(), immunity, keyword boosts direto de get_card_effects) -- limitacao conhecida, mesmo padrao de divida tecnica ja documentado pro sistema de imunidade (TODO.md).
    immunity_ko_until: str = ''       # imunidade a KO por efeito TEMPORARIA concedida por outro efeito (ex: OP09-033 Nico Robin -- "none of your X type Characters can be K.O.'d by effects until end of opp's next turn"). Mesma semantica de duracao. Checada em is_immune().
    attack_paywall: dict = field(default_factory=dict)  # {'cost_type','cost_amount'} ou {} -- lock_opp_attack_unless_pays (OP08-043): PODE atacar, mas o DONO paga o custo a cada ataque enquanto ativo. Distinto de cannot_attack_until (bloqueio total). Resetado no refresh_phase do dono junto com cannot_attack_until (mesma simplificacao de duration ja usada la).
    frozen_next_refresh: bool = False  # Freeze (lock_opp_character_refresh / lock_self_character_refresh com target='this_card') -- pula APENAS o untap (c.rested=False) na PROXIMA refresh_phase do dono, consumido uma vez (refresh_phase zera este campo, fica rested mesmo se nao tiver sido atacado/restado por outro motivo). DISTINTO de cannot_be_rested_until (que trava o character de FICAR rested -- aqui e o oposto, ele PERMANECE rested ignorando o untap).
    life_face_up: bool = False  # estado valido apenas enquanto a carta esta na zona de Life (ST13/face-up life)
    # Buffs temporários (resetados a cada turno)
    power_buff: int = 0
    base_power_override: Optional[int] = None
    cost_buff: int = 0       # resetado no fim do turno do oponente (duration until_opp_turn_end)
    cost_buff_permanent: int = 0  # nunca resetado (duration permanent, ex: leader_type condicional)
    # Rastreio de combate (achado 15/07, OP12-020 Zoro lider e familia --
    # OP04-047, ST02-010, ST08-013 tambem usam "battles your opponent's
    # Character" como condicao/gatilho): True se esta carta participou de
    # uma batalha CONTRA UM CHARACTER do oponente (nao Leader) neste
    # turno -- setado em _execute_attack apos o alvo final (pos-blocker)
    # ser resolvido. Resetado no refresh_phase do dono, igual just_played.
    battled_opp_character_this_turn: bool = False
    # "cannot attack opponent's Characters with a cost of N or less
    # during this turn" (OP12-020) -- auto-restricao de ALVO, DISTINTA de
    # cannot_attack_until (bloqueio TOTAL de ataque). -1 = sem restricao.
    cannot_attack_opp_chars_cost_lte: int = -1

    def __deepcopy__(self, memo):
        """
        deepcopy customizado: `self.data` é uma REFERÊNCIA compartilhada,
        NUNCA copiada (é frozen/imutável, copiar seria desperdício puro --
        este é o ganho de performance real desta refatoração, medido por
        profiling em 24/06 mostrando 94% do tempo de simulação em
        deepcopy). Todo o resto (campos mutáveis) é copiado normalmente.
        """
        from copy import deepcopy as _dc
        cls = self.__class__
        novo = cls.__new__(cls)
        memo[id(self)] = novo
        novo.data = self.data  # referência compartilhada, SEM copiar
        for campo in ('has_rush', 'has_rush_character', 'has_blocker',
                      'has_double_attack', 'has_banish', 'has_unblockable',
                      'rested', 'just_played', 'rush_character_only_this_turn',
                      'don_attached', 'cannot_attack_until', 'cannot_be_rested_until', 'cannot_block_until',
                      'effects_negated_until',
                      'unblockable_this_turn', 'rush_this_turn', 'double_attack_this_turn', 'blocker_this_turn',
                      'can_attack_active', 'can_attack_active_this_turn',
                      'power_buff', 'base_power_override',
                      'cost_buff', 'cost_buff_permanent', 'frozen_next_refresh',
                      'life_face_up', 'immunity_ko_until',
                      'battled_opp_character_this_turn', 'cannot_attack_opp_chars_cost_lte'):
            setattr(novo, campo, getattr(self, campo))
        for campo in ('_db_base_power', '_attack_power_override'):
            if hasattr(self, campo):
                setattr(novo, campo, getattr(self, campo))
        novo.attack_paywall = self.attack_paywall  # dict sempre REASSIGNED (nunca mutado in-place), referencia compartilhada e segura
        return novo

    # ── Properties de delegação para os campos fixos de CardData ──────────
    # Mantém `card.code`, `card.name`, etc funcionando exatamente como
    # antes em TODOS os pontos do engine que já acessam esses campos --
    # nenhum dos call sites existentes precisa mudar.
    @property
    def code(self) -> str: return self.data.code
    @property
    def name(self) -> str: return self.data.name
    @property
    def card_type(self) -> str: return self.data.card_type
    @property
    def color(self) -> str: return self.data.color
    @property
    def cost(self) -> int: return self.data.cost
    @property
    def power(self) -> int: return self.data.power
    @property
    def counter(self) -> int: return self.data.counter
    @property
    def life(self) -> int: return self.data.life
    @property
    def sub_types(self) -> str: return self.data.sub_types
    @property
    def attribute(self) -> str: return self.data.attribute
    @property
    def card_text(self) -> str: return self.data.card_text
    @property
    def has_trigger(self) -> bool: return self.data.has_trigger
    @property
    def is_searcher(self) -> bool: return self.data.is_searcher
    @property
    def draw_power(self) -> int: return self.data.draw_power
    @property
    def draw_then_trash(self) -> int: return self.data.draw_then_trash
    @property
    def draw_condition(self) -> str: return self.data.draw_condition
    @property
    def has_on_play_ko(self) -> bool: return self.data.has_on_play_ko
    @property
    def has_bounce(self) -> bool: return self.data.has_bounce
    @property
    def don_cond_keywords(self) -> dict: return self.data.don_cond_keywords_dict()
    @property
    def has_rest_effect(self) -> bool: return self.data.has_rest_effect
    @property
    def has_start_of_game(self) -> bool: return self.data.has_start_of_game
    @property
    def has_power_minus(self) -> bool: return self.data.has_power_minus
    @property
    def trash_opp_char(self) -> bool: return self.data.trash_opp_char
    @property
    def alternate_names(self) -> tuple: return self.data.alternate_names

    def effective_cost(self) -> int:
        from optcg_engine.rules_facade import effective_card_cost
        return effective_card_cost(self)

    def _kw_active(self, kw: str, native: bool) -> bool:
        """Keyword ativa se nativa OU condicional a [DON!! ×N] com DON suficiente."""
        if native:
            return True
        cond = self.don_cond_keywords or {}
        req = cond.get(kw)
        if req is not None:
            return getattr(self, 'don_attached', 0) >= req
        return False

    def is_blocker(self) -> bool:
        return self._kw_active('blocker', self.has_blocker) or self.blocker_this_turn

    def is_double_attack(self) -> bool:
        return self._kw_active('double_attack', self.has_double_attack) or self.double_attack_this_turn

    def is_rush(self) -> bool:
        return self._kw_active('rush', self.has_rush) or self.rush_this_turn

    def is_rush_character(self) -> bool:
        return self._kw_active('rush_character', self.has_rush_character)

    def is_banish(self) -> bool:
        return self._kw_active('banish', self.has_banish)

    def effective_power(self, your_turn: bool = True) -> int:
        from optcg_engine.rules_facade import effective_card_power
        return effective_card_power(self, your_turn=your_turn)

    def board_value(self) -> int:
        v = self.power // 1000
        if self.has_rush or self.rush_this_turn:          v += 4
        if self.has_blocker or self.blocker_this_turn:       v += 3
        if self.has_double_attack or self.double_attack_this_turn: v += 3
        if self.has_banish:        v += 2
        if self.has_unblockable:   v += 4
        if self.has_trigger:       v += 2
        return v


@dataclass
class GameState:
    leader: Card
    deck: List[Card] = field(default_factory=list)
    hand: List[Card] = field(default_factory=list)
    field_chars: List[Card] = field(default_factory=list)
    field_stage: Optional[Card] = None
    life: List[Card] = field(default_factory=list)
    don_deck: int = 10
    don_available: int = 0
    don_rested: int = 0
    frozen_don_count: int = 0  # Freeze de DON (lock_opp_don_refresh, OP10-033) -- N do don_rested NAO volta a ficar available na proxima refresh_phase deste jogador. Consumido uma vez (capado por min(frozen_don_count, don_rested) no momento do refresh, depois zerado).
    trash: List[Card] = field(default_factory=list)
    turn: int = 0
    global_turn: int = 0
    # Verdadeiro apenas para o jogador cujo turno esta em andamento. Usado
    # por eventos reativos que distinguem [Your Turn]/[Opponent's Turn].
    is_active_turn: bool = True
    # Auto-restrição "cannot play this turn" (combo set DON active + você se trava).
    # Resetados no início do próprio turno. Valores:
    #   cant_play_from_hand_this_turn: True = não pode jogar NADA da mão
    #   cant_play_chars_this_turn:     True = não pode jogar CHARACTER
    #   cant_play_cost_gte:            int  = não pode jogar com base cost >= N (0 = sem limite)
    cant_play_from_hand_this_turn: bool = False
    cant_play_chars_this_turn: bool = False
    cant_play_cost_gte: int = 0
    cannot_attack_leader_this_turn: bool = False
    cant_take_life_this_turn: bool = False  # ST15-001 Atmos: "cannot add Life cards to your hand using your own effects this turn"
    face_up_life_to_deck: bool = False      # ST13-003 Luffy Leader: face-up life cards go to BOTTOM of deck instead of hand when damaged
    is_first: bool = True
    # Estatísticas
    dmg_dealt: int = 0
    chars_played: int = 0
    counters_used: int = 0
    searchers_used: int = 0
    triggers_activated: int = 0
    full_deck_census: dict = None
    # ids (id(card), nao codigo -- pode haver copias da mesma carta na mao
    # com status de revelacao diferente) das instancias de Card atualmente
    # na mao que foram expostas ao oponente por um efeito de busca com
    # 'reveal' (confirmado pela regra oficial: o padrao "look at N; reveal
    # up to 1 [filtro] and add to hand" expoe a carta especifica escolhida,
    # mesmo sendo o texto mais comum do jogo -- distinto de dano normal na
    # vida, que NUNCA revela, e de busca sem a palavra 'reveal', que tambem
    # nao revela). Removido do set quando a carta sai da mao (jogada,
    # trashada, etc) -- usado pelo OpponentModel para saber quais cartas
    # specificas o oponente certamente tem, em vez de sortear via Monte Carlo.
    revealed_to_opponent: set = field(default_factory=set)
    # Trava TRANSITORIA de Blocker, escopo de UMA UNICA batalha (a que esta
    # sendo resolvida agora). Setada por lock_opp_blocker_battle (efeito
    # [When Attacking] do atacante) e LIMPA pelo proprio _resolve_battle
    # logo depois do block step -- nunca deve sobreviver pra proxima
    # batalha. None = sem trava. dict = {'power_lte'|'power_gte'|'cost_lte': N}.
    blocker_lock_battle: Optional[dict] = None
    end_of_turn_queue: List[dict] = field(default_factory=list)
    pending_play_cost_reductions: List[dict] = field(default_factory=list)
    # "Then, take an extra turn after this one" (achado 16/07, OP05-119,
    # unica carta no banco). Setado pelo executor de take_extra_turn,
    # consumido e resetado pelo loop de simulate() logo apos play_turn().
    extra_turn_pending: bool = False
    # Custos dos Events ativados/jogados NESTE turno (achado 16/07,
    # OP15-002 Lucy: "if you have activated an Event with a base cost of N
    # or more during this turn"). Populado em _play_card() sempre que um
    # EVENT sai da mao, resetado no inicio de cada turno do jogador
    # (refresh_phase, mesmo ponto onde as outras auto-restricoes "this
    # turn" sao limpas).
    events_activated_costs_this_turn: List[int] = field(default_factory=list)

    def __deepcopy__(self, memo):
        """
        Clone enxuto para o Turn Planner. `Card` ja tem __deepcopy__ proprio,
        entao aqui evitamos o caminho generico do dataclass e copiamos apenas
        as zonas/flags do estado.
        """
        from copy import deepcopy as _dc
        cls = self.__class__
        novo = cls.__new__(cls)
        memo[id(self)] = novo

        novo.leader = _dc(self.leader, memo)
        novo.deck = [_dc(c, memo) for c in self.deck]
        novo.hand = [_dc(c, memo) for c in self.hand]
        novo.field_chars = [_dc(c, memo) for c in self.field_chars]
        novo.field_stage = _dc(self.field_stage, memo) if self.field_stage else None
        novo.life = [_dc(c, memo) for c in self.life]
        novo.trash = [_dc(c, memo) for c in self.trash]

        novo.don_deck = self.don_deck
        novo.don_available = self.don_available
        novo.don_rested = self.don_rested
        novo.frozen_don_count = self.frozen_don_count
        novo.turn = self.turn
        novo.global_turn = self.global_turn
        novo.is_active_turn = self.is_active_turn
        novo.cant_play_from_hand_this_turn = self.cant_play_from_hand_this_turn
        novo.cant_take_life_this_turn = self.cant_take_life_this_turn
        novo.face_up_life_to_deck = self.face_up_life_to_deck
        novo.cant_play_chars_this_turn = self.cant_play_chars_this_turn
        novo.cant_play_cost_gte = self.cant_play_cost_gte
        novo.cannot_attack_leader_this_turn = self.cannot_attack_leader_this_turn
        novo.is_first = self.is_first

        novo.dmg_dealt = self.dmg_dealt
        novo.chars_played = self.chars_played
        novo.counters_used = self.counters_used
        novo.searchers_used = self.searchers_used
        novo.triggers_activated = self.triggers_activated
        # full_deck_census e INVARIANTE (setado no setup, nunca mutado durante
        # o jogo) -- compartilhamos a REFERENCIA em vez de deepcopiar o dict
        # inteiro a cada clone do Turn Planner (economiza ~0.1ms por clone
        # sem risco de corrupcao, confirmado por leitura de todos os call sites).
        novo.full_deck_census = self.full_deck_census
        novo.revealed_to_opponent = set(self.revealed_to_opponent)
        novo.blocker_lock_battle = _dc(self.blocker_lock_battle, memo)
        novo.end_of_turn_queue = _dc(self.end_of_turn_queue, memo)
        novo.pending_play_cost_reductions = _dc(self.pending_play_cost_reductions, memo)
        novo.extra_turn_pending = self.extra_turn_pending
        novo.events_activated_costs_this_turn = list(self.events_activated_costs_this_turn)
        return novo

    def known_hand_cards(self) -> List['Card']:
        """
        Subconjunto de `self.hand` que é conhecido pelo oponente (cartas
        reveladas por efeito de busca e que ainda estão na mão). Filtra de
        forma lazy contra `self.hand` em vez de exigir limpeza manual de
        `revealed_to_opponent` em cada um dos pontos do engine onde uma
        carta sai da mão (jogada, trashada, etc) -- mais seguro do que
        arriscar esquecer algum desses pontos e deixar um id() órfão
        apontando para memória já realocada para outra carta.
        """
        ids_na_mao = {id(c) for c in self.hand}
        # remove ids que não correspondem a nenhuma carta atual na mão
        # (carta já saiu -- ex: jogada, trashada). Faz isso aqui (lazy)
        # em vez de em cada ponto de remoção da mão.
        self.revealed_to_opponent &= ids_na_mao
        return [c for c in self.hand if id(c) in self.revealed_to_opponent]

    def life_count(self) -> int:
        return len(self.life)

    def active_chars(self) -> List[Card]:
        return [c for c in self.field_chars
                if not c.rested and (not c.just_played or c.is_rush()
                                     or c.is_rush_character()
                                     or c.rush_character_only_this_turn)]

    def rested_chars(self, attacker: 'Card' = None) -> List[Card]:
        # "This Character can also attack active Characters" (permanente ou
        # so este turno, 9 cartas -- achado 27/06, nunca implementado antes).
        # Sem attacker (uso normal de scoring/heuristica) mantém o
        # comportamento de sempre -- só passa attacker explicitamente nos
        # pontos que decidem o ataque real, pra não arriscar a lógica de
        # múltiplos atacantes do planejador numa mudança apressada.
        if attacker is not None and (attacker.can_attack_active or attacker.can_attack_active_this_turn):
            return list(self.field_chars)
        return [c for c in self.field_chars if c.rested]

    def counter_in_hand(self) -> int:
        return sum(c.counter for c in self.hand if c.counter > 0)

    def blockers_active(self) -> List[Card]:
        elegiveis = [c for c in self.field_chars
                     if c.is_blocker() and not c.rested and not c.cannot_be_rested_until
                     and not c.cannot_block_until]
        lock = self.blocker_lock_battle
        if lock is None:
            return elegiveis
        power_lte = lock.get('power_lte')
        power_gte = lock.get('power_gte')
        cost_lte = lock.get('cost_lte')
        if power_lte is None and power_gte is None and cost_lte is None:
            return []   # sem filtro -- trava o campo inteiro
        def travado(c):
            if power_lte is not None and c.power <= power_lte: return True
            if power_gte is not None and c.power >= power_gte: return True
            if cost_lte is not None and c.cost <= cost_lte: return True
            return False
        return [c for c in elegiveis if not travado(c)]

    def board_score(self) -> int:
        return sum(c.board_value() for c in self.field_chars)

    def estimated_counter(self) -> int:
        return len(self.hand) * 1000

    def can_attack_this_turn(self) -> bool:
        return self.turn > 1

    def don_on_field(self) -> int:
        return self.don_available + self.don_rested


def _play_cost_rule_matches(card: Card, rule: dict) -> bool:
    if card.card_type != 'CHARACTER':
        return False
    if card.cost < rule.get('cost_gte', 0):
        return False
    if rule.get('filter_type') and _norm_type_text(rule['filter_type']) not in _norm_type_text(card.sub_types):
        return False
    if rule.get('filter_name') and rule['filter_name'].lower() not in card.name.lower():
        return False
    return True


def _hand_cost_conditions_match(p: GameState, opp: Optional[GameState],
                                card: Card, conds: dict) -> bool:
    if 'life_lte' in conds and p.life_count() > conds['life_lte']:
        return False
    if 'trash_gte' in conds and len(p.trash) < conds['trash_gte']:
        return False
    if 'events_in_trash_gte' in conds:
        events = sum(1 for c in p.trash if c.card_type == 'EVENT')
        if events < conds['events_in_trash_gte']:
            return False
    if 'leader_power_lte' in conds and p.leader.effective_power(True) > conds['leader_power_lte']:
        return False
    if 'leader_type' in conds:
        if _norm_type_text(conds['leader_type']) not in _norm_type_text(p.leader.sub_types):
            return False
    if 'leader_name_includes' in conds:
        if conds['leader_name_includes'].lower() not in p.leader.name.lower():
            return False
    if 'don_gte' in conds and p.don_on_field() < conds['don_gte']:
        return False
    if 'don_on_field_gte' in conds and p.don_on_field() < conds['don_on_field_gte']:
        return False
    if 'don_on_field_zero_or_gte' in conds:
        n = p.don_on_field()
        if not (n == 0 or n >= conds['don_on_field_zero_or_gte']):
            return False
    if 'other_char_power_gte' in conds:
        candidates = [c for c in p.field_chars if c is not card]
        filter_type = conds.get('other_char_power_gte_type')
        if filter_type:
            candidates = [c for c in candidates
                          if _norm_type_text(filter_type) in _norm_type_text(c.sub_types)]
        filter_names = [n.lower() for n in conds.get('other_char_power_gte_names', [])]
        if filter_names:
            candidates = [c for c in candidates
                          if any(n in c.name.lower() for n in filter_names)]
        power_of = ((lambda c: c.power) if conds.get('other_char_power_uses_base')
                    else (lambda c: c.effective_power(True)))
        if not any(power_of(c) >= conds['other_char_power_gte']
                   for c in candidates):
            return False
    if 'opp_char_power_gte' in conds:
        if opp is None or not any(
                c.power >= conds['opp_char_power_gte'] for c in opp.field_chars):
            return False
    if 'opp_rested_cards_gte' in conds:
        if opp is None:
            return False
        rested = opp.don_rested + sum(1 for c in opp.field_chars if c.rested)
        rested += int(bool(getattr(opp.leader, 'rested', False)))
        rested += int(bool(opp.field_stage and getattr(opp.field_stage, 'rested', False)))
        if rested < conds['opp_rested_cards_gte']:
            return False
    if conds.get('don_on_field_lte_opp'):
        if opp is None or p.don_on_field() > opp.don_on_field():
            return False
    if 'don_fewer_than_opp_by_gte' in conds:
        if opp is None or opp.don_on_field() - p.don_on_field() < conds['don_fewer_than_opp_by_gte']:
            return False
    return True


def effective_hand_play_cost(p: GameState, card: Card,
                             opp: Optional[GameState] = None) -> int:
    """Custo para jogar uma carta da mao no estado simplificado atual."""
    cost = card.effective_cost()
    stage = p.field_stage
    if stage:
        for entry in get_card_effects(stage.code).values():
            for step in entry.get('steps', []):
                if (step.get('action') == 'buff_cost'
                        and step.get('target') == 'own_play_hand'
                        and _play_cost_rule_matches(card, step)):
                    cost -= step.get('amount', 0)
    for rule in p.pending_play_cost_reductions:
        if _play_cost_rule_matches(card, rule):
            cost -= rule.get('amount', 0)
    passive = get_card_effects(card.code).get('passive', {})
    passive_conds = passive.get('conditions', {})
    if (passive_conds
            and _hand_cost_conditions_match(p, opp, card, passive_conds)):
        for step in passive.get('steps', []):
            if step.get('action') == 'debuff_cost' and step.get('target') == 'own_play_self':
                cost -= step.get('amount', 0)
            elif step.get('action') == 'set_play_cost' and step.get('target') == 'own_play_self':
                cost = step.get('amount', cost)
    return max(0, cost)


def consume_play_cost_reductions(p: GameState, card: Card) -> None:
    """Consome buffs one-shot que casam com a carta efetivamente jogada."""
    p.pending_play_cost_reductions = [
        rule for rule in p.pending_play_cost_reductions
        if not _play_cost_rule_matches(card, rule)
    ]


def _norm_type_text(text: str) -> str:
    """Normaliza typos conhecidos vindos do texto bruto da base."""
    return (text or '').lower().replace('whitebeard piratess', 'whitebeard pirates')


def _ko_sentence(card: 'Card') -> str:
    text = ((card.card_text or '') or get_card_flags(card.code).get('text', '')).lower()
    if not text:
        return ''
    text = (text.replace('&lt;', '<').replace('&gt;', '>')
                .replace('＜', '<').replace('＞', '>'))
    cannot_ko = re.search(r"cannot be k\.?o\.?'?d|can't be k\.?o", text)
    if not cannot_ko:
        return ''
    sentence_start = max(text.rfind('.', 0, cannot_ko.start()), text.rfind('\n', 0, cannot_ko.start()))
    sentence_end = text.find('.', cannot_ko.end())
    if sentence_end == -1:
        sentence_end = len(text)
    return text[sentence_start + 1:sentence_end]


def _source_matches_battle_ko_immunity(sentence: str, source_card: Optional['Card']) -> bool:
    if not source_card:
        return True

    src_type = (source_card.card_type or '').upper()
    src_attr = (source_card.attribute or '').lower()

    if 'by leaders' in sentence:
        return src_type == 'LEADER'
    if 'by characters without' in sentence and 'special' in sentence:
        return src_type == 'CHARACTER' and 'special' not in src_attr
    if 'by attribute cards' in sentence:
        return bool(src_attr)

    for attr in ('strike', 'slash', 'special', 'wisdom', 'ranged'):
        if attr in sentence and re.search(rf'by [^.]*(?:<|")?{attr}(?:>|")?[^.]*attribute', sentence):
            return attr in src_attr

    return True


def _ko_immunity_applies_to_context(card: 'Card', ko_context: str | None,
                                    source_card: Optional['Card'] = None) -> bool:
    if ko_context not in ('battle', 'effect'):
        return True

    sentence = _ko_sentence(card)
    if not sentence:
        return True

    battle_only = 'in battle' in sentence
    effect_only = 'by effect' in sentence or "by your opponent's effect" in sentence
    if ko_context == 'battle' and effect_only and not battle_only:
        return False
    if ko_context == 'effect' and battle_only and not effect_only:
        return False
    if ko_context == 'battle' and not _source_matches_battle_ko_immunity(sentence, source_card):
        return False
    return True


def is_immune(card: 'Card', imm_type: str, owner: 'GameState', opp: 'GameState',
              source_is_opp: bool = True, ko_context: str | None = None,
              source_card: Optional['Card'] = None) -> bool:
    """
    True se `card` está imune a `imm_type` ('ko' | 'removal' | 'rest') no
    estado atual. 'rest': autoproteção contra rest forçado por efeito do
    oponente (achado 01/07/2026, OP11-046/OP12-021/OP15-024) -- DISTINTA de
    `cannot_be_rested_until` (trava posta por OUTRA carta via
    `lock_opp_cannot_be_rested`, já checada separadamente).

    Lê a action 'immunity' nos effects da carta (parseada como passive/opp_turn/
    don_conditional). Respeita:
      - source: imunidade "by opponent's effects" (source='opp') só vale quando
        a remoção/KO VEM do oponente (source_is_opp=True). Imunidade 'any' sempre.
      - condição de DON: imunidade sob [DON!! xN] só vale com N DON anexados.
      - condição de turno: imunidade [Opponent's Turn] só vale no turno do oponente
        (= NÃO é o turno do dono da carta).
    KO em batalha vs por efeito: 'ko' cobre ambos aqui (o banco não distingue
    "in battle" vs "by effect" nas 68 cartas — todas são "cannot be K.O.'d").
    """
    effects = get_card_effects(card.code)
    for timing, blk in effects.items():
        if not isinstance(blk, dict):
            continue
        for step in blk.get('steps', []):
            if step.get('action') != 'immunity' or step.get('imm_type') != imm_type:
                continue
            if imm_type == 'ko' and not _ko_immunity_applies_to_context(card, ko_context, source_card):
                continue
            # source
            if step.get('source') == 'opp' and not source_is_opp:
                continue
            # condição de turno: [Opponent's Turn] só no turno do oponente
            if timing == 'opp_turn' and owner is _current_turn_owner(owner, opp):
                continue
            # condição de DON anexado ([DON!! xN])
            don_req = blk.get('don_requirement', 0)
            if don_req and getattr(card, 'don_attached', 0) < don_req:
                continue
            # condições estruturadas (If all DON rested, If life <= N, etc)
            conds = blk.get('conditions') or step.get('conditions')
            if conds and not _immunity_conds_met(conds, card, owner, opp):
                continue
            return True
    # Imunidade TEMPORARIA concedida via grant_ko_immunity_type (ex: OP09-033
    # Nico Robin). Campo immunity_ko_until no Card, setado pelo engine quando
    # o efeito e executado e limpo no refresh_phase do DONO da carta.
    if imm_type == 'ko' and getattr(card, 'immunity_ko_until', ''):
        if source_is_opp:  # imunidade valida contra efeitos do oponente
            return True
    return False


def _current_turn_owner(owner, opp):
    """Heurística leve: quem tem o turno. owner.turn é incrementado no play_turn
    do jogador ativo, então comparamos quem agiu por último. Conservador:
    se indeterminado, retorna None (imunidade de opp_turn vale)."""
    # Sem um flag global de turno acessível aqui, usamos a convenção de que
    # durante a resolução de um ataque, o atacante é opp e o defensor é owner.
    # Para imunidade [Opponent's Turn] do defensor, é o turno do oponente => vale.
    return None


def _immunity_conds_met(conds, card, owner, opp):
    if 'all_don_rested' in conds:
        if owner.don_available > 0:
            return False
    if 'life_lte' in conds:
        if len(owner.life) > conds['life_lte']:
            return False
    if 'life_gte' in conds:
        if len(owner.life) < conds['life_gte']:
            return False
    if 'only_field_type' in conds:
        tipo = conds['only_field_type'].lower()
        if not owner.field_chars or any(tipo not in c.sub_types.lower() for c in owner.field_chars):
            return False
    # Achado 15/07 (OP12-021 Ipponmatsu, "If your Leader has the (Slash)
    # attribute and you have 6 or more rested DON!! cards..."): a imunidade
    # aplicava sempre porque _immunity_conds_met (checador DEDICADO desta
    # funcao, distinto de _check_conditions usado por on_play/main/trigger)
    # nunca tinha esses 2 campos, mesmo com parse_conditions ja gerando-os.
    if 'leader_attribute' in conds:
        my_attr = (getattr(owner.leader, 'attribute', '') or '').lower()
        if conds['leader_attribute'].lower() not in my_attr:
            return False
    if 'don_rested_gte' in conds:
        if owner.don_rested < conds['don_rested_gte']:
            return False
    # "if your opponent has a Leader or Character with a (base) power of N
    # or more" (achado 16/07, OP06-012, ordem invertida "power of N") --
    # distinta de opp_char_power_gte (so campo, checado em _check_conditions
    # noutro lugar): aqui inclui TAMBEM o lider do oponente.
    if 'opp_leader_or_char_power_gte' in conds:
        threshold = conds['opp_leader_or_char_power_gte']
        candidatos = [opp.leader] + list(opp.field_chars)
        if not any(c.power >= threshold for c in candidatos):
            return False
    if 'no_other_named' in conds:
        needle = conds['no_other_named'].lower()
        cost_eq = conds.get('no_other_named_cost_eq')
        outros = [c for c in owner.field_chars
                  if c is not card and needle in c.name.lower()]
        if cost_eq is not None:
            outros = [c for c in outros if c.cost == cost_eq]
        if outros:
            return False
    return True


def is_attack_locked_self(card: 'Card', owner: 'GameState', opp: 'GameState') -> bool:
    """
    True se `card` esta travada para atacar por um efeito PASSIVO PROPRIO
    (cannot_attack_self / cannot_attack_self_unless /
    cannot_attack_own_characters_by_cost), distinto de cannot_attack_until
    (que e trava posta por OUTRA carta via lock_opp_character_attack e ja
    e checada separadamente nos mesmos 6 pontos). Centraliza a logica aqui
    em vez de duplicar em GameAnalyzer/OPTCGMatch -- ambas as classes tem
    acesso a um GameState do dono e um do oponente em todo ponto que
    precisa decidir "esta carta pode atacar?".

    Condicoes suportadas (mesmo vocabulario de _check_conditions, mas
    replicado aqui de forma minima -- so os campos que cannot_attack_self_*
    de fato usa no banco hoje: board_has_power_gte,
    opp_chars_power_gte_count). Se 'conditions' nao foi reconhecida pelo
    parser (campo legado 'condition_text' presente em vez de 'conditions'),
    trata como travado SEMPRE -- mais seguro assumir o lock ativo do que
    liberar o ataque sem confirmar a condicao real.
    """
    effects = get_card_effects(card.code)
    passive = effects.get('passive', {})
    for step in passive.get('steps', []):
        action = step.get('action')
        if action == 'cannot_attack_self':
            return True
        if action == 'cannot_attack_self_unless':
            if 'condition_text' in step and 'conditions' not in step:
                return True  # condicao nao estruturada -- trava por seguranca
            conds = step.get('conditions', {})
            if 'board_has_power_gte' in conds:
                todos = list(owner.field_chars) + list(opp.field_chars)
                if not todos or max(c.effective_power(True) for c in todos) < conds['board_has_power_gte']:
                    return True  # condicao NAO satisfeita -> travada
            if 'opp_chars_power_gte_count' in conds:
                spec = conds['opp_chars_power_gte_count']
                n = sum(1 for c in opp.field_chars if c.effective_power(False) >= spec['power_gte'])
                if n < spec['count']:
                    return True
            # alguma condicao reconhecida e satisfeita (ou nenhuma condicao
            # suportada presente, caso futuro) -- nao trava.
    # mass_lock_conditional e um efeito de OUTRA carta no board (ex: P-084)
    # que trava `card` por filtro de custo -- precisa varrer todo o board
    # do dono (characters + leader) procurando alguma fonte com esse
    # trigger ativo, e nao apenas os efeitos da propria `card` sendo
    # avaliada (P-084 trava as OUTRAS cartas custo 3/4, nao trava P-084
    # nela mesma via este trigger -- P-084 se trava via cannot_attack_self
    # incondicional, ja checado acima).
    fontes_mass_lock = list(owner.field_chars) + [owner.leader]
    for fonte in fontes_mass_lock:
        fonte_effects = get_card_effects(fonte.code)
        mass_lock = fonte_effects.get('mass_lock_conditional')
        if not mass_lock:
            continue
        conds = mass_lock.get('conditions', {})
        leader_is = conds.get('leader_is', '').lower()
        if leader_is and leader_is not in owner.leader.name.lower():
            continue
        costs_alvo = set()
        for s in mass_lock.get('steps', []):
            if s.get('action') == 'cannot_attack_own_characters_by_cost':
                costs_alvo.update(s.get('costs', []))
        if card.cost in costs_alvo:
            return True
    return False


def can_afford_attack_paywall(card: 'Card', owner: 'GameState') -> bool:
    """
    True se `card` PODE atacar apesar de ter `attack_paywall` ativo
    (lock_opp_attack_unless_pays, ex: OP08-043 Edward.Newgate) -- ou se nao
    tem paywall nenhum. Simplificacao deliberada: paga sempre que pode (nao
    modela "vale a pena" como Opponent Reading faria), mesmo padrao do resto
    do engine pra custos de ativacao (so checa viabilidade material).
    """
    paywall = card.attack_paywall
    if not paywall:
        return True
    if paywall.get('cost_type') == 'trash_from_hand':
        return len(owner.hand) >= paywall.get('cost_amount', 1)
    return True


def character_can_attack_now(card: 'Card', owner: 'GameState', opp: 'GameState') -> bool:
    """True if a field character can be offered as an attacker right now."""
    if getattr(card, 'rested', False):
        return False
    if getattr(card, 'cannot_attack_until', False):
        return False
    if getattr(card, 'cannot_be_rested_until', False):
        return False
    if (getattr(card, 'just_played', False)
            and not (card.is_rush()
                     or card.is_rush_character()
                     or getattr(card, 'rush_character_only_this_turn', False))):
        return False
    if is_attack_locked_self(card, owner, opp):
        return False
    if not can_afford_attack_paywall(card, owner):
        return False
    return True


def _step_matching_targets(step: dict, chars: list) -> int:
    """Quantos personagens de `chars` passam nos FILTROS do step
    (cost_lte/gte/eq, power_lte/gte, rested_only, filter_type)."""
    n = 0
    for c in chars:
        if step.get('cost_lte') is not None and c.cost > step['cost_lte']:
            continue
        if step.get('cost_gte') is not None and c.cost < step['cost_gte']:
            continue
        if step.get('cost_eq') is not None and c.cost != step['cost_eq']:
            continue
        if step.get('power_lte') is not None and c.power > step['power_lte']:
            continue
        if step.get('power_gte') is not None and c.power < step['power_gte']:
            continue
        if step.get('rested_only') and not getattr(c, 'rested', False):
            continue
        filters = step.get('filter_types') or []
        ft = (step.get('filter_type') or '').lower()
        if ft:
            filters = [ft]
        if filters and not any(str(f).lower() in c.sub_types.lower() for f in filters):
            continue
        n += 1
    return n


def _on_ko_play_card_value(step: dict, owner: 'Optional[GameState]') -> float:
    """
    Valor do step play_card/play_from_trash de um on-KO: só conta se
    existir alvo de verdade na mão/trash do DONO da carta, e escala pelo
    valor situacional da melhor carta elegível — não um bônus fixo.

    Achado 07/07: partida real teve o Avalo Pizarro (on-KO: draw + play até
    1 Fullalead da mão/trash) escolhido como sacrifício do redirect do Teach
    em vez do Vasco Shot (on-KO: draw + restar personagem <= custo 6 do
    oponente, com o Kuma do oponente em campo como alvo real). O Fullalead
    já tinha sido jogado antes (nenhum alvo disponível), mas o bônus fixo de
    30 não sabia disso — Pizarro (15+30=45 fantasma) venceu o Vasco Shot
    (25+15=40 real) por pontos que não existiam.
    """
    if owner is None:
        return 30.0   # sem GameState do dono para checar — mantém o antigo
    from optcg_engine.rules_facade import eligible_cards
    cost_lte = step.get('cost_lte')
    if cost_lte == 99:   # "até custo X" usado como "sem limite" no parser
        cost_lte = None
    fontes = [owner.hand]
    if step.get('source_alt') == 'trash':
        fontes.append(owner.trash)
    elegiveis = []
    for fonte in fontes:
        elegiveis.extend(eligible_cards(
            fonte, cost_lte=cost_lte, name_or_code=step.get('filter_name', ''),
            filter_text=step.get('filter_type', ''), color=step.get('color', ''),
            exclude_name=step.get('exclude', ''),
        ))
    if not elegiveis:
        return 0.0   # sem alvo — jogar no vácuo não vale nada
    melhor = max(elegiveis, key=lambda c: c.board_value())
    return min(30.0, 12.0 + melhor.board_value() * 2.0)


def on_ko_value(code: str, opp: 'Optional[GameState]' = None,
                owner: 'Optional[GameState]' = None) -> float:
    """
    Valor dos efeitos [On K.O.] de uma carta — o que GANHAMOS se ela morrer.
    Usado para escolher sacrifícios (ex: redirect do Teach). Escala
    compatível com char_value_score.

    Os FILTROS dos steps são aplicados contra o campo REAL do oponente
    (partida 04/07: Doc Q "KO até 2 de custo <= 1" foi escolhido com o
    oponente sem nenhum custo <= 1 — morreu por um draw seco; o Vasco Shot,
    cujo rest custo <= 6 tinha alvo, era o sacrifício certo).

    `owner` (opcional): GameState de quem é dono da carta — usado só para
    validar play_card/play_from_trash contra a mão/trash reais dele (ver
    `_on_ko_play_card_value`). Sem `owner`, mantém o bônus fixo antigo.
    """
    steps = get_card_effects(code).get('on_ko', {}).get('steps', [])
    total = 0.0
    for step in steps:
        action = step.get('action', '')
        count = int(step.get('count', 1) or 1)
        if action in ('ko', 'trash'):
            if opp is None:
                total += 30 * count
            else:
                total += 30 * min(count, _step_matching_targets(step, opp.field_chars))
        elif action in ('draw', 'draw_cards'):
            total += 15 * count
        elif action in ('rest_opp', 'rest_opp_character'):
            # restar personagem do oponente nega um ataque/bloqueio — tempo
            # real (partida 04/07: Vasco Shot era o sacrificio certo)
            if opp is None:
                total += 25 * count
            else:
                total += 25 * min(count, _step_matching_targets(step, opp.field_chars))
        elif action in ('play_card', 'play_from_trash'):
            total += _on_ko_play_card_value(step, owner)
        elif action == 'debuff_power':
            # enfraquece o oponente -- so vale se sobrar alvo que AINDA vai
            # agir este turno (duration tipicamente 'this_turn'). Achado
            # 07/07: caia no fallback generico (+8) e perdia pro play_card
            # do Pizarro mesmo sem alvo real, e depois de corrigido ainda
            # empatava (23 vs 23) com set_base_power do Sanjuan Wolf, um
            # efeito bem mais forte -- os dois ficavam invisiveis aqui.
            amount = step.get('amount', 0) or 0
            peso = 12 + min(amount / 1000 * 4, 20)
            if opp is None:
                total += peso
            else:
                tem_char_ativo = any(not getattr(c, 'rested', False) for c in opp.field_chars)
                tem_lider_ativo = opp.leader is not None and not getattr(opp.leader, 'rested', False)
                if tem_char_ativo or tem_lider_ativo:
                    total += peso
        elif action in ('set_base_power', 'buff_power') and 'opp' not in (step.get('target') or ''):
            # buff/fixa poder do NOSSO lado -- swing ofensivo real (ex:
            # Sanjuan Wolf: ate 1 dos nossos vira 7000 de poder este turno)
            amount = step.get('amount', 0) or 0
            total += 15 + min(amount / 1000 * 3, 25)
        elif action in ('life_to_hand', 'send_life_to_hand'):
            total += 10
        else:
            total += 8
    return total


def redirect_option_value(card: 'Card', atk_power: int,
                          opp: 'GameState', engine) -> float:
    """
    Valor LIQUIDO de redirecionar um ataque inimigo para `card` (personagem
    nosso), avaliado caso a caso no campo atual (regra do usuario):
    - sobrevive (poder > atacante): 0 — nada perdido, golpe anulado;
    - morre: on_ko_value - valor da carta. Um Doc Q (on-KO 75, valor ~20)
      da +55: MELHOR que um sobrevivente, porque QUEREMOS o efeito dele.
    """
    if card.power > atk_power:
        return 0.0
    return on_ko_value(card.code, opp, owner=engine.me) - engine.analyzer.char_value_score(card)


def life_redirect_cost(life_count: int) -> float:
    """
    Custo de deixar o golpe (ou mandar o golpe) na VIDA do lider, na mesma
    escala de char_value_score/on_ko_value. Vida alta = barato; cada vida a
    menos pesa mais.
    """
    if life_count >= 4:
        return 15.0
    return {3: 25.0, 2: 45.0, 1: 90.0}.get(life_count, 90.0)


def live_attack_power(attacker: 'Card') -> int:
    """Poder vivo de ataque vindo do jogo, sem projetar When Attacking."""
    atk_override = getattr(attacker, '_attack_power_override', None)
    if atk_override is None:
        return attacker.effective_power(True)
    # powerAtk vem do CardPower(..., attacking=true) do jogo sem DON.
    # Reaplica somente os buffs/custos simulados pelo engine e o DON
    # anexado, mantendo o jogo como fonte da passiva "ao atacar".
    #
    # SEM PISO em 0 aqui: o proprio CardPower do jogo nao pisa (achado
    # confirmado 06/07 -- Doc Q base 0, -2000 do Activate do lider Krieg,
    # fica -2000 vivo de verdade). Pisar ANTES de somar o DON ainda-nao-
    # anexado (em score_attack_target/don_needed_for_attack, que somam
    # don_disp*1000 por cima deste retorno) subestimava o deficit: achava
    # que 9 DON bastavam pra Doc Q -2000 vs Krieg 9000 (0+9000=9000), mas
    # o real e -2000+11000=9000 -- precisa de 11. Log da partida confirma:
    # com 9 DON anexados o combate saiu 7000 (-2000+9000), nunca 9000.
    base = int(atk_override)
    return base + attacker.power_buff + getattr(attacker, 'don_attached', 0) * 1000


def attack_time_power(attacker: 'Card', opp: 'GameState') -> int:
    """
    Poder do atacante NO MOMENTO do ataque: effective_power + buffs próprios
    de [When Attacking] (buff_power em si mesmo, ou set_base_power copiando
    um personagem do oponente — ex: Catarina Devon OP16-104, cuja base vira
    o poder do personagem escolhido). Sem isso o engine subestima esses
    atacantes e barra/superpaga ataques que na prática passam fácil.
    """
    power = live_attack_power(attacker)
    wa = get_card_effects(attacker.code).get('when_attacking')
    if not isinstance(wa, dict):
        return power
    req = wa.get('don_requirement', 0)
    if req and getattr(attacker, 'don_attached', 0) < req:
        return power
    for step in wa.get('steps', []):
        action = step.get('action', '')
        target = step.get('target', 'self')
        if target not in ('self', ''):
            continue
        if action == 'buff_power':
            power += int(step.get('amount', 0) or 0)
        elif action == 'set_base_power' and step.get('source') == 'selected_opp_character':
            if opp.field_chars:
                best = max(c.power for c in opp.field_chars)
                # Modificadores VIVOS do atacante (ex: -2000 do lider Krieg)
                # persistem depois da copia: base nova + mod, nao base crua.
                # _db_base_power e setado pelo server quando o poder vivo
                # difere do banco (partida 06/07: Devon copiou 7000 mas
                # bateu 6000 por causa do -1000 residual e o engine aprovou
                # ataque perdido).
                mod = attacker.power - getattr(attacker, '_db_base_power',
                                               attacker.power)
                ganho = (best + mod) - attacker.power
                if ganho > 0:
                    power += ganho
    return power


def don_needed_for_attack(attacker: 'Card', ttype: str, tgt: 'Optional[Card]',
                          p: 'GameState', opp: 'GameState', engine,
                          don_livre: 'Optional[int]' = None) -> int:
    """
    Quantos DON anexar ao atacante para este ataque (0 = nenhum). Função pura
    — quem anexa de fato é o chamador (_attach_don_for_attack na simulação;
    o plugin do bot via /decide). Duas parcelas distintas:

    1. DÉFICIT BASE (alvo - poder): obrigatório. Sem ele o ataque é
       matematicamente perdido — nunca declarar sem cobrir.
    2. MARGEM DE COUNTER (counter provável do oponente): LUXO. Atacar "seco"
       no empate (5000 vs 5000) é jogada legítima de pressão — força o
       oponente a escolher entre gastar counter/blocker ou perder a carta /
       tomar o dano (regra do usuário, 04/07/2026). A margem só é paga com
       `don_livre`: DON que o plano do turno deixaria OCIOSO depois das
       jogadas pretendidas e da reserva de defesa. don_livre=None mantém o
       comportamento antigo (margem limitada só pelo DON disponível).
    """
    if p.don_available <= 0:
        return 0
    if ttype == 'leader':
        alvo_power = opp.leader.power
    else:
        alvo_power = tgt.power if tgt else 0
    atk = attack_time_power(attacker, opp)

    falta_base = alvo_power - atk
    need_base = (falta_base + 999) // 1000 if falta_base > 0 else 0
    if need_base >= p.don_available:
        return min(p.don_available, need_base)

    # Counter REAL da mao do oponente (stat impresso + efeitos [Counter],
    # ex: Ground Death/Never Existed — achado 07/07: um flat "1000 if
    # opp.hand" nunca previa os +4000 desses efeitos). Achado 10/07,
    # simulacao Teach vs Imu (100 partidas, winrate 6.7%): um teto fixo de
    # 2000 aqui fazia o bot atacar sistematicamente "seco demais" contra
    # counters reais de 3000-4000 (Imu tem varios), levando ataque atras de
    # ataque bloqueado com DON ocioso sobrando no campo (visto no trace:
    # "Counter! +3000/+4000 -> defesa 8000/9000", ataque falha, personagens
    # nunca atacam pq so o lider e forte o bastante pra tentar). O teto de
    # 2000 vinha de uma regra de nao "afundar DON demais" -- mas
    # `livre_para_margem` (abaixo) ja e o limitador real: so paga margem
    # com DON que sobraria ocioso mesmo assim, nunca rouba DON do plano do
    # turno. Sem o teto fixo, a margem escala com a ameaca real, nao um
    # numero arbitrario.
    counter_prov = engine.analyzer.opp_counter_potential()
    need_margem = (counter_prov + 999) // 1000

    if don_livre is None:
        don_livre = p.don_available
    # O deficit base deste ataque tambem e gasto OBRIGATORIO do plano —
    # desconta antes de liberar margem (senao a margem rouba DON do plano)
    livre_para_margem = max(0, min(don_livre - need_base,
                                   p.don_available - need_base))
    # Margem PARCIAL vale: don_livre ja exclui plano e reserva, entao esse
    # DON esta OCIOSO — anexar e pressao gratis (força o oponente a pagar
    # mais counter para negar; visto em partida real 06/07: bot passou o
    # turno com 1 DON parado e atacou 5000 seco em vez de 6000).
    return need_base + min(need_margem, livre_para_margem)


def remove_by_identity(lst: list, obj) -> bool:
    """
    Remove de `lst` EXATAMENTE o objeto `obj` (comparando por identidade,
    `is`, nunca por __eq__ de valor). Retorna True se removeu.

    Necessario porque `Card` e um @dataclass SEM eq=False -- __eq__ e
    auto-gerado por VALOR (todos os campos), de proposito: `_remap_action`
    (linha ~5064) depende disso pra mapear uma acao do estado real pro
    clone via deepcopy do Turn Planner (`p.hand.index(obj)` so funciona
    cruzando a fronteira real->clone se a comparacao for por valor, ja que
    objetos pos-deepcopy nunca sao `is` o original). MUDAR Card pra
    eq=False quebraria isso (todo `_remap_action` passaria a sempre
    falhar com ValueError, zerando a pontuacao de toda acao simulada).

    Mas isso significa que `list.remove(card)`/`card in lista` DENTRO de
    um UNICO estado (sem cruzar real/clone) sao AMBIGUOS quando 2+ copias
    fisicas da mesma carta com o MESMO estado (recem compradas, por
    exemplo) coexistem na mesma zona -- list.remove()/in casam a PRIMEIRA
    ocorrencia "igual", nao necessariamente o objeto exato passado.
    Achado 28/06/2026 via auditoria de partida real instrumentada
    (replay_optcg.py + checagem de conservacao de DON): uma carta
    ("St. Topman Warcury", 2 copias na mao com estado identico) foi jogada
    -- e devido a esse bug, a copia "errada" ficou removida da mao,
    deixando a copia REALMENTE jogada ainda la; numa iteracao posterior do
    Turn Planner ela foi selecionada e jogada DE NOVO, resultando no MESMO
    objeto Card duas vezes em field_chars (inflando board_value e DON
    summado). Usar esta funcao em qualquer remocao DENTRO do mesmo estado
    corrige isso sem tocar em `_remap_action`.
    """
    for i, x in enumerate(lst):
        if x is obj:
            del lst[i]
            return True
    return False


def contains_identity(lst: list, obj) -> bool:
    """`obj in lista`, mas por identidade (`is`) -- ver remove_by_identity."""
    return any(x is obj for x in lst)


def remove_character_from_field(owner: 'GameState', card: 'Card', destino: str = 'trash') -> None:
    """
    Remove `card` de owner.field_chars e move pro destino indicado:
    'trash' | 'hand' | 'deck_bottom' | 'deck_top' | 'life_top' | 'life_bottom'.

    Regra oficial (comprehensive rules -- "When a Character with DON!!
    card(s) Leaves the Field"): qualquer DON anexado volta para a area
    de custo do DONO da carta (NUNCA de quem causou a remocao) e fica
    RESTED. Auditoria 27/06 encontrou esse retorno faltando em 12 pontos
    diferentes do engine (combate, KO por efeito, bounce, substituicao
    de custo, troca por campo-cheio), e mais 1 ponto (gain_life
    source='own_field', Kawamatsu OP06-103) achado ao corrigir essa
    mesma carta -- usava field_chars.pop(0) direto, fora do grep original
    (procurava so '.remove(', nao '.pop('). Esta funcao e o UNICO ponto
    que deve remover um Character do campo a partir de agora; nunca fazer
    owner.field_chars.remove(card)/pop(...) direto em codigo novo.
    """
    remove_by_identity(owner.field_chars, card)
    if card.don_attached > 0:
        owner.don_rested += card.don_attached
        card.don_attached = 0
    if destino == 'trash':
        owner.trash.append(card)
    elif destino == 'hand':
        card.rested = False
        owner.hand.append(card)
    elif destino == 'deck_bottom':
        card.rested = False
        owner.deck.insert(0, card)   # fundo do deck = início da lista
    elif destino == 'deck_top':
        card.rested = False
        owner.deck.append(card)
    elif destino == 'life_bottom':
        card.rested = False
        owner.life.insert(0, card)
    elif destino == 'life_top':
        card.rested = False
        owner.life.append(card)   # fim da lista = topo da vida (mesma convencao do deck)


# ===========================================================================
# EffectExecutor — único ponto de execução de efeitos
# Baseado no DoV3ActionStep das 34k linhas
# ===========================================================================

class EffectExecutor:
    """
    Executa efeitos de cartas conforme o banco card_effects_db.json.
    Cada 'action' corresponde a um efeito do DoV3ActionStep das 34k linhas.
    """

    def __init__(self, me: GameState, opp: GameState):
        self.me = me
        self.opp = opp
        self._once_used: set = set()  # (card_code, trigger)
        self._last_selected: Optional[Card] = None  # ver execute()

    def reset_once_per_turn(self):
        self._once_used.clear()

    def _step_is_viable(self, step: dict, card: Card) -> bool:
        """
        Diz se um step PRODUZIRÁ efeito real no estado atual. Usado para não
        pagar custo de um efeito que não vai fazer nada (decisão 25/06: ampla
        — minimiza jogadas-erro). Default seguro: action desconhecida = viável
        (não aborta por engano). Só retorna False quando há CERTEZA de que o
        step é inócuo agora (falta material: alvo, carta na zona, deck vazio).
        """
        a = step.get('action', '')
        me, opp = self.me, self.opp

        # Condicao com escopo do proprio step deve participar da viabilidade
        # ANTES do pagamento. Sem isto, o executor pagaria custos para um
        # beneficio que _execute_step descartaria logo depois.
        if step.get('conditions') and not self._check_conditions(step['conditions'], card):
            return False

        # Efeito cuja fonte e "escolha 1 personagem do oponente" (ex: Catarina
        # Devon [When Attacking] "select up to 1 opponent Character, copia o
        # poder dele") -- sem NENHUM personagem no campo do oponente, o step
        # nao produz nada (fica no poder base). Achado real 10/07: sem essa
        # checagem, _rest_activates_effect() achava que atacar SEMPRE valia
        # a pena (so por ter [When Attacking]), mesmo com campo do oponente
        # vazio -- o bot atacava com 3000 de poder puro contra um lider de
        # 5000, sem chance de passar e sem nenhum beneficio.
        if step.get('source') == 'selected_opp_character':
            return bool(opp.field_chars)

        # ── Efeitos que precisam de ALVO no oponente ──────────────────────────
        if a in ('ko', 'rest_opp_character', 'debuff_power', 'debuff_cost',
                 'bounce', 'lock_opp_character_refresh', 'lock_opp_character_attack',
                 'opp_trash_from_hand', 'place_opp_character_bottom_deck'):
            if a == 'opp_trash_from_hand':
                return len(opp.hand) > 0
            # Alvo e o STAGE do oponente, nao personagem (ex: Never Existed
            # OP13-098, "KO up to 1 opponent's Stage cost<=7") -- achado real
            # 11/07 (log 00.49.30): a checagem generica abaixo olhava
            # field_chars e dava viavel com o oponente SEM stage nenhum; o
            # evento foi jogado no vacuo (1 DON + a carta, efeito nulo).
            if step.get('target') == 'opp_stage':
                stage = getattr(opp, 'field_stage', None)
                if stage is None:
                    return False
                cost_lte = self._resolve_cost_lte(step, default=None)
                return cost_lte is None or stage.cost <= cost_lte
            from optcg_engine.rules_facade import eligible_cards
            cost_lte = self._resolve_cost_lte(step, default=None)

        if a == 'play_from_life_top':
            if not me.life:
                return False
            top = me.life[-1]
            if step.get('filter_name') and step['filter_name'].lower() not in top.name.lower():
                return False
            if step.get('filter_type') and _norm_type_text(step['filter_type']) not in _norm_type_text(top.sub_types):
                return False
            if step.get('cost_eq') is not None and top.cost != step['cost_eq']:
                return False
            if step.get('cost_lte') is not None and top.cost > step['cost_lte']:
                return False
            return top.card_type == 'CHARACTER'
            candidates = eligible_cards(
                opp.field_chars,
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                don_attached_gte=step.get('don_attached_gte'),
                rested_only=step.get('rested_only', False),
                active_only=(a == 'rest_opp_character'),
                filter_text=step.get('filter_type', ''),
                exclude_name=step.get('exclude', ''),
            )
            return bool(candidates)
        # negate_effect: alvo pode ser opp_leader (sempre existe -- viavel),
        # opp_leader_or_character (idem, lider sempre cobre) ou opp_character
        # (precisa de personagem elegivel, mesmo filtro dos outros acima).
        if a == 'negate_effect':
            target = step.get('target', 'opp_character')
            if target in ('opp_leader', 'opp_leader_or_character'):
                return True
            from optcg_engine.rules_facade import eligible_cards
            cost_lte = self._resolve_cost_lte(step, default=None)
            return bool(eligible_cards(opp.field_chars, cost_lte=cost_lte))
        if a == 'opp_choose_trash_our_hand':
            return len(me.hand) > 0
        if a == 'opp_bounce_own_character':
            cost_lte = step.get('cost_lte')
            return any(cost_lte is None or c.cost <= cost_lte for c in opp.field_chars)

        # ── Jogar carta da mão com filtro ─────────────────────────────────────
        if a == 'play_card':
            if step.get('source') == 'self':
                return contains_identity(me.hand, card)  # GRUPO 1 (trigger): a própria carta
            from optcg_engine.rules_facade import eligible_cards

            cost_lte = step.get('cost_lte')
            if cost_lte == 'don_count_self':
                cost_lte = me.don_available + me.don_rested
            # "Play 1 [tipo] ..." sem card_type explicito = CHARACTER — mesma
            # regra do _elegivel_para_play (sim_bridge). Achado real 12/07
            # (partida 23.03.36, 3a vez reportado pelo usuario): o EVENTO
            # "The Five Elders Are at Your Service!!!" (custo 1, 'five
            # elders' no NOME) passava neste filtro e o gate do Empty Throne
            # dizia "elegivel" — o jogo so aceita personagem, a ativacao
            # fizzlava (3 DON + stage restados por nada).
            req_type = (step.get('card_type') or 'CHARACTER').upper()
            return bool(eligible_cards(
                [c for c in me.hand if c.card_type == req_type],
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                filter_text=step.get('filter_type', ''),
                name_or_code=step.get('filter_name', ''),
                color=step.get('color', ''),
                exclude_name=step.get('exclude', ''),
            ))

        # ── Recuperar/jogar de zona que pode estar vazia ──────────────────────
        if a in ('play_from_trash', 'add_from_trash'):
            return len(me.trash) > 0
        if a in ('play_from_deck', 'trash_from_deck_top', 'deck_reorder_rest',
                 'deck_top_rest', 'deck_bottom_rest', 'look_top_deck', 'draw'):
            return len(me.deck) > 0
        if a in ('trash_from_hand', 'life_to_hand', 'hand_to_deck'):
            return len(me.hand) > 0 if a in ('trash_from_hand', 'hand_to_deck') else len(me.life) > 0
        if a == 'trash_own_life':
            return any(c.life_face_up for c in me.life) if step.get('face') == 'up' else len(me.life) > 0
        if a == 'attack_life':
            return len(opp.life) > 0
        if a == 'set_don_active':
            return me.don_rested > 0
        if a in ('peek_life', 'turn_life_face_up', 'turn_life_face_down'):
            owner = opp if step.get('target') == 'opponent' else me
            return len(owner.life) > 0
        if a == 'return_don_until_match_opp':
            return me.don_on_field() > opp.don_on_field()

        # Default: sem material a checar (buff próprio, keyword, add_don,
        # gain_life do deck, etc) = sempre viável.
        return True

    def _resolve_choice(self, options: list, card: Card, chooser: str = 'self') -> list:
        """Escolhe a opcao viavel de maior valor heuristico."""
        if not options:
            return []

        weights = {
            'attack_life': 4,
            'place_opp_character_bottom_deck': 3,
            # Mesmo peso de place_opp_character_bottom_deck -- remocao
            # forte equivalente (achado 16/07, OP05-096: essa acao nunca
            # tinha peso proprio aqui, caia no default=1 igual bounce,
            # subvalorizada na escolha entre as 3 opcoes do "Choose one").
            'place_opp_char_to_opp_life': 3,
            'ko': 2,
            'trash_character': 2,
            'bounce': 1,
            'draw': 1,
            'trash_opp_life': 3,
            'gain_life': 2,
        }

        def choice_step_viable(step: dict) -> bool:
            action = step.get('action', '')
            if action == 'draw':
                return True
            if action == 'gain_life':
                source = step.get('source', 'deck_top')
                if source == 'deck_top':
                    return bool(self.me.deck)
                if source == 'hand':
                    return bool(self.me.hand)
                if source == 'trash':
                    return bool(self.me.trash)
                if source == 'opp_life':
                    return bool(self.opp.life)
            return self._step_is_viable(step, card)

        best_steps = []
        best_score = None
        for option in options:
            steps = option if isinstance(option, list) else [option]
            viable = [s for s in steps if choice_step_viable(s)]
            if not viable:
                continue
            score = sum(weights.get(s.get('action', ''), 1) for s in viable)
            if best_score is None or (score > best_score if chooser != 'opponent' else score < best_score):
                best_score = score
                best_steps = steps

        return best_steps

    def execute(self, card: Card, trigger: str, verbose: bool = False, is_opp_turn: bool = False) -> list:
        """
        Executa todos os efeitos de um trigger para uma carta.
        Retorna lista de logs para o replay.

        is_opp_turn: relevante SO para trigger='on_ko' com a condicao
        'opp_turn_only' (gerada para blocos "[Opponent's Turn][On K.O.]",
        7 cards -- ex: EB03-055 Nico Robin). Era gerada pelo parser e NUNCA
        checada (achado em auditoria 27/06) -- o efeito disparava
        incondicionalmente, inclusive no turno do PROPRIO dono. Quem chama
        execute() deve passar True/False conforme o contexto real (ex:
        K.O. por combate = turno de quem ataca = opp_turn_only vale pro
        dono do alvo; K.O. como custo pago pelo proprio jogador = seu
        proprio turno = opp_turn_only NAO vale). Default False (conservador
        -- nao dispara de graca em contexto indeterminado, mesmo principio
        do don_requirement abaixo).
        """
        effects = get_card_effects(card.code)
        if trigger not in effects:
            return []

        # Efeito negado (negate_effect, ex: OP09-093): a carta nao produz
        # NENHUM efeito enquanto a negacao estiver ativa. So bloqueia
        # gatilhos FUTUROS -- nao desfaz um on_play que ja resolveu antes
        # da negacao ser aplicada (execute() e sempre disparo pontual no
        # momento do gatilho, nunca reexecucao de algo passado).
        if getattr(card, 'effects_negated_until', ''):
            return []

        ef_data = effects[trigger]

        # Once per turn
        key = (card.code, trigger)
        if ef_data.get('once_per_turn') and key in self._once_used:
            return []

        # [Opponent's Turn][On K.O.]: so dispara se o K.O. aconteceu de fato
        # no turno do oponente do dono da carta.
        if trigger == 'on_ko' and ef_data.get('conditions', {}).get('opp_turn_only') and not is_opp_turn:
            return []

        # Verifica condições
        if not self._check_conditions(ef_data.get('conditions', {}), card):
            return []

        # [DON!! ×N]: o efeito só ativa se a carta tem N DON anexados.
        # Sem isso, a IA executaria o efeito de graça (vantagem ilegal).
        don_req = ef_data.get('don_requirement', 0)
        if don_req and getattr(card, 'don_attached', 0) < don_req:
            return []

        # VIABILIDADE (conserto estrutural, decisão 25/06): não pagar custo se
        # NENHUM step do efeito vai produzir resultado real no estado atual
        # (ex: "play up to 1" sem carta elegível, "KO 1" sem alvo, mill com deck
        # vazio). Minimiza jogadas-erro nas estatísticas. Só aborta se TODOS os
        # steps forem inviáveis; um único step viável já ativa o efeito.
        steps_all = ef_data.get('steps', [])
        if not steps_all and ef_data.get('choice'):
            steps_all = self._resolve_choice(ef_data.get('choice', []), card, ef_data.get('choice_chooser', 'self'))
        if steps_all and not any(self._step_is_viable(s, card) for s in steps_all):
            return []

        # Custo opcional ("you may pagar X: Y") vale a pena? So aplica em
        # on_play/main -- gatilhos que resolvem automaticamente ao jogar a
        # carta, sem uma etapa de scoring PRÉVIA que já tenha decidido se
        # vale ativar (diferente de activate_main, já filtrado por
        # _score_activate_main antes de chegar aqui). Mesma pergunta feita
        # ao vivo via resolve_optional_effect em sim_bridge.py.
        if trigger in ('on_play', 'main') and not self._worth_paying_optional_costs(
                ef_data.get('costs', []), card):
            return []

        # Paga custos. _last_trashed_names zerado ANTES (nao depois, ao
        # contrario de _last_selected) porque e preenchido DENTRO de
        # _pay_costs (custo trash_from_hand) e precisa sobreviver ate os
        # steps rodarem logo abaixo -- ver "same_name_as_trashed" em
        # play_from_trash (achado 16/07, EB02-039).
        self._last_trashed_names = []
        if not self._pay_costs(ef_data.get('costs', []), card):
            return []

        # Executa steps. Os logs do CUSTO (pago acima) vêm primeiro, para o
        # replay mostrar o que foi pago antes do benefício.
        logs = list(getattr(self, '_cost_logs', []))
        # Memoria de alvo entre steps (SaveTargetName, achado 28/06/2026):
        # zerada a cada execute(), preenchida por um step de selecao
        # (buff_power target='select_filtered') e consumida por um step
        # POSTERIOR no MESMO bloco (target='selected') -- nunca atravessa
        # triggers/blocos diferentes.
        self._last_selected = None
        for step in steps_all:
            log = self._execute_step(step, card)
            if log:
                logs.append(log)

        if ef_data.get('once_per_turn'):
            self._once_used.add(key)

        return logs

    def try_substitute(self, card: Card, removal_kind: str, verbose: bool = False) -> str | None:
        """
        Verifica se `card` (do lado self.me) tem substitute_ko (removal_kind
        == 'ko') ou substitute_removal (removal_kind in ('ko','bounce',
        'deck_bottom') -- substitute_removal cobre QUALQUER remocao, nao so
        K.O.) ativo, e se sim tenta pagar o custo da substituicao.
        Retorna uma string de log se substituiu (e quem chamou NAO deve
        prosseguir com a remocao real), ou None se nao ha substituto
        aplicavel/pagavel (remocao segue normalmente).
        """
        effects = get_card_effects(card.code)
        # Achado 01/07/2026: so checava 'passive', mas cartas com a tag
        # formal "[Opponent's Turn]"/"[Your Turn]" ANTES da clausula de
        # substituicao (ex: OP14-029, OP14-092) viram esse timing virar a
        # chave de topo no parser, nao 'passive' (mesmo padrao que
        # is_immune() ja trata corretamente ao iterar varios timings).
        for timing in ('passive', 'opp_turn', 'your_turn'):
            block = effects.get(timing, {})
            if not block:
                continue

            for step in block.get('steps', []):
                action = step.get('action')
                aplica = ((action == 'substitute_ko' and removal_kind == 'ko') or (action == 'substitute_removal' and removal_kind != 'rest') or (action == 'substitute_rest' and removal_kind == 'rest'))
                if not aplica:
                    continue

                # Once per turn (mesma chave de controle que efeitos normais)
                key = (card.code, f'{timing}_substitute')
                if block.get('once_per_turn') and key in self._once_used:
                    continue

                # Filtro de alvo: self_type (sub_types) ou self_name (nome
                # proprio) -- quando presentes, restringem quais cards desse
                # arquetipo podem usar o substituto.
                conds = dict(block.get('conditions', {}))
                if not self._check_conditions(conds, card):
                    continue
                filter_type = step.get('filter_type', '')
                if filter_type and filter_type.lower() not in card.sub_types.lower():
                    continue
                filter_name = step.get('filter_name', '')
                if filter_name and filter_name.lower() not in card.name.lower():
                    continue

                cost = step.get('cost', {})
                log = self._pay_substitute_cost(cost, card)
                if log is None:
                    continue  # não conseguiu pagar -- tenta o próximo step (raro) ou desiste

                extra_logs = []
                for extra in step.get('extra_steps', []):
                    extra_log = self._execute_step(extra, card)
                    if extra_log:
                        extra_logs.append(extra_log)

                if block.get('once_per_turn'):
                    self._once_used.add(key)
                if extra_logs:
                    return log + ' | ' + ' | '.join(extra_logs)
                return log

        return None

    def _substitute_source_blocks(self, source: Card, source_is_opp: bool):
        effects = get_card_effects(source.code)
        # 'your_turn' adicionado em 01/07/2026 -- mesmo achado de
        # try_substitute(): cartas com a tag formal "[Your Turn]" antes da
        # clausula de substituicao (ex: OP14-034) usam essa chave de topo,
        # nao 'passive'. Sem gating extra por source_is_opp aqui (mesma
        # simplificacao ja usada no resto do engine pra essas tags de turno
        # -- is_immune()/_current_turn_owner() tambem trata como "sempre
        # vale" por falta de rastreamento fino de turno).
        for trigger in ('passive', 'opp_turn', 'your_turn'):
            if trigger == 'opp_turn' and not source_is_opp:
                continue
            block = effects.get(trigger, {})
            if block:
                yield trigger, block

    def _source_conditions_met_for_substitute(self, source: Card, block: dict) -> bool:
        conds = dict(block.get('conditions', {}))
        for key in ('self_type', 'self_power_base_lte', 'self_power_base_gte'):
            conds.pop(key, None)
        return self._check_conditions(conds, source)

    def _target_matches_external_substitute(self, target: Card, source: Card,
                                            step: dict, block: dict) -> bool:
        from optcg_engine.rules_facade import card_matches_filter

        if step.get('filter_type') and not card_matches_filter(target, step.get('filter_type')):
            return False
        if step.get('filter_name'):
            needle = step.get('filter_name', '').lower()
            if needle not in target.name.lower() and needle not in target.code.lower():
                return False
        if step.get('filter_color') and step.get('filter_color', '').lower() not in target.color.lower():
            return False
        if step.get('filter_attribute') and step.get('filter_attribute', '').lower() not in (target.attribute or '').lower():
            return False
        if step.get('cost_lte') is not None and target.cost > step['cost_lte']:
            return False
        if step.get('cost_gte') is not None and target.cost < step['cost_gte']:
            return False
        if step.get('power_lte') is not None and target.power > step['power_lte']:
            return False
        if step.get('power_eq') is not None and target.power != step['power_eq']:
            return False
        if step.get('power_gte') is not None and target.power < step['power_gte']:
            return False
        if step.get('rested_only') and not target.rested:
            return False
        if step.get('exclude_self') and target is source:
            return False
        if step.get('exclude'):
            exclude = step.get('exclude', '').lower()
            if exclude in target.name.lower() or exclude in target.code.lower():
                return False

        conds = block.get('conditions', {})
        if conds.get('self_type') and conds['self_type'] not in target.sub_types.lower():
            return False
        if conds.get('self_power_base_lte') is not None and target.power > conds['self_power_base_lte']:
            return False
        if conds.get('self_power_base_gte') is not None and target.power < conds['self_power_base_gte']:
            return False

        target_keys = (
            'filter_type', 'filter_name', 'filter_color', 'filter_attribute', 'cost_lte', 'cost_gte',
            'power_lte', 'power_eq', 'power_gte', 'rested_only', 'exclude', 'exclude_self',
        )
        target_cond_keys = ('self_type', 'self_power_base_lte', 'self_power_base_gte')
        # 'no_filter': marcado explicitamente pelo parser quando o texto real
        # nao tem restricao nenhuma de alvo (ex: OP16-014 "if one of your
        # Characters would be removed..."). Distinto de "nenhuma chave
        # presente" generico (que continua tratado como "protecao desligada"
        # por seguranca, default pra falha de extracao de filtro).
        if step.get('no_filter'):
            return True
        return any(k in step for k in target_keys) or any(k in conds for k in target_cond_keys)

    def _try_external_substitute_from_source(self, source: Card, target: Card,
                                             removal_kind: str,
                                             source_is_opp: bool) -> str | None:
        for trigger, block in self._substitute_source_blocks(source, source_is_opp):
            if not self._source_conditions_met_for_substitute(source, block):
                continue
            don_req = block.get('don_requirement', 0)
            if don_req and getattr(source, 'don_attached', 0) < don_req:
                continue
            for step in block.get('steps', []):
                action = step.get('action')
                aplica = ((action == 'substitute_ko' and removal_kind == 'ko') or (action == 'substitute_removal' and removal_kind != 'rest') or (action == 'substitute_rest' and removal_kind == 'rest'))
                if not aplica:
                    continue
                key = (source.code, f'{trigger}_substitute')
                if block.get('once_per_turn') and key in self._once_used:
                    continue
                if not self._target_matches_external_substitute(target, source, step, block):
                    continue
                cost = step.get('cost', {})
                cost_card = target if cost.get('action') == 'debuff_power_self' else source
                log = self._pay_substitute_cost(cost, cost_card)
                if log is None:
                    continue
                extra_logs = []
                for extra in step.get('extra_steps', []):
                    extra_log = self._execute_step(extra, source)
                    if extra_log:
                        extra_logs.append(extra_log)
                if block.get('once_per_turn'):
                    self._once_used.add(key)
                if extra_logs:
                    return log + ' | ' + ' | '.join(extra_logs)
                return log
        return None

    def try_any_substitute(self, target: Card, removal_kind: str,
                           source_is_opp: bool = True) -> str | None:
        log = self.try_substitute(target, removal_kind)
        if log:
            return log

        sources = [c for c in self.me.field_chars if c is not target]
        sources.append(self.me.leader)
        if self.me.field_stage:
            sources.append(self.me.field_stage)
        for source in sources:
            log = self._try_external_substitute_from_source(
                source, target, removal_kind, source_is_opp)
            if log:
                return log
        return None

    def try_counter_event_substitute(self, target: Card, removal_kind: str) -> str | None:
        """Ativa evento [Counter] da mao que substitui K.O./remocao em batalha."""
        for event in list(self.me.hand):
            if event.card_type != 'EVENT':
                continue
            block = get_card_effects(event.code).get('counter', {})
            if not block:
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue

            for step in block.get('steps', []):
                action = step.get('action')
                aplica = ((action == 'substitute_ko' and removal_kind == 'ko') or (action == 'substitute_removal' and removal_kind != 'rest') or (action == 'substitute_rest' and removal_kind == 'rest'))
                if not aplica:
                    continue
                target_keys = (
                    'filter_type', 'filter_name', 'filter_color', 'cost_lte', 'cost_gte',
                    'power_lte', 'power_eq', 'power_gte', 'rested_only', 'exclude',
                )
                if any(k in step for k in target_keys) and not self._target_matches_external_substitute(target, event, step, block):
                    continue

                cost = step.get('cost', {})
                if cost.get('action') != 'trash_from_hand':
                    continue
                count = cost.get('count', 1)
                if len([c for c in self.me.hand if c is not event]) < count:
                    continue

                remove_by_identity(self.me.hand, event)
                self.me.trash.append(event)
                self.me.don_available -= play_cost
                self.me.don_rested += play_cost

                log = self._pay_substitute_cost(cost, target)
                if log is None:
                    continue
                return f'Counter {event.name[:18]}: {log}'

        return None

    def _counter_event_cost_payable(self, event: Card, costs: list) -> bool:
        extra_discards = 0
        for cost in costs:
            ctype = cost.get('type')
            if ctype == 'trash_from_hand':
                extra_discards += cost.get('count', 1)
            elif ctype == 'don_minus' and not cost.get('optional', False):
                if self.me.don_available + self.me.don_rested < cost.get('count', 1):
                    return False
            elif ctype != 'don_minus':
                return False
        return len([c for c in self.me.hand if c is not event]) >= extra_discards

    def _pay_counter_event_costs(self, event: Card, costs: list) -> list[str] | None:
        logs = []
        for cost in costs:
            ctype = cost.get('type')
            if ctype == 'trash_from_hand':
                trashed = []
                for _ in range(cost.get('count', 1)):
                    candidates = [c for c in self.me.hand if c is not event]
                    if not candidates:
                        return None
                    worst = self._choose_to_trash(candidates)
                    remove_by_identity(self.me.hand, worst)
                    self.me.trash.append(worst)
                    trashed.append(worst.name[:15])
                logs.append(f'trashou da mao: {", ".join(trashed)}')
            elif ctype == 'don_minus' and not cost.get('optional', False):
                count = cost.get('count', 1)
                if not self._return_don_to_deck(count):
                    return None
                logs.append(f'devolveu {count} DON')
        return logs

    def _parse_counter_event_text_fallback(
        self, event: Card, target: Card, target_type: str
    ) -> dict | None:
        """
        Parseia o efeito [Counter] do texto bruto da carta para o caso padrão:
        "Your Leader [or Character] gains +X power during this battle."
        Cobre ~90% dos counter events; casos condicionais ou multi-step ficam
        fora de escopo aqui (retornam None e o engine ignora o evento como
        counter, sem catastrófico -- só não usa a carta).
        """
        text = event.card_text or ''
        # Extrai o bloco após [Counter]
        m_block = re.search(r'\[counter\](.*?)(?:\[|$)', text.lower(), re.DOTALL)
        if not m_block:
            return None
        counter_text = m_block.group(1)

        # Condições globais simples — usa as mesmas chaves de _check_conditions
        conditions: dict = {}
        m_leader = re.search(r'if your leader is \[(\w+)\]', counter_text)
        if m_leader:
            conditions['leader_is'] = m_leader.group(1).lower()
        m_trash = re.search(r'if you have (\d+) or more cards? in your trash', counter_text)
        if m_trash:
            conditions['trash_gte'] = int(m_trash.group(1))

        # Detecta o buff: "+X power during this battle"
        m_buff = re.search(r'\+(\d+)\s*power\s+during\s+this\s+battle', counter_text)
        if not m_buff:
            return None
        amount = int(m_buff.group(1))

        # Detecta o target
        if 'your leader or character' in counter_text:
            target_rule = 'leader_or_character'
        elif 'your leader' in counter_text:
            target_rule = 'leader'
        elif 'your character' in counter_text:
            target_rule = 'own_character'
        else:
            target_rule = 'leader_or_character'

        # Rejeita se target não bate com quem está sendo atacado
        if target_rule == 'leader' and target_type != 'leader':
            return None
        if target_rule == 'own_character' and target_type != 'character':
            return None

        return {
            'steps': [{
                'action': 'buff_power',
                'amount': amount,
                'target': target_rule,
                'duration': 'battle_only',
            }],
            'conditions': conditions,
        }

    def _counter_event_power_plan(self, event: Card, target: Card,
                                  target_type: str) -> tuple[int, list[dict]] | None:
        block = get_card_effects(event.code).get('counter', {})
        # Fallback: parser atual não parseia blocos [Counter] de EVENT cards
        # (armazena counter: 0). Para o padrão mais comum — "gains +X power
        # during this battle" — extrai o valor direto do texto.
        if not block:
            block = self._parse_counter_event_text_fallback(event, target, target_type)
            if block is None:
                return None
        if not self._check_conditions(block.get('conditions', {}), event):
            return None
        steps = block.get('steps', [])
        # 'this_turn' conta igual a 'battle_only' aqui: o Counter Step so
        # acontece DENTRO da resolucao desta batalha, e o resto do engine ja
        # trata as duas durations de forma identica na limpeza (reset de
        # power_buff no inicio do turno) -- achado 30/06/2026, 5 cartas reais
        # no banco usam 'this_turn' num buff que so faz sentido como defesa
        # de Counter (OP04-037, OP04-076, OP06-017, OP09-039, OP13-077).
        buff_steps = [
            step for step in steps
            if step.get('action') == 'buff_power' and step.get('duration') in ('battle_only', 'this_turn')
        ]
        if not buff_steps:
            return None
        buff_step_ids = {id(s) for s in buff_steps}
        extras = [step for step in steps if id(step) not in buff_step_ids]
        safe_extra_actions = {
            'draw', 'set_active', 'rest_opp_character', 'add_don', 'set_don_active',
            'ko', 'bounce', 'place_opp_character_bottom_deck', 'debuff_power',
            'trash_from_deck_top', 'peek_life', 'add_from_trash', 'gain_life',
            'character_to_owner_life', 'opp_bounce_own_character',
            'play_card', 'play_from_deck', 'look_top_deck', 'add_to_hand',
            'deck_bottom_rest', 'deck_reorder_rest', 'deck_top_rest',
        }
        if any(step.get('action') not in safe_extra_actions for step in extras):
            return None
        principal, *bonus_steps = buff_steps
        target_rule = principal.get('target')
        if target_rule == 'leader' and target_type != 'leader':
            return None
        if target_rule == 'own_character' and target_type != 'character':
            return None
        if target_rule == 'select_filtered':
            # "Up to 1 of your [Tipo] type Leader or Character cards gains
            # +X power" -- so conta como defesa se o ALVO REAL sob ataque
            # (target, o leader/character defendendo) bater no filtro; senao
            # o efeito buffaria outra carta qualquer, que nao impede o hit
            # nesta batalha (achado 30/06/2026, 9 cartas no banco).
            from optcg_engine.rules_facade import card_matches_filter
            if not card_matches_filter(target, principal.get('filter_type', '')):
                return None
        elif target_rule not in ('leader', 'own_character', 'leader_or_character'):
            return None
        if principal.get('conditions') and not self._check_conditions(principal.get('conditions', {}), event):
            return None
        amount = principal.get('amount', 0)
        # buff_power(battle_only) ADICIONAL com target='self' -- texto real
        # confirmado nos 8 casos do banco: "Up to 1 of your Leader or
        # Character cards gains +X power... Then, if [cond], THAT CARD gains
        # an additional +Y power" (ex: EB03-020, OP04-095, OP07-035). O
        # parser mapeia "that card" como target='self' (mesma carta
        # escolhida no step anterior, NAO o proprio Event) -- soma como
        # bonus condicional ao MESMO alvo, nunca um 2º alvo independente.
        for bonus in bonus_steps:
            if bonus.get('target') != 'self':
                return None
            if bonus.get('conditions') and not self._check_conditions(bonus.get('conditions', {}), event):
                continue
            amount += bonus.get('amount', 0)
        return amount, extras

    def try_counter_event_power(self, target: Card, target_type: str,
                                needed: int) -> tuple[int, str] | None:
        """Usa um evento [Counter] simples se o buff de batalha impedir o hit."""
        candidates = []
        for event in self.me.hand:
            if event.card_type != 'EVENT':
                continue
            plan = self._counter_event_power_plan(event, target, target_type)
            if plan is None:
                continue
            amount, extras = plan
            if amount < needed:
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue
            costs = get_card_effects(event.code).get('counter', {}).get('costs', [])
            if not self._counter_event_cost_payable(event, costs):
                continue
            candidates.append((amount - needed, play_cost, event, amount, costs, extras))

        if not candidates:
            return None

        _, play_cost, event, amount, costs, extras = min(candidates, key=lambda item: (item[0], item[1]))
        cost_logs = self._pay_counter_event_costs(event, costs)
        if cost_logs is None:
            return None
        remove_by_identity(self.me.hand, event)
        self.me.trash.append(event)
        self.me.don_available -= play_cost
        self.me.don_rested += play_cost
        log = f'Counter {event.name[:18]}: +{amount} power'
        extra_logs = []
        for extra in extras:
            if extra.get('conditions') and not self._check_conditions(extra.get('conditions', {}), event):
                continue
            extra_log = self._execute_step(extra, event)
            if extra_log:
                extra_logs.append(extra_log)
        if cost_logs:
            log += ' | custo: ' + '; '.join(cost_logs)
        if extra_logs:
            log += ' | ' + ' | '.join(extra_logs)
        return amount, log

    def _counter_event_debuff_plan(self, event: Card, attacker: Card,
                                   attacker_type: str) -> int | None:
        """Plano pra Counter events que enfraquecem o ATACANTE em vez de
        buffar a propria defesa -- mecanica distinta de
        _counter_event_power_plan, que so cobre 'Your Leader or Character
        gains power'. Achado 30/06/2026: 5 cartas no banco sao "[Counter]
        Give up to 1 of your opponent's Leader or Character cards -X power
        during this turn" (OP01-028, OP03-017, OP07-075, OP15-021,
        ST09-014) -- um unico debuff_power, sem extras, alvo escolhido pela
        IA = sempre o atacante (o que importa pra sobreviver A ESTE ataque).
        Escopo deliberadamente minimo: exige EXATAMENTE 1 debuff_power e
        nenhum outro step -- cartas com 2 debuffs em sequencia (OP04-017,
        OP02-089) ou combinadas com outra action (OP09-097 negate_effect)
        tem semantica ambigua sobre se afetam o MESMO alvo, fora de escopo
        por ora (ver TODO.md)."""
        block = get_card_effects(event.code).get('counter', {})
        if not block or not self._check_conditions(block.get('conditions', {}), event):
            return None
        steps = block.get('steps', [])
        if len(steps) != 1:
            return None
        step = steps[0]
        if step.get('action') != 'debuff_power':
            return None
        target_rule = step.get('target')
        if target_rule == 'opp_character' and attacker_type != 'character':
            return None
        if target_rule not in ('opp_character', 'opp_leader_or_character'):
            return None
        if step.get('conditions') and not self._check_conditions(step.get('conditions', {}), event):
            return None
        return step.get('amount', 0)

    def try_counter_event_debuff(self, attacker: Card, attacker_type: str,
                                 needed: int) -> tuple[int, str] | None:
        """Usa um evento [Counter] que enfraquece o ATACANTE (em vez de
        buffar a propria defesa) se isso sozinho impedir o hit."""
        candidates = []
        for event in self.me.hand:
            if event.card_type != 'EVENT':
                continue
            amount = self._counter_event_debuff_plan(event, attacker, attacker_type)
            if amount is None or amount < needed:
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue
            costs = get_card_effects(event.code).get('counter', {}).get('costs', [])
            if not self._counter_event_cost_payable(event, costs):
                continue
            candidates.append((amount - needed, play_cost, event, amount, costs))

        if not candidates:
            return None

        _, play_cost, event, amount, costs = min(candidates, key=lambda item: (item[0], item[1]))
        cost_logs = self._pay_counter_event_costs(event, costs)
        if cost_logs is None:
            return None
        remove_by_identity(self.me.hand, event)
        self.me.trash.append(event)
        self.me.don_available -= play_cost
        self.me.don_rested += play_cost
        attacker.power_buff -= amount
        log = f'Counter {event.name[:18]}: -{amount} power no atacante'
        if cost_logs:
            log += ' | custo: ' + '; '.join(cost_logs)
        return amount, log

    def _counter_event_ko_plan(self, event: Card, attacker: Card) -> bool:
        """Checa se um evento [Counter] da K.O. no ATACANTE especifico.
        Achado 30/06/2026: 4 cartas no banco sao "[Counter] K.O. up to 1 of
        your opponent's Characters with cost/power N or less[, rested
        only]" (EB01-010, OP08-094, OP10-040, OP13-039) -- cancelamento
        TOTAL do ataque (sem dano nenhum), distinto de buffar defesa ou
        debuffar o atacante. Escopo minimo: exige EXATAMENTE 1 step 'ko'
        com target='opp_character' (Leaders nunca aparecem como alvo nesses
        4 casos) e nenhum outro step."""
        block = get_card_effects(event.code).get('counter', {})
        if not block or not self._check_conditions(block.get('conditions', {}), event):
            return False
        steps = block.get('steps', [])
        if len(steps) != 1:
            return False
        step = steps[0]
        if step.get('action') != 'ko' or step.get('target') != 'opp_character':
            return False
        cost_lte = step.get('cost_lte')
        if cost_lte is not None and attacker.cost > cost_lte:
            return False
        power_lte = step.get('power_lte')
        if power_lte is not None and attacker.effective_power(False) > power_lte:
            return False
        if step.get('rested_only') and not attacker.rested:
            return False
        return True

    def try_counter_event_ko_attacker(self, attacker: Card) -> str | None:
        """Usa um evento [Counter] que da K.O. no atacante inteiro,
        cancelando o ataque (sem comparacao de power -- o ataque
        simplesmente nao acontece). Respeita imunidade/substituicao do
        atacante igual ao 'ko' generico (ko_context='effect': nao e KO em
        combate, e o efeito do proprio Counter event)."""
        candidates = []
        for event in self.me.hand:
            if event.card_type != 'EVENT':
                continue
            if not self._counter_event_ko_plan(event, attacker):
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue
            costs = get_card_effects(event.code).get('counter', {}).get('costs', [])
            if not self._counter_event_cost_payable(event, costs):
                continue
            candidates.append((play_cost, event, costs))

        if not candidates:
            return None

        play_cost, event, costs = min(candidates, key=lambda item: item[0])

        if is_immune(attacker, 'ko', self.opp, self.me, source_is_opp=True, ko_context='effect'):
            return None
        ee_attacker = EffectExecutor(self.opp, self.me)
        if ee_attacker.try_any_substitute(attacker, 'ko', source_is_opp=True):
            return None

        cost_logs = self._pay_counter_event_costs(event, costs)
        if cost_logs is None:
            return None
        remove_by_identity(self.me.hand, event)
        self.me.trash.append(event)
        self.me.don_available -= play_cost
        self.me.don_rested += play_cost
        remove_character_from_field(self.opp, attacker, 'trash')
        log = f'Counter {event.name[:18]}: K.O. no atacante {attacker.name[:15]}'
        if cost_logs:
            log += ' | custo: ' + '; '.join(cost_logs)
        return log

    def _pay_substitute_cost(self, cost: dict, card: Card) -> str | None:
        """Paga o custo de uma substituicao de K.O./remocao. Retorna log de
        sucesso, ou None se nao pode pagar (substituicao nao ocorre)."""
        ctype = cost.get('action')
        me = self.me

        if ctype == 'trash_self':
            if not contains_identity(me.field_chars, card):
                return None
            remove_character_from_field(me, card, 'trash')
            return f'{card.name[:18]} evitou K.O./remoção trashando a si mesmo'

        if ctype == 'rest_don':
            count = cost.get('count', 1)
            if me.don_available < count:
                return None
            me.don_available -= count
            me.don_rested += count
            return f'{card.name[:18]} evitou K.O./remoção restando {count} DON'

        if ctype in ('return_own_don', 'don_minus'):
            count = cost.get('count', 1)
            if not self._return_don_to_deck(count):
                return None
            return f'{card.name[:18]} evitou K.O./remoção devolvendo {count} DON ao deck'

        if ctype == 'trash_from_hand':
            from optcg_engine.rules_facade import eligible_cards

            count = cost.get('count', 1)
            candidatos = eligible_cards(
                me.hand,
                filter_text=cost.get('filter_type', ''),
                power_gte=cost.get('power_gte'),
                power_lte=cost.get('power_lte'),
            )
            if len(candidatos) < count:
                return None
            trashed = []
            for _ in range(count):
                worst = min(candidatos, key=lambda c: c.board_value())
                remove_by_identity(me.hand, worst)
                me.trash.append(worst)
                remove_by_identity(candidatos, worst)
                trashed.append(worst.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção trashando da mão: {", ".join(trashed)}'

        if ctype == 'debuff_power_self':
            amount = cost.get('amount', 0)
            card.power_buff -= amount
            return f'{card.name[:18]} evitou K.O./remoção perdendo {amount} de power'

        if ctype == 'debuff_power_self_leader':
            amount = cost.get('amount', 0)
            me.leader.power_buff -= amount
            return f'{card.name[:18]} evitou K.O./remoção (Leader perdeu {amount} de power)'

        if ctype == 'rest_self':
            if card.rested:
                return None
            card.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando-se'

        if ctype == 'bounce_self':
            if not contains_identity(me.field_chars, card):
                return None
            remove_character_from_field(me, card, 'hand')
            return f'{card.name[:18]} evitou K.O./remoção voltando para a mão'

        if ctype == 'rest_self_and_trash_hand':
            trash_count = cost.get('trash_count', cost.get('count', 1))
            if card.rested or len(me.hand) < trash_count:
                return None
            trashed = []
            for _ in range(trash_count):
                worst = self._choose_to_trash(me.hand)
                if worst is None:
                    return None
                remove_by_identity(me.hand, worst)
                me.trash.append(worst)
                trashed.append(worst.name[:15])
            card.rested = True
            return (
                f'{card.name[:18]} evitou K.O./remocao restando-se '
                f'e trashando da mao: {", ".join(trashed)}'
            )

        # ── Custos novos achados na auditoria de substituicao externa de
        # 01/07/2026 (11 cartas, ver TODO.md) ──────────────────────────────

        if ctype == 'rest_leader':
            # OP04-082: "you may rest your Leader or 1 [Corrida Coliseum]
            # instead" -- simplificacao deliberada: so a opcao do Leader (a
            # alternativa de stage nomeado e rara e exige modelar "OR" entre
            # dois tipos de carta bem diferentes).
            if me.leader.rested:
                return None
            me.leader.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando o Leader'

        if ctype == 'rest_own_filtered':
            # OP10-037/OP11-110: "you may rest 1 of your [Tipo] (type)
            # Characters instead" -- rest um PROPRIO Character que bate no
            # filtro de tipo do CUSTO (distinto do filtro de ALVO -- aqui o
            # filtro e sobre quem PAGA, nao sobre quem e protegido).
            from optcg_engine.rules_facade import eligible_cards

            candidatos = eligible_cards(
                [c for c in me.field_chars if not c.rested],
                filter_text=cost.get('filter_type', ''),
            )
            if not candidatos:
                return None
            alvo = max(candidatos, key=lambda c: c.board_value())
            alvo.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando {alvo.name[:15]}'

        if ctype == 'rest_own_character':
            # OP14-034 (substituicao EXTERNA): "you may rest 1 of your
            # Characters instead" -- qualquer Character proprio, sem filtro
            # de tipo (distinto de rest_own_filtered). cost_gte/exclude
            # opcionais (achado 17/07, OP05-032 Pica: "rest up to 1 of your
            # Characters with a cost of 3 or more other than [Pica]
            # instead" -- exclusao por nome, nao necessariamente self, mas
            # aqui coincide por ser substituicao propria).
            from optcg_engine.rules_facade import eligible_cards
            candidatos = eligible_cards(
                [c for c in me.field_chars if not c.rested],
                cost_gte=cost.get('cost_gte'),
                cost_lte=cost.get('cost_lte'),
                exclude_name=cost.get('exclude', ''),
            )
            if not candidatos:
                return None
            alvo = max(candidatos, key=lambda c: c.board_value())
            alvo.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando {alvo.name[:15]}'

        if ctype == 'rest_own_other_character':
            # PRB02-006 (Zoro): "you may rest 1 of your OTHER Characters
            # instead" -- substituicao PROPRIA (a carta se protege restando
            # uma ALIADA, nao qualquer character -- precisa excluir `card`,
            # a propria carta que esta se substituindo, dos candidatos.
            # Distinto de rest_own_character (substituicao EXTERNA, onde
            # `card` ja e outra carta e a exclusao nao se aplica).
            count = cost.get('count', 1)
            candidatos = [c for c in me.field_chars if not c.rested and c is not card]
            if len(candidatos) < count:
                return None
            restados = []
            for _ in range(count):
                alvo = max(candidatos, key=lambda c: c.board_value())
                alvo.rested = True
                remove_by_identity(candidatos, alvo)
                restados.append(alvo.name[:15])
            return f'{card.name[:18]} evitou rest restando: {", ".join(restados)}'

        if ctype == 'rest_own_card':
            # OP14-029/OP15-035: "you may rest N of your cards instead" --
            # qualquer carta propria (Character OU Leader), sem filtro.
            count = cost.get('count', 1)
            candidatos = [c for c in me.field_chars if not c.rested]
            if not me.leader.rested:
                candidatos.append(me.leader)
            if len(candidatos) < count:
                return None
            restados = []
            for _ in range(count):
                alvo = max(candidatos, key=lambda c: c.board_value())
                alvo.rested = True
                remove_by_identity(candidatos, alvo)
                restados.append(alvo.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção restando: {", ".join(restados)}'

        if ctype == 'life_to_hand':
            # OP10-034/OP12-061: "you may add N cards from the top of your
            # Life cards to your hand instead" -- perde vida (carta sai da
            # zona de Life) mas ganha a carta na mao, mesma logica da action
            # generica 'life_to_hand' (achado: aqui e usada como CUSTO de
            # substituicao, nao como efeito solto).
            count = cost.get('count', 1)
            if len(me.life) < count:
                return None
            taken = []
            for _ in range(count):
                c = me.life.pop()
                c.life_face_up = False
                me.hand.append(c)
                taken.append(c.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção comprando da vida: {", ".join(taken)}'

        if ctype == 'life_to_trash':
            # ST09-010/ST20-002: "you may trash N cards from the top [or
            # bottom] of your Life cards instead" -- perde vida igual
            # life_to_hand, mas a carta vai pro trash em vez da mao.
            count = cost.get('count', 1)
            if len(me.life) < count:
                return None
            trashed = []
            for _ in range(count):
                c = me.life.pop()
                c.life_face_up = False
                me.trash.append(c)
                trashed.append(c.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção trashando da vida: {", ".join(trashed)}'

        if ctype == 'trash_to_deck_bottom':
            # OP14-092: "you may place N cards from your trash at the
            # bottom of your deck in any order instead" -- mesma semantica
            # do custo 'place_from_trash_bottom_deck' ja usado em
            # _pay_costs (ativacao normal), replicada aqui pro contexto de
            # substituicao (funcoes de custo separadas, sem reuso direto).
            count = cost.get('count', 1)
            if len(me.trash) < count:
                return None
            movidas = []
            for _ in range(count):
                pior = min(me.trash, key=lambda c: c.board_value())
                remove_by_identity(me.trash, pior)
                me.deck.insert(0, pior)
                movidas.append(pior.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção mandando pro fundo do deck: {", ".join(movidas)}'

        if ctype == 'rest_opp_character':
            # OP07-029 (Basil Hawkins): "you may rest 1 of your opponent's
            # Characters instead" -- custo INVERTIDO, nao sacrifica nada
            # proprio, resta um Character do OPONENTE. Distingue de
            # rest_own_character (mesmo nome raiz, alvo oposto). Verifica
            # imunidade a rest da carta alvo (mesmo criterio do action
            # 'rest_opp_character' usado para efeitos diretos). Heuristica:
            # escolhe o MELHOR Character do oponente pra restar (maior
            # board_value), pois e um custo que beneficia quem ativa.
            from optcg_engine.rules_facade import eligible_cards, choose_highest_board_value
            count = cost.get('count', 1)
            candidatos = [
                c for c in self.opp.field_chars
                if not c.rested
                and not c.cannot_be_rested_until
                and not is_immune(c, 'rest', self.opp, me, source_is_opp=True)
            ]
            if len(candidatos) < count:
                return None
            restados = []
            for _ in range(count):
                alvo = choose_highest_board_value(candidatos)
                alvo.rested = True
                remove_by_identity(candidatos, alvo)
                restados.append(alvo.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção restando {", ".join(restados)} do oponente'

        if ctype == 'turn_life_face_up':
            # OP12-102/OP13-109/ST29-008: "you may turn N card(s) from the
            # top of your Life cards face-up instead" -- custo de
            # substituicao nunca reconhecido antes (achado 16/07); carta do
            # topo da vida vira face-up, sem sair da zona de Life.
            count = cost.get('count', 1)
            if len(me.life) < count:
                return None
            for c in me.life[-count:]:
                c.life_face_up = True
            return f'{card.name[:18]} evitou K.O./remoção virando {count} carta(s) de vida face-up'

        return None

    def apply_your_turn_buffs(self) -> list:
        """
        Aplica buffs passivos [Your Turn] de todas as cartas em campo.
        Baseado no CardV3PassiveFieldBuffs das 34k linhas.
        Inclui stages, líderes e personagens.
        """
        logs = []
        sources = self.me.field_chars + [self.me.leader]
        if self.me.field_stage:
            sources.append(self.me.field_stage)
        # Reset buffs temporários antes de aplicar novos. cost_buff_permanent
        # ENTRA aqui tambem (achado 16/07, ST25-002 e familia): apply_your_
        # turn_buffs() roda 1x por turno do proprio jogador e RECALCULA os
        # steps de 'passive'/'your_turn' do zero -- sem resetar
        # cost_buff_permanent antes, cada chamada SOMAVA de novo o mesmo
        # +N (acumulo sem limite, turno apos turno). O campo so precisa
        # sobreviver ao reset_your_turn_buffs() de FIM de turno (distinto
        # de cost_buff comum) -- nao precisa (nem deve) sobreviver a esta
        # recalculacao do INICIO do turno, que ja e a fonte da verdade.
        for c in self.me.field_chars + [self.me.leader]:
            c.power_buff = 0
            c.cost_buff = 0
            c.cost_buff_permanent = 0

        for source in sources:
            effects = get_card_effects(source.code)
            for trigger in ('your_turn', 'passive'):
                if trigger not in effects:
                    continue
                ef_data = effects[trigger]
                if not self._check_conditions(ef_data.get('conditions', {}), source):
                    continue
                don_req = ef_data.get('don_requirement', 0)
                if don_req and getattr(source, 'don_attached', 0) < don_req:
                    continue
                # LACUNA CONHECIDA: cartas com 'Choose one: • opcao A • opcao
                # B' tem ef_data['choice'] = [[steps_opcao_A], [steps_opcao_B]]
                # em vez de ef_data['steps'] (ver gerar_effects_db.py,
                # parse_block). O .get('steps', []) abaixo retorna [] para
                # essas cartas -- nenhuma opcao e executada (neutro, nao
                # quebra), mas tambem nenhum efeito real acontece. Decidir
                # qual opcao escolher e avaliacao de jogo (Opponent Reading /
                # Play Scoring), nao um parsing determinístico -- pendente.
                #
                # LACUNA CONHECIDA #2: cartas com 'Apply each of the
                # following effects based on N' (efeitos COEXISTENTES, nao
                # exclusivos como choice) tem ef_data['conditional_stack'] =
                # [{conditions, steps}, ...] em vez de ef_data['steps'].
                # Carta unica confirmada (OP15-092) -- mesma neutralidade:
                # nao quebra, mas nenhum item do stack e avaliado/executado
                # ainda. Pendente: iterar o stack, checar conditions de cada
                # item via _check_conditions, executar os steps dos que
                # passarem (sem early-return -- sao cumulativos, nao 'escolha
                # 1 e para').
                steps_to_run = list(ef_data.get('steps', []))
                for item in ef_data.get('conditional_stack', []):
                    if self._check_conditions(item.get('conditions', {}), source):
                        steps_to_run.extend(item.get('steps', []))
                if not steps_to_run and ef_data.get('choice'):
                    steps_to_run = self._resolve_choice(ef_data.get('choice', []), source, ef_data.get('choice_chooser', 'self'))

                for step in steps_to_run:
                    log = self._execute_step(step, source)
                    if log:
                        logs.append(log)

        return logs

    def reset_your_turn_buffs(self):
        """Reseta buffs temporários ao fim do turno."""
        for card in self.me.field_chars + [self.me.leader]:
            card.power_buff = 0
            card.cost_buff = 0

    # ── Verificação de condições ─────────────────────────────────────────────

    def _check_conditions(self, conds: dict, card: Card) -> bool:
        me = self.me
        opp = self.opp

        if not conds:
            return True

        if 'life_lte' in conds and me.life_count() > conds['life_lte']:
            return False
        if 'life_gte' in conds and me.life_count() < conds['life_gte']:
            return False
        if 'opp_life_lte' in conds and opp.life_count() > conds['opp_life_lte']:
            return False
        if 'opp_life_gte' in conds and opp.life_count() < conds['opp_life_gte']:
            return False
        if 'total_life_lte' in conds and (me.life_count() + opp.life_count()) > conds['total_life_lte']:
            return False
        if conds.get('battled_opp_character_this_turn') and not getattr(
                card, 'battled_opp_character_this_turn', False):
            return False
        if 'trash_gte' in conds and len(me.trash) < conds['trash_gte']:
            return False
        # Simetrico a trash_gte -- achado 16/07 (OP04-094), usado pra
        # modelar "if you have M or more cards in your trash, [X] instead
        # of [Y]" como 2 steps mutuamente exclusivos (trash_gte no
        # upgrade, trash_lte=M-1 no base).
        if 'trash_lte' in conds and len(me.trash) > conds['trash_lte']:
            return False
        if 'don_gte' in conds and me.don_available < conds['don_gte']:
            return False
        if conds.get('has_don_attached'):
            attached = getattr(me.leader, 'don_attached', 0) + sum(
                getattr(c, 'don_attached', 0) for c in me.field_chars)
            if attached <= 0:
                return False
        # "if you have a total of N or more given DON!! cards" -- limiar
        # numerico (achado 16/07, OP12-015/OP12-024/OP13-112), distinto
        # de has_don_attached (so checa >=1). Mesma soma lider+campo.
        if 'don_attached_total_gte' in conds:
            attached_total = getattr(me.leader, 'don_attached', 0) + sum(
                getattr(c, 'don_attached', 0) for c in me.field_chars)
            if attached_total < conds['don_attached_total_gte']:
                return False
        # "if you have activated an Event with a base cost of N or more
        # during this turn" -- rastreamento de EVENTO ativado NESTE turno
        # (achado 16/07, OP15-002 Lucy). Populado em _play_card()/
        # _put_into_play() sempre que um EVENT sai da mao.
        if 'event_activated_cost_gte_this_turn' in conds:
            threshold = conds['event_activated_cost_gte_this_turn']
            if not any(c >= threshold for c in me.events_activated_costs_this_turn):
                return False
        if 'don_on_field_gte' in conds and me.don_on_field() < conds['don_on_field_gte']:
            return False
        if 'don_on_field_lte' in conds and me.don_on_field() > conds['don_on_field_lte']:
            return False
        if 'don_on_field_zero_or_gte' in conds:
            n = me.don_on_field()
            if not (n == 0 or n >= conds['don_on_field_zero_or_gte']):
                return False
        if 'opp_don_on_field_gte' in conds and opp.don_on_field() < conds['opp_don_on_field_gte']:
            return False
        if 'opp_don_on_field_lte' in conds and opp.don_on_field() > conds['opp_don_on_field_lte']:
            return False
        if conds.get('don_on_field_lte_opp') and me.don_on_field() > opp.don_on_field():
            return False
        if ('don_fewer_than_opp_by_gte' in conds
                and opp.don_on_field() - me.don_on_field()
                < conds['don_fewer_than_opp_by_gte']):
            return False
        if 'chars_rested_gte' in conds:
            n_rested = sum(1 for c in me.field_chars if c.rested)
            if n_rested < conds['chars_rested_gte']:
                return False
        if 'opp_chars_rested_gte' in conds:
            # simetrico a chars_rested_gte, mas do lado do OPONENTE (achado
            # 16/07, ST24-004/OP01-032).
            n_rested_opp = sum(1 for c in opp.field_chars if c.rested)
            if n_rested_opp < conds['opp_chars_rested_gte']:
                return False
        if 'opp_hand_gte' in conds and len(opp.hand) < conds['opp_hand_gte']:
            return False
        if 'chars_gte' in conds:
            cost_filter = conds.get('chars_gte_cost_filter')
            type_filter = conds.get('chars_gte_type_filter')
            if cost_filter is not None:
                contagem = sum(1 for c in me.field_chars if c.cost >= cost_filter)
            elif type_filter is not None:
                contagem = sum(1 for c in me.field_chars
                                if type_filter.lower() in (c.sub_types or '').lower())
            else:
                contagem = len(me.field_chars)
            if contagem < conds['chars_gte']:
                return False
        if 'chars_lte' in conds:
            # 'chars_lte_power_filter' -- so conta Characters com power>=N
            # (achado 16/07, EB02-022/OP10-010), distinto do chars_lte puro
            # (conta todos).
            power_filter = conds.get('chars_lte_power_filter')
            contagem_lte = (sum(1 for c in me.field_chars if c.power >= power_filter)
                             if power_filter is not None else len(me.field_chars))
            if contagem_lte > conds['chars_lte']:
                return False
        if 'chars_fewer_than_opp_by_gte' in conds:
            diff = len(opp.field_chars) - len(me.field_chars)
            if diff < conds['chars_fewer_than_opp_by_gte']:
                return False
        if 'total_chars_cost_gte' in conds:
            if sum(c.cost for c in me.field_chars) < conds['total_chars_cost_gte']:
                return False
        if 'hand_lte' in conds and len(me.hand) > conds['hand_lte']:
            return False
        if 'hand_gte' in conds and len(me.hand) < conds['hand_gte']:
            return False
        if conds.get('just_played') and not getattr(card, 'just_played', False):
            return False
        if 'leader_is' in conds:
            if conds['leader_is'].lower() not in me.leader.name.lower():
                return False
        if 'opp_leader_attribute' in conds:
            opp_attr = (getattr(opp.leader, 'attribute', '') or '').lower()
            if conds['opp_leader_attribute'].lower() not in opp_attr:
                return False
        if 'leader_attribute' in conds:
            my_attr = (getattr(me.leader, 'attribute', '') or '').lower()
            if conds['leader_attribute'].lower() not in my_attr:
                return False
        if 'don_rested_gte' in conds and me.don_rested < conds['don_rested_gte']:
            return False
        if 'leader_type_includes' in conds:
            if _norm_type_text(conds['leader_type_includes']) not in _norm_type_text(me.leader.sub_types):
                return False
        if 'leader_type' in conds:
            if _norm_type_text(conds['leader_type']) not in _norm_type_text(me.leader.sub_types):
                return False
        if conds.get('leader_multicolor'):
            colors = set(me.leader.color.replace('/', ' ').split())
            if len(colors) < 2:
                return False
        if 'other_char_power_gte' in conds:
            outros = [c for c in me.field_chars if c is not card]
            filter_type = conds.get('other_char_power_gte_type')
            if filter_type:
                outros = [c for c in outros
                          if _norm_type_text(filter_type) in _norm_type_text(c.sub_types)]
            filter_names = [n.lower() for n in conds.get('other_char_power_gte_names', [])]
            if filter_names:
                outros = [c for c in outros
                          if any(n in c.name.lower() for n in filter_names)]
            power_of = ((lambda c: c.power) if conds.get('other_char_power_uses_base')
                        else (lambda c: c.effective_power(True)))
            if not outros or max(power_of(c) for c in outros) < conds['other_char_power_gte']:
                return False
        if 'other_char_cost_gte' in conds:
            outros = [c for c in me.field_chars if c is not card]
            if not outros or max(c.cost for c in outros) < conds['other_char_cost_gte']:
                return False
        if 'no_other_named' in conds:
            # "if you have no other [Nome]" -- condicao SEM implementacao
            # nenhuma ate 16/07 (achado via OP12-102, generalizado por
            # busca global pra 7 cartas: EB01-012, EB02-018, EB04-031,
            # OP07-060, OP08-074, OP12-102, OP15-080). Verdadeira quando
            # NAO existe outra copia (por nome) da carta nomeada no proprio
            # campo, excluindo a propria `card` que carrega o efeito.
            needle = conds['no_other_named'].lower()
            cost_eq = conds.get('no_other_named_cost_eq')
            outros = [c for c in me.field_chars
                      if c is not card and needle in c.name.lower()]
            if cost_eq is not None:
                outros = [c for c in outros if c.cost == cost_eq]
            if outros:
                return False
        if 'no_char_power_gte' in conds:
            # "if/and you have NO Characters with N (base) power or more"
            # -- negacao de other_char_power_gte (achado 16/07, EB03-004).
            threshold = conds['no_char_power_gte']
            if any(c.power >= threshold for c in me.field_chars):
                return False
        if 'has_named_character' in conds:
            # "if/and you have a [Nome] Character" -- presenca simples por
            # nome no proprio campo (achado 16/07, OP08-109 e familia:
            # OP02-031, OP07-030). Distinto de no_other_named (que exclui
            # a propria carta e checa AUSENCIA).
            needle = conds['has_named_character'].lower()
            if not any(needle in c.name.lower() for c in me.field_chars):
                return False
        if 'own_rested_cards_gte' in conds:
            # "if/and you have N or more rested cards" -- QUALQUER carta
            # rested do proprio lado (DON + Characters + Leader + Stage),
            # simetrico ao ja existente opp_rested_cards_gte. Achado 16/07
            # (ST16-003).
            rested = me.don_rested + sum(1 for c in me.field_chars if c.rested)
            rested += int(bool(getattr(me.leader, 'rested', False)))
            rested += int(bool(me.field_stage and getattr(me.field_stage, 'rested', False)))
            if rested < conds['own_rested_cards_gte']:
                return False
        if 'self_power_gte' in conds and card.effective_power(True) < conds['self_power_gte']:
            return False
        if 'leader_power_gte' in conds and me.leader.effective_power(True) < conds['leader_power_gte']:
            return False
        if 'leader_power_lte' in conds and me.leader.effective_power(True) > conds['leader_power_lte']:
            return False
        if ('leader_name_includes' in conds
                and conds['leader_name_includes'].lower() not in me.leader.name.lower()):
            return False
        if 'opp_rested_cards_gte' in conds:
            rested = opp.don_rested + sum(1 for c in opp.field_chars if c.rested)
            rested += int(bool(getattr(opp.leader, 'rested', False)))
            rested += int(bool(opp.field_stage and getattr(opp.field_stage, 'rested', False)))
            if rested < conds['opp_rested_cards_gte']:
                return False
        if 'events_in_trash_gte' in conds:
            n_events = sum(1 for c in me.trash if c.card_type.lower() == 'event')
            if n_events < conds['events_in_trash_gte']:
                return False
        if 'board_has_cost' in conds or 'board_has_cost_gte' in conds:
            # condicao de existencia: QUALQUER Character no jogo (os dois
            # campos) com custo == N exato ou >= M.
            todos = list(me.field_chars) + list(opp.field_chars)
            exatos = set(conds.get('board_has_cost', []))
            gte = conds.get('board_has_cost_gte')
            existe = any(
                c.cost in exatos or (gte is not None and c.cost >= gte)
                for c in todos)
            if not existe:
                return False
        if 'board_chars_cost_gte_count' in conds:
            # CONTAGEM (distinto de board_has_cost_gte, que so checa
            # existencia de 1) -- achado 16/07, EB04-045.
            spec = conds['board_chars_cost_gte_count']
            todos = list(me.field_chars) + list(opp.field_chars)
            n = sum(1 for c in todos if c.cost >= spec['cost_gte'])
            if n < spec['count_gte']:
                return False
        if 'opp_char_power_gte' in conds:
            if not opp.field_chars or max(c.effective_power(False) for c in opp.field_chars) < conds['opp_char_power_gte']:
                return False
        if 'board_has_power_gte' in conds:
            # condicao de existencia generica: QUALQUER Character no jogo
            # (os dois campos) com power >= N. Mesma semantica de
            # board_has_cost, mas para power -- usada por
            # cannot_attack_self_unless (ex: EB04-051).
            todos = list(me.field_chars) + list(opp.field_chars)
            if not todos or max(c.effective_power(True) for c in todos) < conds['board_has_power_gte']:
                return False
        if 'opp_chars_power_gte_count' in conds:
            # CONTAGEM (nao existencia): precisa de >= count Characters
            # distintos no campo do OPONENTE, cada um com power >= power_gte
            # -- usada por cannot_attack_self_unless (ex: EB04-005) e por
            # efeitos condicionais a board do oponente (ex: OP09-005).
            spec = conds['opp_chars_power_gte_count']
            n = sum(1 for c in opp.field_chars if c.effective_power(False) >= spec['power_gte'])
            if n < spec['count']:
                return False
        if 'opp_chars_gte' in conds and len(opp.field_chars) < conds['opp_chars_gte']:
            return False
        if 'self_type' in conds and conds['self_type'] not in card.sub_types.lower():
            return False
        if 'only_field_type' in conds:
            tipo = conds['only_field_type'].lower()
            if not me.field_chars or any(tipo not in c.sub_types.lower() for c in me.field_chars):
                return False
        if conds.get('has_face_up_life') and not any(c.life_face_up for c in me.life):
            return False

        return True

    # ── Pagamento de custos ──────────────────────────────────────────────────

    def _pay_costs(self, costs: list, card: Card) -> bool:
        """Verifica e paga custos. Retorna False se não pode pagar.
        Registra o que foi pago em self._cost_logs (para o replay mostrar)."""
        self._cost_logs = []
        # Preflight de trash -> fundo antes de qualquer mutacao. Em custos
        # compostos, rest_self aparece primeiro; sem isto a carta ficaria
        # restada mesmo quando o restante do custo fosse impagavel.
        from optcg_engine.rules_facade import eligible_cards
        for pending in costs:
            if pending.get('type') != 'place_from_trash_bottom_deck':
                continue
            candidates = eligible_cards(
                self.me.trash,
                filter_text=pending.get('filter_type', ''),
            )
            if len(candidates) < pending.get('count', 1):
                return False
        for cost in costs:
            ctype = cost['type']
            if ctype == 'rest_self':
                if card.rested:
                    return False
                card.rested = True
                self._cost_logs.append(f'custo: restou {card.name[:18]}')
            elif ctype == 'rest_self_and_leader_or_stage':
                # Custo composto: a propria carta E um Leader/Stage com
                # filtro de tipo, AMBOS precisam estar disponiveis (nao
                # rested) antes de pagar qualquer um -- pagamento parcial
                # deixaria o jogo em estado inconsistente (carta restada
                # sem o efeito ter sido de fato pago).
                if card.rested:
                    return False
                filter_type = cost.get('filter_type', '').lower()
                candidato = None
                if filter_type in self.me.leader.sub_types.lower() and not self.me.leader.rested:
                    candidato = self.me.leader
                elif (self.me.field_stage and filter_type in self.me.field_stage.sub_types.lower()
                      and not self.me.field_stage.rested):
                    candidato = self.me.field_stage
                if candidato is None:
                    return False
                card.rested = True
                candidato.rested = True
                self._cost_logs.append(
                    f'custo: restou {card.name[:15]} e {candidato.name[:15]}')
            elif ctype == 'rest_don':
                count = cost.get('count', 1)
                if self.me.don_available < count:
                    return False
                self.me.don_available -= count
                self.me.don_rested += count
                self._cost_logs.append(f'custo: restou {count} DON')
            elif ctype == 'reveal_from_hand':
                # Custo de REVELAR N cartas com filtro de tipo (achado
                # 15/07, OP08-044 Kingdew) OU de power+card_type (achado
                # 16/07, OP16-002/003/007/010/011, ST30-004: "you may
                # reveal N Character cards with X power from your hand")
                # -- so exige TER as cartas na mao, nao remove nada
                # (revelar != trashar/descartar).
                count = cost.get('count', 1)
                filter_type = _norm_type_text(cost.get('filter_type') or '')
                power_eq = cost.get('power_eq')
                card_type_req = cost.get('card_type')
                matches = [
                    c for c in self.me.hand
                    if (not filter_type or filter_type in _norm_type_text(c.sub_types or ''))
                    and (power_eq is None or c.power == power_eq)
                    and (not card_type_req or c.card_type == card_type_req)
                ]
                if len(matches) < count:
                    return False
                self._cost_logs.append(f'custo: revelou {count} carta(s) '
                                        f'com tipo {cost.get("filter_type","")}')
            elif ctype == 'trash_from_hand':
                count = cost.get('count', 1)
                # "trash N card(s) with a [Trigger] from your hand" (leader
                # Teach OP16-080 e outras 8 cartas): custo so pode ser pago
                # com carta que TEM [Trigger] -- sem esse filtro o engine
                # considerava a mao inteira como elegivel.
                from optcg_engine.rules_facade import eligible_cards
                pool = eligible_cards(
                    self.me.hand,
                    filter_text=cost.get('filter_type', ''),
                    color=cost.get('color', ''),
                    power_lte=cost.get('power_lte'),
                    power_gte=cost.get('power_gte'),
                    power_eq=cost.get('power_eq'),
                )
                if cost.get('has_trigger'):
                    pool = [c for c in pool if c.has_trigger]
                if len(pool) < count:
                    return False
                trashed = []
                trashed_names_actual = []
                for _ in range(count):
                    worst = self._choose_to_trash(pool)
                    if worst:
                        remove_by_identity(self.me.hand, worst)
                        remove_by_identity(pool, worst)
                        self.me.trash.append(worst)
                        trashed.append(worst.name[:15])
                        trashed_names_actual.append(worst.name)
                if trashed:
                    self._cost_logs.append(f'custo: trashou da mão: {", ".join(trashed)}')
                # Memoria pra "play ... with the same card name as the
                # trashed card" (achado 16/07, EB02-039 GERMA 66) -- um step
                # POSTERIOR no mesmo bloco pode filtrar pelo nome do que foi
                # trashado aqui. Atributo dedicado (nao _last_selected) pra
                # nao colidir com o mecanismo de selecao entre steps ja
                # existente (negate_effect/play_from_deck/buff_power).
                self._last_trashed_names = trashed_names_actual
            elif ctype == 'trash_typed_hand_or_named_hand_field':
                from optcg_engine.rules_facade import eligible_cards

                count = cost.get('count', 1)
                typed_hand = eligible_cards(
                    self.me.hand, filter_text=cost.get('filter_type', ''))
                named = (cost.get('alternate_name') or '').lower()
                named_hand = [c for c in self.me.hand if named in c.name.lower()]
                named_field = [c for c in self.me.field_chars if named in c.name.lower()]
                if self.me.field_stage and named in self.me.field_stage.name.lower():
                    named_field.append(self.me.field_stage)
                options = [('hand', c) for c in typed_hand + named_hand]
                options.extend(('field', c) for c in named_field)
                unique = []
                seen = set()
                for zone, candidate in options:
                    if id(candidate) not in seen:
                        unique.append((zone, candidate))
                        seen.add(id(candidate))
                if len(unique) < count:
                    return False
                for _ in range(count):
                    zone, chosen = min(
                        unique,
                        key=lambda item: (self._trash_value(item[1]) if item[0] == 'hand'
                                          else item[1].board_value() * 10))
                    if zone == 'hand':
                        remove_by_identity(self.me.hand, chosen)
                    elif chosen is self.me.field_stage:
                        self.me.field_stage = None
                    else:
                        remove_by_identity(self.me.field_chars, chosen)
                    self.me.trash.append(chosen)
                    unique = [item for item in unique if item[1] is not chosen]
                self._cost_logs.append(f'custo: trashou {count} carta(s) por tipo/nome')
            elif ctype == 'life_to_hand':
                count = cost.get('count', 1)
                if self.me.cant_take_life_this_turn or len(self.me.life) < count:
                    return False
                source = cost.get('source', 'life_top')
                taken = []
                for _ in range(count):
                    idx = 0 if source == 'life_bottom' else -1
                    life_card = self.me.life.pop(idx)
                    life_card.life_face_up = False
                    self.me.hand.append(life_card)
                    taken.append(life_card.name[:15])
                self._cost_logs.append(f'custo: pegou da Life: {", ".join(taken)}')
            elif ctype == 'trash_char_or_hand':
                from optcg_engine.rules_facade import eligible_cards

                # Custo com ESCOLHA (ex: leader Imu): trashar 1 character próprio
                # (com filtro de tipo) OU 1 carta da mão. Resolve gastando o
                # recurso de MENOR valor — naturalmente trasha um character só
                # quando ele vale menos que descartar da mão. (Escolha fina de
                # "trashar p/ encher o trash e ligar imunidade" = Bug B, futuro.)
                count = cost.get('count', 1)
                for _ in range(count):
                    chars = eligible_cards(
                        self.me.field_chars,
                        filter_text=cost.get('filter_type', ''),
                    )
                    pior_char = min(chars, key=lambda c: c.board_value(), default=None)
                    pior_mao = self._choose_to_trash(self.me.hand)
                    if pior_char is None and pior_mao is None:
                        return False
                    # Chars ATIVOS (podem atacar este turno) nunca são descartados
                    # enquanto há carta na mão disponível. O jogador correto ataca
                    # primeiro e só trasha o char depois (ou usa mão). MAS só
                    # protege quem tem poder > 0 -- um char de 0 poder (ex: Saint
                    # Shalria, cujo valor inteiro já foi gasto no On Play e nunca
                    # conecta um ataque) não ganha nada de ficar "ativo", e a
                    # guarda achava real 09/07 (log 19.25.50, usuário: "Imu pode
                    # dar alvo em Shalria") que a guarda protegia ele do mesmo
                    # jeito que um atacante de verdade, forçando trash de carta
                    # da mão sem necessidade.
                    if pior_mao is not None and pior_char is not None:
                        if (pior_char.power > 0 and not pior_char.rested
                                and not pior_char.just_played
                                and not getattr(pior_char, 'cannot_attack_until', False)):
                            # char ativo: forçar trash da mão
                            remove_by_identity(self.me.hand, pior_mao)
                            self.me.trash.append(pior_mao)
                            self._cost_logs.append(f'custo: trashou da mão {pior_mao.name[:14]}')
                            continue
                    # comparar perda real: campo e mao usam escalas proximas.
                    val_char = pior_char.board_value() * 10 if pior_char else 10**9
                    # GamePlan (HANDOFF #119): enquanto o trash ainda nao
                    # bateu o alvo do deck (ex: Imu, 7 pra imunidade dos
                    # Celestial Dragons), trashar personagem pesa MENOS —
                    # o proprio deck foi construido pra usar a lixeira como
                    # recurso, nao so como perda de campo.
                    if pior_char is not None:
                        plano = compute_game_plan(self.me)
                        if plano['trash_target'] and len(self.me.trash) < plano['trash_target']:
                            val_char *= 0.5
                    val_mao = self._trash_value(pior_mao) if pior_mao else 10**9
                    if pior_char is not None and val_char <= val_mao:
                        remove_character_from_field(self.me, pior_char, 'trash')
                        self._cost_logs.append(f'custo: trashou character {pior_char.name[:14]}')
                    elif pior_mao is not None:
                        remove_by_identity(self.me.hand, pior_mao)
                        self.me.trash.append(pior_mao)
                        self._cost_logs.append(f'custo: trashou da mão {pior_mao.name[:14]}')
            elif ctype == 'trash_self':
                if contains_identity(self.me.field_chars, card):
                    remove_character_from_field(self.me, card, 'trash')
                    self._cost_logs.append(f'custo: trashou {card.name[:18]} (ele mesmo)')
            elif ctype == 'return_own_character_to_hand':
                from optcg_engine.rules_facade import eligible_cards
                count = cost.get('count', 1)
                candidates = eligible_cards(
                    self.me.field_chars,
                    cost_gte=cost.get('cost_gte'),
                    filter_text=cost.get('filter_type', ''),
                    exclude_name=cost.get('exclude', ''),
                    exclude_card=card if cost.get('exclude_self') else None,
                )
                if len(candidates) < count:
                    return False
                returned = []
                for _ in range(count):
                    target = min(candidates, key=lambda c: c.board_value())
                    remove_character_from_field(self.me, target, 'hand')
                    remove_by_identity(candidates, target)
                    returned.append(target.name[:15])
                self._cost_logs.append(f'custo: devolveu para a mao: {", ".join(returned)}')
            elif ctype == 'don_minus':
                count = cost.get('count', 1)
                if not self._return_don_to_deck(count):
                    return False
                self._cost_logs.append(f'custo: devolveu {count} DON ao deck')
            elif ctype == 'ko_own_character':
                from optcg_engine.rules_facade import eligible_cards

                # Custo de K.O. de um Character PROPRIO (distinto de trash_self:
                # o alvo e OUTRO Character do jogador). K.O. != Trash -- precisa
                # disparar o [On K.O.] do Character escolhido. Ex: OP14-079
                # Crocodile (K.O. um Baroque Works), OP05-087 Hakuba.
                count = cost.get('count', 1)
                candidatos = eligible_cards(
                    self.me.field_chars,
                    filter_text=cost.get('filter_type', ''),
                    exclude_card=card,
                )
                if len(candidatos) < count:
                    return False
                koados = []
                for _ in range(count):
                    if not candidatos:
                        break
                    # escolhe o de menor valor de board (sacrifica o menos util),
                    # reaproveitando a heuristica de _choose_to_trash.
                    alvo = min(candidatos, key=lambda c: c.board_value())
                    remove_by_identity(candidatos, alvo)
                    remove_character_from_field(self.me, alvo, 'trash')
                    koados.append(alvo.name[:15])
                    # dispara [On K.O.] do Character K.O.ado (regra K.O. != Trash)
                    self.execute(alvo, 'on_ko', is_opp_turn=False)
                if koados:
                    self._cost_logs.append(f'custo: K.O. próprio: {", ".join(koados)}')
            elif ctype == 'trash_own_character':
                from optcg_engine.rules_facade import eligible_cards

                # Custo de TRASH (nao K.O.) de um Character PROPRIO do CAMPO
                # -- achado 16/07 (OP06-015/OP13-053/OP16-008/EB04-048/
                # OP07-085): distinto de ko_own_character (dispara [On
                # K.O.], regra K.O. != Trash) e de trash_from_hand (fonte
                # errada, texto nao menciona "from your hand"). power_eq
                # (ex: OP16-008 "10000 base power" sem "or more/or less")
                # compara contra card.power, que no nosso modelo JA E o
                # base power (buffs ficam isolados em power_buff, nunca
                # mutam .power) -- sem necessidade de campo dedicado.
                count = cost.get('count', 1)
                candidatos = eligible_cards(
                    self.me.field_chars,
                    filter_text=cost.get('filter_type', ''),
                    power_lte=cost.get('power_lte'),
                    power_gte=cost.get('power_gte'),
                    power_eq=cost.get('power_eq'),
                    exclude_card=card,
                )
                if len(candidatos) < count:
                    return False
                trashed_own = []
                for _ in range(count):
                    if not candidatos:
                        break
                    alvo = min(candidatos, key=lambda c: c.board_value())
                    remove_by_identity(candidatos, alvo)
                    remove_character_from_field(self.me, alvo, 'trash')
                    trashed_own.append(alvo.name[:15])
                if trashed_own:
                    self._cost_logs.append(f'custo: trashou do campo: {", ".join(trashed_own)}')
            elif ctype == 'place_from_trash_bottom_deck':
                from optcg_engine.rules_facade import eligible_cards

                # Custo de colocar N cartas do PRÓPRIO trash no fundo do
                # PRÓPRIO deck ("in any order" -- ordem e escolha do
                # jogador, irrelevante pro engine). Achado em auditoria de
                # buff_cost 27/06: 51 cartas usam esse custo, zero
                # cobertura antes (Kaku OP07-080, Trafalgar Law, Dragon...).
                count = cost.get('count', 1)
                candidatos = eligible_cards(
                    self.me.trash,
                    filter_text=cost.get('filter_type', ''),
                )
                if len(candidatos) < count:
                    return False
                movidos = []
                for _ in range(count):
                    # qualquer N -- "in any order" e escolha estetica do
                    # jogador, sem efeito mecanico (fundo do deck nao
                    # discrimina ordem entre as N cartas movidas agora).
                    alvo = candidatos.pop()
                    remove_by_identity(self.me.trash, alvo)
                    self.me.deck.insert(0, alvo)   # fundo do deck = inicio da lista
                    movidos.append(alvo.name[:14])
                self._cost_logs.append(f'custo: fundo do deck (do trash): {", ".join(movidos)}')
            elif ctype in ('turn_life_face_up', 'turn_life_face_down'):
                if not self.me.life:
                    return False
                alvo = self.me.life[-1]
                alvo.life_face_up = (ctype == 'turn_life_face_up')
                face = 'face-up' if alvo.life_face_up else 'face-down'
                self._cost_logs.append(f'custo: virou vida do topo {face}')
        return True

    def _return_don_to_deck(self, count: int, estado: 'GameState' = None) -> bool:
        """
        Paga um custo DON!! −X: devolve X DON do campo para o deck de DON.
        Preferência (regra do usuário): devolve primeiro o DON "sem trabalho" —
        anexado a quem JÁ atacou (restado) ou ao líder que já atacou, depois DON
        restado no banco. Evita DON ativo e DON anexado a quem ainda vai agir.
        Retorna False se não há DON suficiente devolvível.

        `estado`: por padrão self.me (uso normal, custo do PRÓPRIO jogador).
        Aceita self.opp também -- usado por opp_don_minus (achado 27/06,
        "Your opponent returns N DON!! cards from their field to their
        DON!! deck", FORÇADO no oponente, não custo próprio).
        """
        me = estado if estado is not None else self.me
        devolvidos = 0

        # Fonte 1: DON anexado a personagens que JÁ atacaram (restados)
        for c in me.field_chars:
            while c.don_attached > 0 and c.rested and devolvidos < count:
                c.don_attached -= 1
                me.don_deck += 1
                devolvidos += 1

        # Fonte 2: DON anexado ao líder se já atacou (restado)
        while me.leader.don_attached > 0 and me.leader.rested and devolvidos < count:
            me.leader.don_attached -= 1
            me.don_deck += 1
            devolvidos += 1

        # Fonte 3: DON restado no banco (gasto, parado)
        while me.don_rested > 0 and devolvidos < count:
            me.don_rested -= 1
            me.don_deck += 1
            devolvidos += 1

        # Fonte 4 (último caso): DON anexado a quem ainda NÃO atacou / DON ativo
        # — só se for inevitável. Preferimos NÃO chegar aqui (o planner deve
        # ordenar para atacar antes). Mas se o custo é obrigatório, paga.
        if devolvidos < count:
            for c in me.field_chars:
                while c.don_attached > 0 and devolvidos < count:
                    c.don_attached -= 1
                    me.don_deck += 1
                    devolvidos += 1
            while me.leader.don_attached > 0 and devolvidos < count:
                me.leader.don_attached -= 1
                me.don_deck += 1
                devolvidos += 1
            while me.don_available > 0 and devolvidos < count:
                me.don_available -= 1
                me.don_deck += 1
                devolvidos += 1

        if devolvidos:
            self._dispatch_don_returned(me, devolvidos, source_owner=self.me)
        return devolvidos >= count

    def _dispatch_don_returned(self, owner: 'GameState', amount: int,
                               source_owner: 'GameState') -> None:
        """Dispara a familia parametrizada ``when_don_returned``.

        ``amount`` e a quantidade devolvida na MESMA resolucao. Portanto duas
        devolucoes separadas de 1 nao satisfazem um limiar 2. ``source_owner``
        permite respeitar o fraseado restrito "by your effect".
        """
        other = self.opp if owner is self.me else self.me
        cards = [owner.leader, *owner.field_chars]
        if owner.field_stage:
            cards.append(owner.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get('when_don_returned')
            if not entry or amount < entry.get('return_count_gte', 1):
                continue
            timing = entry.get('owner_turn')
            if timing == 'your' and not owner.is_active_turn:
                continue
            if timing == 'opponent' and owner.is_active_turn:
                continue
            if entry.get('by_own_effect') and source_owner is not owner:
                continue
            marker = (owner.global_turn, 'when_don_returned')
            if entry.get('once_per_turn') and getattr(source, '_event_once_marker', None) == marker:
                continue
            logs = EffectExecutor(owner, other).execute(source, 'when_don_returned')
            if logs and entry.get('once_per_turn'):
                source._event_once_marker = marker

    def _dispatch_damage_or_own_char_ko(self, owner: 'GameState',
                                        ko_card: 'Card | None' = None) -> None:
        """Dispara evento de dano recebido OU K.O. de Character proprio.

        ``ko_card=None`` representa dano. Com carta, valida o base power
        minimo antes de resolver. O requisito DON anexado e o once-per-turn
        continuam centralizados em ``execute``.
        """
        other = self.opp if owner is self.me else self.me
        cards = [owner.leader, *owner.field_chars]
        for source in list(cards):
            entry = get_card_effects(source.code).get(
                'when_damage_or_own_char_ko')
            if not entry:
                continue
            if (ko_card is not None
                    and ko_card.power < entry.get('own_char_base_power_gte', 0)):
                continue
            marker = (owner.global_turn, 'when_damage_or_own_char_ko')
            if (entry.get('once_per_turn')
                    and getattr(source, '_damage_ko_once_marker', None) == marker):
                continue
            logs = EffectExecutor(owner, other).execute(
                source, 'when_damage_or_own_char_ko')
            if logs and entry.get('once_per_turn'):
                source._damage_ko_once_marker = marker

    # ── Execução de steps individuais ────────────────────────────────────────

    def _resolve_cost_lte(self, step: dict, default=99):
        """
        Resolve o valor de cost_lte de um step, tratando os dois casos:
        (1) valor FIXO (int), como ja era -- maioria dos casos.
        (2) valor DINAMICO ("equal to or less than the number of DON!! cards
            on your/your opponent's field"), confirmado em 4 cartas:
            OP13-099 (Empty Throne), OP08-098 (Kalgara), OP11-022
            (Shirahoshi) -- as 3 usam DON!! do PROPRIO campo
            ('don_count_self') -- e P-090 (Charlotte Smoothie), que usa
            DON!! do campo do OPONENTE ('don_count_opp') -- texto da carta
            diz explicitamente "on your opponent's field", lado invertido
            das outras 3. Sem esta distincao, um simbolo generico unico
            erraria a Smoothie.
        Antes desta funcao, o parser ja emitia cost_lte=99 (fixo, "sem
        limite") para as 4 cartas -- nao quebrava o engine, mas tornava o
        limite real do efeito (baseado em DON!! em campo) inexistente na
        pratica: qualquer carta de custo ate 99 passava, quando a regra real
        e mais restritiva na maioria das posicoes de jogo (DON!! em campo
        raramente chega a 99).
        """
        cost_lte = step.get('cost_lte', default)
        if cost_lte == 'don_count_self':
            return self.me.don_available + self.me.don_rested
        if cost_lte == 'don_count_opp':
            return self.opp.don_available + self.opp.don_rested
        return cost_lte

    def _execute_step(self, step: dict, card: Card) -> str:
        from optcg_engine.rules_facade import eligible_cards

        action = step.get('action', '')
        me = self.me
        opp = self.opp

        # Condicao PROPRIA do step (distinta da condicao global do entry,
        # ja checada em _execute_trigger antes de chamar qualquer step).
        # Existe para separar "[A incondicional]. Then, if [cond], [B]" --
        # a condicao do "Then, if" deve bloquear SO o step B, nao o A que
        # vem antes dela no texto. Sem isto, qualquer condicao so podia
        # valer pro bloco inteiro (todos os steps), causando scope leakage
        # (confirmado em ST14-001/ST14-008 e ~44 outras cartas, 23/06).
        step_conds = step.get('conditions')
        if step_conds and not self._check_conditions(step_conds, card):
            return ''
        if step.get('timing') == 'end_of_turn' and not step.get('_from_queue'):
            queued = dict(step)
            queued['_from_queue'] = True
            me.end_of_turn_queue.append({'step': queued, 'card': card})
            return f'agendou {action} para o fim do turno'

        # ── Busca (StartTopDeck + AddToHand + FinalizeTopDeck) ────────────────
        if action == 'look_top_deck':
            # Apenas marca quantas cartas serão vistas — próximo step faz a seleção
            return ''

        if action == 'add_to_hand':
            from optcg_engine.rules_facade import eligible_cards

            if not me.deck:
                return ''
            # Número de cartas a olhar (do step anterior look_top_deck)
            # Busca o look_top_deck no mesmo bloco de efeitos
            effects = get_card_effects(card.code)
            look_count = 5  # padrão
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                        break

            look = min(look_count, len(me.deck))
            candidates = me.deck[-look:]

            exclude = step.get('exclude', [])
            cost_lte = self._resolve_cost_lte(step, default=99)
            filtered = eligible_cards(
                candidates,
                cost_lte=cost_lte,
                cost_gte=step.get('cost_gte'),
                power_lte=step.get('power_lte', 999999),
                filter_text=step.get('filter_type', ''),
                include_text=True,
            )
            if exclude:
                filtered = [
                    c for c in filtered
                    if not any(ex.lower() in c.name.lower() for ex in exclude)
                ]

            count = step.get('count', 1)
            taken = []
            # _trash_value = avaliar_carta (situacional, achado 07/07: search
            # do Laffitte/Shiryu trazia sempre o corpo mais "parrudo",
            # ignorando cartas mais uteis pra situacao — preservado, e a
            # base da conta) + as protecoes de MANTER NA MAO: win-con do
            # GamePlan (+150 enquanto o DON nao bate o alvo), carta cara
            # (custo>=7), evento counter. "Qual carta eu mais quero na mao"
            # e exatamente a pergunta do search — achado real 12/07 (spy de
            # trash, 13x/20 partidas): searchers do Imu viam a Five Elders
            # no top 5, avaliar_carta puro (~45, sem protecao) perdia pra
            # qualquer corpo jogavel e a win-con ia pro trash com o resto
            # (mill do trash_rest) — e OP13-082 nao e reanimavel (o
            # play_from_trash dela filtra power 5000; a copia milada morre).
            for _ in range(min(count, len(filtered))):
                best = max(filtered, key=self._trash_value) if filtered else None
                if best:
                    taken.append(best)
                    remove_by_identity(filtered, best)

            for c in taken:
                remove_by_identity(me.deck, c)
                me.hand.append(c)
                if step.get('revealed_to_opponent') is True:
                    me.revealed_to_opponent.add(id(c))

            # Resto permanece no deck (será tratado pelo próximo step)
            me.searchers_used += 1
            names = ', '.join(c.name[:15] for c in taken)
            if names:
                return f'olhou {look} do topo -> pegou: {names}'
            else:
                return f'olhou {look} do topo -> nada para pegar'

        if action == 'peek_opp_deck_top':
            # Efeito apenas informacional: nao move nem reordena a carta.
            return 'olhou o topo do deck do oponente' if opp.deck else ''

        if action == 'reveal_opp_deck_top_choose_cost':
            # A escolha acontece ANTES da revelacao, portanto nunca usamos a
            # carta do topo para decidir o palpite. O censo representa a
            # informacao de decklist que a IA possui e escolhe o custo modal;
            # empates favorecem o menor custo para manter determinismo.
            if not opp.deck:
                return ''
            census = getattr(opp, 'full_deck_census', None) or {}
            by_cost = census.get('by_cost', {})
            if by_cost:
                chosen_cost = max(
                    ((int(cost), qty) for cost, qty in by_cost.items()),
                    key=lambda item: (item[1], -item[0]),
                )[0]
            else:
                # Estados unitarios/bridge antigos podem nao ter censo. Usa
                # um palpite fixo plausivel e, principalmente, nao consulta
                # o topo oculto para fabricar um acerto.
                chosen_cost = 3
            revealed = opp.deck[-1]
            matched = revealed.cost == chosen_cost
            nested_logs = []
            if matched:
                for nested in step.get('on_match_steps', []):
                    nested_log = self._execute_step(nested, card)
                    if nested_log:
                        nested_logs.append(nested_log)
            result = (f'escolheu custo {chosen_cost}, revelou '
                      f'{revealed.name[:15]} (custo {revealed.cost})')
            if matched:
                result += ': acertou'
                if nested_logs:
                    result += ' | ' + ' | '.join(nested_logs)
            else:
                result += ': errou'
            return result

        if action == 'reveal_deck_top_conditional':
            # "Reveal 1 card from the top of your deck. If [condicao],
            # [efeito]. [Then, place the revealed card at the bottom of
            # your deck]." -- achado 16/07 (10 cartas: EB01-029, OP04-011,
            # OP14-044, OP15-065, ST17-001, ST22-003/006/007/012/016).
            # A carta revelada fica no TOPO por padrao (return_to=='top',
            # regra oficial de reveal sem mover) -- so vai pro fundo
            # quando o step diz explicitamente.
            if not me.deck:
                return ''
            revealed = me.deck[-1]
            cond = step.get('condition', {})
            matched = True
            if cond.get('revealed_card_type') and not _norm_type_text(
                    cond['revealed_card_type']) in _norm_type_text(revealed.sub_types):
                matched = False
            if matched and cond.get('revealed_card_cost_lte') is not None and \
                    revealed.cost > cond['revealed_card_cost_lte']:
                matched = False
            if matched and cond.get('revealed_card_cost_gte') is not None and \
                    revealed.cost < cond['revealed_card_cost_gte']:
                matched = False
            if matched and cond.get('revealed_card_power_gte') is not None and \
                    (revealed.card_type != 'CHARACTER' or revealed.power < cond['revealed_card_power_gte']):
                matched = False

            if step.get('return_to') == 'bottom':
                me.deck.pop()
                me.deck.insert(0, revealed)

            nested_logs = []
            if matched:
                for nested in step.get('on_match_steps', []):
                    nested_log = self._execute_step(nested, card)
                    if nested_log:
                        nested_logs.append(nested_log)

            result = f'revelou {revealed.name[:15]} do topo do deck'
            if matched:
                result += ': bateu a condicao'
                if nested_logs:
                    result += ' | ' + ' | '.join(nested_logs)
            else:
                result += ': nao bateu a condicao'
            return result

        if action == 'trash_rest':
            # Cartas que foram vistas mas não pegas vão ao trash
            # Identifica quais cartas do topo foram vistas
            effects = get_card_effects(card.code)
            look_count = 5
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                        break
            # As cartas não tomadas ficam no topo do deck
            # Quantas foram tomadas: count do add_to_hand
            taken_count = 1
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'add_to_hand':
                        taken_count = s.get('count', 1)
                        break
            # O resto = look_count - taken = vão ao trash
            rest_count = max(0, look_count - taken_count)
            trashed = []
            for _ in range(min(rest_count, len(me.deck))):
                if me.deck:
                    c = me.deck.pop()
                    me.trash.append(c)
                    trashed.append(c.name[:12])
            return f'trash resto: {", ".join(trashed)}' if trashed else ''

        if action == 'deck_bottom_rest':
            # Resto vai ao fundo do deck (já está no topo, move para o fundo)
            effects = get_card_effects(card.code)
            look_count = 5
            taken_count = 1
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                    if s.get('action') == 'add_to_hand':
                        taken_count = s.get('count', 1)
            rest_count = max(0, look_count - taken_count)
            moved = []
            for _ in range(min(rest_count, len(me.deck))):
                if me.deck:
                    c = me.deck.pop()  # tira do topo
                    me.deck.insert(0, c)  # coloca no fundo
                    moved.append(c)
            return f'{len(moved)} carta(s) no fundo do deck' if moved else ''

        if action in ('deck_reorder_rest', 'deck_top_rest'):
            # Achado 01/07/2026: 'deck_top_rest' e um nome de action
            # equivocado do parser -- TODAS as 21 ocorrencias reais no banco
            # (16 deck_reorder_rest + 5 deck_top_rest) sao o mesmo texto
            # "place the rest/them at the top OR BOTTOM of the deck in any
            # order" (escolha livre, nunca um "place at the top" puro sem
            # "or bottom"). 'deck_top_rest' nasceu de um regex que casa o
            # PREFIXO "place the rest at the top" antes de checar o sufixo
            # "or bottom" -- confirmado: nenhuma carta no banco tem so
            # "place the rest at the top" sem "or bottom". As duas actions
            # tem a MESMA semantica de execucao aqui (nao vale a pena tocar
            # o parser/regenerar DBs so por causa do nome).
            # Heuristica (mesmo principio do peek_life 'all'): a IA controla
            # a ordem livremente, entao bota a carta mais valiosa no TOPO
            # (fim da lista = proxima a ser comprada).
            effects = get_card_effects(card.code)
            look_count = 5
            taken_count = 0
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                    if s.get('action') == 'add_to_hand':
                        taken_count = s.get('count', 1)
            rest_count = max(0, look_count - taken_count)
            seen = []
            for _ in range(min(rest_count, len(me.deck))):
                seen.append(me.deck.pop())
            if not seen:
                return ''
            seen.sort(key=lambda c: c.board_value())  # pior primeiro, melhor por ultimo
            me.deck.extend(seen)  # melhor carta -> fim da lista = topo do deck
            return f'{len(seen)} carta(s) reordenada(s) no deck (melhor no topo)'

        if action == 'activate_main_effect':
            # Trigger que ativa o efeito Main da carta. CORRIGIDO 24/06:
            # antes chamava self.execute(card, 'main') DUAS vezes (uma no
            # if, outra no corpo) -- isso duplicava o efeito quando ambas
            # tinham sucesso, e causava IndexError quando a 2a chamada
            # retornava lista vazia (ex: 'main' tinha once_per_turn e já
            # havia sido consumido pela 1a chamada). Executa uma única vez
            # e junta os logs com segurança.
            logs = self.execute(card, 'main')
            return '; '.join(l for l in logs if l) if logs else ''

        if action == 'peek_life':
            target = step.get('target', 'any')
            count = step.get('count', 1)
            pools = ([(me, 'propria')] if target == 'self'
                     else [(opp, 'oponente')] if target == 'opponent'
                     else [(opp, 'oponente'), (me, 'propria')])
            for owner, label in pools:
                if not owner.life:
                    continue
                n = len(owner.life) if count == 'all' else min(int(count), len(owner.life))
                if count == 'all':
                    seen = owner.life[-n:]
                    owner.life[-n:] = sorted(
                        seen,
                        key=lambda c: c.board_value() + (2500 if c.has_trigger else 0),
                        reverse=(owner is me),
                    )
                    return f'olhou/reordenou {n} vida(s) ({label})'
                top = owner.life[-1]
                should_bottom = owner is opp and (top.has_trigger or top.counter > 0 or top.board_value() >= 5000)
                if should_bottom:
                    owner.life.insert(0, owner.life.pop())
                    return f'olhou vida do {label}: moveu topo para o fundo'
                return f'olhou vida do {label}: manteve topo'
            return ''

        if action == 'life_to_deck_top':
            if not me.life:
                return ''
            count = min(step.get('count', 1), len(me.life))
            moved = []
            for _ in range(count):
                # O controlador acabou de olhar toda a Life; coloca no topo
                # do deck a carta de maior valor estimado para a proxima compra.
                best = max(me.life, key=lambda c: c.board_value() + c.counter / 1000)
                remove_by_identity(me.life, best)
                best.life_face_up = False
                me.deck.append(best)
                moved.append(best.name[:15])
            return f'Life para topo do deck: {", ".join(moved)}'

        if action in ('turn_life_face_up', 'turn_life_face_down'):
            owner = opp if step.get('target') == 'opponent' else me
            if not owner.life:
                return ''
            count = len(owner.life) if step.get('count') == 'all' else min(int(step.get('count', 1)), len(owner.life))
            desired = action == 'turn_life_face_up'
            changed = 0
            for c in owner.life[-count:]:
                if c.life_face_up != desired:
                    c.life_face_up = desired
                    changed += 1
            face = 'face-up' if desired else 'face-down'
            return f'virou {changed} vida(s) {face}' if changed else f'vida ja estava {face}'

        if action == 'cannot_attack_leader_turn':
            me.cannot_attack_leader_this_turn = True
            return 'nao pode atacar Leader neste turno'

        if action == 'return_don_until_match_opp':
            target_total = opp.don_on_field()
            returned = 0
            while me.don_on_field() > target_total:
                before = me.don_on_field()
                if not self._return_don_to_deck(1, estado=me) or me.don_on_field() == before:
                    break
                returned += 1
            return f'devolveu {returned} DON ate igualar o oponente' if returned else ''

        # ── Draw ──────────────────────────────────────────────────────────────
        if action == 'draw':
            count = step.get('count', 1)
            drawn = []
            for _ in range(count):
                if me.deck:
                    c = me.deck.pop()
                    me.hand.append(c)
                    drawn.append(c.name[:12])
            # then_trash após draw
            then_trash = step.get('then_trash', 0)
            trashed_after = []
            for _ in range(then_trash):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    remove_by_identity(me.hand, worst)
                    me.trash.append(worst)
                    trashed_after.append(worst.name[:12])
            if not drawn:
                return ''
            msg = f'comprou: {", ".join(drawn)}'
            if trashed_after:
                msg += f' (e trashou: {", ".join(trashed_after)})'
            return msg

        # ── KO ───────────────────────────────────────────────────────────────
        if action in ('ko', 'trash_character'):
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                choose_lowest_board_value,
                eligible_cards,
            )
            # 'trash_character' usa a MESMA mecanica de remocao de campo que
            # 'ko' (vai para o trash do dono). A diferenca de regra real do
            # jogo -- K.O. dispara o gatilho [On K.O.] do alvo, Trash de
            # personagem NAO dispara -- ainda nao tem efeito aqui porque o
            # engine hoje so dispara on_ko por morte em BATALHA (ver
            # _resolve_battle), nunca por efeito de carta de nenhum dos dois
            # tipos. Quando essa cascata for implementada para efeitos de
            # carta, ela deve checar `action == 'ko'` antes de disparar.
            count = step.get('count', 1)
            target_type = step.get('target', 'opp_character')
            cost_lte = self._resolve_cost_lte(step, default=None)
            cost_eq = step.get('cost_eq')
            power_lte = step.get('power_lte')
            rested_only = step.get('rested_only', False)

            if target_type == 'opp_stage':
                if opp.field_stage and (cost_lte is None or opp.field_stage.cost <= cost_lte):
                    ko_name = opp.field_stage.name[:20]
                    opp.trash.append(opp.field_stage)
                    opp.field_stage = None
                    return f'KO stage: {ko_name}'
                return ''

            # KO personagem(s) -- opp_character (so do oponente),
            # self_character (so o PROPRIO campo, ex: Five Elders OP13-082
            # "trash all of your Characters" -- distinto de all_character
            # por afetar so um lado), ou all_character (ambos os lados, ex:
            # board wipe simetrico do Kaido OP01-094/Kaido & Linlin OP08-119
            # -- exclude_self impede a propria carta se autodestruir,
            # confirmado por foto real "K.O. all Characters other than
            # this Character").
            def target_pool(cards):
                return eligible_cards(
                    cards,
                    cost_lte=cost_lte,
                    cost_eq=cost_eq,
                    power_lte=power_lte,
                    rested_only=rested_only,
                    filter_text=step.get('filter_type', ''),
                    exclude_card=card if step.get('exclude_self', False) else None,
                )

            if target_type == 'all_character':
                pools = [(opp, target_pool(opp.field_chars)),
                         (me, target_pool(me.field_chars))]
            elif target_type == 'self_character':
                pools = [(me, target_pool(me.field_chars))]
            else:
                pools = [(opp, target_pool(opp.field_chars))]

            koed = []
            sub_logs = []
            immune_skipped = []
            imm_kind = 'ko' if action == 'ko' else 'removal'
            for owner, candidates in pools:
                # Alvo no OPONENTE = remocao, mira o mais valioso. Alvo no
                # PROPRIO campo = sacrificio/drawback ("trash 1 dos seus"),
                # mira o MENOS valioso — mesma regua que
                # _worth_paying_optional_costs usou pra aprovar o custo
                # (min board_value); escolher o mais caro aqui pagaria um
                # custo aprovado como "quase gratis" com a melhor carta do
                # campo. Pra "trash all" (count 99, ex: Five Elders) a
                # ordem nao muda nada.
                escolhe = (choose_lowest_board_value if owner is me
                           else choose_highest_board_value)
                for _ in range(min(count, len(candidates))):
                    target = escolhe(candidates)
                    # Imunidade: o alvo pode ser imune a KO/remoção por efeito do
                    # oponente. Pula o alvo (não conta como removido).
                    other = me if owner is opp else opp
                    source_is_opp = owner is opp
                    if is_immune(
                        target,
                        imm_kind,
                        owner,
                        other,
                        source_is_opp=source_is_opp,
                        ko_context='effect' if imm_kind == 'ko' else None,
                    ):
                        immune_skipped.append(target.name[:12])
                        remove_by_identity(candidates, target)
                        continue
                    # Antes de remover de fato, verifica se o ALVO tem
                    # substitute_ko/substitute_removal ativo -- e um efeito
                    # passivo do proprio target, avaliado do ponto de vista
                    # do SEU dono (quem paga o custo da substituicao).
                    ee_target = EffectExecutor(owner, me if owner is opp else opp)
                    sub_log = ee_target.try_any_substitute(
                        target,
                        'ko' if action == 'ko' else 'removal',
                        source_is_opp=source_is_opp,
                    )
                    if sub_log:
                        sub_logs.append(sub_log)
                        remove_by_identity(candidates, target)
                        continue
                    remove_character_from_field(owner, target, 'trash')
                    if action == 'ko':
                        ee_target.execute(target, 'on_ko', is_opp_turn=owner is opp)
                        ee_target._dispatch_damage_or_own_char_ko(owner, target)
                    remove_by_identity(candidates, target)
                    koed.append(target.name[:15])
            label = 'KO' if action == 'ko' else 'Trash'
            partes = []
            if koed:
                partes.append(f'{label}: {", ".join(koed)}')
            if immune_skipped:
                partes.append(f'imune: {", ".join(immune_skipped)}')
            partes.extend(sub_logs)
            return ' | '.join(partes)

        # ── KO condicional sobre a carta selecionada anteriormente no bloco ──
        if action == 'ko_selected':
            # "Then, if that Character has a cost of N or less, K.O. it" --
            # segunda clausula encadeada apos negate_effect (achado 15/07,
            # OP09-098 Black Hole). Alvo = self._last_selected, gravado pelo
            # step anterior no MESMO bloco (negate_effect). Mira sempre o
            # campo do OPONENTE (e o unico caso ate agora).
            alvo = self._last_selected
            cost_lte = step.get('cost_lte')
            if alvo is None or alvo not in opp.field_chars:
                return ''
            if cost_lte is not None and alvo.cost > cost_lte:
                return ''
            if is_immune(alvo, 'ko', opp, me, source_is_opp=True, ko_context='effect'):
                return f'imune: {alvo.name[:15]}'
            ee_target = EffectExecutor(opp, me)
            sub_log = ee_target.try_any_substitute(alvo, 'ko', source_is_opp=True)
            if sub_log:
                return sub_log
            ko_name = alvo.name[:15]
            remove_character_from_field(opp, alvo, 'trash')
            ee_target.execute(alvo, 'on_ko', is_opp_turn=True)
            ee_target._dispatch_damage_or_own_char_ko(opp, alvo)
            return f'KO: {ko_name}'

        # ── Bounce ───────────────────────────────────────────────────────────
        if action == 'bounce':
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                eligible_cards,
            )
            count = step.get('count', 1)
            cost_lte = self._resolve_cost_lte(step, default=99)

            candidates = eligible_cards(
                opp.field_chars,
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                power_gte=step.get('power_gte'),
                power_eq=step.get('power_eq'),
                rested_only=step.get('rested_only', False),
                active_only=step.get('active_only', False),
                filter_text=step.get('filter_type', ''),
            )
            bounced = []
            immune_skipped = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                # Bounce é remoção do campo -> respeita imunidade a removal
                if is_immune(target, 'removal', opp, me, source_is_opp=True):
                    immune_skipped.append(target.name[:12])
                    remove_by_identity(candidates, target)
                    continue
                remove_character_from_field(opp, target, 'hand')
                remove_by_identity(candidates, target)
                bounced.append(target.name[:15])
            out = []
            if bounced: out.append(f'bounce: {", ".join(bounced)}')
            if immune_skipped: out.append(f'imune: {", ".join(immune_skipped)}')
            return ' | '.join(out)

        # ── Restar oponente ───────────────────────────────────────────────────
        if action == 'rest_opp_character':
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                eligible_cards,
            )
            count = step.get('count', 1)
            cost_lte = self._resolve_cost_lte(step, default=99)

            # imunidade a rest forçado (achado 01/07/2026, ex: OP12-021,
            # OP15-024, OP11-046) -- DISTINTA de cannot_be_rested_until
            # (trava posta por OUTRA carta, mecanica oposta, ja filtrada
            # acima).
            candidates = eligible_cards(
                [c for c in opp.field_chars
                 if not c.cannot_be_rested_until
                 and not is_immune(c, 'rest', opp, self.me, source_is_opp=True)],
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                don_attached_gte=step.get('don_attached_gte'),
                active_only=True,
                filter_text=step.get('filter_type', ''),
            )
            rested = []
            sub_logs = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                # Substituicao de rest (achado 15/07, PRB02-006 Zoro): "If
                # this Character would be rested by your opponent's
                # Character's effect, you may rest 1 of your other
                # Characters instead". Checado do ponto de vista do DONO
                # do alvo (mesmo padrao ja usado por KO/removal acima --
                # EffectExecutor(opp, self.me), 'opp' aqui e quem SERIA
                # restado).
                ee_target = EffectExecutor(opp, self.me)
                sub_log = ee_target.try_any_substitute(target, 'rest', source_is_opp=True)
                if sub_log:
                    sub_logs.append(sub_log)
                    remove_by_identity(candidates, target)
                    continue
                target.rested = True
                remove_by_identity(candidates, target)
                rested.append(target.name[:15])
            out = []
            if rested: out.append(f'restou: {", ".join(rested)}')
            if sub_logs: out.append(' | '.join(sub_logs))
            return ' | '.join(out)

        # ── rest_opp_don: restar DON!! do OPONENTE -- desvantagem de tempo
        # (ele tem menos DON ativo pro turno dele), DISTINTA de
        # rest_opp_character (alvo é Character, não DON!! card). Achado na
        # auditoria do censo 0_nao_classificado (27/06): P-060 Tot Musica,
        # ST02-008 Scratchmen Apoo. NUNCA confundir com don_minus (que
        # devolve DON ao deck do PRÓPRIO jogador como custo) -- aqui o DON
        # do oponente continua no campo dele, só fica rested.
        if action == 'rest_opp_don':
            count = step.get('count', 1)
            rested_n = min(count, opp.don_available)
            opp.don_available -= rested_n
            opp.don_rested += rested_n
            return f'restou {rested_n} DON do oponente' if rested_n else ''

        # ── opp_don_minus: FORÇA o oponente a devolver N DON!! do campo
        # dele pro DON deck DELE (perde DON pro resto da partida, mais forte
        # que rest_opp_don que só atrasa por 1 turno). DISTINTA de
        # don_minus (que devolve DON do PRÓPRIO jogador como custo). Achado
        # 27/06: Magellan OP02-085/OP16-074, Senor Pink OP14-065, Judgment
        # of Hell, Hydra, Venom Road. Reaproveita _return_don_to_deck
        # generalizada -- mesma preferência de "devolver o DON que menos
        # importa" vale pro oponente escolhendo por si mesmo.
        if action == 'opp_don_minus':
            count = step.get('count', 1)
            self._return_don_to_deck(count, estado=opp)
            return f'oponente devolveu até {count} DON pro deck'

        # "your opponent adds N card(s) from their Life area to their hand"
        # -- forca o oponente a mover da propria vida para a propria mao
        # (enfraquece a vida dele, da carta a ele na mao). P-009 Law.
        if action == 'opp_life_to_hand':
            count = step.get('count', 1)
            moved = []
            for _ in range(min(count, len(opp.life))):
                c = opp.life.pop()
                c.life_face_up = False
                opp.hand.append(c)
                moved.append(c.name[:12])
            return f'oponente moveu da vida pra mao: {", ".join(moved)}' if moved else ''

        # ── KO se custo == DON anexado (OP15-031 Purinpurin) ────────────────────
        # "Select up to 1 of your opponent's rested Characters. If the chosen
        # Character has a cost equal to the number of DON!! cards given to it,
        # K.O. it." -- escolhe o melhor rested do oponente que satisfaz a
        # condicao cost == don_attached; KO se achar.
        if action == 'ko_if_cost_eq_don':
            from optcg_engine.rules_facade import card_matches_filter
            filter_type = step.get('filter_type', '')
            rested_only = step.get('rested_only', True)
            candidates = [c for c in opp.field_chars
                          if (not rested_only or c.rested)
                          and card_matches_filter(c, filter_type)
                          and c.cost == c.don_attached
                          and not is_immune(c, 'ko', opp, me, source_is_opp=True)]
            if candidates:
                # escolhe o mais valioso que satisfaz a condicao
                alvo = max(candidates, key=lambda c: c.board_value())
                remove_character_from_field(opp, alvo, 'trash')
                ee_ko = EffectExecutor(opp, me)
                ee_ko.execute(alvo, 'on_ko', is_opp_turn=False)
                return f'K.O. {alvo.name[:15]} (cost=={alvo.cost}==DON!!)'
            return ''

        # ── Swap base power entre 2 Characters (OP14-001/OP14-017) ─────────────
        if action == 'swap_base_power':
            from optcg_engine.rules_facade import eligible_cards, card_matches_filter
            target = step.get('target', 'own_two_chars')
            filter_type = step.get('filter_type', '')
            power_lte = step.get('power_lte')
            pool = me.field_chars if 'own' in target else opp.field_chars
            cands = [c for c in pool
                     if card_matches_filter(c, filter_type)
                     and (power_lte is None or c.effective_power(True) <= power_lte)]
            if len(cands) >= 2:
                # Escolhe os dois com maior board_value
                cands.sort(key=lambda c: -c.board_value())
                a, b = cands[0], cands[1]
                pa = a.effective_power('own' in target)
                pb = b.effective_power('own' in target)
                a.base_power_override = pb
                b.base_power_override = pa
                return f'trocou power: {a.name[:12]}({pa}->{pb}) / {b.name[:12]}({pb}->{pa})'
            return ''

        # ── Mutual KO após batalha (ST08-013 Mr.2) ──────────────────────────────
        # "K.O. the opponent's Character you battled with. If you do, K.O. this
        # Character." -- simplificacao: KO o melhor char do oponente + KO self.
        if action == 'ko_battled_opp_char_and_self':
            if opp.field_chars:
                target_opp = max(opp.field_chars, key=lambda c: c.board_value())
                if not is_immune(target_opp, 'ko', opp, me, source_is_opp=True):
                    remove_character_from_field(opp, target_opp, 'trash')
                    ee_opp = EffectExecutor(opp, me)
                    ee_opp.execute(target_opp, 'on_ko', is_opp_turn=True)
                    # KO self (o proprio character que ativou o efeito)
                    if contains_identity(me.field_chars, card):
                        remove_character_from_field(me, card, 'trash')
                    return f'KO mutuo: {target_opp.name[:12]} e {card.name[:12]}'
            return ''

        # ── ST13-003 Luffy Leader: face-up Life → deck bottom rule ─────────────
        if action == 'face_up_life_to_deck_rule':
            me.face_up_life_to_deck = True
            return 'regra: vida face-up vai pro fundo do deck em vez da mao'

        # ── Redirect attack target (OP14-060) -- no-op engine, parser only ──────
        if action == 'redirect_attack_target':
            return ''  # complexidade de interrupcao de resolucao de ataque inviavel

        # ── Activate trash event Main (EB03-031) -- no-op engine, parser only ───
        if action == 'activate_trash_event_main':
            return ''  # executar efeito de evento do trash exige VM separada

        # ── Imunidade a KO temporária para tipo próprio (OP09-033 Nico Robin) ──
        # Concede immunity_ko_until a todos os PROPRIOS Characters que
        # correspondem ao filter_type. Limpo no refresh_phase do dono.
        if action == 'grant_ko_immunity_type':
            from optcg_engine.rules_facade import card_matches_filter
            filter_type = step.get('filter_type', '')
            dur = step.get('duration', 'opp_turn_end')
            granted = []
            for c in me.field_chars + [me.leader]:
                if card_matches_filter(c, filter_type):
                    c.immunity_ko_until = dur
                    granted.append(c.name[:12])
            return f'imunidade a KO concedida: {", ".join(granted)}' if granted else ''

        # ── Coloca Character do oponente na VIDA DELE face-up ──────────────────
        # "Add up to N of your opponent's [X] Characters to the top/bottom of
        # your opponent's Life cards face-up." (OP04-097 Otama, OP05-111 Hotori,
        # EB02-057 Mad Treasure). Remove do campo do oponente e insere na vida
        # dele (face-up). Heuristica: escolhe o PIOR Character do oponente (menor
        # board_value) pra maximizar o dano ao campo dele; o destino dentro da
        # vida e o topo ('life_top') por padrao.
        if action == 'place_opp_char_to_opp_life':
            from optcg_engine.rules_facade import eligible_cards, card_matches_filter
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte')
            filter_type = step.get('filter_type', '')
            candidates = [c for c in opp.field_chars
                          if (cost_lte is None or c.cost <= cost_lte)
                          and card_matches_filter(c, filter_type)]
            placed = []
            for _ in range(min(count, len(candidates))):
                worst = min(candidates, key=lambda c: c.board_value())
                # Move direto campo -> Life. Usar 'hand' aqui duplicava a
                # carta na mao e na Life ao mesmo tempo.
                worst.life_face_up = True
                dest = step.get('dest', 'life_top')
                real_dest = 'life_bottom' if dest == 'life_bottom' else 'life_top'
                remove_character_from_field(opp, worst, real_dest)
                remove_by_identity(candidates, worst)
                placed.append(worst.name[:12])
            return f'mandou {", ".join(placed)} pra vida do oponente face-up' if placed else ''

        if action == 'character_to_owner_life':
            from optcg_engine.rules_facade import card_matches_filter
            target_scope = step.get('target', 'any')
            cost_lte = step.get('cost_lte')
            power_eq = step.get('power_eq')
            filter_type = step.get('filter_type', '')
            exclude = step.get('exclude', '').lower()

            def eligible(owner, c):
                return ((cost_lte is None or c.cost <= cost_lte)
                        and (power_eq is None or c.power == power_eq)
                        and card_matches_filter(c, filter_type)
                        and (not exclude or exclude not in c.name.lower()))

            pools = []
            if target_scope in ('own', 'any'):
                pools.extend((me, c, False) for c in me.field_chars if eligible(me, c))
            if target_scope in ('opponent', 'any'):
                pools.extend((opp, c, True) for c in opp.field_chars if eligible(opp, c))
            moved = []
            for _ in range(min(step.get('count', 1), len(pools))):
                # Para alvo livre, remover a maior ameaca adversaria tem
                # precedencia; em alvo proprio, salva o menor board value.
                opp_pool = [x for x in pools if x[2]]
                if opp_pool:
                    owner, chosen, is_opp = max(
                        opp_pool, key=lambda x: x[1].board_value())
                    if is_immune(chosen, 'removal', opp, me, source_is_opp=True):
                        pools.remove((owner, chosen, is_opp))
                        continue
                else:
                    owner, chosen, is_opp = min(
                        pools, key=lambda x: x[1].board_value())
                dest = step.get('dest', 'life_top')
                # top_or_bottom e escolha do controlador; topo e o default
                # deterministico atual, preservando a carta como proxima Life.
                real_dest = 'life_bottom' if dest == 'life_bottom' else 'life_top'
                remove_character_from_field(owner, chosen, real_dest)
                chosen.life_face_up = step.get('face') == 'up'
                pools.remove((owner, chosen, is_opp))
                moved.append(chosen.name[:14])
            return f'campo -> Life do dono: {", ".join(moved)}' if moved else ''

        # ── Trava de ataque / trava de rest / trava de Blocker (persistente) ────
        # Mecanicas DISTINTAS apesar de compartilharem estrutura de
        # implementacao: lock_opp_character_attack impede ATACAR;
        # lock_opp_cannot_be_rested impede o character de ficar RESTED por
        # qualquer meio (atacar, bloquear, ou efeito); lock_opp_blocker_turn
        # impede especificamente de usar [Blocker] (Limejuice OP09-014, Kuzan
        # OP16-063) -- DISTINTA de lock_opp_blocker_battle (essa aqui e
        # persistente, escolhe 1 character especifico e dura alem desta
        # batalha; a outra e transitoria e trava o campo todo/filtrado so na
        # batalha que esta sendo resolvida agora). Nunca tratar como
        # sinonimos -- confirmado por Arthur.
        if action in ('lock_opp_character_attack', 'lock_opp_cannot_be_rested', 'lock_opp_blocker_turn'):
            count = step.get('count', 1)
            cost_lte = self._resolve_cost_lte(step, default=None)
            power_lte = step.get('power_lte')
            exclude = step.get('exclude', '').lower()
            DUR_MAP = {
                'until_opp_turn_end': 'opp_turn_end',
                'until_opp_end_phase': 'opp_end_phase',
                'until_my_next_turn_start': 'my_next_turn_start',
            }
            dur = DUR_MAP.get(step.get('duration', 'until_opp_turn_end'), 'opp_turn_end')

            candidates = [c for c in opp.field_chars
                          if (cost_lte is None or c.cost <= cost_lte)
                          and (power_lte is None or c.power <= power_lte)
                          and (action != 'lock_opp_blocker_turn' or c.is_blocker())
                          and (not exclude or exclude not in c.name.lower())]

            locked = []
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                if action == 'lock_opp_character_attack':
                    target.cannot_attack_until = dur
                elif action == 'lock_opp_cannot_be_rested':
                    target.cannot_be_rested_until = dur
                else:
                    target.cannot_block_until = dur
                remove_by_identity(candidates, target)
                locked.append(target.name[:15])
            verbo = {'lock_opp_character_attack': 'atacar',
                     'lock_opp_cannot_be_rested': 'ficar rested',
                     'lock_opp_blocker_turn': 'bloquear'}[action]
            return f'travou (não pode {verbo}): {", ".join(locked)}' if locked else ''

        # ── Trava de ataque condicional a pagamento ─────────────────────────────
        # DISTINTA de lock_opp_character_attack: aqui o character do oponente
        # PODE atacar, mas o oponente paga um custo (ex: trash N cards) a cada
        # ataque enquanto a trava estiver ativa. Implementado em 01/07/2026:
        # `attack_paywall` (campo novo em Card) guarda {'cost_type',
        # 'cost_amount'}; os pontos que filtram "pode atacar" (mesmos 6 que
        # checam cannot_attack_until) tambem checam
        # `can_afford_attack_paywall()`; o pagamento de verdade acontece em
        # `_resolve_attack` no momento de declarar o ataque (simplificacao
        # deliberada: paga sempre que pode, sem modelar "vale a pena" --
        # mesmo padrao que o resto do engine usa pra custos de ativacao).
        # Unica carta no banco: OP08-043 Edward.Newgate, count=99 = "select
        # ALL of your opponent's Characters on their field" (sem escolha).
        if action == 'lock_opp_attack_unless_pays':
            count = step.get('count', 99)
            cost_type = step.get('cost_type', 'trash_from_hand')
            cost_amount = step.get('cost_amount', 1)
            DUR_MAP = {
                'until_opp_turn_end': 'opp_turn_end',
                'until_opp_end_phase': 'opp_end_phase',
                'until_my_next_turn_start': 'my_next_turn_start',
            }
            dur = DUR_MAP.get(step.get('duration', 'until_opp_turn_end'), 'opp_turn_end')
            targets = list(opp.field_chars)[:count]
            for t in targets:
                t.attack_paywall = {'cost_type': cost_type, 'cost_amount': cost_amount, 'until': dur}
            names = ', '.join(t.name[:15] for t in targets)
            return f'travou (so ataca pagando {cost_amount} cartas): {names}' if names else ''

        # ── Trava de Refresh Phase (Freeze -- nao fica ativo no proximo
        # refresh) ───────────────────────────────────────────────────────────
        # lock_opp_character_refresh / lock_opp_don_refresh: trava o character
        # ou DON do OPONENTE de virar active na proxima Refresh Phase dele.
        # lock_self_character_refresh: trava o PROPRIO character (geralmente
        # custo de um efeito forte do jogador) -- alvo OPOSTO dos dois
        # anteriores, nunca tratar como sinonimo. refresh_phase consome
        # frozen_next_refresh/frozen_don_count (implementado 28/06/2026).
        if action == 'lock_opp_character_refresh':
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte')
            cost_eq = step.get('cost_eq')
            don_attached_gte = step.get('don_attached_gte')
            candidates = [c for c in opp.field_chars
                          if c.rested
                          and (cost_lte is None or c.cost <= cost_lte)
                          and (cost_eq is None or c.cost == cost_eq)
                          and (don_attached_gte is None or c.don_attached >= don_attached_gte)]
            locked = []
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                target.frozen_next_refresh = True
                remove_by_identity(candidates, target)
                locked.append(target.name[:15])
            return f'congelou (não desvira no próx. refresh): {", ".join(locked)}' if locked else ''

        if action == 'lock_opp_don_refresh':
            count = step.get('count', 1)
            opp.frozen_don_count += count
            return f'congelou até {count} DON do oponente (não desvira no próx. refresh)'

        if action == 'lock_self_character_refresh':
            if step.get('target') == 'this_card':
                card.frozen_next_refresh = True
                return f'{card.name[:15]} congelado (não desvira no próx. refresh)'
            # target == 'selected': alvo escolhido por um step ANTERIOR no
            # mesmo bloco (ex: EB02-021 "up to 1 Character gains +6000 power
            # ... THEN the selected Character will not become active") --
            # consome _last_selected (memoria de alvo entre steps,
            # implementado 28/06/2026 junto com buff_power
            # target='select_filtered'). Sem alvo memorizado, nao executa.
            alvo = self._last_selected
            if alvo is None:
                return ''
            alvo.frozen_next_refresh = True
            return f'{alvo.name[:15]} (selecionado antes) congelado (não desvira no próx. refresh)'

        # ── lock_opp_blocker_battle: trava o Blocker do oponente NESTA
        # batalha (quem está atacando agora) -- DISTINTA dos cannot_attack_*
        # acima e de lock_opp_character_refresh: aqui é transitória (só essa
        # batalha, _resolve_battle limpa logo depois) e afeta a ELEGIBILIDADE
        # de Blocker, não a capacidade de atacar. blockers_active() já lê
        # opp.blocker_lock_battle -- aqui só seta o filtro (ou None pra
        # campo todo) antes do block step rodar.
        if action == 'lock_opp_blocker_battle':
            lock = {}
            if step.get('power_lte') is not None: lock['power_lte'] = step['power_lte']
            if step.get('power_gte') is not None: lock['power_gte'] = step['power_gte']
            if step.get('cost_lte') is not None: lock['cost_lte'] = step['cost_lte']
            opp.blocker_lock_battle = lock
            filtro = ', '.join(f'{k}={v}' for k, v in lock.items()) or 'campo todo'
            return f'oponente nao pode usar Blocker nesta batalha ({filtro})'

        # ── Substituicao de power base (set_base_power) ─────────────────────────
        # Mecanica DISTINTA de buff_power/debuff_power: 'base power becomes N'
        # substitui o valor (ignora buffs aditivos anteriores aplicados sobre a
        # base), nao soma. `base_power_override` (campo em Card) e consumido
        # por `effective_card_power` em rules_facade.py -- JA implementado e
        # correto pra valor FIXO (target 'leader'/'self'/'own_character'/
        # 'leader_or_own_character', 8 cards, ex: OP15-092 Monkey.D.Luffy,
        # EB04-003/004). `source` (achado 28/06/2026, MatchLeaderToBasePower)
        # cobre o caso DINAMICO -- "becomes the same as [outra carta]",
        # sem numero literal no banco -- 12 cartas a mais.
        if action == 'set_base_power':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_effective_power,
            )
            amount = step.get('amount')
            source = step.get('source')
            if source:
                # MatchLeaderToBasePower (achado 28/06/2026, 12 cartas
                # reais): valor DINAMICO, calculado do estado atual em vez
                # de um amount fixo do banco. Sempre target='self' (a
                # propria carta do efeito, unico caso confirmado).
                if source == 'opp_leader':
                    amount = opp.leader.effective_power(False)
                elif source == 'own_leader':
                    amount = me.leader.effective_power(True)
                elif source == 'selected_opp_character':
                    from optcg_engine.rules_facade import (
                        eligible_cards,
                        choose_highest_effective_power,
                    )
                    candidatos = eligible_cards(opp.field_chars)
                    if not candidatos:
                        return ''
                    alvo = choose_highest_effective_power(candidatos,
                                                          your_turn=False)
                    amount = alvo.effective_power(False)
                else:
                    return None
                card.base_power_override = int(amount)
                return f'base power de {card.name[:15]} virou {amount} ({source})'
            if amount is None:
                return None

            target = step.get('target', 'self')
            filter_type = step.get('filter_type') or ''

            if target == 'self':
                candidates = [card] if card_matches_filter(card, filter_type) else []
            elif target == 'leader':
                candidates = [me.leader] if card_matches_filter(me.leader, filter_type) else []
            elif target == 'own_character':
                candidates = [c for c in me.field_chars
                              if card_matches_filter(c, filter_type)]
            elif target in ('leader_or_own_character', 'leader_or_character'):
                candidates = [c for c in [me.leader] + me.field_chars
                              if card_matches_filter(c, filter_type)]
            elif target == 'opp_character':
                # "Set the power of up to N of your opponent's Characters to X"
                # (Ain OP07-002). Escolhe o mais valioso -- beneficia mais
                # zerando o Character que ameaca mais.
                count = step.get('count', 1)
                candidates = sorted(
                    [c for c in opp.field_chars if card_matches_filter(c, filter_type)],
                    key=lambda c: -c.board_value()
                )[:count]
                for c in candidates:
                    c.base_power_override = int(amount)
                return f'power de {", ".join(c.name[:12] for c in candidates)} virou {amount}'
            else:
                candidates = []

            if not candidates:
                return None

            chosen = choose_highest_effective_power(candidates, your_turn=True)
            chosen.base_power_override = int(amount)
            return f'base power de {chosen.name[:15]} virou {amount}'

        # ── Self-lock de ataque (incondicional / condicional / em massa) ────────
        # Achado 01/07/2026: este comentario estava DESATUALIZADO -- a trava
        # ja e aplicada de verdade, so que por um caminho diferente deste
        # branch. `is_attack_locked_self()` (definida no topo do arquivo) le
        # `effects['passive']['steps']` DIRETO de `get_card_effects()` (sem
        # depender de nenhum estado setado aqui) e ja e chamada nos 5+
        # pontos que filtram "pode atacar" (my_attack_power, geracao de
        # acoes de ataque, Turn Planner). Esses steps TAMBEM passam por aqui
        # via `apply_your_turn_buffs()` (que executa TODO step de 'passive',
        # nao so buffs) -- mas como a trava real ja acontece em
        # is_attack_locked_self(), este branch e so um no-op silencioso
        # (evita logar a mensagem antiga de "nao implementado" toda vez que
        # uma dessas 6 cartas tem o turno passado em revista). Cartas
        # cobertas: cannot_attack_self (3: OP06-083, OP11-058, OP14-056,
        # mais P-084 que tambem usa esta action pra si mesmo), unless (2:
        # EB04-005, EB04-051), mass-lock condicional (1: P-084, via
        # `mass_lock_conditional` separado, nao por este branch).
        if action in ('cannot_attack_self', 'cannot_attack_self_unless', 'cannot_attack_own_characters_by_cost'):
            return ''

        # ── Power buff ────────────────────────────────────────────────────────
        if action == 'buff_power':
            amount = step.get('amount', 0)
            target = step.get('target', 'self')
            duration = step.get('duration', 'this_turn')

            if target == 'self':
                card.power_buff += amount
            elif target == 'leader':
                # "Up to 1 of your Leader with N power or less gains +X
                # power" (achado 16/07, OP09-007) -- power_lte filtra se o
                # buff se aplica, checado contra o power EFETIVO atual do
                # Leader (base + buffs ja acumulados), nao so o base.
                power_lte = step.get('power_lte')
                if power_lte is not None and me.leader.effective_power(True) > power_lte:
                    return ''
                me.leader.power_buff += amount
            elif target == 'leader_or_character':
                # IA escolhe o mais forte
                best = max(me.field_chars + [me.leader],
                           key=lambda c: c.effective_power(True)) if me.field_chars else me.leader
                best.power_buff += amount
            elif target in ('all_allies', 'all_allies_and_leader'):
                # filter_type: "all of your [Tipo] type Characters gain +N
                # power" (achado 16/07, OP12-102/ST05-001) -- sem isso o
                # buff aplicava em TODO character do campo, ignorando o
                # filtro de tipo do texto.
                from optcg_engine.rules_facade import card_matches_filter
                filter_type = step.get('filter_type', '')
                alvos = ([c for c in me.field_chars if card_matches_filter(c, filter_type)]
                         if filter_type else list(me.field_chars))
                cost_lte = step.get('cost_lte')
                if cost_lte is not None:
                    alvos = [c for c in alvos if c.cost <= cost_lte]
                cost_gte = step.get('cost_gte')
                if cost_gte is not None:
                    alvos = [c for c in alvos if c.cost >= cost_gte]
                filter_color = step.get('filter_color', '')
                if filter_color:
                    alvos = [c for c in alvos if filter_color.lower() in c.color.lower()]
                if step.get('exclude_self'):
                    alvos = [c for c in alvos if c is not card]
                for c in alvos:
                    c.power_buff += amount
                if target == 'all_allies_and_leader':
                    me.leader.power_buff += amount
            elif target == 'select_filtered':
                # "Select up to N of your [Tipo] Leader/Character cards and
                # that card gains +X power" (OP07-057, EB02-021) -- alvo NAO
                # e a propria carta do efeito, e sim escolhido por filtro de
                # tipo/categoria entre Leader+Characters. Guarda em
                # _last_selected para um step POSTERIOR no mesmo bloco poder
                # referenciar "the selected card" (lock_self_character_refresh
                # / select_grant_unblockable_turn com target='selected').
                from optcg_engine.rules_facade import (
                    card_matches_filter,
                    choose_highest_board_value,
                )
                filter_type = step.get('filter_type', '')
                candidatos = [c for c in me.field_chars + [me.leader]
                              if card_matches_filter(c, filter_type)]
                if candidatos:
                    alvo = choose_highest_board_value(candidatos)
                    alvo.power_buff += amount
                    self._last_selected = alvo
                    return f'{alvo.name[:18]} selecionado, +{amount} power'
                return ''
            elif target == 'own_character':
                # "Up to N of your Characters [with X power or less] [other
                # than [Nome]] gains +Y power" -- selecao entre os PROPRIOS
                # characters SEM filtro de tipo (distinto de
                # 'select_filtered'). Achado 28/06/2026: este target ja era
                # gerado pelo parser (15 cartas reais) mas nunca era
                # consumido aqui -- caia no fallback abaixo sem aplicar
                # nada (no-op silencioso).
                from optcg_engine.rules_facade import (
                    eligible_cards,
                    choose_highest_board_value,
                )
                candidatos = eligible_cards(
                    me.field_chars,
                    power_lte=step.get('power_lte'),
                    exclude_name=step.get('exclude', ''),
                )
                # "Up to N of your Characters gain +X power" -- N>1
                # (achado 16/07, OP08-018): antes escolhia SEMPRE so 1,
                # mesmo com N=3 no texto.
                count_own = step.get('count', 1)
                alvos = []
                for _ in range(count_own):
                    if not candidatos:
                        break
                    alvo = choose_highest_board_value(candidatos)
                    remove_by_identity(candidatos, alvo)
                    alvo.power_buff += amount
                    alvos.append(alvo.name[:15])
                return f'+{amount} power em: {", ".join(alvos)}' if alvos else ''
            return f'+{amount} power em {target}'

        if action == 'debuff_power':
            # Espelha buff_power, mas do lado do oponente -- achado 30/06/2026:
            # a action ja era reconhecida em viabilidade (_step_is_viable) e em
            # heuristicas de score, mas nunca tinha handler de execucao aqui,
            # virando no-op silencioso em 142 steps reais no banco (on_play,
            # when_attacking, main, activate_main, counter, trigger, etc).
            # O parser (gerar_effects_db.py) nunca emite filtro/count pra estes
            # alvos -- sempre 1 alvo escolhido pela IA (o mais valioso do
            # oponente), exceto 'all_opp_characters' que afeta o campo inteiro.
            from optcg_engine.rules_facade import choose_highest_board_value

            amount = step.get('amount', 0)
            target = step.get('target', 'opp_character')

            if target == 'opp_leader':
                opp.leader.power_buff -= amount
                return f'Leader do oponente -{amount} power'
            if target == 'all_opp_characters':
                if not opp.field_chars:
                    return ''
                if step.get('per_don_attached'):
                    # "-N power for every DON!! card given to that
                    # Character" (achado 15/07, OP15-008 Krieg): escala
                    # POR ALVO, multiplicando pelo don_attached de CADA
                    # character, nao um -N fixo pra todos.
                    afetados = []
                    for c in opp.field_chars:
                        n_don = getattr(c, 'don_attached', 0)
                        if n_don <= 0:
                            continue
                        c.power_buff -= amount * n_don
                        afetados.append(f'{c.name[:12]}(-{amount * n_don})')
                    return f'debuff por DON anexado: {", ".join(afetados)}' if afetados else ''
                for c in opp.field_chars:
                    c.power_buff -= amount
                return f'-{amount} power em todos os Characters do oponente'
            if target == 'opp_leader_or_character':
                # duration='this_turn': só tem efeito em algo que ainda pode
                # agir neste turno -- achado em partida real 07/07: Van Augur
                # (on-KO, opp_turn_only) debuffou -3000 no St. Marcus Mars
                # bem depois dele já ter atacado e resolvido o combate (já
                # restado) -- board_value puro escolhia o "maior" personagem
                # sem checar se ele ainda ia agir, jogando o debuff fora.
                # Prioriza ativo (char não-restado ou líder não-restado);
                # só cai pra qualquer um se não sobrar nenhuma opção ativa
                # (debuff sem efeito nenhum é melhor que travar a execução).
                ativos = [c for c in opp.field_chars if not c.rested]
                if not getattr(opp.leader, 'rested', False):
                    ativos.append(opp.leader)
                candidatos = ativos or (list(opp.field_chars) + [opp.leader])
                alvo = choose_highest_board_value(candidatos)
                alvo.power_buff -= amount
                return f'{alvo.name[:18]} -{amount} power'
            if target == 'opp_character':
                if not opp.field_chars:
                    return ''
                ativos = [c for c in opp.field_chars if not c.rested]
                candidatos = list(ativos or opp.field_chars)
                # "up to N" com N>1 (achado 15/07, ex: OP01-022/OP11-020,
                # 13 cartas reais): antes so debuffava 1 alvo sempre, mesmo
                # quando o texto pedia 2. count>1 agora repete a escolha do
                # melhor alvo restante ate N ou os candidatos acabarem.
                count = step.get('count', 1)
                alvos = []
                for _ in range(min(count, len(candidatos))):
                    alvo = choose_highest_board_value(candidatos)
                    alvo.power_buff -= amount
                    remove_by_identity(candidatos, alvo)
                    alvos.append(alvo.name[:15])
                return f'-{amount} power em: {", ".join(alvos)}' if alvos else ''
            return ''

        if action == 'negate_effect':
            # "Negate the effect of up to N of your opponent's Leader/
            # Character(s)" (OP09-093, OP09-097, OP09-098, OP16-115, etc):
            # marca effects_negated_until no(s) alvo(s) -- checado no topo
            # de execute() (bloqueia qualquer trigger FUTURO da carta
            # enquanto ativo). Achado real 09/07: a action ja aparecia em 4
            # cartas parseadas mas nunca tinha handler de execucao (virava
            # no-op silencioso), mesmo padrao do achado do debuff_power
            # (30/06) documentado acima.
            from optcg_engine.rules_facade import choose_highest_board_value

            target = step.get('target', 'opp_character')
            DUR_MAP = {
                'until_opp_turn_end': 'opp_turn_end',
                'until_opp_end_phase': 'opp_end_phase',
                'until_my_next_turn_start': 'my_next_turn_start',
            }
            dur = DUR_MAP.get(step.get('duration', 'this_turn'), 'opp_turn_end')
            cost_lte = self._resolve_cost_lte(step, default=None)

            def _negar_character():
                candidatos = eligible_cards(opp.field_chars, cost_lte=cost_lte)
                if not candidatos:
                    return None
                alvo = choose_highest_board_value(candidatos)
                alvo.effects_negated_until = dur
                return alvo

            if target == 'opp_leader':
                opp.leader.effects_negated_until = dur
                return f'negou o efeito do lider {opp.leader.name[:18]}'
            if target == 'opp_leader_or_character':
                # escolhe o mais ameacador entre lider e o melhor character
                # (mesma ideia do debuff_power opp_leader_or_character:
                # so vale negar quem ainda vai agir/importar)
                melhor_char = choose_highest_board_value(opp.field_chars) if opp.field_chars else None
                if melhor_char is None or opp.leader.board_value() >= melhor_char.board_value():
                    opp.leader.effects_negated_until = dur
                    return f'negou o efeito do lider {opp.leader.name[:18]}'
                melhor_char.effects_negated_until = dur
                return f'negou o efeito de {melhor_char.name[:18]}'
            alvo = _negar_character()
            if alvo is not None:
                # Grava pra um step POSTERIOR no mesmo bloco poder alvejar
                # "that Character" (ex: OP09-098 Black Hole, "negate the
                # effect... Then, if that Character has a cost of 4 or
                # less, K.O. it" -- achado 15/07). Mesma memoria ja usada
                # por play_from_deck/buff_power target='selected'.
                self._last_selected = alvo
            return f'negou o efeito de {alvo.name[:18]}' if alvo else ''

        if action == 'buff_power_per_count':
            source = step.get('source', 'trash')
            count_per = max(1, int(step.get('count_per', 1) or 1))
            amount_per = int(step.get('amount_per', 1000) or 0)
            target = step.get('target', 'self')

            if source == 'events_in_trash':
                n = sum(1 for c in me.trash if c.card_type == 'EVENT')
            elif source == 'trash':
                n = len(me.trash)
            elif source == 'rested_don':
                n = me.don_rested
            elif source == 'hand':
                n = len(me.hand)
            elif source == 'unique_character_names':
                n = len({c.name for c in me.field_chars})
            elif source == 'own_characters':
                n = len(me.field_chars)
            else:
                n = 0

            amount = (n // count_per) * amount_per
            if amount <= 0:
                return ''

            if target == 'self':
                card.power_buff += amount
            elif target == 'leader':
                me.leader.power_buff += amount
            elif target == 'leader_or_character':
                best = max(me.field_chars + [me.leader],
                           key=lambda c: c.effective_power(True)) if me.field_chars else me.leader
                best.power_buff += amount
            elif target in ('all_allies', 'all_allies_and_leader'):
                for c in me.field_chars:
                    c.power_buff += amount
                if target == 'all_allies_and_leader':
                    me.leader.power_buff += amount
            return f'+{amount} power em {target} ({n}/{count_per} {source})'

        if action == 'buff_cost_per_count':
            # "gains [Blocker] and +N cost for every M cards in your
            # trash" (achado 16/07, ST27-004) -- mesma semantica de
            # buff_power_per_count, so que muta cost_buff em vez de
            # power_buff. amount_per pode ser NEGATIVO (achado 16/07,
            # EB04-048: "+1000 power and -2 cost for every 5 cards in
            # your trash" -- reducao de custo, nao aumento).
            source = step.get('source', 'trash')
            count_per = max(1, int(step.get('count_per', 1) or 1))
            amount_per = int(step.get('amount_per', 1) or 0)
            target = step.get('target', 'self')

            n = len(me.trash) if source == 'trash' else 0
            amount = (n // count_per) * amount_per
            if amount == 0:
                return ''

            if target == 'self':
                card.cost_buff += amount
            else:
                for c in me.field_chars:
                    c.cost_buff += amount
            sinal = '+' if amount >= 0 else ''
            return f'{sinal}{amount} cost em {target} ({n}/{count_per} {source})'

        # ── Cost buff/debuff (buff_cost / debuff_cost) ──────────────────────────
        # NOTA DE LIMITACAO: assim como buff_power, o sistema geral de turnos
        # ainda nao distingue 'until_opp_turn_end' de 'this_turn' -- ambos sao
        # resetados no mesmo ciclo (apply_your_turn_buffs/reset_your_turn_buffs).
        # duration='permanent' (ex: condicionado a leader_type, sem prazo) usa
        # cost_buff_permanent, que nunca e resetado por esses dois pontos.
        if action in ('buff_cost', 'debuff_cost'):
            from optcg_engine.rules_facade import eligible_cards

            amount = step.get('amount', 0)
            if action == 'debuff_cost':
                amount = -amount
            target = step.get('target', 'self')
            duration = step.get('duration', 'this_turn')
            count = step.get('count', 1)
            filter_name = step.get('filter_name', '').lower()
            cost_gte = step.get('cost_gte')

            if target == 'own_play_hand':
                if duration == 'next_play_only':
                    me.pending_play_cost_reductions.append({
                        k: step[k] for k in
                        ('amount', 'filter_type', 'filter_name', 'cost_gte')
                        if k in step
                    })
                    return f'proxima carta elegivel custa -{amount}'
                # Auras de Stage sao lidas diretamente por
                # effective_hand_play_cost; nao mutam cartas na mao.
                return f'aura de custo -{amount} para cartas elegiveis'

            campo_alvo = me if target in ('self', 'own_character') else opp
            if target == 'self':
                candidatos = [card]
            else:
                candidatos = eligible_cards(
                    campo_alvo.field_chars,
                    cost_lte=step.get('cost_lte'),
                    power_lte=step.get('power_lte'),
                    filter_text=step.get('filter_type', ''),
                    color=step.get('color', ''),
                )
                if filter_name:
                    # Filtro por NOME PROPRIO (ex: Shinobu OP16-087, "up to 1
                    # of your [Kouzuki Momonosuke] gains +20 cost") -- DISTINTO
                    # de filter_type: aqui o alvo e 1 personagem especifico
                    # por nome, nao uma familia/tipo inteira. Achado 27/06:
                    # o parser confundia com filter_type antes da correcao.
                    candidatos = [c for c in candidatos if filter_name in c.name.lower()]
                if cost_gte is not None:
                    candidatos = [c for c in candidatos if c.cost >= cost_gte]
                # filter_no_effect: Characters sem efeito parseado no banco
                # ("with no base effect", OP03-091 Helmeppo).
                if step.get('filter_no_effect'):
                    candidatos = [c for c in candidatos
                                  if not get_card_effects(c.code).get('effects')]

            to_value = step.get('to_value')  # "set cost to N" (OP03-091)
            afetados = []
            for c in candidatos[:count]:
                if to_value is not None:
                    real_amount = -(c.effective_cost() - to_value)
                else:
                    real_amount = amount
                if duration == 'permanent':
                    c.cost_buff_permanent += real_amount
                else:
                    c.cost_buff += real_amount
                afetados.append(c.name[:15])
            sinal = '+' if amount >= 0 else ''
            return f'{sinal}{amount} cost em {", ".join(afetados)}' if afetados else ''

        # ── Give DON ──────────────────────────────────────────────────────────
        if action == 'give_don':
            count = step.get('count', 1)
            rested = step.get('rested', False)
            # Dá DON ao personagem mais forte ativo
            targets = [c for c in me.field_chars if not c.rested] + [me.leader]
            transferido = 0
            if targets:
                best = max(targets, key=lambda c: c.effective_power(True))
                # "up to N" e um TETO que o jogador escolhe (0..N), nao uma
                # ordem fixa de sempre dar N -- achado 15/07 (usuario): o
                # motor sempre tentava dar o maximo do texto, mesmo quando
                # o personagem ja teria poder suficiente pra passar pelo
                # lider do oponente sem DON nenhum, desperdicando DON que
                # ficaria melhor reservado pra defesa. So se aplica ao
                # alvo PROPRIO (give_don) -- give_don_opp tem objetivo
                # oposto (sobrecarregar o oponente), la o maximo continua
                # sendo a jogada certa. Formula = mesmo deficit BASE de
                # don_needed_for_attack (secao 1, obrigatoria), sem a
                # margem de counter (exige contexto de ataque declarado,
                # que ainda nao existe neste ponto do efeito -- On Play/
                # Activate Main roda antes da fase de ataque).
                deficit = opp.leader.power - attack_time_power(best, opp)
                necessario = (deficit + 999) // 1000 if deficit > 0 else 0
                count = min(count, necessario)
                # Debita do banco de DON real (don_rested + don_available),
                # nunca de uma fonte gratuita externa -- ambos os tipos vêm
                # do mesmo banco do jogador. Achado 15/07 via
                # audit_parser_coverage.py (ST01-011 Brook): o comentario
                # ja dizia "a IA nao inventa DON", mas o codigo anexava
                # `count` cheio no character ANTES de saber quanto o banco
                # realmente tinha pra debitar -- se o banco tivesse MENOS
                # que `count`, o personagem recebia o valor cheio mesmo
                # assim (DON criado do nada, banco e campo dessincronizam).
                # Fix: anexa exatamente o que foi de fato debitado do banco.
                if rested:
                    # "give up to N RESTED DON" -- exige especificamente DON
                    # rested do banco. Se não houver o suficiente, usa o que
                    # tiver (parcial) -- a IA não inventa DON.
                    do_rested = min(count, me.don_rested)
                    me.don_rested -= do_rested
                    transferido = do_rested
                else:
                    # "give up to N DON" (sem qualificador) -- a IA escolhe.
                    # Prioriza DON rested primeiro (preserva don_available
                    # ativo para outras jogadas no mesmo turno); se não
                    # houver rested suficiente, completa com don_available.
                    do_rested = min(count, me.don_rested)
                    me.don_rested -= do_rested
                    restante = count - do_rested
                    do_available = min(restante, me.don_available) if restante > 0 else 0
                    me.don_available -= do_available
                    transferido = do_rested + do_available
                best.don_attached += transferido
            return f'+{transferido} DON'

        # ── Give DON ao oponente (controle/setup) ───────────────────────────────
        # Mecanica distinta de give_don: o DON sai do BANCO DO OPONENTE (nao do
        # meu), e e anexado a um Character do OPONENTE. Geralmente usado para
        # travar o refresh dele depois (ex: combinado com lock_opp_don /
        # lock_opp_character_refresh), nao para dar vantagem ao oponente.
        if action == 'give_don_opp':
            count = step.get('count', 1)
            rested = step.get('rested', False)

            targets_opp = [c for c in opp.field_chars] + [opp.leader]
            transferido = 0
            if targets_opp:
                best = max(targets_opp, key=lambda c: c.effective_power(True))
                # Mesmo fix do give_don (15/07, achado via ST01-011 Brook):
                # anexa so o que foi de fato debitado do banco do oponente,
                # nunca o `count` cheio se o banco tiver menos que isso.
                if rested:
                    do_rested = min(count, opp.don_rested)
                    opp.don_rested -= do_rested
                    transferido = do_rested
                else:
                    # sem qualificador / "from cost area" -- usa o banco
                    # ativo do oponente primeiro (e o DON que ele "gastou"
                    # no turno, fica no cost area), completando com rested
                    # se nao houver ativo suficiente.
                    do_available = min(count, opp.don_available)
                    opp.don_available -= do_available
                    restante = count - do_available
                    do_rested = min(restante, opp.don_rested) if restante > 0 else 0
                    opp.don_rested -= do_rested
                    transferido = do_available + do_rested
                best.don_attached += transferido
            return f'deu {transferido} DON ao character do oponente'

        # ── Play from trash ───────────────────────────────────────────────────
        if action == 'play_from_trash':
            from optcg_engine.rules_facade import eligible_cards

            filter_type = step.get('filter_type', '').lower()
            filter_name = step.get('filter_name', '').lower()
            cost_lte = self._resolve_cost_lte(step, default=None)
            cost_eq = step.get('cost_eq')
            power_eq = step.get('power_eq')
            power_lte = step.get('power_lte')
            power_gte = step.get('power_gte')
            count = step.get('count', 1)
            enters_rested = step.get('rested', False)
            distinct_names = step.get('distinct_names', False)

            # filter_self: recupera a SI MESMO do trash (ex: substituicao de
            # remocao por auto-K.O. seguida de replay). Nao usa o pool geral
            # de candidatos, e sim a propria carta que acabou de ir ao trash.
            if step.get('filter_self'):
                self_card = next((c for c in me.trash if c.code == card.code), None)
                if self_card:
                    remove_by_identity(me.trash, self_card)
                    self_card.rested = enters_rested
                    if self_card.card_type == 'STAGE':
                        if me.field_stage:
                            me.trash.append(me.field_stage)
                        me.field_stage = self_card
                    else:
                        me.field_chars.append(self_card)
                        apply_conditional_keyword_passives(me, opp)
                        self_card.just_played = not (self_card.has_rush or self_card.rush_this_turn or self_card.is_rush_character())
                        self_card.rush_character_only_this_turn = self_card.is_rush_character() and not self_card.is_rush()
                    return f'jogou do trash (self): {self_card.name[:15]}'
                return ''

            candidates = eligible_cards(
                me.trash,
                cost_lte=cost_lte,
                cost_eq=cost_eq,
                power_eq=power_eq,
                power_lte=power_lte,
                power_gte=power_gte,
                has_trigger=step.get('has_trigger', False),
                filter_text=filter_type,
                name_or_code=filter_name,
                exclude_name=step.get('exclude', ''),
            )
            if step.get('same_name_as_trashed'):
                nomes = set(getattr(self, '_last_trashed_names', []) or [])
                candidates = [c for c in candidates if c.name in nomes]

            played = []
            played_names_lower = set()
            for _ in range(min(count, len(candidates))):
                pool = candidates
                if distinct_names:
                    pool = [c for c in candidates if c.name.lower() not in played_names_lower]
                if not pool:
                    break
                if any(c.card_type == 'STAGE' for c in pool):
                    best = max((c for c in pool if c.card_type == 'STAGE'), key=lambda x: x.cost)
                else:
                    best = max(pool, key=lambda x: x.board_value())

                remove_by_identity(me.trash, best)
                best.rested = enters_rested
                if best.card_type == 'STAGE':
                    if me.field_stage:
                        me.trash.append(me.field_stage)
                    me.field_stage = best
                else:
                    if len(me.field_chars) >= 5:
                        worst = min(me.field_chars, key=lambda x: x.board_value())
                        remove_character_from_field(me, worst, 'trash')
                    me.field_chars.append(best)
                    apply_conditional_keyword_passives(me, opp)
                    best.just_played = not (best.has_rush or best.rush_this_turn or best.is_rush_character())
                    best.rush_character_only_this_turn = best.is_rush_character() and not best.is_rush()

                played.append(best.name[:15])
                played_names_lower.add(best.name.lower())
                remove_by_identity(candidates, best)

            return f'jogou do trash: {", ".join(played)}' if played else ''

        # ── Play from deck ────────────────────────────────────────────────────
        if action == 'play_from_deck':
            from optcg_engine.rules_facade import eligible_cards

            filter_type = step.get('filter_type', '').lower()
            cost_lte = self._resolve_cost_lte(step, default=99)
            color = step.get('color', '')
            count = step.get('count', 1)

            # Se precedido de 'look_top_deck' (padrao "look at N cards from
            # the top of your deck; play up to 1 [filtro]"), restringe a
            # busca as N cartas do topo, igual a add_to_hand -- sem isto, a
            # IA "veria" o deck inteiro para escolher a melhor carta, o que
            # nao e a regra real (so as N cartas reveladas pelo look estao
            # disponiveis) e tambem nao embaralharia o deck no final (regra
            # de "look E play" deixa o resto no topo/fundo conforme o texto,
            # nao embaralha -- distinto do "play a card from anywhere in
            # your deck", que de fato revela o deck inteiro e embaralha).
            effects = get_card_effects(card.code)
            look_count = None
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count')
                        break
                if look_count:
                    break

            if look_count:
                look = min(look_count, len(me.deck))
                pool = me.deck[-look:]
            else:
                pool = me.deck

            candidates = eligible_cards(
                list(pool),
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                filter_text=filter_type,
                name_or_code=step.get('filter_name', ''),
                color=color,
            )

            played = []
            for _ in range(min(count, len(candidates))):
                best = max(candidates, key=lambda x: x.board_value())
                remove_by_identity(me.deck, best)
                if len(me.field_chars) >= 5:
                    worst = min(me.field_chars, key=lambda x: x.board_value())
                    remove_character_from_field(me, worst, 'trash')
                me.field_chars.append(best)
                apply_conditional_keyword_passives(me, opp)
                best.just_played = not (best.has_rush or best.rush_this_turn or best.is_rush_character())
                best.rush_character_only_this_turn = best.is_rush_character() and not best.is_rush()
                remove_by_identity(candidates, best)
                played.append(best.name[:15])
                # Grava pra um step POSTERIOR no mesmo bloco poder alvejar
                # "that Character" (ex: OP12-058 Whitebeard, "gains [Rush]"
                # apos jogar do deck) -- mesma memoria ja usada por
                # buff_power/lock_self_character_refresh target='selected'.
                self._last_selected = best

            if not look_count:
                # so embaralha quando a busca expos o deck inteiro -- o
                # padrao "look at N; play" deixa o resto das N cartas vistas
                # para o step seguinte (trash_rest/deck_bottom_rest/etc)
                # tratar, sem tocar no resto do deck.
                random.shuffle(me.deck)
            return f'jogou do deck: {", ".join(played)}' if played else ''

        # ── Trash from hand ───────────────────────────────────────────────────
        if action == 'trash_from_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(me.hand))):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    remove_by_identity(me.hand, worst)
                    me.trash.append(worst)
                    trashed.append(worst.name[:12])
            return f'descartou da mão: {", ".join(trashed)}' if trashed else ''

        # ── Trash from hand FORCADO no oponente (disrupcao de mao) ──────────────
        # Distinto de trash_from_hand: alvo e a mao do OPONENTE, nao a minha.
        # E um efeito DETERMINISTICO (sempre acontece, sem "se o oponente
        # quiser") -- a unica decisao real e QUAL carta ele descarta, e isso
        # reaproveita a mesma heuristica de _choose_to_trash (menor valor de
        # board) aplicada na mao dele. Simplificacao assumida: nao modela
        # blefe/retencao estrategica do oponente, so "descarta o que tem
        # menos valor para o lado que esta descartando" -- aproximacao
        # razoavel e nao tendenciosa para nenhum dos lados, mas e uma
        # simplificacao real, nao a decisao otima do oponente.
        if action == 'opp_trash_from_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(opp.hand))):
                # "your opponent trashes" = o dono da mao escolhe e
                # preserva suas melhores cartas. Ja "trash ... from your
                # opponent's hand" = controlador do efeito escolhe cartas
                # face-down (Q&A OP03-078), logo a escolha e cega/aleatoria.
                chosen = (random.choice(opp.hand)
                          if step.get('chosen_by') == 'effect_owner_blind'
                          else self._choose_to_trash(opp.hand))
                if chosen:
                    remove_by_identity(opp.hand, chosen)
                    opp.trash.append(chosen)
                    trashed.append(chosen.name[:12])
            return f'oponente descartou: {", ".join(trashed)}' if trashed else ''

        # ── Mesma familia: forca o OPONENTE a mover 1 dos PROPRIOS
        # characters dele (ele escolheria; aproximamos pelo pior por
        # board_value, mesmo criterio de toda escolha "sacrifique o pior"
        # já usada no engine). DISTINTO de bounce/
        # place_opp_character_bottom_deck (onde EU escolho o MELHOR do
        # oponente pra remover). Achado por foto real 27/06 (Tsuru
        # OP06-051, Luffy P-055).
        if action == 'opp_choose_trash_our_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(me.hand))):
                chosen = max(me.hand, key=lambda c: c.board_value())
                remove_by_identity(me.hand, chosen)
                me.trash.append(chosen)
                trashed.append(chosen.name[:12])
            return f'oponente escolheu descartar: {", ".join(trashed)}' if trashed else ''

        if action == 'opp_bounce_own_character':
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte')
            active_only = step.get('active_only', False)
            rested_only = step.get('rested_only', False)
            candidates = [
                c for c in opp.field_chars
                if (cost_lte is None or c.cost <= cost_lte)
                and (not active_only or not c.rested)
                and (not rested_only or c.rested)
            ]
            bounced = []
            for _ in range(min(count, len(candidates))):
                worst = min(candidates, key=lambda c: c.board_value())
                remove_character_from_field(opp, worst, 'hand')
                remove_by_identity(candidates, worst)
                bounced.append(worst.name[:12])
            return f'oponente devolveu pra mão: {", ".join(bounced)}' if bounced else ''

        if action == 'opp_place_own_character_bottom_deck':
            count = step.get('count', 1)
            placed = []
            for _ in range(min(count, len(opp.field_chars))):
                worst = min(opp.field_chars, key=lambda c: c.board_value())
                remove_character_from_field(opp, worst, 'deck_bottom')
                placed.append(worst.name[:12])
            return f'oponente colocou no fundo do deck: {", ".join(placed)}' if placed else ''

        # ── Mesma familia (forca o OPONENTE), mas a fonte e a MAO dele, nao
        # o campo -- destino e o FUNDO DO PROPRIO DECK do oponente (NUNCA
        # trash, distinto de opp_trash_from_hand). Reusa _choose_to_trash
        # (mesma heuristica de "descarta o pior" ja usada pra mao do
        # oponente) so pra escolher QUAL carta, ja que o destino e
        # diferente. Achado 02/07/2026 (EB03-026, EB04-022, EB04-025,
        # OP06-044, OP07-047, OP08-046, OP15-048, P-048, OP16-047).
        # ── hand_to_deck: coloca N cartas da PRÓPRIA mão de volta no deck
        # ("top or bottom... in any order" -- escolha estética do jogador,
        # sem efeito mecânico relevante; modela como fundo do deck, mesma
        # convenção de opp_place_hand_bottom_deck). Achado 15/07: clausula
        # "loot" (draw N, devolve M) que seguia um 'draw' ficava ausente
        # do parseado inteira (OP07-053, OP08-050, OP11-054 Nami).
        if action == 'hand_to_deck':
            count = step.get('count', 1)
            placed = []
            for _ in range(min(count, len(me.hand))):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    remove_by_identity(me.hand, worst)
                    me.deck.insert(0, worst)
                    placed.append(worst.name[:12])
            return f'colocou da mão no deck: {", ".join(placed)}' if placed else ''

        if action == 'opp_place_hand_bottom_deck':
            count = step.get('count', 1)
            placed = []
            for _ in range(min(count, len(opp.hand))):
                worst = self._choose_to_trash(opp.hand)
                if worst:
                    remove_by_identity(opp.hand, worst)
                    opp.deck.insert(0, worst)
                    placed.append(worst.name[:12])
            return f'oponente colocou da mão no fundo do deck: {", ".join(placed)}' if placed else ''

        # ── Mesma familia, fonte = TRASH do oponente. filter_type='event'
        # restringe a Event cards (OP11-091). Achado 02/07/2026 (OP05-079,
        # OP06-092, OP11-072, OP11-091).
        if action == 'opp_place_trash_bottom_deck':
            count = step.get('count', 1)
            filter_type = step.get('filter_type')
            candidates = list(opp.trash)
            if filter_type == 'event':
                candidates = [c for c in candidates if c.card_type.lower() == 'event']
            placed = []
            for _ in range(min(count, len(candidates))):
                worst = min(candidates, key=lambda c: c.board_value())
                remove_by_identity(opp.trash, worst)
                remove_by_identity(candidates, worst)
                opp.deck.insert(0, worst)
                placed.append(worst.name[:12])
            return f'oponente colocou do trash no fundo do deck: {", ".join(placed)}' if placed else ''

        # ── AUTO-RESTRIÇÃO: "Then, you cannot play ... this turn" ─────────────
        # Combo de ramp (set DON active) que cobra: você perde o direito de jogar.
        # Resetado no início do próprio turno (refresh).
        if action == 'self_cant_play':
            scope = step.get('scope', 'chars')   # 'hand' | 'chars'
            if scope == 'hand':
                me.cant_play_from_hand_this_turn = True
            else:
                me.cant_play_chars_this_turn = True
                gte = step.get('cost_gte', 0)
                if gte:
                    me.cant_play_cost_gte = gte
            return 'auto-restrição: não pode jogar mais este turno'

        # ── SHUFFLE/CYCLE mão no deck (+ recompra) = redesenhar a mão ─────────
        if action == 'shuffle_hand_into_deck':
            import random as _rnd
            n = len(me.hand)
            if n == 0:
                return ''
            dest = step.get('dest', 'deck')
            # move toda a mão para o deck
            cards = list(me.hand)
            me.hand.clear()
            if dest == 'deck_bottom':
                for c in cards:
                    me.deck.insert(0, c)        # fundo = início da lista
            else:
                me.deck.extend(cards)
                _rnd.shuffle(me.deck)
            # recompra N (= nº devolvido), do topo (= pop())
            if step.get('draw_back'):
                for _ in range(n):
                    if not me.deck: break
                    me.hand.append(me.deck.pop())
            return f'redesenhou a mão ({n} cartas)'

        # Versao OPONENTE de shuffle_hand_into_deck: forca o oponente a
        # reciclar sua mao inteira no deck e recomprar N cartas (OP06-047).
        if action == 'opp_shuffle_hand_into_deck':
            import random as _rnd
            n = len(opp.hand)
            if n == 0:
                return ''
            cards = list(opp.hand)
            opp.hand.clear()
            opp.deck.extend(cards)
            _rnd.shuffle(opp.deck)
            draw_back = step.get('draw_back', 0)
            for _ in range(draw_back):
                if not opp.deck: break
                opp.hand.append(opp.deck.pop())
            return f'oponente reciclou mão ({n} cartas) e comprou {draw_back}'

        # ── DON: reativar DON rested (set as active) = ramp dentro do turno ───
        if action == 'add_don':
            count = step.get('count', 1)
            moved = min(count, me.don_deck)
            me.don_deck -= moved
            if step.get('rested'):
                me.don_rested += moved
                return f'adicionou {moved} DON restado' if moved else ''
            me.don_available += moved
            return f'adicionou {moved} DON ativo' if moved else ''

        if action == 'set_don_active':
            count = step.get('count', 1)
            moved = min(count, me.don_rested)
            me.don_rested    -= moved
            me.don_available += moved
            return f'reativou {moved} DON' if moved else ''

        # "Then, take an extra turn after this one" (achado 16/07,
        # OP05-119, unica carta no banco). So SETA a flag -- quem decide
        # de fato repetir o mesmo jogador e o loop de simulate(), lido
        # logo apos play_turn() retornar (ver docstring de GameState.
        # extra_turn_pending). Nao mexe na fase atual em andamento.
        if action == 'take_extra_turn':
            me.extra_turn_pending = True
            return 'ganhou um turno extra'

        # ── set_active: desrestar Character(s)/Leader fora do Refresh normal
        # (26 cartas, censo padrão 8, nunca implementado antes -- ex:
        # Komurasaki OP01-042, Pica OP05-032, Zoro OP06-118). DISTINTO de
        # set_don_active (DON!! cards) -- nunca confundir. Sempre exige
        # candidato JÁ RESTED (reativar algo já ativo é no-op sem sentido,
        # mesmo quando o texto não diz "rested" explicitamente).
        # Auto-restricao de alvo de ataque (OP12-020 Zoro lider, achado
        # 15/07): "cannot attack your opponent's Characters with a cost
        # of N or less during this turn" -- distinta de
        # lock_opp_character_attack (trava o OPONENTE, mecanica oposta).
        # Consumida na geracao de acoes de ataque (_generate_and_score_actions).
        if action == 'lock_self_attack_opp_chars_cost_lte':
            card.cannot_attack_opp_chars_cost_lte = step.get('cost_lte', 0)
            return f'{card.name[:18]} nao pode atacar Characters custo<={step.get("cost_lte", 0)} este turno'

        if action == 'set_active':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_board_value,
                eligible_cards,
            )

            target = step.get('target', 'self')
            if target == 'self':
                if card.rested:
                    card.rested = False
                    return f'{card.name[:18]} ficou ativo'
                return ''
            if target == 'leader':
                if not card_matches_filter(me.leader, step.get('filter_type', '')):
                    return ''
                if me.leader.rested:
                    me.leader.rested = False
                    return f'{me.leader.name[:18]} (leader) ficou ativo'
                return ''
            if target == 'own_stage':
                stage = me.field_stage
                if not stage or not stage.rested:
                    return ''
                wanted_color = step.get('color', '')
                if wanted_color and wanted_color.lower() not in stage.color.lower():
                    return ''
                stage.rested = False
                return f'{stage.name[:18]} (stage) ficou ativo'

            count = step.get('count', 1)
            candidatos = eligible_cards(
                me.field_chars,
                rested_only=True,
                filter_text=step.get('filter_type', ''),
                name_or_code=step.get('filter_name', ''),
                color=step.get('color', ''),
                attribute=step.get('attribute', ''),
                cost_lte=step.get('cost_lte'),
                cost_gte=step.get('cost_gte'),
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                power_eq=step.get('power_eq'),
            )

            ativados = []
            for _ in range(count):
                if not candidatos:
                    break
                melhor = choose_highest_board_value(candidatos)
                melhor.rested = False
                remove_by_identity(candidatos, melhor)
                ativados.append(melhor.name[:14])

            if target == 'own_character_and_leader' and me.leader.rested:
                me.leader.rested = False
                ativados.append(f'{me.leader.name[:14]} (leader)')
            elif target == 'leader_or_character' and not ativados and me.leader.rested:
                # "leader OR character" sem candidato de character valido --
                # tenta o leader como alternativa (mesmo "ou" da carta).
                me.leader.rested = False
                ativados.append(f'{me.leader.name[:14]} (leader)')

            return f'ficou(ram) ativo(s): {", ".join(ativados)}' if ativados else ''

        # ── REMOÇÃO: enviar Character do oponente ao FUNDO do deck dele ───────
        # Remoção forte (ignora On-KO; enterra no deck). Respeita imunidade a
        # removal. Distinta de bounce (mão) e KO (trash).
        if action == 'place_opp_character_bottom_deck':
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                eligible_cards,
            )
            count = step.get('count', 1)
            cands = eligible_cards(
                opp.field_chars,
                cost_lte=step.get('cost_lte'),
                power_lte=step.get('power_lte'),
                filter_text=step.get('filter_type', ''),
            )
            placed = []
            immune = []
            for _ in range(min(count, len(cands))):
                if not cands: break
                target = choose_highest_board_value(cands)
                if is_immune(target, 'removal', opp, me, source_is_opp=True):
                    immune.append(target.name[:12])
                    remove_by_identity(cands, target)
                    continue
                remove_character_from_field(opp, target, 'deck_bottom')
                remove_by_identity(cands, target)
                placed.append(target.name[:14])
            out = []
            if placed: out.append(f'fundo do deck: {", ".join(placed)}')
            if immune: out.append(f'imune: {", ".join(immune)}')
            return ' | '.join(out)

        # Variante do PROPRIO lado (achado 16/07, OP05-119 -- unica carta
        # no banco): manda os PROPRIOS personagens (opcionalmente
        # excluindo a fonte) pro fundo do PROPRIO deck. "in any order" NAO
        # e tratado como irrelevante aqui (pedido explicito do usuario,
        # ver HANDOFF/memoria "ordem no fundo do deck") -- remove_character_
        # from_field faz deck.insert(0, ...) a cada chamada, e cada insert
        # NOVO empurra os anteriores pra indices MAIORES (mais perto do
        # topo, ja que draw_phase compra via pop() do fim da lista).
        # Processar do MAIS FORTE pro MAIS FRACO deixa o mais forte com
        # indice maior (comprado mais cedo se o deck chegar la) e o mais
        # fraco no fundo de verdade (indice 0, comprado por ultimo).
        if action == 'place_own_character_bottom_deck':
            count = step.get('count', 1)
            candidatos = [c for c in me.field_chars
                          if not (step.get('exclude_self') and c is card)]
            candidatos.sort(key=lambda c: c.board_value(), reverse=True)
            movidos = []
            for alvo in candidatos[:count]:
                remove_character_from_field(me, alvo, 'deck_bottom')
                movidos.append(alvo.name[:14])
            return f'fundo do proprio deck: {", ".join(movidos)}' if movidos else ''

        # ── REMOÇÃO: enviar Character do oponente ao FUNDO do deck dele (fim) ──
        # ── MILL: trashar do topo do PRÓPRIO deck (sem disparar trigger) ──────
        # Regra (Arthur): trash do deck = carta vai ao trash SEM ativar Trigger.
        # Topo do deck = fim da lista (= draw_phase usa pop()).
        if action == 'trash_from_deck_top':
            count = step.get('count', 1)
            milled = 0
            for _ in range(count):
                if not me.deck: break
                me.trash.append(me.deck.pop())
                milled += 1
            return f'mill {milled} (topo do deck -> trash)' if milled else ''

        # ── LIFE: adicionar à própria vida (unifica o antigo 'heal') ──────────
        # Convenção confirmada no engine: fim da lista = TOPO da vida
        # (combate faz opp.life.pop() = último = próxima a revelar).
        # Logo: append = topo ; insert(0) = fundo.
        if action == 'gain_life':
            count  = step.get('count', 1)
            source = step.get('source', 'deck_top')
            dest   = step.get('dest', 'life_top')
            power_eq = step.get('power_eq')

            def _put_life(c):
                face = step.get('face')
                c.life_face_up = (face == 'up')
                if dest == 'life_bottom':
                    me.life.insert(0, c)
                else:
                    me.life.append(c)   # life_top e life_top_or_bottom → topo (default)

            added = 0
            for _ in range(count):
                c = None
                if source == 'deck_top':
                    if not me.deck: break
                    c = me.deck.pop()       # topo do deck = fim da lista (= draw_phase)
                elif source == 'hand':
                    # Filtros (cost_lte/cost_eq/filter_type) -- achado
                    # 16/07 (EB03-059/EB04-060/OP09-104/OP10-103/OP10-107):
                    # antes pegava SEMPRE a 1a carta da mao (pop(0)),
                    # ignorando qualquer filtro do step por completo,
                    # mesmo quando o parser ja o extraia corretamente.
                    from optcg_engine.rules_facade import (
                        choose_highest_board_value,
                        eligible_cards,
                    )
                    candidatos_hand = eligible_cards(
                        me.hand,
                        cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'),
                        filter_text=step.get('filter_type', ''),
                    )
                    if not candidatos_hand:
                        break
                    c = choose_highest_board_value(candidatos_hand)
                    remove_by_identity(me.hand, c)
                elif source == 'trash':
                    from optcg_engine.rules_facade import (
                        choose_highest_board_value,
                        eligible_cards,
                    )
                    candidatos_trash = eligible_cards(
                        me.trash,
                        cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'),
                        filter_text=step.get('filter_type', ''),
                    )
                    if not candidatos_trash:
                        break
                    c = choose_highest_board_value(candidatos_trash)
                    remove_by_identity(me.trash, c)
                elif source == 'hand_or_trash':
                    # Fonte COMBINADA (achado 16/07, ST13-003): elegiveis
                    # de AMBAS as zonas, escolhe o melhor entre as duas.
                    from optcg_engine.rules_facade import (
                        choose_highest_board_value,
                        eligible_cards,
                    )
                    candidatos_ht = eligible_cards(
                        me.hand, cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'), filter_text=step.get('filter_type', ''),
                    ) + eligible_cards(
                        me.trash, cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'), filter_text=step.get('filter_type', ''),
                    )
                    if not candidatos_ht:
                        break
                    c = choose_highest_board_value(candidatos_ht)
                    if not remove_by_identity(me.hand, c):
                        remove_by_identity(me.trash, c)
                elif source == 'own_field':
                    # Character do PRÓPRIO campo virando life card (ex:
                    # Kawamatsu OP06-103, "with 0 power" -> power_eq=0).
                    # Usa remove_character_from_field (nao pop(0) direto)
                    # pra devolver DON anexado -- achado 27/06, faltava
                    # nesse ponto especifico (fora do grep original).
                    candidatos = [x for x in me.field_chars
                                  if power_eq is None or x.power == power_eq]
                    if not candidatos: break
                    c = min(candidatos, key=lambda x: x.board_value())
                    remove_character_from_field(me, c, dest)
                    added += 1
                    continue
                elif source == 'opp_life':
                    if not opp.life: break
                    c = opp.life.pop()
                if c is None: break
                _put_life(c)
                added += 1
            return f'+{added} vida ({source}->{dest})' if added else ''

        # Revela o TOPO da propria Life e joga exatamente aquela carta se
        # os filtros baterem. Se falhar, a carta permanece na Life. Play por
        # efeito e gratuito; on_success_steps implementa o "If you do".
        if action == 'play_from_life_top':
            if not me.life:
                return ''
            candidate = me.life[-1]
            wanted_name = (step.get('filter_name') or '').lower()
            if wanted_name and wanted_name not in candidate.name.lower():
                return ''
            wanted_type = step.get('filter_type') or ''
            if wanted_type and _norm_type_text(wanted_type) not in _norm_type_text(candidate.sub_types):
                return ''
            if step.get('cost_eq') is not None and candidate.cost != step['cost_eq']:
                return ''
            if step.get('cost_lte') is not None and candidate.cost > step['cost_lte']:
                return ''
            if candidate.card_type != 'CHARACTER':
                return ''
            me.life.pop()
            candidate.life_face_up = False
            if len(me.field_chars) >= 5:
                worst = min(me.field_chars, key=lambda x: x.board_value())
                remove_character_from_field(me, worst, 'trash')
            me.field_chars.append(candidate)
            candidate.just_played = not (
                candidate.has_rush or candidate.rush_this_turn or candidate.is_rush_character())
            candidate.rush_character_only_this_turn = (
                candidate.is_rush_character() and not candidate.is_rush())
            apply_conditional_keyword_passives(me, opp)
            self._last_selected = candidate
            nested_logs = []
            for nested in step.get('on_success_steps', []):
                nested_log = self._execute_step(nested, card)
                if nested_log:
                    nested_logs.append(nested_log)
            suffix = f' | {" | ".join(nested_logs)}' if nested_logs else ''
            return f'jogou da Life: {candidate.name[:15]}{suffix}'

        # ── LIFE: "comprar" da própria vida para a mão (Hiyori OP06-106) ──────
        if action == 'life_to_hand':
            # ST15-001 Atmos: "cannot add Life cards to your hand using your
            # own effects during this turn" -- bloqueia esta action.
            if me.cant_take_life_this_turn:
                return ''
            count = step.get('count', 1)
            src   = step.get('source', 'life_top')
            taken = 0
            for _ in range(count):
                if not me.life: break
                # topo = pop() (fim) ; fundo = pop(0). top_or_bottom default topo.
                c = me.life.pop(0) if src == 'life_bottom' else me.life.pop()
                c.life_face_up = False
                me.hand.append(c)
                taken += 1
            return f'comprou {taken} da vida -> mao' if taken else ''

        # ── Restricao: nao pode adicionar Life cards a mao neste turno ──────────
        # ST15-001 Atmos: "you cannot add Life cards to your hand using your
        # own effects during this turn." -- ativo quando a carta ataca.
        if action == 'self_cant_take_life':
            me.cant_take_life_this_turn = True
            return 'restricao: nao pode pegar da vida este turno'

        # ── LIFE: remover da vida do OPONENTE ─────────────────────────────────
        if action == 'attack_life':
            count = step.get('count', 1)
            removed = 0
            for _ in range(count):
                if not opp.life: break
                c = opp.life.pop()              # topo da vida do oponente
                c.life_face_up = False
                opp.trash.append(c)
                removed += 1
            return f'-{removed} vida do oponente' if removed else ''

        # ── DANO direto, FORA de combate (ex: Nico Robin EB03-055, Reject
        # OP06-116) -- distinto de attack_life: aqui a vida vai pra MAO e,
        # se tiver [Trigger], pode ser revelada/ativada (regra 4-6, mesmo
        # fluxo que dano de combate ao Leader ja usa). NUNCA tratar como
        # attack_life -- la a vida vai pro trash sem trigger, e e o oposto
        # do que esse efeito faz.
        if action == 'deal_damage':
            count = step.get('count', 1)
            dealt = 0
            for _ in range(count):
                if not opp.life: break
                life_card = opp.life.pop()
                life_card.life_face_up = False
                opp.hand.append(life_card)
                dealt += 1
                if life_card.has_trigger:
                    opp.triggers_activated += 1
                    ee_opp = EffectExecutor(opp, me)
                    ee_opp.execute(life_card, 'trigger')
            return f'-{dealt} vida do oponente (dano, com trigger)' if dealt else ''

        # ── LIFE: descartar da própria vida (custo/troca) ─────────────────────
        if action == 'trash_own_life':
            if step.get('face') == 'up':
                face_up_cards = [c for c in list(me.life) if c.life_face_up]
                for c in face_up_cards:
                    remove_by_identity(me.life, c)
                    c.life_face_up = False
                    me.trash.append(c)
                return f'trashou {len(face_up_cards)} vida(s) face-up' if face_up_cards else ''
            if step.get('until_1'):
                trashed = 0
                while len(me.life) > 1:
                    c = me.life.pop()
                    c.life_face_up = False
                    me.trash.append(c)
                    trashed += 1
                return f'trashou {trashed} da propria vida (ate 1)' if trashed else ''
            count = step.get('count', 1)
            trashed = 0
            for _ in range(count):
                if not me.life: break
                c = me.life.pop()
                c.life_face_up = False
                me.trash.append(c)
                trashed += 1
            return f'trashou {trashed} da propria vida' if trashed else ''

        # ── Add from trash ────────────────────────────────────────────────────
        # ── PLAY_CARD: jogar carta de graça (não consome DON) ─────────────────
        # Regra confirmada (Arthur): "play card from effect" entra com custo ZERO.
        # Dois grupos no banco:
        #   GRUPO 1 (source='self', sempre [Trigger]): jogar a PRÓPRIA carta que
        #     virou da vida, em vez de mandá-la para a mão. OPCIONAL — a IA decide
        #     por score se vale jogar grátis ou guardar na mão (counter/uso futuro).
        #   GRUPO 2 (cost_lte/filter_type/color): jogar OUTRA carta da mão que bate
        #     o filtro, escolhendo a de maior valor. "up to" => pode não jogar.
        if action == 'play_card':

            def _score_to_play(c):
                # score local (executor não tem DecisionEngine): board_value real
                # + bônus por efeito útil, via as MESMAS flags do analysis_db.
                f = get_card_flags(c.code)
                s = c.board_value()
                if f.get('kos') or f.get('is_removal'): s += 70
                if f.get('bounces'):                    s += 45
                if f.get('rests_opponent'):             s += 35
                if f.get('is_searcher'):                s += 40
                if f.get('draws'):                      s += 35
                if f.get('is_blocker'):                 s += 30
                if f.get('power_buff'):                 s += 20
                if f.get('has_trigger'):                s += 10
                # Carta CERTA do game_plan (a bomba do combo, ex: Five Elders):
                # 3a copia do MESMO bug ja corrigido em avaliar_carta (14/07) e
                # em order_target_candidates/own_hand (09/07) -- esta selecao
                # (usada pela EXECUCAO real de qualquer 'play_card' dentro de
                # QUALQUER trigger, incl. Empty Throne activate_main) nunca
                # tinha sido tocada. Sem isso, um searcher generico (+40 de
                # flag) batia a bomba de 12000 poder (board_value=12, zero
                # flags) por larga margem -- achado ao vivo indireto 14/07
                # (Empty Throne jogou Ju Peter em vez de Five Elders com
                # ambos na mao). Generico via compute_game_plan, zero nome de
                # carta.
                try:
                    if compute_game_plan(me).get('win_con_code') == c.code:
                        s += 90
                except Exception:
                    pass
                return s

            def _pior_para_trocar(field_chars):
                # Pior character pra eventual troca por um play gratis quando o
                # campo ja tem 5. EXCEÇÃO (aprovada por Arthur, audit PLAY):
                # nunca escolhe pra trocar quem tem has_blocker ou DON anexado
                # -- board_value() nao captura esse papel ativo (um Blocker de
                # power baixo seguraria o campo; um character com DON anexado
                # perde esse DON se for trashado, ja que nada devolve pra area
                # de custo nesse caminho -- bug separado, registrado, nao
                # corrigido aqui, só evitado com essa exceção).
                candidatos = [x for x in field_chars
                              if not (x.has_blocker or x.blocker_this_turn) and x.don_attached == 0]
                pool = candidatos if candidatos else field_chars  # se TODOS
                # tiverem papel ativo, nao trava a troca pra sempre -- usa o
                # pool completo como ultimo recurso.
                if not pool:
                    return None
                return min(pool, key=lambda x: x.board_value())

            def _put_into_play(c):
                # replica a parte de "entrar em campo" de _play_card, SEM cobrar
                # DON e sem o verbose do replay. Eventos vão pro trash (resolvem
                # efeito on_play depois), characters/stages pro campo.
                if c.card_type == 'CHARACTER':
                    if len(me.field_chars) >= 5:
                        worst = _pior_para_trocar(me.field_chars)
                        if worst is not None:
                            remove_character_from_field(me, worst, 'trash')
                    c.rested = False
                    me.field_chars.append(c)
                    apply_conditional_keyword_passives(me, opp)
                    c.just_played = not (c.has_rush or c.rush_this_turn or c.is_rush_character())
                    c.rush_character_only_this_turn = c.is_rush_character() and not c.is_rush()
                elif c.card_type == 'STAGE':
                    if me.field_stage:
                        me.trash.append(me.field_stage)
                    me.field_stage = c
                elif c.card_type == 'EVENT':
                    me.trash.append(c)
                    me.events_activated_costs_this_turn.append(c.cost)
                # dispara o efeito on_play da carta jogada (entrou agora)
                self.execute(c, 'on_play')
                self.execute(c, 'main')

            source = step.get('source')

            # GRUPO 1 — jogar a própria carta (trigger de vida), opcional por score
            if source == 'self':
                if not contains_identity(me.hand, card):
                    return ''   # já saiu da mão / contexto inesperado
                # valor de jogar (corpo em campo) vs guardar na mão (counter/futuro)
                val_play = _score_to_play(card)
                val_keep = card.counter / 1000 * 15 + card.board_value() * 0.3
                # guarda de campo cheio: só descarta o pior se a nova supera
                campo_cheio = (card.card_type == 'CHARACTER' and len(me.field_chars) >= 5)
                if campo_cheio:
                    pior = _pior_para_trocar(me.field_chars)
                    if pior is None or card.board_value() <= pior.board_value():
                        return ''   # não vale trocar — mantém na mão
                if val_play <= val_keep:
                    return ''       # vale mais na mão — não joga
                remove_by_identity(me.hand, card)
                _put_into_play(card)
                return f'jogou {card.name[:18]} (grátis, do trigger)'

            # GRUPO 2 — jogar carta da mão (ou mão+trash) com filtro, escolhendo a melhor
            cost_lte = step.get('cost_lte')
            if cost_lte == 'don_count_self':
                cost_lte = self.me.don_available + self.me.don_rested  # dinâmico
            cost_eq = step.get('cost_eq')
            fontes = [me.hand]
            if step.get('source_alt') == 'trash':
                fontes.append(me.trash)

            elegiveis = []
            for fonte in fontes:
                elegiveis.extend(
                    c for c in eligible_cards(
                        fonte,
                        cost_lte=cost_lte,
                        cost_eq=cost_eq,
                        power_lte=step.get('power_lte'),
                        power_eq=step.get('power_eq'),
                        has_trigger=step.get('has_trigger', False),
                        filter_text=step.get('filter_type', ''),
                        name_or_code=step.get('filter_name', ''),
                        color=step.get('color', ''),
                        exclude_name=step.get('exclude', ''),
                    )
                    # sem card_type explicito no step = CHARACTER (mesma regra
                    # de _step_is_viable e _elegivel_para_play — 12/07)
                    if c.card_type == (step.get('card_type') or 'CHARACTER').upper()
                )
            # "no base effect" -- so cartas sem efeito parseado no banco
            # (achado 16/07, EB02-022/EB03-003/EB03-007/EB03-039), mesma
            # convencao ja usada por gain_life (source=='trash').
            if step.get('filter_no_effect'):
                elegiveis = [c for c in elegiveis
                             if not get_card_effects(c.code).get('effects')]

            if not elegiveis:
                return ''

            count = step.get('count', 1)
            jogadas = []
            for _ in range(count):
                if not elegiveis:
                    break
                melhor = max(elegiveis, key=_score_to_play)
                # guarda de campo cheio para characters
                if melhor.card_type == 'CHARACTER' and len(me.field_chars) >= 5:
                    pior = _pior_para_trocar(me.field_chars)
                    if pior is None or melhor.board_value() <= pior.board_value():
                        remove_by_identity(elegiveis, melhor)
                        continue
                if not remove_by_identity(me.hand, melhor):
                    remove_by_identity(me.trash, melhor)
                remove_by_identity(elegiveis, melhor)
                _put_into_play(melhor)
                if step.get('enters_rested'):
                    melhor.rested = True
                jogadas.append(melhor.name[:15])
            return f'jogou (grátis): {", ".join(jogadas)}' if jogadas else ''

        if action == 'add_from_trash':
            from optcg_engine.rules_facade import eligible_cards

            filter_name = step.get('filter_name', '').lower()
            count = step.get('count', 1)
            found = eligible_cards(
                me.trash,
                cost_lte=step.get('cost_lte'),
                cost_gte=step.get('cost_gte'),
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                filter_text=step.get('filter_type', ''),
                name_or_code=filter_name,
                color=step.get('color', ''),
                exclude_name=step.get('exclude_name', ''),
            )
            added = []
            for c in found[:count]:
                remove_by_identity(me.trash, c)
                me.hand.append(c)
                added.append(c.name[:15])
            return f'recuperou do trash: {", ".join(added)}' if added else ''

        # ── Keywords ──────────────────────────────────────────────────────────
        if action == 'gain_rush':
            # target='selected': "that Character gains [Rush]" refere-se a
            # carta selecionada/jogada por um step ANTERIOR no mesmo bloco
            # (ex: OP12-058 Whitebeard, play_from_deck + gain_rush), nao a
            # propria `card` (o Event/Character que carrega o efeito).
            alvo = self._last_selected if step.get('target') == 'selected' else card
            if alvo is None:
                return ''
            if step.get('duration') == 'this_turn':
                alvo.rush_this_turn = True
                return 'ganhou Rush (so este turno)'
            alvo.has_rush = True
            return 'ganhou Rush'
        if action == 'gain_rush_character':
            card.has_rush_character = True
            # Se o character ja esta em campo (efeito concedido mid-jogo, nao
            # no momento em que entrou), a restricao de alvo so importa se
            # ele ainda nao atacou neste turno -- aproxima usando just_played
            # como sinal de 'ainda no turno em que pode usar a permissao'.
            # Quando concedido no proprio turno em que e jogado (ex:
            # EB04-007 via Activate:Main apos o On Play), marca a janela.
            card.rush_character_only_this_turn = not (card.has_rush or card.rush_this_turn)
            return 'ganhou Rush: Character'
        if action == 'grant_rush_character_type':
            wanted = _norm_type_text(step.get('filter_type') or '')
            granted = []
            for target in me.field_chars:
                if wanted and wanted in _norm_type_text(target.sub_types):
                    target.has_rush_character = True
                    if target.just_played:
                        target.rush_character_only_this_turn = True
                    granted.append(target.name[:14])
            return f'Rush: Character para tipo: {", ".join(granted)}' if granted else ''
        if action == 'select_grant_rush_character':
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            candidates = eligible_cards(me.field_chars, filter_text=step.get('filter_type', ''))
            if not candidates:
                return ''
            target = choose_highest_board_value(candidates)
            target.has_rush_character = True
            if target.just_played:
                target.rush_character_only_this_turn = True
            return f'{target.name[:18]} ganhou Rush: Character'
        if action == 'gain_blocker':
            if step.get('duration') == 'this_turn':
                card.blocker_this_turn = True
                return 'ganhou Blocker (so este turno)'
            card.has_blocker = True
            return 'ganhou Blocker'
        if action == 'select_grant_blocker':
            # "Up to N of your [Tipo] Characters [com filtro de custo]
            # [other than [Nome]] gains [Blocker]" -- SELECIONA outro
            # Character do proprio campo (por tipo/custo/exclusao),
            # DISTINTO de gain_blocker (sempre a propria carta-fonte, sem
            # selecao). 'until_opp_end_phase'/'until_opp_turn_end' mapeiam
            # pro MESMO blocker_this_turn -- o engine ja trata "this turn"
            # e "ate a proxima End Phase do oponente" como equivalentes
            # (mesma simplificacao documentada em refresh_phase pra
            # cannot_attack_until/cannot_be_rested_until: ambos so resetam
            # no refresh do DONO, entao a granularidade e identica).
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            count = step.get('count', 1)
            candidates = eligible_cards(
                me.field_chars,
                cost_lte=step.get('cost_lte'),
                filter_text=step.get('filter_type', ''),
                exclude_name=step.get('exclude', ''),
            )
            granted = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                target.blocker_this_turn = True
                remove_by_identity(candidates, target)
                granted.append(target.name[:15])
            return f'ganhou Blocker: {", ".join(granted)}' if granted else ''
        if action == 'select_grant_rush':
            # "Up to N of your [Nome] Characters OR up to M of your
            # Characters with a type including "Tipo", with X power or
            # more, gains [Rush]" -- OR entre nome exato E (tipo+power),
            # nao AND (achado 17/07, OP16-001). filter_name casa QUALQUER
            # power; filter_type exige power_gte tambem. Variante GENERICA
            # (sem filter_name, achado 17/07: EB03-001/OP04-001/OP12-007/
            # PRB01-001): filtro UNICO combinando tipo/custo/exclusao/
            # filter_no_tag (AND, nao OR).
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            count = step.get('count', 1)
            if step.get('filter_name'):
                pool_nome = eligible_cards(me.field_chars, name_or_code=step.get('filter_name', ''))
                pool_tipo = eligible_cards(
                    me.field_chars,
                    filter_text=step.get('filter_type', ''),
                    power_gte=step.get('power_gte'),
                )
                candidates = list(pool_nome)
                for c in pool_tipo:
                    if not contains_identity(candidates, c):
                        candidates.append(c)
            else:
                candidates = eligible_cards(
                    me.field_chars,
                    cost_lte=step.get('cost_lte'),
                    filter_text=step.get('filter_type', ''),
                    exclude_name=step.get('exclude', ''),
                )
                filter_no_tag = step.get('filter_no_tag')
                if filter_no_tag:
                    candidates = [
                        c for c in candidates
                        if filter_no_tag not in get_card_effects(c.code).get('effects', {})
                    ]
            granted = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                if step.get('duration') == 'this_turn':
                    target.rush_this_turn = True
                else:
                    target.has_rush = True
                remove_by_identity(candidates, target)
                granted.append(target.name[:15])
            return f'ganhou Rush: {", ".join(granted)}' if granted else ''
        if action == 'gain_double_attack':
            if step.get('duration') == 'this_turn':
                card.double_attack_this_turn = True
                return 'ganhou Double Attack (so este turno)'
            card.has_double_attack = True
            return 'ganhou Double Attack'
        if action == 'gain_banish':
            card.has_banish = True
            return 'ganhou Banish'
        if action == 'gain_unblockable':
            if step.get('duration') == 'this_turn':
                card.unblockable_this_turn = True
                return 'ganhou Unblockable (so este turno)'
            card.has_unblockable = True
            return 'ganhou Unblockable'

        # ── select_grant_unblockable_turn: "Select up to 1 of your [Tipo]
        # Character(s)/Leader-or-Character... if that card attacks during
        # this turn, opponent cannot activate [Blocker]." Equivalente (regra
        # 10-1-7-1) a conceder [Unblockable] SO NESTE TURNO ao alvo
        # escolhido -- por isso seta unblockable_this_turn, NUNCA
        # has_unblockable (que e permanente/nativo). DISTINTA de
        # gain_unblockable: aqui tem selecao de alvo com filtro, lá o alvo
        # é sempre 'card' (a própria carta com o efeito).
        # Sanji ST21-003, Diable Jambe ST01-016, OP13-057 (target='leader_only').
        if action == 'select_grant_unblockable_turn':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_board_value,
                eligible_cards,
            )

            if step.get('target') == 'leader_only':
                me.leader.unblockable_this_turn = True
                return f'{me.leader.name[:18]} ganhou Unblockable este turno'
            if step.get('target') == 'selected':
                # "Then, if the selected card attacks during this turn, your
                # opponent cannot activate Blocker" (OP07-057, OP12-077) --
                # alvo e o card escolhido por um step ANTERIOR no mesmo
                # bloco (buff_power target='select_filtered'), nao uma nova
                # selecao. Sem alvo memorizado, nao executa (mais seguro do
                # que adivinhar).
                alvo = self._last_selected
                if alvo is None:
                    return ''
                alvo.unblockable_this_turn = True
                return f'{alvo.name[:18]} (selecionado antes) ganhou Unblockable este turno'
            filter_type = step.get('filter_type', '')
            candidatos = eligible_cards(
                me.field_chars,
                filter_text=filter_type,
                power_gte=step.get('power_gte'),
            )
            if step.get('include_leader') and card_matches_filter(me.leader, filter_type):
                candidatos.append(me.leader)
            if not candidatos:
                return ''
            alvo = choose_highest_board_value(candidatos)
            alvo.unblockable_this_turn = True
            return f'{alvo.name[:18]} ganhou Unblockable este turno'

        # ── "can also attack active Characters" -- keyword nova (achada
        # 27/06, 9 cartas). gain_can_attack_active = PERMANENTE ("This
        # Character can also attack active Characters", sem seleção --
        # Cavendish OP04-081, Luffy OP04-090). select_grant_*_turn = mesma
        # estrutura de select_grant_unblockable_turn, mas concede
        # can_attack_active_this_turn (temporário) ao alvo escolhido.
        if action == 'gain_can_attack_active':
            card.can_attack_active = True
            return f'{card.name[:18]} pode atacar characters ativos (permanente)'

        if action == 'select_grant_can_attack_active_turn':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_board_value,
                eligible_cards,
            )

            filter_type = step.get('filter_types') or step.get('filter_type', '')
            candidatos = eligible_cards(me.field_chars, filter_text=filter_type)
            if step.get('include_leader') and card_matches_filter(me.leader, filter_type):
                candidatos.append(me.leader)
            if not candidatos:
                return ''
            alvo = choose_highest_board_value(candidatos)
            alvo.can_attack_active_this_turn = True
            if step.get('allow_played_this_turn'):
                alvo.rush_character_only_this_turn = True
            return f'{alvo.name[:18]} pode atacar characters ativos este turno'

        # Keywords passivas (apenas registra, já vem do banco)
        if action in ('keyword_blocker', 'keyword_rush', 'keyword_double_attack',
                      'keyword_banish', 'keyword_trigger', 'keyword_unblockable'):
            return ''

        return ''

    # ── Helpers de IA ────────────────────────────────────────────────────────

    def _trash_value(self, card: Card) -> float:
        """Valor aproximado de manter uma carta na mao; menor = melhor descarte."""
        if card is None:
            return 10**9

        value = DecisionEngine(self.me, self.opp).avaliar_carta(card)
        text = (card.card_text or '').lower()
        flags = get_card_flags(card.code)

        if card.card_type == 'EVENT':
            if '[counter]' in text:
                # Protecao com retorno decrescente: 1 counter na mao e uma
                # rede de seguranca real, mas o 2o/3o valem cada vez menos
                # (redundantes) -- achado 09/07: bot trashando evento
                # counter em vez de personagem reanimavel, mesmo com varios
                # counters acumulados na mao.
                counters_na_mao = sum(
                    1 for c2 in self.me.hand
                    if c2.card_type == 'EVENT' and '[counter]' in (c2.card_text or '').lower())
                value += 35 / max(1, counters_na_mao)
                if self.me.life_count() <= 2:
                    value += 35
            if flags.get('kos') or flags.get('is_removal') or flags.get('bounces'):
                value += 35
            if 'negate the effect' in text or 'cannot be removed' in text:
                value += 40
            if flags.get('draws') or flags.get('is_searcher'):
                value += 20

        # Carta cara = win condition ou ameaça principal; proteger mesmo sem DON
        # disponível agora (provavelmente jogável nos próximos turnos).
        if card.card_type == 'CHARACTER' and card.cost >= 7:
            value += 20 + card.cost * 8   # custo 10 → +100 extra

        # GamePlan (HANDOFF #119): a carta identificada como combo/bomba do
        # deck (maior play_from_trash, ex: Five Elders) ganha proteção
        # extra explícita enquanto o DON ainda não bate o custo dela —
        # diferente do bônus genérico de custo≥7 acima, este é ligado à
        # carta CERTA do deck, não a qualquer carta cara.
        plano = compute_game_plan(self.me)
        if (plano['win_con_code'] and card.code == plano['win_con_code']
                and plano['don_target'] and self.me.don_available < plano['don_target']):
            value += 150

        # Carta que ENCHE O TRASH no on_play (self-mill: trash_rest/
        # trash_from_hand/mill) e trash_SETUP do deck: enquanto o trash ainda
        # nao bateu o alvo do game_plan (ex: Imu precisa de 7 pra imunidade dos
        # Celestial Dragons + combo), joga-la ADIANTA o plano -> NAO trashar
        # como custo, guardar pra JOGAR. Pedido do usuario 14/07 (Shalria da mao
        # no early nao deve ser trashada). Generico via game_plan.trash_target +
        # acoes de trash no proprio on_play (zero nome de carta).
        if (card.card_type == 'CHARACTER' and plano.get('trash_target')
                and len(self.me.trash) < plano['trash_target']):
            _TRASH_FILL = {'trash_rest', 'trash_from_hand', 'mill', 'mill_self',
                           'trash_deck_top', 'self_mill'}
            op_steps = get_card_effects(card.code).get('on_play', {}).get('steps', [])
            if any(s.get('action') in _TRASH_FILL for s in op_steps):
                value += 50

        # Carta jogável ESTE turno vale ainda mais — perda dupla se trashada.
        custo = effective_hand_play_cost(self.me, card, self.opp)
        if custo <= self.me.don_available:
            value += 60 + custo * 6   # bônus adicional por ser jogável agora

        # Personagem recuperavel via play_from_trash da propria engine do
        # deck (ex: Five Elders OP13-082 reanima ate 5 copias de 5000 power
        # com esse mesmo nome/tipo) e descarte SEGURO: a perda e temporaria.
        # Achado 09/07 (log 17.52.14): bot trashando evento [Counter] em vez
        # de um Elder reanimavel para o custo trash_char_or_hand do lider
        # Imu -- generico pra qualquer carta+reanimador que bata o filtro,
        # nao hardcoded pro Five Elders.
        if card.card_type == 'CHARACTER':
            for src in list(self.me.field_chars) + list(self.me.hand):
                if src is card:
                    continue
                am = get_card_effects(src.code).get('activate_main', {})
                pft = next((s for s in am.get('steps', [])
                            if s.get('action') == 'play_from_trash'), None)
                if not pft:
                    continue
                conds = am.get('conditions', {})
                if conds and not EffectExecutor(self.me, self.opp)._check_conditions(conds, src):
                    continue
                ft = (pft.get('filter_type') or '').lower()
                if ft and ft not in (card.sub_types or '').lower():
                    continue
                peq = pft.get('power_eq')
                if peq is not None and card.power != peq:
                    continue
                value *= 0.4   # a maior parte do valor volta via reanimacao
                break

        return value

    def _choose_to_trash(self, hand: list) -> Optional[Card]:
        """Escolhe a carta de menor valor situacional para descartar."""
        if not hand:
            return None
        return min(hand, key=self._trash_value)

    _SACRIFICE_COST_TYPES = {'trash_from_hand', 'trash_hand', 'trash_char_or_hand',
                             'trash_typed_hand_or_named_hand_field',
                             'ko_own_character', 'trash_self', 'trash_own_life',
                             'trash_own_character', 'return_own_character_to_hand'}

    def _worth_paying_optional_costs(self, costs: list, card: Card) -> bool:
        """
        Em OPTCG, um bloco de efeito com custo é sempre "you may pagar X: Y"
        -- decide se vale a pena. ÚNICA fonte de verdade pra essa pergunta,
        usada tanto por `execute()` (simulador interno) quanto por
        `resolve_optional_effect()` em sim_bridge.py (caminho ao vivo).
        Achado real 09/07: existiam DUAS heurísticas diferentes pra essa
        MESMA decisão -- o simulador interno pagava sempre que havia alvo
        (sem julgar se compensava), e o caminho ao vivo tinha sua própria
        régua isolada, sem nem saber qual carta/efeito estava perguntando.
        Isso e exatamente o que a regra "sem dois motores" existe pra
        evitar (ver memory/feedback_dois_motores.md) -- consolidado aqui.
        Custos de RECURSO (rest_self/rest_don/don_minus) não entram nessa
        conta -- já são filtrados por pagabilidade antes de chegar aqui;
        só custos de SACRIFÍCIO (mão/campo/vida) exigem julgamento de valor.
        """
        if not any(c.get('type') in self._SACRIFICE_COST_TYPES for c in costs):
            return True

        # trash_char_or_hand (ex: lider Imu): o custo tambem pode ser pago
        # com um personagem do CAMPO -- um corpo de 0 poder cujo On Play ja
        # foi gasto (ex: Saint Shalria) e sacrificio quase gratis, e trashar
        # ele ainda alimenta o plano de lixeira do deck. Achado real 11/07
        # (log 00.49.30): sem esta checagem, a decisao olhava SO a mao --
        # mao com cartas valiosas => recusava o draw do lider todo turno,
        # mesmo com 2 Shalrias gastas paradas no campo. Mesmo criterio de
        # escala do _pay_costs (board_value*10 comparavel a _trash_value).
        for c in costs:
            if c.get('type') != 'trash_char_or_hand':
                continue
            from optcg_engine.rules_facade import eligible_cards
            chars = eligible_cards(self.me.field_chars,
                                   filter_text=c.get('filter_type', ''))
            if chars and min(ch.board_value() * 10 for ch in chars) <= 60:
                return True

        # ko_own_character/trash_own_character: custo PURAMENTE de campo
        # (K.O. ou trash de um Character proprio, nunca da mao). Achado
        # 16/07: ko_own_character ja existia ha tempos mas SEMPRE caia no
        # branch generico final, que so olha self.me.hand -- avaliando o
        # recurso ERRADO (mao) pra um custo que nunca toca a mao. Mesmo
        # criterio de escala do branch trash_char_or_hand acima
        # (board_value*10 <= 60), mas aqui o RETURN e definitivo (nao
        # "either/or" com a mao -- se o campo nao compensa, o custo nao
        # compensa, ponto final, nao cai no fallback de mao).
        for c in costs:
            if c.get('type') not in ('ko_own_character', 'trash_own_character'):
                continue
            from optcg_engine.rules_facade import eligible_cards
            chars = eligible_cards(
                self.me.field_chars,
                filter_text=c.get('filter_type', ''),
                power_lte=c.get('power_lte'),
                power_gte=c.get('power_gte'),
                power_eq=c.get('power_eq'),
                exclude_card=card,
            )
            return bool(chars) and min(ch.board_value() * 10 for ch in chars) <= 60

        # return_own_character_to_hand: mesmo criterio de ko_own_character/
        # trash_own_character (custo de CAMPO, nunca da mao) -- achado
        # 16/07 (OP10-047 e familia, 8 cartas): esse custo nunca tinha
        # branch proprio aqui, entao caia no `not any(... SACRIFICE...)`
        # do topo e SEMPRE era considerado "de graca" (sem julgar se
        # devolver o Character pra mao compensa o efeito). Devolver a mao
        # e menos definitivo que K.O./trash (a carta pode ser rejogada
        # depois), mas ainda e perda real de tempo/board -- mesmo limiar
        # de "sacrificio barato" (board_value*10 <= 60).
        for c in costs:
            if c.get('type') != 'return_own_character_to_hand':
                continue
            from optcg_engine.rules_facade import eligible_cards
            chars = eligible_cards(
                self.me.field_chars,
                cost_gte=c.get('cost_gte'),
                filter_text=c.get('filter_type', ''),
                exclude_name=c.get('exclude', ''),
                exclude_card=card if c.get('exclude_self') else None,
            )
            return bool(chars) and min(ch.board_value() * 10 for ch in chars) <= 60

        for c in costs:
            if c.get('type') != 'trash_typed_hand_or_named_hand_field':
                continue
            from optcg_engine.rules_facade import eligible_cards
            named = (c.get('alternate_name') or '').lower()
            hand = eligible_cards(self.me.hand, filter_text=c.get('filter_type', ''))
            hand.extend(x for x in self.me.hand if named in x.name.lower())
            field = [x for x in self.me.field_chars if named in x.name.lower()]
            if self.me.field_stage and named in self.me.field_stage.name.lower():
                field.append(self.me.field_stage)
            values = [self._trash_value(x) for x in hand]
            values.extend(x.board_value() * 10 for x in field)
            # _trash_value tem piso estrutural 75 mesmo para carta 0/0 sem
            # counter; usar 60 tornaria as alternativas da mao impossiveis.
            return bool(values) and min(values) <= 80

        if len(self.me.hand) < 2:
            return False
        worst = self._choose_to_trash(self.me.hand)
        if worst is None:
            return False
        return self._trash_value(worst) <= 60


# ===========================================================================
# Carregamento de dados
# ===========================================================================

def _leading_keyword(t: str, kw: str) -> bool:
    """
    True so se `kw` aparece entre os keyword tags no INICIO do texto (ex:
    "[Blocker] (After your opponent...)", "[Rush][Blocker] [On Play]...").
    Convencao do jogo: keywords INCONDICIONAIS sempre vem colados no
    comeco, um colchete atras do outro. Distingue de "gains [Blocker]"/
    "this Character gains [Rush]" embutido no MEIO de uma frase condicional
    ("If you have 7+ cards in your trash, ... gains [Blocker]") -- achado
    real 10/07 (St. Marcus Mars OP13-091 sempre contava como blocker na
    pontuacao de ataque, mesmo com a lixeira vazia no turno 1, porque
    `'[blocker]' in t` acha a substring em QUALQUER lugar do texto,
    inclusive dentro da condicao). NAO aplicar a has_trigger: [Trigger]
    e convenção OPOSTA (sempre no FINAL do texto, apos as outras
    habilidades) -- confirmado numericamente (so 42/475 cartas com
    [Trigger] teriam o tag "no inicio").
    """
    return bool(re.match(r'^(?:\[[^\]]+\]\s*)*\[' + re.escape(kw) + r'\]', t.strip()))


def parse_card_effects_basic(text: str, counter_amount: str) -> dict:
    """Parser básico de keywords para cartas sem entrada no banco."""
    t = (text or '').lower()
    c_val = 0
    try:
        c_str = str(counter_amount or '').replace('.0', '')
        if c_str.isdigit():
            c_val = int(c_str)
    except:
        pass
    return {
        'has_rush':          _leading_keyword(t, 'rush'),
        'has_blocker':       _leading_keyword(t, 'blocker'),
        'has_double_attack': _leading_keyword(t, 'double attack'),
        'has_banish':        _leading_keyword(t, 'banish'),
        'has_trigger':       '[trigger]' in t,
        'has_unblockable':   _leading_keyword(t, 'unblockable'),
        'counter':           c_val,
    }


def load_cards_db(csv_path: str = 'cards_rows.csv') -> dict:
    db = {}
    try:
        df = pd.read_csv(csv_path)
        for col in ['card_cost', 'card_power', 'life']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        for col in ['card_set_id', 'card_name', 'card_color', 'card_type',
                    'card_text', 'counter_amount', 'sub_types']:
            df[col] = df[col].fillna('').astype(str)

        for _, row in df.iterrows():
            code = row['card_set_id'].split('_')[0]
            if not code or code == 'nan':
                continue
            kws = parse_card_effects_basic(row['card_text'], row['counter_amount'])
            db[code] = {
                'name':      row['card_name'],
                'color':     row['card_color'],
                'type':      row['card_type'].upper(),
                'cost':      int(row['card_cost']),
                'power':     int(row['card_power']),
                'life':      int(row['life']),
                'text':      row['card_text'],
                'sub_types': row['sub_types'],
                **kws,
            }
            # Guarda URL de imagem para o replay viewer
            img_url = str(row.get('card_image', '') or '')
            if img_url and img_url != 'nan':
                _CARD_IMAGE_CACHE[code] = img_url
        print(f'  Banco de cartas: {len(db)} cartas carregadas')
    except Exception as e:
        print(f'  Erro ao carregar {csv_path}: {e}')
    return db


def validar_deck(leader: Card, cards: list, cards_db: dict) -> tuple:
    from collections import Counter
    erros = []
    if len(cards) != 50:
        erros.append(f'Total: {len(cards)} (deve ser 50)')
    contagem = Counter(c.code for c in cards)
    for code, qty in contagem.items():
        unlimited = any(r.get('type') == 'unlimited_copies'
                        for r in get_card_game_rules(code))
        if qty > 4 and not unlimited:
            erros.append(f'{code}: {qty} copias (max 4)')
    for rule in get_card_game_rules(leader.code):
        if rule.get('type') == 'forbid_cards_cost_gte':
            invalidos = sorted({c.code for c in cards if c.cost >= rule['cost_gte']})
            if invalidos:
                erros.append(f"{leader.code}: cartas de custo {rule['cost_gte']}+ proibidas: "
                             + ', '.join(invalidos))
        elif rule.get('type') == 'forbid_card_type_cost_gte':
            invalidos = sorted({c.code for c in cards
                                if c.card_type == rule['card_type']
                                and c.cost >= rule['cost_gte']})
            if invalidos:
                erros.append(f"{leader.code}: {rule['card_type']} de custo "
                             f"{rule['cost_gte']}+ proibidos: " + ', '.join(invalidos))
    return len(erros) == 0, erros


# Cache de CardData por código de carta -- garante referência compartilhada
# entre todas as cópias da mesma carta em qualquer GameState (ver
# _make_card e Card.__deepcopy__). Não é limpo entre partidas: CardData é
# imutável e idêntico para o mesmo código em qualquer contexto, então
# manter o cache ao longo de todo o processo é seguro e só economiza
# trabalho repetido.
_CARD_DATA_CACHE: dict = {}
# Cache de imagens: code -> URL da imagem (preenchido por load_cards_db)
_CARD_IMAGE_CACHE: dict = {}


def _make_card(code: str, data: dict) -> Card:
    """Cria Card a partir do banco de dados, usando o effects_db para keywords."""
    effects = get_card_effects(code)
    alternate_names = tuple(
        name
        for rule in get_card_game_rules(code)
        if rule.get('type') == 'alternate_names'
        for name in rule.get('names', [])
    )

    # Keywords do banco ou do parse básico
    has_blocker      = data.get('has_blocker', False)
    has_rush         = data.get('has_rush', False)
    has_rush_character = data.get('has_rush_character', False)
    has_double_attack= data.get('has_double_attack', False)
    has_banish       = data.get('has_banish', False)
    has_trigger      = data.get('has_trigger', False)
    has_unblockable  = data.get('has_unblockable', False)

    # Enriquece com o banco de efeitos
    if 'passive' in effects:
        for step in effects['passive'].get('steps', []):
            a = step.get('action', '')
            if a == 'keyword_blocker':      has_blocker = True
            elif a == 'keyword_rush':       has_rush = True
            elif a == 'keyword_rush_character': has_rush_character = True
            elif a == 'keyword_double_attack': has_double_attack = True
            elif a == 'keyword_banish':     has_banish = True
            elif a == 'keyword_trigger':    has_trigger = True
            elif a == 'keyword_unblockable': has_unblockable = True

    # Keywords CONDICIONAIS a [DON!! ×N]: só valem com N DON anexados.
    # Guardadas em dict {keyword: don_req}; a Card decide na hora se está ativa.
    don_cond_keywords = {}
    if 'don_conditional_keywords' in effects:
        for step in effects['don_conditional_keywords'].get('steps', []):
            a = step.get('action', '')
            req = step.get('don_requirement', 1)
            kw = a.replace('keyword_', '')
            don_cond_keywords[kw] = req

    # Campos extras detectados pelo banco ou pelo texto
    t = data.get('text', '').lower()
    is_searcher   = ('look at' in t or 'search your deck' in t or 'add up to' in t)
    has_start_of_game = 'at the start of the game' in t
    has_on_play_ko = 'on play' in t and ('k.o.' in t or 'trash' in t) and 'draw' not in t
    has_bounce    = 'return' in t and 'hand' in t
    has_rest_effect = 'rest' in t and 'opponent' in t
    has_power_minus = '-' in t and 'power' in t and 'opponent' in t
    trash_opp_char = 'opponent' in t and ('trash' in t or 'k.o.' in t) and 'on play' in t

    import re as _re
    raw_draw = (t.count('draw 1') + t.count('draw 2') * 2 +
                t.count('draw 3') * 3 + t.count('draw a card'))
    draw_then_trash = 0
    draw_condition  = 'always'
    m = _re.search(r'draw\s+(\d)\s+cards?.*?trash\s+(\d)\s+card', t)
    if m:
        raw_draw = int(m.group(1))
        draw_then_trash = int(m.group(2))
        lm = _re.search(r'if you have\s+(\d+)\s+or less life', t)
        if lm:
            draw_condition = f'life<={lm.group(1)}'

    # Cache de CardData por código: garante que TODAS as cópias da mesma
    # carta (em qualquer GameState, qualquer deepcopy) compartilham a
    # MESMA instância de CardData -- sem isto, cada chamada de _make_card
    # criaria um CardData novo e o ganho de deepcopy seria parcial (cada
    # Card ainda apontaria para um objeto distinto, mesmo que do mesmo
    # código, perdendo a vantagem de referência compartilhada).
    cache_key = code
    card_data = _CARD_DATA_CACHE.get(cache_key)
    if card_data is None:
        card_data = CardData(
            code=code,
            name=data.get('name', code),
            card_type=data.get('type') or 'CHARACTER',
            color=data.get('color', ''),
            cost=data.get('cost', 0),
            power=data.get('power', 0),
            counter=data.get('counter', 0),
            life=data.get('life', 0),
            sub_types=data.get('sub_types', ''),
            attribute=data.get('attribute', ''),
            card_text=data.get('text', ''),
            has_trigger=has_trigger,
            don_cond_keywords=tuple(don_cond_keywords.items()) if don_cond_keywords else None,
            is_searcher=is_searcher,
            draw_power=raw_draw,
            draw_then_trash=draw_then_trash,
            draw_condition=draw_condition,
            has_on_play_ko=has_on_play_ko,
            has_bounce=has_bounce,
            has_rest_effect=has_rest_effect,
            has_start_of_game=has_start_of_game,
            has_power_minus=has_power_minus,
            trash_opp_char=trash_opp_char,
            alternate_names=alternate_names,
        )
        _CARD_DATA_CACHE[cache_key] = card_data

    return Card(
        data=card_data,
        has_rush=has_rush,
        has_rush_character=has_rush_character,
        has_blocker=has_blocker,
        has_double_attack=has_double_attack,
        has_banish=has_banish,
        has_unblockable=has_unblockable,
    )


def build_real_deck(deck_name: str, deck_url: str,
                    df_raw: pd.DataFrame, cards_db: dict) -> Optional[tuple]:
    rows = df_raw[df_raw['deck_url'] == deck_url]
    if rows.empty:
        return None

    leader = None
    cards  = []

    for _, row in rows.iterrows():
        code = str(row['card_code'])
        qty  = int(row['qty'])
        data = cards_db.get(code, {})
        if not data:
            continue

        card = _make_card(code, data)

        if card.card_type == 'LEADER':
            leader = card
        else:
            for _ in range(qty):
                cards.append(deepcopy(card))

    if leader is None:
        leader = Card(data=CardData(code='UNK', name=deck_name, card_type='LEADER',
                                     color='', power=5000, life=5))

    return leader, cards, None  # start_stage detectada no setup


# ===========================================================================
# DecisionEngine — IA de decisão
# ===========================================================================


# ============================================================================
# NOVO DecisionEngine — Análise probabilística completa
# Substitui a classe DecisionEngine no decision_engine.py
# ============================================================================

class GameAnalyzer:
    """
    Analisador de estado do jogo — calcula probabilidades e avalia posições.
    Usado pelo DecisionEngine para tomar decisões informadas.
    """

    def __init__(self, me: 'GameState', opp: 'GameState'):
        self.me  = me
        self.opp = opp

    # ── Análise do deck (perfil early/mid/late) ──────────────────────────────

    def deck_profile(self) -> str:
        """
        Determina se o deck é early, mid ou late game
        baseado na curva de custo das cartas no campo e mão.
        """
        all_cards = self.me.field_chars + self.me.hand
        if not all_cards:
            return 'mid'
        avg_cost = sum(c.cost for c in all_cards) / len(all_cards)
        if avg_cost <= 2.5:   return 'early'
        elif avg_cost <= 5.0: return 'mid'
        else:                 return 'late'

    def game_phase(self) -> str:
        """
        FASE DA PARTIDA pelos DON na mesa (documento pág. 3):
        Early (0-4 DON), Mid (5-8), Late (9-10).
        É o MOMENTO da partida, não o tipo do deck.
        """
        don_total = self.me.don_available + self.me.don_rested
        if don_total <= 4:   return 'early'
        elif don_total <= 8: return 'mid'
        else:                return 'late'

    def deck_profile_type(self) -> str:
        """
        PERFIL do deck (aggressive/control/midrange) a partir do censo do deck
        completo. Diferente de deck_profile() (que é por curva de mão+campo).
        Usa o deck guardado em me.full_deck_census (setado no setup).
        """
        census = getattr(self.me, 'full_deck_census', None)
        if not census:
            return 'midrange'  # sem censo, neutro
        from optcg_engine.deck_census import deck_profile as classify
        return classify(census)['profile']

    # ── Potencial ofensivo ───────────────────────────────────────────────────

    def my_attack_power(self) -> int:
        """Poder total de ataque disponível (sem DON)."""
        total = attack_time_power(self.me.leader, self.opp) if not self.me.leader.rested and not self.me.cannot_attack_leader_this_turn else 0
        for c in self.me.field_chars:
            if character_can_attack_now(c, self.me, self.opp):
                total += attack_time_power(c, self.opp)
        return total

    def my_available_don(self) -> int:
        return self.me.don_available

    def max_don_boost(self) -> int:
        """Máximo de boost de poder com DON disponível."""
        return self.me.don_available * 1000

    # ── Potencial defensivo do oponente ──────────────────────────────────────

    def opp_counter_potential(self) -> int:
        """
        Potencial de counter do oponente: soma REAL do stat impresso
        (counter) + efeitos [Counter] parseados (buff_power em
        effects.counter.steps, respeitando as condições do efeito contra o
        estado real dele) das cartas da mão. As cartas da mão dele existem
        como objetos Card tanto na simulação quanto no caminho do bot
        (SoloVSelf) — soma REAL, não estimativa estatística (a estimativa
        antiga por tamanho de mão devolvia 0 para mão de 2 cartas mesmo com
        2 Kobys de counter 2000; visto em partida real 06/07).

        Achado 07/07: cartas como Ground Death e "...Never Existed..." têm
        counter=0 no stat impresso — o bônus delas é um efeito [Counter]
        Activate condicional (+4000, ex: trash_gte 10 / leader_is imu), que
        esse cálculo ignorava por completo. Isso fazia o bot atacar
        empatado sem margem e falhar contra elas (Teach 5000 e depois 9000
        vs Ethanbaron bufado, mesma partida, duas vezes).

        Se no futuro a mão for oculta de verdade (multiplayer vs humano),
        voltar à estimativa para os slots desconhecidos, como
        opp_counter_chunks_for_lethal faz — regra do usuário 07/07: o banco
        de cartas/efeitos permite estimar a densidade média de counter do
        formato para os slots que não dá pra ver.
        """
        ee = EffectExecutor(self.opp, self.me)   # perspectiva do DONO da carta
        total = 0
        for c in self.opp.hand:
            total += getattr(c, 'counter', 0)
            counter_block = get_card_effects(c.code).get('counter', {})
            steps = counter_block.get('steps', [])
            if not steps:
                continue
            if ee._check_conditions(counter_block.get('conditions', {}), c):
                total += sum(s.get('amount', 0) for s in steps
                            if s.get('action') == 'buff_power')
        return total

    def opp_counter_chunks_for_lethal(self) -> list[int]:
        """
        Counter disponivel para analise de lethal GARANTIDO sem espiar a mao
        oculta. Cartas reveladas contam pelo valor real; slots desconhecidos
        contam como possiveis counters de 2000. Isso e conservador de proposito:
        se a mao e desconhecida, nao podemos chamar de lethal garantido.
        """
        known = self.opp.known_hand_cards()
        unknown_hand_size = max(0, len(self.opp.hand) - len(known))

        # Cartas reveladas: valor real de counter (inclui 0 para cartas sem counter)
        chunks = [c.counter for c in known]
        # Slots desconhecidos: não sabemos o counter — tratamos como 0 para
        # não inflar a defesa do oponente com suposições. O cálculo de lethal
        # é sobre o que podemos GARANTIR, não sobre o que o oponente pode ter.
        # (Se o oponente tiver counters ocultos ele escolherá usar, mas não
        # sabemos quantos são — ignorar é conservador para o atacante.)
        # Ignoramos slots ocultos: nenhum chunk adicional.
        _ = unknown_hand_size  # reservado para futura estimativa probabilística
        return sorted(chunks)

    def opp_counter_in_hand(self) -> int:
        """Counter real do oponente (se visível — normalmente 0 em simulação)."""
        return self.opp.counter_in_hand()

    def opp_has_active_don_for_events(self) -> bool:
        """Oponente tem DON para ativar eventos de defesa?"""
        return self.opp.don_available >= 1

    def opp_blocker_count(self) -> int:
        """Quantos blockers ativos o oponente tem."""
        return len(self.opp.blockers_active())

    def opp_attack_count(self) -> int:
        """Quantos personagens o oponente pode atacar no próximo turno."""
        count = sum(1 for c in self.opp.field_chars if not c.rested)
        if not self.opp.leader.rested:
            count += 1
        return count

    # ── Análise de lethality ─────────────────────────────────────────────────

    def can_lethal_this_turn(self) -> bool:
        """
        Posso GARANTIR a vitória neste turno, mesmo no pior caso de defesa do
        oponente (ele escolhe livremente blocker/counter por ataque, na ordem
        que mais o favorece)?

        Antes, esta funcao so contava NUMERO de ataques >= vida+1, ignorando
        poder/blocker/counter -- superestimava lethal contra qualquer
        oponente com blocker ou counter na mao. Agora simula o pior caso real:
          1. Lista os poderes de ataque disponiveis (com DON ja anexado via
             effective_power); double attack conta como 2 hits do MESMO poder
             (e o MESMO ataque -- um unico Blocker ou Counter resolve os 2
             hits dele, nao 2 blockers/counters separados).
          2. Ataques [Unblockable] NUNCA podem ser bloqueados -- sempre vao
             direto pro Leader.
          3. Os blocker do oponente (N ativos) desviam ate N ataques
             BLOQUEAVEIS -- ele escolhe bloquear os de MAIOR poder primeiro
             (sao os mais caros/dificeis de cobrir so com counter), pior caso
             pra mim.
          4. O que sobra (nao bloqueado) precisa ser coberto por counter
             conhecido/estimado do oponente. Cartas reveladas contam pelo
             valor real; slots ocultos usam estimativa por tamanho da mao.
             Sobrevive ao ataque de poder P se consegue somar counter total
             >= P - leader_power + 1.
             Distribui os counters da mao greedy: cobre primeiro os ataques
             que precisam de MENOS counter (maximiza quantos ataques
             sobrevive com o estoque de counter que tem).
          5. Lethal garantido = mesmo nessa defesa otima do oponente, a vida
             dele chega a 0 E ainda resta pelo menos 1 hit que conecta
             (regra: receber dano com 0 vidas = derrota).
        """
        opp_life = self.opp.life_count()
        leader_power = self.opp.leader.effective_power(False)

        # Ataques disponiveis: (poder_base, eh_unblockable, hits). DON
        # disponivel ainda pode ser distribuido entre eles para garantir lethal.
        ataques = []
        if not self.me.cannot_attack_leader_this_turn and not self.me.leader.rested and not is_attack_locked_self(self.me.leader, self.me, self.opp):
            ataques.append((attack_time_power(self.me.leader, self.opp),
                            self.me.leader.has_unblockable or self.me.leader.unblockable_this_turn,
                            1))
        for c in self.me.field_chars:
            if character_can_attack_now(c, self.me, self.opp):
                hits = 2 if c.is_double_attack() else 1
                ataques.append((attack_time_power(c, self.opp),
                                c.has_unblockable or c.unblockable_this_turn,
                                hits))

        if not ataques:
            return False  # sem atacantes disponiveis, nunca fecha o jogo
        counters_base = sorted(self.opp_counter_chunks_for_lethal())
        n_blockers = len(self.opp.blockers_active())
        don_total = max(0, self.me.don_available)
        target_hits = opp_life + 1 if opp_life > 0 else 1

        def hits_after_best_defense(powered_attacks):
            unblockable = [a for a in powered_attacks if a[1]]
            bloqueaveis = sorted([a for a in powered_attacks if not a[1]],
                                 key=lambda a: -a[0])
            candidatos_dano = unblockable + bloqueaveis[n_blockers:]
            if not candidatos_dano:
                return 0

            sobrou_counters = list(counters_base)
            conecta = []
            for power, _is_unblockable, hits in sorted(candidatos_dano, key=lambda a: a[0]):
                necessario = power - leader_power + 1
                if necessario <= 0:
                    continue
                soma = 0
                usados = []
                for ctr in sobrou_counters:
                    if soma >= necessario:
                        break
                    soma += ctr
                    usados.append(ctr)
                if soma >= necessario:
                    for u in usados:
                        sobrou_counters.remove(u)
                else:
                    conecta.append((power, hits))
            return sum(h for _, h in conecta)

        def search_alloc(idx: int, don_left: int, current: list):
            if idx == len(ataques):
                return hits_after_best_defense(current) >= target_hits

            base_power, unblockable, hits = ataques[idx]
            # Tenta mais DON primeiro; se houver lethal garantido, acha cedo.
            for don in range(don_left, -1, -1):
                if search_alloc(
                    idx + 1,
                    don_left - don,
                    current + [(base_power + don * 1000, unblockable, hits)],
                ):
                    return True
            return False

        return search_alloc(0, don_total, [])

    # ── Análise de defesa ────────────────────────────────────────────────────

    def opp_lethal_threat(self) -> float:
        """
        Probabilidade do oponente me finalizar no próximo turno.
        Considera atacantes, DON disponível, minha vida.
        """
        opp_attacks = self.opp_attack_count()
        my_life = self.me.life_count()
        my_blockers = len(self.me.blockers_active())
        my_counter  = self.me.counter_in_hand()

        if opp_attacks == 0:
            return 0.0

        # Oponente precisa de (my_life + 1) hits para me finalizar
        hits_needed = my_life + 1
        available_hits = opp_attacks

        if available_hits < hits_needed:
            return 0.0

        # Chance base
        prob = max(0.0, (available_hits - hits_needed + 1) / max(available_hits, 1))

        # Meus blockers reduzem a ameaça
        prob *= max(0.1, 1.0 - my_blockers * 0.2)

        # Meus counters reduzem a ameaça
        if my_counter >= 2000:
            prob *= 0.7
        elif my_counter >= 1000:
            prob *= 0.85

        return min(prob, 0.95)

    # ── Vale a pena salvar um personagem? ────────────────────────────────────

    def char_value_score(self, card: 'Card') -> float:
        """
        Valor de um personagem para a partida.
        Usado para decidir se vale gastar blocker/counter para salvar.
        """
        score = card.board_value() * 10.0

        effects = get_card_effects(card.code)

        # Tem efeito ativável que ainda não usou
        if 'activate_main' in effects:
            score += 20

        # Tem efeito de ataque
        if 'when_attacking' in effects:
            score += 15

        # É um blocker valioso
        if (card.has_blocker or card.blocker_this_turn) and self.me.life_count() <= 2:
            score += 30

        # Tem double attack
        if card.has_double_attack or card.double_attack_this_turn:
            score += 20

        return score

    # ── Análise do campo ─────────────────────────────────────────────────────

    def field_advantage(self) -> float:
        """
        Vantagem de campo: positivo = eu estou na frente.
        Considera poder total, quantidade de cartas e efeitos.
        """
        my_score  = sum(c.board_value() for c in self.me.field_chars)
        opp_score = sum(c.board_value() for c in self.opp.field_chars)
        return my_score - opp_score

    def critical_threats(self) -> list:
        """
        Identifica AMEAÇAS CRÍTICAS no board do oponente (documento nível 3).
        Uma carta é ameaça crítica se:
        - poder alto (>= 6000), OU
        - tem efeito perigoso (gera vantagem recorrente, blocker que trava ataque),
        - (a ameaça de lethal é tratada à parte por opp_lethal_threat).
        Retorna a lista de cartas-ameaça, da mais perigosa para a menos.
        """
        ameacas = []
        for c in self.opp.field_chars:
            peso = 0
            if c.power >= 6000:           peso += 3
            elif c.power >= 5000:         peso += 1
            if c.has_blocker or c.blocker_this_turn:             peso += 2   # trava meu ataque
            effects = get_card_effects(c.code)
            if 'activate_main' in effects: peso += 2   # vantagem recorrente
            if 'when_attacking' in effects: peso += 2
            if c.has_double_attack or c.double_attack_this_turn:       peso += 2
            if c.has_rush or c.rush_this_turn:                peso += 1
            if peso >= 3:
                ameacas.append((peso, c))
        ameacas.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in ameacas]

    def analysis_priority(self) -> str:
        """
        PRIORIDADE DE ANÁLISE (documento) — cascata de INCLINAÇÃO.
        Retorna o modo dominante deste momento. A ordem é respeitada (o nível
        mais alto satisfeito comanda), mas é inclinação, não bloqueio: o loop
        de pontuação ainda considera o contexto, com pesos ajustados por este modo.

        1. LETHAL      — posso vencer neste turno (sempre vence, topo)
        2. DEFENSIVE   — posso morrer no próximo turno (e não tenho lethal)
        3. REMOVE_THREAT — existe ameaça crítica no board
        4. DEVELOP     — posso/devo desenvolver board
        5. ATTACK      — atacar líder (padrão)
        """
        if self.can_lethal_this_turn():
            return 'LETHAL'
        if self.opp_lethal_threat() > 0.6:
            return 'DEFENSIVE'
        if self.critical_threats():
            return 'REMOVE_THREAT'
        # desenvolver cedo / sem pressão; senão, atacar
        don_total = self.me.don_available + self.me.don_rested
        if don_total <= 4 and self.me.hand:
            return 'DEVELOP'
        return 'ATTACK'

    def should_clear_field(self) -> bool:
        """
        Vale a pena limpar o campo do oponente?
        Sim se oponente tem cartas com efeitos importantes ou muitos atacantes.
        """
        opp_threats = 0
        for c in self.opp.field_chars:
            effects = get_card_effects(c.code)
            if any(t in effects for t in ('activate_main', 'when_attacking', 'on_ko')):
                opp_threats += 2
            else:
                opp_threats += 1
        return opp_threats >= 3 or self.opp_attack_count() >= 3


_KEYWORD_GRANTS = {
    'gain_blocker':        'has_blocker',
    'gain_rush':           'has_rush',
    'gain_rush_character': 'has_rush_character',
    'gain_double_attack':  'has_double_attack',
    'gain_banish':         'has_banish',
    'gain_unblockable':    'has_unblockable',
}


def apply_conditional_keyword_passives(gs: 'GameState', opp: 'GameState') -> None:
    """
    Liga keywords vindas de PASSIVA CONDICIONAL (ex: Mars OP13-091
    gain_blocker e Nusjuro OP13-080 gain_rush, ambos com trash_gte 7).
    _make_card so aplica keyword_* incondicional — essas NUNCA ligavam,
    entao o engine nao via o Mars como blocker nem dava Rush ao Nusjuro
    mesmo com o trash cheio (achado real 12/07, partida 23.41.50 — duas
    reclamacoes do usuario com a mesma causa raiz).

    GRANT-ONLY e idempotente: as condicoes deste padrao (trash_gte) so
    crescem durante a partida; nao ha revogacao. Chamada barata (cartas
    visiveis x lookup cacheado) feita no __init__ do DecisionEngine —
    todo ponto de decisao passa por la.
    """
    ee = EffectExecutor(gs, opp)
    pool = list(gs.field_chars) + list(gs.hand)
    if gs.leader is not None:
        pool.append(gs.leader)
    if gs.field_stage is not None:
        pool.append(gs.field_stage)
    for c in pool:
        passive = get_card_effects(c.code).get('passive', {})
        steps = passive.get('steps', [])
        grants = [s for s in steps if s.get('action') in _KEYWORD_GRANTS]
        aura_grants = [s for s in steps if s.get('action') == 'grant_rush_character_type']
        if not grants and not aura_grants:
            continue
        if not ee._check_conditions(passive.get('conditions', {}), c):
            continue
        for s in grants:
            setattr(c, _KEYWORD_GRANTS[s['action']], True)
            if s.get('action') == 'gain_rush_character' and c.just_played:
                c.rush_character_only_this_turn = True
        for s in aura_grants:
            wanted = _norm_type_text(s.get('filter_type') or '')
            for target in gs.field_chars:
                if wanted and wanted in _norm_type_text(target.sub_types):
                    target.has_rush_character = True
                    if target.just_played:
                        target.rush_character_only_this_turn = True


class DecisionEngine:
    """
    Motor de decisão com análise probabilística completa.

    Toma decisões baseado em:
    - Perfil do deck (early/mid/late)
    - Análise de lethality (posso finalizar? oponente pode me finalizar?)
    - Distribuição ótima de DON
    - Ordem de ataque estratégica
    - Decisões de defesa (blocker vs counter)
    - Gerenciamento de mão e DON reservado
    """

    def __init__(self, me: 'GameState', opp: 'GameState'):
        self.me   = me
        self.opp  = opp
        self.analyzer = GameAnalyzer(me, opp)
        # Keywords de passiva condicional (trash_gte etc.) — ver docstring
        # de apply_conditional_keyword_passives. Nos DOIS lados: a decisão
        # também precisa saber que o blocker/rush DO OPONENTE está ativo.
        apply_conditional_keyword_passives(me, opp)
        apply_conditional_keyword_passives(opp, me)

    # ── Postura ──────────────────────────────────────────────────────────────

    def posture(self) -> str:
        """
        Postura do turno = PERFIL do deck (aggressive/control/midrange) +
        FASE da partida (early/mid/late pelos DON), conforme o documento.

        - Prioridades absolutas primeiro (lethal / evitar derrota).
        - Depois o PERFIL comanda:
          * aggressive: pressiona em todas as fases (busca dano cedo)
          * control: segue a fase (early desenvolve, mid controla, late finaliza)
          * midrange: equilíbrio pela fase
        """
        a = self.analyzer
        profile = a.deck_profile_type()   # aggressive / control / midrange
        phase   = a.game_phase()          # early / mid / late (pelos DON)
        my_life  = self.me.life_count()
        opp_life = self.opp.life_count()

        # ── Prioridades absolutas (independem de perfil/fase) ──
        if a.can_lethal_this_turn():
            return 'LETHAL'
        if a.opp_lethal_threat() > 0.6:
            return 'DEFENSIVE'

        # ── Perfil AGRESSIVO: pressiona em todas as fases ──
        # (deck de curva baixa com rush/buff ataca a vida desde cedo)
        if profile == 'aggressive':
            if my_life <= 1 and a.field_advantage() < 0:
                return 'DEFENSIVE'      # só recua se realmente prestes a morrer
            return 'AGGRESSIVE'

        # ── Perfil CONTROLE: segue o padrão das fases ──
        if profile == 'control':
            if phase == 'early':
                # desenvolver e preservar (board > dano)
                if opp_life <= 1: return 'AGGRESSIVE'
                return 'DEVELOP'
            if phase == 'mid':
                # disputar board, eliminar ameaças
                if my_life <= 1: return 'DEFENSIVE'
                if a.field_advantage() < -2: return 'CONTROL'
                if opp_life <= 2: return 'AGGRESSIVE'
                return 'CONTROL'
            # late: buscar letal / finalizar
            if my_life <= 2 and a.field_advantage() < 0: return 'DEFENSIVE'
            return 'AGGRESSIVE'

        # ── Perfil MIDRANGE: equilíbrio pela fase ──
        if opp_life <= 1:   return 'AGGRESSIVE'
        if my_life <= 1:    return 'DEFENSIVE'
        if phase == 'early':
            if a.field_advantage() < -2: return 'CONTROL'
            return 'DEVELOP'
        if phase == 'mid':
            if a.field_advantage() < -3: return 'CONTROL'
            if opp_life <= 2: return 'AGGRESSIVE'
            return 'MIDRANGE'
        # late
        return 'AGGRESSIVE'

    # ── Avaliação de cartas ──────────────────────────────────────────────────

    def _counter_stat_bonus(self, card: 'Card', life_mult: bool = True) -> float:
        """
        Componente de avaliar_carta que vem do STAT de counter da carta
        (rede de seguranca na mao). Extraido como metodo proprio porque
        pitch_cost_as_counter precisa recalcular exatamente este componente
        sem o multiplicador de urgencia (life_mult=False).
        """
        if card.counter <= 0:
            return 0.0
        my_life = self.me.life_count()
        v = card.counter / 1000 * 15
        if life_mult:
            if my_life <= 1: v *= 4.0
            elif my_life <= 2: v *= 2.5
            elif my_life <= 3: v *= 1.5
        # Penaliza se já tem muitos counters na mão
        counters_em_mao = sum(1 for c in self.me.hand
                              if c.counter > 0 and c is not card)
        if counters_em_mao >= 4: v *= 0.4
        elif counters_em_mao >= 2: v *= 0.7
        return v

    def pitch_cost_as_counter(self, card: 'Card') -> float:
        """
        Quanto se PERDE gastando a carta como counter AGORA: o valor
        situacional dela, trocando o componente de counter (que inclui um
        multiplicador de urgencia por vida baixa — circular na hora de
        USAR: a carta ficaria cara demais justamente quando o counter e
        mais necessario) pela OPCAO FUTURA de counter que se abre mao ao
        gastar. Essa opcao vale o componente-base cheio com vida alta
        (muitos golpes ainda por vir — guardar tem valor real) e quase
        nada com vida 1 (defender AGORA e o proprio uso pra que a carta
        foi guardada). Um Saturn jogavel (corpo + efeito) continua caro de
        pitchar em qualquer vida; uma vanilla injogavel de 2000 counter e
        quase gratis com vida baixa (achado real 11/07: bot pitchou Saturn
        num jab 5000v5000 com vida 4 e depois recusou counter com vida 2).
        """
        my_life = self.me.life_count()
        opcao_futura = {0: 0.0, 1: 0.1, 2: 0.4, 3: 0.7}.get(my_life, 1.0)
        return max(0.0, self.avaliar_carta(card)
                   - self._counter_stat_bonus(card)
                   + self._counter_stat_bonus(card, life_mult=False) * opcao_futura)

    def avaliar_carta(self, card: 'Card', stage_redundancy: bool = True) -> float:
        """
        Avalia o valor situacional de uma carta para jogar/guardar/descartar.
        stage_redundancy=False: pula o desconto de "2a stage com stage em
        campo" — usado por stage_worth pra comparar substituicao com os
        valores CRUS dos dois lados (senao o desconto entra em dupla
        contagem e bloqueia ate upgrade legitimo).
        """
        a       = self.analyzer
        posture = self.posture()
        s       = 0.0
        my_life  = self.me.life_count()
        opp_life = self.opp.life_count()
        don_now  = self.me.don_available

        # Jogabilidade imediata -- empurrão de DESEMPATE entre cartas de
        # valor parecido, NÃO um substituto pro valor intrínseco da carta.
        # Achado #3 (multissessão, finalmente atacado 10/07): antes disso
        # tinha +40/+20/-15 (span de 55), maior que boa parte dos bônus de
        # keyword/flag abaixo -- uma vanilla barata e jogável agora (ex:
        # Saint Mjosgard, 0 de poder) pontuava ACIMA de uma bomba de custo
        # alto só injogável neste turno (ex: Five Elders, 12000 de poder),
        # mesmo a bomba tendo poder/impacto muito maior. Reduzido pra
        # span de 23 (+15/+8/-8) -- ainda favorece jogar o que cabe no DON
        # de agora quando os valores são próximos, mas não afoga mais a
        # diferença real de poder/efeito entre as opções.
        play_cost = effective_hand_play_cost(self.me, card, self.opp)
        if play_cost <= don_now:       s += 15
        elif play_cost <= don_now + 2: s += 8
        else:                          s -= 8

        s += card.power / 1000 * 5

        # Keywords
        if card.has_rush or card.rush_this_turn:
            v = 30
            if opp_life <= 2: v += 50
            if opp_life == 0: v += 100
            s += v

        if card.has_rush_character or card.rush_character_only_this_turn:
            v = 18
            if self.opp.field_chars: v += 18
            if a.should_clear_field(): v += 12
            s += v

        if card.has_double_attack or card.double_attack_this_turn:
            s += 25
            if opp_life <= 2: s += 35

        if card.has_unblockable or card.unblockable_this_turn:
            s += 20
            if opp_life <= 2: s += 30

        if card.has_banish:
            s += 15

        if card.has_blocker or card.blocker_this_turn:
            v = 20
            if my_life <= 1:   v += 100
            elif my_life <= 2: v += 60
            elif my_life <= 3: v += 30
            if a.opp_attack_count() >= 3: v += 20
            s += v

        s += self._counter_stat_bonus(card)

        if card.has_trigger:
            s += 10

        # Efeitos do banco — flags estruturadas do card_analysis_db (fonte única
        # de classificação; substituiu a detecção frágil por substring no texto).
        flags = get_card_flags(card.code)
        has_draw   = flags.get('draws', False)
        has_search = flags.get('is_searcher', False)
        has_ko     = flags.get('kos', False) or flags.get('is_removal', False)
        has_bounce = flags.get('bounces', False)
        has_rest   = flags.get('rests_opponent', False)
        has_buff   = flags.get('power_buff', False)
        has_givdon = flags.get('gives_don', False)
        has_gainlf = flags.get('gains_life', False)

        if has_draw:   s += 25 + (10 if len(self.me.hand) <= 3 else 0)
        if has_search: s += 30 + (15 if self.me.turn <= 3 else 0)
        if has_ko:
            s += 35
            if a.field_advantage() < 0: s += 25
            # remoção sem alvo vale pouco -- não pontuar KO no vácuo
            if not self.opp.field_chars: s -= 30
        if has_bounce:
            s += 20
            if a.field_advantage() < 0: s += 15
            if not self.opp.field_chars: s -= 20
        if has_rest:
            # Restar abre personagens para ataque
            if a.should_clear_field(): s += 20
            else: s += 10
        if has_buff:
            s += 15
        if has_givdon:
            s += 20
        if has_gainlf:
            v = 15
            if my_life <= 1:   v += 60
            elif my_life <= 2: v += 35
            s += v

        # Ajuste por postura
        if posture == 'LETHAL':
            if card.has_rush or card.rush_this_turn:          s += 50
            if card.has_rush_character or card.rush_character_only_this_turn: s += 20
            if card.has_double_attack or card.double_attack_this_turn: s += 40
            if card.has_unblockable or card.unblockable_this_turn:   s += 30
        elif posture == 'AGGRESSIVE':
            if card.has_rush or card.rush_this_turn:          s += 30
            if card.has_rush_character or card.rush_character_only_this_turn: s += 15
            if card.has_double_attack or card.double_attack_this_turn: s += 20
            if card.counter > 0:       s -= 10
        elif posture == 'DEFENSIVE':
            if card.has_blocker or card.blocker_this_turn:       s += 50
            if card.counter > 0:       s += 25
            if card.has_rush or card.rush_this_turn:          s -= 15
        elif posture == 'CONTROL':
            if has_ko:     s += 30
            if has_bounce: s += 20
            if has_rest:   s += 15
        elif posture == 'DEVELOP':
            if has_search: s += 25
            if has_draw:   s += 20

        # Carta CERTA do game_plan (a bomba do combo do deck, ex: Five Elders):
        # avaliar_carta hoje trata qualquer character so pelos termos genericos
        # (poder/keyword/counter) — SEM nenhuma nocao de plano, diferente de
        # `_trash_value` (que ja protege o win-con no CUSTO de trash). Sem isso,
        # um corpo mais barato com counter alto (ex: Nosjuro, 1000 counter) podia
        # pontuar ACIMA da bomba de 12000 poder em vida baixa (multiplicador de
        # panico do counter), e a bomba nunca era jogada mesmo saindo DE GRACA
        # (ex: Empty Throne "play 1 Five Elders da mao") -- achado ao vivo 14/07
        # (log 12.02.31): bot jogou Nosjuro em vez do Five Elders com 10 DON no
        # pool. Generico via compute_game_plan (zero nome de carta).
        plano_bomba = compute_game_plan(self.me)
        if plano_bomba['win_con_code'] and card.code == plano_bomba['win_con_code']:
            s += 90

        # STAGE redundante: com stage propria ja em campo, a 2a copia na
        # mao so vale o UPGRADE liquido sobre a atual — e vira o pitch mais
        # barato pra custos/counter (achado real 12/07, 23.41.50: o custo
        # do lider trashou o Mars recem-descido tendo Mary Geoise inutil
        # na mao). Guarda `is not field_stage` corta a recursao (a stage
        # de campo avalia cheia).
        if (stage_redundancy
                and card.card_type == 'STAGE' and self.me.field_stage is not None
                and card is not self.me.field_stage):
            s = max(5.0, s - self.stage_worth(self.me.field_stage))

        return s

    def stage_worth(self, stage: 'Card') -> float:
        """
        Valor de uma STAGE pra comparacao de substituicao: avaliar_carta +
        o motor recorrente de [Activate: Main] — o bonus equivalente em
        _score_play_action so existe pra CHARACTER, entao o Empty Throne
        (deploy gratis todo turno) avaliava quase nada e a Mary Geoise
        (custo 1, passiva situacional) o substituia (2x em partida real,
        12/07). Nao chamar para carta na MAO com stage em campo (avaliar
        ja desconta a redundancia nesse caso).
        """
        v = self.avaliar_carta(stage, stage_redundancy=False)
        am = get_card_effects(stage.code).get('activate_main', {})
        if am.get('steps'):
            v += 40
        return v

    # ── Escolher carta para jogar ─────────────────────────────────────────────

    def _effect_conditions_met(self, card) -> bool:
        """
        Verifica se as condições do efeito principal da carta estão satisfeitas
        no estado ATUAL. Evita jogar carta cujo efeito condicional não vai ativar
        (ex: Otama com 'life_lte:3' jogada com 4 vidas).

        Retorna True se não há condições, ou se as condições batem.
        """
        effects = get_card_effects(card.code)
        # pega o gatilho principal (on_play / main / activate_main)
        main_trig = None
        for t in ('on_play', 'main', 'activate_main'):
            if t in effects:
                main_trig = effects[t]
                break
        if not main_trig:
            return True  # sem efeito principal — sem condição a checar

        conds = main_trig.get('conditions', {})
        if not conds:
            return True

        me = self.me
        my_life  = me.life_count()
        my_hand  = len(me.hand)
        my_don   = me.don_available
        my_trash = len(me.trash)
        my_chars = len(me.field_chars)
        leader_types = set(str(getattr(me.leader, 'sub_types', '')).lower().split())

        for k, v in conds.items():
            if k == 'life_lte'  and not (my_life  <= v): return False
            if k == 'life_gte'  and not (my_life  >= v): return False
            if k == 'hand_lte'  and not (my_hand  <= v): return False
            if k == 'hand_gte'  and not (my_hand  >= v): return False
            if k == 'don_gte'   and not (my_don   >= v): return False
            if k == 'has_don_attached' and v:
                attached = getattr(me.leader, 'don_attached', 0) + sum(
                    getattr(c, 'don_attached', 0) for c in me.field_chars)
                if attached <= 0: return False
            if k == 'don_attached_total_gte':
                attached_total = getattr(me.leader, 'don_attached', 0) + sum(
                    getattr(c, 'don_attached', 0) for c in me.field_chars)
                if attached_total < v: return False
            if k == 'event_activated_cost_gte_this_turn':
                if not any(c >= v for c in me.events_activated_costs_this_turn): return False
            if k == 'don_on_field_gte' and not ((my_don + me.don_rested) >= v): return False
            if k == 'don_on_field_lte' and not ((my_don + me.don_rested) <= v): return False
            if k == 'don_on_field_zero_or_gte':
                n = my_don + me.don_rested
                if not (n == 0 or n >= v): return False
            if k == 'opp_don_on_field_gte' and not (self.opp.don_on_field() >= v): return False
            if k == 'opp_don_on_field_lte' and not (self.opp.don_on_field() <= v): return False
            if k == 'don_on_field_lte_opp' and v:
                if not (me.don_on_field() <= self.opp.don_on_field()): return False
            if k == 'don_fewer_than_opp_by_gte':
                if not (self.opp.don_on_field() - me.don_on_field() >= v): return False
            if k == 'opp_hand_gte' and not (len(self.opp.hand) >= v): return False
            if k == 'opp_chars_gte' and not (len(self.opp.field_chars) >= v): return False
            if k == 'trash_gte' and not (my_trash >= v): return False
            if k == 'trash_lte' and not (my_trash <= v): return False
            if k == 'just_played' and v and not getattr(card, 'just_played', False): return False
            if k == 'events_in_trash_gte':
                n_events = sum(1 for c in me.trash if c.card_type.lower() == 'event')
                if not (n_events >= v): return False
            if k == 'leader_power_lte':
                if not (me.leader.effective_power(True) <= v): return False
            if k == 'leader_name_includes':
                if v.lower() not in me.leader.name.lower(): return False
            if k == 'opp_rested_cards_gte':
                rested = self.opp.don_rested + sum(
                    1 for c in self.opp.field_chars if c.rested)
                rested += int(bool(getattr(self.opp.leader, 'rested', False)))
                rested += int(bool(self.opp.field_stage and getattr(
                    self.opp.field_stage, 'rested', False)))
                if rested < v: return False
            if k == 'other_char_power_gte':
                candidates = [c for c in me.field_chars if c is not card]
                ftype = conds.get('other_char_power_gte_type')
                if ftype:
                    candidates = [c for c in candidates
                                  if _norm_type_text(ftype) in _norm_type_text(c.sub_types)]
                fnames = [n.lower() for n in conds.get('other_char_power_gte_names', [])]
                if fnames:
                    candidates = [c for c in candidates
                                  if any(n in c.name.lower() for n in fnames)]
                power_of = ((lambda c: c.power) if conds.get('other_char_power_uses_base')
                            else (lambda c: c.effective_power(True)))
                if not any(power_of(c) >= v for c in candidates): return False
            if k == 'opp_char_power_gte':
                if not any(c.power >= v for c in self.opp.field_chars): return False
            if k == 'no_other_named':
                needle = v.lower()
                cost_eq = conds.get('no_other_named_cost_eq')
                outros = [c for c in me.field_chars
                          if c is not card and needle in c.name.lower()]
                if cost_eq is not None:
                    outros = [c for c in outros if c.cost == cost_eq]
                if outros: return False
            if k == 'no_char_power_gte':
                if any(c.power >= v for c in me.field_chars): return False
            if k == 'has_named_character':
                needle = v.lower()
                if not any(needle in c.name.lower() for c in me.field_chars): return False
            if k == 'own_rested_cards_gte':
                rested = me.don_rested + sum(1 for c in me.field_chars if c.rested)
                rested += int(bool(getattr(me.leader, 'rested', False)))
                rested += int(bool(me.field_stage and getattr(me.field_stage, 'rested', False)))
                if rested < v: return False
            if k in ('board_has_cost', 'board_has_cost_gte'):
                todos = list(me.field_chars) + list(self.opp.field_chars)
                exatos = set(conds.get('board_has_cost', []))
                gte = conds.get('board_has_cost_gte')
                if not any(c.cost in exatos or (gte is not None and c.cost >= gte)
                           for c in todos):
                    return False
            if k == 'chars_gte':
                cost_filter = conds.get('chars_gte_cost_filter')
                contagem = (sum(1 for c in me.field_chars if c.cost >= cost_filter)
                            if cost_filter is not None else my_chars)
                if not (contagem >= v): return False
            if k == 'chars_fewer_than_opp_by_gte':
                if not ((len(self.opp.field_chars) - my_chars) >= v): return False
            if k == 'total_chars_cost_gte':
                if not (sum(c.cost for c in me.field_chars) >= v): return False
            if k == 'leader_type':
                if str(v).lower() not in ' '.join(leader_types): return False
            if k == 'leader_is':
                if str(v).lower() not in str(getattr(me.leader, 'name', '')).lower(): return False
        return True

    def _can_play_card(self, card, don_usable: int | None = None) -> bool:
        """Decide se uma carta é jogável agora (mesma regra do choose_card_to_play)."""
        if card.card_type not in ('CHARACTER', 'EVENT', 'STAGE'):
            return False
        # Auto-restrição "cannot play this turn" (combo de ramp que trava você)
        if self.me.cant_play_from_hand_this_turn:
            return False
        if self.me.cant_play_chars_this_turn and card.card_type == 'CHARACTER':
            return False
        if self.me.cant_play_cost_gte and card.card_type == 'CHARACTER' \
                and card.cost >= self.me.cant_play_cost_gte:
            return False
        if don_usable is None:
            don_reserve = self._don_reserve_for_defense()
            don_usable  = max(0, self.me.don_available - don_reserve)
        if effective_hand_play_cost(self.me, card, self.opp) > don_usable:
            return False
        effects = get_card_effects(card.code)
        has_main = any(t in effects for t in ('on_play', 'main', 'activate_main'))
        # Eventos pure-counter (só trigger 'counter', sem 'main'): só usáveis
        # na vez do oponente via try_counter_event_*; não entram no main phase.
        # Eventos com AMBOS counter+main (ex: Ground Death, Never Existed) SÃO
        # jogáveis no main phase pelo efeito 'main'.
        if card.card_type == 'EVENT' and '[counter]' in card.card_text.lower() and not has_main:
            return False
        if card.card_type == 'EVENT' and not has_main:
            return False
        if not self._effect_conditions_met(card):
            vale_pelo_corpo = (card.card_type == 'CHARACTER' and card.power >= 5000)
            if not vale_pelo_corpo:
                return False
        return True

    def _has_don_reactive_use(self) -> bool:
        """
        Existe algum jeito real de gastar DON reservado durante o turno do
        oponente? Sem isso, reservar é desperdício puro -- melhor
        concentrar tudo no ataque (auditoria 27/06, sugestão de Arthur).

        3 fontes, em ordem de confiabilidade:
          1. Counter event na mão que EXIGE DON no próprio custo (raro --
             a maioria de [Counter] só pede trashar a carta, sem DON).
          2. Character/Leader em campo com efeito [Counter]/[Opponent's
             Turn] que pede DON!! xN -- já estruturado no banco via
             don_requirement, nada novo a parsear.
          3. Proxy de EXPECTATIVA por composição: proporção de cartas com
             counter ainda não vistas em deck+vida. NÃO espia a ordem da
             vida (isso seria cheat) -- só conta quantas das restantes,
             agregadas, têm counter. Threshold 15%, aprovado por Arthur
             como número de partida (sem dado real por arquétipo ainda --
             isso fica pra quando Opponent Reading for retomado).
        """
        me = self.me

        for c in me.hand:
            if c.card_type == 'EVENT' and '[counter]' in c.card_text.lower():
                # Conta o custo de play da carta (DON!! necessário para jogá-la)
                # OU texto explícito de DON!! no efeito (efeitos paid-activate)
                play_cost = effective_hand_play_cost(me, c, self.opp)
                if play_cost > 0:
                    return True
                if re.search(r'don!!\s*[-x]?\s*\d', c.card_text.lower()):
                    return True

        for c in list(me.field_chars) + [me.leader]:
            effects = get_card_effects(c.code)
            for timing in ('counter', 'opp_turn'):
                blk = effects.get(timing)
                if blk and blk.get('don_requirement', 0) > 0:
                    return True

        pool = me.deck + me.life
        if pool:
            com_counter = sum(1 for c in pool
                               if c.counter >= 1000 or '[counter]' in c.card_text.lower())
            if com_counter / len(pool) >= 0.15:
                return True

        return False

    def _don_reserve_for_defense(self) -> int:
        """
        Quantos DON reservar para defesa no turno do oponente.
        Decisão baseada na ANÁLISE DE RISCO (regra do usuário):
        - Em PERIGO (pouca vida, ameaça alta, pouco counter na mão, ou tenho
          evento counter que preciso deixar DON em pé para usar) -> reserva mais.
        - SEGURO (muito counter na mão, blockers, vida alta, sem risco de perder
          no próximo turno) -> reserva pouco/nada, força ataque.
        """
        # Sem NENHUM jeito real de gastar DON na defesa, reservar é só
        # perder poder de ataque de graça -- corta aqui antes de qualquer
        # análise de ameaça/vida.
        if not self._has_don_reactive_use():
            return 0

        a = self.analyzer
        my_life = self.me.life_count()
        threat  = a.opp_lethal_threat()
        don_disp = self.me.don_available

        # Recursos defensivos que JÁ tenho na mão/campo
        counters_mao = sum(1 for c in self.me.hand if getattr(c, 'counter', 0) >= 1000)
        eventos_counter = sum(1 for c in self.me.hand
                              if c.card_type == 'EVENT' and '[counter]' in c.card_text.lower())
        blockers = len(self.me.blockers_active())

        # ── Estou SEGURO? muito counter + blocker + vida ok + sem ameaça ──
        seguro = (counters_mao >= 3 and my_life >= 3 and threat < 0.4) or \
                 (blockers >= 2 and my_life >= 4 and threat < 0.4)
        if seguro:
            return 0   # força ataque, não precisa guardar DON

        # ── Estou em PERIGO? reserva conforme a gravidade ──
        reserva = 0
        if threat > 0.7:        reserva = 3
        elif threat > 0.4:      reserva = 2
        elif my_life <= 2:      reserva = 2
        elif my_life <= 3:      reserva = 1

        # Tenho evento counter mas POUCO counter de mão? vale deixar DON p/ o evento
        if eventos_counter >= 1 and counters_mao <= 1 and my_life <= 3:
            reserva = max(reserva, 1)

        # Pouco counter na mão aumenta o risco de não conseguir defender
        if counters_mao == 0 and my_life <= 3:
            reserva = max(reserva, 1)

        return min(reserva, don_disp)

    def _can_spend_reserved_don_for_play(self, card) -> bool:
        """
        Reserva defensiva nao deve remover automaticamente uma jogada premium
        da lista de candidatas. O Turn Planner ainda compara a linha; aqui so
        deixamos o candidato existir.
        """
        if effective_hand_play_cost(self.me, card, self.opp) > self.me.don_available:
            return False
        return card.card_type == 'CHARACTER' and (card.cost >= 8 or card.power >= 9000)

    def _don_usable_for_play(self, card, don_reserve: int | None = None) -> int:
        if don_reserve is None:
            don_reserve = self._don_reserve_for_defense()
        don_usable = max(0, self.me.don_available - don_reserve)
        if effective_hand_play_cost(self.me, card, self.opp) > don_usable \
                and self._can_spend_reserved_don_for_play(card):
            return self.me.don_available
        return don_usable

    # ── Distribuição de DON ───────────────────────────────────────────────────

    # ── Ordem e escolha de ataques ────────────────────────────────────────────

    def _rest_activates_effect(self, card) -> bool:
        """
        Decide se restar este personagem (atacando) ativa um efeito útil,
        justificando o ataque mesmo sem chance de passar.

        Verdadeiro quando:
        - tem [When Attacking] que vai produzir efeito real agora (checado
          via _step_is_viable -- achado real 10/07: antes bastava TER a
          chave when_attacking, sem checar se o efeito tem alvo/material.
          Catarina Devon "select 1 personagem do oponente, copia o poder"
          contava como "vale atacar mesmo sem chance de passar" mesmo com
          o campo do oponente VAZIO -- o bot declarava um ataque de 3000
          contra lider de 5000 sem nenhum beneficio real, so por ter a
          chave presente), OU
        - tem efeito [Your Turn]/[Opponent's Turn] que depende de estar restado
          (ex: Shanks — restado dá -1000 a todos os personagens do oponente).
        """
        effects = get_card_effects(card.code)
        wa = effects.get('when_attacking')
        if wa:
            steps = wa.get('steps', [])
            # Sem steps parseados (so texto cru): mantem comportamento antigo,
            # nao ha como checar viabilidade sem estrutura. _step_is_viable e
            # metodo de EffectExecutor, nao de DecisionEngine -- instancia
            # local so pra essa checagem (mesmo padrao usado em
            # _should_activate_main).
            if not steps:
                return True
            ee = EffectExecutor(self.me, self.opp)
            if any(ee._step_is_viable(s, card) for s in steps):
                return True
        # efeitos que se beneficiam de estar restado
        txt = (card.card_text or '').lower()
        if ('when this character becomes rested' in txt or
                'if this character is rested' in txt or
                'while this character is rested' in txt):
            return True
        return False

    def score_attack_target(self, attacker: 'Card',
                             target_type: str,
                             target: 'Optional[Card]') -> float:
        """
        Pontua um alvo de ataque levando em conta múltiplos fatores.
        """
        a = self.analyzer
        s = 0.0
        opp_life  = self.opp.life_count()
        # Poder NO ATAQUE: inclui buffs de [When Attacking] proprios
        # (ex: Devon OP16-104 copia o poder de um personagem do oponente)
        atk_power = attack_time_power(attacker, self.opp)

        # Custo de restar um atacante que tem [Activate: Main] útil:
        # atacar com ele perde o efeito do turno. Desconta, salvo letal/ameaça grande.
        activate_cost = self._activate_main_value(attacker)

        if target_type == 'leader':
            don_disp  = self.me.don_available
            leader_power = self.opp.leader.power

            # REGRA DURA (validada com o usuário):
            # Ataque ao líder só vale se:
            #  (a) poder do atacante >= poder-base do líder (passa sem DON), OU
            #  (b) poder + DON disponível >= poder-base do líder (passa com DON), OU
            #  (c) restar o personagem ativa um efeito útil (When Attacking, ou
            #      efeito Your Turn/Opp Turn que depende de estar restado).
            passa_sem_don = atk_power >= leader_power
            passa_com_don = (atk_power + don_disp * 1000) >= leader_power
            vale_restar   = self._rest_activates_effect(attacker)

            if not (passa_sem_don or passa_com_don or vale_restar):
                return -999  # ataque inútil: não passa e não ativa nada — barra

            # Pontua os ataques validos. Vida 0/1 so vira prioridade maxima
            # quando o conjunto de ataques realmente garante lethal; com
            # blockers/counters suficientes, atacar leader ainda e pressao,
            # mas nao deve soterrar as outras acoes.
            lethal_now = a.can_lethal_this_turn()
            s = 100
            if opp_life == 1:
                s = 500 if lethal_now else 220
            if opp_life == 0:
                s = 10000 if lethal_now else 130

            # Bônus se restar ativa efeito (vale mesmo sem dano)
            if vale_restar and not passa_sem_don:
                s = max(s, 80)

            # Penaliza levemente se precisa de muito DON (mas ainda é válido)
            opp_defense = leader_power + a.opp_counter_potential()
            if atk_power < opp_defense and not passa_sem_don:
                s -= 10

            # Unblockable: o ataque não pode ser bloqueado. Vale mais quando o
            # oponente tem blockers (passa onde os outros seriam interceptados).
            if (attacker.has_unblockable or attacker.unblockable_this_turn) and self.opp.blockers_active():
                s += 40

            # Custo de perder o Activate Main: desconta, salvo se for letal
            if activate_cost > 0 and opp_life > 1:
                s -= activate_cost
            return s

        elif target_type == 'character' and target:
            don_disp = self.me.don_available
            # REGRA DURA (mesma do líder, validada com o usuário):
            # só ataca personagem se:
            #  (a) poder >= poder do alvo (mata sem DON), OU
            #  (b) poder + DON disponível >= poder do alvo (mata com DON), OU
            #  (c) restar o atacante ativa efeito útil.
            passa_sem_don = atk_power >= target.power
            passa_com_don = (atk_power + don_disp * 1000) >= target.power
            vale_restar   = self._rest_activates_effect(attacker)

            if not (passa_sem_don or passa_com_don or vale_restar):
                return -999   # não mata e não ativa nada — barra

            # Valor do alvo (quão importante é removê-lo)
            s = target.board_value() * 15

            # Alvo COM EFEITO vale matar mesmo com poder baixo/0 (regra do usuário)
            tgt_effects = get_card_effects(target.code)
            tem_efeito_alvo = any(t in tgt_effects for t in
                                  ('on_play', 'activate_main', 'when_attacking',
                                   'blocker', 'on_ko', 'your_turn', 'opp_turn'))
            if tem_efeito_alvo and target.power <= 2000:
                s += 50   # remover utilidade do oponente vale, apesar do poder baixo

            # Alvo cujo efeito AMEAÇA (pune no turno do oponente, ativa vantagem
            # recorrente, ou bloqueia): remover nega a ameaça futura. Vale mais.
            efeito_ameaca = any(t in tgt_effects for t in
                                ('opp_turn', 'activate_main', 'blocker'))
            if efeito_ameaca:
                s += 70   # negar ameaça futura do oponente

            # Prioriza ameaças (ordem de prioridade de alvos do documento)
            if target.has_double_attack or target.double_attack_this_turn:  s += 50
            if target.has_rush or target.rush_this_turn:           s += 40
            if target.has_blocker or target.blocker_this_turn:        s += 60
            if 'when_attacking' in tgt_effects: s += 35
            if 'activate_main' in tgt_effects:  s += 25
            if 'on_ko' in tgt_effects:          s -= 20  # cuidado: ativa ao morrer

            # Bônus se restar ativa efeito (vale mesmo sem matar)
            if vale_restar and not passa_sem_don:
                s = max(s, 60)

            # Custo de perder o Activate Main do ATACANTE: só compensa se o alvo
            # é ameaça grande (poder alto, blocker, rush, gera vantagem).
            ameaca_grande = (target.power >= 5000 or target.has_blocker or target.blocker_this_turn or
                             target.has_rush or target.rush_this_turn or target.has_double_attack or target.double_attack_this_turn)
            if activate_cost > 0 and not ameaca_grande:
                s -= activate_cost

            return s

        return s

    def _activate_main_value(self, card) -> float:
        """
        Valor do efeito [Activate: Main] de um personagem — o "custo" de restá-lo
        atacando (perde o efeito do turno). 0 se não tem efeito ativável OU se a
        condição do efeito NÃO está satisfeita agora (não há o que preservar:
        regra do usuário — se não pode ativar, ataca normalmente).
        """
        effects = get_card_effects(card.code)
        am = effects.get('activate_main')
        if not am:
            return 0.0
        # Se o efeito não pode ativar agora (condição não satisfeita), não há
        # nada a preservar — custo zero, a IA pode atacar com ela.
        if not self._effect_conditions_met(card):
            return 0.0
        # Respeita once_per_turn: se já usou, não há efeito a preservar neste turno
        if am.get('once_per_turn') and getattr(card, '_am_used_turn', -1) == self.me.turn:
            return 0.0
        # So existe custo real se a habilidade EXIGE a carta ativa (rest_self).
        # Sem isso, atacar nao impede usar o Activate:Main no mesmo turno --
        # achado 09/07 (log 18.39.46): o lider Imu (trash_char_or_hand -> draw,
        # SEM rest_self) sofria esse desconto como se atacar custasse a
        # habilidade, quando as duas coisas sao independentes. Descontava
        # score de ataque do lider ate ficar negativo e o turno terminava com
        # DON parado e nada mais pra fazer com ele.
        if not any(c.get('type') == 'rest_self' for c in am.get('costs', [])):
            return 0.0
        steps = am.get('steps', [])
        actions = [s.get('action') for s in steps]
        if any(x in ('draw', 'look_top_deck', 'add_to_hand') for x in actions):
            return 70.0
        return 40.0

    # ── Decisões de defesa ────────────────────────────────────────────────────

    def should_use_blocker(self, attacker_power: int) -> 'Optional[Card]':
        """
        Decide se usa blocker e qual usar.

        Fatores:
        - Valor da minha vida (poucos = mais defensivo)
        - Probabilidade de trigger na vida
        - Valor do personagem que está sendo atacado vs valor do blocker
        """
        a = self.analyzer
        my_life = self.me.life_count()
        opp_life = self.opp.life_count()

        # Com muita vida, não usa blocker
        if my_life > 4:
            return None

        blockers = self.me.blockers_active()
        if not blockers:
            return None

        # Analisa se vale usar blocker
        # Quanto mais baixa a vida, mais agressivo na defesa
        use_threshold = {5: False, 4: False, 3: True, 2: True, 1: True}
        if not use_threshold.get(my_life, True):
            # Com 4 vidas e oponente pressionando (≤ 2 vidas), vale bloquear
            if opp_life > 2:
                return None

        # Com 1-2 vidas, sempre usa blocker se tiver
        if my_life <= 2:
            return min(blockers, key=lambda c: a.char_value_score(c))

        # Com 3 vidas, usa se o atacante é forte
        if my_life == 3 and attacker_power >= self.me.leader.power:
            return min(blockers, key=lambda c: a.char_value_score(c))

        # Com 4 vidas e oponente com ≤ 2 vidas: bloqueia apenas atacantes fortes
        if my_life == 4 and opp_life <= 2 and attacker_power >= self.me.leader.power:
            return min(blockers, key=lambda c: a.char_value_score(c))

        return None

    def pick_counters(self, needed: int,
                      pool: 'list[tuple[int, Card]] | None' = None
                      ) -> tuple[list['Card'], float, int]:
        """
        Escolhe o conjunto de counters que cobre `needed` MINIMIZANDO o
        valor perdido (pitch_cost_as_counter), nao o stat de counter.
        pool: [(valor_de_counter, carta)] — por padrao os personagens com
        stat impresso na mao; sim_bridge passa um pool maior incluindo
        EVENTOS [Counter] elegiveis.
        Retorna (cartas, gasto, total_coberto). total < needed = nao cobre
        (cartas vem vazias nesse caso — nunca counter parcial).
        Guloso por pitch crescente + alternativa de carta unica: cobre o
        caso "uma carta grande barata de pitchar vale mais que tres
        pequenas caras" sem precisar de knapsack completo.
        """
        if pool is None:
            pool = [(c.counter, c) for c in self.me.hand if c.counter > 0]
        if needed <= 0 or not pool:
            return [], 0.0, 0

        custo = {id(c): self.pitch_cost_as_counter(c) for _, c in pool}
        # pitch menor primeiro; empate = counter maior (cobre mais rapido)
        ordenado = sorted(pool, key=lambda item: (custo[id(item[1])], -item[0]))
        escolha, gasto, total = [], 0.0, 0
        for valor, c in ordenado:
            if total >= needed:
                break
            escolha.append(c)
            gasto += custo[id(c)]
            total += valor
        if total < needed:
            return [], 0.0, total

        # Alternativa: UMA carta que cobre sozinha por gasto menor
        singles = [(custo[id(c)], valor, c) for valor, c in pool if valor >= needed]
        if singles:
            g1, v1, c1 = min(singles, key=lambda t: t[0])
            if g1 < gasto:
                return [c1], g1, v1
        return escolha, gasto, total

    def buff_wins_combat(self, defender_power: int, threat_power: int,
                         buffed_power: int) -> bool:
        """
        Regra de COMBATE do OPTCG (motor unico): um defensor so sobrevive a uma
        ameaca se ficar ESTRITAMENTE acima -- EMPATE vai pro ATACANTE. Decide se
        um buff de poder (counter/reacao) SALVA quem esta/ficara sob ataque:
        `defender_power <= threat_power < buffed_power`. Generica (so numeros),
        serve pra QUALQUER carta/lider de qualquer deck. Consolidada aqui pra o
        sim_bridge (ordenacao de alvo de buff) NAO ter regua propria -- antes as
        duas checagens divergiam (`<` vs `<=`) e o buff ia pro corpo errado no
        empate (Ground Death, log 21.01.22).
        """
        return defender_power <= threat_power < buffed_power

    def debuff_flips_attack_in_my_favor(self, target_power: int, debuff_amount: int,
                                        my_attacker_power: int) -> bool:
        """
        Espelho de `buff_wins_combat`, do lado OFENSIVO: eu sou o ATACANTE
        (empate ja favorece MIM), entao um debuff no DEFENSOR vira o combate a
        meu favor se ele cair pra <= meu poder: `target_power - debuff <=
        my_attacker_power`. Motor unico, generico (so numeros) -- decide se um
        debuff [When Attacking] (ex: Nosjuro) deve mirar o alvo do MEU proprio
        ataque em vez de "a maior ameaca ativa" generica, que ignorava o
        combate em andamento (achado ao vivo 14/07, log 12.02.31: Nosjuro
        atacando Law 9000 com 7000 de poder debuffou Hawkins, sem ligacao
        nenhuma com esse ataque).
        """
        return target_power - debuff_amount <= my_attacker_power

    def would_lose_last_defender(self, p, card) -> bool:
        """
        Trashar/perder `card` deixa p SEM defensor real? = e o ultimo corpo E
        ele de fato defende (body_provides_defense). Motor unico decide se vale
        proteger o "ultimo corpo" no custo de trash; generico, sem nome de
        carta (log 01.23.31: corpo morto nao conta como ultimo defensor).
        """
        return len(p.field_chars) <= 1 and self.body_provides_defense(card)

    def body_provides_defense(self, card) -> bool:
        """
        Um personagem em campo oferece valor DEFENSIVO real (segura um golpe)?
        So com poder > 0 OU Blocker. Corpo de 0 poder sem blocker (ex: enabler
        ja usado) nao protege o lider de nada -- generico, sem nome de carta.
        Usado pra o custo de trash nao "proteger" um corpo morto como se fosse
        ultimo defensor (log 01.23.31).
        """
        if card is None:
            return False
        return (getattr(card, 'power', 0) > 0
                or getattr(card, 'has_blocker', False)
                or getattr(card, 'blocker_this_turn', False))

    def trash_cost_board_perda(self, card, p) -> float:
        """
        Custo situacional de trashar `card` do MEU campo pra pagar um custo de
        trash (draw do lider Imu, etc.). Motor unico, generico (zero nome de
        carta). Um corpo DEAD-WEIGHT (sem valor defensivo E que ja passou o
        turno de entrada -> 0 poder parado, nao ataca nem defende, on-play ja
        gasto) e o MAIS BARATO de largar: perda minima, pra vir antes de cartas
        da MAO (que guardam opcionalidade). Antes o corpo morto "sobrevivia"
        porque a comparacao cruzava duas reguas (char_value_score no campo vs
        _trash_value na mao) e um stage redundante da mao pontuava mais baixo --
        o lider trashava a mao e mantinha a Shalria morta no campo a partida
        toda (achado ao vivo 14/07, logs 01.23.31 e 02.34.18).
        """
        if card is None:
            return 0.0
        # dead weight = sem valor defensivo (0 poder, sem blocker) E sem efeito
        # ATIVO futuro (when_attacking/activate_main). Um corpo assim nao ataca,
        # nao defende e nao vai fazer nada -- mesmo RECEM-JOGADO (o on-play ja
        # resolveu na entrada). Largar nao perde nada -> trasha PRIMEIRO, antes
        # de cartas da mao. (So poder>0/blocker/efeito futuro merece o just_played
        # +35 abaixo; Shalria de 0 poder so tinha on_play.)
        if not self.body_provides_defense(card):
            _eff = get_card_effects(card.code)
            _tem_futuro = bool(_eff.get('when_attacking', {}).get('steps')
                               or _eff.get('activate_main', {}).get('steps'))
            if not _tem_futuro:
                return -999.0
        perda = self.analyzer.char_value_score(card)
        if getattr(card, 'just_played', False):
            perda += 35            # recem-entrado: corpo+efeito a realizar
        if card.has_blocker or getattr(card, 'blocker_this_turn', False):
            perda += 25            # defesa recorrente
        if self.would_lose_last_defender(p, card):
            perda += 40            # ultimo defensor real: lider exposto
        return perda

    def should_use_counter(self, atk_power: int, def_power: int,
                           counter_avail: int | None = None,
                           gasto: float | None = None) -> bool:
        """
        Decide se countera um ataque no LIDER por GANHO LIQUIDO (regra do
        usuario: caso a caso, nunca threshold fixo por categoria):
        countera se o CUSTO das cartas gastas (pitch_cost_as_counter, que
        desconta o proprio papel de counter) fica ABAIXO do valor da vida
        que o golpe tiraria (life_redirect_cost — mesma regua ja usada em
        redirect/reaction). Substitui os gates fixos por faixa de vida
        (achado real 11/07, duas pontas do mesmo bug: com 4 vidas gastava
        counter em jab 5000v5000 [needed=1 passava no gate <=1000]; com
        menos vida recusava ataque serio porque needed>2000 estourava o
        gate da faixa — mesmo com +2000/+1000 na mao cobrindo).

        counter_avail/gasto: override de quem ja montou o pool completo
        (sim_bridge inclui eventos [Counter], que counter_in_hand() nao
        enxerga). Sem override, calcula dos personagens da mao via
        pick_counters (mesma selecao que use_counter executa).
        """
        if atk_power < def_power:
            return False  # defesa já suficiente
        needed = atk_power - def_power + 1
        my_life = self.me.life_count()

        if counter_avail is None or gasto is None:
            _, gasto, total = self.pick_counters(needed)
            counter_avail = total

        if counter_avail < needed:
            return False  # nunca counter parcial

        # Vida 0: qualquer golpe no líder = derrota. Paga o que for.
        if my_life <= 0:
            return True

        # Valor da vida na ESCALA do avaliar_carta (que roda bem mais
        # quente que a de char_value_score usada por life_redirect_cost —
        # um corpo jogavel de custo 5 avalia 100-150). Curva ingreme de
        # proposito, casada com o feedback real das duas pontas (11/07):
        # 4+ vidas = golpe barato de tomar, nao gasta nem carta lixo;
        # <=2 vidas = countera ate pitchando corpo bom (so nao entrega a
        # win-con, que avalia acima de 150 com a protecao do GamePlan).
        valor_vida = {1: 250.0, 2: 150.0, 3: 65.0}.get(my_life, 12.0)
        # MAO GORDA: com 6+ cartas o valor marginal de cada carta cai (nao
        # da pra jogar tudo) e counter fica proporcionalmente barato —
        # feedback real 12/07: "8 cartas na mao e levando dano toda hora".
        # +8 de orcamento por carta acima de 5 (mao 8 com 4+ vidas: 12->36,
        # cobre pitchar carta fraca num jab; nao chega perto de corpo bom).
        folga = len(self.me.hand) - 5
        if folga > 0:
            valor_vida += 8.0 * min(folga, 5)
        return gasto < valor_vida

    def use_counter(self, needed: int) -> int:
        """
        Usa counters cobrindo `needed` com o MENOR valor perdido (mesma
        selecao de pick_counters que should_use_counter usou pra decidir
        — as duas pontas nao podem divergir).
        """
        escolha, _, total = self.pick_counters(needed)
        for c in escolha:
            remove_by_identity(self.me.hand, c)
            self.me.trash.append(c)
            self.me.counters_used += c.counter
        return sum(c.counter for c in escolha)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def choose_to_trash(self, hand: list) -> 'Optional[Card]':
        """Escolhe a carta de menor valor situacional para descartar."""
        if not hand:
            return None
        return min(hand, key=self.avaliar_carta)



# ===========================================================================
# OPTCGMatch — motor de partida
# Baseado no fluxo de turno das 34k linhas
# ===========================================================================

class OPTCGMatch:
    MAX_TURNS = 15

    def __init__(self, deck_a: tuple, deck_b: tuple):
        leader_a, cards_a, stage_a = deck_a if len(deck_a) == 3 else (*deck_a, None)
        leader_b, cards_b, stage_b = deck_b if len(deck_b) == 3 else (*deck_b, None)

        self.state_a = GameState(leader=deepcopy(leader_a),
                                 deck=[deepcopy(c) for c in cards_a])
        self.state_b = GameState(leader=deepcopy(leader_b),
                                 deck=[deepcopy(c) for c in cards_b])

        # full_deck_census (curva completa do deck, base do posture()
        # aggressive/control/midrange): achado 14/07 (pedido do usuario --
        # parar de so consertar o Imu) -- este campo NUNCA era populado em
        # lugar nenhum do motor (so em replay_optcg.py, uma ferramenta de
        # visualizacao isolada). posture() SEMPRE caia no fallback 'midrange'
        # pra QUALQUER deck, sempre, offline e ao vivo -- a logica aggressive/
        # control ja existia e ja era boa (curva calibrada com decks reais do
        # Limitless), so nunca recebia dado nenhum. Aqui e trivial: a decklist
        # completa ja e conhecida (cards_a/cards_b).
        self.state_a.full_deck_census = deck_census(cards_a)
        self.state_b.full_deck_census = deck_census(cards_b)

        # full_deck_plan (win_con_code/don_target/trash_target) e
        # full_deck_profile (arquetipo+eixos+papeis, deck_profile.py):
        # MESMO principio do census acima, pedido explicito do usuario
        # 14/07 -- "o bot tem que ler arquetipo/papeis/eixos antes da
        # partida e guardar na memoria pra toda decisao lembrar", como um
        # jogador humano conhece o proprio deck desde o T1, nao so o que ja
        # comprou. Calculado UMA VEZ do deck INTEIRO (cards_a/cards_b, ja
        # conhecidos aqui), nao das zonas reveladas -- compute_game_plan/
        # deck_profile_for preferem esses campos quando presentes (ver
        # docstrings). Custo desprezivel (~50 cartas, 1x por partida).
        self.state_a.full_deck_plan = compute_game_plan_from_cards(cards_a)
        self.state_b.full_deck_plan = compute_game_plan_from_cards(cards_b)
        if _build_profile_from_codes is not None:
            try:
                self.state_a.full_deck_profile = _build_profile_from_codes(
                    [c.code for c in cards_a] + [leader_a.code])
                self.state_b.full_deck_profile = _build_profile_from_codes(
                    [c.code for c in cards_b] + [leader_b.code])
            except Exception:
                self.state_a.full_deck_profile = None
                self.state_b.full_deck_profile = None

        if random.random() < 0.5:
            self.state_a.is_first = True
            self.state_b.is_first = False
        else:
            self.state_a.is_first = False
            self.state_b.is_first = True

        self.global_turn = 0
        # replay_log: lista de eventos estruturados gerados durante a partida.
        # None = modo normal (sem logging extra). Definida para uma lista vazia
        # por simulate_replay() antes de chamar setup()+play_turn().
        self.replay_log: list | None = None
        self._suppress_replay_log: bool = False
        # nomes dos jogadores para o replay (preenchidos por simulate_replay)
        self._name_a = 'Player A'
        self._name_b = 'Player B'
        # decision_log: lista de registros de auditoria de decisão.
        # None = desligado. Ligado via enable_decision_audit().
        self.decision_log: list | None = None

        # OpponentModel de cada lado: construído a partir da decklist
        # COMPLETA do ADVERSÁRIO (state_a usa o deck de state_b para saber
        # contra o que está jogando, e vice-versa) -- a decklist completa é
        # sempre conhecida neste produto (colada pelo usuário ou carregada
        # de meta_decklists/user_decks), nunca estimada por arquétipo.
        # Usado por _simulate_sequence via DecisionEngine para substituir a
        # mão/vida REAL do oponente por amostras Monte Carlo plausíveis.
        self.model_for_a = OpponentModel(full_decklist=list(self.state_b.deck))
        self.model_for_b = OpponentModel(full_decklist=list(self.state_a.deck))

    def _human_pattern_bonus(self, p: GameState, kind: str, card: Optional[Card]) -> float:
        """Pequeno bonus por padroes humanos observados para este leader."""
        if card is None or not p or not p.leader:
            return 0.0
        _load_human_patterns()
        if not _HUMAN_PATTERN_BONUS_BY_LEADER:
            return 0.0
        leader_bonus = _HUMAN_PATTERN_BONUS_BY_LEADER.get(p.leader.code, {})
        return float(leader_bonus.get((kind, card.code), 0.0))

    # ── Setup (CheckStartOfGameActions das 34k linhas) ───────────────────────

    def _place_start_stage(self, p: GameState, opp: GameState = None):
        """
        Coloca o Stage inicial (proc.StartOfGame). Para leaders que puxam um Stage
        do deck no início (ex: Imu — "play up to 1 [Mary Geoise] type Stage").

        Escolha condicional ao matchup (regra confirmada por Arthur):
          - Default: o Stage de MAIOR custo (ex: The Empty Throne) — mais valor.
          - Stage de MENOR custo (Mary Geoise barata) SE:
              (a) MIRROR — oponente é o mesmo leader (sempre tem como atacar Stage alto), OU
              (b) o deck do oponente contém remoção de Stage que ALCANÇA o Stage caro
                  (K.O./trash/return de Stage do oponente com custo >= custo do Stage caro).
          Ver deck do oponente no setup é legítimo (decklist é conhecida nas 3 análises;
          só a MÃO não pode ser vista).
        """
        rule = next((r for r in get_card_game_rules(p.leader.code)
                     if r.get('type') == 'start_stage_from_deck'), None)
        if not rule:
            return
        wanted = str(rule.get('filter_type', '')).lower()

        candidates = [c for c in p.deck if c.card_type == 'STAGE'
                      and (not wanted or wanted in c.sub_types.lower()
                           or wanted in c.name.lower())]
        if not candidates:
            return

        caro = max(candidates, key=lambda c: c.cost)
        barato = min(candidates, key=lambda c: c.cost)

        usar_barato = False
        if caro.cost != barato.cost and opp is not None:
            # (a) mirror
            if opp.leader.code == p.leader.code:
                usar_barato = True
            # (b) oponente remove Stage com alcance >= custo do Stage caro
            elif self._opp_can_remove_stage(opp, caro.cost):
                usar_barato = True

        best = barato if usar_barato else caro
        remove_by_identity(p.deck, best)
        p.field_stage = best

    @staticmethod
    def _opp_can_remove_stage(opp: GameState, reach_cost: int) -> bool:
        """True se o deck do oponente tem carta que K.O./trasha/devolve um Stage
        do oponente (= nosso) com alcance de custo >= reach_cost."""
        for c in opp.deck:
            t = (c.card_text or '').lower()
            # K.O./trash explicito do "opponent's stage", respeitando filtro de custo
            for mm in re.finditer(r"(k\.?o\.?|trash)[^.]*?opponent's stages?(?:[^.]*?cost of (\d+) or less)?", t):
                cap = mm.group(2)
                if cap and int(cap) < reach_cost:
                    continue
                return True
            # return stage to owner (bounce), sem filtro baixo
            for mm in re.finditer(r"return[^.]*?\bstages?\b[^.]*?to (?:its|the) owner", t):
                seg = t[max(0, mm.start() - 15):mm.end()]
                if 'this stage' in seg:
                    continue
                cm = re.search(r'cost of (\d+) or less', seg)
                if cm and int(cm.group(1)) < reach_cost:
                    continue
                return True
        return False

    def _mulligan_decision(self, hand, deck=None) -> tuple:
        """
        Decide mulligan seguindo o documento (pág. 2) e as regras do usuário.
        Chamado por replay_optcg.ReplayMatch.setup().

        Avalia (contagem simples — sinais bons vs ruins):
        - Jogada para T1/T2/T3: consigo aproveitar o DON de cada turno com as
          cartas baratas da mão? (não é 1 carta — é gastar o DON do turno)
        - Trigger demais na mão: relativo a quantos o deck tem (triggers valem
          mais na vida; ter muitos na mão desperdiça)
        - Tem searcher (bom: busca peça)
        - Tem ramp de DON (bom: acelera)
        - Counter de menos (ruim: sem defesa)
        Se sinais ruins > bons -> mulligan.
        """
        from optcg_engine.deck_census import deck_census
        non_leader = [c for c in hand if c.card_type != 'LEADER']
        custos = sorted(c.cost for c in non_leader)

        bons, ruins, motivos = 0, 0, []

        def aproveita_don(don_disp):
            restante = don_disp
            usadas = 0
            for c in custos:
                if c <= restante and c > 0:
                    restante -= c
                    usadas += 1
            return usadas > 0

        t1 = aproveita_don(1)
        t2 = aproveita_don(3)
        t3 = aproveita_don(5)
        jogadas_cedo = sum([t1, t2, t3])
        if jogadas_cedo >= 2:
            bons += 1
            motivos.append(f'curva ok (T1:{"s" if t1 else "n"} T2:{"s" if t2 else "n"} T3:{"s" if t3 else "n"})')
        else:
            ruins += 1
            motivos.append('mao lenta (sem jogadas para os primeiros turnos)')

        tem_searcher = any(getattr(c, 'is_searcher', False) or 'search' in c.card_text.lower()
                           for c in non_leader)
        if tem_searcher:
            bons += 1; motivos.append('tem searcher')

        tem_ramp = any('don' in c.card_text.lower() and
                       ('add' in c.card_text.lower() or 'active' in c.card_text.lower())
                       for c in non_leader)
        if tem_ramp:
            bons += 1; motivos.append('tem ramp de DON')

        if deck:
            census = deck_census(deck)
            trig_no_deck = max(1, census['trigger'])
            trig_na_mao = sum(1 for c in non_leader if getattr(c, 'has_trigger', False))
            if trig_na_mao >= 2 and trig_na_mao >= trig_no_deck * 0.5:
                ruins += 1
                motivos.append(f'trigger demais na mao ({trig_na_mao} de {trig_no_deck} do deck)')

        counters_mao = sum(1 for c in non_leader if getattr(c, 'counter', 0) >= 1000)
        if counters_mao == 0:
            ruins += 1; motivos.append('sem counter na mao')

        deve_trocar = ruins > bons
        resumo = '; '.join(motivos)
        return deve_trocar, resumo

    def setup(self):
        """
        Setup inicial conforme sequência das 34k linhas:
        CheckStartOfGameActions → DrawCard(5) → OfferMulligan → StartGame
        """
        for p in [self.state_a, self.state_b]:
            don_rule = next((r for r in get_card_game_rules(p.leader.code)
                             if r.get('type') == 'don_deck_size'), None)
            p.don_deck = int(don_rule['count']) if don_rule else 10
            random.shuffle(p.deck)

        # Regra oficial: efeitos "at the start of the game" resolvem depois
        # de definir o primeiro jogador, mas antes da mao inicial.
        ordered = ([self.state_a, self.state_b] if self.state_a.is_first
                   else [self.state_b, self.state_a])
        for p in ordered:
            opp_state = self.state_b if p is self.state_a else self.state_a
            self._place_start_stage(p, opp_state)

        for p in [self.state_a, self.state_b]:
            p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]

            # Mulligan se mão sem cartas de custo <= 2
            if not any(c.cost <= 2 for c in p.hand if c.card_type != 'LEADER'):
                p.deck.extend(p.hand)
                random.shuffle(p.deck)
                p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]

            life_count = p.leader.life if p.leader.life > 0 else 5
            p.life = [p.deck.pop() for _ in range(min(life_count, len(p.deck)))]


    # ── Fases do turno ───────────────────────────────────────────────────────

    def refresh_phase(self, p: GameState, opp: 'GameState | None' = None):
        """
        PlayerUntap das 34k linhas:
        - Retorna DON dado a cartas
        - Reseta rested/just_played/power_buff
        - Reseta once_per_turn
        - Reseta travas de ataque/rest/blocker (cannot_attack_until,
          cannot_be_rested_until, cannot_block_until) quando este jogador
          comeca seu turno.
          NOTA: o engine nao modela 'End Phase' como passo distinto do
          turno -- por isso 'until end of next turn' e 'until end of next
          End Phase' sao tratados de forma equivalente aqui (ambos resetam
          no refresh do jogador travado). A diferenca de granularidade
          entre os dois so importaria se algum efeito pudesse agir
          especificamente NA End Phase antes do refresh, o que o engine
          ainda nao simula.

        `opp` (opcional, so usado por lock_both_character_refresh): passiva
        SIMETRICA de Stage (achado 15/07, OP05-040 Birdcage/Doflamingo) que
        trava "nao ficar ativo" em AMBOS os campos, cost<=N, enquanto a
        fonte estiver em jogo (nao e freeze-1x como frozen_next_refresh).
        A fonte pode estar no campo de QUALQUER um dos 2 jogadores -- por
        isso verifica os dois field_stage antes de decidir o cost_lte.
        """
        lock_both_cost_lte = None
        for owner in (p, opp):
            if owner is None or owner.field_stage is None:
                continue
            passive = get_card_effects(owner.field_stage.code).get('passive', {})
            for step in passive.get('steps', []):
                if step.get('action') != 'lock_both_character_refresh':
                    continue
                conds = passive.get('conditions', {})
                leader_is = conds.get('leader_is', '').lower()
                if leader_is and leader_is not in owner.leader.name.lower():
                    continue
                lock_both_cost_lte = step.get('cost_lte', 99)

        don_from_cards = sum(c.don_attached for c in p.field_chars) + p.leader.don_attached
        for c in p.field_chars:
            c.don_attached = 0
            # Freeze (lock_opp_character_refresh / lock_self_character_refresh
            # target='this_card'): pula SO o untap nesta refresh, consumido
            # uma vez -- card permanece rested mesmo sem ter sido restado de
            # novo por outro motivo. Resto do reset (buffs, travas de turno)
            # acontece normalmente, igual a qualquer outro character.
            if c.frozen_next_refresh:
                c.frozen_next_refresh = False
            elif lock_both_cost_lte is not None and c.cost <= lock_both_cost_lte:
                pass  # Birdcage: nao ativa, mas NAO consome frozen_next_refresh (persistente)
            else:
                c.rested = False
            c.just_played = False
            c.power_buff = 0
            c.cost_buff = 0
            c.cannot_attack_until = ''
            c.cannot_be_rested_until = ''
            c.cannot_block_until = ''
            c.effects_negated_until = ''
            c.attack_paywall = {}
            c.unblockable_this_turn = False
            c.rush_this_turn = False
            c.double_attack_this_turn = False
            c.blocker_this_turn = False
            c.can_attack_active_this_turn = False
            c.immunity_ko_until = ''  # imunidade temporaria (grant_ko_immunity_type)
            c.battled_opp_character_this_turn = False
            c.cannot_attack_opp_chars_cost_lte = -1
        p.leader.don_attached = 0
        p.leader.rested = False
        p.leader.power_buff = 0
        p.leader.cost_buff = 0
        p.leader.cannot_attack_until = ''
        p.leader.effects_negated_until = ''
        p.leader.unblockable_this_turn = False
        p.leader.battled_opp_character_this_turn = False
        p.leader.cannot_attack_opp_chars_cost_lte = -1
        if p.field_stage:
            if p.field_stage.frozen_next_refresh:
                p.field_stage.frozen_next_refresh = False
            else:
                p.field_stage.rested = False
        # Freeze de DON (lock_opp_don_refresh): N do don_rested fica congelado
        # (nao volta a ficar available nesta refresh), consumido uma vez.
        frozen = min(p.frozen_don_count, p.don_rested)
        p.don_available += (p.don_rested - frozen) + don_from_cards
        p.don_rested = frozen
        p.frozen_don_count = 0
        # Reset da auto-restrição "cannot play this turn" (vale só pelo turno em
        # que foi imposta; ao começar o próximo turno do jogador, ela cai).
        p.cant_play_from_hand_this_turn = False
        p.cant_play_chars_this_turn = False
        p.cant_play_cost_gte = 0
        p.cannot_attack_leader_this_turn = False
        p.cant_take_life_this_turn = False
        p.events_activated_costs_this_turn = []

    def draw_phase(self, p: GameState, verbose: bool = False):
        """PlayerDrawPhase — 1º jogador não compra no T1."""
        if p.turn == 1 and p.is_first:
            return
        if p.deck:
            drawn = p.deck.pop()
            p.hand.append(drawn)
            if verbose:
                print(f'  \033[90mComprou: {drawn.name[:30]}\033[0m')

    def don_phase(self, p: GameState, verbose: bool = False):
        """
        PlayerDonPhase:
        - T1 do 1º jogador: +1 DON
        - Outros turnos: +2 DON
        - Máximo 10 (limitado pelo don_deck)
        """
        gain = min(1 if (p.turn == 1 and p.is_first) else 2, p.don_deck)
        p.don_deck -= gain
        p.don_available += gain
        if verbose:
            print(f'  \033[93mDON!! +{gain} rampados │ '
                  f'{p.don_available} ativos │ '
                  f'{p.don_rested} restados\033[0m')

    def end_phase(self, p: GameState, opp: GameState, verbose: bool = False):
        """Resolve [End of Your Turn] e actions agendadas para o fim do turno."""
        ee = EffectExecutor(p, opp)
        sources = [p.leader] + list(p.field_chars)
        if p.field_stage:
            sources.append(p.field_stage)
        for source in sources:
            logs = ee.execute(source, 'end_of_turn')
            if verbose:
                for log in logs:
                    if log:
                        print(f'  \033[90m[end] {log}\033[0m')

        queue = list(p.end_of_turn_queue)
        p.end_of_turn_queue.clear()
        for item in queue:
            step = item.get('step', {})
            source = item.get('card') or p.leader
            log = ee._execute_step(step, source)
            if verbose and log:
                print(f'  \033[90m[end queued] {log}\033[0m')

    def _activate_main_effects(self, p, opp, ee, verbose=False):
        """
        Ativa efeitos [Activate: Main] disponíveis (líder, Stage, personagens).
        A IA decide ativar quando o benefício é claro e o custo é pagável.
        Respeita 'once_per_turn'.
        """
        # Fontes de efeito ativável: líder, stage, e personagens em campo
        sources = []
        if p.leader:
            sources.append(p.leader)
        if p.field_stage:
            sources.append(p.field_stage)
        sources.extend(p.field_chars)

        for src in sources:
            effects = get_card_effects(src.code)
            am = effects.get('activate_main')
            if not am:
                continue
            # once per turn: marca em atributo dinâmico
            if am.get('once_per_turn'):
                used = getattr(src, '_am_used_turn', -1)
                if used == p.turn:
                    continue
            # Decide se vale ativar (benefício claro): draw/search/play sempre vale;
            # efeitos que precisam de alvo, só se houver alvo.
            pode, motivo = self._should_activate_main(src, am, p, opp)
            if not pode:
                self._log_decision(p, src, 'activate_main', 'skip', motivo)
                continue
            # Marca uso e executa
            src._am_used_turn = p.turn
            self._log_decision(p, src, 'activate_main', 'activate', motivo)
            if verbose:
                print(f'    ⚙ ativou [Activate:Main] de {src.name[:22]}')
            logs = ee.execute(src, 'activate_main')
            if verbose:
                for log in logs:
                    if log:
                        print(f'      ↳ {log}')
            # Só loga no replay se o efeito produziu algo observável
            if any(logs):
                desc = ' | '.join(l for l in logs if l)
                self._log_event(p, 'activate_main', card=src, description=desc)

    def _should_activate_main(self, src, am, p, opp) -> tuple[bool, str]:
        """
        Decide se vale ativar um efeito [Activate: Main].
        Retorna (pode_ativar: bool, motivo: str).
        O motivo é usado pelo decision audit para categorizar por que um
        efeito não foi ativado — sem precisar caçar caso a caso.
        """
        # ── 0. Verifica condições do bloco (ex: board_has_cost) ─────────────
        conds = am.get('conditions', {})
        if conds:
            # Reutiliza _check_conditions do EffectExecutor para consistência
            dummy_ee = EffectExecutor(p, opp)
            if not dummy_ee._check_conditions(conds, src):
                return False, 'condições do efeito não satisfeitas (board/estado)'

        steps = am.get('steps', [])
        actions = [s.get('action') for s in steps]
        costs = am.get('costs', [])

        # ── 0b. play_card sem carta elegível na mão: ativar é jogar o custo
        # fora (achado real 11/07, log 01.36.16: Empty Throne ativado com a
        # mão só de custo-7+ e eventos, 3 DON + stage restados pra "Choose 0
        # Friendly Targets"). Usa o MESMO _step_is_viable do executor — fonte
        # única da regra de elegibilidade.
        if 'play_card' in actions:
            dummy_ee = EffectExecutor(p, opp)
            passos_play = [s for s in steps if s.get('action') == 'play_card']
            if not any(dummy_ee._step_is_viable(s, src) for s in passos_play):
                return False, 'play_card: nenhuma carta elegível na mão'

        # ── 1. Verifica pagabilidade de cada custo ───────────────────────────
        for c in costs:
            ctype = c.get('type')
            cnt   = c.get('count', 1)
            ftype = (c.get('filter_type') or '').lower()

            if ctype == 'rest_self':
                if getattr(src, 'rested', False):
                    return False, f'custo rest_self: {src.name} já está restado'

            elif ctype == 'rest_don':
                if p.don_available < cnt:
                    return False, f'custo rest_don {cnt}: só {p.don_available} DON disponível'

            elif ctype in ('trash_from_hand', 'trash_hand'):
                color = (c.get('color') or '').lower()
                if ftype or color or c.get('has_trigger'):
                    elegíveis = [
                        c2 for c2 in p.hand
                        if (not ftype or ftype in c2.sub_types.lower())
                        and (not color or color in c2.color.lower())
                        and (not c.get('has_trigger') or c2.has_trigger)
                    ]
                    if len(elegíveis) < cnt:
                        return False, (f'custo trash_hand ({ftype}): '
                                       f'só {len(elegíveis)} elegíveis na mão')
                elif len(p.hand) < cnt:
                    return False, f'custo trash_hand: mão com só {len(p.hand)} cartas'

            elif ctype == 'trash_typed_hand_or_named_hand_field':
                named = (c.get('alternate_name') or '').lower()
                typed = [c2 for c2 in p.hand if ftype in c2.sub_types.lower()]
                named_hand = [c2 for c2 in p.hand if named in c2.name.lower()]
                named_field = [c2 for c2 in p.field_chars if named in c2.name.lower()]
                if p.field_stage and named in p.field_stage.name.lower():
                    named_field.append(p.field_stage)
                available = {id(c2) for c2 in typed + named_hand + named_field}
                if len(available) < cnt:
                    return False, 'custo tipo/nome: nenhuma opcao valida na mao ou campo'

            elif ctype == 'life_to_hand':
                if p.cant_take_life_this_turn:
                    return False, 'custo life_to_hand bloqueado neste turno'
                if len(p.life) < cnt:
                    return False, f'custo life_to_hand: Life com so {len(p.life)} cartas'

            elif ctype == 'trash_char_or_hand':
                # "trash 1 [Tipo] Character (campo) OU 1 carta da mão"
                # O filtro de tipo aplica SOMENTE ao personagem de campo.
                # Qualquer carta da mão qualifica sem restrição de tipo.
                chars_ok = [c2 for c2 in p.field_chars
                            if not ftype or ftype in c2.sub_types.lower()]
                hand_ok  = p.hand   # qualquer carta da mão
                if len(chars_ok) + len(hand_ok) < cnt:
                    return False, (f'custo trash_char_or_hand ({ftype or "qualquer"}): '
                                   f'{len(chars_ok)} chars + {len(hand_ok)} na mão, precisa {cnt}')
                # Se a mão está vazia e só há chars ATIVOS elegíveis (que podem
                # atacar este turno) E que REALMENTE valem a pena atacar (poder
                # > 0 -- um corpo de 0 poder nunca conecta dano nem justifica
                # nada, "pode atacar" e so legalidade, nao valor), adia: melhor
                # atacar antes de trashar. SEM o filtro de poder, um corpo
                # dead-weight (ex: Shalria pos on-play, 0 poder) fica pra
                # SEMPRE "tecnicamente ativo" -- o bot corretamente nunca
                # ataca com ele (0 poder nao vale) -> ele nunca fica restado
                # -> este guard nunca libera -> DEADLOCK: o ciclo do lider
                # trava pro resto da partida (achado ao vivo 14/07, log
                # 13.08.24: Shalria nunca foi trashada em 10 turnos).
                if len(hand_ok) < cnt:
                    ativos = [c2 for c2 in chars_ok
                              if c2.power > 0 and character_can_attack_now(c2, p, opp)]
                    if len(ativos) >= cnt:
                        return False, 'adia trash_char: atacar com chars ativos antes de trashar'
                # Imu leader: mesmo com carta na mao para pagar o custo, o
                # alvo real do simulador pode acabar sendo um Elder ativo no
                # campo. Nao cicla antes de extrair ataques ja disponiveis
                # (mesmo filtro de poder>0 acima -- mesmo deadlock).
                if src is p.leader and any(a in ('draw', 'look_top_deck', 'add_to_hand')
                                           for a in actions):
                    ativos = [c2 for c2 in chars_ok
                              if c2.power > 0 and character_can_attack_now(c2, p, opp)]
                    if ativos:
                        return False, 'adia ciclo do lider: atacar com chars ativos antes de trashar'

            elif ctype == 'trash_char':
                chars_ok = [c2 for c2 in p.field_chars
                            if not ftype or ftype in c2.sub_types.lower()]
                if len(chars_ok) < cnt:
                    return False, (f'custo trash_char ({ftype or "qualquer"}): '
                                   f'só {len(chars_ok)} no campo')

            elif ctype == 'don_minus':
                don_total = (p.don_available + p.don_rested
                             + sum(x.don_attached for x in p.field_chars)
                             + p.leader.don_attached)
                if don_total < cnt:
                    return False, f'custo don_minus {cnt}: só {don_total} DON total'

        # ── 2. Avalia se o benefício compensa ────────────────────────────────
        tem_custo_trash = any(c.get('type') in
                              ('trash_from_hand', 'trash_hand',
                               'trash_char_or_hand', 'trash_char',
                               'trash_typed_hand_or_named_hand_field')
                              for c in costs)

        # Draw / search — vantagem pura, sempre vale se custo foi pago
        if any(a in ('draw', 'look_top_deck', 'add_to_hand') for a in actions):
            if tem_custo_trash:
                cnt_trash = next((c.get('count', 1) for c in costs
                                  if c.get('type') in ('trash_from_hand', 'trash_hand',
                                                        'trash_char_or_hand',
                                                        'trash_typed_hand_or_named_hand_field')), 1)
                if len(p.hand) <= cnt_trash:
                    return False, (f'custo-benefício draw: mão ({len(p.hand)}) '
                                   f'não sobra após trashar {cnt_trash}')
            return True, 'benefício draw/search compensa'

        # Efeitos sobre oponente — só com alvo
        control_actions = (
            'rest_opp', 'rest_opp_character', 'ko', 'ko_opp',
            'ko_if_cost_eq_don', 'debuff', 'debuff_power', 'debuff_cost',
            'bounce', 'place_opp_character_bottom_deck',
            'lock_opp_character_refresh', 'lock_opp_character_attack',
        )
        if any(a in control_actions for a in actions):
            if not opp.field_chars:
                return False, 'efeito sobre oponente: nenhum personagem alvo disponível'
            return True, 'alvo disponível no campo oponente'

        # DON ramp — sempre vale
        if any(a in ('add_don', 'set_don_active') for a in actions):
            return True, 'benefício DON ramp'

        # play_card de graça — vale se há carta elegível na mão.
        # ATENÇÃO (12/07): esta era a TERCEIRA cópia da regra de
        # elegibilidade (0b/_step_is_viable, executor, aqui), e foi assim
        # que o bug do "Empty Throne no vácuo" sobreviveu a 3 reports —
        # cada cópia com um detalhe faltando. Mesmo default de tipo aqui:
        # play_card sem card_type explícito = CHARACTER (o evento "The
        # Five Elders Are at Your Service!!!" tem 'five elders' nos
        # sub_types e passava neste laço).
        if 'play_card' in actions:
            for s in steps:
                if s.get('action') != 'play_card':
                    continue
                cost_lte = s.get('cost_lte')
                if cost_lte == 'don_count_self':
                    cost_lte = p.don_available + p.don_rested
                ftype = (s.get('filter_type') or '').lower()
                fcolor = (s.get('color') or '').lower()
                req_type = (s.get('card_type') or 'CHARACTER').upper()
                for c in p.hand:
                    if c.card_type != req_type:                       continue
                    if cost_lte is not None and c.cost > cost_lte:   continue
                    if ftype and ftype not in c.sub_types.lower():    continue
                    if fcolor and fcolor not in c.color.lower():      continue
                    return True, f'play_card elegível: {c.name}'
            return False, 'play_card: sem carta elegível na mão com o filtro'

        # buff_power / debuff_power sem alvo explícito — aplica sempre
        if any(a in ('buff_power', 'set_base_power') for a in actions):
            if any(c.get('type') == 'ko_own_character' for c in costs):
                attackers = [c for c in p.field_chars
                             if character_can_attack_now(c, p, opp)]
                if not attackers and getattr(p.leader, 'rested', False):
                    return False, 'buff_power com K.O. proprio sem ataques para aproveitar'
            return True, 'buff_power incondicionado'

        # play_from_trash — vale se há carta no trash elegível
        if 'play_from_trash' in actions:
            for s in steps:
                if s.get('action') != 'play_from_trash':
                    continue
                ftype  = (s.get('filter_type') or '').lower()
                fcolor = (s.get('color') or '').lower()
                for c in p.trash:
                    if ftype  and ftype  not in c.sub_types.lower(): continue
                    if fcolor and fcolor not in c.color.lower():      continue
                    return True, f'play_from_trash elegível: {c.name}'
            return False, 'play_from_trash: sem carta elegível no trash'

        # Efeitos de descarte do oponente — vale se oponente tem mão
        if any(a in ('opp_trash_from_hand', 'opp_shuffle_hand_into_deck',
                     'opp_place_hand_bottom_deck') for a in actions):
            if not opp.hand:
                return False, 'discard oponente: oponente sem cartas na mão'
            return True, f'discard oponente ({len(opp.hand)} cartas na mão)'

        # Qualquer outra ação com custo já validado — ativa por omissão.
        # Melhor ativar e deixar o executor decidir do que silenciosamente ignorar.
        return True, f'ação ativada por omissão (heurística não cobre): {actions}'

    def _negate_effect_target_value(self, target) -> float:
        """Valor futuro de negar efeito; on_play ja resolvido nao conta."""
        if target is None or getattr(target, 'effects_negated_until', ''):
            return 0.0
        effects = get_card_effects(target.code)
        if not effects:
            return 0.0

        value = 0.0
        future_blocks = (
            'activate_main', 'when_attacking', 'on_ko', 'on_opponent_attack',
            'your_turn', 'opp_turn', 'end_of_turn', 'start_of_turn',
            'passive', 'continuous', 'trigger',
        )
        for key in future_blocks:
            if effects.get(key):
                value += 55 if key in ('activate_main', 'when_attacking') else 30

        if getattr(target, 'has_blocker', False) or getattr(target, 'blocker_this_turn', False):
            value += 25
        return value

    def _best_negate_effect_target_value(self, opp, target_scope='opp_leader_or_character') -> float:
        targets = []
        scope = (target_scope or 'opp_leader_or_character').lower()
        if 'leader' in scope and getattr(opp, 'leader', None) is not None:
            targets.append(opp.leader)
        if 'character' in scope or scope in ('opp', 'opponent'):
            targets.extend(getattr(opp, 'field_chars', []))
        return max((self._negate_effect_target_value(t) for t in targets), default=0.0)

    def _stage_play_saves_don_for_card(self, p, card) -> int:
        stage = getattr(p, 'field_stage', None)
        if stage is None or getattr(stage, 'rested', False):
            return 0
        effects = get_card_effects(stage.code)
        am = effects.get('activate_main', {})
        steps = am.get('steps', [])
        if not any(s.get('action') == 'play_card' for s in steps):
            return 0
        costs = am.get('costs', [])
        stage_don_cost = sum(c.get('count', 0) for c in costs if c.get('type') == 'rest_don')
        if p.don_available < stage_don_cost:
            return 0

        for step in steps:
            if step.get('action') != 'play_card':
                continue
            cost_lte = step.get('cost_lte')
            if cost_lte == 'don_count_self':
                cost_lte = p.don_available + p.don_rested
            ftype = (step.get('filter_type') or '').lower()
            fcolor = (step.get('color') or '').lower()
            fcard_type = (step.get('card_type') or 'CHARACTER').upper()
            if fcard_type and card.card_type.upper() != fcard_type:
                continue
            if cost_lte is not None and card.cost > cost_lte:
                continue
            if ftype and ftype not in card.sub_types.lower():
                continue
            if fcolor and fcolor not in card.color.lower():
                continue
            opponent = self.state_b if p is self.state_a else self.state_a
            return max(0, effective_hand_play_cost(p, card, opponent) - stage_don_cost)
        return 0

    def _score_play_action(self, card, engine) -> float:
        """
        Pontua JOGAR uma carta. Cartas cujo efeito HABILITA o ataque
        (On Play remoção, rush, buff, activate que ajuda) pontuam alto e saem
        ANTES dos ataques. Cartas só-desenvolvimento (blocker defensivo, vanilla)
        pontuam como dev e saem DEPOIS dos ataques (regra de ordem do usuário).
        """
        stage_saves = self._stage_play_saves_don_for_card(engine.me, card)
        if stage_saves >= 3:
            return -999.0

        base = engine.avaliar_carta(card)
        flags = get_card_flags(card.code)
        effects = get_card_effects(card.code)

        # Contra-parte do bônus de counter em avaliar_carta: aquele bônus
        # existe pra contexto "vale manter essa carta na mão" (ex: _trash_value).
        # Jogar a carta FAZ O OPOSTO — ela sai da mão e perde o valor de counter
        # (e, se veio de um Life card recém-revelado, o próprio
        # resolve_trigger_choice já decidiu deliberadamente NÃO usar o trigger
        # porque a carta vale mais como counter garantido na mão). Sem este
        # desconto, cartas com counter alto e pouco poder (achado real 10/07:
        # Doc Q counter=2000/poder=0, Baby 5 counter=2000) herdavam o bônus de
        # avaliar_carta e pontuavam artificialmente alto pra JOGAR, esvaziando
        # a mão de counters — 2x Doc Q + 1x Baby 5 jogados em 2 turnos, bot
        # terminou o resto da partida sem nenhum counter na mão.
        if card.counter > 0:
            my_life = engine.me.life_count()
            v = card.counter / 1000 * 15
            if my_life <= 1: v *= 4.0
            elif my_life <= 2: v *= 2.5
            elif my_life <= 3: v *= 1.5
            counters_em_mao = sum(1 for c in engine.me.hand
                                  if c.counter > 0 and c is not card)
            if counters_em_mao >= 4: v *= 0.4
            elif counters_em_mao >= 2: v *= 0.7
            base -= v

        # GamePlan fase 2 (HANDOFF #119/#120): DON!! não é perdido entre
        # turnos (refresh no início do turno devolve TUDO que foi anexado,
        # + o ramp de +2) — o que trava a carta-bomba (ex: Five Elders,
        # custo 10) não é "não guardei DON ao longo de várias partidas", é
        # gastar o DON deste MESMO turno em margem de ataque ANTES dela
        # competir pela vez, no turno exato em que ela já ficou pagável.
        # Achado real 10/07 (log 23.38.05): don=9 no turno 5 foi todo pra
        # 2 ataques (top3 480/480/470, tudo 'attack') — no turno em que o
        # DON bater o alvo, a jogada precisa vencer qualquer ataque na
        # ordem, não só competir normalmente. Mesma lógica do ZEHAHAHAHA
        # do usuário: joga a bomba PRIMEIRO quando o DON permite, ataque
        # "seco" (sem margem) depois com o que sobrar.
        plano = compute_game_plan(engine.me)
        if (plano['win_con_code'] and card.code == plano['win_con_code']
                and plano['don_target']
                and engine.me.don_available >= plano['don_target']):
            base += 600

        # Guarda de campo cheio: jogar um Character com o campo cheio (5)
        # KO a pior carta ja em campo pra abrir espaco (main_phase, sem volta
        # depois de pago o custo). Se a nova carta nao supera a pior ja em
        # campo, a troca e liquido zero ou negativo -- desqualifica a jogada
        # aqui, ANTES do DON ser gasto (mesma regra que o outro caminho de
        # play_card, GRUPO 2, ja aplica). Achado em partida real 07/07: o
        # planner reofereceu "jogar Doc Q" repetidas vezes com o campo cheio
        # de Doc Qs/Laffittes, trocando carta fraca por carta fraca a troco
        # de nada, turno apos turno.
        if card.card_type == 'CHARACTER' and len(engine.me.field_chars) >= 5:
            pior = min(engine.me.field_chars, key=lambda c: c.board_value())
            if card.board_value() <= pior.board_value():
                return -999.0

        # Carta que PRECISA entrar para ativar efeito que ajuda o ataque agora:
        # On Play de remoção/buff/rest/draw, ou rush. Bônus para sair antes do
        # ataque. Detecção via flags estruturadas (não substring no texto cru).
        habilita_ataque = False
        if 'on_play' in effects:
            if (flags.get('kos') or flags.get('is_removal') or flags.get('bounces')
                    or flags.get('power_buff')
                    or flags.get('draws') or flags.get('is_searcher')):
                habilita_ataque = True
            # rests_opponent só habilita ataque se o oponente tem alvo para restar
            if flags.get('rests_opponent') and engine.opp.field_chars:
                habilita_ataque = True
        if card.has_rush or card.rush_this_turn:
            habilita_ataque = True
        # when_attacking: o personagem precisa estar em campo para disparar o
        # efeito; jogar ele agora HABILITA ataques com bônus no mesmo turno.
        if 'when_attacking' in effects and card.card_type == 'CHARACTER':
            habilita_ataque = True
        # activate_main: valor recorrente por turno em campo — priorizar colocar
        # em campo para acumular esse valor nos turnos seguintes.
        if 'activate_main' in effects and card.card_type == 'CHARACTER':
            am = effects['activate_main']
            am_steps = am.get('steps', [])
            recupera_trash = next((s for s in am_steps if s.get('action') == 'play_from_trash'), None)
            if recupera_trash:
                ft = (recupera_trash.get('filter_type') or '').lower()
                max_rec = recupera_trash.get('count', 1)
                # Conta alvos no trash + no campo (que o efeito vai trashar antes de recuperar)
                def _matches_ft(c2):
                    return c2.card_type == 'CHARACTER' and (
                        not ft or ft in (c2.sub_types or '').lower())
                trash_targets = sum(1 for c2 in engine.me.trash if _matches_ft(c2))
                field_targets = sum(1 for c2 in engine.me.field_chars if _matches_ft(c2) and c2 is not card)
                n = min(trash_targets + field_targets, max_rec)
                base += 30 + n * 50   # cada char recuperável vale ~50
            else:
                base += 30

        if habilita_ataque:
            base += 60   # prioriza sair antes dos ataques

        # Penalização de AUTO-TRAVA (parte b): se jogar esta carta me trava de
        # jogar mais neste turno (self_cant_play no on_play), e ainda tenho cartas
        # que eu QUERERIA jogar antes de travar, penaliza — para o planner preferir
        # jogá-las primeiro (ou só ativar o combo quando a mão já foi gasta).
        op = effects.get('on_play')
        if op and any(s.get('action') == 'self_cant_play' for s in op.get('steps', [])):
            scope = next((s.get('scope', 'chars') for s in op['steps']
                          if s.get('action') == 'self_cant_play'), 'chars')
            gte = next((s.get('cost_gte', 0) for s in op['steps']
                        if s.get('action') == 'self_cant_play'), 0)
            me = engine.me
            don_usable = me.don_available
            perdidas = 0
            for c in me.hand:
                if c is card or c.card_type not in ('CHARACTER', 'EVENT', 'STAGE'):
                    continue
                if effective_hand_play_cost(me, c, engine.opp) > don_usable:
                    continue   # não jogaria mesmo (sem DON) — não conta como perda
                # essa carta SERIA bloqueada pela trava?
                bloqueada = (scope == 'hand'
                             or (c.card_type == 'CHARACTER'
                                 and (gte == 0 or c.cost >= gte)))
                if bloqueada:
                    perdidas += engine.avaliar_carta(c)
            base -= perdidas * 0.5   # peso TUNÁVEL (fase 3)

        # EVENT cujo [Main] não PRODUZ nada no estado atual: jogar é pagar
        # custo + carta no vácuo. Era um caso hardcoded ko+opp_stage ("Never
        # Existed" sem stage, 11/07) — achado real 12/07 (partida 14.30.52):
        # Ground Death (negate_effect em opp_character) foi jogado com o
        # campo do oponente VAZIO porque o padrão não era coberto.
        # Generalizado via _step_is_viable/_check_conditions — a MESMA régua
        # do gate de activate_main (regra do projeto: viabilidade ampla,
        # nunca ativar no vácuo), cobre qualquer evento/step, não uma carta.
        if card.card_type == 'EVENT':
            main = effects.get('main', {})
            main_steps = main.get('steps', [])
            if main_steps:
                ee_viab = EffectExecutor(engine.me, engine.opp)
                cond_ok = ee_viab._check_conditions(main.get('conditions', {}), card)
                if not cond_ok or not any(ee_viab._step_is_viable(s, card)
                                          for s in main_steps):
                    # Evento cujo [Main] nao produz NADA agora: jogar e pagar
                    # custo + a carta no vacuo -- e, se ela tambem for um
                    # [Counter] (ex: Never Existed OP13-098, ko opp_stage sem
                    # stage do oponente), ainda QUEIMA a defesa por zero. Nunca
                    # vale na propria main phase. BLOQUEIO DURO: o -120 anterior
                    # era mole e o bot jogava quando sobrava DON e nada melhor
                    # (achado ao vivo 14/07, log 01.23.31 -- "Never Existed do
                    # nada"). A carta fica na mao pra defender.
                    return -999.0

        # STAGE com stage própria já em campo: jogar SUBSTITUI a atual (regra
        # do jogo, 1 stage por lado). A 1ª versão deste fix descontava só
        # avaliar_carta da atual — o Empty Throne (motor de deploy grátis)
        # avalia baixo e a Mary Geoise substituiu DE NOVO na partida
        # seguinte (23.41.50, 2º report). Agora régua composta stage_worth
        # (avaliar + motor de activate_main) dos DOIS lados: substituição
        # com ganho líquido <= 0 é bloqueada dura (-999, nunca compete);
        # uma stage genuinamente melhor continua podendo entrar.
        if card.card_type == 'EVENT':
            main = effects.get('main', {})
            main_steps = main.get('steps', [])
            if main_steps and any(s.get('action') == 'negate_effect' for s in main_steps):
                negate_value = max(
                    self._best_negate_effect_target_value(engine.opp, s.get('target'))
                    for s in main_steps if s.get('action') == 'negate_effect'
                )
                if negate_value <= 0:
                    base = min(base - 140, -80)  # on_play ja resolvido/sem texto futuro: nao gaste DON
                else:
                    base += min(negate_value, 70)

        if card.card_type == 'STAGE' and engine.me.field_stage is not None:
            worth_nova  = engine.stage_worth(card)
            worth_atual = engine.stage_worth(engine.me.field_stage)
            if worth_nova <= worth_atual:
                return -999.0
            base -= worth_atual

        # CHARACTER cujo on_play não dispara AGORA (condição falha ou nenhum
        # step com material): o play perde o valor de efeito e vira só o
        # corpo. Corpo de 0 poder com on_play morto é um play quase inútil
        # que ainda alimenta remoção/KO do oponente — reclamação real 12/07:
        # Mjosgard (on_play reanimar Mary Geoise custo 1, condição vida<=3)
        # descido com vida 4 e trash sem alvo, 2 DON num vanilla de 0 poder.
        if card.card_type == 'CHARACTER':
            op_block = effects.get('on_play', {})
            if op_block.get('steps'):
                ee_viab = EffectExecutor(engine.me, engine.opp)
                op_vivo = (ee_viab._check_conditions(op_block.get('conditions', {}), card)
                           and any(ee_viab._step_is_viable(s, card)
                                   for s in op_block['steps']))
                if not op_vivo:
                    base -= 40 if card.power > 0 else 90

        # Vanilla fraca (custo ≤ 2, poder ≤ 3000, sem efeito) no early game:
        # humanos normalmente passam em vez de gastar o único DON do T1/T3 em
        # cartas que não mudam o estado do jogo significativamente.
        if (card.card_type == 'CHARACTER'
                and card.cost <= 2
                and card.power <= 3000
                and not effects
                and not card.has_blocker):
            personal_turn = (engine.me.turn + 1) // 2
            if personal_turn <= 2:
                base -= 60  # penaliza fortemente no early; o humano prefere passar

        return base

    def _score_activate_main(self, src, am, p, opp, priority, engine=None) -> float:
        """
        Pontua a ação de ATIVAR um efeito [Activate:Main].
        Permite que a ativação compita com plays e ataques no Turn Planner,
        em vez de sempre disparar no início do turno.
        """
        steps = am.get('steps', [])
        actions_list = [s.get('action') for s in steps]
        costs = am.get('costs', [])
        custo_don = sum(c.get('count', 0) for c in costs if c.get('type') == 'rest_don')

        # Benefício base pelo tipo de efeito
        if any(a in ('draw', 'look_top_deck', 'add_to_hand') for a in actions_list):
            # vantagem de carta — muito valioso, custa quase nada (rest) e
            # buscar PRIMEIRO e estritamente melhor (filtra o deck antes de
            # decidir os deploys). 170 para vir antes de deploys baratos:
            # em partida real (04/07) o search do Laffitte (105) perdia para
            # 3 deploys e o DON acabava antes de ativar.
            base = 170
            # Se ativar NAO trava o plano (sobra DON para continuar jogando
            # depois), buscar primeiro nao tem downside nenhum — bonus para
            # vencer qualquer deploy (partida 06/07: play 166 > activate 155
            # e o Laffitte ficou parado de novo, num turno de 3 DON).
            if p.don_available >= custo_don + 2:
                base += 60
        elif any(a in ('add_don', 'set_don_active') for a in actions_list):
            base = 90    # ramp de DON
        elif any(a in ('play_card',) for a in actions_list):
            base = 110   # jogar carta grátis
            best_play_value = 0.0
            best_saved_don = 0
            for step in steps:
                if step.get('action') != 'play_card':
                    continue
                cost_lte = step.get('cost_lte')
                if cost_lte == 'don_count_self':
                    cost_lte = p.don_available + p.don_rested
                ftype = (step.get('filter_type') or '').lower()
                fcolor = (step.get('color') or '').lower()
                fcard_type = (step.get('card_type') or '').upper()
                for candidate in p.hand:
                    if cost_lte is not None and candidate.cost > cost_lte:
                        continue
                    if ftype and ftype not in candidate.sub_types.lower():
                        continue
                    if fcolor and fcolor not in candidate.color.lower():
                        continue
                    if fcard_type and candidate.card_type.upper() != fcard_type:
                        continue
                    value = engine.avaliar_carta(candidate) if engine is not None else candidate.board_value()
                    best_play_value = max(best_play_value, value)
                    best_saved_don = max(best_saved_don, effective_hand_play_cost(p, candidate, opp) - custo_don)
            base += min(best_play_value * 0.55, 95)
            base += min(max(0, best_saved_don) * 18, 45)
            if src is getattr(p, 'field_stage', None) and best_saved_don >= 3:
                base += min(best_saved_don * 80, 520)
                base += min(best_play_value * 0.20, 180)
        elif any(a in ('rest_opp', 'rest_opp_character', 'ko', 'ko_opp',
                       'ko_if_cost_eq_don', 'debuff_power', 'debuff_cost',
                       'bounce', 'place_opp_character_bottom_deck',
                       'negate_effect', 'lock_opp_character_attack') for a in actions_list):
            base = 100   # remoção/controle
            if 'negate_effect' in actions_list and engine is not None:
                negate_value = max(
                    self._best_negate_effect_target_value(opp, s.get('target'))
                    for s in steps if s.get('action') == 'negate_effect'
                )
                base = -60 if negate_value <= 0 else 100 + min(negate_value, 70)
        elif any(a == 'play_from_trash' for a in actions_list):
            # Achado real 09/07 (Five Elders OP13-082 nunca ativava, mesmo
            # com o board quase morrendo e a lixeira cheia de alvos
            # reanimaveis): 'play_from_trash' nao estava em NENHUMA
            # categoria reconhecida acima, entao caia no fallback generico
            # de 60 -- a mesma pontuacao de um efeito qualquer sem
            # categoria, mesmo quando reanima ATE 5 personagens de uma vez
            # (Five Elders). Nao e um problema so dessa carta: e QUALQUER
            # carta cujo Activate:Main usa essa acao (Kuma tambem tem, em
            # menor escala). Fix generico: soma o valor real dos alvos
            # elegiveis na lixeira (respeitando filter_type/distinct_names/
            # count do proprio step), igual 'play_card' ja faz pra mao.
            base = 120
            reanimados_valor = 0.0
            for step in steps:
                if step.get('action') != 'play_from_trash':
                    continue
                count = step.get('count', 1)
                ftype = (step.get('filter_type') or '').lower()
                elegiveis = [c for c in p.trash
                             if c.card_type == 'CHARACTER'
                             and (not ftype or ftype in c.sub_types.lower())]
                if step.get('distinct_names'):
                    vistos, unicos = set(), []
                    for c in elegiveis:
                        if c.name not in vistos:
                            unicos.append(c)
                            vistos.add(c.name)
                    elegiveis = unicos
                elegiveis.sort(key=lambda c: -(engine.analyzer.char_value_score(c) if engine is not None else c.board_value()))
                for c in elegiveis[:count]:
                    reanimados_valor += engine.analyzer.char_value_score(c) if engine is not None else c.board_value()
            base += min(reanimados_valor * 0.4, 280)

            # Se o custo INCLUI trashar o proprio campo inteiro (Five
            # Elders: "trash all your Characters"), desconta o que esta
            # sendo sacrificado -- senao a IA acha que ganhou os
            # reanimados de graca quando na verdade TROCOU o campo atual
            # pelo novo. So desconta quando e "trash ALL" (count>=99,
            # convencao do parser pra "todos") -- custo de sacrificio
            # pontual (1 personagem) ja e capturado por tem_ko_own abaixo.
            if any(s.get('action') == 'trash_character' and s.get('count', 0) >= 99
                   for s in steps):
                sacrificio = sum(
                    (engine.analyzer.char_value_score(c) if engine is not None else c.board_value())
                    for c in p.field_chars if c is not src
                )
                base -= min(sacrificio * 0.5, 220)
        else:
            base = 60

        # Custo real: quanto a ativação nos custa (trash de mão, DON, etc.)
        tem_trash_hand = any(c.get('type') in ('trash_from_hand', 'trash_hand', 'trash_char_or_hand',
                                               'trash_typed_hand_or_named_hand_field')
                             for c in costs)
        tem_ko_own = any(c.get('type') == 'ko_own_character' for c in costs)

        base -= custo_don * 15   # cada DON gasto tem custo de oportunidade

        if tem_ko_own:
            sacrifice_pool = []
            for card in p.field_chars:
                ok = True
                for cost in costs:
                    if cost.get('type') != 'ko_own_character':
                        continue
                    ftype = (cost.get('filter_type') or '').lower()
                    if ftype and ftype not in card.sub_types.lower():
                        ok = False
                        break
                if ok and card is not src:
                    sacrifice_pool.append(card)
            if sacrifice_pool:
                sacrifice_value = min(c.board_value() for c in sacrifice_pool)
                base -= min(sacrifice_value * 8, 80)
            else:
                base -= 100

        if tem_trash_hand:
            # Comprar descartando da mao nao e vantagem liquida de carta.
            # Ex: leader Imu trasha 1 da mao/campo para comprar 1; isso filtra
            # a mao, mas nao deveria competir como draw puro de score 120 no
            # early quando ainda ha cartas jogaveis para desenvolver campo.
            draw_count = sum(s.get('count', 1) for s in steps
                             if s.get('action') == 'draw')
            trash_count = sum(c.get('count', 1) for c in costs
                              if c.get('type') in ('trash_from_hand',
                                                   'trash_hand',
                                                   'trash_char_or_hand',
                                                   'trash_typed_hand_or_named_hand_field'))
            is_ciclo_neutro = bool(draw_count) and draw_count <= trash_count

            # Estimar qual carta seria trashada e quanto ela vale. Só penaliza
            # aqui quando NAO for ciclo card-neutro (draw>=trash já cobre o
            # trade-off via o cap abaixo) -- achado 09/07: penalizar os dois
            # (perda*0.3 aqui E o cap min(base,45)+early-penalty embaixo)
            # duplo-conta o mesmo custo "abriu mao de 1 carta da mao" e
            # derrubava o score do Imu pra negativo mesmo sem nada melhor
            # pra fazer, encerrando o turno com mao cheia e DON parado.
            if p.hand and not is_ciclo_neutro:
                ee_tmp = EffectExecutor(p, opp)
                pior = min(p.hand, key=ee_tmp._trash_value)
                perda = ee_tmp._trash_value(pior)
                # Se a carta mais "barata" de trashar ainda é cara (jogável), penaliza
                base -= min(perda * 0.3, 60)

            if is_ciclo_neutro:
                base = min(base, 45)
                # GamePlan (HANDOFF #119/#121): num deck cujo plano usa a
                # LIXEIRA como recurso (trash_target > 0, ex: Imu — imunidade
                # com 7+ e Five Elders reanimando do trash), o ciclo "trasha 1
                # → compra 1" não é neutro: cada ativação alimenta o plano.
                # Auditor 11/07 (check F): com o cap de 45 + as penalidades
                # genéricas abaixo, o draw do líder Imu pontuava NEGATIVO em
                # ~25% dos turnos com material sobrando e nunca era ativado.
                plano = compute_game_plan(p)
                alimenta_plano = bool(plano['trash_target']) and len(p.trash) < plano['trash_target']
                if alimenta_plano:
                    base += 30
                playable = [
                    c for c in p.hand
                    if c.card_type in ('CHARACTER', 'STAGE', 'EVENT')
                    and effective_hand_play_cost(p, c, opp) <= p.don_available
                ]
                if (not alimenta_plano and playable and len(p.field_chars) <= 1
                        and GameAnalyzer(p, opp).game_phase() == 'early'):
                    base -= 35

        # Ajustes por prioridade
        if priority == 'LETHAL':
            base -= 30   # prefere atacar quando pode ganhar
        elif priority == 'DEFENSIVE':
            base -= 20

        return base

    def _card_action_key(self, card):
        if card is None:
            return None
        return (
            getattr(card, 'code', ''),
            getattr(card, 'name', ''),
            getattr(card, 'card_type', ''),
            getattr(card, 'cost', 0),
            getattr(card, 'power', 0),
            getattr(card, 'power_buff', 0),
            getattr(card, 'don_attached', 0),
            bool(getattr(card, 'rested', False)),
            bool(getattr(card, 'just_played', False)),
            getattr(card, '_am_used_turn', -1),
        )

    def _action_dedupe_key(self, action):
        _score, kind, obj, ttype, tgt = action
        if kind == 'play':
            return (kind, getattr(obj, 'code', ''), getattr(obj, 'name', ''))
        if kind == 'activate':
            return (kind, self._card_action_key(obj))
        if kind == 'attack':
            return (kind, self._card_action_key(obj), ttype, self._card_action_key(tgt))
        if kind == 'attach_don':
            trig = tgt or {}
            trig_key = (
                trig.get('trigger') if isinstance(trig, dict) else str(trig),
                trig.get('action') if isinstance(trig, dict) else '',
            )
            return (kind, self._card_action_key(obj), ttype, trig_key)
        return (kind, self._card_action_key(obj), ttype, self._card_action_key(tgt))

    def _dedupe_scored_actions(self, actions):
        best_by_key = {}
        order = []
        for action in actions:
            key = self._action_dedupe_key(action)
            if key not in best_by_key:
                order.append(key)
                best_by_key[key] = action
            elif action[0] > best_by_key[key][0]:
                best_by_key[key] = action
        return [best_by_key[key] for key in order]

    def _is_unsafe_zero_life_leader_attack(self, action, p, opp, engine) -> bool:
        """Ataque ao leader com 0 vidas so deve sair se for lethal garantido
        ou se a simulacao Monte Carlo encontrar alguma linha vencedora."""
        _score, kind, _obj, target_type, _target = action
        return (
            kind == 'attack'
            and target_type == 'leader'
            and opp.life_count() == 0
            and not engine.analyzer.can_lethal_this_turn()
        )

    def _generate_and_score_actions(self, p, opp, engine):
        """
        Gera TODAS as ações possíveis no estado atual e as pontua.
        Retorna lista de (score, tipo, dados) ordenada por score desc.

        Ações: ('play', card) | ('activate', source) | ('attack', attacker, ttype, tgt)
        """
        actions = []
        a = engine.analyzer

        # PRIORIDADE DE ANÁLISE (cascata de inclinação): o modo dominante ajusta
        # os pesos das ações, respeitando a ordem do documento sem bloquear.
        priority = a.analysis_priority()
        threats = a.critical_threats() if priority == 'REMOVE_THREAT' else []
        don_reserve = engine._don_reserve_for_defense()

        # ── Ações de JOGAR carta ──
        for card in p.hand:
            don_usable = engine._don_usable_for_play(card, don_reserve)
            if not engine._can_play_card(card, don_usable=don_usable):
                continue
            score = self._score_play_action(card, engine)
            score += self._human_pattern_bonus(p, 'play', card)
            # Inclinação: desenvolver ganha peso no modo DEVELOP; perde no LETHAL/DEFENSIVE
            if priority == 'DEVELOP':
                score += 40
            elif priority == 'LETHAL':
                score -= 60   # não desenvolve quando pode ganhar — ataca
            # Carta defensiva (blocker/counter) ganha peso no modo DEFENSIVE
            if priority == 'DEFENSIVE' and (card.has_blocker or card.blocker_this_turn or card.counter > 0):
                score += 120
            # Preservacao de mao (partida real 04/07: bot esvaziou a mao em
            # deploys e ficou sem counter/custo de reacao para defender).
            # Mao encolhendo = cada play adicional fica mais caro.
            if len(p.hand) <= 3:
                score -= (4 - len(p.hand)) * 30
            actions.append((score, 'play', card, None, None))

        # ── Ações de ATACAR (com risco de trigger descontado) ──
        if p.can_attack_this_turn():
            attackers = [c for c in p.field_chars
                         if character_can_attack_now(c, p, opp)]
            if not p.leader.rested:
                attackers.append(p.leader)
            for att in attackers:
                # [Rush: Character] restringe o alvo a Characters do
                # oponente neste turno -- nao gera a opcao de atacar o Leader.
                pode_atacar_leader = not getattr(att, 'rush_character_only_this_turn', False)
                # alvo líder
                if pode_atacar_leader and not p.cannot_attack_leader_this_turn:
                    s_leader = engine.score_attack_target(att, 'leader', None)
                    if s_leader > -500:
                        s_leader += self._human_pattern_bonus(p, 'attack', att)
                        s_leader -= self._trigger_risk_penalty(opp)   # desconto de trigger
                        # Banish: prioriza atacar a vida (nega trigger e remove a carta
                        # de vez). Inclinação forte, mas a ameaça crítica ainda vem antes.
                        if att.has_banish:
                            s_leader += 150
                        if priority == 'LETHAL':       s_leader += 500   # foco em fechar
                        elif priority == 'DEFENSIVE':  s_leader -= 80    # não exponha à toa
                        elif priority == 'REMOVE_THREAT': s_leader -= 100 # remova antes
                        # Ataque de LÍDER validado é quase grátis (ele resta de
                        # qualquer jeito no fim do turno, não expõe personagem):
                        # postura defensiva + risco de trigger não podem
                        # negativá-lo a ponto de passar o turno sem atacar
                        # (visto em partida real: score -4 → líder ficou parado).
                        if att is p.leader:
                            s_leader = max(s_leader, 15)
                        actions.append((s_leader, 'attack', att, 'leader', None))
                # alvos personagem
                cost_lock = getattr(att, 'cannot_attack_opp_chars_cost_lte', -1)
                for tgt in opp.rested_chars(att):
                    # Auto-restricao de alvo (OP12-020): nao pode atacar
                    # Characters do oponente com custo <= N neste turno.
                    if cost_lock >= 0 and tgt.cost <= cost_lock:
                        continue
                    s_char = engine.score_attack_target(att, 'character', tgt)
                    if s_char > -500:
                        s_char += self._human_pattern_bonus(p, 'attack', att)
                        # Inclinação: remover a AMEAÇA CRÍTICA ganha prioridade alta
                        if tgt in threats:
                            s_char += 300   # acima de atacar o líder
                        actions.append((s_char, 'attack', att, 'character', tgt))

        # ── Ações de ATIVAR efeitos [Activate:Main] ──
        sources = []
        if p.leader:
            sources.append(p.leader)
        if p.field_stage:
            sources.append(p.field_stage)
        sources.extend(p.field_chars)
        for src in sources:
            effects = get_card_effects(src.code)
            am = effects.get('activate_main')
            if not am:
                continue
            # Fonte RESTADA nao ativa: a maioria dos [Activate: Main] de
            # personagem custa restar a propria carta, e o parser nem sempre
            # captura o rest_self (Laffitte OP09-095 06/07: engine reofereceu
            # o activate com ele restado, o jogo recusou em silencio e o
            # guarda de loop encerrou o turno com 4 DON em pe).
            # EXCECAO (auditor 11/07, check F): o LIDER cujo activate nao
            # custa rest_self (ex: Imu — custo e so trash) PODE ativar
            # restado; regra oficial nao exige a fonte ativa. A guarda
            # derrubava o draw do lider em todo turno em que ele atacava
            # ANTES de ativar (~25% dos turnos auditados). Personagens/
            # stages continuam conservadores (risco de rest_self perdido
            # pelo parser).
            if getattr(src, 'rested', False):
                exige_rest_self = any(c.get('type') == 'rest_self'
                                      for c in am.get('costs', []))
                if exige_rest_self or src is not p.leader:
                    continue
            # Ja usado NESTE turno: rastreado pelo engine na simulacao, ou
            # pelo jogo (lb_ActionsUsed -> actionUsed no DTO) no caminho do
            # bot. Vale para qualquer activate, com ou sem once_per_turn —
            # o estado do jogo e a verdade (loops do Laffitte/Devon 06/07).
            if getattr(src, '_am_used_turn', -1) == p.turn:
                continue
            pode, _ = self._should_activate_main(src, am, p, opp)
            if not pode:
                continue
            score = self._score_activate_main(src, am, p, opp, priority, engine=engine)
            score += self._human_pattern_bonus(p, 'activate', src)
            actions.append((score, 'activate', src, None, None))

        # ── Ações de ANEXAR DON para ligar efeitos/keywords [DON!! ×N] ──
        actions.extend(self._generate_attach_don_actions(p, opp, engine, priority=priority))

        actions = self._dedupe_scored_actions(actions)
        actions.sort(key=lambda x: x[0], reverse=True)
        return actions

    def _generate_attach_don_actions(self, p, opp, engine, priority=None):
        """
        Gera ações de ANEXAR DON para ligar efeitos/keywords [DON!! ×N].
        Avalia cada personagem em campo que tem efeito condicional a DON e ainda
        não atingiu o requisito. Vale anexar se o efeito ligado compensa prender
        o DON (custo ~25/DON), modulado pelo estado (postura/prioridade).
        """
        DON_COST = 25
        acts = []
        if p.don_available <= 0:
            return acts
        if priority is None:
            priority = engine.analyzer.analysis_priority()

        for card in p.field_chars:
            effects = get_card_effects(card.code)
            # 1) keywords condicionais a DON (blocker/double_attack/rush/banish)
            cond_kw = getattr(card, 'don_cond_keywords', None) or {}
            for kw, req in cond_kw.items():
                falta = req - card.don_attached
                if falta <= 0 or falta > p.don_available:
                    continue
                valor = self._keyword_don_value(kw, card, p, opp, priority)
                score = valor - falta * DON_COST
                if score > 0:
                    acts.append((score, 'attach_don', card, falta, kw))

            # 2) gatilhos condicionais a DON (when_attacking/on_play/etc.)
            for trig, ef in effects.items():
                if not isinstance(ef, dict):
                    continue
                req = ef.get('don_requirement', 0)
                if not req or card.don_attached >= req:
                    continue
                falta = req - card.don_attached
                if falta > p.don_available:
                    continue
                # só vale ligar gatilho de ataque se o personagem vai atacar
                valor = self._trigger_don_value(trig, ef, card, p, opp, priority)
                score = valor - falta * DON_COST
                if score > 0:
                    acts.append((score, 'attach_don', card, falta, trig))
        return acts

    def _keyword_don_value(self, kw, card, p, opp, priority) -> float:
        """Valor de ligar uma keyword via DON, conforme o estado."""
        if kw == 'blocker':
            # defensivo: vale muito sob pressão / vida baixa
            base = 100
            if priority == 'DEFENSIVE': base += 80
            if p.life_count() <= 2:     base += 60
            return base
        if kw == 'double_attack':
            # ofensivo: vale se o oponente está em alcance de dano
            base = 80
            if opp.life_count() <= 3: base += 60
            if priority == 'LETHAL':  base += 150
            return base
        if kw == 'rush':
            return 90   # poder atacar já
        if kw == 'banish':
            return 70 + (40 if opp.life_count() <= 3 else 0)
        return 40

    def _trigger_don_value(self, trig, ef, card, p, opp, priority) -> float:
        """Valor de ligar um gatilho condicional a DON, pelo que o efeito faz."""
        steps = ef.get('steps', [])
        actions = [s.get('action') for s in steps]
        valor = 0
        if any(x in ('ko', 'rest_opp', 'debuff_power', 'bounce') for x in actions):
            valor = 120   # remoção/controle — vale
            if opp.field_chars: valor += 30
        elif any(x in ('draw', 'add_to_hand', 'look_top_deck') for x in actions):
            valor = 90    # vantagem de carta
        elif any('power' in str(x) for x in actions):
            valor = 60    # buff de poder
        else:
            valor = 40
        # gatilhos de ataque só valem se o personagem pode atacar
        if trig == 'when_attacking' and not character_can_attack_now(card, p, opp):
            valor = 0
        return valor

    def _trigger_risk_penalty(self, opp) -> float:
        """
        Risco de trigger ao atacar (documento pág. 21): desconta, mas não proíbe.
        Mais vidas do oponente = mais chance de trigger. Amarelo = risco maior.
        """
        vidas = opp.life_count()
        if vidas == 0:
            return 0
        base = vidas * 8   # desconto suave por vida (trigger é risco, não veto)
        cor = (getattr(opp.leader, 'color', '') or '').lower()
        if 'yellow' in cor or 'amarelo' in cor:
            base *= 1.8
        return base

    def _evaluate_state(self, p, opp) -> float:
        """
        Avalia quão bom é um estado para 'p' (ao fim de uma sequência simulada).
        Combina: dano causado, vida própria, vantagem de board, recursos.
        Usado pelo Turn Planner para comparar linhas de jogo.
        """
        score = 0.0
        # Dano causado ao oponente (vidas tiradas) — peso alto
        score += p.dmg_dealt * 200
        score -= opp.life_count() * 150          # quanto menos vida o opp tem, melhor
        # Vitoria real na simulacao ja retorna SIMULATED_WIN_SCORE em
        # _simulate_sequence_values. Vida 0 sem dano final conectado ainda
        # e apenas pressao, nao deve receber bonus de vitoria.
        # Board próprio vs oponente
        score += sum(c.board_value() for c in p.field_chars) * 10
        score -= sum(c.board_value() for c in opp.field_chars) * 8
        # Blockers do oponente vivos (ruim para mim)
        score -= len(opp.blockers_active()) * 30
        # Minha vida (defesa)
        score += p.life_count() * 40
        # Recursos: cartas na mão, DON ainda disponível (flexibilidade)
        score += len(p.hand) * 8
        score += p.don_available * 5
        # Chars no trash que podem ser recuperados por cartas na mão (ex: Five Elders)
        for hc in p.hand:
            hc_eff = get_card_effects(hc.code)
            am = hc_eff.get('activate_main', {})
            for step in am.get('steps', []):
                if step.get('action') == 'play_from_trash':
                    ft = (step.get('filter_type') or '').lower()
                    max_rec = step.get('count', 1)
                    targets = sum(1 for c2 in p.trash
                                  if c2.card_type == 'CHARACTER'
                                  and (not ft or ft in (c2.sub_types or '').lower()))
                    score += min(targets, max_rec) * 60
                    break
        return score

    # ── evaluate_state v2: régua ÚNICA (item 1) ───────────────────────────────
    # Curva de vida ÍNGREME (marginal decrescente): 1ª vida vale muito mais que
    # a 5ª. Índice = quantas vidas tenho; valor = soma dos marginais. Mesma
    # filosofia da curva de counter (vida 1 » vida alta).
    _LIFE_MARGINAL = [0, 95, 55, 35, 22, 15, 11, 9, 8, 8, 8]

    def _life_value(self, n: int) -> float:
        m = self._LIFE_MARGINAL
        return float(sum(m[1:min(n, len(m) - 1) + 1]))

    def _turn_profile_for(self, p) -> dict | None:
        """Compatibilidade: delega pro modulo (deck_profile_for), que cacheia
        no proprio GameState -- assim DecisionEngine.avaliar_carta usa o
        MESMO cache sem precisar de acesso a instancia de OPTCGMatch."""
        return deck_profile_for(p)

    def _derived_axes_value(self, p, profile) -> float:
        """
        Contribuição dos eixos DERIVADOS do perfil ao estado de p. Só os eixos
        de AUTO-MOTOR (trash/reanimação/inversão): o valor da disrupção já
        entra pelos termos simétricos (o estado degradado do oponente é contado
        no board/DON dele), então NÃO se adiciona de novo aqui (evita dupla
        contagem). Escalas são PRIORS — a tunagem do item 5 ajusta.
        """
        if not profile:
            return 0.0
        W = getattr(p, 'eval_weights', None) or EVAL_WEIGHTS
        total = 0.0
        trash_n = len(p.trash)
        for ax in profile.get('derived_axes', []):
            kind = ax.get('kind')
            if kind == 'resource_staircase' and str(ax.get('resource', '')).startswith('trash'):
                # progresso SATURANTE até cada degrau: cresce até o threshold,
                # depois não vale mais (anti "mill pra sempre").
                for step in ax.get('steps', []):
                    if step.get('pruned'):
                        continue
                    thr = step.get('threshold') or 1
                    frac = min(1.0, trash_n / thr)
                    total += step.get('impacto', 0) * frac * W['ax_trash']
            elif kind == 'bottleneck':   # reanimação = min(motor, combustível)
                eng = ax.get('engine_card', {})
                ff = ax.get('fuel_filter', {})
                has_engine = any(c.code == eng.get('code')
                                 for c in (list(p.hand) + list(p.deck)))
                ft = (ff.get('filter_type') or '').lower()
                peq = ff.get('power_eq')
                fuel = sum(1 for c in p.trash
                           if c.card_type == 'CHARACTER'
                           and (not ft or ft in (c.sub_types or '').lower())
                           and (peq is None or c.power == peq))
                val = min(eng.get('reanima_ate', 0), fuel) if has_engine else 0
                total += val * W['ax_reanim']
                # win-con JOGÁVEL = "arma carregada": a peça-motor está na MÃO
                # (não só buscável no deck), há fuel real no trash E há progresso
                # de DON NO CAMPO rumo ao custo. DON usado/anexado neste turno
                # volta ativo no refresh, então `don_available` sozinho
                # subvaloriza a linha no fim da simulação. Faz a busca preferir a linha que
                # PRESERVA/desenvolve rumo ao combo em vez de trocá-lo por dano
                # marginal — e, quando o custo já é pagável (ramp satura em 1),
                # valoriza fortemente o estado que dispara o payoff. Genérico:
                # código/custo/fuel vêm do perfil, zero nome de carta. (Achado
                # ao vivo 13/07: OP13-082 ficou na mão a partida inteira, fuel
                # pronto, mas o combo nunca foi valorizado — ver HANDOFF.)
                engine_in_hand = any(c.code == eng.get('code') for c in p.hand)
                custo = eng.get('custo') or 0
                if engine_in_hand and fuel >= 1 and custo:
                    ramp = min(1.0, p.don_on_field() / custo)
                    total += val * ramp * W['wincon_ready']
            elif kind == 'inversion':    # life_lte: achata o pânico
                try:
                    thr = int(str(ax.get('condition', '')).split()[-1])
                except (ValueError, IndexError):
                    thr = 0
                if p.life_count() <= thr:
                    total += ax.get('prior_weight', 0) * W['ax_inversion']
        return total

    def _evaluate_state_v2(self, p, opp) -> float:
        """
        Régua ÚNICA de estado (item 1): termos GENÉRICOS simétricos + eixos
        DERIVADOS do perfil do deck. Substitui o _evaluate_state ad-hoc.
        Recebe (p, opp) do estado a julgar — usa GameAnalyzer local ligado a
        ESSES args (não a self.me/self.opp, que são o estado real).
        """
        an = GameAnalyzer(p, opp)
        # pesos POR JOGADOR (tunagem per-deck) — cai no global se não setado
        W = getattr(p, 'eval_weights', None) or EVAL_WEIGHTS
        score = 0.0

        # dano feito NESTE turno — delta que faz o planner preferir a linha que
        # de fato conecta dano (não só "desenvolve")
        score += p.dmg_dealt * W['dmg']

        # vida (curva íngreme, simétrica)
        score += self._life_value(p.life_count()) * W['life_mult']
        score -= self._life_value(opp.life_count()) * W['life_mult']

        # SOBREVIVENCIA ciente do game_plan (pedido do usuario 14/07): se a
        # win-con do deck e um combo de CUSTO ALTO que ainda NAO da pra
        # disparar, minha propria vida vale mais — perder antes de chegar no
        # combo = derrota certa, entao o planner prefere a linha que preserva
        # vida/defesa a uma agressao arriscada. Generico via compute_game_plan
        # (zero nome de carta). Escala com a distancia ate poder disparar
        # (pending) e SATURA em 0 quando ja da (ai a "arma carregada"/dano
        # assumem) ou quando o deck nao tem combo caro (don_target baixo/None).
        # NAO impede racar: e premio sobre a MINHA vida, atacar o opp continua
        # valendo pelos termos de dano/vida do oponente.
        # So dispara sob RISCO REAL de morrer (vida <= 3): panico cresce quanto
        # mais baixa a vida. Vida alta = sem urgencia, NAO durdla (senao vira
        # passividade contra controle, que quer exatamente que voce durdle —
        # medido 14/07: premio ligado a vida cheia feria Krieg 0.53->0.27).
        try:
            _plano_surv = compute_game_plan(p)
            _dt = _plano_surv.get('don_target')
            if _dt and _dt >= 6:
                # So vale sobreviver pro combo se o OPONENTE me RACA (aggro): vs
                # CONTROLE, durdlar e exatamente o que ele quer -- ali eu preciso
                # PRESSIONAR. O perfil do opp decide (plano item 2 ponto 5: o
                # perfil do oponente muda o valor do MEU estado). Medido 14/07:
                # premio incondicional feria Krieg (controle) 0.53->0.27; gated
                # pelo arquetipo do opp, so liga vs Kid/aggro.
                _opp_prof = self._turn_profile_for(opp)
                _opp_ctrl = (_opp_prof or {}).get('archetype', {}).get('dominante') == 'Controle'
                if _opp_prof and not _opp_ctrl:
                    _pending = 1.0 - min(1.0, p.don_on_field() / _dt)
                    _panic = max(0, 4 - p.life_count())   # 0 em vida>=4, ate 3 em vida 1
                    if _pending > 0 and _panic > 0:
                        score += _panic * W['survival_premium'] * _pending
        except Exception:
            pass

        # board (reusa char_value_score — já vê blocker/rush/imunidade/efeito)
        score += sum(an.char_value_score(c) for c in p.field_chars) * W['board_mine']
        score -= sum(an.char_value_score(c) for c in opp.field_chars) * W['board_opp']

        # blockers do oponente vivos travam meu ataque
        score -= len(opp.blockers_active()) * W['opp_blocker']

        # mão: retorno decrescente (as primeiras cartas valem mais)
        nh = len(p.hand)
        score += min(nh, 5) * W['hand_first'] + max(0, nh - 5) * W['hand_extra']
        # poder de counter na mão = vida futura
        score += p.counter_in_hand() / 1000 * W['counter_hand']

        # DON no campo (ramp = chegar na bomba) — leve
        score += p.don_on_field() * W['don_field']

        # cobertura defensiva: counter na mão vs ataques que o opp faz no
        # próximo turno (líder + chars ativos). min = ter counter além do
        # necessário satura (não vale acumular counter infinito).
        opp_atk = 1 + sum(1 for c in opp.field_chars if not c.rested)
        cobertura = min(p.counter_in_hand(), opp_atk * 2000)
        score += cobertura / 1000 * W['coverage']

        # eixos derivados do perfil (auto-motor: trash/reanimação/inversão)
        score += self._derived_axes_value(p, self._turn_profile_for(p))

        return score

    def _apply_action(self, action, p, opp, ee, engine, verbose=False):
        """
        Executa UMA ação no estado dado (real ou cópia). Retorna True se venceu.
        Reúso entre o jogo real e a simulação do planner.
        """
        score, kind, obj, ttype, tgt = action

        if kind == 'play':
            self._play_card(obj, p, opp, ee, verbose=verbose)

        elif kind == 'activate':
            src = obj
            am = get_card_effects(src.code).get('activate_main', {})
            src._am_used_turn = p.turn
            self._log_decision(p, src, 'activate_main', 'activate', 'ação no planner')
            logs = ee.execute(src, 'activate_main')
            if verbose:
                print(f'    ⚙ ativou [Activate:Main] de {src.name[:22]}')
                for log in logs:
                    if log:
                        print(f'      ↳ {log}')
            if any(logs):
                desc = ' | '.join(l for l in logs if l)
                self._log_event(p, 'activate_main', card=src, description=desc)

        elif kind == 'attach_don':
            card, falta, what = obj, ttype, tgt
            anexar = min(falta, p.don_available)
            if anexar > 0:
                card.don_attached += anexar
                p.don_available -= anexar
                if verbose:
                    print(f'    ⚡ anexou {anexar} DON em {card.name[:20]} para ligar [{what}]')

        elif kind == 'attack':
            attacker = obj
            if attacker.rested:
                return False
            attached = self._attach_don_for_attack(attacker, ttype, tgt, p, opp, engine, verbose)
            if verbose:
                tgt_name = 'Leader' if ttype == 'leader' else (tgt.name[:20] if tgt else '?')
                print(f'    {attacker.name[:20]} ({attack_time_power(attacker, opp)}pwr) ataca {tgt_name}')
            if self._execute_attack(attacker, ttype, tgt, p, opp, engine, verbose=verbose,
                                    attached_don=attached):
                return True
        return False

    def _simulate_sequence(self, p, opp, first_action, max_steps=8, amostras=None):
        """
        Simula uma LINHA DE JOGO começando por first_action, numa CÓPIA do estado.
        Após a primeira ação, segue gulosamente (melhor ação a cada passo) até o
        fim do turno. Retorna o valor do estado final (para comparar linhas).

        A mão e vida REAIS de `opp` NUNCA são lidas dentro da simulação --
        são substituídas pelas amostras em `amostras` (lista de
        (hand_sample, life_sample), uma por rodada Monte Carlo -- gerada
        UMA VEZ por turno em main_phase e reusada entre todas as TOP_K
        candidatas, não regerada aqui). O valor final é a MÉDIA das N
        rodadas. Isso corrige a "trapaça" original (a simulação via a mão
        exata do oponente real para decidir blocker/counter) sem mudar
        nada na lógica de should_use_blocker/should_use_counter, que
        continuam idênticas — só passam a operar sobre a mão fictícia.

        Se `amostras` for None (ex: chamada legada sem Monte Carlo
        disponível), cai numa única rodada contra o estado real de opp.
        """
        valores = self._simulate_sequence_values(p, opp, first_action, max_steps, amostras)
        return sum(valores) / len(valores) if valores else -1e9

    def _simulate_sequence_values(self, p, opp, first_action, max_steps=8, amostras=None):
        """Retorna os valores por amostra Monte Carlo para auditoria do planner."""
        old_suppress = self._suppress_replay_log
        self._suppress_replay_log = True
        try:
            if not amostras:
                return [self._simulate_sequence_once(p, opp, first_action, max_steps, amostra=None)]

            return [
                self._simulate_sequence_once(p, opp, first_action, max_steps, amostra=amostra)
                for amostra in amostras
            ]
        finally:
            self._suppress_replay_log = old_suppress

    def _simulate_sequence_once(self, p, opp, first_action, max_steps=8, amostra=None):
        """
        Uma única rodada de simulação (ver _simulate_sequence para a versão
        agregada com Monte Carlo). `amostra` é uma tupla (hand_sample,
        life_sample) já sorteada -- esta função só aplica, não sorteia.
        Separada em método próprio para poder ser chamada N vezes com
        amostras diferentes sem duplicar a lógica de remap/apply/loop.
        """
        from copy import deepcopy
        # Optimizacao de deepcopy: zeramos os decks antes de clonar os estados
        # e os restauramos como copias rasas depois. Isso evita deepcopiar ~80+
        # Cards de uma vez (o gargalo dominante -- ~0.7ms dos ~1.2ms totais).
        #
        # Para opp.deck: seguro porque o oponente nao age durante a simulacao
        # do turno ativo, entao nenhuma carta sai do deck dele.
        # Para p.deck: usamos _SimDeck (lazy copy-on-pop) -- o wrapper faz
        # deepcopy SOMENTE das cartas efetivamente sacadas durante a simulacao
        # (normalmente 0-2 por chamada), nao de todo o deck de uma vez.
        # Correctness garantido: a carta original em p.deck nunca e mutada
        # (a mutacao ocorre no clone gerado pelo pop(), nao no objeto original).
        _p_deck = p.deck
        p.deck = []
        _opp_deck = opp.deck
        opp.deck = []
        p2 = deepcopy(p)
        opp2 = deepcopy(opp)
        p.deck = _p_deck
        opp.deck = _opp_deck
        p2.deck = _SimDeck(_p_deck)   # lazy copy-on-pop (ver _SimDeck no topo)
        opp2.deck = list(_opp_deck)   # lista rasa -- opp nao age, sem risco

        if amostra is not None:
            # Substitui mão e vida REAIS de opp2 pela amostra Monte Carlo
            # ANTES de qualquer ação ser aplicada -- nenhum código de
            # combate (should_use_blocker, should_use_counter, trigger ao
            # tomar dano) vê a mão/vida real do oponente a partir daqui.
            # As instâncias de Card na amostra são reusadas (mesmo objeto)
            # entre as TOP_K chamadas que recebem a mesma `amostra` desta
            # lista -- isso é seguro porque cada chamada já faz seu próprio
            # deepcopy de opp2 seria necessário SE a amostra fosse mutada,
            # mas should_use_blocker/should_use_counter apenas leem
            # power/counter das cartas, nunca mutam o objeto Card em si
            # (mutam GameState.hand/life, que já são listas novas aqui).
            hand_sample, life_sample = amostra
            opp2.hand = list(hand_sample)
            opp2.life = list(life_sample)

        eng2 = DecisionEngine(p2, opp2)
        ee2 = EffectExecutor(p2, opp2)

        # Mapeia a primeira ação para os objetos da cópia (por índice/identidade)
        first2 = self._remap_action(first_action, p, p2, opp, opp2)
        if first2 is None:
            return -1e9
        won = self._apply_action(first2, p2, opp2, ee2, eng2, verbose=False)
        if won:
            return SIMULATED_WIN_SCORE   # essa linha vence

        # Continua gulosamente até o fim do turno
        # activate_main agora compete como ação no _generate_and_score_actions,
        # então não precisa mais de chamada separada aqui.
        for _ in range(max_steps):
            acts = self._generate_and_score_actions(p2, opp2, eng2)
            if not acts or acts[0][0] < 0:
                break
            if self._apply_action(acts[0], p2, opp2, ee2, eng2, verbose=False):
                return SIMULATED_WIN_SCORE

        # ITEM 3 do plano (busca prof.2): simula o TURNO INTEIRO de RESPOSTA
        # do oponente (proprio engine dele, guloso — ver _play_turn_greedy)
        # ANTES de avaliar. Sem isto a avaliacao so via a foto no fim do MEU
        # turno, cega pra "ataquei seco -> ele countera barato e devolve" vs
        # "anexei DON -> passa/drena counter" -- a passividade sistemica que
        # o marco-zero mediu (don_por_atk baixo). `amostra` (mao/vida
        # ficticia de opp2, ja aplicada acima) e a mesma usada na resposta —
        # ficcao interna consistente, nao resorteia.
        if USE_OPPONENT_RESPONSE_SEARCH:
            if self._play_turn_greedy(opp2, p2):
                return -SIMULATED_WIN_SCORE   # a resposta dele me mata -> linha ruim

        # config de avaliação POR JOGADOR (p é quem age): permite Imu usar v2 e
        # o oponente v1 na mesma partida — como o sistema per-deck vai operar
        # (cada deck tem sua régua/pesos). None = cai no global USE_EVAL_V2.
        use_v2 = getattr(p, 'use_eval_v2', None)
        if use_v2 is None:
            use_v2 = USE_EVAL_V2
        if use_v2:
            return self._evaluate_state_v2(p2, opp2)
        return self._evaluate_state(p2, opp2)

    def _remap_action(self, action, p, p2, opp, opp2):
        """Remapeia uma ação do estado real para os objetos da cópia (por índice)."""
        score, kind, obj, ttype, tgt = action
        try:
            if kind == 'activate':
                # Remapeia source para o objeto equivalente na cópia
                if obj is p.leader:
                    return (score, kind, p2.leader, None, None)
                if obj is p.field_stage:
                    return (score, kind, p2.field_stage, None, None)
                if obj in p.field_chars:
                    return (score, kind, p2.field_chars[p.field_chars.index(obj)], None, None)
                return None
            if kind == 'play':
                idx = p.hand.index(obj)
                return (score, kind, p2.hand[idx], None, None)
            if kind == 'attach_don':
                idx = p.field_chars.index(obj) if obj in p.field_chars else None
                obj2 = p2.field_chars[idx] if idx is not None else (p2.leader if obj is p.leader else None)
                return (score, kind, obj2, ttype, tgt)
            if kind == 'attack':
                if obj is p.leader:
                    att2 = p2.leader
                else:
                    att2 = p2.field_chars[p.field_chars.index(obj)]
                if ttype == 'character' and tgt in opp.field_chars:
                    tgt2 = opp2.field_chars[opp.field_chars.index(tgt)]
                else:
                    tgt2 = None
                return (score, kind, att2, ttype, tgt2)
        except (ValueError, IndexError):
            return None
        return None

    def main_phase(self, p: GameState, opp: GameState, verbose: bool = False) -> bool:
        """
        Fase principal = LOOP DE PONTUAÇÃO DE JOGADAS (documento pág. 9).
        A cada passo: gera todas as ações possíveis, pontua, executa a melhor,
        reavalia o estado, repete. A ordem (jogar antes/depois de atacar) emerge
        das pontuações: cartas que habilitam ataque saem antes; desenvolvimento
        sai depois. Para quando nenhuma ação tem score acima do limiar.
        """
        engine = DecisionEngine(p, opp)
        ee     = EffectExecutor(p, opp)
        ee.apply_your_turn_buffs()

        if verbose:
            print('  -- Turno (Turn Planner: simula sequências) --')

        MAX_ACOES = 30
        # simula so as K acoes mais promissoras (custo controlado). Com a busca
        # de resposta do oponente (item 3) LIGADA, cada simulacao agora inclui
        # o turno INTEIRO de resposta dele -- medido 14/07: board cheio late-
        # game fez 1 partida ir de 5s pra 147s com K=6/S=6 (explosao O(board²)
        # por passo, multiplicada pelos dois turnos). Corta pro K≈3/S≈3 que o
        # PROPRIO plano ja recomendava ("top-K≈3 linhas minhas... S≈3
        # amostras") quando a busca de resposta esta ativa; K=6/S=6 (validado
        # em 13/07 sem a resposta) continua valendo com a flag desligada.
        TOP_K = 3 if USE_OPPONENT_RESPONSE_SEARCH else 6
        MIN_PLANNER_CANDIDATES = 3
        PLANNER_SCORE_WINDOW = 180
        n = 0

        while n < MAX_ACOES:
            n += 1
            actions = self._generate_and_score_actions(p, opp, engine)
            if not actions or actions[0][0] < 0:
                break
            priority = engine.analyzer.analysis_priority()

            # GamePlan fase 2b (auditor 10/07, flag D_win_con_parado): quando a
            # acao do topo e JOGAR a carta-bomba do plano e o DON ja paga, executa
            # DIRETO, sem passar pelo Monte Carlo. O valor da bomba se realiza no
            # turno SEGUINTE (ex: Five Elders reanima via activate_main no
            # proximo turno) — a simulacao de fim de turno nao enxerga isso e
            # escolhia linhas que gastavam o DON em outra coisa (Empty Throne
            # 3 DON primeiro), deixando a bomba impagavel de novo, todo turno.
            # O caminho AO VIVO (choose_action) ja pega o topo da lista direto —
            # este bypass so alinha o simulador interno ao mesmo comportamento.
            # Nao dispara em LETHAL: fechar a partida vem antes de desenvolver.
            if actions[0][1] == 'play' and priority != 'LETHAL':
                _top_card = actions[0][2]
                _plano = compute_game_plan(p)
                if (_plano['win_con_code'] and _top_card.code == _plano['win_con_code']
                        and _plano['don_target']
                        and p.don_available >= _plano['don_target']):
                    if self._apply_action(actions[0], p, opp, ee, engine, verbose=verbose):
                        return True
                    continue

            # TURN PLANNER: para as TOP_K ações candidatas, simula a linha de jogo
            # resultante e escolhe a que leva ao MELHOR estado de fim de turno.
            # (Em vez de escolher gulosamente a de maior score imediato.)
            #
            # As N amostras Monte Carlo do oponente são geradas UMA VEZ por
            # turno (aqui), não uma vez por candidata -- o estado observável
            # de `opp` é o mesmo para todas as TOP_K candidatas neste ponto
            # (nenhuma delas foi aplicada ainda), então gerar 6x N amostras
            # do zero seria 6x mais caro sem nenhum ganho de fidelidade.
            # Reusar as mesmas N amostras também torna a comparação entre
            # candidatas pareada (mesma "versão do oponente" testada contra
            # cada uma), reduzindo ruído Monte Carlo na escolha final.
            top_score = actions[0][0]
            candidatas = [
                acao for idx, acao in enumerate(actions[:TOP_K])
                if acao[0] >= 0
                and (idx < MIN_PLANNER_CANDIDATES or acao[0] >= top_score - PLANNER_SCORE_WINDOW)
            ]
            if priority == 'REMOVE_THREAT':
                # A remocao de uma ameaca critica pode receber score imediato
                # muito alto (ex.: Roger/Shanks), estreitando demais a janela.
                # Mantem essa pressao, mas garante diversidade para a simulacao
                # comparar pelo menos algumas linhas de desenvolvimento.
                seen_candidate_ids = {id(acao) for acao in candidatas}

                def include_best_kind(kind: str, limit: int):
                    current = sum(1 for acao in candidatas if acao[1] == kind)
                    for acao in actions:
                        if current >= limit:
                            break
                        if acao[0] < 0 or acao[1] != kind or id(acao) in seen_candidate_ids:
                            continue
                        candidatas.append(acao)
                        seen_candidate_ids.add(id(acao))
                        current += 1

                include_best_kind('play', 1)
                include_best_kind('activate', 1)
                candidatas.sort(key=lambda acao: acao[0], reverse=True)
            if len(candidatas) == 1:
                melhor_acao = candidatas[0]
                if self._is_unsafe_zero_life_leader_attack(melhor_acao, p, opp, engine):
                    break
                self._log_turn_planner_decision(
                    p, opp, engine, priority, actions, candidatas,
                    melhor_acao, None, {}
                )
                if self._apply_action(melhor_acao, p, opp, ee, engine, verbose=verbose):
                    return True
                continue

            model = self.model_for_a if p is self.state_a else self.model_for_b
            # mesmo corte de custo do TOP_K acima (ver comentario la): S≈3 com
            # a busca de resposta ligada, S=6 (ja validado) sem ela.
            n_monte_carlo = 3 if USE_OPPONENT_RESPONSE_SEARCH else PLANNER_MC_SAMPLES
            amostras_turno = [model.sample(opp, rng=random.Random()) for _ in range(n_monte_carlo)]

            melhor_acao = None
            melhor_valor = -1e18
            sim_values = {}
            for cand in candidatas:
                valores = self._simulate_sequence_values(p, opp, cand, amostras=amostras_turno)
                valor = sum(valores) / len(valores) if valores else -1e9
                wins = sum(1 for v in valores if v >= SIMULATED_WIN_SCORE)
                sim_values[id(cand)] = {
                    'avg': valor,
                    'wins': wins,
                    'samples': len(valores),
                }
                if self._is_unsafe_zero_life_leader_attack(cand, p, opp, engine) and wins == 0:
                    continue
                if valor > melhor_valor:
                    melhor_valor = valor
                    melhor_acao = cand

            if melhor_acao is None:
                break

            # Executa a primeira ação da melhor linha no estado REAL
            self._log_turn_planner_decision(
                p, opp, engine, priority, actions, candidatas,
                melhor_acao, sim_values.get(id(melhor_acao), melhor_valor), sim_values
            )
            if self._apply_action(melhor_acao, p, opp, ee, engine, verbose=verbose):
                return True

        for c in p.field_chars:
            c.just_played = False
        return False

    def _don_livre_for_plan(self, p, opp, engine) -> int:
        """
        DON ocioso do plano do turno: o que sobra do don_available depois
        (a) das jogadas/ativacoes que o Turn Planner ainda pretende fazer
        (acoes 'play'/'activate' com score >= 0, na ordem de preferencia,
        enquanto o DON alcanca) e (b) da reserva de defesa. So esse sobra
        vira margem de counter num ataque -- DON comprometido com o plano
        nunca e gasto a mais numa unica margem.

        'activate' entrou 14/07 (achado ao vivo, log 13.08.24): so 'play'
        reservava DON -- o Activate:Main da PROPRIA win-con ja em campo (ex:
        Five Elders, rest_don:1 pra reanimar 5 do trash) nunca tinha DON
        protegido, e o ataque seguinte (margem de counter) consumia o DON
        que faltava pra ativar o combo no MESMO turno. Mesmo padrao de
        reserva, so estende a cobertura pro tipo de acao que faltava.

        Fonte unica: antes so existia essa conta no caminho AO VIVO
        (sim_bridge.don_for_attack) -- o simulador interno
        (_attach_don_for_attack) chamava don_needed_for_attack sem
        don_livre (default None -> usa TODO o don_available como se
        estivesse ocioso). Achado real 10/07 (simulacao Teach vs Imu,
        winrate 6.7%): o Turn Planner anexava 9 DON numa unica declaracao
        de ataque (muito alem do necessario pra passar, sem ganho nenhum
        alem de 1 vida), esvaziando o DON que sobraria pra jogar Catarina
        Devon e outras cartas na mao no MESMO turno -- exatamente o padrao
        "desce carta barata, carta de peso fica parada" que o usuario
        reportou, so que a causa raiz era DON sendo desperdicado no
        ataque, nao um viés de avaliar_carta.
        """
        planejado = 0
        try:
            acts = self._generate_and_score_actions(p, opp, engine)
            for a in acts:
                if a[0] < 0:
                    break
                if a[1] == 'play':
                    custo = effective_hand_play_cost(p, a[2], opp)
                    if planejado + custo <= p.don_available:
                        planejado += custo
                elif a[1] == 'activate':
                    am = get_card_effects(a[2].code).get('activate_main', {})
                    custo = sum(c.get('count', 0) for c in am.get('costs', [])
                               if c.get('type') == 'rest_don')
                    if custo and planejado + custo <= p.don_available:
                        planejado += custo
            reserva = engine._don_reserve_for_defense()
        except Exception:
            planejado, reserva = 0, 0
        return max(0, p.don_available - planejado - reserva)

    def _attach_don_for_attack(self, attacker, ttype, tgt, p, opp, engine, verbose):
        """Anexa DON a este ataque, se ajudar a passar a defesa."""
        don_livre = self._don_livre_for_plan(p, opp, engine)
        need = don_needed_for_attack(attacker, ttype, tgt, p, opp, engine, don_livre=don_livre)
        if need > 0:
            attacker.don_attached += need
            p.don_available -= need
            if verbose:
                print(f'    anexou {need} DON em {attacker.name[:20]}')
        return need

    def _play_card(self, card: Card, p: GameState, opp: GameState,
                   ee: EffectExecutor, verbose: bool = False):
        """
        Joga uma carta.
        Efeitos executados APENAS via EffectExecutor — sem lógica duplicada.
        Com verbose=True, narra a jogada (para o replay). Silencioso por padrão
        (simulação em massa não passa verbose).
        """
        play_cost = effective_hand_play_cost(p, card, opp)
        # "The next time you play...": consome apenas regras cujo filtro
        # casa com ESTA carta. Jogar uma carta inelegivel nao gasta o buff.
        consume_play_cost_reductions(p, card)
        remove_by_identity(p.hand, card)
        p.don_rested  += play_cost
        p.don_available -= play_cost
        # Replay event: carta jogada
        self._log_event(p, 'play_card', card=card,
                        description=f'Jogou {card.name} (custo {play_cost} DON)',
                        phase='main')

        if verbose:
            don_txt = f'gastou {play_cost} DON' if play_cost > 0 else 'grátis'
            print(f'  > {don_txt} -> Joga: {card.name[:30]} '
                  f'({card.effective_power(True)}pwr) [{card.card_type}]')
            # Texto do efeito da carta (cinza) — para auditoria sem decorar
            txt = (card.card_text or '').strip()
            if txt:
                # primeira frase/linha do efeito, até ~90 chars
                short = txt.replace('\n', ' ')[:90]
                print(f'    \033[90mefeito: {short}{"..." if len(txt) > 90 else ""}\033[0m')

        if card.card_type == 'CHARACTER':
            if len(p.field_chars) >= 5:
                worst = min(p.field_chars, key=lambda c: c.board_value())
                remove_character_from_field(p, worst, 'trash')
                if verbose:
                    print(f'    campo cheio -> descartou {worst.name[:25]}')
            card.rested = False
            p.field_chars.append(card)
            apply_conditional_keyword_passives(p, opp)
            card.just_played = not (card.has_rush or card.rush_this_turn or card.is_rush_character())
            card.rush_character_only_this_turn = card.is_rush_character() and not card.is_rush()

        elif card.card_type == 'EVENT':
            p.trash.append(card)
            p.events_activated_costs_this_turn.append(card.cost)

        elif card.card_type == 'STAGE':
            if p.field_stage:
                p.trash.append(p.field_stage)
            p.field_stage = card

        # Executa efeito ao jogar a carta via EffectExecutor (único ponto).
        # Eventos e personagens podem ter o efeito em 'on_play' OU em 'main'
        # (cartas cujo texto começa com [Main]). Ao jogar, ambos disparam.
        logs = []
        logs += ee.execute(card, 'on_play')
        logs += ee.execute(card, 'main')
        if verbose:
            for log in logs:
                if log:
                    print(f'    ↳ [{card.name[:20]}] {log}')
        # Replay: log effects that fired
        effect_descs = [l for l in logs if l]
        if effect_descs:
            self._log_event(p, 'effect', card=card,
                            description='; '.join(effect_descs[:3]),
                            phase='main')

    def _execute_attack(self, attacker: Card, target_type: str,
                        target: Optional[Card], p: GameState,
                        opp: GameState, engine: DecisionEngine,
                        verbose: bool = False, attached_don: int = 0) -> bool:
        """
        Sequência: tap atacante → blocker → counter → damage.
        Com verbose, narra blocker/counter/dano.
        """
        if target_type == 'leader' and p.cannot_attack_leader_this_turn:
            if verbose:
                print('      ataque ao Leader bloqueado por efeito neste turno')
            return False

        if attacker is p.leader:
            p.leader.rested = True
        else:
            attacker.rested = True
        # Replay event: ataque declarado
        tgt_name = 'Leader' if target_type == 'leader' else (target.name if target else '?')
        atk_power_preview = live_attack_power(attacker)
        don_txt = f' anexando {attached_don} DON' if attached_don else ' sem anexar DON'
        self._log_event(p, 'attack', card=attacker, target=target if target_type != 'leader' else opp.leader,
                        description=f'{attacker.name} ataca {tgt_name}{don_txt} ({atk_power_preview} poder)',
                        phase='attack',
                        extra={'attached_don': attached_don, 'attack_power': atk_power_preview})

        # Paga o custo de lock_opp_attack_unless_pays (OP08-043), se o
        # atacante estiver sob essa trava. A viabilidade ja foi checada na
        # geracao da acao (can_afford_attack_paywall); re-checa aqui por
        # seguranca (defensivo, nao deve faltar carta na pratica).
        if attacker.attack_paywall:
            paywall = attacker.attack_paywall
            if paywall.get('cost_type') == 'trash_from_hand':
                cost_amount = min(paywall.get('cost_amount', 1), len(p.hand))
                pagas = []
                for _ in range(cost_amount):
                    pior = min(p.hand, key=lambda c: c.board_value())
                    remove_by_identity(p.hand, pior)
                    p.trash.append(pior)
                    pagas.append(pior.name[:15])
                if verbose and pagas:
                    print(f'      💸 {attacker.name[:18]} pagou pra atacar (trava): {", ".join(pagas)}')

        # Dispara efeito "when this character becomes rested" (when_rested),
        # se houver. Ocorre imediatamente apos o atacante ser restado, antes
        # do When Attacking -- segue a ordem real do texto da carta
        # (ex: OP14-119 Mihawk: "When this Character becomes rested, [efeito]").
        ee = EffectExecutor(p, opp)
        wr_logs = ee.execute(attacker, 'when_rested')
        if verbose:
            for log in wr_logs:
                if log:
                    print(f'      [quando restou] {log}')

        # Executa efeito When Attacking
        wa_logs = ee.execute(attacker, 'when_attacking')
        if verbose:
            for log in wa_logs:
                if log:
                    print(f'      ↳ [when attacking] {log}')

        # Executa [On Your Opponent's Attack] -- gatilho do DEFENSOR,
        # reage à declaração do ataque (qualquer Character/Leader dele
        # pode ter essa habilidade, não só o alvo). Achado 27/06: a tag
        # nunca tinha reconhecimento dedicado antes, caía em 'passive'
        # (nunca disparava de verdade -- 44 cartas, ex: Viola OP04-021,
        # Mr.9 EB01-037). Roda ANTES de calcular atk_power -- efeitos
        # como debuff_power (EB01-002 Izo) precisam valer pra ESTA
        # batalha, não depois que o dano já foi calculado.
        ee_react = EffectExecutor(opp, p)
        for reagente in [opp.leader] + list(opp.field_chars):
            oa_logs = ee_react.execute(reagente, 'on_opp_attack')
            if verbose:
                for log in oa_logs:
                    if log:
                        print(f'      ↳ [on opp attack: {reagente.name[:15]}] {log}')

        atk_power = live_attack_power(attacker)
        damage    = 2 if attacker.is_double_attack() else 1

        # Block step
        opp_engine = DecisionEngine(opp, p)
        blocker = opp_engine.should_use_blocker(atk_power)
        opp.blocker_lock_battle = None   # trava era so pra ESTA batalha -- limpa already-consumida
        if blocker and not attacker.has_unblockable and not attacker.unblockable_this_turn:
            target_type = 'character'
            target      = blocker
            blocker.rested = True
            if verbose:
                print(f'      🛡 Blocker! {blocker.name[:20]} intercepta')
            # [On Block]: efeito que dispara quando este personagem bloqueia.
            # Roda no contexto do oponente (dono do blocker).
            ob_effects = get_card_effects(blocker.code)
            if 'on_block' in ob_effects:
                ee_block = EffectExecutor(opp, p)
                ob_logs = ee_block.execute(blocker, 'on_block')
                if verbose:
                    for log in ob_logs:
                        if log:
                            print(f'      ⚡ [On Block] {log}')

            # Vitoria alternativa (OP09-118 Gol.D.Roger, achado 15/07):
            # "When your opponent activates [Blocker], if either you or
            # your opponent has 0 Life cards, you win the game." `p` aqui
            # e o ATACANTE (dono do Roger, se houver) -- `opp` acabou de
            # usar Blocker, ou seja e o "your opponent" da perspectiva de
            # `p`. Checa qualquer Character/Leader de `p` com essa
            # passiva; se algum tiver, e a vida de QUALQUER um dos dois
            # lados esta em 0, `p` vence a partida imediatamente.
            if p.life_count() == 0 or opp.life_count() == 0:
                fontes = [p.leader] + list(p.field_chars)
                for fonte in fontes:
                    passive = get_card_effects(fonte.code).get('passive', {})
                    if any(s.get('action') == 'win_game_on_opp_blocker'
                           for s in passive.get('steps', [])):
                        if verbose:
                            print(f'      🏆 {fonte.name[:20]}: vitoria alternativa '
                                  f'(oponente ativou Blocker com alguem em 0 vida)')
                        return True

        # Define poder de defesa
        if target_type == 'leader':
            defend_power = opp.leader.power + opp.leader.power_buff
        elif target and target in opp.field_chars:
            defend_power = target.power + target.power_buff
            # Rastreio de combate (achado 15/07, OP12-020 Zoro lider e
            # familia -- OP04-047/ST02-010/ST08-013): alvo final (ja
            # pos-blocker) e um Character do oponente -- registra que o
            # ATACANTE "battled" um Character neste turno. Setado aqui (nao
            # so na declaracao) pra cobrir corretamente o caso de blocker
            # redirect (atacar o Leader mas acabar batendo num Character).
            attacker.battled_opp_character_this_turn = True
        else:
            return False

        # Counter step
        if opp_engine.should_use_counter(atk_power, defend_power):
            counter_add = opp_engine.use_counter(atk_power - defend_power + 1)
            defend_power += counter_add
            if verbose and counter_add > 0:
                print(f'      🛡 Counter! +{counter_add} -> defesa {defend_power}')

        if atk_power >= defend_power:
            counter_target = opp.leader if target_type == 'leader' else target
            counter_event = ee_react.try_counter_event_power(
                counter_target,
                target_type,
                atk_power - defend_power + 1,
            )
            if counter_event:
                amount, counter_log = counter_event
                defend_power += amount
                if verbose:
                    print(f'      🛡 {counter_log} -> defesa {defend_power}')

        attacker_type = 'leader' if attacker is p.leader else 'character'

        # Counter event que enfraquece o ATACANTE em vez de buffar a propria
        # defesa -- mecanica distinta (ex: OP01-028, ST09-014). So tentado se
        # o buff acima nao bastou.
        if atk_power >= defend_power:
            counter_debuff = ee_react.try_counter_event_debuff(
                attacker,
                attacker_type,
                atk_power - defend_power + 1,
            )
            if counter_debuff:
                amount, counter_log = counter_debuff
                atk_power -= amount
                if verbose:
                    print(f'      🛡 {counter_log} -> ataque {atk_power}')

        # Counter event que da K.O. no ATACANTE inteiro -- cancela o ataque
        # por completo (sem dano), distinto dos dois mecanismos acima que so
        # ajustam power. So aplica a Characters atacando (Leaders nao sao
        # alvo de 'opp_character').
        if atk_power >= defend_power and attacker_type == 'character':
            ko_log = ee_react.try_counter_event_ko_attacker(attacker)
            if ko_log:
                if verbose:
                    print(f'      🛡 {ko_log} -> ataque cancelado')
                return False

        # Damage step
        if atk_power >= defend_power:
            if target_type == 'leader':
                # Vitória só se o oponente JÁ estava com 0 vidas ANTES deste ataque.
                # (Receber dano com 0 vidas = derrota.)
                if not opp.life:
                    p.dmg_dealt += 1
                    return True  # vitória: dano com 0 vidas

                # Tira até 'damage' vidas, UMA por vez, resolvendo trigger de cada.
                # Se a vida acabar durante o double attack, PARA — o dano extra
                # não causa derrota (regra: só compra as vidas que tem).
                for _ in range(damage):
                    if not opp.life:
                        break   # acabou a vida durante este ataque — não é derrota
                    life_card = opp.life.pop()
                    p.dmg_dealt += 1
                    # Banish: a vida vai DIRETO para o trash, sem ir para a mão
                    # e sem direito a trigger (regra oficial).
                    if attacker.has_banish:
                        opp.trash.append(life_card)
                        self._log_event(p, 'life_damage', card=attacker, target=life_card,
                            description=f'BANISH! vida de {(self._name_b if p is self.state_a else self._name_a)}: {opp.life_count()}',
                            phase='attack')
                        if verbose:
                            print(f'      💥 DANO (BANISH)! vida -> trash: {opp.life_count()}')
                    else:
                        # ST13-003 Luffy Leader: face-up life cards go to deck
                        # bottom instead of hand (passive rule change).
                        if life_card.life_face_up and opp.face_up_life_to_deck:
                            life_card.life_face_up = False
                            opp.deck.insert(0, life_card)
                        else:
                            opp.hand.append(life_card)
                        opp_name = self._name_b if p is self.state_a else self._name_a
                        self._log_event(p, 'life_damage', card=attacker, target=life_card,
                            description=f'Dano! vida de {opp_name}: {opp.life_count()} restantes',
                            phase='attack')
                        if verbose:
                            print(f'      💥 DANO! vida do oponente: {opp.life_count()}')
                    # O dano foi recebido mesmo em Banish; apenas o Trigger
                    # da carta de Life e bloqueado por Banish.
                    EffectExecutor(opp, p)._dispatch_damage_or_own_char_ko(opp)
                    if life_card.has_trigger and not attacker.has_banish:
                        opp.triggers_activated += 1
                        ee_opp = EffectExecutor(opp, p)
                        tg_logs = ee_opp.execute(life_card, 'trigger')
                        if verbose:
                            for log in tg_logs:
                                if log:
                                    print(f'      ⚡ [trigger] {log}')
                return False   # tirou vida(s), mas oponente não estava em 0 — sem derrota
            elif target_type == 'character' and target and target in opp.field_chars:
                # Imunidade a KO em combate. `is_immune` separa esta janela de
                # KO por efeito quando o texto bruto diz "in battle"/"by effects".
                if is_immune(
                    target,
                    'ko',
                    opp,
                    p,
                    source_is_opp=True,
                    ko_context='battle',
                    source_card=attacker,
                ):
                    if verbose:
                        print(f'      🛡 {target.name[:20]} imune a KO!')
                    return False
                ee_opp = EffectExecutor(opp, p)
                sub_log = ee_opp.try_any_substitute(target, 'ko', source_is_opp=True)
                if sub_log:
                    if verbose:
                        print(f'      🔁 {sub_log}')
                    return False
                counter_sub_log = ee_opp.try_counter_event_substitute(target, 'ko')
                if counter_sub_log:
                    if verbose:
                        print(f'      🔁 {counter_sub_log}')
                    return False
                remove_character_from_field(opp, target, 'trash')
                if verbose:
                    print(f'      💀 {target.name[:20]} foi KO!')
                ko_logs = ee_opp.execute(target, 'on_ko', is_opp_turn=True)
                ee_opp._dispatch_damage_or_own_char_ko(opp, target)
                if verbose:
                    for log in ko_logs:
                        if log:
                            print(f'      ↳ [on KO] {log}')
        else:
            if verbose:
                print(f'      ✗ Ataque bloqueado ({atk_power} < {defend_power})')

        return False

    # ── Decision audit logger ────────────────────────────────────────────────

    def enable_decision_audit(self):
        """Ativa o log de auditoria de decisão. Chamar antes de setup()/play_turn()."""
        self.decision_log = []

    def _log_decision(self, p: GameState, card, trigger: str,
                      decision: str, reason: str):
        """
        Registra uma decisão da IA sobre um efeito.
        decision: 'skip' | 'activate'
        reason:   texto livre explicando o motivo
        """
        if self.decision_log is None or self._suppress_replay_log:
            return
        player_id = 'A' if p is self.state_a else 'B'
        self.decision_log.append({
            'turn':    self.global_turn,
            'player':  player_id,
            'card':    card.code if card else '',
            'name':    card.name if card else '',
            'trigger': trigger,
            'decision': decision,
            'reason':  reason,
        })

    def _audit_card_brief(self, card):
        if card is None:
            return None
        if not hasattr(card, 'code'):
            return {'label': str(card)}
        return {
            'code': card.code,
            'name': card.name,
            'type': card.card_type,
            'cost': card.cost,
            'power': card.power,
            'current_power': card.effective_power(True),
            'rested': bool(getattr(card, 'rested', False)),
            'just_played': bool(getattr(card, 'just_played', False)),
            'don_attached': int(getattr(card, 'don_attached', 0)),
        }

    def _audit_action_brief(self, action, simulated_value=None):
        score, kind, obj, target_type, target = action
        sim_avg = simulated_value
        sim_wins = None
        sim_samples = None
        if isinstance(simulated_value, dict):
            sim_avg = simulated_value.get('avg')
            sim_wins = simulated_value.get('wins')
            sim_samples = simulated_value.get('samples')
        return {
            'score': round(float(score), 2),
            'simulated_value': (None if sim_avg is None
                                else round(float(sim_avg), 2)),
            'simulated_wins': sim_wins,
            'simulated_samples': sim_samples,
            'kind': kind,
            'card': self._audit_card_brief(obj),
            'target_type': target_type,
            'target': self._audit_card_brief(target),
        }

    def _log_turn_planner_decision(self, p: GameState, opp: GameState, engine,
                                   priority: str, actions: list, candidates: list,
                                   chosen, chosen_value, sim_values: dict):
        """Registra o ranking que levou o Turn Planner a escolher uma acao."""
        if self.decision_log is None or self._suppress_replay_log:
            return
        player_id = 'A' if p is self.state_a else 'B'
        top_immediate = actions[0] if actions else None
        chosen_card = chosen[2] if chosen else None
        self.decision_log.append({
            'kind': 'turn_planner',
            'turn': self.global_turn,
            'player': player_id,
            'decision': 'choose_action',
            'trigger': 'turn_planner',
            'card': chosen_card.code if chosen_card else '',
            'name': chosen_card.name if chosen_card else '',
            'reason': f'priority={priority}',
            'context': {
                'priority': priority,
                'posture': engine.posture(),
                'phase': engine.analyzer.game_phase(),
                'profile': engine.analyzer.deck_profile_type(),
                'life': p.life_count(),
                'opp_life': opp.life_count(),
                'hand': len(p.hand),
                'opp_hand': len(opp.hand),
                'field': len(p.field_chars),
                'opp_field': len(opp.field_chars),
                'don_available': p.don_available,
                'don_rested': p.don_rested,
                'can_lethal': engine.analyzer.can_lethal_this_turn(),
                'opp_lethal_threat': round(float(engine.analyzer.opp_lethal_threat()), 3),
            },
            'chosen': self._audit_action_brief(chosen, chosen_value) if chosen else None,
            'top_immediate': self._audit_action_brief(top_immediate) if top_immediate else None,
            'candidates': [
                self._audit_action_brief(a, sim_values.get(id(a)))
                for a in candidates[:8]
            ],
        })
        # DecisionTrace (ideia 2 do PDF): torna EXPLÍCITO "por que a alternativa
        # foi descartada" = margem de valor esperado abaixo da escolhida. Já
        # tínhamos os candidatos+valores; isto só rotula o gap pra leitura
        # humana/front (o valor bruto continua disponível pra depuração).
        rec = self.decision_log[-1]
        chosen_val = (rec['chosen'] or {}).get('simulated_value')
        if chosen_val is not None:
            for c in rec['candidates']:
                cv = c.get('simulated_value')
                if cv is None:
                    c['descartada_porque'] = 'linha inviável / sem simulação'
                elif abs(cv - chosen_val) < 1e-6:
                    c['descartada_porque'] = None   # é a escolhida (ou empate)
                else:
                    c['descartada_porque'] = f'valor esperado {round(chosen_val - cv, 1)} abaixo da escolhida'

    # ── Replay logger ────────────────────────────────────────────────────────

    def _log_event(self, p: GameState, event_type: str, card: 'Card' = None,
                   target: 'Card' = None, description: str = '', phase: str = 'main',
                   extra: dict = None):
        """Registra um evento estruturado se replay_log estiver ativo."""
        if self.replay_log is None or self._suppress_replay_log:
            return

        def card_dict(c):
            if c is None:
                return None
            return {
                'code':  c.code,
                'name':  c.name,
                'image': _CARD_IMAGE_CACHE.get(c.code, ''),
                'cost':  c.cost,
                'power': c.power,
                'type':  c.card_type,
                'color': c.color or '',
            }

        def state_dict(s: GameState):
            don_total = 10 - s.don_deck
            return {
                'leader': card_dict(s.leader),
                'life': s.life_count(),
                'hand': len(s.hand),
                'hand_cards': [
                    {
                        **card_dict(c),
                        'counter': c.counter,
                        'effective_cost': effective_hand_play_cost(
                            s, c, self.state_b if s is self.state_a else self.state_a),
                    }
                    for c in s.hand
                ],
                'deck': len(s.deck),
                'trash': len(s.trash),
                'don_available': s.don_available,
                'don_rested': s.don_rested,
                'don_total': don_total,
                'stage': card_dict(s.field_stage),
                'characters': [
                    {
                        **card_dict(c),
                        'rested': bool(getattr(c, 'rested', False)),
                        'current_power': c.effective_power(True),
                    }
                    for c in s.field_chars
                ],
                'stats': {
                    'damage': s.dmg_dealt,
                    'counters': s.counters_used,
                    'searchers': s.searchers_used,
                    'triggers': s.triggers_activated,
                },
            }

        player_id = 'A' if p is self.state_a else 'B'
        player_name = self._name_a if player_id == 'A' else self._name_b
        event = {
            'turn':        self.global_turn,
            'player':      player_id,
            'player_name': player_name,
            'phase':       phase,
            'type':        event_type,
            'card':        card_dict(card),
            'target':      card_dict(target),
            'description': description,
            'state':       {
                'A': state_dict(self.state_a),
                'B': state_dict(self.state_b),
            },
        }
        if extra:
            event.update(extra)
        self.replay_log.append(event)

    def simulate_replay(self, name_a: str = 'Player A', name_b: str = 'Player B') -> dict:
        """Roda uma partida completa capturando log estruturado de eventos.
        Retorna o mesmo dict de simulate() mais 'events' (lista de eventos
        por turno) e 'turns_detail' (eventos agrupados por turno)."""
        self.replay_log = []
        self._name_a = name_a
        self._name_b = name_b
        result = self.simulate()

        # Agrupa eventos por turno para o frontend navegar facilmente
        turns_detail = {}
        for ev in self.replay_log:
            t = ev['turn']
            turns_detail.setdefault(t, []).append(ev)

        result['events'] = self.replay_log
        result['turns_detail'] = [
            {'turn': t, 'events': evs}
            for t, evs in sorted(turns_detail.items())
        ]
        return result

    def _play_turn_greedy(self, p: 'GameState', opp: 'GameState', max_steps: int = 6) -> bool:
        """
        Joga UM turno completo de `p` (refresh->draw->don->acoes) GULOSAMENTE:
        sempre a acao de maior score IMEDIATO (_generate_and_score_actions),
        SEM Monte Carlo e SEM aninhar main_phase. Item 3 do plano
        (PLANO_AVALIACAO_E_BUSCA.md): usado por `_simulate_sequence_once` pra
        simular a RESPOSTA do oponente depois da MINHA linha, com o PROPRIO
        engine dele -- "modo guloso, sem aninhar" e explicito no plano
        justamente pra evitar explosao (main_phase ja roda TOP_K x MC
        simulacoes por decisao; chamar main_phase() de novo aqui multiplicaria
        isso por turno de resposta simulado). Motor unico: mesma
        _generate_and_score_actions/_apply_action que decide QUALQUER turno,
        sem regua propria -- serve pra qualquer deck de qualquer lado.

        Retorna True se `p` (quem esta jogando este turno) vence.
        """
        p.turn += 1
        p.is_active_turn = True
        opp.is_active_turn = False
        p.pending_play_cost_reductions.clear()
        self.refresh_phase(p, opp)
        self.draw_phase(p)
        self.don_phase(p)
        engine = DecisionEngine(p, opp)
        ee = EffectExecutor(p, opp)
        for _ in range(max_steps):
            acts = self._generate_and_score_actions(p, opp, engine)
            if not acts or acts[0][0] < 0:
                break
            if self._apply_action(acts[0], p, opp, ee, engine, verbose=False):
                return True
        self.end_phase(p, opp)
        for c in p.field_chars:
            c.just_played = False
        return False

    def play_turn(self, p: GameState, opp: GameState, verbose: bool = False) -> Optional[str]:
        self.global_turn += 1
        p.turn += 1
        p.global_turn = self.global_turn
        opp.global_turn = self.global_turn
        p.is_active_turn = True
        opp.is_active_turn = False
        p.pending_play_cost_reductions.clear()

        self._log_event(p, 'turn_start', phase='refresh',
                        description=f'Turno {self.global_turn} — refresh/compra/DON')
        self.refresh_phase(p, opp)

        # Log de compra de carta
        hand_before = len(p.hand)
        self.draw_phase(p, verbose=verbose)
        drawn = len(p.hand) - hand_before
        if drawn > 0:
            self._log_event(p, 'draw', phase='draw',
                            description=f'Comprou {drawn} carta(s)',
                            extra={'count': drawn})

        self.don_phase(p, verbose=verbose)

        if self.main_phase(p, opp, verbose=verbose):
            return 'A' if p is self.state_a else 'B'
        self.end_phase(p, opp, verbose=verbose)
        self._log_event(p, 'turn_end', phase='end',
                        description=f'Fim do turno {self.global_turn}')
        if not p.deck:
            return 'B' if p is self.state_a else 'A'
        if not opp.deck:
            return 'A' if p is self.state_a else 'B'
        return None

    def simulate(self) -> dict:
        self.setup()
        winner = None
        total_turns = 0

        # Ponteiro "quem joga agora" (achado 16/07, OP05-119 "take an
        # extra turn"): antes disso o loop decidia via turn_num % 2, uma
        # alternancia fixa sem estado -- nunca permitia o MESMO jogador
        # jogar duas vezes seguidas. Agora alterna normalmente apos cada
        # play_turn(), MAS repete o mesmo `p` (sem trocar pra `opp`) se
        # extra_turn_pending foi setado durante o turno que acabou de
        # rodar (consumido/resetado aqui, uma unica vez por turno extra
        # concedido). MAX_TURNS * 2 continua como teto de seguranca --
        # ainda conta CADA execucao de play_turn() como 1 iteracao, entao
        # turnos extras nao estouram o limite de chamadas, so mudam quem
        # joga em cada uma.
        p = self.state_a if self.state_a.is_first else self.state_b
        opp = self.state_b if p is self.state_a else self.state_a

        for _ in range(self.MAX_TURNS * 2):
            result = self.play_turn(p, opp)
            total_turns += 1
            if result:
                winner = result
                break
            if p.extra_turn_pending:
                p.extra_turn_pending = False
                # mesmo jogador de novo -- p/opp permanecem os mesmos
            else:
                p, opp = opp, p

        return {
            'winner':      winner or 'DRAW',
            'turns':       total_turns,
            'dmg_a':       self.state_a.dmg_dealt,
            'dmg_b':       self.state_b.dmg_dealt,
            'life_a':      self.state_a.life_count(),
            'life_b':      self.state_b.life_count(),
            'counters_a':  self.state_a.counters_used,
            'counters_b':  self.state_b.counters_used,
            'searchers_a': self.state_a.searchers_used,
            'searchers_b': self.state_b.searchers_used,
            'triggers_a':  self.state_a.triggers_activated,
            'triggers_b':  self.state_b.triggers_activated,
        }


# ===========================================================================
# Pipeline de simulação
# ===========================================================================

def simular_matchup(deck_a: tuple, deck_b: tuple, n: int = 100) -> dict:
    wins_a = wins_b = draws = 0
    total_turns = []
    counters_a = counters_b = searchers_a = searchers_b = triggers_a = triggers_b = 0

    for _ in range(n):
        match = OPTCGMatch(deck_a, deck_b)
        r = match.simulate()
        if r['winner'] == 'A':   wins_a += 1
        elif r['winner'] == 'B': wins_b += 1
        else:                    draws  += 1
        total_turns.append(r['turns'])
        counters_a  += r['counters_a'];  counters_b  += r['counters_b']
        searchers_a += r['searchers_a']; searchers_b += r['searchers_b']
        triggers_a  += r['triggers_a'];  triggers_b  += r['triggers_b']

    total     = wins_a + wins_b + draws
    avg_turns = sum(total_turns) / len(total_turns) if total_turns else 0

    return {
        'wins_a': wins_a, 'wins_b': wins_b, 'draws': draws,
        'winrate_a':      round(wins_a / total * 100, 1) if total > 0 else 50.0,
        'winrate_b':      round(wins_b / total * 100, 1) if total > 0 else 50.0,
        'avg_turns':      round(avg_turns, 1),
        'counters_pg_a':  round(counters_a  / total, 1) if total > 0 else 0,
        'counters_pg_b':  round(counters_b  / total, 1) if total > 0 else 0,
        'searchers_pg_a': round(searchers_a / total, 1) if total > 0 else 0,
        'searchers_pg_b': round(searchers_b / total, 1) if total > 0 else 0,
        'triggers_pg_a':  round(triggers_a  / total, 1) if total > 0 else 0,
        'triggers_pg_b':  round(triggers_b  / total, 1) if total > 0 else 0,
    }
