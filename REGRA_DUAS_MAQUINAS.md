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
| código, motor, parser | `metrics/selfplay_v2.jsonl` |
| `HANDOFF.md`, `TODO.md` | `metrics/live_runs/`, `BOT/engine_server/logs/` |
| banco de logs (`logs/`) | qualquer coisa grande **e** regenerável |
| `q_net.joblib` (219 KB) | |
| `metrics/ciclo_estado.json` | |
| **o corpus, em fatias `.gz`** | |

**O critério não é tamanho**: git para o que precisa de MERGE e HISTÓRICO; zip
para o que cresce sempre e não tem semântica de merge.

### O CORPUS MUDOU DE LADO em 18/09/2026 — e por quê

Esta seção dizia, até 18/09:

> "O corpus fica fora porque **cresce a cada ciclo** e `.gz` não faz delta
> entre versões — cada commit guardaria uma cópia inteira nova, ~13 MB
> permanentes por ciclo."

**O argumento estava CERTO, e continua certo — para um zip ÚNICO regerado a
cada ciclo.** O que mudou foi o formato, não o argumento: o corpus virou **N
fatias**, cada uma escrita uma vez e **nunca reescrita**. Um ciclo novo
acrescenta só as suas próprias linhas, não uma cópia nova de tudo. O custo
permanente por ciclo cai de ~13 MB para **~1,3 MB**.

O que forçou a mudança foi o custo REAL pago em 18/09: o usuário chegou ao
trabalho sem conexão com a máquina de casa e **o zip não existia deste lado**.
Meio dia de trabalho parado por um arquivo que não atravessou.

Medido nesta máquina no mesmo dia:

```
amostra de 20.000 linhas : 13,1 MB -> 0,35 MB gz   (fator 37,4x)
corpus de 698.838 linhas : 465 MB  -> 12,9 MB gz
incremento de 1 ciclo    :  47 MB  ->  1,3 MB gz
```

### UM COMANDO DE CADA LADO — corpus **e** logs juntos

> Pedido do usuário no mesmo dia: *"a ideia é pegar os treinos de uma maquina e
> os logs, e quando a outra maquina for atualizar, tb atualizar os logs e os
> treinos"*.

O problema nunca foi transporte de UM arquivo — foi **completude**. Sempre
faltava um pedaço, e sempre em silêncio: o corpus não viajava; os logs viajavam
mas só os que alguém lembrou de `git add`; e quem puxava não tinha um passo que
dissesse "faltou isto". [`scriptis_da_ia/sincroniza.py`](scriptis_da_ia/sincroniza.py)
cobre os dois de uma vez:

```bash
cd scriptis_da_ia
python sincroniza.py entrega   # antes de passar a vez
python sincroniza.py chega     # ao sentar na outra máquina
```

| verbo | o que faz |
|---|---|
| `entrega` | exporta a fatia do corpus + **versiona todo log que o `index.json` referencia e o git não tem** |
| `chega` | `git pull --ff-only` + importa as fatias + confere se todo log referenciado chegou |

`entrega` **não commita nem empurra**, de propósito: o `pre-push` exige bloco de
`HANDOFF.md`/`TODO.md`, e isso é trabalho de sessão. Ele prepara e diz o que falta.

A ferramenta de baixo nível, para uso avulso, é
[`scriptis_da_ia/corpus_git.py`](scriptis_da_ia/corpus_git.py):

```bash
python corpus_git.py status      # o que falta importar/exportar
python corpus_git.py importa     # aplica as fatias do git no .jsonl local
python corpus_git.py exporta     # cria a fatia com o que só existe aqui
```

### OS LOGS NÃO SÃO ZIPADOS — e a medição é o motivo

```
logs/ em disco (working tree) : 27,0 MB
logs/ dentro do .git          :  1,7 MB
tar.gz dos mesmos arquivos    :  1,7 MB
```

**O git já comprime os logs exatamente na taxa que o zip daria.** Comprimir não
economizaria um byte, e custaria: **11 ferramentas** leem `logs/parsed/*.json`
direto (`parse_combat_log`, `audit_human_patterns`, `audit_real_losses`,
`decision_quality_vs_human`, até o `decision_engine`), e todas quebrariam —
além de perder diff, grep e merge por arquivo.

O corpus precisou de fatias por ser **um arquivo de 465 MB**. Os logs já são
muitos arquivos pequenos, que é o formato em que o git é bom. **A solução para
os logs não era formato, era automação** — ninguém mais precisa lembrar do
`git add`.

