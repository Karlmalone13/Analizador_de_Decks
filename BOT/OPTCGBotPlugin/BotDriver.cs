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

            // Mulligan da mao inicial: no SoloVSelf cada lado decide em sequencia,
            // controlado por iPlayerAction (CurrentPlayer = Lps_Players[iPlayerAction])
            if (gls.e_CurrentState == GameplayState.Start_WaitOnMulliganChoice)
            {
                if (gls.gsv_CurrentGame.iPlayerAction == BotPlayerIndex)
                {
                    var mulBotPs = gls.Lps_Players[BotPlayerIndex];
                    var mulDto = GameStateBuilder.Build(mulBotPs, gls.Lps_Players[1 - BotPlayerIndex], gls);
                    bool mull = EngineClient.IsAlive() && EngineClient.ShouldMulligan(mulDto.bot.hand);
                    Plugin.Log.LogInfo($"[Bot] mao inicial: {(mull ? "MULLIGAN" : "KEEP")}");
                    gls.ChoiceButtonClicked(
                        mull ? ButtonChoiceType.StartingHand_Mulligan : ButtonChoiceType.StartingHand_Keep, -1);
                    _cooldown = 1f;
                }
                return;
            }

            // Efeito pendente pedindo alvo (On Play do bot, efeito do lider ao
            // tomar dano, etc.) — vale nos DOIS turnos
            if (gls.acaActive != null && !gls.bOpponentResolving && !gls.bForcingOpponentAction
                && !BotExecutor.IsOfferingDownside(gls))
            {
                HandlePendingAction(gls);
                return;
            }

            // Turno do humano: bot pode precisar DEFENDER (blocker/counter/trigger)
            if (gls.gsv_CurrentGame.iPlayerTurn != BotPlayerIndex)
            {
                HandleDefense(gls);
                return;
            }

            // Fases de inicio de turno: clica Draw Card / Draw Don sozinho.
            // Os botoes ESPERAM nos estados *Wait (PlayerDrawPhase/PlayerDonPhase
            // adicionam o choice e mudam para DrawCardWait/DrawDonWait).
            if (gls.e_CurrentState == GameplayState.PlayerTurn_DrawCardWait)
            {
                gls.ChoiceButtonClicked(ButtonChoiceType.DrawCard, -1);
                _cooldown = 0.5f;
                return;
            }
            if (gls.e_CurrentState == GameplayState.PlayerTurn_DrawDonWait)
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

        // Estado da defesa: evita loop se o blocker escolhido for recusado pelo jogo
        private GameplayState _lastDefenseState;
        private bool _blockerTried;

        // Estado do efeito pendente: tenta candidatos em ordem; Cancel se esgotar
        private object? _pendingRef;
        private System.Collections.Generic.List<int>? _pendingOrder;
        private int _pendingAttempt;

        // Efeito pendente (acaActive) pedindo selecao de alvo. O engine ordena
        // os candidatos; clicamos um por tick — o jogo ignora cliques invalidos,
        // entao um "nao avancou" vira tentativa do proximo da lista.
        private void HandlePendingAction(GameplayLogicScript gls)
        {
            var botPs = gls.Lps_Players[BotPlayerIndex];
            var oppPs = gls.Lps_Players[1 - BotPlayerIndex];

            // Efeito do humano? nao toca (ele clica os proprios prompts)
            if (!BotExecutor.PendingActionIsMine(gls, botPs))
                return;

            // Novo prompt? busca a ordem de preferencia no engine
            if (!ReferenceEquals(_pendingRef, gls.acaActive))
            {
                _pendingRef = gls.acaActive;
                _pendingAttempt = 0;
                _pendingOrder = null;

                if (EngineClient.IsAlive())
                {
                    var dto = GameStateBuilder.Build(botPs, oppPs, gls);
                    var candidates = BotExecutor.CollectTargetCandidates(botPs, oppPs);
                    _pendingOrder = EngineClient.ChooseTarget(dto, candidates, BotExecutor.ActorCode(gls));
                }
            }

            if (_pendingOrder == null || _pendingAttempt >= _pendingOrder.Count)
            {
                // Sem ordem do engine ou candidatos esgotados: tenta cancelar
                Plugin.Log.LogWarning("[Bot] efeito pendente sem alvo viavel — Cancel");
                BotExecutor.CancelPendingAction(gls);
                _pendingRef = null;
                _cooldown = 1f;
                return;
            }

            int targetId = _pendingOrder[_pendingAttempt];
            _pendingAttempt++;
            BotExecutor.ClickTargetCandidate(gls, botPs, oppPs, targetId);
            _cooldown = 0.8f;
        }

        // Defesa quando o HUMANO ataca o bot. Durante o blocker/counter step o
        // jogo poe iPlayerAction no DEFENSOR (SetupBlockerPhase alterna o indice),
        // entao so agimos quando iPlayerAction == BotPlayerIndex.
        private void HandleDefense(GameplayLogicScript gls)
        {
            var st = gls.e_CurrentState;
            if (st != _lastDefenseState)
            {
                _lastDefenseState = st;
                if (st == GameplayState.Attack_WaitOnBlocker)
                    _blockerTried = false;
            }

            bool actionIsMine = gls.gsv_CurrentGame.iPlayerAction == BotPlayerIndex;

            // ── Blocker step ──────────────────────────────────────────────
            if (st == GameplayState.Attack_WaitOnBlocker && actionIsMine)
            {
                var botPs = gls.Lps_Players[BotPlayerIndex];
                var oppPs = gls.Lps_Players[1 - BotPlayerIndex];
                var attacker = BotExecutor.Attacker(gls);
                var defender = BotExecutor.Defender(gls);
                int atkPower = attacker != null ? BotExecutor.PowerOf(gls, attacker, true) : 0;
                int defPower = defender != null ? BotExecutor.PowerOf(gls, defender, false) : 0;

                var dto = GameStateBuilder.Build(botPs, oppPs, gls);
                var resp = EngineClient.IsAlive()
                    ? EngineClient.Defense(dto, "blocker", atkPower, defPower)
                    : null;

                if (resp != null && resp.blockerId != 0 && !_blockerTried)
                {
                    _blockerTried = true;   // se o jogo recusar, proximo tick vai de NoBlocker
                    if (!BotExecutor.TryBlock(gls, botPs, resp.blockerId))
                        BotExecutor.NoBlocker(gls);
                }
                else
                {
                    BotExecutor.NoBlocker(gls);
                }
                _cooldown = 1f;
                return;
            }

            // ── Counter step ──────────────────────────────────────────────
            if (st == GameplayState.Attack_WaitOnCounters && actionIsMine)
            {
                var botPs = gls.Lps_Players[BotPlayerIndex];
                var oppPs = gls.Lps_Players[1 - BotPlayerIndex];
                var attacker = BotExecutor.Attacker(gls);
                var defender = BotExecutor.Defender(gls);
                int atkPower = attacker != null ? BotExecutor.PowerOf(gls, attacker, true) : 0;
                int defPower = defender != null ? BotExecutor.PowerOf(gls, defender, false) : 0;

                var dto = GameStateBuilder.Build(botPs, oppPs, gls);
                var resp = EngineClient.IsAlive()
                    ? EngineClient.Defense(dto, "counter", atkPower, defPower)
                    : null;

                BotExecutor.PlayCounters(gls, botPs,
                    resp?.counterIds ?? new System.Collections.Generic.List<int>());
                _cooldown = 1f;
                return;
            }

            // ── Trigger step ──────────────────────────────────────────────
            // (dano na vida do bot durante o turno do humano = trigger e do bot)
            if (st == GameplayState.Life_ActivateTrigger || st == GameplayState.Life_DoubleTriggering)
            {
                var botPs = gls.Lps_Players[BotPlayerIndex];
                var oppPs = gls.Lps_Players[1 - BotPlayerIndex];
                string? code = BotExecutor.TriggerCardCode(gls);

                var dto = GameStateBuilder.Build(botPs, oppPs, gls);
                var resp = EngineClient.IsAlive()
                    ? EngineClient.Defense(dto, "trigger", 0, 0, code)
                    : null;

                BotExecutor.ResolveTrigger(gls, resp?.useTrigger ?? false);
                _cooldown = 1f;
                return;
            }
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
