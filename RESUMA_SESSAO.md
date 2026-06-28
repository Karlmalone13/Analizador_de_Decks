# RESUMO DA SESSÃO — Auditoria do Parser OPTCG

## Estado final
- `gerar_effects_db.py` real: **1888 → 2017 cards com efeito** (commit `94fe287` já no GitHub, até o lote 8)
- Lotes 9, 10, 11 (cartas 146-209) processados nesta sessão mas **ainda não aplicados ao parser real** — só estão na proposta (`propostas_finais_209.json`)
- **209 de 209 cartas `efeito_real`** mapeadas com proposta de `effects`, nível de confiança, e notas
- Correções de sinal confirmadas por você (13 cards de "give cost" → `debuff_cost`, não buff)

## O que falta fazer (próxima sessão)
1. **Implementar no parser real** o vocabulário ainda pendente (lista abaixo, por volume de uso nas 209)
2. **Aplicar lotes 9-11** — várias correções de sinal e mecânicas novas confirmadas (substitute_removal expandido, lock_opp_cannot_be_rested, on_self_becomes_rested, redirect_attack_target, etc.) ainda não estão no `gerar_effects_db.py`
3. **Rodar `diff_parser.py`** após cada bloco de implementação, igual fizemos a sessão toda — zero regressão é o padrão de qualidade já estabelecido
4. **OP13-082 (Five Elders)** — o card que originou toda essa auditoria, ainda sem efeito
5. Resolver as ~7 cards da lista de "perda parcial" (45 originais) que não chegamos a verificar manualmente uma a uma

## Actions/campos que faltam implementar no código (por volume nas 209)
- `choice` (estrutura, 11 ocorrências) — precisa suporte especial no parser, não é função isolada
- `lock_opp_character_attack` (8) — confirmar se já existe ou se é só `lock_opp_character_refresh`
- `transfer_don` (4), `gain_attack_active` (4), `set_power` (4), `opp_trash_from_hand` (4)
- `rest_opp_don` (3), `buff_power_per_trash` (3), `buff_cost_discount_hand` (3), `return_opp_don` (3)
- `shuffle_deck`, `immune_to_opp_removal`, `mulligan_hand_equal`, `cannot_attack`, `opp_add_from_life_to_hand`, `lock_opp_cannot_be_rested` (2 cada)
- ~25 actions únicas (1 ocorrência cada) — ver `propostas_finais_209.json` para lista completa

## Regra de sinal importante (documentar/lembrar)
- `give [opponent's Character] N power` sem sinal explícito = **SEMPRE debuff** (confirmado por 11+ imagens)
- `give [opponent's Character] N cost` sem sinal explícito = **depende do contexto** (não generalizável) — mas nas 13 cartas revisadas manualmente, sempre foi `debuff_cost` (reduz custo, prepara kill por filtro de custo baixo)
- Custo de `substitute_ko`/`substitute_removal` com power = **SEMPRE debuff no alvo do custo**, mesmo sendo "seu próprio" Leader/Character — é sacrifício, não bônus (confirmado por imagem real: X.Drake OP14-016)

## Observação especial de regra (ST19-003, "Tashigi")
O `[Activate: Main]` dela só funciona no **mesmo turno em que foi jogada** — não é `once_per_turn` recorrente genérico. Campo correto: `conditions: {self_played_this_turn: True}`, sem `once_per_turn`.

## Arquivos desta sessão
- `propostas_finais_209.json` — todas as 209 propostas em formato JSON
- `propostas_completo.py` — código Python fonte das propostas (com notas e confidence)
- `censo_padroes.py` / `censo_padroes.json` — script e resultado do censo estrutural original
- `gerar_effects_db.py` — parser já com lotes 1-8 implementados (commitado)

## Pendências de verificação (baixa prioridade)
- ~7 cards da lista de 45 "perda parcial" nunca verificados individualmente (alta probabilidade de serem falsos positivos, mesmo padrão dos 38 já confirmados)
- `OP05-109`, `OP05-119` — lacunas registradas (mecânicas raras/únicas: "when a Trigger activates" sem outro delimitador; "take an extra turn")