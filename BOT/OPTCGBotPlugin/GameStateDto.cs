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
        public int donAttached;   // DON anexados a esta carta (+1000 poder cada no proprio turno)
        public bool actionUsed;   // alguma acao da carta ja usada neste turno (lb_ActionsUsed)
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
        // "play" | "attack" | "attach_don" | "end_turn"
        public string type = "end_turn";
        // Para play/attack/attach_don: deckUniqueId da carta do bot
        public int cardId;
        // Para attack: deckUniqueId do alvo (0 = lider oponente)
        public int targetId;
        // attack: DON a anexar no atacante ANTES de declarar;
        // attach_don: quantos DON anexar na carta (ligar efeito/keyword)
        public int donToAttach;
    }
}
