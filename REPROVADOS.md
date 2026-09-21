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

## CAUSA RAIZ: a funcao de valor e CEGA em 58% das decisoes (bloco 755)

**Leia isto antes de propor qualquer mecanismo que atue na funcao de
valor ou na escolha entre candidatas.** Explica, com uma causa unica,
por que tanta coisa deu nulo.

`_simulate_sequence_once` avalia o estado no FIM da linha simulada (o
resto do turno inteiro, `max_steps=8`), nao logo apos a acao escolhida.
Como as duas irmas costumam acabar fazendo as MESMAS acoes em ordem
diferente, a linha CONVERGE:

| estado POS-LINHA das duas irmas | pares (de 60) |
|---|---|
| **IDENTICO -- 0 de 32 features diferem** | **35 (58%)** |
| difere em 1-7 features | 12 (20%) |
| difere em 8+ features | 13 (22%) |

Em 58% das decisoes `_evaluate_state_v2` e o `value_net` recebem o
**mesmo vetor** para as duas opcoes -- nao avaliam mal, nao tem o que
avaliar. A decisao cai no desempate (`_tb`, alinhamento humano, DON).

**O que isso torna INUTIL de antemao** (nao repetir):
- Melhorar o MODELO de valor (mais features, mais dado, outro
  algoritmo) sem mudar o PONTO de avaliacao. O AUC 0,77 do bloco 753 ja
  provou que o modelo nao e o gargalo.
- Coletar mais pares contrafactuais: 58% nascem sem sinal aproveitavel.
  O lote de ~4,5h foi SUSPENSO por causa deste numero.


> **RETIFICACAO 09/09 (bloco 756) -- a leitura acima esta CERTA no numero
> e ERRADA na conclusao.** O 58% e real e reproduziu exato (35/60 na
> mesma seed). Mas o bloco 755 nao perguntou se a POSICAO tambem e a
> mesma quando o vetor converge -- e as 32 features sao so contagens e
> agregados, **sem nenhuma identidade de carta**, entao duas posicoes
> diferentes colapsariam no mesmo vetor com facilidade. Medido com
> impressao digital rica (codigos de carta na mao/campo/trash, DON
> anexado personagem a personagem, vida, deck): **65 de 65 pares
> convergidos sao a MESMA POSICAO**, em duas amostras independentes
> (seed 909: 30/30; seed 2001: 35/35). Ferramenta:
> `diagnostico_convergencia.py` + `value_net.fingerprint_estado()`.
>
> **Consequencia: "o modelo esta cego e precisa enxergar" e um
> ENQUADRAMENTO REPROVADO.** Onde ele esta cego nao ha o que ver -- a
> decisao e genuinamente indiferente, e fazer o modelo "distinguir" ali
> seria ensina-lo a preferir uma de duas coisas iguais.
>
> | saida proposta pelo bloco 755 | veredito | bloco |
> |---|---|---|
> | (1) avaliar logo apos a PRIMEIRA acao em vez do fim da linha | **fora de pauta** -- conserta o lugar errado; a convergencia nao e defeito de ponto de avaliacao, e indiferenca real | 756 |
> | (2) alimentar o modelo com a DESCRICAO da acao escolhida | **fora de pauta pelo mesmo motivo** -- daria ao modelo um sinal pra separar estados que sao identicos de fato | 756 |
>
> **E o dado de treino e pior do que o 755 reportou**: dos 16 pares
> "informativos" de `pares_cf_v2.jsonl`, **10 tem posicao identica e
> desfecho diferente** -- so pode ser o fluxo de RNG dessincronizado
> apos a decisao forcada. **62,5% dos rotulos informativos sao RUIDO.**
> A taxa real de par util e **~10%**, nao os 26,7% reportados. Isso
> explica de outro angulo a linha "a curva ACHATA apos ~4.000 estados":
> mais partidas do mesmo regime injetam mais ruido na mesma proporcao.

## REDE DE POLITICA pra PODAR o shortlist -- REPROVADA offline (bloco 772)

