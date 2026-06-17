# Plano de Unificação Replay → Engine (optcg_engine)

## O achado central (diagnóstico)

O `replay_optcg.py` foi escrito com **lógica de jogo PRÓPRIA**, separada do
`decision_engine.py`. Isso é a raiz da maioria dos bugs auditados:

- O **engine** (`decision_engine.py`) executa efeitos CORRETAMENTE:
  - On KO dispara só no KO real (`_execute_attack` → `ee.execute(target, 'on_ko')`)
  - On Play via `EffectExecutor` apenas, sem lógica duplicada
  - Regra de combate certa: `atk_power >= defend_power` (ataque ≥ defesa passa)
  - Trigger de vida, banish, double attack tratados

- O **replay** reimplementa tudo de forma simplificada e BUGADA:
  - `draw_then_trash` paralelo → Warcury fazia draw no On Play (devia ser On KO)
  - efeitos pela metade, cartas jogadas sem propósito (Mjosgard/Shirahoshi)
  - decisão de jogar cartas própria, divergente do `choose_card_to_play` do engine

## A correção: Opção B — replay vira só visualização

Decisão tomada: o replay NÃO deve ter lógica. Ele é uma TELA do engine.

Abordagem (validada com o usuário): **modo `verbose` no engine**, não log
estruturado. Razão: replay (detalhado, agora) e simulação em massa (1000
partidas, depois) rodam em MOMENTOS SEPARADOS — não simultâneos. Então um flag
`verbose=True/False` basta: replay liga, simulação em massa não liga. Sem
lentidão, sem arquitetura de eventos.

## Plano em fatias auditáveis

1. **Etapa 1 — Instrumentar o engine com `verbose`.** `play_turn`, `main_phase`,
   `_play_card`, `_execute_attack`, efeitos imprimem o que fazem quando verbose.
   O motor narra as AÇÕES; o replay desenha o ESTADO (caixas, vida, mão) entre turnos.

2. **Etapa 2 — Replay vira fino.** Remover do replay: `play_card`, `execute_attack`,
   `choose_card`, `play_turn`, `_mulligan` próprios. O replay passa a: montar decks,
   chamar `play_turn` do engine com verbose=True, desenhar o estado entre turnos.
   Manter só visualização (`print_field`, `print_deck_list`, cores, `don_bar`).

3. **Etapa 3 — Auditar o ENGINE de verdade** (pela primeira vez). Bugs que podem
   aparecer (do engine, não mais do replay):
   - Defesa usando counter DEMAIS (`should_use_counter`/`use_counter`) — o usuário
     viu blocker + counter 1000 + 2000 juntos quando só um bastava (Grupo 3).
   - Decisão de jogar cartas (`choose_card_to_play`) — validar se joga com propósito.
   - Ativação de `activate_main` / Stage — o usuário quer que a IA use o Stage
     (ex: Empty Throne baixa personagem por -1 custo) — HOJE NÃO ATIVA.

## Pendências de jogo levantadas pelo usuário (a implementar)

- **Mulligan**: a IA deve avaliar a mão inicial e decidir trocar ou não. NÃO EXISTE.
- **Ativar efeitos `[Activate: Main]`** (Stage e personagens) durante o turno.
- **Defesa eficiente**: usar só o counter necessário (não empilhar blocker + counters).
- **Camadas da decisão de DON** (1a já feito em `counter_estimation.py`):
  - 1a: decisão de DON de UM ataque (pressão vs garantir, peso de ameaça). PRONTO.
  - 1b: sequência adaptativa (re-decidir cada ataque vendo o resultado do anterior).
  - 1c: reserva de DON para defesa (não gastar tudo se precisa de evento defensivo).
  - Camada 2: avaliação de risco (posso perder no próximo turno? guardo counters?).
  - Camada 3: custo de exposição (restar personagem o expõe; vale atacar?).

## Intenção de longo prazo

O `optcg_engine` deve virar uma IA que melhora com o tempo (ML/treino). Mas a
ORDEM é: primeiro a IA jogar CERTO pelas regras (base determinística, guiada pelo
documento IA_para_OPTCG.docx), DEPOIS ensiná-la a aprender. ML sobre regras
erradas seria construir sobre fundação trincada.