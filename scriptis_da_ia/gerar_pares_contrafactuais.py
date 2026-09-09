"""
gerar_pares_contrafactuais.py
=============================
Coleta o rotulo que faltava: **entre duas IRMAS da mesma decisao, qual
delas de fato leva a ganhar a partida?**

Escolha do usuario (08/09/2026, opcao A), depois do diagnostico do bloco
754: o valor aprendido troca decisao em 100% das partidas, muda o
vencedor em 28% delas, e MESMO ASSIM o winrate fica em ~50% e a
distribuicao de estados nao muda (separabilidade 0,52). A leitura e que
ele ordena bem estados DISTANTES (AUC 0,77) e nao distingue estados
IRMAOS -- as opcoes de uma mesma decisao, que diferem por um DON, um
corpo, uma carta.

Modelo treinado em estado avulso nunca aprende essa distincao, porque
nunca ve duas irmas lado a lado com rotulos diferentes. Aqui ele passa a
ver.

COMO O ROTULO E OBTIDO (contrafactual de verdade)
-------------------------------------------------
Para um par:
  1. Escolhe uma decisao alvo `D` da partida.
  2. Roda a partida com a seed S forcando, em `D`, a candidata de rank 0.
     Joga ate o fim. Anota quem venceu.
  3. Roda a MESMA partida com a MESMA seed S forcando, em `D`, a
     candidata de rank 1. Joga ate o fim. Anota quem venceu.

O motor e determinístico dada a seed, entao os dois ramos sao IDENTICOS
ate `D` -- a unica diferenca e a acao forcada. Isso e *common random
numbers*: reduz a variancia da comparacao, porque tudo que nao e a
decisao esta pareado.

O rotulo do par e "o ramo 0 venceu?" do ponto de vista do jogador que
decidiu.

RUIDO -- a limitacao honesta, e ela e grande
--------------------------------------------
Um playout por ramo e uma amostra so de um processo com muita
aleatoriedade (compras, mulligan, decisoes seguintes). O rotulo de UM
par e barulhento; o sinal so aparece no agregado, sobre muitos pares.
Pares em que os dois ramos dao o MESMO vencedor nao carregam informacao
de preferencia e sao marcados `empate_de_desfecho` (guardados, mas o
treino pode descartar).

Custo: 2 partidas completas por par. Nao ha atalho -- e o preco do
rotulo honesto, e foi a escolha explicita do usuario entre este caminho
e a destilacao da busca (mais barata, sinal indireto).

Uso:
  python gerar_pares_contrafactuais.py --pares 40 --workers 4
  python gerar_pares_contrafactuais.py --pares 200 --workers 4 --append
"""
from __future__ import annotations

import argparse
import json
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

SAIDA = 'metrics/pares_contrafactuais.jsonl'


def _workers_padrao() -> int:
    """Default proporcional a maquina, com folga pro sistema.

    ACHADO (08/09/2026): esta sessao rodou o dia inteiro com
    `--workers 4` numa maquina de **16 nucleos** -- ~4x de desperdicio,
    por inercia de copiar o `--workers 4` dos exemplos do `CLAUDE.md`.
    O projeto EXIGE escolher workers explicitamente antes de cada lote;
    a regra continua valendo, mas o default deixa de ser um numero fixo
    que ninguem revisita."""
    import multiprocessing
    try:
        return max(1, multiprocessing.cpu_count() - 3)
    except Exception:
        return 4


def _um_ramo(deck_a, deck_b, seed: int, decisao_alvo: int, rank: int) -> dict:
    """Joga a partida inteira forcando, na decisao `decisao_alvo`, a
    candidata de `rank`. Devolve vencedor + o que foi capturado no seam."""
    random.seed(seed)
    match = OPTCGMatch(deck_a, deck_b)
    match.setup()
    # Liga o seam do coletor (ver `_select_action_via_search`).
    match._cf_contador = 0
    match._cf_forcar_em = decisao_alvo
    match._cf_rank = rank
    match._cf_forcada = None
    match._cf_estado = None
    match._cf_candidatas = None
    match._cf_lider = None
    match._cf_pos = None
    match._cf_captura_pos = None

    winner = None
    lado_decisor = None
    for turn_num in range(match.MAX_TURNS * 2):
        p = (match.state_a if match.state_a.is_first else match.state_b) \
            if turn_num % 2 == 0 \
            else (match.state_b if match.state_a.is_first else match.state_a)
        opp = match.state_b if p is match.state_a else match.state_a
        antes = match._cf_forcada
        r = match.play_turn(p, opp)
        if antes is None and match._cf_forcada is not None:
            lado_decisor = 'A' if p is match.state_a else 'B'
        if r:
            winner = r
            break

    return {
        'forcou': match._cf_forcada is not None,
        'winner': winner,
        'lado_decisor': lado_decisor,
        'estado': match._cf_estado,
        'candidatas': match._cf_candidatas,
        # Estado POS-LINHA de cada irma -- a parte que DIFERE entre elas
        # e a que o motor realmente avalia. Sem isto o par nao treina o
        # que esta em producao (erro da 1a versao, ver bloco 754).
        'pos': match._cf_pos,
        'leader': match._cf_lider,
        'decisoes_totais': match._cf_contador,
    }


