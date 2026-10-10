"""Bloco 960 -- reproducao de ATAQUES de partidas reais no motor.

Extensao do mede_replay_estado.py (que cobre play/activate/attach). Num ataque
o DEFENSOR e o outro lado -- e em CPU x CPU o registro de DEFESA dele traz a
mao REAL naquele instante. Monta o atacante pelo `state_before` da decisao de
ataque e o defensor pelo `state_before` da 1a decisao de defesa que aquele
ataque gerou; aplica o ataque no motor (que decide a defesa do jeito dele) e
compara com o jogo: o golpe passou? vida do defensor, personagens dele, quanto
counter ele usou (jogo: o que o defensor ESCOLHEU ao vivo; motor: o que o
motor escolheu).
"""
import collections, glob, json, os, sys
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, '..', 'BOT', 'engine_server'))


def main(receipts):
    import server
    from optcg_engine.decision_engine import EffectExecutor, DecisionEngine
    br, mt = server._get_bridge(), server._get_match()
    tot = collections.Counter(); exemplos = collections.defaultdict(list)
    soma = collections.defaultdict(lambda: [0, 0, 0])   # (motor_hits, jogo_hits, n)
    for rp in receipts:
        r = json.load(open(rp, encoding='utf-8'))
        mid = r.get('match_id')
        if not mid or not r.get('decision_log'):
            continue
        evs = []
        with open(r['decision_log'], encoding='utf-8', errors='ignore') as f:
            for l in f:
                if mid in l[:400]:
                    d = json.loads(l)
                    if d.get('event') == 'decision' and d.get('state_before'):
                        evs.append(d)
        for i, d in enumerate(evs):
            ca = d.get('chosen_action') or {}
            if d.get('decision_kind') != 'main' or ca.get('type') != 'attack':
                continue
            lado = d['state_before']['bot']['leader']['code']
            defesa = next((e for e in evs[i + 1:i + 12] if e.get('decision_kind') == 'defense'
                           and e['state_before'].get('bot', {}).get('leader', {}).get('code') != lado), None)
            prox = next((e for e in evs[i + 1:] if e.get('decision_kind') == 'main'
                         and e['state_before']['bot']['leader']['code'] == lado), None)
            if defesa is None or prox is None or prox['state_before']['turnNumber'] != d['state_before']['turnNumber']:
                tot['sem_par'] += 1
                continue
            s1 = server.GameStateDto(**d['state_before'])
            sd = server.GameStateDto(**defesa['state_before'])
            gs = server._dto_to_gs(s1.bot, s1.turnNumber)
            op = server._dto_to_gs(sd.bot, sd.turnNumber)          # defensor REAL (mao real)
            br.aplica_mundo_completo(gs, op, s1.bot, sd.bot, s1.combatLog, s1.botLogName)
            gs.is_active_turn, op.is_active_turn = True, False
            act = br.choose_action(gs, op, mt, timeout=5.0,
                                   allowed_types={"play", "attack", "attach_don", "activate"})
            cod = getattr(act[2], 'code', None) if act and len(act) > 2 else None
            if not act or act[1] != 'attack' or cod != ca.get('card_code'):
                tot['decisao_diferente'] += 1
                continue
            vida0, mao0 = op.life_count(), len(op.hand)
            try:
                mt._apply_action(act, gs, op, EffectExecutor(gs, op), DecisionEngine(gs, op))
            except Exception:
                tot['erro'] += 1
                continue
            s2 = server.GameStateDto(**prox['state_before'])
            vida_jogo = s2.opp.life if isinstance(s2.opp.life, int) else len(s2.opp.life or [])
            hit_motor = op.life_count() < vida0
            hit_jogo = vida_jogo < vida0
            gasto_motor = mao0 - len(op.hand)
            gasto_jogo = len(sd.bot.hand) - (len(s2.opp.hand) if isinstance(s2.opp.hand, list) else s2.opp.handCount)
            k = f"{lado} ataca {'lider' if ca.get('target_type') == 'leader' else 'personagem'}"
            s = soma[k]; s[0] += hit_motor; s[1] += hit_jogo; s[2] += 1
            tot['comparados'] += 1
            if hit_motor != hit_jogo:
                tot['resultado_diferente'] += 1
                exemplos[k].append((r.get('bank_entry_id'), s1.turnNumber, ca.get('card_code'),
                                    f'motor {"passou" if hit_motor else "segurou"} (defesa gastou {gasto_motor})',
                                    f'jogo {"passou" if hit_jogo else "segurou"} (defesa gastou {gasto_jogo})'))
    print(dict(tot))
    for k, (hm, hj, n) in sorted(soma.items()):
        print(f'{k:32s} n={n:3d} | golpe passou: motor {hm:3d} | jogo {hj:3d}')
    for k, v in exemplos.items():
        print(f'\n== {k}: {len(v)} com resultado diferente')
        for x in v[:6]:
            print('   ', *x)


if __name__ == '__main__':
    pad = sys.argv[1] if len(sys.argv) > 1 else 'metrics/live_runs/receipt_2026-10-10T1[67]*.json'
    main(sorted(glob.glob(pad)))
