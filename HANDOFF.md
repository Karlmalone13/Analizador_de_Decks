# HANDOFF — registro de troca entre IAs (Claude / Codex)

## 2026-07-02 (3) - Claude — ÚLTIMA DESTA SESSÃO

**Feito — os 4 itens do usuário em sequência: substituição externa (2
cartas), imunidade/exclusão (2 cartas), 5 funções órfãs, deepcopy.**

**Substitução externa (OP07-029 + OP16-014):**
- *OP07-029 (Basil Hawkins)*: novo cost type `rest_opp_character` em
  `_parse_substitute_cost` + handler em `_pay_substitute_cost` (resta o
  melhor Character do oponente, verifica imunidade a rest). Bônus: o
  `rfind('if ')` trick corrigiu um bug silencioso no split de prefixo de
  `parse_block` — o regex original `if .*?` consumia a partir do PRIMEIRO
  "if" do texto (e.g. a condição de tipo do Leader), deixando o prefixo
  vazio; a nova heurística localiza o "if" mais próximo de "would be
  removed from the field". Bônus 2: ST15-005 também ganhou `gain_rush`
  que estava sendo silenciado pelo mesmo bug.
- *OP16-014 (Marco)*: novo flag `no_filter` em
  `_apply_substitute_target_filters` (marcado quando o sujeito do "if
  X would be removed" é genuinamente irrestrito — "one of your
  characters" sem nenhum filtro). `_target_matches_external_substitute`
  agora retorna True quando `no_filter=True`, em vez de tratar
  "nenhuma chave de filtro" como "proteção desligada" (padrão de
  segurança pra falha de extração, não pra ausência real de filtro).
  Custo "K.O. this character instead" mapeado para `trash_self`
  (simplificação documentada: on_ko de self-ressurreição não dispara
  no contexto de substituição).

**Imunidade/exclusão (OP16-032):** regex de `lock_opp_cannot_be_rested`
  /`lock_opp_character_attack` extendido com grupo opcional `(?: other
  than \[([^\]]+)\])?` — agora extrai `exclude` diretamente no parser,
  sem handler de engine adicional (engine já lia `step.get('exclude')`
  desde a implementação original). OP16-032 Boa Hancock agora tem
  `on_play: lock_opp_cannot_be_rested exclude='monkey.d.luffy'` correto.
  OP14-119 (Mihawk, trigger "when this Character becomes rested") ficou
  de fora: exigiria modelar um novo tipo de timing de gatilho não
  suportado, impacto baixo, 1 carta.

**5 funções órfãs (→ 5 deletadas, 1 restaurada):** AST scan detectou 6
  candidatas. Deletadas via script de remoção de linhas: `_count_available
  _attacks`, `choose_card_to_play`, `plan_don_distribution`,
  `plan_attacks`, `_distribute_don` (5 genuinamente mortas, -345 linhas).
  `_mulligan_decision` foi deletada por engano e restaurada depois: é
  chamada por `replay_optcg.py` via `self._get_engine_match()._mulligan_
  decision(...)` — não aparecia no scan interno porque só é chamada
  externamente. Lesson learned: AST scan de "funções não chamadas dentro
  do arquivo" não detecta calls de arquivos externos.

**Deepcopy (otimização menor):** dois pontos em `GameState.__deepcopy__` e
  `_simulate_sequence_once`: (a) `full_deck_census` agora é referência
  compartilhada (invariante de partida, nunca mutado); (b) `opp.deck` em
  `_simulate_sequence_once` usa `list()` em vez de deepcopy por card —
  salva ~0.5-0.7ms por chamada de simulação (opponent não age durante a
  simulação do turno ativo). A dívida maior (clone incremental) permanece.

**Validação:** `diff_parser.py` (PERDEU=0, 1 GANHOU + 6 MUDOU);
  `gerar_dbs.py` + `snapshot_parser.py`; `smoke_test.py` (2 testes
  novos, 100%); `smoke_test_broad.py` (40/40);
  `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0
  anomalias).

---

## 2026-07-02 (2) - Claude

**Feito - corrige a "simplificação consciente" do item anterior
(opp_hand_gte), a pedido do usuário.** O item (1) abaixo tinha deixado
registrado que a condição "if opponent has N+ cards in hand" (prefixo de
5 das 13 cartas de place-at-bottom-of-deck) não estava sendo checada — a
ação disparava sempre, só coincidindo com a regra real quando a mão do
oponente estava em 0. Usuário pediu exemplo concreto, viu que com mão
intermediária (1 a N-1 cartas) a ação tira uma carta que a regra real não
tiraria, e pediu correção.

Nova condição `opp_hand_gte` em `parse_conditions` (`gerar_effects_db.py`,
mesmo molde de `hand_gte` já existente mas sobre `opp.hand`), plugada em
`_check_conditions` e no pre-filtro do Turn Planner
(`decision_engine.py`). Escopo real saiu maior do que os 5 cards
esperados — o mesmo gap textual ("if your opponent has N or more cards in
their hand") afetava TODA a família `opp_trash_from_hand`/`attack_life`
com esse prefixo, não só `opp_place_hand_bottom_deck`: 13 cartas no total
(EB02-045, EB03-026, EB04-022, OP05-082, OP06-093, OP07-047, OP08-046,
OP09-087, OP10-087, OP10-118, OP12-087, OP16-047, ST13-009).

**Validação:** `diff_parser.py` (`PERDEU=0`, 13/13 MUDOU — só ganharam o
gate, nenhum efeito novo nem perdido); `gerar_dbs.py` + `snapshot_parser.py`;
`smoke_test.py` (4 testes novos: 2 unidade + 2 end-to-end via carta real
OP08-046 abaixo/no limiar); `smoke_test_broad.py` (40/40);
`audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0 exceções, 0
anomalias.

---

## 2026-07-02 (1) - Claude

**Feito - os 2 itens "Parser — cobertura" pedidos pelo usuário: `opponent
has N+ DON` (8 cartas) e `place-at-bottom-of-deck` (13 cartas).** Ver
detalhe completo no TODO.md (seção "Parser — cobertura").

Resumo rápido:
1. **opp_don_on_field_gte**: nova condição em `parse_conditions`
   (`gerar_effects_db.py`), simétrica a `don_on_field_gte` já existente
   mas sobre o campo do OPONENTE. Infra de `conditions` já genérica — só
   regex + 2 linhas de `_check_conditions`/pre-filtro do Turn Planner.
   Achado real: OP02-089/090/091 disparavam "opponent returns 1 DON!!"
   SEM gate nenhum (sempre, mesmo com oponente em 0 DON) — bug real
   corrigido, não só cobertura nova.
2. **place-at-bottom-of-deck**: a busca textual ampla por "bottom of
   deck" trouxe ~80 cartas, mas a maioria já estava coberta por
   mecanismos existentes (`deck_top_rest`/`deck_reorder_rest`/custos de
   trash-pro-fundo). O gap real era uma família nova e coerente:
   disrupção FORÇADA no oponente com destino o FUNDO DO PRÓPRIO DECK
   dele (nunca trash) — 2 actions novas (`opp_place_hand_bottom_deck`,
   `opp_place_trash_bottom_deck` com `filter_type='event'`) em
   `decision_engine.py`, parser estendido em
   `parse_opp_self_move_character`. Bônus no caminho: OP06-092 (Brook)
   tinha um `Choose one:` com bullet corrompido (`�`) no `card_text`
   bruto que o split de `parse_block` já reconhecia — só faltava a 2ª
   opção ter parser pra virar uma `choice` de verdade.

**Validação dos dois itens:** `python -m py_compile`; `diff_parser.py`
(`PERDEU=0` nos dois); `gerar_dbs.py` + `snapshot_parser.py`;
`smoke_test.py` (4 casos novos, 100%); `smoke_test_broad.py` (40/40);
`audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0
anomalias nas duas).

**Simplificação consciente, não corrigida:** a condição "if opponent has
N+ cards in hand" que prefixa várias das 13 cartas de
place-at-bottom-of-deck não ficou modelada como gate — mesmo padrão já
aceito pra família `opp_trash_from_hand` (a ação natural já não faz nada
com mão vazia/pequena). Registrar se reabrir o tema.

---

## 2026-07-01 (8) - Claude

**Feito - imunidade a rest forçado (imm_type='rest'), 3 cartas:** um
segundo agente de investigação que eu tinha disparado em paralelo (e cujo
resultado cheguei a achar que tinha falhado) voltou depois de eu já ter
fechado o item de auditoria de imunidade. Relatou um gap real: "cannot be
rested by your opponent's effects" — mas reportou 11 cartas afetadas.
Investigando, descobri que 8 dessas 11 já estavam corretamente
implementadas como `lock_opp_cannot_be_rested` — uma mecânica **oposta**
(trava o character do OPONENTE, beneficia quem ativa o efeito) que só
compartilha a palavra "rested" no texto com a autoproteção real. O agente
confundiu as duas por similaridade superficial. O gap genuíno era só 3
cartas: **OP11-046, OP12-021, OP15-024**.

Implementado: novo `imm_type='rest'` em `parse_immunity`
(`gerar_effects_db.py`), incluindo a forma composta "cannot be K.O.'d OR
rested by your opponent's effects" (OP11-046). `is_immune()` já era
genérico o suficiente pra qualquer `imm_type` sem precisar de mudança — só
documentei. Plugado em `rest_opp_character`
([decision_engine.py](scriptis_da_ia/optcg_engine/decision_engine.py)), o
único ponto real de "rest forçado por efeito do oponente" no banco hoje.

**Validação:** `python -m py_compile`; `python diff_parser.py` (`PERDEU=0`,
exatamente as 3 cartas esperadas); `python gerar_dbs.py` + `python
snapshot_parser.py`; `python smoke_test.py` (119/119, 4 casos novos);
`python smoke_test_broad.py` (40/40); `python audit_replay.py --n 20
--seed 7` e `--n 15 --seed 99` (0 exceções, 0 anomalias nas duas).

**Gaps menores não corrigidos** (achados de raspão, baixo impacto, 2
cartas): OP14-119 (`lock_opp_cannot_be_rested` com gatilho "when this
Character becomes rested" — trigger condicional não reconhecido pelo
parser, perde o efeito inteiro) e OP16-032 (mesma action, mas com exclusão
"other than [Nome]" não extraída — fica sem nenhum efeito parseado).
Registrado no TODO.md.

---

## RESUMO DA SESSÃO DE 2026-07-01 (encerrada aqui — próxima sessão deve
começar lendo este HANDOFF.md inteiro + `git log --oneline -20` antes de
qualquer coisa):

Sessão longa cobrindo, em sequência: (1) auditoria + correção da fila
"FILA ANTERIOR ainda aberta" do TODO.md (5 de 7 itens já estavam
implementados, 2 reais feitos — `lock_opp_attack_unless_pays` e
`deck_reorder_rest`/`deck_top_rest`); (2) família completa de substituição
externa (11 de 13 cartas + 2 bugs estruturais de parser corrigidos no
caminho); (3) auditoria de imunidade restante (confirmado sem gap real em
`EffectImmune`/`CombatImmune`/`ImmuneToStrikes`); (4) imunidade a rest
forçado (3 cartas). Todos os commits já enviados pro `origin/main`.

**Itens reais ainda abertos no TODO.md** pra próxima sessão: 5 funções
órfãs (deletar ou integrar), otimização de `deepcopy` no Turn Planner
(performance), revalidar contagem de cartas com `card_text` mas `effects`
vazio, `opponent has N+ DON` sem parser (~8 cartas), `place-at-bottom-of-deck`
mecânica nova (~14 cartas), OP15-074 Varie (aguarda foto — não dá pra
resolver sem a imagem), `lock_opp_cannot_be_rested` com gatilho "becomes
rested" + exclusão "other than [Nome]" (2 cartas, achado nesta sessão), e
rotação de chaves Supabase (segurança, antes de deploy público).

---

## 2026-07-01 (7) - Claude

**Feito - fecha item "auditoria de imunidade restante" (sem código, só
investigação + documentação):** próximo item da fila do TODO.md. Antes de
implementar, investiguei se `EffectImmune`/`CombatImmune`/`ImmuneToStrikes`
eram mecânicas reais com cartas afetadas — mesmo padrão de checar antes de
agir que rendeu bons resultados hoje.

**Achado:** são nomes de MECANISMOS INTERNOS do código oficial decompilado
(`_referencias/simulador-oficial/dnspy-export/Assembly-CSharp/ActV3Effect.cs`,
`GameplayLogicScript.cs` — flags como `bCombatImmune`, `bEffectImmune`,
`ImmuneToStrikes: List<StrikeType>`), não padrões de texto adicionais que
aparecem em cartas. Busquei direto em `cards_rows.csv` por variantes
textuais mais amplas ("cannot be affected", "immune to", "cannot be
targeted/selected/chosen", "unaffected", "ignores effects") e não achei
NENHUMA carta real usando esses padrões além do que `cannot be K.O.'d`/
`cannot be removed from the field` já cobre — e isso já está implementado,
incluindo a parte de atributo do atacante (Strike/Slash/Special/Wisdom/
Ranged/Leaders — que é literalmente "ImmuneToStrikes" na prática) feita
ontem (30/06). Confirmei com 2 exemplos reais (OP01-024, EB03-018) já
parseados corretamente.

**Resultado:** item fechado no TODO.md — não há mais gap de cobertura
conhecido na família de imunidade.

**Estado da sessão:** essa foi uma sessão longa cobrindo toda a "fila
anterior" do TODO.md pedida pelo usuário (itens 4-10 de uma lista
numerada, depois substituição externa completa, depois esta auditoria de
imunidade). Itens reais que ainda restam abertos no TODO.md: 5 funções
órfãs (deletar ou integrar), otimização de `deepcopy` no Turn Planner,
revalidar contagem de cartas com `card_text` mas `effects` vazio,
`opponent has N+ DON` sem parser (~8 cartas), `place-at-bottom-of-deck`
mecânica nova (~14 cartas), OP15-074 Varie (aguarda foto), e rotação de
chaves Supabase (segurança, antes de deploy público).

