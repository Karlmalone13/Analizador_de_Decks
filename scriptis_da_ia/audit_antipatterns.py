"""
audit_antipatterns.py
=====================
Auditor automático de anti-padrões de pilotagem (criado 10/07/2026, ver
HANDOFF #120): roda partidas motor-contra-motor com os decks REAIS e acusa,
turno a turno, os erros de decisão que o usuário apontou em partidas ao
vivo — para achá-los ANTES de gastar uma partida real do usuário com isso.

Anti-padrões checados (lado auditado = deck A):
  A. don_ocioso        — terminou o turno com 3+ DON ativos E carta jogável
                         na mão (pode ser reserva legítima de defesa; o
                         relatório mostra o contexto pra julgar caso a caso)
  B. lider_nao_atacou  — líder terminou o turno ATIVO (nunca atacou) do
                         turno 2 em diante
  C. win_con_trashado  — a carta-bomba do GamePlan saiu da MÃO pro trash
  D. win_con_parado    — DON no campo >= custo da bomba, bomba na mão,
                         turno terminou sem jogá-la
  E. stage_nao_usado   — Stage ativo no fim do turno com alvo válido na mão
                         e DON sobrando pra pagar a ativação
  F. leader_draw_nao_usado — líder com activate_main de draw (ex: Imu) não
                         usado no turno, tendo material barato pra pagar
                         (personagem de 0 poder no campo ou carta fraca na mão)

Uso:
  python audit_antipatterns.py                     # 20 partidas Imu vs Teach
  python audit_antipatterns.py --n 50 --seed 42
  python audit_antipatterns.py --deck-a Imu --deck-b "Barba Negra BY"
"""
from __future__ import annotations
import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from optcg_engine.sim_bridge import load_sim_deck
from optcg_engine.decision_engine import (
    OPTCGMatch, compute_game_plan, effective_hand_play_cost, get_card_effects,
)


def _hand_codes(p):
    return Counter(c.code for c in p.hand)


def _trash_codes(p):
    return Counter(c.code for c in p.trash)


