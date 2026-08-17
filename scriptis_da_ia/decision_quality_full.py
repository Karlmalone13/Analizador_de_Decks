"""
decision_quality_full.py -- comparacao COMPLETA motor-de-hoje vs humano,
turno a turno, cobrindo TODAS as categorias de decisao (pedido explicito
do usuario, 17/08: "nao quero so DON ocioso, tem que ser todas as
decisoes... counter, ordem de counter, blocker, efeito, ataque,
distribuicao de dons, ativacao de efeito").

`decision_quality_vs_human.py` so media DANO agregado do turno proprio.
O scratchpad `audit_defense.py` (nunca formalizado) media blocker/counter
mas so sim/nao, sem qual carta nem ordem. Este script unifica os dois e
fecha a lacuna de ORDEM de counter, numa unica tabela por categoria --
pra nunca mais precisar responder "90% em relacao a que?" caca-niquel.

CATEGORIAS (cada uma sua propria %, contra sua propria base de turnos/
ataques -- nao existe um numero unico "o bot joga X% igual ao humano"
porque cada categoria tem denominador diferente):

  OFENSIVA (turno PROPRIO de cada humano, via audit_one_game(capture_
  actions=True) -- fonte unica, chama OPTCGMatch.play_turn() de
  verdade, nao reimplementa decisao):
    - play: mesmo(s) codigo(s) de carta jogada(s) no turno (conjunto)
    - attack_quem: mesmo(s) atacante(s) atacaram (conjunto)
    - attack_alvo: dos atacantes em comum, mesmo alvo escolhido
    - activate: mesma(s) carta(s) ativou [Activate: Main]
    - attach_don_alvo: mesmo(s) personagem(ns)/lider recebeu DON

  DEFESA (turno do OPONENTE, ataque a ataque contra o humano --
  reconstrucao igual `audit_defense.py`, chama DIRETAMENTE
  DecisionEngine.should_use_blocker/should_use_counter/pick_counters,
  as MESMAS funcoes que o jogo ao vivo usa via _execute_attack):
    - blocker_sim_nao: bloquearia? (bool)
    - blocker_carta: quando os dois bloquearam, mesma carta?
    - counter_sim_nao: counteraria? (bool)
    - counter_cartas: quando os dois counteraram, mesmo CONJUNTO de cartas?
    - counter_ordem: quando os dois usaram 2+ cartas, MESMA ORDEM
      (pick_counters ja devolve a selecao gulosa por menor pitch_cost --
      a mesma ordem que o jogo ao vivo jogaria as cartas)?

LIMITACOES (herdadas de audit_one_game/audit_defense -- ver os
docstrings deles): don_available e reconstrucao best-effort; deck
restante e composicao real mas ORDEM embaralhada; mao do oponente com
informacao COMPLETA (motor enxerga mais que o bot ao vivo enxergaria);
DEFESA reconstroi o board do defensor uma vez por TURNO do atacante, nao
ataque-a-ataque dentro do mesmo turno (aproximacao ja aceita no
scratchpad original).

Uso:
    python decision_quality_full.py --all [--workers N]
    python decision_quality_full.py --leader OP17-039 [--workers N]
    python decision_quality_full.py --log <parsed.json>
"""
import argparse
import concurrent.futures
import json
import os
import re

import pandas as pd

from audit_real_losses import (
    audit_one_game, _cards_from_codes, _find_real_deck, DonEstimator,
)
from decision_quality_vs_human import find_bot_vs_human_logs
from optcg_engine.decision_engine import (
    load_cards_db, DecisionEngine, GameState, populate_full_deck_knowledge,
    attack_time_power,
)

LOGS_DIR = 'logs'
OUT_DIR = os.path.join('metrics', 'decision_quality_full')
CODE_RE = re.compile(r'"([A-Za-z0-9\-]+)">')


# ── OFENSIVA (turno proprio) ────────────────────────────────────────────

