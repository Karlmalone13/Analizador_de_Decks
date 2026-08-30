using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace OPTCGBotPlugin
{
    // Executa acoes usando o MESMO caminho do clique humano — o jogo valida
    // e paga custos por conta propria (TapDon no Deploy, etc.):
    //
    //   play:   HandleMouseClickCardDuringActionState(card) -> ChoiceButtonClicked(Deploy)
    //           (Deploy() paga o custo via TapDon e chama DeployCardFromHand)
    //   attack: go_PendingChoice = atacante -> StartAttack() -> HandleMouseClickCardAttackTarget(alvo)
    //   end:    bConfirmEnd = false; ChoiceButtonClicked(EndTurn)
    public static class BotExecutor
    {
        private static readonly FieldInfo _fPendingChoice =
            AccessTools.Field(typeof(GameplayLogicScript), "go_PendingChoice");
        private static readonly MethodInfo _mClickDuringAction =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardDuringActionState");
        private static readonly MethodInfo _mStartAttack =
            AccessTools.Method(typeof(GameplayLogicScript), "StartAttack");
        private static readonly MethodInfo _mClickAttackTarget =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardAttackTarget");

        // Defesa (membros privados verificados no decompilado)
        private static readonly FieldInfo _fAttacker =
            AccessTools.Field(typeof(GameplayLogicScript), "go_Attacker");
        private static readonly FieldInfo _fDefender =
            AccessTools.Field(typeof(GameplayLogicScript), "go_Defender");
        private static readonly MethodInfo _mClickBlocker =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardAttackBlocker");
        private static readonly MethodInfo _mDiscardCounter =
            AccessTools.Method(typeof(GameplayLogicScript), "DiscardCardForCounter");
        private static readonly MethodInfo _mClickWaitOnCounters =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardWaitOnCounters");
        private static readonly MethodInfo _mLastDrawnCard =
            AccessTools.Method(typeof(GameplayLogicScript), "LastDrawnCard");

        // Ordem de ativacao quando 2+ cartas disparam gatilho ao mesmo tempo
        // (ex: 2 copias de Izou reagindo ao mesmo ataque do oponente). O jogo
        // enfileira TODAS em acaPending (publico) e deixa acaActive (publico)
        // vazio ate o jogador clicar numa das cartas destacadas em
        // lgo_ActionChoices (privado) pra escolher qual resolve primeiro --
        // so DEPOIS desse clique e que gls.acaActive != null e o resto do
        // driver (HandlePendingAction etc.) passa a agir. Achado real 02/08
        // (usuario, partida ao vivo): sem nenhum handler pra este estado
        // especifico, o bot ficava parado indefinidamente ate o usuario
        // clicar manualmente. Mesmo padrao de reflexao ja usado acima pros
        // outros metodos privados do jogo.
        private static readonly FieldInfo _fActionChoices =
            AccessTools.Field(typeof(GameplayLogicScript), "lgo_ActionChoices");
        private static readonly MethodInfo _mClickActionChoice =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickCardMakingActionChoice");

        // True se o jogo esta esperando ALGUEM escolher QUAL de varias acoes
        // pendentes (acaPending) resolver primeiro -- acaActive ainda null e
        // lgo_ActionChoices ja populado com as cartas clicaveis. Achado real
        // 16/08 (usuario, tela "Choose card effect to activate next" travou
        // de novo com o fix de 02/08 ja instalado): a versao anterior decidia
        // "e comigo?" pelo DONO da carta em choices[0]
        // (`FindCardOwner(choices[0]) == botPs`) -- exatamente a MESMA
        // categoria de bug que o bloco 551 ja corrigiu pras telas de
        // downside/efeito pendente vizinhas ("o dono da carta nao decide
        // isso, iPlayerAction decide", comentario poucas linhas acima desta
        // chamada em BotDriver.cs). Cenario relatado (Nola do bot ativando em
        // resposta a Kaido do oponente mirando o Cracker): se a 1a carta da
        // lista de opcoes for do OPONENTE nesse instante, a checagem antiga
        // retornava false e o driver nunca clicava, mesmo com `iPlayerAction`
        // apontando pro bot. Agora usa o MESMO sinal ja usado por
        // HandleDefense/mulligan/downside em vez de reimplementar via dono
        // da carta.
        public static bool IsOfferingActionChoiceOrder(GameplayLogicScript gls, bool minhaVezDeClicar)
        {
            if (gls.acaActive != null) return false;
            if (!minhaVezDeClicar) return false;
            var choices = _fActionChoices.GetValue(gls) as List<GameObject>;
            return choices != null && choices.Count > 0;
        }

        // Resolve a ordem clicando na PRIMEIRA opcao que pertence ao PROPRIO
        // bot (nunca clica na escolha do humano, mesmo que a lista misture
        // donos -- caso do achado 16/08 acima). Cartas que disparam gatilho
        // ao mesmo tempo tem efeitos INDEPENDENTES (cada uma resolve seu
        // proprio custo/alvo depois, via HandlePendingAction normal) -- a
        // ORDEM entre as opcoes do bot raramente muda o resultado, entao nao
        // vale a pena consultar o engine so pra isso. Se NENHUMA opcao for
        // do bot apesar de `iPlayerAction` apontar pra ele (nao deveria
        // acontecer, mas e defensivo -- mesmo espirito do bloco 559 pro
        // counter), loga e retorna false sem clicar em nada.
        public static bool ResolveActionChoiceOrder(GameplayLogicScript gls, PlayerState botPs)
        {
            var choices = _fActionChoices.GetValue(gls) as List<GameObject>;
            if (choices == null || choices.Count == 0) return false;
            GameObject? escolhido = null;
            foreach (var go in choices)
            {
                bool minha;
                try { minha = gls.FindCardOwner(go) == botPs; }
                catch { minha = false; }
                if (minha) { escolhido = go; break; }
            }
            if (escolhido == null)
            {
                // ACHADO AO VIVO 29/08: este ramo era "defensivo, nao deveria
                // acontecer" e NAO CLICAVA NADA -- a partida congelava na tela
                // "Choose card effect to activate next", repetindo o aviso a
                // cada frame. Aconteceu de verdade, com 2 opcoes.
                //
                // A premissa estava errada: `IsOfferingActionChoiceOrder` so
                // devolve true quando `iPlayerAction` aponta pro BOT, ou seja,
                // chegar aqui significa que **o jogo esta pedindo pro bot
                // ordenar** -- mesmo que `FindCardOwner` nao reconheca
                // nenhuma das cartas como dele (gatilho de carta do oponente
                // que o bot tem que ordenar, ou objeto que o lookup nao
                // resolve).
                //
                // Ficar parado e estritamente pior que ordenar: os gatilhos
                // simultaneos tem efeitos INDEPENDENTES (cada um resolve o
                // proprio custo/alvo depois), entao a ordem raramente muda o
                // resultado -- e uma partida congelada muda TUDO. Mesma
                // politica ja adotada no V3Choice ("destravar a tela vale
                // mais que acertar").
                escolhido = choices[0];
                Plugin.Log.LogWarning(
                    $"[Bot] ordem de ativacao: nenhuma das {choices.Count} opcoes "
                    + $"e reconhecida como do bot, mas o jogo esta perguntando pra ele "
                    + $"-- clicando a PRIMEIRA ({CodeOf(escolhido)}) pra nao travar");
            }
            _mClickActionChoice.Invoke(gls, new object[] { escolhido });
            Plugin.Log.LogInfo(
                $"[Bot] ordem de ativacao (2+ gatilhos simultaneos): escolheu {CodeOf(escolhido)} "
                + $"({choices.Count} opcoes na lista, pode incluir carta do oponente)");
            return true;
        }

        public static GameObject? Attacker(GameplayLogicScript gls)
            => _fAttacker.GetValue(gls) as GameObject;

        public static GameObject? Defender(GameplayLogicScript gls)
            => _fDefender.GetValue(gls) as GameObject;

        // Poder atual do atacante/defensor via metodo do proprio jogo (inclui buffs/DON)
        public static int PowerOf(GameplayLogicScript gls, GameObject go, bool attacking)
        {
            try { return gls.CardPower(go, attacking, false); }
            catch { return 0; }
        }

        // deckUniqueID de qualquer carta em jogo (0 se nao der para ler)
        public static int UidOf(GameObject go)
        {
            var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
            return cls != null ? cls.myCard.deckUniqueID : 0;
        }

        // Bloqueia com o personagem indicado (mesmo caminho do clique humano;
        // o jogo valida CardCanBlock). Retorna false se a carta nao foi achada.
        public static bool TryBlock(GameplayLogicScript gls, PlayerState botPs, int blockerId)
        {
            var blocker = FindCard(botPs.Lgo_MyDeploy, blockerId);
            if (blocker == null)
            {
                Plugin.Log.LogWarning($"[Bot] block: blocker {blockerId} nao encontrado");
                return false;
            }
            _mClickBlocker.Invoke(gls, new object[] { blocker });
            Plugin.Log.LogInfo($"[Bot] block: {CodeOf(blocker)}");
            return true;
        }

        public static void NoBlocker(GameplayLogicScript gls)
        {
            gls.ChoiceButtonClicked(ButtonChoiceType.NoBlocker, -1);
            Plugin.Log.LogInfo("[Bot] no blocker");
        }

        // Eventos [Counter] ja tentados NESTE counter step (uid). Se o jogo
        // recusar o clique (condicao/DON), a carta continua na mao e o
        // /defense devolve o mesmo id no proximo tick — sem isto o driver
        // loopava clicando pra sempre. Limpo pelo driver ao iniciar a defesa
        // de um NOVO ataque (Attack_WaitOnBlocker) e ao fechar o step aqui.
        private static readonly HashSet<int> _counterEventTried = new();

        public static void ResetCounterStep() => _counterEventTried.Clear();

        // Usa as cartas de counter indicadas e resolve o ataque.
        // Personagem com stat de counter -> DiscardCardForCounter (instantaneo).
        // EVENTO [Counter] (stat 0, ex: OP13-098 "...Never Existed..." +4000)
        // -> HandleMouseClickCardWaitOnCounters, o MESMO handler do clique
        // humano, que enfileira a acao [Counter] do evento (QueueUpV3Counter
        // Actions/QueueUpAction). Achado real 12/07 (2 partidas): descartar o
        // evento via DiscardCardForCounter registrava "for Counter 0" — o bot
        // jogou fora 2x Never Existed por ZERO de defesa e perdeu com counter
        // na mao. A acao do evento resolve em ticks seguintes (prompt de alvo
        // etc. cai na maquinaria existente do driver), entao NAO clicamos
        // ResolveAttack neste tick: o jogo reabre Attack_WaitOnCounters, o
        // /defense reavalia com o buff ja aplicado e decide o que falta.
        public static void PlayCounters(GameplayLogicScript gls, PlayerState botPs, List<int> counterIds)
        {
            gls.bConfirmCounter = false;   // descarta direto, sem dialogo de confirmacao
            foreach (int id in counterIds)
            {
                // Achado real 16/08 (pedido do usuario -- investigar "so 1 dos
                // 2 counters selecionados pelo motor e aplicado", combat log
                // mostrando 1 buff quando /defense pediu 2 uids). Hipotese
                // NAO confirmada (sem jogo ao vivo pra reproduzir aqui): se o
                // proprio jogo ja considera o combate resolvido depois do
                // PRIMEIRO desconto (poder real do jogo divergindo da
                // estimativa do motor no momento do calculo), a janela de
                // counter fecha e o(s) descarte(s) seguinte(s) cairiam aqui
                // MESMO ASSIM, sem checagem -- carta some da mao pro trash
                // sem counter de verdade aplicado, batendo exatamente com o
                // sintoma reportado. Checagem defensiva: NAO muda o caminho
                // feliz (quando o jogo continua em Attack_WaitOnCounters o
                // loop inteiro roda igual a antes), so para e loga se a
                // janela ja fechou no meio -- confirma ou descarta esta
                // hipotese com dado real na proxima partida, em vez de
                // continuar descartando carta numa janela morta.
                if (gls.e_CurrentState != GameplayState.Attack_WaitOnCounters)
                {
                    Plugin.Log.LogWarning(
                        $"[Bot] counter: estado saiu de Attack_WaitOnCounters " +
                        $"({gls.e_CurrentState}) antes de aplicar uid={id} -- " +
                        $"abortando o resto da lista (janela de counter ja fechada, " +
                        $"evita descartar carta a toa)");
                    return;
                }
                var go = FindCard(botPs.Lgo_MyHand, id);
                if (go == null)
                {
                    Plugin.Log.LogWarning($"[Bot] counter: carta {id} nao encontrada na mao");
                    continue;
                }
                var cls = go.GetComponent<CardLogicScript>();
                bool isEvent = cls != null && cls.myCard.cardDef != null
                               && cls.myCard.cardDef.cardType == CardType.Event;
                if (isEvent)
                {
                    if (_counterEventTried.Contains(id))
                        continue;   // jogo ja recusou este evento neste step
                    _counterEventTried.Add(id);
                    _mClickWaitOnCounters.Invoke(gls, new object[] { go });
                    Plugin.Log.LogInfo($"[Bot] counter EVENT: {CodeOf(go)} (acao enfileirada, resolve sem clicar ResolveAttack)");
                    return;
                }
                _mDiscardCounter.Invoke(gls, new object[] { go });
                Plugin.Log.LogInfo($"[Bot] counter: {CodeOf(go)}");
            }
            _counterEventTried.Clear();
            gls.ChoiceButtonClicked(ButtonChoiceType.ResolveAttack, -1);
        }

        public static void ResolveTrigger(GameplayLogicScript gls, bool use)
        {
            gls.ChoiceButtonClicked(use ? ButtonChoiceType.Trigger : ButtonChoiceType.NoTrigger, -1);
            Plugin.Log.LogInfo($"[Bot] trigger: {(use ? "USAR" : "nao usar")}");
        }

        // Codigo da carta de vida revelada (LastDrawnCard) para a decisao de trigger
        public static string? TriggerCardCode(GameplayLogicScript gls)
        {
            try
            {
                var go = _mLastDrawnCard.Invoke(gls, null) as GameObject;
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                return cls != null && cls.myCard.cardDef != null ? cls.myCard.cardDef.cardID : null;
            }
            catch { return null; }
        }

        // ── Prompt de selecao de alvo de efeito (acaActive != null) ──────────

        private static readonly MethodInfo _mClickDuringCardAction =
            AccessTools.Method(typeof(GameplayLogicScript), "HandleMouseClickDuringCardAction");

        // bOfferingDownside (campo interno do jogo) so e setado pelo sistema
        // de acoes LEGADO (StartUsingAction_DEPRECATEME) — o sistema V3, usado
        // pela maioria das cartas novas, resolve o mesmo dialogo Cancel/Usar
        // em SetupPendingActionTargets/ConfirmAction sem nunca tocar nesse
        // campo. Em vez de depender de um flag que so metade do jogo
        // preenche, lemos os botoes REAIS na tela (mesmo sinal que o jogador
        // ve) — funciona pra qualquer carta/lider nos dois sistemas QUE
        // MOSTRAM uma tela de oferta dedicada. Algumas cartas V3 (Teach
        // confirmado) nunca marcam ConfirmAction pra esse step — o "aceitar/
        // recusar" fica embutido na propria selecao do alvo do custo, so com
        // Cancel. Pra esses, ver IsOptionalHandTrashCost().
        public static bool IsOfferingDownside(GameplayLogicScript gls)
        {
            foreach (var btn in OfferedButtons(gls))
                if (btn.myType == ButtonChoiceType.UseOnPlay
                    || btn.myType == ButtonChoiceType.UseV3OnPlay)
                    return true;
            return false;
        }

        // Custo V3 "trash N carta(s) da mao" oferecido SEM tela de oferta
        // dedicada (IsOfferingDownside acima nao pega esse caso — a selecao
        // do alvo do custo JA e a tela de aceitar/recusar). Sinal GERAL,
        // valido pra qualquer carta com esse padrao: o step atual do efeito
        // pendente marca effect.TrashCard (mesmo campo que o jogo usa pra
        // montar o botao "Select N Cards to Trash" em PopulateV3Choice) e o
        // Cancel esta realmente na tela — se nao tem Cancel, o custo e
        // obrigatorio (parte de uma acao ja confirmada), nao opcional.
        public static bool IsOptionalHandTrashCost(GameplayLogicScript gls)
        {
            if (gls.acaActive == null || !gls.acaActive.UsesV3())
                return false;
            try
            {
                if (!gls.acaActive.V3Step().effect.TrashCard)
                    return false;
            }
            catch { return false; }

            foreach (var btn in OfferedButtons(gls))
                if (btn.myType == ButtonChoiceType.Cancel)
                    return true;
            return false;
        }

        // Custo opcional de RESTAR DON, irmao de IsOptionalHandTrashCost acima.
        // Achado real 16/08 (bloco 565, partida ao vivo): o bot jogando
        // Monkey D. Luffy OP13-001 ("[DON!! x1] [On Your Opponent's Attack] ...
        // you may rest any number of your DON!! cards: +2000 por DON restado")
        // NUNCA usou a habilidade do lider -- e a telemetria mostrou por que:
        // 12 decisoes de blocker e 12 de counter na partida, e ZERO de
        // `reaction`. O motor nao decidiu mal, ele nunca foi PERGUNTADO.
        //
        // Causa: o plugin so reconhecia janela de custo opcional em dois
        // formatos -- tela com botao UseOnPlay (`IsOfferingDownside`) ou custo
        // de TRASHAR carta da mao (`IsOptionalHandTrashCost`, que exige
        // `effect.TrashCard`). O Teach OP16-080 tem o MESMO gatilho
        // [On Your Opponent's Attack] mas paga com trash de carta, entao caia
        // no segundo caso e funcionava; um custo de RESTAR DON (`effect.DonTap`,
        // campo vizinho do TrashCard em ActV3Effect) nao batia em nenhum dos
        // dois e a janela passava batido.
        //
        // Generico, nao e do Luffy: vale pra qualquer carta/lider cujo custo
        // opcional seja restar DON. Mesma regra do irmao -- sem Cancel na tela,
        // o custo e obrigatorio (parte de acao ja confirmada), nao opcional.
        public static bool IsOptionalDonRestCost(GameplayLogicScript gls)
            => IsOptionalCostWindow(gls);

        // Generalizacao do bloco 566 (varredura `audit_card_coverage.py` sobre
        // as 2747 cartas do banco). O bug do Luffy era a ponta de um padrao: o
        // plugin so reconhecia a janela de custo opcional pela MOEDA especifica
        // do custo, uma funcao por moeda -- entao cada moeda nao prevista era
        // um efeito silenciosamente morto ao vivo. A varredura mediu o tamanho
        // real do buraco, por cartas com gatilho INTERATIVO:
        //
        //     trash_from_hand  207  (ja cobria, effect.TrashCard)
        //     don_minus        163  <- morto
        //     rest_self        130  <- morto
        //     rest_don         125  (passou a cobrir com effect.DonTap, b.565)
        //     trash_self        60  <- morto
        //     rest_any_don       1  (o Luffy, b.565)
        //
        // Agora a checagem e pela FORMA do problema, nao pela moeda (mesma
        // orientacao do CLAUDE.md sobre corrigir generico): "o step V3 atual
        // exige ALGUM custo do jogador E existe Cancel na tela". Sem Cancel o
        // custo e obrigatorio (parte de acao ja confirmada), nao opcional --
        // regra que as versoes por-moeda ja usavam, preservada.
        //
        // Os campos vem de `ActV3Effect` (dnspy-export), todos vizinhos do
        // TrashCard que ja era lido. Custo novo que apareca no jogo so precisa
        // ser somado a esta lista, num lugar so.
        // DIAGNOSTICO (bloco 744): IsOptionalCostWindow abaixo tem TRES
        // portoes e devolve um bool so -- quando ela diz "nao", o log nao
        // dizia QUAL portao barrou, e a sessao seguinte ficava adivinhando.
        //
        // Motivo concreto: o efeito reativo do lider Luffy OP13-001
        // ([On Your Opponent's Attack], custo `rest_any_don`) continua sem
        // virar pergunta pro motor -- ZERO decisoes de `reaction` no
        // decision log da partida de 30/08, pela 3a vez reportado pelo
        // usuario. O bloco 565 ja tentou consertar isto e nao pegou este
        // caso. Sem saber qual portao falha, o proximo conserto seria
        // chute de novo.
        public static string OptionalCostWhy(GameplayLogicScript gls)
        {
            if (gls.acaActive == null) return "sem_aca";
            bool v3;
            try { v3 = gls.acaActive.UsesV3(); }
            catch { return "UsesV3_excecao"; }
            if (!v3) return "nao_e_V3";
            string flags;
            try
            {
                var ef = gls.acaActive.V3Step().effect;
                flags = $"TrashCard={ef.TrashCard} RestSelf={ef.RestSelf} "
                      + $"TrashSelf={ef.TrashSelf} DonTap={ef.DonTap} DonMinus={ef.DonMinus}";
                bool exige = ef.TrashCard || ef.RestSelf || ef.TrashSelf
                          || ef.DonTap > 0 || ef.DonMinus > 0;
                if (!exige) return "sem_custo_opcional[" + flags + "]";
            }
            catch { return "V3Step_excecao"; }
            foreach (var btn in OfferedButtons(gls))
                if (btn.myType == ButtonChoiceType.Cancel)
                    return "OK[" + flags + "]";
            return "sem_botao_Cancel[" + flags + "|botoes=" + OfferedButtonNames(gls) + "]";
        }

        public static bool IsOptionalCostWindow(GameplayLogicScript gls)
        {
            if (gls.acaActive == null || !gls.acaActive.UsesV3())
                return false;

            bool exigeCusto;
            try
            {
                var ef = gls.acaActive.V3Step().effect;
                exigeCusto = ef.TrashCard      // trashar carta da mao
                          || ef.RestSelf       // restar a propria carta
                          || ef.TrashSelf      // trashar a propria carta
                          || ef.DonTap    > 0  // restar DON
                          || ef.DonMinus  > 0; // devolver DON ao deck de DON
            }
            catch { return false; }

            if (!exigeCusto)
                return false;

            foreach (var btn in OfferedButtons(gls))
                if (btn.myType == ButtonChoiceType.Cancel)
                    return true;
            return false;
        }

        // Existe QUALQUER botao de escolha na tela agora? Sinal generico de
        // "o jogo esta esperando um clique de escolha", sem depender de qual
        // tipo de botao e. Achado real 16/08 (bloco 562, Charlotte Linlin
        // OP17-049 "[On Play] Your opponent chooses one:"): a guarda de
        // escolha forcada estava presa a IsOfferingDownside, que so reconhece
        // telas com UseOnPlay/UseV3OnPlay. Uma tela que oferece as OPCOES DE
        // EFEITO direto (sem UseOnPlay, sem Cancel) escapava dela e caia em
        // HandlePendingAction, que retorna seco quando a carta e do oponente
        // -- ninguem clicava e a partida travava ate o humano intervir.
        public static bool HasOfferedButtons(GameplayLogicScript gls)
        {
            foreach (var _ in OfferedButtons(gls))
                return true;
            return false;
        }

        // Ator do efeito pendente. goActor e null em acoes V3 — ActorObject()
        // resolve os dois estilos (V3 busca por iActorID).
        private static GameObject? PendingActor(GameplayLogicScript gls)
        {
            if (gls.acaActive == null) return null;
            try { return gls.acaActive.ActorObject(); }
            catch { return null; }
        }

        // Codigo da carta cujo efeito esta resolvendo
        public static string? ActorCode(GameplayLogicScript gls)
        {
            var actor = PendingActor(gls);
            var cls = actor != null ? actor.GetComponent<CardLogicScript>() : null;
            return cls != null && cls.myCard.cardDef != null ? cls.myCard.cardDef.cardID : null;
        }

        // O efeito pendente pertence ao bot?
        // Tipos dos botoes que o jogo esta oferecendo AGORA, em texto -- so
        // pra diagnostico. Sem isso, quando o bot trava numa tela que o
        // plugin nao sabe tratar, o log nao diz QUAL era a tela, e a sessao
        // seguinte fica adivinhando (foi o que aconteceu com a tela de
        // "Forcing opponent to resolve Card Action", blocos 543/550).
        public static string OfferedButtonNames(GameplayLogicScript gls)
        {
            var nomes = new System.Collections.Generic.List<string>();
            foreach (var btn in OfferedButtons(gls))
                nomes.Add(btn.myType.ToString());
            return nomes.Count == 0 ? "(nenhum)" : string.Join("|", nomes);
        }

        // Clica o primeiro botao ofertado que casar com a lista de
        // preferencia; se nenhum casar, clica o primeiro ofertado. Usado pra
        // DESTRAVAR telas de escolha forcada pelo oponente que o plugin
        // ainda nao sabe pontuar -- nunca deixa o jogo parado esperando um
        // clique humano. Devolve o tipo clicado (ou null se nao havia botao).
        public static string? ClickFirstOffered(GameplayLogicScript gls,
                                                params ButtonChoiceType[] preferidos)
        {
            ChoiceButtonScript? primeiro = null;
            foreach (var btn in OfferedButtons(gls))
            {
                primeiro ??= btn;
                foreach (var p in preferidos)
                    if (btn.myType == p)
                    {
                        gls.ChoiceButtonClicked(btn.myType, -1);
                        return btn.myType.ToString();
                    }
            }
            if (primeiro == null) return null;
            gls.ChoiceButtonClicked(primeiro.myType, -1);
            return primeiro.myType.ToString();
        }

        public static bool PendingActionIsMine(GameplayLogicScript gls, PlayerState botPs)
        {
            var actor = PendingActor(gls);
            if (actor == null) return false;
            try { return gls.FindCardOwner(actor) == botPs; }
            catch { return false; }
        }

        // O BOT e quem tem que responder este prompt?
        //
        // CRITERIO UNICO -- criado 29/08 depois da SEXTA ocorrencia do mesmo
        // bug em lugares diferentes. `PendingActionIsMine` responde "a CARTA
        // e minha?", que NAO e a mesma pergunta. Existe uma classe inteira de
        // efeito em que o dono e o oponente e quem decide e o bot:
        // `choice_chooser: "opponent"` -- Charlotte Linlin OP17-049/OP17-099
        // ("Your opponent chooses one", "opponent trashes 2 cards"), entre
        // outros. Nesses casos o jogo poe `iPlayerAction` no bot e fica
        // esperando; quem le so o dono conclui "nao e comigo" e a partida
        // TRAVA ate o humano clicar.
        //
        // Historico das ocorrencias: 15/08 (as guardas de
        // `resolucaoDoOutroLado`, corrigidas la), 28/08 (ramo V3Choice,
        // nasceu ja com o bug) e 29/08 (`HandlePendingAction`). Cada uma foi
        // corrigida isolada. Daqui pra frente, TODO ponto que decide "devo
        // responder?" usa esta funcao -- nao `PendingActionIsMine` direto.
        public static bool ShouldBotAnswer(GameplayLogicScript gls, PlayerState botPs, int botIndex)
        {
            if (PendingActionIsMine(gls, botPs)) return true;
            try { return gls.gsv_CurrentGame.iPlayerAction == botIndex; }
            catch { return false; }
        }

        // Alvos que ainda faltam selecionar num step V3 (<= 0 = pode confirmar)
        private static readonly MethodInfo _mRemainingTargets =
            AccessTools.Method(typeof(GameplayLogicScript), "RemainingTargetsToSelect");

        public static int RemainingV3Targets(GameplayLogicScript gls)
        {
            if (gls.acaActive == null || !gls.acaActive.UsesV3())
                return -1;
            try { return (int)_mRemainingTargets.Invoke(gls, new object[] { gls.acaActive }); }
            catch { return -1; }
        }

        // Confirma a selecao V3 atual ("Choose N Targets" -> V3NextStep)
        public static void ConfirmV3Targets(GameplayLogicScript gls)
        {
            gls.ChoiceButtonClicked(ButtonChoiceType.SelectTargets, -1);
            Plugin.Log.LogInfo("[Bot] V3: confirmar selecao (NextStep)");
        }

        // Cartas reveladas do topo do deck (search/look at top X) — zona
        // privada do GLS, fora dos PlayerStates
        private static readonly FieldInfo _fTopDeck =
            AccessTools.Field(typeof(GameplayLogicScript), "lgo_TopDeck");

        private static List<GameObject>? TopDeck(GameplayLogicScript gls)
            => _fTopDeck.GetValue(gls) as List<GameObject>;

        // Reporta ao engine_server (POST /reveal) as cartas cuja identidade o
        // jogo acabou de mostrar ao bot -- chamado pelo BotDriver no estado
        // ConfirmRevealedCard, ANTES do clique de confirmacao (depois do
        // clique a zona de reveal esvazia). A zona e classificada pelo LUGAR
        // onde o uid vive AGORA: mao do oponente (Arlong), vida do oponente,
        // propria vida (Katakuri/OP15-119); quem esta so no lgo_TopDeck e
        // peek de deck do OPONENTE (peek_opp_deck_top da Pudding) -- reveals
        // do PROPRIO deck (search) nao sao reportados: a MatchMemory nao
        // rastreia own_deck (o gs.deck ao vivo e placeholder de contagem, nao
        // ha onde re-injetar identidade; ver match_memory.py). Cartas da
        // PROPRIA mao tambem nao (o bot ja ve a propria mao). Best-effort e
        // idempotente (o server deduplica por set de uids).
        public static void ReportRevealedCards(GameplayLogicScript gls,
                                               PlayerState botPs, PlayerState oppPs)
        {
            var porZona = new Dictionary<string, List<int>>();
            void Nota(string zona, int uid)
            {
                if (!porZona.TryGetValue(zona, out var l))
                    porZona[zona] = l = new List<int>();
                l.Add(uid);
            }
            foreach (var go in TopDeck(gls) ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls == null) continue;
                int uid = cls.myCard.deckUniqueID;
                if (FindCard(botPs.Lgo_MyHand, uid) != null)
                    continue;  // propria mao: bot ja ve
                if (FindCard(oppPs.Lgo_MyHand, uid) != null)
                    Nota("opp_hand", uid);
                else if (FindCard(oppPs.Lgo_MyLifeDeck, uid) != null)
                    Nota("opp_life", uid);
                else if (FindCard(botPs.Lgo_MyLifeDeck, uid) != null)
                    Nota("own_life", uid);
                else if (FindCard(botPs.Lgo_MyDeck, uid) == null)
                    Nota("opp_deck", uid);  // nao e nada do bot: peek de deck inimigo
            }
            // PeekSelfLife/PeekOppLife do jogo oficial nao move a carta para
            // lgo_TopDeck: apenas chama SetFaceUp(true) diretamente na zona
            // de Life. Capture essas cartas visiveis durante a confirmacao.
            void NotaLifeFaceUp(List<GameObject>? life, string zona)
            {
                if (life == null) return;
                foreach (var go in life)
                {
                    var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                    if (cls != null && cls.myCard.bFaceUp)
                        Nota(zona, cls.myCard.deckUniqueID);
                }
            }
            NotaLifeFaceUp(oppPs.Lgo_MyLifeDeck, "opp_life");
            NotaLifeFaceUp(botPs.Lgo_MyLifeDeck, "own_life");
            foreach (var kv in porZona)
                EngineClient.ReportReveal(kv.Key, kv.Value);
        }

        // Todos os alvos clicaveis possiveis, com zona e codigo (o jogo valida
        // cada clique; o codigo permite ao engine valorar cartas fora do DTO,
        // como trash e top deck)
        public static List<EngineClient.TargetCandidate> CollectTargetCandidates(
            PlayerState botPs, PlayerState oppPs, GameplayLogicScript gls)
        {
            var list = new List<EngineClient.TargetCandidate>();
            // hideCode: nao expoe o cardID do candidato. Usado pra zonas de
            // INFORMACAO OCULTA do oponente (mao) -- o bot escolhe as cegas
            // (efeitos "choose 1 card from your opponent's hand": Arlong
            // OP01-063 reveal, Kanjuro OP01-038, etc.); nao pode "trapacear"
            // avaliando cartas que nao deveria ver. Sem code, o sim_bridge cai
            // no catch-all e pega qualquer uma (o jogo valida o clique).
            void Add(List<GameObject>? zone, string name, bool hideCode = false)
            {
                if (zone == null) return;
                foreach (var go in zone)
                {
                    var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                    if (cls != null)
                        list.Add(new EngineClient.TargetCandidate
                        {
                            id = cls.myCard.deckUniqueID,
                            zone = name,
                            code = (hideCode || cls.myCard.cardDef == null)
                                   ? "" : cls.myCard.cardDef.cardID,
                        });
                }
            }
            Add(TopDeck(gls),       "top_deck");
            Add(botPs.Lgo_MyHand,   "own_hand");
            Add(botPs.Lgo_MyDeploy, "own_board");
            Add(botPs.Lgo_MyTrash,  "own_trash");
            Add(oppPs.Lgo_MyDeploy, "opp_board");
            Add(oppPs.Lgo_MyTrash,  "opp_trash");
            Add(botPs.Lgo_MyLeader, "own_leader");
            Add(oppPs.Lgo_MyLeader, "opp_leader");
            Add(botPs.Lgo_MyStage,  "own_stage");
            Add(oppPs.Lgo_MyStage,  "opp_stage");
            // Mao do oponente -- alvo de "choose 1 card from your opponent's
            // hand" (Arlong reveal_opp_hand, Kanjuro opp_choose_trash_our_hand).
            // _valid_target_location aceita hand_card em QUALQUER jogador, so
            // faltava a zona. hideCode: escolha as cegas (o bot nao ve a mao).
            Add(oppPs.Lgo_MyHand,   "opp_hand", hideCode: true);

            // DON na propria area de custo -- alvo clicavel pra qualquer custo
            // "DON!! -N" (don_minus no parser). Achado real 21/07 (partida ao
            // vivo, hipotese correta do usuario): o jogo real
            // (GameplayLogicScript.ValidV3TargetLocation, decompilado) exige
            // clicar N cartas de DON na DonCostArea pra pagar esse custo --
            // branch dedicado "vTarget.DonAreaCard && CardObjectInDonArea(...)",
            // DISTINTO de personagem/mao/trash/deck. CollectTargetCandidates
            // nunca incluia essa zona -- qualquer habilidade com custo DON!! -N
            // (Katakuri, Mamaragan [Main], Pudding PRB02-010 on_play, etc.)
            // ficava ciclando por candidatos que o jogo SEMPRE recusa.
            //
            // don_minus RETORNA DON ao deck (action_system.py: "retornar X don
            // ao deck") -- NAO resta. Por isso ValidV3TargetLocation/
            // _valid_target_location aceita a area de custo SEM checar b_tapped:
            // DON restado E ativo sao ambos alvos validos. Preferencia
            // estrategica (pedido do usuario): devolver primeiro o DON ja gasto
            // (restado) e preservar o ativo, que ainda pode pagar/atacar neste
            // turno. Duas zonas separadas pra o sim_bridge ordenar restado
            // ANTES de ativo. (DON anexado a carta: o validador tem branch
            // proprio attached_don, mas nao da pra confirmar aqui quais flags o
            // don_minus seta -- deixado de fora ate checar no dnspy p/ nao
            // coletar candidato que o jogo recuse.)
            var donRestado = new List<GameObject>();
            var donAtivo = new List<GameObject>();
            var donAnexadoUsado = new List<GameObject>();
            var donAnexadoNaoUsado = new List<GameObject>();
            void CollectAttachedDon(List<GameObject>? cards)
            {
                if (cards == null) return;
                foreach (var cardGo in cards)
                {
                    var owner = cardGo != null ? cardGo.GetComponent<CardLogicScript>() : null;
                    if (owner?.lgo_AttachedDon == null) continue;
                    var destination = owner.myCard.bTapped
                        ? donAnexadoUsado : donAnexadoNaoUsado;
                    foreach (var donGo in owner.lgo_AttachedDon)
                        if (donGo != null) destination.Add(donGo);
                }
            }
            CollectAttachedDon(botPs.Lgo_MyDeploy);
            CollectAttachedDon(botPs.Lgo_MyLeader);
            foreach (var go in botPs.Lgo_MyDonCostArea ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls == null) continue;
                if (cls.myCard.bTapped) donRestado.Add(go);
                else                    donAtivo.Add(go);
            }
            Add(donAnexadoUsado,    "own_don_attached_used");
            Add(donRestado,         "own_don_rested");
            Add(donAnexadoNaoUsado, "own_don_attached");
            Add(donAtivo,           "own_don");

            // DON do oponente -- alvo de efeitos que restam/retornam DON
            // adversario (comum no Krieg). _valid_target_location varre TODOS
            // os jogadores no branch don_area_card, entao o DON do oponente e
            // alvo valido; so faltava a zona ser candidata aqui.
            Add(oppPs.Lgo_MyDonCostArea, "opp_don");
            return list;
        }

        // Clica num candidato (mesmo caminho do clique humano; o jogo valida
        // via CardIsViableTarget/V3 e ignora cliques invalidos)
        public static bool ClickTargetCandidate(GameplayLogicScript gls, PlayerState botPs,
                                                PlayerState oppPs, int targetId)
        {
            // DON anexado vive em lgo_AttachedDon do Leader/Character, nao
            // em Lgo_MyDonCostArea. A coleta o achava, mas o clique nao.
            var go = FindAttachedDon(botPs, targetId)
                  ?? FindCard(TopDeck(gls), targetId)
                  ?? FindCard(botPs.Lgo_MyHand, targetId)
                  ?? FindCard(botPs.Lgo_MyDeploy, targetId)
                  ?? FindCard(botPs.Lgo_MyTrash, targetId)
                  ?? FindCard(oppPs.Lgo_MyDeploy, targetId)
                  ?? FindCard(oppPs.Lgo_MyTrash, targetId)
                  ?? FindCard(botPs.Lgo_MyLeader, targetId)
                  ?? FindCard(oppPs.Lgo_MyLeader, targetId)
                  ?? FindCard(botPs.Lgo_MyStage, targetId)
                  ?? FindCard(oppPs.Lgo_MyStage, targetId)
                  ?? FindCard(botPs.Lgo_MyDonCostArea, targetId)
                  ?? FindCard(oppPs.Lgo_MyDonCostArea, targetId)
                  ?? FindCard(oppPs.Lgo_MyHand, targetId);
            if (go == null)
            {
                // Alvo que o motor pediu nao foi encontrado em NENHUMA zona
                // clicavel. Antes isso era um `return false` silencioso -- o
                // efeito simplesmente nao acontecia e nao sobrava rastro
                // nenhum no log pra distinguir "motor errou o alvo" de
                // "plugin nao achou a carta". Achado 16/08 (bloco 564, Doc Q
                // OP16-109): investigacao do "[On K.O.] nao deu K.O." ficou
                // sem conclusao porque este caminho e mudo.
                Plugin.Log.LogWarning(
                    $"[Bot] alvo de efeito NAO ENCONTRADO (uid={targetId}, " +
                    $"actor={ActorCode(gls)}) -- efeito nao vai resolver");
                return false;
            }

            // Diagnostico do bloco 564: o clique era registrado sem NENHUMA
            // verificacao de que surtiu efeito. No Doc Q, o motor mandou o
            // alvo certo (Streusen, custo 1) e o log mostrou o clique nele --
            // mas o K.O. nunca apareceu no combat log, e nao havia como saber
            // se o jogo aceitou o clique. Logar alvos-restantes antes/depois
            // separa "clique recusado pelo jogo" de "clique aceito e efeito
            // resolveu errado". Nao muda comportamento -- so observa.
            int faltavamAntes = RemainingV3Targets(gls);
            _mClickDuringCardAction.Invoke(gls, new object[] { go });
            int faltamDepois = RemainingV3Targets(gls);
            Plugin.Log.LogInfo(
                $"[Bot] alvo de efeito: {CodeOf(go)} (uid={targetId}, " +
                $"actor={ActorCode(gls)}, faltavam={faltavamAntes} -> " +
                $"faltam={faltamDepois})");
            if (faltavamAntes >= 0 && faltamDepois == faltavamAntes)
            {
                // Bloco 687: quando o contador nao anda E esta num valor de
                // SENTINELA (o jogo usa 999 pra "infinito"; visto 99 ao vivo
                // num efeito do lider Luffy OP13-001), o problema NAO e o
                // alvo escolhido -- e que o step nao tem contagem definida e
                // nenhum clique vai consumir nada. Sem esses campos no log
                // nao da pra distinguir "alvo errado" de "step sem
                // contagem", e foi exatamente essa duvida que impediu o
                // diagnostico do relato ao vivo de 25/08. Loga o suficiente
                // pra fechar isso no PROXIMO teste, sem mudar comportamento.
                string extra = "";
                if (faltamDepois >= 99)
                {
                    try
                    {
                        var step = gls.acaActive.V3Step();
                        extra = $" [SENTINELA: targetIdx={gls.acaActive.iActionTargetIdx}"
                              + $", targets={step.target.Count}"
                              + $", actionStep={gls.acaActive.iActionStep}]";
                    }
                    catch { extra = " [SENTINELA: sem detalhe do step]"; }
                }
                Plugin.Log.LogWarning(
                    $"[Bot] clique em {CodeOf(go)} NAO consumiu alvo " +
                    $"(faltam {faltamDepois} antes e depois) -- jogo pode ter " +
                    $"recusado a selecao{extra}");
                LastClickConsumed = false;
                return true;
            }
            LastClickConsumed = true;
            return true;
        }

        // O ultimo ClickTargetCandidate foi de fato CONSUMIDO pelo jogo?
        // (contador de alvos restantes andou). Antes so existia no log:
        // quem chamava nao tinha como saber, e o driver seguia clicando
        // candidato por candidato ate esgotar a lista.
        public static bool LastClickConsumed { get; private set; }

        // O step atual aceita QUANTIDADE LIVRE de alvos?
        //
        // ACHADO 29/08 (partida ao vivo): `RemainingTargetsToSelect` do jogo
        // devolve `TargetCount - selecionados`, e cartas de quantidade livre
        // ("rest ANY NUMBER of your DON!!", lider Monkey D. Luffy OP13-001)
        // trazem TargetCount = 99. **99 nao e sentinela de erro -- e "a
        // vontade".** O driver so confirmava com `remaining == 0`, que nesse
        // step NUNCA acontece: ele percorria os 28 candidatos a 0,8s cada
        // (~22s), esgotava e confirmava com ZERO selecionado. O jogo
        // reperguntava, e o ciclo repetia -- 21 vezes na mesma partida, com
        // a habilidade do lider morta o jogo inteiro.
        public static bool V3CountIsFree(GameplayLogicScript gls)
            => RemainingV3Targets(gls) >= 99;

        private static GameObject? FindAttachedDon(PlayerState player, int deckUniqueId)
        {
            GameObject? InOwners(List<GameObject>? owners)
            {
                if (owners == null) return null;
                foreach (var ownerGo in owners)
                {
                    var owner = ownerGo != null
                        ? ownerGo.GetComponent<CardLogicScript>() : null;
                    var found = FindCard(owner?.lgo_AttachedDon, deckUniqueId);
                    if (found != null) return found;
                }
                return null;
            }
            return InOwners(player.Lgo_MyDeploy) ?? InOwners(player.Lgo_MyLeader);
        }

        // ── Botoes de escolha atualmente ofertados (go_ChoiceButton1..4) ─────
        private static IEnumerable<ChoiceButtonScript> OfferedButtons(GameplayLogicScript gls)
        {
            foreach (var go in new[] { gls.go_ChoiceButton1, gls.go_ChoiceButton2,
                                       gls.go_ChoiceButton3, gls.go_ChoiceButton4 })
            {
                if (go == null || !go.activeSelf) continue;
                var btn = go.GetComponent<ChoiceButtonScript>();
                if (btn != null) yield return btn;
            }
        }

        // ── Escolha entre OPCOES DE EFEITO da mesma carta (bloco 686) ──────
        // O jogo chama isso de V3Choice: `ActV3Choice { ButtonText, JumpToStep }`,
        // populado por `PopulateV3Choice` -> `AddChoiceWithExtras(..., V3Choice,
        // i, textoDaOpcao)`. Cada botao carrega o INDICE da opcao em
        // `iChoiceInt`, e o clique e `ChoiceButtonClicked(V3Choice, indice)`.
        //
        // Achado real 25/08 (teste ao vivo, bloco 685): o plugin tratava
        // GoFirst/StartingHand/UseOnPlay/Cancel mas NAO o V3Choice -- a tela
        // "Trash 2 Cards" x "Opponent Draws 2 Cards" simplesmente travava, e o
        // motor NEM ERA CONSULTADO (confirmado: nas 196 linhas do decision_log
        // da partida nao existe nenhuma fase de escolha entre efeitos).
        public static bool IsOfferingV3Choice(GameplayLogicScript gls)
        {
            foreach (var b in OfferedButtons(gls))
                if (b.myType == ButtonChoiceType.V3Choice) return true;
            return false;
        }

        /// (indice_da_opcao, texto_do_botao) de cada opcao ofertada AGORA.
        /// O texto e o que o jogador ve ("Trash 2 Cards"), e e o que o motor
        /// usa pra decidir -- o bot continua so olhos/maos.
        public static List<KeyValuePair<int, string>> GetV3Choices(GameplayLogicScript gls)
        {
            var fora = new List<KeyValuePair<int, string>>();
            foreach (var b in OfferedButtons(gls))
            {
                if (b.myType != ButtonChoiceType.V3Choice) continue;
                // Le o texto por REFLEXAO: a assembly do TextMeshPro nao esta
                // referenciada no csproj, e adiciona-la so pra ler uma string
                // criaria dependencia nova de build por nada.
                string texto = "";
                foreach (var comp in b.gameObject.GetComponentsInChildren<Component>())
                {
                    if (comp == null) continue;
                    var tipo = comp.GetType();
                    if (tipo.Name != "TextMeshProUGUI" && tipo.Name != "Text") continue;
                    var prop = tipo.GetProperty("text");
                    if (prop == null) continue;
                    texto = prop.GetValue(comp, null) as string ?? "";
                    if (!string.IsNullOrEmpty(texto)) break;
                }
                fora.Add(new KeyValuePair<int, string>(b.iChoiceInt, texto));
            }
            return fora;
        }

        public static void ClickV3Choice(GameplayLogicScript gls, int indice)
        {
            gls.ChoiceButtonClicked(ButtonChoiceType.V3Choice, indice);
            Plugin.Log.LogInfo($"[Bot] V3Choice: opcao {indice}");
        }

        // Confirma a selecao atual clicando o botao de finalize CORRETO
        // ofertado pelo jogo (search do topo do deck usa FinalizeTopDeck /
        // ConfirmRevealedCard, que roteiam diferente de SelectTargets).
        public static void ConfirmPendingSelection(GameplayLogicScript gls)
        {
            var preferidos = new[] { ButtonChoiceType.FinalizeTopDeck,
                                     ButtonChoiceType.ConfirmRevealedCard,
                                     ButtonChoiceType.SelectTargets,
                                     ButtonChoiceType.SelectFriendlyTargets,
                                     ButtonChoiceType.SelectEnemyTargets,
                                     ButtonChoiceType.SelectEnemyCharacters,
                                     ButtonChoiceType.SelectEnemyLeaders,
                                     ButtonChoiceType.SelectEnemyStage,
                                     ButtonChoiceType.SelectTrashTargets,
                                     ButtonChoiceType.ConfirmInfiniteTargets };
            foreach (var alvo in preferidos)
                foreach (var oferecido in OfferedButtons(gls))
                    if (oferecido.myType == alvo)
                    {
                        // Mesmo contrato de ChoiceButtonScript.ImClicked():
                        // usa o tipo e o inteiro do botao que esta na tela.
                        gls.ChoiceButtonClicked(oferecido.myType, oferecido.iChoiceInt);
                        Plugin.Log.LogInfo(
                            $"[Bot] confirmar selecao: {oferecido.myType} ({oferecido.iChoiceInt})");
                        return;
                    }
            // Nenhum botao de finalize visivel — mantem o comportamento antigo
            gls.ChoiceButtonClicked(ButtonChoiceType.SelectTargets, -1);
            Plugin.Log.LogInfo("[Bot] confirmar selecao (fallback SelectTargets)");
        }

        public static void CancelPendingAction(GameplayLogicScript gls)
        {
            gls.ChoiceButtonClicked(ButtonChoiceType.Cancel, -1);
            Plugin.Log.LogInfo("[Bot] efeito pendente: Cancel");
        }

        // Deploy com campo cheio (Action_SelectingDeploySwap): substitui o
        // personagem indicado pelo pendente (DeploySwap trasha + deploya)
        private static readonly MethodInfo _mDeploySwap =
            AccessTools.Method(typeof(GameplayLogicScript), "DeploySwap");

        public static bool TryDeploySwap(GameplayLogicScript gls, PlayerState botPs, int replaceId)
        {
            var go = FindCard(botPs.Lgo_MyDeploy, replaceId);
            if (go == null)
            {
                Plugin.Log.LogWarning($"[Bot] deploy swap: personagem {replaceId} nao encontrado");
                return false;
            }
            _mDeploySwap.Invoke(gls, new object[] { go, false });
            Plugin.Log.LogInfo($"[Bot] deploy swap: substitui {CodeOf(go)}");
            return true;
        }

        public static bool ExecuteOne(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs,
                                      BotAction action, GameStateDto dto)
        {
            switch (action.type)
            {
                case "play":
                    return TryPlay(gls, botPs, action.cardId);
                case "attack":
                    return TryAttack(gls, botPs, oppPs, action.cardId, action.targetId,
                                     action.donToAttach, dto);
                case "attach_don":
                    return TryAttachDon(gls, botPs, action.cardId, action.donToAttach, dto);
                case "activate":
                    return TryActivate(gls, botPs, action.cardId, dto);
                default:
                    Plugin.Log.LogWarning($"[Bot] tipo de acao desconhecido: {action.type}");
                    return false;
            }
        }

        // ── Anexar DON (mesma mutacao do drag humano: AttachDonToCard e publico;
        //    lider = iDeployIdx -1). CheckForAttachDonAction dispara eventuais
        //    triggers "when DON attached" do lider, como no fluxo original. ──
        private static readonly MethodInfo _mCheckForAttachDon =
            AccessTools.Method(typeof(GameplayLogicScript), "CheckForAttachDonAction");
        // Mesmo helper de combat log que o arraste humano usa (LogLine privado).
        // Sem chama-lo, o DON anexado pelo bot nao aparece no combat log e a
        // metrica de agressao (don_por_atk) subconta o bot. Ver comentario no
        // TryAttachDon.
        private static readonly MethodInfo _mLogLine =
            AccessTools.Method(typeof(GameplayLogicScript), "LogLine");

        public static bool TryAttachDon(GameplayLogicScript gls, PlayerState botPs,
                                        int cardId, int count, GameStateDto dto)
        {
            int deployIdx;
            var go = FindCard(botPs.Lgo_MyDeploy, cardId);
            if (go != null)
            {
                deployIdx = botPs.Lgo_MyDeploy.IndexOf(go);
            }
            else if (dto.bot.leader != null && dto.bot.leader.deckUniqueId == cardId
                     && botPs.Lgo_MyLeader != null && botPs.Lgo_MyLeader.Count > 0)
            {
                go = botPs.Lgo_MyLeader[0];
                deployIdx = -1;
            }
            else
            {
                Plugin.Log.LogWarning($"[Bot] attach_don: carta {cardId} nao encontrada");
                return false;
            }

            int attached = 0;
            for (int i = 0; i < count; i++)
            {
                var don = botPs.FirstAvailableDon();
                if (don == null) break;
                gls.AttachDonToCard(botPs, deployIdx, botPs.FindIndexOfDonCard(don));
                attached++;
            }
            if (attached > 0)
            {
                _mCheckForAttachDon.Invoke(gls, new object[] { attached });
                // Emite a MESMA linha de combat log que o arraste humano
                // (Log.AttachDonMulti, GameplayLogicScript:8002/8269). O bot
                // chamava AttachDonToCard direto e pulava o LogLine, entao seu
                // DON nunca aparecia no combat log ([You] Attach ... Don to ...)
                // e o parse_combat_log (RE_ATTACH) subcontava a agressao dele —
                // don_por_atk e a metrica-chave da investigacao de passividade.
                // total = DON anexado na carta APOS este attach (i2 do log).
                try
                {
                    var acls = go.GetComponent<CardLogicScript>();
                    int total = acls != null ? acls.lgo_AttachedDon.Count : attached;
                    _mLogLine.Invoke(gls, new object[]
                    {
                        "Log.AttachDonMulti", true, gls.CardName(go), "", attached, total,
                        ulong.MaxValue
                    });
                }
                catch (System.Exception e)
                {
                    Plugin.Log.LogWarning($"[Bot] attach_don: LogLine falhou ({e.Message})");
                }
            }

            Plugin.Log.LogInfo($"[Bot] attach_don: {attached}/{count} DON em {CodeOf(go)}");
            return attached > 0;
        }

        public static void EndTurn(GameplayLogicScript gls)
        {
            gls.bConfirmEnd = false;   // pula o dialogo de confirmacao
            gls.ChoiceButtonClicked(ButtonChoiceType.EndTurn, -1);
        }

        private static bool TryPlay(GameplayLogicScript gls, PlayerState botPs, int cardId)
        {
            var go = FindCard(botPs.Lgo_MyHand, cardId);
            if (go == null)
            {
                Plugin.Log.LogWarning($"[Bot] play: carta {cardId} nao encontrada na mao");
                return false;
            }

            // Caminho do clique humano: seleciona a carta (o jogo valida custo
            // e adiciona as opcoes + seta go_PendingChoice)...
            _mClickDuringAction.Invoke(gls, new object[] { go });

            // ...e confirma se o jogo aceitou a selecao
            var pending = _fPendingChoice.GetValue(gls) as GameObject;
            if (pending != go)
            {
                Plugin.Log.LogWarning($"[Bot] play: jogo recusou {CodeOf(go)} (custo? restricao?)");
                return false;
            }

            var cls = go.GetComponent<CardLogicScript>();
            bool isEvent = cls != null && cls.myCard.cardDef != null
                        && cls.myCard.cardDef.cardType == CardType.Event;

            if (isEvent)
            {
                // EVENT nao usa Deploy (Deploy() pagaria o DON sem efeito!).
                // O clique adicionou botoes CardAction — replica a busca do
                // indice da primeira acao ativavel (EventFindPossibleActions).
                int idx = FindActivatableMainIndex(cls!);
                if (idx < 0)
                {
                    Plugin.Log.LogWarning($"[Bot] play: evento {CodeOf(go)} sem acao ativavel — cancel");
                    gls.ChoiceButtonClicked(ButtonChoiceType.Cancel, -1);
                    return false;
                }
                gls.ChoiceButtonClicked(ButtonChoiceType.CardAction, idx);
                Plugin.Log.LogInfo($"[Bot] play EVENT: {CodeOf(go)} (acao {idx})");
                return true;
            }

            gls.ChoiceButtonClicked(ButtonChoiceType.Deploy, -1);
            Plugin.Log.LogInfo($"[Bot] play: {CodeOf(go)}");
            return true;
        }

        // Indice da primeira acao [Activate: Main] ativavel da carta
        // (V3 com CanActivateAction; fallback old-style por actionTrigger)
        private static int FindActivatableMainIndex(CardLogicScript cls)
        {
            var v3 = cls.V3Actions(false);
            for (int i = 0; i < v3.Count; i++)
                if (v3[i].proc.ActivateMain && cls.CanActivateAction(i)) return i;
            var cas = cls.GetCardActions();
            for (int j = 0; j < cas.Count; j++)
                if (cas[j].actionTrigger.ActivateMain) return j;
            return -1;
        }

        // [Activate: Main] de carta EM CAMPO (lider/personagem/stage) — ex:
        // Laffitte OP09-095 (search). Mesmo caminho do clique humano: o jogo
        // valida e paga o custo (rest da carta/DON) sozinho.
        public static bool TryActivate(GameplayLogicScript gls, PlayerState botPs,
                                       int cardId, GameStateDto dto)
        {
            var go = FindCard(botPs.Lgo_MyDeploy, cardId)
                  ?? FindCard(botPs.Lgo_MyStage, cardId);
            if (go == null && dto.bot.leader != null && dto.bot.leader.deckUniqueId == cardId
                && botPs.Lgo_MyLeader != null && botPs.Lgo_MyLeader.Count > 0)
            {
                go = botPs.Lgo_MyLeader[0];
            }
            if (go == null)
            {
                Plugin.Log.LogWarning($"[Bot] activate: carta {cardId} nao encontrada em campo");
                return false;
            }

            _mClickDuringAction.Invoke(gls, new object[] { go });
            var pending = _fPendingChoice.GetValue(gls) as GameObject;
            if (pending != go)
            {
                Plugin.Log.LogWarning($"[Bot] activate: jogo recusou selecao de {CodeOf(go)}");
                return false;
            }

            var cls = go.GetComponent<CardLogicScript>();
            int idx = cls != null ? FindActivatableMainIndex(cls) : -1;
            if (idx < 0)
            {
                Plugin.Log.LogWarning($"[Bot] activate: {CodeOf(go)} sem acao ativavel — cancel");
                gls.ChoiceButtonClicked(ButtonChoiceType.Cancel, -1);
                return false;
            }
            gls.ChoiceButtonClicked(ButtonChoiceType.CardAction, idx);
            Plugin.Log.LogInfo($"[Bot] activate: {CodeOf(go)} (acao {idx})");
            return true;
        }

        private static bool TryAttack(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs,
                                      int attackerId, int targetId, int donToAttach, GameStateDto dto)
        {
            // Regra do jogo (mesma validacao do FindPossibleCardActions):
            // sem ataque no turno 1 do jogo
            if (gls.gsv_CurrentGame.iTurnNumber <= 1)
            {
                Plugin.Log.LogInfo("[Bot] attack: turno 1 — nao pode atacar");
                return false;
            }

            var attacker = FindCard(botPs.Lgo_MyDeploy, attackerId);
            // Lider: deckUniqueID pode ser -1/0 — compara com o uid que NOS
            // enviamos no DTO (lido do mesmo objeto)
            if (attacker == null && dto.bot.leader != null && dto.bot.leader.deckUniqueId == attackerId
                && botPs.Lgo_MyLeader != null && botPs.Lgo_MyLeader.Count > 0)
            {
                attacker = botPs.Lgo_MyLeader[0];
            }
            if (attacker == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: atacante {attackerId} nao encontrado");
                return false;
            }

            // Validacao propria (replica do FindPossibleCardActions): rested/summon sick
            var acls = attacker.GetComponent<CardLogicScript>();
            if (acls == null || acls.myCard.bTapped)
            {
                Plugin.Log.LogWarning("[Bot] attack: atacante rested");
                return false;
            }

            GameObject? target = null;
            if (targetId == 0 || (dto.opp.leader != null && dto.opp.leader.deckUniqueId == targetId))
            {
                if (oppPs.Lgo_MyLeader != null && oppPs.Lgo_MyLeader.Count > 0)
                    target = oppPs.Lgo_MyLeader[0];
            }
            else
            {
                target = FindCard(oppPs.Lgo_MyDeploy, targetId);
            }

            if (target == null)
            {
                Plugin.Log.LogWarning($"[Bot] attack: alvo {targetId} nao encontrado");
                return false;
            }

            // DON do engine SO depois de todas as validacoes — um ataque
            // recusado nao pode desperdicar DON (aconteceu no turno 1)
            if (donToAttach > 0)
                TryAttachDon(gls, botPs, attackerId, donToAttach, dto);

            // Fluxo real: go_PendingChoice -> StartAttack() -> clique no alvo
            _fPendingChoice.SetValue(gls, attacker);
            _mStartAttack.Invoke(gls, null);
            _mClickAttackTarget.Invoke(gls, new object[] { target, false });
            Plugin.Log.LogInfo($"[Bot] attack: {CodeOf(attacker)} -> {CodeOf(target)} (don {donToAttach})");
            return true;
        }

        private static GameObject? FindCard(List<GameObject>? list, int deckUniqueId)
        {
            if (list == null) return null;
            foreach (var go in list)
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null && cls.myCard.deckUniqueID == deckUniqueId)
                    return go;
            }
            return null;
        }

        private static string CodeOf(GameObject go)
        {
            var cls = go.GetComponent<CardLogicScript>();
            return cls != null && cls.myCard.cardDef != null ? cls.myCard.cardDef.cardID : "?";
        }
    }
}
