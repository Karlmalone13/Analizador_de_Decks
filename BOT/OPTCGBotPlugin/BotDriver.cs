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

        // Liga/desliga o bot em tempo real (sem reiniciar o jogo nem trocar a
        // DLL) — pra jogar manualmente e printar telas de decisao sem o
        // plugin clicar antes de dar tempo. Checado TODO frame, antes de
        // qualquer leitura de estado do jogo, entao funciona mesmo com o bot
        // pausado no meio de uma acao. Atalho: Shift+B.
        private const KeyCode ToggleKey = KeyCode.B;
        private bool _botEnabled = true;

        private const float ActionCooldown = 1.0f;
        private const int   MaxActionsPerTurn = 25;

        private GameplayLogicScript? _gls;
        private float _cooldown;
        private int   _actionsThisTurn;
        private int   _lastTurnSeen = -1;
        private int   _consecutiveFails;
        private string _lastActionKey = "";
        private int    _sameActionCount;
        private float _heartbeat;
        private string _lastHeartbeatMsg = "";

        // Evita perguntar pro engine de novo a cada tick pela mesma acao
        // pendente (custo opcional sem tela dedicada — ver Update())
        private object? _downsideCheckedFor;

        private void Update()
        {
            bool shiftHeld = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);
            if (shiftHeld && Input.GetKeyDown(ToggleKey))
            {
                _botEnabled = !_botEnabled;
                Plugin.Log.LogWarning($"[Bot] {(_botEnabled ? "ATIVADO" : "DESATIVADO")} (Shift+{ToggleKey})");
                if (_botEnabled)
                    _cooldown = ActionCooldown;   // pausa curta ao reativar, evita agir no mesmo frame
            }

            var gls = FindGls();
            if (gls == null || gls.e_GameStyle != GameStyle.SoloVSelf)
            {
                _cooldown = 1f;
                return;
            }

            // Heartbeat de diagnostico: SEMPRE roda, mesmo com o bot pausado
            // (Shift+B) — e exatamente pra observar estado/decisao numa janela
            // pausada (ex: "downside=True" apareceu quando o Cancel apareceu
            // na tela?) que o toggle existe. So a EXECUCAO de acoes (abaixo)
            // fica condicionada a _botEnabled.
            _heartbeat += Time.deltaTime;
            if (_heartbeat >= 3f)
            {
                _heartbeat = 0f;
                var botPsHb = gls.Lps_Players[BotPlayerIndex];
                string msg = $"[HB] enabled={_botEnabled} state={gls.e_CurrentState} turn={gls.gsv_CurrentGame.iPlayerTurn} " +
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

            if (!_botEnabled)
                return;

            if (_cooldown > 0f)
            {
                _cooldown -= Time.deltaTime;
                return;
            }

            // Escolha de 1o/2o: o estado Start_WaitOnTurnOrder so existe no
            // cliente que GANHOU o dado (WaitOnTurnSelection retorna cedo no
            // perdedor) — se chegou aqui, a escolha e do bot. 50/50 aleatorio
            // de proposito (pedido do usuario 12/07: ver o bot tambem na
            // curva par; decisao estrategica de curva seria logica de deck,
            // que nao vive no plugin).
            if (gls.e_CurrentState == GameplayState.Start_WaitOnTurnOrder)
            {
                bool first = UnityEngine.Random.value < 0.5f;
                Plugin.Log.LogInfo($"[Bot] ganhou o dado: vai de {(first ? "PRIMEIRO" : "SEGUNDO")}");
                gls.ChoiceButtonClicked(first ? ButtonChoiceType.GoFirst : ButtonChoiceType.GoSecond, -1);
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

            // Efeito pendente (On Play do bot, efeito do lider ao tomar dano,
            // etc.) — vale nos DOIS turnos
            if (gls.acaActive != null && !gls.bOpponentResolving && !gls.bForcingOpponentAction)
            {
                var pdBotPs = gls.Lps_Players[BotPlayerIndex];
                bool duringAttack =
                    gls.e_CurrentState == GameplayState.Attack_WaitOnBlocker ||
                    gls.e_CurrentState == GameplayState.Attack_BeforeBlocker ||
                    gls.e_CurrentState == GameplayState.Attack_WaitOnCounters;

                // Oferta de "downside cost" com tela dedicada (botoes Cancel /
                // UseOnPlay|UseV3OnPlay): cliques em cartas sao ignorados ate
                // decidir.
                if (BotExecutor.IsOfferingDownside(gls))
                {
                    if (BotExecutor.PendingActionIsMine(gls, pdBotPs))
                    {
                        bool use = ShouldUseOptionalCost(gls, duringAttack);
                        var btn = !use ? ButtonChoiceType.Cancel
                                : gls.acaActive.UsesV3() ? ButtonChoiceType.UseV3OnPlay
                                : ButtonChoiceType.UseOnPlay;
                        Plugin.Log.LogInfo($"[Bot] downside offer ({(duringAttack ? "reacao" : "proprio turno")}): {(use ? "USAR efeito" : "Cancel")}");
                        gls.ChoiceButtonClicked(btn, -1);
                        _cooldown = 1f;
                    }
                    return;
                }

                // Custo "trash 1 carta da mao" SEM tela dedicada (ex: redirect
                // do lider Teach — "You may trash 1 card..." pula direto pra
                // selecao do alvo do custo, so com Cancel; achado em partida
                // real 07/07 via print do usuario + confirmado no log:
                // downside=False mesmo durante o ataque). Sinal GERAL, valido
                // pra qualquer carta V3 com esse padrao (nao so o Teach): o
                // step atual pede TrashCard (mesmo campo que o jogo usa pra
                // montar o botao "Select N Cards to Trash") e o Cancel esta
                // realmente na tela (ou seja, e opcional). Pergunta pro engine
                // so na 1a vez que essa acao aparece; se recusar, cancela em
                // vez de deixar HandlePendingAction trashar a pior carta da
                // mao automaticamente (o bug reportado: Teach trashava toda
                // vez, mesmo quando nao valia a pena).
                if (!ReferenceEquals(_downsideCheckedFor, gls.acaActive) &&
                    BotExecutor.PendingActionIsMine(gls, pdBotPs) &&
                    BotExecutor.IsOptionalHandTrashCost(gls))
                {
                    _downsideCheckedFor = gls.acaActive;
                    bool use = ShouldUseOptionalCost(gls, duringAttack);
                    Plugin.Log.LogInfo($"[Bot] custo opcional sem tela dedicada ({(duringAttack ? "reacao" : "proprio turno")}): {(use ? "USAR efeito" : "Cancel")}");
                    if (!use)
                    {
                        BotExecutor.CancelPendingAction(gls);
                        _cooldown = 1f;
                        return;
                    }
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
                foreach (var c in BotExecutor.CollectTargetCandidates(swBotPs, swOppPs, gls))
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

            // Mesma acao repetida = o jogo esta recusando silenciosamente
            // (ex: ataque invalido que nao muda o estado) — corta o loop
            string key = $"{action.type}:{action.cardId}:{action.targetId}";
            _sameActionCount = (key == _lastActionKey) ? _sameActionCount + 1 : 0;
            _lastActionKey = key;
            if (_sameActionCount >= 3)
            {
                Plugin.Log.LogWarning($"[Bot] acao {key} repetida {_sameActionCount}x sem efeito — end turn");
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

        // Pergunta pro engine se vale usar um efeito de custo opcional — a
        // MESMA pergunta serve pra tela de oferta dedicada (Cancel/UseOnPlay)
        // e pro custo de trash-da-mao sem tela dedicada (Update()); so muda
        // como a resposta e executada (clicar o botao vs cancelar a acao).
        private bool ShouldUseOptionalCost(GameplayLogicScript gls, bool duringAttack)
        {
            var botPs = gls.Lps_Players[BotPlayerIndex];
            var oppPs = gls.Lps_Players[1 - BotPlayerIndex];
            var attacker = BotExecutor.Attacker(gls);
            var defender = BotExecutor.Defender(gls);
            int atkP = duringAttack && attacker != null ? BotExecutor.PowerOf(gls, attacker, true) : 0;
            int defP = duringAttack && defender != null ? BotExecutor.PowerOf(gls, defender, false) : 0;
            int defId = duringAttack && defender != null ? BotExecutor.UidOf(defender) : 0;
            var dto = GameStateBuilder.Build(botPs, oppPs, gls);
            // Codigo da carta cujo custo opcional esta sendo oferecido (ex:
            // Marcus Mars "you may trash 1 card: K.O. ..."). Sem isso o
            // engine nao tem como checar se o beneficio tem alvo antes de
            // aceitar pagar o custo (achado 09/07, log 19.25.50: bot
            // trashou carta da mao pro Mars sem nenhum alvo elegivel pro K.O.).
            string? actorCode = BotExecutor.ActorCode(gls);
            var resp = EngineClient.IsAlive()
                ? EngineClient.Defense(dto, duringAttack ? "reaction" : "optional", atkP, defP, actorCode, defId)
                : null;
            return resp?.useReaction ?? false;
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
                    var candidates = BotExecutor.CollectTargetCandidates(botPs, oppPs, gls);

                    // Efeito resolvendo DURANTE um ataque (ex: redirect do
                    // Teach)? Passa o contexto — o engine nunca escolhe o alvo
                    // original e prefere quem sobrevive ao golpe.
                    int atkPower = 0, defenderId = 0;
                    var attacker = BotExecutor.Attacker(gls);
                    var defender = BotExecutor.Defender(gls);
                    if (attacker != null && defender != null &&
                        (gls.e_CurrentState == GameplayState.Attack_WaitOnBlocker ||
                         gls.e_CurrentState == GameplayState.Attack_BeforeBlocker ||
                         gls.e_CurrentState == GameplayState.Attack_WaitOnCounters))
                    {
                        atkPower   = BotExecutor.PowerOf(gls, attacker, true);
                        defenderId = BotExecutor.UidOf(defender);
                    }

                    _pendingOrder = EngineClient.ChooseTarget(
                        dto, candidates, BotExecutor.ActorCode(gls), atkPower, defenderId);
                }
            }

            // V3 sem alvos faltando (ex: "Choose 0 Targets") → confirma direto
            // (com o botao de finalize certo: search do topo usa FinalizeTopDeck)
            int remaining = BotExecutor.RemainingV3Targets(gls);
            if (remaining == 0)
            {
                BotExecutor.ConfirmPendingSelection(gls);
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
                BotExecutor.ConfirmPendingSelection(gls);
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
                {
                    _blockerTried = false;
                    // novo ataque = novo counter step; eventos [Counter]
                    // recusados no ataque anterior voltam a ser candidatos
                    BotExecutor.ResetCounterStep();
                }
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
                int defId = defender != null ? BotExecutor.UidOf(defender) : 0;

                var dto = GameStateBuilder.Build(botPs, oppPs, gls);
                var resp = EngineClient.IsAlive()
                    ? EngineClient.Defense(dto, "counter", atkPower, defPower, null, defId)
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
