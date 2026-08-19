"""
decision_quality_vs_human.py -- compara o motor de HOJE contra o que
HUMANOS de verdade fizeram, turno a turno, em TODOS os logs bot-vs-humano
do banco (`logs/index.json`, campo `bot_side` preenchido).

Criado 17/08/2026 a pedido do usuário, formalizando um script de
scratchpad usado ao longo da sessão pra medir 3 tentativas sucessivas de
mudar `_generate_attach_don_actions`/o Turn Planner (2 revertidas por
regredirem este número, 1 aceita por manter/melhorar) -- ver HANDOFF
blocos 592-595. Fica como ferramenta permanente pra qualquer sessão
futura repetir essa validação sem reescrever o script do zero.

MÉTRICA (objetiva, não interpretação): pra cada turno de cada humano no
banco, reconstrói o estado exato do jogo (mão/campo/DON/vida dos dois
lados) a partir do snapshot REAL do log, joga esse turno por inteiro com
`OPTCGMatch.play_turn()` de verdade (via `audit_real_losses.audit_one_game`
-- fonte única, não reimplementa nada da decisão) e compara:

    dano_humano_real = vida_do_oponente_ANTES - vida_do_oponente_DEPOIS
                        (dos dois snapshots do próprio log, fato histórico)
    dano_motor_hoje  = vida_do_oponente_ANTES - menor_vida_atingida_na_
                        narrativa_da_simulação (`engine_hoje_narrativa`,
                        parseando "vida do oponente: N"; "VITORIA" conta
                        como 0)

Reporta em quantos turnos `dano_motor_hoje >= dano_humano_real` -- "o
motor causaria dano igual ou maior que o humano causou de verdade nesse
turno". Dano é um número, não julgamento qualitativo: dá pra automatizar
com confiança em vez de ler cada narrativa na mão (rodado uma vez, 111
turnos, blocos 592-595).

LIMITAÇÕES HONESTAS (herdadas de `audit_one_game`, ver o docstring dele
antes de confiar cegamente num resultado):
- Mede só o TURNO ISOLADO -- um turno que causa pouco dano mas prepara
  uma vantagem melhor no turno seguinte (desenvolvimento de mesa,
  economia de DON, remoção de ameaça) aparece como "pior" mesmo sendo a
  jogada certa. NÃO mede valor multi-turno.
- Só mede OFENSIVA (dano causado) -- não avalia nenhuma decisão de
  DEFESA (bloquear, usar counter). Ver `audit_defense`-style scripts
  (scratchpad desta sessão, ainda não formalizado) se precisar disso.
- `don_available` é reconstrução best-effort (ver limitações de
  `audit_real_losses.py`) -- pode divergir do valor real em jogos
  longos ou com efeitos que dão/tiram DON de formas não capturadas.
- Mão do oponente tratada com informação COMPLETA (mesmo padrão do
  self-play/gauntlet hoje) -- o motor aqui enxerga mais do oponente do
  que o bot real ao vivo enxergaria, resultado tende a ficar "melhor"
  que o bot real conseguiria nessa exata situação, nunca pior.
- Primeiro turno de cada jogador é pulado (sem snapshot "antes").

Uso:
    python decision_quality_vs_human.py --all [--workers N]
    python decision_quality_vs_human.py --log <caminho_do_parsed.json>
    python decision_quality_vs_human.py --leader OP17-039 [--workers N]
    python decision_quality_vs_human.py --all --pior N   # mostra os N piores turnos
"""
import argparse
import concurrent.futures
import json
import os
import re

import pandas as pd

from audit_real_losses import audit_one_game
from optcg_engine.decision_engine import load_cards_db

LOGS_DIR = 'logs'
INDEX_PATH = os.path.join(LOGS_DIR, 'index.json')
OUT_DIR = os.path.join('metrics', 'decision_quality_vs_human')

LIFE_RE = re.compile(r'vida do oponente: (\d+)')
VICTORY_RE = re.compile(r'VITORIA')


def find_bot_vs_human_logs(leader_filter: str | None = None):
    """[(parsed_file, human_side_label, human_leader_code, game_id)] pra
    TODOS os logs com `bot_side` preenchido (qualquer resultado, não só
    derrota do bot -- diferente de `audit_real_losses.find_real_bot_
    losses`, que é só derrotas). `human_side_label` é o rótulo usado no
    log ('You'/'Opponent'), já invertido do `bot_side` do índice."""
    idx = json.load(open(INDEX_PATH, encoding='utf-8'))
    jobs = []
    for e in idx:
        bs = e.get('bot_side')
        if not bs:
            continue
        human_key = 'p2' if bs == 'p1' else 'p1'
        human_side_label = 'Opponent' if bs == 'p1' else 'You'
        human_leader = e[human_key]['leader_code']
        if leader_filter and human_leader != leader_filter:
            continue
        jobs.append((e['parsed_file'], human_side_label, human_leader, e['id']))
    return jobs


