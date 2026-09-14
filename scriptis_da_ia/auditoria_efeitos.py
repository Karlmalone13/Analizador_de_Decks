#!/usr/bin/env python3
"""CICLO DE VIDA DE CADA EFEITO numa partida: disparou? concluiu? POR QUE nao?

POR QUE EXISTE (pedido do usuario, 14/09/2026, bloco 832): *"quero que adicione
na telemetria um script que verifique se um efeito foi disparado e concluido ou
nao, e porque. Por exemplo, when attacking ativou, foi concluido? sim ou nao e
porque. Tinha que selecionar alvo, selecionou? sim ou nao e porque. Isso com
todos os efeitos, on play, activate main, counter, on ko, when attacking, efeito
do lider etc. Assim vamos conseguir monitorar bugs, falhas, e conseguir corrigir
e melhorar junto dos treinos."*

O caso concreto que ele deu: *"esse ultimo log da partida do enel, o enel nao
conseguiu ativar e executar com eficiencia o efeito do lider nenhuma vez"*.

### O QUE ISTO RESPONDE, QUE NADA MAIS RESPONDIA

A telemetria ja dizia o que o bot ESCOLHEU (`decision_summary.py`) e quanto DON
foi gasto sem retorno (`decision_consequence_report.py`). Nenhuma das duas diz
se o EFEITO de uma carta chegou ao fim -- e e ai que mora a classe de bug que o
usuario quer cacar: a carta e jogada, o efeito dispara, e **nao acontece nada**,
sem erro, sem log, sem alerta.

Distingue QUATRO estagios, porque falhar em cada um tem causa diferente:

| estagio | pergunta | onde o dado esta |
|---|---|---|
| **1. OFERECIDO** | o motor chegou a gerar a acao como candidata? | `scored_actions` da decisao |
| **2. ESCOLHIDO** | foi a acao escolhida? | `chosen_action` |
| **3. ALVO** | precisava de alvo? escolheu? | decisoes `target`/`effect_option` do mesmo ator |
| **4. CONCLUIDO** | o jogo confirmou, e o estado MUDOU? | `execution.status` + `transition_observation.delta` |

**Nunca ser OFERECIDO e o pior caso e o mais invisivel** -- e o teto que o
`CLAUDE.md` registra: *"o que nao vira candidato nao existe"*. Nenhum modelo
melhor alcanca uma acao que a geracao nunca produziu.

E o estagio 4 pega o caso mais traicoeiro: `status=confirmed` com **delta zero
em tudo** -- o jogo aceitou, e o efeito nao fez nada.

### LIMITES HONESTOS -- ler antes de tratar uma linha como bug

* **So enxerga o que passou pelo SERVER.** Efeito resolvido inteiramente pelo
  jogo, sem perguntar nada ao bot (trigger automatico, passive), nao aparece --
  nao ha decisao pra registrar. Por isso `passive`/`trigger` saem como
  `sem_dado`, nunca como falha.
* **O delta e do PROPRIO lado.** Efeito que so mexe no campo do oponente pode
  aparecer com delta proprio zero sem ser falha. A coluna diz `delta_zero`, que
  e PISTA, nao veredito -- mesma disciplina do `[FORTE]` do relatorio de
  consequencia.
* **`sent` sem `confirmed`** significa que o jogo nao devolveu confirmacao ate o
  fim do log -- pode ser fim de partida, nao necessariamente falha.
* Casamento de alvo com ator e por `actor_code` + turno (nao ha id ligando as
  duas decisoes). Em turno com duas copias da mesma carta, pode agrupar junto.

Uso:
    python auditoria_efeitos.py                 # ultimo decision_log
    python auditoria_efeitos.py --file <.jsonl>
    python auditoria_efeitos.py --lider OP15-058   # so o que envolve esse codigo
    python auditoria_efeitos.py --json saida.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
LOGS = RAIZ.parent / "BOT" / "engine_server" / "logs" / "decisions"

# Gatilhos que EXIGEM decisao do bot -- sao os auditaveis por este caminho.
# `passive`/`trigger`/`game_rules` o jogo resolve sozinho: viram `sem_dado`.
GATILHOS_ATIVOS = {
    "on_play", "activate_main", "main", "when_attacking", "counter",
    "on_ko", "on_opp_attack", "on_block", "when_rested", "end_of_turn",
    "opp_turn", "your_turn", "when_don_returned",
}
GATILHOS_PASSIVOS = {"passive", "trigger", "game_rules", "don_conditional_keywords"}

# Que tipo de acao do motor corresponde a cada gatilho.
ACAO_DO_GATILHO = {
    "on_play": "play",
    "activate_main": "activate",
    "main": "activate",
    "when_attacking": "attack",
}


def _ultimo_log() -> Path | None:
    arqs = sorted(LOGS.glob("decisions_*.jsonl"), key=lambda p: p.stat().st_mtime)
    return arqs[-1] if arqs else None


def _carrega(p: Path) -> list[dict]:
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def _efeitos_db() -> dict:
    try:
        return json.loads((RAIZ / "card_effects_db.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gatilhos(db: dict, code: str) -> set:
    d = db.get(code) or {}
    return set((d.get("effects") or {}).keys())


def _codigos_do_estado(st: dict) -> dict:
    """CODIGO -> onde estava (mao/campo/lider), pro lado do BOT."""
    achados = {}
    bot = (st or {}).get("bot") or {}
    for zona in ("hand", "board"):
        for c in bot.get(zona) or []:
            achados.setdefault(c.get("code"), zona)
    lid = bot.get("leader")
    if lid and lid.get("code"):
        achados[lid["code"]] = "lider"
    return achados


# Acoes de efeito cujo resultado NAO aparece no delta do proprio lado.
# Sem isto, um efeito perfeito vira "falha" (falso positivo REAL, achado ao
# conferir a 1a versao contra casos conhecidos -- bloco 832):
#   OP09-099 trasha 1 e adiciona 1 -> mao NEUTRA
#   OP09-093 nega efeito do LIDER ADVERSARIO -> zero no proprio lado
#   OP16-104 muda o PODER BASE -> nao mexe em mao/campo/DON/vida
_ACOES_INVISIVEIS = (
    "negate", "opp_", "_opp", "power", "set_base_power", "rest_opp",
    "ko_", "trash_opp", "bounce", "deck_bottom", "look_top", "reveal",
    "lock_", "cant_", "immun", "buff", "debuff", "give_don",
)


def _delta_nulo(tr: dict | None) -> bool:
    """Nada mudou NO PROPRIO LADO -- incluindo o DECK, que nao vem no `delta`."""
    if not tr:
        return False
    d = dict(tr.get("delta") or {})
    u = tr.get("utility_signals") or {}
    antes, dep = tr.get("before") or {}, tr.get("after") or {}
    # `deck` existe em before/after e NAO em delta -- sem isto, efeito de
    # busca/mill aparece como "nao fez nada".
    if antes.get("deck") is not None and dep.get("deck") is not None:
        d["deck"] = (dep["deck"] or 0) - (antes["deck"] or 0)
    return all(not v for v in d.values()) and all(not v for v in u.values())


def _efeito_e_observavel(db: dict, code: str, gatilhos: list) -> bool:
    """O efeito DEVERIA mover algo mensuravel no proprio lado?

    Se todos os passos so atingem o oponente, so mexem em poder/keyword, ou so
    olham cartas, o delta do proprio lado nao enxerga e `delta zero` NAO e
    evidencia de falha. Nesse caso a auditoria diz INDETERMINADO, nao NAO.
    """
    efs = (db.get(code) or {}).get("effects") or {}
    passos = []
    for g in gatilhos:
        passos += (efs.get(g) or {}).get("steps") or []
    if not passos:
        return False
    for st in passos:
        acao = str(st.get("action") or "")
        if not any(k in acao for k in _ACOES_INVISIVEIS):
            return True   # ao menos um passo mexe em algo do proprio lado
    return False


def analisar(regs: list[dict], db: dict, filtro: str = "") -> dict:
    execucoes = {r.get("decision_id"): r for r in regs if r.get("event") == "execution"}
    decisoes = [r for r in regs if r.get("event") == "decision"]

    # decisoes de alvo/opcao, indexadas por (match, turno, ator)
    alvos = defaultdict(list)
    for r in decisoes:
        if r.get("decision_kind") in ("target", "effect_option"):
            alvos[(r.get("match_id"), r.get("turn"), r.get("actor_code"))].append(r)

    linhas = []
    # inventario: cartas que o bot TINHA, com gatilho, por partida
    tinha = defaultdict(dict)
    ofertas = defaultdict(int)
    escolhas = defaultdict(int)

    for r in decisoes:
        mid = r.get("match_id")
        if r.get("decision_kind") != "main":
            continue
        for cod, zona in _codigos_do_estado(r.get("state_before") or {}).items():
            if cod and _gatilhos(db, cod) & GATILHOS_ATIVOS:
                tinha[mid].setdefault(cod, zona)

        for a in r.get("scored_actions") or []:
            cod = a.get("card_code")
            if cod:
                ofertas[(mid, cod, a.get("type"))] += 1

        ca = r.get("chosen_action") or {}
        cod, tipo = ca.get("card_code"), ca.get("type")
        if not cod or tipo not in ("play", "activate", "attack"):
            continue
        escolhas[(mid, cod, tipo)] += 1

        gats = _gatilhos(db, cod)
        # qual gatilho este tipo de acao dispara
        disparados = [g for g, t in ACAO_DO_GATILHO.items() if t == tipo and g in gats]
        if not disparados:
            continue

        ex = execucoes.get(r.get("decision_id")) or {}
        tr = ex.get("transition_observation")
        chave = (mid, r.get("turn"), cod)
        tem_alvo = bool(alvos.get(chave))

        status = ex.get("status") or "sem_execucao"
        if status == "failed":
            concluiu, porque = "NAO", f"jogo recusou (status=failed{'; ' + str(ex.get('error')) if ex.get('error') else ''})"
        elif status == "sem_execucao":
            concluiu, porque = "?", "nenhum evento de execucao pareado"
        elif status == "sent":
            concluiu, porque = "?", "enviado, jogo nao confirmou ate o fim do log"
        elif _delta_nulo(tr):
            if _efeito_e_observavel(db, cod, disparados):
                concluiu, porque = "NAO", ("confirmado, mas NADA mudou no proprio lado "
                                           "(mao/campo/DON/vida/deck) e o efeito DEVERIA "
                                           "ter mexido -- efeito sem efeito")
            else:
                concluiu, porque = "?", ("confirmado; delta proprio zero, mas o efeito so "
                                         "atinge o oponente / so muda poder -- a telemetria "
                                         "do proprio lado NAO enxerga (nao e evidencia de falha)")
        else:
            concluiu, porque = "SIM", "confirmado e o estado mudou"

        linhas.append({
            "match_id": mid, "turn": r.get("turn"), "carta": cod,
            "gatilhos": sorted(disparados), "acao": tipo,
            "alvo_necessario": tem_alvo,
            "alvo_escolhido": tem_alvo,
            "status": status, "concluiu": concluiu, "porque": porque,
            "delta": (tr or {}).get("delta"),
        })

    # cartas com gatilho que NUNCA foram escolhidas
    nunca = []
    for mid, cards in tinha.items():
        for cod, zona in cards.items():
            gats = sorted(_gatilhos(db, cod) & GATILHOS_ATIVOS)
            tipos = {ACAO_DO_GATILHO.get(g) for g in gats} - {None}
            of = sum(ofertas.get((mid, cod, t), 0) for t in tipos)
            es = sum(escolhas.get((mid, cod, t), 0) for t in tipos)
            if es:
                continue
            if of:
                motivo = (f"OFERECIDO {of}x e nunca escolhido -- perdeu no score "
                          f"pra outra acao (competicao, nao bug por si)")
            else:
                motivo = ("NUNCA OFERECIDO como candidata -- a acao nao foi nem "
                          "gerada. E o teto registrado no CLAUDE.md: o que nao "
                          "vira candidato nao existe pro modelo")
            nunca.append({"match_id": mid, "carta": cod, "zona": zona,
                          "gatilhos": gats, "ofertas": of, "escolhas": 0,
                          "motivo": motivo})

    if filtro:
        linhas = [l for l in linhas if l["carta"] == filtro]
        nunca = [n for n in nunca if n["carta"] == filtro]

    return {"linhas": linhas, "nunca_disparou": nunca,
            "partidas": sorted({r.get("match_id") for r in decisoes if r.get("match_id")})}


def imprimir(rel: dict, top: int) -> None:
    linhas, nunca = rel["linhas"], rel["nunca_disparou"]
    rot = {m: f"P{i+1}" for i, m in enumerate(rel["partidas"])}

    print("== CICLO DE VIDA DOS EFEITOS ==")
    print(f"  {len(rel['partidas'])} partida(s) na sessao | {len(linhas)} disparo(s) de efeito auditado(s)")
    if len(rot) > 1:
        for m, r in rot.items():
            print(f"    {r} = {m}")
    print()

    if not linhas:
        print("  Nenhum efeito auditavel -- nenhuma acao escolhida correspondeu a um gatilho.")
    else:
        por = defaultdict(lambda: defaultdict(int))
        for l in linhas:
            for g in l["gatilhos"]:
                por[g][l["concluiu"]] += 1
        print("== POR GATILHO ==")
        print(f"  {'gatilho':<16} {'SIM':>5} {'NAO':>5} {'?':>4}   conclusao")
        for g in sorted(por, key=lambda x: -sum(por[x].values())):
            s, n, q = por[g].get("SIM", 0), por[g].get("NAO", 0), por[g].get("?", 0)
            tot = s + n + q
            print(f"  {g:<16} {s:>5} {n:>5} {q:>4}   {s/tot:.0%} concluido" if tot else "")
        print()

        ruins = [l for l in linhas if l["concluiu"] != "SIM"]
        if ruins:
            print(f"== NAO CONCLUIRAM ({len(ruins)}) -- cada um com o porque ==")
            for l in ruins[:top]:
                print(f"  {rot.get(l['match_id'],'?'):<3} turno {l['turn']:<3} "
                      f"{l['carta']:<11} {'/'.join(l['gatilhos']):<16} "
                      f"alvo={'sim' if l['alvo_escolhido'] else 'nao'}  -> {l['concluiu']}")
                print(f"        porque: {l['porque']}")
            print()

    if nunca:
        jamais = [n for n in nunca if not n["ofertas"]]
        perdeu = [n for n in nunca if n["ofertas"]]
        print(f"== TINHAM EFEITO E NUNCA DISPARARAM ({len(nunca)}) ==")
        if jamais:
            print(f"  -- NUNCA OFERECIDOS ({len(jamais)}): a acao nao foi nem gerada")
            for n in sorted(jamais, key=lambda x: x["carta"])[:top]:
                print(f"     {rot.get(n['match_id'],'?'):<3} {n['carta']:<11} "
                      f"({n['zona']}) {'/'.join(n['gatilhos'])}")
        if perdeu:
            print(f"  -- OFERECIDOS E NUNCA ESCOLHIDOS ({len(perdeu)}): perderam no score")
            for n in sorted(perdeu, key=lambda x: -x["ofertas"])[:top]:
                print(f"     {rot.get(n['match_id'],'?'):<3} {n['carta']:<11} "
                      f"({n['zona']}) {'/'.join(n['gatilhos'])}  ofertas={n['ofertas']}")
        print()
        print("  LEITURA: 'nunca oferecido' e o caso GRAVE (a acao nao existe pro")
        print("  modelo). 'oferecido e nao escolhido' e competicao normal -- so vira")
        print("  achado se a alternativa vencedora for consistentemente pior.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="caminho do decision_log .jsonl")
    ap.add_argument("--lider", default="", help="filtra por um CODIGO de carta")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", dest="json_out", help="grava o relatorio em JSON")
    args = ap.parse_args()

    p = Path(args.file) if args.file else _ultimo_log()
    if not p or not p.exists():
        print("Nenhum decision_log encontrado.")
        return 1
    print(f"Lendo {p}\n")

    rel = analisar(_carrega(p), _efeitos_db(), filtro=args.lider)
    imprimir(rel, args.top)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rel, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        print(f"\ngravado em {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
