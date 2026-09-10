"""
treino_continuo.py
==================
LACO de aprendizado por auto-jogo: o motor joga, aprende com o que jogou,
e so adota a versao nova se ela PROVAR que e melhor. Roda em geracoes.

Pedido do usuario (08/09/2026): *"o que precisamos fazer e criar uma ML
que melhore a jogabilidade com o tempo e vai aprendendo com cada
partida"*.

POR QUE ISTO E DIFERENTE DA TENTATIVA DE TIRO UNICO (bloco 753)
---------------------------------------------------------------
No bloco 753 o dataset veio de partidas jogadas pelo motor **sem** o
modelo, e o modelo foi depois usado **com** ele. Treino e uso em
distribuicoes diferentes. O modelo aprendeu bem (AUC 0,707 fora da
amostra) e nao converteu em acerto.

Aqui cada geracao **joga com o modelo da geracao anterior ligado** e
aprende sobre os estados que ela mesma produz. E a correcao classica
desse problema, e e o unico caminho de ML que o projeto ainda nao tinha
testado -- os blocos 680-683 ja mediram que "mais features" NAO resolve.

O CICLO DE UMA GERACAO
----------------------
  1. GERA   -- N partidas com o CAMPEAO ligado (peso + modelo atuais).
               As amostras sao APENDADAS ao corpus, que so cresce.
  2. TREINA -- reajusta sobre o corpus inteiro, GroupKFold POR LIDER
               (`treinar_value.py`), num arquivo de DESAFIANTE.
  3. DUELA  -- campeao x desafiante na MESMA partida, lados alternados
               (o lado que comeca alterna a cada duelo, senao a vantagem
               de iniciativa vira "ganho" do modelo).
  4. PROMOVE se e SO SE o desafiante bater o portao medido. Senao,
     DESCARTA o desafiante e segue com o campeao -- o corpus fica (o
     dado nao se perde), so o modelo nao e adotado.

O portao e o ponto todo: sem ele isto vira "treina e reza". Uma geracao
que nao prova ganho nao entra, e o historico registra as duas coisas.

O QUE ESTE LACO OTIMIZA (e a tensao registrada, nao escondida)
--------------------------------------------------------------
O duelo mede FORCA (quem ganha). A metrica OFICIAL do projeto mede
SEMELHANCA COM O HUMANO. Sao coisas diferentes e podem divergir -- foi
exatamente por isso que o usuario escolheu o caminho HIBRIDO: o termo de
alinhamento humano (`human_alignment`) continua na soma da avaliacao e
age como regularizador.

Por isso `--checar-metrica-oficial` roda `decision_quality_full.py` no
campeao promovido: forca que sobe as custas de despencar a semelhanca
humana e um resultado que o usuario precisa VER, nao um detalhe. Nao e
rodado a cada geracao porque e caro (~10 min).

Uso:
  python treino_continuo.py --geracoes 5 --partidas 100 --workers 4
  python treino_continuo.py --geracoes 3 --partidas 60 --workers 4 --duelos 40
  python treino_continuo.py --status          # so mostra o historico
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    raise SystemExit(subprocess.call([sys.executable] + sys.argv))

sys.path.insert(0, str(Path(__file__).parent))

from optcg_engine.decision_engine import OPTCGMatch

RAIZ = Path(__file__).parent
CAMPEAO = RAIZ / 'metrics' / 'value_net.joblib'
DESAFIANTE = RAIZ / 'metrics' / 'value_net_desafiante.joblib'
CORPUS = RAIZ / 'metrics' / 'selfplay_dataset.jsonl'
HISTORICO = RAIZ / 'metrics' / 'treino_continuo' / 'historico.json'


# ── DUELO: campeao x desafiante ─────────────────────────────────────────

def _duelo(task) -> dict:
    """1 partida com CONFIGURACOES DIFERENTES nos dois lados.

    `desafiante_e_A` alterna entre duelos: quem joga primeiro tem
    vantagem estrutural neste jogo, entao sem alternar o resultado
    mediria iniciativa, nao modelo."""
    (i, seed, desafiante_e_A, peso_camp, peso_desaf) = task
    from gerar_selfplay_dataset import _load_deck_list

    deck_list = _load_deck_list()
    rng = random.Random(seed)
    idx_a, idx_b = rng.sample(range(len(deck_list)), 2)
    _code_a, deck_a = deck_list[idx_a]
    _code_b, deck_b = deck_list[idx_b]
    random.seed(seed)

    try:
        match = OPTCGMatch(deck_a, deck_b)
        match.setup()
    except Exception:
        return {'erro': True}

    lado_desaf = match.state_a if desafiante_e_A else match.state_b
    lado_camp = match.state_b if desafiante_e_A else match.state_a
    lado_desaf.value_net_weight = peso_desaf
    lado_desaf.value_net_path = str(DESAFIANTE)
    lado_camp.value_net_weight = peso_camp
    lado_camp.value_net_path = str(CAMPEAO) if CAMPEAO.exists() else None

    winner = None
    try:
        for turn_num in range(match.MAX_TURNS * 2):
            p = (match.state_a if match.state_a.is_first else match.state_b) \
                if turn_num % 2 == 0 \
                else (match.state_b if match.state_a.is_first else match.state_a)
            opp = match.state_b if p is match.state_a else match.state_a
            r = match.play_turn(p, opp)
            if r:
                winner = r
                break
    except Exception:
        return {'erro': True}

    if winner is None:
        return {'empate': True}
    venceu_desaf = (winner == 'A') == desafiante_e_A
    return {'desafiante': bool(venceu_desaf)}


def duelar(n: int, workers: int, seed: int, peso_camp: float,
           peso_desaf: float, pareado: bool = True) -> dict:
    """Portao campeao x desafiante.

    `pareado=True` (default desde o bloco 756) usa ESPELHO PAREADO: cada
    par de partidas roda a MESMA seed -- e portanto o MESMO par de decks e
    o MESMO embaralhamento (`_duelo` deriva os dois da seed) -- uma vez com
    o desafiante do lado A e outra do lado B. So conta o par em que o mesmo
    modelo vence dos DOIS lados; par dividido significa que quem decidiu foi
    o matchup/iniciativa, nao o modelo, e entra como SEM INFORMACAO.

    Por que mudou (medido, bloco 756): o desenho anterior sorteava seed E
    par de decks novos a cada duelo, entao a variancia somava matchup +
    embaralhamento + lado. Com ~54 partidas decididas o portao de 55% tinha
    **10,9% de poder** -- uma geracao genuinamente melhor era descartada em
    89% das vezes, que e exatamente o que as 3 primeiras geracoes fizeram
    (48,2% / 49,1% / 53,1%, todas com IC95 de +-13pp incluindo 50%). O
    portao nao estava reprovando modelo ruim: nao estava conseguindo medir.

    O desenho espelho+pareado e o MESMO que ja tinha resolvido um problema
    de variancia identico na calibragem do score de mao (commit 41731f5,
    bloco 752): sem ele a forca de deck vazava pros coeficientes.

    `_duelo` continua sendo a UNICA funcao que roda uma partida de duelo --
    aqui so muda como as tarefas sao geradas e contadas.
    """
    if not pareado:
        tasks = [(i, seed * 1_000_003 + i, i % 2 == 0, peso_camp, peso_desaf)
                 for i in range(n)]
        return _contar_solto(tasks, workers)

    # n partidas => n//2 pares espelhados (mesma seed, lados trocados).
    n_pares = max(1, n // 2)
    tasks = []
    for j in range(n_pares):
        sj = seed * 1_000_003 + j
        tasks.append((2 * j, sj, True, peso_camp, peso_desaf))
        tasks.append((2 * j + 1, sj, False, peso_camp, peso_desaf))

    res = _rodar_tasks(tasks, workers)

    vit = der = div = descartados = 0
    for j in range(n_pares):
        a, b = res[2 * j], res[2 * j + 1]
        if a.get('erro') or b.get('erro') or a.get('empate') or b.get('empate'):
            descartados += 1
            continue
        ga, gb = a['desafiante'], b['desafiante']
        if ga and gb:
            vit += 1          # desafiante venceu dos DOIS lados
        elif (not ga) and (not gb):
            der += 1          # campeao venceu dos DOIS lados
        else:
            div += 1          # dividido: decidiu o matchup/iniciativa
    decididos = vit + der
    return {
        'vitorias_desafiante': vit, 'derrotas_desafiante': der,
        'empates': div, 'erros': descartados, 'decididas': decididos,
        'winrate_desafiante': (vit / decididos) if decididos else None,
        'pareado': True, 'pares_rodados': n_pares,
        'pares_divididos': div, 'partidas': len(tasks),
    }


def limite_inferior_wilson(vitorias: int, n: int, z: float = 1.96) -> float:
    """Limite INFERIOR do IC de Wilson pra proporcao.

    Existe por um risco que o espelho pareado CRIA (bloco 756): pares
    divididos nao contam, entao o n de pares DECIDIDOS pode ficar pequeno --
    e um portao que olha so a media (`vitorias/n >= 0.55`) promoveria com
    2 de 3 (66,7%) em cima de ruido puro. O limite inferior resolve os dois
    lados de uma vez: com n pequeno ele fica bem abaixo da media e barra
    sozinho, e com n grande converge pra media. Wilson (nao normal simples)
    porque n pequeno e proporcao perto de 0/1 quebram a aproximacao normal.
    """
    if n <= 0:
        return 0.0
    p = vitorias / n
    d = 1.0 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    margem = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / d
    return max(0.0, centro - margem)


def duelar_sprt(workers: int, seed: int, peso_camp: float, peso_desaf: float,
                p0: float = 0.50, p1: float = 0.65,
                alpha: float = 0.05, beta: float = 0.05,
                pares_por_lote: int = 20, max_pares: int = 200,
                progresso=None) -> dict:
    """Portao por PARADA SEQUENCIAL (SPRT de Wald) -- default desde o bloco 762.

    POR QUE SUBSTITUIU o portao de Wilson (medido, nao teorico): em 10/09 a
    geracao 4 PASSOU no portao de Wilson com 11x3 em 14 pares discordantes
    (limite 52,4% contra corte de 50%) e foi promovida. Re-testada com 31
    pares discordantes, deu **12x19 (38,7%)** -- **a promocao era FALSO
    POSITIVO**. O Wilson com n pequeno nao errou a conta; o problema e que
    ele nao tem como saber que 14 pares e pouco, e o portao nao exigia
    minimo. O SPRT resolve isso por construcao: ele so decide quando a
    evidencia ACUMULADA basta, nos dois sentidos.

    Roda o MESMO duelo espelho pareado (`duelar`) em lotes, acumulando o log
    da razao de verossimilhanca sobre os pares DISCORDANTES (os divididos
    sao empates e nao entram -- teste de McNemar; empate nao diz nada sobre
    direcao). Cruzar o limite superior ACEITA H1 (desafiante melhor), o
    inferior ACEITA H0 (equivalentes).

    Nao e "espiar ate dar certo": os limites do SPRT ja embutem o custo das
    checagens repetidas, ao contrario de olhar o IC a cada lote.

    Bonus medido: para CEDO nos casos claros. Na rodada que pegou o falso
    positivo, cruzou o limite em 140 pares em vez dos 200 do teto.
    """
    import math
    lim_sup = math.log((1 - beta) / alpha)
    lim_inf = math.log(beta / (1 - alpha))
    ganho_vit = math.log(p1 / p0)
    ganho_der = math.log((1 - p1) / (1 - p0))

    vit = der = div = pares = partidas = erros = 0
    llr = 0.0
    veredito, promove = 'INCONCLUSIVO (teto de pares)', False
    lote = 0
    while pares < max_pares:
        lote += 1
        d = duelar(n=pares_por_lote * 2, workers=workers,
                   seed=seed + lote * 1000, peso_camp=peso_camp,
                   peso_desaf=peso_desaf, pareado=True)
        vit += d['vitorias_desafiante']
        der += d['derrotas_desafiante']
        div += d['pares_divididos']
        erros += d['erros']
        pares += d['pares_rodados']
        partidas += d['partidas']
        llr = vit * ganho_vit + der * ganho_der
        if progresso:
            progresso(lote, pares, vit, der, llr, lim_sup, lim_inf)
        if llr >= lim_sup:
            veredito, promove = 'PROMOVE (desafiante e melhor)', True
            break
        if llr <= lim_inf:
            veredito = 'DESCARTA (equivalentes)'
            break

    disc = vit + der
    return {
        'vitorias_desafiante': vit, 'derrotas_desafiante': der,
        'empates': div, 'erros': erros, 'decididas': disc,
        'winrate_desafiante': (vit / disc) if disc else None,
        'pareado': True, 'sprt': True, 'llr': llr,
        'lim_sup': lim_sup, 'lim_inf': lim_inf,
        'pares_rodados': pares, 'pares_divididos': div,
        'partidas': partidas, 'lotes': lote,
        'veredito': veredito, 'promove': promove,
    }


def _rodar_tasks(tasks: list, workers: int) -> list:
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_duelo, tasks))
    return [_duelo(t) for t in tasks]


def _contar_solto(tasks: list, workers: int) -> dict:
    """Contagem do desenho ANTIGO (nao pareado), mantida so pra comparacao
    A/B -- ver o docstring de `duelar`."""
    res = _rodar_tasks(tasks, workers)
    vit = sum(1 for r in res if r.get('desafiante') is True)
    der = sum(1 for r in res if r.get('desafiante') is False)
    emp = sum(1 for r in res if r.get('empate'))
    err = sum(1 for r in res if r.get('erro'))
    decididas = vit + der
    return {
        'vitorias_desafiante': vit, 'derrotas_desafiante': der,
        'empates': emp, 'erros': err, 'decididas': decididas,
        'winrate_desafiante': (vit / decididas) if decididas else None,
    }


# ── Passos externos (reusam as ferramentas que ja existem) ──────────────

def _rodar(cmd: list, descr: str) -> bool:
    print(f'  $ {" ".join(str(c) for c in cmd)}')
    r = subprocess.run([sys.executable] + cmd, cwd=str(RAIZ))
    if r.returncode != 0:
        print(f'  [FALHOU] {descr} (codigo {r.returncode})')
        return False
    return True


def carregar_historico() -> list:
    if HISTORICO.exists():
        try:
            return json.loads(HISTORICO.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


def salvar_historico(h: list) -> None:
    HISTORICO.parent.mkdir(parents=True, exist_ok=True)
    HISTORICO.write_text(json.dumps(h, indent=2, ensure_ascii=False), encoding='utf-8')


def mostrar_status() -> None:
    h = carregar_historico()
    if not h:
        print('sem historico ainda -- nenhuma geracao rodada.')
        return
    print(f'{"gen":>4} | {"estados":>8} | {"AUC fora":>9} | {"winrate":>8} | resultado')
    print('-----+----------+-----------+----------+----------')
    for r in h:
        wr = r.get('winrate_desafiante')
        wr_s = f'{wr:.1%}' if wr is not None else '   --   '
        auc = r.get('auc_fora_amostra')
        auc_s = f'{auc:.4f}' if auc else '   --   '
        print(f'{r.get("geracao", "?"):>4} | {r.get("estados_corpus", 0):>8} | '
              f'{auc_s:>9} | {wr_s:>8} | {r.get("resultado", "?")}')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--geracoes', type=int, default=3)
    ap.add_argument('--partidas', type=int, default=100, help='partidas geradas por geracao')
    ap.add_argument('--duelos', type=int, default=40, help='partidas do portao campeao x desafiante')
    ap.add_argument('--workers', type=int, default=__import__('multiprocessing').cpu_count() - 3)
    ap.add_argument('--peso', type=float, default=200.0,
                    help='peso do valor aprendido usado ao jogar')
    ap.add_argument('--portao', type=float, default=0.50,
                    help='o LIMITE INFERIOR do IC95 do winrate (Wilson) tem que '
                         'passar deste valor pro desafiante ser promovido. Default '
                         '0.50 = "melhor que cara-ou-coroa com significancia". '
                         'Mudou de media>=0.55 no bloco 756: com espelho pareado os '
                         'pares divididos nao contam, entao o n decidido pode ficar '
                         'pequeno e uma media alta em 2 de 3 pares e ruido')
    ap.add_argument('--portao-wilson', dest='portao_wilson', action='store_true',
                    help='volta ao portao de Wilson com n fixo (--duelos). So pra '
                         'A/B: foi ele que aprovou a geracao 4 por FALSO POSITIVO '
                         'em 10/09 (11x3 em 14 pares; re-teste deu 12x19 em 31)')
    ap.add_argument('--portao-media', dest='portao_media', action='store_true',
                    help='volta ao portao ANTIGO (media >= --portao). So pra A/B')
    ap.add_argument('--decks', type=int, default=24)
    ap.add_argument('--seed', type=int, default=101)
    ap.add_argument('--nao-pareado', dest='nao_pareado', action='store_true',
                    help='usa o desenho ANTIGO do portao (seed e decks novos a cada '
                         'duelo). So pra comparacao A/B -- medido com 10,9%% de poder '
                         'estatistico, ver docstring de duelar() (bloco 756)')
    ap.add_argument('--status', action='store_true', help='so mostra o historico e sai')
    args = ap.parse_args()

    if args.status:
        mostrar_status()
        return

    historico = carregar_historico()
    gen_inicial = (historico[-1]['geracao'] + 1) if historico else 1

    for k in range(args.geracoes):
        gen = gen_inicial + k
        seed_gen = args.seed + gen * 7919
        print(f'\n{"="*66}\nGERACAO {gen}\n{"="*66}')

        # Geracao 1 nao tem campeao ainda: joga com peso 0 (motor puro).
        tem_campeao = CAMPEAO.exists()
        peso_gerar = args.peso if tem_campeao else 0.0
        print(f'[1/4] GERA {args.partidas} partidas '
              f'(campeao {"ligado, peso " + str(peso_gerar) if tem_campeao else "inexistente -- motor puro"})')
        ok = _rodar(['gerar_selfplay_dataset.py', '--n', str(args.partidas),
                     '--workers', str(args.workers), '--decks', str(args.decks),
                     '--seed', str(seed_gen), '--gen', str(gen),
                     '--weight', str(peso_gerar), '--model', str(CAMPEAO),
                     '--append', '--out', str(CORPUS)], 'geracao de partidas')
        if not ok:
            break

        n_estados = sum(1 for _ in CORPUS.open(encoding='utf-8'))
        print(f'[2/4] TREINA desafiante sobre {n_estados} estados (corpus acumulado)')
        ok = _rodar(['treinar_value.py', '--dataset', str(CORPUS),
                     '--out', str(DESAFIANTE)], 'treino do desafiante')
        if not ok:
            break
        try:
            import joblib
            auc = joblib.load(DESAFIANTE).get('auc_fora_amostra')
        except Exception:
            auc = None

        registro = {
            'geracao': gen, 'quando': datetime.now().isoformat(timespec='seconds'),
            'partidas_geradas': args.partidas, 'estados_corpus': n_estados,
            'auc_fora_amostra': auc, 'peso': args.peso, 'portao': args.portao,
            'portao_modo': ('media' if args.portao_media else ('limite_inferior_wilson' if args.portao_wilson else 'sprt')),
            'llr': d.get('llr'), 'pares_rodados': d.get('pares_rodados'),
        }

        if not tem_campeao:
            # Sem campeao nao ha duelo possivel: o desafiante VIRA o
            # campeao inicial. Isso NAO e uma promocao medida, e o marco
            # zero -- registrado como tal pra ninguem ler o historico
            # depois achando que a geracao 1 provou alguma coisa.
            shutil.copyfile(DESAFIANTE, CAMPEAO)
            registro |= {'resultado': 'marco-zero (sem campeao pra duelar)',
                         'winrate_desafiante': None, 'promovido': True}
            print('[3/4] DUELO pulado -- nao havia campeao. Desafiante vira o marco zero.')
        else:
            print(f'[3/4] DUELA {args.duelos} partidas (lados alternados)')
            def _prog(lote, pares, vit, der, llr, sup, inf):
                print('      lote {:>2} | pares {:>3} | discordantes {:>3} '
                      '({}x{}) | LLR {:+.3f}  (sup {:+.2f} / inf {:+.2f})'
                      .format(lote, pares, vit + der, vit, der, llr, sup, inf),
                      flush=True)

            if args.portao_wilson:
                d = duelar(args.duelos, args.workers, seed_gen + 13, args.peso,
                           args.peso, pareado=not args.nao_pareado)
            else:
                d = duelar_sprt(args.workers, seed_gen + 13, args.peso,
                                args.peso, progresso=_prog)
            registro |= d
            wr = d['winrate_desafiante']
            if d.get('pareado'):
                print(f'      ESPELHO PAREADO: {d["pares_rodados"]} pares '
                      f'({d["partidas"]} partidas), desafiante venceu dos DOIS '
                      f'lados em {d["vitorias_desafiante"]}, perdeu dos dois em '
                      f'{d["derrotas_desafiante"]}, {d["pares_divididos"]} divididos '
                      f'(sem informacao), {d["erros"]} descartados')
                print(f'      winrate sobre pares decididos: '
                      f'{"n/d" if wr is None else f"{wr:.1%}"} (n={d["decididas"]})')
            else:
                print(f'      desafiante {d["vitorias_desafiante"]}-{d["derrotas_desafiante"]} '
                      f'({"n/d" if wr is None else f"{wr:.1%}"}), '
                      f'{d["empates"]} empates, {d["erros"]} erros')
            lim = limite_inferior_wilson(d['vitorias_desafiante'], d['decididas'])
            if d.get('sprt'):
                print(f"      SPRT: {d['pares_rodados']} pares "
                      f"({d['partidas']} partidas, {d['lotes']} lotes), "
                      f"{d['decididas']} discordantes, LLR {d['llr']:+.3f}")
                print(f"      -> {d['veredito']}   (Wilson do mesmo dado: {lim:.1%})")
                aprovou = d['promove']
            else:
                if d['decididas']:
                    print(f'      limite inferior do IC95 (Wilson): {lim:.1%} '
                          f'-- portao exige > {args.portao:.0%}')
                aprovou = ((wr is not None and wr >= args.portao)
                           if args.portao_media
                           else (d['decididas'] > 0 and lim > args.portao))
            if aprovou:
                shutil.copyfile(DESAFIANTE, CAMPEAO)
                registro |= {'resultado': f'PROMOVIDO ({wr:.1%} >= {args.portao:.0%})',
                             'promovido': True}
                print(f'[4/4] PROMOVIDO -- desafiante vira campeao.')
            else:
                registro |= {'resultado': f'descartado ({"n/d" if wr is None else f"{wr:.1%}"} < {args.portao:.0%})',
                             'promovido': False}
                print(f'[4/4] DESCARTADO -- campeao mantido. O corpus cresceu mesmo assim.')

        historico.append(registro)
        salvar_historico(historico)

    print(f'\n{"="*66}\nHISTORICO\n{"="*66}')
    mostrar_status()
    print(f'\nhistorico -> {HISTORICO}')
    print('\nLEMBRETE: o duelo mede FORCA. A metrica OFICIAL mede SEMELHANCA')
    print('COM O HUMANO. Antes de ligar o knob por default, rodar:')
    print('  OPTCG_K_VALUE_NET_WEIGHT=<peso> python decision_quality_full.py --all')
    print('e comparar contra o default -- forca que sobe as custas da')
    print('semelhanca e uma decisao do usuario, nao um detalhe tecnico.')


if __name__ == '__main__':
    main()
