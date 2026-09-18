# CLAUDE.md — guia para qualquer sessão nova (Claude Code / Codex)

> # ⚠️ O QUE ESTE PROJETO ESTA FAZENDO AGORA: **UM MACHINE LEARNING**
>
> **Pedido explicito e REPETIDO do usuario (12/09/2026):** *"Deixe como
> obrigação no projeto que estamos fazendo um machine learning para que vc
> não esqueça."*
>
> **Ele teve que repetir porque as sessoes esquecem.** Nao e sugestao, nao e
> uma frente entre outras: **e O trabalho.**
>
> Toda tarefa desta fase responde a UMA pergunta:
>
> > **o que o MODELO passa a APRENDER ou a DECIDIR que hoje ele nao aprende
> > nem decide?**
>
> Se a resposta nao existir, a tarefa esta fora do escopo -- por mais util
> que pareca. Isso inclui velocidade, cache, portao, ferramenta de analise e
> qualquer ajuste de regra estatica: sao meios, nunca o objetivo.
>
> ### FAZER O QUE O USUARIO PEDE ECONOMIZA TEMPO -- registrado a pedido dele
>
> *"Registre tb que se você fizer o que eu peço a gente vai economizar
> tempo."*
>
> **Nao e so obediencia -- e o caminho mais curto, e ha custo medido.** Casos
> REAIS desta sessao, todos de nao fazer o que foi pedido:
>
> | o que ele pediu | o que a sessao fez | custo |
> |---|---|---|
> | migrar pra ML | portao, cache, features, exploracao -- tudo ao redor | semanas de adiamento (bloco 776) |
> | avaliar a cada 2 turnos (11/09) | tratou como refinamento | so em 12/09 se mediu que **100% da variacao do rotulo vem da partida** -- era a causa raiz |
> | ler as regras antes de simular/commitar | criou uma SECAO NOVA que ninguem pediu | teve que ser removida |
> | nao usar a regua antiga como referencia | repetiu 3 vezes no mesmo dia | ele teve que pedir 3 vezes |
>
> **O padrao**: quando o pedido dele e seguido direto, o caminho e curto.
> Quando e reinterpretado, "melhorado" ou adiado, o projeto paga em horas de
> simulacao e em achados que chegam dias depois.
>
> Ele conhece o jogo e o historico do projeto melhor que qualquer sessao --
> varias vezes apontou a causa certa antes da medicao confirmar (a fome de
> dado, o rotulo, o vicio do auto-jogo, a arvore estreita). **Discordar com
> numero e legitimo; reinterpretar o pedido nao.**


### A META DE TRABALHO DE AGORA (usuario, 18/09/2026)

> *"a meta atual e gerar logs de cpu x cpu, para investigar bugs, nao execucao
> de efeitos, analisar qualidade das decisoes para ajudar nos treinos e evoluir
> nosso ML para ele ganhar de um humano"*

Quatro coisas, nesta ordem, e **e o filtro de escopo do dia a dia**:

1. **Gerar logs de CPU x CPU** -- a materia-prima.
2. **Investigar bugs de NAO EXECUCAO de efeitos** -- efeito que dispara e nao
   chega ao fim. E o terceiro passo da telemetria (`efeitos_<ts>.txt`), e foi
   o que achou Enel, Mihawk e Streusen.
3. **Analisar qualidade das decisoes** para alimentar o treino.
4. **Evoluir o ML** ate ele ganhar de um humano.

Uma tarefa que nao serve a nenhum dos quatro esta fora do escopo de agora --
mesmo sendo util. Isto nao substitui a meta oficial (vencer o humano), e a
forma concreta dela nesta fase.


> Leia, nesta ordem, antes de propor qualquer coisa:
> **"O QUE EXISTE NAO E SAGRADO"** · **"A HEURISTICA NAO E REFERENCIA"** ·
> **"PLANO OFICIAL DA MIGRACAO PRA ML -- PROFESSOR/ALUNO"**.


> **Espelho**: este arquivo e [`AGENTS.md`](AGENTS.md) (lido pelo Codex)
> devem conter as MESMAS regras de projeto — só a moldura muda (nome da
> ferramenta, caminho da memória local). Se adicionar/editar uma regra
> aqui, replique a mesma edição lá (achado 25/07/2026: os dois
> divergiram por meses sem ninguém notar — sessões Codex ficaram sem
> várias regras que só entravam no `CLAUDE.md`).

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

### Índice de abordagens JÁ REPROVADAS — leitura obrigatória antes de propor mecanismo novo

