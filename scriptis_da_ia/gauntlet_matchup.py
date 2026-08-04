"""
Gauntlet controlado: um deck fixo vs um roster fixo de arquétipos reais do
meta (decklists_raw.csv), com seeds fixas por matchup -- controla adversário
e sorte pra isolar "decisão ruim" de "matchup ruim/RNG".

Diferença pro `bot_efficiency_report.py` (que lê logs REAIS já jogados):
aqui o motor joga os dois lados via self-play (`OPTCGMatch`/`ReplayMatch`),
então dá pra escolher QUALQUER adversário do banco de decklists reais e
repetir a mesma seed pra cada um -- não depende de já existir log de
partida real contra aquele arquétipo específico.

Criado 04/08/2026 pra calibração do combo de reanimação do Imu (HANDOFF
bloco 432/433): a comparação direta de vitória/derrota real (1 vitória
histórica) não tinha amostra suficiente. O gauntlet (70 partidas, 7
adversários x 10 seeds) revelou um padrão MUITO mais forte e reprodutível:
Imu vence folgado contra os 2 decks mais representados no meta (Enel 60%,
Nami 70%) mas perde muito contra decks agressivos/counter-densos (Ace 10%,
Mihawk 10%, Lucy 20%). Investigação (replay verbose de Ace seed=0, ver
HANDOFF 433) mostrou DON ficando ocioso enquanto o Imu ataca "seco" e
apanha de Counter -- MAS o `ATTACK_MARGIN_DON_FRACTION` que rege essa
margem já tinha sido calibrado e cross-validado contra DON/ataque real
(bloco 398, 29/07) e o padrão observado aqui (DON/ataque menor nas derrotas
de Ace que na vitória) bate com o padrão já usado pra calibrar a constante
-- não é um bug novo, é o dial existente reagindo a um matchup
estruturalmente desfavorável (aggro/counter-denso vs controle/reanimação).
Não mexer em `ATTACK_MARGIN_DON_FRACTION`/`_don_reserve_for_defense` por
causa só deste gauntlet sem log real desses matchups pra cross-validar.

Uso:
    python gauntlet_matchup.py
"""
import random
import sys
import contextlib
import io
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replay_optcg import ReplayMatch
from optcg_engine.decision_engine import build_real_deck, load_cards_db, validar_deck, OPTCGMatch
import pandas as pd

cards_db = load_cards_db('cards_rows.csv')
df_raw = pd.read_csv('decklists_raw.csv')
urls = df_raw.groupby('deck_url')['deck_name'].first()

# Roster escolhido pelos arquétipos mais representados em decklists_raw.csv
# (meta real de torneio): Enel (70 decks), Nami (30), Ace (19), Mihawk (16),
# Lucy (16), Luffy-Amarelo (8), Rosinante (6), + espelho (outro build de Imu).
ROSTER_NAMES = {
    'Enel':      'Purple Enelby Mirko Zanelli',
    'Nami':      'Blue/Yellow Namiby AceOfSpades',
    'Ace':       'Red/Blue Aceby Tzuwy',
    'Mihawk':    'Green Mihawkby Phi Nguyen',
    'Lucy':      'Red/Blue Lucyby Magyo',
    'Luffy-Y':   'Yellow Luffyby David Melendo Villena',
    'Rosinante': 'Purple/Yellow Rosinanteby Matt',
}
FIXED_NAME = 'Black Imuby Spence Gibson'
FIXED_MIRROR_NAME = 'Black Imuby Adderall'
N_SEEDS = 10
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'metrics', 'gauntlet_imu_04_08.json')


def find_deck(target_name):
    for url, name in urls.items():
        if name == target_name:
            result = build_real_deck(name, url, df_raw, cards_db)
            if not result:
                return None
            leader, cards, stage = result
            valido, erros = validar_deck(leader, cards, cards_db)
            if not valido:
                return None
            return (leader, cards, stage)
    return None


