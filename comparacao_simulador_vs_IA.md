# Comparação: Simulador Oficial (ActV3) × Nossa IA

**Fonte:** `OPTCG_Simulator_Source_Reading.pdf` — Assembly-CSharp.dll decompilada
(GameplayLogicScript, 34.127 linhas, v1.40a, 100% lida via dnSpy).
**Método:** cruzamento dos `ActV3Effect` do `DoV3ActionStep` (lista canônica de
efeitos do simulador) contra as 66 actions do nosso `card_effects_db.json`.
**Resultado:** 39 efeitos cobertos, 28 ausentes — destes, ~8 valem implementação,
o resto é raro/arquétipo-específico/não-essencial para a IA de decisão.

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

## BURACOS — efeitos que o simulador tem e nós NÃO (28)

### 🔴 Relevantes para a IA (vale implementar) — 8

| Efeito (sim) | O que faz | Nossa lacuna |
|--------------|-----------|--------------|
| **DealDamage / TakeDamage** | dano direto à vida (sem combate) | sem action; distinto de attack_life (que trasha) — dano pode disparar trigger de vida |
| **Freeze (don/stage/card)** | `bSkipNextActive` — alvo não desvira na próxima Refresh | temos lock_*_refresh parcial; falta o freeze genérico de DON/Stage |
| **CantPlayAnyCardsFromHand** | trava a mão do oponente no turno | sem action — efeito de trava forte (Imu, control) |
| **CantPlayAnyCharactersToField** | trava jogar characters | sem action |
| **OppNoBlockerThisTurn** | oponente não pode bloquear | sem action — habilita lethal, alto impacto |
| **ShuffleHandIntoDeck** | devolve mão ao deck e embaralha | sem action — arquétipo de reset (ex: Sanji visto no replay) |
| **CycleEntireHandToDeckBottom** | mão inteira ao fundo do deck | sem action |
| **BuffSelf1KPerXTargets / BuffXPerGivenDon / BuffXPerTopDeckCost** | buff dinâmico proporcional | temos buff_power fixo; falta o escalonável (ex: Sanji "+1000 per 5 events in trash" visto no replay) |

### 🟡 Médios (casos específicos, implementar se aparecerem no meta) — 7

| Efeito | O que faz |
|--------|-----------|
| PeekSelfLife / PeekOppLife | ver carta de vida (sem mover) — informação, baixo impacto mecânico |
| TrashAllFaceUpLife | trasha vida face-up (arquétipo específico) |
| MatchLeaderToBasePower | iguala power do Leader a um valor |
| SaveTargetName / HandSize / Count | memória entre passos (efeitos "do mesmo nome que...") |
| ForceOpponent | força ação do oponente (raro) |
| QueueUpEndOfTurnAction / QueueUpOppMainPhaseAction | efeito agendado para fim de turno / main do oponente |
| FieldCantAttackLeader | campo não pode atacar Leader |

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

## CONCLUSÃO DA COMPARAÇÃO

1. **A arquitetura está certa.** Nosso modelo trigger/condition/cost/step espelha
   o proc/details/effect do simulador. Não há defeito estrutural a corrigir.
2. **Os buracos são de cobertura, e são finitos:** 8 efeitos relevantes, ~7 médios,
   ~13 ignoráveis. Não é poço sem fundo.
3. **Os 8 relevantes priorizados:** OppNoBlockerThisTurn e os buffs dinâmicos têm
   maior impacto competitivo (aparecem no meta — Sanji no replay usa buff dinâmico).
   CantPlayFromHand/Field e ShuffleHand são de arquétipos control (Imu).
4. **Maior dívida não-atacada: sistema de imunidade** (família inteira ausente).
   Consciente, registrada, fora de escopo atual.