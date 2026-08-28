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

e o criterio de aceite e:

    **o termo sobe o `play` no HOLDOUT?**

### CRITERIO ERRADO JA USADO AQUI, E CORRIGIDO (bloco 717)

A 1a versao deste arquivo usava **ganho de AUC** como criterio. Ele
reprovou a si mesmo no 1o uso: `counter_perdido` subiu o AUC do holdout
de 0,592 pra **0,657** (+0,065) e, com os 3 termos aprovados, o `play` do
holdout **CAIU de 23,9% pra 20,7%**.

E o MESMO padrao do bloco 683 (AUC 0,851 com metrica real PIOR), repetido
por mim no mesmo dia em que citei aquele bloco como licao. A causa: **AUC
mede ordenacao par a par; `play` mede o CONJUNTO exato do turno.** Um
modelo pode ordenar melhor em media e ainda montar conjuntos errados. E
ajustar pesos por maxima verossimilhanca otimiza a probabilidade da
escolha, nao o acerto do conjunto.

**Regra que fica: neste projeto, so `play` medido no holdout aceita ou
reprova um termo. AUC serve no maximo como pista para gerar candidatos --
nunca como criterio.**

(Achado colateral que sobrevive: os pesos de PRODUCAO, escritos a mao,
dao `play` 29,1% no holdout e batem QUALQUER ajuste estatistico testado
-- 23,9% com 14 termos, 20,7% com 17.)

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


# ══ CRITERIO CORRETO: `play` no holdout ════════════════════════════════
def avalia_por_play(nome_termo=None, n_pontos=13):
    """Aceita/reprova um termo pelo `play` no HOLDOUT -- nao por AUC.

    Mantem os pesos de PRODUCAO fixos (eles batem qualquer ajuste
    estatistico testado) e varre APENAS o coeficiente do termo novo,
    escolhendo-o no TREINO. Isola a contribuicao do termo e nao refaz o
    erro de re-ajustar tudo por verossimilhanca.
    """
    import json as _j
    from collections import defaultdict
    from optcg_engine.decision_engine import EVAL_WEIGHTS
    chaves, turnos = prepara(carrega())
    props = props_das_cartas()
    hold = set(_j.load(open('metrics/holdout_lideres.json')))
    tr = [d for d in turnos if d[0]['leader'] not in hold]
    va = [d for d in turnos if d[0]['leader'] in hold]
    w0 = np.array([EVAL_WEIGHTS.get(k, 0.0) for k in chaves])

    def play(turnos_, coef):
        ok = n = 0
        for dec in turnos_:
            hum = dec[0]['humano']; esc = set()
            for d in dec:
                e = d.get('estado') or {}
                v = d['M'] @ w0 + d['res']
                if nome_termo and coef:
                    f = CANDIDATOS[nome_termo]
                    v = v + coef * np.array(
                        [f(e, props.get(c) or {}, k)
                         for c, k in zip(d['code'], d['kind'])])
                i = int(np.argmax(v))
                if d['kind'][i] == 'play' and d['code'][i]:
                    esc.add(d['code'][i])
            if hum or esc:
                n += 1; ok += esc == hum
        return ok / n if n else 0.0

    base_tr, base_va = play(tr, 0.0), play(va, 0.0)
    if not nome_termo:
        return {'termo': '(base)', 'coef': 0.0,
                'play_tr': base_tr, 'play_va': base_va, 'ganho': 0.0}
    melhor = (0.0, base_tr)
    for c in np.concatenate([-np.logspace(-1, 2.5, n_pontos),
                             np.logspace(-1, 2.5, n_pontos)]):
        v = play(tr, float(c))
        if v > melhor[1]:
            melhor = (float(c), v)
    coef = melhor[0]
    return {'termo': nome_termo, 'coef': coef, 'play_tr': melhor[1],
            'play_va': play(va, coef), 'ganho': play(va, coef) - base_va}


# ══ TERMOS DE INTERACAO CARTA-A-CARTA (bloco 719) ══════════════════════
# A LACUNA ESTRUTURAL. Todos os termos acima -- os 14 do motor e os 14
# candidatos -- sao AGREGADOS: contagens, somas, medias. Uma soma
# ponderada de agregados **nao consegue representar "esta carta responde
# aquela carta"**, e o bloco 716 mediu exatamente isso (AUC 0,611).
#
# Estes leem o BOARD CONCRETO (`board_meu`/`board_opp`, que so passaram a
# existir no bloco 719) e computam relacoes PAR A PAR entre a carta
# candidata e cada carta adversaria, agregando por max/soma. E um
# "DeepSets manual": captura interacao sem exigir rede neural (torch nao
# esta disponivel neste ambiente) e sem usar identidade de carta.

