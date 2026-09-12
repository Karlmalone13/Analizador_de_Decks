# AGENTS.md — guia para qualquer sessão nova (Codex)

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

> Leia, nesta ordem, antes de propor qualquer coisa:
> **"O QUE EXISTE NAO E SAGRADO"** · **"A HEURISTICA NAO E REFERENCIA"** ·
> **"PLANO OFICIAL DA MIGRACAO PRA ML -- PROFESSOR/ALUNO"**.


> **Espelho**: este arquivo e [`CLAUDE.md`](CLAUDE.md) (lido pelo Claude
> Code) devem conter as MESMAS regras de projeto — só a moldura muda
> (nome da ferramenta, caminho da memória local). Se adicionar/editar
> uma regra aqui, replique a mesma edição lá (achado 25/07/2026: os
> dois divergiram por meses sem ninguém notar — sessões Codex ficaram
> sem várias regras que só entravam no `CLAUDE.md`, sincronizado nesta
> sessão).

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

Antes de commitar qualquer coisa, este `AGENTS.md` é o mecanismo oficial de
instruções persistentes do repo. Memórias locais do Codex são auxiliares e
não substituem documentação versionada — a memória local do Codex, quando
ativada via `/memories` ou `[features] memories = true` em `config.toml`,
fica em `C:\Users\arthu\.codex\memories\` nesta máquina; é estado gerado
automaticamente, não é fonte de regras obrigatórias nem portável entre
máquinas — nunca depender dela para uma decisão de arquitetura.

> **ESCOPO (espelhado do `CLAUDE.md`, 27/08/2026)**: o mesmo vale pro
> caminho de memória do Claude Code
> (`C:\Users\arthu\.claude\projects\...\memory\MEMORY.md`) — leitura
> obrigatória **se acessível**, mas em sessão **remota/nuvem esse caminho
> não existe** e a regra fica incumprível. Nesse caso a fonte de regra é
> a documentação versionada, e a sessão deve **declarar** que a memória
> local estava indisponível. Memória local **nunca** é a única fonte de
> uma regra obrigatória: se uma regra só existe lá, tem que ser promovida
> pra cá. (Esta divergência específica ficou meses sem ser notada — o
> `AGENTS.md` tinha a versão certa e o `CLAUDE.md` não.)

Regras-chave (resumo — leia o resto deste arquivo):

- **Bot = olhos/mãos only** (`bot_optcgsim.py`). Engine = cérebro. Sem lógica
  de carta no bot. Sem dois motores.
- **Objetivo do bot**: captar logs contra humanos → validar engine → front-end.
  Não otimizar o bot além disso.
- **Sem função duplicada** (extensão da regra "sem dois motores", pedido do
  usuário 25/07/2026): nunca ter duas funções diferentes respondendo à MESMA
  decisão do jogo (o que jogar/descartar/qual alvo escolher/vale pagar um
  custo). Leitura **obrigatória** antes de qualquer commit/push que toque
  `decision_engine.py`, `sim_bridge.py`, `server.py`, `replay_optcg.py` ou
  `bot_optcgsim.py`:
  [`scriptis_da_ia/REGRA_SEM_DUPLICACAO.md`](scriptis_da_ia/REGRA_SEM_DUPLICACAO.md)
  (impresso por inteiro pelo hook `pre-commit`) — tem os casos reais já
  achados/corrigidos e como caçar duplicatas novas antes de aceitar uma
  função de decisão nova.

---

Este arquivo é lido automaticamente no início de cada sessão do Codex.
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

## Placar de qualidade de decisão por líder — OBRIGATÓRIO antes de avaliar se o bot "sabe jogar" um deck

> **OBRIGATÓRIO** (pedido explícito do usuário, 10/08/2026, bloco 485):
> sempre que a avaliação for "o bot sabe jogar com este líder/deck?" —
> não "quem ganha mais" — rode primeiro
> `scriptis_da_ia/decision_quality_report.py --leader <CODIGO> --n 20-30
> --workers 4` **antes** de olhar winrate agregado. Nasceu da auditoria do
> Sanji OP12-041 (blocos 482-484): o líder ficou preso em ~10% de winrate
> mesmo depois de 3 correções de código diferentes, e o usuário definiu o
> critério real — **"não tem problema perder a partida, as vezes o deck
> só é fraco mesmo, nós só precisamos garantir de que o bot entende o
> deck e toma as melhores decisões, maximizando a play com o deck"**.
> Winrate mede sorte de matchup; não distingue "bot jogou mal" de "deck é
> fraco/matchup ruim" — este relatório mede qualidade de decisão
> independente do resultado.
>
> **O que mede** (os três sinais lidos direto do `decision_log`/estado
> real do motor — NÃO reimplementa elegibilidade própria, contra
> `REGRA_SEM_DUPLICACAO.md`):
> 1. **Utilização da habilidade do líder** ([Activate: Main]): em quantos
>    turnos o Turn Planner ofereceu a habilidade como candidata legal vs.
>    quantos turnos ela foi de fato escolhida. Líderes sem
>    [Activate: Main] reportam N/A. **Ressalva (achado real 10/08,
>    Nefeltari Vivi EB03-001, bloco 489)**: quando o custo inclui restar
>    o PRÓPRIO líder (`rest_self`), ativar é mutuamente exclusivo com
>    atacar esse turno — taxa baixa aí não é comparável a líderes cujo
>    custo é DON (compatível com atacar também); o script já avisa
>    quando detecta esse tipo de custo.
> 2. **DON deixado na mesa** no fim de cada turno do próprio lado —
>    recurso não aproveitado, independe de vitória/derrota.
> 3. **Utilização por CARTA** (pedido explícito do usuário, mesmo dia:
>    "não quero só conferir efeito do líder, preciso saber se os efeitos
>    das outras cartas estão sendo utilizados") — mesmo mecanismo do
>    item 1, generalizado por CÓDIGO de carta (personagens/Eventos
>    jogados, incl. reanimados via `play_from_trash`): quantos turnos
>    apareceu como candidata vs. foi escolhida, tabela ordenada do pior
>    aproveitamento pro melhor. Limitação honesta documentada no
>    docstring: `decision_log` só grava os top-8 candidatos por decisão
>    — uma carta que nunca chega perto de ser a melhor opção não aparece
>    na tabela, mesmo estando na mão.
>
> Uso: `python decision_quality_report.py --leader OP12-041 --n 30
> --workers 4 [--top-cartas N] [--min-ofertas N]` (`scriptis_da_ia/`).
> Referência calibrada nesta sessão (20 partidas cada, seed=77): Sanji
> OP12-041 ativou a habilidade em 98,3% dos turnos elegíveis (118/120) e
> terminou 61,6% dos turnos com 0 DON sobrando — **mesmo perdendo 85%
> das partidas**, confirmando que o bot usa o mecanismo central do deck
> quase sempre; Mihawk OP14-020 (88,2%) e Imu OP13-079 (99,1%) deram
> números na mesma faixa, como esperado de líderes com winrate saudável.
> Item 3 no Sanji achou 2 cartas com utilização baixa (`Boeuf Burst`
> OP12-060, 14,3%; `Gum-Gum Jet Culverin` OP11-061, 0%) — **investigadas
> a fundo (bloco 487) e NÃO são bug**: rastreamento manual de cada
> ocorrência no `decision_log` mostrou que, toda vez que não foram
> escolhidas, perderam pra uma alternativa com score legitimamente MAIOR
> no mesmo turno (ativar a habilidade do líder, atacar, outra carta) —
> competição real por DON escasso, não erro de avaliação. **Lição
> registrada pra sessões futuras**: uma taxa baixa no item 3 é PONTO DE
> PARTIDA pra investigar (rastrear 3-5 ocorrências reais comparando
> score contra o `chosen` de cada uma), nunca um veredito automático de
> bug — só escale se a alternativa vencedora for consistentemente pouco
> melhor ou claramente pior, não só "não foi a escolhida desta vez".
> Complementa (não substitui) a comparação obrigatória contra
> `IA_Compendium/RESUMO_ESTRATEGICO.md` acima — o placar dá o "quanto",
> o catálogo dá o "o que era esperado".

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

**Antes de propor ou implementar qualquer mecanismo, responda em uma
linha: de qual PREMISSA ele depende, e como ela seria testada?**

Se a premissa for barata de testar, **teste ANTES de construir**. Custo
real medido em 10/09: tres experimentos de ~1h cada foram gastos
descobrindo que "o ML muda resultados" era falsa -- 20 minutos testando a
premissa teriam levado direto a mudanca de arquitetura.

> ## EXIGENCIA CENTRAL DO USUARIO -- leia isto antes de propor QUALQUER coisa de ML
>
> **O ML tem que APRENDER EMPIRICAMENTE. Ele NAO pode ser uma ferramenta da
> heuristica.**
>
> Citacoes diretas, ao longo de 10-11/09/2026, **repetidas porque a sessao
> nao executava**:
> - *"quero que o ML faça o bot aprender, já te disse isso inúmeras vezes"*
> - *"preciso que ML seja um ML e aprenda"*
> - *"temos que criar um ML de verdade e não só um analizador/regulador"*
> - *"ele tem que ser capaz de aprender e descobrir e não só regular"*
> - *"temos que fazer um ML de verdade para o Bot aprender empiricamente e
>   não fazer o ML ser uma ferramenta da heurística"*
>
>

> ### BURACO CONFIRMADO (11/09/2026, achado do usuario): a DEFESA esta 100% FORA do ML
>
> Pergunta dele: *"e tb precisamos treinar defesa, quando alguem ataca o
> bot"*. Verificado no codigo -- `should_use_blocker`, `should_use_counter` e
> `pick_counters` fazem **ZERO** consultas a busca ou ao modelo. Sao heuristica
> fixa pura.
>
> Bate com a qualidade de decisao ja medida, sem ninguem ter ligado os pontos:
>
> | decisao defensiva | acerto contra humano | volume |
> |---|---|---|
> | bloquear ou nao | 85,7% | 1.326 |
> | usar counter ou nao | 59,7% | 1.186 |
> | **quais cartas de counter** | **18,5%** | 804 |
>
> A ultima e uma das **tres piores categorias do projeto inteiro** -- e a causa
> agora esta identificada: escolhida por regra fixa, sem busca e sem modelo.
>
> **3.316 de 14.973 decisoes (22%) estao FORA do alcance do ML**, e sao caras:
> determinam se o bot toma dano.
>
> **Isto reforca a tese do usuario**: o ML nao esta perdendo por ser fraco --
> esta **impedido de participar** de boa parte do jogo. Um modelo melhor nao
> muda nada em 22% das decisoes, por construcao.
>
> **Pendente**: levar a decisao defensiva pra dentro da busca/modelo. Nao
> tentado ainda.
>
> **MAIS DUAS, apontadas pelo usuario no mesmo dia e VERIFICADAS no codigo:**
>
> | decisao | como escolhe hoje | ML alcanca? |
> |---|---|---|
> | carta no SEARCH (procurar no deck) | `max(candidates, key=self._trash_value)` | **nao** |
> | reviver do TRASH | `sorted(fuel, key=board_value, reverse=True)` | **nao** |
>
> Sao decisoes de alto impacto -- buscar a peca errada ou reviver o
> personagem errado define o turno -- e nenhuma delas passa por busca ou
> modelo. **Regra fixa de uma linha.**
>
> ### O quadro completo do que o ML NAO alcanca
>
> | decisao | ML alcanca? |
> |---|---|
> | qual acao de topo (jogar / atacar / ativar / anexar DON / passar) | **sim** |
> | em quem mirar o efeito | nao (`max(board_value)`) |
> | bloquear ou nao, e com quem | nao |
> | usar counter, e quais cartas | nao |
> | **qual carta pegar num search** | **nao** |
> | **quem reviver do trash** | **nao** |
>
> **O ML participa de UMA das seis familias de decisao.** Isso, e nao a
> qualidade do modelo, e o teto que nenhuma melhoria de treino atravessa.
>
> ### INVENTARIO COMPLETO (11/09/2026, a pedido do usuario): **81 decisoes FIXAS em 28 funcoes**
>
> Pedido: *"Faca uma busca e verifique tudo que for fixo e exija decisao, o
> ML tem que treinar"*. Ferramenta: `audita_decisoes_fixas.py` -- procura
> escolha de UM entre VARIOS por `max`/`min`/`sorted` com chave heuristica,
> em `decision_engine.py`, `rules_facade.py` e `sim_bridge.py`.
>
> | familia | funcoes | ocorrencias |
> |---|---|---|
> | **execucao de efeito** | `_execute_step` | **27** |
> | **pagar custo** (o que sacrificar) | `_pay_costs`, `_pay_substitute_cost` | **16** |
> | **bot AO VIVO** (responder prompt do jogo) | `resolve_prompt_choice`, `escolher_opcao_de_efeito`, `sort_key` | **9** |
> | defesa | `_should_use_blocker_inner`, `try_counter_event_debuff` | 4 |
> | alvo de efeito | `_pick_effect_target_inner` | 2 |
> | descarte | `_choose_to_trash`, `choose_to_trash`, `_execute_attack_inner` | 3 |
> | stage inicial | `_place_start_stage` | 2 |
> | utilitarios da facade | `choose_highest/lowest_board_value` | 5 |
>
> **`_execute_step` sozinha tem 27**: toda vez que uma carta FAZ alguma coisa,
> quem escolhe o alvo/a carta e uma linha de `max`/`min` -- nunca o modelo.
>
> **O bot AO VIVO tem 9 proprias**: quando o jogo pergunta algo durante uma
> partida real contra o usuario, a resposta sai de regra fixa.
>
> **E quase todas usam a MESMA chave**: `board_value()` ou `_trash_value`.
> **Duas funcoes heuristicas escolhem praticamente tudo no jogo.**
>
> RESSALVA de metodo: a varredura e heuristica, entao algumas ocorrencias sao
> ordenacao interna e nao escolha (ex: o `sorted` de `_lethal_search` e o de
> `_explorar`). O numero exato de decisoes reais e um pouco menor que 81 --
> mas a ordem de grandeza e essa, e nenhuma delas passa por modelo.
>
>
> ### O CAMINHO QUE O INVENTARIO REVELA: nao sao 28 problemas, sao DOIS
>
> Observacao do usuario que fecha o raciocinio: *"se nao a gente treina so
> uma coisa e o bot continua perdendo"*. Correto -- e o inventario mostra o
> atalho:
>
> **Quase todas as 81 decisoes fixas usam as MESMAS duas chaves:
> `board_value()` e `_trash_value`.** O resto do motor so chama `max`/`min`
> em cima delas.
>
> Entao nao e preciso reescrever 28 funcoes pra consultarem o modelo: basta
> **trocar a REGUA que as 28 ja usam**. O ML alcanca tudo de uma vez.
>
> **E da pra fazer sem treinar nada novo**, usando a rede de valor que ja
> existe:
>
> ```
> valor(carta) = P(vencer | posicao) - P(vencer | posicao SEM essa carta)
> ```
>
> A carta passa a valer o quanto ela muda a chance de vitoria -- precificada
> por CONSEQUENCIA MEDIDA, em vez de `power // 1000 + bonus de keyword`
> escrito a mao.
>
> Com isso o ML passa a decidir: qual alvo eliminar, o que sacrificar pra
> pagar custo, quem bloquear, quais counters gastar, o que buscar no deck,
> quem reviver do trash, o que descartar. **Todas, porque todas passam pela
> mesma regua.**
>
> **Custo a medir antes de adotar**: cada precificacao vira uma consulta ao
> modelo (2,1ms, ou cache). Com 81 pontos de decisao isso pode pesar -- e o
> memo de `win_prob` (bloco 766) ja existe justamente pra isso. **Nao
> adotado ainda, so desenhado.**

