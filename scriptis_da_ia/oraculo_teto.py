"""ORACULO: qual o TETO que a arquitetura atual consegue expressar?

Pergunta que decide o rumo do projeto (bloco 697): "da pra chegar a 85%
ajustando configuracao, ou o gap e estrutural?".

Mede TRES niveis na mesma decisao, diretamente comparaveis entre si:

  1. REAL          -- o que o motor de fato escolheu.
  2. ORACULO-BUSCA -- se escolhesse PERFEITAMENTE dentro do shortlist que
                      ele mesmo montou (`candidates`).
                      Teto do que ajustar a FUNCAO DE VALOR alcanca.
  3. ORACULO-GERACAO -- se escolhesse perfeitamente dentro de TUDO que
                      gerou como acao legal (`all_actions`), ou seja, se
                      o corte do shortlist tambem fosse perfeito.
                      Teto do que ajustar QUALQUER peso alcanca.

O que sobra acima de (3) e o que a arquitetura NAO consegue expressar de
jeito nenhum: a opcao nunca virou acao legal. Nenhum tuning alcanca isso.

-- DUAS CORRECOES DESTA VERSAO (29/08, blocos 728/729) ----------------

**(a) A REGUA ESTAVA VENCIDA.** A versao original (bloco 697, 27/08) foi
escrita quando a metrica oficial era CONJUNTO EXATO por turno -- ela
contava `hum == motor` e `hum <= candidatas`, e reportou "real 28,9% ->
busca 80,3% -> geracao 97,4%". No dia seguinte o bloco 728 trocou a
regua oficial pra **ACERTO POR JOGADA** (`soma|H inter X| / soma|H|`, o
mesmo denominador de `decision_quality_full.py`), e o oraculo nunca foi
re-medido. Os tetos de 80,3%/97,4% sao numeros de uma regua que nao vale
mais. Aqui as duas saem lado a lado: a oficial e a de conjunto (esta so
pra comparar com o bloco 697).

**(b) MEDIA SO `play` -- 8% das decisoes.** O bloco 729 mediu que a meta
cobre **14.973 decisoes**, e `play` e 1.214 delas. As categorias que
carregam o buraco (DON 23,5%, alvo-de-efeito 16,4%, counter 18,5%)
**nunca tiveram teto medido** -- estavamos perseguindo 85% com o teto
conhecido de outra categoria. Aqui entram as que os dados do
`decision_log` sustentam:

    play | activate | attach_don | attack-QUEM | attack-ALVO

Cobertura: 6.180 das 14.973 decisoes (41,3%).

**O QUE ESTA VERSAO NAO MEDE, e por que** (declarado, nao omitido):
- **quais cartas de counter** (n=804): e decisao de DEFESA, resolvida por
  `pick_counters()` fora do Turn Planner -- nao passa por
  `candidates`/`all_actions`. Exige outro laco (o de `_defense_verdict`),
  nao um campo novo.
- **alvo dentro do efeito** (n=590, a PIOR categoria): o alvo e escolhido
  durante a RESOLUCAO do efeito, nao na geracao da acao -- nao existe
  lista de alvos candidatos em lugar nenhum do log. E o board concreto do
  `context` (bloco 719) grava **so propriedades, nunca o codigo** (por
  exigencia de "qualquer deck"), entao nem por disponibilidade da pra
  cruzar. **Medir o teto desta categoria exige instrumentacao nova.**

-- LIMITES HONESTOS DO METODO ----------------------------------------

1. **Sao tetos OTIMISTAS.** Os niveis 2 e 3 perguntam se a opcao do
   humano ESTAVA DISPONIVEL, nao se o motor teria DON e sequencia pra
   executar todas juntas. O alcancavel real e menor. O vies e a favor de
   "da pra chegar la" -- entao um numero BAIXO aqui e conclusao solida,
   um numero ALTO e so "o alvo existe".
2. **O oraculo tem retrovisor**: ele conhece a resposta do humano. A
   distancia real->busca e o TAMANHO DO ALVO, nunca ganho prometido.
3. `M` (o que o motor fez) e unido a `C` e `A` por construcao: o que o
   motor executou estava, por definicao, disponivel. Sem isso a
   monotonicidade real <= busca <= geracao podia quebrar por buraco de
   log (ex: top-up automatico de DON, que e um `kind` proprio fora do
   `turn_planner`). O script CONFERE essa monotonicidade e avisa.

-- VALIDACAO EMBUTIDA ------------------------------------------------

A linha REAL tem que reproduzir a tabela oficial do bloco 729
(play 43,5% | activate 63,9% | attach_don 23,5% | attack-quem 71,6% |
attack-alvo 69,3%). O script confere sozinho e imprime PASSA/FALHA: se a
extracao divergir da regua oficial, os tetos nao sao comparaveis e o
resultado nao vale. Nao interpretar nenhum numero com a validacao em
FALHA.

Uso:
    python oraculo_teto.py --workers 4
    python oraculo_teto.py --workers 4 --limit 20    # amostra rapida
"""
import argparse
import concurrent.futures
import json
import os
import sys
from collections import defaultdict

