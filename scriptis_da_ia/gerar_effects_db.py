"""
gerar_effects_db.py
====================
Gera card_effects_db.json a partir do cards_rows.csv.
Baseado na logica DoV3ActionStep das 34k linhas do Assembly-CSharp.dll v1.40a.

Uso:
    python gerar_effects_db.py
"""

import pandas as pd
import json
import re


# ===========================================================================
# Parsers de condicoes
# ===========================================================================

def parse_conditions(text):
    conds = {}
    t = text.lower()

    m = re.search(r'if you have (\d+) or less life', t)
    if m: conds['life_lte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more life', t)
    if m: conds['life_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more cards? in your trash', t)
    if m: conds['trash_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more don!!', t)
    if m: conds['don_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more don!! cards? on your field', t)
    if m: conds['don_on_field_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more characters?', t)
    if m: conds['chars_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or less cards? in your hand', t)
    if m: conds['hand_lte'] = int(m.group(1))

    m = re.search(r'if your leader is \[([^\]]+)\]', t)
    if m: conds['leader_is'] = m.group(1)

    m = re.search(r"if your leaders? type includes? [\"']?([^\"'\n,]+)[\"']?", t)
    if m: conds['leader_type_includes'] = m.group(1).strip()

    # "if your leader has the X type" — X entre aspas, colchetes ou chaves
    m = re.search(r'if your leader has (?:the )?["\[{]([^"\]}]+)["\]}] type', t)
    if m: conds['leader_type'] = m.group(1).strip()

    if 'if your leader is multicolored' in t:
        conds['leader_multicolor'] = True

    return conds


def parse_costs(text):
    costs = []
    t = text.lower()

    if re.search(r'rest this (card|character|stage)', t):
        costs.append({'type': 'rest_self'})

    if re.search(r'trash this (character|card)', t):
        costs.append({'type': 'trash_self'})

    m = re.search(r'rest (\d+) of your don!!', t)
    if m:
        costs.append({'type': 'rest_don', 'count': int(m.group(1))})

    # Custo de trash da mao/campo (antes do efeito principal, padrão "...: efeito")
    # Captura variações: "trash N cards from your hand", "trash 1 [type] Character
    # or 1 card from your hand", "trash 1 of your Characters", etc.
    # O custo vem ANTES de um ':' que separa custo do benefício.
    m = re.search(r'you may trash (\d+)[^:]*?(?:from your hand|character|card)[^:]*:', t)
    if m:
        costs.append({'type': 'trash_from_hand', 'count': int(m.group(1))})
    else:
        # padrão mais simples sem "you may" (custo obrigatório com ':')
        m = re.search(r'\btrash (\d+) cards? from your hand\s*:', t)
        if m:
            costs.append({'type': 'trash_from_hand', 'count': int(m.group(1))})

    # DON!! −X: devolve X DON do campo para o deck de DON.
    # "you may" perto (antes ou depois, ex: dentro do parêntese explicativo)
    # -> opcional; senão -> obrigatório.
    m = re.search(r'don!!\s*[−\-‐]\s*(\d+)', t)
    if m:
        x = int(m.group(1))
        idx = m.start()
        janela = t[max(0, idx-40):idx+60]   # olha antes E depois
        opcional = 'you may' in janela
        costs.append({'type': 'don_minus', 'count': x, 'optional': opcional})

    return costs


# ===========================================================================
# Parsers de efeitos individuais
# ===========================================================================