---

## 2026-07-01 (6) - Claude

**Feito - substituição externa: fecha 11 das 13 cartas restantes + 2 bugs
estruturais achados no caminho:** continuação direta da fatia anterior.
Implementei 7 cost-types novos em `_pay_substitute_cost`
([decision_engine.py](scriptis_da_ia/optcg_engine/decision_engine.py)):
`rest_leader`, `rest_own_filtered`, `rest_own_character`, `rest_own_card`,
`life_to_hand`, `life_to_trash`, `trash_to_deck_bottom` — com os padrões de
parser correspondentes em `_parse_substitute_cost`. Fechou OP04-082,
OP10-034, OP10-037, OP11-110, OP12-061, OP14-029, OP14-034, OP14-092,
OP15-035, ST09-010, ST20-002 (11 das 13).

**Bônus genuínos** pegos pelos mesmos padrões de regex, fora da lista
original (confirmados corretos por leitura do texto bruto): EB04-043,
OP15-098, OP15-105, e **OP11-001** — a primeira carta de substituição cuja
FONTE é um Leader (Koby), não um Character; funcionou sem nenhuma mudança
de engine porque `try_any_substitute()` já incluía `self.me.leader` na
lista de fontes externas desde a fatia anterior.

**2 bugs estruturais achados e corrigidos no processo** (não eram apenas
"faltava regex"):

1. `parse_substitute_ko`/`parse_substitute_removal` reivindicavam o BLOCO
   INTEIRO de texto ao achar a cláusula de substituição, descartando
   silenciosamente qualquer efeito incondicional que viesse ANTES dela no
   mesmo bloco. Pegou OP14-034 no meio do trabalho: a carta tem um
   `buff_power` sob a tag `[Your Turn]` seguido de uma sentença de
   substituição separada (sem tag própria) — como "[Once Per Turn]" não é
   uma tag formal reconhecida que para a captura do bloco `[Your Turn]`, o
   texto inteiro virava um blob só, e quando a substituição passou a ser
   reconhecida (graças à fatia anterior), ela "engolia" o buff junto.
   Corrigido extraindo o prefixo antes da cláusula e reparseando via
   `parse_block` recursivo. Sem nenhuma intervenção extra minha, o MESMO
   fix corrigiu ST25-003 (achado bônus, perdia `draw`+`play_card` pelo
   mesmo motivo).
2. `try_substitute()` e `_substitute_source_blocks()` só checavam a chave
   `'passive'` do banco — mas cartas com a tag formal `[Opponent's
   Turn]`/`[Your Turn]` ANTES da cláusula de substituição (OP14-029,
   OP14-092, OP14-034) fazem esse timing virar a chave de TOPO no parser,
   não `passive`. É o mesmo padrão que `is_immune()` já tratava
   corretamente (ela itera múltiplos timings); as duas funções de
   substituição não tinham recebido o mesmo tratamento. Ambas agora iteram
   `('passive', 'opp_turn', 'your_turn')`.

**Validação:** `python -m py_compile`; `python diff_parser.py` (`PERDEU=0`
em todas as rodadas, incluindo depois do fix do prefixo); `python
gerar_dbs.py` + `python snapshot_parser.py`; `python smoke_test.py`
(111/111, 11 casos novos); `python smoke_test_broad.py` (40/40); `python
audit_replay.py` com 3 seeds diferentes (`--n 20 --seed 7`, `--n 15 --seed
99`, `--n 25 --seed 321` — terceira rodada extra por causa do escopo amplo
da mudança no dispatch do parser): 0 exceções, 0 anomalias nas três.

