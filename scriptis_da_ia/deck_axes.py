"""
deck_axes.py
============
Tres eixos de leitura de um deck -- SINERGIA, DEFESA e ATAQUE -- calculados
no MOTOR, a partir dos efeitos PARSEADOS (`card_analysis_db.json`), nunca de
texto cru no consumidor.

POR QUE EXISTE (06/09/2026, pedido do usuario)
----------------------------------------------
O painel "Analisador Inteligente" do front era uma calculadora
hipergeometrica: os 8 tiles respondiam todos a mesma pergunta -- "qual a
chance de eu ter isso nas 5 primeiras cartas?" -- e o Score saia dai. O
usuario resumiu o defeito: *"esse 49 tem que ser a sinergia do deck e
capacidade de defesa etc"*.

Defeitos concretos que este modulo ataca (levantados na sessao):
  1. Media so a ABERTURA e chama de nota do deck. Uma partida tem 10+ turnos.
  2. "Pelo menos 1" satura: 26 counters dao 98%, 40 dariam ~100% -- a
     metrica nao distingue "suficiente" de "excesso".
  3. Nao existe INTERACAO entre cartas em lugar nenhum da conta, mesmo com
     `detect_deck_synergies` ja pronto no motor e ignorado pelo painel.
  4. Defesa nao era medida como defesa: blocker e counter apareciam como
     tiles independentes, e a vida do lider (4 no Krieg, 20% menos que um
     lider de 5) so era usada pro trigger.

O QUE ESTE MODULO NAO RESOLVE (honestidade sobre escopo)
--------------------------------------------------------
Os PESOS aqui continuam escolhidos por mim, nao validados contra vitoria.
E o mesmo defeito que os cortes tinham antes de virarem percentis do meta --
so que agora esta concentrado num lugar so, declarado, e facil de calibrar
quando alguem rodar o passo de validacao (comparar eixo x winrate simulado
dos 184 decks, que o motor consegue rodar). Ate la, os numeros crus servem
pra COMPARAR decks entre si (via percentis do meta), nao como verdade
absoluta sobre um deck isolado.
"""
from collections import defaultdict

from synergy_states import detect_deck_synergies


# ── helpers ─────────────────────────────────────────────────────────────────

def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _qtd(card):
    """Copias da carta no deck (o chamador anexa `quantity`)."""
    return int(card.get('quantity') or 1)


def _steps(card):
    """Todos os steps de efeito da carta, de qualquer gatilho."""
    effects = card.get('effects') or {}
    if isinstance(effects, list):
        return [s for s in effects if isinstance(s, dict)]
    out = []
    for trig, data in effects.items():
        if isinstance(data, dict):
            out.extend([s for s in (data.get('steps') or []) if isinstance(s, dict)])
        elif isinstance(data, list):
            out.extend([s for s in data if isinstance(s, dict)])
    return out


# ── EIXO 1: SINERGIA ────────────────────────────────────────────────────────

