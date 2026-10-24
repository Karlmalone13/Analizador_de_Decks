//! Nucleo do jogo em Rust (PLANO_MOTOR_FORTE.md, fase A). Por enquanto so o
//! esqueleto que prova a cadeia Rust -> Python (maturin/PyO3).
use pyo3::prelude::*;

/// Versao do nucleo (confere que o modulo carregado e o compilado agora).
#[pyfunction]
fn versao() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn optcg_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(versao, m)?)?;
    Ok(())
}
