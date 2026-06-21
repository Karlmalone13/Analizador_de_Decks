"""
gerar_dbs.py
============
Gera os DOIS bancos (effects + analysis) numa execução só, da mesma fonte.
Única porta de geração — os geradores individuais estão bloqueados.

Uso:
    python gerar_dbs.py
"""

import json

from gerar_effects_db import generate_effects_db
from gerar_card_analysis_db import generate_analysis_db

CSV = 'cards_rows.csv'

TESTES = {
    'OP13-086': 'Saint Shalria',
    'OP13-099': 'The Empty Throne',
    'OP13-092': 'Saint Mjosgard',
    'OP13-082': 'Five Elders',
    'PRB02-008': 'Marco',
    'OP13-042': 'Edward Newgate SP',
    'OP13-046': 'Vista',
    'OP03-004': 'rush condicional a DON (regressao das 4 cartas)',
}


def main():
    # 1. effects_db (motor de jogo)
    print('[1/2] Gerando card_effects_db.json ...')
    effects = generate_effects_db(CSV)
    with open('card_effects_db.json', 'w', encoding='utf-8') as f:
        json.dump(effects, f, ensure_ascii=False, indent=2)
    print(f'      {len(effects)} cartas.')

    # 2. analysis_db (frontend/analisador)
    print('[2/2] Gerando card_analysis_db.json ...')
    analysis, skipped = generate_analysis_db(CSV)
    with open('card_analysis_db.json', 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=1)
    print(f'      {len(analysis)} cartas ({skipped} ignoradas).')

    # 3. Sanidade: chaves batem entre os dois
    ka, kb = set(effects), set(analysis)
    if ka != kb:
        print(f'  AVISO: chaves divergentes! so-effects={len(ka-kb)} so-analysis={len(kb-ka)}')
    else:
        print(f'OK: {len(ka)} cartas sincronizadas nos dois bancos.')

    # 4. Sanidade de parsing — checa os DOIS bancos (pega dessincronia)
    print()
    print('--- Sanidade de parsing (cartas-chave, effects + analysis) ---')
    for code, nome in TESTES.items():
        if code not in effects or code not in analysis:
            print(f'  {code} ({nome}): NAO ENCONTRADA')
            continue
        ef_effects = effects[code]['effects']
        ef_analysis = analysis[code]['effects']
        if ef_effects and not ef_analysis:
            print(f'  {code} ({nome}): DESSINCRONIZADA  <-- effects tem, analysis perdeu')
        elif not ef_effects:
            print(f'  {code} ({nome}): SEM EFEITOS  <-- verificar parser')
        else:
            triggers = ', '.join(ef_effects.keys())
            print(f'  {code} ({nome}): OK [{triggers}]')


if __name__ == '__main__':
    main()