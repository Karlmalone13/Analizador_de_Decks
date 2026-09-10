"""A/B da VISAO do modelo: 49 features ricas x 32 basicas (bloco 764).

Os dois modelos foram treinados sobre o MESMO corpus (`selfplay_ricas.jsonl`,
1.582 estados, 16 lideres) -- a unica diferenca entre eles e QUANTO enxergam.
Sem isso a comparacao mediria volume de dado, nao visao.

AUC fora da amostra: basicas 0,7484 | ricas 0,7591 (+1,1 ponto).
A pergunta aqui e outra: isso vira VITORIA?

Cada lado usa seu proprio modelo via `value_net_path` (o `win_prob` le
`bundle['feature_names']` e calcula as features certas pra cada um -- por
isso dois modelos com visoes diferentes podem duelar no MESMO processo).
"""
import time
from pathlib import Path
import treino_continuo as tc

RAIZ = Path(__file__).resolve().parent
RICAS = RAIZ / 'metrics' / 'vn_ricas.joblib'
BASICAS = RAIZ / 'metrics' / 'vn_basicas.joblib'


def main():
    t0 = time.time()

    def prog(lote, pares, vit, der, llr, sup, inf):
        print('lote {:>2} | pares {:>3} | discordantes {:>3} ({}x{}) | '
              'LLR {:+.3f} | {:.0f} min'.format(
                  lote, pares, vit + der, vit, der, llr,
                  (time.time() - t0) / 60), flush=True)

    d = tc.duelar_sprt(
        workers=2, seed=1717, peso_camp=200.0, peso_desaf=200.0,
        progresso=prog,
        extras={'desafiante': {'value_net_path': str(RICAS)},
                'campeao': {'value_net_path': str(BASICAS)}})

    disc = d['decididas']
    print('')
    print('=== A/B DA VISAO: ricas (49) x basicas (32) ===')
    print('  pares rodados      : {} ({} partidas, {} lotes)'.format(
        d['pares_rodados'], d['partidas'], d['lotes']))
    print('  RICAS venceram 2x0 : {}'.format(d['vitorias_desafiante']))
    print('  basicas 2x0        : {}'.format(d['derrotas_desafiante']))
    print('  divididos (empate) : {} ({:.0%})'.format(
        d['pares_divididos'], d['pares_divididos'] / max(d['pares_rodados'], 1)))
    print('  discordantes       : {}'.format(disc))
    if disc:
        print('  winrate das ricas  : {:.1%}'.format(
            d['vitorias_desafiante'] / disc))
        print('  Wilson             : {:.1%}'.format(
            tc.limite_inferior_wilson(d['vitorias_desafiante'], disc)))
    print('  LLR                : {:+.3f}'.format(d['llr']))
    print('  VEREDITO           : {}'.format(d['veredito']))
    print('  tempo              : {:.0f} min'.format((time.time() - t0) / 60))


if __name__ == '__main__':
    main()
