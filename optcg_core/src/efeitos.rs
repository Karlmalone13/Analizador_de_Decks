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
use std::cell::RefCell;
use std::collections::VecDeque;
use std::rc::Rc;

/// Lugar de uma carta do ponto de vista de quem executa: ("eu"|"oponente", zona, indice)
pub type Lug = (String, String, usize);

/// Quem decide as escolhas internas quando NAO ha diario (simulacao / busca).
/// No teste de paridade a politica e None e as escolhas vem do diario do Python.
pub trait Politica {
    /// indice em `n` opcoes (None = nenhuma, so quando `pode_nenhuma`)
    fn escolhe(&mut self, qual: &str, n: usize, pode_nenhuma: bool) -> Option<usize>;
    fn veredito(&mut self, qual: &str) -> bool;
}

pub type PoliticaRef = Rc<RefCell<dyn Politica>>;

fn lug(lado: &str, z: &str, i: usize) -> Lug {
    (lado.to_string(), z.to_string(), i)
}

/// opcoes: cartas da zona `z` do proprio lado (menos `exceto`)
fn zona_toda(n: usize, z: &str, exceto: Option<usize>) -> Vec<Lug> {
    (0..n).filter(|i| Some(*i) != exceto).map(|i| lug("eu", z, i)).collect()
}

fn ns(m: &str) -> Resultado {
    Resultado::NaoSuportado(m.to_string())
}

type R<T> = Result<T, Resultado>;

pub(crate) fn dados(c: &Carta) -> R<std::sync::Arc<InfoCarta>> {
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

pub(crate) fn passos_de(b: &Value) -> impl Iterator<Item = &Value> {
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
    /// `_last_selected` e carta do oponente (passo `selected` depois disso: fora do nucleo)
    ultimo_oponente: bool,
    /// `_last_cost_rest_any_don_count` (vive no executor, como no Python)
    rest_any_don_n: i64,
    /// `_last_cost_trash_any_count`
    trash_any_n: i64,
    /// atacante da batalha em curso, no lado `opp` deste executor (None = lider);
    /// so o `ee_react` recebe (on_opp_attack / leader_battle_reactive)
    pub atacante_batalha: Option<(Option<usize>, String)>,
    /// `_battle_attacker`: cada execute() o REDEFINE (None fora daqueles gatilhos);
    /// passos rodados sem execute() (counter) veem o ultimo valor
    atacante: Option<(Option<usize>, String)>,
    /// o ultimo `executa` pagou o custo e rodou os passos (`logs` nao vazio no Python)
    pub rodou: bool,
    /// Some = simulacao: as escolhas internas sao da politica, nao do diario
    pub politica: Option<PoliticaRef>,
}

impl Executor {
    pub fn novo(fila: VecDeque<Value>) -> Self {
        Executor { fila, inst: 0, usados: Default::default(), lugar_fonte: None, ultimo: None, ultimo_oponente: false, rest_any_don_n: 0, trash_any_n: 0, atacante_batalha: None, atacante: None, rodou: false, politica: None }
    }
}

/// Carta do lado `me` por lugar (None = lider)
fn carta_mut(me: &mut Jogador, i: Option<usize>) -> R<&mut Carta> {
    match i {
        None => Ok(&mut me.leader),
        Some(i) => me.field_chars.get_mut(i).ok_or_else(|| ns("carta fora do campo")),
    }
}

/// `effective_power(your_turn=False)`: sem DON, com o override do turno do oponente
pub(crate) fn poder_turno_do_outro(c: &Carta) -> R<i64> {
    let base = c.base_power_override.or(c.base_power_override_opp_turn).unwrap_or(dados(c)?.power);
    Ok((base + c.power_buff).max(0))
}

/// `effective_power(your_turn=True)`
pub(crate) fn poder_meu_turno(c: &Carta) -> R<i64> {
    let base = c.base_power_override.unwrap_or(dados(c)?.power);
    Ok((base + c.power_buff + c.don_attached * 1000).max(0))
}

/// `_play_cost_rule_matches` (custo IMPRESSO da carta)
pub fn regra_de_custo_casa(c: &Carta, regra: &Value) -> R<bool> {
    let i = dados(c)?;
    if i.card_type != "CHARACTER" || i.cost < regra["cost_gte"].as_i64().unwrap_or(0) {
        return Ok(false);
    }
    match &regra["filter_type"] {
        Value::Null => {}
        Value::String(t) if t.is_empty() => {}
        Value::String(t) => {
            if !norm_tipo(&i.sub_types).contains(&norm_tipo(t)) {
                return Ok(false);
            }
        }
        _ => return Err(ns("regra de custo com filter_type nao-string")),
    }
    if let Some(n) = regra["filter_name"].as_str().filter(|n| !n.is_empty()) {
        if !i.name.to_lowercase().contains(&n.to_lowercase()) {
            return Ok(false);
        }
    }
    Ok(true)
}

/// `_hand_cost_conditions_match`
/// `other_char_power_gte` (+ _type/_names/_uses_base) sobre os personagens `outros`
fn outro_com_poder(cs: &serde_json::Map<String, Value>, outros: &[&Carta]) -> R<bool> {
    let l = cs["other_char_power_gte"].as_i64().unwrap_or(0);
    let tipo = cs.get("other_char_power_gte_type").and_then(|x| x.as_str()).unwrap_or("");
    let nomes: Vec<String> = cs.get("other_char_power_gte_names").and_then(|x| x.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_str()).map(|x| x.to_lowercase()).collect()).unwrap_or_default();
    let base = cs.get("other_char_power_uses_base").map_or(false, |x| x.as_bool().unwrap_or(!x.is_null()));
    for c in outros {
        let i = dados(c)?;
        if !tipo.is_empty() && !norm_tipo(&i.sub_types).contains(&norm_tipo(tipo)) {
            continue;
        }
        if !nomes.is_empty() && !nomes.iter().any(|n| i.name.to_lowercase().contains(n.as_str())) {
            continue;
        }
        if (if base { i.power } else { poder_meu_turno(c)? }) >= l {
            return Ok(true);
        }
    }
    Ok(false)
}

fn condicoes_de_custo(p: &Jogador, opp: &Jogador, carta: &Carta, cs: &serde_json::Map<String, Value>) -> R<bool> {
    let don = |j: &Jogador| j.don_available + j.don_rested;
    let n = |k: &str| cs[k].as_i64().unwrap_or(0);
    for k in cs.keys() {
        let ok = match k.as_str() {
            "life_lte" => (p.life.len() as i64) <= n(k),
            "trash_gte" => (p.trash.len() as i64) >= n(k),
            "events_in_trash_gte" => {
                let mut e = 0;
                for c in &p.trash {
                    if dados(c)?.card_type == "EVENT" {
                        e += 1;
                    }
                }
                e >= n(k)
            }
            "leader_power_lte" => poder_meu_turno(&p.leader)? <= n(k),
            "leader_type" => norm_tipo(&dados(&p.leader)?.sub_types).contains(&norm_tipo(cs[k].as_str().unwrap_or(""))),
            "leader_name_includes" => dados(&p.leader)?.name.to_lowercase().contains(&cs[k].as_str().unwrap_or("").to_lowercase()),
            "don_gte" | "don_on_field_gte" => don(p) >= n(k),
            "don_on_field_zero_or_gte" => don(p) == 0 || don(p) >= n(k),
            "opp_char_power_gte" => {
                let mut a = false;
                for c in &opp.field_chars {
                    a |= dados(c)?.power >= n(k);
                }
                a
            }
            "opp_char_cost_eq" => {
                let mut a = false;
                for c in &opp.field_chars {
                    a |= dados(c)?.cost == n(k);
                }
                a
            }
            "opp_char_cost_eq_or_gte" => {
                let (eq, ge) = (cs[k]["eq"].as_i64(), cs[k]["gte"].as_i64());
                let mut a = false;
                for c in &opp.field_chars {
                    let x = dados(c)?.cost;
                    a |= Some(x) == eq || ge.map_or(false, |g| x >= g);
                }
                a
            }
            "opp_rested_cards_gte" => {
                let r = opp.don_rested + opp.field_chars.iter().filter(|c| c.rested).count() as i64
                    + opp.leader.rested as i64 + opp.stage.as_ref().map_or(0, |s| s.rested as i64);
                r >= n(k)
            }
            "don_on_field_lte_opp" => !cs[k].as_bool().unwrap_or(false) || don(p) <= don(opp),
            "don_fewer_than_opp_by_gte" => don(opp) - don(p) >= n(k),
            "other_char_power_gte" => outro_com_poder(cs, &p.field_chars.iter().collect::<Vec<_>>())?,
            _ => true,
        };
        if !ok {
            return Ok(false);
        }
    }
    let _ = carta;
    Ok(true)
}

/// `_counter_event_cost_payable` (o evento ainda esta na mao)
fn custo_de_counter_pagavel(me: &Jogador, custos: &[Value]) -> bool {
    let mut descartes = 0;
    for c in custos {
        match c["type"].as_str().unwrap_or("") {
            "trash_from_hand" => descartes += c["count"].as_i64().unwrap_or(1),
            "don_minus" => {
                if !c["optional"].as_bool().unwrap_or(false)
                    && me.don_available + me.don_rested < c["count"].as_i64().unwrap_or(1)
                {
                    return false;
                }
            }
            _ => return false,
        }
    }
    (me.hand.len() as i64 - 1) >= descartes
}

/// `_KEYWORD_GRANTS`: campo ligado por cada acao
fn liga_keyword(c: &mut Carta, acao: &str) {
    match acao {
        "gain_blocker" => c.has_blocker = true,
        "gain_rush" => c.has_rush = true,
        "gain_rush_character" => c.has_rush_character = true,
        "gain_double_attack" => c.has_double_attack = true,
        "gain_banish" => c.has_banish = true,
        "gain_unblockable" => c.has_unblockable = true,
        _ => {}
    }
}

const KEYWORD_GRANTS: &[&str] = &[
    "gain_blocker", "gain_rush", "gain_rush_character", "gain_double_attack", "gain_banish", "gain_unblockable",
];

/// `apply_conditional_keyword_passives(gs, opp)`: so LIGA (nunca desliga).
/// Varre campo, mao, lider e stage, nessa ordem; cada carta ve o que as
/// anteriores ja ligaram.
pub fn aplica_passivas_keyword(gs: &mut Jogador, opp: &Jogador) -> R<()> {
    let mut ex = Executor::novo(Default::default());
    let mut pool: Vec<(u8, usize)> = (0..gs.field_chars.len()).map(|i| (0, i)).collect();
    pool.extend((0..gs.hand.len()).map(|i| (1, i)));
    pool.push((2, 0));
    if gs.stage.is_some() {
        pool.push((3, 0));
    }
    fn pega(gs: &mut Jogador, l: (u8, usize)) -> &mut Carta {
        match l.0 {
            0 => &mut gs.field_chars[l.1],
            1 => &mut gs.hand[l.1],
            2 => &mut gs.leader,
            _ => gs.stage.as_mut().unwrap(),
        }
    }
    for l in pool {
        let c = pega(gs, l).clone();
        let z = ["field_chars", "hand", "leader", "stage"][l.0 as usize];
        ex.lugar_fonte = Some((z.to_string(), l.1));
        let inf = dados(&c)?;
        let pas = inf.efeitos.get("passive").cloned().unwrap_or(Value::Null);
        let ot = inf.efeitos.get("opp_turn").cloned().unwrap_or(Value::Null);
        let acao = |s: &Value| s["action"].as_str().unwrap_or("").to_string();
        let passos: Vec<Value> = passos_de(&pas).cloned().collect();
        let passos_ot: Vec<Value> = passos_de(&ot).cloned().collect();
        let ot_grants: Vec<String> = passos_ot.iter().map(acao).filter(|a| KEYWORD_GRANTS.contains(&a.as_str())).collect();
        if !ot_grants.is_empty() && ex.condicoes(&ot["conditions"], gs, opp, &c, "opp_turn")? {
            for a in &ot_grants {
                liga_keyword(pega(gs, l), a);
            }
        }
        let tem = |nomes: &[&str]| passos.iter().any(|s| nomes.contains(&s["action"].as_str().unwrap_or("")));
        let bp_grupo: Vec<&Value> = passos_ot.iter()
            .filter(|s| s["action"].as_str() == Some("set_base_power_group_opp_turn")).collect();
        if !(tem(KEYWORD_GRANTS)
            || tem(&["grant_rush_character_type", "grant_rush_aura", "grant_blocker_aura",
                     "grant_unblockable_aura_named", "grant_double_attack_aura_named"])
            || !bp_grupo.is_empty())
        {
            continue;
        }
        if !ex.condicoes(&pas["conditions"], gs, opp, &c, "passive")? {
            continue;
        }
        // grants, depois cada aura, na ordem do Python (por tipo, nao por passo)
        for s in passos.iter().filter(|s| KEYWORD_GRANTS.contains(&s["action"].as_str().unwrap_or(""))) {
            let a = acao(s);
            let cm = pega(gs, l);
            liga_keyword(cm, &a);
            if a == "gain_rush_character" && cm.just_played {
                cm.rush_character_only_this_turn = true;
            }
        }
        let eh_eu = |j: usize| l.0 == 0 && l.1 == j;
        for s in passos.iter().filter(|s| s["action"].as_str() == Some("grant_rush_character_type")) {
            let w = match &s["filter_type"] {
                Value::String(t) => norm_tipo(t),
                Value::Null => String::new(),
                _ => return Err(ns("grant_rush_character_type com filter_type nao-string")),
            };
            for t in gs.field_chars.iter_mut() {
                if !w.is_empty() && norm_tipo(&dados(t)?.sub_types).contains(&w) {
                    t.has_rush_character = true;
                    if t.just_played {
                        t.rush_character_only_this_turn = true;
                    }
                }
            }
        }
        for s in passos.iter().filter(|s| s["action"].as_str() == Some("grant_rush_aura")) {
            let cor = s["color"].as_str().unwrap_or("").to_lowercase();
            for (j, t) in gs.field_chars.iter_mut().enumerate() {
                if s["exclude_self"].as_bool().unwrap_or(false) && eh_eu(j) {
                    continue;
                }
                let ti = dados(t)?;
                if !cor.is_empty() && ti.color.to_lowercase() != cor {
                    continue;
                }
                if s["cost_gte"].as_i64().map_or(false, |g| ti.cost < g) {
                    continue;
                }
                t.has_rush = true;
            }
        }
        for s in passos.iter().filter(|s| s["action"].as_str() == Some("grant_blocker_aura")) {
            for t in gs.field_chars.iter_mut() {
                let ct = dados(t)?.cost;
                if s["cost_gte"].as_i64().map_or(false, |g| ct < g) {
                    continue;
                }
                t.has_blocker = true;
            }
        }
        for s in passos.iter().filter(|s| matches!(s["action"].as_str(),
                Some("grant_unblockable_aura_named") | Some("grant_double_attack_aura_named"))) {
            let unb = s["action"].as_str() == Some("grant_unblockable_aura_named");
            let liga = |x: &mut Carta| if unb { x.has_unblockable = true } else { x.has_double_attack = true };
            liga(pega(gs, l));
            let nome = s["filter_name"].as_str().unwrap_or("").to_lowercase();
            for (j, t) in gs.field_chars.iter_mut().enumerate() {
                if eh_eu(j) {
                    continue;
                }
                if !nome.is_empty() && dados(t)?.name.to_lowercase().contains(&nome) {
                    liga(t);
                }
            }
        }
        for s in &bp_grupo {
            let v = s["amount"].as_i64();
            pega(gs, l).base_power_override_opp_turn = v;
            let nome = s["filter_name"].as_str().unwrap_or("").to_lowercase();
            for (j, t) in gs.field_chars.iter_mut().enumerate() {
                if eh_eu(j) {
                    continue;
                }
                if !nome.is_empty() && dados(t)?.name.to_lowercase().contains(&nome) {
                    t.base_power_override_opp_turn = v;
                }
            }
        }
    }
    Ok(())
}

/// `_ko_sentence`: a frase do texto da carta com "cannot be K.O.'d" / "can't be K.O"
fn frase_de_ko(texto: &str) -> String {
    let t = texto.to_lowercase().replace("&lt;", "<").replace("&gt;", ">").replace('＜', "<").replace('＞', ">");
    let b = t.as_bytes();
    let casa = |i: usize| -> Option<usize> {
        // devolve o fim do trecho casado a partir de i
        let resto = &t[i..];
        if let Some(r) = resto.strip_prefix("cannot be k") {
            let mut j = i + 11;
            let r = r.strip_prefix('.').map(|x| { j += 1; x }).unwrap_or(r);
            let r = r.strip_prefix('o')?;
            j += 1;
            let r = r.strip_prefix('.').map(|x| { j += 1; x }).unwrap_or(r);
            let r = r.strip_prefix('\'').map(|x| { j += 1; x }).unwrap_or(r);
            r.strip_prefix('d')?;
            return Some(j + 1);
        }
        if let Some(r) = resto.strip_prefix("can't be k") {
            let mut j = i + 10;
            let r = r.strip_prefix('.').map(|x| { j += 1; x }).unwrap_or(r);
            r.strip_prefix('o')?;
            return Some(j + 1);
        }
        None
    };
    let mut achado = None;
    for i in 0..b.len() {
        if !t.is_char_boundary(i) {
            continue;
        }
        if let Some(fim) = casa(i) {
            achado = Some((i, fim));
            break;
        }
    }
    let Some((ini, fim)) = achado else { return String::new() };
    let antes = &t[..ini];
    let inicio = antes.rfind('.').map(|x| x as i64).unwrap_or(-1).max(antes.rfind('\n').map(|x| x as i64).unwrap_or(-1));
    let final_ = t[fim..].find('.').map(|x| x + fim).unwrap_or(t.len());
    t[(inicio + 1) as usize..final_].to_string()
}