>
> ### CORRECAO MEDIDA (12/09/2026): a tese do ALCANCE esta ENFRAQUECIDA
>
> A secao acima concluia que o problema era **alcance** -- o ML participa de
> 1 de 6 familias, e isso seria o teto. **Medido, e nao se sustenta como
> estava escrito.**
>
> Instrumento (`mede_alavanca.py`, bloco 777): um lado decide a familia no
> ALEATORIO, o outro pela regra. Se o aleatorio nao perder, a familia nao
> importa.
>
> | familia | empate | pares que decidiram | winrate no ALEATORIO |
> |---|---|---|---|
> | **acao de topo** (onde o ML JA atua) | **72%** | -- | -- |
> | descarte | 81% | 15 de 80 | 40,0% |
> | alvo | 91% | 7 de 80 | 0,0% |
> | **blocker** | **100%** | **0 de 80** | -- |
>
> **Decidir qual blocker defende no CHUTE nao mudou o resultado de UMA
> partida em 80 pares.** As tres familias testadas empatam entre 81% e 100%.
>
> **A alavanca esta concentrada na ACAO DE TOPO -- exatamente onde o ML ja
> atua.** Levar o ML as outras familias existe como possibilidade, mas **nao
> paga**: nem decidir no aleatorio atrapalha.
>
> O inventario das 81 decisoes fixas **continua correto como fato** -- elas
> existem e sao regra fixa. O que caiu foi a INFERENCIA de que elas eram o
> teto.
>
> **Ressalva de amostra**: 7, 0 e 15 pares discordantes. O blocker e forte
> (zero em 80). Os outros dois sao indicativos. **Nao medidas ainda**: pagar
> custo, e carta do search / reviver do trash.
>
> ### RESSALVA DE ESCOPO -- MUITO MAIOR que a de amostra (12/09/2026, bloco 780)
>
> **Achado do usuario, e ele esta certo:** *"o meu receio do bot treinar
> contra ele mesmo e ele manter vicios -- por exemplo nao fazer combos, nao
> acertar sequenciamento e nao defender direito, e mesmo assim vencer a
> partida"*.
>
> **Isso limita o que a tabela acima pode afirmar.** `mede_alavanca.py` roda
> em AUTO-JOGO: um lado decide a familia no aleatorio e o outro e **o mesmo
> motor**. Entao o que foi medido nao e
>
> ~~"escolher mal o blocker nao custa nada"~~
>
> e sim
>
> **"escolher mal o blocker nao custa nada CONTRA O NOSSO PROPRIO MOTOR"**.
>
> Um vicio COMPARTILHADO e invisivel ao auto-jogo por construcao: o
> adversario so pune o que ele proprio sabe explorar. Chutar o blocker nao
> perdeu partida porque o outro lado **nao sabe punir bloqueio ruim** -- nao
> porque bloquear bem seja irrelevante contra gente.
>
> **O dado independente aponta o contrario**: as tres piores categorias
> medidas contra humano sao exatamente os vicios que o usuario nomeou --
> `sequenciamento` 36,4%, `distribuicao de DON` (combos) 23,5%, `quais cartas
> de counter` (defesa) 18,5%.
>
> **Consequencia pratica**: nenhuma familia de decisao pode ser descartada
> com base SO em auto-jogo. Pra afirmar "nao paga" e preciso medir contra
> dado que nao compartilhe o vicio -- banco de logs humanos, ou partida
> contra o usuario. A tabela acima continua valida para o que mediu, e **nao
> autoriza** a conclusao mais forte que eu tinha registrado.

