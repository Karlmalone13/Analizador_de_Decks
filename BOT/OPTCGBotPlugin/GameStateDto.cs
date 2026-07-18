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
        // Travado de atacar por efeito do oponente (ex: Teach OP09-093:
        // "that Character cannot attack until the end of your opponent's
        // next turn") — lido via CardCantAttack(), o mesmo metodo que o
        // jogo usa pra decidir se deixa o HUMANO clicar num atacante.
        // Achado real 09/07: StartAttack() (chamado pelo bot via reflection)
        // NAO valida isso sozinho — so a camada de clique que normalmente
        // filtra antes de chegar la, que o bot pula. Sem ler esse campo,
        // o bot atacava com personagens travados e o jogo deixava.
        public bool cantAttack;
        public int deckUniqueId;  // ID unico dentro da partida (para identificar alvos)
        public int donAttached;   // DON anexados a esta carta (+1000 poder cada no proprio turno)
        public bool actionUsed;   // alguma acao da carta ja usada neste turno (lb_ActionsUsed)
        // Poder ao ATACAR (CardPower bAttacking=true, sem DON): inclui passivas
        // de campo que so valem no ataque (ex: -2000 do deck do Krieg) — o
        // CardPower com bAttacking=false NAO soma essas (gap visto 06/07)
        public int powerAtk;
    }

    public class PlayerDto
    {
        public List<CardDto> hand = new();
        public List<CardDto> board = new();
        public List<CardDto> life = new();
        public CardDto? leader;
        // Carta STAGE em campo (zona propria, Lgo_MyStage no jogo — nunca
        // veio junto com board/Lgo_MyDeploy, que so tem personagens).
        // Achado 07/07: sem isso o motor nao sabia que uma stage existia
        // (ex: Fullalead), entao nunca oferecia o Activate:Main dela.
        public CardDto? stage;
        // Lixeira (informacao PUBLICA no jogo real — o oponente ve o trash).
        // Achado 11/07: sem isso o motor via gs.trash=[] ao vivo e (a) o
        // [Counter] do Ground Death (trash_gte:10) nunca era usavel, (b) a
        // imunidade dos Celestial Dragons (trash_gte:7) nunca ativava, (c) o
        // progresso do GamePlan (len(trash) < trash_target) ficava em 0.
        public List<CardDto> trash = new();
        // Contagem do deck (tamanho e publico; conteudo continua oculto) —
        // substitui os 10 placeholders que o server.py inventava.
        public int deckCount;
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
        // Correlaciona decisao do engine com tentativa/confirmacao no plugin.
        public string decisionId = "";
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
