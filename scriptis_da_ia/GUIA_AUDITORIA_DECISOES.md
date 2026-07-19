# Guia de auditoria do Turn Planner — como o motor decide

> Documento de referência pra ler as saídas de `audit_decision_quality.py`
> sem reinterpretar os campos a cada sessão. Todas as referências de linha
> são de `scriptis_da_ia/optcg_engine/decision_engine.py` no commit
> `98e3509` (19/07/2026). Se o arquivo crescer/mudar, revalidar antes de
> confiar cegamente nos números de linha.

## 1. Visão geral: quem decide o quê

O "cérebro" inteiro vive em `decision_engine.py`. Nada disso roda no bot
(`BOT/OPTCGBotPlugin`, `BOT/engine_server`) — o bot só executa a ação que o
engine já escolheu (regra do projeto, ver `feedback_dois_motores.md`).

Por turno, `main_phase()` (linha 11392) roda um loop: gera todas as ações
possíveis, pontua, executa a melhor, repete até não sobrar ação com score
≥ 0. "Melhor" não é sempre "maior score imediato" — para as candidatas do
topo, o motor **simula a linha de jogo inteira** e compara o estado final
(Turn Planner, item 3 do `PLANO_AVALIACAO_E_BUSCA.md`).

Duas réguas diferentes entram em jogo, em momentos diferentes:

| Régua | Onde | Pra quê |
|---|---|---|
| Score imediato (`_generate_and_score_actions`) | a cada ação candidata | rankear TODAS as ações possíveis agora, decidir o TOP_K a simular |
| Valor de estado (`_evaluate_state_v2`) | fim de cada linha simulada | comparar o resultado de simular cada candidata do TOP_K até o fim do turno |

O score imediato NUNCA decide sozinho quando há mais de 1 candidata visível
— ele só ordena/filtra quem entra na simulação. Quem decide de fato é o
valor médio da simulação (Monte Carlo).

## 2. Prioridade do turno: duas funções parecidas, propósitos diferentes

**Cuidado ao auditar**: existem DUAS funções de "modo do turno" que
parecem a mesma coisa mas não são:

- **`GameAnalyzer.analysis_priority()`** (linha 8309) — usada DENTRO de
  `_generate_and_score_actions` pra ajustar os scores imediatos
  (`LETHAL`/`DEFENSIVE`/`REMOVE_THREAT`/`DEVELOP`/`ATTACK`). É o campo
  `context.priority` no log de auditoria.
- **`DecisionEngine.posture()`** (linha 8484) — combina perfil do deck
  (aggressive/control/midrange) com fase da partida
  (`AGGRESSIVE`/`DEFENSIVE`/`CONTROL`/`DEVELOP`). É o campo
  `context.posture` no log. Usada em outros pontos de decisão (ex:
  blocker/counter), não dentro do loop de score do Turn Planner.

Ambas checam `can_lethal_this_turn()` PRIMEIRO e ambas retornam algo como
`'LETHAL'`/`'DEFENSIVE'` nesse caso — por isso é fácil confundir as duas,
mas elas divergem em qualquer outro modo. **No log de auditoria, o campo
que dirige o score do Turn Planner é `priority`, não `posture`.**

### `can_lethal_this_turn()` (linha 8108) — determinístico, não probabilístico

Não conta "número de ataques ≥ vida+1". Simula o **pior caso real de
defesa do oponente**:
1. Lista os poderes de ataque disponíveis (com DON já anexado).
2. Ataques `[Unblockable]` sempre conectam.
3. Blockers do oponente (N ativos) desviam até N ataques bloqueáveis — ele
   escolhe bloquear os de MAIOR poder primeiro (pior caso pra mim).
4. O que sobra precisa ser coberto por counter conhecido/estimado da mão
   dele (distribuído greedy pra cobrir o máximo de ataques).
5. `True` só se, MESMO nessa defesa ótima, a vida dele chega a 0 E ainda
   resta 1 hit que conecta.

Isso é uma conta matemática sobre o estado **atual**, sem rodar
`_apply_action`/attack resolution de verdade e sem levar em conta a mão
REAL do oponente (ele estima blocker/counter — ver comentário do método).

