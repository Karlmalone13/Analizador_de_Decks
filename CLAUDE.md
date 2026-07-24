# CLAUDE.md — guia para qualquer sessão nova (Claude Code / Codex)

## LEITURA OBRIGATÓRIA ANTES DE QUALQUER COMMIT

> **ESTADO ATUAL OBRIGATORIO - proxy/telemetria (18/07/2026):** antes de
> alterar bot, engine server, logs ou metricas, leia o bloco **267** no topo de
> `HANDOFF.md` e `specs/metrics-protocol.md`. Baseline:
> `0c96391 feat(metrics): endurece proxy e coleta de logs`.
>
> Invariantes: confirmar banco somente apos validar index/raw/parsed/decks e o
> nome `Lider-Cores_x_Lider-Cores_timestamp`; `match_id` nasce no mulligan e
> permanece ate `outcome` (nunca recriar em `/decide`); manter estado, decisao,
> execucao e resultado separados; preservar alertas, latencia, confirmacao
> semantica e comparacao entre commits. GameOver/AutoSaved **resolvido** (era
> DLL do plugin desatualizada, nao logica -- rebuild via `setup_bepinex.ps1`
> antes de qualquer teste ao vivo daqui pra frente). Pendente ao vivo:
> `state_after_coverage_pct` < gate 95%, 3 `semantic_transition_failed`,
> `winner: null` cosmetico no index, prompts auxiliares e calibracao com
> 20-50 partidas. Em partida real, conferir
> `[AUTO-COLLECT] LOG SALVO NO BANCO` e o recibo em `metrics/live_runs/`.

### Gate obrigatório: auditoria global do parser

Ao encontrar erro em uma carta, busque a mesma gramática em todo o banco
antes de corrigir. Mudanças em `gerar_effects_db.py` ou
`card_effects_db.json` exigem um registro em `scriptis_da_ia/parser_audits/`.
O hook de pre-commit bloqueia a ausência desse registro. Se a busca encontrar
apenas a carta inicial, use `isolated_after_global_scan`.

**Corrija de forma GENÉRICA, não amarrada à carta que revelou o bug**
(pedido explícito do usuário, 16/07). Um regex/condição corrigido deve
cobrir a FORMA do problema (ordem de cláusulas, sinônimos de verbo,
variantes de fraseado), não só o texto exato da carta que expôs o gap —
senão a próxima carta nova com a mesma forma, mas palavras diferentes,
quebra de novo e exige outro fix. Exemplo real: o fix de
`place_opp_character_bottom_deck` (bloco HANDOFF 199) não hardcodeou "2
alvos encadeados" pra EB03-021 — generalizou pra QUALQUER número de
alvos via `and up to N Character(s)`, e ficou ordem-agnóstico pra
custo/power em vez de assumir a ordem em que a carta-gatilho os
mencionava.

Antes de commitar qualquer coisa, leia as memórias do projeto:

```
C:\Users\arthu\.claude\projects\C--Projetos-TI-analidador-de-decks-optcg\memory\MEMORY.md
```

As memórias contêm regras arquiteturais e feedbacks do usuário que DEVEM ser
seguidos. Ignorar essas memórias pode levar a violações de arquitetura que o
usuário já corrigiu explicitamente. Regras-chave (resumo — leia os arquivos
completos):

- **Bot = olhos/mãos only** (`bot_optcgsim.py`). Engine = cérebro. Sem lógica
  de carta no bot. Sem dois motores. Ver `memory/feedback_dois_motores.md`.
- **Objetivo do bot**: captar logs contra humanos → validar engine → front-end.
  Não otimizar o bot além disso. Ver `memory/project_objetivo_bot.md`.

---

Este arquivo é lido automaticamente no início de cada sessão do Claude Code.
Leia também o [HANDOFF.md](HANDOFF.md) (registro do que foi feito na sessão
anterior, por qual IA) antes de tocar em qualquer coisa, e rode
`git log --oneline -10` + `git status` para ver o estado real.

## O que é o projeto

Analisador de decks de **One Piece TCG (OPTCG)**: classifica arquétipo,
detecta sinergias, mede coesão tribal, e simula partidas completas entre dois
decks com IA jogando os dois lados. Duas partes bem separadas:

### 1. Front-end (`src/`) — Next.js 16 + React 19 + Supabase
- App Router (`src/app/*/page.tsx`): `/`, `/cards`, `/deck`, `/analysis`,
  `/meus-decks`, `/simulate`.
