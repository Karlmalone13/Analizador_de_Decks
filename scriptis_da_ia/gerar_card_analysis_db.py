"""
gerar_card_analysis_db.py
=========================
Gera card_analysis_db.json — a fonte ÚNICA de verdade que o analisador
de listas GRÁTIS (frontend/TypeScript) consome.

Não roda no navegador. É pré-computado aqui, no Mundo A (motor fiel),
e exportado como JSON estático. O frontend só faz aritmética leve
(somar curva, contar cores) sobre esses dados — o CONHECIMENTO de
"o que cada carta faz" vem daqui, de uma fonte só.

Reusa parse_card_effect() de gerar_effects_db.py (o parser de texto que
já existe) para não duplicar a lógica de leitura de efeitos.

Uso:
    python gerar_card_analysis_db.py
Saída:
    card_analysis_db.json
"""

import json
import re
import pandas as pd

from gerar_effects_db import parse_card_effect
from synergy_states import detect_card_states


# ===========================================================================
# Derivação de flags de análise a partir dos efeitos parseados
# ===========================================================================

def _collect_actions(effects: dict) -> set:
    """Junta todos os 'action' de todos os triggers numa carta."""
    actions = set()
    for trigger, data in effects.items():
        for step in data.get('steps', []):
            a = step.get('action')
            if a:
                actions.add(a)
    return actions


def _effects_with_trigger(effects: dict) -> list:
    """
    Extrai [{action, trigger, ...attrs}] preservando QUAL gatilho dispara cada
    efeito e atributos relevantes para sinergia (power_lte, cost_lte).
    """
    out = []
    for trigger, data in effects.items():
        don_req = data.get('don_requirement')
        for step in data.get('steps', []):
            a = step.get('action')
            if a:
                entry = {'action': a, 'trigger': trigger}
                if don_req:
                    entry['don_requirement'] = don_req
                for attr in ('power_lte', 'cost_lte', 'rested_only', 'target'):
                    if attr in step:
                        entry[attr] = step[attr]
                out.append(entry)
    return out


def derive_analysis(card_text: str, card_type: str, counter: int) -> dict:
    """
    Recebe texto bruto da carta e devolve as flags de análise estática
    que o analisador grátis precisa. Tudo derivado de uma fonte só.
    """
    effects = parse_card_effect(card_text, card_type)
    actions = _collect_actions(effects)
    triggers = set(effects.keys())

    # ── Motor de deck: busca e compra ───────────────────────────────────
    is_searcher = bool(actions & {'look_top_deck', 'add_to_hand', 'add_from_trash'})
    draws = 'draw' in actions

    # ── Defesa ──────────────────────────────────────────────────────────
    has_counter_value = counter > 0          # counter impresso (1000/2000)
    has_counter_event = 'counter' in triggers  # evento/efeito [Counter]
    is_blocker = 'keyword_blocker' in actions or 'gain_blocker' in actions

    # ── Interação / removal ─────────────────────────────────────────────
    is_removal = bool(actions & {'ko', 'bounce', 'rest_opp_character'})
    # comportamentos granulares (para detecção de arquétipo por cartas)
    kos = 'ko' in actions                          # KO de personagem (controle)
    rests_opponent = 'rest_opp_character' in actions  # trava personagem (controle/tempo)
    bounces = 'bounce' in actions                  # retorna à mão (tempo/controle)
    gives_don = 'give_don' in actions              # engine de DON (ramp)
    power_buff = 'buff_power' in actions           # buff/debuff de poder

    # ── Agressão / finalização ──────────────────────────────────────────
    has_rush = 'keyword_rush' in actions or 'gain_rush' in actions
    has_double_attack = 'keyword_double_attack' in actions or 'gain_double_attack' in actions
    has_unblockable = 'keyword_unblockable' in actions or 'gain_unblockable' in actions
    has_banish = 'keyword_banish' in actions or 'gain_banish' in actions

    # ── Cura / vida (identidade amarela) ────────────────────────────────
    heals = 'heal' in actions or 'gain_life' in actions   # heal unificado em gain_life
    # Manipulação de vida detectada por padrão de texto (parser de efeitos
    # não captura vida). Três direções, pois têm sinais opostos:
    _t = (card_text or '').lower()
    gains_life = bool(re.search(r'to (the top of )?your life', _t))      # defensivo (Vida)
    attacks_life = bool(re.search(r"opponent's life", _t))               # ofensivo (Aggro/Controle)
    trashes_own_life = bool(re.search(r'trash[^.]*your life', _t))       # troca vida por vantagem

    # ── Trigger na vida (afeta consistência defensiva) ──────────────────
    has_trigger = 'trigger' in triggers

    return {
        'effects': _effects_with_trigger(effects),
        'synergy_states': detect_card_states(card_text),
        'text': card_text or '',
        'is_searcher': is_searcher,
        'draws': draws,
        'has_counter_value': has_counter_value,
        'has_counter_event': has_counter_event,
        'is_blocker': is_blocker,
        'is_removal': is_removal,
        'kos': kos,
        'rests_opponent': rests_opponent,
        'bounces': bounces,
        'gives_don': gives_don,
        'power_buff': power_buff,
        'heals': heals,
        'gains_life': gains_life,
        'attacks_life': attacks_life,
        'trashes_own_life': trashes_own_life,
        'has_rush': has_rush,
        'has_double_attack': has_double_attack,
        'has_unblockable': has_unblockable,
        'has_banish': has_banish,
        'has_trigger': has_trigger,
    }