### O BURACO ESTRUTURAL que o usuario mandou RESOLVER (12/09/2026)

> *"O modelo escolhe entre o que as regras produzem -- o que nao vira
> candidato nao existe. Vamos resolver isso tb"*.

Estava registrado como "NAO resolvido" desde 10/09 e nunca foi atacado.
**Agora esta em escopo, por pedido explicito.**

O ML so pontua o que `_generate_and_score_actions` coloca na lista. Uma linha
legal pelas regras que nunca vira candidata e **invisivel pra sempre** --
nenhum modelo melhor, nenhum corpus maior e nenhuma exploracao a alcanca,
porque exploracao tambem sorteia DENTRO da lista gerada.

E o teto mais duro do sistema, e e diferente de todos os outros ja medidos:
os outros sao sobre ESCOLHER melhor; este e sobre **existir** o que escolher.


>
> **Onde investir, entao**: o ML ja esta na familia que importa, e la o que
> mediu progresso foi QUANTIDADE DE DADO -- 23x de corpus rendeu +22pp de
> winrate (10,0% -> 31,8%, bloco 775). E a unica alavanca com ganho medido e
> trajetoria clara.

> **AGENDA -- CORRIGIDA em 12/09/2026 (bloco 780).** A versao anterior desta
> linha dizia *"o ML nao precisa melhorar, precisa ALCANCAR"*. **Isso foi
> refutado pela medicao logo acima** (`mede_alavanca.py`, bloco 777) e mesmo
> assim continuava escrito aqui, depois da propria correcao -- quem lesse de
> cima pra baixo terminava com a conclusao derrubada.
>
> **A agenda que vale**: o ML ja esta na familia de decisao que importa (a
> acao de topo, 72% de empate -- a menor medida). Levar o ML as outras
> familias **nao paga**: decidi-las no aleatorio quase nao muda o resultado
> (blocker 100% de empate, zero pares discordantes em 80). A unica alavanca
> com ganho medido e trajetoria clara e **QUANTIDADE DE DADO** -- 23x de
> corpus levou o AUC de 0,632 a 0,856 e o ML autonomo de 10,0% a 31,8%.
>
> O inventario das 81 decisoes fixas continua correto como FATO. O que caiu
> foi a inferencia de que elas eram o teto.



