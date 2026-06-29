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

# "[efeito A incondicional]. Then, if [condicao], [efeito B]" ou
# "[efeito A incondicional]. If [condicao], [efeito B]" -- divide um bloco em
# duas partes (a parte ANTES do split, sem condicao; a parte DEPOIS, com sua
# propria condicao) em vez de aplicar parse_conditions() no bloco inteiro.
# Sem isto, _check_conditions() no engine bloqueava TAMBEM o efeito A (sempre
# incondicional no jogo real) sempre que a condicao do "Then, if" falhasse --
# bug confirmado visualmente em ST14-001/ST14-008 e replicado estruturalmente
# em ~44 outras cartas (auditoria de 23/06). Exclui deliberadamente "if you
# do" / "if that card is" -- la a condicao e sobre o RESULTADO da acao
# anterior (custo opcional), nao sobre estado de jogo, e ja tem tratamento
# proprio via parse_costs(optional=True); aplicar o split ali separaria
# custo e efeito incorretamente (25 cards identificadas e excluidas).
SPLIT_THEN_IF_RE = re.compile(
    r'\.\s*(?:then,?\s+)?if\s+(?:you|your|there|opponent)(?!\s+do\b)',
    re.IGNORECASE
)


def split_then_if(block_text):
    """
    Se block_text tem o padrao '[A]. Then, if [cond], [B]' ou '[A]. If
    [cond], [B]', retorna (parte_a, parte_b) onde parte_a e o texto ANTES do
    ponto (sem a condicao) e parte_b e o texto DEPOIS (com 'Then,'/'.'
    removido do inicio, condicao incluida). Se nao houver o padrao, retorna
    (block_text, None) -- parte_b None sinaliza "sem split, comportamento
    antigo preservado".
    """
    m = SPLIT_THEN_IF_RE.search(block_text)
    if not m:
        return block_text, None
    parte_a = block_text[:m.start() + 1].strip()  # inclui o '.'
    parte_b = block_text[m.start() + 1:].strip()
    # remove 'Then,' isolado do inicio de parte_b -- parse_conditions/
    # parse_block nao precisam dele, e ele nao carrega nenhuma informacao
    # de condicao por si so.
    parte_b = re.sub(r'^then,?\s+', '', parte_b, flags=re.IGNORECASE).strip()
    if not parte_a or not parte_b:
        return block_text, None
    return parte_a, parte_b


def parse_conditions(text):
    conds = {}
    t = text.lower()

    m = re.search(r'(?:if|and) you have (\d+) or less life', t)
    if m: conds['life_lte'] = int(m.group(1))

    m = re.search(r'(?:if|and) you have (\d+) or more life', t)
    if m: conds['life_gte'] = int(m.group(1))

    m = re.search(r'(?:if (?:you have|there are)|and you have) (\d+) or more cards? in your trash', t)
    if m: conds['trash_gte'] = int(m.group(1))

    # "if you have N or more Events in your trash" -- conta SO os Event
    # cards no trash, distinto de trash_gte (que conta qualquer card).
    # 7 cards no banco (ex: OP15-021 Just Watch Me, Ace!!!).
    m = re.search(r'if you have (\d+) or more events? in your trash', t)
    if m: conds['events_in_trash_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more don!!', t)
    if m: conds['don_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more don!! cards? on your field', t)
    if m: conds['don_on_field_gte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more characters?(?: with an? (?:base|original) cost of (\d+) or more)?', t)
    if m:
        conds['chars_gte'] = int(m.group(1))
        if m.group(2):
            conds['chars_gte_cost_filter'] = int(m.group(2))

    m = re.search(r'if you have (\d+) or less cards? in your hand', t)
    if m: conds['hand_lte'] = int(m.group(1))

    m = re.search(r'if you have (\d+) or more cards? in your hand', t)
    if m: conds['hand_gte'] = int(m.group(1))

    m = re.search(r'if your leader is \[([^\]]+)\]', t)
    if m: conds['leader_is'] = m.group(1)

    m = re.search(r"if your leader(?:'s|\u2019s)? type includes? [\"'\u2019]?([^\"'\u2019\n,]+)[\"'\u2019]?", t)
    if m: conds['leader_type_includes'] = m.group(1).strip()

    # "if your leader has the X type" — X entre aspas, colchetes ou chaves
    m = re.search(r'if your leader has (?:the )?["\[{]([^"\]}]+)["\]}] type', t)
    if m: conds['leader_type'] = m.group(1).strip()

    if 'if your leader is multicolored' in t:
        conds['leader_multicolor'] = True

    if 'if you have a face-up life card' in t:
        conds['has_face_up_life'] = True

    # "If the only Characters on your field are [X]/{X}/"X" type Characters"
    # -- condicao sobre a COMPOSICAO do proprio campo (todos os Characters
    # do jogador sao do mesmo tipo X), distinta de leader_type/self_type
    # (que olham o Leader ou o proprio Character com o efeito). Escopo
    # pequeno (6 cards no banco), mas padrao textual estavel e unico.
    m = re.search(r'if the only character.{0,5} on your field (?:are|is) ["\[{]([^"\]}]+)["\]}] type', t)
    if m: conds['only_field_type'] = m.group(1).strip()

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

    # "if your Leader has N power or less" -- simetrico ao gte. Usado para
    # detectar Leader debuffado a 0 (ex: OP15-013 Pincers, "0 power or less").
    m = re.search(r'if your leader has (\d+) power or less', t)
    if m: conds['leader_power_lte'] = int(m.group(1))

    # "if your opponent has a Character with N power or more" -- existe
    # Character no campo do OPONENTE com power >= N (distinto de
    # other_char_power_gte, que e sobre o PROPRIO campo). Aceita as 2 ordens
    # de palavras encontradas no texto oficial -- "N power or more" e "N or
    # more power" (ex: OP09-019) -- sem isto a segunda ordem nunca era
    # reconhecida e a condicao ficava vazia.
    m = re.search(r'if your opponent has a character with (\d+)(?: power or more| or more power)', t)
    if m: conds['opp_char_power_gte'] = int(m.group(1))

    # Variante combinada: "...power or more and the "X"/[X]/{X} type" --
    # captura o type quando vem encadeado depois da clausula de power (a
    # regex leader_type/leader_type_includes acima nao cobre esse encadeamento).
    if 'leader_power_gte' in conds and 'leader_type' not in conds and 'leader_type_includes' not in conds:
        m = re.search(r'power or more and (?:the )?["\[{]([^"\]}]+)["\]}] type', t)
        if m: conds['leader_type'] = m.group(1).strip()

    # "if there is a Character with a cost of N [or with a cost of M or
    # more]" -- condicao de EXISTENCIA sobre QUALQUER Character no jogo
    # (qualquer lado do campo), distinta de chars_gte (que conta o proprio
    # campo do jogador). Dois padroes: simples "cost of N" e composto
    # "cost of N or with a cost of M or more". 14 cards no banco
    # (ex: OP14-098 Crescent Cutlass).
    m = re.search(
        r'if there is a character with a cost of (\d+)'
        r'(?: or with a cost of (\d+) or more)?', t)
    if m:
        conds['board_has_cost'] = [int(m.group(1))]
        if m.group(2):
            conds['board_has_cost_gte'] = int(m.group(2))

    # "there is a Character with N base power or more" -- existencia
    # generica de POWER no jogo (qualquer lado do campo), mesma semantica
    # de board_has_cost mas para power em vez de cost. Distinta de
    # other_char_power_gte (proprio campo) e opp_char_power_gte (campo do
    # oponente, existencia de 1). Usada por cannot_attack_self_unless (ex:
    # EB04-051 'cannot attack unless there is a Character with 12000 base
    # power or more').
    m = re.search(r'there is a character with (\d+) base power or more', t)
    if m: conds['board_has_power_gte'] = int(m.group(1))

    # "your opponent has N or more Characters with a base power of M or
    # more" -- CONTAGEM (nao existencia) no campo do oponente: precisa de N
    # Characters distintos, cada um com power >= M. Distinta de
    # opp_char_power_gte (so checa se EXISTE 1 Character com power >= M,
    # sem exigir contagem minima). Usada por cannot_attack_self_unless (ex:
    # EB04-005).
    m = re.search(
        r'your opponent has (\d+) or more characters with a base power of (\d+) or more', t)
    if m:
        conds['opp_chars_power_gte_count'] = {'count': int(m.group(1)), 'power_gte': int(m.group(2))}

    return conds


