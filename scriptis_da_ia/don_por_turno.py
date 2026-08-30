"""ONDE O DON FOI PARAR, turno a turno.

Responde a pergunta direta do usuario (29/08): "da pra saber com o que o
DON foi usado?". Ate hoje a resposta era "quase" -- o log tinha o estado
de DON antes de cada decisao e a acao escolhida, mas o CUSTO nao era
gravado, entao so dava pra diferenciar `active_don` entre decisoes
consecutivas. E como o ledger e `_before`, a diferenca aparecia na linha
SEGUINTE: a atribuicao saia deslocada em uma acao.

Agora cada acao grava `don_cost` (attach_don = quantidade; play =
`effective_hand_play_cost`; activate = custos `rest_don`), entao este
relatorio nao infere nada -- so soma o que ficou registrado.

`attack` aparece com custo 0 de proposito: ao vivo o DON que impulsiona um
ataque entra por uma acao `attach_don` PROPRIA, ja contabilizada.

Uso:
    python don_por_turno.py                 # sessao mais recente
    python don_por_turno.py <arquivo.jsonl>
"""
import json
import os
import sys
import glob
from collections import defaultdict

LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'BOT', 'engine_server', 'logs', 'decisions')


def main():
    if len(sys.argv) > 1:
        caminho = sys.argv[1]
    else:
        arqs = sorted(glob.glob(os.path.join(LOGS, '*.jsonl')), key=os.path.getmtime)
        if not arqs:
            print('nenhum log de decisao encontrado em', LOGS)
            return
        caminho = arqs[-1]
    print(f'sessao: {os.path.basename(caminho)}\n')

    turnos = defaultdict(list)
    reserva_por_turno = {}
    for linha in open(caminho, encoding='utf-8'):
        linha = linha.strip()
        if not linha:
            continue
        try:
            d = json.loads(linha)
        except Exception:
            continue
        if d.get('decision_kind') != 'main':
            continue
        t = d.get('turn')
        led = d.get('resource_ledger_before') or {}
        ch = d.get('chosen_action') or {}
        turnos[t].append({
            'tipo': ch.get('type'), 'carta': ch.get('card_code'),
            'custo': ch.get('don_cost'), 'ativo': led.get('active_don'),
        })
        if 'don_reserva' in led and t not in reserva_por_turno:
            reserva_por_turno[t] = led

    if not turnos:
        print('nenhuma decisao de main neste log.')
        return

    tem_custo = any(a['custo'] is not None for aa in turnos.values() for a in aa)
    if not tem_custo:
        print('*** Este log e ANTERIOR a instrumentacao de `don_cost`. ***')
        print('*** Sem ele, "no que o DON foi gasto" so sai por diferenca ***')
        print('*** de `active_don`, com atribuicao deslocada em 1 acao.   ***\n')

    total_por_tipo = defaultdict(int)
    for t in sorted(turnos, key=lambda x: (x is None, x)):
        acoes = turnos[t]
        led = reserva_por_turno.get(t) or {}
        cab = f'== turno {t} =='
        if led:
            cab += (f"  DON ativo={led.get('active_don')}"
                    f" reservado={led.get('don_reserva')}"
                    f" (teto={led.get('don_reserva_teto')},"
                    f" uso reativo={led.get('don_reserva_tem_uso')})"
                    f" usavel={led.get('don_usavel')}")
        print(cab)
        gasto = 0
        for a in acoes:
            c = a['custo']
            if c:
                gasto += c
                total_por_tipo[a['tipo']] += c
            marca = f"{c} DON" if c is not None else "?"
            if a['tipo']:
                print(f"   {str(a['tipo']):11} {str(a['carta'] or ''):12} -> {marca}")
        print(f"   {'':11} {'':12}    TOTAL do turno: {gasto} DON\n")

    print('== para onde o DON foi, na partida ==')
    tot = sum(total_por_tipo.values()) or 1
    for tipo, v in sorted(total_por_tipo.items(), key=lambda kv: -kv[1]):
        print(f'   {str(tipo):12} {v:4} DON  ({100*v/tot:.0f}%)')


if __name__ == '__main__':
    main()
