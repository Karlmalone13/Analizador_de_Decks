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
