# scriptis_da_ia — Motor de análise de decks (OPTCG)

Esta pasta contém o cérebro do analisador: o pipeline que lê as cartas, entende
o que cada uma faz, classifica o arquétipo do deck, detecta sinergias e mede a
coesão tribal — e a API que expõe tudo isso para o front.

> Nota: a subpasta `optcg_engine/` (motor de simulação de partidas) **não** está
> documentada aqui — está em avaliação separada e pode ter usos futuros.

---

## Visão geral do pipeline

```
cards_rows.csv                (banco de cartas, exportado do Supabase)
      │
      ▼
gerar_effects_db.py           parseia o texto → efeitos estruturados (ação + gatilho)
      │
      ▼
card_effects_db.json          efeitos de cada carta
      │
      ▼
gerar_card_analysis_db.py     junta efeitos + estados de sinergia + texto + atributos
      │
      ▼
card_analysis_db.json         banco final que a API consome
      │
      ▼
deck_analyzer.py              analisa um deck (arquétipo + sinergias + coesão + ratios)
      │
      ▼
api.py                        expõe a análise como API HTTP (FastAPI)
```

---

## Os arquivos (analisador atual — em produção)

| Arquivo | O que faz |
|---|---|
| `gerar_effects_db.py` | Parser de texto → efeitos. Lê o texto de cada carta e extrai ações (ko, rest, give_don, gain_life…) separadas por **gatilho** (On Play, When Attacking, Trigger, etc.) e atributos (KO por poder/custo, requisito de DON). Cobertura ~80%. |
| `gerar_card_analysis_db.py` | Gera o `card_analysis_db.json`: cruza efeitos + estados de sinergia + texto + atributos por carta. É o passo que produz o banco que a API usa. |
| `deck_analyzer.py` | Coração da análise. Classifica o **arquétipo** (Aggro / Controle / Tempo-Ramp / Vida-Triggers) pelo comportamento das cartas, ponderado por confiabilidade de gatilho. Integra sinergias e coesão. Ponto de entrada: `analyze_deck(leader, main)`. |
| `synergy_states.py` | Motor de **sinergias**, em três formatos: (A) estado compartilhado — uma carta cria um estado, outra explora (restar+punir, vida+trigger, DON-ao-oponente+punir); (B) atributo — KO-por-poder × redução-de-poder, KO-por-custo × redução-de-custo; (payoff) dar DON a aliado + cartas `[DON!! xN]`, com direção (aggro/controle) vinda do efeito. |
| `tribal_cohesion.py` | Eixo **separado** do arquétipo: mede o quão focado o deck é no tipo do líder. Distingue "tribal de verdade" (muitas cartas do tipo + ganchos que recompensam o tipo) de "good-stuff mono-cor" (contém o tipo mas não o explora). |
| `api.py` | API FastAPI. `POST /analyze` recebe a lista de cartas e devolve a análise completa. Fonte única de verdade: o front chama esta API. |

## Dados

| Arquivo | O que é |
|---|---|
| `cards_rows.csv` | Banco de cartas (exportado do Supabase). Entrada do pipeline. |
| `card_effects_db.json` | Efeitos parseados por carta (saída de `gerar_effects_db.py`). |
| `card_analysis_db.json` | Banco final consumido pela API (efeitos + sinergias + texto + atributos). |
| `decklists_raw.csv` | Decklists de torneio, hoje usadas como casos de teste da classificação. |

---

## Como regenerar o banco

Sempre que mudar o parser (`gerar_effects_db.py`) ou a detecção de estados:

```bash
python gerar_card_analysis_db.py
```

Deve reportar ~2613 cartas. Depois, se o front consumir o JSON localmente,
copie `card_analysis_db.json` para `src/data/` do front.

---

## A API

Hospedada no **Railway**:

```
https://analizadordedecks-production.up.railway.app
```

- Health: `GET /` → `{"status":"ok","cards_loaded":2613}`
- Análise: `POST /analyze` com body `{"cards":[{"code":"OP15-001","qty":1}, ...]}`

Resposta: `archetype` (arquétipo + mistura de %), `synergies`, `tribal_cohesion`,
`ratios` (Golden Ratios), `curve`, `avg_cost`.

Observação: no plano free, o serviço dorme após inatividade; a primeira chamada
pode demorar alguns segundos.

### Rodar a API localmente

```bash
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

### Como o front aponta para a API

O front lê a variável `NEXT_PUBLIC_ANALYZER_API`:
- Dev: arquivo `.env.local` na raiz do projeto front.
- Produção: painel de variáveis do serviço do front (Vercel, etc.).

```
NEXT_PUBLIC_ANALYZER_API=https://analizadordedecks-production.up.railway.app
```

Sem a variável, o front usa `http://localhost:8000`.

### Deploy no Railway (referência)

- Root Directory: `scriptis_da_ia`
- Start Command: `uvicorn api:app --host 0.0.0.0 --port $PORT`
- `requirements.txt` instalado automaticamente.
- `card_analysis_db.json` precisa estar versionado (a API o lê na inicialização).

---

## Abordagens anteriores (na pasta, fora de produção)

O projeto evoluiu por tentativas. Além do analisador atual, a pasta contém:

- **Modelo estatístico treinado** (`treinar_modelo.py`, `modelo_optcg.json`,
  `features.csv`, `coletar_dados_optcg.py`): previa um "score de performance" via
  Gradient Boosting sobre decklists de torneio. Substituído pela análise por
  efeitos/sinergias (resultados explicáveis, sem re-treino). O coletor de
  decklists (Limitless TCG) ainda pode servir para validar a classificação contra
  torneios reais.
- **`optcg_engine/`** — motor de simulação de partidas. Em avaliação; documentado
  à parte.