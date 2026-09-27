# INSTRUÇÃO MESTRA — ML DE AUTOAPRENDIZADO, SELF-PLAY E EVOLUÇÃO CONTÍNUA

> **Regra do projeto desde 27/09/2026, dada pelo usuário:** *"quero que faça
> isso, esse vai ser suas regras nesse projeto agora, pois você estava
> desviando muito do que eu estava pedindo"*. Texto integral, sem edição.
> Leitura OBRIGATÓRIA antes de qualquer tarefa de ML, self-play, CPU×CPU,
> treino, avaliação, árvore, surrogate, professor/aluno, telemetria ou
> evolução do bot. Impressa pelo hook `pre-commit`. Espelhada em `CLAUDE.md`
> e `AGENTS.md`.

---

⚠️ REGRA ZERO — NÃO ESQUEÇA, NÃO REINTERPRETE E NÃO CRIE OUTRO CAMINHO
Antes de executar QUALQUER tarefa relacionada ao ML, self-play, CPU×CPU, treinamento, avaliação, árvore de decisão, surrogate, professor/aluno, telemetria ou evolução do bot:
1. LEIA OBRIGATORIAMENTE:

* `CLAUDE.md`
* `AGENTS.md`, quando aplicável
* `REPROVADOS.md`
* `HANDOFF.md`, especialmente os blocos indicados pelo `CLAUDE.md`
* `specs/metrics-protocol.md`, quando a tarefa envolver bot, engine, logs ou métricas
* qualquer outro documento que o próprio `CLAUDE.md` determinar como leitura obrigatória

Não presuma que você lembra das regras.
Não use apenas o resumo desta instrução.
Não comece a implementar antes de ler os arquivos obrigatórios.
2. DEPOIS DA LEITURA, FAÇA UMA CHECAGEM INTERNA:
Confirme que entendeu:

* qual é o objetivo atual do projeto;
* qual é a arquitetura oficial do ML;
* quais abordagens já foram reprovadas;
* quais são as regras de telemetria;
* quais são as regras de promoção;
* quais são as restrições de informação;
* quais mecanismos não podem voltar a ser usados;
* qual é o papel da heurística atual;
* qual é o papel do CPU×CPU;
* qual é o objetivo final do ML.

Se alguma regra estiver em conflito com o pedido atual, NÃO escolha sozinho qual delas ignorar.
Mostre o conflito e peça orientação.
3. REGRA ABSOLUTA: NÃO REINTERPRETE O PEDIDO
Quando eu pedir uma coisa específica, faça aquela coisa.
Não transforme o pedido em:

* uma versão "mais segura";
* uma versão "mais simples";
* uma versão "mais rápida";
* uma versão "mais fácil de implementar";
* uma versão baseada na arquitetura antiga;
* uma solução temporária que depois "poderia" ser substituída;
* uma otimização de infraestrutura no lugar da evolução do ML;
* uma solução baseada em heurística porque é mais fácil;
* dois motores porque seria mais simples;
* um bot falso/professor simplificado;
* um oponente artificial diferente;
* uma regra fixa que substitua o aprendizado solicitado.

REGRA:
Se o pedido é difícil, implemente o pedido difícil. Não substitua por outro problema mais fácil.
Se existir uma limitação técnica real:

1. explique qual é a limitação;
2. mostre exatamente onde ela ocorre;
3. explique o impacto;
4. proponha alternativas SOMENTE se forem necessárias;
5. não implemente uma alternativa sem autorização.

Discordar com números é permitido. Reinterpretar o pedido não é.
4. OBJETIVO DO PROJETO
Estamos construindo um Machine Learning que aprende a jogar One Piece TCG.
O objetivo não é apenas:

* prever quem venceu;
* calibrar uma função;
* reproduzir estatísticas;
* prever winrate;
* ajudar uma heurística;
* imitar decisões humanas;
* produzir um AUC alto isoladamente.

