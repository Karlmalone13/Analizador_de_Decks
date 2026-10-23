"""Portao da Fase 3 (bloco 973): o MESMO Q campeao com a arvore do turno
(`arvore_q`) contra ele sem a arvore. Muda so a forma de decidir."""
import json
import os
import sys

os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import treino_continuo as tc  # noqa: E402
from ciclo import Q_CAMPEAO  # noqa: E402

if __name__ == '__main__':
    d = tc.duelar_sprt(
        workers=int(sys.argv[1]) if len(sys.argv) > 1 else 4, seed=973,
        peso_camp=0.0, peso_desaf=0.0, max_pares=4000,
        extras={'desafiante': {'q_net_path': str(Q_CAMPEAO), 'arvore_q': True},
                'campeao': {'q_net_path': str(Q_CAMPEAO)}})
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str))