def parse_look_at(text):
    """
    StartTopDeck + AddToHand + FinalizeTopDeck conforme 34k linhas.
    Dois destinos para o resto: deck_bottom_rest ou trash_rest.
    """
    steps = []
    t = text.lower()

    m = re.search(r'look at (\d+) cards?', t)
    if not m:
        return steps
    look_count = int(m.group(1))
    steps.append({'action': 'look_top_deck', 'count': look_count})

    # Quantas pega
    take_m = re.search(r'(?:reveal|add|play) up to (\d+)', t)
    take_count = int(take_m.group(1)) if take_m else 1

    # Filtro
    filter_type = None
    exclude = []

    fm = re.search(r'reveal up to \d+ "([^"]+)" (?:type |or [^\n]+)?(?:character )?card', t)
    if fm:
        filter_type = fm.group(1)

    if not filter_type:
        fm = re.search(r'reveal up to \d+ \[([^\]]+)\]', t)
        if fm:
            filter_type = fm.group(1)

    # "other than [X]"
    ex = re.search(r'other than \[([^\]]+)\]', t)
    if ex:
        exclude = [ex.group(1)]

    cost_m = re.search(r'with a cost of (\d+) or less', t)
    power_m = re.search(r'with (\d+) power or less', t)

    take_step = {
        'action': 'add_to_hand',
        'count': take_count,
    }
    if filter_type:
        take_step['filter_type'] = filter_type
    if exclude:
        take_step['exclude'] = exclude
    if cost_m:
        take_step['cost_lte'] = int(cost_m.group(1))
    if power_m:
        take_step['power_lte'] = int(power_m.group(1))

    steps.append(take_step)

    # Destino do resto — conforme FinalizeTopDeck das 34k linhas
    if 'trash the rest' in t:
        steps.append({'action': 'trash_rest'})
        # "trash 1 card from your hand" apos trash the rest (Saint Shalria, etc.)
        m2 = re.search(r'trash the rest.*?trash (\d+) card from your hand', t, re.DOTALL)
        if m2:
            steps.append({'action': 'trash_from_hand', 'count': int(m2.group(1))})
    elif 'place the rest at the bottom' in t:
        steps.append({'action': 'deck_bottom_rest'})
    elif 'place the rest at the top' in t:
        steps.append({'action': 'deck_top_rest'})
    elif 'place them at the top or bottom' in t:
        steps.append({'action': 'deck_reorder_rest'})

    return steps


def parse_ko(text):
    steps = []
    t = text.lower()

    # KO stage
    m = re.search(r"k\.o\. up to (\d+) of your opponent.{0,20} stages?", t)
    if m:
        cost_m = re.search(r'with a cost of (\d+)', t)
        steps.append({
            'action': 'ko',
            'count': int(m.group(1)),
            'target': 'opp_stage',
            'cost_lte': int(cost_m.group(1)) if cost_m else 99
        })
        return steps

    # KO personagem com custo
    m = re.search(r"k\.o\. up to (\d+) of your opponent.{0,20} characters? with a cost of (\d+) or less", t)
    if m:
        step = {
            'action': 'ko',
            'count': int(m.group(1)),
            'target': 'opp_character',
            'cost_lte': int(m.group(2))
        }
        if 'rested' in t:
            step['rested_only'] = True
        steps.append(step)
        return steps

    # KO personagem com PODER (with N (base) power or less)
    m = re.search(r"k\.o\. up to (\d+) of your opponent.{0,20} characters? with (?:a )?(\d+) (?:base )?power or less", t)
    if m:
        step = {
            'action': 'ko',
            'count': int(m.group(1)),
            'target': 'opp_character',
            'power_lte': int(m.group(2))
        }
        if 'rested' in t:
            step['rested_only'] = True
        steps.append(step)
        return steps

    # KO generico
    m = re.search(r"k\.o\. up to (\d+) of your opponent.{0,20} characters?", t)
    if m:
        steps.append({
            'action': 'ko',
            'count': int(m.group(1)),
            'target': 'opp_character',
        })

    return steps


def parse_bounce(text):
    steps = []
    t = text.lower()

    m = re.search(r"return up to (\d+) of your opponent.{0,20} characters? with a cost of (\d+) or less", t)
    if m:
        steps.append({
            'action': 'bounce',
            'count': int(m.group(1)),
            'target': 'opp_character',
            'cost_lte': int(m.group(2))
        })
        return steps

    m = re.search(r"return up to (\d+) of your opponent.{0,20} characters?", t)
    if m:
        steps.append({'action': 'bounce', 'count': int(m.group(1)), 'target': 'opp_character'})

    return steps


