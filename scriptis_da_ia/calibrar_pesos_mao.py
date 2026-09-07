"""
calibrar_pesos_mao.py
=====================
Ajusta os pesos de `hand_scorer.py` contra WINRATE SIMULADO, em vez de
escolhe-los a mao.

POR QUE EXISTE (07/09/2026, pedido do usuario: "vamos calibrar esses pesos
contra winrate simulado")
--------------------------------------------------------------------------
Os pesos do score de mao de abertura -- 28 pro T1, 25 pro T2, 35 pro
searcher, 16/20 pro counter, -35 pra mao sem jogada -- eram numeros
escolhidos a mao, sem nenhuma medicao por tras. Pior: a MESMA tabela estava
duplicada em `avaliarMao()` no TypeScript, tendo como unica garantia de
consistencia um comentario dizendo "mesma logica de avaliarMao()".

Este script fecha os dois problemas: mede os pesos contra resultado real de
partida, e grava num JSON unico que os dois consumidores leem.

COMO FUNCIONA -- e por que ESPELHO e PAREADO
--------------------------------------------
A 1a versao simulava decks DIFERENTES entre si e ajustava
P(vitoria | features da mao). Deu AUC 0,579 e coeficientes absurdos:
`t1` (ter jogada no turno 1) virou **-36,5** e `so_custo1` (mao inteira de
custo 1) virou **+43,9**. O motivo e obvio depois de visto: **forca do deck
domina o resultado** e vazava pros coeficientes -- decks com muita carta de
custo 1 sao decks aggro, e o que o modelo aprendeu foi "aggro ganha", nao
"mao de custo 1 e boa".

O desenho atual elimina isso:

1. **Partidas-ESPELHO**: o mesmo deck dos dois lados. Forca de deck,
   arquetipo e matchup cancelam EXATAMENTE -- o que sobra e mao e posicao.
2. **Comparacao PAREADA**: cada partida vira `delta = features(A) -
   features(B)`, rotulo "A venceu". Tudo que e comum a partida some na
   subtracao. Cada partida entra duas vezes (A-B e B-A) pra ficar simetrica,
   e o modelo roda SEM intercepto.
3. **Posicao como controle explicito**: `indo_primeiro` entra como coluna,
   entao o efeito de jogar primeiro nao e absorvido pelos pesos das cartas.
4. Ajusta a logistica, reescala pra faixa dos pesos atuais e grava
   `pesos_mao.json`.
5. **Porta de estabilidade (bootstrap)**: cada peso so e ADOTADO se o sinal
   dele se sustentar em pelo menos `--estabilidade` das reamostragens. O
   resto mantem o fallback.

   Isto existe por causa da 2a rodada (AUC 0,601, desenho espelho): mesmo
   com forca de deck controlada, OITO pesos trocaram de sinal, incluindo
   `sem_nada` (mao SEM NENHUMA jogada) virando **+21**. Nao ha leitura de
   jogo que sustente isso -- a causa e COLINEARIDADE: varias features sao
   funcao deterministica de outras (`t1_t2 = t1 AND t2`,
   `sem_nada` e subconjunto de `sem_t1_t2`, `curva_completa` deriva das
   tres). Com colunas colineares a logistica reparte o efeito de forma
   arbitraria entre elas e o sinal individual vira ruido -- mesmo com a AUC
   agregada boa. A porta de estabilidade separa "o dado decidiu" de "o
   solver decidiu".

As features saem de `hand_scorer.extract_features` -- as MESMAS que o score
usa, sem reimplementacao aqui.

O QUE ESTE SCRIPT NAO RESOLVE -- leia antes de confiar no numero
----------------------------------------------------------------
- **Mao de abertura explica POUCO de vitoria.** Espere AUC na casa de
  0,55-0,60, nao 0,9. Isso NAO invalida os pesos: significa que eles agora
  refletem a direcao e a magnitude RELATIVA que o dado sustenta, em vez de
  palpite. Se a AUC vier ~0,50, o honesto e dizer que nao ha sinal e MANTER
  o fallback -- o script avisa e nao grava nesse caso.
- **Os modificadores por arquetipo continuam nao calibrados.** Nao ha
  amostra por arquetipo que sustente ajusta-los; seguem multiplicando por
  cima, como antes.
- O motor que joga as partidas e o mesmo que sera guiado pelo score. Isso
  mede "que mao faz ESTE motor ganhar", nao "que mao faz um humano ganhar".
  Limite conhecido e aceito -- e o mesmo do resto do tuning do projeto.

USO
---
    python calibrar_pesos_mao.py --n 400 --workers 2
    python calibrar_pesos_mao.py --n 400 --workers 2 --dry-run
"""
import argparse
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