### `opp_lethal_threat()` (linha 8210) — probabilístico, heurística

Retorna um FLOAT 0.0-0.95 (não bool). Base = `(hits disponíveis - hits
necessários + 1) / hits disponíveis`, depois multiplicado por fatores fixos
de blocker (`1 - 0.2*blockers`) e counter (`0.7` se ≥2000, `0.85` se
≥1000). `DEFENSIVE` dispara se isso passar de `0.6`. **Isto é uma
heurística arbitrária, não uma simulação** — bom candidato a validar contra
os 79 logs reais (a probabilidade "sentida" bate com o que realmente
acontece?).

## 3. Score imediato: `_generate_and_score_actions` (linha 10755)

Gera 3 tipos de ação e pontua cada uma:

- **`play`**: `_score_play_action` + bônus de padrão humano
  (`_human_pattern_bonus`) + ajuste de `priority` (`DEVELOP` +40,
  `LETHAL` −60) + penalidade se mão ≤ 3 cartas (preservação de recursos).
- **`attack`**: `score_attack_target` (não lido em detalhe aqui) + desconto
  de risco de trigger + bônus de prioridade (`LETHAL` +500,
  `REMOVE_THREAT` +300 se o alvo é ameaça crítica, `DEFENSIVE` −80 no
  líder) + piso de score 15 pro ataque de líder "quase grátis".
- **`activate`**: `_score_activate_main`, com guardas de custo (fonte
  restada, já usado no turno).

Cada ação é uma tupla `(score, kind, obj, target_type, target)`. A lista
final é ordenada por score desc.

## 4. Turn Planner: `main_phase()` (linha 11392)

Loop principal (até `MAX_ACOES=30` iterações por turno):

1. Gera e pontua todas as ações (§3). Se a melhor tem score < 0, encerra o
   turno.
2. **Atalho win-con**: se a ação do topo é `play` da carta-bomba do
   `compute_game_plan` e o DON já paga, joga direto sem passar pelo Turn
   Planner (não dispara em `LETHAL`).
3. **TOP_K** = 3 candidatas (com `USE_OPPONENT_RESPONSE_SEARCH=True`, o
   padrão atual) ou 6 (se desligado). Filtro: as `MIN_PLANNER_CANDIDATES=3`
   primeiras sempre entram; as demais só se estiverem a até
   `PLANNER_SCORE_WINDOW=180` pontos da melhor.
   - Em `REMOVE_THREAT`, garante pelo menos 1 `play` e 1 `activate` na
     janela mesmo que o score de remoção domine (diversidade forçada).
4. **Se só sobrou 1 candidata**, executa direto (sem Monte Carlo) — log
   ainda é registrado, mas sem `simulated_value`.
5. **Senão**, sorteia `n_monte_carlo` amostras (3 com resposta do
   oponente ligada, senão `PLANNER_MC_SAMPLES=6`) de `(mão, vida)` fictícias
   do oponente via `OpponentModel.sample` — **as MESMAS amostras pra todas
   as candidatas** (comparação pareada, menos ruído).
6. Pra cada candidata, `_simulate_sequence_values` roda 1 simulação por
   amostra e tira a média (`valor`). Conta quantas amostras deram
   `>= SIMULATED_WIN_SCORE` (`wins`).
7. Escolhe a candidata de maior `valor` médio (não maior score imediato!).
   Guarda de segurança: se a linha ataca o líder com o oponente já em vida
   0 sem lethal garantido E nenhuma amostra venceu, ela é descartada
   mesmo tendo o maior valor simulado.
8. Aplica a primeira ação da linha vencedora no estado REAL. Repete o loop.

### `_simulate_sequence_once` (linha 11268) — o que cada rodada Monte Carlo faz

1. Clona `p`/`opp` (cópia rasa de baralho + `_SimDeck` lazy pra
   performance).
2. Substitui a mão/vida do `opp` clonado pela AMOSTRA sorteada (nunca vê a
   mão real do oponente).
3. Aplica a ação candidata. **Se ela sozinha vence** (`_apply_action`
   retorna `True` — vida chega a 0 E o hit conecta), retorna
   `SIMULATED_WIN_SCORE = 50000.0` na hora.