- Supabase: auth + tabela `cards` (banco de cartas) + tabela `decks` (decks
  salvos do usuário, coluna `cards` é um JSON string `{leader, cards}`).
- Stack: TypeScript estrito, Tailwind, ESLint com regras de React Hooks
  (`react-hooks/set-state-in-effect` etc. — **rodar `npx eslint` e
  `npx tsc --noEmit` antes de considerar algo pronto**, o projeto tem zero
  erros hoje, não regredir).
- Páginas que usam `useSearchParams()` precisam estar envolvidas em
  `<Suspense>` (senão `next build` quebra) — ver `/analysis`, `/deck`,
  `/simulate` como referência do padrão usado.

### 2. Back-end Python (`scriptis_da_ia/`) — duas sub-partes

**a) Analisador de deck (produção, hospedado no Railway)**
Pipeline: `cards_rows.csv` → `gerar_effects_db.py` (parser texto→efeitos) →
`card_effects_db.json` → `gerar_card_analysis_db.py` → `card_analysis_db.json`
→ `deck_analyzer.py` (classifica arquétipo/sinergias/coesão) → `api.py`
(FastAPI, `POST /analyze`). Front consome via `NEXT_PUBLIC_ANALYZER_API`.
Detalhes completos em [scriptis_da_ia/README.md](scriptis_da_ia/README.md).

**b) Motor de simulação de partidas** (`scriptis_da_ia/optcg_engine/`)
Simula partidas turno a turno entre dois decks. Peças principais:
- `decision_engine.py` — `OPTCGMatch`: turnos, fases, IA de decisão
  (`_execute_step`, `_score_to_play`, Turn Planner). **Fonte única de
  verdade das regras** — qualquer lógica de jogo deve viver aqui, não
  duplicada em scripts de replay/visualização.
- `replay_optcg.py` — visualizador/auditor de partidas; delega tudo
  (`_place_start_stage`, `refresh_phase`, `main_phase`) ao `OPTCGMatch`, não
  reimplementa regra própria.
- `rules_facade.py` — funções utilitárias compartilhadas (`eligible_cards`,
  `card_matches_filter`, `choose_highest_board_value`, etc.) usadas via
  import local dentro de `_execute_step`. **Cuidado**: imports locais
  Python tornam o nome local pra função inteira — se usar uma função da
  facade num branch novo, garanta que o import já rodou antes nesse caminho
  (ou importe no topo da função, como foi feito pra `eligible_cards`).
  Ver [PLANO_UNIFICACAO.md](scriptis_da_ia/PLANO_UNIFICACAO.md) (status:
  CONCLUÍDO) para o diagnóstico e a decisão "replay vira só visualização".

**Material de referência (não é código de produção, não importar em nada
do `scriptis_da_ia/`):** `_referencias/simulador-oficial/dnspy-export/` tem
o C# decompilado da DLL oficial do jogo (`GameplayLogicScript.cs`, 34k
linhas). `_referencias/simulador-oficial/decompiled_python/` tem um porte
Python fiel desse C# (`models.py`, `action_system.py`, `card_power.py`,
`validators.py`, `card_queries.py`, `card_loader.py`) — auditoria de
28/06/2026 confirmou ZERO acoplamento com `decision_engine.py` e que o
motor de produção já está correto nos pontos testados (poder, combate, DON,
direção do deck). Use esse material só quando precisar confirmar a regra
exata do jogo sem ler 34 mil linhas de C#. **Não tente "unificar" os dois**
sem necessidade real — já foi avaliado e a conclusão foi manter separado
(ver [comparacao_simulador_vs_IA.md](comparacao_simulador_vs_IA.md), mas
desconfie da lista de gaps ali — auditoria encontrou que está inflada,
correção ainda pendente, ver [HANDOFF.md](HANDOFF.md)).

## Regras de jogo (NUNCA quebrar) — ver [TODO.md](TODO.md) para a lista completa
- K.O. ≠ Trash · Rush ≠ Rush:Character · `give_don_opp` tira do próprio jogador
- Sinal de custo só conta com texto explícito
- `play_card` vindo de efeito = sempre GRÁTIS (sem custo de DON)
- Só paga custo de uma ação ativável se algum step realmente produzir efeito
  (viabilidade ampla — evita ativar habilidade "no vácuo")
