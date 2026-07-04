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
        public static GameStateDto Build(PlayerState p1, PlayerState p2, GameplayLogicScript gls)
        {
            return new GameStateDto
            {
                turnNumber = gls.gsv_CurrentGame.iTurnNumber,
                bot = BuildPlayer(p2),   // bot = P2
                opp = BuildPlayer(p1),   // oponente = P1
            };
        }

        private static PlayerDto BuildPlayer(PlayerState ps)
        {
            var dto = new PlayerDto();
            CountDon(ps, out dto.activeDon, out dto.restedDon);

            // Mao
            foreach (var go in ps.Lgo_MyHand ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null)
                    dto.hand.Add(CardToDto(cls.myCard));
            }

            // Campo (personagens em jogo = deploy area)
            foreach (var go in ps.Lgo_MyDeploy ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null)
                    dto.board.Add(CardToDto(cls.myCard));
            }

            // Vida
            foreach (var go in ps.Lgo_MyLifeDeck ?? new List<GameObject>())
            {
                var cls = go != null ? go.GetComponent<CardLogicScript>() : null;
                if (cls != null)
                    dto.life.Add(CardToDto(cls.myCard));
            }

            // Lider
            if (ps.Lgo_MyLeader != null && ps.Lgo_MyLeader.Count > 0 && ps.Lgo_MyLeader[0] != null)
            {
                var cls = ps.Lgo_MyLeader[0].GetComponent<CardLogicScript>();
                if (cls != null)
                    dto.leader = CardToDto(cls.myCard);
            }

            return dto;
        }

        // LiveCard e struct — recebemos uma copia, leitura apenas
        private static CardDto CardToDto(LiveCard card)
        {
            return new CardDto
            {
                code         = card.cardDef != null ? card.cardDef.cardID : "",
                cost         = card.cardDef != null ? card.cardDef.cardCost : 0,
                power        = card.cardPower,
                rested       = card.bTapped,
                justPlayed   = card.bSummonSick,
                deckUniqueId = card.deckUniqueID,
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
