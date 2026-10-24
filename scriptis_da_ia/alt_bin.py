# -*- coding: utf-8 -*-
"""As ALTERNATIVAS (jogadas NAO feitas, nota da simulacao) em BINARIO, POR GERACAO.

POR QUE EXISTE (AS-IS 24/10/2026, bloco 986): todo treino le `q_alternativas.jsonl`
(3,6 GB de TEXTO) e faz `json.loads` de ~158 numeros por linha -- o mesmo custo
que o `q_bin` (bloco 969) tirou das escolhidas. O arquivo e PODADO a cada geracao
nova (janela de `corpus_escolhidas.GERACOES_ALT`), entao um binario unico teria
que ser refeito todo ciclo. Aqui cada geracao e um arquivo: a poda so apaga.

O QUE E (derivado, gitignored, regeneravel a partir de `q_alternativas.jsonl`):
    metrics/q_alt_bin/gen_<g>.f32   float32, uma linha por alternativa, largura W
    metrics/q_alt_bin/gen_<g>.rec   registro fixo (_REC) da MESMA linha
    metrics/q_alt_bin/vocab.json    W, prox_seq e os textos (lider, acao, modo)

`seq` = posicao da linha no fluxo de alternativas: `linhas()` devolve na MESMA
ordem do texto (o treino sorteia com semente fixa -- ordem diferente = modelo
diferente). Linha que o treino descartaria por largura sai com `ok` = 0 e
`feats` None (mesma regra: completa ate 60 colunas a menos, colunas novas no fim).

Quem escreve: `corpus_escolhidas.atualiza` (no MESMO laco que escreve o texto) e
`constroi()` (uma vez, a partir do texto). Quem le: `treinar_q.py`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
DIR = RAIZ / 'metrics' / 'q_alt_bin'
VOCAB = DIR / 'vocab.json'
_JANELA = 60
_REC = np.dtype([('seq', '<i8'), ('alvo', '<f8'), ('match', '<i8'), ('decisao', '<i8'),
                 ('dec_none', 'i1'), ('ok', 'i1'), ('leader', '<i2'), ('acao', '<i2'),
                 ('modo', '<i2')])


def largura() -> int:
    import corpus_bin
    return corpus_bin.largura()


def _vocab() -> dict:
    try:
        return json.loads(VOCAB.read_text(encoding='utf-8'))
    except Exception:
        return {}


def valido() -> bool:
    """Binario existe e tem a largura atual do vetor do Q."""
    v = _vocab()
    return bool(v) and v.get('W') == largura() and v.get('completo') is True


def apaga() -> None:
    if DIR.exists():
        for p in DIR.iterdir():
            p.unlink()


def poda(corte: int) -> None:
    """Apaga as geracoes que sairam da janela (< corte)."""
    if not DIR.exists():
        return
    for p in DIR.glob('gen_*.*'):
        try:
            g = int(p.stem.split('_', 1)[1])
        except ValueError:
            continue
        if g < corte:
            p.unlink()


class Escritor:
    """Acrescenta linhas (dict do jsonl) nos arquivos da geracao delas."""

    def __init__(self, completo_ao_fechar: bool | None = None):
        DIR.mkdir(parents=True, exist_ok=True)
        v = _vocab()
        self.W = largura()
        if v and v.get('W') != self.W:
            apaga()
            v = {}
        self.v = v or {'W': self.W, 'prox_seq': 0, 'leader': [], 'acao': [], 'modo': [],
                       'completo': False}
        self._idx = {k: {s: i for i, s in enumerate(self.v[k])} for k in ('leader', 'acao', 'modo')}
        self._buf: dict[int, tuple[list, list]] = {}
        self.completo_ao_fechar = completo_ao_fechar

    def _id(self, campo: str, s) -> int:
        s = '' if s is None else str(s)
        m = self._idx[campo]
        if s not in m:
            m[s] = len(self.v[campo])
            self.v[campo].append(s)
        return m[s]

    def add(self, d: dict) -> None:
        f, a = d.get('feats'), d.get('alvo')
        ok = 1
        row = np.zeros(self.W, dtype=np.float32)
        if not f or a is None:
            ok = 0
        else:
            n = len(f)
            if self.W - _JANELA <= n <= self.W:
                row[:n] = f
            else:
                ok = 0
        dec = d.get('decisao')
        rec = (self.v['prox_seq'], float('nan') if a is None else float(a),
               int(d.get('match') or 0), int(dec) if dec is not None else 0,
               1 if dec is None else 0, ok, self._id('leader', d.get('leader')),
               self._id('acao', d.get('acao')), self._id('modo', d.get('modo')))
        self.v['prox_seq'] += 1
        g = int(d.get('gen') or 0)
        rows, recs = self._buf.setdefault(g, ([], []))
        rows.append(row)
        recs.append(rec)
        if len(rows) >= 20000:
            self._despeja(g)

    def _despeja(self, g: int) -> None:
        rows, recs = self._buf.pop(g, ([], []))
        if not rows:
            return
        with open(DIR / f'gen_{g}.f32', 'ab') as fh:
            np.asarray(rows, dtype=np.float32).tofile(fh)
        with open(DIR / f'gen_{g}.rec', 'ab') as fh:
            np.asarray(recs, dtype=_REC).tofile(fh)

    def fecha(self) -> None:
        for g in list(self._buf):
            self._despeja(g)
        if self.completo_ao_fechar is not None:
            self.v['completo'] = self.completo_ao_fechar
        VOCAB.write_text(json.dumps(self.v), encoding='utf-8')


def constroi(origem: Path | None = None) -> int:
    """Refaz o binario inteiro a partir do `q_alternativas.jsonl`."""
    import corpus_escolhidas as ce
    origem = ce.ALTERNATIVAS if origem is None else origem
    apaga()
    esc = Escritor(completo_ao_fechar=True)
    n = 0
    if origem.exists():
        with open(origem, encoding='utf-8') as fh:
            for ln in fh:
                if ln.strip():
                    esc.add(json.loads(ln))
                    n += 1
    esc.fecha()
    return n


def linhas():
    """Cada alternativa como dict (campos que o treino usa), na ORDEM do texto.
    `feats` = linha float32 (visao do memmap) ou None se o treino a descartaria."""
    v = _vocab()
    W = v['W']
    partes = []
    for p in sorted(DIR.glob('gen_*.rec'), key=lambda p: int(p.stem.split('_')[1])):
        g = int(p.stem.split('_')[1])
        rec = np.fromfile(p, dtype=_REC)
        if len(rec) == 0:
            continue
        mm = np.memmap(p.with_suffix('.f32'), dtype=np.float32, mode='r', shape=(len(rec), W))
        partes.append((g, rec, mm))
    if not partes:
        return
    seq = np.concatenate([r['seq'] for _, r, _ in partes])
    qual = np.concatenate([np.full(len(r), k) for k, (_, r, _) in enumerate(partes)])
    pos = np.concatenate([np.arange(len(r)) for _, r, _ in partes])
    ordem = np.argsort(seq, kind='stable')
    L, A, M = v['leader'], v['acao'], v['modo']
    for i in ordem:
        g, rec, mm = partes[qual[i]]
        r = rec[pos[i]]
        yield {'feats': mm[pos[i]] if r['ok'] else None,
               'alvo': None if np.isnan(r['alvo']) else float(r['alvo']),
               'gen': g, 'match': int(r['match']),
               'decisao': None if r['dec_none'] else int(r['decisao']),
               'leader': L[r['leader']] or None, 'acao': A[r['acao']] or None,
               'modo': M[r['modo']] or None}


if __name__ == '__main__':
    if '--constroi' in sys.argv:
        print('alternativas em binario:', constroi(), 'linhas')
    v = _vocab()
    print('valido:', valido(), '| linhas:', v.get('prox_seq'), '| W:', v.get('W'))
