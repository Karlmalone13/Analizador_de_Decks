"""O BURACO ESTRUTURAL: "o que nao vira candidato nao existe". Bloco 780.

Pedido explicito do usuario (12/09/2026): *"O modelo escolhe entre o que as
regras produzem -- o que nao vira candidato nao existe. Vamos resolver isso
tb"*.

Antes de resolver, MEDIR o tamanho -- a mesma disciplina que o bloco 779 usou.
Este script separa DOIS modos de falha bem diferentes:

  A. o turno PARA com acoes legais ainda na mesa, porque a melhor pontuou
     abaixo de `ACTION_SCORE_FLOOR` (=0,0). A jogada EXISTE, e legal, foi
     gerada e pontuada -- e mesmo assim nunca acontece. Combo cujo primeiro
     passo parece ruim isolado morre exatamente aqui.

  B. o turno para porque nao havia acao nenhuma. Ai nao ha buraco: as regras
     realmente nao ofereciam nada.

So o modo A e problema, e so ele e corrigivel sem mexer nas regras.

Mede tambem o TAMANHO da lista de candidatas por decisao (quantas opcoes o
modelo chega a ver) e a fatia de cada tipo de acao.
"""
from __future__ import annotations
import argparse
import collections
import random

from optcg_engine import decision_engine as de


def uma(seed, acc):
    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    try:
        m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
        m.setup()
    except Exception:
        return

    piso = de._k.get('ACTION_SCORE_FLOOR')
    orig = de.OPTCGMatch._generate_and_score_actions
    ultimo = {'acts': None}

    def espiao(self, p, opp, engine, exclude_activate_uids=None):
        acts = orig(self, p, opp, engine, exclude_activate_uids)
        if not getattr(self, '_suppress_replay_log', False):
            ultimo['acts'] = acts
            acc['n_decisoes'] += 1
            acc['tam_lista'].append(len(acts))
            for a in acts:
                acc['tipo'][a[1]] += 1
            # FASE 3 (bloco 783): quantas quantidades de DON DISTINTAS o
            # avaliador recebe por (atacante, alvo). Antes era sempre 1 --
            # o DON nascia depois da escolha, entao "atacar com 2" e
            # "atacar com 4" nunca coexistiam como opcoes.
            import collections as _c
            por_atk = _c.defaultdict(set)
            for a in acts:
                if a[1] == 'attack':
                    por_atk[(id(a[2]), a[3], id(a[4]))].add(
                        a[5] if len(a) > 5 else None)
            for v in por_atk.values():
                acc.setdefault('don_por_ataque', []).append(len(v))
        return acts

    de.OPTCGMatch._generate_and_score_actions = espiao
    try:
        for t in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            ultimo['acts'] = None
            r = m.play_turn(p, opp)
            acts = ultimo['acts']
            if acts is not None:
                acc['turnos'] += 1
                if not acts:
                    acc['parou_vazio'] += 1
                elif acts[0][0] < piso:
                    # MODO A: havia acao legal, pontuou abaixo do piso
                    acc['parou_com_acao'] += 1
                    acc['sobraram'].append(len(acts))
                    acc['melhor_score'].append(acts[0][0])
                    acc['tipo_perdido'][acts[0][1]] += 1
                else:
                    acc['parou_por_limite'] += 1
            if r:
                break
    except Exception:
        pass
    finally:
        de.OPTCGMatch._generate_and_score_actions = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8)
    ap.add_argument('--seed', type=int, default=3131)
    a = ap.parse_args()

    acc = {'n_decisoes': 0, 'turnos': 0, 'parou_vazio': 0,
           'parou_com_acao': 0, 'parou_por_limite': 0,
           'tam_lista': [], 'sobraram': [], 'melhor_score': [],
           'tipo': collections.Counter(), 'tipo_perdido': collections.Counter()}
    for i in range(a.n):
        uma(a.seed * 1_000_003 + i, acc)

    tl = acc['tam_lista']
    print('')
    print('GERACAO DE CANDIDATAS -- o que o modelo chega a VER')
    print('  decisoes observadas       : {}'.format(acc['n_decisoes']))
    if tl:
        print('  candidatas por decisao    : media {:.1f} | min {} | max {}'.format(
            sum(tl) / len(tl), min(tl), max(tl)))
        print('  decisoes com <= 2 opcoes  : {:.1%}'.format(
            sum(1 for x in tl if x <= 2) / len(tl)))
    tot = sum(acc['tipo'].values()) or 1
    print('  por tipo de acao          : {}'.format(', '.join(
        '{} {:.0%}'.format(k, v / tot) for k, v in acc['tipo'].most_common())))

    dpa = acc.get('don_por_ataque') or []
    if dpa:
        print('')
        print('  LARGURA EM DON (Fase 3): quantidades distintas por (atacante, alvo)')
        print('    media {:.2f} | max {} | com 1 so valor: {:.1%}'.format(
            sum(dpa) / len(dpa), max(dpa),
            sum(1 for x in dpa if x == 1) / len(dpa)))
    print('')
    print('COMO O TURNO TERMINA  ({} turnos)'.format(acc['turnos']))
    t = acc['turnos'] or 1
    print('  sem nenhuma acao legal            : {} ({:.1%})'.format(
        acc['parou_vazio'], acc['parou_vazio'] / t))
    print('  >> COM acao legal, score < piso   : {} ({:.1%})  <-- O BURACO'.format(
        acc['parou_com_acao'], acc['parou_com_acao'] / t))
    print('  bateu o limite de acoes/turno     : {} ({:.1%})'.format(
        acc['parou_por_limite'], acc['parou_por_limite'] / t))
    if acc['sobraram']:
        s, ms = acc['sobraram'], acc['melhor_score']
        print('')
        print('  nos turnos do buraco:')
        print('    acoes legais deixadas na mesa : media {:.1f} | max {}'.format(
            sum(s) / len(s), max(s)))
        print('    score da melhor delas          : media {:.1f} | melhor {:.1f}'.format(
            sum(ms) / len(ms), max(ms)))
        print('    que TIPO ficou de fora         : {}'.format(', '.join(
            '{} {}x'.format(k, v) for k, v in acc['tipo_perdido'].most_common())))
    print('')
    print('LEITURA: a linha marcada e o modo de falha CORRIGIVEL -- a jogada')
    print('era legal, foi gerada e pontuada, e mesmo assim nunca acontece.')
    print('E onde morre o combo cujo primeiro passo parece ruim isolado.')


if __name__ == '__main__':
    main()
