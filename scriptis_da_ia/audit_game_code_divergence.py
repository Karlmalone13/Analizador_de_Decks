"""
audit_game_code_divergence.py
=============================
Compara os codigos de carta que o SIMULADOR usa com os codigos do banco
(`cards_rows.csv`) e reporta as divergencias.

POR QUE EXISTE
--------------
Ao vivo o bot recebe do jogo o codigo que o JOGO usa. Quando esse codigo nao
existe no banco, a carta vira "copia cega": sem efeito, sem custo, sem nome --
o motor nunca a considera como candidata e nem sabe que ela existe. Nao gera
erro nenhum, so uma carta que some silenciosamente da partida.

Foi assim que 4 copias do Thousand Sunny sumiram do deck real do usuario
(bloco 570): o jogo chama a carta de `ST31-005`, o banco a chama de
`ST31-006` (que e o codigo IMPRESSO na arte -- o banco esta certo).

O jogo ATUALIZA e traz sets novos, entao a lista de divergencias envelhece.
Este script existe pra re-derivar essa lista em vez de mantê-la na mao.
Rode-o depois de cada atualizacao do simulador e leve o resultado para
`ALIASES_DO_SIMULADOR` em `gerar_dbs.py`.

DUAS CLASSES DE ACHADO, com tratamentos DIFERENTES
--------------------------------------------------
1. **Divergencia de identidade** (a mesma carta com codigo diferente nos dois
   lados) -- ex: `ST31-005`/`ST31-006`, ou `St22-012`/`ST22-012` (so a caixa).
   Resolve-se com um alias em `gerar_dbs.py`. O script SUGERE candidatos, mas
   a confirmacao e MANUAL: abra a imagem da carta no jogo e leia o codigo
   impresso na arte. Foi exatamente isso que derrubou o diagnostico inicial
   deste caso -- a suspeita era de que o banco estivesse errado, e a arte
   mostrou que o banco estava certo e o jogo e que renumera.
2. **Carta ausente do banco** (o jogo tem, o banco nao tem NENHUMA
   correspondente) -- ex: os promos P-1xx e varios OP17. Alias nao resolve
   nada aqui: o banco precisa ser atualizado a partir da fonte de cartas.

Uso:
    python audit_game_code_divergence.py
    python audit_game_code_divergence.py --cards-dir "<caminho>/StreamingAssets/Cards"
"""

import argparse
import csv
import os
import re
from pathlib import Path

CSV_PADRAO = Path(__file__).with_name('cards_rows.csv')

# Caminho tipico da instalacao do usuario. E so um DEFAULT -- o script nao
# depende dele (e nem roda em sessao remota/nuvem, onde o jogo nao existe).
CARDS_DIR_PADRAO = (r'E:\Games\OnePieceSimulador\Builds_Windows'
                    r'\OPTCGSim_Data\StreamingAssets\Cards')

# Nome de arquivo que corresponde a uma carta de verdade. Exclui as
# miniaturas (`_small`), o verso, os DON e qualquer outro asset solto.
RE_CODIGO = re.compile(r'^[A-Za-z]+\d*-\d+[a-z]?$')


def codigos_do_jogo(cards_dir: str) -> set[str]:
    achados = set()
    raiz = Path(cards_dir)
    if not raiz.is_dir():
        raise SystemExit(
            f'Pasta de cartas do jogo nao encontrada: {cards_dir}\n'
            'Use --cards-dir, ou rode numa maquina com o simulador instalado.'
        )
    for sub in raiz.iterdir():
        if not sub.is_dir():
            continue
        for arquivo in sub.iterdir():
            nome, ext = os.path.splitext(arquivo.name)
            if ext.lower() not in ('.jpg', '.png'):
                continue
            if nome.endswith('_small') or not RE_CODIGO.match(nome):
                continue
            achados.add(nome)
    return achados


def codigos_do_banco(csv_path: Path) -> set[str]:
    csv.field_size_limit(10 ** 7)
    with open(csv_path, encoding='utf-8') as fh:
        return {linha['id'] for linha in csv.DictReader(fh)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cards-dir', default=CARDS_DIR_PADRAO)
    ap.add_argument('--csv', default=str(CSV_PADRAO))
    args = ap.parse_args()

    jogo = codigos_do_jogo(args.cards_dir)
    banco = codigos_do_banco(Path(args.csv))
    print(f'Cartas no jogo: {len(jogo)}   |   codigos no banco: {len(banco)}')
    print()

    so_jogo = sorted(jogo - banco)
    # Compara so os sets que o jogo REALMENTE tem -- senao todo set que o
    # simulador ainda nao recebeu apareceria como divergencia falsa.
    sets_do_jogo = {c.split('-')[0].upper() for c in jogo}
    so_banco = sorted(c for c in banco - jogo
                      if c.split('-')[0].upper() in sets_do_jogo and '_' not in c)

    # Candidatos a ALIAS: pares que batem ignorando a caixa, ou que ficam
    # a 1 de distancia no numero dentro do mesmo set. Heuristica de TRIAGEM
    # -- confirme lendo o codigo impresso na arte antes de criar o alias.
    print('--- Candidatos a ALIAS (mesma carta, codigo diferente) ---')
    por_caixa = {c.upper(): c for c in so_banco}
    candidatos = []
    for c in so_jogo:
        gemeo = por_caixa.get(c.upper())
        if gemeo and gemeo != c:
            candidatos.append((c, gemeo, 'caixa diferente'))
            continue
        m = re.match(r'^([A-Za-z]+\d*)-(\d+)$', c)
        if not m:
            continue
        prefixo, num = m.group(1).upper(), int(m.group(2))
        for delta in (1, -1):
            vizinho = f'{prefixo}-{num + delta:03d}'
            if vizinho in so_banco:
                candidatos.append((c, vizinho, f'numero {delta:+d} no mesmo set'))
                break
    if candidatos:
        for jogo_code, banco_code, motivo in candidatos:
            print(f'  {jogo_code:<14} -> {banco_code:<14} ({motivo})')
        print()
        print('  CONFIRME cada um abrindo a arte da carta no jogo e lendo o')
        print('  codigo impresso, e so entao adicione a ALIASES_DO_SIMULADOR')
        print('  em gerar_dbs.py. A arte manda; o nome do arquivo nao.')
    else:
        print('  nenhum.')
    print()

    ja_cobertos = {c for c, _, _ in candidatos}
    ausentes = [c for c in so_jogo if c not in ja_cobertos]
    print(f'--- Cartas do jogo AUSENTES do banco ({len(ausentes)}) ---')
    print('  (alias nao resolve: o banco precisa ser atualizado na fonte)')
    por_set: dict[str, list[str]] = {}
    for c in ausentes:
        por_set.setdefault(c.split('-')[0].upper(), []).append(c)
    for s, lista in sorted(por_set.items()):
        print(f'  {s}: {len(lista)}  ({", ".join(lista[:6])}'
              f'{", ..." if len(lista) > 6 else ""})')
    print()

    sobrando = [c for c in so_banco if c not in {b for _, b, _ in candidatos}]
    print(f'--- Codigos do banco sem arquivo no jogo ({len(sobrando)}) ---')
    print('  (esperado para reprints/variantes que o simulador nao carrega)')
    for c in sobrando:
        print(f'  {c}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
