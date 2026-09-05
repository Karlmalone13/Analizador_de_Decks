"""
tribal_cohesion.py
==================
Eixo SEPARADO do arquétipo: mede o quão focado um deck é no TIPO do seu líder.

Não diz se o deck é aggro ou controle — diz quão COESO/tribal ele é:
  - Coesão alta: líder de tipo T, muitas cartas do tipo T, e cartas que
    recompensam controlar/ter líder T ("if your leader has the {T} type").
  - Coesão baixa: deck "good-stuff" (cartas boas avulsas, tipos variados,
    poucos ganchos tribais).

Dois ganchos cobertos:
  - "if your leader has the {T} type"  (comum, ~513 cartas)
  - "if you control a {T}"             (raro, ~37 cartas)
"""
import re


def _leader_type_string(leader_card: dict) -> str:
    """Sub_types do líder como string única em minúsculas (para substring match)."""
    return (leader_card.get('sub_types') or '').lower().strip()


# Tipos conhecidos do jogo, para detectar quais estão presentes no líder
# (sub_types vêm colados por espaço, ex: 'Straw Hat Crew Sky Island').
KNOWN_TYPES = [
    'straw hat crew', 'navy', 'whitebeard pirates', 'big mom pirates',
    'land of wano', 'revolutionary army', 'donquixote pirates',
    'animal kingdom pirates', 'sky island', 'east blue', 'baroque works',
    'kuja pirates', 'blackbeard pirates', 'red-haired pirates', 'impel down',
    'seven warlords of the sea', 'the four emperors', 'fish-man', 'minks',
    'dressrosa', 'arlong pirates', 'krieg pirates', 'buggy pirates',
    'germa 66', 'cross guild', 'supernovas', 'egghead', 'bonney pirates',
]


def _leader_types(leader_card: dict) -> set:
    """Tipos do líder, detectados por presença na string de sub_types."""
    s = _leader_type_string(leader_card)
    found = {t for t in KNOWN_TYPES if t in s}
    return found


def _card_has_tribal_hook(card_text: str, leader_types: set,
                           referenced_types: list | None = None) -> bool:
    """A carta recompensa o tipo do líder?

    Fonte PRIMÁRIA: `referenced_types`, os tipos que o PARSER já extraiu dos
    efeitos (`filter_type`, `leader_type`, `only_field_type`...). Achado
    05/09: a versão anterior só tinha os regexes abaixo e reconhecia apenas
    as formas "if your leader has X"/"if you control X" -- perdia as cartas
    que BUSCAM o tipo ("reveal up to 1 {East Blue} type card"), que são das
    mais tribais que existem. Num deck East Blue real: 17 cópias citavam o
    tipo e só 9 eram contadas, o que derrubava a coesão de ~78% pra 50,8% e
    rotulava um deck 100% do tipo como "moderadamente focado".

    Os regexes ficam como REDE DE SEGURANÇA para gancho que exista no texto
    mas o parser ainda não estruture -- nunca como fonte única.
    """
    if not leader_types:
        return False

    for lt in leader_types:
        if lt and any(lt in (rt or '') for rt in (referenced_types or [])):
            return True

    t = (card_text or '').lower()
    for lt in leader_types:
        if not lt:
            continue
        if re.search(rf"if your leader (has|is|'?s type includes).{{0,15}}{re.escape(lt)}", t):
            return True
        if re.search(rf"if you (have|control).{{0,20}}{re.escape(lt)}", t):
            return True
        if re.search(rf"your .{{0,5}}{re.escape(lt)}.{{0,15}}characters?", t):
            return True
    return False


def compute_tribal_cohesion(leader_card: dict, main_cards: list) -> dict:
    """
    Retorna a coesão tribal do deck:
      {
        'leader_type': tipo principal do líder,
        'same_type_pct': % de cartas do mesmo tipo do líder,
        'hook_count': nº de cartas com gancho tribal,
        'cohesion_pct': pontuação geral de coesão (0-100),
        'label': descrição,
      }
    """
    leader_types = _leader_types(leader_card)
    if not leader_types or not main_cards:
        return {
            'leader_type': None, 'same_type_pct': 0, 'hook_count': 0,
            'cohesion_pct': 0, 'label': 'sem dados de tipo',
        }

    n = len(main_cards)
    same_type = 0
    hooks = 0
    for card in main_cards:
        ctype_str = (card.get('sub_types', '') or '').lower()
        if any(lt in ctype_str for lt in leader_types):
            same_type += 1
        if _card_has_tribal_hook(card.get('text', ''), leader_types,
                                  card.get('referenced_types')):
            hooks += 1

    same_type_pct = round(100 * same_type / n, 1)
    hook_pct = round(100 * hooks / n, 1)

    # Coesão = média ponderada: concentração de tipo (peso 2) + ganchos (peso 1).
    # Ganchos valem como "o deck ATIVAMENTE recompensa o tipo", não só o contém.
    #
    # O peso do gancho era 3 (nunca 1, apesar deste comentário sempre dizer 1 --
    # código e documentação divergiam). Com peso 3 a escala ficava impossível:
    # um deck com 100% das cartas do tipo do líder só passaria de 70 ("altamente
    # focado") se METADE das cartas tivesse gancho explícito, o que nenhum deck
    # real tem. Resultado prático: deck 100% East Blue era rotulado
    # "moderadamente focado" (50,8%). Alinhado ao 2:1 documentado em 05/09.
    cohesion = round((same_type_pct * 2 + hook_pct * 1) / 3, 1)
    cohesion = min(cohesion, 100.0)

    main_type = sorted(leader_types)[0].title()
    if cohesion >= 70:
        label = f'Deck altamente focado em {main_type} (tribal)'
    elif cohesion >= 40:
        label = f'Deck moderadamente focado em {main_type}'
    else:
        label = f'Deck good-stuff (pouca dependência de tipo)'

    return {
        'leader_type': main_type,
        'same_type_pct': same_type_pct,
        'hook_count': hooks,
        'cohesion_pct': cohesion,
        'label': label,
    }