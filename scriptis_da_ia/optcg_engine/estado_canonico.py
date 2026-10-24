# -*- coding: utf-8 -*-
"""ESTADO CANONICO e DIARIO DE DECISOES -- o gabarito da paridade do nucleo Rust
(PLANO_MOTOR_FORTE.md, fase A; `optcg_core/ESPEC.md` secao 5).

`canonico(p, opp)` devolve uma estrutura deterministica, independente de
implementacao, com TUDO que e REGRA do estado da partida: zonas (na ordem), estado
de cada instancia de carta, DON, turno, travas, filas. Ficam FORA so estatistica e
heuristica (contadores de dano/kill/jogadas, censo/plano do deck) -- o nucleo novo
nao reproduz heuristica, quem decide e a busca.

`DIARIO` grava, quando ligado, a sequencia de decisoes de uma partida: cada jogada
principal (com o estado canonico antes e depois) e cada escolha interna (familia,
numero de opcoes, indice escolhido). O nucleo Rust repete as MESMAS escolhas e
compara o estado depois de cada jogada. So grava; nao muda nenhuma decisao.
"""
from __future__ import annotations

import dataclasses

# Estatistica/heuristica do GameState -- fora da comparacao.
_FORA_GS = {'dmg_dealt', 'char_kill_value', 'don_spent_on_combat', 'chars_played',
            'counters_used', 'searchers_used', 'triggers_activated', 'full_deck_census',
            'full_deck_codes', 'full_deck_plan', 'full_deck_profile',
            'self_play_info_hidden', 'leader', 'deck', 'hand', 'field_chars',
            'field_stage', 'life', 'trash'}
_ZONAS = ('deck', 'hand', 'field_chars', 'life', 'trash')

DIARIO = {'on': False, 'eventos': []}


def _valor(v):
    """Valor serializavel e deterministico (sets ordenados, dicts por chave)."""
    if isinstance(v, (set, frozenset)):
        return sorted(_valor(x) for x in v)
    if isinstance(v, dict):
        return {str(k): _valor(v[k]) for k in sorted(v, key=str)}
    if isinstance(v, (list, tuple)):
        return [_valor(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if hasattr(v, 'data') and hasattr(getattr(v, 'data', None), 'code'):
        return getattr(v.data, 'code')          # referencia a carta -> codigo
    return v


def carta(c) -> dict | None:
    """Estado de UMA instancia de carta: codigo + todos os campos mutaveis."""
    if c is None:
        return None
    out = {'code': c.data.code}
    for f in dataclasses.fields(c):
        if f.name == 'data':
            continue
        out[f.name] = _valor(getattr(c, f.name))
    for k, v in vars(c).items():                # marcas criadas na hora (regra)
        if k.startswith('_') and k not in out:
            out[k] = _valor(v)
    return out


# Conjuntos de `id()` de objeto (memoria) -- viram o LUGAR das cartas.
_IDS = {'revealed_deck', 'revealed_life', 'revealed_to_opponent'}


def _lugares_de_ids(s, ids) -> list:
    out = []
    for z in ('leader', 'stage') + _ZONAS:
        cs = ([s.leader] if z == 'leader' else [s.field_stage] if z == 'stage'
              else list(getattr(s, z) or []))
        for i, c in enumerate(cs):
            if c is not None and id(c) in ids:
                out.append([z, i])
    return out


def jogador(s) -> dict:
    out = {'leader': carta(s.leader), 'stage': carta(s.field_stage)}
    for z in _ZONAS:
        out[z] = [carta(c) for c in (getattr(s, z) or [])]
    for f in dataclasses.fields(s):
        if f.name in _FORA_GS:
            continue
        v = getattr(s, f.name)
        if f.name in _IDS:
            # `id()` muda a cada execucao: guarda ONDE estao as cartas reveladas
            out[f.name] = _lugares_de_ids(s, set(v or ()))
        else:
            out[f.name] = _valor(v)
    return out


def canonico(p, opp) -> dict:
    """Estado canonico do ponto de vista de `p` (quem esta agindo)."""
    return {'ativo': jogador(p), 'oponente': jogador(opp)}


def _onde(c, s) -> list:
    """Localiza uma carta pelo LUGAR (zona, indice) -- identidade independente de
    implementacao (o nucleo nao tem os mesmos objetos)."""
    if c is None:
        return None
    if c is s.leader:
        return ['leader', 0]
    if c is s.field_stage:
        return ['stage', 0]
    for z in _ZONAS:
        for i, x in enumerate(getattr(s, z) or []):
            if x is c:
                return [z, i]
    return ['?', getattr(getattr(c, 'data', None), 'code', None)]


def descreve_acao(acao, p, opp) -> dict:
    """A jogada principal em termos de LUGAR: tipo, ator, alvo (de quem), DON."""
    kind = acao[1] if len(acao) > 1 else None
    ator = acao[2] if len(acao) > 2 else None
    tt = acao[3] if len(acao) > 3 else None
    alvo = acao[4] if len(acao) > 4 else None
    don = acao[5] if len(acao) > 5 else None
    d = {'tipo': kind, 'ator': _onde(ator, p) if hasattr(ator, 'data') else _valor(ator),
         'alvo_tipo': tt, 'don': _valor(don)}
    if hasattr(alvo, 'data'):
        lado = 'oponente' if _onde(alvo, opp)[0] != '?' else 'ativo'
        d['alvo'] = [lado] + (_onde(alvo, opp) if lado == 'oponente' else _onde(alvo, p))
    else:
        d['alvo'] = _valor(alvo)
    return d


def registra(evento: dict) -> None:
    if DIARIO['on']:
        DIARIO['eventos'].append(evento)
