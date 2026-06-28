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

### Gaps reais confirmados — 4 (+ 1 parcial barato)
- [ ] OppNoBlockerThisTurn — oponente não bloqueia (habilita lethal, alto impacto).
  Hoje só existe trava por 1 batalha (`blocker_lock_battle`) ou por carta
  específica (`cannot_block_until`); falta "campo todo, turno inteiro".
- [ ] Freeze (don/stage/card) — `lock_opp_character_refresh`/`lock_opp_don_refresh`/
  `lock_self_character_refresh` são reconhecidos mas SEM lógica de refresh
  implementada (`decision_engine.py:1722`, comentário confirma).
- [ ] CantPlayAnyCardsFromHand / CantPlayAnyCharactersToField DIRECIONADO AO
  OPONENTE — trava control (Imu). Hoje `self_cant_play` só afeta o próprio
  jogador (`me.*`), nunca o oponente.
- [ ] (parcial, barato) Buff dinâmico por DON anexado / custo do topo do deck —
  framework `buff_power_per_count` já existe e cobre várias fontes (trash,
  events_in_trash, rested_don, hand, etc.); falta só 2 branches novos.
- [x] ~~DealDamage/TakeDamage~~ — já implementado (`deal_damage`)
- [x] ~~ShuffleHandIntoDeck / CycleEntireHandToDeckBottom~~ — já implementado
  (`shuffle_hand_into_deck`, parâmetro `dest`)

### "Médios" — 7, na verdade TODOS ausentes (categorização original invertida)
PeekSelfLife/OppLife, TrashAllFaceUpLife, MatchLeaderToBasePower (set_base_power
só aceita valor fixo, não dinâmico), SaveTargetName (sem memória entre steps),
ForceOpponent, QueueUpEndOfTurnAction/OppMainPhase, FieldCantAttackLeader
(`cannot_attack_self` é outra coisa — trava a própria carta, não o ataque ao
líder). Nenhum tem urgência — implementar quando aparecer carta real no meta
que dependa.

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