def _hist_target_type_code(target_raw, leader_code):
    m = CODE_RE.search(target_raw or '')
    code = m.group(1) if m else None
    is_leader = (code == leader_code) or ('Leader' in (target_raw or ''))
    return ('leader', None) if is_leader else ('character', code)


def _offense_verdict(parsed_path, human_side_label, cards_db, df_raw, urls):
    data = json.load(open(parsed_path, encoding='utf-8'))
    meta = data['meta']['players']
    turns_raw = data['turns']
    opp_side = 'Opponent' if human_side_label == 'You' else 'You'
    opp_leader_code = meta['p1' if meta['p1']['name'] == opp_side else 'p2']['leader'].get('code')

    report = audit_one_game(parsed_path, human_side_label, cards_db, df_raw, urls,
                            capture_actions=True)
    if report.get('error'):
        return {'error': report['error']}

    rows = []
    for t in report.get('turnos', []):
        if 'error' in t:
            continue
        turn_num = t['turn']
        hist_actions = t.get('historical_actions', [])
        motor_actions = t.get('chosen_actions', [])

        # Achado real 17/08: o log historico rotula `type` por CONVENCAO
        # DA SIMULACAO, nao por categoria do motor -- jogar uma carta
        # EVENT/STAGE da mao aparece como `type: "activate"` la (209
        # EVENT + 148 STAGE no banco inteiro sao "activate" historico,
        # confirmado grep), enquanto o motor sempre gera essa MESMA acao
        # como `kind: "play"` (unico gerador de 'play' em decision_
        # engine.py cobre CHARACTER/EVENT/STAGE igual). Comparar os
        # rotulos crus inflava falso mismatch (ex: Disappointed? OP14-099
        # jogado nos dois lados, contado como divergencia so por rotulo).
        # Fix: reclassifica o HISTORICO pelo TIPO REAL da carta
        # (cards_db), nao pelo `type` do log -- EVENT/STAGE = "play"
        # (so podem ser jogados da mao, nunca ficam "ativaveis" depois),
        # LEADER/CHARACTER com `type=="activate"` = "activate" de
        # verdade ([Activate: Main] de algo ja em campo).
        def _hist_kind(card_type):
            return 'play' if card_type in ('EVENT', 'STAGE') else 'activate'

        hist_play = {a['card'] for a in hist_actions if a.get('card') and (
            a.get('type') == 'play'
            or (a.get('type') == 'activate' and _hist_kind(cards_db.get(a['card'], {}).get('type')) == 'play'))}
        motor_play = {a['card'] for a in motor_actions if a.get('kind') == 'play' and a.get('card')}

        hist_activate = {a['card'] for a in hist_actions if a.get('type') == 'activate' and a.get('card')
                         and _hist_kind(cards_db.get(a['card'], {}).get('type')) == 'activate'}
        motor_activate = {a['card'] for a in motor_actions if a.get('kind') == 'activate' and a.get('card')}

        hist_don_alvo = {a['to'] for a in hist_actions if a.get('type') == 'attach_don' and a.get('to')}
        motor_don_alvo = {a['card'] for a in motor_actions if a.get('kind') == 'attach_don' and a.get('card')}
        for rec in t.get('attach_don_for_attack_events', []):
            if rec.get('card'):
                motor_don_alvo.add(rec['card'])

        hist_attacks = []
        for a in hist_actions:
            if a.get('type') != 'attack' or not a.get('attacker_code'):
                continue
            ttype, tcode = _hist_target_type_code(a.get('target'), opp_leader_code)
            hist_attacks.append((a['attacker_code'], ttype, tcode))
        motor_attacks = [(a['card'], a.get('target_type'), a.get('target'))
                         for a in motor_actions if a.get('kind') == 'attack' and a.get('card')]

        hist_atk_who = {a[0] for a in hist_attacks}
        motor_atk_who = {a[0] for a in motor_attacks}
        hist_atk_map = {a[0]: (a[1], a[2]) for a in hist_attacks}
        motor_atk_map = {a[0]: (a[1], a[2]) for a in motor_attacks}
        common_attackers = hist_atk_who & motor_atk_who
        alvo_matches = [hist_atk_map[c] == motor_atk_map[c] for c in common_attackers]

        rows.append({
            'game': os.path.basename(parsed_path), 'turn': turn_num,
            'play_match': hist_play == motor_play,
            'play_has_data': bool(hist_play or motor_play),
            'attack_quem_match': hist_atk_who == motor_atk_who,
            'attack_has_data': bool(hist_atk_who or motor_atk_who),
            'attack_alvo_common': len(common_attackers),
            'attack_alvo_match': sum(alvo_matches),
            'activate_match': hist_activate == motor_activate,
            'activate_has_data': bool(hist_activate or motor_activate),
            'don_alvo_match': hist_don_alvo == motor_don_alvo,
            'don_has_data': bool(hist_don_alvo or motor_don_alvo),
        })
    return {'rows': rows}


