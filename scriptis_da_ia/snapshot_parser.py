"""
snapshot_parser.py
==================
Tira uma foto do que o parser produz HOJE para todas as cartas.
Rede de segurança: rode ANTES de mexer no parser, depois compare com diff_parser.py.

Uso:
    python snapshot_parser.py
Saída:
    parser_snapshot.json
"""
import json
from gerar_effects_db import generate_effects_db

db = generate_effects_db('cards_rows.csv')
snap = {code: data['effects'] for code, data in db.items()}

with open('parser_snapshot.json', 'w', encoding='utf-8') as f:
    json.dump(snap, f, ensure_ascii=False, indent=1, sort_keys=True)

com_efeito = sum(1 for e in snap.values() if e)
print(f'Snapshot salvo: {len(snap)} cartas, {com_efeito} com efeito.')