- Topo do deck = fim da lista em Python (`pop()`, não `pop(0)`)
- Mill do deck = trash seco, sem disparar trigger
- **Regra dos dois-pontos (`:`) é universal pra QUALQUER gatilho** (`[On
  Play]`, `[When Attacking]`, `[On Your Opponent's Attack]`, `[Activate:
  Main]`, `[Trigger]`, `[Counter]`, etc — confirmado pelo usuário, 23/07):
  tudo ANTES do `:` é custo, tudo DEPOIS é efeito. Se existe custo antes do
  `:` (`DON!! N`, `Trash N card(s)`, `Rest N DON!!`, etc.), pagar esse
  custo é **sempre opcional** — independe de a carta ter a palavra "may"
  por perto. Só é obrigatório: (a) efeito SEM custo antes do `:` (aí é
  obrigatório, mas "up to N" cobre N=0 como recusa disfarçada), ou (b) já
  decidiu pagar o custo — a partir daí o efeito em si é obrigatório (falha
  sem alvo, não vira recusa). "You may" no texto é só reforço redundante
  em algumas cartas, não é o que TORNA um custo opcional.

Referências oficiais das regras (manual, playsheet) em
[_referencias/regras_do_jogo/](_referencias/regras_do_jogo/).

## Estado do projeto / o que falta
Ver [TODO.md](TODO.md) (lista viva, atualizada por sessão) para: buracos de
mecânica conhecidos e priorizados, problemas abertos do replay, dívida
técnica consciente (sistema de imunidade, etc.), e o roadmap (consertar
lógica → auditar via replay → tunar heurísticas por volume de simulação →
ML só se 1-3 baterem teto).

## Workflow / convenções
```
# parser: snapshot → fix → diff_parser.py (PERDEU=0 é o padrão) → gerar_dbs → re-snapshot → commit
# engine puro: editar → partida real instrumentada (replay) → commit (sem gerar_dbs)
# NUNCA `git add -A`; commits em linha única (ambiente CMD/PowerShell)
```
- **Validacao rapida do bot ao vivo:** antes de liberar um novo teste no
  OPTCGSim, rode:
  ```powershell
  cd scriptis_da_ia
  $env:PYTHONDONTWRITEBYTECODE='1'
  python smoke_fast.py
  ```
  Este e o pre-flight padrao para ajustes do bot/engine vistos em combat log
  recente (turn order Imu, Empty Throne antes do play direto de `OP13-082`,
  Ground Death sem alvo util, Imu nao trashar Elder ativo antes de atacar).
  `smoke_test.py` NAO e mais smoke curto: trate como regressao ampla e rode
  so quando mexer em parser, counters, imunidade, substituicao, gramatica de
  efeitos ou outra area compartilhada de alto risco.
- Front: `npm run dev` (porta 3000), `npx eslint`, `npx tsc --noEmit`,
  `npx next build` antes de considerar uma tarefa de front concluída.
- API Python local: `cd scriptis_da_ia && pip install -r requirements.txt
  && uvicorn api:app --reload --port 8000`.
- Chaves Supabase: `.env.local` tem `service_role` exposta — **rotacionar
  antes de deploy público** (pendência de segurança conhecida, ver TODO.md).
- **Bot parou de responder / `LogOutput.log` sumiu?** O jogo apaga a pasta
  `BepInEx` inteira quando atualiza (já aconteceu, 09/07/2026). Feche o
  jogo e rode `BOT\setup_bepinex.bat` (reinstala BepInEx + recompila/copia
  o plugin, sem precisar de internet). Ver `BOT/README.md`.

## Banco de logs de partidas reais — OBRIGATÓRIO salvar

Sempre que o usuário mandar um combat log (cola o conteúdo, referencia um
caminho `.log`, ou pede pra investigar uma partida), **Claude ou Codex —
quem estiver na sessão — tem que adicionar esse log ao banco antes de
considerar a tarefa terminada**, seguindo a regra de nomenclatura já
existente do projeto. Não é opcional e não é "se sobrar tempo": os logs
somem quando o simulador atualiza/reinstala (já aconteceu, ver HANDOFF
bloco 109) e são a matéria-prima do roadmap de "banco de logs" (ver
TODO.md, seção `📊 BANCO DE LOGS`).

