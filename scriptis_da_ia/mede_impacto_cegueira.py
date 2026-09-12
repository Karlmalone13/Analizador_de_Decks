"""FASE 0: o que MUDA no jogo quando o bot para de espiar? Bloco 782.

NAO mede placar de auto-jogo -- de proposito. O portao SPRT nao julga esta
mudanca (bot-que-espia vence por ter mais informacao, e reprovaria medindo a
coisa errada). Mede COMPORTAMENTO: quanto DON o bot anexa, quantos ataques
faz, quanto dano tira. Sao os sinais que tambem existem no banco de logs
humanos, entao dao pra comparar contra gente de verdade depois.
"""
from __future__ import annotations
import argparse
import random

from optcg_engine import decision_engine as de


def uma(seed, cego, acc):
    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    try:
        m = de.OPTCGMatch(dl[ia][1], dl[ib][1], hide_opponent_info=cego)
        m.enable_decision_audit()
        m.setup()
    except Exception:
        return
    try:
        for t in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            if m.play_turn(p, opp):
                break
    except Exception:
        pass
    atks = [d for d in (m.decision_log or []) if d.get('kind') == 'attack_outcome']
    acc['partidas'] += 1
    acc['turnos'] += t + 1
    acc['ataques'] += len(atks)
    acc['don_anexado'] += sum(d.get('attached_don') or 0 for d in atks)
    acc['vidas'] += sum(d.get('vidas_tiradas') or 0 for d in atks)
    acc['bloqueados'] += sum(1 for d in atks if d.get('blocked_by'))
    acc['counterados'] += sum(1 for d in atks if (d.get('counter_add') or 0) > 0)


def roda(cego, n, seed):
    acc = {'partidas': 0, 'turnos': 0, 'ataques': 0, 'don_anexado': 0,
           'vidas': 0, 'bloqueados': 0, 'counterados': 0}
    for i in range(n):
        uma(seed * 1_000_003 + i, cego, acc)
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--seed', type=int, default=5252)
    a = ap.parse_args()

    print('')
    print('FASE 0 -- impacto de PARAR DE ESPIAR (mesmas seeds, mesmos decks)')
    e = roda(False, a.n, a.seed)
    c = roda(True, a.n, a.seed)

    def linha(nome, ke, kc, div_e, div_c, fmt='{:.2f}'):
        ve = e[ke] / max(1, e[div_e]); vc = c[kc] / max(1, c[div_c])
        d = ((vc - ve) / ve * 100) if ve else 0.0
        print(('  {:28s} ' + fmt + '   ' + fmt + '   {:+.1f}%').format(
            nome, ve, vc, d))

    print('')
    print('  {:28s} {:>7s}   {:>7s}   {:>7s}'.format(
        '', 'ESPIA', 'CEGO', 'delta'))
    print('  ' + '-' * 56)
    linha('ataques por turno', 'ataques', 'ataques', 'turnos', 'turnos')
    linha('DON anexado por ataque', 'don_anexado', 'don_anexado', 'ataques', 'ataques')
    linha('vidas tiradas por partida', 'vidas', 'vidas', 'partidas', 'partidas')
    linha('% ataques bloqueados', 'bloqueados', 'bloqueados', 'ataques', 'ataques')
    linha('% ataques counterados', 'counterados', 'counterados', 'ataques', 'ataques')
    linha('turnos por partida', 'turnos', 'turnos', 'partidas', 'partidas')
    print('')
    print('REFERENCIA HUMANA (banco de logs, ja medido): o humano ataca 1,66')
    print('vezes por turno; o motor atacava 1,98 (+0,32). Se a cegueira')
    print('aproximar o motor do humano, e sinal de fidelidade -- nao de forca.')


if __name__ == '__main__':
    main()