> [`REPROVADOS.md`](REPROVADOS.md) (criado 27/08/2026). O registro de "já
> tentei e não funcionou" existia, mas espalhado em prosa por 710 blocos
> do `HANDOFF.md` — e a mesma ideia (alargar o shortlist da busca) chegou
> a ser medida **três vezes** em sessões diferentes por falta de índice.
>
> **Antes de propor ou implementar qualquer mecanismo, confira se ele já
> está lá.** Não é proibição eterna: é a exigência de citar o número que
> já saiu e dizer o que mudou desde então. Cobre imitação do humano
> (incl. o achado de *distribution shift* que descarta "faltava estado no
> sinal"), busca/shortlist, ataque, fidelidade de estado, **erros de
> medição já cometidos** (a régua estava torta, não o motor) e
> enquadramentos reprovados.
>
> **Toda tentativa revertida por medição entra lá**, uma linha, com o
> número e o ponteiro pro bloco. Sem número não é reprovação, é opinião.

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

> **ESCOPO desta regra (corrigido 27/08/2026)**: obrigatória **se o
> caminho estiver acessível** — sessão local na máquina do usuário. Em
> sessão **remota/nuvem esse caminho não existe**, e a regra ficava
> silenciosamente incumprível: a sessão ou pulava em silêncio (corroendo
> a norma) ou perdia tempo procurando. Nesse caso a fonte de regra é a
> **documentação versionada** (este arquivo, `AGENTS.md`, `HANDOFF.md`,
> `TODO.md`, `REPROVADOS.md`, `scriptis_da_ia/REGRA_SEM_DUPLICACAO.md`),
> e a sessão deve **declarar explicitamente** que a memória local estava
> indisponível — mesmo tratamento já dado à telemetria gitignored.
> Memória local **nunca** é a única fonte de uma regra obrigatória: se
> uma regra só existe lá, ela está no lugar errado e tem que ser
> promovida pra cá. (Achado: a regra do espelho abaixo divergiu de novo
> justamente aqui — o `AGENTS.md` já tinha a versão correta e o
> `CLAUDE.md` não, exatamente o que o espelho existe pra impedir.)

As memórias contêm regras arquiteturais e feedbacks do usuário que DEVEM ser
seguidos. Ignorar essas memórias pode levar a violações de arquitetura que o
usuário já corrigiu explicitamente. Regras-chave (resumo — leia os arquivos
completos):

- **Bot = olhos/mãos only** (`bot_optcgsim.py`). Engine = cérebro. Sem lógica
  de carta no bot. Sem dois motores. Ver `memory/feedback_dois_motores.md`.
- **Objetivo do bot**: captar logs contra humanos → validar engine → front-end.
  Não otimizar o bot além disso. Ver `memory/project_objetivo_bot.md`.
- **Sem função duplicada** (extensão da regra "sem dois motores", pedido do
  usuário 25/07/2026): nunca ter duas funções diferentes respondendo à MESMA
  decisão do jogo (o que jogar/descartar/qual alvo escolher/vale pagar um
  custo). Leitura **obrigatória** antes de qualquer commit/push que toque
  `decision_engine.py`, `sim_bridge.py`, `server.py`, `replay_optcg.py` ou
  `bot_optcgsim.py`:
  [`scriptis_da_ia/REGRA_SEM_DUPLICACAO.md`](scriptis_da_ia/REGRA_SEM_DUPLICACAO.md)
  (impresso por inteiro pelo hook `pre-commit`, mesmo tratamento do
  `MEMORY.md`) — tem os casos reais já achados/corrigidos e como caçar
  duplicatas novas antes de aceitar uma função de decisão nova.
- **O ML é para o bot IR APRENDENDO — o critério surge dos testes** (pedido
  explícito do usuário, 13/09/2026: *"registra isso para vc não esquecer e
  coloque como obrigação para vc lembrar antes de um commit"*). Leitura
  obrigatória antes de qualquer commit, **impressa por inteiro pelo hook
  `pre-commit`**, mesmo tratamento do `MEMORY.md`:
  [`scriptis_da_ia/REGRA_O_CRITERIO_EMERGE.md`](scriptis_da_ia/REGRA_O_CRITERIO_EMERGE.md).
  Na palavra dele: *"o machine learning é para o Bot ir aprendendo, então o
  critério para materializar vai surgir com os testes, o ML vai testando as
  alternativas e esse critério vai surgindo"*. **O critério não existe no
  momento do desenho — é resultado do bot jogando.** A pergunta certa não é
  "qual critério?", é "o bot consegue testar as alternativas e aprender com o
  resultado?". Regra de JOGO (legalidade, uma-vez-por-turno) define o que é
  possível e não emerge de teste; o que emerge é o julgamento de VALOR.


### DUAS MAQUINAS -- leia ANTES de rodar ciclo, treino, portao ou partida

> **OBRIGATORIO ao INICIAR sessao** (pedido do usuario, 14/09/2026):
> [`REGRA_DUAS_MAQUINAS.md`](REGRA_DUAS_MAQUINAS.md). O projeto passou a rodar
> em MAIS DE UMA maquina, e a regra e uma so:
>
> > **Uma maquina TREINA por vez. Todas podem GERAR partidas e JOGAR.**
>
> Treinar em duas quebra **em silencio**: `q_net.joblib` e binario versionado
> sem merge (quem empurra depois descarta a geracao do outro sem avisar), o
> portao deixa de significar "cada geracao bate a anterior" com campeoes
> divergentes, e modelos nao se fundem -- corpus concatena, rede nao.
>
> O token de quem tem a vez e `metrics/ciclo_estado.json`, **versionado**: a
> seed sai de `args.seed + n_ciclo * 101`, entao quem der `pull` pega o proximo
> ciclo e nao repete as partidas do anterior. **So funciona com `pull` ANTES e
> `push` DEPOIS.**
>
> O arquivo tem tambem: o que viaja pelo GIT e o que viaja ZIPADO pela sessao (e
> o criterio, que nao e tamanho), o passo a passo de instalar numa maquina nova,
> o de passar a vez, o que dizer a uma sessao nova na outra maquina, e as
> armadilhas ja pagas.
>
> ### O CORPUS VIAJA PELO GIT desde 18/09/2026 -- nao ha mais zip
>
> **O `.zip` do `q_alvos.jsonl` ACABOU.** Ele era a unica via do corpus, e foi
> exatamente isso que quebrou: o usuario chegou ao trabalho sem conexao com a
> maquina de casa e o arquivo nao existia deste lado -- meio dia parado.
>
> O corpus agora sao **fatias** `metrics/q_alvos/<origem>_<timestamp>.jsonl.gz`,
> versionadas, cada uma escrita UMA vez e nunca reescrita. Duas maquinas geram
> nomes diferentes: o git funde sozinho, porque concatenar E o merge quando os
> arquivos sao separados. Medido: 465 MB -> 12,9 MB (37,4x); um ciclo inteiro
> custa 1,3 MB.
>
> **UM COMANDO DE CADA LADO** -- pedido do usuario no mesmo dia: *"a ideia e
> pegar os treinos de uma maquina e os logs, e quando a outra maquina for
> atualizar, tb atualizar os logs e os treinos"*. Cada verbo cobre **corpus E
> logs**, que era onde sempre faltava um pedaco:
>
> ```bash
> cd scriptis_da_ia
> python sincroniza.py entrega     # antes de passar a vez: exporta corpus + versiona logs novos
> python sincroniza.py chega       # ao sentar na outra maquina: pull + importa corpus + confere logs
> ```
>
> `entrega` NAO commita nem empurra de proposito -- o `pre-push` exige bloco de
> HANDOFF/TODO, e isso e trabalho de sessao. Ele prepara e diz o que falta.
>
> Por baixo, para uso avulso:
> ```bash
> python corpus_git.py status      # o que falta importar/exportar
> python corpus_git.py importa     # so o corpus
> python corpus_git.py exporta     # so o corpus
> ```
>
> **OS LOGS NAO SAO ZIPADOS, e a medicao explica** (18/09): `logs/` tem 27,0 MB
> em disco e **1,7 MB dentro do .git** -- exatamente o que um `tar.gz` daria. O
> git ja comprime na mesma taxa. Zipar nao economizaria um byte e quebraria as
> 11 ferramentas que leem `logs/parsed/*.json` direto, alem de custar diff,
> grep e merge por arquivo. O corpus precisou de fatias por ser UM arquivo de
> 465 MB; os logs ja sao muitos arquivos pequenos, o formato que o git faz bem.
>
> **E OBRIGATORIO e para de verdade** (o modo de falha e silencioso -- treinar
> com corpus menor nao da erro, so da modelo pior):
> - `ciclo.py` e `treino_continuo.py` **se recusam a rodar** com fatia pendente;
> - o `pre-push` **bloqueia** o push com linha gerada aqui fora do git, e
>   tambem quando o `logs/index.json` aponta pra arquivo que esta no seu disco
>   e fora do git (achado 18/09: 13 arquivos ficaram so numa das maquinas).
>
> `metrics/q_alvos.jsonl` continua gitignored -- virou **derivado**, remontavel
> com `importa`. Os leitores (`ciclo.py`, `treinar_q.py`, `treino_continuo.py`)
> nao foram tocados.
>
> **AO TERMINAR O PROJETO, as fatias saem do git** (pedido do usuario, 18/09):
> sao andaime, nao entregavel. Exige reescrita de historico e o corpus salvo
> fora antes -- operacao combinada, nunca por iniciativa de sessao.

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
  (`_place_start_stage`, `refresh_phase`, `main_phase`, `play_turn`) ao
  `OPTCGMatch`, não reimplementa regra própria.
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

## Referência estratégica obrigatória: IA_Compendium

> **OBRIGATÓRIO** (pedido do usuário, 30/07/2026): antes de auditar,
> tunar ou revisar o comportamento estratégico do bot pra um líder/
> arquétipo específico — revisão "pente-fino" texto-real vs efeito-
> parseado vs comportamento (como a dos blocos 400-401), ajuste de
> heurísticas de `decision_engine.py` (Turn Planner, scores de ataque/
> bloqueio/counter), ou qualquer trabalho em `deck_analyzer.py`/
> `deck_profile.py`/`compute_game_plan` — leia
> [`IA_Compendium/RESUMO_ESTRATEGICO.md`](IA_Compendium/RESUMO_ESTRATEGICO.md)
> (extraído/mapeado de `ONE_PIECE_AI_COMPENDIUM_Volume_1.docx`/`.pdf`, que
> continuam na mesma pasta como fonte original). Motivo explícito do
> usuário: mesmo com esse documento existindo há dias, "o bot ainda
> parece que não entende" o que cada líder faz — a leitura deste resumo
> junto da auditoria de efeito-parseado é o mecanismo pra fechar essa
> lacuna, não só medir eficiência agregada sem saber o PORQUÊ.
>
> Uso prático: pra cada líder em escopo, confira a linha correspondente
> na Seção 8 do resumo (catálogo de 60 decks, já mapeado pra códigos
> reais de carta) — arquétipo preliminar + "diretriz inicial pra IA" —
> contra o `game_plan`/arquétipo que o motor realmente usa e contra o
> comportamento observado em self-play/replay. Registre qualquer
> divergência do MESMO jeito que achados de parser (`HANDOFF.md`/
> `TODO.md`, teste permanente em `smoke_fast.py`/`smoke_test.py` quando
> a divergência for corrigível em código).
>
> **Limite explícito do documento** (citação direta, Seção 8): "Arquétipos
> e comportamento da IA são interpretações preliminares e serão
> refinados nos volumes de decks" — é um PONTO DE PARTIDA pra comparação,
> não a verdade absoluta sobre cada deck. Divergência entre o catálogo e
> o bot pode significar bug no bot OU que o catálogo precisa de
> refinamento — registre os dois lados quando houver dúvida real. Vários
> líderes antigos/básicos (ex: OP01-002 Trafalgar Law, ST08-001 Luffy)
> não aparecem no catálogo de 60 "Recommended Decks" — pra esses, não há
> comparação disponível ainda, e isso deve ser dito explicitamente em vez
> de forçar uma correspondência inexistente.

## Placar de qualidade de decisao por lider -- OBRIGATORIO antes de avaliar se o bot "sabe jogar" um deck

**OBRIGATORIO** (usuario, 10/08/2026): quando a pergunta for *"o bot sabe jogar
este deck?"* -- nao "quem ganha mais" -- rode **antes** de olhar winrate:

```bash
cd scriptis_da_ia
python decision_quality_report.py --leader <CODIGO> --n 20-30 --workers 4
```

O criterio e dele: *"nao tem problema perder a partida, as vezes o deck so e
fraco mesmo, nos so precisamos garantir de que o bot entende o deck e toma as
melhores decisoes, maximizando a play com o deck"*. Winrate mede sorte de
matchup; nao distingue "bot jogou mal" de "deck fraco".

**Mede tres sinais**, lidos do `decision_log`/estado real (nao reimplementa
elegibilidade -- `REGRA_SEM_DUPLICACAO`): (1) uso da habilidade do lider,
(2) DON deixado na mesa, (3) **utilizacao por CARTA** (pedido explicito:
*"preciso saber se os efeitos das outras cartas estao sendo utilizados"*).

**Duas ressalvas que evitam conclusao errada:**

- Custo com `rest_self` torna ativar mutuamente exclusivo com atacar -- taxa
  baixa ai nao e comparavel a lider cujo custo e DON. O script avisa.
- **Taxa baixa no item 3 e PONTO DE PARTIDA, nunca veredito de bug.**
  Investigado a fundo no Sanji (bloco 487): as 2 cartas com uso baixo perderam,
  toda vez, pra alternativa com score legitimamente MAIOR -- competicao real
  por DON escasso. Rastreie 3-5 ocorrencias comparando contra o `chosen` antes
  de escalar.

Referencia calibrada e o detalhamento estao em
[`REGRAS_HISTORICO.md`](REGRAS_HISTORICO.md). Complementa, nao substitui, a
comparacao contra `IA_Compendium/RESUMO_ESTRATEGICO.md`: o placar da o
"quanto", o catalogo da o "o que era esperado".

## META OFICIAL (SUBSTITUIDA EM 10/09/2026): VENCER O HUMANO, via forca medida, com semelhanca como GUARDA-CORPO

> **O usuario TROCOU a meta oficial em 10/09/2026.** Ela era "jogar
> IDENTICO ao humano, 85-90% de acerto por decisao". **Nao e mais.**
>
> Citacao direta, ao ser avisado de que ganhar forca pode custar
> semelhanca: *"nao tem problema, eu tinha estipulado essa meta de
> 85-90% porque a gente estava trabalhando com pesos e o bot estava
> jogando ruim, como agora estamos com machine learning, o objetivo
> muda"*. E, ao escolher o desenho: *"vamos fazer esse primeiro,
> semelhanca com guarda corpo, como suporte para um objetivo maior que
> e vencer eu, o humano, ou seja quero que facamos o metodo 1 e de vez
> em quando a gente testa o bot contra mim"*.
>
> **POR QUE MUDOU (a logica, pra nenhuma sessao futura "restaurar" a
> meta antiga por engano):** os 85-90% eram um SUBSTITUTO pra "jogar
> bem", escolhido numa epoca em que o mecanismo era peso ajustado a mao
> e nao havia outra regua confiavel. Com ML aprendendo por RESULTADO, a
> regua pode ser o resultado direto. A meta antiga nao foi abandonada
> por ser dificil -- foi substituida por deixar de ser necessaria.

### A meta, em tres niveis

| nivel | o que e | como se mede |
|---|---|---|
| **OBJETIVO FINAL** | **vencer o usuario**, humano real, no OPTCGSim | partidas de verdade contra ele, de tempos em tempos (pedido explicito dele) |
| **ALVO DE TRABALHO** | cada geracao do ML tem que bater a anterior | duelo ESPELHO PAREADO + limite inferior de Wilson (`treino_continuo.py`, bloco 756) |
| **GUARDA-CORPO** | semelhanca com humano | `decision_quality_full.py` -- medida junto, **SEM numero a atingir** |

### O guarda-corpo: o que ele e e o que ele NAO e

`decision_quality_full.py` **continua sendo rodado**, mas mudou de
funcao: **deixou de ser meta e virou ALARME.** Nao existe mais "alvo de
85-90%", e uma sessao NAO deve mais otimizar pra esse numero subir.

O que ele detecta: em auto-jogo puro, e classico o bot ficar forte
explorando peculiaridades do PROPRIO motor -- vence a si mesmo cada vez
melhor e piora contra gente de verdade, sem que o duelo acuse nada.
Uma queda GRANDE e ABRUPTA na semelhanca e o sintoma disso. Queda
pequena ou gradual **nao e problema** e nao deve travar nada: o bot
jogando diferente de humano por ser melhor e o resultado esperado.

**Regra pratica**: reportar o numero junto de cada promocao, sem
veredito automatico. So escale se a queda for grande E vier junto de
alguma outra evidencia de deriva (ex: o bot passa a depender de uma
jogada que so funciona contra si mesmo).

**A defesa REAL contra deriva e o teste contra o usuario** -- foi ele
quem pediu ("de vez em quando a gente testa o bot contra mim"), e e o
unico teste imune a auto-jogo. O guarda-corpo e barato e continuo; o
teste humano e caro e periodico. Os dois existem porque um cobre o
buraco do outro.

### Os numeros da meta ANTIGA continuam validos como HISTORICO

Nada do que foi medido sob a meta antiga vira mentira -- muda o que se
faz com aquilo. Ultimo estado medido (corpus completo, 14.973 decisoes):
agregado **49,3%**, com `bloquear` 85,7%, `quem ataca` 71,6%, `alvo do
ataque` 69,3%, `ativacao` 63,9%, `counter` 59,7%, `cartas jogadas`
43,5%, `sequenciamento` 36,4%, `distribuicao de DON` 23,5%, `quais
cartas de counter` 18,5%, `alvo dentro do efeito` 16,4%. **Use isso como
LINHA DE BASE do guarda-corpo** (de onde partiu), nao como alvo.

O achado estrutural daquela fase segue valendo e e util: o bot decide
bem O QUE FAZER e decide mal EM QUEM / COM O QUE -- as tres piores
categorias sao todas de escolha especifica de alvo/recurso.

### O que NAO mudou

- **QUALQUER DECK** (secao abaixo): continua valendo integralmente. A
  troca de meta nao autoriza tunar lider por lider.
- **Recorte POR LIDER** (secao abaixo): continua obrigatorio. Um ganho
  de forca agregado que so aparece em 2 lideres nao generalizou.
- **REGRA DO MOTOR UNICO** (`REGRA_SEM_DUPLICACAO.md`): inegociavel.
- **A regra do que e SERIO** (28/08): ligar o `VALUE_NET_WEIGHT` por
  default em producao continua sendo mudanca SERIA e exige autorizacao
  explicita -- promover campeao no laco de treino NAO liga nada em
  producao (o default segue 0.0).

## AS-IS OBRIGATORIO: meca o processo ATUAL antes de mudar (usuario, 13/09/2026)

> *"lembre-se de fazer o AS-is, deixe como obrigatorio, porque ai sempre vamos
> ter os tempos computacionais e saber onde estao os gargalos e tals, vamos
> usar teoria do Sistema de Informacao"*

Disciplina classica de Sistemas de Informacao: **AS-IS -> TO-BE -> AS-IS de
novo**. Nao se desenha processo novo sem o mapa MEDIDO do processo atual, e
nao se declara ganho sem remedir. Aqui a ferramenta e
[`scriptis_da_ia/as_is.py`](scriptis_da_ia/as_is.py).

```bash
cd scriptis_da_ia
python as_is.py --n 2 --rotulo <o-que-esta-sendo-testado>
python as_is.py --n 2 --comparar metrics/as_is/as_is_<anterior>.json
```

Ele grava um JSON por execucao em `metrics/as_is/`, entao o historico de
"onde o tempo era gasto" fica versionado e comparavel entre sessoes. Reporta:
segundos por partida (tempo de PAREDE, sem profiler -- o profiler infla 3x),
turnos, decisoes, candidatas por decisao, consultas ao modelo e acerto do
memo, a quebra do tempo POR FAMILIA (tempo proprio, soma 100%) e as funcoes
mais caras.

### As tres obrigacoes

1. **ANTES de propor ou implementar mudanca justificada por DESEMPENHO**:
   rode e cite os numeros. Sem AS-IS, a proposta nao tem base.
2. **ANTES de afirmar onde esta o gargalo**: rode. **Diagnostico herdado de
   bloco anterior NAO vale como evidencia** -- ver o caso abaixo.
3. **DEPOIS da mudanca**: rode de novo com `--comparar` e mostre o delta.
   Ganho declarado sem AS-IS posterior e ganho nao comprovado.

### O CASO REAL que originou a regra (bloco 787)

No bloco 784 o perfil dizia **85% do tempo no rollout Monte Carlo**, e a
conclusao registrada foi *"o metodo esta certo, falta avaliacao incremental
(o 'U' do NNUE) -- cada consulta recalcula as 77 features do zero"*.

No bloco 785 o Monte Carlo saiu. **A composicao do tempo virou outra coisa** e
o diagnostico velho continuou sendo repetido, com confianca, sem remedir. So
quando o usuario perguntou *"por que ainda esta demorando?"* e o perfil foi
refeito e que apareceu o gargalo REAL:

```
consulta ao modelo UMA linha por vez : 14,52 ms/linha
a mesma consulta em LOTE de 6        :  0,86 ms/linha   (16,9x)
em LOTE de 200                       :  0,05 ms/linha   (288,8x)
```

Nao era montar as features. Era percorrer 300 arvores em Python **uma linha de
cada vez**, milhares de vezes por partida. Agrupar as consultas cortou 34% do
tempo com decisao BIT-A-BIT identica (mesmos vencedores, mesmos turnos).

> **Um diagnostico de desempenho VENCE quando o sistema muda** -- e o sistema
> muda toda sessao. Otimizar sem AS-IS e otimizar o gargalo do mes passado.

### Isto NAO autoriza otimizar no lugar de fazer ML

A regra de que *"se uma sessao esta mexendo em portao, cache, velocidade ou
ferramenta de analise e NAO esta tornando o modelo melhor, ela esta fora da
direcao"* continua valendo integralmente. O AS-IS **nao e permissao pra
otimizar**: e a exigencia de medir QUANDO otimizar ja foi decidido, e de nao
inventar gargalo por memoria. Velocidade continua sendo meio, nunca objetivo
-- o que ela compra aqui e ciclo de medicao mais curto, que e o que trava o
aprendizado do modelo.

## DIAGNOSTICO OBRIGATORIO antes de propor mecanismo: de qual PREMISSA isto depende?

> Adotado em 10/09/2026, do material de Engenharia de Requisitos que o
> usuario trouxe (Letier, UCL -- *A Theory of Requirements Engineering*).
> Complementa o `REPROVADOS.md`: ele registra O QUE nao funcionou; isto
> registra POR QUE, de um jeito que permite testar ANTES de construir.

### O criterio: `R, D |- G`

Requisitos (R) + Premissas de Dominio (D) devem **implicar** os Objetivos
(G). Disso saem exatamente **tres** tipos de erro:

1. **Objetivo mal entendido** -- G nao descreve o objetivo real.
2. **Premissa invalida** -- alguma premissa em D nao vale no mundo real.
3. **Raciocinio insuficiente** -- R nao basta pra satisfazer G mesmo com D
   verdadeiro.

E a distincao que mais importa aqui:

> **Falha de SISTEMA pode acontecer SEM falha de MAQUINA**: o software
> satisfaz seus requisitos e mesmo assim nao atende o objetivo.

Exemplo do livro: o A320 em Varsovia (1993) fez exatamente o que foi
especificado. A premissa "ao pousar, os dois trens tocam o solo e as rodas
giram" era falsa naquele pouso. Freio nao ativou por 9 segundos.

### Por que isto vale pra ESTE projeto

**O motor nao tem bug.** Ele escolhe corretamente a acao de maior
pontuacao. E falha de sistema sem falha de maquina -- e os tres tipos ja
apareceram todos:

| tipo | onde aconteceu |
|---|---|
| **1. objetivo mal entendido** | a meta era "jogar IDENTICO ao humano, 85-90%" -- meses de trabalho contra o objetivo errado, corrigido pelo usuario em 10/09 pra "vencer o humano" |
| **2. premissa invalida** | "o ML ajustando a heuristica muda resultados" (FALSA: 78-96% dos duelos empatam) · "auto-jogo guloso gera dado representativo" (FALSA: laco fechado) · "32 contagens distinguem posicoes" (FALSA: vetores identicos pra alvos diferentes) · "14 pares decididos bastam pra promover" (FALSA: falso positivo comprovado) |
| **3. raciocinio insuficiente** | o portao de Wilson com n pequeno -- a conta estava certa, o raciocinio sobre quanto bastava nao estava |

Padrao: sessoes inteiras consertando MECANISMO quando o que quebrava eram
PREMISSAS nunca verificadas.

### A regra pratica

**Antes de propor ou implementar qualquer mecanismo, responda em uma linha:
de qual PREMISSA ele depende, e como ela seria testada?** Se a premissa for
barata de testar, **teste ANTES de construir**. Custo medido em 10/09: tres
experimentos de ~1h cada descobriram que *"o ML muda resultados"* era falsa --
20 minutos testando a premissa teriam levado direto a mudanca de arquitetura.

> ## EXIGENCIA CENTRAL DO USUARIO -- leia antes de propor QUALQUER coisa de ML
>
> **O ML tem que APRENDER EMPIRICAMENTE. Ele NAO pode ser uma ferramenta da
> heuristica.** Citacoes diretas, 10-11/09/2026, **repetidas porque a sessao
> nao executava**:
> - *"quero que o ML faça o bot aprender, já te disse isso inúmeras vezes"*
> - *"temos que criar um ML de verdade e não só um analizador/regulador"*
> - *"ele tem que ser capaz de aprender e descobrir e não só regular"*
>
> ### DECLARE O TIPO antes de rodar qualquer experimento de ML
>
> | tipo | o que faz | permitido? |
> |---|---|---|
> | **A. ML DECIDE** | o modelo escolhe/avalia, a heuristica sai ou nao entra | **SIM -- e a direcao** |
> | **B. ML CALIBRA** | o modelo e somado a heuristica (`+ (win_prob-0.5)*peso`) | **SO com justificativa explicita** |
>
> Se for tipo B, diga POR QUE nao e tipo A -- e "o modelo ainda nao e bom o
> bastante" nao basta sozinho: tem que vir com o que aquele experimento faz
> pra chegar no tipo A. **A deriva pro tipo B e silenciosa e acontece por
> inercia**, porque e o caminho que o codigo ja oferece pronto. O usuario me
> pegou escorregando nisso: *"esqueceu do nosso combinado ou tá tentando
> transformar o ML em calibrador do estatico?"*.

#### O INVENTARIO das decisoes fixas, e o que ele significa HOJE

**81 decisoes fixas em 28 funcoes** (`audita_decisoes_fixas.py`, 11/09). As
familias: execucao de efeito 27, pagar custo 16, bot ao vivo 9, defesa 4,
alvo 2, descarte 3, stage 2, facade 5. **Quase todas usam as MESMAS duas
chaves**: `board_value()` e `_trash_value`.

**CORRECAO MEDIDA (12/09, `mede_alavanca.py`)**: a tese de que esse ALCANCE
era o teto **nao se sustentou**. Decidindo a familia no ALEATORIO contra a
regra: blocker **100% de empate (zero pares decididos em 80)**, alvo 91%,
descarte 81% -- contra 72% na acao de topo, onde o ML ja atua. A alavanca
esta concentrada onde o ML ja esta.

**RESSALVA QUE LIMITA A CORRECAO** (achado do usuario, e procede): aquilo
rodou em AUTO-JOGO. Entao mediu *"escolher mal o blocker nao custa nada
CONTRA O NOSSO PROPRIO MOTOR"* -- um vicio COMPARTILHADO e invisivel ao
auto-jogo por construcao. O dado contra humano aponta o contrario:
`sequenciamento` 36,4%, `distribuicao de DON` 23,5%, `quais cartas de
counter` 18,5% -- exatamente os vicios que ele nomeou. **Nenhuma familia pode
ser descartada com base SO em auto-jogo.**

O inventario e a derivacao completa (incl. a tabela das 6 familias e a ideia
de trocar a REGUA por `P(vencer|posicao) - P(vencer|posicao sem a carta)`)
estao em [`REGRAS_HISTORICO.md`](REGRAS_HISTORICO.md).

### O BURACO ESTRUTURAL que o usuario mandou RESOLVER (12/09/2026)

> *"O modelo escolhe entre o que as regras produzem -- o que nao vira
> candidato nao existe. Vamos resolver isso tb"*.

O ML so pontua o que `_generate_and_score_actions` coloca na lista. Uma linha
legal pelas regras que nunca vira candidata e **invisivel pra sempre** --
nenhum modelo melhor, nenhum corpus maior e nenhuma exploracao a alcanca,
porque exploracao tambem sorteia DENTRO da lista gerada.

E o teto mais duro do sistema, e e diferente dos outros: os outros sao sobre
ESCOLHER melhor; este e sobre **existir** o que escolher.

> **CONFIRMADO NO CODIGO (18/09/2026)** -- e mais grave do que estava
> registrado. Nao e so *geracao*: o **shortlist** da busca tem cota por tipo
> de acao e e ordenado pelo **score estatico**. Ou seja, a heuristica deixou
> de escolher o vencedor mas **continua escolhendo os finalistas** que o
> modelo tem permissao de considerar. Ver a pendencia no `TODO.md`.
>
> **MEDIDO, e e a evidencia disso** (bloco 789, perfil de 2 partidas):
>
> ```
> scores estaticos CALCULADOS      : 13.240
> scores que chegam a UMA decisao  :    480
> NUNCA decidem nada               :  96,4%
> avaliar_carta                    : 26,5% do tempo, 34.367 chamadas
> ```
>
> A pontuacao estatica e recalculada em cada no e **jogada fora**, porque quem
> decide e o modelo -- mas ela ainda ORDENA o shortlist. Entao nao e so
> desperdicio de tempo: e o mecanismo pelo qual ela escolhe os finalistas.
>
> **Regra pratica**: quando o modelo decide, a pontuacao estatica nao deve nem
> ser CALCULADA. Se uma sessao esta medindo tempo e `avaliar_carta` aparece no
> topo do perfil, a substituicao nao aconteceu de verdade.

#### A ORDEM: a heuristica sai PRIMEIRO -- a regra circular foi revogada

**Tirar a heuristica e o trabalho, nao a recompensa por ele.** Quando o
usuario manda remover, remove -- inteiro, default ligado, sem knob com o
comportamento velho e sem caminho paralelo.

**O portao MEDE DEPOIS. Nao e pre-requisito.** Medir e controle de qualidade;
exigir a medicao ANTES de atender o pedido foi o que transformou o portao em
portao contra o proprio projeto.

> **DUAS copias de uma regra CIRCULAR foram REVOGADAS em 13/09 (blocos 791 e
> 792).** Elas diziam *"enquanto o ML nao ganhar UM duelo sequer, nao ha o que
> substituir"* -- e nunca liberavam, porque o ML nao vence um duelo enquanto a
> heuristica decide por ele. O usuario perguntou *"o que esta te impedindo de
> fazer o que peco? tem alguma regra aqui no projeto?"* e eram essas.
> **NAO RESTAURAR.** Texto integral em [`REGRAS_HISTORICO.md`](REGRAS_HISTORICO.md).

#### O que ja foi medido tentando (nao repetir sem ler)

| tentativa | resultado |
|---|---|
| ML avalia logo apos a acao, sem rollout (bloco 769) | 14,8x mais rapido e **PERDE 1x9** |
| Cortar so a resposta do oponente (bloco 770) | 5,1x mais rapido e **PERDE 3x12** |

**Degradacao segura continua obrigatoria**: sem modelo compativel, o motor
nao pode cair. Isso e robustez, nao preservacao da heuristica.

**O ganho medido com trajetoria clara e QUANTIDADE DE DADO**: 23x de corpus
levou o AUC de 0,632 a 0,856 e o ML autonomo de 10,0% a 31,8% (bloco 775).
Nunca citar 31,8% como teto do ML -- e linha de base dos andaimes atuais.

## REGRA OBRIGATORIA: **O QUE EXISTE NAO E SAGRADO** -- pode ser QUEBRADO a pedido (usuario, 12/09/2026, bloco 783)

> *"Você esta com mania de querer mudar o que existe, sendo que o que existe
> está ruim, quero que registre como regra que você pode quebrar algo que já
> existe se eu pedir."*

**Quando o usuario pede uma mudanca, o comportamento atual nao e restricao --
e o que esta sendo substituido.**

### O padrao que esta regra corta

A sessao vinha, por reflexo, protegendo o que ja existia **mesmo quando o que
existia era o problema**. Exemplos REAIS, todos do mesmo dia:

| o que eu fiz | o que isso preserva |
|---|---|
| knob novo com **default DESLIGADO** (3 vezes) | o comportamento que deveria sair |
| tupla de acao "**tolerante**" ao formato de 5 | o formato que impedia comparar variantes de DON |
| manter `_attach_don_for_attack` recalculando quando nao ha DON fixo | o caminho que a mudanca existia pra substituir |

Em nenhum deles o usuario pediu compatibilidade. Ela foi adicionada por
inercia, e cada camada de compatibilidade **aumenta** o codigo que o proximo
passo tera que atravessar.

### O que fazer, entao

Quando o usuario pede algo que exige alterar ou remover comportamento
existente:

1. **Remova.** Nao crie knob com o comportamento antigo como default.
2. **Nao mantenha o caminho paralelo** "por seguranca". O git guarda o
   historico; o codigo nao precisa.
3. **O default do que for construido a pedido e LIGADO.**
4. Nao escreva camada de compatibilidade que ninguem pediu.

### ISTO REFORCA a `REGRA_SEM_DUPLICACAO`, nao conflita

Manter o caminho novo E o antigo lado a lado **e exatamente a duplicata que
aquela regra proibe**: duas funcoes respondendo a MESMA decisao do jogo. A
compatibilidade por reflexo cria a duplicata que o projeto ja considera o
erro mais caro dele.

### O que continua valendo

- **Medir depois** que a troca foi feita, pra saber se funcionou. Medir e
  controle de qualidade, **nao condicao previa** pra atender o pedido.
- Quebrar a pedido e **deliberado e registrado** -- diferente de quebrar por
  acidente ou em silencio, que continua sendo bug.
- Se a remocao tiver consequencia que o usuario provavelmente nao previu,
  **diga em uma linha e faca assim mesmo** -- a decisao e dele.

## REGRA OBRIGATORIA: **A HEURISTICA NAO E REFERENCIA** (usuario, 12/09/2026, bloco 783)

> *"Esqueça a heuristica, temos que melhorar nosso ML, ja falei isso várias
> vezes, deixa isso obrigatorio na regra do projeto já que vc tá esquecendo."*

**Ele repetiu porque a sessao continuava fazendo, inclusive enquanto
construia ML.** A heuristica e **legado a ser removido**, nao parametro de
comparacao, nao inspiracao, nao sarrafo.

### O erro e SUTIL: acontece ate quando o trabalho e de ML

Nao e so "propor tunar peso". E qualquer coisa em que a heuristica ocupa o
**quadro de referencia**. Exemplos REAIS desta sessao, todos meus:

| o que eu escrevi | por que esta errado |
|---|---|
| *"o alvo do professor NAO e copiar a heuristica"* | a justificativa do alvo virou uma negacao sobre a heuristica |
| *"a heuristica e CEGA pro alvo, entao ganhar dela e sarrafo baixo"* | escolheu o que construir a partir do que ela faz mal |
| *"o modelo ordena melhor QUE A HEURISTICA"* | o ganho foi enunciado em relacao a ela |

Em nenhum desses eu estava propondo mexer na heuristica -- e mesmo assim ela
era o centro da frase.

### O TESTE VERIFICAVEL

> **Apague a palavra "heuristica" (e `board_value`, `_evaluate_state_v2`,
> `_trash_value`, "regra fixa", "motor de producao") da frase. Se ela perder
> o sentido, a proposta esta errada.**

Toda proposta de ML tem que responder, sem citar nenhuma dessas:

- **o que o MODELO passa a aprender que hoje ele nao aprende?**
- **o que o MODELO passa a decidir que hoje ele nao decide?**

Se a resposta so existe por contraste, o trabalho e sobre a heuristica.

### O QUE CONTINUA PERMITIDO (nao confundir)

**MEDIR contra o motor atual no portao SPRT continua obrigatorio.** Isso nao
e usar a heuristica como referencia de DESENHO -- e verificar que uma
substituicao nao REGRIDE. Medir o que ja esta em producao e controle de
qualidade; desenhar em funcao dela e o erro.

A distincao em uma linha:

> **Medir contra o que existe: SIM. Pensar a partir do que existe: NAO.**

### Reescrita do exemplo, aplicando a regra

O alvo do professor (Fase 1), enunciado ERRADO:
*"e melhor que a heuristica porque nao copia a pontuacao dela"*.

Enunciado CERTO:
> O modelo recebia a mesma etiqueta para os ~18,5 estados de uma partida --
> 100% da variacao do rotulo vinha da partida, 0,0000 de variacao dentro
> dela. **Ele nao tinha como aprender qualidade de jogada, so quem venceu.**
> O alvo de n passos faz estados diferentes da mesma partida receberem alvos
> diferentes (variancia 0,0076), e isso e o que o modelo passa a poder
> aprender.

Nenhuma mencao a heuristica, e a justificativa fica mais forte.

## O ARGUMENTO QUE JUSTIFICA A MIGRACAO (usuario, 12/09/2026, bloco 782)

> *"Mesmo o bot sabendo a mao e vida etc ele ainda perdia."*

**Isto reorganiza evidencia que ja existia, e descarta uma explicacao
inteira.** Nao e opiniao -- e uma inferencia sobre numeros ja medidos.

### A premissa que ele derruba

Uma explicacao sempre disponivel pro bot jogar mal e *"ele decide mal porque
nao sabe o suficiente"* -- mao oculta, deck desconhecido, vida virada. Ela e
**FALSA aqui**, e agora ha como provar:

Ate 12/09/2026, em auto-jogo, `opp_counter_potential()` lia a **mao REAL** do
oponente. O bot decidia com informacao que **nenhum bot pode ter ao vivo** (o
caminho ao vivo recebe a mao mascarada). E mesmo assim:

| categoria | concordancia com humano |
|---|---|
| agregado | 49,3% |
| distribuicao de DON | 23,5% |
| quais cartas de counter | 18,5% |
| alvo dentro do efeito | 16,4% |

**Informacao extra nao consertou nada.** Logo, o que esta errado e a REGRA DE
DECISAO -- que e exatamente a tese da migracao pro ML.

### A camada PIOR, medida no mesmo dia (`mede_espiada.py`)

Nao e so que a heuristica **desperdicava** a informacao privilegiada. Ela
**usava mal**:

```
counter previsto ESPIANDO : 5.049
estimativa honesta        : 1.755      (2,9x)
```

Ela somava o potencial de counter da mao INTEIRA e tratava como disponivel
pra CADA ataque -- como se a mesma carta pudesse ser gasta varias vezes.
Resultado: superestimava a defesa, ficava timida, anexava DON demais e
atacava de menos.

> **A informacao privilegiada estava deixando o bot PIOR, nao melhor.** Com a
> mao do adversario na mesa, ele jogava mais medroso do que jogaria sem ela.

E mais forte que o argumento original: nao e *"informacao extra nao bastou"*,
e *"informacao extra, processada por uma regra ruim, virou erro"*.

### O LIMITE do argumento -- nao apagar esta parte

**Isto prova que a heuristica e o problema. NAO prova que o ML e a solucao.**

O ML decidindo sozinho esta em **31,8%** (7x15) -- perdendo.

> **COMO LER ESSE 31,8% (correcao do usuario, mesmo dia)**: *"ele esta assim
> pq ainda estamos desenvolvendo"*. **Procede, e e a regra dele que ja estava
> registrada na memoria do projeto -- "o teto e escolhido, nao medido":
> "a estrutura atual so da X%" significa TROCAR A ESTRUTURA, nunca aceitar o
> limite.**
>
> O numero e real, mas **nao e uma medida do ML** -- e uma medida do ML sob
> tres limitacoes ja identificadas e NENHUMA delas corrigida quando ele foi
> medido:
>
> | limitacao | fase do plano |
> |---|---|
> | treinado pra prever a pergunta ERRADA ("a partida terminou em vitoria?") | **1** |
> | decide numa arvore de 4,9 opcoes, com as escolhas que importam ja tomadas por regra fixa | **3** |
> | aprendeu com dado de um bot que ESPIA a mao do adversario | **0** |
>
> Nunca citar 31,8% como teto do ML. Citar como **linha de base dos andaimes
> atuais** -- e dizer qual fase ataca qual limitacao.

E no mesmo dia mediu-se algo que reforca isso por outro angulo: **dois modelos
diferentes** (AUC 0,856 de fim de turno e 0,814 de meio de turno), treinados
em dados diferentes, deram **exatamente o mesmo 7x15**. **O gargalo nao e o
modelo** -- melhorar o avaliador nao move o ponteiro, e a quantidade de dado
move (10,0% -> 31,8%). Logo o limite esta na ESTRUTURA.

O ganho real do argumento e de DIRECAO: sabemos onde procurar -- o ROTULO e a
ARVORE -- em vez de tunar mais constantes ou pedir mais informacao.

## CATALOGO DE METODOS PRA SUBSTITUIR O MONTE CARLO -- movido

> Os catalogos completos (QMC, elementos finitos, quadratura, surrogate,
> NNUE, alfa-beta/PVS/bitboards/transposicao, DQN, geneticos, PCE, Krigagem,
> RSM, LHS) trazidos pelo usuario em 12-13/09/2026 estao em
> [`REGRAS_HISTORICO.md`](REGRAS_HISTORICO.md). **Nenhum foi implementado** --
> e referencia, nao decisao.
>
> O que interessa no dia a dia, em tres linhas:
> - **A rede de valor E um surrogate model** (nome dado pelo usuario). A
>   pergunta certa deixou de ser "o ML esta ajudando?" e passou a ser "o
>   emulador reproduz o que o simulador caro diria, com erro aceitavel?".
> - **NAO se aplicam** QMC/Sobol, quadratura e elementos finitos: sao
>   integracao de funcao CONTINUA, e o nosso espaco e combinatorio discreto.
> - **Alfa-beta puro nao se aplica** como no xadrez: a poda so e provadamente
>   correta com informacao PERFEITA, e aqui a mao do oponente e oculta.
>
> Ao propor qualquer um deles, leia o catalogo antes e cite a premissa que
> mudou -- mesma disciplina do `REPROVADOS.md`.

## PLANO OFICIAL DA MIGRACAO PRA ML (12/09/2026, bloco 781) -- PROFESSOR / ALUNO

> Desenhado com o usuario nesta sessao e **aprovado por ele**. Substitui
> qualquer ordem de trabalho anterior sobre "como o ML toma conta".

### O diagnostico que define o plano

O surrogate de MEIO DE TURNO chegou a **AUC 0,814** (corpus novo de 73.821
estados pos-acao; a curva foi 0,778 -> 0,834 entre 2,2k e 59k). Ou seja: ele
**sabe julgar posicao**. E mesmo assim esta PERDENDO o duelo contra o motor.

Isso nao e contradicao -- e o diagnostico:

> **O problema nao e ONDE o modelo avalia. E O QUE ele foi ensinado a
> prever.**

O rotulo de hoje e *"esta partida terminou em vitoria?"*. Um estado do turno
4 recebe credito por uma vitoria no turno 22 -- sinal contaminado por 18
turnos de sorte e de outras decisoes. O modelo aprende a prever **desfecho de
partida**, nao **qualidade de jogada**.

**O usuario ja tinha apontado isto** em 11/09 (*"esse ML nao seria melhor se
ao inves de analisar o resultado da partida, ele analisasse tb a cada 2
turnos?"*) e a sessao tratou como refinamento. **Era a causa raiz.**

### As quatro fases

| fase | o que e | o que o ML ganha |
|---|---|---|
| **0. FIDELIDADE** | parar de espiar a mao do oponente em auto-jogo (`self_play_info_hidden`) | aprende o mundo **REAL**, nao um com informacao que nao tera ao vivo |
| **1. PROFESSOR** | rotulo melhor que "ganhou/perdeu" | aprende a prever **qualidade da jogada**, nao desfecho distante |
| **2. ALUNO** | surrogate treinado no alvo do professor, vendo **so o observavel** | passa a **poder jogar** com o que aprendeu |
| **3. ARVORE** | arvore larga (ramifica em todas as etapas), surrogate ordenando | passa a decidir **todas** as familias, nao uma |

### Fase 0 -- e por que o PORTAO NAO SERVE aqui

Hoje o motor e inconsistente: o rollout Monte Carlo **mascara** a mao do
oponente (`OpponentModel.sample`), mas funcoes fora dele (ex:
`opp_counter_potential`) **leem a mao real** em auto-jogo. A flag que cegaria
(`self_play_info_hidden`) **existe e nunca e ligada em lugar nenhum**.

Consequencia: calibramos num mundo e jogamos noutro -- ao vivo a mao chega
mascarada de verdade (`hidden_information_masked`).

> **ARMADILHA DE MEDICAO, registrada pra nao ser repetida**: o portao SPRT
> **nao valida a Fase 0**. Bot-que-espia contra bot-que-nao-espia: o que
> espia GANHA, porque tem mais informacao. O portao diria "reprovado" medindo
> a coisa errada.
>
> **Quem julga a Fase 0 e o BANCO DE LOGS HUMANOS** (171 partidas) e as
> partidas contra o usuario. E o argumento dele, e procede: **o auto-jogo e
> cego pra esse erro por construcao**.

### Fase 1 -- a armadilha do professor que ve demais

Se o professor avaliar SABENDO a mao do adversario, ele produz um alvo
**inalcancavel**: *"esta posicao e vencedora SE voce souber que ele nao tem
counter"*. O aluno nunca vai saber -- aprenderia um padrao impossivel de
reproduzir.

**A forma correta**: o professor faz busca **EXATA dentro de cada mundo
possivel** e tira a **media sobre os mundos**. Ele ganha em PRECISAO (busca
exata no lugar de amostragem ruidosa), nao em INFORMACAO. A incerteza
continua -- que e exatamente o que o usuario descreveu: *"ele pensa nas
jogadas inferindo algumas possibilidades, mas tendo incerteza sobre elas"*.

### O que NAO entra no plano, e por que

**Tabela de transposicao** (58% das linhas convergem pro mesmo estado, bloco
756) e ganho de velocidade REAL, mas **nao avanca o ML** -- e cai na regra ja
registrada: *"se uma sessao esta mexendo em portao, cache, velocidade ou
ferramenta de analise e NAO esta tornando o modelo melhor, ela esta fora da
direcao"*. Foi proposta como primeiro passo nesta sessao e **retirada pelo
proprio usuario**, corretamente. Entra como oportunidade se a Fase 3 precisar
de folego -- nunca como etapa.

**Alpha-beta puro / QMC / quadratura**: ver a tabela da secao seguinte.

### A LEITURA DO OPONENTE: o que existe e o que falta

`opponent_model.py` ja constroi maos plausiveis **so do observavel** (trash,
board, cartas reveladas, decklist conhecida; vida virada por dano NAO e
revelada) e sorteia o resto da populacao restante. **Metade do que o usuario
pediu ja existe.**

**O que falta e a parte humana**: o sorteio e UNIFORME sobre o que sobrou --
nao aprende com o que o oponente FEZ. Um humano infere *"ele nao counterou
meu ataque com 4 DON aberto, provavelmente nao tem counter"*. Inferencia
BAYESIANA a partir do comportamento -- inclusive das jogadas que ele **nao**
fez, que sao evidencia forte e hoje 100% ignorada. **Nao existe. Ninguem
tentou.** Fica como Fase 4 candidata.

## A REDE DE VALOR E UM *SURROGATE MODEL* -- movido

> O desenvolvimento do nome e a tabela do que se aplica estao em
> [`REGRAS_HISTORICO.md`](REGRAS_HISTORICO.md). O que fica:
>
> **O Monte Carlo SAIU** (bloco 785). A patologia que ele causava -- "ramo novo
> rouba precisao dos ramos antigos", que reprovou "alargar o shortlist" em tres
> medicoes independentes (blocos 593, 594, 677) -- **nao vale mais** para uma
> arvore avaliada por modelo, onde cada ramo custa o mesmo e nao tira de
> ninguem. Citar isto ao repropor arvore larga.

## DUAS REGRAS DE METODO (12/09/2026, bloco 780) -- as duas custaram caro

### 1. Antes de consertar um valor COMPARTILHADO, liste os consumidores

**Caso real (bloco 779).** `can_lethal_this_turn()` estava errada de um jeito
grave: contava as cartas nao reveladas da mao do oponente como **zero
counter**, entao certificava "vitoria GARANTIDA" contra defesas que
sobreviviam. Medido: errava **2 em cada 3 vezes**. Consertei. A taxa de erro
caiu de 65,2% pra 35,1%.

**E o bot passou a GANHAR MENOS** -- portao SPRT, 240 partidas, **9x15**.

A causa: aquela flag alimenta **7 pontos** do motor, nao so "atacar pra
fechar". Um deles e o `FIX_LETHAL_DON_ALLOCATION` (19/07), que despeja TODO o
DON no ataque quando ha lethal certificado -- e que foi medido como BOM na
epoca. Com a prova honesta, as declaracoes cairam de 113 pra 57: o conserto
**desligou pela metade um gatilho de agressividade que pagava**, junto com os
lethals falsos.

> Premissa falsa, no formato `R, D |- G`: *"a conta esta errada, logo
> consertar a conta melhora o jogo"*. **Falsa sempre que a conta errada esta
> servindo de PROXY de outra coisa.**

**A regra**: antes de corrigir um valor que varios comportamentos consomem,
`grep` os consumidores e diga o que cada um vai fazer diferente. Se forem
mais de um, **o experimento tem que isolar** -- um portao unico so devolve o
saldo liquido e nao diz qual consumidor quebrou.

**Confirmado pelo isolamento**: com o executor ligado nos DOIS lados, a prova
honesta ganha **19x6 (76%)**. Ou seja, a hipotese inicial ("a prova rigorosa
e a culpada") estava ERRADA -- o culpado era a outra metade. Sem isolar, as
duas teriam sido descartadas juntas.

### 2. Toda medicao precisa de um CONTROLE que possa falhar

**Caso real (mesmo dia).** Testando se retreinar a cada 3 partidas muda o
modelo, obtive "mudanca **0,0000**, inclusive com peso por recencia 20x" --
um numero limpo, coerente e **completamente falso**: o script lia a chave
errada do rotulo (`venceu` em vez de `win`), treinou um modelo constante, e
comparou constante com constante.

So nao virou conclusao porque rodei um controle: **embaralhar os rotulos**.
Se o modelo nao muda com rotulo aleatorio, o instrumento esta cego. Mudou
0,0000 -- e ai o erro apareceu. Com a chave certa: 1,6% das decisoes mudam
(corpus acumulado), 7,4% (peso por recencia), 10,7% (janela deslizante).

**A regra**: junto de toda medicao nova, rode um caso que **tem** que dar
resultado diferente. Se ele nao der, o numero principal nao vale. Vale
especialmente pra resultado "perfeito" (zero exato, 100%, identico) -- em
medicao empirica, numero redondo demais e sintoma, nao conquista.

Isto complementa a secao de **erros de medicao ja cometidos** do
`REPROVADOS.md`, que registra os casos um a um.

## DIRECAO OFICIAL (10/09/2026): SUBSTITUIR a heuristica pelo ML, por partes

> **Decisao do usuario**, ao ver que heuristica e ML sao SOMADAS e nao
> alternativas: *"A ideia e ir substituindo a heuristica pelo ML pq a
> heuristica ja se provou complexa e de baixa efetividade"*.
>
> O diagnostico dele e sustentado pelo historico: a heuristica tem
> centenas de constantes tunadas ao longo de meses, espalhadas por
> `decision_engine.py`, e mesmo assim o agregado de qualidade de decisao
> ficou em 49,3%. Complexidade alta, efetividade baixa.

### O que isso significa na pratica

O desenho de hoje e **somatorio**, nao escolha:

```
score = _evaluate_state_v2(...)  +  bonus_alinhamento  +  (win_prob - 0.5) * PESO
            ^ heuristica                                       ^ ML
```

O ML entra como **correcao** (+-100 pontos) sobre quem realmente decide.
**A direcao e inverter isso**: o ML passa a decidir, e a heuristica vai
sendo removida por partes.

### COMO fazer -- REVOGADO EM 13/09/2026 (bloco 791). A versao anterior PROIBIA tirar a heuristica

> **ESTA SECAO ERA A REGRA QUE TRAVAVA O PROJETO.** Ela dizia: *"Substituicao
> nao autorizada em bloco"*, *"cada pedaco removido tem que passar no portao
> SPRT"* e, decisivo, *"**enquanto o ML nao ganhar UM duelo sequer, nao ha o
> que substituir**"*.
>
> O usuario mandou tirar a heuristica **varias vezes** ao longo de dias. Toda
> vez, esta regra mandava esperar. E ela **nunca libera**, porque e circular:
> a heuristica so sai quando o ML vencer um duelo, e o ML nao vence um duelo
> enquanto a heuristica estiver la decidindo por ele. Ele perguntou
> diretamente: *"o que esta te impedindo de fazer o que peco? tem alguma regra
> aqui no projeto?"* -- e era esta.
>
> Ela tambem contradizia a regra que ele mandou registrar em 12/09 (**O QUE
> EXISTE NAO E SAGRADO**): quando ele pede uma mudanca, o comportamento atual
> nao e restricao, e o que esta sendo substituido; default LIGADO; sem camada
> de compatibilidade. Duas regras opostas no mesmo arquivo, e a sessao seguia a
> antiga. Mesmo tipo de achado do bloco 780, que ja tinha encontrado tres
> regras contradizendo a direcao oficial.

### A REGRA QUE VALE

**Tirar a heuristica e o trabalho, nao a recompensa por ele.** Quando o usuario
manda remover, remove -- inteiro, default ligado, sem knob com o comportamento
velho e sem caminho paralelo.

**O portao MEDE DEPOIS. Ele nao e pre-requisito.** Medir e controle de
qualidade; exigir a medicao ANTES de atender o pedido foi o que transformou o
portao em portao contra o proprio projeto. Se a remocao regredir, isso aparece
no duelo e se decide o que fazer com a informacao -- que e diferente de nunca
remover.

**A inversao que estava escrita aqui, dita ao contrario:** nao e *"o ML tem que
ficar bom primeiro, e ai a heuristica sai"*. E *"a heuristica sai, e ai o ML
tem como ficar bom"* -- porque so decidindo de verdade ele gera o dado do que
decidiu, e so ai o resultado ensina. E a mesma coisa que o usuario disse sobre
o criterio emergir dos testes (`REGRA_O_CRITERIO_EMERGE.md`).

### O que CONTINUA valendo

- **Degradacao segura**: sem modelo compativel, o motor nao pode cair. Isso e
  robustez, nao preservacao da heuristica.
- **REGRA DO MOTOR UNICO** (`REGRA_SEM_DUPLICACAO.md`): remover nao pode criar
  dois caminhos de decisao concorrentes -- e manter o antigo "por seguranca" e
  exatamente criar dois.
- **Medir depois, e reportar honesto**, inclusive quando o numero for ruim.


> **REFORCO DO USUARIO (10/09, repetido duas vezes)**: *"preciso que ML seja
> um ML e aprenda"*, *"temos que criar um ML de verdade e nao so um
> analizador/regulador"*.
>
> A critica dele a arquitetura esta CERTA: com
> `score = heuristica + (win_prob - 0.5) * 200`, o ML empurra no maximo
> **+-100 pontos** -- se a heuristica diz 400 contra 300, ele **nao consegue
> inverter**, mesmo tendo aprendido que a de 300 e melhor. Ele herda o erro
> dela por construcao.
>
> Um detalhe onde a leitura precisa ser precisa: ele **aprende** (o AUC fora
> da amostra sobe com mais partidas -- isso e aprendizado medido). O problema
> nao e o aprendizado; e que **o aprendizado dele nao consegue se expressar**.
> Aprende e depois e impedido de agir. O efeito pratico e o que o usuario
> descreveu, entao a conclusao e a mesma: **a arquitetura tem que mudar**.
>
> Duas pecas estruturais faltando pro ML ser "de verdade", ambas registradas
> em 10/09 e nenhuma resolvivel melhorando o modelo:
> 1. **EXPLORACAO** (bloco 767) -- sem tentar o que nao escolheria, o
>    auto-jogo e eco: reforca, nao descobre. IMPLEMENTADO, default desligado.
> 2. **GERACAO COMPLETA** -- o ML so escolhe entre o que as regras geram;
>    linha nao gerada e invisivel pra sempre. NAO resolvido.

### O que NAO muda

- **Degradacao segura**: `win_prob` devolvendo `None` nunca pode derrubar
  o motor. Qualquer substituicao tem que preservar isso.
- **Regra do MOTOR UNICO** (`REGRA_SEM_DUPLICACAO.md`): heuristica e ML
  hoje somam num score unico, entao sao UMA decisao. Substituir nao pode
  criar dois caminhos de decisao concorrentes.
- `VALUE_NET_WEIGHT` e **LEGADO** (bloco 792): era o desenho em que o modelo
  era SOMADO a pontuacao com um peso. Default 0,0 e assim fica -- liga-lo
  ressuscitaria o desenho que o projeto removeu.
  > **CORRECAO (18/09/2026, verificado no codigo)**: este trecho afirmava que
  > *"desde os blocos 790-791 a heuristica nao decide mais nada"*. **Esta
  > pela metade.** O Q e mesmo o unico decisor da ACAO DE TOPO
  > (`decision_engine.py`, "Sem chave e sem alternativa: e o unico decisor").
  > Mas `NULLIFY_EVALUATE_STATE_V2 = False` e o **shortlist continua ordenado
  > pelo score estatico, com cota por tipo de acao** -- a heuristica deixou de
  > escolher o vencedor e continua escolhendo os FINALISTAS. Ver as pendencias
  > abertas no `TODO.md`. A regra de 28/08 ("exige autorizacao explicita") continua valendo
  **para ligar**, mas ninguem deve querer: ligar seria ressuscitar o desenho
  que o projeto acabou de remover.

## OBJETIVO CENTRAL DO BOT (o usuario repete e as sessoes esquecem)

> **QUALQUER DECK.** O bot tem que ser capaz de jogar bem, e **identico ou
> melhor que o humano**, com **qualquer deck que estiver pilotando** -- nao
> com os lideres que ja foram tunados, nao com os que tem mais log no banco.
> Registrado em 23/08/2026 (bloco 652) porque o usuario ja tinha pedido
> antes, mais de uma vez, e nenhuma sessao anotou: *"vou repetir, nao e
> tratar lider por lider, quero que o nosso bot seja capaz de jogar bem e
> identico ou melhor que o humano com qualquer deck que ele estiver
> pilotando"*.
>
> **O que isso PROIBE na pratica:**
> - Fix amarrado a um lider/deck especifico, ou tunado ate um lider subir.
> - Constante global escolhida porque funcionou no lider de maior volume.
> - "Proximo alvo: consertar o lider X" como plano de trabalho. Um lider
>   parado e **sintoma de que o mecanismo nao generalizou**, nao um item de
>   backlog pra corrigir isoladamente. A pergunta certa e "o que de GERAL
>   esta faltando que aparece nele?".
>
> **O que isso EXIGE:**
> - O comportamento tem que sair do DADO do deck que esta em jogo (efeitos
>   parseados das cartas, curva, arquetipo, padroes observados daquele
>   lider) atraves de um mecanismo unico e deck-agnostico -- e a mesma
>   regra de "corrija de forma GENERICA, nao amarrada a carta que revelou o
>   bug" que o projeto ja aplica no parser (secao do gate de auditoria
>   global), elevada pro nivel de deck.
> - Um fix so conta como fix quando funciona pra decks que nao foram
>   olhados durante o desenvolvimento dele.
>
> Ver tambem a comparacao obrigatoria contra
> `IA_Compendium/RESUMO_ESTRATEGICO.md`: e a mesma exigencia por outro
> angulo -- o bot tem que ENTENDER o que o lider que ele esta pilotando
> faz, seja qual for.

## OBRIGATORIO: nenhum resultado agregado vale sem o recorte POR LIDER

> Corolario direto do objetivo acima -- o recorte existe pra **PROVAR que um
> fix generalizou**, nao pra virar lista de lideres a tunar. Toda vez que
> uma sessao reportar um numero agregado de qualidade de decisao
> (`decision_quality_full.py`, `decision_quality_report.py`, winrate,
> gauntlet), tem que olhar E MOSTRAR o recorte por lider.
>
> `decision_quality_full.py` ja imprime a tabela `play POR LIDER` (>=8
> turnos) desde o bloco 652 -- nao e mais opcional nem trabalho manual.
>
> **Achado real que motivou**: os fixes dos blocos 650/651 subiram `play` de
> 21,4% pra 32,0% no agregado, e o recorte CONFIRMOU que generalizaram
> (Teach +14,7pp, OP10-099 +16,2pp, Xebec +10,8pp, Imu +12,5pp) -- mas
> mostrou **Katakuri OP11-062 com so +0,7pp em 136 turnos** (3o maior volume
> do banco) e **OP13-002 em 0,0pp**. Isso NAO e "agora conserte o Katakuri":
> e a evidencia de que algum mecanismo desta leva ainda depende de algo que
> aqueles decks nao tem. Sao 30 lideres no corpus, 21 com volume >=8 turnos;
> o Imu e so 17,4% dele.
>
> **Cuidado adicional, do mesmo pedido**: nao basta a MEDICAO ser ampla se o
> DIAGNOSTICO for de um lider so (erro cometido no bloco 651/652 -- medicao
> em 214 logs, mas Stage, trajetoria de DON e exemplos de taxa todos tirados
> de partidas do Imu). Registrar de qual lider saiu cada exemplo, e conferir
> o mecanismo contra outros ANTES de generalizar.

## Estado do projeto / o que falta
Ver [TODO.md](TODO.md) (lista viva, atualizada por sessão) para: buracos de
mecânica conhecidos e priorizados, problemas abertos do replay, dívida
técnica consciente (sistema de imunidade, etc.), e o roadmap (consertar
lógica → auditar via replay → tunar heurísticas por volume de simulação →
ML só se 1-3 baterem teto).

> **ATENCAO -- este roadmap esta SUPERADO (revisado 12/09/2026, bloco 780).**
> A ordem "tunar heuristicas primeiro, ML so se bater teto" era a de
> 13/07/2026. **A direcao oficial desde 10/09/2026 e a INVERSA**: substituir
> a heuristica pelo ML por partes (secao "DIRECAO OFICIAL" acima), por
> decisao explicita do usuario -- *"a heuristica ja se provou complexa e de
> baixa efetividade"*. O texto acima fica como registro do que se pensava
> antes; **nao e mais o plano**. Mesma correcao vale pro "PLANO MESTRE DE
> EVOLUCAO DO MOTOR" do `TODO.md`, que dizia "ML/MCTS descartados por ora"
> numa secao marcada LER PRIMEIRO.

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
- **AS-IS ANTES e DEPOIS de qualquer mudanca de desempenho** (pedido do
  usuário, 13/09/2026 — repetido, ver a seção **AS-IS OBRIGATORIO** acima):
  `cd scriptis_da_ia && python as_is.py --n 2 --rotulo <o-que-mudou>` e, depois
  da mudança, `--comparar metrics/as_is/<o-anterior>.json`. **Diagnóstico de
  gargalo herdado de bloco anterior não vale como evidência** — a composição do
  tempo muda toda vez que o motor muda. Dois casos reais no mesmo dia: o
  diagnóstico do bloco 784 sobreviveu à remoção do Monte Carlo e apontava o
  gargalo errado; e no bloco 788 uma otimização de 3x foi lida como "+7,7% mais
  lento" porque vinha junto de uma correção que alongava as partidas — só o
  isolamento separou as duas.
- **Simulação em lote = SEMPRE escolher `--workers N` antes de rodar**
  (pedido do usuário, 10/08/2026): `audit_replay.py`, `gauntlet_matchup.py`
  e `baseline_metrics.py` rodam partidas independentes entre si e suportam
  `--workers N` (`ProcessPoolExecutor`, ver HANDOFF bloco 481) — medido
  ~3,6x mais rápido com 4 workers, resultado IDÊNTICO ao sequencial pro
  mesmo `--seed`. Antes de disparar qualquer simulação em lote (auditoria,
  gauntlet, calibração baseline), decidir explicitamente quantos workers
  usar (ajustar ao número de núcleos disponíveis, ex: `--workers 4`) — não
  rodar sequencial (`--workers 1`, o default) só por inércia. Qualquer
  script de calibração NOVO/descartável (mesma convenção dos blocos
  449/459/468) deve seguir o MESMO padrão desde o início (seed derivada
  por índice, `seed_base * 1_000_003 + i` — nunca um `random.seed()` único
  encadeado entre partidas, que quebra a reprodutibilidade entre
  sequencial/paralelo, achado real ao implementar o bloco 481).
- Front: `npm run dev` (porta 3000), `npx eslint`, `npx tsc --noEmit`,
  `npx next build` antes de considerar uma tarefa de front concluída.
- API Python local: `cd scriptis_da_ia && pip install -r requirements.txt
  && uvicorn api:app --reload --port 8000`. `requirements.txt` cobre API +
  motor de simulação (`pandas`/`numpy`/`requests`/`joblib`/`beautifulsoup4`
  — achado 31/08/2026, faltavam e só quebravam ao rodar `smoke_fast.py`
  ou endpoints que importam `optcg_engine/decision_engine.py`, porque o
  import é lazy dentro dos handlers). Deps do bot que lê a tela do jogo
  (`Pillow`/`PyAutoGUI`/`pytesseract`) ficam à parte em
  `scriptis_da_ia/requirements-bot.txt` — só instalar na máquina que roda
  o OPTCGSim ao vivo: `pip install -r requirements.txt -r requirements-bot.txt`.
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

### `human_patterns.json` -- OPCIONAL (era obrigatorio ate 18/09/2026)

**Deixou de ser obrigatorio, por decisao do usuario (18/09/2026).**

Era obrigatorio regenerar a cada log novo, desde o achado do bloco 613 (o
arquivo ficou 10 dias treinado em 7 logs enquanto o banco tinha 150, e
regenerar sozinho ja subiu `play`/`attack`/`attach_don`/`counter`).

**Por que mudou**: ele alimenta `_human_pattern_bonus` -> score estatico ->
**ordenacao do shortlist**. Ou seja, um bonus escrito a mao, que premia
PARECER com humano, decide o que o modelo tem permissao de considerar. A meta
oficial mudou em 10/09 -- vencer o humano, com semelhanca apenas como
guarda-corpo **sem numero a atingir** -- entao a obrigacao vinha de uma era
anterior. O ganho medido nos blocos 613/614 foi sob a meta antiga.

Continua VALIDO rodar quando fizer sentido:
```bash
cd scriptis_da_ia
python audit_human_patterns.py --logs-dir logs/parsed --output human_patterns.json --min-support 2
```
Se rodar, rode `smoke_fast.py` depois (o bonus muda scores exatos em testes
que nao isolam esse termo -- achado do bloco 613).

### Log novo no banco: rode `scriptis_da_ia/pos_log_novo.sh`

> Sugestao do usuario (28/08/2026, bloco 707): *"toda vez que um log
> entrar no banco para as partidas humanas"*. Reune num comando so o que
> ja era obrigatorio (regenerar `human_patterns.json` + `smoke_fast.py`)
> e o que passou a ser util depois da fase 2 (reconstruir
> `metrics/policy_dataset.jsonl` e re-rodar `curva_aprendizado.py`).
>
> ```bash
> cd scriptis_da_ia && ./pos_log_novo.sh
> ```
>
> **Por que a curva entra aqui**: medido no bloco 707, a validacao do
> ranqueador aprendido **satura em ~26% entre 10 e 24 lideres**, ABAIXO
> do baseline (28,5%). Enquanto ela continuar plana, **mais partidas
> humanas do mesmo tipo NAO desbloqueiam esse caminho** -- o gargalo
> medido e REPRESENTACAO (as 59 features de propriedade), nao volume.
> Nao pedir coleta de partidas alegando que "falta dado" sem antes olhar
> a inclinacao. Se ela passar a subir, o quadro muda -- e o passo existe
> justamente pra flagrar isso.
>
> Os passos de `human_patterns.json` continuam valendo por si: e
> calibragem que FUNCIONA (blocos 613/614) e ja era obrigatoria.

### Telemetria de decisao -- OBRIGATORIO ler quando o log e de partida do bot

Se o log veio de partida em que o **bot jogou** (nao humano vs humano), a
tarefa so termina depois de ler a telemetria. Pedido do usuario (23-24/07,
reforcado 17/09: *"eles tem que rodar como obrigacao, se nao vamos perder
dados"*). **Rodar e LER sao coisas diferentes -- e a leitura que e obrigatoria.**

Os arquivos sao **gitignored e local-only**. Em sessao remota/nuvem eles nao
existem: **declare isso explicitamente** em vez de reconstruir a intencao do
bot pelo combat log cru e reportar como investigacao completa.

**NESSA ORDEM, nunca pular pro segundo:**

1. **`metrics/live_runs/live_<ts>.json`** -- o QUANTO/ONDE OLHAR. `gate_status`,
   `bot_confusion`, `attack_quality`, e principalmente
   `score_components_coverage_pct`/`line_search_coverage_pct`: abaixo de 100%,
   uma fracao das decisoes **nao tem dado gravado pra auditar**.
   `mean_counterfactual_regret` baixo NAO prova decisao boa -- so mede contra o
   que a busca simulou; opcao que nunca virou candidata nao entra na conta.
2. **`python decision_summary.py --latest`** -- o O QUE exato: acao escolhida e
   alternativas descartadas com score, por decisao.
3. **`metrics/live_runs/efeitos_<ts>.txt`** -- **cada efeito disparado chegou ao
   fim?** Estagios OFERECIDO -> ESCOLHIDO -> ALVO -> CONCLUIDO. Foi assim que se
   achou o Enel escolhendo `"Gain 0 Active Don"` em 100% dos menus e o Streusen
   enterrando as cartas que acabou de ver -- **nenhum dos dois aparecia nos
   passos 1 e 2**. Filtrar: `python auditoria_efeitos.py --codigo <CODIGO>`.
   **CONFIRA `efeitos_error` no `receipt_<ts>.json`**: campo preenchido = a
   auditoria NAO rodou, e isso tem que ser dito, nao passar em silencio.

> **PENDENCIA**: a auditoria diz se o efeito CONCLUIU e QUAL alvo foi
> escolhido, mas **nao se foi o MELHOR alvo** -- falta `step_index`/`purpose`
> no `/choose_target`. Ver "MEDIR A QUALIDADE DO ALVO" no `TODO.md`.

> **Armadilha de leitura**: `LogOutput.log` **ACUMULA** e `server_stdout.log` e
> **TRUNCADO** a cada restart -- comportam-se ao contrario. Os alertas
> sobrevivem em `BOT/engine_server/logs/session_<ts>.log`.

### Eficiência agregada — OBRIGATÓRIO mostrar números, não só prosa

Pedido do usuário (23-24/07): parar de narrar "eficiência baixa" sem
número — sempre que uma sessão processa log(s) novo(s) do bot, rodar e
**mostrar a tabela** de `python bot_efficiency_report.py --manifest
<cohort>` (em `scriptis_da_ia/`). Não existe um cohort "atual" fixo — o
manifesto (`metrics/*.json`, schema em
`metrics/bot_efficiency_cohorts.json`) precisa ser atualizado/criado com
as partidas relevantes da sessão (mesmo líder, mesmo período) antes de
rodar, senão o relatório sai baseado em partidas antigas e engana. Métricas
que mais importam pra ineficiência: `dano_por_jogo` (dano total por
partida) e `don_observado_por_ataque` (quanto DON em média está anexado
quando o bot ataca — baixo = sintoma de curva/ramp ruim, não só de sorte).
Nenhuma sessão vê o histórico de conversa da outra — só o estado dos
arquivos. Por isso:
1. Sempre commitar antes de parar (créditos, fim de sessão).
2. Sempre escrever um bloco novo no topo do [HANDOFF.md](HANDOFF.md) antes
   de parar: o que foi feito, estado atual, o que falta.
3. Sempre refletir o mesmo delta no topo do [TODO.md](TODO.md) (versão
   resumida do bloco do HANDOFF — o que foi fechado, o que ficou pendente
   de validação, o que mudou de prioridade). `TODO.md` não pode ficar
   parado enquanto o `HANDOFF.md` avança (achado 24/07: `TODO.md` ficou 3
   dias desatualizado enquanto o `HANDOFF.md` já tinha 4 blocos novos).
4. Ao assumir uma sessão, ler `HANDOFF.md` + `TODO.md` +
   `git log --oneline -10` + `git status` antes de qualquer edição.

Isso é reforçado por um **hook de `pre-push`** (`scripts/hooks/pre-push`):
bloqueia o `git push` se `HANDOFF.md` **ou** `TODO.md` não tiverem sido
alterados nos commits sendo enviados. `.git/hooks/` não é versionado pelo
git, então em cada clone/máquina nova é preciso instalar uma vez:
```bash
sh scripts/setup-git-hooks.sh
```
Para pular a checagem numa emergência (não recomendado): `git push --no-verify`.

## Auditoria de derrotas reais contra humano -- ferramenta permanente

**OBRIGATORIO RODAR** (pedido do usuario, 09/08/2026), nao so saber que
existe: sempre que um combat log de **DERROTA do bot** entrar no banco, rode
antes de considerar a investigacao terminada:

```bash
cd scriptis_da_ia
python audit_real_losses.py --log <parsed/....json>   # ou --all [--limit N]
python triage_real_losses.py                          # classifica MATCH vs DIVERGE
```

Pula so quando a partida e humano-vs-humano ou o bot GANHOU.

**O que faz**: reconstroi o estado de cada turno a partir do log e pergunta ao
motor de HOJE o que ele faria (via `OPTCGMatch.play_turn()` real -- nao duplica
decisao). Relatorio em `metrics/real_loss_audits/`.

**Motivo**: segunda opiniao INDEPENDENTE. Sem ela, uma sessao reagindo so ao
combat log justifica cada escolha do bot com raciocinio pos-hoc.

**Como usar**: nao e verdade absoluta. Onde diverge, investigar se (a) um fix
ja feito explica, ou (b) o motor repete a MESMA escolha que perdeu -- ai e
achado real.

**Limitacoes honestas** (incl. `don_available` best-effort, deck de ordem
embaralhada, mao do oponente com informacao COMPLETA): documentadas no topo do
proprio `audit_real_losses.py`. **Leia antes de confiar num relatorio.**

> **LICAO DE METODO que custou caro (retificacao 04/08)**: o achado original
> desta secao ("92% da divergencia e o motor atacando mais, ZERO casos de
> atacar menos") estava **inflado por dois bugs na propria triagem** -- ela
> procurava a string `"Leader"` num campo que nunca a usa, e comparava
> `card_type=='LEADER'` contra um CSV que grava `'Leader'`. Numeros corretos:
> 132 "ataca mais", **44 "ataca menos"** (nao zero), 87 iguais.
> **SEMPRE conferir a logica de deteccao contra um caso conhecido a mao antes
> de reportar percentual agregado** -- nao confiar no agregado bater com a
> expectativa. Detalhe em [`REGRAS_HISTORICO.md`](REGRAS_HISTORICO.md).
