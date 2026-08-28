"""
Gauntlet controlado: um deck fixo vs um roster fixo de arquétipos reais do
meta (decklists_raw.csv), com seeds fixas por matchup -- controla adversário
e sorte pra isolar "decisão ruim" de "matchup ruim/RNG".

Diferença pro `bot_efficiency_report.py` (que lê logs REAIS já jogados):
aqui o motor joga os dois lados via self-play (`OPTCGMatch`/`ReplayMatch`),
então dá pra escolher QUALQUER adversário do banco de decklists reais e
repetir a mesma seed pra cada um -- não depende de já existir log de
partida real contra aquele arquétipo específico.

Criado 04/08/2026 pra calibração do combo de reanimação do Imu (HANDOFF
bloco 432/433): a comparação direta de vitória/derrota real (1 vitória
histórica) não tinha amostra suficiente. O gauntlet (70 partidas, 7
adversários x 10 seeds) revelou um padrão MUITO mais forte e reprodutível:
Imu vence folgado contra os 2 decks mais representados no meta (Enel 60%,
Nami 70%) mas perde muito contra decks agressivos/counter-densos (Ace 10%,
Mihawk 10%, Lucy 20%). Investigação (replay verbose de Ace seed=0, ver
HANDOFF 433) mostrou DON ficando ocioso enquanto o Imu ataca "seco" e
apanha de Counter -- MAS o `ATTACK_MARGIN_DON_FRACTION` que rege essa
margem já tinha sido calibrado e cross-validado contra DON/ataque real
(bloco 398, 29/07) e o padrão observado aqui (DON/ataque menor nas derrotas
de Ace que na vitória) bate com o padrão já usado pra calibrar a constante
-- não é um bug novo, é o dial existente reagindo a um matchup
estruturalmente desfavorável (aggro/counter-denso vs controle/reanimação).
Não mexer em `ATTACK_MARGIN_DON_FRACTION`/`_don_reserve_for_defense` por
causa só deste gauntlet sem log real desses matchups pra cross-validar.

Uso:
    python gauntlet_matchup.py
    python gauntlet_matchup.py --workers 4   # paraleliza (achado 10/08)

Paralelismo: cada (adversario, seed) e uma partida independente -- roda em
processo separado via ProcessPoolExecutor, mesmo padrao ja validado em
audit_replay.py/blocos de calibracao anteriores. Cada worker reconstroi os
decks do zero a partir de decklists_raw.csv (evita depender de picklar
objetos Card entre processos) e aplica o MESMO monkeypatch de
`OPTCGMatch._execute_attack` localmente (o `captured`/`_fixed_side_marker`
do original era estado compartilhado via closure -- aqui vira retorno da
propria funcao, sem risco de contaminacao entre partidas).
"""
import argparse
import random
import sys
import contextlib
import io
import json
import os
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replay_optcg import ReplayMatch
from optcg_engine.decision_engine import build_real_deck, load_cards_db, validar_deck, OPTCGMatch
import pandas as pd

# Roster escolhido pelos arquétipos mais representados em decklists_raw.csv
# (meta real de torneio): Enel (70 decks), Nami (30), Ace (19), Mihawk (16),
# Lucy (16), Luffy-Amarelo (8), Rosinante (6), + espelho (outro build de Imu).
ROSTER_NAMES = {
    'Enel':      'Purple Enelby Mirko Zanelli',
    'Nami':      'Blue/Yellow Namiby AceOfSpades',
    'Ace':       'Red/Blue Aceby Tzuwy',
    'Mihawk':    'Green Mihawkby Phi Nguyen',
    'Lucy':      'Red/Blue Lucyby Magyo',
    'Luffy-Y':   'Yellow Luffyby David Melendo Villena',
    'Rosinante': 'Purple/Yellow Rosinanteby Matt',
}
FIXED_NAME = 'Black Imuby Spence Gibson'
FIXED_MIRROR_NAME = 'Black Imuby Adderall'
N_SEEDS = 30

