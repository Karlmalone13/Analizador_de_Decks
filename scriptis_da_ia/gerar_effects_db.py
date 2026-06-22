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

    # "if you have a Character with N power or more [other than this
    # Character]" -- existe outro Character no SEU campo com power >= N.
    m = re.search(r'if you have a character with (\d+) power or more', t)
    if m: conds['other_char_power_gte'] = int(m.group(1))

    # "if you have a Character with a cost of N or more" -- idem, por custo.
    m = re.search(r'if you have a character with a cost of (\d+) or more', t)
    if m: conds['other_char_cost_gte'] = int(m.group(1))

    # "if this Character has N power or more" -- auto-referencia (o proprio
    # Character que carrega o efeito).
    m = re.search(r'if this character has (\d+) power or more', t)
    if m: conds['self_power_gte'] = int(m.group(1))

    # "if your [TIPO] type Character would be ..." -- restringe o PROPRIO
    # Character que carrega o efeito a um tipo (sub_types) especifico.
    # Distinto de leader_type: aqui e o tipo do Character com o efeito, nao
    # do Leader. Duas variantes de redacao: "your "X" type Character" e
    # "your Character with a type including "X"".
    m = (re.search(r'if your ["\[{]([^"\]}]+)["\]}] type character (?:would|gains?|has)', t)
         or re.search(r'if your character with a type including ["\[{]([^"\]}]+)["\]}] would', t))
    if m: conds['self_type'] = m.group(1).strip()

    # "if your Leader has N power or more" -- power BASE do Leader (pode
    # vir junto com type, ex: "...power or more and the \"X\" type").
    m = re.search(r'if your leader has (\d+) power or more', t)
    if m: conds['leader_power_gte'] = int(m.group(1))

    # "if your opponent has a Character with N power or more" -- existe
    # Character no campo do OPONENTE com power >= N (distinto de
    # other_char_power_gte, que e sobre o PROPRIO campo).
    m = re.search(r'if your opponent has a character with (\d+) power or more', t)
    if m: conds['opp_char_power_gte'] = int(m.group(1))

    # Variante combinada: "...power or more and the "X"/[X]/{X} type" --
    # captura o type quando vem encadeado depois da clausula de power (a
    # regex leader_type/leader_type_includes acima nao cobre esse encadeamento).
    if 'leader_power_gte' in conds and 'leader_type' not in conds and 'leader_type_includes' not in conds:
        m = re.search(r'power or more and (?:the )?["\[{]([^"\]}]+)["\]}] type', t)
        if m: conds['leader_type'] = m.group(1).strip()

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

    # Custo de power no PROPRIO lider/character (ex: "you may give your active
    # leader -5000 power during this turn: [efeito]"). So conta como custo se
    # vier ANTES de um ':' (separador custo->efeito) e o alvo for proprio
    # (your leader/character), nao do oponente.
    m = re.search(r"give your[^:]*?(?:leader|character)[^:]*?[−\-]\s*(\d+)\s*power[^:]*:", t)
    if m:
        amount = int(m.group(1))
        idx = m.start()
        janela = t[max(0, idx-30):idx]
        opcional = 'you may' in janela
        target = 'leader' if 'leader' in m.group(0) and 'character' not in m.group(0).split('leader')[0] else 'leader_or_character'
        costs.append({'type': 'debuff_power_self', 'amount': amount, 'optional': opcional, 'target': target})

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

    # Verbo: "k.o." ou "trash" (sinonimos de remocao neste contexto).
    VERBO = r'(?:k\.o\.|trash)'

    # KO/trash stage (stage nao tem gatilho On K.O., entao mantem 'ko' para
    # ambos os verbos sem distincao -- a diferenca semantica so importa para
    # Character).
    m = re.search(VERBO + r" up to (\d+) of your opponent.{0,20} stages?", t)
    if m:
        cost_m = re.search(r'with a cost of (\d+)', t)
        steps.append({
            'action': 'ko',
            'count': int(m.group(1)),
            'target': 'opp_stage',
            'cost_lte': int(cost_m.group(1)) if cost_m else 99
        })
        return steps

    # KO/trash personagem do oponente. Verbo real do match decide a action:
    # 'k.o.' -> 'ko' (dispara [On K.O.] do alvo); 'trash' -> 'trash_character'
    # (remove do campo, mas NAO dispara [On K.O.] -- diferenca de regra
    # confirmada: trash de personagem != K.O., so K.O. ativa o gatilho).
    for m in re.finditer(
        VERBO + r" (up to (\d+)|all(?: of)?(?: the)?(?: rested)?) of your opponent.{0,20}"
        r'(?:"([a-z][a-z0-9 .\'-]+)"\s+type\s+)?'
        r"characters?(?: with a (?:base )?cost of (\d+)( or less)?)?"
        r"(?: with (?:a )?(\d+) (?:base )?power(?: or less)?)?",
        t
    ):
        verbo_usado = re.match(r'k\.o\.|trash', m.group(0)).group(0)
        action = 'ko' if verbo_usado == 'k.o.' else 'trash_character'
        is_all = m.group(1).startswith('all')
        count = 99 if is_all else int(m.group(2))
        step = {'action': action, 'count': count, 'target': 'opp_character'}
        if m.group(3):
            step['filter_type'] = m.group(3).strip()
        if m.group(4):
            if m.group(5):
                step['cost_lte'] = int(m.group(4))
            else:
                step['cost_eq'] = int(m.group(4))
        if m.group(6):
            step['power_lte'] = int(m.group(6))
        if 'rested' in m.group(0):
            step['rested_only'] = True
        steps.append(step)

    if steps:
        return steps

    # Variante SEM "of your opponent" -- alvo AMBOS os lados, ex: "K.O. all
    # rested Characters with a cost of 5 or less" (sem qualificador de
    # posse = afeta characters de qualquer jogador, confirmado pelo
    # contexto de regra simetrica em OP05-040: a condicao trava Refresh
    # Phase de "your and your opponent's", e o KO no End of Turn segue a
    # mesma simetria). Mesma logica de separacao K.O./trash por verbo real.
    m = re.search(
        VERBO + r" (up to (\d+)|all) (?:of the )?(?:rested )?characters?"
        r"(?: with a (?:base )?cost of (\d+)( or less)?)?",
        t
    )
    if m:
        verbo_usado = re.match(r'k\.o\.|trash', m.group(0)).group(0)
        action = 'ko' if verbo_usado == 'k.o.' else 'trash_character'
        is_all = m.group(1).startswith('all')
        count = 99 if is_all else int(m.group(2))
        step = {'action': action, 'count': count, 'target': 'all_character'}
        if m.group(3):
            if m.group(4):
                step['cost_lte'] = int(m.group(3))
            else:
                step['cost_eq'] = int(m.group(3))
        if 'rested' in m.group(0):
            step['rested_only'] = True
        steps.append(step)

    return steps


