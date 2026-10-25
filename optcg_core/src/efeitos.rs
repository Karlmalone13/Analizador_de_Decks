//! Interpretador de efeitos (onda 1), espelho de `EffectExecutor.execute` /
//! `_check_conditions` / `_step_is_viable` / `_pay_costs` / `_execute_step`.
//!
//! O nucleo aplica a REGRA; o que o motor Python DECIDE no meio do efeito
//! (alvo, carta descartada, carta buscada, pagar ou nao o custo opcional) chega
//! pronto na FILA (eventos `escolha_efeito` / `paga_custo` do diario, na ordem).
//! Tudo que ainda nao esta coberto devolve `NaoSuportado` -- nunca um resultado
//! aproximado.
use crate::acoes::Resultado;
use crate::cartas::{info, InfoCarta};
use crate::estado::{Carta, Jogador};
use serde_json::Value;
use std::collections::VecDeque;

fn ns(m: &str) -> Resultado {
    Resultado::NaoSuportado(m.to_string())
}

type R<T> = Result<T, Resultado>;

fn dados(c: &Carta) -> R<InfoCarta> {
    info(&c.code).ok_or_else(|| ns(&format!("carta sem dados: {}", c.code)))
}

fn norm_tipo(t: &str) -> String {
    t.to_lowercase().replace("whitebeard piratess", "whitebeard pirates")
}

/// `rules_facade.card_matches_filter`
fn casa_filtro(i: &InfoCarta, filtro: &Value, incluir_texto: bool) -> bool {
    let agulhas: Vec<String> = match filtro {
        Value::Array(a) => a
            .iter()
            .filter_map(|x| x.as_str())
            .filter(|x| !x.is_empty())
            .map(|x| x.to_lowercase())
            .collect(),
        Value::String(s) if !s.is_empty() => vec![s.to_lowercase()],
        _ => vec![],
    };
    if agulhas.is_empty() {
        return true;
    }
    let mut campos = vec![i.sub_types.to_lowercase(), i.name.to_lowercase(), i.card_type.to_lowercase()];
    campos.extend(i.alternate_names.iter().map(|x| x.to_lowercase()));
    if incluir_texto {
        campos.push(i.card_text.to_lowercase());
    }
    agulhas.iter().any(|a| campos.iter().any(|c| c.contains(a.as_str())))
}

fn passos_de(b: &Value) -> impl Iterator<Item = &Value> {
    b["steps"].as_array().into_iter().flatten()
}

/// Todas as chaves que `_check_conditions` do Python checa (as outras ele ignora).
const CONDICOES_DO_PYTHON: &[&str] = &[
    "battled_opp_character_this_turn", "board_chars_cost_gte_count", "board_has_cost",
    "board_has_cost_gte", "board_has_power_gte", "chars_fewer_than_opp_by_gte", "chars_gte",
    "chars_gte_color_filter", "chars_gte_cost_filter", "chars_gte_distinct_names",
    "chars_gte_exclude_self", "chars_gte_type_filter", "chars_lte", "chars_lte_power_filter",
    "chars_rested_gte", "chars_rested_gte_type_filter", "deck_lte", "don_attached_total_gte",
    "don_fewer_than_opp_by_gte", "don_gte", "don_lte", "don_on_field_gte", "don_on_field_lte",
    "don_on_field_lte_opp", "don_on_field_zero_or_gte", "don_rested_gte",
    "event_activated_cost_gte_this_turn", "events_in_trash_gte", "hand_eq",
    "hand_fewer_than_opp_by_gte", "hand_gte", "hand_lte", "has_don_attached", "has_face_up_life",
    "has_named_card_on_field", "has_named_character", "has_named_characters",
    "has_named_characters_in_trash", "has_named_characters_power_eq", "has_other_named",
    "just_played", "leader_attribute", "leader_is", "leader_is_or_type", "leader_multicolor",
    "leader_name_includes", "leader_power_gte", "leader_power_lte", "leader_state", "leader_type",
    "leader_type_includes", "life_and_hand_total_lte", "life_gte", "life_lte",
    "life_removed_recently", "no_char_cost_gte", "no_char_power_gte", "no_char_type_cost_gte",
    "no_other_named", "no_other_named_cost_eq", "no_own_chars_cost_gte_count", "only_field_type",
    "opp_char_cost_eq", "opp_char_cost_eq_or_gte", "opp_char_power_gte", "opp_chars_gte",
    "opp_chars_lte", "opp_chars_power_gte_count", "opp_chars_rested_gte", "opp_don_on_field_gte",
    "opp_don_on_field_lte", "opp_hand_gte", "opp_leader_attribute", "opp_leader_power_gte",
    "opp_life_gte", "opp_life_lte", "opp_life_removed_recently", "opp_rested_cards_gte",
    "other_char_cost_gte", "other_char_cost_gte_type", "other_char_power_gte",
    "other_char_power_gte_names", "other_char_power_gte_type", "other_char_power_uses_base",
    "own_rested_cards_gte", "self_power_gte", "self_rested", "self_type", "total_chars_cost_gte",
    "total_life_lte", "trash_gte", "trash_lte", "turn_gte",
];

pub struct Executor {
    pub fila: VecDeque<Value>,
    /// Instancia de `EffectExecutor` do Python em uso: o `_once_used` dele e POR
    /// INSTANCIA (descartavel). 0 = o executor da Main, que vive o turno todo e
    /// nao esta no canonico -> once_per_turn fora do nucleo.
    pub inst: u32,
    pub usados: std::collections::HashSet<(u32, String, String)>,
    /// Lugar da carta-fonte no lado de quem executa ("leader"|"field_chars", i):
    /// passos que mexem na PROPRIA carta (`target='self'`). None = fora do campo.
    pub lugar_fonte: Option<(String, usize)>,
    /// `_last_selected` (memoria de alvo entre passos do MESMO execute)
    ultimo: Option<Option<usize>>,
    /// o ultimo `executa` pagou o custo e rodou os passos (`logs` nao vazio no Python)
    pub rodou: bool,
}

impl Executor {
    pub fn novo(fila: VecDeque<Value>) -> Self {
        Executor { fila, inst: 0, usados: Default::default(), lugar_fonte: None, ultimo: None, rodou: false }
    }
}

/// Carta do lado `me` por lugar (None = lider)
fn carta_mut(me: &mut Jogador, i: Option<usize>) -> R<&mut Carta> {
    match i {
        None => Ok(&mut me.leader),
        Some(i) => me.field_chars.get_mut(i).ok_or_else(|| ns("carta fora do campo")),
    }
}

/// `effective_power(your_turn=True)`
fn poder_meu_turno(c: &Carta) -> R<i64> {
    let base = c.base_power_override.unwrap_or(dados(c)?.power);
    Ok((base + c.power_buff + c.don_attached * 1000).max(0))
}

impl Executor {
    fn proxima(&mut self, tipo: &str) -> R<Value> {
        let d = self.fila.pop_front().ok_or_else(|| ns(&format!("fila sem decisao ({tipo})")))?;
        if d["tipo"].as_str() != Some(tipo) {
            return Err(ns(&format!("decisao fora de ordem: esperava {tipo}, veio {}", d["tipo"])));
        }
        Ok(d)
    }

    /// Lugar da carta escolhida (lado de quem executa): ("eu"|"oponente", zona, i)
    fn escolha(&mut self, qual: &str) -> R<Option<(String, String, usize)>> {
        let d = self.proxima("escolha_efeito")?;
        if d["qual"].as_str() != Some(qual) {
            return Err(ns(&format!("escolha fora de ordem: esperava {qual}, veio {}", d["qual"])));
        }
        let c = &d["carta"];
        if c.is_null() {
            return Ok(None);
        }
        let a = c.as_array().ok_or_else(|| ns("escolha sem lugar"))?;
        Ok(Some((
            a.first().and_then(|x| x.as_str()).unwrap_or("?").to_string(),
            a.get(1).and_then(|x| x.as_str()).unwrap_or("?").to_string(),
            a.get(2).and_then(|x| x.as_u64()).ok_or_else(|| ns("escolha sem indice"))? as usize,
        )))
    }

