# -*- coding: utf-8 -*-
"""Reparseia TODO o banco de combat logs (`logs/raw` -> `logs/parsed`).

POR QUE EXISTE (bloco 739). O parser de combat log descartava em silencio
o ULTIMO turno de cada partida: um bloco de turno so era emitido quando
casava o marcador de fim de turno, e o turno final nao tem esse marcador
-- a partida acaba em `GameOver`.

Nao e caso de borda: o turno final e o turno LETAL, onde se ataca e se
despeja DON em vez de desenvolver board. A perda por isso e ENVIESADA
por tipo de acao, e o corpus e a regua de todo o projeto
(`human_patterns.json`, `decision_quality_full.py`, sequenciamento).

Depois de qualquer correcao no parser que mude a EXTRACAO (nao o formato
de saida), o banco inteiro precisa ser reconstruido -- senao convivem
logs parseados por versoes diferentes do parser, que e a pior das duas
opcoes.

Uso:
    python reparse_banco.py [--dry-run]
"""
import glob
import json
import os
import sys

import parse_combat_log as P

TIPOS = ('play', 'activate', 'attack', 'attach_don')


def conta(d):
    c = {t: 0 for t in TIPOS}
    for t in d.get('turns', []):
        for a in (t.get('actions') or []):
            if a.get('type') in c:
                c[a['type']] += 1
    return c


def main():
    dry = '--dry-run' in sys.argv
    antes = {t: 0 for t in TIPOS}
    depois = {t: 0 for t in TIPOS}
    turnos_antes = turnos_depois = 0
    ok = falhou = 0

    for raw in sorted(glob.glob(os.path.join('logs', 'raw', '*.log'))):
        destino = os.path.join('logs', 'parsed',
                               os.path.basename(raw)[:-4] + '.json')
        if not os.path.exists(destino):
            continue
        try:
            velho = json.load(open(destino, encoding='utf-8'))
        except Exception:
            continue
        try:
            novo, _ = P.parse_log(raw)
        except Exception as e:
            falhou += 1
            print(f'  FALHOU {os.path.basename(raw)}: {e}')
            continue
        ca, cd = conta(velho), conta(novo)
        for t in TIPOS:
            antes[t] += ca[t]
            depois[t] += cd[t]
        turnos_antes += len(velho.get('turns', []))
        turnos_depois += len(novo.get('turns', []))
        ok += 1
        if not dry:
            with open(destino, 'w', encoding='utf-8') as f:
                json.dump(novo, f, ensure_ascii=False, indent=2)

    print(f'{ok} logs reparseados, {falhou} falha(s)'
          f'{"  [DRY-RUN, nada gravado]" if dry else ""}')
    print(f'turnos: {turnos_antes} -> {turnos_depois} '
          f'(+{turnos_depois - turnos_antes})')
    print()
    print(f'{"tipo":12s} {"antes":>7s} {"depois":>7s} {"delta":>7s}    %')
    for t in TIPOS:
        a, d = antes[t], depois[t]
        print(f'{t:12s} {a:7d} {d:7d} {d - a:+7d}   {(d - a) / max(a, 1) * 100:+5.1f}%')


if __name__ == '__main__':
    main()
