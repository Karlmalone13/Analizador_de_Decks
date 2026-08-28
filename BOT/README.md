# BOT — integração do engine com o OPTCGSim (BepInEx)

Bot que joga OPTCGSim usando o `decision_engine.py` como cérebro, via plugin
C# injetado no jogo (BepInEx) + servidor HTTP local. Substitui o bot antigo de
OCR/mouse (`scriptis_da_ia/bot_optcgsim.py`).

## Arquitetura (regra do motor único — NUNCA violar)

```
Plugin C# (olhos/mãos)
    ↓ JSON
server.py (transporte puro)
    ↓
sim_bridge.py (PORTA: traduz mundo-simulador ↔ mundo-engine)
    ↓
decision_engine.py (CÉREBRO: todas as decisões)
```

- **Plugin C#** (`OPTCGBotPlugin/`) — lê o estado do jogo e executa cliques
  pelos mesmos caminhos do clique humano (o jogo valida e paga custos).
  ZERO lógica estratégica.
- **server.py** (`engine_server/`) — FastAPI em `localhost:8765`. Só converte
  JSON ↔ objetos do engine e delega. ZERO heurística.
- **sim_bridge.py** (`scriptis_da_ia/optcg_engine/`) — porta de entrada do
  motor: converte estado do simulador em `GameState`/`Card`, chama o método
  certo do engine, traduz a resposta de volta (carta → uid).
- **decision_engine.py** — o motor. `OPTCGMatch` (regras), `DecisionEngine`
  (avaliação/decisão). Não sabe que simulador, uid ou HTTP existem.

Se uma decisão nova precisar existir, ela nasce no `decision_engine.py` (ou
como função de tradução no `sim_bridge.py`) — nunca no plugin ou no server.

## ⚠️ Jogo atualizou e o bot parou de funcionar?

O Steam (ou verificação de integridade) apaga a pasta `BepInEx` inteira da
instalação do jogo quando atualiza — isso já aconteceu (09/07/2026) e vai
acontecer de novo. Sintoma: `LogOutput.log` não existe mais, ou o bot não
reage a nada.

**Fix**: feche o jogo (o BepInEx trava `winhttp.dll` enquanto o jogo está
aberto) e rode:
```
C:\Projetos_TI\analidador_de_decks_optcg\BOT\setup_bepinex.bat
```
(duplo-clique funciona). Reinstala o BepInEx (usa o zip já salvo em
`BOT/vendor/`, não precisa internet) + recompila e copia o plugin. Depois
é só abrir o jogo de novo.

## DLL pre-compilada -- o que torna o bot instalavel em VARIOS PCs

> **Requisito registrado a pedido do usuario (28/08/2026, bloco 727)**:
> *"registre que temos que deixar ele em Dll para podermos instalar em
> varios computadores se quisermos"*.

O plugin **e** uma DLL (`OPTCGBotPlugin.dll`) -- o BepInEx so carrega
DLL, nunca `.exe`. O problema nunca foi o formato: era que a DLL **nao
era versionada** (`bin/` esta no `.gitignore`), entao cada maquina nova
precisava de **.NET SDK** pra compilar do zero.

**Fluxo agora:**

1. Numa maquina COM .NET, rode `BOT\instalar.bat`. Alem de instalar, ele
   guarda a DLL compilada em **`BOT\dist\OPTCGBotPlugin.dll`**.
2. **Commite esse arquivo.**
3. Nas OUTRAS maquinas, `BOT\instalar.bat` detecta a DLL pronta e so
   copia -- **sem .NET SDK, sem compilar**.

Pra forcar recompilacao (jogo atualizou, plugin mudou):
```
powershell -ExecutionPolicy Bypass -File BOT\instalar.ps1 -Rebuild
```

**Limite honesto:** a DLL e ligada contra as DLLs do jogo (`Assembly-CSharp`,
`UnityEngine`, ...). Se o OPTCGSim atualizar e mudar essas assinaturas, a
DLL pre-compilada para de funcionar e **e preciso recompilar numa maquina
com .NET** e recommitar. Sintoma: o bot nao reage a nada no jogo.

## Instalar em OUTRA maquina

