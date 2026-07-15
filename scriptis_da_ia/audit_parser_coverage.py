"""
audit_parser_coverage.py
=========================
Varredura AMPLA (não carta a carta) do banco inteiro procurando o mesmo
tipo de bug achado manualmente em Krieg (OP15-001) e Kid (OP10-099) em
14/07: um NÚMERO que aparece no texto real da carta (limiar, intervalo,
contagem) e não aparece em lugar nenhum do que o parser entendeu.

Por quê esse jeito (e não uma lista de padrões conhecidos): o usuário
pediu a varredura mas não lembra de cabeça todos os tipos de condição que
podem estar mal parseados -- "intervalo N a M" e "N+ DON anexado" foram só
os 2 que a gente JÁ achou por acaso. Uma lista de regex por padrão
conhecido só pegaria bugs que a gente já sabe procurar. Este script usa um
critério GENÉRICO que independe de nomear o padrão: compara o CONJUNTO de
números do texto cru com o CONJUNTO de números que aparecem em qualquer
lugar do JSON parseado daquela carta. Número sobrando no texto = candidato
a "perdido pelo parser".

Isso teria pego os 2 bugs de 14/07 sem eu ter pensado neles antes:
  - Krieg: texto tem "2" ("2 or more DON!! cards given"), JSON antigo só
    tinha {'cost_lte': 99} -- o 2 não aparecia em lugar nenhum -> flag.
  - Kid: texto tem "8" ("cost of 3 to 8"), JSON antigo só tinha
    {'cost_eq': 3} -- o 8 não aparecia em lugar nenhum -> flag.

Não é prova de bug (às vezes um número é redundante, faz parte de nome de
carta, ou é coberto por lógica fora do step tipo `costs`) -- é uma lista
de SUSPEITOS pra revisão humana, ordenada por quantas cópias/decks reais
usam a carta (prioriza o que afeta partida de verdade).

Uso:
  python audit_parser_coverage.py                 # varre tudo, resumo
  python audit_parser_coverage.py --show 40        # lista os 40 primeiros
  python audit_parser_coverage.py --code OP15-001  # 1 carta só, detalhado
  python audit_parser_coverage.py --min-severity 2 # só numeros perdidos >=2
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_CSV_PATH = Path(__file__).parent / 'cards_rows.csv'
_EFFECTS_DB_PATH = Path(__file__).parent / 'card_effects_db.json'
_DECKS_DIR = Path(r"E:\Games\OnePieceSimulador\Builds_Windows\Decks")

# Sufixos de reprint/parallel/alt-art -- textos idênticos entre eles na
# grande maioria dos casos, reportar 1x por texto único evita triplicar
# o relatório (achado ao rodar a 1a versão: OP15-001 e OP15-001_p1 sempre
# aparecem juntos com o mesmo bug).
_REPRINT_SUFFIX = re.compile(r'_(p|r)\d+$')

# Números "colados" em letra (ex: "x1" do [DON!! x1], "OP15" de código de
# carta) não contam -- ruído, não são limiares/contagens do efeito.
_NUM_RE = re.compile(r'(?<![a-zA-Z0-9])\d+(?![a-zA-Z0-9])')


def _base_code(code: str) -> str:
    return _REPRINT_SUFFIX.sub('', code)


def _load_raw_texts() -> dict[str, str]:
    out = {}
    with open(_CSV_PATH, encoding='utf-8') as f:
        for row in csv.reader(f):
            if not row:
                continue
            code = row[0]
            text = row[5] if len(row) > 5 else ''
            out[code] = text
    return out


def _load_effects() -> dict:
    return json.loads(_EFFECTS_DB_PATH.read_text(encoding='utf-8'))


def _numbers_in_text(text: str) -> set[str]:
    # Remove texto de lembrete entre parenteses -- normalmente reafirma
    # regra genérica de palavra-chave (ex: "(You may return the specified
    # number of DON!! cards...)"), raramente introduz limiar NOVO da carta,
    # e é uma fonte grande de ruído.
    sem_parenteses = re.sub(r'\([^)]*\)', ' ', text)
    return set(_NUM_RE.findall(sem_parenteses))


def _numbers_in_json(obj) -> set[str]:
    nums = set()
    if isinstance(obj, dict):
        for v in obj.values():
            nums |= _numbers_in_json(v)
    elif isinstance(obj, list):
        for v in obj:
            nums |= _numbers_in_json(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        nums.add(str(int(obj)))
    elif isinstance(obj, str):
        # valores tipo "east blue" não tem número, mas alguns campos guardam
        # limiar como string dentro de 'condition' textual (ex: inversion
        # axis) -- extrai números de dentro de strings tambem.
        nums |= set(_NUM_RE.findall(obj))
    return nums


def _deck_usage_counts() -> Counter:
    """Quantos decks reais (arquivo .deck) usam cada código -- prioriza
    revisão pelo que aparece em partida de verdade, não card obscuro."""
    counts = Counter()
    if not _DECKS_DIR.exists():
        return counts
    for deck_path in _DECKS_DIR.glob('*.deck'):
        for line in deck_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or 'x' not in line:
                continue
            _, code = line.split('x', 1)
            counts[code] += 1
    return counts


def scan() -> list[dict]:
    raw = _load_raw_texts()
    effects = _load_effects()
    deck_usage = _deck_usage_counts()

    vistos_por_texto: dict[str, str] = {}   # texto -> code representante
    resultados = []

    for code, eff in effects.items():
        text = raw.get(code, '')
        if not text.strip():
            continue
        base = _base_code(code)
        # dedupe: reprints com texto IDENTICO ao já visto -> pula, mas
        # acumula uso de deck no representante.
        chave_dedupe = text
        if chave_dedupe in vistos_por_texto:
            continue
        vistos_por_texto[chave_dedupe] = code

        texto_nums = _numbers_in_text(text)
        json_nums = _numbers_in_json(eff.get('effects', eff))
        perdidos = sorted(texto_nums - json_nums, key=int)
        if not perdidos:
            continue

        usos = deck_usage.get(base, 0) + sum(
            v for k, v in deck_usage.items() if _base_code(k) == base and k != base)
        resultados.append({
            'code': code,
            'name': eff.get('name', ''),
            'text': text,
            'perdidos': perdidos,
            'usos_em_decks': usos,
        })

    resultados.sort(key=lambda r: (-r['usos_em_decks'], -len(r['perdidos'])))
    return resultados


def print_report(resultados: list[dict], show: int, min_sev: int) -> None:
    filtrados = [r for r in resultados if len(r['perdidos']) >= min_sev]
    print(f"Total de cartas com texto: varredura completa do banco.")
    print(f"Cartas com numero(s) do texto ausente(s) no JSON parseado: {len(resultados)}")
    if min_sev > 1:
        print(f"  (filtrado pra severidade >= {min_sev}: {len(filtrados)})")
    print()
    print(f"Mostrando os primeiros {min(show, len(filtrados))} "
          f"(ordenados por uso em decks reais, depois por qtd de numeros perdidos):")
    print()
    for r in filtrados[:show]:
        tag_uso = f"[{r['usos_em_decks']}x em decks reais]" if r['usos_em_decks'] else "[nao usado em deck salvo]"
        print(f"{'='*78}")
        print(f"{r['code']} - {r['name']}  {tag_uso}")
        print(f"  numeros no texto sem match no parsed: {r['perdidos']}")
        print(f"  texto: {r['text'][:220]}")
        print()


def detail_one(code: str) -> None:
    raw = _load_raw_texts()
    effects = _load_effects()
    eff = effects.get(code)
    if eff is None:
        print(f"Codigo {code} nao encontrado em card_effects_db.json")
        return
    text = raw.get(code, '')
    texto_nums = _numbers_in_text(text)
    json_nums = _numbers_in_json(eff.get('effects', eff))
    print(f"{code} - {eff.get('name','')}")
    print(f"\nTexto cru:\n  {text}")
    print(f"\nEfeitos parseados:\n  {json.dumps(eff.get('effects', eff), ensure_ascii=False, indent=2)}")
    print(f"\nNumeros no texto:    {sorted(texto_nums, key=int)}")
    print(f"Numeros no parseado: {sorted(json_nums, key=int)}")
    perdidos = sorted(texto_nums - json_nums, key=int)
    print(f"Perdidos (suspeitos): {perdidos if perdidos else '(nenhum -- parece OK)'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', help='detalha 1 carta so')
    ap.add_argument('--show', type=int, default=40, help='quantas mostrar no resumo')
    ap.add_argument('--min-severity', type=int, default=1,
                     help='so mostra cartas com >= N numeros perdidos')
    args = ap.parse_args()

    if args.code:
        detail_one(args.code)
        return

    resultados = scan()
    print_report(resultados, args.show, args.min_severity)


if __name__ == '__main__':
    main()