`metrics/q_alvos.jsonl` **continua gitignored** — mudou de "o corpus" para
"materialização local das fatias", remontável a qualquer momento com
`importa`. Os três leitores (`ciclo.py`, `treinar_q.py`, `treino_continuo.py`)
não foram tocados: continuam lendo o mesmo caminho fixo.

**É OBRIGATÓRIO, não opcional**, e em dois pontos que param de verdade:

1. `ciclo.py` e `treino_continuo.py` **se recusam a rodar** com fatia pendente.
2. O `pre-push` **bloqueia** o push se houver linha gerada aqui fora do git.

Os dois existem porque o modo de falha é silencioso: treinar com o corpus
menor não dá erro, só produz um modelo pior que ninguém relaciona à causa.

### QUANDO O PROJETO TERMINAR, ISTO SAI DO GIT

> Registrado a pedido explícito do usuário, 18/09/2026: *"deixe registrado que
> quando finalizarmos o projeto, a gente retira do git esses zips"*.

As fatias são **andaime de desenvolvimento**, não entregável. Enquanto houver
duas máquinas treinando, elas pagam o próprio custo. Terminado o projeto, o
histórico do git fica carregando dezenas de MB de corpus intermediário que não
serve a mais ninguém.

**A remoção exige reescrita de histórico** (`git filter-repo` ou equivalente) —
apagar os arquivos num commit novo não recupera espaço nenhum, porque as fatias
continuam em todos os commits anteriores. É operação destrutiva e combinada:
não fazer por iniciativa de sessão, e não fazer sem o corpus final salvo fora
do git antes.

---

## PASSO A PASSO — instalar numa máquina nova

1. `git clone https://github.com/Karlmalone13/Analizador_de_Decks.git`
2. `BOT\instalar.bat` (duplo-clique) — acha o jogo, instala o BepInEx, copia a
   DLL pronta de `BOT/dist/` (**sem precisar de .NET**), cria o venv e gera
   `iniciar_bot.bat`.
   Se não achar o jogo:
   `powershell -ExecutionPolicy Bypass -File BOT\instalar.ps1 -GameDir "<caminho>\Builds_Windows"`
3. Trazer corpus e logs (desde 18/09/2026 os dois viajam pelo git — **não há
   mais zip para pedir a ninguém**):
   ```bash
   cd scriptis_da_ia && python sincroniza.py chega
   ```
   Sem isso o treino começaria do zero e perderia as centenas de milhares de
   posições já acumuladas — mas agora ele **não deixa**: `ciclo.py` e
   `treino_continuo.py` se recusam a rodar com fatia pendente.

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
está parada. O corpus vem pelo git, em fatias: rode
`cd scriptis_da_ia && python corpus_git.py importa`.

Quero treinar e jogar CPU x CPU aqui.

Antes de começar, confirme:
1. o corpus tem o volume esperado e todas as linhas têm o campo "origem"
   (`python corpus_git.py status` mostra a quebra por origem)
2. qual a seed do próximo ciclo (ciclo_estado.json)
3. scikit-learn na versão do requirements.txt e q_net.joblib carrega sem erro

