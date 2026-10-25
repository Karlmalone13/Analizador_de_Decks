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
use crate::efeitos::{aplica_passivas_keyword, custo_de_jogar, lado_tem_acao, regra_de_custo_casa, tem_reativo, Executor};
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
    /// decisoes DENTRO dos efeitos (escolha_efeito / paga_custo), na ordem
    #[serde(default)]
    pub efeito: Vec<Value>,
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

pub fn is_rush(c: &Carta, i: &InfoCarta) -> bool {
    kw_ativa(c, i, "rush", c.has_rush) || c.rush_this_turn
}

pub fn is_rush_character(c: &Carta, i: &InfoCarta) -> bool {
    kw_ativa(c, i, "rush_character", c.has_rush_character)
}

pub fn is_blocker(c: &Carta, i: &InfoCarta) -> bool {
    kw_ativa(c, i, "blocker", c.has_blocker) || c.blocker_this_turn
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
pub fn tira_do_campo_para_lixo(dono: &mut Jogador, idx: usize) {
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
    // reativos de "jogou personagem"/"ativou evento" e passivas de keyword ainda
    // fora do nucleo: o teste so manda jogadas cujos passos estao na onda
    let (z, i) = lugar(&acao["ator"]).ok_or_else(|| ns("play sem ator"))?;
    if z != "hand" {
        return Err(ns("play fora da mao"));
    }
    let p = &mut e.ativo;
    let carta = p.hand.get(i).ok_or_else(|| ns("carta fora da mao"))?;
    let inf = dados(carta)?;
    let custo = custo_de_jogar(p, &e.oponente, carta)?;
    // consume_play_cost_reductions: so as regras que casam com ESTA carta
    let mut resto = Vec::new();
    for r in std::mem::take(&mut p.pending_play_cost_reductions) {
        if !regra_de_custo_casa(carta, &r)? {
            resto.push(r);
        }
    }
    p.pending_play_cost_reductions = resto;
    let mut carta = p.hand.remove(i);
    let mut fonte = carta.clone();
    let mut fila_resto: Option<std::collections::VecDeque<Value>> = None;
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
            p.field_chars.push(carta);
            aplica_passivas_keyword(p, &e.oponente)?;
            let carta = p.field_chars.last_mut().unwrap();
            carta.just_played =
                !(carta.has_rush || carta.rush_this_turn || is_rush_character(carta, &inf));
            carta.rush_character_only_this_turn =
                is_rush_character(carta, &inf) && !is_rush(carta, &inf);
            fonte = p.field_chars.last().unwrap().clone();
            let mut ex = Executor::novo(d.efeito.iter().cloned().collect());
            ex.dispara_jogou_personagem(&mut e.ativo, &mut e.oponente, &fonte, false)?;
            fila_resto = Some(ex.fila);
        }
        "EVENT" => {
            p.trash.push(carta);
            p.events_activated_costs_this_turn.push(Value::from(inf.cost));
            Executor::novo(Default::default()).confere_evento_ativado(&e.ativo, &e.oponente)?;
        }
        "STAGE" => {
            if let Some(velho) = p.stage.take() {
                p.trash.push(velho);
            }
            p.stage = Some(carta);
        }
        _ => return Err(ns("tipo de carta inesperado")),
    }
    // efeito ao jogar: on_play e depois main (os dois disparam)
    let mut ex = Executor::novo(fila_resto.unwrap_or_else(|| d.efeito.iter().cloned().collect()));
    let (p, opp) = (&mut e.ativo, &mut e.oponente);
    if inf.card_type == "CHARACTER" {
        ex.lugar_fonte = Some(("field_chars".to_string(), p.field_chars.len() - 1));
    }
    ex.executa(p, opp, &fonte, "on_play")?;
    ex.executa(p, opp, &fonte, "main")?;
    if !ex.fila.is_empty() {
        return Err(ns("sobrou decisao de efeito na fila"));
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
    let atk_code = if za == "leader" { p.leader.code.clone() } else { p.field_chars[ia].code.clone() };
    let mut alvo_code = match alvo_idx {
        Some(j) => Some(opp.field_chars.get(j).ok_or_else(|| ns("alvo fora do campo"))?.code.clone()),
        None => None,
    };
    // efeito que tira atacante/alvo do lugar no meio do ataque: o Python segue
    // com o objeto velho; o nucleo nao modela isso
    let confere = |e: &Estado, alvo_idx: Option<usize>, alvo_code: &Option<String>| -> Result<(), Resultado> {
        if za != "leader" && e.ativo.field_chars.get(ia).map(|c| &c.code) != Some(&atk_code) {
            return Err(ns("atacante saiu do lugar durante o ataque"));
        }
        if let (Some(j), Some(c)) = (alvo_idx, alvo_code) {
            if e.oponente.field_chars.get(j).map(|x| &x.code) != Some(c) {
                return Err(ns("alvo saiu do lugar durante o ataque"));
            }
        }
        Ok(())
    };
    let atk = if za == "leader" { &mut p.leader } else { &mut p.field_chars[ia] };
    atk.rested = true;
    if !atk.attack_paywall.as_object().map_or(true, |m| m.is_empty()) {
        return Err(ns("paywall de ataque (efeito)"));
    }
    // GATILHOS do ataque, na ordem do Python. Efeito que tira o atacante/alvo do
    // lugar ainda nao existe nesta onda (os indices continuam validos).
    let mut ex = Executor::novo(d.efeito.iter().cloned().collect());
    ex.inst = 1; // `ee` do ataque (lado do atacante)
    let atk_clone = |e: &Estado| if za == "leader" { e.ativo.leader.clone() } else { e.ativo.field_chars[ia].clone() };
    ex.lugar_fonte = Some((za.clone(), ia));
    let f = atk_clone(e);
    ex.executa(&mut e.ativo, &mut e.oponente, &f, "when_rested")?;
    confere(e, alvo_idx, &alvo_code)?;
    let f = atk_clone(e);
    ex.executa(&mut e.ativo, &mut e.oponente, &f, "when_attacking")?;
    confere(e, alvo_idx, &alvo_code)?;
    let lugares = |j: &Jogador| -> Vec<(Carta, (String, usize))> {
        std::iter::once((j.leader.clone(), ("leader".to_string(), 0)))
            .chain(j.field_chars.iter().cloned().enumerate().map(|(i, c)| (c, ("field_chars".to_string(), i))))
            .collect()
    };
    if za == "leader" {
        for (f, l) in lugares(&e.ativo) {
            ex.lugar_fonte = Some(l);
            ex.executa(&mut e.ativo, &mut e.oponente, &f, "leader_battle_reactive")?;
        }
    }
    ex.inst = 2; // `ee_react` (lado do defensor)
    for (f, l) in lugares(&e.oponente) {
        ex.lugar_fonte = Some(l);
        ex.executa(&mut e.oponente, &mut e.ativo, &f, "on_opp_attack")?;
    }
    if alvo_tipo == "leader" {
        for (f, l) in lugares(&e.oponente) {
            ex.lugar_fonte = Some(l);
            ex.executa(&mut e.oponente, &mut e.ativo, &f, "leader_battle_reactive")?;
        }
    }
    confere(e, alvo_idx, &alvo_code)?;
    let (p, opp) = (&mut e.ativo, &mut e.oponente);
    let atk = if za == "leader" { &mut p.leader } else { p.field_chars.get_mut(ia).ok_or_else(|| ns("atacante saiu"))? };
    let inf_atk = dados(atk)?;
    let mut atk_power = poder_ataque(atk, &inf_atk);
    let dano = if is_double_attack(atk, &inf_atk) { 2 } else { 1 };
    let atk_eh_char = za != "leader";
    // BLOQUEIO: `DecisionEngine(opp, p)` liga as passivas de keyword dos dois lados
    aplica_passivas_keyword(opp, p)?;
    aplica_passivas_keyword(p, opp)?;
    let atk = if za == "leader" { &p.leader } else { &p.field_chars[ia] };
    let banish = atk.has_banish;
    let unblockable = atk.has_unblockable || atk.unblockable_this_turn;
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
            let fb = opp.field_chars[ib].clone();
            ex.inst = 3; // `ee_block`
            ex.lugar_fonte = Some(("field_chars".to_string(), ib));
            ex.executa(opp, p, &fb, "on_block")?;
            alvo_code = Some(fb.code.clone());
            if opp.field_chars.get(ib).map(|c| &c.code) != alvo_code.as_ref()
                || (za != "leader" && p.field_chars.get(ia).map(|c| &c.code) != Some(&atk_code))
            {
                return Err(ns("carta saiu do lugar no on_block"));
            }
            for c in std::iter::once(&p.leader).chain(p.field_chars.iter()) {
                if dados(c)?.efeitos.get("passive").and_then(|b| b["steps"].as_array()).map_or(false, |a| {
                    a.iter().any(|s| matches!(s["action"].as_str(), Some("win_game_on_opp_blocker") | Some("ko_on_opp_blocker")))
                }) {
                    return Err(ns("passiva contra blocker"));
                }
            }
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
    // EVENTO [Counter] de poder (`ee_react`), so se o golpe ainda passa
    if atk_power >= defesa {
        ex.inst = 2;
        defesa += ex.counter_evento_poder(opp, p, alvo_idx.filter(|_| alvo_tipo != "leader"), &alvo_tipo,
                                          atk_power - defesa + 1)?;
    }
    // EVENTO [Counter] que enfraquece o atacante, se o de poder nao bastou
    if atk_power >= defesa {
        let a = if za == "leader" { None } else { Some(ia) };
        atk_power -= ex.counter_evento_debuff(opp, p, a, atk_power - defesa + 1)?;
    }
    if (za != "leader" && p.field_chars.get(ia).map(|c| &c.code) != Some(&atk_code))
        || alvo_idx.map_or(false, |j| opp.field_chars.get(j).map(|c| &c.code) != alvo_code.as_ref())
    {
        return Err(ns("carta saiu do lugar no counter"));
    }
    if atk_power >= defesa && atk_eh_char && Executor::tem_counter_evento_ko(opp)? {
        return Err(ns("counter evento de KO no atacante"));
    }
    let _ = &mut atk_power;
    if atk_power >= defesa {
        if alvo_tipo == "leader" {
            if opp.life.is_empty() {
                return Ok(Resultado::Feito { venceu: true });
            }
            let mut tiradas = 0;
            for _ in 0..dano {
                let Some(mut vida) = opp.life.pop() else { break };
                tiradas += 1;
                let gatilho = dados(&vida)?.has_trigger && !banish;
                if banish {
                    opp.trash.push(vida.clone());
                } else if vida.life_face_up && opp.face_up_life_to_deck {
                    vida.life_face_up = false;
                    opp.deck.insert(0, vida.clone());
                } else {
                    opp.hand.push(vida.clone());
                }
                let na_mao = if !banish && opp.hand.last().map(|c| &c.code) == Some(&vida.code) { Some(opp.hand.len() - 1) } else { None };
                ex.dispara_dano_ou_ko(opp, p, None)?;
                if gatilho {
                    // [Trigger]: o defensor executa, fora do proprio turno
                    ex.inst = 10 + tiradas; // `ee_opp` novo a cada vida
                    ex.lugar_fonte = na_mao.map(|i| ("hand".to_string(), i));
                    ex.executa(opp, p, &vida, "trigger")?;
                    if (za != "leader" && p.field_chars.get(ia).map(|c| &c.code) != Some(&atk_code))
                        || alvo_idx.map_or(false, |j| opp.field_chars.get(j).map(|c| &c.code) != alvo_code.as_ref())
                    {
                        return Err(ns("carta saiu do lugar no trigger"));
                    }
                }
            }
            if tiradas > 0 {
                let a = if za == "leader" { &p.leader } else { &p.field_chars[ia] };
                if dados(a)?.efeitos.contains_key("on_damage_to_life") {
                    return Err(ns("on_damage_to_life"));
                }
            }
        } else {
            let j = alvo_idx.unwrap();
            if j < opp.field_chars.len() {
                let t = &opp.field_chars[j];
                let atacante = if za == "leader" { p.leader.clone() } else { p.field_chars[ia].clone() };
                if crate::efeitos::imune_ko_em_batalha(opp, p, j, &atacante)? {
                    let _ = atk_eh_char;
                    if !ex.fila.is_empty() {
                        return Err(ns("sobrou decisao de efeito na fila"));
                    }
                    return Ok(Resultado::Feito { venceu: false });
                }
                ex.inst = 20; // `ee_opp` do KO de batalha
                ex.lugar_fonte = None;
                if ex.substitui_ko(opp, p, j)? {
                    if !ex.fila.is_empty() {
                        return Err(ns("sobrou decisao de efeito na fila"));
                    }
                    return Ok(Resultado::Feito { venceu: false });
                }
                let t = &opp.field_chars[j];
                if tem_reativo(opp, &["on_own_effect_removes_char"])? || tem_reativo(p, &["on_own_effect_removes_char"])? {
                    return Err(ns("reativo de remocao por efeito"));
                }
                let alvo = t.clone();
                tira_do_campo_para_lixo(opp, j);
                let alvo = opp.trash.last().cloned().unwrap_or(alvo);
                ex.inst = 20; // `ee_opp` do KO de batalha
                ex.lugar_fonte = None;
                ex.executa(opp, p, &alvo, "on_ko")?;
                ex.dispara_dano_ou_ko(opp, p, Some(&alvo))?;
                ex.dispara_ko(opp, p, &alvo)?;
            }
        }
    }
    let _ = atk_eh_char;
    if !ex.fila.is_empty() {
        return Err(ns("sobrou decisao de efeito na fila"));
    }
    Ok(Resultado::Feito { venceu: false })
}