def _op(est):
    return est.get('board_opp') or []

def _meu(est):
    return est.get('board_meu') or []

def i_mata_alguem(est, prop, kind):
    """Meu poder supera o poder ATUAL de alguma carta dele? (remocao real)"""
    pw = float(prop.get('power', 0)) * 1000.0
    return 1.0 if any(pw > float(c.get('current_power') or 0) for c in _op(est)) else 0.0

def i_maior_alvo_batido(est, prop, kind):
    """Poder do MAIOR alvo que este corpo consegue superar."""
    pw = float(prop.get('power', 0)) * 1000.0
    alvos = [float(c.get('current_power') or 0) for c in _op(est)
             if pw > float(c.get('current_power') or 0)]
    return (max(alvos) / 1000.0) if alvos else 0.0

def i_sobrevive_ao_board(est, prop, kind):
    """Meu corpo sobrevive a TODOS os ataques dele? (nao morre de graca)"""
    pw = float(prop.get('power', 0)) * 1000.0
    return 1.0 if all(pw > float(c.get('current_power') or 0)
                      for c in _op(est)) and _op(est) else 0.0

def i_morre_de_graca(est, prop, kind):
    """Entra e morre pra qualquer coisa dele -- o oposto do anterior."""
    pw = float(prop.get('power', 0)) * 1000.0
    return 1.0 if _op(est) and all(pw <= float(c.get('current_power') or 0)
                                   for c in _op(est)) else 0.0

def i_passa_do_blocker(est, prop, kind):
    """Supera o maior BLOCKER dele -- destrava dano que hoje nao passa."""
    pw = float(prop.get('power', 0)) * 1000.0
    bl = [float(c.get('current_power') or 0) for c in _op(est) if c.get('blocker')]
    return 1.0 if bl and pw > max(bl) else 0.0

def i_gap_maior_ameaca(est, prop, kind):
    """Distancia entre meu corpo e a MAIOR ameaca dele (negativo = perco)."""
    pw = float(prop.get('power', 0)) * 1000.0
    mx = max((float(c.get('current_power') or 0) for c in _op(est)), default=0.0)
    return (pw - mx) / 1000.0

def i_meu_board_ja_cobre(est, prop, kind):
    """Meu board JA supera a maior ameaca -- mais um corpo e redundante."""
    mx_op = max((float(c.get('current_power') or 0) for c in _op(est)), default=0.0)
    mx_meu = max((float(c.get('current_power') or 0) for c in _meu(est)), default=0.0)
    return 1.0 if mx_meu > mx_op else 0.0

def i_ativos_dele(est, prop, kind):
    """Cartas ATIVAS dele (podem bloquear/atacar) -- pressao real, nao contagem."""
    return float(sum(1 for c in _op(est) if not c.get('rested')))

def i_blocker_supera_todos(est, prop, kind):
    """Blocker que segura TUDO que ele tem -- muito diferente de 'tem blocker'."""
    if not prop.get('blocker'):
        return 0.0
    pw = float(prop.get('power', 0)) * 1000.0
    return 1.0 if all(pw > float(c.get('current_power') or 0) for c in _op(est)) else 0.0

def i_don_dele_no_board(est, prop, kind):
    return float(sum(c.get('don') or 0 for c in _op(est)))


CANDIDATOS.update({
    'i_mata_alguem': i_mata_alguem,
    'i_maior_alvo_batido': i_maior_alvo_batido,
    'i_sobrevive_ao_board': i_sobrevive_ao_board,
    'i_morre_de_graca': i_morre_de_graca,
    'i_passa_do_blocker': i_passa_do_blocker,
    'i_gap_maior_ameaca': i_gap_maior_ameaca,
    'i_meu_board_ja_cobre': i_meu_board_ja_cobre,
    'i_ativos_dele': i_ativos_dele,
    'i_blocker_supera_todos': i_blocker_supera_todos,
    'i_don_dele_no_board': i_don_dele_no_board,
})
