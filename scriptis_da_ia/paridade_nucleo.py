#!/usr/bin/env python
"""TESTE DIFERENCIAL do nucleo Rust (`optcg_core`) contra o motor Python
(PLANO_MOTOR_FORTE.md fase A; `optcg_core/ESPEC.md` secao 5).

Joga partidas no motor Python com o DIARIO ligado e confere, no nucleo Rust:
  1. IDA E VOLTA: o Rust le e reescreve cada estado canonico sem perder nada;
  2. INICIO DE TURNO: de `turno_inicio` o Rust aplica contadores/refresh/compra/DON
     e tem que dar o `main_inicio` do Python, campo a campo.
Turnos com efeito de inicio de turno que o nucleo ainda nao tem (reativos
`opp_turn`, trava de refresh do Stage) sao PULADOS e contados -- onda de efeitos.

    python paridade_nucleo.py --partidas 20 --seed 1000
"""
import argparse
import json
import os
import random
import sys

os.environ.setdefault('PYTHONHASHSEED', '0')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import optcg_core  # noqa: E402
from optcg_engine import decision_engine as de, estado_canonico as ec  # noqa: E402
from gerar_selfplay_dataset import _load_deck_list  # noqa: E402

_REATIVAS = de.OPTCGMatch._OPP_TURN_REACTIVE_ACTIONS
# Onda de efeitos 1 no nucleo: jogadas cujos passos de efeito estao TODOS aqui
# vao para o Rust com a fila de decisoes do efeito.
_ONDA = {'look_top_deck', 'add_to_hand', 'deck_bottom_rest', 'trash_rest', 'draw',
         'gain_life', 'add_don', 'set_don_active', 'ko', 'rest_opp_character', 'debuff_power', 'buff_power', 'give_don', 'play_from_trash', 'play_card', 'redirect_attack_target', 'activate_trash_event_main',
         '#custo_jogar', 'attack_life', 'life_to_hand', 'add_from_trash', 'deck_reorder_rest', 'deck_top_rest', 'buff_power_per_count', 'lock_opp_blocker_turn', 'custo:rest_any_don', 'custo:return_active_don_to_don_deck', 'custo:life_to_hand', 'bounce', 'place_opp_character_bottom_deck', 'negate_effect', 'trash_from_hand', 'peek_opp_deck_top', 'trash_own_life', 'gain_banish', 'gain_rush_character', 'transfer_don', 'activate_main_effect', 'hand_to_deck', 'deal_damage', 'give_don_either_side', 'self_cant_play', 'give_don_opp', 'gain_blocker', 'gain_rush', 'set_active', 'lock_opp_character_attack', 'lock_opp_cannot_be_rested', 'lock_opp_character_refresh', 'custo:rest_self', 'custo:rest_own_card', 'custo:rest_own_character', 'custo:trash_self', 'custo:give_don_opp', '#passiva_keyword', '#try_counter_event_power', '#try_counter_event_debuff', 'custo:trash_from_hand', 'custo:don_minus', 'custo:rest_don'}


def _tem_efeito_de_inicio(estado: dict) -> bool:
    """O inicio deste turno dispara efeito que o nucleo ainda nao modela?"""
    op = estado['oponente']
    for c in [op['leader'], op['stage']] + op['field_chars']:
        if c and any(s.get('action') in _REATIVAS for s in
                     de.get_card_effects(c['code']).get('opp_turn', {}).get('steps', [])):
            return True
    for lado in ('ativo', 'oponente'):
        st = estado[lado]['stage']
        if st and any(s.get('action') == 'lock_both_character_refresh' for s in
                      de.get_card_effects(st['code']).get('passive', {}).get('steps', [])):
            return True
    return False


def _primeira_diferenca(a, b, cam=''):
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return cam, a, b
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f'{cam}/{k}', k in a, k in b
            r = _primeira_diferenca(a[k], b[k], f'{cam}/{k}')
            if r:
                return r
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f'{cam} (tamanho)', len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            r = _primeira_diferenca(x, y, f'{cam}[{i}]')
            if r:
                return r
        return None
    return None if a == b else (cam, a, b)


