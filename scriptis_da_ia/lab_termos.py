"""LABORATORIO DE TERMOS: um termo novo carrega sinal? (bloco 717)

O QUE O BLOCO 716 PROVOU
------------------------
Os 14 termos de `_evaluate_state_v2` **nao carregam a informacao**: o
MELHOR ajuste linear possivel sobre eles da **AUC 0,611** (aleatorio =
0,500) e fica ABAIXO do baseline, enquanto o oraculo mostra 79%
disponivel nas mesmas candidatas. Isso fechou tres becos de uma vez
(busca de pesos, ranqueador de 59 features, curva de aprendizado) com
uma causa unica: REPRESENTACAO.

O QUE ESTE ARQUIVO E
--------------------
A infraestrutura "controlavel e observavel" aplicada no nivel certo:
**termos PLUGAVEIS**. Cada termo candidato e uma funcao pura

    termo(estado, propriedades_da_carta, kind) -> float

e o criterio de aceite e objetivo e barato:

    **o termo sobe o AUC do ajuste direto sobre os 14 atuais?**

Se sobe, ele carrega sinal que os 14 nao tem -- e so entao vale
implementa-lo no motor. Se nao sobe, foi reprovado em SEGUNDOS, sem
medicao de 20 minutos e sem risco de confundir ruido com ganho (erro que
esta sessao cometeu 4 vezes).

REGRA MANTIDA: nenhum termo pode usar identidade de carta ou de lider --
so PROPRIEDADES e relacoes com o estado, senao o motor memoriza e quebra
no 1o deck novo (requisito "qualquer deck", bloco 702).

VALIDACAO: AUC no HOLDOUT por lider, nunca so no treino.
"""
from __future__ import annotations

import json
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from otimizar_pesos import carrega, prepara
from treinar_ranqueador import props_das_cartas


# ══ TERMOS CANDIDATOS ═══════════════════════════════════════════════════
# Assinatura: f(est, prop, kind) -> float.  `est` = estado no instante da
# decisao (`context` do decision_log); `prop` = propriedades da carta.
# NENHUM usa codigo de carta/lider.

def t_custo_vs_don(est, prop, kind):
    """Fracao do DON disponivel que a jogada consome. Tempo/eficiencia."""
    don = float(est.get('don_available') or 0)
    return (float(prop.get('cost', 0)) / don) if don > 0 else 0.0

def t_sobra_don(est, prop, kind):
    """DON que SOBRA depois de jogar -- 0 significa turno bem aproveitado."""
    return float(est.get('don_available') or 0) - float(prop.get('cost', 0))

def t_poder_por_custo(est, prop, kind):
    """Corpo por DON gasto."""
    c = float(prop.get('cost', 0))
    return float(prop.get('power', 0)) / c if c > 0 else 0.0

def t_blocker_sob_pressao(est, prop, kind):
    """Blocker vale mais quando o oponente ameaca -- interacao, nao flag."""
    return (float(prop.get('blocker', 0))
            * float(est.get('opp_board_power_total') or 0) / 10.0)

def t_blocker_vida_baixa(est, prop, kind):
    return float(prop.get('blocker', 0)) * max(0.0, 5 - float(est.get('life') or 0))

def t_remocao_vs_board(est, prop, kind):
    """Efeito de remocao vale com board adversario ocupado."""
    tem = float(prop.get('tem_on_play', 0))
    return tem * float(est.get('opp_field') or 0)

def t_counter_perdido(est, prop, kind):
    """Jogar uma carta com counter alto gasta municao defensiva."""
    return -float(prop.get('counter', 0))

def t_counter_perdido_sob_risco(est, prop, kind):
    return -float(prop.get('counter', 0)) * max(0.0, 5 - float(est.get('life') or 0))

def t_rush_com_don(est, prop, kind):
    """Rush so vale se ha DON pra atacar depois de jogar."""
    sobra = float(est.get('don_available') or 0) - float(prop.get('cost', 0))
    return float(prop.get('rush', 0)) * max(0.0, sobra)

def t_mao_apertada(est, prop, kind):
    """Gastar carta com a mao curta pesa mais."""
    return -1.0 / max(1.0, float(est.get('hand') or 1))

def t_efeito_com_mao(est, prop, kind):
    """Efeito [On Play] que depende de recurso na mao."""
    return float(prop.get('tem_on_play', 0)) * float(est.get('hand') or 0)

