using System.Collections.Generic;
using UnityEngine;

namespace OPTCGBotPlugin
{
    // Converte PlayerState (objetos vivos do Unity) em GameStateDto (JSON-serializavel)
    // Nomes de campos verificados contra o decompilado (dnspy-export):
    //   LiveCard: cardDef, deckUniqueID, cardPower, bTapped, bSummonSick (struct!)
    //   CardDefinition: cardID, cardCost
    //   PlayerState: Lgo_MyHand, Lgo_MyDeploy, Lgo_MyLifeDeck, Lgo_MyLeader, Lgo_MyDonCostArea
    public static class GameStateBuilder
    {
        public static GameStateDto Build(PlayerState botPs, PlayerState oppPs, GameplayLogicScript gls)
        {
            return new GameStateDto
            {
                turnNumber = gls.gsv_CurrentGame.iTurnNumber,
                bot = BuildPlayer(botPs, gls),
                opp = BuildPlayer(oppPs, gls),
            };
        }

        private static PlayerDto BuildPlayer(PlayerState ps, GameplayLogicScript gls)
        {
            var dto = new PlayerDto();
            CountDon(ps, out dto.activeDon, out dto.restedDon);

            // Mao
            foreach (var go in ps.Lgo_MyHand ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null)
                    dto.hand.Add(CardToDto(cls, go, gls));
            }

            // Campo (personagens em jogo = deploy area)
            foreach (var go in ps.Lgo_MyDeploy ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null)
                    dto.board.Add(CardToDto(cls, go, gls));
            }

            // Vida
            foreach (var go in ps.Lgo_MyLifeDeck ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null)
                    dto.life.Add(CardToDto(cls, go, gls));
            }

            // Lider
            if (ps.Lgo_MyLeader != null && ps.Lgo_MyLeader.Count > 0 && ps.Lgo_MyLeader[0] != null)
            {
                var goLeader = ps.Lgo_MyLeader[0];
                var cls = goLeader.GetComponent<CardLogicScript>();
                if (cls != null)
                    dto.leader = CardToDto(cls, goLeader, gls);
            }

            return dto;
        }

        // LiveCard e struct — recebemos uma copia, leitura apenas.
        // Recebe o CardLogicScript inteiro porque lgo_AttachedDon vive nele.
        // power = poder ATUAL via CardPower do jogo (inclui buffs/debuffs e
        // passivas de campo, ex: -2000 do Krieg — invisiveis no myCard.cardPower),
        // sem contar When Attacking nem DON anexado (o engine soma o DON sozinho).
        private static CardDto CardToDto(CardLogicScript cls, GameObject go, GameplayLogicScript gls)
        {
            var card = cls.myCard;
            int power;
            try { power = gls.CardPower(go, false, true); }
            catch { power = card.cardPower; }
            bool used = false;
            if (card.lb_ActionsUsed != null)
                foreach (bool b in card.lb_ActionsUsed)
                    if (b) { used = true; break; }
            return new CardDto
            {
                code         = card.cardDef != null ? card.cardDef.cardID : "",
                cost         = card.cardDef != null ? card.cardDef.cardCost : 0,
                power        = power,
                rested       = card.bTapped,
                justPlayed   = card.bSummonSick,
                deckUniqueId = card.deckUniqueID,
                donAttached  = cls.lgo_AttachedDon != null ? cls.lgo_AttachedDon.Count : 0,
                actionUsed   = used,
            };
        }

        // DON ativo = nao-tapped na cost area; rested = tapped
        private static void CountDon(PlayerState ps, out int active, out int rested)
        {
            active = 0;
            rested = 0;
            foreach (var go in ps.Lgo_MyDonCostArea ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls == null) continue;
                if (cls.myCard.bTapped) rested++;
                else active++;
            }
        }
    }
}