def parse_costs(text):
    costs = []
    t = text.lower()

    # Custo composto: "rest this Character and 1 of your [TIPO] type Leader
    # or Stage cards" -- DOIS recursos pagos juntos (a propria carta + um
    # Leader/Stage com filtro de tipo). Distinto de rest_self puro: aqui o
    # efeito so pode ser pago se AMBOS os recursos estiverem disponiveis.
    # Verificado ANTES do rest_self generico para nao perder o segundo
    # componente do custo (a regex de rest_self abaixo tambem casaria com o
    # inicio desta frase, mas devolveria so 1 dos 2 recursos reais).
    m_composto = re.search(
        r'rest this character and \d+ of your ["\[{]([a-z][a-z0-9 .\'-]+)["\]}]\s+type leader or stage',
        t
    )
    if m_composto:
        costs.append({
            'type': 'rest_self_and_leader_or_stage',
            'filter_type': m_composto.group(1).strip(),
        })
    elif re.search(r'rest this (card|character|stage)', t):
        costs.append({'type': 'rest_self'})

    if re.search(r'trash this (character|card)', t):
        costs.append({'type': 'trash_self'})

    m_face_cost = re.search(
        r'you may turn 1 card from the top of your life cards face-(up|down)\s*:',
        t
    )
    if m_face_cost:
        costs.append({'type': f'turn_life_face_{m_face_cost.group(1)}'})

    # Custo de K.O. de um Character PROPRIO (distinto de trash_self: o alvo
    # nao e a carta que ativa o efeito, e outro Character do jogador, e o
    # K.O. dispara o [On K.O.] desse Character -- K.O. != Trash). Pode ter
    # filtro de tipo, em DUAS ordens de palavra possiveis:
    #   (a) "Characters with a type including 'X'" -- ex: OP14-079 Crocodile
    #   (b) "[X] type Characters" -- ex: OP06-083 Oars, OP14-080 Gecko Moria
    #       (achado em auditoria 27/06, nunca capturado antes -- a IA tratava
    #       como custo gratis, sem checar se tinha o character pra pagar)
    m = re.search(
        r'you may k\.?o\.? (?:up to )?(\d+) of your character'
        r'(?:s)?(?: with a type including [\'"\[{]([a-z][a-z0-9 .\'-]+)[\'"\]}])?', t)
    m_b = re.search(
        r'you may k\.?o\.? (?:up to )?(\d+) of your '
        r'[\["\{]([a-z][a-z0-9 .\'-]+)[\]"\}]\s*type\s+characters?', t)
    if m:
        cost = {'type': 'ko_own_character', 'count': int(m.group(1))}
        if m.group(2):
            cost['filter_type'] = m.group(2).strip()
        costs.append(cost)
    elif m_b:
        costs.append({'type': 'ko_own_character', 'count': int(m_b.group(1)),
                       'filter_type': m_b.group(2).strip()})

    # Custo de colocar N cartas do PRÓPRIO trash no fundo do PRÓPRIO deck
    # ("in any order" -- ordem é escolha do jogador, irrelevante pro engine).
    # Achado em auditoria de buff_cost 27/06: 51 cartas usam esse custo,
    # ZERO cobertura antes -- a IA tratava como grátis. 3 formas de filtro
    # de tipo + verbo "place" OU "return":
    #   (a) 'N "Tipo" type cards from your trash'        -- ex: Dragon, Garp
    #   (b) 'N cards with a type including "Tipo"'       -- ex: Kaku OP07-080
    #   (c) sem filtro: 'N cards from your trash'         -- ex: Trafalgar Law
    # NAO cobre (deliberado, fora de escopo por ora): combo "this Character
    # and N [Tipo]" (Kin'emon OP10-026/027, 2 cartas) nem "any number"
    # (Luffy OP07-091, 1 carta) -- ambos precisam de tratamento especial.
    m_a = re.search(
        r'you may (?:place|return) (\d+) [\'"\[{]([a-z][a-z0-9 .\'-]+?)[\'"\]}]\s*type\s+cards?'
        r' from your trash (?:at|to) the bottom of your deck', t)
    m_b2 = re.search(
        r'you may (?:place|return) (\d+) cards? with a type including'
        r' [\'"\[{]([a-z][a-z0-9 .\'-]+?)[\'"\]}] from your trash'
        r' (?:at|to) the bottom of your deck', t)
    m_c = re.search(
        r'you may (?:place|return) (\d+) cards? from your trash'
        r' (?:at|to) the bottom of your deck', t)
    if m_a:
        costs.append({'type': 'place_from_trash_bottom_deck',
                       'count': int(m_a.group(1)), 'filter_type': m_a.group(2).strip()})
    elif m_b2:
        costs.append({'type': 'place_from_trash_bottom_deck',
                       'count': int(m_b2.group(1)), 'filter_type': m_b2.group(2).strip()})
    elif m_c:
        costs.append({'type': 'place_from_trash_bottom_deck',
                       'count': int(m_c.group(1))})

    # rest N DON como custo. Cobre tanto "rest N of your DON" isolado quanto o
    # padrão COMPOSTO "rest this card and N of your DON!! cards" (ex: Empty
    # Throne OP13-099 -- rest_self + rest 3 DON), onde "rest" não vem colado ao
    # número. O rest_self acima já capturou a 1ª parte; aqui pegamos os DON.
    m = re.search(r'rest (?:this (?:card|character|stage) and )?(\d+) of your don!!', t)
    if m:
        costs.append({'type': 'rest_don', 'count': int(m.group(1))})
    else:
        # Forma "(N) (You may rest the specified number of DON!! cards in
        # your cost area.):" -- atalho numérico isolado entre parênteses,
        # com a explicação-padrão da regra também entre parênteses. Achado
        # 27/06 auditando [On Your Opponent's Attack] -- Viola OP04-021,
        # Giolla OP04-025, Trebol OP04-030 pagavam de graça antes disso.
        m_par = re.search(
            r'\((\d+)\)\s*\(you may rest the specified number of don!{0,2}\s*cards? in your cost area',
            t)
        if m_par:
            costs.append({'type': 'rest_don', 'count': int(m_par.group(1))})

    # Custo de trash do TOPO DO PRÓPRIO DECK (mill como custo, distinto de
    # trash_from_hand) -- "you may trash N cards from the top of your deck:
    # [efeito]". Verificado ANTES da regex generica de trash_from_hand
    # abaixo: sem esta prioridade, "N cards from the top of your deck:"
    # era erroneamente capturado como trash_from_hand, porque a alternancia
    # '(?:from your hand|character|card)' da regex generica casava a
    # palavra solta "card(s)" antes de checar se o destino real era o
    # deck, nao a mao (bug confirmado: EB04-042 Alpha e outras ~6 cards
    # com este padrao de custo explicito antes de ':').
    m = re.search(r'you may trash (\d+) cards? from the top of (?:your|the) deck\s*:', t)
    if m:
        costs.append({'type': 'trash_from_deck_top', 'count': int(m.group(1))})
    else:
        # Custo de trash da mao/campo (antes do efeito principal, padrão "...: efeito")
        # Captura variações: "trash N cards from your hand", "trash 1 [type] Character
        # or 1 card from your hand", "trash 1 of your Characters", etc.
        # O custo vem ANTES de um ':' que separa custo do benefício.
        # CASO ESPECIAL: "trash 1 of your [tipo] Characters OR 1 card from your hand"
        # (ex: leader Imu) -- é um custo com ESCOLHA. Capturado como tipo próprio
        # para não perder a opção de trashar character (engine decide qual gastar).
        m_choice = re.search(
            r'you may trash (\d+)[^:]*?characters?\s+or\s+\d+\s+cards?\s+from your hand\s*:', t)
        if m_choice:
            cost = {'type': 'trash_char_or_hand', 'count': int(m_choice.group(1))}
            ft = re.search(r"of your [\['\"{]([a-z][a-z0-9 .'-]+)[\]'\"}]\s+type characters", t)
            if ft:
                cost['filter_type'] = ft.group(1).strip()
            costs.append(cost)
        else:
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
    verbo_pega = take_m.group(0).split()[0] if take_m else 'add'  # 'reveal' | 'add' | 'play'

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
        'action': 'play_from_deck' if verbo_pega == 'play' else 'add_to_hand',
        'count': take_count,
    }
    # rastreamento de informacao conhecida pelo oponente: "reveal up to N
    # [filtro]" expoe a carta especifica adicionada a mao (181 das 221
    # cards de busca usam esse padrao -- confirmado oficialmente como
    # informacao publica, mesmo sendo o texto-padrao de search comum).
    # "add up to N" SEM a palavra reveal (ex: OP05-043) NAO expoe a carta.
    # "play up to N" vai direto pro campo, que ja e publico por natureza --
    # nao precisa do campo revealed (tratado pela action play_from_deck_search).
    if verbo_pega == 'add':
        take_step['revealed_to_opponent'] = False
    elif verbo_pega == 'reveal':
        take_step['revealed_to_opponent'] = True
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

    # Variante "K.O./trash N (ou up to N) de characters PROPRIOS com filtro
    # de TIPO explicito" -- contagem exata ou "up to", tipo sempre entre
    # [ ] / { } / "" , DISTINTA de "all of your characters" abaixo (sem
    # tipo, board wipe total sem filtro). Ex: Orlumbus OP04-079 "K.O. 1 of
    # your [Dressrosa] type Characters". Auditoria buff_cost 27/06.
    m_self_typed = re.search(
        VERBO + r" (up to (\d+)|(\d+)) of your "
        r'[\["\{]([a-z][a-z0-9 .\'-]+)[\]"\}]\s*type\s+characters?',
        t
    )
    if m_self_typed:
        # GUARD (mesma armadilha do trash_from_hand, ja corrigida 2x hoje):
        # "you may K.O. N of your [Tipo] type Characters: efeito" e CUSTO,
        # nao efeito incondicional -- nao duplicar como step aqui. Achado
        # ao validar OP06-083 Oars / OP14-080 Gecko Moria, que tem
        # exatamente essa frase como custo opcional, nao efeito solto.
        antes = t[max(0, m_self_typed.start() - 10):m_self_typed.start()]
        depois = t[m_self_typed.end():m_self_typed.end() + 3].lstrip()
        eh_custo = 'you may' in antes and depois.startswith(':')
        if not eh_custo:
            verbo_usado = re.match(r'k\.o\.|trash', m_self_typed.group(0)).group(0)
            action = 'ko' if verbo_usado == 'k.o.' else 'trash_character'
            count = int(m_self_typed.group(2) or m_self_typed.group(3))
            steps.append({
                'action': action, 'count': count, 'target': 'self_character',
                'filter_type': m_self_typed.group(4).strip(),
            })
            return steps

    # Variante "all of YOUR characters" (sem "opponent") -- alvo SO o
    # PROPRIO campo, distinto da variante sem qualificador abaixo (que
    # afeta AMBOS os lados). Ex: Five Elders OP13-082 "Trash all of your
    # Characters" (verbo trash -- nao dispara On K.O., e board wipe do
    # PROPRIO board pra reconstruir do trash em seguida). Auditoria 27/06,
    # confirmado por foto da carta real.
    m_self = re.search(VERBO + r" all of your characters", t)
    if m_self:
        verbo_usado = re.match(r'k\.o\.|trash', m_self.group(0)).group(0)
        action = 'ko' if verbo_usado == 'k.o.' else 'trash_character'
        steps.append({'action': action, 'count': 99, 'target': 'self_character'})
        return steps

    # Variante SEM "of your opponent" -- alvo AMBOS os lados, ex: "K.O. all
    # rested Characters with a cost of 5 or less" (sem qualificador de
    # posse = afeta characters de qualquer jogador, confirmado pelo
    # contexto de regra simetrica em OP05-040: a condicao trava Refresh
    # Phase de "your and your opponent's", e o KO no End of Turn segue a
    # mesma simetria). Mesma logica de separacao K.O./trash por verbo real.
    # "other than this character" (Kaido OP01-094, Kaido & Linlin OP08-119,
    # confirmado por foto 27/06) exclui a PROPRIA carta do board wipe --
    # sem isso o engine se autodestruiria junto com o resto do campo.
    m = re.search(
        VERBO + r" (up to (\d+)|all) (?:of the )?(?:rested )?characters?"
        r"(?: with a (?:base )?cost of (\d+)( or less)?)?"
        r"( other than this character)?",
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
        if m.group(5):
            step['exclude_self'] = True
        if 'rested' in m.group(0):
            step['rested_only'] = True
        steps.append(step)

    return steps


def parse_place_bottom(text):
    """
    "Place up to N of your opponent's Character(s) [with cost/power filter] at the
    bottom of the owner's deck." Remoção forte (enterra no fundo do deck, ignora
    On-KO). Distinta de bounce (vai pra mão) e de KO (vai pro trash).
    Filtros: cost_lte / power_lte. Respeita imunidade a removal no engine.
    """
    steps = []
    t = text.lower()
    # só do OPONENTE (o caso próprio é place_own_character_bottom_deck)
    m = re.search(
        r"place (?:up to )?(\d+) of your opponent's characters?"
        r"(?:[^.]*?(?:base )?cost of (\d+) or less)?"
        r"(?:[^.]*?(\d+) power or less)?"
        r"[^.]*?bottom of", t)
    if m:
        step = {'action': 'place_opp_character_bottom_deck', 'count': int(m.group(1))}
        if m.group(2):
            step['cost_lte'] = int(m.group(2))
        if m.group(3):
            step['power_lte'] = int(m.group(3))
        steps.append(step)
        return steps

    # Forma genérica sem "of your opponent" -- "Place up to N Character(s)
    # with a cost of X or less at the bottom of the owner's deck" (ex:
    # OP01-070 Mihawk, OP05-051 Borsalino, OP06-046 Sakazuki). Mesma
    # convenção já usada em parse_bounce: sem qualificador de posse, o
    # alvo é implicitamente o character do OPONENTE (regra do jogo).
    # Exclui "of your [Tipo] Characters" -- isso seria auto-bounce de
    # tribo pro fundo do deck, fora de escopo aqui (nenhum caso visto
    # ainda, mas guard por consistência com parse_bounce).
    m = re.search(
        r"place (?:up to )?(\d+) characters?"
        r"(?:[^.]*?(?:base )?cost of (\d+) or less)?"
        r"(?:[^.]*?(\d+) power or less)?"
        r"[^.]*?bottom of (?:the owner.?s|your) deck", t)
    if m:
        prefix = t[max(0, m.start() - 12):m.start()]
        if 'of your' in prefix or 'of you' in prefix:
            return steps
        step = {'action': 'place_opp_character_bottom_deck', 'count': int(m.group(1))}
        if m.group(2):
            step['cost_lte'] = int(m.group(2))
        if m.group(3):
            step['power_lte'] = int(m.group(3))
        steps.append(step)
    return steps


def parse_bounce(text):
    steps = []
    t = text.lower()
    if 'your opponent chooses' in t:
        return steps

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

    # Rest DON!! do OPONENTE -- mecânica distinta de rest_opp_character
    # (aqui o alvo é DON!! card no campo do oponente, não um Character).
    # Achado na auditoria do censo 0_nao_classificado (27/06): P-060 Tot
    # Musica, ST02-008 Scratchmen Apoo, EB03-012 Otama (parte de um
    # "choose one"). Nunca confundir com don_minus (que devolve DON ao
    # DECK do PRÓPRIO jogador como custo) -- aqui é desvantagem temporária
    # imposta no oponente, o DON continua no campo dele, só fica rested.
    m_don = re.search(r"rest (?:up to (\d+)|(\d+)) of your opponent.{0,15}don!{0,2}\s*cards?", t)
    if m_don:
        steps.append({
            'action': 'rest_opp_don',
            'count': int(m_don.group(1) or m_don.group(2)),
        })
        return steps

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


def parse_set_active(text):
    """
    "Set [alvo] as active" -- desrestar fora da Refresh Phase normal.
    DISTINTO de set_don_active (DON!! cards especificamente, já cobre seu
    próprio padrão -- aqui excluímos qualquer match com 'don!!' no meio
    pra nunca duplicar). Alvos vistos no banco (26 cartas, censo padrão 8,
    nunca implementado antes):
      'this Character'                          -> target='self'
      'this Leader'                              -> target='leader'
      'up to N of your [Tipo] Characters...'     -> target='own_character'
      'up to N of your [Tipo] Characters and
       your Leader'                              -> target='own_character_and_leader'
      'up to N of your [Tipo] Leader or
       Character cards'                          -> target='leader_or_character'
      'up to N of your [Tipo] Leader'             -> target='leader'
    Filtros possíveis no mesmo trecho: filter_type, attribute, color,
    cost_lte/cost_eq, power_lte/power_eq, rested_only.
    """
    steps = []
    t = text.lower()

    for m in re.finditer(r'set ([^.]*?) as active', t):
        desc = m.group(1)
        if 'don!!' in desc:
            continue   # cobertura própria em set_don_active, não duplicar
        # "...add up to N DON!! card(s)... AND set it as active" -- o "it"
        # refere-se ao DON!! card da clausula ANTERIOR, não um character.
        # 'don!!' não aparece dentro do proprio desc (so na frase anterior),
        # por isso o filtro acima nao pega. Achado ao validar 74 cartas que
        # teriam virado 'own_character' por engano (EB01-021 e outras).
        antes = t[max(0, m.start() - 60):m.start()]
        if desc.strip() in ('it', 'this', 'them') and 'don!!' in antes:
            continue
        step = {'action': 'set_active'}

        desc_strip = desc.strip()
        if desc_strip == 'this character':
            step['target'] = 'self'
        elif desc_strip == 'this leader':
            step['target'] = 'leader'
        else:
            count_m = re.match(r'up to (\d+) of your', desc_strip)
            if count_m:
                step['count'] = int(count_m.group(1))
            elif 'all of your' in desc:
                step['count'] = 99   # ex: OP16-038 "your Leader and all of your Characters"
            else:
                step['count'] = 1

            # "your leader and X" (leader no INICIO, ex: OP16-038) OU "X and
            # your leader" (leader no FIM, ex: Carrot EB04-013) -- as duas
            # ordens aparecem no banco, achado ao validar essa carta.
            if 'leader and' in desc or 'and your leader' in desc:
                step['target'] = 'own_character_and_leader'
            elif 'leader or character' in desc:
                step['target'] = 'leader_or_character'
            elif 'leader' in desc and 'character' not in desc:
                step['target'] = 'leader'
            else:
                step['target'] = 'own_character'

            type_m = (re.search(r'"([a-z][a-z0-9 .\'-]+)"\s+type', desc)
                      or re.search(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}]\s+type', desc))
            if type_m:
                step['filter_type'] = type_m.group(1).strip()
            else:
                # Filtro por NOME PRÓPRIO (sem "type" depois, ex: "[Kuro]
                # cards"/"[Foxy] cards"/"[Charlotte Linlin] Characters") --
                # mesma distinção já feita pra buff_cost (Shinobu OP16-087).
                name_m = re.search(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}]\s+(?:cards?|characters?)', desc)
                if name_m:
                    step['filter_name'] = name_m.group(1).strip()
            attr_m = re.search(r'"([a-z]+)"\s+attribute', desc)
            if attr_m:
                step['attribute'] = attr_m.group(1).strip()
            color_m = re.search(
                r'your (purple|red|green|blue|yellow|black)\s+'
                r'(?:[\[{"][a-z][a-z0-9 .\'-]+[\]}"]\s+type\s+)?characters', desc)
            if color_m:
                step['color'] = color_m.group(1)
            cost_m = re.search(r'cost of (\d+)( or less)?', desc)
            if cost_m:
                if cost_m.group(2):
                    step['cost_lte'] = int(cost_m.group(1))
                else:
                    step['cost_eq'] = int(cost_m.group(1))
            power_m = re.search(r'(\d+) power( or less)?', desc)
            if power_m:
                if power_m.group(2):
                    step['power_lte'] = int(power_m.group(1))
                else:
                    step['power_eq'] = int(power_m.group(1))
            if 'rested' in desc:
                step['rested_only'] = True
        if 'at the end of this turn' in t[max(0, m.start() - 20):m.end() + 45]:
            step['timing'] = 'end_of_turn'
        steps.append(step)

    return steps


def parse_can_attack_active(text):
    """
    "This Character can also attack active Characters" (PERMANENTE, sem
    seleção -- Cavendish OP04-081, Luffy OP04-090) ou "Up to N of your
    [Tipo] Leader or Character cards can also attack active Characters
    during this turn" (TEMPORÁRIO, com seleção -- Hibari, Gyats, Borsalino,
    Aramaki, Kuzan, Koby). Keyword nunca implementada antes, achada na
    auditoria do censo 27/06 (9 cartas).
    """
    steps = []
    t = text.lower()

    if re.search(r'this character can also attack active characters?', t):
        steps.append({'action': 'gain_can_attack_active'})
        return steps

    m_select = re.search(
        r'(?:up to (\d+) of your|your) '
        r'(?:[\["\{]([a-z][a-z0-9 .\'-]+)[\]"\}]\s+type\s+)?'
        r'(?:leader or character|characters?)'
        r'[^.]*?can also attack active characters?', t)
    if m_select:
        step = {'action': 'select_grant_can_attack_active_turn',
                'count': int(m_select.group(1)) if m_select.group(1) else 1}
        if m_select.group(2):
            step['filter_type'] = m_select.group(2).strip()
        if 'leader or character' in m_select.group(0):
            step['include_leader'] = True
        steps.append(step)

    return steps