**Nao repetir sem citar estes numeros.** Diferente da reprovacao de politica
por IMITACAO DE HUMANO (blocos 680-683, secao acima), esta era por
DESTILACAO DE BUSCA -- o rotulo era "qual candidata a busca completa
escolheu", treinada em auto-jogo, pra PODAR e nao pra escolher. Desenho
correto, respeitando os 4 pontos que o registro anterior exigia. **E mesmo
assim nao paga.**

Medicao OFFLINE, 626 decisoes de teste em 4 lideres nunca vistos:

| top-N | POLITICA | score estatico (de graca) | sorteio |
|---|---|---|---|
| 2 | 71,6% | 71,1% | 52,1% |
| 3 | 82,9% | 81,6% | 71,0% |
| 4 | 92,2% | 90,4% | 84,8% |
| 5 | 98,4% | 96,3% | 93,4% |

**A politica ganha do score estatico por 0,5 a 2,1 pontos.** O score ja e
calculado de graca pelo motor e faz praticamente o mesmo trabalho -- um
modelo nao se justifica por essa margem.

**A CAUSA e estrutural, nao do modelo**: nao ha o que podar.

- media de **4,5 candidatas** por decisao (min 2, max 9)
- **31,9% das decisoes tem <=3 candidatas** -- podar nao faz nada nelas
- podar pra 4 economizaria ~15% do custo e perderia 9,6% das escolhas

**Podar serve pra arvore LARGA; a nossa e estreita.** Fator de ramificacao
de 4,5 nao sustenta o mecanismo.

**CORRECAO DE NUMERO que motivou a ideia**: o mapa AS-IS (bloco 765) dizia
"10,7 candidatas por decisao" -- eram 10,7 SIMULACOES, porque cada candidata
e simulada varias vezes (Monte Carlo). A oportunidade era 2,4x menor do que
parecia, e a ideia foi proposta em cima do numero errado.

**Falso achado descartado no caminho**: com amostra pequena (56 decisoes, 1
lider) o score estatico parecia PIOR que o sorteio (69,6% x 73,1%), o que
teria sido um achado e tanto. Com 626 decisoes ele bate o sorteio com folga
(71,1% x 52,1%). Era ruido -- e a ressalva de amostra pequena estava escrita
antes de medir.

**O que FICA de util**: `politica.py` (coleta + medicao offline) e o seam
`_pol_captura`. E o padrao de teste: **construir o baseline que pode matar a
propria ideia, e rodar offline antes de gastar duelo**. Custo total desta
reprovacao: ~30 minutos, contra ~3 horas dos experimentos anteriores.

## ERRO DE MEDICAO: "o bot nunca aceita counter nem blocker" era A REGUA (bloco 837)

**Reportado como o achado mais caro em aberto do projeto, em DOIS commits
(blocos 834 e 836), e era FALSO.**

`auditoria_efeitos.py` julgava todas as fases de defesa por
`chosen_action.accepted`. Esse campo **so e preenchido em
`optional`/`trigger`/`reaction`**. Em `counter` a resposta e `counter_ids`, em
`blocker` e `blocker_id` -- com `accepted` os dois davam **sempre zero**.

| | reportado | REAL |
|---|---|---|
| counter | 0 aceitos | **56 de 144 com opcao (39%)** |
| blocker | 0 aceitos | **11 de 21 com opcao (52%)** |

**A evidencia que desmentia estava no MESMO arquivo de log o tempo todo**: o
stdout do server imprime `[DEF] counter atk=8000 def=5000 -> 4 cartas` e
`[DEF] blocker ... -> <nome>`. Bastava ler os proprios prints do endpoint.

**O que enganou**: o numero batia com uma expectativa pre-existente. O
`CLAUDE.md` ja registrava que a defesa e heuristica fixa sem consulta ao
modelo, e que `quais cartas de counter` e uma das 3 piores categorias (18,5%).
"Zero" encaixou nessa historia e passou por confirmacao em vez de checagem --
inclusive por MIM, que tinha acabado de me queimar com o mesmo tipo de erro no
bloco 832 (o `delta zero` que dizia 18% quando era 45%).

