# Comparação: Simulador Oficial (ActV3) × Nossa IA

**Fonte:** `OPTCG_Simulator_Source_Reading.pdf` — Assembly-CSharp.dll decompilada
(GameplayLogicScript, 34.127 linhas, v1.40a, 100% lida via dnSpy).
**Método:** cruzamento dos `ActV3Effect` do `DoV3ActionStep` (lista canônica de
efeitos do simulador) contra as 66 actions do nosso `card_effects_db.json`.
**Resultado original (pré-correção):** 39 efeitos cobertos, 28 ausentes — destes,
~8 valem implementação, o resto é raro/arquétipo-específico/não-essencial.

> **CORRIGIDO em 28/06/2026** (ver [HANDOFF.md](HANDOFF.md)). O cruzamento original
> buscou só por NOME LITERAL no C#, sem checar se a mesma mecânica já existia no
> Python sob outro nome. Re-auditoria item a item contra `decision_engine.py`
> (código citado por linha) encontrou que **4 dos 8 "relevantes" já estavam
> implementados** e que a categorização estava invertida: os "7 médios" (menor
> prioridade no doc original) estão **100% ausentes**, enquanto os "8 relevantes"
> (prioridade alta) já tinham metade pronta. Contagem real: **42 cobertos, 25
> ausentes** — ver tabela corrigida abaixo.
>
> **ATUALIZADO em 28/06/2026** (mesmo dia, depois de implementar): parser
> estendido para `OppNoBlockerThisTurn` (3 cartas: OP11-013, OP12-051,
> ST21-016) e validado o `buff_power_per_count` que já existia no parser sem
> nunca ter tido snapshot/db regenerado (9 cartas afetadas: EB01-014,
> EB01-027, OP01-072, OP01-083, OP06-085, OP09-086, OP12-070, OP16-034,
> P-024). Contagem: **44 cobertos, 23 ausentes**.
>
> **CONCLUÍDO em 28/06/2026** (mesmo dia, segunda rodada — "o restante"):
> `Freeze` (don/stage/card) implementado de verdade (`frozen_next_refresh`/
> `frozen_don_count`, consumidos em `refresh_phase`); `CantPlayAnyCardsFromHand`/
> `CantPlayAnyCharactersToField` no oponente investigado e descartado (0
> cartas reais no banco — exemplo "Imu" do doc original não corresponde a
> carta real); `SaveTargetName`/memória de alvo entre steps implementado
> (`EffectExecutor._last_selected`), resolvendo os 3 residuais de
> `OppNoBlockerThisTurn` (2 reais: OP07-057, OP12-077; OP12-016 fica de fora,
> memória custo→efeito é mecanismo diferente) + o residual de `Freeze`
> (EB02-021) + corrigindo de quebra um bug de target errado pré-existente em
> `buff_power` (48 cartas com o padrão "up to N of your [Tipo] cards gains
> power" caíam em `target='self'` por engano). Contagem final: **47
> cobertos, 6 "médios" ausentes** (nenhum com urgência de meta).

---

## Arquitetura do simulador (referência)

O simulador usa o sistema **ActV3**: cada carta tem `actionV3s: List<ActV3Base>`, onde:
- `proc` (ActV3Proc) = QUANDO/requisitos/custos — equivale aos nossos `trigger` + `conditions` + `costs`
- `steps` (List<ActV3Step>) = sequência de passos — equivale aos nossos `steps`
- `details` = condições IF por passo — equivale ao nosso `conditions` no nível do step (split_then_if)
- `target` = QUEM é alvo — nós embutimos no filtro de cada action
- `effect` (ActV3Effect) = O QUE acontece — equivale à nossa `action`

**Validação importante:** nossa separação trigger/condition/cost/step espelha a
estrutura proc/details/effect do simulador. A arquitetura está alinhada. Os
buracos são de COBERTURA de efeitos, não de modelo.

**Convenções confirmadas pelo source (batem com o nosso engine):**
- `DrawCard_Internal: deck[-1] → hand` → topo do deck = fim da lista (= nosso pop()). ✅
- `MillCard_Internal: deck[-1] → trash` → mill tira do topo (= nosso trash_from_deck_top). ✅
- `MoveDeckCardToBottom: deck[i] → deck[0]` → fundo = início da lista. ✅ (confirma nosso gain_life dest=life_bottom usar insert(0))

---

## BURACOS — efeitos que o simulador tem e nós NÃO (25, corrigido → 6 reais hoje)

### 🔴 Relevantes para a IA — 0 gaps reais (8 originais, todos cobertos/resolvidos em 28/06/2026)

| Efeito (sim) | Status real (verificado no código, 28/06/2026) |
|--------------|--------------------------------------------------|
| ~~DealDamage / TakeDamage~~ | ✅ **JÁ COBERTO** — action `deal_damage` (`decision_engine.py:2400`), trata trigger de vida corretamente |
| ~~ShuffleHandIntoDeck~~ | ✅ **JÁ COBERTO** — `shuffle_hand_into_deck` com `dest='deck'` (`decision_engine.py:2185`) |
| ~~CycleEntireHandToDeckBottom~~ | ✅ **JÁ COBERTO** — mesma action, `dest='deck_bottom'` |
| ~~BuffSelf1KPerXTargets / BuffXPerGivenDon / BuffXPerTopDeckCost~~ | ✅ **JÁ COBERTO** — framework `buff_power_per_count` (`decision_engine.py:1822`), parser correspondente em `gerar_effects_db.py` (commit `4f41178`). Cobre `trash`, `events_in_trash`, `rested_don`, `hand`, `unique_character_names`, `own_characters`. Faltam só as fontes "DON anexado à própria carta" e "custo do topo do deck" (nenhuma carta real encontrada com essas variantes ainda — não bloqueante) |
| ~~OppNoBlockerThisTurn~~ | ✅ **COBERTO** — `lock_opp_blocker_turn` (engine) + parser estendido em 28/06/2026 + memória de alvo entre steps (mesmo dia, 2ª rodada). Das 20 cartas reais: 19 cobertas. Resta só OP12-016 (Rayleigh, alvo = quem recebeu DON!! de um CUSTO — memória custo→efeito, mecanismo diferente, não implementado, 1 carta raro) |
| ~~Freeze (don/stage/card)~~ | ✅ **IMPLEMENTADO em 28/06/2026** — `frozen_next_refresh` (Card) + `frozen_don_count` (GameState), consumidos em `refresh_phase`. 21 cartas cobertas (18 `lock_opp_character_refresh`, 1 `lock_opp_don_refresh`, 2 `lock_self_character_refresh`) |
| ~~CantPlayAnyCardsFromHand~~ (no oponente) | ✅ **INVESTIGADO, 0 cartas reais** — as 18 cartas com "cannot play" no banco são todas auto-aplicadas (custo de ramp de DON, já cobertas por `self_cant_play`). Exemplo "Imu" do doc original não corresponde a carta real do pool |
| ~~CantPlayAnyCharactersToField~~ (no oponente) | ✅ mesma conclusão do item acima |

### 🟡 "Médios" — 6 gaps reais (SaveTargetName resolvido em 28/06/2026)

| Efeito | Confirmação (verificado no código, 28/06/2026) |
|--------|--------------------------------------------------|
| PeekSelfLife / PeekOppLife | nenhuma action equivalente nas 75 do banco |
| TrashAllFaceUpLife | não modelamos face da vida (face-up/down) em lugar nenhum |
| MatchLeaderToBasePower | `set_base_power` só aceita valor FIXO do step (`decision_engine.py:1785`, `int(amount)`) — nunca copia dinamicamente o power de outra carta |
| ~~SaveTargetName / HandSize / Count~~ | ✅ **IMPLEMENTADO em 28/06/2026** — `EffectExecutor._last_selected`, preenchido por `buff_power target='select_filtered'`, consumido por `select_grant_unblockable_turn`/`lock_self_character_refresh` `target='selected'`. Resolveu OP07-057, OP12-077, EB02-021. Também corrigiu um bug de ordem de despacho (sub-parsers não seguem a ordem do texto original) e um bug pré-existente de target errado em `buff_power` (48 cartas com "up to N of your [Tipo] cards gains power" caíam em `target='self'`, agora `select_filtered` com seleção real) |
| ForceOpponent | nenhuma action equivalente (raro, mantido como tal) |
| QueueUpEndOfTurnAction / QueueUpOppMainPhaseAction | nenhuma action equivalente |
| FieldCantAttackLeader | `cannot_attack_self` é OUTRA coisa — trava a própria carta de atacar, não impede atacar o líder especificamente (`decision_engine.py:518`) |

### 🟢 Raros / arquétipo-específico / não-essencial (provavelmente ignorar) — 13

ZoroDon (DON especial do Zoro), RosinanteLeader (leader específico),
TransformToSavedString (transformar carta), AllCharsEffectImmune / EffectImmune
(imunidade — família inteira que não modelamos), CopyTargetsAtEnd,
NoTakeLifeToTurnStart, ActivateAllFilmCharsEndOfTurn (arquétipo Film),
EndOfTurnEqDon, BuffXPerPrevTargets, e variantes de imunidade.

**Nota sobre imunidade:** o simulador tem um sistema inteiro de imunidade
(ImmuneToKO, ImmuneToRemoval, CombatImmune, EffectImmune, ImmuneToStrikes...).
Nós não modelamos NENHUM. É a maior família ausente. Decisão consciente: imunidade
é rara no meta atual e custa muito para modelar (toca todo o combate e remoção).
Registrar como dívida técnica, não atacar agora.

---

## CONDIÇÕES (proc) que o simulador valida e talvez não tenhamos

O `CanUseV3Action` valida ~80 condições. Cruzamento rápido revela algumas que
podem faltar no nosso `_check_conditions` (auditar quando relevante):

- `OppDonXOrMore` / `OppRestedDon` — DON do oponente (já registrado no TODO como buraco)
- `LeaderPowerXOrMore/Zero` — temos leader_power_lte, falta o _gte/zero
- `TrashEventsXOrMore` — temos events_in_trash_gte ✅
- `FacedownLife / FaceupLife` — vida face-up/down (não modelamos face)
- `HasBattledCharacter`, `AnyOppCharacterKOd` — estado de combate do turno
- `CombinedLifeXOrLess` — soma das duas vidas
- `ColorCountOrMore`, `FieldIsOnlyCategory` — composição de campo

A maioria é nicho. Auditar sob demanda, não em varredura.

---

## CONCLUSÃO DA COMPARAÇÃO (corrigida em 28/06/2026)

1. **A arquitetura está certa.** Nosso modelo trigger/condition/cost/step espelha
   o proc/details/effect do simulador. Não há defeito estrutural a corrigir.
   Confirmado de novo numa auditoria por amostragem do cálculo de poder,
   resolução de combate, economia de DON e direção do deck — todos batem com
   o C# oficial, sem bug encontrado no motor de produção.
2. **Implementado em 28/06/2026** (mesmo dia da auditoria): `OppNoBlockerThisTurn`
   tinha o engine pronto mas o parser cobria só 2 de 5 variantes de texto reais —
   estendida a regex em `gerar_effects_db.py` (3 cartas a mais: OP11-013,
   OP12-051, ST21-016; `PERDEU=0`, smoke tests OK). `BuffSelf1KPerXTargets`/
   `BuffXPerGivenDon`/`BuffXPerTopDeckCost` já estava implementado num commit
   anterior (`4f41178`) cujo snapshot nunca tinha sido regenerado/validado —
   feito agora.
3. **Concluído em 28/06/2026** (mesmo dia, segunda rodada — "o restante"):
   `Freeze` (don/stage/card) implementado de verdade; `CantPlayAnyCardsFromHand`/
   `CantPlayAnyCharactersToField` no oponente investigado e descartado (0
   cartas reais); `SaveTargetName`/memória de alvo entre steps implementado,
   resolvendo os 3 residuais de `OppNoBlockerThisTurn` reais (OP07-057,
   OP12-077; OP12-016 fica de fora — memória custo→efeito é outro mecanismo)
   e o residual de `Freeze` (EB02-021). De brinde, corrigiu um bug de ordem
   de despacho no parser (sub-parsers não seguem a ordem do texto original)
   e um bug pré-existente de target errado em `buff_power` (48 cartas).
4. **Os buracos reais restantes são 6, todos "médios" sem urgência de meta:**
   PeekSelfLife/OppLife, TrashAllFaceUpLife, MatchLeaderToBasePower,
   ForceOpponent, QueueUpEndOfTurnAction/OppMainPhase, FieldCantAttackLeader.
   Nenhum exige mudança estrutural grande.
5. **Maior dívida não-atacada: sistema de imunidade** (família inteira ausente).
   Consciente, registrada, fora de escopo atual.