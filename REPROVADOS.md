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
