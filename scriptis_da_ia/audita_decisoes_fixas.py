"""INVENTARIO de decisoes FIXAS -- tudo que escolhe entre alternativas por
regra de uma linha, sem passar por busca nem por modelo (bloco 774).

Pedido do usuario: *"Faca uma busca e verifique tudo que for fixo e exija
decisao, o ML tem que treinar"*.

Motivo: ja foi verificado caso a caso que o ML alcanca APENAS a acao de topo
(jogar/atacar/ativar/anexar DON/passar). Alvo de efeito, defesa (blocker e
counter), carta do search e revivencia do trash sao todos regra fixa. Isto
aqui procura o RESTO -- o que ainda nao foi olhado.

O que conta como "decisao fixa": escolher UM entre VARIOS candidatos usando
`max`/`min`/`sorted`/`[0]` com uma chave heuristica. Nao conta filtro de
elegibilidade (isso e regra do jogo, nao escolha).

Saida: por FUNCAO, pra dar o mapa de onde o ML precisaria entrar.
"""
from __future__ import annotations
import re
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARQS = [RAIZ / 'optcg_engine' / 'decision_engine.py',
        RAIZ / 'optcg_engine' / 'rules_facade.py',
        RAIZ / 'optcg_engine' / 'sim_bridge.py']

# Escolha de UM entre VARIOS por chave heuristica.
PADROES = [
    (r'\bmax\([^)]*key\s*=', 'max(key=)'),
    (r'\bmin\([^)]*key\s*=', 'min(key=)'),
    (r'\bsorted\([^)]*key\s*=', 'sorted(key=)'),
    (r'choose_highest_board_value\(', 'choose_highest_board_value'),
    (r'choose_lowest_board_value\(', 'choose_lowest_board_value'),
]

# Coisas que indicam que NAO e escolha de carta (ordenar numero, log, etc).
RUIDO = re.compile(r'#|print\(|log|debug|\.items\(\)|\.values\(\)|enumerate\(|'
                   r'reverse=True\)\[:0\]|key=lambda [a-z]+: -?[a-z_]+\[0\]')


def func_de(linhas, i):
    """Metodo de topo (indentacao 4) que contem a linha i (1-based)."""
    for j in range(i - 1, -1, -1):
        m = re.match(r'^    def (\w+)', linhas[j])
        if m:
            return m.group(1)
        if re.match(r'^def (\w+)', linhas[j]):
            return re.match(r'^def (\w+)', linhas[j]).group(1)
    return '?'


def main():
    por_func = defaultdict(list)
    total = 0
    for arq in ARQS:
        if not arq.exists():
            continue
        linhas = arq.read_text(encoding='utf-8').split('\n')
        for i, l in enumerate(linhas, start=1):
            if RUIDO.search(l):
                continue
            for pad, nome in PADROES:
                if re.search(pad, l):
                    # so interessa se mexe em CARTA/alvo
                    if not re.search(r'card|char|alvo|target|cand|blocker|'
                                     r'counter|trash|hand|deck|fuel|opcoes|'
                                     r'escolh', l, re.I):
                        continue
                    por_func[(arq.name, func_de(linhas, i))].append(
                        (i, nome, l.strip()[:96]))
                    total += 1
                    break

    print('INVENTARIO DE DECISOES FIXAS (escolha por regra, sem busca/modelo)')
    print('=' * 78)
    print('{} ocorrencias em {} funcoes\n'.format(total, len(por_func)))
    for (arqn, fn), ocs in sorted(por_func.items(), key=lambda kv: -len(kv[1])):
        print('[{}]  {}   ({} ocorrencia{})'.format(
            arqn, fn, len(ocs), 's' if len(ocs) > 1 else ''))
        for i, nome, txt in ocs[:4]:
            print('    L{:<6} {:<26} {}'.format(i, nome, txt))
        if len(ocs) > 4:
            print('    ... e mais {}'.format(len(ocs) - 4))
        print('')


if __name__ == '__main__':
    main()
