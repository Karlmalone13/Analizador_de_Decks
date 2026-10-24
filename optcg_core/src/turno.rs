//! Fases do turno (ESPEC.md secao 3), espelho de `OPTCGMatch.play_turn`
//! (contadores e jogador ativo), `refresh_phase`, `draw_phase` e `don_phase`.
//! Onda 1: SEM efeitos (Birdcage/lock_both e reativos `opp_turn` ficam para a
//! onda de efeitos; o teste diferencial pula esses turnos).
use crate::estado::{Carta, Estado, Jogador};

fn refresh_char(c: &mut Carta) {
    c.don_attached = 0;
    if c.frozen_next_refresh {
        c.frozen_next_refresh = false;
    } else {
        c.rested = false;
    }
    c.just_played = false;
    c.power_buff = 0;
    c.cost_buff = 0;
    c.cannot_attack_until.clear();
    c.cannot_be_rested_until.clear();
    c.cannot_block_until.clear();
    c.effects_negated_until.clear();
    c.attack_paywall = serde_json::Value::Object(Default::default());
    c.unblockable_this_turn = false;
    c.rush_this_turn = false;
    c.double_attack_this_turn = false;
    c.blocker_this_turn = false;
    c.banish_this_turn = false;
    c.extra_attribute_this_turn.clear();
    c.can_attack_active_this_turn = false;
    c.ko_on_opp_blocker_used_this_turn = false;
    c.immunity_ko_until.clear();
    c.battled_opp_character_this_turn = false;
    c.cannot_attack_opp_chars_cost_lte = -1;
    c.own_effect_negated_this_turn = false;
}

fn refresh(p: &mut Jogador) {
    let don_from_cards: i64 =
        p.field_chars.iter().map(|c| c.don_attached).sum::<i64>() + p.leader.don_attached;
    for c in p.field_chars.iter_mut() {
        refresh_char(c);
    }
    let l = &mut p.leader;
    l.don_attached = 0;
    if l.frozen_next_refresh {
        l.frozen_next_refresh = false;
    } else {
        l.rested = false;
    }
    l.power_buff = 0;
    l.cost_buff = 0;
    l.cannot_attack_until.clear();
    l.effects_negated_until.clear();
    l.unblockable_this_turn = false;
    l.ko_on_opp_blocker_used_this_turn = false;
    l.battled_opp_character_this_turn = false;
    l.cannot_attack_opp_chars_cost_lte = -1;
    if let Some(s) = p.stage.as_mut() {
        if s.frozen_next_refresh {
            s.frozen_next_refresh = false;
        } else {
            s.rested = false;
        }
    }
    let frozen = p.frozen_don_count.min(p.don_rested);
    p.don_available += (p.don_rested - frozen) + don_from_cards;
    p.don_rested = frozen;
    p.frozen_don_count = 0;
    p.cant_play_from_hand_this_turn = false;
    p.cant_play_chars_this_turn = false;
    p.cant_play_cost_gte = 0;
    p.cannot_attack_leader_this_turn = false;
    p.cant_take_life_this_turn = false;
    p.events_activated_costs_this_turn.clear();
}

fn draw(p: &mut Jogador) {
    if p.turn == 1 && p.is_first {
        return;
    }
    if let Some(c) = p.deck.pop() {
        p.hand.push(c);
    }
}

fn don(p: &mut Jogador) {
    let ganho = (if p.turn == 1 && p.is_first { 1 } else { 2 }).min(p.don_deck);
    p.don_deck -= ganho;
    p.don_available += ganho;
}

/// Do estado `turno_inicio` (antes de tudo) ate o `main_inicio` (depois do DON).
/// `global_turn` = contador da partida ANTES deste turno.
pub fn inicio_de_turno(e: &mut Estado, global_turn: i64) {
    let g = global_turn + 1;
    e.ativo.turn += 1;
    e.ativo.global_turn = g;
    e.oponente.global_turn = g;
    e.ativo.is_active_turn = true;
    e.oponente.is_active_turn = false;
    e.ativo.pending_play_cost_reductions.clear();
    refresh(&mut e.ativo);
    draw(&mut e.ativo);
    don(&mut e.ativo);
}