# Painel de decks FIXOS pra testar uma mudanca de motor em varios
# arquetipos, nao so num (pedido do usuario, 15/08/2026): "jogar so de imu
# nao e ruim nao?". Estava certo -- o deck fixo era HARDCODED no Imu, que e
# CONTROLE. Uma mudanca que mexe em gasto de DON pra atacar (como a do
# bloco 551) pesa completamente diferente num deck AGRESSIVO, e um gauntlet
# so de Imu nunca mostraria uma regressao la. Cada entrada aqui e um
# arquetipo diferente do meta real (decklists_raw.csv), e o `--painel` roda
# o MESMO roster contra todos, reportando por deck E o agregado.
PAINEL = {
    'Imu':    ('Black Imuby Spence Gibson',        'controle'),
    'Ace':    ('Red/Blue Aceby Tzuwy',             'agressivo'),
    'Enel':   ('Purple Enelby Mirko Zanelli',      'ramp/controle'),
    'Nami':   ('Blue/Yellow Namiby AceOfSpades',   'tempo'),
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'metrics')


def _out_path(fixed_label: str) -> str:
    # bloco 721: corrida com pesos NAO-default grava em arquivo proprio.
    # Sem isto, um A/B de pesos sobrescrevia o resultado canonico (que e
    # versionado) com o da variante -- mesma armadilha ja corrigida em
    # `decision_quality_full.py` (blocos 683 e 696), por um 3o caminho.
    _var = os.environ.get('OPTCG_EVAL_WEIGHTS', '')
    if _var:
        _slug = os.path.splitext(os.path.basename(_var))[0][:40]
        return os.path.join(OUT_DIR, f'gauntlet_{fixed_label.lower()}_{_slug}.json')
    return os.path.join(OUT_DIR, f'gauntlet_{fixed_label.lower()}.json')


def _wilson_ci95(vitorias: int, n: int) -> tuple[float, float]:
    """
    Intervalo de confianca 95% (Wilson) do win rate, em pontos percentuais.

    Existe porque 30 seeds por matchup dao margem larga: sem isso e facil
    ler RUIDO como melhora/piora ao comparar duas rodadas do gauntlet
    (risco real -- a primeira rodada desta sessao deu 31,9% e foi descartada
    justamente por nao dar pra distinguir efeito de ruido). Wilson em vez da
    aproximacao normal por se comportar melhor com n pequeno e taxas
    proximas de 0/100%.
    """
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = vitorias / n
    denom = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / denom
    margem = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, (centro - margem) * 100), min(100.0, (centro + margem) * 100))


def _find_deck(target_name, cards_db, df_raw, urls):
    for url, name in urls.items():
        if name == target_name:
            result = build_real_deck(name, url, df_raw, cards_db)
            if not result:
                return None
            leader, cards, stage = result
            valido, erros = validar_deck(leader, cards, cards_db)
            if not valido:
                return None
            return (leader, cards, stage)
    return None


def _run_one_seed(task):
    """Roda 1 partida (adversario, seed) completa e devolve (label, linha).
    Independente de qualquer outra chamada -- pode rodar em processo
    separado sem coordenacao."""
    # `fixed_name` vem na TUPLA, nunca do global: no Windows o
    # ProcessPoolExecutor usa spawn, entao cada worker RE-IMPORTA este
    # modulo e enxergaria o FIXED_NAME default (Imu), ignorando o --deck
    # escolhido na linha de comando. Passar pela tarefa e o que faz o
    # painel multi-deck funcionar de verdade em paralelo.
    fixed_name, label, opp_name, seed = task
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()
    fixed_deck = _find_deck(fixed_name, cards_db, df_raw, urls)
    opp_deck = _find_deck(opp_name, cards_db, df_raw, urls)

    original_execute_attack = OPTCGMatch._execute_attack
    captured = []

    def patched_execute_attack(self, attacker, target_type, target, p, opp, engine, verbose=False, attached_don=0):
        if p is self._fixed_side_marker:
            captured.append(attacker.don_attached)
        return original_execute_attack(self, attacker, target_type, target, p, opp, engine, verbose=verbose, attached_don=attached_don)

    OPTCGMatch._execute_attack = patched_execute_attack
    try:
        random.seed(1000 + seed)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            match = ReplayMatch(fixed_deck, opp_deck, 'Fixo', label)
            match.setup()
            eng = match._get_engine_match()
            eng._fixed_side_marker = match.state_a
            vencedor = None
            turn_num = 0
            for turn_num in range(match.MAX_TURNS * 2):
                p = (match.state_a if match.state_a.is_first else match.state_b) \
                    if turn_num % 2 == 0 \
                    else (match.state_b if match.state_a.is_first else match.state_a)
                opp = match.state_b if p is match.state_a else match.state_a
                vencedor = eng.play_turn(p, opp, verbose=False)
                if vencedor:
                    break
    finally:
        OPTCGMatch._execute_attack = original_execute_attack

    fixo_won = (vencedor == 'A')
    n_ataques = len(captured)
    don_medio = sum(captured) / n_ataques if n_ataques else 0.0
    linha = {
        'seed': seed, 'fixo_won': fixo_won,
        'dmg_fixo': match.state_a.dmg_dealt, 'dmg_opp': match.state_b.dmg_dealt,
        'turnos': turn_num, 'ataques_fixo': n_ataques, 'don_medio': don_medio,
    }
    return label, linha