4. Senão, continua GULOSAMENTE (sempre a ação de maior score imediato no
   estado simulado) até `max_steps=8` ou até vencer.
5. **Busca de resposta do oponente** (item 3, `USE_OPPONENT_RESPONSE_SEARCH
   = True`): depois do meu turno simulado, simula o TURNO INTEIRO de
   resposta do oponente (`_play_turn_greedy`, guloso, mesmo motor). Se essa
   resposta me mata, a linha inteira vira `-SIMULATED_WIN_SCORE` (péssima),
   mesmo que meu turno tenha parecido bom isoladamente.
6. Se ninguém venceu em nenhum dos dois lados, o valor final é
   `_evaluate_state_v2(p2, opp2)` (ou `_evaluate_state`, legado, se
   `use_v2=False` pro jogador).

**Importante**: "vencer" aqui É BINÁRIO e SÓ conta gols batidos DENTRO da
simulação (≤8 passos meus + 1 turno inteiro do oponente). Um turno que só
"pressiona muito" mas não termina o jogo dentro dessa janela nunca gera
`wins > 0` — isso é NORMAL na maioria dos turnos do meio de jogo. `win=0/N`
não é em si um sinal de bug; só vira suspeito quando combinado com
`priority=LETHAL` (§6).

## 5. `_evaluate_state_v2` (linha 11101) — a régua de fim de linha

Pesos em `EVAL_WEIGHTS` (linha 77 de `decision_engine.py` = default de
código), **sobrescritos em runtime por `scriptis_da_ia/eval_weights.json`**
se existir (é o que `tune_weights.py` grava depois de tunar por self-play —
esse arquivo existe hoje e vale mais que o default do código). Tabela
abaixo usa o valor REAL em vigor (`eval_weights.json`), com o default de
código entre parênteses quando diferem:

| termo | peso em vigor (default código) | o que mede |
|---|---:|---|
| `dmg_dealt` | `dmg` = **180** (120) | dano à vida do oponente NESTE turno simulado |
| vida própria/do oponente | `life_mult` = 1.0 | curva íngreme não-linear (`_LIFE_MARGINAL`), não é `life_count * peso` linear |
| prêmio de sobrevivência | `survival_premium` = **15** (25) | só ativa com combo caro (`don_target>=6`) ainda não disparável, vida ≤3, e oponente NÃO é arquétipo Controle |
| board próprio/do oponente | `board_mine`=1.0 / `board_opp`=0.8 | `char_value_score` (já pesa blocker/rush/imunidade) |
| blockers do oponente vivos | `opp_blocker` = 25 | penalidade — travam meu próximo ataque |
| mão | `hand_first`=8 (até 5 cartas) / `hand_extra`=3 (excedente) | retorno decrescente |
| counter na mão | `counter_hand` = **9** (6) | `/1000`, i.e. 1000 de counter = 9 pontos |
| DON no campo | `don_field` = 4 | ramp em direção à bomba |
| cobertura defensiva | `coverage` = 7 | counter na mão vs ataques esperados do oponente no próximo turno, com teto (satura) |
| `wincon_ready` | **20 (só default — não está em `eval_weights.json`)** | "arma carregada": peça-motor na mão + fuel no trash + DON rumo ao custo |
| eixos derivados do perfil | `ax_trash`/`ax_reanim`/`ax_inversion` | ver `deck_profile.py` — termos específicos do arquétipo do deck (mill, reanimação, "inversão" de vida baixa) |

Isso é uma régua **linear e aditiva** com pesos fixos (por deck, se
tunados) — não há nenhuma noção de "risco"/variância entre os termos, só
soma ponderada do estado médio das N amostras.

**Nota de auditoria**: `wincon_ready` (peso 20) não aparece em
`eval_weights.json` — ou nunca foi tunado por `tune_weights.py`, ou foi
tunado e descartado. Vale confirmar qual dos dois antes de assumir que o
peso 20 é intencional/validado, já que todos os outros termos que existiam
em 13/07 (quando `EVAL_WEIGHTS` foi criado) já têm entrada tunada no JSON.

## 6. Campos do log de auditoria (`_log_turn_planner_decision`, linha 12078)