```
BOT\instalar.bat        (duplo-clique)
```
ou, apontando o jogo na mao:
```
powershell -ExecutionPolicy Bypass -File BOT\instalar.ps1 -GameDir "D:\Jogos\OnePieceSimulador\Builds_Windows"
```

Ele acha o jogo sozinho (bibliotecas Steam + discos), instala o BepInEx,
compila o plugin contra as DLLs DESSA maquina, cria o venv com as
dependencias e gera `iniciar_bot.bat` na raiz.

**Por que nao existe um .exe unico** (pergunta do usuario, 28/08/2026):
o bot tem duas metades e nenhuma vira executavel.
- O **plugin** e uma DLL do BepInEx -- por definicao precisa ser DLL, e e
  compilada contra as DLLs do PROPRIO jogo (que mudam por versao e por
  maquina). Um .exe nao seria carregado.
- O **motor** e Python e precisa do banco de cartas, do parser de efeitos
  e do engine inteiro. Daria pra empacotar com PyInstaller, **mas so
  compilando no Windows** -- nao existe cross-compile, e as sessoes de
  desenvolvimento remoto rodam em Linux.

**Pre-requisitos na maquina nova** (o instalador avisa se faltar):
- .NET SDK -- https://dotnet.microsoft.com/download (compilar o plugin)
- Python 3.10+ com "Add to PATH" -- https://python.org
- O OPTCGSim instalado

**O que mudou pra isso funcionar** (bloco 722): o `OPTCGBotPlugin.csproj`
tinha o caminho do jogo CRAVADO em 11 lugares (`E:\Games\...`) -- toda
referencia aponta pra uma DLL que vive na instalacao do jogo. Agora vem
de `-p:GameDir=...` ou de `OPTCG_GAME_DIR`, com o caminho antigo so como
default.

## Como rodar (Solo vs Self)

1. Servidor do engine (primeiro):
   ```cmd
   cd C:\Projetos_TI\analidador_de_decks_optcg
   python BOT\engine_server\server.py
   ```
