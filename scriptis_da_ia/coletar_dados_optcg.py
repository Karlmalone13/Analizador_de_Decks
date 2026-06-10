"""
OPTCG Data Collector v3
Fontes:
  - Limitless TCG (onepiece.limitlesstcg.com)
  - OP Leaderboard (op-leaderboard.com)

Instalação:
    pip install requests beautifulsoup4 pandas

Uso:
    python coletar_dados_optcg.py
    python coletar_dados_optcg.py --forcar   (re-coleta mesmo se já tiver raw)

Saída:
    decklists_raw.csv     — lista de cartas por deck
    winrates_leaders.csv  — winrates por leader do op-leaderboard
    features.csv          — features extraídas prontas para treinar
"""

import os
import sys
import requests
import pandas as pd
import time
import re
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'HX-Request': 'true',
}

BASE_LIMITLESS   = 'https://onepiece.limitlesstcg.com'
BASE_LEADERBOARD = 'https://op-leaderboard.com'
FORMATS = ['OP15', 'OP14', 'OP13', 'OP12', 'OP11', 'OP10']

# ── 1. OP Leaderboard ─────────────────────────────────────────────────────────

def get_winrates_leaderboard():
    all_rows = []
    for fmt in FORMATS:
        print(f'  OP Leaderboard {fmt}...')
        url = f'{BASE_LEADERBOARD}/api/leaderboard?meta_format={fmt}&region=all'
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')

            rows = soup.select('table tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) < 5:
                    continue

                # Código do leader — está no link da linha
                leader_code = ''
                link = row.find('a', href=re.compile(r'lid='))
                if link:
                    m = re.search(r'lid=([A-Z0-9\-]+)', link['href'])
                    if m:
                        leader_code = m.group(1)

                if not leader_code:
                    continue

                leader_name = link.get_text(strip=True) if link else ''
                text_cells  = [c.get_text(strip=True) for c in cells]

                # Extrai winrate (formato "53.22%")
                win_rate = 0.0
                for cell in text_cells:
                    m = re.search(r'(\d{2,3}\.?\d*)%', cell)
                    if m:
                        val = float(m.group(1))
                        if 30 <= val <= 80:  # winrate razoável
                            win_rate = val
                            break

                # Extrai match count
                games = 0
                for cell in text_cells:
                    m = re.search(r'^(\d{2,6})$', cell)
                    if m:
                        v = int(m.group(1))
                        if v > 5:
                            games = v
                            break

                # Tournament wins
                tourney_wins = 0
                for cell in text_cells:
                    m = re.match(r'^(\d{1,4})$', cell)
                    if m:
                        v = int(m.group(1))
                        if 0 <= v <= 500:
                            tourney_wins = v
                            break

                all_rows.append({
                    'format':        fmt,
                    'leader_code':   leader_code,
                    'leader_name':   leader_name,
                    'win_rate':      win_rate,
                    'games':         games,
                    'tourney_wins':  tourney_wins,
                })

            print(f'    ✅ {len([r for r in all_rows if r["format"] == fmt])} líderes')
            time.sleep(0.5)
        except Exception as e:
            print(f'    Erro {fmt}: {e}')

    return all_rows


# ── 2. Limitless ──────────────────────────────────────────────────────────────

def get_decklist_links(pages=9):
    links = []
    for page in range(1, pages + 1):
        url = f'{BASE_LIMITLESS}/decks/lists?time=past_year&page={page}&per_page=100'
        print(f'  Limitless página {page}...')
        try:
            r = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            for row in soup.select('table tr'):
                cells = row.find_all('td')
                if len(cells) >= 2:
                    placing = parse_placing(cells[0].get_text(strip=True))
                    link_tag = cells[1].find('a')
                    if link_tag and '/decks/list/' in link_tag.get('href', ''):
                        href = link_tag['href']
                        name = link_tag.get_text(strip=True)
                        links.append({
                            'url': BASE_LIMITLESS + href if href.startswith('/') else href,
                            'placing': placing,
                            'name': name
                        })
            time.sleep(0.5)
        except Exception as e:
            print(f'  Erro página {page}: {e}')
    print(f'  Total links: {len(links)}')
    return links


def parse_placing(text):
    match = re.search(r'(\d+)', text.strip().lower())
    return int(match.group(1)) if match else 99


def get_decklist(url):
    try:
        r = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        cards = []
        lines = [l.strip() for l in soup.get_text().split('\n') if l.strip()]
        i = 0
        while i < len(lines):
            # Captura o Leader (linha "Leader" seguida do nome)
            if lines[i] == 'Leader' and i + 1 < len(lines):
                next_line = lines[i + 1]
                code_match = re.search(r'\(([A-Z0-9][A-Z0-9\-]+)\)', next_line)
                if code_match:
                    code = code_match.group(1)
                    name = next_line[:next_line.rfind('(')].strip()
                    cards.append({'qty': 1, 'name': name, 'code': code, 'is_leader': True})
                    i += 2
                    continue
            # Captura cartas normais (quantidade seguida do nome)
            if re.match(r'^\d+$', lines[i]):
                qty = int(lines[i])
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    code_match = re.search(r'\(([A-Z0-9][A-Z0-9\-]+)\)', next_line)
                    if code_match:
                        code = code_match.group(1)
                        name = next_line[:next_line.rfind('(')].strip()
                        cards.append({'qty': qty, 'name': name, 'code': code, 'is_leader': False})
                        i += 2
                        continue
            i += 1
        return cards
    except Exception as e:
        print(f'  Erro ao coletar {url}: {e}')
        return []

# ── 3. Banco de cartas ────────────────────────────────────────────────────────

CARDS_DB = {}

def load_cards_db(csv_path='cards_rows.csv'):
    global CARDS_DB
    try:
        df = pd.read_csv(csv_path)
        df['card_cost']      = pd.to_numeric(df['card_cost'],   errors='coerce').fillna(0).astype(int)
        df['card_power']     = pd.to_numeric(df['card_power'],  errors='coerce').fillna(0).astype(int)
        df['counter_amount'] = df['counter_amount'].fillna('').astype(str)
        df['card_type']      = df['card_type'].fillna('').astype(str)
        df['card_color']     = df['card_color'].fillna('').astype(str)
        df['card_text']      = df['card_text'].fillna('').astype(str)
        df['card_set_id']    = df['card_set_id'].fillna('').astype(str)
        for _, row in df.iterrows():
            code = row['card_set_id'].split('_')[0]
            if not code or code == 'nan':
                continue
            CARDS_DB[code] = {
                'cost':    int(row['card_cost']),
                'power':   int(row['card_power']),
                'counter': row['counter_amount'],
                'type':    row['card_type'].upper(),
                'color':   row['card_color'],
                'text':    row['card_text'].lower(),
            }
        print(f'  Banco de cartas: {len(CARDS_DB)} cartas')
    except Exception as e:
        print(f'  Erro ao carregar {csv_path}: {e}')


def has_kw(text, kw):
    return kw.lower() in text.lower()


def extract_features(cards_list, deck_name=''):
    if not cards_list:
        return None

    leader_code = leader_color = ''
    costs = []
    powers = []
    counters_2k = counters_1k = searchers = draw_power = 0
    blockers = rush = double_atk = triggers = banish = unblockable = 0
    low_cost_1 = low_cost_2 = events = characters = stages = total = 0

    for c in cards_list:
        code      = c['code']
        qty       = c['qty']
        data      = CARDS_DB.get(code, {})
        card_type = data.get('type', '').upper()
        text      = data.get('text', '')
        cost      = data.get('cost', 0)
        power     = data.get('power', 0)
        counter   = data.get('counter', '')

        if card_type == 'LEADER':
            leader_code  = code
            leader_color = data.get('color', '')
            continue

        total += qty
        if card_type == 'CHARACTER': characters += qty
        elif card_type == 'EVENT':   events     += qty
        elif card_type == 'STAGE':   stages     += qty

        for _ in range(qty):
            costs.append(cost)
            if power > 0:
                powers.append(power)

        if counter in ['2000', '2000.0']:   counters_2k += qty
        elif counter in ['1000', '1000.0']: counters_1k += qty

        if has_kw(text, 'look at') or has_kw(text, 'search your deck') or has_kw(text, 'add up to'):
            searchers += qty
        if any(has_kw(text, k) for k in ['draw 1','draw 2','draw 3','draw 4','draw 5','draw a card']):
            draw_power += qty
        if has_kw(text, '[blocker]'):        blockers   += qty
        if has_kw(text, '[rush]'):           rush       += qty
        if has_kw(text, '[double attack]'):  double_atk += qty
        if has_kw(text, '[trigger]'):        triggers   += qty
        if has_kw(text, '[banish]'):         banish     += qty
        if has_kw(text, '[unblockable]'):    unblockable+= qty
        if cost == 1:  low_cost_1 += qty
        if cost <= 2:  low_cost_2 += qty

    if not costs:
        return None

    tr = max(total, 1)
    return {
        'deck_name':      deck_name,
        'leader':         leader_code or 'unknown',
        'leader_color':   leader_color,
        'total_cards':    total,
        'avg_cost':       round(sum(costs) / len(costs), 2),
        'avg_power':      round(sum(powers) / len(powers), 0) if powers else 0,
        'searchers':      searchers,
        'draw_power':     draw_power,
        'blockers':       blockers,
        'rush':           rush,
        'double_atk':     double_atk,
        'triggers':       triggers,
        'banish':         banish,
        'unblockable':    unblockable,
        'counters_2k':    counters_2k,
        'counters_1k':    counters_1k,
        'low_cost_1':     low_cost_1,
        'low_cost_2':     low_cost_2,
        'events':         events,
        'characters':     characters,
        'stages':         stages,
        'searcher_ratio': round(searchers / tr, 3),
        'counter_ratio':  round((counters_2k + counters_1k) / tr, 3),
        'blocker_ratio':  round(blockers / tr, 3),
        'event_ratio':    round(events / tr, 3),
    }


# ── 4. Pipeline principal ─────────────────────────────────────────────────────

def main():
    forcar = '--forcar' in sys.argv

    print('=' * 60)
    print('OPTCG Data Collector v3')
    print('Fontes: Limitless TCG + OP Leaderboard')
    print('=' * 60)

    load_cards_db('cards_rows.csv')

    # ── OP Leaderboard ────────────────────────────────────────────────────────
    if forcar or not os.path.exists('winrates_leaders.csv'):
        print('\n[A] Coletando winrates do OP Leaderboard...')
        winrate_rows = get_winrates_leaderboard()
        if winrate_rows:
            df_wr = pd.DataFrame(winrate_rows)
            # Remove linhas sem winrate útil
            df_wr = df_wr[df_wr['win_rate'] > 0]
            df_wr.to_csv('winrates_leaders.csv', index=False, encoding='utf-8')
            print(f'✅ winrates_leaders.csv — {len(df_wr)} líderes com winrate')
            print(df_wr[['format','leader_code','leader_name','win_rate','games']].head(10).to_string())
        else:
            print('⚠️  Nenhum winrate coletado')
    else:
        print('\n✅ winrates_leaders.csv já existe (use --forcar para re-coletar)')

    # Monta mapa leader_code → winrate (pega o mais recente por formato)
    winrate_map = {}
    if os.path.exists('winrates_leaders.csv'):
        df_wr = pd.read_csv('winrates_leaders.csv')
        for _, row in df_wr.iterrows():
            code = str(row.get('leader_code', ''))
            wr   = float(row.get('win_rate', 0) or 0)
            if code and wr > 0:
                winrate_map[code] = wr

    # ── Limitless ─────────────────────────────────────────────────────────────
    if not forcar and os.path.exists('decklists_raw.csv'):
        print('\n✅ decklists_raw.csv encontrado! Extraindo features...')
        df_raw = pd.read_csv('decklists_raw.csv')
        print(f'  Linhas: {len(df_raw)}')
        features_list = _extrair_features_do_raw(df_raw, winrate_map)
        _salvar_features(features_list)
        return

    print('\n[1/3] Coletando links do Limitless...')
    links = get_decklist_links(pages=9)
    if not links:
        print('Nenhum link encontrado.')
        return

    print(f'\n[2/3] Coletando {len(links)} decklists...')
    rows_raw      = []
    features_list = []

    for i, item in enumerate(links):
        print(f'  [{i+1}/{len(links)}] {item["name"]} (#{item["placing"]})')
        cards = get_decklist(item['url'])
        if cards:
            for c in cards:
                rows_raw.append({
                    'deck_url':  item['url'],
                    'deck_name': item['name'],
                    'placing':   item['placing'],
                    'card_code': c['code'],
                    'card_name': c['name'],
                    'qty':       c['qty'],
                })
            feat = extract_features(cards, item['name'])
            if feat:
                feat['placing']           = item['placing']
                feat['url']               = item['url']
                feat['performance_score'] = max(0, round(100 - (item['placing'] - 1) * 3, 1))
                feat['leader_winrate']    = winrate_map.get(feat['leader'], 0)
                features_list.append(feat)
        time.sleep(0.8)

    print('\n[3/3] Salvando...')
    if rows_raw:
        pd.DataFrame(rows_raw).to_csv('decklists_raw.csv', index=False, encoding='utf-8')
        print(f'✅ decklists_raw.csv — {len(rows_raw)} linhas')
    _salvar_features(features_list)
    print('\n✅ Concluído! Próximo: python treinar_modelo.py')


def _extrair_features_do_raw(df_raw, winrate_map):
    features_list = []
    for url, group in df_raw.groupby('deck_url'):
        cards = [
            {'code': str(r['card_code']), 'name': str(r['card_name']), 'qty': int(r['qty'])}
            for _, r in group.iterrows()
        ]
        feat = extract_features(cards, group.iloc[0]['deck_name'])
        if feat:
            feat['placing']           = int(group.iloc[0]['placing'])
            feat['url']               = url
            feat['performance_score'] = max(0, round(100 - (feat['placing'] - 1) * 3, 1))
            feat['leader_winrate']    = winrate_map.get(feat['leader'], 0)
            features_list.append(feat)
    return features_list


def _salvar_features(features_list):
    if features_list:
        df_feat = pd.DataFrame(features_list)
        df_feat.to_csv('features.csv', index=False, encoding='utf-8')
        print(f'✅ features.csv — {len(features_list)} decks')
        print('\nPreview:')
        print(df_feat[['deck_name','placing','avg_cost','searchers','counters_2k','blockers','leader_winrate']].head(10).to_string())
    else:
        print('⚠️  Nenhuma feature extraída.')


if __name__ == '__main__':
    main()