/// `_source_matches_battle_ko_immunity`
fn fonte_casa_imunidade(frase: &str, atacante: &InfoCarta) -> bool {
    let tipo = atacante.card_type.to_uppercase();
    let attr = atacante.attribute.to_lowercase();
    if frase.contains("by leaders") {
        return tipo == "LEADER";
    }
    if frase.contains("by characters without") && frase.contains("special") {
        return tipo == "CHARACTER" && !attr.contains("special");
    }
    if frase.contains("by attribute cards") {
        return !attr.is_empty();
    }
    for a in ["strike", "slash", "special", "wisdom", "ranged"] {
        if !frase.contains(a) {
            continue;
        }
        // regex `by [^.]*<a>[^.]*attribute` (a frase nao tem '.')
        let casa = frase.find("by ").map_or(false, |p| {
            frase[p + 3..].find(a).map_or(false, |q| frase[p + 3 + q + a.len()..].contains("attribute"))
        });
        if casa {
            return attr.contains(a);
        }
    }
    true
}

/// `_immunity_conds_met`
fn condicoes_de_imunidade(cs: &Value, alvo_idx: usize, dono: &Jogador, outro: &Jogador) -> R<bool> {
    let Some(m) = cs.as_object() else { return Ok(true) };
    let n = |k: &str| m[k].as_i64().unwrap_or(0);
    if m.contains_key("all_don_rested") && dono.don_available > 0 {
        return Ok(false);
    }
    if m.contains_key("life_lte") && dono.life.len() as i64 > n("life_lte") {
        return Ok(false);
    }
    if m.contains_key("life_gte") && (dono.life.len() as i64) < n("life_gte") {
        return Ok(false);
    }
    if let Some(t) = m.get("only_field_type") {
        let t = t.as_str().unwrap_or("").to_lowercase();
        let mut ok = !dono.field_chars.is_empty();
        for c in &dono.field_chars {
            if !dados(c)?.sub_types.to_lowercase().contains(&t) {
                ok = false;
            }
        }
        if !ok {
            return Ok(false);
        }
    }
    if let Some(a) = m.get("leader_attribute") {
        if !dados(&dono.leader)?.attribute.to_lowercase().contains(&a.as_str().unwrap_or("").to_lowercase()) {
            return Ok(false);
        }
    }
    if m.contains_key("don_rested_gte") && dono.don_rested < n("don_rested_gte") {
        return Ok(false);
    }
    if m.contains_key("opp_leader_or_char_power_gte") {
        let l = n("opp_leader_or_char_power_gte");
        let mut algum = dados(&outro.leader)?.power >= l;
        for c in &outro.field_chars {
            algum |= dados(c)?.power >= l;
        }
        if !algum {
            return Ok(false);
        }
    }
    if let Some(nm) = m.get("no_other_named") {
        let nm = nm.as_str().unwrap_or("").to_lowercase();
        let ceq = m.get("no_other_named_cost_eq").and_then(|x| x.as_i64());
        for (j, c) in dono.field_chars.iter().enumerate() {
            let i = dados(c)?;
            if j != alvo_idx && i.name.to_lowercase().contains(&nm) && ceq.map_or(true, |x| i.cost == x) {
                return Ok(false);
            }
        }
    }
    Ok(true)
}

/// `is_immune(alvo, 'ko', dono, outro, source_is_opp=True, ko_context='battle', source_card=atacante)`
pub fn imune_ko_em_batalha(dono: &Jogador, outro: &Jogador, alvo_idx: usize, atacante: &Carta) -> R<bool> {
    imune_a_ko(dono, outro, alvo_idx, Some(atacante), true)
}

/// `is_immune(alvo, 'ko', ..., ko_context='battle'|'effect', source_card=fonte)`
pub fn imune_a_ko(dono: &Jogador, outro: &Jogador, alvo_idx: usize, fonte: Option<&Carta>, batalha: bool) -> R<bool> {
    let alvo = &dono.field_chars[alvo_idx];
    let inf = dados(alvo)?;
    let ainf = match fonte { Some(f) => Some(dados(f)?), None => None };
    for (_timing, blk) in inf.efeitos.iter() {
        if !blk.is_object() {
            continue;
        }
        for st in passos_de(blk) {
            if st["action"].as_str() != Some("immunity") || st["imm_type"].as_str() != Some("ko") {
                continue;
            }
            // `_ko_immunity_applies_to_context(..., 'battle', atacante)`
            if inf.card_text.is_empty() {
                return Err(ns("imunidade sem texto da carta"));
            }
            let frase = frase_de_ko(&inf.card_text);
            if !frase.is_empty() {
                let so_batalha = frase.contains("in battle");
                let so_efeito = frase.contains("by effect") || frase.contains("by your opponent's effect");
                if batalha && so_efeito && !so_batalha {
                    continue;
                }
                if !batalha && so_batalha && !so_efeito {
                    continue;
                }
                if batalha {
                    if let Some(a) = &ainf {
                        if !fonte_casa_imunidade(&frase, a) {
                            continue;
                        }
                    }
                }
            }
            if let Some(l) = st["source_power_lte"].as_i64() {
                if ainf.as_ref().map_or(true, |a| a.power > l) {
                    continue;
                }
            }
            let dr = blk["don_requirement"].as_i64().unwrap_or(0);
            if dr != 0 && alvo.don_attached < dr {
                continue;
            }
            let cs = if blk["conditions"].as_object().map_or(false, |m| !m.is_empty()) { &blk["conditions"] } else { &st["conditions"] };
            if !cs.is_null() && cs.as_object().map_or(false, |m| !m.is_empty()) && !condicoes_de_imunidade(cs, alvo_idx, dono, outro)? {
                continue;
            }
            return Ok(true);
        }
    }
    if !alvo.immunity_ko_until.is_empty() {
        return Ok(true);
    }
    for (j, o) in dono.field_chars.iter().enumerate() {
        if j == alvo_idx {
            continue;
        }
        let Some(pas) = dados(o)?.efeitos.get("passive").cloned() else { continue };
        for s in passos_de(&pas) {
            if s["action"].as_str() != Some("grant_ko_immunity_aura") {
                continue;
            }
            if s["self_active_required"].as_bool().unwrap_or(false) && o.rested {
                continue;
            }
            let w = s["filter_type"].as_str().unwrap_or("").to_lowercase();
            if !w.is_empty() && !inf.sub_types.to_lowercase().contains(&w) {
                continue;
            }
            if s["cost_lte"].as_i64().map_or(false, |l| inf.cost > l) {
                continue;
            }
            let ex = s["exclude"].as_str().unwrap_or("").to_lowercase();
            if !ex.is_empty() && inf.name.to_lowercase().contains(&ex) {
                continue;
            }
            return Ok(true);
        }
    }
    Ok(false)
}

/// `is_immune(alvo, 'rest', dono, outro, source_is_opp=True)` (sem carta-fonte)
pub fn imune_a_rest(dono: &Jogador, outro: &Jogador, alvo_idx: usize) -> R<bool> {
    let alvo = &dono.field_chars[alvo_idx];
    let inf = dados(alvo)?;
    for (_t, blk) in inf.efeitos.iter() {
        for st in passos_de(blk) {
            if st["action"].as_str() != Some("immunity") || st["imm_type"].as_str() != Some("rest") {
                continue;
            }
            if !st["source_power_lte"].is_null() {
                continue; // sem carta-fonte: nao vale
            }
            let dr = blk["don_requirement"].as_i64().unwrap_or(0);
            if dr != 0 && alvo.don_attached < dr {
                continue;
            }
            let cs = if blk["conditions"].as_object().map_or(false, |m| !m.is_empty()) { &blk["conditions"] } else { &st["conditions"] };
            if cs.as_object().map_or(false, |m| !m.is_empty()) && !condicoes_de_imunidade(cs, alvo_idx, dono, outro)? {
                continue;
            }
            return Ok(true);
        }
    }
    Ok(false)
}

/// Alguma substituicao de K.O. PODE valer para este alvo? (proprio alvo,
/// outras cartas do dono, evento [Counter] na mao) -- fora do nucleo.
pub fn substituicao_possivel(dono: &Jogador, alvo_idx: usize) -> R<bool> {
    let sub = |b: &Value| passos_de(b).any(|s| matches!(s["action"].as_str(), Some("substitute_ko") | Some("substitute_removal")));
    let alvo = &dono.field_chars[alvo_idx];
    let cartas = std::iter::once(alvo).chain(dono.field_chars.iter().enumerate().filter(|(j, _)| *j != alvo_idx).map(|(_, c)| c))
        .chain(std::iter::once(&dono.leader)).chain(dono.stage.iter());
    for c in cartas {
        let i = dados(c)?;
        for t in ["passive", "opp_turn", "your_turn"] {
            if i.efeitos.get(t).map_or(false, |b| sub(b)) {
                return Ok(true);
            }
        }
    }
    for c in &dono.hand {
        let i = dados(c)?;
        if i.card_type == "EVENT" && i.efeitos.get("counter").map_or(false, |b| sub(b)) {
            return Ok(true);
        }
    }
    Ok(false)
}

/// `_target_matches_external_substitute` (sem `exclude_self`: a fonte nunca e o alvo aqui)
fn casa_alvo_de_substituicao(t: &Carta, i: &InfoCarta, _mesma: bool, st: &Value, b: &Value) -> R<bool> {
    if !st["filter_type"].is_null() && st["filter_type"].as_str() != Some("") && !casa_filtro(i, &st["filter_type"], false) {
        return Ok(false);
    }
    if let Some(n) = st["filter_name"].as_str().filter(|x| !x.is_empty()) {
        let n = n.to_lowercase();
        if !i.name.to_lowercase().contains(&n) && !t.code.to_lowercase().contains(&n) {
            return Ok(false);
        }
    }
    if let Some(c) = st["filter_color"].as_str().filter(|x| !x.is_empty()) {
        if !i.color.to_lowercase().contains(&c.to_lowercase()) {
            return Ok(false);
        }
    }
    if let Some(a) = st["filter_attribute"].as_str().filter(|x| !x.is_empty()) {
        let a = a.to_lowercase();
        let at = [i.attribute.to_lowercase(), t.extra_attribute_this_turn.to_lowercase()];
        if !at.iter().any(|x| !x.is_empty() && x.contains(&a)) {
            return Ok(false);
        }
    }
    let n = |k: &str| st[k].as_i64();
    if n("cost_lte").map_or(false, |x| i.cost > x) || n("cost_gte").map_or(false, |x| i.cost < x)
        || n("power_lte").map_or(false, |x| i.power > x) || n("power_eq").map_or(false, |x| i.power != x)
        || n("power_gte").map_or(false, |x| i.power < x)
    {
        return Ok(false);
    }
    if st["rested_only"].as_bool().unwrap_or(false) && !t.rested {
        return Ok(false);
    }
    if let Some(e) = st["exclude"].as_str().filter(|x| !x.is_empty()) {
        let e = e.to_lowercase();
        if i.name.to_lowercase().contains(&e) || t.code.to_lowercase().contains(&e) {
            return Ok(false);
        }
    }
    let cs = &b["conditions"];
    if let Some(ty) = cs["self_type"].as_str().filter(|x| !x.is_empty()) {
        if !i.sub_types.to_lowercase().contains(ty) {
            return Ok(false);
        }
    }
    if cs["self_power_base_lte"].as_i64().map_or(false, |x| i.power > x) || cs["self_power_base_gte"].as_i64().map_or(false, |x| i.power < x) {
        return Ok(false);
    }
    const CHAVES: &[&str] = &["filter_type", "filter_name", "filter_color", "filter_attribute", "cost_lte", "cost_gte",
        "power_lte", "power_eq", "power_gte", "rested_only", "exclude", "exclude_self"];
    if st["no_filter"].as_bool().unwrap_or(false) {
        return Ok(true);
    }
    Ok(CHAVES.iter().any(|k| st.get(*k).is_some())
        || ["self_type", "self_power_base_lte", "self_power_base_gte"].iter().any(|k| cs.get(*k).is_some()))
}

/// Filtros de `eligible_cards` do `play_card` (nome/cor/exclusao; poder so na execucao)
fn casa_play_card(st: &Value, c: &Carta, i: &InfoCarta, com_poder: bool) -> R<bool> {
    let nomes: Vec<String> = match (&st["filter_names"], &st["filter_name"]) {
        (Value::Array(a), _) if !a.is_empty() => a.iter().filter_map(|x| x.as_str()).map(|x| x.to_lowercase()).collect(),
        (_, Value::Array(a)) => a.iter().filter_map(|x| x.as_str()).map(|x| x.to_lowercase()).collect(),
        (_, Value::String(x)) if !x.is_empty() => vec![x.to_lowercase()],
        _ => vec![],
    };
    if !nomes.is_empty() {
        let (nm, cd) = (i.name.to_lowercase(), c.code.to_lowercase());
        if !nomes.iter().any(|n| nm.contains(n.as_str()) || cd.contains(n.as_str())) {
            return Ok(false);
        }
    }
    let cor = st["color"].as_str().unwrap_or("").to_lowercase();
    if !cor.is_empty() && !i.color.to_lowercase().contains(&cor) {
        return Ok(false);
    }
    match &st["exclude"] {
        Value::String(x) if !x.is_empty() && i.name.to_lowercase().contains(&x.to_lowercase()) => return Ok(false),
        Value::Array(a) if !a.is_empty() => return Err(ns("play_card exclude em lista")),
        _ => {}
    }
    if com_poder {
        let num = |k: &str| st[k].as_i64();
        if num("power_lte").map_or(false, |x| i.power > x) || num("power_gte").map_or(false, |x| i.power < x)
            || num("power_eq").map_or(false, |x| i.power != x)
        {
            return Ok(false);
        }
        if st["filter_no_effect"].as_bool().unwrap_or(false) && !i.efeitos.is_empty() {
            return Ok(false);
        }
    }
    Ok(true)
}

/// `effective_hand_play_cost(p, card, opp)`
pub fn custo_de_jogar(p: &Jogador, opp: &Jogador, c: &Carta) -> R<i64> {
    let i = dados(c)?;
    let mut custo = i.cost + c.cost_buff + c.cost_buff_permanent;
    if let Some(st) = &p.stage {
        for (_, ent) in dados(st)?.efeitos.iter() {
            for s in ent["steps"].as_array().into_iter().flatten() {
                if s["action"].as_str() == Some("buff_cost") && s["target"].as_str() == Some("own_play_hand")
                    && regra_de_custo_casa(c, s)?
                {
                    custo -= s["amount"].as_i64().unwrap_or(0);
                }
            }
        }
    }
    for r in &p.pending_play_cost_reductions {
        if regra_de_custo_casa(c, r)? {
            custo -= r["amount"].as_i64().unwrap_or(0);
        }
    }
    if let Some(pas) = i.efeitos.get("passive") {
        if let Some(cs) = pas["conditions"].as_object().filter(|m| !m.is_empty()) {
            if condicoes_de_custo(p, opp, c, cs)? {
                for s in pas["steps"].as_array().into_iter().flatten() {
                    if s["target"].as_str() != Some("own_play_self") {
                        continue;
                    }
                    match s["action"].as_str() {
                        Some("debuff_cost") => custo -= s["amount"].as_i64().unwrap_or(0),
                        Some("set_play_cost") => custo = s["amount"].as_i64().unwrap_or(custo),
                        _ => {}
                    }
                }
            }
        }
    }
    Ok(custo.max(0))
}

impl Executor {
    /// `try_counter_event_power(alvo, alvo_tipo, falta)` pelo `ee_react`
    /// (`me` = defensor). Devolve o poder somado a defesa (0 = nenhum).
    pub fn counter_evento_poder(&mut self, me: &mut Jogador, opp: &mut Jogador, alvo: Option<usize>,
                                alvo_tipo: &str, falta: i64) -> R<i64> {
        const EXTRAS_OK: &[&str] = &[
            "draw", "set_active", "rest_opp_character", "add_don", "set_don_active",
            "ko", "bounce", "place_opp_character_bottom_deck", "debuff_power",
            "trash_from_deck_top", "peek_life", "add_from_trash", "gain_life",
            "character_to_owner_life", "opp_bounce_own_character",
            "play_card", "play_from_deck", "look_top_deck", "add_to_hand",
            "deck_bottom_rest", "deck_reorder_rest", "deck_top_rest",
        ];
        let alvo_inf = dados(match alvo {
            None => &me.leader,
            Some(j) => me.field_chars.get(j).ok_or_else(|| ns("alvo do counter fora do campo"))?,
        })?;
        // (excesso, custo, k, quanto, custos, extras)
        let mut cands: Vec<(i64, i64, usize, i64, Vec<Value>, Vec<Value>)> = Vec::new();
        for (k, ev) in me.hand.iter().enumerate() {
            let inf = dados(ev)?;
            if inf.card_type != "EVENT" {
                continue;
            }
            let bloco = inf.efeitos.get("counter").cloned().unwrap_or(Value::Null);
            if bloco.as_object().map_or(true, |m| m.is_empty()) {
                if inf.card_text.to_lowercase().contains("[counter]") {
                    return Err(ns("counter evento pelo texto (fallback)"));
                }
                continue;
            }
            if !self.condicoes(&bloco["conditions"], me, opp, ev, "counter")? {
                continue;
            }
            let passos: Vec<Value> = passos_de(&bloco).cloned().collect();
            let eh_buff = |s: &Value| s["action"].as_str() == Some("buff_power")
                && matches!(s["duration"].as_str(), Some("battle_only") | Some("this_turn"));
            let buffs: Vec<&Value> = passos.iter().filter(|s| eh_buff(s)).collect();
            if buffs.is_empty() {
                continue;
            }
            let extras: Vec<Value> = passos.iter().filter(|s| !eh_buff(s)).cloned().collect();
            if extras.iter().any(|s| !EXTRAS_OK.contains(&s["action"].as_str().unwrap_or(""))) {
                continue;
            }
            let pr = buffs[0];
            match pr["target"].as_str().unwrap_or("") {
                "leader" if alvo_tipo != "leader" => continue,
                "own_character" if alvo_tipo != "character" => continue,
                "leader" | "own_character" | "leader_or_character" => {}
                "select_filtered" => {
                    if !casa_filtro(&alvo_inf, &pr["filter_type"], false) {
                        continue;
                    }
                }
                _ => continue,
            }
            if !pr["conditions"].is_null() && !self.condicoes(&pr["conditions"], me, opp, ev, "counter")? {
                continue;
            }
            let mut quanto = pr["amount"].as_i64().unwrap_or(0);
            let mut ok = true;
            for b in &buffs[1..] {
                if !matches!(b["target"].as_str(), Some("self") | Some("selected")) {
                    ok = false;
                    break;
                }
                if !b["conditions"].is_null() && !self.condicoes(&b["conditions"], me, opp, ev, "counter")? {
                    continue;
                }
                quanto += b["amount"].as_i64().unwrap_or(0);
            }
            if !ok || quanto < falta {
                continue;
            }
            let custo = custo_de_jogar(me, opp, ev)?;
            if me.don_available < custo {
                continue;
            }
            let custos: Vec<Value> = bloco["costs"].as_array().cloned().unwrap_or_default();
            if !custo_de_counter_pagavel(me, &custos) {
                continue;
            }
            cands.push((quanto - falta, custo, k, quanto, custos, extras));
        }
        if cands.is_empty() {
            return Ok(0);
        }
        self.passivas_da_fila(me, opp)?;
        let ops: Vec<Lug> = cands.iter().map(|c| lug("eu", "hand", c.2)).collect();
        let Some((lado, z, k)) = self.escolha_entre("counter_evento", &ops, true)? else { return Ok(0) };
        if lado != "eu" || z != "hand" {
            return Err(ns("counter evento fora da mao"));
        }
        let Some(pos) = cands.iter().position(|c| c.2 == k) else {
            return Err(ns("counter evento fora dos candidatos"));
        };
        let (_, custo, k, quanto, custos, extras) = cands.swap_remove(pos);
        let Some(k) = self.paga_custo_de_counter(me, opp, &custos, k)? else { return Ok(0) };
        let ev = me.hand.remove(k);
        me.trash.push(ev.clone());
        me.don_available -= custo;
        me.don_rested += custo;
        let inf = dados(&ev)?;
        let lf = self.lugar_fonte.take();
        let mut r = Ok(());
        for st in &extras {
            r = self.passo(st, me, opp, &ev, &inf, "counter");
            if r.is_err() {
                break;
            }
        }
        self.lugar_fonte = lf;
        r?;
        Ok(quanto)
    }

