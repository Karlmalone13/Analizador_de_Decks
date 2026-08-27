"""Superficie de CONTROLE do motor -- knobs nomeados, ajustaveis e rastreaveis.

Pedido do usuario (27/08/2026): *"Precisamos criar um sistema controlavel
e observavel nao so observavel"*. O diagnostico que motivou: o motor tinha
~40 constantes de tuning espalhadas como valores fixos de modulo, 4 flags
de ambiente feitas a mao, e **nenhum registro de qual configuracao gerou
qual medicao** -- comparar "antes/depois" dependia da memoria de quem
editou. Mudar qualquer comportamento exigia editar heuristica no
`decision_engine.py` e esperar ~1h30 pra saber se foi pro lado certo.

O que este modulo da:

  1. **Um lugar so** pra declarar cada parametro ajustavel (nome, default,
     tipo, faixa valida, descricao, categoria).
  2. **Override em runtime** sem editar codigo: arquivo JSON
     (`OPTCG_KNOBS=caminho.json`) ou variavel de ambiente
     (`OPTCG_K_<NOME>=valor`). Precedencia: env > arquivo > default.
  3. **Fingerprint** -- `fingerprint()` devolve o conjunto de valores
     NAO-default + um hash curto. A regua grava isso junto do resultado,
     entao toda medicao fica atribuivel e reproduzivel.
  4. Base pro varredor (`sweep.py`): medir N configuracoes e comparar.

NAO cria caminho de decisao novo. Um knob PARAMETRIZA o caminho unico que
ja existe -- nunca vira um segundo jeito de responder a mesma decisao do
jogo (`REGRA_SEM_DUPLICACAO.md`). Se um knob so faz sentido ligando um
ramo alternativo de logica, ele esta errado: o certo e o ramo unico ler o
valor.

**Aviso sobre overfitting (assumido, nao ignorado):** varrer knobs contra
o corpus aproxima de otimizar nos MESMOS logs que validam a metrica. Por
isso `sweep.py` reporta o recorte POR LIDER obrigatoriamente -- um knob
que sobe o agregado mas so mexe em 2 lideres nao generalizou, e o
objetivo do projeto e jogar bem com QUALQUER deck.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Knob:
    nome: str
    default: Any
    tipo: Callable[[str], Any]
    descricao: str
    categoria: str = 'geral'
    minimo: float | None = None
    maximo: float | None = None

    def valida(self, v: Any) -> Any:
        if self.minimo is not None and v < self.minimo:
            raise ValueError(f'{self.nome}={v} abaixo do minimo {self.minimo}')
        if self.maximo is not None and v > self.maximo:
            raise ValueError(f'{self.nome}={v} acima do maximo {self.maximo}')
        return v


def _bool(s: str) -> bool:
    return str(s).strip().lower() in ('1', 'true', 'yes', 'sim', 'on')


REGISTRO: dict[str, Knob] = {}


def registra(nome: str, default: Any, tipo, descricao: str,
             categoria: str = 'geral', minimo=None, maximo=None) -> None:
    if nome in REGISTRO:
        raise ValueError(f'knob duplicado: {nome}')
    REGISTRO[nome] = Knob(nome, default, tipo, descricao, categoria,
                          minimo, maximo)


# ── Valores efetivos ────────────────────────────────────────────────────
_ARQUIVO: dict[str, Any] = {}
_caminho = os.environ.get('OPTCG_KNOBS', '')
if _caminho:
    try:
        with open(_caminho, encoding='utf-8') as fh:
            _ARQUIVO = json.load(fh)
    except Exception as e:                                   # pragma: no cover
        # Falha ALTA e proposital: rodar uma medicao com o arquivo de
        # configuracao silenciosamente ignorado produz um numero que
        # parece valido e nao e. Ja aconteceu com o modelo de politica
        # (bloco 682) -- worker com modelo velho caiu num except generico
        # e mediu com a politica DESLIGADA sem ninguem notar.
        raise RuntimeError(f'OPTCG_KNOBS={_caminho} ilegivel: {e}') from e

_cache: dict[str, Any] = {}


def get(nome: str) -> Any:
    """Valor efetivo do knob. Precedencia: env > arquivo > default."""
    if nome in _cache:
        return _cache[nome]
    k = REGISTRO.get(nome)
    if k is None:
        raise KeyError(f'knob nao registrado: {nome}')
    bruto = os.environ.get(f'OPTCG_K_{nome}')
    if bruto is not None:
        v = k.valida(k.tipo(bruto))
    elif nome in _ARQUIVO:
        v = k.valida(k.tipo(_ARQUIVO[nome]) if isinstance(_ARQUIVO[nome], str)
                     else _ARQUIVO[nome])
    else:
        v = k.default
    _cache[nome] = v
    return v


def nao_default() -> dict[str, Any]:
    """Só o que foi alterado -- o que descreve um experimento."""
    fora = {}
    for nome, k in REGISTRO.items():
        v = get(nome)
        if v != k.default:
            fora[nome] = v
    return fora


def fingerprint() -> dict[str, Any]:
    """Identidade da configuracao, pra gravar junto de qualquer medicao."""
    fora = nao_default()
    bruto = json.dumps(fora, sort_keys=True, ensure_ascii=False)
    return {
        'knobs_nao_default': fora,
        'knobs_hash': hashlib.sha1(bruto.encode()).hexdigest()[:12],
        'knobs_total_registrados': len(REGISTRO),
    }


def descreve() -> str:
    linhas = []
    por_cat: dict[str, list[Knob]] = {}
    for k in REGISTRO.values():
        por_cat.setdefault(k.categoria, []).append(k)
    for cat in sorted(por_cat):
        linhas.append(f'\n[{cat}]')
        for k in sorted(por_cat[cat], key=lambda x: x.nome):
            atual = get(k.nome)
            marca = '' if atual == k.default else '  <-- ALTERADO'
            faixa = ''
            if k.minimo is not None or k.maximo is not None:
                faixa = f' [{k.minimo}..{k.maximo}]'
            linhas.append(f'  {k.nome:34} = {atual!r:>10}'
                          f'  (default {k.default!r}){faixa}{marca}')
            linhas.append(f'  {"":34}   {k.descricao}')
    return '\n'.join(linhas)


if __name__ == '__main__':
    import optcg_engine.decision_engine  # noqa: F401  (popula o registro)
    print(descreve())
    print('\nfingerprint:', json.dumps(fingerprint(), ensure_ascii=False))
