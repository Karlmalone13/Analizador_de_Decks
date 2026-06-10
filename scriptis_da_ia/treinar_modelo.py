"""
OPTCG Model Trainer — Treina a IA com os dados coletados
Requer: features.csv gerado pelo coletar_dados_optcg.py

Instalação:
    pip install pandas scikit-learn joblib

Uso:
    python treinar_modelo.py

Saída:
    modelo_optcg.json    — modelo exportado para usar no Next.js
    modelo_optcg.pkl     — modelo salvo localmente para retreinar
    resultado_treino.txt — relatório de performance do modelo
"""

import os
import pandas as pd
import numpy as np
import json
import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_absolute_error, r2_score

# ── Features que o modelo vai usar ───────────────────────────────────────────
FEATURE_COLS = [
    'avg_cost',
    'searchers',
    'draw_power',
    'blockers',
    'counters_2k',
    'counters_1k',
    'rush',
    'double_atk',
    'triggers',
    'banish',
    'low_cost_1',
    'low_cost_2',
    'events',
    'characters',
    'searcher_ratio',
    'counter_ratio',
    'blocker_ratio',
    'event_ratio',
    'leader_winrate',
    'sim_winrate',
]

TARGET_COL = 'final_score'


def main():
    print('=' * 60)
    print('OPTCG Model Trainer')
    print('=' * 60)

    # ── Carrega dados ─────────────────────────────────────────────────────────
    print('\n[1/5] Carregando features.csv...')
    try:
        df = pd.read_csv('features.csv')
    except FileNotFoundError:
        print('❌ features.csv não encontrado!')
        print('Execute primeiro: python coletar_dados_optcg.py')
        return

    print(f'Total de decks: {len(df)}')
    print(f'Distribuição de colocações:\n{df["placing"].value_counts().head(10)}')

    # ── Limpeza e criação do target ───────────────────────────────────────────
    print('\n[2/5] Limpando dados e criando score final...')

    # Carrega dados de simulação se disponível
    if os.path.exists('resultados_simulacao.csv'):
        df_sim = pd.read_csv('resultados_simulacao.csv')
        df = df.merge(
            df_sim[['deck_name', 'sim_winrate', 'final_score']],
            on='deck_name', how='left'
        )
        print(f'✅ Dados de simulação adicionados! ({df["sim_winrate"].notna().sum()} decks com sim_winrate)')
    else:
        print('⚠️  resultados_simulacao.csv não encontrado — usando score combinado')
        df['sim_winrate'] = 50.0
        df['final_score'] = (
            df['performance_score'] * 0.70 +
            df['leader_winrate']    * 0.30
        ).round(1)

    # Preenche NaN de sim_winrate com 50 (neutro)
    df['sim_winrate'] = df['sim_winrate'].fillna(50.0)

    # Recalcula final_score para quem não tinha simulação
    mask = df['final_score'].isna()
    df.loc[mask, 'final_score'] = (
        df.loc[mask, 'performance_score'] * 0.50 +
        df.loc[mask, 'leader_winrate']    * 0.30 +
        df.loc[mask, 'sim_winrate']       * 0.20
    ).round(1)

    # Filtra
    df = df[df['placing'] <= 32].copy()
    df = df[df['final_score'].notna()].copy()
    df = df.dropna(subset=FEATURE_COLS + [TARGET_COL])

    print(f'Decks após limpeza: {len(df)}')
    print(f'Final score — min: {df[TARGET_COL].min():.1f} | max: {df[TARGET_COL].max():.1f} | média: {df[TARGET_COL].mean():.1f}')

    if len(df) < 50:
        print('⚠️  Poucos dados para treinar! Mínimo recomendado: 100 decks')
        print('   Continuando mesmo assim...')

    X = df[FEATURE_COLS].values
    y = df[TARGET_COL].values

    # ── Split treino/teste ────────────────────────────────────────────────────
    print('\n[3/5] Dividindo treino/teste (80/20)...')
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f'Treino: {len(X_train)} | Teste: {len(X_test)}')

    # ── Treina modelo ─────────────────────────────────────────────────────────
    print('\n[4/5] Treinando modelo Gradient Boosting...')
    modelo = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        min_samples_split=5,
        random_state=42
    )
    modelo.fit(X_train, y_train)

    y_pred = modelo.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2  = r2_score(y_test, y_pred)
    cv  = cross_val_score(modelo, X, y, cv=5, scoring='r2')

    print(f'\n📊 Resultados:')
    print(f'   MAE (erro médio): {mae:.1f} pontos')
    print(f'   R² (precisão):    {r2:.3f} ({r2*100:.1f}%)')
    print(f'   CV R² médio:      {cv.mean():.3f} ± {cv.std():.3f}')

    importancias = sorted(
        zip(FEATURE_COLS, modelo.feature_importances_),
        key=lambda x: x[1], reverse=True
    )
    print(f'\n🔑 Features mais importantes:')
    for feat, imp in importancias[:8]:
        bar = '█' * int(imp * 50)
        print(f'   {feat:<20} {bar} {imp:.3f}')

    # ── Salva modelo ──────────────────────────────────────────────────────────
    print('\n[5/5] Exportando modelo...')

    joblib.dump(modelo, 'modelo_optcg.pkl')
    print('✅ modelo_optcg.pkl salvo')

    modelo_json = {
        'type': 'gradient_boosting',
        'feature_cols': FEATURE_COLS,
        'target': TARGET_COL,
        'params': {
            'n_estimators': modelo.n_estimators,
            'max_depth': modelo.max_depth,
            'learning_rate': modelo.learning_rate,
            'min_samples_split': modelo.min_samples_split,
        },
        'thresholds': {
            'excelente': float(np.percentile(y, 75)),
            'bom':       float(np.percentile(y, 50)),
            'regular':   float(np.percentile(y, 25)),
        },
        'stats': {
            feat: {
                'mean': float(df[feat].mean()),
                'std':  float(df[feat].std()),
                'min':  float(df[feat].min()),
                'max':  float(df[feat].max()),
            }
            for feat in FEATURE_COLS
        },
        'meta_reference': df.nlargest(10, TARGET_COL)[
            ['deck_name', 'leader', 'avg_cost', 'searchers', 'counters_2k', TARGET_COL]
        ].to_dict('records'),
    }

    print('\nGerando lookup table para Next.js...')
    lookup = []
    for _, row in df.iterrows():
        features = [row[f] for f in FEATURE_COLS]
        pred = float(modelo.predict([features])[0])
        lookup.append({
            'leader':          row['leader'],
            'leader_winrate':  float(row['leader_winrate']),
            'sim_winrate':     float(row['sim_winrate']),
            'avg_cost':        float(row['avg_cost']),
            'searchers':       int(row['searchers']),
            'counters_2k':     int(row['counters_2k']),
            'counters_1k':     int(row['counters_1k']),
            'blockers':        int(row['blockers']),
            'combined_score':  round(pred, 1),
        })
    modelo_json['lookup'] = lookup

    with open('modelo_optcg.json', 'w', encoding='utf-8') as f:
        json.dump(modelo_json, f, ensure_ascii=False, indent=2)
    print('✅ modelo_optcg.json salvo')

    relatorio = f"""
OPTCG Model — Relatorio de Treino
==================================
Data: {pd.Timestamp.now()}
Decks usados: {len(df)}
Features: {len(FEATURE_COLS)}
Target: {TARGET_COL} (50% performance + 30% leader_winrate + 20% sim_winrate)

Resultados:
  MAE (erro medio): {mae:.1f} pontos
  R2 (precisao):    {r2:.3f} ({r2*100:.1f}%)
  CV R2 medio:      {cv.mean():.3f} +- {cv.std():.3f}

Features mais importantes:
{chr(10).join(f'  {f:<20} {i:.3f}' for f, i in importancias)}

Thresholds calibrados:
  Excelente: >= {modelo_json['thresholds']['excelente']:.1f}
  Bom:       >= {modelo_json['thresholds']['bom']:.1f}
  Regular:   >= {modelo_json['thresholds']['regular']:.1f}
"""
    with open('resultado_treino.txt', 'w', encoding='utf-8') as f:
        f.write(relatorio)
    print('✅ resultado_treino.txt salvo')

    print('\n' + '=' * 60)
    print('✅ Modelo treinado com sucesso!')
    print('\nProximos passos:')
    print('  1. copy modelo_optcg.json ..\\public\\modelo_optcg.json')
    print('  2. Abra o site e teste a analise de deck!')
    print('=' * 60)


if __name__ == '__main__':
    main()