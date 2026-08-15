"""
Compara o motor de HOJE com as flags de calibragem dinamica por curva do
deck (USE_*_CURVE_SCALE, decision_engine.py, blocos 529-534) DESLIGADAS
(comportamento atual em producao) vs LIGADAS (todas), reconstruindo o lado
VENCEDOR (humano) de partidas reais que o bot perdeu -- reusa
`audit_real_losses.audit_one_game` com `bot_side='Opponent'` (a funcao e
generica, so muda qual lado e reconstruido).

Continuacao do bloco HANDOFF 535 (sessao remota): o script equivalente
(`compare_human_vs_engine.py`) foi descartavel/scratchpad, nunca commitado
-- essa versao fica permanente pra nao reescrever do zero na proxima vez.

Licao do bloco 534 (nao repetir): `_remaining_deck` (dentro de
`audit_one_game`) embaralha o deck restante via `random.shuffle` SEM seed
propria. Comparar OFF vs ON em 2 chamadas separadas SEM fixar
`random.seed()` idêntico antes de CADA chamada contamina a comparacao com
ruido de ordem de deck, nao efeito real das flags -- por isso este script
sempre fixa a MESMA seed antes de cada chamada de `audit_one_game`.

Uso:
    python audit_curve_calibration_flags.py --limit N   # so os N mais recentes
    python audit_curve_calibration_flags.py --all       # todos os disponiveis
"""
import argparse
import json
import os
import random
import time

import pandas as pd

import optcg_engine.decision_engine as de
from audit_real_losses import audit_one_game, find_real_bot_losses
from optcg_engine.decision_engine import load_cards_db

OUT_DIR = os.path.join('metrics', 'curve_calibration_audits')

# As 8 flags "calibragem dinamica por curva do deck" (blocos 529-533),
# todas False em producao hoje. is_closing_mode (bloco 534) nao tem flag
# propria -- so afeta o resultado quando DMG/BOARD/LIFE_VALUE ja estao ON.
CURVE_FLAGS = [
    'USE_DON_FIELD_CURVE_SCALE',
    'USE_HAND_VALUE_CURVE_SCALE',
    'USE_BOARD_VALUE_CURVE_SCALE',
    'USE_LIFE_VALUE_CURVE_SCALE',
    'USE_DMG_VALUE_CURVE_SCALE',
    'USE_COUNTER_HAND_CURVE_SCALE',
    'USE_COVERAGE_CURVE_SCALE',
    'USE_OPP_BLOCKER_CURVE_SCALE',
]

SEED = 20260814  # fixa, mesma pros dois lados de cada partida (ver docstring)


def _set_flags(value: bool) -> None:
    for name in CURVE_FLAGS:
        setattr(de, name, value)


def run_one(pf: str, cards_db, df_raw, urls) -> dict:
    random.seed(SEED)
    _set_flags(False)
    off = audit_one_game(os.path.join('logs', pf), 'Opponent', cards_db, df_raw, urls)

    random.seed(SEED)
    _set_flags(True)
    on = audit_one_game(os.path.join('logs', pf), 'Opponent', cards_db, df_raw, urls)

    _set_flags(False)  # nunca deixa ligado pro resto do processo

    if off.get('error') or on.get('error'):
        return {'parsed_file': pf, 'error': off.get('error') or on.get('error')}

    turnos_off = {t['turn']: t for t in off['turnos']}
    turnos_on = {t['turn']: t for t in on['turnos']}
    divergentes = []
    for turno in sorted(set(turnos_off) & set(turnos_on)):
        n_off = turnos_off[turno].get('engine_hoje_narrativa', '')
        n_on = turnos_on[turno].get('engine_hoje_narrativa', '')
        if n_off != n_on:
            divergentes.append({
                'turn': turno,
                'historical_actions': turnos_off[turno].get('historical_actions', []),
                'narrativa_off': n_off,
                'narrativa_on': n_on,
            })

    return {
        'parsed_file': pf,
        'bot_leader': off.get('bot_leader'),
        'opp_leader': off.get('opp_leader'),
        'turnos_auditados': len(turnos_off),
        'turnos_divergentes': len(divergentes),
        'divergencias': divergentes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--limit', type=int, default=None,
                    help='so os N jogos mais recentes (default: todos)')
    ap.add_argument('--all', action='store_true', help='(default) todos os disponiveis')
    args = ap.parse_args()

    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    games = find_real_bot_losses()
    if args.limit:
        games = games[-args.limit:]
    print(f'{len(games)} partidas (vitoria real do humano) a auditar')

    os.makedirs(OUT_DIR, exist_ok=True)
    resultados = []
    total_turnos = 0
    total_divergentes = 0
    erros = 0
    t0 = time.time()
    for i, (pf, _bot_side) in enumerate(games, 1):
        nome = os.path.basename(pf)
        r = run_one(pf, cards_db, df_raw, urls)
        resultados.append(r)
        if r.get('error'):
            erros += 1
            print(f'[{i}/{len(games)}] {nome}: ERRO -- {r["error"]}')
            continue
        total_turnos += r['turnos_auditados']
        total_divergentes += r['turnos_divergentes']
        print(f'[{i}/{len(games)}] {nome}: {r["turnos_divergentes"]}/{r["turnos_auditados"]} '
              f'turnos divergentes ({r["bot_leader"]} venceu vs {r["opp_leader"]})')

    dt = time.time() - t0
    print()
    print(f'TOTAL: {total_divergentes}/{total_turnos} turnos divergentes '
          f'({100 * total_divergentes / total_turnos:.1f}%), {erros} jogos com erro '
          f'de reconstrucao, {dt:.1f}s')

    out_path = os.path.join(OUT_DIR, f'audit_{time.strftime("%Y-%m-%dT%H.%M.%S")}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            'seed': SEED,
            'flags': CURVE_FLAGS,
            'total_turnos': total_turnos,
            'total_divergentes': total_divergentes,
            'erros': erros,
            'jogos': resultados,
        }, f, ensure_ascii=False, indent=2)
    print(f'Relatorio completo salvo em {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
