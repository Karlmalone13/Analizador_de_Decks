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
confirmação deve reutilizar o mesmo `decision_id` em todas as camadas. A
implementação usa eventos JSONL append-only: um evento `decision` e eventos
`execution` com status `sent`, `confirmed` ou `failed`. O relatório agrupa os
eventos pelo ID; assim uma queda do plugin não corrompe registros anteriores.

`confirmed` significa que o próximo `PlayerTurn_Action` estável apresentou DTO
diferente do estado anterior. É evidência de execução, mas não prova que todo o
efeito semântico esperado ocorreu; essa auditoria exige comparação específica de
transição por tipo de ação.

## Protocolo estatístico

1. Congelar commit, decks, lados, seeds e cohorts.
2. Usar no mínimo 5 partidas para pre-flight; 20 por matchup para indicação; 50
   por matchup para decisão de tuning.
3. Calcular intervalos bootstrap de 95% por partida, com seed fixa registrada.
4. Comparar versões nos mesmos estados ou seeds.
5. Separar resultado ao vivo de proxy motor-vs-motor.
6. Não declarar melhora quando os intervalos forem inconclusivos.
7. Preservar todos os combat logs via `parse_combat_log.py --add-to-db`.

## Decisoes auxiliares, futuro e contrafactual

O mesmo envelope cobre `main`, `mulligan`, `blocker`, `counter`, `trigger`,
`reaction`, `optional` e `target`. Decisoes auxiliares ficam `pending` ate o
plugin observar uma mudanca real no DTO; `sent` sozinho nao conta como sucesso.
O evento `outcome` registra `win/loss/draw/aborted` e o estado final.

- Resultado futuro: deltas de vida, mao, campo e DON apos 1, 3 e 5 decisoes.
  E correlacao temporal, nao causalidade.
- Arrependimento contrafactual: somente alternativas presentes em
  `search_values` e realmente simuladas pelo motor no mesmo snapshot.
- Falha operacional vem de `failed`. Erro estrategico exige execucao confirmada
  e valor futuro ou contrafactual ruim.
- Acoes apenas enumeradas ou pontuadas nao sao chamadas de contrafactuais.

O plano canonico de coleta esta em
`scriptis_da_ia/metrics/evidence_collection_plan.json`: 5 partidas ao vivo para
pre-flight, 20 para indicacao e 50 self-play por matchup com seed fixa.

## Gates iniciais

O relatorio gera alertas estruturados para: execucao abaixo de 95%, estado
posterior abaixo de 95%, outcome ausente, decisoes pendentes, timeout, commits
misturados, baixa cobertura contrafactual, latencia p95 acima de 3000 ms e
transicao semantica incoerente. Schema desconhecido, JSONL invalido, sessoes ou
IDs duplicados tambem falham. `gate_status` e `pass`, `warning` ou `fail`.

Confirmacao semantica da Main Phase verifica a mudanca esperada por tipo:
`play` sai da mao, `attack` resta o atacante, `attach_don` aumenta DON,
`activate` marca uso e `end_turn` muda turno. Fluxos auxiliares continuam sem
assertiva semantica especifica ate haver evidencia ao vivo suficiente.

O `match_id` nasce no mulligan e permanece fixo ate `outcome`; horizontes
1/3/5 nunca atravessam partidas. Cada decisao registra `latency_ms`; timeout e
latencia sao metricas separadas de qualidade estrategica.

`collect_latest_match.py` so confirma sucesso depois de localizar no
`logs/index.json` a entrada criada por `parse_combat_log.py`, verificar raw,
parsed e decks e validar o nome canonico
`Lider-Cores_x_Lider-Cores_timestamp`. Exit code zero sozinho nao basta.

Comparacao entre versoes usa `compare_bot_reports.py`; manifests/seeds
incompativeis geram aviso e retorno nao-zero. Mesmo sem aviso, causalidade exige
os mesmos snapshots ou seeds/decks.

- Snapshot coverage e completeness devem ser 100% nos novos logs.
- Execução confirmada deve ser pelo menos 95% quando a telemetria existir.
- Para Imu ao vivo pós-fix: pelo menos 1,28 ataques/turno e 80% de ataques no
  líder, sem regressão de win rate no gauntlet.