**A licao, que ja era regra do projeto e foi furada de novo**: *"toda medicao
precisa de um CONTROLE que possa falhar"* (bloco 780) e *"conferir a logica de
deteccao contra um caso conhecido manualmente antes de reportar um percentual
agregado"* (retificacao de 04/08). Um resultado REDONDO -- zero exato, duas
sessoes seguidas -- e sintoma, nao conquista.

**O que SOBREVIVE da investigacao** (medido com a regua certa):
* `blocker`: **149 de 170 decisoes nao tinham blocker nenhum em campo** (88%).
  Isso e composicao de deck/tabuleiro, nao decisao.
* `trigger`: 11 aceitos de 51 (22%), com uma sessao em **0 de 16** -- essa
  ponta continua real e NAO investigada.

---

## ERRO DE MEDICAO: o portao de promocao tinha 10,9% de poder (bloco 756)

**Nao e uma tentativa reprovada -- e a regua que reprovava as
tentativas.** Entra aqui pelo mesmo motivo dos outros erros de medicao
ja registrados: o resultado nulo era da ferramenta, nao do mecanismo.

O portao do `treino_continuo.py` exigia **media >= 55% em ~54 partidas
decididas**. Para esse portao ter 80% de poder estatistico precisaria de
**~782 partidas**. Poder real: **10,9%** -- uma geracao genuinamente 55%
melhor seria DESCARTADA em 89% das vezes.

| geracao | estados | AUC fora | winrate | IC95 |
|---|---|---|---|---|
| 1 | 5.569 | 0,7612 | 48,2% | [35,1; 61,3] |
| 2 | 6.507 | 0,7645 | 49,1% | [36,1; 62,1] |
| 3 | 7.413 | 0,7682 | 53,1% | [39,1; 67,0] |
| agregado | | | 50,0% | [42,3; 57,7] |

**As 3 geracoes descartadas sao INCONCLUSIVAS, nao negativas** -- a
entrada "Laco de geracoes com portao (3 geracoes)" da tabela acima tem
que ser lida com esta ressalva. O modelo de fato melhora conforme joga
(AUC +0,69 ponto com corpus +33%); o teste e que nao conseguia ver.

**Corrigido (bloco 756)**: espelho pareado (mesma seed => mesmo par de
decks e mesmo embaralhamento, lados trocados; so conta quem vence dos
DOIS lados, par dividido = sem informacao) + portao por **limite
inferior do IC95 de Wilson** em vez da media, porque o pareamento cria
um risco novo de n decidido pequeno. Validado por teste A/A: motores
identicos dao 8 pares TODOS divididos e 0 decididos, como previsto.
**O ganho de PODER continua NAO MEDIDO** -- o A/A valida correcao, nao
poder.

**Licao pra sessoes futuras**: antes de registrar um resultado nulo como
reprovacao, conferir o PODER do teste que produziu esse nulo. Um portao
sem poder nao reprova mecanismo -- ele so nao mede.

## TETO ESTRUTURAL: 80% das decisoes entre irmas nao mudam o desfecho (bloco 754)

**Nao e uma tentativa reprovada -- e uma MEDICAO que limita familias
inteiras de tentativa.** Fica aqui porque e o primeiro lugar que uma
sessao nova consulta antes de propor mecanismo novo.

Contrafactual REAL (180 pares; para cada decisao, os dois ramos jogados
ate o fim com a mesma seed): **so 20,6% dos pares sao INFORMATIVOS** --
nos outros 80%, trocar a escolha da MESMA decisao da o MESMO vencedor.

| medicao | resultado | bloco |
|---|---|---|
| pares informativos (troca muda o vencedor) | **20,6%** | 754 |
| taxa de TROCA do valor aprendido (peso 200) | 100% das partidas, mediana a 12% do jogo | 754 |
| trocas que mudam o vencedor | 28% | 754 |
| separabilidade das distribuicoes gen0 x gen1-3 | AUC 0,52 | 754 |

