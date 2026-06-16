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


def _card_has_tribal_hook(card_text: str, leader_types: set) -> bool:
    """A carta recompensa o tipo do líder? (líder-é-tipo OU controla-tipo)."""
    t = (card_text or '').lower()
    if not leader_types:
        return False
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
        if _card_has_tribal_hook(card.get('text', ''), leader_types):
            hooks += 1

    same_type_pct = round(100 * same_type / n, 1)
    hook_pct = round(100 * hooks / n, 1)

    # Coesão = média ponderada: concentração de tipo (peso 2) + ganchos (peso 1).
    # Ganchos valem como "o deck ATIVAMENTE recompensa o tipo", não só o contém.
    cohesion = round((same_type_pct * 2 + hook_pct * 3) / 5, 1)
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