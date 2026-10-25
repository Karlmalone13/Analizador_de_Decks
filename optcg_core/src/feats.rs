//! FEATURES da rede nova (fase C): estado e jogada como vetores de numeros, do
//! ponto de vista de quem DECIDE, so com o que ele pode ver.
//!
//! Fonte UNICA: o auto-jogo grava, o treino (Python) le, a busca usa -- os tres
//! pelo mesmo codigo. Do oponente entra so o observavel: tamanho da mao, as
//! cartas dela que eu CONHECO (`_conhecida` bit do oponente do dono), tamanho do
//! deck, vida (contagem e as viradas pra cima). Diferente das 32 de
//! `value_net.state_features`, que somam o counter da mao inteira do oponente.
use crate::acoes::{is_blocker, is_rush, Jogada};
use crate::efeitos::dados;
use crate::estado::{Carta, Jogador, CONHECIDA_OPONENTE};

pub const N_SLOTS: usize = 5;
const POR_CARTA: usize = 11;
pub const N_ESTADO: usize = 2 * (4 + N_SLOTS * POR_CARTA) + 2 * 9 + 16 + 3;
pub const N_JOGADA: usize = 5 + 4 + 9 + 4;

fn poder(c: &Carta) -> f32 {
    let base = c.base_power_override.unwrap_or_else(|| dados(c).map_or(0, |i| i.power));
    ((base + c.power_buff + 1000 * c.don_attached).max(0)) as f32 / 1000.0
}

/// Uma carta em campo: presente, poder, custo, DON, restada, blocker, rush,
/// recem-jogada, banish, ataque duplo, imbloqueavel.
fn carta_campo(c: &Carta) -> [f32; POR_CARTA] {
    let Ok(i) = dados(c) else { return [0.0; POR_CARTA] };
    [
        1.0, poder(c), i.cost as f32 / 10.0, c.don_attached as f32, c.rested as u8 as f32,
        is_blocker(c, &i) as u8 as f32, is_rush(c, &i) as u8 as f32, c.just_played as u8 as f32,
        (c.has_banish || c.banish_this_turn) as u8 as f32,
        (c.has_double_attack || c.double_attack_this_turn) as u8 as f32,
        (c.has_unblockable || c.unblockable_this_turn) as u8 as f32,
    ]
}

/// Mesa de um lado: lider (poder, DON, restado, vida) + ate 5 personagens
/// (os de maior poder primeiro, ordem estavel).
fn lado_mesa(p: &Jogador, out: &mut Vec<f32>) {
    out.extend([poder(&p.leader), p.leader.don_attached as f32, p.leader.rested as u8 as f32, p.life.len() as f32]);
    let mut idx: Vec<usize> = (0..p.field_chars.len()).collect();
    idx.sort_by(|&a, &b| poder(&p.field_chars[b]).partial_cmp(&poder(&p.field_chars[a])).unwrap_or(std::cmp::Ordering::Equal));
    for k in 0..N_SLOTS {
        match idx.get(k) {
            Some(&j) => out.extend(carta_campo(&p.field_chars[j])),
            None => out.extend([0.0; POR_CARTA]),
        }
    }
}

/// Recursos de um lado: DON ativo, DON restado, DON no deck de DON, mao, deck,
/// lixo, vida virada pra cima, stage, eventos no lixo.
fn lado_recursos(p: &Jogador, out: &mut Vec<f32>) {
    let eventos = p.trash.iter().filter(|c| dados(c).map_or(false, |i| i.card_type == "EVENT")).count();
    out.extend([
        p.don_available as f32, p.don_rested as f32, p.don_deck as f32, p.hand.len() as f32,
        p.deck.len() as f32 / 10.0, p.trash.len() as f32 / 10.0,
        p.life.iter().filter(|c| c.life_face_up).count() as f32, p.stage.is_some() as u8 as f32,
        eventos as f32,
    ]);
}