def parse_rest_opp(text):
    steps = []
    t = text.lower()

    m = re.search(r"rest up to (\d+) of your opponent.{0,10} characters? (?:with a cost of (\d+) or|that has)", t)
    if m:
        cost_m = re.search(r'cost of (\d+) or', t)
        steps.append({
            'action': 'rest_opp_character',
            'count': int(m.group(1)),
            'cost_lte': int(cost_m.group(1)) if cost_m else 99
        })
        return steps

    m = re.search(r"rest up to (\d+) of your opponent.{0,20} characters?", t)
    if m:
        steps.append({'action': 'rest_opp_character', 'count': int(m.group(1))})

    return steps


def parse_draw(text):
    steps = []
    t = text.lower()

    m = re.search(r'draw (\d+) cards?', t)
    if m:
        step = {'action': 'draw', 'count': int(m.group(1))}
        trash_m = re.search(r'draw \d+ cards? and trash (\d+)', t)
        if trash_m:
            step['then_trash'] = int(trash_m.group(1))
        steps.append(step)
    elif 'draw a card' in t:
        steps.append({'action': 'draw', 'count': 1})

    return steps


def parse_power_buff(text):
    steps = []
    t = text.lower()

    m = re.search(r'([+\-−])(\d+)\s*power', t)
    if not m:
        return steps

    sign = m.group(1)
    amount = int(m.group(2))
    is_debuff = sign in ('-', '−')
    target = 'self'
    duration = 'this_turn'

    # debuff normalmente mira o oponente
    if is_debuff or "opponent" in t:
        if "opponent's leader" in t:
            target = 'opp_leader'
        elif "opponent's character" in t or "opponent" in t:
            target = 'opp_character'
    if 'your leader or 1 of your characters' in t:
        target = 'leader_or_character'
    elif 'all of your' in t and "leader" in t:
        target = 'all_allies_and_leader'
    elif 'all of your characters' in t:
        target = 'all_allies'
    elif 'your leader' in t and not is_debuff:
        target = 'leader'
    elif ('this character' in t or 'this card' in t) and not is_debuff:
        target = 'self'

    if 'until the start of your' in t:
        duration = 'until_my_turn_start'
    elif "until the start of your opponent" in t:
        duration = 'until_opp_turn_start'
    elif "until the end of your opponent" in t:
        duration = 'until_opp_turn_end'
    elif 'during this battle' in t:
        duration = 'battle_only'
    elif 'this turn' in t:
        duration = 'this_turn'

    steps.append({
        'action': 'debuff_power' if is_debuff else 'buff_power',
        'amount': amount, 'target': target, 'duration': duration
    })
    return steps


def parse_give_don(text):
    steps = []
    t = text.lower()

    # Dar/anexar DON — distinguir alvo (aliado vs oponente)
    m = re.search(r'give up to (\d+) (?:rested )?don!!', t)
    if m:
        cnt = int(m.group(1))
        # alvo: se menciona "opponent" perto, é setup no oponente (controle)
        # senão é buff em personagem próprio (aggro)
        to_opp = bool(re.search(r"to .{0,30}opponent's (leader|character)", t)) or \
                 bool(re.search(r"opponent's characters?:?\s*$", t))
        steps.append({
            'action': 'give_don_opp' if to_opp else 'give_don',
            'count': cnt,
        })

    # Aceleração REAL: adicionar DON do seu deck de DON ao seu campo (ramp)
    if re.search(r'add up to \d+ don!! cards? from your don!! deck|add \d+ don!! cards? from your don!! deck', t):
        m2 = re.search(r'add up to (\d+) don!! cards?|add (\d+) don!! cards?', t)
        if m2:
            steps.append({'action': 'add_don', 'count': int(m2.group(1) or m2.group(2))})

    # Reativar DON (set as active) = aceleração
    if re.search(r'set (?:up to )?\d* ?(?:of your )?don!! cards?.* as active', t):
        steps.append({'action': 'set_don_active'})

    # Trava de DON do oponente: "will not become active" (controle de recurso)
    if re.search(r"opponent's .{0,30}will not become active|will not become active", t):
        steps.append({'action': 'lock_opp_don'})

    return steps


