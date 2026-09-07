"""
calibrar_percentis_abertura.py
==============================
Gera `percentis_abertura.json`: a distribuicao REAL, nos decks de torneio de
`decklists_raw.csv`, da probabilidade de ter cada recurso na mao inicial
(hipergeometrica, N=50, n=5).

POR QUE EXISTE (achado 06/09, deck Krieg): o painel "Analisador Inteligente"
do front comparava cada probabilidade contra um `ideal` HARDCODED em
TypeScript (0.65, 0.40, 0.50...), inventado sem base. Medindo esses cortes
contra os 184 decks reais, metade deles nao discriminava nada:

    counter1k  >= 40%  -> 100,0% dos decks passam
    blocker    >= 40%  ->  97,8%
    draw       >= 50%  ->  92,9%
    low2       >= 65%  ->  85,9%

Ou seja: quatro tiles que so sabem dizer "Excelente". Trocando o corte
inventado pelos quartis da distribuicao real, cada tile passa a situar o
deck CONTRA O META ("acima da mediana", "ultimo quartil"), que e uma
afirmacao verificavel -- mesma disciplina ja aplicada em
`tribal_cohesion.py`, onde os cortes tambem sairam destes 184 decks.

Uso:
    python calibrar_percentis_abertura.py            # regrava o JSON
    python calibrar_percentis_abertura.py --print    # so mostra a tabela
"""
import csv
import json
import argparse
import collections
import statistics
from math import comb
from pathlib import Path

from deck_axes import compute_deck_axes

AQUI = Path(__file__).parent
SAIDA = AQUI / 'percentis_abertura.json'

# n cartas na mao inicial, N cartas no deck
N_DECK = 50
N_MAO = 5

# Cada metrica é (rotulo, como contar a carta). A contagem tem que bater com
# a do front -- se divergir, volta o problema do bloco 751 (consumidor
# medindo uma coisa e exibindo o ideal de outra).
# `trigger` NAO entra aqui: [Trigger] so dispara quando a carta e virada da
# VIDA -- na mao ela nao faz nada. Medir "chance de trigger na mao inicial"
# e medir uma coisa que nao ajuda o jogador (achado do usuario, 06/09: "ter
# trigger na mao nao e bom"). Ele e medido a parte, em `trigger_vida`, com
# n = life do lider daquele deck em vez de n = 5 cartas da mao.
METRICAS = ['searcher', 'counter2k', 'counter1k', 'blocker', 'draw',
            'low1', 'low2']
METRICA_VIDA = 'trigger_vida'
# Custo medio do main deck. Entra aqui porque o Score de Consistencia
# comparava contra faixas fixas (<=2.5 / <=3.5 / <=4.5) tambem inventadas.
METRICA_CUSTO = 'custo_medio'
# Eixos de SINERGIA/DEFESA/ATAQUE (`deck_axes.py`). Sao numeros crus sem teto
# natural, entao so significam alguma coisa comparados ao meta -- por isso
# entram na mesma calibracao.
METRICAS_EIXOS = ['eixo_sinergia', 'eixo_defesa', 'eixo_ataque']
# Contagem por categoria dos Golden Ratios. Medido 07/09: as faixas fixas de
# `deck_analyzer.GOLDEN_RATIOS` reprovavam o proprio meta --
#   finishers 2-6  -> so   6,5% dos 184 decks de torneio ficam dentro
#   searchers 4-8  -> so  30,4%
#   events    0-6  -> so  41,8%
# Uma faixa "ideal" que reprova 93,5% dos decks de torneio nao e ideal, e
# opiniao. Com p25-p75 do meta, 50% fica dentro por construcao.
METRICAS_RATIOS = ['ratio_counters', 'ratio_searchers', 'ratio_blockers',
                   'ratio_finishers', 'ratio_events']


