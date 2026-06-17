"""
synergy_states.py
=================
Camada 2 da análise: SINERGIAS (Formato A — estado compartilhado).

Cada carta pode CRIAR um estado de jogo e/ou EXPLORAR um estado.
Quando um deck tem cartas que criam o estado S e cartas que exploram S,
há sinergia — e isso reforça um arquétipo.

Esta camada é SEPARADA da pontuação de efeitos isolados (deck_analyzer),
para ser visível e depurável: o resultado final mostra quanto do arquétipo
veio dos efeitos e quanto veio das sinergias.

Mantido fora de gerar_effects_db para não misturar com o parser de efeitos.
"""
import re

# ── Definição dos estados ───────────────────────────────────────────────────
# Cada estado tem:
#   cria    : regex que indica que a carta CRIA o estado
#   explora : regex que indica que a carta EXPLORA o estado
#   arquetipo : para qual arquétipo a sinergia aponta (quando detectada)
#   peso    : força da sinergia (pontos adicionados ao arquétipo)
SYNERGY_STATES = {
    'char_restado': {
        'cria':    r'rest up to \d+ (of your opponent|of them)|set .{0,20}character.{0,10}as rested|rest \d+ of your opponent',
        'explora': r'rested character|that is rested|if .{0,15}is rested',
        'arquetipo': 'Controle',
        'peso': 3,
        'desc': 'Restar + punir restado',
    },
    'vida_ganha': {
        'cria':    r'to (the top of )?your life',
        'explora': r'\[trigger\]',
        'arquetipo': 'Vida/Triggers',
        'peso': 3,
        'desc': 'Ganhar vida + triggers (que vêm da vida)',
    },
    'opp_char_com_DON': {
        'cria':    r"give .{0,30}don!!.{0,30}opponent'?s? (character|leader)",
        'explora': r'with \d+ or more don!!|that has \d+ or more don',
        'arquetipo': 'Controle',
        'peso': 4,
        'desc': 'DON ao oponente + punir quem tem DON (engine Krieg)',
    },
}


def detect_card_states(card_text: str) -> dict:
    """Para uma carta, retorna {estado: {'creates': bool, 'requires': bool}}."""
    t = (card_text or '').lower()
    out = {}
    for state, cfg in SYNERGY_STATES.items():
        creates = bool(re.search(cfg['cria'], t))
        requires = bool(re.search(cfg['explora'], t))
        if creates or requires:
            out[state] = {'creates': creates, 'requires': requires}
    return out


def detect_deck_synergies(main_cards: list) -> list:
    """
    Recebe a lista de cartas do deck. Retorna as sinergias ativas (Formato A
    + Formato B). Cada sinergia: {state, desc, arquetipo, n_creators,
    n_exploiters, score}.
    """
    active = _synergies_format_a(main_cards)
    active += _synergies_format_b(main_cards)
    active += _synergies_don_payoff(main_cards)
    return active


# ── Item 3: give_don a aliado + cartas [DON!! xN] (payoff de DON) ───────────
# Dar DON a um aliado só vale se houver aliados que ficam melhores com DON.
# A DIREÇÃO (aggro/controle) vem do que esses aliados [DON!! xN] fazem:
#   efeito de KO/rest/debuff -> Controle ; rush/power/double -> Aggro
_CONTROL_ACTIONS = {'ko', 'rest_opp_character', 'bounce', 'debuff_power',
                    'debuff_cost', 'trash_from_hand', 'lock_opp_don', 'give_don_opp'}
_AGGRO_ACTIONS = {'buff_power', 'keyword_rush', 'gain_rush', 'keyword_double_attack',
                  'gain_double_attack', 'keyword_unblockable', 'gain_unblockable'}


def _synergies_don_payoff(main_cards: list) -> list:
    givers = 0           # cartas que dão DON a aliado
    payoffs_ctrl = 0     # cartas [DON xN] com efeito de controle
    payoffs_aggro = 0    # cartas [DON xN] com efeito de aggro

    for card in main_cards:
        effects = card.get('effects', [])
        for eff in effects:
            if eff.get('action') == 'give_don':
                givers += 1
            if eff.get('don_requirement'):
                act = eff.get('action')
                if act in _CONTROL_ACTIONS:
                    payoffs_ctrl += 1
                elif act in _AGGRO_ACTIONS:
                    payoffs_aggro += 1

    active = []
    if givers >= 1 and (payoffs_ctrl + payoffs_aggro) >= 1:
        # a direção dominante define o arquétipo da sinergia
        if payoffs_aggro >= payoffs_ctrl:
            arche, n = 'Aggro', payoffs_aggro
        else:
            arche, n = 'Controle', payoffs_ctrl
        strength = min(givers, payoffs_ctrl + payoffs_aggro)
        active.append({
            'state': 'don_payoff',
            'desc': f'Dar DON a aliado + cartas [DON xN] ({arche.lower()})',
            'arquetipo': arche,
            'n_creators': givers,
            'n_exploiters': payoffs_ctrl + payoffs_aggro,
            'score': strength * 3,
        })
    return active


def _synergies_format_a(main_cards: list) -> list:
    """Formato A: estado compartilhado (uma carta cria, outra explora)."""
    creators = {s: 0 for s in SYNERGY_STATES}
    exploiters = {s: 0 for s in SYNERGY_STATES}

    for card in main_cards:
        states = card.get('synergy_states') or detect_card_states(card.get('text', ''))
        for state, flags in states.items():
            if flags.get('creates'):
                creators[state] += 1
            if flags.get('requires'):
                exploiters[state] += 1

    active = []
    for state, cfg in SYNERGY_STATES.items():
        c, e = creators[state], exploiters[state]
        if c >= 1 and e >= 1:
            strength = min(c, e)
            active.append({
                'state': state,
                'desc': cfg['desc'],
                'arquetipo': cfg['arquetipo'],
                'n_creators': c,
                'n_exploiters': e,
                'score': strength * cfg['peso'],
            })
    return active


# ── Formato B: sinergia por ATRIBUTO do efeito ─────────────────────────────
# Uma carta com KO condicionado a poder/custo combina com cartas que reduzem
# aquele mesmo atributo no oponente (a redução amplia o alcance do KO).
FORMAT_B_SYNERGIES = {
    'ko_poder_x_debuff_poder': {
        'lado_a': lambda eff: eff.get('action') == 'ko' and 'power_lte' in eff,
        'lado_b': lambda eff: eff.get('action') == 'debuff_power',
        'arquetipo': 'Controle',
        'peso': 3,
        'desc': 'KO por poder + redução de poder (controle por poder)',
    },
    'ko_custo_x_debuff_custo': {
        'lado_a': lambda eff: eff.get('action') == 'ko' and 'cost_lte' in eff,
        'lado_b': lambda eff: eff.get('action') == 'debuff_cost',
        'arquetipo': 'Controle',
        'peso': 3,
        'desc': 'KO por custo + redução de custo (controle por custo)',
    },
}


def _synergies_format_b(main_cards: list) -> list:
    """Formato B: KO por atributo + redução do mesmo atributo."""
    active = []
    for key, cfg in FORMAT_B_SYNERGIES.items():
        a = b = 0
        for card in main_cards:
            for eff in card.get('effects', []):
                if cfg['lado_a'](eff):
                    a += 1
                if cfg['lado_b'](eff):
                    b += 1
        if a >= 1 and b >= 1:
            strength = min(a, b)
            active.append({
                'state': key,
                'desc': cfg['desc'],
                'arquetipo': cfg['arquetipo'],
                'n_creators': a,
                'n_exploiters': b,
                'score': strength * cfg['peso'],
            })
    return active