**Ainda fora de escopo (2 cartas):** OP07-029 (mecânica invertida — rest 1
Character do OPONENTE como custo, precisa de design próprio) e OP16-014
(K.O. da própria fonte como custo, mas o texto real não tem NENHUM filtro
de alvo — "if one of your Characters would be removed... instead" — a
checagem de segurança atual trata "sem filtro" como "não protege" por
padrão, pensada pra parser que falhou em extrair um filtro existente, não
pra texto genuinamente irrestrito; precisa de um jeito de distinguir os
dois cenários).

---

## 2026-07-01 (5) - Claude

**Feito - substituição externa: gap real de parser achado e corrigido (6
cartas):** próximo item pedido pelo usuário. Antes de mergulhar, rodei um
agente de investigação pra confirmar se ainda tinha trabalho real (o item
do TODO.md tinha cara de já estar majoritariamente fechado em sessões
anteriores, igual aos outros achados stale de hoje).

**Confirmado**: a parte de executor/filtro JÁ estava fechada — `21 de 33`
steps com filtro estruturado, os 12 sem filtro são todos self-referentes
(sem bug de "fonte externa sem filtro protegendo qualquer alvo" —
`_target_matches_external_substitute` já bloqueia esse caso por padrão).
**Mas achei um gap real**: `parse_substitute_ko` e `parse_substitute_removal`
(`gerar_effects_db.py`) tinham listas de PADRÕES DE CUSTO paralelas mas
dessincronizadas — vários padrões existiam só numa das duas funções
(`return_own_don` só em removal; `trash this character instead`/`rest this
character instead` só em KO). 17 cartas reais com texto "would be
removed/K.O.'d ... instead" ficavam sem NENHUMA action `substitute_*`
parseada por causa disso.

**Corrigido**: unifiquei numa função só, `_parse_substitute_cost()`,
chamada pelas duas — união de todos os padrões + 2 bugs extras achados na
mesma auditoria: "you CAN [custo] instead" (regex só aceitava "you MAY") e
falta de variante power-or-less pro `trash_from_hand` (só existia
power-or-more, em duas redações de texto diferentes: "N power or less" e
"a power of N or less"). Fechei 6 das 17 cartas nesta fatia (as que reusam
custo/filtro já existente):
- **EB04-030, EB04-031**: `substitute_ko` self com `return_own_don`.
- **EB04-044**: `substitute_removal` self, só precisava do fix do verbo "can".
- **OP15-003**: `substitute_ko` self com `trash_from_hand` + `power_lte` novo.
- **OP12-027**: substituição EXTERNA (protege outro Character), precisou de
  um filtro de alvo novo — `filter_attribute` (Strike/Slash/Special/Wisdom/
  Ranged), plugado em `_target_matches_external_substitute`.
- **OP15-094**: substituição EXTERNA — achado bônus interessante: o
  early-return de `_apply_substitute_target_filters` via "this character"
  no assunto da frase descartava o filtro de TIPO inteiro quando o texto
  real era "X type Character OTHER THAN this Character" (tratando como
  self-target por engano). A exclusão de si mesma já é garantida
  estruturalmente pelo executor (`sources = [c for c in
  self.me.field_chars if c is not target]` em `try_any_substitute`), então
  só precisava parar de jogar fora o filtro nesse caso específico.

**Validação:** `python -m py_compile`; `python diff_parser.py` (`GANHOU=0
PERDEU=0`, 6 MUDOU = exatamente as 6 cartas esperadas); `python
gerar_dbs.py` + `python snapshot_parser.py`; `python smoke_test.py`
(102/102, 8 casos novos); `python smoke_test_broad.py` (40/40); `python
audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0
anomalias nas duas).

**Ainda falta:** 13 cartas com custos genuinamente novos (não reusam nada
do que já existe): OP04-082, OP07-029 (mecânica invertida — rest 1
Character do OPONENTE como custo), OP10-034, OP10-037, OP11-110, OP12-061,
OP14-029, OP14-034 (externa), OP14-092, OP15-035 (externa), OP16-014, ST09-010,
ST20-002. Cada uma precisa de 1 cost-type novo em `_pay_substitute_cost` —
detalhado no TODO.md.

---

## 2026-07-01 (4) - Claude

**Feito - cannot_attack_self family: já estava implementado, só faltava
teste + limpar comentário enganoso:** depois de fechar `deck_reorder_rest`/
`deck_top_rest`, fui pro próximo item de maior leverage (mesmo bloqueador
estrutural dos "5 pontos de filtro de ataque" que tinha acabado de tocar):
`cannot_attack_self`/`cannot_attack_self_unless`/
`cannot_attack_own_characters_by_cost` (6 cartas, comentário inline no
código dizia "reconhecidas sem travar nada ainda").

**Achado:** essa família JÁ estava 100% implementada e funcionando.
`is_attack_locked_self()` (`decision_engine.py:609-672`) lê
`effects['passive']['steps']` direto de `get_card_effects()` — sem depender
de nenhum estado setado por `_execute_step` — e já é chamada nos 5 pontos
que filtram "pode atacar" (os mesmos que recebi `can_afford_attack_paywall`
na sessão anterior). Verifiquei diretamente: Oars (cannot_attack_self),
Trafalgar Law EB04-005 (unless + condição opp_chars_power_gte_count) e
Buggy P-084 (mass_lock_conditional por custo) já travam corretamente.

O placeholder em `_execute_step` (`if action in (...): return '(...nao
implementado...)'`) NÃO bloqueava nada — mas também não era código morto:
`apply_your_turn_buffs()` executa TODO step de `'passive'` via
`_execute_step` (não só buffs), então esse placeholder rodava todo turno
pra cada uma dessas 6 cartas, gerando um log confuso de "não implementado"
mesmo a trava real já estando ativa em paralelo via `is_attack_locked_self`.
Troquei o placeholder por um `return ''` silencioso e corrigi o comentário
pra explicar a situação real (evita que uma sessão futura tente
"reimplementar" algo que já funciona).