def parse_play_from_trash(text):
    steps = []
    t = text.lower()

    m = re.search(r'play up to (\d+) .{0,20}type (?:stage|character) card.{0,30}from your trash', t)
    if m:
        type_m = re.search(r'play up to \d+ "?([a-z][a-z0-9 .]+)"? type', t)
        cost_m = re.search(r'with a cost of (\d+) or less', t)
        steps.append({
            'action': 'play_from_trash',
            'count': int(m.group(1)),
            'filter_type': type_m.group(1).strip() if type_m else '',
            'cost_lte': int(cost_m.group(1)) if cost_m else 99
        })

    return steps


def parse_play_from_deck(text):
    steps = []
    t = text.lower()

    m = re.search(r'play up to (\d+) .{0,20}type character card.{0,40}from your deck', t)
    if m:
        type_m = re.search(r'play up to \d+ (?:black |red |blue |green |yellow |purple )?"?([a-z][a-z0-9 .]+)"? type', t)
        cost_m = re.search(r'with a cost of (\d+) or less', t)
        color_m = re.search(r'play up to \d+ (black|red|blue|green|yellow|purple)', t)
        steps.append({
            'action': 'play_from_deck',
            'count': int(m.group(1)),
            'filter_type': type_m.group(1).strip() if type_m else '',
            'cost_lte': int(cost_m.group(1)) if cost_m else 99,
            'color': color_m.group(1) if color_m else None
        })

    return steps


def parse_play_generic(text):
    """Play sem origem explícita: 'Play this card', 'Play up to N ... Character card'."""
    steps = []
    t = text.lower()
    if 'play this card' in t:
        steps.append({'action': 'play_card', 'count': 1, 'source': 'self'})
        return steps
    m = re.search(r'play up to (\d+) [^.]*?(?:character|stage) card', t)
    if m and 'from your deck' not in t and 'from your trash' not in t:
        cost_m = re.search(r'with a cost of (\d+) or less', t)
        steps.append({
            'action': 'play_card', 'count': int(m.group(1)),
            'cost_lte': int(cost_m.group(1)) if cost_m else 99,
        })
    return steps


def parse_cost_debuff(text):
    """Give -N cost / +N cost (manipulação de custo)."""
    steps = []
    t = text.lower()
    m = re.search(r'give [^.]*?([+\-−])(\d+) cost', t)
    if m:
        is_debuff = m.group(1) in ('-', '−')
        target = 'opp_character' if "opponent" in t[:m.start()+len(m.group(0))] else 'own_character'
        steps.append({
            'action': 'debuff_cost' if is_debuff else 'buff_cost',
            'amount': int(m.group(2)), 'target': target,
        })
    return steps


def parse_heal(text):
    steps = []
    t = text.lower()

    m = re.search(r'add (\d+) cards? from the top of your deck to the bottom of your life', t)
    if m:
        steps.append({'action': 'heal', 'count': int(m.group(1))})

    return steps


def parse_life(text):
    """
    Manipulação de vida em três direções (sinais de arquétipo diferentes):
      - gain_life   : adiciona à SUA vida (defensivo → Vida/Triggers)
      - attack_life : remove da vida do OPONENTE (ofensivo → Aggro/Controle)
      - trash_own_life : descarta da SUA vida como custo/troca (engine)
    Cobre variações de redação ("to the top/bottom of your Life", "up to N").
    """
    steps = []
    t = text.lower()

    # quantidade genérica (N ou "up to N"); default 1 quando não especifica
    def qty_near(keyword_idx):
        seg = t[max(0, keyword_idx - 60):keyword_idx]
        m = re.search(r'(?:up to |add )?(\d+) cards?', seg)
        return int(m.group(1)) if m else 1

    # ── Ganha a própria vida ───────────────────────────────────────────
    m = re.search(r'to (?:the (?:top|bottom) of )?your life', t)
    if m and 'trash' not in t[:m.start()]:
        # garante que é ADIÇÃO (add/put), não trash
        if re.search(r'(add|put)[^.]*your life', t):
            steps.append({'action': 'gain_life', 'count': qty_near(m.start())})

    # ── Ataca a vida do oponente ───────────────────────────────────────
    m = re.search(r"opponent's life", t)
    if m:
        # trash da vida do oponente OU fazer oponente add (ambos ofensivos)
        if re.search(r"trash[^.]*opponent's life", t):
            steps.append({'action': 'attack_life', 'count': qty_near(m.start())})

    # ── Descarta a própria vida (custo/troca) ──────────────────────────
    m = re.search(r'trash[^.]*from (?:the top of )?your life', t)
    if m:
        steps.append({'action': 'trash_own_life', 'count': qty_near(m.start())})

    return steps


