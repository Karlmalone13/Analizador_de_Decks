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
        private float _heartbeat;
        private string _lastHeartbeatMsg = "";

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

            // Heartbeat de diagnostico: loga o estado do jogo a cada 3s
            // (so quando muda) para depurar travamentos
            _heartbeat += Time.deltaTime;
            if (_heartbeat >= 3f)
            {
                _heartbeat = 0f;
                var botPsHb = gls.Lps_Players[BotPlayerIndex];
                string msg = $"[HB] state={gls.e_CurrentState} turn={gls.gsv_CurrentGame.iPlayerTurn} " +
                             $"action={gls.gsv_CurrentGame.iPlayerAction} aca={(gls.acaActive != null)} " +
                             $"downside={BotExecutor.IsOfferingDownside(gls)} " +
                             $"mine={(gls.acaActive != null && BotExecutor.PendingActionIsMine(gls, botPsHb))} " +
                             $"actor={BotExecutor.ActorCode(gls) ?? "-"} " +
                             $"oppResolving={gls.bOpponentResolving} forcing={gls.bForcingOpponentAction}";
                if (msg != _lastHeartbeatMsg)
                {
                    _lastHeartbeatMsg = msg;
                    Plugin.Log.LogInfo(msg);
                }
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

            // Efeito pendente (On Play do bot, efeito do lider ao tomar dano,
            // etc.) — vale nos DOIS turnos
            if (gls.acaActive != null && !gls.bOpponentResolving && !gls.bForcingOpponentAction)
            {
                // Oferta de "downside cost" (ex: Teach — trash 1 carta para usar
                // o efeito): botoes Cancel / UseOnPlay; cliques em cartas sao
                // ignorados ate decidir.
                if (BotExecutor.IsOfferingDownside(gls))
                {
                    var dsBotPs = gls.Lps_Players[BotPlayerIndex];
                    if (BotExecutor.PendingActionIsMine(gls, dsBotPs))
                    {
                        bool use;
                        bool duringAttack =
                            gls.e_CurrentState == GameplayState.Attack_WaitOnBlocker ||
                            gls.e_CurrentState == GameplayState.Attack_BeforeBlocker ||
                            gls.e_CurrentState == GameplayState.Attack_WaitOnCounters;

                        if (duringAttack)
                        {
                            // Reacao a ataque (ex: Teach): engine decide se o
                            // ataque e serio o bastante para gastar recurso
                            var attacker = BotExecutor.Attacker(gls);
                            var defender = BotExecutor.Defender(gls);
                            int atkP = attacker != null ? BotExecutor.PowerOf(gls, attacker, true) : 0;
                            int defP = defender != null ? BotExecutor.PowerOf(gls, defender, false) : 0;
                            var dsOppPs = gls.Lps_Players[1 - BotPlayerIndex];
                            var dsDto = GameStateBuilder.Build(dsBotPs, dsOppPs, gls);
                            var resp = EngineClient.IsAlive()
                                ? EngineClient.Defense(dsDto, "reaction", atkP, defP)
                                : null;
                            use = resp?.useReaction ?? false;
                        }
                        else
                        {
                            // Efeito opcional no proprio turno (pos-play):
                            // usa se tiver carta sobrando pro custo
                            use = dsBotPs.Lgo_MyHand != null && dsBotPs.Lgo_MyHand.Count >= 2;
                        }

                        var btn = !use ? ButtonChoiceType.Cancel
                                : gls.acaActive.UsesV3() ? ButtonChoiceType.UseV3OnPlay
                                : ButtonChoiceType.UseOnPlay;
                        Plugin.Log.LogInfo($"[Bot] downside offer ({(duringAttack ? "reacao" : "proprio turno")}): {(use ? "USAR efeito" : "Cancel")}");
                        gls.ChoiceButtonClicked(btn, -1);
                        _cooldown = 1f;
                    }
                    return;
                }
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

            // Deploy com campo cheio: escolhe (via engine) quem substituir
            if (gls.e_CurrentState == GameplayState.Action_SelectingDeploySwap)
            {
                var swBotPs = gls.Lps_Players[BotPlayerIndex];
                var swOppPs = gls.Lps_Players[1 - BotPlayerIndex];

                // So candidatos do proprio campo; engine ordena por menor valor
                var swCandidates = new System.Collections.Generic.List<EngineClient.TargetCandidate>();
                foreach (var c in BotExecutor.CollectTargetCandidates(swBotPs, swOppPs))
                    if (c.zone == "own_board")
                        swCandidates.Add(c);

                var swDto = GameStateBuilder.Build(swBotPs, swOppPs, gls);
                var order = EngineClient.IsAlive()
                    ? EngineClient.ChooseTarget(swDto, swCandidates, "deploy_swap")
                    : null;

                bool done = false;
                if (order != null)
                    foreach (int id in order)
                    {
                        if (BotExecutor.TryDeploySwap(gls, swBotPs, id)) { done = true; break; }
                    }
                if (!done)
                {
                    Plugin.Log.LogWarning("[Bot] deploy swap sem candidato — Cancel");
                    BotExecutor.CancelPendingAction(gls);
                }
                _cooldown = 1f;
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

        // Estado do efeito pendente: tenta candidatos em ordem; confirma/cancela se esgotar
        private object? _pendingRef;
        private int _pendingStep = -1;
        private System.Collections.Generic.List<int>? _pendingOrder;
        private int _pendingAttempt;
        private bool _pendingConfirmTried;

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

            // Novo prompt (ou novo step do mesmo efeito V3)? refaz a ordem
            int step = gls.acaActive.iActionStep;
            if (!ReferenceEquals(_pendingRef, gls.acaActive) || step != _pendingStep)
            {
                _pendingRef = gls.acaActive;
                _pendingStep = step;
                _pendingAttempt = 0;
                _pendingOrder = null;
                _pendingConfirmTried = false;

                if (EngineClient.IsAlive())
                {
                    var dto = GameStateBuilder.Build(botPs, oppPs, gls);
                    var candidates = BotExecutor.CollectTargetCandidates(botPs, oppPs);
                    _pendingOrder = EngineClient.ChooseTarget(dto, candidates, BotExecutor.ActorCode(gls));
                }
            }

            // V3 sem alvos faltando (ex: "Choose 0 Targets") → confirma direto
            int remaining = BotExecutor.RemainingV3Targets(gls);
            if (remaining == 0)
            {
                BotExecutor.ConfirmV3Targets(gls);
                _cooldown = 1f;
                return;
            }

            if (_pendingOrder != null && _pendingAttempt < _pendingOrder.Count)
            {
                int targetId = _pendingOrder[_pendingAttempt];
                _pendingAttempt++;
                BotExecutor.ClickTargetCandidate(gls, botPs, oppPs, targetId);
                _cooldown = 0.8f;
                return;
            }

            // Candidatos esgotados: confirma selecao parcial (V3) uma vez...
            if (!_pendingConfirmTried && gls.acaActive.UsesV3())
            {
                _pendingConfirmTried = true;
                BotExecutor.ConfirmV3Targets(gls);
                _cooldown = 1f;
                return;
            }

            // ...e se ainda travado, cancela
            Plugin.Log.LogWarning("[Bot] efeito pendente sem alvo viavel — Cancel");
            BotExecutor.CancelPendingAction(gls);
            _pendingRef = null;
            _cooldown = 1f;
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
