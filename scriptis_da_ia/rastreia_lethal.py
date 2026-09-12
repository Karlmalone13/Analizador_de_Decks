"""Pega turnos em que o lethal foi CERTIFICADO e a partida NAO acabou, e
mostra o que de fato aconteceu, ataque por ataque. Bloco 779.

Medido no bloco 778: em **65,2% dos turnos** em que `can_lethal_this_turn()`
diz TRUE no estado REAL, no inicio do turno, o jogo nao termina. Tres causas
possiveis, com gravidades bem diferentes:

  1. o bot NAO EXECUTA a linha vencedora (a busca escolhe outra coisa)
  2. trigger/defesa quebra o lethal (o bug que o usuario apontou)
  3. a certificacao esta ERRADA (otimista demais)

A v1 deste script mostrou que em 3 de 6 casos o dano do turno foi ZERO, com
4-6 atacantes no board -- o que ja descarta "trigger" como causa unica. Esta
versao liga `enable_decision_audit()` e le os registros `attack_outcome`
(bloco 742), que trazem blocker, counter somado e dano de CADA ataque real.
Assim as tres causas ficam separadas por evidencia, nao por suposicao:

  - nenhum `attack_outcome` no turno  -> o bot NAO ATACOU (causa 1)
  - atacou e `blocked_by`/`counter_add` seguraram -> defesa (causa 2/3)
"""
from __future__ import annotations
import argparse
import random

from optcg_engine import decision_engine as de


def _desc(c):
    return '{} {}pwr{}{}'.format(
        getattr(c, 'name', '?')[:16], getattr(c, 'power', 0),
        '/rest' if getattr(c, 'rested', False) else '',
        '/DONx{}'.format(c.don_attached) if getattr(c, 'don_attached', 0) else '')


def uma(seed, achados, limite):
    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    try:
        m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
        m.enable_decision_audit()
        m.setup()
    except Exception:
        return

    est = {'cert': None}
    orig = de.GameAnalyzer.can_lethal_this_turn

    def espiao(self):
        r = orig(self)
        if not getattr(m, '_suppress_replay_log', False) and est['cert'] is None:
            if r:
                ok, alloc = self.can_lethal_this_turn_alloc()
                est['cert'] = {
                    'vida_opp': self.opp.life_count(),
                    'chars': [_desc(c) for c in self.me.field_chars],
                    'lider': _desc(self.me.leader),
                    'don': self.me.don_available,
                    'blk': len(self.opp.blockers_active()),
                    'mao_opp': len(self.opp.hand),
                    'alloc': [
                        ('lider' if a is self.me.leader else getattr(a, 'name', '?')[:12], d)
                        for a, d in (alloc or [])],
                }
            else:
                est['cert'] = False
        return r

    de.GameAnalyzer.can_lethal_this_turn = espiao
    try:
        for t in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            est['cert'] = None
            marca = len(m.decision_log)
            r = m.play_turn(p, opp)
            if est['cert'] and not r and len(achados) < limite:
                c = est['cert']
                lado = 'A' if p is m.state_a else 'B'
                c['seed'], c['turno'] = seed, t
                c['ataques'] = [d for d in m.decision_log[marca:]
                                if d.get('kind') == 'attack_outcome'
                                and d.get('player') == lado]
                c['acoes'] = [d.get('kind') for d in m.decision_log[marca:]]
                achados.append(c)
            if r:
                break
    except Exception:
        pass
    finally:
        de.GameAnalyzer.can_lethal_this_turn = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--casos', type=int, default=6)
    ap.add_argument('--seed', type=int, default=9090)
    a = ap.parse_args()

    achados = []
    for i in range(a.n):
        if len(achados) >= a.casos:
            break
        uma(a.seed * 1_000_003 + i, achados, a.casos)

    sem_ataque = 0
    print('')
    print('CASOS: lethal CERTIFICADO e a partida NAO acabou  ({})'.format(len(achados)))
    print('=' * 74)
    for k, c in enumerate(achados, 1):
        atks = c['ataques']
        if not atks:
            sem_ataque += 1
        print('')
        print('CASO {}  (seed {}, turno {})   vida do oponente: {}'.format(
            k, c['seed'], c['turno'], c['vida_opp']))
        print('  board: {} | {}'.format(c['lider'], ', '.join(c['chars']) or '-'))
        print('  DON {} | blockers do opp {} | mao do opp {}'.format(
            c['don'], c['blk'], c['mao_opp']))
        print('  CERTIFICOU: {}'.format(
            ', '.join('{}+{}'.format(n, d) for n, d in c['alloc']) or '(vazia)'))
        if not atks:
            print('  >>> NENHUM ATAQUE EXECUTADO NO TURNO <<<')
            print('      acoes do turno: {}'.format(
                ', '.join(sorted(set(c['acoes']))) or '(nada)'))
        else:
            print('  EXECUTOU {} ataque(s):'.format(len(atks)))
            for d in atks:
                print('    {} -> {} | DON {} | blocker {} | counter +{} | vidas {}'.format(
                    d.get('attacker'), d.get('target_type'), d.get('attached_don'),
                    d.get('blocked_by') or '-', d.get('counter_add'),
                    d.get('vidas_tiradas')))
    print('')
    print('RESUMO: {} de {} casos SEM NENHUM ATAQUE no turno.'.format(
        sem_ataque, len(achados)))


if __name__ == '__main__':
    main()
