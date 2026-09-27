"""
Paridade OFFLINE x AO VIVO -- o jogo que o ciclo simula e o mesmo que o bot
joga no OPTCGSim?

Exigencia do usuario (27/09/2026, bloco 907): *"o offline que vc roda em torno
de 200 partidas em 9 min tem que ter a mesma qualidade do cpu x cpu ao vivo"*.
Se nao tiver, o modelo treina num jogo e joga outro.

Compara as MESMAS metricas por turno de cada jogador:
  AO VIVO  : decisoes 'main' CONFIRMADAS pelo jogo nos logs do server do dia.
  OFFLINE  : as mesmas partidas (mesmos decks, de `logs/decks_full/`), mesmo
             modelo, sem exploracao -- isola "motor offline x jogo real".
  --gerador: tambem roda a configuracao EXATA do `ciclo.py` (decks de torneio,
             exploracao 0,17, adversario do pool em 25%).

A 1a medicao (bloco 907) achou o ao vivo montando as opcoes por outro caminho
(sem PASS, com piso e corte da pontuacao estatica): 1,17 x 0,83 carta/turno,
ativacao 100% x ~50% quando disponivel, 0,9 x 1,53 DON parado.

LEITURA: o ao vivo tem poucas partidas -- diferenca pequena e ruido. O que
importa e diferenca GRANDE e consistente, e a falha de execucao ao vivo (acao
que o motor acha legal e o jogo recusa), que offline e zero por construcao.

Uso:
    python mede_paridade.py --data 2026-09-26 --modelo metrics/q_net_pool/<o que jogou>.joblib
    python mede_paridade.py --n 40 --gerador
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

os.environ.setdefault('OMP_NUM_THREADS', '1')
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
SERVER_LOGS = os.path.join(RAIZ, '..', 'BOT', 'engine_server', 'logs', 'decisions')
TIPOS = ('attack', 'play', 'activate', 'attach_don')


def sessoes_do_dia(data: str) -> list[str]:
    return sorted(glob.glob(os.path.join(SERVER_LOGS, f'decisions_{data}T*.jsonl')))


def partidas_do_dia(data: str) -> list[dict]:
    idx = json.load(open(os.path.join(RAIZ, 'logs', 'index.json'), encoding='utf-8'))
    return [e for e in idx if str(e.get('id', '')).startswith(data)
            and (e.get('deck_full_files') or {}).get('You')
            and (e.get('deck_full_files') or {}).get('Opponent')]


def ao_vivo(sessoes: list[str]) -> dict:
    status = collections.defaultdict(set)
    decisoes = []
    for s in sessoes:
        for linha in open(s, encoding='utf-8'):
            d = json.loads(linha)
            if d.get('event') == 'execution':
                status[d.get('decision_id')].add(d.get('status'))
            elif d.get('event') == 'decision' and d.get('decision_kind') == 'main':
                decisoes.append(d)
    turnos = collections.defaultdict(collections.Counter)
    don_fim, falhas = {}, collections.Counter()
    for d in decisoes:
        bot = (d.get('state_before') or {}).get('bot') or {}
        # os DOIS lados gravam no mesmo match_id e `turn` e a rodada
        k = (d['match_id'], (bot.get('leader') or {}).get('code'), d['turn'])
        t = (d.get('chosen_action') or {}).get('type') or 'pass'
        st = status.get(d.get('decision_id'), set())
        turnos[k]
        if 'failed' in st:
            falhas[t] += 1
        if 'confirmed' not in st:
            continue
        turnos[k][t] += 1
        if t == 'pass':
            don_fim[k] = bot.get('activeDon')
    lados = collections.defaultdict(int)
    for (m, lid, t) in turnos:
        lados[(m, lid)] = max(lados[(m, lid)], t)
    r = resumo(list(turnos.values()), [v for v in don_fim.values() if v is not None],
               list(lados.values()), len(lados))
    r['falhas de execucao (jogo recusou)'] = dict(falhas)
    return r


def _deck(rel, cards_db):
    import sim_deck_registry
    import audit_real_losses as arl
    code, corpo = sim_deck_registry.carregar_snapshot(os.path.join(RAIZ, 'logs'), rel)
    return (arl._make_card(code, cards_db[code]),
            arl._cards_from_codes(list(corpo.elements()), cards_db), None)


def _uma(task):
    modo, i, seed, modelo, pool, partidas = task
    os.chdir(RAIZ)
    from optcg_engine.decision_engine import OPTCGMatch, load_cards_db
    random.seed(seed)
    if modo == 'mesmas':
        e = partidas[i % len(partidas)]
        db = load_cards_db('cards_rows.csv')
        da = _deck(e['deck_full_files']['You'], db)
        dbb = _deck(e['deck_full_files']['Opponent'], db)
    else:
        import gerar_selfplay_dataset as g
        dl = g._load_deck_list()
        a, b = random.Random(seed).sample(range(len(dl)), 2)
        da, dbb = dl[a][1], dl[b][1]
        random.seed(seed)
    m = OPTCGMatch(da, dbb)
    m.setup()
    m.decision_log = []        # so pra medir; nao muda decisao
    for st in (m.state_a, m.state_b):
        st.q_net_path = modelo
    if modo == 'gerador':
        m._explora_eps = 0.17
        pr = random.Random('pool-%s' % seed)
        if pool and pr.random() < 0.25:
            pr.choice([m.state_a, m.state_b]).q_net_path = pr.choice(pool)
    turnos, don_fim, n = [], [], 0
    for tn in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if tn % 2 == 0 \
            else (m.state_b if m.state_a.is_first else m.state_a)
        opp = m.state_b if p is m.state_a else m.state_a
        lab = 'A' if p is m.state_a else 'B'
        ini = len(m.decision_log)
        try:
            r = m.play_turn(p, opp)
        except Exception:
            return None
        c = collections.Counter()
        for e in m.decision_log[ini:]:
            if e.get('kind') == 'turn_planner' and e.get('player') == lab:
                c[(e.get('chosen') or {}).get('kind') or 'pass'] += 1
        turnos.append(c)
        don_fim.append(p.don_available)
        n += 1
        if r:
            break
    return turnos, don_fim, (n + 1) // 2


def offline(modo, n, workers, modelo, pool, partidas) -> dict:
    tasks = [(modo, i, 777_000 + i * 1_000_003, modelo, pool, partidas) for i in range(n)]
    with ProcessPoolExecutor(workers) as ex:
        res = [r for r in ex.map(_uma, tasks) if r]
    return resumo([t for r in res for t in r[0]], [d for r in res for d in r[1]],
                  [r[2] for r in res for _ in (0, 1)], len(res) * 2)


def resumo(turnos, don_fim, dur, n_lados) -> dict:
    tipos = collections.Counter()
    for c in turnos:
        tipos.update(c)
    nt = max(1, len(turnos))
    out = {'lados': n_lados, 'turnos': len(turnos)}
    for t in TIPOS:
        out[t + '/turno'] = round(tipos[t] / nt, 2)
    out['DON ativo sobrando no fim'] = round(statistics.mean(don_fim), 2) if don_fim else None
    out['turnos por lado/partida'] = round(statistics.mean(dur), 1) if dur else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=None, help='YYYY-MM-DD (default: sessao mais recente do server)')
    ap.add_argument('--modelo', default=os.path.join(RAIZ, 'metrics', 'q_net.joblib'),
                    help='o modelo que JOGOU as partidas ao vivo -- outro modelo mistura duas variaveis')
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--gerador', action='store_true', help='tambem mede a configuracao do ciclo.py')
    a = ap.parse_args()
    data = a.data
    if not data:
        ult = sessoes_do_dia('*')
        data = os.path.basename(ult[-1])[len('decisions_'):len('decisions_') + 10] if ult else None
    sess, partidas = sessoes_do_dia(data), partidas_do_dia(data)
    if not sess or not partidas:
        print(f'sem sessao do server ou partida banqueada em {data}')
        return 1
    r = {f'AO VIVO ({len(partidas)} partidas de {data})': ao_vivo(sess),
         'OFFLINE (mesmos decks, mesmo modelo)': offline('mesmas', a.n, a.workers, a.modelo, [], partidas)}
    if a.gerador:
        pool = sorted(glob.glob(os.path.join(RAIZ, 'metrics', 'q_net_pool', '*.joblib')))
        r['OFFLINE (gerador do ciclo)'] = offline('gerador', a.n, a.workers,
                                                  os.path.join(RAIZ, 'metrics', 'q_net.joblib'),
                                                  pool, partidas)
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
