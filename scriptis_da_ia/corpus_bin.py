# -*- coding: utf-8 -*-
"""As jogadas ESCOLHIDAS em formato BINARIO, para o treino (bloco 968).

POR QUE EXISTE (AS-IS 21/10/2026): o treino le `q_escolhidas.jsonl` (4,6 GB de
TEXTO) e decodifica 158 numeros por linha com `json.loads` -- 2,5 milhoes de
linhas. Cada numero vira texto ("0.6666666666666666", ~18 bytes) e depois objeto
do Python. Decisao do usuario: guardar so as escolhidas, em binario.

O QUE E (derivado, gitignored, regeneravel -- igual ao indice das escolhidas):
    metrics/q_bin/feats.f32    float32 cru, uma linha por jogada, largura fixa W
    metrics/q_bin/meta.jsonl   a MESMA linha do indice SEM `feats` (o resto)
    metrics/q_bin/estado.json  ate onde do indice ja foi convertido
A linha i do meta corresponde a linha i do feats. W = largura atual do vetor do
Q; linha antiga mais estreita entra completada com 0 pela MESMA regra do treino
(colunas novas sempre no FIM). Linha que nem completando cabe vira `_largura`
no meta e o leitor a devolve com `feats` = None (o treino ja a descartava).

COMO FICA EM DIA: o indice so CRESCE. `atualiza()` converte so o trecho novo.
Indice reescrito (impressao do inicio ou do trecho antes do offset mudou, ou
ficou menor) ou W mudou (coluna nova) -> reconstroi do zero.

Uso:
    python corpus_bin.py               # atualiza e mostra o estado
    python corpus_bin.py --reconstroi
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

import corpus_escolhidas as ce

RAIZ = Path(__file__).resolve().parent
DIR = RAIZ / 'metrics' / 'q_bin'
FEATS = DIR / 'feats.f32'
META_L = DIR / 'meta.jsonl'
ESTADO = DIR / 'estado.json'
_JANELA_COMPLETA = 60      # treinar_q: completa linha com ate 60 colunas a menos


def largura() -> int:
    from optcg_engine import value_net as vn
    return (len(vn.FEATURE_NAMES_ALUNO) + len(vn.FEATURE_NAMES_ACAO)
            + len(vn.FEATURE_NAMES_CORRIDA) + len(vn.FEATURE_NAMES_PENSAR))


def _estado():
    try:
        return json.loads(ESTADO.read_text(encoding='utf-8'))
    except Exception:
        return None


def _consistente(e, W) -> bool:
    if not e or e.get('W') != W or not FEATS.exists() or not META_L.exists():
        return False
    ind = ce.INDICE
    off = int(e.get('offset', -1))
    if off < 0 or not ind.exists() or ind.stat().st_size < off:
        return False
    if FEATS.stat().st_size != int(e['linhas']) * W * 4:
        return False
    return (e.get('cabeca') == ce._hash(ind, 0, ce._CABECA)
            and e.get('elo') == ce._hash(ind, off - ce._ELO, min(ce._ELO, off)))


def atualiza(reconstroi: bool = False) -> int:
    """Poe o binario em dia com o indice das escolhidas. Devolve o no de linhas."""
    ind = ce.atualiza()
    W = largura()
    e = _estado()
    if reconstroi or not _consistente(e, W):
        DIR.mkdir(parents=True, exist_ok=True)
        for f in (FEATS, META_L):
            if f.exists():
                f.unlink()
        e = {'offset': 0, 'linhas': 0}
        recomecou = True
    else:
        recomecou = False
    off, n = int(e['offset']), int(e['linhas'])
    novas = 0
    buf = []
    with open(ind, 'rb') as fi, open(FEATS, 'ab') as ff, open(META_L, 'ab') as fm:
        fi.seek(off)
        for ln in fi:
            if not ln.endswith(b'\n'):
                break
            off += len(ln)
            if not ln.strip():
                continue
            d = json.loads(ln)
            f = d.pop('feats', None) or []
            if len(f) != W and W - _JANELA_COMPLETA <= len(f) < W:
                f = list(f) + [0.0] * (W - len(f))
            if len(f) != W:
                d['_largura'] = len(f)
                f = [0.0] * W
            buf.append(f)
            fm.write(json.dumps(d, ensure_ascii=False).encode('utf-8') + b'\n')
            n += 1
            novas += 1
            if len(buf) >= 65536:
                ff.write(np.asarray(buf, dtype=np.float32).tobytes())
                buf = []
        if buf:
            ff.write(np.asarray(buf, dtype=np.float32).tobytes())
    ESTADO.write_text(json.dumps({
        'offset': off, 'linhas': n, 'W': W,
        'cabeca': ce._hash(ind, 0, ce._CABECA),
        'elo': ce._hash(ind, off - ce._ELO, min(ce._ELO, off)),
    }), encoding='utf-8')
    if recomecou or novas:
        print('  binario das escolhidas: %s %d linhas (%.2f GB de numeros)'
              % ('RECONSTRUIDO:' if recomecou else '+%d novas ->' % novas, n,
                 FEATS.stat().st_size / 1e9), flush=True)
    return n


def linhas():
    """Cada jogada escolhida como o dict do indice, com `feats` = linha float32
    do binario (visao do memmap; None se a largura nao cabia)."""
    n = atualiza()
    W = largura()
    if n == 0:
        return
    mm = np.memmap(FEATS, dtype=np.float32, mode='r', shape=(n, W))
    with open(META_L, 'rb') as fm:
        for i, ln in enumerate(fm):
            if i >= n:
                break
            d = json.loads(ln)
            d['feats'] = None if '_largura' in d else mm[i]
            yield d


if __name__ == '__main__':
    k = atualiza(reconstroi='--reconstroi' in sys.argv)
    print('binario: %d linhas | feats %.2f GB | meta %.2f GB'
          % (k, FEATS.stat().st_size / 1e9, META_L.stat().st_size / 1e9))
