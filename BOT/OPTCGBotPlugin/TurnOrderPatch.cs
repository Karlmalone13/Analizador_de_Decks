using System.Collections.Generic;
using HarmonyLib;

namespace OPTCGBotPlugin
{
    [HarmonyPatch(typeof(GameplayLogicScript), "WaitOnTurnSelection")]
    internal static class TurnOrderPatch
    {
        private static void Postfix(GameplayLogicScript __instance)
        {
            if (__instance == null || __instance.e_GameStyle != GameStyle.SoloVSelf)
                return;
            if (__instance.e_CurrentState != GameplayState.Start_WaitOnTurnOrder)
                return;

            // Le o MESMO indice que BotDriver usa (Shift+P troca os dois juntos)
            // -- antes este arquivo tinha seu PROPRIO const=0 duplicado, que
            // divergiria silenciosamente do BotDriver assim que o toggle novo
            // fosse usado (achado ao consolidar 14/07).
            var ps = __instance.Lps_Players[BotDriver.BotPlayerIndex];
            var codes = new List<string>();
            foreach (var lista in new[] { ps.Lgo_MyDeck, ps.Lgo_MyHand, ps.Lgo_MyLeader })
            {
                if (lista == null)
                    continue;
                foreach (var go in lista)
                {
                    var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                    if (cls != null && cls.myCard.cardDef != null)
                        codes.Add(cls.myCard.cardDef.cardID);
                }
            }

            bool first = EngineClient.IsAlive() && EngineClient.GoFirst(codes);
            Plugin.Log.LogInfo($"[Bot] turn_order patch codes={codes.Count}: vai de {(first ? "PRIMEIRO" : "SEGUNDO")}");
            __instance.ChoiceButtonClicked(first ? ButtonChoiceType.GoFirst : ButtonChoiceType.GoSecond, -1);
        }
    }
}
