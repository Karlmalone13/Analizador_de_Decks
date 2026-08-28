"""FASE 1 do plano do bloco 702: avaliador RAPIDO sobre o banco de decisoes.

O QUE ISTO RESOLVE
------------------
Uma medicao com `decision_quality_full.py` custa ~20 minutos. Um laco
iterativo (DAgger, busca de features, tuning de ranqueador) precisa de
CENTENAS de iteracoes. **Foi por isso que toda tentativa anterior de
imitacao teve UM tiro so e foi abandonada** -- nao por falta de ideia,
por custo de iteracao. Aqui a mesma pergunta ("este ranqueador joga mais
parecido com o humano?") e respondida em SEGUNDOS, sobre o banco ja
extraido (`metrics/policy_dataset.jsonl`, 4420 decisoes).

A METRICA -- mesma granularidade do `play` oficial
--------------------------------------------------
Agrupa as decisoes por TURNO e compara o CONJUNTO de cartas que o
ranqueador jogaria contra o conjunto que o humano jogou. E a mesma regra
de `decision_quality_full.py`, nao uma proxy inventada (AUC, top-1) --
justamente porque a tentativa reprovada do bloco 683 melhorou o AUC
isolado (0,702 -> 0,851) e PIOROU a metrica real.

LIMITACAO CENTRAL, declarada de saida -- LEIA ANTES DE CONFIAR NO NUMERO
------------------------------------------------------------------------
As decisoes do banco foram gravadas ao longo da trajetoria do motor
BASELINE. Offline o estado NAO se atualiza conforme o ranqueador escolhe
diferente: um modelo que divergiria no 1o passo continua vendo estados
que, na pratica, ele nunca alcancaria. **Isto E o *distribution shift* --
o mesmo que reprovou o bloco 683.**

Consequencia pratica: **o numero daqui e OTIMISTA e serve pra ITERAR, nao
pra decidir.** Toda conclusao final continua exigindo
`decision_quality_full.py` (regua real, ~20 min) e, quando houver mudanca
de comportamento, o A/B com recorte por lider. O avaliador rapido existe
pra chegar nesse teste caro com uma hipotese ja filtrada, nao pra
substitui-lo.

LIMITE DO PROPRIO BANCO -- a continencia aqui e 100% POR CONSTRUCAO
-------------------------------------------------------------------
O conjunto "humano" deste banco e DERIVADO das candidatas marcadas
`humano_fez`. Cartas que o humano jogou e que NUNCA viraram candidata
simplesmente nao existem aqui. Entao o `play` medido por este avaliador
ignora esse 2,6% (medido no bloco 697) e e, tambem por isso, otimista.
NAO comparar a "continencia" daqui com os 80,3% do oraculo do bloco 697:
sao coisas diferentes.

SPLIT POR LIDER (requisito de 1a classe do bloco 702)
-----------------------------------------------------
`split_por_lider()` separa treino/validacao por LIDER, nunca por partida.
A tentativa do bloco 683 usava split por PARTIDA e tinha one-hot de lider
nas features -- combinacao que **nunca poderia detectar** falha de
generalizacao pra deck novo, que e exatamente o requisito do usuario
("qualquer deck que o usuario montar").
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(AQUI, 'metrics', 'policy_dataset.jsonl')


def carrega(path: str = DATASET) -> list[dict]:
    with open(path, encoding='utf-8') as fh:
        return [json.loads(l) for l in fh if l.strip()]


def agrupa_por_turno(linhas: list[dict]) -> list[dict]:
    """Uma entrada por TURNO: as decisoes + o conjunto que o humano jogou."""
    por = defaultdict(list)
    for d in linhas:
        por[(d['game_id'], d['turn'])].append(d)
    turnos = []
    for (gid, turn), decisoes in por.items():
        humano = {c['code'] for d in decisoes for c in d['candidates']
                  if c['kind'] == 'play' and c.get('humano_fez')}
        # UNIVERSO FIXO de avaliacao (bug ja cometido: sem isto, cada
        # ranqueador pulava turnos diferentes -- denominadores 960/935/871
        # -- e as porcentagens nao eram comparaveis entre si). Criterio
        # independente do ranqueador testado: o humano jogou algo, OU o
        # motor baseline jogou algo.
        motor_jogou = any((d.get('motor_escolheu') or {}).get('kind') == 'play'
                          for d in decisoes)
        turnos.append({'game_id': gid, 'turn': turn,
                       'leader': decisoes[0]['leader'],
                       'decisoes': decisoes, 'humano': humano,
                       'avaliavel': bool(humano) or motor_jogou})
    return turnos


def avalia(turnos: list[dict], rank_fn) -> dict:
    """`rank_fn(candidatas, decisao) -> candidata escolhida` (ou None=passa).

    Devolve o `play` (conjunto exato) agregado e por lider.
    """
    ok = n = 0
    por_lider = defaultdict(lambda: [0, 0])
    for t in turnos:
        escolhido = set()
        for d in t['decisoes']:
            c = rank_fn(d['candidates'], d)
            if c and c.get('kind') == 'play':
                escolhido.add(c['code'])
        if not t['avaliavel']:
            continue
        n += 1
        acerto = escolhido == t['humano']
        ok += acerto
        p = por_lider[t['leader']]
        p[0] += acerto
        p[1] += 1
    return {'play': ok / n if n else 0.0, 'n': n,
            'por_lider': {k: (a / b, b) for k, (a, b) in por_lider.items()}}


def split_por_lider(turnos, frac_val=0.3, seed=13):
    """Treino/validacao separados por LIDER -- valida em decks NUNCA vistos."""
    import random
    lideres = sorted({t['leader'] for t in turnos})
    random.Random(seed).shuffle(lideres)
    n_val = max(1, int(len(lideres) * frac_val))
    val = set(lideres[:n_val])
    return ([t for t in turnos if t['leader'] not in val],
            [t for t in turnos if t['leader'] in val], val)


# ── Referencias pra VALIDAR o proprio proxy ────────────────────────────
def rank_motor(cands, d):
    """Reproduz a escolha REAL do motor (gravada no banco)."""
    m = d.get('motor_escolheu') or {}
    for c in cands:
        if c['kind'] == m.get('kind') and c.get('code') == m.get('code'):
            return c
    return None


def rank_estatico(cands, d):
    """Topo do score estatico -- o que a heuristica sozinha faria."""
    return max(cands, key=lambda c: c.get('score') or -1e9) if cands else None


def faz_oraculo():
    """Teto de um RE-RANQUEADOR: escolhe cartas do humano SEM repetir.

    ATENCAO -- bug ja cometido e corrigido aqui: a 1a versao devolvia a
    PRIMEIRA candidata com `humano_fez` em CADA decisao. Quando a mesma
    carta era candidata em varias decisoes do turno, ela era escolhida
    repetidamente e a 2a carta do humano nunca saia -- o teto aparecia
    como 59,3% quando na verdade era artefato do ranqueador, nao limite
    da arquitetura. Ranqueador com ESTADO (o que ja escolheu no turno)
    resolve; por isso e uma factory, nao uma funcao solta.
    """
    ja = set()
    ultimo_turno = [None]

    def rank(cands, d):
        chave = (d['game_id'], d['turn'])
        if ultimo_turno[0] != chave:
            ja.clear()
            ultimo_turno[0] = chave
        for c in cands:
            if (c['kind'] == 'play' and c.get('humano_fez')
                    and c['code'] not in ja):
                ja.add(c['code'])
                return c
        return None
    return rank


if __name__ == '__main__':
    turnos = agrupa_por_turno(carrega())
    print(f'{len(turnos)} turnos no banco\n')
    print('VALIDACAO DO PROXY -- `motor` tem que bater com os ~28,9% da regua real')
    for nome, fn in (('motor (real)', rank_motor),
                     ('score estatico', rank_estatico),
                     ('oraculo (re-ranqueador)', faz_oraculo())):
        r = avalia(turnos, fn)
        print(f'  {nome:16} play {r["play"]*100:5.1f}%   (n={r["n"]})')
    tr, va, lv = split_por_lider(turnos)
    print(f'\nsplit por LIDER: {len(tr)} turnos treino / {len(va)} validacao')
    print(f'  lideres de validacao (nunca vistos no treino): {sorted(lv)}')