> ### REGRA OBRIGATORIA E VERIFICAVEL -- declare isto ANTES de rodar qualquer experimento de ML
>
> **Todo experimento de ML tem que declarar, em uma linha, qual dos dois ele e:**
>
> | tipo | o que faz | permitido? |
> |---|---|---|
> | **A. ML DECIDE** | o modelo escolhe/avalia, a heuristica sai ou nao entra | **SIM -- e a direcao** |
> | **B. ML CALIBRA** | o modelo e somado a heuristica (`+ (win_prob-0.5)*peso`) | **SO com justificativa explicita** |
>
> **Se o experimento e do tipo B, ele precisa dizer POR QUE nao e do tipo A**
> -- e "porque o modelo ainda nao e bom o bastante" nao basta sozinho: tem que
> vir com o que aquele experimento faz pra chegar no tipo A.
>
> **Motivo desta regra** (usuario, 11/09/2026, ao me pegar escorregando):
> *"esqueceu do nosso combinado ou tá tentando transformar o ML em calibrador
> do estatico?"*. Eu tinha acabado de propor gerar um corpus grande sem dizer
> pra que -- e treinar+ligar a peso 200 seria o calibrador de novo, sem eu
> perceber. **A deriva pro tipo B e silenciosa e acontece por inercia**, porque
> e o caminho que o codigo ja oferece pronto.
>
> **Exemplo do enquadramento CERTO, do mesmo dia**: corpus grande **nao** pra
> melhorar o ajuste sobre a heuristica, e sim pra dar ao **ML AUTONOMO** a
> primeira chance justa -- ele perdeu 1x9 no bloco 769 com AUC 0,63 e apenas
> 3.614 estados. **O teste seguinte tem que ser o ML DECIDINDO SOZINHO**, nao o
> ML somado. Sem declarar isso antes, o experimento vira tipo B por inercia.

