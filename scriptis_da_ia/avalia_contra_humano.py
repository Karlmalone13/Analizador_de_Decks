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


def mede_modelo_oponente(posicoes, rodadas=8, seed=4242) -> dict:
    """Das cartas que o modelo SORTEIA pra mao do adversario, quantas ele
    de fato tinha?

    `opponent_model.sample(opp, rng)` recebe o ESTADO do oponente (nao uma
    contagem) e devolve `(mao_sorteada, vida_sorteada)`. **Conferido no
    codigo antes de acreditar no numero**: de `opp.hand` ele le apenas o
    TAMANHO (`len(opp.hand) - len(known_hand_cards())`), e
    `known_hand_cards()` filtra por `revealed_to_opponent`, que aqui nasce
    vazio. As cartas da mao tambem NAO saem da populacao de sorteio --
    `_known_population_excluded` exclui trash, board, stage e mao
    REVELADA, nao a mao. Ou seja: entregar a mao real nao vaza nada, e o
    que o modelo enxerga e so o observavel (trash, board, vida, tamanho da
    mao).

    Acerto e contado como MULTICONJUNTO (`Counter &`): um deck e cheio de
    4-ofs, e `set` diria "acertou Nami" uma vez quando o adversario tinha
    tres.

    ## Os dois controles (regra do projeto: toda medicao precisa de um que
    POSSA falhar)

      * **sem observar** -- o MESMO modelo com trash/board/vida vazios.
        Isola o que a OBSERVACAO agrega sobre so conhecer a decklist. Se
        empatar com o numero principal, condicionar no observavel nao esta
        fazendo nada.
      * **lider errado** -- o modelo de OUTRO lider do corpus. **Tem que
        despencar.** Se nao despencar, o instrumento esta medindo
        coincidencia entre cartas comuns, nao leitura de oponente.
    """
    import random as _r
    from collections import Counter
    from optcg_engine.sim_bridge import (opponent_model_for_leader,
                                         opponent_model_source_for_leader)
    from optcg_engine.decision_engine import GameState, _make_card, load_cards_db

    db = load_cards_db(str(RAIZ / 'cards_rows.csv'))
    rng = _r.Random(seed)

    def carta(cod):
        d = db.get(str(cod))
        return _make_card(str(cod), d) if d else None

    def cartas(lista):
        return [c for c in (carta(x) for x in (lista or [])) if c]

    def estado(sn, lider_code, observavel=True):
        lider = carta(lider_code)
        if lider is None:
            return None
        st = GameState(leader=lider)
        st.hand = cartas(sn.get('hand'))          # so o TAMANHO e lido
        if observavel:
            st.field_chars = cartas(sn.get('board'))
            st.trash = cartas(sn.get('trash'))
            st.life = cartas(sn.get('life_cards'))
        return st

    def acerto(mao_sorteada, real_cnt):
        cods = Counter(getattr(c, 'code', str(c)) for c in (mao_sorteada or []))
        return sum((cods & real_cnt).values())

    # lideres presentes no corpus, pro controle de lider ERRADO
    lideres = []
    for r, _t in posicoes:
        od = r.get('p2' if r['bot_side'] == 'p1' else 'p1') or {}
        lc = od.get('leader_code')
        if lc and lc not in lideres:
            lideres.append(lc)

    tot = {'modelo': 0.0, 'cego': 0.0, 'errado': 0.0}
    cartas_totais, amostras = 0, 0
    por_camada = {}
    for r, t in posicoes:
        lado_opp = 'Opponent' if r['bot_side'] == 'p1' else 'You'
        sn = (t.get('snapshot') or {}).get(lado_opp) or {}
        mao_real = [str(x) for x in (sn.get('hand') or [])]
        if len(mao_real) < 2:
            continue
        od = r.get('p2' if r['bot_side'] == 'p1' else 'p1') or {}
        lc = od.get('leader_code') or ''
        modelo = opponent_model_for_leader(lc, '')
        if modelo is None:
            continue
        est = estado(sn, lc, observavel=True)
        cego = estado(sn, lc, observavel=False)
        if est is None or cego is None:
            continue
        outro = next((x for x in lideres if x != lc), None)
        m_errado = opponent_model_for_leader(outro, '') if outro else None

        real_cnt = Counter(mao_real)
        parcial = {'modelo': 0, 'cego': 0, 'errado': 0}
        n_ok = 0
        for _ in range(rodadas):
            try:
                mao, _v = modelo.sample(est, rng=rng)
                parcial['modelo'] += acerto(mao, real_cnt)
                mao_c, _v = modelo.sample(cego, rng=rng)
                parcial['cego'] += acerto(mao_c, real_cnt)
                if m_errado is not None:
                    mao_e, _v = m_errado.sample(est, rng=rng)
                    parcial['errado'] += acerto(mao_e, real_cnt)
                n_ok += 1
            except Exception:
                break
        if not n_ok:
            continue
        for k in tot:
            tot[k] += parcial[k] / float(n_ok)
        cartas_totais += len(mao_real)
        amostras += 1
        cam = opponent_model_source_for_leader(lc, '')
        d = por_camada.setdefault(cam, {'acertos': 0.0, 'cartas': 0, 'n': 0})
        d['acertos'] += parcial['modelo'] / float(n_ok)
        d['cartas'] += len(mao_real)
        d['n'] += 1

    if not amostras:
        return {'amostras': 0}

    def pct(x):
        return round(100.0 * x / max(1, cartas_totais), 1)

    return {'amostras': amostras,
            'rodadas_por_posicao': rodadas,
            'cartas_por_mao': round(cartas_totais / float(amostras), 1),
            'acerto_pct': pct(tot['modelo']),
            'acerto_pct_sem_observar': pct(tot['cego']),
            'acerto_pct_lider_errado': pct(tot['errado']),
            'acertos_medios': round(tot['modelo'] / amostras, 2),
            'por_camada': {k: {'acerto_pct': round(100.0 * v['acertos'] / max(1, v['cartas']), 1),
                               'posicoes': v['n']}
                           for k, v in sorted(por_camada.items())}}


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
        print('      %.2f acertos por mao de %.1f cartas, em %d posicoes (%dx cada)'
              % (m['acertos_medios'], m['cartas_por_mao'], m['amostras'],
                 m['rodadas_por_posicao']))
        print()
        print('      CONTROLES (sozinho, o numero acima nao diria nada):')
        print('        sem observar trash/board/vida : %.1f%%'
              % m['acerto_pct_sem_observar'])
        print('        modelo do LIDER ERRADO        : %.1f%%  <- tem que despencar'
              % m['acerto_pct_lider_errado'])
        if m.get('por_camada'):
            print()
            print('      por camada de fallback:')
            for cam, d in m['por_camada'].items():
                print('        %-28s %5.1f%%  (%d posicoes)'
                      % (cam, d['acerto_pct'], d['posicoes']))
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