    /// `_check_conditions` -- so as chaves conhecidas; qualquer outra = fora do nucleo.
    fn condicoes(&self, conds: &Value, me: &Jogador, opp: &Jogador, fonte: &Carta, gatilho: &str) -> R<bool> {
        let Some(m) = conds.as_object() else { return Ok(true) };
        if m.is_empty() {
            return Ok(true);
        }
        let li = dados(&me.leader)?;
        let fi = dados(fonte)?;
        let mut ok = true;
        for (k, v) in m {
            let n = v.as_i64().unwrap_or(0);
            let r = match k.as_str() {
                "turn_gte" => me.turn >= n,
                "life_lte" => (me.life.len() as i64) <= n,
                "life_gte" => (me.life.len() as i64) >= n,
                "opp_life_lte" => (opp.life.len() as i64) <= n,
                "leader_is" => {
                    let nomes: Vec<String> = match v {
                        Value::Array(a) => a.iter().map(|x| x.as_str().unwrap_or("").to_lowercase()).collect(),
                        Value::String(s) if !s.is_empty() => vec![s.to_lowercase()],
                        _ => vec![],
                    };
                    let ln = li.name.to_lowercase();
                    nomes.iter().any(|x| ln.contains(x.as_str()))
                }
                "leader_type" | "leader_type_includes" => {
                    norm_tipo(&li.sub_types).contains(&norm_tipo(v.as_str().unwrap_or("")))
                }
                "leader_multicolor" => {
                    if v.as_bool().unwrap_or(false) {
                        let cs: std::collections::HashSet<&str> = li
                            .color
                            .split(|c: char| c == '/' || c.is_whitespace())
                            .filter(|x| !x.is_empty())
                            .collect();
                        cs.len() >= 2
                    } else {
                        true
                    }
                }
                "opp_life_gte" => (opp.life.len() as i64) >= n,
                "only_field_type" => {
                    let t = v.as_str().unwrap_or("").to_lowercase();
                    let mut todos = !me.field_chars.is_empty();
                    for c in &me.field_chars {
                        if !dados(c)?.sub_types.to_lowercase().contains(&t) {
                            todos = false;
                        }
                    }
                    todos
                }
                "has_face_up_life" => !v.as_bool().unwrap_or(false) || me.life.iter().any(|c| c.life_face_up),
                "total_life_lte" => ((me.life.len() + opp.life.len()) as i64) <= n,
                "trash_gte" => (me.trash.len() as i64) >= n,
                "trash_lte" => (me.trash.len() as i64) <= n,
                "don_gte" => me.don_available >= n,
                "don_lte" => me.don_available <= n,
                "don_on_field_gte" => me.don_available + me.don_rested >= n,
                "don_on_field_lte" => me.don_available + me.don_rested <= n,
                "don_rested_gte" => me.don_rested >= n,
                "hand_gte" => (me.hand.len() as i64) >= n,
                "hand_lte" => (me.hand.len() as i64) <= n,
                "hand_eq" => (me.hand.len() as i64) == n,
                "deck_lte" => (me.deck.len() as i64) <= n,
                "opp_chars_gte" => (opp.field_chars.len() as i64) >= n,
                "opp_chars_lte" => (opp.field_chars.len() as i64) <= n,
                "opp_hand_gte" => (opp.hand.len() as i64) >= n,
                "self_rested" => !v.as_bool().unwrap_or(false) || fonte.rested,
                "just_played" => !v.as_bool().unwrap_or(false) || fonte.just_played,
                "self_type" => fi.sub_types.to_lowercase().contains(v.as_str().unwrap_or("")),
                "leader_attribute" => li.attribute.to_lowercase().contains(&v.as_str().unwrap_or("").to_lowercase()),
                "opp_leader_attribute" => dados(&opp.leader)?
                    .attribute
                    .to_lowercase()
                    .contains(&v.as_str().unwrap_or("").to_lowercase()),
                "leader_name_includes" => li.name.to_lowercase().contains(&v.as_str().unwrap_or("").to_lowercase()),
                "has_don_attached" => {
                    !v.as_bool().unwrap_or(false)
                        || me.leader.don_attached + me.field_chars.iter().map(|c| c.don_attached).sum::<i64>() > 0
                }
                "own_rested_cards_gte" => {
                    let r = me.don_rested
                        + me.field_chars.iter().filter(|c| c.rested).count() as i64
                        + me.leader.rested as i64
                        + me.stage.as_ref().map_or(0, |s| s.rested as i64);
                    r >= n
                }
                "opp_char_power_gte" => {
                    let mut mx: Option<i64> = None;
                    for c in &opp.field_chars {
                        let base = c.base_power_override.or(c.base_power_override_opp_turn).unwrap_or(dados(c)?.power);
                        let pw = (base + c.power_buff).max(0);
                        mx = Some(mx.map_or(pw, |m: i64| m.max(pw)));
                    }
                    mx.map_or(false, |m| m >= n)
                }
                "board_has_cost" | "board_has_cost_gte" => {
                    let exatos: Vec<i64> = conds["board_has_cost"]
                        .as_array()
                        .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
                        .unwrap_or_default();
                    let gte = conds["board_has_cost_gte"].as_i64();
                    let mut existe = false;
                    for c in me.field_chars.iter().chain(opp.field_chars.iter()) {
                        let cc = dados(c)?.cost;
                        if exatos.contains(&cc) || gte.map_or(false, |g| cc >= g) {
                            existe = true;
                        }
                    }
                    existe
                }
                outro if CONDICOES_DO_PYTHON.contains(&outro) => {
                    return Err(ns(&format!("condicao fora do nucleo: {outro}")))
                }
                // chave que o `_check_conditions` do Python nao olha: nao restringe
                _ => true,
            };
            ok &= r;
        }
        Ok(ok)
    }

    /// `_step_is_viable` (so os passos desta onda; acao desconhecida = fora do nucleo)
    fn viavel(&self, st: &Value, me: &Jogador, opp: &Jogador, fonte: &Carta, gatilho: &str) -> R<bool> {
        if !st["conditions"].is_null() && !self.condicoes(&st["conditions"], me, opp, fonte, gatilho)? {
            return Ok(false);
        }
        if st["source"].as_str() == Some("selected_opp_character") {
            return Err(ns("source selected_opp_character"));
        }
        Ok(match st["action"].as_str().unwrap_or("") {
            "look_top_deck" | "deck_bottom_rest" | "draw" => !me.deck.is_empty(),
            "set_don_active" => me.don_rested > 0,
            "add_to_hand" | "trash_rest" | "gain_life" | "add_don" | "buff_power" | "give_don" | "redirect_attack_target"
            | "activate_trash_event_main" => true,
            "play_from_trash" => !me.trash.is_empty(),
            "play_card" => {
                if st["source"].as_str() == Some("self") {
                    return Err(ns("play_card self: viabilidade pela identidade da carta"));
                }
                let tipo = st["card_type"].as_str().unwrap_or("CHARACTER").to_uppercase();
                let cl = match &st["cost_lte"] {
                    Value::Null => st["total_cost_lte"].as_i64(),
                    Value::String(x) if x == "don_count_self" => Some(me.don_available + me.don_rested),
                    Value::String(x) if x == "don_count_opp" => Some(opp.don_available + opp.don_rested),
                    v => v.as_i64(),
                };
                let mut ok = false;
                for c in &me.hand {
                    let i = dados(c)?;
                    if i.card_type == tipo && cl.map_or(true, |l| i.cost <= l)
                        && st["cost_eq"].as_i64().map_or(true, |x| i.cost == x)
                        && casa_filtro(&i, &st["filter_type"], false)
                    {
                        ok = true;
                    }
                }
                ok
            }
            a @ ("ko" | "rest_opp_character" | "debuff_power") => {
                match st["target"].as_str() {
                    Some("opp_stage") => return Err(ns("alvo opp_stage")),
                    Some("opp_leader") | Some("opp_leader_or_character") | Some("self") => true,
                    _ => {
                        let mut algum = false;
                        for c in &opp.field_chars {
                            if casa_alvo(st, c, a == "rest_opp_character", false, me, opp)? {
                                algum = true;
                            }
                        }
                        if !algum && !st["alt_target"].is_null() {
                            return Err(ns("alt_target"));
                        }
                        algum
                    }
                }
            }
            outro => return Err(ns(&format!("passo fora do nucleo: {outro}"))),
        })
    }

