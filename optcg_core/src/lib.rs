//! Nucleo do jogo em Rust (PLANO_MOTOR_FORTE.md, fase A; ESPEC.md).
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;

pub mod acoes;
pub mod busca;
pub mod cartas;
pub mod efeitos;
pub mod estado;
pub mod jogo;
pub mod legais;
pub mod turno;

fn erro(x: impl ToString) -> PyErr {
    PyValueError::new_err(x.to_string())
}

#[pyfunction]
fn versao() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Carrega (ou acrescenta) dados impressos de cartas: {code: InfoCarta}.
#[pyfunction]
fn carrega_cartas(tabela_json: &str) -> PyResult<usize> {
    let t: HashMap<String, cartas::InfoCarta> = serde_json::from_str(tabela_json).map_err(erro)?;
    let n = t.len();
    cartas::carrega(t);
    Ok(n)
}

/// Teste diferencial: estado canonico (JSON) de `turno_inicio` -> inicio de
/// turno do nucleo -> estado canonico (JSON).
#[pyfunction]
fn inicio_de_turno(estado_json: &str, global_turn: i64, decisoes_json: &str) -> PyResult<(String, String)> {
    let mut e = estado::Estado::de_json(estado_json).map_err(erro)?;
    let fila: Vec<serde_json::Value> = serde_json::from_str(decisoes_json).map_err(erro)?;
    match turno::inicio_de_turno(&mut e, global_turn, fila.into(), None) {
        Ok(()) => Ok(("ok".into(), e.para_json().map_err(erro)?)),
        Err(acoes::Resultado::NaoSuportado(m)) => Ok(("nao_suportado".into(), m)),
        Err(_) => Ok(("nao_suportado".into(), "resultado inesperado".into())),
    }
}

/// Teste diferencial: estado de `fim_antes` -> fim de turno do nucleo.
#[pyfunction]
fn fim_de_turno(estado_json: &str, decisoes_json: &str) -> PyResult<(String, String)> {
    let mut e = estado::Estado::de_json(estado_json).map_err(erro)?;
    let fila: Vec<serde_json::Value> = serde_json::from_str(decisoes_json).map_err(erro)?;
    match turno::fim_de_turno(&mut e, fila.into(), None) {
        Ok(()) => Ok(("ok".into(), e.para_json().map_err(erro)?)),
        Err(acoes::Resultado::NaoSuportado(m)) => Ok(("nao_suportado".into(), m)),
        Err(_) => Ok(("nao_suportado".into(), "resultado inesperado".into())),
    }
}

/// Teste diferencial de UMA jogada principal: estado antes + jogada (por LUGAR)
/// + decisoes internas -> ("ok", estado depois, venceu) ou ("nao_suportado", motivo, false).
#[pyfunction]
fn aplica_jogada(
    estado_json: &str,
    acao_json: &str,
    decisoes_json: &str,
) -> PyResult<(String, String, bool)> {
    let mut e = estado::Estado::de_json(estado_json).map_err(erro)?;
    let acao: serde_json::Value = serde_json::from_str(acao_json).map_err(erro)?;
    let d: acoes::Decisoes = serde_json::from_str(decisoes_json).map_err(erro)?;
    match acoes::aplica(&mut e, &acao, &d) {
        acoes::Resultado::Feito { venceu } => {
            // `marca_publicas` dos dois lados ao fim de cada jogada (_apply_action)
            e.ativo.marca_publicas();
            e.oponente.marca_publicas();
            Ok(("ok".to_string(), e.para_json().map_err(erro)?, venceu))
        }
        acoes::Resultado::NaoSuportado(m) => Ok(("nao_suportado".to_string(), m, false)),
    }
}

/// So le e reescreve o estado (confere que o modelo de dados faz ida e volta exata).
#[pyfunction]
fn ida_e_volta(estado_json: &str) -> PyResult<String> {
    let mut e = estado::Estado::de_json(estado_json).map_err(erro)?;
    e.para_json().map_err(erro)
}