def find_all_human_logs(leader_filter: str | None = None):
    """[(parsed_file, human_side_label, human_leader_code, game_id)] pra
    TODO o banco (150 logs), não só os 26 com `bot_side` preenchido.

    Achado real 18/08/2026 (bloco 617, pedido do usuário "por que só 26
    se temos 150 no banco?"): `find_bot_vs_human_logs` só inclui logs
    onde o índice sabe QUAL lado é o bot -- mas `_offense_verdict`/
    `_defense_verdict` (via `audit_one_game`) nunca usam essa
    informação pra nada além de escolher QUAL lado auditar; a
    comparação em si é "reconstrua o estado real deste turno e pergunte
    pro motor de hoje o que ele faria" -- funciona igual pra QUALQUER
    jogador humano, bot do outro lado ou não. Os outros 124 logs do
    banco são humano-vs-humano de verdade (confirmado: nomes reais tipo
    "Karlmalone#2854", não "You"/"Opponent") -- `turn['player']` usa o
    nome real do jogador, e o resto do pipeline (`_offense_verdict`
    etc.) já compara por igualdade de string, sem hardcode de "You"/
    "Opponent" em nenhum lugar crítico -- funciona sem mudança.

    Pra logs SEM `bot_side` (humano vs humano), audita OS DOIS lados
    (dobra a amostra pra esses 124 -- os dois são decisões humanas reais
    igualmente válidas). Pra logs COM `bot_side`, mantém o comportamento
    de `find_bot_vs_human_logs` (só o lado humano, não o bot) -- não
    faz sentido comparar o motor de hoje contra o BOT histórico como se
    fosse "humano".
    """
    idx = json.load(open(INDEX_PATH, encoding='utf-8'))
    jobs = []
    for e in idx:
        bs = e.get('bot_side')
        p1 = e.get('p1', {})
        p2 = e.get('p2', {})
        if not p1.get('leader_code') or not p2.get('leader_code'):
            continue
        # Achado real 18/08: 30 entradas antigas do indice nao tem
        # campo `id` (schema mais antigo, so `parsed_file`/`p1`/`p2`/
        # `winner`) -- nenhuma delas tem `bot_side` (confirmado), entao
        # o codigo antigo (`find_bot_vs_human_logs`) nunca batia nelas
        # e nunca precisou de fallback. Aqui, que tambem processa as
        # sem-bot_side, precisa de um id generico pra essas.
        game_id = e.get('id') or e.get('parsed_file', 'unknown')
        if bs:
            human_key = 'p2' if bs == 'p1' else 'p1'
            human_side_label = p2.get('name') if bs == 'p1' else p1.get('name')
            human_leader = e[human_key]['leader_code']
            if leader_filter and human_leader != leader_filter:
                continue
            jobs.append((e['parsed_file'], human_side_label, human_leader, game_id))
        else:
            for side_key, other_key in (('p1', 'p2'), ('p2', 'p1')):
                side = e.get(side_key, {})
                human_leader = side.get('leader_code')
                human_side_label = side.get('name')
                if not human_leader or not human_side_label:
                    continue
                if leader_filter and human_leader != leader_filter:
                    continue
                jobs.append((e['parsed_file'], human_side_label, human_leader,
                             f"{game_id}_{side_key}"))
    return jobs


def _turn_verdict(parsed_path, human_side_label, cards_db, df_raw, urls):
    """Roda audit_one_game pro lado do HUMANO e devolve o veredito de dano
    por turno -- reusa engine_hoje_narrativa já gerada, não duplica nada."""
    raw = json.load(open(parsed_path, encoding='utf-8'))
    turns_raw = raw['turns']
    report = audit_one_game(parsed_path, human_side_label, cards_db, df_raw, urls)
    if report.get('error'):
        return {'error': report['error'], 'file': os.path.basename(parsed_path)}

    bot_side = report['bot_side']  # == human_side_label aqui (nome herdado de audit_one_game)
    opp_side = 'Opponent' if bot_side == 'You' else 'You'

    rows = []
    for t in report.get('turnos', []):
        if 'error' in t:
            continue
        turn_num = t['turn']
        idx_i = next((i for i, tr in enumerate(turns_raw)
                      if tr['turn'] == turn_num and tr['player'] == bot_side), None)
        if idx_i is None or idx_i == 0:
            continue
        before_snap = turns_raw[idx_i - 1]['snapshot']
        after_snap = turns_raw[idx_i]['snapshot']
        if opp_side not in before_snap or opp_side not in after_snap:
            continue
        before_life = before_snap[opp_side].get('life')
        after_life_real = after_snap[opp_side].get('life')
        if before_life is None or after_life_real is None:
            continue
        human_damage = before_life - after_life_real

        narrativa = t.get('engine_hoje_narrativa', '')
        life_matches = [int(m) for m in LIFE_RE.findall(narrativa)]
        engine_final_life = life_matches[-1] if life_matches else before_life
        engine_won = bool(VICTORY_RE.search(narrativa))
        if engine_won:
            engine_final_life = 0
        engine_damage = before_life - engine_final_life

        rows.append({
            'turn': turn_num, 'before_life': before_life,
            'human_damage': human_damage, 'engine_damage': engine_damage,
            'engine_won_this_turn': engine_won,
        })
    return {'file': os.path.basename(parsed_path), 'turnos': rows}


