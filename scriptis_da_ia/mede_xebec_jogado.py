"""Bloco 956 -- o motor tira valor do Xebec 10 (OP17-118) quando ele fica na mao?

O teste de descarte (mede_descarte_xebec.py) deu guardar ~ descartar no
auto-jogo. Antes de concluir que o modelo esta certo, mede o que o MOTOR faz
com a carta: quantas partidas a tem na mao, quantas vezes a JOGA, em que turno,
com quanto DON, o que o [On Play] rende (cartas baixadas de graca) e a vitoria
com/sem ela jogada. Lado Xebec alternando quem comeca.
"""
import argparse, collections, os, random, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
XEBEC, BOMBA = 'Rocks D Xebec', 'OP17-118'
OPONENTES = ['SABO RB', 'Enel P', 'Luffy RG', 'ace luffy']


def _um(seed):
    from optcg_engine import sim_bridge as sb
    from optcg_engine.decision_engine import OPTCGMatch
    from gerar_selfplay_dataset import _quem_joga
    rng = random.Random(seed); random.seed(seed)
    m = OPTCGMatch(sb.load_sim_deck(XEBEC), sb.load_sim_deck(rng.choice(OPONENTES)))
    m.setup()
    m.replay_log = []
    x = m.state_a
    st = {'na_mao_algum_turno': False, 'jogou': 0, 'turno_jogou': [], 'don_quando_na_mao_max': 0,
          'gratis_no_on_play': 0, 'descartou': 0, 'turnos': 0, 'venceu': None,
          'turnos_com_10don_e_na_mao': 0}
    r = None
    for t in range(m.MAX_TURNS * 2):
        p, o = _quem_joga(m, t)
        if p is x:
            na_mao = any(c.code == BOMBA for c in x.hand)
            if na_mao:
                st['na_mao_algum_turno'] = True
        n0 = len(m.replay_log)
        try:
            r = m.play_turn(p, o)
        except Exception:
            return None
        if p is x:
            st['turnos'] += 1
            don_total = len(getattr(x, 'don_field', []) or []) if hasattr(x, 'don_field') else None
            if na_mao and (x.don_available + getattr(x, 'don_rested', 0)) >= 10:
                st['turnos_com_10don_e_na_mao'] += 1
            for ev in m.replay_log[n0:]:
                c = (ev.get('card') or {}).get('code')
                if ev.get('type') == 'play_card' and c == BOMBA and ev.get('player') == 'A':
                    st['jogou'] += 1; st['turno_jogou'].append(st['turnos'])
                if ev.get('type') == 'effect' and c == BOMBA and ev.get('player') == 'A':
                    st['gratis_no_on_play'] += (ev.get('description') or '').count('jogou')
        if r:
            break
    st['descartou'] = sum(1 for c in x.trash if c.code == BOMBA)
    st['venceu'] = (r == 'A') if r in ('A', 'B') else None
    return st


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=80)
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    with ProcessPoolExecutor(a.workers) as ex:
        rs = [r for r in ex.map(_um, range(9560000, 9560000 + a.n)) if r and r['venceu'] is not None]
    n = len(rs)
    print(f'partidas: {n} | Xebec venceu {sum(r["venceu"] for r in rs)}/{n}')
    print(f'Xebec 10 na mao em algum turno: {sum(r["na_mao_algum_turno"] for r in rs)}/{n}')
    print(f'partidas em que JOGOU o Xebec 10: {sum(r["jogou"] > 0 for r in rs)}/{n}')
    tj = [t for r in rs for t in r['turno_jogou']]
    if tj:
        print(f'turno proprio em que jogou: media {sum(tj)/len(tj):.1f} | {collections.Counter(tj).most_common()}')
    print(f'cartas baixadas de graca pelo On Play (media por Xebec jogado): '
          f'{sum(r["gratis_no_on_play"] for r in rs)/max(1,len(tj)):.2f}')
    print(f'turnos com 10+ DON e Xebec na mao: {sum(r["turnos_com_10don_e_na_mao"] for r in rs)}')
    print(f'Xebec 10 terminando no trash (media/partida): {sum(r["descartou"] for r in rs)/n:.2f}')
    print(f'duracao media (turnos proprios): {sum(r["turnos"] for r in rs)/n:.1f}')
    j = [r for r in rs if r['jogou']]; nj = [r for r in rs if not r['jogou'] and r['na_mao_algum_turno']]
    if j: print(f'vitoria quando JOGOU: {sum(r["venceu"] for r in j)}/{len(j)}')
    if nj: print(f'vitoria quando teve na mao e NAO jogou: {sum(r["venceu"] for r in nj)}/{len(nj)}')
