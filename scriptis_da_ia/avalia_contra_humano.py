# -*- coding: utf-8 -*-
"""AVALIACAO CONTRA PARTIDAS HUMANAS REAIS -- roda em TODO ciclo (bloco 805).

Pergunta do usuario: *"coloque essas avaliacoes onde a gente nao vai esquecer
de usa-las"*. Resposta: aqui, e chamado pelo `ciclo.py` na etapa 4. Nao depende
do tempo dele e nao pode ser esquecido -- se nao rodar, o ciclo diz.

## Por que isto existe, e por que nao e telemetria

Telemetria e o que o bot GRAVA enquanto joga (decision log, recibos). Isto e
ANALISE sobre o banco de partidas humanas ja coletadas.

E existe porque o laco de treino e inteiramente auto-referente: o alvo vem do
modelo, o dado vem do modelo jogando contra si mesmo, e o portao compara o
modelo com uma versao dele. **Nada ali esta ancorado em vencer um humano**, e um
vicio COMPARTILHADO e invisivel ao auto-jogo por construcao (achado do usuario,
bloco 780: decidir o blocker no CHUTE nao mudou uma partida em 80 pares).

Estas medidas sao a ancora BARATA. A cara -- jogar contra o usuario -- o
`ciclo.py` so pede quando o portao promove.

## O que virou possivel, e por que so agora

Os logs guardam **as duas maos, carta por carta**, em 113 dos 171 registros
(medido no bloco 805). Enquanto se supunha a mao do adversario desconhecida,
nenhuma destas medidas existia.

## As duas medidas

1. **O MODELO DE OPONENTE ACERTA?** `opponent_model.py` sorteia maos plausiveis
   do que sobrou do deck, e **ninguem nunca conferiu se acerta**. Aqui a mao
   sorteada e comparada com a mao REAL do log.

2. **QUANTO CUSTA A INCERTEZA?** A MESMA posicao avaliada as cegas e com a mao
   do adversario aberta. Mede direto o que o usuario levantou em 12/09 -- e em
   posicao REAL contra humano, nao em auto-jogo.

## O que NAO esta aqui, de proposito

O "professor com informacao perfeita" (calcular a jogada certa em retrospecto)
**nao e avaliacao, e sinal de TREINO** -- entraria em `treinar_q.py`, nao aqui.
E carrega risco ja registrado (bloco 781): professor que ve demais produz alvo
INALCANCAVEL -- *"esta posicao e vencedora SE voce souber que ele nao tem
counter"*, e o aluno nunca vai saber. Usar exigiria media sobre mundos
possiveis, nao a resposta do mundo real. Fica como candidato, nao como feito.

Uso:
    python avalia_contra_humano.py              # todas as utilizaveis
    python avalia_contra_humano.py --limite 10
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

RAIZ = Path(__file__).parent
INDEX = RAIZ / 'logs' / 'index.json'
SAIDA = RAIZ / 'metrics' / 'avaliacao_humana'


def posicoes_utilizaveis(limite=None):
    """(registro, turno) com as DUAS maos reais e `bot_side` conhecido."""
    dados = json.loads(INDEX.read_text(encoding='utf-8'))
    regs = dados if isinstance(dados, list) else dados.get('logs', [])
    saida = []
    for r in regs:
        if not r.get('bot_side') or not r.get('parsed_file'):
            continue
        p = RAIZ / 'logs' / r['parsed_file']
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        for t in (d.get('turns') or []):
            sn = t.get('snapshot') or {}
            a = (sn.get('You') or {}).get('hand')
            b = (sn.get('Opponent') or {}).get('hand')
            if not (a and b):
                continue
            if any('UNKNOWN' in str(x) for x in list(a) + list(b)):
                continue
            saida.append((r, t))
            if limite and len(saida) >= limite:
                return saida
    return saida


def mede_modelo_oponente(posicoes) -> dict:
    """Das cartas que o modelo SORTEIA, quantas o adversario de fato tinha?"""
    from optcg_engine.sim_bridge import opponent_model_for_leader

    acertos, totais, amostras = [], [], 0
    for r, t in posicoes:
        lado_bot = r['bot_side']
        lado_log = 'You' if lado_bot == 'p1' else 'Opponent'
        lado_opp = 'Opponent' if lado_bot == 'p1' else 'You'
        sn = t.get('snapshot') or {}
        mao_real = [str(x) for x in ((sn.get(lado_opp) or {}).get('hand') or [])]
        if not mao_real:
            continue
        pdata = r.get('p2' if lado_bot == 'p1' else 'p1') or {}
        modelo = opponent_model_for_leader(pdata.get('leader_code', ''),
                                           pdata.get('leader_name', ''))
        if modelo is None:
            continue
        try:
            sorteada = modelo.sample(len(mao_real), rng=random)
        except Exception:
            continue
        cods = [getattr(c, 'code', str(c)) for c in (sorteada or [])]
        if not cods:
            continue
        acerto = len(set(cods) & set(mao_real))
        acertos.append(acerto)
        totais.append(len(mao_real))
        amostras += 1
    if not amostras:
        return {'amostras': 0}
    taxa = 100.0 * sum(acertos) / max(1, sum(totais))
    return {'amostras': amostras, 'acerto_pct': round(taxa, 1),
            'acertos_medios': round(statistics.mean(acertos), 2),
            'cartas_por_mao': round(statistics.mean(totais), 1)}


def mede_custo_da_incerteza(posicoes) -> dict:
    """A mesma posicao avaliada as CEGAS e com a mao do adversario ABERTA."""
    from optcg_engine import value_net as vn
    from optcg_engine.decision_engine import GameState, _make_card, load_cards_db
    bundle = vn.load_value_net(str(RAIZ / 'metrics' / 'value_net_aluno.joblib'))
    if not bundle:
        return {'amostras': 0, 'motivo': 'sem modelo compativel'}
    db = load_cards_db(str(RAIZ / 'cards_rows.csv'))

    def get_card(code):
        d = db.get(str(code))
        return _make_card(str(code), d) if d else None

    difs = []
    for r, t in posicoes:
        lado_bot = r['bot_side']
        lado_log = 'You' if lado_bot == 'p1' else 'Opponent'
        lado_opp = 'Opponent' if lado_bot == 'p1' else 'You'
        sn = t.get('snapshot') or {}
        eu, ele = sn.get(lado_log) or {}, sn.get(lado_opp) or {}
        if not (eu.get('hand') and ele.get('hand')):
            continue
        try:
            def monta(d, lider_code):
                lider = get_card(lider_code) if lider_code else None
                st = GameState(leader=lider) if lider else None
                if st is None:
                    return None
                st.hand = [c for c in (get_card(x) for x in d.get('hand') or []) if c]
                st.field_chars = [c for c in (get_card(x) for x in d.get('board') or []) if c]
                st.trash = [c for c in (get_card(x) for x in d.get('trash') or []) if c]
                st.life = [c for c in (get_card(x) for x in d.get('life_cards') or []) if c] \
                    or [None] * int(d.get('life') or 0)
                st.life = [c for c in st.life if c is not None] or st.life
                return st
            pd = r.get('p1' if lado_bot == 'p1' else 'p2') or {}
            od = r.get('p2' if lado_bot == 'p1' else 'p1') or {}
            me = monta(eu, pd.get('leader_code'))
            op = monta(ele, od.get('leader_code'))
            if me is None or op is None:
                continue
            aberta = vn.win_prob(me, op, bundle=bundle)
            mao_guardada = op.hand
            op.hand = []
            cega = vn.win_prob(me, op, bundle=bundle)
            op.hand = mao_guardada
            if aberta is None or cega is None:
                continue
            difs.append(abs(aberta - cega))
        except Exception:
            continue
    if not difs:
        return {'amostras': 0}
    return {'amostras': len(difs),
            'diferenca_mediana': round(statistics.median(difs), 4),
            'diferenca_media': round(statistics.mean(difs), 4),
            'maxima': round(max(difs), 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--limite', type=int, default=200)
    args = ap.parse_args()

    pos = posicoes_utilizaveis(args.limite)
    print()
    print('  posicoes REAIS utilizaveis (2 maos + lado): %d' % len(pos))
    if not pos:
        print('  nada a avaliar -- ver inventario_reconstrucao.py')
        return 0

    print()
    print('  (1) O MODELO DE OPONENTE ACERTA?')
    m = mede_modelo_oponente(pos)
    if m.get('amostras'):
        print('      das cartas sorteadas, %.1f%% estavam MESMO na mao'
              % m['acerto_pct'])
        print('      %.2f acertos por mao de %.1f cartas, em %d posicoes'
              % (m['acertos_medios'], m['cartas_por_mao'], m['amostras']))
    else:
        print('      sem amostra (modelo de oponente indisponivel)')

    print()
    print('  (2) QUANTO CUSTA A INCERTEZA?')
    u = mede_custo_da_incerteza(pos)
    if u.get('amostras'):
        print('      mesma posicao, mao aberta x as cegas:')
        print('      diferenca mediana %.4f | media %.4f | max %.4f (%d posicoes)'
              % (u['diferenca_mediana'], u['diferenca_media'], u['maxima'],
                 u['amostras']))
    else:
        print('      sem amostra (%s)' % u.get('motivo', 'reconstrucao falhou'))

    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / 'ultimo.json').write_text(
        json.dumps({'posicoes': len(pos), 'modelo_oponente': m,
                    'custo_incerteza': u}, indent=2, ensure_ascii=False),
        encoding='utf-8')
    print()
    print('  gravado em metrics/avaliacao_humana/ultimo.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