Cada entrada `kind='turn_planner'` no `decision_log` tem:

- `context.priority` — `analysis_priority()` no momento da decisão (§2).
- `context.posture` — `posture()` no mesmo momento (§2, cuidado: campo
  diferente, não confundir).
- `context.can_lethal` — bool cru de `can_lethal_this_turn()` (fonte da
  verdade pra saber se o motor "achava" que tinha lethal garantido).
- `context.opp_lethal_threat` — float 0-0.95 de `opp_lethal_threat()`.
- `top_immediate` — a ação de MAIOR SCORE IMEDIATO (antes de qualquer
  simulação).
- `chosen` — a ação REALMENTE executada (pode ou não ser a `top_immediate`
  — se não for, é um "override" do Turn Planner).
- `candidates` — até 8 candidatas simuladas, cada uma com
  `descartada_porque` (motivo textual do porquê perdeu pra `chosen`).

Cada ação (`action_label` em `audit_decision_quality.py`, linha 52) mostra:

```
<kind> <código> <nome> [-> alvo] score=<imediato> sim=<valor médio simulado> win=<wins>/<samples>
```

- **`score`**: score imediato desta ação isolada (§3) — NÃO leva em conta
  simulação nenhuma.
- **`sim`**: média de `_evaluate_state_v2` (ou `SIMULATED_WIN_SCORE`
  puxando a média pra cima) sobre as N amostras Monte Carlo — só existe se
  essa ação passou pelo Turn Planner (não existe quando só sobrou 1
  candidata, §4 passo 4).
- **`win=W/S`**: `W` das `S` amostras em que a linha simulada literalmente
  terminou o jogo (`_apply_action` retornou `True` em algum ponto da minha
  simulação). `S` é sempre 3 hoje (`USE_OPPONENT_RESPONSE_SEARCH=True`).
  **Não confundir com "% de vitória projetada do estado"** — é só "quantas
  das 3 amostras esse turno específico já fechou o jogo".

### O que `audit_decision_quality.py` já cataloga sozinho (`summarize`, linha 73)

- **`large_overrides`**: `chosen != top_immediate` E a diferença de score
  imediato entre eles é ≥ 60. Ou seja, o Turn Planner trocou a jogada de
  maior score isolado por outra com pior score mas melhor valor simulado.
  **Não é bug por si só** — é o comportamento pretendido do Turn Planner.
  Vira suspeito quando o gap é enorme (milhares de pontos) e ambos os lados
  têm `win=0/N` — nesse caso não dá pra confiar que a simulação captou a
  diferença real (ver achado abaixo).
- **`early_activates`**: `activate` escolhido em fase `early` com campo
  próprio ≤ 1 carta — heurística de possível ineficiência (ativar antes de
  desenvolver).
- **`nonlethal_zero_life_attacks`**: ataque ao líder escolhido quando
  `opp_life == 0` mas `can_lethal_this_turn()` era `False` E a simulação
  não achou vitória (`wins == 0` ou sem amostras). Candidato a "ataque
  desperdiçado" — o motor achou que não fechava (`can_lethal=False`) mas
  atacou mesmo assim sem confirmação simulada.

## 7. Achado confirmado em volume (N=8, 353 decisões do Turn Planner, seed=7)

`python audit_decision_quality.py --n 8 --seed 7 --json-out audit_8.json`.
Prioridades observadas: `{'DEVELOP': 96, 'REMOVE_THREAT': 129, 'ATTACK': 68,
'LETHAL': 53, 'DEFENSIVE': 7}`. Nos 6 `large_overrides` exibidos, **5 têm
`priority=LETHAL`**; desses 5, **4 mostram `win=0/3` em TODAS as
candidatas simuladas** (o ataque top E a jogada escolhida) — ou seja, o
motor achou `LETHAL` garantido mas NENHUMA das 3 amostras Monte Carlo
efetivamente fechou o jogo em nenhuma linha testada:

