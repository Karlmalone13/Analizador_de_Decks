//! Tabela das cartas (dados IMPRESSOS, imutaveis), carregada uma vez.
//! Espelho de `CardData` do motor Python nos campos que as regras do nucleo usam.
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
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
    // --- texto impresso usado por filtros/condicoes de efeito ---
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub sub_types: String,
    #[serde(default)]
    pub color: String,
    #[serde(default)]
    pub card_text: String,
    #[serde(default)]
    pub attribute: String,
    #[serde(default)]
    pub alternate_names: Vec<String>,
    /// blocos de efeito do `card_effects_db` (gatilho -> bloco), na ordem do banco
    #[serde(default)]
    pub efeitos: serde_json::Map<String, serde_json::Value>,
    /// calculado ao carregar: tem passiva/opp_turn que `aplica_passivas_keyword` usa
    #[serde(skip)]
    pub kw_passiva: bool,
}

/// Compartilhada (Arc): consultar uma carta NAO copia os dados (efeitos inclusos).
static TABELA: RwLock<Option<HashMap<String, Arc<InfoCarta>>>> = RwLock::new(None);

pub fn carrega(t: HashMap<String, InfoCarta>) {
    let mut g = TABELA.write().unwrap();
    let t = t.into_iter().map(|(k, mut v)| {
        v.kw_passiva = crate::efeitos::tem_passiva_de_keyword(&v);
        (k, Arc::new(v))
    });
    match g.as_mut() {
        Some(m) => m.extend(t),
        None => *g = Some(t.collect()),
    }
}

pub fn info(code: &str) -> Option<Arc<InfoCarta>> {
    TABELA.read().unwrap().as_ref().and_then(|m| m.get(code).cloned())
}

/// Codigo da carta INTERNADO: um numero (copiar e comparar e de graca); o texto
/// ("OP01-001") fica numa tabela unica e e o que vai e volta no JSON.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct Cod(u32);

struct Internos {
    nomes: Vec<&'static str>,
    ids: HashMap<&'static str, u32>,
}

static INTERNOS: RwLock<Option<Internos>> = RwLock::new(None);

impl Cod {
    pub fn de(s: &str) -> Cod {
        if let Some(t) = INTERNOS.read().unwrap().as_ref() {
            if let Some(&i) = t.ids.get(s) {
                return Cod(i);
            }
        }
        let mut g = INTERNOS.write().unwrap();
        let t = g.get_or_insert_with(|| Internos { nomes: Vec::new(), ids: HashMap::new() });
        if let Some(&i) = t.ids.get(s) {
            return Cod(i);
        }
        let txt: &'static str = Box::leak(s.to_string().into_boxed_str());
        let i = t.nomes.len() as u32;
        t.nomes.push(txt);
        t.ids.insert(txt, i);
        Cod(i)
    }

    pub fn txt(self) -> &'static str {
        INTERNOS.read().unwrap().as_ref().map_or("", |t| t.nomes[self.0 as usize])
    }
}

impl std::ops::Deref for Cod {
    type Target = str;
    fn deref(&self) -> &str {
        self.txt()
    }
}

impl std::fmt::Display for Cod {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.txt())
    }
}

impl Serialize for Cod {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.txt())
    }
}

impl<'de> Deserialize<'de> for Cod {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Cod, D::Error> {
        let s = String::deserialize(d)?;
        Ok(Cod::de(&s))
    }
}