import pandas as pd

sys.path.insert(0, '.')
from audit_real_losses import audit_one_game, hist_action_kind, load_cards_db
# REUSO, nao reimplementacao (REGRA_SEM_DUPLICACAO.md): a conversao de
# alvo historico -> (tipo, codigo) e a classificacao play/activate sao as
# MESMAS de `decision_quality_full.py`. Se divergirem, a linha REAL para
# de reproduzir a tabela oficial e a validacao embutida acusa.
from decision_quality_full import _hist_target_type_code
from decision_quality_vs_human import find_all_human_logs

CATEGORIAS = ('play', 'activate', 'attach_don', 'attack-quem', 'attack-alvo')

# Tabela oficial do bloco 729 -- a linha REAL tem que bater com isto.
#
# ACHADO 29/08, ao construir esta validacao: **a tabela do bloco 729
# MISTURA DUAS REGUAS.** Conferido campo a campo contra
# `metrics/decision_quality_full/ultimo_resultado.json`:
#
#   play        43,5% = 528/1214  -> denominador |H|      (por jogada)
#   activate    63,9% = 280/438   -> denominador |H|      (por jogada)
#   attack-quem 71,6% = 1449/2024 -> denominador |H u M|  (SOBREPOSICAO)
#   attach_don  23,5% = 248/1055  -> denominador |H u M|  (SOBREPOSICAO)
#
# Sao perguntas DIFERENTES: |H| pergunta "das jogadas do humano, quantas
# o motor tambem fez?"; |H u M| pune tambem o que o motor fez A MAIS.
# Somar as quatro num agregado unico ("49,3% em 14.973 decisoes") mistura
# as duas -- e as categorias medidas por sobreposicao parecem PIORES do
# que na regua oficial declarada no bloco 728. Por isso a validacao aqui
# confere cada categoria contra a regua que a tabela de fato usou, e o
# relatorio imprime as DUAS pra toda categoria.
REGUA_OFICIAL = {'play': ('jogada', 43.5), 'activate': ('jogada', 63.9),
                 'attach_don': ('sobreposicao', 23.5),
                 'attack-quem': ('sobreposicao', 71.6),
                 'attack-alvo': ('jogada', 69.3)}

# indices do acumulador por categoria.
#
# `N_UNIAO` existe SO pra reproduzir a linha REAL das categorias que a
# tabela oficial mediu por sobreposicao. Os NIVEIS DE ORACULO ficam
# sempre na regua por jogada, e isso nao e escolha de gosto: sob
# sobreposicao, um escolhedor PERFEITO nunca faz nada a mais, entao
# |H u escolha_perfeita| colapsa em |H| -- a regua de sobreposicao e a
# de jogada sao a MESMA coisa no teto. Punir excesso so faz sentido pra
# quem de fato erra pra mais, isto e, pro motor real.
(N_HUM, REAL, BUSCA, GERACAO, TURNOS, CJ_REAL, CJ_BUSCA, CJ_GERACAO,
 N_UNIAO) = range(9)


def _novo_acumulador():
    return {c: [0] * 9 for c in CATEGORIAS}


def _soma(dst, src):
    for c, v in src.items():
        for i, x in enumerate(v):
            dst[c][i] += x


