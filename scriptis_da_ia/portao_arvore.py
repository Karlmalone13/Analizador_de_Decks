"""Portoes da Fase 3: o MESMO Q campeao dos dois lados, muda so a forma de
decidir. `arvore` (bloco 973): com x sem a arvore do turno. `efeitos` (bloco
974): os dois com a arvore; escolhas de efeito DENTRO dela pelo Q x pela regra.
`defesa` (bloco 976): bloqueio/counter pelo fim do turno do atacante x pelo Q
no estado logo depois do golpe.

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
    flag = {'arvore': 'arvore_q', 'efeitos': 'arvore_efeitos_q',
            'defesa': 'arvore_defesa'}[modo]
    extras = {'desafiante': {'q_net_path': q, flag: True},
              'campeao': {'q_net_path': q, flag: False}}
    d = tc.duelar_sprt(
        workers=int(sys.argv[1]) if len(sys.argv) > 1 else 4,
        seed={'arvore': 973, 'efeitos': 974, 'defesa': 976}[modo],
        peso_camp=0.0, peso_desaf=0.0, max_pares=4000, extras=extras)
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str))