    /// Ha evento [Counter] de K.O. no atacante na mao? (fora do nucleo)
    pub fn tem_counter_evento_ko(me: &Jogador) -> R<bool> {
        for ev in &me.hand {
            let inf = dados(ev)?;
            if inf.card_type != "EVENT" {
                continue;
            }
            let Some(b) = inf.efeitos.get("counter") else { continue };
            let p: Vec<&Value> = passos_de(b).collect();
            if p.len() == 1 && p[0]["action"].as_str() == Some("ko") {
                return Ok(true);
            }
        }
        Ok(false)
    }

    /// `try_counter_event_debuff(atacante, tipo, falta)` pelo `ee_react`
    /// (`me` = defensor). Devolve quanto o atacante perdeu (0 = nenhum); o
    /// `power_buff` do atacante e baixado aqui.
    pub fn counter_evento_debuff(&mut self, me: &mut Jogador, opp: &mut Jogador, atacante: Option<usize>,
                                 falta: i64) -> R<i64> {
        let atk_char = atacante.is_some();
        // (excesso, custo, k, quanto, custos)
        let mut cands: Vec<(i64, i64, usize, i64, Vec<Value>)> = Vec::new();
        for (k, ev) in me.hand.iter().enumerate() {
            let inf = dados(ev)?;
            if inf.card_type != "EVENT" {
                continue;
            }
            // `_counter_event_debuff_plan`
            let Some(bloco) = inf.efeitos.get("counter").filter(|b| b.as_object().map_or(false, |m| !m.is_empty())) else {
                continue;
            };
            if !self.condicoes(&bloco["conditions"], me, opp, ev, "counter")? {
                continue;
            }
            let passos: Vec<&Value> = passos_de(bloco).collect();
            if passos.is_empty()
                || passos.iter().any(|s| !matches!(s["action"].as_str(), Some("debuff_power") | Some("negate_effect")))
            {
                continue;
            }
            let mut total = 0;
            let mut ok = true;
            for s in &passos {
                if s["action"].as_str() != Some("debuff_power") {
                    continue;
                }
                match s["target"].as_str() {
                    Some("opp_character") if !atk_char => continue,
                    Some("opp_character") | Some("opp_leader_or_character") => {}
                    _ => {
                        ok = false;
                        break;
                    }
                }
                if !s["conditions"].is_null() && !self.condicoes(&s["conditions"], me, opp, ev, "counter")? {
                    continue;
                }
                total += s["amount"].as_i64().unwrap_or(0);
            }
            if !ok || total == 0 || total < falta {
                continue;
            }
            let custo = custo_de_jogar(me, opp, ev)?;
            if me.don_available < custo {
                continue;
            }
            let custos: Vec<Value> = bloco["costs"].as_array().cloned().unwrap_or_default();
            if !custo_de_counter_pagavel(me, &custos) {
                continue;
            }
            cands.push((total - falta, custo, k, total, custos));
        }
        if cands.is_empty() {
            return Ok(0);
        }
        self.passivas_da_fila(me, opp)?;
        let ops: Vec<Lug> = cands.iter().map(|c| lug("eu", "hand", c.2)).collect();
        let Some((lado, z, k)) = self.escolha_entre("counter_evento", &ops, true)? else { return Ok(0) };
        if lado != "eu" || z != "hand" {
            return Err(ns("counter evento fora da mao"));
        }
        let Some(pos) = cands.iter().position(|c| c.2 == k) else {
            return Err(ns("counter evento fora dos candidatos"));
        };
        let (_, custo, k, quanto, custos) = cands.swap_remove(pos);
        let Some(k) = self.paga_custo_de_counter(me, opp, &custos, k)? else { return Ok(0) };
        let ev = me.hand.remove(k);
        me.trash.push(ev);
        me.don_available -= custo;
        me.don_rested += custo;
        carta_mut(opp, atacante)?.power_buff -= quanto;
        Ok(quanto)
    }

    /// `_pay_counter_event_costs`; devolve o novo indice do evento na mao
    /// (None = nao pagou; o que ja foi pago fica pago, como no Python).
    fn paga_custo_de_counter(&mut self, me: &mut Jogador, opp: &mut Jogador, custos: &[Value], mut k: usize) -> R<Option<usize>> {
        for c in custos {
            match c["type"].as_str().unwrap_or("") {
                "trash_from_hand" => {
                    for _ in 0..c["count"].as_i64().unwrap_or(1) {
                        if me.hand.len() <= 1 {
                            return Ok(None);
                        }
                        self.passivas_da_fila(me, opp)?;
                        let ops = zona_toda(me.hand.len(), "hand", Some(k));
                        let Some((lado, z, i)) = self.escolha_entre("descarte", &ops, false)? else {
                            return Err(ns("descarte vazio no custo do counter"));
                        };
                        if lado != "eu" || z != "hand" || i >= me.hand.len() || i == k {
                            return Err(ns("descarte fora da mao"));
                        }
                        let x = me.hand.remove(i);
                        me.trash.push(x);
                        if i < k {
                            k -= 1;
                        }
                    }
                }
                "don_minus" if !c["optional"].as_bool().unwrap_or(false) => {
                    let (ok, dev) = devolve_don(me, c["count"].as_i64().unwrap_or(1), None)?;
                    self.dispara_don_devolvido(me, opp, dev)?;
                    if !ok {
                        return Ok(None);
                    }
                }
                _ => {}
            }
        }
        Ok(Some(k))
    }

    /// A proxima decisao veio depois de o Python criar o motor de decisao
    /// (`EffectExecutor._de`), que liga as passivas de keyword dos dois lados.
    fn passivas_da_fila(&mut self, me: &mut Jogador, opp: &mut Jogador) -> R<()> {
        // na simulacao nao ha fila: as passivas de keyword sao momento do Python (`_de` preguicoso)
        if let Some(d) = self.fila.front_mut() {
            if d.get("passivas").and_then(|v| v.as_bool()) == Some(true) {
                d.as_object_mut().unwrap().remove("passivas");
                aplica_passivas_keyword(me, opp)?;
                aplica_passivas_keyword(opp, me)?;
            }
        }
        Ok(())
    }

    /// `lock_opp_*` / `lock_opp_character_refresh`: candidatas pela regra; QUAL
    /// trava (o motor usa board_value) vem da fila (`trava`).
    fn trava(&mut self, st: &Value, acao: &str, me: &mut Jogador, opp: &mut Jogador) -> R<()> {
        let n = st["count"].as_i64().unwrap_or(1);
        let dur = match st["duration"].as_str().unwrap_or("until_opp_turn_end") {
            "until_opp_end_phase" => "opp_end_phase",
            "until_my_next_turn_start" => "my_next_turn_start",
            _ => "opp_turn_end",
        };
        let num = |k: &str| -> R<Option<i64>> {
            match &st[k] {
                Value::Null => Ok(None),
                v => v.as_i64().map(Some).ok_or_else(|| ns(&format!("{k} nao numerico"))),
            }
        };
        let (cost_lte, power_lte) = (num("cost_lte")?, num("power_lte")?);
        let mut cands: Vec<Option<usize>> = Vec::new();
        if acao == "lock_opp_character_refresh" {
            let (ceq, dg) = (num("cost_eq")?, num("don_attached_gte")?);
            for (j, c) in opp.field_chars.iter().enumerate() {
                let i = dados(c)?;
                if c.rested && cost_lte.map_or(true, |x| i.cost <= x) && ceq.map_or(true, |x| i.cost == x)
                    && power_lte.map_or(true, |x| i.power <= x) && dg.map_or(true, |x| c.don_attached >= x)
                {
                    cands.push(Some(j));
                }
            }
        } else if st["target"].as_str() == Some("opp_leader") {
            if !st["only_rested"].as_bool().unwrap_or(false) || opp.leader.rested {
                cands.push(None);
            }
        } else {
            let excl = st["exclude"].as_str().unwrap_or("").to_lowercase();
            for (j, c) in opp.field_chars.iter().enumerate() {
                let i = dados(c)?;
                if cost_lte.map_or(true, |x| i.cost <= x) && power_lte.map_or(true, |x| i.power <= x)
                    && (acao != "lock_opp_blocker_turn" || crate::acoes::is_blocker(c, &i))
                    && (excl.is_empty() || !i.name.to_lowercase().contains(&excl))
                {
                    cands.push(Some(j));
                }
            }
        }
        for _ in 0..n.min(cands.len() as i64) {
            self.passivas_da_fila(me, opp)?;
            let ops: Vec<Lug> = cands.iter().map(|c| match c { Some(i) => lug("oponente", "field_chars", *i), None => lug("oponente", "leader", 0) }).collect();
            let x = match self.escolha_entre("trava", &ops, false)? {
                Some((l, z, i)) if l == "oponente" && z == "field_chars" => Some(i),
                Some((l, z, _)) if l == "oponente" && z == "leader" => None,
                _ => return Err(ns("trava sem alvo valido")),
            };
            let Some(p) = cands.iter().position(|c| *c == x) else { return Err(ns("trava fora dos candidatos")) };
            cands.remove(p);
            let t = carta_mut(opp, x)?;
            match acao {
                "lock_opp_character_attack" => t.cannot_attack_until = dur.into(),
                "lock_opp_cannot_be_rested" => t.cannot_be_rested_until = dur.into(),
                "lock_opp_blocker_turn" => t.cannot_block_until = dur.into(),
                _ => t.frozen_next_refresh = true,
            }
        }
        Ok(())
    }

    /// `bounce` / `place_opp_character_bottom_deck` em personagem do oponente
    /// (alvo = `_pick_effect_target`, da fila).
    fn remove_do_oponente(&mut self, st: &Value, acao: &str, me: &mut Jogador, opp: &mut Jogador) -> R<()> {
        if acao == "bounce" && st["target"].as_str() == Some("own_character") {
            return Err(ns("bounce no proprio personagem"));
        }
        for k in ["power_gte", "power_eq"] {
            if !st[k].is_null() {
                return Err(ns(&format!("{acao} com {k}")));
            }
        }
        if tem_reativo(me, &["on_own_effect_removes_char"])? {
            return Err(ns("reativo on_own_effect_removes_char"));
        }
        let mut cands: Vec<usize> = Vec::new();
        for (i, c) in opp.field_chars.iter().enumerate() {
            let ok = if acao == "bounce" {
                casa_alvo(st, c, st["active_only"].as_bool().unwrap_or(false), false, me, opp)?
            } else {
                let i2 = dados(c)?;
                st["cost_lte"].as_i64().map_or(true, |x| i2.cost <= x)
                    && st["cost_eq"].as_i64().map_or(true, |x| i2.cost == x)
                    && st["power_lte"].as_i64().map_or(true, |x| i2.power <= x)
                    && casa_filtro(&i2, &st["filter_type"], false)
            };
            if ok {
                cands.push(i);
            }
        }
        if acao != "bounce" && !st["cost_lte"].is_null() && !st["cost_lte"].is_i64() {
            return Err(ns("place_opp_character_bottom_deck com cost_lte dinamico"));
        }
        let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
        for _ in 0..n.min(cands.len()) {
            self.passivas_da_fila(me, opp)?;
            let i = self.alvo_no_oponente(&cands)?;
            let imune = dados(&opp.field_chars[i])?.efeitos.values().any(|b| passos_de(b).any(|s|
                s["action"].as_str() == Some("immunity") && s["imm_type"].as_str() == Some("removal")));
            if imune {
                return Err(ns("alvo com imunidade a remocao"));
            }
            let mut x = opp.field_chars.remove(i);
            if x.don_attached > 0 {
                opp.don_rested += x.don_attached;
                x.don_attached = 0;
            }
            x.rested = false;
            if acao == "bounce" {
                opp.hand.push(x);
            } else {
                opp.deck.insert(0, x);
            }
            cands.retain(|&j| j != i);
            for j in cands.iter_mut() {
                if *j > i {
                    *j -= 1;
                }
            }
            // `_last_selected` passa a ser carta do OPONENTE
            self.ultimo = None;
            self.ultimo_oponente = true;
        }
        Ok(())
    }

    /// `_dispatch_don_returned(owner=me, amount, source_owner=me)`: o proprio
    /// efeito de `me` devolveu `dev` DON; um EffectExecutor novo por fonte.
    fn dispara_don_devolvido(&mut self, me: &mut Jogador, opp: &mut Jogador, dev: i64) -> R<()> {
        if dev <= 0 {
            return Ok(());
        }
        let mut fontes: Vec<(Carta, Option<(String, usize)>)> = vec![(me.leader.clone(), Some(("leader".into(), 0)))];
        fontes.extend(me.field_chars.iter().cloned().enumerate().map(|(i, c)| (c, Some(("field_chars".into(), i)))));
        if let Some(s) = &me.stage {
            fontes.push((s.clone(), None));
        }
        for (f, l) in fontes {
            let inf = dados(&f)?;
            let Some(ent) = inf.efeitos.get("when_don_returned").cloned() else { continue };
            if dev < ent["return_count_gte"].as_i64().unwrap_or(1) {
                continue;
            }
            match ent["owner_turn"].as_str() {
                Some("your") if !me.is_active_turn => continue,
                Some("opponent") if me.is_active_turn => continue,
                _ => {}
            }
            let uma_vez = ent["once_per_turn"].as_bool().unwrap_or(false);
            let marca = Value::from(vec![Value::from(me.global_turn), Value::from("when_don_returned")]);
            if uma_vez && f.extras.get("_event_once_marker") == Some(&marca) {
                continue;
            }
            let (k, lf, rod) = (self.inst, self.lugar_fonte.clone(), self.rodou);
            self.inst = 8000 + self.fila.len() as u32 + self.usados.len() as u32;
            self.lugar_fonte = l.clone();
            let r = self.executa(me, opp, &f, "when_don_returned");
            let rodou = self.rodou;
            self.inst = k;
            self.lugar_fonte = lf;
            self.rodou = rod;
            r?;
            if uma_vez && rodou {
                let alvo = match &l {
                    Some((z, _)) if z == "leader" => Some(&mut me.leader),
                    Some((_, i)) => me.field_chars.get_mut(*i),
                    None => me.stage.as_mut(),
                };
                let alvo = alvo.filter(|c| c.code == f.code).ok_or_else(|| ns("fonte do when_don_returned saiu do lugar"))?;
                alvo.extras.insert("_event_once_marker".into(), marca);
            }
        }
        Ok(())
    }

