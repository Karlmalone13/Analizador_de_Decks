"""
Compliance checker por evidencia de execucao.

Roda partidas reais e instrumenta o motor para responder perguntas praticas:
- quais triggers parseados foram chamados;
- quais triggers chamados produziram log/efeito observavel;
- quais actions do banco chegaram ao executor;
- quais actions chamadas nunca produziram log na amostra.

Isto NAO prova fidelidade oficial carta-a-carta. E uma triagem de suspeitos:
efeito parseado que nunca dispara, action que parece no-op, ou trigger chamado
repetidamente sem efeito observavel.

Uso:
    python audit_card_effects.py --n 25 --seed 42
    python audit_card_effects.py --n 50 --seed 7 --json-out effect_audit.json
"""
import argparse
import contextlib
import io
import json
import random
import sys
import traceback
from collections import Counter
from pathlib import Path

import pandas as pd

from optcg_engine.decision_engine import (
    EffectExecutor,
    OPTCGMatch,
    build_real_deck,
    get_card_effects,
    load_cards_db,
    validar_deck,
)


ACTIVE_TRIGGERS = {
    'on_play',
    'main',
    'activate_main',
    'when_attacking',
    'when_rested',
    'on_opp_attack',
    'on_block',
    'on_ko',
    'trigger',
    'counter',
}


def load_real_decks(limit: int = 16):
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
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


def load_card_names():
    with open(Path(__file__).with_name('card_effects_db.json'), encoding='utf-8') as f:
        db = json.load(f)
    return {code: data.get('name', code) for code, data in db.items()}


def card_label(code: str, name: str, trigger: str) -> str:
    return f'{code} | {name[:32]} | {trigger}'


def iter_card_codes(deck_tuple):
    leader, cards, stage = deck_tuple
    yield leader.code
    if stage:
        yield stage.code
    for c in cards:
        yield c.code