def _um_par(task) -> dict | None:
    i, seed, decisao_alvo = task
    from gerar_selfplay_dataset import _load_deck_list

    deck_list = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(deck_list)), 2)
    _ca, deck_a = deck_list[ia]
    _cb, deck_b = deck_list[ib]

    try:
        r0 = _um_ramo(deck_a, deck_b, seed, decisao_alvo, 0)
        if not r0['forcou']:
            return {'descartado': 'decisao alvo nao existiu (partida curta ou <2 candidatas)'}
        r1 = _um_ramo(deck_a, deck_b, seed, decisao_alvo, 1)
        if not r1['forcou']:
            return {'descartado': 'ramo 1 nao forcou'}
    except Exception as e:
        return {'descartado': f'erro: {str(e)[:70]}'}

    # Coerencia: os dois ramos tem que ter visto a MESMA decisao (mesmo
    # estado e mesmas candidatas). Se divergirem, o determinismo quebrou e
    # o par nao vale -- checar isso e barato e evita treinar em lixo.
    if r0['estado'] != r1['estado'] or r0['candidatas'] != r1['candidatas']:
        return {'descartado': 'ramos viram decisoes diferentes (determinismo quebrou)'}
    pos = r0.get('pos') or []
    if len(pos) != 2 or any(v is None for v in pos):
        # Alguma irma terminou a linha em vitoria/derrota e saiu antes da
        # captura. Descarta em vez de treinar com vetor inventado.
        return {'descartado': 'sem estado pos-linha das duas irmas'}

    lado = r0['lado_decisor']
    ganhou0 = (r0['winner'] == lado) if r0['winner'] else None
    ganhou1 = (r1['winner'] == lado) if r1['winner'] else None
    if ganhou0 is None or ganhou1 is None:
        return {'descartado': 'algum ramo sem desfecho'}

    return {
        'seed': seed, 'decisao': decisao_alvo, 'leader': r0['leader'],
        'estado': r0['estado'], 'candidatas': r0['candidatas'],
        'pos': pos,
        'ganhou_ramo0': bool(ganhou0), 'ganhou_ramo1': bool(ganhou1),
        # Preferencia: 1 = a candidata de rank 0 e melhor, 0 = a de rank 1.
        # Só existe quando os desfechos DIFEREM.
        'preferencia': (None if ganhou0 == ganhou1 else (1 if ganhou0 else 0)),
        'empate_de_desfecho': ganhou0 == ganhou1,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pares', type=int, default=40)
    ap.add_argument('--seed', type=int, default=909)
    ap.add_argument('--workers', type=int, default=_workers_padrao())
    ap.add_argument('--decisao-max', type=int, default=14,
                    help='indice MINIMO da decisao alvo, sorteado em [0, N) -- '
                         'o seam forca na primeira decisao DISPUTADA a partir dele')
    ap.add_argument('--out', default=SAIDA)
    ap.add_argument('--append', action='store_true')
    args = ap.parse_args()

    rng = random.Random(args.seed)
    tasks = [(i, args.seed * 1_000_003 + i, rng.randrange(args.decisao_max))
             for i in range(args.pares)]
    print(f'[cf] {args.pares} pares (2 partidas cada = {args.pares * 2} partidas), '
          f'workers={args.workers}')

    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            res = list(ex.map(_um_par, tasks))
    else:
        res = [_um_par(t) for t in tasks]

    bons = [r for r in res if r and not r.get('descartado')]
    descartes: dict = {}
    for r in res:
        if r and r.get('descartado'):
            descartes[r['descartado']] = descartes.get(r['descartado'], 0) + 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('a' if args.append else 'w', encoding='utf-8') as fh:
        for r in bons:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')

    informativos = [r for r in bons if not r['empate_de_desfecho']]
    print(f'\n  pares validos:        {len(bons)}/{args.pares}')
    print(f'  INFORMATIVOS:         {len(informativos)} '
          f'({len(informativos)/len(bons):.1%} dos validos)' if bons else '')
    print(f'  empate de desfecho:   {len(bons) - len(informativos)}')
    for k, v in sorted(descartes.items(), key=lambda kv: -kv[1]):
        print(f'  descartado ({v}x): {k}')
    print(f'\n  -> {out}')
    if bons and len(informativos) / len(bons) < 0.25:
        print('\n  ATENCAO: poucos pares informativos. A maioria das decisoes')
        print('  nao muda o desfecho -- consistente com o achado do bloco 754')
        print('  (as trocas do modelo sao NEUTRAS). Pra treinar vai precisar')
        print('  de MUITO mais pares, ou de decisoes mais tardias/criticas.')


if __name__ == '__main__':
    main()
