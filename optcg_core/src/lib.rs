//! Nucleo do jogo em Rust (PLANO_MOTOR_FORTE.md, fase A; ESPEC.md).
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

pub mod estado;
pub mod turno;

fn erro(x: impl ToString) -> PyErr {
    PyValueError::new_err(x.to_string())
}

#[pyfunction]
fn versao() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Teste diferencial: recebe o estado canonico (JSON) de `turno_inicio`, aplica o
/// inicio de turno do nucleo e devolve o estado canonico (JSON) resultante.
#[pyfunction]
fn inicio_de_turno(estado_json: &str, global_turn: i64) -> PyResult<String> {
    let mut e = estado::Estado::de_json(estado_json).map_err(erro)?;
    turno::inicio_de_turno(&mut e, global_turn);
    e.para_json().map_err(erro)
}

/// So le e reescreve o estado (confere que o modelo de dados faz ida e volta exata).
#[pyfunction]
fn ida_e_volta(estado_json: &str) -> PyResult<String> {
    let mut e = estado::Estado::de_json(estado_json).map_err(erro)?;
    e.para_json().map_err(erro)
}

#[pymodule]
fn optcg_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(versao, m)?)?;
    m.add_function(wrap_pyfunction!(inicio_de_turno, m)?)?;
    m.add_function(wrap_pyfunction!(ida_e_volta, m)?)?;
    Ok(())
}