def audit_match(deck_a, deck_b, match_idx: int) -> list[dict]:
    match = OPTCGMatch(deck_a, deck_b)
    match.setup()
    match.replay_log = []   # habilita eventos estruturados (activate_main etc.)
    plan = compute_game_plan(match.state_a)
    flags: list[dict] = []

    # Líder do lado auditado tem activate_main de draw? (ex: Imu)
    lider_am = get_card_effects(match.state_a.leader.code).get('activate_main', {})
    lider_tem_draw = any(s.get('action') == 'draw' for s in lider_am.get('steps', []))

    for turn_num in range(match.MAX_TURNS * 2):
        p = (match.state_a if match.state_a.is_first else match.state_b) \
            if turn_num % 2 == 0 \
            else (match.state_b if match.state_a.is_first else match.state_a)
        opp = match.state_b if p is match.state_a else match.state_a

        is_audited = p is match.state_a
        if is_audited:
            hand_before = _hand_codes(p)
            trash_before = _trash_codes(p)
        eventos_antes = len(match.replay_log)

        result = match.play_turn(p, opp)
        eventos_turno = match.replay_log[eventos_antes:]

        # Turno que TERMINOU a partida não conta: DON parado / bomba não
        # jogada são legítimos quando o jogo acabou no meio do turno
        # (ex: lethal no primeiro ataque). Só audita turnos completos.
        if is_audited and result is None:
            t = p.turn
            ctx = {'match': match_idx, 'turn': t}

            # A. DON ocioso com jogada disponível
            jogaveis = [c for c in p.hand
                        if c.card_type in ('CHARACTER', 'STAGE')
                        and effective_hand_play_cost(p, c) <= p.don_available]
            if p.don_available >= 3 and jogaveis:
                flags.append({**ctx, 'tipo': 'A_don_ocioso',
                              'detalhe': f"{p.don_available} DON ativos, jogáveis: "
                                         f"{[c.code for c in jogaveis]}"})

            # B. Líder não atacou (turno 2+, oponente vivo)
            if t >= 2 and not p.leader.rested and opp.life_count() >= 0:
                flags.append({**ctx, 'tipo': 'B_lider_nao_atacou',
                              'detalhe': f"líder ativo no fim do turno "
                                         f"(opp vida={opp.life_count()})"})

            # C. win_con trashado da mão
            wc = plan['win_con_code']
            if wc:
                saiu_da_mao = hand_before.get(wc, 0) > _hand_codes(p).get(wc, 0)
                entrou_no_trash = _trash_codes(p).get(wc, 0) > trash_before.get(wc, 0)
                em_campo = any(c.code == wc for c in p.field_chars)
                if saiu_da_mao and entrou_no_trash and not em_campo:
                    flags.append({**ctx, 'tipo': 'C_win_con_trashado',
                                  'detalhe': f"{wc} saiu da mão pro trash"})

                # D. win_con pagável e não jogado
                if (plan['don_target'] and _hand_codes(p).get(wc, 0) > 0
                        and p.don_on_field() >= plan['don_target']):
                    flags.append({**ctx, 'tipo': 'D_win_con_parado',
                                  'detalhe': f"{wc} na mão, DON no campo="
                                             f"{p.don_on_field()} >= {plan['don_target']}"})

            # F. Líder com draw de activate_main não usado, com material barato
            if lider_tem_draw and t >= 1:
                usou_lider = any(
                    e.get('type') == 'activate_main'
                    and (e.get('card') or {}).get('code') == p.leader.code
                    for e in eventos_turno)
                if not usou_lider:
                    ee_tmp2 = None
                    tem_material = any(c.power == 0 for c in p.field_chars)
                    if not tem_material and p.hand:
                        from optcg_engine.decision_engine import EffectExecutor as _EE
                        ee_tmp2 = _EE(p, opp)
                        worst = min(p.hand, key=ee_tmp2._trash_value)
                        tem_material = ee_tmp2._trash_value(worst) <= 60
                    if tem_material:
                        flags.append({**ctx, 'tipo': 'F_leader_draw_nao_usado',
                                      'detalhe': f"líder {p.leader.code} não ativou "
                                                 f"draw (material barato disponível)"})

            # E. Stage ativo com alvo válido e DON sobrando
            stage = getattr(p, 'field_stage', None)
            if stage is not None and not stage.rested:
                am = get_card_effects(stage.code).get('activate_main', {})
                custo_don = sum(c.get('count', 0) for c in am.get('costs', [])
                                if c.get('type') == 'rest_don')
                for step in am.get('steps', []):
                    if step.get('action') != 'play_card':
                        continue
                    ft = (step.get('filter_type') or '').lower()
                    fcolor = (step.get('color') or '').lower()
                    cost_lte = step.get('cost_lte')
                    if cost_lte == 'don_count_self':
                        cost_lte = p.don_on_field()
                    alvos = [c for c in p.hand
                             if c.card_type == 'CHARACTER'
                             and (not ft or ft in (c.sub_types or '').lower())
                             and (not fcolor or fcolor in (c.color or '').lower())
                             and (cost_lte is None or c.cost <= cost_lte)]
                    if alvos and p.don_available >= custo_don:
                        flags.append({**ctx, 'tipo': 'E_stage_nao_usado',
                                      'detalhe': f"{stage.code} ativo, alvos "
                                                 f"{[c.code for c in alvos]}, "
                                                 f"{p.don_available} DON ativos"})
                    break

        if result:
            break

    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--deck-a', default='Imu')
    ap.add_argument('--deck-b', default='Barba Negra BY')
    ap.add_argument('--detalhes', action='store_true',
                    help='lista cada flag individual, não só o resumo')
    args = ap.parse_args()

    random.seed(args.seed)
    deck_a = load_sim_deck(args.deck_a)
    deck_b = load_sim_deck(args.deck_b)

    todas: list[dict] = []
    for i in range(args.n):
        todas.extend(audit_match(deck_a, deck_b, i))

    resumo = Counter(f['tipo'] for f in todas)
    print(f"\n=== Auditoria: {args.deck_a} (auditado) vs {args.deck_b} — "
          f"{args.n} partidas, seed={args.seed} ===")
    if not todas:
        print("Nenhum anti-padrão detectado.")
        return
    for tipo, n in sorted(resumo.items()):
        print(f"  {tipo:24s} {n:4d} ocorrências "
              f"({n / args.n:.1f} por partida)")

    if args.detalhes:
        print()
        for f in todas:
            print(f"  [m{f['match']:02d} t{f['turn']:02d}] {f['tipo']}: {f['detalhe']}")
    else:
        print("\nAmostra (3 primeiras de cada tipo; --detalhes pra ver tudo):")
        vistos: Counter = Counter()
        for f in todas:
            if vistos[f['tipo']] < 3:
                vistos[f['tipo']] += 1
                print(f"  [m{f['match']:02d} t{f['turn']:02d}] {f['tipo']}: {f['detalhe']}")


if __name__ == '__main__':
    main()