Depois disso, rode o ciclo e me diga os números.
```

Os três pontos não são burocracia: são exatamente onde isso quebra em silêncio —
corpus faltando, seed colidindo, ou versão de biblioteca que não abre o modelo.

---

## FECHAMENTO DE SESSÃO DE JOGO — o que entregar quando o usuário pedir

> Combinado com o usuário em 14/09/2026: *"eu vou continuar jogando, ai quando
> eu solicitar você faz o push e me envia os logs em zip e o q_alvos, para
> evitar problemas"*.

Enquanto ele joga, **não** interromper com push a cada partida. Quando ele
pedir, entregar **os três**:

1. **`python sincroniza.py entrega`** — exporta em fatia `.gz` o corpus gerado
   nesta máquina E versiona os logs novos. **Antes do push**, senão o
   `pre-push` bloqueia.
2. **`git push`** — leva código, banco de logs (`logs/`), `ciclo_estado.json`,
   `q_net.joblib` (se promovido) **e agora o corpus, nas fatias**. Antes:
   `git pull`, e os blocos de `HANDOFF.md`/`TODO.md` (o hook bloqueia sem eles).
3. **ZIP do banco de logs** — `logs/{raw,parsed,decks,decks_full}` +
   `index.json`. Entregar por `SendUserFile`.

> **O passo 3 é REDUNDANTE com o git, e isso é intencional** — o pedido foi
> explicitamente *"para evitar problemas"*. Não substituir o push por ele nem
> vice-versa: o git é quem dá merge e histórico; o zip é a cópia que não
> depende de nada dar certo.
>
> **O ZIP do `q_alvos` SAIU da lista em 18/09/2026.** Ele era a ÚNICA via do
> corpus, e foi exatamente isso que quebrou: o usuário chegou ao trabalho sem
> conexão com a outra máquina e o zip não existia deste lado. Agora o corpus
> viaja pelo git em fatias e **ninguém precisa pedir arquivo a ninguém**.

**Conferir antes de entregar** (os três lugares onde isso quebra em silêncio):
contagem de linhas do corpus e a quebra por `origem`; que todo log novo entrou
no `index.json`; e que a telemetria de cada partida do bot foi lida
(`live_runs/`, na ordem obrigatória).

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
* **Política corporativa pode bloquear `instalar.ps1`** (achado 14/09/2026, na
  2ª máquina). `MachinePolicy = RemoteSigned` vem por política de grupo e
  **vence o `-ExecutionPolicy Bypass`** da linha de comando — o parâmetro não
  ajuda. O arquivo chegou com a marca da internet (`Zone.Identifier`), e o erro
  é enganoso: diz *"não está assinado digitalmente"*, não *"está bloqueado"*.
  Conferir e destravar só esse arquivo:
  ```powershell
  Get-Item BOT\instalar.ps1 -Stream Zone.Identifier   # existe = bloqueado
  Unblock-File BOT\instalar.ps1
  ```
  Mesma família do `start` bloqueado que o `JOGAR.bat` já contorna com
  `Start-Process`. Só o `instalar.ps1` veio marcado; o `setup_bepinex.ps1` não.
* **O `.venv/` (347 MB) e o `iniciar_bot.bat` não eram ignorados** — o
  instalador cria os dois. O `.bat` é gerado com os caminhos ABSOLUTOS da
  máquina (`OPTCG_GAME_DIR` + raiz do repo cravados), então commitá-lo apontaria
  a outra máquina pra uma pasta de jogo inexistente. Ambos foram pro
  `.gitignore`; o `.bat` volta rodando `BOT\instalar.bat`.
* **A DLL instalada pode ser mais velha que a do repo, e o sintoma é mudo.** Na
  2ª máquina a instalada era de 31/08 (67.584 bytes) e **não tinha CPU x CPU** —
  o Shift+C simplesmente não existia. Conferir por conteúdo, não por data:
  ```powershell
  # strings de .NET são UTF-16LE: grep ASCII NÃO acha e dá falso negativo
  python -c "b=open(r'<jogo>\BepInEx\plugins\OPTCGBotPlugin.dll','rb').read(); print('CPU x CPU'.encode('utf-16-le') in b)"
  ```
  `BOT\instalar.bat` copia a de `BOT/dist/` e resolve, sem precisar de .NET.
* **`du -sh .git` NÃO é o tamanho do repositório.** O número que vale é
  `git count-objects -vH | grep size-pack`. Em 14/09 a pasta mostrava 1,1 GB
  com 28 MB de conteúdo real — eram objetos soltos, e `git gc --prune=now`
  resolveu em 31 segundos.

---

## O QUE O TOKEN **NÃO** PROTEGE (achado 17/09/2026, bloco 852)

`ciclo_estado.json` protege a **seed**. Ele não protege o **histórico do git**.

Caso real: a Arthur_PC tinha **3 commits nunca empurrados** quando a
Arthur_Trabalho assumiu. As duas avançaram da mesma base, e o `pull --ff-only`
falhou com `Not possible to fast-forward`. Resolver exigiu merge com resolução
manual de conflito.

> **Quem SAI empurra antes de sair. Quem ENTRA confere que não tem commit local
> pendente** (`git log --oneline origin/main..HEAD` tem que vir vazio).

### Os zips ficam na máquina que os recebeu

As sessões do Claude Code são **locais de cada máquina** — verificado:
`list_sessions` numa máquina não vê as sessões da outra, nem arquivadas. Os
arquivos que uma sessão envia são cartões **dentro daquela conversa**; sem abrir
aquela conversa, não há de onde baixar.

**Isto deixou de doer em 18/09/2026.** Até então o corpus era o único que
dependia do zip — e por isso a sessão que o recebeu virava um ponto único de
falha: sem abrir *aquela* conversa, *naquela* máquina, não havia de onde
baixar. Foi o que travou o trabalho em 18/09.

Agora o git leva **tudo** que importa: banco de logs, código, `q_net.joblib`,
`ciclo_estado.json` e o corpus em fatias. Nenhum arquivo depende mais de uma
conversa específica estar acessível.

### Ao unir `logs/index.json`, chaveie por `parsed_file`

O campo **`id` NÃO é único**: partidas do mesmo lote (`_p2`, `_p3`, …)
compartilham o timestamp. Unir por `id` descarta entradas **sem erro nenhum**.
