"""Teste das JOGADAS LEGAIS do nucleo Rust (PLANO_MOTOR_FORTE, fim da fase A).

Roda partidas do motor Python e, ANTES de cada jogada principal, compara a
lista de `optcg_core.jogadas_legais` com:

  1. a jogada que o Python fez -- tem que estar na lista (o DON do ataque
     entra como `attach_don` antes, entao o ataque e comparado sem o DON e o
     DON pedido tem que caber no DON disponivel);
  2. uma referencia montada com os PREDICADOS DE REGRA do proprio motor
     Python (`character_can_attack_now`, `rested_chars`,
     `active_taunt_character`, `effective_hand_play_cost`), sem os cortes
     heuristicos de `_generate_and_score_actions` -- jogar e atacar tem que
     bater exatamente.

Uso: python legais_nucleo.py --partidas 30 --seed 1000
"""
import argparse
import json
import sys

import optcg_core
import paridade_nucleo as P
from optcg_engine import decision_engine as de
from optcg_engine import estado_canonico as ec

TOT = {'jogadas': 0, 'contida': 0, 'ref_ok': 0, 'ref_n': 0, 'nao_suportado': 0}
FALHAS = []
MOTIVOS = {}


def _norm(a):
    t = a['tipo']
    if t == 'attack':
        return (t, tuple(a['ator']), a['alvo_tipo'], tuple(a['alvo']) if a['alvo'] else None)
    if t == 'attach_don':
        return (t, tuple(a['ator']), 1)     # dar k DON = k jogadas de 1
    return (t, tuple(a['ator']) if isinstance(a.get('ator'), list) else None)


def _referencia(p, opp):
    """Jogar e atacar pelas regras do motor Python (sem heuristica)."""
    out = set()
    for k, c in enumerate(p.hand):
        if c.card_type not in ('CHARACTER', 'EVENT', 'STAGE') or p.cant_play_from_hand_this_turn:
            continue
        if c.card_type == 'CHARACTER' and (p.cant_play_chars_this_turn or (
                p.cant_play_cost_gte and c.cost >= p.cant_play_cost_gte)):
            continue
        if de.effective_hand_play_cost(p, c, opp) > p.don_available:
            continue
        efs = de.get_card_effects(c.code)
        if c.card_type == 'EVENT' and not any(t in efs for t in ('on_play', 'main', 'activate_main')):
            continue
        out.add(('play', ('hand', k)))
    if p.can_attack_this_turn():
        taunt = de.active_taunt_character(opp, p)
        atk = [(c, ('field_chars', k)) for k, c in enumerate(p.field_chars)
               if de.character_can_attack_now(c, p, opp)]
        if de.character_can_attack_now(p.leader, p, opp):
            atk.append((p.leader, ('leader', 0)))
        for a, l in atk:
            if (not getattr(a, 'rush_character_only_this_turn', False) and taunt is None
                    and not p.cannot_attack_leader_this_turn):
                out.add(('attack', l, 'leader', None))
            lock = getattr(a, 'cannot_attack_opp_chars_cost_lte', -1)
            for t in opp.rested_chars(a):
                if taunt is not None and t is not taunt:
                    continue
                if lock >= 0 and t.cost <= lock:
                    continue
                j = next(i for i, x in enumerate(opp.field_chars) if x is t)
                out.add(('attack', l, 'character', ('oponente', 'field_chars', j)))
    return out


_orig = de.OPTCGMatch._apply_action


def _apply_com_teste(self, action, p, opp, ee, engine, verbose=False):
    if not de._EM_SIMULACAO['on'] and ec.DIARIO['on']:
        TOT['jogadas'] += 1
        st, r = optcg_core.jogadas_legais(json.dumps(ec.canonico(p, opp)))
        if st != 'ok':
            TOT['nao_suportado'] += 1
            MOTIVOS[r] = MOTIVOS.get(r, 0) + 1
        else:
            leg = json.loads(r)
            normas = {_norm(a) for a in leg}
            feita = ec.descreve_acao(action, p, opp)
            ok = _norm(feita) in normas and (feita['tipo'] != 'attack' or (feita['don'] or 0) <= p.don_available)                 and (feita['tipo'] != 'attach_don' or feita['alvo_tipo'] <= p.don_available)
            TOT['contida'] += ok
            if not ok and len(FALHAS) < 10:
                FALHAS.append(('contida', feita, p.leader.code, p.leader.rested, getattr(p.leader, '_am_used_turn', None), p.turn, p.don_available, p.don_rested, len(p.hand), de.get_card_effects(p.leader.code).get('activate_main') if feita['tipo'] == 'activate' else None))
            ref = _referencia(p, opp)
            rs = {x for x in normas if x[0] in ('play', 'attack')}
            TOT['ref_n'] += 1
            if ref == rs:
                TOT['ref_ok'] += 1
            elif len(FALHAS) < 10:
                FALHAS.append(('referencia', sorted(map(str, ref - rs)), sorted(map(str, rs - ref))))
    return _orig(self, action, p, opp, ee, engine, verbose)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=10)
    ap.add_argument('--seed', type=int, default=1000)
    a = ap.parse_args()
    de.OPTCGMatch._apply_action = _apply_com_teste
    for i in range(a.partidas):
        P.diario_de(a.seed + i)
    n = max(TOT['jogadas'] - TOT['nao_suportado'], 1)
    print(f"jogadas {TOT['jogadas']} | nao suportadas {TOT['nao_suportado']}")
    print(f"jogada feita esta na lista do Rust: {TOT['contida']}/{n} ({100 * TOT['contida'] / n:.1f}%)")
    print(f"jogar/atacar = referencia de regras: {TOT['ref_ok']}/{TOT['ref_n']} "
          f"({100 * TOT['ref_ok'] / max(TOT['ref_n'], 1):.1f}%)")
    for m, k in sorted(MOTIVOS.items(), key=lambda x: -x[1]):
        print('   nao suportado:', m, k)
    for f in FALHAS:
        print('FALHA', f)
    return 0 if TOT['contida'] == n and TOT['ref_ok'] == TOT['ref_n'] else 1


if __name__ == '__main__':
    sys.exit(main())
