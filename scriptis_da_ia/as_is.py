# -*- coding: utf-8 -*-
"""AS-IS: a fotografia MEDIDA do motor como ele esta AGORA.

Por que existe (pedido do usuario, 13/09/2026, bloco 787): *"lembre-se de
fazer o AS-is, deixe como obrigatorio, porque ai sempre vamos ter os tempos
computacionais e saber onde estao os gargalos e tals, vamos usar teoria do
Sistema de Informacao"*.

E a disciplina classica de Sistemas de Informacao: **AS-IS -> TO-BE ->
AS-IS de novo**. Nao se propoe processo novo sem o mapa medido do processo
atual, e nao se declara ganho sem remedir. Aqui vale palavra por palavra:
otimizar sem AS-IS e otimizar o gargalo do mes passado.

## O CASO REAL QUE ORIGINOU A REGRA

No bloco 784 o perfil dizia: **85% do tempo no rollout Monte Carlo**, e a
conclusao registrada foi *"o metodo esta certo, falta avaliacao incremental
(o 'U' do NNUE) -- cada consulta recalcula as 77 features do zero"*.

No bloco 785 o Monte Carlo saiu. **A composicao do tempo virou outra coisa** e
o diagnostico velho continuou sendo repetido -- por mim, com confianca, sem
remedir. So quando o usuario perguntou *"por que ainda esta demorando?"* e o
perfil foi refeito e que apareceu o gargalo REAL:

    consulta ao modelo UMA linha por vez : 14,52 ms/linha
    a mesma consulta em LOTE de 6        :  0,86 ms/linha   (16,9x)
    em LOTE de 200                       :  0,05 ms/linha   (288,8x)

Nao era montar as features. Era percorrer 300 arvores em Python, uma linha de
cada vez, 1.902 vezes por partida. **Um diagnostico de desempenho vence quando
o sistema muda** -- e o sistema muda toda sessao.

## A REGRA (obrigatoria, ver CLAUDE.md / AGENTS.md)

1. ANTES de propor ou implementar qualquer mudanca justificada por
   DESEMPENHO, rode este script e cite os numeros.
2. ANTES de afirmar onde esta o gargalo, rode este script. Diagnostico
   herdado de bloco anterior NAO vale como evidencia.
3. DEPOIS da mudanca, rode de novo e compare (`--comparar`). Ganho declarado
   sem AS-IS posterior e ganho nao comprovado.

## Como ler o resultado

A quebra por familia usa **tempo PROPRIO** (`tottime`), nao cumulativo: assim
as fatias somam o total sem contar duas vezes a mesma chamada aninhada. O
cumulativo aparece separado, so pra dizer "quanto do tempo passa POR AQUI".

Uso:

    python as_is.py                          # 2 partidas, grava em metrics/as_is/
    python as_is.py --n 4 --rotulo pos-lote   # rotulo entra no nome do arquivo
    python as_is.py --comparar metrics/as_is/as_is_<...>.json
"""
from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import random
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
SAIDA = RAIZ / 'metrics' / 'as_is'

# Cada familia e uma lista de (arquivo_contem, funcao_contem). Tempo PROPRIO.
FAMILIAS = [
    ('modelo (rede de valor)', [
        ('value_net.py', 'win_prob'), ('value_net.py', 'state_features'),
        ('sklearn', ''), ('numpy', ''),
    ]),
    ('busca de decisao', [
        ('decision_engine.py', '_busca_determinista'),
        ('decision_engine.py', '_valor'),
        ('decision_engine.py', '_select_action_via_search'),
        ('decision_engine.py', '_ordena_pelo_modelo'),
        ('decision_engine.py', '_select_search_candidates'),
    ]),
    ('clonagem de estado', [('copy.py', ''), ('decision_engine.py', '__deepcopy__')]),
    ('gerar/pontuar candidatas', [
        ('decision_engine.py', '_generate_and_score_actions'),
        ('decision_engine.py', 'avaliar_carta'),
        ('decision_engine.py', '_generate_attach_don_actions'),
        ('decision_engine.py', '_evaluate_state_v2'),
    ]),
    ('prova de lethal', [
        ('decision_engine.py', '_lethal_search'),
        ('decision_engine.py', 'search_alloc'),
        ('decision_engine.py', 'hits_after_best_defense'),
    ]),
    ('executar acao/combate', [
        ('decision_engine.py', '_apply_action'),
        ('decision_engine.py', '_execute_attack'),
        ('decision_engine.py', 'execute'),
        ('decision_engine.py', '_execute_step'),
    ]),
    ('primitivas do interpretador', [('~', 'getattr'), ('~', 'setattr'),
                                     ('~', "method 'get' of 'dict'"),
                                     ('~', 'isinstance'), ('~', 'len'),
                                     ('~', "method 'append'")]),
    ('defesa (blocker/counter)', [
        ('decision_engine.py', 'pick_counters'),
        ('decision_engine.py', '_should_use_counter'),
        ('decision_engine.py', '_should_use_blocker'),
    ]),
]


