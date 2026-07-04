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
(heartbeat `[HB]` a cada 3s para debug). Decisões do engine: saída do server.

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
