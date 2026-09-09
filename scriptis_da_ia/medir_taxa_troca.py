"""
medir_taxa_troca.py
===================
Com que frequencia o termo de valor aprendido REALMENTE troca a acao
escolhida pelo motor?

Pedido do usuario (08/09/2026). Vem de tres observacoes independentes que
apontam pra mesma suspeita -- o termo pode estar INERTE:
  - metrica oficial praticamente nao se moveu (`play` 26,6% -> 26,5%);
  - a distribuicao de estados nao mudou (separabilidade gen0 x gen1-3
    AUC 0,52, `analisar_corpus_valor.py`);
  - as geracoes do laco nao iteraram, so acumularam.

Se o termo quase nunca troca a decisao, o problema NAO e o modelo (que
tem AUC 0,77 fora da amostra): e que +-0,5*peso e pequeno demais perto
dos gaps entre candidatas. Nesse caso o teste certo e SUBIR O PESO, nao
gerar mais partidas -- e este script e o que separa uma coisa da outra.

COMO MEDE (e a limitacao honesta disso)
---------------------------------------
Roda a MESMA partida (mesma seed, mesmo matchup) duas vezes: uma com
peso 0, outra com o peso alvo. O motor e determinístico dada a seed,
entao as duas execucoes sao identicas ATE a primeira decisao em que o
termo troca a escolha.

O que isto mede bem:
  - **% de partidas que divergem** -- se for ~0, o termo e inerte, e a
    conclusao e direta.
  - **onde diverge pela primeira vez** (indice da acao e turno) -- diz se
    o termo so age no fim (jogo decidido, pouco efeito) ou cedo.

O que isto NAO mede: a taxa de troca POR DECISAO ao longo da partida
inteira. Depois da primeira divergencia os dois jogos entram em estados
diferentes, e comparar acao a acao vira comparacao entre partidas
distintas, nao entre decisoes. O numero honesto aqui e "divergiu ou
nao, e quando" -- e o suficiente pra decidir o proximo passo.

Uso:
  python medir_taxa_troca.py --n 20 --peso 200 --workers 4
  python medir_taxa_troca.py --n 20 --peso 800 --workers 4
"""
from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    raise SystemExit(subprocess.call([sys.executable] + sys.argv))

sys.path.insert(0, str(Path(__file__).parent))

from optcg_engine.decision_engine import OPTCGMatch

MODELO = str(Path(__file__).parent / 'metrics' / 'value_net.joblib')


def _assinatura(log: list) -> list:
    """Sequencia de acoes que identifica uma partida, na ordem.

    So o que caracteriza a DECISAO (tipo, quem agiu, carta, alvo) -- nao
    numeros derivados de estado, que mudariam por consequencia e nao por
    escolha."""
    sig = []
    for e in log or []:
        alvo = e.get('target') or {}
        sig.append((e.get('type'), e.get('player'),
                    (e.get('card') or {}).get('code') if isinstance(e.get('card'), dict) else e.get('card'),
                    alvo.get('code') if isinstance(alvo, dict) else alvo))
    return sig


def _jogar(deck_a, deck_b, seed: int, peso: float) -> dict:
    random.seed(seed)
    match = OPTCGMatch(deck_a, deck_b)
    match.setup()
    match.replay_log = []
    if peso:
        for estado in (match.state_a, match.state_b):
            estado.value_net_weight = peso
            estado.value_net_path = MODELO

    winner = None
    turnos = 0
    for turn_num in range(match.MAX_TURNS * 2):
        p = (match.state_a if match.state_a.is_first else match.state_b) \
            if turn_num % 2 == 0 \
            else (match.state_b if match.state_a.is_first else match.state_a)
        opp = match.state_b if p is match.state_a else match.state_a
        r = match.play_turn(p, opp)
        turnos += 1
        if r:
            winner = r
            break
    return {'sig': _assinatura(match.replay_log), 'winner': winner, 'turnos': turnos}


def _par(task) -> dict:
    i, seed, peso = task
    from gerar_selfplay_dataset import _load_deck_list
    deck_list = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(deck_list)), 2)
    _ca, deck_a = deck_list[ia]
    _cb, deck_b = deck_list[ib]

    try:
        sem = _jogar(deck_a, deck_b, seed, 0.0)
        com = _jogar(deck_a, deck_b, seed, peso)
    except Exception as e:
        return {'erro': str(e)[:80]}

    a, b = sem['sig'], com['sig']
    n = min(len(a), len(b))
    primeiro = None
    for k in range(n):
        if a[k] != b[k]:
            primeiro = k
            break
    if primeiro is None and len(a) != len(b):
        primeiro = n     # identicas ate acabar, mas uma seguiu adiante

    return {
        'divergiu': primeiro is not None,
        'primeira_divergencia': primeiro,
        'acoes_sem': len(a), 'acoes_com': len(b),
        'winner_sem': sem['winner'], 'winner_com': com['winner'],
        'mudou_resultado': sem['winner'] != com['winner'],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--peso', type=float, default=200.0)
    ap.add_argument('--seed', type=int, default=555)
    ap.add_argument('--workers', type=int, default=__import__('multiprocessing').cpu_count() - 3)
    args = ap.parse_args()

    tasks = [(i, args.seed * 1_000_003 + i, args.peso) for i in range(args.n)]
    print(f'[troca] {args.n} pares (peso 0 x peso {args.peso}), workers={args.workers}')

    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            res = list(ex.map(_par, tasks))
    else:
        res = [_par(t) for t in tasks]

    erros = [r for r in res if r.get('erro')]
    ok = [r for r in res if not r.get('erro')]
    if not ok:
        print('nenhum par valido:', erros[:3])
        return

    div = [r for r in ok if r['divergiu']]
    mudou = [r for r in ok if r['mudou_resultado']]
    print(f'\n  pares validos:            {len(ok)}  (erros: {len(erros)})')
    print(f'  DIVERGIRAM:               {len(div)}/{len(ok)} ({len(div)/len(ok):.1%})')
    print(f'  mudaram o VENCEDOR:       {len(mudou)}/{len(ok)} ({len(mudou)/len(ok):.1%})')

    if div:
        pos = sorted(r['primeira_divergencia'] for r in div)
        tam = [r['acoes_sem'] for r in div]
        meio = pos[len(pos) // 2]
        frac = [p / t for p, t in zip((r['primeira_divergencia'] for r in div),
                                      (r['acoes_sem'] or 1 for r in div))]
        print(f'\n  1a divergencia (indice da acao): min {pos[0]}, mediana {meio}, max {pos[-1]}')
        print(f'  partida tipica tem ~{sorted(tam)[len(tam)//2]} acoes')
        print(f'  posicao RELATIVA da 1a divergencia (0=inicio, 1=fim): '
              f'mediana {sorted(frac)[len(frac)//2]:.2f}')

    print('\n  LEITURA:')
    if len(div) / len(ok) < 0.25:
        print('  Taxa BAIXA -- o termo esta praticamente INERTE neste peso.')
        print('  Explica de uma vez a metrica parada, a distribuicao identica')
        print('  e o laco que nao itera. O proximo teste e SUBIR O PESO, nao')
        print('  gerar mais partidas.')
    else:
        print('  O termo TROCA decisao com frequencia real. Entao "inerte" nao')
        print('  explica a metrica parada -- ele muda a escolha e o resultado')
        print('  nao melhora, que e um problema DIFERENTE (o valor aprendido')
        print('  discorda do humano sem ganhar mais).')


if __name__ == '__main__':
    main()
