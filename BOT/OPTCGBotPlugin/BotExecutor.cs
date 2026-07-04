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
        private static readonly MethodInfo _mLastDrawnCard =
            AccessTools.Method(typeof(GameplayLogicScript), "LastDrawnCard");

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

        // Descarta as cartas de counter indicadas e resolve o ataque
        public static void PlayCounters(GameplayLogicScript gls, PlayerState botPs, List<int> counterIds)
        {
            gls.bConfirmCounter = false;   // descarta direto, sem dialogo de confirmacao
            foreach (int id in counterIds)
            {
                var go = FindCard(botPs.Lgo_MyHand, id);
                if (go == null)
                {
                    Plugin.Log.LogWarning($"[Bot] counter: carta {id} nao encontrada na mao");
                    continue;
                }
                _mDiscardCounter.Invoke(gls, new object[] { go });
                Plugin.Log.LogInfo($"[Bot] counter: {CodeOf(go)}");
            }
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
        private static readonly FieldInfo _fOfferingDownside =
            AccessTools.Field(typeof(GameplayLogicScript), "bOfferingDownside");

        public static bool IsOfferingDownside(GameplayLogicScript gls)
            => _fOfferingDownside.GetValue(gls) is bool b && b;

        // Codigo da carta cujo efeito esta resolvendo
        public static string? ActorCode(GameplayLogicScript gls)
        {
            var actor = gls.acaActive?.goActor;
            var cls = actor != null ? actor.GetComponent<CardLogicScript>() : null;
            return cls != null && cls.myCard.cardDef != null ? cls.myCard.cardDef.cardID : null;
        }

        // O efeito pendente pertence ao bot?
        public static bool PendingActionIsMine(GameplayLogicScript gls, PlayerState botPs)
        {
            var actor = gls.acaActive?.goActor;
            if (actor == null) return false;
            try { return gls.FindCardOwner(actor) == botPs; }
            catch { return false; }
        }

        // Todos os alvos clicaveis possiveis, com zona (o jogo valida cada clique)
        public static List<EngineClient.TargetCandidate> CollectTargetCandidates(
            PlayerState botPs, PlayerState oppPs)
        {
            var list = new List<EngineClient.TargetCandidate>();
            void Add(List<GameObject>? zone, string name)
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
                        });
                }
            }
            Add(botPs.Lgo_MyHand,   "own_hand");
            Add(botPs.Lgo_MyDeploy, "own_board");
            Add(oppPs.Lgo_MyDeploy, "opp_board");
            Add(botPs.Lgo_MyLeader, "own_leader");
            Add(oppPs.Lgo_MyLeader, "opp_leader");
            Add(botPs.Lgo_MyStage,  "own_stage");
            Add(oppPs.Lgo_MyStage,  "opp_stage");
            return list;
        }

        // Clica num candidato (mesmo caminho do clique humano; o jogo valida
        // via CardIsViableTarget/V3 e ignora cliques invalidos)
        public static bool ClickTargetCandidate(GameplayLogicScript gls, PlayerState botPs,
                                                PlayerState oppPs, int targetId)
        {
            var go = FindCard(botPs.Lgo_MyHand, targetId)
                  ?? FindCard(botPs.Lgo_MyDeploy, targetId)
                  ?? FindCard(oppPs.Lgo_MyDeploy, targetId)
                  ?? FindCard(botPs.Lgo_MyLeader, targetId)
                  ?? FindCard(oppPs.Lgo_MyLeader, targetId)
                  ?? FindCard(botPs.Lgo_MyStage, targetId)
                  ?? FindCard(oppPs.Lgo_MyStage, targetId);
            if (go == null)
                return false;
            _mClickDuringCardAction.Invoke(gls, new object[] { go });
            Plugin.Log.LogInfo($"[Bot] alvo de efeito: {CodeOf(go)}");
            return true;
        }

        public static void CancelPendingAction(GameplayLogicScript gls)
        {
            gls.ChoiceButtonClicked(ButtonChoiceType.Cancel, -1);
            Plugin.Log.LogInfo("[Bot] efeito pendente: Cancel");
        }

        public static bool ExecuteOne(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs,
                                      BotAction action, GameStateDto dto)
        {
            switch (action.type)
            {
                case "play":
                    return TryPlay(gls, botPs, action.cardId);
                case "attack":
                    return TryAttack(gls, botPs, oppPs, action.cardId, action.targetId, dto);
                default:
                    Plugin.Log.LogWarning($"[Bot] tipo de acao desconhecido: {action.type}");
                    return false;
            }
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
            // e adiciona a opcao Deploy + seta go_PendingChoice)...
            _mClickDuringAction.Invoke(gls, new object[] { go });

            // ...e confirma se o jogo aceitou a selecao
            var pending = _fPendingChoice.GetValue(gls) as GameObject;
            if (pending != go)
            {
                Plugin.Log.LogWarning($"[Bot] play: jogo recusou {CodeOf(go)} (custo? restricao?)");
                return false;
            }

            gls.ChoiceButtonClicked(ButtonChoiceType.Deploy, -1);
            Plugin.Log.LogInfo($"[Bot] play: {CodeOf(go)}");
            return true;
        }

        private static bool TryAttack(GameplayLogicScript gls, PlayerState botPs, PlayerState oppPs,
                                      int attackerId, int targetId, GameStateDto dto)
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

            // Fluxo real: go_PendingChoice -> StartAttack() -> clique no alvo
            _fPendingChoice.SetValue(gls, attacker);
            _mStartAttack.Invoke(gls, null);
            _mClickAttackTarget.Invoke(gls, new object[] { target, false });
            Plugin.Log.LogInfo($"[Bot] attack: {CodeOf(attacker)} -> {CodeOf(target)}");
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