def _num(v):
    """counter_amount/card_cost vem como '2000.0' OU '2000' no banco (medido
    06/09: 519 linhas no formato .0 contra 28 no formato inteiro). Comparar
    string exata perde a maioria -- sempre numerico."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def prob_pelo_menos_1(N, K, n):
    if K <= 0:
        return 0.0
    if N - K < n:
        return 1.0
    return 1 - comb(N - K, n) / comb(N, n)


def carrega_cards():
    cards = {}
    with open(AQUI / 'cards_rows.csv', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            code = (r.get('card_set_id') or '').split('_')[0]
            if code and code not in cards:
                cards[code] = r
    return cards


def pertence(metrica, card_row, info):
    ca = _num(card_row.get('counter_amount'))
    custo = int(_num(card_row.get('card_cost')) or 99)
    return {
        'searcher':  bool(info.get('is_searcher')),
        'counter2k': ca >= 2000,
        'counter1k': ca == 1000,
        'blocker':   bool(info.get('is_blocker')),
        'draw':      bool(info.get('draws_ativo')),
        'trigger':   bool(info.get('has_trigger')),
        'trigger_vida': bool(info.get('has_trigger')),
        'low1':      custo == 1,
        'low2':      custo <= 2,
    }[metrica]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--print', dest='so_print', action='store_true')
    args = ap.parse_args()

    cards = carrega_cards()
    adb = json.load(open(AQUI / 'card_analysis_db.json', encoding='utf-8'))

    # Dedup por URL: `decklists_raw.csv` tem uma linha por colocacao, e somar
    # sem deduplicar foi exatamente o bug do bloco 750 (decks de ate 500
    # cartas). Aqui a chave e a URL da decklist.
    decks = collections.defaultdict(dict)
    with open(AQUI / 'decklists_raw.csv', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            decks[r['deck_url']][r['card_code']] = int(r['qty'])

    dist = {m: [] for m in list(METRICAS) + [METRICA_VIDA, METRICA_CUSTO] + METRICAS_EIXOS + METRICAS_RATIOS}
    usados = 0
    for _url, d in decks.items():
        main_qty = sum(q for code, q in d.items()
                       if cards.get(code)
                       and (cards[code].get('card_type') or '').lower() != 'leader')
        if main_qty < 40:          # decklist incompleta no scrape
            continue
        usados += 1
        for m in METRICAS:
            K = sum(q for code, q in d.items()
                    if cards.get(code)
                    and (cards[code].get('card_type') or '').lower() != 'leader'
                    and pertence(m, cards[code], adb.get(code) or {}))
            dist[m].append(prob_pelo_menos_1(N_DECK, K, N_MAO))

        # Trigger na VIDA: mesma hipergeometrica, mas n = life do lider
        # DESTE deck (4 ou 5 conforme o lider), nao as 5 cartas da mao.
        life = 5
        for code in d:
            c = cards.get(code)
            if c and (c.get('card_type') or '').lower() == 'leader':
                life = int(_num(c.get('life')) or 5)
                break
        K_trig = sum(q for code, q in d.items()
                     if cards.get(code)
                     and (cards[code].get('card_type') or '').lower() != 'leader'
                     and pertence('trigger_vida', cards[code], adb.get(code) or {}))
        dist[METRICA_VIDA].append(prob_pelo_menos_1(N_DECK, K_trig, life))

        # Custo medio do main deck (ponderado por copia).
        soma = qtd = 0
        for code, q in d.items():
            c = cards.get(code)
            if not c or (c.get('card_type') or '').lower() == 'leader':
                continue
            soma += _num(c.get('card_cost')) * q
            qtd += q
        if qtd:
            dist[METRICA_CUSTO].append(soma / qtd)

        # Eixos: precisam das entradas do analysis_db com `quantity` anexado
        lider_info = None
        main_info = []
        for code, q in d.items():
            c = cards.get(code)
            if not c:
                continue
            info = dict(adb.get(code) or {})
            if not info:
                continue
            if (c.get('card_type') or '').lower() == 'leader':
                lider_info = info
            else:
                # Lista REPETIDA (uma entrada por copia), a mesma convencao que
                # `api.py`/`deck_analyzer.py` usam -- `detect_deck_synergies`
                # conta POR ENTRADA, entao anexar `quantity` aqui e repetir la
                # dariam numeros diferentes pro mesmo deck.
                main_info.extend([info] * q)
        # Contagem por categoria (mesmos criterios de `_count_categories`)
        cnt = {k: 0 for k in ('counters', 'searchers', 'blockers', 'finishers', 'events')}
        for code, q in d.items():
            c = cards.get(code)
            if not c or (c.get('card_type') or '').lower() == 'leader':
                continue
            i = adb.get(code) or {}
            if _num(c.get('counter_amount')) >= 2000:
                cnt['counters'] += q
            if i.get('is_searcher'):
                cnt['searchers'] += q
            if i.get('is_blocker'):
                cnt['blockers'] += q
            if _num(c.get('card_cost')) >= 8:
                cnt['finishers'] += q
            if (c.get('card_type') or '').upper() == 'EVENT':
                cnt['events'] += q
        for k, v in cnt.items():
            dist['ratio_' + k].append(v)

        if lider_info and main_info:
            eixos = compute_deck_axes(lider_info, main_info)
            dist['eixo_sinergia'].append(eixos['sinergia']['bruto'])
            dist['eixo_defesa'].append(eixos['defesa']['bruto'])
            dist['eixo_ataque'].append(eixos['ataque']['bruto'])

    out = {'n_decks': usados, 'fonte': 'decklists_raw.csv', 'metricas': {}}
    for m in list(METRICAS) + [METRICA_VIDA, METRICA_CUSTO] + METRICAS_EIXOS + METRICAS_RATIOS:
        v = sorted(dist[m])
        k = len(v)
        if not k:
            print(f'AVISO: sem amostra para {m}, metrica omitida')
            continue
        def q(p):
            return round(v[min(k - 1, int(p * k))], 4)
        out['metricas'][m] = {
            'p25': q(.25), 'mediana': round(statistics.median(v), 4), 'p75': q(.75),
        }

    print(f'{usados} decks de torneio')
    print(f"{'metrica':11s} {'p25':>8s} {'mediana':>8s} {'p75':>8s}")
    for m in list(METRICAS) + [METRICA_VIDA, METRICA_CUSTO] + METRICAS_EIXOS + METRICAS_RATIOS:
        e = out['metricas'][m]
        # custo_medio e CUSTO, nao probabilidade -- imprimir com *100 dava
        # "374,0%" pra um custo medio de 3,74 e confundia a leitura.
        if m in METRICAS_RATIOS:
            print(f"{m:15s} {e['p25']:8.0f} {e['mediana']:8.0f} {e['p75']:8.0f}   (copias)")
        elif m in METRICAS_EIXOS:
            print(f"{m:13s} {e['p25']:8.1f} {e['mediana']:8.1f} {e['p75']:8.1f}   (bruto, nao %)")
        elif m == METRICA_CUSTO:
            print(f"{m:11s} {e['p25']:8.2f} {e['mediana']:8.2f} {e['p75']:8.2f}   (custo, nao %)")
        else:
            print(f"{m:11s} {e['p25']*100:7.1f}% {e['mediana']*100:7.1f}% {e['p75']*100:7.1f}%")

    if not args.so_print:
        SAIDA.write_text(json.dumps(out, indent=2), encoding='utf-8')
        print(f'\n-> {SAIDA.name} gravado')


if __name__ == '__main__':
    main()
