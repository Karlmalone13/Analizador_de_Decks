"""ALAVANCA de cada familia de decisao: quanto custa decidir MAL ali?

Bloco 777. Achado que motiva (bloco 776): duas tentativas completamente
diferentes de melhorar a escolha de ALVO deram o MESMO 96% de empate --
escolher melhor o alvo NAO decide partidas neste jogo. E eu tinha priorizado
essa familia por ela ser a pior em CONCORDANCIA COM HUMANO (16,4%), o que se
mostrou criterio errado: concordar com humano e mudar o resultado sao coisas
diferentes.

O INSTRUMENTO: um lado decide a familia no ALEATORIO, o outro pela regra
normal. Se o lado aleatorio perder feio, a familia IMPORTA -- e decidir bem
ali tem espaco pra ganhar. Se empatar, a familia NAO importa, e construir ML
pra ela e desperdicio.

Isso mede o TETO: quanto se perde decidindo mal e o maximo que se poderia
ganhar decidindo bem. Barato (~20 min por familia) contra horas implementando
ML pra descobrir depois que nao valia.

Uso: python mede_alavanca.py --familia blocker
     python mede_alavanca.py --todas
"""
from __future__ import annotations
import argparse
import time

import treino_continuo as tc

FAMILIAS = {
    'alvo': 'qual alvo o efeito elimina (regra: max board_value)',
    'blocker': 'qual blocker defende (regra: min custo de sacrificio)',
    'descarte': 'qual carta descartar (regra: min _trash_value)',
}


def uma(familia, workers, max_pares):
    t0 = time.time()

    def prog(lote, pares, vit, der, llr, sup, inf):
        print('   lote {:>2} | pares {:>3} | discordantes {:>3} ({}x{}) | '
              'LLR {:+.3f} | {:.1f} min'.format(
                  lote, pares, vit + der, vit, der, llr,
                  (time.time() - t0) / 60), flush=True)

    # desafiante = quem decide ALEATORIO nesta familia
    d = tc.duelar_sprt(
        workers=workers, seed=3030, peso_camp=0.0, peso_desaf=0.0,
        max_pares=max_pares, progresso=prog,
        extras={'desafiante': {'familia_aleatoria': familia},
                'campeao': {'familia_aleatoria': None}})
    d['minutos'] = (time.time() - t0) / 60
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--familia', choices=tuple(FAMILIAS))
    ap.add_argument('--todas', action='store_true')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--max-pares', dest='max_pares', type=int, default=100)
    a = ap.parse_args()

    alvo = list(FAMILIAS) if a.todas else [a.familia]
    if not alvo or alvo == [None]:
        ap.error('use --familia NOME ou --todas')

    res = {}
    for f in alvo:
        print('')
        print('=' * 70)
        print('FAMILIA: {}  --  {}'.format(f, FAMILIAS[f]))
        print('  (desafiante decide no ALEATORIO; campeao usa a regra)')
        print('=' * 70)
        res[f] = uma(f, a.workers, a.max_pares)

    print('')
    print('=' * 70)
    print('ALAVANCA POR FAMILIA')
    print('=' * 70)
    print('{:<12}{:>9}{:>14}{:>12}{:>10}'.format(
        'familia', 'empate', 'discordantes', 'winrate ALE', 'min'))
    for f, d in res.items():
        disc = d['decididas']
        wr = d['winrate_desafiante']
        print('{:<12}{:>8.0%}{:>14}{:>12}{:>10.0f}'.format(
            f, d['pares_divididos'] / max(d['pares_rodados'], 1), disc,
            'n/d' if wr is None else '{:.1%}'.format(wr), d['minutos']))
    print('')
    print('LEITURA: "winrate ALE" e o desempenho de quem decide NO ALEATORIO.')
    print('  perto de 50% -> a familia NAO importa (decidir bem nao paga)')
    print('  bem abaixo de 50% -> a familia IMPORTA, e ha espaco pra ganhar')
    print('  empate alto -> a decisao raramente muda o desfecho')


if __name__ == '__main__':
    main()