**Como usar isto**: antes de propor um mecanismo que atue na ESCOLHA
entre candidatas de uma mesma decisao, lembre que ~80% dessas escolhas
sao indiferentes ao desfecho. Ganho ali e limitado por construcao -- o
que explica, em retrospecto, boa parte dos resultados nulos dos blocos
641-706 sem precisar de uma causa diferente pra cada um.

| tentativa | resultado medido | bloco |
|---|---|---|
| **SUBIR o peso** do valor aprendido (hipotese: termo inerte) | **REFUTADO antes de implementar**: `medir_taxa_troca.py` mostrou 100% das partidas divergindo, cedo. O termo nunca esteve inerte -- forca do sinal nunca foi o problema | 754 |
| Laco de geracoes com portao (3 geracoes) | 48,2% / 49,1% / 53,1% de winrate do desafiante, **3 descartes**. RESSALVA: nao foi iteracao -- nada foi promovido, entao as 3 jogaram com o MESMO campeao | 754 |
| Mais dado de auto-jogo do mesmo regime | curva de aprendizado **ACHATA** apos ~4.000 estados (0,7510 -> 0,7682, ganhos dentro do ruido de +-0,005) | 754 |

## Funcao de VALOR aprendida por AUTO-JOGO (bloco 753)

Familia DIFERENTE das reprovacoes de imitacao acima -- rotulo = quem
GANHOU a partida (nao "que carta o humano escolheu"), dado gerado pelo
proprio motor (nao os 171 logs finitos), sem *distribution shift* por
construcao. Valia a tentativa; **nao pagou**.

| tentativa | resultado medido | bloco |
|---|---|---|
| Valor aprendido somado a `_evaluate_state_v2`, `VALUE_NET_WEIGHT=200` | `play` 26,6% -> **26,5%**; `seq identica` 5,7 -> **4,7**; `LCS` 35,3 -> 35,1; `attach_don` 17,4 -> 16,8. Por lider: 9 sobem x 9 descem, sem direcao | 753 |
| O mesmo com `VALUE_NET_WEIGHT=50` (testar se 200 era alto demais) | `play` **26,4%** (pior que os dois); `LCS` 35,1 igual. **Nao e questao de peso** | 753 |

**O modelo em si e BOM** -- AUC fora da amostra **0,7071**, positivo em
5/5 folds, sob GroupKFold POR LIDER (lideres nunca vistos). Sanidade
confere (posicao ganha 0,90, perdida 0,04). Ou seja: **nao foi reprovado
por nao aprender.** Ordenar estado bem nao virou acerto na metrica.

**Duas hipoteses honestas, nenhuma testada ainda** (nao repetir a
tentativa sem atacar uma delas):
1. **Redundancia com a busca** -- o Monte Carlo com `_evaluate_state_v2`
   na folha talvez ja extraia esse sinal; somar os dois nao acrescenta.
2. **Alvo errado pra esta metrica** -- o modelo preve VITORIA, a metrica
   mede SEMELHANCA COM O HUMANO. As duas categorias que mais cairam sao
   de sequenciamento, e "quem ganha" e indiferente a ordem das jogadas
   dentro do turno, que e exatamente o que o LCS mede.

A infra fica no repo e util: `optcg_engine/value_net.py`,
`gerar_selfplay_dataset.py`, `treinar_value.py`, knob `VALUE_NET_WEIGHT`
(**default 0.0**, producao inalterada). Testar a hipotese 2 nao exige
comecar do zero -- exige trocar o ROTULO, nao o mecanismo.

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

## Lethal certificado -- conserto CERTO que PIOROU o jogo (bloco 779)

| tentativa | resultado medido | bloco |
|---|---|---|
| **Fazer a prova de lethal enxergar a mao OCULTA do oponente** (fix completo: executor + estimativa de counter) | **REPROVADO no portao SPRT: 9x15, winrate 37,5%**, 120 pares / 240 partidas, veredito DESCARTA | 779 |

