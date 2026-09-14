#!/usr/bin/env python3
"""As partidas AO VIVO (CPU x CPU no simulador) tambem alimentam o corpus do Q.

POR QUE EXISTE (pedido do usuario, 14/09/2026, bloco 831): *"eu so quero que a
cpu x cpu tb seja um treino, so que com um diferencial que eu consigo
vizualizar e acompanhar turno a turno"*.

Ate aqui o CPU x CPU produzia combat log + telemetria e o dado de DECISAO era
jogado fora. O bloco 816 tinha enquadrado a bancada como "validacao, nao
caminho de dado" -- **e isso continua certo quanto a VOLUME** (uma partida no
simulador custa 15-30 min contra ~0,6s no motor, entao ela nunca vai ser a
fonte principal). Mas volume nao e o unico eixo: a partida ja esta sendo
gerada e assistida de qualquer jeito, e descartar o dado dela era perda pura.

### Como funciona, sem motor novo

O captador do corpus JA EXISTE no motor e e opt-in:

```python
# decision_engine.py:19053
# Default desligado: `_q_captura` fica None e isto custa zero.
_cap = getattr(self, '_q_captura', None)
```

O caminho ao vivo chama o MESMO `decision_engine` (via
`sim_bridge.choose_action`, com o `OPTCGMatch` singleton do server). Provado
empiricamente antes de escrever isto: com `_q_captura = []`, um
`choose_action` devolveu 2 linhas de 101 features, com `alvo` e `escolhida`
corretamente marcada -- formato IDENTICO ao do self-play.

Entao aqui nao ha decisao nenhuma sendo tomada, nem regra reimplementada: este
modulo so LIGA o captador, junta as linhas por partida e grava. A regra do
MOTOR UNICO (`REGRA_SEM_DUPLICACAO.md`) fica intacta -- quem produz o dado e o
motor, igual no self-play.

### O que e diferente do self-play, e por que isso e o VALOR

| | self-play (`ciclo.py`) | aqui |
|---|---|---|
| quem julga a legalidade | o nosso codigo | **o JOGO de verdade** |
| custo por partida | ~0,6s | 15-30 min |
| volume | ~72.000 alvos / 300 partidas | ~dezenas por partida |

O volume e desprezivel (uma partida ao vivo e ~0,1% de um ciclo). O que ela tem
de unico e a FIDELIDADE: sao estados adjudicados pelo jogo real, a mesma
distribuicao em que o bot de fato joga. Por isso as linhas saem com `origem`
propria -- o mecanismo do bloco 820 -- e nao se misturam sem rastro: da pra
medir o efeito delas separadamente, ou remove-las, a qualquer momento.

### Cuidados deliberados

* **So o `/decide` REAL alimenta.** O pondering (`PONDER`) especula jogadas que
  podem nunca acontecer -- capturar dali poluiria o corpus com estados que o
  jogo nunca viu.
* **So grava no `/outcome`.** Partida sem desfecho nao entra, mesma regra do
  self-play (*"Sem desfecho -- sem rotulo, fora do dataset"*).
* **Desligavel**: `OPTCG_COLETA_AO_VIVO=0` desliga tudo e volta ao anterior.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent
Q_ALVOS = _RAIZ / "metrics" / "q_alvos.jsonl"

# Buffer por partida: match_id -> lista de linhas capturadas.
_buffer: dict[str, list] = {}


def ligado() -> bool:
    return os.environ.get("OPTCG_COLETA_AO_VIVO", "1") != "0"


def _origem() -> str:
    """Mesma convencao do bloco 820, com sufixo dizendo que veio do SIMULADOR.

    Sem o sufixo, as linhas ao vivo e as de self-play da mesma maquina ficariam
    indistinguiveis -- e sao distribuicoes diferentes (uma adjudicada pelo jogo,
    outra pelo nosso codigo). Separa-las e o que torna possivel medir o efeito
    de cada uma.
    """
    base = os.environ.get("OPTCG_ORIGEM") or socket.gethostname()
    return f"{base}_simulador"


def abre_captura(match) -> None:
    """Liga o captador do motor antes de uma decisao REAL."""
    if not ligado() or match is None:
        return
    try:
        match._q_captura = []
    except Exception:
        pass


def drena(match, match_id: str) -> int:
    """Tira as linhas que o motor produziu nesta decisao e guarda por partida.

    Devolve quantas linhas foram guardadas (0 quando desligado) -- o server usa
    isso so pra telemetria; nada depende do numero.
    """
    if not ligado() or match is None:
        return 0
    try:
        cap = getattr(match, "_q_captura", None) or []
        if cap:
            _buffer.setdefault(match_id or "sem_match", []).extend(cap)
        match._q_captura = None
        return len(cap)
    except Exception:
        return 0


def descarta(match_id: str) -> int:
    """Joga fora o que foi capturado (partida abortada/sem desfecho)."""
    return len(_buffer.pop(match_id or "sem_match", []))


def grava(match_id: str, resultado: str, gen: int = 0) -> dict:
    """Escreve as linhas da partida em `q_alvos.jsonl`, no schema do self-play.

    `resultado` vem do `/outcome`. So 'win'/'loss' entram: 'draw' e 'aborted'
    nao tem desfecho utilizavel, mesma regra do gerador de self-play.
    """
    linhas = _buffer.pop(match_id or "sem_match", [])
    if not ligado():
        return {"gravadas": 0, "motivo": "coleta ao vivo desligada"}
    if resultado not in {"win", "loss"}:
        return {"gravadas": 0, "descartadas": len(linhas),
                "motivo": f"sem desfecho utilizavel ({resultado})"}
    if not linhas:
        return {"gravadas": 0, "motivo": "nada capturado"}

    origem = _origem()
    escritas = 0
    try:
        Q_ALVOS.parent.mkdir(parents=True, exist_ok=True)
        with open(Q_ALVOS, "a", encoding="utf-8") as f:
            for l in linhas:
                feats = l.get("feats")
                alvo = l.get("alvo")
                if not feats or alvo is None:
                    continue
                f.write(json.dumps({
                    "feats": feats,
                    "alvo": float(alvo),
                    "escolhida": bool(l.get("escolhida")),
                    "leader": l.get("leader"),
                    "turn": int(l.get("turn") or 0),
                    "match": 0,
                    "gen": int(gen),
                    "origem": origem,
                }, ensure_ascii=False) + "\n")
                escritas += 1
    except Exception as exc:
        return {"gravadas": escritas, "erro": str(exc)}
    return {"gravadas": escritas, "origem": origem, "arquivo": str(Q_ALVOS)}


def pendentes(match_id: str = "") -> int:
    if match_id:
        return len(_buffer.get(match_id, []))
    return sum(len(v) for v in _buffer.values())
