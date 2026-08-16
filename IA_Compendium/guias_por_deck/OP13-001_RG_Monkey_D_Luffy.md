# Red/Green Monkey D. Luffy (OP13-001) — guia de deck

> **Fonte**: Spell Mana, "Red Green Monkey D.Luffy Deck Guide – One Piece Card
> Game" (autor: Sorry, 22/10/2025) —
> <https://spellmana.com/red-green-monkey-d-luffy-deck-guide-one-piece-card-game-2/>
> Salvo por pedido do usuário em 16/08/2026 (bloco 568), depois da partida ao
> vivo em que o bot jogou este deck e não conseguiu usar o líder.
> Material de REFERÊNCIA estratégica, mesmo papel do
> [`RESUMO_ESTRATEGICO.md`](../RESUMO_ESTRATEGICO.md): serve para comparar o
> `game_plan` do motor contra o plano real do deck. Não é código.

## Por que este guia está no repositório

A partida `Monkey.D.Luffy-RG_x_Rocks.D.Xebec-B_2026-08-16T17.10.36` expôs que
o bot não executa o plano deste deck. O guia explica o plano em detalhe e
**contradiz uma suposição embutida no motor** (ver "Conflitos com o motor"
abaixo), então vale mais como documento de arquitetura do que como dica de
jogo.

## O líder

4 de Life. Efeito **defensivo**:

> `[DON!! x1] [On Your Opponent's Attack]` — se você tiver **5 ou menos DON
> ativos**, pode restar qualquer número de DON. Para cada DON restado, este
> Líder ou até 1 Personagem tipo *Straw Hat Crew* ganha **+2000 de poder**
> durante esta batalha.

**Duas condições, ambas obrigatórias** (é o ponto que o guia enfatiza):

1. ter **1 DON anexado ao Líder**;
2. ter **no máximo 5 DON ativos**.

Máximo prático: +10.000 de poder. Pode passar disso com as cartas que
*re-ativam* DON durante o turno do oponente.

Confirmado contra o `card_effects_db.json` (16/08/2026) — o parser está
correto nas duas condições:

```json
"on_opp_attack": {
  "don_requirement": 1,
  "conditions": { "don_lte": 5 },
  "costs": [ { "type": "rest_any_don" } ],
  "steps": [ { "action": "buff_power_per_count", "amount_per": 2000,
               "source": "rested_don_this_effect",
               "target": "leader_or_character",
               "filter_type": "straw hat crew" } ]
}
```

## O plano do deck: *banking* de DON

A frase central do guia:

> "Don management is crucial. We want to **bank Don** to get the most out of
> our Leader's effect. Depending on the state of the game, we might go for
> **less threatening attacks** to keep more Don for the defense."

Ou seja: guardar DON é a jogada, não desperdício. O deck aceita **atacar
menos** para sobreviver mais, e ganha alongando o jogo até as win conditions
de custo alto.

## Motor de recursos (as cartas que alimentam o líder)

| carta | papel |
|---|---|
| Nami (1) | **anexa 1 DON restado ao Líder** — resolve a condição 1 |
| Monkey D. Garp (1) | busca carta de custo 3+ |
| Bonney (3) | Blocker; no turno do oponente, **ativa 1 DON** |
| Zoro (4) | ao entrar **ativa 2 DON**; se re-ativa no fim do turno |
| Sanji (5) | 7000; ao entrar **ativa 2 DON**; +1 DON no fim de cada turno |
| Luffy (6) | Double Attack; **ativa 4 DON** (trava plays de custo 5+) |
| Trafalgar Law (6) | Blocker 6000; devolve 1 personagem e joga outro ≤5 |
| Roronoa Zoro (9) | win condition — pode atacar **3 vezes** |
| Shanks (10) | 12000; **ativa até 10 DON** (não podem pagar cartas) |

Eventos: *Charlestone* (+4000 e ativa 3 DON), *Demon Aura Nine Sword* (resta 2
personagens/DON do oponente; serve para **cair de 6 para 5 DON** e destravar o
líder), *Gum-Gum Giant Pistol* (+6000, finalizador com o Zoro 9).

## Curva (do guia)

**Jogando primeiro**: T1 searcher (1) · T2 Bonney (3) · T3 Sanji (5) ·
T4 Law+Sanji ou Luffy+Zoro (7) · T5 e T6 Zoro 9.

**Jogando segundo**: T1 searcher (2) · T2 Zoro (4) · T3 Law+Sanji (6) ·
T4 Law+Sanji ou Luffy+Zoro (8) · T5 Zoro 9 (10).

Mulligan — primeiro: searcher 1, Bonney 3, Sanji 5. Segundo: searcher 1,
Zoro 4, Law 6.

## Conflitos com o motor (o que importa para o projeto)

1. **DON ocioso não é desperdício aqui.** O motor trata DON sobrando como
   "margem de pressão" a ser anexada. Este deck quer o contrário. A métrica
   `pct_turnos_zero_don` do `quality_baseline.py` (bloco 565) conta "terminar
   com 0 DON" como BOM — para este arquétipo é **ruim**, porque sem DON ativo
   não há como pagar o custo do líder na defesa. **Métrica invertida para o
   arquétipo**; não usar esse número isolado para julgar este deck.
2. **Atacar menos pode ser certo.** "Go for less threatening attacks to keep
   more Don" colide de frente com o peso de ataque do motor.
3. **Teto de 5 DON ativos.** Nenhuma heurística genérica de "gaste seu DON"
   modela isso: passar de 5 **desliga** o líder. O guia chega a descrever
   jogar um Evento só para cair de 6 para 5.
4. **Anexar DON no Líder é jogada de setup**, não de dano — era exatamente a
   opção que o motor nunca gerava (bloco 567).
