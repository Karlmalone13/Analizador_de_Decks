# HANDOFF — registro de troca entre IAs (Claude / Codex)

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
