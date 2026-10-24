#!/usr/bin/env python
"""Teste do DIARIO de paridade (PLANO_MOTOR_FORTE fase A, `estado_canonico.py`):
a MESMA partida rodada duas vezes gera o MESMO diario (deterministico), e o
diario tem as jogadas com estado antes/depois e as escolhas internas."""
import hashlib, json, os, random, sys
os.environ.setdefault('PYTHONHASHSEED', '0')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optcg_engine import decision_engine as de, estado_canonico as ec
from gerar_selfplay_dataset import _load_deck_list


def joga(seed):
    dl = _load_deck_list()
    rng = random.Random(seed); ia, ib = rng.sample(range(len(dl)), 2); random.seed(seed)
    ec.DIARIO.update(on=True, eventos=[], passos=0, acoes=[])
    m = de.OPTCGMatch(dl[ia][1], dl[ib][1]); m.setup()
    for n in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if n % 2 == 0 \
            else (m.state_b if m.state_a.is_first else m.state_a)
        o = m.state_b if p is m.state_a else m.state_a
        if m.play_turn(p, o):
            break
    ev = list(ec.DIARIO['eventos']); ec.DIARIO.update(on=False, eventos=[])
    return ev


falhas = 0
for seed in (1000, 1001):
    a, b = joga(seed), joga(seed)
    ha = hashlib.sha1(json.dumps(a, sort_keys=True).encode()).hexdigest()
    hb = hashlib.sha1(json.dumps(b, sort_keys=True).encode()).hexdigest()
    jog = [e for e in a if e['tipo'] == 'jogada']; esc = [e for e in a if e['tipo'] == 'escolha']
    ok = ha == hb and jog and all('antes' in e and 'depois' in e for e in jog)
    falhas += 0 if ok else 1
    tam = len(json.dumps(a)) / 1e6
    print(f'seed {seed}: {"OK" if ok else "FALHA"} | deterministico {ha == hb} | jogadas {len(jog)} '
          f'| escolhas {len(esc)} ({sorted({e["familia"] for e in esc})}) | {tam:.1f} MB')
sys.exit(1 if falhas else 0)