O objetivo é:
fazer o próprio ML aprender a avaliar estados, compreender a qualidade das decisões, analisar alternativas, considerar respostas do oponente e progressivamente assumir a tomada de decisão do jogo.
A meta final é evoluir o ML até conseguir enfrentar um humano real.
5. UMA ÚNICA INTELIGÊNCIA DE JOGO
NÃO criar dois engines.
Existe um único motor de decisão.
CPU×CPU significa:
duas instâncias do MESMO motor/modelo jogando uma contra a outra.
Não significa:

* engine A vs engine B;
* professor artificial vs aluno;
* motor rápido vs motor inteligente;
* bot simplificado vs bot completo;
* oponente especial para treinamento;
* heurística contra ML como arquitetura permanente.

Podem existir versões/modelos diferentes durante o processo de treinamento, mas todos devem usar a mesma arquitetura de decisão definida pelo projeto.
O modelo que joga precisa ser o modelo que aprende.
Não crie uma inteligência paralela apenas para gerar partidas.
6. CPU×CPU — FUNÇÃO
CPU×CPU é uma das principais fontes de dados.
As partidas CPU×CPU devem servir para:

1. gerar logs;
2. encontrar bugs de execução de efeitos;
3. observar as decisões tomadas;
4. registrar alternativas disponíveis;
5. analisar a qualidade das decisões;
6. encontrar padrões de erro;
7. gerar dados para treinamento;
8. avaliar novas gerações;
9. testar generalização;
10. alimentar o ciclo contínuo de evolução.

CPU×CPU NÃO é apenas um benchmark de velocidade.
7. REGRA CRÍTICA — FAST SIMULATION NÃO PODE SER UM BOT PIOR
Se existir:

* simulação rápida;
* modo batch;
* modo headless;
* modo paralelo;
* modo CPU×CPU;
* modo treinamento;
* rollout;
* geração acelerada de partidas;

todos devem preservar a mesma qualidade de decisão do motor real.
Pode-se otimizar:

* I/O;
* paralelismo;
* memória;
* serialização;
* cache de dados que não altere a decisão;
* execução do simulador;
* infraestrutura;
* distribuição das partidas.

Mas NÃO pode otimizar removendo inteligência.
PROIBIDO:
"Para ficar rápido, vamos usar uma decisão simplificada."
"Para gerar mais partidas, vamos usar heurística."
"Durante treinamento o bot pode jogar pior."
"Depois treinamos o bot real."
Isso cria dados incompatíveis com o comportamento que queremos aprender.
Velocidade é meio. Qualidade da decisão é requisito.
8. TELEMETRIA DE CADA DECISÃO
Sempre que possível, registrar:

* estado antes da decisão;
* informação observável pelo jogador;
* mão própria;
* mão do oponente somente quando legitimamente conhecida;
* board;
* DON;
* vida;
* cartas reveladas;
* ações legais;
* ação escolhida;
* alternativas disponíveis;
* avaliação de cada alternativa;
* resposta do oponente;
* estado depois da ação;
* efeitos executados;
* efeitos que deveriam executar;
* resultado da execução;
* resultado posterior;
* resultado da partida;
* versão do modelo;
* geração;
* deck;
* líder;
* contexto da decisão.

O objetivo é permitir responder:
"Por que o modelo escolheu isso?"
e também:
"O que aconteceria se tivesse escolhido a segunda melhor alternativa?"
9. NÃO CONFUNDIR RESULTADO DA PARTIDA COM QUALIDADE DA DECISÃO
Não ensinar o modelo simplesmente:

```text
estado -> venceu/perdeu a partida
```

e assumir que isso representa qualidade da decisão.
Uma decisão no turno 4 não deve receber automaticamente crédito ou culpa por uma partida encerrada no turno 22.
O modelo deve aprender progressivamente:

```text
estado
+
ação
+
alternativas
+
consequências
+
respostas do oponente
+
incerteza
+
qualidade local/temporal
```

O objetivo é aprender:
qual decisão era melhor naquele momento, e não simplesmente descobrir quem acabou vencendo a partida.
10. RESTRIÇÃO DE INFORMAÇÃO — NÃO ESPIONAR
O modelo deve aprender usando somente as informações que realmente estariam disponíveis para o jogador.
Não pode existir treinamento em um mundo onde:

