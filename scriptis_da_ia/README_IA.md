# 🧠 OPTCG IA — Guia Completo

## Pré-requisitos

```bash
pip install requests beautifulsoup4 pandas scikit-learn joblib
```

---

## Passo 1 — Exportar banco de cartas do Supabase

1. Acesse o **Supabase Dashboard** do seu projeto
2. Vá em **Table Editor → cards**
3. Clique em **Export → CSV**
4. Salve como `cards.csv` na mesma pasta dos scripts

---

## Passo 2 — Coletar decklists de torneio

```bash
python coletar_dados_optcg.py
```

Isso vai:
- Coletar ~200-500 decklists do Limitless TCG
- Extrair features de cada deck
- Gerar `decklists_raw.csv` e `features.csv`

**Tempo estimado:** 10-20 minutos (respeita rate limit)

---

## Passo 3 — Treinar o modelo

```bash
python treinar_modelo.py
```

Isso vai:
- Carregar `features.csv`
- Treinar um Gradient Boosting Regressor
- Exportar `modelo_optcg.json`
- Gerar `resultado_treino.txt` com métricas

---

## Passo 4 — Integrar no projeto Next.js

Copie o modelo para o projeto:

```bash
cp modelo_optcg.json SEU_PROJETO/src/data/modelo_optcg.json
```

---

## Passo 5 — Retreinar com mais dados

Quanto mais decklists você coletar, melhor o modelo fica.

Para retreinar:
1. Rode `coletar_dados_optcg.py` novamente (coleta dados novos)
2. Rode `treinar_modelo.py` novamente
3. Copie o novo `modelo_optcg.json` para o projeto

---

## O que a IA vai prever

| Feature | Descrição |
|---------|-----------|
| `avg_cost` | Custo médio do deck |
| `searchers` | Quantidade de searchers |
| `counters_2k` | Quantidade de counters 2000 |
| `counters_1k` | Quantidade de counters 1000 |
| `blockers` | Quantidade de blockers |
| `rush` | Quantidade de Rush |
| `triggers` | Quantidade de Triggers |
| `draw_power` | Quantidade de Draw Power |
| `low_cost_2` | Cartas de custo ≤2 |
| `event_ratio` | % de eventos no deck |

**Saída:** `performance_score` (0-100) baseado nas colocações reais de torneio

---

## Interpretação do R²

| R² | Qualidade |
|----|-----------|
| > 0.7 | Excelente |
| 0.5-0.7 | Bom |
| 0.3-0.5 | Regular |
| < 0.3 | Ruim (precisa de mais dados) |

---

## Fontes de dados adicionais

- **Limitless TCG:** https://onepiece.limitlesstcg.com/decks/lists
- **Egman Events:** https://egmanevents.com/one-piece
- **OPTCG.one:** https://www.optcg.one/decklists