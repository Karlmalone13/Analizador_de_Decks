"""
Audita, em qualquer decision_log, DUAS coisas GENERICAS ligadas ao bloco 900
(achado real do usuario, 26/09/2026, lider Mihawk OP14-020, mas a checagem
NAO e amarrada a essa carta -- ver REGRA da auditoria global do parser):

1. Quando uma habilidade `[Activate: Main]`/`[Activate: ...]` tem custo
   `rest_own_card` ("rest N of your cards"), QUAL zona pagou o custo --
   Stage, personagem de banco ou o proprio lider. O gate corrigido no
   bloco 900 fazia o Stage nunca contar como candidato; este script serve
   pra provar, em partidas FUTURAS, se o Stage passa a ser usado quando
   esta em campo (o motor decide isso -- aqui so se MEDE, nunca se decide).
2. Se essa ativacao aconteceu ANTES ou DEPOIS do primeiro ataque do MESMO
   turno pelo mesmo lado -- o sequenciamento que o usuario apontou.

Detecta o CUSTO pela FORMA (tipo `rest_own_card` no banco de efeitos), nao
pelo codigo da carta -- qualquer lider/carta com esse mesmo custo entra
automaticamente. A zona que pagou o custo e lida comparando state_before
x state_after (quem virou `rested=True` que nao estava) -- nao reimplementa
a escolha do motor (REGRA_SEM_DUPLICACAO), so observa o que ja aconteceu.

Uso:
    python audita_custo_stage_sequenciamento.py [--decision-log PATH]
    (default: JSONL mais recente de BOT/engine_server/logs/decisions/)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from optcg_engine.decision_engine import get_card_effects  # noqa: E402


def _tem_custo_rest_own_card(card_code: str) -> bool:
    effects = get_card_effects(card_code)
    for block in effects.values():
        if not isinstance(block, dict):
            continue
        for cost in block.get("costs", []) or []:
            if isinstance(cost, dict) and cost.get("type") == "rest_own_card":
                return True
    return False


def _uids_rested(estado: dict | None, lado: str) -> set:
    """`board` e uma LISTA; `stage` e `leader` sao objetos UNICOS (ou None)
    -- schema real do decision_log (confirmado 26/09), diferente da lista
    homogenea que seria natural supor."""
    if not estado:
        return set()
    bot = estado.get(lado) or {}
    out = set()
    for c in bot.get("board") or []:
        if c.get("rested"):
            out.add(c.get("deckUniqueId"))
    stage = bot.get("stage")
    if stage and stage.get("rested"):
        out.add("stage")
    leader = bot.get("leader")
    if leader and leader.get("rested"):
        out.add("leader")
    return out


def _zona_do_uid(estado: dict | None, lado: str, uid) -> str:
    if uid == "leader":
        return "own_leader"
    if uid == "stage":
        return "own_stage"
    bot = (estado or {}).get(lado) or {}
    for c in bot.get("board") or []:
        if c.get("deckUniqueId") == uid:
            return "own_board"
    return "desconhecida"


def _latest_log() -> Path:
    d = REPO.parent / "BOT" / "engine_server" / "logs" / "decisions"
    candidatos = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not candidatos:
        raise FileNotFoundError(f"nenhum decision log em {d}")
    return candidatos[-1]


def auditar(path: Path) -> None:
    linhas = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    decisoes = [d for d in linhas if d.get("event") == "decision"]

    # primeiro ataque de cada (match_id, turn, lado) -- pra saber se a
    # ativacao aconteceu antes ou depois, na MESMA ordem em que o server
    # decidiu (a ordem no arquivo E a ordem real das decisoes).
    primeiro_ataque: dict[tuple, int] = {}
    for i, d in enumerate(decisoes):
        ca = d.get("chosen_action") or {}
        if ca.get("type") != "attack":
            continue
        chave = (d.get("match_id"), d.get("turn"))
        primeiro_ataque.setdefault(chave, i)

    achados = []
    for i, d in enumerate(decisoes):
        ca = d.get("chosen_action") or {}
        if ca.get("type") != "activate" or not ca.get("card_code"):
            continue
        if not _tem_custo_rest_own_card(ca["card_code"]):
            continue
        antes = d.get("state_before") or {}
        # state_after nao vem no evento 'decision' -- vem do(s) evento(s)
        # 'execution' do MESMO decision_id (mesmo padrao usado no resto do
        # projeto pra medir consequencia). Uma ativacao com custo produz
        # MAIS DE UM 'execution' (confirmacao do jogo chega em ticks
        # separados -- achado ao testar, 26/09): o custo so aparece pago no
        # ULTIMO, nunca no primeiro.
        execs = [e for e in linhas if e.get("event") == "execution"
                 and e.get("decision_id") == d.get("decision_id")]
        estado_depois = execs[-1].get("state_after") if execs else None

        rested_antes = _uids_rested(antes, "bot")
        rested_depois = _uids_rested(estado_depois, "bot")
        novos = rested_depois - rested_antes
        zona = _zona_do_uid(antes, "bot", next(iter(novos))) if novos else "nao_identificada"

        chave = (d.get("match_id"), d.get("turn"))
        idx_ataque = primeiro_ataque.get(chave)
        if idx_ataque is None:
            sequencia = "sem_ataque_no_turno"
        elif idx_ataque < i:
            sequencia = "depois_do_ataque"
        else:
            sequencia = "antes_do_ataque"

        achados.append({
            "match_id": d.get("match_id"), "turn": d.get("turn"),
            "card_code": ca["card_code"], "zona_do_custo": zona,
            "sequenciamento": sequencia,
        })

    if not achados:
        print("Nenhuma ativacao com custo rest_own_card neste log.")
        return

    print(f"{len(achados)} ativacao(oes) com custo rest_own_card em {path.name}:\n")
    for a in achados:
        print(f"  match={a['match_id'][:8]} turn={a['turn']:<3} {a['card_code']:<10} "
              f"custo pago por: {a['zona_do_custo']:<12} sequencia: {a['sequenciamento']}")

    zonas = [a["zona_do_custo"] for a in achados]
    print(f"\n  Stage usado como custo: {zonas.count('own_stage')}/{len(achados)}")
    print(f"  Personagem usado como custo: {zonas.count('own_board')}/{len(achados)}")
    print(f"  Lider usado como custo: {zonas.count('own_leader')}/{len(achados)}")
    seqs = [a["sequenciamento"] for a in achados]
    print(f"  Ativou ANTES do 1o ataque do turno: {seqs.count('antes_do_ataque')}/{len(achados)}")
    print(f"  Ativou DEPOIS do 1o ataque do turno: {seqs.count('depois_do_ataque')}/{len(achados)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision-log", type=Path, default=None)
    args = ap.parse_args()
    auditar(args.decision_log or _latest_log())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