def _familia(arquivo: str, funcao: str) -> str:
    for nome, padroes in FAMILIAS:
        for arq, fn in padroes:
            if arq in arquivo and (not fn or fn in funcao):
                return nome
    return 'outros'


def roda(n: int, seed_base: int):
    """Joga `n` partidas completas sob o profiler. Devolve (stats, metricas)."""
    from optcg_engine import decision_engine as de
    from optcg_engine import value_net as vn
    from gerar_selfplay_dataset import _load_deck_list

    dl = _load_deck_list()
    contas = {'turnos': 0, 'decisoes': 0, 'candidatas': 0}

    orig_sel = de.OPTCGMatch._select_action_via_search

    def espiao(self, p, opp, engine, candidatas):
        contas['decisoes'] += 1
        contas['candidatas'] += len(candidatas)
        return orig_sel(self, p, opp, engine, candidatas)

    de.OPTCGMatch._select_action_via_search = espiao
    vn._WP_STATS['hit'] = vn._WP_STATS['miss'] = 0

    def _partidas():
        for i in range(n):
            seed = seed_base * 1_000_003 + i
            rng = random.Random(seed)
            ia, ib = rng.sample(range(len(dl)), 2)
            random.seed(seed)
            try:
                m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
                m.setup()
            except Exception:
                continue
            for t in range(m.MAX_TURNS * 2):
                p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                    else (m.state_b if m.state_a.is_first else m.state_a)
                o = m.state_b if p is m.state_a else m.state_a
                contas['turnos'] += 1
                if m.play_turn(p, o):
                    break
            vn.limpar_cache_win_prob()

    # PASSO 0 -- AQUECIMENTO DESCARTADO (bloco 789). Sem isto o AS-IS mede a
    # fase RAPIDA do processo e sai sistematicamente otimista: a mesma carga,
    # com resultado identico, foi de 9,60s pra 15,30s ao longo de 4 voltas no
    # MESMO processo, e processos NOVOS deram 14,6s estaveis. O regime estavel
    # e o que vale -- e o que o portao vai pagar, partida after partida.
    _partidas()
    contas['turnos'] = contas['decisoes'] = contas['candidatas'] = 0
    vn._WP_STATS['hit'] = vn._WP_STATS['miss'] = 0

    # PASSO 1 -- tempo de PAREDE, sem profiler (o profiler infla 3x), TRES
    # vezes. Esta maquina varia ate 59% entre execucoes IDENTICAS, com o mesmo
    # resultado de partida (medido no bloco 789) -- um numero unico ja levou a
    # conclusao errada duas vezes num dia. Reportamos a MENOR (a menos
    # contaminada por outro processo) junto do intervalo, pra ninguem comparar
    # duas medicoes fingindo que 20% de diferenca significa alguma coisa.
    voltas = []
    for _ in range(3):
        t0 = time.time()
        _partidas()
        voltas.append((time.time() - t0) / max(1, n))
        contas['turnos'] = contas['decisoes'] = contas['candidatas'] = 0
        vn._WP_STATS['hit'] = vn._WP_STATS['miss'] = 0
    real = min(voltas) * n
    contas['voltas_s_por_partida'] = [round(v, 2) for v in voltas]

    # PASSO 2 -- a MESMA carga sob profiler, so pra quebrar o tempo por familia
    pr = cProfile.Profile()
    pr.enable()
    _partidas()
    pr.disable()
    de.OPTCGMatch._select_action_via_search = orig_sel

    contas['wp_hit'] = vn._WP_STATS['hit']
    contas['wp_miss'] = vn._WP_STATS['miss']
    contas['segundos_reais'] = real
    return pstats.Stats(pr), contas