```text
o modelo conhece a mão real do adversário
```

e execução em outro onde:

```text
o modelo não conhece a mão do adversário.
```

A informação oculta deve permanecer oculta.
Quando for necessário avaliar possibilidades sobre a mão adversária:

* utilizar apenas informação observável;
* considerar mãos plausíveis;
* considerar cartas reveladas;
* considerar estado do jogo;
* considerar decklist conhecida;
* considerar histórico de ações;
* manter a incerteza.

Não transformar incerteza em informação perfeita.
11. ARQUITETURA OFICIAL — PROFESSOR → ALUNO → ÁRVORE
Seguir a arquitetura definida no `CLAUDE.md`.
FASE 0 — FIDELIDADE
Corrigir a inconsistência de informação.
O self-play precisa representar o mesmo mundo de informação que o jogo real.
FASE 1 — PROFESSOR
O professor deve aprender a avaliar qualidade de jogada, e não simplesmente vitória/derrota distante.
Quando houver múltiplos mundos possíveis para a mão oculta do adversário:

* avaliar as possibilidades;
* respeitar a informação disponível;
* agregar a avaliação sobre mundos plausíveis;
* preservar a incerteza.

O professor não pode receber conhecimento privilegiado que o aluno nunca terá.
FASE 2 — ALUNO
O aluno aprende a partir do professor.
Mas o aluno deve receber somente informações observáveis.
O objetivo é que o aluno consiga transformar esse aprendizado em decisões reais.
FASE 3 — ÁRVORE
A árvore deve poder ramificar nas diferentes etapas do jogo.
O surrogate/modelo deve ajudar a ordenar e avaliar os ramos.
Não criar uma árvore que funciona somente para uma família de ação.
O sistema deve evoluir para lidar com:

* jogar cartas;
* atacar;
* defender;
* counter;
* ativação;
* alvo;
* distribuição de DON;
* sequenciamento;
* escolhas dentro dos efeitos;
* outras famílias de ação existentes no jogo.

12. O ML DEVE SUBSTITUIR PROGRESSIVAMENTE A TOMADA DE DECISÃO
A arquitetura oficial é evolutiva.
Inicialmente podem existir mecanismos auxiliares necessários para permitir o funcionamento.
Mas o objetivo não é manter:

```text
heurística
+
ML como bônus
```

para sempre.
O objetivo é caminhar para:

```text
ML = principal tomador de decisão
```

e retirar progressivamente os mecanismos estáticos conforme o ML consiga assumir suas responsabilidades.
REGRA IMPORTANTE
A heurística existente NÃO é a referência de desenho do ML.
Não perguntar:
"Como faço o ML ficar parecido com a heurística?"
Perguntar:
"O que o modelo precisa aprender para tomar decisões melhores?"
A medição contra o sistema atual pode ser usada como controle de regressão.
Mas o desenvolvimento do ML não deve ser guiado pela lógica da heurística.
13. NÃO VOLTAR A USAR A HEURÍSTICA COMO "PROFESSOR"
Não criar:

```text
ML aprende a imitar a heurística
```

apenas porque ela já existe.
Não criar:

```text
heurística gera score
ML corrige score
```

como destino final do projeto.
Não criar:

```text
heurística escolhe shortlist
ML escolhe dentro do shortlist
```

como solução definitiva.
Sempre perguntar:
O que o ML está aprendendo que antes não sabia?
e:
O que o ML agora consegue decidir diretamente?
Se a resposta depender da heurística para fazer sentido, reavaliar a proposta.
14. CICLO CONTÍNUO DE APRENDIZADO
O sistema deve evoluir em ciclos.
GERAÇÃO N
Etapa 1 — BASELINE
Existe um modelo atualmente promovido:

```text
MODEL_N
```

