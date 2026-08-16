"""
A/B DESCARTAVEL do desconto de valor esperado do bloco 551
(`_generate_attach_don_actions`: `valor *= 0.35` quando o poder final, ja
com o DON pago, ainda fica abaixo de `alvo + counter provavel`).

Por que existe: eu nao consigo afirmar que 0.35 e o numero certo -- so que
1.0 (o de antes) estava errado, porque herdava o valor CHEIO de um ataque
previsto pra falhar. A unica forma honesta de saber se a mudanca ajuda ou
atrapalha e medir nos DOIS lados, no MESMO codigo, com as MESMAS seeds --
e em varios arquetipos, nao so no Imu (pedido do usuario, 15/08: "jogar so
de imu nao e ruim nao?").

Faz tudo sozinho pra eliminar dois erros que ja aconteceram nesta sessao:
1. rodar o gauntlet enquanto as flags de calibragem eram ligadas/desligadas
   pro commit (resultado contaminado, teve que ser descartado);
2. esquecer de restaurar o fator no arquivo depois do teste.
O `finally` garante a restauracao mesmo se o script morrer no meio.

Uso:
    python ab_desconto_ataque.py --seeds 15 --workers 4
"""
import argparse
import json
import os
import re
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
ALVO = os.path.join(AQUI, 'optcg_engine', 'decision_engine.py')
FATOR_FIX = '0.35'
LINHA_RE = re.compile(r'^(\s*)valor \*= [0-9.]+(.*)$', re.M)


def _ler() -> str:
    with open(ALVO, encoding='utf-8') as f:
        return f.read()


def _escrever(txt: str) -> None:
    with open(ALVO, 'w', encoding='utf-8') as f:
        f.write(txt)


def _set_fator(valor: str) -> None:
    txt = _ler()
    novo, n = LINHA_RE.subn(rf'\g<1>valor *= {valor}\g<2>', txt)
    if n != 1:
        raise SystemExit(f'esperava achar 1 linha `valor *= X`, achei {n} -- '
                         f'o fix do bloco 551 mudou de forma? abortando sem escrever')
    _escrever(novo)


def fator_atual() -> str:
    """Fator que esta AGORA no arquivo -- pra conferir que o A/B nao deixou
    lixo pra tras.

    Existe por um erro REAL (16/08): matei um A/B pela metade, o `finally`
    que restaura nao rodou, e o arquivo ficou com `valor *= 1.0` -- ou seja,
    o fix DESLIGADO. Pior: eu 'verifiquei' procurando o marcador
    `AB-TEST-BASELINE`, que este script nunca escreve (ele troca so o
    numero), e o grep deu 0, me dando confianca falsa. O servidor foi
    reiniciado assim e o usuario testou sem o fix. Quem pegou foi o teste
    do smoke_fast (14 -> 15 falhas). Confira SEMPRE o numero, nunca um
    marcador.
    """
    m = LINHA_RE.search(_ler())
    return m.group(0).split('*=')[1].strip() if m else '(nao encontrado)'


def _rodar_painel(seeds: int, workers: int) -> dict:
    cmd = [sys.executable, os.path.join(AQUI, 'gauntlet_matchup.py'),
           '--painel', '--seeds', str(seeds), '--workers', str(workers)]
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    r = subprocess.run(cmd, cwd=AQUI, text=True, capture_output=True, env=env)
    if r.returncode:
        raise SystemExit(f'gauntlet falhou:\n{r.stderr[-2000:]}')
    print(r.stdout)
    with open(os.path.join(AQUI, 'metrics', 'gauntlet_painel.json'), encoding='utf-8') as f:
        return {d['deck']: d for d in json.load(f)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seeds', type=int, default=15)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()

    original = _ler()
    try:
        print('########## RODADA A: SEM o desconto (baseline, fator 1.0) ##########')
        _set_fator('1.0')
        base = _rodar_painel(args.seeds, args.workers)

        print(f'########## RODADA B: COM o desconto (fator {FATOR_FIX}) ##########')
        _set_fator(FATOR_FIX)
        fix = _rodar_painel(args.seeds, args.workers)
    finally:
        # Restaura o arquivo EXATAMENTE como estava, aconteca o que acontecer.
        # ATENCAO: um kill -9 no processo NAO executa este bloco -- se o A/B
        # for interrompido a forca, CONFIRA `fator_atual()` antes de subir o
        # servidor (erro real de 16/08, ver docstring de fator_atual).
        _escrever(original)
        print(f'(decision_engine.py restaurado -- fator agora: {fator_atual()})')

    print('=' * 78)
    print('COMPARACAO A/B -- desconto de valor esperado em attach_don')
    print(f'{"Deck":10} {"Arquetipo":16} {"SEM fix":>18} {"COM fix":>18} {"delta":>8}')
    for deck in base:
        b, f = base[deck], fix.get(deck)
        if not f:
            continue
        sb = f'{b["win_rate"]:.1f}% [{b["ic95"][0]:.0f}-{b["ic95"][1]:.0f}]'
        sf = f'{f["win_rate"]:.1f}% [{f["ic95"][0]:.0f}-{f["ic95"][1]:.0f}]'
        delta = f['win_rate'] - b['win_rate']
        # Sobreposicao de IC95 = nao da pra afirmar efeito real
        sobrepoe = not (f['ic95'][0] > b['ic95'][1] or b['ic95'][0] > f['ic95'][1])
        marca = ' (ruido)' if sobrepoe else ' *'
        print(f'{deck:10} {b.get("arquetipo",""):16} {sb:>18} {sf:>18} {delta:+7.1f}{marca}')
    print()
    print('* = intervalos NAO se sobrepoem (efeito provavelmente real).')
    print('(ruido) = intervalos se sobrepoem; a diferenca pode ser so sorte.')
    print()
    print('DON/atk tambem importa: o objetivo do fix e gastar MENOS DON em')
    print('ataque fraco, entao DON/atk caindo sem winrate cair e sinal BOM.')
    print(f'{"Deck":10} {"DON/atk SEM":>12} {"DON/atk COM":>12} {"delta":>8}')
    for deck in base:
        b, f = base[deck], fix.get(deck)
        if not f:
            continue
        print(f'{deck:10} {b["don_por_ataque"]:12.2f} {f["don_por_ataque"]:12.2f} '
              f'{f["don_por_ataque"] - b["don_por_ataque"]:+8.2f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
