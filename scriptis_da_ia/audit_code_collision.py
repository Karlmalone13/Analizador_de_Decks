# -*- coding: utf-8 -*-
"""COLISAO de codigo de carta: mesmo codigo, cartas DIFERENTES (bloco 747).

POR QUE EXISTE, e por que `audit_game_code_divergence.py` nao bastava.

Aquele script compara os NOMES DE ARQUIVO das artes que o jogo instala
contra os codigos do banco. Ele acha duas coisas:

  - codigo do jogo AUSENTE do banco -> a carta vira "copia cega": sem
    efeito, sem custo, sem nome. Falha ALTA e visivel.
  - numeracao +-1 no mesmo set -> candidato a alias.

Ele NAO acha COLISAO: o codigo existe nos DOIS lados e aponta pra cartas
DIFERENTES. Essa e a classe pior, porque falha em SILENCIO -- o motor
raciocina a partida inteira com a carta errada e nada acusa.

ACHADO REAL QUE MOTIVOU (30/08, jogo 1.42c.22). O log diz:

    [You] Leader is Kaido ["OP17-058">OP17-058]

O banco tem em `OP17-058` um EVENTO ("There's No Authority in the World
That Lasts Forever!!!"), byte a byte igual ao `OP17-055` -- uma linha
DUPLICADA -- e o lider Kaido de verdade esta em `OP17-059`.

Consequencia medida: o motor jogou achando que o lider tinha
`[Main] You may rest 1 of your DON!!: ... gains [Unblockable]`, que NAO
tem limite por turno. Ativou em 100% dos seus turnos (3, 5, 7, 9, 11) e
ficou sem DON. O usuario reportou como "o Kaido usa o efeito do lider
toda hora e acaba ficando sem don". **Nao era decisao ruim: era a carta
errada.** O Kaido real e `[When Attacking]/[On Your Opponent's Attack]
[Once Per Turn] DON!!-1: -2000 num Personagem do oponente`.

FONTE DE VERDADE: os combat logs bancados, que imprimem
`Nome ["CODIGO">CODIGO]`. E o que o jogo afirma em TEMPO DE EXECUCAO --
mais autoritativo que nome de arquivo, e cobre toda carta ja vista em
partida. Nao supoe nada.

Uso:
    python audit_code_collision.py
"""
import csv
import glob
import os
import re
import sys
from collections import defaultdict

# "Nome da carta [\"CODIGO\">CODIGO]" -- o log prefixa acoes ("Deploy X",
# "Attach 1 Don to X", "Trash X"), entao o nome vem sujo e a comparacao
# abaixo tolera prefixo.
RE_PAR = re.compile(r'([^\[\]"\n]{2,70}?) \["([A-Z0-9][A-Za-z0-9-]+)"')


def limpa(texto):
    return re.sub(r'[^a-z0-9]', '', (texto or '').lower())


def nomes_do_jogo(dir_raw):
    """{codigo: {nomes que o jogo usou}} a partir dos combat logs."""
    visto = defaultdict(set)
    for caminho in sorted(glob.glob(os.path.join(dir_raw, '*.log'))):
        try:
            txt = open(caminho, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for m in RE_PAR.finditer(txt):
            visto[m.group(2)].add(m.group(1).strip())
    return visto


def bate(nome_banco, nomes_jogo):
    """O nome do banco aparece em ALGUM dos nomes que o jogo usou?"""
    alvo = limpa(nome_banco)
    if not alvo:
        return True
    for n in nomes_jogo:
        j = limpa(n)
        if not j:
            continue
        # prefixo de acao ("deploykaido" contem "kaido"); ou o banco usa
        # nome mais longo que o jogo ("missbuckinghamstussy" x "stussy")
        if alvo in j or j in alvo:
            return True
        if len(alvo) >= 8 and alvo[:8] in j:
            return True
        if len(j) >= 6 and j[-6:] in alvo:
            return True
    return False


def main():
    banco = {r['id']: r for r in csv.DictReader(
        open('cards_rows.csv', encoding='utf-8'))}
    visto = nomes_do_jogo(os.path.join('logs', 'raw'))
    print(f'{len(visto)} codigos observados em partida | {len(banco)} no banco\n')

    colisoes, ausentes = [], []
    for cod in sorted(visto):
        r = banco.get(cod)
        if r is None:
            ausentes.append((cod, sorted(visto[cod])[:2]))
        elif not bate(r['card_name'], visto[cod]):
            colisoes.append((cod, sorted(visto[cod])[:2], r['card_name'],
                             r.get('card_type', '')))

    print(f'--- COLISOES: mesmo codigo, carta DIFERENTE ({len(colisoes)}) ---')
    print('    (falha SILENCIOSA -- o motor usa a carta errada)')
    for cod, nj, nb, tipo in colisoes:
        print(f'  {cod:12s} jogo={str(nj)[:46]:46s}')
        print(f'  {"":12s} banco="{nb[:46]}" [{tipo}]')
    if not colisoes:
        print('  nenhuma')

    print(f'\n--- codigos vistos em partida e AUSENTES do banco ({len(ausentes)}) ---')
    print('    (falha ALTA -- carta vira copia cega)')
    for cod, nj in ausentes[:15]:
        print(f'  {cod:12s} jogo={str(nj)[:52]}')
    if len(ausentes) > 15:
        print(f'  ... e mais {len(ausentes) - 15}')
    if not ausentes:
        print('  nenhum')

    # Duplicatas exatas dentro do mesmo set: foi o que DESLOCOU o Kaido.
    por_set = defaultdict(lambda: defaultdict(list))
    for cod, r in banco.items():
        m = re.match(r'^([A-Z]+\d+)-(\d+)', cod)
        if m:
            chave = (r['card_name'], r.get('card_type'), (r.get('card_text') or '')[:60])
            por_set[m.group(1)][chave].append(int(m.group(2)))
    # >1 NUMERO DISTINTO. Artes paralelas (`OP01-029_p1`) compartilham o
    # numero base e nao sao deslocamento -- so ruido se contadas.
    dups = [(s, sorted(set(nums)), k[0], k[1]) for s, d in por_set.items()
            for k, nums in d.items() if len(set(nums)) > 1]
    print(f'\n--- linhas DUPLICADAS no banco dentro do mesmo set ({len(dups)}) ---')
    print('    (uma duplicata desloca a numeracao e cria colisao)')
    for s, nums, nome, tipo in sorted(dups):
        print(f'  {s}: {sorted(nums)}  [{tipo}] {nome[:50]}')
    if not dups:
        print('  nenhuma')

    return 1 if (colisoes or dups) else 0


if __name__ == '__main__':
    sys.exit(main())
