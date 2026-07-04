using UnityEngine;

namespace OPTCGBotPlugin
{
    // Driver principal do bot: MonoBehaviour que roda a cada frame.
    //
    // Em vez de hookear AddTurn (que dispara em PlayerTurn_Start, ANTES do
    // untap/draw/don), o driver espera o jogo chegar em PlayerTurn_Action
    // ocioso (sem acoes pendentes) e executa UMA acao por vez, com cooldown
    // entre acoes para as animacoes e o state machine resolverem.
    public class BotDriver : MonoBehaviour
    {
        // Lado do bot em Lps_Players: 0 = "You" = baixo (LoadMyDeck)
        public const int BotPlayerIndex = 0;

        private const float ActionCooldown = 1.0f;
        private const int   MaxActionsPerTurn = 25;

        private GameplayLogicScript? _gls;
        private float _cooldown;
        private int   _actionsThisTurn;
        private int   _lastTurnSeen = -1;
        private int   _consecutiveFails;

        private void Update()
        {
            if (_cooldown > 0f)
            {
                _cooldown -= Time.deltaTime;
                return;
            }

            var gls = FindGls();
            if (gls == null || gls.e_GameStyle != GameStyle.SoloVSelf)
            {
                _cooldown = 1f;
                return;
            }

            // So age no turno do bot
            if (gls.gsv_CurrentGame.iPlayerTurn != BotPlayerIndex)
                return;

            // Fases de inicio de turno: clica Draw Card / Draw Don sozinho
            if (gls.e_CurrentState == GameplayState.PlayerTurn_DrawCard)
            {
                gls.ChoiceButtonClicked(ButtonChoiceType.DrawCard, -1);
                _cooldown = 0.5f;
                return;
            }
            if (gls.e_CurrentState == GameplayState.PlayerTurn_DrawDon)
            {
                gls.ChoiceButtonClicked(ButtonChoiceType.DrawDon, -1);
                _cooldown = 0.5f;
                return;
            }

            // Main Phase: so com o state machine ocioso
            if (gls.e_CurrentState != GameplayState.PlayerTurn_Action)
                return;
            if (gls.acaActive != null || (gls.acaPending != null && gls.acaPending.Count > 0))
                return;

            // Novo turno? reseta contadores
            int turn = gls.gsv_CurrentGame.iTurnNumber;
            if (turn != _lastTurnSeen)
            {
                _lastTurnSeen = turn;
                _actionsThisTurn = 0;
                _consecutiveFails = 0;
                Plugin.Log.LogInfo($"[Bot] Meu turno {turn} comecou");
            }

            if (_actionsThisTurn >= MaxActionsPerTurn)
            {
                Plugin.Log.LogWarning("[Bot] MAX_ACTIONS — end turn");
                BotExecutor.EndTurn(gls);
                _cooldown = ActionCooldown;
                return;
            }

            if (!EngineClient.IsAlive())
            {
                Plugin.Log.LogWarning("[Bot] Servidor Python offline — passando turno");
                BotExecutor.EndTurn(gls);
                _cooldown = ActionCooldown;
                return;
            }

            var botPs = gls.Lps_Players[BotPlayerIndex];
            var oppPs = gls.Lps_Players[1 - BotPlayerIndex];
            var dto   = GameStateBuilder.Build(botPs, oppPs, gls);
            var action = EngineClient.Decide(dto);
            _actionsThisTurn++;

            if (action == null || action.type == "end_turn")
            {
                Plugin.Log.LogInfo("[Bot] end_turn");
                BotExecutor.EndTurn(gls);
                _cooldown = ActionCooldown;
                return;
            }

            bool ok = BotExecutor.ExecuteOne(gls, botPs, oppPs, action, dto);
            if (!ok)
            {
                _consecutiveFails++;
                if (_consecutiveFails >= 2)
                {
                    Plugin.Log.LogWarning("[Bot] 2 falhas seguidas — end turn seguro");
                    BotExecutor.EndTurn(gls);
                }
            }
            else
            {
                _consecutiveFails = 0;
            }

            _cooldown = ActionCooldown;
        }

        private GameplayLogicScript? FindGls()
        {
            if (_gls != null)
                return _gls;
            var go = GameObject.Find("GameplayLogic");
            _gls = go != null ? go.GetComponent<GameplayLogicScript>() : null;
            return _gls;
        }
    }
}
