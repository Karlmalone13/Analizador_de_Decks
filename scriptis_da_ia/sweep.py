"""Varredor de knobs: mede N configuracoes e compara, com recorte POR LIDER.

Pedido do usuario (27/08/2026): *"Precisamos criar um sistema controlavel
e observavel nao so observavel"*. Antes disto, testar um valor diferente
significava editar `decision_engine.py`, rodar a regua (~1h30), anotar o
numero a mao e lembrar de reverter. Nao havia como varrer, nem como provar
depois qual codigo gerou qual numero.

Uso:
    python sweep.py --knob SEARCH_MIN_PLAY_CANDIDATES=1,2,3 --limit 60
    python sweep.py --config base.json exp_a.json exp_b.json --limit 60
    python sweep.py --knob PLANNER_MC_SAMPLES=6,10 --workers 4 --limit 40

Cada configuracao roda `decision_quality_full.py` num SUBPROCESSO com o
knob setado por ambiente (`OPTCG_K_<NOME>`), porque os knobs sao lidos no
import do motor -- rodar em processo reaproveitaria o valor ja cacheado e
mediria a mesma coisa duas vezes (esse tipo de falha silenciosa ja
aconteceu no bloco 682).

**O recorte por lider e OBRIGATORIO, nao opcional** (regra do projeto): um
knob que sobe o agregado mexendo em 2 lideres NAO generalizou, e o
objetivo e jogar bem com QUALQUER deck. O relatorio marca quantos lideres
melhoraram/pioraram, nao so a media.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, 'metrics', 'sweeps')


def _le_resultado(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _metricas(d, min_turnos=8):
    """(agregado, por_lider) -- mesma regua do decision_quality_full."""
    r = [x for x in d['offense'] if x.get('play_has_data')]
    agg = {'play': sum(1 for x in r if x['play_match']) / len(r) if r else 0.0,
           'n_turnos': len(r)}
    for campo, gate in (('activate_match', 'activate_has_data'),
                        ('attack_quem_match', 'attack_has_data'),
                        ('don_alvo_match', 'don_has_data'),
                        ('seq_exact_match', 'seq_has_data')):
        sub = [x for x in d['offense'] if x.get(gate)]
        agg[campo.replace('_match', '')] = (
            sum(1 for x in sub if x[campo]) / len(sub) if sub else 0.0)
    por = defaultdict(lambda: [0, 0])
    for x in r:
        p = por[x.get('leader') or '?']
        p[1] += 1
        p[0] += 1 if x['play_match'] else 0
    return agg, {k: (a / b, b) for k, (a, b) in por.items() if b >= min_turnos}


def roda(env_extra: dict, limit, workers, tag):
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_extra.items()})
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    cmd = [sys.executable, 'decision_quality_full.py', '--all']
    if limit:
        cmd += ['--limit', str(limit)]
    if workers:
        cmd += ['--workers', str(workers)]
    print(f'\n=== {tag} ===\n    {env_extra or "(default)"}', flush=True)
    p = subprocess.run(cmd, cwd=AQUI, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-2000:]); print(p.stderr[-2000:])
        raise SystemExit(f'{tag} falhou (rc={p.returncode})')
    nome = (f'parcial_limit{limit}.json' if limit else 'ultimo_resultado.json')
    return _le_resultado(os.path.join(AQUI, 'metrics',
                                      'decision_quality_full', nome))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--knob', action='append', default=[],
                    help='NOME=v1,v2,v3 (repetivel; combina em produto)')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--workers', type=int, default=None)
    ap.add_argument('--min-turnos', type=int, default=8)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    nomes, listas = [], []
    for spec in a.knob:
        nome, _, vals = spec.partition('=')
        nomes.append(nome.strip())
        listas.append([v.strip() for v in vals.split(',') if v.strip()])
    combos = [dict(zip(nomes, c)) for c in itertools.product(*listas)] or [{}]
    if not any(c == {} for c in combos):
        combos.insert(0, {})  # baseline sempre presente

    resultados = []
    for c in combos:
        tag = ' '.join(f'{k}={v}' for k, v in c.items()) or 'BASELINE'
        d = roda({f'OPTCG_K_{k}': v for k, v in c.items()},
                 a.limit, a.workers, tag)
        agg, por = _metricas(d, a.min_turnos)
        resultados.append({'tag': tag, 'knobs': c, 'agg': agg, 'por_lider': por,
                           'config_gravada': d.get('config')})

    base = resultados[0]
    print('\n' + '=' * 78)
    print(f'{"config":<34}{"play":>8}{"delta":>8}{"activate":>10}{"don":>8}{"seq":>8}')
    print('=' * 78)
    for r in resultados:
        g, bg = r['agg'], base['agg']
        d = (g['play'] - bg['play']) * 100
        dtxt = '--' if r is base else f'{d:+.1f}pp'
        print(f'{r["tag"][:33]:<34}{g["play"]*100:7.1f}%{dtxt:>8}'
              f'{g["activate"]*100:9.1f}%{g["don_alvo"]*100:7.1f}%'
              f'{g["seq_exact"]*100:7.1f}%')

    print(f'\n--- RECORTE POR LIDER (>={a.min_turnos} turnos) — obrigatorio ---')
    print('Um knob que sobe o agregado mexendo em poucos lideres NAO generalizou.')
    for r in resultados[1:]:
        subiu = caiu = igual = 0
        piores = []
        for lid, (taxa, n) in r['por_lider'].items():
            b = base['por_lider'].get(lid)
            if not b:
                continue
            d = (taxa - b[0]) * 100
            if d > 0.5:
                subiu += 1
            elif d < -0.5:
                caiu += 1
                piores.append((d, lid, n))
            else:
                igual += 1
        piores.sort()
        print(f'\n  {r["tag"][:60]}')
        print(f'    lideres: {subiu} melhoraram / {caiu} pioraram / {igual} iguais')
        if piores:
            print('    piores: ' + ', '.join(
                f'{l} {d:+.1f}pp (n={n})' for d, l, n in piores[:5]))

    os.makedirs(SAIDA, exist_ok=True)
    out = a.out or os.path.join(SAIDA, 'ultimo_sweep.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(resultados, fh, ensure_ascii=False, indent=1)
    print(f'\ngravado em {out}')


if __name__ == '__main__':
    main()
