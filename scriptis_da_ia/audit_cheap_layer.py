"""
audit_cheap_layer.py -- auditoria PERMANENTE da camada barata da fase 1 da
"calibragem dinamica" (bloco 508/509, pedido explicito do usuario 11/08:
"quero que deixe isso bem registrado e tb crie uma forma de auditoria dessa
nova funcao").

`_cheap_rollout_value` (optcg_engine/decision_engine.py) aproxima o valor de
uma acao candidata SEM resolver o efeito de verdade -- so usa as flags ja
pre-parseadas (get_card_flags) sobre um resumo grosseiro do estado. Ela
alimenta `_select_search_candidates` (via `cheap_values=`) pra ALARGAR o
shortlist que recebe a busca cara, mas NUNCA decide a acao final sozinha.
Esse desenho so vale a pena se o sinal barato for CONFIAVEL -- este script
mede isso empiricamente contra a busca real, em vez de aceitar por
construcao. Roda self-play com USE_CHEAP_LAYER_SHORTLIST ligado (desligado
por padrao no motor) e le o `decision_log` (kind='turn_planner') pra
responder 3 perguntas:

1. CONCORDANCIA: quando uma candidata tem tanto `cheap_value` quanto
   `simulated_value` (a busca real) no MESMO turno, o RANKING do sinal
   barato bate com o da busca real? (a candidata de maior cheap_value
   tambem e a de maior simulated_value?) -- mede se o sinal barato e
   confiavel OU enganoso.
2. ALARGAMENTO: quantas decisoes tiveram pelo menos 1 candidata adicionada
   SO pela camada barata (`added_by_cheap_layer=True`, nao entraria no
   shortlist pelo score estatico sozinho) -- quanto isso aconteceu de
   verdade, nao so em teoria.
3. VALOR REAL DO ALARGAMENTO (a pergunta mais importante): das candidatas
   que SO a camada barata promoveu, quantas viraram a ESCOLHIDA final
   (`chosen`) depois da busca real as reavaliar? Se for ~0%, o alargamento
   so gasta orcamento de busca a toa; se for uma fracao real, a camada
   barata esta pegando valor que o score estatico sozinho perderia.

Uso: python audit_cheap_layer.py --leader OP13-079 --n 20 [--seed S]
     [--workers W] [--pool-size N]

Mesmo padrao de decoupling de processo de decision_quality_report.py
(bloco 485) -- cada worker carrega o proprio pool de decks, seed derivada
por indice (seed_base * 1_000_003 + i, nunca random.seed() encadeado).
"""
import argparse
import concurrent.futures
import contextlib
import io
import random

import pandas as pd

from replay_optcg import ReplayMatch
from optcg_engine import decision_engine as de
from optcg_engine.decision_engine import build_real_deck, load_cards_db, validar_deck


def _load_deck_list(pool_size: int = 30):
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()
    deck_list = []
    for url, name in urls.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if not result:
            continue
        leader, cards, start_stage = result
        valido, erros = validar_deck(leader, cards, cards_db)
        if not valido:
            continue
        if len(cards) >= 40:
            deck_list.append((name, (leader, cards, start_stage)))
        if len(deck_list) >= pool_size:
            break
    return deck_list