> ### O que ele cobrou da sessao, e PROCEDE
>
> *"Eu peço para migrarmos da heurística para um ML [...] ai vc faz o que,
> cria uma ferramenta avaliativa e reguladora da heurística"*.
>
> A arquitetura de regulador e ANTERIOR a essa sessao, mas o adiamento foi
> real: o usuario pediu MIGRACAO varias vezes e recebeu portao, cache,
> features, exploracao, PyPy -- tudo em volta. O argumento *"nao ha o que
> substituir ate o ML vencer um duelo"* e tecnicamente defensavel e, na
> pratica, foi adiamento.
>
> **Qualquer sessao futura que se pegue propondo melhoria AO REDOR do ML em
> vez de fazer o ML decidir esta repetindo esse erro.**
>
> ### O que "ferramenta da heuristica" significa concretamente
>
> Hoje: `score = _evaluate_state_v2(...) + alinhamento + (win_prob-0.5)*peso`.
> O ML empurra no MAXIMO +-100 pontos. Se a heuristica diz 400 contra 300,
> ele **nao inverte**, mesmo tendo aprendido que a de 300 e melhor. **Herda
> o erro dela por construcao.**
>
> Precisao necessaria: ele **aprende** (AUC fora da amostra sobe com mais
> partidas -- aprendizado medido). O que ele nao consegue e **agir** sobre o
> que aprendeu. O efeito pratico e o que o usuario descreve, e a conclusao e
> a mesma: **a arquitetura tem que mudar.**
>
> ### O que ja foi medido tentando (nao repetir sem ler)
>
> | tentativa | resultado |
> |---|---|
> | ML avalia logo apos a acao, sem rollout (bloco 769) | **14,8x mais rapido** e **PERDE 1x9** -- AUC cai de 0,76 pra 0,63 porque julga turno pela metade |
> | Cortar so a resposta do oponente (bloco 770) | 5,1x mais rapido e **PERDE 3x12** |
>
> **Conclusao medida**: a busca esta ganhando o que custa. **O ML nao
> substitui a busca HOJE porque ainda nao e bom o bastante** -- nao porque a
> direcao esteja errada.
>
> ### A ordem correta, que decorre disso
>
> 1. **Fazer o modelo ficar bom** -- corpus grande, tratar sobre-ajuste
>    (0,99 treino x 0,63 teste), features de contexto de turno, exploracao
>    no auto-jogo (ja implementada, bloco 767).
> 2. **So entao** a busca pode encolher, porque o modelo passa a fazer o
>    trabalho dela.
> 3. E a heuristica sai por partes, cada remocao passando pelo portao SPRT.
>
> **Isto nao autoriza adiar de novo.** O passo 1 E o trabalho de ML de
> verdade -- nao e pre-requisito burocratico pra ele. Se uma sessao esta
> mexendo em portao, cache, velocidade ou ferramenta de analise e NAO esta
> tornando o modelo melhor, ela esta fora da direcao.


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

## A REDE DE VALOR E UM *SURROGATE MODEL* -- o nome certo, dado pelo usuario (12/09/2026)

> *"Acho que estamos indo para (Surrogate Models)"*.

**Esta certo, e nomear isso muda como o projeto raciocina.** Um surrogate
model (emulador) e uma funcao rapida treinada pra IMITAR um calculo pesado.
E exatamente o que a rede de valor faz: substitui o rollout Monte Carlo
(simular o resto do turno + o turno do oponente) por uma consulta de ~2ms.

Isso da a esta linha de trabalho uma literatura e um criterio proprios: a
pergunta deixa de ser *"o ML esta ajudando?"* e passa a ser **"o emulador
reproduz o que o simulador caro diria, com erro aceitavel?"**.

### O que o Monte Carlo de hoje E, exatamente