# ===========================================================================
# Gerador principal
# ===========================================================================

def generate_analysis_db(csv_path: str = 'cards_rows.csv') -> dict:
    df = pd.read_csv(csv_path)
    df['code'] = df['card_set_id'].fillna('').astype(str).str.split('_').str[0]
    df_unique = df.drop_duplicates(subset='code', keep='first')

    db = {}
    skipped = 0

    for _, row in df_unique.iterrows():
        code = str(row['code']).strip()
        if not code or code == 'nan':
            skipped += 1
            continue

        card_text = str(row.get('card_text') or '')
        card_type = str(row.get('card_type') or '').upper()

        # counter impresso
        try:
            counter = int(float(str(row.get('counter_amount', '') or '0').replace('.0', '') or 0))
        except (ValueError, TypeError):
            counter = 0

        try:
            cost = int(float(row.get('card_cost') or 0))
        except (ValueError, TypeError):
            cost = 0
        try:
            power = int(float(row.get('card_power') or 0))
        except (ValueError, TypeError):
            power = 0
        try:
            life = int(float(row.get('life') or 0))
        except (ValueError, TypeError):
            life = 0

        analysis = derive_analysis(card_text, card_type, counter)

        attribute_raw = str(row.get('attribute') or '').strip()
        attribute = '' if attribute_raw.upper() in ('NULL', 'N/A', '?', 'NAN') else attribute_raw

        db[code] = {
            'name': str(row.get('card_name') or code),
            'type': card_type,
            'cost': cost,
            'power': power,
            'counter': counter,
            'life': life,
            'color': str(row.get('card_color') or ''),
            'sub_types': str(row.get('sub_types') or ''),
            'attribute': attribute,
            **analysis,
        }

    return db, skipped


def main():
    print('Gerando card_analysis_db.json a partir de cards_rows.csv ...')
    db, skipped = generate_analysis_db('cards_rows.csv')

    out = 'card_analysis_db.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=1)

    # Resumo
    total = len(db)
    searchers = sum(1 for c in db.values() if c['is_searcher'])
    removal = sum(1 for c in db.values() if c['is_removal'])
    blockers = sum(1 for c in db.values() if c['is_blocker'])
    counters = sum(1 for c in db.values() if c['has_counter_value'])

    print(f'  {total} cartas escritas em {out} ({skipped} ignoradas)')
    print(f'  searchers: {searchers} | removal: {removal} | '
          f'blockers: {blockers} | counter-cards: {counters}')


if __name__ == '__main__':
    print('Este gerador não deve ser rodado sozinho — geraria um JSON')
    print('dessincronizado do outro banco.')
    print('Use:  python gerar_dbs.py   (gera os dois juntos)')
    import sys
    sys.exit(1)    
    main()