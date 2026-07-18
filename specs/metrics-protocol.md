# Protocolo de métricas do bot

## Objetivo

Comparar versões do bot sem misturar três superfícies diferentes:

1. **Estado:** o jogo observado chegou completo ao motor?
2. **Decisão:** dado o mesmo estado, o motor escolheu uma ação de qualidade?
3. **Execução:** a ação escolhida foi concluída no OPTCGSim?
4. **Resultado:** a sequência inteira produziu pressão e vitórias?

Nenhuma métrica isolada deve ser publicada como “eficiência total”. O relatório
mantém as camadas separadas. Um índice composto só pode ser adicionado com pesos
definidos neste arquivo antes da medição.

## Unidades de comparação

- **Cohort ao vivo:** lista explícita de partidas e lado auditado. Não inferir
  humano/bot pelo nome do arquivo.
- **Proxy do motor:** partidas motor-vs-motor com decks, seed, número de jogos e
  commit registrados.
- **Comparação pareada:** preferida. Versões antiga e nova recebem os mesmos
  snapshots pré-ação ou as mesmas seeds/decks.

## Métricas disponíveis nos combat logs atuais

| camada | métrica | definição |
|---|---|---|
| dados | cobertura de snapshot | turnos com snapshot / turnos da partida |
| dados | completude de snapshot | campos `hand`, `board`, `trash`, `life` presentes para os dois lados / campos esperados |
| resultado | ataques por turno | ataques declarados / turnos próprios |
| resultado | ataques no líder | ataques cujo alvo é o líder adversário / ataques |
| resultado | dano por partida | soma de dano causado ao líder / partidas |
| resultado | counters arrancados | quantidade de cartas de counter usadas contra ataques do lado auditado / partidas |
| resultado | turnos passivos | turnos próprios a partir do segundo sem ataque / partidas |
| resultado | primeiro ataque | turno global do primeiro ataque do lado auditado |
| resultado | DON anexado observado | soma dos eventos `attach_don` / ataques; pode subcontar ações do bot |

Ataque sem resultado explícito continua sendo ataque declarado. Alvo no líder é
identificado pelo código ou nome do líder adversário no campo `target`.

## Métricas ainda indisponíveis

- **Fidelidade real do estado:** exige comparar DTO com um snapshot de verdade do
  jogo no mesmo instante. Cobertura/completude apenas detectam campos ausentes.
- **Qualidade ou arrependimento da decisão:** exige snapshot **antes** de cada ação,
  conjunto de ações legais, ação escolhida, scores e avaliação das alternativas.
- **Sucesso de execução:** exige `action_id` compartilhado entre motor, bridge,
  plugin e confirmação do jogo (`proposed`, `sent`, `clicked`, `confirmed` ou
  `failed`).
- **Oportunidades de ataque:** snapshots atuais são de fim de turno; não permitem
  reconstruir com segurança quais personagens podiam atacar antes da ação.
- **DON real do bot:** o attach via reflection pode não aparecer no combat log.

Esses campos devem aparecer como `null` com uma explicação, nunca como zero.

## Instrumentação necessária para shadow replay

Para cada decisão, gravar JSONL com:

```json
{
  "schema": 1,
  "match_id": "...",
  "decision_id": "...",
  "commit": "...",
  "actor": "A",
  "phase": "main",
  "state_before": {},
  "legal_actions": [],
  "chosen_action": {},
  "action_scores": [],
  "execution": {"sent": true, "confirmed": true, "error": null},
  "state_after": {}
}
```

O `state_before` deve ser capturado antes de cada ação, não no fim do turno. A
confirmação deve reutilizar o mesmo `decision_id` em todas as camadas.

## Protocolo estatístico

1. Congelar commit, decks, lados, seeds e cohorts.
2. Usar no mínimo 5 partidas para pre-flight; 20 por matchup para indicação; 50
   por matchup para decisão de tuning.
3. Calcular intervalos bootstrap de 95% por partida, com seed fixa registrada.
4. Comparar versões nos mesmos estados ou seeds.
5. Separar resultado ao vivo de proxy motor-vs-motor.
6. Não declarar melhora quando os intervalos forem inconclusivos.
7. Preservar todos os combat logs via `parse_combat_log.py --add-to-db`.

## Gates iniciais

- Snapshot coverage e completeness devem ser 100% nos novos logs.
- Execução confirmada deve ser pelo menos 95% quando a telemetria existir.
- Para Imu ao vivo pós-fix: pelo menos 1,28 ataques/turno e 80% de ataques no
  líder, sem regressão de win rate no gauntlet.

