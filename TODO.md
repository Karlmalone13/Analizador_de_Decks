# TODO — Analisador de Decks OPTCG

**Última atualização:** 26 de junho de 2026
**Estado:** 2148 cards com efeito (subiu de 2138), parser auditado OP-02 a OP-15
**Baseline:** commit bbb4d31 (set_don_active + mill) + viabilidade transacional (a commitar)
**Repo:** github.com/Karlmalone13/Analizador_de_Decks

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

- [ ] **Problema 2 — _choose_to_trash não avalia qualidade**: Imu trashou Ground Death
  (removal) como custo no T1 tendo cartas piores. Mesma família do conserto de
  viabilidade. PRÓXIMO candidato.
- [ ] **Problema 3 — Five Elders (c10) nunca jogada**: na mão T7→T11 com 9 DON.
  Correto (nunca teve 10 DON) ou subvalorização? Investigar.

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

### "Médios" — 5 (SaveTargetName e MatchLeaderToBasePower implementados em 28/06/2026)
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

PeekSelfLife/OppLife, TrashAllFaceUpLife, ForceOpponent, QueueUpEndOfTurnAction/
OppMainPhase, FieldCantAttackLeader (`cannot_attack_self` é outra coisa — trava
a própria carta, não o ataque ao líder). Nenhum tem urgência — implementar
quando aparecer carta real no meta que dependa.

### Dívida técnica grande (consciente, fora de escopo)
- [ ] Sistema de imunidade inteiro (ImmuneToKO/Removal/Combat/Effect/Strikes) — família
  ausente, ~6 variantes. Raro no meta, custa muito (toca combate + remoção). Não agora.

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
- [ ] can_lethal_this_turn ainda cheata lendo self.opp.hand para counters
- [ ] 5 funções órfãs — deletar ou integrar

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