# Ferramentas do projeto — catálogo resumido

> Referência rápida pra não esquecer o que já existe antes de escrever
> um script novo. Se uma tarefa parece "eu preciso de algo que compare
> X com Y" ou "meça a eficiência de Z", procure aqui primeiro — quase
> sempre já existe. Organizado por PROPÓSITO, não ordem alfabética.
> Todos os comandos abaixo rodam a partir de `scriptis_da_ia/`, salvo
> indicação contrária.

## 1. Comparar a IA com jogadas reais (humano ou log real)

- **`compare_vs_human.py`** — pega um log de partida real PARSEADO
  (`logs/parsed/*.json`) e, turno a turno, reconstrói o estado exato e
  roda o Turn Planner (`_generate_and_score_actions`) pra comparar a
  sugestão da IA com o que o jogador daquele lado realmente fez.
  Aponta `DIVERGENCIA` quando nenhuma ação exata do humano aparece no
  top-K da IA. **Foi assim que achamos o bug real de `ST22-015`
  (bloco HANDOFF 386) — é a ferramenta certa pra "por que o bot não
  jogou como eu jogaria".**
  ```
  python compare_vs_human.py logs/parsed/<arquivo>.json --player <nome_do_lado>
  python compare_vs_human.py logs/parsed <pasta ou arquivo> --summary   # agregado
  ```
- **`audit_human_patterns.py`** — extrai padrões de pilotagem humana
  agregados de vários logs parseados (ordem de jogada, combos, uso de
  counter/defesa) pra alimentar sinais de calibração, sem tratar 1 log
  como regra absoluta.
- **`decision_summary.py --latest`** — gera um `.txt` legível ao lado
  do `receipt_<timestamp>.json` mais recente (telemetria de uma
  partida AO VIVO real, não log parseado): mostra, pra cada decisão do
  bot, a ação ESCOLHIDA e as melhores alternativas descartadas com
  score. **Leitura obrigatória depois de qualquer log de partida do
  bot ir pro banco** (regra do CLAUDE.md) — só funciona em sessão
  LOCAL (a telemetria é gitignored).
- **`audit_decision_quality.py --n 25 --seed 7`** — mesma ideia, mas
  pra partidas SIMULADAS (self-play), não log real: resume como o
  Turn Planner escolheu cada ação (contexto, candidatos, escolha).
- **`diag_lethal_don_alloc.py`** — diagnóstico específico (não fix):
  compara o DON que `can_lethal_this_turn_alloc()` certifica como
  suficiente contra o que a política real de anexação daria, no MESMO
  estado — usado pra validar hipótese antes de mexer em alocação de
  DON pra lethal.

## 2. Medir eficiência / regressão de qualidade (com números, não prosa)

- **`bot_efficiency_report.py`** — relatório reprodutível de eficiência
  observável a partir de combat logs parseados (`logs/parsed/`, já
  banco, sem precisar de telemetria local). Métricas: `dano_por_jogo`,
  `don_observado_por_ataque`, `atk_por_turno`, `turnos_passivos_por_jogo`,
  com IC95% via bootstrap. Usa um **manifesto de cohorts**
  (`metrics/bot_efficiency_cohorts.json` por padrão) — **não existe
  cohort "atual" fixo, tem que atualizar/gerar um novo agrupando as
  partidas relevantes antes de rodar**, senão compara com partidas
  antigas e engana.
  ```
  python bot_efficiency_report.py --manifest metrics/meu_cohort.json
  python bot_efficiency_report.py --decision-log ..\BOT\engine_server\logs\decisions\decisions_<ts>.jsonl
  ```
- **`compare_bot_reports.py`** — compara 2 relatórios do proxy sem
  misturar execução (o clique funcionou?) com estratégia (a decisão
  era boa?) — indica se cada métrica subiu/desceu do jeito certo.
- **`baseline_metrics.py`** — bateria DETERMINÍSTICA motor-vs-motor
  (auto-relança com `PYTHONHASHSEED=0`), o "marco-zero" pra qualquer
  mudança de peso/heurística: roda antes e depois, só é "feito" se o
  winrate não regride.
- **`tune_weights.py`** — otimizador de pesos de `evaluate_state_v2`
  via self-play determinístico + coordinate-ascent, critério MAXIMIN
  (melhora sem regredir nenhum matchup do gauntlet). Resultado salvo
  em `eval_weights.json` (o motor carrega automaticamente).
