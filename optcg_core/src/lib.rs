//! Nucleo do jogo em Rust (PLANO_MOTOR_FORTE.md, fase A; ESPEC.md).
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;

pub mod acoes;
pub mod cartas;
pub mod estado;
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
fn inicio_de_turno(estado_json: &str, global_turn: i64) -> PyResult<String> {
    let mut e = estado::Estado::de_json(estado_json).map_err(erro)?;
    turno::inicio_de_turno(&mut e, global_turn);
    e.para_json().map_err(erro)
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

#[pymodule]
fn optcg_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(versao, m)?)?;
    m.add_function(wrap_pyfunction!(carrega_cartas, m)?)?;
    m.add_function(wrap_pyfunction!(inicio_de_turno, m)?)?;
    m.add_function(wrap_pyfunction!(aplica_jogada, m)?)?;
    m.add_function(wrap_pyfunction!(ida_e_volta, m)?)?;
    Ok(())
}