def _extrai(t, raw_t, cards_db, opp_leader_code):
    """{categoria: (H, M, C, A)} -- conjuntos do humano / motor /
    shortlist / tudo gerado, no MESMO turno.

    As definicoes de H e M sao identicas as de `_offense_verdict`
    (decision_quality_full.py) -- e por isso que a linha REAL reproduz a
    tabela oficial. C e A saem do `decision_log` cru.
    """
    hist = raw_t.get('actions') or []
    decisions = t.get('decisions') or []
    motor = t.get('chosen_actions') or []

    def _hk(code):
        return hist_action_kind({'type': 'activate', 'card': code}, cards_db)

    def _cands(kind):
        s = {(c.get('card') or {}).get('code')
             for r in decisions for c in (r.get('candidates') or [])
             if c.get('kind') == kind}
        s.discard(None)
        return s

    def _todas(kind):
        s = {a.get('code') for r in decisions
             for a in (r.get('all_actions') or []) if a.get('kind') == kind}
        s.discard(None)
        return s

    out = {}

    # -- play ---------------------------------------------------------
    H = {a['card'] for a in hist if a.get('card') and (
        a.get('type') == 'play'
        or (a.get('type') == 'activate' and _hk(a['card']) == 'play'))}
    M = {a['card'] for a in motor if a.get('kind') == 'play' and a.get('card')}
    out['play'] = (H, M, _cands('play') | M, _todas('play') | M)

    # -- activate -----------------------------------------------------
    H = {a['card'] for a in hist if a.get('type') == 'activate'
         and a.get('card') and _hk(a['card']) == 'activate'}
    M = {a['card'] for a in motor if a.get('kind') == 'activate' and a.get('card')}
    out['activate'] = (H, M, _cands('activate') | M, _todas('activate') | M)

    # -- attach_don (ALVO do DON) -------------------------------------
    H = {a['to'] for a in hist if a.get('type') == 'attach_don' and a.get('to')}
    M = {a['card'] for a in motor if a.get('kind') == 'attach_don' and a.get('card')}
    for rec in t.get('attach_don_for_attack_events', []):
        if rec.get('card'):
            M.add(rec['card'])
    out['attach_don'] = (H, M, _cands('attach_don') | M, _todas('attach_don') | M)

    # -- attack: QUEM atacou ------------------------------------------
    h_atk, m_atk = {}, {}
    for a in hist:
        if a.get('type') == 'attack' and a.get('attacker_code'):
            h_atk[a['attacker_code']] = _hist_target_type_code(
                a.get('target'), opp_leader_code)
    for a in motor:
        if a.get('kind') == 'attack' and a.get('card'):
            m_atk[a['card']] = (a.get('target_type'), a.get('target'))
    H, M = set(h_atk), set(m_atk)
    out['attack-quem'] = (H, M, _cands('attack') | M, _todas('attack') | M)

    # -- attack: ALVO (so entre atacantes que os DOIS usaram, mesmo
    #    denominador da tabela oficial) --------------------------------
    comuns = H & M
    Ha = {(c, h_atk[c]) for c in comuns}
    Ma = {(c, m_atk[c]) for c in comuns}
    Ca = set(Ma)
    for r in decisions:
        for c in (r.get('candidates') or []):
            if c.get('kind') != 'attack':
                continue
            code = (c.get('card') or {}).get('code')
            if code in comuns:
                alvo = c.get('target')
                Ca.add((code, (c.get('target_type'),
                               alvo.get('code') if alvo else None)))
    # `all_actions` e o formato ENXUTO (score/kind/code) e NAO carrega
    # alvo -- entao o nivel GERACAO nao existe pra esta categoria.
    out['attack-alvo'] = (Ha, Ma, Ca, None)
    return out