**Validação:** `python -m py_compile`; `python smoke_test.py` (90/90, 6
casos novos: `cannot_attack_self` incondicional, `unless` com condição
falhando/passando, mass-lock por custo travando/liberando/não-aplicando com
Leader errado); `python smoke_test_broad.py` (40/40); `python
audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0
anomalias nas duas).

**Ainda falta:** substituição externa (família grande, ~38 textos),
auditoria de imunidade restante (`EffectImmune`/`CombatImmune`/
`ImmuneToStrikes`), itens de performance (`deepcopy` no Turn Planner, 5
funções órfãs), itens menores de parser (place-at-bottom-of-deck ~14,
opponent has N+ DON ~8), e rotação de chaves Supabase (segurança, antes de
deploy público).

---

## 2026-07-01 (3) - Claude

**Feito - implementa deck_reorder_rest / deck_top_rest (último item da
fila pedida pelo usuário):** os dois últimos stubs sem handler de execução.

**Achado importante:** `deck_top_rest` é um nome de action EQUIVOCADO do
parser. `gerar_effects_db.py:467-470` tem um `elif` que casa o PREFIXO
`'place the rest at the top'` antes de checar o sufixo `'or bottom'` —
então toda carta com o texto real "place the rest at the top or bottom of
the deck in any order" cai incorretamente em `deck_top_rest`. Verifiquei
diretamente em `cards_rows.csv`: nenhuma das 5 cartas que usam
`deck_top_rest` (OP02-057, OP05-043, OP08-053, OP11-040, OP11-104) tem
texto "place the rest at the top" SEM "or bottom" em seguida — são
exatamente o mesmo mecanismo de `deck_reorder_rest` (escolha livre de
ordem), só com nome diferente. Decidi não tocar o parser/regenerar os DBs
só por causa do nome — as duas actions agora compartilham o mesmo handler
em `_execute_step`.

**Implementação:** heurística mirando o `peek_life` 'all' já existente — a
IA controla a ordem livremente, então bota a carta mais valiosa de volta no
topo do deck (próxima a ser comprada), o resto ordenado por `board_value`
crescente abaixo dela. Também adicionadas a `safe_extra_actions` dos
Counter events — isso desbloqueia **OP01-088**, que tinha ficado de fora
explicitamente na fatia de Counter events de ontem por causa desse handler
faltando (documentado no HANDOFF.md (8) de 30/06).

**Validação:** `python -m py_compile`; `python smoke_test.py` (84/84, 3
casos novos: `deck_reorder_rest` puro, `deck_top_rest` com filtro, e
integração via Counter event OP01-088); `python smoke_test_broad.py`
(40/40); `python audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99` (0
exceções, 0 anomalias nas duas).

**Estado da fila pedida pelo usuário (4 a 10 da lista original): TODOS
fechados.** 5 já estavam implementados (corrigido no TODO.md), 2
implementados nesta sessão (`lock_opp_attack_unless_pays` e
`deck_reorder_rest`/`deck_top_rest`). Itens reais ainda em aberto no
TODO.md: substituição externa (família grande), auditoria de imunidade
restante (`EffectImmune`/`CombatImmune`/`ImmuneToStrikes`), `cannot_attack_self`/
`cannot_attack_self_unless`/`cannot_attack_own_characters_by_cost` (6
cartas, mesmo bloqueador estrutural do `lock_opp_attack_unless_pays` — os
5 pontos de filtro "pode atacar" já foram tocados nesta sessão, então a
próxima implementação desses fica mais barata), e os itens de performance/
parser menores listados no TODO.md.

---

## 2026-07-01 (2) - Claude

**Feito - implementa lock_opp_attack_unless_pays (OP08-043 Edward.Newgate):**
primeiro dos 2 itens reais que sobraram da auditoria da fila anterior.
Character do oponente PODE atacar, mas o dono paga um custo (trash N cartas
da mão) a cada ataque enquanto a trava estiver ativa — distinto de
`cannot_attack_until` (bloqueio total, já implementado).

- Campo novo `Card.attack_paywall: dict` (`{cost_type, cost_amount, until}`)
  — adicionado ao `__deepcopy__` customizado de `Card` (campo dict sempre
  REASSIGNED, nunca mutado in-place, então compartilhar referência no
  deepcopy é seguro) e resetado em `refresh_phase` junto com
  `cannot_attack_until`.
- Execução do step seleciona TODOS os Characters do oponente no campo no
  momento (texto real confirma: "select all of your opponent's
  Characters", sem escolha — `count=99`).
- Novo helper `can_afford_attack_paywall(card, owner)`
  ([decision_engine.py:675](scriptis_da_ia/optcg_engine/decision_engine.py))
  — adicionado aos 5 pontos que já filtravam `not c.cannot_attack_until`
  como "pode atacar" (`my_attack_power`, geração de ações de ataque em 3
  lugares diferentes, Turn Planner). Simplificação deliberada: paga sempre
  que a mão tem cartas suficientes, sem modelar "vale a pena pagar" (a
  fase "Opponent Reading" mencionada no comentário antigo do código
  continua pausada — não reabri ela só por causa de 1 carta; mesmo padrão
  conservador que o resto do engine já usa pra custos de ativação).
- Pagamento real acontece em `_execute_attack`, logo depois de restar o
  atacante: trasha as N piores cartas da mão por `board_value()`.

**Validação:** `python -m py_compile`; `python smoke_test.py` (81/81, 4
casos novos: trava aplicada a todos os characters do oponente,
`can_afford_attack_paywall` com/sem paywall e mão insuficiente, e
integração real via `OPTCGMatch._execute_attack` confirmando o trash
automático); `python smoke_test_broad.py` (40/40); `python audit_replay.py
--n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0 anomalias nas duas).

**Ainda falta:** `deck_reorder_rest`/`deck_top_rest` (2 actions distintas,
16+5 cartas) — próximo item da fila pedida pelo usuário.

---

## 2026-07-01 - Claude

**Feito - auditoria da "FILA ANTERIOR ainda aberta" do TODO.md:** usuário
pediu pra trabalhar os itens "choice", "conditional_stack", "set_base_power",
"lock_opp_attack_unless_pays", "deck_reorder_rest/deck_top_rest",
"plan_don_distribution" e "on_opponent_attack timing" em ordem. Antes de
implementar, rodei um agente de investigação (read-only) pra confirmar o
estado real de cada um no código, já que `on_opponent_attack timing` eu
sabia de antemão que estava stale (resolvido em 27/06, confirmado de novo
ontem). Resultado: **5 dos 7 itens já estavam implementados**, o TODO.md
só não tinha sido atualizado:

- `choice` (heurística de valor) — já implementado, `_resolve_choice`
  (`decision_engine.py:853-897`). Contagem real 17 cartas (TODO dizia 19).
- `conditional_stack` — já implementado (`decision_engine.py:1610-1613`).
  1 carta (OP15-092), confere com o TODO.
- `set_base_power` — já implementado, handler completo em
  `decision_engine.py:2512-2566` incluindo caso dinâmico. Contagem real 15
  cartas (TODO dizia 8 — dobrou).
- `plan_don_distribution` — já subtrai a reserva defensiva
  (`decision_engine.py:4720`), só ignora no modo LETHAL deliberadamente
  (decisão do usuário em 27/06).
- `on_opponent_attack timing` — já existe e já é executado, confirmado de
  novo.

Corrigi o TODO.md marcando os 5 como feitos com a contagem/localização real,
mantendo só os 2 itens genuinamente pendentes:
- `lock_opp_attack_unless_pays` (OP08-043, 1 carta) — placeholder não
  implementado em `decision_engine.py:2438-2439`.
- `deck_reorder_rest`/`deck_top_rest` — duas actions DISTINTAS sem handler
  de execução (`deck_reorder_rest`: 16 cartas; `deck_top_rest`: 5 cartas
  próprias — OP02-057, OP05-043, OP08-053, OP11-040, OP11-104).

**Ainda falta:** implementar esses 2 itens reais (próximo passo desta
sessão).

---

## 2026-06-30 (8) - Claude

**Feito - Counter events: buff + play_card/busca em deck (última fatia
desta sequência):** `play_card`, `play_from_deck`, `look_top_deck`,
`add_to_hand`, `deck_bottom_rest` já tinham handler genérico (usados em
on_play/trigger normalmente) — adicionados a `safe_extra_actions` como
bônus de valor junto de um buff `battle_only` que já defende sozinho.
Desbloqueia 8 das 9 cartas do grupo: EB01-019, EB02-059, OP02-045,
OP05-018, OP08-054, OP08-115, OP14-116, ST12-017.

**Achado novo (não corrigido, baixo impacto):** `deck_reorder_rest` (usado
só por OP01-088) é parseada e referenciada em `_step_is_viable`, mas
**nunca teve handler de execução** — mesmo padrão de bug do `debuff_power`
de uma sessão atrás, só que aqui afeta 1 única carta. Deixei de fora desta
fatia por ser baixo impacto; registrado no TODO.md pra não se perder.

**Deliberadamente fora de escopo:** os 4 Counter events sem nenhum buff que
só jogam/buscam carta (EB01-009, OP01-087, OP04-036, OP10-078) — não
afetam `defend_power`/`atk_power` de jeito nenhum, então não cabem no
framework "isso impede o hit". Exigiriam um critério de decisão diferente
("vale gastar DON/carta por puro valor, mesmo sem impedir o ataque?").

Cobertura final de Counter events com buff (depois de toda a sequência
desta sessão): **136/180** (começou em 102/180).

**Validação:** `python -m py_compile`; `python smoke_test.py` (76/76, 4
casos novos cobrindo play_card incondicional/condicional pass-fail e busca
em deck); `python smoke_test_broad.py` (40/40); `python audit_replay.py
--n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0 anomalias nas duas).

**Estado final da auditoria de Counter events (encerrada por ora).** Ainda
fora de escopo, ver TODO.md para detalhes:
- `deck_reorder_rest` sem handler (1 carta, OP01-088).
- `bounce` puro (2, avaliado como fora de escopo em sessão anterior).
- `substitute_ko`/`immunity`/`negate_effect` combinados (4, mecânicas
  distintas que merecem auditoria própria).
- 3 cartas com semântica ambígua de alvo no debuff (OP02-089, OP04-017,
  OP09-097).
- 4 cartas puramente de busca/play sem buff (fora do framework atual).

---

## 2026-06-30 (7) - Claude

**Feito - KO via Counter event:** terceiro e último mecanismo de Counter
event desta sequência de auditoria, item que tinha ficado explicitamente
pendente no handoff anterior. 4 cartas ("[Counter] K.O. up to 1 of your
opponent's Characters with cost/power N or less[, rested only]" — EB01-010,
OP08-094, OP10-040, OP13-039) removem o atacante INTEIRAMENTE antes do dano,
cancelando o ataque por completo — não é uma redução de power como os dois
mecanismos anteriores (buff de defesa / debuff do atacante), é cancelamento
total.

Implementei `_counter_event_ko_plan` + `try_counter_event_ko_attacker` em
[decision_engine.py](scriptis_da_ia/optcg_engine/decision_engine.py),
chamadas no fluxo de `_resolve_attack` logo depois do debuff do atacante não
bastar e antes do Damage Step — se ativar, `return False` direto. Respeita
imunidade/substituição do atacante com a mesma checagem do `ko` genérico
(`ko_context='effect'`, já que isto é o efeito do Counter event, não dano em
combate). `rested_only` é satisfeito trivialmente porque o atacante já fica
`rested=True` ao declarar o ataque, bem antes do Counter Step rodar. Escopo
mínimo de novo: exige exatamente 1 step `ko` com `target='opp_character'` e
nenhum outro step.

**Validação:** `python -m py_compile`; `python smoke_test.py` (72/72, 4
casos novos cobrindo ativação por `power_lte`/`cost_lte`+`rested_only` e os
respectivos casos negativos); `python smoke_test_broad.py` (40/40); `python
audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0
anomalias nas duas).