- **`measure_lethal_don_fix.py`** — mesma metodologia pareada do
  `tune_weights.py`, mas comparando uma FLAG on/off (ex: fix de
  alocação de DON em lethal) em vez de pesos.
- **`audit_antipatterns.py`** — roda partidas motor-vs-motor com decks
  REAIS e acusa turno a turno anti-padrões de pilotagem (DON ocioso,
  líder nunca atacou, etc.) — pra achar isso ANTES de gastar uma
  partida real do usuário testando.
- **`audit_replay.py`** — N matchups reais via `ReplayMatch`,
  reportando violação de invariante (`decision_log`, `kind ==
  'invariant_violation'`): conservação de DON, poder nunca negativo,
  contagem de cartas.

## 3. Parser de texto de carta → efeitos estruturados

- **`gerar_effects_db.py`** → gera `card_effects_db.json` a partir de
  `cards_rows.csv` (o parser em si).
- **`gerar_card_analysis_db.py`** → gera `card_analysis_db.json` (o
  banco que o analisador de decks GRÁTIS do front consome).
- **`gerar_dbs.py`** → gera os DOIS num passo só (porta única).
- **`snapshot_parser.py`** / **`diff_parser.py`** → rede de segurança
  obrigatória ao mexer no parser: `snapshot_parser.py` ANTES da
  mudança, `diff_parser.py` DEPOIS pra ver exatamente o que mudou
  (`PERDEU=0` é o padrão esperado). Ver skill `optcg-parser-audit`.
- **`audit_card_effects.py`** — roda partidas reais instrumentadas e
  responde: quais triggers parseados nunca disparam, quais disparam
  sem produzir log observável (handler no-op), por que a IA decidiu
  NÃO ativar um `activate_main` especificamente.
- **`audit_parser_coverage.py`** — varredura AMPLA do banco inteiro
  procurando um NÚMERO que aparece no texto real da carta e não
  aparece em lugar nenhum do que o parser entendeu (acha a FORMA do
  bug, não card a card).
- **`audit_leader_and_goal.py`** — mostra lado a lado o texto cru da
  carta e o que o parser entendeu, focado no efeito do líder + no
  objetivo "reduzir vida do oponente a 0".
- **`censo_padroes.py`** — classifica cartas ainda sem `effects`
  parseado por PADRÃO estrutural de texto (não carta a carta), gera
  contagem por padrão.
- **`propostas_completo.py`** — rascunho de `effects` propostos pras
  cartas não classificadas (com nível de confiança), material de
  trabalho pro parser, não script de execução.

## 4. Banco de logs de partida real

- **`parse_combat_log.py`** — converte 1 combat log em JSON
  estruturado + gerencia o banco (`logs/{raw,parsed,decks}/` +
  `logs/index.json`). **Uso obrigatório sempre que um combat log
  chegar** (`--add-to-db`), ver skill `optcg-live-log-triage`.
  ```
  python parse_combat_log.py partida.log --add-to-db
  python parse_combat_log.py --list-db
  ```
- **`importar_logs_autosaved.py`** — converte os `.log` da pasta
  `AutoSaved` do simulador (que ficam pra trás quando o jogo
  atualiza/reinstala) pro formato do banco, em lote.
- **`collect_latest_match.py`** — preserva o combat log mais recente +
  gera o relatório da sessão num comando só; também é chamado
  automaticamente pelo `engine_server` quando recebe `outcome`.

## 5. Visualização / replay de partida

- **`replay_optcg.py`** — replay visual de uma partida (decklists
  reais) pra validar o simulador turno a turno; DELEGA a orquestração
  de turno pra `OPTCGMatch.play_turn()` (não reimplementa, ver regra
  sem-duplicação) — vira "só visualização" desde a unificação.

## 6. Análise estática de deck (produto grátis, sem simular partida)

- **`deck_analyzer.py`** — motor de análise estática (arquétipo,
  sinergias, coesão) exposto via `api.py`. Fonte única pro front.
- **`deck_profile.py`** — deriva os EIXOS de avaliação específicos de
  um deck a partir do `card_effects_db` (generalização do
  `compute_game_plan`), sem citar carta nenhuma.
- **`card_taxonomy.py`** — vocabulário único "ação de carta →
  significado" compartilhado entre `deck_analyzer.py`/`deck_profile.py`
  (dado, não lógica de decisão).
- **`synergy_states.py`** — camada de sinergias por ESTADO
  COMPARTILHADO (cartas que criam um estado + cartas que exploram esse
  estado).
