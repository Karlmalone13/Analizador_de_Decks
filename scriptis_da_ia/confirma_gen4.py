"""Confirmacao da promocao da geracao 4 (bloco 760).

A promocao passou por MARGEM: 11x3 em 14 pares decididos, limite de Wilson
52,4% contra portao de 50%. Uma partida a menos (10x4) daria 45,4% e
REPROVARIA. E o planejamento errou por 2x -- previ 58% de pares divididos e
saiu 80%, entao vieram 14 decididos em vez dos ~30.

Aqui: MESMOS dois modelos, amostra 2x maior (150 pares / 300 partidas), que
aos 20% de aproveitamento medidos devem render ~30 pares decididos.

  campeao    = value_net.joblib do commit 5872a58 (o original do bloco 753,
               AUC 0,7704, 4.619 estados -- nunca trocado, porque as
               geracoes 1-3 foram todas descartadas)
  desafiante = value_net_desafiante.joblib (o gen 4, AUC 0,7785, 8.729)

Descartavel. Troca os arquivos, roda e RESTAURA no finally.
"""
import shutil, time
from pathlib import Path
import treino_continuo as tc

ANTIGO = Path(r'C:\Users\arthu\AppData\Local\Temp\claude'
              r'\C--Projetos-TI-analidador-de-decks-optcg'
              r'\76d559b5-5a92-43ee-b611-b37ec1437643\scratchpad'
              r'\campeao_antigo.joblib')


def main():
    campeao_gen4 = tc.CAMPEAO.with_suffix('.gen4.bak')
    shutil.copyfile(tc.CAMPEAO, campeao_gen4)
    shutil.copyfile(ANTIGO, tc.CAMPEAO)
    print('campeao trocado pelo ANTIGO; gen4 guardado em ' + campeao_gen4.name)
    try:
        t0 = time.time()
        d = tc.duelar(n=300, workers=2, seed=606, peso_camp=200.0,
                      peso_desaf=200.0, pareado=True)
        dt = time.time() - t0
    finally:
        shutil.copyfile(campeao_gen4, tc.CAMPEAO)
        campeao_gen4.unlink(missing_ok=True)
        print('campeao RESTAURADO para o gen4')

    lim = tc.limite_inferior_wilson(d['vitorias_desafiante'], d['decididas'])
    wr = d['winrate_desafiante']
    print('')
    print('=== CONFIRMACAO DA GERACAO 4 (150 pares / 300 partidas) ===')
    print('  gen4 venceu dos DOIS lados : {}'.format(d['vitorias_desafiante']))
    print('  antigo venceu dos dois     : {}'.format(d['derrotas_desafiante']))
    print('  divididos (sem informacao) : {} ({:.0%})'.format(
        d['pares_divididos'], d['pares_divididos'] / d['pares_rodados']))
    print('  descartados                : {}'.format(d['erros']))
    print('  pares DECIDIDOS            : {} ({:.0%} de aproveitamento)'.format(
        d['decididas'], d['decididas'] / d['pares_rodados']))
    print('  winrate                    : {}'.format(
        'n/d' if wr is None else '{:.1%}'.format(wr)))
    print('  limite inferior de Wilson  : {:.1%}  (portao exige > 50%)'.format(lim))
    print('  VEREDITO                   : {}'.format(
        'CONFIRMADO' if lim > 0.5 else 'NAO CONFIRMADO'))
    print('  tempo                      : {:.0f} min ({:.1f}s por partida)'.format(
        dt / 60, dt / d['partidas']))
    print('')
    print('  comparar com a promocao: 11x3, 14 decididos, Wilson 52,4%')


if __name__ == '__main__':
    main()
