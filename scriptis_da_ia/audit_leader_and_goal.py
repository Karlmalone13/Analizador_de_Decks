"""
audit_leader_and_goal.py
=========================
Fase 1 do plano "bot entende antes de jogar melhor" (HANDOFF, sessão de
14/07 pós-derrota Krieg vs Kid). NÃO escreve scoring novo — só prova, com
saída impressa, o que o motor hoje já sabe sobre (a) o efeito do líder que
está pilotando e (b) o objetivo "reduzir vida do oponente a 0 e finalizar",
ANTES de qualquer conserto de pontuação (Fase 2 em diante).

Mostra o TEXTO CRU da carta ao lado do que o parser entendeu, de propósito
— achado real 14/07: rodando esse script pro Krieg (OP15-001), o usuário
percebeu visualmente que o `activate_main` ("Rest up to 1 of your
opponent's Characters that has 2 or more DON!! cards given") tinha virado
`cost_lte: 99` no parser (ou seja: sem filtro nenhum, restava QUALQUER
personagem). Consertado no mesmo commit deste script (parse_rest_opp +
eligible_cards ganharam don_attached_gte). Deixar o texto cru visível é o
que permite achar esse tipo de coisa de novo, sem precisar ler JSON.

Uso:
  python audit_leader_and_goal.py Krieg
  python audit_leader_and_goal.py Kid
  python audit_leader_and_goal.py --list
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from optcg_engine.sim_bridge import load_sim_deck, list_decks
from optcg_engine.decision_engine import (
    Card, CardData, GameAnalyzer, GameState, get_card_effects,
)
from deck_profile import build_profile_from_codes

# Kinds de derived_axes que _derived_axes_value (decision_engine.py:~8206)
# de fato lê hoje ao calcular o score de um estado. Os outros kinds
# (ex: 'disruption') são calculados no perfil mas NÃO entram no score —
# isso é um GAP que a Fase 2 do plano deve fechar, não um estado aceitável.
_AXES_CONSUMIDOS = {'resource_staircase', 'bottleneck', 'inversion'}

_CSV_PATH = Path(__file__).parent / 'cards_rows.csv'


def _raw_card_text(code: str) -> str:
    """Texto CRU da carta (coluna 'text' do cards_rows.csv), pra comparar
    lado a lado com o que o parser entendeu -- é assim que se pega um
    parser errado, não lendo só o JSON já parseado."""
    with open(_CSV_PATH, encoding='utf-8') as f:
        for row in csv.reader(f):
            if row and row[0] == code:
                return row[5] if len(row) > 5 else ''
    return '(carta não encontrada no cards_rows.csv)'


def mk(code: str, name: str, power: int = 5000, cost: int = 4,
       card_type: str = "CHARACTER", color: str = "Black") -> Card:
    return Card(data=CardData(code=code, name=name, card_type=card_type,
                               color=color, cost=cost, power=power))


def _print_header(titulo: str) -> None:
    print()
    print("=" * 78)
    print(titulo)
    print("=" * 78)


def _print_effect_block(trig: str, block) -> None:
    print(f"  [{trig}]")
    if not isinstance(block, dict):
        print(f"    {block}")
        return
    steps = block.get('steps') or []
    for st in steps:
        print(f"    jogada: {st}")
    # Mostra QUALQUER outra chave do bloco (conditions, don_requirement,
    # once_per_turn, costs, ...) de forma genérica -- um audit anterior
    # dessa mesma tela só imprimia 'conditions'/'steps' e deixava
    # 'don_requirement' invisível, escondendo que ele JÁ estava parseado
    # certo (bug de exibição, não de parser).
    for chave, valor in block.items():
        if chave == 'steps':
            continue
        print(f"    {chave}: {valor}")


def audit_leader_effect(leader: Card, cards: list) -> dict:
    _print_header(f"1) EFEITO DO LÍDER: TEXTO CRU vs O QUE O PARSER ENTENDEU")
    print(f"  Texto cru (cards_rows.csv):")
    for linha in _raw_card_text(leader.code).split('\n'):
        print(f"    {linha}")

    print(f"\n  O parser (get_card_effects) entendeu isto:")
    effects = get_card_effects(leader.code)
    if not effects:
        print("    (nenhum efeito parseado pro código do líder -- se o texto"
              " acima não está vazio, isso é um parser faltando, não uma"
              " carta sem habilidade)")
    else:
        for trig, block in effects.items():
            _print_effect_block(trig, block)
    print("\n  >> Compare as duas caixas acima: se alguma condição do texto"
          " cru (custo, filtro de alvo, 'if you have N DON given' etc.) não"
          " aparecer refletida no que o parser entendeu, é um gap de"
          " parser -- reportar antes de seguir pra Fase 2.")

    _print_header("2) O QUE O MOTOR DERIVOU DO ARQUÉTIPO (líder + resto do deck)")
    codes = [c.code for c in cards] + [leader.code]
    profile = build_profile_from_codes(codes)

    arche = profile.get('archetype', {})
    print(f"  archetype.dominante = {arche.get('dominante')}")
    print(f"  archetype.mix       = {arche.get('mix')}")
    print("  usado na decisão hoje? NÃO -- é calculado mas nenhuma função de"
          " pontuação lê esse valor. (única exceção: entra em"
          " _go_first_heuristic pra decidir quem começa jogando, e mesmo ali"
          " o líder é excluído do cálculo do perfil.) Isso é um GAP a"
          " corrigir na Fase 2, não uma escolha de design.")

    roles = profile.get('roles', {})
    print(f"\n  roles = {roles}")
    print("  usado na decisão hoje? NÃO -- calculado, nunca lido por"
          " nenhuma função de pontuação. GAP a corrigir na Fase 2.")

    axes = profile.get('derived_axes', [])
    print(f"\n  derived_axes ({len(axes)} eixo(s) detectado(s) pra este deck):")
    if not axes:
        print("    (nenhum eixo derivado passou do filtro de relevância"
              " prior_weight>=5 pra este deck+líder)")
    for ax in axes:
        kind = ax.get('kind')
        consome = kind in _AXES_CONSUMIDOS
        tag = ("SIM, via _derived_axes_value -- pesa no score de qualquer"
               " estado simulado" if consome else
               "NÃO -- calculado, mas esse tipo de eixo (kind="
               f"{kind!r}) não tem leitura em _derived_axes_value hoje")
        print(f"    - id={ax.get('id')} kind={kind} "
              f"prior_weight={ax.get('prior_weight')}")
        print(f"      nota: {ax.get('nota')}")
        print(f"      usado na decisão hoje? {tag}")

    return profile


def audit_lethal_detection(leader: Card) -> None:
    _print_header("3) OBJETIVO DO JOGO: o bot sabe reconhecer LETHAL (reduzir vida do oponente a 0)?")

    # Cenário A: lethal óbvio -- meu líder + 1 atacante forte vs vida baixa
    # do oponente, sem blocker/counter pra defender.
    me_a = GameState(leader=leader, don_available=4)
    me_a.field_chars = [mk("TEST-ATK1", "Atacante Teste", power=9000, cost=4)]
    opp_a = GameState(
        leader=mk("TEST-OPPL", "Líder Oponente Teste", card_type="LEADER",
                   color="Green", power=5000),
        don_available=0,
    )
    opp_a.life = [mk(f"TEST-LIFE{i}", "Vida", cost=0) for i in range(1)]
    an_a = GameAnalyzer(me_a, opp_a)
    lethal_a = an_a.can_lethal_this_turn()
    prio_a = an_a.analysis_priority()
    print(f"  Cenário A -- vida do oponente = 1, meu líder + 1 atacante de"
          f" 9000 de poder, oponente sem blocker/counter disponível:")
    print(f"    can_lethal_this_turn() = {lethal_a}   (esperado: True)")
    print(f"    analysis_priority()    = {prio_a!r}   (esperado: 'LETHAL')")

    # Cenário B: sem lethal -- vida alta do oponente, mesmo ataque disponível.
    me_b = GameState(leader=leader, don_available=4)
    me_b.field_chars = [mk("TEST-ATK1", "Atacante Teste", power=9000, cost=4)]
    opp_b = GameState(
        leader=mk("TEST-OPPL", "Líder Oponente Teste", card_type="LEADER",
                   color="Green", power=5000),
        don_available=0,
    )
    opp_b.life = [mk(f"TEST-LIFE{i}", "Vida", cost=0) for i in range(5)]
    an_b = GameAnalyzer(me_b, opp_b)
    lethal_b = an_b.can_lethal_this_turn()
    print(f"\n  Cenário B -- mesmo board, vida do oponente = 5 (dano"
          f" insuficiente pra fechar o jogo):")
    print(f"    can_lethal_this_turn() = {lethal_b}   (esperado: False)")

    ok = lethal_a is True and prio_a == 'LETHAL' and lethal_b is False
    print(f"\n  RESULTADO: {'OK -- o motor reconhece lethal corretamente nos'
                            ' 2 cenários testados' if ok else 'FALHOU -- ver detalhes acima, isso é um problema sério'}")


def audit_summary(profile: dict) -> None:
    _print_header("4) RESUMO -- o que o bot USA pra decidir vs o que ele SÓ CALCULA e joga fora")
    usa_na_decisao = ["objetivo lethal (can_lethal_this_turn / analysis_priority)"]
    calculado_e_descartado = [
        "archetype.mix (Aggro/Controle/Ramp/Vida do próprio deck)",
        "roles (contagem de finisher/beater/counter_2000/trigger_payoff etc.)",
    ]
    for ax in profile.get('derived_axes', []):
        kind = ax.get('kind')
        alvo = usa_na_decisao if kind in _AXES_CONSUMIDOS else calculado_e_descartado
        alvo.append(f"derived_axis '{ax.get('id')}' (kind={kind})")

    print("  USA PRA DECIDIR (influencia o score de algum estado simulado):")
    for item in usa_na_decisao:
        print(f"    - {item}")
    print("\n  CALCULADO E DESCARTADO (existe no perfil do deck, mas nenhuma")
    print("  função de pontuação lê -- isso é o problema que motivou a Fase 2,")
    print("  não é assim que deveria ficar):")
    for item in calculado_e_descartado:
        print(f"    - {item}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", nargs="?", help="nome do deck (arquivo .deck sem extensão)")
    ap.add_argument("--list", action="store_true", help="lista decks disponíveis")
    args = ap.parse_args()

    if args.list or not args.deck:
        print("Decks disponíveis:")
        for name in list_decks():
            print(f"  {name}")
        if not args.deck:
            return

    leader, cards, _ = load_sim_deck(args.deck)
    print(f"Deck: {args.deck}  |  Líder: {leader.code} {leader.name}  |  "
          f"{len(cards)} cartas no corpo do deck")

    profile = audit_leader_effect(leader, cards)
    audit_lethal_detection(leader)
    audit_summary(profile)


if __name__ == "__main__":
    main()