**Como fazer** (ferramenta já existe, não reinventar):
```bash
cd scriptis_da_ia
python parse_combat_log.py <caminho_do.log> --add-to-db
```
Isso copia/renomeia automaticamente pra `scriptis_da_ia/logs/{raw,parsed,decks}/`
e atualiza `logs/index.json` com a convenção de nome certa
(`{LiderSlug-Cores}_x_{LiderSlugOponente-Cores}_{timestamp}.log/json` pros
combat logs, `{LiderSlug-Cores}_{timestamp}.json` pros decks reconstruídos).
**Nunca inventar outra pasta/convenção pra guardar log de teste** (erro
cometido em 09/07: criei `BOT/test_logs/` sem saber que esse banco já
existia — teve que ser desfeito).

Se o combat log não estiver disponível como arquivo local (usuário colou
o conteúdo direto na conversa, ou o caminho já não existe mais), salvar o
conteúdo bruto num arquivo temporário primeiro e então rodar o comando
acima nele — nunca pular a etapa de adicionar ao banco só porque não veio
como path pronto.

### Telemetria de decisão — OBRIGATÓRIO ler quando o log é de partida do bot

Se o log adicionado ao banco veio de uma partida em que o **bot jogou de
verdade** (não humano vs humano), a tarefa só termina depois de ler o
resumo de decisões — não é opcional, e não é suficiente só olhar o combat
log/resultado da partida (pedido do usuário, 23/07: "a leitura da
telemetria tem que ser obrigatória depois que o log chega no banco",
depois de repetidas vezes o mesmo tipo de erro passar despercebido).

**Ordem obrigatória, NUNCA pular direto pro segundo passo** (achado 23/07:
ler só o resumo decisão-a-decisão dá quadro incompleto e sem prioridade —
o usuário pediu explicitamente pra telemetria agregada vir primeiro):

1. **`metrics/live_runs/live_<timestamp>.json`** (já gerado automaticamente
   pelo auto-collect, desde o bloco 316) — LER PRIMEIRO, sempre. Mostra o
   **QUANTO/ONDE OLHAR**: `gate_status`, `bot_confusion` (inclui
   `client_timeouts`, distinto de `no_eligible_action`), `attack_quality`
   (`under_target_count`/`don_planned_total` — corrobora bug de
   DON-pra-ataque de um ângulo agregado, sem precisar achar a decisão
   exata), `resource_signals`, e principalmente
   `instrumentation.score_components_coverage_pct`/`line_search_coverage_pct`
   — quando esses ficam abaixo de 100%, uma fração real das decisões da
   partida **não tem dado gravado pra auditar**, mesmo com o passo 2.
   `mean_counterfactual_regret` baixo NÃO prova decisão boa — só mede
   contra o que a busca realmente simulou; uma opção que nunca virou
   candidata (o bug do Pekoms) nunca entra nessa conta. Esse relatório
   diz SE tem algo suspeito e ONDE (que categoria de decisão, quantas
   vezes) antes de gastar tempo lendo decisão por decisão.
2. **`python decision_summary.py --latest`** (em `scriptis_da_ia/`,
   ferramenta já existe, não reinventar) — só DEPOIS do passo 1, pra
   investigar o que ele apontou como suspeito. Gera um `.txt` legível ao
   lado do `receipt_<timestamp>.json` mais recente (ou `--receipt <path>`
   pro receipt exato). Mostra o **O QUÊ exato**: pra cada decisão do bot,
   a ação ESCOLHIDA e as melhores alternativas descartadas com seus
   scores — onde bugs de calibração (ex: DON anexado numa carta errada
   porque a alternativa certa nem foi gerada como candidata) ficam
   visíveis sem vasculhar o `.jsonl` na mão.

Leia os dois inteiros, NESSA ORDEM, antes de reportar a partida como
investigada.

## Trabalhando junto com outra IA (Codex ou outra sessão Claude)
Nenhuma sessão vê o histórico de conversa da outra — só o estado dos
arquivos. Por isso:
1. Sempre commitar antes de parar (créditos, fim de sessão).
2. Sempre escrever um bloco novo no topo do [HANDOFF.md](HANDOFF.md) antes
   de parar: o que foi feito, estado atual, o que falta.
3. Ao assumir uma sessão, ler `HANDOFF.md` + `git log --oneline -10` +
   `git status` antes de qualquer edição.

Isso é reforçado por um **hook de `pre-push`** (`scripts/hooks/pre-push`):
bloqueia o `git push` se `HANDOFF.md` não tiver sido alterado nos commits
sendo enviados. `.git/hooks/` não é versionado pelo git, então em cada
clone/máquina nova é preciso instalar uma vez:
```bash
sh scripts/setup-git-hooks.sh
```
Para pular a checagem numa emergência (não recomendado): `git push --no-verify`.
