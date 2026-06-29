# HANDOFF — registro de troca entre IAs (Claude / Codex)

Regra: antes de parar (créditos, fim de sessão, etc.), escreva um bloco novo
no TOPO deste arquivo com data/hora, o que foi feito, e o que falta. Quem
assumir a sessão seguinte deve ler este arquivo + rodar `git log --oneline -10`
e `git status` antes de tocar em qualquer coisa.

---

## 2026-06-29 02:30 — Claude

**Feito** — item 3 do plano do usuário ("vamos fazer 1, depois 2 e depois
3"): auditoria via partida real instrumentada (não a lista teórica de
gaps). Encontrei e corrigi um bug real de integridade de estado:

- Construí um harness de auditoria (`audit_replay.py`, scratchpad, **não
  versionado**) que roda N partidas reais (decks de `decklists_raw.csv`)
  via `ReplayMatch`/`OPTCGMatch` e checa por turno: conservação de DON
  (`don_available + don_rested + don_attached_em_campo == 10 - don_deck`),
  power negativo, conservação de contagem de cartas.
- 25 partidas (seed=42) acharam 2 com violação de conservação de DON. Causa
  raiz: `Card` é `@dataclass` SEM `eq=False` → `__eq__`/`__hash__` por
  VALOR (todos os campos), o que faz `list.remove(card)`/`card in lista`
  ficarem ambíguos quando 2+ cópias físicas da MESMA carta com o MESMO
  estado coexistem na mesma zona (ex: 2 cópias recém-compradas na mão) —
  `.remove()` pode remover a cópia IRMÃ em vez da exata, deixando a carta
  realmente jogada ainda na mão; o Turn Planner a re-seleciona numa
  iteração seguinte e a joga DE NOVO, resultando no MESMO objeto Python
  duas vezes em `field_chars` (board_value e DON contados em dobro).
- **Por que não é um fix trivial de `eq=False`**: `_remap_action`
  (`decision_engine.py` ~5064, Turn Planner) usa `.index(obj)` para mapear
  uma ação do estado real pro clone (deepcopy) — isso DEPENDE de
  comparação por valor pra funcionar (objetos pós-deepcopy nunca são `is`
  o original). Mudar `Card` pra identidade quebraria isso por completo
  (todo remap falharia com `ValueError`, zerando a pontuação de toda ação
  simulada pelo Turn Planner).
- **Fix aplicado**: 2 helpers de identidade (`remove_by_identity`,
  `contains_identity`, logo antes de `remove_character_from_field`,
  `decision_engine.py` ~linha 591) + ~35 call sites de `.remove(card)`/
  `in`/`not in` trocados de comparação por valor pra `is`, em TODAS as
  operações que removem/checam uma carta DENTRO de um único estado (mão,
  campo, trash, deck, listas de candidatos temporárias). `_remap_action`
  ficou intocado de propósito.
- Validação: `smoke_test.py` 100%, `smoke_test_broad.py` 40/40, e
  re-rodei `audit_replay.py` com o MESMO seed=42 → **0 anomalias, 0
  exceções** nas 25 partidas (antes: 6 anomalias em 2 partidas).