```
T14 PB prio=LETHAL vida=2/0 campo=2/4 DON=6
  top:     attack St. Shepherd Ju Peter -> leader   score=10520.0 sim=None
  escolha: play Saint Shalria                        score=45.0   sim=604.1  win=0/3
    cand: attack St. Shepherd Ju Peter -> leader     score=10520.0 sim=580.6 win=0/3
    cand: attack St. Shepherd Ju Peter -> character  score=155.0  sim=580.6 win=0/3
    cand: play Saint Shalria                         score=45.0   sim=604.1 win=0/3
```

(mesmo padrão em T9 PA, T12 PB, T11 PA — sempre `vida_opp=0` ou vida baixa,
sempre `win=0/3` em TODAS as linhas simuladas apesar de `priority=LETHAL`.)

**Caso de controle, mesma amostra (T13 PB)** — mostra que a maquinaria SABE
detectar vitória quando ela realmente está lá, então o problema não é "o
contador de vitória nunca funciona":

```
T13 PB prio=LETHAL vida=0/0 campo=4/2 DON=10
  top:     attack Otama -> leader                    score=10490.0 sim=None
  escolha: play Gol.D.Roger (SP)                      score=310.0  sim=50000.0 win=3/3
    cand: attack Otama -> leader                       score=10490.0 sim=-50000.0 win=0/3
    cand: play Gol.D.Roger (SP)                        score=310.0  sim=50000.0  win=3/3
```

Aqui o ataque direto (`top_immediate`) na verdade PERDE a simulação
(`sim=-50000`, ou seja: nas 3 amostras, a resposta do oponente simulada —
item 3, `_play_turn_greedy` — me mata de volta), enquanto jogar Gol.D.Roger
primeiro fecha o jogo nas 3 amostras. Esse é o Turn Planner funcionando
EXATAMENTE como pretendido: descartando o score imediato gigante do ataque
"óbvio" porque a simulação prova que essa linha perde.

**A diferença entre T13 (correto) e T14/T9/T12/T11 (suspeito) não é a
maquinaria de detecção de vitória — é que nos 4 casos suspeitos NENHUMA
linha vence, nem o ataque nem a alternativa**, apesar de `can_lethal_this_
turn()` ter certificado que existe uma alocação de ataques+DON que
GARANTE lethal no pior caso. Ou a certificação está errada, ou a execução
simulada não está reproduzindo a alocação que a certificação assumiu.

## 8. Causa raiz — VALIDADA por instrumentação (19/07/2026)

> Atualização: a hipótese abaixo foi confirmada. `scriptis_da_ia/
> diag_lethal_don_alloc.py` (diagnóstico, não mexe em lógica de jogo —
> só monkeypatcha `GameAnalyzer.analysis_priority` pra capturar e comparar,
> depois restaura o original) instrumentou 3 partidas reais (`--n 3 --seed
> 7`) e comparou, em TODO momento em que `can_lethal_this_turn()` certificou
> lethal garantido, a alocação de DON que a certificação exigiu contra a
> alocação que `don_needed_for_attack`/`_don_livre_for_plan` de fato dariam
> pro mesmo atacante no mesmo estado.
>
> **Resultado: 1165 de 1413 momentos (82,4%) — a alocação real de DON é
> MENOR que a certificada em pelo menos 1 atacante.** Exemplo capturado:
> ```
> T5 don_disp=10 don_livre_plan=5 opp_vida=2 opp_campo=3 opp_blockers=0
>   Imu (Alternate Art): certificado=10 real=4
> ```
> Com 10 DON disponíveis e prioridade LETHAL, a certificação diz "aloque
> os 10 no líder"; a execução real só libera 4 (`don_livre_plan` já reservou
> 5 pro "resto do plano do turno", mesmo sem existir resto de plano que
> valha mais que fechar o jogo agora). **A cada 3 partidas simuladas, isso
> acontece em ~82% dos momentos de LETHAL certificado — não é um caso raro.**
>
> Cuidado de leitura: os 1413 momentos NÃO são 1413 decisões reais de turno
> — `analysis_priority()` é chamado a cada candidata × amostra Monte Carlo
> × passo da simulação gulosa (inclusive dentro da busca de resposta do
> oponente), então o mesmo estado real gera dezenas de chamadas. O que
> importa é a TAXA (82%), não o volume bruto.

**Como o mecanismo funciona (a hipótese original, agora confirmada):**

