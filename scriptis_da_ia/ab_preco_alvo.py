"""A/B: ALVO escolhido pelo MODELO x por `board_value()`. Bloco 776.

Primeira fatia do ALCANCE. O inventario do bloco 774 achou **81 decisoes
fixas em 28 funcoes**, quase todas usando `board_value()` ou `_trash_value`
-- duas heuristicas escolhendo quase tudo no jogo. Em vez de reescrever 28
funcoes pra consultarem o modelo, troca-se a REGUA.

Aqui so a familia ALVO DE EFEITO, que e a mais contida e a de pior
desempenho medido (16,4% de acerto contra humano, uma das tres piores
categorias do projeto).

Desafiante: alvo = `max(candidatos, key=delta_remover)` -- a carta cuja
            remocao mais aumenta a chance de vitoria, medida pelo modelo
            de AUC 0,856 (bloco 775).
Campeao   : alvo = `max(candidatos, key=board_value)` -- `power//1000` mais
            bonus de keyword, escrito a mao.

ML COMO TERMO fica DESLIGADO nos dois lados (peso 0, o default de
producao). Isolado de proposito: mede a troca de REGUA, nao o ML somado.
Pela regra do bloco 770, este e um experimento **tipo A** -- o modelo
DECIDE (qual alvo), nao calibra pontuacao de heuristica.
"""
from __future__ import annotations
import time
from pathlib import Path

import treino_continuo as tc

RAIZ = Path(__file__).resolve().parent
MODELO = RAIZ / 'metrics' / 'vn_grande.joblib'


def main():
    t0 = time.time()

    def prog(lote, pares, vit, der, llr, sup, inf):
        print('lote {:>2} | pares {:>3} | discordantes {:>3} ({}x{}) | '
              'LLR {:+.3f} | {:.1f} min'.format(
                  lote, pares, vit + der, vit, der, llr,
                  (time.time() - t0) / 60), flush=True)

    d = tc.duelar_sprt(
        workers=2, seed=8080, peso_camp=0.0, peso_desaf=0.0,
        progresso=prog,
        extras={'desafiante': {'alvo_preco_ml': True,
                               'value_net_path': str(MODELO)},
                'campeao': {'alvo_preco_ml': False}})

    disc = d['decididas']
    print('')
    print('=== ALVO pelo MODELO x ALVO por board_value() ===')
    print('  pares rodados       : {} ({} partidas, {} lotes)'.format(
        d['pares_rodados'], d['partidas'], d['lotes']))
    print('  regua do MODELO 2x0 : {}'.format(d['vitorias_desafiante']))
    print('  board_value 2x0     : {}'.format(d['derrotas_desafiante']))
    print('  divididos (empate)  : {} ({:.0%})'.format(
        d['pares_divididos'], d['pares_divididos'] / max(d['pares_rodados'], 1)))
    print('  discordantes        : {}'.format(disc))
    if disc:
        print('  winrate do MODELO   : {:.1%}'.format(
            d['vitorias_desafiante'] / disc))
        print('  Wilson              : {:.1%}'.format(
            tc.limite_inferior_wilson(d['vitorias_desafiante'], disc)))
    print('  LLR                 : {:+.3f}'.format(d['llr']))
    print('  VEREDITO            : {}'.format(d['veredito']))
    print('  tempo               : {:.1f} min'.format((time.time() - t0) / 60))
    print('')
    print('  LEMBRETE de leitura (bloco 770): "DESCARTA" significa NAO E')
    print('  MELHOR -- nao distingue equivalente de pior. Olhar o placar.')


if __name__ == '__main__':
    main()
