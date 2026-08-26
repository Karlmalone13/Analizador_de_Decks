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
        private string _lastUnhandledDialogKey = "";
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
                                           $"GameOver; bot=P{BotPlayerIndex + 1}",
                                           BotPlayerIndex == 0 ? "p1" : "p2");
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

            // 2+ cartas dispararam gatilho ao mesmo tempo (ex: 2 copias de
            // Izou reagindo ao mesmo ataque) -- o jogo espera o jogador
            // clicar em QUAL delas resolve primeiro antes de acaActive ser
            // definido (ver BotExecutor.IsOfferingActionChoiceOrder).
            // Achado real 02/08 (usuario, partida ao vivo): sem este bloco
            // o bot ficava parado indefinidamente ate o usuario clicar
            // manualmente. Cartas envolvidas tem efeitos independentes --
            // qualquer ordem valida desbloqueia, sem precisar do engine.
            // Mesma leitura de "de quem e o clique agora" usada no bloco de
            // efeito pendente logo abaixo (ver comentario la): o dono da
            // carta nao decide isso, `iPlayerAction` decide. Achado real
            // 16/08: a tela travou de novo mesmo com este bloco instalado --
            // IsOfferingActionChoiceOrder ainda decidia por DONO da carta
            // (choices[0]), nao por `iPlayerAction`, quebrando exatamente
            // quando a 1a opcao da lista era do oponente mas a decisao era
            // do bot (Nola do bot respondendo a Kaido do oponente). Agora
            // passa `minhaVezDeClicarOrdem` direto pra function decidir, e
            // ResolveActionChoiceOrder varre a lista inteira procurando a
            // opcao do bot em vez de assumir que e sempre a primeira.
            bool minhaVezDeClicarOrdem = gls.gsv_CurrentGame.iPlayerAction == BotPlayerIndex;
            if (!((gls.bOpponentResolving || gls.bForcingOpponentAction) && !minhaVezDeClicarOrdem)
                && BotExecutor.IsOfferingActionChoiceOrder(gls, minhaVezDeClicarOrdem))
            {
                if (BotExecutor.ResolveActionChoiceOrder(gls, gls.Lps_Players[BotPlayerIndex]))
                {
                    _cooldown = 0.8f;
                    return;
                }
            }

            // O JOGO diz de quem e o clique agora. `iPlayerAction` e o sinal
            // proprio do jogo pra isso -- o mesmo ja usado no mulligan
            // (linha ~237) e na defesa (linha ~766). Achado real 15/08
            // (usuario, 2 partidas seguidas travadas): quando uma carta do
            // OPONENTE forca o bot a decidir (ex: Charlotte Linlin OP17-049,
            // `choice_chooser: "opponent"` -- quem escolhe e quem SOFRE o
            // efeito), o jogo poe `iPlayerAction` no bot, mas o dono da
            // carta continua sendo o oponente. As duas guardas abaixo liam
            // so o DONO DA CARTA e concluiam "nao e comigo", deixando o jogo
            // parado ate o humano clicar ("Forcing opponent to resolve Card
            // Action!" na tela).
            bool minhaVezDeClicar = gls.gsv_CurrentGame.iPlayerAction == BotPlayerIndex;
            // So fica de fora quando o OUTRO lado e quem deve clicar -- ai
            // sim o bot nao pode se meter (comportamento antigo preservado).
            bool resolucaoDoOutroLado =
                (gls.bOpponentResolving || gls.bForcingOpponentAction) && !minhaVezDeClicar;

            // Efeito pendente (On Play do bot, efeito do lider ao tomar dano,
            // etc.) — vale nos DOIS turnos
            if (gls.acaActive != null && !resolucaoDoOutroLado)
            {
                var pdBotPs = gls.Lps_Players[BotPlayerIndex];
                bool duringAttack =
                    gls.e_CurrentState == GameplayState.Attack_WaitOnBlocker ||
                    gls.e_CurrentState == GameplayState.Attack_BeforeBlocker ||
                    gls.e_CurrentState == GameplayState.Attack_WaitOnCounters;

                // Oferta de "downside cost" com tela dedicada (botoes Cancel /
                // UseOnPlay|UseV3OnPlay): cliques em cartas sao ignorados ate
                // decidir.
                // Escolha entre OPCOES DE EFEITO da mesma carta (bloco 686):
                // tela V3Choice, ex "Trash 2 Cards" x "Opponent Draws 2
                // Cards". Achado do teste ao vivo (bloco 685): o plugin nao
                // tratava e o motor nem era consultado -- a partida TRAVAVA.
                // Vem ANTES do downside porque as duas telas usam os mesmos
                // go_ChoiceButton1..4 e esta e mais especifica (identificada
                // pelo `myType == V3Choice` do proprio botao).
                if (BotExecutor.IsOfferingV3Choice(gls)
                    && BotExecutor.PendingActionIsMine(gls, pdBotPs))
                {
                    var opcoes = BotExecutor.GetV3Choices(gls);
                    var dtoV3 = GameStateBuilder.Build(pdBotPs, gls.Lps_Players[1 - BotPlayerIndex], gls);
                    var lista = new System.Collections.Generic.List<EngineClient.EffectOption>();
                    foreach (var o in opcoes)
                        lista.Add(new EngineClient.EffectOption { index = o.Key, text = o.Value });
                    int? escolha = EngineClient.ChooseEffectOption(
                        dtoV3, lista, BotExecutor.ActorCode(gls));
                    // Sem resposta do motor: clica a PRIMEIRA opcao ofertada
                    // em vez de travar. Destravar a tela vale mais que acertar
                    // -- travado o jogo nao anda de jeito nenhum.
                    int idx = escolha ?? (opcoes.Count > 0 ? opcoes[0].Key : 0);
                    Plugin.Log.LogInfo(
                        $"[Bot] V3Choice: {opcoes.Count} opcao(oes), escolhida {idx}"
                        + (escolha == null ? " (FALLBACK: motor nao respondeu)" : ""));
                    BotExecutor.ClickV3Choice(gls, idx);
                    _cooldown = 1f;
                    return;
                }

                if (BotExecutor.IsOfferingDownside(gls)
                    && BotExecutor.PendingActionIsMine(gls, pdBotPs))
                {
                    bool use = ShouldUseOptionalCost(gls, duringAttack);
                    var btn = !use ? ButtonChoiceType.Cancel
                            : gls.acaActive.UsesV3() ? ButtonChoiceType.UseV3OnPlay
                            : ButtonChoiceType.UseOnPlay;
                    Plugin.Log.LogInfo($"[Bot] downside offer ({(duringAttack ? "reacao" : "proprio turno")}): {(use ? "USAR efeito" : "Cancel")}");
                    gls.ChoiceButtonClicked(btn, -1);
                    _cooldown = 1f;
                    return;
                }

                // Escolha FORCADA por carta do OPONENTE. Antes esta guarda
                // vivia DENTRO do `if (IsOfferingDownside)` acima, entao so
                // valia pra telas com botao UseOnPlay/UseV3OnPlay. Achado real
                // 16/08 (bloco 562, partida ao vivo travada): Charlotte Linlin
                // OP17-049 ("[On Play] Your opponent chooses one:") oferece as
                // duas OPCOES DE EFEITO como botoes -- sem UseOnPlay e sem
                // Cancel -- entao IsOfferingDownside dava false, o fluxo caia
                // em HandlePendingAction e ele retorna seco quando a carta nao
                // e do bot ("efeito do humano? nao toca"). Ninguem clicava:
                // freeze ate o usuario clicar na mao. Terceira variacao da
                // MESMA causa dos blocos 551 e 560 -- quem decide e
                // `iPlayerAction`, nunca o dono da carta.
                //
                // A condicao agora e a FORMA do problema, nao o tipo de tela:
                // ha efeito pendente, a carta e do oponente, o jogo aponta o
                // clique pro bot, e existe botao na tela.
                if (!BotExecutor.PendingActionIsMine(gls, pdBotPs))
                {
                    if (minhaVezDeClicar && BotExecutor.HasOfferedButtons(gls))
                    {
                        // Nao da pra reusar ShouldUseOptionalCost (a pergunta
                        // dele e "vale pagar MEU custo?", que nao e esta).
                        // Cancel primeiro quando existir (recusar o que o
                        // oponente empurra e a leitura conservadora); quando
                        // nao existir -- caso da Linlin, em que as duas opcoes
                        // sao efeitos -- clica a primeira ofertada. Isso NAO e
                        // uma escolha informada: o motor nao pontua estas
                        // opcoes hoje (limitacao registrada no HANDOFF 562), e
                        // o WARNING abaixo grava os nomes dos botoes justamente
                        // pra dar o dado que falta pra implementar a escolha
                        // real depois. O que nao pode e ficar parado.
                        string? clicado = BotExecutor.ClickFirstOffered(
                            gls, ButtonChoiceType.Cancel);
                        Plugin.Log.LogWarning(
                            $"[Bot] escolha FORCADA por carta do oponente " +
                            $"(actor={BotExecutor.ActorCode(gls)}) -- clicou " +
                            $"'{clicado ?? "nada"}'. Botoes ofertados: " +
                            $"{BotExecutor.OfferedButtonNames(gls)}");
                        _cooldown = 1f;
                    }
                    // Sem botao na tela ou clique do outro lado: nao e comigo.
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
                // `IsOptionalDonRestCost` entrou no bloco 565: mesma familia do
                // trash-da-mao, so muda a MOEDA do custo (restar DON em vez de
                // trashar carta). Sem ele, o efeito reativo do lider Luffy
                // OP13-001 nunca chegava a virar pergunta pro motor -- 12
                // ataques sofridos na partida ao vivo e ZERO decisoes de
                // `reaction` no decision log.
                if (!ReferenceEquals(_downsideCheckedFor, gls.acaActive) &&
                    BotExecutor.PendingActionIsMine(gls, pdBotPs) &&
                    BotExecutor.IsOptionalCostWindow(gls))
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
                // ANTES de confirmar (o clique esvazia a zona de reveal):
                // reporta as cartas mostradas pro engine_server guardar na
                // MatchMemory da partida (POST /reveal) -- e o que permite ao
                // engine "lembrar" da carta revelada nos /decide seguintes,
                // agora que a mao/vida do oponente chegam mascaradas
                // (HANDOFF blocos 300/301).
                BotExecutor.ReportRevealedCards(
                    gls,
                    gls.Lps_Players[BotPlayerIndex],
                    gls.Lps_Players[1 - BotPlayerIndex]);
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

            // Diagnostico generico pra qualquer dialogo AINDA NAO tratado
            // acima. Achado real 17/08: apos os fixes dos blocos 551/560/563
            // (as 3 variacoes conhecidas de "dono da carta vs iPlayerAction"),
            // a tela "Choose card effect to activate next" travou de NOVO
            // (print do usuario as 00:01) -- e desta vez sem nenhum
            // client_timeout no log do server, ou seja: o plugin nunca sequer
            // tentou perguntar pro engine, o que aponta pra um 4o caso, ainda
            // desconhecido, do mesmo padrao (estado nao reconhecido por
            // nenhum dos blocos acima). Sem acesso ao jogo nem ao
            // LogOutput.log desta sessao remota pra achar o GameplayState
            // exato, o bloco abaixo NAO tenta clicar em nada (zero risco de
            // clique errado) -- so GRAVA o estado completo na 1a vez que
            // acontecer (dedupe por state, mesmo padrao do heartbeat), pra
            // que a proxima ocorrencia real seja resolvida direto pelo log
            // em vez de outra rodada de investigacao as cegas.
            if (gls.e_CurrentState != GameplayState.PlayerTurn_Action
                && BotExecutor.HasOfferedButtons(gls))
            {
                string diagKey = $"{gls.e_CurrentState}|{BotExecutor.OfferedButtonNames(gls)}";
                if (diagKey != _lastUnhandledDialogKey)
                {
                    _lastUnhandledDialogKey = diagKey;
                    Plugin.Log.LogWarning(
                        $"[Bot] DIALOGO NAO TRATADO -- state={gls.e_CurrentState} " +
                        $"botoes={BotExecutor.OfferedButtonNames(gls)} " +
                        $"acaActive={(gls.acaActive != null)} " +
                        $"iPlayerAction={gls.gsv_CurrentGame.iPlayerAction} " +
                        $"BotPlayerIndex={BotPlayerIndex} " +
                        $"oppResolving={gls.bOpponentResolving} " +
                        $"forcing={gls.bForcingOpponentAction} " +
                        $"actor={BotExecutor.ActorCode(gls) ?? "-"}. " +
                        $"Nenhuma acao tomada -- so diagnostico, pra achar a causa " +
                        $"exata na proxima ocorrencia sem depender de print do usuario.");
                }
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

            // ...confirma selecao PARCIAL uma vez -- ex: "K.O. up to 2
            // Character com custo<=1" com so 1 candidato de verdade: o bot
            // ja selecionou o unico alvo valido, e quando o 2o slot nao
            // acha mais candidato, o jogo espera um clique tipo "Choose 1
            // Enemy Character(s)" (confirma com o que ja foi escolhido),
            // nao um Cancel. Achado real 15/08 (usuario descreveu o
            // comportamento exato ao vivo, Doc Q OP16-109 e Marshall D.
            // Teach custo 10 OP09-093): esse branch so rodava com
            // `gls.acaActive.UsesV3()` == true -- pra acoes "up to N" que
            // NAO usam o sistema V3, o gate pulava direto pro Cancel,
            // JOGANDO FORA a selecao parcial ja feita (o alvo unico
            // escolhido certo virava nulo, nenhum K.O./efeito acontecia).
            // ConfirmPendingSelection so clica um botao que o jogo
            // realmente esta oferecendo AGORA (OfferedButtons) -- seguro
            // tentar independente de V3, no pior caso e um clique sem
            // efeito e cai pro Cancel do jeito que já caia antes.
            if (!_pendingConfirmTried)
            {
                _pendingConfirmTried = true;
                // Log distinto de "confirmar selecao: X (Y)" generico --
                // pedido do usuario (15/08, bloco 542): fechar o loop do
                // fix acima com evidencia clara no LogOutput.log de que a
                // selecao PARCIAL (nao 0) realmente confirmou, sem precisar
                // reconstruir na mao de novo se o problema reapareceu.
                Plugin.Log.LogInfo(
                    $"[Bot] confirma selecao PARCIAL: {_pendingAttempt} de " +
                    $"{(_pendingOrder?.Count ?? 0)} candidato(s) selecionado(s) " +
                    $"(actor={BotExecutor.ActorCode(gls)})");
                BotExecutor.ConfirmPendingSelection(gls);
                _cooldown = 1f;
                return;
            }

            // ...e se ainda travado, cancela
            // Achado 26/07 (bloco HANDOFF 373, Charlotte Pudding OP11-070
            // "peek_opp_deck_top" -- loop recorrente confirmado em 6+
            // partidas historicas MESMO apos os fixes de 21/07 e 22/07
            // acima): hipotese e que este Cancel reverte a acao INTEIRA
            // (incluindo o custo rest_self ja pago), entao a carta nunca
            // fica "rested" de verdade e o engine reoferece a mesma
            // ativacao pra sempre. Log extra aqui (uso unico, ainda nao
            // confirmado ao vivo) pra achar a causa exata na proxima vez
            // que reproduzir: UsesV3/remaining ajudam a saber se o efeito
            // realmente precisava de candidato ou se CollectTargetCandidates
            // nunca soube modelar um "reveal" sem escolha real.
            // pendingAttempt aqui mostra se o Cancel aconteceu MESMO DEPOIS
            // da tentativa de confirmar parcial (bloco 540/542) -- se >0,
            // o ConfirmPendingSelection tentou mas nao achou nenhum botao
            // dos preferidos (OfferedButtons), sinal de que falta cobrir
            // outro ButtonChoiceType na lista; se ==0, o efeito realmente
            // nao tinha nenhum candidato pra comecar (ex: reveal sem alvo).
            Plugin.Log.LogWarning(
                $"[Bot] efeito pendente sem alvo viavel — Cancel " +
                $"(actor={BotExecutor.ActorCode(gls)}, usesV3={gls.acaActive?.UsesV3()}, " +
                $"remaining={BotExecutor.RemainingV3Targets(gls)}, " +
                $"pendingAttempt={_pendingAttempt}, " +
                $"step={gls.acaActive?.iActionStep}, state={gls.e_CurrentState})");
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