def parse_select_unblockable_turn(text):
    """
    "Select up to 1 of your [Tipo] Character(s)/Leader-or-Character... If
    the selected card attacks during this turn, your opponent cannot
    activate [Blocker]." Equivalente por regra (10-1-7-1) a conceder
    [Unblockable] SO NESTE TURNO ao alvo escolhido. DISTINTA de
    gain_unblockable (alvo sempre 'card', sem seleção, sem expiração).

    3 cartas no banco hoje (Sanji ST21-003, Diable Jambe ST01-016, OP13-057
    -- esta última sem seleção, sempre o Leader, daí target='leader_only').
    Perfume Femur (OP07-057) e Trafalgar Law (OP12-077): "select + buff" no
    MESMO alvo ("...and that card gains +2000 power. Then, if the selected
    card attacks...") -- consome a memoria de alvo entre steps preenchida
    pelo step de buff_power anterior (target='select_filtered',
    _last_selected no engine; implementado 28/06/2026, ver SaveTargetName em
    comparacao_simulador_vs_IA.md), em vez de re-selecionar do zero.
    Rayleigh (OP12-016, alvo = quem recebeu o DON!! do custo, nao de um step)
    fica de fora -- memoria de CUSTO->efeito e um mecanismo diferente, nao
    implementado.
    """
    t = text.lower()
    steps = []

    # "...and that card gains +N power... Then, if the selected
    # card/character attacks..." -- prova de que um step de buff_power
    # ANTERIOR no mesmo bloco ja selecionou o alvo (ver parse_power_buff,
    # m_select_buff). Reusa esse alvo via memoria entre steps, em vez da
    # re-selecao independente por filtro feita abaixo (que poderia escolher
    # uma carta DIFERENTE da que recebeu o buff).
    if re.search(r"and that card gains? \+\d+\s*power", t) and \
       re.search(r"(?:the selected (?:card|character)|that (?:card|leader or character)) attacks", t):
        steps.append({'action': 'select_grant_unblockable_turn', 'target': 'selected'})
        return steps

    # OP13-057: sem seleção, sempre o próprio Leader, condicional a vida.
    if re.search(r"opponent cannot activate \[?blocker\]?.{0,10}whenever your leader attacks.{0,10}during this turn", t):
        steps.append({'action': 'select_grant_unblockable_turn', 'target': 'leader_only'})
        return steps

    # Sanji / Diable Jambe: "select up to 1 of your [Tipo] Character(s)
    # [with N power or more]. If/Your opponent cannot...if that
    # Leader-or-Character/Character attacks during this turn, opponent
    # cannot activate [Blocker]."
    m_select = re.search(
        r"select up to (\d+) of your \{?([a-z .'’-]+?)\}? type (characters?|leader or character cards?)"
        r"(?: with (\d+) power or more)?", t)
    if m_select and 'cannot activate' in t and ('blocker' in t):
        step = {
            'action': 'select_grant_unblockable_turn',
            'filter_type': m_select.group(2).strip(),
        }
        if m_select.group(4):
            step['power_gte'] = int(m_select.group(4))
        if 'leader or character' in m_select.group(3):
            step['include_leader'] = True
        steps.append(step)

    return steps


def parse_lock_blocker_battle(text):
    """
    "Your opponent cannot activate [a] [Blocker] [Character that has N
    power] [Character with a cost of N or less] during this battle."

    Trava TRANSITÓRIA, escopo de UMA batalha (a que está sendo resolvida
    agora, sempre via [When Attacking]) -- DISTINTA de parse_lock_attack
    (que trava ataque/rest com duração entre turnos, persistente). Nunca
    unificar: aqui some no fim desta mesma batalha; lá persiste.

    Filtros vistos no banco: power_lte / power_gte / cost_lte (nunca dois
    juntos na mesma carta). Sem filtro = trava o campo inteiro do oponente.
    """
    t = text.lower()
    steps = []

    m = re.search(r"blocker.{0,15}character that has (\d+) (or less|or more) power.{0,30}during this battle", t)
    if m:
        step = {'action': 'lock_opp_blocker_battle'}
        if m.group(2) == 'or less':
            step['power_lte'] = int(m.group(1))
        else:
            step['power_gte'] = int(m.group(1))
        steps.append(step)
        return steps

    m = re.search(r"blocker.{0,20}character with a cost of (\d+) or less.{0,30}during this battle", t)
    if m:
        steps.append({'action': 'lock_opp_blocker_battle', 'cost_lte': int(m.group(1))})
        return steps

    # Sem filtro -- as duas formas acima já tentaram e falharam, então
    # qualquer "cannot activate [Blocker] ... during this battle" que
    # sobrar aqui é incondicional (campo inteiro).
    if re.search(r"cannot activate \[?blocker\]?.{0,5}during this battle", t):
        steps.append({'action': 'lock_opp_blocker_battle'})

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

    # Self-lock: "This Character cannot attack" -- trava no PROPRIO
    # Character, geralmente como contrapartida de um efeito forte
    # (balanceamento). NUNCA tratar como lock_opp_character_attack (alvo
    # oposto). Cobre tambem a variante condicional 'cannot attack unless
    # [condicao do board]' -- aqui a condicao fica embutida na propria
    # frase de ataque (distinto de lock_opp_attack_unless_pays, que e sobre
    # o oponente pagar um custo por ataque; aqui e sobre o ESTADO DO BOARD
    # permitir ou nao o proprio ataque, sem custo nenhum envolvido).
    if re.search(r'this character cannot attack(?! a leader)', t):
        unless_m = re.search(r'this character cannot attack unless ([^.]+)', t)
        if unless_m:
            cond_texto = unless_m.group(1).strip()
            cond_estruturada = parse_conditions(cond_texto)
            step_unless = {'action': 'cannot_attack_self_unless'}
            if cond_estruturada:
                step_unless['conditions'] = cond_estruturada
            else:
                # fallback: condicao ainda nao reconhecida por
                # parse_conditions -- preserva o texto cru para auditoria
                # futura em vez de descartar silenciosamente, mas o engine
                # trata ausencia de 'conditions' estruturada como travado
                # sempre (mais seguro: forcar o lock incondicionalmente do
                # que assumir liberado sem confirmar a condicao real).
                step_unless['condition_text'] = cond_texto
            steps.append(step_unless)
        else:
            steps.append({'action': 'cannot_attack_self'})
        # Padrao adicional, raro: alem do self-lock acima, o MESMO bloco pode
        # conter uma 2a frase independente travando OUTROS Characters por
        # filtro de custo, condicionada a um Leader especifico (ex: P-084
        # 'This Character cannot attack. If your Leader is [Buggy], all
        # Characters with a cost of 3 or 4 cannot attack.'). A condicao fica
        # DENTRO do step (nao no nivel do entry/passive), pois parse_conditions
        # roda sobre o bloco inteiro e contaminaria o self-lock incondicional
        # acima se fosse anexada no entry. Carta unica confirmada -- escopo
        # minimo, sem generalizar para outras variantes de filtro.
        cond_leader_m = re.search(r"if your leader is \[([^\]]+)\]", t)
        mass_m = re.search(
            r'all characters with a cost of (\d+)(?: or (\d+))? cannot attack',
            t
        )
        if mass_m and cond_leader_m:
            costs_alvo = [int(mass_m.group(1))]
            if mass_m.group(2):
                costs_alvo.append(int(mass_m.group(2)))
            steps.append({
                'action': 'cannot_attack_own_characters_by_cost',
                'costs': costs_alvo,
                'conditions': {'leader_is': cond_leader_m.group(1).strip()},
            })
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
    # Tambem cobre "select all of your opponent's Characters" (sem "up to"
    # -- count = 99, convencao usada em outros parsers para "all").
    m_select = (re.search(r"select up to (\d+) of your opponent.{0,15}characters?(?: with a cost of (\d+) or less)?", t)
                or re.search(r"select all of your opponent.{0,15}characters?(?: with a cost of (\d+) or less)?", t))
    is_select_all = m_select and 'up to' not in m_select.group(0)
    m_efeito = re.search(r"the selected character.{0,5} cannot (attack|be rested) until ([^.]+)", t)
    if m_select and m_efeito:
        action = 'lock_opp_character_attack' if m_efeito.group(1) == 'attack' else 'lock_opp_cannot_be_rested'
        count = 99 if is_select_all else int(m_select.group(1))
        cost_group = m_select.group(2) if not is_select_all else m_select.group(1)
        step = {'action': action, 'count': count, 'duration': parse_duration(m_efeito.group(2))}
        if cost_group:
            step['cost_lte'] = int(cost_group)
        steps.append(step)
        return steps

    # Variante condicional ao pagamento: "none of the selected Character(s)
    # can attack unless your opponent trashes N cards from their hand
    # whenever they attack" -- distinta do lock incondicional acima ("until"
    # sem escape). Aqui o oponente PODE atacar pagando um custo a cada
    # ataque; nao e um lock binario. Mecanica rara (carta unica no banco
    # ate o momento desta auditoria) -- decision_engine ainda nao simula a
    # decisao "vale a pena pagar", entao por ora o campo e so capturado
    # (fica disponivel para a fase Opponent Reading implementar depois).
    m_unless = re.search(
        r"none of the selected character.{0,5} can attack unless your opponent "
        r"trashes (\d+) cards? from their hand whenever they attack",
        t
    )
    if m_select and m_unless:
        count = 99 if is_select_all else int(m_select.group(1))
        cost_group = m_select.group(2) if not is_select_all else m_select.group(1)
        # duration: procura clausula "until the end of..." antes do "select"
        dur_m = re.search(r"until ([^,]+),", t[:t.find('select')]) if 'select' in t else None
        step = {
            'action': 'lock_opp_attack_unless_pays',
            'count': count,
            'duration': parse_duration(dur_m.group(1)) if dur_m else 'until_opp_turn_end',
            'cost_type': 'trash_from_hand',
            'cost_amount': int(m_unless.group(1)),
        }
        if cost_group:
            step['cost_lte'] = int(cost_group)
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

    # lock_opp_blocker_turn: "cannot activate [Blocker]... during this turn"
    # -- DISTINTA de lock_opp_blocker_battle (essa e "during this BATTLE",
    # transitoria, ja tratada em parse_lock_blocker_battle). Aqui e
    # persistente (dura alem desta batalha, igual cannot_attack_until) e
    # mira 1 character ESPECIFICO escolhido pela IA, nao o campo filtrado.
    # 2 formas vistas no banco (Limejuice OP09-014, Kuzan OP16-063).
    m_block_power = re.search(
        r"cannot activate up to (\d+) \[?blocker\]? character that has (\d+) power or less"
        r"[^.]*?during this turn", t)
    if m_block_power:
        steps.append({
            'action': 'lock_opp_blocker_turn',
            'count': int(m_block_power.group(1)),
            'power_lte': int(m_block_power.group(2)),
            'duration': 'until_opp_turn_end',
        })
        return steps

    m_block_plain = re.search(
        r"up to (\d+) of your opponent.{0,15}characters? cannot activate \[?blocker\]?"
        r"[^.]*?during this turn", t)
    if m_block_plain:
        steps.append({
            'action': 'lock_opp_blocker_turn',
            'count': int(m_block_plain.group(1)),
            'duration': 'until_opp_turn_end',
        })
        return steps

    # Variante com filtro de custo/power ENTRE "character(s)" e "cannot
    # activate" (ordem de frase distinta de m_block_power/m_block_plain
    # acima), e/ou "All" no lugar de "up to N" (campo inteiro filtrado,
    # nao so 1 character). 3 cartas no banco hoje: OP11-013 (all + power),
    # OP12-051 (up to 1 + cost), ST21-016 (up to 1 + power). count=99 para
    # "all" segue a mesma convencao de is_select_all usada acima neste
    # arquivo -- decision_engine.py ja faz min(count, len(candidates)).
    m_block_filtered = re.search(
        r"(all|up to (\d+)) of your opponent.{0,15}characters?"
        r"(?: with (?:a base cost of (\d+) or less|(\d+) power or less))?"
        r" cannot activate \[?blocker\]?[^.]*?during this turn", t)
    if m_block_filtered:
        step = {
            'action': 'lock_opp_blocker_turn',
            'count': 99 if m_block_filtered.group(1) == 'all' else int(m_block_filtered.group(2)),
            'duration': 'until_opp_turn_end',
        }
        if m_block_filtered.group(3):
            step['cost_lte'] = int(m_block_filtered.group(3))
        if m_block_filtered.group(4):
            step['power_lte'] = int(m_block_filtered.group(4))
        steps.append(step)
        return steps

    return steps


