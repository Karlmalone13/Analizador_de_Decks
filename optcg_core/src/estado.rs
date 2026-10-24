//! Estado da partida (ESPEC.md secao 2). Campos que as regras do nucleo ja
//! manipulam sao TIPADOS; o resto passa intacto em `extras`, para a comparacao
//! com o estado canonico do motor Python ser exata desde a primeira onda.
//! Cada onda de regras/efeitos traz campos de `extras` para dentro.
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Clone, Debug, Serialize, Deserialize)]
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
    /// Revelada ao oponente (bit 0 = revealed_deck, 1 = revealed_life,
    /// 2 = revealed_to_opponent). Marca DA CARTA: viaja com ela entre zonas.
    /// No canonico do Python sao listas de LUGARES (ver `estado_canonico.py`).
    #[serde(skip)]
    pub revelada: u8,
    #[serde(flatten)]
    pub extras: Map<String, Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
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
    pub revealed_deck: Vec<(String, usize)>,
    pub revealed_life: Vec<(String, usize)>,
    pub revealed_to_opponent: Vec<(String, usize)>,
    pub face_up_life_to_deck: bool,
    pub blocker_lock_battle: serde_json::Value,
    #[serde(flatten)]
    pub extras: Map<String, Value>,
}

/// Ordem das zonas igual a `estado_canonico._lugares_de_ids`.
const ZONAS: [&str; 7] = ["leader", "stage", "deck", "hand", "field_chars", "life", "trash"];

impl Jogador {
    fn zona_mut(&mut self, z: &str) -> Vec<&mut Carta> {
        match z {
            "leader" => vec![&mut self.leader],
            "stage" => self.stage.iter_mut().collect(),
            "deck" => self.deck.iter_mut().collect(),
            "hand" => self.hand.iter_mut().collect(),
            "field_chars" => self.field_chars.iter_mut().collect(),
            "life" => self.life.iter_mut().collect(),
            "trash" => self.trash.iter_mut().collect(),
            _ => vec![],
        }
    }

    /// Lugares (do canonico) -> marca nas cartas. Chamar depois de ler.
    pub fn marca_reveladas(&mut self) {
        let listas = [
            (0u8, self.revealed_deck.clone()),
            (1u8, self.revealed_life.clone()),
            (2u8, self.revealed_to_opponent.clone()),
        ];
        for (bit, lugares) in listas {
            for (z, i) in lugares {
                if let Some(c) = self.zona_mut(&z).into_iter().nth(i) {
                    c.revelada |= 1 << bit;
                }
            }
        }
    }

    /// Marca nas cartas -> lugares (na ordem do canonico). Chamar antes de gravar.
    /// Cada marca so vale na zona a que se refere (bit 0 deck, 1 vida, 2 mao):
    /// carta que saiu da zona perde a marca (mesma regra do canonico do Python).
    pub fn recalcula_reveladas(&mut self) {
        const ZONA_DO_BIT: [&str; 3] = ["deck", "life", "hand"];
        let mut out: [Vec<(String, usize)>; 3] = [vec![], vec![], vec![]];
        for z in ZONAS {
            for (i, c) in self.zona_mut(z).into_iter().enumerate() {
                for (bit, lista) in out.iter_mut().enumerate() {
                    if c.revelada & (1 << bit) == 0 {
                        continue;
                    }
                    if ZONA_DO_BIT[bit] == z {
                        lista.push((z.to_string(), i));
                    } else {
                        c.revelada &= !(1 << bit);
                    }
                }
            }
        }
        let [d, l, o] = out;
        self.revealed_deck = d;
        self.revealed_life = l;
        self.revealed_to_opponent = o;
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
        e.ativo.marca_reveladas();
        e.oponente.marca_reveladas();
        Ok(e)
    }

    pub fn para_json(&mut self) -> Result<String, serde_json::Error> {
        self.ativo.recalcula_reveladas();
        self.oponente.recalcula_reveladas();
        serde_json::to_string(self)
    }
}