def parse_bounce(text):
    steps = []
    t = text.lower()

    # Forma explicita "of your opponent['s] Character(s)" -- mantida primeiro
    # pois e mais especifica.
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

    # Forma generica sem "of your opponent" -- "return up to N Character(s)
    # with a cost of X or less to the owner's hand". Target e implicitamente
    # o character do oponente (regra do jogo: sem qualificador de posse,
    # bounce mira o oponente). NAO casar quando o trecho diz "of your" logo
    # antes de "Character" (ai e auto-bounce de tribo, tratado em outro
    # parser por exigir contexto de tipo).
    for m in re.finditer(
        r"return up to (\d+) characters?(?: other than this character)?"
        r" with a cost of (\d+) or less",
        t
    ):
        # Garante que nao e "of your [Tipo] Characters" (auto-bounce de tribo)
        prefix = t[max(0, m.start() - 12):m.start()]
        if 'of your' in prefix or 'of you' in prefix:
            continue
        steps.append({
            'action': 'bounce',
            'count': int(m.group(1)),
            'target': 'opp_character',
            'cost_lte': int(m.group(2)),
        })

    if steps:
        return steps

    # Variante por power (em vez de custo): "return up to N Character(s)
    # with [base power] X to the owner's hand"
    m = re.search(
        r"return up to (\d+) characters? with (\d+) base power(?: or (more|less))? to the owner.?s hand",
        t
    )
    if m:
        step = {
            'action': 'bounce',
            'count': int(m.group(1)),
            'target': 'opp_character',
            'power_base_only': True,
        }
        comparator = m.group(3)
        if comparator == 'more':
            step['power_gte'] = int(m.group(2))
        elif comparator == 'less':
            step['power_lte'] = int(m.group(2))
        else:
            step['power_eq'] = int(m.group(2))
        steps.append(step)
        return steps

    # Variante sem qualquer filtro de custo/power: "return up to N
    # Character(s) to the owner's hand" (sem "of your opponent" e sem "of
    # your [Tipo]" antes).
    for m in re.finditer(r"return up to (\d+) characters? to the owner.?s hand", t):
        prefix = t[max(0, m.start() - 12):m.start()]
        if 'of your' in prefix or 'of you' in prefix:
            continue
        steps.append({'action': 'bounce', 'count': int(m.group(1)), 'target': 'opp_character'})

    if steps:
        return steps

    # Auto-bounce: "return this Character to the owner's hand" -- devolve a
    # SI MESMO pra mao, nao mira o oponente. Geralmente vem como efeito apos
    # um custo opcional (ex: "you may give your leader -5000 power: return
    # this Character to the owner's hand").
    if re.search(r"return this character to the owner.?s hand", t):
        steps.append({'action': 'bounce', 'count': 1, 'target': 'self'})

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