2. Abrir o OPTCGSim (BepInEx instalado em
   `E:\Games\OnePieceSimulador\Builds_Windows\` carrega o plugin sozinho).
3. Solo vs Self. O bot é o lado de **baixo** (`Lps_Players[0]`, "[You]");
   o humano joga o lado de cima.

Logs do plugin: `E:\Games\OnePieceSimulador\Builds_Windows\BepInEx\LogOutput.log`
(heartbeat `[HB]` a cada 3s para debug). Decisões do engine: saída do server
— e desde 10/07 essa saída TAMBÉM fica salva automaticamente em
`BOT/engine_server/logs/session_<timestamp>.log` (arquivo criado sozinho
toda vez que o server sobe, sem precisar deixar o terminal aberto). Se o bot
parar de agir no meio de um turno ou fizer algo estranho, manda esse arquivo
junto com o combat log — sem ele só dá pra ver O QUE o bot decidiu (via
combat log), não POR QUE ele parou de decidir (só o console/log do server
mostra os `[ENG]`/`[DEF]`/`[PLAY]` de cada chamada de `/decide`/`/defense`).
Esses logs não vão pro git (`.gitignore`) — são diagnóstico efêmero, não o
banco de combat logs.

Telemetria estruturada de decisões: cada `/decide` gera um `decisionId` e grava
estado anterior, ações pontuadas, ação escolhida e resposta em
`BOT/engine_server/logs/decisions/decisions_<timestamp>.jsonl`. O plugin envia
eventos `sent` e, no próximo estado principal estável, `confirmed` ou `failed`
com o estado posterior. Para medir:

```cmd
cd scriptis_da_ia
python bot_efficiency_report.py --decision-log ..\BOT\engine_server\logs\decisions\decisions_<timestamp>.jsonl
```

A telemetria cobre Main Phase, mulligan, defesa, triggers, reacoes, custos
opcionais e selecao de alvos. O fim da partida grava `win/loss`. Preserve o
combat log e o JSONL da mesma sessao e use:

Por padrao isso agora e automatico: ao receber `GameOver`, o server espera o
arquivo AutoSaved estabilizar, adiciona ao banco e grava relatorio + recibo em
`scriptis_da_ia/metrics/live_runs/`. Para desligar, inicie o server com
`BOT_AUTO_COLLECT=0`. Se a deteccao automatica falhar, o fallback e um comando:

O plugin mostra no canto superior esquerdo `Salvando log no banco...` e depois
`LOG SALVO NO BANCO`. Em falha, mostra a mensagem em vermelho. A confirmacao
tambem fica no `LogOutput.log` com o caminho do recibo.

`LOG SALVO NO BANCO` so aparece depois de conferir `logs/index.json`, os arquivos
raw/parsed/decks e o nome oficial `Lider-Cores_x_Lider-Cores_timestamp`.

Para comparar dois relatorios sem misturar camadas:

```cmd
python compare_bot_reports.py metrics\antes.json metrics\depois.json --json metrics\comparacao.json
```

```cmd
python scriptis_da_ia\collect_latest_match.py
```

```cmd
python parse_combat_log.py <CombatLog.log> --add-to-db
python bot_efficiency_report.py --decision-log ..\BOT\engine_server\logs\decisions\decisions_<timestamp>.jsonl --json metrics\live_<data>.json
python baseline_metrics.py --deck-a Imu --deck-b "Barba Negra BY" --n 50 --seed 20260717 --json metrics\selfplay_imu_teach.json
python audit_decision_quality.py --n 50 --seed 20260717 --json-out metrics\selfplay_decisions.json
```

`confirmed` significa que o DTO mudou; não prova sozinho que toda a semântica do
efeito foi correta. Os JSONL são efêmeros/ignorados pelo git: preserve o arquivo
junto do combat log quando investigar uma partida.

**Shift+B**: liga/desliga o bot em tempo real, sem reiniciar o jogo nem
recarregar a dll (`BotDriver.cs`, campo `_botEnabled`). Útil pra jogar
manualmente e printar telas de decisão sem o plugin clicar antes de dar
tempo. Checado a cada frame antes de qualquer leitura de estado do jogo —
funciona mesmo com o bot pausado no meio de uma ação. O log confirma com
`[Bot] ATIVADO`/`[Bot] DESATIVADO (Shift+B)`.

**Shift+P**: troca qual lado (P1 "You"/baixo ou P2 "Opponent"/cima) o bot
controla (`BotPlayerIndex`, `BotDriver.cs`) — Solo vs Self não tem tela de
cara-ou-coroa, os dois lados já ficam fixos desde o início da partida, e
isso é o jeito de escolher se o bot joga primeiro (ímpar) ou segundo
(par), ou simplesmente qual lado é seu e qual é do bot. Seguro trocar a
qualquer momento (o driver lê o valor fresco todo frame). Log confirma
com `[Bot] agora controla P<N> (Shift+P)`.

## Recompilar o plugin (após editar os .cs)

```cmd
dotnet build BOT\OPTCGBotPlugin\OPTCGBotPlugin.csproj
```
O build copia a dll para `BepInEx\plugins\` automaticamente.
**Fechar e reabrir o jogo** para carregar a dll nova.

## Endpoints do server

| Endpoint | Uso |
|---|---|
| `GET /health` | plugin verifica se o server está vivo |
| `POST /mulligan` | mão inicial → keep/mulligan (`_mulligan_decision`) |
| `POST /decide` | ação do turno: play/attack/end_turn (`choose_action`) |
| `POST /defense` | fases `blocker`/`counter`/`trigger`/`reaction`/`optional` |
| `POST /choose_target` | ordena alvos de efeito pendente por preferência |

## O que o bot cobre hoje

- Mulligan, draw card/don, plays (Character/Stage/Event), ataques, end turn
- Defesa: blocker, counter, trigger, reação de líder (ex: Teach), prompts de
  seleção de alvo (acaActive/V3), downside offers, deploy swap (campo cheio)

## Pendências conhecidas

- Ações `activate`/`attach_don` do engine viram end_turn no server
- Multiplayer: adaptar detecção de lado/turno (objetivo final: captar logs
  contra humanos para validar o engine — ver memory/project_objetivo_bot.md)
