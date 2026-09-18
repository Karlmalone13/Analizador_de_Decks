#!/usr/bin/env python
"""Teste do `q_fallback` no `live_<ts>.json` (bloco 867).

O campo existe pra responder, no passo 1 da telemetria: **esta partida foi
decidida pelo modelo?** Antes do bloco 866 a resposta era invisivel, e uma
partida inteira decidida por `candidatas[0]` (sem avaliacao) chegava ali
indistinguivel de uma decidida pelo modelo.

O controle que importa e o C: relatorio ilegivel tem que devolver ERRO. Se ele
passasse calado, trocariamos uma falha silenciosa por outra.

    cd scriptis_da_ia && python teste_q_fallback.py
"""
import json, sys, tempfile
from pathlib import Path
import os
R = str(Path(__file__).resolve().parent)
sys.path.insert(0, R)
from collect_latest_match import grava_q_fallback

falhas = []
def ok(c, m):
    print(('[OK] ' if c else '[FALHA] ') + m)
    if not c: falhas.append(m)

d = Path(tempfile.mkdtemp())
rel = d / 'live_x.json'

# A. partida SA -- o campo tem que existir mesmo vazio (ausencia != "tudo bem")
rel.write_text(json.dumps({'dano_por_jogo': 7}), encoding='utf-8')
err = grava_q_fallback(rel, {}, None)
j = json.loads(rel.read_text(encoding='utf-8'))
ok(err is None, 'sem erro')
ok('q_fallback' in j, 'campo q_fallback SEMPRE presente (mesmo com 0)')
ok(j['q_fallback']['total'] == 0, 'total 0 na partida sa')
ok(j['dano_por_jogo'] == 7, 'nao destruiu o relatorio existente')

# B. partida DOENTE
rel.write_text(json.dumps({'dano_por_jogo': 7}), encoding='utf-8')
grava_q_fallback(rel, {'sem_modelo': 180, 'primeiro_candidato': 180}, None)
j = json.loads(rel.read_text(encoding='utf-8'))
ok(j['q_fallback']['total'] == 360, 'soma os motivos (360)')
ok(j['q_fallback']['por_motivo']['sem_modelo'] == 180, 'preserva a quebra por motivo')

# C. CONTROLE que TEM que falhar: relatorio ilegivel nao pode passar calado
rel.write_text('{ isto nao e json', encoding='utf-8')
err = grava_q_fallback(rel, {'erro': 1}, None)
ok(err is not None, 'CONTROLE: relatorio ilegivel devolve ERRO (nao silencia)')
ok('gravar no relatorio' in (err or ''), 'o erro diz o que falhou')

# D. o delta do servidor
ini = {'sem_modelo': 5}
fim = {'sem_modelo': 12, 'erro': 3}
delta = {k: v - ini.get(k, 0) for k, v in fim.items() if v - ini.get(k, 0) > 0}
ok(delta == {'sem_modelo': 7, 'erro': 3}, 'delta por partida ignora o que era da anterior')

print()
print('FALHAS:', len(falhas))
sys.exit(1 if falhas else 0)
