"""Ataque e Defesa MEDIDOS jogando, nao estimados por formula (14/10/2026).

Pedido do usuario ao ver Krieg com Ataque 90 e Defesa 58: a formula de
`deck_axes.py` usava pesos escolhidos a mao, ignorava o efeito do lider (o
-2000 em todos os personagens do oponente do Krieg e o motor defensivo dele) e
inflava ataque com personagem barato. Agora o MOTOR joga o deck contra o meta
e mede o que aconteceu:

  * ATAQUE = dano que o deck CAUSA por turno proprio      (mais = melhor)
  * DEFESA = dano que o deck SOFRE por turno do oponente  (menos = melhor)

Oponentes: decks de torneio sorteados na proporcao do meta (estratificado por
lider), e cada confronto jogado DUAS vezes, comecando e indo em segundo, pra
tirar o peso de quem comeca. A nota 0-100 e a posicao do deck entre os 184
decks de torneio medidos do MESMO jeito (`metrics/eixos_medidos_meta.json`,
gerado por `python measure_axes.py --base`).

Isto captura efeito do lider, sinergia e tudo que a formula nao via -- e o
motor jogando. Limite honesto: mede o deck nas maos do BOT, nao de um humano.
"""
from __future__ import annotations

import json
import os
import random
import sys
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(AQUI, 'metrics', 'eixos_medidos_meta.json')
PARTIDAS = 40          # por deck analisado (20 oponentes x comecando/segundo)
PARTIDAS_BASE = 20     # por deck do meta, na base de comparacao


def _pool_meta() -> list[tuple[str, list[dict]]]:
    """[(lider, [{code, qty}...])] dos decks de torneio."""
    import suggest_card as sc
    lideres, torneio = sc._torneio()
    return [(lideres[u], [{'code': lideres[u], 'qty': 1}] +
             [{'code': c, 'qty': q} for c, q in d.items()])
            for u, d in torneio.items() if u in lideres]


def _oponentes(n: int, seed: int) -> list[list[dict]]:
    """n decks do meta, ESTRATIFICADOS: cada lider recebe partidas na
    proporcao da presenca dele nos torneios (nao sorteio livre)."""
    pool = _pool_meta()
    por_lider: dict = {}
    for lider, cards in pool:
        por_lider.setdefault(lider, []).append(cards)
    rng = random.Random(seed)
    cotas = sorted(((len(v) / len(pool) * n, k) for k, v in por_lider.items()), reverse=True)
    out = []
    for frac, k in cotas:
        out += [rng.choice(por_lider[k]) for _ in range(int(frac))]
    for _, k in cotas:                       # sobra do arredondamento: os maiores
        if len(out) >= n:
            break
        out.append(rng.choice(por_lider[k]))
    return out[:n]


def _uma(task):
    """Worker: 1 partida. `primeiro` = o deck analisado comeca."""
    cards, opp, primeiro, seed = task
    import simulation_worker as sw
    random.seed(seed)
    try:
        a = sw.load_deck(cards)
        b = sw.load_deck(opp)
        from optcg_engine.decision_engine import OPTCGMatch
        m = OPTCGMatch(a, b, hide_opponent_info=True)
        m.state_a.is_first, m.state_b.is_first = primeiro, not primeiro
        r = m.simulate()
    except Exception:
        return None
    turnos = max(int(r.get('turns') or 0), 1)
    meus = (turnos + (1 if primeiro else 0)) // 2 or 1
    deles = turnos - meus or 1
    return {'win': r.get('winner') == 'A', 'causado': (r.get('dmg_a') or 0) / meus,
            'sofrido': (r.get('dmg_b') or 0) / deles, 'turnos': turnos}


def medir(cards: list[dict], partidas: int = PARTIDAS, seed: int = 1, workers: int = 4) -> dict:
    opps = _oponentes(partidas // 2, seed)
    tasks = []
    for i, o in enumerate(opps):
        s = seed * 1_000_003 + i
        tasks += [(cards, o, True, s), (cards, o, False, s)]   # pareado: mesma semente
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            res = [r for r in ex.map(_uma, tasks) if r]
    else:
        res = [r for r in map(_uma, tasks) if r]
    if not res:
        return {'n': 0}
    n = len(res)
    return {'n': n,
            'ataque': sum(r['causado'] for r in res) / n,
            'defesa': sum(r['sofrido'] for r in res) / n,
            'winrate': sum(r['win'] for r in res) / n,
            'turnos': sum(r['turnos'] for r in res) / n}


def nota(valor: float, base: list[float], menor_e_melhor: bool = False) -> int:
    """Posicao 0-100 entre os decks do meta (percentil)."""
    if not base:
        return 50
    b = sorted(base)
    p = bisect_left(b, valor) / len(b)
    return round(100 * (1 - p if menor_e_melhor else p))


def com_nota(medida: dict) -> dict:
    try:
        base = json.load(open(BASE_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        base = None
    if not base or not medida.get('n'):
        return {**medida, 'nota_ataque': None, 'nota_defesa': None}
    return {**medida,
            'nota_ataque': nota(medida['ataque'], base['ataque']),
            'nota_defesa': nota(medida['defesa'], base['defesa'], menor_e_melhor=True),
            'n_base': len(base['ataque'])}


def gerar_base(workers: int = 4) -> None:
    """Mede os 184 decks de torneio do mesmo jeito -> base da nota."""
    pool = _pool_meta()
    out = {'ataque': [], 'defesa': [], 'winrate': [], 'decks': []}
    # UM pool de processos pra tudo: abrir um por deck custava ~8s de
    # carregamento de modelo por deck (medido 14/10/2026).
    tasks, dono = [], []
    for i, (lider, cards) in enumerate(pool):
        seed = 10_000 + i
        for j, o in enumerate(_oponentes(PARTIDAS_BASE // 2, seed)):
            s = seed * 1_000_003 + j
            tasks += [(cards, o, True, s), (cards, o, False, s)]
            dono += [i, i]
    por_deck: dict = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for k, r in enumerate(ex.map(_uma, tasks, chunksize=8)):
            if r:
                por_deck.setdefault(dono[k], []).append(r)
            if k % 200 == 0:
                print(f'{k}/{len(tasks)} partidas', flush=True)
    for i, (lider, cards) in enumerate(pool):
        res = por_deck.get(i) or []
        if not res:
            continue
        n = len(res)
        m = {'n': n, 'ataque': sum(r['causado'] for r in res) / n,
             'defesa': sum(r['sofrido'] for r in res) / n,
             'winrate': sum(r['win'] for r in res) / n,
             'turnos': sum(r['turnos'] for r in res) / n}
        out['ataque'].append(m['ataque'])
        out['defesa'].append(m['defesa'])
        out['winrate'].append(m['winrate'])
        out['decks'].append({'lider': lider, **m})
        print(f'[{i + 1}/{len(pool)}] {lider} ataque {m["ataque"]:.2f} defesa {m["defesa"]:.2f} '
              f'wr {m["winrate"]:.0%}', flush=True)
    os.makedirs(os.path.dirname(BASE_PATH), exist_ok=True)
    json.dump(out, open(BASE_PATH, 'w', encoding='utf-8'), ensure_ascii=False)
    print('base salva em', BASE_PATH)


if __name__ == '__main__':
    if '--base' in sys.argv:
        gerar_base()
    else:
        print(json.dumps(com_nota(medir(json.loads(sys.argv[1]))), indent=1))
