"""
decision_quality_report.py -- placar de QUALIDADE DE DECISAO por lider/deck,
independente de vitoria/derrota (pedido do usuario, 10/08/2026, bloco 485,
depois da auditoria do Sanji OP12-041 nos blocos 482-484).

Winrate agregado mede sorte de matchup, nao qualidade de jogo -- um deck
genuinamente fraco perde mesmo jogado perfeitamente, e isso NAO e um
problema pra corrigir (confirmado pelo usuario: "não tem problema perder a
partida, as vezes o deck só é fraco mesmo, nós só precisamos garantir de
que o bot entende o deck e toma as melhores decisões"). Este script mede
tres coisas que independem do resultado da partida:

1. UTILIZACAO DA HABILIDADE DO LIDER: em quantos turnos a habilidade
   [Activate: Main] do lider foi oferecida como CANDIDATA pelo Turn
   Planner (o motor real ja considerou como opcao legal -- le direto de
   `decision_log`, NAO reimplementa elegibilidade own, pra nao virar uma
   segunda fonte de verdade sobre "quando essa acao e legal", contra
   REGRA_SEM_DUPLICACAO.md) vs quantos turnos foi de fato ESCOLHIDA.
   Liders sem [Activate: Main] (boa parte do banco) reportam N/A.
2. DON DEIXADO NA MESA: `don_available` do lado alvo IMEDIATAMENTE apos
   cada um dos proprios turnos dele terminar (estado real, nao inferido
   do log) -- DON > 0 no fim do turno e sinal de recurso nao aproveitado.
3. UTILIZACAO POR CARTA (achado real 10/08, pedido do usuario apos o
   placar do lider: "não quero só conferir efeito do líder, preciso
   saber se os efeitos das outras cartas estão sendo utilizados"):
   MESMO mecanismo do item 1, generalizado pra QUALQUER carta da mao
   (personagens/Eventos jogados, incl. reanimados via play_from_trash)
   -- por turno, "essa carta apareceu como candidata de jogar/reanimar"
   vs "foi de fato escolhida". Agregado por CODIGO de carta (nao por
   copia), ordenado do PIOR aproveitamento pro melhor -- destaca cartas
   que o bot recebe na mao com frequencia mas raramente prioriza.
   LIMITACAO HONESTA: `decision_log` so grava os top-8 candidatos por
   decisao (`candidates[:8]`, ver `_log_turn_planner_decision`) -- uma
   carta cuja pontuacao NUNCA entra no top-8 (sempre pior que outras 8+
   opcoes) nunca aparece como "ofertada" aqui, mesmo estando na mao.
   Este relatorio so enxerga cartas que competem perto do topo pelo
   menos alguma vez; nao prova que uma carta ausente da tabela nunca
   foi considerada, so que nunca chegou perto de ser a melhor escolha.

Uso obrigatorio (ver CLAUDE.md): sempre que for avaliar se o bot sabe
jogar um lider/deck especifico, rodar este relatorio ANTES de olhar
winrate -- winrate sozinho nao distingue "bot jogou mal" de "deck e
fraco/matchup ruim".

Uso: python decision_quality_report.py --leader OP12-041 --n 30 [--seed S] [--workers W] [--top-cartas N]
"""
import argparse
import concurrent.futures
import contextlib
import io
import random
from collections import defaultdict

import pandas as pd