`can_lethal_this_turn()` (§2, linha 8191, `search_alloc`) resolve um
problema de alocação: distribui `don_total = self.me.don_available`
livremente entre TODOS os ataques disponíveis, testando se ALGUMA
distribuição faz `hits_after_best_defense(...) >= target_hits` no pior
caso de bloqueio/counter do oponente. É uma busca completa e sem
restrição — o DON está 100% livre para qualquer ataque.

A execução real (ao vivo e dentro da própria simulação do Turn Planner)
NÃO segue essa alocação. Cada ataque vira uma ação SEPARADA em
`_generate_and_score_actions`, e o DON anexado a ele vem de
`_attach_don_for_attack` → `don_needed_for_attack` (linha 1535), que separa
o DON em duas partes:

1. **Déficit base** (cobrir a diferença de poder) — sempre pago,
   obrigatório.
2. **Margem de counter** (DON extra pra superar o counter provável do
   oponente) — pago **só com `don_livre`**, isto é, o que sobra depois de
   `_don_livre_for_plan` (linha 11538) reservar DON para as jogadas/
   ativações QUE O PRÓPRIO PLANNER AINDA PRETENDE FAZER neste turno + a
   reserva de defesa (`_don_reserve_for_defense`).

**O ajuste de `priority == 'LETHAL'` só mexe no SCORE** (`s_leader += 500`,
linha 10813; `base -= 30` em jogar carta, linha 10693) — ele nunca manda
`_don_livre_for_plan`/`don_needed_for_attack` ignorarem a reserva do plano
e comprometerem TODO o DON disponível na margem de counter. Ou seja: o
motor fica mais inclinado a ESCOLHER atacar quando está em `LETHAL`, mas
a quantidade de DON que de fato anexa ao ataque continua limitada pela
mesma lógica "não gasta o que o plano do turno ainda vai precisar" —
mesmo quando não deveria sobrar "plano do turno" nenhum (se dá pra
fechar o jogo agora, não existe jogada futura a proteger).

**Isso bate com os 4 casos observados**: campo do oponente com vários
personagens (`campo` do oponente 4, 3, 2, 3 nos 4 exemplos — sempre ≥ o
meu), ou seja, cenários com blocker/counter reais disponíveis pro
oponente, exatamente onde a margem de counter FARIA diferença entre
conectar ou ser bloqueado. Não é coincidência que `T13` (o caso que
funciona) tem vida 0/0 e DON=10 — provavelmente há DON de sobra bastando
mesmo com a reserva do plano, então a lacuna nunca aparece.

**Mudança de código feita nesta sessão para permitir a validação (aditiva,
sem alterar comportamento)**: `can_lethal_this_turn()` foi refatorada pra
delegar a uma `_lethal_search()` privada; um novo método
`can_lethal_this_turn_alloc()` expõe a alocação de DON vencedora (antes
descartada — a busca só retornava `bool`). `can_lethal_this_turn()`
continua retornando exatamente o mesmo `bool` de sempre — `smoke_fast.py`
100% verde depois da mudança, zero regressão de comportamento.

