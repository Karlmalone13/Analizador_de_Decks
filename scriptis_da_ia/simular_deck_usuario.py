"""
simular_deck_usuario.py
========================
Conecta deck do Supabase com o simulador OPTCG.

Uso:
    python simular_deck_usuario.py --deck_id SEU_DECK_ID --n 200
    python simular_deck_usuario.py --deck_id SEU_DECK_ID --n 200 --salvar
"""

import argparse
import json
import os
import sys
import pandas as pd
from copy import deepcopy

sys.path.insert(0, os.path.dirname(__file__))

from optcg_engine.decision_engine import (
    Card, GameState, DecisionEngine,
    load_cards_db, build_real_deck, validar_deck,
    parse_card_effects, simular_matchup
)

# ── Supabase ──────────────────────────────────────────────────────────────────
try:
    from supabase import create_client
    SUPABASE_URL = os.environ.get(
        'NEXT_PUBLIC_SUPABASE_URL',
        'https://opycjxbgqbkrmmqptqsk.supabase.co'
    )
    SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_KEY else None
except ImportError:
    supabase = None
    print("⚠️  supabase-py não instalado: pip install supabase")


def fetch_deck(deck_id: str) -> dict | None:
    if not supabase:
        print("❌ Supabase não configurado.")
        return None
    r = supabase.table('decks').select('id,name,cards').eq('id', deck_id).execute()
    if not r.data:
        print(f"❌ Deck {deck_id} não encontrado.")
        return None
    row = r.data[0]
    cards_json = json.loads(row['cards']) if isinstance(row['cards'], str) else row['cards']
    return {'id': row['id'], 'name': row.get('name', 'Deck'), 'deck_json': cards_json}


def supabase_json_to_deck(deck_json: dict, cards_db: dict) -> tuple | None:
    """
    Converte JSON do Deck Builder para (leader, cards, start_stage).
    Formato: {"leader": {...}, "cards": [{"card": {...}, "quantity": N}]}
    """
    def make_card(card_data: dict) -> Card | None:
        code = (card_data.get('card_set_id') or
                card_data.get('id') or '').split('_')[0].strip()
        if not code:
            return None
        data = cards_db.get(code, {})
        if not data:
            # tenta parsear do próprio JSON
            text    = str(card_data.get('card_text', ''))
            counter = str(card_data.get('counter_amount', ''))
            data    = parse_card_effects(text, counter)
            data['name']  = str(card_data.get('card_name', code))
            data['color'] = str(card_data.get('card_color', ''))
            data['type']  = str(card_data.get('card_type', 'CHARACTER')).upper()
            try: data['cost']  = int(float(card_data.get('card_cost') or 0))
            except: data['cost'] = 0
            try: data['power'] = int(float(card_data.get('card_power') or 0))
            except: data['power'] = 0
            try: data['life']  = int(float(card_data.get('life') or 0))
            except: data['life'] = 0
            data['text'] = text

        return Card(
            code=code,
            name=data.get('name', code),
            card_type=data.get('type', 'CHARACTER'),
            color=data.get('color', ''),
            cost=data.get('cost', 0),
            power=data.get('power', 0),
            counter=data.get('counter', 0),
            life=data.get('life', 0),
            has_rush=data.get('has_rush', False),
            has_blocker=data.get('has_blocker', False),
            has_double_attack=data.get('has_double_attack', False),
            has_banish=data.get('has_banish', False),
            has_trigger=data.get('has_trigger', False),
            has_unblockable=data.get('has_unblockable', False),
            has_on_play_ko=data.get('has_on_play_ko', False),
            has_bounce=data.get('has_bounce', False),
            has_rest_effect=data.get('has_rest_effect', False),
            is_searcher=data.get('is_searcher', False),
            has_start_of_game=data.get('has_start_of_game', False),
            has_power_minus=data.get('has_power_minus', False),
            trash_opp_char=data.get('trash_opp_char', False),
            draw_power=data.get('draw_power', 0),
            draw_then_trash=data.get('draw_then_trash', 0),
            draw_condition=data.get('draw_condition', 'always'),
            card_text=data.get('text', ''),
        )

    # Líder
    leader_data = deck_json.get('leader', {})
    leader = make_card(leader_data)
    if not leader:
        print("❌ Líder não encontrado")
        return None
    leader.card_type = 'LEADER'

    # Cartas
    cards = []
    start_stage = None
    missing = []

    for entry in deck_json.get('cards', []):
        card_data = entry.get('card') or entry
        quantity  = int(entry.get('quantity', 1))
        card = make_card(card_data)
        if not card:
            missing.append(card_data.get('card_set_id', '?'))
            continue
        for _ in range(quantity):
            cards.append(deepcopy(card))
        if (card.card_type == 'STAGE' and
                card.has_start_of_game and
                start_stage is None):
            start_stage = deepcopy(card)

    if missing:
        print(f"  ⚠️  {len(missing)} cartas não encontradas: {list(set(missing))[:5]}")

    print(f"  Deck montado: líder={leader.name} | {len(cards)} cartas")
    return (leader, cards, start_stage)


