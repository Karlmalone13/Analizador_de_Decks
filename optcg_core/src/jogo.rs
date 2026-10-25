//! Partida inteira SO no nucleo (sem o motor Python decidindo nada): o laco de
//! turnos de `OPTCGMatch.play_turn` (inicio -> jogadas -> fim -> troca de lado),
//! com as jogadas da lista de `legais` e as escolhas internas de uma `Politica`.
//! E o simulador que a busca da fase B vai rodar milhares de vezes por decisao.
use crate::acoes::{aplica_j, Decisoes, Jogada, Resultado};
use crate::efeitos::{Politica, PoliticaRef};
use crate::estado::Estado;
use crate::legais::jogadas_legais;
use crate::turno::{fim_de_turno, inicio_de_turno};
use serde_json::Value;
use std::cell::RefCell;
use std::rc::Rc;

/// Gerador pseudo-aleatorio pequeno e deterministico (xorshift64*)
pub struct Rng(u64);

impl Rng {
    pub fn novo(semente: u64) -> Self {
        Rng(semente.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1)
    }
    pub fn ate(&mut self, n: usize) -> usize {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        (self.0.wrapping_mul(0x2545_F491_4F6C_DD1D) >> 33) as usize % n.max(1)
    }
}

/// Politica uniforme: cada opcao (e "nenhuma", quando permitida) com a mesma chance.
pub struct Aleatoria(pub Rng);

impl Politica for Aleatoria {
    fn escolhe(&mut self, _qual: &str, n: usize, pode_nenhuma: bool) -> Option<usize> {
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

thread_local! { pub static TEMPOS: std::cell::RefCell<[f64; 8]> = std::cell::RefCell::new([0.0; 8]); }
pub fn soma(i: usize, t: std::time::Instant) { TEMPOS.with(|x| x.borrow_mut()[i] += t.elapsed().as_secs_f64()); }

pub struct Fim {
    /// 0 = quem comecou ativo no estado inicial, 1 = o outro, None = limite de turnos
    pub vencedor: Option<u8>,
    pub turnos: u32,
    pub jogadas: u32,
    /// Some(motivo) = parou num caso ainda fora do nucleo
    pub nao_suportado: Option<String>,
}

/// Como acabou um trecho do turno, do ponto de vista de quem esta ATIVO nele.
pub enum Passo {
    Segue,
    Venceu,
    Perdeu,
    ForaDoNucleo(String),
}

/// Inicio do turno do ativo (`_once_main` zerado: um executor da Main por turno).
pub fn abre_turno(e: &mut Estado, global_turn: i64, pol: &PoliticaRef) -> Passo {
    e.ativo.extras.insert("_once_main".into(), Value::Array(vec![]));
    let t0 = std::time::Instant::now();
    let r = inicio_de_turno(e, global_turn, Default::default(), Some(pol.clone()));
    soma(0, t0);
    match r {
        Err(Resultado::NaoSuportado(m)) => Passo::ForaDoNucleo(format!("inicio: {m}")),
        _ => Passo::Segue,
    }
}

/// Aplica UMA jogada principal do ativo.
pub fn joga(e: &mut Estado, j: &Jogada, d: &Decisoes) -> Passo {
    let t2 = std::time::Instant::now();
    let r = aplica_j(e, j, d);
    soma(2, t2);
    match r {
        Resultado::Feito { venceu } => {
            e.ativo.marca_publicas();
            e.oponente.marca_publicas();
            if venceu { Passo::Venceu } else { Passo::Segue }
        }
        Resultado::NaoSuportado(m) => Passo::ForaDoNucleo(m),
    }
}

/// Jogadas do ativo ate a politica escolher `Fim` (ou acabar a partida).
pub fn joga_ate_o_fim(e: &mut Estado, d: &Decisoes, pol: &PoliticaRef, jogadas: &mut u32) -> Passo {
    loop {
        let t1 = std::time::Instant::now();
        let leg = jogadas_legais(e);
        soma(1, t1);
        let leg = match leg {
            Ok(v) => v,
            Err(Resultado::NaoSuportado(m)) => return Passo::ForaDoNucleo(format!("legais: {m}")),
            Err(_) => return Passo::ForaDoNucleo("legais: inesperado".into()),
        };
        let k = pol.borrow_mut().escolhe("jogada", leg.len(), false).unwrap_or(0).min(leg.len() - 1);
        if leg[k] == Jogada::Fim {
            return Passo::Segue;
        }
        *jogadas += 1;
        match joga(e, &leg[k], d) {
            Passo::Segue => {}
            outro => return outro,
        }
    }
}

/// Fim do turno do ativo + deck vazio (perde quem ficou sem deck). NAO troca de lado.
pub fn fecha_turno(e: &mut Estado, pol: &PoliticaRef) -> Passo {
    let t3 = std::time::Instant::now();
    let r = fim_de_turno(e, Default::default(), Some(pol.clone()));
    soma(3, t3);
    if let Err(Resultado::NaoSuportado(m)) = r {
        return Passo::ForaDoNucleo(format!("fim: {m}"));
    }
    // deck_out_win_instead_of_loss ainda fora do nucleo
    if e.ativo.deck.is_empty() {
        return Passo::Perdeu;
    }
    if e.oponente.deck.is_empty() {
        return Passo::Venceu;
    }
    Passo::Segue
}

/// Joga do estado `e` (ativo = quem vai comecar o PROXIMO turno, antes do inicio
/// de turno) ate o fim. `global_turn` = contador da partida antes desse turno.
pub fn simula(mut e: Estado, mut global_turn: i64, pol: PoliticaRef, max_turnos: u32) -> Fim {
    let d = Decisoes { politica: Some(pol.clone()), ..Default::default() };
    let mut lado = 0u8;
    let (mut turnos, mut jogadas) = (0u32, 0u32);
    while turnos < max_turnos {
        let mut p = abre_turno(&mut e, global_turn, &pol);
        global_turn += 1;
        turnos += 1;
        if let Passo::Segue = p {
            p = joga_ate_o_fim(&mut e, &d, &pol, &mut jogadas);
        }
        if let Passo::Segue = p {
            p = fecha_turno(&mut e, &pol);
        }
        let fim = |v, m| Fim { vencedor: v, turnos, jogadas, nao_suportado: m };
        match p {
            Passo::Segue => {}
            Passo::Venceu => return fim(Some(lado), None),
            Passo::Perdeu => return fim(Some(1 - lado), None),
            Passo::ForaDoNucleo(m) => return fim(None, Some(m)),
        }
        std::mem::swap(&mut e.ativo, &mut e.oponente);
        lado = 1 - lado;
    }
    Fim { vencedor: None, turnos, jogadas, nao_suportado: None }
}

/// N partidas aleatorias a partir do mesmo estado (para medir velocidade).
pub fn simula_varias(e: &Estado, global_turn: i64, n: u32, semente: u64, max_turnos: u32) -> Vec<Fim> {
    let pol: PoliticaRef = Rc::new(RefCell::new(Aleatoria(Rng::novo(semente))));
    (0..n).map(|_| simula(e.clone(), global_turn, pol.clone(), max_turnos)).collect()
}