    /// `EffectExecutor.execute(card, gatilho)` para o lado `me` (quem executa).
    pub fn executa(&mut self, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta, gatilho: &str) -> R<()> {
        self.rodou = false;
        let inf = dados(fonte)?;
        let Some(ef) = inf.efeitos.get(gatilho).cloned() else { return Ok(()) };
        if !fonte.effects_negated_until.is_empty() {
            return Ok(());
        }
        let uma_vez = ef["once_per_turn"].as_bool().unwrap_or(false);
        let chave = (self.inst, fonte.code.clone(), gatilho.to_string());
        if uma_vez {
            if self.inst == 0 {
                // executor da Main: `_once_used` dele vem no canonico (`_once_main`)
                let lista = me.extras.get("_once_main").and_then(|v| v.as_array())
                    .ok_or_else(|| ns("once_per_turn sem _once_main no estado"))?;
                if lista.iter().any(|k| k[0].as_str() == Some(&chave.1) && k[1].as_str() == Some(&chave.2)) {
                    return Ok(());
                }
            } else if self.usados.contains(&chave) {
                return Ok(());
            }
        }
        if !self.condicoes(&ef["conditions"], me, opp, fonte, gatilho)? {
            return Ok(());
        }
        let don_req = ef["don_requirement"].as_i64().unwrap_or(0);
        if don_req > 0 && fonte.don_attached < don_req {
            return Ok(());
        }
        let passos: Vec<Value> = ef["steps"].as_array().cloned().unwrap_or_default();
        if passos.is_empty() && !ef["choice"].is_null() {
            return Err(ns("efeito de escolha (choice)"));
        }
        if !passos.is_empty() {
            let mut algum = false;
            for st in &passos {
                if self.viavel(st, me, opp, fonte, gatilho)? {
                    algum = true;
                    break;
                }
            }
            if !algum {
                return Ok(());
            }
        }
        match gatilho {
            "on_play" | "main" | "trigger" => {
                let d = self.proxima("paga_custo")?;
                if d["qual"].as_str() != Some("_worth_paying_optional_costs") {
                    return Err(ns("veredito de custo inesperado"));
                }
                if d["valor"].as_bool() != Some(true) {
                    return Ok(());
                }
            }
            // gatilhos de combate: `_combat_buff_worth_paying`; se ele nao decide
            // (None), `_worth_paying_optional_costs`
            "when_attacking" | "on_opp_attack" | "leader_battle_reactive" => {
                let d = self.proxima("paga_custo")?;
                let v = match d["qual"].as_str() {
                    Some("_combat_buff_worth_paying") if d["valor"].is_null() => {
                        let d2 = self.proxima("paga_custo")?;
                        if d2["qual"].as_str() != Some("_worth_paying_optional_costs") {
                            return Err(ns("veredito de custo inesperado"));
                        }
                        d2["valor"].as_bool()
                    }
                    Some("_combat_buff_worth_paying") => d["valor"].as_bool(),
                    _ => return Err(ns("veredito de combate inesperado")),
                };
                if v != Some(true) {
                    return Ok(());
                }
            }
            // sem portao de custo opcional no Python
            "on_own_char_played" | "on_opp_char_played" | "when_rested" | "on_block" | "on_ko" | "activate_main"
            | "when_damage_or_own_char_ko" | "on_opp_char_ko" | "on_own_char_ko" | "on_any_char_ko" => {}
            outro => return Err(ns(&format!("gatilho fora do nucleo: {outro}"))),
        }
        let custos: Vec<Value> = ef["costs"].as_array().cloned().unwrap_or_default();
        if !self.paga_custos(&custos, me)? {
            return Ok(());
        }
        self.ultimo = None;
        self.rodou = !custos.is_empty() || !passos.is_empty();
        for st in &passos {
            self.passo(st, me, opp, fonte, &inf, gatilho)?;
        }
        if uma_vez {
            if self.inst == 0 {
                let mut lista: Vec<(String, String)> = me.extras["_once_main"].as_array().unwrap().iter()
                    .map(|k| (k[0].as_str().unwrap_or("").to_string(), k[1].as_str().unwrap_or("").to_string()))
                    .collect();
                lista.push((chave.1.clone(), chave.2.clone()));
                lista.sort();
                lista.dedup();
                me.extras.insert("_once_main".into(),
                    Value::Array(lista.into_iter().map(|(a, b)| Value::from(vec![a, b])).collect()));
            } else {
                self.usados.insert(chave);
            }
        }
        Ok(())
    }

    /// `_pay_costs` -- sequencial (pagamento parcial fica, como no Python).
    fn paga_custos(&mut self, custos: &[Value], me: &mut Jogador) -> R<bool> {
        for c in custos {
            let n = c["count"].as_i64().unwrap_or(1);
            match c["type"].as_str().unwrap_or("") {
                "rest_don" => {
                    if me.don_available < n {
                        return Ok(false);
                    }
                    me.don_available -= n;
                    me.don_rested += n;
                }
                "don_minus" => {
                    if !devolve_don(me, n)? {
                        return Ok(false);
                    }
                }
                "trash_from_hand" => {
                    for k in ["color", "power_lte", "power_gte", "power_eq", "cost_lte", "cost_gte", "cost_eq"] {
                        if !c[k].is_null() && c[k].as_str() != Some("") {
                            return Err(ns(&format!("custo trash_from_hand com filtro {k}")));
                        }
                    }
                    let mut pool = 0i64;
                    for h in &me.hand {
                        let hi = dados(h)?;
                        if casa_filtro(&hi, &c["filter_type"], false)
                            && (!c["has_trigger"].as_bool().unwrap_or(false) || hi.has_trigger)
                        {
                            pool += 1;
                        }
                    }
                    if pool < n {
                        return Ok(false);
                    }
                    for _ in 0..n {
                        let Some((lado, z, i)) = self.escolha("descarte")? else { continue };
                        if lado != "eu" || z != "hand" || i >= me.hand.len() {
                            return Err(ns("descarte fora da mao"));
                        }
                        let x = me.hand.remove(i);
                        me.trash.push(x);
                    }
                }
                outro => return Err(ns(&format!("custo fora do nucleo: {outro}"))),
            }
        }
        Ok(true)
    }

    fn passo(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta, inf: &InfoCarta, gatilho: &str) -> R<()> {
        if !st["conditions"].is_null() && !self.condicoes(&st["conditions"], me, opp, fonte, gatilho)? {
            return Ok(());
        }
        for k in ["unless_opp_pays", "requires_own_cost"] {
            if !st[k].is_null() {
                return Err(ns(&format!("passo com {k}")));
            }
        }
        if st["timing"].as_str() == Some("end_of_turn") {
            return Err(ns("passo agendado para o fim do turno"));
        }
        let n = st["count"].as_i64().unwrap_or(1);
        let acao = st["action"].as_str().unwrap_or("");
        match acao {
            "look_top_deck" => {}
            // nao implementados no motor Python (retornam '' sem mudar nada): espelho
            "redirect_attack_target" | "activate_trash_event_main" => {}
            "draw" => {
                let mut n = n;
                match st["count_source"].as_str() {
                    None => {}
                    Some("own_field_type_count") => {
                        n = 0;
                        for c in &me.field_chars {
                            if casa_filtro(&dados(c)?, &st["filter_type"], false) {
                                n += 1;
                            }
                        }
                    }
                    Some(o) => return Err(ns(&format!("draw count_source {o}"))),
                }
                let mut compradas = 0;
                for _ in 0..n {
                    if let Some(c) = me.deck.pop() {
                        me.hand.push(c);
                        compradas += 1;
                    }
                }
                let mut descarta = st["then_trash"].as_i64().unwrap_or(0);
                if st["then_trash_same_as_drawn"].as_bool().unwrap_or(false) {
                    descarta = compradas;
                }
                for _ in 0..descarta {
                    // mao vazia: o diario grava a escolha vazia (None) e a fila a consome
                    let Some((lado, z, i)) = self.escolha("descarte")? else { continue };
                    if lado != "eu" || z != "hand" || i >= me.hand.len() {
                        return Err(ns("descarte fora da mao"));
                    }
                    let x = me.hand.remove(i);
                    me.trash.push(x);
                }
            }
            "add_don" => {
                let m = n.min(me.don_deck);
                me.don_deck -= m;
                if st["rested"].as_bool().unwrap_or(false) {
                    me.don_rested += m;
                } else {
                    me.don_available += m;
                }
            }
            "set_don_active" => {
                let m = n.min(me.don_rested);
                me.don_rested -= m;
                me.don_available += m;
            }
            "gain_life" => {
                if st["source"].as_str().unwrap_or("deck_top") != "deck_top" || !st["power_eq"].is_null() {
                    return Err(ns("gain_life de outra fonte"));
                }
                if !st["then"].is_null() {
                    return Err(ns("gain_life com then"));
                }
                let fundo = st["dest"].as_str() == Some("life_bottom");
                let cima = st["face"].as_str() == Some("up");
                for _ in 0..n {
                    let Some(mut c) = me.deck.pop() else { break };
                    c.life_face_up = cima;
                    if fundo {
                        me.life.insert(0, c);
                    } else {
                        me.life.push(c);
                    }
                }
            }
            "add_to_hand" => self.busca(st, me, inf)?,
            "ko" => self.ko(st, me, opp)?,
            "buff_power" => self.buff(st, me, fonte)?,
            "give_don" => self.da_don(st, me)?,
            "play_from_trash" => self.joga_do_lixo(st, me)?,
            "play_card" => self.joga_carta(st, me, opp, fonte)?,
            "rest_opp_character" => self.restar_oponente(st, me, opp)?,
            "debuff_power" => self.debuff(st, me, opp, fonte)?,
            "trash_rest" | "deck_bottom_rest" => {
                let (olha, pega) = olhar_e_pegar(inf, acao == "deck_bottom_rest");
                let resto = (olha - pega).max(0).min(me.deck.len() as i64);
                for _ in 0..resto {
                    let Some(c) = me.deck.pop() else { break };
                    if acao == "trash_rest" {
                        me.trash.push(c);
                    } else {
                        me.deck.insert(0, c);
                    }
                }
            }
            outro => return Err(ns(&format!("passo fora do nucleo: {outro}"))),
        }
        Ok(())
    }