def parse_shuffle_hand(text):
    """
    "Return all cards in your hand to your deck and shuffle. Then draw equal to
    the number returned" (OP04-048, P-002) OU "place all hand at bottom of deck,
    if you do draw equal" (P-046). Redesenha a mão do mesmo tamanho.
      dest:      'deck' (shuffle) | 'deck_bottom'
      draw_back: True  (compra = nº devolvido)
      optional:  True se "if you do" / "you may"
    """
    t = text.lower()
    to_bottom = bool(re.search(r'place all (?:the )?cards in your hand (?:on|at) the bottom', t))
    optional  = ('you may place all' in t) or ('if you do' in t)
    draw_back = bool(re.search(r'draw cards? equal to the number', t))
    return [{
        'action':    'shuffle_hand_into_deck',
        'dest':      'deck_bottom' if to_bottom else 'deck',
        'draw_back': draw_back,
        'optional':  optional,
    }]


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
    dynamic_spans = []

    def target_from_context(ctx: str) -> str:
        if 'your leader or 1 of your characters' in ctx or 'your leader or character' in ctx:
            return 'leader_or_character'
        if 'your leader' in ctx:
            return 'leader'
        if 'all of your characters' in ctx:
            return 'all_allies'
        return 'self'

    # Buffs dinamicos do ActV3: Passive1KPerXTrash,
    # Passive1KPerXEventTrash, Passive1KPerXRestedDon e variantes simples.
    # Captura antes do buff fixo para nao degradar "+1000 por N" em "+1000".
    dynamic_patterns = [
        (r'gains? \+(\d+)\s*power\s+for every (\d+) events? in your trash',
         'events_in_trash'),
        (r'gains? \+(\d+)\s*power\s+for every (\d+) cards? in your trash',
         'trash'),
        (r'gains? \+(\d+)\s*power\s+for every (\d+) of your rested don!! cards?',
         'rested_don'),
        (r'gains? \+(\d+)\s*power\s+for every card in your hand',
         'hand'),
        (r'gains? \+(\d+)\s*power\s+for each of your characters with a different card name',
         'unique_character_names'),
        (r'gains? \+(\d+)\s*power\s+for each of your characters(?! with a different card name)',
         'own_characters'),
    ]
    for pattern, source in dynamic_patterns:
        for dm in re.finditer(pattern, t):
            contexto_antes = t[max(0, dm.start() - JANELA_ANTES):dm.start()]
            amount_per = int(dm.group(1))
            count_per = int(dm.group(2)) if dm.lastindex and dm.lastindex >= 2 and dm.group(2) else 1
            steps.append({
                'action': 'buff_power_per_count',
                'amount_per': amount_per,
                'count_per': count_per,
                'source': source,
                'target': target_from_context(contexto_antes),
                'duration': 'this_turn',
            })
            dynamic_spans.append((dm.start(), dm.end()))

    # "Select up to N of your [Tipo]/{Tipo}/"Tipo" Leader or Character cards
    # and that card gains +X power" (OP07-057, OP12-077) ou "Up to N of your
    # [Tipo] type Characters gains +X power" (EB02-021, sem a palavra
    # "select", mas com "the selected Character" depois) -- alvo escolhido
    # por FILTRO DE TIPO entre Leader+Characters, distinto de 'self' (a
    # propria carta do efeito) e de 'own_character' (sem memoria de
    # selecao). Tipo aparece com 3 estilos de delimitador inconsistentes na
    # fonte (achado 28/06/2026) -- TIPO_BRACKETS cobre os 3. Guarda
    # filter_type para a action escolher o alvo certo em tempo de execucao,
    # e habilita memoria de alvo entre steps (SaveTargetName, ver
    # comparacao_simulador_vs_IA.md).
    TIPO_BRACKETS = r'(?:\{([^}]+)\}|\[([^\]]+)\]|"([^"]+)")'
    m_select_buff = re.search(
        r"(?:select )?up to (\d+) of your " + TIPO_BRACKETS +
        r"(?: type)? (?:leader or character cards|character cards|leader or character|characters|cards)"
        r"(?:\s+and that card)? gains? \+(\d+)\s*power",
        t
    )
    if m_select_buff:
        count = int(m_select_buff.group(1))
        filtro = next((g for g in m_select_buff.groups()[1:4] if g), '').strip()
        amount = int(m_select_buff.group(5))
        step = {
            'action': 'buff_power', 'amount': amount,
            'target': 'select_filtered', 'duration': 'this_turn', 'count': count,
        }
        if filtro:
            step['filter_type'] = filtro
        steps.append(step)
        dynamic_spans.append((m_select_buff.start(), m_select_buff.end()))

    for m in re.finditer(r'([+\-−]?)\s*(\d+)\s*power', t):
        if any(start <= m.start() < end for start, end in dynamic_spans):
            continue
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

        # Filtros do alvo 'own_character' (selecao entre os PROPRIOS
        # characters, sem tipo -- distinto de 'select_filtered', que e por
        # tipo). 15 cartas reais no banco usam esse alvo, algumas com filtro
        # de power ("with N (base) power or less") ou exclusao de nome
        # ("other than [Nome]") -- sem isso a action escolheria QUALQUER
        # character, ignorando a restrição do texto.
        power_lte_own = None
        exclude_own = ''
        if target == 'own_character':
            m_plte = re.search(r'with (\d+) (?:base )?power or less', contexto_antes)
            if m_plte:
                power_lte_own = int(m_plte.group(1))
            m_excl = re.search(r'other than \[([^\]]+)\]', contexto_antes)
            if m_excl:
                exclude_own = m_excl.group(1).strip()

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

        step = {
            'action': 'debuff_power' if is_debuff else 'buff_power',
            'amount': amount, 'target': target, 'duration': duration
        }
        if power_lte_own is not None:
            step['power_lte'] = power_lte_own
        if exclude_own:
            step['exclude'] = exclude_own
        steps.append(step)

    return steps


def parse_set_base_power(text):
    """'[X]'s base power becomes N' -- SUBSTITUI o valor de power, nao soma
    como buff_power/debuff_power. Distinto e nunca deve ser unificado: um
    Character com base power 5000 e +2000 de buff tem 7000 de power; se um
    segundo efeito diz 'base power becomes 6000', o resultado e 6000 (a
    SUBSTITUICAO ignora buffs aditivos anteriores aplicados sobre a base),
    nao 6000+2000. Alvos confirmados no banco: Leader, o proprio Character
    ('this Character'), 'up to N of your Leader or Character cards', e 'all
    of your [TIPO] cards' -- escopo deliberadamente restrito a esses 4
    padroes textuais confirmados (8 cards), sem generalizar para variantes
    nao vistas."""
    steps = []
    t = text.lower()

    for m in re.finditer(r"([a-z][a-z0-9 {}\[\]\"'.\-]*?)'s? base power becomes (\d+)", t):
        sujeito = m.group(1).strip()
        amount = int(m.group(2))
        contexto_depois = t[m.end():m.end() + 60]

        if re.search(r'\bleader\b', sujeito) and 'character' not in sujeito:
            target = 'leader'
        elif 'this character' in sujeito:
            target = 'self'
        elif re.search(r'\bleader or character\b', sujeito):
            # alvo ambiguo (escolha do jogador entre Leader OU Character) --
            # marca os dois alvos possiveis explicitamente em vez de
            # adivinhar um dos dois; quem consumir decide a prioridade.
            target = 'leader_or_own_character'
        elif re.search(r'\ball of your\b', sujeito) or re.search(r'up to \d+ of your', sujeito):
            target = 'own_character'
        else:
            # sujeito nao reconhecido com confianca -- nao captura em vez
            # de adivinhar o alvo errado (ex: poderia ser do OPONENTE, que
            # ainda nao apareceu em nenhuma carta confirmada).
            continue

        step = {'action': 'set_base_power', 'amount': amount, 'target': target}

        count_m = re.search(r'up to (\d+) of your', sujeito)
        if count_m:
            step['count'] = int(count_m.group(1))
        type_m = (re.search(r'"([a-z][a-z0-9 .\'-]+)"\s+type', sujeito)
                  or re.search(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}]', sujeito))
        if type_m:
            step['filter_type'] = type_m.group(1).strip()

        if re.search(r'until the end of your opponent.?s next (?:end phase|turn)', contexto_depois):
            step['duration'] = 'until_opp_turn_end'
        elif re.search(r'during this turn', contexto_depois):
            step['duration'] = 'this_turn'
        else:
            step['duration'] = 'this_turn'  # default observado nas cartas confirmadas sem clausula explicita
        steps.append(step)

    # "[Tipo]'s base power becomes the same as [fonte]" -- SEM numero literal
    # (MatchLeaderToBasePower, achado 28/06/2026, 12 cartas reais). Distinto
    # do loop acima (que exige `becomes (\d+)`, valor fixo): aqui o valor e
    # DINAMICO, calculado em tempo de execucao a partir de outra carta no
    # estado do jogo (engine usa effective_power(), nao um amount fixo do
    # banco). 3 fontes confirmadas:
    #   'opp_leader'              -- "...the same as your opponent's Leader
    #                                 (during this turn|'s (base )?power...)"
    #   'own_leader'              -- "...the same as your Leader's base power"
    #   'selected_opp_character'  -- precedido de "select up to 1 of your
    #                                 opponent's characters", copia da carta
    #                                 selecionada (selecao e copia no MESMO
    #                                 step, sem precisar de memoria entre
    #                                 steps -- distinto do SaveTargetName)
    # Fica de fora: "the same as the power of your opponent's ATTACKING
    # Leader or Character" (OP04-069, 1 carta) -- exige saber QUEM esta
    # atacando no momento da resolucao, contexto de batalha que o
    # set_base_power nao tem acesso hoje. Nao implementado (raro).
    m_dyn = re.search(
        r"this character'?s base power becomes the same as "
        r"(your opponent'?s leader|your leader'?s base power|the selected character'?s power)",
        t
    )
    if m_dyn:
        fonte = m_dyn.group(1)
        if 'selected character' in fonte:
            source = 'selected_opp_character'
        elif 'your leader' in fonte and "opponent" not in fonte:
            source = 'own_leader'
        else:
            source = 'opp_leader'
        step = {'action': 'set_base_power', 'target': 'self', 'source': source}
        contexto_depois = t[m_dyn.end():m_dyn.end() + 60]
        step['duration'] = ('until_my_turn_start' if 'until the start of your next turn' in contexto_depois
                             else 'this_turn')
        steps.append(step)

    return steps


def parse_give_don(text):
    steps = []
    t = text.lower()

    # Dar/anexar DON — distinguir alvo (aliado vs oponente) e se o DON
    # retirado do banco e especificamente RESTED (qualificador explicito no
    # texto, ex: "give up to 1 rested DON!! card") -- sem o qualificador, a
    # IA escolhe entre DON rested/ativo do banco na hora de executar.
    m = re.search(r'give up to (\d+) (rested )?don!! cards?[^.]{0,60}', t)
    if m:
        cnt = int(m.group(1))
        is_rested = bool(m.group(2))
        clause = m.group(0)
        # alvo: se menciona "opponent" DENTRO da clausula do give (nao em
        # outro efeito mais adiante na mesma carta), é setup no oponente
        # (controle) senão é buff em personagem próprio (aggro). Tambem
        # cobre o padrao indireto "its owner's Leader/Character" quando o
        # CUSTO anterior ja estabeleceu "1 of your opponent's..." -- "its
        # owner" refere-se a esse oponente, nao a "you".
        to_opp = bool(re.search(r"to .{0,30}opponent.?s (leader|character)", clause)) or \
                 bool(re.search(r"opponent.?s characters?:?\s*$", clause)) or \
                 bool(re.search(r"from .{0,15}opponent.?s cost area", clause)) or \
                 (bool(re.search(r"to its owner.?s (leader|character)", clause))
                  and bool(re.search(r"of your opponent.?s (rested )?(don!!|character)", t[:m.start()])))
        step = {
            'action': 'give_don_opp' if to_opp else 'give_don',
            'count': cnt,
        }
        if is_rested:
            step['rested'] = True
        steps.append(step)

    # Aceleração REAL: adicionar DON do seu deck de DON ao seu campo (ramp)
    if re.search(r'add up to \d+ don!! cards? from your don!! deck|add \d+ don!! cards? from your don!! deck', t):
        m2 = re.search(r'add up to (\d+) don!! cards?|add (\d+) don!! cards?', t)
        if m2:
            steps.append({'action': 'add_don', 'count': int(m2.group(1) or m2.group(2))})

    # Reativar DON (set as active) = aceleração
    m = re.search(r'set (up to )?(\d+)? ?(?:of your )?don!! cards?.* as active', t)
    if m:
        step = {'action': 'set_don_active', 'count': int(m.group(2)) if m.group(2) else 1}
        if m.group(1):
            step['up_to'] = True
        if 'at the end of this turn' in m.group(0) or 'at the end of this turn' in t[max(0, m.start() - 20):m.end() + 40]:
            step['timing'] = 'end_of_turn'
        steps.append(step)

    if re.search(r'at the end of this turn, return don!! cards from your field to your don!! deck until you have the same number of don!! cards on your field as your opponent', t):
        steps.append({'action': 'return_don_until_match_opp', 'timing': 'end_of_turn'})

    # Trava de "nao ficar ativo no Refresh" -- distinguir alvo: DON especifico,
    # Character/Leader especifico (do OPONENTE, com filtro opcional de custo),
    # ou self-lock (o proprio Character do efeito, sem "opponent" no texto --
    # geralmente custo de um efeito forte, ex: "this Character will not
    # become active" / "the selected Character will not become active").
    # NUNCA tratar self-lock como lock_opp_*: alvo errado muda completamente
    # quem perde a jogada no proximo turno.
    m_self = re.search(
        r"(this character|the selected characters?) will not become active",
        t
    )
    if m_self and 'opponent' not in t[:m_self.start()]:
        step = {'action': 'lock_self_character_refresh', 'count': 1}
        # 'this character' = a propria carta do efeito, alvo sem ambiguidade
        # (OP04-090). 'the selected character(s)' = a carta escolhida por um
        # step ANTERIOR no mesmo bloco (ex: EB02-021, "up to 1 Character
        # gains +6000 power... THEN the selected Character will not become
        # active") -- exige memoria de alvo entre steps, que o engine ainda
        # nao tem (mesma raiz do gap SaveTargetName/residuais de
        # OppNoBlockerThisTurn). target='this_card' e executado de verdade;
        # target='selected' fica so reconhecido (engine nao aplica ainda).
        step['target'] = 'this_card' if m_self.group(1) == 'this character' else 'selected'
        steps.append(step)
        return steps

    # Padrao principal (cobre a maioria): "up to N / all of your opponent's
    # rested Characters [with a cost of X or less] will not become active".
    # cost_lte so e anexado quando o texto realmente traz o filtro -- nunca
    # assumir um valor default que nao esta escrito na carta.
    m = re.search(
        r"(up to (\d+)|all) of your opponent.?s rested "
        r"(don!! cards?|leader and character cards?|characters?|character cards?|leader cards?|cards?)"
        r"(?: with a cost of (\d+) or less)?"
        r" will not become active",
        t
    )
    if m:
        cnt = 99 if m.group(1) == 'all' else int(m.group(2))
        tipo = m.group(3)
        cost_lte = m.group(4)
        if tipo.startswith('don'):
            step = {'action': 'lock_opp_don_refresh', 'count': cnt}
        else:
            # 'cards'/'card' generico (sem especificar Character/Leader) e
            # tambem modelado como character_refresh -- caso mais comum
            # nesse fraseado quando o substantivo nao e explicito.
            step = {'action': 'lock_opp_character_refresh', 'count': cnt}
        if cost_lte:
            step['cost_lte'] = int(cost_lte)
        steps.append(step)
        return steps

    # Variante sem "rested": "up to N of your opponent's Characters with a
    # cost of X will not become active" -- aqui o custo e EXATO (cost_eq),
    # nao "ou menos" (sem a clausula "or less" apos o numero). Ex: OP05-094
    # "Characters with a cost of 0 will not become active".
    m_eq = re.search(
        r"up to (\d+) of your opponent.?s characters? with a cost of (\d+) will not become active",
        t
    )
    if m_eq:
        steps.append({
            'action': 'lock_opp_character_refresh',
            'count': int(m_eq.group(1)),
            'cost_eq': int(m_eq.group(2)),
        })
        return steps

    if re.search(r"opponent's .{0,30}will not become active|will not become active", t):
        # fallback final: padrao nao identificado claramente pelos casos
        # acima. Mantido como lock_opp_don por compatibilidade com a
        # convencao anterior, mas a essa altura da auditoria a maioria dos
        # casos reais (Character com filtro de custo/power, DON given,
        # Stages) ja deveria ter caido nos ramos especificos -- se uma carta
        # nova cair aqui, vale revisar o texto antes de assumir que e DON.
        steps.append({'action': 'lock_opp_don'})

    return steps


