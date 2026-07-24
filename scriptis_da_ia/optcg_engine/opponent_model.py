"""
opponent_model.py — Leitura do Oponente / Opponent Reading (fase 1)
====================================================================
Constrói amostras Monte Carlo plausíveis da mão e vida do oponente, a
partir SOMENTE de informação observável (regra confirmada em sessão de
23/06):

  - Trash: sempre público.
  - Board (field_chars, field_stage, leader): sempre público.
  - Cartas de vida que viraram por DANO NORMAL: NÃO reveladas — só o dono
    sabe qual carta é. Entram na mão como "desconhecida".
  - Cartas adicionadas à mão por busca com a palavra "reveal" no texto
    oficial (padrão "look at N; reveal up to 1 [filtro] and add to hand",
    181 das 221 cards de busca do banco): REVELADAS — conhecidas enquanto
    permanecerem na mão. Rastreado em GameState.revealed_to_opponent via
    GameState.known_hand_cards().
  - Decklist COMPLETA do oponente: sempre conhecida (produto sempre informa
    a lista exata — colada pelo usuário ou do banco de meta —, nunca
    arquétipo genérico estimado por densidade).

A "mão fictícia" nunca é guardada como estado — é recalculada a cada
amostra Monte Carlo, a partir do estado observável real no momento da
chamada. Isso garante que cartas reveladas conhecidas SEMPRE aparecem
certas na amostra, e o resto é sorteado da população restante.

Mão e vida fictícias são sorteadas de uma ÚNICA população compartilhada
(uma carta não pode aparecer simultaneamente nas duas, porque é a mesma
cópia física do baralho) — ver `OpponentModel.sample()`.
"""
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from optcg_engine.decision_engine import Card, GameState


@dataclass
class OpponentModel:
    """
    Modelo de leitura do oponente para UM GameState observável. Não
    armazena nenhuma amostra — `sample()` gera uma nova combinação
    plausível de mão+vida fictícias a cada chamada, para uso em uma única
    iteração do Monte Carlo dentro de `_simulate_sequence`.

    full_decklist: as 50 cartas do deck do oponente (lista com repetição
        se houver múltiplas cópias da mesma carta) — SEM o líder. Vem da
        decklist completa e conhecida (colada pelo usuário ou registrada
        em meta_decklists), nunca estimada por densidade de arquétipo.
    """
    full_decklist: list  # list['Card']

    def _known_population_excluded(self, opp: 'GameState') -> Counter:
        """
        Conta, por código de carta, quantas cópias já estão em zonas
        públicas ou conhecidas (trash, board, mão revelada) — essas saem
        da população disponível para sorteio, porque já sabemos
        exatamente onde estão.
        """
        excluded = Counter()
        for c in opp.trash:
            excluded[c.code] += 1
        for c in opp.field_chars:
            excluded[c.code] += 1
        if opp.field_stage is not None:
            excluded[opp.field_stage.code] += 1
        for c in opp.known_hand_cards():
            excluded[c.code] += 1
        # Vida conhecida (revelada por peek/efeito): sabemos onde essas copias
        # estao, entao saem da populacao de sorteio -- mesma logica da mao.
        for c in opp.known_life_cards():
            excluded[c.code] += 1
        return excluded

    def _available_pool(self, opp: 'GameState') -> list:
        """
        Population disponível para sorteio: decklist completa menos as
        cópias já observadas em zonas conhecidas. Não diferencia "está no
        deck" de "está na mão desconhecida" ou "está na vida desconhecida"
        -- do ponto de vista do observador, todas essas cópias são
        igualmente prováveis de estar em qualquer uma dessas 3 zonas
        ocultas, então uma única população serve para as 3.
        """
        excluded = self._known_population_excluded(opp)
        excluded = Counter(excluded)  # cópia para decrementar sem afetar o original
        pool = []
        for card in self.full_decklist:
            if excluded[card.code] > 0:
                excluded[card.code] -= 1
                continue
            pool.append(card)
        return pool

    def sample(self, opp: 'GameState', rng: random.Random = None) -> tuple[list, list]:
        """
        Gera UMA amostra Monte Carlo de (mão_fictícia, vida_fictícia),
        consistente com o estado observável atual de `opp`.

        Retorna (hand_sample, life_sample), ambas listas de Card (objetos
        distintos por amostra -- instâncias sorteadas do pool, não
        compartilhadas entre chamadas, para evitar um efeito de trigger ou
        counter em uma amostra contaminar outra).

        As cartas conhecidas (reveladas, ainda na mão) SEMPRE aparecem em
        hand_sample -- são certeza, não sorteio. O restante dos slots de
        mão e todos os slots de vida desconhecida são sorteados juntos de
        uma população compartilhada (ver módulo docstring).
        """
        rng = rng or random.Random()

        known_hand = opp.known_hand_cards()
        known_life = opp.known_life_cards()
        n_hand_unknown = max(0, len(opp.hand) - len(known_hand))
        # Vida conhecida (revelada por peek/efeito -- Katakuri, etc.) entra como
        # CERTEZA, so o resto da vida e sorteado. Antes toda a vida era
        # desconhecida (dano normal nunca revela); agora reveals persistidos
        # reduzem a incerteza.
        n_life_unknown = max(0, len(opp.life) - len(known_life))

        pool = self._available_pool(opp)
        rng.shuffle(pool)

        n_slots = n_hand_unknown + n_life_unknown
        sorteadas = pool[:n_slots]

        hand_sample = list(known_hand) + sorteadas[:n_hand_unknown]
        life_sample = list(known_life) + sorteadas[n_hand_unknown:n_hand_unknown + n_life_unknown]

        return hand_sample, life_sample

    def counter_available_in_sample(self, hand_sample: list) -> int:
        """Soma de counter disponível na amostra de mão (mesma semântica de GameState.counter_in_hand)."""
        return sum(c.counter for c in hand_sample if c.counter > 0)

    def blockers_in_sample(self, hand_sample: list) -> list:
        """
        Characters com [Blocker] que ESTARIAM na mão na amostra -- não se
        aplica diretamente (Blocker já em campo é observável de verdade,
        não amostrado); esta função existe só para o caso em que a
        simulação testa "e se ele jogasse essa carta de blocker da mão
        fictícia antes de bloquear" em sequências multi-turno. Uso
        esperado limitado nesta fase; mantido simples.
        """
        return [c for c in hand_sample if c.is_blocker()]


def build_opponent_model(full_decklist: list) -> OpponentModel:
    """
    Ponto de entrada simples: recebe a decklist completa (lista de Card,
    50 cartas, sem o líder) e devolve o OpponentModel pronto para usar
    repetidamente contra qualquer GameState observável daquele oponente
    durante a simulação.
    """
    return OpponentModel(full_decklist=full_decklist)