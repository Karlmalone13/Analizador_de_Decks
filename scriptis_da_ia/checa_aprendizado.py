# -*- coding: utf-8 -*-
"""O BOT APRENDE COM OS TREINOS? Checagem antes de gastar maquina treinando.

Pedido do usuario (13/09/2026, bloco 795): *"depois de resolvido quero que
check se o bot aprende com os treinos, e se estando tudo certo, acho que
podemos comecar a treinar e a coletar dados"*.

Treinar so vale se DUAS coisas forem verdade, e as duas sao medidas aqui:

  1. **MAIS DADO -> MODELO MELHOR.** Curva de aprendizado: o mesmo treino
     sobre 25%, 50% e 100% do corpus. Se o AUC fora da amostra sobe, aprender
     mais e possivel. Se e plano, o gargalo nao e volume -- e coletar mais do
     mesmo nao desbloqueia nada (foi o que o bloco 707 achou pro ranqueador).

  2. **MODELO MELHOR -> DECISAO DIFERENTE.** Um modelo que aprende e nao muda
     o que o bot faz e decoracao. Joga as MESMAS seeds com o modelo pequeno e
     com o grande e conta em quantas decisoes eles divergem.

O (2) importa mais que o (1) desde os blocos 790-794: o modelo agora DECIDE
tudo que e valor, entao uma mudanca nele tem por onde chegar ao tabuleiro --
coisa que no desenho somado (peso sobre a heuristica) nao acontecia.

Uso:
    python checa_aprendizado.py --dataset metrics/corpus_professor.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).parent
TMP = RAIZ / 'metrics' / 'aprendizado'


def treina(dataset: Path, fracao: float, saida: Path) -> dict:
    """Treina sobre uma FRACAO do corpus. Devolve o bundle resumido."""
    linhas = dataset.read_text(encoding='utf-8').splitlines()
    n = max(1, int(len(linhas) * fracao))
    rng = random.Random(7)
    amostra = rng.sample(linhas, n) if n < len(linhas) else linhas
    parcial = TMP / ('corpus_%d.jsonl' % int(fracao * 100))
    parcial.write_text('\n'.join(amostra) + '\n', encoding='utf-8')

    t0 = time.time()
    r = subprocess.run(
        [sys.executable, 'treinar_value.py', '--dataset', str(parcial),
         '--alvo', 'professor', '--features', 'aluno', '--out', str(saida)],
        cwd=str(RAIZ), capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:])
        print(r.stderr[-1500:])
        raise SystemExit('treino falhou em %d%%' % int(fracao * 100))
    import joblib
    b = joblib.load(saida)
    return {'fracao': fracao, 'estados': b.get('n_estados'),
            'auc': b.get('auc_fora_amostra'), 'auc_treino': b.get('auc_treino'),
            'minutos': round((time.time() - t0) / 60.0, 1)}


def joga(modelo: Path, n: int, seed_base: int):
    """Joga `n` partidas com ESTE modelo decidindo. Devolve as acoes escolhidas."""
    from optcg_engine import decision_engine as de
    from optcg_engine import value_net as vn
    from gerar_selfplay_dataset import _load_deck_list

    dl = _load_deck_list()
    escolhas, desfechos = [], []
    orig = de.OPTCGMatch._select_action_via_search

    def espiao(self, p, opp, engine, candidatas):
        r = orig(self, p, opp, engine, candidatas)
        try:
            a = r[0]
            escolhas.append((a[1], getattr(a[2], 'code', None),
                             a[5] if len(a) > 5 else None))
        except Exception:
            escolhas.append(None)
        return r

    de.OPTCGMatch._select_action_via_search = espiao
    try:
        for i in range(n):
            seed = seed_base * 1_000_003 + i
            rng = random.Random(seed)
            ia, ib = rng.sample(range(len(dl)), 2)
            random.seed(seed)
            m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
            for st in (m.state_a, m.state_b):
                st.modelo_ordena_path = str(modelo)
            m.setup()
            w, t = None, 0
            for t_ in range(m.MAX_TURNS * 2):
                p = (m.state_a if m.state_a.is_first else m.state_b) if t_ % 2 == 0 \
                    else (m.state_b if m.state_a.is_first else m.state_a)
                o = m.state_b if p is m.state_a else m.state_a
                t = t_ + 1
                r = m.play_turn(p, o)
                if r:
                    w = r
                    break
            desfechos.append('%s/%d' % (w, t))
            vn.limpar_cache_win_prob()
    finally:
        de.OPTCGMatch._select_action_via_search = orig
    return escolhas, desfechos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='metrics/corpus_professor.jsonl')
    ap.add_argument('--partidas', type=int, default=3)
    args = ap.parse_args()

    TMP.mkdir(parents=True, exist_ok=True)
    dataset = RAIZ / args.dataset

    print()
    print('=' * 68)
    print('1) MAIS DADO -> MODELO MELHOR?   (curva de aprendizado)')
    print('=' * 68, flush=True)
    curva = []
    for fr in (0.25, 0.50, 1.00):
        saida = TMP / ('modelo_%d.joblib' % int(fr * 100))
        r = treina(dataset, fr, saida)
        curva.append(r)
        print('  %3d%% do corpus | %6d estados | AUC fora %.4f | treino %.4f | %.1f min'
              % (int(fr * 100), r['estados'], r['auc'], r['auc_treino'], r['minutos']),
              flush=True)

    subiu = curva[-1]['auc'] - curva[0]['auc']
    print()
    print('  AUC de 25%% para 100%%: %+.4f' % subiu)
    if subiu >= 0.01:
        print('  => APRENDE COM MAIS DADO. Coletar mais vale a pena.')
    elif subiu <= -0.005:
        print('  => PIORA com mais dado. Investigar antes de coletar.')
    else:
        print('  => SATUROU. Mais do MESMO dado nao desbloqueia -- o gargalo')
        print('     e representacao ou diversidade, nao volume.')

    print()
    print('=' * 68)
    print('2) MODELO MELHOR -> DECISAO DIFERENTE?')
    print('=' * 68, flush=True)
    peq, des_peq = joga(TMP / 'modelo_25.joblib', args.partidas, 101)
    gra, des_gra = joga(TMP / 'modelo_100.joblib', args.partidas, 101)

    # RESSALVA DE MEDICAO (achada ao ler o primeiro resultado): comparar
    # decisao-a-decisao por POSICAO so vale ATE a primeira divergencia. Depois
    # dela os dois jogos estao em estados diferentes, entao "tudo difere" e
    # tautologia -- a primeira rodada reportou 96,6% por isso, e o numero nao
    # significava o que parecia. O que vale e: (a) em que decisao os dois
    # modelos se separam pela primeira vez, e (b) se o jogo termina diferente.
    n = min(len(peq), len(gra))
    primeira = next((i for i in range(n) if peq[i] != gra[i]), None)
    dif = 1 if primeira is not None else 0
    print('  decisoes ate a 1a divergencia : %s'
          % ('%d de %d' % (primeira, n) if primeira is not None
             else 'nenhuma -- modelos indistinguiveis'))
    print('  desfechos diferentes          : %s'
          % ('SIM' if des_peq != des_gra else 'nao'))
    print('  desfechos 25%%  : %s' % ' '.join(des_peq))
    print('  desfechos 100%% : %s' % ' '.join(des_gra))
    print()
    if primeira is None and des_peq == des_gra:
        print('  => O TREINO NAO CHEGA AO TABULEIRO. Treinar seria decoracao.')
    else:
        print('  => O TREINO MUDA O QUE O BOT FAZ. E o pre-requisito de treinar.')

    (TMP / 'resultado.json').write_text(json.dumps(
        {'curva': curva, 'decisoes_comparadas': n, 'decisoes_diferentes': dif,
         'desfechos_25': des_peq, 'desfechos_100': des_gra},
        indent=2, ensure_ascii=False), encoding='utf-8')
    print('  gravado em metrics/aprendizado/resultado.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
