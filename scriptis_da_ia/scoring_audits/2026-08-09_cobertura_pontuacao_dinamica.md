# Auditoria de cobertura — "pontuação dinâmica" (bloco 475)

> Passo 1 da tarefa registrada no `TODO.md`/HANDOFF bloco 473/474: mapear o
> que `decision_engine.py` já considera em cada função de score vs. os
> fatores que o usuário quer ver de forma mais dinâmica (efeito/mecânica,
> mão própria, mão do oponente, blocker, vidas, número de personagens em
> campo, número de personagens que oferecem ameaça real). Nenhuma mudança
> de código nesta auditoria — só mapeamento factual, com linha citada,
> pra decidir DEPOIS (passo 2, calibração por volume) o que realmente vale
> a pena mexer.

Funções auditadas (as 4 citadas pelo usuário + 2 helpers que elas usam):
`avaliar_carta` (10909), `score_attack_target` (11922), `_score_play_action`
(13352), `_generate_attach_don_actions` (14725), `field_advantage` (10023),
`critical_threats` (10051). Linhas em `optcg_engine/decision_engine.py`.

Outras superfícies de score encontradas na varredura, não pedidas
explicitamente mas relevantes pro quadro geral: `_score_activate_main`
(13756), `_generate_and_score_actions` (14433, orquestrador que chama as
outras), `char_value_score` (9994), `search_card_value` (11138),
`stage_worth` (11181), `opp_combo_threat` (~10068, mitigação documentada no
próprio código pro gap "critical_threats só olha o board atual, não o que o
trash pode reanimar").

## Tabela de cobertura por fator

| Fator pedido pelo usuário | Cobertura hoje | Onde |
|---|---|---|
| Efeito/mecânica da carta | **Completa e bem granular.** `get_card_flags`/`get_card_effects` alimentam quase todo bônus em todas as 4 funções (draw, search, KO, bounce, rest, buff, give_don, gain_life, blocker, rush, double_attack, unblockable, banish, trigger, activate_main, when_attacking, on_ko, passive/continuous, don_cond_keywords). | `avaliar_carta` 10989-11082; `score_attack_target` 12055-12075; `_score_play_action` 13364-13594; `_generate_attach_don_actions` 14742-14926 |
| Mão própria | **Coberta, mas parcial por função.** `avaliar_carta` só olha tamanho (`len<=3` pro bônus de draw); `_score_play_action` itera conteúdo real (valor de cada carta via `avaliar_carta` recursivo, pra nested `play_card` e pra penalidade de `self_cant_play`). | `avaliar_carta` 11029; `_score_play_action` 13414, 13611-13622 |
| **Mão do oponente** | **GAP CONFIRMADO.** Nenhuma das 4 funções lê `len(opp.hand)` como fator geral. Só existe: (a) `_effect_conditions_met` (`opp_hand_gte`/`hand_fewer_than_opp_by_gte`, linhas 11260-11261) — só ativa se a PRÓPRIA carta declarar essa condição no texto; (b) `opp_counter_potential()` — soma VALOR real dos counters na mão do oponente (não tamanho), e só entra em `score_attack_target` no ramo de ataque ao LÍDER (11998); o fallback por tamanho (`n_unknown = len(opp.hand) - len(known)`) só ativa com `self_play_info_hidden`, nunca setado hoje (comentário no próprio código). `GameState.estimated_counter()` (linha ~1370, `len(self.hand)*1000`) existe mas **nunca é chamado em lugar nenhum** — código morto. | Confirmado ausente em `avaliar_carta`, `score_attack_target` (ramo character), `_score_play_action`, `_generate_attach_don_actions` |
| Blocker | **Coberta bem.** Próprio blocker (bônus escalado por vida própria); blocker do alvo em ataque (`+60`); `opp.blockers_active()` gate pro bônus de unblockable; blocker como keyword em `_generate_attach_don_actions`. | `avaliar_carta` 10966-10972; `score_attack_target` 12004-12005, 12071; `_generate_attach_don_actions` 14872-14877 |
| Vidas (própria/oponente) | **Coberta e bem granular**, com limiares específicos (`<=1/<=2/<=3`) em quase toda função. | `avaliar_carta` 10945-10972, 11061-11063; `score_attack_target` 11992-11995; `_generate_attach_don_actions` 14876-14887 |
| Número de personagens em campo (própria) | **Parcial.** `_score_play_action` conta de verdade (`len(field_chars)>=5` guarda de board cheio); `avaliar_carta` NÃO conta diretamente — só entra via `field_advantage()` (diferença de VALOR de board, não contagem) dentro dos bônus de KO/bounce. | `_score_play_action` 13517-13520; `avaliar_carta` 11036, 11042 (via `field_advantage`) |
| Número de personagens em campo (oponente) | **Parcial/fraca.** Em `avaliar_carta` é só checagem de EXISTÊNCIA (`if self.opp.field_chars`), não contagem — mesmo bônus se o oponente tem 1 ou 5 personagens. `field_advantage()` usa VALOR agregado, não contagem. Contagem real só aparece em `critical_threats()` (tamanho da lista retornada) e no consumo dela (não nas 4 funções auditadas diretamente). | `avaliar_carta` 10951, 11038, 11043 (truthy, não count) |
| Personagens que oferecem ameaça real | **Existe, mas não plugado nas 4 funções centrais.** `critical_threats()`/`future_threat_value()` já pesam ativação, keywords (blocker/double_attack), diferença de power vs. líder próprio — mas é consumida no nível de orquestração (`_generate_and_score_actions`, prioridade de análise), não dentro de `avaliar_carta`/`score_attack_target`/`_score_play_action` diretamente. `score_attack_target` tem sua própria lógica paralela de "ameaça" pro alvo específico do ataque (`tgt_effects`), que é redundante em espírito com `future_threat_value` mas não a reusa. | `critical_threats` 10051-10066; `future_threat_value` 10032-10049; consumida em `_generate_and_score_actions` |

## Achados que não são gap de fator, mas afetam a auditoria

1. **`opp_combo_threat` já documenta, no próprio código, um gap primo deste**:
   `critical_threats()` só olha o board atual do oponente, nunca o que o
   trash dele pode reanimar. Já mitigado por função separada — não é um
   gap novo, é confirmação de que o time já rastreia esse tipo de lacuna
   quando aparece.
2. **`GameState.estimated_counter()` é código morto** (nunca chamado) — se
   a decisão do passo 2 for adicionar peso de mão do oponente, é candidato
   natural a reaproveitar/deletar em vez de escrever um estimador novo do
   zero.
3. **`score_attack_target` (ramo character) tem sua própria leitura de
   "ameaça" do alvo** (`tgt_effects`, linhas 12055-12075) que se sobrepõe
   conceitualmente a `future_threat_value()`/`critical_threats()` sem
   reusar — duas fontes de verdade pro mesmo conceito ("esse personagem é
   perigoso"), risco de decisão duplicada (ver
   `scriptis_da_ia/REGRA_SEM_DUPLICACAO.md`). Vale investigar no passo 2 se
   dá pra unificar sem quebrar o que já funciona, mas **não é urgente**
   nem foi pedido — registrado como observação lateral.

## Conclusão do passo 1

O único gap **confirmado e genuíno** contra a lista do usuário é **mão do
oponente como fator geral de score** — hoje só existe em: (a) condições
específicas de texto de carta (`opp_hand_gte`), e (b) valor de counter no
ramo de ataque ao líder. Não existe em nenhuma função como um sinal de
pressão estratégica genérico (ex.: "oponente com poucas cartas na mão →
mais seguro pressionar" ou "oponente com mão cheia → mais cautela com
KO/remoção porque pode ter counter/resposta").

Os outros fatores pedidos (blocker, vidas, efeito/mecânica) já têm
cobertura sólida. Contagem de personagens (própria e do oponente) tem
cobertura **parcial** — existe checagem de existência/valor agregado, mas
não contagem direta na maioria dos lugares, o que é uma forma mais fraca
do mesmo pedido do usuário ("número de personagens"). "Ameaça real" já tem
uma implementação (`critical_threats`), só não está plugada nas funções de
score por carta/ação — está no nível de orquestração.

**Não mexi em nada agora.** Isso é matéria-prima pro passo 2 (decidir o
que vale calibrar, com volume de simulação — `bot_efficiency_report.py`
antes/depois — não reescrita ampla de uma vez).

## Passo 2 (mesma sessão, 09/08) — implementado a pedido do usuário

O usuário pediu pra atacar 4 dos itens acima nesta mesma sessão (achado
lateral do dedupe, mão do oponente, contagem de personagens do oponente,
ameaça real). Mudanças feitas em `optcg_engine/decision_engine.py`:

1. **Dedupe `score_attack_target` vs `future_threat_value`**: extraído
   `GameAnalyzer._effect_threat_weight(card)` como fonte ÚNICA de peso por
   efeito/keyword ("esse corpo é ameaça?"), usada por `future_threat_value`
   (quanto ainda produz) e por `score_attack_target` (quanto vale matar).
   Achado lateral: o código antigo de `score_attack_target` somava
   `activate_main`/`blocker` DUAS vezes (via `efeito_ameaca` E via checagem
   individual) — corrigido de graça pelo dedupe.
2. **Mão do oponente → estimativa de counter**: `opp_counter_potential()`
   só ligava a estimativa estatística por tamanho de mão
   (`counter_estimation.py`, já testada) com `opp.self_play_info_hidden`,
   flag NUNCA setada em produção (nem live, nem self-play). O caminho ao
   vivo já seta uma flag irmã, `hidden_information_masked`
   (`BOT/engine_server/server.py:_dto_to_gs`), que essa função ignorava —
   resultado real: toda carta oculta na mão do oponente ao vivo contava
   como counter=0 na defesa do líder. Fix: agora QUALQUER uma das duas
   flags liga a estimativa.
3. **Contagem de personagens do oponente**: bônus de KO/bounce em
   `avaliar_carta` agora escalam (limitado a +15/+10) com quantos
   personagens o oponente tem em campo, em vez de só "existe ou não
   existe" (mesmo bônus com 1 ou 5 alvos antes).
4. **Ameaça real plugada**: os mesmos bônus de KO/bounce agora somam um
   extra (+20/+15) quando `critical_threats()` (já existente, mesma fonte
   de peso do item 1) confirma pelo menos uma ameaça de efeito real no
   board do oponente — reuso, não reinvenção.

**Validação feita** (nível regressão, não calibração completa):
`smoke_fast.py` 100% (incluindo 2 testes novos pro item 2) e
`audit_replay.py --n 30 --seed 98` com as 4 mudanças juntas: 0 exceções,
0 anomalias.

**O que NÃO foi feito, fica pendente**: calibração por volume de verdade
(`bot_efficiency_report.py` antes/depois com cohort real) pros novos
pesos/escalas (+15/+10/+20/+15 nos itens 3/4, a mudança de escala do
dedupe do item 1 blocker 60→45/double_attack 50→65). `audit_replay.py`
confirma ausência de crash/anomalia estrutural, não que os pesos estão
bem calibrados — isso é trabalho de próxima sessão com volume real,
consistente com o próprio roadmap do projeto.