/// Mao que `quem_ve` enxerga de `p`: na minha mao, tudo; na do oponente, so as
/// cartas que eu conheco. Custos 0..9 (contagem), counter total, personagens,
/// eventos, blockers, cartas jogaveis com o DON ativo, cartas conhecidas.
fn mao(p: &Jogador, minha: bool, out: &mut Vec<f32>) {
    let mut v = [0.0f32; 16];
    for c in &p.hand {
        if !minha && c.conhecida & CONHECIDA_OPONENTE == 0 {
            continue;
        }
        let Ok(i) = dados(c) else { continue };
        v[(i.cost.clamp(0, 9)) as usize] += 1.0;
        v[10] += i.counter as f32 / 1000.0;
        match i.card_type.as_str() {
            "CHARACTER" => v[11] += 1.0,
            "EVENT" => v[12] += 1.0,
            _ => {}
        }
        if is_blocker(c, &i) {
            v[13] += 1.0;
        }
        if i.cost <= p.don_available {
            v[14] += 1.0;
        }
        v[15] += 1.0;
    }
    out.extend(v);
}

/// Estado do ponto de vista de `eu` (quem decide).
pub fn estado(eu: &Jogador, ele: &Jogador) -> Vec<f32> {
    let mut v = Vec::with_capacity(N_ESTADO);
    lado_mesa(eu, &mut v);
    lado_mesa(ele, &mut v);
    lado_recursos(eu, &mut v);
    lado_recursos(ele, &mut v);
    mao(eu, true, &mut v);
    v.extend([eu.turn as f32, eu.is_first as u8 as f32, ele.hand.len() as f32]);
    debug_assert_eq!(v.len(), N_ESTADO);
    v
}

fn ator<'a>(eu: &'a Jogador, z: &str, i: usize) -> Option<&'a Carta> {
    match z {
        "hand" => eu.hand.get(i),
        "leader" => Some(&eu.leader),
        "stage" => eu.stage.as_ref(),
        _ => eu.field_chars.get(i),
    }
}

/// Jogada: tipo (5), zona do ator (4), a carta do ator (poder, custo, counter,
/// personagem, evento, stage, blocker, rush, DON nela) e o alvo do ataque
/// (lider?, poder, custo, restado).
pub fn jogada(eu: &Jogador, ele: &Jogador, j: &Jogada) -> Vec<f32> {
    let mut v = vec![0.0f32; N_JOGADA];
    let (t, a): (usize, Option<(&str, usize)>) = match j {
        Jogada::Jogar(i) => (0, Some(("hand", *i))),
        Jogada::Ativar(l) => (1, Some(*l)),
        Jogada::DarDon(l, _) => (2, Some(*l)),
        Jogada::Atacar(l, _) => (3, Some(*l)),
        Jogada::Fim => (4, None),
    };
    v[t] = 1.0;
    if let Some((z, i)) = a {
        v[5 + match z { "hand" => 0, "leader" => 1, "field_chars" => 2, _ => 3 }] = 1.0;
        if let Some(c) = ator(eu, z, i) {
            if let Ok(inf) = dados(c) {
                v[9] = poder(c);
                v[10] = inf.cost as f32 / 10.0;
                v[11] = inf.counter as f32 / 1000.0;
                v[12] = (inf.card_type == "CHARACTER") as u8 as f32;
                v[13] = (inf.card_type == "EVENT") as u8 as f32;
                v[14] = (inf.card_type == "STAGE") as u8 as f32;
                v[15] = is_blocker(c, &inf) as u8 as f32;
                v[16] = is_rush(c, &inf) as u8 as f32;
                v[17] = c.don_attached as f32;
            }
        }
    }
    if let Jogada::Atacar(_, alvo) = j {
        match alvo {
            None => {
                v[18] = 1.0;
                v[19] = poder(&ele.leader);
            }
            Some(k) => {
                if let Some(c) = ele.field_chars.get(*k) {
                    v[19] = poder(c);
                    v[20] = dados(c).map_or(0.0, |i| i.cost as f32 / 10.0);
                    v[21] = c.rested as u8 as f32;
                }
            }
        }
    }
    v
}
