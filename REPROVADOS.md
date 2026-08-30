# REPROVADOS — o que já foi tentado e MEDIDO como sem ganho

> **Por que este arquivo existe** (27/08/2026): o registro de "já tentei
> isso e não funcionou" existia, mas espalhado em prosa por **710 blocos**
> do `HANDOFF.md` (2,2 MB). Uma sessão nova não tem como descobrir que uma
> ideia já foi reprovada antes de gastar um dia refazendo — e isso já
> aconteceu mais de uma vez (a mesma ideia de alargar shortlist foi
> medida **três** vezes em sessões diferentes).
>
> Foi discutido arquivar os blocos antigos do `HANDOFF.md` pra reduzir o
> tamanho, e a conclusão foi **NÃO**: o acesso real ao arquivo é `grep` +
> ler o topo, e os dois funcionam bem em 2,2 MB. O que faltava não era
> tamanho menor, era ÍNDICE. Este é o índice.

## Como usar

**Antes de propor ou implementar qualquer mecanismo desta lista, leia o
bloco citado.** Não é proibição eterna: é a exigência de saber o número
que já saiu e dizer o que mudou desde então. Repetir uma tentativa sem
citar o que é diferente desta vez é desperdício de sessão.

**Como adicionar:** toda tentativa revertida por medição entra aqui, com
o número medido e o ponteiro pro bloco. Uma linha. Se não tem número, não
foi medida — e aí não é reprovação, é opinião.

---

## Imitação do humano

| tentativa | resultado medido | bloco |
|---|---|---|
| Imitação por BÔNUS/desempate **sem estado** — 7 variantes | todas nulas ou negativas | 641-649, 663 |
| Desempate por "banda larga" | `play` 27,5% → 27,2%; `attach_don` −1,0pp | 676 |
| ↳ **defeito 2, achado só em 28/08**: `policy.py:98` tinha **one-hot de LÍDER** e o split era **por partida** | aquela validação **nunca poderia detectar falha de generalização para deck novo** | 702 |
| Imitação por **POLÍTICA aprendida, com estado** | ranker 28,3% / counter 27,3% / ambos 26,4% — **todas abaixo** do baseline 29,5% | 680-683 |
| ↳ mais features de composição de mão no modelo | AUC 0,848 → 0,851 (ruído); contagem 65,6% → 63,6% | 682 |
| `_HUMAN_PATTERN_MIN_SUPPORT` 2 → 3 | regrediu `play` e `attack-quem` | 615 |
| peso do alinhamento humano = 0.0 | `play` 21,4% → 19,9%; quase tudo piorou | ~628-636 |

> **O achado que mais importa desta seção** (bloco 683): a política
> aprendida ranqueia melhor **isolada** (AUC 0,851 vs 0,702) e **mesmo
> assim piora** quando ligada no laço de decisão. Causa medida:
> *distribution shift* — treina em estados do motor baseline e degrada no
> laço. **Isso descarta "faltava estado no sinal" como explicação das 7
> tentativas anteriores.** Se retomar: laço iterativo estilo DAgger. Mais
> features NÃO resolve — foi medido.

## Busca Monte Carlo (o estagio de simulacao)

| tentativa | resultado medido | bloco |
|---|---|---|
| **Remover a busca** (TOP_K=1 + SEARCH_MIN_CANDIDATES=1, decisao cai no score estatico) | **REGREDIU**: `play` 28,9% -> 26,2% (**-2,7pp**); 12 lideres pioraram x 4 melhoraram; piores OP02-093 e OP11-040 -36,4pp | 700 |

