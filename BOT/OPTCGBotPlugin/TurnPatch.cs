using HarmonyLib;

namespace OPTCGBotPlugin
{
    // Hook em GameStateManager.AddTurn — disparado no inicio de cada turno
    // com o estado completo dos dois jogadores.
    //
    // Lados (verificado no decompilado, GameStartSolo):
    //   Lps_Players[0] = "You"      = lado de BAIXO (LoadMyDeck)    = BOT
    //   Lps_Players[1] = "Opponent" = lado de CIMA  (LoadEnemyDeck) = humano
    // isPlayer1TurnStarting == true → turno do player 0 (baixo) = vez do bot.
    // Igual ao multiplayer: o lado do bot e sempre o de baixo na maquina dele.
    //
    // "___gls" = injecao de campo privado do Harmony (GameStateManager.gls e private).
    [HarmonyPatch(typeof(GameStateManager), "AddTurn")]
    public static class AddTurnPatch
    {
        // Indice do jogador controlado pelo bot em Lps_Players
        public const int BotPlayerIndex = 0;

        static void Postfix(PlayerState player1, PlayerState player2, bool isPlayer1TurnStarting,
                            GameplayLogicScript ___gls)
        {
            // So age quando e o turno do lado do bot (player 0 = baixo)
            bool botTurn = (BotPlayerIndex == 0) ? isPlayer1TurnStarting : !isPlayer1TurnStarting;
            if (!botTurn)
                return;

            if (___gls == null)
                return;

            var botPs = (BotPlayerIndex == 0) ? player1 : player2;
            var oppPs = (BotPlayerIndex == 0) ? player2 : player1;

            var dto = GameStateBuilder.Build(botPs, oppPs, ___gls);

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