def parse_lock_attack(text):
    """
    Cobre 'Up to N of your opponent's Character(s) [with a cost of X or
    less] cannot attack [until DURATION]' e a variante indireta 'select up
    to N ... Characters. The selected Character(s) cannot attack ...'.
    Tambem cobre 'cannot be rested' -- mecanica DISTINTA de 'cannot attack'
    (trava o character de virar rested por qualquer meio, nao so de
    atacar). Nunca unificar as duas actions.
    """
    steps = []
    t = text.lower()

    # SEGURANCA: 'Choose one: • opcao A • opcao B' sao alternativas
    # MUTUAMENTE EXCLUSIVAS, nao efeitos sequenciais. Capturar o padrao de
    # lock_attack quando ele esta dentro de uma bullet de escolha faria o
    # parser tratar a opcao alternativa como se sempre acontecesse junto
    # com a outra -- pior do que nao capturar nada. Ate a estrutura
    # 'choice' ser implementada de verdade, deixa de fora aqui.
    if 'choose one' in t and ('•' in t or '\u2022' in t):
        return steps

    def parse_duration(clause):
        if 'end phase' in clause:
            return 'until_opp_end_phase'
        if 'the end of your opponent' in clause:
            return 'until_opp_turn_end'
        if 'the start of your next turn' in clause:
            return 'until_my_next_turn_start'
        return 'until_opp_turn_end'

    # Padrao direto: "up to N of your opponent's Character(s) [with a cost
    # of X or less] cannot (attack|be rested) until ..."
    m = re.search(
        r"up to (\d+) of your opponent.{0,15}characters?"
        r"(?: with a cost of (\d+) or less)?"
        r" cannot (attack|be rested) until ([^.]+)",
        t
    )
    if m:
        action = 'lock_opp_character_attack' if m.group(3) == 'attack' else 'lock_opp_cannot_be_rested'
        step = {'action': action, 'count': int(m.group(1)), 'duration': parse_duration(m.group(4))}
        if m.group(2):
            step['cost_lte'] = int(m.group(2))
        steps.append(step)
        return steps

    # Padrao indireto: "select up to N ... Characters [with a cost of X or
    # less]. The selected Character(s) cannot (attack|be rested) until ..."
    m_select = re.search(r"select up to (\d+) of your opponent.{0,15}characters?(?: with a cost of (\d+) or less)?", t)
    m_efeito = re.search(r"the selected character.{0,5} cannot (attack|be rested) until ([^.]+)", t)
    if m_select and m_efeito:
        action = 'lock_opp_character_attack' if m_efeito.group(1) == 'attack' else 'lock_opp_cannot_be_rested'
        step = {'action': action, 'count': int(m_select.group(1)), 'duration': parse_duration(m_efeito.group(2))}
        if m_select.group(2):
            step['cost_lte'] = int(m_select.group(2))
        steps.append(step)
        return steps

    # Variante "your opponent's rested Leader or up to N of your opponent's
    # Character(s) ... cannot attack until ..." -- alvo pode ser Leader OU
    # Character. Captura so a parte de Character por ora (travar ataque do
    # PROPRIO leader e mecanica rara e nao implementada no engine ainda).
    m_leader_or_char = re.search(
        r"opponent.{0,3}s rested leader or up to (\d+) of your opponent.{0,15}characters?"
        r"(?: other than \[([a-z][a-z0-9 .\'-]+)\])?"
        r" cannot attack until ([^.\[]+)",
        t
    )
    if m_leader_or_char:
        step = {
            'action': 'lock_opp_character_attack',
            'count': int(m_leader_or_char.group(1)),
            'duration': parse_duration(m_leader_or_char.group(3)),
        }
        if m_leader_or_char.group(2):
            step['exclude'] = m_leader_or_char.group(2).strip()
        steps.append(step)

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
    """
    Processa TODAS as ocorrencias de "<sinal?>N power" no bloco de texto,
    cada uma com sua propria janela de contexto local (nao o texto inteiro),
    pra suportar cartas com multiplos efeitos de power no mesmo bloco
    (ex: "Up to 3 of your Characters gain +1000 power. Then, give opponent's
    Characters 2000 power" -- dois efeitos, sinais e alvos diferentes).

    Regra de sinal quando ausente no texto (problema confirmado na fonte,
    ~81 cartas no banco), validada por imagens reais das cartas:
      alvo "opponent's [...]" => SEMPRE debuff
      alvo "your [...]" / nome proprio / "this character" => SEMPRE buff
    """
    steps = []
    t = text.lower()

    JANELA_ANTES = 90  # chars de contexto antes do match, suficiente p/ pegar "of your opponent's characters"
    JANELA_DEPOIS = 40  # chars de contexto depois, p/ pegar "during this turn/battle"

    for m in re.finditer(r'([+\-−]?)\s*(\d+)\s*power', t):
        sign = m.group(1)
        amount = int(m.group(2))

        contexto_antes = t[max(0, m.start() - JANELA_ANTES):m.start()]
        contexto_depois = t[m.end():m.end() + JANELA_DEPOIS]
        contexto = contexto_antes + ' <<N power>> ' + contexto_depois

        # ignora clausulas de FILTRO (ex: "with 3000 power or less", "characters
        # with 7000 power or more") -- isso e condicao de outro efeito (KO,
        # bounce, etc.), nao um buff/debuff de power em si
        if re.match(r'\s*(or less|or more)\b', contexto_depois):
            continue
        if re.search(r'\bwith\s*$', contexto_antes[-10:]):
            continue

        # ignora filtro de SELECAO DE CARTA (ex: "play up to N Character
        # cards with [type] and X power from your hand/trash/deck") -- aqui
        # o numero de power especifica qual carta jogar, nao e um buff/debuff
        if re.search(r'\bplay up to \d+[^.]*$', contexto_antes) and \
           re.match(r'\s*from your (hand|trash|deck)', contexto_depois):
            continue

        # ignora clausula de CUSTO proprio (ex: "give your leader -5000 power:
        # [efeito]") -- isso ja foi capturado por parse_costs como custo,
        # nao deve duplicar como step de debuff/buff solto
        if re.search(r'give your[^:]*$', contexto_antes) and re.match(r'\s*[^.]*:', contexto_depois):
            continue

        if sign in ('-', '−'):
            is_debuff = True
        elif sign == '+':
            is_debuff = False
        else:
            # sem sinal explicito -- infere pelo alvo na janela local (nao no texto inteiro)
            is_debuff = bool(re.search(r"opponent'?s?\s+(?:leader\s+or\s+)?(?:leader|character)", contexto_antes))

        target = 'self'
        if is_debuff:
            if "opponent's leader or character" in contexto_antes or "opponent's leader" in contexto_antes and "character" in contexto_antes:
                target = 'opp_leader_or_character'
            elif "opponent's leader" in contexto_antes:
                target = 'opp_leader'
            elif re.search(r"all of your opponent.?s? characters", contexto_antes):
                target = 'all_opp_characters'
            else:
                target = 'opp_character'
        else:
            if 'your leader or 1 of your characters' in contexto_antes or 'your leader or character' in contexto_antes:
                target = 'leader_or_character'
            elif 'all of your' in contexto_antes and "leader" in contexto_antes:
                target = 'all_allies_and_leader'
            elif 'all of your characters' in contexto_antes:
                target = 'all_allies'
            elif 'your leader' in contexto_antes:
                target = 'leader'
            elif ('this character' in contexto_antes or 'this card' in contexto_antes):
                target = 'self'
            elif 'of your characters' in contexto_antes or 'of your character cards' in contexto_antes:
                target = 'own_character'

        duration = 'this_turn'
        if 'until the start of your opponent' in contexto_depois:
            duration = 'until_opp_turn_start'
        elif 'until the end of your opponent' in contexto_depois:
            duration = 'until_opp_turn_end'
        elif 'until the start of your' in contexto_depois:
            duration = 'until_my_turn_start'
        elif 'during this battle' in contexto_depois:
            duration = 'battle_only'
        elif 'this turn' in contexto_depois:
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

    # Trava de "nao ficar ativo no Refresh" -- distinguir alvo: DON especifico,
    # Character/Leader especifico, ou generico ("cards", pode ser qualquer um).
    m = re.search(
        r"up to (?:a total of )?(\d+) of your opponent.?s rested "
        r"(don!! cards?|leader and character cards?|characters?|character cards?|leader cards?|cards?)"
        r" will not become active",
        t
    )
    if m:
        cnt = int(m.group(1))
        tipo = m.group(2)
        if tipo.startswith('don'):
            steps.append({'action': 'lock_opp_don_refresh', 'count': cnt})
        elif tipo == 'cards' or tipo == 'card':
            # generico ("cards" sem especificar) -- modelado como
            # character_refresh por ser o caso mais comum nesse fraseado
            steps.append({'action': 'lock_opp_character_refresh', 'count': cnt})
        else:
            steps.append({'action': 'lock_opp_character_refresh', 'count': cnt})
    elif re.search(r"opponent's .{0,30}will not become active|will not become active", t):
        # fallback antigo: padrao nao identificado claramente, mantem
        # comportamento anterior (assume DON) para nao regredir casos nao
        # cobertos pela regex especifica acima
        steps.append({'action': 'lock_opp_don'})

    return steps