    /// `add_to_hand` (busca no topo): candidatas reveladas; a(s) escolhida(s)
    /// vem da fila (`busca`), na ordem.
    fn busca(&mut self, st: &Value, me: &mut Jogador, inf: &InfoCarta) -> R<()> {
        if me.deck.is_empty() {
            return Ok(());
        }
        let tem_tipo = st["filter_type"].as_str().map_or(!st["filter_type"].is_null(), |x| !x.is_empty());
        let tem_nome = st["filter_names"].as_array().map_or(false, |a| !a.is_empty());
        if tem_tipo && tem_nome {
            return Err(ns("busca com tipo E nome (uniao)"));
        }
        if !st["cost_lte"].is_null() && !st["cost_lte"].is_i64() {
            return Err(ns("busca com custo dinamico"));
        }
        let (olha, _) = olhar_e_pegar(inf, false);
        let olha = (olha.max(0) as usize).min(me.deck.len());
        let ini = me.deck.len() - olha;
        let cost_lte = st["cost_lte"].as_i64().unwrap_or(99);
        let mut filtradas: Vec<usize> = Vec::new();
        for i in ini..me.deck.len() {
            me.deck[i].revelada |= 1;
            let ci = dados(&me.deck[i])?;
            let nomes: Vec<String> = st["filter_names"]
                .as_array()
                .map(|a| a.iter().map(|x| x.as_str().unwrap_or("").to_lowercase()).collect())
                .unwrap_or_default();
            let excl: Vec<String> = st["exclude"]
                .as_array()
                .map(|a| a.iter().map(|x| x.as_str().unwrap_or("").to_lowercase()).collect())
                .unwrap_or_default();
            let nm = ci.name.to_lowercase();
            if ci.cost <= cost_lte
                && st["cost_gte"].as_i64().map_or(true, |g| ci.cost >= g)
                && ci.power <= st["power_lte"].as_i64().unwrap_or(999_999)
                && st["power_eq"].as_i64().map_or(true, |p| ci.power == p)
                && casa_filtro(&ci, &st["filter_type"], true)
                && (nomes.is_empty() || nomes.iter().any(|x| nm.contains(x.as_str())))
                && !excl.iter().any(|x| nm.contains(x.as_str()))
            {
                filtradas.push(i);
            }
        }
        let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
        let mut pegas: Vec<usize> = Vec::new();
        for _ in 0..n.min(filtradas.len()) {
            let Some((lado, z, i)) = self.escolha("busca")? else { break };
            if lado != "eu" || z != "deck" || !filtradas.contains(&i) {
                return Err(ns("busca escolheu fora das candidatas"));
            }
            filtradas.retain(|&x| x != i);
            pegas.push(i);
        }
        // tira do deck (indices maiores antes) e poe na mao na ordem da escolha
        let mut desc = pegas.clone();
        desc.sort_unstable_by(|a, b| b.cmp(a));
        let mut tiradas: Vec<(usize, Carta)> = Vec::new();
        for i in desc {
            tiradas.push((i, me.deck.remove(i)));
        }
        let mostra = st["revealed_to_opponent"].as_bool() == Some(true);
        for i in pegas {
            let k = tiradas.iter().position(|(j, _)| *j == i).unwrap();
            let mut c = tiradas.remove(k).1;
            if mostra {
                c.revelada |= 1 << 2;
            }
            me.hand.push(c);
        }
        Ok(())
    }
}

impl Executor {
    /// `_dispatch_char_played` (jogada normal da Main: via_effect=False): reativos
    /// `on_own_char_played` do lado de quem jogou e `on_opp_char_played` do outro.
    pub fn dispara_jogou_personagem(&mut self, quem: &mut Jogador, outro: &mut Jogador, jogada: &Carta,
                                    via_efeito: bool) -> R<()> {
        let ij = dados(jogada)?;
        for (gat, lado_quem) in [("on_own_char_played", true), ("on_opp_char_played", false)] {
            let (w, o) = if lado_quem { (&mut *quem, &mut *outro) } else { (&mut *outro, &mut *quem) };
            let mut fontes: Vec<Carta> = vec![w.leader.clone()];
            fontes.extend(w.field_chars.iter().cloned());
            fontes.extend(w.stage.iter().cloned());
            for f in fontes {
                let inf = dados(&f)?;
                let Some(ent) = inf.efeitos.get(gat).cloned() else { continue };
                let alts: Vec<Value> = match ent["play_filter_or"].as_array() {
                    Some(a) if !a.is_empty() => a.clone(),
                    _ => vec![ent.clone()],
                };
                let casa = alts.iter().any(|a| {
                    !(a["play_filter_no_base_effect"].as_bool().unwrap_or(false) && !ij.efeitos.is_empty())
                        && !(a["play_filter_has_trigger"].as_bool().unwrap_or(false) && !ij.has_trigger)
                        && !(a["play_filter_cost_gte"].as_i64().map_or(false, |c| c != 0 && ij.cost < c))
                        && !(a["play_filter_via_effect"].as_bool().unwrap_or(false) && !via_efeito)
                });
                if !casa {
                    continue;
                }
                if ent["once_per_turn"].as_bool().unwrap_or(false) {
                    return Err(ns("reativo once_per_turn (marcador fora do canonico)"));
                }
                let k = self.inst;
                self.inst = 1000 + self.usados.len() as u32 + self.fila.len() as u32;
                let r = self.executa(w, o, &f, gat);
                self.inst = k;
                r?;
            }
        }
        Ok(())
    }

    /// Um reativo de `w` (cada um num `EffectExecutor` novo do Python).
    fn reativo(&mut self, w: &mut Jogador, o: &mut Jogador, gat: &str, inclui_stage: bool,
               filtro: impl Fn(&Value) -> R<bool>) -> R<()> {
        let mut fontes: Vec<(Carta, (String, usize))> = vec![(w.leader.clone(), ("leader".into(), 0))];
        fontes.extend(w.field_chars.iter().cloned().enumerate().map(|(i, c)| (c, ("field_chars".into(), i))));
        if inclui_stage {
            fontes.extend(w.stage.iter().cloned().map(|c| (c, ("stage".into(), 0))));
        }
        for (f, l) in fontes {
            let Some(ent) = dados(&f)?.efeitos.get(gat).cloned() else { continue };
            if !filtro(&ent)? {
                continue;
            }
            let uma_vez = ent["once_per_turn"].as_bool().unwrap_or(false);
            let marca_nome = match gat {
                "when_damage_or_own_char_ko" => "_damage_ko_once_marker",
                "on_opp_char_ko" => "_opp_char_ko_once_marker",
                "on_own_char_ko" => "_own_char_ko_once_marker",
                "on_any_char_ko" => "_any_char_ko_once_marker",
                _ => return Err(ns("marcador desconhecido")),
            };
            let marca = Value::from(vec![Value::from(w.global_turn), Value::from(gat)]);
            if uma_vez && f.extras.get(marca_nome) == Some(&marca) {
                continue;
            }
            let (k, lf) = (self.inst, self.lugar_fonte.take());
            self.inst = 5000 + self.fila.len() as u32 + self.usados.len() as u32;
            self.lugar_fonte = Some(l.clone());
            let r = self.executa(w, o, &f, gat);
            self.inst = k;
            self.lugar_fonte = lf;
            r?;
            if uma_vez && self.rodou {
                let alvo = match l.0.as_str() {
                    "leader" => Some(&mut w.leader),
                    "field_chars" => w.field_chars.get_mut(l.1),
                    _ => w.stage.as_mut(),
                };
                let alvo = alvo.ok_or_else(|| ns("fonte do reativo saiu do lugar"))?;
                if alvo.code != f.code {
                    return Err(ns("fonte do reativo saiu do lugar"));
                }
                alvo.extras.insert(marca_nome.into(), marca);
            }
        }
        Ok(())
    }

