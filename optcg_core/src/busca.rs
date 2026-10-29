//! BUSCA (PLANO_MOTOR_FORTE, fase B): ISMCTS de um observador sobre as jogadas
//! do MEU turno, no simulador do nucleo.
//!
//! - Cada iteracao sorteia um MUNDO so do que eu conheco (`determiniza`): a mao,
//!   o deck e a vida do oponente que eu nao vi sao redistribuidos entre si; o meu
//!   deck e a minha vida que eu nao vi, idem. Carta conhecida fica onde esta.
//! - A arvore desce pelas jogadas legais NAQUELE mundo (UCB com contagem de
//!   disponibilidade, o padrao do ISMCTS); a primeira jogada nao tentada expande.
//! - Depois do meu turno, o resto e simulado por `turnos_rollout` turnos com uma
//!   politica simples; partida acabada vale 1/0, senao uma nota pela mesa.
//! Fase C troca a politica do rollout e a nota pela rede (prioridade e valor).
use crate::acoes::{Decisoes, Jogada};
use crate::efeitos::{Politica, PoliticaRef};
use crate::estado::{Carta, Estado, Jogador, CONHECIDA_DONO, CONHECIDA_OPONENTE, POSICAO_PERDIDA};
use crate::jogo::{abre_turno, fecha_turno, joga, joga_ate_o_fim, simula, Passo, Rng};
use crate::legais::jogadas_legais;
use std::cell::RefCell;
use std::rc::Rc;

#[derive(Clone, Copy)]
pub struct Config {
    pub iteracoes: u32,
    pub turnos_rollout: u32,
    pub c_ucb: f64,
    pub semente: u64,
    /// espaco da rede de politica+valor (0 = sem rede: rede de valor antiga / nota simples)
    pub rede: u8,
    /// opcao B: bloqueio/counter do defensor escolhidos pela rede de valor (senao: aleatorio)
    pub defesa_rede: bool,
}

pub struct Resposta {
    pub jogada: Jogada,
    /// (jogada da raiz, visitas, valor medio para mim)
    pub raiz: Vec<(Jogada, u32, f64)>,
    pub iteracoes: u32,
    /// simulacoes que pararam num caso fora do nucleo (avaliadas pela nota)
    pub fora_do_nucleo: u32,
    pub motivos: std::collections::BTreeMap<String, u32>,
}

thread_local! { static MOTIVOS: RefCell<std::collections::BTreeMap<String, u32>> = RefCell::new(Default::default()); }
fn anota(m: &str) {
    MOTIVOS.with(|x| *x.borrow_mut().entry(m.chars().take(70).collect()).or_default() += 1);
}

/// Rollout: joga quase sempre que pode (encerra o turno com 10% quando ha outra
/// opcao); as escolhas internas sao aleatorias.
struct Rollout(Rng);

impl Politica for Rollout {
    fn escolhe(&mut self, qual: &str, n: usize, pode_nenhuma: bool) -> Option<usize> {
        if qual == "jogada" {
            // `Jogada::Fim` e sempre a ultima da lista de legais
            if n <= 1 || self.0.ate(10) == 0 {
                return Some(n.saturating_sub(1));
            }
            return Some(self.0.ate(n - 1));
        }
        let tot = n + pode_nenhuma as usize;
        if tot == 0 {
            return None;
        }
        let k = self.0.ate(tot);
        if k < n { Some(k) } else { None }
    }
    fn veredito(&mut self, _qual: &str) -> bool {
        self.0.ate(2) == 0
    }
}

fn embaralha<T>(v: &mut [T], rng: &mut Rng) {
    for i in (1..v.len()).rev() {
        v.swap(i, rng.ate(i + 1));
    }
}

/// Redistribui entre si as cartas das posicoes que `quem` NAO conhece.
fn redistribui(p: &mut Jogador, quem: u8, com_mao: bool, rng: &mut Rng) {
    let desconhecida = |c: &Carta, no_deck: bool| c.conhecida & quem == 0 || (no_deck && c.conhecida & POSICAO_PERDIDA != 0);
    let mut cartas: Vec<Carta> = Vec::new();
    let mut lugares: Vec<(u8, usize)> = Vec::new();
    if com_mao {
        for (i, c) in p.hand.iter().enumerate() {
            if desconhecida(c, false) {
                lugares.push((0, i));
                cartas.push(c.clone());
            }
        }
    }
    for (i, c) in p.deck.iter().enumerate() {
        if desconhecida(c, true) {
            lugares.push((1, i));
            cartas.push(c.clone());
        }
    }
    for (i, c) in p.life.iter().enumerate() {
        if desconhecida(c, false) {
            lugares.push((2, i));
            cartas.push(c.clone());
        }
    }
    embaralha(&mut cartas, rng);
    for ((z, i), c) in lugares.into_iter().zip(cartas) {
        let slot = match z {
            0 => &mut p.hand[i],
            1 => &mut p.deck[i],
            _ => &mut p.life[i],
        };
        // a carta que vai para o lugar herda a face (vida virada) do lugar
        let face = slot.life_face_up;
        *slot = c;
        slot.life_face_up = face && z == 2;
    }
}

