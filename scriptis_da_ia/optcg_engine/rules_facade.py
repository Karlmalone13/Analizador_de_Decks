"""
optcg_engine/rules_facade.py
============================
Fachada de regras usada pelo motor atual.

Este modulo e a ponte de migracao: o decision_engine continua funcionando com
Card/GameState atuais, mas deixa de ser o dono de regras puras. A cada fatia,
funcoes daqui podem passar a delegar para os modulos ActV3 oficiais
(card_power.py, validators.py, action_system.py, models.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decision_engine import Card


def effective_card_cost(card: "Card") -> int:
    """Custo efetivo no estado simplificado atual do decision_engine."""
    return max(0, card.cost + card.cost_buff + card.cost_buff_permanent)


def effective_card_power(card: "Card", your_turn: bool = True) -> int:
    """Poder efetivo no estado simplificado atual do decision_engine."""
    base_power = getattr(card, "base_power_override", None)
    if base_power is None:
        base_power = card.power
    don_power = card.don_attached * 1000 if your_turn else 0
    return base_power + card.power_buff + don_power


def card_matches_filter(card: "Card", filter_text: str = "", include_color: bool = False) -> bool:
    """Filtro textual usado pelos efeitos parseados do banco atual."""
    needle = (filter_text or "").lower()
    if not needle:
        return True

    fields = [
        getattr(card, "sub_types", ""),
        getattr(card, "name", ""),
        getattr(card, "card_type", ""),
    ]
    if include_color:
        fields.append(getattr(card, "color", ""))

    return any(needle in str(value).lower() for value in fields)


def eligible_cards(
    cards: list["Card"],
    *,
    cost_lte: int | None = None,
    cost_eq: int | None = None,
    power_lte: int | None = None,
    power_eq: int | None = None,
    power_gte: int | None = None,
    rested_only: bool = False,
    active_only: bool = False,
    filter_text: str = "",
    name_or_code: str = "",
    color: str = "",
    exclude_name: str = "",
    exclude_card: "Card | None" = None,
) -> list["Card"]:
    """Retorna cartas que passam nos filtros comuns de alvo."""
    out = []
    color_filter = (color or "").lower()
    exclude = (exclude_name or "").lower()

    for card in cards:
        if exclude_card is not None and card is exclude_card:
            continue
        if cost_lte is not None and card.cost > cost_lte:
            continue
        if cost_eq is not None and card.cost != cost_eq:
            continue
        if power_lte is not None and card.power > power_lte:
            continue
        if power_eq is not None and card.power != power_eq:
            continue
        if power_gte is not None and card.power < power_gte:
            continue
        if rested_only and not getattr(card, "rested", False):
            continue
        if active_only and getattr(card, "rested", False):
            continue
        if filter_text and not card_matches_filter(card, filter_text):
            continue
        if name_or_code:
            name_or_code_filter = name_or_code.lower()
            if (name_or_code_filter not in str(getattr(card, "name", "")).lower()
                    and name_or_code_filter not in str(getattr(card, "code", "")).lower()):
                continue
        if color_filter and color_filter not in str(getattr(card, "color", "")).lower():
            continue
        if exclude and exclude in str(getattr(card, "name", "")).lower():
            continue
        out.append(card)

    return out


def choose_highest_board_value(cards: list["Card"]) -> "Card | None":
    """Escolhe o alvo mais valioso segundo a heuristica atual."""
    return max(cards, key=lambda card: card.board_value()) if cards else None


def choose_highest_effective_power(
    cards: list["Card"],
    your_turn: bool = True,
) -> "Card | None":
    """Escolhe a carta com maior poder efetivo."""
    return max(cards, key=lambda card: card.effective_power(your_turn)) if cards else None