> **A busca Monte Carlo e LIQUIDO POSITIVO.** Nao remover, nao gatilhar
> "pra confiar mais no estatico". Medido de verdade, com ablacao.
>
> **O ERRO DE LEITURA que levou ate aqui (bloco 699 -> 700), pra ninguem
> repetir:** o diagnostico media, entre as decisoes em que o motor JA
> TINHA ERRADO, quantas vezes o score estatico ja tinha a carta do humano
> em 1o lugar -> 45%. Numero real, **mas CONDICIONADO AO FRACASSO**. As
> decisoes em que a busca derruba o estatico e ACERTA ficaram inteiramente
> fora da amostra -- e a ablacao mostrou que sao mais numerosas.
>
> **Regra que fica:** ao apresentar estatistica condicionada a um
> subconjunto (so os fracassos, so os turnos com X), medir o COMPLEMENTO
> antes de concluir. Mesma familia do erro de correlacao do bloco 690.
> `activate` (+0,5pp) e `don` (+2,5pp) ate melhoraram sem a busca -- mas
> `play`, a metrica oficial, e `seq` cairam.

## Limiar de parada global (`ACTION_SCORE_FLOOR`) -- 2a reprovacao

| tentativa | resultado medido | bloco |
|---|---|---|
| `ACTION_SCORE_FLOOR` 0 -> 20 -> 50, contra o agregado oficial | **+0,0pp** nas duas; `seq` 36,4 -> 36,4/36,5 | 734 |

> **Por que nao funciona** (medido, nao suposto): as ULTIMAS acoes do
> turno -- as marginais que um piso cortaria -- tem **mediana de score
> 119,5**, e so **26,4%** ficam abaixo de 50. **O excesso de acoes do
> motor nao e composto de acoes marginais: sao acoes que ele valoriza
> ALTO.** Nenhum limiar de score alcanca isso sem cortar tambem o que ele
> acerta.
>
> Fingerprint confirmou que os knobs entraram (hashes distintos) -- o
> resultado plano e real.
>
> **2a reprovacao independente** do mesmo mecanismo (a 1a: bloco 695, em
> `play`, onde o erro de contagem e simetrico). Nao retomar.

## Contagem (quantas cartas jogar por turno)

| tentativa | resultado medido | bloco |
|---|---|---|
| Atacar a contagem por **limiar global de parada** (`ACTION_SCORE_FLOOR`) | **descartado pela propria medicao, antes de implementar**: o erro e SIMETRICO — 22,4% joga a mais, 25,2% a menos. Um numero global sobe um e desce o outro; liquido ~zero | 695 |

> **O que a medicao ensinou** (bloco 695, 987 turnos): media por turno
> motor 1,18 vs humano 1,23 — praticamente identicas. O motor **nao** e
> sistematicamente guloso nem timido. Contagem NAO e problema de
> calibracao: e o mesmo problema de julgamento visto de outro angulo, e
> nao merece entrada propria na fila de trabalho.
>
> O que continua valendo do diagnostico: quando a contagem esta certa, o
> `play` sobe de 28,9% pra **55,1%**. A contagem e mesmo o gargalo
> aritmetico — so nao se resolve por limiar.

### Termo do BLOCKER PROPRIO na funcao de valor (bloco 741)

| tentativa | resultado medido | bloco |
|---|---|---|
| `blocker_proprio` = `len(p.blockers_active())`, pesos 0 / 150 | `attack` 1,98 -> **1,94** (humano 1,66) -- 12% do gap, com peso implausivel; acerto exato de contagem **28,5% -> 26,8%** | 741 |

> A LACUNA E REAL: `_evaluate_state_v2` representa `opp_blocker` e nao
> representa os MEUS blockers, entao atacar com o ultimo blocker custa
> zero na avaliacao. **Mas preencher a lacuna nao reduz a contagem de
> ataque.** A hipotese "o motor ataca demais porque nao valoriza segurar
> blocker" esta REFUTADA por medicao.
>
> Fica em peso 0.0, inerte e documentado (mesmo tratamento de
> `human_sequence_alignment`). Se alguem retomar: a causa do +0,32 de
> ataque por turno continua NAO identificada.

## Ordem das jogadas (sequenciamento)

| tentativa | resultado medido | bloco |
|---|---|---|
| `KIND_SCALE_ATTACH_DON` 0,5 -> 0,8 e -> 1,0 (reduzir a prioridade de anexar DON) | **PLANO**: `play` 28,9% -> 28,9% (+0,1pp); `activate` 28,0% -> 27,9%; `don` 18,7% -> 18,3%; 18 de 20 lideres sem mexer. **0,8 e 1,0 deram resultado IDENTICO** | 696 |

