"""
gerar_selfplay_dataset.py
=========================
Gera o dataset de AUTO-JOGO que treina a funcao de valor
(`optcg_engine/value_net.py` -> `treinar_value.py`).

Decisao do usuario (08/09/2026): caminho HIBRIDO, atras de flag.

O QUE ISTO PRODUZ, E POR QUE E DIFERENTE DO QUE JA FOI REPROVADO
-----------------------------------------------------------------
Uma linha por ESTADO visitado, com:
  - `feats`  -- vetor de `value_net.state_features(p, opp)` (fonte UNICA,
                a mesma que o motor monta em runtime)
  - `win`    -- 1 se o jogador daquele estado GANHOU a partida, 0 se nao
  - `leader` -- codigo do lider, usado SO como GRUPO na validacao
                (GroupKFold), NUNCA como feature

O rotulo e o RESULTADO DA PARTIDA, nao a escolha de um humano. Por isso
este caminho nao esbarra no que matou a clonagem de comportamento dos
blocos 680-706: o dado e ilimitado (o motor gera) e vem da propria
politica que joga, entao nao ha *distribution shift* por construcao.

O `leader` fora das features e deliberado, e vem de um defeito REAL: o
bloco 702 achou one-hot de lider em `policy.py:98` com split por partida
-- validacao que nunca poderia detectar falha de generalizacao pra deck
novo. Aqui o lider so agrupa o holdout.

PARALELISMO E REPRODUTIBILIDADE
-------------------------------
`--workers N` (convencao obrigatoria do projeto pra simulacao em lote).
Cada partida usa seed PROPRIA derivada por indice (`seed * 1_000_003 + i`)
-- nunca um `random.seed()` unico encadeado entre partidas, que quebra a
reprodutibilidade entre sequencial e paralelo (achado real do bloco 481).

Uso:
  python gerar_selfplay_dataset.py --n 200 --workers 4
  python gerar_selfplay_dataset.py --n 1000 --workers 8 --out metrics/selfplay_dataset.jsonl
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

# Reprodutibilidade real (mesmo preambulo de baseline_metrics.py):
# PYTHONHASHSEED precisa existir antes do interpretador subir.
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    raise SystemExit(subprocess.call([sys.executable] + sys.argv))

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

from optcg_engine.decision_engine import (OPTCGMatch, build_real_deck,
                                          load_cards_db, validar_deck)
from optcg_engine import value_net

OUT_DEFAULT = 'metrics/selfplay_dataset.jsonl'

_DECK_CACHE: list | None = None


def _load_deck_list(limite: int = 24) -> list:
    """Decks REAIS de torneio (`decklists_raw.csv`), mesma fonte de
    `audit_replay.py`. Variedade de lider importa aqui mais que em
    qualquer outro script: o objetivo registrado do projeto e jogar bem
    com QUALQUER deck, e a validacao agrupa POR LIDER -- com poucos
    lideres o GroupKFold nao tem o que separar."""
    global _DECK_CACHE
    if _DECK_CACHE is not None:
        return _DECK_CACHE
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    deck_list = []
    vistos = set()
    for url, name in urls.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if not result:
            continue
        leader, cards, start_stage = result
        valido, _erros = validar_deck(leader, cards, cards_db)
        if not valido or len(cards) < 40:
            continue
        code = getattr(leader, 'code', None) or str(name)
        # 1 deck por lider: o dataset ganha mais com 24 lideres distintos
        # do que com 24 listas do mesmo lider (o holdout e por lider).
        if code in vistos:
            continue
        vistos.add(code)
        deck_list.append((code, (leader, cards, start_stage)))
        if len(deck_list) >= limite:
            break
    _DECK_CACHE = deck_list
    return deck_list


def _run_one_match(task) -> list:
    """Roda 1 partida de auto-jogo e devolve as amostras dela.

    Cada processo carrega o proprio banco -- sem estado global
    compartilhado, igual `audit_replay._run_one_match`."""
    # 6o elemento OPCIONAL (bloco 767): epsilon de EXPLORACAO.
    if len(task) == 7:
        i, match_seed, peso, modelo_path, geracao, eps, pos_acao = task
    else:
        i, match_seed, peso, modelo_path, geracao = task
        eps, pos_acao = 0.0, False
    deck_list = _load_deck_list()
    rng = random.Random(match_seed)
    idx_a, idx_b = rng.sample(range(len(deck_list)), 2)
    code_a, deck_a = deck_list[idx_a]
    code_b, deck_b = deck_list[idx_b]

    # O motor usa `random.*` GLOBAL pra amostragem Monte Carlo/decisoes
    # internas -- precisa da mesma seed por partida, nao so o rng.sample
    # acima (que so escolhe o matchup).
    random.seed(match_seed)

    try:
        match = OPTCGMatch(deck_a, deck_b)
        match.setup()
    except Exception:
        return []

    # ── O PONTO DA ITERACAO ─────────────────────────────────────────────
    # As partidas sao jogadas COM o modelo da geracao atual ligado (nos
    # dois lados). E o que distingue este laco da tentativa de tiro unico
    # do bloco 753: la o dataset veio de partidas do motor SEM o modelo, e
    # o modelo foi usado COM ele -- treino e uso em distribuicoes
    # diferentes. Aqui cada geracao aprende sobre os estados que ela mesma
    # produz, que e a correcao classica desse problema.
    if peso:
        for estado in (match.state_a, match.state_b):
            estado.value_net_weight = peso
            estado.value_net_path = modelo_path

    # EXPLORACAO (bloco 767, pedido do usuario: "ele tem que ser capaz de
    # aprender e descobrir e nao so regular"). Sem isto o auto-jogo e um LACO
    # FECHADO: joga sempre a linha que ja considera melhor, entao o dataset so
    # contem o que ele ja fazia e o modelo aprende a prever o resultado das
    # PROPRIAS escolhas -- reforca, nao descobre. Com eps > 0 ele as vezes
    # joga fora do topo e VE no que deu, que e como se descobre que uma linha
    # preterida era boa.
    if eps:
        match._explora_eps = eps

    # CORPUS POS-ACAO (bloco 769). Com o ML como AVALIADOR ele julga a
    # posicao logo APOS a acao, nao no fim do turno -- e o corpus tem que ser
    # gravado nesse MESMO ponto, senao treino e uso ficam em distribuicoes
    # diferentes (o erro do bloco 753). Rende MUITO mais estado por partida:
    # varias acoes por turno, contra um estado por turno no modo antigo.
    if pos_acao:
        match._ml_captura = []

    amostras = []
    winner = None
    for turn_num in range(match.MAX_TURNS * 2):
        p = (match.state_a if match.state_a.is_first else match.state_b) \
            if turn_num % 2 == 0 \
            else (match.state_b if match.state_a.is_first else match.state_a)
        opp = match.state_b if p is match.state_a else match.state_a
        try:
            result = match.play_turn(p, opp)
        except Exception:
            # Partida que estoura no meio ainda tem estados validos ate
            # aqui, mas NAO tem rotulo confiavel -- descarta inteira.
            return []

        # Estado no FIM do meu turno: exatamente o ponto que
        # `_evaluate_state_v2` julga numa linha simulada. Treinar no mesmo
        # ponto em que o modelo vai ser consultado e o que mantem treino e
        # uso na MESMA distribuicao.
        lado = 'A' if p is match.state_a else 'B'
        amostras.append({
            'match': i,
            'side': lado,
            'leader': code_a if lado == 'A' else code_b,
            'turn': turn_num,
            # `gen` = qual geracao do modelo jogou esta partida. Fica no
            # dado (nao so no log) porque o treino pode querer pesar as
            # geracoes recentes, e porque sem isso e impossivel saber
            # depois de que politica veio cada estado.
            'gen': geracao,
            # Grava o SUPERCONJUNTO rico (49). O treino escolhe o
            # subconjunto -- assim o mesmo corpus serve pros dois modelos do
            # A/B e a comparacao isola a VISAO, nao o volume de dado
            # (bloco 764).
            'feats': value_net.state_features(
                p, opp, nomes=value_net.FEATURE_NAMES_V3),
        })

        if result:
            winner = result
            break

    if winner is None:
        # Sem desfecho (estourou MAX_TURNS) -- sem rotulo, fora do dataset.
        # Contado no resumo pra a taxa ficar visivel, nao escondida.
        return [{'_sem_desfecho': True, 'match': i}]

    if pos_acao:
        # Troca os estados de FIM DE TURNO pelos estados POS-ACAO que o
        # `_ml_captura` recolheu -- e o ponto onde o ML avaliador e de fato
        # consultado. O rotulo continua sendo quem ganhou a PARTIDA.
        amostras = [{'match': i, 'side': d['lado'],
                     'leader': code_a if d['lado'] == 'A' else code_b,
                     'turn': -1, 'gen': geracao, 'feats': d['feats']}
                    for d in (getattr(match, '_ml_captura', None) or [])]
    for a in amostras:
        a['win'] = 1 if a['side'] == winner else 0
    return amostras


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n', type=int, default=200, help='partidas de auto-jogo')
    ap.add_argument('--seed', type=int, default=77)
    ap.add_argument('--workers', type=int, default=__import__('multiprocessing').cpu_count() - 3,
                    help='processos paralelos (o projeto EXIGE escolher explicitamente)')
    ap.add_argument('--decks', type=int, default=24, help='quantos lideres distintos')
    ap.add_argument('--out', default=OUT_DEFAULT)
    ap.add_argument('--weight', type=float, default=0.0,
                    help='peso do valor aprendido nas partidas GERADAS '
                         '(0 = motor sem modelo, geracao 0)')
    ap.add_argument('--model', default=None,
                    help='modelo usado pra gerar (default: o de value_net.MODEL_PATH)')
    ap.add_argument('--pos-acao', dest='pos_acao', action='store_true',
                    help='grava os estados POS-ACAO (o ponto onde o ML '
                         'AVALIADOR e consultado) em vez do fim do turno. '
                         'Rende varios estados por turno. Obrigatorio pra '
                         'treinar o modelo do ML_AVALIADOR (bloco 769)')
    ap.add_argument('--explorar', type=float, default=0.0,
                    help='epsilon de EXPLORACAO (0.0-1.0): em epsilon das '
                         'decisoes joga FORA do topo, pra o dataset conter '
                         'linhas que o bot nao escolheria sozinho. Default 0.0 '
                         '(guloso, comportamento antigo). Tipico: 0.10-0.20. '
                         'NAO usar em duelo -- la mediria ruido (bloco 767)')
    ap.add_argument('--gen', type=int, default=0, help='numero da geracao, gravado em cada amostra')
    ap.add_argument('--append', action='store_true',
                    help='ACRESCENTA ao arquivo em vez de sobrescrever -- '
                         'o corpus cresce a cada rodada')
    args = ap.parse_args()

    tasks = [(i, args.seed * 1_000_003 + i, args.weight, args.model, args.gen,
              args.explorar, args.pos_acao)
             for i in range(args.n)]
    print(f'[selfplay] {args.n} partidas, seed={args.seed}, workers={args.workers}, '
          f'gen={args.gen}, peso={args.weight}, explorar={args.explorar}')

    resultados = []
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for k, r in enumerate(ex.map(_run_one_match, tasks), 1):
                resultados.append(r)
                if k % 25 == 0:
                    print(f'  ... {k}/{args.n}')
    else:
        for k, t in enumerate(tasks, 1):
            resultados.append(_run_one_match(t))
            if k % 25 == 0:
                print(f'  ... {k}/{args.n}')

    linhas, sem_desfecho, vazias = [], 0, 0
    for r in resultados:
        if not r:
            vazias += 1
            continue
        if len(r) == 1 and r[0].get('_sem_desfecho'):
            sem_desfecho += 1
            continue
        linhas.extend(r)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('a' if args.append else 'w', encoding='utf-8') as fh:
        for a in linhas:
            fh.write(json.dumps(a, ensure_ascii=False) + '\n')

    lideres = sorted({a['leader'] for a in linhas})
    vitorias = sum(a['win'] for a in linhas)
    print(f'\n[selfplay] {len(linhas)} estados de {args.n - sem_desfecho - vazias} '
          f'partidas com desfecho -> {out}')
    print(f'  partidas sem desfecho (MAX_TURNS): {sem_desfecho}')
    print(f'  partidas descartadas por erro:     {vazias}')
    print(f'  lideres distintos:                 {len(lideres)}')
    print(f'  taxa de rotulo positivo:           {vitorias / max(1, len(linhas)):.1%}')


if __name__ == '__main__':
    main()
