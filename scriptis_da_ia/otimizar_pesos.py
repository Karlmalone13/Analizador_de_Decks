"""Busca CONJUNTA sobre os 17 pesos de `EVAL_WEIGHTS`, contra o `play`.

POR QUE ISTO NAO E A 12a TENTATIVA DE "TUNAR PESO"
--------------------------------------------------
As 11 reprovadas mudavam **UM peso por vez, a mao, medindo ~20 min por
valor** -- nessa velocidade o espaco de 17 dimensoes e inexploravel, e o
que se testava era sempre um eixo isolado. Aqui, gracas a decomposicao em
termos (bloco 709), avaliar um vetor de pesos e um **produto escalar
sobre valores ja simulados**: milhares de configuracoes por segundo, o
espaco CONJUNTO. Metodo diferente, nao repeticao. (Pedido direto do
usuario: *"a gente so precisa mudar a estrutura ... pra que a gente
consiga aumentar ou diminuir os parametros pra fazer essas porcentagem
subir"*.)

METRICA: o `play` oficial (conjunto de cartas jogadas no turno).

DISCIPLINA (erros ja cometidos nesta sessao, nao repetir)
---------------------------------------------------------
- **Nada e escolhido olhando a validacao** (bloco 704): a busca roda so
  no TREINO; a validacao e olhada uma vez, no fim.
- **Generalizacao exige CV agrupada por LIDER** (bloco 706): um split
  unico ja produziu um "+4,8pp" que era ruido.

LIMITE HERDADO: offline o estado nao se atualiza conforme os pesos mudam
a escolha -- e o mesmo *distribution shift* de sempre. O numero daqui
FILTRA hipotese; quem decide e `decision_quality_full.py`.
"""
from __future__ import annotations

import argparse, json, os
from collections import defaultdict

import numpy as np

from optcg_engine.decision_engine import EVAL_WEIGHTS

DATASET = 'metrics/termos_dataset.jsonl'


def carrega(path=DATASET):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def prepara(linhas):
    """Vetoriza: por decisao, matriz (candidatas x termos) + residuo."""
    chaves = sorted({k for d in linhas for c in d['candidates']
                     for k in c['termos']})
    idx = {k: i for i, k in enumerate(chaves)}
    por_turno = defaultdict(list)
    for d in linhas:
        M = np.zeros((len(d['candidates']), len(chaves)), dtype=np.float64)
        for i, c in enumerate(d['candidates']):
            for k, v in c['termos'].items():
                M[i, idx[k]] = v
        por_turno[(d['game_id'], d['turn'])].append({
            'M': M,
            'res': np.array([c['residuo'] for c in d['candidates']]),
            'kind': [c['kind'] for c in d['candidates']],
            'code': [c['code'] for c in d['candidates']],
            'leader': d['leader'],
            'humano': set(d['humano']),
            'humano_don': set(d.get('humano_don') or []),
            'estado': d.get('estado') or {},
        })
    return chaves, list(por_turno.values())


def metricas_de(turnos, w):
    """`play` E `don_alvo` sob o vetor `w`. Puro produto escalar.

    bloco 714: `don_alvo` entrou aqui porque a otimizacao de objetivo
    UNICO do bloco 713 comprou `play` (+1,9pp no holdout) vendendo
    `don_alvo` (**-8,0pp**) -- e o otimizador nunca viu o estrago, porque
    a metrica nao existia pra ele. Ele nao errou: acertou o alvo errado.
    """
    ok = n = 0
    ok_don = n_don = 0
    por = defaultdict(lambda: [0, 0])
    for decisoes in turnos:
        escolhido, escolhido_don = set(), set()
        for d in decisoes:
            v = d['M'] @ w + d['res']
            i = int(np.argmax(v))
            if d['code'][i]:
                if d['kind'][i] == 'play':
                    escolhido.add(d['code'][i])
                elif d['kind'][i] == 'attach_don':
                    escolhido_don.add(d['code'][i])
        hum = decisoes[0]['humano']
        hum_don = decisoes[0].get('humano_don', set())
        if hum or escolhido:
            n += 1
            a = escolhido == hum
            ok += a
            p = por[decisoes[0]['leader']]
            p[0] += a; p[1] += 1
        if hum_don or escolhido_don:
            n_don += 1
            ok_don += escolhido_don == hum_don
    return {'play': ok / n if n else 0.0, 'n': n,
            'don': ok_don / n_don if n_don else 0.0, 'n_don': n_don,
            'por_lider': {k: (x / y, y) for k, (x, y) in por.items()}}


def play_de(turnos, w):
    """Compatibilidade: so o `play` (usado pelos relatorios existentes)."""
    m = metricas_de(turnos, w)
    return m['play'], m['n'], m['por_lider']


