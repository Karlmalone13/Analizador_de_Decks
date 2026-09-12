# Onde está a alavanca do bot — medição de 11-12/09/2026

## A pergunta

O bot decide várias coisas por regra fixa. Vale a pena levar o ML até todas
elas? A medição responde: **um lado decide no aleatório, o outro pela regra.
Se o aleatório não perder, aquela decisão não importa.**

## Resultado

| família de decisão | empate | pares que decidiram | winrate no aleatório |
|---|---|---|---|
| **ação de topo** (jogar/atacar/ativar) | **72%** | — | — |
| descarte (qual carta jogar fora) | 81% | 15 de 80 | 40,0% |
| alvo (quem o efeito elimina) | 91% | 7 de 80 | 0,0% |
| **blocker (quem defende)** | **100%** | **0 de 80** | — |

**Quanto maior o empate, menos aquela decisão muda o resultado da partida.**

## O que isso quer dizer

**Decidir qual blocker defende não mudou o resultado de UMA partida sequer
em 80 pares.** Mesmo escolhendo no chute.

As três famílias testadas empatam entre 81% e 100%. A alavanca está
concentrada na **ação de topo** — jogar, atacar, ativar — que é exatamente
onde o ML já atua.

## Correção de uma tese anterior

Em 11/09 foi registrado que o problema do ML era de **ALCANCE**: ele
participa de 1 de 6 famílias de decisão, e isso seria o teto.

**A medição enfraquece isso.** As outras famílias realmente são regra fixa,
mas decidi-las bem quase não muda o resultado — levar o ML até elas não
pagaria o esforço.

## Onde investir, então

O ML já está na família que importa. E lá, o que mediu progresso foi
**quantidade de dado**:

| corpus | AUC | winrate do ML decidindo sozinho |
|---|---|---|
| 3.614 estados | 0,632 | 10,0% |
| 81.645 estados | 0,856 | 31,8% |

23x mais dado rendeu +22 pontos. É a única alavanca com ganho medido e
trajetória clara.

## Ressalva honesta

As amostras de pares discordantes são pequenas — 7 (alvo), 0 (blocker) e 15
(descarte). O resultado do blocker é forte (zero em 80 pares é muita
evidência de que não importa). Os outros dois são indicativos, não
definitivos.

Duas famílias ainda não foram medidas: **pagar custo** (o que sacrificar) e
**carta do search / reviver do trash**.