# ── DEFESA (turno do oponente, ataque a ataque) ─────────────────────────

def _defense_verdict(parsed_path, human_side_label, cards_db, df_raw, urls):
    data = json.load(open(parsed_path, encoding='utf-8'))
    meta = data['meta']['players']
    turns = data['turns']
    opp_side = 'Opponent' if human_side_label == 'You' else 'You'

    human_leader = meta['p1' if meta['p1']['name'] == human_side_label else 'p2']['leader']
    opp_leader = meta['p1' if meta['p1']['name'] == opp_side else 'p2']['leader']

    human_deck = _find_real_deck(human_leader['name'], cards_db, df_raw, urls, human_leader.get('code'))
    opp_deck = _find_real_deck(opp_leader['name'], cards_db, df_raw, urls, opp_leader.get('code'))
    if not human_deck or not opp_deck:
        return {'error': f'deck real nao encontrado (human={human_leader["name"]}, opp={opp_leader["name"]})'}

    rows = []
    for i, turn in enumerate(turns):
        if turn['player'] != opp_side or i == 0:
            continue
        before = turns[i - 1]['snapshot']
        if human_side_label not in before or opp_side not in before:
            continue
        human_snap = before[human_side_label]
        opp_snap = before[opp_side]

        don_on_attacker = {}
        don_est = DonEstimator()
        for j in range(i):
            don_est.apply_turn(turns[j]['player'], turns[j], cards_db)

        for act in turn.get('actions', []):
            if act.get('type') == 'attach_don':
                don_on_attacker[act.get('to')] = don_on_attacker.get(act.get('to'), 0) + int(act.get('amount', 0) or 0)
                continue
            if act.get('type') != 'attack':
                continue

            attacker_code = act.get('attacker_code')
            ttype, tcode = _hist_target_type_code(act.get('target'), human_leader.get('code'))

            human_leader_card = _cards_from_codes([human_leader['code']], cards_db)[0]
            opp_leader_card = _cards_from_codes([opp_leader['code']], cards_db)[0]
            human = GameState(leader=human_leader_card)
            opp = GameState(leader=opp_leader_card)
            human.hand = _cards_from_codes(human_snap.get('hand', []), cards_db)
            human.field_chars = _cards_from_codes(human_snap.get('board', []), cards_db, human_snap.get('rested', {}))
            human.trash = _cards_from_codes(human_snap.get('trash', []), cards_db)
            life_n = human_snap.get('life', 4)
            human.life = _cards_from_codes([human_leader['code']] * life_n, cards_db) if life_n else []

            opp.hand = _cards_from_codes(opp_snap.get('hand', []), cards_db)
            opp.field_chars = _cards_from_codes(opp_snap.get('board', []), cards_db, opp_snap.get('rested', {}))
            opp.trash = _cards_from_codes(opp_snap.get('trash', []), cards_db)
            opp_life_n = opp_snap.get('life', 4)
            opp.life = _cards_from_codes([opp_leader['code']] * opp_life_n, cards_db) if opp_life_n else []

            populate_full_deck_knowledge(human, human_deck[1], human_deck[0].code)
            populate_full_deck_knowledge(opp, opp_deck[1], opp_deck[0].code)
            human.don_available = don_est.available(human_side_label)

            attacker = opp.leader if opp.leader.code == attacker_code else next(
                (c for c in opp.field_chars if c.code == attacker_code), None)
            if attacker is None:
                continue
            attacker.don_attached = don_on_attacker.get(attacker_code, 0)
            atk_power = attack_time_power(attacker, human)

            target = None
            if ttype == 'character' and tcode:
                target = next((c for c in human.field_chars if c.code == tcode), None)

            eng = DecisionEngine(human, opp)
            try:
                blocker = eng.should_use_blocker(atk_power)
            except Exception as exc:
                rows.append({'game': os.path.basename(parsed_path), 'turn': turn['turn'], 'error': f'blocker: {exc}'})
                continue

            defend_power = (human.leader.power + human.leader.power_buff if ttype == 'leader'
                            else (target.power + target.power_buff if target else atk_power))
            needed = max(0, atk_power - defend_power + 1)
            try:
                escolha, gasto, total = eng.pick_counters(needed) if not blocker and needed > 0 else ([], 0.0, 0)
                would_counter = eng.should_use_counter(atk_power, defend_power) if not blocker else False
            except Exception:
                escolha, would_counter = [], False
            motor_counter_codes = [c.code for c in escolha] if would_counter else []

            hist_blocked = bool(act.get('blocked_by'))
            hist_countered_codes = [CODE_RE.search(x).group(1) if CODE_RE.search(x) else x
                                    for x in (act.get('countered_by') or [])]
            hist_ambiguous = (act.get('result') == 'blocked' and not hist_blocked and not hist_countered_codes)
            if hist_ambiguous:
                continue  # schema do log nao distingue blocker de counter aqui -- excluido, nao contado como erro

            rows.append({
                'game': os.path.basename(parsed_path), 'turn': turn['turn'],
                'attacker': attacker_code,
                'hist_blocked': hist_blocked,
                'engine_blocked': bool(blocker),
                'hist_blocker_card': act.get('blocked_by'),
                'engine_blocker_card': blocker.code if blocker else None,
                'hist_countered': bool(hist_countered_codes),
                'engine_countered': bool(motor_counter_codes),
                'hist_counter_codes': hist_countered_codes,
                'engine_counter_codes': motor_counter_codes,
            })
    return {'rows': rows}


