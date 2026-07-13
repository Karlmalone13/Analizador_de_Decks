# HANDOFF — registro de troca entre IAs (Claude / Codex)

## 2026-07-13 (123) - Claude — SESSÃO GRANDE: núcleo de avaliação + busca (plano mestre)

**LEIA PRIMEIRO:** [scriptis_da_ia/PLANO_AVALIACAO_E_BUSCA.md](scriptis_da_ia/PLANO_AVALIACAO_E_BUSCA.md)
(doc vivo, tem tudo com detalhe) + memória `project_plano_avaliacao_busca.md`.
Mudança de método decidida com o usuário: parar o whack-a-mole de heurística
(pêndulos) e construir UMA função de avaliação global + perfil derivado do deck
+ busca + tunagem por self-play. Itens 0/1/2/5 avançados nesta sessão.

**O QUE FOI ENTREGUE (tudo commitado):**
1. **`evaluate_state_v2` LIGADA (`USE_EVAL_V2=True`) — item 1 CONCLUÍDO.** Régua
   única (vida curva/board/mão/DON/cobertura/tempo + eixos do perfil). Validação
   rigorosa MC=6/n=50, Imu-v2 vs opp-v1: winrate Krieg 0.38→0.40, Kid 0.34→0.36,
   Teach 0.88→0.96, dano e %líder sobem nos 3, SEM regressão. Ponto de drop-in:
   `_simulate_sequence_once` → `_evaluate_state_v2`.
2. **Tunagem (item 5 núcleo): `tune_weights.py`** (coordinate-ascent, self-play
   A=v2 vs B=v1, maximin sem-regressão, MC=4+early-stop). Achou dmg 120→180 e
   counter_hand 6→9 (só 2 pesos, confirmou diagnóstico). Pesos em
   `eval_weights.json` (com camada de confiança `_meta` origin=learned).
3. **Perfil do deck `deck_profile.py` (item 2)** — UNIVERSAL (provado em 7+ decks:
   Imu/Sakazuki/moria/Crocodile todos com reanimação, engines diferentes).
   Deriva arquétipo + eixos (trash-staircase/reanimação-gargalo/inversão/
   disrupção) + PAPÉIS de carta. Alimenta a evaluate_state.
4. **Trilha conhecimento/dados**: `knowledge/crawl_decks.py`+`parse_decks.py`
   baixaram os 103 guias oficiais → **55 decks completos** p/ gauntlet.
   `crosscheck_archetypes.py` = QA (perfil derivado vs rótulo do PDF nos 55).
5. **`card_taxonomy.py` = vocabulário ÚNICO** (arquétipo+disrupção+papéis+
   magnitude+conds) compartilhado por deck_analyzer(front) e deck_profile(motor).
   Acabou a duplicação. NÃO é 2º motor (dado, não decisão).
6. **Gramática R4b (GAP1/GAP3 do crosscheck)**: disruption = denial-only
   (102/102→51/102 decks), remoção genérica desinflada, negate ganha peso de
   controle. NÃO afeta a evaluate_state (que só usa trash/reanim/inversão).
7. **1º/2º ciente do perfil** (`choose_turn_order`), 3 ideias baratas do PDF
   (papéis / camadas de confiança / DecisionTrace), avaliação de 3 repos MTG.

**ESTADO / SALVAGUARDAS:** smoke_test 100%; v2 ligada e validada; front (api.py)
importando; fix de gramática não invalida a v2. Pesos são globais/Imu-tunados
por ora (cache per-deck = pipeline self-service do item 5, a fazer).

**PRÓXIMO (roadmap comprometido, ver PLANO seção "O BOT ENTENDE O DECK"):**
R1 mulligan guiado pelo perfil · R2 sequenciamento de abertura · R3 combos
arbitrários (sinergia genérica; DUAS REGRAS: não individual, não 2º motor;
convergir c/ synergy_states) · R4 enriquecer papéis · R4b resíduo (aggro-por-
estatística p/ híbridos Vivi/Enel/Moria) · item 3 busca c/ resposta do oponente
(quebra o teto do vetor-de-pesos-único) · item 5 full (tunagem per-deck cacheada).
PENDÊNCIA ANTIGA: validar ao vivo a leva 7 (Mars blocker etc.) — reabrir jogo.

## 2026-07-12 (122) - Claude

### DTO com trash + deckCount (prioridade #1 do bloco 121) — IMPLEMENTADO, falta teste ao vivo

O plugin C# agora transmite a lixeira (lista de `CardDto`, info pública) e a
contagem do deck no `PlayerDto`, e `server.py` reconstrói `gs.trash` real e
usa `deckCount` no lugar dos 10 placeholders (fallback 10 mantido pra plugin
antigo). Arquivos: `GameStateDto.cs` (campos `trash`/`deckCount`),
`GameStateBuilder.cs` (lê `Lgo_MyTrash`/`Lgo_MyDeck` — nomes confirmados no
dnspy-export `PlayerState.cs`), `server.py` (`PlayerDto` + `_dto_to_gs`).
Vale pros DOIS jogadores (BuildPlayer/_dto_to_gs são compartilhados).

Validação: `dotnet build` OK (warnings pré-existentes); smoke do
`_dto_to_gs` com trash=11/deckCount=37 reconstruiu certo. **NÃO testado em
partida real** — o efeito esperado ao vivo (condicional, ver memória
`feedback_nao_declarar_resolvido_sem_partida_real`): Ground Death
(OP14-096) counterar com trash>=10, imunidade dos Celestial Dragons
(trash_gte:7) reconhecida, progresso do GamePlan > 0. Requer rodar
`BOT\setup_bepinex.bat` (recompila/copia o plugin) com o jogo fechado e
jogar uma partida com o usuário.

### Segunda leva da mesma sessão: counter por ganho líquido + give_don + 2 achados novos do auditor

Todas as pendências do bloco 121 atacadas (engine puro, sem partida real —
condicional até o próximo teste ao vivo):

1. **Política de counter reescrita por ganho líquido** (`should_use_counter`
   em `decision_engine.py` + `select_counter_cards` em `sim_bridge.py`).
   As duas pontas do bug real eram o mesmo defeito (gates fixos por faixa
   de vida): com 4 vidas, needed=1 passava no gate `<=1000` e gastava
   counter em jab 5000v5000; com vida baixa, needed>2000 estourava o gate
   da faixa e recusava mesmo cobrindo. Agora: countera se o PITCH das
   cartas gastas < valor da vida. Peças novas:
   - `pitch_cost_as_counter`: avaliar_carta MENOS o componente de counter
     (extraído como `_counter_stat_bonus`) — sem isso a decisão era
     circular (counter caro de usar por ser counter). O componente-base
     volta escalado por vida (opção futura: 1.0 com 4+ vidas → 0.1 com 1).
   - `pick_counters`: seleção que MINIMIZA pitch (não counter stat) —
     não pitcha mais Saturn jogável tendo vanilla na mão; usada pelos
     DOIS caminhos (use_counter do simulador e select_counter_cards ao
     vivo, incl. eventos [Counter] no pool).
   - Curva de vida própria na escala do avaliar_carta (12/65/150/250 para
     4+/3/2/1 vidas; vida 0 = sempre countera). `life_redirect_cost` roda
     frio demais nessa escala (corpo custo 5 avalia 100-150).
   Validado com teste dirigido: vida 4 não gasta; vida 2 countera jab
   escolhendo a vanilla e preservando Saturn.
2. **give_don (Kuma)**: branch 'delta' de `order_target_candidates`
   desempatava só por just_played — líder e Shalria 0-poder empatavam e a
   ordem dos candidatos decidia. Agora: alvo restado/recém-jogado por
   último, desempate por MAIOR poder efetivo (líder 5000 > Shalria 0).
3. **Checks G/H no auditor** (via replay_log, eventos 'attack' com snapshot
   antes/depois): G = counter gasto defendendo líder com 4+ vidas; H =
   golpe levado com vida <=2 (ou letal com vida 0) tendo counter que
   cobria. G foi de 5→0 e H de 12→1 (caso restante: precisar 2+ cartas
   por 1 vida, recusa defensável) ao longo da iteração.
4. **Achado novo (spy de trash, 13x/20 partidas): searchers milavam a
   win-con** — take-choice do look_top_deck usava avaliar_carta puro
   (Five Elders ~45 perdia pra qualquer corpo jogável e ia pro trash no
   trash_rest; a cópia milada é irrecuperável — o play_from_trash dela
   filtra power 5000). Fix: take-choice usa `_trash_value` (avaliar_carta
   + proteções de GamePlan/carta cara/counter event).
5. **Sacrifício próprio escolhia a carta MAIS valiosa**: executor de
   ko/trash_character com pool próprio (self_character/all_character)
   usava choose_highest_board_value (correto só pra remoção no oponente).
   Novo `choose_lowest_board_value` (rules_facade) — consistente com a
   régua de _worth_paying_optional_costs.
6. **Falso positivo C/D do auditor**: win-con jogada no turno (combo da
   Five Elders trasha o próprio campo incluindo ela mesma — assinatura
   idêntica a "trashou da mão") flagava C, e a 2ª cópia na mão flagava D.
   Guarda novo: play_card da win-con no turno suprime C/D.

Validação final: smoke_test 100%, smoke_test_broad 40/40, auditor
A/B/C/D/E/F/G zerados, H=1 (defensável). NÃO testado em partida real.

**Auditor agora é determinístico**: partidas motor-vs-motor variavam
entre processos com a MESMA seed (hash randomization de string muda a
ordem de iteração de `set`, e há desempates sensíveis a isso no engine) —
pista de flag evaporava antes de dar pra instrumentar. O
`audit_antipatterns.py` agora se relança com `PYTHONHASHSEED=0`; dois
runs com a mesma seed saem byte a byte idênticos (validado). Flag do
auditor virou caso reprodutível: re-rodar com a mesma seed + spy na
partida acusada. Também é o pré-requisito de comparação limpa antes/
depois pra tunagem de heurística (mesmo conjunto de partidas).

**Pendência restante do bloco 121:** flag D residual em postura LETHAL
(segurando a bomba pra tentar matar) — hoje zerou nos runs, mas não foi
investigada a fundo. E a prioridade #1 (DTO trash/deckCount) segue
aguardando teste ao vivo com o usuário.

### Sétima leva: partida 23:41 (vs Kid) — 6 fixes dos reports detalhados do usuário

Log `Imu-B_x_Eustass.Captain.Kid-Y_2026-07-12T23.41.50` salvo. Confirmado
no log: Never Existed ATIVOU (+4000 de verdade — fix da leva 4 funcionou)
mas mirou errado; counters em vida baixa funcionaram; ponto positivo
reportado pelo usuário (stage→Mars→Shalria→líder mirando Shalria).

1. **Passivas condicionais de keyword nunca ligavam** (causa raiz dupla:
   "Mars não é blocker" + parte da passividade do Nusjuro): _make_card só
   aplica keyword_* incondicional; gain_blocker/gain_rush com trash_gte 7
   (padrão dos Celestial Dragons) não tinham NENHUM caminho de aplicação.
   Novo `apply_conditional_keyword_passives` (grant-only, idempotente —
   trash só cresce) chamado no __init__ do DecisionEngine pros DOIS lados.
2. **Never Existed buffou o Mars parado em vez do líder sob ataque**:
   buff_power era tratado como ('set', 4000) ("poder vira 4000" → preferia
   o alvo mais fraco). Agora é ('delta') e, em janela de defesa, o alvo
   que está LEVANDO o golpe tem prioridade máxima se o buff o salva
   (empate favorece atacante — precisa ficar estritamente acima).
3. **Pêndulo do trash de custo** (leva 6 exagerou): Mars 5000 recém-descido
   via stage foi sacrificado pelo custo do líder/Shalria 2x. A perda do
   campo agora soma custo situacional: recém-entrado +35, blocker (incl.
   condicional) +25, último corpo +40.
4. **Mary Geoise substituiu o Empty Throne DE NOVO** (2º report): o
   desconto por avaliar_carta era raso demais (Empty Throne avalia baixo;
   o bônus de "activate_main recorrente" só existia pra CHARACTER). Nova
   régua `stage_worth` (avaliar cru + 40 se tem activate_main) dos dois
   lados; substituição com ganho <= 0 = -999 (bloqueio duro). E stage
   REDUNDANTE na mão avalia só o upgrade líquido (vira pitch barato —
   resolve também "tinha stage inútil na mão e trashou o Mars").
5. **Counter com mão gorda**: "8 cartas na mão levando dano toda hora" —
   orçamento de vida ganha +8 por carta acima de 5 na mão (vida 4, mão 8:
   12→36 — countera jab pitchando carta fraca; corpo bom continua caro).
6. **1º/2º decidido pelo ENGINE pela curva do deck** (pedido: nada de
   50/50): novo `choose_turn_order` (sim_bridge) + endpoint /turn_order +
   plugin coleta os códigos do deck e clica. Imu (curva 3.8, 9 cartas 7+,
   0 rush) → SEGUNDO. Aggro barato com rush → primeiro.

Validação: 6 cenários dirigidos reproduzindo a partida (todos passam),
smoke 100%, auditor 10 partidas quase zerado (A=1: bot SEGURANDO Mjosgard
jogável — comportamento pedido pelo usuário no item 5, o check A não
distingue reserva de counter), plugin compilado e copiado pro jogo
(23:57:17), server reiniciado com tudo. **Usuário precisa REABRIR O JOGO**
(DLL nova) antes de testar. NÃO testado ao vivo ainda.

### Sexta leva: partidas 23:03/23:09 (vs Krieg) — 3 fixes dos reports do usuário

Logs `Imu-B_x_Krieg-RG_2026-07-12T23.03.36` e `23.09.31` salvos no banco.
O trigger de evento (leva 5) FUNCIONOU ao vivo ("Activate Trigger" no
combat log + `[DEF] trigger OP13-096 -> True` no session log 22.41.02).

1. **Empty Throne no vácuo (3º report!) — CAUSA RAIZ ACHADA**: a regra
   "play_card sem card_type = CHARACTER" existia SÓ no _elegivel_para_play
   (sim_bridge); as outras TRÊS cópias da elegibilidade aceitavam o EVENTO
   "The Five Elders Are at Your Service!!!" (custo 1, 'five elders' nos
   sub_types/nome): `_step_is_viable` (gate), executor de play_card, e a
   varredura própria do `_should_activate_main` (~linha 6835). Com o
   evento na mão o gate dizia "elegível" e a ativação fizzlava no jogo.
   Default CHARACTER aplicado nas 3; reproduzido antes/depois com o estado
   real do turno 3 (gate False agora). LIÇÃO: regra duplicada em N lugares
   = bug sobrevive a N-1 fixes.
2. **Custo do líder Imu nunca trashava a Shalria do campo**: zona
   own_hand (prio 1) sempre vencia own_board (prio 3) no
   order_target_candidates — pagava o draw com Saturn da MÃO todo turno.
   Novo: ator com custo `trash_char*` põe own_board no MESMO tier da mão,
   perda por char_value_score (Shalria 0-poder usada « qualquer carta útil).
3. **Mary Geoise descida POR CIMA do Empty Throne**: jogar STAGE com stage
   própria em campo substitui — `_score_to_play` agora desconta
   avaliar_carta da stage atual (stage nova só compete se vale MAIS).

Validação: repro dos 3 cenários OK, smoke 100%, auditor 10 partidas com
ruído baixo (A=1, H=2 borderline — precisa olhar na próxima sessão:
m04 t11 needed=1 com 1000 na mão recusado). Server reiniciado 23:20 com
tudo. Obs de infra: `Get-ChildItem Length` MENTE pra session log aberto
(NTFS metadata) — o log de 22:41 parecia 0 bytes e tinha 34KB; ler o
conteúdo antes de concluir que não logou.

### Quinta leva: partida 15:27 — PRIMEIRO teste válido (server+plugin novos confirmados) + fix do trigger de evento

Log `Imu-B_x_Marshall.D.Teach-BY_2026-07-12T15.27.45` salvo no banco.
Perícia: server PID 4208 (15:00, código de hoje) + plugin 14:59:50 no jogo
— dessa vez os fixes RODARAM. Resultado mensurável vs baseline da análise:
bot fez 3 de dano (média anterior 1.3, três partidas anteriores 0-2),
counterou certo (Kuma/Shalria 1000, ZERO "for Counter 0"), give_don foi no
LÍDER, nenhum play no vácuo, 7 ataques em 5 turnos (1.4/t vs 0.88). Ainda
perdeu: passividade relativa continua (humano 2.0 atk/t) e o combo Five
Elders não disparou na partida.

Fix novo (reportado pelo usuário): **trigger de EVENTO recusado sempre** —
`resolve_trigger_choice` avaliava `activate_main_effect` com `on_ko_value`
(régua do padrão de PERSONAGEM; evento dá 0 → recusa). "Are At Your
Service" da vida ia pra mão em vez da busca grátis. Agora: EVENTO sem
bloco [Counter] usa o trigger se o main é viável (`_step_is_viable`);
evento COM [Counter] segue indo pra mão. Validado unitário (096→True,
Ground Death→False), smoke 100%, auditor 10 partidas ZERADO (até o H
residual sumiu). Server reiniciado com o código (health 200).

**Discussão estratégica com o usuário (pergunta "hora de ML?")**: ver
resposta na sessão — resumo: 3 camadas de bugs de encanamento (server
velho 2x, plugin descartando counter-event, DTO cego) consumiram os testes
ao vivo; a linhagem de pontuação não está esgotada nem foi de fato testada
com informação completa até 15:27. Próximo degrau proposto: tunagem de
pesos por volume de simulação (auditor determinístico + winrate
motor-vs-motor já permitem A/B limpo) antes de qualquer ML de verdade.

### Quarta leva: teste ao vivo do usuário (2 partidas 14:25/14:30) — INVÁLIDO + 5 fixes achados

**O teste rodou com o SERVIDOR DE ONTEM**: o processo na porta 8765 era o
PID 12932, iniciado 11/07 01:44 — NENHUM fix de hoje (DTO trash, counter
policy etc.) estava ativo. Lição operacional: SEMPRE checar
`Get-NetTCPConnection -LocalPort 8765` + data do processo antes de validar
ao vivo. Reiniciei (novo PID em 15:00, health 200). Os 2 logs foram salvos
no banco (`Imu-B_x_Marshall.D.Teach-BY_2026-07-12T14.25.08` e `14.30.52` —
ATENÇÃO: são a MESMA partida, o autosaved é snapshot parcial do final).

Mesmo assim o log rendeu 5 fixes novos (commitados nesta leva):

1. **Plugin descartava evento [Counter] como counter de stat 0**
   (`BotExecutor.PlayCounters`): "Discard ...Never Existed... for Counter
   0" — 2x na partida, ZERO defesa, bot morreu com counter na mão. Agora
   evento → `HandleMouseClickCardWaitOnCounters` (o handler do clique
   humano, enfileira a ação [Counter] de verdade) SEM clicar ResolveAttack
   no mesmo tick (o step reabre e o /defense reavalia com o buff);
   `_counterEventTried` evita loop se o jogo recusar. Personagem com stat
   continua no DiscardCardForCounter.
2. **select_counter_cards não checava o custo da PRÓPRIA carta do evento**
   (1 DON ativo, o jogo resta ao ativar) — o simulador interno já checava
   (try_counter_event_power); espelhado no caminho ao vivo.
3. **Ground Death jogado no vácuo** (negate_effect com board do opp vazio):
   a penalidade de evento-sem-alvo era hardcoded ko+opp_stage (fix pontual
   do Never Existed, 11/07). Generalizada em `_score_to_play` via
   _step_is_viable/_check_conditions pra QUALQUER evento.
4. **Mjosgard descido com on_play morto** (reanimar Mary Geoise exige
   vida<=3, bot tinha 4): penalidade nova em _score_to_play pra CHARACTER
   cujo on_play não dispara agora (-90 se corpo 0 de poder, -40 senão).
5. **Bot agora decide 1º/2º quando ganha o dado** (`Start_WaitOnTurnOrder`
   não era tratado; 50/50 aleatório de propósito — pedido do usuário pra
   ver a curva par também; escolha estratégica de curva seria lógica de
   deck, não vive no plugin).

Também: `parse_combat_log.py` aceita logs AUTOSAVED (rich-text
`<mark><link=...>` do Unity convertido pro formato final antes dos
patterns).

Validação: smoke 100%, auditor 10 partidas A-G=0 H=1 (defensável), plugin
compila. Plugin PRECISA ser reinstalado: **jogo fechado →
`BOT\setup_bepinex.bat` → abrir jogo** (server novo já está no ar).

### Terceira leva: análise "Imu humano vs Imu bot" (passividade)

A pedido do usuário ("ganho sem levar dano"), comparei as 5 partidas dele
de Imu com as 12 do bot (banco de logs) + 10 motor-vs-motor com o engine
de hoje. Relatório completo com tabela e plano:
`scriptis_da_ia/analise_imu_humano_vs_bot_2026-07-12.md` (+ seção nova no
topo do TODO.md). Conclusão-chave: bot ao vivo 0.88 atk/turno e 42% no
líder vs humano 2.03 e 82% — mas o MOTOR com informação completa faz 91%
no líder; a causa raiz principal era o DTO sem trash (Nusjuro OP13-080,
o beater do deck, tem Rush+imunidade com trash>=7 — ao vivo era avaliado
como vanilla e ia pro descarte). Já corrigido hoje, validação ao vivo
pendente. Detalhe de análise: attach de DON do bot NÃO gera linha no
combat log (reflection pula o log do jogo) — parse subconta agressividade
do bot; os counters baratos do usuário (1000-2000 sempre bastaram) provam
os ataques quase secos.

---

## 2026-07-11 (121) - Claude

### Mudança de método: auditor automático de anti-padrões + 6 fixes achados por ele (sem gastar partida do usuário)

Depois de mais 2 partidas reais com problemas (logs `2026-07-10T23.38.05` e
`2026-07-11T00.49.30`, salvos no banco) e frustração explícita do usuário
com o ciclo "joga → acha bug → fix → joga de novo", mudei o método:
**`scriptis_da_ia/audit_antipatterns.py`** (novo, permanente) roda partidas
motor-contra-motor com os decks reais e acusa turno a turno os anti-padrões
que o usuário apontou ao vivo. Iterar contra ele ANTES de pedir partida real.
Uso: `python audit_antipatterns.py --n 20 [--deck-a Imu --deck-b "Barba Negra BY"] [--detalhes]`.
Checks: A don ocioso c/ jogada disponível; B líder não atacou; C win-con
trashado da mão; D win-con pagável não jogado; E stage não usado c/ alvo;
F líder com draw de activate_main não usado (genéricos — win-con/alvos vêm
do compute_game_plan/card_effects_db, não hardcode). Turnos que TERMINAM a
partida não contam (1ª versão flagava DON "parado" de turno de lethal).

**Fixes achados pelo auditor + pelos 2 logs reais (cada um validado
re-rodando o auditor com o mesmo seed):**

1. **GamePlan fase 2b — bypass do Monte Carlo pro win-con** (flag D, era
   2x/20 jogos): o +600 do fase 2 colocava Five Elders no topo da lista,
   mas a escolha final do main_phase é por simulação MC de fim de turno —
   que NÃO enxerga o valor da reanimação (realiza-se no turno seguinte).
   Linhas "Empty Throne primeiro" (3 DON) venciam e a bomba ficava
   impagável de novo, todo turno. Fix: `main_phase` executa DIRETO a ação
   do topo quando é play do win_con_code com don_available >= don_target e
   priority != LETHAL (o caminho ao vivo já pega o topo direto — bypass só
   alinha o simulador interno). D caiu 2→0 (voltou 3x depois do fix do F
   mudar a forma das partidas — casos restantes são postura LETHAL
   segurando a bomba pra tentar matar, decisão discutível, NÃO investigada
   ainda; próxima sessão pode olhar).
2. **resolve_optional_effect não achava o LÍDER nem checava activate_main**
   (obs. do usuário: "Imu não trashou nenhuma Shalria, tá perdendo draw"):
   busca era só hand+field_chars (líder nunca achado → fallback genérico
   olhando só a mão → mão valiosa = recusa TODO turno), e o loop de
   triggers era só on_play/main (activate_main do líder nunca visto).
   Fix: pool inclui gs.leader e field_stage; loop inclui 'activate_main'.
3. **_worth_paying_optional_costs ignora o campo pro custo
   trash_char_or_hand**: Shalria de 0 poder gasta no campo é sacrifício
   quase grátis (e alimenta o plano de lixeira) — agora se
   min(board_value*10) <= 60 nos personagens elegíveis, paga. (Motor
   compartilhado — vale pros dois caminhos.)
4. **_step_is_viable: ko com target opp_stage olhava field_chars** — Never
   Existed (OP13-098) foi jogado no vácuo com o oponente SEM stage (1 DON +
   carta por nada, log 00.49.30). Agora checa opp.field_stage e cost_lte.
5. **order_target_candidates: prompt de "JOGUE carta da mão" usava régua de
   DESCARTE** (obs. do usuário: "usou o stage à toa"): own_hand rankeava
   por _trash_value (fix #115, correto pra descarte) — num deploy do Empty
   Throne o plugin clicava primeiro na carta mais descartável (evento
   INELEGÍVEL), o jogo recusava e o deploy fizzlava (3 DON + stage por
   nada) mesmo com Ju Peter elegível na mão. Fix: detecção de intenção
   (actor com step play_card source != self) → elegíveis primeiro por
   avaliar_carta desc, inelegíveis por último.
6. **Leader restado não oferecia activate_main** (flag F, 29x/20 jogos →
   0): guarda "fonte restada não ativa" (criada pra personagens com
   rest_self perdido pelo parser) pegava o LÍDER — Imu que atacava antes
   de ativar perdia o draw do turno. Fix: líder sem rest_self nos custos
   pode ativar restado (regra oficial não exige fonte ativa); personagens/
   stages continuam conservadores. TAMBÉM: bônus +30 no _score_activate_main
   pro ciclo trasha→compra quando o deck tem trash_target não batido
   (GamePlan) e a penalidade de early-game não se aplica nesse caso (antes
   o draw do Imu pontuava NEGATIVO em ~25% dos turnos).
7. **server.py: _declined_optional.clear() no /mulligan** — o cache de
   recusas (fix do bloco #120) é chaveado por (código, turno) e vazava
   entre PARTIDAS do mesmo processo.

Validação final: smoke_test 100%, smoke_test_broad 40/40, auditor com
A/C/E/F zerados e D=3 (casos LETHAL, ver item 1).

### Partida de teste 01:36 (log `2026-07-11T01.36.16`, salvo) — 2 fixes a quente + PENDÊNCIAS pra próxima sessão

O usuário testou ao vivo e vários sintomas persistiram. NÃO era arquivo
desatualizado (confirmado: server novo, PID 15064, score 105 do draw só
existe no código de hoje). Causas achadas:

8. **DTO sem deck → viabilidade de 'draw' sempre False AO VIVO**: o
   GameState reconstruído em `_dto_to_gs` tinha `deck=[]` (informação
   oculta) — `_step_is_viable('draw')` exige `len(deck)>0`, então
   `resolve_optional_effect` recusava o draw do líder TODO turno ao vivo,
   enquanto o simulador interno (deck completo) funcionava — POR ISSO o
   auditor dava F=0 e o jogo real falhava. Fix: `_dto_to_gs` preenche
   `gs.deck` com 10 placeholders (deck real nunca está vazio em jogo;
   nada do caminho ao vivo compra do gs.deck de verdade). LIÇÃO GERAL:
   diferença simulador-com-informação-completa vs ao-vivo-com-informação-
   oculta é uma CLASSE de bug que o auditor não pega — checar sempre que
   um comportamento diverge entre auditor e partida real.
9. **Stage ativado sem carta elegível** ("Choose 0 Friendly Targets"):
   `_should_activate_main` não validava steps `play_card` — mão só com
   custo 7+ e eventos, Empty Throne ativava mesmo assim (3 DON + stage
   por nada). Fix: gate novo usando o próprio `_step_is_viable`.

**PENDÊNCIA PRIORIDADE #1 (próxima sessão — decidido com o usuário ao
encerrar, 11/07 ~2h):** o DTO do plugin C# NÃO transmite o TRASH (nem
contagem do deck) — `PlayerDto` só tem hand/board/life/leader/stage/don
(`server.py` ~linha 90; confirmado também em `EngineClient.cs`). Isso é
a MESMA classe do bug #8 (deck vazio): o motor é um só, mas ao vivo ele
recebe um retrato incompleto do jogo. Consequências REAIS já observadas:
`gs.trash = []` ao vivo → (a) o bloco [Counter] do Ground Death
(OP14-096, exige `trash_gte: 10`) NUNCA é usável ao vivo — provável
causa direta da observação do usuário "tinha 2 eventos counter na mão e
não counterou"; (b) a imunidade dos Celestial Dragons (`trash_gte: 7`)
nunca é vista como ativa pelo caminho ao vivo; (c) o progresso do
GamePlan (`len(trash) < trash_target`) fica sempre em 0. Fix certo:
plugin C# enviar a lista do trash (informação PÚBLICA no jogo real — o
oponente vê a lixeira) + contagem do deck no `PlayerDto`
(`EngineClient.cs` captura, `server.py` reconstrói em `_dto_to_gs`,
substituindo os 10 placeholders por contagem real). Exige recompilar o
plugin (`BOT/setup_bepinex.bat`) e testar com o usuário presente.

**Demais pendências (reportadas pelo usuário nesta partida, NÃO
corrigidas):**
- **Kuma anexou o DON restado na Shalria (0 poder) em vez do líder** —
  branch 'delta' (give_don) de `order_target_candidates` desempata só por
  just_played; falta desempate por poder efetivo/utilidade do alvo.
- **Política de counter ruim nas duas pontas** (obs. do usuário): gasta
  counter cedo em jab 5000v5000 com vida 4 (incl. Saturn, personagem
  jogável de custo 4 — `select_counter_cards` ordena só por counter stat,
  sem olhar _trash_value da carta), e depois NÃO countera 3 ataques no
  turno 5 com +2000/+1000/2 eventos na mão. Verificar: Ground Death
  (OP14-096) tem `counter` com `conditions: {trash_gte: 10}` — pode ter
  sido recusa LEGÍTIMA (trash < 10); e a possível causa de não-counter
  dos +1000/+2000: should_use_counter/maior_por_vir. Auditor ainda não
  tem check de defesa — criar check G (counter gasto em ataque barato
  early) e H (ataque letal/valioso não counterado com counter na mão).

### Operacional
Python (`decision_engine.py`, `sim_bridge.py`, `server.py`) + novo
`audit_antipatterns.py`. Logs salvos:
`Imu-B_x_Marshall.D.Teach-BY_2026-07-10T23.38.05`,
`Imu-B_x_Marshall.D.Teach-BY_2026-07-11T00.49.30`.

---

## 2026-07-10 (120) - Claude

### GamePlan fase 2 (prioridade de win-con quando DON bate o alvo) + fix real do loop de ativação recusada

Continuação direta do bloco #119 (GamePlan v1 recém-commitado). Terceira e
quarta partida real do bot jogando Imu no mesmo dia (`2026-07-10T23.19.23.log`
e `2026-07-10T23.38.05.log`, ambos salvos no banco) — usuário reportou que
o turno 4 travava de novo do MESMO jeito que o achado anterior descrevia
("resolve_optional_effect sempre recusando custo só-DON", bloco #119),
mesmo já corrigido.

**1) O fix de ontem resolveu só metade do bug — loop de ativação
recusada.** Cruzando com o log do engine: mesmo com `resolve_optional_effect`
avaliando CORRETAMENTE (podendo legitimamente recusar por falta de alvo,
ex: Empty Throne sem "Five Elders" tipo certo na mão pra jogar de graça),
o `GameState` é reconstruído do ZERO a cada `/decide` — quando a resposta
é `False`, nada no estado muda, e a MESMA ativação de score alto é
reoferecida no próximo `/decide`, travando o turno em loop até o plugin
desistir sem nunca tentar a ação de score mais baixo que sobrava (achado
real: 4 propostas idênticas seguidas, `hand=5 don=4` parado o turno
inteiro). Fix: cache `_declined_optional: set[(codigo, turno)]` em
`server.py`, populado no handler `/defense` fase "optional" quando a
resposta é `False`; `choose_action` (`sim_bridge.py`) ganhou parâmetro
`exclude_activate_codes` que filtra essas ativações do próximo `/decide`
do MESMO turno, deixando o Turn Planner cair pra próxima ação da lista.
Confirmado em log real subsequente: turno trava no máximo 2x (não mais
4x) e progride normalmente até `0 acoes`.

**2) GamePlan fase 2 — prioridade do win-con quando o DON bate o alvo.**
Mesmo com o loop corrigido, o log seguinte (23.38.05) mostrou o problema
de fundo que a fase 1 (bloco #119) não cobria: turno 5, `don=9`
(quase o alvo de 10 do Five Elders), `top3: [(480,'attack'),(480,'attack'),
(470,'attack')]` — TODO o DON vai pra margem de ataque, turno após turno,
e a jogada da bomba nunca chega a competir. Usuário deu o exemplo
concreto: o próprio adversário (jogando Teach) fechou a partida
executando ZEHAHAHAHA (`OP16-116`, rest 8 DON: deploy Teach 093 de graça
+ nega efeito do Imu + ataque letal) — um "plano de jogo" deliberado de
guardar DON pro momento exato do combo, não gastar aos poucos.

Achado técnico importante: DON!! NÃO se perde entre turnos (refresh no
início do turno devolve tudo que foi anexado, + o ramp de +2) — o que
trava a carta-bomba não é "preciso guardar DON ao longo de várias
partidas", é gastar o DON DESTE MESMO turno em margem de ataque ANTES da
bomba competir pela vez, no turno exato em que ela já ficou pagável. Fix
mais simples que "reservar DON com antecedência": quando
`don_available >= plano['don_target']` (calculado por `compute_game_plan`,
já existente da fase 1) e a carta é o `win_con_code`, `_score_play_action`
soma `+600` — supera qualquer ataque normal observado (480-510) mas fica
ABAIXO do bônus de postura LETHAL em ataques (`+500` sobre base já alta,
facilmente 900+) — não deve nunca impedir fechar a partida quando dá pra
matar neste turno. Verificado numericamente: Five Elders com don=9 pontua
98 (não afordável), com don=10 pontua 705 (dispara o bônus).

Validado com `smoke_test.py` 100% e `smoke_test_broad.py` 40/40 sem
exceção após cada fix, isolado.

**Estado emocional do usuário (registrar pra próxima sessão não repetir o
erro de tom):** o dia inteiro foi gasto nesse ciclo comparação→achado→fix→
teste→achado novo, e o usuário expressou frustração explícita ("estamos o
dia inteiro nisso e não estou vendo melhoras, mesmo mandando log de como
se jogar o bot continua tomando péssimas decisões") depois do 3º log
seguido mostrando problema. Isso é justo — cada fix individual foi real e
validado, mas a percepção de progresso pro usuário depende do jogo AO VIVO
melhorar, não só do smoke test passar. Não prometer "resolvido" sem
partida real confirmando.

### Operacional
Python (`decision_engine.py`, `sim_bridge.py`, `server.py`). Logs salvos
no banco: `Imu-B_x_Marshall.D.Teach-BY_2026-07-10T23.19.23`,
`Imu-B_x_Marshall.D.Teach-BY_2026-07-10T23.38.05`.

---

## 2026-07-10 (119) - Claude

### 2 fixes reais (desconto de counter em play, resolve_optional_effect sempre recusando custo só-DON) + decisão de arquitetura: "GamePlan" pré-partida (NÃO IMPLEMENTADO AINDA — ler antes de reabrir isso do zero)

Terceira partida real do bot jogando Imu contra o usuário de Teach
(`2026-07-10T21.41.10.log` e `2026-07-10T22.32.09.log`, ambos salvos no
banco). 2 achados novos, 1 decisão de arquitetura grande registrada aqui
pra não se perder entre sessões.

**1) Desconto de counter em `_score_play_action`.** `avaliar_carta` dá
bônus de valor pra carta com `counter>0` (pensado pra contexto "vale
manter na mão"), mas `_score_play_action` usava esse valor como BASE sem
descontar — ou seja, jogar uma carta com counter alto (Doc Q counter=2000
poder=0, Baby 5 counter=2000) herdava o bônus e pontuava artificialmente
alto pra ir pro campo, esvaziando a mão de counters. Achado real: 2x Doc Q
+ 1x Baby 5 jogados em 2 turnos, bot terminou sem NENHUM counter na mão.
Fix: desconto simétrico do mesmo valor em `_score_play_action` quando
`card.counter>0` (`decision_engine.py`, logo após `base = engine.avaliar_carta(card)`).

**2) `resolve_optional_effect` sempre recusava custo só de `rest_don`.**
A versão anterior (achado de sessão passada) só entrava no bloco de
decisão se o custo tivesse tipo "sacrifício" (`_SACRIFICE_COST_TYPES`) —
custo SÓ `rest_don` (ex: "...Never Existed..." OP13-098, `[Main] You may
rest 1 DON: KO até 1 Stage do oponente custo≤7`) caía no fallback final e
SEMPRE recusava, mesmo com alvo válido e efeito bom. Sem custo real
descontado, o estado não muda quando recusa — a MESMA ativação de score
alto era reoferecida a cada `/decide` seguinte, travando o turno inteiro
em loop (achado via log real: 4 propostas idênticas seguidas, turno
terminou sem jogar a única carta que sobrava na mão, mesmo com 3 DON
livres). `execute()` (simulador interno) chama `_worth_paying_optional_costs`
incondicionalmente pra `on_play`/`main`, sem filtrar por tipo de custo —
o filtro em `resolve_optional_effect` era outra divergência real dos dois
motores. Fix: removido o filtro (`sim_bridge.py`).

Validado com `smoke_test.py` 100% e `smoke_test_broad.py` 40/40 sem
exceção após cada fix, isolado.

**3) Decisão de arquitetura (aprovada pelo usuário, ainda NÃO
implementada nesta sessão — próxima sessão deve continuar daqui, não
redesenhar do zero):** o usuário observou que o bot joga sem noção do
"plano de jogo" do deck — ex: Imu tem o combo Five Elders (custo 10,
reanima até 5 do trash) como bomba, e 5 personagens Celestial Dragons com
`passive: {conditions: {trash_gte: 7}}` (imunidade a remoção). Hoje o
engine só pontua ganho IMEDIATO por turno, sem nenhum alvo de médio prazo
("chegar a 7 no trash", "proteger a bomba até ter 10 DON").