def tabela_de_cartas(m) -> dict:
    """Dados IMPRESSOS das cartas da partida, no formato `optcg_core::cartas::InfoCarta`."""
    out = {}
    for s in (m.state_a, m.state_b):
        for c in [s.leader] + list(s.deck) + list(s.hand) + list(s.life) + list(s.field_chars) +                 list(s.trash) + ([s.field_stage] if s.field_stage else []):
            if c is None or c.code in out:
                continue
            ef = de.get_card_effects(c.code)
            pas = ef.get('passive', {})
            custo_ef = any(st.get('target') == 'own_play_self'
                           and st.get('action') in ('debuff_cost', 'set_play_cost')
                           for st in pas.get('steps', []))
            reduz = any(st.get('action') == 'buff_cost' and st.get('target') == 'own_play_hand'
                        for b in ef.values() if isinstance(b, dict) for st in b.get('steps', []))
            out[c.code] = {'cost': int(c.data.cost), 'power': int(c.data.power),
                           'counter': int(c.data.counter), 'card_type': c.data.card_type,
                           'has_trigger': bool(c.data.has_trigger),
                           'don_cond': c.data.don_cond_keywords_dict(),
                           'custo_por_efeito': custo_ef, 'reduz_custo_mao': reduz,
                           'name': c.data.name or '', 'sub_types': c.data.sub_types or '',
                           'color': c.data.color or '', 'card_text': c.data.card_text or '',
                           'attribute': getattr(c.data, 'attribute', '') or '',
                           'alternate_names': list(getattr(c.data, 'alternate_names', ()) or ()),
                           'efeitos': ef}
    return out


