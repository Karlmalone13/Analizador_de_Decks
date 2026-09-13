# -*- coding: utf-8 -*-
"""Marca no banco as partidas HUMANO vs HUMANO (bloco 801, item 1).

## O problema

`logs/index.json` tinha **133 de 171 registros sem `bot_side`**, e a ausencia do
campo era AMBIGUA: nao dava pra distinguir

    "nao havia bot nesta partida"      <- resposta
    "havia bot e ninguem anotou"       <- buraco

`audit_real_losses.py` depende disso pra saber quem auditar, e com o campo
ausente ela nao pode nem decidir se a partida serve.

## O criterio, e por que ele e seguro

Os logs do simulador vem em dois formatos:

  * **anonimo** -- `You` / `Opponent`. O nome diz de quem e a PERSPECTIVA do
    log, nao quem era o bot. Nesses, `bot_side` e IRRECUPERAVEL pelo indice:
    nos 38 que tem o campo, `p1` e sempre `You` e mesmo assim `bot_side` varia
    entre p1 e p2 -- houve log exportado da perspectiva do humano, com o bot do
    outro lado. **Este script NAO toca neles.**

  * **com nomes reais** -- `Karlmalone#2854`, `BigRato#5650`, `Jack#5459`... O
    bot nunca aparece com nome de conta: quando ele joga, o log sai anonimo.
    Entao DOIS nomes reais = duas pessoas = humano vs humano.

So o segundo grupo e marcado, e so quando os DOIS lados tem nome real.

Uso:
    python marca_humano_vs_humano.py            # mostra o que faria
    python marca_humano_vs_humano.py --aplicar  # grava
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

RAIZ = Path(__file__).parent
INDEX = RAIZ / 'logs' / 'index.json'

ANONIMOS = {'You', 'Opponent'}


def e_nome_real(nome) -> bool:
    return bool(nome) and nome not in ANONIMOS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--aplicar', action='store_true',
                    help='grava as mudancas (sem isto, so mostra)')
    args = ap.parse_args()

    dados = json.loads(INDEX.read_text(encoding='utf-8'))
    regs = dados if isinstance(dados, list) else dados.get('logs', [])

    marcar, ja_ok, anonimos_sem = [], 0, 0
    for r in regs:
        n1 = (r.get('p1') or {}).get('name')
        n2 = (r.get('p2') or {}).get('name')
        if r.get('bot_side'):
            ja_ok += 1
            continue
        if e_nome_real(n1) and e_nome_real(n2):
            marcar.append(r)
        else:
            anonimos_sem += 1

    print()
    print('  registros no banco              : %d' % len(regs))
    print('  ja tem bot_side                 : %d' % ja_ok)
    print('  ANONIMOS sem bot_side (intocados): %d' % anonimos_sem)
    print('  a marcar como humano_vs_humano  : %d' % len(marcar))
    print()
    for r in marcar[:6]:
        print('     %-22s x %-22s' % ((r.get('p1') or {}).get('name'),
                                      (r.get('p2') or {}).get('name')))
    if len(marcar) > 6:
        print('     ... e mais %d' % (len(marcar) - 6))

    if not args.aplicar:
        print()
        print('  (simulacao -- rode com --aplicar pra gravar)')
        return 0

    for r in marcar:
        r['bot_side'] = None
        r['tipo'] = 'humano_vs_humano'
        r['tipo_origem'] = 'inferido: os dois lados tem nome de conta real'

    bak = INDEX.with_suffix('.json.bak')
    shutil.copyfile(INDEX, bak)
    INDEX.write_text(json.dumps(dados, indent=2, ensure_ascii=False),
                     encoding='utf-8')
    print()
    print('  gravado. backup em %s' % bak.name)
    print('  RESTA o grupo anonimo (%d): ali a informacao pode ser' % anonimos_sem)
    print('  irrecuperavel pelo indice -- exige cruzar com metrics/live_runs/,')
    print('  que so existe quando o BOT jogou.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
