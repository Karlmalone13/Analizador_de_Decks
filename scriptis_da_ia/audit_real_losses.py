"""
Auditoria de derrota real: reconstrói o estado do jogo em cada turno do BOT
numa derrota REAL (log de partida contra humano, `logs/parsed/*.json`) e
pergunta pro motor de HOJE (`decision_engine.py`, fonte única — chama
`OPTCGMatch.play_turn()` de verdade, não reimplementa decisão nenhuma) o
que ele faria. Compara com o que o bot fez de verdade na época.

Criado 04/08/2026 a pedido do usuário: em vez de forçar uma linha de jogo
fixa (que quebra se a mão/board divergir), usa o HISTÓRICO REAL como
ground truth e o motor ATUAL como "segunda opinião" sobre cada decisão —
ferramenta permanente, ver CLAUDE.md/AGENTS.md ("Auditoria de derrotas
reais contra humano").

Limitações honestas (documentadas, não escondidas):
- `don_available` é uma RECONSTRUÇÃO best-effort (soma don_drawn por turno,
  subtrai custo de play/activate conhecido via cards_db/card_effects_db e
  os `attach_don` registrados) — pode divergir do valor real em jogos
  longos ou com efeitos que dão/tiram DON de formas não capturadas pelo
  parser. Sinalizado no relatório como `don_available_estimado`.
- O deck restante (cartas ainda não vistas) é aproximado: pega um deck
  REAL do mesmo líder em `decklists_raw.csv`, remove o que já apareceu em
  mão/campo/trash/vida, embaralha o resto — a COMPOSIÇÃO é real, a ORDEM
  não é (não tem como saber a ordem real do deck a partir do log).
- Mão do oponente é tratada com informação COMPLETA (mesmo padrão que o
  self-play/gauntlet já usa hoje — `self_play_info_hidden` nunca é ligado
  em lugar nenhum do projeto ainda), não mascarada como o caminho ao vivo
  faz. Ou seja: o motor aqui tem mais informação do oponente do que o bot
  real teve ao vivo — resultado tende a ficar "melhor" que o bot real
  teria conseguido nessa exata situação, não pior.
- Primeiro turno de cada jogador é pulado (não dá pra reconstruir o
  "antes" sem o snapshot da mão inicial, que não é registrado).

Uso:
    python audit_real_losses.py --log <caminho_do_parsed.json>
    python audit_real_losses.py --all [--limit N]
    python audit_real_losses.py --list   # só lista as derrotas reais disponíveis
"""
import argparse
import contextlib
import io
import json
import os
import random
from copy import deepcopy

import pandas as pd

from optcg_engine.decision_engine import (
    Card, GameState, load_cards_db, build_real_deck, validar_deck,
    populate_full_deck_knowledge, get_card_effects, _make_card,
)
from replay_optcg import ReplayMatch

LOGS_DIR = 'logs'
INDEX_PATH = os.path.join(LOGS_DIR, 'index.json')
OUT_DIR = os.path.join('metrics', 'real_loss_audits')


def find_real_bot_losses():
    """Retorna [(parsed_file, bot_side)] pras derrotas reais do bot (You)
    contra humano (Opponent), na convenção já usada no projeto (bloco 432)."""
    idx = json.load(open(INDEX_PATH, encoding='utf-8'))
    out = []
    for e in idx:
        p1, p2 = e.get('p1', {}), e.get('p2', {})
        n1, n2 = p1.get('name', ''), p2.get('name', '')
        winner = e.get('winner')
        pf = e.get('parsed_file')
        if not pf:
            continue
        if n1 == 'You' and n2 == 'Opponent' and winner == 'p2':
            out.append((pf, 'You'))
        elif n2 == 'You' and n1 == 'Opponent' and winner == 'p1':
            out.append((pf, 'You'))
    return out


def _cards_from_codes(codes, cards_db, rested_map=None):
    rested_map = rested_map or {}
    out = []
    for code in codes:
        data = cards_db.get(code)
        if not data:
            continue
        card = _make_card(code, data)
        card.rested = bool(rested_map.get(code))
        out.append(card)
    return out