**O defeito era REAL e continua real.** `opp_counter_chunks_for_lethal`
contava as cartas nao reveladas da mao do oponente como **zero counter**
(`_ = unknown_hand_size  # reservado para futura estimativa`), enquanto
**tres docstrings** afirmavam que a estimativa existia. Medido em 40
partidas: a prova assumia 460 de counter e o oponente gastava 2.416 (5,2x);
**94,5%** dos lethals que falhavam eram explicados por isso; a taxa de falha
caiu de **65,2% pra 35,1%** com o conserto.

**E mesmo assim o bot passou a GANHAR MENOS.**

### A licao, que e o que importa aqui

**`can_lethal_this_turn()` nao e consumida so pra "atacar pra ganhar".** Ela
alimenta **7 pontos** do motor -- entre eles `FIX_LETHAL_DON_ALLOCATION`
(19/07), que despeja TODO o DON no ataque quando o lethal esta certificado, e
que foi medido como BOM na epoca.

Com a prova honesta, as declaracoes de lethal cairam de **113 pra 57**. O
conserto nao desligou so os lethals falsos: **desligou pela metade um gatilho
de AGRESSIVIDADE que pagava na media**, mesmo quando a vitoria nao era
garantida de fato.

> E o caso de livro do `R, D |- G` que o CLAUDE.md ja registra: **falha de
> sistema sem falha de maquina**, agora ao contrario -- a premissa "a conta
> esta errada, logo consertar a conta melhora o jogo" e FALSA quando a conta
> errada esta sendo usada como PROXY de outra coisa.

**Antes de consertar um valor que varios comportamentos consomem, liste os
consumidores.** Consertar a fonte muda todos eles de uma vez, e o portao so
devolve o saldo -- nao diz qual consumidor quebrou.

### O que NAO esta reprovado

O fix tem duas metades independentes e o portao testou as duas JUNTAS:

1. **executar a linha certificada** -- `_lethal_search` ja devolvia quais
   atacantes e quanto DON, e o motor descartava isso, deixando o turno pro
   guloso (medido: 6 de 6 casos executaram diferente do certificado, com 0
   DON onde a prova pedia +3/+7). **Nao foi isolado ainda.**
2. **a prova enxergar a mao oculta** -- e esta que cortou as declaracoes pela
   metade, entao e a suspeita.

