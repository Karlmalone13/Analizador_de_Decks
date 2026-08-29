"""DIAGNOSTICO: por que 22,9% dos alvos de DON do humano NUNCA viraram opcao?

Vem do oraculo estendido (`oraculo_teto.py`, 29/08): na categoria
`attach_don`, o motor chega a 45,1% de acerto por jogada, o teto de
ordenacao e 71,3% e o de geracao e 77,1% -- ou seja, **22,9% dos alvos
que o humano escolheu nunca existiram como acao legal**. Nenhum peso,
knob ou busca alcanca esses: a opcao nao perde a votacao, ela nao chega
a existir.

MECANISMO (lido em `_generate_attach_don_actions`, decision_engine.py):
nao existe uma acao generica "anexar DON neste personagem". O motor so
GERA a opcao por uma lista fechada de motivos:
  1) destravar keyword `[DON!! xN]`;
  2) destravar gatilho `[DON!! xN]`;
  3) cruzar o poder de um combate DESTE turno (exige
     `can_attack_this_turn` e `character_can_attack_now`; o ramo de
     reforco com gap<=0 ainda exige DON ocioso e e limitado a
     `min(don_sobra, 2)`).
As tres nasceram de casos reais tapados um a um (blocos 567, 610 +
achados de 23/07, 02/08, 17/08) -- e enumeracao, nao regra geral.

ESTE SCRIPT NAO PROPOE FIX. Ele so mede QUAL caso domina, porque a
diferenca muda o conserto por completo:
  - se dominar "estava na mao", o problema e de `play` (o motor nao
    jogou a carta), nao de geracao de DON;
  - se dominar "no campo e podia atacar", a categoria 3 existia e algum
    GATE a cortou -- e conserto de gate, cirurgico;
  - se dominar "no campo mas nao podia atacar", falta a regra geral que
    o motor nao tem (DON em corpo que ataca no PROXIMO turno);
  - se dominar "ausente das acoes", e divergencia de ESTADO (o motor nao
    tinha aquela carta em campo) -- fidelidade de reconstrucao, nao
    decisao.

COMO CLASSIFICA (so com dado que ja existe no `decision_log`, sem
instrumentacao nova): a presenca do codigo do alvo nas acoes geradas
naquele turno diz onde a carta estava do ponto de vista do motor --
`play` => estava na MAO; `attack` => estava em campo e podia atacar;
`activate` => estava em campo. Ausente de tudo => provavelmente nem
estava em campo.

LIMITE HONESTO: e inferencia por presenca, nao leitura direta do campo
(o board concreto do `context` grava so PROPRIEDADES, nunca o codigo --
exigencia de "qualquer deck", bloco 719). Uma carta em campo, restada e
sem efeito ativavel nao gera acao nenhuma e cai em "ausente" junto com a
que nao estava la. Por isso "ausente" e um balde MISTO e esta rotulado
como tal -- nao ler como "erro de reconstrucao" sem confirmar caso a
caso.

Uso:
    python diag_don_nunca_gerada.py --workers 4 [--limit N]
"""
import argparse
import concurrent.futures
import json
import os
import sys
from collections import Counter, defaultdict

import pandas as pd

sys.path.insert(0, '.')
from audit_real_losses import audit_one_game, load_cards_db
from decision_quality_vs_human import find_all_human_logs

CASOS = ('lider', 'estava_na_mao', 'campo_podia_atacar',
         'campo_outra_acao', 'ausente_das_acoes')


