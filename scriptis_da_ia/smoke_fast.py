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
    apply_conditional_keyword_passives,
    consume_play_cost_reductions,
    effective_counter,
    effective_hand_play_cost,
    get_card_effects,
    is_immune,
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
    attribute: str = "",
    has_trigger: bool = False,
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
            attribute=attribute,
            has_trigger=has_trigger,
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


def test_debuff_when_attacking_mira_o_defensor_que_vira_o_combate() -> None:
    # Nosjuro [When Attacking] debuff -2000: se o alvo do MEU ataque (Law,
    # 9000) cai pra <= meu poder (7000) com o debuff, DEVE mirar ele -- e o
    # motivo da carta ter essa habilidade. A regra generica antiga (maior
    # ameaca ATIVA) ignorava attacker_power/defender_uid (que ja chegavam
    # populados) e mirava outro personagem sem nenhum ganho no combate em
    # andamento. Achado ao vivo 14/07 (log 12.02.31): debuffou Hawkins (nao
    # envolvido) atacando Law (o alvo real).
    me = GameState(leader=mk("OP13-079", "Imu", card_type="LEADER"))
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    law = mk("OP10-119", "Law", power=9000)
    law._deck_uid = 360
    hawkins = mk("OP10-109", "Hawkins", power=8000)
    hawkins._deck_uid = 190
    opp.field_chars = [law, hawkins]
    cands = [{"id": 360, "zone": "opp_board", "code": "OP10-119"},
             {"id": 190, "zone": "opp_board", "code": "OP10-109"}]
    order = sim_bridge.order_target_candidates(
        me, opp, cands, attacker_power=7000, defender_uid=360, actor_code="OP13-080")
    check("debuff when_attacking mira o defensor do ataque quando vira o combate",
          bool(order) and order[0] == 360)


def test_avaliar_carta_prioriza_wincon_sobre_corpo_barato_vida_baixa() -> None:
    # avaliar_carta nao tinha NENHUMA nocao de game_plan (diferente de
    # _trash_value, que ja protegia o win-con no custo de trash) — um corpo
    # mais barato com counter alto (Nosjuro, 1000 counter) podia pontuar ACIMA
    # da bomba do deck (Five Elders, 12000 poder) em vida baixa (multiplicador
    # de panico do counter). Cenario adversarial: vida=1 (o counter da Nosjuro
    # recebe o MAIOR multiplicador possivel) — mesmo assim a bomba do plano
    # deve vencer. Achado ao vivo 14/07 (log 12.02.31): Empty Throne jogou
    # Nosjuro em vez do Five Elders com 10 DON disponiveis.
    me = GameState(leader=real_card("OP13-079"), don_available=10)
    five = real_card("OP13-082")
    nos = real_card("OP13-080")
    me.hand = [five, nos]
    me.life = [real_card("OP13-080")]   # vida 1 -- pior caso pro fix
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    eng = DecisionEngine(me, opp)
    check("avaliar_carta prioriza a win-con (Five Elders) sobre Nosjuro mesmo em vida baixa",
          eng.avaliar_carta(five) > eng.avaliar_carta(nos))


def test_execucao_play_card_prioriza_wincon_sobre_searcher() -> None:
    # 3a copia do mesmo bug (avaliar_carta 14/07, order_target_candidates/
    # own_hand 09/07): _score_to_play, usada pela EXECUCAO real de QUALQUER
    # 'play_card' dentro de QUALQUER trigger (incl. Empty Throne
    # activate_main), nao tinha nocao de game_plan -- um searcher generico
    # (Ju Peter, +40 de flag is_searcher) batia a bomba do deck (Five
    # Elders, 12000 poder, zero flags) so por causa das flags. Achado ao
    # vivo indireto 14/07: usuario reportou "nunca ativa o combo" -- rastreado
    # ate aqui, a Empty Throne literalmente jogava a carta ERRADA da mao.
    match = OPTCGMatch((real_card("OP13-079"), []), (mk("OP10-099", "Kid", card_type="LEADER", color="Red"), []))
    gs = GameState(leader=real_card("OP13-079"), don_available=10)
    gs.hand = [real_card("OP13-082"), real_card("OP13-084")]   # Five Elders + Ju Peter (searcher)
    gs.field_stage = real_card("OP13-099")   # Empty Throne
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    ee = EffectExecutor(gs, opp)
    ee.execute(gs.field_stage, "activate_main")
    codes_no_campo = [c.code for c in gs.field_chars]
    check("Empty Throne joga a win-con (Five Elders) em vez do searcher generico",
          "OP13-082" in codes_no_campo and "OP13-084" not in codes_no_campo)


def test_salvar_blocker_desconta_on_ko_e_ataques_restantes() -> None:
    # Usuario apontou (14/07): salvar um blocker com counter nao e ganho puro
    # -- Warcury tem on_ko (draw 1), entao salva-lo abre mao desse gatilho
    # (custo de oportunidade); e se o oponente ainda tem mais atacantes
    # ativos este turno, gastar o counter agora compete com precisar dele de
    # novo. select_counter_cards['defender_char'] agora desconta os dois.
    me = GameState(leader=real_card("OP13-079"), don_available=2)
    warcury = real_card("OP13-089")
    warcury._deck_uid = 99
    warcury.rested = True
    me.field_chars = [warcury]
    gd = real_card("OP14-096")
    gd._deck_uid = 50
    me.hand = [gd]
    me.trash = [real_card("OP13-080") for _ in range(10)]   # trash_gte:10 do Ground Death
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    ids = sim_bridge.select_counter_cards(me, atk_power=7000, def_power=5000,
                                          opp_gs=opp, defender_uid=99)
    check("select_counter_cards salva Warcury quando o ganho liquido (com on_ko descontado) supera o gasto",
          bool(ids))


def test_full_deck_census_populado_offline_e_ao_vivo() -> None:
    # ACHADO ESTRUTURAL 14/07 (usuario: "consertamos so o Imu, o bot nao sabe
    # jogar outro deck"): full_deck_census (base do posture() aggressive/
    # control/midrange, ja existente e bem calibrado) NUNCA era populado em
    # lugar nenhum do motor -- so numa ferramenta de visualizacao isolada
    # (replay_optcg.py). posture() sempre caia no fallback 'midrange' pra
    # QUALQUER deck, offline e ao vivo. Fix: OPTCGMatch.__init__ popula pros
    # dois lados (decklist completa ja conhecida); sim_bridge.
    # deck_cards_for_leader (mesmo lookup do OpponentModel) alimenta o
    # caminho ao vivo via server.py _dto_to_gs.
    match = OPTCGMatch((real_card("OP13-079"), []), (mk("OP10-099", "Kid", card_type="LEADER", color="Red"), []))
    check("OPTCGMatch popula full_deck_census pros dois lados (offline)",
          match.state_a.full_deck_census is not None
          and match.state_b.full_deck_census is not None)

    cards = sim_bridge.deck_cards_for_leader("OP10-099")
    if cards is None:
        print("[SKIP] deck Kid.deck nao encontrado")
        return
    from optcg_engine.decision_engine import deck_census
    census = deck_census(cards)
    check("deck_cards_for_leader + deck_census populam o mesmo formato usado ao vivo",
          census.get("total") == 50)


def test_ciclo_do_lider_nao_trava_com_corpo_morto_ativo() -> None:
    # Deadlock real (log 13.08.24): "adia ciclo do lider: atacar com chars
    # ativos antes de trashar" so olhava LEGALIDADE (character_can_attack_now),
    # nao VALOR. Shalria (0 poder) e "tecnicamente ativa" pra sempre (o bot
    # corretamente nunca ataca com ela, 0 poder nao conecta nada) -> o guard
    # nunca liberava -> o lider nunca mais ciclava a partida inteira (Shalria
    # nunca era trashada). Fix: so conta como "vale esperar o ataque" corpos
    # com poder>0.
    match = OPTCGMatch((real_card("OP13-079"), []), (mk("OP10-099", "Kid", card_type="LEADER", color="Red"), []))
    me = GameState(leader=real_card("OP13-079"), don_available=5, turn=4)
    shalria = real_card("OP13-086")
    shalria.rested = False
    shalria.just_played = False
    me.field_chars = [shalria]
    me.hand = [real_card("OP13-083"), real_card("OP13-089"), real_card("OP13-084")]
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    am = get_card_effects("OP13-079")["activate_main"]
    pode, motivo = match._should_activate_main(me.leader, am, me, opp)
    check("ciclo do lider nao trava com Shalria (0 poder) 'ativa' no campo", pode)


def test_don_reservado_para_ativar_wincon_em_campo() -> None:
    # _don_livre_for_plan so reservava DON pra acoes 'play', nunca 'activate'
    # -- o Activate:Main da propria win-con ja em campo (Five Elders, rest_
    # don:1 pra reanimar 5 do trash) nunca tinha DON protegido, e o ataque
    # seguinte consumia o DON que faltava pra ativar o combo no MESMO turno
    # (achado ao vivo 14/07, log 13.08.24). Cenario: 4 DON, Five Elders em
    # campo com fuel no trash -- deve sobrar so 3 livres pra margem de ataque
    # (1 reservado pro activate).
    me = GameState(leader=real_card("OP13-079"), don_available=4, turn=5)
    me.field_chars = [real_card("OP13-089"), real_card("OP13-082")]
    me.trash = ([real_card("OP13-083"), real_card("OP13-080"), real_card("OP13-091")]
                + [real_card("OP13-080") for _ in range(8)])
    me.hand = [real_card("OP13-084")]
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"))
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    eng = DecisionEngine(me, opp)
    don_livre = match._don_livre_for_plan(me, opp, eng)
    check("DON reservado pra ativar a win-con em campo (don_livre cai de 4 pra 3)",
          don_livre == 3)


def test_opponent_model_ao_vivo_por_lider_e_fallback_seguro() -> None:
    # Item 3 ligado AO VIVO (14/07): lookup do .deck real por codigo do lider
    # (os decks de teste sao nomeados por arquetipo -- Kid.deck, Krieg.deck)
    # alimenta o OpponentModel que o offline sempre teve. Kid.deck precisa
    # existir no banco de decks pra este check ter sentido.
    deck_path = Path(r"E:\Games\OnePieceSimulador\Builds_Windows\Decks\Kid.deck")
    if not deck_path.exists():
        print("[SKIP] deck Kid.deck nao encontrado")
        return
    model = sim_bridge.opponent_model_for_leader("OP10-099")
    check("opponent_model_for_leader acha o Kid.deck real (50 cartas) pelo lider",
          model is not None and len(model.full_decklist) == 50)
    check("lider desconhecido cai em None (busca fica indisponivel, nao quebra)",
          sim_bridge.opponent_model_for_leader("ZZ99-999") is None)

    me = GameState(leader=real_card("OP13-079"), don_available=5, turn=3)
    me.hand = [real_card("OP13-083"), real_card("OP13-089")]
    me.life = [real_card("OP13-080") for _ in range(4)]
    opp = GameState(leader=mk("OP10-099", "Kid", card_type="LEADER", color="Red"), turn=3)
    opp.life = [real_card("OP13-080") for _ in range(4)]
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    action = sim_bridge.choose_action(me, opp, match, timeout=3.0,
                                      allowed_types={"play", "attack", "attach_don", "activate"})
    check("choose_action com busca ao vivo retorna uma acao valida (nao None)",
          action is not None)


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


def test_krieg_rest_opp_requires_2_don_attached() -> None:
    # Achado 14/07 via audit_leader_and_goal.py: o activate_main do Krieg
    # (OP15-001, "Rest up to 1 of your opponent's Characters that has 2 or
    # more DON!! cards given") caia sempre no fallback cost_lte=99 (sem
    # filtro nenhum) -- o parser nunca tinha gramatica pra "personagem com
    # N+ DON anexado" como filtro de ALVO. Fix: parse_rest_opp emite
    # don_attached_gte, eligible_cards() ganhou o parametro.
    me = GameState(leader=real_card("OP15-001"), don_available=4, turn=3)
    opp = GameState(leader=mk("OP11-051", "Doflamingo", card_type="LEADER", color="Purple"), turn=3)
    alvo_valido = mk("XOPP1", "Com 2+ DON", power=5000, cost=4, color="Black")
    alvo_valido.don_attached = 2
    alvo_invalido = mk("XOPP2", "Sem DON suficiente", power=5000, cost=4, color="Black")
    alvo_invalido.don_attached = 1
    opp.field_chars = [alvo_invalido, alvo_valido]

    effects = get_card_effects("OP15-001")
    step = effects.get("activate_main", {}).get("steps", [{}])[0]
    check("OP15-001 parseia don_attached_gte=2 no rest_opp_character",
          step.get("don_attached_gte") == 2)

    EffectExecutor(me, opp).execute(me.leader, "activate_main")
    check("Krieg resta apenas o alvo com 2+ DON anexado", alvo_valido.rested)
    check("Krieg NAO resta o alvo com DON insuficiente", not alvo_invalido.rested)


def test_kid_leader_set_active_respects_cost_range() -> None:
    # Achado 14/07 via audit_leader_and_goal.py: o end_of_turn do lider do
    # Kid (OP10-099, "Supernovas type Characters with a cost of 3 to 8")
    # virava cost_eq=3 (perdia o intervalo 4-8 inteiro) -- parse_set_active
    # so tinha gramatica pra "cost of N" e "cost of N or less", nunca "cost
    # of N to M". Fix: novo ramo de intervalo emite cost_gte/cost_lte,
    # eligible_cards() ganhou cost_gte.
    effects = get_card_effects("OP10-099")
    step = effects.get("end_of_turn", {}).get("steps", [{}])[0]
    check("OP10-099 parseia intervalo cost_gte=3/cost_lte=8 (nao cost_eq=3)",
          step.get("cost_gte") == 3 and step.get("cost_lte") == 8
          and "cost_eq" not in step)

    me = GameState(leader=real_card("OP10-099"), don_available=4, turn=5)
    opp = GameState(leader=mk("OP11-051", "Doflamingo", card_type="LEADER", color="Purple"), turn=5)
    fora_do_intervalo = mk("XSN1", "Supernova custo 2", power=5000, cost=2,
                            sub_types="Supernovas")
    fora_do_intervalo.rested = True
    dentro_do_intervalo = mk("XSN2", "Supernova custo 6", power=5000, cost=6,
                              sub_types="Supernovas")
    dentro_do_intervalo.rested = True
    me.field_chars = [fora_do_intervalo, dentro_do_intervalo]
    me.life = [mk("XLIFE", "Vida", cost=0)]

    EffectExecutor(me, opp).execute(me.leader, "end_of_turn")
    check("Kid ativa Supernova de custo 6 (dentro do intervalo 3-8)",
          not dentro_do_intervalo.rested)
    check("Kid NAO ativa Supernova de custo 2 (fora do intervalo 3-8)",
          fora_do_intervalo.rested)


def test_lock_opp_character_refresh_variantes_de_fraseado() -> None:
    # Achado 15/07 via audit_parser_coverage.py: 4 cartas reais caiam no
    # fallback 'lock_opp_don' SEM NENHUM filtro (nem count) porque o regex
    # principal de parse_lock_refresh so aceitava "up to N of your
    # opponent's rested X [with a cost of Y or less] will not become
    # active" -- 3 variantes de fraseado reais quebravam isso: "up to A
    # TOTAL OF N" (OP04-031), filtro de "N+ DON anexado" em vez de custo
    # (OP15-025/038, com "with"/"that has" variando), e "of your
    # opponent's" ausente quando a posse aparece so no final da frase
    # (OP15-025). Fix generalizou o regex sem perder os casos antigos.
    step_op04031 = get_card_effects("OP04-031").get("on_play", {}).get("steps", [{}])[0]
    check("OP04-031 parseia 'up to a total of 3' -> count=3 (nao lock_opp_don generico)",
          step_op04031.get("action") == "lock_opp_character_refresh"
          and step_op04031.get("count") == 3)

    step_op15025 = get_card_effects("OP15-025").get("on_play", {}).get("steps", [{}])
    step_op15025 = step_op15025[-1] if step_op15025 else {}
    check("OP15-025 parseia don_attached_gte=3 (posse implicita no fim da frase)",
          step_op15025.get("action") == "lock_opp_character_refresh"
          and step_op15025.get("don_attached_gte") == 3)

    step_op15038 = get_card_effects("OP15-038").get("main", {}).get("steps", [{}])[0]
    check("OP15-038 parseia cost_lte=8 E don_attached_gte=2 juntos (2 filtros encadeados)",
          step_op15038.get("cost_lte") == 8 and step_op15038.get("don_attached_gte") == 2)

    # Execucao real: alvo com DON insuficiente nao pode ser travado, alvo
    # com DON suficiente pode.
    me = GameState(leader=real_card("OP15-025"), don_available=4, turn=3)
    opp = GameState(leader=mk("OP11-051", "Doflamingo", card_type="LEADER", color="Purple"), turn=3)
    alvo_valido = mk("XOPP1", "Com 3+ DON", power=5000, cost=4, color="Black")
    alvo_valido.don_attached = 3
    alvo_valido.rested = True
    alvo_invalido = mk("XOPP2", "Sem DON suficiente", power=5000, cost=4, color="Black")
    alvo_invalido.don_attached = 2
    alvo_invalido.rested = True
    opp.field_chars = [alvo_invalido, alvo_valido]
    EffectExecutor(me, opp).execute(me.leader, "on_play")
    check("Kuro congela (frozen_next_refresh) so o alvo com 3+ DON anexado",
          alvo_valido.frozen_next_refresh and not alvo_invalido.frozen_next_refresh)


def test_rest_opp_alvo_misto_character_ou_don() -> None:
    # Achado 15/07 via audit_parser_coverage.py: OP06-035 (Hody Jones, 7x em
    # deck real) tinha "Rest up to a total of 2 of your opponent's
    # Characters or DON!! cards" -- clausula INTEIRA ausente do parseado (so
    # a parte seguinte, "add 1 card from Life to hand", tinha sido
    # capturada). parse_rest_opp ganhou ramo pra alvo misto
    # Character-ou-DON (aproximado como rest_opp_character).
    steps = get_card_effects("OP06-035").get("on_play", {}).get("steps", [])
    check("OP06-035 parseia o rest misto (Character ou DON) como step real",
          any(s.get("action") == "rest_opp_character" and s.get("count") == 2 for s in steps))
    check("OP06-035 mantem o 2o step (add 1 card da Life pra mao) intacto",
          any(s.get("action") == "life_to_hand" for s in steps))


def test_give_don_opp_com_of_your_opponent_no_meio_da_frase() -> None:
    # Achado 15/07 via audit_parser_coverage.py: OP15-008 (Krieg, 4x em
    # deck real) tinha "Give up to 3 OF YOUR OPPONENT'S RESTED DON!! cards
    # to 1 of your opponent's Characters" -- a clausula inteira ausente do
    # parseado (so o 'gain_rush' da mesma carta sobrevivia) porque o regex
    # de parse_give_don exigia "(rested )?don!!" logo apos o numero, sem a
    # clausula "of your opponent's" no meio. Mesmo fix pegou mais 2 cartas
    # de bonus (OP15-015, OP15-026) com o mesmo padrao, nem estavam no
    # top-15 da varredura.
    for code, trig in (("OP15-008", "on_play"), ("OP15-015", "on_play"),
                        ("OP15-026", "activate_main")):
        steps = get_card_effects(code).get(trig, {}).get("steps", [])
        check(f"{code} parseia give_don_opp (antes ausente por completo)",
              any(s.get("action") == "give_don_opp" and s.get("rested") for s in steps))


def test_give_don_nao_inventa_don_quando_banco_insuficiente() -> None:
    # Achado 15/07 -- o USUARIO reparou olhando a saida do
    # audit_parser_coverage.py pra ST01-011 (Brook, "Give up to 2 rested
    # DON!! cards..." -> count=2) e perguntou se "up to" bater com um
    # 'count' fixo estava certo. Investigando, achei algo pior que
    # semantica de "up to": give_don/give_don_opp anexava o `count` CHEIO
    # no character ANTES de saber quanto o banco realmente tinha pra
    # debitar -- com banco insuficiente, o character recebia o valor cheio
    # mesmo assim (DON criado do nada, campo e banco dessincronizam). Fix:
    # anexa exatamente o que foi debitado de verdade. Lider do oponente
    # forte (9000) garante que o "necessario" (ver teste seguinte) exceda
    # tanto o banco quanto o teto da carta, isolando so essa checagem.
    me = GameState(leader=real_card("ST01-001"), don_available=0, turn=3)
    me.don_rested = 1  # banco so tem 1 DON rested, carta pede ate 2
    opp_lider_forte = mk("XOPPL", "Lider Forte", power=9000, cost=0, card_type="LEADER")
    opp = GameState(leader=opp_lider_forte, turn=3)
    brook = real_card("ST01-011")
    me.field_chars = [brook]
    EffectExecutor(me, opp).execute(brook, "on_play")
    check("give_don debita o banco de verdade (nao fica negativo)",
          me.don_rested == 0)
    check("give_don anexa so o que o banco tinha (1), nao o count pedido (2)",
          me.leader.don_attached == 1)


def test_give_don_da_so_o_necessario_nao_sempre_o_teto() -> None:
    # Achado 15/07 -- o usuario apontou que "up to N" significa "0 a N,
    # escolha livre", nao "sempre N". Antes deste fix, give_don sempre
    # tentava dar o TETO do texto, mesmo quando o personagem ja tinha
    # poder suficiente pra passar pelo lider do oponente sem DON nenhum
    # (desperdicando DON que ficaria melhor reservado pra defesa). Fix:
    # calcula o deficit real (mesma formula base de don_needed_for_attack)
    # e da so o minimo entre o teto da carta e o que falta.
    meu_lider_fraco = mk("XMELIDER", "Lider Fraco", power=1000, cost=0, card_type="LEADER")

    # Cenario A: personagem ja bate o lider do oponente (9000 vs 5000) --
    # nao deveria gastar DON nenhum, mesmo a carta pedindo ate 2.
    me_a = GameState(leader=meu_lider_fraco, don_available=0, turn=3)
    me_a.don_rested = 2
    opp_a = GameState(leader=mk("XOPPL", "Lider", power=5000, cost=0, card_type="LEADER"), turn=3)
    brook_a = real_card("ST01-011")
    forte = mk("XFORTE", "Forte", power=9000, cost=4)
    me_a.field_chars = [brook_a, forte]
    EffectExecutor(me_a, opp_a).execute(brook_a, "on_play")
    check("give_don NAO gasta DON se o alvo ja bate o lider do oponente sem ajuda",
          me_a.don_rested == 2 and forte.don_attached == 0)

    # Cenario B: personagem precisa so de 1 DON (4000 vs 5000, falta 1000)
    # pra bater o lider -- carta pede ate 2, deveria dar so 1.
    me_b = GameState(leader=meu_lider_fraco, don_available=0, turn=3)
    me_b.don_rested = 2
    opp_b = GameState(leader=mk("XOPPL", "Lider", power=5000, cost=0, card_type="LEADER"), turn=3)
    brook_b = real_card("ST01-011")
    fraco = mk("XFRACO", "Fraco", power=4000, cost=2)
    me_b.field_chars = [brook_b, fraco]
    EffectExecutor(me_b, opp_b).execute(brook_b, "on_play")
    check("give_don da so o necessario (1), nao o teto pedido pela carta (2)",
          me_b.don_rested == 1 and fraco.don_attached == 1)


def test_hand_to_deck_clausula_loot_apos_draw() -> None:
    # Achado 15/07 -- o usuario revisou o script e apontou que Nami
    # (OP11-054, "draw 3 cards and place 2 cards from your hand at the top
    # or bottom of your deck in any order") tinha a 2a clausula inteira
    # ausente do parseado. parse_draw ganhou ramo pra "place M cards from
    # your hand at top or bottom of your deck" (hand_to_deck). Mesmo fix
    # pegou 5 cartas reais (Nami + OP07-053, OP08-050, OP08-002, OP08-056).
    steps = get_card_effects("OP11-054").get("on_play", {}).get("steps", [])
    check("Nami parseia hand_to_deck count=2 (antes ausente por completo)",
          any(s.get("action") == "hand_to_deck" and s.get("count") == 2 for s in steps))

    lider_multicolor = mk("XMULTI", "Lider Multicolor", card_type="LEADER", color="Red Blue")
    me = GameState(leader=lider_multicolor, turn=3)
    opp = GameState(leader=mk("OP11-051", "Doflamingo", card_type="LEADER", color="Purple"), turn=3)
    nami = real_card("OP11-054")
    me.hand = [mk(f"XCARD{i}", f"Carta {i}", cost=1) for i in range(3)]
    me.deck = [mk(f"XDECK{i}", f"Deck {i}", cost=1) for i in range(5)]
    EffectExecutor(me, opp).execute(nami, "on_play")
    check("Nami executa hand_to_deck de verdade: mao encolhe pelas 2 devolvidas",
          len(me.hand) == 3 - 2 + 3)  # comprou 3, devolveu 2 -> liquido +1


def test_ipponmatsu_immunity_exige_leader_slash_e_don_rested() -> None:
    # Achado 15/07 -- o usuario apontou que OP12-021 (Ipponmatsu) tinha a
    # imunidade a rest aplicando SEMPRE, sem nenhum dos 2 requisitos do
    # texto ("If your Leader has the (Slash) attribute and you have 6 or
    # more rested DON!! cards..."). parse_conditions ganhou leader_attribute
    # (parenteses -- delimitador diferente do leader_type usual) e
    # don_rested_gte (distinto de don_gte, que olha don_available).
    conds = get_card_effects("OP12-021").get("passive", {}).get("conditions", {})
    check("Ipponmatsu parseia leader_attribute=slash", conds.get("leader_attribute") == "slash")
    check("Ipponmatsu parseia don_rested_gte=6", conds.get("don_rested_gte") == 6)

    ipponmatsu = real_card("OP12-021")
    opp = GameState(leader=mk("OP11-051", "Doflamingo", card_type="LEADER", color="Purple"), turn=3)

    # Sem lider Slash nem DON rested suficiente -> NAO deveria estar imune.
    me_sem = GameState(leader=mk("XL1", "Lider nao-Slash", card_type="LEADER", color="Red"), turn=3)
    me_sem.field_chars = [ipponmatsu]
    check("Ipponmatsu NAO imune sem lider Slash e sem 6+ DON rested",
          not is_immune(ipponmatsu, "rest", me_sem, opp, source_is_opp=True))

    # Com lider Slash e 6+ DON rested -> deveria estar imune.
    ipponmatsu2 = real_card("OP12-021")
    lider_slash = mk("XL2", "Lider Slash", card_type="LEADER", color="Red", attribute="Slash")
    me_com = GameState(leader=lider_slash, turn=3)
    me_com.don_rested = 6
    me_com.field_chars = [ipponmatsu2]
    check("Ipponmatsu IMUNE com lider Slash e 6+ DON rested",
          is_immune(ipponmatsu2, "rest", me_com, opp, source_is_opp=True))


def test_don_minus_sem_sinal_de_menos_na_fonte() -> None:
    # Achado 15/07 -- usuario suspeitou que OP14-078 (Bullet String,
    # "[Counter] DON!! 1: ...") tinha o sinal de menos faltando no dado
    # cru (deveria ser "DON!! -1:"). Confirmado: cards_rows.csv realmente
    # nao tem o "-", e o parser de don_minus so aceitava a forma COM sinal
    # -- 51 cartas reais no banco tinham esse mesmo problema de dado (vs
    # 33 com o sinal certo, que ja funcionavam). Fallback: quando o numero
    # e imediatamente seguido de ':' (a notacao de custo oficial sempre
    # tem o ':' colado), trata como don_minus mesmo sem o sinal.
    costs = get_card_effects("OP14-078").get("counter", {}).get("costs", [])
    check("OP14-078 parseia don_minus:1 mesmo sem o sinal de menos na fonte",
          any(c.get("type") == "don_minus" and c.get("count") == 1 for c in costs))

    lider_doflamingo = mk("XDOFL", "Lider Doflamingo", card_type="LEADER",
                           color="Yellow", sub_types="Donquixote Pirates")
    me = GameState(leader=lider_doflamingo, turn=3, don_available=3, don_deck=7)
    opp = GameState(leader=mk("XOPPL", "Lider Oponente", card_type="LEADER"), turn=3)
    bullet = real_card("OP14-078")
    EffectExecutor(me, opp).execute(bullet, "counter")
    check("OP14-078 paga o custo de verdade: 1 DON sai do campo, volta pro deck de DON",
          me.don_available == 2 and me.don_deck == 8)


def test_opp_life_lte_gte_condicao_ausente() -> None:
    # Achado 15/07 -- usuario revisou OP10-112 (Kid) e apontou que o
    # end_of_turn ("If your opponent has 2 or less Life cards, draw 1
    # card...") nao tinha NENHUMA condicao de vida do oponente no
    # parseado -- so existiam life_lte/life_gte (vida PROPRIA), nunca o
    # espelho pro lado do oponente. 45 cartas reais no banco usam esse
    # padrao textual.
    conds = get_card_effects("OP10-112").get("end_of_turn", {}).get("conditions", {})
    check("OP10-112 (Kid) parseia opp_life_lte=2 no end_of_turn",
          conds.get("opp_life_lte") == 2)

    kid = real_card("OP10-112")

    # Vida do oponente ACIMA do limiar -> condicao NAO satisfeita, deck
    # intacto (draw nunca dispara).
    me_alto = GameState(leader=real_card("OP10-099"), turn=3)
    me_alto.field_chars = [kid]
    me_alto.deck = [mk("XDECK1", "Deck", cost=1)]
    opp_alto = GameState(leader=mk("XOPPL", "Lider", card_type="LEADER"), turn=3)
    opp_alto.life = [mk(f"XL{i}", f"Vida{i}", cost=0) for i in range(3)]
    EffectExecutor(me_alto, opp_alto).execute(kid, "end_of_turn")
    check("Kid NAO compra se vida do oponente > 2 (condicao nao satisfeita)",
          len(me_alto.deck) == 1)

    # Vida do oponente NO limiar -> condicao satisfeita, deck esvazia (1
    # carta comprada de verdade, mesmo que depois trashada da mao).
    me_baixo = GameState(leader=real_card("OP10-099"), turn=3)
    me_baixo.field_chars = [kid]
    me_baixo.deck = [mk("XDECK2", "Deck", cost=1)]
    opp_baixo = GameState(leader=mk("XOPPL2", "Lider2", card_type="LEADER"), turn=3)
    opp_baixo.life = [mk(f"XL{i}", f"Vida{i}", cost=0) for i in range(2)]
    EffectExecutor(me_baixo, opp_baixo).execute(kid, "end_of_turn")
    check("Kid compra de verdade se vida do oponente <= 2 (condicao satisfeita)",
          len(me_baixo.deck) == 0)


def test_zoro_substitui_rest_por_aliado() -> None:
    # Achado 15/07 -- usuario revisou PRB02-006 (Zoro): "If this Character
    # would be rested by your opponent's Character's effect, you may rest
    # 1 of your other Characters instead" -- clausula de SUBSTITUICAO
    # (mesma familia de substitute_ko/substitute_removal, mas pra "rest",
    # sem cobertura nenhuma antes). Novo action substitute_rest + custo
    # rest_own_other_character (exclui a propria carta dos candidatos,
    # distinto de rest_own_character que nao exclui -- usado por
    # substituicao EXTERNA onde a exclusao nao faz sentido).
    conds_step = get_card_effects("PRB02-006").get("opp_turn", {}).get("steps", [{}])[0]
    check("PRB02-006 parseia substitute_rest com custo rest_own_other_character",
          conds_step.get("action") == "substitute_rest"
          and conds_step.get("cost", {}).get("action") == "rest_own_other_character")

    me = GameState(leader=real_card("ST01-001"), turn=3)
    opp = GameState(leader=mk("XOPPL", "Lider", card_type="LEADER"), turn=3)
    zoro = real_card("PRB02-006")
    aliado = mk("XALIADO", "Aliado", power=3000, cost=2)
    opp.field_chars = [zoro, aliado]
    EffectExecutor(me, opp)._execute_step({"action": "rest_opp_character", "count": 1}, me.leader)
    check("Zoro NAO fica rested (substituiu)", not zoro.rested)
    check("Aliado fica rested no lugar do Zoro", aliado.rested)


def test_whitebeard_reveal_conditional_play() -> None:
    # Achado 15/07 -- usuario revisou OP12-058 (Whitebeard): "reveal 1
    # card... If that card is a Character card with a type including
    # 'Whitebeard Pirates' AND a cost of 9 or less, you may play that
    # card." O parser ja tinha uma funcao pra esse padrao
    # (parse_reveal_top_play, variante condicional) mas exigia "with a
    # cost of" logo apos "is [Tipo]" -- o fraseado do Whitebeard usa "with
    # a type including "X" AND a cost of" (conjuncao diferente + tipo
    # nomeado de outro jeito), quebrava os 2 regexes (cost E tipo).
    steps = get_card_effects("OP12-058").get("main", {}).get("steps", [])
    play_step = next((s for s in steps if s.get("action") == "play_from_deck"), None)
    check("Whitebeard parseia play_from_deck com filtro de tipo e cost_lte=9",
          play_step is not None and play_step.get("cost_lte") == 9
          and play_step.get("filter_type") == "whitebeard pirates")
    check("Whitebeard mantem o gain_rush condicional (If you do, gains Rush)",
          any(s.get("action") == "gain_rush" for s in steps))

    lider_wb = mk("XWB", "Lider Whitebeard", card_type="LEADER", color="Red",
                   sub_types="Whitebeard Pirates")
    me = GameState(leader=lider_wb, turn=3, don_available=5)
    opp = GameState(leader=mk("XOPPL", "Lider", card_type="LEADER"), turn=3)
    carta_evento = real_card("OP12-058")
    topo = mk("XTOPO", "Personagem Whitebeard", cost=5, sub_types="Whitebeard Pirates")
    me.deck = [topo]
    EffectExecutor(me, opp).execute(carta_evento, "main")
    check("Whitebeard joga de verdade o personagem revelado (sai do deck, entra em campo)",
          len(me.deck) == 0 and topo in me.field_chars)
    check("Personagem jogado ganha Rush neste turno", topo.rush_this_turn)


def test_zoro_lider_battled_character_e_restricao_de_ataque() -> None:
    # Achado 15/07 -- o usuario corrigiu minha avaliacao de escopo (eu
    # tinha deixado OP12-020 de fora por "so 1 carta usa isso hoje", mas
    # ele apontou que o banco so tem 50 decks catalogados, uso atual nao
    # e bom criterio pra decidir o que consertar). OP12-020 (Zoro lider):
    # "If this Leader battles your opponent's Character during this turn,
    # set this Leader as active. Then, this Leader cannot attack your
    # opponent's Characters with a base cost of 7 or less during this
    # turn." Implementado: rastreio de combate
    # (battled_opp_character_this_turn, setado em _execute_attack, usado
    # tambem por OP04-047/ST02-010/ST08-013) + nova restricao de alvo de
    # ataque (cannot_attack_opp_chars_cost_lte, distinta de
    # lock_opp_character_attack que trava o OPONENTE).
    lider_zoro = real_card("OP12-020")
    me = GameState(leader=lider_zoro, turn=3, don_available=5)
    opp = GameState(leader=mk("XOPPL", "Lider", card_type="LEADER"), turn=3)

    check("OP12-020 parseia condicao battled_opp_character_this_turn",
          get_card_effects("OP12-020").get("activate_main", {}).get("conditions", {})
          .get("battled_opp_character_this_turn") is True)

    # Sem ter batido personagem ainda -- ativar nao deve fazer nada.
    log_sem = EffectExecutor(me, opp).execute(me.leader, "activate_main")
    check("Zoro NAO ativa sem ter batido um Character do oponente",
          not any(log_sem))

    # Simula uma batalha do lider contra um Character do oponente.
    fraco_opp = mk("XFRACO", "Fraco", power=1000, cost=3)
    opp.field_chars = [fraco_opp]
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    eng = DecisionEngine(me, opp)
    match._execute_attack(me.leader, "character", fraco_opp, me, opp, eng, verbose=False)
    check("battled_opp_character_this_turn liga apos bater um Character",
          me.leader.battled_opp_character_this_turn)

    # Agora ativa de verdade (DON anexado cobre o don_requirement=3).
    me.leader.don_attached = 3
    log_com = EffectExecutor(me, opp).execute(me.leader, "activate_main")
    check("Zoro ativa e aplica a restricao apos bater um Character",
          any(log_com) and me.leader.cannot_attack_opp_chars_cost_lte == 7)

    # Gera acoes de ataque -- personagem custo 3 (<=7) fica de fora,
    # custo 9 (>7) continua disponivel.
    custo3 = mk("XC3", "Custo3", power=1000, cost=3)
    custo3.rested = True
    custo9 = mk("XC9", "Custo9", power=1000, cost=9)
    custo9.rested = True
    opp.field_chars = [custo3, custo9]
    actions = match._generate_and_score_actions(me, opp, eng)
    alvos_character = {getattr(a[4], "name", None)
                        for a in actions if a[1] == "attack" and a[3] == "character"}
    check("Restricao exclui alvo de custo <=7 da lista de ataques gerados",
          "Custo3" not in alvos_character and "Custo9" in alvos_character)


def test_roger_vitoria_alternativa_ao_oponente_bloquear() -> None:
    # Achado 15/07 -- OP09-118 (Gol.D.Roger): "When your opponent
    # activates [Blocker], if either you or your opponent has 0 Life
    # cards, you win the game." Descoberto durante a implementacao: essa
    # carta tinha um bug PRE-EXISTENTE nao relacionado (nao da sessao
    # atual) -- o scanner de keywords nativas lia "[Blocker]" dentro da
    # frase "your opponent activates [Blocker]" como se fosse Blocker
    # NATIVO da propria carta (sem checar contexto). Corrigido junto:
    # scanner agora ignora tag precedida por "your opponent activates"/
    # "opponent's" (mesmo fix pegou OP06-048 e ST30-012 de bonus).
    conds_pass = get_card_effects("OP09-118").get("passive", {}).get("steps", [])
    check("OP09-118 NAO tem keyword_blocker nativo por engano (bug pre-existente corrigido)",
          not any(s.get("action") == "keyword_blocker" for s in conds_pass))
    check("OP09-118 parseia win_game_on_opp_blocker",
          any(s.get("action") == "win_game_on_opp_blocker" for s in conds_pass))

    roger = real_card("OP09-118")
    me = GameState(leader=mk("XLD", "Lider", card_type="LEADER"), turn=3, don_available=5)
    me.field_chars = [roger]
    me.life = []  # 0 vidas -- satisfaz "either you or your opponent has 0 life"
    opp = GameState(leader=mk("XOPPL", "Lider Opp", card_type="LEADER"), turn=3)
    opp.life = [mk("XL1", "Vida1", cost=0)]
    blocker_char = mk("XBLK", "Blocker", power=3000, cost=3)
    blocker_char.has_blocker = True
    opp.field_chars = [blocker_char]

    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    eng = DecisionEngine(me, opp)
    resultado = match._execute_attack(roger, "leader", None, me, opp, eng, verbose=False)
    check("Roger vence a partida quando oponente bloqueia com alguem em 0 vida",
          resultado is True)


def test_debuff_power_multiplo_alvo_e_condicao_por_tipo() -> None:
    # Achado 15/07 (varredura ampla do audit_parser_coverage.py, dois
    # padroes distintos corrigidos juntos):
    # 1. chars_gte_type_filter: "if you have N or more {TIPO} type
    #    Characters" nunca existia como condicao -- EB03-020 (e 4 outras
    #    cartas reais) aplicava um buff condicional SEMPRE. Ja coberto
    #    pelo teste corrigido em smoke_test.py (15c); aqui so confirma o
    #    parse.
    # 2. debuff_power com count>1: "give up to N of your opponent's
    #    Characters -X power" com N=2 (13 cartas reais, ex: OP01-022) so
    #    debuffava 1 alvo sempre -- o parser nunca extraia o count, e o
    #    executor nunca respeitava. Ambos corrigidos.
    step_op01022 = get_card_effects("OP01-022").get("when_attacking", {}).get("steps", [{}])[0]
    check("OP01-022 parseia debuff_power com count=2 (antes sempre 1)",
          step_op01022.get("count") == 2)

    me = GameState(leader=mk("XLD", "Lider", card_type="LEADER"), turn=3, don_available=5)
    kid = real_card("OP01-022")
    kid.don_attached = 1  # satisfaz [DON!! x1]
    me.field_chars = [kid]
    opp = GameState(leader=mk("XOPPL", "Lider Opp", card_type="LEADER"), turn=3)
    forte = mk("XFORTE", "Forte", power=8000, cost=6)
    medio = mk("XMEDIO", "Medio", power=5000, cost=4)
    fraco = mk("XFRACO", "Fraco", power=3000, cost=2)
    opp.field_chars = [forte, medio, fraco]
    EffectExecutor(me, opp).execute(kid, "when_attacking")
    debuffados = [c for c in opp.field_chars if c.power_buff < 0]
    check("debuff_power com count=2 afeta 2 alvos de verdade (nao so 1)",
          len(debuffados) == 2)
    check("debuff_power prioriza os 2 alvos de maior valor (Forte e Medio, nao Fraco)",
          forte in debuffados and medio in debuffados and fraco not in debuffados)


def test_total_life_lte_condicao_combinada() -> None:
    # Achado 15/07 (varredura ampla) -- "you and your opponent have a
    # total of N or less Life cards" (SOMA da vida dos 2 lados) nunca
    # existia como condicao -- 7 cartas reais (ex: OP09-114, familia
    # Revolutionary Army) tinham efeitos late-game disparando sempre, sem
    # checar o total combinado.
    conds = get_card_effects("OP09-114").get("on_play", {}).get("conditions", {})
    check("OP09-114 parseia total_life_lte=5", conds.get("total_life_lte") == 5)

    op09114 = real_card("OP09-114")
    opp_alvo = mk("XOPPC", "Alvo", power=1500, cost=1)

    me_alto = GameState(leader=mk("XLD1", "Lider", card_type="LEADER"), turn=3)
    me_alto.life = [mk(f"XL{i}", f"Vida{i}", cost=0) for i in range(3)]
    opp_alto = GameState(leader=mk("XOPPL1", "Lider Opp", card_type="LEADER"), turn=3)
    opp_alto.life = [mk(f"XOL{i}", f"OVida{i}", cost=0) for i in range(3)]
    opp_alto.field_chars = [opp_alvo]
    EffectExecutor(me_alto, opp_alto).execute(op09114, "on_play")
    check("Efeito NAO dispara com vida total > 5 (3+3=6)",
          opp_alvo in opp_alto.field_chars)

    me_baixo = GameState(leader=mk("XLD2", "Lider", card_type="LEADER"), turn=3)
    me_baixo.life = [mk(f"XL{i}", f"Vida{i}", cost=0) for i in range(2)]
    opp_baixo = GameState(leader=mk("XOPPL2", "Lider Opp", card_type="LEADER"), turn=3)
    opp_baixo.life = [mk(f"XOL{i}", f"OVida{i}", cost=0) for i in range(2)]
    opp_alvo2 = mk("XOPPC2", "Alvo2", power=1500, cost=1)
    opp_baixo.field_chars = [opp_alvo2]
    EffectExecutor(me_baixo, opp_baixo).execute(op09114, "on_play")
    check("Efeito dispara de verdade com vida total <= 5 (2+2=4)",
          opp_alvo2 not in opp_baixo.field_chars)


def test_zero_life_condicao_e_scoping_then_if() -> None:
    # Familia "If you have 0 Life cards": o gate nao pode engolir a acao
    # anterior a "Then, if". OP10-115/ST13-018 mantem o buff sempre e
    # condiciona somente o draw; EB04-051 mantem o debuff e condiciona o play.
    op10 = get_card_effects("OP10-115").get("counter", {})
    op10_steps = op10.get("steps", [])
    check("OP10-115 mantem buff incondicional antes de Then, if",
          len(op10_steps) == 2
          and op10_steps[0].get("action") == "buff_power"
          and not op10_steps[0].get("conditions"))
    check("OP10-115 condiciona somente draw a life_lte=0",
          op10_steps[1].get("action") == "draw"
          and op10_steps[1].get("conditions", {}).get("life_lte") == 0)

    emet_steps = get_card_effects("EB04-051").get("trigger", {}).get("steps", [])
    check("EB04-051 mantem debuff incondicional e condiciona somente play",
          len(emet_steps) == 2
          and emet_steps[0].get("action") == "debuff_power"
          and not emet_steps[0].get("conditions")
          and emet_steps[1].get("conditions", {}).get("life_lte") == 0)

    op06 = get_card_effects("OP06-115").get("trigger", {})
    check("OP06-115 condiciona o Trigger inteiro a life_lte=0",
          op06.get("conditions", {}).get("life_lte") == 0)

    carta = real_card("OP10-115")
    me = GameState(leader=mk("XLD0", "Lider", card_type="LEADER"), turn=3)
    opp = GameState(leader=mk("XOP0", "Lider Opp", card_type="LEADER"), turn=3)
    me.life = [mk("XLIFE", "Vida")]
    me.deck = [mk("XDRAW", "Compra")]
    alvo = me.leader
    EffectExecutor(me, opp).execute(carta, "counter")
    check("OP10-115 com 1 Life aplica buff mas nao compra",
          alvo.power_buff == 4000 and len(me.hand) == 0 and len(me.deck) == 1)

    me.life.clear()
    alvo.power_buff = 0
    EffectExecutor(me, opp).execute(carta, "counter")
    check("OP10-115 com 0 Life aplica buff e compra",
          alvo.power_buff == 4000 and len(me.hand) == 1 and len(me.deck) == 0)


def test_descarte_mao_oponente_variantes_e_escolha_cega() -> None:
    # OP03-078/OP06-097 usam imperativo "trash ... from your opponent's
    # hand": quem ativa escolhe cartas face-down (Q&A oficial), diferente
    # de "your opponent trashes", em que o dono da mao escolhe.
    issho = get_card_effects("OP03-078").get("on_play", {})
    step = issho.get("steps", [{}])[0]
    check("OP03-078 recupera On Play com gate de 6 cartas",
          issho.get("conditions", {}).get("opp_hand_gte") == 6
          and step.get("action") == "opp_trash_from_hand"
          and step.get("count") == 2
          and step.get("chosen_by") == "effect_owner_blind")

    negative = get_card_effects("OP06-097").get("main", {}).get("steps", [{}])[0]
    check("OP06-097 parseia a mesma variante imperativa como escolha cega",
          negative.get("action") == "opp_trash_from_hand"
          and negative.get("chosen_by") == "effect_owner_blind")

    brook = get_card_effects("OP09-111").get("trigger", {}).get("conditions", {})
    karasu = get_card_effects("OP12-085").get("when_attacking", {}).get("conditions", {})
    check("Condicao encadeada preserva opp_hand_gte em Brook e Karasu",
          brook.get("opp_hand_gte") == 6 and karasu.get("opp_hand_gte") == 5)

    law = get_card_effects("ST10-010").get("on_play", {})
    check("ST10-010 recupera On Play, gate 7 e custo DON -1",
          law.get("steps", [{}])[0].get("conditions", {}).get("opp_hand_gte") == 7
          and law.get("steps", [{}])[0].get("chosen_by") == "effect_owner_blind"
          and law.get("costs", [{}])[0].get("type") == "don_minus")

    card = real_card("OP03-078")
    me = GameState(leader=mk("XLDI", "Lider", card_type="LEADER"), turn=3)
    opp = GameState(leader=mk("XOPI", "Lider Opp", card_type="LEADER"), turn=3)
    opp.hand = [mk(f"XH{i}", f"Mao{i}") for i in range(5)]
    EffectExecutor(me, opp).execute(card, "on_play")
    check("OP03-078 nao descarta com apenas 5 cartas na mao adversaria",
          len(opp.hand) == 5 and len(opp.trash) == 0)

    opp.hand.append(mk("XH5", "Mao5"))
    EffectExecutor(me, opp).execute(card, "on_play")
    check("OP03-078 descarta exatamente 2 quando o gate de 6 passa",
          len(opp.hand) == 4 and len(opp.trash) == 2)


def test_reveal_top_life_play_nome_custo_e_if_you_do() -> None:
    effects = get_card_effects("ST13-010").get("activate_main", {})
    steps = effects.get("steps", [])
    check("ST13-010 tem um unico play_from_life_top, sem buff solto",
          len(steps) == 1 and steps[0].get("action") == "play_from_life_top")
    step = steps[0]
    check("ST13-010 preserva nome, custo exato e buff subordinado",
          step.get("filter_name") == "portgas.d.ace"
          and step.get("cost_eq") == 5
          and step.get("on_success_steps", [{}])[0].get("amount") == 2000)
    for code, nome in (("ST13-007", "sabo"), ("ST13-014", "monkey.d.luffy")):
        sibling = get_card_effects(code).get("activate_main", {}).get("steps", [{}])[0]
        check(f"{code} usa a mesma gramatica com filtro {nome}",
              sibling.get("action") == "play_from_life_top"
              and sibling.get("filter_name") == nome)

    source_bad = real_card("ST13-010")
    me_bad = GameState(leader=mk("XLDA", "Lider", card_type="LEADER"), turn=3)
    opp_bad = GameState(leader=mk("XOPA", "Lider Opp", card_type="LEADER"), turn=3)
    me_bad.field_chars = [source_bad]
    wrong = mk("XWRONG", "Portgas.D.Ace", cost=4)
    me_bad.life = [wrong]
    EffectExecutor(me_bad, opp_bad).execute(source_bad, "activate_main")
    check("Filtro falho mantem Life e nao concede buff If you do",
          me_bad.life == [wrong] and me_bad.leader.power_buff == 0)

    source_ok = real_card("ST13-010")
    me_ok = GameState(leader=mk("XLDB", "Lider", card_type="LEADER"), turn=3)
    opp_ok = GameState(leader=mk("XOPB", "Lider Opp", card_type="LEADER"), turn=3)
    me_ok.field_chars = [source_ok]
    ace5 = mk("XACE5", "Portgas.D.Ace", cost=5)
    me_ok.life = [ace5]
    EffectExecutor(me_ok, opp_ok).execute(source_ok, "activate_main")
    check("Filtro correto joga da Life gratuitamente e concede +2000",
          not me_ok.life and ace5 in me_ok.field_chars
          and me_ok.leader.power_buff == 2000)


def test_op10_022_condicao_custo_e_play_life_por_tipo() -> None:
    effect = get_card_effects("OP10-022").get("activate_main", {})
    step = effect.get("steps", [{}])[0]
    check("OP10-022 estrutura condicao, custo e play da Life",
          effect.get("conditions", {}).get("total_chars_cost_gte") == 5
          and effect.get("costs", [{}])[0].get("type") == "return_own_character_to_hand"
          and step.get("action") == "play_from_life_top"
          and step.get("filter_type") == "supernovas"
          and step.get("cost_lte") == 5)

    law = real_card("OP10-022")
    law.don_attached = 1
    me_fail = GameState(leader=law, turn=3)
    opp_fail = GameState(leader=mk("XOPL", "Lider Opp", card_type="LEADER"), turn=3)
    cheap = mk("XC1", "Cheap", cost=4)
    wrong_top = mk("XWT", "Wrong", cost=4, sub_types="Navy")
    me_fail.field_chars = [cheap]
    me_fail.life = [wrong_top]
    EffectExecutor(me_fail, opp_fail).execute(law, "activate_main")
    check("OP10-022 nao paga bounce se condicao total cost <5",
          cheap in me_fail.field_chars and not me_fail.hand)

    law2 = real_card("OP10-022")
    law2.don_attached = 1
    me_wrong = GameState(leader=law2, turn=3)
    opp_wrong = GameState(leader=mk("XOP2", "Lider Opp", card_type="LEADER"), turn=3)
    body5 = mk("XC5", "Body5", cost=5)
    me_wrong.field_chars = [body5]
    me_wrong.life = [wrong_top]
    EffectExecutor(me_wrong, opp_wrong).execute(law2, "activate_main")
    check("OP10-022 nao paga bounce quando topo da Life falha o filtro",
          body5 in me_wrong.field_chars and not me_wrong.hand)

    law3 = real_card("OP10-022")
    law3.don_attached = 1
    me_ok = GameState(leader=law3, turn=3)
    opp_ok = GameState(leader=mk("XOP3", "Lider Opp", card_type="LEADER"), turn=3)
    body6 = mk("XC6", "Body6", cost=6)
    target = mk("XSUP", "Supernova alvo", cost=5, sub_types="Supernovas")
    me_ok.field_chars = [body6]
    me_ok.life = [target]
    EffectExecutor(me_ok, opp_ok).execute(law3, "activate_main")
    check("OP10-022 paga bounce e joga topo elegivel da Life",
          body6 in me_ok.hand and target in me_ok.field_chars and not me_ok.life)


def test_rush_character_fraseado_condicional_e_auras() -> None:
    zoro_effect = get_card_effects("EB02-019").get("passive", {})
    check("EB02-019 usa Rush: Character e exige 2 Characters oponentes",
          zoro_effect.get("steps", [{}])[0].get("action") == "gain_rush_character"
          and zoro_effect.get("conditions", {}).get("opp_chars_gte") == 2)

    me1 = GameState(leader=mk("XLDR1", "Lider", card_type="LEADER"), turn=3)
    zoro1 = real_card("EB02-019")
    zoro1.just_played = True
    me1.field_chars = [zoro1]
    opp1 = GameState(leader=mk("XOPR1", "Lider Opp", card_type="LEADER"), turn=3)
    opp1.field_chars = [mk("XO1", "Opp1")]
    apply_conditional_keyword_passives(me1, opp1)
    check("EB02-019 nao ganha permissao com apenas 1 Character oponente",
          not zoro1.has_rush_character)

    me2 = GameState(leader=mk("XLDR2", "Lider", card_type="LEADER"), turn=3)
    zoro2 = real_card("EB02-019")
    zoro2.just_played = True
    me2.field_chars = [zoro2]
    opp2 = GameState(leader=mk("XOPR2", "Lider Opp", card_type="LEADER"), turn=3)
    opp2.field_chars = [mk("XO2", "Opp2"), mk("XO3", "Opp3")]
    apply_conditional_keyword_passives(me2, opp2)
    check("EB02-019 ganha somente Rush: Character com 2 oponentes",
          zoro2.has_rush_character and zoro2.rush_character_only_this_turn
          and not zoro2.has_rush)

    corrida = real_card("OP04-096")
    dressrosa = mk("XDRE", "Dressrosa", sub_types="Dressrosa")
    dressrosa.just_played = True
    me_stage = GameState(leader=mk("XLDDS", "Lider", card_type="LEADER", sub_types="Dressrosa"), turn=3)
    me_stage.field_stage = corrida
    me_stage.field_chars = [dressrosa]
    opp_stage = GameState(leader=mk("XOPS", "Lider Opp", card_type="LEADER"), turn=3)
    apply_conditional_keyword_passives(me_stage, opp_stage)
    check("Corrida Coliseum concede Rush: Character ao tipo, nao Rush completo",
          dressrosa.has_rush_character and not dressrosa.has_rush)

    shira = real_card("P-091")
    shira.rested = False
    nept = mk("XNEP", "Neptunian", sub_types="Neptunian")
    nept.just_played = True
    me_sel = GameState(leader=mk("XLDP", "Lider", card_type="LEADER"), turn=3)
    me_sel.field_chars = [shira, nept]
    opp_sel = GameState(leader=mk("XOPP", "Lider Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me_sel, opp_sel).execute(shira, "activate_main")
    check("P-091 resta a si e concede Rush: Character ao Neptunian",
          shira.rested and nept.has_rush_character and not nept.has_rush)


def test_comparacao_don_proprio_lte_oponente() -> None:
    cond = get_card_effects("EB02-035").get("on_play", {}).get("conditions", {})
    check("EB02-035 parseia comparacao DON proprio <= DON oponente",
          cond.get("don_on_field_lte_opp") is True)
    for code, trigger in (("OP06-061", "on_play"), ("OP07-068", "when_attacking"),
                          ("OP12-078", "main")):
        card_cond = get_card_effects(code).get(trigger, {}).get("conditions", {})
        check(f"{code} preserva o mesmo gate comparativo",
              card_cond.get("don_on_field_lte_opp") is True)

    card = real_card("EB02-035")
    me_high = GameState(leader=mk("XLDH", "Lider", card_type="LEADER"), turn=3,
                        don_available=5)
    opp_low = GameState(leader=mk("XOPL", "Lider Opp", card_type="LEADER"), turn=3,
                        don_available=4)
    me_high.deck = [mk("XD1", "Compra1")]
    EffectExecutor(me_high, opp_low).execute(card, "on_play")
    check("EB02-035 nao compra quando possui mais DON que o oponente",
          len(me_high.hand) == 0 and len(me_high.deck) == 1)

    me_equal = GameState(leader=mk("XLDE", "Lider", card_type="LEADER"), turn=3,
                         don_available=4)
    opp_equal = GameState(leader=mk("XOPE", "Lider Opp", card_type="LEADER"), turn=3,
                          don_available=4)
    me_equal.deck = [mk("XD2", "Compra2")]
    EffectExecutor(me_equal, opp_equal).execute(card, "on_play")
    check("EB02-035 compra quando os totais de DON sao iguais",
          len(me_equal.hand) == 1 and not me_equal.deck)

    for code in ("OP06-072", "OP07-064"):
        conds = get_card_effects(code).get("passive", {}).get("conditions", {})
        check(f"{code} preserva diferenca minima de 2 DON",
              conds.get("don_fewer_than_opp_by_gte") == 2)

    sanji = real_card("OP07-064")
    sanji_step = next(s for s in get_card_effects("OP07-064")["passive"]["steps"]
                      if s.get("action") == "debuff_cost")
    check("OP07-064 marca reducao como custo da propria carta na mao",
          sanji_step.get("target") == "own_play_self")
    opp_5 = GameState(leader=mk("XSO5", "Opp", card_type="LEADER"),
                      don_available=5)
    for own_don, expected in ((3, 3), (4, 6), (5, 6), (6, 6)):
        me_sanji = GameState(
            leader=mk(f"XSD{own_don}", "Lider", card_type="LEADER"),
            don_available=own_don,
        )
        check(f"Sanji com {own_don} DON contra 5 custa {expected}",
              effective_hand_play_cost(me_sanji, sanji, opp_5) == expected)

    cosette = real_card("OP06-072")
    germa = mk("XGER", "Lider GERMA", card_type="LEADER",
               sub_types="GERMA 66")
    me_cosette = GameState(leader=germa, field_chars=[cosette], don_available=3)
    apply_conditional_keyword_passives(me_cosette, opp_5)
    check("Cosette ganha Blocker com lider GERMA e diferenca de 2 DON",
          cosette.has_blocker)
    cosette2 = real_card("OP06-072")
    me_cosette2 = GameState(leader=germa, field_chars=[cosette2], don_available=4)
    apply_conditional_keyword_passives(me_cosette2, opp_5)
    check("Cosette nao ganha Blocker com diferenca de apenas 1 DON",
          not cosette2.has_blocker)


def test_custos_condicionais_da_propria_carta_na_mao() -> None:
    empty_opp = GameState(leader=mk("XHCO", "Opp", card_type="LEADER"))

    def cost(code, me, opp=empty_opp):
        return effective_hand_play_cost(me, real_card(code), opp)

    eb = real_card("EB04-061")
    me = GameState(leader=mk("XHCL", "Lider", card_type="LEADER"),
                   life=[mk("XLF", "Life")])
    check("EB04-061 reduz 1 com Life <= 1", cost("EB04-061", me) == eb.cost - 1)
    me.life.append(mk("XLF2", "Life 2"))
    check("EB04-061 nao reduz com 2 Life", cost("EB04-061", me) == eb.cost)

    pincers = real_card("OP15-013")
    me = GameState(leader=mk("XLP0", "Lider", power=0, card_type="LEADER"))
    check("OP15-013 reduz 2 com Leader em 0 power", cost("OP15-013", me) == pincers.cost - 2)

    events = [mk(f"XEV{i}", f"Event {i}", card_type="EVENT") for i in range(4)]
    me = GameState(leader=mk("XEVL", "Lider", card_type="LEADER"), trash=events)
    check("OP15-021 reduz 3 com 4 Events no trash",
          cost("OP15-021", me) == real_card("OP15-021").cost - 3)

    wb = mk("XWB", "Newgate", power=8000, sub_types="Whitebeard Pirates")
    me = GameState(leader=mk("XWBL", "Lider", card_type="LEADER"), field_chars=[wb])
    check("OP16-005 exige poder 8000 e tipo Whitebeard Pirates",
          cost("OP16-005", me) == real_card("OP16-005").cost - 3)
    me.field_chars = [mk("XNV8", "Forte Navy", power=8000, sub_types="Navy")]
    check("OP16-005 nao aceita Character 8000 de tipo errado",
          cost("OP16-005", me) == real_card("OP16-005").cost)

    ace_leader = mk("XACE", "Portgas.D.Ace", card_type="LEADER")
    me = GameState(leader=ace_leader, don_available=6)
    check("OP16-015 exige Leader Ace e 6 DON",
          cost("OP16-015", me) == real_card("OP16-015").cost - 2)
    me.don_available = 5
    check("OP16-015 nao reduz com apenas 5 DON",
          cost("OP16-015", me) == real_card("OP16-015").cost)

    me = GameState(leader=mk("XTRL", "Lider", card_type="LEADER"),
                   trash=[mk(f"XT{i}", f"Trash {i}") for i in range(15)])
    check("PRB02-014 reduz 3 com 15 cartas no trash",
          cost("PRB02-014", me) == real_card("PRB02-014").cost - 3)

    me = GameState(leader=mk("X10L", "Lider", card_type="LEADER"),
                   field_chars=[mk("X10K", "Forte", power=10000)])
    check("ST23-001 reduz 4 com Character proprio de 10000+",
          cost("ST23-001", me) == real_card("ST23-001").cost - 4)

    me = GameState(leader=mk("XOPL", "Lider", card_type="LEADER"))
    opp = GameState(leader=mk("XOPR", "Opp", card_type="LEADER"),
                    field_chars=[mk("X800", "Opp forte", power=8000)])
    check("ST23-002 reduz 3 com Character oponente de base power 8000+",
          cost("ST23-002", me, opp) == real_card("ST23-002").cost - 3)

    me = GameState(leader=mk("XSNL", "Lider", card_type="LEADER"),
                   field_chars=[mk("XSNJ", "Sanji", power=7000)])
    check("ST26-001 exige Sanji ou San-Gorou de base power 7000+",
          cost("ST26-001", me) == real_card("ST26-001").cost - 5)
    sanji_buffed = mk("XSNB", "Sanji", power=6000)
    sanji_buffed.power_buff = 1000
    me.field_chars = [sanji_buffed]
    check("ST26-001 usa base power; buff nao transforma 6000 em elegivel",
          cost("ST26-001", me) == real_card("ST26-001").cost)

    fish = mk("XFSL", "Lider", card_type="LEADER", sub_types="Fish-Man")
    me = GameState(leader=fish, life=[mk(f"XFL{i}", "Life") for i in range(3)])
    opp = GameState(leader=mk("XFOP", "Opp", card_type="LEADER"), don_rested=5)
    check("OP11-023 define custo 3 com os 3 gates satisfeitos",
          cost("OP11-023", me, opp) == 3)
    opp.don_rested = 4
    check("OP11-023 nao define custo sem 5 cartas oponentes restadas",
          cost("OP11-023", me, opp) == real_card("OP11-023").cost)

    sky = mk("XSKY", "Sky", power=7000, sub_types="Sky Island")
    me = GameState(leader=mk("XSKL", "Lider", card_type="LEADER"), field_chars=[sky])
    check("OP15-102 define custo 3 com Sky Island de 7000+",
          cost("OP15-102", me) == 3)

    check("EB04-041 preserva gate de 4 DON no campo",
          get_card_effects("EB04-041")["main"]["conditions"].get(
              "don_on_field_gte") == 4)
    check("OP11-075 preserva gate de 7 DON no campo",
          get_card_effects("OP11-075")["on_play"]["conditions"].get(
              "don_on_field_gte") == 7)
    check("OP08-028 preserva gate de 7 cartas oponentes restadas",
          get_card_effects("OP08-028")["on_play"]["conditions"].get(
              "opp_rested_cards_gte") == 7)
    op10_conds = get_card_effects("OP10-003")["end_of_turn"]["conditions"]
    check("OP10-003 preserva poder 6000 e tipo Donquixote Pirates",
          op10_conds.get("other_char_power_gte") == 6000
          and op10_conds.get("other_char_power_gte_type") == "donquixote pirates")


def test_searcher_cost_gte_e_peek_deck_oponente() -> None:
    for code, trigger, minimum in (
        ("EB02-008", "main", 4), ("OP09-069", "on_play", 2),
        ("OP11-048", "on_play", 2), ("OP11-070", "on_play", 2),
        ("OP12-017", "main", 3), ("OP13-012", "on_play", 2),
        ("OP13-016", "on_play", 3), ("OP14-042", "on_play", 2),
        ("ST28-005", "on_play", 2),
    ):
        add = next(s for s in get_card_effects(code)[trigger]["steps"]
                   if s.get("action") == "add_to_hand")
        check(f"{code} preserva cost_gte={minimum} no searcher",
              add.get("cost_gte") == minimum)

    pudding = real_card("OP11-070")
    cheap = mk("XPCH", "Big Mom barata", cost=1, sub_types="Big Mom Pirates")
    eligible = mk("XPEL", "Big Mom elegivel", cost=2, sub_types="Big Mom Pirates")
    me = GameState(leader=mk("XPL", "Lider", card_type="LEADER"),
                   deck=[cheap, eligible], field_chars=[pudding])
    opp = GameState(leader=mk("XPO", "Opp", card_type="LEADER"),
                    deck=[mk("XTOP", "Topo oculto")])
    EffectExecutor(me, opp).execute(pudding, "on_play")
    check("Pudding busca custo 2+ e rejeita Big Mom de custo 1",
          eligible in me.hand and cheap not in me.hand)

    pudding.don_attached = 1
    before = list(opp.deck)
    EffectExecutor(me, opp).execute(pudding, "activate_main")
    entry = get_card_effects("OP11-070")["activate_main"]
    check("Pudding preserva DON x1, rest_self e peek do topo adversario",
          entry.get("don_requirement") == 1
          and any(c.get("type") == "rest_self" for c in entry.get("costs", []))
          and any(s.get("action") == "peek_opp_deck_top" for s in entry["steps"])
          and pudding.rested and opp.deck == before)
    check("OP11-074 tambem recupera DON x1 normalizado sem letra x",
          get_card_effects("OP11-074")["activate_main"].get("don_requirement") == 1)

    for code, trigger, nested_action in (
        ("OP11-066", "activate_main", "ko"),
        ("OP11-071", "activate_main", "draw"),
        ("OP11-073", "on_opp_attack", "buff_power"),
        ("OP11-074", "activate_main", "rest_opp_character"),
    ):
        reveal = next(
            s for s in get_card_effects(code)[trigger]["steps"]
            if s.get("action") == "reveal_opp_deck_top_choose_cost")
        check(f"{code} condiciona efeito ao custo revelado",
              any(s.get("action") == nested_action
                  for s in reveal.get("on_match_steps", [])))

    # OP11-066: o palpite usa o custo modal do censo (2), nunca o topo
    # oculto. Errar nao causa K.O., mas o "Then, add DON" resolve mesmo
    # assim; acertar permite o K.O. subsequente.
    oven = real_card("OP11-066")
    victim = mk("XRV", "Vitima", cost=3)
    me_r = GameState(leader=mk("XRML", "Lider", card_type="LEADER"),
                     field_chars=[oven], don_deck=2)
    opp_r = GameState(leader=mk("XROL", "Opp", card_type="LEADER"),
                      field_chars=[victim], deck=[mk("XRT3", "Topo 3", cost=3)])
    opp_r.full_deck_census = {"by_cost": {2: 8, 3: 4}}
    EffectExecutor(me_r, opp_r).execute(oven, "activate_main")
    check("OP11-066 erra custo sem K.O. e ainda adiciona DON restado",
          victim in opp_r.field_chars and me_r.don_rested == 1)

    oven2 = real_card("OP11-066")
    victim2 = mk("XRV2", "Vitima 2", cost=3)
    me_r2 = GameState(leader=mk("XRML2", "Lider", card_type="LEADER"),
                      field_chars=[oven2], don_deck=2)
    opp_r2 = GameState(leader=mk("XROL2", "Opp", card_type="LEADER"),
                       field_chars=[victim2], deck=[mk("XRT2", "Topo 2", cost=2)])
    opp_r2.full_deck_census = {"by_cost": {2: 8, 3: 4}}
    EffectExecutor(me_r2, opp_r2).execute(oven2, "activate_main")
    check("OP11-066 acerta custo e executa K.O. condicional",
          victim2 not in opp_r2.field_chars and victim2 in opp_r2.trash)


def test_evento_parametrizado_de_don_devolvido() -> None:
    for code, threshold in (("OP06-042", 1), ("EB02-035", 2),
                            ("OP09-061", 2), ("P-077", 2)):
        entry = get_card_effects(code).get("when_don_returned", {})
        check(f"{code} parseia limiar {threshold} por resolucao",
              entry.get("return_count_gte") == threshold)
    luffy_steps = get_card_effects("OP09-061")["when_don_returned"]["steps"]
    check("OP09-061 preserva 1 DON ativo e 1 DON adicional restado",
          luffy_steps == [{"action": "add_don", "count": 1},
                          {"action": "add_don", "count": 1, "rested": True}])

    # Duas devolucoes separadas de 1 nao equivalem a uma devolucao de 2+.
    sanji = real_card("EB02-035")
    me = GameState(leader=mk("XDRL", "Lider", card_type="LEADER"),
                   field_chars=[sanji], don_available=4, don_deck=6,
                   global_turn=1, is_active_turn=True)
    opp = GameState(leader=mk("XDRO", "Opp", card_type="LEADER"),
                    global_turn=1, is_active_turn=False)
    ee = EffectExecutor(me, opp)
    ee._return_don_to_deck(1)
    ee._return_don_to_deck(1)
    check("EB02-035 nao acumula duas resolucoes separadas de DON -1",
          me.don_available == 2 and me.don_deck == 8)

    sanji2 = real_card("EB02-035")
    me2 = GameState(leader=mk("XDR2", "Lider", card_type="LEADER"),
                    field_chars=[sanji2], don_available=6, don_deck=4,
                    global_turn=2, is_active_turn=True)
    opp2 = GameState(leader=mk("XDO2", "Opp", card_type="LEADER"),
                     global_turn=2, is_active_turn=False)
    ee2 = EffectExecutor(me2, opp2)
    ee2._return_don_to_deck(2)
    check("EB02-035 dispara ao devolver 2 DON na mesma resolucao",
          me2.don_available == 5 and me2.don_deck == 5)
    ee2._return_don_to_deck(2)
    check("EB02-035 respeita once per turn no evento central",
          me2.don_available == 3 and me2.don_deck == 7)

    reiju = real_card("OP06-042")
    me3 = GameState(leader=reiju, deck=[mk("XBUY", "Compra")],
                    don_available=2, don_deck=8, global_turn=3,
                    is_active_turn=True)
    opp3 = GameState(leader=mk("XDO3", "Opp", card_type="LEADER"),
                     global_turn=3, is_active_turn=False)
    EffectExecutor(me3, opp3)._return_don_to_deck(1)
    check("gatilho de 1 DON da OP06-042 dispara no turno correto",
          len(me3.hand) == 1)

    ulti = real_card("P-077")
    stage = mk("XSTG", "Stage Roxo", card_type="STAGE", color="Purple")
    stage.rested = True
    me4 = GameState(leader=mk("XDR4", "Lider", card_type="LEADER"),
                    field_chars=[ulti], field_stage=stage,
                    don_available=4, don_deck=6, global_turn=4,
                    is_active_turn=True)
    opp4 = GameState(leader=mk("XDO4", "Opp", card_type="LEADER"),
                     global_turn=4, is_active_turn=False)
    EffectExecutor(me4, opp4)._return_don_to_deck(2)
    p077_steps = get_card_effects("P-077")["when_don_returned"]["steps"]
    p077 = next(s for s in p077_steps if s.get("action") == "set_active")
    check("P-077 aponta para Stage roxo, nao Character",
          p077.get("target") == "own_stage" and p077.get("color") == "purple")
    check("P-077 preserva ordem: adiciona DON antes de reativar Stage",
          [s.get("action") for s in p077_steps] == ["add_don", "set_active"])
    check("P-077 reativa o Stage roxo quando o evento dispara", not stage.rested)


def test_ace_evento_dano_ou_ko_proprio() -> None:
    effects = get_card_effects("OP13-002")
    first = effects["on_opp_attack"]
    event = effects["when_damage_or_own_char_ko"]
    check("Ace separa debuff defensivo do draw por evento",
          [s.get("action") for s in first["steps"]] == ["debuff_power"]
          and [s.get("action") for s in event["steps"]] == ["draw"])
    check("Ace preserva DON x1, once e base power 6000+",
          event.get("don_requirement") == 1
          and event.get("once_per_turn") is True
          and event.get("own_char_base_power_gte") == 6000)

    ace = real_card("OP13-002")
    ace.don_attached = 1
    draw1, draw2 = mk("XAD1", "Compra dano"), mk("XAD2", "Compra KO")
    me = GameState(leader=ace, deck=[draw2, draw1], global_turn=3)
    opp = GameState(leader=mk("XAOL", "Opp", card_type="LEADER"), global_turn=3)
    ee = EffectExecutor(me, opp)
    ee._dispatch_damage_or_own_char_ko(me)
    check("Ace compra ao receber dano", draw1 in me.hand)
    ee._dispatch_damage_or_own_char_ko(me, mk("XAK6", "KO 6000", power=6000))
    check("Ace respeita once per turn entre dano e KO", draw2 not in me.hand)

    ace2 = real_card("OP13-002")
    ace2.don_attached = 1
    draw3 = mk("XAD3", "Compra valida")
    me2 = GameState(leader=ace2, deck=[draw3], global_turn=4)
    opp2 = GameState(leader=mk("XAO2", "Opp", card_type="LEADER"), global_turn=4)
    ee2 = EffectExecutor(me2, opp2)
    ee2._dispatch_damage_or_own_char_ko(me2, mk("XAK5", "KO 5000", power=5000))
    check("Ace nao compra por KO abaixo de base power 6000", draw3 in me2.deck)
    ee2._dispatch_damage_or_own_char_ko(me2, mk("XAK7", "KO 7000", power=7000))
    check("Ace compra por KO de base power 6000+", draw3 in me2.hand)


def test_custo_composto_trash_para_fundo() -> None:
    for code in ("OP05-082", "OP05-088"):
        costs = get_card_effects(code).get("activate_main", {}).get("costs", [])
        check(f"{code} preserva rest_self + 2 cartas do trash ao fundo",
              {"rest_self", "place_from_trash_bottom_deck"}.issubset(
                  {c.get("type") for c in costs})
              and next(c for c in costs
                       if c.get("type") == "place_from_trash_bottom_deck").get("count") == 2)

    shira_entry = get_card_effects("OP05-082")["activate_main"]
    check("Shirahoshi limita apenas o descarte a opp_hand_gte=6",
          not shira_entry.get("conditions")
          and shira_entry["steps"][0].get("conditions", {}).get("opp_hand_gte") == 6)

    mansherry = real_card("OP05-088")
    target = mk("XREC", "Alvo Preto", cost=4, color="Black")
    filler1 = mk("XF01", "Filler 1", card_type="EVENT", color="Red")
    filler2 = mk("XF02", "Filler 2", card_type="EVENT", color="Red")
    me = GameState(leader=mk("XCL1", "Lider", card_type="LEADER"),
                   field_chars=[mansherry], trash=[target, filler1, filler2],
                   don_available=1)
    opp = GameState(leader=mk("XCO1", "Opp", card_type="LEADER"))
    EffectExecutor(me, opp).execute(mansherry, "activate_main")
    check("Mansherry paga os 3 custos e recupera o alvo elegivel",
          mansherry.rested and me.don_available == 0 and me.don_rested == 1
          and target in me.hand and len(me.trash) == 0 and len(me.deck) == 2)

    mansherry2 = real_card("OP05-088")
    only = mk("XONE", "Unica no trash", cost=4, color="Black")
    me2 = GameState(leader=mk("XCL2", "Lider", card_type="LEADER"),
                    field_chars=[mansherry2], trash=[only], don_available=1)
    opp2 = GameState(leader=mk("XCO2", "Opp", card_type="LEADER"))
    EffectExecutor(me2, opp2).execute(mansherry2, "activate_main")
    check("custo composto impagavel nao resta Mansherry nem DON parcialmente",
          not mansherry2.rested and me2.don_available == 1
          and me2.don_rested == 0 and me2.trash == [only])

    shira = real_card("OP05-082")
    me3 = GameState(leader=mk("XSL3", "Lider", card_type="LEADER"),
                    field_chars=[shira],
                    trash=[mk("XSF1", "Filler 1"), mk("XSF2", "Filler 2")])
    opp3 = GameState(leader=mk("XSO3", "Opp", card_type="LEADER"),
                     hand=[mk(f"XH{i}", f"Mao {i}") for i in range(5)])
    EffectExecutor(me3, opp3).execute(shira, "activate_main")
    check("engine nao paga Shirahoshi sem beneficio util apesar de ser legal",
          not shira.rested and len(me3.trash) == 2 and len(opp3.hand) == 5)

    opp3.hand.append(mk("XH5", "Mao 5"))
    EffectExecutor(me3, opp3).execute(shira, "activate_main")
    check("Shirahoshi paga custo e descarta quando o gate do step passa",
          shira.rested and not me3.trash and len(me3.deck) == 2
          and len(opp3.hand) == 5)


def test_reducao_de_custo_com_limite() -> None:
    mary_step = get_card_effects("OP05-097")["your_turn"]["steps"][0]
    check("Mary Geoise preserva custo minimo 2",
          mary_step.get("action") == "buff_cost"
          and mary_step.get("cost_gte") == 2
          and mary_step.get("filter_type") == "celestial dragons")

    kinemon_step = get_card_effects("OP02-025")["activate_main"]["steps"][0]
    check("Kin'emon preserva proximo play Wano de custo minimo 3",
          kinemon_step.get("duration") == "next_play_only"
          and kinemon_step.get("cost_gte") == 3
          and kinemon_step.get("filter_type") == "land of wano")

    rosinante_entry = get_card_effects("OP12-061")["activate_main"]
    rosinante_step = rosinante_entry["steps"][0]
    check("Rosinante preserva DON -1 e proximo Law de custo minimo 4",
          any(c.get("type") == "don_minus" and c.get("count") == 1
              for c in rosinante_entry.get("costs", []))
          and rosinante_step.get("amount") == 2
          and rosinante_step.get("filter_name") == "trafalgar law"
          and rosinante_step.get("cost_gte") == 4)

    mary = real_card("OP05-097")
    me = GameState(leader=mk("XMGL", "Lider", card_type="LEADER"),
                   field_stage=mary)
    celestial_1 = mk("XMC1", "Celestial 1", cost=1,
                     sub_types="Celestial Dragons")
    celestial_2 = mk("XMC2", "Celestial 2", cost=2,
                     sub_types="Celestial Dragons")
    outsider = mk("XMO", "Outro", cost=4, sub_types="Navy")
    check("Mary reduz apenas Celestial Dragons de custo original 2+",
          effective_hand_play_cost(me, celestial_1) == 1
          and effective_hand_play_cost(me, celestial_2) == 1
          and effective_hand_play_cost(me, outsider) == 4)

    kinemon = real_card("OP02-025")
    me2 = GameState(leader=kinemon, don_available=3)
    opp2 = GameState(leader=mk("XKOP", "Opp", card_type="LEADER"))
    EffectExecutor(me2, opp2).execute(kinemon, "activate_main")
    wano_2 = mk("XKW2", "Wano barato", cost=2, sub_types="Land of Wano")
    wano_4 = mk("XKW4", "Wano elegivel", cost=4, sub_types="Land of Wano")
    other_4 = mk("XKO4", "Outro", cost=4, sub_types="Navy")
    check("Kin'emon aplica a reducao somente ao proximo Wano elegivel",
          effective_hand_play_cost(me2, wano_2) == 2
          and effective_hand_play_cost(me2, wano_4) == 3
          and effective_hand_play_cost(me2, other_4) == 4)
    consume_play_cost_reductions(me2, wano_2)
    check("Play inelegivel nao consome a reducao de Kin'emon",
          len(me2.pending_play_cost_reductions) == 1)
    consume_play_cost_reductions(me2, wano_4)
    check("Play elegivel consome a reducao de Kin'emon",
          not me2.pending_play_cost_reductions)

    rosinante = real_card("OP12-061")
    me3 = GameState(leader=rosinante, don_available=5, don_deck=5)
    opp3 = GameState(leader=mk("XROP", "Opp", card_type="LEADER"))
    EffectExecutor(me3, opp3).execute(rosinante, "activate_main")
    law_3 = mk("XRL3", "Trafalgar Law", cost=3)
    law_5 = mk("XRL5", "Trafalgar Law", cost=5)
    not_law = mk("XRNL", "Bepo", cost=5)
    check("Rosinante devolve 1 DON e reduz apenas Law de custo original 4+",
          me3.don_available == 4 and me3.don_deck == 6
          and effective_hand_play_cost(me3, law_3) == 3
          and effective_hand_play_cost(me3, law_5) == 3
          and effective_hand_play_cost(me3, not_law) == 5)
    me3.hand = [law_5]
    EffectExecutor(me3, opp3)._execute_step(
        {"action": "play_card", "filter_name": "trafalgar law", "cost_lte": 99},
        rosinante,
    )
    check("Law jogado gratis por efeito nao consome reducao pendente de Rosinante",
          law_5 in me3.field_chars
          and len(me3.pending_play_cost_reductions) == 1)


def test_don_on_field_lte_condicao_ausente() -> None:
    # Achado 15/07 -- "if you have N or less DON!! cards on your field"
    # (proprio lado) nunca existia, so o "N or more" (don_on_field_gte).
    # OP15-067 (e familia OP15-060/061/063/066/068) dava Rush/Blocker/
    # imunidade SEMPRE, sem checar se o DON estava realmente baixo.
    conds = get_card_effects("OP15-067").get("passive", {}).get("conditions", {})
    check("OP15-067 parseia don_on_field_lte=6", conds.get("don_on_field_lte") == 6)

    rush_char = real_card("OP15-067")

    me_muito_don = GameState(leader=mk("XLD", "Lider", card_type="LEADER"), turn=3,
                              don_available=7)
    me_muito_don.field_chars = [rush_char]
    opp = GameState(leader=mk("XOPPL", "Lider Opp", card_type="LEADER"), turn=3)
    apply_conditional_keyword_passives(me_muito_don, opp)
    check("Com DON > 6 no campo, NAO ganha Rush", not rush_char.has_rush)

    rush_char2 = real_card("OP15-067")
    me_pouco_don = GameState(leader=mk("XLD2", "Lider", card_type="LEADER"), turn=3,
                              don_available=5)
    me_pouco_don.field_chars = [rush_char2]
    apply_conditional_keyword_passives(me_pouco_don, opp)
    check("Com DON <= 6 no campo, ganha Rush de verdade", rush_char2.has_rush)


def test_black_hole_negate_e_ko_encadeado() -> None:
    # Achado 15/07 -- OP09-098 Black Hole: "negate the effect of up to 1 of
    # your opponent's Characters during this turn. Then, if that Character
    # has a cost of 4 or less, K.O. it." A segunda clausula (ko_selected)
    # faltava por completo -- so o negate_effect sobrevivia no parse.
    steps = get_card_effects("OP09-098").get("main", {}).get("steps", [])
    check("OP09-098 parseia ko_selected cost_lte=4",
          any(s.get("action") == "ko_selected" and s.get("cost_lte") == 4 for s in steps))

    black_hole = real_card("OP09-098")
    leader_bb = mk("XBB", "Lider BB", card_type="LEADER", sub_types="Blackbeard Pirates")

    # Caso 1: alvo custo <= 4 -- deve ser negado E KOed.
    alvo_barato = mk("XA1", "Alvo Barato", cost=3)
    me = GameState(leader=leader_bb, turn=3)
    me.field_chars = [black_hole]
    opp = GameState(leader=mk("XOPPL", "Lider Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [alvo_barato]
    log = EffectExecutor(me, opp).execute(black_hole, "main")
    log_str = " | ".join(log) if isinstance(log, list) else str(log)
    check("Negou e KOed alvo de custo <= 4", "KO" in log_str and alvo_barato not in opp.field_chars)
    check("Alvo custo <= 4 foi pro trash", alvo_barato in opp.trash)

    # Caso 2: alvo custo > 4 -- so nega, nao mata.
    black_hole2 = real_card("OP09-098")
    alvo_caro = mk("XA2", "Alvo Caro", cost=6)
    me2 = GameState(leader=leader_bb, turn=3)
    me2.field_chars = [black_hole2]
    opp2 = GameState(leader=mk("XOPPL2", "Lider Opp", card_type="LEADER"), turn=3)
    opp2.field_chars = [alvo_caro]
    EffectExecutor(me2, opp2).execute(black_hole2, "main")
    check("Alvo custo > 4 NAO foi KOed (so negado)", alvo_caro in opp2.field_chars)


def test_rebecca_add_from_trash_range_exclude_e_ordem() -> None:
    # Achado 15/07 -- OP05-091 Rebecca: "Add up to 1 black Character card
    # with a cost of 3 to 7 OTHER THAN [Rebecca] from your trash to your
    # hand. Then, play up to 1 black Character card with a cost of 3 or
    # less from your hand rested." 3 bugs reais no mesmo parse: (1)
    # "other than [Rebecca]" virava filter_name='rebecca' (INCLUI so
    # Rebecca -- exatamente o oposto do texto), (2) faixa "3 to 7" nunca
    # batia em nenhuma regex (sem limite de custo nenhum), (3) o step de
    # play vinha ANTES do add no parse, embora narrativamente o add
    # aconteca primeiro.
    steps = get_card_effects("OP05-091").get("on_play", {}).get("steps", [])
    check("OP05-091 parseia exclude_name=rebecca (nao filter_name)",
          steps and steps[0].get("action") == "add_from_trash"
          and steps[0].get("exclude_name") == "rebecca" and "filter_name" not in steps[0])
    check("OP05-091 parseia faixa de custo 3-7", steps[0].get("cost_gte") == 3 and steps[0].get("cost_lte") == 7)
    check("OP05-091 add_from_trash vem ANTES do play_card na lista de steps",
          any(s.get("action") == "play_card" for s in steps[1:]))

    rebecca = real_card("OP05-091")
    alvo_barato = mk("XRB1", "Zoro Custo 3", cost=3, color="Black")
    rebecca_no_trash = mk("XRB2", "Rebecca no Trash", cost=2, color="Black", sub_types="Dressrosa")
    fora_de_faixa = mk("XRB3", "Custo 1 Fora de Faixa", cost=1, color="Black")
    me = GameState(leader=mk("XLDR", "Lider", card_type="LEADER"), turn=4, don_available=3)
    me.field_chars = [rebecca]
    me.trash = [rebecca_no_trash, alvo_barato, fora_de_faixa]
    opp = GameState(leader=mk("XOPPR", "Lider Opp", card_type="LEADER"), turn=4)
    EffectExecutor(me, opp).execute(rebecca, "on_play")
    check("Recuperou o alvo dentro da faixa 3-7 (nao a copia de Rebecca no trash)",
          alvo_barato not in me.trash and rebecca_no_trash in me.trash)
    check("Alvo fora da faixa (custo 1) permanece no trash", fora_de_faixa in me.trash)
    check("Personagem recuperado foi jogado de verdade, ja restado",
          alvo_barato in me.field_chars and alvo_barato not in me.hand and alvo_barato.rested)


def test_birdcage_trava_refresh_simetrica_cost_lte() -> None:
    # Achado 15/07 -- OP05-040 Birdcage (Stage): "If your Leader is
    # [Donquixote Doflamingo], all Characters with a cost of 5 or less do
    # not become active in your AND your opponent's Refresh Phases."
    # Antes, essa clausula inteira nao existia no parse (so o KO de fim de
    # turno sobrevivia) -- passiva SIMETRICA (afeta os 2 lados) e
    # PERSISTENTE (nao e freeze de 1x), distinta de toda a familia
    # lock_opp_character_refresh/lock_self_character_refresh existente.
    passive = get_card_effects("OP05-040").get("passive", {})
    check("OP05-040 parseia lock_both_character_refresh cost_lte=5",
          any(s.get("action") == "lock_both_character_refresh" and s.get("cost_lte") == 5
              for s in passive.get("steps", [])))
    check("OP05-040 parseia leader_is=donquixote doflamingo",
          passive.get("conditions", {}).get("leader_is") == "donquixote doflamingo")

    leader_dofla = mk("XDOFLA", "Donquixote Doflamingo", card_type="LEADER")
    birdcage = real_card("OP05-040")
    baixo_custo = mk("XBC1", "Baixo Custo", cost=4)
    alto_custo = mk("XBC2", "Alto Custo", cost=8)
    baixo_custo.rested = True
    alto_custo.rested = True
    me = GameState(leader=leader_dofla, turn=3)
    me.field_stage = birdcage
    me.field_chars = [baixo_custo, alto_custo]
    opp_baixo = mk("XBC3", "Opp Baixo Custo", cost=3)
    opp_baixo.rested = True
    opp = GameState(leader=mk("XOPPDF", "Lider Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [opp_baixo]

    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    match.refresh_phase(me, opp)
    check("Cost<=5 do DONO da Birdcage continua rested apos o proprio refresh",
          baixo_custo.rested)
    check("Cost>5 do dono da Birdcage ativa normalmente", not alto_custo.rested)

    match.refresh_phase(opp, me)
    check("Cost<=5 do OPONENTE da Birdcage tambem continua rested (trava simetrica)",
          opp_baixo.rested)


def test_zehahahahaha_segunda_clausula_dano_direto() -> None:
    # Achado 15/07 -- OP16-116 Zehahahahaha: "Then, add up to 1 card from
    # the top of your opponent's Life cards to the owner's hand." A vida
    # SEMPRE pertence ao proprio dono, entao "to the owner's hand" e so um
    # fraseado alternativo pra "dano direto" (a mesma regra que
    # deal_damage ja executa) -- reaproveitado em vez de criar mecanismo
    # novo. Clausula inteira estava ausente do parse antes.
    steps = get_card_effects("OP16-116").get("main", {}).get("steps", [])
    check("OP16-116 parseia deal_damage encadeado apos o play_card",
          any(s.get("action") == "deal_damage" and s.get("target") == "opponent" for s in steps))

    teach_card = mk("MDT", "Marshall.D.Teach", cost=3)
    zeha = real_card("OP16-116")
    me = GameState(leader=mk("XZLD", "Lider", card_type="LEADER"), turn=4, don_available=10)
    me.field_chars = [zeha]
    me.hand = [teach_card]
    opp = GameState(leader=mk("XZOPPLD", "Lider Opp", card_type="LEADER"), turn=4)
    opp.life = [mk(f"OL{i}", f"Vida {i}") for i in range(3)]
    topo_vida = opp.life[-1]
    EffectExecutor(me, opp).execute(zeha, "main")
    check("Teach foi jogado do deck de verdade", teach_card in me.field_chars and teach_card not in me.hand)
    check("Vida do topo do oponente foi pra mao dele (dano direto)",
          topo_vida in opp.hand and len(opp.life) == 2)


def test_shiryu_add_from_trash_to_life_com_filtro() -> None:
    # Achado 15/07 -- OP16-108 Shiryu: "[On Play] You may trash 1 card
    # from your hand: Add up to 1 {Blackbeard Pirates} type card with a
    # cost of 6 or less from your trash to the top of your Life cards
    # face-up." O bloco on_play inteiro estava ausente (so o [Trigger]
    # sobrevivia) por causa de uma exclusao genérica demais em
    # `parse_life`: qualquer match de "add ... to life" contendo a
    # palavra 'trash' era descartado, mesmo quando 'trash' e a FONTE
    # legitima (source_from ja suportava 'from your trash' -> 'trash',
    # so nunca chegava a ser usado por essa carta).
    entry = get_card_effects("OP16-108").get("on_play", {})
    check("OP16-108 parseia custo opcional trash_from_hand=1",
          any(c.get("type") == "trash_from_hand" and c.get("count") == 1
              for c in entry.get("costs", [])))
    steps = entry.get("steps", [])
    check("OP16-108 parseia gain_life com source=trash, filtro de tipo e custo",
          steps and steps[0].get("action") == "gain_life" and steps[0].get("source") == "trash"
          and steps[0].get("filter_type") == "blackbeard pirates" and steps[0].get("cost_lte") == 6
          and steps[0].get("face") == "up")

    shiryu = real_card("OP16-108")
    alvo_certo = mk("XSH1", "Alvo BB Custo 5", cost=5, sub_types="Blackbeard Pirates")
    alvo_caro = mk("XSH2", "Alvo BB Custo 8", cost=8, sub_types="Blackbeard Pirates")
    alvo_tipo_errado = mk("XSH3", "Alvo Tipo Errado", cost=2, sub_types="Straw Hat Crew")
    me = GameState(leader=mk("XSHLD", "Lider", card_type="LEADER"), turn=4, don_available=3)
    me.field_chars = [shiryu]
    me.trash = [alvo_caro, alvo_tipo_errado, alvo_certo]
    opp = GameState(leader=mk("XSHOPP", "Lider Opp", card_type="LEADER"), turn=4)
    # Testa o step gain_life diretamente (bypassa o julgamento de "vale a
    # pena pagar o custo opcional?" de _worth_paying_optional_costs, que e
    # uma decisao estrategica separada ja coberta em outros testes -- aqui
    # o alvo e so provar que o mecanismo fonte=trash+filtros funciona).
    EffectExecutor(me, opp)._execute_step(steps[0], shiryu)
    check("Alvo dentro do filtro (tipo+custo) foi pra vida face-up",
          alvo_certo in me.life and alvo_certo.life_face_up)
    check("Alvo caro (custo>6) e alvo de tipo errado continuam no trash",
          alvo_caro in me.trash and alvo_tipo_errado in me.trash)


def test_character_para_life_do_dono_com_filtros() -> None:
    expected = {
        "OP03-123": ("on_play", "any", 8),
        "OP06-103": ("when_attacking", "own", None),
        "OP06-107": ("on_play", "own", None),
        "OP11-116": ("main", "any", 6),
        "OP12-117": ("main", "any", 9),
        "P-085": ("on_play", "opponent", 4),
        "ST09-015": ("counter", "opponent", 3),
    }
    for code, (trigger, target, cost_lte) in expected.items():
        step = next(s for s in get_card_effects(code)[trigger]["steps"]
                    if s.get("action") == "character_to_owner_life")
        check(f"{code} preserva campo->Life do dono, alvo e custo",
              step.get("target") == target
              and step.get("dest") == "life_top_or_bottom"
              and step.get("cost_lte") == cost_lte)

    kawa = next(s for s in get_card_effects("OP06-103")["when_attacking"]["steps"]
                if s.get("action") == "character_to_owner_life")
    momo = next(s for s in get_card_effects("OP06-107")["on_play"]["steps"]
                if s.get("action") == "character_to_owner_life")
    check("Kawamatsu preserva power exato 0", kawa.get("power_eq") == 0)
    check("Momonosuke preserva tipo Wano e exclusao do proprio nome",
          momo.get("filter_type") == "land of wano"
          and momo.get("exclude") == "kouzuki momonosuke")

    slam = real_card("OP12-117")
    elegivel = mk("XSL8", "Alvo custo 8", cost=8)
    caro = mk("XSL10", "Alvo custo 10", cost=10)
    me = GameState(leader=mk("XSLL", "Lider", card_type="LEADER",
                             sub_types="Supernovas"),
                   hand=[slam], don_available=5)
    opp = GameState(leader=mk("XSLO", "Opp", card_type="LEADER"),
                    field_chars=[elegivel, caro])
    EffectExecutor(me, opp).execute(slam, "main")
    check("Slam Gibson move somente Character custo 9- para a Life do dono",
          elegivel in opp.life and elegivel not in opp.field_chars
          and caro in opp.field_chars and elegivel not in opp.hand)
    check("Slam Gibson coloca a carta face-down", not elegivel.life_face_up)


def test_liberation_condicao_relativa_ko_duplo_e_trigger_1_de_cada() -> None:
    # Achado 15/07 -- OP10-098 Liberation: "[Main] If the number of your
    # Characters is at least 2 less than the number of your opponent's
    # Characters, K.O. up to 1 of your opponent's Characters with a base
    # cost of 6 or less and up to 1 of your opponent's Characters with a
    # base cost of 4 or less. [Trigger] Negate the effect of up to 1 of
    # EACH of your opponent's Leader and Character cards during this
    # turn." 3 bugs: (1) condicao de comparacao RELATIVA entre boards
    # nunca existia (so contra numero fixo); (2) 2a clausula de KO (custo
    # <=4) nunca era capturada -- o "and up to N..." sem repetir o verbo
    # K.O. nao batia em nenhum regex; (3) [Trigger] inteiro ausente (1 de
    # CADA tipo, nao uma escolha entre um ou outro).
    main_entry = get_card_effects("OP10-098").get("main", {})
    check("OP10-098 parseia condicao chars_fewer_than_opp_by_gte=2",
          main_entry.get("conditions", {}).get("chars_fewer_than_opp_by_gte") == 2)
    ko_steps = main_entry.get("steps", [])
    check("OP10-098 parseia os 2 alvos de KO (custo<=6 e custo<=4)",
          any(s.get("cost_lte") == 6 for s in ko_steps) and any(s.get("cost_lte") == 4 for s in ko_steps))
    trig_steps = get_card_effects("OP10-098").get("trigger", {}).get("steps", [])
    check("OP10-098 parseia negate_effect de 1 Leader E 1 Character (nao escolha)",
          any(s.get("target") == "opp_leader" for s in trig_steps)
          and any(s.get("target") == "opp_character" for s in trig_steps))

    liberation = real_card("OP10-098")
    me = GameState(leader=mk("XLIB", "Lider", card_type="LEADER"), turn=4, don_available=3)
    me.field_chars = [liberation]
    opp = GameState(leader=mk("XLIBOPP", "Lider Opp", card_type="LEADER"), turn=4)
    caro = mk("XLB1", "Alvo Custo 6", cost=6)
    barato = mk("XLB2", "Alvo Custo 4", cost=4)
    muito_caro = mk("XLB3", "Alvo Custo 8", cost=8)
    opp.field_chars = [caro, barato, muito_caro]  # oponente com 3, eu com 1: diferenca=2, condicao bate
    EffectExecutor(me, opp)._execute_step(ko_steps[0], liberation)
    EffectExecutor(me, opp)._execute_step(ko_steps[1], liberation)
    check("KOed o alvo custo<=6 e o alvo custo<=4, poupou o custo 8",
          caro not in opp.field_chars and barato not in opp.field_chars and muito_caro in opp.field_chars)


def test_krieg_just_played_e_debuff_escalado_por_don() -> None:
    # Achado 15/07 -- OP15-008 Krieg [Activate: Main]: "If this Character
    # was played on this turn, give all of your opponent's Characters
    # -1000 power during this turn for every DON!! card given to that
    # Character." 2 bugs: (1) condicao 'was played this turn' nunca
    # existia (disparava sempre, mesmo turnos depois); (2) o debuff era
    # um -1000 FIXO pra todos, ignorando que deveria escalar pelo proprio
    # don_attached de CADA alvo (-1000 * N, individual por character).
    entry = get_card_effects("OP15-008").get("activate_main", {})
    check("OP15-008 parseia condicao just_played=True",
          entry.get("conditions", {}).get("just_played") is True)
    step = entry.get("steps", [{}])[0]
    check("OP15-008 parseia debuff_power com per_don_attached=True",
          step.get("action") == "debuff_power" and step.get("per_don_attached") is True
          and step.get("amount") == 1000)

    krieg = real_card("OP15-008")
    krieg.just_played = True
    me = GameState(leader=mk("XKRLD", "Lider", card_type="LEADER"), turn=4, don_available=5)
    me.field_chars = [krieg]
    opp = GameState(leader=mk("XKROPP", "Lider Opp", card_type="LEADER"), turn=4)
    com_2_don = mk("XKR1", "Alvo 2 DON", power=8000)
    com_2_don.don_attached = 2
    com_1_don = mk("XKR2", "Alvo 1 DON", power=8000)
    com_1_don.don_attached = 1
    sem_don = mk("XKR3", "Alvo Sem DON", power=8000)
    opp.field_chars = [com_2_don, com_1_don, sem_don]
    EffectExecutor(me, opp)._execute_step(step, krieg)
    check("Alvo com 2 DON leva -2000 power (escalado)", com_2_don.power_buff == -2000)
    check("Alvo com 1 DON leva -1000 power", com_1_don.power_buff == -1000)
    check("Alvo sem DON nao leva debuff nenhum", sem_don.power_buff == 0)


def test_condicao_any_don_cards_given() -> None:
    # Familia OP13-061/062/063/066/076/077: "If you have any DON!! cards
    # given" olha DON anexado as proprias cartas, nao DON na cost area.
    entry = get_card_effects("OP13-061").get("on_play", {})
    check("OP13-061 parseia has_don_attached=True",
          entry.get("conditions", {}).get("has_don_attached") is True)

    source = real_card("OP13-061")
    me = GameState(leader=mk("XDONL", "Lider", card_type="LEADER"),
                   don_available=10, don_rested=0)
    opp = GameState(leader=mk("XDONO", "Lider Opp", card_type="LEADER"))
    executor = EffectExecutor(me, opp)
    check("DON apenas na cost area nao satisfaz any DON given",
          executor._check_conditions(entry.get("conditions", {}), source) is False)

    me.leader.don_attached = 1
    check("DON anexado ao Leader satisfaz any DON given",
          executor._check_conditions(entry.get("conditions", {}), source) is True)

    me.leader.don_attached = 0
    corpo = mk("XDONC", "Corpo com DON")
    corpo.don_attached = 1
    me.field_chars = [corpo]
    check("DON anexado a Character satisfaz any DON given",
          executor._check_conditions(entry.get("conditions", {}), source) is True)


def test_opp_life_condition_after_and() -> None:
    # ST28-003/OP14-108 encadeiam 2 requisitos com "and your opponent has";
    # o parser antigo so reconhecia a variante iniciada por "if".
    kin = get_card_effects("ST28-003").get("trigger", {})
    check("ST28-003 preserva leader_type e opp_life_lte=3",
          kin.get("conditions", {}).get("leader_type") == "land of wano"
          and kin.get("conditions", {}).get("opp_life_lte") == 3)

    rayleigh = get_card_effects("OP14-108").get("on_play", {})
    check("OP14-108 preserva leader_multicolor e opp_life_lte=3",
          rayleigh.get("conditions", {}).get("leader_multicolor") is True
          and rayleigh.get("conditions", {}).get("opp_life_lte") == 3)

    caribou = get_card_effects("OP10-104").get("passive", {})
    check("OP10-104 preserva leader_type e opp_life_gte=3",
          caribou.get("conditions", {}).get("leader_type") == "supernovas"
          and caribou.get("conditions", {}).get("opp_life_gte") == 3)

    doji = get_card_effects("ST28-001").get("on_play", {})
    check("ST28-001 preserva leader_type e opp_life_gte=3",
          doji.get("conditions", {}).get("leader_type") == "land of wano"
          and doji.get("conditions", {}).get("opp_life_gte") == 3)

    source = real_card("ST28-003")
    me = GameState(leader=mk("XLIFE", "Lider", card_type="LEADER",
                             sub_types="Land of Wano"))
    opp = GameState(leader=mk("XLIFEO", "Lider Opp", card_type="LEADER"))
    opp.life = [mk(f"XL{i}", "Life") for i in range(4)]
    executor = EffectExecutor(me, opp)
    check("ST28-003 NAO ativa com oponente acima de 3 vidas",
          executor._check_conditions(kin.get("conditions", {}), source) is False)
    opp.life.pop()
    check("ST28-003 ativa com tipo correto e oponente em 3 vidas",
          executor._check_conditions(kin.get("conditions", {}), source) is True)


def test_hina_on_block_lock_during_this_turn() -> None:
    # OP02-110 era a unica carta [On Block] sem entry: a variante indireta
    # "Select... The selected Character cannot attack during this turn"
    # aceitava apenas duracao iniciada por "until".
    entry = get_card_effects("OP02-110").get("on_block", {})
    step = entry.get("steps", [{}])[0]
    check("OP02-110 parseia On Block como trava de ataque cost<=6",
          step.get("action") == "lock_opp_character_attack"
          and step.get("count") == 1 and step.get("cost_lte") == 6
          and step.get("duration") == "until_opp_turn_end")

    hina = real_card("OP02-110")
    me = GameState(leader=mk("XHINAL", "Lider", card_type="LEADER"))
    opp = GameState(leader=mk("XHINAO", "Lider Opp", card_type="LEADER"))
    elegivel = mk("XHINA1", "Alvo custo 6", cost=6, power=7000)
    caro = mk("XHINA2", "Alvo custo 7", cost=7, power=9000)
    opp.field_chars = [elegivel, caro]
    EffectExecutor(me, opp)._execute_step(step, hina)
    check("Hina trava um alvo elegivel ate o fim do turno do oponente",
          elegivel.cannot_attack_until == "opp_turn_end")
    check("Hina nao trava Character acima de custo 6",
          caro.cannot_attack_until == "")


def test_overheat_counter_buff_e_bounce_active_only() -> None:
    # Achado 16/07 -- OP01-086 Overheat [Counter]: "up to 1 of your Leader
    # or Character cards gains +4000 power during this battle. Then,
    # return up to 1 ACTIVE Character with a cost of 3 or less to the
    # owner's hand." O bounce inteiro sumia porque o parser generico de
    # bounce ("return up to N Character(s) with a cost of X or less")
    # exigia "Character(s)" logo apos a contagem -- a palavra "active" no
    # meio quebrava o match. Alvo agora respeita active_only (novo filtro
    # em bounce, ja suportado por eligible_cards mas nunca repassado).
    steps = get_card_effects("OP01-086").get("counter", {}).get("steps", [])
    check("OP01-086 parseia bounce active_only cost<=3",
          any(s.get("action") == "bounce" and s.get("active_only") is True
              and s.get("cost_lte") == 3 for s in steps))
    check("OP01-086 mantem o buff +4000 do proprio lider/character",
          any(s.get("action") == "buff_power" and s.get("amount") == 4000 for s in steps))

    overheat = real_card("OP01-086")
    me = GameState(leader=mk("XOHL", "Lider", card_type="LEADER"))
    opp = GameState(leader=mk("XOHOPP", "Lider Opp", card_type="LEADER"))
    ativo_barato = mk("XOH1", "Ativo Custo 3", cost=3)
    ativo_caro = mk("XOH2", "Ativo Custo 5", cost=5)
    restado_barato = mk("XOH3", "Restado Custo 2", cost=2)
    restado_barato.rested = True
    opp.field_chars = [ativo_barato, ativo_caro, restado_barato]
    bounce_step = next(s for s in steps if s.get("action") == "bounce")
    EffectExecutor(me, opp)._execute_step(bounce_step, overheat)
    check("Bounced o alvo ATIVO dentro do custo (nao o restado, nao o caro)",
          ativo_barato in opp.hand and ativo_caro in opp.field_chars
          and restado_barato in opp.field_chars)

    # Achado 16/07 -- o [Trigger] SEPARADO da mesma carta ("Return up to 1
    # CARD with a cost of 4 or less to the owner's hand") tambem sumia:
    # usa "card" em vez de "Character" como substantivo, e o regex generico
    # de bounce so aceitava "character(s)". Unica carta no banco com essa
    # variante de palavra.
    trigger_steps = get_card_effects("OP01-086").get("trigger", {}).get("steps", [])
    check("OP01-086 parseia bounce do [Trigger] (substantivo 'card', cost<=4)",
          any(s.get("action") == "bounce" and s.get("cost_lte") == 4
              and not s.get("active_only") for s in trigger_steps))
    opp2 = GameState(leader=mk("XOHOPP2", "Lider Opp", card_type="LEADER"))
    alvo_trigger = mk("XOH4", "Alvo Trigger Custo 4", cost=4)
    caro_trigger = mk("XOH5", "Alvo Trigger Custo 5", cost=5)
    opp2.field_chars = [alvo_trigger, caro_trigger]
    trigger_bounce_step = trigger_steps[0]
    EffectExecutor(me, opp2)._execute_step(trigger_bounce_step, overheat)
    check("Trigger fez bounce do alvo custo<=4, poupou o custo 5",
          alvo_trigger in opp2.hand and caro_trigger in opp2.field_chars)


def test_germa66_power_range_e_mesmo_nome_do_trashado() -> None:
    # Achado 16/07 -- EB02-039 GERMA 66: "play up to 1 Character card with
    # 5000 to 7000 power AND THE SAME CARD NAME AS THE TRASHED CARD from
    # your trash." Bug grave: o numero "7000" (2o da faixa) virava um
    # buff_power FANTASMA target=self na propria fonte, porque nenhum
    # guard reconhecia "N to M power" como filtro de selecao (so "N power
    # or less/or more" era filtrado). play_from_trash tambem nunca sabia
    # filtrar por faixa de power nem por "mesmo nome do que foi trashado
    # como custo" (mecanica nova: self._last_trashed_names, setada em
    # _pay_costs, consumida por same_name_as_trashed).
    steps = get_card_effects("EB02-039").get("main", {}).get("steps", [])
    check("EB02-039 NAO tem mais o buff_power fantasma",
          not any(s.get("action") == "buff_power" for s in steps))
    check("EB02-039 parseia play_from_trash com faixa 5000-7000 e same_name_as_trashed",
          any(s.get("action") == "play_from_trash" and s.get("power_gte") == 5000
              and s.get("power_lte") == 7000 and s.get("same_name_as_trashed") is True
              for s in steps))

    germa = real_card("EB02-039")
    me = GameState(leader=mk("XGMLD", "Lider", card_type="LEADER"), turn=4, don_available=0)
    me.field_chars = [germa]
    homonimo_na_faixa = mk("XGM2", "Sanji GERMA", cost=5, power=6000, sub_types="GERMA 66")
    outro_na_faixa = mk("XGM3", "Ichiji GERMA", cost=5, power=6000, sub_types="GERMA 66")
    fora_da_faixa = mk("XGM4", "Sanji GERMA", cost=5, power=3000, sub_types="GERMA 66")
    me.trash = [homonimo_na_faixa, outro_na_faixa, fora_da_faixa]
    opp = GameState(leader=mk("XGMOPP", "Lider Opp", card_type="LEADER"), turn=4)
    # Testa o step direto (bypassa _worth_paying_optional_costs, que exige
    # mao com 2+ cartas -- decisao estrategica separada, ja coberta em
    # outros testes; aqui o alvo e validar so o mecanismo de faixa+nome).
    ee = EffectExecutor(me, opp)
    ee._last_trashed_names = ["Sanji GERMA"]
    ee._execute_step(steps[0], germa)
    check("So o homonimo dentro da faixa de power foi jogado do trash",
          homonimo_na_faixa in me.field_chars
          and outro_na_faixa in me.trash and fora_da_faixa in me.trash)


def test_trash_own_character_custo_novo_e_avaliacao_por_campo() -> None:
    # Achado 16/07 -- 5 cartas (OP06-015, OP13-053, OP16-008, EB04-048,
    # OP07-085) tinham "you may trash N of your Characters [filtro]:" sem
    # NENHUM "from your hand" no texto, mas caiam no regex generico de
    # trash_from_hand por engano (so exigia a palavra "character" aparecer
    # em algum lugar). Sacrificio de CAMPO virava descarte de MAO. Novo
    # tipo de custo trash_own_character (distinto de ko_own_character --
    # nao dispara [On K.O.], regra K.O. != Trash -- e de trash_from_hand,
    # fonte errada).
    check("OP16-008 parseia trash_own_character com power_eq=10000 (base power)",
          get_card_effects("OP16-008").get("on_play", {}).get("costs", [{}])[0]
          == {"type": "trash_own_character", "count": 1, "power_eq": 10000})
    check("OP13-053 parseia trash_own_character com filter_type",
          get_card_effects("OP13-053").get("when_attacking", {}).get("costs", [{}])[0].get("filter_type")
          == "whitebeard pirates")
    check("OP06-015 parseia trash_own_character com power_gte=6000",
          get_card_effects("OP06-015").get("activate_main", {}).get("costs", [{}])[0].get("power_gte") == 6000)
    check("EB04-048 e OP07-085 parseiam trash_own_character sem filtro (custo bruto)",
          get_card_effects("EB04-048").get("on_play", {}).get("costs", [{}])[0].get("type") == "trash_own_character"
          and get_card_effects("OP07-085").get("on_play", {}).get("costs", [{}])[0].get("type") == "trash_own_character")

    # Achado adicional (mesma causa raiz): _worth_paying_optional_costs
    # SEMPRE avaliava esses custos pelo tamanho/valor da MAO (recurso
    # errado -- o custo nunca toca a mao). Prova com mao VAZIA: o custo so
    # deve ser pago se houver alvo elegivel BARATO no campo, nunca por
    # causa da mao.
    op13053 = real_card("OP13-053")
    fraco_whitebeard = mk("XWB1", "Fraco WB", power=0, sub_types="Whitebeard Pirates")
    me = GameState(leader=mk("XWBLD", "Lider", card_type="LEADER"), turn=4, don_available=3)
    me.field_chars = [op13053, fraco_whitebeard]
    me.hand = []  # mao vazia -- se o custo fosse julgado pela mao, seria sempre recusado
    me.deck = [mk("XWBDECK", "Topo do Deck")]
    opp = GameState(leader=mk("XWBOPP", "Lider Opp", card_type="LEADER"), turn=4)
    log = EffectExecutor(me, opp).execute(op13053, "when_attacking")
    check("Custo de campo foi pago mesmo com mao vazia (avaliacao correta, nao mais pela mao)",
          fraco_whitebeard in me.trash and fraco_whitebeard not in me.field_chars)
    check("Efeito pago executou de verdade (draw + gain_banish)",
          any("comprou" in x for x in log) and op13053.has_banish)

    # Sem alvo elegivel no campo (nenhum Whitebeard Pirates alem da propria
    # fonte, que e excluida): custo nao deve ser pago, efeito nao dispara.
    op13053_b = real_card("OP13-053")
    nao_whitebeard = mk("XNWB", "Nao WB", power=0, sub_types="Straw Hat Crew")
    me2 = GameState(leader=mk("XWBLD2", "Lider", card_type="LEADER"), turn=4, don_available=3)
    me2.field_chars = [op13053_b, nao_whitebeard]
    me2.hand = []
    opp2 = GameState(leader=mk("XWBOPP2", "Lider Opp", card_type="LEADER"), turn=4)
    log2 = EffectExecutor(me2, opp2).execute(op13053_b, "when_attacking")
    check("Sem alvo elegivel no campo, custo NAO e pago e efeito nao dispara",
          not log2 and nao_whitebeard in me2.field_chars)


def test_bounce_por_power_eq_base_power() -> None:
    # Achado 16/07 -- variante de bounce por PODER ("return up to N
    # Character(s) with N base power [or more/or less] to the owner's
    # hand", ex: EB03-025/EB03-027/OP14-058). O parser ja gravava
    # power_eq/power_lte certo no JSON, mas o executor de bounce so
    # repassava power_lte pra eligible_cards -- power_eq (poder EXATO)
    # nunca era aplicado, entao qualquer personagem do oponente era
    # bounced, ignorando o filtro por completo.
    steps = get_card_effects("EB03-027").get("on_play", {}).get("steps", [])
    check("EB03-027 parseia bounce power_eq=7000",
          steps and steps[0].get("action") == "bounce" and steps[0].get("power_eq") == 7000)

    fonte = real_card("EB03-027")
    me = GameState(leader=mk("XBPLD", "Lider", card_type="LEADER"))
    opp = GameState(leader=mk("XBPOPP", "Lider Opp", card_type="LEADER"))
    alvo_exato = mk("XBP1", "Alvo 7000", power=7000)
    alvo_diferente = mk("XBP2", "Alvo 8000", power=8000)
    opp.field_chars = [alvo_exato, alvo_diferente]
    EffectExecutor(me, opp)._execute_step(steps[0], fonte)
    check("So o alvo com power EXATO 7000 foi bounced (nao o de 8000)",
          alvo_exato in opp.hand and alvo_diferente in opp.field_chars)


def test_power_of_n_ordem_invertida_transversal() -> None:
    # Achado 16/07 -- correcao de metodologia do usuario: "power of N"
    # (ordem invertida, numero DEPOIS de "power", com "of") nao e bug de
    # 1 mecanismo so -- vaza em QUALQUER lugar que filtra por power. Todo
    # regex existente esperava "N power"/"N base power" (numero ANTES).
    # 5 cartas reais, 4 mecanismos: ko (OP09-015/OP14-064), bounce
    # (OP13-062), rest_opp_character (OP14-062), condicao de imunidade
    # (OP06-012, variante extra "Leader or Character").
    ko_step = get_card_effects("OP09-015").get("on_ko", {}).get("steps", [{}])[0]
    check("OP09-015 (ko) parseia power_lte=6000 via 'power of N'", ko_step.get("power_lte") == 6000)

    ko0_steps = get_card_effects("OP14-064").get("on_ko", {}).get("steps", [])
    check("OP14-064 (ko) parseia power_lte=0 via 'power of 0' sem qualificador",
          any(s.get("action") == "ko" and s.get("power_lte") == 0 for s in ko0_steps))

    bounce_step = get_card_effects("OP13-062").get("when_attacking", {}).get("steps", [{}])[0]
    check("OP13-062 (bounce) parseia power_lte=3000 via 'power of N'", bounce_step.get("power_lte") == 3000)

    rest_step = get_card_effects("OP14-062").get("on_ko", {}).get("steps", [{}])[0]
    check("OP14-062 (rest_opp_character) parseia power_lte=6000 via 'power of N'",
          rest_step.get("action") == "rest_opp_character" and rest_step.get("power_lte") == 6000)

    imm_conds = get_card_effects("OP06-012").get("passive", {}).get("conditions", {})
    check("OP06-012 (condicao de imunidade) parseia opp_leader_or_char_power_gte=6000",
          imm_conds.get("opp_leader_or_char_power_gte") == 6000)

    # Execucao real: a condicao de imunidade so vale se o LIDER (nao so
    # Character) do oponente tiver power>=6000.
    op06012 = real_card("OP06-012")
    me = GameState(leader=mk("XPWLD", "Lider", card_type="LEADER"))
    me.field_chars = [op06012]
    opp_forte = GameState(leader=mk("XPWOPPFORTE", "Lider Forte", card_type="LEADER", power=6000))
    check("Imune quando o LIDER do oponente tem power>=6000 (nao so Character)",
          is_immune(op06012, "ko", me, opp_forte, source_is_opp=True))
    opp_fraco = GameState(leader=mk("XPWOPPFRACO", "Lider Fraco", card_type="LEADER", power=5000))
    check("NAO imune quando nem lider nem nenhum Character do oponente bate 6000",
          not is_immune(op06012, "ko", me, opp_fraco, source_is_opp=True))

    # Achado irmao (mesma rodada): OP10-079 tem um typo oficial "a cost 5
    # or less" (sem "of") -- tolerancia adicionada no mesmo regex de ko.
    ko_typo_step = get_card_effects("OP10-079").get("main", {}).get("steps", [{}])[0]
    check("OP10-079 tolera typo 'cost 5' sem 'of' -> cost_lte=5", ko_typo_step.get("cost_lte") == 5)


def test_place_bottom_deck_dois_alvos_ordem_agnostica() -> None:
    # Achado 16/07 -- EB03-021: "Place up to 1 of your opponent's
    # Characters with 4000 base power or less AND up to 1 Character with
    # a base cost of 3 or less at the bottom of the owner's deck."
    # parse_place_bottom foi reescrita pra ser ORDEM-AGNOSTICA (extrai
    # cost/power de cada clausula independente, nao 2 grupos sequenciais
    # na mesma regex) e reconhecer QUALQUER numero de alvos encadeados
    # via "and up to N Character(s)".
    steps = get_card_effects("EB03-021").get("on_play", {}).get("steps", [])
    check("EB03-021 parseia os 2 alvos encadeados (power_lte E cost_lte)",
          any(s.get("power_lte") == 4000 for s in steps)
          and any(s.get("cost_lte") == 3 for s in steps))

    fonte = real_card("EB03-021")
    me = GameState(leader=mk("XPB1LD", "Lider", card_type="LEADER"), turn=4, don_available=3)
    me.field_chars = [fonte]
    me.hand = [mk("XPB1H", "Carta pra Trashar", cost=1, power=1000)]
    opp = GameState(leader=mk("XPB1OPP", "Lider Opp", card_type="LEADER"), turn=4)
    alvo_power = mk("XPB1A", "Alvo Power 3000", cost=8, power=3000)
    alvo_cost = mk("XPB1B", "Alvo Cost 2", cost=2, power=9000)
    fora_dos_2 = mk("XPB1C", "Fora dos 2", cost=8, power=9000)
    opp.field_chars = [alvo_power, alvo_cost, fora_dos_2]
    for s in steps:
        EffectExecutor(me, opp)._execute_step(s, fonte)
    check("Alvo pelo filtro de POWER foi mandado pro fundo do deck",
          alvo_power not in opp.field_chars)
    check("Alvo pelo filtro de CUSTO foi mandado pro fundo do deck",
          alvo_cost not in opp.field_chars)
    check("Alvo fora dos 2 filtros permanece no campo",
          fora_dos_2 in opp.field_chars)


def test_place_opp_char_to_opp_life_variantes_de_fraseado() -> None:
    # Achado 16/07 -- EB01-053/OP05-096/OP09-101 usam "Place" (nao "Add")
    # e "your opponent's"/"their" Life cards (nao "the owner's"), alem de
    # OP09-101 omitir "up to". As 3 caiam por engano em
    # place_opp_character_bottom_deck (acao errada: fundo do DECK em vez
    # de vida do oponente) porque o regex antigo desse mecanismo aceitava
    # "bottom of" seguido de QUALQUER coisa, sem exigir "deck".
    step_eb = get_card_effects("EB01-053").get("on_play", {}).get("steps", [{}])[0]
    check("EB01-053 parseia place_opp_char_to_opp_life (nao bottom_deck)",
          step_eb.get("action") == "place_opp_char_to_opp_life" and step_eb.get("cost_lte") == 3)

    step_op09 = get_card_effects("OP09-101").get("on_play", {}).get("steps", [])
    check("OP09-101 (sem 'up to') tambem parseia place_opp_char_to_opp_life",
          any(s.get("action") == "place_opp_char_to_opp_life" and s.get("cost_lte") == 3
              for s in step_op09))

    choice_op05 = get_card_effects("OP05-096").get("main", {}).get("choice", [])
    terceira_opcao = choice_op05[2] if len(choice_op05) > 2 else []
    check("OP05-096 ('their Life cards') tambem parseia place_opp_char_to_opp_life, SEM filter_type vazado",
          any(s.get("action") == "place_opp_char_to_opp_life" and "filter_type" not in s
              for s in terceira_opcao))

    eb01053 = real_card("EB01-053")
    me = GameState(leader=mk("XPOL1LD", "Lider", card_type="LEADER"))
    opp = GameState(leader=mk("XPOL1OPP", "Lider Opp", card_type="LEADER"))
    alvo = mk("XPOL1A", "Alvo Custo 3", cost=3, power=5000)
    opp.field_chars = [alvo]
    EffectExecutor(me, opp)._execute_step(step_eb, eb01053)
    check("Execucao real: alvo saiu do campo e foi pra vida do PROPRIO oponente (face-up)",
          alvo not in opp.field_chars and alvo in opp.life and alvo.life_face_up)


def test_place_own_character_bottom_deck_e_turno_extra() -> None:
    # Achado 16/07 -- OP05-119: "DON!! -10: Place all of your Characters
    # except this Character at the bottom of your deck in any order.
    # Then, take an extra turn after this one." 2 mecanicas novas: (1)
    # place_own_character_bottom_deck (acao existia no codigo mas sem
    # executor nenhum, nunca produzida pelo parser); (2) take_extra_turn,
    # a PRIMEIRA carta do banco com essa mecanica -- exigiu refatorar o
    # loop de simulate()/replay run() de alternancia fixa (turn_num % 2)
    # pra um ponteiro "quem joga agora" que so alterna se
    # extra_turn_pending nao estiver setada.
    entry = get_card_effects("OP05-119").get("on_play", {})
    check("OP05-119 parseia custo DON!! -10 obrigatorio",
          entry.get("costs", [{}])[0] == {"type": "don_minus", "count": 10, "optional": False})
    steps = entry.get("steps", [])
    check("OP05-119 parseia place_own_character_bottom_deck (all, exclude_self) + take_extra_turn",
          any(s.get("action") == "place_own_character_bottom_deck" and s.get("count") == 99
              and s.get("exclude_self") is True for s in steps)
          and any(s.get("action") == "take_extra_turn" for s in steps))

    # Execucao real do place_own: ordem "in any order" deixa de ser
    # arbitraria -- o mais FORTE (maior board_value) fica mais perto do
    # topo do deck (comprado primeiro se o deck chegar la), processado
    # por ULTIMO no loop (cada remove_character_from_field(...,
    # 'deck_bottom') empurra os anteriores mais fundo).
    fonte = real_card("OP05-119")
    me = GameState(leader=mk("XETLD", "Lider", card_type="LEADER"), turn=4)
    fraco = mk("XETF", "Fraco", power=1000)
    forte = mk("XETFT", "Forte", power=9000)
    me.field_chars = [fonte, fraco, forte]
    me.deck = [mk("XETDECK", "Resto do Deck")]
    place_step = next(s for s in steps if s.get("action") == "place_own_character_bottom_deck")
    EffectExecutor(me, GameState(leader=mk("XETOPP", "Opp", card_type="LEADER")))._execute_step(place_step, fonte)
    check("A propria fonte NAO foi movida (exclude_self)", fonte in me.field_chars)
    check("Fraco e Forte foram movidos pro fundo do deck", fraco in me.deck and forte in me.deck)
    check("O mais FORTE fica mais perto do topo (indice maior) que o mais fraco",
          me.deck.index(forte) > me.deck.index(fraco))

    # Execucao real do LOOP de simulate(): deve deixar o MESMO jogador
    # jogar de novo quando extra_turn_pending esta setada apos o turno,
    # em vez de alternar pro oponente -- testado via monkeypatch de
    # play_turn (evita montar uma partida completa so pra pagar DON!! -10
    # de verdade), registrando a sequencia real de jogadores que o loop
    # de simulate() decidiu chamar.
    leader_a = mk("XETLDA", "Lider A", card_type="LEADER")
    leader_b = mk("XETLDB", "Lider B", card_type="LEADER")
    match = OPTCGMatch((leader_a, []), (leader_b, []))
    sequencia = []

    def fake_play_turn(p, opp, verbose=False):
        sequencia.append("A" if p is match.state_a else "B")
        if len(sequencia) == 1:
            p.extra_turn_pending = True   # simula OP05-119 no 1o turno
        if len(sequencia) >= 4:
            return "A"   # encerra a partida pra nao rodar MAX_TURNS*2
        return None

    match.play_turn = fake_play_turn
    match.simulate()
    check("simulate() repete o MESMO jogador logo apos o turno com extra_turn_pending",
          sequencia[0] == sequencia[1])
    check("simulate() volta a alternar normalmente depois do turno extra consumido",
          sequencia[1] != sequencia[2] and sequencia[2] != sequencia[3])


def test_don_attached_total_gte_condicao_nova() -> None:
    # Achado 16/07 -- "If you have a total of N or more given DON!! cards"
    # (limiar NUMERICO, distinto de has_don_attached que so checa >=1)
    # nunca existia -- OP12-015 (buff), OP12-024 (rest_opp_character),
    # OP13-112 (Blocker) disparavam SEMPRE, mesmo sem DON nenhum anexado.
    check("OP12-015 parseia don_attached_total_gte=2",
          get_card_effects("OP12-015").get("passive", {}).get("conditions", {}).get("don_attached_total_gte") == 2)
    check("OP12-024 parseia don_attached_total_gte=3",
          get_card_effects("OP12-024").get("when_attacking", {}).get("conditions", {}).get("don_attached_total_gte") == 3)
    check("OP13-112 parseia don_attached_total_gte=2",
          get_card_effects("OP13-112").get("passive", {}).get("conditions", {}).get("don_attached_total_gte") == 2)

    # Execucao real via os 2 caminhos que consomem a condicao:
    # apply_your_turn_buffs (buff_power self, OP12-015) e
    # apply_conditional_keyword_passives (gain_blocker, OP13-112) --
    # ambos usam _check_conditions, ja corrigido.
    op12015 = real_card("OP12-015")
    me_pouco = GameState(leader=mk("XDT1LD", "Lider", card_type="LEADER"))
    me_pouco.field_chars = [op12015]
    EffectExecutor(me_pouco, GameState(leader=mk("XDT1OPP", "Opp", card_type="LEADER"))).apply_your_turn_buffs()
    check("SEM 2+ DON total anexado, o buff de OP12-015 NAO aplica", op12015.power_buff == 0)

    op12015b = real_card("OP12-015")
    op12015b.don_attached = 2
    me_muito = GameState(leader=mk("XDT2LD", "Lider", card_type="LEADER"))
    me_muito.field_chars = [op12015b]
    EffectExecutor(me_muito, GameState(leader=mk("XDT2OPP", "Opp", card_type="LEADER"))).apply_your_turn_buffs()
    check("COM 2+ DON total anexado (na propria carta), o buff de OP12-015 aplica",
          op12015b.power_buff == 2000)

    op13112 = real_card("OP13-112")
    me_blocker = GameState(leader=mk("XDT3LD", "Lider", card_type="LEADER"))
    me_blocker.leader.don_attached = 2
    me_blocker.field_chars = [op13112]
    apply_conditional_keyword_passives(me_blocker, GameState(leader=mk("XDT3OPP", "Opp", card_type="LEADER")))
    check("COM 2+ DON total anexado NO LIDER (soma lider+campo), OP13-112 ganha Blocker",
          op13112.has_blocker)


def test_activate_event_from_hand_sinonimo_de_play() -> None:
    # Achado 16/07 -- "Activate up to N [Tipo] type Event [with a base
    # cost of X or less] from your hand" e semanticamente identico a
    # play_card (o executor de play_card ja suporta card_type='EVENT'
    # nativamente), so o parser nunca reconhecia "activate" como
    # sinonimo de "play" nesse contexto. 3 cartas: OP12-041, OP15-014
    # (mesma causa da familia "base cost"), e OP15-046 (achada no censo,
    # variante sem filtro de custo).
    check("OP12-041 parseia play_card(card_type=EVENT, filter_type, cost_lte=3)",
          get_card_effects("OP12-041").get("activate_main", {}).get("steps", [{}])[0]
          == {"action": "play_card", "count": 1, "card_type": "EVENT",
              "filter_type": "straw hat crew", "cost_lte": 3})
    check("OP15-014 parseia o mesmo padrao (on_play, filter_type dressrosa)",
          get_card_effects("OP15-014").get("on_play", {}).get("steps", [{}])[0]
          == {"action": "play_card", "count": 1, "card_type": "EVENT",
              "filter_type": "dressrosa", "cost_lte": 3})
    check("OP15-046 (sem filtro de custo) tambem parseia",
          get_card_effects("OP15-046").get("on_play", {}).get("steps", [{}])[0]
          == {"action": "play_card", "count": 1, "card_type": "EVENT", "filter_type": "dressrosa"})

    op15046 = real_card("OP15-046")
    step = get_card_effects("OP15-046")["on_play"]["steps"][0]
    me = GameState(leader=mk("XAELD", "Lider Dressrosa", card_type="LEADER", sub_types="Dressrosa"))
    me.field_chars = [op15046]
    evento = mk("XAEEV", "Evento Dressrosa", cost=2, card_type="EVENT", sub_types="Dressrosa")
    personagem_isca = mk("XAECH", "Personagem Isca", cost=2)
    me.hand = [evento, personagem_isca]
    opp = GameState(leader=mk("XAEOPP", "Lider Opp", card_type="LEADER"))
    EffectExecutor(me, opp)._execute_step(step, op15046)
    check("So o EVENTO foi jogado da mao (nao o Character isca)",
          evento not in me.hand and evento in me.trash and personagem_isca in me.hand)


def test_koala_leader_attack_leader_e_opp_plays_character() -> None:
    # Achado 16/07 -- OP12-081 tem 2 clausulas em prosa, SEM tag formal
    # nenhuma: "When this Leader attacks your opponent's Leader, if you
    # have 2 or more Characters with a cost of 8 or more, draw 1 card."
    # (trigger when_attacking nunca reconhecido sem a tag "[When
    # Attacking]" -- _execute_attack ja dispara esse trigger pro LIDER
    # normalmente, so faltava o parser aceitar a introducao em prosa) e
    # "[Once Per Turn] This effect can be activated when your opponent
    # plays a Character ..., Your opponent adds 1 card from the top of
    # their Life cards to their hand." (aproximado pra opp_turn, MESMA
    # convencao ja usada em OP04-024 pra "when your opponent plays a
    # Character" -- o engine nao rastreia o evento exato "personagem
    # jogado", só o turno do oponente. A condicao OR complexa -- custo
    # base>=8 OU jogado via efeito -- NAO e modelada com precisao,
    # mesma aproximacao documentada do precedente).
    when_att = get_card_effects("OP12-081").get("when_attacking", {})
    check("OP12-081 parseia when_attacking (sem tag) com chars_gte+cost_filter",
          when_att.get("conditions", {}) == {"chars_gte": 2, "chars_gte_cost_filter": 8}
          and any(s.get("action") == "draw" for s in when_att.get("steps", [])))
    opp_turn = get_card_effects("OP12-081").get("opp_turn", {})
    check("OP12-081 parseia a 2a clausula (sem tag) como opp_turn, opp_life_to_hand",
          any(s.get("action") == "opp_life_to_hand" and s.get("count") == 1
              for s in opp_turn.get("steps", [])))

    # Achado irmao (mesma rodada): OP13-108 tinha a mesma clausula de
    # opp_life_to_hand ausente, so que com "from the top of their Life
    # CARDS" (variante de fraseado que o regex antigo nao aceitava).
    check("OP13-108 tambem parseia opp_life_to_hand (variante 'Life cards')",
          any(s.get("action") == "opp_life_to_hand"
              for s in get_card_effects("OP13-108").get("on_play", {}).get("steps", [])))

    koala = real_card("OP12-081")
    me = GameState(leader=koala, turn=4)
    forte1 = mk("XKO1", "Forte 1", cost=8)
    forte2 = mk("XKO2", "Forte 2", cost=9)
    me.field_chars = [forte1, forte2]
    opp = GameState(leader=mk("XKOOPP", "Lider Opp", card_type="LEADER"), turn=4)
    me.deck = [mk("XKODECK", "Topo do Deck")]
    log = EffectExecutor(me, opp).execute(koala, "when_attacking")
    check("Execucao real: com 2+ Characters de custo>=8, o draw dispara",
          any("comprou" in x for x in log))


def test_shirahoshi_turn_life_face_up_substitute_e_no_other_named() -> None:
    # Achado 16/07 -- OP12-102 (Shirahoshi) tinha 3 bugs distintos:
    # (1) "you may turn 1 card from the top of your Life cards face-up
    # instead" nunca era reconhecido como custo de substituicao (cost_lte:6
    # do filtro de alvo tambem sumia); (2) "if you have no other
    # [Shirahoshi] with a base cost of 2" -- condicao inteira ausente do
    # parser (nao so regex, o tipo de condicao nao existia); (3) "all of
    # your "Neptunian" type Characters gain +2000 power" caia no fallback
    # errado target=self por causa do tipo intercalado entre "all of your"
    # e "type character(s)".
    effects = get_card_effects("OP12-102")
    passive = effects.get("passive", {})
    check("OP12-102 passive parseia substitute_removal com custo turn_life_face_up e cost_lte:6",
          any(s.get("action") == "substitute_removal"
              and s.get("cost", {}).get("action") == "turn_life_face_up"
              and s.get("cost_lte") == 6
              for s in passive.get("steps", [])))

    opp_turn = effects.get("opp_turn", {})
    check("OP12-102 opp_turn tem condicao no_other_named (nome+custo) nova",
          opp_turn.get("conditions", {}).get("no_other_named") == "shirahoshi"
          and opp_turn.get("conditions", {}).get("no_other_named_cost_eq") == 2)
    check("OP12-102 opp_turn buffa all_allies com filter_type neptunian (nao mais self)",
          any(s.get("action") == "buff_power" and s.get("target") == "all_allies"
              and s.get("filter_type") == "neptunian"
              for s in opp_turn.get("steps", [])))

    # Execucao real do custo de substituicao: Shirahoshi em campo, outro
    # Character proprio de custo 5 (<=6) seria removido pelo oponente --
    # deve virar 1 carta de vida face-up em vez de ser removido.
    shirahoshi = real_card("OP12-102")
    vitima = mk("XVIT", "Vitima", cost=5)
    me = GameState(leader=mk("XSHLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [shirahoshi, vitima]
    me.life = [mk("XLIFE1", "Vida", cost=0)]
    opp = GameState(leader=mk("XSHOPP", "Lider Opp", card_type="LEADER"), turn=3)
    log = EffectExecutor(me, opp).try_any_substitute(vitima, "removal")
    check("Execucao real: substituicao vira a vida do topo face-up, vitima continua em campo",
          log is not None and me.life[-1].life_face_up
          and vitima in me.field_chars)

    # Execucao real da condicao no_other_named: um aliado Neptunian so deve
    # ganhar +2000 quando NAO ha outra copia de Shirahoshi custo 2 em
    # campo; com a outra copia presente, a condicao falha e o buff nao
    # aplica.
    neptunian = mk("XNEP", "Neptunian Aliado", sub_types="Neptunian", cost=3)
    me2 = GameState(leader=mk("XSHLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [shirahoshi, neptunian]
    EffectExecutor(me2, GameState(leader=mk("XOPP2", "Opp", card_type="LEADER"), turn=3)).execute(shirahoshi, "opp_turn")
    check("Execucao real: SEM outra Shirahoshi custo 2, o Neptunian aliado ganha +2000",
          neptunian.power_buff == 2000)

    outra_shirahoshi = real_card("OP12-102")
    neptunian2 = mk("XNEP2", "Neptunian Aliado 2", sub_types="Neptunian", cost=3)
    me3 = GameState(leader=mk("XSHLDR3", "Lider", card_type="LEADER"), turn=3)
    me3.field_chars = [shirahoshi, outra_shirahoshi, neptunian2]
    EffectExecutor(me3, GameState(leader=mk("XOPP3", "Opp", card_type="LEADER"), turn=3)).execute(shirahoshi, "opp_turn")
    check("Execucao real: COM outra Shirahoshi custo 2 em campo, o buff NAO dispara (no_other_named falha)",
          neptunian2.power_buff == 0)


def test_no_other_named_condicao_transversal() -> None:
    # Busca global (mesma rodada de OP12-102) achou 6 outras cartas com a
    # MESMA condicao "if you have no other [Nome]" nunca implementada:
    # EB01-012, EB02-018, EB04-031, OP07-060, OP08-074, OP15-080. Todas
    # tinham o efeito disparando SEMPRE (condicao descartada silenciosamente).
    check("EB02-018 (Buggy) parseia no_other_named='buggy'",
          get_card_effects("EB02-018").get("on_play", {}).get("conditions", {})
          .get("no_other_named") == "buggy")
    check("OP08-074 (Black Maria) parseia no_other_named='black maria'",
          get_card_effects("OP08-074").get("activate_main", {}).get("conditions", {})
          .get("no_other_named") == "black maria")
    check("EB01-012 (Cavendish) combina leader_type + no_other_named (AND)",
          get_card_effects("EB01-012").get("on_play", {}).get("conditions", {})
          == {"leader_type": "supernovas", "no_other_named": "cavendish"})

    # OP15-080 (Oars): reusa other_char_power_gte (variante de fraseado
    # "[Nome] with N power or more on your field") + no_other_named na
    # MESMA condicao (AND) -- prova que os 2 achados nao colidem.
    conds15080 = get_card_effects("OP15-080").get("passive", {}).get("conditions", {})
    check("OP15-080 combina other_char_power_gte(Gecko Moria) + no_other_named(Oars)",
          conds15080.get("other_char_power_gte") == 10000
          and conds15080.get("other_char_power_gte_names") == ["gecko moria"]
          and conds15080.get("no_other_named") == "oars")

    # Execucao real (Buggy, EB02-018): sozinho em campo -> Double Attack
    # dispara; com outro Buggy em campo -> nao dispara.
    buggy = real_card("EB02-018")
    me = GameState(leader=mk("XBLDR", "Lider", card_type="LEADER"), turn=2)
    me.field_chars = [buggy]
    opp = GameState(leader=mk("XBOPP", "Opp", card_type="LEADER"), turn=2)
    log_sozinho = EffectExecutor(me, opp).execute(buggy, "on_play")
    check("Buggy sozinho em campo: Double Attack dispara (no_other_named satisfeita)",
          any("double" in x.lower() or "gain_double_attack" in x.lower() for x in log_sozinho))

    outro_buggy = real_card("EB02-018")
    me2 = GameState(leader=mk("XBLDR2", "Lider", card_type="LEADER"), turn=2)
    me2.field_chars = [buggy, outro_buggy]
    log_com_outro = EffectExecutor(me2, GameState(leader=mk("XBOPP2", "Opp", card_type="LEADER"), turn=2)).execute(buggy, "on_play")
    check("Buggy com OUTRO Buggy em campo: Double Attack NAO dispara (no_other_named falha)",
          not any("double" in x.lower() or "gain_double_attack" in x.lower() for x in log_com_outro))


def test_all_allies_filter_type_buff_power() -> None:
    # Busca global (mesma rodada de OP12-102) achou mais 6 cartas com "all
    # of your [Tipo] type Characters gain +N power" caindo no fallback
    # errado target=self (o tipo intercalado quebrava o match literal de
    # 'all of your characters'): EB01-024, EB03-041 (+cost_lte sub-filtro),
    # EB03-052, OP04-012 (+exclude_self), OP08-020, OP11-044, ST05-001.
    check("ST05-001 (Shanks) buffa all_allies filter_type=film (nao mais self)",
          any(s.get("action") == "buff_power" and s.get("target") == "all_allies"
              and s.get("filter_type") == "film"
              for s in get_card_effects("ST05-001").get("activate_main", {}).get("steps", [])))
    check("EB03-041 preserva o sub-filtro cost_lte:6 dentro do mesmo buff all_allies",
          any(s.get("action") == "buff_power" and s.get("target") == "all_allies"
              and s.get("filter_type") == "sword" and s.get("cost_lte") == 6
              for s in get_card_effects("EB03-041").get("opp_turn", {}).get("steps", [])))
    check("OP04-012 preserva exclude_self dentro do mesmo buff all_allies",
          any(s.get("action") == "buff_power" and s.get("target") == "all_allies"
              and s.get("filter_type") == "alabasta" and s.get("exclude_self")
              for s in get_card_effects("OP04-012").get("your_turn", {}).get("steps", [])))

    # Execucao real: Shanks (ST05-001) com 2 "FILM" e 1 outro tipo em
    # campo -- so os 2 FILM devem ganhar +2000 power.
    shanks = real_card("ST05-001")
    film1 = mk("XFILM1", "Film 1", sub_types="FILM", cost=3)
    film2 = mk("XFILM2", "Film 2", sub_types="FILM", cost=3)
    outro = mk("XOUTRO", "Outro Tipo", sub_types="East Blue", cost=3)
    me = GameState(leader=shanks, turn=3)
    me.field_chars = [film1, film2, outro]
    me.don_available = 5
    opp = GameState(leader=mk("XSTOPP", "Opp", card_type="LEADER"), turn=3)
    log = EffectExecutor(me, opp).execute(shanks, "activate_main")
    check("Execucao real: so os 2 Characters FILM ganham power, o outro tipo fica intacto",
          film1.power_buff == 2000 and film2.power_buff == 2000 and outro.power_buff == 0)
    check("Execucao real: log confirma o efeito disparou", bool(log))


def test_all_allies_filter_color_e_type_intercalados() -> None:
    # Achado 16/07 (OP14-034 Luffy): variante de Bug 3 com uma COR entre
    # "all of your" e o tipo -- "all of your green {Straw Hat Crew} type
    # Characters with a base cost of 4 or more gain +1000 power". A
    # regex de type_all_m (fix anterior, OP12-102/ST05-001) exigia o
    # tipo logo apos "all of your", entao a cor no meio quebrava o match
    # de novo (mesma raiz: literal rigido demais). Corrigido tolerando
    # uma cor opcional e extraindo filter_color separado de filter_type.
    steps = get_card_effects("OP14-034").get("your_turn", {}).get("steps", [])
    check("OP14-034 buffa all_allies com filter_type+filter_color+cost_gte simultaneos",
          any(s.get("action") == "buff_power" and s.get("target") == "all_allies"
              and s.get("filter_type") == "straw hat crew"
              and s.get("filter_color") == "green"
              and s.get("cost_gte") == 4
              for s in steps))

    # Execucao real: 3 Straw Hat Crew custo>=4 no campo, so 1 delas verde
    # -- so a verde deve ganhar +1000 (cor E tipo E custo, os 3 filtros).
    luffy = real_card("OP14-034")
    verde_alto = mk("XSHV", "Verde Alto Custo", sub_types="Straw Hat Crew", cost=5, color="Green")
    preto_alto = mk("XSHP", "Preto Alto Custo", sub_types="Straw Hat Crew", cost=5, color="Black")
    verde_baixo = mk("XSHVB", "Verde Baixo Custo", sub_types="Straw Hat Crew", cost=2, color="Green")
    me = GameState(leader=luffy, turn=3)
    me.field_chars = [verde_alto, preto_alto, verde_baixo]
    opp = GameState(leader=mk("XLUOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(luffy, "your_turn")
    check("Execucao real: so o Straw Hat Crew VERDE de custo>=4 ganha +1000",
          verde_alto.power_buff == 1000
          and preto_alto.power_buff == 0
          and verde_baixo.power_buff == 0)


def test_lucy_event_activated_cost_gte_this_turn() -> None:
    # Achado 16/07 (OP15-002 Lucy, 3a familia do lote) -- "[Activate: Main]
    # [Once Per Turn] If you have activated an Event with a base cost of 3
    # or more during this turn, draw 1 card." Condicao inteira ausente do
    # parser (nao existia NENHUM rastreamento de "evento ativado neste
    # turno", distinto de events_in_trash_gte que so conta quantidade
    # acumulada sem checar QUANDO nem custo) -- o draw disparava sempre.
    conds = get_card_effects("OP15-002").get("activate_main", {}).get("conditions", {})
    check("OP15-002 activate_main parseia event_activated_cost_gte_this_turn=3",
          conds.get("event_activated_cost_gte_this_turn") == 3)

    lucy = real_card("OP15-002")
    opp = GameState(leader=mk("XLUCYOPP", "Opp", card_type="LEADER"), turn=3)

    # SEM ter ativado nenhum Event neste turno -- draw NAO dispara.
    me1 = GameState(leader=lucy, turn=3)
    log1 = EffectExecutor(me1, opp).execute(lucy, "activate_main")
    check("Execucao real: sem Event ativado neste turno, o draw NAO dispara",
          not any("comprou" in x for x in log1))

    # Com um Event de custo BAIXO (2, abaixo do limiar 3) ativado -- ainda
    # nao dispara.
    me2 = GameState(leader=lucy, turn=3)
    me2.events_activated_costs_this_turn = [2]
    log2 = EffectExecutor(me2, opp).execute(lucy, "activate_main")
    check("Execucao real: Event ativado de custo ABAIXO do limiar, draw NAO dispara",
          not any("comprou" in x for x in log2))

    # Com um Event de custo>=3 ativado neste turno -- dispara.
    me3 = GameState(leader=lucy, turn=3)
    me3.events_activated_costs_this_turn = [4]
    me3.deck = [mk("XLUCYDECK", "Topo do Deck")]
    log3 = EffectExecutor(me3, opp).execute(lucy, "activate_main")
    check("Execucao real: Event ativado de custo>=3 neste turno, draw dispara",
          any("comprou" in x for x in log3))

    # refresh_phase reseta o rastreamento no inicio do proprio turno.
    me4 = GameState(leader=lucy, turn=3, don_deck=10)
    me4.events_activated_costs_this_turn = [5]
    match = object.__new__(OPTCGMatch)
    match.refresh_phase(me4)
    check("refresh_phase reseta events_activated_costs_this_turn no inicio do turno",
          me4.events_activated_costs_this_turn == [])


def test_gains_keyword_and_cost_buff() -> None:
    # Achado 16/07 (ST25-002/ST25-005 e familia) -- "gains [Blocker] and
    # +N cost" nunca reconhecia a metade do custo: a regex de buff_cost
    # exigia o sinal+numero LOGO apos "gains", e aqui vem "[Blocker] and "
    # no meio. 8 cartas reais tinham o +N cost inteiro ausente (so o
    # Blocker sobrevivia). ST27-004 e a variante DINAMICA ("+1 cost for
    # every 4 cards in your trash").
    passive = get_card_effects("ST25-002").get("passive", {})
    check("ST25-002 passive parseia gain_blocker E buff_cost (+1, self, permanent)",
          any(s.get("action") == "gain_blocker" for s in passive.get("steps", []))
          and any(s.get("action") == "buff_cost" and s.get("amount") == 1
                  and s.get("target") == "self" and s.get("duration") == "permanent"
                  for s in passive.get("steps", [])))
    check("ST25-005 (mesma frase exata) tambem parseia os 2 steps",
          any(s.get("action") == "buff_cost" and s.get("amount") == 1
              for s in get_card_effects("ST25-005").get("passive", {}).get("steps", [])))
    check("OP12-089 (custo +4) preserva o amount certo",
          any(s.get("action") == "buff_cost" and s.get("amount") == 4
              for s in get_card_effects("OP12-089").get("passive", {}).get("steps", [])))

    dyn = get_card_effects("ST27-004").get("passive", {}).get("steps", [])
    check("ST27-004 (variante dinamica) parseia buff_cost_per_count (1 a cada 4 no trash)",
          any(s.get("action") == "buff_cost_per_count" and s.get("amount_per") == 1
              and s.get("count_per") == 4 and s.get("source") == "trash"
              for s in dyn))

    # Execucao real: ST25-002 com 2+ Characters proprios de custo>=5 --
    # Blocker E +1 cost (permanente) devem aplicar na propria carta.
    cabaji = real_card("ST25-002")
    aliado1 = mk("XCB1", "Aliado Caro 1", cost=5)
    aliado2 = mk("XCB2", "Aliado Caro 2", cost=6)
    me = GameState(leader=mk("XCBLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [cabaji, aliado1, aliado2]
    opp = GameState(leader=mk("XCBOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(cabaji, "passive")
    # duration='permanent' grava em cost_buff_permanent (campo separado de
    # cost_buff, sobrevive ao reset de fim de turno) -- achado 16/07 em
    # conjunto: cost_buff_permanent NUNCA era resetado no INICIO do turno
    # por apply_your_turn_buffs(), entao cada turno somava de novo o mesmo
    # +N sem limite (bug pre-existente, so agora alcancavel por essas 8
    # cartas). Corrigido: apply_your_turn_buffs() agora zera
    # cost_buff_permanent tambem antes de recalcular (mesmo padrao de
    # power_buff/cost_buff).
    check("Execucao real: Cabaji ganha Blocker E +1 cost (permanente) com 2+ aliados caros",
          cabaji.has_blocker and cabaji.cost_buff_permanent == 1)

    for _ in range(4):
        EffectExecutor(me, opp).apply_your_turn_buffs()
    check("cost_buff_permanent NAO acumula turno apos turno (fica em +1, nao +5)",
          cabaji.cost_buff_permanent == 1)

    # Execucao real da variante dinamica: Whitebeard Pirate ST27-004 com 8
    # cartas no trash (2x o limiar de 4) -- +2 cost (1 * 8//4). Precisa do
    # Leader [Blackbeard Pirates] pra satisfazer a condicao da carta.
    st27 = real_card("ST27-004")
    me2 = GameState(leader=mk("X27LDR", "Lider", card_type="LEADER", sub_types="Blackbeard Pirates"), turn=3)
    me2.field_chars = [st27]
    me2.trash = [mk(f"XTR{i}", f"Trash {i}") for i in range(8)]
    EffectExecutor(me2, GameState(leader=mk("X27OPP", "Opp", card_type="LEADER"), turn=3)).execute(st27, "passive")
    check("Execucao real: ST27-004 com 8 cartas no trash ganha +2 cost (proporcional, variante dinamica NAO permanente)",
          st27.cost_buff == 2)


def test_and_you_have_condicoes_transversais() -> None:
    # Achado 16/07 (mesma investigacao ST25-002/005) -- varias condicoes
    # "if you have X" so reconheciam a ancora literal "if", nunca "and"
    # (quando a condicao vem encadeada depois de OUTRA com "and"). Busca
    # ampla por "and you have" achou 23 ocorrencias; a maioria ja tolerava
    # "and" (life_lte/don_on_field_gte/don_rested_gte, sessoes anteriores),
    # mas hand_lte/hand_gte, has_don_attached e chars_rested_gte nao. A
    # mesma varredura tambem achou 3 condicoes NOVAS (sem implementacao
    # nenhuma antes): no_char_power_gte, has_named_character,
    # own_rested_cards_gte.
    check("EB02-026 (hand_lte apos 'and') parseia hand_lte=5",
          get_card_effects("EB02-026").get("on_play", {}).get("conditions", {})
          .get("hand_lte") == 5)
    check("OP14-059 (hand_lte apos 'and', 'Main' trigger) parseia hand_lte=2",
          get_card_effects("OP14-059").get("main", {}).get("conditions", {})
          .get("hand_lte") == 2)
    check("OP13-072 (has_don_attached apos 'and') parseia has_don_attached",
          get_card_effects("OP13-072").get("on_play", {}).get("conditions", {})
          .get("has_don_attached") is True)
    check("OP09-039 (chars_rested_gte apos 'and') parseia chars_rested_gte=2",
          get_card_effects("OP09-039").get("counter", {}).get("conditions", {})
          .get("chars_rested_gte") == 2)
    check("EB03-004 parseia condicao NOVA no_char_power_gte=6000",
          get_card_effects("EB03-004").get("opp_turn", {}).get("conditions", {})
          .get("no_char_power_gte") == 6000)
    check("OP08-109 parseia condicao NOVA has_named_character='kalgara'",
          get_card_effects("OP08-109").get("on_play", {}).get("conditions", {})
          .get("has_named_character") == "kalgara")
    check("OP02-031 (mesma familia, 'if' direto) tambem parseia has_named_character",
          get_card_effects("OP02-031").get("passive", {}).get("conditions", {})
          .get("has_named_character") == "kouzuki oden")
    check("ST16-003 parseia condicao NOVA own_rested_cards_gte=6",
          get_card_effects("ST16-003").get("passive", {}).get("conditions", {})
          .get("own_rested_cards_gte") == 6)

    # Execucao real: OP02-031 (Blocker condicionado a ter um [Kouzuki Oden]
    # em campo) -- com o aliado nomeado presente, ganha Blocker; sem ele, nao.
    toki = real_card("OP02-031")
    oden = mk("XODEN", "Kouzuki Oden Aliado")
    me = GameState(leader=mk("XTKLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [toki, oden]
    EffectExecutor(me, GameState(leader=mk("XTKOPP", "Opp", card_type="LEADER"), turn=3)).execute(toki, "passive")
    check("Execucao real: com Kouzuki Oden em campo, Toki ganha Blocker",
          toki.has_blocker)

    toki2 = real_card("OP02-031")
    me2 = GameState(leader=mk("XTKLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [toki2]
    EffectExecutor(me2, GameState(leader=mk("XTKOPP2", "Opp", card_type="LEADER"), turn=3)).execute(toki2, "passive")
    check("Execucao real: SEM Kouzuki Oden em campo, Toki NAO ganha Blocker",
          not toki2.has_blocker)

    # Execucao real: EB03-004 (buff condicionado a leader multicor E
    # ausencia de Character proprio com power>=6000).
    carina = real_card("EB03-004")
    fraco = mk("XCARFR", "Fraco", power=3000)
    me3 = GameState(leader=mk("XCARLDR", "Lider", card_type="LEADER", color="Red/Blue"), turn=3)
    me3.field_chars = [carina, fraco]
    EffectExecutor(me3, GameState(leader=mk("XCAROPP", "Opp", card_type="LEADER"), turn=3)).execute(carina, "opp_turn")
    check("Execucao real: sem Character forte (>=6000) em campo, buff de EB03-004 aplica",
          carina.power_buff == 4000)

    carina2 = real_card("EB03-004")
    forte = mk("XCARFT", "Forte", power=7000)
    me4 = GameState(leader=mk("XCARLDR2", "Lider", card_type="LEADER", color="Red/Blue"), turn=3)
    me4.field_chars = [carina2, forte]
    EffectExecutor(me4, GameState(leader=mk("XCAROPP2", "Opp", card_type="LEADER"), turn=3)).execute(carina2, "opp_turn")
    check("Execucao real: COM Character forte (>=6000) em campo, buff de EB03-004 NAO aplica",
          carina2.power_buff == 0)


def test_opp_chars_rested_gte_condicao_nova() -> None:
    # Achado 16/07 (ST24-004 Law & Bepo e OP01-032 Ashura Doji) --
    # simetrico a chars_rested_gte (proprio lado, ja existia), mas do lado
    # do OPONENTE: "if your opponent has N or more rested Characters".
    # Condicao inteira ausente, o buff disparava sempre.
    check("ST24-004 parseia opp_chars_rested_gte=2 (condicao no step buff_power)",
          any(s.get("conditions", {}).get("opp_chars_rested_gte") == 2
              for s in get_card_effects("ST24-004").get("on_play", {}).get("steps", [])))
    check("OP01-032 (mesma condicao, carta diferente) tambem parseia",
          get_card_effects("OP01-032").get("passive", {}).get("conditions", {})
          .get("opp_chars_rested_gte") == 2)

    ashura = real_card("OP01-032")
    ashura.don_attached = 1  # satisfaz don_requirement=1 ([DON!! x1])
    me = GameState(leader=mk("XASLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [ashura]
    opp_rested = GameState(leader=mk("XASOPP", "Opp", card_type="LEADER"), turn=3)
    opp_rested.field_chars = [mk("XOR1", "Opp Rested 1"), mk("XOR2", "Opp Rested 2")]
    for c in opp_rested.field_chars:
        c.rested = True
    EffectExecutor(me, opp_rested).execute(ashura, "passive")
    check("Execucao real: com 2+ Characters do OPONENTE rested, o buff de Ashura aplica",
          ashura.power_buff == 2000)

    ashura2 = real_card("OP01-032")
    ashura2.don_attached = 1
    me2 = GameState(leader=mk("XASLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [ashura2]
    opp_ativo = GameState(leader=mk("XASOPP2", "Opp", card_type="LEADER"), turn=3)
    opp_ativo.field_chars = [mk("XOA1", "Opp Ativo 1")]  # nao rested
    EffectExecutor(me2, opp_ativo).execute(ashura2, "passive")
    check("Execucao real: SEM 2+ Characters do OPONENTE rested, o buff NAO aplica",
          ashura2.power_buff == 0)


def test_choose_and_ko_it_com_upgrade_condicional() -> None:
    # Achado 16/07 (OP04-094 Trueno Bastardo) -- "Choose up to 1 of your
    # opponent's Characters with a cost of 4 or less and K.O. it." e uma
    # construcao INVERTIDA (escolhe primeiro, o verbo K.O./trash vem no
    # final), nunca reconhecida por parse_ko (que so aceita VERBO
    # primeiro). A habilidade [Main] inteira ficava ausente, so o
    # [Trigger] sobrevivia. Tambem cobre o upgrade condicional ("if you
    # have 15+ cards in your trash, ... cost of 6 or less instead of ...
    # cost of 4 or less") como 2 steps mutuamente exclusivos via
    # trash_gte/trash_lte complementares. Busca global achou so esta
    # carta -- forma generalizada mesmo assim (N alvos, tipo opcional,
    # K.O. OU trash).
    main_steps = get_card_effects("OP04-094").get("main", {}).get("steps", [])
    check("OP04-094 [Main] parseia 2 steps de ko mutuamente exclusivos (base cost_lte=4, upgrade cost_lte=6)",
          any(s.get("cost_lte") == 4 and s.get("conditions", {}).get("trash_lte") == 14 for s in main_steps)
          and any(s.get("cost_lte") == 6 and s.get("conditions", {}).get("trash_gte") == 15 for s in main_steps))
    check("Bloco [Main] NAO tem condicao vazada no nivel do bloco (so nos steps)",
          "conditions" not in get_card_effects("OP04-094").get("main", {}))

    # Execucao real: com trash < 15, so o KO de custo<=4 deve disparar
    # (o de custo<=6 fica bloqueado pela condicao trash_gte:15).
    bastardo = real_card("OP04-094")
    me = GameState(leader=mk("XTBLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [bastardo]
    me.trash = [mk(f"XTBTR{i}", f"Trash {i}") for i in range(5)]  # 5 < 15
    opp = GameState(leader=mk("XTBOPP", "Opp", card_type="LEADER"), turn=3)
    alvo_barato = mk("XTBC", "Alvo Barato", cost=4)
    alvo_caro = mk("XTBE", "Alvo Caro", cost=6)
    opp.field_chars = [alvo_barato, alvo_caro]
    ee = EffectExecutor(me, opp)
    for step in get_card_effects("OP04-094").get("main", {}).get("steps", []):
        ee._execute_step(step, bastardo)
    check("Execucao real: com trash<15, o alvo caro (custo 6) sobrevive -- so o filtro cost<=4 era viavel",
          alvo_caro in opp.field_chars)
    check("Execucao real: com trash<15, o alvo barato (custo 4) foi K.O.'d",
          alvo_barato not in opp.field_chars)

    # Com trash >= 15, o filtro upgrade (cost<=6) deve poder alcancar um
    # alvo que o filtro base (cost<=4) nao alcancaria.
    bastardo2 = real_card("OP04-094")
    me2 = GameState(leader=mk("XTBLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [bastardo2]
    me2.trash = [mk(f"XTBTR2{i}", f"Trash {i}") for i in range(15)]  # 15 >= 15
    opp2 = GameState(leader=mk("XTBOPP2", "Opp", card_type="LEADER"), turn=3)
    alvo_caro2 = mk("XTBE2", "Alvo Caro 2", cost=6)
    opp2.field_chars = [alvo_caro2]
    ee2 = EffectExecutor(me2, opp2)
    for step in get_card_effects("OP04-094").get("main", {}).get("steps", []):
        ee2._execute_step(step, bastardo2)
    check("Execucao real: com trash>=15, o alvo de custo 6 (so alcancavel pelo upgrade) foi K.O.'d",
          alvo_caro2 not in opp2.field_chars)


def test_rebecca_reveal_play_pair_condicional() -> None:
    # Achado 16/07 (OP10-058 Rebecca) -- "reveal up to 2 [Tipo] Character
    # cards with a cost of X or less other than [Nome] from your hand.
    # Play 1 of the revealed cards and play the other card rested if it
    # has a cost of Y or less" nunca era reconhecido; a metade da
    # habilidade [On Play] sumia inteira. Decompoe em 2 plays sequenciais
    # (reaproveita play_card GRUPO 2: cost_lte/filter_type/exclude/
    # enters_rested). A 2a so joga se sobrar candidato custo<=Y na mao
    # apos a 1a (senao nao faz nada -- "if" lido como condicao sobre a
    # acao inteira, confirmado com o usuario). Investigacao inicial
    # tentou tambem separar a condicao 'board_has_cost' do draw (achando
    # que so o draw era condicional) -- REVERTIDO ao comparar com 34
    # outras cartas no banco do mesmo formato "If cond, A. Then, B" onde
    # B SEMPRE compartilha a condicao de A (nao e um efeito solto
    # incondicional); manter os 3 steps sob a MESMA condicao de bloco e o
    # comportamento correto e consistente com o resto do parser.
    on_play = get_card_effects("OP10-058").get("on_play", {})
    check("OP10-058 parseia os 2 plays (reveal-pair) alem do draw, todos sob board_has_cost:[8]",
          on_play.get("conditions", {}).get("board_has_cost") == [8]
          and any(s.get("action") == "play_card" and s.get("cost_lte") == 7
                  and s.get("filter_type") == "dressrosa" and s.get("exclude") == "rebecca"
                  for s in on_play.get("steps", []))
          and any(s.get("action") == "play_card" and s.get("cost_lte") == 4
                  and s.get("enters_rested") for s in on_play.get("steps", [])))

    # Execucao real: com a condicao satisfeita (Character custo>=8 em
    # campo) e 2 Dressrosa elegiveis na mao (um custo<=4, outro custo>4)
    # -- o 1o play pega o mais valioso (potencialmente o caro), o 2o so
    # entra se ainda sobrar um custo<=4 na mao.
    rebecca = real_card("OP10-058")
    barato = mk("XRBB", "Dressrosa Barato", sub_types="Dressrosa", cost=3, power=3000)
    caro = mk("XRBC", "Dressrosa Caro", sub_types="Dressrosa", cost=7, power=9000)
    me = GameState(leader=mk("XRBLDR", "Lider", card_type="LEADER"), turn=3)
    me.hand = [barato, caro]
    me.field_chars = [mk("XRBFC", "Custo Alto em Campo", cost=8)]  # satisfaz board_has_cost
    me.deck = [mk("XRBDECK", "Topo do Deck")]
    opp = GameState(leader=mk("XRBOPP", "Opp", card_type="LEADER"), turn=3)
    log = EffectExecutor(me, opp).execute(rebecca, "on_play")
    check("Execucao real: os 2 Dressrosa saem da mao e entram em campo",
          barato in me.field_chars and caro in me.field_chars
          and barato not in me.hand and caro not in me.hand)
    check("Execucao real: o Dressrosa de custo<=4 entra RESTADO (enters_rested)",
          barato.rested)
    check("Execucao real: log confirma o draw tambem disparou (condicao satisfeita)",
          any("comprou" in x for x in log))


def test_gain_life_hand_filtro_ignorado_e_st13003_fonte_combinada() -> None:
    # Achado 16/07 (ST13-003 Luffy) -- a familia "add up to N [Tipo] type
    # Character card [with a cost of X] from your hand to the top of your
    # Life cards face-up" tinha 2 bugs em CAMADAS: (1) o PARSER nunca
    # extraia filter_type/cost quando source=='hand' (so quando source==
    # 'trash'); (2) mesmo quando o filtro existisse no step, o EXECUTOR
    # pegava sempre hand.pop(0) -- a 1a carta da mao, IGNORANDO o filtro
    # por completo. 6 cartas: EB04-060, OP08-116, OP09-104, OP10-103,
    # OP10-107 (+cost_eq exato), ST13-003 (fonte COMBINADA hand_or_trash
    # + count=2 + o bloco [DON!! x2][Activate: Main] inteiro que antes
    # nem era reconhecido -- regex antigo tinha orcamento de caracteres
    # pequeno demais pra frases com filtro).
    check("OP10-107 parseia cost_eq=5 (custo EXATO, sem 'or less')",
          any(s.get("action") == "gain_life" and s.get("cost_eq") == 5
              for s in get_card_effects("OP10-107").get("on_play", {}).get("steps", [])))
    am = get_card_effects("ST13-003").get("activate_main", {})
    check("ST13-003 parseia o bloco DON!!x2/Activate:Main inteiro (antes ausente)",
          am.get("don_requirement") == 2 and am.get("once_per_turn")
          and any(s.get("action") == "gain_life" and s.get("source") == "hand_or_trash"
                  and s.get("count") == 2 and s.get("cost_eq") == 5
                  and s.get("conditions", {}).get("life_lte") == 0
                  for s in am.get("steps", [])))

    # Execucao real: mao com 1 Character custo 5 e 1 custo 3 -- so o de
    # custo 5 deve ser elegivel (cost_eq filtra estrito).
    supernovas = real_card("OP10-107")
    certo = mk("XGL5", "Custo 5", cost=5, sub_types="Supernovas")
    errado = mk("XGL3", "Custo 3", cost=3, sub_types="Supernovas")
    me = GameState(leader=mk("XGLLDR", "Lider", card_type="LEADER"), turn=3)
    me.hand = [errado, certo]
    me.life = [mk("XGLLIFE", "Vida", cost=0)]
    opp = GameState(leader=mk("XGLOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(supernovas, "on_play")
    check("Execucao real: SO o Character de custo EXATO 5 vai pra vida (cost_eq filtra)",
          certo in me.life and errado in me.hand and errado not in me.life)

    # ST13-003: fonte combinada -- com o candidato certo (custo 5) so no
    # TRASH (nao na mao), o gain_life ainda deve alcanca-lo.
    luffy = real_card("ST13-003")
    luffy.don_attached = 2  # satisfaz [DON!! x2]
    trash_candidato = mk("XSTT5", "Trash Custo 5", cost=5)
    me2 = GameState(leader=luffy, turn=3)
    me2.hand = [mk("XSTHAND", "Custo Errado na Mao", cost=2)]
    me2.trash = [trash_candidato]
    me2.life = []  # satisfaz life_lte:0
    opp2 = GameState(leader=mk("XSTOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(luffy, "activate_main")
    check("Execucao real: ST13-003 alcanca candidato no TRASH via fonte hand_or_trash",
          trash_candidato in me2.life)


def test_leader_condicao_contamina_alvo_self_do_buff() -> None:
    # Achado 16/07 (varredura por uso real -- EB04-048 revelou o bug) --
    # "If your Leader's type includes X, this Character gains +N power"
    # tinha o buff indo pro LEADER errado: a deteccao de alvo checava
    # 'your leader' em QUALQUER lugar da janela de 90 chars ANTES de
    # checar 'this character'/'this card' -- e 'your leader' aparecia na
    # CONDICAO (nao no alvo do efeito), contaminando o resultado.
    # Corrigido com prioridade de ADJACENCIA (this character/card
    # IMEDIATAMENTE antes de 'gains') sobre a presenca solta de 'your
    # leader'. 11 cartas reais: EB01-027, EB04-048, OP01-083, OP06-088,
    # OP09-086, OP11-112, OP15-051, OP16-068, PRB02-001, ST16-003,
    # ST27-001. Guard extra: NAO deve disparar em "other than this
    # character/card gains" (exclusao de alvo, nao o alvo em si --
    # ST01-005, confirmado que continua target=leader_or_character).
    for code in ("OP06-088", "OP11-112", "OP15-051",
                 "OP16-068", "PRB02-001", "ST16-003", "ST27-001"):
        effects = get_card_effects(code)
        found_self = any(
            s.get("action") == "buff_power" and s.get("target") == "self"
            for block in effects.values() if isinstance(block, dict)
            for s in block.get("steps", [])
        )
        check(f"{code}: buff_power vai pro proprio Character (target=self), nao pro Leader",
              found_self)
    for code in ("EB01-027", "OP01-083", "OP09-086", "EB04-048"):
        effects = get_card_effects(code)
        found_self_dyn = any(
            s.get("action") == "buff_power_per_count" and s.get("target") == "self"
            for block in effects.values() if isinstance(block, dict)
            for s in block.get("steps", [])
        )
        check(f"{code}: buff_power_per_count (variante dinamica) tambem vai pro self",
              found_self_dyn)
    check("ST01-005 ('other than this card') NAO foi afetado -- continua leader_or_character",
          any(s.get("target") == "leader_or_character"
              for s in get_card_effects("ST01-005").get("when_attacking", {}).get("steps", [])))

    # Execucao real: OP06-088 com Leader Dressrosa ativo -- o buff deve
    # aplicar na PROPRIA carta (nao no lider).
    op06088 = real_card("OP06-088")
    me = GameState(leader=mk("XLDR", "Lider Dressrosa", card_type="LEADER", sub_types="Dressrosa"), turn=3)
    me.field_chars = [op06088]
    opp = GameState(leader=mk("XOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(op06088, "passive")
    check("Execucao real: power_buff vai pro Character (nao pro leader.power_buff)",
          op06088.power_buff == 2000 and me.leader.power_buff == 0)

    # Execucao real: EB04-048 com Leader CP e 10 cartas no trash (2x o
    # divisor 5) -- +2000 power E -4 cost, ambos na propria carta.
    lucci = real_card("EB04-048")
    me2 = GameState(leader=mk("XCPLDR", "Lider CP", card_type="LEADER", sub_types="CP0"), turn=3)
    me2.field_chars = [lucci]
    me2.trash = [mk(f"XLT{i}", f"Trash {i}") for i in range(10)]
    EffectExecutor(me2, GameState(leader=mk("XCPOPP", "Opp", card_type="LEADER"), turn=3)).execute(lucci, "passive")
    check("Execucao real: EB04-048 ganha +2000 power (2x1000, 10/5) na propria carta",
          lucci.power_buff == 2000)
    check("Execucao real: EB04-048 ganha -4 cost (2x-2, 10/5) na propria carta",
          lucci.cost_buff == -4)


def test_reveal_deck_top_conditional_9_cartas() -> None:
    # Achado 16/07 -- "Reveal 1 card from the top of your deck. If
    # [condicao sobre a carta revelada], [efeito]." nunca era reconhecido:
    # o efeito disparava SEMPRE, ignorando o que foi revelado. Mecanica
    # NOVA (reveal_deck_top_conditional, mesmo padrao de nested
    # on_match_steps ja usado por reveal_opp_deck_top_choose_cost). 9
    # cartas: OP04-011, OP14-044, OP15-065, ST17-001, ST22-003/006/007/
    # 012/016. Guard evitou uma regressao real em OP12-058 (mecanica
    # DIFERENTE, play_from_deck, "you may play that card" -- confirmado
    # que continua intacto). EB01-029 nao foi fechada ainda (o efeito
    # "return up to 1 of your characters to the owner's hand" nao e
    # reconhecido por nenhum parser existente -- fica de fora do fix por
    # seguranca, registrado como pendencia separada).
    check("OP04-011 parseia reveal_deck_top_conditional com power_gte=6000 e return_to=bottom",
          any(s.get("action") == "reveal_deck_top_conditional"
              and s.get("condition", {}).get("revealed_card_power_gte") == 6000
              and s.get("return_to") == "bottom"
              for s in get_card_effects("OP04-011").get("when_attacking", {}).get("steps", [])))
    check("ST22-003 parseia condition type_includes 'whitebeard pirates' (ordem invertida 'type includes X')",
          any(s.get("action") == "reveal_deck_top_conditional"
              and s.get("condition", {}).get("revealed_card_type") == "whitebeard pirates"
              for s in get_card_effects("ST22-003").get("on_play", {}).get("steps", [])))
    check("OP12-058 (mecanica DIFERENTE, play_from_deck) continua intacto, sem reveal_deck_top_conditional",
          not any(s.get("action") == "reveal_deck_top_conditional"
                  for s in get_card_effects("OP12-058").get("main", {}).get("steps", []))
          and any(s.get("action") == "play_from_deck"
                  for s in get_card_effects("OP12-058").get("main", {}).get("steps", [])))

    # Execucao real: OP04-011 com uma carta de power>=6000 no topo do
    # deck -- o buff deve disparar E a carta vai pro FUNDO do deck.
    nami = real_card("OP04-011")
    forte_topo = mk("XNMTOP", "Forte no Topo", power=7000)
    me = GameState(leader=mk("XNMLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [nami]
    me.deck = [mk("XNMBASE", "Base do Deck", power=3000), forte_topo]
    opp = GameState(leader=mk("XNMOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(nami, "when_attacking")
    check("Execucao real: com carta forte no topo, o buff dispara",
          nami.power_buff == 3000)
    check("Execucao real: a carta revelada foi pro FUNDO do deck (return_to=bottom)",
          me.deck[0] is forte_topo)

    # Sem carta forte no topo -- buff NAO dispara, mas a carta ainda e
    # revelada (e, no caso do OP04-011, ainda vai pro fundo).
    nami2 = real_card("OP04-011")
    fraco_topo = mk("XNMFR", "Fraco no Topo", power=2000)
    me2 = GameState(leader=mk("XNMLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [nami2]
    me2.deck = [mk("XNMBASE2", "Base 2", power=3000), fraco_topo]
    EffectExecutor(me2, GameState(leader=mk("XNMOPP2", "Opp", card_type="LEADER"), turn=3)).execute(nami2, "when_attacking")
    check("Execucao real: SEM carta forte no topo, o buff NAO dispara",
          nami2.power_buff == 0)

    # OP15-065 (return_to=top, default, efeito NAO mexe no deck -- add_don
    # -- diferente de ST17-001 que teria 'draw' consumindo o topo de novo
    # de forma legitima): a carta revelada permanece no topo quando o
    # texto nao pede fundo.
    bonney = real_card("OP15-065")
    barato_topo = mk("XBNC", "Barato no Topo", cost=1)
    me3 = GameState(leader=mk("XBNLDR", "Lider", card_type="LEADER"), turn=3)
    me3.field_chars = [bonney]
    me3.deck = [mk("XBNBASE", "Base 3", cost=5), barato_topo]
    me3.don_deck = 5
    EffectExecutor(me3, GameState(leader=mk("XBNOPP", "Opp", card_type="LEADER"), turn=3)).execute(bonney, "on_play")
    check("Execucao real: a carta revelada continua no TOPO do deck quando o efeito nao mexe nele (return_to=top)",
          me3.deck[-1] is barato_topo)


def test_play_card_power_lte_e_no_base_effect_e_chars_lte_power() -> None:
    # Achado 16/07 -- 3 bugs relacionados achados investigando EB04-045/
    # EB02-022: (a) OP15-097 tinha o bloco [Main] inteiro ausente por
    # falta de tolerancia a "base" em "cannot attack" (mesma familia
    # transversal ja documentada); (b) board_chars_cost_gte_count nova
    # (contagem, nao so existencia, EB04-045); (c) chars_lte nunca aceitava
    # filtro de power (EB02-022/OP10-010, o '(?! with)' excluia de
    # proposito); (d) play_card NUNCA extraia power_lte/filter_no_effect
    # -- busca ampla (nao so as 6 cartas originais) achou 25 cartas reais
    # com esse filtro perdido.
    check("OP15-097 [Main] parseia lock_opp_character_attack com cost_lte=5 (tolera 'base cost')",
          any(s.get("action") == "lock_opp_character_attack" and s.get("cost_lte") == 5
              for s in get_card_effects("OP15-097").get("main", {}).get("steps", [])))
    check("EB04-045 parseia condicao NOVA board_chars_cost_gte_count",
          get_card_effects("EB04-045").get("activate_main", {}).get("steps", [{}])[0]
          .get("conditions", {}).get("board_chars_cost_gte_count") == {"count_gte": 2, "cost_gte": 8})
    check("EB02-022 parseia chars_lte=2 com chars_lte_power_filter=5000",
          get_card_effects("EB02-022").get("on_play", {}).get("conditions", {}) ==
          {"chars_lte": 2, "chars_lte_power_filter": 5000})
    check("EB02-022 play_card parseia power_lte=6000 E filter_no_effect",
          any(s.get("action") == "play_card" and s.get("power_lte") == 6000
              and s.get("filter_no_effect") for s in get_card_effects("EB02-022").get("on_play", {}).get("steps", [])))
    check("OP04-010 (sem 'no base effect', so power_lte) tambem parseia power_lte=3000",
          any(s.get("action") == "play_card" and s.get("power_lte") == 3000
              for s in get_card_effects("OP04-010").get("on_play", {}).get("steps", [])))

    # Execucao real: EB04-045 -- com 2+ Characters (qualquer lado) de
    # custo>=8, o buff dispara; sem, nao dispara.
    ginny = real_card("EB04-045")
    me = GameState(leader=mk("XGNLDR", "Lider", card_type="LEADER"), turn=3)
    aliado_caro = mk("XGNC", "Aliado Caro", cost=8, sub_types="Revolutionary Army")
    me.field_chars = [ginny, aliado_caro]
    opp_caro = mk("XGNOC", "Opp Caro", cost=8)
    opp = GameState(leader=mk("XGNOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [opp_caro]
    EffectExecutor(me, opp).execute(ginny, "activate_main")
    check("Execucao real: com 2+ Characters custo>=8 (ambos os lados), buff de EB04-045 dispara",
          aliado_caro.power_buff == 1000)

    ginny2 = real_card("EB04-045")
    me2 = GameState(leader=mk("XGNLDR2", "Lider", card_type="LEADER"), turn=3)
    aliado2 = mk("XGN2", "Aliado", cost=8, sub_types="Revolutionary Army")
    me2.field_chars = [ginny2, aliado2]
    EffectExecutor(me2, GameState(leader=mk("XGNOPP2", "Opp", card_type="LEADER"), turn=3)).execute(ginny2, "activate_main")
    check("Execucao real: SEM 2+ Characters custo>=8, buff de EB04-045 NAO dispara",
          aliado2.power_buff == 0)

    # Execucao real: EB02-022 -- mao com 2 Characters, 1 dentro do filtro
    # power<=6000+sem-efeito, outro forte demais.
    usopp = real_card("EB02-022")
    ok_candidato = mk("XUSOK", "Candidato Fraco", power=5000)  # sem efeito parseado (mk generico)
    forte_demais = mk("XUSFT", "Candidato Forte", power=7000)
    me3 = GameState(leader=mk("XUSLDR", "Lider", card_type="LEADER"), turn=3)
    me3.hand = [forte_demais, ok_candidato]
    opp3 = GameState(leader=mk("XUSOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me3, opp3).execute(usopp, "on_play")
    check("Execucao real: EB02-022 joga SO o Character dentro do filtro power<=6000",
          ok_candidato in me3.field_chars and forte_demais in me3.hand)


def test_own_character_buff_count_maior_que_1() -> None:
    # Achado 16/07 (OP08-018) -- "Up to N of your Characters gain +X
    # power" com N>1 SEMPRE escolhia so 1 Character, mesmo com N=3 no
    # texto (nem o parser extraia count, nem o executor respeitava).
    check("OP08-018 parseia count=3 no step own_character",
          any(s.get("action") == "buff_power" and s.get("target") == "own_character"
              and s.get("count") == 3 for s in get_card_effects("OP08-018").get("main", {}).get("steps", [])))

    op08018 = real_card("OP08-018")
    c1 = mk("XOC1", "Char 1", power=3000)
    c2 = mk("XOC2", "Char 2", power=5000)
    c3 = mk("XOC3", "Char 3", power=4000)
    c4 = mk("XOC4", "Char 4 (nao deve ganhar)", power=1000)
    me = GameState(leader=mk("XOCLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [op08018, c1, c2, c3, c4]
    opp = GameState(leader=mk("XOCOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(op08018, "main")
    check("Execucao real: exatamente 3 Characters (os mais fortes) ganham +1000 power",
          sum(1 for c in [c1, c2, c3, c4, op08018] if c.power_buff == 1000) == 3
          and c4.power_buff == 0)


def test_reveal_from_hand_por_power_6_cartas() -> None:
    # Achado 16/07 -- "You may reveal N Character cards with X power
    # from your hand: [efeito]" -- custo OPCIONAL de REVELAR (prova de
    # posse, nao remove nada da mao) nunca era reconhecido, so a variante
    # por TIPO ja existia (reveal_from_hand). O efeito (as vezes poderoso,
    # ex: -6000 power) disparava de GRACA, sem exigir as cartas na mao.
    # 6 cartas: OP16-002/003/007/010/011, ST30-004.
    check("OP16-003 parseia custo reveal_from_hand power_eq=8000 card_type=CHARACTER, count=2",
          get_card_effects("OP16-003").get("on_play", {}).get("costs", []) ==
          [{"type": "reveal_from_hand", "count": 2, "power_eq": 8000, "card_type": "CHARACTER"}])
    check("ST30-004 (power diferente, 6000) tambem parseia",
          any(c.get("type") == "reveal_from_hand" and c.get("power_eq") == 6000
              for c in get_card_effects("ST30-004").get("on_play", {}).get("costs", [])))

    # Execucao real: OP16-007 -- SEM Character de power=8000 na mao, o
    # custo nao pode ser pago, o debuff nao dispara.
    newgate = real_card("OP16-007")
    me = GameState(leader=mk("XNGLDR", "Lider", card_type="LEADER"), turn=3)
    me.hand = [mk("XNGH1", "Fraco", power=5000)]
    opp_char = mk("XNGOC", "Opp Char", power=5000)
    opp = GameState(leader=mk("XNGOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [opp_char]
    EffectExecutor(me, opp).execute(newgate, "on_play")
    check("Execucao real: SEM Character de power=8000 na mao, o debuff NAO dispara",
          opp_char.power_buff == 0)

    # Com o Character de power=8000 na mao (e continua na mao -- reveal
    # NAO remove), o debuff dispara.
    newgate2 = real_card("OP16-007")
    forte_na_mao = mk("XNGH2", "Forte", power=8000)
    me2 = GameState(leader=mk("XNGLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.hand = [forte_na_mao]
    opp_char2 = mk("XNGOC2", "Opp Char 2", power=5000)
    opp2 = GameState(leader=mk("XNGOPP2", "Opp", card_type="LEADER"), turn=3)
    opp2.field_chars = [opp_char2]
    EffectExecutor(me2, opp2).execute(newgate2, "on_play")
    check("Execucao real: COM Character de power=8000 na mao, o debuff dispara E a carta continua na mao",
          opp_char2.power_buff == -1000 and forte_na_mao in me2.hand)


def test_parse_play_generic_janela_com_ponto_em_nome_colchetado() -> None:
    # Achado 16/07: `parse_play_generic` cortava a JANELA de busca no
    # primeiro '.' encontrado apos "play up to N...", sem ignorar pontos
    # DENTRO de colchetes -- nomes reais tipo [Monkey.D.Luffy]/
    # [Mr.2.Bon.Kurei.(Bentham)]/[Dr. Hogback] (300+ cartas no banco usam
    # esse padrao) cortavam a janela ANTES de "other than [...]"/"from your
    # hand or trash", derrubando exclude/source_alt/filtro em silencio (e
    # ate gerando um step DUPLICADO/bogus quando a janela escondia um
    # "from your trash" que deveria ter bloqueado o play_card generico,
    # OP14-110). Fix generalizado (scan bracket-depth-aware), nao amarrado
    # a nenhuma carta especifica.
    check("OP14-091 (type-including + 'and a cost of N or less' + hand-or-trash) parseia certo",
          get_card_effects("OP14-091").get("on_ko", {}).get("steps", []) ==
          [{"action": "play_card", "count": 1, "cost_lte": 5,
            "filter_type": "baroque works", "source_alt": "trash"}])
    check("OP16-019 ('type including X' fora do inicio da clausula + power exato) parseia certo",
          any(s.get("filter_type") == "whitebeard pirates" and s.get("power_eq") == 8000
              for s in get_card_effects("OP16-019").get("main", {}).get("steps", [])))
    check("OP05-004 recupera o 'exclude' (self-exclusion) que a janela cortada escondia",
          get_card_effects("OP05-004").get("activate_main", {}).get("steps", [{}])[0].get("exclude")
          == "emporio.ivankov")
    check("OP14-110 NAO gera mais o play_card bogus duplicado (filter_name='trigger')"
          " -- so sobra o play_from_trash correto com has_trigger+exclude",
          get_card_effects("OP14-110").get("on_ko", {}).get("steps", []) ==
          [{"action": "play_from_trash", "count": 1, "cost_lte": 4,
            "has_trigger": True, "exclude": "dr. hogback"}])

    # Execucao real: has_trigger em play_card (GRUPO 2, EB04-027 [Trigger])
    # -- so a carta com a keyword Trigger pode ser jogada, mesmo as duas
    # cabendo no filtro de power<=5000. Campo novo has_trigger no parser
    # so tem efeito se o executor tambem filtrar por ele -- sem o wiring em
    # rules_facade.eligible_cards + decision_engine, o dado ficaria
    # "calculado mas nao usado".
    eb04027 = real_card("EB04-027")
    sem_trigger = mk("TRGA", "Sem Trigger", power=4000, has_trigger=False)
    com_trigger = mk("TRGB", "Com Trigger", power=4000, has_trigger=True)
    me = GameState(leader=mk("TRGLDR", "Lider", card_type="LEADER"), turn=3)
    me.hand = [sem_trigger, com_trigger]
    opp = GameState(leader=mk("TRGOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(eb04027, "trigger")
    check("Execucao real: has_trigger filtra em play_card -- SO a carta com [Trigger] eh jogada",
          com_trigger in me.field_chars and sem_trigger in me.hand)

    # Execucao real: power_eq em play_card (OP16-019 [Main]) -- so a carta
    # de power EXATO 8000 e tipo certo entra, nao 7000/9000 nem tipo errado.
    op16019 = real_card("OP16-019")
    fraca = mk("WBA", "WB Fraca", power=7000, sub_types="Whitebeard Pirates")
    certa = mk("WBB", "WB Certa", power=8000, sub_types="Whitebeard Pirates")
    tipo_errado = mk("WBC", "Tipo Errado", power=8000, sub_types="Navy")
    me2 = GameState(leader=mk("WBLDR", "Lider", card_type="LEADER"), turn=3)
    me2.hand = [fraca, certa, tipo_errado]
    opp2 = GameState(leader=mk("WBOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(op16019, "main")
    check("Execucao real: power_eq=8000 + filter_type filtram em play_card -- so a WB de 8000 entra",
          certa in me2.field_chars and fraca in me2.hand and tipo_errado in me2.hand)

    # Execucao real: exclude em play_from_trash (OP16-085) -- a copia de si
    # mesmo no trash (mesmo nome) fica de fora mesmo elegivel por tipo/custo;
    # so o candidato Land of Wano diferente entra.
    momo = real_card("OP16-085")
    outra_copia = mk("MOMOX", "Kouzuki Momonosuke (085)", power=6000, cost=9,
                      sub_types="Land of Wano Kouzuki Clan")
    candidato_valido = mk("LOWA", "Kanjuro", power=5000, cost=5, sub_types="Land of Wano")
    me3 = GameState(leader=mk("MOMOLDR", "Lider", card_type="LEADER"), turn=3)
    me3.trash = [outra_copia, candidato_valido]
    opp3 = GameState(leader=mk("MOMOOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me3, opp3).execute(momo, "on_play")
    check("Execucao real: exclude em play_from_trash barra a copia homonima, joga o outro Land of Wano",
          candidato_valido in me3.field_chars and outra_copia in me3.trash)


def test_rest_opp_character_typo_cost_or_n_or_less() -> None:
    # Achado 16/07, OP16-039: "rest up to 2 of your opponent's Characters
    # with a cost or 3 or less" (typo "or" em vez de "of") -- a mesma
    # tolerancia ja existia pra lock_opp_character_attack (OP14-119), mas
    # rest_opp_character usava regex separada sem o (?:of|or). cost_lte
    # saia None (sem filtro nenhum), restando characters CAROS demais.
    check("OP16-039 parseia cost_lte=3 apesar do typo 'cost or 3 or less'",
          any(s.get("action") == "rest_opp_character" and s.get("cost_lte") == 3
              for s in get_card_effects("OP16-039").get("main", {}).get("steps", [])))

    jet_pistol = real_card("OP16-039")
    me = GameState(leader=mk("JPLDR", "Lider", card_type="LEADER", sub_types="Impel Down"), turn=3)
    barato = mk("JPA", "Barato", cost=3, power=3000, color="Green")
    caro = mk("JPB", "Caro", cost=5, power=5000, color="Green")
    opp = GameState(leader=mk("JPOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [barato, caro]
    EffectExecutor(me, opp).execute(jet_pistol, "main")
    check("Execucao real: SO o Character de custo<=3 e restado, o de custo 5 fica de fora",
          barato.rested and not caro.rested)


def test_eb01_028_active_qualifier_e_return_como_sinonimo_de_place() -> None:
    # Achado 16/07, EB01-028 (Gum-Gum Champion Rifle): duas clausulas
    # inteiras nunca eram parseadas.
    # (1) [Counter] "your opponent returns 1 of their ACTIVE Characters to
    #     the owner's hand" -- o qualificador "active" entre o possessivo e
    #     "characters" quebrava a regex de opp_bounce_own_character (so
    #     aceitava "their characters" direto). Alem de reconhecer a
    #     clausula, "active" tambem RESTRINGE quais characters do
    #     oponente sao elegiveis -- nao so cosmetico.
    # (2) [Trigger] "Return up to 1 Character with a cost of 3 or less to
    #     the bottom of the owner's deck" -- parse_place_bottom so aceitava
    #     o verbo "place", nao "return" (sinonimo, mesmo mecanismo). Sem
    #     qualificador de posse = mira o oponente (regra ja estabelecida).
    effects = get_card_effects("EB01-028")
    check("EB01-028 [Counter] parseia opp_bounce_own_character com active_only=True",
          {"action": "opp_bounce_own_character", "count": 1, "active_only": True}
          in effects.get("counter", {}).get("steps", []))
    check("EB01-028 [Trigger] parseia place_opp_character_bottom_deck (verbo 'return') cost_lte=3",
          effects.get("trigger", {}).get("steps", []) ==
          [{"action": "place_opp_character_bottom_deck", "count": 1, "cost_lte": 3}])

    # Guarda de regressao: EB01-029 tem "return up to 1 of your Characters
    # to the owner's hand" (bounce, sentenca 1) seguido por "place THE
    # REVEALED CARD at the bottom of your deck" (sentenca 2, sujeito
    # diferente) no mesmo bloco [Counter] -- ao adicionar "return" como
    # sinonimo de "place", um .*? sem guarda de ponto quase fabricou
    # place_own_character_bottom_deck ligando as duas sentencas sem
    # relacao (pego ANTES do commit, nunca chegou a rodar smoke_test_broad
    # com o bug). So deve ter o bounce (ainda nao implementado -- gap
    # separado, nao regride) e o buff/reveal do inicio, NUNCA
    # place_own_character_bottom_deck.
    eb01029 = get_card_effects("EB01-029")
    check("EB01-029 NAO fabrica place_own_character_bottom_deck cruzando duas sentencas",
          not any(s.get("action") == "place_own_character_bottom_deck"
                  for s in eb01029.get("counter", {}).get("steps", [])))

    # Execucao real: opp_bounce_own_character com active_only -- so o
    # character ATIVO do oponente e devolvido pra mao, mesmo o RESTADO
    # sendo pior (board_value menor) e normalmente escolhido primeiro pela
    # heuristica "pior primeiro".
    rifle = real_card("EB01-028")
    me = GameState(leader=mk("RFLDR", "Lider", card_type="LEADER", sub_types="Impel Down"), turn=3)
    me.field_chars = [mk("RFA", "Meu Char", power=3000)]
    ativo_forte = mk("RFB", "Ativo Forte", power=6000)
    restado_fraco = mk("RFC", "Restado Fraco", power=1000)
    restado_fraco.rested = True
    opp = GameState(leader=mk("RFOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [ativo_forte, restado_fraco]
    EffectExecutor(me, opp).execute(rifle, "counter")
    check("Execucao real: active_only bounce SO o ativo (mesmo sendo o mais forte), restado fica no campo",
          ativo_forte in opp.hand and restado_fraco in opp.field_chars)

    # Execucao real: [Trigger] com "return" -- SO o Character de custo<=3
    # do oponente vai pro fundo do deck.
    rifle2 = real_card("EB01-028")
    me2 = GameState(leader=mk("RFLDR2", "Lider", card_type="LEADER"), turn=3)
    barato_opp = mk("RFOA", "Barato", cost=3, power=3000)
    caro_opp = mk("RFOB", "Caro", cost=5, power=8000)
    opp2 = GameState(leader=mk("RFOPP2", "Opp", card_type="LEADER"), turn=3)
    opp2.field_chars = [barato_opp, caro_opp]
    EffectExecutor(me2, opp2).execute(rifle2, "trigger")
    check("Execucao real: [Trigger] manda SO o custo<=3 pro fundo do deck do oponente",
          barato_opp not in opp2.field_chars and caro_opp in opp2.field_chars)


def test_select_grant_blocker_4_cartas() -> None:
    # Achado 16/07, OP07-024 (Koala): "Up to 1 of your [Fish-Man] type
    # Characters with a cost of 5 or less gains [Blocker]" era tratado
    # como "esta carta ganha Blocker" (gain_blocker, alvo=self) -- bug de
    # COMPORTAMENTO REAL, nao so filtro perdido: Koala resta A SI MESMA
    # como custo, entao a antiga implementacao concederia Blocker a quem
    # ja esta restada (inutil, ja que rested nao pode ativar Blocker de
    # qualquer forma). Censo global achou 4 cartas com a mesma FORMA
    # ("up to N of your [Tipo] Characters ... gains [Blocker]"):
    # OP07-024 (filtro de custo), OP07-103/OP15-055 (so tipo), OP12-012
    # ("type including X" + "other than [Nome]" de auto-exclusao +
    # duracao 'until_opp_end_phase' em vez de permanente).
    check("OP07-024 parseia select_grant_blocker com filter_type='fish-man' e cost_lte=5",
          get_card_effects("OP07-024").get("on_opp_attack", {}).get("steps", []) ==
          [{"action": "select_grant_blocker", "count": 1, "filter_type": "fish-man",
            "cost_lte": 5, "duration": "this_turn"}])
    check("OP12-012 parseia filter_type via 'type including', exclude='buggy' e duration='until_opp_end_phase'",
          get_card_effects("OP12-012").get("on_play", {}).get("steps", []) ==
          [{"action": "select_grant_blocker", "count": 1, "filter_type": "roger pirates",
            "exclude": "buggy", "duration": "until_opp_end_phase"}])

    # Execucao real: OP07-024 -- so o Fish-Man com custo<=5 ganha Blocker,
    # um Fish-Man de custo 6 (fora do filtro) e ignorado, e a propria
    # Koala (nao e Fish-Man) nao ganha nada.
    koala = real_card("OP07-024")
    me = GameState(leader=mk("KOLDR", "Lider", card_type="LEADER"), turn=3)
    fishman_barato = mk("FMA", "Fishman Barato", cost=5, power=4000, sub_types="Fish-Man")
    fishman_caro = mk("FMB", "Fishman Caro", cost=6, power=7000, sub_types="Fish-Man")
    me.field_chars = [koala, fishman_barato, fishman_caro]
    opp = GameState(leader=mk("KOOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(koala, "on_opp_attack")
    check("Execucao real: SO o Fish-Man de custo<=5 ganha Blocker, custo 6 e a propria Koala ficam de fora",
          fishman_barato.blocker_this_turn and not fishman_caro.blocker_this_turn
          and not koala.blocker_this_turn)

    # Execucao real: OP12-012 (Buggy) -- exclude='buggy' impede que a
    # propria carta-fonte (mesmo sendo Roger Pirates) ganhe Blocker;
    # outro Roger Pirates no campo ganha normalmente.
    buggy = real_card("OP12-012")
    me2 = GameState(leader=mk("BGLDR", "Lider", card_type="LEADER"), turn=3)
    outro_roger = mk("RGA", "Outro Roger Pirates", power=5000, sub_types="Roger Pirates")
    me2.field_chars = [buggy, outro_roger]
    opp2 = GameState(leader=mk("BGOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(buggy, "on_play")
    check("Execucao real: 'other than [Buggy]' exclui a propria fonte, o outro Roger Pirates ganha Blocker",
          outro_roger.blocker_this_turn and not buggy.blocker_this_turn)


def test_look_top_deck_cost_range_eb03_060() -> None:
    # Achado 16/07, EB03-060: "look at 4 cards from the top of your deck;
    # reveal up to 1 card with a cost of 2 to 8 and add it to your hand"
    # -- parse_look_at so aceitava "cost of N or less"/"or more"
    # separados, nunca a FAIXA "N to M" (mesma convencao ja usada em
    # parse_add_from_trash desde 15/07, OP05-091 "cost of 3 to 7", so que
    # aquela e fonte=trash, esta e fonte=topo do deck).
    check("EB03-060 parseia cost_gte=2 e cost_lte=8 no add_to_hand",
          any(s.get("action") == "add_to_hand" and s.get("cost_gte") == 2 and s.get("cost_lte") == 8
              for s in get_card_effects("EB03-060").get("main", {}).get("steps", [])))

    # Execucao real: das 4 cartas no topo do deck, so a de custo DENTRO da
    # faixa [2, 8] pode ser adicionada -- custo 1 (abaixo) e custo 9
    # (acima) ficam de fora, so a de custo 5 (dentro) e elegivel.
    nami_evento = real_card("EB03-060")
    me = GameState(leader=mk("NMLDR", "Nami", card_type="LEADER"), turn=3)
    barato_demais = mk("NMA", "Barato Demais", cost=1, power=1000)
    dentro_da_faixa = mk("NMB", "Dentro da Faixa", cost=5, power=5000)
    caro_demais = mk("NMC", "Caro Demais", cost=9, power=9000)
    me.deck = [barato_demais, dentro_da_faixa, caro_demais]
    opp = GameState(leader=mk("NMOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(nami_evento, "main")
    check("Execucao real: SO a carta de custo 5 (dentro de 2-8) vai pra mao",
          dentro_da_faixa in me.hand and barato_demais not in me.hand and caro_demais not in me.hand)


def test_op09_007_leader_power_lte_e_op03_016_sem_contaminacao() -> None:
    # Achado 16/07, OP09-007 (Heat): "Up to 1 of your Leader with 4000
    # power or less gains +1000 power" -- power_lte nunca era extraido
    # pra target='leader' (so 'own_character' ja tinha essa filtragem).
    # O buff aplicava incondicionalmente, mesmo com o Leader MUITO forte
    # (ex: 8000+ power), quando o texto so autoriza ate 4000.
    check("OP09-007 parseia power_lte=4000 no buff do Leader",
          get_card_effects("OP09-007").get("on_play", {}).get("steps", []) ==
          [{"action": "buff_power", "amount": 1000, "target": "leader",
            "duration": "this_turn", "power_lte": 4000}])

    # Guarda de regressao: ao generalizar power_lte pra 'leader', quase
    # contaminou OP03-016 ("K.O. up to 1 of your opponent's Characters
    # with 8000 power or less, and your Leader gains [Double Attack] and
    # +3000 power during this turn.") -- o "8000 power or less" pertence
    # ao KO anterior, NADA a ver com o Leader, mas a janela de contexto
    # generica capturava por proximidade. Pego pelo diff_parser ANTES do
    # commit, corrigido com regex mais estrita ("your leader with N power"
    # adjacente, nao qualquer "with N power or less" na janela).
    check("OP03-016 NAO ganha power_lte espurio no buff do Leader",
          "power_lte" not in next(
              (s for s in get_card_effects("OP03-016").get("main", {}).get("steps", [])
               if s.get("action") == "buff_power"), {}))

    # Execucao real: Leader com 4000 power (dentro do limite) recebe o
    # buff; Leader com 5000 power (acima do limite) NAO recebe.
    heat = real_card("OP09-007")
    me = GameState(leader=mk("HTLDR", "Lider Fraco", power=4000, card_type="LEADER"), turn=3)
    opp = GameState(leader=mk("HTOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(heat, "on_play")
    check("Execucao real: Leader com 4000 power (limite exato) RECEBE o buff",
          me.leader.power_buff == 1000)

    heat2 = real_card("OP09-007")
    me2 = GameState(leader=mk("HTLDR2", "Lider Forte", power=5000, card_type="LEADER"), turn=3)
    opp2 = GameState(leader=mk("HTOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(heat2, "on_play")
    check("Execucao real: Leader com 5000 power (acima do limite) NAO recebe o buff",
          me2.leader.power_buff == 0)


def test_return_own_character_to_hand_com_filtro_8_cartas() -> None:
    # Achado 16/07, OP10-047 (Koala) e familia: "You may return 1 of your
    # [Tipo] type Characters with a cost of N or more to the owner's
    # hand: [efeito]" -- o custo return_own_character_to_hand JA existia
    # no parser/engine, mas a regex exigia "characters to the owner's
    # hand" ADJACENTE -- qualquer filtro de tipo/custo/exclusao no meio
    # (8 cartas: EB01-021, OP07-056, OP10-002, OP10-047, OP16-045,
    # OP16-050, ST12-001, OP08-047) derrubava o CUSTO INTEIRO. A IA
    # tratava a habilidade como GRATIS, sem checar se tinha Character
    # elegivel pra pagar.
    check("OP10-047 parseia o custo com filter_type='revolutionary army' e cost_gte=3",
          get_card_effects("OP10-047").get("when_attacking", {}).get("costs", []) ==
          [{"type": "return_own_character_to_hand", "count": 1,
            "filter_type": "revolutionary army", "cost_gte": 3}])
    check("OP08-047 parseia 'other than this Character' como exclude_self=True",
          get_card_effects("OP08-047").get("on_play", {}).get("costs", []) ==
          [{"type": "return_own_character_to_hand", "count": 1, "exclude_self": True}])

    # Execucao real: OP10-047 (Koala, when_attacking) -- SO paga o custo
    # se existir um Revolutionary Army com custo>=3 pra devolver (custo
    # 2 nao serve mesmo sendo Revolutionary Army; custo 5 nao serve por
    # nao ser Revolutionary Army). Com candidato valido, o custo e pago
    # (o candidato volta pra mao) E o efeito dispara (+3000 na Koala).
    koala = real_card("OP10-047")
    ra_barato = mk("KLA", "RA Barato", cost=2, power=2000, sub_types="Revolutionary Army")
    ra_caro = mk("KLB", "RA Caro", cost=4, power=4000, sub_types="Revolutionary Army")
    outro_tipo = mk("KLC", "Outro Tipo", cost=5, power=5000, sub_types="Marines")
    me = GameState(leader=mk("KLLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [koala, ra_barato, ra_caro, outro_tipo]
    opp = GameState(leader=mk("KLOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(koala, "when_attacking")
    check("Execucao real: custo pago com o RA de custo 4 (unico elegivel), Koala ganha +3000",
          ra_caro in me.hand and ra_barato in me.field_chars
          and outro_tipo in me.field_chars and koala.power_buff == 3000)

    # Sem candidato elegivel (so RA barato demais e tipo errado), o custo
    # NAO pode ser pago -- o efeito inteiro (buff) nao dispara.
    koala2 = real_card("OP10-047")
    ra_barato2 = mk("KLD", "RA Barato 2", cost=2, power=2000, sub_types="Revolutionary Army")
    outro_tipo2 = mk("KLE", "Outro Tipo 2", cost=5, power=5000, sub_types="Marines")
    me2 = GameState(leader=mk("KLLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [koala2, ra_barato2, outro_tipo2]
    opp2 = GameState(leader=mk("KLOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(koala2, "when_attacking")
    check("Execucao real: SEM candidato elegivel, custo NAO e pago, Koala NAO ganha o buff",
          ra_barato2 in me2.field_chars and outro_tipo2 in me2.field_chars
          and koala2.power_buff == 0)

    # Julgamento de "vale a pena" (on_play, _worth_paying_optional_costs):
    # OP16-045 tem custo generico (sem filtro de tipo, so cost_gte=2) --
    # antes desta correcao, esse tipo de custo nunca entrava na conta de
    # sacrificio (SEMPRE tratado como "de graca"). Com um candidato FRACO
    # (board_value baixo) a habilidade vale a pena e dispara; com SO um
    # candidato FORTE (o unico sacrificio possivel seria caro demais), a
    # IA recusa e a habilidade nao dispara.
    croc = real_card("OP16-045")
    fraco = mk("CRA", "Fraco", cost=2, power=2000)
    me3 = GameState(leader=mk("CRLDR", "Lider", card_type="LEADER"), turn=3)
    me3.field_chars = [croc, fraco]
    me3.hand = [mk("CRH", "Impel Down Barato", cost=1, power=1000, sub_types="Impel Down")]
    opp3 = GameState(leader=mk("CROPP", "Opp", card_type="LEADER"), turn=3)
    logs3 = EffectExecutor(me3, opp3).execute(croc, "on_play")
    check("Execucao real: candidato FRACO -- IA aceita pagar o custo (habilidade dispara)",
          bool(logs3) and fraco in me3.hand)

    croc2 = real_card("OP16-045")
    forte = mk("CRB", "Forte", cost=8, power=9000)
    me4 = GameState(leader=mk("CRLDR2", "Lider", card_type="LEADER"), turn=3)
    me4.field_chars = [croc2, forte]
    me4.hand = [mk("CRH2", "Impel Down Barato 2", cost=1, power=1000, sub_types="Impel Down")]
    opp4 = GameState(leader=mk("CROPP2", "Opp", card_type="LEADER"), turn=3)
    logs4 = EffectExecutor(me4, opp4).execute(croc2, "on_play")
    check("Execucao real: SO candidato FORTE -- IA recusa pagar (habilidade nao dispara)",
          not logs4 and forte in me4.field_chars)


def test_reveal_events_custo_5_cartas() -> None:
    # Achado 16/07, OP12-001 (Silvers Rayleigh) e familia: "You may
    # reveal 2 Events from your hand: [efeito]" -- 3a variante do custo
    # reveal_from_hand ja existente (prova de posse, nao remove nada da
    # mao), filtrada por card_type=EVENT em vez de tipo/power. Census
    # achou 5 cartas com essa forma: OP12-001, OP12-003, OP12-004,
    # OP12-009, OP12-015 -- todas perdiam o custo INTEIRO, efeito
    # disparava de graca sem checar se tinha 2 Events na mao.
    check("OP12-001 parseia o custo reveal_from_hand count=2 card_type=EVENT",
          get_card_effects("OP12-001").get("activate_main", {}).get("costs", []) ==
          [{"type": "reveal_from_hand", "count": 2, "card_type": "EVENT"}])
    check("OP12-004 (mesma forma, acao diferente) tambem parseia",
          get_card_effects("OP12-004").get("activate_main", {}).get("costs", []) ==
          [{"type": "reveal_from_hand", "count": 2, "card_type": "EVENT"}])

    # Execucao real: SEM 2 Events na mao, o custo nao pode ser pago, o
    # buff nao dispara.
    rayleigh = real_card("OP12-001")
    me = GameState(leader=mk("RLLDR", "Lider", card_type="LEADER"), turn=3)
    fraco = mk("RLA", "Fraco", power=3000)
    me.field_chars = [fraco]
    me.hand = [mk("RLH1", "Nao Event", card_type="CHARACTER"),
               mk("RLH2", "Event Unico", card_type="EVENT")]
    opp = GameState(leader=mk("RLOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(rayleigh, "activate_main")
    check("Execucao real: SO 1 Event na mao (precisa de 2) -- custo NAO pago, buff NAO dispara",
          fraco.power_buff == 0)

    # Com 2 Events na mao, o custo e pago (revelar, sem remover nada) e o
    # buff dispara; as cartas continuam na mao.
    rayleigh2 = real_card("OP12-001")
    me2 = GameState(leader=mk("RLLDR2", "Lider", card_type="LEADER"), turn=3)
    fraco2 = mk("RLB", "Fraco 2", power=3000)
    me2.field_chars = [fraco2]
    ev1 = mk("RLH3", "Event 1", card_type="EVENT")
    ev2 = mk("RLH4", "Event 2", card_type="EVENT")
    me2.hand = [ev1, ev2]
    opp2 = GameState(leader=mk("RLOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(rayleigh2, "activate_main")
    check("Execucao real: COM 2 Events na mao, custo pago (SEM remover) e buff dispara",
          fraco2.power_buff == 2000 and ev1 in me2.hand and ev2 in me2.hand)


def test_atalho_don_bare_sem_texto_explicativo_2_cartas() -> None:
    # Achado 17/07, OP05-032 (Pica) e OP05-119: "(N):" logo apos a tag do
    # trigger e o mesmo atalho numerico de custo em DON!! ja reconhecido
    # em outras cartas (ex: "When Attacking (1) (You may rest the
    # specified number of DON!! cards in your cost area.):"), so que SEM
    # o texto explicativo padrao -- a raspagem do banco parece ter
    # omitido a explicacao so nessas 2 cartas. Primeira tentativa tratou
    # "(1)" como don_requirement (exige DON ANEXADO na carta, semantica
    # de "[DON!! xN]") -- ERRADO: confirmado contra OP03-022 (mesmo
    # atalho, mas com a explicacao presente) que o "(N)" e um CUSTO de
    # restar N DON!! do cost area (rest_don), campo totalmente separado
    # de don_requirement. Corrigido antes do commit.
    check("OP05-032 parseia o custo rest_don count=1 (nao don_requirement)",
          get_card_effects("OP05-032").get("end_of_turn", {}).get("costs", []) ==
          [{"type": "rest_don", "count": 1}])
    check("OP05-119 (com tag [Once Per Turn] entre o trigger e o atalho) tambem parseia",
          get_card_effects("OP05-119").get("activate_main", {}).get("costs", []) ==
          [{"type": "rest_don", "count": 1}])

    # Execucao real: sem DON disponivel, o custo nao pode ser pago, a
    # habilidade nao dispara (Pica nao fica ativa).
    pica = real_card("OP05-032")
    pica.rested = True
    me = GameState(leader=mk("PCLDR", "Lider", card_type="LEADER"), turn=3)
    me.don_available = 0
    opp = GameState(leader=mk("PCOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(pica, "end_of_turn")
    check("Execucao real: SEM DON disponivel, custo nao pago, Pica continua restada",
          pica.rested)

    # Com 1 DON disponivel, o custo e pago (DON vai pra rested) e Pica
    # fica ativa.
    pica2 = real_card("OP05-032")
    pica2.rested = True
    me2 = GameState(leader=mk("PCLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.don_available = 1
    opp2 = GameState(leader=mk("PCOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(pica2, "end_of_turn")
    check("Execucao real: COM 1 DON disponivel, custo pago, Pica fica ativa",
          not pica2.rested and me2.don_available == 0 and me2.don_rested == 1)


def test_pica_substitute_ko_cost_gte_e_exclude_self() -> None:
    # Achado 17/07, OP05-032 (Pica): "[Once Per Turn] If this Character
    # would be K.O.'d, you may rest up to 1 of your Characters with a cost
    # of 3 or more other than [Pica] instead." -- nenhum padrao de custo
    # existente tolerava "up to" + filtro de custo + exclusao por nome
    # juntos (so 1 carta no banco usa essa combinacao).
    #
    # BUG ESTRUTURAL achado durante a implementacao (nao so filtro
    # perdido): "[End of Your Turn] (1): Set active. [Once Per Turn] If...
    # instead" faz "[Once Per Turn]" ficar preso DENTRO do bloco
    # end_of_turn (sem tag formal propria) -- o substitute_ko virava um
    # step de end_of_turn, timing que try_substitute() NUNCA verifica (so
    # 'passive'/'opp_turn'/'your_turn'), tornando a substituicao
    # SILENCIOSAMENTE INERTE. Mesma classe de bug ja corrigida em 16/07
    # pra when_attacking (OP12-081) -- corrigido aqui com uma NOVA entrada
    # em trigger_patterns ancorada em "[end of your turn]...clausula"
    # (nao um padrao generico, pra nao conflitar com as ~30 cartas que ja
    # tem "[Once Per Turn] If...K.O.'d...instead" capturado certo por
    # segmento_solto quando vem no INICIO do texto, sem tag antes).
    check("OP05-032 parseia substitute_ko em 'passive' (nao em 'end_of_turn')",
          get_card_effects("OP05-032").get("passive", {}).get("steps", []) ==
          [{"action": "substitute_ko", "cost": {"action": "rest_own_character",
            "count": 1, "cost_gte": 3, "exclude": "pica"}}])
    check("end_of_turn continua so com set_active (substitute_ko NAO ficou preso la)",
          get_card_effects("OP05-032").get("end_of_turn", {}).get("steps", []) ==
          [{"action": "set_active", "target": "self"}])

    # Execucao real: um atacante tenta K.O. a Pica. Ela tem 2 candidatos
    # pra pagar o custo: um Donquixote barato (custo 2, fora do filtro
    # cost_gte=3) e um caro (custo 4, dentro do filtro) -- so o caro pode
    # pagar. A propria Pica ("other than [Pica]") fica de fora mesmo tendo
    # custo 4 (seu proprio custo real).
    pica = real_card("OP05-032")
    barato = mk("PCA", "Barato", cost=2, power=2000)
    caro = mk("PCB", "Caro", cost=4, power=4000)
    dono_pica = GameState(leader=mk("PCDLDR", "Lider", card_type="LEADER"), turn=3)
    dono_pica.field_chars = [pica, barato, caro]
    atacante = GameState(leader=mk("PCATKLDR", "Atacante", card_type="LEADER"), turn=3)
    EffectExecutor(atacante, dono_pica)._execute_step(
        {"action": "ko", "count": 1, "target": "opp_character"}, atacante.leader)
    check("Execucao real: Pica NAO foi K.O.'d (substituiu), so o Caro (custo>=3) foi restado",
          pica in dono_pica.field_chars and pica not in dono_pica.trash
          and caro.rested and not barato.rested and not pica.rested)

    # Sem NENHUM candidato elegivel (so o barato, fora do filtro de
    # custo), a substituicao falha e Pica E K.O.'d normalmente.
    pica2 = real_card("OP05-032")
    barato2 = mk("PCA2", "Barato 2", cost=2, power=2000)
    dono_pica2 = GameState(leader=mk("PCDLDR2", "Lider", card_type="LEADER"), turn=3)
    dono_pica2.field_chars = [pica2, barato2]
    atacante2 = GameState(leader=mk("PCATKLDR2", "Atacante", card_type="LEADER"), turn=3)
    EffectExecutor(atacante2, dono_pica2)._execute_step(
        {"action": "ko", "count": 1, "target": "opp_character"}, atacante2.leader)
    check("Execucao real: SEM candidato elegivel (custo>=3), Pica E K.O.'d normalmente",
          pica2 in dono_pica2.trash and pica2 not in dono_pica2.field_chars)


def test_don_on_field_zero_or_gte_2_cartas() -> None:
    # Achado 17/07, OP05-060/ST10-002 (Monkey.D.Luffy, 2 cartas): "If you
    # have 0 [DON!! cards on your field] or N or more DON!! cards on your
    # field, add up to 1 DON!! card..." -- condicao OR de dois limiares
    # DESCONECTADOS (0 OU N+), distinta de um intervalo (gte+lte com AND
    # excluiria justamente o 0). A condicao inteira ficava ausente, o
    # add_don disparava sempre, independente da contagem real de DON.
    check("OP05-060 parseia don_on_field_zero_or_gte=3 (condicao por-step, apos custo ':')",
          get_card_effects("OP05-060").get("activate_main", {}).get("steps", [{}])[0]
          .get("conditions", {}) == {"don_on_field_zero_or_gte": 3})
    check("ST10-002 parseia don_on_field_zero_or_gte=8 (condicao no nivel do entry)",
          get_card_effects("ST10-002").get("activate_main", {}).get("conditions", {}) ==
          {"don_on_field_zero_or_gte": 8})

    # Execucao real (ST10-002, limiar=8): com 0 DON no campo, dispara.
    luffy0 = real_card("ST10-002")
    me0 = GameState(leader=mk("LF0LDR", "Lider", card_type="LEADER"), turn=3,
                     don_available=0, don_rested=0)
    opp0 = GameState(leader=mk("LF0OPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me0, opp0).execute(luffy0, "activate_main")
    check("Execucao real: 0 DON no campo -- dispara (extremo inferior do OR)",
          me0.don_available == 1)

    # Com 2 DON no campo (entre 1 e 7, FORA do OR: nao e 0 nem >=8), NAO dispara.
    luffy_meio = real_card("ST10-002")
    me_meio = GameState(leader=mk("LFMLDR", "Lider", card_type="LEADER"), turn=3,
                         don_available=1, don_rested=1)
    opp_meio = GameState(leader=mk("LFMOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me_meio, opp_meio).execute(luffy_meio, "activate_main")
    check("Execucao real: 2 DON no campo (nem 0 nem >=8) -- NAO dispara",
          me_meio.don_available == 1)

    # Com 8 DON no campo (limiar exato), dispara.
    luffy8 = real_card("ST10-002")
    me8 = GameState(leader=mk("LF8LDR", "Lider", card_type="LEADER"), turn=3,
                     don_available=8, don_rested=0)
    opp8 = GameState(leader=mk("LF8OPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me8, opp8).execute(luffy8, "activate_main")
    check("Execucao real: 8 DON no campo (limiar exato) -- dispara",
          me8.don_available == 9)


def test_select_grant_rush_6_cartas() -> None:
    # Achado 17/07: gain_rush (self-only, sem selecao) era usado por engano
    # em 6 cartas que na verdade SELECIONAM outro Character do campo --
    # bug de comportamento real (o Rush ia pra propria fonte, nao pro alvo
    # descrito no texto). Mesma familia arquitetural de select_grant_blocker
    # (16/07). 2 variantes: (a) OR entre nome exato E tipo+power (OP16-001,
    # unica com essa forma); (b) filtro UNICO tipo/custo/exclusao/
    # filter_no_tag ("without a [Tag] effect", achado NOVO -- distinto de
    # filter_no_effect que exige NENHUM efeito parseado): EB03-001,
    # OP04-001, OP12-007, PRB01-001.
    check("OP16-001 parseia select_grant_rush com OR (filter_name + filter_type/power_gte)",
          get_card_effects("OP16-001").get("activate_main", {}).get("steps", [{}])[0] ==
          {"action": "select_grant_rush", "filter_name": "monkey.d.luffy",
           "filter_type": "whitebeard pirates", "power_gte": 8000, "duration": "this_turn"})
    check("PRB01-001 parseia filter_no_tag='on_play' + cost_lte=8",
          get_card_effects("PRB01-001").get("activate_main", {}).get("steps", [{}])[0] ==
          {"action": "select_grant_rush", "count": 1, "cost_lte": 8,
           "filter_no_tag": "on_play", "duration": "this_turn"})
    check("EB03-001 parseia filter_no_tag='when_attacking' (tag DIFERENTE, mesmo mecanismo)",
          any(s.get("action") == "select_grant_rush" and s.get("filter_no_tag") == "when_attacking"
              for s in get_card_effects("EB03-001").get("activate_main", {}).get("steps", [])))
    check("OP12-007 parseia filter_type='roger pirates' + exclude='shanks'",
          get_card_effects("OP12-007").get("on_play", {}).get("steps", [{}])[0] ==
          {"action": "select_grant_rush", "count": 1, "filter_type": "roger pirates",
           "exclude": "shanks", "duration": "this_turn"})

    # Execucao real (OR): entre um Luffy fraco e um Whitebeard Pirates
    # forte (acima do limiar de power), o mais valioso (Whitebeard forte)
    # ganha Rush; um Whitebeard FRACO (abaixo do limiar) fica de fora.
    ace = real_card("OP16-001")
    luffy_char = mk("RSA", "Monkey.D.Luffy Fraco", power=3000)
    wb_fraco = mk("RSB", "WB Fraco", power=5000, sub_types="Whitebeard Pirates")
    wb_forte = mk("RSC", "WB Forte", power=9000, sub_types="Whitebeard Pirates")
    me = GameState(leader=ace, turn=3)
    me.field_chars = [luffy_char, wb_fraco, wb_forte]
    opp = GameState(leader=mk("RSOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(ace, "activate_main")
    check("Execucao real: WB Forte (acima do limiar) ganha Rush, WB Fraco (abaixo) NAO",
          wb_forte.rush_this_turn and not wb_fraco.rush_this_turn and not luffy_char.rush_this_turn)

    # Execucao real (filter_no_tag): entre um Character REAL com efeito
    # [On Play] (nao elegivel) e um sem NENHUM efeito parseado (elegivel,
    # custo dentro do limite), so o segundo ganha Rush.
    sanji = real_card("PRB01-001")
    com_on_play = real_card("EB01-015")
    sem_efeito = real_card("EB01-005")
    me2 = GameState(leader=sanji, turn=3)
    me2.field_chars = [com_on_play, sem_efeito]
    opp2 = GameState(leader=mk("SNOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(sanji, "activate_main")
    check("Execucao real: SO o Character sem [On Play] ganha Rush",
          sem_efeito.rush_this_turn and not com_on_play.rush_this_turn)


def test_op16_043_typo_tour_opponent() -> None:
    # Achado 17/07, OP16-043 (Usopp): "[On K.O.] Return up to 1 of TOUR
    # opponent's Characters with a cost of 5 or less to the owner's hand."
    # -- typo "tour" em vez de "your" nunca era tolerado, a acao de bounce
    # inteira ficava ausente (so o keyword Blocker era parseado).
    check("OP16-043 parseia bounce (tolerando o typo 'tour')",
          get_card_effects("OP16-043").get("on_ko", {}).get("steps", []) ==
          [{"action": "bounce", "count": 1, "target": "opp_character", "cost_lte": 5}])

    usopp = real_card("OP16-043")
    barato_opp = mk("UPA", "Barato", cost=5, power=5000)
    caro_opp = mk("UPB", "Caro", cost=6, power=6000)
    me = GameState(leader=mk("UPLDR", "Lider", card_type="LEADER"), turn=3)
    opp = GameState(leader=mk("UPOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [barato_opp, caro_opp]
    EffectExecutor(me, opp).execute(usopp, "on_ko")
    check("Execucao real: SO o Character de custo<=5 do oponente volta pra mao",
          barato_opp in opp.hand and caro_opp in opp.field_chars)


def test_opp_char_cost_eq_or_gte_op14_120() -> None:
    # Achado 17/07, OP14-120 (Crocodile): "Then, if your opponent has a
    # Character 1ith a cost of 0 or with a cost of 8 or more, draw 1
    # card." -- "1ith" e typo de "with". Existencia OR de dois limiares
    # desconectados (custo==0 OU custo>=8) no campo do OPONENTE, mesma
    # familia de don_on_field_zero_or_gte (bloco anterior). Condicao
    # inteira ausente, o draw disparava sempre.
    check("OP14-120 parseia opp_char_cost_eq_or_gte={eq:0, gte:8}",
          get_card_effects("OP14-120").get("on_play", {}).get("steps", [])[1]
          .get("conditions") == {"opp_char_cost_eq_or_gte": {"eq": 0, "gte": 8}})

    # Execucao real: oponente so tem Characters de custo 1-7 (nem 0 nem
    # >=8) -- draw NAO dispara.
    croc = real_card("OP14-120")
    me = GameState(leader=mk("CZLDR", "Lider", card_type="LEADER"), turn=3)
    me.hand = []
    opp = GameState(leader=mk("CZOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [mk("CZOA", "Meio", cost=4, power=4000)]
    EffectExecutor(me, opp).execute(croc, "on_play")
    check("Execucao real: oponente SO com custo 4 (nem 0 nem >=8) -- draw NAO dispara",
          len(me.hand) == 0)

    # Com um Character de custo 0 no campo do oponente, dispara.
    croc2 = real_card("OP14-120")
    me2 = GameState(leader=mk("CZLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.deck = [mk("CZDECK", "Compra", cost=1, power=1000)]
    me2.hand = []
    opp2 = GameState(leader=mk("CZOPP2", "Opp", card_type="LEADER"), turn=3)
    opp2.field_chars = [mk("CZOB", "Custo Zero", cost=0, power=0)]
    EffectExecutor(me2, opp2).execute(croc2, "on_play")
    check("Execucao real: oponente com Character de custo 0 -- draw dispara",
          len(me2.hand) == 1)


def test_play_card_power_range_prb02_010() -> None:
    # Achado 17/07, PRB02-010 (Charlotte Pudding): "play up to 1 'Big Mom
    # Pirates' type Character card with 6000 to 8000 power from your
    # hand." -- faixa de power (nao so power_lte/power_eq isolados) nunca
    # reconhecida em parse_play_generic, mesma convencao ja usada em
    # parse_play_from_trash/parse_look_at. Executor tambem nao repassava
    # power_gte pro play_card (GRUPO 2) -- corrigido junto.
    check("PRB02-010 parseia power_gte=6000 e power_lte=8000 no play_card",
          get_card_effects("PRB02-010").get("on_play", {}).get("steps", [])[1]
          .get("power_gte") == 6000 and get_card_effects("PRB02-010").get("on_play", {}).get("steps", [])[1]
          .get("power_lte") == 8000)

    pudding = real_card("PRB02-010")
    fraco = mk("PDA", "Fraco", power=4000, sub_types="Big Mom Pirates")
    na_faixa = mk("PDB", "Na Faixa", power=7000, sub_types="Big Mom Pirates")
    forte_demais = mk("PDC", "Forte Demais", power=9000, sub_types="Big Mom Pirates")
    me = GameState(leader=mk("PDLDR", "Lider Big Mom Pirates", card_type="LEADER",
                              sub_types="Big Mom Pirates"), turn=3, don_available=2)
    me.hand = [fraco, na_faixa, forte_demais]
    opp = GameState(leader=mk("PDOPP", "Opp", card_type="LEADER"), turn=3)
    opp.don_available = 6
    EffectExecutor(me, opp).execute(pudding, "on_play")
    check("Execucao real: SO a carta com power DENTRO da faixa 6000-8000 e jogada",
          na_faixa in me.field_chars and fraco in me.hand and forte_demais in me.hand)


def test_gain_life_own_field_cost_gte_power_gte_st13_001() -> None:
    # Achado 17/07, ST13-001 (Sabo): "You may add 1 of your Characters
    # with a cost of 3 or more and 7000 power or more to the top of your
    # Life cards face-up: [buff]." -- filtro COMBINADO custo+power no
    # Character movido pra vida (custo=fonte do 'pagamento'), nunca
    # extraido (so o power_eq exato de Kawamatsu ja existia). Executor
    # tambem nao filtrava por cost_gte/power_gte -- so power_eq.
    check("ST13-001 parseia cost_gte=3 e power_gte=7000 no gain_life",
          get_card_effects("ST13-001").get("activate_main", {}).get("steps", [])[1]
          .get("cost_gte") == 3 and get_card_effects("ST13-001").get("activate_main", {}).get("steps", [])[1]
          .get("power_gte") == 7000)

    sabo = real_card("ST13-001")
    sabo.don_attached = 1  # "[DON!! x1]" -- exige DON ANEXADO na carta, nao don_available
    fraco = mk("SBA", "Fraco", cost=2, power=3000)
    forte_mas_barato = mk("SBB", "Forte mas barato", cost=2, power=8000)
    elegivel = mk("SBC", "Elegivel", cost=4, power=7500)
    me = GameState(leader=sabo, turn=3)
    me.field_chars = [fraco, forte_mas_barato, elegivel]
    opp = GameState(leader=mk("SBOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(sabo, "activate_main")
    check("Execucao real: SO o Character com custo>=3 E power>=7000 vai pra vida",
          elegivel in me.life and elegivel not in me.field_chars
          and fraco in me.field_chars and forte_mas_barato in me.field_chars)


def test_pos_keyword_generico_e_ko_reativo_st10_006() -> None:
    # Achado 17/07: mecanismo "segmento solto APOS o reminder de
    # keyword" (ja existia so pra [Blocker], achado 01/07) GENERALIZADO
    # pra [Rush]/[Rush: Character]/[Double Attack]/[Banish]/[Unblockable]
    # -- 3 cartas confirmadas com o MESMO gap: P-039 (buff condicionado a
    # Life==0, apos [Banish]), OP01-067 (debuff_cost, apos [Banish]),
    # OP03-041 (trigger reativo de mill, apos [Rush]). ST10-006 (item
    # original do lote) revelou o gap mais serio: "[Rush] (...) [Once Per
    # Turn] When your opponent activates a [Blocker], K.O. up to 1 of
    # your opponent's Characters with 8000 power or less" -- alem de
    # generalizar a posicao, precisou de mecanismo NOVO (ko_on_opp_blocker)
    # com hook real em _execute_attack (mesma janela ja usada por
    # win_game_on_opp_blocker, achado 15/07).
    check("P-039 parseia buff_power condicionado a life_lte=0 (antes so keyword_banish)",
          get_card_effects("P-039").get("passive", {}).get("conditions") == {"life_lte": 0}
          and any(s.get("action") == "buff_power" for s in get_card_effects("P-039").get("passive", {}).get("steps", [])))
    check("OP01-067 parseia debuff_cost (antes so keyword_banish)",
          any(s.get("action") == "debuff_cost" for s in get_card_effects("OP01-067").get("passive", {}).get("steps", [])))
    check("OP03-041 parseia trash_from_deck_top count=7 na chave on_damage_to_life "
          "(reclassificado 17/07 -- ver test_reativo_mill_on_damage_to_life_familia_op03, "
          "antes ficava em 'passive' e disparava incondicionalmente a cada turno)",
          any(s.get("action") == "trash_from_deck_top" and s.get("count") == 7
              for s in get_card_effects("OP03-041").get("on_damage_to_life", {}).get("steps", [])))
    check("ST10-006 parseia acao NOVA ko_on_opp_blocker (nao mais um 'ko' incondicional morto)",
          get_card_effects("ST10-006").get("passive", {}).get("steps", [])[0] ==
          {"action": "ko_on_opp_blocker", "count": 1, "power_lte": 8000})
    check("OP09-118 continua so com 1 win_game_on_opp_blocker (sem duplicar apos a generalizacao)",
          sum(1 for s in get_card_effects("OP09-118").get("passive", {}).get("steps", [])
              if s.get("action") == "win_game_on_opp_blocker") == 1)

    # Execucao real de PONTA A PONTA (mesma janela de combate de
    # win_game_on_opp_blocker): ST10-006 ataca o Leader do oponente, que
    # bloqueia com um Character -- o K.O. reativo dispara contra OUTRO
    # Character do oponente (custo/power<=8000), nao contra o proprio
    # blocker necessariamente.
    atacante_char = real_card("ST10-006")  # power base 11000
    me = GameState(leader=mk("STLDR", "Lider", card_type="LEADER"), turn=3, don_available=5)
    me.field_chars = [atacante_char]
    opp = GameState(leader=mk("STOPPL", "Lider Opp", card_type="LEADER"), turn=3)
    # power > 11000 pra SOBREVIVER ao combate normal (isola o efeito do
    # K.O. reativo, que deve mirar OUTRO Character, nao o blocker).
    blocker_char = mk("STBLK", "Blocker", power=12000, cost=5)
    blocker_char.has_blocker = True
    alvo_ko = mk("STKO", "Alvo do KO", power=7000, cost=4)
    me.deck = []
    opp.field_chars = [blocker_char, alvo_ko]
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    eng = DecisionEngine(me, opp)
    match._execute_attack(atacante_char, "leader", None, me, opp, eng, verbose=False)
    check("Execucao real: oponente ativou Blocker -- o K.O. reativo trashou o alvo elegivel (power<=8000)",
          alvo_ko in opp.trash and alvo_ko not in opp.field_chars
          and blocker_char in opp.field_chars)
    check("Execucao real: once_per_turn -- a flag do Card fica marcada como usada",
          atacante_char.ko_on_opp_blocker_used_this_turn)


def test_reativo_mill_on_damage_to_life_familia_op03() -> None:
    # Achado 17/07 (reexame do que a tarefa original chamava de "gap em
    # apply_conditional_keyword_passives" -- essa premissa nao se sustentou:
    # apply_your_turn_buffs() ja executa buff_power/debuff_cost genericos de
    # 'passive' faz tempo; P-039 Bellamy ja funcionava). O bug REAL achado no
    # caminho: "When this Character's/Leader's attack deals damage to your
    # opponent's Life, you may trash N cards from the top of your deck"
    # (familia OP-03: Nami 040 lider, Usopp 041, Gaimon 043, Zeff 047,
    # Bell-mere 051) caia em result['passive'] e apply_your_turn_buffs()
    # disparava o mill INCONDICIONALMENTE a cada inicio do PROPRIO turno,
    # mesmo sem nenhum ataque ter ocorrido. Fix: chave nova 'on_damage_to_life'
    # (nao mais 'passive'), com hook dedicado em _execute_attack que so
    # dispara se o ataque REALMENTE conectar na vida do oponente, gated por
    # don_requirement do atacante. Gaimon tambem ganhou 'self_ko' correto
    # (antes vinha como costs=[trash_self], nunca pago -- apply_your_turn_
    # buffs nao paga costs de 'passive').
    check("OP03-041 (Usopp) parseia on_damage_to_life com don_requirement=1",
          get_card_effects("OP03-041").get("on_damage_to_life") ==
          {"steps": [{"action": "trash_from_deck_top", "count": 7}], "don_requirement": 1})
    check("OP03-043 (Gaimon) parseia self_ko=True no proprio step (nao mais costs=trash_self)",
          get_card_effects("OP03-043").get("on_damage_to_life", {}).get("steps", []) ==
          [{"action": "trash_from_deck_top", "count": 3, "self_ko": True}])
    check("OP03-047 (Zeff) mantem on_play intacto (bounce+mill) ao lado do novo on_damage_to_life",
          get_card_effects("OP03-047").get("on_play", {}).get("steps", []) ==
          [{"action": "bounce", "count": 1, "target": "opp_character", "cost_lte": 3},
           {"action": "trash_from_deck_top", "count": 2}])
    check("OP03-051 (Bell-mere) mantem on_ko intacto (mill 3) ao lado do novo on_damage_to_life",
          get_card_effects("OP03-051").get("on_ko", {}).get("steps", []) ==
          [{"action": "trash_from_deck_top", "count": 3}])

    # Execucao real de PONTA A PONTA: Usopp ataca o Leader do oponente
    # (sem bloqueio, sem counter -- poder de sobra), com 1 DON anexado
    # (satisfaz don_requirement=1). So deve milhar DEPOIS do dano conectar.
    usopp = real_card("OP03-041")
    usopp.don_attached = 1
    me = GameState(leader=mk("USLD", "Lider", card_type="LEADER"), turn=3, don_available=5)
    me.field_chars = [usopp]
    me.deck = [mk(f"UD{i}", f"Deck{i}") for i in range(10)]
    opp = GameState(leader=mk("USOPPL", "Lider Opp", card_type="LEADER", power=1000), turn=3)
    opp.life = [mk(f"UL{i}", f"Life{i}") for i in range(3)]
    match = OPTCGMatch((me.leader, []), (opp.leader, []))
    eng = DecisionEngine(me, opp)
    check("PRE-ataque: nenhum mill ocorreu so por existir em campo (apply_your_turn_buffs nao mais dispara)",
          len(me.trash) == 0 and len(me.deck) == 10)
    match._execute_attack(usopp, "leader", None, me, opp, eng, verbose=False)
    check("Execucao real: Usopp conectou na vida -- mill de 7 disparou (deck 10 -> 3, trash 0 -> 7)",
          len(me.trash) == 7 and len(me.deck) == 3)

    # Sem DON!! x1 anexado, o ataque conecta mas o mill NAO deve disparar
    # (don_requirement nao satisfeito).
    usopp2 = real_card("OP03-041")
    usopp2.don_attached = 0
    me2 = GameState(leader=mk("USLD2", "Lider2", card_type="LEADER"), turn=3, don_available=5)
    me2.field_chars = [usopp2]
    me2.deck = [mk(f"UD2{i}", f"Deck2{i}") for i in range(10)]
    opp2 = GameState(leader=mk("USOPPL2", "Lider Opp2", card_type="LEADER", power=1000), turn=3)
    opp2.life = [mk(f"UL2{i}", f"Life2{i}") for i in range(3)]
    match2 = OPTCGMatch((me2.leader, []), (opp2.leader, []))
    eng2 = DecisionEngine(me2, opp2)
    match2._execute_attack(usopp2, "leader", None, me2, opp2, eng2, verbose=False)
    check("Execucao real: SEM DON!! x1 anexado, o mill NAO dispara mesmo com dano conectado",
          len(me2.trash) == 0 and len(me2.deck) == 10)

    # Gaimon: mill 3 + self_ko (attacker sai do campo pro trash). Poder BASE
    # de Gaimon e 0 -- anexa DON suficiente pra garantir que o ataque conecte
    # contra um Leader de poder 0 (isola o efeito do mill, sem depender de
    # empate/counter).
    gaimon = real_card("OP03-043")
    gaimon.don_attached = 3
    me3 = GameState(leader=mk("GALD", "Lider3", card_type="LEADER"), turn=3, don_available=5)
    me3.field_chars = [gaimon]
    me3.deck = [mk(f"GD{i}", f"Deck3{i}") for i in range(10)]
    opp3 = GameState(leader=mk("GAOPPL", "Lider Opp3", card_type="LEADER", power=0), turn=3)
    opp3.life = [mk(f"GL{i}", f"Life3{i}") for i in range(3)]
    match3 = OPTCGMatch((me3.leader, []), (opp3.leader, []))
    eng3 = DecisionEngine(me3, opp3)
    match3._execute_attack(gaimon, "leader", None, me3, opp3, eng3, verbose=False)
    check("Execucao real: Gaimon conectou -- mill de 3 + self K.O. (sai do campo, vai pro trash)",
          len(me3.deck) == 7 and gaimon not in me3.field_chars and gaimon in me3.trash)


def test_op07_091_place_trash_matching_bottom_deck_e_buff_por_contagem_real() -> None:
    # Achado 17/07, OP07-091 (unica carta no banco): "[When Attacking]
    # Trash up to 1 of your opponent's Characters with a cost of 2 or
    # less. Then, place any number of Character cards with a cost of 4
    # or more from your trash at the bottom of your deck in any order.
    # This Character gains +1000 power during this turn for every 3
    # cards placed at the bottom of your deck." -- acao NOVA
    # place_trash_matching_bottom_deck (contagem VARIAVEL, move TODAS as
    # Characters elegiveis do proprio trash) + buff_power_per_count com
    # source NOVO placed_bottom_deck_this_effect, que le o RESULTADO REAL
    # do step anterior (via EffectExecutor._last_moved_count), nao um
    # estado estatico do tabuleiro como as demais fontes (trash/hand/etc).
    check("OP07-091 parseia place_trash_matching_bottom_deck cost_gte=4",
          any(s.get("action") == "place_trash_matching_bottom_deck" and s.get("cost_gte") == 4
              for s in get_card_effects("OP07-091").get("when_attacking", {}).get("steps", [])))
    check("OP07-091 parseia buff_power_per_count source=placed_bottom_deck_this_effect",
          any(s.get("action") == "buff_power_per_count"
              and s.get("source") == "placed_bottom_deck_this_effect"
              and s.get("count_per") == 3 and s.get("amount_per") == 1000
              for s in get_card_effects("OP07-091").get("when_attacking", {}).get("steps", [])))

    ataca = real_card("OP07-091")
    me = GameState(leader=mk("OPLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [ataca]
    # 4 Characters com custo>=4 no trash (elegiveis) + 2 com custo<4
    # (devem PERMANECER no trash) + 1 Event (nunca elegivel, so
    # Character conta). floor(4/3) = 1 -> +1000 power esperado.
    elegivel_a = mk("TRA", "Elegivel A", cost=4, power=4000)
    elegivel_b = mk("TRB", "Elegivel B", cost=5, power=5000)
    elegivel_c = mk("TRC", "Elegivel C", cost=4, power=4000)
    elegivel_d = mk("TRD", "Elegivel D", cost=6, power=6000)
    barato_a = mk("TRE", "Barato A", cost=2, power=2000)
    barato_b = mk("TRF", "Barato B", cost=3, power=3000)
    evento = mk("TRG", "Evento", cost=1, power=0, card_type="EVENT")
    me.trash = [elegivel_a, elegivel_b, elegivel_c, elegivel_d, barato_a, barato_b, evento]
    me.deck = []
    opp = GameState(leader=mk("OPOPPL", "Opp", card_type="LEADER"), turn=3)
    alvo_barato = mk("OPX", "Alvo Barato", cost=1, power=1000)
    opp.field_chars = [alvo_barato]
    EffectExecutor(me, opp).execute(ataca, "when_attacking")
    check("Execucao real: custo trashou o Character barato do oponente (cost<=2)",
          alvo_barato in opp.trash and alvo_barato not in opp.field_chars)
    check("Execucao real: as 4 Characters com custo>=4 foram pro FUNDO do deck (inicio da lista)",
          len(me.deck) == 4
          and all(c in me.deck for c in (elegivel_a, elegivel_b, elegivel_c, elegivel_d))
          and all(c not in me.trash for c in (elegivel_a, elegivel_b, elegivel_c, elegivel_d)))
    check("Execucao real: Characters baratas e o Event PERMANECERAM no trash (nao elegiveis)",
          barato_a in me.trash and barato_b in me.trash and evento in me.trash)
    check("Execucao real: buff = floor(4/3)*1000 = 1000 (contagem REAL movida, nao estado estatico)",
          ataca.power_buff == 1000)


def test_lote_11_itens_falso_positivo_op09_118_e_custo_don_ativo() -> None:
    # Achado 17/07: OP09-118 (win_game_on_opp_blocker) e FALSO-POSITIVO --
    # o engine ja checa p.life_count()==0 or opp.life_count()==0 em
    # _execute_attack ANTES do loop (hardcoded pro unico caso), entao a
    # condicao "0 Life cards" nunca precisou aparecer no JSON parseado.
    check("OP09-118 permanece so com win_game_on_opp_blocker (sem condicao no JSON -- correto, hardcoded no engine)",
          get_card_effects("OP09-118").get("passive", {}).get("steps", [{}])[0] ==
          {"action": "win_game_on_opp_blocker"})

    # EB02-061/OP16-060: custo NOVO return_active_don_to_don_deck (exige
    # DON ATIVO especificamente, distinto de don_minus que PREFERE DON
    # ja restado).
    check("EB02-061 parseia custo return_active_don_to_don_deck count=2",
          get_card_effects("EB02-061").get("when_attacking", {}).get("costs", []) ==
          [{"type": "return_active_don_to_don_deck", "count": 2}])
    check("OP16-060 parseia custo return_active_don_to_don_deck count=8",
          get_card_effects("OP16-060").get("activate_main", {}).get("costs", []) ==
          [{"type": "return_active_don_to_don_deck", "count": 8}])

    luffy = real_card("EB02-061")
    me = GameState(leader=mk("LFLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [luffy]
    me.don_available = 1
    opp = GameState(leader=mk("LFOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(luffy, "when_attacking")
    check("Execucao real: SEM 2 DON ativos suficientes, custo NAO e pago (efeito nao dispara)",
          me.don_available == 1 and not luffy.rested)

    luffy2 = real_card("EB02-061")
    me2 = GameState(leader=mk("LFLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [luffy2]
    me2.don_available = 2
    me2.don_deck = 5
    opp2 = GameState(leader=mk("LFOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(luffy2, "when_attacking")
    check("Execucao real: COM 2 DON ativos, custo pago (don_available->0, don_deck->7), Set Active dispara",
          me2.don_available == 0 and me2.don_deck == 7)


def test_lote_11_itens_hand_top_deck_familia() -> None:
    # ST17-005 (custo opcional) + EB03-034/ST17-001 (step obrigatorio):
    # "place N cards from your hand at the top of your deck" -- TOPO
    # (fim da lista), distinto do hand_to_deck existente (fundo).
    check("ST17-005 parseia custo place_hand_top_deck count=1",
          get_card_effects("ST17-005").get("activate_main", {}).get("costs", []) ==
          [{"type": "place_hand_top_deck", "count": 1}])
    check("EB03-034 parseia step hand_to_deck_top count=1 em on_play",
          any(s.get("action") == "hand_to_deck_top" and s.get("count") == 1
              for s in get_card_effects("EB03-034").get("on_play", {}).get("steps", [])))
    check("ST17-001 parseia step hand_to_deck_top DENTRO de on_match_steps (reveal condicional)",
          any(s.get("action") == "hand_to_deck_top"
              for step in get_card_effects("ST17-001").get("on_play", {}).get("steps", [])
              for s in step.get("on_match_steps", [])))

    teach = real_card("ST17-005")
    carta_a = mk("HTA", "Carta A", cost=2, power=2000)
    carta_b = mk("HTB", "Carta B", cost=1, power=1000)
    me = GameState(leader=mk("TCHLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [teach]
    me.hand = [carta_a, carta_b]
    me.deck = []
    opp = GameState(leader=mk("TCHOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(teach, "activate_main")
    check("Execucao real: 1 carta da mao foi pro TOPO do deck (fim da lista, nao inicio)",
          len(me.deck) == 1 and len(me.hand) == 1
          and me.deck[-1] is (carta_b if carta_b not in me.hand else carta_a))


def test_lote_11_itens_eb01_001_e_op12_098_cost_gte_type_e_selected() -> None:
    # EB01-001 (Oden): condicao "Land of Wano type Character custo>=5"
    # -- variante por TIPO da ja existente other_char_cost_gte (so
    # existia por power antes).
    check("EB01-001 parseia other_char_cost_gte=5 + other_char_cost_gte_type=land of wano",
          get_card_effects("EB01-001").get("when_attacking", {}).get("conditions", {}) ==
          {"other_char_cost_gte": 5, "other_char_cost_gte_type": "land of wano"})

    oden = real_card("EB01-001")
    fraco = mk("ODW", "Fraco", cost=3, power=3000, sub_types="Land of Wano")
    forte = mk("ODS", "Forte", cost=5, power=5000, sub_types="Land of Wano")
    me = GameState(leader=oden, turn=3, don_available=5)
    oden.don_attached = 1
    me.field_chars = [fraco, forte]
    opp = GameState(leader=mk("ODOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(oden, "when_attacking")
    check("Execucao real: COM Land of Wano custo>=5 no campo, Leader ganha +1000 power",
          oden.power_buff == 1000)

    oden2 = real_card("EB01-001")
    me2 = GameState(leader=oden2, turn=3, don_available=5)
    oden2.don_attached = 1
    me2.field_chars = [mk("ODW2", "Fraco2", cost=3, power=3000, sub_types="Land of Wano")]
    opp2 = GameState(leader=mk("ODOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(oden2, "when_attacking")
    check("Execucao real: SO Land of Wano custo<5 no campo, Leader NAO ganha o buff",
          oden2.power_buff == 0)

    # OP12-098: mesma familia de EB03-020/OP01-029/etc -- 2o buff_power
    # de um Counter (apos 'Then, if [cond]') deve mirar 'selected' (a
    # MESMA carta escolhida pelo 1o buff leader_or_character), nao 'self'
    # (o proprio Event, que nao luta). 10+ cartas descobertas pela mesma
    # generalizacao.
    check("OP12-098 parseia 2o buff_power com target=selected (nao mais self)",
          get_card_effects("OP12-098").get("counter", {}).get("steps", [{}, {}])[1].get("target") == "selected")

    rayleigh_ally = mk("RLA", "Aliado Forte", cost=8, power=8000, sub_types="Revolutionary Army")
    me3 = GameState(leader=mk("RLLDR", "Lider", card_type="LEADER"), turn=3)
    me3.field_chars = [rayleigh_ally]
    opp3 = GameState(leader=mk("RLOPP", "Opp", card_type="LEADER"), turn=3)
    evento = real_card("OP12-098")
    EffectExecutor(me3, opp3).execute(evento, "counter")
    check("Execucao real: com condicao satisfeita (Revolutionary Army custo>=8), o ALIADO ganha +4000 total (2000+2000), nao o Event",
          rayleigh_ally.power_buff == 4000)


def test_lote_11_itens_eb03_009_filter_no_effect_bug_e_ordem_target() -> None:
    # EB03-009 (Makino): custo "rest this Character" contaminava a
    # deteccao de alvo do buff SEGUINTE ('of your Characters' virava
    # 'self' por causa do 'this Character' do custo aparecer ANTES na
    # mesma janela) -- reordenado pra 'of your characters' ganhar
    # prioridade. Tambem achado e corrigido: filter_no_effect SEMPRE
    # retornava True (bug pre-existente, get_card_effects() ja desempacota
    # o dict, .get('effects') nele sempre None).
    check("EB03-009 parseia target=own_character com filter_no_effect=True",
          get_card_effects("EB03-009").get("activate_main", {}).get("steps", [{}])[0] ==
          {"action": "buff_power", "amount": 2000, "target": "own_character",
           "duration": "this_turn", "filter_no_effect": True})

    makino = real_card("EB03-009")
    com_efeito = real_card("OP07-091")  # tem on_play/when_attacking real
    sem_efeito = mk("SEMEF", "Sem Efeito", cost=3, power=3000)
    me = GameState(leader=mk("MKLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [makino, com_efeito, sem_efeito]
    opp = GameState(leader=mk("MKOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(makino, "activate_main")
    check("Execucao real: filter_no_effect escolhe a carta SEM efeito parseado (bug antigo aceitava QUALQUER carta)",
          sem_efeito.power_buff == 2000 and com_efeito.power_buff == 0 and makino.power_buff == 0)


def test_lote_11_itens_eb02_056_opp_chars_lte() -> None:
    # EB02-056 (Vegapunk): "...and if your opponent has 2 or less
    # Characters, trash 1 card from your hand" -- condicao NOVA
    # opp_chars_lte (so existia opp_chars_gte), extraida via split
    # NOVO "and if" (sem ponto antes, distinto do split_then_if
    # existente que exige ponto).
    check("EB02-056 anexa conditions opp_chars_lte=2 SO no step trash_from_hand (nao nos anteriores)",
          get_card_effects("EB02-056").get("on_play", {}).get("steps", [])[-1] ==
          {"action": "trash_from_hand", "count": 1, "conditions": {"opp_chars_lte": 2}})

    vega = real_card("EB02-056")
    extra = mk("VGX", "Extra", cost=1, power=1000)
    me = GameState(leader=mk("VGLDR", "Lider", card_type="LEADER"), turn=3, don_available=10)
    me.field_chars = [vega]
    me.hand = [extra]
    me.deck = [mk(f"VGD{i}", f"Deck{i}") for i in range(5)]
    opp = GameState(leader=mk("VGOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = []
    EffectExecutor(me, opp).execute(vega, "on_play")
    check("Execucao real: oponente com 0 Characters (<=2) -- trash_from_hand dispara",
          extra not in me.hand)

    vega2 = real_card("EB02-056")
    extra2 = mk("VGX2", "Extra", cost=1, power=1000)
    me2 = GameState(leader=mk("VGLDR2", "Lider", card_type="LEADER"), turn=3, don_available=10)
    me2.field_chars = [vega2]
    me2.hand = [extra2]
    me2.deck = [mk(f"VGD2{i}", f"Deck2{i}") for i in range(5)]
    opp2 = GameState(leader=mk("VGOPP2", "Opp", card_type="LEADER"), turn=3)
    opp2.field_chars = [mk("VGO1", "O1"), mk("VGO2", "O2"), mk("VGO3", "O3")]
    EffectExecutor(me2, opp2).execute(vega2, "on_play")
    check("Execucao real: oponente com 3 Characters (>2) -- trash_from_hand NAO dispara",
          extra2 in me2.hand)


def test_lote_11_itens_eb03_006_dado_bruto_e_once_per_turn_scoping() -> None:
    # EB03-006 (Nami): erro de DADO BRUTO confirmado via WebSearch contra
    # o texto oficial -- "-5000 power" (sinal de menos perdido no scrape
    # do cards_rows.csv), nao um bug de parser. Cost sign so conta com
    # texto explicito (regra do projeto) -- o sinal foi CONFIRMADO
    # existente no card oficial antes de adicionar.
    check("EB03-006 parseia custo debuff_power_self (com o sinal restaurado no CSV)",
          get_card_effects("EB03-006").get("on_play", {}).get("costs", []) ==
          [{"type": "debuff_power_self", "amount": 5000, "optional": True, "target": "leader"}])

    # Bug SISTEMICO achado via EB03-006: '[once per turn]' era checado
    # contra o TEXTO INTEIRO da carta (t_low), nao contra o bloco do
    # trigger atual -- qualquer carta com 2+ blocos onde SO UM tem a tag
    # contaminava TODOS com once_per_turn=True. 65+ cartas confirmadas
    # afetadas (amostra abaixo).
    check("EB03-006 on_play NAO tem once_per_turn (tag pertence so ao activate_main)",
          "once_per_turn" not in get_card_effects("EB03-006").get("on_play", {}))
    check("EB03-006 activate_main mantem once_per_turn=True (tag realmente presente ali)",
          get_card_effects("EB03-006").get("activate_main", {}).get("once_per_turn") is True)
    check("EB03-026 (amostra adicional): on_play NAO tem once_per_turn, activate_main SIM",
          "once_per_turn" not in get_card_effects("EB03-026").get("on_play", {})
          and get_card_effects("EB03-026").get("activate_main", {}).get("once_per_turn") is True)


def test_lote_11_itens_op14_009_swap_leader_e_character() -> None:
    # OP14-009 (Trafalgar Law): custo trash 2 cartas da mao + mecanica
    # NOVA swap_base_power(target='leader_and_own_character') -- troca o
    # power BASE entre o Leader e o melhor Character proprio.
    check("OP14-009 parseia custo trash_from_hand count=2 + swap_base_power leader_and_own_character",
          get_card_effects("OP14-009").get("on_opp_attack", {}).get("costs", []) ==
          [{"type": "trash_from_hand", "count": 2}]
          and get_card_effects("OP14-009").get("on_opp_attack", {}).get("steps", [{}])[0] ==
          {"action": "swap_base_power", "target": "leader_and_own_character", "duration": "battle_only"})

    law = real_card("OP14-009")  # power 10000 + bonus de [Rush] nativo no board_value
    # "aliado" precisa superar o board_value do PROPRIO Law (nao excluido
    # da selecao pelo texto, e Law tem +4 de bonus por [Rush] nativo) pra
    # tornar o teste deterministico -- power bem acima do de Law.
    aliado = mk("LWA", "Aliado", cost=10, power=20000)
    me = GameState(leader=mk("LWLDR", "Lider", card_type="LEADER", power=5000), turn=3)
    me.field_chars = [law, aliado]
    me.hand = [mk("LWH1", "H1"), mk("LWH2", "H2")]
    opp = GameState(leader=mk("LWOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(law, "on_opp_attack")
    check("Execucao real: custo pago (2 cartas trashed da mao)",
          len(me.hand) == 0)
    check("Execucao real: power BASE trocado entre Lider (5000->20000) e o Character de maior board_value (20000->5000)",
          me.leader.base_power_override == 20000 and aliado.base_power_override == 5000)


def test_lote_11_itens_op12_016_familia_rayleigh_e_keyword_blocker_guard() -> None:
    # OP12-016 (evento "To Never Doubt"): custo give_don_to_named NOVO
    # (familia de 4: EB04-009/OP12-016/OP12-017/OP12-019, "you may give
    # N active DON!! cards to 1 of your [Silvers Rayleigh]: efeito") +
    # efeito NOVO select_grant_unblockable_turn(target='don_recipient')
    # -- alvo = quem recebeu o DON!!, sem precisar de step de selecao
    # proprio no texto.
    check("OP12-016 parseia custo give_don_to_named count=2 target_name=silvers rayleigh",
          get_card_effects("OP12-016").get("main", {}).get("costs", []) ==
          [{"type": "give_don_to_named", "count": 2, "target_name": "silvers rayleigh"}])
    check("OP12-016 parseia efeito select_grant_unblockable_turn target=don_recipient",
          get_card_effects("OP12-016").get("main", {}).get("steps", []) ==
          [{"action": "select_grant_unblockable_turn", "target": "don_recipient", "target_name": "silvers rayleigh"}])
    check("EB04-009/OP12-017/OP12-019 (mesma familia) tambem parseiam o custo give_don_to_named",
          all(get_card_effects(c).get("main", {}).get("costs", []) ==
              [{"type": "give_don_to_named", "count": 1, "target_name": "silvers rayleigh"}]
              for c in ("EB04-009", "OP12-017", "OP12-019")))

    rayleigh = mk("RAYL", "Silvers Rayleigh", cost=6, power=6000)
    evento = real_card("OP12-016")
    me = GameState(leader=mk("RYLDR", "Lider", card_type="LEADER"), turn=3, don_available=3)
    me.field_chars = [rayleigh]
    opp = GameState(leader=mk("RYOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(evento, "main")
    check("Execucao real: custo pago (2 DON ativos -> Rayleigh, banco 3->1) e Rayleigh ganha Unblockable este turno",
          me.don_available == 1 and rayleigh.don_attached == 2 and rayleigh.unblockable_this_turn)

    # Bug SISTEMICO achado via OP12-016: guarda de 'your opponent
    # activates [Blocker]' (achado 15/07) nao tolerava a NEGACAO "cannot
    # activate"/"can't activate" -- 9+ cartas ganhavam Blocker NATIVO por
    # engano (self-grant), duplicado com o efeito de unblockable JA
    # correto (lock_opp_blocker_battle/select_grant_unblockable_turn).
    check("OP12-016 NAO tem mais keyword_blocker bogus em passive",
          "passive" not in get_card_effects("OP12-016")
          or not any(s.get("action") == "keyword_blocker"
                     for s in get_card_effects("OP12-016").get("passive", {}).get("steps", [])))
    for c in ("OP05-016", "OP06-055", "OP08-111", "OP12-077", "ST01-016", "ST21-003", "OP13-057"):
        check(f"{c} (amostra guarda cannot-activate): sem keyword_blocker bogus",
              not any(s.get("action") == "keyword_blocker"
                      for s in get_card_effects(c).get("passive", {}).get("steps", [])))
    check("ST01-012 mantem keyword_rush real (guarda nao filtrou keyword LEGITIMA)",
          any(s.get("action") == "keyword_rush"
              for s in get_card_effects("ST01-012").get("passive", {}).get("steps", [])))


def test_lote_11_itens_op16_118_counter_na_mao() -> None:
    # OP16-118 (Portgas Ace): estatica NOVA set_hand_counter_by_power --
    # "The counter of all of your Character cards with 8000 power in
    # your hand becomes +2000." Engine consome via effective_counter()
    # nos pontos DECISIVOS (counter_in_hand/pick_counters), escopo
    # deliberadamente estreito (nao em toda heuristica de scoring
    # secundaria que le card.counter direto).
    check("OP16-118 parseia passive set_hand_counter_by_power power_eq=8000 to_value=2000",
          get_card_effects("OP16-118").get("passive", {}).get("steps", [{}])[0] ==
          {"action": "set_hand_counter_by_power", "power_eq": 8000, "to_value": 2000})

    ace = real_card("OP16-118")
    alvo_8000 = mk("PW8", "Alvo 8000", cost=8, power=8000)
    alvo_8000.data = alvo_8000.data.__class__(**{**alvo_8000.data.__dict__, "counter": 1000})
    outro_power = mk("PW7", "Outro Power", cost=7, power=7000)
    outro_power.data = outro_power.data.__class__(**{**outro_power.data.__dict__, "counter": 2000})
    me = GameState(leader=mk("ACLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [ace]
    me.hand = [alvo_8000, outro_power]
    check("effective_counter: carta com power==8000 vira 2000 (estatica ativa, Ace no campo)",
          effective_counter(alvo_8000, me) == 2000)
    check("effective_counter: carta com OUTRO power mantem o counter IMPRESSO (2000, sem alteracao)",
          effective_counter(outro_power, me) == 2000)
    check("counter_in_hand soma os valores EFETIVOS (2000 + 2000 = 4000)",
          me.counter_in_hand() == 4000)

    me_sem_ace = GameState(leader=mk("ACLDR2", "Lider2", card_type="LEADER"), turn=3)
    me_sem_ace.hand = [alvo_8000]
    check("effective_counter: SEM Ace no campo, carta com power==8000 mantem o counter IMPRESSO (1000)",
          effective_counter(alvo_8000, me_sem_ace) == 1000)


def test_lote_9_itens_st22_005_custo_composto_e_eb02_002_select_exclude() -> None:
    # ST22-005 (Kouzuki Oden): custo COMPOSTO "rest 3 DON e devolver 1
    # Character (exceto esta) pra mao" -- so o rest_don existia antes.
    check("ST22-005 parseia os 2 custos (rest_don=3 + return_own_character_to_hand exclude_self)",
          get_card_effects("ST22-005").get("activate_main", {}).get("costs", []) ==
          [{"type": "rest_don", "count": 3},
           {"type": "return_own_character_to_hand", "count": 1, "exclude_self": True}])

    oden = real_card("ST22-005")
    oden.rested = True
    aliado = mk("ODA", "Aliado Fraco", cost=2, power=2000)
    me = GameState(leader=mk("ODLDR", "Lider", card_type="LEADER"), turn=3, don_available=3)
    me.field_chars = [oden, aliado]
    opp = GameState(leader=mk("ODOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(oden, "activate_main")
    check("Execucao real: os 2 custos pagos (3 DON restados, aliado devolvido pra mao) -- Oden fica ativo",
          not oden.rested and aliado in me.hand and aliado not in me.field_chars
          and me.don_available == 0 and me.don_rested == 3)

    # EB02-002 (Sabo): "other than [Nome]" quebrava select_filtered
    # (virava auto-buff em vez de selecao filtrada com exclusao).
    check("EB02-002 parseia select_filtered com filter_type=revolutionary army + exclude=sabo",
          get_card_effects("EB02-002").get("activate_main", {}).get("steps", [{}])[0] ==
          {"action": "buff_power", "amount": 2000, "target": "select_filtered",
           "duration": "this_turn", "count": 1, "filter_type": "revolutionary army", "exclude": "sabo"})

    sabo = real_card("EB02-002")
    ra_aliado = mk("RAA", "RA Aliado", cost=3, power=3000, sub_types="Revolutionary Army")
    me2 = GameState(leader=mk("SBLDR", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [sabo, ra_aliado]
    opp2 = GameState(leader=mk("SBOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(sabo, "activate_main")
    check("Execucao real: o ALIADO Revolutionary Army ganha +2000 (nao o proprio Sabo, excluido por nome)",
          ra_aliado.power_buff == 2000 and sabo.power_buff == 0)


def test_lote_9_itens_eb03_050_eb04_024_selecao_double_attack_e_unblockable() -> None:
    # EB03-050 (Conis)/OP04-115: gain_double_attack (auto-concessao) devia
    # ser selecao filtrada (select_grant_double_attack) -- mesma classe
    # de bug ja corrigida pra Blocker/Rush.
    check("EB03-050 parseia select_grant_double_attack filter_type=sky island",
          get_card_effects("EB03-050").get("on_play", {}).get("steps", [{}])[0] ==
          {"action": "select_grant_double_attack", "count": 1, "filter_type": "sky island", "duration": "this_turn"})

    conis = real_card("EB03-050")
    sky_ally = mk("SKA", "Sky Ally", cost=3, power=3000, sub_types="Sky Island")
    me = GameState(leader=mk("CNLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [conis, sky_ally]
    opp = GameState(leader=mk("CNOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(conis, "on_play")
    check("Execucao real: o ALIADO Sky Island ganha Double Attack este turno (nao a propria Conis)",
          sky_ally.double_attack_this_turn and not conis.double_attack_this_turn)

    # EB04-024: gain_unblockable (auto-concessao) devia ser
    # select_grant_unblockable_turn (mecanismo JA existente, so faltava a
    # forma DIRETA da keyword "gains [Unblockable]" ser reconhecida).
    check("EB04-024 parseia select_grant_unblockable_turn filter_type=alabasta (sem duplicar gain_unblockable)",
          get_card_effects("EB04-024").get("activate_main", {}).get("steps", []) ==
          [{"action": "select_grant_unblockable_turn", "count": 1, "filter_type": "alabasta"}])

    doflamingo = real_card("EB04-024")  # ativo -- precisa poder pagar rest_self como custo
    alabasta_ally = mk("ALA", "Alabasta Ally", cost=3, power=3000, sub_types="Alabasta")
    me2 = GameState(leader=mk("DFLDR", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [doflamingo, alabasta_ally]
    me2.hand = [mk("DFH1", "H1")]
    opp2 = GameState(leader=mk("DFOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(doflamingo, "activate_main")
    check("Execucao real: o ALIADO Alabasta ganha Unblockable este turno (custos pagos: rest_self + trash 1 da mao)",
          alabasta_ally.unblockable_this_turn and not doflamingo.unblockable_this_turn
          and doflamingo.rested and len(me2.hand) == 0)


def test_lote_9_itens_eb01_053_count2_e_eb03_061_alvo_misto() -> None:
    # EB01-053 (Gastino): "up to a total of 2" no debuff
    # opp_leader_or_character virava count=1 implicito.
    check("EB01-053 parseia count=2 no debuff_power opp_leader_or_character",
          get_card_effects("EB01-053").get("trigger", {}).get("steps", [{}])[0] ==
          {"action": "debuff_power", "amount": 3000, "target": "opp_leader_or_character",
           "duration": "this_turn", "count": 2})

    gastino = real_card("EB01-053")
    me = GameState(leader=mk("GSLDR", "Lider", card_type="LEADER"), turn=3)
    opp = GameState(leader=mk("GSOPP", "Opp", card_type="LEADER"), turn=3, don_available=0)
    opp.field_chars = [mk("GSO1", "O1", power=5000), mk("GSO2", "O2", power=4000)]
    EffectExecutor(me, opp).execute(gastino, "trigger")
    check("Execucao real: os 2 alvos mais fortes (Leader do oponente + O1) recebem -3000, nao so 1",
          opp.leader.power_buff == -3000 and opp.field_chars[0].power_buff == -3000
          and opp.field_chars[1].power_buff == 0)

    # EB03-061 (Uta): "rest DON!! cards OR Characters" (DON mencionado
    # PRIMEIRO) -- so a alternativa DON!! era capturada antes.
    step_061 = get_card_effects("EB03-061").get("activate_main", {}).get("steps", [{}])[0]
    check("EB03-061 parseia rest_opp_character cost_lte=4 e preserva alternativa DON",
          step_061.get("action") == "rest_opp_character"
          and step_061.get("count") == 1 and step_061.get("cost_lte") == 4
          and step_061.get("or_rest_opp_don") is True)
    # Generalizacao colateral: mesma ordem invertida em mais 3 cartas.
    for c, cost_lte in (("OP06-020", 3), ("OP09-036", 6), ("ST26-002", 1)):
        family_step = (get_card_effects(c)
                       .get("on_play" if c != "OP06-020" else "activate_main", {})
                       .get("steps", [{}])[0])
        check(f"{c} (mesma familia): Character cost_lte={cost_lte} OU DON",
              family_step.get("action") == "rest_opp_character"
              and family_step.get("count") == 1
              and family_step.get("cost_lte") == cost_lte
              and family_step.get("or_rest_opp_don") is True)


def test_lote_9_itens_eb03_049_segunda_play_card_e_eb02_028_play_from_hand() -> None:
    # EB03-049: 2 clausulas de play_card encadeadas ("...cost of 6 or
    # less AND up to 1 ... cost of 4 or less from your hand or trash") --
    # so a 1a era capturada.
    steps_049 = get_card_effects("EB03-049").get("main", {}).get("steps", [])
    check("EB03-049 parseia 2 play_card (cost_lte=6 e cost_lte=4, mesmo filtro/fonte)",
          len(steps_049) == 2
          and steps_049[0]["cost_lte"] == 6 and steps_049[1]["cost_lte"] == 4
          and steps_049[0]["filter_type"] == steps_049[1]["filter_type"] == "thriller bark pirates")

    perona_card = real_card("EB03-049")
    barco6 = mk("TB6", "Barco 6", cost=6, power=6000, sub_types="Thriller Bark Pirates")
    barco4 = mk("TB4", "Barco 4", cost=4, power=4000, sub_types="Thriller Bark Pirates")
    me = GameState(leader=mk("PRLDR", "Perona", card_type="LEADER"), turn=3, don_available=10)
    me.hand = [perona_card, barco6, barco4]
    me.trash = []
    opp = GameState(leader=mk("PROPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(perona_card, "main")
    check("Execucao real: AMBAS as Thriller Bark Pirates (custo 6 e custo 4) sao jogadas",
          barco6 in me.field_chars and barco4 in me.field_chars)

    # EB02-028 (Portgas Ace): clausula "play up to 1 Character card com
    # custo 2 da MAO, restado" -- step inteiro ausente (distinto do
    # play_from_deck ja coberto).
    check("EB02-028 parseia play_card cost_eq=2 enters_rested=True (alem do look_top_deck/add_to_hand ja existentes)",
          get_card_effects("EB02-028").get("on_play", {}).get("steps", [])[-1] ==
          {"action": "play_card", "count": 1, "cost_eq": 2, "enters_rested": True})

    ace_card = real_card("EB02-028")
    ace_card.data = ace_card.data.__class__(**{**ace_card.data.__dict__})
    custo2 = mk("C2A", "Custo 2 A", cost=2, power=2000)
    me2 = GameState(leader=mk("ACLDR3", "Whitebeard Leader", card_type="LEADER", sub_types="Whitebeard Pirates"), turn=3)
    me2.hand = [ace_card, custo2]
    me2.deck = [mk(f"D{i}", f"Deck{i}", cost=5) for i in range(5)]
    opp2 = GameState(leader=mk("ACOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(ace_card, "on_play")
    check("Execucao real: a carta de custo 2 da MAO entra em campo RESTADA",
          custo2 in me2.field_chars and custo2.rested)


def test_lote_9_itens_eb02_007_leader_or_character_count3() -> None:
    # EB02-007: "up to a total of 3 of your Leader and Character cards
    # gain +1000 power" -- conectivo "and" (nao "or") + count=3, ambos
    # ausentes antes (virava buff incondicional so no Leader).
    check("EB02-007 parseia buff_power target=leader_or_character count=3",
          get_card_effects("EB02-007").get("main", {}).get("steps", [{}])[1] ==
          {"action": "buff_power", "amount": 1000, "target": "leader_or_character",
           "duration": "this_turn", "count": 3})

    blizzard = real_card("EB02-007")
    forte = mk("BZF", "Forte", cost=8, power=8000)
    medio = mk("BZM", "Medio", cost=5, power=5000)
    fraco = mk("BZW", "Fraco", cost=2, power=2000)
    me = GameState(leader=mk("BZLDR", "Lider", card_type="LEADER", power=1000), turn=3)
    me.field_chars = [forte, medio, fraco]
    opp = GameState(leader=mk("BZOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [mk("BZO1", "O1", power=100)]
    EffectExecutor(me, opp).execute(blizzard, "main")
    check("Execucao real: os 3 mais fortes (Forte/Medio/Fraco, o Lider fica de fora) ganham +1000 cada",
          forte.power_buff == 1000 and medio.power_buff == 1000 and fraco.power_buff == 1000
          and me.leader.power_buff == 0)


def test_lote_9_itens_eb04_056_condicao_composta_bonney_e_vida() -> None:
    # EB04-056 (Pacifista): "If you have [Jewelry Bonney] and you have 0
    # Life cards, gains [Blocker]" -- condicao INTEIRA ausente (ficou
    # deliberadamente na fila desde 15/07 ate essa familia composta ser
    # corrigida por inteiro).
    check("EB04-056 parseia has_named_character=jewelry bonney + life_lte=0",
          get_card_effects("EB04-056").get("passive", {}).get("conditions", {}) ==
          {"has_named_character": "jewelry bonney", "life_lte": 0})

    pacifista = real_card("EB04-056")
    bonney = mk("BNY", "Jewelry Bonney", cost=5, power=5000)
    me = GameState(leader=mk("PFLDR", "Lider", card_type="LEADER"), turn=3)
    me.field_chars = [pacifista, bonney]
    me.life = []
    opp = GameState(leader=mk("PFOPP", "Opp", card_type="LEADER"), turn=3)
    log = EffectExecutor(me, opp).execute(pacifista, "passive")
    check("Execucao real: COM Bonney no campo E 0 Life cards, Pacifista ganha Blocker",
          "Blocker" in "".join(log))

    pacifista2 = real_card("EB04-056")
    me2 = GameState(leader=mk("PFLDR2", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [pacifista2, mk("BNY2", "Jewelry Bonney", cost=5, power=5000)]
    me2.life = [mk("LF1", "Life 1")]
    opp2 = GameState(leader=mk("PFOPP2", "Opp", card_type="LEADER"), turn=3)
    log2 = EffectExecutor(me2, opp2).execute(pacifista2, "passive")
    check("Execucao real: COM Bonney mas SEM 0 Life cards, Pacifista NAO ganha Blocker",
          not any("Blocker" in s for s in log2))


def test_don_n_parenteses_explicativo_e_life_area_cost() -> None:
    # Custo "DON!! N (explicacao entre parenteses): efeito" -- a tolerancia
    # existente exigia ':' colado no numero, sem parenteses no meio.
    # Achado 17/07, 19 cartas reais no banco (amostra abaixo).
    check("EB03-036 parseia custo don_minus count=1 (parenteses explicativo tolerado)",
          get_card_effects("EB03-036").get("on_play", {}).get("costs", []) ==
          [{"type": "don_minus", "count": 1, "optional": True}])
    check("OP08-064 (amostra) tambem parseia don_minus count=1",
          get_card_effects("OP08-064").get("activate_main", {}).get("costs", []) ==
          [{"type": "don_minus", "count": 1, "optional": True}])
    check("OP08-057 (amostra, bloco 'choice') tambem parseia don_minus count=2",
          get_card_effects("OP08-057").get("activate_main", {}).get("costs", []) ==
          [{"type": "don_minus", "count": 2, "optional": True}])

    baby5 = real_card("EB03-036")
    alvo1 = mk("BB1", "Alvo 1", cost=3, power=3000)
    alvo2 = mk("BB2", "Alvo 2", cost=2, power=2000)
    me = GameState(leader=mk("BBLDR", "Lider", card_type="LEADER"), turn=3, don_available=1)
    me.field_chars = [baby5]
    opp = GameState(leader=mk("BBOPP", "Opp", card_type="LEADER"), turn=3)
    opp.field_chars = [alvo1, alvo2]
    EffectExecutor(me, opp).execute(baby5, "on_play")
    check("Execucao real: custo don_minus pago (1 DON devolvido ao deck) e K.O. dispara nos 2 alvos elegiveis",
          me.don_deck == 11 and alvo1 not in opp.field_chars and alvo2 not in opp.field_chars)

    # OP01-008 (Cavendish)/OP01-013 (Sanji): custo "add N cards from your
    # Life area to your hand" (redacao sem topo/fundo explicito) --
    # totalmente ausente antes.
    check("OP01-008 parseia custo life_to_hand count=1 (sem source explicito -- default life_top)",
          get_card_effects("OP01-008").get("on_play", {}).get("costs", []) == [{"type": "life_to_hand", "count": 1}])
    check("OP01-013 (mesma familia) tambem parseia",
          get_card_effects("OP01-013").get("activate_main", {}).get("costs", []) == [{"type": "life_to_hand", "count": 1}])

    cavendish = real_card("OP01-008")
    me2 = GameState(leader=mk("CVLDR", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [cavendish]
    me2.life = [mk("LFA", "Life A"), mk("LFB", "Life B")]
    opp2 = GameState(leader=mk("CVOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(cavendish, "on_play")
    check("Execucao real: 1 carta da Life foi pra mao (custo pago) e Cavendish ganhou Rush",
          len(me2.life) == 1 and len(me2.hand) == 1 and cavendish.rush_this_turn)


def test_lote_10_pendencias_eb01_011_a_op05_007() -> None:
    effects = {code: get_card_effects(code) for code in (
        "EB01-011", "OP05-056", "EB01-029", "EB01-045", "EB03-012",
        "OP04-044", "OP04-046", "OP04-084", "OP05-002", "OP05-007")}
    check("Lote 10: Mini-Merry exige rest_self + Character base 1000 no fundo",
          effects["EB01-011"]["activate_main"]["costs"][-1] ==
          {"type": "place_own_character_bottom_deck", "count": 1, "power_eq": 1000})
    check("Lote 10: X.Barrels exclui a propria carta do custo",
          effects["OP05-056"]["on_play"]["costs"] ==
          [{"type": "place_own_character_bottom_deck", "count": 1, "exclude_self": True}])
    check("Lote 10: Sorry I'm a Goner preserva Counter revelado custo>=4 e fundo",
          effects["EB01-029"]["counter"]["steps"][0]["condition"] ==
          {"revealed_card_cost_gte": 4}
          and effects["EB01-029"]["counter"]["steps"][0]["return_to"] == "bottom")
    check("Lote 10: Brook exige Character custo 0 do oponente",
          effects["EB01-045"]["on_play"]["conditions"] == {"opp_char_cost_eq": 0})
    check("Lote 10: Otama mantem escolha DON ou Animal/SMILE custo<=3",
          effects["EB03-012"]["activate_main"]["steps"][0].get("or_rest_opp_don") is True
          and effects["EB03-012"]["activate_main"]["steps"][0].get("filter_types") == ["animal", "smile"])
    check("Lote 10: Kaido tem os dois bounces 8 e 3",
          [s.get("cost_lte") for s in effects["OP04-044"]["on_play"]["steps"]] == [8, 3])
    queen = effects["OP04-046"]["on_play"]["steps"][1]
    check("Lote 10: Queen busca ate 2 Plague Rounds/Ice Oni",
          queen.get("count") == 2 and queen.get("filter_names") == ["plague rounds", "ice oni"])
    stussy = effects["OP04-084"]["on_play"]["steps"][1]
    check("Lote 10: Stussy joga CP custo<=2 e exclui Stussy",
          stussy.get("filter_type") == "cp" and stussy.get("cost_lte") == 2
          and stussy.get("exclude") == ["stussy"])
    betty = effects["OP05-002"]["activate_main"]["steps"][0]
    check("Lote 10: Belo Betty escolhe 3 Revolutionary Army ou Trigger",
          betty.get("count") == 3 and betty.get("filter_type_or_has_trigger") == "revolutionary army")
    check("Lote 10: Sabo limita o KO a soma de 4000 power",
          effects["OP05-007"]["on_play"]["steps"][0].get("total_power_lte") == 4000)

    # Execucao dos mecanismos novos/alterados.
    mini = real_card("EB01-011")
    fodder = mk("MM1", "Milzinho", power=1000)
    me = GameState(leader=mk("MML", "Lider", card_type="LEADER"), turn=3)
    me.field_stage = mini
    me.field_chars = [fodder]
    me.deck = [mk("MMD", "Compra")]
    opp = GameState(leader=mk("MMO", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(mini, "activate_main")
    check("Execucao lote 10: Mini-Merry paga ambos os custos e compra",
          mini.rested and fodder not in me.field_chars and fodder in me.deck and len(me.hand) == 1)

    brook = real_card("EB01-045")
    me2 = GameState(leader=mk("BRL", "Lider", card_type="LEADER"), turn=3)
    opp2 = GameState(leader=mk("BRO", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me2, opp2).execute(brook, "on_play")
    no_gate = not brook.rush_this_turn
    opp2.field_chars = [mk("C0", "Custo zero", cost=0)]
    EffectExecutor(me2, opp2).execute(brook, "on_play")
    check("Execucao lote 10: Brook ganha Rush somente com o gate custo 0", no_gate and brook.rush_this_turn)

    sabo = real_card("OP05-007")
    a = mk("SA", "Dois mil A", power=2000)
    b = mk("SB", "Dois mil B", power=2000)
    big = mk("SC", "Cinco mil", power=5000)
    me3 = GameState(leader=mk("SL", "Lider", card_type="LEADER"), turn=3)
    opp3 = GameState(leader=mk("SO", "Opp", card_type="LEADER"), turn=3)
    opp3.field_chars = [a, b, big]
    EffectExecutor(me3, opp3).execute(sabo, "on_play")
    check("Execucao lote 10: Sabo remove combinacao 2000+2000 e preserva 5000",
          a not in opp3.field_chars and b not in opp3.field_chars and big in opp3.field_chars)

    betty_card = real_card("OP05-002")
    rev = mk("REV", "Revolucionario", sub_types="Revolutionary Army")
    trig = mk("TRG", "Com Trigger", has_trigger=True)
    outsider = mk("OUT", "Sem filtro")
    me4 = GameState(leader=mk("BTL", "Lider", card_type="LEADER"), turn=3)
    me4.field_chars = [betty_card, rev, trig, outsider]
    me4.hand = [mk("PAY", "Pagamento", sub_types="Revolutionary Army")]
    opp4 = GameState(leader=mk("BTO", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me4, opp4).execute(betty_card, "activate_main")
    check("Execucao lote 10: Belo Betty buffa apenas tribo/Trigger",
          outsider.power_buff == 0
          and sum(c.power_buff == 3000 for c in (betty_card, rev, trig)) == 3)


def test_segundo_lote_10_pendencias_op01_063_a_op05_100() -> None:
    effects = {code: get_card_effects(code) for code in (
        "OP01-063", "OP01-098", "OP01-105", "OP02-002", "OP02-015",
        "OP05-026", "OP05-058", "OP05-080", "OP05-098", "OP05-100",
    )}
    check("Parser lote 2: dez cartas ganharam as estruturas esperadas",
          effects["OP01-063"]["activate_main"]["steps"][0].get("action") == "reveal_opp_hand"
          and effects["OP01-098"]["on_play"]["steps"][0].get("action") == "search_deck"
          and effects["OP01-105"]["on_play"]["steps"][0].get("count") == 2
          and effects["OP02-002"]["on_don_given"]["steps"][0].get("cost_lte") == 7
          and effects["OP02-015"]["activate_main"]["steps"][0].get("filter_color") == "red"
          and effects["OP05-026"]["when_attacking"]["costs"][0].get("cost_gte") == 3
          and effects["OP05-058"]["main"]["steps"][0].get("action") == "place_all_character_bottom_deck"
          and effects["OP05-080"]["when_attacking"]["costs"][0].get("count") == 20
          and effects["OP05-098"]["opp_turn"]["conditions"].get("life_lte") == 0
          and effects["OP05-100"]["passive"]["steps"][1].get("action") == "substitute_removal")

    # Arlong e Bao Huang: informacao revelada persistente; Arlong tambem
    # resolve a clausula condicional do Event revelado.
    arlong = real_card("OP01-063")
    arlong.don_attached = 1
    me = GameState(leader=mk("A-L", "Lider", card_type="LEADER"))
    me.field_chars = [arlong]
    event = mk("EV", "Evento", card_type="EVENT")
    life = mk("LIFE", "Vida")
    opp = GameState(leader=mk("A-O", "Opp", card_type="LEADER"))
    opp.hand = [event]
    opp.life = [life]
    EffectExecutor(me, opp).execute(arlong, "activate_main")
    check("Execucao lote 2: Arlong revela Event e move vida ao fundo",
          arlong.rested and id(event) in opp.revealed_to_opponent
          and not opp.life and opp.deck and opp.deck[0] is life)

    bao = real_card("OP01-105")
    me_bao = GameState(leader=mk("B-L", "Lider", card_type="LEADER"))
    opp_bao = GameState(leader=mk("B-O", "Opp", card_type="LEADER"))
    opp_bao.hand = [mk(f"BH{i}", f"Carta {i}") for i in range(3)]
    EffectExecutor(me_bao, opp_bao).execute(bao, "on_play")
    check("Execucao lote 2: Bao Huang registra exatamente duas reveladas",
          len(opp_bao.revealed_to_opponent) == 2)

    orochi = real_card("OP01-098")
    smile = mk("SMILE", "Artificial Devil Fruit SMILE", card_type="EVENT")
    me_orochi = GameState(leader=mk("O-L", "Lider", card_type="LEADER"))
    me_orochi.deck = [mk("NO", "Outra"), smile]
    EffectExecutor(me_orochi, opp_bao).execute(orochi, "on_play")
    check("Execucao lote 2: Orochi busca e revela SMILE no deck inteiro",
          smile in me_orochi.hand and id(smile) in me_orochi.revealed_to_opponent)

    makino = real_card("OP02-015")
    red1 = mk("R1", "Vermelho custo 1", cost=1, color="Red")
    black1 = mk("B1", "Preto custo 1", cost=1, color="Black")
    me_makino = GameState(leader=mk("M-L", "Lider", card_type="LEADER"))
    me_makino.field_chars = [makino, red1, black1]
    EffectExecutor(me_makino, opp_bao).execute(makino, "activate_main")
    check("Execucao lote 2: Makino restringe o buff a vermelho custo 1",
          makino.rested and red1.power_buff == 3000 and black1.power_buff == 0)

    garp = real_card("OP02-002")
    me_garp = GameState(leader=garp)
    opp_garp = GameState(leader=mk("G-O", "Opp", card_type="LEADER"))
    cost7 = mk("G7", "Custo sete", cost=7)
    cost8 = mk("G8", "Custo oito", cost=8, power=9000)
    opp_garp.field_chars = [cost7, cost8]
    EffectExecutor(me_garp, opp_garp)._dispatch_don_given(garp)
    check("Execucao lote 2: Garp reage ao DON e limita o debuff a custo 7",
          cost7.cost_buff == -1 and cost8.cost_buff == 0)

    sarquiss = real_card("OP05-026")
    sarquiss.don_attached = 1
    sarquiss.rested = True
    ally3 = mk("SQ3", "Aliado custo 3", cost=3)
    ally2 = mk("SQ2", "Aliado custo 2", cost=2)
    me_sarquiss = GameState(leader=mk("SQ-L", "Lider", card_type="LEADER"))
    me_sarquiss.field_chars = [sarquiss, ally3, ally2]
    EffectExecutor(me_sarquiss, opp_garp).execute(sarquiss, "when_attacking")
    check("Execucao lote 2: Sarquiss resta custo 3+ e fica ativo",
          not sarquiss.rested and ally3.rested and not ally2.rested)

    waste = real_card("OP05-058")
    me_waste = GameState(leader=mk("W-L", "Lider", card_type="LEADER"))
    opp_waste = GameState(leader=mk("W-O", "Opp", card_type="LEADER"))
    me_waste.field_chars = [mk("WC1", "Meu baixo", cost=3), mk("WC2", "Meu alto", cost=4)]
    opp_waste.field_chars = [mk("OC1", "Opp baixo", cost=2), mk("OC2", "Opp alto", cost=4)]
    me_waste.hand = [mk(f"MH{i}", f"Minha {i}") for i in range(7)]
    opp_waste.hand = [mk(f"OH{i}", f"Opp {i}") for i in range(6)]
    EffectExecutor(me_waste, opp_waste).execute(waste, "main")
    check("Execucao lote 2: Waste limpa ambos os campos e limita ambas as maos",
          [c.name for c in me_waste.field_chars] == ["Meu alto"]
          and [c.name for c in opp_waste.field_chars] == ["Opp alto"]
          and len(me_waste.hand) == len(opp_waste.hand) == 5)

    elizabello = real_card("OP05-080")
    me_eliz = GameState(leader=mk("EZ-L", "Lider", card_type="LEADER"))
    me_eliz.trash = [mk(f"EZ{i}", f"Trash {i}") for i in range(20)]
    EffectExecutor(me_eliz, opp_waste).execute(elizabello, "when_attacking")
    check("Execucao lote 2: Elizabello recicla 20 e recebe +10000",
          not me_eliz.trash and len(me_eliz.deck) == 20 and elizabello.power_buff == 10000)

    enel_leader = real_card("OP05-098")
    me_enel_leader = GameState(leader=enel_leader)
    me_enel_leader.deck = [mk("ET", "Topo")]
    me_enel_leader.hand = [mk("EH", "Descarte")]
    EffectExecutor(me_enel_leader, opp_waste).execute(enel_leader, "opp_turn")
    check("Execucao lote 2: Enel lider recupera Life e descarta uma carta",
          len(me_enel_leader.life) == 1 and not me_enel_leader.hand
          and len(me_enel_leader.trash) == 1)

    enel = real_card("OP05-100")
    me_enel = GameState(leader=mk("E-L", "Lider", card_type="LEADER"))
    me_enel.field_chars = [enel]
    me_enel.life = [mk("EL", "Vida Enel")]
    executor = EffectExecutor(me_enel, opp_waste)
    substituted = executor.try_substitute(enel, "deck_bottom")
    luffy = mk("LU", "Monkey.D.Luffy")
    me_enel.life = [mk("EL2", "Vida Enel 2")]
    opp_waste.field_chars.append(luffy)
    blocked = EffectExecutor(me_enel, opp_waste).try_substitute(enel, "ko")
    check("Execucao lote 2: Enel substitui remocao, exceto com Luffy em campo",
          substituted is not None and len(me_enel.trash) == 1 and blocked is None)


def test_filter_names_prb02_018_or_e_st13_006_each() -> None:
    # PRB02-018/ST13-006: "play up to N [A], [B], or [C]" (OR, escolhe ate N
    # no total) vs "play up to N each of [A], [B], and [C]" (AND, ate N de
    # CADA um). Achado 17/07: o parser so capturava o 1o nome ([Sabo]),
    # perdendo Portgas.D.Ace/Monkey.D.Luffy inteiramente em ambas.
    check("PRB02-018 parseia filter_names com os 3 nomes (sem 'each')",
          get_card_effects("PRB02-018").get("on_play", {}).get("steps", [{}])[0].get("filter_names") ==
          ["sabo", "portgas.d.ace", "monkey.d.luffy"]
          and "each" not in get_card_effects("PRB02-018")["on_play"]["steps"][0])
    check("ST13-006 parseia filter_names com os 3 nomes e each=True",
          get_card_effects("ST13-006").get("on_play", {}).get("steps", [{}])[0].get("filter_names") ==
          ["sabo", "portgas.d.ace", "monkey.d.luffy"]
          and get_card_effects("ST13-006")["on_play"]["steps"][0].get("each") is True)

    # OR (PRB02-018): condicao de vida face-up satisfeita, os 3 nomes
    # disponiveis (2 na mao, 1 no trash, cost 2) -- so 1 deve ser jogado no
    # total, os outros 2 continuam disponiveis (mao ou trash).
    prb02018 = real_card("PRB02-018")
    sabo = real_card("ST13-007")       # Sabo, custo 2
    ace = real_card("ST13-010")        # Portgas.D.Ace, custo 2
    luffy = real_card("ST13-014")      # Monkey.D.Luffy, custo 2
    me = GameState(leader=mk("PRBLDR", "Lider", card_type="LEADER"), turn=1)
    me.hand = [prb02018, sabo, ace]
    me.trash = [luffy]
    me.life = [mk("PRBLIFE1", "Life 1")]
    me.life[0].life_face_up = True
    opp = GameState(leader=mk("PRBOPP", "Opp", card_type="LEADER"), turn=1)
    log = EffectExecutor(me, opp).execute(prb02018, "on_play")
    jogados_or = [c for c in me.field_chars if c.code in ("ST13-007", "ST13-010", "ST13-014")]
    check("PRB02-018 (OR) joga exatamente 1 entre Sabo/Ace/Luffy, nao os 3",
          len(jogados_or) == 1 and any("jogou" in s for s in log))
    restantes_or = [c for c in me.hand + me.trash if c.code in ("ST13-007", "ST13-010", "ST13-014")]
    check("PRB02-018 (OR): os outros 2 nomes continuam na mao ou no trash",
          len(restantes_or) == 2)

    # OR sem a condicao (sem Life face-up): efeito nao deve jogar nada.
    prb02018_b = real_card("PRB02-018")
    sabo_b = real_card("ST13-007")
    me2 = GameState(leader=mk("PRBLDR2", "Lider", card_type="LEADER"), turn=1)
    me2.hand = [prb02018_b, sabo_b]
    me2.life = []
    opp2 = GameState(leader=mk("PRBOPP2", "Opp", card_type="LEADER"), turn=1)
    log2 = EffectExecutor(me2, opp2).execute(prb02018_b, "on_play")
    check("PRB02-018 sem Life face-up: nao joga nada (condicao bloqueia)",
          not any("jogou" in s for s in log2) and sabo_b in me2.hand)

    # AND/each (ST13-006): os 3 nomes na mao (cost 2) -- os 3 devem ser
    # jogados (1 de CADA), nao so 1 no total.
    st13006 = real_card("ST13-006")
    sabo2 = real_card("ST13-007")
    ace2 = real_card("ST13-010")
    luffy2 = real_card("ST13-014")
    me3 = GameState(leader=mk("STLDR", "Lider", card_type="LEADER"), turn=1)
    me3.hand = [st13006, sabo2, ace2, luffy2]
    opp3 = GameState(leader=mk("STOPP", "Opp", card_type="LEADER"), turn=1)
    EffectExecutor(me3, opp3).execute(st13006, "on_play")
    jogados_each = {c.code for c in me3.field_chars} & {"ST13-007", "ST13-010", "ST13-014"}
    check("ST13-006 (each) joga os 3 nomes (1 de CADA), nao so 1 no total",
          jogados_each == {"ST13-007", "ST13-010", "ST13-014"})
    check("ST13-006 (each): mao fica vazia dos 3 alvos (todos jogados)",
          not any(c.code in ("ST13-007", "ST13-010", "ST13-014") for c in me3.hand))

    # AND/each parcial: so 2 dos 3 nomes disponiveis -- deve jogar so os 2
    # presentes, sem quebrar por falta do 3o.
    st13006_b = real_card("ST13-006")
    sabo3 = real_card("ST13-007")
    ace3 = real_card("ST13-010")
    me4 = GameState(leader=mk("STLDR2", "Lider", card_type="LEADER"), turn=1)
    me4.hand = [st13006_b, sabo3, ace3]
    opp4 = GameState(leader=mk("STOPP2", "Opp", card_type="LEADER"), turn=1)
    EffectExecutor(me4, opp4).execute(st13006_b, "on_play")
    jogados_parcial = {c.code for c in me4.field_chars} & {"ST13-007", "ST13-010"}
    check("ST13-006 (each) parcial: joga os 2 nomes presentes quando o 3o falta na mao",
          jogados_parcial == {"ST13-007", "ST13-010"})


def test_kinemon_op10_026_027_e_familia_place_self_bottom_deck() -> None:
    # OP10-026/OP10-027 (Kin'emon): "You may place this Character and 1
    # [Kin'emon] with N power from your trash at the bottom of your deck
    # in any order: Play up to 1 [Kin'emon] with a cost of 6 from your
    # hand." -- custo INTEIRO ausente antes (achado 17/07), tratado como
    # gratis. Generalizado (mesma raiz gramatical "place this Character
    # ... at the bottom of ... deck", sem parceiro do trash) tambem pra
    # OP06-016/OP09-008/P-013/OP12-080/P-033 -- mesmo bug, custo ausente.
    check("OP10-026 parseia custo composto (self + kin'emon 0 power do trash)",
          get_card_effects("OP10-026").get("activate_main", {}).get("costs", []) ==
          [{"type": "place_self_bottom_deck", "trash_partner_count": 1,
            "trash_partner_name": "kin'emon", "trash_partner_power_eq": 0}])
    check("OP10-027 parseia custo composto (self + kin'emon 1000 power do trash)",
          get_card_effects("OP10-027").get("activate_main", {}).get("costs", []) ==
          [{"type": "place_self_bottom_deck", "trash_partner_count": 1,
            "trash_partner_name": "kin'emon", "trash_partner_power_eq": 1000}])
    check("OP06-016 parseia custo self-only (sem parceiro do trash)",
          get_card_effects("OP06-016").get("activate_main", {}).get("costs", []) ==
          [{"type": "place_self_bottom_deck"}])

    # Caso 1: custo PAGAVEL -- ha um Kin'emon com 0 power no trash.
    kinemon = real_card("OP10-026")
    parceiro = mk("OP10-P1", "Kin'emon", power=0, cost=1, sub_types="Wano Country")
    alvo_mao = mk("OP10-P2", "Kin'emon Alvo", power=5000, cost=6, sub_types="Wano Country")
    me = GameState(leader=mk("KEMLDR", "Lider", card_type="LEADER"), turn=3, don_available=6)
    me.field_chars = [kinemon]
    me.trash = [parceiro]
    me.hand = [alvo_mao]
    opp = GameState(leader=mk("KEMOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me, opp).execute(kinemon, "activate_main")
    check("Execucao real (custo pagavel): Kin'emon original + parceiro do trash foram pro fundo do deck",
          kinemon not in me.field_chars and kinemon in me.deck
          and parceiro not in me.trash and parceiro in me.deck)
    check("Execucao real (custo pagavel): o alvo da mao foi jogado (efeito disparou)",
          alvo_mao in me.field_chars and alvo_mao not in me.hand)

    # Caso 2: custo IMPAGAVEL -- sem Kin'emon 0 power no trash, nada e pago
    # e o efeito nao dispara (Kin'emon original continua no campo).
    kinemon_b = real_card("OP10-026")
    me2 = GameState(leader=mk("KEMLDR2", "Lider", card_type="LEADER"), turn=3, don_available=6)
    me2.field_chars = [kinemon_b]
    me2.trash = []
    me2.hand = [mk("OP10-P3", "Kin'emon Alvo 2", power=5000, cost=6, sub_types="Wano Country")]
    opp2 = GameState(leader=mk("KEMOPP2", "Opp", card_type="LEADER"), turn=3)
    logs = EffectExecutor(me2, opp2).execute(kinemon_b, "activate_main")
    check("Execucao real (custo impagavel, sem parceiro no trash): efeito nao dispara",
          not logs)
    check("Execucao real (custo impagavel): Kin'emon original continua no campo e mao intacta",
          kinemon_b in me2.field_chars and len(me2.hand) == 1)

    # Familia self-only (OP06-016): so exige a propria carta, sempre pagavel
    # enquanto ela estiver no campo.
    debuffer = real_card("OP06-016")
    alvo_opp = mk("OPPT", "Alvo Oponente", power=5000, cost=5)
    me3 = GameState(leader=mk("DBLDR", "Lider", card_type="LEADER"), turn=3)
    me3.field_chars = [debuffer]
    opp3 = GameState(leader=mk("DBOPP", "Opp", card_type="LEADER"), turn=3)
    opp3.field_chars = [alvo_opp]
    EffectExecutor(me3, opp3).execute(debuffer, "activate_main")
    check("Execucao real OP06-016 (self-only): a propria carta foi pro fundo do deck e o debuff aplicou",
          debuffer not in me3.field_chars and debuffer in me3.deck and alvo_opp.power_buff == -3000)


def test_your_turn_on_play_dispara_uma_vez_e_so_no_seu_turno() -> None:
    # "[Your Turn][On Play]" (ST22-011 Whitey Bay + 14 outras) gerava DOIS
    # blocos identicos (on_play e your_turn) -- o efeito disparava ao
    # entrar em campo E reaplicava de novo TODO turno seguinte via
    # apply_your_turn_buffs (achado 19/07/2026). Fundido num unico on_play
    # com o gate 'your_turn_only', checado via EffectExecutor.execute
    # (is_my_turn=...).
    whitey = real_card("ST22-011")
    check("ST22-011 nao tem mais bloco your_turn duplicado (fundido no on_play)",
          "your_turn" not in get_card_effects("ST22-011")
          and get_card_effects("ST22-011").get("on_play", {}).get("conditions", {}).get("your_turn_only") is True)

    lider = mk("WBLDR", "Lider", card_type="LEADER")
    me = GameState(leader=lider, turn=3)
    me.field_chars = [whitey]
    opp = GameState(leader=mk("WBOPP", "Opp", card_type="LEADER"), turn=3)
    ee = EffectExecutor(me, opp)
    ee.execute(whitey, "on_play")  # jogada normal = sempre o seu proprio turno (default is_my_turn=True)
    check("Execucao real: Whitey Bay jogada normalmente buffa o lider (+2000)",
          lider.power_buff == 2000)

    # Turno seguinte: apply_your_turn_buffs() zera e recalcula 'your_turn'/
    # 'passive' -- como o bloco duplicado foi removido, o buff do on_play
    # (ja aplicado uma vez, duration=this_turn) NAO deve ser reaplicado por
    # este mecanismo.
    ee.apply_your_turn_buffs()
    check("Execucao real: no turno seguinte, apply_your_turn_buffs NAO reaplica o buff (nao ha mais your_turn duplicado)",
          lider.power_buff == 0)

    # EB03-058 (Vegapunk): tem [Trigger] "If your Leader is Vegapunk, play
    # this card" -- pode entrar em campo via Trigger de vida, no turno do
    # OPONENTE (quem esta atacando). O "draw 1 card if life<=2" so deve
    # disparar se REALMENTE for o turno do dono.
    vegapunk_a = real_card("EB03-058")
    me2 = GameState(leader=mk("VPLDR", "Lider", card_type="LEADER"), turn=3)
    me2.field_chars = [vegapunk_a]
    me2.life = []  # 0 Life cards -> bate a condicao life_lte=2
    me2.deck = [mk("VPDECK2", "Carta do Deck")]  # garante que o bloqueio e o gate, nao deck vazio
    opp2 = GameState(leader=mk("VPOPP", "Opp", card_type="LEADER"), turn=3)
    hand_antes = len(me2.hand)
    EffectExecutor(me2, opp2).execute(vegapunk_a, "on_play", is_my_turn=False)
    check("Execucao real: Vegapunk via Trigger no turno do oponente (is_my_turn=False) NAO compra carta",
          len(me2.hand) == hand_antes)

    vegapunk_b = real_card("EB03-058")
    me3 = GameState(leader=mk("VPLDR2", "Lider", card_type="LEADER"), turn=3)
    me3.field_chars = [vegapunk_b]
    me3.life = []
    me3.deck = [mk("VPDECK", "Carta do Deck")]
    opp3 = GameState(leader=mk("VPOPP2", "Opp", card_type="LEADER"), turn=3)
    hand_antes3 = len(me3.hand)
    EffectExecutor(me3, opp3).execute(vegapunk_b, "on_play")  # jogada normal, is_my_turn=True default
    check("Execucao real: Vegapunk jogada normalmente no seu turno compra 1 carta",
          len(me3.hand) == hand_antes3 + 1)


def test_lote_8_op02_030_a_op03_012() -> None:
    # Lote de 10 suspeitos severidade-1 (19/07): maioria falso-positivo
    # (alvo unico implicito), mas 8 bugs reais descobertos alem da carta-
    # gatilho original.

    # OP02-030 Kouzuki Oden: [On K.O.] inteiro sumia (janela de 20 chars
    # cortava "green \"land of wano\" type character card" por 1 char) +
    # custo exato (nao "or less") virava cost_lte=99 (qualquer custo).
    on_ko = get_card_effects("OP02-030").get("on_ko", {})
    check("OP02-030 recupera o [On K.O.] inteiro (play_from_deck)",
          on_ko.get("steps", [{}])[0].get("action") == "play_from_deck")
    check("OP02-030 usa custo EXATO (cost_eq=3), nao cost_lte=99",
          on_ko["steps"][0].get("cost_eq") == 3
          and on_ko["steps"][0].get("color") == "green"
          and on_ko["steps"][0].get("filter_type") == "land of wano")

    # OP02-049 Emporio.Ivankov: condicao "if you have 0 cards in your
    # hand" inteira ausente -- o draw disparava sempre, incondicional.
    check("OP02-049 parseia condicao hand_eq=0",
          get_card_effects("OP02-049").get("end_of_turn", {}).get("conditions", {}) == {"hand_eq": 0})
    ivankov = real_card("OP02-049")
    me_iv_vazia = GameState(leader=mk("IVLDR", "Lider", card_type="LEADER"), turn=3)
    me_iv_vazia.field_chars = [ivankov]
    me_iv_vazia.hand = []
    me_iv_vazia.deck = [mk("IVD1", "D1"), mk("IVD2", "D2")]
    opp_iv = GameState(leader=mk("IVOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me_iv_vazia, opp_iv).execute(ivankov, "end_of_turn")
    check("Execucao real: OP02-049 COM mao vazia compra 2 cartas",
          len(me_iv_vazia.hand) == 2)
    ivankov2 = real_card("OP02-049")
    me_iv_cheia = GameState(leader=mk("IVLDR2", "Lider", card_type="LEADER"), turn=3)
    me_iv_cheia.field_chars = [ivankov2]
    me_iv_cheia.hand = [mk("IVH1", "H1")]
    me_iv_cheia.deck = [mk("IVD3", "D3")]
    opp_iv2 = GameState(leader=mk("IVOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me_iv_cheia, opp_iv2).execute(ivankov2, "end_of_turn")
    check("Execucao real: OP02-049 COM mao nao-vazia NAO compra (condicao bloqueia)",
          len(me_iv_cheia.hand) == 1)

    # OP02-051/OP02-069: "draw cards so that you have N cards in your
    # hand" -- mecanica dinamica nova, inteira ausente antes.
    check("OP02-051 parseia draw_to_hand_count target_count=3",
          any(s.get("action") == "draw_to_hand_count" and s.get("target_count") == 3
              for s in get_card_effects("OP02-051").get("on_play", {}).get("steps", [])))
    check("OP02-069 parseia draw_to_hand_count target_count=2",
          any(s.get("action") == "draw_to_hand_count" and s.get("target_count") == 2
              for s in get_card_effects("OP02-069").get("counter", {}).get("steps", [])))
    dth_me = GameState(leader=mk("DTHLDR", "Lider", card_type="LEADER"), turn=3)
    dth_me.hand = [mk("DTHH1", "H1")]
    dth_me.deck = [mk("DTHD1", "D1"), mk("DTHD2", "D2"), mk("DTHD3", "D3")]
    opp_dth = GameState(leader=mk("DTHOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(dth_me, opp_dth)._execute_step({"action": "draw_to_hand_count", "target_count": 3}, dth_me.leader)
    check("Execucao real: draw_to_hand_count com 1 na mao e alvo 3 compra exatamente 2",
          len(dth_me.hand) == 3)
    dth_me2 = GameState(leader=mk("DTHLDR2", "Lider", card_type="LEADER"), turn=3)
    dth_me2.hand = [mk("DTHH2", "H2"), mk("DTHH3", "H3"), mk("DTHH4", "H4"), mk("DTHH5", "H5")]
    dth_me2.deck = [mk("DTHD4", "D4")]
    opp_dth2 = GameState(leader=mk("DTHOPP2", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(dth_me2, opp_dth2)._execute_step({"action": "draw_to_hand_count", "target_count": 3}, dth_me2.leader)
    check("Execucao real: draw_to_hand_count com mao JA acima do alvo nao compra nada",
          len(dth_me2.hand) == 4)

    # OP02-059/OP02-070/OP09-059: "Then, trash up to N cards from your
    # hand" -- 2a clausula independente, sempre ausente antes (so a 1a,
    # "draw N and trash M", sobrevivia via then_trash).
    check("OP02-059 parseia as DUAS clausulas (then_trash=1 E trash_from_hand=3)",
          get_card_effects("OP02-059")["when_attacking"]["steps"][0].get("then_trash") == 1
          and get_card_effects("OP02-059")["when_attacking"]["steps"][1]
          == {"action": "trash_from_hand", "count": 3})
    check("OP02-070 (activate_main, nao estava na whitelist antes) tambem parseia as 2 clausulas",
          any(s.get("action") == "trash_from_hand" and s.get("count") == 3
              for s in get_card_effects("OP02-070")["activate_main"]["steps"]))
    check("OP09-059 (counter, tambem fora da whitelist antes) parseia trash_from_hand=2",
          any(s.get("action") == "trash_from_hand" and s.get("count") == 2
              for s in get_card_effects("OP09-059")["counter"]["steps"]))
    check("OP09-059 parseia o mill LIGADO (trash_from_deck_top count_from_last_hand_trash)",
          get_card_effects("OP09-059")["counter"]["steps"][-1]
          == {"action": "trash_from_deck_top", "count_from_last_hand_trash": True})

    # Execucao real do mill ligado: trash_from_hand trasha o que existir na
    # mao (ate 2), trash_from_deck_top deve milhar EXATAMENTE esse total,
    # nao um numero fixo do texto.
    murder = real_card("OP09-059")
    me_murder = GameState(leader=mk("MDLDR", "Lider", card_type="LEADER"), turn=3)
    me_murder.hand = [mk("MDH1", "H1")]  # so 1 carta na mao (custo pede "up to 2")
    me_murder.deck = [mk("MDD1", "D1"), mk("MDD2", "D2"), mk("MDD3", "D3")]
    opp_murder = GameState(leader=mk("MDOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me_murder, opp_murder).execute(murder, "counter")
    check("Execucao real: OP09-059 trasha 1 da mao (so tinha 1) e milha EXATAMENTE 1 do deck (nao 2 fixo)",
          len(me_murder.hand) == 0 and len(me_murder.trash) == 2 and len(me_murder.deck) == 2)

    # OP03-012 Marshall.D.Teach: custo "trash 1 of your red Characters with
    # 4000 power or more" virava trash_from_hand (zona errada) + perdia
    # filtro de cor e power inteiros.
    check("OP03-012 parseia custo trash_own_character com color=red e power_gte=4000",
          get_card_effects("OP03-012")["when_attacking"]["costs"][0]
          == {"type": "trash_own_character", "count": 1, "color": "red", "power_gte": 4000})
    teach = real_card("OP03-012")
    fraco_vermelho = mk("TEACHR1", "Fraco Vermelho", power=3000, color="Red")
    forte_azul = mk("TEACHR2", "Forte Azul", power=5000, color="Blue")
    forte_vermelho = mk("TEACHR3", "Forte Vermelho", power=5000, color="Red")
    me_teach = GameState(leader=mk("TCHLDR", "Lider", card_type="LEADER"), turn=3)
    me_teach.field_chars = [teach, fraco_vermelho, forte_azul, forte_vermelho]
    me_teach.deck = [mk("TCHD1", "D1")]
    opp_teach = GameState(leader=mk("TCHOPP", "Opp", card_type="LEADER"), turn=3)
    EffectExecutor(me_teach, opp_teach).execute(teach, "when_attacking")
    check("Execucao real: OP03-012 so aceita Character VERMELHO com 4000+ power como custo (nao a mao)",
          forte_vermelho not in me_teach.field_chars
          and fraco_vermelho in me_teach.field_chars and forte_azul in me_teach.field_chars)


def test_lote_5_op03_021_a_op03_083() -> None:
    # Continuacao do lote de 10 severidade-1 (itens 21-32), 5 bugs reais.

    # OP03-021 Kuro + familia (OP03-036/OP03-037/OP08-037): custo "you may
    # rest N of your [Tipo] type Characters:" inteiro ausente.
    check("OP03-021 parseia custo rest_own_character com filter_type=east blue",
          {"type": "rest_own_character", "count": 2, "filter_type": "east blue"}
          in get_card_effects("OP03-021")["activate_main"]["costs"])
    kuro = real_card("OP03-021")
    eb_char = mk("KEB1", "East Blue Guy", sub_types="East Blue")
    outro_char = mk("KOUT", "Outro", sub_types="Punk Hazard")
    me_kuro = GameState(leader=kuro, don_available=10)
    me_kuro.field_chars = [eb_char, outro_char]
    opp_kuro = GameState(leader=mk("KOPP", "Opp", card_type="LEADER"))
    opp_kuro.field_chars = [mk("KOT", "Alvo", cost=3)]
    ok = EffectExecutor(me_kuro, opp_kuro)._pay_costs(
        get_card_effects("OP03-021")["activate_main"]["costs"], kuro)
    check("Execucao real: OP03-021 so paga o custo com 2 East Blue disponiveis (so tem 1 -- falha)",
          not ok)

    # OP03-040 Nami lider: regra "when your deck is reduced to 0, you win
    # instead of losing" inteira ausente (fora do gate 'under the rules').
    check("OP03-040 parseia game_rules deck_out_win_instead_of_loss",
          {"type": "deck_out_win_instead_of_loss"}
          in get_card_effects("OP03-040").get("game_rules", {}).get("rules", []))

    # OP03-045/049/053: condicao "if you have 20 or less cards in your
    # deck" inteira ausente -- nova condicao deck_lte.
    check("OP03-045 parseia condicao deck_lte=20",
          get_card_effects("OP03-045")["opp_turn"]["conditions"] == {"deck_lte": 20})
    op03045 = real_card("OP03-045")
    me_deck45 = GameState(leader=mk("D45LDR", "Lider", card_type="LEADER"))
    me_deck45.field_chars = [op03045]
    me_deck45.deck = [mk(f"D45-{i}", f"D{i}") for i in range(25)]  # 25 > 20, condicao NAO bate
    opp_deck45 = GameState(leader=mk("D45OPP", "Opp", card_type="LEADER"))
    EffectExecutor(me_deck45, opp_deck45).execute(op03045, "opp_turn")
    check("Execucao real: OP03-045 com 25 cartas no deck (>20) NAO ganha o buff",
          op03045.power_buff == 0)
    op03045b = real_card("OP03-045")
    me_deck45b = GameState(leader=mk("D45LDR2", "Lider", card_type="LEADER"))
    me_deck45b.field_chars = [op03045b]
    me_deck45b.deck = [mk(f"D45B-{i}", f"D{i}") for i in range(15)]  # 15 <= 20, condicao bate
    opp_deck45b = GameState(leader=mk("D45OPP2", "Opp", card_type="LEADER"))
    EffectExecutor(me_deck45b, opp_deck45b).execute(op03045b, "opp_turn")
    check("Execucao real: OP03-045 com 15 cartas no deck (<=20) ganha +3000",
          op03045b.power_buff == 3000)

    # OP03-070 Ace: custo "trash 1 Character card with a cost of 5 from
    # your hand" perdia o filtro de custo inteiro (aceitava qualquer carta).
    check("OP03-070 parseia custo trash_from_hand com cost_eq=5",
          get_card_effects("OP03-070")["on_play"]["costs"][0]
          == {"type": "trash_from_hand", "count": 1, "cost_eq": 5})
    # Testado via _pay_costs direto (nao execute()): o beneficio (Rush)
    # sem alvo pra atacar nao passa no scoring "vale a pena pagar" do
    # engine, questao pre-existente e fora de escopo -- o que este fix
    # corrige e SO o filtro de custo (cost_eq=5), isolado aqui.
    ace = real_card("OP03-070")
    carta_custo3 = mk("ACEH1", "Custo 3", cost=3)
    carta_custo5 = mk("ACEH2", "Custo 5", cost=5)
    me_ace = GameState(leader=mk("ACELDR", "Lider", card_type="LEADER"), don_available=10)
    me_ace.field_chars = [ace]
    me_ace.hand = [carta_custo3, carta_custo5]
    opp_ace = GameState(leader=mk("ACEOPP", "Opp", card_type="LEADER"))
    ee_ace = EffectExecutor(me_ace, opp_ace)
    ee_ace._pay_costs(get_card_effects("OP03-070")["on_play"]["costs"], ace)
    check("Execucao real: OP03-070 so aceita a carta de custo 5 como custo (nao a de custo 3)",
          carta_custo5 not in me_ace.hand and carta_custo3 in me_ace.hand)

    # OP03-083 Corgy: "look 5, trash up to 2, place rest at bottom" virava
    # um add_to_hand INVENTADO (a carta nao adiciona nada a mao no texto real).
    check("OP03-083 parseia trash_from_looked_deck (nao add_to_hand)",
          get_card_effects("OP03-083")["on_play"]["steps"]
          == [{"action": "look_top_deck", "count": 5},
              {"action": "trash_from_looked_deck", "count": 2},
              {"action": "deck_bottom_rest"}])
    corgy = real_card("OP03-083")
    me_corgy = GameState(leader=mk("CGLDR", "Lider", card_type="LEADER"))
    me_corgy.field_chars = [corgy]
    me_corgy.deck = [mk(f"CGD-{i}", f"D{i}", power=1000 * (i + 1)) for i in range(10)]
    opp_corgy = GameState(leader=mk("CGOPP", "Opp", card_type="LEADER"))
    deck_antes = len(me_corgy.deck)
    EffectExecutor(me_corgy, opp_corgy).execute(corgy, "on_play")
    check("Execucao real: OP03-083 trasha exatamente 2 (nao adiciona nada a mao) e devolve 3 ao fundo do deck",
          len(me_corgy.hand) == 0 and len(me_corgy.trash) == 2 and len(me_corgy.deck) == deck_antes - 2)


def main() -> int:
    test_turn_order_imu_prefers_second()
    test_empty_throne_beats_direct_five_elders_play()
    test_ground_death_no_low_value_negate()
    test_never_existed_no_stage_is_hard_blocked()
    test_counter_buff_vai_pro_lider_defensor_no_empate()
    test_draw_cost_trasha_corpo_morto_antes_da_mao()
    test_shalria_na_mao_protegida_enquanto_precisa_de_trash()
    test_debuff_when_attacking_mira_o_defensor_que_vira_o_combate()
    test_avaliar_carta_prioriza_wincon_sobre_corpo_barato_vida_baixa()
    test_execucao_play_card_prioriza_wincon_sobre_searcher()
    test_salvar_blocker_desconta_on_ko_e_ataques_restantes()
    test_full_deck_census_populado_offline_e_ao_vivo()
    test_ciclo_do_lider_nao_trava_com_corpo_morto_ativo()
    test_don_reservado_para_ativar_wincon_em_campo()
    test_opponent_model_ao_vivo_por_lider_e_fallback_seguro()
    test_play_turn_greedy_opponent_response()
    test_play_turn_greedy_detecta_letal_do_oponente()
    test_imu_waits_for_active_elder_attack()
    test_nusjuro_rush_at_trash_7()
    test_nusjuro_rush_known_in_hand_for_planner()
    test_jinbe_grants_play_turn_character_attack()
    test_krieg_rest_opp_requires_2_don_attached()
    test_kid_leader_set_active_respects_cost_range()
    test_lock_opp_character_refresh_variantes_de_fraseado()
    test_rest_opp_alvo_misto_character_ou_don()
    test_give_don_opp_com_of_your_opponent_no_meio_da_frase()
    test_give_don_nao_inventa_don_quando_banco_insuficiente()
    test_give_don_da_so_o_necessario_nao_sempre_o_teto()
    test_hand_to_deck_clausula_loot_apos_draw()
    test_ipponmatsu_immunity_exige_leader_slash_e_don_rested()
    test_don_minus_sem_sinal_de_menos_na_fonte()
    test_opp_life_lte_gte_condicao_ausente()
    test_zoro_substitui_rest_por_aliado()
    test_whitebeard_reveal_conditional_play()
    test_zoro_lider_battled_character_e_restricao_de_ataque()
    test_roger_vitoria_alternativa_ao_oponente_bloquear()
    test_debuff_power_multiplo_alvo_e_condicao_por_tipo()
    test_total_life_lte_condicao_combinada()
    test_zero_life_condicao_e_scoping_then_if()
    test_descarte_mao_oponente_variantes_e_escolha_cega()
    test_reveal_top_life_play_nome_custo_e_if_you_do()
    test_op10_022_condicao_custo_e_play_life_por_tipo()
    test_rush_character_fraseado_condicional_e_auras()
    test_comparacao_don_proprio_lte_oponente()
    test_custos_condicionais_da_propria_carta_na_mao()
    test_searcher_cost_gte_e_peek_deck_oponente()
    test_evento_parametrizado_de_don_devolvido()
    test_ace_evento_dano_ou_ko_proprio()
    test_custo_composto_trash_para_fundo()
    test_reducao_de_custo_com_limite()
    test_don_on_field_lte_condicao_ausente()
    test_black_hole_negate_e_ko_encadeado()
    test_rebecca_add_from_trash_range_exclude_e_ordem()
    test_birdcage_trava_refresh_simetrica_cost_lte()
    test_zehahahahaha_segunda_clausula_dano_direto()
    test_shiryu_add_from_trash_to_life_com_filtro()
    test_character_para_life_do_dono_com_filtros()
    test_liberation_condicao_relativa_ko_duplo_e_trigger_1_de_cada()
    test_krieg_just_played_e_debuff_escalado_por_don()
    test_condicao_any_don_cards_given()
    test_opp_life_condition_after_and()
    test_hina_on_block_lock_during_this_turn()
    test_overheat_counter_buff_e_bounce_active_only()
    test_germa66_power_range_e_mesmo_nome_do_trashado()
    test_trash_own_character_custo_novo_e_avaliacao_por_campo()
    test_bounce_por_power_eq_base_power()
    test_power_of_n_ordem_invertida_transversal()
    test_place_bottom_deck_dois_alvos_ordem_agnostica()
    test_place_opp_char_to_opp_life_variantes_de_fraseado()
    test_place_own_character_bottom_deck_e_turno_extra()
    test_don_attached_total_gte_condicao_nova()
    test_activate_event_from_hand_sinonimo_de_play()
    test_koala_leader_attack_leader_e_opp_plays_character()
    test_shirahoshi_turn_life_face_up_substitute_e_no_other_named()
    test_no_other_named_condicao_transversal()
    test_all_allies_filter_type_buff_power()
    test_all_allies_filter_color_e_type_intercalados()
    test_lucy_event_activated_cost_gte_this_turn()
    test_gains_keyword_and_cost_buff()
    test_and_you_have_condicoes_transversais()
    test_opp_chars_rested_gte_condicao_nova()
    test_choose_and_ko_it_com_upgrade_condicional()
    test_rebecca_reveal_play_pair_condicional()
    test_gain_life_hand_filtro_ignorado_e_st13003_fonte_combinada()
    test_leader_condicao_contamina_alvo_self_do_buff()
    test_reveal_deck_top_conditional_9_cartas()
    test_play_card_power_lte_e_no_base_effect_e_chars_lte_power()
    test_own_character_buff_count_maior_que_1()
    test_reveal_from_hand_por_power_6_cartas()
    test_parse_play_generic_janela_com_ponto_em_nome_colchetado()
    test_rest_opp_character_typo_cost_or_n_or_less()
    test_eb01_028_active_qualifier_e_return_como_sinonimo_de_place()
    test_select_grant_blocker_4_cartas()
    test_look_top_deck_cost_range_eb03_060()
    test_op09_007_leader_power_lte_e_op03_016_sem_contaminacao()
    test_return_own_character_to_hand_com_filtro_8_cartas()
    test_reveal_events_custo_5_cartas()
    test_atalho_don_bare_sem_texto_explicativo_2_cartas()
    test_pica_substitute_ko_cost_gte_e_exclude_self()
    test_don_on_field_zero_or_gte_2_cartas()
    test_select_grant_rush_6_cartas()
    test_op16_043_typo_tour_opponent()
    test_opp_char_cost_eq_or_gte_op14_120()
    test_play_card_power_range_prb02_010()
    test_gain_life_own_field_cost_gte_power_gte_st13_001()
    test_pos_keyword_generico_e_ko_reativo_st10_006()
    test_reativo_mill_on_damage_to_life_familia_op03()
    test_op07_091_place_trash_matching_bottom_deck_e_buff_por_contagem_real()
    test_lote_11_itens_falso_positivo_op09_118_e_custo_don_ativo()
    test_lote_11_itens_hand_top_deck_familia()
    test_lote_11_itens_eb01_001_e_op12_098_cost_gte_type_e_selected()
    test_lote_11_itens_eb03_009_filter_no_effect_bug_e_ordem_target()
    test_lote_11_itens_eb02_056_opp_chars_lte()
    test_lote_11_itens_eb03_006_dado_bruto_e_once_per_turn_scoping()
    test_lote_11_itens_op14_009_swap_leader_e_character()
    test_lote_11_itens_op12_016_familia_rayleigh_e_keyword_blocker_guard()
    test_lote_11_itens_op16_118_counter_na_mao()
    test_lote_9_itens_st22_005_custo_composto_e_eb02_002_select_exclude()
    test_lote_9_itens_eb03_050_eb04_024_selecao_double_attack_e_unblockable()
    test_lote_9_itens_eb01_053_count2_e_eb03_061_alvo_misto()
    test_lote_9_itens_eb03_049_segunda_play_card_e_eb02_028_play_from_hand()
    test_lote_9_itens_eb02_007_leader_or_character_count3()
    test_lote_9_itens_eb04_056_condicao_composta_bonney_e_vida()
    test_don_n_parenteses_explicativo_e_life_area_cost()
    test_lote_10_pendencias_eb01_011_a_op05_007()
    test_segundo_lote_10_pendencias_op01_063_a_op05_100()
    test_filter_names_prb02_018_or_e_st13_006_each()
    test_kinemon_op10_026_027_e_familia_place_self_bottom_deck()
    test_your_turn_on_play_dispara_uma_vez_e_so_no_seu_turno()
    test_lote_8_op02_030_a_op03_012()
    test_lote_5_op03_021_a_op03_083()
    print()
    print("SMOKE FAST OK" if FAIL == 0 else f"{FAIL} FALHA(S) NO SMOKE FAST")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