def parse_add_from_trash(text):
    steps = []
    t = text.lower()

    m = re.search(r'add up to (\d+) \[([^\]]+)\] from your trash to your hand', t)
    if m:
        steps.append({
            'action': 'add_from_trash',
            'count': int(m.group(1)),
            'filter_name': m.group(2)
        })

    return steps


# ===========================================================================
# Parser principal de um bloco de texto
# ===========================================================================

def parse_block(block_text, trigger_name):
    """Parseia um bloco de efeito e retorna lista de steps."""
    steps = []
    t = block_text.lower()

    # Busca
    if 'look at' in t:
        steps.extend(parse_look_at(t))

    # KO
    if 'k.o.' in t:
        steps.extend(parse_ko(t))

    # Bounce
    if 'return' in t and 'hand' in t and 'opponent' in t:
        steps.extend(parse_bounce(t))

    # Restar oponente
    if 'rest up to' in t and 'opponent' in t:
        steps.extend(parse_rest_opp(t))

    # Draw (sem look at)
    if 'draw' in t and 'look at' not in t:
        steps.extend(parse_draw(t))

    # Power buff/debuff
    if 'power' in t and ('+' in t or '-' in t or '−' in t):
        steps.extend(parse_power_buff(t))

    # Custo: give -N/+N cost
    if 'cost' in t and ('give' in t) and ('-' in t or '−' in t or '+' in t):
        steps.extend(parse_cost_debuff(t))

    # Play genérico (sem origem explícita)
    if 'play ' in t:
        steps.extend(parse_play_generic(t))

    # DON: give, add (ramp), set active
    if 'don' in t and ('give' in t or 'add' in t or 'set' in t):
        steps.extend(parse_give_don(t))

    # Play from trash
    if 'from your trash' in t and 'play up to' in t:
        steps.extend(parse_play_from_trash(t))

    # Play from deck
    if 'from your deck' in t and 'play up to' in t and 'look at' not in t:
        steps.extend(parse_play_from_deck(t))

    # Heal (vida pelo fundo, redação clássica)
    if 'bottom of your life' in t:
        steps.extend(parse_heal(t))

    # Manipulação de vida (3 direções: ganhar / atacar oponente / trashar própria)
    if 'life' in t:
        steps.extend(parse_life(t))

    # Add from trash
    if 'from your trash to your hand' in t:
        steps.extend(parse_add_from_trash(t))

    # Keywords concedidas
    if 'gain [rush]' in t or 'gains [rush]' in t:
        steps.append({'action': 'gain_rush'})
    if 'gain [blocker]' in t or 'gains [blocker]' in t:
        steps.append({'action': 'gain_blocker'})
    if 'gain [double attack]' in t or 'gains [double attack]' in t:
        steps.append({'action': 'gain_double_attack'})
    if 'gain [banish]' in t or 'gains [banish]' in t:
        steps.append({'action': 'gain_banish'})
    if 'gain [unblockable]' in t or 'gains [unblockable]' in t:
        steps.append({'action': 'gain_unblockable'})

    # Trash from hand (efeito, nao custo)
    if trigger_name in ('on_play', 'when_attacking', 'end_of_turn'):
        m = re.search(r'trash (\d+) cards? from your hand', t)
        # NÃO duplicar: se já foi tratado pelo bloco "trash the rest ... trash
        # N card from your hand" (look_top_deck), não detectar de novo aqui.
        already = bool(re.search(r'trash the rest.*?trash \d+ card from your hand', t, re.DOTALL))
        if m and 'you may trash' not in t[:t.find('trash')] and not already:
            steps.append({'action': 'trash_from_hand', 'count': int(m.group(1))})

    # Trigger especial: "Activate this card's [Main] effect"
    if trigger_name == 'trigger' and 'activate this card' in t:
        return [{'action': 'activate_main_effect'}]

    return steps


# ===========================================================================
# Parser completo de uma carta
# ===========================================================================

