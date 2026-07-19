"""
Diagnostico (NAO fix): compara a alocacao de DON que can_lethal_this_turn_alloc()
certifica como suficiente para lethal garantido contra o DON que a politica real
de anexacao (don_needed_for_attack + _don_livre_for_plan) de fato daria pros
MESMOS atacantes, no MESMO estado. Valida a hipotese registrada em
GUIA_AUDITORIA_DECISOES.md secao 8 antes de qualquer mudanca de codigo.

Uso:
    python diag_lethal_don_alloc.py --n 20 --seed 7
"""
import argparse
import random
from pathlib import Path

from optcg_engine.decision_engine import (
    DecisionEngine,
    GameAnalyzer,
    OPTCGMatch,
    build_real_deck,
    don_needed_for_attack,
    load_cards_db,
    validar_deck,
)

ROOT = Path(__file__).resolve().parent

_ORIG_PRIORITY = GameAnalyzer.analysis_priority
_CASES = []
_CURRENT_MATCH = None  # setado pelo loop de main() antes de match.simulate()
_RECORDING = False  # trava de reentrancia -- ver _record_case


def _patched_priority(self):
    result = _ORIG_PRIORITY(self)
    global _RECORDING
    # _record_case chama _don_livre_for_plan, que por sua vez chama
    # _generate_and_score_actions -- que RECAI em analysis_priority() pro
    # MESMO estado (ainda LETHAL) e reentraria em _record_case
    # infinitamente/exponencialmente. Trava impede a reentrada: so grava a
    # PRIMEIRA vez que este estado e' visto, ignora as chamadas aninhadas
    # disparadas pela propria instrumentacao.
    if result == 'LETHAL' and not _RECORDING:
        _RECORDING = True
        try:
            ok, alloc = self.can_lethal_this_turn_alloc()
            if ok:
                _record_case(self, alloc)
        finally:
            _RECORDING = False
    return result


def _record_case(analyzer: GameAnalyzer, alloc):
    p, opp = analyzer.me, analyzer.opp
    # _don_livre_for_plan/_attach_don_for_attack sao metodos de OPTCGMatch
    # (nao de DecisionEngine) -- usam self.state_a/model_for_a etc. Um
    # DecisionEngine solto so serve pra passar como `engine` posicional pra
    # don_needed_for_attack (que so le engine.analyzer/_don_reserve_for_defense).
    engine = DecisionEngine(p, opp)
    don_livre = _CURRENT_MATCH._don_livre_for_plan(p, opp, engine)
    rows = []
    for attacker, don_certificado in alloc:
        real = don_needed_for_attack(attacker, 'leader', None, p, opp, engine,
                                     don_livre=don_livre)
        rows.append({
            'attacker': attacker.name,
            'don_certificado': don_certificado,
            'don_real_atribuido': real,
            'gap': don_certificado - real,
        })
    _CASES.append({
        'turn': p.turn,
        'don_available': p.don_available,
        'don_livre_for_plan': don_livre,
        'opp_life': opp.life_count(),
        'opp_field': len(opp.field_chars),
        'opp_blockers_active': len(opp.blockers_active()),
        'rows': rows,
    })


def load_real_decks(limit: int):
    cards_db = load_cards_db(str(ROOT / 'cards_rows.csv'))
    import pandas as pd
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--decks', type=int, default=16)
    args = ap.parse_args()

    GameAnalyzer.analysis_priority = _patched_priority
    try:
        random.seed(args.seed)
        decks = load_real_decks(args.decks)
        if len(decks) < 2:
            print('ERRO: menos de 2 decks validos carregados.')
            return 2

        import contextlib
        import io
        for i in range(args.n):
            idx_a, idx_b = random.sample(range(len(decks)), 2)
            _name_a, deck_a = decks[idx_a]
            _name_b, deck_b = decks[idx_b]
            try:
                global _CURRENT_MATCH
                match = OPTCGMatch(deck_a, deck_b)
                _CURRENT_MATCH = match
                with contextlib.redirect_stdout(io.StringIO()):
                    match.simulate()
            except Exception as exc:
                print(f'  partida {i+1}/{args.n}: EXCECAO {type(exc).__name__}: {exc}')
    finally:
        GameAnalyzer.analysis_priority = _ORIG_PRIORITY

    print(f'\n{len(_CASES)} momento(s) com priority=LETHAL certificado (ok=True)')
    gaps = 0
    for case in _CASES:
        rows_txt = '; '.join(
            f"{r['attacker'][:18]} certificado={r['don_certificado']} real={r['don_real_atribuido']}"
            for r in case['rows']
        )
        any_gap = any(r['gap'] > 0 for r in case['rows'])
        gaps += int(any_gap)
        marker = 'GAP' if any_gap else 'ok '
        print(f"[{marker}] T{case['turn']} don_disp={case['don_available']} "
              f"don_livre_plan={case['don_livre_for_plan']} opp_vida={case['opp_life']} "
              f"opp_campo={case['opp_field']} opp_blockers={case['opp_blockers_active']} :: {rows_txt}")

    print(f"\nResumo: {gaps}/{len(_CASES)} casos LETHAL onde a alocacao real "
          f"de DON e' MENOR que a alocacao certificada (gap > 0 em pelo menos 1 atacante).")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
