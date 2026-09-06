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
    Retorna a coesão tribal do deck em DOIS eixos independentes:
      {
        'leader_type': tipo principal do líder,
        'same_type_pct': % de cartas do mesmo tipo do líder,
        'hook_count': nº de cartas com gancho tribal,
        'hook_pct': % de cartas com gancho tribal,
        'label': leitura qualitativa dos dois eixos juntos,
      }

    NAO existe mais um `cohesion_pct` unico (removido 06/09). Ele misturava
    concentracao de tipo com quantidade de ganchos numa media ponderada, e o
    resultado nao significava nada verificavel: um deck 100% East Blue com
    34% de ganchos aparecia como "78%" logo abaixo da frase "100% das cartas
    sao East Blue" -- contradicao na cara do usuario, que foi quem reclamou.
    Pior: o peso era arbitrario (mudou de 3 pra 1 no mesmo dia sem nenhum
    criterio empirico), entao qualquer valor unico so ia empurrar o erro pra
    outro deck. Os dois eixos medem coisas diferentes e ficam separados.
    """
    leader_types = _leader_types(leader_card)
    if not leader_types or not main_cards:
        return {
            'leader_type': None, 'same_type_pct': 0, 'hook_count': 0,
            'hook_pct': 0, 'label': 'sem dados de tipo',
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

    # Rótulo lido dos DOIS eixos, sem misturá-los num score. Os cortes saem
    # da distribuição REAL dos 184 decks de torneio em `decklists_raw.csv`
    # (medido 06/09), não de chute:
    #   concentração de tipo -> p25=56  mediana=70  p75=94   (corte: 70)
    #   ganchos              -> p25=8   mediana=28  p75=36   (corte: 25)
    # Com esses cortes: 83 decks "tribal de verdade", 10 "good-stuff
    # mono-tipo", 91 "pouca dependência" -- discrimina de verdade, e é
    # exatamente a distinção que este módulo existe pra fazer (ver README).
    CORTE_TIPO = 70.0
    CORTE_GANCHO = 25.0

    main_type = sorted(leader_types)[0].title()
    if same_type_pct >= CORTE_TIPO and hook_pct >= CORTE_GANCHO:
        label = f'Tribal de verdade — o deck é {main_type} e explora o tipo'
    elif same_type_pct >= CORTE_TIPO:
        label = f'Good-stuff mono-tipo — é quase todo {main_type}, mas poucas cartas exploram isso'
    else:
        label = 'Pouca dependência de tipo'

    return {
        'leader_type': main_type,
        'same_type_pct': same_type_pct,
        'hook_count': hooks,
        'hook_pct': hook_pct,
        'label': label,
    }