def _processa(tarefa):
    pf, human, lider = tarefa
    cards_db = _processa.cards_db
    df_raw, urls = _processa.df_raw, _processa.urls
    acc = _novo_acumulador()
    por_lider = defaultdict(_novo_acumulador)
    quebras = 0
    path = os.path.join('logs', pf)
    try:
        raw = json.load(open(path, encoding='utf-8'))
        rep = audit_one_game(path, human, cards_db, df_raw, urls,
                             capture_actions=True, capture_candidates=True)
    except Exception:
        return acc, {}, 0
    if rep.get('error'):
        return acc, {}, 0

    # MESMA derivacao de `_offense_verdict` (decision_quality_full.py):
    # o lado oponente e o nome do meta que NAO e o humano auditado -- vale
    # pros dois formatos de log (bot-vs-humano usa 'You'/'Opponent', humano-
    # vs-humano usa os nomes reais). Errar isto faz `_hist_target_type_code`
    # classificar ataque ao lider como ataque a personagem, e a categoria
    # attack-alvo desaba (medido: 2,3% em vez de 69,3%).
    meta = (raw.get('meta') or {}).get('players') or {}
    if 'p1' not in meta or 'p2' not in meta:
        return acc, {}, 0
    opp_side = meta['p2']['name'] if meta['p1']['name'] == human else meta['p1']['name']
    opp_leader_code = meta['p1' if meta['p1']['name'] == opp_side
                           else 'p2']['leader'].get('code')
    rb = {(t['turn'], t['player']): t for t in raw['turns']}

    for t in rep.get('turnos', []):
        if not t.get('decisions'):
            continue
        raw_t = rb.get((t['turn'], human))
        if not raw_t:
            continue
        lid = t.get('leader') or lider
        for cat, (H, M, C, A) in _extrai(t, raw_t, cards_db,
                                         opp_leader_code).items():
            # ACHADO 29/08, ao conferir as 2 FALHAs da validacao: a uniao
            # tem que somar TAMBEM os turnos em que o humano nao fez nada
            # nessa categoria e o motor fez -- e assim que a tabela
            # oficial conta (`don_alvo_union` etc. e somado sobre TODAS as
            # linhas). Sao 380 unidades em attach_don (36% do denominador
            # oficial de 1055!) e 66 em attack-quem: turnos em que o
            # humano nao anexou/atacou e o motor sim. Sem esta linha, a
            # validacao comparava a MINHA uniao restrita contra a uniao
            # completa da tabela oficial e acusava FALHA numa extracao
            # que estava certa -- conferido: os numeradores batem EXATO
            # nas 4 categorias (play 528, activate 280, attach_don 248,
            # attack-quem 1449).
            acc[cat][N_UNIAO] += len(H | M)
            por_lider[lid][cat][N_UNIAO] += len(H | M)
            if not H:
                continue          # sem jogada humana = fora do denominador
                                  # POR JOGADA (nao ha |H| pra dividir)
            r, b = len(H & M), len(H & C)
            g = len(H & A) if A is not None else 0
            if b < r or (A is not None and g < b):
                quebras += 1
            linha = [len(H), r, b, g, 1,
                     int(H == M), int(H <= C),
                     int(A is not None and H <= A), 0]   # uniao ja somada acima
            for i, x in enumerate(linha):
                acc[cat][i] += x
                por_lider[lid][cat][i] += x
    return acc, {k: dict(v) for k, v in por_lider.items()}, quebras


def _init(cards_db, df_raw, urls):
    _processa.cards_db = cards_db
    _processa.df_raw = df_raw
    _processa.urls = urls


