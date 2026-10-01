#!/bin/bash
# Loop de ciclos ate promover (max 6). Uso: bash metrics/_loop_ciclos.sh  (de scriptis_da_ia)
W='C:/Projetos_TI/analidador_de_decks_optcg/scriptis_da_ia'
cd "$W" || exit 1
for i in 1 2 3 4 5 6; do
  n=$(python -c "import json;print(len(json.load(open('$W/metrics/ciclo_estado.json'))['ciclos'])+1)") || break
  PYTHONDONTWRITEBYTECODE=1 python -u "$W/ciclo.py" --workers 4 > "$W/metrics/ciclo_$n.log" 2>&1 || { echo "ciclo $n falhou"; break; }
  p=$(python -c "import json;print(json.load(open('$W/metrics/ciclo_estado.json'))['ciclos'][-1].get('promovido'))")
  echo "ciclo $n promovido=$p $(grep 'pares decididos' "$W/metrics/ciclo_$n.log")"
  [ "$p" = "True" ] && break
done
echo FIM