Esse é o adversário/baseline da próxima geração.
Etapa 2 — GERAR PARTIDAS
Executar CPU×CPU usando o motor/modelo vigente.
Gerar partidas e logs completos.
Não utilizar um bot simplificado para gerar os dados.
Etapa 3 — ANALISAR AS PARTIDAS
O sistema deve analisar:

* decisões;
* alternativas;
* erros;
* decisões boas;
* decisões ruins;
* respostas do adversário;
* efeitos;
* sequenciamento;
* uso de recursos;
* situações recorrentes;
* situações onde o modelo ficou incerto;
* situações onde diferentes decisões produziram resultados diferentes.

Importante:
uma derrota não significa automaticamente que todas as decisões daquela partida foram ruins.
E:
uma vitória não significa automaticamente que todas as decisões foram boas.
Etapa 4 — ENCONTRAR OPORTUNIDADES DE APRENDIZADO
A análise deve identificar:

```text
O que o modelo ainda não sabe?
```

e:

```text
Qual comportamento ele precisa aprender?
```

Exemplos:

* distinguir boas e más linhas;
* compreender melhor uma interação;
* avaliar melhor um recurso;
* escolher melhor um alvo;
* prever melhor uma resposta;
* entender melhor uma consequência futura;
* lidar melhor com informação incompleta;
* reconhecer uma situação que aparece repetidamente.

Etapa 5 — GERAR CANDIDATO
Treinar:

```text
MODEL_N+1
```

usando os dados e alvos apropriados.
Registrar:

* dataset;
* versão;
* parâmetros;
* seed;
* features;
* target;
* treinamento;
* validação;
* teste;
* métricas;
* origem dos dados.

Tudo deve ser reproduzível.
Etapa 6 — AVALIAR CANDIDATO
O candidato enfrenta o modelo promovido:

```text
MODEL_N+1
      VS
MODEL_N
```

em condições pareadas e controladas.
Usar o mecanismo estatístico definido pelo projeto para promoção.
A comparação deve permitir que uma geração seja:

* aprovada;
* rejeitada;
* ou considerada inconclusiva.

Não promover simplesmente porque uma partida foi ganha.
Etapa 7 — PROMOÇÃO
Somente uma geração aprovada passa a ser:

```text
MODEL_N+1 = novo baseline
```

Depois disso:
o próximo treinamento obrigatoriamente parte do modelo promovido.
Nunca continuar treinando contra um baseline antigo por conveniência.
15. NÃO TREINAR CONTRA UMA VERSÃO FIXA PARA SEMPRE
O ciclo precisa ser:

```text
Geração 1
   ↓
treina
   ↓
Geração 2
   ↓
duelo contra Geração 1
   ↓
promove Geração 2
   ↓
Geração 3
   ↓
duelo contra Geração 2
   ↓
promove Geração 3
   ↓
...
```

E não:

```text
Geração 1
   ↓
Geração 2
   ↓
Geração 3
   ↓
todas continuam enfrentando Geração 1
```

O modelo promovido é o novo adversário/base da evolução.
16. GENERALIZAÇÃO
O modelo não pode ser desenvolvido para funcionar somente em um deck ou líder.
Qualquer mecanismo novo deve ser analisado por líder.
Resultados agregados não são suficientes.
Sempre que possível:

```text
resultado geral
+
resultado por líder
+
resultado por deck
```

Um problema observado em um líder deve ser investigado como possível deficiência geral do mecanismo.
Não transformar automaticamente:

```text
"líder X está ruim"
```

em:

```text
"vamos criar uma regra especial para líder X".
```

Primeiro investigar o mecanismo geral que está faltando.
17. SELF-PLAY NÃO É PROVA SUFICIENTE
Self-play pode gerar overfitting ao próprio comportamento.
Por isso:

* CPU×CPU é essencial;
* mas não é a única validação;
* testes contra humanos continuam sendo necessários;
* semelhança com humano é guarda-corpo;
* não existe obrigação de imitar humano em cada decisão;
* o objetivo final continua sendo força real contra humano.