/// Um mundo possivel, do ponto de vista do jogador ATIVO de `e`.
pub fn determiniza(e: &Estado, rng: &mut Rng) -> Estado {
    let mut w = e.clone();
    redistribui(&mut w.oponente, CONHECIDA_OPONENTE, true, rng);
    redistribui(&mut w.ativo, CONHECIDA_DONO, false, rng);
    w
}

/// Nota de 0 a 1 para `eu` numa mesa sem vencedor: a rede de valor do motor
/// (`win_prob`) quando carregada; senao vida/mesa/mao.
fn nota(eu: &Jogador, ele: &Jogador) -> f64 {
    if let Some(r) = crate::rede::rede(REDE_ATUAL.with(|x| x.get())) {
        return r.valor(eu, ele);
    }
    if let Some(v) = crate::valor::prob(eu, ele) {
        return v;
    }
    let v = 0.5 + 0.08 * (eu.life.len() as f64 - ele.life.len() as f64)
        + 0.02 * (eu.field_chars.len() as f64 - ele.field_chars.len() as f64)
        + 0.01 * (eu.hand.len() as f64 - ele.hand.len() as f64);
    v.clamp(0.05, 0.95)
}

struct No {
    filhos: Vec<(Jogada, usize)>,
    visitas: u32,
    disponivel: u32,
    soma: f64,
}

impl No {
    fn novo() -> No {
        No { filhos: Vec::new(), visitas: 0, disponivel: 0, soma: 0.0 }
    }
}

/// Valor para MIM depois que o meu turno acabou em `w` (ativo ainda sou eu).
fn depois_do_meu_turno(mut w: Estado, gt: i64, pol: &PoliticaRef, turnos: u32, fora: &mut u32) -> f64 {
    match fecha_turno(&mut w, pol) {
        Passo::Venceu => return 1.0,
        Passo::Perdeu => return 0.0,
        Passo::ForaDoNucleo(m) => {
            *fora += 1;
            anota(&m);
            return nota(&w.ativo, &w.oponente);
        }
        Passo::Segue => {}
    }
    std::mem::swap(&mut w.ativo, &mut w.oponente);
    if turnos == 0 {
        // avalia no COMECO do turno do oponente (depois da compra e do DON dele): e o
        // tipo de estado em que as redes foram treinadas (estado de decisao). Valor
        // do ponto de vista dele -> 1 - valor.
        return match abre_turno(&mut w, gt, pol) {
            Passo::ForaDoNucleo(m) => {
                *fora += 1;
                anota(&m);
                nota(&w.oponente, &w.ativo)
            }
            _ => 1.0 - nota(&w.ativo, &w.oponente),
        };
    }
    let fim = simula(w.clone(), gt, pol.clone(), turnos);
    if let Some(m) = &fim.nao_suportado {
        *fora += 1;
        anota(m);
    }
    match fim.vencedor {
        Some(0) => 0.0, // o oponente comecou ativo na simulacao
        Some(_) => 1.0,
        None => nota(&w.oponente, &w.ativo),
    }
}

thread_local! { static REDE_ATUAL: std::cell::Cell<u8> = const { std::cell::Cell::new(0) }; }

/// Melhor jogada do ativo de `e` (ja no meio da Main dele). `gt` = global_turn atual.
pub fn busca(e: &Estado, gt: i64, cfg: &Config) -> Resposta {
    busca_sem(e, gt, cfg, &[])
}

