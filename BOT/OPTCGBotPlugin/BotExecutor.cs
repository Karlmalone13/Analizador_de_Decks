using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace OPTCGBotPlugin
{
    // Traduz a acao retornada pelo engine Python em chamadas reais do GLS.
    //
    // Membros privados do GLS acessados via AccessTools (verificados no decompilado):
    //   private GameObject go_PendingChoice
    //   private void DeployCardFromHand(GameObject, bool, bool, GameObject)
    //   private void StartAttack()
    //   private void HandleMouseClickCardAttackTarget(GameObject, bool)
    // Publicos: EndTurn_Internal(), Lps_Players, gsv_CurrentGame
    public static class BotExecutor
    {
        private const int MAX_ACTIONS = 20;

        private static readonly FieldInfo  _fPendingChoice =
            AccessTools.Field(typeof(GameplayLogicScript), "go_PendingChoice");
        private static readonly MethodInfo _mDeployFromHand =
            AccessTools.Method(typeof(GameplayLogicScript), "DeployCardFromHand");
        private static readonly MethodInfo _mStartAttack =
            AccessTools.Method(typeof(GameplayLogicScript), "StartAttack");
        private static readonly MethodInfo _mClickAttackTarget =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardAttackTarget");

        public static void RunTurn(GameplayLogicScript gls, GameStateDto dto)
        {
            // Bot = lado de baixo (ver AddTurnPatch.BotPlayerIndex)
            PlayerState botPs = gls.Lps_Players[AddTurnPatch.BotPlayerIndex];
            PlayerState oppPs = gls.Lps_Players[1 - AddTurnPatch.BotPlayerIndex];

            for (int i = 0; i < MAX_ACTIONS; i++)
            {
                // Reconstroi DTO com estado atual (pode ter mudado apos ultima acao)
                var current = GameStateBuilder.Build(oppPs, botPs, gls);
                var action  = EngineClient.Decide(current);

                if (action == null || action.type == "end_turn")
                {
                    Plugin.Log.LogInfo("[Bot] end_turn");
                    gls.EndTurn_Internal();
                    return;
                }

                bool ok = Execute(gls, botPs, oppPs, action);
                if (!ok)
                {
                    Plugin.Log.LogWarning($"[Bot] acao {action.type}:{action.cardId} falhou — end_turn seguro");
                    gls.EndTurn_Internal();
                    return;
                }
            }

            Plugin.Log.LogWarning("[Bot] MAX_ACTIONS atingido — end_turn");
            gls.EndTurn_Internal();
        }

        private static bool Execute(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs, BotAction action)
        {
            switch (action.type)
            {
                case "play":
                    return TryPlay(gls, botPs, action.cardId);

                case "attack":
                    return TryAttack(gls, botPs, oppPs, action.cardId, action.targetId);

                default:
                    Plugin.Log.LogWarning($"[Bot] tipo de acao desconhecido: {action.type}");
                    return false;
            }
        }

        private static bool TryPlay(GameplayLogicScript gls, PlayerState botPs, int cardId)
        {
            var go = FindCard(botPs.Lgo_MyHand, cardId);
            if (go == null)
            {
                Plugin.Log.LogWarning($"[Bot] play: carta {cardId} nao encontrada na mao");
                return false;
            }

            // DeployCardFromHand(go_Card, bFromTrigger=false, bRested=false, go_DeployedBy=null)
            _mDeployFromHand.Invoke(gls, new object?[] { go, false, false, null });
            Plugin.Log.LogInfo($"[Bot] play: {CodeOf(go)}");
            return true;
        }

        private static bool TryAttack(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs, int attackerId, int targetId)
        {
            var attacker = FindCard(botPs.Lgo_MyDeploy, attackerId)
                        ?? FindCard(botPs.Lgo_MyLeader, attackerId);
            if (attacker == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: atacante {attackerId} nao encontrado");
                return false;
            }

            // targetId == 0 = lider oponente
            GameObject? target = targetId == 0
                ? (oppPs.Lgo_MyLeader != null && oppPs.Lgo_MyLeader.Count > 0 ? oppPs.Lgo_MyLeader[0] : null)
                : FindCard(oppPs.Lgo_MyDeploy, targetId);

            if (target == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: alvo {targetId} nao encontrado");
                return false;
            }

            // Fluxo real do jogo (mesmo caminho do clique humano):
            // 1. go_PendingChoice = atacante  2. StartAttack()  3. clique no alvo
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
