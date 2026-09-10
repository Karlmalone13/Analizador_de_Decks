"""Quem toca DISCO durante a partida? (pista do usuario, bloco 759)
Perfil mostrou 5.650 nt.stat somando 1,154s numa UNICA partida, a ~204us
cada -- lento demais pra stat comum. Banco estatico nao deveria tocar
disco durante a partida."""
import os, random, collections, traceback

_orig_stat = os.stat
_orig_exists = os.path.exists
cont = collections.Counter()

def _quem():
    for fr in traceback.extract_stack()[-14:-1][::-1]:
        f = fr.filename.replace(chr(92), "/")
        if ("/os.py" in f or "genericpath" in f or "/importlib" in f
                or "stat_trace" in f):
            continue
        return f.split("/")[-1] + ":" + str(fr.lineno) + " (" + fr.name + ")"
    return "?"

def stat_espiao(*a, **k):
    cont[_quem()] += 1
    return _orig_stat(*a, **k)

def exists_espiao(*a, **k):
    cont["[exists] " + _quem()] += 1
    return _orig_exists(*a, **k)

def main():
    from gerar_selfplay_dataset import _load_deck_list
    from optcg_engine.decision_engine import OPTCGMatch
    dl = _load_deck_list()
    rng = random.Random(909)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(909)
    os.stat = stat_espiao
    os.path.exists = exists_espiao
    try:
        m = OPTCGMatch(dl[ia][1], dl[ib][1])
        m.setup()          # <- agora DENTRO da conta (roda por partida no duelo)
        m.state_a.value_net_weight = 200.0
        m.state_b.value_net_weight = 200.0
        _pos_setup = sum(cont.values())
        print('acessos durante OPTCGMatch(...) + setup(): {:,}'.format(_pos_setup))
        for turn in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if turn % 2 == 0                 else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            if m.play_turn(p, opp):
                break
    finally:
        os.stat = _orig_stat
        os.path.exists = _orig_exists
    tot = sum(cont.values())
    print("acessos a disco DURANTE a partida: {:,}".format(tot))
    for quem, n in cont.most_common(12):
        print("{:>8,}  {}".format(n, quem))

if __name__ == "__main__":
    main()
