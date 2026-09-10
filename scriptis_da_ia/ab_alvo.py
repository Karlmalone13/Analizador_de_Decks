"""A/B do knob ALVO_EFEITO_NA_BUSCA, por SPRT (bloco 763).

O QUE MEDE: trazer a escolha de ALVO de efeito pra dentro da busca -- em vez
de deixar a heuristica fixa `max(board_value)` escolher na execucao -- faz o
bot GANHAR mais?

POR QUE IMPORTA (medido em 10/09): das escolhas de alvo com 2+ candidatos,
**44,6% tem EMPATE EXATO no topo** -- a regua nao esta discordando, esta
CEGA, e devolve o que estiver primeiro na lista. E o modelo de valor nunca
e consultado sobre alvo: ele so decide a acao de topo.

DESENHO: knob LIGADO no desafiante, DESLIGADO no campeao, na MESMA partida
(override por jogador do bloco 763 -- o knob e do processo, entao sem isso
ligaria pros dois lados e o duelo daria 50% por construcao).

ML DESLIGADO dos dois lados (peso 0) de proposito: mede a mudanca
ESTRUTURAL sozinha, no motor como ele e hoje. Misturar com o value_net
tornaria impossivel saber qual dos dois causou o que.

Duelo espelho pareado + SPRT (bloco 762): so conta o par em que o mesmo
lado vence dos DOIS lados, e para assim que a evidencia basta.
"""
import time
import treino_continuo as tc


def main():
    def prog(lote, pares, vit, der, llr, sup, inf):
        print('lote {:>2} | pares {:>3} | discordantes {:>3} ({}x{}) | '
              'LLR {:+.3f} (sup {:+.2f} / inf {:+.2f}) | {:.0f} min'
              .format(lote, pares, vit + der, vit, der, llr, sup, inf,
                      (time.time() - t0) / 60), flush=True)

    t0 = time.time()
    d = tc.duelar_sprt(
        workers=2, seed=4242, peso_camp=0.0, peso_desaf=0.0,
        progresso=prog,
        extras={'desafiante': {'alvo_efeito_na_busca': True},
                'campeao': {'alvo_efeito_na_busca': False}})

    disc = d['decididas']
    print('')
    print('=== A/B: ALVO na busca (desafiante) x heuristica fixa (campeao) ===')
    print('  pares rodados       : {} ({} partidas, {} lotes)'.format(
        d['pares_rodados'], d['partidas'], d['lotes']))
    print('  ALVO-na-busca 2x0   : {}'.format(d['vitorias_desafiante']))
    print('  heuristica fixa 2x0 : {}'.format(d['derrotas_desafiante']))
    print('  divididos (empate)  : {} ({:.0%})'.format(
        d['pares_divididos'], d['pares_divididos'] / max(d['pares_rodados'], 1)))
    print('  discordantes        : {}'.format(disc))
    if disc:
        print('  winrate             : {:.1%}'.format(
            d['vitorias_desafiante'] / disc))
        print('  Wilson              : {:.1%}'.format(
            tc.limite_inferior_wilson(d['vitorias_desafiante'], disc)))
    print('  LLR                 : {:+.3f}'.format(d['llr']))
    print('  VEREDITO            : {}'.format(d['veredito']))
    print('  tempo               : {:.0f} min'.format((time.time() - t0) / 60))


if __name__ == '__main__':
    main()