def parse_play_from_trash(text):
    steps = []
    t = text.lower()

    # Padrao "choose up to N1 ... and up to N2 ... from your trash. Play 1
    # card and play the other card rested." -- duas escolhas com custos
    # distintos, uma delas entra rested e a outra ativa (regra fixa do
    # template: a explicitamente nomeada como "the other" entra rested).
    m_choose = re.search(
        r'choose up to (\d+) character card with a cost of (\d+) or less '
        r'and up to (\d+) character card with a cost of (\d+) or less from your trash',
        t
    )
    if m_choose and 'play 1 card and play the other card rested' in t:
        steps.append({'action': 'play_from_trash', 'count': int(m_choose.group(1)), 'cost_lte': int(m_choose.group(2))})
        steps.append({'action': 'play_from_trash', 'count': int(m_choose.group(3)), 'cost_lte': int(m_choose.group(4)), 'rested': True})
        return steps

    # Padrao "play up to N1 Character card with a type including 'X' and a
    # cost of C1 or less and up to N2 Character card with a type including
    # 'X' and a cost of C2 from your trash." -- dois targets compartilhando
    # um unico 'from your trash' no final da frase.
    m_double = re.search(
        r'play up to (\d+) character card with a type including "([a-z][a-z0-9 .\'-]+)" and a cost of (\d+) or less '
        r'and up to (\d+) character card with a type including "[a-z][a-z0-9 .\'-]+" and a cost of (\d+)\b'
        r'(?: or less)? from your trash',
        t
    )
    if m_double:
        steps.append({'action': 'play_from_trash', 'count': int(m_double.group(1)), 'filter_type': m_double.group(2).strip(), 'cost_lte': int(m_double.group(3))})
        # segundo cost sem "or less" no texto original = igualdade exata
        second_cost_eq = f'cost of {m_double.group(5)} from your trash' in t
        step2 = {'action': 'play_from_trash', 'count': int(m_double.group(4)), 'filter_type': m_double.group(2).strip()}
        if second_cost_eq:
            step2['cost_eq'] = int(m_double.group(5))
        else:
            step2['cost_lte'] = int(m_double.group(5))
        steps.append(step2)
        return steps

    # Padrao "play up to 1 [Nome1], up to 1 [Nome2], and up to 1 [Nome3],
    # with a cost of C or less from your trash" -- lista de nomes proprios
    # compartilhando um unico filtro de custo no final.
    m_names = re.search(
        r'play up to (\d+) \[([a-z][a-z0-9 .\'-]+)\], up to (\d+) \[([a-z][a-z0-9 .\'-]+)\], '
        r'and up to (\d+) \[([a-z][a-z0-9 .\'-]+)\], with a cost of (\d+) or less from your trash',
        t
    )
    if m_names:
        cost_lte = int(m_names.group(7))
        for i in (1, 2, 3):
            cnt = int(m_names.group(i * 2 - 1))
            name = m_names.group(i * 2).strip()
            steps.append({'action': 'play_from_trash', 'count': cnt, 'filter_name': name, 'cost_lte': cost_lte})
        return steps


    # Cada match abaixo cobre UM target "play up to N ... from your trash
    # [rested]?". Frases com dois targets (ex: "play up to 1 Character card
    # with a cost of 4 or less and up to 1 ... with a cost of 1 ... from
    # your trash") produzem dois steps, na ordem em que aparecem no texto.
    for m in re.finditer(r'play up to (\d+) .{0,140}?from your trash(\s+rested)?', t):
        clause = m.group(0)
        count = int(m.group(1))
        rested = bool(m.group(2))

        step = {'action': 'play_from_trash', 'count': count}

        cost_m = re.search(r'cost of (\d+) or less', clause)
        cost_eq_m = re.search(r'with a cost of (\d+)\b(?! or less)', clause)
        power_lte_m = re.search(r'(\d+) power or less', clause)
        power_eq_m = re.search(r'with (\d+) power\b(?! or less)', clause)
        if cost_m:
            step['cost_lte'] = int(cost_m.group(1))
        elif cost_eq_m:
            step['cost_eq'] = int(cost_eq_m.group(1))
        elif power_lte_m:
            step['power_lte'] = int(power_lte_m.group(1))
        elif power_eq_m:
            step['power_eq'] = int(power_eq_m.group(1))
        else:
            step['cost_lte'] = 99

        if 'different card names' in clause:
            step['distinct_names'] = True

        # Filtro de tipo: '"X" type' / '[X] type' / '{X} type' / 'type including "X"'
        type_m = (re.search(r'"([a-z][a-z0-9 .\'-]+)"\s+type', clause)
                  or re.search(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}]\s+type', clause)
                  or re.search(r'type including "([a-z][a-z0-9 .\'-]+)"', clause))
        if type_m:
            step['filter_type'] = type_m.group(1).strip()
        else:
            # Sem "type": colchetes contendo nome PROPRIO de carta, ex.
            # "play up to 1 [Ulti] with a cost of 4 or less from your trash"
            name_m = re.search(r'play up to \d+ \[([a-z][a-z0-9 .\'-]+)\]', clause)
            if name_m:
                step['filter_name'] = name_m.group(1).strip()

        if re.search(r'and a \[trigger\]', clause):
            step['has_trigger'] = True

        exclude_m = re.search(r'other than \[([a-z][a-z0-9 .\'-]+)\]', clause)
        if exclude_m:
            step['exclude'] = exclude_m.group(1).strip()

        if rested:
            step['rested'] = True

        steps.append(step)

    if steps:
        return steps

    # Variante sem "up to": "play this Character card from your trash"
    # (auto-recuperacao de si mesmo, geralmente apos um custo de trash de
    # outra carta). Count implicito = 1, target = self.
    if re.search(r'play this character card from your trash', t):
        steps.append({'action': 'play_from_trash', 'count': 1, 'filter_self': True})

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
    """Give -N cost / +N cost (manipulação de custo no oponente, geralmente)
    ou 'gains +N/-N cost' (auto-buff/debuff, sempre no próprio lado -- 'this
    Character'/'up to N of your... Characters'/'All of your Characters')."""
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

    # "gains +N cost" / "gain -N cost" -- sempre sobre o PROPRIO lado
    # (Character que carrega o efeito, ou outros Characters do mesmo
    # jogador). O alvo (self vs own_character generico) e determinado pelo
    # sujeito da frase, nao pela presenca de "opponent".
    m = re.search(r'gains? ([+\-−])(\d+) cost', t)
    if m:
        is_debuff = m.group(1) in ('-', '−')
        is_self = bool(re.search(r'this character gains? [+\-−]\d+ cost', t))
        step = {
            'action': 'debuff_cost' if is_debuff else 'buff_cost',
            'amount': int(m.group(2)),
            'target': 'self' if is_self else 'own_character',
        }
        count_m = re.search(r'up to (\d+) of your', t)
        if count_m:
            step['count'] = int(count_m.group(1))
        elif 'all of your' in t:
            step['count'] = 99
        type_m = (re.search(r'"([a-z][a-z0-9 .\'-]+)"\s+type', t)
                  or re.search(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}]\s+type', t))
        if type_m and not is_self:
            step['filter_type'] = type_m.group(1).strip()
        color_m = re.search(r'your (black|red|green|blue|yellow|purple) characters', t)
        if color_m and not is_self:
            step['color'] = color_m.group(1)
        duration_m = re.search(r'until the end of your opponent.?s next (?:end phase|turn)', t)
        step['duration'] = 'until_opp_turn_end' if duration_m else 'permanent'
        steps.append(step)

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


