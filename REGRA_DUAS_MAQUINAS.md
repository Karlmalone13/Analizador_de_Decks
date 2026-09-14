# Duas máquinas: quem treina, quem joga, e o que viaja como

**Leitura obrigatória ao INICIAR uma sessão em qualquer máquina** — antes de
rodar ciclo, treino, portão ou partida. Registrado a pedido do usuário
(14/09/2026): *"deixa essas regras registradas e o passo a passo, assim
evitamos de quebrar ou paralelismo quando iniciarmos novas sessões"*.

---

## A REGRA, em uma linha

> **Uma máquina TREINA por vez. Todas podem GERAR partidas e JOGAR.**

Gerar dado em paralelo é o que paga. Treinar em paralelo quebra o projeto — e
quebra **em silêncio**, que é o pior modo de falha.

---

## Por que treinar em duas quebra

**1. `q_net.joblib` é binário versionado sem estratégia de merge.**
Se as duas máquinas promoverem um campeão, o git não sabe fundir: quem der push
depois escolhe um e **descarta a geração do outro sem avisar**.

**2. O portão perde o significado.**
Ele compara campeão contra desafiante. Com campeões divergentes, as gerações
nunca se medem entre si — e o portão deixa de significar *"cada geração bate a
anterior"*, que é o ALVO DE TRABALHO registrado do projeto.

**3. Modelos não se fundem.**
Média de duas redes treinadas em separado não produz um terceiro modelo válido.
O corpus, sendo JSON por linha, concatena trivialmente — os modelos, não.

---

## O TOKEN de quem tem a vez

`scriptis_da_ia/metrics/ciclo_estado.json` **é versionado** e guarda o histórico
dos ciclos. A seed de cada ciclo sai de:

```python
seed = args.seed + n_ciclo * 101      # n_ciclo = len(historico) + 1
```

Com o ciclo 1 registrado, a máquina que der `pull` vira ciclo 2 → seed 9202, e
**não repete** as partidas do 9101. O estado do ciclo funciona como bastão sem
que ninguém tenha desenhado para isso.

**Isso só funciona com `pull` ANTES e `push` DEPOIS.** Rodar um ciclo sem puxar
é gerar exatamente as mesmas partidas que a outra máquina já gerou.

### Por que isso importa — custo já medido

Em 13/09 o ciclo se re-executou sozinho por um bug e entraram **9.865 alvos que
eram 100% repetição** de posições já existentes. Eco puro, o oposto do que o
corpus precisa. Só foi possível separar porque havia **uma origem só** e o corte
era o fim do arquivo. Com duas máquinas escrevendo, esse corte não existe — por
isso cada linha agora grava o campo `origem` (bloco 820).

---

## O que viaja COMO

| vai pelo **GIT** | vai **ZIPADO pela sessão** |
|---|---|
| código, motor, parser | `metrics/q_alvos.jsonl` (381 MB → 12,7 MB) |
| `HANDOFF.md`, `TODO.md` | `metrics/selfplay_v2.jsonl` |
| banco de logs (`logs/`) | `metrics/live_runs/`, `BOT/engine_server/logs/` |
| `q_net.joblib` (219 KB) | qualquer coisa grande **e** regenerável |
| `metrics/ciclo_estado.json` | |

**O critério não é tamanho**: git para o que precisa de MERGE e HISTÓRICO; zip
para o que cresce sempre e não tem semântica de merge.

O corpus fica fora porque **cresce a cada ciclo** e `.gz` não faz delta entre
versões — cada commit guardaria uma cópia inteira nova, ~13 MB permanentes por
ciclo. O código fica dentro porque **zip não funde**: quem descompactar por
último sobrescreve o trabalho do outro em silêncio.

---

## PASSO A PASSO — instalar numa máquina nova

1. `git clone https://github.com/Karlmalone13/Analizador_de_Decks.git`
2. `BOT\instalar.bat` (duplo-clique) — acha o jogo, instala o BepInEx, copia a
   DLL pronta de `BOT/dist/` (**sem precisar de .NET**), cria o venv e gera
   `iniciar_bot.bat`.
   Se não achar o jogo:
   `powershell -ExecutionPolicy Bypass -File BOT\instalar.ps1 -GameDir "<caminho>\Builds_Windows"`
3. Descompactar o corpus recebido em `scriptis_da_ia/metrics/q_alvos.jsonl`.
   Sem isso o treino começa do zero e perde as centenas de milhares de posições
   já acumuladas.

**Pré-requisitos**: Python 3.10+ com "Add to PATH" e o OPTCGSim instalado.
.NET **não** é necessário enquanto `BOT/dist/OPTCGBotPlugin.dll` estiver
atualizada.

---

## PASSO A PASSO — assumir a vez (virar a máquina treinadora)

1. **Na máquina que está saindo**: commitar, escrever o bloco no `HANDOFF.md` e
   dar push. Parar de treinar.
2. **Na que está entrando**: `git pull`.
3. Conferir, ANTES de rodar qualquer coisa:
   * o corpus tem o volume esperado e todas as linhas têm `origem`;
   * `ciclo_estado.json` indica o próximo ciclo (a seed sai dele);
   * `scikit-learn` na versão do `requirements.txt` e `q_net.joblib` abre sem
     erro.
4. Rodar o ciclo / jogar.
5. Commitar `ciclo_estado.json` (+ `q_net.joblib` **se promover**) +
   `HANDOFF.md`/`TODO.md`, e dar push.
6. **Na outra máquina**: `git pull` antes de encostar em qualquer coisa.

---

## O QUE DIZER a uma sessão nova na outra máquina

Ela não vê o histórico de nenhuma conversa — só o estado dos arquivos. Cole algo
como:

```
Leia o HANDOFF.md (blocos 819 a 822) e o TODO.md antes de mexer em qualquer coisa.

Contexto: esta é a SEGUNDA máquina do projeto. A outra gerou o corpus atual e
está parada. Eu trouxe metrics/q_alvos.jsonl por fora do git.

Quero treinar e jogar CPU x CPU aqui.

Antes de começar, confirme:
1. o corpus tem o volume esperado e todas as linhas têm o campo "origem"
2. qual a seed do próximo ciclo (ciclo_estado.json)
3. scikit-learn na versão do requirements.txt e q_net.joblib carrega sem erro

Depois disso, rode o ciclo e me diga os números.
```

Os três pontos não são burocracia: são exatamente onde isso quebra em silêncio —
corpus faltando, seed colidindo, ou versão de biblioteca que não abre o modelo.

---

## Armadilhas já pagas (não repetir)

* **`scikit-learn` não estava no `requirements.txt`** (achado 14/09). O import é
  lazy, então a falta só aparece quando alguém de fato treina. Fixado em
  `1.9.0` — e a versão importa porque `joblib` serializa **objetos** do sklearn,
  não um formato neutro: versão diferente entre máquinas quebra o `q_net.joblib`
  que viaja pelo git, com erro difícil de ligar à causa.
* **A DLL pré-compilada é ligada contra as DLLs do JOGO.** Se a outra máquina
  tiver outra versão do OPTCGSim — ou o jogo atualizar — ela para de funcionar e
  é preciso recompilar numa máquina com .NET e recommitar `BOT/dist/`. Sintoma:
  o bot não reage a nada.
* **`du -sh .git` NÃO é o tamanho do repositório.** O número que vale é
  `git count-objects -vH | grep size-pack`. Em 14/09 a pasta mostrava 1,1 GB
  com 28 MB de conteúdo real — eram objetos soltos, e `git gc --prune=now`
  resolveu em 31 segundos.
