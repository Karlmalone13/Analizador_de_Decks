"""A/B do MEIO-TERMO: cortar a simulacao da RESPOSTA DO OPONENTE. Bloco 770.

Desafiante: `resposta_oponente=False` -- simula o resto do MEU turno e avalia
            no fim dele, sem simular o turno do oponente.
Campeao   : producao de hoje -- simula tambem o turno inteiro do oponente.

Por que este desenho, depois do ML_AVALIADOR ter sido reprovado (1x9):
ha DUAS fontes de nao-quiescencia na avaliacao -- o resto do MEU turno e a
resposta do oponente. O ML_AVALIADOR removeu as DUAS e passou a julgar turno
pela metade (AUC 0,63 contra 0,76). Aqui so a SEGUNDA sai: a posicao continua
quieta em relacao ao meu turno, que e onde a avaliacao e precisa.

Custo medido: 15,3s -> 3,0s por partida (5,1x).
A pergunta aberta: isso custa QUALIDADE? O oponente pode eliminar exatamente
o que acabei de jogar, e nao ver isso pode enganar a escolha.

ML desligado nos dois lados (peso 0, o default de producao) pra isolar a
mudanca de BUSCA. Espelho pareado + SPRT.
"""
from __future__ import annotations
import time

import treino_continuo as tc


def main():
    t0 = time.time()

    def prog(lote, pares, vit, der, llr, sup, inf):
        print('lote {:>2} | pares {:>3} | discordantes {:>3} ({}x{}) | '
              'LLR {:+.3f} | {:.1f} min'.format(
                  lote, pares, vit + der, vit, der, llr,
                  (time.time() - t0) / 60), flush=True)

    d = tc.duelar_sprt(
        workers=2, seed=5150, peso_camp=0.0, peso_desaf=0.0,
        progresso=prog,
        extras={'desafiante': {'resposta_oponente': False},
                'campeao': {'resposta_oponente': True}})

    disc = d['decididas']
    print('')
    print('=== MEIO-TERMO (sem resposta do oponente) x PRODUCAO ===')
    print('  pares rodados       : {} ({} partidas, {} lotes)'.format(
        d['pares_rodados'], d['partidas'], d['lotes']))
    print('  meio-termo 2x0      : {}'.format(d['vitorias_desafiante']))
    print('  producao 2x0        : {}'.format(d['derrotas_desafiante']))
    print('  divididos (empate)  : {} ({:.0%})'.format(
        d['pares_divididos'], d['pares_divididos'] / max(d['pares_rodados'], 1)))
    print('  discordantes        : {}'.format(disc))
    if disc:
        print('  winrate meio-termo  : {:.1%}'.format(
            d['vitorias_desafiante'] / disc))
        print('  Wilson              : {:.1%}'.format(
            tc.limite_inferior_wilson(d['vitorias_desafiante'], disc)))
    print('  LLR                 : {:+.3f}'.format(d['llr']))
    print('  VEREDITO            : {}'.format(d['veredito']))
    print('  tempo               : {:.1f} min'.format((time.time() - t0) / 60))
    print('')
    print('  LEITURA: aqui "DESCARTA (equivalentes)" e VITORIA PRATICA --')
    print('  significa jogar igual gastando 1/5 do tempo.')


if __name__ == '__main__':
    main()