def parse_transfer_don(text):
    """
    Cobre duas variantes distintas, ambas com action 'transfer_don' (move
    DON para um Character ja em campo, sem consumir o DON disponivel do
    pool igual a give_don):
      1) "give up to N of your currently given DON!! cards to 1 of your
         [TIPO] Character(s)" -- move DON ja anexado a OUTRO character/
         leader para o alvo (transferencia real entre characters).
      2) "give up to N of your [TIPO/power] Characters up to M rested
         DON!! card(s) each" -- distribui DON do pool entre VARIOS
         characters, M por alvo, ate N alvos (distribution='free').
    """
    steps = []
    t = text.lower()

    # Variante 1: transferencia de DON ja anexado
    m = re.search(
        r"give up to (\d+)(?: total)? of your currently given don!! cards? to (\d+) of your"
        r"(?: \[?\"?([a-z][a-z0-9 .\'-]+?)\"?\]? type)? characters?",
        t
    )
    if m:
        step = {'action': 'transfer_don', 'count': int(m.group(1)), 'target': 'friendly_character'}
        if m.group(3):
            step['filter_type'] = m.group(3).strip()
        steps.append(step)
        return steps

    # Variante 2: distribuicao do pool para multiplos alvos
    m2 = re.search(
        r"give up to (\d+) of your"
        r"(?: ((?:\[[a-z][a-z0-9 .\'-]+?\]\s*(?:or\s*)?)+) type)?"
        r" characters?(?: with (\d+) base power)?"
        r" up to (\d+) rested don!! cards? each",
        t
    )
    if m2:
        step = {
            'action': 'transfer_don',
            'count': int(m2.group(1)),
            'target': 'own_character',
            'distribution': 'free',
            'per_target_max': int(m2.group(4)),
        }
        if m2.group(2):
            tipos = re.findall(r'\[([a-z][a-z0-9 .\'-]+?)\]', m2.group(2))
            step['filter_type'] = tipos if len(tipos) > 1 else tipos[0]
        if m2.group(3):
            step['filter_power_base_eq'] = int(m2.group(3))
        steps.append(step)

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


def parse_reveal_top_play(text):
    """
    Padrao "reveal 1 card from the top of your deck, play up to N Character
    card(s) [filtro], (then) place the rest at the top or bottom of your
    deck" -- DISTINTO de parse_look_at (que exige "look at N cards..." e
    olha MULTIPLAS cartas antes de escolher). Aqui sempre revela 1 carta so
    e decide na hora jogar ou nao -- sem janela de escolha entre varias.
    Confirmado em 6 cards que escapavam de parse_play_generic e
    parse_play_from_deck por nao conterem a frase EXATA "from your deck"
    (diziam "from THE TOP OF your deck"): OP06-057, OP08-052, OP08-054,
    ST12-010, ST12-013, ST12-017.
    """
    steps = []
    t = text.lower()

    if not re.search(r'reveal 1 card from the top of (?:your|the) deck', t):
        return steps

    m = re.search(r'play up to (\d+) [^.]*?character card', t)
    if not m:
        return steps
    count = int(m.group(1))

    type_m = re.search(r'type including "([^"]+)"', t)
    cost_m = re.search(r'with a cost of (\d+) or less', t)
    rested = bool(re.search(r'character card[^.]*\brested\b', t))

    steps.append({
        'action': 'play_from_deck',
        'count': count,
        'filter_type': type_m.group(1).strip() if type_m else '',
        'cost_lte': int(cost_m.group(1)) if cost_m else 99,
        'reveal_count': 1,
        'rested': rested,
    })
    return steps


def parse_play_generic(text):
    """Play sem origem explícita: 'Play this card', 'Play up to N ... Character card'."""
    steps = []
    t = text.lower()
    if 'play this card' in t:
        steps.append({'action': 'play_card', 'count': 1, 'source': 'self'})
        return steps
    m = re.search(
        r'play up to (\d+) [^.]*?'
        r'(?:(?:character|stage) cards?'        # "Character card"/"Stage card" (forma original)
        r'|type cards?'                          # "[Tipo] type card" generico, sem a palavra Character/Stage
        r'|characters?\b(?!\s*card)'              # "red Character"/"Character with..." sem "card" depois
        r'|[\[{][a-z][a-z0-9 .\'-]+[\]}](?!\s+type))',  # "[Nome]" carta especifica por nome, nao tipo
        t)
    # Exclusao de DECK/trash olha so a JANELA PROXIMA da clausula "play up
    # to..." (curto alcance: clausula anterior conectada por ":" ou inicio
    # de frase), NAO o texto inteiro -- olhar o texto inteiro causa falso
    # negativo quando "from your deck"/"from your trash" pertence a uma
    # CLAUSULA ANTERIOR nao relacionada. Caso real: OP15-109 tem "add up to
    # 1 card from the top of your deck to your life cards" numa clausula de
    # busca, seguida por "play up to 1 [...] from your HAND" numa clausula
    # SEPARADA -- a checagem no texto inteiro bloqueava o play_card por
    # engano (a carta e de jogar da MAO, sem relacao com o deck mencionado
    # antes). Janela = do inicio da ultima clausula (apos ':' ou '.' mais
    # proximo antes do match) até o fim do match.
    inicio_clausula = max(t.rfind(':', 0, m.start()), t.rfind('. ', 0, m.start())) if m else -1
    fim_sentenca = t.find('.', m.end()) if m else -1
    fim_janela = fim_sentenca if fim_sentenca != -1 else (m.end() if m else 0)
    janela = t[inicio_clausula + 1:fim_janela] if m else ''
    sem_origem_deck = 'from your deck' not in janela and 'from the top of your deck' not in janela
    if m and sem_origem_deck and 'from your trash' not in janela:
        # exclui tambem o padrao "look at N cards from the top of your
        # deck ... play up to N [filtro]" -- ja tratado integralmente por
        # parse_look_at() como play_from_deck (respeitando a janela das N
        # cartas vistas, nao o deck inteiro). Sem esta exclusao, esse

        # padrao gerava DUAS actions de jogar a mesma carta (bug
        # pre-existente, 17 cards: EB01-009, EB02-025, OP01-116, etc).
        precedido_de_look = bool(re.search(r'look at \d+ cards? from the top of (?:your|the) deck', t[:m.start()]))
        if not precedido_de_look:
            cost_m = re.search(r'with a cost of (\d+) or less', janela)
            cost_eq_m = re.search(r'with a cost of (\d+)(?! or less)', janela)
            # filter_type/color: mesma regex usada em parse_play_from_deck.
            # Antes ausente aqui -- confirmado faltando em OP13-099 (Empty
            # Throne: "play up to 1 BLACK \"Five Elders\" type Character
            # card..."), que perdia o filtro de arquetipo/cor inteiramente.
            type_m = (re.search(
                r'play up to \d+ (?:black |red |blue |green |yellow |purple )?"([a-z][a-z0-9 .]+)" type',
                janela)
                or re.search(
                r'play up to \d+ (?:black |red |blue |green |yellow |purple )?[\[{]([a-z][a-z0-9 .\'-]+)[\]}]\s+type',
                janela))
            color_m = re.search(r'play up to \d+ (black|red|blue|green|yellow|purple)', janela)
            # cost_lte DINAMICO: "with a cost equal to or less than the
            # number of DON!! cards on your/your opponent's field" --
            # confirmado em 4 cartas (OP13-099 Empty Throne, OP08-098
            # Kalgara, OP11-022 Shirahoshi: lado PROPRIO; P-090 Charlotte
            # Smoothie: lado do OPONENTE, unica das 4 com "opponent's"
            # entre "number of don!! cards on" e "field"). Resolvido em
            # runtime por EffectExecutor._resolve_cost_lte.
            dyn_m = re.search(
                r'number of don!{0,2} cards on (your opponent.{0,3}s|your) field', janela)
            if dyn_m:
                cost_lte_val = 'don_count_opp' if 'opponent' in dyn_m.group(1) else 'don_count_self'
            elif cost_m:
                cost_lte_val = int(cost_m.group(1))
            else:
                cost_lte_val = 99
            cost_eq_val = int(cost_eq_m.group(1)) if (cost_eq_m and not cost_m and not dyn_m) else None
            step = {
                'action': 'play_card', 'count': int(m.group(1)),
                'cost_lte': cost_lte_val,
            }
            if cost_eq_val is not None:
                step['cost_eq'] = cost_eq_val
                del step['cost_lte']   # exato substitui o limite generico, nao soma
            if type_m:
                step['filter_type'] = type_m.group(1).strip()
            else:
                # Filtro por NOME PRÓPRIO (sem "type" depois, ex: "Play up
                # to 1 [Gaimon] from your hand" -- carta especifica, nao
                # arquetipo). Mesma distinção já feita pra buff_cost
                # (Shinobu) e set_active (Kuro/Foxy). Achado 27/06. NUNCA
                # usar o mesmo nome que já está em "other than [X]" --
                # esse colchete é so exclusão, não filtro (ex: Dogura
                # "red Character other than [Dogura]": sem isso, virava
                # "jogar [Dogura] que não seja [Dogura]" = sempre vazio).
                excl_m_probe = re.search(r'other than [\[{]([a-z][a-z0-9 .\'-]+)[\]}]', janela)
                for name_cand in re.finditer(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}](?!\s+type)', janela):
                    nome = name_cand.group(1).strip()
                    if excl_m_probe and nome == excl_m_probe.group(1).strip():
                        continue
                    step_filter_name = nome
                    break
                else:
                    step_filter_name = None
                if step_filter_name:
                    step['filter_name'] = step_filter_name
            if color_m:
                step['color'] = color_m.group(1)
            # "other than [Nome]" -- exclui a propria carta-fonte (ou outra
            # especifica) da lista de elegiveis, ex: Bepo "other than
            # [Bepo]", Dogura "other than [Dogura]".
            excl_m = re.search(r'other than [\[{]([a-z][a-z0-9 .\'-]+)[\]}]', janela)
            if excl_m:
                step['exclude'] = excl_m.group(1).strip()
            # "from your hand or trash" -- fonte flexivel, nao so a mao.
            if 'from your hand or trash' in janela:
                step['source_alt'] = 'trash'
            # "...from your hand rested" -- entra em campo JA restado
            # (oposto do normal). Ex: Coribou "play up to 1 [Caribou]...
            # from your hand rested."
            if re.search(r'from your hand(?: or trash)? rested\b', janela):
                step['enters_rested'] = True
            steps.append(step)
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
        clause = t[:m.start()+len(m.group(0))]
        # "give this card [in your hand] -N cost" e SEMPRE auto-referencia
        # (geralmente reduzir o proprio custo para jogar, condicionado a
        # algo do board state -- ex: estar atras em DON). A palavra
        # 'opponent' pode aparecer na CONDICAO anterior ('if your opponent
        # has...', 'less than the number on your opponent's field') sem
        # ter nada a ver com o alvo do give -- 'give this card' decide o
        # alvo antes de checar 'opponent' na clausula inteira.
        if re.search(r'give this card', clause):
            target = 'self'
        else:
            target = 'opp_character' if "opponent" in clause else 'own_character'
        step = {
            'action': 'debuff_cost' if is_debuff else 'buff_cost',
            'amount': int(m.group(2)), 'target': target,
        }
        count_m = re.search(r'up to (\d+) of (?:your opponent\'s|your)', clause)
        if count_m:
            step['count'] = int(count_m.group(1))
        elif 'all of your opponent' in clause or 'all of your' in clause:
            step['count'] = 99
        steps.append(step)
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
        # CLAUSULA escopada em DUAS camadas (bug confirmado por foto/leitura
        # real 27/06, dois casos distintos):
        # 1) Limita a SENTENCA atual (depois do ultimo '.') -- sem isso,
        #    type_m/color_m vazavam pra frases SEGUINTES nao-relacionadas
        #    (Marshall.D.Teach OP16-080: "{Blackbeard Pirates} type" era de
        #    uma habilidade [On Your Opponent's Attack] diferente).
        # 2) Dentro da sentenca, se existir 'all of your'/'up to N of your',
        #    comeca DALI -- sem isso, cost_gte_m vazava da condicao de
        #    ativacao ANTERIOR na mesma sentenca (OP14-098: "if there is a
        #    Character with a cost of 8 or more" e a condicao, nao o filtro
        #    do alvo do buff).
        inicio_periodo = t.rfind('.', 0, m.start()) + 1
        sentenca = t[inicio_periodo:m.end()]
        alvo_m = re.search(r'(?:all of your|up to \d+ of your)', sentenca)
        clause = sentenca[alvo_m.start():] if alvo_m else sentenca

        count_m = re.search(r'up to (\d+) of your', clause)
        if count_m:
            step['count'] = int(count_m.group(1))
        elif 'all of your' in clause:
            step['count'] = 99
        type_m = (re.search(r'"([a-z][a-z0-9 .\'-]+)"\s+type', clause)
                  or re.search(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}]\s+type', clause)
                  or re.search(r'type including ["\[{]([a-z][a-z0-9 .\'-]+)["\]}]', clause))
        if type_m and not is_self:
            step['filter_type'] = type_m.group(1).strip()
        else:
            # Filtro por NOME PRÓPRIO (sem "type" depois) -- ex: Shinobu
            # OP16-087 "up to 1 of your [Kouzuki Momonosuke] gains +20
            # cost" (nome de personagem entre [], NAO um tipo). Achado
            # 27/06: antes vazava o filter_type da condição anterior na
            # mesma frase ("{Land of Wano} type" pertencia ao "if your
            # Leader has..."), já corrigido pelo escopo de clausula acima
            # -- mas faltava capturar o filtro REAL (por nome) que sobra.
            name_m = re.search(r'[\[{]([a-z][a-z0-9 .\'-]+)[\]}]\s+gains?\s+[+\-−]\d+ cost', clause)
            if name_m and not is_self:
                step['filter_name'] = name_m.group(1).strip()
        color_m = re.search(r'your (black|red|green|blue|yellow|purple) characters', clause)
        if color_m and not is_self:
            step['color'] = color_m.group(1)
        # filtro de custo MINIMO no proprio alvo (distinto de cost_lte, usado
        # para filtrar o ALVO do debuff no oponente -- aqui e o oposto: so os
        # characters com custo >= N recebem o auto-buff/debuff). Ex: OP10-042
        # 'all of your "Dressrosa" type Characters with a cost of 2 or more
        # gain +1 cost'. Mesma clausula de 2 camadas acima.
        cost_gte_m = re.search(r'with a cost of (\d+) or more', clause)
        if cost_gte_m and not is_self:
            step['cost_gte'] = int(cost_gte_m.group(1))
        duration_m = re.search(r'until the end of your opponent.?s next (?:end phase|turn)', t)
        step['duration'] = 'until_opp_turn_end' if duration_m else 'permanent'
        steps.append(step)

    return steps