    /// `_dispatch_damage_or_own_char_ko(dono)`: dano na vida (vitima None) ou KO
    /// de personagem do `dono`.
    pub fn dispara_dano_ou_ko(&mut self, dono: &mut Jogador, outro: &mut Jogador, vitima: Option<&Carta>) -> R<()> {
        let pw = match vitima { Some(v) => Some(dados(v)?.power), None => None };
        self.reativo(dono, outro, "when_damage_or_own_char_ko", false, |e| {
            Ok(pw.map_or(true, |p| p >= e["own_char_base_power_gte"].as_i64().unwrap_or(0)))
        })
    }

    /// `_dispatch_opp_char_ko` + `_dispatch_own_char_ko` + `_dispatch_any_char_ko`
    /// depois do KO de um personagem de `dono` (na ordem do motor).
    pub fn dispara_ko(&mut self, dono: &mut Jogador, outro: &mut Jogador, vitima: &Carta) -> R<()> {
        let vi = dados(vitima)?;
        self.reativo(outro, dono, "on_opp_char_ko", true, |_| Ok(true))?;
        self.reativo(dono, outro, "on_own_char_ko", true, |e| {
            let f = &e["victim_type_filter"];
            let tem_f = f.as_str().map_or(!f.is_null(), |x| !x.is_empty());
            Ok((!tem_f || casa_filtro(&vi, f, false))
                && e["victim_power_gte"].as_i64().map_or(true, |p| p == 0 || vi.power >= p))
        })?;
        for lado_dono in [true, false] {
            let (w, o) = if lado_dono { (&mut *dono, &mut *outro) } else { (&mut *outro, &mut *dono) };
            self.reativo(w, o, "on_any_char_ko", true, |e| {
                let f = &e["victim_type_filter"];
                let tem_f = f.as_str().map_or(!f.is_null(), |x| !x.is_empty());
                Ok(!tem_f || casa_filtro(&vi, f, false))
            })?;
        }
        Ok(())
    }

    /// `_dispatch_event_activated`: reativos de evento ainda fora do nucleo.
    pub fn confere_evento_ativado(&self, a: &Jogador, b: &Jogador) -> R<()> {
        for (j, gat) in [(a, "on_own_event_activated"), (b, "on_opp_event_activated")] {
            let fontes = std::iter::once(&j.leader).chain(j.field_chars.iter()).chain(j.stage.iter());
            for c in fontes {
                if dados(c)?.efeitos.contains_key(gat) {
                    return Err(ns(&format!("reativo {gat}")));
                }
            }
        }
        Ok(())
    }
}

/// `eligible_cards` dos passos de alvo no oponente (`_step_is_viable` e execucao):
/// cost_lte (fixo ou DON em campo), cost_eq, power_lte (impresso), don_attached_gte,
/// rested_only, active_only, filter_type (sem texto), exclude.
fn casa_alvo(st: &Value, c: &Carta, active_only: bool, usa_filter_types: bool, me: &Jogador, opp: &Jogador) -> R<bool> {
    let i = dados(c)?;
    let cost_lte = match &st["cost_lte"] {
        Value::Null => None,
        Value::String(x) if x == "don_count_self" => Some(me.don_available + me.don_rested),
        Value::String(x) if x == "don_count_opp" => Some(opp.don_available + opp.don_rested),
        v => Some(v.as_i64().ok_or_else(|| ns("cost_lte inesperado"))?),
    };
    let filtro = if usa_filter_types && !st["filter_types"].is_null() { &st["filter_types"] } else { &st["filter_type"] };
    let excl = st["exclude"].as_str().unwrap_or("").to_lowercase();
    Ok(cost_lte.map_or(true, |l| i.cost <= l)
        && st["cost_eq"].as_i64().map_or(true, |x| i.cost == x)
        && st["power_lte"].as_i64().map_or(true, |x| i.power <= x)
        && st["don_attached_gte"].as_i64().map_or(true, |x| c.don_attached >= x)
        && (!st["rested_only"].as_bool().unwrap_or(false) || c.rested)
        && (!active_only || !c.rested)
        && casa_filtro(&i, filtro, false)
        && (excl.is_empty() || !i.name.to_lowercase().contains(&excl)))
}

