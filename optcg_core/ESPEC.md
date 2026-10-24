# Especificação do núcleo Rust (`optcg_core`) — PLANO_MOTOR_FORTE, fase A.0

Levantamento do motor Python atual (`scriptis_da_ia/optcg_engine/decision_engine.py`,
24/10/2026), que é o GABARITO da paridade.

## 1. Princípio de arquitetura: REGRAS separadas de DECISÕES

No motor Python as regras chamam o motor de decisão no meio da resolução: 26 métodos do
`DecisionEngine` são chamados de dentro de `EffectExecutor`/`OPTCGMatch`:

- **decisão de fato** (vira PONTO DE DECISÃO no núcleo): `should_use_blocker`,
  `should_use_counter`/`use_counter`, `should_pay_removal_substitute`, escolhas de alvo
  (`_pick_effect_target`), e as famílias do Q: `mulligan`, `block_pos`, `counter_pos`,
  `counter_evento_pos`, `target`, `opcao_efeito`, `pagar_custo`, `descarte`, `busca`,
  `jogar_gratis`, + a jogada principal (`play`/`attack`/`activate`/`attach_don`/`pass`);
- **regra disfarçada de decisão** (vai para as REGRAS do núcleo): `_can_play_card`,
  `_effect_conditions_met`, `_step_condition_currently_holds`, `_char_played_filter_matches`;
- **heurística no meio da regra** (NÃO entra no núcleo; quem decide é a política/busca):
  `avaliar_carta`, `don_opportunity_cost`, `score_attack_target`, `posture`, `stage_worth`...

O núcleo é uma **máquina de estados**: `estado.decisao_pendente()` devolve QUEM decide e as
OPÇÕES LEGAIS; `estado.aplica(opcao)` avança até o próximo ponto de decisão. Assim a busca
(ISMCTS), a rede, um humano ou o motor Python (na paridade) podem dirigir o mesmo jogo.
É o padrão dos simuladores de Hearthstone usados nas competições.

## 2. Estado

Declarado no Python (`dataclass`): `CardData` 25 campos (impressos/derivados da carta),
`Card` 36 (estado da carta em jogo: rested, don_attached, buffs, keywords temporárias,
imunidades, travas "até X"), `GameState` 39 (zonas: leader, deck, hand, field_chars,
field_stage, life, trash; DON: don_deck/available/rested/frozen; turno; travas do turno;
fila de fim de turno; reduções de custo pendentes; informação revelada).

Atributos criados na hora (vistos em 10 partidas): GameState `full_deck_codes`,
`full_deck_plan`, `full_deck_profile`, `self_play_info_hidden`; Card `_am_used_turn`,
`_event_once_marker`, `_own_char_ko_once_marker`, `_passivo_on`. Os de "uma vez por
turno"/passivo são REGRA (entram no núcleo); os de plano/perfil do deck são heurística.

No núcleo (REGRA_DADOS_BINARIOS): cartas como índices numa tabela de dados impressos
(imutável, carregada uma vez) + estado mutável compacto por instância (structs de
números/bitflags); zonas como vetores de índices. Cópia barata (clone de vetores pequenos).

## 3. Fluxo do turno (`OPTCGMatch.play_turn`)

refresh → efeitos reativos do oponente → draw → DON → main (laço de ações até passar)
→ end (fila de fim de turno) → checagem de vitória (inclui `deck_out_win_instead_of_loss`).
Combate (`_execute_attack_inner`): declarar ataque → reações (`on_opp_attack`,
`leader_battle_reactive`, `when_attacking`) → BLOQUEIO (decisão do defensor) →
COUNTER de personagens (decisão) → EVENTO de counter (decisão) → debuff de counter →
comparação de poder → dano (vida/trigger) ou KO → efeitos de KO.

## 4. Efeitos (`card_effects_db.json`)

2.839 cartas (2.542 com efeito): 31 gatilhos, 140 tipos de ação, 88 condições, 34
custos, 95 parâmetros de passo. Ondas por cobertura: 10 ações → 71% das cartas, 20 → 86%,
40 → 95%, 140 → 100%. Ordem de implementação = mais usadas primeiro (lista no plano).

## 5. Teste diferencial (a peça central da paridade)

1. O motor Python joga a partida normalmente e GRAVA, a cada ponto de decisão:
   (estado canônico antes, ponto de decisão, opção escolhida, estado canônico depois).
   "Estado canônico" = serialização determinística e independente de implementação
   (zonas por código de carta + estado de cada instância + DON + travas).
2. O núcleo Rust parte do MESMO estado inicial (mesma ordem de deck), recebe a MESMA
   sequência de escolhas e, depois de cada uma, compara o seu estado canônico com o do
   Python. A primeira divergência é o bug a corrigir (relatório: jogada, carta, campo).
3. Medida de paridade: % de partidas inteiras idênticas e % de passos idênticos, por
   onda de efeitos. O núcleo só passa a decidir algo com paridade ~100%.
4. Fontes: auto-jogo (milhares de partidas, decks variados) + logs reais do banco.

## 6. Pendências da A.0

- Serializador de estado canônico no motor Python (é ele que define a igualdade).
- Gancho de gravação dos pontos de decisão no motor Python (sem mudar decisões).
- Mapa ação → função do `EffectExecutor` (onde está cada uma das 140).
