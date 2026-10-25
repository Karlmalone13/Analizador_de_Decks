//! Estado da partida (ESPEC.md secao 2). Campos que as regras do nucleo ja
//! manipulam sao TIPADOS; o resto passa intacto em `extras`, para a comparacao
//! com o estado canonico do motor Python ser exata desde a primeira onda.
//! Cada onda de regras/efeitos traz campos de `extras` para dentro.
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Carta {
    pub code: String,
    pub rested: bool,
    pub just_played: bool,
    pub don_attached: i64,
    pub power_buff: i64,
    pub cost_buff: i64,
    pub frozen_next_refresh: bool,
    pub cannot_attack_until: String,
    pub cannot_be_rested_until: String,
    pub cannot_block_until: String,
    pub effects_negated_until: String,
    pub attack_paywall: Value,
    pub unblockable_this_turn: bool,
    pub rush_this_turn: bool,
    pub double_attack_this_turn: bool,
    pub blocker_this_turn: bool,
    pub banish_this_turn: bool,
    pub extra_attribute_this_turn: String,
    pub can_attack_active_this_turn: bool,
    pub ko_on_opp_blocker_used_this_turn: bool,
    pub immunity_ko_until: String,
    pub battled_opp_character_this_turn: bool,
    pub cannot_attack_opp_chars_cost_lte: i64,
    pub own_effect_negated_this_turn: bool,
    pub cost_buff_permanent: i64,
    pub base_power_override: Option<i64>,
    pub base_power_override_opp_turn: Option<i64>,
    pub has_rush: bool,
    pub has_rush_character: bool,
    pub has_double_attack: bool,
    pub has_banish: bool,
    pub has_unblockable: bool,
    pub has_blocker: bool,
    pub life_face_up: bool,
    pub rush_character_only_this_turn: bool,
    /// `_conhecida` (decision_engine.revela_carta): 1 = o dono viu,
    /// 2 = o oponente do dono viu, 4 = posicao perdida (deck embaralhado).
    /// Marca DA CARTA: viaja com ela entre zonas.
    #[serde(rename = "_conhecida", default, skip_serializing_if = "e_zero")]
    pub conhecida: u8,
    /// dados impressos da carta (cache da tabela, preenchido ao ler o estado)
    #[serde(skip)]
    pub dados: Option<std::sync::Arc<crate::cartas::InfoCarta>>,
    #[serde(flatten)]
    pub extras: Map<String, Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Jogador {
    pub leader: Carta,
    pub stage: Option<Carta>,
    pub deck: Vec<Carta>,
    pub hand: Vec<Carta>,
    pub field_chars: Vec<Carta>,
    pub life: Vec<Carta>,
    pub trash: Vec<Carta>,
    pub don_deck: i64,
    pub don_available: i64,
    pub don_rested: i64,
    pub frozen_don_count: i64,
    pub turn: i64,
    pub global_turn: i64,
    pub is_active_turn: bool,
    pub is_first: bool,
    pub cant_play_from_hand_this_turn: bool,
    pub cant_play_chars_this_turn: bool,
    pub cant_play_cost_gte: i64,
    pub cannot_attack_leader_this_turn: bool,
    pub cant_take_life_this_turn: bool,
    pub events_activated_costs_this_turn: Vec<Value>,
    pub pending_play_cost_reductions: Vec<Value>,
    pub face_up_life_to_deck: bool,
    pub blocker_lock_battle: serde_json::Value,
    #[serde(flatten)]
    pub extras: Map<String, Value>,
}

fn e_zero(x: &u8) -> bool {
    *x == 0
}

pub const CONHECIDA_DONO: u8 = 1;
pub const CONHECIDA_OPONENTE: u8 = 2;
pub const POSICAO_PERDIDA: u8 = 4;

impl Carta {
    /// `revela_carta(c, quem)`
    pub fn revela(&mut self, quem: u8) {
        self.conhecida = (self.conhecida | quem) & !POSICAO_PERDIDA;
    }
}

impl Jogador {
    /// `marca_publicas(gs)`: campo, lixo, lider e stage -> os dois lados conhecem
    pub fn marca_publicas(&mut self) {
        let cartas = self.field_chars.iter_mut().chain(self.trash.iter_mut())
            .chain(std::iter::once(&mut self.leader)).chain(self.stage.iter_mut());
        for c in cartas {
            c.conhecida |= 3;
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Estado {
    pub ativo: Jogador,
    pub oponente: Jogador,
}

impl Estado {
    pub fn de_json(s: &str) -> Result<Estado, serde_json::Error> {
        let mut e: Estado = serde_json::from_str(s)?;
        for p in [&mut e.ativo, &mut e.oponente] {
            let cartas = std::iter::once(&mut p.leader).chain(p.stage.iter_mut()).chain(p.deck.iter_mut())
                .chain(p.hand.iter_mut()).chain(p.field_chars.iter_mut()).chain(p.life.iter_mut()).chain(p.trash.iter_mut());
            for c in cartas {
                c.dados = crate::cartas::info(&c.code);
            }
        }
        Ok(e)
    }

    pub fn para_json(&mut self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }
}
