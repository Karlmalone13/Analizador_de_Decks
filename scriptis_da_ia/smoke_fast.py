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


def test_never_existed_no_stage_is_hard_blocked() -> None:
    # OP13-098 [Main] = ko opp_stage; sem stage do oponente o efeito e nulo e
    # jogar ainda QUEIMA o [Counter] +4000. Deve ser bloqueio DURO, nao so
    # penalizado (achado ao vivo 14/07, log 01.23.31: "Never Existed do nada").
    me = GameState(leader=real_card("OP13-079"), don_available=6)
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    opp.field_chars = [mk("OP10-111", "Luffy", power=5000, color="Red")]
    opp.field_stage = None
    never = real_card("OP13-098")
    me.hand = [never]
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    score = match._score_play_action(never, DecisionEngine(me, opp))
    check("Never Existed no vacuo (sem stage do opp) e bloqueio duro", score <= -900)


def test_counter_buff_vai_pro_lider_defensor_no_empate() -> None:
    # Ground Death/Never Existed [Counter] +4000: com o LIDER (5000) sob ataque
    # de 5000 (empate = atacante vence) e um personagem ATIVO mais forte no
    # campo, o buff DEVE ir pro lider (quem leva o golpe), nao pro corpo forte
    # parado (achado ao vivo 13/07, Ground Death log 21.01.22 buffou o Kuma).
    leader = mk("OP13-079", "Imu", power=5000, card_type="LEADER")
    leader._deck_uid = 500
    me = GameState(leader=leader, don_available=5)
    saturn = mk("OP13-083", "Saturn", power=8000)
    saturn._deck_uid = 320
    saturn.rested = False
    me.field_chars = [saturn]
    opp = GameState(leader=mk("ST04-001", "Kaido", power=5000, card_type="LEADER"))
    cands = [{"id": 320, "zone": "own_board", "code": "OP13-083"},
             {"id": 500, "zone": "own_leader", "code": "OP13-079"}]
    order = sim_bridge.order_target_candidates(
        me, opp, cands, attacker_power=5000, defender_uid=1, actor_code="OP14-096")
    check("counter buff vai pro lider defensor no empate (nao pro corpo forte)",
          bool(order) and order[0] == 500)


def test_draw_cost_trasha_corpo_morto_antes_da_mao() -> None:
    # Custo do draw do lider Imu (trash_char_or_hand celestial dragons): um
    # corpo de 0 poder ja usado no campo (Shalria) deve ser trashado ANTES de
    # cartas jogaveis da mao. O +40 "ultimo corpo" nao vale pra corpo que nao
    # defende (achado ao vivo 14/07, log 01.23.31: "nao trashou a Shalria").
    me = GameState(leader=real_card("OP13-079"), don_available=3)
    shalria = real_card("OP13-086"); shalria._deck_uid = 10
    shalria.just_played = True   # recem-jogada (on-play ja resolveu) segue dead weight
    me.field_chars = [shalria]
    mars = real_card("OP13-091"); mars._deck_uid = 20
    saturn = real_card("OP13-083"); saturn._deck_uid = 30
    me.hand = [mars, saturn]
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    cands = [{"id": 10, "zone": "own_board", "code": "OP13-086"},
             {"id": 20, "zone": "own_hand", "code": "OP13-091"},
             {"id": 30, "zone": "own_hand", "code": "OP13-083"}]
    order = sim_bridge.order_target_candidates(me, opp, cands, actor_code="OP13-079")
    check("draw do Imu trasha o corpo morto (Shalria) antes da mao",
          bool(order) and order[0] == 10)


def test_shalria_na_mao_protegida_enquanto_precisa_de_trash() -> None:
    # Shalria da MAO enche o trash no on-play (trash_rest/trash_from_hand);
    # enquanto o trash < alvo do game_plan (7 no Imu) ela deve ser PROTEGIDA de
    # ser trashada como custo (guardar pra JOGAR). Pedido do usuario 14/07.
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

    def trash_value_com(n_trash: int) -> float:
        me = GameState(leader=real_card("OP13-079"), don_available=1)
        me.deck = [real_card(c) for c in codes]
        me.trash = [real_card("OP13-080") for _ in range(n_trash)]
        opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
        return EffectExecutor(me, opp)._trash_value(real_card("OP13-086"))

    check("Shalria na mao mais protegida com trash baixo (precisa encher) que cheio",
          trash_value_com(0) > trash_value_com(8))


def test_play_turn_greedy_opponent_response() -> None:
    # Item 3 do plano (busca prof.2): _play_turn_greedy simula o turno de
    # RESPOSTA do oponente (motor proprio, guloso, sem aninhar main_phase).
    # Sanity funcional: joga a carta jogavel, avanca o turno, nao quebra --
    # `me` precisa de VIDA REAL (default e [] = life_count 0), senao qualquer
    # ataque do oponente "vence" trivialmente sem exercitar o loop de acoes.
    opp = GameState(leader=mk("OP10-099", "Kid", power=5000, card_type="LEADER", color="Red"),
                     don_available=0, don_deck=8, turn=2)
    body = mk("OP10-111", "Corpo", power=5000, cost=2)   # cabe nos 2 DON do turno (nao-T1)
    opp.hand = [body]
    me = GameState(leader=mk("OP13-079", "Imu", power=5000, card_type="LEADER"), turn=2)
    me.life = [real_card("OP13-080") for _ in range(4)]
    match = OPTCGMatch((opp.leader, []), (me.leader, []))
    won = match._play_turn_greedy(opp, me)
    check("_play_turn_greedy nao quebra e avanca o turno do oponente",
          opp.turn == 3 and not won)
    check("_play_turn_greedy joga a carta jogavel disponivel (motor age de verdade)",
          body in opp.field_chars)


def test_play_turn_greedy_detecta_letal_do_oponente() -> None:
    # Fio central do item 3: a simulacao do turno de RESPOSTA do oponente
    # precisa enxergar quando ELE fecha letal contra MIM -- e o que
    # _simulate_sequence_once usa (via _play_turn_greedy) pra punir (-SIMULATED_
    # WIN_SCORE) uma linha minha que deixa o oponente com ataque letal pronto.
    me = GameState(leader=real_card("OP13-079"))
    me.life = [real_card("OP13-080")]   # 1 vida so, sem counter na mao
    opp = GameState(leader=mk("OP10-099", "Kid", power=5000, card_type="LEADER", color="Red"),
                    don_available=0, don_deck=8, turn=2)   # turn>1 pos-increment: pode atacar
    opp.field_chars = [mk("OP10-111", "Ameaca", power=9000)]  # ativo, poder > minha vida
    match = OPTCGMatch((opp.leader, []), (me.leader, []))
    letal = match._play_turn_greedy(opp, me)
    check("resposta do oponente com ameaca 9000 vs minha vida 1 fecha LETAL",
          letal or me.life_count() == 0)


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
    test_never_existed_no_stage_is_hard_blocked()
    test_counter_buff_vai_pro_lider_defensor_no_empate()
    test_draw_cost_trasha_corpo_morto_antes_da_mao()
    test_shalria_na_mao_protegida_enquanto_precisa_de_trash()
    test_play_turn_greedy_opponent_response()
    test_play_turn_greedy_detecta_letal_do_oponente()
    test_imu_waits_for_active_elder_attack()
    test_nusjuro_rush_at_trash_7()
    test_nusjuro_rush_known_in_hand_for_planner()
    test_jinbe_grants_play_turn_character_attack()
    print()
    print("SMOKE FAST OK" if FAIL == 0 else f"{FAIL} FALHA(S) NO SMOKE FAST")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