def _find_real_deck(leader_name, cards_db, df_raw, urls, leader_code=None):
    """Acha QUALQUER deck real (decklists_raw.csv) com o mesmo nome de
    líder do log -- serve só de fonte pra compor o RESTO do deck (ver
    limitações no topo do arquivo). Sem decklist real disponível pra esse
    líder (ex: Marshall D. Teach/Krieg/Kid -- confirmado ausentes do
    decklists_raw.csv em investigação anterior desta sessão), cai num
    deck GENÉRICO (mesma cor do líder, sem fidelidade real) só pra não
    travar a auditoria -- qualidade do reconstruído pra ESSE lado fica
    mais fraca, mas o lado que importa pra auditoria (bot_side) quase
    sempre tem decklist real (Imu/Jinbe/Crocodile confirmados presentes)."""
    for url, name in urls.items():
        if leader_name.lower() in name.lower():
            result = build_real_deck(name, url, df_raw, cards_db)
            if not result:
                continue
            leader, cards, stage = result
            valido, _ = validar_deck(leader, cards, cards_db)
            if valido:
                return leader, cards, stage
    if leader_code and leader_code in cards_db:
        leader = _make_card(leader_code, cards_db[leader_code])
        cor = (leader.color or '').split('/')[0]
        candidatos = [code for code, d in cards_db.items()
                      if d.get('type') == 'CHARACTER' and cor and cor in (d.get('color') or '')]
        random.shuffle(candidatos)
        cards = []
        i = 0
        while len(cards) < 50 and candidatos:
            code = candidatos[i % len(candidatos)]
            cards.append(_make_card(code, cards_db[code]))
            i += 1
        return leader, cards, None
    return None


def _remaining_deck(full_cards, seen_codes_with_qty):
    """full_cards: lista de Card (deck completo real, sem líder). Remove
    até a quantidade vista de cada código (mão+campo+trash+vida)."""
    pool = list(full_cards)
    remaining = []
    seen = dict(seen_codes_with_qty)
    for card in pool:
        if seen.get(card.code, 0) > 0:
            seen[card.code] -= 1
            continue
        remaining.append(card)
    random.shuffle(remaining)
    return remaining


class DonEstimator:
    """Reconstrução best-effort de don_available por jogador, turno a
    turno, a partir do stream de ações do log (ver limitações no topo)."""

    def __init__(self):
        self.pool = {}

    def apply_turn(self, player, turn, cards_db):
        self.pool.setdefault(player, 0)
        self.pool[player] += turn.get('don_drawn', 0) or 0
        for act in turn.get('actions', []):
            t = act.get('type')
            if t == 'play':
                data = cards_db.get(act.get('card', ''), {})
                self.pool[player] = max(0, self.pool[player] - int(data.get('cost', 0) or 0))
            elif t == 'activate':
                effects = get_card_effects(act.get('card', ''))
                am = effects.get('activate_main', {})
                custo = sum(c.get('count', 0) for c in am.get('costs', [])
                            if c.get('type') == 'rest_don')
                self.pool[player] = max(0, self.pool[player] - custo)
            elif t == 'attach_don':
                self.pool[player] = max(0, self.pool[player] - int(act.get('amount', 0) or 0))

    def available(self, player):
        return self.pool.get(player, 0)