AQUI = Path(__file__).parent
SAIDA = AQUI / 'pesos_mao.json'

# Piso de sinal: abaixo disso o ajuste nao e melhor que cara-ou-coroa e
# gravar os pesos seria trocar palpite por ruido.
AUC_MINIMA = 0.53

# Fracao das reamostragens que precisa concordar com o sinal do peso pra
# ele ser adotado. Abaixo disso, o dado nao determina o sinal.
ESTABILIDADE_MINIMA = 0.90
N_BOOTSTRAP = 200

# Suporte minimo: em quantos pares a feature precisa ser nao-nula pra receber
# peso proprio. Achado 07/09 investigando `c2k_excesso`: ele saia com +20,1 e
# 100% de estabilidade, mas o efeito BRUTO era 51,7% com IC95 [44,3; 59,0] --
# indistinguivel de zero -- porque so aparecia em 356 dos 4.938 pares. Coluna
# RARA precisa de coeficiente grande pra ter a mesma influencia, e o peso cru
# nao mostra isso: na escala PADRONIZADA ele caia pra +0,076, abaixo da
# cobertura de curva (+0,100). Medido: a porta em 400 custa 0,03pp de AUC
# (0,5989 -> 0,5986) e derruba os mal-suportados; em 600 ja custa 0,9pp.
SUPORTE_MINIMO = 400


def _carregar_pool(pool_size):
    from decision_quality_report import _load_deck_list
    return _load_deck_list(pool_size=pool_size)


# Cache POR PROCESSO do pool de decks. Sem isto cada tarefa reconstruia os
# decks a partir do CSV -- 8 recarregamentos do banco em 6 partidas no teste,
# com o custo de montagem dominando o de simular.
_POOL_CACHE = {}


def _pool(pool_size):
    if pool_size not in _POOL_CACHE:
        from decision_quality_report import _load_deck_list
        _POOL_CACHE[pool_size] = _load_deck_list(pool_size=pool_size)
    return _POOL_CACHE[pool_size]


