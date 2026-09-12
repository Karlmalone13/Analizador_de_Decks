"""A/B: ML COMO AVALIADOR x motor de producao (rollout). Bloco 769.

Desafiante: `ml_avaliador=True` com o modelo treinado em estados POS-ACAO
            (`vn_grande.joblib`) -- avalia a posicao logo apos a acao, sem
            simular turno nenhum.
Campeao   : motor de producao de hoje -- rollout de 2 turnos por candidata,
            heuristica decidindo, ML desligado (peso 0, que e o default).

O que esta em jogo (pedido repetido do usuario: migrar da heuristica pro
ML, um ML que DECIDA):

  custo    : 17,4s -> 1,2s por partida (14,8x, medido)
  precisao : AUC fora da amostra 0,7591 (fim de turno) -> 0,6318 (pos-acao)

Mais barato E menos preciso. Nenhum dos dois numeros decide -- so o duelo
diz se o bot JOGA MELHOR. Espelho pareado + SPRT (bloco 762).
"""
from __future__ import annotations
import time
from pathlib import Path

import treino_continuo as tc

RAIZ = Path(__file__).resolve().parent
# Bloco 781: modelo treinado no corpus GRANDE de MEIO DE TURNO (73.821
# estados pos-acao). O teste do bloco 769 usou um modelo de 3.614 estados,
# AUC 0,632, e perdeu 1x9 -- este tem AUC 0,8144 fora da amostra. A curva
# medida no mesmo corpus: 0,778 (2,2k estados) -> 0,834 (59k).
#
# POR QUE NAO E REPETIR EXPERIMENTO REPROVADO: o bloco 769 concluiu que o ML
# nao substitui o rollout porque "julga turno pela metade". Medido agora, a
# causa era FOME DE DADO de meio de turno, nao dificuldade intrinseca --
# mesmo padrao do bloco 775, onde 23x de corpus levou o ML autonomo de 10,0%
# a 31,8%. Este e o primeiro teste com um modelo de meio de turno DE VERDADE.
#
# TIPO DO EXPERIMENTO (regra obrigatoria do CLAUDE.md): **TIPO A** -- o
# modelo AVALIA sozinho, sem rollout e sem heuristica somada (peso 0 nos
# dois lados). Se ganhar, o Monte Carlo perde a razao de existir e os ~85%
# do tempo de simulacao caem junto.
MODELO = RAIZ / 'metrics' / 'value_net_meio_turno.joblib'


def main():
    t0 = time.time()

    def prog(lote, pares, vit, der, llr, sup, inf):
        print('lote {:>2} | pares {:>3} | discordantes {:>3} ({}x{}) | '
              'LLR {:+.3f} | {:.1f} min'.format(
                  lote, pares, vit + der, vit, der, llr,
                  (time.time() - t0) / 60), flush=True)

    d = tc.duelar_sprt(
        workers=2, seed=2727, peso_camp=0.0, peso_desaf=1.0,
        progresso=prog,
        extras={'desafiante': {'ml_avaliador': True,
                               'value_net_path': str(MODELO)},
                'campeao': {'ml_avaliador': False}})

    disc = d['decididas']
    print('')
    print('=== ML AVALIADOR (pos-acao) x MOTOR DE PRODUCAO (rollout) ===')
    print('  pares rodados       : {} ({} partidas, {} lotes)'.format(
        d['pares_rodados'], d['partidas'], d['lotes']))
    print('  ML avaliador 2x0    : {}'.format(d['vitorias_desafiante']))
    print('  producao 2x0        : {}'.format(d['derrotas_desafiante']))
    print('  divididos (empate)  : {} ({:.0%})'.format(
        d['pares_divididos'], d['pares_divididos'] / max(d['pares_rodados'], 1)))
    print('  discordantes        : {}'.format(disc))
    if disc:
        print('  winrate do ML       : {:.1%}'.format(
            d['vitorias_desafiante'] / disc))
        print('  Wilson              : {:.1%}'.format(
            tc.limite_inferior_wilson(d['vitorias_desafiante'], disc)))
    print('  LLR                 : {:+.3f}'.format(d['llr']))
    print('  VEREDITO            : {}'.format(d['veredito']))
    print('  tempo               : {:.1f} min'.format((time.time() - t0) / 60))


if __name__ == '__main__':
    main()