def _eixo_sinergia(leader, main_cards):
    """
    Quanto as cartas do deck trabalham JUNTAS. Quatro componentes, todos
    lidos do efeito parseado:

    a) Estados compartilhados -- `detect_deck_synergies` (uma carta cria o
       estado, outra explora). Ja existia no motor e o painel ignorava.
    b) Cobertura de busca -- searcher so vale se o deck REALMENTE roda o que
       ele procura. Um searcher de {East Blue} num deck sem East Blue e
       carta morta, e nenhuma contagem de "8 searchers" enxerga isso.
    c) Gancho tribal -- cartas que citam o tipo do lider (via
       `referenced_types`, o campo que o parser ja extrai).
    d) Payoff de DON -- cartas que dao DON a aliados + cartas que ficam
       melhores com DON anexado.
    """
    detalhes = []

    # (a) estados compartilhados
    sinergias = detect_deck_synergies(main_cards)
    score_estados = sum(s.get('score', 0) for s in sinergias)
    for s in sinergias:
        detalhes.append({
            'tipo': 'estado', 'desc': s.get('desc'),
            'n': min(s.get('n_creators', 0), s.get('n_exploiters', 0)),
            'pontos': s.get('score', 0),
        })

    # (b) cobertura de busca: o que os searchers procuram existe no deck?
    tipos_no_deck = defaultdict(int)
    for c in main_cards:
        for t in (c.get('sub_types') or '').lower().split():
            tipos_no_deck[t] += _qtd(c)
    alvos_cobertos = alvos_totais = 0
    for c in main_cards:
        if not c.get('is_searcher'):
            continue
        refs = [str(r).lower() for r in (c.get('referenced_types') or []) if r]
        if not refs:
            # searcher generico (procura por custo/nome): sempre util
            alvos_cobertos += _qtd(c)
            alvos_totais += _qtd(c)
            continue
        for r in refs:
            alvos_totais += _qtd(c)
            if any(p in tipos_no_deck for p in r.split()):
                alvos_cobertos += _qtd(c)
    cobertura = (alvos_cobertos / alvos_totais) if alvos_totais else 0.0
    score_busca = 12 * cobertura
    if alvos_totais:
        detalhes.append({
            'tipo': 'busca',
            'desc': f'{cobertura*100:.0f}% das buscas do deck encontram alvo real',
            'n': alvos_totais, 'pontos': round(score_busca, 1),
        })

    # (c) gancho tribal com o tipo do lider
    tipos_lider = set((leader.get('sub_types') or '').lower().split()) if leader else set()
    ganchos = 0
    for c in main_cards:
        refs = ' '.join(str(r).lower() for r in (c.get('referenced_types') or []))
        if tipos_lider and any(t in refs for t in tipos_lider if len(t) > 3):
            ganchos += _qtd(c)
    score_gancho = min(ganchos, 20) * 0.6
    if ganchos:
        detalhes.append({
            'tipo': 'tribal', 'desc': f'{ganchos} copias citam o tipo do lider',
            'n': ganchos, 'pontos': round(score_gancho, 1),
        })

    # (d) payoff de DON
    da_don = sum(_qtd(c) for c in main_cards if c.get('gives_don'))
    quer_don = 0
    for c in main_cards:
        for s in _steps(c):
            if 'don_requirement' in s or 'don_attached_gte' in s:
                quer_don += _qtd(c)
                break
    score_don = min(da_don, quer_don) * 1.0
    if score_don:
        detalhes.append({
            'tipo': 'don', 'desc': f'{da_don} dao DON a aliados, {quer_don} ficam melhores com DON',
            'n': min(da_don, quer_don), 'pontos': round(score_don, 1),
        })

    bruto = score_estados + score_busca + score_gancho + score_don
    return round(bruto, 2), detalhes


# ── EIXO 2: DEFESA ──────────────────────────────────────────────────────────

def _eixo_defesa(leader, main_cards):
    """
    Capacidade de SOBREVIVER, nao "tenho blocker?".

    - Poder de counter TOTAL do deck (soma dos counter_amount), que e o
      recurso de fato gasto pra aguentar um turno -- diferente de "chance de
      ter pelo menos 1 counter", que satura.
    - Eventos de [Counter] (contam mais: costumam valer bem mais que 1000).
    - Blockers ponderados por EFICIENCIA (poder por custo): um blocker de
      custo 1 e 3000 de poder segura melhor que um de custo 4 e 4000.
    - Remocao defensiva (ko/rest/bounce), que evita dano antes de acontecer.
    - Vida do lider, multiplicador direto: 4 de vida aguenta 20% menos que 5.
    """
    detalhes = []
    poder_counter = sum(_num(c.get('counter')) * _qtd(c) for c in main_cards)
    eventos_counter = sum(_qtd(c) for c in main_cards if c.get('has_counter_event'))

    blocker_ef = 0.0
    n_blockers = 0
    for c in main_cards:
        if not c.get('is_blocker'):
            continue
        n_blockers += _qtd(c)
        custo = max(_num(c.get('cost'), 1), 1)
        blocker_ef += (_num(c.get('power')) / custo / 1000.0) * _qtd(c)

    remocao = sum(_qtd(c) for c in main_cards
                  if c.get('kos') or c.get('rests_opponent') or c.get('bounces'))

    vida = _num(leader.get('life'), 5) if leader else 5

    detalhes.append({'tipo': 'counter', 'desc': f'{poder_counter/1000:.0f}k de poder de counter no deck', 'n': int(poder_counter)})
    detalhes.append({'tipo': 'counter_evento', 'desc': f'{eventos_counter} eventos [Counter]', 'n': eventos_counter})
    detalhes.append({'tipo': 'blocker', 'desc': f'{n_blockers} blockers (eficiencia {blocker_ef:.1f})', 'n': n_blockers})
    detalhes.append({'tipo': 'remocao', 'desc': f'{remocao} copias com KO/rest/bounce', 'n': remocao})
    detalhes.append({'tipo': 'vida', 'desc': f'{vida:.0f} de vida no lider', 'n': int(vida)})

    bruto = ((poder_counter / 1000.0) * 1.0
             + eventos_counter * 2.0
             + blocker_ef * 3.0
             + remocao * 1.0) * (vida / 5.0)
    return round(bruto, 2), detalhes


