"""REDE de POLITICA + VALOR da fase C (PLANO_MOTOR_FORTE), treinada no auto-jogo.

Le os .npz do `autojogo.py` (features do `optcg_core/src/feats.rs`, fonte unica)
e treina, em numpy puro (sem torch no ambiente):

  tronco   h  = relu(W2 relu(W1 s + b1) + b2)          s = estado normalizado
  valor    v  = sigmoide(wv . h + bv)                   alvo: venceu (z)
  politica u  = relu(Wa [h ; a] + ba), logit = wp . u   a = jogada normalizada
           softmax entre as jogadas legais da decisao   alvo: visitas da busca

Perda = BCE(valor) + entropia cruzada(politica). Validacao separada POR
PARTIDA (nunca a mesma partida no treino e na validacao). Saida: JSON com os
pesos e a normalizacao, que o nucleo carrega (`optcg_core.carrega_rede`).

Uso: python rede_pv.py --dados metrics/autojogo/gen000.npz --saida metrics/autojogo/rede_gen001.json
"""
import argparse
import json
import sys

import numpy as np


def carrega(caminhos):
    partes = [np.load(c) for c in caminhos]
    S = np.concatenate([p['S'] for p in partes])
    A = np.concatenate([p['A'] for p in partes])
    z = np.concatenate([p['z'] for p in partes])
    vis = np.concatenate([p['visitas'] for p in partes]).astype(np.float64)
    ini, part, base_d, base_p = [], [], 0, 0
    for p in partes:
        i = p['ini'][:-1] + base_d
        ini.append(i)
        part.append(p['partida'] + base_p)
        base_d += int(p['ini'][-1])
        base_p += int(p['partida'].max()) + 1
    ini = np.concatenate(ini + [np.array([base_d])])
    return S, A, z, vis, ini, np.concatenate(part)


class Rede:
    def __init__(self, ns, na, h=64, hp=32, semente=0):
        r = np.random.default_rng(semente)
        g = lambda a, b: r.normal(0, np.sqrt(2.0 / a), (a, b))
        self.p = {'W1': g(ns, h), 'b1': np.zeros(h), 'W2': g(h, h), 'b2': np.zeros(h),
                  'wv': g(h, 1)[:, 0] * 0.1, 'bv': np.zeros(1),
                  'Wa': g(h + na, hp), 'ba': np.zeros(hp), 'wp': g(hp, 1)[:, 0] * 0.1, 'bp': np.zeros(1)}
        self.m = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.t = 0

    def passo(self, Sb, Ab, d, zb, pib, B, cv=1.0, lr=1e-3, treina=True):
        p = self.p
        H1 = np.maximum(Sb @ p['W1'] + p['b1'], 0)
        H2 = np.maximum(H1 @ p['W2'] + p['b2'], 0)
        vl = H2 @ p['wv'] + p['bv'][0]
        v = 1 / (1 + np.exp(-vl))
        Z = np.concatenate([H2[d], Ab], axis=1)
        U = np.maximum(Z @ p['Wa'] + p['ba'], 0)
        L = U @ p['wp'] + p['bp'][0]
        mx = np.full(B, -np.inf)
        np.maximum.at(mx, d, L)
        E = np.exp(L - mx[d])
        soma = np.zeros(B)
        np.add.at(soma, d, E)
        P = E / soma[d]
        perda_v = -np.mean(zb * np.log(v + 1e-9) + (1 - zb) * np.log(1 - v + 1e-9))
        perda_p = -np.sum(pib * np.log(P + 1e-12)) / B
        if not treina:
            return perda_v, perda_p, v, P
        dL = (P - pib) / B
        g = {}
        g['wp'] = U.T @ dL
        g['bp'] = np.array([dL.sum()])
        dU = np.outer(dL, p['wp']) * (U > 0)
        g['Wa'] = Z.T @ dU
        g['ba'] = dU.sum(0)
        dZ = dU @ p['Wa'].T
        dH2 = np.zeros_like(H2)
        np.add.at(dH2, d, dZ[:, :H2.shape[1]])
        dvl = cv * (v - zb) / B
        g['wv'] = H2.T @ dvl
        g['bv'] = np.array([dvl.sum()])
        dH2 += np.outer(dvl, p['wv'])
        dH2 *= (H2 > 0)
        g['W2'] = H1.T @ dH2
        g['b2'] = dH2.sum(0)
        dH1 = (dH2 @ p['W2'].T) * (H1 > 0)
        g['W1'] = Sb.T @ dH1
        g['b1'] = dH1.sum(0)
        self.t += 1
        b1, b2 = 0.9, 0.999
        for k in p:
            self.m[k] = b1 * self.m[k] + (1 - b1) * g[k]
            self.v[k] = b2 * self.v[k] + (1 - b2) * g[k] ** 2
            mh = self.m[k] / (1 - b1 ** self.t)
            vh = self.v[k] / (1 - b2 ** self.t)
            p[k] -= lr * mh / (np.sqrt(vh) + 1e-8)
        return perda_v, perda_p, v, P


