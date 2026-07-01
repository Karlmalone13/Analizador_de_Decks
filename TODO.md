# TODO — Analisador de Decks OPTCG

**Última atualização:** 01 de julho de 2026 (sessão 22)
**Estado:** 2148 cards com efeito (subiu de 2138), parser auditado OP-02 a OP-15
**Baseline:** commit bbb4d31 (set_don_active + mill) + viabilidade transacional (a commitar)
**Repo:** github.com/Karlmalone13/Analizador_de_Decks

---

## Dívida técnica ativa — Turn Planner

- [x] **Reduzir `deepcopy` em `_simulate_sequence*`** — **implementado (02/07/2026).** `_SimDeck` (list subclass copy-on-pop lazy) aplicada ao `p.deck` + mesmo truque do `opp.deck`. Speedup 2.8× (0.85ms → 0.30ms/call, 31ms → 11ms/main_phase). Ver HANDOFF (13). a poda de orçamento já
  melhorou o runtime; a reserva defensiva agora é calculada uma vez por estado
  em `_generate_and_score_actions()`; e `GameState.__deepcopy__` já tem cópia
  manual mais enxuta. `main_phase()` também passou a simular no mínimo 3
  candidatas e só incluir a 4ª-6ª quando estiverem perto da melhor por score.
  Ainda assim, o gargalo estrutural continua sendo clonar estados demais dentro
  do planner. Próxima melhoria real deve atacar clone incremental ou cache
  seguro de avaliações por estado, medindo impacto em qualidade de decisão.

---

## 🟢 FEITO NESTA SESSÃO (25-26/06)

Sessão focada em destravar mecânicas sem branch no engine (auditoria por mecânica,
não carta-a-carta). Método: levantamento por mecânica → confirma regra com Arthur →
implementa → valida (snapshot/diff PERDEU=0 + partidas reais instrumentadas).

### Blocos implementados (commits 961b881, 16c616c, bbb4d31, + viabilidade)

- [x] **Life unificada** (961b881): parse_heal deletada (bug top/bottom), parse_life
  reescrita com eixos (source: deck_top/hand/own_field/opp_life/trash; dest: life_top/
  bottom/top_or_bottom; count; up_to; face). 4 branches: gain_life, life_to_hand (novo,
  Hiyori OP06-106), attack_life, trash_own_life. life_to_hand como CUSTO suprimido
  (deixado p/ parse_costs). PERDEU=0, GANHOU=10.

- [x] **avaliar_carta usa flags do analysis_db** (16c616c): loader _ANALYSIS_DB +
  get_card_flags(). Trocada detecção por substring frágil pelas flags limpas
  (kos/is_removal/bounces/etc), cobertura ampliada (gives_don/gains_life/power_buff),
  guarda KO-no-vácuo. _score_play_action também migrado.

- [x] **play_card no engine** (232 cartas, maior bloco): regra = jogar GRÁTIS.
  GRUPO 1 (114, trigger-self): própria carta da vida, OPCIONAL por score.
  GRUPO 2 (118, da mão): melhor carta elegível por filtro, "up to", guarda campo cheio.
  _should_activate_main reconhece play_card. cost_lte dinâmico. Instrumentado: 943+3611
  execuções reais antes no-op. Empty Throne ATIVA (replay confirma).

- [x] **mill** (bbb4d31): trash_from_deck_top como efeito (51). Trash seco do topo.
  Bug corrigido de brinde: convenção topo do deck no gain_life (pop(0)→pop()).

- [x] **set_don_active** (bbb4d31): 56 cartas. Parser ganhou count/up_to; engine ganhou
  branch (rested→available). PERDEU=0.

- [x] **Viabilidade transacional** (a commitar): _step_is_viable + checagem antes de
  pagar custo. Se NENHUM step produz efeito real, não ativa e não paga. Regra AMPLA
  (minimiza jogadas-erro). Resolve desperdício Empty Throne (replay T7/9/11 ativava 3x
  sem jogar). Vale p/ TODA mecânica opcional. Validado.

### Comparação com simulador oficial (26/06)
- [x] Cruzamento ActV3 (simulador) × nossas actions — ver comparacao_simulador_vs_IA.md.
  Fonte: DLL 34.127 linhas, 100% lida. 39 cobertos, 28 ausentes (8 relevantes, 7 médios,
  13 raros). CONCLUSÃO: arquitetura está certa (trigger/condition/cost/step espelha
  proc/details/effect). Buracos são de cobertura, finitos.

---

## 🔴 PRÓXIMO (decisão via log real)

- [ ] **Comparação IA vs humano a partir do parse_combat_log**: dado um turno do JSON gerado pelo parser, instanciar o GameState equivalente no engine e ver o que a IA escolheria. Identificar divergências concretas para tunar scores/heurísticas. Script ainda não existe — próxima sessão.
- [ ] **[B] handlers sem log**: `look_top_deck`, `negate_effect`, `activate_trash_event_main`, `lock_opp_don` — efeitos que executam sem emitir evento no replay.

---

## 🔴 PROBLEMAS ABERTOS (replay Imu vs Sanji, 26/06)

- [x] ~~**Problema 2 — _choose_to_trash não avalia qualidade**~~: corrigido em
  29/06/2026. O descarte agora usa valor situacional e preserva eventos
  defensivos/removal como Ground Death quando há descarte pior.
- [x] ~~**Problema 3 — Five Elders (c10) nunca jogada**~~: corrigido em
  29/06/2026. Mary Geoise reduz o custo para 9; corpos premium agora podem
  disputar DON reservado em vez de serem filtrados antes do Turn Planner.

---

## 🔴 BURACOS DE MECÂNICA (cruzamento com simulador) — priorizados

> **CORRIGIDO em 28/06/2026** — lista original (`comparacao_simulador_vs_IA.md`)
> buscou só por nome literal no C#, sem checar sinônimos no Python. Re-auditada
> item a item contra `decision_engine.py`: DealDamage, ShuffleHandIntoDeck e
> CycleEntireHandToDeckBottom **já estavam implementados**. Lista abaixo reflete
> o estado real, verificado por linha de código.