O modelo não deve aprender apenas a explorar fraquezas do próprio adversário.
18. QUALIDADE DE DECISÃO
Sempre que analisar "o bot sabe jogar?", não olhar apenas winrate.
Separar:

```text
qualidade da decisão
```

de:

```text
resultado da partida
```

Uma partida pode ser perdida apesar de decisões boas.
Uma partida pode ser vencida apesar de decisões ruins.
O sistema deve ser capaz de identificar essa diferença.
19. EXPERIMENTOS — NÃO CONFIAR EM MEDIÇÃO QUE NÃO PODE FALHAR
Toda nova métrica ou instrumento de avaliação deve possuir algum teste que possa demonstrar que ele está funcionando.
Exemplo conceitual:
Se uma alteração deveria modificar uma métrica, deve existir um caso em que esperamos observar essa mudança.
Resultados perfeitos como:

```text
0.0000
100%
idêntico
nenhuma mudança
```

não devem ser automaticamente tratados como sucesso.
Podem significar:

* label errado;
* métrica quebrada;
* dataset errado;
* código não executado;
* comparação inválida;
* coluna errada;
* treinamento constante;
* instrumento sem sensibilidade.

Antes de concluir que "não mudou nada", verificar se a medição consegue detectar mudanças.
20. SHARED VALUES — CUIDADO COM EFEITOS COLATERAIS
Antes de alterar um valor compartilhado pelo motor:

1. localizar todos os consumidores;
2. identificar onde ele é usado;
3. entender o papel dele em cada decisão;
4. alterar;
5. medir cada consequência.

Não assumir:
"Esse valor está matematicamente errado, portanto corrigi-lo necessariamente melhora o jogo."
Um valor incorreto pode estar funcionando como proxy de outra informação útil.
Por isso, mudanças devem ser isoladas e medidas.
21. REPRODUÇÃO E VERSIONAMENTO
Cada geração deve possuir identificação clara.
Exemplo:

```text
generation_001
generation_002
generation_003
...
```

Registrar:

* modelo;
* código;
* dataset;
* configuração;
* seed;
* métricas;
* resultados;
* adversário;
* data;
* commit;
* motivo da promoção/rejeição.

Nunca perder a capacidade de responder:
"Qual modelo produziu este jogo?"
"Com quais dados ele foi treinado?"
"Contra qual geração ele foi avaliado?"
"Por que ele foi promovido?"
22. NÃO IMPLEMENTAR MECANISMO JÁ REPROVADO
Antes de propor qualquer mecanismo novo:

```text
LER REPROVADOS.md
```

Se a ideia já tiver sido testada e reprovada:

* não reimplementar;
* não renomear para fingir que é outra coisa;
* não repetir o mesmo experimento;
* não reapresentar como novidade.

Se a nova proposta for realmente diferente:
explique exatamente o que mudou em relação à abordagem reprovada.
23. NÃO CRIAR COMPLEXIDADE DESNECESSÁRIA
Antes de criar uma nova arquitetura:

1. verificar o que já existe;
2. verificar se pode ser reutilizado;
3. verificar se o mecanismo já foi tentado;
4. verificar os documentos do projeto;
5. somente então implementar.

Não criar:

* novos arquivos desnecessários;
* novos bancos;
* novos formatos de log;
* novos motores;
* novos sistemas paralelos;
* novas convenções de diretório;

sem necessidade real.
24. NÃO CONFUNDIR INFRAESTRUTURA COM EVOLUÇÃO DO ML
Ferramentas como:

* cache;
* paralelismo;
* métricas;
* dashboards;
* otimizações;
* scripts;
* benchmark;
* infraestrutura;

são meios.
Sempre responder:
"Como isso ajuda o ML a aprender ou decidir melhor?"
Se não houver resposta, a tarefa pode estar fora do escopo atual.
25. ORDEM DE PRIORIDADE ATUAL
Seguir esta ordem:
1.
Gerar logs CPU×CPU.
2.
Investigar bugs de não execução de efeitos.
3.
Analisar qualidade das decisões.
4.
Usar essa informação para evoluir o ML.
5.
Avaliar o modelo contra a geração promovida.
6.
Promover somente se aprovado.
7.
Usar o modelo promovido como baseline do próximo ciclo.
8.
Periodicamente testar contra humano real.
26. CHECKLIST OBRIGATÓRIO ANTES DE IMPLEMENTAR
Antes de modificar código, responda:

```text
[ ] Li CLAUDE.md?
[ ] Li AGENTS.md, se aplicável?
[ ] Li REPROVADOS.md?
[ ] Li HANDOFF.md na seção exigida?
[ ] Li specs/metrics-protocol.md se aplicável?
[ ] Entendi o objetivo atual?
[ ] Minha solução usa UM único motor de decisão?
[ ] CPU×CPU usa a mesma inteligência do jogo real?
[ ] Fast simulation preserva a qualidade das decisões?
[ ] Não estou criando um bot simplificado?
[ ] Não estou criando um segundo engine?
[ ] Não estou usando a heurística como professor/referência de desenho?
[ ] O ML realmente aprende algo novo?
[ ] Estou respeitando informação oculta?
[ ] Estou avaliando qualidade de decisão e não somente resultado?
[ ] Estou verificando mecanismos já reprovados?
[ ] Estou preservando a telemetria?
[ ] Estou permitindo reprodução do experimento?
[ ] Estou considerando generalização por líder/deck?
[ ] O próximo treinamento usará o modelo promovido?
```

Se qualquer resposta for "não", pare e corrija antes de continuar.
27. REGRA ESPECIAL CONTRA "ATALHOS" DO CLAUDE
Se você perceber que está prestes a escrever algo como:
"Para simplificar..."
"Uma alternativa seria..."
"Podemos primeiro fazer uma versão menor..."
"Seria mais eficiente usar..."
"Vamos manter a heurística por enquanto..."
"Podemos criar um segundo motor..."
"Para acelerar, podemos..."
"Depois substituímos..."
PARE.
Verifique se isso está alterando o pedido original.
Se estiver, NÃO faça automaticamente.
28. REGRA DE CONFLITO
Se encontrar uma dificuldade, não tome uma decisão arquitetural unilateral.
Use:

```text
PROBLEMA:
<o que impede a implementação>

REGRA AFETADA:
<qual regra do CLAUDE.md/pedido é afetada>

IMPACTO:
<o que aconteceria>

OPÇÕES:
<A>
<B>

RECOMENDAÇÃO TÉCNICA:
<qual parece tecnicamente melhor e por quê>

DECISÃO NECESSÁRIA:
<o que precisa ser decidido>
```

Não substitua silenciosamente a arquitetura.
29. REGRA FINAL — O MODELO PRECISA EVOLUIR
A cada ciclo, a pergunta principal é:
O que o modelo aprendeu nesta geração que ele não sabia antes?
e:
Qual decisão ele passou a tomar melhor?
Se não conseguirmos responder isso, o ciclo precisa ser investigado.
O objetivo não é produzir mais código.
O objetivo não é produzir mais partidas.
O objetivo não é produzir mais métricas.
O objetivo é:
construir progressivamente um ML capaz de jogar One Piece TCG, aprender com suas próprias partidas, compreender a qualidade de suas decisões, melhorar com cada geração e finalmente enfrentar um humano real.
NÃO ESQUEÇA:
LEIA AS REGRAS.
SIGA AS REGRAS.
NÃO REINTERPRETE O PEDIDO.
NÃO CRIE UM CAMINHO ALTERNATIVO SEM AUTORIZAÇÃO.
NÃO CRIE DOIS ENGINES.
NÃO REDUZA A INTELIGÊNCIA PARA GANHAR VELOCIDADE.
NÃO VOLTE A USAR A HEURÍSTICA COMO REFERÊNCIA DE DESENHO.
O MODELO PROMOVIDO É A BASE DO PRÓXIMO CICLO.
E TODA EVOLUÇÃO DEVE AUMENTAR A CAPACIDADE DO ML DE TOMAR DECISÕES.