def parse_life(text):
    """
    Manipulação de vida — UMA action por operação atômica, com eixos:

      gain_life     : adiciona à SUA vida
        source: deck_top | hand | own_field | opp_life | trash
        dest:   life_top | life_bottom | life_top_or_bottom
        count:  int (N fixo)
        up_to:  bool  (True = "up to N", opcional)
        face:   'up' | 'down'  (engine ainda não modela face; campo preservado)

      life_to_hand  : "comprar" da SUA vida para a mão (ex: Hiyori OP06-106)
        source: life_top | life_bottom | life_top_or_bottom
        count, up_to

      attack_life   : remove da vida do OPONENTE -- vai DIRETO pro trash, SEM
        checar [Trigger] (padrao textual "trash ... opponent's life").
        count, up_to

      trash_own_life: descarta da SUA vida (custo/troca)
        count, up_to, until_1 (bool: "until you have 1 Life card")

      deal_damage   : dano direto ao oponente, FORA de combate (ex: Nico Robin
        EB03-055 "[On K.O.] You may deal 1 damage", Reject OP06-116 "If your
        opponent has 1 Life card, deal 1 damage"). Regra oficial (comprehensive
        rules 4-6): a vida vai pra MAO e, se tiver [Trigger], pode ser revelada
        e ativada -- == o mesmo fluxo que dano de combate ao Leader ja usa.
        NUNCA unificar com attack_life: e o oposto semantico (mao+trigger vs
        trash sem trigger), mesma logica que separa K.O. de trash_character.
        count, target ('opponent' -- unico valor visto no banco; campo
        generico para nao travar se aparecer "self" no futuro)

    Regra de design (auditoria 25/06): NUNCA juntar duas operações numa action.
    "trash life: add life" = trash_own_life (custo) + gain_life (efeito), 2 steps.
    'heal' foi unificado aqui em gain_life (corrige bug top/bottom do parse_heal).
    """
    steps = []
    t = text.lower()

    def qty_in(seg):
        m = re.search(r'(\d+) cards?', seg)
        return int(m.group(1)) if m else 1

    def up_to_in(seg):
        return 'up to' in seg

    def dest_from(seg):
        has_top = 'top of your life' in seg or 'top of the owner' in seg
        has_bot = 'bottom of your life' in seg or 'bottom of the owner' in seg
        if has_top and has_bot:
            return 'life_top_or_bottom'
        if has_bot:
            return 'life_bottom'
        return 'life_top'   # default: topo

    def source_from(seg):
        if 'top of your deck' in seg:                return 'deck_top'
        if 'from your hand' in seg:                  return 'hand'
        if 'from your trash' in seg:                 return 'trash'
        if 'character' in seg and 'your' in seg:     return 'own_field'
        return 'deck_top'   # fallback mais comum

    # ── gain_life: ADIÇÃO à própria vida ───────────────────────────────
    # Ancorar na CLÁUSULA "add ... to (top/bottom of) your/the owner's
    # life" e ler source/dest/qty SÓ de dentro dela (seg = o próprio
    # match), nunca do texto todo -- senão vaza entre cláusulas (ex:
    # Hiyori, custo + efeito). "the owner's life cards" (Kawamatsu
    # OP06-103) é sinônimo de "your life" aqui -- mesmo dono, fraseado
    # diferente porque a regra original usa "owner" genericamente.
    if re.search(r'look at up to 1 card from the top of your or your opponent.?s life cards?', t):
        steps.append({'action': 'peek_life', 'target': 'any', 'count': 1})
    elif re.search(r'look at up to 1 card from the top of your opponent.?s life cards?', t):
        steps.append({'action': 'peek_life', 'target': 'opponent', 'count': 1})
    elif re.search(r'look at all of your opponent.?s life cards?|look at all your opponent.?s life cards?', t):
        steps.append({'action': 'peek_life', 'target': 'opponent', 'count': 'all'})
    elif re.search(r'look at all of your life cards?|look at all your life cards?', t):
        steps.append({'action': 'peek_life', 'target': 'self', 'count': 'all'})

    if re.search(r'turn all of your life cards face-down', t):
        steps.append({'action': 'turn_life_face_down', 'target': 'self', 'count': 'all'})
    m_turn = re.search(r'turn 1 card from the top of your life cards face-(up|down)', t)
    if m_turn:
        after = t[m_turn.end():m_turn.end() + 2]
        if not after.lstrip().startswith(':'):
            steps.append({'action': f"turn_life_face_{m_turn.group(1)}", 'target': 'self', 'count': 1})

    if re.search(r'trash all your face-up life cards?', t):
        steps.append({'action': 'trash_own_life', 'face': 'up', 'count': 'all'})

    m = re.search(r'(add|put)[^.:]*?to (?:the (?:top|bottom|top or bottom) of )?(?:your|the owner.?s) life(?: cards?)?', t)
    if m and 'trash' not in m.group(0):
        seg = m.group(0)
        step = {
            'action': 'gain_life',
            'source': source_from(seg),
            'dest':   dest_from(seg),
            'count':  qty_in(seg),
            'up_to':  up_to_in(seg),
        }
        # Filtro de power no PRÓPRIO character fonte (só relevante quando
        # source == own_field, ex: Kawamatsu "1 of your Characters with 0
        # power"). Sem isso a IA poderia mandar qualquer character pra
        # vida, nao só os de power exato pedido pela carta.
        if step['source'] == 'own_field':
            power_m = re.search(r'with (\d+) power', seg)
            if power_m:
                step['power_eq'] = int(power_m.group(1))
        face_window = t[m.start():m.end() + 25]
        if 'face-up' in face_window or 'face up' in face_window:
            step['face'] = 'up'
        elif 'face-down' in face_window or 'face down' in face_window:
            step['face'] = 'down'
        steps.append(step)

    # ── life_to_hand: "comprar" da própria vida → mão ──────────────────
    # SÓ quando é EFEITO puro (sem ':' logo após, que indicaria custo de
    # outro efeito). Padrão de custo "add 1 from Life to hand: [efeito]"
    # (~40 cartas, arquétipo Whitebeard) é tratado em parse_costs, NÃO aqui
    # -- senão a IA executaria o custo como benefício grátis. (auditoria 25/06)
    m = re.search(r'add[^.:]*?from the (top|bottom|top or bottom) of your life cards? to your hand', t)
    if m:
        after = t[m.end():m.end() + 2]
        is_cost = after.lstrip().startswith(':')
        if not is_cost:
            seg = m.group(0)
            where = m.group(1)
            src = ('life_top_or_bottom' if where == 'top or bottom'
                   else 'life_bottom' if where == 'bottom' else 'life_top')
            steps.append({
                'action': 'life_to_hand',
                'source': src,
                'count':  qty_in(seg),
                'up_to':  up_to_in(seg),
            })

    # ── attack_life: trash da vida do OPONENTE ─────────────────────────
    m = re.search(r"trash[^.:]*opponent's life", t)
    if m:
        steps.append({
            'action': 'attack_life',
            'count':  qty_in(m.group(0)),
            'up_to':  up_to_in(m.group(0)),
        })

    # ── trash_own_life: descarta da própria vida ───────────────────────
    m = re.search(r'trash[^.:]*from (?:the top of )?your life', t)
    if m:
        step = {'action': 'trash_own_life', 'count': qty_in(m.group(0)),
                'up_to': up_to_in(m.group(0))}
        if 'until you have 1 life' in t:
            step['until_1'] = True
        steps.append(step)

    # ── deal_damage: dano direto, FORA de combate ──────────────────────
    # Ancora em "to your opponent" -- nunca aparece no texto-lembrete de
    # [Double Attack]/[Banish] ("This card deals 2 damage." / "When this
    # card deals damage, the target card is trashed..."), então não
    # precisaria do guard, mas mantém por segurança caso uma carta nova
    # use fraseado parecido dentro de parenteses.
    for m in re.finditer(r'deal[s]? (\d+) damage to your opponent', t):
        contexto_antes = t[max(0, m.start() - 15):m.start()]
        if '(this card' in contexto_antes or '(when this card' in contexto_antes:
            continue
        steps.append({
            'action': 'deal_damage',
            'count':  int(m.group(1)),
            'target': 'opponent',
        })

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


def parse_opp_trash_from_hand(text):
    """'Your opponent trashes N cards from their hand' -- disrupcao de mao
    FORCADA no oponente (sem 'up to', a quantidade exata e descartada por
    escolha dele). Distinto de trash_from_hand (sempre sobre o PROPRIO
    jogador) -- nunca unificar, alvo e oposto."""
    steps = []
    t = text.lower()
    m = re.search(r'your opponent trashes (\d+) cards? from (?:their|his|her) hand', t)
    if m:
        steps.append({'action': 'opp_trash_from_hand', 'count': int(m.group(1))})
    m2 = re.search(r'your opponent chooses (\d+) cards? from your hand;? trash', t)
    if m2:
        steps.append({'action': 'opp_choose_trash_our_hand', 'count': int(m2.group(1))})
    return steps


def parse_opp_self_move_character(text):
    """
    'Your opponent returns N of their Characters to the owner's hand'
    (OP06-051 Tsuru) / 'Your opponent places N of their Characters at the
    bottom of the owner's deck' (P-055 Luffy) -- FORCA o oponente a mover
    1 dos PROPRIOS characters dele (ele escolhe qual -- aproximamos
    escolhendo o PIOR por board_value, mesmo criterio ja usado em toda
    escolha "sacrifique o pior" do engine). DISTINTO de bounce/
    place_opp_character_bottom_deck (onde EU escolho o MELHOR do oponente
    pra remover) -- aqui o alvo e dele, a escolha (aproximada) e dele.
    Achado por foto real 27/06, expondo um efeito que nunca tinha sido
    parseado (mascarado por um bug de duplicacao de trash_from_hand).
    """
    steps = []
    t = text.lower()
    m_choose_bounce = re.search(
        r"your opponent chooses (\d+) of (?:their|his|her) characters?(?: with a cost of (\d+) or less)?[^.]*return",
        t
    )
    if m_choose_bounce:
        step = {'action': 'opp_bounce_own_character', 'count': int(m_choose_bounce.group(1))}
        if m_choose_bounce.group(2):
            step['cost_lte'] = int(m_choose_bounce.group(2))
        steps.append(step)
    m = re.search(r"your opponent returns (\d+) of (?:their|his|her) characters? to the owner.?s hand", t)
    if m:
        steps.append({'action': 'opp_bounce_own_character', 'count': int(m.group(1))})
    m2 = re.search(r"your opponent places (\d+) of (?:their|his|her) characters? at the bottom of the owner.?s deck", t)
    if m2:
        steps.append({'action': 'opp_place_own_character_bottom_deck', 'count': int(m2.group(1))})
    # 'Your opponent returns N DON!! card(s) from their field to their
    # DON!! deck' -- mesma familia (forca o oponente), agora sobre DON em
    # vez de Character. DISTINTO de don_minus (custo do PROPRIO jogador).
    m3 = re.search(r"your opponent returns (\d+) don!{0,2}\s*cards? from (?:their|his|her) field", t)
    if m3:
        steps.append({'action': 'opp_don_minus', 'count': int(m3.group(1))})
    return steps


# ===========================================================================
# Parser principal de um bloco de texto
# ===========================================================================

def parse_immunity(text):
    """
    Imunidade passiva. Dois tipos presentes no banco (os tipos exóticos do
    simulador — effect-immune genérico, combat-immune — não aparecem no pool):
      - 'ko'      : "cannot be K.O.'d"
      - 'removal' : "cannot be removed from the field"
    source: 'opp' se "by your opponent's effects" (só efeitos do oponente),
            senão 'any'. A condição (DON xN / Opponent's Turn / If...) é tratada
            pelo sistema de conditions do parser, no nível do entry/step.
    """
    t = text.lower()
    steps = []
    src = 'opp' if "opponent's effect" in t or "opponents effect" in t else 'any'
    if re.search(r"cannot be k\.?o\.?'?d|can'?t be k\.?o", t):
        steps.append({'action': 'immunity', 'imm_type': 'ko', 'source': src})
    if re.search(r'cannot be removed from the field|can'+chr(39)+r't be removed from the field', t):
        steps.append({'action': 'immunity', 'imm_type': 'removal', 'source': src})
    return steps


