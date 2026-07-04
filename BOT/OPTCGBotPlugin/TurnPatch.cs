using HarmonyLib;

namespace OPTCGBotPlugin
{
    // Hook em GameStateManager.AddTurn — disparado no inicio de cada turno
    // com o estado completo dos dois jogadores.
    //
    // "___gls" = injecao de campo privado do Harmony (GameStateManager.gls e private).
    [HarmonyPatch(typeof(GameStateManager), "AddTurn")]
    public static class AddTurnPatch
    {
        static void Postfix(PlayerState player1, PlayerState player2, bool isPlayer1TurnStarting,
                            GameplayLogicScript ___gls)
        {
            // Bot e sempre P2. So age quando e o turno do P2.
            if (isPlayer1TurnStarting)
                return;

            if (___gls == null)
                return;

            var dto = GameStateBuilder.Build(player1, player2, ___gls);

            Plugin.Log.LogInfo($"[Bot] Turno {dto.turnNumber} — mao={dto.bot.hand.Count} don={dto.bot.activeDon}");

            if (!EngineClient.IsAlive())
            {
                Plugin.Log.LogWarning("[Bot] Servidor Python nao esta respondendo — passando turno");
                ___gls.EndTurn_Internal();
                return;
            }

            // Executa acoes em loop ate engine retornar end_turn
            BotExecutor.RunTurn(___gls, dto);
        }
    }
}