/// Jogadas legais (regras) do jogador ativo: ("ok", lista JSON) ou ("nao_suportado", motivo).
#[pyfunction]
fn jogadas_legais(estado_json: &str) -> PyResult<(String, String)> {
    let e = estado::Estado::de_json(estado_json).map_err(erro)?;
    match legais::jogadas_legais(&e) {
        Ok(v) => Ok(("ok".into(), serde_json::to_string(&v.iter().map(|j| j.para_json()).collect::<Vec<_>>()).map_err(erro)?)),
        Err(acoes::Resultado::NaoSuportado(m)) => Ok(("nao_suportado".into(), m)),
        Err(_) => Ok(("nao_suportado".into(), "resultado inesperado".into())),
    }
}

/// N partidas inteiras so no nucleo (politica aleatoria) a partir do estado:
/// resumo JSON com vitorias, jogadas, casos fora do nucleo e o tempo gasto.
#[pyfunction]
fn simula_partidas(estado_json: &str, global_turn: i64, n: u32, semente: u64, max_turnos: u32) -> PyResult<String> {
    let e = estado::Estado::de_json(estado_json).map_err(erro)?;
    let t0 = std::time::Instant::now();
    let fins = jogo::simula_varias(&e, global_turn, n, semente, max_turnos);
    let seg = t0.elapsed().as_secs_f64();
    let mut ns: std::collections::BTreeMap<String, u32> = Default::default();
    let (mut v0, mut v1, mut emp, mut jog, mut tur) = (0, 0, 0, 0u64, 0u64);
    for f in &fins {
        jog += f.jogadas as u64;
        tur += f.turnos as u64;
        match (&f.nao_suportado, f.vencedor) {
            (Some(m), _) => *ns.entry(m.clone()).or_default() += 1,
            (None, Some(0)) => v0 += 1,
            (None, Some(_)) => v1 += 1,
            (None, None) => emp += 1,
        }
    }
    Ok(serde_json::json!({"partidas": n, "vitorias_ativo": v0, "vitorias_outro": v1, "limite": emp,
        "nao_suportado": ns, "jogadas": jog, "turnos": tur, "segundos": seg,
        "tempos": jogo::TEMPOS.with(|x| x.borrow().to_vec())}).to_string())
}

/// Busca (ISMCTS) da melhor jogada do ativo, no meio da Main dele.
#[pyfunction]
fn busca_jogada(estado_json: &str, global_turn: i64, iteracoes: u32, turnos_rollout: u32, c_ucb: f64, semente: u64) -> PyResult<String> {
    let e = estado::Estado::de_json(estado_json).map_err(erro)?;
    let t0 = std::time::Instant::now();
    let r = busca::busca(&e, global_turn, &busca::Config { iteracoes, turnos_rollout, c_ucb, semente });
    let raiz: Vec<serde_json::Value> = r.raiz.iter()
        .map(|(j, v, q)| serde_json::json!({"jogada": j.para_json(), "visitas": v, "valor": q})).collect();
    Ok(serde_json::json!({"jogada": r.jogada.para_json(), "raiz": raiz, "iteracoes": r.iteracoes,
        "fora_do_nucleo": r.fora_do_nucleo, "motivos": r.motivos, "segundos": t0.elapsed().as_secs_f64()}).to_string())
}

#[pymodule]
fn optcg_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(versao, m)?)?;
    m.add_function(wrap_pyfunction!(carrega_cartas, m)?)?;
    m.add_function(wrap_pyfunction!(inicio_de_turno, m)?)?;
    m.add_function(wrap_pyfunction!(fim_de_turno, m)?)?;
    m.add_function(wrap_pyfunction!(aplica_jogada, m)?)?;
    m.add_function(wrap_pyfunction!(ida_e_volta, m)?)?;
    m.add_function(wrap_pyfunction!(jogadas_legais, m)?)?;
    m.add_function(wrap_pyfunction!(simula_partidas, m)?)?;
    m.add_function(wrap_pyfunction!(busca_jogada, m)?)?;
    Ok(())
}