**Monte Carlo PLANO** -- verificado no codigo (bloco 781): nao ha arvore, nao
ha UCB/UCT. Cada candidata recebe simulacoes independentes e o orcamento e
DIVIDIDO entre elas (ha parada sequencial, que ajuda, mas nao realoca).

E dai vem a patologia medida: **ramo novo rouba precisao dos ramos antigos**.
Por isso "alargar o shortlist" regrediu em 3 medicoes independentes (blocos
593, 594, 677). **Nao e que olhar mais opcoes seja ruim -- e que olhar mais
custa olhar pior.** Com um surrogate essa penalidade some: cada ramo custa
~2ms fixos e nao tira nada de ninguem.

### O que se aplica e o que NAO se aplica (pesquisa trazida pelo usuario)

| ferramenta | aplica aqui? |
|---|---|
| **Surrogate model / emulador** | **SIM -- e o caminho, ja em teste** |
| Tabela de transposicao (hash de posicao) | **SIM -- 58% das linhas convergem pro MESMO estado (bloco 756). Trabalho duplicado medido** |
| Busca exaustiva do PROPRIO turno + rede nas folhas | **SIM -- e o analogo honesto de "alpha-beta + NNUE"; `_lethal_search` JA e isso, so nao saiu de dentro da prova de lethal** |
| Reducao de variancia | **em parte** -- e ja usamos uma: sementes comuns no duelo pareado (bloco 756) |
| Alpha-beta puro | **NAO como no xadrez**: poda alfa-beta e provadamente correta so com INFORMACAO PERFEITA. Aqui a mao do oponente e oculta e ha aleatoriedade (compra, trigger) |
| MCTS / ISMCTS | possivel, mas ganho modesto: arvore de 4,9 candidatas e horizonte de 1 turno. MCTS brilha em arvore profunda e larga |
| **QMC (Sobol/Halton), quadratura gaussiana, elementos finitos** | **NAO -- outro dominio.** Sao ferramentas de INTEGRACAO NUMERICA e equacoes diferenciais: problemas continuos e suaves. O nosso e combinatorio discreto ("qual carta, em quem, quanto DON") -- nao ha funcao suave pra integrar |

### A ordem recomendada pra SAIR do Monte Carlo

**Nao de uma vez.** Em duas etapas, e a primeira ja entrega a arvore larga:

1. **Surrogate como ORDENADOR** (nao decisor): o modelo pontua TODAS as
   candidatas; o rollout caro roda so nas 2-3 melhores. **Nao exige que o
   surrogate ganhe do rollout** -- exige so que ele ordene melhor que a
   heuristica, que hoje e LITERALMENTE CEGA nas dimensoes novas (da score
   IDENTICO a variantes de alvo, ver `ALVO_EFEITO_MAX_CANDIDATOS`). E a
   arquitetura do Stockfish moderno: avaliador rapido ordena, busca confirma.
2. **Surrogate como DECISOR**: o rollout sai inteiro (~85% do tempo).

> **DISTINCAO OBRIGATORIA de um mecanismo REPROVADO**: a "rede de POLITICA
> pra podar o shortlist" foi reprovada no bloco 772, e a causa registrada foi
> *"nao ha o que podar -- a arvore e estreita (4,5 candidatas)"*. A proposta
> acima e **diferente em especie**: (a) e rede de VALOR avaliando o estado
> resultante, nao politica prevendo a escolha da busca; (b) o objetivo e
> ORDENAR uma arvore LARGA, nao podar uma estreita -- ou seja, a premissa que
> derrubou aquela ideia (arvore estreita) e exatamente o que esta sendo
> mudado. Citar isto ao propor, conforme a regra do `REPROVADOS.md`.

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

### COMO fazer -- por partes e COM PORTAO, nunca de uma vez

**Substituicao nao autorizada em bloco.** O ML ainda **nao venceu nenhum
duelo** (bloco 762: a unica promocao era falso positivo; bloco 764: visao
rica ficou em 20x11, inconclusivo). Trocar uma heuristica madura por um
modelo nao provado regride, e o projeto ja tem o mecanismo pra impedir
isso: **cada pedaco removido tem que passar no portao SPRT**
(`duelar_sprt`, bloco 762) contra a versao com o pedaco ainda la.

Ordem sugerida (do mais barato/menos arriscado pro mais):
1. **Subir o peso do ML** ate ele dominar, medindo a cada passo -- nao
   exige remover nada, e mede quanto o ML aguenta sozinho.
2. **Remover termos da heuristica um a um**, do menos importante pro mais,
   com duelo a cada remocao.
3. So ao fim, se sobrar pouco, avaliar remover `_evaluate_state_v2`.

**Pre-requisito honesto**: enquanto o ML nao ganhar UM duelo sequer, nao
ha o que substituir. A prioridade continua sendo fazer o ML ficar bom
(visao rica, horizonte do rotulo, corpus maior) -- a substituicao e a
CONSEQUENCIA disso, nao o caminho pra chegar la.


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
- Ligar/mudar `VALUE_NET_WEIGHT` por default em producao continua sendo
  mudanca **SERIA** (regra de 28/08): exige autorizacao explicita.

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

### `human_patterns.json` — OBRIGATÓRIO regenerar junto com o banco de logs