/// `[Activate: Main]` (kind 'activate'): marca `_am_used_turn` e executa o bloco
/// pelo executor da Main.
fn ativar(e: &mut Estado, acao: &Value, d: &Decisoes) -> Result<Resultado, Resultado> {
    let (z, i) = lugar(&acao["ator"]).ok_or_else(|| ns("activate sem ator"))?;
    let turno = e.ativo.turn;
    let src = match z.as_str() {
        "leader" => &mut e.ativo.leader,
        "stage" => e.ativo.stage.as_mut().ok_or_else(|| ns("sem stage"))?,
        "field_chars" => e.ativo.field_chars.get_mut(i).ok_or_else(|| ns("ator fora do campo"))?,
        _ => return Err(ns("activate em zona inesperada")),
    };
    src.extras.insert("_am_used_turn".into(), Value::from(turno));
    let fonte = src.clone();
    let mut ex = Executor::novo(d.efeito.iter().cloned().collect());
    if z != "stage" {
        ex.lugar_fonte = Some((z.clone(), i));
    }
    ex.executa(&mut e.ativo, &mut e.oponente, &fonte, "activate_main")?;
    if !ex.fila.is_empty() {
        return Err(ns("sobrou decisao de efeito na fila"));
    }
    Ok(Resultado::Feito { venceu: false })
}

pub fn aplica(e: &mut Estado, acao: &Value, d: &Decisoes) -> Resultado {
    let r = match acao["tipo"].as_str().unwrap_or("") {
        "attach_don" => anexar_don(e, acao),
        "play" => jogar(e, acao, d),
        "attack" => atacar(e, acao, d),
        "activate" => ativar(e, acao, d),
        outro => Err(ns(&format!("jogada ainda fora do nucleo: {outro}"))),
    };
    match r {
        Ok(x) | Err(x) => x,
    }
}