def objetivo(turnos, w, base_don, penalidade=3.0):
    """MULTI-OBJETIVO: `play` penalizado por REGREDIR `don_alvo`.

    `max(0, base_don - don)` so pune QUEDA -- melhorar `don_alvo` nao
    rende bonus, entao o otimizador nao troca `play` por DON tambem no
    sentido inverso. `penalidade=3.0` significa que 1pp perdido em
    `don_alvo` precisa de 3pp ganhos em `play` pra compensar: a queda do
    bloco 713 (-8,0pp de DON por +1,9pp de play) seria REJEITADA.
    """
    m = metricas_de(turnos, w)
    return m['play'] - penalidade * max(0.0, base_don - m['don'])


def busca(turnos, w0, chaves, n_iter=4000, seed=13, penalidade=3.0):
    """Subida de encosta com passos aleatorios multiplicativos.

    O criterio e `objetivo()` (multi-objetivo), nao `play` puro -- ver
    bloco 714. O valor RETORNADO continua sendo o `play`, pra os
    relatorios seguirem comparaveis com as medicoes anteriores.
    """
    rng = np.random.RandomState(seed)
    w = w0.copy()
    base_don = metricas_de(turnos, w0)['don']
    melhor = objetivo(turnos, w, base_don, penalidade)
    escala = 0.6
    sem_ganho = 0
    for it in range(n_iter):
        cand = w.copy()
        # perturba um subconjunto aleatorio (busca CONJUNTA, nao 1-a-1)
        k = rng.randint(1, max(2, len(w) // 2))
        for i in rng.choice(len(w), size=k, replace=False):
            cand[i] *= float(np.exp(rng.randn() * escala))
        v = objetivo(turnos, cand, base_don, penalidade)
        if v > melhor:
            melhor, w, sem_ganho = v, cand, 0
        else:
            sem_ganho += 1
            if sem_ganho > 400:
                escala *= 0.7
                sem_ganho = 0
                if escala < 0.02:
                    break
    return w, play_de(turnos, w)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iter', type=int, default=4000)
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--out', default='eval_weights_otimizado.json')
    a = ap.parse_args()

    linhas = carrega()
    chaves, turnos = prepara(linhas)
    w0 = np.array([EVAL_WEIGHTS.get(k, 0.0) for k in chaves], dtype=np.float64)
    print(f'{len(turnos)} turnos, {len(chaves)} termos: {chaves}')
    base_play, n, _ = play_de(turnos, w0)
    print(f'pesos ATUAIS: play {base_play*100:.1f}% (n={n})\n')

    lideres = sorted({d[0]['leader'] for d in turnos})
    rng = np.random.RandomState(13)
    ordem = list(lideres); rng.shuffle(ordem)
    folds = [set(ordem[i::a.folds]) for i in range(a.folds)]

    print('CV agrupada por LIDER -- busca SO no treino de cada fold')
    print(f'{"fold":>5}{"base tr":>10}{"otim tr":>10}{"base val":>11}{"otim val":>11}')
    acc_b = acc_o = tot = 0
    for f_i, f in enumerate(folds):
        tr = [d for d in turnos if d[0]['leader'] not in f]
        va = [d for d in turnos if d[0]['leader'] in f]
        if not tr or not va:
            continue
        w, v_tr = busca(tr, w0, chaves, a.iter, seed=13 + f_i)
        b_tr = play_de(tr, w0)[0]
        b_va, n_va, _ = play_de(va, w0)
        o_va = play_de(va, w)[0]
        print(f'{f_i:>5}{b_tr*100:9.1f}%{v_tr*100:9.1f}%'
              f'{b_va*100:10.1f}%{o_va*100:10.1f}%')
        acc_b += b_va * n_va; acc_o += o_va * n_va; tot += n_va
    print(f'\n  CV VALIDACAO -- baseline {acc_b/tot*100:.1f}%  '
          f'otimizado {acc_o/tot*100:.1f}%  '
          f'delta {(acc_o-acc_b)/tot*100:+.1f}pp  (n={tot})')

    w_final, v_final = busca(turnos, w0, chaves, a.iter, seed=99)
    print(f'\n  busca no corpus INTEIRO (pra publicar): {v_final*100:.1f}% '
          f'(era {base_play*100:.1f}%)')
    pesos = {k: float(v) for k, v in zip(chaves, w_final)}
    json.dump({**{k: EVAL_WEIGHTS[k] for k in EVAL_WEIGHTS}, **pesos,
               '_meta': {'origem': 'otimizar_pesos.py bloco 710',
                         'play_treino': v_final,
                         'aviso': 'offline; validar em decision_quality_full.py'}},
              open(a.out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'  gravado em {a.out} (NAO e eval_weights.json -- publicar so apos a regua real)')


if __name__ == '__main__':
    main()