def resume(stats: pstats.Stats, contas: dict, n: int) -> dict:
    total_proprio = 0.0
    por_familia: dict[str, float] = {}
    topo = []
    for (arquivo, _linha, funcao), (_cc, nc, tt, ct, _cal) in stats.stats.items():
        total_proprio += tt
        por_familia[_familia(arquivo, funcao)] = \
            por_familia.get(_familia(arquivo, funcao), 0.0) + tt
        topo.append((tt, ct, nc, f'{Path(arquivo).name}:{funcao}'))
    topo.sort(reverse=True)

    return {
        'quando': datetime.now().isoformat(timespec='seconds'),
        'partidas': n,
        'segundos_por_partida_real': round(contas['segundos_reais'] / max(1, n), 2),
        'voltas_s_por_partida': contas.get('voltas_s_por_partida'),
        'variacao_da_maquina_pct': (
            round(100.0 * (max(contas['voltas_s_por_partida'])
                           - min(contas['voltas_s_por_partida']))
                  / max(1e-9, min(contas['voltas_s_por_partida'])), 0)
            if contas.get('voltas_s_por_partida') else None),
        'segundos_sob_profiler_total': round(total_proprio, 1),
        'turnos': contas['turnos'],
        'decisoes_de_busca': contas['decisoes'],
        'candidatas_por_decisao': round(
            contas['candidatas'] / max(1, contas['decisoes']), 2),
        'consultas_ao_modelo': contas['wp_hit'] + contas['wp_miss'],
        'consultas_que_pagaram_previsao': contas['wp_miss'],
        'acerto_do_memo_pct': round(
            100.0 * contas['wp_hit'] / max(1, contas['wp_hit'] + contas['wp_miss']), 1),
        'familias_pct': {
            k: round(100.0 * v / max(1e-9, total_proprio), 1)
            for k, v in sorted(por_familia.items(), key=lambda kv: -kv[1])
        },
        'top_funcoes': [
            {'funcao': f, 'proprio_s': round(tt, 2), 'cumulativo_s': round(ct, 2),
             'chamadas': nc}
            for tt, ct, nc, f in topo[:15]
        ],
    }


def imprime(r: dict, anterior: dict | None = None):
    print()
    print('=' * 68)
    print('AS-IS  --  %s  (%d partidas)' % (r['quando'], r['partidas']))
    print('=' * 68)
    print('  segundos por partida     : %.2f s   (MENOR de 3, apos aquecimento)'
          % r['segundos_por_partida_real'])
    if r.get('voltas_s_por_partida'):
        print('    as 3 voltas            : %s  -> a maquina varia %.0f%% sozinha'
              % (r['voltas_s_por_partida'], r['variacao_da_maquina_pct']))
    print('  turnos / decisoes        : %d / %d' % (r['turnos'], r['decisoes_de_busca']))
    print('  candidatas por decisao   : %.2f' % r['candidatas_por_decisao'])
    print('  consultas ao modelo      : %d  (pagaram previsao: %d, memo %.1f%%)'
          % (r['consultas_ao_modelo'], r['consultas_que_pagaram_previsao'],
             r['acerto_do_memo_pct']))
    print()
    print('  ONDE O TEMPO E GASTO (tempo PROPRIO, soma 100%)')
    for k, v in r['familias_pct'].items():
        barra = '#' * int(v / 2)
        print('    %-28s %5.1f%%  %s' % (k, v, barra))
    print()
    print('  TOP FUNCOES (proprio | cumulativo | chamadas)')
    for f in r['top_funcoes'][:8]:
        print('    %8.2fs %8.2fs %9d  %s'
              % (f['proprio_s'], f['cumulativo_s'], f['chamadas'], f['funcao']))

    if anterior:
        print()
        print('  COMPARACAO com %s' % anterior['quando'])
        a = anterior['segundos_por_partida_real']
        b = r['segundos_por_partida_real']
        print('    segundos por partida : %.2f -> %.2f  (%+.1f%%)'
              % (a, b, 100.0 * (b - a) / max(1e-9, a)))
        for k in sorted(set(list(r['familias_pct']) + list(anterior['familias_pct']))):
            va = anterior['familias_pct'].get(k, 0.0)
            vb = r['familias_pct'].get(k, 0.0)
            if abs(vb - va) >= 1.0:
                print('    %-28s %5.1f%% -> %5.1f%%  (%+.1f pp)' % (k, va, vb, vb - va))
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--n', type=int, default=2, help='partidas completas a perfilar')
    ap.add_argument('--seed', type=int, default=101)
    ap.add_argument('--rotulo', default='', help='entra no nome do arquivo')
    ap.add_argument('--comparar', default=None,
                    help='AS-IS anterior (json) pra medir o delta')
    ap.add_argument('--nao-gravar', dest='nao_gravar', action='store_true')
    args = ap.parse_args()

    anterior = None
    if args.comparar:
        anterior = json.loads(Path(args.comparar).read_text(encoding='utf-8'))

    stats, contas = roda(args.n, args.seed)
    r = resume(stats, contas, args.n)
    imprime(r, anterior)

    if not args.nao_gravar:
        SAIDA.mkdir(parents=True, exist_ok=True)
        nome = 'as_is_%s%s.json' % (
            datetime.now().strftime('%Y-%m-%dT%H.%M.%S'),
            ('_' + args.rotulo) if args.rotulo else '')
        destino = SAIDA / nome
        destino.write_text(json.dumps(r, indent=2, ensure_ascii=False),
                           encoding='utf-8')
        print('  gravado em %s' % destino.relative_to(RAIZ))
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