from replay_optcg import ReplayMatch
from optcg_engine.decision_engine import (
    build_real_deck, get_card_effects, load_cards_db, validar_deck,
)


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
    """Roda 1 partida com o lider-alvo sempre no lado A (target) contra um
    oponente aleatorio do resto do pool, e extrai os dois sinais direto do
    decision_log/estado real -- cada processo carrega o proprio banco
    (mesmo padrao de audit_replay.py/gauntlet_matchup.py, bloco 481)."""
    i, match_seed, leader_code = task
    deck_list = _load_deck_list()
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

    tem_activate_main = bool(get_card_effects(leader_code).get('activate_main'))

    turnos_totais_alvo = 0
    don_leftover = []

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
            if p is match.state_a:
                turnos_totais_alvo += 1
                don_leftover.append(match.state_a.don_available)
            if vencedor:
                break

    # Item 3 (generico, cobre item 1 tambem): por CODIGO de carta, conta
    # turnos em que apareceu como candidata de 'play'/'activate'/
    # 'play_from_trash' vs turnos em que foi de fato escolhida. Agregado
    # por turno (nao por entrada de log) pra nao inflar o denominador com
    # a MESMA carta reavaliada varias vezes no mesmo turno (Turn Planner
    # roda em loop ate esgotar acoes do turno).
    USA_EFEITO = ('play', 'activate', 'play_from_trash')
    por_turno = defaultdict(list)
    for e in (match.decision_log or []):
        if e is None or e.get('kind') != 'turn_planner' or e.get('player') != 'A':
            continue
        por_turno[e['turn']].append(e)

    por_carta = {}   # code -> {'nome':str, 'ofertada': int, 'escolhida': int}
    for turno, entradas in por_turno.items():
        ofertadas_no_turno = set()
        for e in entradas:
            for c in (e.get('candidates') or []):
                if c.get('kind') not in USA_EFEITO:
                    continue
                card = c.get('card') or {}
                code = card.get('code')
                if not code:
                    continue
                ofertadas_no_turno.add(code)
                slot = por_carta.setdefault(code, {'nome': card.get('name', code), 'ofertada': 0, 'escolhida': 0})
        for code in ofertadas_no_turno:
            por_carta[code]['ofertada'] += 1
        escolhidas_no_turno = set()
        for e in entradas:
            chosen = e.get('chosen') or {}
            if chosen.get('kind') not in USA_EFEITO:
                continue
            code = (chosen.get('card') or {}).get('code')
            if code and code in ofertadas_no_turno:
                escolhidas_no_turno.add(code)
        for code in escolhidas_no_turno:
            por_carta[code]['escolhida'] += 1

    return {
        'i': i, 'name_a': name_a, 'name_b': name_b, 'vencedor': vencedor,
        'tem_activate_main': tem_activate_main,
        'turnos_totais_alvo': turnos_totais_alvo,
        'don_leftover': don_leftover,
        'por_carta': por_carta,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--leader', required=True, help='codigo do lider-alvo, ex: OP12-041')
    ap.add_argument('--n', type=int, default=30, help='numero de partidas a rodar')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--workers', type=int, default=1,
                     help='processos paralelos (1=sequencial). Partidas sao '
                          'independentes -- paraleliza sem risco de correcao.')
    ap.add_argument('--top-cartas', type=int, default=15,
                     help='quantas cartas (piores primeiro) mostrar na tabela do item 3')
    ap.add_argument('--min-ofertas', type=int, default=2,
                     help='ignora cartas ofertadas menos que isso (amostra pequena demais)')
    args = ap.parse_args()

    deck_list = _load_deck_list()
    if not any(d[0].code == args.leader for _, d in deck_list):
        raise SystemExit(f'lider {args.leader} nao tem deck valido no pool de '
                          f'{len(deck_list)} decks (decklists_raw.csv)')

    tasks = [(i, args.seed * 1_000_003 + i, args.leader) for i in range(args.n)]
    if args.workers <= 1:
        resultados = [_run_one(t) for t in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            resultados = list(ex.map(_run_one, tasks))
    resultados = [r for r in resultados if r is not None]

    tem_activate_main = resultados[0]['tem_activate_main'] if resultados else False
    vitorias = sum(1 for r in resultados if r['vencedor'] == 'A')

    # Merge por_carta de todas as partidas (mesmo codigo pode aparecer em varios jogos)
    por_carta = {}
    for r in resultados:
        for code, dados in r['por_carta'].items():
            slot = por_carta.setdefault(code, {'nome': dados['nome'], 'ofertada': 0, 'escolhida': 0})
            slot['ofertada'] += dados['ofertada']
            slot['escolhida'] += dados['escolhida']

    print(f'{"="*70}')
    print(f'PLACAR DE QUALIDADE DE DECISAO -- lider {args.leader} ({len(resultados)} partidas, seed={args.seed})')
    print(f'{"="*70}')
    print(f'(winrate agregado, so contexto -- NAO e o criterio de avaliacao aqui): '
          f'{vitorias}/{len(resultados)} = {vitorias/len(resultados)*100:.1f}%' if resultados else '(sem partidas)')
    print()

    if not tem_activate_main:
        print('1) Utilizacao da habilidade do lider: N/A (este lider nao tem [Activate: Main] parseado)')
    else:
        lider = por_carta.get(args.leader, {'ofertada': 0, 'escolhida': 0})
        total_oferta, total_ativou = lider['ofertada'], lider['escolhida']
        taxa = (total_ativou / total_oferta * 100) if total_oferta else 0.0
        print(f'1) Utilizacao da habilidade do lider (Activate:Main):')
        print(f'   Oferecida como candidata em {total_oferta} turnos, ATIVADA em {total_ativou} '
              f'({taxa:.1f}%)')
        if total_oferta == 0:
            print('   (nunca foi legal ativar em nenhum turno destas partidas -- checar elegibilidade/custo)')

    todos_leftover = [d for r in resultados for d in r['don_leftover']]
    if todos_leftover:
        media = sum(todos_leftover) / len(todos_leftover)
        zero_leftover = sum(1 for d in todos_leftover if d == 0)
        print()
        print(f'2) DON deixado na mesa no fim do proprio turno:')
        print(f'   media={media:.2f} DON/turno ({len(todos_leftover)} turnos), '
              f'{zero_leftover}/{len(todos_leftover)} turnos terminaram com 0 DON sobrando '
              f'({zero_leftover/len(todos_leftover)*100:.1f}%)')

    outras_cartas = [
        (code, d) for code, d in por_carta.items()
        if code != args.leader and d['ofertada'] >= args.min_ofertas
    ]
    print()
    print(f'3) Utilizacao por CARTA (pior aproveitamento primeiro, min. {args.min_ofertas} '
          f'ofertas -- ver limitacao do top-8 no docstring):')
    if not outras_cartas:
        print('   (nenhuma carta alem do lider apareceu como candidata o suficiente nesta amostra)')
    else:
        outras_cartas.sort(key=lambda kv: (kv[1]['escolhida'] / kv[1]['ofertada'], -kv[1]['ofertada']))
        print(f'   {"Carta":34s} {"Codigo":10s} {"Ofertada":>8s} {"Usada":>6s} {"Taxa":>7s}')
        for code, d in outras_cartas[:args.top_cartas]:
            taxa = d['escolhida'] / d['ofertada'] * 100
            print(f'   {d["nome"][:34]:34s} {code:10s} {d["ofertada"]:8d} {d["escolhida"]:6d} {taxa:6.1f}%')
        if len(outras_cartas) > args.top_cartas:
            print(f'   ... e mais {len(outras_cartas) - args.top_cartas} carta(s) '
                  f'com {args.min_ofertas}+ ofertas')


if __name__ == '__main__':
    main()
