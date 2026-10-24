//! Tabela das cartas (dados IMPRESSOS, imutaveis), carregada uma vez.
//! Espelho de `CardData` do motor Python nos campos que as regras do nucleo usam.
use serde::Deserialize;
use std::collections::HashMap;
use std::sync::RwLock;

#[derive(Clone, Debug, Deserialize)]
pub struct InfoCarta {
    pub cost: i64,
    pub power: i64,
    pub counter: i64,
    pub card_type: String,
    pub has_trigger: bool,
    /// keyword -> DON necessario (ex.: {"rush": 1})
    #[serde(default)]
    pub don_cond: HashMap<String, i64>,
    /// a propria carta muda o custo de jogar da mao (passivo own_play_self) --
    /// efeito ainda fora do nucleo
    #[serde(default)]
    pub custo_por_efeito: bool,
    /// Stage que reduz custo de jogar da mao (buff_cost own_play_hand)
    #[serde(default)]
    pub reduz_custo_mao: bool,
}

static TABELA: RwLock<Option<HashMap<String, InfoCarta>>> = RwLock::new(None);

pub fn carrega(t: HashMap<String, InfoCarta>) {
    let mut g = TABELA.write().unwrap();
    match g.as_mut() {
        Some(m) => m.extend(t),
        None => *g = Some(t),
    }
}

pub fn info(code: &str) -> Option<InfoCarta> {
    TABELA.read().unwrap().as_ref().and_then(|m| m.get(code).cloned())
}
