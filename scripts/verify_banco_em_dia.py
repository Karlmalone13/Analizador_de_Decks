"""Guarda contra o modo de falha SILENCIOSO do banco de efeitos.

Achado 24/09/2026 (bloco 887): o commit 15dc604 alterou `gerar_effects_db.py`
(custo `or_rest_opp_don`) e `card_effects_db.json` **nunca foi regerado** para
OP06-035 e OP12-037. O parser tinha o conserto e o motor nao via -- fix pela
metade, no repo, por dias, sem nenhum sinal.

Nada detectava isso: `diff_parser.py` compara o parser contra o SNAPSHOT (os
dois derivados do mesmo codigo), nunca contra o banco que o motor le de
verdade. E o proprio snapshot pode ser regerado junto, mascarando tudo.

Este script fecha o buraco: regera o banco EM MEMORIA e compara com o JSON
versionado. Se divergirem, alguem mexeu no parser e esqueceu `gerar_dbs.py`.
"""
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(RAIZ, 'scriptis_da_ia')
VIGIADOS = ('scriptis_da_ia/gerar_effects_db.py',
            'scriptis_da_ia/cards_rows.csv',
            'scriptis_da_ia/card_effects_db.json')


def _staged():
    try:
        out = subprocess.run(['git', 'diff', '--cached', '--name-only'],
                             cwd=RAIZ, capture_output=True, text=True, check=True)
    except Exception:
        return []
    return [l.strip().replace(chr(92), '/') for l in out.stdout.splitlines() if l.strip()]


def main():
    if not any(v in _staged() for v in VIGIADOS):
        return 0

    sys.path.insert(0, SCRIPTS)
    try:
        from gerar_effects_db import generate_effects_db
    except Exception as exc:
        print(f'[banco-em-dia] nao foi possivel importar o gerador: {exc}')
        return 0   # nao e o trabalho deste gate derrubar commit por import

    csv = os.path.join(SCRIPTS, 'cards_rows.csv')
    alvo = os.path.join(SCRIPTS, 'card_effects_db.json')
    try:
        gerado = generate_effects_db(csv)
        with open(alvo, encoding='utf-8') as f:
            versionado = json.load(f)
    except Exception as exc:
        print(f'[banco-em-dia] nao foi possivel comparar: {exc}')
        return 0

    # Os aliases do simulador sao adicionados por gerar_dbs.py DEPOIS do
    # gerador, entao codigos que so existem no JSON nao sao divergencia.
    divergentes = sorted(
        c for c in gerado
        if c in versionado and gerado[c].get('effects') != versionado[c].get('effects')
    )
    if not divergentes:
        return 0

    print('==============================================================')
    print(' BANCO DE EFEITOS DESATUALIZADO em relacao ao parser')
    print('==============================================================')
    print(f'{len(divergentes)} carta(s) parseiam diferente do que esta em')
    print('card_effects_db.json. O parser foi alterado e o banco nao foi')
    print('regerado -- o motor continuaria lendo a versao antiga.')
    print('')
    for c in divergentes[:20]:
        print(f'  {c}')
    if len(divergentes) > 20:
        print(f'  ... e mais {len(divergentes) - 20}')
    print('')
    print('Rode:  cd scriptis_da_ia && python gerar_dbs.py')
    print('e adicione os bancos ao commit.')
    print('==============================================================')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