> **Por que falhou, e o que isso ensina** (bloco 696): o gap de
> sequenciamento e REAL e grande (o motor abre o turno com `attach_don`
> em 27,3% dos turnos contra 8,2% do humano, bloco 691). Mas
> `KIND_SCORE_SCALE` e um multiplicador **GLOBAL por tipo de acao**, e o
> padrao humano e **POSICIONAL** -- ele anexa DON *por ultimo no turno*,
> nao "com peso menor sempre". **Um peso global nao consegue expressar
> 'faca isto mais tarde'.**
>
> Consequencia pra quem retomar: nao adianta varrer mais valores deste
> knob (0,8 e 1,0 ja deram resultado identico -- ele so mexe em decisoes
> na margem de entrar no shortlist). Atacar sequenciamento exige um
> mecanismo POSICIONAL/de fase (ex: o score de `attach_don` depender de
> ainda haver ataques por fazer no turno), que e mudanca de
> comportamento, nao parametro.
>
> **Nota de metodo:** a previsao ("ganho pequeno e positivo") foi
> registrada ANTES de rodar e estava ERRADA. O fingerprint da config
> provou que os 3 subprocessos rodaram com valores distintos
> (`bf21a9e8fbc5` / `c9d4a5eb2a05` / `4a54f4ccfd1b`), entao o resultado
> plano e real e nao falha de encanamento -- foi o 1o uso do mecanismo do
> bloco 692 e ele pagou na estreia.

### Desempate POSICIONAL com banda estatistica (bloco 738) -- TETO DE +1,6pp

| tentativa | resultado medido | bloco |
|---|---|---|
| `attach_don` categoria 1 com custo de oportunidade em vez de custo fixo | **ZERO**: diagnostico antes/depois saiu IDENTICO byte a byte | 738 |
| Banda de indiferenca estatistica no desempate (`TIEBREAK_BANDA_Z`), regua de DON do bloco 651 | LCS 47,8% -> 48,7% (Z=1,0) -> **49,4%** (Z=2,0) | 738 |
| Mesma banda, regua trocada pra DESTRUICAO de opcao (quantas candidatas empatadas a acao inviabiliza) | LCS **49,4%** -- identico a regua de DON | 738 |

> **O teto deste caminho e +1,6pp** (47,8% -> 49,4%), medido em 5
> configuracoes: epsilon fixo, banda Z=1,0, banda Z=2,0, regua de DON e
> regua de destruicao. **Nao re-medir sem mudar o mecanismo.**
>
> **O que o mecanismo REALMENTE era.** Os desempates dos blocos 651/663
> estavam certos na direcao, mas presos atras de `TIEBREAK_EPS = 1e-9`:
> media de Monte Carlo nunca empata nessa casa, entao eles quase nunca
> disparavam e o motor decidia a ordem do turno por RUIDO DE AMOSTRAGEM.
> A banda troca o epsilon fixo pelo erro-padrao da diferenca pareada que
> a busca ja calcula pro criterio de parada -- quando a busca nao
> consegue separar duas candidatas, ela passa a DECLARAR indiferenca em
> vez de fingir preferencia. Isso funcionou: `play` como 1a acao do
> turno foi de 36,5% pra 49,5% (humano 55,8%), +13pp.
>
> **Por que mesmo assim empacou.** O desvio dominante do sequenciamento
> e `attach_don` como 1a acao do turno: **28% do motor contra 7,8% do
> humano**. Ele NAO se moveu em nenhuma das 5 configuracoes. Isso prova
> que **abrir o turno anexando DON nao e fenomeno de empate** -- a busca
> prefere aquilo com valor simulado folgado. Nenhum desempate alcanca
> isso, por construcao: desempate so age onde a busca ja e indiferente.
> O alvo restante e a FUNCAO DE VALOR, nao a ordenacao.
>
> **Nota de metodo:** as duas previsoes foram registradas ANTES de rodar
> e as duas acertaram 2 de 4. Na 2a, a explicacao do overshoot de
> `attack` (1a acao desabou pra 11,2% contra 20,5% do humano) estava
> ERRADA: culpei a regra de destruicao, mas `attack` perde no desempate
> SECUNDARIO de DON, onde vale 0 e quase tudo vale mais. Corrigir a
> regua principal nao recuperou nada (10,8%).
>
> **O que SOBREVIVEU e vale por si** (nao e reprovacao): a regua de
> destruicao conserta `attack -> activate`, de **3,1x pra 1,9x** o
> humano, consistente em Z=1,0 e Z=2,0. E a besteira que o usuario
> reportou ao vivo -- "o bot ativar o stage depois de atacar com o
> lider, nao faz sentido": atacar resta a fonte, e fonte restada nao
> ativa mais. Ficou ATIVA no default. O que ficou desligado
> (`TIEBREAK_BANDA_Z=0`) e so a banda.