def parse_substitute_ko(text):
    """
    Cobre 'If [this Character/your X] would be K.O.'d [by an effect], you
    may [custo] instead [of being K.O.'d]'. Dois padroes de custo vistos:
      - trash 1 Event/Stage/card from your hand instead
      - give that Character -N power ... instead of being K.O.'d
    """
    steps = []
    t = text.lower()

    if not re.search(r"would be k\.o\.'?d", t):
        return steps

    cost = None

    m = re.search(r"you may trash this character instead", t)
    if m:
        cost = {'action': 'trash_self'}

    if not cost:
        m = re.search(r"you may rest (\d+) of your active don!! cards instead", t)
        if m:
            cost = {'action': 'rest_don', 'count': int(m.group(1))}

    if not cost:
        # "trash N card(s) from your hand instead" -- SEM filtro de tipo
        # (qualquer carta da mao). Testado ANTES da regex de tipo especifico
        # para nao deixar a palavra solta "card" ser capturada como se
        # fosse o nome de um tipo (ex: "Event"/"Stage").
        m = re.search(r"you may trash (\d+) cards? from your hand instead", t)
        if m:
            cost = {'action': 'trash_from_hand', 'count': int(m.group(1))}

    if not cost:
        # trash N [card(s)] from your hand instead -- com filtro de TIPO
        # ("Event"/"Stage") OU filtro de POWER ("Character card with N
        # power or more"). So um dos dois filtros se aplica por carta.
        m = re.search(r"you may trash (\d+) ([a-z][a-z0-9 /]*?)(?: cards?)? from your hand instead", t)
        if m and 'power' in m.group(2):
            m = None
        if m:
            tipos = re.split(r'\s*(?:/| or )\s*', m.group(2).strip())
            cost = {'action': 'trash_from_hand', 'count': int(m.group(1)), 'filter_type': [x.strip() for x in tipos if x.strip()]}

    if not cost:
        m = re.search(r"you may trash (\d+) character cards? with (\d+) power or more from your hand instead", t)
        if m:
            cost = {'action': 'trash_from_hand', 'count': int(m.group(1)), 'power_gte': int(m.group(2))}

    if not cost:
        # custo de power: SEMPRE debuff no alvo do custo (mesmo sendo proprio
        # Leader/Character), mesmo sem sinal explicito no texto -- e
        # sacrificio/substituicao, nao bonus. Confirmado por imagem real
        # (X.Drake OP14-016: "give your Leader 2000 power instead" = -2000).
        m = re.search(r"you may give (?:that character|this character) [−\-]?(\d+) power[^.]*instead", t)
        if m:
            cost = {'action': 'debuff_power_self', 'amount': int(m.group(1))}
        else:
            m = re.search(r"you may give your leader [−\-]?(\d+) power[^.]*instead", t)
            if m:
                cost = {'action': 'debuff_power_self_leader', 'amount': int(m.group(1))}

    if cost:
        steps.append({'action': 'substitute_ko', 'cost': cost})

    return steps


def parse_substitute_removal(text):
    """
    Cobre 'If [this/your X Character] would be removed from the field [by
    your opponent's effect][or K.O.'d], you may [custo] instead'. Mais
    generico que substitute_ko (remocao cobre K.O., bounce, deck-bottom
    causados por efeito -- nao so K.O.). Variacoes de custo vistas:
      - discard/trash 1 card from your hand instead
      - rest this Character instead
      - return this Character to the owner's hand instead (bounce_self)
      - give that Character/your Leader -N power instead (debuff_power_self
        ou debuff_power_self_leader -- SEMPRE debuff, mesmo alvo proprio,
        pois e sacrificio de substituicao)
      - trash this Character and draw 1 card instead
      - place 1 of your Characters [other than X] at the bottom of the
        owner's deck instead
    """
    steps = []
    t = text.lower()

    if not re.search(r"would be removed from the field", t):
        return steps

    cost = None
    extra_steps = []

    # tentativas em ordem -- a primeira que casar define o custo
    tentativas = [
        (r"you may (?:discard|trash) (\d+) cards? from your hand instead",
         lambda m: {'action': 'trash_from_hand', 'count': int(m.group(1))}),
        (r"trash this character and draw (\d+) cards? instead",
         lambda m: {'action': 'trash_self'}),
        (r"you may rest this character and trash (\d+) cards? from your hand instead",
         lambda m: {'action': 'rest_self_and_trash_hand', 'trash_count': int(m.group(1))}),
        (r"you may rest this character instead",
         lambda m: {'action': 'rest_self'}),
        (r"return this character to the owner.?s hand instead",
         lambda m: {'action': 'bounce_self'}),
        (r"you may give (?:that character|this character) [−\-]?(\d+) power[^.]*instead",
         lambda m: {'action': 'debuff_power_self', 'amount': int(m.group(1))}),
        (r"you may give your leader [−\-]?(\d+) power[^.]*instead",
         lambda m: {'action': 'debuff_power_self_leader', 'amount': int(m.group(1))}),
        (r"you may (?:return|place) (\d+) of your characters?[^.]*instead",
         lambda m: {'action': 'place_own_character_bottom_deck', 'count': int(m.group(1))}),
        (r"you may return (\d+) don!! cards? from your field to your don!! deck instead",
         lambda m: {'action': 'return_own_don', 'count': int(m.group(1))}),
    ]

    for pattern, builder in tentativas:
        m = re.search(pattern, t)
        if m:
            cost = builder(m)
            if pattern == r"trash this character and draw (\d+) cards? instead":
                extra_steps.append({'action': 'draw', 'count': int(m.group(1))})
            break

    if cost:
        step = {'action': 'substitute_removal', 'cost': cost}
        if extra_steps:
            step['extra_steps'] = extra_steps
        steps.append(step)

    return steps


def parse_negate_effect(text):
    """
    Cobre dois padroes distintos:
      - 'Your [On Play] effects are negated' / "your opponent's [On Play]
        effects are negated" -> negate_on_play_effects (alvo: self/opponent)
      - 'Negate the effects of up to N of your opponent's Characters with a
        cost of X or less' -> negate_effect (generico, com filtro de custo)
    """
    steps = []
    t = text.lower()

    # padrao especifico [on play] -- apenas o caso "opponent's effects negados"
    # com trigger explicito (ex: dentro de [Activate: Main]). O caso "your
    # [On Play] effects are negated" passivo e tratado em parse_card_effect.
    if 'on play' in t and 'negat' in t:
        if "your opponent's [on play] effects are negated" in t or "opponent's [on play] effects are negated" in t:
            duration = 'until_opp_turn_end' if 'until the end' in t else 'this_turn'
            steps.append({'action': 'negate_on_play_effects', 'target': 'opponent', 'duration': duration})
            return steps

    # padrao generico: 'negate the effects of up to N of your opponent's
    # leader or character cards/characters [with a cost of X or less]'
    m = re.search(r"negate the effects? of up to (\d+) of your opponent.{0,30}?(?:leader or character cards?|characters?)", t)
    if m:
        step = {'action': 'negate_effect', 'count': int(m.group(1)), 'target': 'opp_leader_or_character' if 'leader' in m.group(0) else 'opp_character'}
        cost_m = re.search(r'with a cost of (\d+) or less', t)
        if cost_m:
            step['cost_lte'] = int(cost_m.group(1))
        if 'during this turn' in t:
            step['duration'] = 'this_turn'
        steps.append(step)

    return steps



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

    # Aceita: "add up to N <descrição> from your trash to your hand"
    # A <descrição> pode ser [tipo], "tipo" type, "Character cards with cost...", etc.
    m = re.search(r'add up to (\d+) (.+?) from your trash to your hand', t)
    if not m:
        return steps

    count = int(m.group(1))
    desc = m.group(2)

    step = {'action': 'add_from_trash', 'count': count}

    # filtro de nome/tipo entre colchetes (ex: [Nico Robin])
    name_m = re.search(r'\[([^\]]+)\]', desc)
    if name_m:
        step['filter_name'] = name_m.group(1)
    # filtro de tipo entre aspas (ex: "CP" type)
    else:
        type_m = re.search(r'"([^"]+)" type', desc)
        if type_m:
            step['filter_type'] = type_m.group(1)

    # filtro de custo (ex: with a cost of 4 or less)
    cost_m = re.search(r'cost of (\d+) or less', desc)
    if cost_m:
        step['cost_lte'] = int(cost_m.group(1))

    steps.append(step)
    return steps