/// Alguma carta do lado tem passo com acao contendo `trecho` (imunidade/substituicao
/// ainda fora do nucleo: se existir, o resultado nao e garantido)
pub fn lado_tem_acao(j: &Jogador, trecho: &str) -> R<bool> {
    let cartas = std::iter::once(&j.leader).chain(j.field_chars.iter()).chain(j.stage.iter());
    for c in cartas {
        for b in dados(c)?.efeitos.values() {
            if passos_de(b).any(|s| s["action"].as_str().map_or(false, |a| a.contains(trecho))) {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

pub const REATIVOS_DE_KO: &[&str] = &["when_damage_or_own_char_ko", "on_opp_char_ko", "on_own_char_ko",
    "on_any_char_ko", "on_own_effect_removes_char"];

pub fn tem_reativo(j: &Jogador, chaves: &[&str]) -> R<bool> {
    let cartas = std::iter::once(&j.leader).chain(j.field_chars.iter()).chain(j.stage.iter());
    for c in cartas {
        let inf = dados(c)?;
        if chaves.iter().any(|k| inf.efeitos.contains_key(*k)) {
            return Ok(true);
        }
    }
    Ok(false)
}

impl Executor {
    /// Escolha de alvo (`_pick_effect_target`) que tem que estar entre os candidatos.
    fn alvo_no_oponente(&mut self, cands: &[usize]) -> R<usize> {
        match self.escolha("alvo")? {
            Some((l, z, i)) if l == "oponente" && z == "field_chars" && cands.contains(&i) => Ok(i),
            outro => Err(ns(&format!("alvo fora dos candidatos: {outro:?}"))),
        }
    }

    /// `ko` em personagem do oponente (sem orcamento total, sem stage).
    fn ko(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador) -> R<()> {
        let t = st["target"].as_str().unwrap_or("opp_character");
        if t != "opp_character" {
            return Err(ns(&format!("ko com alvo {t}")));
        }
        for k in ["total_power_lte", "total_cost_lte", "alt_target"] {
            if !st[k].is_null() {
                return Err(ns(&format!("ko com {k}")));
            }
        }
        if lado_tem_acao(opp, "substitute")? || lado_tem_acao(opp, "immunity")?
            || lado_tem_acao(opp, "ko_immunity")?
        {
            return Err(ns("imunidade/substituicao no lado do alvo"));
        }
        if tem_reativo(me, REATIVOS_DE_KO)? || tem_reativo(opp, REATIVOS_DE_KO)? {
            return Err(ns("reativo de KO"));
        }
        let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
        let mut cands: Vec<usize> = Vec::new();
        for (i, c) in opp.field_chars.iter().enumerate() {
            if casa_alvo(st, c, false, false, me, opp)? {
                cands.push(i);
            }
        }
        for _ in 0..n.min(cands.len()) {
            let i = self.alvo_no_oponente(&cands)?;
            let c = &opp.field_chars[i];
            if !c.immunity_ko_until.is_empty() {
                return Err(ns("alvo com imunidade a KO"));
            }
            if dados(c)?.efeitos.contains_key("on_ko") {
                return Err(ns("on_ko do alvo"));
            }
            let mut x = opp.field_chars.remove(i);
            if x.don_attached > 0 {
                opp.don_rested += x.don_attached;
                x.don_attached = 0;
            }
            opp.trash.push(x);
            cands.retain(|&j| j != i);
            for j in cands.iter_mut() {
                if *j > i {
                    *j -= 1;
                }
            }
        }
        Ok(())
    }

    /// `buff_power` (a duracao nao muda a execucao: o buff some no inicio do turno)
    fn buff(&mut self, st: &Value, me: &mut Jogador, fonte: &Carta) -> R<()> {
        let v = st["amount"].as_i64().unwrap_or(0);
        match st["target"].as_str().unwrap_or("self") {
            "self" => {
                let (z, i) = self.lugar_fonte.clone().ok_or_else(|| ns("buff self sem fonte no campo"))?;
                let c = match z.as_str() {
                    "leader" => &mut me.leader,
                    "field_chars" => me.field_chars.get_mut(i).ok_or_else(|| ns("fonte fora do campo"))?,
                    _ => return Err(ns("fonte em zona inesperada")),
                };
                if c.code != fonte.code {
                    return Err(ns("fonte mudou de lugar"));
                }
                c.power_buff += v;
            }
            "leader" => {
                if let Some(l) = st["power_lte"].as_i64() {
                    if poder_meu_turno(&me.leader)? > l {
                        return Ok(());
                    }
                }
                me.leader.power_buff += v;
            }
            "leader_or_character" => {
                // regra de hoje: o de maior poder efetivo (max = primeiro em empate)
                let mut pool: Vec<Option<usize>> = (0..me.field_chars.len()).map(Some).collect();
                pool.push(None);
                let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
                let mut best = None;
                for _ in 0..n.min(pool.len()) {
                    let mut bi = 0;
                    let mut bp = i64::MIN;
                    for (k, x) in pool.iter().enumerate() {
                        let pw = poder_meu_turno(carta_mut(me, *x)?)?;
                        if pw > bp {
                            bp = pw;
                            bi = k;
                        }
                    }
                    let x = pool.remove(bi);
                    carta_mut(me, x)?.power_buff += v;
                    best = Some(x);
                }
                self.ultimo = best;
            }
            "selected" => {
                let Some(x) = self.ultimo else { return Ok(()) };
                carta_mut(me, x)?.power_buff += v;
            }
            t @ ("all_allies" | "all_allies_and_leader") => {
                if st["exclude_self"].as_bool().unwrap_or(false) {
                    return Err(ns("buff all_allies exclude_self"));
                }
                let nomes: Vec<String> = st["filter_names"].as_array()
                    .map(|a| a.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect())
                    .unwrap_or_default();
                let cor = st["filter_color"].as_str().unwrap_or("").to_lowercase();
                for k in 0..me.field_chars.len() {
                    let i = dados(&me.field_chars[k])?;
                    let nm = i.name.to_lowercase();
                    let ok = casa_filtro(&i, &st["filter_type"], false)
                        && (nomes.is_empty() || nomes.iter().any(|x| nm.contains(x.as_str())))
                        && st["cost_lte"].as_i64().map_or(true, |x| i.cost <= x)
                        && st["cost_gte"].as_i64().map_or(true, |x| i.cost >= x)
                        && (cor.is_empty() || i.color.to_lowercase().contains(&cor))
                        && st["power_lte"].as_i64().map_or(true, |x| i.power <= x);
                    if ok {
                        me.field_chars[k].power_buff += v;
                    }
                }
                if t == "all_allies_and_leader" {
                    me.leader.power_buff += v;
                }
            }
            "select_filtered" => {
                let excl = st["exclude"].as_str().unwrap_or("").to_lowercase();
                let mut cands: Vec<Option<usize>> = Vec::new();
                for x in (0..me.field_chars.len()).map(Some).chain(std::iter::once(None)) {
                    let i = dados(carta_mut(me, x)?)?;
                    if casa_filtro(&i, &st["filter_type"], false)
                        && (excl.is_empty() || !i.name.to_lowercase().contains(&excl))
                    {
                        cands.push(x);
                    }
                }
                if cands.is_empty() {
                    return Ok(());
                }
                let x = self.alvo_meu(&cands)?;
                carta_mut(me, x)?.power_buff += v;
                self.ultimo = Some(x);
            }
            "own_character" => {
                for k in ["filter_type_or_has_trigger", "filter_no_effect", "filter_color"] {
                    if !st[k].is_null() && st[k] != Value::Bool(false) && st[k].as_str() != Some("") {
                        return Err(ns(&format!("buff own_character com {k}")));
                    }
                }
                let excl = st["exclude"].as_str().unwrap_or("").to_lowercase();
                let mut cands: Vec<Option<usize>> = Vec::new();
                for k in 0..me.field_chars.len() {
                    let i = dados(&me.field_chars[k])?;
                    if st["power_lte"].as_i64().map_or(true, |x| i.power <= x)
                        && st["cost_lte"].as_i64().map_or(true, |x| i.cost <= x)
                        && st["cost_gte"].as_i64().map_or(true, |x| i.cost >= x)
                        && st["cost_eq"].as_i64().map_or(true, |x| i.cost == x)
                        && (excl.is_empty() || !i.name.to_lowercase().contains(&excl))
                    {
                        cands.push(Some(k));
                    }
                }
                let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
                for _ in 0..n {
                    if cands.is_empty() {
                        break;
                    }
                    let x = self.alvo_meu(&cands)?;
                    cands.retain(|y| *y != x);
                    carta_mut(me, x)?.power_buff += v;
                }
            }
            outro => return Err(ns(&format!("buff alvo {outro}"))),
        }
        Ok(())
    }

    /// `give_don`: quem recebe e quantos e DECISAO (vem da fila); a regra e de
    /// onde o DON sai (restado primeiro; `rested=True` so do restado).
    fn da_don(&mut self, st: &Value, me: &mut Jogador) -> R<()> {
        let nome = st["target_name"].as_str().unwrap_or("").to_lowercase();
        let mut alvos: Vec<Option<usize>> = Vec::new();
        let ordem: Vec<Option<usize>> = (0..me.field_chars.len()).filter(|&i| !me.field_chars[i].rested)
            .map(Some).chain(std::iter::once(None)).collect();
        for x in ordem {
            let i = dados(carta_mut(me, x)?)?;
            if (nome.is_empty() || i.name.to_lowercase().contains(&nome))
                && casa_filtro(&i, &st["filter_type"], false)
            {
                alvos.push(x);
            }
        }
        if alvos.is_empty() {
            return Ok(());
        }
        let d = self.proxima("escolha_efeito")?;
        if d["qual"].as_str() != Some("give_don") {
            return Err(ns("decisao de give_don fora de ordem"));
        }
        let x = match d["carta"].as_array().map(|a| (a[0].as_str(), a[1].as_str(), a[2].as_u64())) {
            Some((Some("eu"), Some("field_chars"), Some(i))) => Some(i as usize),
            Some((Some("eu"), Some("leader"), _)) => None,
            _ => return Err(ns("give_don sem alvo valido")),
        };
        if !alvos.contains(&x) {
            return Err(ns("give_don fora dos alvos"));
        }
        let t = d["qtd"].as_i64().unwrap_or(0);
        if st["rested"].as_bool().unwrap_or(false) {
            if t > me.don_rested {
                return Err(ns("give_don maior que o DON restado"));
            }
            me.don_rested -= t;
        } else {
            let r = t.min(me.don_rested);
            if t - r > me.don_available {
                return Err(ns("give_don maior que o DON"));
            }
            me.don_rested -= r;
            me.don_available -= t - r;
        }
        carta_mut(me, x)?.don_attached += t;
        if t > 0 && tem_reativo(me, &["on_don_given"])? {
            return Err(ns("reativo on_don_given"));
        }
        Ok(())
    }

    fn veredito(&mut self, qual: &str) -> R<bool> {
        let d = self.proxima("veredito_efeito")?;
        if d["qual"].as_str() != Some(qual) {
            return Err(ns(&format!("veredito fora de ordem: esperava {qual}, veio {}", d["qual"])));
        }
        Ok(d["valor"].as_bool().unwrap_or(false))
    }

    /// Campo cheio dentro de efeito: quem sai e decisao (fila `sai_campo`).
    fn sai_do_campo(&mut self, me: &mut Jogador) -> R<()> {
        match self.escolha("sai_campo")? {
            None => Ok(()),
            Some((l, z, i)) if l == "eu" && z == "field_chars" && i < me.field_chars.len() => {
                crate::acoes::tira_do_campo_para_lixo(me, i);
                Ok(())
            }
            outro => Err(ns(&format!("sai_campo inesperado: {outro:?}"))),
        }
    }

    /// Personagem entra no campo por efeito (rested, just_played, rush de personagem).
    fn entra_personagem(me: &mut Jogador, mut c: Carta, rested: bool) -> R<()> {
        let i = dados(&c)?;
        c.rested = rested;
        c.just_played = !(c.has_rush || c.rush_this_turn || crate::acoes::is_rush_character(&c, &i));
        c.rush_character_only_this_turn =
            crate::acoes::is_rush_character(&c, &i) && !crate::acoes::is_rush(&c, &i);
        me.field_chars.push(c);
        Ok(())
    }

    /// `play_from_trash` (sem on_play -- igual ao motor de hoje)
    fn joga_do_lixo(&mut self, st: &Value, me: &mut Jogador) -> R<()> {
        for k in ["filter_self", "same_name_as_trashed"] {
            if st[k].as_bool().unwrap_or(false) {
                return Err(ns(&format!("play_from_trash {k}")));
            }
        }
        let cl = match &st["cost_lte"] {
            Value::Null => None,
            Value::String(x) if x == "don_count_self" => Some(me.don_available + me.don_rested),
            v => Some(v.as_i64().ok_or_else(|| ns("cost_lte inesperado"))?),
        };
        let nome = st["filter_name"].as_str().unwrap_or("").to_lowercase();
        let excl = st["exclude"].as_str().unwrap_or("").to_lowercase();
        let mut cands: Vec<usize> = Vec::new();
        for (k, c) in me.trash.iter().enumerate() {
            let i = dados(c)?;
            if cl.map_or(true, |l| i.cost <= l)
                && st["cost_eq"].as_i64().map_or(true, |x| i.cost == x)
                && st["power_eq"].as_i64().map_or(true, |x| i.power == x)
                && st["power_lte"].as_i64().map_or(true, |x| i.power <= x)
                && st["power_gte"].as_i64().map_or(true, |x| i.power >= x)
                && (!st["has_trigger"].as_bool().unwrap_or(false) || i.has_trigger)
                && casa_filtro(&i, &Value::from(st["filter_type"].as_str().unwrap_or("").to_lowercase()), false)
                && (nome.is_empty() || i.name.to_lowercase().contains(&nome) || c.code.to_lowercase().contains(&nome))
                && (excl.is_empty() || !i.name.to_lowercase().contains(&excl))
            {
                cands.push(k);
            }
        }
        let distintos = st["distinct_names"].as_bool().unwrap_or(false);
        let rested = st["rested"].as_bool().unwrap_or(false);
        let mut nomes: Vec<String> = Vec::new();
        let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
        for _ in 0..n.min(cands.len()) {
            let mut pool = cands.clone();
            if distintos {
                let mut p2 = Vec::new();
                for &k in &pool {
                    if !nomes.contains(&dados(&me.trash[k])?.name.to_lowercase()) {
                        p2.push(k);
                    }
                }
                pool = p2;
            }
            if pool.is_empty() {
                break;
            }
            let k = match self.escolha("do_lixo")? {
                Some((l, z, i)) if l == "eu" && z == "trash" && pool.contains(&i) => i,
                outro => return Err(ns(&format!("do_lixo inesperado: {outro:?}"))),
            };
            let mut c = me.trash.remove(k);
            cands.retain(|&j| j != k);
            for j in cands.iter_mut() {
                if *j > k {
                    *j -= 1;
                }
            }
            let i = dados(&c)?;
            nomes.push(i.name.to_lowercase());
            if i.card_type == "STAGE" {
                c.rested = rested;
                if let Some(v) = me.stage.take() {
                    me.trash.push(v);
                }
                me.stage = Some(c);
            } else {
                if me.field_chars.len() >= 5 {
                    self.sai_do_campo(me)?;
                }
                Self::entra_personagem(me, c, rested)?;
            }
        }
        Ok(())
    }

    /// `play_card` (jogar de graca por efeito): qual carta vem da fila
    /// (`jogar_gratis`), a troca no campo cheio tambem. on_play/main aninhados.
    fn joga_carta(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta) -> R<()> {
        if st["source"].as_str() == Some("self") {
            return Err(ns("play_card self"));
        }
        for k in ["each", "filter_no_effect", "exclude_color_of_selected", "color", "power_lte",
                  "power_gte", "power_eq", "filter_names", "filter_name", "exclude"] {
            if !st[k].is_null() && st[k] != Value::Bool(false) && st[k].as_str() != Some("") {
                return Err(ns(&format!("play_card com {k}")));
            }
        }
        let _ = fonte;
        let tipo = st["card_type"].as_str().unwrap_or("CHARACTER").to_uppercase();
        let cl = match &st["cost_lte"] {
            Value::Null => None,
            Value::String(x) if x == "don_count_self" => Some(me.don_available + me.don_rested),
            Value::String(x) if x == "don_count_opp" => Some(opp.don_available + opp.don_rested),
            v => Some(v.as_i64().ok_or_else(|| ns("cost_lte inesperado"))?),
        };
        // elegiveis por LUGAR: ("hand"|"trash", i)
        let mut eleg: Vec<(String, usize)> = Vec::new();
        let zonas: Vec<&str> = if st["source_alt"].as_str() == Some("trash") { vec!["hand", "trash"] } else { vec!["hand"] };
        for z in &zonas {
            let lista = if *z == "hand" { &me.hand } else { &me.trash };
            for (k, c) in lista.iter().enumerate() {
                let i = dados(c)?;
                if i.card_type == tipo && cl.map_or(true, |l| i.cost <= l)
                    && st["cost_eq"].as_i64().map_or(true, |x| i.cost == x)
                    && (!st["has_trigger"].as_bool().unwrap_or(false) || i.has_trigger)
                    && casa_filtro(&i, &st["filter_type"], false)
                {
                    eleg.push((z.to_string(), k));
                }
            }
        }
        if eleg.is_empty() {
            return Ok(());
        }
        let n = st["count"].as_i64().unwrap_or(1).max(0);
        let mut orc = st["total_cost_lte"].as_i64();
        let distintos = st["distinct_names"].as_bool().unwrap_or(false);
        let mut nomes: Vec<String> = Vec::new();
        for _ in 0..n {
            let mut pool: Vec<(String, usize)> = Vec::new();
            for (z, k) in &eleg {
                let c = if z == "hand" { &me.hand[*k] } else { &me.trash[*k] };
                let i = dados(c)?;
                if (!distintos || !nomes.contains(&i.name.to_lowercase())) && orc.map_or(true, |o| i.cost <= o) {
                    pool.push((z.clone(), *k));
                }
            }
            if pool.is_empty() {
                break;
            }
            // escolhe_carta_para_jogar -> _q_escolhe_carta('jogar_gratis')
            let (z, k) = match self.escolha("jogar_gratis")? {
                Some((l, z, i)) if l == "eu" && pool.contains(&(z.clone(), i)) => (z, i),
                outro => return Err(ns(&format!("jogar_gratis inesperado: {outro:?}"))),
            };
            let ci = dados(if z == "hand" { &me.hand[k] } else { &me.trash[k] })?;
            if ci.card_type == "CHARACTER" && me.field_chars.len() >= 5 && !self.veredito("troca_campo")? {
                eleg.retain(|x| *x != (z.clone(), k));
                continue;
            }
            let c = if z == "hand" { me.hand.remove(k) } else { me.trash.remove(k) };
            eleg.retain(|x| *x != (z.clone(), k));
            for x in eleg.iter_mut() {
                if x.0 == z && x.1 > k {
                    x.1 -= 1;
                }
            }
            if distintos {
                nomes.push(ci.name.to_lowercase());
            }
            if let Some(o) = orc.as_mut() {
                *o -= ci.cost;
            }
            // _put_into_play
            let lf = self.lugar_fonte.take();
            match ci.card_type.as_str() {
                "CHARACTER" => {
                    if me.field_chars.len() >= 5 {
                        self.sai_do_campo(me)?;
                    }
                    Self::entra_personagem(me, c, false)?;
                    let nova = me.field_chars.last().unwrap().clone();
                    self.dispara_jogou_personagem(me, opp, &nova, true)?;
                    self.lugar_fonte = Some(("field_chars".into(), me.field_chars.len() - 1));
                }
                "STAGE" => {
                    if let Some(v) = me.stage.take() {
                        me.trash.push(v);
                    }
                    me.stage = Some(c);
                }
                _ => return Err(ns("play_card de evento")),
            }
            let nova = match ci.card_type.as_str() {
                "CHARACTER" => me.field_chars.last().unwrap().clone(),
                _ => me.stage.clone().unwrap(),
            };
            if self.inst >= 10 && dados(&nova)?.efeitos.get("on_play").map_or(false, |b| !b["conditions"]["your_turn_only"].is_null()) {
                return Err(ns("on_play your_turn_only fora do proprio turno"));
            }
            let ult = self.ultimo;
            self.executa(me, opp, &nova, "on_play")?;
            self.executa(me, opp, &nova, "main")?;
            self.ultimo = ult.and(None); // execute aninhado zera `_last_selected`
            self.lugar_fonte = lf;
            if st["enters_rested"].as_bool().unwrap_or(false) {
                let c = if ci.card_type == "CHARACTER" {
                    me.field_chars.iter_mut().rev().find(|x| x.code == nova.code)
                } else {
                    me.stage.as_mut()
                };
                if let Some(c) = c {
                    c.rested = true;
                }
            }
        }
        Ok(())
    }

    /// Alvo do proprio lado (lider = None)
    fn alvo_meu(&mut self, cands: &[Option<usize>]) -> R<Option<usize>> {
        let x = match self.escolha("alvo")? {
            Some((l, z, i)) if l == "eu" && z == "field_chars" => Some(i),
            Some((l, z, _)) if l == "eu" && z == "leader" => None,
            outro => return Err(ns(&format!("alvo inesperado: {outro:?}"))),
        };
        if !cands.contains(&x) {
            return Err(ns("alvo fora dos candidatos"));
        }
        Ok(x)
    }

    /// `rest_opp_character`
    fn restar_oponente(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador) -> R<()> {
        if lado_tem_acao(opp, "substitute")? || lado_tem_acao(opp, "immunity")? {
            return Err(ns("imunidade/substituicao no lado do alvo"));
        }
        let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
        let st2 = {
            let mut v = st.clone();
            if v["cost_lte"].is_null() {
                v["cost_lte"] = Value::from(99);
            }
            v
        };
        let mut cands: Vec<usize> = Vec::new();
        for (i, c) in opp.field_chars.iter().enumerate() {
            if c.cannot_be_rested_until.is_empty() && casa_alvo(&st2, c, true, true, me, opp)? {
                cands.push(i);
            }
        }
        let mut feitos = 0;
        for _ in 0..n.min(cands.len()) {
            let i = self.alvo_no_oponente(&cands)?;
            opp.field_chars[i].rested = true;
            cands.retain(|&j| j != i);
            feitos += 1;
        }
        if st["or_rest_opp_don"].as_bool().unwrap_or(false) {
            let m = (n as i64 - feitos).max(0).min(opp.don_available);
            opp.don_available -= m;
            opp.don_rested += m;
        }
        Ok(())
    }

    /// `debuff_power` (fora de batalha: sem atacante em curso)
    fn debuff(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta) -> R<()> {
        let _ = me;
        let v = st["amount"].as_i64().unwrap_or(0);
        let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
        match st["target"].as_str().unwrap_or("opp_character") {
            "self" => {
                let _ = fonte;
                return Err(ns("debuff_power self (fonte no campo)"));
            }
            "opp_leader" => opp.leader.power_buff -= v,
            "all_opp_characters" => {
                if st["per_don_attached"].as_bool().unwrap_or(false) {
                    return Err(ns("debuff por DON anexado"));
                }
                for c in opp.field_chars.iter_mut() {
                    c.power_buff -= v;
                }
            }
            "opp_character" => {
                if opp.field_chars.is_empty() {
                    return Ok(());
                }
                let ativos: Vec<usize> = (0..opp.field_chars.len()).filter(|&i| !opp.field_chars[i].rested).collect();
                let mut cands = if ativos.is_empty() { (0..opp.field_chars.len()).collect() } else { ativos };
                for _ in 0..n.min(cands.len()) {
                    let i = self.alvo_no_oponente(&cands)?;
                    opp.field_chars[i].power_buff -= v;
                    cands.retain(|&j| j != i);
                }
            }
            "opp_leader_or_character" => {
                // candidatos: personagens ativos e o lider (se ativo), nessa ordem
                let mut cands: Vec<Option<usize>> =
                    (0..opp.field_chars.len()).filter(|&i| !opp.field_chars[i].rested).map(Some).collect();
                if !opp.leader.rested {
                    cands.push(None);
                }
                if cands.is_empty() {
                    cands = (0..opp.field_chars.len()).map(Some).collect();
                    cands.push(None);
                }
                for _ in 0..n.min(cands.len()) {
                    let e = match self.escolha("alvo")? {
                        Some((l, z, i)) if l == "oponente" && z == "field_chars" => Some(i),
                        Some((l, z, _)) if l == "oponente" && z == "leader" => None,
                        outro => return Err(ns(&format!("alvo inesperado: {outro:?}"))),
                    };
                    if !cands.contains(&e) {
                        return Err(ns("alvo fora dos candidatos"));
                    }
                    match e {
                        Some(i) => opp.field_chars[i].power_buff -= v,
                        None => opp.leader.power_buff -= v,
                    }
                    cands.retain(|x| *x != e);
                }
            }
            outro => return Err(ns(&format!("debuff alvo {outro}"))),
        }
        Ok(())
    }
}

/// look_count / taken_count de `trash_rest` (PRIMEIRO de cada no banco, com
/// break) e de `deck_bottom_rest` (o ULTIMO de cada: laco sem break no Python).
fn olhar_e_pegar(inf: &InfoCarta, ultimo: bool) -> (i64, i64) {
    let (mut olha, mut pega) = (5, 1);
    if ultimo {
        for b in inf.efeitos.values() {
            for s in passos_de(b) {
                match s["action"].as_str().unwrap_or("") {
                    "look_top_deck" => olha = s["count"].as_i64().unwrap_or(5),
                    "add_to_hand" | "trash_from_looked_deck" => pega = s["count"].as_i64().unwrap_or(1),
                    _ => {}
                }
            }
        }
        return (olha, pega);
    }
    // trash_rest: dois lacos com `break` so do laco interno (o externo continua
    // e pode sobrescrever com o primeiro passo de um bloco SEGUINTE)
    for b in inf.efeitos.values() {
        if let Some(s) = passos_de(b).find(|s| s["action"].as_str() == Some("look_top_deck")) {
            olha = s["count"].as_i64().unwrap_or(5);
        }
    }
    for b in inf.efeitos.values() {
        if let Some(s) = passos_de(b).find(|s| {
            matches!(s["action"].as_str(), Some("add_to_hand") | Some("trash_from_looked_deck"))
        }) {
            pega = s["count"].as_i64().unwrap_or(1);
        }
    }
    (olha, pega)
}

/// `_return_don_to_deck` (custo DON!! -X), mesma ordem de preferencia.
/// (`exclude_card` so vale para o proprio atacante em when_attacking -- fora desta onda)
fn devolve_don(me: &mut Jogador, n: i64) -> R<bool> {
    let mut dev = 0;
    for c in me.field_chars.iter_mut() {
        while c.don_attached > 0 && c.rested && dev < n {
            c.don_attached -= 1;
            me.don_deck += 1;
            dev += 1;
        }
    }
    while me.leader.don_attached > 0 && me.leader.rested && dev < n {
        me.leader.don_attached -= 1;
        me.don_deck += 1;
        dev += 1;
    }
    while me.don_rested > 0 && dev < n {
        me.don_rested -= 1;
        me.don_deck += 1;
        dev += 1;
    }
    if dev < n {
        for c in me.field_chars.iter_mut() {
            while c.don_attached > 0 && dev < n {
                c.don_attached -= 1;
                me.don_deck += 1;
                dev += 1;
            }
        }
        while me.leader.don_attached > 0 && dev < n {
            me.leader.don_attached -= 1;
            me.don_deck += 1;
            dev += 1;
        }
        while me.don_available > 0 && dev < n {
            me.don_available -= 1;
            me.don_deck += 1;
            dev += 1;
        }
    }
    if dev > 0 {
        // _dispatch_don_returned: reativos when_don_returned ficam fora desta onda
        let fontes = std::iter::once(&me.leader).chain(me.field_chars.iter()).chain(me.stage.iter());
        for c in fontes {
            if dados(c)?.efeitos.keys().any(|k| k.starts_with("when_don_returned")) {
                return Err(ns("when_don_returned"));
            }
        }
    }
    Ok(dev >= n)
}