    /// Carta do lado `me` por lugar ("leader" | "field_chars" | "stage")
    fn no_lugar<'a>(me: &'a mut Jogador, l: &(String, usize)) -> R<&'a mut Carta> {
        match l.0.as_str() {
            "leader" => Ok(&mut me.leader),
            "field_chars" => me.field_chars.get_mut(l.1).ok_or_else(|| ns("lugar fora do campo")),
            "stage" => me.stage.as_mut().ok_or_else(|| ns("sem stage")),
            _ => Err(ns("lugar inesperado")),
        }
    }

    /// Escolha `sub_escolha` (max/min de board_value no motor) entre lugares do campo
    fn sub_escolha(&mut self, me: &mut Jogador, opp: &mut Jogador, cands: &[(String, usize)]) -> R<(String, usize)> {
        self.passivas_da_fila(me, opp)?;
        let ops: Vec<Lug> = cands.iter().map(|(z, i)| lug("eu", z, *i)).collect();
        match self.escolha_entre("sub_escolha", &ops, false)? {
            Some((l, z, i)) if l == "eu" => {
                let p = if z == "leader" || z == "stage" { (z, 0) } else { (z, i) };
                if cands.contains(&p) { Ok(p) } else { Err(ns("sub_escolha fora dos candidatos")) }
            }
            o => Err(ns(&format!("sub_escolha inesperada: {o:?}"))),
        }
    }

    /// `_pay_substitute_cost(cost, card)` (card = quem paga, pelo lugar)
    fn paga_substituicao(&mut self, cost: &Value, me: &mut Jogador, opp: &mut Jogador, card: &(String, usize)) -> R<bool> {
        let n = cost["count"].as_i64().unwrap_or(1);
        let no_campo = card.0 == "field_chars";
        match cost["action"].as_str().unwrap_or("") {
            "trash_self" => {
                if !no_campo {
                    return Ok(false);
                }
                crate::acoes::tira_do_campo_para_lixo(me, card.1);
            }
            "rest_don" => {
                if me.don_available < n {
                    return Ok(false);
                }
                me.don_available -= n;
                me.don_rested += n;
            }
            "return_own_don" | "don_minus" => {
                let (ok, dev) = devolve_don(me, n, None)?;
                self.dispara_don_devolvido(me, opp, dev)?;
                if !ok {
                    return Ok(false);
                }
            }
            "trash_from_hand" => {
                let mut cands = Vec::new();
                for (k, h) in me.hand.iter().enumerate() {
                    let i = dados(h)?;
                    if casa_filtro(&i, &cost["filter_type"], false)
                        && cost["power_gte"].as_i64().map_or(true, |x| i.power >= x)
                        && cost["power_lte"].as_i64().map_or(true, |x| i.power <= x)
                    {
                        cands.push(("hand".to_string(), k));
                    }
                }
                if (cands.len() as i64) < n {
                    return Ok(false);
                }
                let mut tirar = Vec::new();
                for _ in 0..n {
                    self.passivas_da_fila(me, opp)?;
                    let ops: Vec<Lug> = cands.iter().map(|(z, i)| lug("eu", z, *i)).collect();
                    let p = match self.escolha_entre("sub_escolha", &ops, false)? {
                        Some((l, z, i)) if l == "eu" && z == "hand" && cands.contains(&(z.clone(), i)) => (z, i),
                        o => return Err(ns(&format!("sub_escolha de descarte inesperada: {o:?}"))),
                    };
                    cands.retain(|c| *c != p);
                    tirar.push(p.1);
                    // os lugares na mao so mudam quando remove: remove ja
                    let x = me.hand.remove(p.1);
                    me.trash.push(x);
                    for c in cands.iter_mut() {
                        if c.1 > p.1 {
                            c.1 -= 1;
                        }
                    }
                }
            }
            "debuff_power_self" => Self::no_lugar(me, card)?.power_buff -= cost["amount"].as_i64().unwrap_or(0),
            "debuff_power_self_leader" => me.leader.power_buff -= cost["amount"].as_i64().unwrap_or(0),
            "rest_self" => {
                let c = Self::no_lugar(me, card)?;
                if c.rested {
                    return Ok(false);
                }
                c.rested = true;
            }
            "bounce_self" => {
                if !no_campo {
                    return Ok(false);
                }
                let mut x = me.field_chars.remove(card.1);
                if x.don_attached > 0 {
                    me.don_rested += x.don_attached;
                    x.don_attached = 0;
                }
                x.rested = false;
                me.hand.push(x);
            }
            "rest_self_and_trash_hand" => {
                let k = cost["trash_count"].as_i64().or(cost["count"].as_i64()).unwrap_or(1);
                if Self::no_lugar(me, card)?.rested || (me.hand.len() as i64) < k {
                    return Ok(false);
                }
                for _ in 0..k {
                    self.passivas_da_fila(me, opp)?;
                    let ops = zona_toda(me.hand.len(), "hand", None);
                    let Some((l, z, i)) = self.escolha_entre("descarte", &ops, false)? else { return Ok(false) };
                    if l != "eu" || z != "hand" || i >= me.hand.len() {
                        return Err(ns("descarte fora da mao"));
                    }
                    let x = me.hand.remove(i);
                    me.trash.push(x);
                }
                Self::no_lugar(me, card)?.rested = true;
            }
            "rest_leader" => {
                if me.leader.rested {
                    return Ok(false);
                }
                me.leader.rested = true;
            }
            t @ ("rest_own_filtered" | "rest_own_character" | "rest_own_other_character" | "rest_own_card") => {
                let mut cands: Vec<(String, usize)> = Vec::new();
                for (j, c) in me.field_chars.iter().enumerate() {
                    if c.rested {
                        continue;
                    }
                    let i = dados(c)?;
                    let ok = match t {
                        "rest_own_filtered" => casa_filtro(&i, &cost["filter_type"], false),
                        "rest_own_character" => {
                            let ex = cost["exclude"].as_str().unwrap_or("").to_lowercase();
                            cost["cost_gte"].as_i64().map_or(true, |x| i.cost >= x)
                                && cost["cost_lte"].as_i64().map_or(true, |x| i.cost <= x)
                                && (ex.is_empty() || !i.name.to_lowercase().contains(&ex))
                        }
                        "rest_own_other_character" => !(no_campo && j == card.1),
                        _ => true,
                    };
                    if ok {
                        cands.push(("field_chars".into(), j));
                    }
                }
                if t == "rest_own_card" {
                    if me.stage.as_ref().map_or(false, |s| !s.rested) {
                        cands.push(("stage".into(), 0));
                    }
                    if !me.leader.rested {
                        cands.push(("leader".into(), 0));
                    }
                }
                let k = if matches!(t, "rest_own_other_character" | "rest_own_card") { n } else { 1 };
                if (cands.len() as i64) < k {
                    return Ok(false);
                }
                for _ in 0..k {
                    let p = self.sub_escolha(me, opp, &cands)?;
                    cands.retain(|c| *c != p);
                    Self::no_lugar(me, &p)?.rested = true;
                }
            }
            t @ ("life_to_hand" | "life_to_trash") => {
                if (me.life.len() as i64) < n {
                    return Ok(false);
                }
                for _ in 0..n {
                    let mut c = me.life.pop().unwrap();
                    c.life_face_up = false;
                    if t == "life_to_hand" { me.hand.push(c) } else { me.trash.push(c) }
                }
            }
            "trash_to_deck_bottom" => {
                if (me.trash.len() as i64) < n {
                    return Ok(false);
                }
                for _ in 0..n {
                    self.passivas_da_fila(me, opp)?;
                    let ops = zona_toda(me.trash.len(), "trash", None);
                    let i = match self.escolha_entre("sub_escolha", &ops, false)? {
                        Some((l, z, i)) if l == "eu" && z == "trash" && i < me.trash.len() => i,
                        o => return Err(ns(&format!("sub_escolha do lixo inesperada: {o:?}"))),
                    };
                    let c = me.trash.remove(i);
                    me.deck.insert(0, c);
                }
            }
            "turn_life_face_up" => {
                if (me.life.len() as i64) < n {
                    return Ok(false);
                }
                let l = me.life.len();
                for c in me.life[l - n as usize..].iter_mut() {
                    c.life_face_up = true;
                }
            }
            "rest_opp_character" => {
                let mut cands = Vec::new();
                for i in 0..opp.field_chars.len() {
                    let c = &opp.field_chars[i];
                    if !c.rested && c.cannot_be_rested_until.is_empty() && !imune_a_rest(opp, me, i)? {
                        cands.push(i);
                    }
                }
                if (cands.len() as i64) < n {
                    return Ok(false);
                }
                for _ in 0..n {
                    self.passivas_da_fila(me, opp)?;
                    let i = self.alvo_no_oponente(&cands)?;
                    opp.field_chars[i].rested = true;
                    cands.retain(|&j| j != i);
                }
            }
            // qualquer outro: `_pay_substitute_cost` devolve None (nao paga)
            _ => return Ok(false),
        }
        Ok(true)
    }

    /// `try_any_substitute(alvo, 'ko', source_is_opp=True)` e depois
    /// `try_counter_event_substitute(alvo, 'ko')`, pelo executor do dono do alvo.
    pub fn substitui_ko(&mut self, me: &mut Jogador, opp: &mut Jogador, alvo: usize) -> R<bool> {
        self.substitui(me, opp, alvo, true)
    }

    /// `try_any_substitute(alvo, 'ko')` (+ evento [Counter] so na batalha)
    fn substitui(&mut self, me: &mut Jogador, opp: &mut Jogador, alvo: usize, com_evento: bool) -> R<bool> {
        let eh_sub = |s: &Value| matches!(s["action"].as_str(), Some("substitute_ko") | Some("substitute_removal"));
        let alvo_l = ("field_chars".to_string(), alvo);
        let a = me.field_chars[alvo].clone();
        let ainf = dados(&a)?;
        // 1) a propria carta (`try_substitute`)
        for timing in ["passive", "opp_turn", "your_turn"] {
            let Some(b) = ainf.efeitos.get(timing).cloned() else { continue };
            let passos: Vec<Value> = passos_de(&b).cloned().collect();
            for st in passos.iter().filter(|s| eh_sub(s)) {
                let neg = st["negated_if_any_character_named"].as_str().unwrap_or("").to_lowercase();
                if !neg.is_empty() {
                    let mut tem = false;
                    for c in me.field_chars.iter().chain(opp.field_chars.iter()) {
                        tem |= dados(c)?.name.to_lowercase().contains(&neg);
                    }
                    if tem {
                        continue;
                    }
                }
                let chave = (self.inst, a.code.clone(), format!("{timing}_substitute"));
                let uma = b["once_per_turn"].as_bool().unwrap_or(false);
                if uma && self.usados.contains(&chave) {
                    continue;
                }
                let outros = passos.iter().any(|s| !matches!(s["action"].as_str(), Some("substitute_ko") | Some("substitute_removal") | Some("substitute_rest")));
                if !outros && !self.condicoes(&b["conditions"], me, opp, &a, timing)? {
                    continue;
                }
                let ft = st["filter_type"].as_str().unwrap_or("").to_lowercase();
                if !ft.is_empty() && !ainf.sub_types.to_lowercase().contains(&ft) {
                    continue;
                }
                let fname = st["filter_name"].as_str().unwrap_or("").to_lowercase();
                if !fname.is_empty() && !ainf.name.to_lowercase().contains(&fname) {
                    continue;
                }
                self.passivas_da_fila(me, opp)?;
                if !self.veredito("paga_substituicao")? {
                    continue;
                }
                if !self.paga_substituicao(&st["cost"], me, opp, &alvo_l)? {
                    continue;
                }
                self.extras_de_substituicao(st, me, opp, &a, None)?;
                if uma {
                    self.usados.insert(chave);
                }
                return Ok(true);
            }
        }
        // 2) outras cartas do dono (`_try_external_substitute_from_source`)
        let mut fontes: Vec<(String, usize)> = (0..me.field_chars.len()).filter(|&j| j != alvo).map(|j| ("field_chars".to_string(), j)).collect();
        fontes.push(("leader".into(), 0));
        if me.stage.is_some() {
            fontes.push(("stage".into(), 0));
        }
        for fl in fontes {
            let f = Self::no_lugar(me, &fl)?.clone();
            let finf = dados(&f)?;
            for timing in ["passive", "opp_turn", "your_turn"] {
                let Some(b) = finf.efeitos.get(timing).cloned() else { continue };
                let passos: Vec<Value> = passos_de(&b).cloned().collect();
                if !passos.iter().any(|s| eh_sub(s)) {
                    continue;
                }
                // `_source_conditions_met_for_substitute`
                let mut cs = b["conditions"].as_object().cloned().unwrap_or_default();
                for k in ["self_type", "self_power_base_lte", "self_power_base_gte"] {
                    cs.remove(k);
                }
                if passos.iter().any(|s| !matches!(s["action"].as_str(), Some("substitute_ko") | Some("substitute_removal") | Some("substitute_rest"))) {
                    cs.clear();
                }
                if !self.condicoes(&Value::Object(cs), me, opp, &f, timing)? {
                    continue;
                }
                let dr = b["don_requirement"].as_i64().unwrap_or(0);
                if dr != 0 && f.don_attached < dr {
                    continue;
                }
                for st in passos.iter().filter(|s| eh_sub(s)) {
                    let chave = (self.inst, f.code.clone(), format!("{timing}_substitute"));
                    let uma = b["once_per_turn"].as_bool().unwrap_or(false);
                    if uma && self.usados.contains(&chave) {
                        continue;
                    }
                    if !casa_alvo_de_substituicao(&a, &ainf, false, st, &b)? {
                        continue;
                    }
                    let paga = if st["cost"]["action"].as_str() == Some("debuff_power_self") { alvo_l.clone() } else { fl.clone() };
                    self.passivas_da_fila(me, opp)?;
                    if !self.veredito("paga_substituicao")? {
                        continue;
                    }
                    if !self.paga_substituicao(&st["cost"], me, opp, &paga)? {
                        continue;
                    }
                    self.extras_de_substituicao(st, me, opp, &f, Some(fl.clone()))?;
                    if uma {
                        self.usados.insert(chave);
                    }
                    return Ok(true);
                }
            }
        }
        // 3) evento [Counter] da mao (`try_counter_event_substitute`)
        if !com_evento {
            return Ok(false);
        }
        let mut k = 0;
        while k < me.hand.len() {
            let ev = me.hand[k].clone();
            let ei = dados(&ev)?;
            k += 1;
            if ei.card_type != "EVENT" {
                continue;
            }
            let Some(b) = ei.efeitos.get("counter").cloned().filter(|b| b.as_object().map_or(false, |m| !m.is_empty())) else { continue };
            let custo = custo_de_jogar(me, opp, &ev)?;
            if me.don_available < custo {
                continue;
            }
            let passos: Vec<Value> = passos_de(&b).cloned().collect();
            for st in passos.iter().filter(|s| eh_sub(s)) {
                const CHAVES: &[&str] = &["filter_type", "filter_name", "filter_color", "cost_lte", "cost_gte",
                    "power_lte", "power_eq", "power_gte", "rested_only", "exclude"];
                if CHAVES.iter().any(|c| st.get(*c).is_some()) && !casa_alvo_de_substituicao(&a, &ainf, false, st, &b)? {
                    continue;
                }
                let c = &st["cost"];
                if c["action"].as_str() != Some("trash_from_hand") {
                    continue;
                }
                if (me.hand.len() as i64 - 1) < c["count"].as_i64().unwrap_or(1) {
                    continue;
                }
                let x = me.hand.remove(k - 1);
                me.trash.push(x);
                me.don_available -= custo;
                me.don_rested += custo;
                if !self.paga_substituicao(c, me, opp, &alvo_l)? {
                    // o Python segue para o proximo passo/evento com o evento ja gasto
                    return Err(ns("substituicao por evento nao paga"));
                }
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn extras_de_substituicao(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta,
                              lugar: Option<(String, usize)>) -> R<()> {
        let ex: Vec<Value> = st["extra_steps"].as_array().cloned().unwrap_or_default();
        if ex.is_empty() {
            return Ok(());
        }
        let inf = dados(fonte)?;
        let lf = std::mem::replace(&mut self.lugar_fonte, lugar);
        let mut r = Ok(());
        for e in &ex {
            r = self.passo(e, me, opp, fonte, &inf, "substitute");
            if r.is_err() {
                break;
            }
        }
        self.lugar_fonte = lf;
        r
    }

    fn proxima(&mut self, tipo: &str) -> R<Value> {
        let d = self.fila.pop_front().ok_or_else(|| ns(&format!("fila sem decisao ({tipo})")))?;
        if d.get("passivas").is_some() {
            return Err(ns("passivas de keyword antes de decisao fora do descarte"));
        }
        if d["tipo"].as_str() != Some(tipo) {
            return Err(ns(&format!("decisao fora de ordem: esperava {tipo}, veio {}", d["tipo"])));
        }
        Ok(d)
    }

    /// Escolha entre `opcoes` (lugares): do diario (conferida contra as opcoes) ou da politica.
    fn escolha_entre(&mut self, qual: &str, opcoes: &[Lug], pode_nenhuma: bool) -> R<Option<Lug>> {
        if let Some(p) = &self.politica {
            if opcoes.is_empty() {
                return Ok(None);
            }
            let k = p.borrow_mut().escolhe(qual, opcoes.len(), pode_nenhuma);
            return Ok(match k {
                Some(k) if k < opcoes.len() => Some(opcoes[k].clone()),
                _ if pode_nenhuma => None,
                _ => Some(opcoes[0].clone()),
            });
        }
        let r = self.escolha(qual)?;
        if let Some(x) = &r {
            if !opcoes.contains(x) {
                return Err(ns(&format!("{qual}: escolha fora das opcoes: {x:?}")));
            }
        }
        Ok(r)
    }

    /// Lugar da carta escolhida (lado de quem executa): ("eu"|"oponente", zona, i)
    fn escolha(&mut self, qual: &str) -> R<Option<(String, String, usize)>> {
        if self.politica.is_some() {
            return Err(ns(&format!("escolha sem opcoes na simulacao: {qual}")));
        }
        let d = self.proxima("escolha_efeito")?;
        if d["qual"].as_str() != Some(qual) {
            return Err(ns(&format!("escolha fora de ordem: esperava {qual}, veio {}", d["qual"])));
        }
        let c = &d["carta"];
        if c.is_null() {
            return Ok(None);
        }
        let a = c.as_array().ok_or_else(|| ns("escolha sem lugar"))?;
        let z = a.get(1).and_then(|x| x.as_str()).unwrap_or("?");
        Ok(Some((
            a.first().and_then(|x| x.as_str()).unwrap_or("?").to_string(),
            (if z == "field_stage" { "stage" } else { z }).to_string(),
            a.get(2).and_then(|x| x.as_u64()).ok_or_else(|| ns("escolha sem indice"))? as usize,
        )))
    }

    /// `_check_conditions` -- so as chaves conhecidas; qualquer outra = fora do nucleo.
    pub(crate) fn condicoes(&self, conds: &Value, me: &Jogador, opp: &Jogador, fonte: &Carta, gatilho: &str) -> R<bool> {
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
                "opp_don_on_field_gte" => opp.don_available + opp.don_rested >= n,
                // sub-chaves: so lidas dentro de chars_gte
                "chars_gte_cost_filter" | "chars_gte_type_filter" | "chars_gte_color_filter"
                | "chars_gte_distinct_names" | "chars_gte_exclude_self" => true,
                "chars_gte" => {
                    let o = conds.as_object().unwrap();
                    let contagem = if let Some(cf) = o.get("chars_gte_cost_filter").filter(|x| !x.is_null()) {
                        let cf = cf.as_i64().unwrap_or(0);
                        let mut k = 0;
                        for c in &me.field_chars {
                            if dados(c)?.cost >= cf {
                                k += 1;
                            }
                        }
                        k
                    } else if let Some(tf) = o.get("chars_gte_type_filter").filter(|x| !x.is_null()) {
                        let tipos: Vec<String> = match tf {
                            Value::Array(a) => a.iter().map(|x| x.as_str().unwrap_or("").to_lowercase()).collect(),
                            x => vec![x.as_str().unwrap_or("").to_lowercase()],
                        };
                        // `c is not card`: a fonte pelo lugar; senao, pela igualdade de estado
                        let excl = if o.get("chars_gte_exclude_self").and_then(|x| x.as_bool()).unwrap_or(false) {
                            self.idx_fonte(me, fonte)
                        } else {
                            None
                        };
                        let cor = o.get("chars_gte_color_filter").and_then(|x| x.as_str()).unwrap_or("").to_lowercase();
                        let mut nomes = std::collections::HashSet::new();
                        let mut k = 0;
                        for (j, c) in me.field_chars.iter().enumerate() {
                            if Some(j) == excl {
                                continue;
                            }
                            let ci = dados(c)?;
                            let st = ci.sub_types.to_lowercase();
                            if !tipos.iter().any(|t| st.contains(t.as_str())) {
                                continue;
                            }
                            if !cor.is_empty() && ci.color.to_lowercase() != cor {
                                continue;
                            }
                            k += 1;
                            nomes.insert(ci.name.clone());
                        }
                        if o.get("chars_gte_distinct_names").map_or(false, |x| x.as_bool().unwrap_or(!x.is_null())) {
                            nomes.len() as i64
                        } else {
                            k
                        }
                    } else {
                        me.field_chars.len() as i64
                    };
                    contagem >= n
                }
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
                "board_has_power_gte" => {
                    let mut mx: Option<i64> = None;
                    for c in me.field_chars.iter().chain(opp.field_chars.iter()) {
                        let pw = poder_meu_turno(c)?;
                        mx = Some(mx.map_or(pw, |m: i64| m.max(pw)));
                    }
                    mx.map_or(false, |m| m >= n)
                }
                "other_char_power_gte" | "other_char_cost_gte" => {
                    let ex = self.idx_fonte(me, fonte);
                    let mut outros: Vec<&Carta> = me.field_chars.iter().enumerate().filter(|(j, _)| Some(*j) != ex).map(|(_, c)| c).collect();
                    if k == "other_char_power_gte" {
                        outro_com_poder(m, &outros)?
                    } else {
                        if let Some(t) = m.get("other_char_cost_gte_type").and_then(|x| x.as_str()).filter(|t| !t.is_empty()) {
                            let mut f = Vec::new();
                            for c in outros {
                                if norm_tipo(&dados(c)?.sub_types).contains(&norm_tipo(t)) {
                                    f.push(c);
                                }
                            }
                            outros = f;
                        }
                        let mut mx: Option<i64> = None;
                        for c in &outros {
                            let x = dados(c)?.cost;
                            mx = Some(mx.map_or(x, |a: i64| a.max(x)));
                        }
                        mx.map_or(false, |x| x >= n)
                    }
                }
                "don_attached_total_gte" => {
                    me.leader.don_attached + me.field_chars.iter().map(|c| c.don_attached).sum::<i64>() >= n
                }
                "no_char_type_cost_gte" => {
                    let t = norm_tipo(v["type"].as_str().unwrap_or(""));
                    let g = v["cost_gte"].as_i64().unwrap_or(0);
                    let mut algum = false;
                    for c in &me.field_chars {
                        let i = dados(c)?;
                        algum |= norm_tipo(&i.sub_types).contains(&t) && i.cost >= g;
                    }
                    !algum
                }
                "events_in_trash_gte" => {
                    let mut e = 0;
                    for c in &me.trash {
                        if dados(c)?.card_type.to_lowercase() == "event" {
                            e += 1;
                        }
                    }
                    e >= n
                }
                "don_on_field_lte_opp" => {
                    !v.as_bool().unwrap_or(!v.is_null())
                        || me.don_available + me.don_rested <= opp.don_available + opp.don_rested
                }
                "opp_char_cost_eq_or_gte" => {
                    let (eq, ge) = (v["eq"].as_i64(), v["gte"].as_i64());
                    let mut a = false;
                    for c in &opp.field_chars {
                        let x = dados(c)?.cost;
                        a |= Some(x) == eq || ge.map_or(false, |g| x >= g);
                    }
                    a
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
            | "activate_trash_event_main" | "transfer_don" | "activate_main_effect"
            | "deal_damage" | "give_don_either_side" | "peek_opp_deck_top"
            | "buff_power_per_count" | "set_base_power" | "buff_cost" | "self_cant_take_life" | "select_grant_can_attack_active_turn" | "self_cant_play" | "give_don_opp" | "set_active"
            | "lock_opp_cannot_be_rested" | "lock_opp_blocker_turn" => true,
            "add_from_trash" => !me.trash.is_empty(),
            "deck_reorder_rest" | "deck_top_rest" => !me.deck.is_empty(),
            "trash_from_hand" | "hand_to_deck" => !me.hand.is_empty(),
            "life_to_hand" => !me.life.is_empty(),
            "trash_own_life" => if st["face"].as_str() == Some("up") { me.life.iter().any(|c| c.life_face_up) } else { !me.life.is_empty() },
            "attack_life" => !opp.life.is_empty(),
            "trash_from_deck_top" => !me.deck.is_empty(),
            "reveal_deck_top_conditional" | "select_grant_unblockable_turn" | "immunity" => true,
            "select_grant_rush" => {
                let nome = st["filter_name"].as_str().unwrap_or("").to_lowercase();
                let exn = st["exclude"].as_str().unwrap_or("").to_lowercase();
                let mut ok = false;
                for c in &me.field_chars {
                    let i = dados(c)?;
                    if !(c.just_played && !c.rested && !crate::acoes::is_rush(c, &i)) {
                        continue;
                    }
                    ok |= if !nome.is_empty() {
                        st["power_gte"].as_i64().map_or(true, |p| i.power >= p)
                            && (i.name.to_lowercase().contains(&nome) || c.code.to_lowercase().contains(&nome)
                                || casa_filtro(&i, &st["filter_type"], false))
                    } else {
                        st["cost_lte"].as_i64().map_or(true, |l| i.cost <= l)
                            && casa_filtro(&i, &st["filter_type"], false)
                            && (exn.is_empty() || !i.name.to_lowercase().contains(&exn))
                    };
                }
                ok
            }
            "opp_trash_from_hand" => !opp.hand.is_empty(),
            "turn_life_face_up" | "turn_life_face_down" => if st["target"].as_str() == Some("opponent") { !opp.life.is_empty() } else { !me.life.is_empty() },
            "negate_effect" => match st["target"].as_str().unwrap_or("opp_character") {
                "opp_leader" | "opp_leader_or_character" => true,
                _ => {
                    let cl = st["cost_lte"].as_i64();
                    if !st["cost_lte"].is_null() && cl.is_none() {
                        return Err(ns("negate cost_lte dinamico"));
                    }
                    let mut a = false;
                    for c in &opp.field_chars {
                        a |= cl.map_or(true, |l| dados(c).map_or(false, |d| d.cost <= l));
                    }
                    a
                }
            },
            "gain_blocker" | "gain_rush" | "gain_banish" | "gain_rush_character" => !(st["duration"].as_str() == Some("this_turn") && me.turn == 1),
            "play_from_trash" => !me.trash.is_empty(),
            "play_card" => {
                if st["source"].as_str() == Some("self") {
                    // `contains_identity(me.hand, card)`: a carta do trigger, pelo lugar
                    return Ok(match &self.lugar_fonte {
                        Some((z, i)) if z == "hand" => me.hand.get(*i).map(|c| &c.code) == Some(&fonte.code),
                        _ => false,
                    });
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
                        && casa_play_card(st, c, &i, false)?
                    {
                        ok = true;
                    }
                }
                ok
            }
            a @ ("ko" | "rest_opp_character" | "debuff_power" | "debuff_cost" | "lock_opp_character_refresh" | "bounce"
                 | "place_opp_character_bottom_deck"
                 | "lock_opp_character_attack") => {
                match st["target"].as_str() {
                    Some("opp_stage") => return Err(ns("alvo opp_stage")),
                    Some("opp_leader") | Some("opp_leader_or_character") | Some("self") => true,
                    _ => {
                        let mut algum = false;
                        for c in &opp.field_chars {
                            if casa_alvo(st, c, a == "rest_opp_character", false, me, opp)?
                                && (a != "lock_opp_character_refresh" || c.rested)
                            {
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
        self.atacante = if matches!(gatilho, "on_opp_attack" | "leader_battle_reactive") { self.atacante_batalha.clone() } else { None };
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
            "on_play" | "main" | "trigger" | "when_attacking" | "on_opp_attack" | "leader_battle_reactive"
                if self.politica.is_some() =>
            {
                if !self.veredito("pagar_custo")? {
                    return Ok(());
                }
            }
            "on_play" | "main" | "trigger" => {
                self.passivas_da_fila(me, opp)?;
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
                self.passivas_da_fila(me, opp)?;
                let d = self.proxima("paga_custo")?;
                let v = match d["qual"].as_str() {
                    Some("_combat_buff_worth_paying") if d["valor"].is_null() => {
                        self.passivas_da_fila(me, opp)?;
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
            | "opp_turn" | "end_of_turn" | "when_don_returned"
            | "when_damage_or_own_char_ko" | "on_opp_char_ko" | "on_own_char_ko" | "on_any_char_ko" => {}
            outro => return Err(ns(&format!("gatilho fora do nucleo: {outro}"))),
        }
        let custos: Vec<Value> = ef["costs"].as_array().cloned().unwrap_or_default();
        self.rest_any_don_n = 0; // `_last_cost_rest_any_don_count` zera a cada execute
        self.trash_any_n = 0;
        if !self.paga_custos(&custos, me, opp, fonte)? {
            return Ok(());
        }
        self.ultimo = None;
        self.ultimo_oponente = false;
        // `logs` do Python: os do custo pago + os de cada passo que FEZ algo.
        // Aproximado por "pagou custo ou o estado mudou" (so importa para o
        // marcador once_per_turn dos reativos, entao so mede quando ha marcador).
        let antes = if uma_vez && custos.is_empty() {
            Some((serde_json::to_value(&*me).ok(), serde_json::to_value(&*opp).ok()))
        } else {
            None
        };
        self.rodou = !custos.is_empty() || !passos.is_empty();
        for st in &passos {
            self.passo(st, me, opp, fonte, &inf, gatilho)?;
        }
        // executa aninhado (trigger, main) nao apaga o deste
        self.rodou = match antes {
            Some(a) => a != (serde_json::to_value(&*me).ok(), serde_json::to_value(&*opp).ok()),
            None => !custos.is_empty() || !passos.is_empty(),
        };
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
    fn paga_custos(&mut self, custos: &[Value], me: &mut Jogador, opp: &mut Jogador, fonte: &Carta) -> R<bool> {
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
                    let exclui = match &self.lugar_fonte {
                        Some((z, _)) if z == "leader" => Some(None),
                        Some((z, i)) if z == "field_chars" => Some(Some(*i)),
                        _ => None,
                    };
                    let (ok, dev) = devolve_don(me, n, exclui)?;
                    self.dispara_don_devolvido(me, opp, dev)?;
                    if !ok {
                        return Ok(false);
                    }
                }
                "trash_from_hand" => {
                    let cor = c["color"].as_str().unwrap_or("").to_lowercase();
                    let num = |k: &str| c[k].as_i64();
                    let mut pool = 0i64;
                    let mut elegiveis = Vec::new();
                    for (j, h) in me.hand.iter().enumerate() {
                        let hi = dados(h)?;
                        if casa_filtro(&hi, &c["filter_type"], false)
                            && (!c["has_trigger"].as_bool().unwrap_or(false) || hi.has_trigger)
                            && (cor.is_empty() || hi.color.to_lowercase().contains(&cor))
                            && num("power_lte").map_or(true, |x| hi.power <= x)
                            && num("power_gte").map_or(true, |x| hi.power >= x)
                            && num("power_eq").map_or(true, |x| hi.power == x)
                            && num("cost_lte").map_or(true, |x| hi.cost <= x)
                            && num("cost_gte").map_or(true, |x| hi.cost >= x)
                            && num("cost_eq").map_or(true, |x| hi.cost == x)
                        {
                            pool += 1;
                            elegiveis.push(j);
                        }
                    }
                    if pool < n {
                        return Ok(false);
                    }
                    for _ in 0..n {
                        self.passivas_da_fila(me, opp)?;
                        let ops: Vec<Lug> = elegiveis.iter().map(|&j| lug("eu", "hand", j)).collect();
                        let Some((lado, z, i)) = self.escolha_entre("descarte", &ops, false)? else { continue };
                        if lado != "eu" || z != "hand" || i >= me.hand.len() {
                            return Err(ns("descarte fora da mao"));
                        }
                        let x = me.hand.remove(i);
                        me.trash.push(x);
                        elegiveis.retain(|&j| j != i);
                        for j in elegiveis.iter_mut() {
                            if *j > i {
                                *j -= 1;
                            }
                        }
                    }
                }
                "rest_self" => {
                    let f = self.fonte_mut(me, fonte)?;
                    if f.rested {
                        return Ok(false);
                    }
                    f.rested = true;
                }
                "trash_self" => {
                    // so se a carta-fonte ainda esta no campo
                    if let Some((z, i)) = self.lugar_fonte.clone() {
                        if z == "field_chars" {
                            if me.field_chars.get(i).map(|c| &c.code) != Some(&fonte.code) {
                                return Err(ns("trash_self: fonte fora do lugar"));
                            }
                            crate::acoes::tira_do_campo_para_lixo(me, i);
                            self.lugar_fonte = None;
                        }
                    }
                }
                "rest_own_character" | "rest_own_card" => {
                    // candidatas na ordem do Python (campo, [stage, lider] em rest_own_card)
                    let mut cands: Vec<(String, usize)> = Vec::new();
                    let excl = if c["exclude_self"].as_bool().unwrap_or(false) {
                        match &self.lugar_fonte {
                            Some((z, i)) if z == "field_chars" => Some(*i),
                            _ => return Err(ns("rest_own_character exclude_self sem lugar")),
                        }
                    } else {
                        None
                    };
                    for (j, x) in me.field_chars.iter().enumerate() {
                        if x.rested {
                            continue;
                        }
                        if c["type"].as_str() == Some("rest_own_character") {
                            if Some(j) == excl {
                                continue;
                            }
                            let xi = dados(x)?;
                            if c["cost_gte"].as_i64().map_or(false, |g| xi.cost < g)
                                || c["cost_lte"].as_i64().map_or(false, |g| xi.cost > g)
                                || !casa_filtro(&xi, &c["filter_type"], false)
                            {
                                continue;
                            }
                            if let Some(nm) = c["filter_name"].as_str().filter(|s| !s.is_empty()) {
                                let nm = nm.to_lowercase();
                                if !xi.name.to_lowercase().contains(&nm) && !x.code.to_lowercase().contains(&nm) {
                                    continue;
                                }
                            } else if c["filter_name"].is_array() {
                                return Err(ns("rest_own_character com lista de nomes"));
                            }
                        }
                        cands.push(("field_chars".into(), j));
                    }
                    if c["type"].as_str() == Some("rest_own_card") {
                        if me.stage.as_ref().map_or(false, |s| !s.rested) {
                            cands.push(("stage".into(), 0));
                        }
                        if !me.leader.rested {
                            cands.push(("leader".into(), 0));
                        }
                    }
                    if (cands.len() as i64) < n {
                        return Ok(false);
                    }
                    for _ in 0..n {
                        self.passivas_da_fila(me, opp)?;
                        let ops: Vec<Lug> = cands.iter().map(|(z, i)| lug("eu", z, *i)).collect();
                        let Some((lado, z, i)) = self.escolha_entre("custo_restar", &ops, false)? else {
                            return Err(ns("custo_restar vazio"));
                        };
                        let z = if z == "field_stage" { "stage".to_string() } else { z };
                        let Some(pos) = cands.iter().position(|(cz, ci)| *cz == z && (*ci == i || cz != "field_chars")) else {
                            return Err(ns("custo_restar fora dos candidatos"));
                        };
                        if lado != "eu" {
                            return Err(ns("custo_restar do lado errado"));
                        }
                        cands.remove(pos);
                        match z.as_str() {
                            "field_chars" => me.field_chars[i].rested = true,
                            "stage" => me.stage.as_mut().unwrap().rested = true,
                            _ => me.leader.rested = true,
                        }
                    }
                }
                "rest_any_don" => {
                    self.rest_any_don_n = me.don_available;
                    me.don_rested += me.don_available;
                    me.don_available = 0;
                }
                "return_active_don_to_don_deck" => {
                    if me.don_available < n {
                        return Ok(false);
                    }
                    me.don_available -= n;
                    me.don_deck += n;
                }
                t @ ("turn_life_face_up" | "turn_life_face_down") => {
                    if (me.life.len() as i64) < n {
                        return Ok(false);
                    }
                    let quer = t == "turn_life_face_up";
                    let k = n as usize;
                    let alvos: Vec<usize> = if c["position"].as_str() == Some("top_or_bottom") {
                        let ja: Vec<usize> = (0..me.life.len()).filter(|&i| me.life[i].life_face_up == quer).collect();
                        if ja.len() >= k { ja[..k].to_vec() } else { (me.life.len() - k..me.life.len()).collect() }
                    } else {
                        (me.life.len() - k..me.life.len()).collect()
                    };
                    for i in alvos {
                        me.life[i].life_face_up = quer;
                    }
                }
                "life_to_hand" => {
                    if me.cant_take_life_this_turn || (me.life.len() as i64) < n {
                        return Ok(false);
                    }
                    for _ in 0..n {
                        let mut v = if c["source"].as_str() == Some("life_bottom") { me.life.remove(0) } else { me.life.pop().unwrap() };
                        v.life_face_up = false;
                        me.hand.push(v);
                    }
                }
                "trash_char_or_hand" => {
                    for _ in 0..n {
                        let mut chars = Vec::new();
                        for (j, x) in me.field_chars.iter().enumerate() {
                            if casa_filtro(&*dados(x)?, &c["filter_type"], false) {
                                chars.push(j);
                            }
                        }
                        if chars.is_empty() && me.hand.is_empty() {
                            return Ok(false);
                        }
                        self.passivas_da_fila(me, opp)?;
                        let mut ops: Vec<Lug> = chars.iter().map(|&j| lug("eu", "field_chars", j)).collect();
                        ops.extend(zona_toda(me.hand.len(), "hand", None));
                        match self.escolha_entre("sacrificio", &ops, false)? {
                            Some((l, z, i)) if l == "eu" && z == "hand" && i < me.hand.len() => {
                                let x = me.hand.remove(i);
                                me.trash.push(x);
                            }
                            Some((l, z, i)) if l == "eu" && z == "field_chars" && chars.contains(&i) => {
                                crate::acoes::tira_do_campo_para_lixo(me, i);
                            }
                            o => return Err(ns(&format!("sacrificio inesperado: {o:?}"))),
                        }
                    }
                }
                "return_own_character_to_hand" => {
                    let excl_self = if c["exclude_self"].as_bool().unwrap_or(false) {
                        match &self.lugar_fonte {
                            Some((z, i)) if z == "field_chars" => Some(*i),
                            _ => return Err(ns("return_own_character_to_hand exclude_self sem lugar")),
                        }
                    } else {
                        None
                    };
                    let exn = c["exclude"].as_str().unwrap_or("").to_lowercase();
                    let mut cands = Vec::new();
                    for (j, x) in me.field_chars.iter().enumerate() {
                        let xi = dados(x)?;
                        if Some(j) == excl_self || c["cost_gte"].as_i64().map_or(false, |g| xi.cost < g)
                            || !casa_filtro(&xi, &c["filter_type"], false)
                            || (!exn.is_empty() && xi.name.to_lowercase().contains(&exn))
                        {
                            continue;
                        }
                        cands.push(j);
                    }
                    if (cands.len() as i64) < n {
                        return Ok(false);
                    }
                    for _ in 0..n {
                        self.passivas_da_fila(me, opp)?;
                        let ops: Vec<Lug> = cands.iter().map(|&j| lug("eu", "field_chars", j)).collect();
                        let Some((l, z, i)) = self.escolha_entre("custo_sacrificar", &ops, false)? else {
                            return Err(ns("custo_sacrificar vazio"));
                        };
                        if l != "eu" || z != "field_chars" || !cands.contains(&i) {
                            return Err(ns("custo_sacrificar fora dos candidatos"));
                        }
                        let mut x = me.field_chars.remove(i);
                        if x.don_attached > 0 {
                            me.don_rested += x.don_attached;
                            x.don_attached = 0;
                        }
                        x.rested = false;
                        me.hand.push(x);
                        cands.retain(|&j| j != i);
                        for j in cands.iter_mut() {
                            if *j > i {
                                *j -= 1;
                            }
                        }
                        if let Some((zf, fi)) = self.lugar_fonte.clone() {
                            if zf == "field_chars" {
                                self.lugar_fonte = if fi == i { None } else if fi > i { Some((zf, fi - 1)) } else { Some((zf, fi)) };
                            }
                        }
                    }
                }
                "give_don_opp" => {
                    if opp.don_rested < n {
                        return Ok(false);
                    }
                    // maior effective_power(True); empate fica com o primeiro (campo, depois lider)
                    let mut melhor: Option<(Option<usize>, i64)> = None;
                    for (j, x) in opp.field_chars.iter().enumerate() {
                        let p = poder_meu_turno(x)?;
                        if melhor.map_or(true, |(_, b)| p > b) {
                            melhor = Some((Some(j), p));
                        }
                    }
                    let pl = poder_meu_turno(&opp.leader)?;
                    if melhor.map_or(true, |(_, b)| pl > b) {
                        melhor = Some((None, pl));
                    }
                    opp.don_rested -= n;
                    carta_mut(opp, melhor.unwrap().0)?.don_attached += n;
                }
                "trash_any_from_hand" => {
                    // guloso: trasha TODAS as elegiveis (sem escolha)
                    let tipos: Vec<String> = c["card_types"].as_array().into_iter().flatten()
                        .filter_map(|x| x.as_str().map(String::from)).collect();
                    let mut k = 0;
                    let mut resto = Vec::new();
                    for h in std::mem::take(&mut me.hand) {
                        let hi = dados(&h)?;
                        if casa_filtro(&hi, &c["filter_type"], false) && (tipos.is_empty() || tipos.contains(&hi.card_type)) {
                            me.trash.push(h);
                            k += 1;
                        } else {
                            resto.push(h);
                        }
                    }
                    me.hand = resto;
                    self.trash_any_n = k;
                }
                "ko_own_character" => {
                    let excl = match &self.lugar_fonte {
                        Some((z, i)) if z == "field_chars" => Some(*i),
                        _ => None,
                    };
                    let mut cands = Vec::new();
                    for (j, x) in me.field_chars.iter().enumerate() {
                        if Some(j) != excl && casa_filtro(&*dados(x)?, &c["filter_type"], false) {
                            cands.push(j);
                        }
                    }
                    if (cands.len() as i64) < n {
                        return Ok(false);
                    }
                    for _ in 0..n {
                        if cands.is_empty() {
                            break;
                        }
                        self.passivas_da_fila(me, opp)?;
                        let ops: Vec<Lug> = cands.iter().map(|&j| lug("eu", "field_chars", j)).collect();
                        let Some((l, z, i)) = self.escolha_entre("custo_sacrificar", &ops, false)? else {
                            return Err(ns("custo_sacrificar vazio"));
                        };
                        if l != "eu" || z != "field_chars" || !cands.contains(&i) {
                            return Err(ns("custo_sacrificar fora dos candidatos"));
                        }
                        crate::acoes::tira_do_campo_para_lixo(me, i);
                        let alvo = me.trash.last().cloned().unwrap();
                        cands.retain(|&j| j != i);
                        for j in cands.iter_mut() {
                            if *j > i {
                                *j -= 1;
                            }
                        }
                        if let Some((zf, fi)) = self.lugar_fonte.clone() {
                            if zf == "field_chars" && fi > i {
                                self.lugar_fonte = Some((zf, fi - 1));
                            }
                        }
                        // [On K.O.] do K.O.ado + reativos de KO (regra K.O. != Trash)
                        let lf = self.lugar_fonte.take();
                        self.executa(me, opp, &alvo, "on_ko")?;
                        self.lugar_fonte = lf;
                        self.dispara_ko(me, opp, &alvo)?;
                    }
                }
                outro => return Err(ns(&format!("custo fora do nucleo: {outro}"))),
            }
        }
        Ok(true)
    }

    /// A carta-fonte do efeito, no lugar onde esta (`card` do Python).
    fn fonte_mut<'a>(&self, me: &'a mut Jogador, fonte: &Carta) -> R<&'a mut Carta> {
        let c = match &self.lugar_fonte {
            Some((z, _)) if z == "leader" => &mut me.leader,
            Some((z, i)) if z == "field_chars" => me.field_chars.get_mut(*i).ok_or_else(|| ns("fonte fora do campo"))?,
            None => match me.stage.as_mut() {
                Some(s) if s.code == fonte.code => s,
                _ => return Err(ns("fonte sem lugar conhecido")),
            },
            _ => return Err(ns("fonte em zona inesperada")),
        };
        if c.code != fonte.code {
            return Err(ns("fonte fora do lugar"));
        }
        Ok(c)
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
        if self.ultimo_oponente && (st["target"].as_str() == Some("selected") || st["source"].as_str() == Some("selected")) {
            return Err(ns("passo em selected depois de alvo do oponente"));
        }
        match acao {
            "look_top_deck" | "immunity" => {}
            "trash_from_deck_top" => {
                if st["count_from_last_hand_trash"].as_bool().unwrap_or(false) {
                    return Err(ns("trash_from_deck_top count_from_last_hand_trash"));
                }
                for _ in 0..n {
                    let Some(x) = me.deck.pop() else { break };
                    me.trash.push(x);
                }
            }
            "reveal_deck_top_conditional" => {
                let Some(rv) = me.deck.last().cloned() else { return Ok(()) };
                let ri = dados(&rv)?;
                let cond = &st["condition"];
                for k in cond.as_object().into_iter().flatten().map(|(k, _)| k) {
                    if !matches!(k.as_str(), "revealed_card_type" | "revealed_card_cost_lte" | "revealed_card_cost_gte" | "revealed_card_power_gte") {
                        return Err(ns(&format!("reveal_deck_top_conditional condicao {k}")));
                    }
                }
                let mut m = true;
                if let Some(t) = cond["revealed_card_type"].as_str().filter(|t| !t.is_empty()) {
                    if !norm_tipo(&ri.sub_types).contains(&norm_tipo(t)) {
                        m = false;
                    }
                }
                if m && cond["revealed_card_cost_lte"].as_i64().map_or(false, |l| ri.cost > l) {
                    m = false;
                }
                if m && cond["revealed_card_cost_gte"].as_i64().map_or(false, |l| ri.cost < l) {
                    m = false;
                }
                if m && cond["revealed_card_power_gte"].as_i64().map_or(false, |l| ri.card_type != "CHARACTER" || ri.power < l) {
                    m = false;
                }
                let rt = st["return_to"].as_str();
                if rt == Some("bottom") || (rt == Some("top_or_bottom") && !m) {
                    let x = me.deck.pop().unwrap();
                    me.deck.insert(0, x);
                }
                if m {
                    let aninhados: Vec<Value> = st["on_match_steps"].as_array().cloned().unwrap_or_default();
                    for a in &aninhados {
                        self.passo(a, me, opp, fonte, inf, gatilho)?;
                    }
                }
            }
            "select_grant_rush" => {
                let num = |k: &str| st[k].as_i64();
                let mut cands: Vec<Option<usize>> = Vec::new();
                let nome = st["filter_name"].as_str().unwrap_or("").to_lowercase();
                if st["filter_name"].is_array() {
                    return Err(ns("select_grant_rush com lista de nomes"));
                }
                let exn = st["exclude"].as_str().unwrap_or("").to_lowercase();
                let sem_tag = st["filter_no_tag"].as_str().unwrap_or("");
                for (j, c) in me.field_chars.iter().enumerate() {
                    let i = dados(c)?;
                    if !(c.just_played && !c.rested && !crate::acoes::is_rush(c, &i)) {
                        continue;
                    }
                    let ok = if !nome.is_empty() {
                        num("power_gte").map_or(true, |p| i.power >= p)
                            && ((i.name.to_lowercase().contains(&nome) || c.code.to_lowercase().contains(&nome))
                                || casa_filtro(&i, &st["filter_type"], false))
                    } else {
                        num("cost_lte").map_or(true, |l| i.cost <= l)
                            && casa_filtro(&i, &st["filter_type"], false)
                            && (exn.is_empty() || !i.name.to_lowercase().contains(&exn))
                            && (sem_tag.is_empty() || !i.efeitos.contains_key(sem_tag))
                    };
                    if ok {
                        cands.push(Some(j));
                    }
                }
                if !nome.is_empty() {
                    // ordem do Python: pool por nome primeiro, depois o de tipo
                    let mut pn = Vec::new();
                    let mut pt = Vec::new();
                    for x in &cands {
                        let c = &me.field_chars[x.unwrap()];
                        let i = dados(c)?;
                        if i.name.to_lowercase().contains(&nome) || c.code.to_lowercase().contains(&nome) { pn.push(*x) } else { pt.push(*x) }
                    }
                    pn.extend(pt);
                    cands = pn;
                }
                for _ in 0..n.min(cands.len() as i64) {
                    self.passivas_da_fila(me, opp)?;
                    let x = self.alvo_meu(&cands)?;
                    let a = carta_mut(me, x)?;
                    if st["duration"].as_str() == Some("this_turn") {
                        a.rush_this_turn = true;
                    } else {
                        a.has_rush = true;
                    }
                    cands.retain(|c| *c != x);
                }
            }
            "select_grant_unblockable_turn" => {
                let bate = |c: &Carta, nm: &str| -> R<bool> {
                    let nm = nm.to_lowercase();
                    Ok(nm.is_empty() || dados(c)?.name.to_lowercase().contains(&nm) || c.code.to_lowercase().contains(&nm))
                };
                let nome = st["filter_name"].as_str().unwrap_or("");
                if st["filter_name"].is_array() {
                    return Err(ns("select_grant_unblockable_turn com lista de nomes"));
                }
                match st["target"].as_str() {
                    Some("leader_only") => {
                        if bate(&me.leader, nome)? {
                            me.leader.unblockable_this_turn = true;
                        }
                    }
                    Some("selected") => {
                        if self.ultimo_oponente {
                            return Err(ns("unblockable selected do oponente"));
                        }
                        if let Some(x) = self.ultimo {
                            carta_mut(me, x)?.unblockable_this_turn = true;
                        }
                    }
                    Some("don_recipient") => return Err(ns("unblockable don_recipient")),
                    _ => {
                        let cor = st["color"].as_str().unwrap_or("").to_lowercase();
                        let mut cands: Vec<Option<usize>> = Vec::new();
                        for (j, c) in me.field_chars.iter().enumerate() {
                            let i = dados(c)?;
                            if casa_filtro(&i, &st["filter_type"], false) && bate(c, nome)?
                                && st["power_gte"].as_i64().map_or(true, |p| i.power >= p)
                                && (cor.is_empty() || i.color.to_lowercase().contains(&cor))
                            {
                                cands.push(Some(j));
                            }
                        }
                        if st["include_leader"].as_bool().unwrap_or(false) {
                            let ok = if !nome.is_empty() { bate(&me.leader, nome)? } else { casa_filtro(&*dados(&me.leader)?, &st["filter_type"], false) };
                            if ok {
                                cands.push(None);
                            }
                        }
                        if !cands.is_empty() {
                            self.passivas_da_fila(me, opp)?;
                            let x = self.alvo_meu(&cands)?;
                            carta_mut(me, x)?.unblockable_this_turn = true;
                        }
                    }
                }
            }
            "self_cant_take_life" => me.cant_take_life_this_turn = true,
            "select_grant_can_attack_active_turn" => {
                let f = if st["filter_types"].is_null() || st["filter_types"].as_array().map_or(false, |a| a.is_empty())
                    || st["filter_types"].as_str() == Some("") { &st["filter_type"] } else { &st["filter_types"] };
                let mut cands: Vec<Option<usize>> = Vec::new();
                for (j, c) in me.field_chars.iter().enumerate() {
                    if casa_filtro(&*dados(c)?, f, false) {
                        cands.push(Some(j));
                    }
                }
                if st["include_leader"].as_bool().unwrap_or(false) && casa_filtro(&*dados(&me.leader)?, f, false) {
                    cands.push(None);
                }
                if !cands.is_empty() {
                    self.passivas_da_fila(me, opp)?;
                    let x = self.alvo_meu(&cands)?;
                    let a = carta_mut(me, x)?;
                    a.can_attack_active_this_turn = true;
                    if st["allow_played_this_turn"].as_bool().unwrap_or(false) {
                        a.rush_character_only_this_turn = true;
                    }
                }
            }
            "opp_trash_from_hand" => {
                if st["chosen_by"].as_str() == Some("effect_owner_blind") {
                    return Err(ns("opp_trash_from_hand aleatorio"));
                }
                let mut k = 0;
                for _ in 0..n.min(opp.hand.len() as i64) {
                    self.passivas_da_fila(me, opp)?;
                    let ops: Vec<Lug> = (0..opp.hand.len()).map(|j| lug("oponente", "hand", j)).collect();
                    let Some((lado, z, i)) = self.escolha_entre("descarte", &ops, false)? else { continue };
                    if lado != "oponente" || z != "hand" || i >= opp.hand.len() {
                        return Err(ns("descarte do oponente fora da mao"));
                    }
                    let x = opp.hand.remove(i);
                    opp.trash.push(x);
                    k += 1;
                }
                if k > 0 && tem_reativo(opp, &["on_hand_card_trashed"])? {
                    return Err(ns("reativo on_hand_card_trashed"));
                }
            }
            "set_base_power" => {
                if let Some(src) = st["source"].as_str() {
                    let v = match src {
                        "opp_leader" => poder_turno_do_outro(&opp.leader)?,
                        "own_leader" => poder_meu_turno(&me.leader)?,
                        "selected_opp_character" => {
                            let mut m: Option<i64> = None;
                            for c in &opp.field_chars {
                                let p = poder_turno_do_outro(c)?;
                                if m.map_or(true, |b| p > b) {
                                    m = Some(p);
                                }
                            }
                            match m {
                                Some(p) => p,
                                None => return Ok(()),
                            }
                        }
                        "opp_attacking_character" => return Err(ns("set_base_power do atacante")),
                        _ => return Ok(()),
                    };
                    self.fonte_mut(me, fonte)?.base_power_override = Some(v);
                } else if let Some(v) = st["amount"].as_i64() {
                    let f = &st["filter_type"];
                    let mut cands: Vec<Option<usize>> = Vec::new();
                    match st["target"].as_str().unwrap_or("self") {
                        "self" => {
                            if casa_filtro(&*dados(fonte)?, f, false) {
                                let c = self.fonte_mut(me, fonte)?;
                                c.base_power_override = Some(v);
                            }
                            return Ok(());
                        }
                        "leader" => {
                            if casa_filtro(&*dados(&me.leader)?, f, false) {
                                cands.push(None);
                            }
                        }
                        t @ ("own_character" | "leader_or_own_character" | "leader_or_character") => {
                            if t != "own_character" && casa_filtro(&*dados(&me.leader)?, f, false) {
                                cands.push(None);
                            }
                            for (j, c) in me.field_chars.iter().enumerate() {
                                if casa_filtro(&*dados(c)?, f, false) {
                                    cands.push(Some(j));
                                }
                            }
                        }
                        "opp_character" => return Err(ns("set_base_power em personagem do oponente")),
                        _ => {}
                    }
                    let mut melhor: Option<(Option<usize>, i64)> = None;
                    for x in cands {
                        let p = poder_meu_turno(carta_mut(me, x)?)?;
                        if melhor.map_or(true, |(_, b)| p > b) {
                            melhor = Some((x, p));
                        }
                    }
                    if let Some((x, _)) = melhor {
                        carta_mut(me, x)?.base_power_override = Some(v);
                    }
                }
            }
            "buff_cost" | "debuff_cost" => {
                let mut v = st["amount"].as_i64().unwrap_or(0);
                if acao == "debuff_cost" {
                    v = -v;
                }
                let alvo = st["target"].as_str().unwrap_or("self");
                let perm = st["duration"].as_str() == Some("permanent");
                if alvo == "own_play_hand" {
                    if st["duration"].as_str() == Some("next_play_only") {
                        let mut r = serde_json::Map::new();
                        for k in ["amount", "filter_type", "filter_name", "cost_gte"] {
                            if let Some(x) = st.get(k) {
                                r.insert(k.into(), x.clone());
                            }
                        }
                        me.pending_play_cost_reductions.push(Value::Object(r));
                    }
                    return Ok(());
                }
                let para = st["to_value"].as_i64();
                let aplica = |c: &mut Carta| -> R<()> {
                    let real = match para {
                        Some(t) => {
                            let i = dados(c)?;
                            -((i.cost + c.cost_buff + c.cost_buff_permanent).max(0) - t)
                        }
                        None => v,
                    };
                    if perm {
                        c.cost_buff_permanent += real;
                    } else {
                        c.cost_buff += real;
                    }
                    Ok(())
                };
                if alvo == "self" {
                    aplica(self.fonte_mut(me, fonte)?)?;
                    return Ok(());
                }
                let lado: &mut Jogador = if alvo == "own_character" { me } else { opp };
                let cl = match &st["cost_lte"] {
                    Value::Null => None,
                    x => Some(x.as_i64().ok_or_else(|| ns("custo: cost_lte dinamico"))?),
                };
                let nome = st["filter_name"].as_str().unwrap_or("").to_lowercase();
                let cor = st["color"].as_str().unwrap_or("").to_lowercase();
                let mut k = 0;
                for c in lado.field_chars.iter_mut() {
                    if k >= n {
                        break;
                    }
                    let i = dados(c)?;
                    if cl.map_or(false, |x| i.cost > x) || st["power_lte"].as_i64().map_or(false, |x| i.power > x)
                        || !casa_filtro(&i, &st["filter_type"], false)
                        || (!cor.is_empty() && !i.color.to_lowercase().contains(&cor))
                        || (!nome.is_empty() && !i.name.to_lowercase().contains(&nome))
                        || st["cost_gte"].as_i64().map_or(false, |x| i.cost < x)
                        || (st["filter_no_effect"].as_bool().unwrap_or(false) && !i.efeitos.is_empty())
                    {
                        continue;
                    }
                    aplica(c)?;
                    k += 1;
                }
            }
            "attack_life" => {
                for _ in 0..n {
                    let Some(mut v) = opp.life.pop() else { break };
                    v.life_face_up = false;
                    opp.trash.push(v);
                }
            }
            "life_to_hand" => {
                if !me.cant_take_life_this_turn {
                    for _ in 0..n {
                        if me.life.is_empty() {
                            break;
                        }
                        let mut v = if st["source"].as_str() == Some("life_bottom") { me.life.remove(0) } else { me.life.pop().unwrap() };
                        v.life_face_up = false;
                        me.hand.push(v);
                    }
                }
            }
            "add_from_trash" => {
                let num = |k: &str| st[k].as_i64();
                let nome = st["filter_name"].as_str().unwrap_or("").to_lowercase();
                let cor = st["color"].as_str().unwrap_or("").to_lowercase();
                let exn = st["exclude_name"].as_str().unwrap_or("").to_lowercase();
                let mut achou = Vec::new();
                for (k, c) in me.trash.iter().enumerate() {
                    let i = dados(c)?;
                    if num("cost_lte").map_or(false, |x| i.cost > x) || num("cost_gte").map_or(false, |x| i.cost < x)
                        || num("cost_eq").map_or(false, |x| i.cost != x) || num("power_lte").map_or(false, |x| i.power > x)
                        || !casa_filtro(&i, &st["filter_type"], false)
                        || (!nome.is_empty() && !i.name.to_lowercase().contains(&nome) && !c.code.to_lowercase().contains(&nome))
                        || (!cor.is_empty() && !i.color.to_lowercase().contains(&cor))
                        || (!exn.is_empty() && i.name.to_lowercase().contains(&exn))
                    {
                        continue;
                    }
                    achou.push(k);
                }
                for &k in achou.iter().take(n.max(0) as usize).rev() {
                    let c = me.trash.remove(k);
                    // a ordem de chegada na mao e a do lixo
                    me.hand.push(c);
                }
                let m = achou.len().min(n.max(0) as usize);
                let l = me.hand.len();
                me.hand[l - m..].reverse();
            }
            "deck_reorder_rest" | "deck_top_rest" => {
                // quantas olhou/pegou: ultimo look_top_deck / add_to_hand|trash_from_looked_deck da carta
                let (mut olha, mut pega) = (5i64, 0i64);
                for b in inf.efeitos.values() {
                    for s in passos_de(b) {
                        match s["action"].as_str() {
                            Some("look_top_deck") => olha = s["count"].as_i64().unwrap_or(5),
                            Some("add_to_hand") | Some("trash_from_looked_deck") => pega = s["count"].as_i64().unwrap_or(1),
                            _ => {}
                        }
                    }
                }
                let k = (olha - pega).max(0).min(me.deck.len() as i64) as usize;
                let mut visto: Vec<Carta> = Vec::new();
                for _ in 0..k {
                    visto.push(me.deck.pop().unwrap());
                }
                if !visto.is_empty() {
                    let ordem: Vec<usize> = if let Some(p) = self.politica.clone() {
                        // a politica tira uma a uma (a primeira tirada vai mais fundo)
                        let mut resto: Vec<usize> = (0..visto.len()).collect();
                        let mut o = Vec::new();
                        while !resto.is_empty() {
                            let k = p.borrow_mut().escolhe("reordena", resto.len(), false).unwrap_or(0).min(resto.len() - 1);
                            o.push(resto.remove(k));
                        }
                        o
                    } else {
                        let d = self.proxima("escolha_efeito")?;
                        if d["qual"].as_str() != Some("reordena") {
                            return Err(ns("reordena fora de ordem"));
                        }
                        d["ordem"].as_array().ok_or_else(|| ns("reordena sem ordem"))?
                            .iter().filter_map(|x| x.as_u64().map(|v| v as usize)).collect()
                    };
                    let mut vis: Vec<bool> = vec![false; visto.len()];
                    if ordem.len() != visto.len() || ordem.iter().any(|&j| j >= vis.len() || std::mem::replace(&mut vis[j], true)) {
                        return Err(ns("reordena invalida"));
                    }
                    for j in ordem {
                        me.deck.push(visto[j].clone());
                    }
                }
            }
            "buff_power_per_count" => {
                let fonte_n = match st["source"].as_str().unwrap_or("trash") {
                    "events_in_trash" => {
                        let mut k = 0;
                        for c in &me.trash {
                            if dados(c)?.card_type == "EVENT" {
                                k += 1;
                            }
                        }
                        k
                    }
                    "trash" => me.trash.len() as i64,
                    "rested_don" => me.don_rested,
                    "hand" => me.hand.len() as i64,
                    "unique_character_names" => {
                        let mut s = std::collections::HashSet::new();
                        for c in &me.field_chars {
                            s.insert(dados(c)?.name.clone());
                        }
                        s.len() as i64
                    }
                    "own_characters" => me.field_chars.len() as i64,
                    "rested_don_this_effect" => self.rest_any_don_n,
                    "trashed_hand_this_effect" => self.trash_any_n,
                    o => return Err(ns(&format!("buff_power_per_count source {o}"))),
                };
                let por = st["count_per"].as_i64().unwrap_or(1).max(1);
                let v = (fonte_n / por) * st["amount_per"].as_i64().unwrap_or(1000);
                if v > 0 {
                    match st["target"].as_str().unwrap_or("self") {
                        "self" => self.fonte_mut(me, fonte)?.power_buff += v,
                        "leader" => me.leader.power_buff += v,
                        "leader_or_character" => {
                            let mut melhor: Option<(Option<usize>, i64)> = None;
                            for (j, c) in me.field_chars.iter().enumerate() {
                                if !casa_filtro(&*dados(c)?, &st["filter_type"], false) {
                                    continue;
                                }
                                let p = poder_meu_turno(c)?;
                                if melhor.map_or(true, |(_, b)| p > b) {
                                    melhor = Some((Some(j), p));
                                }
                            }
                            let pl = poder_meu_turno(&me.leader)?;
                            if melhor.map_or(true, |(_, b)| pl > b) {
                                melhor = Some((None, pl));
                            }
                            carta_mut(me, melhor.unwrap().0)?.power_buff += v;
                        }
                        t @ ("all_allies" | "all_allies_and_leader") => {
                            for c in me.field_chars.iter_mut() {
                                c.power_buff += v;
                            }
                            if t == "all_allies_and_leader" {
                                me.leader.power_buff += v;
                            }
                        }
                        _ => {}
                    }
                }
            }
            "bounce" | "place_opp_character_bottom_deck" => self.remove_do_oponente(st, acao, me, opp)?,
            "negate_effect" => {
                let dur = match st["duration"].as_str().unwrap_or("this_turn") {
                    "until_opp_end_phase" => "opp_end_phase",
                    "until_my_next_turn_start" => "my_next_turn_start",
                    _ => "opp_turn_end",
                };
                match st["target"].as_str().unwrap_or("opp_character") {
                    "opp_leader" => opp.leader.effects_negated_until = dur.into(),
                    "opp_leader_or_character" => return Err(ns("negate_effect leader_or_character (board_value)")),
                    _ => {
                        let cl = match &st["cost_lte"] {
                            Value::Null => None,
                            v => Some(v.as_i64().ok_or_else(|| ns("negate cost_lte dinamico"))?),
                        };
                        let mut cands = Vec::new();
                        for (i, c) in opp.field_chars.iter().enumerate() {
                            if cl.map_or(true, |l| dados(c).map_or(false, |d| d.cost <= l)) {
                                cands.push(i);
                            }
                        }
                        if !cands.is_empty() {
                            self.passivas_da_fila(me, opp)?;
                            let i = self.alvo_no_oponente(&cands)?;
                            opp.field_chars[i].effects_negated_until = dur.into();
                            self.ultimo = None;
                            self.ultimo_oponente = true;
                        }
                    }
                }
            }
            "trash_from_hand" => {
                let mut k = 0;
                for _ in 0..n.min(me.hand.len() as i64) {
                    self.passivas_da_fila(me, opp)?;
                    let ops = zona_toda(me.hand.len(), "hand", None);
                    let Some((lado, z, i)) = self.escolha_entre("descarte", &ops, false)? else { continue };
                    if lado != "eu" || z != "hand" || i >= me.hand.len() {
                        return Err(ns("descarte fora da mao"));
                    }
                    let x = me.hand.remove(i);
                    me.trash.push(x);
                    k += 1;
                }
                if k > 0 && tem_reativo(me, &["on_hand_card_trashed"])? {
                    return Err(ns("reativo on_hand_card_trashed"));
                }
            }
            "peek_opp_deck_top" => {
                if let Some(c) = opp.deck.last_mut() {
                    c.revela(crate::estado::CONHECIDA_OPONENTE);
                }
            }
            "trash_own_life" => {
                if st["face"].as_str() == Some("up") {
                    let mut resto = Vec::new();
                    for mut c in std::mem::take(&mut me.life) {
                        if c.life_face_up {
                            c.life_face_up = false;
                            me.trash.push(c);
                        } else {
                            resto.push(c);
                        }
                    }
                    me.life = resto;
                } else {
                    let ate1 = st["until_1"].as_bool().unwrap_or(false);
                    let mut k = 0;
                    while if ate1 { me.life.len() > 1 } else { k < n && !me.life.is_empty() } {
                        let mut c = me.life.pop().unwrap();
                        c.life_face_up = false;
                        me.trash.push(c);
                        k += 1;
                    }
                }
            }
            "gain_banish" => self.fonte_mut(me, fonte)?.has_banish = true,
            "gain_rush_character" => {
                let f = self.fonte_mut(me, fonte)?;
                f.has_rush_character = true;
                f.rush_character_only_this_turn = !(f.has_rush || f.rush_this_turn);
            }
            "lock_opp_character_attack" | "lock_opp_cannot_be_rested" | "lock_opp_blocker_turn"
            | "lock_opp_character_refresh" => self.trava(st, acao, me, opp)?,
            "self_cant_play" => {
                if st["scope"].as_str() == Some("hand") {
                    me.cant_play_from_hand_this_turn = true;
                } else {
                    me.cant_play_chars_this_turn = true;
                    let g = st["cost_gte"].as_i64().unwrap_or(0);
                    if g != 0 {
                        me.cant_play_cost_gte = g;
                    }
                }
            }
            "give_don_opp" => {
                let mut melhor: Option<(Option<usize>, i64)> = None;
                for (j, x) in opp.field_chars.iter().enumerate() {
                    let p = poder_meu_turno(x)?;
                    if melhor.map_or(true, |(_, b)| p > b) {
                        melhor = Some((Some(j), p));
                    }
                }
                let pl = poder_meu_turno(&opp.leader)?;
                if melhor.map_or(true, |(_, b)| pl > b) {
                    melhor = Some((None, pl));
                }
                let t = if st["rested"].as_bool().unwrap_or(false) {
                    let r = n.min(opp.don_rested);
                    opp.don_rested -= r;
                    r
                } else {
                    let a = n.min(opp.don_available);
                    opp.don_available -= a;
                    let r = (n - a).max(0).min(opp.don_rested);
                    opp.don_rested -= r;
                    a + r
                };
                carta_mut(opp, melhor.unwrap().0)?.don_attached += t;
            }
            "gain_blocker" | "gain_rush" => {
                let f = if st["target"].as_str() == Some("selected") {
                    // `_last_selected` (do proprio lado; None = nada selecionado)
                    let Some(x) = self.ultimo else { return Ok(()) };
                    carta_mut(me, x)?
                } else {
                    self.fonte_mut(me, fonte)?
                };
                let temp = if acao == "gain_blocker" {
                    matches!(st["duration"].as_str(), Some("this_turn") | Some("until_opp_turn_end") | Some("until_opp_end_phase"))
                } else {
                    st["duration"].as_str() == Some("this_turn")
                };
                match (acao, temp) {
                    ("gain_blocker", true) => f.blocker_this_turn = true,
                    ("gain_blocker", false) => f.has_blocker = true,
                    (_, true) => f.rush_this_turn = true,
                    _ => f.has_rush = true,
                }
            }
            "set_active" => match st["target"].as_str().unwrap_or("self") {
                "self" => self.fonte_mut(me, fonte)?.rested = false,
                "leader" => {
                    if casa_filtro(&*dados(&me.leader)?, &st["filter_type"], false) {
                        me.leader.rested = false;
                    }
                }
                "own_stage" => {
                    if let Some(s) = me.stage.as_mut() {
                        let cor = st["color"].as_str().unwrap_or("").to_lowercase();
                        if s.rested && (cor.is_empty() || dados(s)?.color.to_lowercase().contains(&cor)) {
                            s.rested = false;
                        }
                    }
                }
                t => {
                    let num = |k: &str| st[k].as_i64();
                    let nome = st["filter_name"].as_str().unwrap_or("").to_lowercase();
                    let cor = st["color"].as_str().unwrap_or("").to_lowercase();
                    let atr = st["attribute"].as_str().unwrap_or("").to_lowercase();
                    if st["filter_name"].is_array() {
                        return Err(ns("set_active com lista de nomes"));
                    }
                    let mut cands: Vec<Option<usize>> = Vec::new();
                    for (j, c) in me.field_chars.iter().enumerate() {
                        let i = dados(c)?;
                        if !c.rested || !casa_filtro(&i, &st["filter_type"], false)
                            || (!nome.is_empty() && !i.name.to_lowercase().contains(&nome) && !c.code.to_lowercase().contains(&nome))
                            || (!cor.is_empty() && !i.color.to_lowercase().contains(&cor))
                            || (!atr.is_empty() && !i.attribute.to_lowercase().contains(&atr))
                            || num("cost_lte").map_or(false, |x| i.cost > x) || num("cost_gte").map_or(false, |x| i.cost < x)
                            || num("cost_eq").map_or(false, |x| i.cost != x) || num("power_lte").map_or(false, |x| i.power > x)
                            || num("power_eq").map_or(false, |x| i.power != x)
                        {
                            continue;
                        }
                        cands.push(Some(j));
                    }
                    let mut ativou = false;
                    for _ in 0..n {
                        if cands.is_empty() {
                            break;
                        }
                        self.passivas_da_fila(me, opp)?;
                        let x = self.alvo_meu(&cands)?;
                        carta_mut(me, x)?.rested = false;
                        cands.retain(|c| *c != x);
                        ativou = true;
                        self.ultimo = Some(x);
                        self.ultimo_oponente = false;
                    }
                    if (t == "own_character_and_leader" || (t == "leader_or_character" && !ativou)) && me.leader.rested {
                        me.leader.rested = false;
                    }
                }
            },
            "turn_life_face_up" | "turn_life_face_down" => {
                let dono: &mut Jogador = if st["target"].as_str() == Some("opponent") { opp } else { me };
                if !dono.life.is_empty() {
                    let k = if st["count"].as_str() == Some("all") { dono.life.len() } else { (n.max(0) as usize).min(dono.life.len()) };
                    let l = dono.life.len();
                    for c in dono.life[l - k..].iter_mut() {
                        c.life_face_up = acao == "turn_life_face_up";
                    }
                }
            }
            // nao implementados no motor Python (retornam '' sem mudar nada): espelho
            "redirect_attack_target" | "activate_trash_event_main" | "transfer_don" => {}
            "activate_main_effect" => self.executa(me, opp, fonte, "main")?,
            "hand_to_deck" => {
                for _ in 0..n.min(me.hand.len() as i64) {
                    self.passivas_da_fila(me, opp)?;
                    let ops = zona_toda(me.hand.len(), "hand", None);
                    let Some((lado, z, i)) = self.escolha_entre("descarte", &ops, false)? else { continue };
                    if lado != "eu" || z != "hand" || i >= me.hand.len() {
                        return Err(ns("hand_to_deck fora da mao"));
                    }
                    let x = me.hand.remove(i);
                    me.deck.insert(0, x);
                }
            }
            "deal_damage" => {
                for _ in 0..n {
                    let Some(mut v) = opp.life.pop() else { break };
                    v.life_face_up = false;
                    opp.hand.push(v.clone());
                    if dados(&v)?.has_trigger {
                        // `EffectExecutor(opp, me)` novo, fora do turno de quem tem a vida
                        let (k, lf) = (self.inst, self.lugar_fonte.replace(("hand".into(), opp.hand.len() - 1)));
                        self.inst = 7000 + self.fila.len() as u32 + self.usados.len() as u32;
                        let r = self.executa(opp, me, &v, "trigger");
                        self.inst = k;
                        self.lugar_fonte = lf;
                        r?;
                    }
                }
            }
            "give_don_either_side" => {
                let proprio = self.veredito("don_proprio")?;
                let mut s2 = st.clone();
                s2["action"] = Value::from(if proprio { "give_don" } else { "give_don_opp" });
                self.passo(&s2, me, opp, fonte, inf, gatilho)?;
            }
            "draw" => {
                let mut n = n;
                match st["count_source"].as_str() {
                    None => {}
                    Some("own_field_type_count") => {
                        n = 0;
                        for c in &me.field_chars {
                            if casa_filtro(&*dados(c)?, &st["filter_type"], false) {
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
                    self.passivas_da_fila(me, opp)?;
                    let ops = zona_toda(me.hand.len(), "hand", None);
                    let Some((lado, z, i)) = self.escolha_entre("descarte", &ops, false)? else { continue };
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
            "add_to_hand" => {
                self.passivas_da_fila(me, opp)?;
                self.busca(st, me, inf)?
            }
            "ko" => self.ko(st, me, opp, fonte)?,
            "buff_power" => self.buff(st, me, opp, fonte)?,
            "give_don" => {
                self.passivas_da_fila(me, opp)?;
                self.da_don(st, me)?
            }
            "play_from_trash" => self.joga_do_lixo(st, me, opp)?,
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
            me.deck[i].revela(crate::estado::CONHECIDA_DONO);
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
            let ops: Vec<Lug> = filtradas.iter().map(|&j| lug("eu", "deck", j)).collect();
            let Some((lado, z, i)) = self.escolha_entre("busca", &ops, false)? else { break };
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
                c.revela(crate::estado::CONHECIDA_OPONENTE);
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
    /// `_battle_attacker`, se ainda esta no lugar (Some(None) = lider)
    fn atacante_no(&self, opp: &Jogador) -> Option<Option<usize>> {
        match &self.atacante {
            Some((None, c)) if &opp.leader.code == c => Some(None),
            Some((Some(i), c)) if opp.field_chars.get(*i).map(|x| &x.code) == Some(c) => Some(Some(*i)),
            _ => None,
        }
    }

    fn alvo_no_oponente(&mut self, cands: &[usize]) -> R<usize> {
        let ops: Vec<Lug> = cands.iter().map(|&i| lug("oponente", "field_chars", i)).collect();
        match self.escolha_entre("alvo", &ops, false)? {
            Some((l, z, i)) if l == "oponente" && z == "field_chars" && cands.contains(&i) => Ok(i),
            outro => Err(ns(&format!("alvo fora dos candidatos: {outro:?}"))),
        }
    }

    /// `ko` em personagem do oponente (sem orcamento total, sem stage).
    fn ko(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta) -> R<()> {
        let t = st["target"].as_str().unwrap_or("opp_character");
        if t != "opp_character" {
            return Err(ns(&format!("ko com alvo {t}")));
        }
        if !st["alt_target"].is_null() {
            return Err(ns("ko com alt_target"));
        }
        let tpl = st["total_power_lte"].as_i64();
        let orcamento = tpl.is_some() || st["total_cost_lte"].as_i64().is_some();
        if tem_reativo(me, &["on_own_effect_removes_char"])? || tem_reativo(opp, &["on_own_effect_removes_char"])? {
            return Err(ns("reativo on_own_effect_removes_char"));
        }
        let n = st["count"].as_i64().unwrap_or(1).max(0) as usize;
        let mut cands: Vec<usize> = Vec::new();
        for (i, c) in opp.field_chars.iter().enumerate() {
            if casa_alvo(st, c, false, false, me, opp)? {
                cands.push(i);
            }
        }
        if orcamento && self.politica.is_some() {
            // a politica monta a combinacao uma carta por vez, dentro do orcamento
            let (tp, tc) = (st["total_power_lte"].as_i64(), st["total_cost_lte"].as_i64());
            let (mut sp, mut sc) = (0i64, 0i64);
            let mut combo = Vec::new();
            while combo.len() < n {
                let mut ops = Vec::new();
                for &j in &cands {
                    let i = dados(&opp.field_chars[j])?;
                    if !combo.contains(&j) && tp.map_or(true, |l| sp + i.power <= l) && tc.map_or(true, |l| sc + i.cost <= l) {
                        ops.push(lug("oponente", "field_chars", j));
                    }
                }
                let Some((_, _, j)) = self.escolha_entre("orcamento", &ops, true)? else { break };
                let i = dados(&opp.field_chars[j])?;
                sp += i.power;
                sc += i.cost;
                combo.push(j);
            }
            cands = combo;
        } else if orcamento {
            // a combinacao que cabe no orcamento (heuristica do Python, no diario)
            self.passivas_da_fila(me, opp)?;
            let d = self.proxima("escolha_efeito")?;
            if d["qual"].as_str() != Some("orcamento") {
                return Err(ns("escolha fora de ordem: esperava orcamento"));
            }
            let mut combo = Vec::new();
            for c in d["cartas"].as_array().into_iter().flatten() {
                let i = match (c[0].as_str(), c[1].as_str(), c[2].as_u64()) {
                    (Some("oponente"), Some("field_chars"), Some(i)) if cands.contains(&(i as usize)) => i as usize,
                    _ => return Err(ns("orcamento fora dos candidatos")),
                };
                combo.push(i);
            }
            cands = combo;
        }
        let mut usado = 0i64;
        for _ in 0..n.min(cands.len()) {
            self.passivas_da_fila(me, opp)?;
            let i = self.alvo_no_oponente(&cands)?;
            let pw = dados(&opp.field_chars[i])?.power;
            if tpl.map_or(false, |l| usado + pw > l) {
                cands.retain(|&j| j != i);
                continue;
            }
            let fonte_char = if dados(fonte)?.card_type == "CHARACTER" { Some(fonte) } else { None };
            let saiu_da_lista = |cands: &mut Vec<usize>| cands.retain(|&j| j != i);
            if imune_a_ko(opp, me, i, fonte_char, false)? {
                saiu_da_lista(&mut cands);
                continue;
            }
            // `EffectExecutor(owner, me)` novo para a substituicao
            let (k_, lf_) = (self.inst, self.lugar_fonte.take());
            self.inst = 7500 + self.fila.len() as u32 + self.usados.len() as u32;
            let sub = self.substitui(opp, me, i, false);
            self.inst = k_;
            self.lugar_fonte = lf_;
            if sub? {
                return Err(ns("ko: substituicao paga (indices do campo podem mudar)"));
            }
            crate::acoes::tira_do_campo_para_lixo(opp, i);
            usado += pw;
            let alvo = opp.trash.last().cloned().unwrap();
            cands.retain(|&j| j != i);
            for j in cands.iter_mut() {
                if *j > i {
                    *j -= 1;
                }
            }
            // `ee_target = EffectExecutor(owner, me)`: [On K.O.] do alvo + reativos de KO
            let resto: Vec<String> = cands.iter().map(|&j| opp.field_chars[j].code.clone()).collect();
            let mut ee = Executor::novo(std::mem::take(&mut self.fila));
            ee.politica = self.politica.clone();
            ee.inst = 7700 + self.usados.len() as u32;
            let r = ee.executa(opp, me, &alvo, "on_ko")
                .and_then(|_| ee.dispara_dano_ou_ko(opp, me, Some(&alvo)))
                .and_then(|_| ee.dispara_ko(opp, me, &alvo));
            self.fila = std::mem::take(&mut ee.fila);
            r?;
            if cands.iter().zip(&resto).any(|(&j, c)| opp.field_chars.get(j).map(|x| &x.code) != Some(c)) {
                return Err(ns("ko: campo do alvo mudou no on_ko"));
            }
        }
        Ok(())
    }

    /// `buff_power` (a duracao nao muda a execucao: o buff some no inicio do turno)
    fn buff(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta) -> R<()> {
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
                self.passivas_da_fila(me, opp)?;
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
                    self.passivas_da_fila(me, opp)?;
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
        let count = st["count"].as_i64().unwrap_or(1);
        let (x, t) = if self.politica.is_some() {
            let t = if st["rested"].as_bool().unwrap_or(false) {
                count.min(me.don_rested)
            } else {
                let r = count.min(me.don_rested);
                r + (count - r).max(0).min(me.don_available)
            };
            (self.alvo_meu_q("give_don", &alvos)?, t)
        } else {
            let d = self.proxima("escolha_efeito")?;
            if d["qual"].as_str() != Some("give_don") {
                return Err(ns("decisao de give_don fora de ordem"));
            }
            let x = match d["carta"].as_array().map(|a| (a[0].as_str(), a[1].as_str(), a[2].as_u64())) {
                Some((Some("eu"), Some("field_chars"), Some(i))) => Some(i as usize),
                Some((Some("eu"), Some("leader"), _)) => None,
                _ => return Err(ns("give_don sem alvo valido")),
            };
            (x, d["qtd"].as_i64().unwrap_or(0))
        };
        if !alvos.contains(&x) {
            return Err(ns("give_don fora dos alvos"));
        }
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
        if let Some(p) = &self.politica {
            return Ok(p.borrow_mut().veredito(qual));
        }
        let d = self.proxima("veredito_efeito")?;
        if d["qual"].as_str() != Some(qual) {
            return Err(ns(&format!("veredito fora de ordem: esperava {qual}, veio {}", d["qual"])));
        }
        Ok(d["valor"].as_bool().unwrap_or(false))
    }

    /// Campo cheio dentro de efeito: quem sai e decisao (fila `sai_campo`).
    fn sai_do_campo(&mut self, me: &mut Jogador) -> R<()> {
        let ops = zona_toda(me.field_chars.len(), "field_chars", None);
        match self.escolha_entre("sai_campo", &ops, true)? {
            None => Ok(()),
            Some((l, z, i)) if l == "eu" && z == "field_chars" && i < me.field_chars.len() => {
                crate::acoes::tira_do_campo_para_lixo(me, i);
                Ok(())
            }
            outro => Err(ns(&format!("sai_campo inesperado: {outro:?}"))),
        }
    }

    /// Personagem entra no campo por efeito: entra, passivas de keyword,
    /// DEPOIS just_played / rush de personagem (ordem do Python).
    fn entra_personagem(me: &mut Jogador, opp: &Jogador, mut c: Carta, rested: bool) -> R<()> {
        c.rested = rested;
        me.field_chars.push(c);
        aplica_passivas_keyword(me, opp)?;
        let n = me.field_chars.last_mut().unwrap();
        let i = dados(n)?;
        n.just_played = !(n.has_rush || n.rush_this_turn || crate::acoes::is_rush_character(n, &i));
        n.rush_character_only_this_turn =
            crate::acoes::is_rush_character(n, &i) && !crate::acoes::is_rush(n, &i);
        Ok(())
    }

    /// `play_from_trash` (sem on_play -- igual ao motor de hoje)
    fn joga_do_lixo(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador) -> R<()> {
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
            self.passivas_da_fila(me, opp)?;
            let ops: Vec<Lug> = pool.iter().map(|&j| lug("eu", "trash", j)).collect();
            let k = match self.escolha_entre("do_lixo", &ops, false)? {
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
                    self.passivas_da_fila(me, opp)?;
                    self.sai_do_campo(me)?;
                }
                Self::entra_personagem(me, opp, c, rested)?;
            }
        }
        Ok(())
    }

    /// `play_card` (jogar de graca por efeito): qual carta vem da fila
    /// (`jogar_gratis`), a troca no campo cheio tambem. on_play/main aninhados.
    /// `_put_into_play` + on_play/main da carta que entrou (devolve a carta em jogo)
    fn poe_em_jogo(&mut self, me: &mut Jogador, opp: &mut Jogador, c: Carta, ci: &InfoCarta) -> R<Carta> {
        // _put_into_play
        let lf = self.lugar_fonte.take();
        match ci.card_type.as_str() {
            "CHARACTER" => {
                if me.field_chars.len() >= 5 {
                    self.passivas_da_fila(me, opp)?;
                    self.sai_do_campo(me)?;
                }
                Self::entra_personagem(me, opp, c, false)?;
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
        Ok(nova)
    }

    fn joga_carta(&mut self, st: &Value, me: &mut Jogador, opp: &mut Jogador, fonte: &Carta) -> R<()> {
        if st["source"].as_str() == Some("self") {
            // [Trigger] "jogue esta carta": a propria carta, pelo lugar na mao
            let Some((z, i)) = self.lugar_fonte.clone() else { return Ok(()) };
            if z != "hand" || me.hand.get(i).map(|c| &c.code) != Some(&fonte.code) {
                return Err(ns("play_card self: carta fora do lugar esperado"));
            }
            let ci = dados(fonte)?;
            if ci.card_type == "CHARACTER" && me.field_chars.len() >= 5 {
                self.passivas_da_fila(me, opp)?;
                if !self.veredito("troca_campo")? {
                    return Ok(());
                }
            }
            self.passivas_da_fila(me, opp)?;
            if !self.veredito("joga_self")? {
                return Ok(());
            }
            let c = me.hand.remove(i);
            self.lugar_fonte = None;
            self.poe_em_jogo(me, opp, c, &ci)?;
            return Ok(());
        }
        for k in ["each", "exclude_color_of_selected"] {
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
                    && casa_play_card(st, c, &i, true)?
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
            self.passivas_da_fila(me, opp)?;
            let ops: Vec<Lug> = pool.iter().map(|(z, k)| lug("eu", z, *k)).collect();
            let (z, k) = match self.escolha_entre("jogar_gratis", &ops, false)? {
                Some((l, z, i)) if l == "eu" && pool.contains(&(z.clone(), i)) => (z, i),
                outro => return Err(ns(&format!("jogar_gratis inesperado: {outro:?}"))),
            };
            let ci = dados(if z == "hand" { &me.hand[k] } else { &me.trash[k] })?;
            self.passivas_da_fila(me, opp)?;
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
            let nova = self.poe_em_jogo(me, opp, c, &ci)?;
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

    /// `c is card`: indice da fonte no campo (pelo lugar; senao, pela igualdade de estado)
    fn idx_fonte(&self, me: &Jogador, fonte: &Carta) -> Option<usize> {
        match &self.lugar_fonte {
            Some((z, i)) if z == "field_chars" && me.field_chars.get(*i).map(|c| &c.code) == Some(&fonte.code) => Some(*i),
            Some((z, _)) if z != "field_chars" => None,
            _ => {
                let fv = serde_json::to_value(fonte).ok();
                me.field_chars.iter().position(|c| serde_json::to_value(c).ok() == fv)
            }
        }
    }

    /// Alvo do proprio lado (lider = None)
    fn alvo_meu(&mut self, cands: &[Option<usize>]) -> R<Option<usize>> {
        self.alvo_meu_q("alvo", cands)
    }

    fn alvo_meu_q(&mut self, qual: &str, cands: &[Option<usize>]) -> R<Option<usize>> {
        let ops: Vec<Lug> = cands.iter().map(|c| match c { Some(i) => lug("eu", "field_chars", *i), None => lug("eu", "leader", 0) }).collect();
        let x = match self.escolha_entre(qual, &ops, false)? {
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
        // substituicao de rest (`substitute_rest`) ainda fora do nucleo
        {
            let cartas = std::iter::once(&opp.leader).chain(opp.field_chars.iter()).chain(opp.stage.iter());
            for c in cartas {
                for t in ["passive", "opp_turn", "your_turn"] {
                    if dados(c)?.efeitos.get(t).map_or(false, |b| passos_de(b).any(|s| s["action"].as_str() == Some("substitute_rest"))) {
                        return Err(ns("substituicao de rest no lado do alvo"));
                    }
                }
            }
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
            if c.cannot_be_rested_until.is_empty() && !imune_a_rest(opp, me, i)? && casa_alvo(&st2, c, true, true, me, opp)? {
                cands.push(i);
            }
        }
        let mut feitos = 0;
        for _ in 0..n.min(cands.len()) {
            self.passivas_da_fila(me, opp)?;
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
                let mut ativos: Vec<usize> = (0..opp.field_chars.len()).filter(|&i| !opp.field_chars[i].rested).collect();
                if let Some(Some(a)) = self.atacante_no(opp) {
                    if !ativos.contains(&a) {
                        ativos.push(a);
                    }
                }
                let mut cands = if ativos.is_empty() { (0..opp.field_chars.len()).collect() } else { ativos };
                for _ in 0..n.min(cands.len()) {
                    self.passivas_da_fila(me, opp)?;
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
                if let Some(a) = self.atacante_no(opp) {
                    if !cands.contains(&a) {
                        cands.push(a);
                    }
                }
                if cands.is_empty() {
                    cands = (0..opp.field_chars.len()).map(Some).collect();
                    cands.push(None);
                }
                for _ in 0..n.min(cands.len()) {
                    self.passivas_da_fila(me, opp)?;
                    let ops: Vec<Lug> = cands.iter().map(|c| match c { Some(i) => lug("oponente", "field_chars", *i), None => lug("oponente", "leader", 0) }).collect();
                    let e = match self.escolha_entre("alvo", &ops, false)? {
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
/// `exclui`: a carta-fonte do efeito (`exclude_card=card` em `_pay_costs`;
/// Some(None) = lider), fora so das duas fontes "baratas".
fn devolve_don(me: &mut Jogador, n: i64, exclui: Option<Option<usize>>) -> R<(bool, i64)> {
    let mut dev = 0;
    for (j, c) in me.field_chars.iter_mut().enumerate() {
        if exclui == Some(Some(j)) {
            continue;
        }
        while c.don_attached > 0 && c.rested && dev < n {
            c.don_attached -= 1;
            me.don_deck += 1;
            dev += 1;
        }
    }
    while exclui != Some(None) && me.leader.don_attached > 0 && me.leader.rested && dev < n {
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
    Ok((dev >= n, dev))
}
