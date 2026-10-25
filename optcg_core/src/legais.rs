//! Jogadas LEGAIS pelas regras (para a busca da fase B), no mesmo formato de
//! jogada do diario (`estado_canonico.descreve_acao`).
//!
//! Sao as regras do motor Python SEM os cortes heuristicos de
//! `_generate_and_score_actions` (reserva de DON para a defesa, ataque "inutil",
//! `avaliar_carta`, evento sem passo viavel): a busca e quem decide o que vale.
//! O DON do ataque entra pelas jogadas `attach_don` (ataque sempre com don=0).
use crate::acoes::{is_rush, is_rush_character, Resultado};
use crate::efeitos::{custo_de_jogar, dados, passos_de, poder_meu_turno, poder_turno_do_outro, Executor};
use crate::estado::{Carta, Estado, Jogador};
use serde_json::{json, Value};

type R<T> = Result<T, Resultado>;

fn ns(m: &str) -> Resultado {
    Resultado::NaoSuportado(m.to_string())
}

fn texto_vazio(v: &Value) -> bool {
    v.is_null() || v.as_str() == Some("") || v == &Value::Bool(false)
}

/// `is_attack_locked_self(card, owner, opp)`
fn travado_por_passiva(c: &Carta, dono: &Jogador, opp: &Jogador) -> R<bool> {
    if c.own_effect_negated_this_turn {
        return Ok(false);
    }
    let i = dados(c)?;
    let ex = Executor::novo(Default::default());
    if let Some(pas) = i.efeitos.get("passive") {
        let cs = &pas["conditions"];
        let ativo = cs.as_object().map_or(true, |m| m.is_empty()) || ex.condicoes(cs, dono, opp, c, "passive")?;
        if ativo {
            for st in passos_de(pas) {
                match st["action"].as_str().unwrap_or("") {
                    "cannot_attack_self" => return Ok(true),
                    "cannot_attack_self_unless" => {
                        if st.get("condition_text").is_some() && st.get("conditions").is_none() {
                            return Ok(true);
                        }
                        let cs = &st["conditions"];
                        if let Some(l) = cs["board_has_power_gte"].as_i64() {
                            let mut mx: Option<i64> = None;
                            for x in dono.field_chars.iter().chain(opp.field_chars.iter()) {
                                let p = poder_meu_turno(x)?;
                                mx = Some(mx.map_or(p, |m: i64| m.max(p)));
                            }
                            if mx.map_or(true, |m| m < l) {
                                return Ok(true);
                            }
                        }
                        if let Some(spec) = cs.get("opp_chars_power_gte_count") {
                            let pg = spec["power_gte"].as_i64().unwrap_or(0);
                            let mut n = 0;
                            for x in &opp.field_chars {
                                if poder_turno_do_outro(x)? >= pg {
                                    n += 1;
                                }
                            }
                            if n < spec["count"].as_i64().unwrap_or(0) {
                                return Ok(true);
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
    }
    let nome_lider = dados(&dono.leader)?.name.to_lowercase();
    for f in dono.field_chars.iter().chain(std::iter::once(&dono.leader)) {
        let Some(ml) = dados(f)?.efeitos.get("mass_lock_conditional").cloned() else { continue };
        let li = &ml["conditions"]["leader_is"];
        if !texto_vazio(li) && !(li.is_array() && li.as_array().unwrap().is_empty()) {
            let nomes: Vec<String> = match li {
                Value::Array(a) => a.iter().filter_map(|x| x.as_str()).map(|x| x.to_lowercase()).collect(),
                x => vec![x.as_str().unwrap_or("").to_lowercase()],
            };
            if !nomes.iter().any(|n| nome_lider.contains(n.as_str())) {
                continue;
            }
        }
        for s in passos_de(&ml) {
            if s["action"].as_str() == Some("cannot_attack_own_characters_by_cost")
                && s["costs"].as_array().into_iter().flatten().any(|x| x.as_i64() == Some(i.cost))
            {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

/// `character_can_attack_now(card, owner, opp)`
fn pode_atacar(c: &Carta, dono: &Jogador, opp: &Jogador) -> R<bool> {
    if c.rested || !c.cannot_attack_until.is_empty() || !c.cannot_be_rested_until.is_empty() {
        return Ok(false);
    }
    let i = dados(c)?;
    if c.just_played && !(is_rush(c, &i) || is_rush_character(c, &i) || c.rush_character_only_this_turn) {
        return Ok(false);
    }
    if travado_por_passiva(c, dono, opp)? {
        return Ok(false);
    }
    // `can_afford_attack_paywall`
    if let Some(pw) = c.attack_paywall.as_object() {
        if !pw.is_empty() && pw.get("cost_type").and_then(|x| x.as_str()) == Some("trash_from_hand")
            && (dono.hand.len() as i64) < pw.get("cost_amount").and_then(|x| x.as_i64()).unwrap_or(1)
        {
            return Ok(false);
        }
    }
    Ok(true)
}

/// `active_taunt_character(defender, attacker_side)`: indice do personagem que atrai o ataque
fn provocador(def: &Jogador, atk: &Jogador) -> R<Option<usize>> {
    let ex = Executor::novo(Default::default());
    for (j, c) in def.field_chars.iter().enumerate() {
        for b in dados(c)?.efeitos.values() {
            if !b.is_object() || !passos_de(b).any(|s| s["action"].as_str() == Some("force_opp_attack_self")) {
                continue;
            }
            let dr = b["don_requirement"].as_i64().unwrap_or(0);
            if dr != 0 && c.don_attached < dr {
                continue;
            }
            let cs = &b["conditions"];
            if !cs.as_object().map_or(true, |m| m.is_empty()) && !ex.condicoes(cs, def, atk, c, "passive")? {
                continue;
            }
            return Ok(Some(j));
        }
    }
    Ok(None)
}

/// Custo de [Activate: Main] que da pra ver que NAO se paga agora (o resto: legal)
fn custo_impagavel(custos: &Value, p: &Jogador, fonte: &Carta) -> bool {
    for c in custos.as_array().into_iter().flatten() {
        if c["optional"].as_bool().unwrap_or(false) {
            continue;
        }
        let n = c["count"].as_i64().unwrap_or(1);
        let falta = match c["type"].as_str().unwrap_or("") {
            "rest_don" => p.don_available < n,
            "don_minus" => p.don_available + p.don_rested < n,
            "rest_self" => fonte.rested,
            "trash_from_hand" => (p.hand.len() as i64) < n,
            _ => false,
        };
        if falta {
            return true;
        }
    }
    false
}

fn lugar(z: &str, i: usize) -> Value {
    json!([z, i])
}

/// Todas as jogadas legais do jogador ativo (inclui `{"tipo": "end"}`).
pub fn jogadas_legais(e: &Estado) -> R<Vec<Value>> {
    let (p, opp) = (&e.ativo, &e.oponente);
    let mut out = Vec::new();
    // jogar da mao
    for (k, c) in p.hand.iter().enumerate() {
        let i = dados(c)?;
        if !matches!(i.card_type.as_str(), "CHARACTER" | "EVENT" | "STAGE") || p.cant_play_from_hand_this_turn {
            continue;
        }
        if i.card_type == "CHARACTER"
            && (p.cant_play_chars_this_turn || (p.cant_play_cost_gte != 0 && i.cost >= p.cant_play_cost_gte))
        {
            continue;
        }
        if custo_de_jogar(p, opp, c)? > p.don_available {
            continue;
        }
        if i.card_type == "EVENT" && !["on_play", "main", "activate_main"].iter().any(|t| i.efeitos.contains_key(*t)) {
            continue;
        }
        out.push(json!({"tipo": "play", "ator": lugar("hand", k), "alvo_tipo": null, "don": null, "alvo": null}));
    }
    // [Activate: Main]
    let mut fontes: Vec<(&Carta, Value)> = vec![(&p.leader, lugar("leader", 0))];
    if let Some(s) = &p.stage {
        fontes.push((s, lugar("stage", 0)));
    }
    fontes.extend(p.field_chars.iter().enumerate().map(|(k, c)| (c, lugar("field_chars", k))));
    for (c, l) in &fontes {
        let i = dados(c)?;
        let Some(am) = i.efeitos.get("activate_main") else { continue };
        if c.rested {
            let rest_self = am["costs"].as_array().into_iter().flatten().any(|x| x["type"].as_str() == Some("rest_self"));
            if rest_self || l[0] != "leader" {
                continue;
            }
        }
        if c.extras.get("_am_used_turn").and_then(|x| x.as_i64()) == Some(p.turn) {
            continue;
        }
        let dr = am["don_requirement"].as_i64().unwrap_or(0);
        if dr != 0 && c.don_attached < dr {
            continue;
        }
        if custo_impagavel(&am["costs"], p, c) {
            continue;
        }
        out.push(json!({"tipo": "activate", "ator": l, "alvo_tipo": null, "don": null, "alvo": null}));
    }
    // dar DON
    if p.don_available > 0 {
        let mut alvos = vec![lugar("leader", 0)];
        alvos.extend((0..p.field_chars.len()).map(|k| lugar("field_chars", k)));
        for l in alvos {
            for n in 1..=p.don_available {
                out.push(json!({"tipo": "attach_don", "ator": l, "alvo_tipo": n, "don": null, "alvo": null}));
            }
        }
    }
    // atacar
    if p.turn > 1 {
        let prov = provocador(opp, p)?;
        let mut atacantes: Vec<(&Carta, Value)> = Vec::new();
        for (k, c) in p.field_chars.iter().enumerate() {
            if pode_atacar(c, p, opp)? {
                atacantes.push((c, lugar("field_chars", k)));
            }
        }
        if pode_atacar(&p.leader, p, opp)? {
            atacantes.push((&p.leader, lugar("leader", 0)));
        }
        for (a, l) in atacantes {
            if !a.rush_character_only_this_turn && prov.is_none() && !p.cannot_attack_leader_this_turn {
                out.push(json!({"tipo": "attack", "ator": l, "alvo_tipo": "leader", "don": 0, "alvo": null}));
            }
            let ativos_tambem = a.can_attack_active_this_turn
                || a.extras.get("can_attack_active").and_then(|x| x.as_bool()).unwrap_or(false);
            for (j, t) in opp.field_chars.iter().enumerate() {
                if !(t.rested || ativos_tambem) || prov.map_or(false, |x| x != j) {
                    continue;
                }
                if a.cannot_attack_opp_chars_cost_lte >= 0 && dados(t)?.cost <= a.cannot_attack_opp_chars_cost_lte {
                    continue;
                }
                out.push(json!({"tipo": "attack", "ator": l, "alvo_tipo": "character", "don": 0,
                                "alvo": ["oponente", "field_chars", j]}));
            }
        }
    }
    out.push(json!({"tipo": "end"}));
    Ok(out)
}