## Ranqueador aprendido (fase 2 do plano do bloco 702)

| tentativa | resultado medido | bloco |
|---|---|---|
| Ranqueador sobre TODAS as candidatas | **51,1% dos rotulos positivos** -> argmax nao discrimina; validacao 20,3% (baseline 21,3%) e treino 20,8% (baseline 30,7%) | 704 |
| Ranqueador so sobre `play`, com limiar | treino 38,5%, mas **validacao 19,3% com limiar escolhido honestamente** (no treino) -- ABAIXO do baseline 21,3% | 704 |

> **O PORTAO da fase 2 FECHOU**: ~20-24% contra teto de **96,6%**, e isso
> **offline, onde o *distribution shift* nem entrou em jogo**. Logo o
> shift **nao e a causa principal** -- o que economizou a fase 3 (DAgger)
> inteira.
>
> **Erro de metodo cometido aqui, registrado**: os "+2,4pp" da validacao
> vieram de escolher o limiar testando 7 valores NA PROPRIA VALIDACAO.
> Selecao no conjunto de validacao infla o numero. Com o limiar escolhido
> no treino, o modelo fica ABAIXO do baseline.
>
> Pista pra retomada: o rotulo disponivel e de CONJUNTO ("esta carta esta
> entre as que o humano jogou no turno"), nao de decisao. O oraculo chega
> a 96,6% porque enxerga o conjunto inteiro; um modelo que decide UMA
> acao por vez, nao. Tratar como selecao de CONJUNTO nao foi tentado.

## Selecao de conjunto aprendida (fase 2b)

| tentativa | resultado medido | bloco |
|---|---|---|
| Selecao de CONJUNTO do turno por modelo, avaliada em **1 split** de 9 lideres | +4,8pp -- **RETRATADO** | 705 -> 706 |
| A mesma, sob **GroupKFold por lider (30 lideres)** | **-0,2pp** na melhor config; -1,8pp na config original; 6 lideres melhoram x 8 pioram | 706 |
| Regularizar pra fechar o overfit | fecha o TREINO (85,5% -> 47,9%) **sem mover a validacao** (~28%, colada no baseline) | 706 |

> **O que ficou de positivo**: a formulacao de CONJUNTO esta certa -- levou
> o ajuste de TREINO de 38,5% (por decisao) a 86,7% com o mesmo dado. O
> modelo separa quando conhece os lideres; **nao transfere pra deck novo**
> com 797 turnos / 30 lideres.
>
> **Gargalo atual: VOLUME de dado humano**, nao formulacao nem *shift*.
> Self-play da volume mas NAO da rotulo humano.
>
> **Regra de metodo que fica**: afirmacao sobre generalizacao exige **CV
> agrupada por lider**. Split unico nao serve -- os +4,8pp vieram de um
> split onde 138 de 210 turnos eram de UM lider.

## Otimizacao dos pesos da funcao de valor

| tentativa | resultado medido | bloco |
|---|---|---|
| Busca CONJUNTA nos 17 pesos, **objetivo unico (`play`)** | holdout: `play` **+1,9pp** mas `don_alvo` **-8,0pp**; no treino +8,2pp/-6,4pp | 713 |
| Reportar o A/B do corpus inteiro como ganho | **+8,5pp era IN-SAMPLE** (vetor buscado nos mesmos logs que a regua mede) | 712 -> 713 |

> **A alavanca FUNCIONA** -- girar os pesos move a metrica de forma
> medivel, reprodutivel e confirmada FORA da amostra. O problema e o
> objetivo unico: ela **compra `play` vendendo `don_alvo`**.
>
> **O padrao que importa**: o GANHO transfere ~1/4 (+8,2 -> +1,9pp); a
> REGRESSAO transfere INTEIRA e piora fora da amostra (-6,4 -> -8,0pp).
> Ao otimizar uma metrica so, esperar que o preco apareca em outra e
> generalize melhor que o ganho.
>
> Nao repetir com objetivo unico. O caminho e multi-objetivo -- e exige
> rotular as outras categorias no banco de termos.

## Otimizacao MULTI-OBJETIVO dos pesos (bloco 715)

| tentativa | resultado medido | bloco |
|---|---|---|
| `objetivo = play - 3.0*max(0, don_base - don)` | holdout: `play` **-0,8pp**, `don` **-2,9pp** -- contem o estrago (era -11,2pp) mas **nada sobe** | 715 |
| penalidade 6.0 | holdout: `play` -1,2pp, `don` -3,7pp | 715 |
| O "+1,9pp honesto" do bloco 713 | **RETRATADO**: a mesma busca de objetivo unico da **-2,7pp** com 3000 iteracoes em vez de 4000 | 713 -> 715 |

> **VEREDITO: girar os 17 pesos NAO entrega ganho confiavel em `play`.**
> O ganho varia de +1,9pp a -2,7pp entre buscas quase iguais (ruido de
> onde a busca pousa); a PERDA em `don_alvo` e consistente nas duas
> medicoes independentes (-8,0pp regua real, -11,2pp offline).
> **A perda transfere, o ganho nao.**
>
> A alavanca EXISTE e e controlavel -- isso ficou construido (termos
> decomponiveis, `OPTCG_EVAL_WEIGHTS`, fingerprint com hash dos pesos).
> O que nao existe e ganho estavel nela.
>
> **Implicacao**: o proximo suspeito sao os TERMOS (quais existem), nao
> os PESOS (quanto valem). Bate com o bloco 707 (curva satura ->
> representacao) por caminho independente.

## Criterio de aceite por AUC (bloco 718)

| tentativa | resultado medido | bloco |
|---|---|---|
| Aceitar termo novo por **ganho de AUC** | ranking **INVERTIDO** vs `play`: `counter_perdido` +0,065 de AUC e **-2,5pp** de `play`; os 3 aprovados por AUC derrubaram o holdout de 23,9% pra **20,7%** | 718 |
| Ajustar os pesos por maxima verossimilhanca (logistica) | holdout 23,9% (14 termos) e 20,7% (17) contra **29,1% dos pesos de PRODUCAO feitos a mao** | 716, 718 |

> **AUC mede ordenacao par a par; `play` mede o CONJUNTO do turno.** Sao
> objetivos diferentes e neste projeto chegam a se INVERTER. Mesmo padrao
> do bloco 683 (AUC 0,851 com metrica real pior).
>
> **Regra: so `play` medido no HOLDOUT aceita ou reprova um termo.** AUC
> serve no maximo pra gerar candidatos.
>
> **E o holdout offline superestima ~4x** (bloco 718: +2,6pp offline ->
> +0,6pp na regua real). Nenhuma decisao de publicar sem a regua.

## Termos de INTERACAO carta-a-carta (bloco 720)

| tentativa | resultado medido | bloco |
|---|---|---|
| 10 termos usando o BOARD CONCRETO (supera o maior blocker / morre de graca / gap pra maior ameaca / ativos dele) | **0/2 confirmam no holdout**: -1,8pp e -0,8pp; os outros 8 com coeficiente 0 (nao mudam decisao) | 720 |

> **Dado verificado antes de concluir**: 6949 cartas de board, 89% com
> poder real, distribuicao coerente. Nao e bug de captura.
>
> A hipotese do bloco 719 ("a lacuna e o motor nao ver as cartas na
> mesa") **NAO se confirmou** -- a informacao passou a existir e nao
> ajudou. O board concreto no `context` fica como observabilidade util,
> mas nao e a resposta.

## Vetor de pesos otimizado (`eval_weights_holdout.json`) -- REPROVADO no painel

| tentativa | resultado medido | bloco |
|---|---|---|
| Publicar o vetor otimizado, apoiado em **+11,5pp de winrate no Imu** | **o painel derruba**: Enel **-25,0pp** (36,7% -> 11,7%), unico efeito com IC nao-sobreposto; as 3 "melhoras" (Imu/Ace/Nami) tem IC sobreposto = ruido | 723 -> 725 |

> **A licao vale mais que o vetor**: medir UM lider (Imu) deu +11,5pp e
> escondia um colapso de 25pp em outro arquetipo. **Nao e preciosismo de
> processo -- custa conclusao errada.**
>
> Causa aparente: o vetor derruba `DON/ataque` em todos os arquetipos, e
> **ramp (Enel) e justamente o plano que DEPENDE de acumular e gastar
> DON**. Politica boa pra 3 arquetipos, pessima pra 1.
>
> O painel so pegou isso porque virou DEFAULT no bloco 724, apos o usuario
> cobrar pela 2a vez (a 1a foi 15/08). **Na 1a rodada depois da inversao
> ja apareceu a regressao.**

## Arquetipo: multiplicadores e plano de jogo (blocos 736-737)

| tentativa | resultado medido | bloco |
|---|---|---|
| Corrigir o classificador de arquetipo (a classe agressiva era INALCANCAVEL: 0 de 39 decks reais) | **-0,0pp**; e nos 11 decks com o rotulo INVERTIDO, **5 de 7 nao mudam NADA** (n=174, n=65 entre eles) | 735-736 |
| Remover o arquetipo por completo (ablacao neutra) | **-0,2pp** -- nao prejudica nem ajuda | 736 |
| **Plano de jogo por arquetipo** na cascata de prioridade | **-0,0pp**, apesar de mudar **6,5% das decisoes de modo** | 737 |

> **O defeito era real**: a classe `aggressive` exigia
> `avg_cost<=2.5 AND pct_cheap>=0.55` e a distribuicao real vai de 3,28 a
> 4,70 -- matematicamente inalcancavel. `n_rush`/`n_blockers` eram
> calculados e nunca usados. Consertado, **default desligado**.
>
> **Mas nao e o gargalo.** O plano de jogo MUDA decisao (1 em 15) e a
> semelhanca com o humano fica igual: **as decisoes trocadas nao eram
> melhores nem piores, eram diferentes**. Prioridade escolhe a FAMILIA de
> jogada; o erro esta na escolha ESPECIFICA dentro dela.
>
> Nao retomar por este caminho. O alvo sao as categorias de escolha
> especifica: alvo do efeito (16,4%), cartas de counter (18,5%), DON
> (23,5%).

## Busca / shortlist

| tentativa | resultado medido | bloco |
|---|---|---|
| Alargar o shortlist da busca | **3 medições independentes, todas regrediram** | 593, 594, 677 |
| `SEARCH_MIN_PLAY_CANDIDATES` 1 → 3 | `play` 27,5% → 26,8% | 677 |
| Bancar DON ocioso no líder sem ataque (categoria 4) | 90,1% → 86,5% | 593, 594 |

## Ataque

| tentativa | resultado medido | bloco |
|---|---|---|
| `ATTACK_LEADER_BASE_SCORE` 400 → 320 | misto, e a métrica-alvo (attack-alvo) **piorou** −1,9pp | 625 |
| Descontar `score_attack_target` por risco de counter em ataque empatado ao líder | attack-alvo 83,6% → 77,6%; alvo-efeito 54,3% → 39,5%; e piorou a própria métrica que devia ajudar | 612 |
| Hipótese "líderes com poder condicional erram mais o alvo" | **não se sustenta** — o viés é igual ou maior em líderes sem essa habilidade | 624 |

## Fidelidade de estado / régua

| tentativa | resultado medido | bloco |
|---|---|---|
| Estimar DON por `10 - len(don_deck)` | erro 5,16 vs 1,37 do método em uso | 688 |
| Corrigir DON anexado (zona 9 do RZ1) | acerto exato 53% → 82%, **mas só +1,8pp em `play`** | 690 |

> **A lição de método mais cara do projeto** (bloco 690): a correlação
> "`play` 29,3% com DON certo vs 21,3% com DON errado" foi usada pra
> projetar ~8pp de ganho. O experimento controlado deu **+1,8pp**. Turnos
> com DON fácil de reconstruir são turnos SIMPLES, onde bater com o humano
> já é mais fácil por outros motivos — a correlação media o confundidor.
> **Neste projeto, não projetar ganho a partir de correlação. Rodar o A/B
> e olhar o número.**

## Erros de MEDIÇÃO já cometidos (a régua estava torta, não o motor)

Estes não são mecanismos reprovados — são casos em que a **conclusão** foi
errada porque a medição estava. Valem tanto quanto os outros:

| erro | como apareceu | bloco |
|---|---|---|
| `OPTCG_EVAL_WEIGHTS` com JSON de UMA chave pra varrer um peso so | **SUBSTITUI `eval_weights.json`, nao faz merge** -- descarta os 17 pesos de producao e cai nos defaults hardcoded, que DIFEREM (`counter_hand` 6.0 x 9.0, `don_field` 4.0 x 6.0). 4 rodadas invalidas. Pior: conferir isso comparando o JSON com `EVAL_WEIGHTS` depois do import e CIRCULAR. Gere o JSON a partir de `eval_weights.json`. Ha aviso em stderr desde o bloco 741 | 741 |
| Medir acerto de DON contra `don_cost`, que **exclui** o DON anexado | "RZ1 ≈ estimador, ambos ~35%" — falso; o número real era 53% | 688 → retificado no 690 |
| `--limit N` correlacionado com a variável sob teste | os 70 primeiros jobs são os logs mais antigos e **nenhum tem RZ1** — A/B deu resultado byte-idêntico | 689 |
| Detectar ataque ao líder pela string `"Leader"` no alvo | o log nunca usa essa palavra — inflou "motor ataca mais" pra quase todo caso e escondeu 44 casos reais de "ataca menos" | auditoria 04/08 |
| Comparar contra QUALQUER candidato em QUALQUER decisão | incluía decisões onde `play` já tinha vencido (gap trivialmente 0) — inflou "93% quase-empate" | 676 |
| Rodar medição com código editado no meio | workers sobem com versão nova; resultado mistura duas versões | 682, 692 |
| Rodar medições pesadas em PARALELO | 8 processos em 4 núcleos — atribuí a lentidão a 3 causas erradas antes de achar a real | 682 |

## Enquadramentos reprovados (não são mecanismos, são raciocínios)

- **"Diversidade estratégica explica o gap restante"** — proibido como
  resposta por decisão explícita do usuário. Se uma sessão concluir que
  parte do gap é irredutível, tem que **provar com medição**, não alegar.
- **"O teto é X, então a meta cabe em X"** — corrigido pelo usuário em
  27/08: *"O teto a gente pode escolher e criar mecanismos para que seja
  alcançável e não simplesmente impor um limite"*. Os 52,7% de contagem
  não são teto — são o motor jogando o número errado de cartas. As
  limitações da régua são atalhos que nós escrevemos (a ordem real das
  compras, por exemplo, **já está no banco**). Ver bloco 691.
- **"Consertar o líder X" como plano de trabalho** — proibido pelo
  objetivo central do projeto. Um líder parado é sintoma de que um
  mecanismo não generalizou, não item de backlog. Ver `CLAUDE.md`.
