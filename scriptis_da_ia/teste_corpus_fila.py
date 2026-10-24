#!/usr/bin/env python
"""Teste da FILA do corpus (`corpus_git.py consolida --esvazia`, bloco 984).

O `q_alvos.jsonl` deixa de guardar o historico inteiro (40 GB): depois de
consolidado ele e ESVAZIADO e o historico mora nas fatias do git e nos
derivados do treino. O risco que este teste cobre: esvaziar o arquivo e os
derivados acharem que o corpus foi REESCRITO e se reconstruirem a partir da
fila vazia -- apagando o historico em silencio.

Controles (tem que REPROVAR o jeito ingenuo):
  - truncar SEM `marca_esvaziado` -> o indice das escolhidas e reconstruido
    (perde as escolhidas antigas);
  - esvaziar sem `--confirmo` nao apaga nada.

    cd scriptis_da_ia && python teste_corpus_fila.py
"""
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus_escolhidas as ce  # noqa: E402
import corpus_git as cg  # noqa: E402
import alt_bin  # noqa: E402
import corpus_bin  # noqa: E402

falhas = []


def ok(cond, msg):
    print(('[OK] ' if cond else '[FALHA] ') + msg)
    if not cond:
        falhas.append(msg)


def linha(i, gen, escolhida, origem='Maquina_A'):
    d = {'feats': [float(i), 0.0, 1.0], 'alvo': i / 100.0, 'escolhida': escolhida,
         'leader': 'OP01-001', 'turn': 1, 'match': i, 'gen': gen, 'origem': origem}
    if not escolhida:
        d['decisao'] = i
    return json.dumps(d) + '\n'


def aponta(d: Path, git: Path):
    m = d / 'metrics'
    cg.CORPUS = m / 'q_alvos.jsonl'
    cg.FATIAS = git / 'metrics' / 'q_alvos'
    cg.LIVRO = m / 'q_alvos_fatias.json'
    cg.origem_desta_maquina = lambda: 'Maquina_A'
    ce.ORIGEM = m / 'q_alvos.jsonl'
    ce.INDICE = m / 'q_escolhidas.jsonl'
    ce.META = m / 'q_escolhidas_meta.json'
    ce.ALTERNATIVAS = m / 'q_alternativas.jsonl'
    alt_bin.DIR = m / 'q_alt_bin'
    alt_bin.VOCAB = alt_bin.DIR / 'vocab.json'
    alt_bin.largura = lambda: 3
    cg._tamanho_estavel = lambda espera=0: True


def escolhidas():
    return [json.loads(l)['match'] for l in ce.INDICE.read_text(encoding='utf-8').splitlines()]


def linhas_das_fatias():
    n = 0
    for f in sorted(cg.FATIAS.glob('*.jsonl.gz')):
        with gzip.open(f, 'rt', encoding='utf-8') as fh:
            n += sum(1 for l in fh if l.strip())
    return n


base = Path(tempfile.mkdtemp())
try:
    git = base / 'git'
    A = base / 'A'
    for d in (git / 'metrics' / 'q_alvos', A / 'metrics'):
        d.mkdir(parents=True, exist_ok=True)
    aponta(A, git)
    # TRAVA (bloco 984): este teste ja apagou o indice REAL uma vez. Nenhum
    # caminho pode cair fora do diretorio temporario.
    for p in (cg.CORPUS, cg.FATIAS, cg.LIVRO, ce.ORIGEM, ce.INDICE, ce.META, ce.ALTERNATIVAS,
              alt_bin.DIR, alt_bin.VOCAB):
        assert str(p).startswith(str(base)), f'caminho REAL no teste: {p}'

    # historico: 3 geracoes, escolhidas e alternativas
    hist = [linha(i, i // 10, i % 3 == 0) for i in range(30)]
    cg.CORPUS.write_text(''.join(hist), encoding='utf-8', newline='')
    esc_antes = [i for i in range(30) if i % 3 == 0]

    # sem --confirmo: nao apaga
    r = cg.cmd_consolida(esvazia=True, confirmo=False)
    ok(r == 1 and cg.CORPUS.stat().st_size > 0, 'sem --confirmo o corpus NAO e esvaziado')
    ok(escolhidas() == esc_antes, 'consolida pos o indice das escolhidas em dia')
    ok(linhas_das_fatias() == 30, 'consolida exportou o historico inteiro pras fatias')

    r = cg.cmd_consolida(esvazia=True, confirmo=True)
    ok(r == 0 and cg.CORPUS.stat().st_size == 0, 'com --confirmo o corpus vira fila VAZIA')

    # geracao nova acrescenta na fila (escritores nao mudam)
    novas = [linha(i, 3, i % 3 == 0) for i in range(30, 45)]
    with open(cg.CORPUS, 'a', encoding='utf-8', newline='') as fh:
        fh.write(''.join(novas))
    ce.atualiza()
    esc_depois = esc_antes + [i for i in range(30, 45) if i % 3 == 0]
    ok(escolhidas() == esc_depois,
       'depois de esvaziar, o indice CONTINUA (antigas + novas, sem reconstruir)')
    meta = json.loads(ce.META.read_text(encoding='utf-8'))
    ok(meta['linhas'] == 45, f'contagem acumulada de linhas = 45 (deu {meta["linhas"]})')

    loc = cg._conta_corpus()
    ok(sum(loc.values()) == 45, f'contagem da sincronizacao acumulada = 45 (deu {sum(loc.values())})')
    falt = cg._a_exportar(loc, cg._nas_fatias())
    ok(falt == {'Maquina_A': 15}, f'so as 15 novas aparecem como "a exportar" ({falt})')
    cg.cmd_exporta('teste')
    ok(linhas_das_fatias() == 45, 'exporta depois de esvaziar manda SO as novas (30 + 15)')

    alt = [json.loads(l)['gen'] for l in ce.ALTERNATIVAS.read_text(encoding='utf-8').splitlines()]
    ok(alt and min(alt) >= 1 and 3 in alt,
       f'alternativas seguem a janela de 3 geracoes ({sorted(set(alt))})')
    bins = sorted(int(p.stem.split('_')[1]) for p in alt_bin.DIR.glob('gen_*.rec'))
    ok(bins == sorted(set(alt)), f'binario das alternativas segue a MESMA janela ({bins})')
    ok([d['gen'] for d in alt_bin.linhas()] == alt,
       'binario devolve as alternativas na MESMA ordem do texto')

    # CONTROLE: truncar sem marca_esvaziado reconstroi (perde o historico)
    with open(cg.CORPUS, 'r+b') as fh:
        fh.truncate(0)
    with open(cg.CORPUS, 'a', encoding='utf-8', newline='') as fh:
        fh.write(linha(99, 4, True))
    ce.atualiza()
    ok(escolhidas() == [99],
       'CONTROLE: truncar SEM marca_esvaziado reconstroi o indice e perde o historico')
finally:
    shutil.rmtree(base, ignore_errors=True)

print()
print('FALHAS:', len(falhas) if falhas else 0)
sys.exit(1 if falhas else 0)
