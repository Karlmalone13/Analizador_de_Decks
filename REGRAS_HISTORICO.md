# REGRAS_HISTORICO.md -- o que saiu do CLAUDE.md/AGENTS.md

> Criado em 18/09/2026 a pedido do usuario, porque o `CLAUDE.md` chegou a
> 18.310 palavras (~25k tokens) carregadas no inicio de TODA sessao.
>
> **Nada aqui foi apagado -- foi MOVIDO.** Cada item deixou uma lapide de
> uma linha no arquivo de origem, apontando pra ca. A lapide existe pra
> impedir que uma sessao futura 'restaure' por engano uma regra revogada,
> que era a unica funcao do texto longo que ficava la.
>
> Isto e ARQUIVO, nao regra vigente. O que vale esta no `CLAUDE.md`.


---

## CATALOGO DE METODOS PRA SUBSTITUIR O MONTE CARLO (trazidos pelo usuario, 12-13/09/2026)

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

> Registrado a pedido dele. **Nenhum foi implementado ainda** -- e catalogo,
> nao decisao. A coluna "aplica aqui" e avaliacao minha, e cada uma que virar
> trabalho precisa da premissa testada antes de construir.

### O que o motor tem HOJE

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

**Monte Carlo PLANO** -- verificado no codigo (bloco 781): sem arvore, sem
UCB/UCT. Cada candidata recebe simulacoes independentes e o orcamento e
DIVIDIDO entre elas. Custa ~85% do tempo de partida (42,5% resposta do
oponente + 42,2% continuacao gulosa, bloco 765) e e por isso que "alargar o
shortlist" regrediu 3 vezes: **olhar mais custa olhar pior**.

### Bloco 1 -- alternativas de simulacao numerica

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

| metodo | o que e | aplica aqui? |
|---|---|---|
| **Quase-Monte Carlo (QMC)** | sequencias determinísticas de baixa discrepancia (Sobol, Halton, Faure); converge O(1/N) contra O(1/raiz(N)) | **NAO** -- e integracao CONTINUA. O nosso e combinatorio discreto ("qual carta, em quem, quanto DON"): nao ha funcao suave pra integrar |
| **Elementos Finitos / Diferencas Finitas** | malha fixa, derivadas viram diferencas discretas | **NAO** -- equacoes diferenciais, outro dominio |
| **Quadratura Gaussiana** | Gauss-Hermite/Legendre; integral exata pra funcao suave com poucos pontos | **NAO** -- mesmo motivo |
| **Surrogate Models / Emuladores** | Krigagem, Processos Gaussianos, redes neurais -- funcao rapida que IMITA o modelo pesado | **SIM -- e o caminho.** A rede de valor E isto; nome dado pelo proprio usuario |
| **Reducao de variancia** | Importance Sampling, Variaveis Antiteticas, Amostragem Estratificada | **EM PARTE** -- e ja usamos uma: sementes comuns no duelo pareado (bloco 756) |

### Bloco 2 -- motores de xadrez (mais rapidos que MCTS)

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

| metodo | o que e | aplica aqui? |
|---|---|---|
| **Minimax + Poda Alfa-Beta** | busca determinística que descarta ramos comprovadamente piores | **NAO como no xadrez**: a poda so e provadamente correta com INFORMACAO PERFEITA. Aqui a mao do oponente e oculta e ha aleatoriedade (compra, trigger) |
| **NNUE** | rede neural leve na CPU, **atualizada INCREMENTALMENTE** a cada lance; avaliador do Stockfish | **SIM, e e o mais proximo do que falta.** Hoje as 78 features sao recalculadas do zero a cada consulta |
| **PVS / NegaScout** | janela nula nos lances apos o primeiro | depende de alfa-beta -- mesma ressalva |
| **Bitboards** | tabuleiro como inteiros de 64 bits, operacoes binarias | nao se traduz: o estado aqui nao e um tabuleiro fixo de 64 casas |
| **Tabelas de transposicao** | hash de posicoes ja calculadas | **SIM** -- 58% das linhas convergem pro MESMO estado (bloco 756). Trabalho duplicado MEDIDO |

### Bloco 3 -- machine learning aplicado a jogo

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