def _run_one(task):
    """Roda 1 partida com USE_CHEAP_LAYER_SHORTLIST ligado (so neste
    processo -- ProcessPoolExecutor isola o monkeypatch, nao vaza pro
    resto do motor em producao) e extrai as 3 metricas direto do
    decision_log do lado A."""
    i, match_seed, leader_code, pool_size = task
    de.USE_CHEAP_LAYER_SHORTLIST = True
    deck_list = _load_deck_list(pool_size)
    target_indices = [idx for idx, (_, d) in enumerate(deck_list) if d[0].code == leader_code]
    if not target_indices:
        return None
    rng = random.Random(match_seed)
    idx_a = rng.choice(target_indices)
    resto = [idx for idx in range(len(deck_list)) if idx != idx_a]
    idx_b = rng.choice(resto)
    name_a, deck_a = deck_list[idx_a]
    name_b, deck_b = deck_list[idx_b]

    random.seed(match_seed)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        match = ReplayMatch(deck_a, deck_b, name_a[:25], name_b[:25])
        match.enable_decision_audit()
        match.setup()
        vencedor = None
        for turn_num in range(match.MAX_TURNS * 2):
            p = match.state_a if turn_num % 2 == 0 else match.state_b
            opp = match.state_b if p is match.state_a else match.state_a
            vencedor = match.play_turn(p, opp)
            if vencedor:
                break

    entradas_a = [e for e in (match.decision_log or [])
                 if e is not None and e.get('kind') == 'turn_planner' and e.get('player') == 'A']

    n_decisoes = len(entradas_a)
    n_cheap_ativo = sum(1 for e in entradas_a if e.get('context', {}).get('cheap_layer_active'))
    n_candidates_total = sum(e.get('context', {}).get('n_candidates', 0) for e in entradas_a)

    concordancia_ok = 0
    concordancia_total = 0
    # Baseline de ACASO (achado ao ler o 1o resultado real: comparar contra
    # 50% fixo e ingenuo -- um conjunto com 3+ candidatas ja tem chance de
    # concordar por puro acaso MENOR que 50%. Soma 1/tamanho de cada
    # conjunto -- o "esperado por acaso" certo pra comparar contra
    # concordancia_ok, nao um limiar fixo.
    concordancia_esperada_acaso = 0.0
    adicionadas_total = 0
    adicionadas_escolhidas = 0

    for e in entradas_a:
        candidates = e.get('candidates') or []
        chosen = e.get('chosen') or {}
        chosen_card = (chosen.get('card') or {}).get('code')
        chosen_kind = chosen.get('kind')

        com_os_dois = [c for c in candidates
                       if c.get('cheap_value') is not None and c.get('simulated_value') is not None]
        if len(com_os_dois) >= 2:
            concordancia_total += 1
            concordancia_esperada_acaso += 1.0 / len(com_os_dois)
            top_cheap = max(com_os_dois, key=lambda c: c['cheap_value'])
            top_sim = max(com_os_dois, key=lambda c: c['simulated_value'])
            top_cheap_id = ((top_cheap.get('card') or {}).get('code'), top_cheap.get('kind'))
            top_sim_id = ((top_sim.get('card') or {}).get('code'), top_sim.get('kind'))
            if top_cheap_id == top_sim_id:
                concordancia_ok += 1

        for c in candidates:
            if not c.get('added_by_cheap_layer'):
                continue
            adicionadas_total += 1
            c_code = (c.get('card') or {}).get('code')
            if c_code == chosen_card and c.get('kind') == chosen_kind:
                adicionadas_escolhidas += 1

    return {
        'i': i, 'vencedor': vencedor,
        'n_decisoes': n_decisoes,
        'n_cheap_ativo': n_cheap_ativo,
        'n_candidates_total': n_candidates_total,
        'concordancia_ok': concordancia_ok,
        'concordancia_total': concordancia_total,
        'concordancia_esperada_acaso': concordancia_esperada_acaso,
        'adicionadas_total': adicionadas_total,
        'adicionadas_escolhidas': adicionadas_escolhidas,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--leader', required=True, help='codigo do lider-alvo, ex: OP13-079')
    ap.add_argument('--n', type=int, default=20, help='numero de partidas a rodar')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--pool-size', type=int, default=30)
    args = ap.parse_args()

    deck_list = _load_deck_list(args.pool_size)
    if not any(d[0].code == args.leader for _, d in deck_list):
        raise SystemExit(f'lider {args.leader} nao tem deck valido no pool de '
                          f'{len(deck_list)} decks -- tente --pool-size maior')

    tasks = [(i, args.seed * 1_000_003 + i, args.leader, args.pool_size) for i in range(args.n)]
    if args.workers <= 1:
        resultados = [_run_one(t) for t in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            resultados = list(ex.map(_run_one, tasks))
    resultados = [r for r in resultados if r is not None]

    n_decisoes = sum(r['n_decisoes'] for r in resultados)
    n_cheap_ativo = sum(r['n_cheap_ativo'] for r in resultados)
    n_candidates_total = sum(r['n_candidates_total'] for r in resultados)
    concordancia_ok = sum(r['concordancia_ok'] for r in resultados)
    concordancia_total = sum(r['concordancia_total'] for r in resultados)
    concordancia_esperada_acaso = sum(r['concordancia_esperada_acaso'] for r in resultados)
    adicionadas_total = sum(r['adicionadas_total'] for r in resultados)
    adicionadas_escolhidas = sum(r['adicionadas_escolhidas'] for r in resultados)

    print('=' * 70)
    print(f'AUDITORIA DA CAMADA BARATA -- lider {args.leader} '
          f'({len(resultados)} partidas, seed={args.seed})')
    print('=' * 70)
    print(f'Decisoes do Turn Planner (lado A): {n_decisoes}')
    print(f'  com camada barata ativa: {n_cheap_ativo} '
          f'({n_cheap_ativo/max(1,n_decisoes)*100:.1f}%)')
    if n_decisoes:
        print(f'  media de candidatas no shortlist final: '
              f'{n_candidates_total/n_decisoes:.2f}')
    print()
    print('1) CONCORDANCIA (candidatas com cheap_value E simulated_value no mesmo turno):')
    if concordancia_total:
        taxa_conc = concordancia_ok / concordancia_total * 100
        # Comparar contra 50% fixo e ingenuo -- um conjunto com 3+
        # candidatas ja tem chance de concordar por puro ACASO menor que
        # 50%. Compara contra o esperado por acaso de verdade (soma de
        # 1/tamanho de cada conjunto), nao um limiar fixo.
        taxa_acaso = concordancia_esperada_acaso / concordancia_total * 100
        print(f'   {concordancia_ok}/{concordancia_total} decisoes ({taxa_conc:.1f}%) -- '
              f'a candidata de maior cheap_value TAMBEM e a de maior simulated_value')
        print(f'   esperado por ACASO nesta mesma amostra (1/tamanho de cada conjunto): '
              f'{taxa_acaso:.1f}%')
        margem = taxa_conc - taxa_acaso
        if margem <= 2.0:
            print(f'   ALERTA: concordancia ({taxa_conc:.1f}%) proxima ou abaixo do acaso '
                  f'({taxa_acaso:.1f}%) -- sinal barato pode estar')
            print('   ENGANANDO mais do que ajudando. Investigar antes de habilitar em producao.')
        else:
            print(f'   Bate o acaso por +{margem:.1f}pp -- sinal barato carrega informacao real, '
                  f'nao e ruido.')
    else:
        print('   (nenhuma decisao teve 2+ candidatas com os dois valores nesta amostra)')
    print()
    print('2) ALARGAMENTO (candidatas que SO a camada barata promoveu, fora do shortlist estatico):')
    print(f'   {adicionadas_total} candidatas adicionadas em {n_decisoes} decisoes '
          f'({adicionadas_total/max(1,n_decisoes)*100:.1f}% das decisoes tiveram pelo menos 1)')
    print()
    print('3) VALOR REAL DO ALARGAMENTO (das candidatas adicionadas, quantas viraram a escolha final):')
    if adicionadas_total:
        taxa_valor = adicionadas_escolhidas / adicionadas_total * 100
        print(f'   {adicionadas_escolhidas}/{adicionadas_total} ({taxa_valor:.1f}%) das candidatas '
              f'promovidas pela camada barata foram REALMENTE escolhidas apos a busca real')
        print('   (uma taxa baixa nao e necessariamente ruim -- a maioria das candidatas de QUALQUER')
        print('   shortlist normal tambem nao e escolhida; o que importa e se essa taxa e >0% de forma')
        print('   consistente, ou seja: o alargamento ocasionalmente acha a jogada certa que o score')
        print('   estatico sozinho teria perdido)')
    else:
        print('   (nenhuma candidata foi adicionada pela camada barata nesta amostra -- ou o score')
        print('   estatico ja cobria tudo que a camada barata julgava competitivo, ou o pool de')
        print('   partidas nao gerou situacoes onde ela discordasse)')


if __name__ == '__main__':
    main()