**Estado da auditoria de Counter events nesta sequência (encerrada por
ora):** dos 78 eventos `[Counter]` originalmente fora da heurística, agora
restam fora de escopo: `play_card`/`play_from_deck`/busca em deck (9
cartas, lógica de seleção mais complexa — próximo candidato natural se
alguém quiser continuar), `bounce` puro (2, avaliado como fora de escopo em
sessão anterior), `substitute_ko`/`immunity`/`negate_effect` combinados (4,
mecânicas distintas que merecem auditoria própria), e 3 cartas com semântica
ambígua de alvo no debuff (OP02-089, OP04-017, OP09-097).

---

## 2026-06-30 (6) - Claude

**Feito - Counter events que enfraquecem o ATACANTE:** mecânica nova,
distinta de tudo que já existia (que sempre buffava a PRÓPRIA defesa). 5
cartas no banco são "[Counter] Give up to 1 of your opponent's Leader or
Character cards -X power during this turn" (OP01-028, OP03-017, OP07-075,
OP15-021, ST09-014) — reduzem o `atk_power` do atacante diretamente.

Implementei `_counter_event_debuff_plan` + `try_counter_event_debuff` em
[decision_engine.py](scriptis_da_ia/optcg_engine/decision_engine.py),
chamada como fallback no fluxo de `_resolve_attack` logo depois que
`try_counter_event_power` (buff da própria defesa) não bastar sozinho —
`atk_power -= amount`, mutando `attacker.power_buff` de verdade (não é só
matemática local; o atacante fica realmente mais fraco pro resto do turno,
consistente com o texto "during this turn"). Escopo deliberadamente mínimo:
exige EXATAMENTE 1 `debuff_power` no bloco `counter` e nenhum outro step —
deixei de fora 3 cartas com semântica ambígua de alvo (OP02-089 "total of
2... -3000" com distribuição não clara, OP04-017 com 2 debuffs sequenciais
sem o marcador "that card" que o padrão de buff bonus usa, OP09-097 que
combina com `negate_effect`, ainda sem handler).

**Validação:** `python -m py_compile`; `python smoke_test.py` (68/68, 4 casos
novos cobrindo ativação, debuff insuficiente, mismatch de target_type
leader/character, e condição de vida no nível do block); `python
smoke_test_broad.py` (40/40); `python audit_replay.py --n 20 --seed 7` e
`--n 15 --seed 99` (0 exceções, 0 anomalias nas duas).

**Ainda falta (ver TODO.md):**
- **KO via Counter event** (4 cartas: EB01-010, OP08-094, OP10-040,
  OP13-039) — "[Counter] K.O. up to 1 of your opponent's Characters..."
  remove o atacante inteiramente ANTES do dano, cancelando o ataque por
  completo. É um mecanismo de cancelamento, não uma redução de power —
  precisa de um ponto de injeção próprio no fluxo de `_resolve_attack`
  (provavelmente logo após o Blocker), distinto dos dois mecanismos já
  implementados (buff da defesa / debuff do atacante).
- `play_card`/`play_from_deck`/busca em deck (9 cartas, lógica de seleção
  mais complexa).
- `bounce` puro (2, já avaliado como fora de escopo em sessão anterior).
- `substitute_ko`/`immunity`/`negate_effect` combinados (4, mecânicas
  distintas que merecem auditoria própria).

---

## 2026-06-30 (5) - Claude

**Feito - Counter events: duration='this_turn' + select_filtered:**
continuação direta da auditoria dos 44 eventos `[Counter]` sem nenhum
`buff_power(battle_only)`. Achei que 14 deles tinham um único `buff_power`
mas com `duration='this_turn'` em vez de `battle_only` — o planner exigia
`battle_only` estritamente e descartava esses casos.

1. **`this_turn` também conta como defesa de batalha**: o Counter Step só
   acontece DENTRO da resolução da batalha em curso, e o resto do engine já
   trata `'this_turn'`/`'battle_only'` de forma idêntica na limpeza (reset
   de `power_buff` no início do turno) — então restringir a `battle_only` era
   conservador demais sem necessidade. Ampliei o filtro em
   `_counter_event_power_plan`. Desbloqueia 5 cartas com `target` já
   suportado: OP04-037, OP04-076, OP06-017, OP09-039, OP13-077.
2. **Novo `target_rule='select_filtered'`**: as outras 9 cartas usam "Up to
   1 of your [Tipo] Leader or Character cards gains +X power" — o alvo é
   escolhido por filtro de tipo, não necessariamente o defensor. Validação
   importante: só conta como defesa válida se o **alvo real sob ataque**
   bater no `filter_type` (via `card_matches_filter`), senão a carta
   buffaria outro aliado qualquer que não impede o hit desta batalha
   especificamente. Desbloqueia EB03-029, EB04-019, EB04-029, OP07-018,
   OP14-117, OP15-038, OP15-074, OP15-075, OP15-076.

Cobertura de Counter events com buff `battle_only`/`this_turn` foi de
114/180 pra 128/180.

**Validação:** `python -m py_compile`; `python smoke_test.py` (64/64, 5 casos
novos cobrindo `this_turn` e `select_filtered` positivo/negativo); `python
smoke_test_broad.py` (40/40); `python audit_replay.py --n 20 --seed 7` e
`--n 15 --seed 99` (0 exceções, 0 anomalias nas duas).

**Ainda falta (ver TODO.md):** os 30 eventos `[Counter]` restantes — KO puro
(4), debuff puro do atacante (6+1 duplo), `play_card`/`play_from_deck`/busca
em deck (9, lógica de seleção mais complexa), `bounce` puro (2, já avaliado
como fora de escopo da rota defensiva em sessão anterior), `substitute_ko`/
`immunity`/`negate_effect` combinados (4, mecânicas distintas que merecem
auditoria própria) e alguns casos mistos únicos.

---

## 2026-06-30 (4) - Claude

**Feito - fatia de Counter events: 2º buff condicional + extras simples:**
voltei à auditoria original de Counter events (78 eventos `[Counter]` fora
da heurística antes desta sessão). Categorizei os 78 em: 44 sem nenhum
`buff_power(battle_only)` (padrões totalmente diferentes — KO puro, debuff
puro do atacante, etc., fora de escopo hoje), 8 com 2 `buff_power
(battle_only)`, e o resto com 1 buff + alguma extra ainda não suportada.

1. **8 cartas com 2 buffs `battle_only`** (EB03-020, OP04-095, OP05-114,
   OP06-038, OP07-035, OP07-095, OP11-059, OP12-098): conferi o texto real
   e confirmei que o padrão é sempre "Up to 1 of your Leader or Character
   cards gains +X power... Then, if [cond], **that card** gains an
   additional +Y power" — o 2º buff (`target='self'` no parser, na real
   "that card") é BÔNUS condicional ao MESMO alvo do 1º, não um alvo
   independente. Generalizei `_counter_event_power_plan` em
   [decision_engine.py](scriptis_da_ia/optcg_engine/decision_engine.py) pra
   somar quantos `buff_power(battle_only)` existirem, com a regra: o
   primeiro define o alvo (leader/own_character/leader_or_character), os
   demais só entram se `target='self'` e sua própria `conditions` passar.
2. **Extras simples desbloqueados**: `trash_from_deck_top`, `peek_life`,
   `add_from_trash`, `gain_life` adicionados a `safe_extra_actions` — todos
   já tinham handler genérico em `_execute_step`, sem seleção complexa.
   Desbloqueia OP03-054, OP03-055, OP08-096, ST07-016, ST13-017, OP11-097,
   OP12-115, ST09-015.

Cobertura de Counter events com buff `battle_only` foi de 102/180 pra
114/180.

**Validação:** `python -m py_compile`; `python smoke_test.py` (61/61, 9 casos
novos cobrindo multi-buff condicional/incondicional e os 4 extras novos);
`python smoke_test_broad.py` (40/40); `python audit_replay.py --n 20 --seed
7` (0 exceções, 0 anomalias).

**Ainda falta (ver auditoria completa no TODO.md):** os 44 eventos `[Counter]`
sem nenhum `buff_power(battle_only)` (padrões mecanicamente diferentes:
KO/debuff/bounce puro do atacante, draw/buscas isoladas) e `play_card`/
`play_from_deck`/`look_top_deck`+`add_to_hand` (9 cartas, busca mais
complexa) continuam fora da heurística atual.

