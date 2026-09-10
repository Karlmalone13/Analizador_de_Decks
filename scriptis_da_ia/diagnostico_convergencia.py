"""Diagnostico do bloco 756: quando as duas irmas da mesma decisao produzem
o MESMO vetor de `state_features`, a posicao e de fato identica?

Motivo (achado ao cruzar `metrics/pares_cf_v2.jsonl`): dos 35 pares em que o
estado pos-linha CONVERGE (0 de 32 features diferem), 10 tem desfecho
DIFERENTE. Duas explicacoes possiveis, com correcoes OPOSTAS:

  (A) a linha convergiu mesmo -- e a mesma posicao, e a diferenca de desfecho
      e ruido de RNG (os ramos dessincronizam o fluxo aleatorio depois da
      decisao forcada). Nesse caso esses rotulos sao RUIDO e treinar neles
      PIORA o modelo.
  (B) as 32 features -- que sao so contagens e agregados, sem NENHUMA
      identidade de carta -- acharam duas posicoes realmente diferentes.
      Nesse caso e sinal legitimo, e a correcao e enriquecer FEATURE, nao
      mudar o ponto de avaliacao (que era a proposta do bloco 755).

Este script nao decide nada: so mede qual das duas e verdade, comparando uma
impressao digital RICA (codigos de carta na mao/campo/trash, DON anexado por
personagem, vida, tamanho de deck) das duas irmas no MESMO ponto.

Barato de proposito: o seam captura as DUAS irmas numa unica partida, e a
partida para assim que a decisao alvo acontece -- nao precisa de desfecho.

Uso: python diagnostico_convergencia.py --pares 60 --workers 4
"""
from __future__ import annotations
import argparse, json, random, sys
from concurrent.futures import ProcessPoolExecutor

from gerar_pares_contrafactuais import _um_ramo


def _uma_amostra(task):
    i, seed, decisao_alvo = task
    from gerar_selfplay_dataset import _load_deck_list
    deck_list = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(deck_list)), 2)
    _ca, deck_a = deck_list[ia]
    _cb, deck_b = deck_list[ib]
    try:
        r = _um_ramo(deck_a, deck_b, seed, decisao_alvo, 0,
                     quer_fp=True, parar_apos_decisao=True)
    except Exception as e:
        return {'descartado': f'erro: {str(e)[:70]}'}
    if not r['forcou']:
        return {'descartado': 'decisao alvo nao existiu'}
    pos, fp = r.get('pos') or [], r.get('fp') or []
    if len(pos) != 2 or any(v is None for v in pos):
        return {'descartado': 'sem estado pos-linha das duas irmas'}
    if len(fp) != 2 or any(v is None for v in fp):
        return {'descartado': 'sem fingerprint das duas irmas'}
    return {'seed': seed, 'leader': r['leader'], 'candidatas': r['candidatas'],
            'pos': pos, 'fp': fp}


def _difs_fp(a, b):
    """Quais campos da impressao digital diferem entre as duas irmas."""
    difs = []
    for lado in ('eu', 'opp'):
        for campo in a[lado]:
            if a[lado][campo] != b[lado][campo]:
                difs.append(f'{lado}.{campo}')
    return difs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pares', type=int, default=60)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--seed', type=int, default=909)
    ap.add_argument('--decisao-max', type=int, default=12)
    ap.add_argument('--saida', default='metrics/diag_convergencia.jsonl')
    a = ap.parse_args()

    rng = random.Random(a.seed)
    tasks = [(i, a.seed * 1_000_003 + i, rng.randrange(a.decisao_max))
             for i in range(a.pares)]

    bons, descartes = [], 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(_uma_amostra, tasks):
            if r is None or 'descartado' in r:
                descartes += 1
                continue
            bons.append(r)

    with open(a.saida, 'w', encoding='utf-8') as f:
        for r in bons:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print(f'amostras validas: {len(bons)}   descartadas: {descartes}')
    if not bons:
        return

    conv = [r for r in bons if r['pos'][0] == r['pos'][1]]
    print(f'estado CONVERGIDO (0 de 32 features diferem): {len(conv)} '
          f'({len(conv)/len(bons):.1%})')
    print()
    print('=== A PERGUNTA: dos convergidos, quantos sao a MESMA posicao? ===')
    iguais = [r for r in conv if not _difs_fp(*r['fp'])]
    difs = [r for r in conv if _difs_fp(*r['fp'])]
    print(f'  (A) posicao IDENTICA tambem na impressao digital rica: '
          f'{len(iguais)} ({len(iguais)/max(len(conv),1):.1%})')
    print(f'  (B) posicao DIFERENTE achatada pelas 32 features:      '
          f'{len(difs)} ({len(difs)/max(len(conv),1):.1%})')
    if difs:
        from collections import Counter
        c = Counter()
        for r in difs:
            for d in _difs_fp(*r['fp']):
                c[d] += 1
        print()
        print('  campos que diferem (quantos pares cada um):')
        for k, v in c.most_common():
            print(f'    {k:<18} {v:>4}  ({v/len(difs):.0%} dos casos B)')
    print()
    print(f'saida: {a.saida}')


if __name__ == '__main__':
    main()