def _run_one(task):
    parsed_path, human_side_label, human_leader, game_id = task
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()
    result = _turn_verdict(os.path.join(LOGS_DIR, parsed_path), human_side_label,
                           cards_db, df_raw, urls)
    result['game_id'] = game_id
    result['human_leader'] = human_leader
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--log', help='caminho de um parsed json especifico (relativo a logs/)')
    ap.add_argument('--all', action='store_true', help='roda em TODOS os logs bot-vs-humano do banco')
    ap.add_argument('--leader', help='filtra por codigo do lider HUMANO (ex: OP17-039)')
    ap.add_argument('--workers', type=int, default=1,
                     help='processos paralelos (1=sequencial) -- partidas sao independentes')
    ap.add_argument('--pior', type=int, default=15, help='quantos dos piores turnos listar')
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.log:
        idx = json.load(open(INDEX_PATH, encoding='utf-8'))
        entry = next((e for e in idx if e.get('parsed_file') == args.log
                      or e.get('id') == args.log), None)
        if not entry or not entry.get('bot_side'):
            raise SystemExit(f'log nao encontrado ou sem bot_side: {args.log}')
        bs = entry['bot_side']
        human_key = 'p2' if bs == 'p1' else 'p1'
        jobs = [(entry['parsed_file'], 'Opponent' if bs == 'p1' else 'You',
                 entry[human_key]['leader_code'], entry['id'])]
    else:
        jobs = find_bot_vs_human_logs(args.leader)
        if not jobs:
            raise SystemExit('nenhum log bot-vs-humano encontrado (confira --leader)')

    print(f'{len(jobs)} log(s) a auditar...')
    if args.workers <= 1:
        resultados = [_run_one(t) for t in jobs]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            resultados = list(ex.map(_run_one, jobs))

    erros = [r for r in resultados if 'error' in r]
    for e in erros:
        print(f'  ERRO em {e["file"]}: {e["error"]}')

    all_rows = []
    for r in resultados:
        if 'error' in r:
            continue
        for row in r.get('turnos', []):
            row = dict(row)
            row['game'] = r['file']
            row['human_leader'] = r['human_leader']
            all_rows.append(row)

    n = len(all_rows)
    print(f'\n{"="*70}')
    print(f'DECISION QUALITY vs HUMANO -- {len(jobs) - len(erros)} partida(s), {n} turno(s)')
    print(f'{"="*70}')
    if n == 0:
        print('(sem turnos auditaveis)')
        return

    melhor_ou_igual = sum(1 for r in all_rows if r['engine_damage'] >= r['human_damage'])
    pior = n - melhor_ou_igual
    print(f'Motor causa dano >= ao que o humano causou de verdade: '
          f'{melhor_ou_igual}/{n} ({melhor_ou_igual/n*100:.1f}%)')
    print(f'Motor causa MENOS dano que o humano causou de verdade: '
          f'{pior}/{n} ({pior/n*100:.1f}%)')

    engine_vitorias = sum(1 for r in all_rows if r['engine_won_this_turn'])
    human_vitorias = sum(1 for r in all_rows if r['before_life'] - r['human_damage'] <= 0)
    print(f'\nMotor fecha a partida NO PROPRIO TURNO: {engine_vitorias}/{n}')
    print(f'Humano fechou a partida NO PROPRIO TURNO (historico real): {human_vitorias}/{n}')

    mais = sum(1 for r in all_rows if r['engine_damage'] > r['human_damage'])
    empate = sum(1 for r in all_rows if r['engine_damage'] == r['human_damage'])
    print(f'\nDistribuicao: empate={empate} ({empate/n*100:.1f}%)  '
          f'motor causa MAIS={mais} ({mais/n*100:.1f}%)  '
          f'motor causa MENOS={pior} ({pior/n*100:.1f}%)')

    piores = sorted([r for r in all_rows if r['engine_damage'] < r['human_damage']],
                    key=lambda r: r['engine_damage'] - r['human_damage'])
    if piores:
        print(f'\n--- Piores casos (maior diferenca primeiro, ate {args.pior}) ---')
        for r in piores[:args.pior]:
            print(f"  {r['game']} T{r['turn']} (lider humano {r['human_leader']}): "
                  f"humano causou {r['human_damage']}, motor causaria {r['engine_damage']} "
                  f"(vida antes={r['before_life']})")

    out_path = os.path.join(OUT_DIR, 'ultimo_resultado.json')
    json.dump({'n_turnos': n, 'melhor_ou_igual': melhor_ou_igual, 'pior': pior,
               'rows': all_rows}, open(out_path, 'w', encoding='utf-8'),
              indent=2, ensure_ascii=False)
    print(f'\nResultado completo salvo em {out_path}')


if __name__ == '__main__':
    main()
