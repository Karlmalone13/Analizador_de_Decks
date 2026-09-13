#!/bin/sh
# Coleta GRANDE de alvos Q, fatiada -- pode ser interrompida a qualquer momento
# sem perder trabalho (bloco 798, pedido do usuario: "deixa a coleta grande
# engatilhada").
#
# POR QUE FATIADO: o gerador so grava no FIM da execucao. Um lote unico de 2.000
# partidas interrompido no meio perde TUDO -- aconteceu hoje, com 400 partidas.
# Aqui cada fatia grava e o acumulado aparece na tela, entao parar custa no
# maximo uma fatia.
#
# POR QUE A COLETA E MAIS LENTA QUE O JOGO: ela roda com a ARVORE no comando
# (~6,2 s/partida), porque e a busca quem calcula o valor por candidata -- que
# E o alvo Q. O Q (1,87 s/partida) joga; a arvore ensina. `gerar_selfplay_
# dataset.py` desliga o Q sozinho quando recebe `--q-out`.
#
# Uso:
#   sh coleta_q_grande.sh            # 2.000 partidas, fatias de 25
#   sh coleta_q_grande.sh 500 50     # 500 partidas, fatias de 50
#
# Depois de coletar:
#   python treinar_q.py --dataset metrics/q_alvos.jsonl --out metrics/q_net_desafiante.joblib
#   python treino_continuo.py --geracoes N --partidas M --workers 1

set -e
cd "$(dirname "$0")"

TOTAL="${1:-2000}"
FATIA="${2:-25}"
SEED_BASE="${3:-8000}"

export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1

# --workers 1: medido no bloco 797 -- com 2 workers o pool quebra
# (BrokenProcessPool) por falta de RAM (2,4 GB livres de 11,9); cada worker
# carrega banco de cartas, efeitos e modelos.
WORKERS=1

echo "coleta de $TOTAL partidas em fatias de $FATIA (workers=$WORKERS)"
echo "estimativa: ~$(( TOTAL * 62 / 600 )) min a ~6,2 s/partida"
echo

feitas=0
lote=0
while [ "$feitas" -lt "$TOTAL" ]; do
    lote=$(( lote + 1 ))
    restam=$(( TOTAL - feitas ))
    n="$FATIA"
    [ "$restam" -lt "$FATIA" ] && n="$restam"

    python gerar_selfplay_dataset.py \
        --n "$n" --workers "$WORKERS" --decks 24 \
        --seed $(( SEED_BASE + lote )) --append \
        --out metrics/selfplay_v2.jsonl \
        --q-out metrics/q_alvos.jsonl 2>&1 | grep -i "alvos Q" || true

    feitas=$(( feitas + n ))
    acc=$(wc -l < metrics/q_alvos.jsonl)
    echo "  lote $lote | $feitas/$TOTAL partidas | $acc alvos acumulados"
done

echo
echo "coleta terminada: $(wc -l < metrics/q_alvos.jsonl) alvos em metrics/q_alvos.jsonl"
echo "PROXIMO: treinar_q.py, e so entao o portao -- treinar nao e ganho no motor."
