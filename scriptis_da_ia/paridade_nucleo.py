#!/usr/bin/env python
"""TESTE DIFERENCIAL do nucleo Rust (`optcg_core`) contra o motor Python
(PLANO_MOTOR_FORTE.md fase A; `optcg_core/ESPEC.md` secao 5).

Joga partidas no motor Python com o DIARIO ligado e confere, no nucleo Rust:
  1. IDA E VOLTA: o Rust le e reescreve cada estado canonico sem perder nada;
  2. INICIO DE TURNO: de `turno_inicio` o Rust aplica contadores/refresh/compra/DON
     e tem que dar o `main_inicio` do Python, campo a campo.
Turnos com efeito de inicio de turno que o nucleo ainda nao tem (reativos
`opp_turn`, trava de refresh do Stage) sao PULADOS e contados -- onda de efeitos.

    python paridade_nucleo.py --partidas 20 --seed 1000
"""
import argparse
import json
import os
import random
import sys

os.environ.setdefault('PYTHONHASHSEED', '0')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import optcg_core  # noqa: E402
from optcg_engine import decision_engine as de, estado_canonico as ec  # noqa: E402
from gerar_selfplay_dataset import _load_deck_list  # noqa: E402

_REATIVAS = de.OPTCGMatch._OPP_TURN_REACTIVE_ACTIONS


def _tem_efeito_de_inicio(estado: dict) -> bool:
    """O inicio deste turno dispara efeito que o nucleo ainda nao modela?"""
    op = estado['oponente']
    for c in [op['leader'], op['stage']] + op['field_chars']:
        if c and any(s.get('action') in _REATIVAS for s in
                     de.get_card_effects(c['code']).get('opp_turn', {}).get('steps', [])):
            return True
    for lado in ('ativo', 'oponente'):
        st = estado[lado]['stage']
        if st and any(s.get('action') == 'lock_both_character_refresh' for s in
                      de.get_card_effects(st['code']).get('passive', {}).get('steps', [])):
            return True
    return False


def _primeira_diferenca(a, b, cam=''):
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return cam, a, b
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f'{cam}/{k}', k in a, k in b
            r = _primeira_diferenca(a[k], b[k], f'{cam}/{k}')
            if r:
                return r
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f'{cam} (tamanho)', len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            r = _primeira_diferenca(x, y, f'{cam}[{i}]')
            if r:
                return r
        return None
    return None if a == b else (cam, a, b)


def diario_de(seed: int) -> list:
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    ec.DIARIO.update(on=True, eventos=[])
    try:
        m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
        m.setup()
        for n in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if n % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            o = m.state_b if p is m.state_a else m.state_a
            if m.play_turn(p, o):
                break
    finally:
        ev = list(ec.DIARIO['eventos'])
        ec.DIARIO.update(on=False, eventos=[])
    return ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=10)
    ap.add_argument('--seed', type=int, default=1000)
    a = ap.parse_args()
    tot = {'ida_volta': [0, 0], 'inicio_turno': [0, 0], 'pulados': 0}
    divs = []
    for i in range(a.partidas):
        ev = diario_de(a.seed + i)
        for e in ev:
            for k in ('estado', 'antes', 'depois'):
                if k in e:
                    s = json.dumps(e[k])
                    volta = json.loads(optcg_core.ida_e_volta(s))
                    tot['ida_volta'][1] += 1
                    if _primeira_diferenca(e[k], volta) is None:
                        tot['ida_volta'][0] += 1
                    elif len(divs) < 5:
                        divs.append(('ida_volta', a.seed + i, _primeira_diferenca(e[k], volta)))
        for j, e in enumerate(ev):
            if e['tipo'] != 'turno_inicio':
                continue
            alvo = next((x for x in ev[j + 1:] if x['tipo'] == 'main_inicio'), None)
            if alvo is None:
                continue
            if _tem_efeito_de_inicio(e['estado']):
                tot['pulados'] += 1
                continue
            r = json.loads(optcg_core.inicio_de_turno(json.dumps(e['estado']), e['global_turn']))
            tot['inicio_turno'][1] += 1
            d = _primeira_diferenca(alvo['estado'], r)
            if d is None:
                tot['inicio_turno'][0] += 1
            elif len(divs) < 12:
                divs.append(('inicio_turno', a.seed + i, d))
    for k in ('ida_volta', 'inicio_turno'):
        ok, n = tot[k]
        print(f'{k:14s} {ok}/{n} identicos ({100 * ok / max(n, 1):.1f}%)')
    print(f'turnos pulados (efeito de inicio de turno ainda fora do nucleo): {tot["pulados"]}')
    for d in divs:
        print('DIVERGE', d[0], 'seed', d[1], 'campo', d[2][0], '| python', repr(d[2][1])[:60],
              '| rust', repr(d[2][2])[:60])
    return 0 if all(tot[k][0] == tot[k][1] for k in ('ida_volta', 'inicio_turno')) else 1


if __name__ == '__main__':
    sys.exit(main())
