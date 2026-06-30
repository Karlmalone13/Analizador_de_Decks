# TODO — Analisador de Decks OPTCG

**Última atualização:** 26 de junho de 2026
**Estado:** 2148 cards com efeito (subiu de 2138), parser auditado OP-02 a OP-15
**Baseline:** commit bbb4d31 (set_don_active + mill) + viabilidade transacional (a commitar)
**Repo:** github.com/Karlmalone13/Analizador_de_Decks

---

## Dívida técnica ativa — Turn Planner

- [ ] **Reduzir `deepcopy` em `_simulate_sequence*`**: a poda de orçamento já
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
- [ ] Completar auditoria de imunidade (ImmuneToKO/Removal/Combat/Effect/Strikes).
  Em 29/06/2026 foi confirmado que `ko`/`removal` já têm 52 actions parseadas e
  os caminhos principais chamam `is_immune()`. Corrigido bug de fonte: imunidade
  "by opponent's effects" não protege mais contra efeito próprio. Próximo passo
  é auditar variantes ainda fora de `immunity`: `EffectImmune`, `CombatImmune`,
  `ImmuneToStrikes` e substituições "would be removed/K.O.'d ... instead".
- Fatia seguinte feita: KO por efeito e KO em batalha agora passam contexto para
  `is_immune()`, e o helper usa o texto bruto para impedir que imunidade
  `cannot be K.O.'d in battle` proteja contra efeito, ou `by effects` proteja
  contra batalha.
- Fatia seguinte feita (30/06/2026): KO em batalha agora também restringe por
  atributo/fonte do atacante (`Strike`, `Slash`, `Special`, `Leaders`, "by
  Characters without [Special]"). `_source_matches_battle_ko_immunity()` lê o
  atacante (`source_card`) e compara com o texto da sentença de imunidade.
  Ainda falta variantes não parseadas como OP11-005/OP11-046.
- [ ] Implementar substituição externa: auditoria de 29/06/2026 achou cerca de
  38 textos onde uma fonte em campo/líder protege outro alvo (`if your Character
  would be removed/K.O.'d...`). O parser já estrutura muitos como
  `substitute_*`, mas o executor atual consulta principalmente o alvo removido.
  Primeiras fatias feitas: executor agora separa `target`/`source` via
  `try_any_substitute()` quando o step tem filtro estruturado; parser passou a
  extrair filtros simples do alvo protegido. Exemplos confirmados no banco:
  Monster -> `filter_name=bonk punch`, Tashigi -> `filter_color=green` +
  `exclude=tashigi`, Sabo -> `cost_lte=7` + `exclude=sabo`, Rosinante OP12-048
  -> `filter_type=navy` + `filter_color=blue`, ST30-009/ST30-011 ->
  `power_eq=6000`. Auditoria rápida: 21 de 33 steps de substituição têm filtro
  de alvo estruturado. Auditoria dos 12 restantes: 10 são `this Character`,
  `OP07-042` também é self com sujeito composto. `EB02-030` era Counter event
  para `any of your Characters` e foi coberto por suporte estreito a
  `counter -> substitute_ko` com custo `trash_from_hand`. Primeira fatia de
  eventos [Counter] feita: 70 eventos com buff defensivo unico `battle_only`
  agora podem ser usados no Counter Step quando impedem o hit. Segunda fatia:
  blocos com um buff defensivo unico + steps `draw` seguros tambem executam a
  compra. Terceira fatia: extras seguros `set_active` e `rest_opp_character`
  tambem executam junto do buff defensivo. Quarta fatia: `add_don` e
  `set_don_active` tambem executam junto do buff defensivo. Quinta fatia:
  remocoes simples `KO` e bottom-deck junto de buff defensivo tambem executam;
  bounce puro segue fora da rota defensiva. Ainda faltam eventos [Counter] com
  efeitos extras agressivos/estado complexo (`bounce` puro, `play`,
  buscas/topdeck/life) e heuristica mais fina.
  Já corrigido nesta auditoria: `extra_steps` de substituição (`trash self + draw`)
  agora executam.

---

## 🔴 FILA ANTERIOR ainda aberta

### Stubs sem lógica de decisão
- [ ] choice (19) — heurística de valor
- [ ] conditional_stack (OP15-092) — custo-benefício por threshold
- [ ] set_base_power (8) — integrar em effective_power() (6+ pontos)
- [ ] lock_opp_attack_unless_pays (OP08-043) — "vale pagar?"
- [ ] deck_reorder_rest / deck_top_rest (21) — DECK_REORDER, heurística de ordem. Próximo bloco.

### Reserva de DON em combate
- [ ] plan_don_distribution não subtrai reserva defensiva (usa don_available cru)
- [ ] on_opponent_attack timing não existe (72 cards em "passive"). Precondição da reserva fina.

### Turn Planner
- [x] ~~can_lethal_this_turn ainda cheata lendo self.opp.hand para counters~~ —
  corrigido em 29/06/2026. Agora usa counters revelados + estimativa por tamanho
  de mão oculta.
- [ ] 5 funções órfãs — deletar ou integrar
- [ ] Otimização estrutural de performance: reduzir `deepcopy` no Turn Planner
  ou cachear cálculos caros (`_don_reserve_for_defense`, defesa/counter,
  geração de ações). Em 29/06/2026 foi feita só uma poda de orçamento
  (`max_steps=8`, Monte Carlo=6) para recuperar o tempo do broad; não é a
  solução definitiva.

### Parser — cobertura
- [ ] cartas com card_text mas effects vazio — revalidar contagem (2148 com efeito agora)
- [ ] opponent has N+ DON (~8) — sem parser
- [ ] place-at-bottom-of-deck (~14, achado no "OUTROS") — mecânica nova
- [ ] OP15-074 Varie — DON sem sinal, aguarda foto

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

## ROADMAP
1. Consertar lógica — EM ANDAMENTO (vários blocos fechados nesta sessão)
2. Auditar via replay — iniciado (Imu vs Sanji revelou Problemas 1/2/3)
3. Tunar heurísticas por simulação em volume — AQUI MORA QUASE TODO O GANHO
4. ML — só se 1-3 prontos e baterem teto. Descartado por ora (25/06): herdaria bugs de
   execução; não "aprende conforme ensina" — quem faz isso é o parser por mecânica.
