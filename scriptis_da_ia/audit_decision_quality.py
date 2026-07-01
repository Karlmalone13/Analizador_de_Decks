"""
Auditoria de qualidade de decisao do motor.

Roda partidas simuladas com `decision_log` ligado e resume como o Turn Planner
escolheu as acoes: contexto, top imediato, candidatos simulados e escolha final.

Uso:
    python scriptis_da_ia/audit_decision_quality.py --n 10 --seed 42
    python scriptis_da_ia/audit_decision_quality.py --n 25 --seed 7 --json-out audit.json
"""
import argparse
import contextlib
import io
import json
import random
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from optcg_engine.decision_engine import (
    OPTCGMatch,
    build_real_deck,
    load_cards_db,
    validar_deck,
)


ROOT = Path(__file__).resolve().parent


def load_real_decks(limit: int):
    cards_db = load_cards_db(str(ROOT / 'cards_rows.csv'))
    df_raw = pd.read_csv(ROOT / 'decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    decks = []
    for url, name in urls.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if not result:
            continue
        leader, cards, start_stage = result
        valido, _erros = validar_deck(leader, cards, cards_db)
        if valido and len(cards) >= 40:
            decks.append((name, (leader, cards, start_stage)))
        if len(decks) >= limit:
            break
    return decks


def action_label(action: dict | None) -> str:
    if not action:
        return '-'
    card = action.get('card') or {}
    target = action.get('target') or {}
    target_txt = ''
    if action.get('target_type'):
        target_txt = f" -> {action.get('target_type')}"
        if target:
            target_txt += f" {target.get('code', '')}"
    wins = action.get('simulated_wins')
    samples = action.get('simulated_samples')
    win_txt = ''
    if wins is not None and samples:
        win_txt = f" win={wins}/{samples}"
    return (f"{action.get('kind')} {card.get('code', '')} "
            f"{card.get('name', '')[:28]}{target_txt} "
            f"score={action.get('score')}"
            f" sim={action.get('simulated_value')}{win_txt}")


def summarize(entries: list[dict], examples_limit: int):
    planner = [e for e in entries if e.get('kind') == 'turn_planner']
    chosen_kinds = Counter((e.get('chosen') or {}).get('kind') for e in planner)
    top_kinds = Counter((e.get('top_immediate') or {}).get('kind') for e in planner)
    priorities = Counter((e.get('context') or {}).get('priority') for e in planner)

    overrides = []
    early_activates = []
    nonlethal_zero_life_attacks = []

    for e in planner:
        ctx = e.get('context') or {}
        chosen = e.get('chosen') or {}
        top = e.get('top_immediate') or {}
        if chosen.get('kind') != top.get('kind') or (
                (chosen.get('card') or {}).get('code') != (top.get('card') or {}).get('code')):
            gap = float(top.get('score') or 0) - float(chosen.get('score') or 0)
            if gap >= 60:
                overrides.append((gap, e))

        chosen_card = chosen.get('card') or {}
        if (chosen.get('kind') == 'activate'
                and ctx.get('phase') == 'early'
                and ctx.get('field', 0) <= 1):
            early_activates.append(e)

        if (chosen.get('kind') == 'attack'
                and ctx.get('opp_life') == 0
                and not ctx.get('can_lethal')):
            nonlethal_zero_life_attacks.append(e)

    overrides.sort(key=lambda x: x[0], reverse=True)

    return {
        'total_planner_steps': len(planner),
        'chosen_kinds': dict(chosen_kinds),
        'top_immediate_kinds': dict(top_kinds),
        'priorities': dict(priorities),
        'large_overrides': [e for _gap, e in overrides[:examples_limit]],
        'early_activates': early_activates[:examples_limit],
        'nonlethal_zero_life_attacks': nonlethal_zero_life_attacks[:examples_limit],
    }


def print_examples(title: str, examples: list[dict]):
    print(f'\n{title}: {len(examples)} exemplo(s) exibidos')
    for e in examples:
        ctx = e.get('context') or {}
        print(f" - T{e.get('turn')} P{e.get('player')} "
              f"prio={ctx.get('priority')} fase={ctx.get('phase')} "
              f"vida={ctx.get('life')}/{ctx.get('opp_life')} "
              f"campo={ctx.get('field')}/{ctx.get('opp_field')} "
              f"DON={ctx.get('don_available')}")
        print(f"   top:     {action_label(e.get('top_immediate'))}")
        print(f"   escolha: {action_label(e.get('chosen'))}")
        cand = e.get('candidates') or []
        for c in cand[:4]:
            print(f"     cand: {action_label(c)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--n', type=int, default=10, help='numero de partidas')
    ap.add_argument('--seed', type=int, default=42, help='seed reproducivel')
    ap.add_argument('--decks', type=int, default=16, help='decks reais a carregar')
    ap.add_argument('--examples', type=int, default=8, help='exemplos por bloco')
    ap.add_argument('--json-out', default='', help='salva relatorio JSON')
    args = ap.parse_args()

    random.seed(args.seed)
    decks = load_real_decks(args.decks)
    if len(decks) < 2:
        print('ERRO: menos de 2 decks validos carregados.')
        return 2

    all_entries = []
    matches = []
    exceptions = []

    for i in range(args.n):
        idx_a, idx_b = random.sample(range(len(decks)), 2)
        name_a, deck_a = decks[idx_a]
        name_b, deck_b = decks[idx_b]
        try:
            match = OPTCGMatch(deck_a, deck_b)
            match.enable_decision_audit()
            with contextlib.redirect_stdout(io.StringIO()):
                result = match.simulate()
            dlog = match.decision_log or []
            all_entries.extend(dlog)
            matches.append({
                'i': i,
                'deck_a': name_a,
                'deck_b': name_b,
                'winner': result.get('winner'),
                'turns': result.get('turns'),
                'planner_steps': sum(1 for e in dlog if e.get('kind') == 'turn_planner'),
            })
            print(f'  Match {i+1}/{args.n}: {name_a[:22]} vs {name_b[:22]} '
                  f'-> {result.get("winner")} em {result.get("turns")} turnos')
        except Exception as exc:
            exceptions.append({
                'i': i,
                'deck_a': name_a,
                'deck_b': name_b,
                'error': f'{type(exc).__name__}: {exc}',
            })
            print(f'  Match {i+1}/{args.n}: EXCECAO {type(exc).__name__}: {exc}')

    report = summarize(all_entries, args.examples)
    report['matches'] = matches
    report['exceptions'] = exceptions

    print('\n' + '=' * 72)
    print(f'Auditoria de decisao: {args.n} partidas, seed={args.seed}')
    print(f'Planner steps: {report["total_planner_steps"]} | excecoes: {len(exceptions)}')
    print(f'Escolhas finais: {report["chosen_kinds"]}')
    print(f'Top imediato:    {report["top_immediate_kinds"]}')
    print(f'Prioridades:     {report["priorities"]}')
    print('=' * 72)

    print_examples('Overrides grandes do planner', report['large_overrides'])
    print_examples('Activate cedo com campo pequeno', report['early_activates'])
    print_examples('Ataque em vida 0 sem lethal garantido',
                   report['nonlethal_zero_life_attacks'])

    if args.json_out:
        out = Path(args.json_out)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\nJSON salvo em: {out}')

    return 1 if exceptions else 0


if __name__ == '__main__':
    sys.exit(main())
