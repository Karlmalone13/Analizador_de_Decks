//! Rede de VALOR do motor (`value_net.win_prob`) dentro do nucleo: as 32
//! features de `value_net.state_features` (nomes padrao) e as arvores do
//! HistGradientBoostingClassifier exportadas por `value_net.exporta_para_nucleo`.
//! Probabilidade de `p` vencer = sigmoide(base + soma das folhas).
use crate::efeitos::dados;
use crate::estado::{Carta, Jogador};
use serde::Deserialize;
use std::sync::{Arc, RwLock};

#[derive(Deserialize)]
pub struct Modelo {
    pub nomes: Vec<String>,
    pub raiz: Vec<usize>,
    pub feat: Vec<usize>,
    pub thr: Vec<f64>,
    pub mgl: Vec<bool>,
    pub esq: Vec<usize>,
    pub dir: Vec<usize>,
    pub folha: Vec<bool>,
    pub valor: Vec<f64>,
    pub base: f64,
}

static MODELO: RwLock<Option<Arc<Modelo>>> = RwLock::new(None);

pub const NOMES: [&str; 32] = [
    "life_mine", "life_opp", "life_diff", "hand_mine", "hand_opp", "hand_diff", "don_field_mine",
    "don_field_opp", "don_diff", "don_available_mine", "chars_mine", "chars_opp", "chars_diff",
    "power_mine", "power_opp", "power_diff", "cost_mine", "cost_opp", "blockers_mine", "blockers_opp",
    "blockers_diff", "active_mine", "active_opp", "rested_mine", "rested_opp", "counter_hand_mine",
    "counter_hand_opp", "deck_mine", "deck_opp", "trash_mine", "trash_opp", "turn",
];

pub fn carrega(m: Modelo) -> Result<(), String> {
    if m.nomes.iter().map(|s| s.as_str()).ne(NOMES.iter().copied()) {
        return Err("modelo com features diferentes das 32 padrao".into());
    }
    *MODELO.write().unwrap() = Some(Arc::new(m));
    Ok(())
}

pub fn modelo() -> Option<Arc<Modelo>> {
    MODELO.read().unwrap().clone()
}

/// `blockers_active()` (sem a trava de batalha: fora de batalha ela e None)
fn bloqueadores(p: &Jogador) -> f64 {
    p.field_chars.iter().filter(|c| {
        dados(c).map_or(false, |i| crate::acoes::is_blocker(c, &i))
            && !c.rested && c.cannot_be_rested_until.is_empty() && c.cannot_block_until.is_empty()
    }).count() as f64
}

/// `active_chars()`
fn ativos(p: &Jogador) -> f64 {
    p.field_chars.iter().filter(|c| {
        !c.rested && (!c.just_played || c.rush_character_only_this_turn
            || dados(c).map_or(false, |i| crate::acoes::is_rush(c, &i) || crate::acoes::is_rush_character(c, &i)))
    }).count() as f64
}

/// `counter_in_hand()` (com `set_hand_counter_by_power` das passivas do dono)
fn counter_na_mao(p: &Jogador) -> f64 {
    let mut troca: Vec<(i64, i64)> = Vec::new();
    for f in std::iter::once(&p.leader).chain(p.field_chars.iter()) {
        if let Ok(i) = dados(f) {
            if let Some(pas) = i.efeitos.get("passive") {
                for s in pas["steps"].as_array().into_iter().flatten() {
                    if s["action"].as_str() == Some("set_hand_counter_by_power") {
                        troca.push((s["power_eq"].as_i64().unwrap_or(-1), s["to_value"].as_i64().unwrap_or(0)));
                    }
                }
            }
        }
    }
    let mut t = 0i64;
    for c in &p.hand {
        let Ok(i) = dados(c) else { continue };
        let v = troca.iter().find(|(pw, _)| *pw == i.power).map_or(i.counter, |x| x.1);
        if v > 0 {
            t += v;
        }
    }
    t as f64
}

fn soma(cs: &[Carta], f: impl Fn(&crate::cartas::InfoCarta) -> i64) -> f64 {
    cs.iter().map(|c| dados(c).map_or(0, |i| f(&i))).sum::<i64>() as f64
}

/// `state_features(p, opp)` com os 32 nomes padrao, na ordem.
pub fn features(p: &Jogador, o: &Jogador) -> [f64; 32] {
    let (lm, lo) = (p.life.len() as f64, o.life.len() as f64);
    let (hm, ho) = (p.hand.len() as f64, o.hand.len() as f64);
    let (dm, dor) = ((p.don_available + p.don_rested) as f64, (o.don_available + o.don_rested) as f64);
    let (cm, co) = (p.field_chars.len() as f64, o.field_chars.len() as f64);
    let (pm, po) = (soma(&p.field_chars, |i| i.power) / 1000.0, soma(&o.field_chars, |i| i.power) / 1000.0);
    let (bm, bo) = (bloqueadores(p), bloqueadores(o));
    [
        lm, lo, lm - lo, hm, ho, hm - ho, dm, dor, dm - dor, p.don_available as f64,
        cm, co, cm - co, pm, po, pm - po,
        soma(&p.field_chars, |i| i.cost), soma(&o.field_chars, |i| i.cost),
        bm, bo, bm - bo, ativos(p), ativos(o),
        p.field_chars.iter().filter(|c| c.rested).count() as f64,
        o.field_chars.iter().filter(|c| c.rested).count() as f64,
        counter_na_mao(p) / 1000.0, counter_na_mao(o) / 1000.0,
        p.deck.len() as f64, o.deck.len() as f64, p.trash.len() as f64, o.trash.len() as f64,
        p.turn as f64,
    ]
}

/// `win_prob(p, opp)`: None sem modelo carregado.
pub fn prob(p: &Jogador, o: &Jogador) -> Option<f64> {
    let m = modelo()?;
    let x = features(p, o);
    let mut s = m.base;
    for &r in &m.raiz {
        let mut k = r;
        while !m.folha[k] {
            let v = x[m.feat[k]];
            k = if v <= m.thr[k] || (v.is_nan() && m.mgl[k]) { m.esq[k] } else { m.dir[k] };
        }
        s += m.valor[k];
    }
    Some(1.0 / (1.0 + (-s).exp()))
}