- **`tribal_cohesion.py`** — mede quão focado (tribal) um deck é no
  tipo do próprio líder, eixo separado de agressivo/controle.
- **`hand_scorer.py`** — score de mão de abertura (mulligan), espelho
  em Python da lógica do front (`/analysis`).

## 7. Simulação / backend de produção (Supabase + fila)

- **`api.py`** — API FastAPI que expõe `deck_analyzer.analyze_deck`
  (`POST /analyze`) pro front.
- **`simulation_worker.py`** — worker que roda N partidas via
  `OPTCGMatch` em background (fila + polling via Postgres), usado pelo
  simulador de "seu deck vs meta".
- **`simular_deck_usuario.py`** — CLI pra rodar simulações do deck do
  usuário salvo no Supabase.
- **`db.py`** — camada fina de acesso ao Postgres (asyncpg puro, sem
  ORM).
- **`seed_meta_decklists.py`** — popula a tabela `meta_decklists` com
  decklists reais de torneio (Limitless TCG).

## 8. Bot ao vivo (produção)

- **`BOT/engine_server/server.py`** — transporte HTTP puro
  (`/mulligan`, `/decide`, `/defense`, `/choose_target`) entre o plugin
  C# e `sim_bridge.py`. Zero heurística.
- **`optcg_engine/sim_bridge.py`** — porta entre o mundo do simulador
  e o motor (`decision_engine.py`): converte estado, chama
  `choose_action`, traduz resposta de volta.
- **`optcg_engine/decision_engine.py`** — o motor de verdade
  (`OPTCGMatch`, `DecisionEngine`). Toda decisão estratégica nasce
  aqui, nunca no plugin/server.
- **`bot_optcgsim.py`** — bot LEGADO por OCR/mouse (pré-BepInEx),
  mantido só de referência histórica; o bot atual é o plugin C# +
  `engine_server`.
- **`calibrar_prompt_bbox.py`**, **`test_ocr_code.py`**,
  **`test_scan_debug.py`**, **`test_scan_debug2.py`**,
  **`test_scan_hand.py`** — ferramentas de depuração de OCR do bot
  legado acima; obsoletas pro fluxo atual (BepInEx não usa OCR).

## 9. Testes automatizados

- **`smoke_fast.py`** — suíte RÁPIDA, rodar antes de qualquer teste ao
  vivo no OPTCGSim (pré-flight obrigatório).
- **`smoke_test.py`** — regressão AMPLA (parser, engine, execução
  real) — rodar quando mexer em parser/counters/imunidade/substituição/
  gramática de efeitos ou outra área compartilhada de alto risco.
- **`smoke_test_broad.py`** — monta decks ALEATÓRIOS válidos a partir
  do `cards_rows.csv` real e roda N partidas completas capturando
  qualquer exceção — rede de segurança ampla (não card a card) pra
  mudanças que rodam pra TODAS as cartas (ex: `execute()`).
- **`test_bot_efficiency_report.py`** — testes unitários do próprio
  `bot_efficiency_report.py`/`compare_bot_reports.py`.

## 10. Coleta de dados / ML experimental (fora do motor de produção)

- **`coletar_dados_optcg.py`** — coleta dados de Limitless TCG / OP
  Leaderboard pra treinar modelo experimental.
- **`treinar_modelo.py`** — treina modelo scikit-learn a partir dos
  dados coletados (`modelo_optcg.json`/`.pkl`) — via de ML, não é o
  motor de decisão em produção.

---

## Fluxos comuns (qual ferramenta usar quando)

| Situação | Ferramenta |
|---|---|
| "O bot fez algo estranho numa partida ao vivo" | `parse_combat_log.py --add-to-db` (se ainda não banco) → `decision_summary.py --latest` (LOCAL) → `metrics/live_runs/` |
| "O bot joga pior que eu, por quê?" | `compare_vs_human.py --player <vencedor> --summary` num log real onde alguém venceu |
| "Mudei um peso/heurística, regrediu?" | `baseline_metrics.py` antes e depois, mesma seed |
| "Quero achar o melhor peso pra X" | `tune_weights.py` |
| "Mudei o parser de uma carta" | `snapshot_parser.py` (antes) → fix → `diff_parser.py` (depois) → `gerar_dbs.py` → skill `optcg-parser-audit` |
| "Quero saber se uma FLAG específica ajuda" | `measure_lethal_don_fix.py` (adaptar o padrão) |
| "Quero visualizar uma partida decklist vs decklist" | `replay_optcg.py` |
| "Fechando a sessão" | skill `optcg-release-handoff` |