def parse_block(block_text, trigger_name):
    """Parseia um bloco de efeito e retorna lista de steps.

    CASO ESPECIAL -- 'Choose one: • opcao A • opcao B [• opcao C]': as
    opcoes sao ALTERNATIVAS MUTUAMENTE EXCLUSIVAS (o jogador escolhe uma),
    nao efeitos que acontecem em sequencia. Sem este tratamento, os steps
    de todas as opcoes eram concatenados na mesma lista 'steps', fazendo o
    engine acreditar que TODOS os efeitos aconteciam juntos -- falso para
    qualquer carta com essa estrutura (confirmado: 19 cards no banco).
    Retorna uma lista contendo um unico dict sentinela {'_choice': [...]}
    em vez de steps normais; parse_card_effect (unico caller que monta o
    'entry' final) reconhece esse formato e popula entry['choice'] no
    lugar de entry['steps'], preservando o contrato de 'steps' para todo
    o resto do parser (cada item de 'steps' sempre tem 'action').
    """
    if re.search(r'choose(?:s)? one\s*:', block_text, re.IGNORECASE):
        opcoes_raw = re.split(r'[•\u2022]', block_text)
        # primeiro item e o texto antes do primeiro bullet (geralmente so
        # 'Choose one:' e eventual condicao -- nao e uma opcao)
        opcoes_raw = [o.strip() for o in opcoes_raw[1:] if o.strip()]
        if len(opcoes_raw) >= 2:
            opcoes_parseadas = []
            for opcao_texto in opcoes_raw:
                sub_steps = parse_block(opcao_texto, trigger_name)
                if sub_steps:
                    opcoes_parseadas.append(sub_steps)
            if len(opcoes_parseadas) >= 2:
                choice = {'_choice': opcoes_parseadas}
                if re.search(r'your opponent chooses? one\s*:', block_text, re.IGNORECASE):
                    choice['_choice_chooser'] = 'opponent'
                return [choice]
            # se so 1 opcao parseou com sucesso (outras nao reconhecidas
            # pelo parser ainda), nao ha alternativa real capturavel --
            # cai no comportamento normal abaixo em vez de fingir uma
            # escolha de 1 item so.

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
            prefix = re.split(r"if .*?would be removed from the field", t, maxsplit=1)[0]
            dyn_steps = [
                s for s in parse_power_buff(prefix)
                if s.get('action') == 'buff_power_per_count'
            ]
            return dyn_steps + sub_steps

    # Imunidade (passiva): "cannot be K.O.'d" / "cannot be removed from the
    # field". Roda ANTES de parse_ko para a frase não ser lida como um KO real.
    # type: 'ko' | 'removal'; source: 'opp' (só efeitos do oponente) | 'any';
    # a CONDIÇÃO (DON xN, Opponent's Turn, estado) é capturada pelo sistema de
    # conditions do parse_card_effect (timing/[DON]/If...), não aqui.
    imm = parse_immunity(t)
    if imm:
        steps.extend(imm)

    # Busca
    if 'look at' in t:
        steps.extend(parse_look_at(t))

    # KO (e seu sinonimo "trash" quando remove Character do OPONENTE -- ex:
    # "Trash up to 1 of your opponent's Characters with a cost of 4 or
    # less". Gatilho 'trash up to' (nao 'trash' generico) para nao disparar
    # em trash_from_hand/trash_self, que sao muito mais comuns no texto.)
    # KO (e seu sinonimo "trash" quando remove Character do OPONENTE -- ex:
    # "Trash up to 1 of your opponent's Characters with a cost of 4 or
    # less". Gatilho 'trash up to' (nao 'trash' generico) para nao disparar
    # em trash_from_hand/trash_self, que sao muito mais comuns no texto.
    # 'trash all of your characters' (Five Elders) e 'all characters other
    # than this character' (Kaido) tambem precisam do gate -- nao tem
    # 'opponent' nem 'trash up to', ficavam fora antes (auditoria 27/06).
    if ('k.o.' in t or ('trash up to' in t and 'opponent' in t)
            or 'trash all of your characters' in t
            or 'all characters other than this character' in t):
        steps.extend(parse_ko(t))

    # Bounce (oponente OU auto-bounce do proprio character)
    if 'return' in t and 'hand' in t:
        steps.extend(parse_bounce(t))

    # Place character at bottom of deck (remoção forte, ≠ bounce/KO). Cobre
    # tanto "of your opponent's character(s)" quanto a forma genérica sem
    # qualificador (ex: OP01-070 Mihawk) -- a função decide o resto.
    if 'bottom of' in t and 'character' in t:
        steps.extend(parse_place_bottom(t))

    # Restar oponente
    if 'rest up to' in t and 'opponent' in t:
        steps.extend(parse_rest_opp(t))

    # Trava de Blocker do oponente, so NESTA batalha (when_attacking) --
    # DISTINTA da trava de ataque/rest com duracao (abaixo). Roda ANTES
    # pra nao deixar "during this battle" cair no parser errado.
    if 'blocker' in t and 'during this battle' in t and 'cannot activate' in t:
        steps.extend(parse_lock_blocker_battle(t))

    # "can also attack active Characters" -- keyword nova (achada 27/06).
    if 'can also attack active' in t:
        steps.extend(parse_can_attack_active(t))

    # Unblockable concedido via "select + if attacks this turn" ou fixo no
    # Leader (Sanji, Diable Jambe, OP13-057) -- equivalente por regra a
    # gain_unblockable, mas SO neste turno e com alvo selecionado/fixo.
    if 'blocker' in t and 'cannot activate' in t and 'during this turn' in t and 'select' in t:
        steps.extend(parse_select_unblockable_turn(t))
    elif 'blocker' in t and 'cannot activate' in t and 'whenever your leader attacks' in t:
        steps.extend(parse_select_unblockable_turn(t))

    # "Set [alvo] as active" -- desrestar fora do Refresh normal. Exclui
    # don!! explicitamente dentro da função (set_don_active já cobre).
    if ' as active' in t and 'set ' in t:
        steps.extend(parse_set_active(t))

    # Trava de ataque / trava de ser restado / trava de Blocker persistente
    # (mecanicas distintas, cobertas pela mesma funcao por compartilharem
    # estrutura textual). 'can attack unless' e a variante de
    # custo-condicional (carta paga para atacar), distinta de 'cannot
    # attack until' (lock binario incondicional). O terceiro ramo ("cannot
    # activate...blocker...during this turn") e a variante PERSISTENTE da
    # trava de Blocker (Limejuice/Kuzan) -- distinta da transitoria acima,
    # que exige "during this battle" e já foi tratada primeiro.
    if (('cannot attack' in t or 'cannot be rested' in t or 'can attack unless' in t)
            and ('opponent' in t or 'this character cannot attack' in t)) or \
       ('blocker' in t and 'cannot activate' in t and 'during this turn' in t):
        steps.extend(parse_lock_attack(t))

    # Transferencia/distribuicao de DON entre characters (distinto de
    # give_don, que da DON do pool a um unico alvo)
    if 'don!!' in t and ('currently given' in t or 'rested don!! card' in t):
        steps.extend(parse_transfer_don(t))

    # Auto-restrição "you cannot play ... this turn" (combo de ramp).
    # 3 variantes: tudo da mão / characters / characters com base cost >= N.
    m = re.search(r'you cannot play (?:any )?(cards? from your hand|character cards?)(?:[^.]*?base cost of (\d+) or more)?[^.]*?(?:during this turn|this turn)', t)
    if m:
        what = m.group(1)
        if 'from your hand' in what:
            steps.append({'action': 'self_cant_play', 'scope': 'hand'})
        else:
            st = {'action': 'self_cant_play', 'scope': 'chars'}
            if m.group(2):
                st['cost_gte'] = int(m.group(2))
            steps.append(st)

    if re.search(r'you cannot attack a leader[^.]*during this turn', t):
        steps.append({'action': 'cannot_attack_leader_turn'})

    # Shuffle/cycle hand into deck (+ draw back) -- ANTES do draw, pois o texto
    # "...Then, draw N" senão geraria um 'draw' duplicado. O draw-back já está
    # embutido na action shuffle_hand_into_deck (draw_back=True).
    shuffled_hand = False
    if re.search(r'return all (?:the )?cards in your hand to your deck', t) or \
       re.search(r'place all (?:the )?cards in your hand (?:on|at) the bottom of your deck', t):
        steps.extend(parse_shuffle_hand(t))
        shuffled_hand = True

    # Draw (sem look at). Pula se já tratado como shuffle_hand (draw-back embutido).
    if 'draw' in t and 'look at' not in t and not shuffled_hand:
        steps.extend(parse_draw(t))

    # Power buff/debuff (com ou sem sinal explicito -- parse_power_buff agora
    # infere o sinal pelo alvo quando o texto nao traz +/- explicito)
    if 'power' in t:
        steps.extend(parse_power_buff(t))

    # 'base power becomes N' -- SUBSTITUICAO do valor, mecanica distinta de
    # buff_power (aditivo). Regex de parse_power_buff exige 'N power' (numero
    # antes da palavra), e aqui e 'power becomes N' (numero depois) -- nao ha
    # conflito/duplicacao entre as duas chamadas.
    if 'base power becomes' in t:
        steps.extend(parse_set_base_power(t))

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

    # Play from deck -- "reveal 1 from TOP, play" (padrao sem "look at",
    # decisao imediata sobre 1 carta so -- ver docstring de
    # parse_reveal_top_play). Roda ANTES do padrao com "from your deck"
    # literal/"look at", que e estrutura diferente (janela de N cartas).
    if re.search(r'reveal 1 card from the top of (?:your|the) deck', t):
        steps.extend(parse_reveal_top_play(t))

    # Play from deck
    if 'from your deck' in t and 'play up to' in t and 'look at' not in t:
        steps.extend(parse_play_from_deck(t))

    # Manipulação de vida (gain_life/life_to_hand/attack_life/trash_own_life/
    # deal_damage). 'heal' foi unificado em gain_life dentro de parse_life
    # (corrige bug top/bottom). deal_damage não tem a palavra 'life' no
    # texto ("deal 1 damage to your opponent") -- por isso o gate cobre
    # também esse padrão, não só 'life' in t.
    if 'life' in t or ('deal' in t and 'damage' in t):
        steps.extend(parse_life(t))

    # Trash do TOPO DO PRÓPRIO DECK como EFEITO (mill, distinto do custo
    # trash_from_deck_top em parse_costs -- aqui e o efeito completo em si,
    # sem ':' separando custo/beneficio, ex: '[On Play] Trash 2 cards from
    # the top of your deck.' ou '[On K.O.] Trash 3 cards from the top of
    # your deck.'). So roda se a frase NAO tiver ':' antes do trash (senao
    # e o padrao de custo, ja tratado em parse_costs e excluido daqui para
    # nao duplicar a acao). 56 cards no banco, ~49 nesse padrao de efeito.
    m_trash_deck = re.search(r'trash (\d+) cards? from the top of (?:your|the) deck', t)
    if m_trash_deck:
        # confirma que NAO e o padrao de custo (custo tem ':' apos a clausula
        # do deck, ja consumido por parse_costs -- aqui so verifica se ha um
        # ':' explicito imediatamente seguindo esta clausula no texto cru)
        pos_fim_clausula = m_trash_deck.end()
        eh_custo = bool(re.match(r'\s*:', t[pos_fim_clausula:pos_fim_clausula+3]))
        if not eh_custo:
            steps.append({'action': 'trash_from_deck_top', 'count': int(m_trash_deck.group(1))})

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

    # Auditoria 27/06: gain_rush/gain_double_attack/gain_blocker/
    # gain_unblockable nunca expiravam (setavam has_* permanente mesmo
    # quando o texto diz "during this turn"/"during this battle"). Captura
    # a duracao numa JANELA LOCAL apos o match especifico (nao o bloco
    # inteiro -- evita pegar "during this turn" de outra clausula). Sem
    # duration no texto = grant permanente/condicional-passivo (maioria
    # dos casos, ex: "If your Leader is X, gains [Blocker]") -- esses
    # continuam indo pro has_* de sempre, NUNCA tocar.
    def _duration_apos(pos, janela=45):
        seg = t[pos:pos + janela]
        if 'during this turn' in seg:
            return 'this_turn'
        if 'during this battle' in seg:
            return 'battle_only'
        return None

    m_rc = re.search(r'gains?\s+\[rush: character\]', t)
    if m_rc or '[rush: character]' in _lista_txt:
        step = {'action': 'gain_rush_character'}
        dur = _duration_apos(m_rc.end()) if m_rc else None
        if dur:
            step['duration'] = dur
        steps.append(step)
    else:
        m_r = re.search(r'gains?\s+\[rush\]', t)
        if m_r or '[rush]' in _lista_txt:
            step = {'action': 'gain_rush'}
            dur = _duration_apos(m_r.end()) if m_r else None
            if dur:
                step['duration'] = dur
            steps.append(step)
    m_b = re.search(r'gains?\s+\[blocker\]', t)
    if m_b or '[blocker]' in _lista_txt:
        step = {'action': 'gain_blocker'}
        dur = _duration_apos(m_b.end()) if m_b else None
        if dur:
            step['duration'] = dur
        steps.append(step)
    m_da = re.search(r'gains?\s+\[double attack\]', t)
    if m_da or '[double attack]' in _lista_txt:
        step = {'action': 'gain_double_attack'}
        dur = _duration_apos(m_da.end()) if m_da else None
        if dur:
            step['duration'] = dur
        steps.append(step)
    if 'gain [banish]' in t or 'gains [banish]' in t or '[banish]' in _lista_txt:
        steps.append({'action': 'gain_banish'})
    m_u = re.search(r'gains?\s+\[unblockable\]', t)
    if m_u or '[unblockable]' in _lista_txt:
        step = {'action': 'gain_unblockable'}
        dur = _duration_apos(m_u.end()) if m_u else None
        if dur:
            step['duration'] = dur
        steps.append(step)

    # Trash from hand (efeito, nao custo)
    if trigger_name in ('on_play', 'when_attacking', 'end_of_turn'):
        m = re.search(r'trash (\d+) cards? from your hand', t)
        # NÃO duplicar: se já foi tratado pelo bloco "trash the rest ... trash
        # N card from your hand" (look_top_deck), não detectar de novo aqui.
        already = bool(re.search(r'trash the rest.*?trash \d+ card from your hand', t, re.DOTALL))
        # NÃO duplicar (2): "draw N cards and trash M cards from your hand"
        # já é capturado inteiro por parse_draw via 'then_trash' -- achado
        # em auditoria de buff_cost/debuff_cost (27/06), 59 cartas, mesma
        # familia do bug do Luffy mas gatilho diferente (aqui não tem ':'
        # de custo, é "and" ligando draw+trash no mesmo efeito).
        already_draw = bool(re.search(r'draw \d+ cards? and trash \d+ cards? from your hand', t))
        if m and not already and not already_draw:
            # Se a frase casada e seguida de ':' (so espaco entre), ela
            # PROPRIA e a declaracao de custo ("you may trash N cards from
            # your hand: efeito") -- nao duplicar como step de efeito.
            # Bug confirmado por foto real (Luffy EB04-061, 27/06): o guard
            # antigo testava 'you may trash' contra t[:t.find('trash')],
            # um slice que SEMPRE corta antes da palavra 'trash' -- nunca
            # podia conter a frase 'you may trash' completa, entao nunca
            # bloqueava a duplicacao de verdade.
            depois = t[m.end():m.end() + 3].lstrip()
            eh_custo = depois.startswith(':')
            if not eh_custo:
                steps.append({'action': 'trash_from_hand', 'count': int(m.group(1))})

    # Disrupcao de mao FORCADA no oponente -- "your opponent trashes N cards
    # from their hand". Alvo oposto de trash_from_hand (sempre 'their hand',
    # nunca 'your hand'), por isso guard textual distinto e nao precisa de
    # exclusao mutua: as duas regexes nunca casam no mesmo texto.
    if 'opponent trashes' in t or ('opponent chooses' in t and 'from your hand' in t and 'trash' in t):
        steps.extend(parse_opp_trash_from_hand(t))

    # Mesma familia (forca o oponente a mover 1 dos PROPRIOS characters
    # dele) -- "your opponent returns...to the owner's hand" / "your
    # opponent places...at the bottom of the owner's deck".
    if 'your opponent returns' in t or 'your opponent places' in t or ('your opponent chooses' in t and 'return' in t):
        steps.extend(parse_opp_self_move_character(t))

    # Trigger especial: "Activate this card's [Main] effect"
    if trigger_name == 'trigger' and 'activate this card' in t:
        return [{'action': 'activate_main_effect'}]

    # Memoria de alvo entre steps (SaveTargetName, 28/06/2026): a ordem de
    # despacho dos sub-parsers acima NAO segue a ordem do texto original
    # (ex: select_unblockable_turn e chamado antes de power_buff), o que
    # pode colocar um step target='selected' ANTES do step
    # target='select_filtered' que preenche a memoria -- a execucao
    # sequencial em decision_engine.py.execute() ficaria com a memoria
    # vazia no momento errado. Reordenacao ESTAVEL (sort) garante que quem
    # SELECIONA sempre execute antes de quem CONSOME a selecao, sem mexer
    # na ordem relativa dos demais steps.
    steps.sort(key=lambda s: 1 if s.get('target') == 'selected' else 0)

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

    # CASO ESPECIAL: "Apply each of the following effects based on [recurso]:
    # • If [condicao 1], [efeito 1]. • If [condicao 2], [efeito 2]. ..." --
    # efeitos COEXISTENTES (nao mutuamente exclusivos como 'choice': todos
    # cujos thresholds forem atingidos se aplicam ao mesmo tempo, geralmente
    # em camadas crescentes). Estrutura nova 'conditional_stack' dentro de
    # 'passive': lista de {conditions, steps}, cada item avaliado e aplicado
    # independentemente pelo engine. Carta unica confirmada no banco
    # (OP15-092) -- escopo deliberadamente minimo: NAO generaliza para
    # qualquer 'choose one' ou condicional comum, so este padrao textual
    # especifico ('apply each of the following effects').
    if 'apply each of the following effects' in t_low:
        recurso_m = re.search(r'based on the number of cards in your (\w+)', t_low)
        recurso = recurso_m.group(1) if recurso_m else None
        opcoes_raw = re.split(r'[•\u2022]', t)
        opcoes_raw = [o.strip() for o in opcoes_raw[1:] if o.strip()]
        stack = []
        for opcao_texto in opcoes_raw:
            opcao_low = opcao_texto.lower()
            # Normaliza "if there are/you have N or more cards" -> insere o
            # recurso (ex: "in your trash") explicitamente, ja que cada
            # bullet individual costuma omiti-lo (definido so na frase-mae
            # "based on the number of cards in your trash"). Sem isto,
            # parse_conditions nunca reconhece a condicao de cada bullet.
            if recurso and 'in your' not in opcao_low.split('or more')[0][-20:]:
                opcao_low = re.sub(
                    r'(if (?:there are|you have) \d+ or more cards?)',
                    r'\1 in your ' + recurso,
                    opcao_low, count=1
                )
            sub_conds = parse_conditions(opcao_low)
            sub_steps = parse_block(opcao_low, 'passive')
            if sub_steps and not (len(sub_steps) == 1 and '_choice' in sub_steps[0]):
                item = {'steps': sub_steps}
                if sub_conds:
                    item['conditions'] = sub_conds
                stack.append(item)
        if stack:
            return {'passive': {'conditional_stack': stack}}
        # se nada foi parseado com sucesso, cai no fluxo normal abaixo (nao
        # finge uma estrutura vazia)

    # Mapa de triggers → regex para extrair o bloco de texto
    # Lista de TODAS as tags de trigger possiveis no texto cru (case-insensitive),
    # usada simetricamente em todo lookahead de parada -- antes cada padrao so
    # parava em um subconjunto proprio, causando vazamento entre blocos (ex:
    # [Your Turn] vazava pra dentro de [Opponent's Turn] porque a lista de
    # parada do your_turn nao incluia opponent's turn).
    TODAS_TAGS = r"on play|activate:?\s*main|when attacking|on your opponent.{0,3}s? attack|on k\.o\.|your turn|opponent.{0,3}s? turn|trigger|counter|end of your turn|on block|main|blocker|rush|double attack|banish|unblockable"

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
        ('on_opp_attack', ABERTURA + r"\[on your opponent.{0,3}s? attack\](.+?)" + LOOKAHEAD_DELIM),
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
        "on your opponent's attack": 'on_opp_attack',
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

        is_choice = len(steps) == 1 and '_choice' in steps[0]
        is_substitute = (not is_choice and len(steps) == 1
                          and steps[0].get('action') in ('substitute_ko', 'substitute_removal'))

        conds = parse_conditions(block)
        costs = [] if is_substitute else parse_costs(block)
        once = '[once per turn]' in t_low

        # "Then, if [cond]" scope leakage: se o bloco tem o padrao "[A
        # incondicional]. Then, if [cond], [B]", a condicao extraida de
        # block inteiro (linha acima) contaminaria TAMBEM os steps de A.
        # Reparseia A e B separadamente e anexa a condicao SO aos steps de
        # B (campo 'conditions' por-step, novo -- engine checa em
        # _execute_step antes de cada step individual, alem da condicao
        # global do entry). Nao se aplica a is_choice/is_substitute (blocos
        # de estrutura especial que reivindicam o texto inteiro).
        if not is_choice and not is_substitute:
            parte_a, parte_b = split_then_if(block)
            if parte_b is not None:
                steps_a = parse_block(parte_a, trigger_name)
                steps_b = parse_block(parte_b, trigger_name)
                cond_a = parse_conditions(parte_a)
                cond_b = parse_conditions(parte_b)
                # so reaproveita o split se AMBAS as partes produziram pelo
                # menos 1 step reconhecido e a condicao de B foi capturada
                # -- caso contrario o split perderia cobertura (ex: parte_a
                # ou parte_b com construcao nao suportada ainda pelo
                # parser) e e mais seguro manter o comportamento antigo
                # (conds no bloco inteiro) do que descartar steps validos.
                if steps_a and steps_b and cond_b:
                    for s in steps_b:
                        s['conditions'] = cond_b
                    # parte_a pode ter SUA PROPRIA condicao independente
                    # (ex: OP09-019 'If Leader e Red-Haired, efeito A. Then,
                    # if opp tem char 5000+, efeito B' -- 2 condicoes
                    # distintas, uma por efeito). So anexa a steps_a se
                    # cond_a != cond_b (evita duplicar a mesma condicao nos
                    # dois lados quando o split partiu uma condicao unica
                    # que parse_conditions(parte_a) capturou por reflexo).
                    if cond_a and cond_a != cond_b:
                        for s in steps_a:
                            s['conditions'] = cond_a
                    steps = steps_a + steps_b
                    # a condicao global do entry deixa de existir -- ela
                    # agora vive nos steps individuais (de A e/ou B).
                    conds = {}

        # DON x requisito antes do trigger. Usa a posição real do match (m.start)
        # em vez de reconstruir o nome — assim funciona para [Activate: Main],
        # [On K.O.], etc., onde o nome tem pontuação/variações.
        don_req = 0
        trigger_pos = m.start()
        pre_trigger = t_low[:trigger_pos]
        don_m = re.search(r'\[don!! x(\d+)\]', pre_trigger[-50:])
        if don_m:
            don_req = int(don_m.group(1))

        if is_choice:
            entry = {'choice': steps[0]['_choice']}
            if steps[0].get('_choice_chooser'):
                entry['choice_chooser'] = steps[0]['_choice_chooser']
        else:
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

    # Tags ADJACENTES COLADAS sem barra, ex: "[Opponent's Turn] [On K.O.]
    # efeito" -- diferente do caso "[A]/[B]" (que SAO dois triggers
    # distintos de propósito, mesmo efeito). Aqui e UMA UNICA condicao
    # composta ("durante o turno do oponente, quando K.O.") que cada regex
    # de trigger_patterns casa e preenche separadamente, pois elas operam
    # de forma independente na mesma string -- resultado: result['on_ko']
    # e result['opp_turn'] ficam com STEPS IDENTICOS, e o engine executaria
    # o mesmo efeito 2x. Confirmado em 6 cartas (EB03-042, OP12-107,
    # OP12-119, OP14-115, OP16-103, P-090), sempre no padrao
    # "[Opponent's Turn] [On K.O.]". Colapsa em 'on_ko' (mais especifico --
    # toda ocorrencia de K.O. neste padrao ja e composta com opp_turn) e
    # remove a entrada redundante de 'opp_turn', preservando a restricao
    # de turno como 'conditions.opp_turn_only' para o engine checar.
    if ('on_ko' in result and 'opp_turn' in result
            and result['on_ko'].get('steps') == result['opp_turn'].get('steps')):
        if re.search(r"\[opponent.{0,3}s? turn\]\s*\[on k\.o\.\]", t_low):
            result['on_ko'].setdefault('conditions', {})['opp_turn_only'] = True
            del result['opp_turn']

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
                # Separa qualquer step 'cannot_attack_own_characters_by_cost'
                # (carrega sua PROPRIA condicao, ex: P-084 'if your Leader is
                # Buggy') do resto do passive incondicional -- sem isto,
                # parse_conditions(segmento_solto) aplicaria a condicao do
                # mass-lock tambem ao cannot_attack_self incondicional do
                # mesmo bloco. Trigger novo 'mass_lock_conditional', so para
                # esse padrao raro (carta unica confirmada).
                mass_lock_steps = [s for s in solto_steps if s.get('action') == 'cannot_attack_own_characters_by_cost']
                solto_steps = [s for s in solto_steps if s.get('action') != 'cannot_attack_own_characters_by_cost']
                if mass_lock_steps and 'mass_lock_conditional' not in result:
                    result['mass_lock_conditional'] = {
                        'steps': [{'action': s['action'], 'costs': s['costs']} for s in mass_lock_steps],
                        'conditions': mass_lock_steps[0].get('conditions', {}),
                    }
                    # remove a sentenca do mass-lock do texto usado para
                    # extrair conditions do passive restante -- senao
                    # parse_conditions(segmento_solto) reencontraria 'if your
                    # leader is buggy' e contaminaria o cannot_attack_self
                    # incondicional com a mesma condicao do efeito separado.
                    segmento_solto = re.sub(
                        r'if your leader is \[[^\]]+\][^.]*?cannot attack\.?',
                        '', segmento_solto
                    ).strip()

                # 'cannot_attack_self_unless' tambem carrega SUA PROPRIA
                # 'conditions' (quando reconhecida por parse_conditions, ver
                # acima) -- remove a clausula "cannot attack unless [cond]"
                # do texto usado para extrair conditions do passive
                # restante, senao parse_conditions(segmento_solto)
                # reencontraria a mesma condicao e duplicaria no nivel do
                # entry (inofensivo enquanto o passive tiver so esse step,
                # mas viraria scope leakage real se outro step incondicional
                # for adicionado ao mesmo bloco no futuro).
                unless_steps = [s for s in solto_steps if s.get('action') == 'cannot_attack_self_unless' and 'conditions' in s]
                if unless_steps:
                    segmento_solto = re.sub(
                        r'this character cannot attack unless [^.]+\.?',
                        '', segmento_solto, flags=re.IGNORECASE
                    ).strip()

            if solto_steps:
                is_sub_solto = len(solto_steps) == 1 and solto_steps[0].get('action') in ('substitute_ko', 'substitute_removal')
                solto_entry = {'steps': solto_steps}
                solto_conds = parse_conditions(segmento_solto)
                solto_costs = [] if is_sub_solto else parse_costs(segmento_solto)

                # mesmo split de "Then, if"/"If" do loop principal -- o
                # segmento solto e texto livre (sem tag formal), igualmente
                # sujeito a scope leakage quando tem "[A]. If [cond], [B]".
                if not is_sub_solto:
                    parte_a_s, parte_b_s = split_then_if(segmento_solto)
                    if parte_b_s is not None:
                        steps_a_s = parse_block(parte_a_s, 'passive')
                        steps_b_s = parse_block(parte_b_s, 'passive')
                        cond_b_s = parse_conditions(parte_b_s)
                        if steps_a_s and steps_b_s and cond_b_s:
                            for s in steps_b_s:
                                s['conditions'] = cond_b_s
                            solto_steps = steps_a_s + steps_b_s
                            solto_entry['steps'] = solto_steps
                            solto_conds = {}

                if solto_conds:
                    solto_entry['conditions'] = solto_conds
                if solto_costs:
                    solto_entry['costs'] = solto_costs
                if '[once per turn]' in segmento_solto:
                    solto_entry['once_per_turn'] = True
                # mesma logica do fallback abaixo: [DON!! xN] no INICIO do
                # segmento solto tambem condiciona o efeito (ex: OP09-061
                # '[DON!! x1] All of your Characters gain +1 cost' antes de
                # um [Your Turn] formal -- sem isto, o segmento solto nunca
                # recebia don_requirement por ter um trigger formal depois).
                don_solto_m = re.match(r'^\[don!! x(\d+)\]', segmento_solto, re.IGNORECASE)
                if don_solto_m:
                    solto_entry['don_requirement'] = int(don_solto_m.group(1))
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

                # mesma logica usada no segmento_solto: 'cannot_attack_self_unless'
                # ja carrega sua PROPRIA 'conditions' (quando reconhecida) --
                # remove a clausula antes de extrair parse_conditions(t_low)
                # do bloco inteiro, senao a mesma condicao duplicaria no
                # nivel do entry (ex: EB04-005, fallback sem tag formal).
                t_low_para_conds = t_low
                unless_steps_fb = [s for s in fallback_steps if s.get('action') == 'cannot_attack_self_unless' and 'conditions' in s]
                if unless_steps_fb:
                    t_low_para_conds = re.sub(
                        r'this character cannot attack unless [^.]+\.?',
                        '', t_low_para_conds, flags=re.IGNORECASE
                    ).strip()

                conds = parse_conditions(t_low_para_conds)
                costs = [] if is_substitute_fb else parse_costs(t_low)

                # mesmo split de "Then, if"/"If" usado no loop de tags
                # formais acima -- sem tag formal o texto inteiro cai aqui,
                # e o mesmo risco de scope leakage se aplica (ex: ST14-001
                # '[DON!! x1] All Characters gain +1 cost. If cost>=8,
                # Leader gains +1000 power' -- a condicao so deveria valer
                # pro buff_power, nao pro buff_cost).
                if not is_substitute_fb:
                    parte_a_fb, parte_b_fb = split_then_if(t_low_para_conds)
                    if parte_b_fb is not None:
                        steps_a_fb = parse_block(parte_a_fb, 'passive')
                        steps_b_fb = parse_block(parte_b_fb, 'passive')
                        cond_b_fb = parse_conditions(parte_b_fb)
                        if steps_a_fb and steps_b_fb and cond_b_fb:
                            for s in steps_b_fb:
                                s['conditions'] = cond_b_fb
                            fallback_steps = steps_a_fb + steps_b_fb
                            entry['steps'] = fallback_steps
                            conds = {}

                if conds:
                    entry['conditions'] = conds
                if costs:
                    entry['costs'] = costs
                if '[once per turn]' in t_low:
                    entry['once_per_turn'] = True
                # [DON!! xN] no INICIO do texto (antes de 'this character
                # gains...') tambem e condicao de DON anexado para actions
                # genericas (buff_power/buff_cost), nao so para keywords --
                # keyword_don_req (abaixo) so cobre 'gains [keyword]', nao
                # 'gains +N power/cost'. Ex: OP08-093 X.Drake '[DON!! x1]
                # This Character gains +2 cost' so deveria valer +2 cost
                # enquanto a carta tem 1 DON!! anexado, nao permanentemente.
                don_fb_m = re.match(r'^\[don!! x(\d+)\]', t_low.strip(), re.IGNORECASE)
                if don_fb_m:
                    entry['don_requirement'] = int(don_fb_m.group(1))
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