def _run_one(task):
    parsed_path, human_side_label, human_leader, game_id = task
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()
    full_path = os.path.join(LOGS_DIR, parsed_path)
    off = _offense_verdict(full_path, human_side_label, cards_db, df_raw, urls)
    de = _defense_verdict(full_path, human_side_label, cards_db, df_raw, urls)
    return {'game_id': game_id, 'human_leader': human_leader, 'offense': off, 'defense': de}


def _pct(n, d):
    return f'{n}/{d} ({n / d * 100:.1f}%)' if d else 'sem dados'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--log')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--leader')
    ap.add_argument('--workers', type=int, default=1)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.log:
        idx = json.load(open(os.path.join(LOGS_DIR, 'index.json'), encoding='utf-8'))
        entry = next((e for e in idx if e.get('parsed_file') == args.log or e.get('id') == args.log), None)
        if not entry or not entry.get('bot_side'):
            raise SystemExit(f'log nao encontrado ou sem bot_side: {args.log}')
        bs = entry['bot_side']
        human_key = 'p2' if bs == 'p1' else 'p1'
        jobs = [(entry['parsed_file'], 'Opponent' if bs == 'p1' else 'You',
                 entry[human_key]['leader_code'], entry['id'])]
    else:
        jobs = find_bot_vs_human_logs(args.leader)
        if not jobs:
            raise SystemExit('nenhum log bot-vs-humano encontrado')

    print(f'{len(jobs)} log(s) a auditar (ofensiva + defesa)...')
    if args.workers <= 1:
        resultados = [_run_one(t) for t in jobs]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            resultados = list(ex.map(_run_one, jobs))

    off_rows, def_rows = [], []
    for r in resultados:
        if 'error' not in r['offense']:
            off_rows.extend(r['offense']['rows'])
        elif r['offense'].get('error'):
            print(f"  ERRO ofensiva {r['game_id']}: {r['offense']['error']}")
        if 'error' not in r['defense']:
            def_rows.extend([row for row in r['defense']['rows'] if 'error' not in row])
        elif r['defense'].get('error'):
            print(f"  ERRO defesa {r['game_id']}: {r['defense']['error']}")

    print(f'\n{"="*72}')
    print(f'DECISION QUALITY FULL vs HUMANO -- {len(jobs)} partida(s)')
    print(f'{"="*72}')

    print(f'\n--- OFENSIVA (turno proprio, {len(off_rows)} turnos) ---')
    for label, key, has_key in [
        ('play (mesmas cartas jogadas)', 'play_match', 'play_has_data'),
        ('attack -- QUEM atacou (mesmo conjunto)', 'attack_quem_match', 'attack_has_data'),
        ('activate (mesmas cartas ativaram)', 'activate_match', 'activate_has_data'),
        ('attach_don -- MESMO alvo recebeu DON', 'don_alvo_match', 'don_has_data'),
    ]:
        base = [r for r in off_rows if r[has_key]]
        n_ok = sum(1 for r in base if r[key])
        print(f'  {label}: {_pct(n_ok, len(base))}  (turnos com dado: {len(base)}/{len(off_rows)})')

    total_common = sum(r['attack_alvo_common'] for r in off_rows)
    total_alvo_ok = sum(r['attack_alvo_match'] for r in off_rows)
    print(f'  attack -- MESMO ALVO (dos atacantes em comum): {_pct(total_alvo_ok, total_common)}')

    print(f'\n--- DEFESA (turno do oponente, {len(def_rows)} ataques sofridos) ---')
    n = len(def_rows)
    blocker_ok = sum(1 for r in def_rows if r['hist_blocked'] == r['engine_blocked'])
    print(f'  blocker (bloquear ou nao): {_pct(blocker_ok, n)}')
    both_blocked = [r for r in def_rows if r['hist_blocked'] and r['engine_blocked']]
    blocker_card_ok = sum(1 for r in both_blocked if r['hist_blocker_card'] == r['engine_blocker_card'])
    print(f'  blocker -- MESMA CARTA (quando os 2 bloquearam): {_pct(blocker_card_ok, len(both_blocked))}')

    not_blocked = [r for r in def_rows if not r['hist_blocked'] and not r['engine_blocked']]
    counter_ok = sum(1 for r in not_blocked if r['hist_countered'] == r['engine_countered'])
    print(f'  counter (usar ou nao, so quando NAO bloqueou): {_pct(counter_ok, len(not_blocked))}')
    both_countered = [r for r in not_blocked if r['hist_countered'] and r['engine_countered']]
    cartas_ok = sum(1 for r in both_countered if set(r['hist_counter_codes']) == set(r['engine_counter_codes']))
    print(f'  counter -- MESMO CONJUNTO de cartas: {_pct(cartas_ok, len(both_countered))}')
    multi = [r for r in both_countered if len(r['hist_counter_codes']) > 1 or len(r['engine_counter_codes']) > 1]
    ordem_ok = sum(1 for r in multi if r['hist_counter_codes'] == r['engine_counter_codes'])
    print(f'  counter -- MESMA ORDEM (quando 2+ cartas): {_pct(ordem_ok, len(multi))}')

    out_path = os.path.join(OUT_DIR, 'ultimo_resultado.json')
    json.dump({'offense': off_rows, 'defense': def_rows}, open(out_path, 'w', encoding='utf-8'),
              indent=2, ensure_ascii=False)
    print(f'\nResultado completo salvo em {out_path}')


if __name__ == '__main__':
    main()
