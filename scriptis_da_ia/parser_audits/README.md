# Auditorias globais do parser

Toda correção iniciada por uma carta deve primeiro buscar a mesma gramática
no banco inteiro. O hook de `pre-commit` bloqueia alterações em
`gerar_effects_db.py` ou `card_effects_db.json` sem um JSON novo
nesta pasta.

Use um nome como `2026-07-15_OP13-002_damage_or_ko.json`:

```json
{
  "trigger_card": "OP13-002",
  "problem": "O draw estava fundido ao gatilho defensivo anterior.",
  "grammar_family": "When you take damage or your Character ... is K.O.'d",
  "queries": [
    "regex executada no cards_rows.csv",
    "variantes adjacentes também pesquisadas"
  ],
  "cards_found": ["OP13-002"],
  "resolution_scope": "isolated_after_global_scan",
  "decision": "A família tem uma carta, mas usa dispatcher parametrizado.",
  "validated_by": ["Card List oficial", "diff_parser PERDEU=0", "smoke_fast"]
}
```

Valores de `resolution_scope`:

- `global`: duas ou mais cartas encontradas e tratadas pela causa comum.
- `isolated_after_global_scan`: somente a carta inicial foi encontrada após
  a busca global; a correção isolada fica permitida e documentada.

O registro é evidência de processo, não fonte de regras para o engine.

## Padrão transversal: "base power" / "base cost" / "power more" / "power less" / "cost more" / "cost less"

Achado 16/07/2026 (ver HANDOFF blocos 195-196): esse padrão de fraseado
NÃO é um bug de 1 mecanismo só. Ele pode vazar em QUALQUER mecanismo do
parser -- KO, rest (próprio/oponente), trash, travas de "não fica ativo
no Refresh", condições de concessão condicional de keyword ("ganha
[Rush]/[Double Attack]/[Blocker] se [Character] tiver base power/cost
N"), buffs/debuffs, condições de contagem (`chars_gte` com filtro de
custo/power), etc. `card.power`/`card.cost` no engine já SÃO os valores
base (buffs ficam isolados em `power_buff`/`cost_buff`); o bug real
nunca é semântico, é sempre um destes dois:

1. O REGEX do parser não reconhece a variante de fraseado ("base power"
   em vez de "power", "power more" sem a palavra "or" no meio).
2. O EXECUTOR grava o campo certo (`power_eq`/`power_gte`/`power_lte`/
   `cost_eq`/`cost_gte`/`cost_lte`) no JSON mas esquece de repassar pro
   `eligible_cards` (aconteceu com `bounce`: o parser já gravava
   `power_eq` desde 15/07, mas o executor só repassava `power_lte`).

**Ao investigar qualquer carta com essas variantes de fraseado**, não
parar depois de achar e consertar 1 mecanismo -- censar a variante
contra o banco inteiro, e para CADA mecanismo que aparecer no resultado,
checar os dois pontos acima separadamente.
