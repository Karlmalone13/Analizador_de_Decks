"""
decompiled_python
==================
Porte Python fiel do simulador oficial (Assembly-CSharp.dll v1.40a),
extraído via dnSpy. NÃO é usado pelo motor de produção
(scriptis_da_ia/optcg_engine/decision_engine.py) — é material de CONSULTA,
para quando for preciso confirmar a regra exata do jogo sem ler as 34 mil
linhas de C# em `_referencias/simulador-oficial/dnspy-export/`.

Pasta com underscore de propósito (não hífen — hífen não é identificador
Python válido, quebraria o import).

Movido para fora de scriptis_da_ia/optcg_engine/ em 28/06/2026 (auditoria
confirmou zero acoplamento com decision_engine.py — ver HANDOFF.md). Mantido
como pacote Python válido (imports relativos entre estes arquivos continuam
funcionando) só para o caso de algum dia ser útil rodar/testar isoladamente.

Conteúdo:
    enums.py          → CardType, CardColor, CardCategory, StrikeType, etc.
    models.py          → CardDefinition, LiveCard, PlayerState, GameState
    action_system.py   → ActV3Base, ActV3Proc, ActV3Step, ActV3Effect, etc.
    card_power.py       → CardPower(), GetCardCost() (linhas exatas no docstring)
    validators.py       → CanUseV3Action() e afins
    card_queries.py     → card_has_blocker(), card_has_rush(), etc.
    card_loader.py       → CardLoader (carrega CSV em CardDefinition)
"""