Proposta acordada — um `GamePlan` calculado 1x no início da partida
(varre `card_effects_db.json` do próprio deck, SEM parser novo, os dados
já existem):
- `trash_target`: maior `trash_gte` encontrado em `conditions` de
  qualquer carta do deck (ex: 7 pro Imu). Genérico — funciona pra
  qualquer deck com esse padrão, não hardcode pro Imu.
- `win_con_card`: carta com maior bônus de `play_from_trash`/maior swing
  já identificada pelo scoring existente (`_score_activate_main` já tem
  a lógica de valor de reanimação — reaproveitar, não duplicar).
- `don_target`: custo do `win_con_card`.
- (fase 2, NÃO fazer agora): postura defensiva geral baseada em
  razão de blockers/counters no deck até bater `don_target`.

**Escopo combinado com o usuário pra primeira versão** (não fazer o
`don_target`/postura defensiva ainda): só `trash_target` + proteção do
`win_con_card`. Pontos de plugue já identificados (ainda sem código):
- Custo `trash_char_or_hand` do líder Imu (`_pay_costs`,
  `decision_engine.py` ~linha 2464): bônus pra trashar personagem quando
  `len(self.me.trash) < plan.trash_target`.
- `_trash_value`: proteger `win_con_card` na mão até
  `don_available >= plan.don_target` (parecido com o bônus de carta
  cara custo≥7 que já existe ali, mas ligado explicitamente ao win-con
  identificado, não só ao custo bruto).

Log-mining de partidas humanas foi descartado como fonte PRIMÁRIA (dados
estruturais do `card_effects_db.json` já bastam e generalizam pra
qualquer deck); logs humanos continuam servindo só pra validar/tunar
pesos depois, como já é feito hoje.

### Operacional
Python (`decision_engine.py`, `sim_bridge.py`). Logs salvos no banco:
`Marshall.D.Teach-BY_x_Imu-B_2026-07-10T21.41.10`,
`Imu-B_x_Marshall.D.Teach-BY_2026-07-10T22.32.09`,
`Eustass.Captain.Kid-Y_x_Kuzan-B_2026-07-10T22.05.14` (partida avulsa
não relacionada, salva a pedido do usuário).

---

## 2026-07-10 (118) - Claude

### 3 fixes reais de "agressividade" + conclusão: o gargalo virou balanceamento de deck, não mais bug de decisão

Segundo log real do bot jogando Teach (`2026-07-10T17.00.33.log`, salvo no
banco). Usuário reportou: turno com Laffitte+Fullalead+ataque não completados
(Fullalead na mão duplicado, DON sobrando), Catarina Devon atacando sem
ninguém pra copiar poder, e o padrão recorrente "desce carta barata, carta de
peso fica na mão o jogo inteiro". Investigação levou a 3 fixes confirmados:

**1) `_rest_activates_effect` cego a alvo** — mesma família do achado de
sessões anteriores (viabilidade). Qualquer carta com `[When Attacking]`
"valia atacar mesmo sem chance de passar" (regra de pressão), SEM checar se
o efeito tinha material/alvo. Catarina Devon ("select 1 personagem do
oponente, copie o poder") atacava a 3000 contra um líder de 5000 quando o
oponente não tinha NENHUM personagem em campo — sem chance e sem benefício
nenhum. Fix: novo branch em `_step_is_viable` pra `source: selected_opp_character`
+ `_rest_activates_effect` agora chama `_step_is_viable` de verdade em vez
de confiar só na presença da chave `when_attacking`. Mesmo padrão afeta
Mr.2 Bon Kurei (`EB01-061`).

**2) `don_needed_for_attack` sem `don_livre` no simulador interno — achado
via simulação, não log.** Rodei 60 partidas Teach vs Imu motor-contra-motor
(decks reais, `Barba Negra BY.deck` x `Imu.deck`) pra medir "agressividade"
com número, não impressão: **winrate do Teach = 4/60 (6.7%)**, dano médio
2.67 causado vs 4.88 sofrido. Rastreei uma partida verbose passo a passo:
o líder do Teach anexava DON em excesso numa única declaração de ataque
(ex: 9 DON de uma vez, poder final 14000 quando só ~8000 já garantia
passar) — MUITO além do necessário, sem ganho nenhum (1 ataque = 1 dano de
vida, não importa o excedente), e isso ZERAVA o DON que sobraria pra jogar
Catarina Devon e outras cartas no MESMO turno. Causa raiz: essa conta de
"DON ocioso do plano" (quanto sobra depois das jogadas que o Turn Planner
ainda quer fazer) só existia no caminho AO VIVO (`sim_bridge.don_for_attack`)
— o simulador interno (`_attach_don_for_attack`) chamava
`don_needed_for_attack` sem `don_livre`, tratando TODO don_available como
ocioso. Fix: extraído pra `OPTCGMatch._don_livre_for_plan`, fonte única
usada pelos dois caminhos (eliminou uma duplicação real de "dois motores").
Também removi o teto fixo de 2000 na margem de counter (`opp_counter_potential()`
sem cap) que mascarava parte do sintoma sem resolver a causa.

**3) Achado #3 rebalanceado** (ver bloco anterior) já estava aplicado nesta
rodada de testes.

**Resultado honesto**: os 3 fixes são reais e válidos (cada um confirmado
isoladamente, com teste de integração direto antes de qualquer smoke test),
mas NENHUM moveu o winrate Teach-vs-Imu — ficou em 3-4/60 (~5-7%) em TODAS
as rodadas de teste, antes e depois de cada fix. Rodei um espelho Teach vs
Teach (30 partidas) pra descartar "o motor joga mal o Teach" como causa:
deu quase 50/50 (16-14) com dano parecido dos dois lados (3.9 vs 3.7) —
bem mais alto que qualquer coisa que o Teach conseguiu contra o Imu.
**Conclusão**: o motor pilota o Teach razoavelmente bem contra um
adversário igual; o desempenho ruim contra o Imu especificamente é
desbalanceamento real de deck/matchup (o combo Stage→Five Elders→
reanimação do Imu, turbinado pelos fixes de sessões anteriores, é
simplesmente mais forte que esse Teach nesse confronto), não mais um bug
de decisão do motor. Registrado aqui pra não reabrir essa investigação do
zero numa sessão futura sem essa conclusão.

Validado com `smoke_test.py` 100% e `smoke_test_broad.py` 40/40 sem
exceção após CADA fix, isolado.

### Log persistente do `engine_server` (novo)

`BOT/engine_server/server.py` agora duplica TUDO que passa por `print()`
(aqui e em `sim_bridge.py`, mesmo processo/stdout) pra um arquivo em
`BOT/engine_server/logs/session_<timestamp>.log`, criado sozinho toda vez
que o server sobe — sem precisar depender do usuário deixar o terminal
aberto (scrollback tem limite, janela fecha). Antes, quando o bot parava
de agir no meio de um turno (achado do Fullalead/turno 3 do log anterior),
não tinha como investigar isso só pelo combat log — só o console do
server mostra os `[ENG]`/`[DEF]`/`[PLAY]` de cada chamada de
`/decide`/`/defense`. Pasta `BOT/engine_server/logs/` no `.gitignore`
(diagnóstico efêmero, não é o banco de combat logs).

**Correção no ato de testar** (mesmo bloco, achado ao ligar o server de
verdade): `_TeeStream` não implementava `isatty()` — o uvicorn chama
`sys.stdout.isatty()` ao configurar o log e quebrava a inicialização
inteira (`AttributeError`). Corrigido (`isatty()` repassa pro stream
original + `__getattr__` genérico pra qualquer outro atributo de arquivo
que uvicorn/logging perguntem). Testado ao vivo: server sobe limpo,
`/health` responde.

### Operacional
Python (`decision_engine.py`, `sim_bridge.py`, `server.py`) +
documentação (`BOT/README.md`, `.gitignore`). Log salvo no banco:
`Marshall.D.Teach-BY_x_Imu-B_2026-07-10T17.00.33`.

---

## 2026-07-10 (117) - Claude

### Primeira partida real do bot jogando Teach: 3 achados, o principal explica a "baixa agressividade"

Log `2026-07-10T13.35.57.log` — primeira vez que o bot jogou Teach-BY contra o
usuário jogando Imu-B (papéis invertidos da sessão anterior). Usuário reportou
3 observações; usuário venceu sem sofrer dano.

**1) Baby 5 / Teach-10 turno 6-7 — não era bug.** Conferido: DON disponível
(~4) tornava o Teach-10 (custo 10) literalmente impagável ali; Baby 5 (custo
4) era a única jogada real. O setup anterior (Marshall D. Teach `OP16-119`
colocando Baby 5 no topo da vida, buscando o gatilho "líder multicolor: compre
2") foi jogada correta do bot — só não disparou por variância (vida não foi
revelada em ataque depois).

**2) Trashar Shiryu no redirect do líder — escolha correta, mas achei bug
separado.** `_trash_value` já protegia Black Vortex mais que Shiryu (231 vs
130) entre as opções válidas. Mas nem o parser nem o engine aplicavam o
filtro "**com** [Trigger]" do custo do líder Teach ("trash 1 card with a
[Trigger] from your hand") — tratavam como "trash qualquer carta da mão".
Achado em mais 8 cartas com o mesmo padrão de texto (`OP03-105`, `OP03-115`,
`OP04-105`, `OP08-106`, `OP09-062`, `OP16-117`, `PRB02-017`, `ST29-014`).
Fix em 3 pontos: parser (`gerar_effects_db.py`, tag `has_trigger` no custo),
`_pay_costs` (filtra a mão por `has_trigger` antes de escolher o que
trashar), `resolve_reaction` em `sim_bridge.py` (estimava custo/guard de mão
pequena olhando a mão INTEIRA, não só as cartas elegíveis).

**3) Baixa agressividade (0 dano causado o jogo inteiro) — achado principal,
NÃO era desbalanceamento de peso.** Testei o cenário exato do jogo (ataque
5000 vs 5000 empatado): matar St. Marcus Mars pontuava 180 vs atacar o líder
Imu pontuando só 100. Rastreando a origem do 180, achei a causa raiz: `Card.
has_blocker` (e o mesmo padrão em `has_rush`/`has_double_attack`/`has_banish`/
`has_unblockable`) ficava permanentemente `True` pra qualquer carta cujo
texto contivesse "gains [Blocker]" em QUALQUER LUGAR do texto — inclusive
dentro de uma condição nunca satisfeita. Marcus Mars ("**se** você tem 7+
cartas na lixeira, ... ganha [Blocker]") contava como blocker desde o turno 1
com a lixeira vazia, inflando `score_attack_target` (+60 de bônus
"tem_blocker") pro jogo inteiro, não só quando a condição batia de verdade.

Fix: nova heurística `_leading_keyword()` em `decision_engine.py` —
`parse_card_effects_basic` só marca a keyword como incondicional se ela
aparece entre os tags NO INÍCIO do texto (convenção do jogo: keywords
incondicionais sempre vêm coladas no começo, ex: "[Blocker] (After your
opponent declares...)"). Validado contra 9-11 cartas condicionais conhecidas
(`OP02-050`, `OP11-046`, `OP11-058`, `OP12-063`, `OP15-013`, `OP15-119`,
`OP16-005`, `PRB02-014`, `ST23-001`, `OP13-091`, `OP06-010` — todas
corretamente NÃO detectadas como incondicionais) e uma amostra de blockers
de verdade (todas corretamente detectadas). **Cuidado**: NÃO aplicar essa
heurística a `has_trigger` — `[Trigger]` segue convenção OPOSTA (sempre no
FINAL do texto); confirmado numericamente antes de aplicar (só 42/475 cartas
com `[Trigger]` teriam o tag "no início" — quase todas quebrariam).

Com o fix isolado, o mesmo cenário de teste virou 75×100 (líder vence sozinho)
— **não foi necessário tocar no peso de `score_attack_target`**. Recomendado
testar de novo só com esse fix antes de considerar qualquer ajuste de peso,
pra isolar causa e efeito.

Validado com `smoke_test.py` 100% e `smoke_test_broad.py` 40/40 sem exceção
após CADA fix (isolado), mais um teste de integração direto reproduzindo o
cenário exato do jogo (antes/depois do fix).

### Operacional
Python (`decision_engine.py`, `sim_bridge.py`) + parser (`gerar_effects_db.py`,
`card_effects_db.json`, `parser_snapshot.json` via `gerar_dbs.py` +
`snapshot_parser.py`). Log salvo no banco:
`Marshall.D.Teach-BY_x_Imu-B_2026-07-10T13.35.57`.

---

## 2026-07-10 (116) - Claude

### Prep pro teste do bot jogando Teach: parser de OP09-093 + implementação completa de `negate_effect`

Usuário pediu pra analisar os 7 logs onde ele jogou de Teach (lado `[Opponent]`
dos jogos Imu-bot desta sessão) e ir atrás dos padrões de jogo antes de testar
o bot jogando Teach pela primeira vez. Redirect, empilhar counters e o
investimento pesado (ZEHAHAHAHA) já estavam cobertos — sem mudança. Achado
novo: `OP09-093` (Marshall D. Teach personagem, aparece nas 7 partidas) tinha
duas lacunas.

**1) Parser perdia 2 das 3 partes do texto**: `[Activate: Main]` do
OP09-093 é "nega o efeito do líder oponente. Depois, nega o efeito de 1
personagem E trava o ataque dele até o fim do próximo turno do oponente" —
`parse_negate_effect` (`gerar_effects_db.py`) só capturava a cláusula do
personagem (via `re.search`, que só acha a 1ª ocorrência, e o padrão
genérico não reconhecia "...opponent's Leader" sozinho, só "leader or
character"). Fix: novo padrão composto que detecta as DUAS cláusulas
("Leader... Then... Character... cannot attack") e emite os 3 steps
corretos. Cuidado: a 1ª versão do fix capturava demais — confundia com o
idioma "Leader or Character cards" (escolha de UM alvo) usado em 3 outras
cartas (`OP09-097`, `OP09-098`, `OP16-115`), duplicando a cláusula.
Corrigido com negative lookahead `(?!\s*or\s*character)`. `diff_parser.py`
confirmou PERDEU=0 e só o OP09-093 mudou de conteúdo.

**2) `negate_effect` não tinha handler de execução nem categoria de score**
— a action já aparecia em 4 cartas parseadas mas era no-op silencioso
(mesmo padrão do achado do `play_from_trash`/Five Elders, blocos
anteriores). Implementado ponta a ponta:
- Campo novo `effects_negated_until: str` no `Card` (mesmo padrão de
  `cannot_attack_until`), resetado no `refresh_phase` do dono e incluído
  no `__deepcopy__` customizado (campo faltando aqui = perdido em todo
  clone do Turn Planner, silenciosamente).
- Gate no topo de `EffectExecutor.execute()`: carta negada não dispara
  NENHUM trigger futuro (não desfaz on_play já resolvido).
- Handler em `_execute_step` pra `negate_effect` (targets: `opp_leader`,
  `opp_character`, `opp_leader_or_character` — escolhe entre líder/melhor
  personagem por `board_value()`).
- Viabilidade em `_step_is_viable` (líder sempre viável; personagem precisa
  de alvo elegível).
- Categoria própria em `_score_activate_main` (bucket de remoção/controle,
  base=100 — antes caía no fallback genérico de 60). Também adicionei
  `lock_opp_character_attack` nesse bucket (mesma lacuna, mesma carta).

Validado com teste de integração direto (OP09-093 nega o líder Imu +
nega/trava um personagem; confirmado que o líder Imu negado não consegue
mais usar a própria habilidade depois) e `smoke_test.py`/`smoke_test_broad.py`
(100% / 40-40) rodados após CADA mudança (parser e engine, separadamente).

### Operacional
Parser (`gerar_effects_db.py`, `card_effects_db.json`,
`card_analysis_db.json`, `parser_snapshot.json` via `gerar_dbs.py` +
`snapshot_parser.py`) + engine (`decision_engine.py`). Nenhum log novo
salvo neste bloco.

---

## 2026-07-09 (115) - Claude

### Comparação humano-vs-bot jogando Imu revela por que o bot quase nunca monta o combo Stage→Five Elders→reanimação

Usuário pediu pra comparar TODOS os logs em que ele jogou de Imu (2 no banco,
`Nami-BY_x_Imu-B_2026-07-01` e `Imu-B_x_Monkey.D.Luffy-BP_2026-07-01`, ~17
turnos cada) contra os 7 logs desta sessão do bot jogando Imu. Matchups
diferentes (Teach vs Nami/Luffy), mas dá pra comparar tendência estrutural.

**Diferença gritante**: o usuário NUNCA trashou Five Elders (`OP13-082`,
custo 10, a carta-motor do combo "reanima até 5 personagens do trash") em
nenhuma das 2 partidas — o bot trashou em 4 das 7 (3 delas era a ÚNICA cópia
na mão, não uma duplicata descartável). O usuário jogou Five Elders de graça
via Empty Throne 3-4x POR PARTIDA (quase todo turno, montando um exército
reanimado); o bot só em 2 de 7 partidas, e a reanimação em si só disparou
UMA vez em todas as 7.

**Causa raiz**: `order_target_candidates` (`sim_bridge.py`) resolve qualquer
prompt AO VIVO de "selecione 1 carta pra descartar" (a tela real do jogo,
tipo a do print que o usuário mandou). A zona `own_hand` usava
`engine.avaliar_carta(card)` (heurística fraca — acha caro/injogável AGORA
= ruim) — EXCETO no caso especial de redirect do líder Teach (achado
07/07), que já usava `EffectExecutor._trash_value(card)` (heurística rica,
protege carta de custo≥7 mesmo sem DON pra jogar agora). O caso GERAL
(custo do próprio líder Imu, "trash 1 da mão" da Saint Shalria, etc) ainda
caía na versão fraca. `avaliar_carta(Five Elders)=45` vs
`avaliar_carta(Saturn)=115` — o motor escolhia sacrificar a peça mais
valiosa do deck pra comprar 1 carta genérica, logo no turno 1.

**Fix**: zona `own_hand` agora usa `_trash_value` SEMPRE, não só no caso do
redirect — mesma régua pra qualquer prompt de descarte. Testado
reproduzindo a mão exata de um log real (Five Elders + 2x Ju Peter + Saturn
+ Never Existed): antes do fix a ordem colocava Five Elders primeiro
(descarte); depois, Saturn vai primeiro e Five Elders fica protegido —
igual ao que o usuário sempre fez. `smoke_test.py` 100%,
`smoke_test_broad.py` 40/40 sem exceção.

### Operacional
Só Python (`sim_bridge.py`). Nenhum log novo salvo neste bloco (comparação
usou logs já existentes no banco).

---

## 2026-07-09 (114) - Claude

### Achado de "dois motores" real (não só suspeita) + gate mecânico novo pra pegar isso automaticamente

A partir do log `19.25.50.log` (Imu vs Teach, salvo no banco), 3 novas observações do
usuário levaram a mais 2 achados e uma pergunta de fundo importante.

**1) Guarda do custo `trash_char_or_hand` protegia personagem "morto"**: no custo do
líder Imu (trashar 1 Celestial Dragon do campo OU 1 carta da mão), uma guarda evitava
trashar qualquer personagem "ativo" (não restado/just_played), forçando trash da mão
em vez dele — mas não checava se esse personagem tinha ALGUM motivo real pra continuar
ativo. Saint Shalria (0 de poder, efeito só no On Play, já gasto) era protegida do
mesmo jeito que um atacante de verdade, custando carta da mão à toa. Fix: a guarda só
protege personagens com poder > 0 (`decision_engine.py`, `_pay_costs`).

**2) "Dois motores" de verdade (não suspeita — achado confirmado)**: rastreei o caso
do usuário "Marcus Mars jogado sem alvo pro K.O., mas custou 1 carta da mão mesmo
assim" até `resolve_optional_effect` em `sim_bridge.py` — o caminho AO VIVO ("you may
trash 1: K.O...") tinha sua PRÓPRIA régua (`avaliar_carta(pior) <= 60`), completamente
separada da que o simulador interno usa (`EffectExecutor.execute()`, que só paga custo
se `_step_is_viable` confirma que o benefício tem alvo). Pior: o caminho ao vivo nem
sabia qual carta estava perguntando (sem `actorCode`), então não tinha como checar
viabilidade nem que quisesse. Reproduzi exatamente o caso (Shiryu custo 6 em campo,
Mars pede alvo custo≤5): confirmado que o custo era pago sem alvo válido.

**O usuário apontou a causa raiz certa**: isso é a violação exata que a regra "sem
dois motores" existe pra evitar ([[feedback_dois_motores]]). Fix de verdade (não só
band-aid): extraí a decisão "vale pagar esse custo opcional?" pra um ÚNICO método,
`EffectExecutor._worth_paying_optional_costs` (`decision_engine.py`) — chamado tanto
por `execute()` (simulador interno, antes de `_pay_costs`, só pra triggers on_play/main)
quanto por `resolve_optional_effect()` (sim_bridge.py, caminho ao vivo, que agora é só
um wrapper fino sem heurística própria). C# (`BotDriver.cs`) passa a mandar o
`actorCode` (`BotExecutor.ActorCode`, já existia pra outro uso) pra fase
"optional"/"reaction" do `/defense`, resolvendo o "não sabia qual carta perguntou".
Validado: os dois caminhos concordam exatamente no mesmo cenário de teste (nenhum dos
dois paga sem alvo). `smoke_test.py` 100%, `smoke_test_broad.py` 40/40 sem exceção.

**3) Pergunta de fundo do usuário**: "estamos balanceando só o Imu ou melhorando o
motor?" — resposta honesta: o código é genérico (nenhum fix tem `if code ==`), mas
testamos só com Imu vs Teach, então todo bug novo aparece "vestido" de Imu. O caso
Mjosgard (deploy de um vanilla 0-poder quando valia mais como counter de 2000 na mão)
é provavelmente mais um sintoma do achado #3 já conhecido (`avaliar_carta` favorecendo
custo baixo, ainda pendente — ver blocos anteriores). Ainda não atacado diretamente.

### Gate mecânico novo: `scripts/hooks/pre-commit` agora BLOQUEIA, não só lembra

O hook antigo só imprimia as regras de memória (lembrete passivo — não impediu o achado
#2 acima, que só foi pego porque o usuário notou jogando, não porque a IA releu o
lembrete e conectou os pontos). Adicionei um gate mecânico: se o diff staged de
`sim_bridge.py`/`server.py` adiciona, num mesmo HUNK do diff, uma comparação numérica
literal (`<= 60`, `== 5`, etc — assinatura de limiar de decisão) SEM nenhuma chamada
visível a um ponto de entrada conhecido do engine (`DecisionEngine`, `EffectExecutor`,
`avaliar_carta`, etc — lista mantida no topo do hook), bloqueia o commit com instruções
claras (delegar pro engine, ou `--no-verify` se for falso positivo confirmado).
Checagem é por HUNK (`git diff -U0`), não por arquivo inteiro — testei e confirmei que
checar "o arquivo inteiro toca o engine em algum lugar" sempre passa (todo arquivo do
bridge importa `DecisionEngine` por definição), então não pegava nada na prática.
Testado nos dois sentidos: uma função fake reimplementando uma régua própria foi
bloqueada; o diff real desta sessão (que delega corretamente) passou limpo.
Reinstalar em cada clone/máquina: `sh scripts/setup-git-hooks.sh` (já cobre o
pre-commit novo, não só o pre-push).

### Operacional
Python (`decision_engine.py`, `sim_bridge.py`) + C# (`BotDriver.cs`, recompilado) +
hook novo (`scripts/hooks/pre-commit`, precisa reinstalar via setup-git-hooks.sh nas
outras máquinas/clones). Log salvo no banco:
`Imu-B_x_Marshall.D.Teach-BY_2026-07-09T19.25.50`.

---

## 2026-07-09 (113) - Claude

### 4 achados estruturais em sequência, a partir de 3 logs reais novos (16.39/17.52/18.39 — todos salvos no banco, Imu vs Teach)

Usuário continuou testando ao vivo enquanto eu investigava em paralelo.
Cada observação virou um achado genérico (custo duplicado, viés de
recursão de deck, gate de defesa sem noção de valor, custo fantasma),
não um patch pontual — seguindo a mesma diretriz de sessões anteriores.

**1) Mão cheia + DON parado + líder do Imu sem ciclar carta**
(`_score_activate_main`, `decision_engine.py`): a habilidade do líder
(trashar 1 da mão/campo → comprar 1) era penalizada DUAS VEZES pelo
mesmo custo — uma vez pelo cap `min(base, 45)` (efeito não é vantagem
líquida de carta) e de novo subtraindo `perda*0.3` da carta trashada.
Empilhados, o score ia facilmente pra negativo mesmo sem nada melhor
pra fazer, e o loop do turno (`main_phase`) para assim que a MELHOR ação
disponível é negativa — terminando o turno com mão cheia e DON parado.
Fix: pula a subtração de `perda` quando é um ciclo card-neutro
(`draw_count <= trash_count`), já que o cap já precifica esse trade-off.

**2) Bot trashando evento `[Counter]` em vez de personagem reanimável**
(`_trash_value`, `EffectExecutor`): ao escolher qual carta trashar pro
custo da habilidade do líder, o motor não tinha noção de que o Five
Elders (`OP13-082`) em campo reanima cópias de 5000 de poder do próprio
trash — protegia eventos counter (bônus fixo) e ignorava que perder um
Elder de 5000 é temporário. Fix genérico: qualquer personagem na mão que
bata o filtro de um `play_from_trash` disponível (campo ou mão, condições
checadas) tem o valor de trash descontado em 60% — a própria carta de 10
custo (que não bate `power_eq=5000`) continua protegida. Também suavizei
a proteção de eventos `[Counter]` com retorno decrescente conforme a
quantidade já na mão (1 counter protege forte, 3+ protege pouco).

**3) Bot gastou 2 eventos counter pra salvar 1 personagem de baixo valor**
(`should_use_counter`/`select_counter_cards`): o gate de "vale counterizar"
usava a MESMA lógica de vida do jogador tanto pra defender o líder quanto
pra defender um personagem qualquer — sem comparar o valor do personagem
defendido com o valor gasto. Fix: quando o alvo do ataque é um
personagem (via `defender_uid`), a decisão passa a comparar
`char_value_score(defendido)` vs soma de `avaliar_carta` das cartas de
counter gastas — só counteriza se compensar. **Achado no caminho**: o
C# (`BotDriver.cs`) nunca mandava o `defenderId` pra fase "counter" do
`/defense` (só pra "reaction"/"optional") — sem isso o fix em Python não
teria efeito nenhum ao vivo. Corrigido e recompilado (build OK).

**4) Líder quase não ataca mesmo com DON parado sem outro uso possível**
(`_activate_main_value`): essa função desconta o score de QUALQUER ataque
(líder ou personagem) assumindo que atacar sempre custa a chance de usar
o `[Activate: Main]` no mesmo turno — verdade só quando a habilidade
exige a carta ATIVA (custo `rest_self`). A habilidade do líder Imu não
tem `rest_self` (atacar e comprar carta são independentes), mas o
desconto de -70 era aplicado do mesmo jeito, e somado ao desconto de
risco de trigger derrubava o ataque do líder pra negativo — o turno
terminava sem atacar e com DON sem nenhum outro uso possível. Fix:
só desconta quando a habilidade tem custo `rest_self` de fato. Testado
isolado: cenário antes tinha 0 ações candidatas (só a inválida, negativa);
depois, atacar com o líder pontua +72.4 e é escolhido.

**Ressalva do usuário (registrar para não regredir)**: passar o turno com
DON ativo/parado É válido quando esse DON está reservado pra usar uma
habilidade ou counter no turno do OPONENTE (`_don_reserve_for_defense`
já existe pra isso) — o problema era especificamente DON sem NENHUM uso
possível, nem agora nem reservado pra depois.

Validado: `smoke_test.py` 100% e `smoke_test_broad.py` (40/40 sem
exceção) rodados após CADA um dos 4 fixes, isolado.

### Operacional
Python (`decision_engine.py`, `sim_bridge.py`) + C# (`BotDriver.cs`,
já recompilado). Logs salvos no banco:
`Imu-B_x_Marshall.D.Teach-BY_2026-07-09T{17.52.14,18.39.46}` (o de
17.42.21 já tinha sido salvo antes da investigação começar).

---

## 2026-07-09 (112) - Claude

### Achado ESTRUTURAL importante: `_score_activate_main` tem taxonomia FIXA de "tipos de efeito bons" — qualquer ação fora da lista cai num fallback de 60 pontos, subestimando efeitos poderosos

Usuário reportou (3ª partida, `2026-07-09T17.22.22.log`, salva no banco):
bot ficou sem mão de novo, "quase não usou" o Stage, jogou Five Elders
(`OP13-082`, custo 10 — o personagem do combo "trash seu campo inteiro,
reanima até 5 diferentes Five Elders da lixeira") e nunca ativou o efeito
dele. **E fez uma observação crítica**: isso é o MESMO tipo de problema
já visto antes com Teach não usando o Stage — "estamos resolvendo
situações pontuais de cada líder e jogada, precisamos fazer o bot pensar
melhor". Levei isso a sério em vez de investigar só a carta reportada.

**Achado**: `_score_activate_main` (`decision_engine.py`, `OPTCGMatch`)
pontua a ação de ativar um Activate:Main por uma lista FIXA de categorias
reconhecidas — `draw/busca=170`, `play_card=110+`, `remoção/controle=100`,
`don-ramp=90`, **e qualquer ação que não bate com nenhuma delas cai no
`else: base = 60`**, a MESMA pontuação genérica de qualquer efeito
irrelevante. Empty Throne usa `play_card` (categoria reconhecida — por
isso FUNCIONA, o "quase não usou" foi só o ramp natural de DON até ter
7 disponível, não bug). Five Elders usa `trash_character` +
`play_from_trash` — **nenhuma das duas está na lista** — caía no
fallback de 60, e ainda levava a penalidade de custo (`trash_from_hand`,
`rest_don`), ficando com score baixo/negativo, sempre perdendo pra
qualquer outra ação (inclusive "não fazer nada"). Confirmado: **8 cartas
diferentes no banco inteiro** têm `play_from_trash` no Activate:Main
(`Blueno, Lily Carnation, Thriller Bark, Kuzan, Coribou, Five Elders,
Kouzuki Momonosuke, Yamato`) — todas sofriam da mesma subestimação, não
só o Five Elders.

**Fix genérico**: nova categoria reconhecida `play_from_trash` em
`_score_activate_main` — soma o valor real dos alvos elegíveis na
lixeira (respeitando `filter_type`/`distinct_names`/`count` do step,
mesma lógica que `play_card` já usa pra mão) em vez de um número fixo.
Quando o custo inclui "trash TODOS os seus personagens" (`trash_character`
com `count>=99`), desconta o valor do board atual sendo sacrificado —
senão a IA acharia que ganhou os reanimados de graça em vez de ter
TROCADO o campo. Validado: cenário da partida real (board quase vazio,
lixeira cheia de alvos, vida crítica) score subiu de ~45 pra **175**
(compete de verdade com outras ações); cenário sem alvos na lixeira
mantém score baixo/negativo (-55, não força ativação sem motivo).
`smoke_test.py` 100%, `smoke_test_broad.py` rodando.

**Sobre "ficou sem mão de novo"**: não investigado a fundo nesta rodada —
é provavelmente o mesmo achado #3 de ontem (`avaliar_carta` favorecendo
custo baixo), ainda pendente de rebalanceamento dedicado. Não é um bug
novo, é o mesmo already-flagged issue se manifestando de novo.

### Reflexão sobre o padrão do dia (registrado, não é ação)
O usuário tem razão que hoje foram VÁRIOS achados parecendo pontuais
(Sanjuan Wolf, Kuma, Teach OP09-093, contadores de evento, busca do Imu,
agora Five Elders) — mas cada um foi corrigido generalizando a CAUSA
RAIZ (contexto de ataque vazando, viés de DON em escolhas sem custo,
taxonomia incompleta de categorias de efeito), não a carta específica,
e cada fix comprovadamente afeta múltiplas cartas do banco (confirmado
numericamente em quase todos). Ainda assim, o padrão de "descobrir uma
categoria inteira faltando toda vez que uma carta nova aparece" sugere
que a arquitetura de scoring (`avaliar_carta`/`_score_activate_main`/
`_score_play_action`) tem mais buracos de taxonomia por aí — vale
considerar, numa sessão futura, uma auditoria preventiva de TODAS as
`action` que aparecem em `card_effects_db.json` vs. quais são
reconhecidas por essas 3 funções de score, em vez de esperar a próxima
partida real expor a próxima categoria faltando.

### Operacional
Só Python (`decision_engine.py`). Server reiniciado. Logs salvos no
banco (`Imu-B_x_Marshall.D.Teach-BY_2026-07-09T17.22.22`).

---

## 2026-07-09 (111) - Claude

### 3 fixes reais no motor: counters de evento, gate de "vale counterizar", viés de custo em buscas grátis

Usuário reportou 2 observações jogando de Teach contra o bot de Imu, que
viraram 3 fixes (a terceira era a mesma causa em dois pontos):

