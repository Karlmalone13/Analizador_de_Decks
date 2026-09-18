#!/usr/bin/env python
"""Teste do transporte do corpus por fatias (`corpus_git.py`).

Existe porque a PRIMEIRA versao daquele arquivo deduplicava por hash de linha e
teria descartado 25.846 linhas legitimas do corpus real (3,7%) em silencio --
candidatos identicos dentro da MESMA decisao, que tem peso no treino.

O teste `a linha REPETIDA sobreviveu` e o CONTROLE dessa falha: ele REPROVA a
versao antiga. Sem ele, o round-trip passaria igual e o estrago so apareceria
como "o modelo ficou um pouco pior" semanas depois.

    cd scriptis_da_ia && python teste_corpus_git.py
"""
import json, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus_git as cg

falhas = []
def ok(cond, msg):
    print(('[OK] ' if cond else '[FALHA] ') + msg)
    if not cond: falhas.append(msg)

def linha(origem, match, turn, alvo):
    return json.dumps({'origem':origem,'match':match,'turn':turn,'alvo':alvo,'feats':[1,2]})+'\n'

base = Path(tempfile.mkdtemp())
def monta(nome):
    d = base/nome; (d/'metrics'/'q_alvos').mkdir(parents=True, exist_ok=True)
    return d
def aponta(d, fatias_de=None):
    cg.CORPUS = d/'metrics'/'q_alvos.jsonl'
    cg.FATIAS = (fatias_de or d)/'metrics'/'q_alvos'
    cg.LIVRO  = d/'metrics'/'q_alvos_fatias.json'

# git compartilhado entre as duas "maquinas"
git = monta('git')
A, B = monta('A'), monta('B')

# --- maquina A: corpus com REPETICAO LEGITIMA (o caso que quebrou a v1)
conteudo = [linha('A',0,4,'x'), linha('A',0,4,'x'), linha('A',0,5,'y')]
(A/'metrics'/'q_alvos.jsonl').write_text(''.join(conteudo), encoding='utf-8')

aponta(A, fatias_de=git)
cg.origem_desta_maquina = lambda: 'A'
cg.cmd_exporta(None)
fatias = sorted((git/'metrics'/'q_alvos').glob('*.gz'))
ok(len(fatias)==1, 'exporta criou exatamente 1 fatia')

# --- maquina B: clone limpo, importa
aponta(B, fatias_de=git)
cg.cmd_importa()
got = (B/'metrics'/'q_alvos.jsonl').read_text(encoding='utf-8')
ok(got == ''.join(conteudo), 'B reproduz o corpus de A BYTE A BYTE (repetida inclusive)')
ok(got.count(linha('A',0,4,'x')) == 2, 'a linha REPETIDA sobreviveu (controle da v1)')

# --- importar de novo nao duplica
cg.cmd_importa()
ok((B/'metrics'/'q_alvos.jsonl').read_text(encoding='utf-8') == ''.join(conteudo),
   'importar 2x nao duplica')

# --- B gera dado proprio e exporta: so o dele deve sair
novo = [linha('B',9,2,'z'), linha('B',9,3,'w')]
with open(B/'metrics'/'q_alvos.jsonl','a',encoding='utf-8') as fh: fh.write(''.join(novo))
cg.origem_desta_maquina = lambda: 'B'
cg.cmd_exporta(None)
fatias = sorted((git/'metrics'/'q_alvos').glob('*.gz'))
ok(len(fatias)==2, 'segunda fatia criada')
import gzip
nova = gzip.open(fatias[-1],'rt',encoding='utf-8').read()
ok(nova == ''.join(novo), 'a fatia de B traz SO as linhas de B (nao reexporta as de A)')

# --- A importa a fatia de B
aponta(A, fatias_de=git)
cg.cmd_importa()
final = (A/'metrics'/'q_alvos.jsonl').read_text(encoding='utf-8')
ok(final == ''.join(conteudo+novo), 'A converge para o mesmo conteudo total')

# --- CONTROLE QUE TEM QUE FALHAR: corpus adulterado nao pode passar batido
(A/'metrics'/'q_alvos.jsonl').write_text(''.join(conteudo), encoding='utf-8')
locais = cg._conta_por_origem(A/'metrics'/'q_alvos.jsonl', False)
ok(locais.get('B',0) == 0, 'CONTROLE: corpus truncado e detectavel (B=0 apesar da fatia existir)')

shutil.rmtree(base, ignore_errors=True)
print()
print('FALHAS:', len(falhas))
sys.exit(1 if falhas else 0)