def _rodar_um_deck_fixo(fixed_label, fixed_name, cards_db, df_raw, urls,
                        workers, n_seeds):
    """Roda o roster inteiro contra UM deck fixo. Devolve (resultados, resumo)."""
    fixed_deck = _find_deck(fixed_name, cards_db, df_raw, urls)
    if not fixed_deck:
        print(f'AVISO: deck fixo {fixed_label} ({fixed_name}) nao encontrado -- pulando')
        return None, None

    roster_names = {}
    for label, name in ROSTER_NAMES.items():
        if name == fixed_name:
            continue          # nao se enfrenta como "adversario do roster"
        if _find_deck(name, cards_db, df_raw, urls):
            roster_names[label] = name
        else:
            print(f'AVISO: {label} ({name}) nao encontrado/invalido')
    if _find_deck(FIXED_MIRROR_NAME, cards_db, df_raw, urls) and fixed_name == FIXED_NAME:
        roster_names['Mirror'] = FIXED_MIRROR_NAME

    print(f'=== DECK FIXO: {fixed_label} ({fixed_name}) ===')
    print(f'Roster: {list(roster_names.keys())}')

    tasks = [(fixed_name, label, opp_name, seed)
             for label, opp_name in roster_names.items()
             for seed in range(n_seeds)]

    if workers <= 1:
        pares = [_run_one_seed(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            pares = list(ex.map(_run_one_seed, tasks))

    resultados: dict[str, list] = {}
    for label, linha in pares:
        resultados.setdefault(label, []).append(linha)
    for label in resultados:
        resultados[label].sort(key=lambda l: l['seed'])
    resultados = {label: resultados[label] for label in roster_names if label in resultados}

    print(f'{"Adversario":15} {"WinRate":>8} {"IC95%":>16} {"Dano":>7} {"DON/atk":>9} {"Atk/turno":>10}')
    agg_win, agg_dmg, agg_don, agg_atk = [], [], [], []
    for label, linhas in resultados.items():
        n = len(linhas)
        wins = sum(1 for l in linhas if l['fixo_won'])
        lo, hi = _wilson_ci95(wins, n)
        dmg_medio = sum(l['dmg_fixo'] for l in linhas) / n
        dons = [l['don_medio'] for l in linhas if l['ataques_fixo'] > 0]
        don_medio = sum(dons) / len(dons) if dons else 0.0
        atk_turno = sum(l['ataques_fixo'] / max(1, l['turnos']) for l in linhas) / n
        print(f'{label:15} {wins/n*100:7.1f}% {f"[{lo:.0f}-{hi:.0f}]":>16} '
              f'{dmg_medio:7.2f} {don_medio:9.2f} {atk_turno:10.2f}')
        agg_win.extend([1 if l['fixo_won'] else 0 for l in linhas])
        agg_dmg.extend([l['dmg_fixo'] for l in linhas])
        agg_don.extend(dons)
        agg_atk.extend([l['ataques_fixo'] / max(1, l['turnos']) for l in linhas])

    n_tot = len(agg_win)
    lo, hi = _wilson_ci95(sum(agg_win), n_tot)
    resumo = {
        'deck': fixed_label, 'partidas': n_tot,
        'win_rate': sum(agg_win) / n_tot * 100,
        'ic95': [lo, hi],
        'dano_medio': sum(agg_dmg) / n_tot,
        'don_por_ataque': sum(agg_don) / len(agg_don) if agg_don else 0.0,
        'ataques_por_turno': sum(agg_atk) / n_tot,
    }
    print(f'  -> {fixed_label}: {n_tot} partidas, win_rate={resumo["win_rate"]:.1f}% '
          f'(IC95 {lo:.0f}-{hi:.0f}), dano={resumo["dano_medio"]:.2f}, '
          f'DON/atk={resumo["don_por_ataque"]:.2f}')
    print()

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_out_path(fixed_label), 'w') as f:
        json.dump(resultados, f, indent=2)
    return resultados, resumo


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workers', type=int, default=1,
                    help='processos paralelos (1=sequencial, comportamento de sempre)')
    ap.add_argument('--deck', choices=sorted(PAINEL), default=None,
                    help='testar UM arquetipo so (sem isto roda o PAINEL inteiro, '
                         'que e o default desde o bloco 724)')
    ap.add_argument('--painel', action='store_true',
                    help='(obsoleto -- o painel virou o DEFAULT no bloco 724; '
                         'a flag continua aceita e nao faz diferenca)')
    ap.add_argument('--seeds', type=int, default=N_SEEDS,
                    help=f'partidas por matchup (default {N_SEEDS}); menos = mais rapido, IC mais largo')
    args = ap.parse_args()

    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    # bloco 724: o PAINEL passa a ser o DEFAULT. Antes, rodar sem flag
    # testava SO o Imu -- e o usuario ja tinha reclamado disso em
    # 15/08/2026 ("jogar so de imu nao e ruim nao?"), motivo pelo qual o
    # painel foi criado. O painel existia, mas atras de uma flag: quem
    # rodasse pelo caminho natural continuava medindo um lider so, e foi
    # exatamente o que aconteceu de novo em 28/08 (bloco 723).
    #
    # Objetivo central do projeto: o bot tem que jogar bem com QUALQUER
    # deck. Uma ferramenta cujo default mede UM arquetipo empurra a sessao
    # pro vicio que o projeto proibe. **O comportamento seguro tem que ser
    # o default; o recorte estreito e que deve exigir flag.**
    if args.deck:
        escolhidos = [(args.deck, PAINEL[args.deck])]
    else:
        escolhidos = list(PAINEL.items())

    resumos = []
    for fixed_label, (fixed_name, arquetipo) in escolhidos:
        print(f'[{arquetipo}]')
        _res, resumo = _rodar_um_deck_fixo(fixed_label, fixed_name, cards_db,
                                           df_raw, urls, args.workers, args.seeds)
        if resumo:
            resumo['arquetipo'] = arquetipo
            resumos.append(resumo)

    if len(resumos) > 1:
        print('=' * 72)
        print('RESUMO DO PAINEL (compare estes numeros entre duas rodadas do motor)')
        print(f'{"Deck":10} {"Arquetipo":16} {"WinRate":>8} {"IC95%":>14} {"Dano":>7} {"DON/atk":>9}')
        for r in resumos:
            ic = f'[{r["ic95"][0]:.0f}-{r["ic95"][1]:.0f}]'
            print(f'{r["deck"]:10} {r["arquetipo"]:16} {r["win_rate"]:7.1f}% {ic:>14} '
                  f'{r["dano_medio"]:7.2f} {r["don_por_ataque"]:9.2f}')
        print()
        print('LEITURA: so trate como efeito REAL a diferenca que sai do IC95 da')
        print('outra rodada. Sobreposicao de intervalo = ruido, nao melhora.')
        with open(os.path.join(OUT_DIR, 'gauntlet_painel.json'), 'w') as f:
            json.dump(resumos, f, indent=2)


if __name__ == '__main__':
    main()
