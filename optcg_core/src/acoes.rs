//! Jogadas principais SEM efeito de carta (onda 1), espelho de
//! `OPTCGMatch._apply_action_inner` / `_play_card` / `_execute_attack_inner`:
//! anexar DON, jogar carta (personagem/evento/stage) e combate (bloqueio,
//! counter de personagem, dano na vida, KO).
//!
//! Decisoes que o motor Python esconde DENTRO da regra (DON do ataque, qual
//! bloqueador, quais cartas de counter, quem sai do campo cheio) chegam
//! prontas em `Decisoes` -- no nucleo final sao pontos de decisao da busca.
//! O que depende de efeito ainda fora do nucleo devolve `NaoSuportado`.
use crate::cartas::{info, InfoCarta};
use crate::estado::{Carta, Estado, Jogador};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Default, Deserialize)]
pub struct Decisoes {
    pub don_ataque: Option<i64>,
    /// "nenhum" = decidiu nao bloquear; [zona, indice] = bloqueador; ausente = sem registro
    pub bloqueio: Option<Value>,
    #[serde(default)]
    pub counter_cartas: Vec<(String, usize)>,
    pub campo_cheio: Option<(String, usize)>,
}

#[derive(Debug)]
pub enum Resultado {
    Feito { venceu: bool },
    NaoSuportado(String),
}

fn ns(m: &str) -> Resultado {
    Resultado::NaoSuportado(m.to_string())
}

fn dados(c: &Carta) -> Result<InfoCarta, Resultado> {
    info(&c.code).ok_or_else(|| ns(&format!("carta sem dados: {}", c.code)))
}

fn kw_ativa(c: &Carta, i: &InfoCarta, kw: &str, nativa: bool) -> bool {
    nativa || i.don_cond.get(kw).map_or(false, |req| c.don_attached >= *req)
}

fn is_rush(c: &Carta, i: &InfoCarta) -> bool {
    kw_ativa(c, i, "rush", c.has_rush) || c.rush_this_turn
}

fn is_rush_character(c: &Carta, i: &InfoCarta) -> bool {
    kw_ativa(c, i, "rush_character", c.has_rush_character)
}

fn is_double_attack(c: &Carta, i: &InfoCarta) -> bool {
    kw_ativa(c, i, "double_attack", c.has_double_attack) || c.double_attack_this_turn
}

/// `rules_facade.effective_card_power(card, your_turn=True)`
fn poder_ataque(c: &Carta, i: &InfoCarta) -> i64 {
    let base = c.base_power_override.unwrap_or(i.power);
    (base + c.power_buff + c.don_attached * 1000).max(0)
}

/// `rules_facade.effective_card_cost`
fn custo_efetivo(c: &Carta, i: &InfoCarta) -> i64 {
    (i.cost + c.cost_buff + c.cost_buff_permanent).max(0)
}

/// `remove_character_from_field(owner, card, 'trash')`
fn tira_do_campo_para_lixo(dono: &mut Jogador, idx: usize) {
    let mut c = dono.field_chars.remove(idx);
    if c.don_attached > 0 {
        dono.don_rested += c.don_attached;
        c.don_attached = 0;
    }
    dono.trash.push(c);
}

fn lugar(v: &Value) -> Option<(String, usize)> {
    let a = v.as_array()?;
    Some((a.first()?.as_str()?.to_string(), a.get(1)?.as_u64()? as usize))
}

fn anexar_don(e: &mut Estado, acao: &Value) -> Result<Resultado, Resultado> {
    let (z, i) = lugar(&acao["ator"]).ok_or_else(|| ns("attach_don sem ator"))?;
    let falta = acao["alvo_tipo"].as_i64().unwrap_or(0);
    let p = &mut e.ativo;
    let anexar = falta.min(p.don_available);
    if anexar > 0 {
        let carta = match z.as_str() {
            "leader" => &mut p.leader,
            "field_chars" => p.field_chars.get_mut(i).ok_or_else(|| ns("ator fora do campo"))?,
            _ => return Err(ns("attach_don em zona inesperada")),
        };
        carta.don_attached += anexar;
        p.don_available -= anexar;
    }
    Ok(Resultado::Feito { venceu: false })
}

