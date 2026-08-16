"""
game_decks.py -- carrega os decks REAIS salvos pelo OPTCGSim.

Por que existe (pedido do usuario, 16/08/2026, bloco 565): as ferramentas de
calibracao do projeto (`gauntlet_matchup.py`, `decision_quality_report.py`,
`audit_real_losses.py`) so conheciam `decklists_raw.csv` -- decklists de
TORNEIO. O deck que o usuario de fato joga ao vivo, Marshall D. Teach
(OP16-080), **nao existe nesse CSV**: dos 209 decks com lider identificado
la, ZERO sao de Teach/Blackbeard (confirmado por varredura, e ja registrado
no CLAUDE.md junto com Krieg e Kid). Consequencia pratica: era impossivel
rodar `decision_quality_report --leader OP16-080`, ou seja, a ferramenta que
mede "o bot entende este deck?" nao funcionava justamente pro unico deck que
estava sendo testado em partida real.

O simulador guarda os decks do jogador em `<jogo>/Decks/*.deck`, num formato
de uma linha por carta (`NxCODIGO`), com o LIDER na primeira linha. Sao os
decks completos e reais -- melhor fonte que a reconstrucao parcial que
`logs/decks/*.json` faz a partir do combat log (essa so enxerga as cartas que
apareceram na partida).

Caminho configuravel por `OPTCG_DECKS_DIR`; o default e o mesmo caminho ja
hardcoded em `BOT/setup_bepinex.ps1`.
"""
from __future__ import annotations

import os
import re

DEFAULT_DECKS_DIR = r'E:\Games\OnePieceSimulador\Builds_Windows\Decks'

_LINHA = re.compile(r'^\s*(\d+)\s*x\s*([A-Za-z0-9\-_]+)\s*$', re.I)


def decks_dir() -> str:
    return os.environ.get('OPTCG_DECKS_DIR', DEFAULT_DECKS_DIR)


def parse_deck_file(path: str) -> tuple[str, list[str]] | None:
    """
    Le um `.deck` e devolve `(codigo_do_lider, [codigos das 50 cartas])`,
    ja expandido pela quantidade (`4xOP09-095` -> 4 entradas).

    Devolve None se o arquivo nao tiver nenhuma linha valida. NAO valida
    tamanho/legalidade aqui -- quem consome deve passar por `validar_deck`
    (fonte unica de regra de deck), pra isto nao virar uma segunda regra.
    """
    try:
        with open(path, encoding='utf-8-sig') as fh:
            linhas = fh.read().splitlines()
    except OSError:
        return None

    codigos: list[str] = []
    for ln in linhas:
        m = _LINHA.match(ln)
        if not m:
            continue
        qtd, code = int(m.group(1)), m.group(2).upper()
        codigos.extend([code] * qtd)

    if not codigos:
        return None
    return codigos[0], codigos[1:]


def listar_decks(diretorio: str | None = None) -> dict[str, str]:
    """{nome_do_deck: caminho} de todos os `.deck` encontrados."""
    d = diretorio or decks_dir()
    if not os.path.isdir(d):
        return {}
    return {os.path.splitext(f)[0]: os.path.join(d, f)
            for f in sorted(os.listdir(d)) if f.lower().endswith('.deck')}


def carregar_decks_do_jogo(cards_db, validar_deck_fn, diretorio: str | None = None):
    """
    Devolve `[(nome, (leader_card, cards, start_stage)), ...]` no MESMO formato
    que `_load_deck_list` produz a partir de `decklists_raw.csv`, pra poder ser
    usado de forma intercambiavel pelas ferramentas de calibracao.

    Decks que nao passam em `validar_deck` sao descartados com aviso -- alguns
    `.deck` da pasta sao antigos/ilegais pro pool de cartas atual, e entrar com
    deck invalido corromperia a medicao em silencio.
    """
    from optcg_engine.decision_engine import _make_card

    out = []
    for nome, caminho in listar_decks(diretorio).items():
        parsed = parse_deck_file(caminho)
        if not parsed:
            continue
        leader_code, card_codes = parsed
        if leader_code not in cards_db:
            continue

        leader = _make_card(leader_code, cards_db[leader_code])
        cards = [_make_card(c, cards_db[c]) for c in card_codes if c in cards_db]
        if len(cards) < 40:
            continue

        valido, _erros = validar_deck_fn(leader, cards, cards_db)
        if not valido:
            continue
        out.append((nome, (leader, cards, None)))
    return out
