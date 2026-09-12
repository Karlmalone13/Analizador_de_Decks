"""Portao SPRT do fix de lethal (bloco 779).

DE QUAL PREMISSA ISTO DEPENDE (regra R,D |- G do CLAUDE.md):

  premissa: "certificar lethal com honestidade sobre a mao oculta do
  oponente faz o bot GANHAR mais partidas".

Ela NAO e obvia, e por isso passa pelo portao. O fix tem dois lados:

  GANHO   o bot para de ir all-in numa vitoria que nao existe -- hoje
          isso acontece em 64,6% dos turnos com lethal declarado, e o
          preco e o turno seguinte fechando contra ele.
  RISCO   uma prova mais exigente tambem deixa de certificar lethal
          LEGITIMO. Quando isso acontece o bot ataca com menos agressao
          e pode perder a janela. Se esse custo for maior que o ganho,
          o fix REGRIDE mesmo estando conceitualmente certo.

So o duelo decide. Desenho: ESPELHADO E PAREADO (mesmas sementes, mesmos
decks, lados alternados) com parada sequencial de Wald -- o mesmo portao
que pegou o falso positivo da geracao 4 no bloco 762.

TIPO DO EXPERIMENTO (regra obrigatoria do CLAUDE.md): **nenhum dos dois**.
Isto nao e A nem B -- nao mexe no ML. `peso=0` dos DOIS lados, de
proposito: o fix e de REGRA (a prova de lethal), e misturar o modelo aqui
so adicionaria ruido a uma pergunta que nao e sobre ele.

    python ab_lethal.py --workers 2 --max-pares 120
"""
from __future__ import annotations
import argparse
import time

import treino_continuo as tc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--seed', type=int, default=7791)
    ap.add_argument('--max-pares', type=int, default=120)
    ap.add_argument('--pares-por-lote', type=int, default=20)
    ap.add_argument('--so-executor', action='store_true',
                    help='isola o EXECUTOR da linha certificada; a visao da '
                         'mao oculta fica ligada nos dois lados')
    ap.add_argument('--visao-sem-executor', action='store_true',
                    help='a celula que faltava (bloco 779): prova HONESTA sobre '
                         'a mao oculta, SEM forcar a linha certificada. Os dois '
                         'testes anteriores mostraram que o executor e o culpado '
                         '-- 19x6 a favor da visao quando o executor esta ligado '
                         'nos dois lados, contra 9x15 do fix completo')
    ap.add_argument('--so-mao-oculta', action='store_true',
                    help='isola a VISAO da mao oculta; o executor fica '
                         'ligado nos dois lados')
    a = ap.parse_args()

    if a.visao_sem_executor:
        rotulo = 'VISAO da mao oculta SEM o executor (a celula que faltava)'
        desaf = {'executa_lethal': False, 'lethal_ve_mao_oculta': True}
        camp = {'executa_lethal': False, 'lethal_ve_mao_oculta': False}
    elif a.so_executor:
        rotulo = 'EXECUTOR da linha certificada (mao oculta ligada nos dois)'
        desaf = {'executa_lethal': True, 'lethal_ve_mao_oculta': True}
        camp = {'executa_lethal': False, 'lethal_ve_mao_oculta': True}
    elif a.so_mao_oculta:
        rotulo = 'VISAO da mao oculta (executor ligado nos dois)'
        desaf = {'executa_lethal': True, 'lethal_ve_mao_oculta': True}
        camp = {'executa_lethal': True, 'lethal_ve_mao_oculta': False}
    else:
        rotulo = 'fix COMPLETO (executor + visao da mao oculta)'
        desaf = {'executa_lethal': True, 'lethal_ve_mao_oculta': True}
        camp = {'executa_lethal': False, 'lethal_ve_mao_oculta': False}

    print('')
    print('PORTAO SPRT -- {}'.format(rotulo))
    print('  desafiante: {}'.format(desaf))
    print('  campeao   : {}'.format(camp))
    print('  peso do ML: 0,0 nos dois lados (fix de REGRA, nao de modelo)')
    print('')

    t0 = time.time()
    r = tc.duelar_sprt(
        workers=a.workers, seed=a.seed, peso_camp=0.0, peso_desaf=0.0,
        pares_por_lote=a.pares_por_lote, max_pares=a.max_pares,
        extras={'desafiante': desaf, 'campeao': camp},
        progresso=lambda lote, pares, vit, der, llr, ls, li: print(
            '    lote {:2d} | {:3d} pares | desafiante {}x{} | '
            'llr {:+.2f} (promove >= {:+.2f}, descarta <= {:+.2f})'
            .format(lote, pares, vit, der, llr, ls, li), flush=True))
    dt = time.time() - t0

    print('')
    print('RESULTADO ({:.1f} min)'.format(dt / 60))
    for k, v in sorted(r.items()):
        print('  {:26s}: {}'.format(k, v))


if __name__ == '__main__':
    main()
