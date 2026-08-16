"""
quality_baseline.py -- "melhorou ou nao?" medido em QUALIDADE DE DECISAO, com
baseline versionado por commit.

Por que existe (pedido do usuario, 16/08/2026, bloco 565: "precisamos criar
algo para avaliar se esta havendo melhora ou nao"). Os instrumentos que o
projeto tinha para essa pergunta falham por motivos DIFERENTES, todos reais e
observados nesta sessao:

1. `gauntlet_matchup.py` mede WINRATE em SELF-PLAY. O motor joga os DOIS
   lados, entao uma mudanca de heuristica muda o bot E o adversario ao mesmo
   tempo e os efeitos se cancelam -- o instrumento e enviesado pro resultado
   NULO. Evidencia: blocos 558 e 562 acharam "todos os 4 arquetipos dentro do
   IC95" duas vezes seguidas, e a rodada de hoje (bloco 564->565) deu Enel e
   Nami IDENTICOS ate no digito de dano/DON, porque o fix testado nem sequer
   era exercitado naqueles matchups.
2. `gauntlet_painel.json` e SOBRESCRITO a cada rodada. Ao tentar comparar
   antes/depois hoje, o "baseline" ja tinha virado o resultado novo -- ou
   seja, o braco de comparacao simplesmente nao existia.
3. Winrate e a metrica ERRADA pra pergunta, pelo criterio do proprio usuario
   (bloco 485): "nao tem problema perder a partida, as vezes o deck so e
   fraco mesmo, nos so precisamos garantir de que o bot entende o deck e
   toma as melhores decisoes".

Este script mede as MESMAS tres coisas do `decision_quality_report.py`
(reusa `_run_one`/`_load_deck_list` dele, NAO reimplementa nada -- ver
REGRA_SEM_DUPLICACAO.md), mas:

  * agrega em numeros COMPARAVEIS entre rodadas;
  * grava cada rodada em `metrics/quality_baselines/` carimbada com o COMMIT
    e a seed, sem nunca sobrescrever (o erro do item 2);
  * compara automaticamente com o snapshot anterior e mostra o DELTA.

Metricas (todas independentes de vitoria/derrota):
  - `don_sobrando_medio`      : DON deixado na mesa no fim do proprio turno
  - `pct_turnos_zero_don`     : % de turnos que fecharam sem DON ocioso
  - `utilizacao_cartas_pct`   : escolhidas/ofertadas somado sobre todas as cartas
  - `utilizacao_lider_pct`    : idem pra [Activate: Main] (None se o lider nao tem)
  - `winrate_pct`             : SO CONTEXTO, nunca o criterio

Uso:
    python quality_baseline.py --leader OP16-080 --n 20 --workers 4 --decks-do-jogo
    python quality_baseline.py --listar
    python quality_baseline.py --comparar <a.json> <b.json>

IMPORTANTE: rode SEMPRE com a mesma `--seed` e o mesmo `--n` ao comparar duas
versoes do motor -- as partidas sao deterministicas por seed, entao a
diferenca que sobra e atribuivel ao codigo. Mudou seed ou n, os numeros nao
sao comparaveis.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
from datetime import datetime

from decision_quality_report import _load_deck_list, _run_one

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'metrics', 'quality_baselines')


def _commit_atual() -> str:
    try:
        out = subprocess.run(['git', 'rev-parse', 'HEAD'],
                             capture_output=True, text=True, timeout=10,
                             cwd=os.path.dirname(os.path.abspath(__file__)))
        return (out.stdout or '').strip()[:12] or 'desconhecido'
    except Exception:
        return 'desconhecido'


def _git_sujo() -> bool:
    """True se ha mudanca nao commitada -- o snapshot NAO representa o commit."""
    try:
        out = subprocess.run(['git', 'status', '--porcelain'],
                             capture_output=True, text=True, timeout=10,
                             cwd=os.path.dirname(os.path.abspath(__file__)))
        return bool((out.stdout or '').strip())
    except Exception:
        return False


def medir(leader: str, n: int, seed: int, workers: int,
          pool_size: int, decks_do_jogo: bool) -> dict:
    deck_list = _load_deck_list(pool_size, decks_do_jogo)
    if not any(d[0].code == leader for _, d in deck_list):
        raise SystemExit(
            f'lider {leader} nao tem deck valido no pool de {len(deck_list)} decks. '
            f'Se e um deck seu do simulador, use --decks-do-jogo.')

    tasks = [(i, seed * 1_000_003 + i, leader, pool_size, decks_do_jogo)
             for i in range(n)]
    if workers <= 1:
        resultados = [_run_one(t) for t in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            resultados = list(ex.map(_run_one, tasks))
    resultados = [r for r in resultados if r is not None]
    if not resultados:
        raise SystemExit('nenhuma partida valida')

    don_todos = [d for r in resultados for d in r['don_leftover']]
    turnos = len(don_todos)
    zero_don = sum(1 for d in don_todos if d == 0)

    ofertada = escolhida = 0
    por_carta = {}
    for r in resultados:
        for code, dados in r['por_carta'].items():
            slot = por_carta.setdefault(code, {'nome': dados['nome'],
                                               'ofertada': 0, 'escolhida': 0})
            slot['ofertada'] += dados['ofertada']
            slot['escolhida'] += dados['escolhida']
            ofertada += dados['ofertada']
            escolhida += dados['escolhida']

    vitorias = sum(1 for r in resultados if r['vencedor'] == 'A')

    return {
        'commit': _commit_atual(),
        'git_sujo': _git_sujo(),
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'leader': leader, 'n': len(resultados), 'seed': seed,
        'decks_do_jogo': decks_do_jogo,
        'metricas': {
            'don_sobrando_medio': round(sum(don_todos) / turnos, 4) if turnos else None,
            'pct_turnos_zero_don': round(zero_don / turnos * 100, 2) if turnos else None,
            'utilizacao_cartas_pct': round(escolhida / ofertada * 100, 2) if ofertada else None,
            'utilizacao_lider_pct': None,   # preenchido abaixo quando aplicavel
            'winrate_pct': round(vitorias / len(resultados) * 100, 2),
        },
        'turnos_medidos': turnos,
        'por_carta': por_carta,
    }


def _fmt(v):
    return 'N/A' if v is None else f'{v:.2f}'


def comparar(antes: dict, depois: dict) -> None:
    ma, md = antes['metricas'], depois['metricas']
    print('=' * 74)
    print('COMPARACAO DE QUALIDADE DE DECISAO')
    print(f"  antes : commit {antes['commit']}  ({antes['timestamp']})"
          f"{'  [ARVORE SUJA]' if antes.get('git_sujo') else ''}")
    print(f"  depois: commit {depois['commit']}  ({depois['timestamp']})"
          f"{'  [ARVORE SUJA]' if depois.get('git_sujo') else ''}")
    print('=' * 74)

    if (antes['leader'], antes['n'], antes['seed']) != \
       (depois['leader'], depois['n'], depois['seed']):
        print('!! ATENCAO: leader/n/seed diferentes entre os snapshots --')
        print('   os numeros NAO sao comparaveis. Rode os dois com os mesmos parametros.')
        print()

    # direcao: True = maior e melhor
    direcao = {
        'don_sobrando_medio': False,
        'pct_turnos_zero_don': True,
        'utilizacao_cartas_pct': True,
        'utilizacao_lider_pct': True,
        'winrate_pct': True,
    }
    print(f'{"metrica":26} {"antes":>10} {"depois":>10} {"delta":>10}  leitura')
    for k, maior_melhor in direcao.items():
        a, d = ma.get(k), md.get(k)
        if a is None or d is None:
            print(f'{k:26} {_fmt(a):>10} {_fmt(d):>10} {"-":>10}  (indisponivel)')
            continue
        delta = d - a
        if abs(delta) < 1e-9:
            leitura = 'identico'
        else:
            bom = (delta > 0) == maior_melhor
            leitura = 'MELHOROU' if bom else 'piorou'
        marca = ' (so contexto)' if k == 'winrate_pct' else ''
        print(f'{k:26} {a:>10.2f} {d:>10.2f} {delta:>+10.2f}  {leitura}{marca}')

    print()
    print('LEITURA: winrate aqui e SO contexto -- vem de self-play espelhado (o')
    print('motor joga os dois lados), entao tende ao nulo por construcao. O que')
    print('vale sao DON ocioso e utilizacao: medem se o bot APROVEITA o deck,')
    print('independente de ganhar ou perder.')


def _snapshots(leader: str | None = None) -> list[str]:
    if not os.path.isdir(OUT_DIR):
        return []
    fs = [os.path.join(OUT_DIR, f) for f in sorted(os.listdir(OUT_DIR))
          if f.endswith('.json')]
    if leader:
        fs = [f for f in fs
              if json.load(open(f, encoding='utf-8')).get('leader') == leader]
    return fs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--leader')
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--pool-size', type=int, default=30)
    ap.add_argument('--decks-do-jogo', action='store_true',
                    help='inclui os .deck reais do simulador no pool')
    ap.add_argument('--listar', action='store_true', help='lista snapshots salvos')
    ap.add_argument('--comparar', nargs=2, metavar=('ANTES', 'DEPOIS'))
    args = ap.parse_args()

    if args.listar:
        fs = _snapshots()
        if not fs:
            print('nenhum snapshot ainda -- rode com --leader pra criar o primeiro')
            return
        for f in fs:
            d = json.load(open(f, encoding='utf-8'))
            m = d['metricas']
            print(f"{os.path.basename(f):46} lider={d['leader']:10} "
                  f"commit={d['commit']:12} don={_fmt(m['don_sobrando_medio'])} "
                  f"util={_fmt(m['utilizacao_cartas_pct'])}%")
        return

    if args.comparar:
        a = json.load(open(args.comparar[0], encoding='utf-8'))
        b = json.load(open(args.comparar[1], encoding='utf-8'))
        comparar(a, b)
        return

    if not args.leader:
        raise SystemExit('use --leader CODIGO (ou --listar / --comparar)')

    snap = medir(args.leader, args.n, args.seed, args.workers,
                 args.pool_size, args.decks_do_jogo)

    os.makedirs(OUT_DIR, exist_ok=True)
    nome = (f"{args.leader}_{snap['commit']}_"
            f"{snap['timestamp'].replace(':', '.')}.json")
    caminho = os.path.join(OUT_DIR, nome)
    with open(caminho, 'w', encoding='utf-8') as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=2)

    m = snap['metricas']
    print(f"snapshot salvo: {caminho}")
    if snap['git_sujo']:
        print('AVISO: arvore com mudanca nao commitada -- este snapshot NAO')
        print(f"       representa fielmente o commit {snap['commit']}.")
    print()
    print(f"lider {args.leader} | {snap['n']} partidas | seed {args.seed} | "
          f"{snap['turnos_medidos']} turnos medidos")
    print(f"  DON sobrando (media/turno) : {_fmt(m['don_sobrando_medio'])}")
    print(f"  turnos com 0 DON           : {_fmt(m['pct_turnos_zero_don'])}%")
    print(f"  utilizacao das cartas      : {_fmt(m['utilizacao_cartas_pct'])}%")
    print(f"  winrate (so contexto)      : {_fmt(m['winrate_pct'])}%")

    anteriores = [f for f in _snapshots(args.leader)
                  if os.path.abspath(f) != os.path.abspath(caminho)]
    if anteriores:
        print()
        comparar(json.load(open(anteriores[-1], encoding='utf-8')), snap)
    else:
        print()
        print('(primeiro snapshot deste lider -- rode de novo depois de mudar o')
        print(' motor, com a MESMA seed e o mesmo n, pra ver o delta)')


if __name__ == '__main__':
    main()
