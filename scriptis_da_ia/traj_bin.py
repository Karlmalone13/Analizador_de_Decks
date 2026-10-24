# -*- coding: utf-8 -*-
"""Estados de fim de turno do auto-jogo (`selfplay_v2.jsonl`) em BINARIO, para as
trajetorias do treino (bloco 988).

POR QUE EXISTE (AS-IS 24/10/2026, perfil de um treino inteiro): `carrega_trajetorias`
custava 99 s POR TREINO -- `json.loads` de ~830 mil linhas e `regua_x_de_selfplay`
(montar o vetor da regua estado a estado, 44 s), sempre com o MESMO resultado. So
a previsao da regua (~67 s) depende do ciclo: a regua e retreinada a cada um.

O QUE E (derivado, gitignored, regeneravel):
    metrics/traj_bin/rec.bin    registro fixo por estado (gen, match, leader, turn, ld, win)
    metrics/traj_bin/x.f64      vetor da regua (float64 -- o MESMO tipo que a regua
                                recebia; float32 mudaria a previsao) para `nomes`
    metrics/traj_bin/estado.json  ate onde do selfplay foi lido + `nomes` + lideres

So linhas com `gen` (as de gen 0 sao puladas, como em `carrega_trajetorias`).
COMO FICA EM DIA: o selfplay so CRESCE; le so os bytes novos. Arquivo reescrito
(impressao do inicio ou do trecho antes do offset mudou) ou `nomes` diferente ->
reconstroi.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
DIR = RAIZ / 'metrics' / 'traj_bin'
REC = DIR / 'rec.bin'
XF = DIR / 'x.f64'
ESTADO = DIR / 'estado.json'
_REC = np.dtype([('gen', '<i8'), ('match', '<i8'), ('leader', '<i4'), ('turn', '<i8'),
                 ('ld', '<f8'), ('win', '<i8')])
_CABECA, _ELO = 1 << 20, 1 << 12


def _hash(p: Path, ini: int, n: int) -> str:
    with open(p, 'rb') as fh:
        fh.seek(max(0, ini))
        return hashlib.sha1(fh.read(n)).hexdigest()


def _estado():
    try:
        return json.loads(ESTADO.read_text(encoding='utf-8'))
    except Exception:
        return None


def _consistente(e, origem: Path, nomes: list) -> bool:
    if not e or e.get('nomes') != list(nomes) or not REC.exists() or not XF.exists():
        return False
    off = int(e.get('offset', -1))
    if off < 0 or origem.stat().st_size < off:
        return False
    return (e.get('cabeca') == _hash(origem, 0, min(_CABECA, off))
            and e.get('elo') == _hash(origem, off - _ELO, min(_ELO, off)))


def atualiza(origem: Path, nomes: list) -> int:
    """Poe o binario em dia com o selfplay; devolve o numero de estados."""
    from optcg_engine import value_net as vn
    i_ld = list(vn.FEATURE_NAMES_V3).index('life_diff')
    DIR.mkdir(parents=True, exist_ok=True)
    e = _estado()
    if not _consistente(e, origem, nomes):
        for p in (REC, XF):
            if p.exists():
                p.unlink()
        e = {'offset': 0, 'n': 0, 'nomes': list(nomes), 'lideres': []}
    lid = {s: i for i, s in enumerate(e['lideres'])}
    off, n = int(e['offset']), int(e['n'])
    recs, xs = [], []

    def despeja():
        if recs:
            with open(REC, 'ab') as fh:
                np.asarray(recs, dtype=_REC).tofile(fh)
            with open(XF, 'ab') as fh:
                np.asarray(xs, dtype=np.float64).tofile(fh)
            recs.clear()
            xs.clear()

    with open(origem, 'rb') as fh:
        fh.seek(off)
        for ln in fh:
            if not ln.endswith(b'\n'):
                break
            off += len(ln)
            if not ln.strip():
                continue
            d = json.loads(ln)
            if not d.get('gen'):
                continue
            ld_ = d['leader']
            if ld_ not in lid:
                lid[ld_] = len(e['lideres'])
                e['lideres'].append(ld_)
            recs.append((d['gen'], d['match'], lid[ld_], d['turn'],
                         float(d['feats'][i_ld]), d['win']))
            xs.append(vn.regua_x_de_selfplay(d['feats'], nomes))
            n += 1
            if len(recs) >= 50000:
                despeja()
    despeja()
    e.update(offset=off, n=n, cabeca=_hash(origem, 0, min(_CABECA, off)),
             elo=_hash(origem, off - _ELO, min(_ELO, off)))
    ESTADO.write_text(json.dumps(e), encoding='utf-8')
    return n


def trajetorias(origem: Path, avaliador=None) -> dict:
    """O MESMO dict de `treinar_q.carrega_trajetorias`, a partir do binario:
    (gen, match, leader) -> [(turn, ld, win, valor da regua)] ordenado por turno."""
    if avaliador is not None:
        nomes = list(avaliador['feature_names'])
    else:
        nomes = list((_estado() or {}).get('nomes') or [])
    n = atualiza(origem, nomes)
    if n == 0:
        return {}
    rec = np.fromfile(REC, dtype=_REC, count=n)
    vals = [None] * n
    if avaliador is not None:
        try:
            X = np.fromfile(XF, dtype=np.float64, count=n * len(nomes)).reshape(n, len(nomes))
            m = avaliador['modelo']
            vals = list(m.predict_proba(X)[:, 1] if hasattr(m, 'predict_proba') else m.predict(X))
        except Exception:
            vals = [None] * n
    L = (_estado() or {})['lideres']
    traj: dict = {}
    g, mt, lo, tu, ld, wi = (rec['gen'].tolist(), rec['match'].tolist(), rec['leader'].tolist(),
                             rec['turn'].tolist(), rec['ld'].tolist(), rec['win'].tolist())
    for i in range(n):
        v = vals[i]
        traj.setdefault((g[i], mt[i], L[lo[i]]), []).append(
            (tu[i], ld[i], wi[i], None if v is None else float(v)))
    for t in traj.values():
        t.sort(key=lambda r: r[0])
    return traj