def diario_de(seed: int) -> list:
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    ec.DIARIO.update(on=True, eventos=[], passos=0, acoes=[])
    try:
        m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
        m.setup()
        optcg_core.carrega_cartas(json.dumps(tabela_de_cartas(m)))
        for n in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if n % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            o = m.state_b if p is m.state_a else m.state_a
            if m.play_turn(p, o):
                break
    finally:
        ev = list(ec.DIARIO['eventos'])
        ec.DIARIO.update(on=False, eventos=[])
    return ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=10)
    ap.add_argument('--seed', type=int, default=1000)
    a = ap.parse_args()
    tot = {'ida_volta': [0, 0], 'inicio_turno': [0, 0], 'fim_turno': [0, 0], 'pulados': 0,
           'fim_com_efeito': 0}
    jog = {}      # tipo -> [identicas, conferidas, nao_suportadas, com_efeito]
    motivos = {}
    faltam = {}
    divs = []
    for i in range(a.partidas):
        ev = diario_de(a.seed + i)
        for e in ev:
            for k in ('estado', 'antes', 'depois'):
                if k in e:
                    s = json.dumps(e[k])
                    volta = json.loads(optcg_core.ida_e_volta(s))
                    tot['ida_volta'][1] += 1
                    if _primeira_diferenca(e[k], volta) is None:
                        tot['ida_volta'][0] += 1
                    elif len(divs) < 5:
                        divs.append(('ida_volta', a.seed + i, _primeira_diferenca(e[k], volta)))
        for j, e in enumerate(ev):
            if e['tipo'] != 'turno_inicio':
                continue
            alvo = next((x for x in ev[j + 1:] if x['tipo'] == 'main_inicio'), None)
            if alvo is None:
                continue
            if _tem_efeito_de_inicio(e['estado']):
                tot['pulados'] += 1
                continue
            r = json.loads(optcg_core.inicio_de_turno(json.dumps(e['estado']), e['global_turn']))
            tot['inicio_turno'][1] += 1
            d = _primeira_diferenca(alvo['estado'], r)
            if d is None:
                tot['inicio_turno'][0] += 1
            elif len(divs) < 12:
                divs.append(('inicio_turno', a.seed + i, d))
        for j, e in enumerate(ev):
            if e['tipo'] != 'fim_antes':
                continue
            alvo = next((x for x in ev[j + 1:] if x['tipo'] == 'fim_depois'), None)
            if alvo is None:
                continue
            if alvo['passos'] != e['passos']:
                tot['fim_com_efeito'] += 1
                continue
            r = json.loads(optcg_core.fim_de_turno(json.dumps(e['estado'])))
            tot['fim_turno'][1] += 1
            d = _primeira_diferenca(alvo['estado'], r)
            if d is None:
                tot['fim_turno'][0] += 1
            elif len(divs) < 12:
                divs.append(('fim_turno', a.seed + i, d))
        dec = {}
        for e in ev:
            if e['tipo'] == 'jogada_inicio':
                dec = {}
            elif e['tipo'] == 'don_ataque':
                dec['don_ataque'] = e['qtd']
            elif e['tipo'] == 'bloqueio':
                dec['bloqueio'] = e['carta']
            elif e['tipo'] == 'counter_cartas':
                dec['counter_cartas'] = e['cartas']
            elif e['tipo'] == 'campo_cheio':
                dec['campo_cheio'] = e['sai']
            elif e['tipo'] in ('escolha_efeito', 'paga_custo', 'veredito_efeito'):
                dec.setdefault('efeito', []).append(e)
            elif e['tipo'] == 'jogada':
                t = e['acao']['tipo']
                c = jog.setdefault(t, [0, 0, 0, 0])
                if e.get('passos_efeito', 0):
                    if not (t in ('play', 'attack', 'activate') and set(e.get('acoes_efeito', [])) <= _ONDA):
                        c[3] += 1
                        for r_ in set(e.get('acoes_efeito', [])) - _ONDA:
                            faltam[r_] = faltam.get(r_, 0) + 1
                        continue
                    t = t + '+efeito'
                    c = jog.setdefault(t, [0, 0, 0, 0])
                elif t in ('play', 'attack', 'activate'):
                    # sem passo de efeito: as decisoes de efeito (veredito sem custo) ficam
                    dec.setdefault('efeito', [])
                d = dict(dec)
                if 'bloqueio' in d and d['bloqueio'] is None:
                    d['bloqueio'] = 'nenhum'      # null viraria "sem registro" no Rust
                st, r, venceu = optcg_core.aplica_jogada(json.dumps(e['antes']), json.dumps(e['acao']),
                                                          json.dumps(d))
                if st != 'ok':
                    c[2] += 1
                    motivos[r] = motivos.get(r, 0) + 1
                    continue
                c[1] += 1
                dif = _primeira_diferenca(e['depois'], json.loads(r))
                if dif is None and venceu == e['venceu']:
                    c[0] += 1
                elif len(divs) < 15:
                    divs.append((f'jogada {t}', a.seed + i, dif or ('venceu', e['venceu'], venceu)))
    for t, (ok, n, nao, efe) in sorted(jog.items()):
        print(f'jogada {t:11s} {ok}/{n} identicas ({100 * ok / max(n, 1):.1f}%) | '
              f'nao suportadas {nao} | com efeito {efe} (fora desta onda)')
    print('   fora da onda:', ', '.join(f'{k}={v}' for k, v in sorted(faltam.items(), key=lambda x: -x[1])[:25]))
    for m_, n_ in sorted(motivos.items(), key=lambda x: -x[1]):
        print(f'   nao suportado: {m_} ({n_})')
    for k in ('ida_volta', 'inicio_turno', 'fim_turno'):
        ok, n = tot[k]
        print(f'{k:14s} {ok}/{n} identicos ({100 * ok / max(n, 1):.1f}%)')
    print(f'turnos pulados (efeito de inicio de turno ainda fora do nucleo): {tot["pulados"]}')
    print(f'fins de turno com efeito (fora desta onda): {tot["fim_com_efeito"]}')
    for d in divs:
        print('DIVERGE', d[0], 'seed', d[1], 'campo', d[2][0], '| python', repr(d[2][1])[:60],
              '| rust', repr(d[2][2])[:60])
    return 0 if (all(tot[k][0] == tot[k][1] for k in ('ida_volta', 'inicio_turno', 'fim_turno'))
                 and all(v[0] == v[1] for v in jog.values())) else 1


if __name__ == '__main__':
    sys.exit(main())
