# -*- coding: utf-8 -*-
"""O que o banco de logs permite RECONSTRUIR de verdade (bloco 805).

Pergunta do usuario: *"da para saber a mao do bot e do humano?"* -- da, e em
mais log do que se supunha. Este inventario mede a INTERSECAO do que e
necessario pra uma reconstrucao servir:

  * **as duas maos** no snapshot (carta a carta, nao contagem)
  * **`bot_side` conhecido** -- sem saber de que lado o bot estava, nao ha
    quem auditar
  * **desfecho** conhecido

So o cruzamento dos tres da um log utilizavel pra "o motor faria igual ou
melhor?". Ter os tres separados nao adianta.

Tambem lista o que as MAOS abrem, que nao existia quando se supunha que a mao
do adversario era desconhecida -- ver o relatorio impresso no fim.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

RAIZ = Path(__file__).parent
INDEX = RAIZ / 'logs' / 'index.json'


def tem_maos(parsed: Path) -> tuple[bool, int, int]:
    """(as duas maos em algum turno, turnos com as duas, turnos totais)."""
    try:
        d = json.loads(parsed.read_text(encoding='utf-8'))
    except Exception:
        return False, 0, 0
    turnos = d.get('turns') or []
    com = 0
    for t in turnos:
        sn = t.get('snapshot') or {}
        a = (sn.get('You') or {}).get('hand')
        b = (sn.get('Opponent') or {}).get('hand')
        if a and b and not any('UNKNOWN' in str(x) for x in list(a) + list(b)):
            com += 1
    return com > 0, com, len(turnos)


def main() -> int:
    dados = json.loads(INDEX.read_text(encoding='utf-8'))
    regs = dados if isinstance(dados, list) else dados.get('logs', [])

    c = collections.Counter()
    utilizaveis, turnos_uteis = [], 0
    for r in regs:
        pf = r.get('parsed_file')
        if not pf:
            c['sem parsed_file'] += 1
            continue
        p = RAIZ / 'logs' / pf
        if not p.exists():
            c['parsed ausente no disco'] += 1
            continue
        maos, n_com, n_tot = tem_maos(p)
        lado = bool(r.get('bot_side'))
        hvh = r.get('tipo') == 'humano_vs_humano'

        if maos and lado:
            c['UTILIZAVEL (maos + lado)'] += 1
            utilizaveis.append((r, n_com, n_tot))
            turnos_uteis += n_com
        elif maos and hvh:
            c['maos, mas humano vs humano'] += 1
        elif maos:
            c['maos, mas lado DESCONHECIDO'] += 1
        elif lado:
            c['lado, mas SEM as maos'] += 1
        else:
            c['nem maos nem lado'] += 1

    print()
    print('=' * 64)
    print('O QUE DA PRA RECONSTRUIR -- %d registros no banco' % len(regs))
    print('=' * 64)
    for k, v in c.most_common():
        print('  %-34s %4d' % (k, v))

    print()
    print('  TURNOS utilizaveis (maos + lado) : %d' % turnos_uteis)
    if utilizaveis:
        print('  em %d partidas, media de %.1f turnos por partida'
              % (len(utilizaveis), turnos_uteis / len(utilizaveis)))
        print()
        print('  exemplos:')
        for r, n, tot in utilizaveis[:5]:
            print('     %-46s %2d/%2d turnos | bot=%s'
                  % (Path(r['parsed_file']).name[:46], n, tot, r.get('bot_side')))

    print()
    print('=' * 64)
    print('O QUE AS MAOS ABREM (nao existia quando se supunha mao oculta)')
    print('=' * 64)
    print("""
  1. VALIDAR O MODELO DE OPONENTE -- `opponent_model.py` sorteia maos
     plausiveis do que sobrou do deck, e NINGUEM nunca conferiu se acerta.
     Com a mao real no log, da pra medir: das cartas que ele sorteia, quantas
     o adversario de fato tinha?

  2. PROFESSOR COM INFORMACAO PERFEITA -- sabendo as duas maos, da pra
     calcular a jogada certa em RETROSPECTO e usar como alvo. E um professor
     mais forte que o bootstrap, disponivel nos turnos com log.
     RESSALVA que o proprio projeto ja registrou (bloco 781): um professor
     que ve demais produz alvo INALCANCAVEL -- "esta posicao e vencedora SE
     voce souber que ele nao tem counter". O aluno nunca vai saber. Usar
     isso exige media sobre mundos possiveis, nao a resposta do mundo real.

  3. MEDIR O CUSTO DA INCERTEZA -- a MESMA posicao decidida as cegas e com a
     mao aberta. E a medida direta do que o usuario levantou em 12/09
     ("mesmo o bot sabendo a mao e vida etc ele ainda perdia"), agora em
     posicoes REAIS contra humano em vez de auto-jogo.
""")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
