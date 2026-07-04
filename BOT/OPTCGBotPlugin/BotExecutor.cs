using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace OPTCGBotPlugin
{
    // Traduz a acao retornada pelo engine Python em chamadas reais do GLS
    public static class BotExecutor
    {
        private const int MAX_ACTIONS = 20;

        public static void RunTurn(GameplayLogicScript gls, GameStateDto dto)
        {
            // P2 = indice 1 nos arrays internos do GLS
            PlayerState botPs  = gls.Lps_Players[1];
            PlayerState oppPs  = gls.Lps_Players[0];

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

                case "end_turn":
                    gls.EndTurn_Internal();
                    return true;

                default:
                    Plugin.Log.LogWarning($"[Bot] tipo de acao desconhecido: {action.type}");
                    return false;
            }
        }

        private static bool TryPlay(GameplayLogicScript gls, PlayerState botPs, int cardId)
        {
            var go = FindCardInHand(botPs, cardId);
            if (go == null)
            {
                Plugin.Log.LogWarning($"[Bot] play: carta {cardId} nao encontrada na mao");
                return false;
            }

            // Simula o drag da mao para o deploy area usando o metodo interno do GLS
            // O GLS usa go_PendingChoice para saber qual carta foi selecionada
            gls.go_PendingChoice = go;
            gls.DeployCardFromHand(go, false, false, null);
            Plugin.Log.LogInfo($"[Bot] play: {go.GetComponent<CardLogicScript>()?.myCard?.cardDef?.sCode}");
            return true;
        }

        private static bool TryAttack(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs, int attackerId, int targetId)
        {
            var attacker = FindCardOnBoard(botPs, attackerId) ?? FindLeader(botPs, attackerId);
            if (attacker == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: atacante {attackerId} nao encontrado no campo");
                return false;
            }

            // targetId == 0 = lider oponente
            GameObject? target = targetId == 0
                ? (oppPs.Lgo_MyLeader?.Count > 0 ? oppPs.Lgo_MyLeader[0] : null)
                : FindCardOnBoard(oppPs, targetId);

            if (target == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: alvo {targetId} nao encontrado");
                return false;
            }

            gls.go_PendingChoice = attacker;
            gls.StartAttackInternal(attacker, target);
            Plugin.Log.LogInfo($"[Bot] attack: {attackerId} -> {targetId}");
            return true;
        }

        private static GameObject? FindCardInHand(PlayerState ps, int deckUniqueId)
            => ps.Lgo_MyHand?.FirstOrDefault(go =>
                go?.GetComponent<CardLogicScript>()?.myCard?.deckUniqueID == deckUniqueId);

        private static GameObject? FindCardOnBoard(PlayerState ps, int deckUniqueId)
            => ps.Lgo_MyBoard?.FirstOrDefault(go =>
                go?.GetComponent<CardLogicScript>()?.myCard?.deckUniqueID == deckUniqueId);

        private static GameObject? FindLeader(PlayerState ps, int deckUniqueId)
            => ps.Lgo_MyLeader?.FirstOrDefault(go =>
                go?.GetComponent<CardLogicScript>()?.myCard?.deckUniqueID == deckUniqueId);
    }
}
