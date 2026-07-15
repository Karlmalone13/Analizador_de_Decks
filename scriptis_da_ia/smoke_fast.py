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
    test_don_on_field_lte_condicao_ausente()
    test_black_hole_negate_e_ko_encadeado()
    test_rebecca_add_from_trash_range_exclude_e_ordem()
    test_birdcage_trava_refresh_simetrica_cost_lte()
    test_zehahahahaha_segunda_clausula_dano_direto()
    test_shiryu_add_from_trash_to_life_com_filtro()
    test_liberation_condicao_relativa_ko_duplo_e_trigger_1_de_cada()
    test_krieg_just_played_e_debuff_escalado_por_don()
    test_condicao_any_don_cards_given()
    print()
    print("SMOKE FAST OK" if FAIL == 0 else f"{FAIL} FALHA(S) NO SMOKE FAST")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