# ===========================================================================
# Parser principal de um bloco de texto
# ===========================================================================

def parse_block(block_text, trigger_name):
    """Parseia um bloco de efeito e retorna lista de steps."""
    steps = []
    t = block_text.lower()

    # Substitute KO: "would be K.O.'d... you may [custo] instead" -- precisa
    # rodar ANTES de parse_ko e parse_power_buff, pois o texto menciona K.O.
    # e/ou power mas NAO e um KO real nem um buff/debuff solto, e sim uma
    # substituicao condicional. Reivindica o bloco inteiro (return antecipado)
    # pra evitar que parse_ko/parse_power_buff capturem o mesmo trecho.
    if re.search(r"would be k\.o\.'?d", t):
        sub_steps = parse_substitute_ko(t)
        if sub_steps:
            return sub_steps

    # Substitute removal (generico, distinto de K.O.): "would be removed
    # from the field... you may [custo] instead" -- mesma logica de
    # reivindicar o bloco e retornar antecipado.
    if re.search(r"would be removed from the field", t):
        sub_steps = parse_substitute_removal(t)
        if sub_steps:
            return sub_steps

    # Busca
    if 'look at' in t:
        steps.extend(parse_look_at(t))

    # KO (e seu sinonimo "trash" quando remove Character do OPONENTE -- ex:
    # "Trash up to 1 of your opponent's Characters with a cost of 4 or
    # less". Gatilho 'trash up to' (nao 'trash' generico) para nao disparar
    # em trash_from_hand/trash_self, que sao muito mais comuns no texto.)
    if 'k.o.' in t or ('trash up to' in t and 'opponent' in t):
        steps.extend(parse_ko(t))

    # Bounce (oponente OU auto-bounce do proprio character)
    if 'return' in t and 'hand' in t:
        steps.extend(parse_bounce(t))

    # Restar oponente
    if 'rest up to' in t and 'opponent' in t:
        steps.extend(parse_rest_opp(t))

    # Trava de ataque / trava de ser restado (mecanicas distintas, ambas
    # cobertas pela mesma funcao por compartilharem estrutura textual)
    if ('cannot attack' in t or 'cannot be rested' in t) and 'opponent' in t:
        steps.extend(parse_lock_attack(t))

    # Draw (sem look at)
    if 'draw' in t and 'look at' not in t:
        steps.extend(parse_draw(t))

    # Power buff/debuff (com ou sem sinal explicito -- parse_power_buff agora
    # infere o sinal pelo alvo quando o texto nao traz +/- explicito)
    if 'power' in t:
        steps.extend(parse_power_buff(t))

    # Custo: give -N/+N cost (oponente, geralmente) / gains +N cost (proprio)
    if 'cost' in t and ('give' in t or 'gain' in t) and ('-' in t or '−' in t or '+' in t):
        steps.extend(parse_cost_debuff(t))

    # Play genérico (sem origem explícita)
    if 'play ' in t:
        steps.extend(parse_play_generic(t))

    # DON: give, add (ramp), set active -- ou trava de "will not become
    # active" (que pode mirar Character/Leader sem mencionar a palavra "don")
    if ('don' in t and ('give' in t or 'add' in t or 'set' in t)) or 'will not become active' in t:
        steps.extend(parse_give_don(t))

    # Negar efeito (On Play especifico, ou generico com filtro de custo)
    if 'negat' in t:
        steps.extend(parse_negate_effect(t))

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

    # Keywords concedidas. IMPORTANTE: '[Rush: Character]' e MECANICA
    # DIFERENTE de '[Rush]' -- Rush comum permite atacar Leader OU
    # Character; Rush: Character so permite atacar Character. Por isso a
    # action e distinta (gain_rush_character), nunca reaproveitar gain_rush.
    # Janela de lista compartilhada: "gains [A], [B] or [C]" -- [B] e [C] nao
    # estao colados a 'gain(s)', mas pertencem a mesma concessao condicional.
    _gains_lista_m = re.search(r'gains?\s+(\[[a-z: ]+\]\s*,?\s*)+(or\s*\[[a-z: ]+\]\s*)?', t)
    _lista_txt = _gains_lista_m.group(0) if _gains_lista_m else ''

    if 'gain [rush: character]' in t or 'gains [rush: character]' in t or '[rush: character]' in _lista_txt:
        steps.append({'action': 'gain_rush_character'})
    elif 'gain [rush]' in t or 'gains [rush]' in t or '[rush]' in _lista_txt:
        steps.append({'action': 'gain_rush'})
    if 'gain [blocker]' in t or 'gains [blocker]' in t or '[blocker]' in _lista_txt:
        steps.append({'action': 'gain_blocker'})
    if 'gain [double attack]' in t or 'gains [double attack]' in t or '[double attack]' in _lista_txt:
        steps.append({'action': 'gain_double_attack'})
    if 'gain [banish]' in t or 'gains [banish]' in t or '[banish]' in _lista_txt:
        steps.append({'action': 'gain_banish'})
    if 'gain [unblockable]' in t or 'gains [unblockable]' in t or '[unblockable]' in _lista_txt:
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
    # normaliza tags HTML de quebra de linha (<br>, <br/>, <br />) para \n
    # real -- a fonte de dados usa isso como separador equivalente a quebra
    # de linha entre blocos de efeito.
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.IGNORECASE)
    # normaliza espacos multiplos (a fonte por vezes usa 2+ espacos entre
    # frases/blocos) para um unico espaco, simplificando os lookbehind de
    # abertura/parada de bloco que assumem exatamente 0 ou 1 espaco.
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t_low = t.lower()
    result = {}

    # Mapa de triggers → regex para extrair o bloco de texto
    # Lista de TODAS as tags de trigger possiveis no texto cru (case-insensitive),
    # usada simetricamente em todo lookahead de parada -- antes cada padrao so
    # parava em um subconjunto proprio, causando vazamento entre blocos (ex:
    # [Your Turn] vazava pra dentro de [Opponent's Turn] porque a lista de
    # parada do your_turn nao incluia opponent's turn).
    TODAS_TAGS = r"on play|activate:?\s*main|when attacking|on k\.o\.|your turn|opponent.{0,3}s? turn|trigger|counter|end of your turn|on block|main|blocker|rush|double attack|banish|unblockable"

    # Delimitador de bloco só conta quando a tag aparece no INICIO de uma frase
    # (inicio do texto, ou logo apos um '.' ou quebra de linha, com espaco
    # opcional). Isso evita confundir "[Trigger]" como delimitador de novo
    # bloco com "[Trigger]" usado como referencia a keyword no meio de uma
    # frase, ex: "trash 1 card with a [Trigger] from your hand".
    LOOKAHEAD_DELIM = r'(?=(?:^|(?<=[.\n])|(?<=\])|(?<=\)))\s*\[(?:' + TODAS_TAGS + r')\]|$)'

    # Lookbehind de abertura: a tag so conta como INICIO de bloco se vier no
    # comeco do texto, logo apos um '.'/quebra de linha, OU logo apos OUTRA
    # tag '[...]' (tags costumam vir coladas, ex: "[DON!! x1] [When
    # Attacking]"). Sem isso, re.search() acha a primeira ocorrencia da tag
    # em QUALQUER lugar do texto -- incluindo uso da tag como referencia de
    # keyword no meio de uma frase (ex: "a card with a [Trigger] from your
    # hand").
    ABERTURA = r'(?:(?<=^)|(?<=[.\n] )|(?<=[.\n])|(?<=\] )|(?<=\])|(?<=\) )|(?<=\)))'

    trigger_patterns = [
        ('on_play',       ABERTURA + r'\[on play\](.+?)' + LOOKAHEAD_DELIM),
        ('activate_main', ABERTURA + r'\[activate:?\s*main\](.+?)' + LOOKAHEAD_DELIM),
        ('when_attacking',ABERTURA + r'\[when attacking\](.+?)' + LOOKAHEAD_DELIM),
        ('on_ko',         ABERTURA + r'\[on k\.o\.\](.+?)' + LOOKAHEAD_DELIM),
        ('your_turn',     ABERTURA + r'\[your turn\](.+?)' + LOOKAHEAD_DELIM),
        ('opp_turn',      ABERTURA + r"\[opponent.{0,3}s? turn\](.+?)" + LOOKAHEAD_DELIM),
        ('trigger',       ABERTURA + r'\[trigger\](.+?)' + LOOKAHEAD_DELIM),
        ('counter',       ABERTURA + r'\[counter\](.+?)' + LOOKAHEAD_DELIM),
        ('end_of_turn',   ABERTURA + r'\[end of your turn\](.+?)' + LOOKAHEAD_DELIM),
        ('on_block',      ABERTURA + r'\[on block\](.+?)' + LOOKAHEAD_DELIM),
        ('main',          ABERTURA + r'\[main\](.+?)' + LOOKAHEAD_DELIM),
    ]

    # Mapa tag-formal -> trigger_name, usado para resolver pares "[TAG1]/[TAG2]"
    NOME_PARA_TRIGGER = {
        'on play': 'on_play', 'activate main': 'activate_main', 'activate: main': 'activate_main',
        'activate:main': 'activate_main', 'when attacking': 'when_attacking', 'on k.o.': 'on_ko',
        'your turn': 'your_turn', "opponent's turn": 'opp_turn', 'trigger': 'trigger',
        'counter': 'counter', 'end of your turn': 'end_of_turn', 'on block': 'on_block', 'main': 'main',
    }

    def par_de_barra(pos_inicio_tag1):
        """
        Se a tag que comeca em pos_inicio_tag1 (ex: '[on play]') e seguida,
        logo apos o ']', por um '/' e outra tag '[...]' (ex: '[on play]/[when
        attacking]' ou '[on play] / [when attacking]'), retorna o
        trigger_name da segunda tag. Senao retorna None.
        """
        m = re.match(r'\[([a-z0-9 .:\'!]+?)\]\s*/\s*\[([a-z0-9 .:\'!]+?)\]', t_low[pos_inicio_tag1:pos_inicio_tag1+80])
        if not m:
            return None
        nome2 = m.group(2).strip()
        return NOME_PARA_TRIGGER.get(nome2)

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

        is_substitute = len(steps) == 1 and steps[0].get('action') in ('substitute_ko', 'substitute_removal')

        conds = parse_conditions(block)
        costs = [] if is_substitute else parse_costs(block)
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

        # "[TAG1]/[TAG2] efeito" -- mesmo efeito jogavel em dois triggers
        # diferentes (ex: On Play/When Attacking, Main/Counter). Duplica o
        # MESMO entry (copia, nao referencia) pro segundo trigger.
        par = par_de_barra(trigger_pos)
        if par and par != trigger_name and par not in result:
            result[par] = json.loads(json.dumps(entry))

    # Segmento solto ANTES da primeira tag formal (independente de result já
    # ter sido preenchido por outros blocos). Ex: "If your Leader has the
    # [X] type, this Character gains +3 cost. [When Attacking] ...efeito
    # do when_attacking..." -- o trecho antes de "[When Attacking]" e um
    # efeito passivo proprio, nao parte do when_attacking. Sem isto, texto
    # solto antes de QUALQUER tag formal era sempre descartado.
    primeira_tag_m = re.search(ABERTURA + r'\[(?:' + TODAS_TAGS + r')\]', t_low)
    if primeira_tag_m:
        segmento_solto = t_low[:primeira_tag_m.start()].strip()
        # ignora ruido administrativo que nao e efeito de jogo (nomenclatura
        # de arquetipo, regra de deckbuilding) e [DON!! xN] isolado (j[a
        # tratado como prefixo de don_requirement em outro lugar).
        eh_ruido = (
            'also treat this card' in segmento_solto
            or 'you may have any number of this card' in segmento_solto
            or re.fullmatch(r'(\[don!! x\d+\]\s*)+', segmento_solto or '')
        )
        if segmento_solto and len(segmento_solto) > 10 and not eh_ruido:
            solto_steps = parse_block(segmento_solto, 'passive')
            if solto_steps:
                is_sub_solto = len(solto_steps) == 1 and solto_steps[0].get('action') in ('substitute_ko', 'substitute_removal')
                solto_entry = {'steps': solto_steps}
                solto_conds = parse_conditions(segmento_solto)
                solto_costs = [] if is_sub_solto else parse_costs(segmento_solto)
                if solto_conds:
                    solto_entry['conditions'] = solto_conds
                if solto_costs:
                    solto_entry['costs'] = solto_costs
                if '[once per turn]' in segmento_solto:
                    solto_entry['once_per_turn'] = True
                if 'passive' in result:
                    # ja existe passive (ex: vindo de don_conditional_keywords
                    # processado em outro momento) -- mescla os steps em vez
                    # de sobrescrever.
                    result['passive']['steps'].extend(solto_entry['steps'])
                    for k, v in solto_entry.items():
                        if k != 'steps' and k not in result['passive']:
                            result['passive'][k] = v
                else:
                    result['passive'] = solto_entry

    # Fallback: texto sem NENHUM trigger formal da lista (ex: apenas
    # "[Once Per Turn] If this Character would be K.O.'d... instead." ou
    # "[Once Per Turn] When a [Trigger] activates, draw..."). O "quando" do
    # efeito esta escrito em prosa (if/when), nao numa tag formal -- trata-se
    # como passive (efeito sempre vigiando), preservando once_per_turn.
    if not result:
        sem_tags_de_trigger = not re.search(ABERTURA + r'\[(?:' + TODAS_TAGS + r')\]', t_low)
        if sem_tags_de_trigger:
            fallback_steps = parse_block(t_low, 'passive')
            if fallback_steps:
                is_substitute_fb = len(fallback_steps) == 1 and fallback_steps[0].get('action') in ('substitute_ko', 'substitute_removal')
                entry = {'steps': fallback_steps}
                conds = parse_conditions(t_low)
                costs = [] if is_substitute_fb else parse_costs(t_low)
                if conds:
                    entry['conditions'] = conds
                if costs:
                    entry['costs'] = costs
                if '[once per turn]' in t_low:
                    entry['once_per_turn'] = True
                result['passive'] = entry

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
                        ('[rush: character]', 'keyword_rush_character'),
                        ('[double attack]', 'keyword_double_attack'),
                        ('[banish]', 'keyword_banish'),
                        ('[unblockable]', 'keyword_unblockable')]:
        if tag not in t_low:
            continue
        # evita capturar "gains [X]" como keyword nativa passiva quando na
        # verdade e concedida CONDICIONALMENTE (tratada pelo fallback/segmento
        # solto como gain_X, ou condicionada a DON como cond_keywords).
        # evita capturar "gains [X]" como keyword nativa passiva quando na
        # verdade e concedida CONDICIONALMENTE (tratada pelo fallback/segmento
        # solto como gain_X, ou condicionada a DON como cond_keywords).
        # Cobre tambem lista compartilhando um unico verbo, ex: "gains
        # [Double Attack], [Banish] or [Blocker]" -- aqui [Banish] e
        # [Blocker] nao estao colados a 'gains', mas fazem parte da MESMA
        # concessao condicional.
        gain_idx = t_low.find('gain ' + tag) if f'gain {tag}' in t_low else (t_low.find('gains ' + tag) if f'gains {tag}' in t_low else -1)
        if gain_idx == -1:
            # tag pode estar mais adiante numa lista "gains [A], [B] or [C]"
            for verbo_m in re.finditer(r'gains?\s+\[', t_low):
                # janela curta apos o verbo ate o fim da lista (heuristica:
                # ate 60 chars, suficiente para 2-3 keywords curtas)
                janela = t_low[verbo_m.start():verbo_m.start() + 60]
                if tag in janela and re.search(r'^\s*gains?\s+(\[[a-z ]+\]\s*,?\s*)*(or\s*)?$', janela[:janela.find(tag)] + ' '):
                    gain_idx = verbo_m.start()
                    break
        if gain_idx != -1 and keyword_don_req(tag) == 0:
            continue
        req = keyword_don_req(tag)
        if req > 0:
            cond_keywords.append({'action': action, 'don_requirement': req})
        else:
            passive_steps.append({'action': action})

    if passive_steps:
        if 'passive' in result:
            result['passive']['steps'].extend(passive_steps)
        else:
            result['passive'] = {'steps': passive_steps}
    if cond_keywords:
        # keywords condicionais a DON ficam separadas, com seu requisito.
        # Remove do passive (gerado pelo fallback de 'gains [X]') qualquer
        # gain_X cuja MESMA keyword ja esta condicionada a DON aqui --
        # evita duplicacao contraditoria (ex: "gains [Rush] sempre" E
        # "ganha Rush so com 1 DON" ao mesmo tempo).
        ACTION_PARA_GAIN = {
            'keyword_blocker': 'gain_blocker', 'keyword_rush': 'gain_rush',
            'keyword_double_attack': 'gain_double_attack', 'keyword_banish': 'gain_banish',
            'keyword_unblockable': 'gain_unblockable',
        }
        gains_condicionais = {ACTION_PARA_GAIN[c['action']] for c in cond_keywords if c['action'] in ACTION_PARA_GAIN}
        if 'passive' in result and gains_condicionais:
            result['passive']['steps'] = [
                s for s in result['passive']['steps'] if s.get('action') not in gains_condicionais
            ]
            if not result['passive']['steps']:
                del result['passive']
        result['don_conditional_keywords'] = {'steps': cond_keywords}

    # "Your [On Play] effects are negated" passivo (sem trigger explicito,
    # texto solto fora de qualquer bloco [X]). Distinto do caso "your
    # opponent's [On Play] effects are negated" (que vem dentro de um
    # trigger como [Activate: Main] e ja e capturado no loop principal).
    if re.search(r"^your \[on play\] effects are negated", t_low.strip()) or \
       re.search(r"[.\n]\s*your \[on play\] effects are negated", t_low):
        if 'passive' not in result:
            result['passive'] = {'steps': []}
        result['passive']['steps'].append({'action': 'negate_on_play_effects', 'target': 'self', 'duration': 'permanent'})

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

        attribute_raw = str(row.get('attribute') or '').strip()
        attribute = '' if attribute_raw.upper() in ('NULL', 'N/A', '?', 'NAN') else attribute_raw

        db[code] = {
            'name':      str(row.get('card_name') or ''),
            'type':      card_type,
            'cost':      cost,
            'power':     power,
            'counter':   counter,
            'life':      life,
            'color':     str(row.get('card_color') or ''),
            'sub_types': str(row.get('sub_types') or ''),
            'attribute': attribute,
            'effects':   parse_card_effect(card_text, card_type),
        }

    return db


if __name__ == '__main__':
    print('Este gerador não deve ser rodado sozinho — geraria um JSON')
    print('dessincronizado do outro banco.')
    print('Use:  python gerar_dbs.py   (gera os dois juntos)')
    import sys
    sys.exit(1)
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