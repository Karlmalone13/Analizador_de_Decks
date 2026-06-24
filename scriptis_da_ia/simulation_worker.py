"""
simulation_worker.py — Worker de simulação de partidas
========================================================
Carrega decklists ({code, qty}) para objetos Card reais, roda N partidas
via OPTCGMatch (com OpponentModel + Monte Carlo já integrados no Turn
Planner), agrega o resultado (taxa de vitória, breakdown), e atualiza o
progresso do job no Postgres a cada partida concluída.

Roda em background (FastAPI BackgroundTasks) — chamado por api.py depois
de criar o job com status='pending'. Nunca é chamado de forma síncrona
numa requisição HTTP (ver db.py e a migration simulation_jobs: padrão
fila + polling, acordado em sessão de 23-24/06 para evitar timeout).
"""
import asyncio
import json
import os

from optcg_engine.decision_engine import _make_card, OPTCGMatch

import db

_DB_PATH = os.path.join(os.path.dirname(__file__), 'card_analysis_db.json')
with open(_DB_PATH, encoding='utf-8') as f:
    CARD_DB = json.load(f)


class DeckLoadError(Exception):
    """Erro ao carregar uma decklist — código de carta não encontrado ou líder ausente."""
    pass


def load_deck(cards: list[dict]) -> tuple:
    """
    Converte uma decklist no formato [{"code": "OP15-001", "qty": 4}, ...]
    em (leader: Card, main_deck: list[Card]). Mesma normalização de
    arte alternativa (split por '_') usada em api.py /analyze, para
    manter os dois caminhos consistentes.

    Levanta DeckLoadError se algum código não existir no banco ou se não
    houver exatamente 1 Leader na lista.
    """
    leader = None
    main_deck = []
    missing = []

    for entry in cards:
        code = entry['code'].split('_')[0]
        qty = entry.get('qty', 1)
        info = CARD_DB.get(code)
        if not info:
            missing.append(entry['code'])
            continue
        if info.get('type') == 'LEADER':
            leader = _make_card(code, info)
        else:
            main_deck.extend(_make_card(code, info) for _ in range(qty))

    if missing:
        raise DeckLoadError(f"cartas não encontradas: {', '.join(missing)}")
    if leader is None:
        raise DeckLoadError("decklist sem líder")

    return leader, main_deck


def run_single_match(deck_a: tuple, deck_b: tuple) -> dict:
    """Roda 1 partida e devolve o resultado bruto de OPTCGMatch.simulate()."""
    match = OPTCGMatch(deck_a, deck_b)
    return match.simulate()


def aggregate_results(results: list[dict]) -> dict:
    """
    Agrega N resultados de partida em estatísticas finais. `winner` em
    cada resultado é 'A' ou 'B' -- aqui A é sempre o deck do usuário
    (convenção mantida em run_simulation_job).
    """
    n = len(results)
    if n == 0:
        return {'n_simulations': 0, 'win_rate': None}

    wins_a = sum(1 for r in results if r.get('winner') == 'A')
    avg_turns = sum(r.get('turns', 0) for r in results) / n
    avg_dmg_a = sum(r.get('dmg_a', 0) for r in results) / n
    avg_dmg_b = sum(r.get('dmg_b', 0) for r in results) / n

    return {
        'n_simulations': n,
        'wins': wins_a,
        'losses': n - wins_a,
        'win_rate': round(wins_a / n, 4),
        'avg_turns': round(avg_turns, 2),
        'avg_dmg_dealt': round(avg_dmg_a, 2),
        'avg_dmg_taken': round(avg_dmg_b, 2),
    }


async def run_simulation_job(job_id: str):
    """
    Executa um job de simulação do início ao fim: carrega o(s) deck(s),
    roda as partidas necessárias conforme analysis_type, atualiza
    progresso a cada partida, e finaliza com o resultado agregado.

    Chamado como BackgroundTask a partir de api.py -- roda de forma
    assíncrona em relação à requisição HTTP que criou o job (que já
    retornou {job_id} antes desta função começar a rodar).
    """
    job = await db.get_job(job_id)
    if job is None:
        return  # job não existe (não deveria acontecer, mas não há onde reportar erro)

    try:
        await db.update_job_progress(job_id, progress=0, status='running')

        leader_a, deck_a_cards = load_deck(job['deck_a'])

        if job['analysis_type'] == 'meta':
            metas = await db.list_meta_decklists(
                is_current_meta=(job.get('meta_filter') or {}).get('is_current_meta', True),
                limit=job.get('n_meta_decks') or 20,
            )
            if not metas:
                await db.fail_job(job_id, "nenhuma decklist de meta disponível para comparação")
                return
            # meta_decklists.cards guarda SÓ o main deck (50 cartas, sem
            # leader) -- o leader_code é campo separado. load_deck() espera
            # leader + main juntos numa lista só, então o leader precisa
            # ser injetado aqui antes de montar matchups (bug corrigido em
            # 24/06: sem isto, load_deck() levantava "decklist sem líder"
            # para toda decklist de meta).
            matchups = [
                (m['name'], m['leader_code'], [{'code': m['leader_code'], 'qty': 1}] + m['cards'])
                for m in metas
            ]
        else:
            # custom_opponent ou own_decks: deck_b já vem completo no job
            # (com leader incluso, montado pelo frontend antes de chamar
            # POST /simulate -- ver src/app/simulate/page.tsx)
            matchups = [('oponente', None, job['deck_b'])]

        n_sim = job['n_simulations']
        total_steps = job.get('total_steps') or (n_sim * len(matchups))
        progress = 0
        breakdown = []

        for matchup_name, _leader_code, deck_b_cards in matchups:
            leader_b, deck_b_main = load_deck(deck_b_cards)
            resultados_matchup = []
            for _ in range(n_sim):
                resultado = run_single_match(
                    (leader_a, list(deck_a_cards)),
                    (leader_b, list(deck_b_main)),
                )
                resultados_matchup.append(resultado)
                progress += 1
                await db.update_job_progress(job_id, progress=progress, status='running')

            agg = aggregate_results(resultados_matchup)
            agg['matchup'] = matchup_name
            breakdown.append(agg)

        # Agregado geral: soma os contadores de cada matchup já calculado
        # acima, em vez de re-rodar tudo junto -- mais simples e sem custo
        # extra.
        total_wins = sum(b['wins'] for b in breakdown)
        total_n = sum(b['n_simulations'] for b in breakdown)

        final_result = {
            'overall_win_rate': round(total_wins / total_n, 4) if total_n else None,
            'total_simulations': total_n,
            'breakdown_by_matchup': breakdown,
        }

        await db.finish_job(job_id, final_result)

    except DeckLoadError as e:
        await db.fail_job(job_id, str(e))
    except Exception as e:
        await db.fail_job(job_id, f"erro inesperado: {type(e).__name__}: {e}")