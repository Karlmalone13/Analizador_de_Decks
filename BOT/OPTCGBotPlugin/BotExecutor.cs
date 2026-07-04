using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace OPTCGBotPlugin
{
    // Executa acoes usando o MESMO caminho do clique humano — o jogo valida
    // e paga custos por conta propria (TapDon no Deploy, etc.):
    //
    //   play:   HandleMouseClickCardDuringActionState(card) -> ChoiceButtonClicked(Deploy)
    //           (Deploy() paga o custo via TapDon e chama DeployCardFromHand)
    //   attack: go_PendingChoice = atacante -> StartAttack() -> HandleMouseClickCardAttackTarget(alvo)
    //   end:    bConfirmEnd = false; ChoiceButtonClicked(EndTurn)
    public static class BotExecutor
    {
        private static readonly FieldInfo _fPendingChoice =
            AccessTools.Field(typeof(GameplayLogicScript), "go_PendingChoice");
        private static readonly MethodInfo _mClickDuringAction =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardDuringActionState");
        private static readonly MethodInfo _mStartAttack =
            AccessTools.Method(typeof(GameplayLogicScript), "StartAttack");
        private static readonly MethodInfo _mClickAttackTarget =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardAttackTarget");

        public static bool ExecuteOne(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs,
                                      BotAction action, GameStateDto dto)
        {
            switch (action.type)
            {
                case "play":
                    return TryPlay(gls, botPs, action.cardId);
                case "attack":
                    return TryAttack(gls, botPs, oppPs, action.cardId, action.targetId, dto);
                default:
                    Plugin.Log.LogWarning($"[Bot] tipo de acao desconhecido: {action.type}");
                    return false;
            }
        }

        public static void EndTurn(GameplayLogicScript gls)
        {
            gls.bConfirmEnd = false;   // pula o dialogo de confirmacao
            gls.ChoiceButtonClicked(ButtonChoiceType.EndTurn, -1);
        }

        private static bool TryPlay(GameplayLogicScript gls, PlayerState botPs, int cardId)
        {
            var go = FindCard(botPs.Lgo_MyHand, cardId);
            if (go == null)
            {
                Plugin.Log.LogWarning($"[Bot] play: carta {cardId} nao encontrada na mao");
                return false;
            }

            // Caminho do clique humano: seleciona a carta (o jogo valida custo
            // e adiciona a opcao Deploy + seta go_PendingChoice)...
            _mClickDuringAction.Invoke(gls, new object[] { go });

            // ...e confirma se o jogo aceitou a selecao
            var pending = _fPendingChoice.GetValue(gls) as GameObject;
            if (pending != go)
            {
                Plugin.Log.LogWarning($"[Bot] play: jogo recusou {CodeOf(go)} (custo? restricao?)");
                return false;
            }

            gls.ChoiceButtonClicked(ButtonChoiceType.Deploy, -1);
            Plugin.Log.LogInfo($"[Bot] play: {CodeOf(go)}");
            return true;
        }

        private static bool TryAttack(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs,
                                      int attackerId, int targetId, GameStateDto dto)
        {
            // Regra do jogo (mesma validacao do FindPossibleCardActions):
            // sem ataque no turno 1 do jogo
            if (gls.gsv_CurrentGame.iTurnNumber <= 1)
            {
                Plugin.Log.LogInfo("[Bot] attack: turno 1 — nao pode atacar");
                return false;
            }

            var attacker = FindCard(botPs.Lgo_MyDeploy, attackerId);
            // Lider: deckUniqueID pode ser -1/0 — compara com o uid que NOS
            // enviamos no DTO (lido do mesmo objeto)
            if (attacker == null && dto.bot.leader != null && dto.bot.leader.deckUniqueId == attackerId
                && botPs.Lgo_MyLeader != null && botPs.Lgo_MyLeader.Count > 0)
            {
                attacker = botPs.Lgo_MyLeader[0];
            }
            if (attacker == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: atacante {attackerId} nao encontrado");
                return false;
            }

            // Validacao propria (replica do FindPossibleCardActions): rested/summon sick
            var acls = attacker.GetComponent<CardLogicScript>();
            if (acls == null || acls.myCard.bTapped)
            {
                Plugin.Log.LogWarning("[Bot] attack: atacante rested");
                return false;
            }

            GameObject? target = null;
            if (targetId == 0 || (dto.opp.leader != null && dto.opp.leader.deckUniqueId == targetId))
            {
                if (oppPs.Lgo_MyLeader != null && oppPs.Lgo_MyLeader.Count > 0)
                    target = oppPs.Lgo_MyLeader[0];
            }
            else
            {
                target = FindCard(oppPs.Lgo_MyDeploy, targetId);
            }

            if (target == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: alvo {targetId} nao encontrado");
                return false;
            }

            // Fluxo real: go_PendingChoice -> StartAttack() -> clique no alvo
            _fPendingChoice.SetValue(gls, attacker);
            _mStartAttack.Invoke(gls, null);
            _mClickAttackTarget.Invoke(gls, new object[] { target, false });
            Plugin.Log.LogInfo($"[Bot] attack: {CodeOf(attacker)} -> {CodeOf(target)}");
            return true;
        }

        private static GameObject? FindCard(List<GameObject>? list, int deckUniqueId)
        {
            if (list == null) return null;
            foreach (var go in list)
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null && cls.myCard.deckUniqueID == deckUniqueId)
                    return go;
            }
            return null;
        }

        private static string CodeOf(GameObject go)
        {
            var cls = go.GetComponent<CardLogicScript>();
            return cls != null && cls.myCard.cardDef != null ? cls.myCard.cardDef.cardID : "?";
        }
    }
}