def _processa(tarefa):
    pf, human, _lider = tarefa
    cards_db = _processa.cards_db
    casos = Counter()
    motivos = Counter()
    motivo_por_caso = defaultdict(Counter)
    por_qtd = Counter()
    por_caso_qtd = defaultdict(Counter)
    codigos = Counter()
    gerou_algum = Counter()
    total_alvos = 0
    path = os.path.join('logs', pf)
    try:
        raw = json.load(open(path, encoding='utf-8'))
        rep = audit_one_game(path, human, cards_db, _processa.df_raw,
                             _processa.urls, capture_actions=True,
                             capture_candidates=True)
    except Exception:
        return casos, por_qtd, por_caso_qtd, codigos, gerou_algum, motivos, motivo_por_caso, 0
    if rep.get('error'):
        return casos, por_qtd, por_caso_qtd, codigos, gerou_algum, motivos, motivo_por_caso, 0

    meta = (raw.get('meta') or {}).get('players') or {}
    if 'p1' not in meta or 'p2' not in meta:
        return casos, por_qtd, por_caso_qtd, codigos, gerou_algum, motivos, motivo_por_caso, 0
    bot_leader = meta['p1' if meta['p1']['name'] == human
                      else 'p2']['leader'].get('code')
    rb = {(t['turn'], t['player']): t for t in raw['turns']}

    for t in rep.get('turnos', []):
        decisions = t.get('decisions') or []
        if not decisions:
            continue
        raw_t = rb.get((t['turn'], human))
        if not raw_t:
            continue

        # alvos de DON do humano naquele turno, com a QUANTIDADE anexada
        alvos = {}
        for a in (raw_t.get('actions') or []):
            if a.get('type') == 'attach_don' and a.get('to'):
                alvos[a['to']] = alvos.get(a['to'], 0) + int(a.get('amount') or 1)
        if not alvos:
            continue

        # tudo que o motor gerou naquele turno, por kind
        gerado = defaultdict(set)
        for r in decisions:
            for act in (r.get('all_actions') or []):
                if act.get('code'):
                    gerado[act.get('kind')].add(act['code'])
        for rec in t.get('attach_don_for_attack_events', []):
            if rec.get('card'):
                gerado['attach_don'].add(rec['card'])

        # motivos de recusa registrados pelo motor NAQUELE turno
        # (OPTCG_DEBUG_AD=1), indexados pelo codigo da carta
        motivos_por_codigo = defaultdict(list)
        for cod, motivo in (t.get('ad_debug') or []):
            motivos_por_codigo[cod].append(motivo)

        for alvo, qtd in alvos.items():
            total_alvos += 1
            if alvo in gerado['attach_don']:
                continue                     # virou opcao -- fora deste diag
            if alvo == bot_leader:
                caso = 'lider'
            elif alvo in gerado['play']:
                caso = 'estava_na_mao'
            elif alvo in gerado['attack']:
                caso = 'campo_podia_atacar'
            elif alvo in gerado['activate']:
                caso = 'campo_outra_acao'
            else:
                caso = 'ausente_das_acoes'
            casos[caso] += 1
            for m in set(motivos_por_codigo.get(alvo) or ['<sem_motivo_registrado>']):
                motivos[m] += 1
                motivo_por_caso[caso][m] += 1
            por_qtd[min(qtd, 4)] += 1
            por_caso_qtd[caso][min(qtd, 4)] += 1
            codigos[alvo] += 1
            gerou_algum['sim' if gerado['attach_don'] else 'nao'] += 1
    return casos, por_qtd, por_caso_qtd, codigos, gerou_algum, motivos, motivo_por_caso, total_alvos


