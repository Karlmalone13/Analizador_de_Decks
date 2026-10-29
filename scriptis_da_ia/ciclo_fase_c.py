"""CICLO da fase C (PLANO_MOTOR_FORTE / INSTRUCAO_MESTRA item 14), automatico:

  geracao N:  auto-jogo com a CAMPEA (busca + rede, defesa pela rede)
              -> treina candidata nas ultimas `--janela` geracoes de dados
              -> ARENA candidata x campea (lados alternados)
              -> promove se vencer >= `--limite` das partidas com vencedor

Tudo registrado em `metrics/autojogo/ciclo.jsonl` (uma linha por geracao:
dados, treino, placar, promovida?). O portao SPRT do projeto entra depois;
o limite aqui e triagem.

Uso: python ciclo_fase_c.py --campea metrics/autojogo/rede_gen003.json --inicio 3 --geracoes 5
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

PY = sys.executable
D = 'metrics/autojogo'


def roda(args, log):
    t0 = time.time()
    r = subprocess.run([PY] + args, capture_output=True, text=True)
    out = r.stdout + r.stderr
    with open(log, 'a', encoding='utf-8') as f:
        f.write(f'\n$ {" ".join(args)}\n{out}')
    return out, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campea', required=True)
    ap.add_argument('--inicio', type=int, required=True, help='numero da geracao da campea')
    ap.add_argument('--geracoes', type=int, default=5)
    ap.add_argument('--partidas', type=int, default=1000)
    ap.add_argument('--arena', type=int, default=200)
    ap.add_argument('--iteracoes', type=int, default=200)
    ap.add_argument('--janela', type=int, default=4)
    ap.add_argument('--limite', type=float, default=0.55)
    a = ap.parse_args()
    campea, g = a.campea, a.inicio
    log = f'{D}/ciclo.log'
    for k in range(a.geracoes):
        dados = f'{D}/ciclo_dados_g{g:03d}.npz'
        out, t = roda(['autojogo.py', '--partidas', str(a.partidas), '--seed', str(100000 + 7919 * g),
                       '--iteracoes', str(a.iteracoes), '--rede', campea, '--defesa-rede', '--saida', dados], log)
        linha_dados = [l for l in out.splitlines() if 'partidas em' in l]
        # pela GERACAO (o nome nao ordena: `ciclo_dados_*` viria antes de `gen*`)
        janela = sorted((f for f in os.listdir(D) if re.match(r'(gen\d{3}|ciclo_dados_g\d{3})\.npz$', f)),
                        key=lambda f: int(re.search(r'(\d{3})\.npz$', f).group(1)))[-a.janela:]
        cand = f'{D}/rede_gen{g + 1:03d}.json'
        out_t, t_t = roda(['rede_pv.py', '--dados'] + [f'{D}/{f}' for f in janela] + ['--saida', cand, '--epocas', '10'], log)
        treino = [l for l in out_t.splitlines() if l.startswith('epoca') or l.startswith('melhor')][-2:]
        out_a, t_a = roda(['autojogo.py', '--partidas', str(a.arena), '--seed', str(200000 + 7919 * g),
                           '--iteracoes', str(a.iteracoes), '--defesa-rede', '--rede', cand, '--rede-b', campea,
                           '--saida', f'{D}/arena_ciclo_g{g + 1:03d}.npz'], log)
        m = re.search(r'ARENA: --rede (\d+) x (\d+) --rede-b', out_a)
        v, d_ = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        taxa = v / max(v + d_, 1)
        promovida = taxa >= a.limite
        reg = {'geracao': g + 1, 'campea_antes': campea, 'candidata': cand, 'dados': dados,
               'linha_dados': linha_dados, 'janela': janela, 'treino': treino,
               'arena': [v, d_], 'taxa': round(taxa, 3), 'promovida': promovida,
               'tempos_s': [round(t), round(t_t), round(t_a)], 'quando': time.strftime('%Y-%m-%d %H:%M')}
        with open(f'{D}/ciclo.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(reg, ensure_ascii=False) + '\n')
        print(json.dumps(reg, ensure_ascii=False), flush=True)
        if promovida:
            campea = cand
        g += 1
    print(f'campea final: {campea}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