/// `busca`, sem considerar na raiz as jogadas `proibidas`.
pub fn busca_sem(e: &Estado, gt: i64, cfg: &Config, proibidas: &[Jogada]) -> Resposta {
    REDE_ATUAL.with(|x| x.set(cfg.rede));
    let mut rng = Rng::novo(cfg.semente);
    let pol: PoliticaRef = Rc::new(RefCell::new(Rollout(Rng::novo(cfg.semente ^ 0x5DEE_CE66))));
    let d = Decisoes { politica: Some(pol.clone()), rede: if cfg.defesa_rede { cfg.rede } else { 0 }, ..Default::default() };
    let mut nos: Vec<No> = vec![No::novo()];
    let mut fora = 0u32;
    for _ in 0..cfg.iteracoes {
        let mut w = determiniza(e, &mut rng);
        let mut caminho: Vec<usize> = vec![0];
        let mut no = 0usize;
        let valor: f64 = loop {
            let leg = match jogadas_legais(&w) {
                Ok(v) if no == 0 => v.into_iter().filter(|j| !proibidas.contains(j)).collect(),
                Ok(v) => v,
                Err(_) => {
                    fora += 1;
                    break nota(&w.ativo, &w.oponente);
                }
            };
            // disponibilidade: cada filho que existe e e legal neste mundo
            let mut nao_tentadas: Vec<&Jogada> = Vec::new();
            for j in &leg {
                match nos[no].filhos.iter().find(|(f, _)| f == j) {
                    Some(&(_, k)) => nos[k].disponivel += 1,
                    None => nao_tentadas.push(j),
                }
            }
            // c negativo = so o valor da rede, sem a politica (exploracao UCB com |c|)
            let (j, novo) = if let Some(r) = crate::rede::rede(cfg.rede).filter(|_| cfg.c_ucb > 0.0) {
                // PUCT (AlphaZero): Q + c * P * sqrt(N) / (1 + n); nao tentada com Q do pai
                let (pri, _) = r.politica(&w.ativo, &w.oponente, &leg);
                let pai = &nos[no];
                let q_pai = if pai.visitas > 0 { pai.soma / pai.visitas as f64 } else { 0.5 };
                let raiz_n = (pai.visitas.max(1) as f64).sqrt();
                let mut melhor = (f64::MIN, 0usize);
                for (k, j) in leg.iter().enumerate() {
                    let (q, n) = match pai.filhos.iter().find(|(f, _)| f == j) {
                        Some(&(_, c)) => (nos[c].soma / nos[c].visitas.max(1) as f64, nos[c].visitas),
                        None => (q_pai, 0),
                    };
                    let s = q + cfg.c_ucb * pri[k] * raiz_n / (1.0 + n as f64);
                    if s > melhor.0 {
                        melhor = (s, k);
                    }
                }
                let j = leg[melhor.1].clone();
                let novo = !nos[no].filhos.iter().any(|(f, _)| *f == j);
                (j, novo)
            } else if !nao_tentadas.is_empty() {
                (nao_tentadas[rng.ate(nao_tentadas.len())].clone(), true)
            } else {
                let mut melhor = (f64::MIN, 0usize);
                for (f, k) in &nos[no].filhos {
                    if !leg.contains(f) {
                        continue;
                    }
                    let n = &nos[*k];
                    let ucb = n.soma / n.visitas.max(1) as f64
                        + cfg.c_ucb.abs() * ((n.disponivel.max(1) as f64).ln() / n.visitas.max(1) as f64).sqrt();
                    if ucb > melhor.0 {
                        melhor = (ucb, *k);
                    }
                }
                let j = nos[no].filhos.iter().find(|(_, k)| *k == melhor.1).unwrap().0.clone();
                (j, false)
            };
            let filho = if novo {
                nos.push(No::novo());
                let k = nos.len() - 1;
                nos[k].disponivel = 1;
                nos[no].filhos.push((j.clone(), k));
                k
            } else {
                nos[no].filhos.iter().find(|(f, _)| *f == j).unwrap().1
            };
            caminho.push(filho);
            no = filho;
            if j == Jogada::Fim {
                break depois_do_meu_turno(w, gt, &pol, cfg.turnos_rollout, &mut fora);
            }
            match joga(&mut w, &j, &d) {
                Passo::Venceu => break 1.0,
                Passo::Perdeu => break 0.0,
                Passo::ForaDoNucleo(m) => {
                    fora += 1;
                    anota(&m);
                    break nota(&w.ativo, &w.oponente);
                }
                Passo::Segue => {}
            }
            if novo {
                // expandiu: o resto do meu turno pela politica de rollout
                let mut jj = 0u32;
                match joga_ate_o_fim(&mut w, &d, &pol, &mut jj) {
                    Passo::Venceu => break 1.0,
                    Passo::Perdeu => break 0.0,
                    Passo::ForaDoNucleo(m) => {
                        fora += 1;
                        anota(&m);
                        break nota(&w.ativo, &w.oponente);
                    }
                    Passo::Segue => break depois_do_meu_turno(w, gt, &pol, cfg.turnos_rollout, &mut fora),
                }
            }
        };
        for k in caminho {
            nos[k].visitas += 1;
            nos[k].soma += valor;
        }
    }
    let raiz: Vec<(Jogada, u32, f64)> = nos[0].filhos.iter()
        .map(|(j, k)| (j.clone(), nos[*k].visitas, nos[*k].soma / nos[*k].visitas.max(1) as f64))
        .collect();
    let jogada = raiz.iter().max_by_key(|(_, v, _)| *v).map(|x| x.0.clone()).unwrap_or(Jogada::Fim);
    let _ = abre_turno;
    let motivos = MOTIVOS.with(|x| std::mem::take(&mut *x.borrow_mut()));
    Resposta { jogada, raiz, iteracoes: cfg.iteracoes, fora_do_nucleo: fora, motivos }
}

