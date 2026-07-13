"""
crosscheck_archetypes.py — QA da gramática: perfil derivado vs rótulo do PDF
============================================================================
Roda o deck_profile em cada deck crawleado e compara o arquétipo/papéis
DERIVADOS das mecânicas com o rótulo humano do catálogo do PDF
(IA_Compendium/ONE_PIECE_AI_COMPENDIUM_Volume_1.pdf). Cada deck que "lê
certo" valida a gramática; cada divergência forte expõe um buraco (lição
"perfil vazio/errado = alerta de gramática", nunca hardcode pontual).

NÃO usa nome de carta; NÃO decide jogada. Só QA. Leve (não simula).

Uso: python crosscheck_archetypes.py
"""
from __future__ import annotations
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# determinístico (set iteration order estável) — prova de neutralidade limpa
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    raise SystemExit(subprocess.call([sys.executable] + sys.argv))

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / 'scriptis_da_ia'))
from deck_profile import build_profile_from_codes  # noqa: E402


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def load_pdf_catalog() -> dict[str, str]:
    """{nome-normalizado do líder -> rótulo de arquétipo do PDF}."""
    try:
        from pypdf import PdfReader
    except Exception:
        return {}
    pdf = HERE.parent / 'IA_Compendium' / 'ONE_PIECE_AI_COMPENDIUM_Volume_1.pdf'
    if not pdf.exists():
        return {}
    full = ''
    for p in PdfReader(str(pdf)).pages:
        full += (p.extract_text() or '') + '\n'
    # "12. Monkey.D.Luffy - Amarelo\nArquétipo preliminar: Life/Combo."
    cat = {}
    for m in re.finditer(r'\d+\.\s*([A-Za-z.\'\" ]+?)\s*-\s*[A-Za-zç/]+\s*'
                         r'Arqu[eé]tipo preliminar:\s*([^.]+)\.', full):
        cat[_norm(m.group(1))] = m.group(2).strip()
    return cat


def deck_codes(parsed: dict) -> list[str]:
    out = []
    for d in parsed.get('decklist', []):
        out += [d['code']] * d['qty']
    return out


def main():
    catalog = load_pdf_catalog()
    print(f'[qa] catálogo do PDF: {len(catalog)} líderes rotulados\n')
    rows = []
    for jf in sorted(glob.glob(str(HERE / 'data' / 'parsed' / 'deck_*.json'))):
        d = json.load(open(jf, encoding='utf-8'))
        if d['total_cards'] < 40:      # guias parciais, pouco confiáveis
            continue
        codes = deck_codes(d)
        if not codes:
            continue
        prof = build_profile_from_codes(codes)
        arch = prof['archetype']
        top_roles = list(prof['roles'].items())[:4]
        pdf_label = catalog.get(_norm(d['leader']['name']), '—')
        rows.append({
            'name': d['leader']['name'], 'colors': '/'.join(d['leader']['colors']),
            'pdf': pdf_label, 'arch': arch['dominante'],
            'mix': arch['mix'],
            'axes': [a['id'].replace('_staircase', '').replace('_bottleneck', '')
                     for a in prof['derived_axes']],
            'roles': [r for r, _ in top_roles],
        })

    print(f'{"LÍDER":24s} {"CORES":7s} {"PDF (humano)":22s} {"DERIVADO":13s}  EIXOS / PAPÉIS')
    print('-' * 120)
    for r in rows:
        print(f'{r["name"][:24]:24s} {r["colors"][:7]:7s} {r["pdf"][:22]:22s} '
              f'{r["arch"][:13]:13s}  {",".join(r["axes"])[:34]:34s} | {",".join(r["roles"])}')
    print(f'\n{len(rows)} decks perfilados. Divergência PDF↔derivado = candidato a '
          f'buraco de gramática (investigar, nunca hardcode).')


if __name__ == '__main__':
    main()
