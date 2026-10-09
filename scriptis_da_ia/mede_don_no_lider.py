"""Bloco 951 -- "DON no lider em vez de baixar personagem" e estrategia ou erro?

Achado nas 10 partidas CPU x CPU do bloco 950: o Mihawk (OP14-020) pos >=2 DON
no lider sem baixar personagem, tendo personagem jogavel, em 10 de 60 turnos
(Luffy & Ace: 1 de 59). Ressalva do usuario: pode ser estrategia de abrir mao
de board pra atacar forte com o lider.

Mede pelo RESULTADO, nao por regra: acha turnos em que o Q escolheu o padrao,
e a partir da MESMA foto do inicio do turno rejoga o turno N vezes explorando
(mesmo mecanismo da revisao de derrotas) e segue ate o fim. Compara a vitoria
dos ramos que repetiram o padrao contra os que baixaram personagem.
CONTROLE (que pode falhar): ramos com eps=0 -- mesma politica, so sorte.
"""
import argparse, os, random, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DECK_A, DECK_B = 'Mihawk op17', 'ace luffy'


def _padrao(antes, depois, p_depois, don_inicio):
    """(don_no_lider, baixou_personagem, tinha_jogavel)"""
    don = getattr(p_depois.leader, 'don_attached', 0)
    novos = {id(c) for c in p_depois.field_chars} - antes
    jog = any(getattr(c, 'card_type', '').upper() == 'CHARACTER' and c.cost <= don_inicio
              for c in depois)
    return don, bool(novos), jog


def _turno(m, t, lado_alvo):
    from gerar_selfplay_dataset import _quem_joga
    p, opp = _quem_joga(m, t)
    lado = 'A' if p is m.state_a else 'B'
    antes = {id(c) for c in p.field_chars}
    mao = list(p.hand)
    m.play_turn(p, opp)
    don_ini = len(getattr(p, 'don_active', []) or []) if False else 99
    return lado, p, antes, mao


def _ate_fim(m, t0):
    from gerar_selfplay_dataset import _quem_joga
    for t in range(t0, m.MAX_TURNS * 2):
        p, opp = _quem_joga(m, t)
        r = m.play_turn(p, opp)
        if m.state_a.life_lost() if False else False:
            pass
        w = getattr(m, 'winner', None)
        if r and isinstance(r, str) and r in ('A', 'B'):
            return r
        if w in ('A', 'B'):
            return w
        for lado, st in (('A', m.state_a), ('B', m.state_b)):
            if getattr(st, 'lost', False):
                return 'B' if lado == 'A' else 'A'
    return None


def _ramo(args):
    foto, t, eps, seed = args
    from copy import deepcopy
    from gerar_selfplay_dataset import _quem_joga
    random.seed(seed)
    m = deepcopy(foto)
    m._explora_eps = eps
    p, opp = _quem_joga(m, t)
    lado = 'A' if p is m.state_a else 'B'
    antes = {id(c) for c in p.field_chars}
    try:
        m.play_turn(p, opp)
        don = getattr(p.leader, 'don_attached', 0)
        baixou = bool({id(c) for c in p.field_chars} - antes)
        m._explora_eps = 0.0
        w = _ate_fim(m, t + 1)
    except Exception:
        return None
    return don >= 2 and not baixou, baixou, (w == lado) if w else None


def _acha(seed):
    from copy import deepcopy
    from optcg_engine import sim_bridge as sb
    from optcg_engine.decision_engine import OPTCGMatch
    from gerar_selfplay_dataset import _quem_joga, _foto
    random.seed(seed)
    m = OPTCGMatch(sb.load_sim_deck(DECK_A), sb.load_sim_deck(DECK_B))
    m.setup()
    achados = []
    for t in range(0, m.MAX_TURNS * 2):
        p, opp = _quem_joga(m, t)
        foto = _foto(m)
        eh_mihawk = p.leader.code == 'OP14-020'
        antes = {id(c) for c in p.field_chars}
        don_ini = sum(1 for d in getattr(p, 'don_area', []) or []) if False else None
        try:
            r = m.play_turn(p, opp)
        except Exception:
            break
        if eh_mihawk:
            don = getattr(p.leader, 'don_attached', 0)
            baixou = bool({id(c) for c in p.field_chars} - antes)
            if don >= 2 and not baixou:
                achados.append((foto, t))
        if getattr(m, 'winner', None) or r in ('A', 'B'):
            break
    return achados


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=12)
    ap.add_argument('--ramos', type=int, default=16)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--seed', type=int, default=951)
    a = ap.parse_args()
    with ProcessPoolExecutor(a.workers) as ex:
        pos = [x for r in ex.map(_acha, [a.seed * 1_000_003 + i for i in range(a.partidas)]) for x in r]
        print(f'posicoes com o padrao: {len(pos)}', flush=True)
        tarefas = []
        for k, (foto, t) in enumerate(pos):
            for j in range(a.ramos):
                eps = 0.0 if j < a.ramos // 4 else 0.6
                tarefas.append((foto, t, eps, a.seed * 7919 + k * 1000 + j))
        res = list(ex.map(_ramo, tarefas))
    from collections import defaultdict
    g = defaultdict(lambda: [0, 0])
    for (foto, t, eps, s), r in zip(tarefas, res):
        if not r or r[2] is None:
            continue
        padrao, baixou, venceu = r
        chave = ('controle eps=0' if eps == 0 else 'explorando') + ' | ' + (
            'DON no lider, sem personagem' if padrao else 'baixou personagem' if baixou else 'outro')
        g[chave][0] += venceu; g[chave][1] += 1
    for k in sorted(g):
        v, n = g[k]
        print(f'{k:55s} {v:4d}/{n:<4d} = {100*v/max(n,1):5.1f}%')