/// Uma decisao do auto-jogo: o que a busca viu e escolheu.
pub struct Registro {
    /// 0 = quem comecou a partida, 1 = o outro
    pub lado: u8,
    pub feats: [f64; 32],
    /// jogadas legais (na ordem de `jogadas_legais`) e visitas da busca em cada uma
    pub legais: Vec<Jogada>,
    pub visitas: Vec<u32>,
    pub escolhida: usize,
    /// features da rede nova (`feats.rs`): estado e cada jogada legal
    pub estado: Vec<f32>,
    pub jogadas: Vec<Vec<f32>>,
}

pub struct Partida {
    /// 0 / 1 (como `Registro::lado`), None = limite de turnos ou caso fora do nucleo
    pub vencedor: Option<u8>,
    pub registros: Vec<Registro>,
    pub turnos: u32,
    pub fora_do_nucleo: Option<String>,
}

/// AUTO-JOGO (fase C): partida inteira no nucleo, a busca decidindo a jogada
/// principal dos DOIS lados. `e` = estado antes do 1o inicio de turno.
/// `rede_outro` = espaco da rede do lado 1 (o lado 0 usa `cfg.rede`): duas
/// geracoes jogando uma contra a outra.
pub fn autojogo(mut e: Estado, mut gt: i64, cfg: &Config, max_turnos: u32, rede_outro: u8) -> Partida {
    let pol: PoliticaRef = Rc::new(RefCell::new(Rollout(Rng::novo(cfg.semente ^ 0xA5A5))));
    let mut d = Decisoes { politica: Some(pol.clone()), ..Default::default() };
    let mut regs = Vec::new();
    let mut lado = 0u8;
    let mut turnos = 0u32;
    let mut sem = cfg.semente;
    let acaba = |v: Option<u8>, r, t, m| Partida { vencedor: v, registros: r, turnos: t, fora_do_nucleo: m };
    while turnos < max_turnos {
        if let Passo::ForaDoNucleo(m) = abre_turno(&mut e, gt, &pol) {
            return acaba(None, regs, turnos, Some(m));
        }
        gt += 1;
        turnos += 1;
        let mut passo = Passo::Segue;
        let mut proibidas: Vec<Jogada> = Vec::new();
        for _ in 0..200 {
            let legais: Vec<Jogada> = match jogadas_legais(&e) {
                Ok(v) => v.into_iter().filter(|j| !proibidas.contains(j)).collect(),
                Err(_) => return acaba(None, regs, turnos, Some("legais".into())),
            };
            sem = sem.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let r = busca_sem(&e, gt, &Config { semente: sem, rede: if lado == 0 { cfg.rede } else { rede_outro }, ..*cfg }, &proibidas);
            let visitas: Vec<u32> = legais.iter()
                .map(|j| r.raiz.iter().find(|(x, _, _)| x == j).map_or(0, |x| x.1)).collect();
            let escolhida = legais.iter().position(|j| *j == r.jogada).unwrap_or(legais.len() - 1);
            regs.push(Registro {
                lado, feats: crate::valor::features(&e.ativo, &e.oponente), legais: legais.clone(), visitas, escolhida,
                estado: crate::feats::estado(&e.ativo, &e.oponente),
                jogadas: legais.iter().map(|j| crate::feats::jogada(&e.ativo, &e.oponente, j)).collect(),
            });
            if legais[escolhida] == Jogada::Fim {
                break;
            }
            // o defensor (lado de fora do turno) defende com a rede DELE
            d.rede = if cfg.defesa_rede { if lado == 0 { rede_outro } else { cfg.rede } } else { 0 };
            // efeito ainda fora do nucleo: desfaz, proibe a jogada nesta decisao e segue
            let antes = e.clone();
            passo = joga(&mut e, &legais[escolhida], &d);
            if let Passo::ForaDoNucleo(_) = passo {
                e = antes;
                proibidas.push(legais[escolhida].clone());
                regs.pop();
                passo = Passo::Segue;
                continue;
            }
            proibidas.clear();
            if !matches!(passo, Passo::Segue) {
                break;
            }
        }
        if let Passo::Segue = passo {
            passo = fecha_turno(&mut e, &pol);
        }
        match passo {
            Passo::Segue => {}
            Passo::Venceu => return acaba(Some(lado), regs, turnos, None),
            Passo::Perdeu => return acaba(Some(1 - lado), regs, turnos, None),
            Passo::ForaDoNucleo(m) => return acaba(None, regs, turnos, Some(m)),
        }
        std::mem::swap(&mut e.ativo, &mut e.oponente);
        lado = 1 - lado;
    }
    acaba(None, regs, turnos, None)
}
