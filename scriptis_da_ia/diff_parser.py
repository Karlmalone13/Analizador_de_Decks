"""
diff_parser.py
=============
Compara o parser ATUAL contra o snapshot salvo. Mostra o que mudou.
Rode DEPOIS de cada alteração no parser.

Uso:
    python diff_parser.py
"""
import json
from gerar_effects_db import generate_effects_db

with open('parser_snapshot.json', encoding='utf-8') as f:
    old = json.load(f)

db = generate_effects_db('cards_rows.csv')
new = {code: data['effects'] for code, data in db.items()}

ganhou, perdeu, mudou = [], [], []
for code in old:
    o, n = old[code], new.get(code, {})
    if not o and n:
        ganhou.append(code)          # antes vazio, agora tem efeito (BOM)
    elif o and not n:
        perdeu.append(code)          # antes tinha, agora vazio (REGRESSAO!)
    elif o != n:
        mudou.append(code)           # mudou o conteudo (verificar)

print(f'GANHOU efeito (vazio -> com efeito): {len(ganhou)}')
print(f'PERDEU efeito (REGRESSAO!):          {len(perdeu)}')
print(f'MUDOU conteudo (verificar):          {len(mudou)}')

if perdeu:
    print('\n!!! REGRESSOES (cartas que pararam de funcionar):')
    for c in perdeu[:30]:
        print(f'  {c}: {old[c]}')

if mudou:
    print('\n--- Mudancas de conteudo (amostra) ---')
    for c in mudou[:15]:
        print(f'  {c}:\n    ANTES: {old[c]}\n    DEPOIS: {new[c]}')