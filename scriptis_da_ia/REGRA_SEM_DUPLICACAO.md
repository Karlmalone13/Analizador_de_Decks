# Regra do projeto: 1 motor só, zero função duplicada

**Leitura obrigatória antes de qualquer commit/push que toque
`decision_engine.py`, `sim_bridge.py`, `server.py`, `replay_optcg.py` ou
`bot_optcgsim.py`.** Reforçado pelo hook `pre-commit` (imprime este
arquivo inteiro em todo `git commit`, igual já fazia com `MEMORY.md`).

## A regra

Pedido explícito do usuário (25/07/2026): **"apenas 1 motor, apenas um
engine de decisão"** — e depois, ao investigar mais a fundo, uma
extensão direta da mesma regra: **nunca ter duas funções diferentes
respondendo à MESMA pergunta de decisão** (mesmo que uma delas não seja
chamada de "motor"). Toda decisão do jogo — o que jogar, o que
descartar, qual alvo escolher, se vale pagar um custo — tem que morar
em **um único lugar** (`decision_engine.py`, exposta via
`sim_bridge.py`). Se o caminho ao vivo (`sim_bridge.py`/`server.py`/
`bot_optcgsim.py`) ou uma ferramenta de replay/self-play precisa dessa
decisão, ela **chama** a função existente — nunca reimplementa a mesma
lógica com um cálculo próprio, nem que seja "só uma versão mais simples
por enquanto".

Isso vale em DOIS eixos, achados nesta mesma sessão:

1. **Orquestração de turno duplicada** (`ReplayMatch.play_turn()`
   reimplementando o que `OPTCGMatch.play_turn()` já fazia, em vez de
   chamar) — bug de fases inteiras faltando (`end_phase()` nunca
   resolvia `[End of Your Turn]` no replay).
2. **Decisão de conteúdo duplicada** (duas funções calculando "qual a
   melhor/pior carta" com heurísticas DIFERENTES para o MESMO tipo de
   escolha) — o caminho ao vivo usando uma versão mais pobre do que o
   motor interno já tinha construído.

## Casos reais já encontrados e corrigidos (25/07/2026, blocos 372-373)

- `ReplayMatch.play_turn()` apagado — agora delega 100% a
  `OPTCGMatch.play_turn()` via `post_don_hook` opcional (ver HANDOFF
  bloco 372).
- `DecisionEngine.choose_to_trash()` (só ao vivo, via
  `sim_bridge.resolve_prompt_choice`) reimplementava
  `min(hand, key=avaliar_carta)` puro — ignorava TODAS as proteções que
  `EffectExecutor._choose_to_trash()`/`_trash_value()` já aplicam
  internamente (evento `[Counter]` com desconto por redundância,
  remoção/bounce, carta cara/win-con do game_plan, carta que enche o
  trash pro combo, jogável neste turno, reanimável via
  `play_from_trash`). Corrigido: agora delega pra
  `EffectExecutor(self.me, self.opp)._choose_to_trash(hand)`.
- `sim_bridge._choose_opp_target_filtered()` reimplementava na mão o
  mesmo filtro (`cost_lte`/`cost_gte`/`cost_eq`/`power_lte`/`power_gte`/
  `rested_only`) que `eligible_cards()` (`rules_facade.py`) já
  centraliza para o resto do motor inteiro. Corrigido: agora chama
  `eligible_cards(...)` pra filtrar e `choose_highest_board_value(...)`
  pra escolher.
- `sim_bridge.resolve_prompt_choice()` tinha 2 pontos com
  `min(gs.field_chars, key=lambda c: c.board_value())` reimplementado à
  mão (zonas `own_field`/trash-ko) em vez de chamar
  `choose_lowest_board_value()` (`rules_facade.py`, que já existe
  exatamente para isso, com o mesmo comentário de risco: "a execução
  tem que escolher a MESMA carta que a decisão assumiu"). E um
  `max(gs.trash, key=lambda c: c.board_value())` que devia ser
  `choose_highest_board_value()`. Todos corrigidos.

Todos os 4 casos: mesmo padrão — uma função nova (ou um trecho inline)
resolvia de novo, à mão, algo que outra função no motor já resolvia
melhor, geralmente porque o segundo ponto foi escrito antes da versão
rica existir, ou por conveniência local, e nunca foi atualizado depois.

## Como caçar duplicatas (faça isso antes de aceitar qualquer PR/commit novo que adicione uma função de decisão)

1. Pergunte: "essa função decide algo que o jogo já decide em outro
   lugar (mesmo que com um nome diferente)?" — nomes parecidos com
   prefixo `_`/sem prefixo, ou nomes que descrevem a MESMA operação em
   português/inglês trocado, são o sinal mais comum (`choose_to_trash`
   vs `_choose_to_trash` foi exatamente assim).
2. Grep pelo verbo da decisão em todo o repo antes de escrever a
   função nova: `choose_`, `_choose_`, `escolhe`, `melhor`, `pior`,
   `select_`, `pick_`, `avaliar`, `_value`, `_score`, `eligible_cards`,
   `board_value`. Se já existe algo que resolve o mesmo tipo de
   pergunta (mesmo que pra um contexto ligeiramente diferente), a opção
   default é DELEGAR ou PARAMETRIZAR a função existente — não criar uma
   nova ao lado.
3. Se `sim_bridge.py`/`server.py`/`bot_optcgsim.py` precisam de uma
   comparação numérica (`<`, `<=`, `>=`, `>`, `==`) pra decidir algo, ela
   PRECISA estar chamando algo de `decision_engine.py` no mesmo trecho
   — o hook `pre-commit` já bloqueia mecanicamente esse padrão nos 3
   arquivos (ver `ENGINE_TOUCHPOINTS`/`BRIDGE_FILES` no hook — varredura
   retroativa de `bot_optcgsim.py`/`server.py` feita em 25/07/2026,
   bloco HANDOFF 375, resultado limpo), mas isso é uma rede de
   segurança, não substitui a pergunta 1.
4. Se encontrar uma duplicata JÁ existente (não uma nova sendo
   escrita): registre em `HANDOFF.md`/`TODO.md`, corrija delegando pra
   fonte única, adicione teste permanente em `smoke_fast.py` provando a
   divergência de comportamento (não só que a função roda sem
   exception), rode `smoke_fast.py` + `smoke_test.py` inteiros antes de
   commitar.