- Documentado em `TODO.md` (seção nova "29/06/2026 — bug de identidade em
  `Card`"). Detalhes completos da reprodução lá.

**Estado atual:**
- Commit `ffc6a22` (tasks 1+2 da sessão anterior) ainda não pushed.
- Pendente de commit: `scriptis_da_ia/optcg_engine/decision_engine.py`
  (o fix de identidade), `TODO.md`.
- `audit_replay.py` vive só no scratchpad da sessão — não foi trazido pro
  repo. Se for útil como ferramenta permanente de auditoria, é um
  candidato pra uma sessão futura decidir se formaliza em
  `scriptis_da_ia/` (não fiz essa chamada aqui, escopo era só achar e
  corrigir bugs).

**Próximo:**
- Commitar e dar push (item 3 concluído, plano original dos 3 itens
  fechado).
- 5 "médios" restantes sem urgência (PeekLife, TrashAllFaceUpLife,
  ForceOpponent, QueueUpEndOfTurnAction/OppMainPhase, FieldCantAttackLeader).
- Sistema de imunidade — dívida consciente, fora de escopo.

---

## 2026-06-29 01:00 — Claude

**Feito** (plano em 3 partes pedido pelo usuário: 1. import quebrado, 2. um
gap "médio", 3. auditoria via replay — completei 1 e 2 nesta sessão):
- **1. Corrigido o import quebrado de `simular_deck_usuario.py`** (mencionado
  como dívida pendente em handoffs anteriores). Era de fato `parse_card_effects`
  vs `parse_card_effects_basic` (o nome certo). Rename simples no import e no
  único call site. Validado rodando o script até a etapa de Supabase (carrega
  2614 cartas normalmente, só falha depois por falta de credencial — esperado
  neste ambiente local).
- **2. Implementado `MatchLeaderToBasePower`** (escolhido entre os 6 "médios"
  por ter o maior número de cartas reais confirmadas — 13 cartas via
  levantamento por regex no `cards_rows.csv`, contra ≤11 dos outros). Novo
  campo `source` em `set_base_power`: quando presente, o `amount` é calculado
  em tempo de execução via `effective_power()` da carta referenciada, em vez
  do `int(amount)` fixo do banco (gap real confirmado:
  `decision_engine.py` antigo comentário dizia até estar "pendente sessão
  dedicada" pra ativar `base_power_override` no `effective_power()` — achei
  que isso já estava implementado há tempo, comentário estava desatualizado;
  corrigido o comentário também).
  - 3 fontes: `opp_leader` (5 cartas), `own_leader` (1 carta),
    `selected_opp_character` (2 cartas — seleção e cópia no MESMO step de
    texto, não precisa da infra de memória entre steps da rodada anterior).
  - Fica de fora: OP04-069 ("the same as the power of your opponent's
    ATTACKING Leader or Character") — exige saber quem está atacando no
    momento da resolução, contexto de batalha que `set_base_power` não tem
    hoje. 1 carta, registrado como gap residual.
  - Workflow completo: baseline via `git show HEAD:...`, `PERDEU=0` (7 cartas
    mudaram, todas ganho de cobertura — eram blocos sem nenhum efeito antes),
    `gerar_dbs.py`, `snapshot_parser.py`, `smoke_test.py` 100%,
    `smoke_test_broad.py` 40/40, e 4 cenários manuais diretos (opp_leader,
    own_leader, selected com escolha do melhor candidato do oponente, e sem
    candidato não quebra nem aplica nada).
- `TODO.md` e `comparacao_simulador_vs_IA.md` atualizados (médios: 6 → 5).

**Estado atual:**
- Pendente de commit: `simular_deck_usuario.py`, `TODO.md`,
  `comparacao_simulador_vs_IA.md`, `scriptis_da_ia/gerar_effects_db.py`,
  `scriptis_da_ia/optcg_engine/decision_engine.py`,
  `scriptis_da_ia/card_effects_db.json`,
  `scriptis_da_ia/card_analysis_db.json`,
  `scriptis_da_ia/parser_snapshot.json`.

**Próximo:**
- Commitar/push o que está pendente acima.
- **3. Auditoria via replay/partida real instrumentada** — ainda não
  iniciada (era o 3º item do plano do usuário, "vamos fazer 1, depois 2 e
  depois 3"). Rodar `replay_optcg.py` com partidas reais e procurar
  comportamento estranho na prática, em vez de seguir só a lista teórica
  de gaps.
- 5 "médios" restantes sem urgência (PeekLife, TrashAllFaceUpLife,
  ForceOpponent, QueueUpEndOfTurnAction/OppMainPhase, FieldCantAttackLeader).
- Sistema de imunidade — dívida consciente, fora de escopo.

---

## 2026-06-29 00:15 — Claude

**Feito** (sessão tinha travado/fechado o app no meio do bloco anterior;
usuário voltou, confirmei que nada se perdeu no disco, commitei e dei push
do bloco pendente, depois segui com o item que tinha ficado como chip de
background):
- Push do commit `4ea805f` (Freeze + SaveTargetName + investigação CantPlay*,
  ver bloco anterior) — `a5b3007..4ea805f main -> main`, hook de pre-push
  passou normal.
- **Corrigido o `target='own_character'` não tratado em `buff_power`**
  (achado de brinde na rodada anterior, virou chip — usuário pediu pra
  investigar agora em vez de background). 15 cartas reais usam esse target
  (EB04-009, OP03-039, OP08-018, OP08-019 x2, OP08-095, OP08-103, OP10-092,
  OP12-001, OP12-016, OP12-018, OP12-019, OP13-022, P-011, ST13-001) e
  TODAS caíam no fallback sem aplicar nada (no-op silencioso desde sempre,
  não é regressão de hoje). Implementado: seleciona entre `me.field_chars`
  via `eligible_cards`/`choose_highest_board_value` (sem filtro de tipo,
  distinto do `select_filtered` da rodada anterior). No caminho, achei que
  o PARSER também não capturava os filtros do texto em 3 dessas cartas
  ("with N power or less" → `power_lte`, "other than [Nome]" → `exclude`:
  OP10-092, OP12-001, OP13-022) — corrigido junto.
- Workflow completo: baseline via `git show HEAD:...`, `PERDEU=0` (3 cartas
  mudaram no parser, as com filtro — as outras 12 sem filtro não mudam
  estrutura), `gerar_dbs.py`, `snapshot_parser.py`, `smoke_test.py` 100%,
  `smoke_test_broad.py` 40/40, e 3 cenários manuais diretos (sem filtro
  escolhe o mais forte, com `power_lte` filtra certo, com `exclude` ignora
  a carta excluída mesmo sendo a melhor candidata).
- `TODO.md` atualizado com o achado/correção como item separado.

**Estado atual:**
- Pendente de commit: `TODO.md`, `scriptis_da_ia/gerar_effects_db.py`,
  `scriptis_da_ia/optcg_engine/decision_engine.py`,
  `scriptis_da_ia/card_effects_db.json`,
  `scriptis_da_ia/card_analysis_db.json`,
  `scriptis_da_ia/parser_snapshot.json`.

**Próximo:**
- Commitar e (se usuário pedir) dar push do que está pendente acima.
- 6 "médios" sem urgência (ver `comparacao_simulador_vs_IA.md`).
- `simular_deck_usuario.py` com import quebrado pré-existente, ainda não
  corrigido.
- Sistema de imunidade (família inteira ausente) — dívida consciente, fora
  de escopo.

---

## 2026-06-28 23:50 — Claude

**Feito ("vamos fazer o restante" — os 3 gaps reais que sobraram):**
- **Freeze (don/stage/card) implementado de verdade.** Campo novo
  `frozen_next_refresh` (bool) na classe `Card` (incluído também no
  `__deepcopy__` customizado — lista hardcoded, fácil esquecer) e
  `frozen_don_count` (int) em `GameState`. `refresh_phase` agora pula o
  untap de characters/stage congelados (e o flag é consumido, só vale 1
  refresh) e segura `min(frozen_don_count, don_rested)` DON sem desvirar.
  Handlers de `lock_opp_character_refresh` (18 cartas, filtro
  cost_lte/cost_eq), `lock_opp_don_refresh` (1 carta) e
  `lock_self_character_refresh` target='this_card' (1 carta, OP04-090)
  implementados de verdade (antes só retornavam "não implementado").
  Testado manualmente com script direto (character/stage/DON congelados
  ficam rested 1 refresh e voltam ao normal na seguinte) + smoke tests.
- **CantPlayAnyCardsFromHand/CantPlayAnyCharactersToField no oponente:
  investigado e descartado.** Busquei "opponent cannot play" em todas as
  variantes no `cards_rows.csv` — 0 cartas reais. As 18 cartas com "cannot
  play" no banco são TODAS auto-aplicadas (custo de ramp de DON, já
  cobertas por `self_cant_play`). O exemplo "Imu" do doc original não
  corresponde a carta real do nosso pool — não implementei código
  especulativo sem carta pra validar (mesma lógica de não deixar código
  morto). Perguntei ao usuário antes de pular, ele confirmou.
- **SaveTargetName / memória de alvo entre steps implementado.** Isso
  cresceu de escopo no meio do caminho (avisei o usuário, ele confirmou
  seguir): além da memória em si, precisei consertar DOIS bugs
  pré-existentes que travavam as cartas-alvo:
  1. `parse_power_buff` (`gerar_effects_db.py`) tinha um bug de bracket:
     "select up to N of your [Tipo]..." com `[...]` colchetes nunca batia
     porque a regex só previa `{...}` chaves (cartas reais usam os 2
     estilos + `"..."` aspas, inconsistente na fonte). Generalizado pra
     cobrir os 3 estilos.
  2. Ordem de despacho dos sub-parsers dentro de `parse_block` NÃO segue a
     ordem do texto original — `select_grant_unblockable_turn`/
     `lock_self_character_refresh` (consome o alvo) era despachado ANTES
     de `buff_power` (que seleciona o alvo), deixando a memória vazia no
     momento errado. Corrigido com `steps.sort()` estável no final de
     `parse_block` (quem tem `target='selected'` sempre vai depois).
  - Mecanismo: `EffectExecutor._last_selected`, zerado a cada `execute()`,
    preenchido por `buff_power` com `target='select_filtered'` (nova opção,
    seleciona entre `field_chars`+`leader` por `card_matches_filter`,
    escolhe o melhor por `choose_highest_board_value`), consumido por
    `select_grant_unblockable_turn`/`lock_self_character_refresh` com
    `target='selected'` (se não há memória, não aplica em ninguém — mais
    seguro que adivinhar).
  - Resolveu de verdade: OP07-057, OP12-077 (residuais de
    `OppNoBlockerThisTurn`) e EB02-021 (residual de Freeze, "the selected
    Character will not become active"). OP12-016 (Rayleigh) fica de fora —
    o alvo dele vem de um CUSTO ("give 2 DON to 1 of your Rayleigh"), não
    de um step anterior; memória custo→efeito é mecanismo diferente, não
    implementado (1 carta, raro).
  - **Achado de brinde**: ao generalizar a regex de `parse_power_buff`,
    descobri que o padrão "up to N of your [Tipo] cards gains +X power"
    (SEM a palavra "select") já existia em 48 cartas no banco e SEMPRE
    caía em `target='self'` por engano (bug pré-existente — o efeito não é
    "esta carta ganha power", é "escolha 1 personagem do tipo X no
    campo"). Corrigido para `target='select_filtered'` nas 48. Validei uma
    amostra manualmente (OP03-117, OP04-093, OP11-007 — este último tinha
    um false-positive extra: pegava "leader" de uma cláusula de condição
    não relacionada, "if your leader has the Navy type, up to 1 of your
    Navy type Characters gains...") — todas as 48 são correções reais, não
    regressão.
  - **Achado de brinde #2, NÃO corrigido** (fora de escopo, registrado):
    `target='own_character'` também é gerado pelo parser de `buff_power`
    mas o engine nunca trata esse valor — cai no fallback sem aplicar nada
    (no-op silencioso). Criei um chip de task em background pra investigar
    quantas cartas reais isso afeta e corrigir — não toquei agora pra não
    inflar mais o escopo desta sessão.
- Workflow seguido corretamente: baseline limpo via
  `git show HEAD:scriptis_da_ia/parser_snapshot.json` (não `git stash`,
  lição da sessão anterior) → editei parser → `PERDEU=0` em todas as 3
  rodadas (Freeze não mudou parser; SaveTargetName mudou 52 cartas, todas
  conferidas) → `gerar_dbs.py` → `snapshot_parser.py` → `smoke_test.py`
  100% → `smoke_test_broad.py` 40/40 (rodado 3x, uma por feature).
- `TODO.md` e `comparacao_simulador_vs_IA.md` reescritos: zero gaps "reais"
  restantes, só os 6 "médios" sem urgência (PeekLife, TrashAllFaceUpLife,
  MatchLeaderToBasePower, ForceOpponent, QueueUpEndOfTurnAction/
  OppMainPhase, FieldCantAttackLeader).

**Estado atual:**
- Tudo no disco, NÃO commitado ainda (a sessão travou antes do commit).
  `git status`: `TODO.md`, `comparacao_simulador_vs_IA.md`,
  `scriptis_da_ia/card_analysis_db.json`, `scriptis_da_ia/card_effects_db.json`,
  `scriptis_da_ia/gerar_effects_db.py`,
  `scriptis_da_ia/optcg_engine/decision_engine.py`,
  `scriptis_da_ia/parser_snapshot.json`. Próxima ação: revisar `git diff`
  uma vez e commitar (1 commit ou 3 separados por feature — a decidir).

**Próximo:**
- Commitar o que está pendente (ver acima).
- Task em background pendente: `target='own_character'` não tratado em
  `buff_power` (chip criado, não iniciado).
- 6 "médios" sem urgência (ver `comparacao_simulador_vs_IA.md`).
- `simular_deck_usuario.py` com import quebrado pré-existente, ainda não
  corrigido (fora de escopo, mencionado em sessões anteriores).

---

## 2026-06-28 22:30 — Claude

**Feito:**
- Implementado `OppNoBlockerThisTurn`, com correção de rumo no meio do
  caminho (registrando aqui pra próxima sessão não repetir o erro):
  1ª tentativa: classifiquei como "gap real total" — errado, a action
  `lock_opp_blocker_turn` já existia no engine. 2ª tentativa: levantei 6
  cartas "ausentes" e categorizei 3 delas (OP07-057, OP12-016, OP12-077)
  como precisando de mecanismo novo de "atacante específico" — também
  impreciso: 2 dessas (na real, eram outras: OP13-057/ST01-016, não essas 3)
  já eram cobertas por `select_grant_unblockable_turn`. Só depois de varrer
  as 20 cartas reais do banco com "cannot activate Blocker" uma a uma contra
  `card_effects_db.json` é que cheguei no número certo: 17/20 já cobertas,
  3 residuais (OP07-057, OP12-016, OP12-077) que precisam de "lembrar alvo
  selecionado num step anterior" — mesma raiz do gap `SaveTargetName`, não
  implementado agora (registrado como item ligado, não isolado).
  - Implementado: extensão de regex em `gerar_effects_db.py`
    (`parse_lock_attack`, novo bloco `m_block_filtered`) cobrindo "All" (em
    vez de "up to N") e cláusula de custo/power no meio da frase. 3 cartas
    a mais: OP11-013, OP12-051, ST21-016.
- **Achado importante no caminho**: ao validar com `diff_parser.py`, descobri
  que 9 cartas MUDARAM sem eu ter tocado nelas — investigação revelou que o
  commit `4f41178` ("Implementa buffs dinamicos do ActV3", de sessão
  anterior) já tinha implementado `buff_power_per_count` no parser, mas
  NUNCA regenerou/commitou um `parser_snapshot.json` atualizado — violação
  do workflow documentado no `TODO.md` ("PERDEU=0" devia ter sido confirmado
  e não foi). Validei manualmente que a implementação está correta (ex:
  "+1000 power for every 3 rested DON" → `count_per=3, source='rested_don'`,
  bate exato) e completei o workflow que faltava: `gerar_dbs.py` +
  `snapshot_parser.py`.
- **Workflow seguido corretamente nesta sessão** (depois de um tropeço meu —
  rodei `snapshot_parser.py` DEPOIS de editar o parser por engano na 1ª
  tentativa, o que invalidaria a comparação; corrigido buscando o snapshot
  real via `git show HEAD:...` em vez de `git stash`, que reintroduziu o
  erro numa segunda tentativa antes de eu perceber e fazer do jeito limpo):
  `gerar_effects_db.py` editado → `gerar_dbs.py` (regenera
  `card_effects_db.json` + `card_analysis_db.json`) → `snapshot_parser.py`
  → diff contra baseline real do HEAD → `PERDEU=0`, 12 `MUDOU` (3 minhas + 9
  do achado do `4f41178`) → `smoke_test.py` (100%) → `smoke_test_broad.py`
  (40/40 partidas sem exceção).
- Documentação corrigida de novo (3ª revisão do dia neste tópico):
  `comparacao_simulador_vs_IA.md` e `TODO.md` atualizados com a contagem
  final (44 cobertos / 23 ausentes) e os 2 itens implementados marcados.

**Estado atual:**
- Pronto pra commit: `gerar_effects_db.py`, `card_effects_db.json`,
  `card_analysis_db.json`, `parser_snapshot.json`, `comparacao_simulador_vs_IA.md`,
  `TODO.md`.

**Próximo:**
- Gaps reais restantes (2 genuínos + 1 ligado): `Freeze` funcional (refresh
  phase), `CantPlayAnyCardsFromHand`/`CantPlayAnyCharactersToField` no
  oponente, e o conjunto `SaveTargetName`/3 cartas residuais de
  `OppNoBlockerThisTurn` (memória de alvo entre steps — maior escopo,
  resolver junto).
- 7 "médios" sem urgência.
- `simular_deck_usuario.py` com import quebrado pré-existente, ainda não
  corrigido.
- **Lição pra próxima sessão**: sempre que `diff_parser.py` mostrar mudanças
  que você não fez, INVESTIGAR antes de assumir bug seu — pode ser trabalho
  de sessão anterior sem snapshot regenerado (foi o caso aqui).

---

## 2026-06-28 21:15 — Claude

**Feito:**
- Revisão completa (não amostragem) dos 15 itens de
  `comparacao_simulador_vs_IA.md` ("8 relevantes" + "7 médios") direto contra
  `decision_engine.py`, com linha de código citada para cada um. Resultado:
  - Dos 8 "relevantes": `DealDamage`/`TakeDamage`, `ShuffleHandIntoDeck` e
    `CycleEntireHandToDeckBottom` já estavam implementados. `BuffSelf1KPerXTargets`/
    `BuffXPerGivenDon`/`BuffXPerTopDeckCost` é parcial (framework
    `buff_power_per_count` existe, falta só 2 fontes novas — barato). Restam 4
    gaps reais: `OppNoBlockerThisTurn`, `Freeze` (stub confirmado por
    comentário no próprio código, linha 1722), `CantPlayAnyCardsFromHand`/
    `CantPlayAnyCharactersToField` direcionado ao OPONENTE (hoje só
    auto-aplicado via `self_cant_play`).
  - Dos 7 "médios": **todos os 7 confirmados ausentes** — a categorização
    original estava invertida (a lista de "menor prioridade" é a que está
    100% sem cobertura). Confirmado especificamente que `set_base_power` só
    aceita valor fixo (não serve para `MatchLeaderToBasePower`, que precisa
    copiar dinamicamente) e que `cannot_attack_self` é mecanismo diferente de
    `FieldCantAttackLeader`.
- Reescrita a seção "BURACOS" de `comparacao_simulador_vs_IA.md` com a tabela
  corrigida, status verificado por código, e contagem nova (42 cobertos / 25
  ausentes, era 39/28).
- Reescrita a seção "BURACOS DE MECÂNICA" de `TODO.md` com a lista real
  (4 gaps + 1 parcial barato + 7 médios todos ausentes), marcando os 3 itens
  já implementados como `[x]`.

**Estado atual:**
- Edições prontas pra commit em `comparacao_simulador_vs_IA.md` e `TODO.md`.

**Próximo:**
- Implementar os gaps reais confirmados, em ordem de impacto sugerida:
  1. `OppNoBlockerThisTurn` (maior impacto competitivo, habilita lethal)
  2. `CantPlayAnyCardsFromHand`/`CantPlayAnyCharactersToField` no oponente
     (arquétipo control, ex: Imu)
  3. `Freeze` funcional (precisa tocar `refresh_phase`)
  4. (barato) acrescentar fontes `don_attached`/`top_deck_cost` no
     `buff_power_per_count`
- `simular_deck_usuario.py` com import quebrado pré-existente, ainda não
  corrigido (achado em bloco anterior).

---

## 2026-06-28 20:50 — Claude

**Feito:**
- Verificação pedida pelo usuário: conferi se o `origin/main` no GitHub está
  de fato espelhando a higienização toda feita hoje (não só local). Resultado:
  `git status` limpo, local e remoto no mesmo commit (`git rev-list
  --left-right --count origin/main...HEAD` = `0 0`). Confirmado via
  `git ls-tree -r origin/main` que os 14 arquivos removidos hoje estão
  realmente ausentes do remoto, os novos (`CLAUDE.md`, `HANDOFF.md`,
  `scripts/hooks/pre-push`, `_referencias/.../decompiled_python/*`) estão
  presentes, e a DLL/PDFs/dnspy-export continuam fora do git (0 matches).
- **Achado extra**: 2 arquivos `.pyc` (`scriptis_da_ia/optcg_engine/
  __pycache__/engine.cpython-313.pyc` e `simulator.cpython-313.pyc`) estavam
  RASTREADOS no git apesar de `__pycache__/` estar no `.gitignore` — devem
  ter sido adicionados antes da regra existir. Os nomes ("engine", "simulator")
  não correspondem a nenhum `.py` que existe hoje no repo (são bytecode de
  arquivos-fonte já renomeados/removidos há muito tempo). Removidos do git
  com `git rm --cached` (continuam no disco local como cache normal, só não
  versionados mais).

**Estado atual:**
- `git rm --cached` executado, pronto pra commit. Repo tem 87 arquivos
  rastreados no remoto depois da higienização de hoje (era mais antes).

**Próximo:**
- Mesma pendência de antes: corrigir `comparacao_simulador_vs_IA.md` e a
  seção de buracos do `TODO.md` com a lista real de gaps (~3, não 8).
- Implementar os ~3 gaps reais confirmados quando a doc for corrigida.
- `simular_deck_usuario.py` com import quebrado pré-existente (achado às
  20:35), ainda não corrigido.

---

## 2026-06-28 20:35 — Claude

**Feito:**
- Decisão tomada sobre o destino de `optcg_engine/models.py` + companhia
  (`action_system.py`, `validators.py`, `card_power.py`, `card_queries.py`,
  `card_loader.py`, `enums.py`): usuário escolheu **mover para referência**,
  não deletar nem integrar. Executado:
  - `git mv` dos 7 arquivos para
    `_referencias/simulador-oficial/decompiled_python/` (nome com
    UNDERSCORE, não hífen — hífen quebraria import de pacote Python).
  - Criado `decompiled_python/__init__.py` documentando o que é e por que
    está lá.
  - `scriptis_da_ia/optcg_engine/__init__.py` foi ESVAZIADO — antes
    importava todo esse material automaticamente em TODO import do pacote
    (ou seja, rodava em toda chamada da API mesmo sem ser usado). Agora só
    tem docstring + `__version__`. Confirmado por grep: nada em
    `scriptis_da_ia/` faz `from optcg_engine import X` no nível do pacote
    (sempre `from optcg_engine.decision_engine import X` etc), então é
    seguro.
  - Validado: `from decompiled_python.models import ...` etc funciona
    isolado (pacote próprio, imports relativos internos intactos). E
    `import optcg_engine`, `decision_engine.py`, `api.py`, `replay_optcg.py`,
    `simulation_worker.py` continuam importando OK depois da mudança —
    inclusive o `smoke_test.py` (testes de regressão do motor) passou 100%.
  - Atualizados `scriptis_da_ia/README.md` e `CLAUDE.md` pra refletir a nova
    localização e não apontar mais pro `MAPA_EFEITOS.md` (já removido).
- **Achado colateral (NÃO corrigido ainda)**: `scriptis_da_ia/
  simular_deck_usuario.py` tem um import quebrado pré-existente — importa
  `parse_card_effects` de `decision_engine.py`, mas essa função não existe
  lá (só existe `parse_card_effects_basic`). Confirmado via `git show` que
  o bug já existia no commit `9237f2c` (antes desta sessão), não foi
  introduzido pela movimentação de hoje. Script provavelmente não é
  executado há um tempo. Não corrigi — fora do escopo desta tarefa.

**Estado atual:**
- Tudo pronto pra commit: 7 `git mv`, 1 arquivo novo (`__init__.py` da
  pasta de referência), edições em `optcg_engine/__init__.py`,
  `scriptis_da_ia/README.md`, `CLAUDE.md`.

**Próximo:**
- Corrigir `simular_deck_usuario.py` (import quebrado, achado acima) se for
  usar esse script.
- Mesma pendência de antes: corrigir `comparacao_simulador_vs_IA.md` e a
  seção de buracos do `TODO.md` com a lista real de gaps (~3, não 8).
- Implementar os ~3 gaps reais confirmados (`OppNoBlockerThisTurn`, `Freeze`
  funcional, `CantPlay*` direcionado ao oponente) quando a doc for corrigida.

---

## 2026-06-28 20:10 — Claude

**Feito:**
- Higienização round 2, a pedido do usuário: conferidos TODOS os `.md` e
  `.json` do repo (fora node_modules/.next/.git). Achados e tratados:
  - `public/modelo_optcg.json` — gêmeo do `src/data/modelo_optcg.json` já
    removido na limpeza anterior; também não usado em lugar nenhum. Removido.
  - `scriptis_da_ia/MAPA_EFEITOS.md` — **removido por estar desatualizado e
    enganoso**: afirmava que `activate_main` (253 cartas) e `passive` (408
    cartas) "NÃO EXECUTADOS pelo engine", o que é FALSO hoje — conferi no
    código (`_activate_main_effects` em `decision_engine.py:4472`, lógica de
    `passive` em várias linhas) e ambos estão implementados há tempo. Quem
    lesse esse arquivo hoje seria induzido a pensar que falta implementar
    algo que já existe. `TODO.md` já cumpre o papel de tracking atualizado.
  - `scriptis_da_ia/PLANO_UNIFICACAO.md` — mantido (tem valor histórico real:
    documenta o diagnóstico e a decisão "replay vira só visualização"), mas
    adicionei nota `STATUS: CONCLUÍDO` no topo, já que o plano que ele
    descreve está executado (confirmado na auditoria de 19:55 desta sessão)
    e o texto original não deixava isso claro pra quem lesse depois.
  - Conferidos e OK, sem mudança: `TODO.md`, `RESUMA_SESSAO.md`, `README.md`,
    `scriptis_da_ia/README.md`, `_referencias/simulador-oficial/notas.md`,
    `comparacao_simulador_vs_IA.md` (já sabíamos que tem gaps errados, ainda
    não corrigido — ver bloco anterior), `card_analysis_db.json`,
    `card_effects_db.json`, `parser_snapshot.json`, `censo_padroes.json`,
    `propostas_finais_209.json`, configs (`package.json`, `tsconfig.json`,
    `vercel.json`, `.claude/settings.local.json`).
- Validar antes do próximo commit: `npx tsc --noEmit` + `npx eslint` (não
  deveriam ser afetados, já que `public/` não entra no build do Next; e
  `.md` não afeta lint/build).

**Estado atual:**
- `git rm` já executado para os 2 arquivos fantasma; edição de
  `PLANO_UNIFICACAO.md` feita. Pronto para commit.

**Próximo:**
- Mesma pendência do bloco anterior: corrigir `comparacao_simulador_vs_IA.md`
  e a seção de buracos do `TODO.md` com a lista real de gaps (~3, não 8).
- Decidir destino final de `optcg_engine/models.py` + companhia (pausado
  pela higienização, ver bloco de 19:55).

---

## 2026-06-28 19:55 — Claude

**Feito:**
- Auditoria "dois motores" (`decision_engine.py` vs `optcg_engine/models.py` +
  `action_system.py`/`validators.py`/`card_power.py`/`card_queries.py`,
  decompilados da DLL oficial): confirmado que NÃO há acoplamento entre eles
  hoje (zero imports cruzados) e que `decision_engine.py` (o motor real de
  produção) já está correto e fiel à DLL nos pontos de maior risco testados
  por amostragem (cálculo de poder, resolução de combate, economia de DON,
  direção do deck topo/fundo). Detalhe completo na resposta da sessão; não
  escrevi isso num .md ainda — se for re-auditar, repetir a amostragem.
- **Achado importante**: `comparacao_simulador_vs_IA.md` (de sessão anterior)
  **superestimou os gaps de cobertura**. Buscou só por nome literal no C#,
  sem checar sinônimos funcionais no Python. Pelo menos 4 dos "8 efeitos
  relevantes ausentes" já existem sob outro nome (`deal_damage`,
  `ShuffleHandIntoDeck`/`CycleEntireHandToDeckBottom` já cobertos). Gaps reais
  confirmados ficam em ~3: `OppNoBlockerThisTurn` (ausente), `Freeze`/
  `bSkipNextActive` (nome existe mas é stub não funcional), `CantPlay*`
  direcionado ao oponente (só funciona auto-aplicado hoje, ex: carta Imu).
  **`comparacao_simulador_vs_IA.md` e a seção de buracos do `TODO.md` ainda
  NÃO foram corrigidos com essa informação** — próxima sessão deveria
  atualizar antes de implementar qualquer um dos gaps.
- **Higienização de arquivos fantasma** (a pedido do usuário, antes de decidir
  o que fazer com os "dois motores"). Removidos (git rm, commitado):
  - `src/utils/deck-analyzer.ts` — um TERCEIRO motor morto: reimplementação
    própria em TypeScript da análise de deck, nunca importada por nenhuma
    página do front (a API Python já faz esse trabalho). `buildAnalysisIndex`
    era exportada mas nunca chamada.
  - `src/data/card_analysis_db.json` (2.8 MB) e `src/data/modelo_optcg.json`
    (56 KB) — só existiam por causa do módulo morto acima.
  - `scriptis_da_ia/check_leader.py`, `check_meta_count.py` — scripts de
    debug de uso único, hardcoded, sem reuso.
  - `scriptis_da_ia/test_payload.json` — sem nenhuma referência no repo.
  - `scriptis_da_ia/Proficfile` — vazio (0 bytes), nome com typo
    (provavelmente devia ser `Procfile`); não usado (Railway usa start
    command configurado no painel, não Procfile).
  - `scriptis_da_ia/modelo_optcg.json`, `.pkl`, `features.csv`,
    `resultados_simulacao.csv` — artefatos gerados pela abordagem de ML já
    documentada como superada em `scriptis_da_ia/README.md` (os SCRIPTS
    `treinar_modelo.py` e `coletar_dados_optcg.py` foram MANTIDOS — o
    README registra valor futuro possível pro coletor).
  - Validado: `npx tsc --noEmit`, `npx eslint` (0 erros) e import do
    `decision_engine.py`/`api.py` em Python continuam OK após a remoção.
  - **NÃO removidos** (têm uso real ou são trabalho pendente documentado):
    `propostas_completo.py`/`propostas_finais_209.json`/`censo_padroes.py`/
    `censo_padroes.json` (insumo dos lotes 9-11 do parser, ainda não
    aplicados — ver `RESUMA_SESSAO.md`), `smoke_test*.py`, `snapshot_parser.py`,
    `diff_parser.py`, `gerar_dbs.py` (ferramentas ativas do workflow).
  - `scriptis_da_ia/card_analysis_db.json` (no scriptis_da_ia, NÃO no
    src/data) é a base REAL usada pela API — não tocar nesse.

**Estado atual:**
- Mudanças prontas para commit (limpeza de arquivos fantasma). Ainda não
  commitado no momento em que este bloco foi escrito — ver `git status`.

**Próximo:**
- Corrigir `comparacao_simulador_vs_IA.md` e `TODO.md` com a lista real de
  gaps (~3, não 8) antes de implementar qualquer um deles.
- Decidir o destino final de `optcg_engine/models.py` + companhia (4470
  linhas decompiladas, fiéis à DLL, sem uso em produção): a recomendação
  anterior foi mantê-los como referência congelada (não merge de modelo de
  dados, que seria reescrita de alto risco contradizendo a conclusão já
  documentada de que a arquitetura atual está correta) — usuário ainda não
  confirmou essa direção, decisão pausada pela higienização.
- Implementar os ~3 gaps reais confirmados (`OppNoBlockerThisTurn`, `Freeze`
  funcional, `CantPlay*` direcionado ao oponente) quando a documentação for
  corrigida.

---

## 2026-06-28 19:10 — Claude

**Feito:**
- Criados `CLAUDE.md` (lido automaticamente pelo Claude Code no início de
  toda sessão nesta pasta) e este `HANDOFF.md`, para o projeto não depender
  de memória de sessão nem de "lembrar de avisar" a próxima IA.
- Criado hook de `pre-push` (`scripts/hooks/pre-push` + instalador
  `scripts/setup-git-hooks.sh`): bloqueia `git push` se `HANDOFF.md` não
  tiver sido alterado nos commits enviados. `.git/hooks/` não é versionado
  pelo git — **cada clone/máquina nova precisa rodar
  `sh scripts/setup-git-hooks.sh` uma vez** para o hook funcionar lá também.
  Testado: tentei dar push sem atualizar este arquivo e foi bloqueado
  corretamente.
- Commits feitos e enviados ao `origin/main`: correção do `UnboundLocalError`
  do `eligible_cards`, zeragem dos erros de lint/build do front, e agora os
  arquivos de continuidade + o hook.

**Estado atual:**
- Tudo commitado. `git push` deve passar agora que este bloco foi escrito.

**Próximo:**
- Continuar o trabalho de engine/parser que estava em andamento antes
  (ver seção "🔴 PROBLEMAS ABERTOS" e "🔴 BURACOS DE MECÂNICA" do `TODO.md`):
  `_choose_to_trash` não avalia qualidade do trash, Five Elders (c10) nunca
  jogada, e os buracos de mecânica priorizados (DealDamage, Freeze, etc.).
- Se trabalhar em outra máquina/clone, lembrar de rodar
  `sh scripts/setup-git-hooks.sh` primeiro.

---

## 2026-06-28 18:45 — Claude

**Feito:**
- Confirmado: a migração para "um motor só" está correta — o replay
  (`scriptis_da_ia/.../replay` ou similar) só delega para `OPTCGMatch`
  (`_place_start_stage`, `refresh_phase`, `main_phase`), sem regra duplicada.
- Corrigido bug real em `scriptis_da_ia/optcg_engine/decision_engine.py`:
  `_execute_step` (linha ~1318) chamava `eligible_cards` (linha ~2528) antes
  de qualquer import local da função ter sido executado nesse branch
  específico → `UnboundLocalError: cannot access local variable
  'eligible_cards'`. Corrigido movendo `from optcg_engine.rules_facade import
  eligible_cards` para o topo da função (linha ~1319), em vez de depender dos
  imports locais espalhados em cada branch.
- Zerados os 23 erros de lint do frontend (`npx eslint`), em 8 arquivos:
  `src/app/analysis/page.tsx`, `src/app/api/sync-cards/route.ts`,
  `src/app/cards/page.tsx`, `src/app/deck/page.tsx`,
  `src/app/meus-decks/page.tsx`, `src/app/page.tsx`,
  `src/app/simulate/page.tsx`, `src/utils/deck-analyzer.ts`.
  Principais correções: troquei `any` por tipos concretos (`ApiCard`,
  `AnaliseResult`, `SavedDeck`, `CardThumb`), `prefer-const`, ordem de
  declaração de função antes do `useEffect` (`react-hooks/immutability`),
  componente criado durante render (`CostChart` → `renderCostChart()` em
  `deck/page.tsx`), aspas não escapadas em JSX, e `setState` síncrono dentro
  de efeitos (`react-hooks/set-state-in-effect`) resolvido com
  `queueMicrotask(() => { ... })` — mesmo padrão que já existia em
  `simulate/page.tsx`.
- Corrigido bug de build do Next.js (pré-existente, não causado por mim):
  `useSearchParams()` sem `<Suspense>` quebrava `next build` em `/analysis`,
  `/deck` e `/simulate`. Cada página foi dividida em
  `export default function XPage() { return <Suspense><XPageContent /></Suspense> }`
  + `function XPageContent() { ... lógica original ... }`.
- Validado: `npx eslint` → 0 erros (só warnings antigos de `<img>`/deps
  pré-existentes), `npx tsc --noEmit` → limpo, `npx next build` → compila e
  gera as 14 rotas com sucesso.
- Conferido cálculo de DON do usuário no turno 11 do replay (3 custo do
  Empty Throne + 5 anexados no Marcus Mars + 2 anexados no Imu = 10, não 11
  — engine está certo, foi erro de conta do usuário).

**Estado atual:**
- Mudanças ainda NÃO commitadas (ver `git status` / `git diff --stat`).
  Arquivos modificados: `scriptis_da_ia/optcg_engine/decision_engine.py`,
  `src/app/analysis/page.tsx`, `src/app/api/sync-cards/route.ts`,
  `src/app/cards/page.tsx`, `src/app/deck/page.tsx`,
  `src/app/meus-decks/page.tsx`, `src/app/page.tsx`,
  `src/app/simulate/page.tsx`, `src/utils/deck-analyzer.ts`.

**Próximo:**
- Decidir se commita essas correções antes de continuar com novas features.
- Continuar com o que estava em andamento antes do lint (mexer nas faixas /
  migração para motor único, conforme contexto da sessão anterior do Codex).
