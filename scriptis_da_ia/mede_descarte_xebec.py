"""Bloco 956 -- descartar o Xebec 10 (OP17-118) no custo de efeito e erro?

Ao vivo (10/10) o modelo trocou a escolha da regra (Stussy) pelo Xebec 10 no
custo do lider Xebec, duas vezes. Usuario: "e a bomba do deck ... nao e
aconselhavel descarta-lo por um proprio efeito".

Mede pelo RESULTADO: auto-jogo com o Q atual; nos turnos em que o Q descartou o
OP17-118 contra o que a regra escolheria, a MESMA foto do inicio do turno e
rejogada N vezes em dois ramos ate o fim -- (A) como o modelo (descarta o
Xebec 10) e (B) guardando o Xebec (a carta da regra). CONTROLE que pode falhar:
ramos A x A' (os dois descartando) -- a diferenca que sobrar ali e so sorte.
"""
import argparse, os, random, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

XEBEC, BOMBA = 'Rocks D Xebec', 'OP17-118'
OPONENTES = ['SABO RB', 'Enel P', 'Luffy RG', 'ace luffy']
_E = {'modo': 'detecta', 'viu': False}


def _instala():
    from optcg_engine import decision_engine as de
    if getattr(de, '_mede_xebec', False):
        return
    orig = de._q_escolhe_carta

    def wrap(me, opp, fam, cartas, padrao):
        r = orig(me, opp, fam, cartas, padrao)
        tem = [c for c in cartas if getattr(c, 'code', '') == BOMBA]
        if not tem or padrao is None or getattr(me.leader, 'code', '') != 'OP17-039':
            return r
        if _E['modo'] == 'detecta' and r is not None and r.code == BOMBA and padrao.code != BOMBA:
            _E['viu'] = True
        elif _E['modo'] == 'guarda' and r is not None and r.code == BOMBA and padrao.code != BOMBA:
            return padrao
        elif _E['modo'] == 'joga_fora':
            return tem[0]
        return r
    de._q_escolhe_carta = wrap
    de._mede_xebec = True


def _acha(seed):
    from optcg_engine import sim_bridge as sb
    from optcg_engine.decision_engine import OPTCGMatch
    from gerar_selfplay_dataset import _quem_joga, _foto
    _instala()
    rng = random.Random(seed)
    random.seed(seed)
    m = OPTCGMatch(sb.load_sim_deck(XEBEC), sb.load_sim_deck(rng.choice(OPONENTES)))
    m.setup()
    achados = []
    for t in range(m.MAX_TURNS * 2):
        p, o = _quem_joga(m, t)
        foto = _foto(m)
        _E['modo'], _E['viu'] = 'detecta', False
        try:
            r = m.play_turn(p, o)
        except Exception:
            break
        if _E['viu']:
            achados.append((foto, t))
        if r:
            break
    return achados


def _ramo(args):
    foto, t, modo, seed = args
    from copy import deepcopy
    from gerar_selfplay_dataset import _quem_joga
    _instala()
    random.seed(seed)
    m = deepcopy(foto)
    # As proximas compras sao desconhecidas: embaralha o resto dos dois decks.
    # Sem isto o ramo e DETERMINISTICO -- 1a rodada deu A e A' identicos
    # (64/132 e 64/132): cada posicao valia uma partida so.
    random.shuffle(m.state_a.deck)
    random.shuffle(m.state_b.deck)
    p, o = _quem_joga(m, t)
    lado = 'A' if p is m.state_a else 'B'
    try:
        _E['modo'] = modo
        r = m.play_turn(p, o)
        _E['modo'] = 'livre'
        for t2 in range(t + 1, m.MAX_TURNS * 2):
            if r:
                break
            p2, o2 = _quem_joga(m, t2)
            r = m.play_turn(p2, o2)
    except Exception:
        return None
    return (r == lado) if r in ('A', 'B') else None


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=30)
    ap.add_argument('--ramos', type=int, default=12)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--seed', type=int, default=956)
    a = ap.parse_args()
    with ProcessPoolExecutor(a.workers) as ex:
        pos = [x for r in ex.map(_acha, [a.seed * 1_000_003 + i for i in range(a.partidas)]) for x in r]
        print(f'posicoes (Q descartou o Xebec 10 contra a regra): {len(pos)}', flush=True)
        tarefas = []
        for k, (foto, t) in enumerate(pos):
            for j in range(a.ramos):
                modo = ('joga_fora', 'guarda', 'joga_fora')[j % 3]
                rot = ('A descarta Xebec', 'B guarda Xebec', "A' descarta (controle)")[j % 3]
                tarefas.append((rot, (foto, t, modo, a.seed * 7919 + k * 1000 + j)))
        res = list(ex.map(_ramo, [x for _, x in tarefas]))
    from collections import defaultdict
    g = defaultdict(lambda: [0, 0])
    for (rot, _), r in zip(tarefas, res):
        if r is None:
            continue
        g[rot][0] += int(r); g[rot][1] += 1
    for k in sorted(g):
        v, n = g[k]
        print(f'{k:28s} {v:4d}/{n:<4d} = {100 * v / max(n, 1):5.1f}%')
