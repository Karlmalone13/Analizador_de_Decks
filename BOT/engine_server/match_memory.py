"""
Memoria de informacao revelada DA PARTIDA AO VIVO (persistencia entre /decide).

Problema que resolve (ver optcg_engine/MEMORIA_REVEALS.md, secao PENDENTE):
cada /decide reconstroi o GameState do zero a partir do DTO do plugin --
qualquer coisa aprendida em turnos anteriores (carta do oponente revelada
pelo Arlong, topo da vida visto por peek, etc.) se perdia. Esta camada
acumula, por partida, QUAIS cartas ja tiveram a identidade revelada ao bot,
chaveadas por `deckUniqueId` (estavel a partida inteira no jogo real --
`id(card)` do engine so e estavel dentro de um processo/rollout, por isso
NAO serve aqui).

Uso junto com o mascaramento de informacao oculta em `_dto_to_gs`
(hide_hidden): o DTO do plugin traz a mao/vida REAIS do oponente (o cliente
tem o estado inteiro em memoria), mas o engine so pode usar a identidade das
cartas cujo uid esta registrado aqui -- o resto vira placeholder UNKNOWN,
como um humano veria. Regra do usuario (21/07): o bot joga como humano vs
humano; so conhece o que foi revelado durante o jogo.

Zonas rastreadas:
  opp_hand  -- carta da mao do oponente revelada (Arlong reveal_opp_hand etc.)
  opp_life  -- carta da vida do oponente revelada
  own_life  -- carta da PROPRIA vida revelada (Katakuri/OP15-119; a propria
               vida tambem e informacao oculta no jogo real)
  opp_deck  -- topo do deck do oponente visto (Pudding peek_opp_deck_top)

Quem popula: o endpoint /reveal do engine_server (chamado pelo plugin quando
o jogo mostra uma carta ao bot -- ConfirmRevealedCard etc.; a chamada C# e
pendente, ver HANDOFF). Reset por partida no /mulligan.

A invalidacao e implicita: conhecer o uid nao diz em que zona a carta esta
AGORA -- o cruzamento e feito contra o DTO atual (se o uid nao esta mais na
mao do oponente, ele simplesmente nao casa com nenhum CardDto da mao e nao
re-injeta nada). Mesmo espirito da limpeza lazy de known_hand_cards().
"""
from __future__ import annotations

ZONES = ("opp_hand", "opp_life", "own_life", "opp_deck")


class MatchMemory:
    def __init__(self) -> None:
        self._known: dict[str, set[int]] = {z: set() for z in ZONES}

    def reset(self) -> None:
        """Partida nova (chamado no /mulligan)."""
        for z in ZONES:
            self._known[z].clear()

    def note(self, zone: str, uids: list[int] | set[int]) -> int:
        """Registra uids revelados na zona. Retorna quantos novos."""
        if zone not in self._known:
            return 0
        antes = len(self._known[zone])
        self._known[zone].update(int(u) for u in uids)
        return len(self._known[zone]) - antes

    def is_known(self, zone: str, uid: int) -> bool:
        return uid in self._known.get(zone, ())

    def known(self, zone: str) -> set[int]:
        return set(self._known.get(zone, ()))

    def snapshot(self) -> dict:
        """Para telemetria/debug: contagem por zona."""
        return {z: len(s) for z, s in self._known.items()}