def main():
    fixed_deck = find_deck(FIXED_NAME)
    fixed_mirror_deck = find_deck(FIXED_MIRROR_NAME)
    assert fixed_deck and fixed_mirror_deck, "deck fixo nao encontrado"

    roster = {}
    for label, name in ROSTER_NAMES.items():
        d = find_deck(name)
        if d:
            roster[label] = d
        else:
            print(f'AVISO: {label} ({name}) nao encontrado/invalido')
    roster['Mirror'] = fixed_mirror_deck

    print(f'Roster final: {list(roster.keys())}')
    print(f'Deck fixo: {FIXED_NAME}')
    print()

    original_execute_attack = OPTCGMatch._execute_attack
    captured = []

    def patched_execute_attack(self, attacker, target_type, target, p, opp, engine, verbose=False, attached_don=0):
        if p is self._fixed_side_marker:
            captured.append(attacker.don_attached)
        return original_execute_attack(self, attacker, target_type, target, p, opp, engine, verbose=verbose, attached_don=attached_don)

    OPTCGMatch._execute_attack = patched_execute_attack

    resultados = {}
    try:
        for label, opp_deck in roster.items():
            linhas = []
            for seed in range(N_SEEDS):
                random.seed(1000 + seed)
                captured.clear()

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    match = ReplayMatch(fixed_deck, opp_deck, 'Fixo', label)
                    match.setup()
                    eng = match._get_engine_match()
                    eng._fixed_side_marker = match.state_a
                    vencedor = None
                    turn_num = 0
                    for turn_num in range(match.MAX_TURNS * 2):
                        p = (match.state_a if match.state_a.is_first else match.state_b) \
                            if turn_num % 2 == 0 \
                            else (match.state_b if match.state_a.is_first else match.state_a)
                        opp = match.state_b if p is match.state_a else match.state_a
                        vencedor = eng.play_turn(p, opp, verbose=False)
                        if vencedor:
                            break

                fixo_won = (vencedor == 'A')
                n_ataques = len(captured)
                don_medio = sum(captured) / n_ataques if n_ataques else 0.0
                linhas.append({
                    'seed': seed, 'fixo_won': fixo_won,
                    'dmg_fixo': match.state_a.dmg_dealt, 'dmg_opp': match.state_b.dmg_dealt,
                    'turnos': turn_num, 'ataques_fixo': n_ataques, 'don_medio': don_medio,
                })
            resultados[label] = linhas
    finally:
        OPTCGMatch._execute_attack = original_execute_attack

    print(f'{"Adversario":15} {"WinRate":>8} {"Dano_medio":>11} {"DON/atk":>9} {"Ataques/turno":>14} {"Turnos_medio":>13}')
    agg_win, agg_dmg, agg_don, agg_atk_per_turn = [], [], [], []
    for label, linhas in resultados.items():
        n = len(linhas)
        wins = sum(1 for l in linhas if l['fixo_won'])
        win_rate = wins / n * 100
        dmg_medio = sum(l['dmg_fixo'] for l in linhas) / n
        dons = [l['don_medio'] for l in linhas if l['ataques_fixo'] > 0]
        don_medio = sum(dons) / len(dons) if dons else 0.0
        atk_turno = sum(l['ataques_fixo'] / max(1, l['turnos']) for l in linhas) / n
        turnos_medio = sum(l['turnos'] for l in linhas) / n
        print(f'{label:15} {win_rate:7.1f}% {dmg_medio:11.2f} {don_medio:9.2f} {atk_turno:14.2f} {turnos_medio:13.1f}')
        agg_win.extend([1 if l['fixo_won'] else 0 for l in linhas])
        agg_dmg.extend([l['dmg_fixo'] for l in linhas])
        agg_don.extend(dons)
        agg_atk_per_turn.extend([l['ataques_fixo'] / max(1, l['turnos']) for l in linhas])

    print()
    print(f'TOTAL: {len(agg_win)} partidas, win_rate={sum(agg_win)/len(agg_win)*100:.1f}%, '
          f'dano_medio={sum(agg_dmg)/len(agg_dmg):.2f}, don_medio={sum(agg_don)/len(agg_don):.2f}, '
          f'ataques_turno_medio={sum(agg_atk_per_turn)/len(agg_atk_per_turn):.2f}')

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w') as f:
        json.dump(resultados, f, indent=2)


if __name__ == '__main__':
    main()
