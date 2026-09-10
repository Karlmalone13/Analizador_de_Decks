"""Conta acessos a disco em CADA fase (sem rastrear pilha -- a versao com
traceback engasgava). Pergunta do usuario: o setup da partida, que roda
POR PARTIDA no laco de duelo, toca disco?"""
import os, time, random

n = [0]
_stat, _exists = os.stat, os.path.exists
os.stat = lambda *a, **k: (n.__setitem__(0, n[0] + 1), _stat(*a, **k))[1]
os.path.exists = lambda *a, **k: (n.__setitem__(0, n[0] + 1), _exists(*a, **k))[1]

def main():
    marcos = {}
    t0 = time.perf_counter()
    from gerar_selfplay_dataset import _load_deck_list
    from optcg_engine.decision_engine import OPTCGMatch
    marcos['imports'] = (n[0], time.perf_counter() - t0)

    n[0] = 0; t = time.perf_counter()
    dl = _load_deck_list()
    marcos['_load_deck_list (1a vez)'] = (n[0], time.perf_counter() - t)

    n[0] = 0; t = time.perf_counter()
    dl2 = _load_deck_list()
    marcos['_load_deck_list (2a vez, cache)'] = (n[0], time.perf_counter() - t)

    rng = random.Random(909)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(909)
    n[0] = 0; t = time.perf_counter()
    m = OPTCGMatch(dl[ia][1], dl[ib][1]); m.setup()
    marcos['OPTCGMatch + setup (POR PARTIDA)'] = (n[0], time.perf_counter() - t)

    m.state_a.value_net_weight = 200.0
    m.state_b.value_net_weight = 200.0
    n[0] = 0; t = time.perf_counter()
    for turn in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if turn % 2 == 0 else (m.state_b if m.state_a.is_first else m.state_a)
        opp = m.state_b if p is m.state_a else m.state_a
        if m.play_turn(p, opp):
            break
    marcos['partida inteira'] = (n[0], time.perf_counter() - t)

    os.stat, os.path.exists = _stat, _exists
    print()
    print('{:<36}{:>10}{:>10}'.format('fase', 'acessos', 'tempo'))
    for k, (c, dt) in marcos.items():
        print('{:<36}{:>10,}{:>9.2f}s'.format(k, c, dt))

if __name__ == '__main__':
    main()