| metodo | o que e | aplica aqui? |
|---|---|---|
| **DQN (Deep Q-Learning)** | o agente joga contra si mesmo e aprende o **valor Q** -- retorno futuro acumulado de CADA ACAO numa posicao. Arvore de busca pode ser acoplada no fim pra refinar | **SIM, e ja estamos com meio pe dentro**: o alvo do professor (bloco 783) e um **retorno de n passos**, a mesma familia matematica do Q. O que falta e ele DECIDIR por esse valor em vez de por busca |
| **Algoritmos geneticos** | populacoes de motores com variacoes de peso jogam entre si; vencedores combinam genes | otimiza PESO de regra estatica -- fora da direcao registrada (o objetivo nao e achar pesos melhores) |
| **NNUE** (detalhado) | avaliacao por rede no lugar de equacao escrita por humano, com atualizacao incremental | ver bloco 2 |

### A leitura que isto organiza

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

Tres coisas diferentes estao misturadas na palavra "substituir o Monte Carlo":

1. **Trocar o AVALIADOR** (o que da nota a posicao): Surrogate / NNUE / DQN.
2. **Trocar a BUSCA** (como se percorre as opcoes): Alfa-Beta, PVS, MCTS.
3. **Baratear o que ja existe**: transposicao, reducao de variancia, bitboards.

**O projeto esta no (1)** -- e onde o ML entra. (3) e velocidade, e cai na
regra de "melhoria ao redor do ML". (2) esbarra na informacao oculta.

> **CORRECAO REGISTRADA (usuario, 13/09)**: `_lethal_search` **nao** e um
> exemplo de "busca exaustiva que substitui o rollout", e citá-lo assim foi
> erro meu. Ele responde uma pergunta TERMINAL e especifica -- *"consigo
> vencer neste turno?"* -- e enumerar alocacoes de DON pra isso nao e avaliar
> posicao. Nao confundir as duas coisas.

### AMPLIACAO DO CATALOGO -- surrogate models, trazido pelo usuario (13/09/2026)

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

> Pedido explicito: *"te enviei aí, novamente uma lista de metodos para
> substituir o monte carlo, por favor registre isso e não esqueça, pq parece
> que vc esquece que estamos fazendo um ML e fica insistindo em coisas antigas
> que demandam muito tempo, e com medo de largar o osso e a gente evoluir"*.
>
> **Ele mandou DUAS vezes.** Da primeira (12/09) o catalogo entrou como tabela
> e a sessao seguiu otimizando o que ja existia. Esta e a segunda.

**A ideia central, na definicao dele**: em vez de rodar o modelo original
complexo dezenas de milhares de vezes, roda-se o modelo original POUCAS vezes
para coletar dados, treina-se um substituto rapido com esses dados, e as
previsoes saem em fracao de segundo.

Fontes que ele trouxe: COMSOL (`comsol.com/blogs/surrogate-models-for-faster-
simulations-and-apps` e `comsol.fr/technologies/surrogate-models`), IOP
(`iopscience.iop.org/article/10.1088/1681-7575/adb3ab`) e ETH Zurich
(`research-collection.ethz.ch`).

| metodo | como funciona | inferencia | dado de treino | aplica aqui? |
|---|---|---|---|---|
| **PCE** (Expansao de Caos Polinomial) | a resposta vira combinacao linear de polinomios ortogonais as distribuicoes das entradas | instantanea e **analitica** (media, variancia e indices de Sobol sem nova simulacao) | baixo a medio | **parcial** -- exige entradas com distribuicao estocastica bem definida; o nosso estado e combinatorio discreto, mas a ANALISE DE SENSIBILIDADE (quais features realmente movem o resultado) e diretamente util |
| **Processo Gaussiano / Krigagem (GPR)** | modelo bayesiano nao parametrico | muito rapida | **baixo** (centenas a poucos milhares de pontos) | **SIM, e o mais subestimado aqui** -- entrega a INCERTEZA da propria previsao junto do valor. E o que falta pro bot saber quando NAO confiar no proprio avaliador |
| **Redes Neurais (DNN)** | treinada sobre tabela gerada pela simulacao de alta fidelidade | instantanea | alto | **SIM** -- e a familia do que ja temos (o aluno e gradient boosting, primo proximo); o caminho se o corpus crescer muito |
| **RSM** (Superficie de Resposta) | polinomios de 1a/2a ordem por minimos quadrados | instantanea | muito baixo | como linha de base barata, pra saber se algo mais complexo esta ganhando de verdade |