def _uma_partida(task):
    """Roda 1 partida e devolve (features, venceu) dos DOIS lados."""
    idx, seed, pool_size = task
    import random as _r
    from simulation_worker import run_single_match
    import hand_scorer as hs

    deck_list = _pool(pool_size)
    if len(deck_list) < 2:
        return None
    rng = _r.Random(seed)
    # ESPELHO: o mesmo deck nos dois lados. Sem isto, forca de deck domina
    # o resultado e contamina todos os coeficientes (ver docstring).
    ia = rng.randrange(len(deck_list))
    _, deck_a = deck_list[ia]
    deck_b = deck_a
    _r.seed(seed)

    try:
        res = run_single_match(deck_a, deck_b)
    except Exception:
        return None

    # mapa codigo -> HandCard, pros dois decks
    def mapa(deck):
        leader, cards = deck[0], deck[1]
        m = {}
        for c in list(cards) + [leader]:
            hc = hs.card_to_handcard(c)
            m.setdefault(hc.code, hc)
        return m, hs.deck_to_handcards(list(cards))

    if res.get('winner') not in ('A', 'B'):
        return None

    m, mao_deck = mapa(deck_a)
    arq = hs.detect_archetype(mao_deck)
    sq = hs.searcher_quality(mao_deck)
    mod = hs._archetype_mod(arq)

    lados = {}
    for lado in ('a', 'b'):
        codes = res.get(f'opening_{lado}') or []
        mao = [m[c] for c in codes if c in m]
        if len(mao) < 5:
            return None
        gf = bool(res.get('first_a')) if lado == 'a' else not bool(res.get('first_a'))
        lados[lado] = (hs.extract_features(mao, gf, sq, None, aggro=mod['c2k'] < 1.0), gf)

    fa, gfa = lados['a']
    fb, gfb = lados['b']
    venceu_a = 1 if res.get('winner') == 'A' else 0

    # PAREADO e simetrico: a mesma partida entra nos dois sentidos.
    delta_ab = {k: fa[k] - fb[k] for k in fa}
    delta_ab['indo_primeiro'] = (1.0 if gfa else 0.0) - (1.0 if gfb else 0.0)
    delta_ba = {k: -v for k, v in delta_ab.items()}
    return [(delta_ab, venceu_a), (delta_ba, 1 - venceu_a)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=400, help='partidas a simular')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--pool', type=int, default=40, help='decks de torneio no pool')
    ap.add_argument('--seed', type=int, default=20260907)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--estabilidade', type=float, default=ESTABILIDADE_MINIMA,
                    help='fracao das reamostragens que precisa concordar com o sinal')
    ap.add_argument('--cache', default='dataset_maos.npz',
                    help='onde salvar/ler o dataset (evita re-simular pra reajustar)')
    ap.add_argument('--refit', action='store_true',
                    help='reajusta a partir do cache, sem simular nada')
    args = ap.parse_args()

    import hand_scorer as hs

    caminho_cache = AQUI / args.cache
    if args.refit:
        if not caminho_cache.exists():
            print(f'--refit pedido mas {args.cache} nao existe.')
            return 1
        dados = np.load(caminho_cache, allow_pickle=True)
        X, y, nomes = dados['X'], dados['y'], list(dados['nomes'])
        print(f'reajustando a partir de {args.cache} ({len(y)} comparacoes), sem simular')
    else:
        print(f'simulando {args.n} partidas com {args.workers} worker(s)...', flush=True)
        tarefas = [(i, args.seed * 1_000_003 + i, args.pool) for i in range(args.n)]
        amostras = []
        feitas = 0
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for res in ex.map(_uma_partida, tarefas):
                feitas += 1
                if res:
                    amostras.extend(res)
                if feitas % 25 == 0:
                    print(f'  {feitas}/{args.n} partidas, {len(amostras)} maos', flush=True)

        if len(amostras) < 100:
            print(f'AMOSTRA INSUFICIENTE ({len(amostras)} maos). Nada gravado.')
            return 1

        nomes = sorted(amostras[0][0].keys())
        X = np.array([[a[0][k] for k in nomes] for a in amostras], dtype=float)
        y = np.array([a[1] for a in amostras], dtype=int)
        np.savez_compressed(caminho_cache, X=X, y=y, nomes=np.array(nomes))
        print(f'dataset salvo em {args.cache} (use --refit pra reajustar sem simular)')
    print(f'\n{len(y)} comparacoes pareadas (espelho) | vitorias {y.mean()*100:.1f}%')

    # colunas constantes nao tem o que aprender
    suporte = (np.abs(X) > 1e-9).sum(axis=0)
    varia = (X.std(axis=0) > 1e-9) & (suporte >= SUPORTE_MINIMO)
    if not varia.any():
        print('nenhuma feature varia. Nada gravado.')
        return 1

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score

    Xv = X[:, varia]
    nomes_v = [n for n, v in zip(nomes, varia) if v]
    # sem intercepto: o desenho e simetrico por construcao, entao um
    # intercepto so poderia captar vies de rotulagem, nao efeito real.
    modelo = LogisticRegression(max_iter=2000, C=1.0, fit_intercept=False)

    auc = cross_val_score(modelo, Xv, y, cv=5, scoring='roc_auc').mean()
    print(f'AUC (validacao cruzada, 5 folds): {auc:.3f}')
    if auc < AUC_MINIMA:
        print(f'\nAUC abaixo do piso de {AUC_MINIMA} -- a mao de abertura nao')
        print('explica vitoria nesta amostra. MANTENDO o fallback; nada gravado.')
        print('Isso e um resultado valido, nao uma falha do script.')
        return 0

    modelo.fit(Xv, y)
    coef = dict(zip(nomes_v, modelo.coef_[0]))

    # ── Porta de estabilidade: o sinal aguenta reamostragem? ─────────────
    rng = np.random.default_rng(args.seed)
    sinais = {k: 0 for k in nomes_v}
    for _ in range(N_BOOTSTRAP):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) < 2:
            continue
        m2 = LogisticRegression(max_iter=2000, C=1.0, fit_intercept=False)
        m2.fit(Xv[idx], y[idx])
        for k, c in zip(nomes_v, m2.coef_[0]):
            if (c >= 0) == (coef[k] >= 0):
                sinais[k] += 1
    estab = {k: v / N_BOOTSTRAP for k, v in sinais.items()}

    # Reescala pra faixa dos pesos atuais: o resto da tela (e o `Threshold`
    # de mulligan) esta calibrado na ordem de grandeza de hoje, entao mudar
    # a ESCALA junto com os pesos misturaria dois efeitos.
    escala_atual = np.mean([abs(v) for v in hs.PESOS_FALLBACK.values()])
    escala_nova = np.mean([abs(v) for v in coef.values()]) or 1.0
    fator = escala_atual / escala_nova

    if 'indo_primeiro' in coef:
        print(f"\ncontrole: indo_primeiro = {coef['indo_primeiro']:+.3f} "
              f"(so controle, NAO entra nos pesos)")

    pesos = {}
    adotados = []
    print(f'\n{"peso":24s} {"antes":>8s} {"medido":>8s} {"estab":>7s}   decisao')
    for k in sorted(hs.PESOS_FALLBACK):
        antes = hs.PESOS_FALLBACK[k]
        if k not in coef:
            pesos[k] = antes
            print(f'{k:24s} {antes:8.1f} {"--":>8s} {"--":>7s}   '
                  f'mantido (suporte {int(suporte[nomes.index(k)]) if k in nomes else 0} < {SUPORTE_MINIMO})')
            continue
        medido = round(coef[k] * fator, 2)
        e = estab.get(k, 0.0)
        if e >= args.estabilidade:
            pesos[k] = medido
            adotados.append(k)
            troca = ' (TROCOU DE SINAL, mas estavel)' if (antes >= 0) != (medido >= 0) else ''
            print(f'{k:24s} {antes:8.1f} {medido:8.1f} {e*100:6.0f}%   ADOTADO{troca}')
        else:
            pesos[k] = antes
            print(f'{k:24s} {antes:8.1f} {medido:8.1f} {e*100:6.0f}%   mantido (sinal instavel)')

    print(f'\n{len(adotados)} de {len(hs.PESOS_FALLBACK)} pesos adotados; o resto ficou no fallback.')
    if not adotados:
        print('Nenhum peso passou na porta de estabilidade. Nada gravado.')
        return 0

    if args.dry_run:
        print('\n--dry-run: nada gravado.')
        return 0

    SAIDA.write_text(json.dumps({
        'n_maos': int(len(y)),
        'n_partidas': args.n,
        'auc': round(float(auc), 4),
        'fonte': 'decklists_raw.csv + simulacao (simulation_worker.run_single_match)',
        'pesos': pesos,
        'adotados': adotados,
        'estabilidade_minima': args.estabilidade,
        'estabilidade': {k: round(v, 3) for k, v in estab.items()},
    }, indent=2), encoding='utf-8')
    print(f'\n-> {SAIDA.name} gravado')
    return 0


if __name__ == '__main__':
    sys.exit(main())
