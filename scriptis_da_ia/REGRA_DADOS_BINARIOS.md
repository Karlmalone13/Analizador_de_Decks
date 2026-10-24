# Regra do projeto: linhas e colunas são MATRIZ; todo dado que puder ser binário é BINÁRIO

**Leitura obrigatória antes de qualquer commit.** Impressa pelo hook `pre-commit`,
mesmo tratamento de `REGRA_SEM_DUPLICACAO.md` e `REGRA_O_CRITERIO_EMERGE.md`.

## A regra, na palavra do usuário (24/10/2026, bloco 989)

> *"quero que coloque na regra do projeto que colunas e linha tem de ser matriz,
> e que todos os dados que puderem ser binarios devem ser binarios"*

Duas obrigações:

1. **Dado tabular (linhas × colunas) é MATRIZ.** Nada de percorrer linha a linha
   montando um `dict`/lista por linha quando a operação pode ser feita na matriz
   inteira (máscara, índice, operação vetorizada do numpy). Laço Python sobre
   milhões de linhas é o último recurso, só para o que não tem forma vetorial — e
   mesmo assim sobre colunas já decodificadas, nunca sobre texto.
2. **Todo dado que puder ser binário é BINÁRIO.** Números não ficam guardados
   como texto (`json`, `csv`) para serem decodificados toda vez. Texto só onde
   binário não é possível (ver "Onde texto continua" abaixo).

## Por que (medido, não opinião)

O dia em que a regra nasceu, cada troca de texto/linha por binário/matriz foi
medida com o resultado IDÊNTICO:

| O quê | Antes | Depois |
|---|---|---|
| Alternativas no treino (`alt_bin.py`, 986-987) | 228 s (texto, linha a linha) | ~7 s (binário + matriz) |
| Trajetórias no treino (`traj_bin.py`, 988) | 57 s | 16 s |
| Contagem das fatias do corpus (983) | 378 s | 1 s |
| Escolhidas no treino (`corpus_bin` colunas, 989) | ~280 s | medido no bloco 989 |

Do treino inteiro (627 s no perfil), só 95 s eram a rede aprendendo — o resto era
decodificar texto e percorrer linhas.

## Como cumprir sem mudar resultado (obrigatório)

Trocar o formato **não pode** mudar o que o modelo aprende nem o que o bot
decide. Toda conversão segue o método do bloco 986-989:

1. **AS-IS antes**: medir o tempo atual (perfil), e só converter o que pesa.
2. **Mesmo tipo numérico**: se o consumidor recebia `float64`, o binário guarda
   `float64` (ex.: a régua em `traj_bin`). `float32` só onde já era `float32`.
3. **Mesma ordem**: guardar a ordem original (`seq`) quando o consumidor sorteia
   ou depende da posição (o treino sorteia com semente fixa).
4. **Conferência que pode falhar**: comparar a saída nova com a antiga
   (`confere_*.py`): campo a campo, matriz a matriz e, no fim, o modelo treinado
   (diferença de previsão = 0,0).
5. **Derivado e regenerável**: o binário é derivado de uma fonte (fatias do git,
   índice), fica no `.gitignore` e se reconstrói sozinho quando a fonte muda
   (impressão digital do começo + trecho antes do offset, largura do vetor).
6. **Teste preso ao temporário**: teste que escreve dado nunca toca o caminho
   real (trava que aborta se algum caminho cair fora do diretório temporário —
   lição do bloco 984, que apagou o `q_escolhidas.jsonl` real).

## Onde texto continua (porque binário não é possível ou não é dado)

- **Documentação e registros humanos**: `HANDOFF.md`, `TODO.md`, regras, docs.
- **O que vem de fora em texto**: combat logs do simulador, decklists, textos
  das cartas — o arquivo original é guardado como veio; o que o motor/treino
  consome a partir dele deve ser binário quando for consumido repetidamente.
- **Transporte entre máquinas pelo git**: as fatias do corpus (`.jsonl.gz`)
  continuam texto comprimido por ora (o import/export e o round-trip byte a byte
  dependem disso); mudar exige redesenho próprio, com a mesma conferência.
- **Configuração pequena e índices editáveis** (`index.json`, `estado.json`):
  não é dado volumoso; ler é instantâneo.

## Inventário do que ainda é texto/linha e deveria seguir a regra

Atualizar esta lista quando um item for convertido.

- [ ] `q_escolhidas.jsonl` (4,6 GB) — hoje só alimenta o `q_bin`; pode sumir quando
      o `q_bin` passar a ser escrito direto pela derivação.
- [ ] Montagem de features na hora de decidir (`state_features`, `linha_q`) —
      listas Python carta a carta; deveria ser matriz por lote de candidatas
      (acelera o bot jogando, a árvore e os portões).
- [ ] Banco de cartas na abertura de cada processo (pandas/CSV) — binário
      pré-compilado.
- [ ] `selfplay_v2.jsonl` — já tem cache binário (`traj_bin`); o escritor ainda é texto.
- [x] Alternativas (`alt_bin.py`, 986/987)
- [x] Trajetórias (`traj_bin.py`, 988)
- [x] Metadados das escolhidas em colunas (`corpus_bin` `meta.rec`, 989)
