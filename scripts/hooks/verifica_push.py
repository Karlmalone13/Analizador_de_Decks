#!/usr/bin/env python
"""Checagens de integridade rodadas pelo hook de `pre-push`.

NO PUSH, NAO NO COMMIT (decisao do usuario, 18/09/2026): o commit e local e
barato, e travar cada um so atrapalharia. O push e o momento em que o dado
ATRAVESSA para a outra maquina -- e e ai que o estado quebra.

As tres coisas que quebram EM SILENCIO entre as duas maquinas:

  1. CORPUS nao exportado -- linhas geradas aqui que nao viram fatia .gz no git
     nunca chegam na outra maquina. Era o zip entregue a mao; agora e uma fatia
     esquecida. Mesmo estrago, mesmo silencio.

  2. `logs/index.json` apontando para arquivo NAO VERSIONADO -- o index viaja,
     os arquivos que ele referencia so viajam se alguem der `git add`. Achado
     real em 18/09: 13 arquivos de duas partidas de 17/09 ficaram so no disco da
     Arthur_PC, e o index do outro lado apontava para o vazio.

  3. `q_net.joblib` mexido sem `ciclo_estado.json` -- o modelo e binario e nao
     funde; o token e o unico jeito de saber de quem e a geracao. Modelo novo
     sem ciclo registrado e uma geracao orfa.

Para pular numa emergencia: `git push --no-verify` (nao recomendado).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
falhas: list[str] = []


def _bloqueia(titulo: str, linhas: list[str]) -> None:
    falhas.append(titulo)
    print('')
    print(f'BLOQUEADO: {titulo}')
    for ln in linhas:
        print(f'  {ln}')


def _rastreados() -> set[str]:
    saida = subprocess.run(['git', 'ls-files'], cwd=RAIZ, capture_output=True,
                           text=True, check=True).stdout
    return set(saida.splitlines())


def checa_index_de_logs() -> None:
    idx = RAIZ / 'scriptis_da_ia' / 'logs' / 'index.json'
    if not idx.exists():
        return
    try:
        entradas = json.loads(idx.read_text(encoding='utf-8'))
    except Exception as exc:
        _bloqueia('logs/index.json ilegivel', [str(exc)])
        return

    rastreados = _rastreados()
    # DOIS casos diferentes, e confundi-los faz o hook punir quem nao pode
    # consertar (erro pego ao testar, 18/09):
    #   - esta no DISCO e fora do git -> BLOQUEIA. E seu, e um `git add` resolve.
    #   - nao esta nem no disco       -> AVISA. Ficou na outra maquina; daqui
    #                                    nao ha o que versionar.
    por_versionar: list[str] = []
    so_na_outra: list[str] = []
    for e in entradas:
        refs: list[str] = []
        for chave in ('parsed_file', 'log_file', 'decision_log_file'):
            if e.get(chave):
                refs.append(e[chave])
        for chave in ('deck_files', 'deck_full_files'):
            refs += [v for v in (e.get(chave) or {}).values() if v]
        for r in refs:
            caminho = f'scriptis_da_ia/logs/{r}'
            if caminho in rastreados:
                continue
            (por_versionar if (RAIZ / caminho).exists() else so_na_outra).append(caminho)

    if por_versionar:
        _bloqueia(
            f'logs/index.json referencia {len(por_versionar)} arquivo(s) que estao '
            f'no seu disco e fora do git.',
            por_versionar[:12]
            + ([f'... e mais {len(por_versionar) - 12}'] if len(por_versionar) > 12 else [])
            + ['',
               'O index viaja e eles nao -- a outra maquina recebe ponteiro para o vazio.',
               'Versione-os (a regra do projeto PROIBE `git add -A`):',
               '  git add scriptis_da_ia/logs/<os arquivos acima>'])

    if so_na_outra:
        print('')
        print(f'AVISO: logs/index.json aponta para {len(so_na_outra)} arquivo(s) que '
              f'nao estao nem no disco nem no git.')
        for c in so_na_outra[:6]:
            print(f'  {c}')
        if len(so_na_outra) > 6:
            print(f'  ... e mais {len(so_na_outra) - 6}')
        print('  Ficaram na outra maquina. Nao bloqueia (daqui nao ha o que versionar),')
        print('  mas ate alguem la dar `git add`, estas entradas do index sao ponteiro morto.')


def checa_corpus() -> None:
    sys.path.insert(0, str(RAIZ / 'scriptis_da_ia'))
    try:
        import corpus_git as cg
    except Exception:
        return
    if not cg.CORPUS.exists():
        return
    locais = cg._conta_por_origem(cg.CORPUS, comprimido=False)
    fatias = cg._nas_fatias()
    faltando = cg._a_exportar(locais, fatias)
    if not faltando:
        return
    total = sum(faltando.values())
    _bloqueia(
        f'{cg._mil(total)} linha(s) do corpus nao estao no git.',
        [f'{o}: {cg._mil(n)}' for o, n in sorted(faltando.items())]
        + ['',
           'Sem exportar, este dado nunca chega na outra maquina -- e o mesmo',
           'estrago do zip esquecido, com o mesmo silencio.',
           '',
           '  cd scriptis_da_ia && python corpus_git.py exporta'])


def checa_modelo_com_token(base: str, topo: str) -> None:
    mudou = subprocess.run(
        ['git', 'diff', '--name-only', base, topo, '--',
         'scriptis_da_ia/metrics/q_net.joblib'],
        cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    if not mudou:
        return
    token = subprocess.run(
        ['git', 'diff', '--name-only', base, topo, '--',
         'scriptis_da_ia/metrics/ciclo_estado.json'],
        cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    if token:
        return
    _bloqueia(
        'q_net.joblib mudou sem ciclo_estado.json mudar junto.',
        ['O modelo e binario e NAO funde: quem empurrar depois apaga a geracao',
         'do outro em silencio. O token e o unico registro de quem treinou.',
         '',
         'Se o treino foi de verdade, o ciclo deve estar registrado no token.',
         'Se foi experimento local, nao empurre o modelo.'])


def main() -> int:
    for linha in sys.stdin:
        partes = linha.split()
        if len(partes) < 4:
            continue
        _, local_sha, _, remote_sha = partes[:4]
        if set(local_sha) == {'0'}:
            continue
        if set(remote_sha) == {'0'}:
            continue
        checa_modelo_com_token(remote_sha, local_sha)

    checa_index_de_logs()
    checa_corpus()

    if falhas:
        print('')
        print('Para pular esta checagem uma vez (nao recomendado): git push --no-verify')
        print('')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
