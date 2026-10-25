//! Fases do turno (ESPEC.md secao 3), espelho de `OPTCGMatch.play_turn`
//! (contadores e jogador ativo), `refresh_phase`, `draw_phase` e `don_phase`.
//! Onda 1: SEM efeitos (Birdcage/lock_both e reativos `opp_turn` ficam para a
//! onda de efeitos; o teste diferencial pula esses turnos).
use crate::acoes::Resultado;
use crate::cartas::info;
use crate::efeitos::Executor;
use crate::estado::{Carta, Estado, Jogador};
use serde_json::Value;
use std::collections::VecDeque;

type R<T> = Result<T, Resultado>;

fn ns(m: &str) -> Resultado {
    Resultado::NaoSuportado(m.to_string())
}

/// `lock_both_character_refresh` (Birdcage): stage de QUALQUER lado com a
/// passiva (e `leader_is` do dono batendo) trava o refresh de custo <= N.
fn trava_birdcage(e: &Estado) -> R<Option<i64>> {
    let mut lte = None;
    for dono in [&e.ativo, &e.oponente] {
        let Some(st) = &dono.stage else { continue };
        let i = info(&st.code).ok_or_else(|| ns("carta sem dados"))?;
        let Some(pas) = i.efeitos.get("passive") else { continue };
        for s in pas["steps"].as_array().into_iter().flatten() {
            if s["action"].as_str() != Some("lock_both_character_refresh") {
                continue;
            }
            let li = &pas["conditions"]["leader_is"];
            if !li.is_null() && !(li.as_str() == Some("") || li.as_array().map_or(false, |a| a.is_empty())) {
                let nome = info(&dono.leader.code).ok_or_else(|| ns("carta sem dados"))?.name.to_lowercase();
                let nomes: Vec<String> = match li {
                    Value::Array(a) => a.iter().map(|x| x.as_str().unwrap_or("").to_lowercase()).collect(),
                    x => vec![x.as_str().unwrap_or("").to_lowercase()],
                };
                if !nomes.iter().any(|n| nome.contains(n.as_str())) {
                    continue;
                }
            }
            lte = Some(s["cost_lte"].as_i64().unwrap_or(99));
        }
    }
    Ok(lte)
}

fn refresh_char(c: &mut Carta, birdcage: Option<i64>) {
    c.don_attached = 0;
    if c.frozen_next_refresh {
        c.frozen_next_refresh = false;
    } else if birdcage.map_or(false, |l| info(&c.code).map_or(false, |i| i.cost <= l)) {
        // Birdcage: nao ativa, e NAO consome frozen_next_refresh
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

fn refresh(p: &mut Jogador, birdcage: Option<i64>) {
    let don_from_cards: i64 =
        p.field_chars.iter().map(|c| c.don_attached).sum::<i64>() + p.leader.don_attached;
    for c in p.field_chars.iter_mut() {
        refresh_char(c, birdcage);
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
pub fn inicio_de_turno(e: &mut Estado, global_turn: i64, fila: VecDeque<Value>) -> R<()> {
    let g = global_turn + 1;
    e.ativo.turn += 1;
    e.ativo.global_turn = g;
    e.oponente.global_turn = g;
    e.ativo.is_active_turn = true;
    e.oponente.is_active_turn = false;
    e.ativo.pending_play_cost_reductions.clear();
    let bc = trava_birdcage(e)?;
    refresh(&mut e.ativo, bc);
    // `_apply_opp_turn_reactive_effects`: passivas 'opp_turn' do OUTRO lado,
    // um EffectExecutor novo por fonte
    const REATIVAS: &[&str] = &["buff_power", "debuff_power", "buff_cost", "debuff_cost", "set_base_power"];
    let mut fontes: Vec<(Carta, Option<(String, usize)>)> = vec![(e.oponente.leader.clone(), Some(("leader".into(), 0)))];
    fontes.extend(e.oponente.field_chars.iter().cloned().enumerate().map(|(i, c)| (c, Some(("field_chars".into(), i)))));
    if let Some(s) = &e.oponente.stage {
        fontes.push((s.clone(), None));
    }
    let mut ex = Executor::novo(fila);
    for (k, (f, l)) in fontes.into_iter().enumerate() {
        let i = info(&f.code).ok_or_else(|| ns("carta sem dados"))?;
        let Some(b) = i.efeitos.get("opp_turn") else { continue };
        if !b["steps"].as_array().into_iter().flatten().any(|s| REATIVAS.contains(&s["action"].as_str().unwrap_or(""))) {
            continue;
        }
        ex.inst = 9100 + k as u32;
        ex.lugar_fonte = l;
        ex.executa(&mut e.oponente, &mut e.ativo, &f, "opp_turn")?;
    }
    if !ex.fila.is_empty() {
        return Err(ns("sobrou decisao no inicio do turno"));
    }
    draw(&mut e.ativo);
    don(&mut e.ativo);
    Ok(())
}

/// `OPTCGMatch.end_phase` SEM efeito: [End of Your Turn] e a fila agendada sao
/// efeitos (onda de efeitos); a regra pura do fim de turno nao muda o estado --
/// os "ate o fim do turno" sao limpos no inicio do turno seguinte (`inicio_de_turno`).
pub fn fim_de_turno(e: &mut Estado, fila: VecDeque<Value>) -> R<()> {
    // [End of Your Turn] de lider, personagens e stage, pelo MESMO executor
    let mut fontes: Vec<(Carta, Option<(String, usize)>)> = vec![(e.ativo.leader.clone(), Some(("leader".into(), 0)))];
    fontes.extend(e.ativo.field_chars.iter().cloned().enumerate().map(|(i, c)| (c, Some(("field_chars".into(), i)))));
    if let Some(s) = &e.ativo.stage {
        fontes.push((s.clone(), None));
    }
    let mut ex = Executor::novo(fila);
    ex.inst = 9000;
    for (f, l) in fontes {
        ex.lugar_fonte = l;
        ex.executa(&mut e.ativo, &mut e.oponente, &f, "end_of_turn")?;
    }
    if e.ativo.extras.get("end_of_turn_queue").and_then(|v| v.as_array()).map_or(false, |a| !a.is_empty()) {
        return Err(ns("fila agendada para o fim do turno"));
    }
    if !ex.fila.is_empty() {
        return Err(ns("sobrou decisao no fim do turno"));
    }
    Ok(())
}
