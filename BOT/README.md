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
