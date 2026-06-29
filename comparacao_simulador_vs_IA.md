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
> P-024). Contagem agora: **44 cobertos, 23 ausentes** (7 "médios" + `Freeze`
> + `CantPlay*` no oponente + 3 residuais de `OppNoBlockerThisTurn` que
> precisam de memória de alvo entre steps, mesma raiz de `SaveTargetName`).

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

## BURACOS — efeitos que o simulador tem e nós NÃO (25, corrigido)

### 🔴 Relevantes para a IA — 4 gaps reais + 1 parcial (de 8 originais — 3 já cobertos)

| Efeito (sim) | Status real (verificado no código, 28/06/2026) |
|--------------|--------------------------------------------------|
| ~~DealDamage / TakeDamage~~ | ✅ **JÁ COBERTO** — action `deal_damage` (`decision_engine.py:2400`), trata trigger de vida corretamente |
| ~~ShuffleHandIntoDeck~~ | ✅ **JÁ COBERTO** — `shuffle_hand_into_deck` com `dest='deck'` (`decision_engine.py:2185`) |
| ~~CycleEntireHandToDeckBottom~~ | ✅ **JÁ COBERTO** — mesma action, `dest='deck_bottom'` |
| ~~BuffSelf1KPerXTargets / BuffXPerGivenDon / BuffXPerTopDeckCost~~ | ✅ **JÁ COBERTO** — framework `buff_power_per_count` (`decision_engine.py:1822`), parser correspondente em `gerar_effects_db.py` (commit `4f41178`). Cobre `trash`, `events_in_trash`, `rested_don`, `hand`, `unique_character_names`, `own_characters`. Faltam só as fontes "DON anexado à própria carta" e "custo do topo do deck" (nenhuma carta real encontrada com essas variantes ainda — não bloqueante) |
| ~~OppNoBlockerThisTurn~~ | ✅ **JÁ COBERTO (maior parte)** — `lock_opp_blocker_turn` (engine) + parser estendido em 28/06/2026. Das 20 cartas reais com "cannot activate Blocker": 17 cobertas (9 `lock_opp_blocker_battle`, 5 `lock_opp_blocker_turn`, 3 `select_grant_unblockable_turn`). Restam 3 (OP07-057, OP12-016, OP12-077) que exigem "lembrar o alvo selecionado num step anterior" — ver gap `SaveTargetName` abaixo, mesma raiz |
| **Freeze (don/stage/card)** | ❌ **GAP REAL** — `lock_opp_character_refresh`/`lock_opp_don_refresh`/`lock_self_character_refresh` são reconhecidos mas o próprio código documenta: "ainda não tem lógica de refresh implementada" (`decision_engine.py:1722`) |
| **CantPlayAnyCardsFromHand** (no oponente) | ❌ **GAP REAL** — `self_cant_play` só seta a flag em `me.*` (`decision_engine.py:2173`), nunca no oponente |
| **CantPlayAnyCharactersToField** (no oponente) | ❌ **GAP REAL** — mesma raiz do item acima |

### 🟡 "Médios" — na verdade 7 gaps reais, 100% ausentes (categorização original estava invertida)

| Efeito | Confirmação (verificado no código, 28/06/2026) |
|--------|--------------------------------------------------|
| PeekSelfLife / PeekOppLife | nenhuma action equivalente nas 75 do banco |
| TrashAllFaceUpLife | não modelamos face da vida (face-up/down) em lugar nenhum |
| MatchLeaderToBasePower | `set_base_power` só aceita valor FIXO do step (`decision_engine.py:1785`, `int(amount)`) — nunca copia dinamicamente o power de outra carta |
| SaveTargetName / HandSize / Count | não existe memória entre steps na engine. Mesma raiz do gap restante de `OppNoBlockerThisTurn` (OP07-057, OP12-016, OP12-077 — "select X, X ganha +2000 power, então se X atacar, oponente não bloqueia") |
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
3. **Os buracos reais restantes (verificados por código) são 9, não 15:**
   `Freeze` funcional, `CantPlayAnyCardsFromHand`/`CantPlayAnyCharactersToField`
   direcionado ao oponente, 3 cartas residuais de `OppNoBlockerThisTurn`
   (precisam de "memória de alvo entre steps") + os 7 "médios" (categorização
   original invertida — são os que estão 100% ausentes, não os "relevantes").
   Nenhum exige mudança estrutural grande; nenhum tem urgência de meta hoje.
4. **Maior dívida não-atacada: sistema de imunidade** (família inteira ausente).
   Consciente, registrada, fora de escopo atual.