> **Achado real 18/08/2026 (bloco 613)**: `human_patterns.json`
> (calibragem que ensina o motor a partir de sequências REAIS de
> decisão humana — `play`/`activate`/`attack`/`attach_don`/`counter`,
> lida por `_human_pattern_bonus`/`_human_counter_card_bonus` em
> `decision_engine.py`) ficou **10 dias desatualizada, treinada em só
> 7 logs**, enquanto o banco cresceu pra 150 sem ninguém regenerar o
> arquivo — 21x mais dado real nunca incorporado. Regenerar sozinho
> (medido, blocos 613/614) já subiu `play`/`attack`/`attach_don`/
> `counter` de verdade, sem precisar de nenhuma mudança de lógica.

Sempre que um log novo entrar no banco (`logs/parsed/`, via
`parse_combat_log.py --add-to-db` acima) — **Claude ou Codex, quem
estiver na sessão, tem que regenerar `human_patterns.json` antes de
considerar a tarefa terminada**, mesmo padrão de obrigatoriedade do
banco de logs em si. Não precisa ser a cada log individual dentro da
MESMA sessão (regenerar 1x no fim da sessão que adicionou logs basta),
mas nenhuma sessão deve terminar com logs novos no banco e o arquivo
de calibragem desatualizado.

**Como fazer** (ferramenta já existe, não reinventar):
```bash
cd scriptis_da_ia
python audit_human_patterns.py --logs-dir logs/parsed --output human_patterns.json --min-support 2
```
Depois de regenerar, rodar `smoke_fast.py` (o bônus por padrão humano
pode mudar scores exatos em testes que não isolam esse termo — achado
real do bloco 613, um teste pré-existente quebrou por assumir bônus
sempre 0) e considerar medir o impacto real via
`decision_quality_full.py --all` antes de commitar, mesma disciplina
de "medir antes de aceitar" do resto do projeto.

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

### Telemetria de decisão — OBRIGATÓRIO ler quando o log é de partida do bot

Se o log adicionado ao banco veio de uma partida em que o **bot jogou de
verdade** (não humano vs humano), a tarefa só termina depois de ler o
resumo de decisões — não é opcional, e não é suficiente só olhar o combat
log/resultado da partida (pedido do usuário, 23/07 e reforçado 24/07: "a
leitura da telemetria tem que ser obrigatória depois que o log chega no
banco", pra garantir que a eficiência do bot é realmente investigada e
melhorada, não só medida — depois de repetidas vezes o mesmo tipo de erro
passar despercebido).

**Essa telemetria (`BOT/engine_server/logs/` e
`scriptis_da_ia/metrics/live_runs/`) é gitignored de propósito — só existe
no disco local de quem rodou o bot.** Isso significa:
- Numa sessão **local** (com acesso a esse filesystem): ler é obrigatório
  e incondicional, sempre que um log de partida do bot for pro banco —
  nunca pular pra "olhar só o combat log" por conveniência.