def audit_one_game(parsed_path, bot_side, cards_db, df_raw, urls, verbose=False):
    data = json.load(open(parsed_path, encoding='utf-8'))
    meta = data['meta']['players']
    turns = data['turns']
    opp_side = 'Opponent' if bot_side == 'You' else 'You'

    bot_leader = meta['p1' if meta['p1']['name'] == bot_side else 'p2']['leader']
    opp_leader = meta['p1' if meta['p1']['name'] == opp_side else 'p2']['leader']
    bot_leader_name, bot_leader_code = bot_leader['name'], bot_leader.get('code')
    opp_leader_name, opp_leader_code = opp_leader['name'], opp_leader.get('code')

    bot_deck = _find_real_deck(bot_leader_name, cards_db, df_raw, urls, bot_leader_code)
    opp_deck = _find_real_deck(opp_leader_name, cards_db, df_raw, urls, opp_leader_code)
    if not bot_deck or not opp_deck:
        return {'error': f'deck real nao encontrado (bot={bot_leader_name}, opp={opp_leader_name})'}

    don_est = DonEstimator()
    bot_turn_count = 0
    results = []

    for i, turn in enumerate(turns):
        player = turn['player']
        if player == bot_side:
            bot_turn_count += 1
        if i == 0:
            # sem snapshot "antes" pro 1o turno de qualquer um dos lados
            don_est.apply_turn(player, turn, cards_db)
            continue
        if player != bot_side:
            don_est.apply_turn(player, turn, cards_db)
            continue

        before = turns[i - 1]['snapshot']
        if bot_side not in before or opp_side not in before:
            don_est.apply_turn(player, turn, cards_db)
            continue

        bot_snap = before[bot_side]
        opp_snap = before[opp_side]

        match = ReplayMatch(bot_deck, opp_deck, 'Bot(hoje)', 'Oponente')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            match.setup()
        p = match.state_a
        opp = match.state_b
        p.is_first = True
        opp.is_first = False

        p.hand = _cards_from_codes(bot_snap.get('hand', []), cards_db)
        p.field_chars = _cards_from_codes(bot_snap.get('board', []), cards_db,
                                           bot_snap.get('rested', {}))
        p.trash = _cards_from_codes(bot_snap.get('trash', []), cards_db)
        life_n = bot_snap.get('life', 4)
        p.life = [deepcopy(c) for c in p.deck[:life_n]] if p.deck else []

        opp.hand = _cards_from_codes(opp_snap.get('hand', []), cards_db)
        opp.field_chars = _cards_from_codes(opp_snap.get('board', []), cards_db,
                                             opp_snap.get('rested', {}))
        opp.trash = _cards_from_codes(opp_snap.get('trash', []), cards_db)
        opp_life_n = opp_snap.get('life', 4)
        opp.life = [deepcopy(c) for c in opp.deck[:opp_life_n]] if opp.deck else []

        seen_bot = {}
        for c in p.hand + p.field_chars + p.trash + p.life:
            seen_bot[c.code] = seen_bot.get(c.code, 0) + 1
        p.deck = _remaining_deck(bot_deck[1], seen_bot)
        populate_full_deck_knowledge(p, bot_deck[1], bot_deck[0].code)

        seen_opp = {}
        for c in opp.hand + opp.field_chars + opp.trash + opp.life:
            seen_opp[c.code] = seen_opp.get(c.code, 0) + 1
        opp.deck = _remaining_deck(opp_deck[1], seen_opp)
        populate_full_deck_knowledge(opp, opp_deck[1], opp_deck[0].code)

        p.turn = bot_turn_count - 1
        p.don_available = don_est.available(bot_side)

        eng = match._get_engine_match()
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            try:
                eng.play_turn(p, opp, verbose=True)
            except Exception as exc:  # nunca deixa uma reconstrucao ruim derrubar a auditoria inteira
                results.append({
                    'turn': turn['turn'], 'error': str(exc),
                    'historical_actions': turn.get('actions', []),
                })
                don_est.apply_turn(player, turn, cards_db)
                continue
        engine_log = buf2.getvalue()

        results.append({
            'turn': turn['turn'],
            'don_available_estimado': p.don_available,
            'historical_actions': turn.get('actions', []),
            'engine_hoje_narrativa': engine_log,
        })
        if verbose:
            print(f'--- turno {turn["turn"]} (real vs motor de hoje) ---')
            print('HISTORICO:', json.dumps(turn.get('actions', []), ensure_ascii=False)[:300])
            print('HOJE:', engine_log[:600])

        don_est.apply_turn(player, turn, cards_db)

    return {
        'parsed_file': os.path.basename(parsed_path),
        'bot_side': bot_side,
        'bot_leader': bot_leader_name,
        'opp_leader': opp_leader_name,
        'turnos_auditados': len(results),
        'turnos': results,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--log', help='caminho de um parsed json especifico')
    ap.add_argument('--all', action='store_true', help='roda em todas as derrotas reais do bot')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    if args.list:
        for pf, side in find_real_bot_losses():
            print(pf)
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    if args.log:
        jobs = [(args.log, 'You')]
    else:
        jobs = find_real_bot_losses()
        if args.limit:
            jobs = jobs[:args.limit]

    for pf, side in jobs:
        full_path = os.path.join(LOGS_DIR, pf) if not os.path.isabs(pf) and not pf.startswith(LOGS_DIR) else pf
        print(f'Auditando {pf}...')
        try:
            report = audit_one_game(full_path, side, cards_db, df_raw, urls, verbose=args.verbose)
        except Exception as exc:
            report = {'parsed_file': os.path.basename(pf), 'error': str(exc)}
        out_path = os.path.join(OUT_DIR, os.path.basename(pf))
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        if 'error' in report:
            print(f'  ERRO: {report["error"]}')
        else:
            print(f'  {report["turnos_auditados"]} turno(s) auditado(s) -> {out_path}')


if __name__ == '__main__':
    main()