def parse_card_effect(card_text, card_type):
    if not card_text or str(card_text) == 'nan':
        return {}

    t = str(card_text)
    t_low = t.lower()
    result = {}

    # Mapa de triggers → regex para extrair o bloco de texto
    trigger_patterns = [
        ('on_play',       r'\[on play\](.+?)(?=\[(?:on play|activate|when attacking|on k\.o\.|trigger|counter|your turn|end of your turn|blocker|rush|double attack|banish|unblockable)\]|$)'),
        ('activate_main', r'\[activate:?\s*main\](.+?)(?=\[(?:on play|when attacking|on k\.o\.|trigger|counter|your turn|end of your turn)\]|$)'),
        ('when_attacking',r'\[when attacking\](.+?)(?=\[(?:on play|activate|on k\.o\.|trigger|counter|your turn|end of your turn)\]|$)'),
        ('on_ko',         r'\[on k\.o\.\](.+?)(?=\[(?:on play|activate|when attacking|trigger|counter|your turn|end of your turn)\]|$)'),
        ('your_turn',     r'\[your turn\](.+?)(?=\[(?:on play|activate|when attacking|on k\.o\.|trigger|counter|end of your turn)\]|$)'),
        ('opp_turn',      r"\[opponent.{0,3}s? turn\](.+?)(?=\[(?:on play|activate|when attacking|on k\.o\.|trigger|counter|your turn|end of your turn)\]|$)"),
        ('trigger',       r'\[trigger\](.+?)(?=\[(?:on play|activate|when attacking|on k\.o\.|counter|your turn|end of your turn)\]|$)'),
        ('counter',       r'\[counter\](.+?)(?=\[(?:on play|activate|when attacking|on k\.o\.|trigger|your turn|end of your turn)\]|$)'),
        ('end_of_turn',   r'\[end of your turn\](.+?)(?=\[(?:on play|activate|when attacking|trigger|counter|on block)\]|$)'),
        ('on_block',      r'\[on block\](.+?)(?=\[(?:on play|activate|when attacking|on k\.o\.|trigger|counter|your turn|end of your turn)\]|$)'),
        ('main',          r'\[main\](.+?)(?=\[(?:trigger|counter|on play|activate|when attacking|on k\.o\.|your turn|end of your turn)\]|$)'),
    ]

    for trigger_name, pattern in trigger_patterns:
        m = re.search(pattern, t_low, re.DOTALL | re.IGNORECASE)
        if not m:
            continue

        block = m.group(1).strip()
        if not block:
            continue

        steps = parse_block(block, trigger_name)
        if not steps:
            continue

        conds = parse_conditions(block)
        costs = parse_costs(block)
        once = '[once per turn]' in t_low

        # DON x requisito antes do trigger. Usa a posição real do match (m.start)
        # em vez de reconstruir o nome — assim funciona para [Activate: Main],
        # [On K.O.], etc., onde o nome tem pontuação/variações.
        don_req = 0
        trigger_pos = m.start()
        pre_trigger = t_low[:trigger_pos]
        don_m = re.search(r'\[don!! x(\d+)\]', pre_trigger[-50:])
        if don_m:
            don_req = int(don_m.group(1))

        entry = {'steps': steps}
        if conds:
            entry['conditions'] = conds
        if costs:
            entry['costs'] = costs
        if once:
            entry['once_per_turn'] = True
        if don_req:
            entry['don_requirement'] = don_req

        result[trigger_name] = entry

    # Keywords — distinguir NATIVA (sempre ligada) de CONDICIONAL a [DON!! ×N].
    # Ex: "[DON!! x1] This Character gains [Blocker]" -> blocker só com 1 DON anexado.
    def keyword_don_req(keyword_tag):
        """Se a keyword vem logo após um [DON!! ×N], retorna N; senão 0."""
        idx = t_low.find(keyword_tag)
        if idx < 0:
            return 0
        # olha os ~60 chars antes da keyword por um [DON!! ×N] e 'gains'
        janela = t_low[max(0, idx-60):idx]
        m = re.search(r'\[don!! x(\d+)\]', janela)
        if m and ('gain' in janela or 'gains' in janela):
            return int(m.group(1))
        return 0

    passive_steps = []
    cond_keywords = []   # keywords que exigem DON anexado

    for tag, action in [('[blocker]', 'keyword_blocker'),
                        ('[rush]', 'keyword_rush'),
                        ('[double attack]', 'keyword_double_attack'),
                        ('[banish]', 'keyword_banish'),
                        ('[unblockable]', 'keyword_unblockable')]:
        if tag not in t_low:
            continue
        # evita capturar "gains [rush]" como passivo nativo
        if tag in ('[rush]', '[banish]') and f'gains {tag}' in t_low and keyword_don_req(tag) == 0:
            continue
        req = keyword_don_req(tag)
        if req > 0:
            cond_keywords.append({'action': action, 'don_requirement': req})
        else:
            passive_steps.append({'action': action})

    if passive_steps:
        result['passive'] = {'steps': passive_steps}
    if cond_keywords:
        # keywords condicionais a DON ficam separadas, com seu requisito
        result['don_conditional_keywords'] = {'steps': cond_keywords}

    # Your Turn passivo de poder (sem trigger explicito)
    your_turn_power = re.search(r'\[your turn\].{0,60}\+(\d+)\s*power', t_low)
    if your_turn_power and 'your_turn' not in result:
        result['your_turn'] = {
            'steps': [{'action': 'buff_power', 'amount': int(your_turn_power.group(1)),
                       'target': 'self', 'duration': 'your_turn'}]
        }

    return result