Nao jogar a metade 1 fora citando este numero: ele nao a mede sozinha.

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
| Extrapolar tempo de um job pela METADE | "10,5s/partida" virou **15,9s** com o lote inteiro — a duração das partidas varia demais pra média parcial valer. Só medir lote terminado | 750 |
| Contar núcleos LÓGICOS pra escolher workers | i3-8130U = 2 físicos / 4 lógicos. 4 workers deram ganho **ZERO** (17,6s x 16,5s sequencial). `cpu_count()//2` | 750 |
| Assumir que "cortar a busca" acelera sempre | `TOP_K=1` ficou **mais LENTO** que o padrão (24,8s x 16,5s): ainda roda a busca (1 candidata + PASS, 8 passos). O que acelera é NÃO chamar a busca (`search_top_k_override=0`: 1,3s) | 750 |
| Parâmetro na assinatura ≠ parâmetro aplicado | `run_single_match` recebia `mc_samples_override` e **nunca repassava** pro `OPTCGMatch` — o "modo rápido" não valeu nada até ser notado. Conferir o ponto de USO, não só a assinatura | 750 |
| Bissectar `smoke_fast` com a maquina carregada | 6 falhas de Monte Carlo apontaram um commit de FRONT como culpado. Reexecutar o commit "bom" depois falhou tambem: a bissecao media ESTADO, nao codigo. Causa real: `next-dev` de 12h com **4269 s de CPU e 2,7 GB** sufocando testes com `timeout=3.0` | 752 |
| Declarar hipotese descartada medindo cedo demais | matei o dev server, rodei o smoke NA HORA, deu 6 falhas de novo e eu escrevi "descarto". Minutos depois, maquina assentada: **SMOKE FAST OK**. A hipotese estava CERTA -- a medicao e que foi apressada | 752 |
| Calibrar peso de mao com decks DIFERENTES entre si | forca de deck vaza pros coeficientes: `t1` virou **-36,5** e `so_custo1` **+43,9** -- o modelo aprendeu "aggro ganha". Usar partidas-ESPELHO | 752 |
| Aceitar coeficiente de logistica sem testar estabilidade | com features colineares (`t1_t2 = t1 AND t2`, `sem_nada` ⊂ `sem_t1_t2`) o solver reparte o efeito arbitrariamente: `sem_nada` (mao sem jogada) saiu **+21** com AUC agregada boa. Bootstrap de sinal barrou | 752 |
| `_is_searcher` por substring `'look at the top'` | 3a vez que esta forma de bug aparece (bloco 751 no front, agora no `hand_scorer`): 0 de 50 cartas detectadas num deck real, contra 12 pelo parser | 752 |
| Codificar curva de mao com 7 indicadores aninhados | `t1_t2`, `curva_completa`, `sem_t1_t2`, `sem_nada` sao funcao deterministica de `t1/t2/t3` -- o efeito real se reparte e cada pedaco fica instavel (`curva_completa`: bruto 57,0% em 971 pares, REJEITADA a 74%), e o solver empurra sinal pra colunas erradas (`t1` -22,3 com bruto 49,0%). Uma ordinal 0-3 resolveu: AUC 0,6000 -> 0,6040 | 752 |
| Feature separada por POSICAO em analise pareada | numa partida so um lado vai primeiro, entao `c2k`/`c2k_indo_depois` ficam correlacionadas +0,67/-0,66 com a POSICAO e o coeficiente mede posicao, nao a carta. A assimetria que parecia insight (46,5% x 54,3%) era isso; a interacao `c2k x posicao` deu exatamente ZERO | 752 |
| Ler peso de feature RARA na escala crua | `c2k_excesso` saiu +20,1 com 100% de estabilidade, mas efeito bruto 51,7% IC95 [44,3; 59,0] em so 356 de 4.938 pares. Padronizado cai pra +0,076, abaixo da cobertura de curva. Coluna rara precisa de coeficiente grande pra mesma influencia -- usar porta de SUPORTE (400 custa 0,03pp; 600 custa 0,9pp) | 752 |

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

### Incerteza do modelo por REGRESSAO QUANTILICA (bloco 793, 13/09/2026)

**Medido: `incerteza` = 0,5000 EXATO em toda posicao. Inutil.**

Nasceu de um pedido legitimo do usuario -- ao me ver decidir a defesa
comparando duas estimativas PONTUAIS, ele perguntou *"porque vc esta fazendo
elas decidirem em probabilidade de vitoria se eu te dei uma lista de
metodos?"*, e a linha da lista que resolve isso e o Processo Gaussiano, que
entrega a incerteza junto da previsao. Como ele tambem perguntou *"porque
diversos modelos?"*, a tentativa foi por cabecas de QUANTIL (10% e 90%) no
MESMO bundle, pra nao criar uma segunda regua.

**Por que falhou, medido:**

```
q10 prediz 0,0000 constante   (1 valor distinto em 200 entradas)
q90 prediz 1,0000 constante   (1 valor distinto em 200 entradas)
alvo do corpus: 2 valores distintos (0 e 1), p10=0 p50=1 p90=1
```

Quantil de alvo BINARIO e sempre `[0, 1]` -- o intervalo 10-90% de uma
Bernoulli nao diz nada sobre o erro do modelo. Ligada, a medida tornava **toda**
decisao de defesa um empate (8 de 8 casos observados).

**O erro conceitual, registrado pra nao repetir:** confundi a **dispersao do
RESULTADO** com o **erro da ESTIMATIVA**. Quantil do rotulo responde a
primeira; a segunda exige incerteza de MODELO -- posterior de GPR, ou
ensemble/bootstrap sobre o proprio preditor.