### Achado/corrigido em 29/06/2026 — bug de identidade em `Card` (auditoria via replay real)
- [x] ~~Carta duplicada por REFERÊNCIA (mesmo objeto Python 2x) em
  `field_chars`~~ — achado pela auditoria #3 do plano do usuário (rodar
  partidas reais instrumentadas em vez de só seguir a lista teórica de
  gaps), não por nenhum gap conhecido. `Card` é `@dataclass` sem
  `eq=False`, então `__eq__`/`__hash__` são gerados por VALOR (todos os
  campos), de propósito — `_remap_action` (Turn Planner, ~linha 5064)
  depende disso pra mapear uma ação do estado real pro clone (deepcopy)
  via `.index(obj)`, já que objetos pós-deepcopy nunca são `is` o
  original. Efeito colateral: quando 2+ cópias físicas da MESMA carta
  com o MESMO estado (ex: recém compradas) coexistem na mesma zona,
  `list.remove(card)`/`card in lista` ficam ambíguos — podem
  remover/casar uma cópia IRMÃ em vez da carta exata. Reproduzido em 2 de
  25 partidas reais aleatórias (seed=42): "St. Topman Warcury" e
  "Roronoa Zoro - PRB" jogados, mas a remoção da mão removeu a cópia
  errada, deixando a carta realmente jogada ainda lá; numa iteração
  seguinte do Turn Planner ela foi selecionada e jogada DE NOVO, virando
  o MESMO objeto duas vezes em `field_chars` (inflava DON somado e
  board_value — quebrava a invariante "don_available + don_rested +
  don_attached em campo == 10 − don_deck"). Corrigido com 2 helpers de
  identidade (`remove_by_identity`/`contains_identity`,
  `decision_engine.py` ~linha 591) e substituição de ~35 call sites de
  `.remove(card)`/`in`/`not in` em zonas (`hand`, `field_chars`, `trash`,
  `deck`, listas de candidatos temporárias) por versão baseada em `is`,
  SEM tocar em `_remap_action` (continua por valor, de propósito).
  Validado: `smoke_test.py` 100%, `smoke_test_broad.py` 40/40, e
  `audit_replay.py` 25/25 partidas reais sem nenhuma anomalia (antes da
  correção: 6 anomalias de conservação de DON em 2 partidas). O script de
  auditoria foi formalizado como ferramenta permanente em
  `scriptis_da_ia/audit_replay.py` (`python audit_replay.py [--n N]
  [--seed S]`, exit code 1 se achar exceção/anomalia) — útil pra rodar
  depois de qualquer mudança no `decision_engine.py` que não seja
  parser-only, complementar ao `smoke_test_broad.py` (que só checa "não
  lançou excecao", não invariantes de estado).
- [x] ~~Dead code `_main_phase_OLD_fixed`~~ — removido (`decision_engine.py`).
  Versão antiga de `main_phase` (pré Turn Planner), confirmada sem
  nenhuma chamada no código (`grep` não achou uso fora da própria
  definição). Continha um bug de conservação de DON (`don_rested +=
  don_amt` duplicava o valor) que NUNCA foi a causa de nada em produção
  por estar morta — removida só por higiene, sem efeito funcional.

### Achado/corrigido em 28/06/2026, 3ª rodada do dia (fora dos gaps originais)
- [x] ~~`buff_power` target='own_character' não consumido pelo engine~~ —
  achado ao investigar o gap de memória de alvo acima. O parser já gerava
  esse target (15 cartas reais: EB04-009, OP03-039, OP08-018, OP08-019 (x2),
  OP08-095, OP08-103, OP10-092, OP12-001, OP12-016, OP12-018, OP12-019,
  OP13-022, P-011, ST13-001) mas o engine não tinha handler — caía no
  fallback sem aplicar nada (no-op silencioso). Implementado: seleciona
  entre `me.field_chars` (sem filtro de tipo, distinto de
  `select_filtered`) via `eligible_cards`, escolhe o melhor por
  `choose_highest_board_value`. Também corrigido o parser, que não
  capturava os filtros do texto (`power_lte` — "with N power or less",
  `exclude` — "other than [Nome]") — 3 cartas afetadas (OP10-092, OP12-001,
  OP13-022). `PERDEU=0`, smoke tests 100%, testado manualmente (sem
  filtro/com power_lte/com exclude, todos corretos).

### Gaps reais confirmados — 0 (todos resolvidos em 28/06/2026)
- [x] ~~"Memória de alvo entre steps" (`SaveTargetName`)~~ — **implementado em
  28/06/2026**: `EffectExecutor._last_selected` (zerado a cada `execute()`,
  preenchido por `buff_power` `target='select_filtered'`, consumido por
  `select_grant_unblockable_turn`/`lock_self_character_refresh`
  `target='selected'`). Resolveu OP07-057, OP12-077 (residuais de
  `OppNoBlockerThisTurn`) e EB02-021 (residual de Freeze). Exigiu também
  corrigir um bug PRÉ-EXISTENTE de ordem de despacho (sub-parsers do
  `parse_block` não seguem a ordem do texto — `steps.sort()` estável
  garante que quem seleciona executa antes de quem consome) e um bug
  pré-existente de target errado em `parse_power_buff` (padrão "up to N of
  your [Tipo] cards gains +X power" caía em `target='self'` por engano —
  corrigido para `select_filtered` com seleção real por filtro, afetando
  48 cartas que tinham esse padrão, todas verificadas como correção real,
  não regressão). OP12-016 (Rayleigh, alvo = quem recebeu DON!! de um
  CUSTO, não de um step) fica de fora — memória custo→efeito é mecanismo
  diferente, não implementado (raro, 1 carta). `PERDEU=0`, smoke tests
  100%, testes diretos do mecanismo (select_filtered + selected, com e sem
  memória prévia) passando.
- [x] ~~CantPlayAnyCardsFromHand / CantPlayAnyCharactersToField direcionado ao
  oponente~~ — **investigado em 28/06/2026, 0 cartas reais no banco**.
  Buscado "opponent cannot play"/"can't play" em todas as formas — as 18
  cartas com "cannot play" são TODAS auto-aplicadas (custo de ramp de DON,
  já cobertas por `self_cant_play`). O exemplo "Imu" do doc original não
  corresponde a carta real do nosso pool. Não implementar especulativo —
  reabrir só se aparecer carta real.
- [x] ~~Freeze (don/stage/card)~~ — **implementado em 28/06/2026**:
  `frozen_next_refresh` (Card) + `frozen_don_count` (GameState), consumidos
  em `refresh_phase`. Cobre `lock_opp_character_refresh` (18 cartas,
  filtro cost_lte/cost_eq), `lock_opp_don_refresh` (1 carta),
  `lock_self_character_refresh` target='this_card' (1 carta, OP04-090).
  target='selected' (EB02-021) fica no item de memória de alvo acima.
  `PERDEU=0`, smoke tests 100%, testado manualmente (character/stage/DON
  congelados ficam rested 1 refresh e voltam ao normal na seguinte).
- [x] ~~DealDamage/TakeDamage~~ — já implementado (`deal_damage`)
- [x] ~~ShuffleHandIntoDeck / CycleEntireHandToDeckBottom~~ — já implementado
  (`shuffle_hand_into_deck`, parâmetro `dest`)
- [x] ~~OppNoBlockerThisTurn (maior parte)~~ — **implementado em 28/06/2026**:
  parser estendido (`gerar_effects_db.py`, regex `m_block_filtered`) para as
  3 variantes de texto que faltavam (OP11-013 "All", OP12-051 custo, ST21-016
  power). `PERDEU=0`, smoke tests OK. 17 de 20 cartas reais cobertas agora.
- [x] ~~Buff dinâmico (BuffSelf1KPerXTargets/BuffXPerGivenDon/BuffXPerTopDeckCost)~~
  — já estava implementado num commit anterior (`4f41178`) que nunca teve o
  snapshot/db regenerado; feito em 28/06/2026 (`gerar_dbs.py` + novo
  snapshot). 9 cartas corrigidas (estavam parseadas como buff FIXO, errado —
  ex: "+1000 per 3 rested DON" tratava como +1000 sempre).

### Fechado em 29/06/2026 -- 5 gaps medios restantes
- [x] ~~PeekSelfLife/OppLife~~ -- parser gera `peek_life`; engine olha/reordena Life propria ou do oponente com heuristica simples.
- [x] ~~TrashAllFaceUpLife~~ -- `Card.life_face_up` modela face da carta na Life; `gain_life face='up'`, `turn_life_face_up/down` e `trash_own_life face='up'` implementados.
- [x] ~~ForceOpponent~~ -- `choice_chooser='opponent'`, `opp_bounce_own_character` com escolha defensiva/filtro de custo, e `opp_choose_trash_our_hand`.
- [x] ~~QueueUpEndOfTurnAction/OppMainPhase~~ -- `GameState.end_of_turn_queue` + `OPTCGMatch.end_phase()`; cobre `set_active`, `set_don_active`, `gain_life` agendados e Black Maria (`return_don_until_match_opp`). OppMainPhase segue sem carta real prioritaria.
- [x] ~~FieldCantAttackLeader~~ -- `cannot_attack_leader_this_turn` bloqueia ataques ao Leader durante o turno (ex: OP06-026 Koushirou), distinto de `cannot_attack_self`.

Validacao: `python smoke_test.py`; `python audit_replay.py --n 5 --seed 42`; teste direto dos 5 gaps. `smoke_test_broad.py` completo ficou lento demais para fechar em 300s; 10 partidas aleatorias terminaram sem excecao em ~289s (risco/performance a observar).

### "Médios" — resolvidos (SaveTargetName e MatchLeaderToBasePower implementados em 28/06/2026)
- [x] ~~MatchLeaderToBasePower~~ — **implementado em 28/06/2026**: novo campo
  `source` em `set_base_power` (`gerar_effects_db.py`, regex `m_dyn` em
  `parse_set_base_power`), valor calculado em tempo de execução via
  `effective_power()` em vez de `amount` fixo do banco. 3 fontes
  confirmadas: `opp_leader` (5 cartas: EB04-052, OP06-009, OP16-036,
  OP16-055 + dup), `own_leader` (1 carta, OP14-053), `selected_opp_character`
  (2 cartas: EB01-061, OP16-104 — seleção e cópia no MESMO step, sem
  precisar de memória entre steps). Fica de fora: OP04-069 ("the same as
  the power of your opponent's ATTACKING Leader or Character" — exige
  saber quem está atacando no momento da resolução, contexto de batalha
  que `set_base_power` não tem hoje; 1 carta, raro). `PERDEU=0`, smoke
  tests 100%, 4 cenários manuais (opp_leader/own_leader/selected com
  escolha do melhor candidato/sem candidato não quebra).

Os 5 medios restantes foram fechados em 29/06/2026. Ainda ficam a familia grande
de imunidade e stubs antigos listados abaixo.

### Dívida técnica grande — imunidade
- [x] **Completar auditoria de imunidade — encerrada (01/07/2026).** Em
  29/06/2026 foi confirmado que `ko`/`removal` já têm 52 actions parseadas e
  os caminhos principais chamam `is_immune()`. Corrigido bug de fonte: imunidade
  "by opponent's effects" não protege mais contra efeito próprio. A
  substituição "would be removed/K.O.'d ... instead" foi fechada em
  01/07/2026 (ver entradas acima). Investigação direta de `EffectImmune`/
  `CombatImmune`/`ImmuneToStrikes`: são nomes de MECANISMOS INTERNOS do
  código oficial decompilado (`_referencias/simulador-oficial/`,
  `ActV3Effect.cs`/`GameplayLogicScript.cs`), não padrões de texto
  adicionais nas cartas. Busca direta em `cards_rows.csv` por variantes
  textuais mais amplas ("cannot be affected", "immune to", "cannot be
  targeted/selected/chosen", "unaffected", "ignores effects") não achou
  NENHUMA carta real usando esses padrões além do que `cannot be K.O.'d`/
  `cannot be removed from the field` já cobre — e isso já está
  implementado, incluindo a parte de atributo do atacante (Strike/Slash/
  Special/Wisdom/Ranged/Leaders, que É literalmente "ImmuneToStrikes" na
  prática) feita em 30/06/2026. Confirmado com exemplos reais (OP01-024,
  EB03-018) já parseados corretamente como `action: 'immunity'`. Item
  fechado — não há mais gap de cobertura conhecido nesta família.
- [x] **Imunidade a `rest` forçado — implementada (01/07/2026).** Um
  segundo agente de investigação (disparado em paralelo, voltou depois do
  item acima já fechado) achou um gap real: "cannot be rested by your
  opponent's effects" — autoproteção contra REST forçado, DISTINTA de
  `lock_opp_cannot_be_rested` (que trava o character DO OPONENTE,
  mecânica oposta, beneficia quem ativa — já implementada, sem gap).
  O agente reportou 11 cartas, mas 8 delas (EB02-011, EB03-017, OP11-034,
  OP13-032, OP14-033, OP14-069, OP15-029) já são `lock_opp_cannot_be_rested`
  funcionando — falso positivo do agente por similaridade textual
  superficial ("cannot be rested" aparece nos dois textos com semântica
  oposta). Gap real: só 3 cartas — OP11-046, OP12-021, OP15-024. Novo
  `imm_type='rest'` em `parse_immunity` (`gerar_effects_db.py`), aceita
  também a forma composta "cannot be K.O.'d OR rested by your opponent's
  effects" (OP11-046). `is_immune()` já funcionava genérico pra qualquer
  `imm_type` sem mudança — só documentado. Checagem plugada em
  `rest_opp_character` (`decision_engine.py`), o único ponto real de
  "rest forçado por efeito do oponente" no banco hoje. 4 smoke tests novos.
  Validado com `diff_parser.py` (`PERDEU=0`, exatamente as 3 cartas
  esperadas), `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  exceções, 0 anomalias.
  **Gaps menores não corrigidos** (achados de raspão, baixo
  impacto): OP14-119 (`lock_opp_cannot_be_rested` com gatilho "when this
  Character becomes rested", trigger condicional não reconhecido, perde o
  efeito) e OP16-032 (mesma action, mas com exclusão `other than [Nome]`
  não extraída pelo parser — fica sem nenhum efeito parseado). 2 cartas,
  registrado aqui pra não se perder.
- Fatia seguinte feita: KO por efeito e KO em batalha agora passam contexto para
  `is_immune()`, e o helper usa o texto bruto para impedir que imunidade
  `cannot be K.O.'d in battle` proteja contra efeito, ou `by effects` proteja
  contra batalha.
- Fatia seguinte feita (30/06/2026): KO em batalha agora também restringe por
  atributo/fonte do atacante (`Strike`, `Slash`, `Special`, `Leaders`, "by
  Characters without [Special]"). `_source_matches_battle_ko_immunity()` lê o
  atacante (`source_card`) e compara com o texto da sentença de imunidade.
- Auditoria de OP11-005/OP11-046 (30/06/2026): achou um bug de parser, não um
  caso não suportado. `'blocker'` está em `TODAS_TAGS` (delimita os OUTROS
  blocos, que param ao bater em `[Blocker]`), mas não tem `trigger_pattern`
  próprio — então qualquer texto que vem DEPOIS do parêntese de regra do
  Blocker era descartado por inteiro (nem o loop principal, nem o segmento
  solto "antes da 1ª tag", nem o fallback final cobriam esse caso). Afetava
  4 cartas no banco: OP11-005, OP11-046, OP11-088, ST10-014. Corrigido com um
  novo segmento "pós-Blocker" em `parse_card_effect` (`gerar_effects_db.py`).
  De brinde: achado e corrigido um 2º bug — a condição `only_field_type`
  ("if you only have Characters with type X") era parseada desde 29/06 mas
  NUNCA checada nem em `_check_conditions` (EffectExecutor) nem em
  `_immunity_conds_met` (caminho de imunidade) — tratava o efeito como
  incondicional para as 6 cartas que já a usavam (EB02-010, OP05-084,
  OP05-092, OP13-097, OP15-001, OP16-022) além da nova OP11-046. Ambos os
  checkers agora respeitam `only_field_type`. `diff_parser.py` confirmou
  `PERDEU=0`; `audit_replay.py` 0 anomalias (turnos mudaram em 2 das 5
  partidas do seed 42, esperado — comportamento real mudou).
- [x] **`debuff_power` sem handler de execução (30/06/2026):** achado durante
  a auditoria dos Counter events — a action já era reconhecida em
  `_step_is_viable` e em heurísticas de score, mas `_execute_step` nunca
  tinha um `if action == 'debuff_power':` — virava no-op silencioso em TODOS
  os 142 steps reais do banco (on_play 31, when_attacking 27, main 25,
  activate_main 17, counter 14, trigger 10, on_opp_attack 6, demais 12), não
  só em Counter events. Implementado handler espelhando `buff_power` mas do
  lado do oponente, 4 targets: `opp_character`/`opp_leader_or_character`
  (escolhe o alvo mais valioso via `choose_highest_board_value`, com
  `opp_leader_or_character` caindo no Leader quando o campo do oponente está
  vazio), `all_opp_characters` (afeta todos) e `opp_leader` (direto, raro/0
  cartas hoje). Parser nunca emite filtro/count pra esses alvos — sempre 1
  escolha automática. Adicionado também a `safe_extra_actions` dos Counter
  events (objetivo original desta fatia), desbloqueando OP08-017, OP10-018,
  OP12-018, ST29-015. **Bug-side-effect descoberto pelo `audit_replay.py`:**
  com debuff de verdade acontecendo, Characters podiam ficar com power
  negativo (Otama, Jozu na auditoria) — `effective_card_power()`
  (`rules_facade.py`) não tinha piso em 0. Corrigido com `max(0, ...)` no
  retorno (regra real do jogo: power nunca é negativo). Validado com
  `audit_replay.py --n 20 --seed 7`: 0 exceções, 0 anomalias.
- [x] **Counter events: 2º buff battle_only + extras simples (30/06/2026):**
  `_counter_event_power_plan` exigia exatamente 1 `buff_power(battle_only)`.
  Achado: 8 cartas no banco têm 2 (EB03-020, OP04-095, OP05-114, OP06-038,
  OP07-035, OP07-095, OP11-059, OP12-098) — texto real confirma que o 2º
  (sempre `target='self'`) é um BÔNUS condicional ao MESMO alvo escolhido no
  1º ("Up to 1 of your Leader or Character cards gains +X power... Then, if
  [cond], **that card** gains an additional +Y power"), não um 2º alvo
  independente. Generalizado para somar quantos `buff_power(battle_only)`
  existirem, desde que os adicionais tenham `target='self'` (aplica o bônus
  só se a condição do step passar; se não tiver condição, soma sempre).
  Também adicionados a `safe_extra_actions`: `trash_from_deck_top`,
  `peek_life`, `add_from_trash`, `gain_life` — ações simples com handler
  genérico já existente, sem seleção complexa. Desbloqueia OP03-054,
  OP03-055, OP08-096 (trash_from_deck_top), ST07-016, ST13-017 (peek_life),
  OP11-097, OP12-115 (add_from_trash), ST09-015 (gain_life). Cobertura de
  Counter events com `buff_power(battle_only)` subiu de 102/180 pra 114/180.
  Ainda fora: `play_card`/`play_from_deck` (7), `look_top_deck`+`add_to_hand`
  (2, busca complexa), os 44 sem nenhum buff `battle_only` (padrões
  totalmente diferentes: KO puro, debuff puro do atacante, bounce puro já
  coberto, etc.) — ver auditoria detalhada no HANDOFF.md de 30/06/2026 (4).
- [x] **Counter events: duration='this_turn' + select_filtered (30/06/2026):**
  dos 44 sem `buff_power(battle_only)`, 14 tinham SO um `buff_power` com
  `duration='this_turn'` (nao `battle_only`) — o planner exigia
  `battle_only` estritamente. Como o Counter Step so acontece DENTRO da
  resolucao da batalha em curso, e o resto do engine ja trata as duas
  durations de forma identica na limpeza (reset de `power_buff` no inicio do
  turno), ampliei o filtro pra aceitar as duas. Desbloqueia 5 cartas com
  `target` ja suportado (leader/leader_or_character): OP04-037, OP04-076,
  OP06-017, OP09-039, OP13-077. As outras 9 usam `target='select_filtered'`
  ("Up to 1 of your [Tipo] Leader or Character cards gains +X power") —
  adicionado como novo `target_rule`, mas so conta como defesa valida se o
  ALVO REAL sob ataque bater no `filter_type` (via `card_matches_filter`);
  senao a carta buffaria outro aliado que nao impede o hit desta batalha.
  Desbloqueia EB03-029, EB04-019, EB04-029, OP07-018, OP14-117, OP15-038,
  OP15-074, OP15-075, OP15-076. Cobertura subiu de 114/180 pra 128/180.
  Validado com `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  excecoes, 0 anomalias.
- [x] **Counter events que enfraquecem o ATACANTE (30/06/2026):** mecanica
  distinta de tudo anterior — em vez de buffar a propria defesa,
  "[Counter] Give up to 1 of your opponent's Leader or Character cards -X
  power during this turn" reduz o `atk_power` do atacante diretamente. Nova
  funcao `try_counter_event_debuff` + `_counter_event_debuff_plan` em
  `decision_engine.py`, chamada como fallback no fluxo de batalha logo apos
  `try_counter_event_power` nao bastar (`atk_power -= amount`, mutando
  `attacker.power_buff` de verdade, nao so o calculo de defesa). Escopo
  minimo e deliberado: exige EXATAMENTE 1 `debuff_power` no bloco `counter`
  e nenhum outro step. Desbloqueia OP01-028, OP03-017, OP07-075, OP15-021,
  ST09-014 (5 cartas). Ficam de fora por ambiguidade de alvo (2 debuffs em
  sequencia sem "that card" explicito, ao contrario do padrao de buff
  bonus): OP02-089 ("total of 2... -3000", distribuicao ambigua), OP04-017
  (2 debuffs sequenciais sem marcador de mesmo alvo), OP09-097 (combina com
  `negate_effect`, ainda sem handler). Validado com `audit_replay.py --n 20
  --seed 7` e `--n 15 --seed 99`: 0 excecoes, 0 anomalias.
- [x] **KO via Counter event (30/06/2026):** implementado — terceiro
  mecanismo de Counter event, distinto de buffar a propria defesa e de
  debuffar o atacante. "[Counter] K.O. up to 1 of your opponent's
  Characters with cost/power N or less[, rested only]" remove o atacante
  inteiramente ANTES do dano, cancelando o ataque por completo (sem
  comparacao de power). Novas funcoes `_counter_event_ko_plan` +
  `try_counter_event_ko_attacker`, chamadas no fluxo de `_resolve_attack`
  logo apos o debuff do atacante nao bastar e antes do Damage Step; se
  ativar, `return False` direto (ataque cancelado). Respeita
  imunidade/substituicao do atacante (mesma checagem do 'ko' generico,
  `ko_context='effect'`). `rested_only` e trivialmente satisfeito (o
  atacante ja fica `rested=True` ao declarar o ataque, bem antes do Counter
  Step). Escopo minimo: exige EXATAMENTE 1 step 'ko' com
  `target='opp_character'` e nenhum outro step. Desbloqueia as 4 cartas:
  EB01-010, OP08-094, OP10-040, OP13-039. Validado com `audit_replay.py
  --n 20 --seed 7` e `--n 15 --seed 99`: 0 excecoes, 0 anomalias.
- [x] **Counter events: buff + play_card/busca em deck (30/06/2026):**
  ultima fatia da auditoria de Counter events. `play_card`, `play_from_deck`,
  `look_top_deck`, `add_to_hand`, `deck_bottom_rest` ja tinham handler
  generico (usados em on_play/trigger/etc.) — adicionados a
  `safe_extra_actions` como bonus de valor junto de um buff `battle_only`
  que ja defende sozinho (mesmo raciocinio dos extras anteriores: o buff e
  o que importa pra decisao, a busca/play e so ganho extra). Desbloqueia
  EB01-019, EB02-059, OP01-088 (exceto a parte de `deck_reorder_rest`, ver
  abaixo), OP02-045, OP05-018, OP08-054, OP08-115, OP14-116, ST12-017 (8 de
  9 cartas do grupo).
  **Achado novo, nao corrigido:** `deck_reorder_rest` (1 carta, OP01-088:
  "look at 3 cards from top, place at top or bottom in any order") e
  parseada e referenciada em `_step_is_viable` mas NUNCA teve handler de
  execucao — mesmo padrao do bug do `debuff_power` (achado 30/06/2026,
  sessao anterior), so que aqui afeta 1 unica carta. Deixado de fora desta
  fatia por escopo (baixo impacto), registrado aqui pra nao se perder.
  **Deliberadamente fora de escopo:** os 4 Counter events SEM nenhum buff
  que so jogam/buscam carta (EB01-009, OP01-087, OP04-036, OP10-078) — nao
  swingam `defend_power`/`atk_power` de jeito nenhum, entao nao cabem no
  framework de "isso impede o hit". Tratá-los exigiria um criterio de
  decisao totalmente diferente ("vale a pena gastar DON/carta por puro
  valor, mesmo sem impedir o ataque?"), fora do escopo desta auditoria.
  Cobertura final de Counter events com buff: 128/180 pra 136/180.
  Validado com `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  excecoes, 0 anomalias.
- [x] **Substituição externa — executor/filtro: fechado.** Auditoria de
  29/06/2026 achou ~38 textos onde uma fonte em campo/líder protege outro
  alvo (`if your Character would be removed/K.O.'d...`). Implementado em
  fatias: `try_any_substitute()` separa `target`/`source`, parser extrai
  filtros estruturados do alvo protegido (`filter_name`, `filter_color`,
  `filter_type`, `cost_lte`/`gte`, `power_eq`/`lte`/`gte`, `exclude`).
  `EB02-030` (Counter event) ganhou suporte estreito próprio. Eventos
  `[Counter]` com buff defensivo + extras (draw, set_active,
  rest_opp_character, add_don, KO, bottom-deck, debuff do atacante, KO do
  atacante, play_card/busca em deck) ficaram prontos na sequência de
  30/06/2026 — ver entradas de HANDOFF.md daquele dia. Auditoria de
  01/07/2026 confirmou: 21 de 33 steps de substituição têm filtro
  estruturado; os 12 sem filtro são todos self-referentes (10 `this
  Character` + OP07-042 self composto + EB02-030 já coberto) — **não havia
  bug de "fonte externa sem filtro protegendo qualquer alvo"**:
  `_target_matches_external_substitute` já bloqueia (retorna False) quando
  um step não tem NENHUM filtro estruturado, comportamento seguro
  confirmado por leitura direta do código.
- [x] **Substituição externa — gap real de PARSER achado e corrigido
  (01/07/2026):** a auditoria de 01/07 achou que `parse_substitute_ko` e
  `parse_substitute_removal` tinham listas de padrões de custo PARALELAS
  mas DESSINCRONIZADAS — vários padrões existiam só numa das duas funções
  (`return_own_don` só em removal, `trash this character instead`/`rest
  this character instead` só em KO). 17 cartas reais com texto "would be
  removed/K.O.'d ... instead" ficaram sem NENHUMA action `substitute_*`
  parseada por causa disso. Corrigido com `_parse_substitute_cost()`
  (`gerar_effects_db.py`), função única compartilhada pelas duas, união de
  todos os padrões de custo + 2 bugs extras corrigidos na mesma auditoria:
  "you CAN [custo] instead" (regex só aceitava "you MAY") e variante
  power-or-less pro `trash_from_hand` (só existia power-or-more, e em duas
  redações: "N power or less" e "a power of N or less"). Desta fatia, 6
  cartas fechadas com cobertura completa (custo + alvo, quando aplicável):
  EB04-030, EB04-031 (`return_own_don` para KO), EB04-044 (verbo "can"),
  OP15-003 (`trash_from_hand` power_lte), OP12-027 (substituição EXTERNA,
  precisou de filtro novo `filter_attribute` pra Slash/Strike/Special/
  Wisdom/Ranged), OP15-094 (substituição EXTERNA — achado bônus: o
  early-return de "this character" em `_apply_substitute_target_filters`
  descartava o filtro de tipo inteiro quando o texto era "X type Character
  OTHER THAN this Character", tratando como self-target por engano; a
  exclusão de si mesma já é garantida estruturalmente pelo executor
  — `sources = [c for c in self.me.field_chars if c is not target]` — então
  só precisava parar de descartar o filtro). 8 smoke tests novos.
  Validado com `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  exceções, 0 anomalias.
- [x] **Substituição externa — 11 das 13 cartas pendentes fechadas
  (01/07/2026):** 7 cost-types novos em `_pay_substitute_cost`:
  `rest_leader` (OP04-082, ignora a alternativa de stage nomeado),
  `rest_own_filtered` (OP10-037, OP11-110 — rest 1 Character próprio de um
  tipo específico, ignora a alternativa "ou Leader" de OP11-110),
  `rest_own_character` (OP14-034, externa), `rest_own_card` (OP14-029;
  OP15-035, externa, count=2), `life_to_hand` (OP10-034, OP12-061),
  `life_to_trash` (ST09-010, ST20-002), `trash_to_deck_bottom` (OP14-092).
  Parser: novos padrões em `_parse_substitute_cost`. **Bônus reais
  encontrados pelos mesmos padrões** (cartas fora da lista original, todas
  confirmadas corretas por leitura do texto bruto): EB04-043 (`filter_color`
  black + cost_lte 5 + `trash_to_deck_bottom`), **OP11-001** (Leader Koby —
  primeira fonte de substituição que é um Leader, já funciona sem mudança
  de engine porque `try_any_substitute()` já incluía `self.me.leader` na
  lista de fontes externas), OP15-098, OP15-105 (`life_to_hand`).
  **2 bugs estruturais achados e corrigidos na mesma fatia:**
  (1) `parse_substitute_ko`/`parse_substitute_removal` reivindicavam o
  BLOCO INTEIRO de texto ao achar a cláusula de substituição, descartando
  silenciosamente qualquer efeito incondicional que viesse ANTES dela no
  mesmo bloco (ex: OP14-034 perdia um `buff_power` que vinha antes do texto
  de substituição sob a mesma tag `[Your Turn]`) — corrigido extraindo o
  prefixo e reparseando via `parse_block` recursivo; corrigiu também
  ST25-003 (achado bônus, perdia `draw`+`play_card`) sem nenhuma
  intervenção minha além de generalizar o fix. (2) `try_substitute()` e
  `_substitute_source_blocks()` só checavam a chave `'passive'`, mas cartas
  com a tag formal `[Opponent's Turn]`/`[Your Turn]` ANTES da cláusula de
  substituição (ex: OP14-029, OP14-092, OP14-034) fazem esse timing virar a
  chave de topo no parser, não `passive` — mesmo padrão que `is_immune()`
  já tratava corretamente. Ambas agora iteram `('passive', 'opp_turn',
  'your_turn')`. 11 smoke tests novos. Validado com `diff_parser.py`
  (`PERDEU=0`), `audit_replay.py --n 20 --seed 7`, `--n 15 --seed 99` e
  `--n 25 --seed 321` (0 exceções, 0 anomalias nas três).
- [x] ~~Substituição externa — OP07-029 e OP16-014~~ — **implementados em
  02/07/2026** (ver commits anteriores desta sessão).

---

## 🔴 FILA ANTERIOR ainda aberta

### Stubs sem lógica de decisão
- [x] ~~choice (19) — heurística de valor~~ — JÁ IMPLEMENTADO (auditoria
  01/07/2026, este item estava desatualizado). `_resolve_choice`
  (`decision_engine.py:853-897`) tem heurística de valor real por peso de
  ação (`attack_life`=4, `trash_opp_life`/`place_opp_character_bottom_deck`=3,
  `ko`/`trash_character`/`gain_life`=2, `bounce`/`draw`=1), filtra por
  viabilidade e escolhe a opção de maior score (menor se `chooser='opponent'`).
  Consumido em `execute()` e no passive-loop. Contagem real: 17 cartas (não
  19). Smoke tests dedicados em `smoke_test.py:120-161`.
- [x] ~~conditional_stack (OP15-092) — custo-benefício por threshold~~ — JÁ
  IMPLEMENTADO (auditoria 01/07/2026). `decision_engine.py:1610-1613` itera
  `conditional_stack`, checa `conditions` de cada item via
  `_check_conditions` e ACUMULA (`extend`) os blocos que passam — cumulativo,
  não exclusivo. 1 carta confirmada (OP15-092), igual ao TODO. Smoke test em
  `smoke_test.py:161-184`.
- [x] ~~set_base_power (8) — integrar em effective_power()~~ — JÁ
  IMPLEMENTADO (auditoria 01/07/2026, contagem estava desatualizada).
  Handler completo em `decision_engine.py:2512-2566`: resolve target
  (self/leader/own_character/leader_or_own_character), filtra por
  `filter_type`, seta `card.base_power_override`, consumido por
  `effective_card_power` (`rules_facade.py`). Inclui caso dinâmico
  (`source=opp_leader/own_leader/selected_opp_character`, achado
  28/06/2026). Contagem real: 15 cartas (não 8 — dobrou desde a estimativa
  original).
- [x] **lock_opp_attack_unless_pays (OP08-043) — implementado (01/07/2026):**
  campo novo `Card.attack_paywall` (dict `{cost_type, cost_amount, until}`,
  resetado em `refresh_phase` junto com `cannot_attack_until` — mesma
  simplificação de duration já usada lá). Execução do step seleciona TODOS
  os Characters do oponente no campo no momento (texto real: "select all of
  your opponent's Characters", sem escolha — `count=99`). Novo helper
  `can_afford_attack_paywall(card, owner)` adicionado aos 5 pontos que já
  filtravam `not c.cannot_attack_until` como "pode atacar"
  (`my_attack_power`, geração de ações de ataque em 3 lugares, Turn
  Planner) — simplificação deliberada: paga sempre que a mão tem cartas
  suficientes, sem modelar "vale a pena" (mesmo padrão do resto do engine
  pra custos de ativação, evita reabrir a fase "Opponent Reading" só por
  causa de 1 carta). Pagamento real acontece em `_execute_attack` no
  momento de declarar o ataque (trasha as N piores cartas da mão por
  `board_value`). 4 smoke tests novos: trava aplicada a todos os
  characters, `can_afford_attack_paywall` com/sem paywall e mão
  insuficiente, e integração real via `OPTCGMatch._execute_attack`
  confirmando o trash automático. Validado com `audit_replay.py --n 20
  --seed 7` e `--n 15 --seed 99`: 0 exceções, 0 anomalias.
- [x] **deck_reorder_rest / deck_top_rest — implementado (01/07/2026):**
  achado importante durante a implementação: `deck_top_rest` é um nome de
  action EQUIVOCADO do parser (`gerar_effects_db.py:467-470`) — o regex
  casa o prefixo `'place the rest at the top'` antes de checar o sufixo
  `'or bottom'`, então TODA carta real com texto "place the rest at the top
  or bottom of the deck in any order" cai em `deck_top_rest` em vez de
  `deck_reorder_rest`. Confirmado varrendo `cards_rows.csv`: nenhuma das 5
  cartas de `deck_top_rest` (OP02-057, OP05-043, OP08-053, OP11-040,
  OP11-104) tem texto "top" sem "or bottom" — são o MESMO mecanismo de
  `deck_reorder_rest` (escolha livre de ordem/posição), só com nome
  diferente. Não vale a pena tocar o parser/regenerar DBs só por causa do
  nome — as duas actions agora compartilham o mesmo handler em
  `_execute_step`. Heurística (mesmo princípio do `peek_life` 'all'): a IA
  bota a carta mais valiosa de volta no topo do deck (próxima a ser
  comprada), o resto fica ordenado por `board_value` crescente abaixo dela.
  Também adicionadas a `safe_extra_actions` dos Counter events — desbloqueia
  OP01-088 (que tinha ficado de fora na fatia de Counter events por causa
  desse handler faltando). 3 smoke tests novos (deck_reorder_rest,
  deck_top_rest, integração via Counter event OP01-088). Validado com
  `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0 exceções, 0
  anomalias.
- [x] **cannot_attack_self / cannot_attack_self_unless /
  cannot_attack_own_characters_by_cost (01/07/2026) — já estava
  implementado, só faltava teste:** não era item formal do TODO.md, só um
  comentário inline em `decision_engine.py` dizendo "reconhecidas sem
  travar nada ainda" (6 cartas: Oars, Luffy OP11-058, Wadatsumi, P-084
  Buggy, Trafalgar Law EB04-005, Emet EB04-051). Auditoria confirmou que
  `is_attack_locked_self()` já lê `effects['passive']`/
  `mass_lock_conditional` direto do banco (sem depender de execução) e já
  estava plugada nos 5 pontos de "pode atacar" — a trava JÁ funcionava.
  O placeholder em `_execute_step` não bloqueava nada, mas também não era
  morto: `apply_your_turn_buffs()` roda todo step de `'passive'` (não só
  buffs), então gerava um log confuso de "não implementado" todo turno
  mesmo a trava real já estando ativa em paralelo. Trocado por `return ''`
  silencioso + comentário corrigido. 6 smoke tests novos cobrindo os 3
  sub-mecanismos. Validado com `audit_replay.py --n 20 --seed 7` e `--n 15
  --seed 99`: 0 exceções, 0 anomalias.

### Reserva de DON em combate
- [x] ~~plan_don_distribution não subtrai reserva defensiva (usa don_available cru)~~
  — STALE, já corrigido (auditoria 01/07/2026). `decision_engine.py:4678-4778`
  já chama `_don_reserve_for_defense()` (linha 4720) e subtrai do
  `don_available` antes de distribuir DON nos modos CLEAR FIELD/NORMAL — só
  ignora a reserva no modo LETHAL deliberadamente (decisão confirmada pelo
  usuário em 27/06/2026: "ir pro lethal vale mais que guardar DON").
- [x] ~~on_opponent_attack timing não existe (72 cards em "passive")~~ —
  STALE, já corrigido em 27/06/2026 (confirmado de novo em 30/06/2026 durante
  a auditoria de Counter events). O timing `on_opp_attack` já existe no
  parser (`gerar_effects_db.py:3160`) e já é executado em
  `_resolve_attack` (`decision_engine.py`, `ee_react.execute(reagente,
  'on_opp_attack')`, ANTES de calcular `atk_power` — necessário pra debuffs
  do tipo Izo EB01-002 valerem nesta batalha).

### Turn Planner
- [x] ~~can_lethal_this_turn ainda cheata lendo self.opp.hand para counters~~ —
  corrigido em 29/06/2026. Agora usa counters revelados + estimativa por tamanho
  de mão oculta.
- [x] **5 funções órfãs — deletadas (02/07/2026).** Na contagem real eram 6
  (mais `_mulligan_decision` que parecia orfã mas é chamada por
  `replay_optcg.py` — restaurada depois de deletada por engano). As 5
  efetivamente mortas e removidas: `_count_available_attacks` (GameAnalyzer),
  `choose_card_to_play` (DecisionEngine, supersedida pelo Turn Planner),
  `plan_don_distribution` (DecisionEngine, idem), `plan_attacks`
  (DecisionEngine, idem), `_distribute_don` (OPTCGMatch). -345 linhas.
- [ ] Otimização estrutural de performance: reduzir `deepcopy` no Turn Planner
  ou cachear cálculos caros (`_don_reserve_for_defense`, defesa/counter,
  geração de ações). Em 29/06/2026 foi feita só uma poda de orçamento
  (`max_steps=8`, Monte Carlo=6) para recuperar o tempo do broad; não é a
  solução definitiva. Em 02/07/2026 foram feitas 2 otimizações menores de
  `deepcopy` em `GameState.__deepcopy__`: (a) `full_deck_census` agora é
  compartilhado por referência (é invariante durante o jogo, jamais mutado
  — economiza deepcopy de dict de ~50 entradas por clone); (b) `opp.deck`
  em `_simulate_sequence_once` é copiado como lista rasa (não deepcopy de
  cada Card) pois o oponente não age durante a simulação do turno ativo —
  economiza ~0.5-0.7ms por chamada. A dívida estrutural mais profunda
  (clone incremental ou cache de avaliações) permanece aberta.

### Parser — cobertura
- [x] **cartas com card_text mas effects vazio — revalidado e parcialmente
  corrigido (2 rodadas: 02/07/2026).** Total atual: **2314/2614 com efeito**
  (era 2148 antigo → 2286 após rodada 1 → 2314 após rodada 2). **24 gaps
  reais restantes** — maioria exige mecânica genuinamente nova: swap de
  poder (OP14-001/017), redirect ataque (OP14-060), trigger reativo ao descarte
  do oponente (OP12-040 Kuzan), "end of battle" trigger (OP04-047/ST08-013),
  adicionar character do oponente à vida dele (OP04-097/OP05-111/EB02-057),
  etc. Ver HANDOFF.md (6) para lista completa e categorização.
- [x] **cartas com card_text mas effects vazio — revalidado (02/07/2026).**
  Contagem anterior "2148 com efeito" estava desatualizada. Resultado atual:
  **2286/2614 com efeito** (+138 desde o início da sessão). Gaps restantes
  reais: **~54 cartas** (excluindo NULL, variantes de ID e cards erratados),
  classificados em 3 grupos: (A) falsos positivos de ID de variante (9 cards
  — efectivamente parsed sob ID canônico); (B) mecânicas novas que requerem
  design próprio (~30+: swap de poder, redirecionar ataque, triggers de
  "opponent trashes from hand", "set power to 0", play específico por nome
  do deck, etc.); (C) gaps de parser menores corrigidos nesta auditoria (9
  cartas novas: `gain_can_attack_active` com variante "your opponent's
  active" — OP01-021, OP02-014 + 1 bônus; `give_don` com target-first —
  ST01-001 + 6 bônus em cartas existentes; `opp_place_trash_bottom_deck`
  player-iniciado — OP15-091; `rest_opp_character` sem "up to" e com "cards"
  — P-008, OP13-033; `play_from_trash filter_self` em on_ko — P-071;
  set_active+set_don_active combinado — OP13-035). Mecânicas do grupo B
  listadas em item separado abaixo conforme aparecerem prioritárias.
- [x] **opponent has N+ DON — implementado (02/07/2026), 8 cartas exatas
  (EB02-061, OP02-089, OP02-090, OP02-091, OP08-060, OP14-063, PRB02-010,
  ST26-005).** Novo `opp_don_on_field_gte` em `parse_conditions`
  (`gerar_effects_db.py`), simétrico a `don_on_field_gte` mas sobre o
  campo do OPONENTE. Infra de `conditions` já era genérica (anexada por
  entry/step, checada em `_check_conditions` antes de executar) — só
  faltava o regex; nenhuma mudança extra de engine necessária além de
  plugar a chave em `_check_conditions` (linha ~1792) e no pre-filtro do
  Turn Planner (linha ~4686). Achado real: OP02-089/090/091 tinham o
  trigger "opponent returns 1 DON!! card" **sem gate algum** — disparava
  sempre, mesmo com oponente em 0 DON. `PERDEU=0`, 8/8 mudanças
  corretas no diff, 2 smoke tests novos, `audit_replay.py --n 20 --seed 7`
  e `--n 15 --seed 99`: 0 exceções, 0 anomalias.
- [x] **place-at-bottom-of-deck — implementado (02/07/2026), 13 cartas
  (EB03-026, EB04-022, EB04-025, OP05-079, OP06-044, OP06-092, OP07-047,
  OP08-046, OP11-072, OP11-091, OP15-048, P-048, OP16-047).** Escopo real
  era mais amplo do que o "~14" original sugeria — boa parte do que
  apareceu numa busca textual ampla por "bottom of deck" já estava
  coberta (`deck_top_rest`/`deck_reorder_rest`/custos de trash-pro-fundo
  já existentes). O gap genuíno era uma família nova e coerente:
  disrupção FORÇADA no oponente com destino o FUNDO DO PRÓPRIO DECK dele
  (nunca trash) — 2 actions novas em `decision_engine.py`:
  `opp_place_hand_bottom_deck` (fonte = mão do oponente, escolhe a pior
  carta por `_choose_to_trash`, mesma heurística de `opp_trash_from_hand`)
  e `opp_place_trash_bottom_deck` (fonte = trash do oponente, aceita
  `filter_type='event'` p/ OP11-091). Parser estendido em
  `parse_opp_self_move_character` (`gerar_effects_db.py`), reconhece
  variantes de redação "your opponent places/must place" e "they place"
  (OP16-047, gatilho já deixa "opponent" implícito antes). Bônus: achado
  no caminho que OP06-092 (Brook) tinha uma estrutura `Choose one:` com
  bullet corrompido (`�` em vez de `•` no `card_text` bruto) que já
  era reconhecida pelo split de `parse_block` — só faltava a 2ª opção
  (`opp_place_trash_bottom_deck`) ter parser pra virar uma `choice` de
  verdade em vez de cair no fallback de "só a 1ª opção conta".
  `PERDEU=0`, 7 GANHOU + 6 MUDOU = 13/13, 2 smoke tests novos,
  `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0 exceções, 0
  anomalias.
- [x] **opp_hand_gte — corrigido (02/07/2026), 13 cartas.** Item acima
  tinha ficado registrado como "simplificação consciente" (ação dispara
  sempre, mesmo com a mão do oponente abaixo do limiar — só coincidia com
  a regra real quando a mão estava em 0). Usuário pediu correção
  explícita: "não pode ser simplificado porque interfere na partida".
  Nova condição `opp_hand_gte` em `parse_conditions` (mesmo molde de
  `hand_gte` já existente, mas sobre `opp.hand`), plugada em
  `_check_conditions` e no pre-filtro do Turn Planner. Escopo real maior
  do que os 5 cards de place-at-bottom-of-deck — o mesmo gap afetava TODA
  a família `opp_trash_from_hand`/`attack_life` com esse prefixo
  condicional: EB02-045, EB03-026, EB04-022, OP05-082, OP06-093,
  OP07-047, OP08-046, OP09-087, OP10-087, OP10-118, OP12-087, OP16-047,
  ST13-009. `PERDEU=0`, 13/13 MUDOU (só ganharam o gate, nenhum efeito
  novo nem perdido), 4 smoke tests novos (2 unidade + 2 end-to-end via
  carta real OP08-046 abaixo/no limiar), `audit_replay.py --n 20 --seed 7`
  e `--n 15 --seed 99`: 0 exceções, 0 anomalias.
- [ ] OP15-074 Varie — DON sem sinal, aguarda foto
- ~~OP14-119 (Mihawk) — trigger "becomes rested" sem parser~~: **resolvido
  (02/07/2026).** Novo timing `when_rested` no parser (`gerar_effects_db.py`,
  trigger_patterns antes de `your_turn`, com lookahead negativo pra evitar
  duplicar o mesmo bloco como `your_turn`). 6 cartas afetadas: OP14-021,
  OP14-027, OP14-028, OP14-032, OP14-035 (antes ficavam como `your_turn`,
  disparavam passivamente no início do turno) + OP14-119 (estava totalmente
  vazia — também tinha o typo "cost or 9" em vez de "cost of 9" no CSV, regex
  do parser corrigido para aceitar ambos). Engine: `when_rested` disparado em
  `_execute_attack` após restar o atacante (único ponto de resting durante o
  turno ativo que cobre todos os casos práticos; resting via custo de
  Activate:Main não dispara — simplificação documentada, sem carta real
  afetada hoje).

---

## ⚠️ SEGURANÇA — antes de deploy público
- [ ] Rotacionar chaves Supabase (service_role exposta). Migrar p/ sb_secret/sb_publishable.

---

## 📚 REGRAS (NUNCA quebrar)
- K.O. ≠ Trash · Rush ≠ Rush:Character · give_don_opp tira do próprio
- Sinal de custo só com texto explícito · play_card do efeito = GRÁTIS
- Pagar custo só se algum step produz efeito (viabilidade ampla, 25/06)
- Topo do deck = fim da lista (pop()) — confirmado no source do simulador
- Mill do deck = trash seco (sem trigger)

### Workflow
```
# parser: snapshot → fix → diff PERDEU=0 → gerar_dbs → re-snapshot → commit
# engine puro: editar → partida real instrumentada → commit (sem gerar_dbs)
# NUNCA git add -A · commit single-line (CMD)
```

---

## 📊 BANCO DE LOGS — análise estatística (planejado)

Banco de partidas reais em `scriptis_da_ia/logs/` (arquivos nomeados por líder+cor).
Uso: `python parse_combat_log.py partida.log --summary --add-to-db`

### Próximos usos planejados (em ordem de prioridade)

- [ ] **Comparação IA vs humano** — dado um snapshot do log real (campo/mão/vida/DON),
  rodar o engine no mesmo estado e comparar a decisão da IA com o que o humano fez.
  Divergências concretas = ponto de tuning de heurística. Este é o uso mais valioso.

- [ ] **Win rate por matchup** — filtrar `logs/decks/` e `logs/index.json` por líder.
  Ex: quantas partidas Teach-BY × Lucy-RB existem, e qual a taxa de vitória de cada lado.

- [ ] **Curva de vida por turno** — média de vida restante em cada turno por líder.
  Ajuda a entender ritmo de jogo e quando o matchup costuma ser decidido.

- [ ] **Deck popularity por líder** — quais cartas aparecem em mais listas do mesmo líder.
  Base para calibrar heurísticas de valor de carta por arquétipo.

- [ ] **ML (futuro)** — behavioral cloning a partir do que os humanos fazem em cada
  estado. Só faz sentido depois de ter volume (50+ partidas) e de a base heurística
  estar afinada. Não antes.

---

## ROADMAP
1. Consertar lógica — EM ANDAMENTO (vários blocos fechados nesta sessão)
2. Auditar via replay — iniciado (Imu vs Sanji revelou Problemas 1/2/3)
3. Tunar heurísticas por simulação em volume — AQUI MORA QUASE TODO O GANHO
   3a. Comparação IA vs humano via banco de logs reais (ver seção acima)
4. ML — só se 1-3 prontos e baterem teto. Descartado por ora (25/06): herdaria bugs de
   execução; não "aprende conforme ensina" — quem faz isso é o parser por mecânica.