**Alternativa que ele registrou separada** (nao trocar o modelo, e sim fazer a
amostragem render mais): **Hipercubo Latino (LHS)** e sequencias de baixa
discrepancia (**Quasi-Monte Carlo**) reduzem o numero de iteracoes em 10 a 100
vezes sem perder precisao.

> RESSALVA JA REGISTRADA, que continua valendo: QMC/Sobol foi avaliado em
> 12/09 como **nao aplicavel** ao rollout, porque aquilo e integracao de
> funcao CONTINUA e o nosso espaco e combinatorio discreto. **Mas a ressalva
> era sobre o Monte Carlo, que SAIU no bloco 785.** Onde LHS/QMC podem valer
> agora e na **escolha de quais posicoes simular pra treinar o substituto** --
> cobrir o espaco de estados de forma espalhada em vez de sortear, que e
> exatamente o problema de "gerar corpus" que o projeto tem.

### O QUE ISTO COBRA DA SESSAO -- a critica dele, que procede

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

> *"você ainda não deve ter substituido a heuristica, estando então com
> simulações caras e com peso fixo, ou algumas funções sendo executadas
> diversas vezes desnecessariamente, ou até mesmo funções mortas ou sem
> funcionalidade que consomem tempo."*

**Testado, e ele esta certo** (bloco 789, perfil de 2 partidas):

```
scores estaticos CALCULADOS      : 13.240
scores que chegam a UMA decisao  :    480
NUNCA decidem nada               :  96,4%

avaliar_carta (heuristica)       : 26,5% do tempo, 34.367 chamadas
_generate_and_score_actions      : 22,4% cumulativo
```

A pontuacao heuristica e recalculada em cada no da arvore e **jogada fora**,
porque quem decide e o modelo. Isso e o diagnostico dele, palavra por palavra:
simulacao cara com peso fixo, funcao executada muitas vezes sem necessidade.

**A regra pratica que sai disto**: quando o modelo decide, a heuristica nao
deve nem ser CALCULADA. Nao e so "o ML tem prioridade no score" -- e nao pagar
pelo caminho que nao vai ser usado. Se a sessao esta medindo tempo e o nome
`avaliar_carta` aparece no topo do perfil, a substituicao nao aconteceu de
verdade.

---

## A REDE DE VALOR E UM *SURROGATE MODEL* -- o nome certo, dado pelo usuario (12/09/2026)

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

> *"Acho que estamos indo para (Surrogate Models)"*.

**Esta certo, e nomear isso muda como o projeto raciocina.** Um surrogate
model (emulador) e uma funcao rapida treinada pra IMITAR um calculo pesado.
E exatamente o que a rede de valor faz: substitui o rollout Monte Carlo
(simular o resto do turno + o turno do oponente) por uma consulta de ~2ms.

Isso da a esta linha de trabalho uma literatura e um criterio proprios: a
pergunta deixa de ser *"o ML esta ajudando?"* e passa a ser **"o emulador
reproduz o que o simulador caro diria, com erro aceitavel?"**.

### O que o Monte Carlo de hoje E, exatamente

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

**Monte Carlo PLANO** -- verificado no codigo (bloco 781): nao ha arvore, nao
ha UCB/UCT. Cada candidata recebe simulacoes independentes e o orcamento e
DIVIDIDO entre elas (ha parada sequencial, que ajuda, mas nao realoca).

E dai vem a patologia medida: **ramo novo rouba precisao dos ramos antigos**.
Por isso "alargar o shortlist" regrediu em 3 medicoes independentes (blocos
593, 594, 677). **Nao e que olhar mais opcoes seja ruim -- e que olhar mais
custa olhar pior.** Com um surrogate essa penalidade some: cada ramo custa
~2ms fixos e nao tira nada de ninguem.

### O que se aplica e o que NAO se aplica (pesquisa trazida pelo usuario)

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

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

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

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

---

### A regra pratica

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

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

---

