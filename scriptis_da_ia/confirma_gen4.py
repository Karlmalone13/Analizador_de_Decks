"""Confirmacao da geracao 4 com PARADA SEQUENCIAL (SPRT) -- bloco 761.

Por que existe: a promocao da gen4 passou por MARGEM (11x3 em 14 pares
decididos, Wilson 52,4% contra portao de 50%; 10x4 daria 45,4% e
reprovaria). Confirmar exigia amostra maior -- 150 pares / 300 partidas,
~45 min, que o usuario considerou tempo demais.

O que muda: MESMO duelo espelho pareado (bloco 756), so que rodado em
LOTES, parando assim que a evidencia for decisiva nos dois sentidos. Se a
gen4 for claramente melhor (ou claramente nao), decide cedo; so gasta as
300 partidas quando o caso e genuinamente ambiguo.

Estatistica: SPRT de Wald sobre os pares DISCORDANTES (os divididos sao
empates e nao entram -- e o teste de McNemar; empate nao diz nada sobre
direcao). H0: p=0,50 (modelos equivalentes). H1: p=0,65 (gen4 melhor).
alpha = beta = 0,05. A cada par discordante o log da razao de
verossimilhanca acumula log(p1/p0) numa vitoria e log((1-p1)/(1-p0)) numa
derrota; cruzar o limite superior ACEITA H1, o inferior ACEITA H0.

Isso NAO e "espiar ate dar certo": os limites do SPRT ja embutem o custo
das checagens repetidas, ao contrario de olhar o intervalo de confianca a
cada lote (que seria p-hacking).

Grava parcial em metrics/confirma_gen4_parcial.json a cada lote, pra
poder acompanhar de longe e pra sobreviver a interrupcao.
"""
import json, math, shutil, time
from pathlib import Path
import treino_continuo as tc

ANTIGO = Path(r'C:\Users\arthu\AppData\Local\Temp\claude'
              r'\C--Projetos-TI-analidador-de-decks-optcg'
              r'\76d559b5-5a92-43ee-b611-b37ec1437643\scratchpad'
              r'\campeao_antigo.joblib')
PARCIAL = tc.RAIZ / 'metrics' / 'confirma_gen4_parcial.json'

P0, P1 = 0.50, 0.65
ALPHA = BETA = 0.05
LIM_SUP = math.log((1 - BETA) / ALPHA)      # aceita H1 (gen4 melhor)
LIM_INF = math.log(BETA / (1 - ALPHA))      # aceita H0 (equivalentes)
PARES_POR_LOTE = 20
MAX_PARES = 200


def main():
    bak = tc.CAMPEAO.with_suffix('.gen4.bak')
    shutil.copyfile(tc.CAMPEAO, bak)
    shutil.copyfile(ANTIGO, tc.CAMPEAO)
    print('campeao trocado pelo ANTIGO (gen4 em {})'.format(bak.name), flush=True)
    print('SPRT: limite superior {:+.3f} (gen4 melhor) | inferior {:+.3f} '
          '(equivalentes)'.format(LIM_SUP, LIM_INF), flush=True)
    print('', flush=True)

    vit = der = div = pares = partidas = 0
    llr = 0.0
    veredito = 'INCONCLUSIVO (bateu o teto de pares)'
    t0 = time.time()
    try:
        lote = 0
        while pares < MAX_PARES:
            lote += 1
            d = tc.duelar(n=PARES_POR_LOTE * 2, workers=2,
                          seed=606 + lote * 1000, peso_camp=200.0,
                          peso_desaf=200.0, pareado=True)
            vit += d['vitorias_desafiante']
            der += d['derrotas_desafiante']
            div += d['pares_divididos']
            pares += d['pares_rodados']
            partidas += d['partidas']
            llr = (vit * math.log(P1 / P0)
                   + der * math.log((1 - P1) / (1 - P0)))
            disc = vit + der
            lim = tc.limite_inferior_wilson(vit, disc) if disc else 0.0
            print('lote {:>2} | pares {:>3} | discordantes {:>3} '
                  '({}x{}) | LLR {:+.3f} | Wilson {:.1%} | {:.0f} min'
                  .format(lote, pares, disc, vit, der, llr, lim,
                          (time.time() - t0) / 60), flush=True)
            PARCIAL.write_text(json.dumps({
                'lote': lote, 'pares': pares, 'partidas': partidas,
                'gen4_venceu': vit, 'antigo_venceu': der, 'divididos': div,
                'discordantes': disc, 'llr': llr, 'wilson': lim,
                'minutos': round((time.time() - t0) / 60, 1),
            }, indent=1), encoding='utf-8')
            if llr >= LIM_SUP:
                veredito = 'CONFIRMADO (gen4 e melhor)'
                break
            if llr <= LIM_INF:
                veredito = 'NAO CONFIRMADO (equivalentes)'
                break
    finally:
        shutil.copyfile(bak, tc.CAMPEAO)
        bak.unlink(missing_ok=True)
        print('campeao RESTAURADO para o gen4', flush=True)

    disc = vit + der
    dt = time.time() - t0
    print('')
    print('=== CONFIRMACAO DA GERACAO 4 (SPRT) ===')
    print('  pares rodados      : {} ({} partidas)'.format(pares, partidas))
    print('  gen4 venceu 2x0    : {}'.format(vit))
    print('  antigo venceu 2x0  : {}'.format(der))
    print('  divididos (empate) : {} ({:.0%})'.format(div, div / max(pares, 1)))
    print('  discordantes       : {}'.format(disc))
    if disc:
        print('  winrate            : {:.1%}'.format(vit / disc))
        print('  limite de Wilson   : {:.1%}'.format(
            tc.limite_inferior_wilson(vit, disc)))
    print('  LLR                : {:+.3f}  (sup {:+.3f} / inf {:+.3f})'.format(
        llr, LIM_SUP, LIM_INF))
    print('  VEREDITO           : {}'.format(veredito))
    print('  tempo              : {:.0f} min'.format(dt / 60))
    print('')
    print('  comparar com a promocao: 11x3, 14 discordantes, Wilson 52,4%')


if __name__ == '__main__':
    main()