**(a) Counters de EVENTO nunca eram usados na defesa ao vivo.**
`select_counter_cards` (`sim_bridge.py`, usada de verdade pelo
`/defense counter`) só somava o stat impresso de Counter em personagens
(`c.counter > 0`) — nunca considerava eventos com bloco `[Counter]` no
texto (ex: `OP13-098` "...Never Existed...", Imu: "+4000 power during
this battle"). O motor JÁ TINHA toda a lógica de avaliação desses eventos
(`EffectExecutor.try_counter_event_power`/`_check_conditions`/
`_counter_event_cost_payable`), só nunca era chamada nesse caminho ao
vivo — só pelo simulador interno. Fix: `select_counter_cards` agora monta
um pool combinado (personagens + eventos elegíveis, em modo SÓ LEITURA,
sem mutar estado — a mutação real acontece no jogo quando o C# descarta a
carta) e ordena tudo pela mesma régua.

**(b) O GATE que decide "vale a pena counterizar" também só via o stat
impresso.** `should_use_counter` (que `select_counter_cards` chama ANTES
de sequer montar a lista) usava `self.me.counter_in_hand()` — mesma
lacuna, sem awareness de eventos. Corrigido: `should_use_counter` ganhou
parâmetro opcional `counter_avail` (default preserva comportamento
antigo pra todo resto do código); `select_counter_cards` monta o pool
combinado PRIMEIRO e passa o total real pro gate.

**(c) Viés de custo/DON aplicado em escolhas SEM custo — achado maior,
generaliza pra qualquer efeito de busca no jogo, não só o Imu.** Usuário
relatou que o bot escolhe sempre Mary Geoise (custo 1) em vez de Empty
Throne (custo 7) na busca gratuita de stage do líder Imu ("at the start
of the game, play up to 1 [Mary Geoise] type Stage card from your deck"
— achado extra: o parser nunca capturou essa ability específica do Imu,
mas não precisou consertar isso — ver abaixo). Causa: `order_target_
candidates`, zona `top_deck`, ordena por `avaliar_carta()` — que pesa
"dá pra pagar AGORA" (+40/+20/-15 conforme DON disponível). Numa busca
GRÁTIS (sem custo, comparando 2 opções que já estão technically "de
graça"), esse peso não faz sentido nenhum — e com 0 DON em campo no
início do jogo, SEMPRE favorece a carta mais barata, não a melhor. Fix:
`engine_busca` — clone raso de `DecisionEngine` com `don_available`
artificialmente alto (99), usado só pra zona `top_deck`, zera o
bônus/penalidade de jogabilidade sem perder o resto do sinal de
`avaliar_carta` (poder, keywords, on-KO etc). Validado numericamente:
Mary Geoise 20→40 vs Empty Throne 0→55 (don=0 vs don=99) — a ordem
inverte corretamente. **Não precisou tocar no parser do Imu**: a zona
`top_deck` já cobre a busca dele igual cobre qualquer outro efeito de
busca do jogo — o fix é genérico por construção, não por-carta.

Validado: testes diretos dos 3 cenários (evento cobre ataque / evento não
cobre / condição do evento falha; Mary Geoise vs Empty Throne com DON
neutro) todos bateram com o esperado. `smoke_test.py` 100%,
`smoke_test_broad.py` rodando (aguardando confirmação).

### Pendência (não bloqueante)
Parser ainda não captura a ability única do Imu ("at the start of the
game, play up to 1 [X] type card from your deck") — não é usada por
nenhuma OUTRA carta no banco hoje (`grep` confirmou), então baixa
prioridade; registrado só pra completude futura caso o simulador interno
(`OPTCGMatch`) precise dela algum dia (o fix de hoje resolve o caminho AO
VIVO sem precisar dela).

### Operacional
Só Python (`sim_bridge.py`, `decision_engine.py`, `server.py`) — sem
mudança de C#/DLL, sem `gerar_dbs`. Server reiniciado com os 3 fixes.

---

## 2026-07-09 (110) - Claude

### Banco de logs: obrigação nova no CLAUDE.md + 2 bugs pré-existentes corrigidos na ferramenta

Usuário perguntou se eu estava salvando os combat logs que ele manda — não
estava (só existiam na conversa; o update do simulador do bloco 109 apagou
os originais). Ele revelou que **já existe um banco de logs de verdade**
(`scriptis_da_ia/logs/{raw,parsed,decks}/` + `index.json`, ferramenta
`parse_combat_log.py --add-to-db`, documentado em `TODO.md` seção
`📊 BANCO DE LOGS`) — eu não sabia e tinha criado `BOT/test_logs/` por
conta própria no bloco anterior (desfeito agora, `rm -rf`).

**Obrigação nova escrita no `CLAUDE.md`** (seção "Banco de logs de
partidas reais — OBRIGATÓRIO salvar"): toda vez que o usuário mandar um
combat log, a sessão (Claude ou Codex) tem que rodar
`python parse_combat_log.py <log> --add-to-db` antes de considerar a
tarefa terminada. Vale pra Codex também — `CLAUDE.md` é lido por qualquer
sessão nova, é o lugar certo pra regras assim.

**2 bugs pré-existentes achados e corrigidos ao tentar usar a ferramenta
pela primeira vez** (`parse_combat_log.py`): `index.json` tem 2 schemas
diferentes (10 entradas antigas do lote "autosaved_log" usam
`original_file`/`total_turns`, sem `id`/`date`/`turns`; as demais 30+ usam
o schema novo com `id`/`date`/`turns`). `add_to_db()` e `list_db()`
assumiam TODAS as entradas tinham o schema novo (`e['id']`, `e['date']`,
`e['turns']`) — `KeyError` em ambas ao rodar contra o banco real. Fix:
`.get()` com fallback (`e.get('id')`, `e.get('date') or
e.get('original_file','')[:10]`, `e.get('turns', e.get('total_turns'))`)
nos dois lugares. Validado: `--add-to-db` das 2 partidas do bloco 109
funcionou (`Imu-B_x_Marshall.D.Teach-BY_2026-07-09T16.07.36` e `...16.12.30`,
42 entradas no índice agora), `--list-db` lista as 42 sem quebrar,
`smoke_test.py` 100% (não testa esse arquivo diretamente, mas confirma
nada mais quebrou).

### Operacional
Nada de C#/DLL nesta rodada — só Python (`parse_combat_log.py`) +
`CLAUDE.md`. Server não precisa reiniciar. Considerar se `BOT/vendor/`
(zip do BepInEx, ~622KB) deve ir pro git ou pro `.gitignore` — ainda não
decidido.

---

## 2026-07-09 (109) - Claude

### Sessão nova: bot jogando de IMU (usuário jogando de Teach) — reinstalação do BepInEx + 2 fixes reais

**Contexto novo**: usuário propôs inverter os papéis pra testar generalização —
ele joga de Teach, o bot joga de Imu (carrega os decks trocados nos slots do
SoloVSelf; o bot so controla `Lps_Players[0]`, é agnóstico de qual deck tá lá).

**0. Simulador atualizou e apagou a pasta BepInEx inteira** (reinstall/update
do jogo às 15:44 de hoje zerou `E:\Games\...\Builds_Windows\BepInEx\`).
Sem backup local do instalador. Baixei a versão oficial certa (BepInEx
5.4.23.2, Windows x64 — confirmada pela versão que já aparecia no
`LogOutput.log` antigo) do GitHub oficial, salvei em `BOT/vendor/` (não
depende de internet nas próximas vezes), e criei **`BOT/setup_bepinex.ps1`**
+ **`BOT/setup_bepinex.bat`** (duplo-clique): reinstala o BepInEx se
ausente, recompila o plugin, copia pro `BepInEx/plugins/`. Rodar sempre que
o jogo atualizar de novo e apagar a pasta (fechar o jogo antes — o
`winhttp.dll` do BepInEx fica travado com o processo aberto).

**Combat logs agora sendo salvos**: usuário perguntou se eu estava
guardando os logs que ele manda — não estava (só existiam na conversa, e
o update do simulador apagou os originais). Criei `BOT/test_logs/` e
copiei os 2 logs desta sessão (`2026-07-09T16.07.36.log`,
`2026-07-09T16.12.30.log`) pra lá. Adotar esse hábito daqui pra frente.

**1. Bartholomew Kuma dando DON restado pra si mesmo em vez do líder —
MESMA causa raiz do Sanjuan Wolf (bloco 108), ainda não generalizada.**
`OP16-093`: "[On Play] ... give up to 1 rested DON!! to your Leader or 1
of your Characters" — o parser nunca captura `target` pra `give_don`
(só decide `give_don` vs `give_don_opp`, sem granularidade lider/personagem
dentro do próprio lado), então esse padrão não caía em NENHUMA das
detecções `actor_*` de `order_target_candidates` — ficava no fallback
genérico de zona, e como o Kuma tinha acabado de entrar e era o único
personagem em campo, "ganhava" por eliminação. Fix: unifiquei
`actor_self_power_target` pra guardar `('set', valor)` (Sanjuan Wolf,
Devon etc — poder vira N fixo) OU `('delta', +1000*count)` (`give_don` —
cada DON soma 1000 permanente). Mesma checagem de sobrevivência do líder
nos dois casos; pro caso `delta` (onde o ganho é IGUAL em qualquer alvo,
não existe "quem se beneficia mais"), desempate novo: nunca prefere o
próprio ator se ele acabou de entrar em campo (`just_played`, sem Rush
não briga esse turno) — o líder, que nunca tem `just_played`, ganha por
padrão. Validado com teste direto + `smoke_test.py` 100% +
`smoke_test_broad.py` 40/40.

**2. Bot atacou com St. Topman Warcury travado pelo Teach OP09-093 do
usuário — bug REAL confirmado (não falso alarme de expiração natural),
causa raiz achada e corrigida no C#.** Contei os turnos no combat log:
o lock ("can't attack next turn") foi aplicado no turno do usuário, e o
Warcury atacou no EXATO turno seguinte (dentro da janela do lock) — não é
coincidência de timing. Investigando o decompilado: `StartAttack()`
(chamado pelo bot via reflection em `BotExecutor.cs`) **não valida** se o
personagem pode atacar — só checa `iConfusion` (mecânica diferente). A
checagem real (`CardCantAttack()`, que confere `bCantAttack`/`bCantRest`/
travas V3/`CantAttack` de card action) só roda na camada de CLIQUE do
jogo (`FindPossibleCardActions`), que decide se ele SEQUER oferece o
personagem como atacante clicável — nosso bot pula essa camada
inteiramente (seta `go_PendingChoice` direto e chama `StartAttack()`).
**Fix de verdade, não workaround**: `GameStateDto.cs` ganhou o campo
`cantAttack`; `GameStateBuilder.cs` chama `CardCantAttack()` via reflection
(mesmo método que o jogo usa) ao montar o DTO de cada personagem;
`server.py` seta `card.cannot_attack_until = 'live_lock'` quando
`cantAttack=true` — reaproveitando o filtro que **já existia** em
`_generate_and_score_actions` (`not c.cannot_attack_until`), nunca
alimentado por dados reais do jogo ao vivo antes disso (só por simulação
interna). Isso é geral: cobre QUALQUER efeito de trava de ataque
(`bCantAttack`, travas V3, `CantAttack` de card action), não só o Teach
especificamente. Validado: teste direto ponta-a-ponta (DTO→Card→
`cannot_attack_until`), `smoke_test.py` 100%, `smoke_test_broad.py` 40/40.

### Operacional
DLL recompilada com o fix do `cantAttack` e copiada automaticamente pro
`BepInEx/plugins/` (confirmado: mesmo tamanho/timestamp nos dois lugares).
**O jogo estava ABERTO com a DLL antiga carregada em memória — precisa
fechar e reabrir pra pegar esse fix.** Server reiniciado com os 2 fixes
Python (`give_don` + `cantAttack` plumbing). `BOT/vendor/` (zip do
BepInEx) e `BOT/test_logs/` são novos, considerar se devem entrar no git
(binário de terceiro + logs de teste — talvez `.gitignore` seja melhor
pro zip, mas os logs valem a pena versionar).

---

## 2026-07-08 (108) - Claude

### Fix do Sanjuan Wolf (bloco 107) NÃO tinha pegado de verdade — causa raiz real era outra + achado grosso na função central de avaliação de carta

Usuário testou de novo (`2026-07-08T02.20.14.log`) e reportou 3 pontos.

**1. Fix do Sanjuan Wolf do bloco 107 confirmado FALHO — causa raiz real
achada e corrigida.** Mesmo comportamento de novo (Pizarro em vez do
líder). Investigando o `LogOutput.log` desta partida: o estado do jogo no
momento da escolha é `Life_ActivateTrigger` — NÃO está na lista de estados
`Attack_WaitOnBlocker/BeforeBlocker/WaitOnCounters` que o C#
(`BotDriver.cs HandlePendingAction`) usa pra calcular `atkPower`. Ou seja
`attacker_power` chega **sempre 0** nesse cenário (qualquer trigger de
vida), e minha regra de "líder sobrevive ao boost" (bloco 107) dependia
justamente de `attacker_power > 0` — nunca tinha chance de disparar.
Fix real: a regra agora usa o ESTADO DO TABULEIRO do oponente diretamente
(`opp_gs.field_chars`/`opp_gs.leader` ainda ativos = ameaça real), mesma
conta de `maior_por_vir` já usada em `resolve_reaction`, em vez de
depender do parâmetro `attacker_power` que só o C# preenche em 3 estados
específicos de ataque. Isso é mais robusto E mais geral: funciona
independente de QUAL estado do jogo a escolha de alvo aparece. Validado
com 2 cenários diretos (ameaça ativa suficiente pra matar sem boost mas
não com boost → prioriza líder; sem ameaça ativa → volta pro "quem
beneficia mais"). `smoke_test.py` 100%, `smoke_test_broad.py` 40/40.

**Lição reforçada**: o fix de ontem (107) tinha teste direto que PASSOU,
mas o teste testava um cenário sintético (`attacker_power=6000`) que eu
inventei sem confirmar que o C# realmente preenche esse valor pra ESSE
tipo de trigger. Teste passando != cenário real coberto — só o log real
do usuário revelou isso. Reforça [[feedback-fixes-globais-nao-pontuais]].

**2. Black Hole vs Shiryu no custo do redirect — observação válida, NÃO
corrigida.** Usuário sugeriu trashar 1 Shiryu (`OP16-108`, tinha 3-4
cópias na mão) em vez do Black Hole (`OP09-098`) como custo do redirect do
Teach, porque Shiryu tem sinergia recursiva (`[On Play] trash 1 carta:
recupera até 1 Blackbeard Pirates custo≤6 da lixeira pra vida face-up` —
uma cópia trashada podia ser recuperada por OUTRA cópia jogada depois).
`_trash_value`/`avaliar_carta` não sabem raciocinar sobre "essa carta é
recuperável porque tenho outra cópia sinérgica na mão" — é um tipo de
avaliação bem mais sofisticado (contar cópias, cross-referenciar
`play_from_trash`/`add_from_trash_to_life` na mão) que não tentei
implementar às pressas. Registrado pra sessão futura com mais tempo
dedicado — não é um bug simples, é uma lacuna de sofisticação real.

**3. "Bot desce carta de custo baixo e evita as bombas do deck" — achado
GRANDE, raiz confirmada, NÃO corrigido (escopo grande demais pra essa
sessão).** Testei diretamente `avaliar_carta` (função central, usada em
`_trash_value`, `_score_play_action`, `choose_to_trash` — dezenas de
pontos de decisão) com cartas reais do banco, DON e vida realistas:

```
OP16-102 Avalo Pizarro (custo=1, poder=2000):  avaliar_carta=125
OP16-109 Doc Q          (custo=1, poder=0):     avaliar_carta=120
OP16-108 Shiryu         (custo=6, poder=8000):  avaliar_carta=140
OP09-093 Teach          (custo=10,poder=12000,Blocker): avaliar_carta=100
```

Confirma o padrão relatado: o Teach de custo 10 (uma "bomba" de verdade —
12000 de poder, Blocker, Activate:Main forte) pontua MENOS que um
personagem de custo 1. Causa: `card.power / 1000 * 5` (escala de poder)
é fraco (+60 pro Teach de 12000) comparado à pilha de bônus fixos que
cartas baratas de sinergia acumulam (draw +25, busca +30, on-KO +35,
trigger +10, jogabilidade imediata +40) — o "tamanho"/investimento de
DON da carta não é recompensado proporcionalmente. Essa é a MESMA função
usada em dezenas de lugares do engine (não só "jogar carta") — mudar os
pesos sem validação ampla é arriscado. **Decisão consciente: não mexi
nisso agora** (sessão já muito longa, mudança de escopo grande, função
central demais pra alterar sem tempo de validar direito) — registrado
aqui com números concretos pra próxima sessão focar nisso com atenção
dedicada, não como patch rápido no fim de uma sessão de 6+ horas.

### Operacional
Server reiniciado com o fix real do Sanjuan Wolf. Pendências claras pra
próxima sessão, em ordem de impacto: (a) rebalancear `avaliar_carta`
pra recompensar poder/custo proporcionalmente — achado #3, maior
impacto; (b) ensinar `_trash_value` a reconhecer sinergia recursiva
(cópias recuperáveis) — achado #2, mais raro/específico; (c) gap do
parser de `OP09-093` (só captura 1 de 3 efeitos, bloco 107) ainda
pendente.

---

## 2026-07-08 (107) - Claude

### Achado GRANDE: "contexto de ataque" vazando pra QUALQUER escolha de alvo — causa raiz comum dos 2 reports desta partida (Sanjuan Wolf + Teach OP09-093)

Usuário mandou combat log de partida nova (`2026-07-08T01.18.57.log`) com
2 observações, e pediu explicitamente pra não resolver só pra carta
específica. As duas investigações levaram à MESMA causa raiz em
`order_target_candidates` (`scriptis_da_ia/optcg_engine/sim_bridge.py`).

**Causa raiz**: a variável `attacker_power > 0` era usada como proxy pra
"estamos resolvendo um redirect" — mas na verdade só significa "estamos
numa janela de ataque" (`Attack_WaitOnBlocker/BeforeBlocker/WaitOnCounters`
no C#). QUALQUER escolha de alvo que aconteça durante essa janela —
inclusive de uma ability completamente diferente, sem nenhuma relação com
redirecionar ataque — reaproveitava as heurísticas de redirect
(`own_hand`/`own_board`/`own_leader` pontuados por `_trash_value`/
`redirect_option_value`/`life_redirect_cost`). Corrigido: nova flag
`actor_is_redirect` (mesmo padrão de `actor_copia_poder`/
`actor_debuff_swing` — inspeciona os steps do `actor_code` procurando
`redirect_attack_target`) agora GATE-KEEPER de todo `attacker_power > 0`
nessas zonas. Só entra na lógica de redirect quem realmente TEM essa
ability.

**1. Sanjuan Wolf redirecionado pro Pizarro em vez do líder** — a ability
real (`OP16-106`, on-KO: "up to 1 of your Leader or Character's power
becomes 7000") não é redirect nenhum, é um auto-buff que o usuário viu
disparar durante uma janela de ataque (life trigger). Sem o gate acima,
ela caía nas heurísticas de redirect por acidente. Fix adicional (não só
o gate): nova detecção genérica `actor_self_power_target` (mesmo padrão —
qualquer carta com `set_base_power`/`buff_power` target=
`leader_or_own_character`) que:
  - por padrão prefere quem tem MENOR poder atual (fixar um valor alto
    beneficia mais quem estava mais fraco — maior delta);
  - EXCETO quando o líder está sob ataque AGORA e o boost fixo é
    suficiente pra ele SOBREVIVER um golpe que hoje não sobreviveria —
    aí o líder ganha prioridade máxima (sobreviver > qualquer delta de
    poder solto). Isso bate com a intuição do usuário nesse caso
    específico, sem hardcode pro Sanjuan Wolf — qualquer carta futura com
    esse padrão textual ("gains X or Y" trocado por "power becomes N")
    herda o comportamento.

**2. Teach OP09-093 — usuário "teve que escolher os alvos"** — log do
plugin (`LogOutput.log`) confirma que o bot NÃO travou: ativou a
habilidade (`activate: OP09-093`) e ficou tentando alvo por alvo, só que
a ORDEM começava pela própria mão/campo (candidatos genéricos de zona
`own_hand`/`own_board`, prioridade estrutural 1/3) antes de chegar nos
candidatos válidos do oponente (`opp_board`, prioridade 4) — 15+ cliques
inválidos (~0,8s cada, ~12s+) até acertar, tempo suficiente pro usuário
perder a paciência e clicar primeiro. A ability real (`OP09-093`: "negate
the effect of up to 1 of your opponent's Leader/Character") só tem alvo
do lado do OPONENTE — nenhuma zona `own_*` é válida nunca. Fix genérico:
nova flag `actor_opp_only` — se TODOS os `target` declarados nos steps do
`actor_code` começam com `opp` (qualquer carta, não só essa), todas as
zonas `own_*` caem pra prioridade mínima (9), garantindo que candidatos
do oponente sempre vêm primeiro.

**Gap secundário achado, não corrigido**: `card_effects_db.json` de
`OP09-093` só capturou 1 dos 3 efeitos do texto real (falta "negate
opponent's Leader" e "can't attack until end of next turn" — só
"negate opp Character" foi parseado). Não afeta o bug corrigido acima
(que dependia só do `target` do step existente), mas o bot provavelmente
subestima o valor de ativar essa ability na hora de decidir. Registrado
pra próxima sessão avaliar o parser dessa carta.

Validado: 3 cenários de teste direto (Sanjuan Wolf com líder sobrevivendo
ao boost / sem ataque em andamento / boost insuficiente) todos bateram
com o esperado; teste direto do Teach OP09-093 confirmou candidato do
oponente vindo primeiro. `smoke_test.py` 100% (múltiplas rodadas ao longo
do trabalho). Mudança é 100% Python puro (`sim_bridge.py`) — não precisou
`gerar_dbs.py`, só reiniciar o server.

### Operacional
Ambiente com bastante flakiness de processos em background nesta sessão
(vários `smoke_test_broad.py` ficaram presos/mudos sem razão aparente,
não relacionado ao código do projeto) — rodei o smoke test amplo várias
vezes até confirmar 40/40 limpo. Server será reiniciado com todos os
fixes de hoje (blocos 105+106+107) antes do usuário testar de novo.

---

## 2026-07-08 (106) - Claude

### Nova partida real: 2 reports do usuário viraram "não é bug" (Nusjuro condicional, trash vazio) + achado de verdade (Catarina Devon OP09-084) + log de mão fina

Usuário mandou combat log de outra partida (`2026-07-08T00.37.06.log`) com
2 reports:

**1. "Nusjuro atacou e não consegui usar meu when attacking, o bot já saiu
trashando carta antes"** — investigado e é **comportamento correto, não
bug**. Texto real do Nusjuro (`OP13-080`): "[When Attacking] **If you have
10 or more cards in your trash**, give up to 1 opponent Character -2000
power". No ataque reportado (turno 3), a lixeira do atacante tinha
**9 cartas** (contado direto no combat log) — condição não bate, o jogo
não oferece a habilidade, não tem nada pra "roubar" via timing. No 2º
ataque do mesmo Nusjuro (lixeira com 11), o debuff disparou normalmente,
confirmando que a condição É respeitada nos dois casos.

**2. "BOT não sabe ativar/escolher o efeito da Catarina Devon"** —
usuário citou o código errado (`OP09-081`, que na verdade é uma variante
do líder Teach, efeito totalmente diferente). Card real (foto confirmada
pelo usuário): **`OP09-084`** — "[Activate: Main][Once Per Turn] If your
Leader has the Blackbeard Pirates type, this Character gains **[Double
Attack], [Banish] or [Blocker]** until the end of your opponent's next
turn." **Achado real aqui, e é geral (não pontual)**: o parser
(`gerar_effects_db.py`) tem uma regex pra "gains [A], [B] or [C]" (janela
de lista compartilhada) que appenda cada keyword como STEP INCONDICIONAL
SEPARADO — ou seja, o motor achava que a carta ganhava as 3 keywords DE
GRAÇA simultaneamente, em vez de ser uma ESCOLHA de 1. Isso silenciosamente
"funcionava" (dava tudo de graça) só que como um efeito enorme e errado —
não bate com o sintoma relatado ("bot não sabe escolher"), mas de qualquer
forma estava semanticamente errado e merecia fix. Fix: quando a lista
compartilhada contém `' or '`, vira `{'_choice': [[gain_a],[gain_b],[gain_c]]}`
em vez de steps paralelos — mesmo formato usado por 19+ cartas com "Choose
one: • ...". Só 1 carta no banco inteiro tinha esse padrão específico
(`OP09-084`, a `_p1` parallel não conta separado), mas o fix é genérico
(detecta pelo padrão textual "or" na lista, não hardcoded pro código da
carta) — qualquer carta futura com esse texto ganha o comportamento
certo automaticamente. `EffectExecutor.execute()` já resolve `choice`
genericamente pra QUALQUER trigger (`activate_main` incluso, confirmado
lendo o código) via `_resolve_choice`, que escolhe a opção viável de
maior peso heurístico — sem peso específico pra
double_attack/banish/blocker (todas caem no default=1), então empate
sempre escolhe a primeira da lista (`gain_blocker`, pela ordem que
construí) — não é estratégico, mas é MUITO melhor que "ganha as 3 de
graça" ou "nunca ativa". Validado: `diff_parser.py` GANHOU=0 PERDEU=0
MUDOU=1, `smoke_test.py` 100%, `smoke_test_broad.py` 40/40 (2x, antes e
depois do log de mão fina).

**Achado à parte, NÃO investigado a fundo (duration)**: o texto real diz
"until the end of your opponent's next turn" — esse padrão de duração
específico NÃO é reconhecido em lugar nenhum do código (`grep` zero
ocorrências). O keyword-grant provavelmente vira permanente em vez de
expirar no tempo certo. Pré-existente, não piorado por este fix, mas
registrado aqui pra próxima sessão avaliar.

### 3. Usuário reportou (sem log ainda, observação de partida ao vivo): bot
jogando excessivas cartas de custo 1-2 (algumas com Counter alto, tipo
+2000) até ficar sem carta na mão, facilitando o ataque do oponente.
Investigado: **já existe uma proteção** (`_generate_and_score_actions`,
achado de uma partida real de 04/07 documentado no próprio código) que
penaliza jogar quando `len(hand) <= 3`, mas essa penalidade é POR
CONTAGEM, não pesa se a carta específica tem Counter alto (mais valiosa
guardada pra defesa). Decidi **não ajustar a heurística às cegas** —
mesmo espírito das auditorias de hoje (não repetir o erro que já cometi
uma vez nesta sessão, de quase declarar bug sem prova sólida; aqui seria o
inverso, ajustar peso sem prova de que o ajuste certo). Em vez disso,
adicionei log `[PLAY]` em `sim_bridge.py choose_action()` (só dispara
quando a mão já está com ≤3 cartas ANTES da jogada, pra não poluir turnos
normais): mostra código/custo/counter da carta jogada e o score. Vai
aparecer no stdout do server na próxima partida — dá pra auditar com
números reais se a régua de preservação de mão está ou não protegendo
carta de counter alto o suficiente, em vez de eu ficar comparando na mão.

### Operacional
Server reiniciado com todos os fixes de hoje (bloco 105 + este). Matei
vários processos `smoke_test_broad.py` que ficaram presos em background
por causa do harness (não sei a causa raiz, mas não tem relação com o
código do projeto). `card_effects_db.json`/`card_analysis_db.json`
regenerados e ressincronizados (`gerar_dbs.py`) com o fix da Catarina
Devon. `C:/Users/arthu/AppData/Local/Temp/optcg_server.log` continua
sendo o arquivo de log persistente do server — ler depois da próxima
partida (`grep "\[REACTION\]\|\[PLAY\]"`).

---

## 2026-07-07 (105) - Claude

### Tentativa de auditar as outras 6 recusas offline — abandonada por falta de confiabilidade; log de diagnóstico ao vivo adicionado no lugar

Usuário pediu pra auditar as outras 6 recusas (não-letais) da mesma
partida do bloco 104 antes de testar de novo. Reconstruí manualmente o
estado (mão/campo/vida) de cada golpe usando os codes reais do Combat Log
e chamei `resolve_reaction`/`redirect_option_value`/`life_redirect_cost`
de verdade (script em `C:/Users/arthu/AppData/Local/Temp/audit_teach.py`,
não versionado). Pra 2 dos golpes reconstruídos (vida 4 e vida 3), o
resultado deu `True` — ou seja, minha reconstrução dizia que o engine
DEVERIA ter aceitado, contrariando o que o log real mostrou (`Cancel`
nos 2 casos).

**Não tratei isso como bug confirmado.** Investiguei a causa mais provável
da divergência: `_trash_value` (usada pra `custo_carta`) tem um bônus de
até `60 + custo*6` se a carta for jogável AGORA (`custo <=
self.me.don_available`) — e meus `GameState` sintéticos tinham
`don_available=0` (default), o que SUBESTIMA `custo_carta` artificialmente
baixo comparado à partida real (onde o bot tinha DON de verdade
disponível). Reconstruir `don_available` exato por turno a partir só do
Combat Log é frágil (o log não expõe isso de forma direta e não auditei
com confiança suficiente pra apontar um segundo bug). **Decisão: não
declarar bug sem certeza — isso violaria a mesma lição que guardei na
memória ontem** (fix "genérico" não é sinônimo de "completo"; aqui o
risco seria o oposto, declarar bug sem prova sólida).

**Em vez de continuar adivinhando offline, adicionei log de diagnóstico
DIRETO no `resolve_reaction`** (`scriptis_da_ia/optcg_engine/
sim_bridge.py`): toda chamada agora imprime uma linha `[REACTION] atk=...
def=... life=... don_disp=... -> True/False (motivo)` no stdout do server,
com os números REAIS (`custo_carta`, `salva`, `opcoes`, `ganho`,
`maior_por_vir`) usados na decisão — em vez de eu reconstruir o estado de
memória, a próxima partida real vai gerar os números de fato. Validado:
`smoke_test.py` 100%, `smoke_test_broad.py` 40/40 (print não quebra nada).

### Operacional
Server reiniciado (matei o processo antigo na porta 8765) redirecionando
stdout/stderr pra um arquivo persistente:
`C:/Users/arthu/AppData/Local/Temp/optcg_server.log` — os processos
`run_in_background` anteriores morreram sozinhos entre turnos desta sessão
(motivo não investigado, pode ser o processo pai da sessão encerrando);
usar esse arquivo de log é mais confiável pra checar depois do teste do
usuário do que depender do rastreamento do harness. Health check OK.

### Pendente
Próxima sessão (ou eu mesmo, se o usuário testar ainda nesta sessão): ler
`C:/Users/arthu/AppData/Local/Temp/optcg_server.log` (grep `[REACTION]`)
depois da próxima partida real e comparar os números de verdade contra o
que o bot decidiu — aí sim dá pra confirmar ou descartar bug nas recusas
não-letais. O fix do golpe letal (vida 0, bloco 104) continua válido e
já está no server rodando.

---

## 2026-07-07 (104) - Claude

### Partida real pós-fix #103: detecção funciona, mas `resolve_reaction` recusava até o golpe que perdeu o jogo — bug de heurística achado e corrigido

Usuário jogou uma partida completa com a DLL do bloco 103 e mandou o
Combat Log (`2026-07-07T23.46.53.log`) + feedback: "achei que deu uma
melhorada, mas precisamos melhorar algumas coisas ainda". Cruzando o
Combat Log com o `LogOutput.log` do plugin (mesma sessão):

**Boa notícia**: a detecção funciona. `[Bot] custo opcional sem tela
dedicada (reacao): ...` apareceu 8 vezes ao longo da partida — o bot não
trashou mais carta às cegas em todo ataque (bug do bloco 102/103
efetivamente resolvido).

**Problema novo**: em TODAS as 8 vezes o engine respondeu `Cancel` —
inclusive na última, que foi o golpe que **terminou o jogo** (5º acerto no
líder Teach; os primeiros 4 levaram a vida de 4 a 0, e por regra do OPTCG
tomar dano com vida 0 = derrota imediata). Confirmado via
`grep "hit for 1 damage"` no Combat Log (5 ocorrências) + a última entrada
`[Bot] custo opcional... Cancel` no `LogOutput.log` bate exatamente com
esse 5º golpe (`actor=OP13-080`, St. Ethanbaron V. Nusjuro, mesmo atacante
do Combat Log).

**Causa raiz** (`resolve_reaction`, `scriptis_da_ia/optcg_engine/
sim_bridge.py`): `life_redirect_cost(life_count)` trata vida=0 igual a
vida=1 (cai no mesmo teto de 90, `dict.get(0, 90.0)`), na MESMA régua
numérica usada pra comparar contra o custo de sacrificar uma carta
(`custo_carta`, tipicamente 40-90+ pra mão boa). Conceitualmente errado:
com vida 0, esse golpe não é "perder mais 1 vida" — é perder a PARTIDA
INTEIRA, que não é comparável a nenhum valor de carta. Fix: bypass
explícito — quando o ataque é no líder (`defender_char is None`) e
`my_life == 0`, redireciona sempre que existir QUALQUER alvo legal (mesmo
que vá morrer sem on-KO bom), sem passar pela conta normal de
ganho/custo nem pela guarda de "segurar a reação pro ataque maior" (não
existe "turno que vem" se perder agora).

Validado com teste direto (`Card`/`GameState` construídos à mão, 3
cenários: vida=0 com alvo → `True`; vida=4 mesmo cenário → comportamento
normal preservado; vida=0 sem nenhum personagem no campo → `False`,
correto, sem alvo legal pra redirecionar). `smoke_test.py` 100%,
`smoke_test_broad.py` 40/40. Engine puro (Python), sem mudança de parser
— não precisou `gerar_dbs`. Server reiniciado (matei o processo antigo na
porta 8765 e subi de novo) pra carregar o fix.

### Pendente
Usuário mencionou "algumas coisas" no plural — só achei e confirmei UM bug
concreto (o de vida 0) com evidência forte (log real). As outras 7 recusas
da partida não foram auditadas uma a uma (podem estar corretas — mão
disponível vs. ameaça pequena, ou podem esconder outro problema de tunagem
não tão óbvio quanto o de vida 0). Não fiz DLL nova nesta rodada (mudança
foi só Python/server) — não precisa reabrir o jogo, só o server já
reiniciado é suficiente. Próximo passo: jogar mais uma partida e ver se o
Teach agora redireciona corretamente perto de vida 0; se sobrar tempo,
auditar as outras recusas dessa mesma partida uma a uma pra achar o que
mais o usuário quis dizer com "algumas coisas".

---

## 2026-07-07 (103) - Claude

### Causa raiz real do Teach achada e corrigida (fix #1 do bloco 102 era necessário mas insuficiente) + gap do parser fechado

Usuário testou de novo (ataque com Saint Shalria) e confirmou que o Teach
continuava trashando toda vez, mesmo sem valer a pena. Log real
(`LogOutput.log`) confirmou: `downside=False` mesmo com o fix do heartbeat
ativo, no exato momento em que `actor=OP16-080` aparece com `aca=True
mine=True` — ou seja, essa ability específica **nunca** passa pela tela de
oferta dedicada (Cancel/UseOnPlay ou Cancel/UseV3OnPlay). Ela pula direto
pra seleção do alvo do custo ("Select 1 Cards to Trash", só com Cancel),
que é exatamente o que o print do usuário já tinha mostrado no bloco
anterior.

**Causa raiz confirmada no decompilado**: `SetupPendingActionTargets`
(V3) só monta a tela dedicada quando `actV3Step.details.ConfirmAction ==
true`. Pra essa habilidade do Teach esse flag não está setado — o
"aceitar/recusar" fica embutido na própria seleção do alvo do custo. Isso
significa que o fix #1 do bloco 102 (ler `UseOnPlay`/`UseV3OnPlay` na tela)
continua válido e necessário pra cartas que TÊM a tela dedicada, mas não
cobre esse padrão — precisava de um segundo sinal.

**Fix novo, também GERAL (não hardcode pro Teach)**: `ActV3Effect.TrashCard`
é o mesmo campo que o próprio jogo usa (`PopulateV3Choice`) pra montar o
botão "Select N Cards to Trash" — presente em QUALQUER carta com esse
padrão de custo, não só o Teach. `BotExecutor.IsOptionalHandTrashCost(gls)`
(novo, `BotExecutor.cs`) verifica: step atual é V3, marca `effect.TrashCard`,
e o botão `Cancel` está realmente disponível na tela (se não tem Cancel, o
custo é obrigatório — parte de uma ação já confirmada, não deve ser
perguntado). `BotDriver.cs` (`Update()`) agora, antes de deixar
`HandlePendingAction` escolher automaticamente um alvo, checa esse sinal na
1ª vez que a ação pendente aparece (`_downsideCheckedFor`, mesmo padrão de
`_pendingRef`) e pergunta pro engine via `resolve_reaction`/
`resolve_optional_effect` (extraído pro helper `ShouldUseOptionalCost`,
compartilhado com o branch da tela dedicada — elimina a duplicação que
existia antes). Se o engine recusar, cancela a ação em vez de trashar a
pior carta da mão automaticamente.

**Gap do parser também fechado** (`scriptis_da_ia/gerar_effects_db.py`):
o texto do redirect do Teach ("Change the target of **that** attack...")
não batia com a regex antiga (`'change the attack target' in t` — ordem de
palavras diferente da de Doflamingo OP14-060/"Oh Come My Way" EB01-038,
que usam "Change the **attack target**..."). Regex trocada por
`change the (?:attack target|target of (?:that|this) attack)` (cobre as
duas ordens) + filtro de tipo simplificado pra casar só `\{X\} type
character(s)` (em vez de tentar casar a frase inteira ao redor, que também
variava). Validado: `diff_parser.py` → GANHOU=0 PERDEU=0 MUDOU=1 (só
OP16-080), `card_effects_db.json` agora tem
`on_opp_attack: {steps: [redirect_attack_target filter_type=blackbeard
pirates], costs: [trash_from_hand count=1]}` pra ele (o campo `costs` veio
de um mecanismo do parser que já existia, só nunca disparava porque o
bloco inteiro ficava vazio antes). `smoke_test.py` 100%,
`smoke_test_broad.py` 40/40 depois do `gerar_dbs.py` + re-snapshot.
Esse gap não bloqueava o fix comportamental acima (`resolve_reaction`/
`order_target_candidates` já eram genéricos, não liam o banco pra esse
caso), mas deixava a `card_analysis_db.json` incompleta pra qualquer coisa
que dependa de conhecer essa ability (auditoria, front-end, etc.).

### Pendente pra confirmar
DLL recompilada de novo com o fix novo (`IsOptionalHandTrashCost` +
`ShouldUseOptionalCost`) e copiada pro `BepInEx\plugins\` — **precisa
fechar e reabrir o jogo** (a instância que estava rodando ainda tem a DLL
anterior, sem esse fix). Server Python reiniciado (matou a instância antiga
que não respondia mais a `/health` — pode ter caído sozinha entre as
sessões — e subiu de novo com `card_effects_db.json` atualizado). Depois de
reabrir o jogo: repetir o mesmo teste (atacar o Teach com Saint Shalria ou
qualquer outro atacante) e confirmar no log `[Bot] custo opcional sem tela
dedicada (reacao): USAR efeito / Cancel` aparecendo — e principalmente,
que o Teach **não trasha mais em todo ataque indiscriminadamente**.

---

## 2026-07-07 (102) - Claude

### Pendência 1 resolvida (fix GERAL, não hardcode do Teach) + pendência 2 (toggle de tecla)

Seguindo a ordem pedida pelo usuário no bloco 101.

**1. `IsOfferingDownside` (`BOT/OPTCGBotPlugin/BotExecutor.cs`) reescrito pra
ler os botões REAIS na tela em vez do campo interno `bOfferingDownside`.**
Causa raiz confirmada no decompilado
(`_referencias/simulador-oficial/dnspy-export/Assembly-CSharp/GameplayLogicScript.cs`):
`bOfferingDownside` só é setado em `StartUsingAction_DEPRECATEME` (linha
~30796), o sistema de ações **legado**. O sistema **V3** — usado pela
maioria das cartas novas, Teach incluso — resolve o mesmo diálogo
Cancel/Usar em `SetupPendingActionTargets` → branch `ConfirmAction` (linha
~30567-30580) e nunca toca esse campo. Ou seja, não era um bug específico
do Teach: **qualquer carta/líder com custo opcional portado pro V3** tinha
esse mesmo problema (o bot nunca perguntava pro engine, sempre usava a
ability "no escuro"). Os dois sistemas, porém, ativam os MESMOS botões de
UI (`ButtonChoiceType.UseOnPlay` no legado, `UseV3OnPlay` no V3) via
`AddChoice` — sinal público (`go_ChoiceButtonN` + `ChoiceButtonScript.myType`,
ambos `public`), igual ao que o jogador vê na tela. Fix: reaproveitado o
helper `OfferedButtons` que já existia no arquivo (usado por
`ConfirmPendingSelection`) — `IsOfferingDownside` agora verifica se algum
botão ofertado é `UseOnPlay` OU `UseV3OnPlay`, cobrindo os dois sistemas
pra qualquer carta. Reflection do campo antigo (`_fOfferingDownside`)
removida.

**2. Toggle de tecla Shift+B pra ligar/desligar o bot em tempo real**
(`BOT/OPTCGBotPlugin/BotDriver.cs`, `Update()`; documentado em
`BOT/README.md`). Campo `_botEnabled` (bool, default true) checado logo no
início do `Update()`, antes de qualquer leitura de estado do jogo — Shift
(esquerdo ou direito) segurado + `Input.GetKeyDown(KeyCode.B)` alterna e
loga `[Bot] ATIVADO/DESATIVADO (Shift+B)`; quando desativado, `Update()`
retorna imediatamente (nenhum side effect). Ao reativar, dá um cooldown de
1s antes de agir de novo (evita ação no mesmo frame que o usuário acabou de
mexer). Precisou adicionar referência nova no `.csproj`
(`UnityEngine.InputLegacyModule.dll`, já existe em
`OPTCGSim_Data/Managed/`) — `UnityEngine`/`UnityEngine.CoreModule` sozinhos
não expõem a classe `Input` nessa versão do Unity. (Primeira versão usava
F9 isolado; trocado pra Shift+B a pedido do usuário — tecla única sozinha
tinha mais chance de colidir com algum atalho do jogo/OS.)

Ambos os itens só têm testado até "compila limpo" (`dotnet build`, 0
erros) — **não testado em partida real ainda** (não é algo que dê pra
validar por script/smoke test, precisa rodar o jogo). Próxima sessão (ou
o usuário jogando manualmente) deve confirmar: (a) o log agora mostra
`[DEF] reaction`/`[DEF] optional` quando o Teach ou qualquer outra carta
V3 oferece o diálogo de custo opcional; (b) a tecla F9 liga/desliga o bot
sem quebrar nada.

### Ajustes ao vivo (mesma sessão, depois do primeiro teste do usuário)

1. **Tecla trocada de F9 pra Shift+B** (a pedido do usuário — F9 sozinha
   tinha mais chance de colidir com algum atalho do OS/jogo). Documentado em
   `BOT/README.md`.
2. **Bug achado no próprio toggle**: o heartbeat de diagnóstico (`[HB] ...
   downside=...`) só rodava quando `_botEnabled=true` — pausar com Shift+B
   também SILENCIAVA os logs que a gente precisa pra ver se `downside=True`
   aparece no momento certo (o motivo de existir o toggle). Corrigido:
   heartbeat agora roda sempre (adicionado campo `enabled=` na mensagem);
   só a execução de ações fica condicionada a `_botEnabled`.
3. **Achado novo**: a habilidade de redirect do Teach ("You may trash 1
   card with a [Trigger] from your hand: Change the target of that
   attack...") **não está no `card_effects_db.json`** — só o efeito de
   custo (`opp_turn: buff_cost`) foi parseado, o redirect ficou de fora.
   Gap do parser (`gerar_effects_db.py`), registrado aqui mas não
   investigado ainda — não deveria travar `resolve_reaction` (que é
   genérico e não lê o banco pra esse caso específico), mas fica pendente
   de confirmação.
4. **Print real do usuário** (Imu [OP13-079] atacando o líder Teach,
   turno 2) mostrou a tela **"Select 1 Cards to Trash" com só o botão
   Cancel** — sem um par Cancel/UseOnPlay separado antes. Isso sugere que
   essa habilidade específica pode pular a etapa de "oferta" inteiramente
   (o Cancel já embutido na própria seleção do alvo do custo), o que
   invalidaria parte da hipótese do fix #1 pra ESSE caso específico —
   ainda não confirmado ao vivo (o log carregado no momento do print era de
   sessão anterior à DLL nova, sem o fix do heartbeat). **Próximo passo
   assim que o usuário reabrir o jogo com a DLL nova**: reproduzir o mesmo
   cenário, pausar com Shift+B, e ler o `LogOutput.log` pra ver se
   `downside=` vira `True` nesse instante ou não.

### Operacional
DLL recompilada e copiada automaticamente pro
`E:\Games\OnePieceSimulador\Builds_Windows\BepInEx\plugins\` (o `.csproj`
já tem um target `CopyToPlugins` pós-build) — **precisa fechar e reabrir o
jogo** pra carregar a versão mais nova (a que tem o fix do heartbeat).
Server Python (porta 8765) foi religado nesta sessão
(`python BOT/engine_server/server.py`, rodando em background) — health
check OK (`{"status":"ok"}`).

---

## 2026-07-07 (101) - Claude

### Fix real do debuff_power no caminho AO VIVO + achado grande: `IsOfferingDownside` nunca detecta a ability do Teach

Mais uma partida real (5ª de hoje) auditada pelo usuário. 2 coisas importantes:

**1. Fix #6 do bloco 100 só valia pra simulação, não pro jogo real — corrigido agora.**
O usuário reportou de novo o Van Augur debuffando -3000 num personagem já
restado (dessa vez o St. Jaygarcia Saturn) em vez do líder (ainda ativo).
Investiguei e achei a causa raiz certa dessa vez: meu fix de ontem no
`_execute_step`/`debuff_power` (decision_engine.py) só é usado pela
simulação INTERNA do Turn Planner. A escolha de alvo AO VIVO (quando o
jogo de verdade pede via `/choose_target`) passa por
`order_target_candidates` (sim_bridge.py), que eu não tinha tocado pra
esse caso — a zona `opp_board` lá é genérica pra REMOÇÃO (maior valor,
sem olhar `rested`) e `opp_leader` cai num catch-all de prioridade baixa,
então o líder quase nunca competia. Fix: detecção do padrão de efeito
(`actor_debuff_swing`, igual ao `actor_copia_poder` que já existia pra
copy-power) — quando o ator tem um step `debuff_power`, `opp_board` e
`opp_leader` são tratados juntos, priorizando quem está ATIVO (não
restado) antes de olhar valor. Testado isolado (líder ativo bate
personagem restado) e validado (`smoke_test.py` 100%, `smoke_test_broad.py`
40/40). Commit `4155623`.

**2. `IsOfferingDownside` nunca retorna true pra ability do Teach — confirmado, não é mais suspeita.**
O usuário reportou (e confirmou visualmente, existe um botão real no jogo)
que o "trash 1 [Trigger]: redirecionar ataque" do Teach parece ter uma
escolha de aceitar/recusar. Mas em NENHUMA das 5 partidas de hoje o
server Python imprimiu `[DEF] reaction` nem `[DEF] optional` — e o
heartbeat do próprio plugin (`[HB] ... downside=...`, já existia no
código, imprime toda vez que o estado muda) **nunca** mostrou
`downside=True` em nenhum momento do LogOutput.log inteiro (rodei
`grep "downside=True"` no log completo — zero ocorrências). Ou seja: a
função `BotExecutor.IsOfferingDownside(gls)` (que lê o campo
`_fOfferingDownside` via reflection) está checando o campo ERRADO do
estado interno do jogo pra essa ability específica — o jogo mostra um
botão real (usuário confirmou visualmente), mas nosso código nunca detecta
essa janela de decisão, então a ability é usada sem nunca passar pelo
`resolve_reaction`/`resolve_optional_effect` do motor. Isso explica os
achados dos blocos 99-100 que pareciam "o fix não pegou" (self-redirect
sem efeito, redirect de ataque de 0 poder que já ia falhar sozinho,
trashando carta à toa) — não é bug de decisão no Python, é a ability
sendo forçada sem nunca perguntar pro motor se vale a pena.

### Pendências pra próxima sessão (usuário pediu explicitamente)
1. **Achar o campo certo no jogo pra detectar essa ability.** Próximo
   passo: procurar no `_referencias/simulador-oficial/dnspy-export/`
   (GameplayLogicScript.cs e o V3 action script específico do Teach) por
   qual state/flag realmente controla esse diálogo — `_fOfferingDownside`
   está descartado como candidato (confirmado errado agora). Pode ser um
   state diferente de `PlayerTurn_Action`/downside, ou um campo novo que
   ninguém tinha mapeado ainda.
2. **Criar um toggle (tecla de atalho) pra ligar/desligar o bot em tempo
   real**, sem precisar reiniciar o jogo nem trocar a DLL de lugar —
   usuário quer isso pra poder jogar manualmente e printar telas de
   decisão sem o plugin clicar automaticamente antes de dar tempo. Dá pra
   fazer em `BotDriver.cs` (`Update()`, ~linha 29): checar uma tecla via
   Unity `Input.GetKeyDown` no início do método, com um `bool _botEnabled`
   que dá `return` cedo quando false. `Plugin.cs`/`BotDriver.cs` já são
   `MonoBehaviour`/`BaseUnityPlugin` com acesso a `UnityEngine`, então
   `Input` já está disponível sem dependência nova.

### Operacional
Server (porta 8765) está DESLIGADO no fim desta sessão (parado a pedido
do usuário pra tentar isolar o diálogo do Teach) — subir de novo com
`python BOT/engine_server/server.py` antes de qualquer teste novo. DLL do
plugin não mudou nesta rodada (só o fix de `order_target_candidates`, que
é Python puro).

---

## 2026-07-07 (100) - Claude

### 2 achados novos + fecha a sessão: on_ko_value sem peso pra debuff/set_power, self-redirect no-op (raiz incerta), abre tópico de combo estratégico

Sequência do bloco 99: rodei mais uma partida real (server reiniciado com
todos os fixes commitados) e o usuário auditou o log completo de novo.
2 achados novos, ambos em `on_ko_value`/redirect:

1. **`on_ko_value` não tinha peso pra `debuff_power`/`set_base_power`** —
   caíam no fallback genérico (`else: +8`). Sanjuan Wolf (`set_base_power`
   7000 no líder/personagem próprio) e Van Augur (`debuff_power` -3000 no
   oponente) empatavam em 23.0 apesar de serem efeitos MUITO diferentes em
   impacto — isso fez o Van Augur "ganhar" a escolha de redirect por ser
   mais barato de sacrificar (custo 1 vs 4), quando o Sanjuan Wolf (efeito
   bem mais forte: líder a 7000 de poder) devia ter sido escolhido. Fix:
   branch dedicado pra `debuff_power` (só conta se o oponente tem alvo
   ATIVO — mesma lição do achado #6 do bloco 99) e pra
   `set_base_power`/`buff_power` do NOSSO lado (peso pelo tamanho do
   swing). Validado: Sanjuan Wolf 51 vs Van Augur 39 com alvo ativo, Van
   Augur cai pra 15 sem alvo ativo nenhum.
2. **Self-redirect no-op**: no início de uma partida (log
   `2026-07-07T21.31.01.log`), o Teach "redirecionou" um ataque do líder
   PRA ELE MESMO (alvo original já era o líder, campo do bot vazio) —
   trashou o Black Hole à toa, zero ganho. Investiguei a fundo: testei
   `resolve_reaction` isolado com o cenário exato (campo vazio, alvo
   original = líder) e ele retorna `False` corretamente — MAS procurei no
   log real do server (155 linhas de stdout da partida inteira) por
   `[DEF] reaction` e **não achei NENHUMA ocorrência**, apesar de pelo
   menos 3 redirects reais terem acontecido nessa partida. Isso sugere que
   a ability do Teach pode não estar passando pelo gate
   `IsOfferingDownside` → `phase="reaction"` que o C# usa (ver
   `BotDriver.cs` ~linha 85-120) — foi direto pra escolha de alvo sem uma
   etapa de aceitar/recusar. **Não confirmei a causa raiz** (só dá pra
   confirmar com instrumentação ao vivo, não só lendo o combat log em
   texto) — não fiz um fix especulativo em cima de teoria não confirmada.
   Em vez disso, adicionei diagnóstico em `server.py` `/choose_target`:
   loga as zonas dos candidatos recebidos e um aviso explícito
   `[TGT][AVISO]` quando o alvo escolhido bate com o alvo original
   (self-redirect no-op detectado). Isso fica no stdout do server
   (`bvjlwph6w.output`-like, não no LogOutput.log do jogo) — checar isso
   manualmente na próxima partida, não pelo monitor ao vivo.

Ambos os fixes de `on_ko_value` validados (`smoke_test.py` 100%,
`smoke_test_broad.py` 40/40). Só Python, servidor precisa reiniciar.

### Resultado das 4 partidas reais de hoje: 4 derrotas, mesmo padrão

Rodei 4 partidas reais instrumentadas ao longo da sessão (2 antes dos
fixes, 2 depois). **O bot perdeu as 4**, sempre pelo mesmo motivo: Five
Elders do oponente reanima um board inteiro do trash num turno só
(Ju Peter + Ethanbaron + Warcury + Marcus Mars + Saturn) e fecha com o
Ethanbaron bufado. Os fixes de hoje (redirect, margem de counter, campo
cheio, on_ko_value) são reais e validados individualmente, mas nenhum
ataca esse padrão — são tudo correção tática pontual, não resposta
estratégica a um combo de virada. **Abri um tópico novo no TODO.md**
("consciência de combos estratégicos do oponente") documentando o padrão
observado e as perguntas de design em aberto — não escopado nem começado,
fica pra próxima sessão (ou continuação desta).

### Operacional
Server precisa reiniciar (server.py + decision_engine.py mudaram nesta
rodada). Nenhuma mudança em C#/DLL desta vez.

---

## 2026-07-07 (99) - Claude

### 2 partidas reais instrumentadas + 8 fixes (redirect/on-KO, margem de counter, campo-cheio, search, Stage no DTO)

Rodei 2 partidas reais contra o bot (server + plugin, SoloVSelf), auditando
decisão por decisão via log ao vivo (BepInEx LogOutput.log) + CombatLog
completo no fim de cada uma. Achados e fixes, todos em `decision_engine.py`
salvo indicação contrária:

1. **`on_ko_value` creditava `play_card` sem checar disponibilidade real**
   (partida 1: redirect do líder Teach escolheu Avalo Pizarro em vez de
   Vasco Shot — o bônus fixo de "jogar Fullalead do trash" valia +30 mesmo
   com o Fullalead já jogado antes, enquanto o Vasco Shot teria restado o
   Kuma do oponente de verdade). Fix: `_on_ko_play_card_value` (nova
   função) só credita se existir alvo elegível de verdade na mão/trash do
   dono (via `eligible_cards`), escalado pelo `board_value()` do achado.
   Testado com carta sem relação nenhuma (Brook/Laboon) pra confirmar que
   não é hardcoded pro caso reportado.
2. **Custo do redirect do líder era um número fixo (~25)**, ignorando o
   que realmente tem na mão. `resolve_reaction`/`order_target_candidates`
   (`sim_bridge.py`) trocados pra usar `EffectExecutor._trash_value` real
   (mesma régua de `_score_activate_main`) — protege carta jogável agora /
   ameaça cara em vez de sacrificar qualquer coisa por ganho marginal.
3. **`opp_counter_potential` só somava o stat impresso de counter**, nunca
   efeitos `[Counter] Activate` condicionais (Ground Death +4000 com
   trash≥10, "...Never Existed..." +4000 com líder Imu) — o bot atacava
   empatado sem margem e falhava contra essas cartas repetidas vezes na
   mesma partida. Fix: soma stat + `effects.counter.steps` (buff_power),
   validando as condições contra o estado real do oponente via
   `EffectExecutor._check_conditions`. Também trocado o
   `1000 if opp.hand else 0` do alvo-personagem em `don_needed_for_attack`
   pela mesma conta real (antes só o alvo-líder usava isso).
4. **Stage nunca chegava ao motor** — confirmado no `PlayerState.cs`
   decompilado: o jogo tem `Lgo_MyStage` dedicado, nunca lido pelo plugin
   (só `Lgo_MyDeploy`, que é só personagem). O Fullalead (stage do próprio
   bot) ficava em campo a partida toda sem nunca ser oferecido pro
   Activate:Main. Fix: `dto.stage` em `GameStateDto.cs`/`GameStateBuilder.cs`
   (lê `Lgo_MyStage`) + `PlayerDto.stage`/`gs.field_stage` em `server.py`.
   Validado end-to-end em Python e via Turn Planner real (Fullalead passou
   a ser oferecido, score 154). **DLL recompilada e copiada nesta sessão**
   — qualquer sessão nova que reabrir o jogo sem essa DLL não tem o fix.
5. **Bug pré-existente achado incidentalmente**: `_pay_costs` tinha uma
   branch `ko_own_character` DUPLICADA e quebrada (variável `p` indefinida,
   claramente colada de `_should_activate_main` por engano) — código morto
   até os fixes acima mudarem o scoring e o Turn Planner escolher, pela
   primeira vez num seed fixo do `smoke_test_broad.py`, uma ação que
   passava por ali. Removida a duplicata (a branch correta já existia logo
   depois, usando `self.me`).
6. **`debuff_power` (target `opp_leader_or_character`) escolhia por
   `board_value` puro, incluindo personagem JÁ RESTADO** (partida 2: Van
   Augur debuffou -3000 no St. Marcus Mars bem depois dele já ter atacado
   — efeito `this_turn` desperdiçado). Fix: prioriza ativo (não restado);
   só cai pra qualquer um se não sobrar opção ativa.
7. **Busca (`add_to_hand`) escolhia por `board_value` puro** (poder+keyword,
   sem contexto) em vez de `avaliar_carta` (situacional: custo jogável
   agora, fase, flags de efeito, postura) — mesmo padrão usado em ~12
   lugares do `_execute_step`, mas só troquei este (Laffitte/Shiryu-search)
   por ser o caso concreto reportado; os outros 11 ficam pendentes (ver
   abaixo — pra "sacrifício" a lógica se inverte, quer o MENOR valor).
8. **Guarda de campo cheio ausente no caminho principal de jogar carta**:
   a execução real (`main_phase`, ~linha 7290) sempre KO a pior carta do
   campo ao jogar um Character com campo cheio, SEM comparar se a nova é
   melhor — só um caminho secundário (efeito trigger-driven, GRUPO 2) tinha
   essa comparação. Causava troca Doc Q→Doc Q→Van Augur repetida no mesmo
   turno (visto em partida real: `Trash Doc Q / Deploy Doc Q / Trash Doc Q
   / Deploy Van Augur` 3x seguidas, turno de 9 DON). Fix: `_score_play_action`
   desqualifica (-999) jogar um Character quando o campo já tem 5 e ele não
   supera o pior lá, ANTES do DON ser gasto.

### Pendências (achadas, não corrigidas)
- **Shiryu (OP16-108) nunca jogado com 3 cópias na mão e DON de sobra**:
  causa raiz é o PARSER, não o scoring — `[On Play] trash 1: add card do
  trash pro topo da vida face-up` não está em `card_effects_db.json` (só o
  `[Trigger] draw 2` foi parseado). `card_analysis_db.json` (flags) está
  correto (`gains_life`, etc.), então a carta não é totalmente ignorada,
  mas perde o bônus de `_score_play_action` que depende de
  `'on_play' in effects`. Corrigir isso é trabalho de PARSER (workflow
  próprio: snapshot → fix → `diff_parser.py` PERDEU=0 → gerar_dbs →
  re-snapshot), não fiz nesta sessão.
- **9 outros lugares com `max(..., key=board_value)`** no `_execute_step`
  (K.O. por efeito, roubo, etc.) — mesmo padrão do achado #7, revisar um a
  um se faz sentido trocar pra `avaliar_carta` (contexto muda o sinal em
  alguns, ex: escolha de sacrifício quer o MENOR valor, não o maior).
- **Coordenação de múltiplos atacantes no mesmo alvo**: investigado e
  descartado como bug — usuário confirmou que atacar 2x o mesmo alvo pode
  ser drenar recurso de defesa do oponente de propósito (o bot não sabe de
  antemão se o 2º ataque vai passar de graça ou não). Sem ação.

### Validação
`smoke_test.py` (100%) e `smoke_test_broad.py` (40/40 sem exceção) rodados
depois de CADA fix acima; usei `git stash` pra comparar com baseline
quando a causa de uma falha não era óbvia (achado #5 veio assim).
`audit_replay.py` está quebrado no baseline por motivo não relacionado
(`_suppress_replay_log`/`decision_log` ausentes no `OPTCGMatch` construído
por esse script) — confirmado via stash, não é regressão desta sessão, não
investigado.

Logs das 2 partidas reais (SoloVSelf, mesma decklist nos dois lados):
`CombatLogs/2026-07-07T16.41.20.log` (antes dos fixes 1-3) e
`2026-07-07T18.27.45.log` (com os fixes 1-4, gerou os achados 5-8). Nas
duas o bot perdeu pra recursão Five Elders/Ethanbaron do oponente — não
investigado ainda (deck/estratégia de longo prazo, não bug pontual).

### Operacional
Server precisa reiniciar (.py mudou nos itens 1-3 e 5-8). DLL só muda pro
item 4 (Stage) — já recompilada e copiada pro BepInEx nesta sessão; se
abrir o jogo numa sessão nova sem rodar `dotnet build` de novo, o Stage
volta a ficar invisível pro motor.

---

## 2026-07-06 (98) - Claude

### Fecha o trabalho do Codex (bloco 97): piso prematuro em `live_attack_power`

Retomei a sessão onde o Codex ficou sem uso diário — ele já tinha commitado
o `powerAtk` end-to-end (97/8d01686) e deixado uncommitted: a correção do
alvo do copy-power da Devon (`EffectExecutor` usa `choose_highest_effective_power`
em vez de `choose_highest_board_value`; `order_target_candidates` prioriza
copy-power antes das zonas genéricas) e testes de regressão no
`smoke_test.py`. `python smoke_test.py` mostrava **1 teste falhando**:
exatamente o caso relatado pelo usuário (Doc Q -2000 vivo atacando Krieg
9000 com 9 DON — matematicamente perdido, mas o engine liberava a ação).

**Causa raiz**: `live_attack_power` aplicava `max(0, ...)` no poder vivo
**antes** de somar o DON que ainda seria anexado. Com Doc Q em -2000 e
`don_disp=9`, o cálculo virava `max(0,-2000) + 9000 = 9000` (empata com o
alvo — parece válido), quando o real é `-2000 + 9000 = 7000` (perde). O
log da partida confirma: com 9 DON anexados o combate real saiu **7000**,
nunca 9000 — o próprio `CardPower` do jogo não pisa em zero (achado do
Codex). Fix: removido o piso de `live_attack_power`; o piso só faz sentido
depois de somar TODO o DON (já anexado + o que ainda será), e os
consumidores (`score_attack_target`, `don_needed_for_attack`) já fazem essa
soma por cima — pisar antes é que causava a subestimação do déficit.

Validação: `python smoke_test.py` → TODOS OS TESTES PASSARAM (era só esse).
3 simulações completas sem regressão. Teste end-to-end via `/decide` e
`/choose_target` replicando a cena exata da partida (Doc Q/Devon com -2000
vivo, Krieg 9000 e Buggy 4000 em campo): o engine não gera mais o ataque
perdido (topo da lista vira ataque de líder com DON, score 15) e a Devon
escolhe Krieg (maior poder) antes de Buggy no copy-power. Plugin
recompilado (dll já tinha o `powerAtk` do commit anterior, só Python mudou
nesta rodada — ainda assim recompilei para garantir dll == fonte commitada).

Reiniciar o server antes da próxima partida (só `.py` mudou de fato).

---

## 2026-07-06 (97) - Codex

### Fix: engine consome `powerAtk` do jogo para ataque com debuff/passiva ao atacar

Contexto: depois do bloco 96, o plugin C# ja calculava `powerAtk` via
`CardPower(..., attacking=true)`, mas o server Python ainda ignorava esse
campo. Resultado provavel: o engine decidia ataques usando `dto.power` normal
e podia atacar como se nao existisse debuff/passiva que so aparece no momento
do ataque (caso observado: ataques sem considerar -2000 do lider/efeito opp).

Mudancas:
- `BOT/engine_server/server.py`: `CardDto` agora aceita `powerAtk`; `_make`
  guarda `_attack_power_override` na instancia da carta sem trocar
  `card.data.power` (fora do ataque continua usando `dto.power`).
- `scriptis_da_ia/optcg_engine/decision_engine.py`: novo `live_attack_power`
  usa `_attack_power_override + power_buff + DON`; `attack_time_power` parte
  desse valor e so depois projeta `[When Attacking]`.
- `Card.__deepcopy__` preserva `_db_base_power` e `_attack_power_override`
  para o Turn Planner nao perder os poderes vivos ao clonar estados.
- Potencial ofensivo, lethal planner e logs de ataque relevantes passaram a
  usar `attack_time_power`/`live_attack_power` em vez de `effective_power(True)`
  direto.

Validacao curta (sem simulacao longa):
- `python -m py_compile BOT\engine_server\server.py scriptis_da_ia\optcg_engine\decision_engine.py scriptis_da_ia\optcg_engine\sim_bridge.py`
- teste inline: atacante com `powerAtk=3000` + 1 DON vira 4000 e
  `don_needed_for_attack` pede +1 DON contra lider 5000.

Operacional: por mexer em `.py`, reiniciar o server antes do proximo teste
in-game. Por mexer no DTO/plugin C#, recompilar/recarregar a DLL se essas
mudancas ainda nao tiverem sido compiladas no build atual.

---

## 2026-07-06 (96) - Claude

### Diagnostico: partida das 10:29 rodou com SERVER ANTIGO

A partida CombatLogs/2026-07-06T10.29.31.log mostrou a reacao do Teach
disparando num caso que o codigo do bloco 95 (commit 09:55) bloqueia
(redirect p/ Van Augur com ganho liquido -2 << 25). A dll era nova (09:52)
mas o processo Python do server nao foi reiniciado. LEMBRETE OPERACIONAL:
apos mudanca em .py, Ctrl+C no server + rodar de novo; apos mudanca na dll,
fechar e reabrir o jogo.

Achado da analise: Krieg OP15-008 tem 9000 de BASE (custo 8) e o -2000 nos
nossos personagens vem do [Activate: Main] dele — o engine novo ve ambos ao
vivo via dto.power. Log do plugin agora imprime o don anexado no ataque
("[Bot] attack: X -> Y (don N)") para fechar auditorias como essa.

---

## 2026-07-06 (95) - Claude

### Fixes da 6ª rodada (partida CombatLogs/2026-07-06T09.48.13.log)

1. **"Turno perdido" com 4+ DON em pe (turnos de 5 e 7 don)** — causa: apos
   ativar o Laffitte, o engine REOFERECIA o mesmo activate como acao top
   (nao sabia que ele restou / ja usou a acao); o jogo recusava em silencio
   e o guarda de 3 repeticoes ENCERRAVA o turno (sem ataque do lider, DON
   parado). Fix em 2 camadas no gerador de activate:
   - fonte RESTADA nao gera activate (parser nem sempre captura rest_self);
   - `actionUsed` novo no DTO (lb_ActionsUsed do jogo) → `_am_used_turn`
     do engine, bloqueando QUALQUER re-activate no turno (com ou sem
     once_per_turn — o estado do jogo e a verdade; loops da Devon idem).
2. **Reacao do lider (Teach) sempre no 1º ataque** — a reacao e 1x/turno;
   agora `resolve_reaction` segura quando ainda vem atacante MAIOR
   (personagem ativo do opp ou lider em pe) e o ganho atual e marginal
   (< 2x o custo da carta). Ganho alto (ex: Doc Q com on-KO cheio) continua
   disparando na hora. Validado: Jango 2000 com Krieg 9000 por vir → False;
   Krieg 9000 atual → True.

Plugin recompilado (actionUsed no CardDto), 3 simulacoes OK.
Reabrir o jogo (dll nova) + reiniciar o server.

---

## 2026-07-06 (94) - Claude

### Fixes da 5ª rodada in-game (partida CombatLogs/2026-07-06T09.12.31.log)

4 observacoes do usuario, 4 fixes (+1 causa raiz achada):

1. **Laffitte de novo sem search em turno de 3 DON**: bonus +60 no
   _score_activate_main quando ativar nao trava o plano
   (don_available >= custo_don + 2) — activate 215 vence deploys (~125-166).
2. **Passou o turno com 1 DON ocioso e atacou 5000 seco**: margem parcial
   REABILITADA no don_needed_for_attack (o tudo-ou-nada do bloco 88 caiu):
   don_livre ja exclui plano+reserva, entao e DON ocioso — anexar e pressao
   gratis (força mais counter do oponente). CAUSA RAIZ junto:
   `opp_counter_potential` era estimativa estatistica por tamanho de mao
   (mao de 2 Kobys counter 2000 → devolvia 0!); agora soma REAL dos
   counters da mao do opp (objetos Card existem na sim e no SoloVSelf;
   docstring anota o caso futuro de mao oculta vs humano).
3. **Trigger do Sanjuan Wolf desperdicado**: resolve_trigger_choice
   reescrito — NAO usar trigger = carta vai pra MAO (valor garantido).
   draw seco/desconhecido → False; activate_main_effect (trigga o on-KO,
   caso Sanjuan/Vasco) → so se on_ko_value >= 25 no campo atual; ko/bounce/
   play/give_don/rest/debuff → True. Devon continua True (play_from_trash).
   Server passa opp_gs para o resolve.
4. **Engine cego ao -2000 do campo no copy-power**: modificadores vivos do
   atacante persistem apos set_base_power. Server guarda
   `card._db_base_power` (poder de banco) quando o vivo difere;
   attack_time_power aplica mod = vivo - banco na base copiada (Devon viva
   1000/banco 3000 copiando 5000 → 3000, nao 5000). Krieg OP15-001 tem
   opp_turn debuff_power 2000 all_opp_characters (confirmado no effects_db).

Validado: attach parcial de 1 DON ocioso, activate 215 primeiro no turno
de 3 DON, triggers Sanjuan False/Vasco True/Devon True, copy c/ debuff
3000. 3 simulacoes OK (1 vitoria do lado A). So Python — reiniciar server.

---

## 2026-07-04 (93) - Claude

### Fixes da 4ª rodada in-game: on-KO com FILTROS reais + search antes de deploy

Duas observacoes do usuario na partida das 18:55:

1. **Redirect escolheu Doc Q com o efeito MORTO**: o on-KO dele so KO-za
   custo <= 1 e o oponente nao tinha nenhum (morreu por um draw seco; o
   Vasco Shot, cujo rest custo <= 6 tinha alvo, era o certo). Fix:
   `on_ko_value` agora aplica os FILTROS dos steps (cost_lte/power_lte/
   rested_only/filter_type via `_step_matching_targets`) contra o campo
   real do oponente — KO sem alvo vale 0. Rest de personagem subiu de 15
   para 25 (nega ataque/bloqueio = tempo real). Validado na cena real:
   Vasco vem antes de Doc Q; com um custo 1 no campo (Otama), Doc Q volta
   a frente.
2. **Laffitte de novo sem ativar o search**: activate (135 pos-descontos)
   perdia para deploys baratos (135.5-150.5) e o DON acabava. Base de
   vantagem de carta em _score_activate_main: 120 → 170 (search PRIMEIRO e
   estritamente melhor: filtra o deck antes de decidir os deploys).
   Validado: activate 155 vira a 1ª acao do turno.

So Python — reiniciar o server. Simulacoes OK (ate uma vitoria do lado A,
variancia normal).

---

## 2026-07-04 (92) - Claude

### Varredura de consciencia de efeito no engine (pedido do usuario)

Auditoria dos pontos de decisao: char_value_score, should_use_blocker,
avaliar_carta e o branch de personagem do score_attack_target JA eram
effect-aware. 3 pontos cegos corrigidos:

1. **Alvo do copy-power (Devon OP16-104)**: `/choose_target` agora passa
   `actorCode` ao `order_target_candidates`; se o ator tem when_attacking
   `set_base_power` de `selected_opp_character`, opp_board ordena por
   MAIOR PODER (copiar o maior), nao por valor generico.
2. **Remocao de personagem do oponente**: opp_board ordena por
   `char_value_score - on_ko_value` — KO-zar personagem com on-KO rico
   presenteia o efeito ao oponente (o Doc Q DELES cai pro fim da fila).
3. **Pitch de counter** (`select_counter_cards`): empate no valor de
   counter desempata por `avaliar_carta` — nao joga fora carta com efeito
   bom junto com o counter (validado: pitchou Van Augur 135, guardou
   Shiryu 195).

Pontos cegos CONHECIDOS e nao corrigidos (baixo impacto, proxima leva):
- `should_use_counter` nao conta eventos [Counter] da mao (so card.counter);
- fallbacks raros de prompt usam choose_highest_board_value (so keywords).

So Python — reiniciar o server antes da proxima partida.

---

## 2026-07-04 (91) - Claude

### Redirect CASO A CASO por ganho liquido (refina o bloco 90)

Usuario corrigiu a prioridade fixa do bloco 90 ("sobrevivente primeiro"):
as vezes QUEREMOS o on-KO (Doc Q) mesmo com sobrevivente disponivel. Agora
cada opcao e pontuada pelo ganho liquido no campo atual e comparada:
- `redirect_option_value(card, atk, opp, engine)`: sobrevive = 0;
  morre = on_ko_value - char_value_score (Doc Q = +55 → vem ANTES de
  sobrevivente; sem chars do oponente o on-KO de KO vale 0 e ele cai).
- `life_redirect_cost(life)`: 15/25/45/90 p/ vida 4+/3/2/1 — o lider
  compete de igual (golpe em personagem → lider pode ser o melhor escape).
- `resolve_reaction`: reage se max(opcoes) + [valor salvo no alvo original]
  >= 25 (custo de 1 carta). Vida 4 + Doc Q → reage (troca paga); so
  sobrevivente → precisa vida <= 3; guardas de mao mantidas.
- `order_target_candidates` usa a MESMA conta (fonte unica) — nada de
  grupos fixos.

Testes: Doc Q antes de sobrevivente; lider antes de sacrificio seco; sem
chars do opp o sobrevivente volta a frente; reage com vida cheia so quando
a troca paga. 2 simulacoes OK. So Python — reiniciar o server (dll do 90
continua valida).

---

## 2026-07-04 (90) - Claude

### Redirect do Teach EFFECT-AWARE (regra do usuario)

O engine agora sabe o que as cartas fazem ao decidir usar e escolher o alvo
do redirect:

- Nova `on_ko_value(code, opp)` no decision_engine: valor dos efeitos
  [On K.O.] (ko 30/un, draw 15, rest 15, play 30...) — Doc Q OP16-109 vale
  75 (2 KOs + draw), Laffitte 0.
- `resolve_reaction(..., defender_uid)`: alem de sobrevivente/sacrificio,
  reage quando (a) o alvo original e um personagem NOSSO valioso
  (board_value >= 4) prestes a morrer — redireciona para o LIDER, 1 vida
  salva o personagem; (b) existe sacrificio barato com on-KO rico
  (on_ko_value >= 20) — vale ate vida 3.
- `order_target_candidates` com contexto de ataque prioriza:
  1. sobrevivente (maior poder), 2. sacrificio com on-KO rico,
  3. o proprio LIDER quando o alvo original e personagem nosso (vida > 1),
  4. sacrificio seco (valor descontado do on-KO). Alvo original sempre
  por ultimo.
- Plumbing: /defense reaction agora recebe `defenderId` (plugin envia
  UidOf(go_Defender)); EngineClient.Defense ganhou o parametro.

Testes: Doc Q escolhido antes do lider, lider antes de sacrificio seco,
sobrevivente sempre primeiro, alvo original sempre ultimo; reacao dispara
p/ salvar Shiryu 8000 e p/ trocar Doc Q com vida 3. 2 simulacoes OK,
plugin recompilado. Falta teste in-game (reabrir jogo + reiniciar server).

---

## 2026-07-04 (89) - Claude

### Fixes da 3ª rodada in-game (partida CombatLogs/2026-07-04T12.49.05.log)

5 observacoes do usuario + 2 bugs achados na investigacao:

1. **[Activate: Main] agora executa** (Laffitte OP09-095 search nunca rodava):
   o server excluia 'activate' dos allowed_types e o bridge pulava — o log
   mostrava `(105.0, 'activate')` sendo ignorado toda rodada. Novo
   `TryActivate` no plugin (clique na carta em campo → CardAction idx, mesma
   busca de acao do fluxo de evento, extraida em `FindActivatableMainIndex`).
2. **BUG GRAVE: sim_bridge lia `_effects_db[code]['trigger']` sem o nivel
   `'effects'`** — steps sempre {} → o bot NUNCA usava trigger de vida
   (todos os `[DEF] trigger -> False` dos logs) e `get_card_on_play_steps`
   sempre []. Corrigido usando `get_card_effects` (que resolve o nesting).
3. **`attack_time_power`**: poder no momento do ataque inclui buffs proprios
   de [When Attacking] (buff_power self e set_base_power copiando personagem
   do oponente — Catarina Devon OP16-104 3000 agora vale o maior char do opp
   no score e no calculo de DON). Usado em score_attack_target e
   don_needed_for_attack.
4. **Margem de counter no lider = PROVAVEL (cap 2000), tudo-ou-nada**: o
   potencial cheio afundava DON demais; margem parcial e DON queimado (o
   oponente cobre a diferenca) — ou cobre o provavel inteiro ou vai seco.
5. **resolve_reaction criterioso** (Teach pagava carta toda rodada e ficou
   de mao vazia): nao usa mais should_use_counter (exigia counter numerico;
   redirect paga carta qualquer). Regras: ataque precisa ganhar; mao >= 2
   (salvo vida 1); redirect para SOBREVIVENTE so com vida <= 3; sacrificio
   barato (board_value <= 3) so com vida <= 2. Sem alvo viavel → nao paga.
6. **Preservacao de mao**: plays com mao <= 3 levam penalidade crescente
   (-30/-60/-90) — deixa carta para counter/custo de reacao.
7. **Guarda de loop no BotDriver**: mesma acao 3x seguidas sem mudar o estado
   (jogo recusando em silencio; turno 7 do log repetiu `(20.0, 'attack')`
   ~20x) → end turn.

Validacao: unit tests de attack_time_power (Devon 3000 → 12000 com Newgate
no campo), trigger OP16-104 → True, /decide devolve activate p/ Laffitte,
5 cenarios de resolve_reaction OK, 3 simulacoes completas sem regressao,
plugin recompilado (0 erros). Falta teste in-game.

---

## 2026-07-04 (88) - Claude

### Margem de counter virou LUXO — ataque "seco" de pressao (regra do usuario)

Refinamento do item 3 do bloco 87. Atacar 5000 vs 5000 SEM don e jogada
legitima: forca o oponente a escolher entre gastar counter/blocker ou perder
a carta/tomar dano. `don_needed_for_attack` agora separa duas parcelas:
- **Deficit base** (alvo - poder): obrigatorio, sempre anexado.
- **Margem de counter**: so paga com DON LIVRE do plano do turno —
  `don_available - jogadas que o engine ainda pretende fazer (plays com
  score >= 0, em ordem, enquanto o don alcanca) - reserva de defesa
  (_don_reserve_for_defense) - o proprio deficit base`.

`sim_bridge.don_for_attack(gs, opp, action, match=...)` calcula o don livre
(match da acesso ao plano); `/decide` passa o match. Simulacao continua com
don_livre=None (comportamento identico ao anterior — verificado).

Cenarios validados (TestClient + unit): plano cheio → so o base (probe seco
no 5000v5000); don ocioso → base + margem; margem 0 quando o oponente nao
tem counter potencial (correto, nao e bug). 3 simulacoes completas OK.
So Python — dll do bloco 87 continua valida, mas reiniciar o server.

---

## 2026-07-04 (87) - Claude

### Fixes da 2ª rodada de teste in-game (partida CombatLogs/2026-07-04T11.58.22.log)

Teste in-game do bloco 86 validou: redirect do Teach 3x sem alvo original,
personagens atacando, attach de DON pre-ataque funcionando (2/2 na Devon →
9000 matou Arlong), evento com custo OK. 4 problemas novos corrigidos:

1. **Engine cego a buffs/debuffs** (Devon -2000 do Krieg): o server usava o
   poder do BANCO. Agora GameStateBuilder envia `CardPower(go, false, true)`
   (poder vivo, sem When Attacking, sem DON — engine soma DON sozinho) e o
   `_make` troca o CardData da instancia via `dataclasses.replace`.
   **CUIDADO (bug ja cometido e corrigido aqui): NUNCA passar poder alterado
   no dict para `_make_card` — o `_CARD_DATA_CACHE` e por codigo e o valor
   envenena todas as copias futuras da carta, inclusive nas simulacoes.**
2. **Lider parado em turno de 5 DON**: postura DEFENSIVE (-80) + risco de
   trigger deixavam o ataque de lider validado com score -4 → bot passava o
   turno sem atacar. Piso `max(score, 15)` p/ ataque de LIDER (ele resta de
   qualquer forma, nao expoe personagem).
3. **Teach 5000 vs Arlong 5000 falhou por counter de 1000**:
   `don_needed_for_attack` agora poe margem de 1000 em alvos PERSONAGEM se o
   oponente tem mao (no lider ja usava opp_counter_potential).
4. **DON desperdicado no turno 1**: o `max(2, turn)` do `_dto_to_gs` fazia o
   engine gerar ataque no turno 1; o plugin anexava o DON e SO ENTAO recusava
   o ataque. Removido o hack (turno real; engine ja barra ataque em turn 1) e
   o attach movido para DENTRO do TryAttack, depois de todas as validacoes.

Validacao: TestClient (turno 1 → end_turn; Devon debufada nao ataca o Gin;
donToAttach=2 com margem; lider defensivo ataca com score 15; cache do
CardData intacto apos request com debuff), 3 simulacoes completas OK, plugin
recompilado (0 erros). Falta: proxima partida in-game para confirmar.

---

## 2026-07-04 (86) - Claude

### As 5 pendencias dos blocos 84/85 implementadas (falta testar in-game)

**Itens 4+5 (so lider ataca / ataques perdedores) — mesma raiz dupla:**
1. `/decide` devolvia `end_turn` quando a acao top do engine era um tipo que o
   plugin nao executa (`attach_don`/`activate`) → turno morria antes dos
   personagens atacarem. Fix: `choose_action(allowed_types=...)` no sim_bridge
   pula tipos nao-executaveis e pega a proxima acao de score >= 0 (ordem de
   preferencia continua 100% do engine).
2. O engine aprovava ataque contando com DON (`passa_com_don` +
   `_attach_don_for_attack` na simulacao), mas o bot declarava o ataque SEM
   anexar → Teach 5000 vs Jozu 7000 falhava. Fix: extraida
   `don_needed_for_attack()` (pura, decision_engine) usada pela simulacao e
   pelo `/decide`, que agora responde `donToAttach`; o plugin anexa via
   `AttachDonToCard` (publico no GLS; lider = iDeployIdx -1; dispara
   `CheckForAttachDonAction` como o fluxo humano). Acao `attach_don`
   (ligar keyword/efeito [DON!! xN]) tambem suportada. DTO ganhou
   `donAttached` por carta (lgo_AttachedDon.Count) para o engine ver DON ja
   anexado.

**Itens 2+3 (zonas trash/top_deck nos candidatos):**
- `CollectTargetCandidates` agora inclui `own_trash`/`opp_trash`
  (Lgo_MyTrash) e `top_deck` (lgo_TopDeck privado, via reflection); cada
  candidato leva `code` para o engine valorar cartas fora do DTO.
- `order_target_candidates`: top_deck = melhor carta primeiro (search),
  own_trash = melhor primeiro (recuperacao), opp_trash = melhor primeiro.
- Confirmacao de selecao agora clica o botao de finalize CERTO ofertado
  (le go_ChoiceButton1..4 ativos): `FinalizeTopDeck` → `ConfirmRevealedCard`
  → `SelectTargets` (fallback = comportamento antigo).

**Item 1 (redirect do Teach com alvo ruim/nulo):**
- `/choose_target` ganhou `attackerPower`/`defenderId`; o BotDriver os envia
  quando um efeito resolve durante estados Attack_*. Com contexto de ataque,
  `order_target_candidates`: alvo original SEMPRE por ultimo (redirect pra ele
  = no-op pago), personagem que sobrevive (poder > atacante) primeiro, senao
  sacrificio mais barato. Testado: sobrevivente 8000 vs golpe 6000 vem
  primeiro; sem sobrevivente, o 0-power vem primeiro; defensor sempre ultimo.

**Validacao:** unit tests via TestClient (decide/choose_target/health OK),
don_needed_for_attack (2 DON p/ 5000 vs 7000; -999 com DON insuficiente),
3 partidas simuladas completas (regressao do refactor OK), plugin compilado
(`dotnet build` 0 erros, dll copiada). **Falta: reabrir o jogo e testar
in-game** — personagens atacando, DON anexado pre-ataque, search do
OP09-096 escolhendo carta, Shiryu pegando do trash, redirect do Teach.

---

## 2026-07-04 (85) - Claude

### Mais pendencias observadas em partidas (2ª e 3ª partidas completas)

Partidas rodando de ponta a ponta com estabilidade (logs em CombatLogs/). Novas observacoes do usuario, somando as do bloco 84:

3. **Search do "My Era...Begins!!" (OP09-096) sem escolha**: o evento resolve
   mas o bot nao escolhe nenhuma carta na tela de search ("look at top X,
   reveal and add"). As cartas reveladas ficam numa zona propria
   (`lgo_TopDeck` no GLS) que NAO esta no `CollectTargetCandidates` — mesma
   familia do bug do trash (bloco 84 item 2). Adicionar zonas top_deck/trash
   aos candidatos + botoes de finalize (`FinalizeTopDeck`/`ConfirmRevealedCard`).

4. **Bot so ataca com o lider (quase nunca com personagens)**: personagens
   raramente atacam (Shiryu atacou 1x na 1ª partida, mas o padrao e so leader).
   Investigar: `bSummonSick` pode nao estar sendo limpo na leitura do DTO
   (justPlayed sempre true?) ou o engine esta descartando ataques de chars.

5. **Bot ataca com poder menor** (ex: Teach 5000 vs Jozu 7000 → Attack Fails,
   turno desperdicado): score de ataque do engine aceita ataques perdidos.
   Revisar `score_attack_target` — ataque que falha sem forcar counter/blocker
   do oponente nao deveria ter score positivo.

---

## 2026-07-04 (84) - Claude

### 🎉 PRIMEIRA PARTIDA COMPLETA (Solo vs Self, bot 100% automatico)

Partida inteira sem intervencao no lado do bot — log salvo em
`CombatLogs/2026-07-04T02.30.14.log` (bot perdeu no turno 5, mas jogou tudo):
- Mulligan, draw/don, deploys, EVENTS resolvendo (custo pago certo)
- Ataques com alvo do engine; defesa: counters (2x Catarina Devon fizeram o
  Ace de 6000 falhar contra 8000!), triggers, reacao do lider Teach com
  redirect de alvo, deploy pos-combate — tudo decidido pelo engine

**2 bugs observados na partida (proxima sessao):**
1. **Reacao do Teach com alvo ruim/nulo**: linha 207 do log — redirecionou o
   ataque para O PROPRIO TEACH (alvo original; pagou 1 carta por nada). Linha
   405: redirecionou para Doc Q [0 power] que morreu (deu 1 draw pelo on-KO,
   mas duvidoso). A decisao de USAR vem do should_use_counter, ok — mas o
   ALVO do redirect precisa de logica propria no engine (redirecionar so se
   existir personagem que sobrevive ao ataque ou que valha o sacrificio;
   nunca redirecionar para o proprio alvo original).
2. **Shiryu (OP16-108) on-play incompleto**: trashou da mao (custo ok) mas a
   parte de escolher carta DO TRASH nao aconteceu — `CollectTargetCandidates`
   nao inclui a zona TRASH (nem deck/vida). Adicionar own_trash/opp_trash
   como zonas de candidato + ordenacao no order_target_candidates.

---

## 2026-07-04 (83) - Claude

### docs: BOT/README.md com a arquitetura em camadas

Criado `BOT/README.md`: diagrama Plugin C# → server.py → sim_bridge.py → decision_engine.py (regra do motor unico), como rodar, como recompilar, tabela de endpoints, cobertura atual e pendencias.

---

## 2026-07-04 (82) - Claude

### Hook pre-commit: regras de memoria impressas em todo commit

Novo `scripts/hooks/pre-commit` (instalado via `setup-git-hooks.sh`, igual ao pre-push): imprime `memory/MEMORY.md` + as 3 regras-chave (um motor so / objetivo do bot / HANDOFF antes do push) na saida de TODO `git commit`. Para sessoes de IA o texto entra no resultado do comando — leitura forcada no momento do commit. Nao bloqueia (lembrete, nao gate).

Lembrete: em maquina/clone novo rodar `sh scripts/setup-git-hooks.sh`.

---

## 2026-07-04 (81) - Claude

### refactor: decisoes movidas do plugin/server para sim_bridge (regra dos dois motores)

Usuario lembrou da regra ANTES do teste — auditoria achou 2 violacoes introduzidas nas sessoes 75-80:
1. Plugin C# decidia "usa efeito opcional se mao >= 2" (BotDriver)
2. server.py continha heuristicas (selecao de counters, ordenacao de alvos)

**Novas funcoes no sim_bridge.py (unico lugar com logica de decisao):**
- `select_counter_cards(gs, atk, def) -> [uids]` — politica do use_counter
- `resolve_reaction(gs, opp, atk, def) -> bool` — efeito com custo durante ataque
- `resolve_optional_effect(gs, opp) -> bool` — efeito com custo no proprio turno (mao >= 2 E pior carta com avaliar_carta <= 60)
- `order_target_candidates(gs, opp, candidates) -> [uids]` — ordenacao por zona

server.py agora so delega (transporte puro). Plugin: downside no proprio turno chama `/defense phase=optional` (zero logica em C#).

Testes das 4 funcoes OK. Memoria `feedback_dois_motores.md` atualizada com o caso.

---

## 2026-07-04 (80) - Claude

### Defesa FUNCIONANDO in-game + reacao via engine + deploy swap

Usuario confirmou: bot reage aos ataques (blocker/counter/trigger/prompt do Teach OK). Dois refinamentos pedidos:

**1. Reacao do lider (Teach) em TODO ataque** — a heuristica "mao >= 2 → usa" era do plugin (paliativo). Agora: downside offer durante estados de ataque (`Attack_WaitOnBlocker/BeforeBlocker/WaitOnCounters`) → `POST /defense phase=reaction` → `engine.should_use_counter(atkPower, defPower)` decide (so gasta carta se o ataque e serio para a vida atual). Downside no proprio turno (pos-play) mantem heuristica mao >= 2.

**2. Deploy com campo cheio (5 chars)** — estado `Action_SelectingDeploySwap` ("Select Character to Replace") nao era tratado → freeze. Agora: engine ordena o proprio campo por menor valor (`/choose_target` zona own_board), `DeploySwap(go, false)` substitui o pior personagem. Sem candidato → Cancel.

Recompilado; falta reabrir o jogo e testar.

---

## 2026-07-04 (79) - Claude

### fix: actor V3 null — causa raiz dos travamentos em prompts de efeito

Heartbeat revelou: em TODOS os prompts pendentes, `aca=True mine=False actor=-` — `acaActive.goActor` e **null em acoes V3** (a maioria das cartas modernas). `PendingActionIsMine` retornava false e os handlers silenciavam.

**Fix**: usar `acaActive.ActorObject()` (metodo publico que resolve os dois estilos: old-style usa goActor; V3 busca `FindCardByUniqueDeckID(iActorID)`).

**Melhorias no HandlePendingAction:**
- `RemainingV3Targets(gls)` via `RemainingTargetsToSelect` (private): se 0 alvos faltando (ex: "Choose 0 Friendly Targets") → confirma direto via `ChoiceButtonClicked(SelectTargets)` → `V3NextStep(acaActive)` (todos os botoes Select*/ConfirmInfiniteTargets roteiam para V3NextStep)
- Rastreia `iActionStep`: novo step do mesmo acaActive → refaz a ordem de candidatos
- Esgotou candidatos: confirma selecao parcial V3 uma vez; ainda travado → Cancel

Evento agora resolve e vai pro trash ✓ (confirmado in-game pelo usuario). Teach: o prompt acontece com acaActive setado durante Attack_WaitOnCounters — com o actor fix o handler agora assume.

---

## 2026-07-04 (78) - Claude

### fix grave: bot pagava DON de EVENT sem efeito + heartbeat de debug

Usuario reportou: bot "jogou" 2x o evento My Era...Begins!! (OP09-096) — DON pago, sem log no jogo, sem carta no trash, carta continuou na mao.

**Causa**: `TryPlay` clicava `Deploy` para qualquer carta. `Deploy()` roda `TapDon(custo)` INCONDICIONALMENTE e depois so tem branch para Character/Stage — para EVENT: paga o DON e nao faz nada.

**Fluxo correto de EVENT** (decompilado): clique na carta → `EventFindPossibleActions` seta `go_PendingChoice` e adiciona botoes **CardAction** (um por acao, extra = indice) → clique no CardAction → `ActivateCardAction(idx)` → evento vira acaActive, custo pago pelo pipeline da acao.

**Fix**: `TryPlay` agora detecta `cardDef.cardType == CardType.Event` e clica `ChoiceButtonClicked(CardAction, idx)` com o indice da primeira acao ativavel (replica a busca do EventFindPossibleActions: V3 `proc.ActivateMain && CanActivateAction(i)` primeiro, old-style `actionTrigger.ActivateMain` depois). Sem acao ativavel → Cancel.

**Debug**: heartbeat no BotDriver loga estado do jogo a cada 3s (state/turn/action/aca/downside/mine/actor) quando muda — para diagnosticar o travamento do prompt do Teach que continua silencioso (handlers novos na dll confirmados, mas nada logado; proximo teste com heartbeat vai revelar).

Teach: efeito e ANTES do dano (reacao ao ataque), nao depois — corrigido o entendimento.

---

## 2026-07-04 (77) - Claude

### fix: prompt "Select 1 Cards to Trash" era downside offer (bOfferingDownside)

Bot travou de novo no efeito do lider Teach. Log do BepInEx: silencio apos "no blocker" — o handler de acaActive nem rodava, porque o prompt e uma **oferta de downside cost** (`bOfferingDownside = true`, linha 30794 do GLS): efeito opcional com custo (trash 1 carta) mostra botoes **Cancel / UseOnPlay** e IGNORA cliques em cartas ate decidir. Meu branch excluia exatamente esse caso.

Fix no `BotDriver`: quando `acaActive != null && bOfferingDownside && efeito e do bot` → decide usar (mao >= 2 cartas → `UseOnPlay`; V3 → `UseV3OnPlay`) ou `Cancel`. Depois do UseOnPlay o jogo zera bOfferingDownside e a selecao do custo (trash) cai no `HandlePendingAction` normal (engine escolhe a pior carta).

Heuristica MVP do "usar ou nao": mao >= 2 cartas. Refinar depois com decisao do engine se necessario.

---

## 2026-07-04 (76) - Claude

### Teste de defesa in-game + 2 fixes: crash do trigger e prompts de efeito

**Teste in-game da defesa**: blocker OK (`NAO bloqueia` clicou NoBlocker), counter OK (`0 cartas` → ResolveAttack, dano passou). Mas: (1) crash no trigger; (2) bot travou no prompt "Select 1 Cards to Trash" do proprio lider Teach (efeito ao tomar dano).

**Fix 1 — bug pre-existente no sim_bridge**: `_effects_db = _load_effects_db()` era sempre None (`_load_effects_db()` popula o global `_EFFECTS_DB` do decision_engine e retorna None). `_analysis_db` idem. Fix: carregar e ler os globals do modulo. `resolve_trigger_choice` nunca tinha sido exercitada de verdade.

**Fix 2 — handler generico de prompts de efeito (acaActive)**: resolve tanto o efeito do lider Teach quanto os prompts de On Play (item 2 da fila!).
- Fluxo do jogo: `acaActive != null` → clique em carta vai para `HandleMouseClickDuringCardAction` que valida via `CardIsViableTarget`/V3 e IGNORA cliques invalidos — podemos tentar candidatos em ordem sem risco.
- `POST /choose_target` no server: engine ordena candidatos por zona — own_hand pior primeiro (`avaliar_carta`), own_board menor valor, opp_board maior valor (`char_value_score`), leaders/stages por ultimo.
- `BotDriver.HandlePendingAction`: detecta acaActive novo (por referencia), pede ordem ao engine 1x, clica um candidato por tick (cooldown 0.8s); esgotou → `Cancel`. So age se `FindCardOwner(acaActive.goActor) == botPs` (prompt do humano fica pro humano).
- Roda nos DOIS turnos (On Play no turno do bot; efeitos reativos no turno do humano).

Testes: `resolve_trigger_choice` com effects_db carregado ✓; `/choose_target` ordena corretamente (descarta pior carta primeiro, leader por ultimo) ✓.

Falta testar in-game (reiniciar servidor + jogo).

---

## 2026-07-04 (75) - Claude

### feat: defesa do bot (blocker / counter / trigger)

Decisoes 100% no engine (sem logica de carta no plugin — regra dos dois motores respeitada).

**Fluxo do jogo (verificado no decompilado):**
- `SetupBlockerPhase` alterna `iPlayerAction` para o DEFENSOR → durante `Attack_WaitOnBlocker`/`Attack_WaitOnCounters`, `iPlayerAction == defensor`
- Blocker: clique no personagem via `HandleMouseClickCardAttackBlocker` (jogo valida `CardCanBlock`); recusa = `NoBlocker`
- Counter: `bConfirmCounter = false` (public) + `DiscardCardForCounter(carta)` por counter + `ChoiceButtonClicked(ResolveAttack)`
- Trigger: estado `Life_ActivateTrigger`/`Life_DoubleTriggering`; carta revelada = `LastDrawnCard()`; botoes `Trigger`/`NoTrigger`
- Poder atual (buffs/DON inclusos): `gls.CardPower(go, bAttacking)` — public

**server.py — `POST /defense`** `{state, phase, attackerPower, defenderPower, triggerCode}`:
- blocker → `DecisionEngine.should_use_blocker(atk)` → `{blockerId}` (0 = nao bloqueia)
- counter → `should_use_counter(atk, def)` + selecao minima (menores primeiro, so se cobre o ataque) → `{counterIds}`
- trigger → `sim_bridge.resolve_trigger_choice(gs, code)` → `{useTrigger}`
- Erro → defesa conservadora (nao bloqueia/counteriza/usa trigger)

**Plugin:** `BotDriver.HandleDefense()` roda no turno do humano; `BotExecutor` ganhou `TryBlock`/`NoBlocker`/`PlayCounters`/`ResolveTrigger`/`Attacker`/`Defender`/`PowerOf`/`TriggerCardCode`. Guard `_blockerTried` evita loop se o jogo recusar o blocker.

**Testes (endpoint):** blocker com vida 2 + OP01-014 no campo → bloqueia ✓; counter 6000 vs 5000 (needed 1001) → escolhe exatamente 2x1000 ✓; trigger → decisao do engine ✓.

**Falta testar in-game** (reiniciar servidor + jogo). Trigger do bot em `Life_DoubleTriggering` durante o proprio turno do bot (Double Attack do humano? nao existe — double attack e do atacante; ok) — cobrir depois se aparecer caso.

---

## 2026-07-04 (74) - Claude

### TESTE COMPLETO OK — bot joga turno inteiro sozinho no Solo vs Self

Confirmado pelo usuario com o servidor + dll novos:
- `/mulligan` chamado e respondido no inicio da partida ✓
- Draw Card / Draw Don automaticos ✓
- Plays e attacks executados pelo engine (varios `/decide` por turno, don pago corretamente) ✓
- End turn automatico quando `0 acoes` ✓

**Estado atual do BOT (BepInEx v1.1)**: turno do bot 100% automatico no Solo vs Self.

**Proximos passos sugeridos (por prioridade):**
1. Defesa do bot quando o humano ataca (Blocker/Counter/Trigger — hoje o usuario clica pelos prompts do lado do bot; ha `bAutoNoBlock` nativo como paliativo)
2. Prompts de escolha pos-deploy (efeitos On Play que pedem alvo — ex: "Select 1 Cards to Trash" do Ace)
3. Acoes `activate` e `attach_don` do engine (hoje viram end_turn no server.py)
4. Multiplayer: mudar deteccao de turno/lado (bot = jogador local; testar como o fluxo de rede difere do SoloVSelf)

---

## 2026-07-04 (73) - Claude

### feat: mulligan automatico decidido pelo engine

Teste anterior confirmou: draw/don/end turn automaticos OK. Faltava a decisao de mao inicial.

Fluxo do SoloVSelf no decompilado: `OfferMulligan` → `Start_WaitOnMulliganChoice`; cada lado decide EM SEQUENCIA, controlado por `iPlayerAction` (`CurrentPlayer() = Lps_Players[iPlayerAction]`); apos cada Keep/Mulligan o jogo alterna `iPlayerAction` e re-oferece para o outro lado.

- `server.py`: novo `POST /mulligan` — recebe a mao, chama `match._mulligan_decision(hand, deck=None)` do engine (avalia curva T1/T2/T3, searcher, ramp, counters), retorna `{mulligan, reason}`. Testado: responde com motivo ("curva ok (T1:s T2:s T3:s); tem searcher").
- `EngineClient.ShouldMulligan(hand)` no plugin (default keep em erro).
- `BotDriver`: em `Start_WaitOnMulliganChoice`, se `iPlayerAction == BotPlayerIndex`, decide e clica `StartingHand_Keep`/`StartingHand_Mulligan`.

**IMPORTANTE para o teste**: reiniciar o servidor Python (Ctrl+C e rodar de novo) — o processo antigo nao tem o endpoint /mulligan. E reabrir o jogo (dll nova).

---

## 2026-07-04 (72) - Claude

### fix: auto Draw Card/Don usava estados errados

Os botoes Draw Card/Draw Don ESPERAM em `PlayerTurn_DrawCardWait`/`PlayerTurn_DrawDonWait` — os estados sem "Wait" sao transitorios (PlayerDrawPhase adiciona o choice e troca pro Wait no mesmo frame). Driver corrigido para os estados *Wait. Recompilado.

Descoberta util: o jogo tem `bAutoDraw` (setting) que auto-clica esses botoes para qualquer jogador — alternativa nativa se quisermos.

---

## 2026-07-03 (71) - Claude

### PRIMEIRO TESTE FUNCIONAL + auto Draw Card/Don

**v1.1 FUNCIONOU no Solo vs Self**: log do jogo mostra `[You] Deploy Catarina Devon`, ataques com trigger ativado, `[You] End Turn` — o bot jogou de verdade pelo engine, pagando custos.

Feedback do usuario: no inicio do turno do bot era preciso clicar Draw Card e Draw Don manualmente. Fix: `BotDriver.Update` agora detecta `PlayerTurn_DrawCard`/`PlayerTurn_DrawDon` e clica `ChoiceButtonClicked(DrawCard/DrawDon)` sozinho (cooldown 0.5s). Recompilado, dll em plugins — precisa reabrir o jogo.

---

## 2026-07-03 (70) - Claude

### refactor(BOT): v1.1 — driver Update() substitui hook AddTurn

**Primeiro teste real** (Solo vs Self): plugin carregou, hooks dispararam, engine respondeu — mas nenhuma acao aconteceu no campo. Dois problemas de raiz encontrados no decompilado:

1. **Timing**: em SoloVSelf o `AddTurn` dispara no estado `PlayerTurn_Start` (linha 29071 do GLS), ANTES do untap/draw/don — por isso `mao=5 don=0`. O state machine nao esta em `PlayerTurn_Action`, entao Deploy/StartAttack nao funcionam nesse momento. Alem disso o RunTurn sincrono dentro do hook nao dava tempo do state machine resolver combates.
2. **`atacante -1 nao encontrado`**: leader tem `deckUniqueID = -1`; a busca por uid falhava.

**Nova arquitetura (v1.1):**
- `TurnPatch.cs` e `EngineServer.cs` REMOVIDOS (sem Harmony patch; server inicia manual)
- `BotDriver.cs` (novo): MonoBehaviour criado no Awake do plugin. A cada frame verifica: `e_GameStyle == SoloVSelf`, `iPlayerTurn == BotPlayerIndex(0)`, `e_CurrentState == PlayerTurn_Action`, `acaActive == null`, `acaPending` vazio. Se tudo ok: monta DTO, chama `/decide`, executa UMA acao, cooldown de 1s. Fail-safes: MAX 25 acoes/turno, 2 falhas consecutivas → end turn.
- `BotExecutor.cs` reescrito com o **caminho do clique humano** (o jogo valida e paga custos sozinho):
  - play: `HandleMouseClickCardDuringActionState(card)` → verifica `go_PendingChoice == card` (jogo aceitou) → `ChoiceButtonClicked(Deploy)` → `Deploy()` paga custo via `TapDon` (chamar `DeployCardFromHand` direto NAO paga custo = trapaça!)
  - attack: valida turno > 1 e nao-rested → `go_PendingChoice = atacante` → `StartAttack()` → `HandleMouseClickCardAttackTarget(alvo, false)`
  - end turn: `bConfirmEnd = false` (public) → `ChoiceButtonClicked(EndTurn)`
  - Lider com uid -1: fallback compara `action.cardId` com o uid que NOS enviamos no DTO (`dto.bot.leader.deckUniqueId`)
- Recompilado; dll atualizada em BepInEx\plugins.

**Pendencias conhecidas (MVP):**
- Defesa do bot (blocker/counter/trigger quando o humano ataca): NAO implementada — o usuario clica pelos prompts do lado do bot durante o teste (ou ativar bAutoNoBlock do jogo)
- Tipos de acao `activate`/`attach_don` do engine viram end_turn no server.py
- Precisa fechar e reabrir o OPTCGSim para carregar a dll nova

---

## 2026-07-03 (69) - Claude

### fix(BOT): lados dos jogadores corrigidos no plugin

Usuario questionou "como sabe que o P1 e o topo?" — auditoria no decompilado revelou que o plugin estava INVERTIDO:

- `GameStartSolo()`: `LoadMyDeck(Lps_Players[0])` / `LoadEnemyDeck(Lps_Players[1])`
- **Lps_Players[0] = "You" = lado de BAIXO** (orientacao normal na tela)
- **Lps_Players[1] = "Opponent" = lado de CIMA** (cartas invertidas)
- `AddTurn(..., isPlayer1TurnStarting = CurrentPlayer() == Lps_Players[0])`

O plugin agia quando `isPlayer1TurnStarting == false` (= turno do lado de CIMA). Corrigido: bot agora e o **player 0 (baixo, [You])** — igual sera no multiplayer (lado local = baixo). Constante `AddTurnPatch.BotPlayerIndex = 0` centraliza a escolha; `GameStateBuilder.Build(botPs, oppPs, gls)` recebe os lados explicitos; `BotExecutor` usa o indice.

Nota: no Solo vs Self o humano joga o lado de CIMA ([Opponent]) e o bot responde pelo de baixo. Os snapshots do bot antigo (bot_optcgsim.py OCR) assumiam bot = [Opponent] — o bot OCR e o plugin usam convencoes OPOSTAS; nao misturar.

Recompilado com sucesso, dll atualizada em BepInEx\plugins.

Limitacao conhecida: `AddTurn` so dispara apos o primeiro `EndTurn` — se o bot (player 0) comecar a partida, ele nao age no turno 1 (o humano precisa passar o primeiro turno dele para destravar o fluxo). Resolver depois se incomodar.

---

## 2026-07-03 (68) - Claude

### BOT compilado + servidor testado de ponta a ponta

**Setup concluido:**
- .NET SDK 8.0.422 instalado (winget)
- BepInEx 5.4.23.2 (binario win x64) extraido em `E:\Games\OnePieceSimulador\Builds_Windows\` (`winhttp.dll` + `BepInEx\core\`); pasta de codigo-fonte baixada por engano foi removida
- `OPTCGBotPlugin.dll` compilado com sucesso e copiado para `BepInEx\plugins\`

**Correcoes no build:**
- `.csproj`: pacotes NuGet BepInEx nao existem no nuget.org → referencia direta as DLLs locais (`BepInEx\core\BepInEx.dll`, `0Harmony.dll`)
- Jogo usa netstandard 2.1 (Unity Mono moderna) → adicionadas referencias a `netstandard.dll` e `System.Net.Http.dll` do `Managed\` do jogo
- PostBuildEvent xcopy falhava (`$(TargetPath)` vazio) → trocado por `<Target Name="CopyToPlugins">` com task `<Copy>`

**server.py reescrito e validado:**
- `choose_action` exige `OPTCGMatch` → `_get_match()` lazy cria um com o primeiro deck disponivel (match e so maquinaria; GameStates reais vem do DTO)
- `GameState` exige `leader` → construido a partir do leader do DTO
- Formato da action confirmado no engine: `(score, tipo, card, ttype, tgt)` — attack usa `action[3]='leader'|'character'` e `action[4]=tgt_card`
- `gs.turn = max(2, turnNumber)` (can_attack_this_turn exige turn > 1)
- **Smoke test OK**: `/health` → ok; `/decide` com estado realista → `{"type":"attack","cardId":100,"targetId":0}` (lider ataca lider — decisao correta)

**Falta**: rodar o OPTCGSim com o plugin carregado e testar Solo vs Self de verdade.
Fluxo de teste: `python BOT/engine_server/server.py` → abrir OPTCGSim → Solo vs Self.
Log do plugin: `BepInEx\LogOutput.log`.

Housekeeping: `BOT/.gitignore` criado (bin/obj do plugin fora do repo; tinham sido commitados por engano e foram removidos do tracking).

---

## 2026-07-03 (67) - Claude

### fix(BOT): nomes de campos/metodos verificados contra o decompilado

Auditoria dos nomes usados no plugin C# vs `dnspy-export/Assembly-CSharp/`:

| Estava no plugin | Nome real verificado |
|---|---|
| `bJustPlayed` | `bSummonSick` (LiveCard e **struct** — leitura ok, escrita nao persiste) |
| `iPower` | `cardPower` |
| `cardDef.sCode` | `cardDef.cardID` |
| `cardDef.iCost` | `cardDef.cardCost` |
| `Lgo_MyBoard` | `Lgo_MyDeploy` |
| `Lgo_MyLife` | `Lgo_MyLifeDeck` |
| `StartAttackInternal()` | nao existe — fluxo real: `go_PendingChoice = atacante` → `StartAttack()` → `HandleMouseClickCardAttackTarget(alvo, false)` |

Membros **private** (precisam de AccessTools/Harmony):
- `GameplayLogicScript.go_PendingChoice`, `DeployCardFromHand`, `StartAttack`, `HandleMouseClickCardAttackTarget`
- `GameStateManager.gls` → resolvido com injecao `___gls` no patch Harmony

Publicos confirmados: `EndTurn_Internal()`, `Lps_Players`, `gsv_CurrentGame`, `Lgo_MyHand`, `Lgo_MyLeader`, `Lgo_MyDonCostArea`.

Outras correcoes:
- `activeDon` agora conta so DON **nao-tapped** na cost area (antes contava tudo)
- `GameStateBuilder` reescrito com null-checks estilo Unity (`go != null ? GetComponent : null`)
- `.csproj` ganhou `<LangVersion>latest</LangVersion>` (sintaxe C# 9 com target net46)

Ainda falta: instalar BepInEx, compilar (`dotnet build`), testar em Solo vs Self.

---

## 2026-07-03 (66) - Claude

### feat: BOT/ — arquitetura BepInEx para integrar engine diretamente no OPTCGSim

Criada pasta `BOT/` com duas sub-partes:

**`BOT/OPTCGBotPlugin/`** — plugin C# para BepInEx 5.x (Unity Mono)
- `OPTCGBotPlugin.csproj` — projeto .NET 4.6, referencia BepInEx + DLLs do jogo
- `Plugin.cs` — entrada BepInEx, inicia o servidor Python e aplica patches Harmony
- `GameStateDto.cs` — DTOs para serializar estado do jogo em JSON
- `GameStateBuilder.cs` — converte `PlayerState` (objetos Unity vivos) → `GameStateDto`
- `EngineClient.cs` — cliente HTTP que chama `localhost:8765/decide`
- `TurnPatch.cs` — `[HarmonyPatch] GameStateManager.AddTurn` → detecta turno P2, chama engine
- `BotExecutor.cs` — traduz ação JSON do engine → chama `EndTurn_Internal`, `DeployCardFromHand`, `StartAttackInternal`
- `EngineServer.cs` — inicia `server.py` como processo filho

**`BOT/engine_server/server.py`** — FastAPI em `localhost:8765`
- `GET /health` — verifica se server está vivo
- `POST /decide` — recebe `GameStateDto`, converte para `GameState` do engine, chama `bridge.choose_action`, retorna `{type, cardId, targetId}`

**Próximos passos:**
1. Instalar BepInEx 5.x em `E:\Games\OnePieceSimulador\Builds_Windows\`
2. Compilar o plugin: `dotnet build BOT/OPTCGBotPlugin/`
3. Verificar nomes exatos dos campos de `LiveCard`, `PlayerState`, `GameplayLogicScript` — alguns podem diferir do decompilado (ex: `bJustPlayed`, `Lgo_MyHand`, `StartAttackInternal`)
4. Testar com Solo vs Self

---

## 2026-07-03 (65) - Claude

### Fix: suporte a Solo vs Self (log formato real do simulador)

Análise do arquivo `.log` real revelou 3 problemas que impediam o bot de funcionar:

**1. Regex de código de carta errada**
Formato real: `["OP13-043">OP13-043]` — não `<link="...">` nem `[CODE]`.
Fix: `_RE_CODE = re.compile(r'"([A-Z]{1,4}\d{2}-\d{3}[a-z]?)">')` — casa o formato real; fallback `_RE_CODE_BARE` mantido para compatibilidade.

**2. Snapshots usam `[]` sem nome**
Formato real: `[] Hand: [OP13-042,...]` — não `[You] Hand:`.
Fix: `_RE_SNAP_*` agora aceita nome vazio `([^\]]*)`; lógica de atribuição usa `_snap_anon_idx` (contador por chamada) + `_last_end_turn` para determinar dono:
- `_last_end_turn == "You"` → 1° bloco = bot (Opponent), 2° = opp (You)
- `_last_end_turn == "Opponent"` ou `""` (game start) → 1° = opp (You), 2° = bot (Opponent)
Counter reseta a cada linha de ação não-snapshot.

**3. Detecção de nome no Solo vs Self**
`_detect_names_from_log` sem `Has Connected` caía no fallback que retornava `You` como `_our_name` (errado — bot é Opponent/P2).
Fix: se `You` e `Opponent` estão nos leaders sem `Has Connected` → retorna `("Opponent", "You")`.

Globais adicionados: `_last_end_turn` (resetado em `_reset_log`), `global _last_end_turn` em `apply_log_delta`.

---

## 2026-07-03 (64) - Claude

### CLAUDE.md atualizado: leitura de memórias obrigatória antes de cada commit

Adicionado bloco "LEITURA OBRIGATÓRIA ANTES DE QUALQUER COMMIT" no topo de `CLAUDE.md`.
O bloco aponta para `memory/MEMORY.md` e resume as duas regras críticas:
- Bot = olhos/mãos; engine = cérebro; sem dois motores (`feedback_dois_motores.md`)
- Objetivo do bot: logs → engine → front-end (`project_objetivo_bot.md`)

Arquivos de memória criados na sessão anterior (fora do repo, em
`C:\Users\arthu\.claude\projects\...\memory\`): `MEMORY.md`, `feedback_dois_motores.md`, `project_objetivo_bot.md`.

---

## 2026-07-03 (63) - Claude

### Refactor: lógica de trigger movida do bot para sim_bridge

`_should_use_trigger()` em `bot_optcgsim.py` consultava o effects_db e tomava decisão estratégica — violação da regra "bot = olhos/mãos, engine = cérebro, sem dois motores".

Fix: bot agora só detecta pixels (`_is_trigger_step`) e lê o nome da carta pelo preview OCR, depois delega para `bridge.resolve_trigger_choice(gs, card_code)` em `sim_bridge.py`. Toda a lógica de decisão (quais actions valem o trigger, checagem de mão/vida) ficou em `sim_bridge.resolve_trigger_choice`.

---

## 2026-07-03 (62) - Claude

### 4 bugs corrigidos proativamente

**Bug 2 — `_reset_log()` mid-game (grave)**
`_reset_log()` era chamado toda vez que a Main Phase era detectada (turno 2+). Isso zerava `_log_file_offset` e `_log_search_after`, fazendo o bot parar de receber eventos do log a partir do segundo turno.
Fix: removido o `_reset_log()` do bloco `if detected`. O arquivo de log é único por partida, o offset continua válido entre turnos.

**Bug 1 — `just_played` nunca limpo**
Personagens marcados `just_played=True` ao entrar no campo nunca tinham esse flag removido. `PRE-FAIL: just_played sem Rush` impedia ataques para sempre.
Fix (duplo): (1) no início de cada Main Phase detectada, itera `gs.field_chars` e zera `just_played`; (2) em `apply_log_delta` ao ver `Draw #N Card` nosso, também zera (garante mesmo se a Main Phase não for re-detectada).

**Bug 3 — DON drift entre turnos**
`don_available` acumulava entre turnos: `ActionActivateDon` somava DON, e o `Draw Don` do turno seguinte somava de novo. Podia inflar sem teto.
Fix: ao detectar Main Phase, lê o DON real via OCR hover badge (`_read_don_active`) e usa esse valor como ground truth, sobrescrevendo o acumulado.

**Bug 4 — Triggers ignorados (448 cartas afetadas)**
Quando uma carta de vida era revelada com Trigger, apareciam dois botões `Use Trigger Effect` / `No Trigger Effect`. O bot sempre clicava `No Trigger Effect`.
Fix: nova função `_is_trigger_step()` faz OCR rápido do botão TOP e checa se contém "trigger" sem "no". Nova função `_should_use_trigger(gs)` lê o nome da carta via preview OCR, busca no effects_db os steps do trigger, e decide: triggers de ko/bounce/draw/buff → usa sempre; trash da mão → só usa se tiver mão; default → usa. Integrado em: loop principal (dois botões fora da Main Phase), `_handle_prompts`. Logs: `T+` (usou) ou `T-` (não usou).

---

## 2026-07-03 (61) - Claude

### Item 3: steps do on_play guiam seleção de alvos nos prompts

**Motivação**: `resolve_prompt_choice` escolhia alvos de forma genérica (maior board_value no campo oponente). Com `action_system.py` como referência, percebemos que cada step de efeito tem filtros precisos (cost_lte, rested_only, power_lte...) que determinam quais alvos são válidos. Extraímos essa informação do nosso `card_effects_db.json` existente.

**Mudanças em `sim_bridge.py`**:
- `get_card_on_play_steps(card_code)` — devolve lista de steps do on_play do effects_db
- `_step_matches_zone(step, zone)` — heurística: o step corresponde à zona OCR detectada?
- `_choose_opp_target_filtered(candidates, step)` — filtra alvos oponente por cost_lte/cost_eq/rested_only/power_lte; para `bounce` prefere maior custo, para `ko` prefere maior ameaça
- `resolve_prompt_choice` agora aceita `steps: list[dict]` — se o step matchado tiver filtros, aplica antes do fallback genérico; se nenhum alvo válido sobrar, retorna `click_button` (efeito opcional/sem alvo)

**Mudanças em `bot_optcgsim.py`**:
- `_resolve_post_deploy(card_code=None)` — carrega on_play steps do bridge e repassa para `_resolve_prompt_with_engine`
- `_try_deploy_card(card_code=None)` — recebe e passa o code da carta deployada
- `_execute_engine_action` — passa `card_code=code` para `_try_deploy_card`
- `_resolve_prompt_with_engine(on_play_steps=None)` — passa steps para `resolve_prompt_choice`

**Efeito prático**: ao jogar uma carta como Brook (on_play: `ko opp_character cost_eq=0`), o bot agora só clica em personagens do oponente com custo 0, em vez de clicar no mais forte. Se não houver, retorna `click_button` (cancela).

---

## 2026-07-03 (60) - Claude

### Item 1: eventos faltantes do log em apply_log_delta

Usando os templates `Log.*` do `TRANSLATION.txt` do simulador, adicionamos eventos que antes eram ignorados:

- **`SelfToHand`** `Return $2 to Hand`: carta nossa voltou da field/trash para a mão (`needs_hand_rescan=True`)
- **`Destroyed`** `$1 Destroyed`: alias do K.O., remove do campo e vai pro trash (juntado ao elif de K.O.)
- **`Deploy from Trash`** / **`Deploy from Deck`**: tratados separados do deploy da mão (não tenta remover da mão)
- **`ActionActivateDon`** `Activate #1 Don`: DON ativado (fim de turno oponente) → `don_available += N`, `don_rested -= N`
- **`DonMinus`** `Minus #1 Don`: DON removido permanentemente por efeito do oponente
- **`RestDon`** `Rest #1 Don`: agora move `don_available→don_rested` corretamente (antes só subtraía)
- **`SetOtherRest`** `Rest $2`: marca `card.rested = True` no personagem do campo
- **`SetActive` / `SetOtherActive`**: marca `card.rested = False` no refresh/reativação
- **`Attack` attacking**: marca atacante como `card.rested = True`
- **`just_played = True`** no Deploy: personagens recém-entrados ficam marcados (sem Rush não atacam)
- Fix colateral: `'Draw ... Card'` agora exclui `'from'` para não conflitar com `DrawFromTrash`
- Fix: `'Trash'` check agora exclui `'Draw'` e `'from Trash'` para não comer saques do trash

### Item 2: pré-validação em sim_bridge.py antes de executar ação

Nova função `can_execute_action(action, gs) -> (bool, str)` em `sim_bridge.py`:
- **play**: checa `don_available >= cost`, carta na mão, `_sim_x > 0`
- **attack**: checa carta no campo, `not rested`, `not just_played` (sem Rush)
- **activate**: checa carta no campo (exceto LEADER/STAGE)

Integrada no loop principal de `bot_optcgsim.py` antes de `_execute_engine_action`:
- Se `PRE-FAIL`: para play → remove da mão (engine não re-propõe); para attack → encerra ações do turno
- Loga `[PRE-FAIL] TIPO código: motivo` para diagnóstico

Também removida linha órfã `_log_lines_seen[:] = _read_log_lines()` que ficou da refatoração anterior.

---

## 2026-07-03 (59) - Claude

### Refatoração: leitura direta do arquivo .log (abandona OCR do painel de log)

**Motivação**: OCR do painel esquerdo era impreciso, lento e só via as últimas linhas visíveis. O OPTCGSim escreve um arquivo `.log` em `CombatLogs/AutoSaved/` com todo o histórico da partida em tempo real.

**O que mudou em `bot_optcgsim.py`**:
- Removido: `LOG_BBOX`, `_read_log_lines()`, `read_log_delta()` via OCR, import `ImageOps`
- Adicionado: `COMBAT_LOG_DIR`, `_current_log_file`, `_log_file_offset`, `_our_name`, `_opp_name`, `_log_search_after`
- `_find_current_log()`: acha o `.log` mais recente criado após o reset da partida
- `_detect_names_from_log()`: detecta nome do jogador local via `"NAME Has Connected"` no cabeçalho
- `read_log_delta()`: lê bytes novos do arquivo por offset, filtra linhas `RZ1|` (protocolo de máquina)
- `_codes_from_log_line()`: extrai codes do formato `<link="CODE">` (e fallback `[CODE]`)
- `apply_log_delta()`: adicionado parser de **snapshots completos** emitidos após cada turno:
  - `[NAME] Hand: [CODE1,CODE2,...]` → sync completo da mão (inclui `needs_hand_rescan=True`)
  - `[NAME] Board: [CODE1,...]` → sync do campo
  - `[NAME] Trash: [CODE1,...]` → sync do trash
  - `[NAME] Life: N` → sync de vida
  - Detecção `is_you`/`is_opp` agora usa `_our_name`/`_opp_name` em vez de `[You]`/`[Opponent]`

**Estado atual**: código salvo, sintaxe OK. **Não testado ainda em partida real** — próxima sessão deve rodar o bot e observar se os snapshots são lidos corretamente (procurar `[LOG] arquivo=...` no output).

**Atenção**: formato do snapshot no log real pode precisar de ajuste. Verificar arquivo `.log` gerado durante a partida para confirmar o padrão exato de `Hand:`, `Board:`, `Trash:`, `Life:` (pode ser diferente do esperado — ver log de 2026-07-03T13.28.12.log como referência).

---

## 2026-07-03 (58) - Claude

### Bug crítico resolvido: posições stale causavam F em cascata

**Sintoma observado**: bot fazia muitos `F(código)` seguidos mesmo com DON suficiente — visualmente parecia "só passar o mouse e passar a vez".

**Causa raiz**: após um deploy bem-sucedido, o código filtrava `hand_cards` mas mantinha os `_sim_x` antigos. O OPTCGSim reposiciona as cartas restantes ao retirar uma, então as posições x ficavam stale. O bot clicava no lugar errado → simulador não abria Deploy prompt → `_try_deploy_card=False`.

**Fix** (`bot_optcgsim.py` ~linha 1186): após cada play bem-sucedido, chama `scan_hand()` + `bridge.sync_hand()` para obter posições frescas antes da próxima ação.

**Investigação via `validators.py`**: confirmado que a validação do engine está correta — o problema NÃO era custo de DON, era posição visual stale.

---

## 2026-07-03 (57) - Claude

### Fixes desta sessão (rodada de observação)

**`bot_optcgsim.py` — `_read_prompt_text` filtra lixo OCR**
- A segunda bbox `(930,490,1275,610)` lia arte de carta durante o jogo normal e gerava texto garbage ("se oe oe al: Xt - on yeaa")
- Fix: só inclui o texto de uma bbox se contiver pelo menos 1 palavra-chave de prompt (`_PROMPT_KEYWORDS` regex). Elimina ruído sem precisar remover a bbox útil para Blocker/Counter Step.

**`sim_bridge.py` — `resolve_prompt_choice` dois fixes**
- `own_field` com `gs.field_chars` vazio → antes retornava `None` (sem intent); agora retorna `click_button/main` ("no own chars")
- `"Use Card Action"` e `"Cancel"` adicionados em `_CONFIRM_KWS` → clica botão principal em vez de retornar None

---

## 2026-07-03 (56) - Claude

### Fixes desta sessão

**`sim_bridge.py` — `_prompt_zone`**
- "Select 1 More Friendly Targets" agora mapeia para `own_field` (regex expandido para incluir "friendly" e "target")

**`bot_optcgsim.py` — trash zone handler**
- Constantes: `TRASH_P2 = (863, 634)`, `TRASH_VIEW_Y = 550`, `TRASH_VIEW_XS = [120,195,265,335,395]`, `TRASH_ARROW_R = (427, 550)`
- Nova função `_click_card_in_trash_view(target_code)`: abre trash via clique em `TRASH_P2`, hover-scan cada posição na row y≈550, lê preview para identificar code, clica o alvo; pagina com seta direita até 3x; fallback: clica primeira posição
- `_execute_prompt_intent`: novo branch `zone == 'trash'` → chama `_click_card_in_trash_view`

**`bot_optcgsim.py` — botão extra y≈515 (multi-efeito Activate:Main)**
- `_click_activate_button` verifica pixel em y≈515 antes do top normal (y≈578) — cobre cartas com 2 opções de efeito como Kouzuki Oden ("Attach All Active Don" / "Action:(3)...")

### Pendências abertas
- **Confirmar `TRASH_P2 = (863, 634)`**: rodar bot e mandar screenshot quando trash precisar ser aberto para calibrar posição exata
- **Confirmar y=515 para botão extra do Oden**: verificar após teste se o pixel detecta corretamente
- **OP13-082 deploy com 7 cartas**: posição 282 falha consistentemente — investigar hitbox da mão cheia
- **Trigger Step**: após dano de ataque, o trigger step pode pedir interação — não mapeado ainda
- **Rotacionar chave Supabase** antes de deploy público (pendência de segurança)

---

## 2026-07-03 (55) - Claude

### Observação arquitetural (IMPORTANTE — nunca violar)

> **O Engine é o cérebro. O Bot é os olhos e as mãos.**

- **Bot (`bot_optcgsim.py`)**: só lê a tela (OCR, scan de cartas/campo), converte em dados estruturados e clica nos botões. Não toma decisões de jogo.
- **Engine (`decision_engine.py` via `sim_bridge.py`)**: recebe o `GameState` montado pelo bot e decide qual ação tomar.
- **Regra**: nunca implementar lógica de "qual carta jogar", "qual alvo atacar" ou "qual carta descartar" no bot. Toda decisão vai para o engine. O bot apenas executa a intenção devolvida.
- Isso evita o problema de ter dois motores divergindo. O `sim_bridge.py` é a ponte: recebe dados visuais do bot → alimenta o engine → devolve intenção clicável.

### Fix aplicado nesta sessão
- **Loop infinito `S(play:OP14-096)`**: quando um `play` estava em `used_engine_actions` e o skip disparava, o `continue` re-chamava o engine sem remover a carta de `gs.hand`, causando loop eterno.
- Fix: ao skippar um `play`, o bot agora remove a carta de `gs.hand` localmente (`gs.hand = [c for c in gs.hand if c is not skip_card and c.code != skip_code]`) antes do `continue`, quebra o loop.
- Arquivo: `scriptis_da_ia/bot_optcgsim.py` (~linha 1038).

### Problema aberto: bot não joga cartas (engine parece não funcionar)
Sintoma reportado: bot roda mas não executa plays. Hipóteses prováveis:

1. **`gs.hand` vazio quando engine é chamado** — `sync_hand()` no bridge pode não estar sendo chamado antes de `choose_action()`, ou o scan visual retorna lista vazia.
2. **`gs.don_available` = 0** — DON não está sendo sincronizado corretamente do estado visual para o `GameState` antes da chamada ao engine.
3. **Engine retorna `None`** — `_generate_and_score_actions` não encontra ação viável (score < 0) porque o `GameState` está incompleto (sem mão, sem DON, turn=0).
4. **`hand_x` não encontrado** — `_execute_engine_action` acha action de `play` mas `hand_cards` visual não tem o código da carta escolhida pelo engine (mismatch entre código no banco e código escaneado pela OCR).

### Análise real do log (3 partidas rodadas)
- **O engine funciona**: DON e hand estão sendo sincronizados corretamente. O engine propõe ações válidas e o bot executa: OP05-089, OP14-096, OP13-098, OP01-074, OP13-086 foram jogados com sucesso.
- **`_try_deploy_card=False`** ocorre quando o simulador NÃO abre o prompt Deploy/Cancel após o clique. Dois padrões:
  1. **`OP13-082` sempre falha** (hand_x=282) — provável regra do jogo que o engine não modela. O sim verifica uma condição de jogo que bloqueia o deploy silenciosamente.
  2. **`OP14-096` falha às vezes** (hand_x=317 falha, hand_x=282 funciona mesmo turno seguinte) — posição stale em `hand_cards`; a carta estava na posição 317 durante o scan mas o clique não acertou o hitbox.
- **`[fim detectado]` após OP13-086** — parece CORRETO: Imu (OP13-086) tem efeito que pode finalizar o jogo (DON explode para 7+), o simulador encerrou a partida.
- **Fix aplicado**: após `F(code)` (deploy falhou), `scan_hand()` é chamada imediatamente para garantir posições frescas antes da próxima tentativa.

### Cards identificados e fluxo de prompts (imagens vistas)
- **OP13-082 (Five Elders)** — CHARACTER 10/12000 com `Activate:Main`: rest 1 DON + trash 1 da mão → trash TODOS os personagens do campo → jogar até 5 [Five Elders] do trash. O deploy (custo 10) deveria funcionar normalmente; as falhas provavelmente são posição stale (282 com 7 cartas na mão). Após o activate, sequência de prompts: DON select → trash mão → trash personagens próprios → escolher Five Elders do trash.
- **OP13-086 (Saint Shalria)** — CHARACTER 1/0 Counter+1000 com `On Play`: olhar 3 cartas do topo → revelar até 1 [Celestial Dragons] → adicionar à mão → trashar o resto → trashar 1 da mão. Após o deploy, sequência de prompts: escolher Celestial Dragons (ou confirmar) → trash restantes → trash 1 da mão.

### Princípio arquitetural aplicado nos prompts (IMPORTANTE — não reverter)
O bot NÃO deve ter lógica por carta ("if five elders, do X"). Ele lê a tela e identifica
genericamente ZONA + AÇÃO + CONTAGEM a partir do texto OCR. O engine/bridge decide o que clicar.

### Mudanças aplicadas
- `sim_bridge.py`: `resolve_prompt_choice` reescrito com parser genérico (`_prompt_zone` + `_prompt_count`).
  Detecta por estrutura do texto, sem mencionar nenhuma carta:
  - zona `don` → `click_don`; zona `trash` → confirma (bot não escaneia trash ainda)
  - zona `revealed` → confirma; zona `hand` → engine escolhe pior carta
  - zona `opp_field` → engine escolhe maior valor; zona `own_field` → engine decide
  - count `0` → confirma sem escolha
- `bot_optcgsim.py`: `_execute_prompt_intent` trata `click_don` → clica `DON_P2_HOVER`
- `bot_optcgsim.py`: `_resolve_post_deploy` de 15 → 25 iterações

### Mapeamento de UI obtido por screenshots (partida observada)
- Botão `main` em y≈638 cobre: "No Blocker", "Resolve Attack", "Return Cards to Deck", "Choose 0 Targets"
- "Blocker Step" / "Counter Step" textos aparecem em y≈490–610 (ACIMA do bbox antigo)
- Trash P2: clicável em ~x=863, y=633 no board; abre visualização **acima da mão**
- Setas scroll da mão (mão cheia): esquerda ~x=83, direita ~x=427, y≈553

### Sequência de ataque (novo conhecimento)
Quando oponente ataca: Blocker Step → Counter Step → (Trigger Step se dano)
- Blocker Step: bot clica "No Blocker" (main button) — por ora não bloqueia
- Counter Step: bot verifica gs.hand por counter cards; se tiver joga o melhor, senão "Resolve Attack"

### Mudanças implementadas
- `apply_log_delta`: rastreia cartas para `gs.trash` via log ("Discard [CODE] for Counter", "Trash [CODE]", "K.O.")
  — sem precisar de scan visual do trash
- `PROMPT_TEXT_BBOXES`: adicionado bbox (930, 490, 1275, 610) para capturar textos de fase mais altos
- `_prompt_zone`: zonas "blocker" e "counter" adicionadas
- `resolve_prompt_choice`:
  - zone "blocker" → "No Blocker" (main)
  - zone "counter" → engine escolhe melhor counter da mão; senão "Resolve Attack"
  - zone "trash" → engine escolhe maior board_value de `gs.trash` (rastreado pelo log)

### O que ainda falta
- **Clicar carta do trash** (zona "trash"): `_execute_prompt_intent` recebe `zone="trash"` mas não sabe onde clicar visualmente — o trash precisa ser aberto (clicar em x=863, y=633) e então as cartas ficam acima da mão. Implementar scan do trash aberto.
- **Deploy de OP13-082 com 7 cartas na mão**: posição 282 pode estar fora do hitbox. Investigar.
- **Counter step**: bot hoje joga o counter de maior valor mas não avalia se o ataque vale ser bloqueado. Lógica futura: comparar poder do ataque vs vida restante.

---

## 2026-07-03 (54) - Codex
**PROMPT_TEXT_BBOX calibrado em prompt real**

### Feito
- Novo script: `scriptis_da_ia/calibrar_prompt_bbox.py`.
- Ele nao clica e nao roda partida; apenas captura a tela atual, testa candidatos de bbox, salva crops e imprime OCR.
- Saida em: `scriptis_da_ia/_debug_prompt_bbox/`.
- `PROMPT_TEXT_BBOX` em `bot_optcgsim.py` atualizado para `(915, 500, 1265, 585)`.

### Resultado da calibracao real
- Tela do OPTCGSim estava em prompt textual.
- Melhor candidato: `prompt_text_wide = (915, 500, 1265, 585)`.
- OCR lido exatamente:
```
Select 1 Cards to Trash
```
- O bbox antigo `(930, 445, 1240, 620)` misturava preview da carta e leu principalmente `Saint.Marcus.Mars`, portanto estava alto demais.
- Segunda leitura em outro prompt mostrou:
```
Choose 0 Enemy Characters
```
- Esse texto fica mais baixo; `bot_optcgsim.py` agora usa `PROMPT_TEXT_BBOXES` com:
  - `(915, 500, 1265, 585)` para prompts altos;
  - `(910, 500, 1265, 690)` para prompts baixos.
- `sim_bridge.resolve_prompt_choice()` agora trata `Choose 0/Select 0 ... Character` como `click_button` sem inventar alvo, e aceita `enemy` como sinonimo de oponente.

### Como recalibrar se a UI mudar
1. Deixar o OPTCGSim visivel exatamente em um prompt textual.
2. Rodar:
```
python scriptis_da_ia\calibrar_prompt_bbox.py
```
3. Conferir `overlay.png` e os crops em `_debug_prompt_bbox`.
4. Copiar o melhor bbox para `PROMPT_TEXT_BBOX` em `bot_optcgsim.py`.

---

## 2026-07-03 (53) - Codex
**Prompt resolver: bot classifica OCR, engine escolhe o clique**

### Decisao arquitetural
- O bot NAO deve decidir "melhor alvo", "pior carta para trash" ou "melhor carta para add".
- O bot so deve:
  1. ler/classificar o prompt visual do OPTCGSim;
  2. pedir ao bridge/engine a intencao clicavel;
  3. clicar carta/botao.
- Isso evita criar um segundo motor dentro do bot.

### Mudancas
- `sim_bridge.py`
  - Novo `resolve_prompt_choice(gs, opp_gs, prompt_text)`.
  - Usa heuristicas ja existentes do engine:
    - `DecisionEngine.choose_to_trash(gs.hand)` para discard/trash de mao.
    - `choose_highest_board_value()` para alvos de personagem proprio/oponente.
  - Retorna intencoes simples: `click_card` com `zone/code/name` ou `click_button`.
  - Trata `Trash Remaining/Rest` como confirmacao de botao, nao como descarte de mao.
- `bot_optcgsim.py`
  - Novo `PROMPT_TEXT_BBOX` e `_read_prompt_text()`.
  - Novo `_resolve_prompt_with_engine(...)`.
  - `_resolve_post_deploy()` tenta resolver prompt via engine antes de clicar botao unico.
  - Loop pos-ataque tambem tenta resolver prompt via engine antes de clicar botao.
  - `play`/`activate` passam `gs/opp_gs/hand_cards/board_cards/opp_board_cards` para o resolvedor.

### Validacao
- `python -m py_compile scriptis_da_ia\bot_optcgsim.py scriptis_da_ia\optcg_engine\sim_bridge.py`

### Risco restante
- `PROMPT_TEXT_BBOX = (930, 445, 1240, 620)` e estimado; precisa calibrar com screenshot real do prompt.
- O resolvedor ainda cobre classes genericas iniciais: trash de mao, trash de personagem proprio, escolher personagem proprio/oponente e confirmacoes. Nao cobre ainda prompts de cartas reveladas com coordenadas proprias fora de mao/campo.

---

## 2026-07-03 (52) - Codex
**Auditoria estatica: bot executava mal activate/attach/attack mesmo com engine certo**

### Achados corrigidos sem rodar simulacao
1. **Campo visual cego**: no inicio da Main Phase o bot fazia `scan_hand()` e zerava `board_cards`. Resultado: engine podia escolher `activate`, `attach_don` ou ataque com personagem, mas o bot nao tinha coordenadas confiaveis para clicar.
   - Fix: scan leve `scan_hand()` + `scan_board_p2()` + `scan_opp_board()` no inicio da Main Phase; sincroniza `gs.field_chars` e `opp_gs.field_chars` no bridge.
2. **Ataque ignorava alvo do engine**: `attack` em personagem inimigo podia virar fallback para leader se nao achasse a fonte.
   - Fix: `_execute_engine_action()` agora usa `action[3]`/`action[4]`, arrasta da fonte real para leader ou para o alvo personagem real. Se nao souber posicao, falha fechado em vez de atacar alvo errado.
3. **Duplicatas com mesmo code**: activate/attack/attach podiam clicar a primeira copia do codigo, nao a copia escolhida pelo engine.
   - Fix: preferir `_sim_x/_sim_y` gravado pelo `sync_field`; `_action_once_key()` inclui posicao quando existe.
4. **Activate marcava tudo como rested**: `_consume_engine_action_locally()` marcava `activate` como rested sempre. Para Imu (`OP13-079`), Activate:Main compra carta/trasha Celestial Dragon e NAO resta o leader; isso podia impedir ataque depois.
   - Fix: activate so marca rested se o custo em `card_effects_db.json` inclui `rest_self`, `rest_self_and_trash_hand` ou `rest_self_and_leader_or_stage`; tambem marca `_am_used_turn = gs.turn`.
5. **Prompt unico clicava coordenada errada**: em alguns handlers, quando so havia botao de cima, o bot ainda clicava `C_BTN_MAIN`.
   - Fix: helper `_click_detected_button(top, main)` clica no botao realmente detectado.
6. **Campo apos play ficava stale**: apos jogar personagem, o estado local tinha a carta, mas `board_cards` nao tinha coordenada visual.
   - Fix: apos `play`, reescaneia `scan_board_p2()` e sincroniza campo.

### Validacao
- `python -m py_compile scriptis_da_ia\bot_optcgsim.py scriptis_da_ia\optcg_engine\sim_bridge.py`

### Risco restante
- Ainda sem teste real no simulador por decisao do usuario para poupar creditos.
- Efeitos On Play que exigem selecao de alvo especifico continuam dependendo do comportamento generico dos prompts; a proxima auditoria barata deve procurar cartas do deck Imu com On Play/Activate que abrem selecao de alvo e mapear se o bot precisa clicar alvo, nao apenas confirmar botao.

---

## 2026-07-03 (51) - Codex
**Fix residual: OP13-086 nao causa fim de jogo; resolver prompt unico pos-deploy**

### Achado
- `AGENTS.md` nao existe na raiz do repo; busca por `AGENTS.md/agents.md/.agents/**` nao retornou arquivo.
- `main` esta alinhada com `origin/main` em `498f3b7`.
- `OP13-086` = Saint Shalria. Efeito: olha 3 do topo, adiciona 1 Celestial Dragons, trasha o resto e trasha 1 da mao. Nao causa dano massivo; a hipotese de fim correto por dano cai.
- Regressao encontrada: em `115acd2`, `_resolve_post_deploy()` resolvia modais On Play de 1 botao e parava ao ver 3 botoes unicos consecutivos. No `HEAD`, ela parava imediatamente em qualquer botao unico, deixando o modal da OP13-086 para o loop principal, que em `in_main=True` tenta continuar via engine.

### Mudanca
- `scriptis_da_ia/bot_optcgsim.py`: restaurei `_resolve_post_deploy()` para clicar prompts unicos pos-deploy ate 2 vezes e parar no 3o botao unico estavel (= provavel End Turn), mantendo pass/counter em prompts de 2 botoes.

### Validacao
- `python -m py_compile scriptis_da_ia\bot_optcgsim.py`

### Proximo teste sugerido
- Rodar um teste curto, com simulador ja na tela de selecao de deck:
```
python scriptis_da_ia\bot_optcgsim.py --deck "Imu" --partidas 1 --timeout 90
```
- Esperado: apos `E(play:OP13-086)`, o bot deve resolver prompts On Play e nao travar/finalizar imediatamente por `[fim detectado]`.

---

## 2026-07-03 (53) - Claude
**Corrige bbox do OCR de prompt**

Problema: `PROMPT_TEXT_BBOXES` apontava para y=500-585/690, que captura
o texto do card preview (Saint Marcus Mars etc.) junto com o prompt.
OCR retornava lixo: `'<i 5 es ee oe = ye ee per wae Yom`.

Diagnosticado via `_debug_prompt_bbox/full.png`: caixa de prompt fica
em y≈615-673, x≈935-1270 (fundo bege, fundo-direita da tela).

Fix: `PROMPT_TEXT_BBOXES = [(930, 608, 1275, 682)]` — apenas a caixa
do prompt, sem o card preview acima.

`calibrar_prompt_bbox.py` atualizado com novos candidatos centrados
na posicao correta.

---

## 2026-07-03 (52) - Claude
**Fix DON apos play e fallback errado quando deploy falha**

### Problema identificado no log
- `[PLAY] _try_deploy_card=False` repetido para mesma carta (ex. OP14-096):
  engine propunha carta com custo > DON disponivel porque `gs.don_available`
  nao era decrementado apos play bem-sucedido anterior.
- Apos deploy falhar, bot caía direto no fallback `A` (ataca lider) em vez
  de tentar outra acao do engine.

### Fixes
1. **DON decrement apos play**: `gs.don_available -= played.cost` imediatamente
   apos `_try_deploy_card=True`. Imprime `[DON-N=M]`.
2. **`_action_once_key` agora inclui 'play'**: permite rastrear deploys falhos
   em `used_engine_actions`.
3. **Skip de play falho**: quando `once_key in used_engine_actions` para 'play',
   faz `continue` (engine propoe proxima acao) em vez de encerrar o turno.
4. **Fallback de deploy falho**: quando `_execute_engine_action` retorna False
   para 'play', adiciona codigo a `used_engine_actions` e `continue`; fallback
   de ataque so dispara quando nao ha mais acoes de play validas.

### Proximos itens
- OCR do prompt (`PROMPT_TEXT_BBOXES`) esta lendo area errada (retorna lixo).
  Calibrar as coordenadas com `calibrar_prompt_bbox.py`.
- [fim detectado] apos OP13-086 pode ser fim de jogo legitimo (On Play poderoso).
  Verificar se o jogo realmente termina ou se e timeout de animacao.

---

## 2026-07-03 (51) - Claude
**Prompts genéricos + Activate:Main**

### Mudancas
**sim_bridge.py — resolve_prompt_choice:**
- `_normalize_prompt()`: corrige OCR antes de parsear (Tras->Trash, Chose->Choose, Enemy->Opponent, "1 Cards"->"1 card", etc.)
- Novos padroes: "place on top/bottom", "look at", "add to hand", "up to N character", "life card"
- "choose 0/select 0" passa direto sem exigir "character" no texto
- Fallback explicito quando nao ha personagens (opp sem chars -> click_button)

**bot_optcgsim.py — _resolve_prompt_with_engine:**
- Sempre imprime OCR + intencao (antes so imprimia quando resolvia)

**bot_optcgsim.py — _execute_engine_action activate:**
- Imprime [ACT] code/type/clicked e buttons para diagnostico
- Se board_cards vazio e carta nao e LEADER/STAGE: faz rescan do campo antes de clicar
- Se nenhum botao apos clicar carta: deseleciona e retorna False (nao travar)

### Proximo passo
- Rodar partida e verificar se P[...] aparece em prompts e [ACT] em activate
- Se "activate" do engine nunca dispara, checar scoring em decision_engine.py
- Resolver [fim detectado] pos-End Turn (MAX_IDLE=50 ainda pode ser pouco)

---

## 2026-07-03 (50) - Claude
**4 fixes aplicados — bot joga e ataca via engine**

### Fixes desta sessão
1. **SelectDeck por teclado** (P1=True,P2=True): `_select_deck_dropdown` usa `Home`+`Down`×N+`Enter` em vez de OCR. Funcionou nos testes 24-27.
2. **attacked=True** apos engine attack: evita tentativa dupla via fallback A.
3. **DON_SYNC removido** apos play: log captura DON corretamente (sem sobrescrever com 0).
4. **gs.hand atualizado** imediatamente apos E(play): remove a carta jogada sem depender do log. Fix critico — engine repetia a mesma carta.
5. **idle_ticks=0** apos E(action) e apos End Turn: animacoes longas nao trigam fim detectado.
6. **Post-attack prompt handler**: apos E(attack), 0.8s + loop de 15x resolve counter/trigger do oponente.
7. **MAX_IDLE=50** (15s): aguarda animacoes On Play longas.

### Resultado (test27)
```
SelectDeck(P1=True,P2=True)
M[DON=2] → E(play:OP13-086) → E(attack:OP07-019) → .
[fim detectado]   <- pos-ataque, provavel fim de jogo ou trigger longo
```

### Problema residual: [fim detectado] apos primeiro ataque
Consistente nos testes 25-27. Pos-ataque, nao aparecem botoes por 15s.
Causas possiveis (a investigar):
- OP13-086 tem On Play que causa dano massivo → jogo acaba em turno 1 (correto?)
- Trigger de vida do P1 tem animacao > 15s (aumentar MAX_IDLE para 100?)
- Post-attack prompt handler resolveu prompts mas em seguida end-turn click
  causou estado inesperado no jogo

### test28: [fim detectado] logo apos Start
Estado do simulador provavelmente era de tela de resultado anterior.
Bot precisa que o simulador esteja na tela de selecao de deck ao iniciar.

### Proximo passo
- Checar o que OP13-086 faz (se faz dano em On Play, o jogo pode estar terminando corretamente)
- Se necessario: aumentar MAX_IDLE para 100 (30s) para trigger animacoes
- Garantir que o simulador reseta para a tela correta entre partidas (ou aguardar manualmente)

---

## 2026-07-03 (49) - Claude
**Engine jogando cartas: fix probe sem deploy + DON correto**

### Bug corrigido
O probe anterior deployava uma carta (gastando todo DON) e depois o `_read_don_active`
sobrescrevia o DON rastreado pelo log com 0. Engine sempre via `don=0` e nunca propunha plays.

### Fix em 2 partes
1. **`_probe_main_phase(x)`** (nova funcao): detecta Main Phase clicando carta e
   **cancelando** o prompt (C_BTN_MAIN), sem deployar nada. DON nao e gasto.
2. **Remove `_read_don_active` do probe**: o log ja captura corretamente o DON ganho
   via `[DON+N=M]`. Printa `[DON=N]` mostrando o valor real ao engine.

### Resultado (test23)
```
M[DON+1=1][DON+2=3][DON+2=5][DON=5]  <- engine ve 5 DON
[ENG] 7 acoes | hand=7 don=5 turn=4   <- 7 opcoes!
E(play:OP13-086)                       <- ENGINE JOGOU CARTA ✅
```

### Problema residual
Apos E(play:OP13-086) → [fim detectado]. Provavelmente On Play effect de OP13-086
gerou prompt que o bot nao tratou. `_resolve_post_deploy` tem 10x0.3s = 3s de janela;
se o prompt demora mais, o bot volta pro loop sem resolver.

### Proximo passo
- Investigar OP13-086 (qual efeito On Play?) e ver se _resolve_post_deploy precisa
  de mais iteracoes ou de um check no loop principal apos action_executed
- DON_SYNC apos engine play ainda usa _read_don_active (retorna 0 por OCR); avaliar
  se deve ser removido tambem (o log pode capturar Rest Don apos deploy)

---

## 2026-07-03 (48) - Claude
**Fix: engine play actions falhavam por DON desatualizado apos probe deploy**

### Causa raiz confirmada
Apos o probe (`_try_deploy_card` na deteccao de Main Phase), o jogo gastava DON mas
`gs.don_available` nao era decrementado. Engine via don=5, propunha plays, mas o jogo
rejeitava (`_try_deploy_card=False`) porque DON real = 0.

Confirmado no log de test20:
```
[PLAY] code=OP05-089 hand_x=212 vis=[..., ('OP05-089', 212)]
[PLAY] _try_deploy_card=False   <- jogo sem DON, engine nao sabia
```

### Fix implementado (`bot_optcgsim.py`)
1. **Probe**: apos deploy do probe, aguarda 0.4s e le DON real da tela via
   `_read_don_active(DON_P2_HOVER)` -> `gs.don_available = don_real`. Imprime
   `[DON_SYNC=N]` para debug.
2. **Engine play**: apos `E(play:...)` executado, le DON real da tela (mesmo mecanismo)
   antes de rodar o delta do log. Engine da proxima iteracao ve DON correto.

### Estado atual
- Engine propoe play e attack com DON/turno corretos
- `[DON_SYNC=N]` aparece no log apos cada deploy (probe e engine)
- Proximo passo: testar em partida real e confirmar `E(play:...)` executando com sucesso

---

## 2026-07-03 (47) - Claude
**Fix typos de regressao do Codex: pag.maouseDown/Up e amaount**

Codex (sessao 46) introduziu `pag.maouseDown()` e `pag.maouseUp()` em 3 lugares
(`_try_attack_leader`, `_try_attack_char`, `attach_don`) e `amaount` como nome de
variavel. Todos corridos para `mouseDown`/`mouseUp`/`amount` sem mudar logica.
Arquivo compila OK.

---

## 2026-07-03 (46) - Codex

**Bot OPTCGSim: selecao de deck validada, engine actions e limpeza ASCII**

### O que foi feito
- `bot_optcgsim.py` agora confirma P1/P2 no dropdown antes de iniciar a partida. Se a selecao visual nao bater com `--deck`, aborta e volta ao menu, evitando logs contaminados.
- `--timeout` foi exposto na CLI para testes curtos de automacao sem esperar partida completa.
- `_execute_engine_action()` passou a tratar tambem:
  - `activate` em leader/stage/personagem de campo
  - `attach_don` por drag do DON para leader/personagem
- No inicio da Main Phase, o bot volta a usar `full_scan(gs, opp_gs)` quando o bridge esta disponivel, para o engine ter mao/campo/DON.
- A condicao de chamada do engine deixou de depender de `hand_cards and gs.hand`; isso permite decisoes com campo/leader mesmo sem carta na mao.
- Adicionada trava local por turno para evitar repetir `activate`/`attack` da mesma carta quando OCR/log nao atualiza o estado rapido o suficiente.
- `bot_optcgsim.py` foi normalizado para ASCII para remover mojibake (`Ã`, `â`, `�`, etc.) que atrapalhava patches e revisao.

### Evidencias de teste
- `python -m py_compile scriptis_da_ia\bot_optcgsim.py scriptis_da_ia\optcg_engine\sim_bridge.py`
- `python scriptis_da_ia\bot_optcgsim.py --help`
- Testes manuais curtos com `--deck "Imu"` validaram:
  - `SelectDeck(P1=True,P2=True)`
  - log recente com `Imu` vs `Imu`
  - engine executando cartas reais, incluindo evento e `Bartholomew Kuma`

### Riscos / dividas
- A selecao do deck ainda depende de coordenadas e calibracao do scrollbar do dropdown do Unity. Agora falha fechado, mas ainda merece uma solucao mais robusta no futuro.
- A trava local de `activate/attack` e pragmatica. A solucao estrutural correta e o engine/modelo de turno entender "once per turn"/acao ja usada.
- `C_P2_STAGE = (765, 545)` e uma coordenada estimada; precisa validacao em partidas com stage/activate.
- `attach_don` foi implementado por drag visual, mas ainda precisa teste dedicado em partida.
- O `HANDOFF.md` antigo ainda contem mojibake em entradas anteriores; esta entrada nova ficou em ASCII para nao aumentar o problema.

---

## 2026-07-02 (45) - Claude

**Bot: fix modal On Play após deploy — `_resolve_post_deploy()`**

### Bug corrigido
`_handle_prompts()` saia imediatamente ao ver 1 botão (`else: return`). Quando uma carta tinha efeito On Play (ex: Electrical Luna OP08-036 "Rest 3 Don"), o modal ficava aberto indefinidamente. O bot ficava travado em `in_main=True` sem conseguir avançar.

### Fix em `bot_optcgsim.py`
- Nova função `_resolve_post_deploy()`: resolve botões pós-deploy com lógica de "consecutive single button counter"
  - 2 botões → clica C_BTN_MAIN (Pass/Counter)
  - 1 botão → clica (modal On Play) — mas para após 3 botões únicos consecutivos (= End Turn estável)
  - 0 botões → para
- `_try_deploy_card()` chama `_resolve_post_deploy()` em vez de `_handle_prompts()`
- `_handle_prompts()` inalterado (ainda usada em `_try_attack_*`)

### Resultado
`DA.DA.DA.DA.D` + "fim detectado" — 5 turnos, jogo encerra naturalmente.

### O que falta (itens restantes da sessão 44)
- Engine ainda raramente é usado (scan_hand após probe devolve [] se modal ainda abre) → engine path depende de hand_cards não-vazio
- Não ataca com personagens do campo, só com o leader
- `activate` e `don_attach` não implementados em `_execute_engine_action()`
- Probe tenta só x=107..247 (5 posições)

---

## 2026-07-02 (44) - Claude

**Bot: partida completa funcionando (5 turnos, DA.DA.DA.DA.DA.)**

### Bugs corrigidos esta sessão

1. **`_handle_prompts` clicava TOP em vez de MAIN** → trocado para C_BTN_MAIN (Pass/Skip) em todos os dois-botões durante jogo
2. **Engine `_generate_and_score_actions` travava infinitamente** → `choose_action()` em `sim_bridge.py` agora usa `threading.Thread(daemon=True)` com `t.join(timeout=4.0)` — retorna None em 4s sem bloquear
   - Tentativa com `ThreadPoolExecutor` falhou: o `with` block chama `shutdown(wait=True)` que trava junto com a thread presa
3. **`full_scan()` após deploy (~11s) causava atraso excessivo** → removida a chamada de `full_scan` imediatamente após deploy; bot usa `hand_cards=[], board_cards=[]` e o engine só é chamado se `hand_cards` não está vazio
4. **Segurança de loop infinito** → `actions_this_turn` + `MAX_ACTIONS_PER_TURN=6`: após 6 ações no mesmo turno encerra forçado (print "X")

### Resultado
Bot completa partida de ponta a ponta: `DA.DA.DA.DA.DA.` = 5 turnos de Deploy+Attack+EndTurn.
- Primeiro deploy na sonda da Main Phase (`D`)
- Ataca leader adversário (`A`)  
- Encerra turno (`.`)
- Detecta fim de partida → baixa log de combate → volta ao menu

### Estado atual
- `bot_optcgsim.py`: funcional, completa partidas
- `sim_bridge.py`: `choose_action()` com daemon thread (timeout 4s)
- Push pendente de HANDOFF

### O que falta / limitações conhecidas
- O engine é chamado apenas quando `hand_cards` não está vazio (nunca, pois removemos o full_scan após deploy) → bot joga só attack+endturn sem usar o engine de decisão
- Não ataca com personagens do campo, só com o leader
- Não implementa `activate` nem `don_attach`
- Probe da Main Phase tenta as primeiras 5 posições da mão (x=107..247); se nenhuma carta acessível estiver nesses slots, o bot não entra em Main Phase e apenas encerra o turno
- Side panel do simulador abre esporadicamente (causa desconhecida, não impede o bot de funcionar pois End Turn pixel ainda detecta corretamente)

---

## 2026-07-02 (43) - Claude

**Bot: log delta para rastrear estado sem rescan constante**

### Problema resolvido
Rescan completo via hover+OCR após cada ação levava ~10s e travava o simulador. Solução: scan completo UMA VEZ no início da Main Phase, depois só lê o painel de log (esquerda) para atualizar o estado incrementalmente.

### Mudanças em `bot_optcgsim.py`
- `HOVER_WAIT`: 0.65s → 0.30s (scan inicial mais rápido)
- `read_log_delta()`: OCR do painel de log (bbox 135,210,390,475), texto claro em fundo escuro (inverte antes do OCR), retorna só linhas novas desde última leitura
- `apply_log_delta(gs, opp_gs, lines)`: parseia linhas e atualiza GameState:
  - `[You] Deploy X [CODE]` → remove de gs.hand, adiciona em gs.field_chars
  - `[Opponent] Deploy X [CODE]` → atualiza opp_gs.field_chars
  - `[You] Draw N Card` → retorna True (precisa rescan parcial da mão)
  - `[You] X: Rest N Don` → gs.don_available -= N
  - `K.O. [CODE]` → remove do campo correto
  - `hit for N damage` → atualiza gs.life ou opp_gs.life
- `full_scan()`: escaneia mão + campo P2 + campo P1 + DON — chamado UMA VEZ por Main Phase
- `scan_opp_board()`: novo, escaneia campo do P1 para estado inicial do oponente
- Loop principal: após cada ação, chama `read_log_delta()` + `apply_log_delta()` em vez de rescan completo. Só rescaneaia mão quando `apply_log_delta` retorna True (sacou carta)

### Estado atual
Código commitado, push pendente de atualizar este HANDOFF. Ainda não testado com simulador aberto nesta sessão.

### O que falta
- Testar o log delta rodando uma partida real e ver se o OCR do painel de log funciona bem (fundo escuro, texto pequeno)
- Calibrar bbox do log se necessário
- Implementar ações `activate` e `don_attach` em `_execute_engine_action()`

---

## 2026-07-02 (42) - Claude

**Bot OPTCGSim com engine real integrado**

### Contexto
Bot para jogar partidas Solo v Self no OPTCGSim usando o `decision_engine.py` real para decisões (não heurísticas).

### `scriptis_da_ia/bot_optcgsim.py` (reescrito completo)
- **Seleção de deck**: `--deck NOME` lista decks de `E:\Games\...\Decks\*.deck`, menu interativo se não passado
- **Engine integrado**: cria `OPTCGMatch(deck_tuple, deck_tuple)`, usa `state_b` como P2 (nós)
- **Leitura de estado** via hover+OCR:
  - `scan_hand()`: hover em y=648, x=107..410, step=35 → OCR nome/custo/power
  - `scan_board_p2()`: hover nas posições da character area P2 → OCR
  - `_read_don_active(hover_pos)`: badge "N(M)" → ativo = N-M
  - `_read_counter_badge(hover_pos)`: lê número de qualquer badge (deck, mão oponente)
- **Fluxo Main Phase**: detecta Main Phase clicando carta (se Deploy aparecer = Main Phase), sincroniza com `bridge.sync_hand/sync_field`, chama `bridge.choose_action()`, executa via `_execute_engine_action()`
- **Execução de ação**: `play` → clica carta na mão; `attack` → drag líder/char até P1; outros tipos retornam False (fallback para ataque com líder + End Turn)

### `scriptis_da_ia/optcg_engine/sim_bridge.py` (sem mudança nesta sessão)
- `choose_action(gs, opp_gs, match)` → engine decide melhor ação

### Posições mapeadas via hover (1366×768):
- DON P2: hover (495, 634) → badge "N(M)"
- DON P1: hover (865, 100) → badge "N(M)"
- Deck P2: hover (480, 545) → badge count = 6
- Deck P1: hover (870, 200) → badge count = 3
- Trash P2: hover (855, 640) → mostra preview topo do trash (Slam Gibson OP12-117)
- Mão P1 count: hover (250, 90) → badge count
- Life P2/P1: posições ainda não mapeadas precisamente (LIFE_P2_HOVER=(480,460) e LIFE_P1_HOVER=(463,210) são estimativas)

### O que falta:
- Mapear posições precisas de life P2 e P1 (o jogo estava turn 19 com P2 talvez com 0 vidas)
- Implementar ações `activate` e `don_attach` em `_execute_engine_action()`
- Testar bot rodando de verdade em uma partida do início

---

## 2026-07-02 (41) - Claude

**Importer de logs do simulador OPTCG (AutoSaved .log) → banco de logs**

### Contexto
Usuário tem simulador Unity local (`OPTCGSim.exe`) em `E:\Games\OnePieceSimulador\Builds_Windows\`.
Pasta `CombatLogs/AutoSaved/` tinha 31 logs `.log` de partidas reais humano vs humano — dados não importados ainda.

### `scriptis_da_ia/importar_logs_autosaved.py` (novo)
Parser de `.log` do AutoSaved → formato `logs/parsed/*.json` + atualiza `logs/index.json`.

**Formato do `.log` (texto com prefixo [jogador]):**
- Setup: líderes, quem escolheu 1º/2º, mão antes/depois do mulligan, se fez mulligan
- Ações: Deploy, Attach Don, attacking, hit for N damage, Concedes!
- Fim de turno: `End Turn` seguido de snapshot completo de ambos os jogadores
- Linhas `RZ1|...`: estado interno de posição de cartas (ignorado pelo parser)

**Detecção de vencedor (dois caminhos):**
1. `[player] Concedes!` → o outro jogador vence
2. Rastreamento de vida em tempo real via snapshots + "X hit for N damage" onde X é líder:
   - quando `tracked_life[victim] == 0` e recebe hit → hit fatal → outro jogador vence

**Formato de saída:** mesmo padrão que os JSONs do simulador, com campos extras:
- `meta.mulligan_p1/p2`: `{before: [...], after: [...], took_mulligan: bool}`
- `meta.source: "autosaved_log"`, `meta.original_file`

**Resultado:** 26/31 importados (5 ignorados: 4 com líderes não identificados por encoding, 1 muito curto). 
Vencedor detectado em ~18/26 (8 foram partidas abandonadas por desconexão sem "Concedes!" e sem hit fatal detectado).

### Próximos passos óbvios
- Jogar mais partidas no simulador → `CombatLogs/AutoSaved/` acumula → rodar importer
- `python importar_logs_autosaved.py "E:/Games/OnePieceSimulador/Builds_Windows/CombatLogs/AutoSaved"` (já pula logs existentes)
- Bot de decision support: monitorar o `.log` ativo em real-time e mostrar recomendação da IA no terminal

---

## 2026-07-02 (40) - Claude

**Validação de hand scoring via simulação (#1 #2) — endpoint /hand-stats + UI win rate brackets**

### Backend — `scriptis_da_ia/hand_scorer.py` (novo)
- Port Python da lógica `avaliarMao()` do TypeScript: `score_hand()`, `detect_archetype()`, `searcher_quality()`
- Mesmo sistema de modificadores por arquétipo (rush/aggro/control/ramp/midrange)
- `card_to_handcard()`: converte Card do engine → HandCard para scoring
- Detecta searcher via texto do card (look at the top / search your deck / look at up to)

### Backend — `scriptis_da_ia/api.py`
- Novo endpoint `POST /hand-stats` (aceita lista de CardEntry igual ao `/analyze`)
- Cria `InstrumentedMatch(OPTCGMatch)`: subclasse que captura `_opening_hand_a/b` pós-setup
- Carrega deck do usuário via `load_deck()` e até 8 oponentes de `decklists_raw.csv`
- Roda ~80 partidas (n_per_opp × len(opponent_pool)), alternando 1º/2º jogador
- Para cada partida: score a mão real capturada → registra se ganhou
- Agrega em 5 brackets fixos (Ruim/Abaixo da média/Médio/Bom/Excelente)
- Retorna `{archetype, n_games_ran, overall_win_rate, avg_hand_score, score_brackets, mulligan_threshold}`
- Threshold = max_score do último bracket com win_rate < 0.45

### Frontend — `src/app/analysis/page.tsx`
- Interfaces `HandStatsBracket` e `HandStats` declaradas ao nível de módulo
- Estado `handStats` + `handStatsLoading`; fetch `POST /hand-stats` no useEffect de análise
- Spinner "Simulando partidas vs decks de meta..." enquanto carrega (~30s)
- Seção "🎲 Validação por Simulação" (entre melhores mãos e plano de turnos):
  - Cards resumo: Win Rate Geral · Score Médio de Mão · Threshold de Mulligan
  - Barra por bracket: cor verde/amarelo/vermelho pelo win rate (≥55% / 45-55% / <45%)
  - Banner "limite mulligan" no bracket de threshold
  - Dica textual quando threshold está definido
- Fix: badge "6 cartas" do 2º jogador corrigido para "5 cartas"
- Timeout de 120s no fetch (partidas podem levar ~30-60s)

### Estado atual
- Zero erros TypeScript + ESLint (apenas warnings de `<img>` pré-existentes)
- `/hand-stats` funciona localmente; endpoint síncrono (~30-60s para 80 partidas)
- Feature #3 (turn plan real da simulação) decidido usar `/leader-stats` já existente em vez de dados de IA (dados humanos = ground truth mais confiável)

---

## 2026-07-02 (39) - Claude

**Plano de turnos em 2 colunas (1º/2º jogador) + heurística de vida como recurso**

### Frontend — `src/app/analysis/page.tsx`
- `gerarPlano()`: novo tipo `PlanoTurno` com `sugestao1/sugestao2` e `cartas1/cartas2` separados por posição
- Layout do plano em grid 2 colunas: esquerda = 1º jogador (laranja), direita = 2º jogador (azul)
- Cada turno tem sugestão e cartas específicas para a faixa de DON de cada posição
- `cartasLog()`: prioriza cartas dos logs reais para a faixa de custo de cada turno

### Heurística: vida como recurso (dica gameplay #1)
- Mão com 3+ counters e nenhuma ofensiva → penalidade "brick funcional" (`-25 × penT1Mult`)
- Deck aggro/rush com 3+ counters → penalidade extra de -12 (excesso de defesa passiva)
- Fundamentado na regra: "vida = recurso, não HP — em aggro você quer offensiva, não counters"

### Referência salva (local only, .gitignore)
- `_referencias/dicas_gameplay_optcg.md`: 7 dicas de gameplay com impacto mapeado nas heurísticas

---

## 2026-07-02 (38) - Claude

**Plano de turnos: DON!! correto + endpoint /leader-stats com dados reais de log**

### Backend — `scriptis_da_ia/api.py`
- Novo endpoint `GET /leader-stats?leader_name=<nome>` (busca parcial, case-insensitive)
- Lê `logs/index.json`, filtra logs onde o líder aparece (p1 ou p2)
- Para cada log encontrado, agrega ações `type=play` por turno do jogador com esse líder
- Retorna `{total_games, turns: {"1": [{card_code, card_name, count, pct}], ...}}`
- Usado pelo front para priorizar cartas reais de log no plano de turnos

### Frontend — `src/app/analysis/page.tsx`
- `gerarPlano()` refatorado: novo tipo `PlanoTurno` com `don1`/`don2` separados
- Curva de DON!! correta: 1º → T1=1, T2=3, T3=5, T4=7 DON!!; 2º → T1=2, T2=4, T3=6, T4=8
- Cartas do plano: se `leaderStats` tem dados para o turno, prioriza cartas mais jogadas nos logs; senão usa análise do deck
- Novo `useEffect` busca `/leader-stats` para o líder do deck ao carregar
- Estado `leaderStats` + badge "✦ N partidas reais no banco" quando API retorna dados
- UI do plano: bloco de DON split em dois (laranja=1º / azul=2º)
- Texto do subtítulo exibe a curva completa de ambas as posições

### Estado atual
- Zero erros TypeScript; servidor 3000 no ar
- `/leader-stats` funciona localmente; precisa do deploy Railway para o front em produção consumir

---

## 2026-07-02 (37) - Claude

**Fix /analysis: melhores mãos por posição (1º/2º jogador) + arquétipo do deck**

### Curva de DON corrigida
- 1º jogador: T1=1 DON (custo≤1), T2=3 DON (custo 2-3), T3=5 DON (custo 4-5)
- 2º jogador: T1=2 DON (custo≤2), T2=4 DON (custo 3-4), T3=6 DON (custo 5-6)
- Ambos compram 5 cartas no mulligan (o +1 do 2º é o draw do T1 dele, não da abertura)

### Separação 1º / 2º jogador
- UI exibe duas seções distintas (laranja / azul) com 3 melhores mãos cada
- Counter 2k vale +20 pra 2º jogador (vai levar 1º hit de qualquer jeito) vs +16 pra 1º
- 2 searchers no 2º jogador recebe bônus extra +12 (ramp de 2 DON T1 = joga + busca)

### Arquétipo detectado via heurística client-side
- `detectarArquetipo()`: classifica `rush / aggro / control / midrange / ramp` pela composição
  - rush: ≥28% cartas com [Rush]
  - aggro: ≥14% [Rush] + avg custo ≤3.5
  - control: ≥18% [Blocker] + avg custo ≥4, ou avg custo ≥4.5
  - ramp: ≥12% cartas com efeito de adicionar DON
- `getArqMod()`: retorna modificadores de scoring (t1Bonus, rushBonus, counter2kMult, etc.)
- Arquétipo exibido na UI ao lado do subtítulo da seção de mãos

### Outros ajustes de scoring
- Searcher escala com `calcSearcherQuality()`: % de bons alvos no deck
- Cartas +2k excluídas da contagem de T1/T2/T3 (não se joga counter no campo)
- Penalidade para mão toda custo 1 (sem gasolina mid-game): -15pts
- Bomba do deck: penalidade por mão pesada escala com `mod.bombPenMult` (ramp/control toleram mais)

### Estado atual
- `/analysis`: zero erros TypeScript, servidor rodando na 3000
- Próximo: testar com diferentes decks (aggro vs control) para validar os modificadores de arquétipo

---

## 2026-07-02 (36) - Claude

**Fix /analysis: scoring de mão com cobertura T1/T2/T3, bomba do deck, brick preciso**

- `avaliarMao`: pontos por jogada em T1(+28), T2(+22), T3(+12) + bônus curva completa T1→T2→T3.
- `getDeckBombId`: identifica carta mais cara/poderosa do deck como "bomba".
- Ter 1 bomba na mão = +8pts (sabe o que está construindo), 2+ = -20pts cada.
- `isEventCounter`: eventos com `counter_amount > 0` contam como defesa.
- Brick = sem jogada T1 nem T2-T3 E sem defesa nenhuma (counter 2k, 1k ou evento-counter).
- `gerarMelhoresMaos` passa `bombId` para `avaliarMao`.

---

## 2026-07-02 (35) - Claude

**Fix /analysis: melhores mãos, dependência, brick e labels**

- `avaliarMao`: diminishing returns — 1 searcher=+30, 2=+3, 3+=-18/cada. Evita mãos com 3 cópias da mesma carta no topo da simulação.
- `isSearcher()`: nova função com detecção mais precisa ("search your deck" / "look at the top...add" / "look at up to"), descarta "add up to" genérico que pegava cartas de vida.
- `simularMaos`: dependência agora conta mãos únicas (Set por hand) em vez de slots. Resultado: % de mãos que viram a carta, não proporção de cópias.
- Brick: `!temLow4 && !temCounter2k` (sem carta ≤4 E sem counter 2k), antes ignorava mãos pesadas que tinham 1 counter.
- Label tabela probabilidade: "Chance de Tirar a Peça se Não Veio na Mão".
- Dependência renomeada para "Frequência na Abertura".

---

## 2026-07-02 (34) - Claude

**Fix + UX: deck builder estável, borda dourada no leader**

- Fix: `card_color is null` em 4 pontos do `/deck/page.tsx` → `(card_color || '').split(...)`.
- UX: imagem do leader ganha `border-2 border-yellow-400` + `shadow glow` dourado.
- Fix tamanho: `w-22 h-31` (classes inexistentes no Tailwind) → inline style `88×124px`.

---

## 2026-07-02 (33) - Claude

**Fix urgente — Deck Builder crashava com `card_color is null`**

Cartas com `card_color = null` no banco causavam TypeError em 4 lugares no
`/deck/page.tsx` onde `.split()` era chamado diretamente sem null check.
Fix: `card.card_color.split(...)` → `(card.card_color || '').split(...)` nos 4 pontos
(validação de cor, badge da carta no resultado da busca, barra de cor do leader, badges do leader).

---

## 2026-07-02 (32) - Claude

**Feito — Melhorias de front-end (/simulate, /analysis, /meus-decks)**

### `/simulate`
- Ao abrir sem `?id=`, mostra picker inline com grid de decks do usuário (antes: erro "Nenhum deck selecionado").
- Botão "🎬 Replay direto" disponível na seção de configuração, sem precisar simular antes.

### `/analysis`
- Skeleton animado (`animate-pulse`) enquanto a API Python carrega arquétipo/sinergias/coesão.
- Aviso amarelo se a API falhar ou não retornar resultado.
- Botão "🎯 Simular este deck" ao final da página, ligando para `/simulate?id=`.

### `/meus-decks`
- Fix: `w-26 h-34` não são classes Tailwind padrão — substituídas por `style={{ width: '88px', height: '124px' }}`.
- Botão duplicar deck (⧉) que clona o deck com sufixo "(cópia)" via insert no Supabase.
- Botões de ação passam de `text-base` para `text-sm` para melhor proporção.

Build `npx next build` + `npx tsc --noEmit`: zero erros.

**Estado:** front funcional, motor em 87% top1-kind.

**Próximos passos:** decidir próxima fatia — mais logs, tuning de heurísticas, ou contrato de API para integrar motor com front.

---

## 2026-07-02 (31) - Claude

**Feito — +3 logs ao banco + fix de slug com caracteres ilegais**

Adicionados 3 logs novos ao banco (`logs/{raw,parsed,decks}/` + `index.json`):
- `Krieg-RG_x_Marshall.D.Teach-B_2026-07-02T00.16.32` (12 turnos, Karlmalone wins)
- `Krieg-RG_x_Brook-GB_2026-07-02T00.33.15` (12 turnos, Karlmalone wins)
- `Eustass.Captain.Kid-Y_x_Sabo-RB_2026-07-02T00.48.19` (11 turnos, TaxiCab wins)

**Fix `parse_combat_log.py`:** `_leader_slug` agora remove chars ilegais em filesystem
(`"`, `'`, `/`, `\`, etc.) do nome do líder antes de montar o slug. Necessário para
`Eustass "Captain" Kid` — as aspas duplas causavam `WinError 123` no `shutil.copy2`.

**Métricas após adição dos 3 logs (10 logs totais, 134 turnos):**
- top1-kind: **117/134 (87%)** — mantém acima do bar de 85%.
- 2 novos logs perfeitos (Brook e Marshall), Kid/Sabo tem 2 divergências no T7
  (humano ativa OP12-117 antes de jogar; comparador vê só 1ª ação).

**Próximos passos:**
- Fechar contrato de saída para o front (endpoint `/simulate` → resumo de decisões,
  motivo da jogada, replay visual). Ver TODO.md.

---

## 2026-07-02 (30) - Claude

**Feito — Fatia A: diagnóstico completo + fixes de score**

Métricas antes: top1-kind 86/99 (87%). Depois: **87/99 (88%)**.

Divergências analisadas turno a turno em todos os 7 logs. Categorias:

**Corrigidas:**
- `_make_card`: `data.get('type', 'CHARACTER')` → `data.get('type') or 'CHARACTER'`
  para tratar type=None no DB (afetava Five Elders OP13-082 e outros da coleção 13).
- `_score_play_action`: EVENT com `ko opp_stage` sem stage no campo do oponente → -120.
  `Never Existed` deixou de competir no T9 do Nami/Imu; `activate Empty Throne` subiu.
- `_score_play_action`: CHARACTER vanilla fraca (custo≤2, power≤3000, sem efeito/blocker)
  no early (turno pessoal ≤2) → -60. Humanos passam em vez de gastar 1 DON em vanilla.

**Divergências restantes (aceitáveis):**
- T11-T15 Nami/Imu: campo muito cheio no mid-game; snapshot do turno anterior
  não reconstruiu corretamente o estado de 5+ engines ativados. Bug do comparador,
  não do motor.
- Gecko Moria T5: humano ataca com opp_life=3 em vez de jogar carta. Priority LETHAL
  já existe mas o Turn Planner não estava priorizando no estado exato desse turno.
- Marshall/Lucy 2 turnos: ordering dentro do turno (humano ataca primeiro, depois joga);
  o comparador só vê a 1ª ação — divergência de método de comparação, não de motor.
- Jinbe vs Ace T1: Leo (custo 1, passive immunity) — humano passa; fix de vanilla
  não cobre por causa do efeito passive. Específico de estratégia do deck.

**Conclusão da Fatia A:**
Motor está em 88% top1-kind. As divergências restantes não são bugs corrigíveis sem
sobrecorrigir (risco de piorar outros casos). Barra de aceite atingida.

**Próximos passos:**
- Criar contrato de saída estável para o front (análise do deck, replay/partida, resumo
  de decisões, explicação curta do motivo da jogada da IA).
- Ou: adicionar mais logs ao banco e re-medir antes de mover pro front.

---

## 2026-07-02 (29) - Claude

**Feito — Fatia B: defesa situacional + fix de counter chunks revelados**

- **`should_use_blocker`**: com 4 vidas e `opp_life <= 2`, agora bloqueia atacantes
  com poder >= poder do líder. Antes nunca bloqueava com 4 vidas, mesmo sob pressão
  de lethal iminente.
- **`should_use_counter`**: com 4 vidas e `opp_life <= 2`, ratio cai de 2x para 1.5x.
  Afrouxar o threshold quando oponente está próximo de ganhar reflete o comportamento
  humano observado nos logs sem depender de padrões por líder (base de 7 partidas
  é insuficiente para isso).
- **`opp_counter_chunks_for_lethal` (bug fix)**: o Codex havia quebrado o teste
  `can_lethal respeita counters revelados` ao assumir `[2000] * unknown_hand_size`
  para slots ocultos. Restaurado para "ocultos = ignora (0), revelados = valor real" —
  contrato correto para cálculo de lethal garantido. Todos os smoke tests passam.
- **`_score_activate_main`** (mudança do Codex, agora commitada): avalia melhor alvo
  elegível da mão quando o efeito é `play_card`. Empty Throne sobe de score 95 para
  ~180, competindo melhor com jogar carta forte da mão.
- Revisão dos commits do Codex (sess. 28): mudanças sólidas no geral. Ponto de atenção:
  bonus de padrões humanos (`_human_pattern_bonus`) com 7 partidas é frágil — monitorar
  se divergências sobem com mais logs.

**Estado atual:**
- Fatia A (tuning Imu/Empty Throne): feita pelo Codex (sess. 28), métricas 43/99 top1-exact.
- Fatia B (defesa/counter): feita agora.
- Smoke tests: todos passando.

**Próximos passos:**
1. Decidir se motor está bom o suficiente para o front (barra de aceite: top1-kind >= 85/99).
2. Se sim: criar contrato de saída estável para o front consumir (análise, replay, decisões, explicação).
3. Se não: identificar os 15/99 turnos em que top1-kind ainda diverge e checar se são
   bugs de regra (corrigir) ou heurística (tunar mais).

---

## 2026-07-02 (28) - Codex

**Feito - padroes humanos de pilotagem + ajuste leve no Turn Planner:**

- Adicionado `scriptis_da_ia/audit_human_patterns.py` para extrair padroes humanos dos logs parseados: ordem de acoes, n-grams por leader, acoes antes do ataque e respostas defensivas/counter.
- Gerado `scriptis_da_ia/human_patterns.json` a partir de 7 logs humanos: 99 turnos, 487 acoes e 95 eventos defensivos/counter.
- `decision_engine.py` agora carrega `human_patterns.json` quando disponivel e aplica bonus leve/capado para `play`, `activate` e `attack` vistos em padroes humanos do leader.
- `compare_vs_human.py` ganhou `--summary`, `--top-k`, normalizacao de ataques por `attacker_code`, comparacao `exact/kind/miss`, DON por turno pessoal e inferencia de Stage ativado (ex.: `The Empty Throne`) no snapshot reconstruido.
- Importados 4 logs humanos novos para `scriptis_da_ia/logs/{raw,parsed,decks}` e atualizado `logs/index.json`.
- `parse_combat_log.py` ajustado para remover sufixo `.log` de timestamps vindos de arquivos `.log.txt`.
- Validacao leve: `python -m py_compile scriptis_da_ia\optcg_engine\decision_engine.py scriptis_da_ia\compare_vs_human.py scriptis_da_ia\audit_human_patterns.py scriptis_da_ia\audit_decision_quality.py scriptis_da_ia\parse_combat_log.py`.
- Metricas atuais do comparador: `top1 exact 41/99`, `top1 kind 84/99`, `top5 exact 87/99`, `top5 kind 96/99`.

**Proximo passo sugerido:**

Tunar prioridade de engines recorrentes (Imu/Five Elders/The Empty Throne) versus jogar carta forte da mao, agora que o comparador ja reconstrui Stage e DON de forma menos contaminada.

---

## 2026-07-01 (27) - Codex

**Feito - auditoria interna do Turn Planner + lethal com DON anexavel:**

- Novo `scriptis_da_ia/audit_decision_quality.py` para auditar o motor, nao logs humanos.
- `decision_log` agora registra decisoes do Turn Planner: contexto, top imediato, candidatos, escolha final, valor simulado e `win=X/N`.
- `_simulate_sequence` deixou de usar `1e9` como valor terminal bruto; agora usa `SIMULATED_WIN_SCORE = 50000.0`, evitando que `win=1/6` esmague linhas estaveis.
- `_score_activate_main` trata efeitos tipo Imu (`trash 1` + `draw 1`) como filtragem, nao vantagem liquida de carta; isso reduziu activate cedo de score ~120 para 10/45.
- `can_lethal_this_turn()` agora considera distribuicao de DON disponivel entre ataques, mantendo defesa conservadora com blockers/counters.
- `smoke_test.py` ganhou cobertura para lethal com DON anexavel e preservou o caso de counters revelados com DON=0.
- Validacao: `python -m py_compile ...`, `python scriptis_da_ia\smoke_test.py` e `python audit_decision_quality.py --n 10 --seed 42 --examples 8` passaram.

**Proximo passo sugerido:**

Rodar `audit_decision_quality.py --n 50 --seed 42 --examples 12` e olhar os blocos restantes: overrides grandes e ataques em vida 0 com `win=0/N`.

---

## 2026-07-01 (26) - Codex

**Feito - compare_vs_human corrigido + falso lethal score removido:**

- `scriptis_da_ia/compare_vs_human.py` agora usa snapshot aproximado de inicio do turno para comparar IA vs humano.
- O snapshot parseado continua sendo pos-turno; por isso o comparador usa o turno anterior + carta comprada no turno atual.
- T1 de Nami-BY x Imu-B deixou de acusar falso positivo: IA agora prefere jogar `Saint Shalria`, nao ativar Imu.
- `scriptis_da_ia/optcg_engine/decision_engine.py` nao da mais score `10000` para atacar leader com vida 0 quando `can_lethal_this_turn()` diz que o lethal nao e garantido.
- Revalidado nos 3 logs parseados: os scores falsos `9900/9920` sumiram; score alto sobrou apenas em lethal real.
- Validacao: `python -m py_compile scriptis_da_ia\compare_vs_human.py scriptis_da_ia\optcg_engine\decision_engine.py` e `python scriptis_da_ia\smoke_test.py` passaram.

**Proximo passo sugerido:**

Auditar os turnos em que Imu ainda prefere `activate` cedo, agora que a regua do comparador esta menos contaminada.

---

## 2026-07-01 (25) - Claude

**Feito — bug crítico no parser corrigido + 3º log adicionado:**

### Bug: parser não capturava ataques, bloqueios nem counters

Formato real do log: `["CODE">DisplayName]` (fecha com `">NAME]`)
Regex antigo esperava: `["CODE"]` (fecha com `"]`)

Resultado: zero ataques capturados em todos os logs anteriores. Corrido:
- `RE_ATTACK`, `RE_BLOCKS`, `RE_DISCARD`, `RE_EFFECT`, `RE_ATTACH` atualizados
- `RE_ATTACK` agora captura também o `attacker_code` (grupo 3)
- `result=None` em ataque sem "Attack Fails" → fechado como `'hit'` ao iniciar próximo ataque ou ao fim do turno
- Logs antigos re-parseados: 40 ataques agora capturados na partida Nami vs Imu (antes: 0)

### Diagnóstico do compare_vs_human após correção

Divergências falsas eliminadas: o humano SIM atacava nos turnos "sem ação". O estado de fim-de-turno (pós-ação) era usado como estado inicial — IA via characters ativos quando já tinham atacado. Divergências reais identificadas:
- **T01**: IA prefere activate do Imu (score 103) vs jogar Shalria (custo 1). Com 1 DON são mutuamente exclusivos — IA provavelmente supervaloriza activate no early.
- **T03**: IA rankeia activate como top, não vê a sequência jogar+ativar+atacar como um todo (Turn Planner vê só 1ª ação do turno).
- **T07/T17**: IA prefere activate, humano jogou carta — pode ser ordering issue do Turn Planner.

### 3º log adicionado

Imu-B vs Monkey.D.Luffy-BP (Sebs#6211), 17 turnos. Partida rica: Saturn debuffando Boa Hancock -2000, Gol D. Roger buffando Luffy, counters com Nami/Usohachi, The Empty Throne ativo todo turno. 41/50 do Imu, 30/50 do Luffy.

**Banco atual:** 3 partidas (Teach-BY×Lucy-RB, Nami-BY×Imu-B, Imu-B×Luffy-BP)

**Próximos passos prioritários (anotados no TODO):**
1. `compare_vs_human.py`: usar snapshot do turno ANTERIOR como estado inicial (hoje usa fim do turno atual → falsos positivos onde IA "quer atacar" chars que já atacaram)
2. `_score_activate_main`: penalizar quando campo vazio e DON ≤ 2 (IA prefere activate a jogar carta no T01 com 1 DON — mutuamente exclusivos)

---

## 2026-07-01 (24) - Claude

**Feito — compare_vs_human.py: compara IA vs humano turno a turno**

Script novo `scriptis_da_ia/compare_vs_human.py`:
- Lê um JSON de partida parseado (`logs/parsed/`)
- Para cada turno, reconstrói `GameState` (mão, campo, trash, vida, DON) a partir do snapshot
- Roda `_generate_and_score_actions` do Turn Planner no estado reconstruído
- Mostra: o que o humano fez vs top 8 ações da IA por score
- Marca `*** DIVERGENCIA` quando IA e humano escolheram diferente

Uso:
```
python compare_vs_human.py logs/parsed/<arquivo>.json
python compare_vs_human.py logs/parsed/<arquivo>.json --player Nome --no-state
python compare_vs_human.py logs/parsed/<arquivo>.json --turn 7
```

**Primeiros achados (partida Nami-BY x Imu-B):**
- T05, T09, T11, T13, T15: humano passou, IA queria atacar (score 470–585) — pode ser IA super-agressiva ou humano guardando DON para counter
- T01, T03: IA prefere `activate` do líder Imu antes de jogar carta — humano preferiu desenvolver campo
- T17: IA prefere activate, humano jogou Warcury — provavelmente IA certa (activate tem mais valor no estado terminal)

**Próximo passo:** auditar turno a turno quais divergências são bug de heurística vs decisão legítima do humano. T05 é o candidato mais óbvio (humano não atacou com field inteiro e vida baixa).

---

## 2026-07-01 (23) - Claude

**Feito — 2ª partida adicionada ao banco de logs:**

- Partida: Jack#5459 (Nami-BY, OP11-041) vs Karlmalone#2854 (Imu-B, OP13-079)
- 17 turnos, Karlmalone foi primeiro e perdeu
- Deck Imu: 42/50 cartas vistas (shell OP13 completo — Five Elders + quatro arcanjos)
- Deck Nami: 29/50 (partida curta)
- Arquivos: `Nami-BY_x_Imu-B_2026-07-01T14.22.50.{log,json}`

**Banco atual:** 2 partidas indexadas (Teach-BY×Lucy-RB, Nami-BY×Imu-B)

---

## 2026-07-01 (22) - Claude

**Feito — roadmap de análise estatística registrado no TODO:**

Adicionado ao TODO o plano de uso do banco de logs para estatísticas e tuning da IA:
- Win rate por matchup (líder × líder)
- Curva de vida por turno
- Deck popularity por líder
- Comparação IA vs humano: snapshot do log → engine decide → compara com jogada real

Nenhuma mudança de código nesta sessão.

---

## 2026-07-01 (21) - Claude

**Feito — nomes de arquivo dos logs usam lider+cor em vez de timestamp puro:**

- Adicionadas funções `_color_abbrev`, `_leader_slug`, `_match_slug` ao `parse_combat_log.py`
- Busca a cor do líder em `cards_rows.csv` (campo `card_color`)
- Converte cor para abreviação na ordem canônica OPTCG (R, G, B, P, B, Y): "Black Yellow" → "BY", "Blue Red" → "RB"
- Nome do líder limpo: remove sufixo " (NNN)", colapsa espaços em ponto, remove pontos duplos
- Arquivos agora se chamam `Marshall.D.Teach-BY_x_Lucy-RB_2026-07-01T12.46.16.{log,json}`
- Decks: `Marshall.D.Teach-BY_2026-07-01T12.46.16.json`, `Lucy-RB_2026-07-01T12.46.16.json`
- `index.json` ganhou campo `friendly_name` e `slug` em p1/p2
- `list_db` atualizado para exibir slugs amigáveis
- Banco re-populado com a partida Teach vs Lucy já no novo formato

**Pendências conhecidas:**
- Próximo passo: dado snapshot do log real, rodar engine e comparar decisão IA vs humano
- [B] handlers sem log: look_top_deck, negate_effect, activate_trash_event_main, lock_opp_don
- Frontend (deferred até motor estar satisfatório)
- Supabase service_role exposta no .env.local — rotacionar antes de deploy público

---

## 2026-07-01 (20) - Claude

**Feito — parse_combat_log.py com reconstrução de decks e banco de partidas:**

### parse_combat_log.py — extensão com deck reconstruction + DB

Adicionadas ao script existente:
- `reconstruct_decks()`: reconstrói deck de cada jogador a partir dos snapshots (contagem máxima simultânea de cada carta) + eventos de draw. Remove o código do líder. Exibe `N/50 cartas vistas` e lista com counts.
- `add_to_db()`: copia o `.log` para `logs/raw/`, salva JSON parseado em `logs/parsed/`, salva JSON dos decks em `logs/decks/`, atualiza `logs/index.json` com metadados da partida.
- `list_db()`: lista todas as partidas indexadas.
- Flags CLI: `--add-to-db` e `--list-db`.
- Testado com partida Teach vs Lucy: 37/50 e 45/50 cartas vistas, banco criado corretamente.
- Estrutura de pastas criada: `scriptis_da_ia/logs/raw/`, `logs/parsed/`, `logs/decks/`.

**Uso:**
```
python parse_combat_log.py partida.log --summary --add-to-db
python parse_combat_log.py --list-db
```

**Pendências conhecidas:**
- Próximo passo: dado um snapshot do log real, rodar o engine e comparar decisão da IA com o que o humano fez → divergências concretas para tunar heurísticas
- Deck reconstruction chega a ~45/50 cartas em partidas longas; decks curtos ficam incompletos (inerente ao método)
- [B] handlers sem log: `look_top_deck`, `negate_effect`, `activate_trash_event_main`, `lock_opp_don`
- Frontend (deferred até motor estar satisfatório)
- Supabase service_role exposta no `.env.local` — rotacionar antes de deploy público

---

## 2026-07-01 (19) - Claude

**Feito — 6 fixes de heurística + parser de combat log do simulador oficial:**

### Fixes no decision_engine.py / card_effects_db.json

1. **`activate_main` vira ação competitiva no Turn Planner** (commit b1ea2f6): Em vez de sempre disparar no início do turno, `_activate_main_effects` foi removido do loop e substituído por entradas `('activate', src, ...)` no `_generate_and_score_actions`. Novo método `_score_activate_main` pontua o benefício vs custo. A IA agora compara "ativar líder (score 120) vs jogar Five Elders (score 190)" e escolhe a ordem certa. `_remap_action` e `_apply_action` atualizados.

2. **`_score_play_action` valoriza `play_from_trash` no `activate_main`** (commit 1179bc7): Se a carta a ser jogada tem `activate_main` com `play_from_trash`, conta alvos no trash + campo e adiciona `n * 50` ao score. Five Elders com 4 alvos recuperáveis → +230 extra.

3. **`_evaluate_state` valoriza chars no trash recuperáveis** (commit 1179bc7): Para cada carta na mão que pode recuperar do trash (`play_from_trash`), o Turn Planner agora enxerga `n * 60` de valor nos chars elegíveis no trash. Faz a sequência atacar → trashar via líder → jogar Five Elders emergir naturalmente.

4. **The Empty Throne só joga CHARACTER** (commit 1056fe3): DB tinha `play_card` sem `card_type`, então escolhia o evento "Never Existed" (sub_type Five Elders) em vez de personagens. Fix: `"card_type": "CHARACTER"` no step + filtro correspondente no engine.

5. **`_trash_value` protege cartas de custo alto** (commit 1056fe3): Chars de custo ≥ 7 agora recebem `20 + custo * 8` (custo 10 → +100) mesmo sem DON disponível. Antes Five Elders era trashado quando o DON do turno era insuficiente para jogá-lo.

6. **`_should_activate_main` verifica condições do efeito** (sessão 18): `board_has_cost` e outros conditions do activate_main eram ignorados. Fix via `dummy_ee._check_conditions(conds, src)` no topo do método.

### parse_combat_log.py (commit f839e27)
- Script novo em `scriptis_da_ia/parse_combat_log.py`
- Lê o `.log` do simulador oficial e gera JSON estruturado: metadados, turnos, ações (play/activate/attack com resultado), snapshots (mão/campo/trash/vida)
- Detecta jogador por Draw Don, Draw Card, ou alternância (quando o log omite "Draw N Don")
- Uso: `python parse_combat_log.py partida.log --summary`
- Testado com partida Teach (OP16-080) vs Lucy (OP15-002): 22 turnos extraídos corretamente

### Commits desta sessão (2026-07-01):
- b1ea2f6: activate_main vira ação competitiva no Turn Planner
- 1179bc7: _score_play_action e _evaluate_state valorizam chars no trash recuperáveis
- 1056fe3: The Empty Throne só joga CHARACTER; _trash_value protege cartas de custo alto
- f839e27: parse_combat_log.py converte log do simulador oficial em JSON estruturado

**Pendências conhecidas:**
- Próximo passo com o parser: dado um snapshot de estado do log real, rodar o engine e comparar decisão da IA com o que o humano fez → identificar divergências concretas para tunar heurísticas
- [B] handlers sem log: `look_top_deck`, `negate_effect`, `activate_trash_event_main`, `lock_opp_don`
- Frontend (deferred até motor estar satisfatório)
- Supabase service_role exposta no `.env.local` — rotacionar antes de deploy público

---

## 2026-07-01 (18) - Claude

**Feito — Mihawk passive corrigido + activate_main aparece no replay log:**

1. **OP14-020 passive condicionado a `opp_leader_attribute: slash`**: O passive do Mihawk (`+1000 power this_turn`) não tinha condição — disparava contra qualquer oponente, incluindo Imu (líder OP13-079 com atributo `?`). Fix: adicionado `"conditions": {"opp_leader_attribute": "slash"}` no `card_effects_db.json`. Novo campo `opp_leader_attribute` em `_check_conditions` do engine.

2. **`_activate_main_effects` agora chama `_log_event`**: Ativações de efeitos [Activate:Main] não apareciam na tabela de eventos do ReplayViewer. Fix: após executar os steps via `ee.execute`, o resultado é logado com `_log_event(p, 'activate_main', card=src, description=...)`.

**Commits desta sessão (2026-07-01):**
- e96c245: Turn Planner + trash_char_or_hand fix
- 1a05572: 4 fixes [A] de jogabilidade
- b7a0388: Mihawk passive + activate_main log

**Pendências conhecidas:**
- [B] handlers sem log: `look_top_deck`, `negate_effect`, `activate_trash_event_main`, `lock_opp_don`, etc.
- Frontend (deferred até motor estar satisfatório)
- Supabase service_role exposta no `.env.local` — rotacionar antes de deploy público

---

## 2026-07-01 (17) - Claude

**Feito — 2 fixes sistêmicos de qualidade de decisão (Imu e padrão geral):**

1. **`_simulate_sequence` agora chama `_activate_main_effects` no loop**: O Turn Planner não chamava `_activate_main_effects` na simulação, então ao avaliar "jogar Saint Shalria", não via que isso habilitaria o líder Imu (trash→draw) e o stage (Empty Throne→play character). Fix: adicionado `_activate_main_effects(p2, opp2, ee2)` antes de cada iteração do loop em `_simulate_sequence`. Agora o planner captura combos multi-ação como jogar personagem → ativar líder → ativar stage → atacar.

2. **`_should_activate_main` trash_char_or_hand**: O filtro de tipo estava sendo aplicado à MÃO indevidamente. O texto correto do Imu é "trash 1 [Celestial Dragons] Character (campo) OR 1 card from your hand" — qualquer carta da mão, sem filtro de tipo. Fix: `hand_ok = p.hand` (sem filtro). Isso resolvia o líder Imu nunca ativando quando a mão não tinha Celestial Dragons.

**Contexto**: User mostrou replay onde Imu tinha 4 DON, 7 cartas, stage no campo, e só atacou+encerrou. A sequência correta (Saint Shalria→líder draw→Empty Throne→Warcury→atacar) agora deve ser capturada.

---

## 2026-07-01 (16) - Claude

**Feito — 4 correções de jogabilidade [A] no decision_engine.py:**

1. **Fix `_can_play_card` (linha ~5021):** Eventos com `[Counter]+main` (ex: OP13-040, OP13-098, OP14-096) estavam sendo bloqueados do main phase. A verificação `[counter] in text → return False` foi reordenada para só bloquear eventos pure-counter (sem trigger `main`). Esses eventos agora são jogados no main phase via trigger `main`.

2. **Fix `_has_don_reactive_use`:** Não detectava counter events com custo de play como motivo para reservar DON. Adicionado check `effective_hand_play_cost(me, c) > 0` para counter events na mão. Agora o AI reserva 1 DON quando tem counter event de custo 1 na mão.

3. **Novo método `_parse_counter_event_text_fallback`:** Parser leve do bloco `[Counter]` do texto bruto da carta. Usado quando `card_effects_db.json` tem `counter: 0` (bug do gerar_effects_db.py — não parseia bloco `[Counter]` de EVENT). Cobre o padrão "+X power during this battle" com suporte a condições `leader_is` e `trash_gte`. Testado com OP06-038, OP12-037, OP09-078: plans retornados corretamente. Verificado por trace: counter events agora USADOS (ex: OP13-098 used 4x em 1 partida).

4. **Fix `_score_play_action`:** Personagens com `when_attacking` ganham `habilita_ataque=True` (+60 bonus para sair antes dos ataques). Personagens com `activate_main` ganham +30 bonus base.

**Resultado auditoria (25 partidas, seed=42):**
- `activate_main NUNCA ativado: 0 cartas` (era multiple antes — Imu leader, Five Elders, etc. agora ativam)
- Counter events estão sendo usados (verificado por monkey-patch; o audit não os vê porque `try_counter_event_power` bypassa `EffectExecutor.execute`)
- [A] restante: Garp/Whitebeard (correto — condição de líder), Carrot when_attacking (amostras pequenas), OP13-040 counter (consumido no main phase, não como counter — correto)

**Pendências [A] que ficaram:**
- Carrot (OP08-023) `when_attacking` — personagem provavelmente morto antes de atacar; ou amostra pequena. Não é bug de engine, é scoring/heurística.
- Pure counter events (OP06-038, OP12-037) aparecem em [A] no audit — artefato: o audit não captura `try_counter_event_power`. Verificado por trace que funcionam.

**Próximo:** Resolver [B] (handlers sem log: `look_top_deck` 3329x, `negate_effect` 287x, `activate_trash_event_main` 164x, `lock_opp_don` 141x, `keyword_blocker`, `immunity`, `substitute_removal`).

---

## 2026-07-01 (15) - Claude

**Feito — revisão e commit do trabalho do Codex (sessão anterior).**
Nenhum código alterado, só commit + push do estado local.

---

## 2026-07-02 - Codex

**Feito — primeira versão do compliance checker:** criado
`scriptis_da_ia/audit_card_effects.py`. Ele roda partidas reais e instrumenta
`EffectExecutor.execute()` / `_execute_step()` para medir:
- triggers parseados chamados;
- triggers chamados que produziram log observável;
- actions executadas;
- actions executadas sem log;
- triggers de cartas presentes na amostra que nunca foram chamados.

**Validação:** `python -m py_compile scriptis_da_ia\audit_card_effects.py`;
`python audit_card_effects.py --n 3 --seed 42 --top 8 --min-calls 1`;
`python audit_card_effects.py --n 10 --seed 42 --top 12 --min-calls 2`.
As duas execuções terminaram sem exceções.

**Leitura importante:** isto é triagem por evidência de execução, não prova
oficial carta-a-carta. Suspeitos persistentes da amostra de 10 partidas:
`OP08-040 Atmos` (`on_play`) e `OP14-027 Shanks` (`when_rested`) foram chamados
muitas vezes sem log observável; também apareceram actions como `look_top_deck`,
`lock_opp_don`, `keyword_blocker`, `substitute_removal` e `immunity` sem log,
que podem ser no-op legítimo ou falta de mensagem/efeito observável.

**Investigação posterior:** `OP08-040 Atmos` era bug real causado por typo no
dado bruto (`Whitebeard Piratess`). A engine agora normaliza esse typo ao
checar `leader_type(_includes)`, e o smoke cobre o bounce com Leader
`Whitebeard Pirates`. `OP14-027 Shanks` tinha filtro perdido no parser/banco:
`rest_opp_character` agora captura `power_lte` para "base power or less", e o
banco atual recebeu `power_lte=7000`. No rerun do compliance, Atmos sumiu dos
suspeitos; Shanks passou de "chamado sem log" para "nunca chamado" na amostra,
indicando problema de uso/seleção na IA ou baixa oportunidade, não handler.

## 2026-07-02 (14) - Claude — ÚLTIMA DESTA SESSÃO

**Feito — Replay Viewer com popup de cartas + compliance checker infrastructure.**

**Backend (Python):**
- `OPTCGMatch.simulate_replay(name_a, name_b)` — roda 1 partida e retorna
  log estruturado de eventos por turno. Eventos: `turn_start`, `draw`,
  `play_card`, `effect` (efeitos on_play), `attack`, `life_damage`.
  Cada evento tem `{turn, player, player_name, phase, type, card, target, description}`.
  `card/target` incluem `{code, name, image, cost, power, type, color}`.
- `_CARD_IMAGE_CACHE` — dict code→URL de imagem carregado pelo `load_cards_db`
  para enriquecer eventos sem modificar Card/CardData.
- `_log_event(p, type, card, ...)` — helper em OPTCGMatch, no-op quando
  `replay_log is None` (modo normal, zero overhead).
- `replay_optcg.ReplayMatch._get_engine_match()` — adicionado `replay_log=None`
  e `_name_a/_name_b` para o `OPTCGMatch.__new__` não ter AttributeError.
- API `POST /replay` em `api.py` — aceita `{deck_a, deck_b, name_a, name_b}`,
  usa `simulation_worker.load_deck()`, retorna `simulate_replay()` result.

**Frontend (Next.js):**
- `src/components/ReplayViewer.tsx` — modal completo com:
  - Timeline de turnos (botões coloridos A=azul/B=vermelho)
  - Eventos do turno atual com ícones por tipo
  - Popup de imagem da carta ao hover (com card_image da API)
  - Navegação Anterior/Próximo + Auto-play (1.5s/turno)
  - Informações do evento: nome, descrição, alvo
- `src/app/simulate/page.tsx` — integrado:
  - `startReplay()`: chama `/replay`, carrega deck_b dinamicamente (pasted
    preview, own deck via Supabase, ou deck_a como fallback)
  - Botão "🎬 Ver Replay de 1 Partida" aparece após resultado da simulação
  - Modal `<ReplayViewer>` controlado por `showReplay` state

**Próximo:** compliance checker (`audit_card_effects.py`) para detectar
  automaticamente efeitos que não disparam.

---

## 2026-07-02 (13) - Claude

**Feito — otimização estrutural de deepcopy no Turn Planner: 2.8x speedup.**

**Técnica:** `_SimDeck` (list subclass com copy-on-pop lazy) + mesmo truque do
  `opp.deck` aplicado agora ao `p.deck` também.

`_simulate_sequence_once` agora:
1. Zera ambos os decks antes do `deepcopy(state)` (evita copiar ~80 Cards cada)
2. Restaura como listas rasas: `p2.deck = _SimDeck(p.deck)` e `opp2.deck = list(opp.deck)`
3. `_SimDeck.pop()` deepcopia a carta APENAS quando ela é efetivamente sacada
   durante a simulação — normalmente 0-2 por chamada, não 80.

**Correctness:** `_SimDeck(list)` é uma lista nova (não compartilha o objeto
  lista com `p.deck` — `list.__init__(other_list)` copia os elementos). Cards
  popped são deepcopiados no momento do pop, então mutações na simulação nunca
  afetam `p.deck`. Validado em 100 partidas (4 seeds × 25) — 0 exceções, 0
  anomalias de conservação de DON.

**Benchmark:** `_simulate_sequence_once`: 0.85ms → 0.30ms por chamada (2.8×),
  `main_phase` (36 calls): 31ms → 11ms. O gargalo era `deck (~80 cards) =
  0.7ms` de 1.2ms total; com lazy copy, só as cartas efetivamente sacadas são
  deepcopiadas.

---

## 2026-07-02 (12) - Claude

**Feito — OP15-074 Varie (foto recebida do usuário) + fix de duração.**

Dois bugs confirmados pela foto:
1. **CSV errado**: "DON!! 1" sem o sinal de menos → corrigido para "DON!! -1"
   em `cards_rows.csv`. Sem a correção, `parse_costs` não reconhecia o custo
   e o efeito ativava de graça.
2. **Duração errada**: `parse_cost_debuff` mapeava toda duração "until the end
   of your opponent's next End Phase" para `until_opp_turn_end`. Corrigido para
   distinguir "end phase" → `until_opp_end_phase` vs "turn" → `until_opp_turn_end`.
   Bonus: 3 cartas com o mesmo bug corrigidas (OP12-119, OP14-082, OP14-098).

Efeito correto agora: **[Main] DON!! −1** (custo don_minus:1), leader_is='enel',
draw 1 + buff_cost +2 own_character duration=until_opp_end_phase.
**[Counter]** buff_power +2000 filter_type='enel'.

TODO.md: item "OP15-074 Varie — DON sem sinal, aguarda foto" fechado.

**Pendências restantes (lista limpa):**
- Otimização estrutural de deepcopy no Turn Planner (dívida técnica de performance)
- Rotação de chaves Supabase (antes de deploy público)
- 3 gaps de parser intencionalmente sem efeito (ID mismatch, info-only, regra de deck)

---

## 2026-07-02 (11) - Claude

**Feito — gaps: 4 → 3 (intencionais), 2334 → 2335 com efeito. Auditoria de
gaps finalizada.**

Último gap implementável: **ST13-003 Luffy Leader** — "Your face-up Life cards
are placed at the bottom of your deck instead of being added to your hand,
according to the rules." Novo campo `face_up_life_to_deck: bool` em `GameState`.
Novo action `face_up_life_to_deck_rule` — setado via passive execution em
`apply_your_turn_buffs` a cada turno que o Leader ST13-003 está ativo. A
resolução de dano em `_execute_attack` (linha ~6502) checa este flag: se
`life_card.life_face_up and opp.face_up_life_to_deck` → card vai para
`opp.deck.insert(0, ...)` (fundo do deck) em vez de `opp.hand`.

**3 gaps intencionalmente sem efeito (de 51 originais):**
  - EB03_OP05-006_p1 — falso positivo de ID (parsa como OP05-006 base)
  - OP01-105 Bao Huang — "Choose 2 cards from your opponent's hand; your opponent
    reveals those cards" — info-only, sem mudança de estado de jogo
  - OP16-042 Prisoner of Impel Down — "You may have any number of this card" —
    regra de deckbuilding, sem efeito durante a partida

**Auditoria de gaps: CONCLUÍDA.** 2614 cartas no banco, 2335 com efeito (era
  2272 no início da sessão total, +63 esta rodada; a auditoria partiu de 51
  gaps reais e chegou a 3 intencionais).

---

## 2026-07-02 (10) - Claude

**Feito — gaps restantes: 14 → 4, 2324 → 2334 com efeito.**

Dispatch fixes + novas mecânicas implementadas nesta rodada:
- **OP15-031 / OP02-025**: m_pu estava dentro de parse_set_base_power (função
  que só é chamada quando "base power becomes" ou "set the power of" estão no
  texto) — movido para dispatch próprio em parse_block. OP02-025 regex
  `.{0,30}` muito curta (57 chars entre "character card" e "cost will be
  reduced") → ampliado para `.{0,80}`.
- **swap_base_power** (OP14-001 Law Leader / OP14-017 Chambres): engine seleciona
  2 chars do lado especificado, troca seus `base_power_override`.
- **mass deck_bottom** (OP05-058): `place_opp_character_bottom_deck count=99
  cost_lte=3` — a segunda parte (equalizar mãos) não implementada.
- **ko_battled_opp_char_and_self** (ST08-013 Mr.2): KO o melhor char do oponente
  + KO self (simplificação: escolhe melhor por board_value em vez do que "battled").
- **redirect_attack_target** (OP14-060 Doflamingo): parser only — no-op no engine
  (interrupcao de resolução de ataque é inviável com arquitetura atual).
- **activate_trash_event_main** (EB03-031): parser only — no-op no engine.
- **when_attacking_after_battle** (OP04-047): parsed como ação de `place_opp_character_
  bottom_deck` dentro do bloco `your_turn`; engine vai tentar executar no início
  do turno (timing errado, mas registrado para analysis_db).
- **EB03-031, OP10-022, OP02-025**: parsers mínimos para coverage análise.
- **OP12-040 Kuzan + OP02-025 Kin'emon**: já parseavam, só precisavam de dispatch
  fix / regex width.

**4 gaps restantes (de 51 originais):**
  - EB03_OP05-006_p1 — ID mismatch (parsa como OP05-006, falso positivo)
  - OP01-105 Bao Huang — info-only (revelar mão do oponente, sem estado)
  - OP16-042 Prisoner of Impel Down — regra de deckbuilding
  - ST13-003 passive — "face-up life → deck" em vez de mão (regra de dano
    modificada, requer mudança em todos os pontos de damage resolution)

**Validação:** `diff_parser.py` (PERDEU=0, 10 GANHOU); `gerar_dbs.py` (2334
  com efeito); `smoke_test.py` (100%); `smoke_test_broad.py` (40/40);
  `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99` (0 exceções, 0 anomalias).

---

## 2026-07-02 (9) - Claude

**Feito — gaps restantes: 19 → 11, 2319 → 2324 com efeito.**

Problemas de dispatch corrigidos (itens que estavam implementados mas não chegavam ao banco):
- **OP04-097 Otama** (`place_opp_char_to_opp_life`): regex `.{0,20}` insuficiente para
  "[animal] or [smile] type characters" (29 chars) → alargado para `.{0,45}`. Dispatch
  corrigido para `'add up to' in t` em vez de regex de path errado.
- **OP09-033 Nico Robin** (`grant_ko_immunity_type`): dispatch checava `"cannot be k.o.'d by"`
  mas texto usa `"can be k.o.'d by"` (negação via "none of", não via "cannot"). Corrigido.
- **OP07-002 Ain** (`set_base_power target=opp_character`): dispatch `parse_set_base_power`
  só disparava com "base power becomes" — adicionado `or 'set the power of' in t`.

Novos parsers/ações:
- **OP06-086 Gecko Moria**: dispatch `parse_play_from_trash` ampliado para aceitar
  "play N card" sem "up to" — dois steps `play_from_trash` (cost≤4 normal + cost≤2
  rested) já eram produzidos corretamente pela função, só o dispatch faltava.
- **OP15-031 Purinpurin**: nova ação `ko_if_cost_eq_don` — engine seleciona rested
  Character do oponente onde `c.cost == c.don_attached` e KO. Parser detecta
  "if the chosen Character has a cost equal to the number of DON!! cards given to it, K.O. it".
- **ST13-003 Luffy Leader** (partial): parser de `gain_life` agora aceita "from your
  hand or trash to the top of your life" (padrão com "trash" na source — antes bloqueado
  pelo guard `'trash' not in m.group(0)`). Resolvido com regex específico antes do
  guard geral. Activate:Main agora parseia (life_lte=0 condition + gain_life hand source).
  A regra passiva "face-up life → deck" continua sem implementação de engine (muito
  complexo, 1 carta).
- **OP12-040 Kuzan Leader**: simplificação — `draw dynamic=True` para analysis (trigger
  reativo real "draw = número de cartas descartadas por Navy" não modelado no engine).
- **OP02-025 Kin'emon Leader**: simplificação — `buff_cost target='own_play_hand'
  duration='next_play_only'` para analysis (one-shot cost reduction para próxima
  jogada não modelado no engine, mas registrado no DB).

**Bug crítico evitado (duas vezes nesta sessão):** editar dentro de `parse_set_base_power`
sem respeitar que o `step = {...}` pertence ao for-loop causa PERDEU em dezenas de cartas
(indentação quebra a pertença ao loop). Cuidado extremo ao editar esta função.

**Gaps restantes: 11** (de 51 iniciais):
  - 3 não-jogáveis: EB03_OP05-006_p1 (ID mismatch), OP01-105 (info only), OP16-042 (regra de deck)
  - 8 mecânicas genuinamente novas: swap de poder (OP14-001/017), redirect ataque
    (OP14-060), EB03-031 (activate Event from trash), OP04-047 (end-of-battle trigger),
    OP05-058 (mass deck_bottom + equalizar mãos), OP10-022 (bounce cost + reveal life + play),
    ST08-013 (mutual KO after battle).

**Validação:** `diff_parser.py` (PERDEU=0); `gerar_dbs.py` (2324 com efeito);
  `smoke_test.py` (5 testes novos, 100%); `smoke_test_broad.py` (40/40);
  `audit_replay.py --n 20 --seed 7` (0 exceções, 0 anomalias).

---

## 2026-07-02 (8) - Claude

**Feito — 4 gaps de mecânica nova (pedidos do usuário), 2315 → 2319 com efeito.**

1. **`grant_ko_immunity_type` (OP09-033 Nico Robin):** "If you have 2 or more
   rested Characters, none of your 'ODYSSEY' or 'Straw Hat Crew' type Characters
   can be K.O.'d by effects until the end of your opponent's next turn." Novo
   campo `immunity_ko_until: str` em Card (mesmo padrão de `cannot_attack_until`).
   Nova ação `grant_ko_immunity_type` com `filter_type` e `duration`. Checado em
   `is_immune()` antes do return False. Reset em `refresh_phase`. Nova condição
   `chars_rested_gte` em `parse_conditions`. Parser: `parse_grant_ko_immunity`.
   Bônus: 17 outras cartas OP09-xxx com "2 or more rested characters" também
   ganharam a condição `chars_rested_gte=2` em seus effects existentes.

2. **`place_opp_char_to_opp_life` (OP04-097 Otama, OP05-111 Hotori, EB02-057
   Mad Treasure):** "Add up to N of your opponent's [X] Characters with a cost
   of Y or less to the top/bottom of your opponent's Life cards face-up." Remove
   character do campo do oponente via `remove_character_from_field(..., 'hand')`
   (sem trigger on_ko), seta `life_face_up=True` e insere em `opp.life`. Parser:
   `parse_opp_char_to_opp_life`. Engine handler em `decision_engine.py`.

3. **`set_cost_to_0` / `filter_no_effect` (OP03-091 Helmeppo):** "Set the cost
   of up to 1 of your opponent's Characters with no base effect to 0 during this
   turn." Novo padrão em `parse_cost_debuff`: regex `set the cost of up to N...
   to X`. Novo campo `to_value` no step (engine calcula `cost_buff += -(
   effective_cost - to_value)` no momento de aplicação, sem precisar do custo
   no parse time). Novo flag `filter_no_effect` em candidatos (filtra Characters
   com `get_card_effects().get('effects')` vazio).

4. **`self_cant_take_life` (ST15-001 Atmos + OP02-004, OP02-023, OP06-020):**
   "You cannot add Life cards to your hand using your own effects during this turn."
   Novo campo `cant_take_life_this_turn: bool` em `GameState`, resetado em
   `refresh_phase`. Engine: `life_to_hand` retorna '' imediatamente se flag ativa.
   4 cartas no banco com esse texto (achado 3 bônus no processo).

**Validação completa:** diff (PERDEU=0 em todos), gerar_dbs (2319 com efeito),
  smoke_test (100%, 2 testes novos por item), smoke_test_broad (40/40),
  audit_replay seeds 7 e 99 (0 exceções, 0 anomalias).

---

## 2026-07-02 (7) - Claude

**Feito — Auditoria de gaps (rodada 3): 23 gaps finais, 2315 com efeito.**

Continuação direta da rodada anterior. Mecânicas novas implementadas nesta rodada:
- `set_base_power` target='opp_character' + duração 'this_turn' — OP07-002 Ain.
  Cuidado: bug de indentação detectado e corrigido durante a implementação
  (o bloco m_opp foi inadvertidamente indentado dentro do if, quebrando o
  for loop original — PERDEU=2 transitório, corrigido, validado PERDEU=0).
- `opp_don_on_field_lte` condição (simétrica à `opp_don_on_field_gte`) —
  PRB02-005 Luffy (oponente tem 7 ou menos DON).
- `rest_opp_don` dispatch broadened: aceita "rests" (conjugado) além de
  "rest" — PRB02-005 "your opponent rests 1 of their active DON!! cards."
- `opp_shuffle_hand_into_deck` com `draw_back=N` — OP06-047 Charlotte Pudding:
  força oponente a reciclar mão no deck e recomprar N. Engine + parser.
- `opp_life_to_hand` — P-009 Law: oponente move carta da própria vida para mão.
- `play_from_deck` por NOME (`filter_name`) — ST03-007, OP08-071, OP08-073.
- `buff_cost target='own_play_hand'` — OP05-097 Mary Geoise (analítico).
- `opp_place_trash_bottom_deck` player-iniciado — OP15-091 Margarita.
- `opp_shuffle_hand_into_deck` + `opp_life_to_hand` engine handlers em
  `decision_engine.py`.
- `set_active` + `set_don_active` combo (Jinbe Leader OP11-021).
- Vários outros fixes de dispatch (rests? \d+, cost sem sinal, can attack on
  the turn, look_at up to/the top N, reveal+conditional-play, bounce own type).

**23 gaps restantes** — esses exigem mecânica genuinamente nova de engine
ou são casos aceitáveis como informação-only/DB anomaly:
  - **DB anomaly**: EB03_OP05-006_p1 (ID mismatch, parses como OP05-006)
  - **Info-only**: OP01-105 Bao Huang (revelar mão do oponente), OP16-042
    Prisoner of Impel Down (regra de deckbuilding)
  - **Novo mecanismo complexo**: OP04-097/OP05-111/EB02-057 (add opp Character
    à vida face-up do oponente), OP05-058 (mass deck_bottom + equalizar mãos),
    OP06-086 Gecko Moria (jogar 2 do trash com custos diferentes), OP09-033
    Nico Robin (mass immunity temporário por tipo), OP10-022 Law Leader
    (bounce cost + peek life + conditional play), OP12-040 Kuzan Leader
    (trigger reativo ao descarte do oponente), OP14-001/017 (swap de poder),
    OP14-060 Doflamingo (redirect ataque), OP15-031 Purinpurin (KO se custo=DON
    anexado), OP02-025 Kin'emon Leader (delay cost reduction), OP03-091
    Helmeppo (set cost to 0 conditional), OP04-047 Ice Oni (end-of-battle
    trigger), EB03-031 Vinsmoke Reiju (activate Event's Main from trash),
    ST08-013 Mr.2 (mutual KO after battle), ST13-003 Luffy Leader (life rule
    change), ST15-001 Atmos (restriction add life to hand), PRB02-005 Luffy
    (delayed rest opp DON — simplification needed), EB02-057 Mad Treasure.

**Validação:** `diff_parser.py` (PERDEU=0 após correção do bug de indentação);
  `gerar_dbs.py` (2315 com efeito); `smoke_test.py` (100%);
  `smoke_test_broad.py` (40/40); `audit_replay.py --n 20 --seed 7` (0
  exceções, 0 anomalias).

---

## 2026-07-02 (6) - Claude

**Feito — Auditoria de gaps (rodada 2): 51 → 24 gaps, 2286 → 2314 com efeito.**

Esta rodada focou nos gaps que ficaram da auditoria anterior, abordando grupos
de parser com regex simples e mecânicas novas implementáveis. Mudanças
por categoria:

**Regex/dispatch corrigidos (sem mechanic nova):**
- `look_at` aceita "look at up to N" e "look at the top N" (OP02-005, OP05-117)
- `parse_reveal_top_play`: aceita "add to hand" (ST11-001) e condicional "if that
  card is X, play rested" (OP01-060, OP07-048); também "character" sem "card"
- `lock_opp_character_attack` aceita "leader or character cards" + "cards" após
  "character" (OP04-100) e "during this turn" além de "until" + `power_lte`
  (EB04-028)
- `parse_rest_opp`: dispatch broadened para "rest N" sem "up to"; aceita "cards"
  além de "characters" (P-008, OP13-033 → já commitados antes)
- `parse_cost_debuff`: dispatch broadened para custo SEM sinal + sinal fullwidth
  － (P-076, OP08-082, OP08-083 + 6 bônus em cartas existentes)
- `parse_can_attack_active` + dispatch: aceita "can attack characters on the turn
  in which it/they is/are played" = Rush semântico (OP04-096, OP11-027 + bônus)
- Dispatch `parse_play_from_trash`: cobre "play this character card from your
  trash" + "add this character card to your hand" (P-071, OP09-052, OP15-080
  Oars + bônus OP02-018, OP14-120, ST30-008)

**Mecânicas novas implementadas:**
- `opp_shuffle_hand_into_deck(draw_back=N)` — OP06-047 Charlotte Pudding:
  força oponente a reciclar mão no deck e recomprar N. Engine em
  `decision_engine.py`, parser em `gerar_effects_db.py`.
- `opp_life_to_hand` — P-009 Law: oponente move carta de sua própria vida para
  a mão (enfraquece vida dele). Parser + engine handler adicionados.
- `play_from_deck` por NOME via filter_name (em vez de filter_type): ST03-007
  Sentomaru "[Pacifista]", OP08-071 "[Baron Tamago]", OP08-073 "[Count Niwatori]".
- `opp_place_trash_bottom_deck` iniciado pelo jogador ativo: OP15-091 Margarita.
- `buff_cost` target='own_play_hand': OP05-097 Mary Geoise (registro analítico;
  engine já trata via hardcode).
- `opp_life_to_hand` + set_active OR set_don_active combos: OP11-021 Jinbe Leader.
- `gain_rush` via `parse_can_attack_active` para "can attack Characters on the
  turn in which it is played" (OP04-096 Corrida Coliseum passivo + OP11-027).
- `give_don` target-first: `give [alvo] up to N rested DON!!` — ST01-001 + bônus.

**Bugs colaterais corrigidos no processo:**
- `parse_look_at` guard life-cards: impede falso positivo para "look at ... Life
  cards" (EB02-053, OP03-099 perdiam look_top_deck que estava errado; corrigido
  para não mais disparar nesses casos).
- OP11-062, OP11-070: perderam look_top_deck incorreto sobre o deck do OPONENTE;
  esses efeitos eram no-op silencioso incorreto antes.

**Gaps restantes (24):** maioria exige mecânica genuinamente nova —  swap de
poder (OP14-001/017), redirect ataque (OP14-060), trigger reativo ao descarte do
oponente (OP12-040), efeito com "at the end of a battle" (OP04-047, ST08-013),
adicionar character do oponente à vida dele (OP04-097, OP05-111, EB02-057),
regra de baralho (OP16-042, EB03_OP05-006_p1 = ID mismatch, OP01-105 = info).

**Validação:** `diff_parser.py` (PERDEU=0 em todos os rounds);
  `gerar_dbs.py` (2314 com efeito); `smoke_test.py` (100%);
  `smoke_test_broad.py` (40/40); `audit_replay.py --n 20 --seed 7` e
  `--n 15 --seed 99` (0 exceções, 0 anomalias).

---

## 2026-07-02 (5) - Claude

**Feito — dead wood + reauditoria de cartas com effects vazio.**

**Dead wood (linha 477 do TODO):** item "substituição externa OP07-029/OP16-014
  fora de escopo" estava desatualizado — ambas implementadas na sessão de hoje.
  Marcado como `[x]` no TODO.

**Reauditoria de effects vazios:** contagem real era 2286 com efeito (não
  "2148" do TODO antigo). Script de varredura identificou 54 gaps reais
  (excluindo NULL, variantes de ID canônico, errata) em 3 grupos. O Grupo C
  (parser menores) foi corrigido na hora — 9+ cartas novas + 20+ ajustes
  em cartas existentes:
  - `gain_can_attack_active` aceita variante "your opponent's active
    Characters" (OP01-021, OP02-014, OP06-110, +1).
  - `give_don` aceita "Give [target] up to N rested DON!!" com alvo antes
    de "up to" — ST01-001 + 6 cartas com give_don em on_play/activate_main
    que vinham sem esse step.
  - `opp_place_trash_bottom_deck` player-iniciado ("Place up to N card from
    your opponent's trash at the bottom of the owner's deck") — OP15-091.
  - `rest_opp_character` sem "up to" e aceitando "cards" em vez de
    "characters" — P-008 Yamato, OP13-033 Franky + custo cost_lte em 8
    cartas que tinham rest_opp_character sem o filtro de custo.
  - `play_from_trash filter_self=True` mapeado de "add this Character card
    to your hand" (K.O. recovery) — P-071 Marco.
  - `set_active + set_don_active` combinados para "Set this Character or
    up to N DON!! cards as active" — OP13-035 Bepo.
  Grupo B (~30+ cartas) deixado para futuros itens: swap de poder, redirect
  ataque, triggers de "quando oponente descarta", etc.

**Validação:** `diff_parser.py` (`PERDEU=0`, 6 GANHOU + 20 MUDOU);
  `gerar_dbs.py` (2286 com efeito); `smoke_test.py` (100%);
  `smoke_test_broad.py` (40/40); `audit_replay.py --n 20 --seed 7` e
  `--n 15 --seed 99` (0 exceções, 0 anomalias).

---

## 2026-07-02 (4) - Claude

**Feito — timing `when_rested` + fix typo OP14-119 (Mihawk).**

Dois problemas paralelos bloqueavam OP14-119 completamente:
1. **Typo no CSV**: "with a cost **or** 9 or less" em vez de "**of** 9".
   Fix: regex de `lock_opp_cannot_be_rested` aceitando `(?:of|or)` antes do
   número (1 linha em `gerar_effects_db.py`).
2. **Timing "when becomes rested" sem parser**: novo `when_rested` em
   `trigger_patterns`, posicionado **antes** de `your_turn` para ter prioridade,
   com lookahead negativo em `your_turn` para não duplicar o bloco. Engine:
   `when_rested` disparado em `_execute_attack` após `attacker.rested = True`.

Bônus: 5 outras cartas do set OP14 (OP14-021/027/028/032/035) que também usam
"When this Character becomes rested" estavam sendo classificadas como
`your_turn` (disparavam no início de cada turno, não quando a carta de fato
ficava rested). Agora migradas para `when_rested` corretamente.

**Simplificação documentada:** `when_rested` dispara APENAS via `_execute_attack`
(carta ataca e fica rested). Resting via custo de Activate:Main (`rest_self`)
não dispara — 0 cartas reais afetadas hoje; reabrir se aparecer carta com
Activate:Main + "when becomes rested" simultaneamente.

**Validação:** `diff_parser.py` (`PERDEU=0`, 6 MUDOU corretos);
`gerar_dbs.py` + `snapshot_parser.py`; `smoke_test.py` (2 testes novos);
`smoke_test_broad.py` (40/40); `audit_replay.py --n 20 --seed 7` e
`--n 15 --seed 99` (0 exceções, 0 anomalias).

---

## 2026-07-02 (3) - Claude

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
