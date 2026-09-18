#!/usr/bin/env python
"""As duas maquinas em UM comando de cada lado: `entrega` e `chega`.

O QUE O USUARIO PEDIU (18/09/2026)
----------------------------------
    "a ideia e pegar os treinos de uma maquina e os logs, e quando a outra
     maquina for atualizar, tb atualizar os logs e os treinos"

O problema nunca foi transporte de UM arquivo -- foi **completude**. Sempre
faltava um pedaco, e sempre em silencio:

  - o corpus nao viajava (era zip entregue a mao; quebrou em 18/09 quando o
    usuario chegou ao trabalho sem conexao com a outra maquina);
  - os logs viajavam, mas so os que alguem lembrou de `git add` (13 arquivos
    de 17/09 ficaram so na Arthur_PC, com o index apontando pro vazio);
  - e quem puxava nao tinha um passo obrigatorio que dissesse "faltou isto".

Entao sao dois verbos, e cada um cobre TUDO:

    python sincroniza.py entrega    # antes de passar a vez
    python sincroniza.py chega      # ao sentar na outra maquina

POR QUE ZIPAR OS LOGS NAO ENTRA AQUI (medido em 18/09)
------------------------------------------------------
    logs/ em disco (working tree) : 27,0 MB
    logs/ dentro do .git          :  1,7 MB
    tar.gz dos mesmos arquivos    :  1,7 MB

**O git ja comprime os logs na mesma taxa que o zip daria.** Comprimir nao
economizaria um byte e quebraria as 11 ferramentas que leem `logs/parsed/*.json`
direto, alem de custar diff, grep e merge por arquivo. O corpus precisou de
fatias por ser UM arquivo de 465 MB; os logs ja sao muitos arquivos pequenos,
que e o formato que o git faz bem.

O QUE ESTE ARQUIVO NAO FAZ
--------------------------
Nao commita e nao empurra. O `pre-push` exige bloco de `HANDOFF.md`/`TODO.md`,
e isso e trabalho de sessao, nao de script. `entrega` deixa tudo preparado e
diz o que falta.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
REPO = RAIZ.parent
INDEX = RAIZ / 'logs' / 'index.json'


def _git(*args: str, checar: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=REPO, capture_output=True,
                          text=True, check=checar)


def logs_referenciados_fora_do_git() -> tuple[list[str], list[str]]:
    """Os arquivos que o `index.json` referencia e o git NAO tem.

    FONTE UNICA desta pergunta: o hook `verifica_push.py` importa daqui em vez
    de reimplementar (REGRA_SEM_DUPLICACAO). Devolve dois grupos, porque sao
    situacoes diferentes:

      - `por_versionar`: estao no DISCO e fora do git -> um `git add` resolve;
      - `so_na_outra`:   nao estao nem no disco -> ficaram na outra maquina, e
                         daqui nao ha o que versionar.
    """
    if not INDEX.exists():
        return [], []
    try:
        entradas = json.loads(INDEX.read_text(encoding='utf-8'))
    except Exception:
        return [], []

    rastreados = set(_git('ls-files').stdout.splitlines())
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
            (por_versionar if (REPO / caminho).exists() else so_na_outra).append(caminho)
    return sorted(set(por_versionar)), sorted(set(so_na_outra))


def _corpus():
    sys.path.insert(0, str(RAIZ))
    import corpus_git
    return corpus_git


def cmd_chega(pular_pull: bool) -> int:
    print('== CHEGA: trazendo logs e treino da outra maquina ==')
    print('')

    if not pular_pull:
        pendente = _git('status', '--porcelain').stdout.strip()
        if pendente:
            print('Ha mudanca local nao commitada -- o pull fica por sua conta:')
            for ln in pendente.splitlines()[:10]:
                print(f'  {ln}')
            print('')
            print('  (rode com --sem-pull depois de resolver)')
            return 1
        print('[1/3] git pull --ff-only')
        r = _git('pull', '--ff-only')
        saida = (r.stdout + r.stderr).strip()
        for ln in saida.splitlines()[-6:]:
            print(f'      {ln}')
        if r.returncode != 0:
            print('')
            print('PAROU: o pull nao foi fast-forward. Resolva a divergencia antes.')
            return 1
    else:
        print('[1/3] pull PULADO (--sem-pull)')

    print('')
    print('[2/3] corpus: aplicando as fatias que vieram')
    cg = _corpus()
    falta = cg.pendentes()
    if falta:
        cg.cmd_importa()
    else:
        print('      nada pendente (corpus ja em dia)')

    print('')
    print('[3/3] logs: conferindo o que o index referencia')
    _, so_na_outra = logs_referenciados_fora_do_git()
    rastreados = len([l for l in _git('ls-files', 'scriptis_da_ia/logs/').stdout.splitlines()])
    print(f'      {rastreados} arquivos de log no git')
    if so_na_outra:
        print(f'      ATENCAO: {len(so_na_outra)} referenciados pelo index NAO chegaram')
        for c in so_na_outra[:6]:
            print(f'        {c}')
        if len(so_na_outra) > 6:
            print(f'        ... e mais {len(so_na_outra) - 6}')
        print('      Quem os tem precisa rodar `sincroniza.py entrega` e empurrar.')

    print('')
    print('PRONTO. Corpus e logs em dia com o que esta no git.')
    return 0


def cmd_entrega() -> int:
    print('== ENTREGA: publicando logs e treino desta maquina ==')
    print('')

    print('[1/2] corpus: exportando o que so existe aqui')
    cg = _corpus()
    locais = cg._conta_por_origem(cg.CORPUS, comprimido=False)
    faltando = cg._a_exportar(locais, cg._nas_fatias())
    if faltando:
        antes = {f.name for f in cg._fatias_no_git()}
        cg.cmd_exporta(None)
        # Por DIFERENCA: a fatia nova e a que nao existia antes da exportacao.
        for nome in sorted({f.name for f in cg._fatias_no_git()} - antes):
            caminho = f'scriptis_da_ia/metrics/q_alvos/{nome}'
            _git('add', caminho)
            print(f'      versionado: {caminho}')
    else:
        print('      nada a exportar (corpus ja todo no git)')

    print('')
    print('[2/2] logs: versionando o que o index referencia e o git nao tem')
    por_versionar, so_na_outra = logs_referenciados_fora_do_git()
    if por_versionar:
        # Explicito, um a um: a regra do projeto PROIBE `git add -A`.
        for c in por_versionar:
            _git('add', c)
        print(f'      {len(por_versionar)} arquivo(s) versionados')
        for c in por_versionar[:8]:
            print(f'        {c}')
        if len(por_versionar) > 8:
            print(f'        ... e mais {len(por_versionar) - 8}')
    else:
        print('      nada a versionar (todo log do index ja esta no git)')

    if so_na_outra:
        print('')
        print(f'      NOTA: {len(so_na_outra)} referencias do index apontam pra arquivo')
        print('      que nao esta nem no disco -- ficaram na outra maquina.')

    preparado = _git('diff', '--cached', '--name-only').stdout.strip()
    print('')
    if not preparado:
        print('Nada novo para entregar.')
        return 0
    print(f'PREPARADO: {len(preparado.splitlines())} arquivo(s) no stage.')
    print('')
    print('Falta VOCE (o script nao faz, e de proposito):')
    print('  1. escrever o bloco no HANDOFF.md e o resumo no TODO.md')
    print('  2. git commit')
    print('  3. git push   (o hook confere corpus, index e token)')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')
    c = sub.add_parser('chega', help='pull + importa corpus + confere logs')
    c.add_argument('--sem-pull', action='store_true', help='nao roda git pull')
    sub.add_parser('entrega', help='exporta corpus + versiona logs novos')
    args = ap.parse_args()

    if args.cmd == 'entrega':
        return cmd_entrega()
    if args.cmd == 'chega':
        return cmd_chega(args.sem_pull)
    ap.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