**Fix implementado (19/07/2026)**, atrás da flag `FIX_LETHAL_DON_ALLOCATION`
(default `True`, mesmo padrão de `USE_EVAL_V2`): `_don_livre_for_plan`
agora checa `engine.analyzer.can_lethal_this_turn()` no início e, se `True`,
retorna `p.don_available` inteiro (sem reservar nada pro "resto do
plano"/defesa). Validado:

- `smoke_fast.py`/`smoke_test.py`: 100% verde. Precisou corrigir 1 teste
  existente (`test_don_reservado_para_ativar_wincon_em_campo`) cujo `opp`
  tinha `life=[]` por omissão (não por intenção) — o novo fix certificava
  lethal trivial pra esse estado degenerado e mascarava o que o teste
  realmente queria validar (reserva de DON pro `activate`). Corrigido dando
  ao `opp` uma vida realista (4), preservando a intenção original do teste.
- `diag_lethal_don_alloc.py --n 3 --seed 7` (mesmas 3 partidas de antes):
  `don_livre_plan` agora É SEMPRE IGUAL a `don_disponivel` nos momentos
  LETHAL (confirma que a reserva parou de roubar DON). O "gap" bruto do
  script caiu de 82,4% (1165/1413) pra 39,4% (251/637), mas isso
  provavelmente é RUÍDO do próprio script: `can_lethal_this_turn_alloc()`
  expõe A PRIMEIRA alocação que a busca encontrou (a que dá MAIS DON pro
  primeiro atacante), não a alocação MÍNIMA — `don_needed_for_attack` pode
  legitimamente decidir que precisa de menos DON pra mesma cobertura e
  ainda assim conectar. O gap residual não necessariamente é bug; o
  diagnóstico de DON não é o critério final.
- **Medição pareada rigorosa (19/07/2026, `measure_lethal_don_fix.py`,
  mesmo padrão de `tune_weights.py`: self-play determinístico,
  `PYTHONHASHSEED=0`, mesma seed nos dois lados, MC=4, N=20 por matchup)**:

  | matchup | winrate antes | winrate depois | delta | turnos médios antes→depois |
  |---|---:|---:|---:|---|
  | Krieg (controle) | 0,55 | 0,60 | **+0,05** | 14,8 → 14,2 |
  | Kid (aggro) | 0,50 | 0,75 | **+0,25** | 12,8 → 11,4 |
  | Barba Negra BY (Teach) | 0,95 | 0,90 | **−0,05** | 11,3 → 10,8 |

  Maximin da margem = **−0,05** — pela regra estrita (maximin ≥ 0, mesmo
  critério de `tune_weights.py`), isto TECNICAMENTE reprova o fix. Leitura
  honesta antes de decidir:
  - **Kid +0,25 é sinal forte** (5 de 20 partidas viraram — não é ruído de
    1 partida).
  - **Teach −0,05 é 1 partida de 20**, e Teach já estava em 0,95 (perto do
    teto) — pouquíssimo espaço pra subir, então a variância natural nesse
    matchup tende a aparecer como queda, não alta. Não dá pra distinguir
    de ruído com N=20 aqui.
  - **Turnos médios até fechar caíram nos 3 matchups, sem exceção** — é
    exatamente o efeito mecânico que o fix deveria ter (motor fecha mais
    rápido quando tem lethal), e é um sinal mais direto/menos ruidoso que
    winrate agregado.
  - **Ainda faltando antes de aceitar/rejeitar com confiança**: rodar
    Teach isoladamente com N maior (50, o tier de "decisão de tuning" do
    protocolo do projeto) pra saber se o −0,05 é real ou ruído — é o único
    ponto que bloqueia o maximin hoje.

**Script de diagnóstico** (fica no repo, reutilizável, não é fix):
`scriptis_da_ia/diag_lethal_don_alloc.py --n <partidas> --seed <seed>`.
Monkeypatcha `GameAnalyzer.analysis_priority` com uma trava de reentrância
(`_don_livre_for_plan` chama `_generate_and_score_actions` internamente,
que re-invoca `analysis_priority` pro mesmo estado — sem a trava, a
instrumentação reentra nela mesma e explode combinatorialmente; isso
travou a primeira tentativa por quase 1h antes de eu perceber e matar o
processo). Restaura o original no `finally`, então rodar o script não deixa
nenhum estado modificado no engine depois que termina.

## 9. Como rodar

```powershell
cd scriptis_da_ia
python audit_decision_quality.py --n 25 --seed 7 --json-out audit_25.json
python diag_lethal_don_alloc.py --n 10 --seed 7   # comparação certificado vs. real de DON em LETHAL
```

`--decks` controla quantos decks reais de `decklists_raw.csv` carregar
(default 16, pareados aleatoriamente por partida). `--examples` controla
quantos exemplos de cada categoria imprimir (default 8, só em
`audit_decision_quality.py`). O JSON de saída de `audit_decision_quality.py`
tem os mesmos dados agregados (`summarize()`), útil pra cruzar com os 79
logs reais depois. `diag_lethal_don_alloc.py` é mais lento por partida (a
instrumentação roda em cima de toda chamada de `analysis_priority`, não só
nas decisões reais de turno) — comece com `--n` baixo (3-5) antes de subir
o volume.
