# -*- coding: utf-8 -*-
"""INDICE DAS JOGADAS ESCOLHIDAS do corpus do Q (bloco 931).

POR QUE EXISTE (AS-IS 02/10/2026): `metrics/q_alvos.jsonl` tem 3,2 GB e 4,3
milhoes de linhas, e CADA ciclo lia tudo varias vezes -- treino do Q, relatorio
de qualidade, diagnostico de decisoes, contagem de linhas -- ~5 min por
leitura, ~10 min por ciclo. Mas desde o bloco 923 o treino usa so as jogadas
ESCOLHIDAS (~8% do corpus); as qualidade/diagnostico tambem so olham as
escolhidas (so elas tem `regret` e consequencia). Os outros 92% eram lidos e
jogados fora toda vez.

O QUE E: `metrics/q_escolhidas.jsonl` = as linhas com `"escolhida": true`, NA
MESMA ORDEM do corpus, copiadas BYTE A BYTE (sem reinterpretar). E DERIVADO e
regeneravel (gitignored, igual ao proprio `q_alvos.jsonl`): o corpus completo
continua intacto e e a fonte de verdade; nada e perdido.

COMO FICA EM DIA: o corpus so CRESCE (append). `atualiza()` le so os bytes
novos desde o ultimo `offset` e acrescenta as escolhidas -- ~1 s por ciclo em
vez de ~5 min. Se o corpus foi reescrito/truncado (impressao do inicio ou do
trecho logo antes do offset mudou, ou o arquivo ficou menor), reconstroi do
zero (uma vez, ~20 s) em vez de usar indice desatualizado.

Uso:
    python corpus_escolhidas.py            # atualiza e mostra o estado
    python corpus_escolhidas.py --reconstroi
"""
from __future__ import annotations

import hashlib
import re
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ORIGEM = RAIZ / 'metrics' / 'q_alvos.jsonl'
INDICE = RAIZ / 'metrics' / 'q_escolhidas.jsonl'
META = RAIZ / 'metrics' / 'q_escolhidas_meta.json'
# ALTERNATIVAS das geracoes RECENTES (bloco 937, decisao do usuario 04/10): a
# nota que a simulacao deu a cada jogada NAO jogada vira ensino do Q. So as
# ultimas GERACOES_ALT geracoes: a nota foi dada pela regua da epoca, e regua
# velha e nota velha. Derivado e gitignored, como o indice das escolhidas.
ALTERNATIVAS = RAIZ / 'metrics' / 'q_alternativas.jsonl'
GERACOES_ALT = 3
_GEN = re.compile(rb'"gen": (\d+)')

_MARCA = b'"escolhida": true'
_CABECA = 1 << 20          # impressao do inicio do corpus
_ELO = 1 << 12             # impressao dos bytes logo ANTES do offset


def _hash(caminho: Path, ini: int, n: int) -> str:
    with open(caminho, 'rb') as fh:
        fh.seek(max(0, ini))
        return hashlib.sha1(fh.read(n)).hexdigest()


def _meta() -> dict | None:
    try:
        return json.loads(META.read_text(encoding='utf-8'))
    except Exception:
        return None


def _consistente(m: dict | None, origem: Path) -> bool:
    """O indice ainda descreve ESTE corpus? Corpus so cresce: o inicio e o
    trecho antes do offset tem que ser os mesmos bytes de quando foi lido."""
    if not m or not INDICE.exists() or not origem.exists():
        return False
    off = int(m.get('offset', -1))
    if off < 0 or origem.stat().st_size < off:
        return False
    if m.get('cabeca') != _hash(origem, 0, _CABECA):
        return False
    return m.get('elo') == _hash(origem, off - _ELO, min(_ELO, off))


def atualiza(origem: Path = ORIGEM, indice: Path = INDICE, reconstroi: bool = False) -> Path:
    """Poe o indice em dia com o corpus e devolve o caminho dele."""
    m = _meta()
    if reconstroi or not _consistente(m, origem):
        if indice.exists():
            indice.unlink()
        m = {'offset': 0, 'linhas': 0, 'escolhidas': 0}
        recomecou = True
        if ALTERNATIVAS.exists():
            ALTERNATIVAS.unlink()
    else:
        recomecou = False
    offset, linhas, escolhidas = int(m['offset']), int(m['linhas']), int(m['escolhidas'])
    novas = 0
    gen_max = int(m.get('gen_max', 0))
    # reconstrucao: so as ultimas geracoes interessam -- descobre a maior
    # olhando o fim do arquivo (o corpus e append, a ultima linha e a mais nova)
    if recomecou and origem.exists():
        with open(origem, 'rb') as fh:
            fh.seek(max(0, origem.stat().st_size - (1 << 16)))
            gs = [int(g) for g in _GEN.findall(fh.read())]
        gen_max = max(gs) if gs else 0
    corte = gen_max - GERACOES_ALT + 1
    with open(origem, 'rb') as fi, open(indice, 'ab') as fo, open(ALTERNATIVAS, 'ab') as fa:
        fi.seek(offset)
        for ln in fi:
            if not ln.endswith(b'\n'):
                break                      # linha ainda sendo escrita: fica pro proximo
            offset += len(ln)
            linhas += 1
            if _MARCA in ln:
                fo.write(ln)
                escolhidas += 1
                novas += 1
            elif b'"decisao": ' in ln:
                g = _GEN.search(ln)
                g = int(g.group(1)) if g else 0
                if g >= corte:
                    fa.write(ln)
                    gen_max = max(gen_max, g)
    _poda_alternativas(gen_max - GERACOES_ALT + 1)
    META.write_text(json.dumps({
        'offset': offset, 'linhas': linhas, 'escolhidas': escolhidas, 'gen_max': gen_max,
        'cabeca': _hash(origem, 0, _CABECA), 'elo': _hash(origem, offset - _ELO, min(_ELO, offset)),
    }), encoding='utf-8')
    if recomecou or novas:
        print('  indice das escolhidas: %s %d linhas escolhidas de %d (%.1f%%)'
              % ('RECONSTRUIDO:' if recomecou else '+%d novas ->' % novas,
                 escolhidas, linhas, 100.0 * escolhidas / max(1, linhas)), flush=True)
    return indice


def _poda_alternativas(corte: int) -> None:
    """Tira do arquivo de alternativas as geracoes que sairam da janela."""
    if not ALTERNATIVAS.exists():
        return
    with open(ALTERNATIVAS, 'rb') as fh:
        primeira = fh.readline()
    g = _GEN.search(primeira)
    if not g or int(g.group(1)) >= corte:
        return                                # nada velho (arquivo em ordem de geracao)
    tmp = ALTERNATIVAS.with_suffix('.tmp')
    with open(ALTERNATIVAS, 'rb') as fi, open(tmp, 'wb') as fo:
        for ln in fi:
            g = _GEN.search(ln)
            if g and int(g.group(1)) >= corte:
                fo.write(ln)
    tmp.replace(ALTERNATIVAS)


def total_linhas() -> int:
    """Linhas do corpus COMPLETO, sem reler o arquivo (vem do indice)."""
    m = _meta()
    return int(m['linhas']) if m else 0


if __name__ == '__main__':
    p = atualiza(reconstroi='--reconstroi' in sys.argv)
    m = _meta()
    print('corpus: %d linhas | escolhidas: %d | %s (%.0f MB)'
          % (m['linhas'], m['escolhidas'], p.name, p.stat().st_size / 1e6))
