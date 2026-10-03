#!/bin/bash
# Loop de ciclos ate promover. Uso: bash metrics/_loop_ciclos.sh [MAX_CICLOS]  (default 3)
W='C:/Projetos_TI/analidador_de_decks_optcg/scriptis_da_ia'
cd "$W" || exit 1
MAX=${1:-3}
for i in $(seq 1 $MAX); do
  n=$(python -c "import json;print(len(json.load(open('$W/metrics/ciclo_estado.json'))['ciclos'])+1)") || break
  PYTHONDONTWRITEBYTECODE=1 python -u "$W/ciclo.py" --workers 4 > "$W/metrics/ciclo_$n.log" 2>&1 || { echo "ciclo $n falhou"; break; }
  p=$(python -c "import json;print(json.load(open('$W/metrics/ciclo_estado.json'))['ciclos'][-1].get('promovido'))")
  echo "ciclo $n promovido=$p $(grep 'pares decididos' "$W/metrics/ciclo_$n.log")"
  [ "$p" = "True" ] && break
done
echo FIM
