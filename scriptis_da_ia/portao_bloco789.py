# -*- coding: utf-8 -*-
"""PORTAO em TRES CELULAS -- o que os blocos 785-788 mudaram, medido.

Pedido do usuario (13/09/2026): *"roda o portao nas tres celulas"*.

## O que cada celula compara

  1. TUDO JUNTO    -- os knobs novos ligados x o comportamento anterior
  2. LETHAL x TRIGGER -- so a prova de lethal contando com [Trigger]
  3. CLONE         -- so a preservacao das guardas de uma-vez-por-turno

As celulas 2 e 3 existem porque as duas mudancas sao da familia que JA custou
partidas quando foi "consertada" sem isolamento (bloco 779: a prova honesta de
lethal deu 9x15 porque a flag alimenta 7 comportamentos). Medir tudo junto
devolve so o saldo liquido e nao diz qual pedaco quebrou.

## O QUE ESTE PORTAO **NAO** MEDE -- declarado, nao escondido

**A remocao do Monte Carlo (bloco 785) NAO e isolavel.** O duelo espelhado roda
os dois lados no MESMO processo, e a busca determinística substituiu o rollout
estruturalmente -- nao ha knob por jogador que traga o Monte Carlo de volta de
um lado so. O que estas celulas medem sao as mudancas de COMPORTAMENTO que
tem override por jogador. A troca de busca em si so seria medivel contra um
commit anterior, em processos separados (sem pareamento).

Mesma coisa vale pro agrupamento das consultas ao modelo (bloco 787): ele foi
provado por TESTE (saida bit-a-bit identica), nao por duelo -- nao muda decisao
nenhuma, entao um duelo daria 100% de empate por construcao.

## Metodo

`duelar_sprt` (SPRT de Wald, parada sequencial) sobre duelo ESPELHO PAREADO:
cada par roda a MESMA seed com o desafiante de cada lado, e so conta o par em
que o mesmo lado vence duas vezes. Par dividido = o matchup decidiu, nao a
mudanca -- entra como SEM INFORMACAO.

Uso:
    python portao_bloco789.py --workers 2                # as 3 celulas
    python portao_bloco789.py --workers 2 --celula 2     # so uma
    python portao_bloco789.py --workers 2 --teste        # 4 pares, so fumaca
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
SAIDA = RAIZ / 'metrics' / 'portao_789'

# Comportamento ANTERIOR aos blocos 785-788, campo a campo.
ANTIGO = {
    'modelo_ordena': False,              # a ordem vinha da pontuacao estatica
    'modelo_sacrificio': False,          # blocker/counter/search/trash por regra fixa
    'arvore_don_extra': 0,               # um unico valor de DON por ataque
    'alvo_efeito_na_busca': False,       # alvo do efeito nao ramificava
    'lethal_ve_trigger': False,          # a prova ignorava [Trigger]
    'clone_perde_once_per_turn': True,   # o clone esquecia as guardas
}

CELULAS = {
    1: ('TUDO JUNTO (knobs novos x comportamento anterior)',
        {}, dict(ANTIGO)),
    2: ('LETHAL x TRIGGER isolado',
        {'lethal_ve_trigger': True}, {'lethal_ve_trigger': False}),
    3: ('CLONE preserva uma-vez-por-turno isolado',
        {'clone_perde_once_per_turn': False}, {'clone_perde_once_per_turn': True}),
}


def roda_celula(n: int, workers: int, seed: int, max_pares: int):
    import treino_continuo as tc
    titulo, desaf, camp = CELULAS[n]
    print()
    print('=' * 70)
    print('CELULA %d -- %s' % (n, titulo))
    print('  desafiante:', desaf or '(defaults de hoje)')
    print('  campeao   :', camp)
    print('=' * 70, flush=True)

    def progresso(lote, pares, vit, der, llr, sup, inf):
        print('   lote %2d | %3d pares | %3d x %3d decididos | LLR %+6.2f '
              '(limites %+.2f / %+.2f)'
              % (lote, pares, vit, der, llr, inf, sup), flush=True)

    t0 = time.time()
    d = tc.duelar_sprt(
        workers=workers, seed=seed,
        peso_camp=0.0, peso_desaf=0.0,   # o termo SOMADO nao decide nada hoje
        max_pares=max_pares, progresso=progresso,
        extras={'desafiante': desaf, 'campeao': camp})
    d['celula'] = n
    d['titulo'] = titulo
    d['extras_desafiante'] = desaf
    d['extras_campeao'] = camp
    d['minutos'] = round((time.time() - t0) / 60.0, 1)
    print()
    print('  RESULTADO: %s' % d['veredito'])
    print('  %d x %d em %d pares decididos (%d divididos, %d partidas, %.1f min)'
          % (d['vitorias_desafiante'], d['derrotas_desafiante'], d['decididas'],
             d['pares_divididos'], d['partidas'], d['minutos']))
    if d['winrate_desafiante'] is not None:
        print('  winrate do desafiante: %.1f%%  | LLR %+.2f'
              % (100 * d['winrate_desafiante'], d['llr']))
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, required=True,
                    help='obrigatorio e explicito (regra do projeto)')
    ap.add_argument('--celula', type=int, default=None, choices=(1, 2, 3))
    ap.add_argument('--seed', type=int, default=4242)
    ap.add_argument('--max-pares', dest='max_pares', type=int, default=200)
    ap.add_argument('--teste', action='store_true',
                    help='4 pares por celula, so pra ver se roda')
    args = ap.parse_args()

    for v in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ.setdefault(v, '1')   # senao os workers disputam os nucleos

    max_pares = 4 if args.teste else args.max_pares
    celulas = [args.celula] if args.celula else [1, 2, 3]

    resultados = []
    for n in celulas:
        resultados.append(roda_celula(n, args.workers,
                                      args.seed + n * 1009, max_pares))

    print()
    print('=' * 70)
    print('RESUMO')
    print('=' * 70)
    for d in resultados:
        print('  celula %d  %-46s %3d x %-3d  %s'
              % (d['celula'], d['titulo'][:46], d['vitorias_desafiante'],
                 d['derrotas_desafiante'], d['veredito']))

    if not args.teste:
        SAIDA.mkdir(parents=True, exist_ok=True)
        destino = SAIDA / ('portao_%s.json'
                           % datetime.now().strftime('%Y-%m-%dT%H.%M.%S'))
        destino.write_text(json.dumps(resultados, indent=2, ensure_ascii=False),
                           encoding='utf-8')
        print()
        print('  gravado em %s' % destino.relative_to(RAIZ))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