fn jogar(e: &mut Estado, acao: &Value, d: &Decisoes) -> Result<Resultado, Resultado> {
    let (z, i) = lugar(&acao["ator"]).ok_or_else(|| ns("play sem ator"))?;
    if z != "hand" {
        return Err(ns("play fora da mao"));
    }
    let p = &mut e.ativo;
    if !p.pending_play_cost_reductions.is_empty() {
        return Err(ns("reducao de custo pendente (efeito)"));
    }
    if let Some(st) = &p.stage {
        if dados(st)?.reduz_custo_mao {
            return Err(ns("stage reduz custo (efeito)"));
        }
    }
    let carta = p.hand.get(i).ok_or_else(|| ns("carta fora da mao"))?;
    let inf = dados(carta)?;
    if inf.custo_por_efeito {
        return Err(ns("custo muda por efeito da propria carta"));
    }
    let custo = custo_efetivo(carta, &inf);
    let mut carta = p.hand.remove(i);
    p.don_rested += custo;
    p.don_available -= custo;
    match inf.card_type.as_str() {
        "CHARACTER" => {
            if p.field_chars.len() >= 5 {
                let (zs, is) = d.campo_cheio.clone().ok_or_else(|| ns("campo cheio sem decisao"))?;
                if zs != "field_chars" {
                    return Err(ns("campo cheio: lugar inesperado"));
                }
                tira_do_campo_para_lixo(p, is);
            }
            carta.rested = false;
            carta.just_played =
                !(carta.has_rush || carta.rush_this_turn || is_rush_character(&carta, &inf));
            carta.rush_character_only_this_turn =
                is_rush_character(&carta, &inf) && !is_rush(&carta, &inf);
            p.field_chars.push(carta);
        }
        "EVENT" => {
            p.trash.push(carta);
            p.events_activated_costs_this_turn.push(Value::from(inf.cost));
        }
        "STAGE" => {
            if let Some(velho) = p.stage.take() {
                p.trash.push(velho);
            }
            p.stage = Some(carta);
        }
        _ => return Err(ns("tipo de carta inesperado")),
    }
    Ok(Resultado::Feito { venceu: false })
}

