"""Portoes da Fase 3: o MESMO Q campeao dos dois lados, muda so a forma de
decidir. `arvore` (bloco 973): com x sem a arvore do turno. `efeitos` (bloco
974): os dois com a arvore; escolhas de efeito DENTRO dela pelo Q x pela regra.

    python portao_arvore.py 4 efeitos
"""
import json
import os
import sys

os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import treino_continuo as tc  # noqa: E402
from ciclo import Q_CAMPEAO  # noqa: E402

if __name__ == '__main__':
    modo = sys.argv[2] if len(sys.argv) > 2 else 'arvore'
    q = str(Q_CAMPEAO)
    extras = ({'desafiante': {'q_net_path': q, 'arvore_q': True},
               'campeao': {'q_net_path': q, 'arvore_q': False}} if modo == 'arvore' else
              {'desafiante': {'q_net_path': q, 'arvore_efeitos_q': True},
               'campeao': {'q_net_path': q, 'arvore_efeitos_q': False}})
    d = tc.duelar_sprt(
        workers=int(sys.argv[1]) if len(sys.argv) > 1 else 4,
        seed=973 if modo == 'arvore' else 974,
        peso_camp=0.0, peso_desaf=0.0, max_pares=4000, extras=extras)
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str))
