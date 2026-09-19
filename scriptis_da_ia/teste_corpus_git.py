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

# --- FATIA DE BACKFILL PARCIALMENTE PRESENTE  (o estrago real de 18/09/2026)
#
# Uma fatia com VARIAS origens, quase toda ja presente no corpus local e
# faltando poucas linhas de UMA delas. O guarda antigo era tudo-ou-nada por
# origem: a origem incompleta reprovava o `all(...)` e a fatia INTEIRA era
# anexada -- 698.222 linhas duplicadas no corpus real.
#
# Este e o CONTROLE: com a versao antiga o corpus final teria 3+3=6 linhas em
# vez de 4, entao o teste REPROVA aquele codigo.
C = monta('C')
git2 = monta('git2')
ja_tinha = [linha('X',1,1,'a'), linha('X',1,2,'b'), linha('Y',2,1,'c')]
(C/'metrics'/'q_alvos.jsonl').write_text(''.join(ja_tinha), encoding='utf-8')

# a fatia de backfill: repete as 3 que ja estao aqui e traz 1 nova de Y
backfill = ja_tinha + [linha('Y',2,2,'d')]
with gzip.open(git2/'metrics'/'q_alvos'/'Outra_20260918T000000_backfill.jsonl.gz',
               'wt', encoding='utf-8', newline='') as fh:
    fh.write(''.join(backfill))

aponta(C, fatias_de=git2)
cg.cmd_importa()
depois = (C/'metrics'/'q_alvos.jsonl').read_text(encoding='utf-8')
ok(depois == ''.join(backfill),
   'CONTROLE 18/09: fatia parcialmente presente traz SO a linha que faltava')
ok(depois.count(linha('X',1,1,'a')) == 1,
   'CONTROLE 18/09: a linha ja existente NAO foi duplicada')

# e a repeticao legitima continua sobrevivendo a esta reconciliacao
D = monta('D')
git3 = monta('git3')
(D/'metrics'/'q_alvos.jsonl').write_text(linha('Z',0,4,'x'), encoding='utf-8')
com_repetida = [linha('Z',0,4,'x'), linha('Z',0,4,'x')]
with gzip.open(git3/'metrics'/'q_alvos'/'Outra_20260918T000001.jsonl.gz',
               'wt', encoding='utf-8', newline='') as fh:
    fh.write(''.join(com_repetida))
aponta(D, fatias_de=git3)
cg.cmd_importa()
ok((D/'metrics'/'q_alvos.jsonl').read_text(encoding='utf-8') == ''.join(com_repetida),
   'a reconciliacao respeita MULTIPLICIDADE (1 local + 1 faltando = 2, nao 1)')

shutil.rmtree(base, ignore_errors=True)
print()
print('FALHAS:', len(falhas))
sys.exit(1 if falhas else 0)
