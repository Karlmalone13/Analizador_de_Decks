using System.Collections;
using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;

namespace OPTCGBotPlugin
{
    // Hook em GameStateManager.AddTurn — disparado no inicio de cada turno
    // com o estado completo dos dois jogadores (serializado pelo proprio jogo).
    [HarmonyPatch(typeof(GameStateManager), "AddTurn")]
    public static class AddTurnPatch
    {
        static void Postfix(GameStateManager __instance, PlayerState player1, PlayerState player2, bool isPlayer1TurnStarting)
        {
            // Bot e sempre P2. So age quando e o turno do P2.
            if (isPlayer1TurnStarting)
                return;

            var gls = __instance.gls;
            if (gls == null)
                return;

            // Monta o DTO a partir dos PlayerState vivos do jogo
            var dto = GameStateBuilder.Build(player1, player2, __instance.gls);

            Plugin.Log.LogInfo($"[Bot] Turno {dto.turnNumber} — mao={dto.bot.hand.Count} don={dto.bot.activeDon}");

            if (!EngineClient.IsAlive())
            {
                Plugin.Log.LogWarning("[Bot] Servidor Python nao esta respondendo — passando turno");
                gls.EndTurn_Internal();
                return;
            }

            // Executa acoes em loop ate engine retornar end_turn
            BotExecutor.RunTurn(gls, dto);
        }
    }
}
