# Guias de deck por líder — índice e fila de trabalho

Material de REFERÊNCIA estratégica (não é código). Serve para comparar o
`game_plan`/arquétipo que o motor usa contra o plano REAL de cada deck —
a comparação que o [`CLAUDE.md`](../../CLAUDE.md) já torna obrigatória antes
de mexer em comportamento por líder.

Criado em 16/08/2026 (bloco 568) por pedido do usuário: *"faça uma varredura
nesse site Cards Realm, para mapear a instrução de cada deck e salvar no nosso
IA"*.

## Por que isso vale mais que classificação automática

Dois precedentes já provaram o ponto:

- O guia do **Mihawk OP14-020** (já no `RESUMO_ESTRATEGICO.md`) **corrigiu o
  catálogo do compêndio**: não é "remoção de mesa", é rest/tempo control.
- O guia do **RG Luffy OP13-001** revelou que o plano do deck (*banking* de
  DON) **contradiz duas suposições do motor** — que DON ocioso é desperdício e
  que atacar mais é melhor. Isso explicou uma derrota ao vivo que nenhuma
  métrica agregada tinha explicado.

## Feitos

| líder | arquivo | fontes |
|---|---|---|
| Monkey D. Luffy OP13-001 (R/G) | [`OP13-001_RG_Monkey_D_Luffy.md`](OP13-001_RG_Monkey_D_Luffy.md) | Spell Mana + Cards Realm |
| Dracule Mihawk OP14-020 | seção no [`RESUMO_ESTRATEGICO.md`](../RESUMO_ESTRATEGICO.md) | Cards Realm |

## Fila — Cards Realm (URLs já levantadas, falta extrair)

Prioridade **alta** = deck que aparece no roster do `gauntlet_matchup.py` ou
nos decks reais do usuário (`<jogo>/Decks/*.deck`), porque é contra esses que
o bot é medido.

| prio | deck | URL |
|---|---|---|
| alta | Purple Enel OP15 | `/pt-br/articles/deck-guide-op15-purple-enel` |
| alta | Lucy OP15 | `/pt-br/articles/deck-guide-op15-lucy` |
| alta | Donquixote Rosinante OP14 | `/pt-br/articles/deck-guide-o-novo-donquixote-rosinante` |
| alta | Jinbe OP14 | `/pt-br/articles/guia-de-deck-op14-jinbe-agressivo-e-focado-em-tritoes` |
| média | Rebecca OP15 (mono blue tempo) | `/pt-br/articles/guia-de-deck-op15-rebecca` |
| média | Roronoa Zoro OP12 | `/pt-br/articles/guia-de-deck-op12-roronoa-zoro` |
| média | Silvers Rayleigh OP12 (aggro) | `/pt-br/articles/deck-guide-op12-silvers-rayleigh-um-otimo-aggro` |
| média | Donquixote Doflamingo OP15 | `/pt-br/articles/deck-guide-op15-donquixote-doflamingo` |
| média | Monkey D. Luffy OP11 (azul/roxo) | `/pt-br/articles/guia-de-deck-op11-monkey-d-luffy-azul-e-roxo` |
| baixa | Gecko Moria OP15 | `/pt-br/articles/guia-de-deck-gecko-moria-op15-adventure-on-kamis-island` |
| baixa | Brook OP15 | `/pt-br/articles/guia-de-deck-brook-op15-adventure-on-kamis-island` |

Prefixo: `https://onepiece.cardsrealm.com`. A listagem veio de
`/pt-br/articles/search/?keyword=&page=2&game=42` — **há outras páginas**, esta
fila cobre só a página 2.

## Template (seguir para manter comparável)

1. **Fonte** (site, autor, data, URL).
2. **Líder**: texto do efeito + condições, e conferir contra o
   `card_effects_db.json` (registrar se o parser bate ou diverge).
3. **Plano do deck** em uma frase.
4. **Cartas-chave** e papel de cada uma.
5. **Curva** turno a turno, se o guia der.
6. **Quando NÃO agir** — a parte mais valiosa para o motor: "quando não
   atacar", "que recurso guardar". É onde os guias mais contradizem as
   heurísticas genéricas.
7. **Conflitos com o motor** — a seção que justifica o arquivo existir.
