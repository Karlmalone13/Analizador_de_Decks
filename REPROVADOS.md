# REPROVADOS — o que já foi tentado e MEDIDO como sem ganho

> **Por que este arquivo existe** (27/08/2026): o registro de "já tentei
> isso e não funcionou" existia, mas espalhado em prosa por centenas de
> blocos do `HANDOFF.md`. Uma sessão nova não tem como descobrir que uma
> ideia já foi reprovada antes de gastar um dia refazendo — e isso já
> aconteceu (a mesma ideia de alargar shortlist foi medida **três** vezes).

> **REVISADO em 27/09/2026 (bloco 911), a pedido do usuario.** Sairam as
> entradas cuja premissa deixou de existir: ajustes da HEURISTICA (pesos da
> funcao de valor, piso de score, desempates, bonus de arquetipo e de
> alinhamento humano, pontuacao de ataque), itens do MONTE CARLO (removido no
> bloco 785) e da era em que a meta era SEMELHANCA com o humano (trocada em
> 10/09). Hoje quem decide e o Q, a heuristica nao escolhe jogada, e o ML
> aprende pela consequencia (bloco 910) -- aquelas medicoes nao dizem nada
> sobre o sistema atual. Tres entradas foram tiradas daqui por que a premissa
> MUDOU e elas podem funcionar agora -- estao em "VALE RE-TESTAR" no
> `TODO.md`. O texto antigo completo continua no git (versao do commit
> `f512f86`).

## Como usar

**Antes de propor ou implementar qualquer mecanismo desta lista, leia o
bloco citado.** Não é proibição eterna: é a exigência de saber o número
que já saiu e dizer o que mudou desde então.

**Como adicionar:** toda tentativa revertida por medição entra aqui, com
o número medido e o ponteiro pro bloco. Se não tem número, não foi medida
— e aí não é reprovação, é opinião.

**Como revisar:** quando uma premissa mudar (quem decide, o rotulo, a meta),
as entradas que dependiam dela saem ou vao pra "VALE RE-TESTAR" no TODO.

---

## Professor do bootstrap (`value_net_aluno`) com mais RESOLUCAO (bloco 909)

Diagnostico que motivou: nas decisoes recentes o professor da o MESMO valor
as duas melhores opcoes em 41,2% dos casos (gap < 0,01 em 61,9%); em 83%
desses empates os estados resultantes sao DIFERENTES -- o modelo (HistGB
profundidade 3, folha 60, lr 0,02, sub-ajustado) nao os separa.

| tentativa | resultado medido | bloco |
|---|---|---|
| Professor em REDE (MLP) no mesmo corpus/rotulo | AUC fora da amostra **0,764** x 0,803 (decora: 0,94 no treino). Mesmo resultado ja visto em 21/09 | 909 |
| Professor + dado recente (selfplay gens 4-11 rotulado igual) | AUC nos estados das gens 12-13: 0,8211 -> 0,8266; resolucao igual | 909 |
| **Professor menos regularizado (63 folhas, lr 0,05)** | AUC 0,8164 -> **0,8531**, empates "em degraus" 36,4% -> **0,8%** -- e o Q treinado com ele **PERDE 8x29** do Q treinado com o professor atual (600 partidas cada) | 909 |
| O mesmo V3 como avaliador de DECISAO (defesa/counter/alvo), campeao igual dos dois lados | **33x45 DESCARTA** | 909 |

**A licao**: prever melhor QUEM GANHA (AUC entre estados) nao e ordenar melhor
as OPCOES de uma decisao. Os desempates do professor fino sao, em boa parte,
ruido com cara de confianca, e o Q aprende o ruido com consistencia.

**Premissa que ja mudou em parte**: medido ANTES do rotulo pela consequencia
(bloco 910). Hoje a jogada escolhida aprende pela consequencia; o professor so
rotula as candidatas NAO escolhidas. Se retomar, medir nesse regime.

**Tambem medido**: a "concordancia top-1" no modo bootstrap NAO e qualidade --
a `escolhida` e o que o campeao da epoca jogou, com 17% de exploracao e pool
de adversarios antigos. Nao usar como alvo.

## Rotulo do Q vindo do professor `busca` que ESPIA (bloco 906)

| tentativa | resultado medido | bloco |
|---|---|---|
| **Misturar as linhas `modo=busca` (95.282, 19-21/09) no corpus do Q** | Mesma receita, duelo contra o campeao: prefixo + `busca` **24x39 DESCARTA**; prefixo + `bootstrap` **75x46 PROMOVE**. O ciclo 13 com tudo junto: 7x24 | 906 |
| Treinar o Q so com `busca` | **0x9** contra o corpus inteiro | 20/09 |
| Replay priorizado (PER) como causa da regressao do ciclo 13 | **Hipotese derrubada**: sem PER, o mesmo corpus perdeu 12x31 | 906 |

Causa provavel (bloco 888): a busca que gera o rotulo ve a mao REAL do
oponente -- alvo otimista (media 0,581 x 0,503) e inalcancavel pra quem so ve
o observavel. Para voltar: gerar `busca` com o professor CEGO e medir de novo.

## Velocidade de inferencia em CPU (21/09/2026)

Fatos de biblioteca, validos enquanto os modelos forem sklearn:

- **`scikit-learn-intelex`**: sem ganho no `MLPRegressor` (5,760s x 5,825s)
  -- nao tem kernel pra rede neural.
- **`batch_size` maior no `MLPRegressor`** (2048/4096): sem ganho de
  velocidade e qualidade PIOR (erro 0,0555 -> 0,0587/0,0598), sem convergir
  em `max_iter=60`.

---

## ERRO DE MEDICAO: "o bot nunca aceita counter nem blocker" era A REGUA (bloco 837)

`auditoria_efeitos.py` julgava a defesa por `chosen_action.accepted`, campo
que so existe em `optional`/`trigger`/`reaction`. Counter e blocker davam
**sempre zero**; o real era counter **39%** e blocker **52%** com opcao. A
prova estava no mesmo log (`[DEF] counter ... -> 4 cartas`). **Um resultado
REDONDO -- zero exato, duas sessoes seguidas -- e sintoma, nao conquista.**

## ERRO DE MEDICAO: portao sem PODER (bloco 756)

O portao antigo (media >= 55% em ~54 partidas) tinha **10,9%** de poder --
uma geracao 55% melhor seria descartada em 89% das vezes. Corrigido com
espelho pareado + SPRT (blocos 756/762, barra `p1=0,58` no 888). **Antes de
registrar um nulo como reprovacao, conferir o PODER do teste.**

## Erros de MEDICAO ja cometidos (a regua estava torta, nao o motor)

| erro | como apareceu | bloco |
|---|---|---|
| Correlacao usada pra projetar ganho | "`play` 29,3% com DON certo vs 21,3% errado" projetou ~8pp; o A/B deu **+1,8pp** -- turnos faceis de reconstruir sao turnos simples. **Nao projetar ganho de correlacao: rodar o A/B** | 690 |
| Estatistica condicionada ao FRACASSO | "45% dos erros ja tinham a carta certa no topo" ignorava os acertos da busca; a ablacao desmentiu. **Medir o COMPLEMENTO antes de concluir** | 699 -> 700 |
| Medir acerto de DON contra `don_cost`, que exclui o DON anexado | "~35%" falso; o real era 53% | 688 -> 690 |
| `--limit N` correlacionado com a variavel sob teste | os 70 primeiros jobs nao tinham RZ1 -- A/B byte-identico | 689 |
| Detectar ataque ao lider pela string `"Leader"` | o log nunca usa a palavra; escondeu 44 casos reais | auditoria 04/08 |
| Comparar contra QUALQUER candidato em QUALQUER decisao | inflou "93% quase-empate" | 676 |
| Rodar medicao com codigo editado no meio | workers com versao nova; resultado mistura duas versoes | 682, 692 |
| Rodar medicoes pesadas em PARALELO | lentidao atribuida a 3 causas erradas | 682 |
| Extrapolar tempo de um job pela METADE | "10,5s/partida" virou 15,9s. So medir lote terminado | 750 |
| Contar nucleos LOGICOS pra escolher workers | 2 fisicos / 4 logicos: 4 workers deram ganho zero | 750 |
| Parametro na assinatura != parametro aplicado | recebia e nunca repassava. Conferir o ponto de USO | 750 |
| Bissectar `smoke_fast` com a maquina carregada | a bissecao media ESTADO, nao codigo | 752 |
| Declarar hipotese descartada medindo cedo demais | maquina assentada, a hipotese estava certa | 752 |
| Calibrar com decks DIFERENTES entre si | forca de deck vaza pros coeficientes. Usar partidas-ESPELHO | 752 |
| Coeficiente de logistica com features colineares | o solver reparte o efeito arbitrariamente. Bootstrap de sinal | 752 |
| `_is_searcher` por substring | 0 de 50 cartas detectadas contra 12 pelo parser | 752 |
| Ler peso de feature RARA na escala crua | +20,1 cru, +0,076 padronizado. Porta de SUPORTE | 752 |
| Diagnosticar divergencia ao vivo x offline sem abrir o log bruto | o erro era AO VIVO (0 DON desvirado) | 893-895 |
| Chave de decisao sem a GERACAO na concordancia | ids de partida recomecam a cada ciclo: decisoes de partidas diferentes misturadas | 910 |
| Script de experimento com `ProcessPoolExecutor` sem `if __name__ == '__main__'` | workers re-importam o script; o duelo cai pra sequencial | 909 |
| Lancar o mesmo job DUAS vezes (`&` + background) | dois processos escreveram no mesmo corpus: 208 linhas corrompidas, gen 13 em dobro | 905 |

## Enquadramentos reprovados (nao sao mecanismos, sao raciocinios)

- **"Diversidade estrategica explica o gap restante"** -- proibido como
  resposta por decisao do usuario. Parte irredutivel tem que ser provada com
  medicao.
- **"O teto e X, entao a meta cabe em X"** -- corrigido pelo usuario em 27/08:
  *"O teto a gente pode escolher e criar mecanismos para que seja alcancavel"*.
- **"Consertar o lider X" como plano de trabalho** -- proibido pelo objetivo
  central. Lider parado e sintoma de mecanismo que nao generalizou.
- **"Medir mais ao redor" no lugar de construir o que foi pedido** -- o padrao
  que atrasou por semanas o ML aprender pela consequencia (bloco 910). Medir e
  controle de qualidade DEPOIS, nao condicao ANTES.
