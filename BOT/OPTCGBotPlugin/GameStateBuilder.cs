using System.Collections.Generic;
using UnityEngine;

namespace OPTCGBotPlugin
{
    // Converte PlayerState (objetos vivos do Unity) em GameStateDto (JSON-serializavel)
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
            var dto = new PlayerDto
            {
                activeDon = ps.Lgo_MyDonCostArea?.Count ?? 0,
                restedDon = CountRestedDon(ps),
            };

            // Mao
            foreach (var go in ps.Lgo_MyHand ?? new List<GameObject>())
            {
                var card = go?.GetComponent<CardLogicScript>()?.myCard;
                if (card != null)
                    dto.hand.Add(CardToDto(card));
            }

            // Campo (personagens)
            foreach (var go in ps.Lgo_MyBoard ?? new List<GameObject>())
            {
                var card = go?.GetComponent<CardLogicScript>()?.myCard;
                if (card != null)
                    dto.board.Add(CardToDto(card));
            }

            // Vida
            foreach (var go in ps.Lgo_MyLife ?? new List<GameObject>())
            {
                var card = go?.GetComponent<CardLogicScript>()?.myCard;
                if (card != null)
                    dto.life.Add(CardToDto(card));
            }

            // Lider
            if (ps.Lgo_MyLeader?.Count > 0)
            {
                var leaderCard = ps.Lgo_MyLeader[0]?.GetComponent<CardLogicScript>()?.myCard;
                if (leaderCard != null)
                    dto.leader = CardToDto(leaderCard);
            }

            return dto;
        }

        private static CardDto CardToDto(LiveCard card)
        {
            return new CardDto
            {
                code        = card.cardDef?.sCode ?? "",
                cost        = card.cardDef?.iCost ?? 0,
                power       = card.iPower,
                rested      = card.bTapped,
                justPlayed  = card.bJustPlayed,
                deckUniqueId = card.deckUniqueID,
            };
        }

        private static int CountRestedDon(PlayerState ps)
        {
            int count = 0;
            foreach (var go in ps.Lgo_MyDonCostArea ?? new List<GameObject>())
            {
                var card = go?.GetComponent<CardLogicScript>()?.myCard;
                if (card != null && card.bTapped)
                    count++;
            }
            return count;
        }
    }
}