def lote(idx, S, A, z, pi, ini):
    """Decisoes `idx` -> (S, A achatado, decisao de cada jogada, z, alvo da politica)."""
    fat = [np.arange(ini[i], ini[i + 1]) for i in idx]
    d = np.concatenate([np.full(len(f), k) for k, f in enumerate(fat)])
    fat = np.concatenate(fat)
    return S[idx], A[fat], d, z[idx], pi[fat]


def avalia(rede, idx, S, A, z, pi, ini):
    Sb, Ab, d, zb, pb = lote(idx, S, A, z, pi, ini)
    pv, pp, v, P = rede.passo(Sb, Ab, d, zb, pb, len(idx), treina=False)
    acerto_v = np.mean((v > 0.5) == (zb > 0.5))
    # politica: a jogada de mais visitas e a de maior probabilidade?
    melhor_rede = np.full(len(idx), -1.0)
    np.maximum.at(melhor_rede, d, P)
    melhor_busca = np.full(len(idx), -1.0)
    np.maximum.at(melhor_busca, d, pb)
    top1 = np.zeros(len(idx))
    np.maximum.at(top1, d, ((P == melhor_rede[d]) & (pb == melhor_busca[d])).astype(float))
    return pv, pp, acerto_v, top1.mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dados', nargs='+', required=True)
    ap.add_argument('--saida', required=True)
    ap.add_argument('--epocas', type=int, default=30)
    ap.add_argument('--lote', type=int, default=256)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--semente', type=int, default=0)
    a = ap.parse_args()
    S, A, z, vis, ini, part = carrega(a.dados)
    # alvo da politica: visitas normalizadas por decisao
    soma = np.add.reduceat(vis, ini[:-1]) if len(vis) else vis
    soma_por = np.repeat(np.maximum(soma, 1e-9), np.diff(ini))
    pi = vis / soma_por
    ms, ss = S.mean(0), S.std(0) + 1e-6
    ma, sa = A.mean(0), A.std(0) + 1e-6
    Sn, An = (S - ms) / ss, (A - ma) / sa
    r = np.random.default_rng(a.semente)
    partidas = np.unique(part)
    r.shuffle(partidas)
    val_p = set(partidas[: max(1, len(partidas) // 5)].tolist())
    eh_val = np.array([p in val_p for p in part])
    tr, va = np.where(~eh_val)[0], np.where(eh_val)[0]
    print(f'{len(S)} decisoes ({len(partidas)} partidas): treino {len(tr)}, validacao {len(va)}; '
          f'estado {S.shape[1]}, jogada {A.shape[1]}')
    rede = Rede(S.shape[1], A.shape[1], semente=a.semente)
    base_v = -np.mean(z[va] * np.log(z[tr].mean()) + (1 - z[va]) * np.log(1 - z[tr].mean()))
    print(f'referencia do valor (so a media): BCE {base_v:.4f}')
    melhor = (np.inf, None)
    for ep in range(a.epocas):
        r.shuffle(tr)
        for k in range(0, len(tr), a.lote):
            idx = tr[k:k + a.lote]
            Sb, Ab, d, zb, pb = lote(idx, Sn, An, z, pi, ini)
            rede.passo(Sb, Ab, d, zb, pb, len(idx), lr=a.lr)
        pv, pp, av, t1 = avalia(rede, va, Sn, An, z, pi, ini)
        print(f'epoca {ep + 1}: validacao valor BCE {pv:.4f} acerto {av:.3f} | politica CE {pp:.4f} top1 {t1:.3f}', flush=True)
        if pv + pp < melhor[0]:
            melhor = (pv + pp, {k: v.copy() for k, v in rede.p.items()})
    saida = {k: v.tolist() for k, v in melhor[1].items()}
    saida.update({'media_s': ms.tolist(), 'desvio_s': ss.tolist(), 'media_a': ma.tolist(), 'desvio_a': sa.tolist(),
                  'n_estado': int(S.shape[1]), 'n_jogada': int(A.shape[1]), 'dados': a.dados})
    with open(a.saida, 'w') as f:
        json.dump(saida, f)
    print(f'melhor (valor+politica na validacao) {melhor[0]:.4f} -> {a.saida}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
