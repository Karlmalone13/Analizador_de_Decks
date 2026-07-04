using System.Collections.Generic;

namespace OPTCGBotPlugin
{
    // DTOs enviados ao servidor Python via JSON
    public class CardDto
    {
        public string code = "";
        public int cost;
        public int power;
        public bool rested;
        public bool justPlayed;
        public int deckUniqueId;  // ID unico dentro da partida (para identificar alvos)
    }

    public class PlayerDto
    {
        public List<CardDto> hand = new();
        public List<CardDto> board = new();
        public List<CardDto> life = new();
        public CardDto? leader;
        public int activeDon;
        public int restedDon;
    }

    public class GameStateDto
    {
        public int turnNumber;
        public PlayerDto bot = new();   // sempre P2 (jogador do bot)
        public PlayerDto opp = new();   // sempre P1 (jogador humano)
    }

    // Acao retornada pelo servidor Python
    public class BotAction
    {
        // "play" | "attack" | "end_turn" | "activate"
        public string type = "end_turn";
        // Para play/attack/activate: deckUniqueId da carta do bot
        public int cardId;
        // Para attack: deckUniqueId do alvo (0 = lider oponente)
        public int targetId;
    }
}
