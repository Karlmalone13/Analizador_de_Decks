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


COPIAS_TESTE = 2   # quantas copias da candidata entram (e quantas saem)


def _variante(cards: list[dict], cand: str, sair: list[str]) -> tuple[list[dict], list[str]]:
    """O deck com COPIAS_TESTE da candidata no lugar de cartas que pesam menos:
    primeiro as que a analise aponta em EXCESSO (`sair`, ex.: blocker demais);
    senao, as de maior custo. Mantem o tamanho do deck."""
    import suggest_card as sc
    db = sc._db()
    lider, resto = cards[0], [dict(c) for c in cards[1:]]
    custo = lambda code: db.get(code, {}).get('cost') or 0
    c_cand = custo(cand)
    teto = max(custo(c['code']) for c in resto)
    # Sai: 1) o que a analise aponta em EXCESSO; 2) carta de custo PARECIDO
    # com a candidata (troca dentro da mesma faixa da curva), com menos copias;
    # NUNCA a carta mais cara do deck -- medido 14/10: tirar a bomba (Krieg
    # OP15-008) derrubava 15% de vitoria em TODA candidata, e a carta que
    # entrava nao fazia diferenca nenhuma no numero.
    ordem = sorted((c for c in resto if c['code'] != cand),
                   key=lambda c: (0 if c['code'] in sair else 1,
                                  1 if custo(c['code']) >= teto else 0,
                                  abs(custo(c['code']) - c_cand), c['qty']))
    ordem += [c for c in resto if c['code'] == cand]
    saiu, falta = [], COPIAS_TESTE
    for c in ordem:
        if falta == 0:
            break
        tira = min(c['qty'], falta)
        c['qty'] -= tira
        falta -= tira
        saiu += [c['code']] * tira   # codigos: a tela busca a arte/nome no proprio deck
    novo = [c for c in ordem if c['qty'] > 0]
    ja = next((c for c in novo if c['code'] == cand), None)
    if ja:
        ja['qty'] = min(4, ja['qty'] + COPIAS_TESTE)
    else:
        novo.append({'code': cand, 'qty': COPIAS_TESTE})
    return [lider] + novo, saiu


PARTIDAS_TESTE = 160   # por variante: com 40 a diferenca ficava dentro do ruido


def testar_candidatas(cards: list[dict], candidatas: list[str], sair: list[str],
                      partidas: int = PARTIDAS_TESTE, seed: int = 7, workers: int = 4) -> dict:
    """Cada candidata e testada JOGANDO (pedido do usuario, 14/10/2026): o deck
    atual e cada variante jogam contra os MESMOS oponentes com as MESMAS
    sementes (numeros aleatorios comuns), entao a diferenca de vitoria e de
    dano vem da carta, nao da sorte do sorteio."""
    opps = _oponentes(partidas // 2, seed)
    decks = {'_base': (cards, [])}
    for cand in candidatas:
        decks[cand] = _variante(cards, cand, sair)
    tasks, dono = [], []
    for nome, (dk, _) in decks.items():
        for i, o in enumerate(opps):
            s = seed * 1_000_003 + i
            tasks += [(dk, o, True, s), (dk, o, False, s)]
            dono += [nome, nome]
    res: dict = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for k, r in enumerate(ex.map(_uma, tasks, chunksize=4)):
            if r:
                res.setdefault(dono[k], []).append(r)

    def resumo(rs):
        n = len(rs) or 1
        return {'n': len(rs), 'winrate': sum(r['win'] for r in rs) / n,
                'ataque': sum(r['causado'] for r in rs) / n, 'defesa': sum(r['sofrido'] for r in rs) / n}
    base = resumo(res.get('_base', []))
    out = {'base': base, 'candidatas': {}}
    for cand in candidatas:
        v = resumo(res.get(cand, []))
        # Margem (95%) da DIFERENCA de duas taxas de vitoria. CONTROLE medido
        # 14/10/2026: o MESMO deck so com a lista embaralhada variou de 42% a
        # 57% em 40 partidas -- a mudanca de uma carta precisa passar disso.
        p = (v['winrate'] + base['winrate']) / 2
        n = max(min(v['n'], base['n']), 1)
        margem = 1.96 * (2 * p * (1 - p) / n) ** 0.5
        d = v['winrate'] - base['winrate']
        veredito = 'ajuda' if d > margem else 'atrapalha' if d < -margem else 'sem diferença clara'
        out['candidatas'][cand] = {**v, 'sai': decks[cand][1], 'margem': margem, 'veredito': veredito,
                                   'd_winrate': v['winrate'] - base['winrate'],
                                   'd_ataque': v['ataque'] - base['ataque'],
                                   'd_defesa': base['defesa'] - v['defesa']}   # + = sofre menos
    return out


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
