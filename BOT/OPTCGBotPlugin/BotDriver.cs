using System;
using UnityEngine;
using Newtonsoft.Json;

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
        // Lado do bot em Lps_Players: 0 = "You" = baixo (LoadMyDeck), 1 = "Opponent"
        // = cima. Solo vs Self NAO tem tela de cara-ou-coroa (achado real 14/07,
        // usuario confirmou: a opcao de 1o/2o simplesmente nao existe nesse modo —
        // Start_WaitOnTurnOrder so ocorre com um oponente de verdade decidindo o
        // dado). Os dois lados (P1/P2) sao fixos desde o inicio da partida; pra
        // testar o bot indo primeiro OU segundo, e preciso trocar QUAL lado ele
        // controla — daqui o toggle Shift+P abaixo. static (nao const) pra poder
        // mudar em tempo real; TurnOrderPatch.cs le o MESMO valor (nao duplicar).
        public static int BotPlayerIndex = 0;

        // Liga/desliga o bot em tempo real (sem reiniciar o jogo nem trocar a
        // DLL) — pra jogar manualmente e printar telas de decisao sem o
        // plugin clicar antes de dar tempo. Checado TODO frame, antes de
        // qualquer leitura de estado do jogo, entao funciona mesmo com o bot
        // pausado no meio de uma acao. Atalho: Shift+B.
        private const KeyCode ToggleKey = KeyCode.B;
        private bool _botEnabled = true;

        // Troca qual lado (P1/P2) o bot controla — pedido do usuario 14/07, pra
        // poder simular o bot indo primeiro (impar) ou segundo (par) em Solo vs
        // Self. Atalho: Shift+P. Seguro trocar a qualquer momento (o driver le
        // BotPlayerIndex fresco todo frame, nao ha estado preso ao indice antigo).
        private const KeyCode SwapSideKey = KeyCode.P;

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
        private BotAction? _pendingTelemetryAction;
        private string _pendingTelemetryState = "";
        private string _pendingTargetDecisionId = "";
        private bool _outcomeReported;
        private float _collectionPoll;
        private string _collectionMessage = "";
        private string _collectionState = "";
        private bool _collectionConfirmationLogged;
        private sealed class PendingAuxTelemetry
        {
            public string id = "";
            public string state = "";
        }
        private readonly System.Collections.Generic.List<PendingAuxTelemetry> _pendingAux = new();

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
            if (shiftHeld && Input.GetKeyDown(SwapSideKey))
            {
                BotPlayerIndex = 1 - BotPlayerIndex;
                Plugin.Log.LogWarning($"[Bot] agora controla P{BotPlayerIndex + 1} (Shift+{SwapSideKey})");
            }

            var gls = FindGls();
            if (gls == null || gls.e_GameStyle != GameStyle.SoloVSelf)
            {
                _cooldown = 1f;
                return;
            }

            if (gls.e_CurrentState == GameplayState.GameOver && !_outcomeReported)
            {
                _outcomeReported = true;
                // Achado 19/07 (leitura do decompilado GameplayLogicScript.cs):
                // o combat log com o desfecho completo ("Downloaded the Combat
                // Log!"/"GameOver") SO existe se DownloadLogLines() for chamado
                // -- isso normalmente acontece so quando o jogador clica o
                // botao "Download Log" (go_DownloadLog) na tela de fim de jogo.
                // O bot nunca clicava nele, entao o coletor so via a copia de
                // CombatLogs/AutoSaved (SaveMyLogLines, autosave continuo que
                // corta bem antes do fim -- confirmado em 5/5 logs do bot que
                // chegaram perto do desfecho, ver HANDOFF bloco 285). Chamando
                // o metodo PUBLICO direto (sem precisar clicar UI) escreve o
                // log cheio em CombatLogs/<timestamp>.log ANTES do outcome.
                try { gls.DownloadLogLines(); }
                catch (Exception ex) { Plugin.Log.LogWarning($"[Bot] DownloadLogLines falhou: {ex.Message}"); }
                bool youWon = gls.go_YouWin != null && gls.go_YouWin.activeSelf;
                bool botWon = BotPlayerIndex == 0 ? youWon : !youWon;
                var finalDto = GameStateBuilder.Build(
                    gls.Lps_Players[BotPlayerIndex], gls.Lps_Players[1 - BotPlayerIndex], gls);
                EngineClient.ReportOutcome(botWon ? "win" : "loss", finalDto,
                                           $"GameOver; bot=P{BotPlayerIndex + 1}");
                _collectionMessage = "Salvando log no banco...";
                _collectionState = "running";
                return;
            }
            if (gls.e_CurrentState == GameplayState.GameOver && _outcomeReported)
            {
                _collectionPoll -= Time.deltaTime;
                if (_collectionPoll <= 0f)
                {
                    _collectionPoll = 1f;
                    var collection = EngineClient.GetCollectionStatus();
                    if (collection != null)
                    {
                        _collectionState = collection.status;
                        _collectionMessage = collection.status == "success"
                            ? "LOG SALVO NO BANCO"
                            : collection.status == "failed"
                                ? $"FALHA AO SALVAR LOG: {collection.message}"
                                : collection.message;
                        if (collection.status == "success" && !_collectionConfirmationLogged)
                        {
                            _collectionConfirmationLogged = true;
                            Plugin.Log.LogWarning($"[AUTO-COLLECT] LOG SALVO NO BANCO: {collection.receipt}");
                        }
                    }
                }
                return;
            }
            if (gls.e_CurrentState == GameplayState.Start_WaitOnMulliganChoice)
            {
                _outcomeReported = false;
                _collectionConfirmationLogged = false;
                _collectionMessage = "";
                _collectionState = "";
            }

            if (_pendingAux.Count > 0)
            {
                var auxDto = GameStateBuilder.Build(
                    gls.Lps_Players[BotPlayerIndex], gls.Lps_Players[1 - BotPlayerIndex], gls);
                string auxState = JsonConvert.SerializeObject(auxDto);
                for (int i = _pendingAux.Count - 1; i >= 0; i--)
                {
                    if (auxState == _pendingAux[i].state) continue;
                    EngineClient.ReportExecutionId(_pendingAux[i].id, "confirmed", auxDto);
                    _pendingAux.RemoveAt(i);
                }
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

            string stateName = gls.e_CurrentState.ToString();
            bool turnOrderState =
                gls.e_CurrentState == GameplayState.Start_WaitOnTurnOrder ||
                (stateName.Contains("Turn") &&
                 (stateName.Contains("Order") || stateName.Contains("Selection")));
            bool setupChoiceState =
                turnOrderState ||
                gls.e_CurrentState == GameplayState.Start_WaitOnMulliganChoice;

            if (_cooldown > 0f && !setupChoiceState)
            {
                _cooldown -= Time.deltaTime;
                return;
            }

            // Escolha de 1o/2o: o estado Start_WaitOnTurnOrder so existe no
            // cliente que GANHOU o dado (WaitOnTurnSelection retorna cedo no
            // perdedor) — se chegou aqui, a escolha e do bot. Quem decide e
            // o ENGINE pela curva do deck (/turn_order — pedido do usuario
            // 12/07: nada de 50/50); o plugin so coleta os codigos (olhos)
            // e clica (maos). Server fora do ar = segundo (conservador).
            if (turnOrderState)
            {
                var toPs = gls.Lps_Players[BotPlayerIndex];
                var codes = new System.Collections.Generic.List<string>();
                foreach (var lista in new[] { toPs.Lgo_MyDeck, toPs.Lgo_MyHand, toPs.Lgo_MyLeader })
                {
                    if (lista == null) continue;
                    foreach (var go in lista)
                    {
                        var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                        if (cls != null && cls.myCard.cardDef != null)
                            codes.Add(cls.myCard.cardDef.cardID);
                    }
                }
                bool first = EngineClient.IsAlive() && EngineClient.GoFirst(codes);
                Plugin.Log.LogInfo($"[Bot] escolha de turno state={stateName} codes={codes.Count}: vai de {(first ? "PRIMEIRO" : "SEGUNDO")}");
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
                    string mulliganDecisionId = "";
                    bool mull = EngineClient.IsAlive() && EngineClient.ShouldMulligan(
                        mulDto.bot.hand, id => mulliganDecisionId = id);
                    Plugin.Log.LogInfo($"[Bot] mao inicial: {(mull ? "MULLIGAN" : "KEEP")}");
                    gls.ChoiceButtonClicked(
                        mull ? ButtonChoiceType.StartingHand_Mulligan : ButtonChoiceType.StartingHand_Keep, -1);
                    TrackAuxDecision(mulliganDecisionId, mulDto);
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

            // Achado 20/07 (partida real, Charlotte Pudding OP11-070 "peek
            // opp deck top"): qualquer efeito de olhar/revelar carta SEM
            // escolha nenhuma joga o jogo pra este estado dedicado, esperando
            // um clique de confirmacao -- sem handler aqui, o activate
            // "clicava" mas nunca comitava (rest_self nunca aplicava), e o
            // engine reofereceria a mesma ativacao pra sempre (visto no log:
            // 20 decisoes de Main falhando com "estado inalterado"/"acao
            // repetida", todas a mesma carta). Mesmo padrao do DrawCard/DrawDon
            // acima -- so confirma, nao precisa do engine.
            if (gls.e_CurrentState == GameplayState.ConfirmRevealedCard
                || gls.e_CurrentState == GameplayState.ConfirmRevealedCardOnOpponentsTurn)
            {
                gls.ChoiceButtonClicked(ButtonChoiceType.ConfirmRevealedCard, -1);
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

            // O proximo estado MAIN estavel confirma se a acao anterior mudou
            // o jogo. Nao assume que ExecuteOne=true significa sucesso: reflection
            // pode retornar sem o simulador aceitar a acao.
            if (_pendingTelemetryAction != null)
            {
                string currentState = JsonConvert.SerializeObject(dto);
                bool changed = currentState != _pendingTelemetryState;
                EngineClient.ReportExecution(
                    _pendingTelemetryAction,
                    changed ? "confirmed" : "failed",
                    dto,
                    changed ? null : "estado inalterado no proximo main state estavel");
                _pendingTelemetryAction = null;
                _pendingTelemetryState = "";
            }

            var action = EngineClient.Decide(dto);
            _actionsThisTurn++;

            if (action == null || action.type == "end_turn")
            {
                Plugin.Log.LogInfo("[Bot] end_turn");
                BotExecutor.EndTurn(gls);
                if (action != null)
                {
                    EngineClient.ReportExecution(action, "sent", dto);
                    _pendingTelemetryAction = action;
                    _pendingTelemetryState = JsonConvert.SerializeObject(dto);
                }
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
                EngineClient.ReportExecution(action, "failed", dto,
                                             "acao repetida 3x sem mudanca de estado");
                BotExecutor.EndTurn(gls);
                _cooldown = ActionCooldown;
                return;
            }

            bool ok = BotExecutor.ExecuteOne(gls, botPs, oppPs, action, dto);
            if (!ok)
            {
                EngineClient.ReportExecution(action, "failed", dto,
                                             "BotExecutor.ExecuteOne retornou false");
                _consecutiveFails++;
                if (_consecutiveFails >= 2)
                {
                    Plugin.Log.LogWarning("[Bot] 2 falhas seguidas — end turn seguro");
                    BotExecutor.EndTurn(gls);
                }
            }
            else
            {
                var immediateAfter = GameStateBuilder.Build(botPs, oppPs, gls);
                EngineClient.ReportExecution(action, "sent", immediateAfter);
                _pendingTelemetryAction = action;
                _pendingTelemetryState = JsonConvert.SerializeObject(dto);
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
            if (resp != null)
                TrackAuxDecision(resp.decisionId, dto);
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
        // Achado real 21/07 (partida ao vivo, Charlotte Pudding/Katakuri
        // "peek_opp_deck_top" -- olhar 1 carta do topo do deck do oponente):
        // CollectTargetCandidates e chamado UMA SO VEZ quando iActionStep
        // muda (bloco abaixo). Se o jogo ainda nao populou lgo_TopDeck com a
        // carta revelada do oponente NESSE EXATO instante (efeito/animacao
        // de revelar rodando 1 frame depois de iActionStep ja avancar), o
        // snapshot fica sem o alvo real pra sempre -- iActionStep nao muda
        // de novo so pq a carta apareceu depois, entao nunca refazemos a
        // lista. Sem isso, o bot cicla por TODOS os candidatos errados
        // (mao/campo proprio) e nunca acha o alvo certo. Fix: quando os
        // candidatos da 1a tentativa esgotam, busca a lista de novo UMA
        // vez antes de confirmar selecao parcial/cancelar -- se a carta
        // revelada so apareceu depois do snapshot inicial, essa 2a busca
        // ja teria ela.
        private bool _pendingRefreshTried;

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
                _pendingRefreshTried = false;
                FetchPendingCandidates(gls, botPs, oppPs);
            }

            // V3 sem alvos faltando (ex: "Choose 0 Targets") → confirma direto
            // (com o botao de finalize certo: search do topo usa FinalizeTopDeck)
            int remaining = BotExecutor.RemainingV3Targets(gls);
            if (remaining == 0)
            {
                // Achado 19/07 via analise do decision log ao vivo: quando o
                // reset acima (linha ~512) acabou de pedir um ChooseTarget novo
                // e o efeito ja nao tem mais alvo faltando, este branch confirma
                // e RETORNA antes do bloco de clique (~558) — que e o UNICO lugar
                // que reportava "sent" pro decisionId recem-recebido. Sem isto, a
                // decisao ficava orfa (0 eventos de execucao), presa em pending
                // pra sempre (12 dos 38 casos de decision_kind=target na partida
                // de 18/07, ver bloco 267/268 do HANDOFF).
                if (!string.IsNullOrEmpty(_pendingTargetDecisionId))
                {
                    TrackAuxDecision(_pendingTargetDecisionId,
                        GameStateBuilder.Build(botPs, oppPs, gls));
                    _pendingTargetDecisionId = "";
                }
                BotExecutor.ConfirmPendingSelection(gls);
                _cooldown = 1f;
                return;
            }

            if (_pendingOrder != null && _pendingAttempt < _pendingOrder.Count)
            {
                int targetId = _pendingOrder[_pendingAttempt];
                _pendingAttempt++;
                BotExecutor.ClickTargetCandidate(gls, botPs, oppPs, targetId);
                if (!string.IsNullOrEmpty(_pendingTargetDecisionId))
                {
                    TrackAuxDecision(_pendingTargetDecisionId,
                        GameStateBuilder.Build(botPs, oppPs, gls));
                    _pendingTargetDecisionId = "";
                }
                _cooldown = 0.8f;
                return;
            }

            // Candidatos esgotados: busca a lista de novo UMA vez antes de
            // desistir (ver comentario em _pendingRefreshTried acima -- pega
            // o caso de a carta revelada so aparecer DEPOIS do snapshot
            // inicial, ex: peek_opp_deck_top da Pudding/Katakuri).
            if (!_pendingRefreshTried)
            {
                _pendingRefreshTried = true;
                _pendingAttempt = 0;
                FetchPendingCandidates(gls, botPs, oppPs);
                if (_pendingOrder != null && _pendingOrder.Count > 0)
                {
                    _cooldown = 0.5f;
                    return;
                }
            }

            // ...confirma selecao parcial (V3) uma vez...
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

        // Busca a lista de candidatos ordenada pelo engine e popula
        // _pendingOrder/_pendingTargetDecisionId. Extraido de HandlePendingAction
        // pra ser reusado tanto no snapshot inicial quanto no refresh de
        // retentativa (ver _pendingRefreshTried).
        private void FetchPendingCandidates(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs)
        {
            _pendingOrder = null;
            if (!EngineClient.IsAlive())
                return;

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
                dto, candidates, BotExecutor.ActorCode(gls), atkPower, defenderId,
                id => _pendingTargetDecisionId = id);
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
                if (resp != null)
                    TrackAuxDecision(resp.decisionId,
                        GameStateBuilder.Build(botPs, oppPs, gls));
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
                if (resp != null)
                    TrackAuxDecision(resp.decisionId,
                        GameStateBuilder.Build(botPs, oppPs, gls));
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
                if (resp != null)
                    TrackAuxDecision(resp.decisionId,
                        GameStateBuilder.Build(botPs, oppPs, gls));
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

        private void TrackAuxDecision(string decisionId, GameStateDto state)
        {
            if (string.IsNullOrEmpty(decisionId)) return;
            EngineClient.ReportExecutionId(decisionId, "sent", state);
            _pendingAux.Add(new PendingAuxTelemetry
            {
                id = decisionId,
                state = JsonConvert.SerializeObject(state),
            });
        }

        // Popup permanente (canto superior esquerdo) mostrando lado/estado do
        // bot — pedido do usuario 14/07, pra conferir de relance se o bot esta
        // em P1 ou P2 e ativado/desativado, sem precisar abrir o LogOutput.log.
        // IMGUI simples (GUI.Label), sem dependencia nova; nao intercepta clique
        // (nao ha botao real na tela, so texto) — zero risco de atrapalhar os
        // cliques do proprio bot (BotExecutor) ou do jogador.
        private void OnGUI()
        {
            string lado = $"P{BotPlayerIndex + 1}";
            string estado = _botEnabled ? "ATIVADO" : "DESATIVADO";
            Color corAntes = GUI.color;
            GUI.color = _botEnabled ? Color.green : Color.red;
            float boxHeight = string.IsNullOrEmpty(_collectionMessage) ? 46 : 70;
            GUI.Box(new Rect(8, 8, 520, boxHeight), "");
            GUI.Label(new Rect(14, 10, 200, 20), $"[Bot] {lado} — {estado}");
            GUI.color = Color.white;
            GUI.Label(new Rect(14, 28, 220, 20), "Shift+B liga/desliga · Shift+P troca lado");
            if (!string.IsNullOrEmpty(_collectionMessage))
            {
                GUI.color = _collectionState == "success" ? Color.green
                          : _collectionState == "failed" ? Color.red : Color.yellow;
                GUI.Label(new Rect(14, 48, 500, 20), _collectionMessage);
            }
            GUI.color = corAntes;
        }
    }
}
