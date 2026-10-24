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
            "add_to_hand" | "trash_rest" | "gain_life" | "add_don" => true,
            outro => return Err(ns(&format!("passo fora do nucleo: {outro}"))),
        })
    }

    /// `EffectExecutor.execute(card, gatilho)` para o lado `me` (quem executa).
    pub fn executa(&mut self, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta, gatilho: &str) -> R<()> {
        let inf = dados(fonte)?;
        let Some(ef) = inf.efeitos.get(gatilho).cloned() else { return Ok(()) };
        if !fonte.effects_negated_until.is_empty() {
            return Ok(());
        }
        if ef["once_per_turn"].as_bool().unwrap_or(false) {
            return Err(ns("once_per_turn (estado do executor fora do canonico)"));
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
            // reativos de "jogou personagem": sem portao de custo opcional no Python
            "on_own_char_played" | "on_opp_char_played" => {}
            outro => return Err(ns(&format!("gatilho fora do nucleo: {outro}"))),
        }
        let custos: Vec<Value> = ef["costs"].as_array().cloned().unwrap_or_default();
        if !self.paga_custos(&custos, me)? {
            return Ok(());
        }
        for st in &passos {
            self.passo(st, me, opp, fonte, &inf, gatilho)?;
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
            "draw" => {
                if !st["count_source"].is_null() || !st["then_trash"].is_null()
                    || !st["then_trash_same_as_drawn"].is_null()
                {
                    return Err(ns("draw com variacao"));
                }
                for _ in 0..n {
                    if let Some(c) = me.deck.pop() {
                        me.hand.push(c);
                    }
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
    pub fn dispara_jogou_personagem(&mut self, quem: &mut Jogador, outro: &mut Jogador, jogada: &Carta) -> R<()> {
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
                        && !a["play_filter_via_effect"].as_bool().unwrap_or(false)
                });
                if !casa {
                    continue;
                }
                if ent["once_per_turn"].as_bool().unwrap_or(false) {
                    return Err(ns("reativo once_per_turn (marcador fora do canonico)"));
                }
                self.executa(w, o, &f, gat)?;
            }
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