# ── EIXO 3: ATAQUE ──────────────────────────────────────────────────────────

def _eixo_ataque(leader, main_cards):
    """
    Capacidade de FECHAR a partida.

    - Poder total por custo (quanto poder o deck poe em campo por DON gasto).
    - Palavras-chave que traduzem em dano: Rush (dano no turno em que entra),
      Double Attack (2 de vida por hit), Unblockable, Banish.
    - Buff de poder (empurra ataque acima do alcance de counter).
    - Remocao ofensiva: KO/rest/bounce tambem ABREM caminho pro ataque
      (tirar o blocker da frente e ataque, nao defesa) -- por isso entra
      nos DOIS eixos, com pesos diferentes.
    - Poder do lider, que ataca todo turno.
    """
    detalhes = []
    poder_por_custo = 0.0
    for c in main_cards:
        if (c.get('type') or '').lower() != 'character':
            continue
        custo = max(_num(c.get('cost'), 1), 1)
        poder_por_custo += (_num(c.get('power')) / custo / 1000.0) * _qtd(c)

    rush = sum(_qtd(c) for c in main_cards if c.get('has_rush'))
    double = sum(_qtd(c) for c in main_cards if c.get('has_double_attack'))
    unblock = sum(_qtd(c) for c in main_cards if c.get('has_unblockable'))
    banish = sum(_qtd(c) for c in main_cards if c.get('has_banish'))
    buff = sum(_qtd(c) for c in main_cards if c.get('power_buff'))
    remocao = sum(_qtd(c) for c in main_cards
                  if c.get('kos') or c.get('rests_opponent') or c.get('bounces'))
    poder_lider = _num(leader.get('power'), 5000) if leader else 5000

    detalhes.append({'tipo': 'corpo', 'desc': f'eficiencia de poder por custo {poder_por_custo:.1f}', 'n': round(poder_por_custo, 1)})
    detalhes.append({'tipo': 'rush', 'desc': f'{rush} com Rush', 'n': rush})
    detalhes.append({'tipo': 'evasao', 'desc': f'{double} Double Attack, {unblock} Unblockable, {banish} Banish', 'n': double + unblock + banish})
    detalhes.append({'tipo': 'buff', 'desc': f'{buff} copias com buff de poder', 'n': buff})
    detalhes.append({'tipo': 'abre_caminho', 'desc': f'{remocao} copias tiram bloqueador do caminho', 'n': remocao})

    bruto = (poder_por_custo * 1.0
             + rush * 2.0
             + double * 3.0
             + unblock * 2.0
             + banish * 1.5
             + buff * 0.5
             + remocao * 0.5
             + (poder_lider / 1000.0))
    return round(bruto, 2), detalhes


# ── API do modulo ───────────────────────────────────────────────────────────

def compute_deck_axes(leader: dict, main_cards: list) -> dict:
    """
    `leader` e `main_cards` sao entradas do `card_analysis_db` enriquecidas
    com `quantity`. Devolve os tres eixos CRUS. A traducao pra 0-100 e feita
    contra os percentis do meta (ver `calibrar_percentis_abertura.py`), nunca
    contra um teto inventado aqui.
    """
    sinergia, det_s = _eixo_sinergia(leader, main_cards)
    defesa, det_d = _eixo_defesa(leader, main_cards)
    ataque, det_a = _eixo_ataque(leader, main_cards)
    return {
        'sinergia': {'bruto': sinergia, 'detalhes': det_s},
        'defesa': {'bruto': defesa, 'detalhes': det_d},
        'ataque': {'bruto': ataque, 'detalhes': det_a},
    }
