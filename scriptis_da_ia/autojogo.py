"""AUTO-JOGO da fase C (PLANO_MOTOR_FORTE): partidas inteiras no nucleo Rust com a
BUSCA decidindo a jogada principal dos dois lados. Gera o material do treino:
para cada decisao, a mesa (features), as jogadas legais, as visitas da busca em
cada uma (alvo da POLITICA) e o resultado da partida (alvo do VALOR).

Saida em binario (REGRA_DADOS_BINARIOS): um .npz por lote, matrizes numpy --
  X        (n, 32)   features da mesa de quem decide (`valor.rs` / state_features)
  lado     (n,)      0 = quem comecou, 1 = o outro
  partida  (n,)      indice da partida no lote
  z        (n,)      1 = quem decidiu venceu, 0 = perdeu, 0.5 = sem vencedor
  esc      (n,)      indice da jogada escolhida dentro das legais da decisao
  ini      (n+1,)    a decisao i tem as legais ini[i]:ini[i+1] em `acoes`/`visitas`
  acoes    (m, 4)    jogada legal: tipo(0 jogar,1 ativar,2 dar DON,3 atacar,4 fim),
                     zona do ator(0 mao,1 lider,2 campo,3 stage), indice do ator,
                     alvo do ataque(-1 lider, j = personagem j, -2 sem alvo)
  visitas  (m,)      visitas da busca em cada jogada legal
  S        (n, NS)   features da rede nova (`feats.rs::estado`), so o observavel
  A        (m, NA)   features de cada jogada legal (`feats.rs::jogada`)

Uso: python autojogo.py --partidas 20 --seed 9000 --iteracoes 500 --saida metrics/autojogo/gen000_a.npz
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import optcg_core
from bench_nucleo import estado_inicial

TIPO = {'play': 0, 'activate': 1, 'attach_don': 2, 'attack': 3, 'end': 4}
ZONA = {'hand': 0, 'leader': 1, 'field_chars': 2, 'stage': 3}


def codifica(j: dict) -> list:
    t = TIPO[j['tipo']]
    if t == 4:
        return [4, -1, -1, -2]
    z, i = j['ator']
    alvo = -2
    if t == 3:
        alvo = -1 if j['alvo_tipo'] == 'leader' else int(j['alvo'][2])
    return [t, ZONA[z], int(i), alvo]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=10)
    ap.add_argument('--seed', type=int, default=9000)
    ap.add_argument('--iteracoes', type=int, default=500)
    ap.add_argument('--turnos', type=int, default=0, help='turnos simulados depois do meu antes da nota')
    ap.add_argument('--c', type=float, default=0.7)
    ap.add_argument('--max-turnos', type=int, default=40)
    ap.add_argument('--saida', default='metrics/autojogo/gen000.npz')
    ap.add_argument('--sem-valor', action='store_true')
    ap.add_argument('--rede', default='', help='rede politica+valor (JSON do rede_pv.py) dos dois lados')
    ap.add_argument('--rede-b', default='', help='ARENA: rede do outro lado (os lados alternam a cada partida)')
    ap.add_argument('--defesa-rede', action='store_true', help='bloqueio/counter do defensor pela rede de valor')
    a = ap.parse_args()
    if not a.sem_valor:
        from optcg_engine import value_net as V
        optcg_core.carrega_valor(json.dumps(V.exporta_para_nucleo()))
    X, lado, partida, z, esc, ini, acoes, visitas, S, A = [], [], [], [], [], [0], [], [], [], []
    def carrega_rede(espaco, caminho):
        optcg_core.carrega_rede(espaco, open(caminho).read() if caminho else '')
    carrega_rede(1, a.rede)
    carrega_rede(2, a.rede_b)
    arena = bool(a.rede_b)
    placar = {'rede': 0, 'rede_b': 0, 'sem': 0}
    res = {'vencidas': 0, 'sem_vencedor': 0, 'fora': {}}
    t0 = time.time()
    for k in range(a.partidas):
        e = estado_inicial(a.seed + k)
        # espacos: 1 = --rede (0 se vazia), 2 = --rede-b; na arena o lado 0 alterna
        ea = 1 if a.rede else 0
        eb = 2 if arena else ea
        if arena and k % 2 == 1:
            ea, eb = eb, ea
        r = json.loads(optcg_core.autojogo(json.dumps(e), 0, a.iteracoes, a.turnos, a.c, a.seed + k, a.max_turnos, ea, eb, a.defesa_rede))
        if arena:
            v_ = r['vencedor']
            if v_ is None:
                placar['sem'] += 1
            else:
                placar['rede' if (ea if v_ == 0 else eb) == (1 if a.rede else 0) else 'rede_b'] += 1
        v = r['vencedor']
        if v is None:
            res['sem_vencedor'] += 1
            if r['fora_do_nucleo']:
                m = r['fora_do_nucleo'][:70]
                res['fora'][m] = res['fora'].get(m, 0) + 1
        else:
            res['vencidas'] += 1
        for g in r['registros']:
            X.append(g['feats'])
            lado.append(g['lado'])
            partida.append(k)
            z.append(0.5 if v is None else float(g['lado'] == v))
            esc.append(g['escolhida'])
            S.append(g['estado'])
            A.extend(g['jogadas'])
            for j, n in zip(g['legais'], g['visitas']):
                acoes.append(codifica(j))
                visitas.append(n)
            ini.append(len(acoes))
        print(f"partida {k}: vencedor {v}, {r['turnos']} turnos, {len(r['registros'])} decisoes, "
              f"{r['segundos']:.1f}s{'  fora: ' + r['fora_do_nucleo'][:60] if r['fora_do_nucleo'] else ''}", flush=True)
    os.makedirs(os.path.dirname(a.saida) or '.', exist_ok=True)
    np.savez_compressed(a.saida, X=np.asarray(X, np.float32), lado=np.asarray(lado, np.int8),
                        partida=np.asarray(partida, np.int32), z=np.asarray(z, np.float32),
                        esc=np.asarray(esc, np.int16), ini=np.asarray(ini, np.int64),
                        acoes=np.asarray(acoes, np.int16).reshape(-1, 4), visitas=np.asarray(visitas, np.int32),
                        S=np.asarray(S, np.float32), A=np.asarray(A, np.float32))
    print(f"\n{a.partidas} partidas em {time.time() - t0:.0f}s: {res['vencidas']} com vencedor, "
          f"{res['sem_vencedor']} sem; {len(X)} decisoes -> {a.saida}")
    if arena:
        n_ = placar['rede'] + placar['rede_b']
        print(f"ARENA: --rede {placar['rede']} x {placar['rede_b']} --rede-b (sem vencedor {placar['sem']}) "
              f"= {100 * placar['rede'] / max(n_, 1):.0f}% para --rede")
    for m, n in sorted(res['fora'].items(), key=lambda x: -x[1]):
        print(f'   parou fora do nucleo: {m} ({n})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
