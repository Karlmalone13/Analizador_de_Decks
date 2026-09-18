#!/usr/bin/env python
"""Duelo ESPELHO PAREADO da remocao do corte do shortlist (bloco 869).

A PERGUNTA: tirar a heuristica do shortlist (bloco 868) fez o bot GANHAR mais,
ou so fez o modelo enxergar mais?

Sao perguntas diferentes e a segunda ja esta respondida: 69,1% das acoes
geradas eram descartadas, e passou a ser 0,0%. Isto aqui mede a primeira.

COMO (o desenho do bloco 756, nao inventar outro): cada par de partidas roda a
MESMA seed -- portanto o MESMO par de decks e o MESMO embaralhamento -- uma vez
com o lado novo em A e outra em B. **So conta o par em que o mesmo lado vence
dos DOIS lados**; par dividido significa que quem decidiu foi o matchup, nao a
mudanca, e entra como SEM INFORMACAO. E isso que cancela a sorte.

O QUE FICA IGUAL NOS DOIS LADOS, de proposito: o modelo. `value_net_weight=0.0`
nos dois (o peso e LEGADO, default 0.0) e nenhum `q_net_path` setado, entao os
dois consultam o MESMO `q_net.joblib`. **A unica diferenca e o flag** -- sem
isso o duelo mediria modelo, nao a mudanca.

    cd scriptis_da_ia
    python duela_shortlist.py --n 60 --workers 4
"""
from __future__ import annotations

import argparse

import treino_continuo as tc


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n', type=int, default=60,
                    help='partidas (viram n//2 pares espelhados)')
    ap.add_argument('--workers', type=int, default=4,
                    help='o projeto EXIGE escolher explicitamente')
    ap.add_argument('--seed', type=int, default=4242)
    ap.add_argument('--controle-aa', dest='controle_aa', action='store_true',
                    help='A/A: os DOIS lados sem corte. Tem que dar ~50%% -- '
                         'se der o mesmo do teste real, o instrumento esta '
                         'quebrado e o resultado nao vale (regra do bloco 780)')
    args = ap.parse_args()

    # DESAFIANTE = sem corte (o comportamento novo). CAMPEAO = com o corte da
    # regua estatica (o que havia antes do bloco 868).
    extras = {
        'desafiante': {'shortlist_sem_corte': True},
        # BUG CORRIGIDO (bloco 869): estava `not args.controle_aa`, que INVERTE
        # -- na execucao normal dava True e os dois lados ficavam iguais. As
        # duas rodadas sairam identicas (52x2 nas duas) e eu li isso como "o
        # controle reprovou o instrumento", quando o controle e que nunca
        # rodou. O certo e simples: no A/A o campeao fica IGUAL ao desafiante.
        'campeao': {'shortlist_sem_corte': args.controle_aa},
    }
    if args.controle_aa:
        print('!! CONTROLE A/A: os dois lados IGUAIS. Esperado ~50%.')

    print('== DUELO: shortlist SEM corte (desafiante) x COM corte (campeao) ==')
    print(f'   {args.n} partidas -> {max(1, args.n // 2)} pares espelhados, '
          f'seed {args.seed}, {args.workers} workers')
    print('   mesmo q_net nos dois lados; a UNICA diferenca e o flag')
    print('')

    r = tc.duelar(args.n, args.workers, args.seed,
                  peso_camp=0.0, peso_desaf=0.0, pareado=True, extras=extras)

    vit = r.get('vitorias_desafiante', 0)
    der = r.get('derrotas_desafiante', 0)
    dec = vit + der
    print('')
    print('==================== RESULTADO ====================')
    print(f'pares DECIDIDOS      : {dec}')
    print(f'  sem corte venceu   : {vit}')
    print(f'  com corte venceu   : {der}')
    print(f'pares DIVIDIDOS      : {r.get("pares_divididos", 0)}  '
          f'(matchup decidiu, nao a mudanca)')
    if r.get('erros'):
        print(f'erros/empates        : {r.get("erros")}')
    print('')
    if dec == 0:
        print('INCONCLUSIVO: nenhum par decidido. A mudanca nao alterou o')
        print('desfecho de nenhuma partida desta amostra.')
        return 0
    taxa = vit / dec
    low = tc.limite_inferior_wilson(vit, dec)
    print(f'taxa do desafiante   : {taxa:.1%}')
    print(f'Wilson (limite inf.) : {low:.1%}')
    print('')
    if low > 0.50:
        print('VEREDITO: o lado SEM corte e melhor com confianca.')
    elif taxa > 0.50:
        print('VEREDITO: INCONCLUSIVO -- taxa a favor, mas o limite inferior')
        print('de Wilson nao passa de 50%. Amostra pequena demais pra afirmar.')
    else:
        print('VEREDITO: o lado SEM corte NAO se mostrou melhor nesta amostra.')
    print('')
    print('LEMBRETE: isto e AUTO-JOGO. Um vicio COMPARTILHADO e invisivel aqui')
    print('por construcao -- o adversario so pune o que ele proprio sabe')
    print('explorar. Ver a ressalva de escopo no CLAUDE.md.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