- Numa sessão **remota/nuvem** (sem esse acesso): esses arquivos
  simplesmente não existem no ambiente. Não dá pra cumprir o passo —
  **declare isso explicitamente** ("telemetria de decisão indisponível
  nesta sessão, é gitignored e local-only") em vez de reconstruir a
  intenção do bot só pelo combat log bruto e reportar como se fosse
  investigação completa (foi exatamente esse gap que gerou o achado do
  bloco HANDOFF 342 — a sessão remota teve que adivinhar via combat log
  cru porque não tinha outro jeito).

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

## Trabalhando junto com outra IA (Claude ou outra sessão Codex)
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

## Auditoria de derrotas reais contra humano — ferramenta permanente

> **Registro obrigatório de existência** (pedido do usuário, 04/08/2026):
> ferramenta criada nesta sessão, `scriptis_da_ia/audit_real_losses.py`.
> Sessões futuras devem SABER que ela existe e usá-la — não reinventar.

> **OBRIGATÓRIO rodar, não só saber que existe** (pedido explícito do
> usuário, 09/08/2026): sempre que um combat log de DERROTA do bot
> (`winner` != `bot_side` no `logs/index.json`) for adicionado ao banco,
> rode `audit_real_losses.py --log <parsed/....json>` (e depois
> `triage_real_losses.py` pra classificar MATCH vs DIVERGE) ANTES de
> considerar a investigação da partida terminada — não é opcional, não é
> "se sobrar tempo". Motivo do pedido: uma sessão inteira reagindo
> decisão-a-decisão só a partir do combat log cru e da telemetria, sem
> essa segunda opinião independente do motor de hoje, arriscava
> justificar cada escolha do bot com raciocínio pós-hoc em vez de
> confirmar (ou contradizer) com uma fonte separada. Ver
> [`.claude/skills/optcg-live-log-triage/SKILL.md`](.claude/skills/optcg-live-log-triage/SKILL.md)
> (Step 4) pro passo a passo — o skill de triagem de log já foi
> atualizado pra cobrir isso. Só pula quando a partida é humano-vs-
> humano (sem lado bot pra auditar) ou o bot GANHOU (a ferramenta é
> especificamente pra derrotas).

**O que faz**: pega uma derrota REAL do bot contra humano (banco de logs,
seção acima), reconstrói o estado do jogo (mão/campo/DON/vida) em cada
turno do bot a partir do snapshot do log, e pergunta pro motor de HOJE
(`decision_engine.py`, via `OPTCGMatch.play_turn()` real — não duplica
decisão) o que ele faria. Salva um relatório por partida em
`scriptis_da_ia/metrics/real_loss_audits/<nome_do_log>.json` com a ação
histórica vs a narrativa do motor atual, turno a turno.

**Por que existe**: em vez de calibrar só contra self-play (decks de
`decklists_raw.csv` jogando contra si mesmos), usa pressão adversarial
REAL de humano — mais direto pra achar o que ainda falta pro bot vencer
partida de gente de verdade. Nasceu de uma ideia do usuário (forçar as
próprias decisões vencedoras dele contra o bot) que esbarrou num
problema real (decisão de humano só faz sentido pra mão/estado que ele
realmente teve) — a versão que ficou usa o HISTÓRICO como estado de
partida real, não como script fixo de decisões.

**Uso**:
```bash
cd scriptis_da_ia
python audit_real_losses.py --list                 # lista derrotas reais disponiveis
python audit_real_losses.py --log <caminho.json>    # audita 1 partida
python audit_real_losses.py --all [--limit N]       # audita todas (ou as N primeiras)
```

**Limitações honestas, documentadas no topo do próprio arquivo** (leia
antes de confiar cegamente num relatório): `don_available` é
reconstrução best-effort — `don_drawn` acumulado de todos os turnos do
jogador MENOS `attach_don` ainda "preso" num personagem (achado real
04/08: DON gasto em play/activate NÃO é perda permanente, desresta
sozinho no refresh do turno seguinte do dono, igual qualquer carta
descansada — versão anterior deste estimador subtraía esses custos
como gasto definitivo, achando "sem DON pra nada" numa mão que
historicamente tinha DON de sobra; confirmado revertendo esse erro
conceitual: o motor de hoje passou a jogar exatamente a mesma carta
cara que o histórico jogava no mesmo turno) — mesmo assim pode
divergir em jogos longos (DON que retorna ao ser removido do campo via
K.O./bounce não é rastreado); deck restante é uma COMPOSIÇÃO real (mesmo líder em
`decklists_raw.csv`) mas ORDEM embaralhada, não a ordem real; se o
líder não tem decklist real no banco (Marshall D. Teach/Krieg/Kid
confirmados ausentes), cai num deck genérico da mesma cor, mais fraco;
mão do oponente entra com informação COMPLETA (mesmo padrão do
self-play hoje, não mascarada como o caminho ao vivo) — o motor aqui
tem MAIS informação do oponente que o bot real teve, então resultado
tende a ficar "melhor" que o bot real conseguiria nessa exata situação,
nunca pior; primeiro turno de cada jogador é pulado (sem snapshot
"antes" pra reconstruir).

**Como usar o resultado**: NÃO é uma verdade absoluta, é uma segunda
opinião pra comparar contra o que aconteceu de verdade. Onde a
narrativa de hoje diverge da ação histórica, investigar se é (a) um fix
já feito nesta ou em sessão anterior explicando a diferença (bom sinal,
documentar), ou (b) o motor de hoje repete a MESMA escolha que perdeu a
partida — aí sim, achado real, investigar causa raiz igual qualquer
outro bug desta sessão (trace instrumentado, fix cirúrgico, validar com
`smoke_fast.py`/`smoke_test.py` + gauntlet antes de aceitar).

**Triagem em lote**: `scriptis_da_ia/triage_real_losses.py` lê todos os
relatórios de `metrics/real_loss_audits/*.json` e classifica cada turno
em `MATCH` (motor de hoje repete a decisão histórica — candidato a
achado real) vs `DIVERGE` (heurístico, baseado em texto — só prioriza o
que merece leitura manual, não é veredito automático).

> **RETIFICAÇÃO 04/08 (mesmo dia)**: o achado original desta seção
> ("92% da divergência é o motor atacando mais, zero casos de atacar
> menos, correlação de 246/266 com pre-29/07") estava **inflado por um
> bug na própria triagem**, achado ao ler os ~20 turnos residuais
> manualmente (pedido do usuário). `parse_historical` detectava ataque
> ao líder procurando a string literal `"Leader"` no campo `target` do
> log — mas o log histórico NUNCA usa essa palavra, sempre o
> nome+código real da carta (ex: `Marshall D. Teach ["OP16-080">
> OP16-080]`), mesmo quando o alvo É o líder. Resultado:
> `hist_leader_atk` ficava artificialmente preso perto de 0 quase
> sempre, inflando o "motor ataca mais" pra quase todo caso e
> escondendo qualquer caso real de "motor ataca menos". Um SEGUNDO bug
> (case-sensitivity: `card_type=='LEADER'` só batia 3 de 288 líderes no
> CSV, o resto é `'Leader'`) fez a primeira tentativa de fix não mudar
> nada, até ser pego também. Corrigido: extrai o código real do alvo e
> confere contra o card_type verdadeiro (case-insensitive) de
> `cards_rows.csv`.
>
> **Números corretos, mesmos 268 turnos**: 132 casos de ataque a MAIS
> que o histórico, **44 casos de ataque a MENOS** (não zero — a
> "ausência de regressão" reportada antes estava errada), 87 com a
> mesma contagem. O sinal ainda existe (mais casos de "mais" que de
> "menos", concentrado em logs pre-29/07: 124 "mais" pre-fix vs 8
> pós-fix), mas é MUITO mais fraco e ruidoso do que o "92%,
> confirmação limpa" reportado antes. Os 44 casos de "ataca menos" tem
> uma concentração real (18/44) em partidas do líder Charlotte Katakuri
> — não investigado a fundo ainda, fica registrado como pista pra
> próxima sessão. Lição: SEMPRE conferir a lógica de detecção contra
> um caso conhecido manualmente antes de reportar um percentual
> agregado como achado — não confiar só no output agregado bater com a
> expectativa.