def t_activate_futuro(est, prop, kind):
    """Corpo com [Activate: Main] rende nos turnos seguintes."""
    return float(prop.get('tem_activate', 0))

def t_evento_vs_personagem(est, prop, kind):
    return float(prop.get('is_event', 0)) - float(prop.get('is_char', 0))

def t_curva_alta_cedo(est, prop, kind):
    """Carta cara com pouco DON = jogada impossivel/ruim cedo."""
    return max(0.0, float(prop.get('cost', 0)) - float(est.get('don_available') or 0))


CANDIDATOS = {
    'custo_vs_don': t_custo_vs_don,
    'sobra_don': t_sobra_don,
    'poder_por_custo': t_poder_por_custo,
    'blocker_sob_pressao': t_blocker_sob_pressao,
    'blocker_vida_baixa': t_blocker_vida_baixa,
    'remocao_vs_board': t_remocao_vs_board,
    'counter_perdido': t_counter_perdido,
    'counter_perdido_sob_risco': t_counter_perdido_sob_risco,
    'rush_com_don': t_rush_com_don,
    'mao_apertada': t_mao_apertada,
    'efeito_com_mao': t_efeito_com_mao,
    'activate_futuro': t_activate_futuro,
    'evento_vs_personagem': t_evento_vs_personagem,
    'curva_alta_cedo': t_curva_alta_cedo,
}


def monta(turnos, props, extras=()):
    """(X, y, grupo) com os 14 termos atuais + os termos `extras`."""
    X, y, g = [], [], []
    for decisoes in turnos:
        hum = decisoes[0]['humano']
        lider = decisoes[0]['leader']
        est = decisoes[0].get('estado') or {}
        for d in decisoes:
            e = d.get('estado') or est
            for i, k in enumerate(d['kind']):
                if k != 'play' or not d['code'][i]:
                    continue
                p = props.get(d['code'][i]) or {}
                v = list(d['M'][i])
                v += [CANDIDATOS[n](e, p, k) for n in extras]
                X.append(v)
                y.append(1 if d['code'][i] in hum else 0)
                g.append(lider)
    return np.array(X, dtype=np.float64), np.array(y), g


def auc(Xtr, ytr, Xva, yva):
    sc = StandardScaler().fit(Xtr)
    lr = LogisticRegression(max_iter=3000, C=1.0).fit(sc.transform(Xtr), ytr)
    return (roc_auc_score(ytr, lr.decision_function(sc.transform(Xtr))),
            roc_auc_score(yva, lr.decision_function(sc.transform(Xva))))


def main():
    chaves, turnos = prepara(carrega())
    props = props_das_cartas()
    hold = set(json.load(open('metrics/holdout_lideres.json')))
    tr = [d for d in turnos if d[0]['leader'] not in hold]
    va = [d for d in turnos if d[0]['leader'] in hold]

    Xtr, ytr, _ = monta(tr, props)
    Xva, yva, _ = monta(va, props)
    a_tr, a_va = auc(Xtr, ytr, Xva, yva)
    print(f'{len(Xtr)} candidatas treino / {len(Xva)} holdout')
    print(f'\nBASE (so os 14 termos atuais): AUC treino {a_tr:.3f}  '
          f'HOLDOUT {a_va:.3f}\n')
    print(f'{"termo candidato":30}{"AUC hold":>10}{"ganho":>9}')
    print('=' * 49)
    res = []
    for nome in CANDIDATOS:
        X1, y1, _ = monta(tr, props, (nome,))
        X2, y2, _ = monta(va, props, (nome,))
        _, v = auc(X1, y1, X2, y2)
        res.append((v - a_va, nome, v))
    res.sort(reverse=True)
    for d, nome, v in res:
        marca = '  <-- carrega sinal' if d > 0.01 else ''
        print(f'{nome:30}{v:9.3f}{d:+9.3f}{marca}')

    bons = [n for d, n, _ in res if d > 0.01]
    if bons:
        X1, y1, _ = monta(tr, props, tuple(bons))
        X2, y2, _ = monta(va, props, tuple(bons))
        t2, v2 = auc(X1, y1, X2, y2)
        print(f'\nTODOS os que passaram ({len(bons)}): AUC treino {t2:.3f}  '
              f'HOLDOUT {v2:.3f}  ({v2-a_va:+.3f})')
        print(f'  {bons}')


if __name__ == '__main__':
    main()
