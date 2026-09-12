"""FASE 1 do plano professor/aluno: o ROTULO. Bloco 783.

NAO RODA PARTIDA NENHUMA -- reanalisa o corpus que ja existe.

## O problema, medido (`analisa_rotulo.py`)

O rotulo de hoje e `win`: "esta PARTIDA terminou em vitoria?", copiado igual
pra todos os ~18,5 estados daquela partida.

```
100,0% da variacao do rotulo e explicada pela PARTIDA, nao pela posicao
variancia DENTRO da mesma partida: 0,0000 (exatamente zero)
correlacao entre melhorar a posicao e o rotulo: +0,21
```

O modelo ve 18 posicoes diferentes -- jogadas boas, ruins e neutras -- com a
MESMA etiqueta. Ele nao aprende qualidade de jogada; aprende quem ganhou.

## O alvo do professor: RETORNO DE N PASSOS com bootstrap

Formula padrao de aprendizado por diferenca temporal, e e exatamente o que o
usuario pediu em 11/09 (*"nao seria melhor se ele analisasse a cada 2
turnos?"*):

    alvo(t) = (1 - lam) * vantagem(t -> t+n)  +  lam * resultado_final

onde `vantagem` e a variacao de `life_diff` nos proximos n passos do MESMO
lado, espremida pra [0,1] por uma logistica.

**Por que isto NAO e copiar a heuristica** (regra do tipo A/B do CLAUDE.md):
`life_diff` e ESTADO DO JOGO observavel -- vida contada no tabuleiro --, nao
pontuacao de `_evaluate_state_v2` nem peso ajustado a mao. O alvo continua
sendo consequencia MEDIDA, so que medida perto em vez de 20 turnos depois. E
TIPO A.

**O `lam` e o que impede o alvo de ficar miope**: vantagem de vida a 2 turnos
sozinha premiaria trocar recurso por dano sem olhar o jogo longo. O termo do
resultado final ancora no que de fato importa.

## Ressalva honesta

Vantagem de vida NAO e a unica forma de estar ganhando -- o usuario ja
apontou isso ("as vezes podemos limpar o board do adversario, ou esvaziar sua
mao"). Esta versao usa vida porque e o sinal denso que JA existe no corpus.
Board e mao entram depois, como termos adicionais, e cada um so entra se
medir melhor.
"""
from __future__ import annotations
import argparse
import collections
import io
import json
import math

from optcg_engine import value_net as vn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default='metrics/selfplay_pos_acao_grande.jsonl')
    ap.add_argument('--out', default='metrics/corpus_professor.jsonl')
    ap.add_argument('--n', type=int, default=2,
                    help='horizonte em passos do MESMO lado (2 = o que o usuario sugeriu)')
    ap.add_argument('--lam', type=float, default=0.5,
                    help='peso do resultado final (0 = so vantagem curta, 1 = so o rotulo de hoje)')
    ap.add_argument('--escala', type=float, default=1.0,
                    help='escala da logistica que espreme a vantagem em [0,1]')
    a = ap.parse_args()

    i_ld = list(vn.FEATURE_NAMES_V3).index('life_diff')

    regs = []
    for L in io.open(a.corpus, encoding='utf-8'):
        d = json.loads(L)
        if 'win' not in d or 'feats' not in d:
            continue
        regs.append(d)
    print('corpus lido: {} estados'.format(len(regs)))

    # agrupa por (partida, lado) e ordena por turno -- o "proximo passo" tem
    # que ser do MESMO lado, senao a vantagem seria medida no turno do
    # adversario e trocaria de sinal.
    seq = collections.defaultdict(list)
    for idx, d in enumerate(regs):
        seq[(d.get('match'), d.get('side'))].append(
            (d.get('turn') if d.get('turn') is not None else 0, idx))

    n_alvo = 0
    for chave, v in seq.items():
        v.sort()
        for j, (_t, idx) in enumerate(v):
            k = min(j + a.n, len(v) - 1)
            ld_agora = regs[idx]['feats'][i_ld]
            ld_depois = regs[v[k][1]]['feats'][i_ld]
            vantagem = ld_depois - ld_agora
            # logistica: 0 de vantagem -> 0,5; +1 vida -> ~0,73; -1 -> ~0,27
            curto = 1.0 / (1.0 + math.exp(-a.escala * vantagem))
            final = float(regs[idx]['win'])
            regs[idx]['alvo'] = (1.0 - a.lam) * curto + a.lam * final
            regs[idx]['vantagem_n'] = vantagem
            n_alvo += 1

    with io.open(a.out, 'w', encoding='utf-8') as f:
        for d in regs:
            f.write(json.dumps(d, ensure_ascii=False) + '\n')

    alvos = [d['alvo'] for d in regs if 'alvo' in d]
    wins = [float(d['win']) for d in regs]
    import statistics as st
    print('')
    print('ALVO DO PROFESSOR gerado: {} estados -> {}'.format(n_alvo, a.out))
    print('  n={} passos | lam={} (peso do resultado final)'.format(a.n, a.lam))
    print('')
    print('  rotulo de HOJE  : media {:.3f} | desvio {:.3f} | valores distintos {}'
          .format(st.mean(wins), st.pstdev(wins), len(set(wins))))
    print('  alvo do PROFESSOR: media {:.3f} | desvio {:.3f} | valores distintos {}'
          .format(st.mean(alvos), st.pstdev(alvos), len(set(round(x, 4) for x in alvos))))
    print('')
    # o teste que importa: o alvo agora VARIA dentro da mesma partida?
    dentro = []
    for chave, v in seq.items():
        if len(v) > 1:
            xs = [regs[i]['alvo'] for _t, i in v if 'alvo' in regs[i]]
            if len(xs) > 1:
                dentro.append(st.pvariance(xs))
    print('  variancia DENTRO da partida:')
    print('    rotulo de hoje   : 0.0000   (por construcao -- era o problema)')
    print('    alvo do professor: {:.4f}'.format(st.mean(dentro) if dentro else 0.0))
    print('')
    print('LEITURA: se a variancia dentro da partida deixou de ser zero, estados')
    print('diferentes da MESMA partida passaram a ter alvos diferentes -- o')
    print('modelo finalmente tem como distinguir jogada boa de ruim.')


if __name__ == '__main__':
    main()