---

## 2026-06-30 (3) - Claude

**Feito - implementa `debuff_power` (achado durante auditoria de Counter
events) + corrige power negativo:** ao auditar a fatia seguinte de Counter
events (extras agressivos/estado complexo), achei que `debuff_power` nunca
teve handler de execução em `_execute_step` — só era reconhecido em
`_step_is_viable` e em heurísticas de score. Era no-op silencioso em **142
steps reais** no banco, em quase todos os timings (on_play, when_attacking,
main, activate_main, counter, trigger, on_opp_attack, etc.), não só Counter
events. Perguntei ao usuário se queria escopo pequeno (pular debuff_power) ou
corrigir a causa raiz — escolheu corrigir.

1. Implementado `if action == 'debuff_power':` em
   [decision_engine.py](scriptis_da_ia/optcg_engine/decision_engine.py),
   espelhando `buff_power` só que no lado do oponente. 4 targets reais:
   `opp_character`/`opp_leader_or_character` (alvo mais valioso via
   `choose_highest_board_value`, cai no Leader se o campo do oponente está
   vazio), `all_opp_characters`, `opp_leader`. Parser nunca emite
   filtro/count pra esses alvos — sempre 1 escolha automática da IA.
2. Adicionado `debuff_power` em `safe_extra_actions` dos Counter events
   (objetivo original da fatia) — desbloqueia OP08-017, OP10-018, OP12-018,
   ST29-015 (buff de batalha + debuff do atacante).
3. **`audit_replay.py` pegou um bug real na primeira rodada**: Characters
   ficando com power negativo (Otama, Jozu) — `effective_card_power()`
   (`rules_facade.py`) não tinha piso em 0. Corrigido com `max(0, ...)`.

**Validação:** `python -m py_compile`; `python smoke_test.py` (50/50, 6 casos
novos cobrindo os 4 targets de debuff_power + integração real com OP10-018);
`python smoke_test_broad.py` (40/40); `python audit_replay.py --n 5 --seed
42` (0 anomalias, depois do fix do power negativo) e `--n 20 --seed 7` (0
exceções, 0 anomalias, amostra maior por ser mudança ampla).

**Ainda falta:** a fatia original de Counter events (extras agressivos:
`play_card`, buscas/topdeck, múltiplos buffs no mesmo evento) continua
pendente — esta sessão desviou pra consertar o achado de `debuff_power`
antes. Ver TODO.md para a lista completa de extras ainda não suportados (78
eventos `[Counter]` fora da heurística atual).

---

## 2026-06-30 (2) - Claude

**Feito - auditoria de OP11-005/OP11-046 + 2 bugs corrigidos:** a pendência
"variantes não parseadas como OP11-005/OP11-046" do HANDOFF anterior era na
verdade um bug de parser, não um caso novo de regra.

1. **Bug do parser (`gerar_effects_db.py`):** `'blocker'` está em
   `TODAS_TAGS` (delimitador para os OUTROS blocos pararem em `[Blocker]`),
   mas não tem `trigger_pattern` próprio. Texto que vem DEPOIS do parêntese
   de regra do Blocker era descartado por inteiro — nenhum dos 3 caminhos de
   fallback cobria esse caso. Afetava 4 cartas: OP11-005 (imunidade KO
   condicionada a DON x1 contra Characters sem Special), OP11-046 (imunidade
   KO condicionada a "só ter Characters GERMA"), OP11-088 (buff de
   counter-attack) e ST10-014 (draw/trash). Corrigido com um novo segmento
   "pós-Blocker" em `parse_card_effect`.
2. **Bug de condição nunca checada:** a condição `only_field_type` ("if you
   only have Characters with type X") era parseada desde 29/06/2026 mas
   NUNCA era lida nem por `_check_conditions` (EffectExecutor) nem por
   `_immunity_conds_met` (caminho específico de imunidade) — o efeito era
   tratado como incondicional. Afetava as 6 cartas que já usavam essa
   condição (EB02-010, OP05-084, OP05-092, OP13-097, OP15-001, OP16-022)
   além da nova OP11-046. Ambos os checkers agora respeitam `only_field_type`.

**Validação:** `python -m py_compile`; `python diff_parser.py` (`GANHOU=0
PERDEU=0`, 4 MUDOU = exatamente as 4 cartas esperadas); `python gerar_dbs.py`
+ `python snapshot_parser.py`; `python smoke_test.py` (45/45, com 7 casos
novos cobrindo os dois bugs); `python smoke_test_broad.py` (40/40); `python
audit_replay.py --n 5 --seed 42` (0 anomalias — turnos mudaram em 2 das 5
partidas, esperado já que comportamento real mudou).

**Ainda falta:** a família grande de substituição externa (eventos
`[Counter]` com efeitos extras agressivos/estado complexo) é a próxima fatia
combinada com o usuário.

---

## 2026-06-30 - Claude

**Feito - imunidade KO em batalha por atributo/fonte do atacante:** próxima
fatia da pendência deixada pela sessão anterior. `_source_matches_battle_ko_immunity()`
(novo) compara a sentença de imunidade (extraída por `_ko_sentence()`, fatorado
de `_ko_immunity_applies_to_context()`) com o atacante (`source_card`) para os
padrões "by Leaders", "by Characters without [Special]" e "by [Strike/Slash/
Special/Wisdom/Ranged] attribute Characters". `is_immune()` e o caminho de KO em
combate (`OPTCGMatch`) agora passam `source_card=attacker`.

**Validação:** `python -m py_compile scriptis_da_ia\smoke_test.py
scriptis_da_ia\optcg_engine\decision_engine.py`; `python
scriptis_da_ia\smoke_test.py` (38/38); `python smoke_test_broad.py` (40/40);
`python audit_replay.py --n 5 --seed 42` (0 anomalias).

**Ainda falta:** variantes de imunidade não parseadas como `immunity` ainda
(ex.: OP11-005/OP11-046), e a família grande de substituição externa (ver
seção de dívida técnica no TODO.md).

## 2026-06-30 - Codex

**Feito - imunidade KO por contexto:** `is_immune()` agora recebe `ko_context`
para diferenciar KO por efeito (`effect`) de KO em batalha (`battle`). O helper
usa o texto bruto da carta para impedir que `cannot be K.O.'d in battle`
proteja contra efeitos, e que `cannot be K.O.'d by effects` proteja contra
combate. Chamadores principais atualizados: executor de KO por efeito e
resolucao de combate.

**Validacao:** `python -m py_compile scriptis_da_ia\smoke_test.py
scriptis_da_ia\optcg_engine\decision_engine.py`; `python
scriptis_da_ia\smoke_test.py`; `python audit_replay.py --n 5 --seed 42`;
`python smoke_test_broad.py` (40/40).

**Ainda falta:** imunidade por atributo/fonte do atacante (`Strike`, `Slash`,
`Special`, `Leaders`) e variantes que o parser ainda nao transformou em
`immunity` (ex.: OP11-005/OP11-046).

## 2026-06-29 23:35 - Codex

**Update posterior - Counter buff simples:** implementada a primeira fatia de
execucao de eventos `[Counter]`: eventos com um unico `buff_power` defensivo
(`battle_only`) agora podem ser usados no Counter Step se o buff sozinho impedir
o hit. A selecao escolhe o evento suficiente com menor excesso de power, respeita
DON disponivel, custos simples de `trash_from_hand` e condicoes `leader_type`.
Auditoria antes da implementacao encontrou 70 eventos nesse formato. Smoke cobre:
buff no leader, custo extra de trash, target leader-only recusando Character e
condicao `leader_type` errada/certa.

**Update posterior - Counter draw + buff:** o helper de Counter agora aceita
blocos com um unico buff defensivo `battle_only` mais steps `draw` seguros. O
draw e executado depois de pagar o evento/custos e respeita condicoes no step.
Smoke cobre `draw + buff`, `buff + draw` condicional falhando e passando.

**Update posterior - Counter set/rest + buff:** o helper tambem aceita extras
seguros `set_active` e `rest_opp_character` junto de um unico buff defensivo
`battle_only`. Smoke cobre `OP01-057` reativando Character proprio e `OP01-058`
restando Character do oponente. Validado com broad `40/40` e audit replay sem
anomalias.

**Update posterior - Counter DON + buff:** implementado executor para `add_don`
e o helper de Counter passou a aceitar extras seguros `add_don` e
`set_don_active`. Smoke cobre `OP01-119` adicionando DON ativo com condicao de
vida, a mesma carta sem a condicao ativa, e `ST02-016` reativando DON rested.

