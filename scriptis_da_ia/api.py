"""
api.py — API do analisador de decks OPTCG
==========================================
Expõe o motor de análise (deck_analyzer.analyze_deck) como endpoint HTTP.
Fonte ÚNICA de verdade: o front chama esta API, não reimplementa a lógica.

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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from deck_analyzer import analyze_deck

# ── Carrega o card_analysis_db uma vez na inicialização ─────────────────────
_DB_PATH = os.path.join(os.path.dirname(__file__), 'card_analysis_db.json')
with open(_DB_PATH, encoding='utf-8') as f:
    CARD_DB = json.load(f)

app = FastAPI(title="OPTCG Deck Analyzer API")

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