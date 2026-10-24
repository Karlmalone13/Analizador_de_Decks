#!/usr/bin/env python
"""Confere `traj_bin.trajetorias` (bloco 988) contra `treinar_q.carrega_trajetorias`:
o MESMO dict (chaves, ordem dos turnos, valores da regua), e cronometra."""
import sys
import time
from pathlib import Path

import traj_bin
import treinar_q as tq
from optcg_engine import value_net as vn
from optcg_engine.decision_engine import MODELO_ORDENA_PATH

aval = vn.load_value_net(MODELO_ORDENA_PATH)
sp = Path(tq.SELFPLAY)
t = time.perf_counter(); a = tq.carrega_trajetorias(sp, avaliador=aval); t0 = time.perf_counter() - t
t = time.perf_counter(); b = traj_bin.trajetorias(sp, avaliador=aval); t1 = time.perf_counter() - t
t = time.perf_counter(); c = traj_bin.trajetorias(sp, avaliador=aval); t2 = time.perf_counter() - t
igual = a == b == c
print(f'antigo {t0:.0f}s | cache 1a vez (monta) {t1:.0f}s | cache {t2:.0f}s')
print(f'partidas {len(a)} | estados {sum(map(len, a.values()))} | IDENTICO: {igual}')
sys.exit(0 if igual else 1)