fn atacar(e: &mut Estado, acao: &Value, d: &Decisoes) -> Result<Resultado, Resultado> {
    let (za, ia) = lugar(&acao["ator"]).ok_or_else(|| ns("attack sem ator"))?;
    let mut alvo_tipo = acao["alvo_tipo"].as_str().unwrap_or("").to_string();
    let mut alvo_idx: Option<usize> = None;
    if alvo_tipo == "character" {
        let a = acao["alvo"].as_array().ok_or_else(|| ns("attack sem alvo"))?;
        if a.first().and_then(|x| x.as_str()) != Some("oponente")
            || a.get(1).and_then(|x| x.as_str()) != Some("field_chars")
        {
            return Err(ns("alvo inesperado"));
        }
        alvo_idx = Some(a.get(2).and_then(|x| x.as_u64()).ok_or_else(|| ns("alvo sem indice"))? as usize);
    }
    let (p, opp) = (&mut e.ativo, &mut e.oponente);
    {
        let atk = match za.as_str() {
            "leader" => &p.leader,
            "field_chars" => p.field_chars.get(ia).ok_or_else(|| ns("atacante fora do campo"))?,
            _ => return Err(ns("atacante em zona inesperada")),
        };
        if atk.rested {
            return Ok(Resultado::Feito { venceu: false });
        }
    }
    // DON do ataque (decisao escondida na regra no motor Python)
    let don = d.don_ataque.ok_or_else(|| ns("ataque sem registro de DON"))?;
    {
        let atk = if za == "leader" { &mut p.leader } else { &mut p.field_chars[ia] };
        if don > 0 {
            atk.don_attached += don;
            p.don_available -= don;
        }
    }
    if alvo_tipo == "leader" && p.cannot_attack_leader_this_turn {
        return Ok(Resultado::Feito { venceu: false });
    }
    let atk = if za == "leader" { &mut p.leader } else { &mut p.field_chars[ia] };
    atk.rested = true;
    if !atk.attack_paywall.as_object().map_or(true, |m| m.is_empty()) {
        return Err(ns("paywall de ataque (efeito)"));
    }
    let inf_atk = dados(atk)?;
    let mut atk_power = poder_ataque(atk, &inf_atk);
    let dano = if is_double_attack(atk, &inf_atk) { 2 } else { 1 };
    let banish = atk.has_banish;
    let unblockable = atk.has_unblockable || atk.unblockable_this_turn;
    let atk_eh_char = za != "leader";
    // BLOQUEIO
    let blv = d.bloqueio.clone().ok_or_else(|| ns("ataque sem registro de bloqueio"))?;
    opp.blocker_lock_battle = Value::Null;
    let bl = if blv.as_str() == Some("nenhum") { None } else { lugar(&blv) };
    if let Some((zb, ib)) = bl {
        if !unblockable {
            if zb != "field_chars" {
                return Err(ns("bloqueador fora do campo"));
            }
            alvo_tipo = "character".to_string();
            alvo_idx = Some(ib);
            opp.field_chars.get_mut(ib).ok_or_else(|| ns("bloqueador inexistente"))?.rested = true;
        }
    }
    let mut defesa = if alvo_tipo == "leader" {
        let l = &opp.leader;
        dados(l)?.power + l.power_buff
    } else {
        let j = alvo_idx.ok_or_else(|| ns("alvo sem indice"))?;
        let t = opp.field_chars.get(j).ok_or_else(|| ns("alvo fora do campo"))?;
        let v = dados(t)?.power + t.power_buff;
        let atk = if za == "leader" { &mut p.leader } else { &mut p.field_chars[ia] };
        atk.battled_opp_character_this_turn = true;
        v
    };
    // COUNTER de personagens (cartas pelo lugar na mao, antes de sair)
    if !d.counter_cartas.is_empty() {
        let mut idxs: Vec<usize> = Vec::new();
        for (z, i) in &d.counter_cartas {
            if z != "hand" {
                return Err(ns("counter fora da mao"));
            }
            idxs.push(*i);
        }
        let ordem: Vec<Carta> = idxs.iter().map(|&i| opp.hand[i].clone()).collect();
        let mut desc = idxs.clone();
        desc.sort_unstable_by(|a, b| b.cmp(a));
        for i in desc {
            opp.hand.remove(i);
        }
        for c in ordem {
            defesa += dados(&c)?.counter;
            opp.trash.push(c);
        }
    }
    let _ = &mut atk_power;
    if atk_power >= defesa {
        if alvo_tipo == "leader" {
            if opp.life.is_empty() {
                return Ok(Resultado::Feito { venceu: true });
            }
            for _ in 0..dano {
                let Some(mut vida) = opp.life.pop() else { break };
                if dados(&vida)?.has_trigger && !banish {
                    return Err(ns("trigger na vida (efeito)"));
                }
                if banish {
                    opp.trash.push(vida);
                } else if vida.life_face_up && opp.face_up_life_to_deck {
                    vida.life_face_up = false;
                    opp.deck.insert(0, vida);
                } else {
                    opp.hand.push(vida);
                }
            }
        } else {
            let j = alvo_idx.unwrap();
            if j < opp.field_chars.len() {
                tira_do_campo_para_lixo(opp, j);
            }
        }
    }
    let _ = atk_eh_char;
    Ok(Resultado::Feito { venceu: false })
}

pub fn aplica(e: &mut Estado, acao: &Value, d: &Decisoes) -> Resultado {
    let r = match acao["tipo"].as_str().unwrap_or("") {
        "attach_don" => anexar_don(e, acao),
        "play" => jogar(e, acao, d),
        "attack" => atacar(e, acao, d),
        outro => Err(ns(&format!("jogada ainda fora do nucleo: {outro}"))),
    };
    match r {
        Ok(x) | Err(x) => x,
    }
}
