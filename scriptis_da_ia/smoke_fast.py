"""
Fast smoke for the live OPTCGSim bot loop.

This is intentionally small. The old smoke_test.py is now a broad regression
suite; use this file before live tests and reserve smoke_test.py for deeper
engine/parser changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from optcg_engine.decision_engine import (  # noqa: E402
    Card,
    CardData,
    DecisionEngine,
    EffectExecutor,
    GameState,
    OPTCGMatch,
    _make_card,
    get_card_effects,
    load_cards_db,
)
from optcg_engine import sim_bridge  # noqa: E402


FAIL = 0


def check(label: str, cond: bool) -> None:
    global FAIL
    status = "OK" if cond else "FALHOU"
    if not cond:
        FAIL += 1
    print(f"[{status}] {label}")


def mk(
    code: str,
    name: str,
    power: int = 5000,
    cost: int = 4,
    sub_types: str = "",
    card_type: str = "CHARACTER",
    color: str = "Black",
) -> Card:
    return Card(
        data=CardData(
            code=code,
            name=name,
            card_type=card_type,
            color=color,
            cost=cost,
            power=power,
            sub_types=sub_types,
        )
    )


cards = load_cards_db("cards_rows.csv")


def real_card(code: str) -> Card:
    return _make_card(code, cards[code])


def test_turn_order_imu_prefers_second() -> None:
    deck_path = Path(r"E:\Games\OnePieceSimulador\Builds_Windows\Decks\Imu.deck")
    if not deck_path.exists():
        print("[SKIP] deck Imu.deck nao encontrado")
        return
    codes: list[str] = []
    for line in deck_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        qty, code = line.split("x", 1)
        codes.extend([code] * int(qty))
    out = sim_bridge.choose_turn_order(codes)
    check("Imu escolhe ir segundo pelo plano de recurso/combo", out.get("goFirst") is False)


def test_empty_throne_beats_direct_five_elders_play() -> None:
    me = GameState(leader=real_card("OP13-079"), don_available=10)
    opp = GameState(leader=mk("OP07-019", "Jewelry Bonney", card_type="LEADER", color="Green"))
    stage = real_card("OP13-099")
    five = real_card("OP13-082")
    me.field_stage = stage
    me.hand = [five, real_card("OP13-091"), real_card("OP13-089")]
    for code in ("OP13-083", "OP13-084", "OP13-080", "OP13-091", "OP13-089"):
        me.trash.append(real_card(code))

    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    eng = DecisionEngine(me, opp)
    actions = match._generate_and_score_actions(me, opp, eng)
    top = actions[0] if actions else None
    check(
        "Empty Throne ativa antes de play direto do Five Elders",
        bool(top and top[1] == "activate" and getattr(top[2], "code", "") == "OP13-099"),
    )
    check("play direto de OP13-082 bloqueado quando stage economiza DON",
          match._score_play_action(five, eng) <= -900)


def test_ground_death_no_low_value_negate() -> None:
    me = GameState(leader=real_card("OP13-079"), don_available=8)
    opp = GameState(leader=mk("OP11-021", "Jinbe", card_type="LEADER", color="Green"))
    opp.field_chars = [mk("OP06-025", "Camie", power=2000, cost=1, color="Green")]
    ground = real_card("OP14-096")
    me.hand = [ground]
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    score = match._score_play_action(ground, DecisionEngine(me, opp))
    check("Ground Death nao gasta DON negando Camie sem texto futuro relevante", score < 0)


def test_imu_waits_for_active_elder_attack() -> None:
    me = GameState(leader=real_card("OP13-079"), don_available=8)
    opp = GameState(leader=mk("OP11-021", "Jinbe", card_type="LEADER", color="Green"))
    saturn = mk(
        "OP13-083",
        "St. Jaygarcia Saturn",
        power=5000,
        cost=5,
        sub_types="Five Elders/Celestial Dragons",
    )
    me.field_chars = [saturn]
    me.hand = [mk("X1", "fodder 1"), mk("X2", "fodder 2")]
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    am = get_card_effects("OP13-079").get("activate_main", {})
    before = match._should_activate_main(me.leader, am, me, opp)
    saturn.rested = True
    after = match._should_activate_main(me.leader, am, me, opp)
    check("Imu nao usa draw/trash antes de Elder ativo atacar", before[0] is False)
    check("Imu libera draw/trash depois do Elder restado", after[0] is True)


def test_nusjuro_rush_at_trash_7() -> None:
    me = GameState(leader=real_card("OP13-079"), don_available=7, turn=5)
    opp = GameState(leader=mk("OP11-051", "Donquixote Doflamingo", card_type="LEADER", color="Purple"), turn=5)
    nusjuro = real_card("OP13-080")
    nusjuro.just_played = True
    me.field_chars = [nusjuro]
    for code in ("OP13-083", "OP13-084", "OP13-085", "OP13-086", "OP13-089", "OP13-091", "OP13-096"):
        me.trash.append(real_card(code))

    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    eng = DecisionEngine(me, opp)
    actions = match._generate_and_score_actions(me, opp, eng)
    attacks = [a for a in actions if a[1] == "attack" and getattr(a[2], "code", "") == "OP13-080"]
    check("Nusjuro com 7 no trash ganha Rush e entra na lista de ataques", bool(attacks))
    if attacks:
        ok, reason = sim_bridge.can_execute_action(attacks[0], me)
        check(f"bridge aceita ataque do Nusjuro com Rush condicional ({reason})", ok)


def test_nusjuro_rush_known_in_hand_for_planner() -> None:
    me = GameState(leader=real_card("OP13-079"), don_available=7, turn=5)
    opp = GameState(leader=mk("OP11-051", "Donquixote Doflamingo", card_type="LEADER", color="Purple"), turn=5)
    nusjuro = real_card("OP13-080")
    me.hand = [nusjuro]
    for code in ("OP13-083", "OP13-084", "OP13-085", "OP13-086", "OP13-089", "OP13-091", "OP13-096"):
        me.trash.append(real_card(code))

    DecisionEngine(me, opp)
    check("planner reconhece Rush condicional do Nusjuro ainda na mao", nusjuro.has_rush)


def test_jinbe_grants_play_turn_character_attack() -> None:
    me = GameState(leader=real_card("OP11-021"), don_available=6, turn=5)
    opp = GameState(leader=mk("OP13-079", "Imu", card_type="LEADER", color="Black"), turn=5)
    jinbe = real_card("OP11-031")
    new_fishman = real_card("OP14-049")
    new_fishman.just_played = True
    opp.field_chars = [mk("XOPP", "active target", power=5000, cost=4, color="Black")]
    me.field_chars = [jinbe, new_fishman]

    effects = get_card_effects("OP11-031")
    check("OP11-031 recupera Activate Main de ataque no turno de entrada", "activate_main" in effects)
    EffectExecutor(me, opp).execute(jinbe, "activate_main")
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    actions = match._generate_and_score_actions(me, opp, DecisionEngine(me, opp))
    fish_attacks = [a for a in actions if a[1] == "attack" and getattr(a[2], "code", "") == "OP14-049"]
    leader_attacks = [a for a in fish_attacks if a[3] == "leader"]
    char_attacks = [a for a in fish_attacks if a[3] == "character"]
    check("Jinbe OP11-031 permite Fish-Man recem-baixado atacar Character", bool(char_attacks))
    check("Jinbe OP11-031 nao transforma isso em ataque ao Leader", not leader_attacks)


def main() -> int:
    test_turn_order_imu_prefers_second()
    test_empty_throne_beats_direct_five_elders_play()
    test_ground_death_no_low_value_negate()
    test_imu_waits_for_active_elder_attack()
    test_nusjuro_rush_at_trash_7()
    test_nusjuro_rush_known_in_hand_for_planner()
    test_jinbe_grants_play_turn_character_attack()
    print()
    print("SMOKE FAST OK" if FAIL == 0 else f"{FAIL} FALHA(S) NO SMOKE FAST")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
