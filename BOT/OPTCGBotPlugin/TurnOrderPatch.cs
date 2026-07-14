using System.Collections.Generic;
using HarmonyLib;

namespace OPTCGBotPlugin
{
    [HarmonyPatch(typeof(GameplayLogicScript), "WaitOnTurnSelection")]
    internal static class TurnOrderPatch
    {
        private const int BotPlayerIndex = 0;

        private static void Postfix(GameplayLogicScript __instance)
        {
            if (__instance == null || __instance.e_GameStyle != GameStyle.SoloVSelf)
                return;
            if (__instance.e_CurrentState != GameplayState.Start_WaitOnTurnOrder)
                return;

            var ps = __instance.Lps_Players[BotPlayerIndex];
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