# ===========================================================================
# Gerador principal
# ===========================================================================

def generate_effects_db(csv_path):
    df = pd.read_csv(csv_path)
    df['code'] = df['card_set_id'].fillna('').astype(str).str.split('_').str[0]
    df_unique = df.drop_duplicates(subset='code', keep='first')

    db = {}

    for _, row in df_unique.iterrows():
        code = str(row['code']).strip()
        if not code or code == 'nan':
            continue

        card_text = str(row.get('card_text') or '')
        card_type = str(row.get('card_type') or '').upper()

        try:
            counter_raw = str(row.get('counter_amount', '') or '').replace('.0', '')
            counter = int(counter_raw) if counter_raw.isdigit() else 0
        except:
            counter = 0

        try: cost = int(float(row.get('card_cost') or 0))
        except: cost = 0
        try: power = int(float(row.get('card_power') or 0))
        except: power = 0
        try: life = int(float(row.get('life') or 0))
        except: life = 0

        db[code] = {
            'name':      str(row.get('card_name') or ''),
            'type':      card_type,
            'cost':      cost,
            'power':     power,
            'counter':   counter,
            'life':      life,
            'color':     str(row.get('card_color') or ''),
            'sub_types': str(row.get('sub_types') or ''),
            'effects':   parse_card_effect(card_text, card_type),
        }

    return db


if __name__ == '__main__':
    print('Gerando card_effects_db.json...')
    db = generate_effects_db('cards_rows.csv')

    with open('card_effects_db.json', 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    total = len(db)
    with_effects = sum(1 for v in db.values() if v['effects'])
    print(f'Total de cartas: {total}')
    print(f'Com efeitos: {with_effects} ({with_effects/total*100:.1f}%)')
    print(f'Sem efeitos: {total - with_effects}')

    # Valida cartas chave
    tests = {
        'OP13-086': 'Saint Shalria',
        'OP13-099': 'The Empty Throne',
        'OP13-092': 'Saint Mjosgard',
        'OP13-082': 'Five Elders',
        'PRB02-008': 'Marco',
        'OP13-042': 'Edward Newgate SP',
        'OP13-046': 'Vista',
    }
    print()
    for code, name in tests.items():
        if code in db:
            efx = db[code]['effects']
            print(f'{code} - {name}:')
            for trigger, data in efx.items():
                steps_str = ', '.join(s.get('action','?') for s in data.get('steps', []))
                conds_str = str(data.get('conditions', ''))
                print(f'  [{trigger}] {steps_str}' + (f' IF {conds_str}' if conds_str != '{}' else ''))
        else:
            print(f'{code}: NAO ENCONTRADO')
    print()
    print('Arquivo salvo: card_effects_db.json')