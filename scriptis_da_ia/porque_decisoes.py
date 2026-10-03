"""POR QUE as decisoes foram ruins, e se isso DIMINUI de uma geracao pra outra.

Pedido do usuario (28/09/2026): *"analisar a qualidade de cada decisao, ai caso
tenha uma decisao ruim, saber o porque ela foi ruim e saber como melhorar. E
tambem descobrir/explorar novas decisoes ai ele vai saber se a decisao melhorou
ou nao"*.

Le o corpus do Q. Cada jogada escolhida no modo bootstrap traz:
  regret  = quanto a melhor alternativa da MESMA decisao valia a mais
  porque  = (so se regret > erro do proprio modelo) a jogada feita, a melhor,
            e os conceitos do estado que o modelo diz terem feito a diferenca
(gravados por `OPTCGMatch._q_diagnostica`).

Mostra, POR GERACAO: taxa de decisoes ruins, regret medio, e os motivos mais
comuns -- por tipo de jogada e por lider (INSTRUCAO_MESTRA item 16). E assim
que se ve se um tipo de erro some depois do treino (parte 4 do pedido).

Uso:
    python porque_decisoes.py                        # metrics/q_alvos.jsonl
    python porque_decisoes.py --dataset <x.jsonl> --gen 16 --top 5
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'metrics', 'q_alvos.jsonl')


def _pct(a, b):
    return f'{100.0 * a / b:5.1f}%' if b else '   - '


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default=DEFAULT)
    ap.add_argument('--gen', type=int, default=None, help='so esta geracao')
    ap.add_argument('--top', type=int, default=3)
    ap.add_argument('--min-lider', dest='min_lider', type=int, default=30,
                    help='decisoes minimas pra um lider aparecer')
    args = ap.parse_args()

    por_gen = collections.defaultdict(list)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import corpus_escolhidas
    dataset = args.dataset
    if os.path.abspath(dataset) == os.path.abspath(str(corpus_escolhidas.ORIGEM)):
        dataset = str(corpus_escolhidas.atualiza())   # so as escolhidas tem `regret` (bloco 931)
    with open(dataset, encoding='utf-8') as fh:
        for ln in fh:
            if '"regret"' not in ln:        # filtro barato: so diagnosticadas
                continue
            r = json.loads(ln)
            if not r.get('escolhida') or r.get('regret') is None:
                continue
            g = r.get('gen')
            if args.gen is not None and g != args.gen:
                continue
            por_gen[g].append(r)

    if not por_gen:
        print('Nenhuma decisao diagnosticada no corpus (o diagnostico existe '
              'desde 28/09/2026; geracoes anteriores nao tem).')
        return

    # Jogada de EXPLORACAO (teste proposital) nao e erro do modelo: medido na
    # gen 16, 31% das "ruins" eram exploracao. Ficam fora do mapa.
    exploradas = {g: sum(1 for r in rs if r.get('explorada')) for g, rs in por_gen.items()}
    por_gen = {g: [r for r in rs if not r.get('explorada')] for g, rs in por_gen.items()}
    print('=== decisoes ruins por GERACAO (ruim = regret > erro do modelo; sem exploracao) ===')
    print(f"{'gen':>5} {'decisoes':>9} {'ruins':>7} {'taxa':>7} {'regret medio':>13} {'exploradas (fora)':>18}")
    for g in sorted(por_gen, key=lambda x: (x is None, x)):
        rs = por_gen[g]
        if not rs:
            continue
        ruins = [r for r in rs if r.get('porque')]
        med = sum(r['regret'] for r in rs) / len(rs)
        print(f'{str(g):>5} {len(rs):>9} {len(ruins):>7} {_pct(len(ruins), len(rs)):>7} {med:>13.4f} {exploradas.get(g, 0):>18}')

    for g in sorted(por_gen, key=lambda x: (x is None, x)):
        rs = por_gen[g]
        print(f'\n=== geracao {g}: por TIPO DE JOGADA ===')
        fam = collections.defaultdict(list)
        for r in rs:
            fam[r.get('acao')].append(r)
        for f, lst in sorted(fam.items(), key=lambda t: -len(t[1])):
            ruins = [r for r in lst if r.get('porque')]
            causas = collections.Counter()
            troca = collections.Counter()
            for r in ruins:
                pq = r['porque']
                for c, _ in (pq.get('causas') or [])[:1]:
                    causas[c] += 1
                troca[str(pq.get('melhor') or '?').split(' ')[0]] += 1
            mot = ', '.join(f'{c} {n}' for c, n in causas.most_common(args.top)) or '-'
            alt = ', '.join(f'{c} {n}' for c, n in troca.most_common(args.top)) or '-'
            print(f'  {str(f):<11} {len(lst):>6} dec  ruins {_pct(len(ruins), len(lst))}'
                  f'  | motivo principal: {mot}  | melhor era: {alt}')

        print(f'\n=== geracao {g}: por LIDER (>= {args.min_lider} decisoes) ===')
        lid = collections.defaultdict(list)
        for r in rs:
            lid[r.get('leader')].append(r)
        for l, lst in sorted(lid.items(), key=lambda t: -len(t[1])):
            if len(lst) < args.min_lider:
                continue
            ruins = [r for r in lst if r.get('porque')]
            causas = collections.Counter(
                (r['porque'].get('causas') or [['?']])[0][0] for r in ruins)
            mot = ', '.join(f'{c} {n}' for c, n in causas.most_common(args.top)) or '-'
            print(f'  {str(l):<10} {len(lst):>6} dec  ruins {_pct(len(ruins), len(lst))}  | {mot}')

        ruins = sorted((r for r in rs if r.get('porque')), key=lambda r: -r['regret'])
        print(f'\n=== geracao {g}: as {args.top} PIORES decisoes ===')
        for r in ruins[:args.top]:
            pq = r['porque']
            print(f"  t{r.get('turn')} {r.get('leader')} partida {r.get('match')}: "
                  f"fez [{pq.get('escolhida')}] -- melhor [{pq.get('melhor')}] "
                  f"(regret {r['regret']:.3f}) porque {pq.get('causas')}")


if __name__ == '__main__':
    main()
