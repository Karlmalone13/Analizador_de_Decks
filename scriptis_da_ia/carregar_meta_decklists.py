"""
carregar_meta_decklists.py — popula a tabela `meta_decklists` (Supabase)
=========================================================================
Le `decklists_raw.csv` (saida de `coletar_dados_optcg.py`, decklists reais
de torneio do Limitless TCG) e insere cada deck na tabela `meta_decklists`,
que e a fonte de OPONENTES do simulador do front (`POST /simulate` ->
`simulation_worker.run_simulation_job` -> `db.list_meta_decklists`).

POR QUE EXISTE
--------------
Achado 05/09/2026: os dois caminhos que simulam partidas usavam fontes de
oponente DIFERENTES --

  /hand-stats  -> le `decklists_raw.csv` direto (193 decks disponiveis)
  /simulate    -> le a tabela `meta_decklists` (tinha so 6 decks)

Com 6 oponentes, o winrate por confronto do `/simulate` vinha de poucas
partidas e a margem de erro ficava larga. O dado ja existia no repo; so
nunca tinha sido carregado no banco.

USO
---
    python carregar_meta_decklists.py --dry-run     # mostra o que faria
    python carregar_meta_decklists.py               # insere de verdade
    python carregar_meta_decklists.py --limite 50   # so os N primeiros

Idempotente por `source_url`: um deck ja presente na tabela e PULADO, entao
rodar de novo depois de recoletar so acrescenta o que e novo.
"""
import argparse
import asyncio
import os

import pandas as pd

import db
from optcg_engine.decision_engine import load_cards_db

MIN_CARTAS_DECK = 40   # mesmo piso usado por hand-stats/simulation_worker


def montar_decks(df_raw: pd.DataFrame, cards_db: dict) -> list[dict]:
    """Agrupa o CSV por deck e separa lider das demais cartas.

    A deteccao de lider usa o MESMO criterio de `build_real_deck`
    (`card_type == 'LEADER'` no banco de cartas) -- nao reimplementa regra
    propria, so nao monta objetos Card porque aqui o destino e JSON.
    """
    decks = []
    for url, grupo in df_raw.groupby('deck_url'):
        # Mesma deduplicacao de `build_real_deck` e pelo mesmo motivo: o
        # CSV repete a lista inteira uma vez por `placing` (mesmo deck em
        # varios torneios), com qty identica.
        grupo = grupo.drop_duplicates(subset='card_code', keep='first')
        leader_code = None
        cards = []
        desconhecidas = 0

        for _, row in grupo.iterrows():
            code = str(row['card_code'])
            qty = int(row['qty'])
            data = cards_db.get(code)
            if not data:
                desconhecidas += 1
                continue
            # `load_cards_db` expoe o tipo em 'type' (nao 'card_type',
            # que e o nome da COLUNA no cards_rows.csv cru).
            if str(data.get('type', '')).upper() == 'LEADER':
                leader_code = code
            else:
                cards.append({'code': code, 'qty': qty})

        total = sum(c['qty'] for c in cards)
        decks.append({
            'name': str(grupo['deck_name'].iloc[0]),
            'leader_code': leader_code,
            'cards': cards,
            'source_url': str(url),
            'total_cartas': total,
            'desconhecidas': desconhecidas,
            'valido': bool(leader_code) and total >= MIN_CARTAS_DECK,
        })
    return decks


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='so mostra o que seria inserido, nao escreve no banco')
    ap.add_argument('--limite', type=int, default=None,
                    help='insere no maximo N decks (util pra testar)')
    args = ap.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    df_raw = pd.read_csv(os.path.join(base, 'decklists_raw.csv'))
    cards_db = load_cards_db(os.path.join(base, 'cards_rows.csv'))

    decks = montar_decks(df_raw, cards_db)
    validos = [d for d in decks if d['valido']]
    invalidos = [d for d in decks if not d['valido']]

    print(f'decklists no CSV: {len(decks)}')
    print(f'  validas (lider + >= {MIN_CARTAS_DECK} cartas): {len(validos)}')
    print(f'  descartadas: {len(invalidos)}')
    for d in invalidos[:5]:
        print(f'    - {d["name"][:45]}: lider={d["leader_code"]} '
              f'cartas={d["total_cartas"]} desconhecidas={d["desconhecidas"]}')

    ja_existem = {d.get('source_url') for d in await db.list_meta_decklists(limit=10000)}
    novos = [d for d in validos if d['source_url'] not in ja_existem]
    print(f'\nja na tabela: {len(ja_existem)} | novos a inserir: {len(novos)}')

    if args.limite:
        novos = novos[:args.limite]
        print(f'(limitado a {len(novos)})')

    if args.dry_run:
        print('\n--dry-run: nada foi escrito. Amostra do que entraria:')
        for d in novos[:5]:
            print(f'  {d["leader_code"]:12} {d["total_cartas"]:3} cartas  {d["name"][:50]}')
        return 0

    inseridos = 0
    for d in novos:
        try:
            await db.insert_meta_decklist(
                name=d['name'],
                leader_code=d['leader_code'],
                cards=d['cards'],
                source_url=d['source_url'],
                is_current_meta=True,
            )
            inseridos += 1
        except Exception as e:
            print(f'  ERRO em {d["name"][:40]}: {e}')

    print(f'\ninseridos: {inseridos}')
    await db.close_pool()
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
