"""
deck_profile.py  —  Extrator de PERFIL do deck (item 2 do PLANO_AVALIACAO_E_BUSCA.md)
=====================================================================================
Varre o card_effects_db de um deck e DERIVA os eixos de avaliação
específicos daquele deck, SEM citar carta nenhuma (generalização do
compute_game_plan). O resultado é um JSON inspecionável: o usuário lê e
critica em português; a evaluate_state (item 1) consome pra montar seus
termos; dobra como auditoria do parser (eixo esperado ausente = condição
não parseada).

Modo LEITURA por enquanto — não toca no motor. As 6 melhorias debatidas:
  1. peso por IMPACTO (cópias × magnitude do que a condição destrava), não contagem
  2. escadaria com saturação (degraus no histograma de thresholds)
  3. eixo com FILTRO (recurso qualificado, ex. corpos power-5000 no trash)
  4. estrutura de GARGALO (min(motor, combustível)) pra combos
  5. varredura dos DOIS lados (perfil do oponente muda valor do meu estado) — TODO no consumo
  6. eixos de INVERSÃO (life_lte: tomar dano = ativação, muda o SINAL)

Uso:
  python deck_profile.py Imu
  python deck_profile.py Imu --json perfil_imu.json
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path

# Gramática de arquétipo — FONTE ÚNICA reusada do analisador do front-end
# (deck_analyzer.py). O usuário nomeou o conceito: "isso é o que chamamos de
# arquétipo". Em vez de manter um vocabulário paralelo, o perfil do MOTOR
# converge com o do front (mesma família de sinal, prevista no plano). Só
# importamos as TABELAS (dados puros) + constantes; a lógica de varredura é
# nossa (card_effects_db é aninhado {gatilho:{steps}}, o do front é achatado).
from deck_analyzer import (ACTION_WEIGHTS, TRIGGER_RELIABILITY,
                           AGGRO, CONTROLE, RAMP, VIDA)

_DB_PATH = Path(__file__).parent / 'card_effects_db.json'
_DECKS_DIR = Path(r"E:\Games\OnePieceSimulador\Builds_Windows\Decks")

# Ações de DISRUPÇÃO/denial (miram o OPONENTE) — a 4ª família de eixo, que o
# Krieg exemplifica e a gramática anterior (só recurso/reanimação/inversão)
# não via. Universal: qualquer deck com essas ações ganha o eixo.
_DISRUPTION_ACTIONS = {
    'give_don_opp', 'lock_opp_don', 'lock_opp_character_refresh',
    'lock_opp_character_attack', 'rest_opp_character', 'debuff_power',
    'debuff_cost', 'bounce', 'ko', 'trash_character', 'negate_effect',
    'opp_trash_from_hand', 'place_opp_character_bottom_deck',
}

# Magnitude relativa do que cada AÇÃO/keyword destrava (proxy pro prior;
# a tunagem por self-play ajusta depois). Escala grosseira, só pra ORDENAR
# os eixos de forma sensata no cold-start.
_ACTION_MAGNITUDE = {
    'immunity': 30, 'negate_effect': 35, 'ko': 40, 'trash_character': 40,
    'bounce': 30, 'debuff_power': 20, 'gain_blocker': 25, 'gain_rush': 25,
    'gain_double_attack': 25, 'gain_unblockable': 20, 'buff_power': 15,
    'play_from_trash': 50, 'play_card': 30, 'give_don': 20,
    'draw': 20, 'look_top_deck': 15, 'add_to_hand': 15, 'add_from_trash': 25,
}
# Recursos "ruins" cuja condição INVERTE o sinal do termo (tomar/gastar = ativar)
_INVERSION_CONDS = {'life_lte'}
# RECURSOS acumuláveis reais que viram escadaria (whitelist — evita tratar
# gate/flag numérica como se fosse motor de recurso, ex: leader_multicolor,
# opp_turn_only, que apareciam como staircase espúria de peso ~0). Universal.
_RESOURCE_CONDS = {
    'trash_gte', 'trash_lte', 'don_gte', 'don_lte',
    'don_on_field_gte', 'don_on_field_lte', 'deck_gte', 'deck_lte',
    'hand_gte', 'events_in_trash_gte', 'chars_gte',
}


def _load_deck_codes(deck_name: str) -> list[tuple[int, str]]:
    path = _DECKS_DIR / f"{deck_name}.deck"
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        qty, code = line.split('x', 1)
        out.append((int(qty), code))
    return out


def _iter_blocks(card_eff: dict):
    """(trigger, block) de cada bloco de efeito com steps/conditions/costs."""
    for trig, block in (card_eff.get('effects', card_eff) or {}).items():
        if isinstance(block, dict) and ('steps' in block or 'conditions' in block or 'costs' in block):
            yield trig, block


def build_profile(deck_name: str) -> dict:
    db = json.loads(_DB_PATH.read_text(encoding='utf-8'))
    deck = _load_deck_codes(deck_name)

    # ── coleta bruta ──────────────────────────────────────────────────────────
    # threshold de recurso -> {valor: {'copias':N, 'payoffs':Counter, 'impacto':float}}
    resource_thresholds: dict[str, dict] = defaultdict(lambda: defaultdict(
        lambda: {'copias': 0, 'payoffs': defaultdict(int), 'impacto': 0.0}))
    inversions: dict[str, dict] = defaultdict(lambda: defaultdict(
        lambda: {'copias': 0, 'effects': defaultdict(int)}))
    reanim: list[dict] = []
    # disrupção -> {ação: {'copias':N, 'impacto':float}}  (peso × confiabilidade)
    disruption: dict[str, dict] = defaultdict(lambda: {'copias': 0, 'impacto': 0.0})
    # arquétipo (reusa vocabulário do deck_analyzer) -> pontuação por eixo
    arch_score: dict[str, float] = {AGGRO: 0.0, CONTROLE: 0.0, RAMP: 0.0, VIDA: 0.0}
    n_cards = 0

    for qty, code in deck:
        c = db.get(code)
        if not c:
            continue
        if (c.get('type') or '').upper() != 'LEADER':
            n_cards += qty
        for trig, block in _iter_blocks(c):
            conds = block.get('conditions', {})
            steps = block.get('steps', [])
            step_actions = [s.get('action') for s in steps]
            # confiabilidade do gatilho: on_play/main valem cheio, counter/trigger
            # /on_ko valem menos (reusado do deck_analyzer — melhoria de impacto)
            rel = TRIGGER_RELIABILITY.get(trig, 0.7)
            block_impact = sum(_ACTION_MAGNITUDE.get(a, 5) for a in step_actions) * rel

            # arquétipo: soma peso-de-ação × confiabilidade (mesma conta do front)
            for a in step_actions:
                for arche, pts in ACTION_WEIGHTS.get(a, {}).items():
                    arch_score[arche] += pts * rel * qty

            for k, v in conds.items():
                if k in _INVERSION_CONDS:
                    node = inversions[k][v]
                    node['copias'] += qty
                    for a in step_actions:
                        node['effects'][a] += qty
                    continue
                # só recursos acumuláveis REAIS viram escadaria (whitelist)
                if k in _RESOURCE_CONDS and isinstance(v, (int, float)):
                    node = resource_thresholds[k][v]
                    node['copias'] += qty
                    node['impacto'] += qty * block_impact
                    for a in step_actions:
                        node['payoffs'][a] += qty

            for s in steps:
                a = s.get('action')
                # reanimação (motor de win-con) — carrega o FILTRO (melhoria 3)
                if a in ('play_from_trash', 'add_from_trash'):
                    reanim.append({
                        'code': code, 'name': c.get('name', '?'), 'copias': qty,
                        'count': s.get('count', 1),
                        'filter': s.get('filter_type') or s.get('filter_name') or '',
                        'power_eq': s.get('power_eq'),
                        'cost': c.get('cost'),
                    })
                # disrupção (4ª família) — ação que mira o oponente
                if a in _DISRUPTION_ACTIONS:
                    node = disruption[a]
                    node['copias'] += qty
                    node['impacto'] += qty * _ACTION_MAGNITUDE.get(a, 5) * rel

    # ── monta os eixos derivados ──────────────────────────────────────────────
    axes = []

    # 4ª família: DISRUPÇÃO/denial (miram o oponente) — o eixo do Krieg
    if disruption:
        acoes = sorted(disruption.items(), key=lambda kv: kv[1]['impacto'], reverse=True)
        axes.append({
            'id': 'disruption', 'kind': 'disruption',
            'nota': ('negar recurso/ação do oponente (DON, lock, rest, remoção, '
                     'negate) — o valor está em REDUZIR o estado dele, não crescer o meu'),
            'acoes': [{'action': a, 'dependentes': d['copias'],
                       'impacto': round(d['impacto'], 1)} for a, d in acoes],
            'prior_weight': round(sum(d['impacto'] for _, d in acoes), 1),
        })

    # 1+2+3: recursos com escadaria de threshold (saturação nos degraus)
    for res, degraus in resource_thresholds.items():
        steps_out = []
        for val in sorted(degraus):
            node = degraus[val]
            payoffs = sorted(node['payoffs'], key=node['payoffs'].get, reverse=True)
            # degrau com 1 cópia e impacto baixo = ruído (ex: trash_gte 19 do
            # Empty Throne) — marca pra poda, a ablação confirma depois
            pruned = node['copias'] <= 1
            steps_out.append({
                'threshold': val, 'dependentes': node['copias'],
                'impacto': round(node['impacto'], 1),
                'payoffs': payoffs, 'pruned': pruned,
            })
        total_imp = sum(s['impacto'] for s in steps_out if not s['pruned'])
        axes.append({
            'id': f'{res}_staircase', 'kind': 'resource_staircase',
            'resource': res,
            'nota': ('progresso até cada degrau vale nota; SATURA após o degrau '
                     '(mais recurso não vale nada até o próximo)'),
            'steps': steps_out,
            'prior_weight': round(total_imp, 1),
        })

    # 4: gargalo de reanimação — min(acesso ao motor, combustível qualificado)
    if reanim:
        motor = max(reanim, key=lambda r: r['count'])  # o de maior alcance = win-con
        axes.append({
            'id': 'reanimation_bottleneck', 'kind': 'bottleneck',
            'nota': 'valor = min(motor acessível na mão/buscável, combustível qualificado no trash)',
            'engine_card': {'code': motor['code'], 'name': motor['name'],
                            'reanima_ate': motor['count'], 'custo': motor['cost']},
            'fuel_filter': {'filter_type': motor['filter'], 'power_eq': motor['power_eq'],
                            'zona': 'trash'},
            'prior_weight': round(_ACTION_MAGNITUDE['play_from_trash'] * motor['count'], 1),
        })

    # 6: eixos de inversão
    for cond, vals in inversions.items():
        for v, node in vals.items():
            effs = sorted(node['effects'], key=node['effects'].get, reverse=True)
            axes.append({
                'id': f'{cond}_inversion', 'kind': 'inversion',
                'condition': f'{cond} {v}',
                'nota': ('recurso "ruim" que ATIVA cartas: tomar dano/gastar é '
                         'parcialmente positivo, achata a curva de pânico'),
                'dependentes': node['copias'], 'effects': effs,
                'prior_weight': round(node['copias'] * 8.0, 1),
            })

    # descarta eixos de peso desprezível (ruído estrutural — a ablação do
    # item 5 mataria mesmo; não poluir o artefato que o usuário lê)
    axes = [a for a in axes if a.get('prior_weight', 0) >= 5]
    axes.sort(key=lambda a: a.get('prior_weight', 0), reverse=True)

    # arquétipo normalizado (mix % que soma 100) — o "guarda-chuva" do deck,
    # reusando a gramática do deck_analyzer. Os derived_axes REFINAM dentro dele.
    total_arch = sum(arch_score.values())
    arch_mix = ({a: round(100 * v / total_arch, 1)
                 for a, v in sorted(arch_score.items(), key=lambda kv: -kv[1]) if v > 0}
                if total_arch else {})
    dominante = max(arch_mix, key=arch_mix.get) if arch_mix else 'Indefinido'

    return {
        'deck': deck_name,
        'n_cards': n_cards,
        'archetype': {'dominante': dominante, 'mix': arch_mix},
        'generic_axes': ['vida', 'board', 'mao', 'don', 'cobertura_counter', 'tempo'],
        'derived_axes': axes,
        'nota_geral': ('generic_axes valem pra QUALQUER deck; derived_axes saem '
                       'da varredura deste deck. Pesos aqui são PRIORS de '
                       'cold-start (impacto×dependentes) — a tunagem por '
                       'self-play (item 5) ajusta e a ablação mata eixo inútil.'),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('deck')
    ap.add_argument('--json', default='')
    args = ap.parse_args()
    prof = build_profile(args.deck)
    txt = json.dumps(prof, indent=2, ensure_ascii=False)
    print(txt)
    if args.json:
        Path(args.json).write_text(txt, encoding='utf-8')
        print(f"\n-> salvo em {args.json}")


if __name__ == '__main__':
    main()
