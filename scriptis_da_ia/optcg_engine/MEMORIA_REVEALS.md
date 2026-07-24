# Memória de cartas reveladas (revealed information memory)

Objetivo: quando o bot **revela/olha** uma carta (vida, topo de deck, mão do
oponente, e cartas vistas em **search**), guardar a identidade dessa carta
para o turno **e os próximos**, reduzindo a incerteza do modelo de oponente e
melhorando decisões (saber que carta há na vida/deck, o que o oponente segura).

## O que já existia (não reinventar)

- `GameState.revealed_to_opponent` — `set` de `id(card)` de cartas **na mão**
  cuja identidade foi exposta por efeito de busca com "reveal". Limpeza lazy
  em `GameState.known_hand_cards()` (remove ids de cartas que saíram da mão).
- `OpponentModel` (`opponent_model.py`) — leitura Monte Carlo do oponente:
  `sample()` sorteia mão+vida fictícias do `full_decklist` menos o que já é
  conhecido. `known_hand_cards()` já entrava como **certeza** na amostra.
- `reveal_opp_hand` (Arlong OP01-063) **já** alimentava `opp.revealed_to_opponent`
  → mão conhecida do oponente já funcionava.

## Gaps fechados nesta iteração (engine, testado)

Estendido o **mesmo padrão** (`id(card)` + limpeza lazy) para vida e deck:

| Campo novo (`GameState`) | Accessor | Populado por |
|---|---|---|
| `revealed_life` | `known_life_cards()` | peek/reveal de carta da Life |
| `revealed_deck` | `known_deck_cards()` | topo do deck visto por **search** ou peek |

Ambos copiados no `__deepcopy__` (isolados por clone do Turn Planner).

### Pontos de captura (onde a identidade passa a ser conhecida)

- **Vida:** `life_top_revealed_cost` (OP15-119 "reveal 1 from top of your Life"
  → `me.revealed_life`).
- **Deck do oponente (peek):** `peek_opp_deck_top` (Pudding OP11-070),
  `reveal_opp_deck_top_choose_cost` → `opp.revealed_deck`.
- **Search (o buscador vê o topo):** `add_to_hand` e `trash_from_looked_deck`
  ("look at top N…") → todas as N cartas olhadas entram em `me.revealed_deck`;
  a que sai do deck (pra mão/trash) some sozinha na limpeza lazy, as que
  ficam seguem conhecidas.

> **Cartas reveladas por SEARCH (pedido explícito do usuário):** ao olhar as
> N cartas do topo e pegar 1, as outras N−1 continuam no deck e **permanecem
> conhecidas** — então nas próximas compras/buscas o bot já sabe o que vem.
> Coberto pelos hooks de `add_to_hand`/`trash_from_looked_deck` acima.

### Consumo (decisão)

- `OpponentModel._known_population_excluded()` agora exclui também a **vida
  conhecida** do pool de sorteio.
- `OpponentModel.sample()` inclui a **vida conhecida como certeza**
  (`n_life_unknown = len(vida) − len(vida conhecida)`), como já fazia com a mão.

## Modelo de invalidação

Sempre **lazy**, nunca manual: `known_*_cards()` filtra o `set` contra a zona
atual (`self.life` / `self.deck` / `self.hand`) e descarta ids órfãos. Assim,
quando a carta **se move** (dano tira da vida, compra tira do deck, joga tira
da mão), o conhecimento expira automaticamente — sem precisar lembrar de
limpar em cada ponto de mutação (mesma decisão de segurança do
`known_hand_cards`).

## PENDENTE (precisa desktop / teste ao vivo)

1. **Persistência entre decisões AO VIVO.** Em simulação/self-play tudo roda
   numa árvore de estados clonados, então a memória persiste naturalmente. No
   jogo ao vivo, cada `/decide` reconstrói o `GameState` a partir do DTO do
   plugin — a memória de turnos passados **não** está no DTO atual. Falta
   camada no `engine_server` (por `match_id`) que acumule `revealed_life/
   revealed_deck` ao longo da partida e re-injete no estado reconstruído.
   Chave sugerida: `deckUniqueId` (estável por carta na partida), em vez de
   `id()` (só estável dentro de um processo/rollout).
2. **Consumo mais amplo.** Hoje só a vida conhecida entra no OpponentModel.
   Próximos: usar o topo conhecido do próprio deck no sequenciamento
   (search/compra), e o topo conhecido da vida em decisões de trigger.
   Mudança que afeta winrate → validar com self-play/`tune_weights` e partida
   real antes de ligar por padrão.

## Testes

Cobertura unitária em `optcg_engine/` (rodada nesta sessão): accessors +
limpeza lazy (`known_life_cards`/`known_deck_cards`), `__deepcopy__` isola os
sets, `OpponentModel` inclui vida conhecida e a exclui do pool, e captura
end-to-end de `peek_opp_deck_top`. `smoke_fast.py` verde.
