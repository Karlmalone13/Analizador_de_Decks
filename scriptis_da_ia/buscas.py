"""O QUE APARECEU NAS BUSCAS, e o que o bot escolheu.

Pedido do usuario (29/08): "quero que a telemetria registre as cartas que
aparecem nos searchs, para depois a gente avaliar a escolha e as
possibilidades".

O DADO ja era gravado -- cada candidato de busca vai pro decision log com
`zone: top_deck`, `card_code`, `rank` (posicao na ordem devolvida) e
`rank_key` (a chave que ordenou; o 2o elemento e a avaliacao NEGADA, por
isso aparece como numero negativo). O que faltava era a VISAO: sem ela,
avaliar uma escolha exigia abrir o .jsonl na mao.

Mostra, por busca: quantas cartas o jogo revelou, qual o bot levou, e as
que ficaram -- cada uma com nome/custo/tipo e a nota que o motor deu. E o
suficiente pra discordar da escolha com argumento, que era o objetivo.

Uso:
    python buscas.py                  # sessao mais recente
    python buscas.py <arquivo.jsonl>
"""
import json
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optcg_engine.decision_engine import load_cards_db

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'BOT', 'engine_server', 'logs', 'decisions')


def main():
    if len(sys.argv) > 1:
        caminho = sys.argv[1]
    else:
        arqs = sorted(glob.glob(os.path.join(LOGS, '*.jsonl')), key=os.path.getmtime)
        if not arqs:
            print('nenhum log de decisao em', LOGS)
            return
        caminho = arqs[-1]
    db = load_cards_db('cards_rows.csv')
    print(f'\nsessao: {os.path.basename(caminho)}\n')

    def desc(code):
        r = db.get(code, {})
        nome = str(r.get('name', code))[:26]
        return f"{nome:28} custo={str(r.get('cost','?')):>2} {str(r.get('type',''))[:9]}"

    def nota(cand):
        # rank_key = [bucket, -avaliacao]; devolve a avaliacao "de volta"
        k = cand.get('rank_key') or []
        return -k[1] if len(k) > 1 else None

    n = 0
    for linha in open(caminho, encoding='utf-8'):
        linha = linha.strip()
        if not linha:
            continue
        try:
            d = json.loads(linha)
        except Exception:
            continue
        if d.get('decision_kind') != 'target':
            continue
        vistas = [a for a in (d.get('scored_actions') or [])
                  if a.get('zone') == 'top_deck']
        if len(vistas) < 2:
            continue          # 1 carta so = nao houve escolha
        n += 1
        vistas.sort(key=lambda a: a.get('rank') if a.get('rank') is not None else 999)
        print(f"== busca #{n} (turno {d.get('turn')}) -- {len(vistas)} cartas reveladas ==")
        for i, c in enumerate(vistas):
            marca = '  >> LEVOU  ' if i == 0 else '     deixou '
            v = nota(c)
            print(f"{marca}{desc(c.get('card_code'))}  nota={'' if v is None else f'{v:.0f}'}")
        print()

    if not n:
        print('nenhuma busca com 2+ cartas neste log.')
    else:
        print(f'{n} busca(s) com escolha real.')


if __name__ == '__main__':
    main()