def fetch_opponent_decks(exclude_id: str, cards_db: dict, limit: int = 10) -> list:
    """Busca outros decks do Supabase como oponentes."""
    if not supabase:
        return []
    r = supabase.table('decks').select('id,name,cards').limit(limit).execute()
    result = []
    for row in (r.data or []):
        if row['id'] == exclude_id:
            continue
        try:
            cards_json = json.loads(row['cards']) if isinstance(row['cards'], str) else row['cards']
            total = sum(int(e.get('quantity', 1)) for e in cards_json.get('cards', []))
            if total < 40:
                continue
            deck = supabase_json_to_deck(cards_json, cards_db)
            if deck and len(deck[1]) >= 40:
                result.append((row.get('name', 'Deck'), deck))
        except:
            continue
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deck_id', required=True)
    parser.add_argument('--n', type=int, default=200)
    parser.add_argument('--salvar', action='store_true')
    args = parser.parse_args()

    # ── Carrega banco de cartas ───────────────────────────────────────────
    print("[1/4] Carregando banco de cartas...")
    csv_path = os.path.join(os.path.dirname(__file__), 'cards_rows.csv')
    cards_db = load_cards_db(csv_path)

    # ── Busca deck do usuário ─────────────────────────────────────────────
    print(f"[2/4] Buscando deck {args.deck_id}...")
    deck_info = fetch_deck(args.deck_id)
    if not deck_info:
        return

    deck_a = supabase_json_to_deck(deck_info['deck_json'], cards_db)
    if not deck_a:
        return

    leader_a, cards_a, _ = deck_a
    valido, erros = validar_deck(leader_a, cards_a, cards_db)
    if erros:
        print(f"  ⚠️  {erros}")
    else:
        print(f"  ✅ Deck válido: {deck_info['name']} | líder: {leader_a.code}")

    # ── Monta oponentes ──────────────────────────────────────────────────
    print("[3/4] Preparando oponentes...")
    opponent_decks = []

    # 1. Outros decks do Supabase
    outros = fetch_opponent_decks(args.deck_id, cards_db, limit=10)
    for nome, deck in outros:
        opponent_decks.append((nome, deck))
        if len(opponent_decks) >= 3:
            break

    # 2. Decklists de torneio do CSV
    csv_raw = os.path.join(os.path.dirname(__file__), 'decklists_raw.csv')
    if len(opponent_decks) < 5 and os.path.exists(csv_raw):
        df_raw = pd.read_csv(csv_raw)
        for url in df_raw['deck_url'].unique()[:30]:
            rows = df_raw[df_raw['deck_url'] == url]
            name = rows['deck_name'].iloc[0]
            result = build_real_deck(name, url, df_raw, cards_db)
            if not result:
                continue
            leader_b, cards_b, _ = result
            v, _ = validar_deck(leader_b, cards_b, cards_db)
            if v:
                opponent_decks.append((name, result))
            if len(opponent_decks) >= 5:
                break

    # 3. Espelho se não tiver oponentes
    if not opponent_decks:
        print("  ⚠️  Sem oponentes — usando espelho")
        opponent_decks = [(deck_info['name'], deck_a)]

    print(f"  {len(opponent_decks)} oponentes prontos")

    # ── Simula ───────────────────────────────────────────────────────────
    print(f"[4/4] Simulando {args.n} partidas por matchup...")

    winrates = []
    avg_turns_list = []
    counters_list = []
    searchers_list = []
    triggers_list = []
    total_matches = 0

    for i, (nome_opp, deck_b) in enumerate(opponent_decks):
        mr = simular_matchup(deck_a, deck_b, n=args.n)
        winrates.append(mr['winrate_a'])
        avg_turns_list.append(mr['avg_turns'])
        counters_list.append(mr['counters_pg_a'])
        searchers_list.append(mr['searchers_pg_a'])
        triggers_list.append(mr['triggers_pg_a'])
        total_matches += args.n
        print(f"  Matchup {i+1}/{len(opponent_decks)} vs {nome_opp[:35]}: "
              f"wr={mr['winrate_a']}% turns={mr['avg_turns']}")

    resultado = {
        'deck_id':       args.deck_id,
        'deck_name':     deck_info['name'],
        'leader':        leader_a.code,
        'sim_winrate':   round(sum(winrates) / len(winrates), 1),
        'avg_turns':     round(sum(avg_turns_list) / len(avg_turns_list), 1),
        'counters_pg':   round(sum(counters_list) / len(counters_list), 1),
        'searchers_pg':  round(sum(searchers_list) / len(searchers_list), 1),
        'triggers_pg':   round(sum(triggers_list) / len(triggers_list), 1),
        'matches_played': total_matches,
    }

    print(f"\n{'='*50}")
    print(f"Deck:           {resultado['deck_name']}")
    print(f"Líder:          {resultado['leader']}")
    print(f"Win Rate:       {resultado['sim_winrate']}%")
    print(f"Turnos médios:  {resultado['avg_turns']}")
    print(f"Counters/jogo:  {resultado['counters_pg']}")
    print(f"Searchers/jogo: {resultado['searchers_pg']}")
    print(f"Triggers/jogo:  {resultado['triggers_pg']}")
    print(f"Partidas:       {resultado['matches_played']}")
    print(f"{'='*50}")

    if args.salvar:
        if not supabase:
            print("⚠️  Supabase não configurado — resultado não salvo.")
        else:
            try:
                supabase.table('deck_sim_results').upsert({
                    'deck_id':       args.deck_id,
                    'sim_winrate':   resultado['sim_winrate'],
                    'avg_turns':     resultado['avg_turns'],
                    'counters_pg':   resultado['counters_pg'],
                    'searchers_pg':  resultado['searchers_pg'],
                    'triggers_pg':   resultado['triggers_pg'],
                    'matches_played': resultado['matches_played'],
                }, on_conflict='deck_id').execute()
                print(f"✅ Resultado salvo no Supabase!")
            except Exception as e:
                print(f"⚠️  Erro ao salvar: {e}")


if __name__ == '__main__':
    main()