**O que muda o quadro:** a ideia (decidir sabendo quando NAO se sabe) continua
valida e o problema que ela ataca e real -- a defesa hoje compara deltas da
ordem de 0,06 sem nenhuma nocao de erro. O que caiu foi o METODO. GPR passa a
ter fundamento **medido** aqui, nao escolha por catalogo -- com a ressalva ja
conhecida de que ele e O(n^3) e o corpus tem 73.821 estados (subconjunto, GP
esparso ou bootstrap sao os caminhos).

### Treinar o Q so com o rotulo 'busca', descartando 'bootstrap' (20/09/2026)

**Medido: perdeu 0x9 (11 empates) em duelo real contra o Q treinado no corpus
inteiro misturado.**

Hipotese: o corpus (818.763 linhas, `metrics/q_alvos.jsonl`) mistura dois
criterios de rotulo sem separar -- 'bootstrap' (o proprio modelo avaliando o
proprio lance, 88,4% do corpus) e 'busca' (professor independente por
simulacao, 11,6%, existe desde o bloco 877). O erro Q fora da amostra subiu 6
ciclos seguidos (0,0498->0,0581) enquanto a fracao 'busca' crescia -- parecia
contaminacao de alvo.

**Testado**: `treinar_q.py --modo busca` (95.282 linhas, 16 lideres) contra
`--modo todos` (818.763 linhas). Metrica estatica ja desconfiava: concordancia
com o professor caiu de 52,0% (+18,5pp acima do acaso) pra 23,0% (+4,9pp) --
mas a regra do projeto e nao confiar em metrica estatica sozinha ("concordancia
alta com forca nao comprovada nao e contradicao", bloco 817). Duelo real
(`treino_continuo.duelar_sprt`, espelho pareado, 20 pares) confirmou: **0
vitorias, 9 derrotas, 11 empates**, LLR cruzou o limite inferior na primeira
rodada.

**Causa real, nao a que a hipotese original apontava**: o corpus 'busca' ainda
e pequeno demais pra treinar sozinho (alguns lideres com so 35-104 decisoes de
validacao) -- misturar com 'bootstrap' hoje ajuda mais do que atrapalha, apesar
de nao ser o mesmo criterio. O que explica o erro Q subindo continua em
aberto -- NAO e mistura de rotulo.

**O que fica**: `treinar_q.py --modo {busca,bootstrap,todos}` (default
'todos') pra re-testar quando 'busca' tiver mais volume, sem precisar reescrever
o filtro. Campo `modo` por linha (bloco 877) ja permite a comparacao a
qualquer momento.

### Retreinar value_net_aluno.joblib como rede (MLP) em vez de arvores (21/09/2026)

**Medido: AUC fora da amostra CAIU de 0,8080 pra 0,7642 (-4,4pp), e o gap
treino-validacao SUBIU pra +0,1777 (mais overfit)** -- o oposto do que
aconteceu com o Q (`treinar_q.py`, bloco 800: rede errou 18% MENOS que
arvores).

Contexto: perfil de self-play (bloco 882) achou `value_net_aluno.joblib`
(arvores, `HistGradientBoostingRegressor`) como ~27% do tempo de uma
partida via `_ordena_pelo_modelo` -- maior custo isolado medido, e um
candidato natural pra ganhar o mesmo `_forward_rapido` (3,1x) que ja
acelerou o Q. Adicionado `--modelo rede` em `treinar_value.py` (mesma
arquitetura Pipeline(StandardScaler, MLPRegressor) de 64/32 neuronios) e
retreinado com os MESMOS parametros do arquivo em producao (`--dataset
metrics/corpus_professor.jsonl --features aluno --alvo professor --folds
5`, 73.821 estados, 16 lideres).

**Causa provavel da diferenca**: o corpus deste modelo (73.821 linhas) e
~11x MENOR que o do Q (818.763) -- a mesma rede leve que generalizou bem
com muito mais dado pode nao ter dado suficiente aqui, e/ou a tarefa
(estado -> win_prob continuo) e mais sensivel a hiperparametro do que
(estado+acao) -> valor. Nao investigado a fundo (fora do escopo do teste).

**Decisao**: NAO trocar `value_net_aluno.joblib` pra rede. O custo de tempo
(~27%) fica como esta -- aceitar velocidade mais baixa em troca de
qualidade de ordenacao e a escolha certa aqui, dado que o proprio projeto
ja pagou caro por trocar sem medir (blocos 680-683: AUC alto e MESMO ASSIM
piorou ligado no motor -- aqui o AUC nem foi alto, foi pior nos dois eixos).

**O que fica**: `--modelo rede` em `treinar_value.py` como capacidade
GENERICA (default continua 'arvores', nada muda pra quem ja chama o
script) -- reaproveitavel se o corpus deste modelo crescer o bastante pra
re-testar, ou pra outro dataset/feature-set futuro.

## Velocidade de inferencia em CPU: 3 caminhos genericos testados (21/09/2026)

Depois do batch de `_forward_rapido`/`_lote` (bloco 884, -47,7% medido),
o usuario colou 3 rodadas sucessivas de sugestoes genericas de IA sobre
"como acelerar scikit-learn em CPU". Duas delas foram testadas de verdade
(nao aceitas por plausibilidade) e reprovadas; a terceira levou a uma
mudanca real que ficou (ver bloco do HANDOFF do dia).

- **`scikit-learn-intelex`/`sklearnex.patch_sklearn()`**: instalado e
  medido em fit identico de `MLPRegressor` (50.000x101 sintetico).
  **Sem patch: 5,760s. Com patch: 5,825s** -- diferenca dentro do ruido.
  Confirmado tambem por identidade: `MLPRegressor.__module__` nao muda
  com o patch aplicado (`sklearn.neural_network._multilayer_perceptron`
  continua igual) -- a extensao nao tem kernel otimizado pra rede neural
  (o foco dela e SVM/KMeans/regressao linear/arvores). Pacote nao
  adicionado a `requirements.txt` -- nenhum modelo do projeto usa.

- **`batch_size` do `MLPRegressor` (200/'auto' -> 2048/4096)**: testado no
  corpus real do Q (818.763 linhas). **Sem ganho de velocidade** (auto:
  80,7s | 2048: 79,8s | 4096: 86,6s -- diferencas dentro do ruido) **e
  qualidade PIOR** (erro fora da amostra 0,0555 -> 0,0587 -> 0,0598).
  Alem disso, os dois batches maiores **nao convergiram** dentro de
  `max_iter=60` (bateram o teto ainda melhorando) -- o gap so tenderia a
  piorar sem tambem subir `max_iter`/ajustar `learning_rate`, nao testado.
  Nao aplicado.

- **Numero de arvores do `HistGradientBoostingRegressor`** (nao veio das
  sugestoes coladas, veio de medir de novo com `as_is.py` em vez de
  aceitar o diagnostico anterior): perfil aquecido mostrou
  `predictor.py:predict` (chamada interna do sklearn, uma por
  estagio/arvore) como **~46% do tempo de uma partida**. Truncar o
  ensemble ja treinado de `value_net_aluno.joblib` (equivalente
  matematicamente a treinar com `max_iter` menor, boosting e aditivo) deu
  a curva real: 300 arv AUC(corpus)=0,8437, 200 arv=0,8339 (-0,0098),
  150 arv=0,8270 (-0,0167) -- o `val_score` HELD-OUT do proprio treino
  nunca platoa ate 300 (`early_stopping` nunca disparou). **Nao e "sobrava
  arvore", e troca real de 1% de qualidade por velocidade** -- aceita
  pelo usuario (*"com os treinos a gente recupera esse AUC, e mais
  veloz a gente consegue ter mais amostras"*) e APLICADA: `max_iter=300
  -> 200` em `treinar_value.py`. Resultado real (retreino completo, nao a
  truncagem): AUC fora da amostra 0,8080 -> 0,8033 (-0,0047, menor que a
  estimativa), tempo de partida (`as_is.py`) -14,7% (0,34s -> 0,29s por
  partida), tempo em modelo caiu de 49,2% pra 42,3% do perfil.