def summarize_counter(counter: Counter, limit: int):
    return [{'key': list(k) if isinstance(k, tuple) else k, 'count': v}
            for k, v in counter.most_common(limit)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, default=25, help='numero de partidas')
    parser.add_argument('--seed', type=int, default=42, help='seed do random')
    parser.add_argument('--decks', type=int, default=16, help='quantos decks reais carregar')
    parser.add_argument('--top', type=int, default=30, help='quantos suspeitos mostrar por bloco')
    parser.add_argument('--min-calls', type=int, default=2, help='minimo de chamadas para suspeito sem log')
    parser.add_argument('--json-out', default='', help='salva relatorio JSON neste caminho')
    args = parser.parse_args()

    random.seed(args.seed)
    decks = load_real_decks(args.decks)
    if len(decks) < 2:
        print('ERRO: menos de 2 decks validos carregados.')
        return 2
    card_names = load_card_names()

    stats = {
        'trigger_calls': Counter(),
        'trigger_logs': Counter(),
        'trigger_steps': Counter(),
        'action_calls': Counter(),
        'action_logs': Counter(),
        'sampled_cards': Counter(),
        'matches': [],
        'exceptions': [],
    }

    original_execute = EffectExecutor.execute
    original_execute_step = EffectExecutor._execute_step

    def instrumented_execute(self, card, trigger, *a, **kw):
        effects = get_card_effects(card.code)
        block = effects.get(trigger)
        key = (card.code, card.name, trigger)
        if isinstance(block, dict):
            stats['trigger_calls'][key] += 1
            if block.get('steps') or block.get('choice') or block.get('conditional_stack'):
                stats['trigger_steps'][key] += 1
        logs = original_execute(self, card, trigger, *a, **kw)
        if isinstance(block, dict) and any(logs):
            stats['trigger_logs'][key] += 1
        return logs

    def instrumented_execute_step(self, step, card):
        action = step.get('action', '<sem action>') if isinstance(step, dict) else '<step invalido>'
        stats['action_calls'][action] += 1
        log = original_execute_step(self, step, card)
        if log:
            stats['action_logs'][action] += 1
        return log

    EffectExecutor.execute = instrumented_execute
    EffectExecutor._execute_step = instrumented_execute_step

    try:
        for i in range(args.n):
            idx_a, idx_b = random.sample(range(len(decks)), 2)
            name_a, deck_a = decks[idx_a]
            name_b, deck_b = decks[idx_b]

            for code in iter_card_codes(deck_a):
                stats['sampled_cards'][code] += 1
            for code in iter_card_codes(deck_b):
                stats['sampled_cards'][code] += 1

            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = OPTCGMatch(deck_a, deck_b).simulate()
                stats['matches'].append({
                    'i': i,
                    'deck_a': name_a,
                    'deck_b': name_b,
                    'winner': result.get('winner'),
                    'turns': result.get('turns'),
                })
                print(f'  Match {i+1}/{args.n}: {name_a[:20]} vs {name_b[:20]} '
                      f'-> vencedor={result.get("winner")}, turnos={result.get("turns")}')
            except Exception as exc:
                tb = traceback.format_exc()
                stats['exceptions'].append({
                    'i': i,
                    'deck_a': name_a,
                    'deck_b': name_b,
                    'error': f'{type(exc).__name__}: {exc}',
                    'traceback_tail': tb[-1200:],
                })
                print(f'  Match {i+1}/{args.n}: EXCECAO {type(exc).__name__}: {exc}')
    finally:
        EffectExecutor.execute = original_execute
        EffectExecutor._execute_step = original_execute_step

    trigger_no_log = []
    for key, calls in stats['trigger_calls'].items():
        if calls < args.min_calls:
            continue
        code, name, trigger = key
        if trigger not in ACTIVE_TRIGGERS:
            continue
        logs = stats['trigger_logs'][key]
        if stats['trigger_steps'][key] and logs == 0:
            trigger_no_log.append((calls, code, name, trigger))
    trigger_no_log.sort(reverse=True)

    action_no_log = []
    for action, calls in stats['action_calls'].items():
        if calls >= args.min_calls and stats['action_logs'][action] == 0:
            action_no_log.append((calls, action))
    action_no_log.sort(reverse=True)

    never_called = []
    seen_codes = set(stats['sampled_cards'])
    for code in seen_codes:
        effects = get_card_effects(code)
        for trigger, block in effects.items():
            if trigger not in ACTIVE_TRIGGERS or not isinstance(block, dict):
                continue
            if not (block.get('steps') or block.get('choice') or block.get('conditional_stack')):
                continue
            called = sum(v for (c, _n, t), v in stats['trigger_calls'].items()
                         if c == code and t == trigger)
            if called == 0:
                name = next((n for (c, n, _t) in stats['trigger_calls'] if c == code), '')
                if not name:
                    name = card_names.get(code, code)
                never_called.append((stats['sampled_cards'][code], code, name, trigger))
    never_called.sort(reverse=True)

    print()
    print('=' * 72)
    print(f'Compliance por execucao: {args.n} partidas, seed={args.seed}, decks={len(decks)}')
    print(f'Excecoes: {len(stats["exceptions"])}')
    print(f'Triggers chamados: {len(stats["trigger_calls"])} tipos | '
          f'Actions chamadas: {len(stats["action_calls"])} tipos')
    print('=' * 72)

    print('\nTriggers chamados com steps, mas sem log observavel:')
    if trigger_no_log:
        for calls, code, name, trigger in trigger_no_log[:args.top]:
            print(f' - {calls:4d}x {card_label(code, name, trigger)}')
    else:
        print(' - nenhum acima do limiar')

    print('\nActions executadas sem log observavel:')
    if action_no_log:
        for calls, action in action_no_log[:args.top]:
            print(f' - {calls:4d}x {action}')
    else:
        print(' - nenhuma acima do limiar')

    print('\nTriggers de cartas amostradas que nunca foram chamados:')
    if never_called:
        for deck_hits, code, name, trigger in never_called[:args.top]:
            print(f' - visto em {deck_hits:3d} deck-copias | {card_label(code, name, trigger)}')
    else:
        print(' - nenhum na amostra')

    if stats['exceptions']:
        print('\nExcecoes:')
        for exc in stats['exceptions'][:10]:
            print(f' - Match {exc["i"]}: {exc["error"]}')

    if args.json_out:
        report = {
            'args': vars(args),
            'matches': stats['matches'],
            'exceptions': stats['exceptions'],
            'trigger_calls': summarize_counter(stats['trigger_calls'], 1000),
            'trigger_logs': summarize_counter(stats['trigger_logs'], 1000),
            'action_calls': summarize_counter(stats['action_calls'], 1000),
            'action_logs': summarize_counter(stats['action_logs'], 1000),
            'trigger_no_log': trigger_no_log[:1000],
            'action_no_log': action_no_log[:1000],
            'never_called': never_called[:1000],
        }
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f'\nJSON salvo em: {args.json_out}')

    return 1 if stats['exceptions'] else 0


if __name__ == '__main__':
    sys.exit(main())
