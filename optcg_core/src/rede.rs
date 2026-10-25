//! REDE de POLITICA + VALOR da fase C no nucleo (pesos de `rede_pv.py`):
//! tronco de 2 camadas sobre `feats::estado`, valor (sigmoide) e uma nota por
//! jogada legal sobre [tronco ; `feats::jogada`]. Mesma conta do `Rede.passo`.
use crate::acoes::Jogada;
use crate::estado::Jogador;
use serde::Deserialize;
use std::sync::{Arc, RwLock};

#[derive(Deserialize)]
#[allow(non_snake_case)]
pub struct Rede {
    W1: Vec<Vec<f64>>,
    b1: Vec<f64>,
    W2: Vec<Vec<f64>>,
    b2: Vec<f64>,
    wv: Vec<f64>,
    bv: Vec<f64>,
    Wa: Vec<Vec<f64>>,
    ba: Vec<f64>,
    wp: Vec<f64>,
    bp: Vec<f64>,
    media_s: Vec<f64>,
    desvio_s: Vec<f64>,
    media_a: Vec<f64>,
    desvio_a: Vec<f64>,
}

/// Espacos de rede: 0 = sem rede; 1..=3 (duas geracoes podem jogar uma contra a outra).
static REDES: RwLock<[Option<Arc<Rede>>; 4]> = RwLock::new([None, None, None, None]);

pub fn carrega(espaco: usize, r: Option<Rede>) -> Result<(), String> {
    if espaco == 0 || espaco > 3 {
        return Err("espaco de rede invalido (1..3)".into());
    }
    if let Some(r) = &r {
        if r.media_s.len() != crate::feats::N_ESTADO || r.media_a.len() != crate::feats::N_JOGADA {
            return Err("rede com features de outro tamanho".into());
        }
    }
    REDES.write().unwrap()[espaco] = r.map(Arc::new);
    Ok(())
}

pub fn rede(espaco: u8) -> Option<Arc<Rede>> {
    REDES.read().unwrap().get(espaco as usize).cloned().flatten()
}

/// x (linha) . W (linhas = entradas) + b, com relu
fn camada(x: &[f64], w: &[Vec<f64>], b: &[f64]) -> Vec<f64> {
    let mut y = b.to_vec();
    for (xi, wi) in x.iter().zip(w) {
        if *xi != 0.0 {
            for (yj, wij) in y.iter_mut().zip(wi) {
                *yj += xi * wij;
            }
        }
    }
    for v in y.iter_mut() {
        if *v < 0.0 {
            *v = 0.0;
        }
    }
    y
}

impl Rede {
    fn tronco(&self, eu: &Jogador, ele: &Jogador) -> Vec<f64> {
        let s: Vec<f64> = crate::feats::estado(eu, ele).iter().zip(self.media_s.iter().zip(&self.desvio_s))
            .map(|(x, (m, d))| (*x as f64 - m) / d).collect();
        let h1 = camada(&s, &self.W1, &self.b1);
        camada(&h1, &self.W2, &self.b2)
    }

    /// chance de `eu` vencer
    pub fn valor(&self, eu: &Jogador, ele: &Jogador) -> f64 {
        let h = self.tronco(eu, ele);
        let l: f64 = h.iter().zip(&self.wv).map(|(a, b)| a * b).sum::<f64>() + self.bv[0];
        1.0 / (1.0 + (-l).exp())
    }

    /// probabilidade de cada jogada (softmax das notas) + o valor, numa conta so
    pub fn politica(&self, eu: &Jogador, ele: &Jogador, legais: &[Jogada]) -> (Vec<f64>, f64) {
        let h = self.tronco(eu, ele);
        let lv: f64 = h.iter().zip(&self.wv).map(|(a, b)| a * b).sum::<f64>() + self.bv[0];
        let mut logits = Vec::with_capacity(legais.len());
        for j in legais {
            let a = crate::feats::jogada(eu, ele, j);
            let mut z = h.clone();
            z.extend(a.iter().zip(self.media_a.iter().zip(&self.desvio_a)).map(|(x, (m, d))| (*x as f64 - m) / d));
            let u = camada(&z, &self.Wa, &self.ba);
            logits.push(u.iter().zip(&self.wp).map(|(a, b)| a * b).sum::<f64>() + self.bp[0]);
        }
        let mx = logits.iter().cloned().fold(f64::MIN, f64::max);
        let e: Vec<f64> = logits.iter().map(|l| (l - mx).exp()).collect();
        let s: f64 = e.iter().sum();
        (e.iter().map(|x| x / s).collect(), 1.0 / (1.0 + (-lv).exp()))
    }
}
