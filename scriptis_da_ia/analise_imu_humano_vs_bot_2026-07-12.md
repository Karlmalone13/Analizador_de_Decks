# Análise: Imu pilotado pelo humano vs pelo bot (12/07/2026)

Comparação a partir do banco de logs (`logs/parsed/`), a pedido do usuário,
antes do próximo teste ao vivo. Foco: **passividade do bot** ("ganho sem
levar dano nenhum").

## Amostras

- **Humano pilotando Imu (5 partidas)**: 2x vs jogadores online (01/07,
  vs Nami e vs Luffy) + 3x vs o bot pilotando Teach (10/07, 13.35/17.00/21.41).
- **Bot pilotando Imu (12 partidas)**: todas vs o usuário de Teach
  (09/07 a 11/07). Atenção: as 7 de 09/07 são de um engine muito mais
  antigo; a mais representativa do estado atual é a de 11/07 01.36.

## Números (lado Imu de cada grupo)

| métrica                        | humano | bot (ao vivo) | motor-vs-motor* |
|--------------------------------|--------|---------------|-----------------|
| ataques por turno              | 2.03   | 0.88          | 1.28            |
| % de ataques no LÍDER          | 82%    | 42%           | **91%**         |
| dano de vida feito / partida   | 4.2    | 1.3           | —               |
| DON anexado / partida          | 16.4   | ~2 (poucos)** | 0.8/ataque      |
| counters arrancados do opp     | 5.2    | 2.4           | —               |
| turnos (t3+) sem nenhum ataque | 0.0    | 1.5           | —               |
| 1º ataque                      | t3–t4  | t3 (t9 nas de 09/07) | —        |

\* 10 partidas Imu vs Barba Negra BY com o engine de HOJE e informação
completa (auditoria interna) — mostra o que o motor faz quando ENXERGA o
jogo inteiro.
\** o attach do bot NÃO aparece no combat log (o `AttachDonToCard` via
reflection não gera a linha "[You] Attach N Don" que o drag humano gera —
gap de LOGGING, não de comportamento; o session log do engine mostra o DON
caindo junto dos ataques). Mas os counters que o usuário gastou (1000–2000
sempre bastaram) provam que os ataques saíam quase secos.

## Causa raiz principal: retrato incompleto do jogo ao vivo (JÁ CORRIGIDA, não testada)

O DTO do plugin não transmitia o TRASH (`gs.trash=[]` ao vivo). No deck do
Imu isso não é detalhe — é o deck inteiro:

- **Nusjuro (OP13-080, o beater do deck: 16 ataques do humano, 20 DON
  anexados nele)**: com trash>=7 ganha **Rush + imunidade a remoção**
  (passive), com >=10 debuff -2000 ao atacar. Ao vivo o engine via um
  vanilla custo 6/5000 → virava custo de descarte do Kuma (aconteceu 2x
  na partida 01.36) e NUNCA atacava.
- Imunidade dos Celestial Dragons (trash_gte 7) invisível → corpos
  tratados como frágeis.
- [Counter] do Ground Death (trash_gte 10) nunca usável → defesa fraca.
- Progresso do GamePlan (len(trash) >= trash_target) sempre 0.

O motor COM informação completa já joga certo o suficiente: 91% dos
ataques no líder, DON de margem quando sobra. **A maior parte da
passividade era este bug**, não heurística.

## Já corrigido (aguardando validação ao vivo — nada disso está "resolvido" até a partida)

1. **DTO transmite trash + deckCount** (`d191c2f`) — libera Rush/imunidade
   do Nusjuro, Ground Death, GamePlan ao vivo. Exige `BOT\setup_bepinex.bat`.
2. **Política de counter por ganho líquido** (`87ad7b3`) — não gasta
   counter com 4+ vidas; countera com vida baixa escolhendo a carta mais
   barata de pitchar (não o Saturn jogável).
3. **give_don do Kuma** → líder/maior poder (era Shalria 0-poder).
4. **Searchers não milam mais a win-con** (take-choice por `_trash_value`).
5. **Sacrifício próprio pega a carta mais barata** (era a mais valiosa).
6. Bloco 121: líder restado ativa `activate_main` (draw do Imu ao vivo),
   bypass do win-con quando o DON bate, stage não ativa no vácuo, etc.
7. Auditor: checks G/H (defesa), C/D sem falso positivo de combo,
   determinístico (`PYTHONHASHSEED=0`).

## Ainda a corrigir / observar (em ordem de prioridade)

1. **[VALIDAR AO VIVO]** Rodar `setup_bepinex.bat`, jogar 1–2 partidas e
   comparar com esta tabela: % ataque no líder deve subir pra ~80%+,
   Nusjuro deve atacar, counters do usuário devem passar a custar 2000+
   (margem de DON), Ground Death deve counterar com trash>=10.
2. **Volume de ataque (1.28/turno vs 2.03 do humano) mesmo com info
   completa**: o humano constrói board de ataque (Nusjuro/Saturn/Ju Peter
   com DON) e ataca com TUDO; o bot prefere utilitários (Shalria/Kuma) e
   segura. Se após o fix do trash o Nusjuro continuar fora do plano de
   jogo (não jogado da mão / não atacando), investigar `_score_to_play`
   (peso de corpo agressivo vs utilitário) e o gate de ataque de
   personagens (`_generate_and_score_actions`).
3. **Margem de DON menor que a humana** (0.8/ataque vs ~1.3): a margem só
   é paga com `don_livre` após plano+reserva — checar se
   `_don_reserve_for_defense` não está guardando DON demais em turnos em
   que o oponente não ameaça (auditor check novo? "DON ocioso no fim do
   turno com ataque declarado seco").
4. **Mix ao vivo 42% líder**: se persistir após o fix do trash, o problema
   é outro (score de remoção supervalorizado no caminho ao vivo) — mas a
   hipótese atual é que era consequência da cegueira (corpos do Teach
   pareciam remoções fáceis; os próprios ataques no líder pareciam fracos).
5. **Logging**: attach de DON do bot não aparece no combat log → o
   `parse_combat_log.py` subconta agressividade do bot. Se formos comparar
   de novo, ou o plugin loga o attach, ou aceitar o gap.

## Como auditar depois do teste

```bash
cd scriptis_da_ia
python parse_combat_log.py <novo.log> --add-to-db
python audit_antipatterns.py --n 20          # regressão motor-vs-motor
# e comparar o novo parsed com a tabela acima (script em scratchpad da
# sessão 12/07 ou refazer: ataques/turno, % líder, dmg, counters gastos)
```
