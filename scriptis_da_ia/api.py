"""
api.py — API do analisador de decks OPTCG
==========================================
Expõe o motor de análise (deck_analyzer.analyze_deck) como endpoint HTTP.
Fonte ÚNICA de verdade: o front chama esta API, não reimplementa a lógica.
Busca manter esta camada o mais fina possível — só recebe a lista de cartas, chama o analisador, e devolve o resultado.
Rode localmente:
Rodar localmente:
    pip install fastapi uvicorn
    uvicorn api:app --reload --port 8000

Endpoint:
    POST /analyze
    body: { "cards": [ {"code": "OP15-001", "qty": 1}, {"code": "OP15-037", "qty": 4}, ... ] }
    resposta: análise completa (arquétipo, sinergias, coesão tribal, ratios, curva)
"""
import json
import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from deck_analyzer import analyze_deck
import db
import simulation_worker

# ── Carrega o card_analysis_db uma vez na inicialização ─────────────────────
_DB_PATH = os.path.join(os.path.dirname(__file__), 'card_analysis_db.json')
with open(_DB_PATH, encoding='utf-8') as f:
    CARD_DB = json.load(f)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # fecha o pool de conexões do Postgres de forma limpa no shutdown --
    # sem isto, conexões podem ficar penduradas no Supabase (free tier tem
    # limite baixo de conexões simultâneas).
    await db.close_pool()


app = FastAPI(title="OPTCG Deck Analyzer API", lifespan=lifespan)

# CORS: permite o front (em outro domínio) chamar a API.
# Em produção, troque "*" pela URL real do seu front.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class CardEntry(BaseModel):
    code: str
    qty: int = 1


class DeckRequest(BaseModel):
    cards: list[CardEntry]


class SimulateRequest(BaseModel):
    """
    Pedido de simulação. analysis_type define o que deck_b/n_meta_decks
    significam:
      - 'custom_opponent': deck_b obrigatório (decklist colada/escolhida)
      - 'own_decks': deck_b obrigatório (outro deck salvo do usuário)
      - 'meta': deck_b ignorado, n_meta_decks define quantas decklists de
        meta_decklists são usadas (limite de 20, acordado em sessão de
        23/06 para caber em tempo de processamento razoável)
    """
    analysis_type: str  # 'meta' | 'custom_opponent' | 'own_decks'
    deck_a: list[CardEntry]
    deck_b: Optional[list[CardEntry]] = None
    n_simulations: int = 10
    n_meta_decks: Optional[int] = None
    user_id: Optional[str] = None


MAX_N_SIMULATIONS = 10   # partidas por matchup -- limite acordado em 23/06
MAX_N_META_DECKS = 20    # decklists de meta por job -- limite acordado em 23/06


@app.get("/")
def health():
    return {"status": "ok", "cards_loaded": len(CARD_DB)}


@app.post("/analyze")
def analyze(req: DeckRequest):
    if not req.cards:
        raise HTTPException(status_code=400, detail="deck vazio")

    leader = None
    main = []
    missing = []
    for entry in req.cards:
        code = entry.code.split('_')[0]  # normaliza arte alternativa
        info = CARD_DB.get(code)
        if not info:
            missing.append(entry.code)
            continue
        if info.get('type') == 'LEADER':
            leader = info
        else:
            main.extend([info] * entry.qty)

    if leader is None:
        raise HTTPException(status_code=400, detail="deck sem líder")

    result = analyze_deck(leader, main)
    if missing:
        result['warnings'] = {'cards_nao_encontradas': missing}
    return result


@app.post("/simulate")
async def simulate(req: SimulateRequest, background_tasks: BackgroundTasks):
    """
    Cria um job de simulação e dispara a execução em background. Responde
    IMEDIATAMENTE com {job_id} -- a requisição HTTP nunca espera as
    partidas rodarem (padrão fila + polling, acordado em 23/06 para evitar
    timeout: ~10 partidas x 20 decklists de meta pode levar minutos).

    O cliente deve consultar GET /simulate/status/{job_id} periodicamente
    até status='done' ou 'error'.
    """
    if req.analysis_type not in ('meta', 'custom_opponent', 'own_decks'):
        raise HTTPException(status_code=400, detail="analysis_type inválido")

    if req.analysis_type in ('custom_opponent', 'own_decks') and not req.deck_b:
        raise HTTPException(status_code=400, detail=f"deck_b é obrigatório para analysis_type={req.analysis_type}")

    n_sim = min(req.n_simulations, MAX_N_SIMULATIONS)
    n_meta = min(req.n_meta_decks or MAX_N_META_DECKS, MAX_N_META_DECKS) if req.analysis_type == 'meta' else None

    deck_a_dicts = [{'code': c.code, 'qty': c.qty} for c in req.deck_a]
    deck_b_dicts = [{'code': c.code, 'qty': c.qty} for c in req.deck_b] if req.deck_b else None

    total_steps = n_sim * (n_meta if req.analysis_type == 'meta' else 1)

    job_id = await db.create_job(
        analysis_type=req.analysis_type,
        deck_a=deck_a_dicts,
        deck_b=deck_b_dicts,
        n_simulations=n_sim,
        n_meta_decks=n_meta,
        total_steps=total_steps,
        user_id=req.user_id,
    )

    background_tasks.add_task(simulation_worker.run_simulation_job, job_id)

    return {"job_id": job_id, "status": "pending", "total_steps": total_steps}


class ReplayRequest(BaseModel):
    """Pedido de replay de uma única partida com log detalhado de eventos."""
    deck_a: list[CardEntry]
    deck_b: list[CardEntry]
    name_a: str = 'Player A'
    name_b: str = 'Player B'


@app.post("/replay")
async def replay(req: ReplayRequest):
    """
    Roda UMA partida completa e retorna log estruturado de eventos por turno.
    Usado pelo replay viewer no frontend para mostrar o que aconteceu em cada
    turno: cartas jogadas, ataques, dano na vida, efeitos disparados.

    Resposta: {winner, turns, events: [...], turns_detail: [{turn, events}]}
    Cada evento tem: {turn, player, player_name, phase, type, card, target, description}
    card/target: {code, name, image, cost, power, type, color}
    """
    from optcg_engine.decision_engine import OPTCGMatch
    from simulation_worker import load_deck, DeckLoadError

    def entries_to_dict(entries):
        return [{'code': e.code, 'qty': e.qty} for e in entries]

    try:
        deck_a = load_deck(entries_to_dict(req.deck_a))
        deck_b = load_deck(entries_to_dict(req.deck_b))
    except DeckLoadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Erro ao montar deck: {e}')

    try:
        match = OPTCGMatch(deck_a, deck_b)
        result = match.simulate_replay(name_a=req.name_a, name_b=req.name_b)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Erro na simulação: {e}')

    return result


@app.get("/simulate/status/{job_id}")
async def simulate_status(job_id: str):
    """
    Consulta rápida ao banco -- nunca espera nada, só lê o estado atual do
    job. O front faz polling neste endpoint a cada poucos segundos até
    status='done' ou 'error'.
    """
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job