"""
deck_analyzer.py
================
Análise estática de deck para o produto GRÁTIS (analisador de listas).

Roda sobre o Mundo A. NÃO simula partidas — só estrutura.
Entrada: lista de cartas do deck builder. Saída: dict de análise.

Esta é a versão Python testável. Depois de validada, porta-se para
TypeScript (deck-analyzer.ts) no front.

Detecção de arquétipo em 3 camadas (precisão decrescente, cobertura crescente):
  1. mapa de líder  → preciso, exige tabela
  2. cor do líder   → bom, cobre líderes novos; multicolor desempata p/ camada 3
  3. estrutura      → curva + keywords; sempre funciona
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional
from synergy_states import detect_deck_synergies
from tribal_cohesion import compute_tribal_cohesion

# Peso moderado da sinergia (Camada 2) ao somar com efeitos isolados (Camada 1).
# Começa em 0.5 para a sinergia reforçar sem dominar; calibrável.
SYNERGY_WEIGHT = 0.5


# ===========================================================================
# Arquétipos
# ===========================================================================

# Arquétipos + pesos de ação vêm do VOCABULÁRIO ÚNICO (card_taxonomy),
# compartilhado com o motor (deck_profile). Antes eram definidos aqui e
# duplicavam a gramática — unificado 13/07.
from card_taxonomy import (AGGRO, CONTROLE, RAMP, VIDA, ARCHETYPES,  # noqa: F401
                           ACTION_WEIGHTS, TRIGGER_RELIABILITY)      # noqa: F401


# ── Camada 1: mapa de líder conhecido → arquétipo ───────────────────────────
# Chave = código base do líder (sem sufixo de arte). Começa com os
# S-tier do meta atual + exemplos clássicos. CRESCE conforme necessário.
# Fonte: meta OP-16 (jun/2026) e identidades de cor consagradas.
LEADER_ARCHETYPE: dict[str, str] = {
    # Aggro
    'ST01-001': AGGRO,   # Luffy (Red, starter aggro)
    'OP01-001': AGGRO,   # Roronoa Zoro (Red)
    'OP07-001': AGGRO,   # ex. Red rush
    # Controle (Preto)
    'OP08-079': CONTROLE,  # Rob Lucci (Black)
    'OP09-001': CONTROLE,  # exemplos Black control
    # Tempo/Ramp (Roxo/Verde)
    'OP05-060': RAMP,    # Kaido (Purple ramp)
    'OP12-001': RAMP,    # Bonney
    # Vida/Triggers (Amarelo)
    'OP05-098': VIDA,    # Enel (Yellow)
}


# ── Camada 2: cor → arquétipo (identidade de cor) ───────────────────────────
COLOR_ARCHETYPE: dict[str, str] = {
    'Red':    AGGRO,
    'Black':  CONTROLE,
    'Purple': RAMP,
    'Green':  RAMP,
    'Yellow': VIDA,
    'Blue':   CONTROLE,  # Azul tende a tempo/controle (bounce); aproximação
}


# ACTION_WEIGHTS e TRIGGER_RELIABILITY agora vêm de card_taxonomy (import no
# topo) — vocabulário único compartilhado com o motor.


# ===========================================================================
# Resultado da detecção
# ===========================================================================

@dataclass
class ArchetypeResult:
    archetype: str                       # arquétipo dominante
    source: str                          # 'leader' | 'color' | 'structure'
    confidence: str                      # 'alta' | 'média' | 'baixa'
    mix: dict[str, float] = field(default_factory=dict)  # {arquétipo: %}
    note: str = ''
    synergies: list = field(default_factory=list)  # sinergias detectadas (Camada 2)

    def label(self) -> str:
        """Texto pronto p/ exibir: 'Tempo/Ramp (70%) + Aggro (30%)'."""
        if not self.mix:
            return self.archetype
        parts = sorted(self.mix.items(), key=lambda kv: -kv[1])
        parts = [(a, p) for a, p in parts if p >= 5]  # ignora ruído <5%
        return ' + '.join(f'{a} ({round(p)}%)' for a, p in parts)


def _base_code(card_set_id: str) -> str:
    return (card_set_id or '').split('_')[0]


def _colors_of(color_str: str) -> list[str]:
    """'Green Red' -> ['Green','Red']. Lida com espaço e barra."""
    return [c for c in (color_str or '').replace('/', ' ').split() if c]


def detect_archetype(leader: dict, main_cards: list[dict]) -> ArchetypeResult:
    """
    leader: dict com ao menos {code, color}
    main_cards: lista de dicts (uma entrada por CÓPIA) com flags de comportamento
    """
    code = _base_code(leader.get('code', ''))
    leader_colors = _colors_of(leader.get('color', ''))

    # ── Camada 1: líder conhecido (override manual de meta) ────────────────
    if code in LEADER_ARCHETYPE:
        arche = LEADER_ARCHETYPE[code]
        return ArchetypeResult(arche, 'leader', 'alta',
                               {arche: 100.0}, 'classificado pelo líder')

    # ── Camada 2: comportamento das cartas (PRIMÁRIO) ──────────────────────
    behavior_score = _behavior_mix(main_cards)

    # ── Camada 2: sinergias (estado criado × estado explorado) ─────────────
    synergies = detect_deck_synergies(main_cards)
    for syn in synergies:
        arche = syn['arquetipo']
        if arche in behavior_score:
            behavior_score[arche] += syn['score'] * SYNERGY_WEIGHT

    total_signal = sum(behavior_score.values())

    if total_signal >= 8:  # sinal de comportamento suficiente para confiar
        mix = _normalize(behavior_score)
        dominant = max(mix, key=mix.get)
        top = mix[dominant]
        conf = 'alta' if top >= 50 else ('média' if top >= 38 else 'baixa')
        return ArchetypeResult(dominant, 'behavior', conf, mix,
                               'inferido pelo comportamento + sinergias',
                               synergies=synergies)

    # ── Camada 3: cor como desempate (pouco sinal de comportamento) ────────
    if leader_colors:
        cmix = _color_mix(leader_colors, main_cards)
        if cmix:
            # combina o pouco sinal de comportamento com a cor
            for a, v in behavior_score.items():
                cmix[a] = cmix.get(a, 0) + v * 2  # comportamento ainda pesa
            mix = _normalize(cmix)
            dominant = max(mix, key=mix.get)
            return ArchetypeResult(dominant, 'color', 'baixa', mix,
                                   f'pouco sinal de cartas; cor como base ({" ".join(leader_colors)})')

    # ── Camada 4: estrutura (último recurso) ───────────────────────────────
    arche = _infer_from_structure(main_cards)
    return ArchetypeResult(arche, 'structure', 'baixa',
                           {arche: 100.0}, 'inferido pela estrutura')


def _behavior_mix(main_cards: list[dict]) -> dict[str, float]:
    """
    Soma os pesos de arquétipo percorrendo os EFEITOS de cada carta (já por
    cópia), multiplicando o peso da ação pelo fator de confiabilidade do
    gatilho que a dispara. On Play vale cheio; Trigger/On K.O. valem menos.
    """
    score: dict[str, float] = {AGGRO: 0.0, CONTROLE: 0.0, RAMP: 0.0, VIDA: 0.0}
    for card in main_cards:
        effects = card.get('effects', [])
        if not effects:
            continue
        for eff in effects:
            action = eff.get('action')
            trigger = eff.get('trigger', 'on_play')
            weights = ACTION_WEIGHTS.get(action)
            if not weights:
                continue
            factor = TRIGGER_RELIABILITY.get(trigger, 0.7)
            for arche, pts in weights.items():
                score[arche] += pts * factor
    return score


def _normalize(score: dict[str, float]) -> dict[str, float]:
    """Converte pontuação bruta em percentuais que somam 100."""
    total = sum(score.values())
    if total == 0:
        return {}
    return {a: round(100 * v / total, 1) for a, v in score.items() if v > 0}


def _color_mix(leader_colors: list[str], main_cards: list[dict]) -> dict[str, float]:
    """
    Pondera o arquétipo pela quantidade de cartas de cada cor do líder
    presentes no deck. Cartas bicolor contam meio p/ cada cor (salvaguarda;
    hoje não há cartas de deck bicolor). Retorna {arquétipo: percentual}.
    """
    # peso por COR (quantas cartas de cada cor do líder há no deck)
    color_weight: dict[str, float] = {c: 0.0 for c in leader_colors}
    for card in main_cards:
        ccolors = _colors_of(card.get('color', ''))
        # só conta cores que pertencem à identidade do líder
        relevant = [c for c in ccolors if c in color_weight]
        if not relevant:
            continue
        share = 1.0 / len(relevant)  # meio a meio se bicolor
        for c in relevant:
            color_weight[c] += share

    total = sum(color_weight.values())
    if total == 0:
        return {}

    # converte peso de cor → peso de arquétipo
    arche_weight: dict[str, float] = {}
    for color, w in color_weight.items():
        arche = COLOR_ARCHETYPE.get(color)
        if arche:
            arche_weight[arche] = arche_weight.get(arche, 0.0) + w

    tot = sum(arche_weight.values())
    if tot == 0:
        return {}
    return {a: round(100 * w / tot, 1) for a, w in arche_weight.items()}


def _infer_from_structure(main_cards: list[dict]) -> str:
    """
    Desempate por curva e keywords. Heurística simples:
      - muita carta barata + rush  → Aggro
      - muita removal              → Controle
      - curva alta + custo médio   → Tempo/Ramp
      - muito counter/trigger      → Vida/Triggers
    """
    if not main_cards:
        return RAMP  # neutro

    n = len(main_cards)
    avg_cost = sum(c.get('cost', 0) for c in main_cards) / n
    rush = sum(1 for c in main_cards if c.get('has_rush'))
    removal = sum(1 for c in main_cards if c.get('is_removal'))
    triggers = sum(1 for c in main_cards if c.get('has_trigger'))
    low_cost = sum(1 for c in main_cards if c.get('cost', 0) <= 3)

    scores = {
        AGGRO:    (rush * 2) + low_cost + (5 if avg_cost <= 3 else 0),
        CONTROLE: removal * 3,
        RAMP:     (5 if avg_cost >= 5 else 0) + sum(1 for c in main_cards if c.get('cost', 0) >= 7),
        VIDA:     triggers * 2,
    }
    return max(scores, key=scores.get)


# ===========================================================================
# Golden Ratios — consenso de meta (jun/2026)
# Fonte: faixas gerais de construção competitiva. Os NÚMEROS são consenso;
# o CONSELHO é contextualizado por arquétipo (Forma A). Não inventamos
# faixas por arquétipo — isso ficaria para a análise por IA (produto pago).
# ===========================================================================

# (mínimo_ideal, máximo_ideal) por categoria
GOLDEN_RATIOS = {
    'counters':  (8, 12),   # cartas com counter 2000 (defesa)
    'searchers': (4, 8),    # busca (consistência)
    'blockers':  (4, 8),    # blockers (defesa de vida)
    'finishers': (2, 4),    # custo alto 8-10 (fechar o jogo)
    'events':    (0, 6),    # eventos (não sobrecarregar)
}


@dataclass
class CategoryCheck:
    name: str
    count: int
    ideal_min: int
    ideal_max: int
    status: str        # 'baixo' | 'ok' | 'alto'
    advice: str


def _count_categories(main_cards: list[dict]) -> dict[str, int]:
    counters  = sum(1 for c in main_cards if c.get('counter', 0) >= 2000)
    searchers = sum(1 for c in main_cards if c.get('is_searcher'))
    blockers  = sum(1 for c in main_cards if c.get('is_blocker'))
    finishers = sum(1 for c in main_cards if c.get('cost', 0) >= 8)
    events    = sum(1 for c in main_cards if c.get('type', '').upper() == 'EVENT')
    return {
        'counters': counters, 'searchers': searchers,
        'blockers': blockers, 'finishers': finishers, 'events': events,
    }


# Conselho contextualizado por arquétipo: o número-alvo é o consenso,
# o tom muda conforme o estilo do deck.
def _advice(cat: str, status: str, archetype: str) -> str:
    if status == 'ok':
        return 'dentro do recomendado'

    base = {
        ('counters', 'baixo'):  'poucos counters de 2000 — defesa frágil',
        ('counters', 'alto'):   'muitos counters — pode faltar agressão',
        ('searchers', 'baixo'): 'poucos searchers — consistência baixa, deck pode travar',
        ('searchers', 'alto'):  'searchers em excesso — pode faltar ameaça',
        ('blockers', 'baixo'):  'poucos blockers — vida exposta a ataques',
        ('blockers', 'alto'):   'muitos blockers — board pouco ofensivo',
        ('finishers', 'baixo'): 'poucos finishers — pode faltar como fechar o jogo',
        ('finishers', 'alto'):  'finishers demais — risco de travar a mão cedo',
        ('events', 'alto'):     'eventos demais — faltam corpos no board para atacar',
    }.get((cat, status), '')

    # tempero por arquétipo
    if cat == 'counters' and status == 'baixo':
        if archetype == AGGRO:
            return base + ' (tolerável num deck agressivo, mas cuidado)'
        if archetype in (CONTROLE, VIDA):
            return base + ' (crítico para um deck que precisa sobreviver)'
    if cat == 'finishers' and status == 'baixo' and archetype == AGGRO:
        return base + ' (menos grave: o plano é fechar cedo)'
    if cat == 'searchers' and status == 'baixo' and archetype == CONTROLE:
        return base + ' (controle depende de achar as peças certas)'
    return base


def analyze_ratios(main_cards: list[dict], archetype: str) -> list[CategoryCheck]:
    counts = _count_categories(main_cards)
    checks = []
    for cat, (lo, hi) in GOLDEN_RATIOS.items():
        n = counts[cat]
        status = 'baixo' if n < lo else ('alto' if n > hi else 'ok')
        checks.append(CategoryCheck(
            cat, n, lo, hi, status, _advice(cat, status, archetype)))
    return checks


# ── Curva de custo ──────────────────────────────────────────────────────────
def cost_curve(main_cards: list[dict]) -> dict[int, int]:
    curve = {}
    for c in main_cards:
        cost = c.get('cost', 0)
        curve[cost] = curve.get(cost, 0) + 1
    return dict(sorted(curve.items()))


# ===========================================================================
# Análise completa — ponto de entrada
# ===========================================================================

def analyze_deck(leader: dict, main_cards: list[dict]) -> dict:
    """
    Recebe líder + cartas (cada uma é um registro do card_analysis_db.json
    multiplicado pela quantidade). Retorna análise estruturada para o front.
    """
    arche = detect_archetype(leader, main_cards)
    ratios = analyze_ratios(main_cards, arche.archetype)
    curve = cost_curve(main_cards)
    cohesion = compute_tribal_cohesion(leader, main_cards)

    n_issues = sum(1 for c in ratios if c.status != 'ok')

    return {
        'deck_size': len(main_cards),
        'archetype': {
            'primary': arche.archetype,
            'label': arche.label(),
            'source': arche.source,
            'confidence': arche.confidence,
            'mix': arche.mix,
            'note': arche.note,
        },
        'synergies': arche.synergies,
        'tribal_cohesion': cohesion,
        'ratios': [
            {'name': c.name, 'count': c.count,
             'ideal': [c.ideal_min, c.ideal_max],
             'status': c.status, 'advice': c.advice}
            for c in ratios
        ],
        'curve': curve,
        'issues_count': n_issues,
        'avg_cost': round(sum(c.get('cost', 0) for c in main_cards) / max(len(main_cards), 1), 2),
    }