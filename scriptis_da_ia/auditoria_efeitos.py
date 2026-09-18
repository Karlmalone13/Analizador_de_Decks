#!/usr/bin/env python3
"""CICLO DE VIDA DE CADA EFEITO numa partida: disparou? concluiu? POR QUE nao?

POR QUE EXISTE (pedido do usuario, 14/09/2026, blocos 832-835): *"quero que
adicione na telemetria um script que verifique se um efeito foi disparado e
concluido ou nao, e porque. When attacking ativou, foi concluido? Tinha que
selecionar alvo, selecionou? Isso com todos os efeitos -- on play, activate
main, counter, on ko, when attacking, efeito do lider etc. Assim vamos
conseguir monitorar bugs, falhas, e corrigir junto dos treinos."*

O caso concreto que ele deu: *"o enel nao conseguiu ativar e executar com
eficiencia o efeito do lider nenhuma vez"* -- reproduzido pela ferramenta em
duas partidas independentes (bloco 836).

### O QUE ISTO RESPONDE, QUE NADA MAIS RESPONDIA

`decision_summary.py` diz o que o bot ESCOLHEU; `decision_consequence_report.py`
diz quanto DON foi gasto sem retorno. Nenhuma das duas diz se o EFEITO chegou ao
fim -- e e ai que mora a classe de bug que o usuario quer cacar: a carta e
jogada, o efeito dispara, e **nao acontece nada**, sem erro, sem log, sem alerta.

Distingue QUATRO estagios, porque falhar em cada um tem causa diferente:

| estagio | pergunta | onde o dado esta |
|---|---|---|
| **1. OFERECIDO** | o motor gerou a acao como candidata? | `scored_actions` |
| **2. ESCOLHIDO** | foi escolhida? | `chosen_action` |
| **3. ALVO** | precisava de alvo? selecionou? | `target`/`effect_option` do mesmo ator |
| **4. CONCLUIDO** | o jogo confirmou E o estado mudou? | `execution.status` + `transition_observation` |

**Nunca ser OFERECIDO e o pior caso e o mais invisivel** -- e o teto que o
`CLAUDE.md` registra: *"o que nao vira candidato nao existe"*.

E o estagio 4 pega o mais traicoeiro: `status=confirmed` com **delta zero** -- o
jogo aceitou e o efeito nao fez nada. Foi assim que o Enel apareceu.

### O QUE COBRE -- as TRES familias

| familia | de onde vem | criterio de "concluiu" |
|---|---|---|
| `on_play`, `activate_main`, `main`, `when_attacking` | decisao `main` | `execution.status` + delta |
| `counter`, `blocker`, `trigger`, opcional, reacao | decisao `defense` | foi ACEITO |
| `on_ko`, `on_opp_attack`, `your_turn`/`opp_turn`, `when_rested`... | `target`/`effect_option` por `actor_code` | respondeu a pergunta do jogo |

As duas ultimas ficaram de fora das primeiras versoes, e o usuario pegou as
duas: *"nao e so on play, eu especifiquei isso"* (as 5 de `defense` -- eram 338
decisoes nao auditadas) e *"confira no nosso projeto porque tem mais efeitos,
'on ko' etc"* (o banco tem 30 familias de gatilho; `on_ko` sozinho sao 168
cartas, e o mapa tinha 4).

So ficam de fora `passive` e `game_rules`: o jogo resolve sem perguntar nada ao
bot, entao nao ha decisao pra auditar -- e **nunca sao contados como falha**.

### LIMITES HONESTOS -- ler antes de tratar uma linha como bug

* **So enxerga o que passou pelo SERVER.** Efeito que o jogo resolve sozinho nao
  aparece.
* **O delta e do PROPRIO lado.** Efeito que so mexe no oponente ou so muda poder
  da delta zero sem ser falha -- por isso a expectativa sai dos PASSOS PARSEADOS
  (`_efeito_e_observavel`) e esses casos saem como `?`, nunca como `NAO`. Sem
  isso ha falso positivo REAL: a 1a versao acusava OP09-099 (trasha 1 e adiciona
  1 -> mao neutra), OP09-093 (nega efeito do lider adversario) e OP16-104 (muda
  poder base), e dizia 18% quando o numero honesto era 45%.
* **`sent` sem `confirmed`** pode ser fim de partida, nao necessariamente falha.
* Casamento alvo-ator e por `actor_code` + turno (nao ha id ligando as duas
  decisoes): duas copias da mesma carta no mesmo turno agrupam.
* Na DEFESA nao ha `execution` pareado -- a resposta E o ato. "Recusou" e
  ESCOLHA do bot, nao falha por si; vira achado quando ele recusa TENDO opcao.

Uso:
    python auditoria_efeitos.py                    # ultimo decision_log
    python auditoria_efeitos.py --file <.jsonl>
    python auditoria_efeitos.py --codigo OP15-058  # UMA carta (qualquer uma)
    python auditoria_efeitos.py --json saida.json

NAO e auditoria "do lider": cobre QUALQUER carta com efeito -- personagem,
evento, stage e lider. Na 1a medicao, 50 dos 76 disparos eram `on_play` de
PERSONAGEM e so 4 do lider.

Roda AUTOMATICO a cada `/outcome` (ligada no `collect_latest_match.py`, bloco
833): grava `metrics/live_runs/efeitos_<ts>.json`/`.txt` e alerta no stdout.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
LOGS = RAIZ.parent / "BOT" / "engine_server" / "logs" / "decisions"

# O JSONL do servidor sabe o que o motor escolheu; o BepInEx sabe se o
# OPTCGSim aceitou o clique. Eles ainda nao compartilham um id por clique, por
# isso esta leitura e deliberadamente apresentada como evidencia do PLUGIN da
# sessao, nunca como uma atribuicao exata a uma unica decision_id.
_PLUGIN_TARGET = re.compile(
    r"\[Bot\] alvo de efeito: (?P<target>.+?) \(uid=.*?, actor=(?P<actor>.*?), "
    r"faltavam=(?P<before>-?\d+) -> faltam=(?P<after>-?\d+)\)"
)
_PLUGIN_REJECTED = re.compile(r"\[Bot\] clique em .+? NAO consumiu alvo")
_PLUGIN_MISSING = re.compile(r"\[Bot\] alvo de efeito NAO ENCONTRADO .*?actor=(?P<actor>[^)]+)")
_PLUGIN_CANCEL = re.compile(r"\[Bot\] efeito pendente sem alvo viavel .+?actor=(?P<actor>[^,)]*)")

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


def _auditar_plugin(path: Path | None, atores: set[str]) -> dict | None:
    """Resume a aceitacao de cliques no OPTCGSim a partir do LogOutput.

    A linha de recusa nao repete actor/decision_id; ela vem imediatamente apos
    a tentativa correspondente. Mantemos essa associacao local e restringimos
    aos atores vistos no JSONL, quando houver, para nao misturar partida antiga
    acumulada no LogOutput com a auditoria atual.
    """
    if not path or not path.exists():
        return None
    tentativas = aceitos = recusados = nao_encontrados = cancelados = 0
    por_ator = defaultdict(lambda: {"tentativas": 0, "aceitos": 0,
                                    "recusados": 0, "nao_encontrados": 0,
                                    "cancelados": 0})
    ultimo_ator = ""
    for linha in path.read_text(encoding="utf-8", errors="replace").splitlines():
        achou = _PLUGIN_TARGET.search(linha)
        if achou:
            ator = achou.group("actor").strip()
            ultimo_ator = ator
            if atores and ator not in atores:
                continue
            tentativas += 1
            por_ator[ator]["tentativas"] += 1
            if int(achou.group("after")) < int(achou.group("before")):
                aceitos += 1
                por_ator[ator]["aceitos"] += 1
            continue
        if _PLUGIN_REJECTED.search(linha) and ultimo_ator and (not atores or ultimo_ator in atores):
            recusados += 1
            por_ator[ultimo_ator]["recusados"] += 1
            continue
        achou = _PLUGIN_MISSING.search(linha)
        if achou:
            ator = achou.group("actor").strip()
            if not atores or ator in atores:
                nao_encontrados += 1
                por_ator[ator]["nao_encontrados"] += 1
            continue
        achou = _PLUGIN_CANCEL.search(linha)
        if achou:
            ator = achou.group("actor").strip()
            if not atores or ator in atores:
                cancelados += 1
                por_ator[ator]["cancelados"] += 1
    return {
        "fonte": str(path), "tentativas": tentativas, "aceitos": aceitos,
        "recusados": recusados, "nao_encontrados": nao_encontrados,
        "cancelados_sem_alvo": cancelados,
        "por_ator": dict(sorted(por_ator.items())),
        "limite": ("LogOutput nao traz decision_id: os totais confirmam a falha "
                   "de execucao da sessao, mas nao atribuem cada clique a uma "
                   "decisao individual."),
    }


def _gatilhos(db: dict, code: str) -> set:
    d = db.get(code) or {}
    return set((d.get("effects") or {}).keys())


# Rotulo entre colchetes no TEXTO OFICIAL -> chave do banco de efeitos.
# Lista branca de proposito: colchete no OPTCG tambem marca keyword
# ([Rush], [Blocker], [Banish]) e condicao ([DON!! x1], [Once Per Turn]),
# que NAO sao gatilhos. O que nao esta aqui e ignorado.
_ROTULO_PARA_GATILHO = {
    "on play": "on_play",
    "when attacking": "when_attacking",
    "activate: main": "activate_main",
    "main": "main",
    "counter": "counter",
    "on k.o.": "on_ko",
    "on your opponent's attack": "on_opp_attack",
    "on block": "on_block",
    "when rested": "when_rested",
    "end of your turn": "end_of_turn",
    "trigger": "trigger",
}
# [Your Turn] / [Opponent's Turn] NUNCA declaram gatilho sozinhos: quando a
# linha e "[Your Turn] [Once Per Turn] When a DON!! card ... is returned",
# o gatilho de verdade esta na PROSA e o parser ja o guarda numa chave mais
# especifica (`when_don_returned`, `on_opp_event_activated`,
# `on_own_effect_removes_char`...). Medido: tratando-os como gatilho, 42 das
# 54 acusacoes eram falso positivo -- o banco estava certo e mais preciso
# que a etiqueta. Por isso ficam FORA do mapa e entram so como qualificador.
_COLCHETE = re.compile(r"\[([^\]]+)\]")
# Colchetes ENCOSTADOS no inicio da linha: e onde um gatilho e DECLARADO.
# "[On Play] [Once Per Turn] K.O. ..." -> pega os dois rotulos e para no 'K'.
_PREFIXO = re.compile(r"^\s*((?:\[[^\]]+\]\s*)+)")
# Rotulos que so QUALIFICAM quando (ou sob que condicao) outro gatilho vale.
# "[Your Turn] [On Play] ..." e um on_play restrito ao seu turno, nao dois
# gatilhos -- o parser dobra isso dentro do proprio on_play. So contam como
# gatilho proprio quando aparecem SOZINHOS no prefixo.
_QUALIFICADORES: set = set()


def _texto_das_cartas() -> dict:
    """CODIGO -> texto oficial. Fonte do que a carta DIZ que faz."""
    import csv
    try:
        with (RAIZ / "cards_rows.csv").open(encoding="utf-8") as f:
            return {r["id"]: (r.get("card_text") or "") for r in csv.DictReader(f)}
    except Exception:
        return {}


def _gatilhos_do_texto(texto: str) -> set:
    """Gatilhos que a carta DECLARA, lidos do texto oficial.

    So conta colchete no INICIO da linha, que e onde um gatilho e declarado.
    Colchete no meio da frase e referencia a keyword, nao declaracao -- sem
    isso, "trash 1 card with a [Trigger] from your hand" virava um gatilho
    `trigger` inexistente (15 falsos positivos medidos no banco).

    Precisao importa mais que cobertura aqui: uma checagem barulhenta e uma
    checagem que ninguem le, e ai ela nao serve pra nada.
    """
    achados = set()
    for linha in (texto or "").splitlines():
        pref = _PREFIXO.match(linha)
        if not pref:
            continue
        rotulos = {
            _ROTULO_PARA_GATILHO[r.strip().lower()]
            for r in _COLCHETE.findall(pref.group(1))
            if r.strip().lower() in _ROTULO_PARA_GATILHO
        }
        proprios = rotulos - _QUALIFICADORES
        # qualificador so vira gatilho quando nao ha gatilho proprio na linha
        achados |= proprios or rotulos
    return achados


def _keywords_so_em_combate() -> frozenset:
    """Vem do MOTOR, nao de uma copia local.

    Uma segunda lista aqui divergiria da do motor no primeiro keyword novo,
    e a auditoria passaria a mentir em silencio. Se o import falhar, a
    checagem se desliga (conjunto vazio) em vez de usar um palpite.
    """
    try:
        from optcg_engine.decision_engine import _KEYWORD_SO_EM_COMBATE
        return _KEYWORD_SO_EM_COMBATE
    except Exception:
        return frozenset()


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


def _detalhe_do_alvo(decisoes_alvo: list) -> dict | None:
    """QUAL alvo o bot escolheu, de que zona, e POR QUE (o rank que decidiu).

    Pedido do usuario (17/09/2026): *"se era para dar alvo, qual alvo ele
    escolheu e porque, em qual turno"*. O dado sempre esteve no
    `decision_log` e nao era lido: cada candidato traz `card_code`, `zone`,
    `eligible`, `rank` e `rank_key` -- o `rank_key` E a razao da escolha, e a
    chave de ordenacao que o motor usou.

    Medido antes de construir: **461 de 461** decisoes de alvo ao vivo
    escolheram algo. "Escolher nenhum alvo" nao acontece neste caminho, entao
    `alvo vazio` nao e um desfecho a esperar aqui.
    """
    # ATRIBUICAO CORRIGIDA (bloco 846): pegar a PRIMEIRA decisao do turno estava
    # errado. Um mesmo (ator, turno) pode ter VARIAS decisoes de alvo -- anexar
    # DON pro ataque, custo, e o alvo do efeito -- e a primeira costuma ser a de
    # DON. Isso produzia "suspeitos" falsos: OP15-061 (`debuff_power`) aparecia
    # mirando `own_don_rested` quando nas outras decisoes do MESMO turno ele
    # mirava `opp_leader`/`opp_board` corretamente.
    #
    # Agora devolve TODAS as decisoes do turno e marca qual delas e COERENTE com
    # o lado que o efeito deveria atingir. Sem id ligando decisao a passo, isto
    # e o mais honesto: mostrar o conjunto, nao fingir que ha uma so.
    todas = []
    for d in decisoes_alvo or []:
        ca = d.get("chosen_action") or {}
        ids = ca.get("ordered_ids") or []
        cands = d.get("scored_actions") or []
        if not ids or not cands:
            continue
        por_id = {c.get("target_id"): c for c in cands}
        esc = por_id.get(ids[0]) or {}
        todas.append({"carta": esc.get("card_code"), "zona": esc.get("zone"),
                      "rank": esc.get("rank"), "n": len(cands)})
        outros = [c for c in cands if c.get("target_id") != ids[0]]
        # Ordena do MAIS PROXIMO pro mais distante: pra entender "por que este
        # e nao aquele", quem importa e o VICE, nao o pior da lista. A 1a
        # versao ordenava ao contrario e mostrava os 3 piores candidatos, que
        # nao explicam nada.
        outros.sort(key=lambda c: (c.get("rank") if c.get("rank") is not None else 10**6))
        primeiro = {
            "carta": esc.get("card_code"), "zona": esc.get("zone"),
            "rank": esc.get("rank"), "rank_key": esc.get("rank_key"),
            "n_candidatos": len(cands),
            "descartados": [{"carta": c.get("card_code"), "zona": c.get("zone"),
                             "rank": c.get("rank")} for c in outros[:3]],
            "ordem_completa": len(ids),
            "todas_do_turno": todas,
        }
        break
    else:
        return None
    primeiro["todas_do_turno"] = todas
    return primeiro


def analisar(regs: list[dict], db: dict, filtro: str = "",
             bepinex_log: Path | None = None) -> dict:
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

    # CHECAGEM NOVA 1 -- O PONTO CEGO DA PROPRIA AUDITORIA.
    # Tudo acima percorre os efeitos que estao NO BANCO. Uma carta cujo
    # gatilho nunca foi parseado nao aparece como "nao concluido" nem como
    # "nunca oferecido": ela simplesmente NAO EXISTE pra esta ferramenta.
    # E o pior caso possivel (a acao nao existe pro modelo) caindo justo no
    # buraco de quem deveria acha-lo. Achado real 18/09/2026: Loki OP17-119
    # entrou em campo 2x sem executar nada e a auditoria deu a partida como
    # 100% verde. Aqui a comparacao e contra o TEXTO OFICIAL, nao contra o
    # banco -- e a unica fonte independente do parser.
    textos = _texto_das_cartas()
    texto_sem_banco = {}

    for r in decisoes:
        mid = r.get("match_id")
        if r.get("decision_kind") != "main":
            continue
        for cod, zona in _codigos_do_estado(r.get("state_before") or {}).items():
            if cod and _gatilhos(db, cod) & GATILHOS_ATIVOS:
                tinha[mid].setdefault(cod, zona)
            if cod and cod in textos:
                faltando = (_gatilhos_do_texto(textos[cod])
                            - _gatilhos(db, cod))
                if faltando:
                    texto_sem_banco.setdefault(cod, {
                        "match_id": mid, "zona": zona,
                        "gatilhos_no_texto_e_fora_do_banco": sorted(faltando),
                        "gatilhos_no_banco": sorted(_gatilhos(db, cod)),
                        "texto": " / ".join(textos[cod].splitlines())[:160],
                    })

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
        # EVENT jogado da mao resolve o `main` -- o mapa acima liga `main` a
        # 'activate', que e o caminho de Character/Stage ja em campo. Sem
        # esta linha, TODO Event jogado ficava fora do ciclo de vida:
        # medido, 285 Events do banco tem `main` e nao tem `on_play`, ou
        # seja, a auditoria era cega pra todos eles. Foi por aqui que o
        # OP17-055 do turno 1 passou sem ser visto (achado 18/09/2026).
        if (tipo == "play" and "main" in gats
                and (db.get(cod) or {}).get("type") == "EVENT"
                and "main" not in disparados):
            disparados.append("main")
        if not disparados:
            continue

        ex = execucoes.get(r.get("decision_id")) or {}
        tr = ex.get("transition_observation")
        chave = (mid, r.get("turn"), cod)
        tem_alvo = bool(alvos.get(chave))

        det_alvo = _detalhe_do_alvo(alvos.get(chave))
        status = ex.get("status") or "sem_execucao"
        if status == "failed":
            concluiu = "NAO"
            desfecho = "ATIVADO E CANCELADO PELO JOGO"
            porque = f"jogo recusou (status=failed{'; ' + str(ex.get('error')) if ex.get('error') else ''})"
        elif status == "sem_execucao":
            desfecho = "SEM EXECUCAO PAREADA"
            concluiu, porque = "?", "nenhum evento de execucao pareado"
        elif status == "sent":
            desfecho = "ENVIADO, SEM CONFIRMACAO"
            concluiu, porque = "?", "enviado, jogo nao confirmou ate o fim do log"
        elif _delta_nulo(tr):
            if _efeito_e_observavel(db, cod, disparados):
                desfecho = "ATIVADO E NAO SURTIU EFEITO"
                concluiu, porque = "NAO", ("confirmado, mas NADA mudou no proprio lado "
                                           "(mao/campo/DON/vida/deck) e o efeito DEVERIA "
                                           "ter mexido -- efeito sem efeito")
            else:
                desfecho = "CONCLUIU (efeito invisivel do proprio lado)"
                concluiu, porque = "?", ("confirmado; delta proprio zero, mas o efeito so "
                                         "atinge o oponente / so muda poder -- a telemetria "
                                         "do proprio lado NAO enxerga (nao e evidencia de falha)")
        else:
            desfecho = "ATIVADO E CONCLUIDO"
            concluiu, porque = "SIM", "confirmado e o estado mudou"

        # CHECAGEM NOVA 2 -- "CONCLUIU" e "VALEU ALGUMA COISA" sao perguntas
        # DIFERENTES, e ate aqui so a primeira era feita. Um efeito pode
        # chegar ao fim perfeitamente e ainda assim ter valor NULO por
        # regra do jogo -- e ai a auditoria dava verde.
        # Achado real 18/09/2026: no turno 1 o bot gastou OP17-055 (custo 0)
        # e restou o unico DON pra dar [Unblockable] "during this turn", num
        # turno em que atacar e impossivel (`can_attack_this_turn(): turn>1`).
        # Concluiu, sim. Valeu zero, com CERTEZA, nao com suspeita.
        # So entra aqui o que e demonstravel pela regra; "jogada fraca" e
        # julgamento de valor e NAO pertence a esta ferramenta.
        nulo = None
        turno_r = r.get("turn")
        if isinstance(turno_r, int) and turno_r == 1:
            combate = _keywords_so_em_combate()
            for g in disparados:
                for passo in (((db.get(cod) or {}).get("effects") or {})
                              .get(g, {}).get("steps") or []):
                    if (passo.get("action") in combate
                            and passo.get("duration") == "this_turn"):
                        nulo = (f"{passo.get('action')} dura so este turno e no "
                                f"turno 1 nao existe combate -- efeito nulo por "
                                f"regra, mesmo tendo concluido")
                        break
                if nulo:
                    break

        linhas.append({
            "match_id": mid, "turn": r.get("turn"), "carta": cod,
            "gatilhos": sorted(disparados), "acao": tipo,
            "alvo_necessario": tem_alvo,
            "alvo_escolhido": tem_alvo,
            "status": status, "concluiu": concluiu, "porque": porque,
            "desfecho": desfecho, "alvo": det_alvo,
            "delta": (tr or {}).get("delta"),
            "valor_nulo_por_regra": nulo,
        })

    # ── DEFESA: counter / blocker / trigger / opcional / reacao ──────────
    # Nao vem de decisao `main` -- por isso ficaram de fora da 1a versao
    # (corrigido a pedido do usuario). Aqui nao existe `execution` pareado: a
    # resposta E o ato, entao o criterio de "concluiu" e `accepted`.
    defesa = []
    for r in decisoes:
        if r.get("decision_kind") != "defense":
            continue
        ca = r.get("chosen_action") or {}
        # ERRO DE MEDICAO CORRIGIDO (17/09/2026, bloco 837): eu usava
        # `accepted` pra TODAS as fases, mas ele so e preenchido em
        # optional/trigger/reaction. Em `counter` a resposta e `counter_ids`
        # e em `blocker` e `blocker_id` -- com `accepted` os dois davam SEMPRE
        # zero, e eu reportei "o bot nunca se defende" como achado grave, duas
        # vezes. O motor de fato contra-atacava: o proprio stdout do server
        # dizia `[DEF] counter ... -> 4 cartas`.
        fase_ = fase = r.get("phase") or "?"
        if fase_ == "counter":
            aceito = bool(ca.get("counter_ids"))
        elif fase_ == "blocker":
            aceito = bool(ca.get("blocker_id"))
        else:
            aceito = bool(ca.get("accepted"))
        opts = r.get("scored_actions") or []
        # opcoes REAIS (fora as de recusar): sao o que estava disponivel
        reais = [o for o in opts
                 if o.get("type") not in ("no_counter", "no_blocker", "decline")]
        cartas = sorted({o.get("card_code") for o in reais if o.get("card_code")})

        if aceito:
            concluiu, porque = "SIM", f"{fase} ACEITO e aplicado"
        elif reais:
            concluiu, porque = "NAO", (
                f"havia {len(reais)} opcao(oes) de {fase} disponivel(is) "
                f"{('(' + ', '.join(cartas) + ') ') if cartas else ''}"
                f"e o bot RECUSOU -- escolha, nao falha por si")
        else:
            concluiu, porque = "?", (
                f"nenhuma opcao de {fase} disponivel -- nada a concluir "
                f"(nao e falha)")

        defesa.append({
            "match_id": r.get("match_id"), "turn": r.get("turn"),
            "fase": fase, "ator": r.get("actor_code"),
            "opcoes": len(reais), "cartas": cartas,
            "aceito": aceito, "concluiu": concluiu, "porque": porque,
        })

    # ── REATIVOS: on_ko, on_opp_attack, your_turn/opp_turn, end_of_turn... ──
    # Nao vem de `main` nem de `defense`: o JOGO dispara e pergunta algo ao bot.
    # Aparecem como decisao `target`/`effect_option` (ou fase reaction/optional/
    # trigger) com o `actor_code` da carta dona do efeito. Achado ao conferir a
    # cobertura a pedido do usuario (*"tem mais efeitos, on ko etc"*): OP16-109
    # e OP14-111 (on_ko) geraram 9x e 8x, OP11-041 (on_opp_attack) 45x.
    REATIVOS = {"on_ko", "on_opp_attack", "your_turn", "opp_turn", "end_of_turn",
                "when_rested", "on_block", "when_don_returned", "on_damage_to_life",
                "on_own_char_ko", "on_any_char_ko", "on_opp_char_ko",
                "on_own_char_played", "on_opp_char_played", "on_hand_card_trashed",
                "on_own_event_activated", "on_opp_event_activated",
                "on_own_effect_removes_char", "leader_battle_reactive",
                "on_don_given", "when_damage_or_own_char_ko", "trigger"}
    reativos = []
    for r in decisoes:
        ator = r.get("actor_code")
        if not ator:
            continue
        ehdef = r.get("decision_kind") == "defense"
        if r.get("decision_kind") not in ("target", "effect_option") and            r.get("phase") not in ("reaction", "optional", "trigger"):
            continue
        gats = sorted(_gatilhos(db, ator) & REATIVOS)
        if not gats:
            continue
        ca = r.get("chosen_action") or {}
        if ehdef:
            ok = bool(ca.get("accepted"))
            porque = ("aceito e aplicado" if ok else
                      "o bot RECUSOU o efeito reativo (escolha, nao falha por si)")
        else:
            ok = bool(ca.get("ordered_ids") or ca.get("option_index") is not None)
            porque = ("o jogo pediu escolha e o bot ESCOLHEU" if ok else
                      "o jogo pediu escolha e o bot NAO escolheu nada")
        reativos.append({"match_id": r.get("match_id"), "turn": r.get("turn"),
                         "ator": ator, "gatilhos": gats,
                         "tipo": r.get("decision_kind"), "fase": r.get("phase"),
                         "ok": ok, "porque": porque})

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

    if filtro:
        defesa = [d for d in defesa if filtro in (d["cartas"] or []) or d["ator"] == filtro]

    if filtro:
        reativos = [x for x in reativos if x["ator"] == filtro]

    atores = {r.get("actor_code") for r in decisoes if r.get("actor_code")}
    return {"linhas": linhas, "defesa": defesa, "reativos": reativos,
            "nunca_disparou": nunca,
            "texto_sem_banco": texto_sem_banco,
            "valor_nulo": [l for l in linhas if l.get("valor_nulo_por_regra")],
            "partidas": sorted({r.get("match_id") for r in decisoes if r.get("match_id")}),
            "execucao_plugin": _auditar_plugin(bepinex_log, atores)}


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

    plugin = rel.get("execucao_plugin")
    if plugin:
        print("== EXECUCAO NO OPTCGSIM (BepInEx) ==")
        print(f"  tentativas de alvo: {plugin['tentativas']} | aceitas: {plugin['aceitos']} | "
              f"recusadas: {plugin['recusados']} | nao encontradas: {plugin['nao_encontrados']} | "
              f"canceladas: {plugin['cancelados_sem_alvo']}")
        if plugin["recusados"]:
            taxa = plugin["recusados"] / max(plugin["tentativas"], 1)
            print(f"  ALERTA: {taxa:.0%} das tentativas de alvo foram recusadas pelo jogo; "
                  "o motor decidiu, mas o plugin nao conseguiu executar.")
        for ator, dados in plugin["por_ator"].items():
            if dados["recusados"] or dados["nao_encontrados"] or dados["cancelados"]:
                print(f"    {ator or '?'}: {dados['recusados']} recusada(s), "
                      f"{dados['nao_encontrados']} nao encontrada(s), "
                      f"{dados['cancelados']} cancelamento(s)")
        print(f"  limite: {plugin['limite']}")
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

    # ── DETALHE turno a turno: desfecho + QUAL alvo e POR QUE ───────────
    if linhas:
        print("== CADA DISPARO, TURNO A TURNO ==")
        print("   desfecho | se deu alvo: QUAL carta, de que zona, e o RANK que")
        print("   decidiu (o `rank_key` e a chave de ordenacao do motor).")
        for l in sorted(linhas, key=lambda x: (str(x.get("match_id")), x.get("turn") or 0))[:top * 2]:
            a = l.get("alvo")
            print(f"  {rot.get(l.get('match_id') or 'legacy','?'):<3} "
                  f"turno {l['turn']:<3} {l['carta']:<11} "
                  f"{'/'.join(l['gatilhos']):<16} {l.get('desfecho','?')}")
            if a:
                dk = ', '.join(f"{d['carta']}(r{d['rank']})" for d in a.get("descartados") or [])
                print(f"        ALVO: {a['carta']} em {a['zona']} "
                      f"| rank {a['rank']} de {a['n_candidatos']} candidatos "
                      f"| chave {a['rank_key']}")
                if dk:
                    print(f"        vice: {dk}")
            elif l.get("alvo_necessario"):
                print("        ALVO: houve decisao de alvo, mas sem detalhe legivel")
            if l.get("valor_nulo_por_regra"):
                print(f"        !! VALOR NULO: {l['valor_nulo_por_regra']}")
        print()

    defesa = rel.get("defesa") or []
    if defesa:
        print("== DEFESA E EFEITOS DE RESPOSTA (counter / blocker / trigger / opcional) ==")
        print("   Aqui nao ha `execution` pareado -- a RESPOSTA e o ato, entao o")
        print("   criterio e se foi ACEITO. 'Recusou' e ESCOLHA do bot, nao falha;")
        print("   vira achado se ele recusa tendo opcao boa, que e onde a metrica")
        print("   'quais cartas de counter' (18,5%) esta ruim.")
        agg = defaultdict(lambda: defaultdict(int))
        for d in defesa:
            agg[d["fase"]][d["concluiu"]] += 1
        print(f"  {'fase':<12} {'ACEITOU':>8} {'RECUSOU':>8} {'sem opcao':>10}")
        for f in sorted(agg, key=lambda x: -sum(agg[x].values())):
            print(f"  {f:<12} {agg[f].get('SIM',0):>8} {agg[f].get('NAO',0):>8} "
                  f"{agg[f].get('?',0):>10}")
        recusou = [d for d in defesa if d["concluiu"] == "NAO"]
        if recusou:
            print(f"\n  -- RECUSOU TENDO OPCAO ({len(recusou)}), as mais caras primeiro:")
            for d in sorted(recusou, key=lambda x: -x["opcoes"])[:top]:
                print(f"     {rot.get(d['match_id'],'?'):<3} turno {d['turn']:<3} "
                      f"{d['fase']:<10} opcoes={d['opcoes']:<3} "
                      f"{', '.join(d['cartas'][:4]) if d['cartas'] else ''}")
        print()

    reativos = rel.get("reativos") or []
    if reativos:
        print("== EFEITOS REATIVOS (on_ko, on_opp_attack, your_turn, trigger...) ==")
        print("   O JOGO dispara e pergunta ao bot -- nao vem de `main` nem de")
        print("   `defense`. Identificados pelo `actor_code` da carta dona.")
        agg = defaultdict(lambda: [0, 0])
        for x in reativos:
            for g in x["gatilhos"]:
                agg[g][0 if x["ok"] else 1] += 1
        print(f"  {'gatilho':<22} {'RESPONDEU':>10} {'NAO':>6}")
        for g in sorted(agg, key=lambda k: -sum(agg[k])):
            print(f"  {g:<22} {agg[g][0]:>10} {agg[g][1]:>6}")
        ruins = [x for x in reativos if not x["ok"]]
        if ruins:
            print("")
            print(f"  -- NAO RESPONDEU ({len(ruins)}):")
            for x in ruins[:top]:
                print(f"     {rot.get(x['match_id'],'?'):<3} turno {x['turn']:<3} "
                      f"{x['ator']:<11} {'/'.join(x['gatilhos']):<24} {x['porque']}")
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
        print()

    # ── O TEXTO DIZ, O BANCO NAO TEM (o ponto cego desta ferramenta) ─────
    tsb = rel.get("texto_sem_banco") or {}
    print(f"== O TEXTO DA CARTA TEM GATILHO QUE O BANCO NAO TEM ({len(tsb)}) ==")
    print("   Tudo acima percorre o BANCO de efeitos. Gatilho que nunca foi")
    print("   parseado nao aparece como 'nao concluido' NEM como 'nunca")
    print("   oferecido' -- ele nao existe pra esta ferramenta. Esta secao e a")
    print("   unica que compara contra o TEXTO OFICIAL, fora do parser.")
    if not tsb:
        print("   nenhum -- toda carta vista tem no banco os gatilhos que o texto declara.")
    else:
        print("   E O CASO MAIS GRAVE: a acao nao existe pro modelo, e nenhum")
        print("   modelo melhor ou corpus maior alcanca. Vai pro parser.")
        for cod, d in sorted(tsb.items()):
            print(f"     {rot.get(d['match_id'],'?'):<3} {cod:<11} ({d['zona']}) "
                  f"FALTA: {'/'.join(d['gatilhos_no_texto_e_fora_do_banco'])} "
                  f"| banco tem: {'/'.join(d['gatilhos_no_banco']) or '(nada)'}")
            print(f"         texto: {d['texto']}")
    print()

    # ── CONCLUIU, MAS VALIA ZERO ────────────────────────────────────────
    vn = rel.get("valor_nulo") or []
    print(f"== CONCLUIU E NAO VALIA NADA ({len(vn)}) ==")
    print("   'Concluiu' e 'valeu alguma coisa' sao perguntas diferentes, e so")
    print("   a primeira era feita. Aqui entra SO o que a regra do jogo prova")
    print("   ser nulo -- 'jogada fraca' e julgamento de valor e nao pertence a")
    print("   esta ferramenta.")
    if not vn:
        print("   nenhum.")
    for l in vn[:top]:
        print(f"     {rot.get(l.get('match_id'),'?'):<3} turno {l['turn']:<3} "
              f"{l['carta']:<11} {l['valor_nulo_por_regra']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="caminho do decision_log .jsonl")
    ap.add_argument("--codigo", default="", help="filtra UMA carta por codigo "
                    "(qualquer uma -- personagem, evento, stage ou lider)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", dest="json_out", help="grava o relatorio em JSON")
    ap.add_argument("--bepinex-log", help="LogOutput.log da MESMA sessao; cruza aceitacao "
                    "real de alvo pelo OPTCGSim")
    args = ap.parse_args()

    p = Path(args.file) if args.file else _ultimo_log()
    if not p or not p.exists():
        print("Nenhum decision_log encontrado.")
        return 1
    print(f"Lendo {p}\n")

    bepinex = Path(args.bepinex_log) if args.bepinex_log else None
    rel = analisar(_carrega(p), _efeitos_db(), filtro=args.codigo,
                   bepinex_log=bepinex)
    imprimir(rel, args.top)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rel, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        print(f"\ngravado em {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