**Update posterior - Counter removal + buff:** o helper de Counter tambem aceita
extras de remocao simples junto de um unico buff defensivo: `ko`, `bounce` e
`place_opp_character_bottom_deck`. Na base atual isso habilita KO+buff e
bottom-deck+buff; bounce existente e puro e segue fora da rota defensiva. Smoke
cobre `OP01-026`, `OP04-057` e garante que `ST03-016` (bounce puro) nao ativa.

**Update posterior - EB02-030:** implementado suporte estreito para Counter event
com `counter -> substitute_ko` e custo `trash_from_hand` no K.O. em batalha.
Hoje so existe 1 caso no banco (`EB02-030`). O evento agora exige DON suficiente,
vai para o trash, trasha 1 carta da mao e preserva o Character alvo. Smoke cobre
ativacao e bloqueio por DON insuficiente.

**Feito** - primeira fatia de substituição externa no executor:
- `try_any_substitute()` tenta primeiro a substituição do próprio alvo e depois
  procura fontes aliadas em campo, leader e stage.
- Fontes externas só protegem quando o step/bloco tem filtro de alvo
  estruturado (`filter_type`, `filter_name`, custo/power/rested ou condições
  target-like). Isso evita que cartas cujo parser perdeu filtro passem a
  proteger qualquer coisa por acidente.
- Caminhos de KO/removal por efeito e KO em combate agora chamam
  `try_any_substitute()`.
- Custo `rest_self_and_trash_hand` foi adicionado para substituições externas
  já parseadas nesse formato.
- Smoke novo cobre fonte externa protegendo alvo filtrado e recusando alvo fora
  do filtro.

**Parser/data coverage nesta fatia:** `gerar_effects_db.py` agora extrai filtros
do alvo protegido em substituições quando o sujeito da frase é claro. Exemplos
confirmados no banco regenerado: Monster ganhou `filter_name=bonk punch`,
Tashigi ganhou `filter_color=green` + `exclude=tashigi`, Sabo ganhou
`cost_lte=7` + `exclude=sabo`, Rosinante OP12-048 ganhou `filter_type=navy` +
`filter_color=blue`; ST30-009/ST30-011 ganharam `power_eq=6000`.
Resultado da auditoria rápida: 21 de 33 steps de
substituição têm filtro de alvo estruturado.

**Limite consciente:** ainda não fecha 100% das 38 cartas reais; faltam variantes
sem filtro extraível pelo sujeito simples e validação carta-a-carta em replay.

**Auditoria pós-commit dos 12 sem filtro:** 10/12 são `this Character`, então
estão corretos sem filtro externo porque o executor tenta primeiro a substituição
do próprio alvo. `OP07-042` também é self, mas o sujeito vem composto com
condição de leader; não precisa de mudança de comportamento. O único caso
conceitualmente diferente é `EB02-030`, que é evento `[Counter]` protegendo
`any of your Characters` em batalha. O motor ainda não executa Counter events
como efeitos, só soma counter impresso da mão; isso deve virar uma fatia própria.

**Validação:**
- `python -m py_compile scriptis_da_ia\smoke_test.py scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40`.

---

Regra: antes de parar (créditos, fim de sessão, etc.), escreva um bloco novo
no TOPO deste arquivo com data/hora, o que foi feito, e o que falta. Quem
assumir a sessão seguinte deve ler este arquivo + rodar `git log --oneline -10`
e `git status` antes de tocar em qualquer coisa.

---

## 2026-06-29 23:11 — Codex

**Feito** — auditoria de imunidade/substituição por texto bruto:
- 220 cartas batem em padrões amplos (`cannot be K.O.'d`, `cannot be removed`,
  `would be removed/K.O.'d`, `instead`, etc.).
- `substitution_text_without_substitute_action = 0`: todo texto com padrão
  claro de substituição já tem alguma action estruturada (`substitute_ko` ou
  `substitute_removal`) ou foi classificado em outra mecânica.
- `extra_steps` em substituição existia no banco para 2 cartas (`OP08-045`
  Thatch e `ST30-009` LittleOars Jr.), mas o executor pagava o custo e ignorava
  o efeito extra. Corrigido: após pagar a substituição, `_execute_step()` roda
  cada `extra_step`. Smoke novo valida `trash_self + draw`.

**Achado importante ainda aberto:** substituições por FONTE EXTERNA. Há cerca de
38 textos do tipo "if your [outro] Character would be removed/K.O.'d, you may
[fazer algo com esta carta/leader/mão] instead". O engine atual chama
`try_substitute(target, ...)`, então ele olha principalmente os efeitos do alvo,
não de aliados/líder que poderiam proteger o alvo. Corrigir isso exige separar
explicitamente `target` e `source` no executor; não é só regex.

**Validação:**
- `python -m py_compile scriptis_da_ia\smoke_test.py scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40`.

**Próximo:** implementar substituição externa com assinatura do tipo
`try_substitute(target, removal_kind, source=None)` ou método novo que procura
fontes protetoras no campo/líder, aplicando custo no `source` e efeito no
`target` quando o texto diz "that Character".

**Estado após esta fatia:** esperado commit/push com
`scriptis_da_ia/optcg_engine/decision_engine.py`, `scriptis_da_ia/smoke_test.py`,
`HANDOFF.md` e `TODO.md`.

---

## 2026-06-29 23:01 — Codex

**Feito** — primeira fatia do sistema de imunidade. A auditoria mostrou que a
família não estava mais "inteira ausente": há 52 `action='immunity'` parseadas
no banco (`ko`: 41, `removal`: 11), e os caminhos principais de KO/removal já
consultavam `is_immune()` (KO/trash por efeito, bounce, bottom deck e KO em
combate).

**Bug corrigido:** em `ko`/`trash` com `target='all_character'`, a engine sempre
passava `source_is_opp=True`. Isso fazia imunidade "by opponent's effects"
proteger também contra efeitos próprios, o que é errado. Agora `source_is_opp`
é calculado por dono do alvo: se meu efeito remove meu próprio personagem, não
conta como efeito do oponente.

**Validação:**
- `python -m py_compile scriptis_da_ia\smoke_test.py scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou, com testes diretos para:
  imunidade `source=opp` não proteger contra KO próprio; e proteger contra KO
  vindo do oponente.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40`.

**Próximo:** continuar imunidade, mas agora como cobertura/variantes: auditar
textos de `EffectImmune`, `CombatImmune`, `ImmuneToStrikes`, e substituições
"would be removed/K.O.'d ... instead" que podem ainda estar fora de `immunity`
ou parcialmente em `substitute_*`.

**Estado após esta fatia:** esperado commit/push com
`scriptis_da_ia/optcg_engine/decision_engine.py`, `scriptis_da_ia/smoke_test.py`,
`HANDOFF.md` e `TODO.md`.

---

## 2026-06-29 22:53 — Codex

**Feito** — `can_lethal_this_turn` deixou de espiar counters reais da mão oculta
do oponente. A análise agora usa:
- cartas reveladas na mão (`known_hand_cards`) pelo counter real;
- slots ocultos apenas por tamanho de mão, com a mesma densidade típica já usada
  por `opp_counter_potential`;
- chunks de 1000 para ser conservador a favor da defesa.

**Validação:**
- `python -m py_compile scriptis_da_ia\smoke_test.py scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou, incluindo regressão que compara
  mão oculta com counter real vs mão oculta sem counter: resultado igual.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40`.

**Próximo:** sistema de imunidade, na ordem combinada. Primeiro mapear actions
`immunity` já parseadas e todos os pontos de remoção/KO/combate que precisam
consultar `is_immune`.

**Estado após esta fatia:** esperado commit/push com
`scriptis_da_ia/optcg_engine/decision_engine.py`, `scriptis_da_ia/smoke_test.py`,
`HANDOFF.md` e `TODO.md`.

---

## 2026-06-29 22:48 — Codex

**Feito** — fechados os 2 erros visíveis de replay que abririam a fila:
- `_choose_to_trash` deixou de descartar "evento sem trigger de menor custo" às
  cegas. Agora usa valor situacional (`DecisionEngine.avaliar_carta`) com bônus
  para evento defensivo/removal/search/draw. Isso preserva `Ground Death` quando
  há descarte realmente pior na mão.
- Five Elders com Mary Geoise: confirmado que o custo efetivo é 9, mas a reserva
  defensiva de DON tirava a carta da lista de ações antes do planner comparar.
  Agora corpos premium (`cost >= 8` ou `power >= 9000`) podem disputar o uso do
  DON reservado; o planner ainda decide se a linha vale.

**Validação:**
- `python -m py_compile scriptis_da_ia\smoke_test.py scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou, com regressões novas para
  Ground Death e Five Elders/Mary Geoise.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40`.

**Próximo:** seguir a ordem combinada: `can_lethal_this_turn` não deve ler a mão
real do oponente para estimar counters; precisa usar informação conhecida ou
estimativa/modelo.