def _init(cards_db, df_raw, urls):
    _processa.cards_db = cards_db
    _processa.df_raw = df_raw
    _processa.urls = urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--out', default='metrics/diag_don_nunca_gerada.json')
    args = ap.parse_args()

    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()
    tarefas = [(pf, h, l) for pf, h, l, _g in find_all_human_logs()]
    if args.limit:
        tarefas = tarefas[:args.limit]
    print(f'{len(tarefas)} logs | workers={args.workers}\n')

    casos, por_qtd, codigos, gerou = Counter(), Counter(), Counter(), Counter()
    por_caso_qtd = defaultdict(Counter)
    motivos_tot = Counter()
    motivo_por_caso_tot = defaultdict(Counter)
    total = 0
    if args.workers > 1:
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=args.workers, initializer=_init,
                initargs=(cards_db, df_raw, urls)) as ex:
            resultados = ex.map(_processa, tarefas)
            for c, q, cq, cod, g, mt, mpc, tt in resultados:
                casos += c
                por_qtd += q
                codigos += cod
                gerou += g
                total += tt
                motivos_tot += mt
                for k, v in cq.items():
                    por_caso_qtd[k] += v
                for k, v in mpc.items():
                    motivo_por_caso_tot[k] += v
    else:
        _init(cards_db, df_raw, urls)
        for tarefa in tarefas:
            c, q, cq, cod, g, mt, mpc, tt = _processa(tarefa)
            casos += c
            por_qtd += q
            codigos += cod
            gerou += g
            total += tt
            motivos_tot += mt
            for k, v in cq.items():
                por_caso_qtd[k] += v
            for k, v in mpc.items():
                motivo_por_caso_tot[k] += v

    faltantes = sum(casos.values())
    print(f'alvos de DON do humano no corpus: {total}')
    print(f'  destes, NUNCA viraram acao legal: {faltantes} '
          f'({100*faltantes/total:.1f}%)\n')

    print('== onde a carta estava, do ponto de vista do MOTOR ==')
    print(f'  {"caso":22}{"n":>7}{"% dos faltantes":>18}')
    for caso in CASOS:
        n = casos[caso]
        if n:
            print(f'  {caso:22}{n:7}{100*n/faltantes:17.1f}%')

    print('\n== quanto DON o humano anexou nesses casos ==')
    print(f'  {"DON":>5}{"n":>8}{"%":>8}')
    for q in sorted(por_qtd):
        rot = f'{q}+' if q == 4 else str(q)
        print(f'  {rot:>5}{por_qtd[q]:8}{100*por_qtd[q]/faltantes:7.1f}%')

    print('\n== DON anexado, por caso (linha = caso, coluna = qtd) ==')
    print(f'  {"caso":22}' + ''.join(f'{("4+" if q==4 else q):>7}'
                                     for q in sorted(por_qtd)))
    for caso in CASOS:
        if not casos[caso]:
            continue
        print(f'  {caso:22}' + ''.join(f'{por_caso_qtd[caso][q]:7}'
                                       for q in sorted(por_qtd)))

    print('\n== o motor gerou ALGUM attach_don naquele turno? ==')
    for k, v in gerou.most_common():
        print(f'  {k}: {v} ({100*v/faltantes:.1f}%)')

    print('\n== MOTIVO da recusa, direto do motor (OPTCG_DEBUG_AD=1) ==')
    if not motivos_tot:
        print('  (nenhum motivo registrado -- rodou sem OPTCG_DEBUG_AD=1?)')
    for m, n in motivos_tot.most_common():
        print(f'  {m:34}{n:6}{100*n/faltantes:7.1f}%')

    print('\n== motivo x caso (os 2 casos que mais importam) ==')
    for caso in ('campo_podia_atacar', 'ausente_das_acoes'):
        if not casos[caso]:
            continue
        print(f'\n  -- {caso} (n={casos[caso]}) --')
        for m, n in motivo_por_caso_tot[caso].most_common(8):
            print(f'    {m:34}{n:6}{100*n/casos[caso]:7.1f}%')

    print('\n== 15 alvos mais frequentes ==')
    for cod, n in codigos.most_common(15):
        nome = cards_db.get(cod, {}).get('name', '')[:28]
        print(f'  {cod:12} {n:4}x  {nome}')

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump({'total_alvos': total, 'faltantes': faltantes,
                   'casos': dict(casos), 'por_qtd': {str(k): v for k, v in por_qtd.items()},
                   'por_caso_qtd': {k: {str(a): b for a, b in v.items()}
                                    for k, v in por_caso_qtd.items()},
                   'codigos': dict(codigos.most_common(50)),
                   'gerou_algum': dict(gerou),
                   'motivos': dict(motivos_tot),
                   'motivo_por_caso': {k: dict(v) for k, v in motivo_por_caso_tot.items()}}, fh, indent=1)
    print(f'\nsalvo em {args.out}')


if __name__ == '__main__':
    main()
