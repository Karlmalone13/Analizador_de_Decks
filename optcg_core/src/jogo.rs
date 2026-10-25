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

/// Joga do estado `e` (ativo = quem vai comecar o PROXIMO turno, antes do inicio
/// de turno) ate o fim. `global_turn` = contador da partida antes desse turno.
pub fn simula(mut e: Estado, mut global_turn: i64, pol: PoliticaRef, max_turnos: u32) -> Fim {
    let d = Decisoes { politica: Some(pol.clone()), ..Default::default() };
    let mut lado = 0u8;
    let (mut turnos, mut jogadas) = (0u32, 0u32);
    let fim = |v, t, j, m: Option<String>| Fim { vencedor: v, turnos: t, jogadas: j, nao_suportado: m };
    while turnos < max_turnos {
        // `_once_used` do executor da Main: um executor novo a cada main_phase
        e.ativo.extras.insert("_once_main".into(), Value::Array(vec![]));
        let t0 = std::time::Instant::now();
        let r0 = inicio_de_turno(&mut e, global_turn, Default::default(), Some(pol.clone()));
        soma(0, t0);
        if let Err(Resultado::NaoSuportado(m)) = r0 {
            return fim(None, turnos, jogadas, Some(format!("inicio: {m}")));
        }
        global_turn += 1;
        turnos += 1;
        loop {
            let t1 = std::time::Instant::now();
            let leg0 = jogadas_legais(&e);
            soma(1, t1);
            let leg = match leg0 {
                Ok(v) => v,
                Err(Resultado::NaoSuportado(m)) => return fim(None, turnos, jogadas, Some(format!("legais: {m}"))),
                Err(_) => return fim(None, turnos, jogadas, Some("legais: inesperado".into())),
            };
            let k = pol.borrow_mut().escolhe("jogada", leg.len(), false).unwrap_or(0).min(leg.len() - 1);
            let a = &leg[k];
            if *a == Jogada::Fim {
                break;
            }
            jogadas += 1;
            let t2 = std::time::Instant::now();
            let ra = aplica_j(&mut e, a, &d);
            soma(2, t2);
            match ra {
                Resultado::Feito { venceu } => {
                    e.ativo.marca_publicas();
                    e.oponente.marca_publicas();
                    if venceu {
                        return fim(Some(lado), turnos, jogadas, None);
                    }
                }
                Resultado::NaoSuportado(m) => return fim(None, turnos, jogadas, Some(m)),
            }
        }
        let t3 = std::time::Instant::now();
        let r3 = fim_de_turno(&mut e, Default::default(), Some(pol.clone()));
        soma(3, t3);
        if let Err(Resultado::NaoSuportado(m)) = r3 {
            return fim(None, turnos, jogadas, Some(format!("fim: {m}")));
        }
        // deck vazio ao fim do turno: perde (deck_out_win_instead_of_loss ainda fora)
        if e.ativo.deck.is_empty() {
            return fim(Some(1 - lado), turnos, jogadas, None);
        }
        if e.oponente.deck.is_empty() {
            return fim(Some(lado), turnos, jogadas, None);
        }
        std::mem::swap(&mut e.ativo, &mut e.oponente);
        lado = 1 - lado;
    }
    fim(None, turnos, jogadas, None)
}

/// N partidas aleatorias a partir do mesmo estado (para medir velocidade).
pub fn simula_varias(e: &Estado, global_turn: i64, n: u32, semente: u64, max_turnos: u32) -> Vec<Fim> {
    let pol: PoliticaRef = Rc::new(RefCell::new(Aleatoria(Rng::novo(semente))));
    (0..n).map(|_| simula(e.clone(), global_turn, pol.clone(), max_turnos)).collect()
}