### O BURACO ESTRUTURAL que o usuario mandou RESOLVER (12/09/2026)

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

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
> **REVOGADO EM 13/09/2026 (bloco 792) -- esta era a SEGUNDA copia da regra
> circular.** Ela dizia: (1) fazer o modelo ficar bom, (2) **so entao** a busca
> pode encolher, (3) a heuristica sai **por partes, cada remocao passando pelo
> portao SPRT**.
>
> Mesmo defeito da copia revogada no bloco 791: condiciona tirar a heuristica a
> o modelo ficar bom primeiro -- e o modelo nao fica bom enquanto a heuristica
> decide por ele. A ordem correta e a INVERSA, e foi o usuario quem apontou:
> **a heuristica sai, e ai o ML tem como aprender**, porque so decidindo de
> verdade ele gera o dado do que decidiu.
>
> O que continua valendo desta secao: corpus grande, tratar sobre-ajuste e
> exploracao no auto-jogo sao trabalho de ML de verdade. O que cai e a ORDEM
> ("so entao", "por partes", "cada remocao passando pelo portao").
>
> **Isto nao autoriza adiar de novo.** O passo 1 E o trabalho de ML de
> verdade -- nao e pre-requisito burocratico pra ele. Se uma sessao esta
> mexendo em portao, cache, velocidade ou ferramenta de analise e NAO esta
> tornando o modelo melhor, ela esta fora da direcao.

---

## Placar de qualidade de decisão por líder — OBRIGATÓRIO antes de avaliar se o bot "sabe jogar" um deck

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

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

---

### Telemetria de decisão — OBRIGATÓRIO ler quando o log é de partida do bot

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

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

3. **`metrics/live_runs/efeitos_<ts>.txt`** — a AUDITORIA DE EFEITOS, o
   terceiro passo obrigatório (pedido do usuário, 17/09/2026: *"eles tem que
   rodar como obrigação, se não vamos perder dados"*). Já é gerada
   AUTOMATICAMENTE pelo auto-collect a cada `/outcome` (bloco 833) — rodar
   sozinha e **ser lida** são coisas diferentes, e é a leitura que é
   obrigatória.

   Responde o que os dois de cima NÃO respondem: **cada efeito disparado
   chegou ao fim?** Estágios OFERECIDO → ESCOLHIDO → ALVO → CONCLUÍDO, nas
   três famílias (`main`, `defense`, reativos por `actor_code`). Foi assim
   que se achou o Enel escolhendo `"Gain 0 Active Don"` em 100% dos menus
   (blocos 838/839) e o Streusen enterrando as 2 cartas que acabou de ver
   (bloco 840) — nenhum dos dois aparecia nos passos 1 e 2.

   **CONFIRA `efeitos_error` no `receipt_<ts>.json`.** A auditoria é
   best-effort de propósito (bancar o log é o trabalho crítico e não pode ser
   perdido junto), então se ela quebrar ela grava o erro e segue. Campo
   preenchido = **a auditoria NÃO rodou nessa partida**, e isso tem que ser
   dito, não passar em silêncio. `efeitos_nao_concluidos` traz a contagem.

   Filtrar uma carta: `python auditoria_efeitos.py --codigo <CODIGO>`.

   > **PENDENCIA OBRIGATORIA (17/09/2026)**: esta auditoria diz se o efeito
   > CONCLUIU e QUAL alvo foi escolhido, mas **nao consegue dizer se foi o
   > MELHOR alvo** -- falta `step_index`/`purpose` no `/choose_target` ligando a
   > decisao ao PASSO do efeito. Ver a secao "MEDIR A QUALIDADE DO ALVO" no
   > `TODO.md`. Nao dar o assunto por encerrado sem isto.


   > **O `server_stdout.log` é TRUNCADO a cada restart do server** (achado
   > 17/09). Os alertas `[AUTO-COLLECT][ATENCAO]`/`[COLETA-Q]` sobrevivem em
   > `BOT/engine_server/logs/session_<ts>.log`, um por sessão, e os relatórios
   > em `metrics/live_runs/` persistem sempre. Nenhum dado se perde — mas não
   > procure o histórico no `server_stdout.log`, que é só a sessão atual.

Leia os TRÊS inteiros, NESSA ORDEM, antes de reportar a partida como
investigada.

---

## Auditoria de derrotas reais contra humano — ferramenta permanente

> `[ARQUIVO]` -- versao LONGA do que ja foi resumido no `CLAUDE.md`. A regra
> vigente e a de la. Isto aqui nao obriga ninguem a nada.

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