def _pc(n, d):
    return f'{100*n/d:5.1f}%' if d else '   n/a'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=1,
                    help='processos em paralelo (convencao do projeto: escolher sempre)')
    ap.add_argument('--limit', type=int, default=0, help='so os N primeiros logs')
    ap.add_argument('--out', default='metrics/oraculo_teto.json')
    args = ap.parse_args()

    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    tarefas = [(pf, human, lider) for pf, human, lider, _g in find_all_human_logs()]
    if args.limit:
        tarefas = tarefas[:args.limit]
    print(f'{len(tarefas)} logs | workers={args.workers}\n')

    acc = _novo_acumulador()
    por_lider = defaultdict(_novo_acumulador)
    quebras = 0
    if args.workers > 1:
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=args.workers, initializer=_init,
                initargs=(cards_db, df_raw, urls)) as ex:
            for a, pl, q in ex.map(_processa, tarefas):
                _soma(acc, a)
                quebras += q
                for lid, v in pl.items():
                    _soma(por_lider[lid], v)
    else:
        _init(cards_db, df_raw, urls)
        for tarefa in tarefas:
            a, pl, q = _processa(tarefa)
            _soma(acc, a)
            quebras += q
            for lid, v in pl.items():
                _soma(por_lider[lid], v)

    # -- VALIDACAO: a linha REAL tem que reproduzir o bloco 729 --------
    print('== VALIDACAO (a linha REAL tem que bater com a tabela oficial do bloco 729) ==')
    if args.limit:
        print('  (AVISO: --limit ativo -- a tabela oficial e do CORPUS INTEIRO,')
        print('   entao FALHA aqui e esperado e nao diz nada. Validar so no corpus todo.)')
    ok_geral = True
    for cat in CATEGORIAS:
        regua, esperado = REGUA_OFICIAL[cat]
        den = acc[cat][N_UNIAO] if regua == 'sobreposicao' else acc[cat][N_HUM]
        obtido = 100 * acc[cat][REAL] / den if den else 0
        ok = abs(obtido - esperado) <= 1.0
        ok_geral &= ok
        print(f'  {cat:14} real {obtido:5.1f}%  oficial {esperado:5.1f}%'
              f'  ({regua})   {"PASSA" if ok else "FALHA"}   n={den}')
    print(f'\n  monotonicidade real<=busca<=geracao: '
          f'{"OK" if quebras == 0 else str(quebras) + " QUEBRAS"}')
    if not ok_geral:
        print('\n  *** VALIDACAO EM FALHA -- os tetos abaixo NAO sao comparaveis '
              'a regua oficial. Nao interpretar. ***')

    # -- AS DUAS REGUAS, LADO A LADO -----------------------------------
    print('\n== a linha REAL nas DUAS reguas (o bloco 729 usa uma pra cada categoria) ==')
    print(f'  {"categoria":14}{"por jogada":>12}{"sobrepos.":>12}'
          f'{"|H|":>7}{"|HuM|":>7}   regua usada no bloco 729')
    for cat in CATEGORIAS:
        nh, nu, r = acc[cat][N_HUM], acc[cat][N_UNIAO], acc[cat][REAL]
        if not nh:
            continue
        print(f'  {cat:14}{_pc(r,nh):>12}{_pc(r,nu):>12}{nh:7}{nu:7}   '
              f'{REGUA_OFICIAL[cat][0]}')

    # -- REGUA OFICIAL: acerto por jogada ------------------------------
    print('\n== TETO por categoria -- REGUA POR JOGADA (a oficial do bloco 728) ==')
    print(f'  {"categoria":14}{"real":>8}{"busca":>8}{"geracao":>9}{"n":>7}'
          f'{"valor":>9}{"corte":>9}{"inalcanc":>10}')
    tot = [0, 0, 0, 0]
    for cat in CATEGORIAS:
        n, r, b, g = acc[cat][:4]
        if not n:
            continue
        tem_g = cat != 'attack-alvo'
        col_g = _pc(g, n) if tem_g else '    n/d'
        col_corte = f'{(g-b)/n*100:+7.1f}pp' if tem_g else '      --'
        col_inalc = f'{(n-g)/n*100:8.1f}pp' if tem_g else '       --'
        print(f'  {cat:14}{_pc(r,n):>8}{_pc(b,n):>8}{col_g:>9}{n:7}'
              f'{(b-r)/n*100:+8.1f}pp{col_corte:>9}{col_inalc:>10}')
        tot[0] += n
        tot[1] += r
        tot[2] += b
        if tem_g:
            tot[3] += g
    print('  ' + '-' * 70)
    print(f'  {"AGREGADO":14}{_pc(tot[1],tot[0]):>8}{_pc(tot[2],tot[0]):>8}'
          f'{"":>9}{tot[0]:7}   (geracao nao somavel: attack-alvo sem nivel 3)')

    # -- REGUA DE CONJUNTO (so pra comparar com o bloco 697) -----------
    print('\n== mesma medida na REGUA VELHA (conjunto exato) -- comparavel ao bloco 697 ==')
    for cat in CATEGORIAS:
        nt = acc[cat][TURNOS]
        cr, cb, cg = acc[cat][CJ_REAL], acc[cat][CJ_BUSCA], acc[cat][CJ_GERACAO]
        if not nt:
            continue
        col_g = _pc(cg, nt) if cat != 'attack-alvo' else '    n/d'
        print(f'  {cat:14}{_pc(cr,nt):>8}{_pc(cb,nt):>8}{col_g:>9}{nt:7} turnos')

    # -- RECORTE POR LIDER (obrigatorio, CLAUDE.md) --------------------
    print('\n== recorte POR LIDER (n>=8 na categoria) -- nenhum agregado vale sem isto ==')
    for cat in CATEGORIAS:
        linhas = [(lid, v[cat]) for lid, v in por_lider.items()
                  if v[cat][N_HUM] >= 8]
        if not linhas:
            continue
        print(f'\n  -- {cat} --')
        print(f'    {"lider":12}{"real":>8}{"busca":>8}{"geracao":>9}{"n":>6}')
        for lid, v in sorted(linhas, key=lambda x: -x[1][N_HUM]):
            n, r, b, g = v[:4]
            col_g = _pc(g, n) if cat != 'attack-alvo' else '    n/d'
            print(f'    {lid:12}{_pc(r,n):>8}{_pc(b,n):>8}{col_g:>9}{n:6}')

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump({'agregado': acc,
                   'por_lider': {k: dict(v) for k, v in por_lider.items()},
                   'n_logs': len(tarefas), 'quebras_monotonicidade': quebras,
                   'validacao_ok': bool(ok_geral)}, fh, indent=1)
    print(f'\nsalvo em {args.out}')


if __name__ == '__main__':
    main()