**Estado após esta fatia:** esperado commit/push com
`scriptis_da_ia/optcg_engine/decision_engine.py`, `scriptis_da_ia/smoke_test.py`,
`HANDOFF.md` e `TODO.md`.

---

## 2026-06-29 13:17 — Codex

**Feito** — reduzida a quantidade de simulações por decisão no Turn Planner sem
voltar ao modo guloso. `main_phase()` continua olhando até `TOP_K=6`, mas agora
sempre simula as 3 melhores ações e só inclui a 4ª-6ª se estiverem a até 180
pontos da melhor ação imediata. Também evita gerar amostras Monte Carlo quando
só existe uma candidata.

**Validação/performance:**
- `python -m py_compile scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40` em ~86s.
- `python audit_replay.py --n 10 --seed 42` passou com 0 anomalias em ~17.3s
  (antes desta fatia: ~24.2s na mesma medição curta).

**Observação:** esta é uma poda conservadora por score, não uma prova de ótima
jogada. O risco residual é alguma 4ª-6ª ação com score imediato baixo produzir
linha futura muito melhor; por isso mantive no mínimo 3 candidatas e uma janela
generosa.

**Estado após esta fatia:** esperado commit/push com
`scriptis_da_ia/optcg_engine/decision_engine.py`, `HANDOFF.md` e `TODO.md`.

---

## 2026-06-29 13:11 — Codex

**Feito** — adicionada cópia manual de `GameState.__deepcopy__` para o Turn
Planner. `Card` já tinha clone customizado; `GameState` ainda usava o caminho
genérico do dataclass. A nova cópia replica zonas, flags e contadores de forma
explícita e preserva referências internas via `memo` (ex: `end_of_turn_queue`
apontando para uma carta também presente em uma zona).

**Validação/performance:**
- `python -m py_compile scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou.
- Teste direto de alias em `end_of_turn_queue` passou.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40` em ~144s.
- `python audit_replay.py --n 10 --seed 42` passou com 0 anomalias em ~24.2s
  (antes desta fatia: ~31.5s na mesma medição curta).

**Observação:** ainda não é a solução final do planner. O clone ficou mais
barato, mas `_simulate_sequence*` continua clonando muitos estados. Próxima
fatia estrutural deve reduzir quantidade de clones ou reaproveitar avaliação
de estados, não aumentar complexidade de regras.

**Estado após esta fatia:** esperado commit/push com
`scriptis_da_ia/optcg_engine/decision_engine.py`, `HANDOFF.md` e `TODO.md`.

---

## 2026-06-29 02:28 — Codex

**Feito** — aplicada uma otimização estrutural pequena no Turn Planner:
`_generate_and_score_actions()` agora calcula a reserva defensiva de DON uma vez
por estado e passa `don_usable` para `_can_play_card()`, em vez de recalcular
`_don_reserve_for_defense()` para cada carta da mão. Também reaproveita a
`analysis_priority()` já calculada ao gerar ações de anexar DON.

**Validação/performance:**
- `python -m py_compile scriptis_da_ia\optcg_engine\decision_engine.py` passou.
- `python scriptis_da_ia\smoke_test.py` passou.
- `python audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- `python smoke_test_broad.py` passou `40/40` em ~144s.
- `python audit_replay.py --n 10 --seed 42` passou com 0 anomalias em ~31.5s.

**Observação importante:** isso não elimina a dívida principal. O gargalo grande
continua sendo o uso pesado de `deepcopy` dentro de `_simulate_sequence*`; esta
mudança só remove recomputação repetida dentro do mesmo estado.

**Estado atual:** mudança ainda não commitada. Working tree deve ter
`scriptis_da_ia/optcg_engine/decision_engine.py`, este `HANDOFF.md` e `TODO.md`
se a nota de TODO for mantida.

---

## 2026-06-29 17:30 — Codex

**Feito** — investigada a lentidão pós-fechamento dos 5 gaps médios. `cProfile`
mostrou que o gargalo não era uma action nova isolada, e sim explosão do Turn
Planner: `_simulate_sequence`/`_simulate_sequence_once` chamavam milhares de
`deepcopy`, amplificado por `TOP_K=6`, `n_monte_carlo=20`, `max_steps=12`.

**Mudança aplicada:** reduzido o orçamento do planner para `max_steps=8` e
`n_monte_carlo=6`. Isso mantém o planner avaliando linhas, mas reduz o número
de simulações/deepcopies por decisão.

**Validação/performance:**
- Antes: 10 partidas aleatórias equivalentes ao broad levaram ~289s; broad 40
  não fechava em 300s.
- Depois: 10 partidas aleatórias fecharam em ~78s; `smoke_test_broad.py` fechou
  `40/40` em ~151s.
- `smoke_test.py` passou.
- `audit_replay.py --n 5 --seed 42` passou com 0 anomalias.
- Perfil de 1 partida caiu de ~24.6s para ~11.8s.

**Estado atual:** commitado e enviado em `9330cc7 Reduz custo do Turn Planner`.

**Próximo:** investigar otimização estrutural de verdade: reduzir `deepcopy` no
planner antes de mexer em qualidade de decisão.

---

## 2026-06-29 17:00 — Codex

**Feito** — fechados os 5 gaps médios que sobravam no cruzamento com o
simulador oficial:
- `PeekSelfLife/OppLife`: parser gera `peek_life`; engine olha/reordena Life
  própria ou do oponente.
- `TrashAllFaceUpLife`: adicionado `Card.life_face_up`; `gain_life` marca
  face-up/face-down; `turn_life_face_up/down` e `trash_own_life face='up'`
  executam a mecânica; face limpa quando a carta sai da Life.
- `ForceOpponent`: escolhas com "Your opponent chooses one" agora carregam
  `choice_chooser='opponent'`; `opp_bounce_own_character` respeita escolha do
  oponente/filtro de custo; `opp_choose_trash_our_hand` cobre Kanjuro-like.
- `QueueUpEndOfTurnAction/OppMainPhase`: adicionado
  `GameState.end_of_turn_queue` + `OPTCGMatch.end_phase()`. Cobre `set_active`,
  `set_don_active`, `gain_life` marcados com `timing='end_of_turn'` e Black
  Maria (`return_don_until_match_opp`). OppMainPhase ficou sem carta real
  prioritária no pool atual.
- `FieldCantAttackLeader`: `cannot_attack_leader_this_turn` bloqueia geração e
  execução direta de ataques ao Leader durante o turno.

**Validado:** `python -m py_compile gerar_effects_db.py optcg_engine\decision_engine.py`;
`python gerar_dbs.py`; `python snapshot_parser.py`; `python smoke_test.py`;
`python audit_replay.py --n 5 --seed 42`; teste direto dos 5 gaps. `smoke_test_broad.py`
completo não terminou em 300s; teste equivalente com 10 partidas aleatórias
terminou sem exceção, mas lento (~289s). Isso é o principal risco a observar.

**Próximo:** investigar a regressão/perfil de performance antes de confiar em
simulações massivas. Dívida grande de imunidade continua fora desta fatia.

---

## 2026-06-29 03:00 — Claude

**Feito** — 2 itens rápidos pedidos pelo usuário pra fechar a sessão:
- **Removido `_main_phase_OLD_fixed`** (`decision_engine.py`) — versão
  antiga de `main_phase`, de antes do Turn Planner existir, confirmada
  como dead code (`grep` não achou chamada em lugar nenhum fora da
  própria definição). Tinha um bug de conservação de DON, mas nunca
  executava em produção. Removida só por higiene.
- **Formalizado `audit_replay.py`** como ferramenta permanente em
  `scriptis_da_ia/audit_replay.py` (antes vivia só no scratchpad da
  sessão anterior). Limpei a instrumentação de debug específica daquela
  investigação (os monkeypatches de rastreamento de `_attach_don_for_attack`/
  `_apply_action` que já cumpriram seu papel) e deixei só as checagens de
  invariante reutilizáveis: conservação de DON (com detector de
  duplicata por `id()` em `field_chars`), power negativo, conservação de
  contagem de cartas. Uso: `python audit_replay.py [--n N] [--seed S]`,
  sai com exit code 1 se achar exceção ou anomalia (dá pra plugar num
  CI/hook no futuro se quiser). Validado: roda limpo (25/25, 0 anomalias,
  exit 0) e `smoke_test.py`/`smoke_test_broad.py` continuam 100%/40-40
  depois da remoção do dead code.

**Estado atual:** tudo commitado e pushed, working tree limpo, sem
pendências da sessão de hoje além do que já está listado em `TODO.md`.

**Próximo:** 5 "médios" restantes sem urgência (PeekLife,
TrashAllFaceUpLife, ForceOpponent, QueueUpEndOfTurnAction/OppMainPhase,
FieldCantAttackLeader); sistema de imunidade (dívida consciente, fora de
escopo).

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
