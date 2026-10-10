"""Bloco 952 -- por que o MESMO modelo/decks da Mihawk 76% no motor e 1/10 no OPTCGSim?

Compara, por lado e por partida, o que acontece no motor (auto-jogo, Mihawk
comecando, gen atual nos dois lados) e no jogo real (logs CPU x CPU do banco):
ataques, ataques no lider e seu poder medio, poder de counter gasto, e cartas
jogadas por codigo. Onde os numeros se separam e onde procurar a regra/efeito
que um dos dois executa diferente.
"""
import argparse, collections, glob, os, random, re, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LADO = {'You': 'Mihawk', 'Opponent': 'Luffy'}


def _motor(seed):
    from optcg_engine import sim_bridge as sb
    from optcg_engine.decision_engine import OPTCGMatch
    from gerar_selfplay_dataset import _quem_joga
    random.seed(seed)
    m = OPTCGMatch(sb.load_sim_deck('Mihawk op17'), sb.load_sim_deck('ace luffy'))
    m.setup()
    m.state_a.is_first, m.state_b.is_first = True, False
    m.replay_log = []
    r = None
    for t in range(m.MAX_TURNS * 2):
        p, o = _quem_joga(m, t)
        try:
            r = m.play_turn(p, o)
        except Exception:
            return None
        if r:
            break
    st = collections.Counter()
    for ev in m.replay_log:
        who = 'Mihawk' if ev.get('player') == 'A' else 'Luffy'
        tp = ev.get('type') or ev.get('event_type')
        if tp == 'attack':
            st[(who, 'ataques')] += 1
            tg = (ev.get('target') or {}).get('code')
            if tg in ('OP14-020', 'ST30-001'):
                st[(who, 'ataques_lider')] += 1
                st[(who, 'poder_atk_lider')] += ev.get('attack_power', 0)
        elif tp == 'play_card':
            st[(who, 'jogou:' + (ev.get('card') or {}).get('code', '?'))] += 1
    st[('Mihawk', 'counter_poder')] = m.state_a.counters_used
    st[('Luffy', 'counter_poder')] = m.state_b.counters_used
    st[('Mihawk', 'venceu')] = int(r == 'A')
    return st


def _jogo():
    out = []
    for f in sorted(glob.glob('logs/raw/*Mihawk*Luffy.&.Ace*2026-10-09T09*.log')):
        t = re.sub(r'<[^>]*>', '', open(f, encoding='utf-8', errors='ignore').read())
        st = collections.Counter()
        for l in t.splitlines():
            m = re.match(r'^\[(You|Opponent)\] (.+?) \["?([A-Z0-9]+-\d+)[^\]]*\] attacking .*?\["?([A-Z0-9]+-\d+)', l)
            if m:
                who = LADO[m.group(1)]
                st[(who, 'ataques')] += 1
                if m.group(4) in ('OP14-020', 'ST30-001'):
                    st[(who, 'ataques_lider')] += 1
            m = re.match(r'^.+?\["?([A-Z0-9]+-\d+)[^\]]*\]\[(\d+)\] vs .+?\["?(OP14-020|ST30-001)', l)
            if m:
                who = 'Mihawk' if m.group(3) == 'ST30-001' else 'Luffy'
                st[(who, 'poder_atk_lider')] += int(m.group(2))
            m = re.match(r'^\[(You|Opponent)\] Deploy .+?\["?([A-Z0-9]+-\d+)', l)
            if m:
                st[(LADO[m.group(1)], 'jogou:' + m.group(2))] += 1
            m = re.match(r'^\[(You|Opponent)\] .*?(?:for Counter|\]: Counter) (\d+)', l)
            if m:
                st[(LADO[m.group(1)], 'counter_poder')] += int(m.group(2))
            m = re.match(r'^\[(You|Opponent)\] .*?: Buff .+? (\d+) for the Combat', l)
            if m:
                st[(LADO[m.group(1)], 'counter_poder')] += int(m.group(2))
        out.append(st)
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    with ProcessPoolExecutor(a.workers) as ex:
        motor = [s for s in ex.map(_motor, range(9520000, 9520000 + a.n)) if s]
    jogo = _jogo()
    chaves = sorted({k for s in motor + jogo for k in s}, key=lambda k: (k[0], not k[1].startswith('jogou'), k[1]))
    print(f'por partida | motor n={len(motor)} | jogo n={len(jogo)}')
    for k in chaves:
        vm = sum(s[k] for s in motor) / len(motor)
        vj = sum(s[k] for s in jogo) / len(jogo)
        if k[1] == 'poder_atk_lider':
            am = sum(s[(k[0], 'ataques_lider')] for s in motor) or 1
            aj = sum(s[(k[0], 'ataques_lider')] for s in jogo) or 1
            vm = sum(s[k] for s in motor) / am; vj = sum(s[k] for s in jogo) / aj
            k = (k[0], 'poder medio no ataque ao lider')
        if max(vm, vj) >= 0.2:
            print(f'{k[0]:7s} {k[1]:34s} motor {vm:8.1f}   jogo {vj:8.1f}')
