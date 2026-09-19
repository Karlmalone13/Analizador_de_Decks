#!/usr/bin/env python
"""O corpus de alvos viaja pelo GIT, em FATIAS comprimidas.

POR QUE ISTO EXISTE
-------------------
Ate 18/09/2026 o `metrics/q_alvos.jsonl` (465 MB) era gitignored e atravessava
entre as maquinas como .zip entregue a mao pela sessao. O modo de falha estava
documentado no bloco 851 e e SILENCIOSO: quem esquecesse de descompactar
treinava com um corpus 10,5% menor e jogava fora 73.477 linhas sem erro nenhum.

A `REGRA_DUAS_MAQUINAS.md` ja tinha avaliado git e recusado, com este
argumento:

    "O corpus fica fora porque cresce a cada ciclo e .gz nao faz delta entre
     versoes -- cada commit guardaria uma copia inteira nova, ~13 MB
     permanentes por ciclo."

**O argumento esta CERTO, e e exatamente o que este arquivo desfaz.** Ele vale
para um zip UNICO regerado a cada ciclo. Aqui o corpus vira N fatias, cada uma
escrita UMA vez e NUNCA reescrita -- entao um ciclo novo acrescenta so as suas
proprias linhas, nao uma copia nova de tudo.

Medido em 18/09 nesta maquina:

    amostra de 20.000 linhas : 13,1 MB -> 0,35 MB gz   (fator 37,4x)
    corpus de 698.838 linhas : 465 MB  -> ~12 MB gz
    incremento de 1 ciclo    :  47 MB  -> ~1,3 MB gz

O CAMINHO FIXO NAO MUDA
-----------------------
`ciclo.py`, `treinar_q.py` e `treino_continuo.py` leem todos o mesmo
`metrics/q_alvos.jsonl`. Nenhum deles e tocado: as fatias sao materializadas
NAQUELE arquivo, que continua gitignored por ser derivado.

    metrics/q_alvos/<origem>_<timestamp>.jsonl.gz   VERSIONADO, imutavel
    metrics/q_alvos.jsonl                           gitignored, derivado
    metrics/q_alvos_fatias.json                     gitignored, o que ja entrou

POR QUE FATIAS E NAO UM ZIP SO
------------------------------
Um arquivo unico regerado nas duas maquinas e binario sem merge: quem empurrar
por ultimo apaga o trabalho do outro EM SILENCIO -- o mesmo modo de falha que a
regra ja registra para o `q_net.joblib`. Fatias por (origem, timestamp) nunca
colidem: o git funde as duas adicoes sozinho, porque concatenar E a operacao de
merge quando os arquivos sao separados.

A IDENTIDADE E POSICIONAL, NAO POR HASH DE LINHA (erro pego em 18/09)
---------------------------------------------------------------------
A primeira versao deste arquivo deduplicava por hash do conteudo da linha, na
mesma disciplina do `impressao` do banco de logs (bloco 856). **Esta errado
aqui**, e o teste mostrou antes de qualquer export: das 698.838 linhas, 672.992
sao distintas -- 25.846 linhas (3,7%) tem conteudo repetido.

Investigadas uma a uma: sao ADJACENTES (distancia 1-2), mesmo `match`, mesmo
`turn`. Nao sao eco de re-execucao -- sao candidatos IDENTICOS dentro da MESMA
decisao (duas copias da mesma carta oferecidas como alvo). Sao dado legitimo e
tem peso no treino. Deduplicar teria descartado 3,7% do corpus sem erro nenhum,
exatamente a classe de falha silenciosa que esta ferramenta existe para matar.

A identidade usada e: **por `origem`, posicional**. Para cada valor de `origem`,
as fatias ja contem N linhas e o corpus local tem M; exporta-se as ULTIMAS
(M - N). O corpus so cresce por acrescimo, entao a ordem dentro de cada origem e
estavel, e repeticoes legitimas sobrevivem intactas.

A protecao contra importar a mesma fatia duas vezes e o LIVRO (nome da fatia ja
aplicada), nao o conteudo da linha.

O IMPORT RECONCILIA LINHA A LINHA (erro pago em 18/09/2026)
-----------------------------------------------------------
Quando o LIVRO nao cobre (clone novo por cima de corpus existente, fatia de
backfill, corpus que veio por outra via), o import precisa decidir o que ja
esta aqui. A primeira versao decidia pela FATIA INTEIRA, por origem:

    ja_presente = all(locais[o] >= aplicadas[o] + n for o, n in desta.items())

Tudo-ou-nada. Uma fatia de backfill com 3 origens -- duas ja completas aqui e
UMA faltando 616 linhas -- reprovou o `all(...)` e foi anexada POR INTEIRO:
**698.222 linhas duplicadas**, corpus de 699.230 para 1.398.068, sem erro
nenhum. O `status` tinha anunciado 687 linhas a importar.

Agora cada linha da fatia e conferida contra um MULTICONJUNTO das linhas locais
das mesmas origens: presente, pula; ausente, anexa. Repeticao legitima
sobrevive porque a contagem e por multiplicidade, nao por presenca.

Uso:
    python corpus_git.py status      # o que falta importar/exportar
    python corpus_git.py importa     # aplica as fatias do git no .jsonl local
    python corpus_git.py exporta     # cria a fatia com o que so existe aqui
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CORPUS = RAIZ / 'metrics' / 'q_alvos.jsonl'
FATIAS = RAIZ / 'metrics' / 'q_alvos'
LIVRO = RAIZ / 'metrics' / 'q_alvos_fatias.json'


def origem_desta_maquina() -> str:
    """Reusa a convencao que ja grava o campo `origem` em cada linha.

    NAO duplicar: `gerar_selfplay_dataset._origem_padrao` e a fonte unica
    (OPTCG_ORIGEM manda, senao o hostname). Ter duas funcoes respondendo "que
    maquina e esta" faria as fatias de uma mesma maquina sairem com dois nomes.
    """
    try:
        from gerar_selfplay_dataset import _origem_padrao
        return _origem_padrao()
    except Exception:
        import socket
        return (os.environ.get('OPTCG_ORIGEM') or '').strip() or socket.gethostname()


def _mil(n: int) -> str:
    return format(n, ',').replace(',', '.')


def _origem_da_linha(linha: str) -> str:
    try:
        return json.loads(linha).get('origem') or '(sem origem)'
    except Exception:
        return '(ilegivel)'


def _conta_por_origem(caminho: Path, comprimido: bool) -> collections.Counter:
    if not caminho.exists():
        return collections.Counter()
    abre = gzip.open if comprimido else open
    c: collections.Counter = collections.Counter()
    with abre(caminho, 'rt', encoding='utf-8', newline='') as fh:
        for linha in fh:
            if linha.strip():
                c[_origem_da_linha(linha)] += 1
    return c


def _fatias_no_git() -> list[Path]:
    if not FATIAS.exists():
        return []
    return sorted(FATIAS.glob('*.jsonl.gz'))


def _digesto(linha: str) -> bytes:
    """Identidade de uma linha para reconciliar fatia contra corpus local.

    Hash e so para caber na memoria (700k linhas x 465 MB nao cabem como str).
    NAO e deduplicacao: a contagem e um MULTICONJUNTO, entao duas linhas
    identicas legitimas -- candidatos iguais na MESMA decisao, 3,7% do corpus
    real -- continuam valendo por duas.
    """
    return hashlib.blake2b(linha.strip().encode('utf-8'), digest_size=16).digest()


def _multiconjunto_local(origens: set[str]) -> collections.Counter:
    """Quantas vezes cada linha ja existe no corpus local, por `origem` em escopo."""
    c: collections.Counter = collections.Counter()
    if not CORPUS.exists():
        return c
    with open(CORPUS, encoding='utf-8', newline='') as fh:
        for linha in fh:
            if linha.strip() and _origem_da_linha(linha) in origens:
                c[_digesto(linha)] += 1
    return c


def _livro() -> dict:
    if LIVRO.exists():
        try:
            return json.loads(LIVRO.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'aplicadas': []}


def _grava_livro(dados: dict) -> None:
    LIVRO.parent.mkdir(parents=True, exist_ok=True)
    LIVRO.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding='utf-8')


def _nas_fatias() -> collections.Counter:
    total: collections.Counter = collections.Counter()
    for f in _fatias_no_git():
        total += _conta_por_origem(f, comprimido=True)
    return total


def pendentes() -> list[Path]:
    """Fatias que estao no git e ainda NAO entraram no corpus local."""
    ja = set(_livro().get('aplicadas', []))
    return [f for f in _fatias_no_git() if f.name not in ja]


def exige_sincronizado(quem: str) -> None:
    """Portao OBRIGATORIO, chamado por quem TREINA ou GERA.

    Para em vez de avisar porque o modo de falha nao da erro: treinar com o
    corpus menor apenas produz um modelo pior, e ninguem descobre.
    """
    falta = pendentes()
    if not falta:
        return
    p = lambda s='': print(s, file=sys.stderr)
    p()
    p(f'BLOQUEADO: {quem} nao pode rodar com fatia de corpus pendente.')
    p(f'{len(falta)} fatia(s) vieram do git e ainda nao entraram no corpus local:')
    for f in falta[:10]:
        p(f'  - {f.name}')
    if len(falta) > 10:
        p(f'  ... e mais {len(falta) - 10}')
    p()
    p('  cd scriptis_da_ia && python corpus_git.py importa')
    p()
    p('Rodar assim treinaria com um corpus MENOR sem nenhum erro aparecer --')
    p('foi exatamente o que custou um dia de trabalho em 18/09 (bloco 851).')
    p()
    raise SystemExit(1)


def _a_exportar(locais: collections.Counter,
                fatias: collections.Counter) -> dict[str, int]:
    """Quantas linhas de cada origem existem aqui e ainda nao estao no git."""
    return {o: locais[o] - fatias.get(o, 0)
            for o in locais if locais[o] - fatias.get(o, 0) > 0}


def cmd_status() -> int:
    locais = _conta_por_origem(CORPUS, comprimido=False)
    fatias = _nas_fatias()
    falta = pendentes()

    print(f'corpus local   : {CORPUS}')
    print(f'  linhas       : {_mil(sum(locais.values()))}')
    print(f'fatias no git  : {len(_fatias_no_git())}')
    print(f'  linhas       : {_mil(sum(fatias.values()))}')
    print('')
    print(f'{"origem":<28} {"aqui":>10} {"no git":>10} {"a exportar":>12}')
    for o in sorted(set(locais) | set(fatias)):
        delta = locais.get(o, 0) - fatias.get(o, 0)
        print(f'{o:<28} {_mil(locais.get(o, 0)):>10} {_mil(fatias.get(o, 0)):>10} '
              f'{(_mil(delta) if delta > 0 else "-"):>12}')

    atras = {o: fatias[o] - locais.get(o, 0) for o in fatias
             if fatias[o] - locais.get(o, 0) > 0}
    print('')
    if falta:
        print(f'A IMPORTAR: {len(falta)} fatia(s) nao aplicadas '
              f'({_mil(sum(atras.values()))} linhas)')
        for f in falta:
            print(f'  - {f.name}')
    else:
        print('A IMPORTAR: nada (corpus local em dia com o git)')

    exportar = _a_exportar(locais, fatias)
    if exportar:
        print(f'A EXPORTAR: {_mil(sum(exportar.values()))} linhas desta maquina '
              f'ainda nao estao no git')
    else:
        print('A EXPORTAR: nada')
    return 0


def cmd_importa() -> int:
    falta = pendentes()
    if not falta:
        print('nada a importar: toda fatia do git ja esta no corpus local.')
        return 0

    locais = _conta_por_origem(CORPUS, comprimido=False)
    livro = _livro()
    ja = set(livro.get('aplicadas', []))

    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    antes = sum(locais.values())
    novas = 0

    for f in falta:
        desta = _conta_por_origem(f, comprimido=True)
        # Reconcilia LINHA A LINHA contra o que o corpus local ja tem, em vez de
        # decidir pela fatia inteira. O guarda anterior era tudo-ou-nada por
        # origem: bastava UMA origem incompleta para ele reaplicar a fatia
        # INTEIRA. Custou 698.222 linhas duplicadas em 18/09/2026 -- uma fatia
        # de backfill com 3 origens, duas ja completas aqui e uma faltando 616
        # linhas, foi anexada por inteiro.
        presentes = _multiconjunto_local(set(desta))
        desta_fatia = 0
        with open(CORPUS, 'a', encoding='utf-8', newline='') as saida, \
                gzip.open(f, 'rt', encoding='utf-8', newline='') as fh:
            for linha in fh:
                if not linha.strip():
                    continue
                d = _digesto(linha)
                if presentes[d] > 0:      # ja esta aqui: consome uma ocorrencia
                    presentes[d] -= 1     # (multiconjunto -- repetida legitima
                    continue              #  so e pulada tantas vezes quanto ha)
                saida.write(linha if linha.endswith('\n') else linha + '\n')
                desta_fatia += 1
                locais[_origem_da_linha(linha)] += 1

        novas += desta_fatia
        trazidas = sum(desta.values())
        if desta_fatia == 0:
            print(f'  {f.name}: ja presente no corpus local (so registra)')
        elif desta_fatia < trazidas:
            print(f'  {f.name}: +{_mil(desta_fatia)} linhas '
                  f'({_mil(trazidas - desta_fatia)} de {_mil(trazidas)} ja estavam aqui)')
        else:
            print(f'  {f.name}: +{_mil(desta_fatia)} linhas')
        ja.add(f.name)

    livro['aplicadas'] = sorted(ja)
    _grava_livro(livro)
    print('')
    print(f'corpus {_mil(antes)} -> {_mil(antes + novas)} linhas (+{_mil(novas)})')
    return 0


def cmd_exporta(rotulo: str | None) -> int:
    if not CORPUS.exists():
        print(f'corpus local nao existe: {CORPUS}', file=sys.stderr)
        return 1

    locais = _conta_por_origem(CORPUS, comprimido=False)
    fatias = _nas_fatias()
    faltando = _a_exportar(locais, fatias)
    if not faltando:
        print('nada a exportar: tudo que esta aqui ja esta no git.')
        return 0

    # Exporta as ULTIMAS (M - N) linhas de cada origem: e o que ainda nao foi.
    # Preserva repeticoes legitimas, que sao 3,7% do corpus (ver docstring).
    pular = dict(fatias)
    FATIAS.mkdir(parents=True, exist_ok=True)
    nome = f'{origem_desta_maquina()}_{datetime.now():%Y%m%dT%H%M%S}'
    if rotulo:
        nome += f'_{rotulo}'
    destino = FATIAS / f'{nome}.jsonl.gz'

    escritas: collections.Counter = collections.Counter()
    vistas: collections.Counter = collections.Counter()
    # mtime=0: conteudo igual gera bytes iguais, entao reexportar por engano nao
    # cria um arquivo diferente so por causa do relogio.
    # newline='' nos DOIS lados: sem isso o Python traduz \n -> \r\n na escrita
    # no Windows e a fatia deixa de reproduzir o corpus byte a byte. O corpus
    # real ja tem fim de linha MISTURADO (a Arthur_PC grava LF, a
    # Arthur_Trabalho CRLF -- sao 73.477 linhas CRLF em 698.838), entao
    # traduzir na leitura tambem apagaria a distincao. Preservar o byte
    # original e o que torna o round-trip exato.
    with open(CORPUS, 'rt', encoding='utf-8', newline='') as fonte, \
            gzip.GzipFile(destino, 'wb', compresslevel=9, mtime=0) as bruto, \
            io.TextIOWrapper(bruto, encoding='utf-8', newline='') as saida:
        for linha in fonte:
            if not linha.strip():
                continue
            o = _origem_da_linha(linha)
            vistas[o] += 1
            if vistas[o] <= pular.get(o, 0):
                continue
            saida.write(linha if linha.endswith('\n') else linha + '\n')
            escritas[o] += 1

    total = sum(escritas.values())
    if total == 0:
        destino.unlink(missing_ok=True)
        print('nada a exportar.')
        return 0

    livro = _livro()
    livro['aplicadas'] = sorted(set(livro.get('aplicadas', [])) | {destino.name})
    _grava_livro(livro)

    print(f'fatia criada: metrics/q_alvos/{destino.name}')
    for o, n in sorted(escritas.items()):
        print(f'  {o:<28} {_mil(n):>10} linhas')
    print(f'  {"TOTAL":<28} {_mil(total):>10} linhas')
    print(f'  tamanho: {destino.stat().st_size / 1e6:.1f} MB')
    print('')
    print('Agora versione a fatia (a regra do projeto PROIBE `git add -A`):')
    print(f'  git add scriptis_da_ia/metrics/q_alvos/{destino.name}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('status', help='o que falta importar/exportar')
    sub.add_parser('importa', help='aplica as fatias do git no corpus local')
    ex = sub.add_parser('exporta', help='cria a fatia com o que so existe aqui')
    ex.add_argument('--rotulo', default=None, help='sufixo opcional no nome da fatia')
    args = ap.parse_args()

    if args.cmd == 'importa':
        return cmd_importa()
    if args.cmd == 'exporta':
        return cmd_exporta(args.rotulo)
    return cmd_status()


if __name__ == '__main__':
    raise SystemExit(main())
