# -*- coding: utf-8 -*-
"""
censo_padroes.py

Classifica as cartas "efeito_real" (texto presente, effects vazio) por
PADRAO ESTRUTURAL de texto, nao card a card. Gera uma tabela:
  padrao -> quantidade -> lista de IDs

Padroes do TODO (1 a 5) + padrao 6 (Activate:Main custo composto, tipo OP13-082).

Uso:
    python censo_padroes.py

Saida: imprime contagem por padrao + salva censo_padroes.json com os IDs.
"""
import json
import re
import sys

ANALYSIS_DB = 'card_analysis_db.json'
OUT_JSON = 'censo_padroes.json'


def carregar_efeito_real():
    with open(ANALYSIS_DB, encoding='utf-8') as f:
        db = json.load(f)

    verbos = ['k.o.', 'draw', 'play', 'rest', 'return', 'look at', 'trash',
              'give', 'gains', 'add']

    efeito_real = {}
    for cid, card in db.items():
        text = card.get('text', '').strip()
        if not text or card.get('effects'):
            continue
        # mesmo filtro counter_only / keyword_only do diagnostico anterior
        sem_counter = re.sub(r'\[counter\][^.]*\.?', '', text.lower()).strip()
        if sem_counter in ('', '.'):
            continue  # counter_only
        if not any(v in text.lower() for v in verbos):
            continue  # keyword_only
        efeito_real[cid] = card
    return efeito_real


def classificar(cid, card):
    """Retorna lista de padroes (pode casar em mais de um)."""
    text = card['text']
    t = text.lower()
    padroes = []

    # Padrao 1: custo-antes-do-efeito  "(cost): effect" com DON!!-N ou trash
    # ex: "DON!! -1 (...): If your Leader..." ou "DON!! 1: Add up to..."
    if re.search(r'don!!\s*-?\d+\s*\([^)]*\)\s*:', t) or re.search(r'don!!\s*-?\d+\s*:', t):
        padroes.append('1_custo_don_antes_efeito')
    if re.search(r'you may trash \d+ card[s]? from your hand[^:]*:', t):
        padroes.append('1_custo_trash_hand_antes_efeito')
    # Padrao 1b: custo entre parenteses SEM a palavra DON!! antes, tipo:
    # "(3) (You may rest the specified number of DON!! cards in your cost area.): efeito"
    if re.search(r'\(\d+\)\s*\(you may rest[^)]*\)\s*:', t):
        padroes.append('1b_custo_parenteses_rest_don')

    # Padrao 2: "place at the bottom of the deck" como remocao (bounce-to-deck)
    if re.search(r'place .*at the bottom of (the|your|the owner.?s) deck', t) or \
       re.search(r'return .* to the bottom of', t):
        padroes.append('2_bounce_to_deck')

    # Padrao 3: Rush/keyword condicional ao estado do oponente
    if re.search(r'gains? \[rush\]', t) and ('opponent' in t or 'your opponent' in t):
        padroes.append('3_rush_condicional_oponente')
    if re.search(r'gains? \[blocker\]', t) and 'if' in t:
        padroes.append('3_blocker_condicional')

    # Padrao 4: manipulacao de Life como verbo principal
    if re.search(r'(top|bottom) of (your|the owner.?s|your opponent.?s) life', t) or \
       re.search(r'look at .* life card', t) or \
       re.search(r'add .* to (the top|the bottom) of .* life', t):
        padroes.append('4_manipulacao_life')

    # Padrao 5: "play from your hand" (so from trash / from deck cobertos)
    if re.search(r'play up to \d+ .* from your hand', t):
        padroes.append('5_play_from_hand')

    # Padrao 6: Activate:Main com custo composto (rest DON + trash hand), tipo OP13-082
    if '[activate' in t or '[activate:' in t:
        custos_no_mesmo_bloco = 0
        if re.search(r'rest \d+ of your don', t):
            custos_no_mesmo_bloco += 1
        if re.search(r'trash \d+ card[s]? from your hand', t):
            custos_no_mesmo_bloco += 1
        if custos_no_mesmo_bloco >= 2:
            padroes.append('6_activate_custo_composto')

    # Padrao 7: protecao "cannot be K.O.'d in battle" (condicional ou nao)
    if re.search(r"cannot be k\.?o\.?'?d", t):
        padroes.append('7_protecao_nao_pode_ko')

    # Padrao 8: "set ... as active" (desrestar character/leader/DON proprio)
    if re.search(r'set (this|up to \d+ of your) .* as active', t):
        padroes.append('8_set_as_active')

    # Padrao 9: mill/looting do próprio deck "trash N cards from (the )?top of (your )?deck"
    if re.search(r'trash \d+ cards? from (the )?top of (your )?deck', t):
        padroes.append('9_mill_proprio_deck')

    if not padroes:
        padroes.append('0_nao_classificado')

    return padroes


def main():
    efeito_real = carregar_efeito_real()
    print(f'Total efeito_real carregado: {len(efeito_real)}\n')

    censo = {}
    for cid, card in efeito_real.items():
        padroes = classificar(cid, card)
        for p in padroes:
            censo.setdefault(p, []).append({'id': cid, 'name': card.get('name', '')})

    # ordena por tamanho desc
    ordem = sorted(censo.items(), key=lambda kv: -len(kv[1]))

    print('--- CENSO POR PADRAO ---')
    for padrao, cards in ordem:
        print(f'{padrao}: {len(cards)} cartas')

    total_classificadas = len(set(
        c['id'] for cards in censo.values() for c in cards
        if not c['id'] in censo.get('0_nao_classificado', [])
    ))
    nao_class = censo.get('0_nao_classificado', [])
    print(f'\nNao classificadas em nenhum padrao conhecido: {len(nao_class)}')

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(censo, f, indent=2, ensure_ascii=False)
    print(f'\nDetalhe completo salvo em {OUT_JSON}')

    print('\n--- Amostra: 0_nao_classificado (revisar manualmente, pode ser padrao novo) ---')
    for c in nao_class[:15]:
        print(f"  {c['id']} - {c['name']}")


if __name__ == '__main__':
    main()