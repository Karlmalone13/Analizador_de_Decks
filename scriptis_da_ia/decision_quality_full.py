"""
decision_quality_full.py -- comparacao COMPLETA motor-de-hoje vs humano,
turno a turno, cobrindo TODAS as categorias de decisao (pedido explicito
do usuario, 17/08: "nao quero so DON ocioso, tem que ser todas as
decisoes... counter, ordem de counter, blocker, efeito, ataque,
distribuicao de dons, ativacao de efeito").

`decision_quality_vs_human.py` so media DANO agregado do turno proprio.
O scratchpad `audit_defense.py` (nunca formalizado) media blocker/counter
mas so sim/nao, sem qual carta nem ordem. Este script unifica os dois e
fecha a lacuna de ORDEM de counter, numa unica tabela por categoria --
pra nunca mais precisar responder "90% em relacao a que?" caca-niquel.

CATEGORIAS (cada uma sua propria %, contra sua propria base de turnos/
ataques -- nao existe um numero unico "o bot joga X% igual ao humano"
porque cada categoria tem denominador diferente):

  OFENSIVA (turno PROPRIO de cada humano, via audit_one_game(capture_
  actions=True) -- fonte unica, chama OPTCGMatch.play_turn() de
  verdade, nao reimplementa decisao):
    - play: mesmo(s) codigo(s) de carta jogada(s) no turno (conjunto)
    - attack_quem: mesmo(s) atacante(s) atacaram (conjunto)
    - attack_alvo: dos atacantes em comum, mesmo alvo escolhido
    - activate: mesma(s) carta(s) ativou [Activate: Main]
    - attach_don_alvo: mesmo(s) personagem(ns)/lider recebeu DON
    - sequencia: ORDEM de execucao (play/activate/attack/attach_don
      combinados) identica start-a-fim, e similaridade por LCS (quanto
      da ordem bate, sem exigir identidade total)
    - alvo_efeito: quando os dois jogaram/ativaram a MESMA carta,
      mesmo alvo ESCOLHIDO DENTRO do efeito dela (nao so ataque) --
      best-effort via texto da narrativa, rotulado como tal (nao e um
      campo estruturado como target_type/target de attack)

    LIMITACAO NOVA (17/08, pedido do usuario "e os outros efeitos,
    mecanicas, sequencias"): mulligan (manter ou embaralhar a mao
    inicial) NAO e capturado pelo schema do log (`meta.goes_first` e o
    unico campo relacionado, sempre null nos logs do banco) -- nao ha
    como medir essa decisao com os dados disponiveis, declarado aqui em
    vez de fingir cobertura.

  DEFESA (turno do OPONENTE, ataque a ataque contra o humano --
  reconstrucao igual `audit_defense.py`, chama DIRETAMENTE
  DecisionEngine.should_use_blocker/should_use_counter/pick_counters,
  as MESMAS funcoes que o jogo ao vivo usa via _execute_attack):
    - blocker_sim_nao: bloquearia? (bool)
    - blocker_carta: quando os dois bloquearam, mesma carta?
    - counter_sim_nao: counteraria? (bool)
    - counter_cartas: quando os dois counteraram, mesmo CONJUNTO de cartas?
    - counter_ordem: quando os dois usaram 2+ cartas, MESMA ORDEM
      (pick_counters ja devolve a selecao gulosa por menor pitch_cost --
      a mesma ordem que o jogo ao vivo jogaria as cartas)?

LIMITACOES (herdadas de audit_one_game/audit_defense -- ver os
docstrings deles): don_available e reconstrucao best-effort; deck
restante e composicao real mas ORDEM embaralhada; mao do oponente com
informacao COMPLETA (motor enxerga mais que o bot ao vivo enxergaria);
DEFESA reconstroi o board do defensor uma vez por TURNO do atacante, nao
ataque-a-ataque dentro do mesmo turno (aproximacao ja aceita no
scratchpad original).

Uso:
    python decision_quality_full.py --all [--workers N]
    python decision_quality_full.py --leader OP17-039 [--workers N]
    python decision_quality_full.py --log <parsed.json>
"""
import argparse
import concurrent.futures
import json
import os
import re

import pandas as pd

from audit_real_losses import (
    audit_one_game, _cards_from_codes, _find_real_deck, DonEstimator,
    hist_action_kind,
)
from decision_quality_vs_human import find_bot_vs_human_logs, find_all_human_logs
from optcg_engine.decision_engine import (
    load_cards_db, DecisionEngine, GameState, populate_full_deck_knowledge,
    attack_time_power, get_card_effects,
)

LOGS_DIR = 'logs'
OUT_DIR = os.path.join('metrics', 'decision_quality_full')
CODE_RE = re.compile(r'"([A-Za-z0-9\-]+)">')


# ── OFENSIVA (turno proprio) ────────────────────────────────────────────

def _hist_target_type_code(target_raw, leader_code):
    m = CODE_RE.search(target_raw or '')
    code = m.group(1) if m else None
    is_leader = (code == leader_code) or ('Leader' in (target_raw or ''))
    return ('leader', None) if is_leader else ('character', code)


def _offense_verdict(parsed_path, human_side_label, cards_db, df_raw, urls):
    data = json.load(open(parsed_path, encoding='utf-8'))
    # Achado real 18/08 (bloco 617): 30 logs do banco usam um schema
    # MAIS ANTIGO (`meta` sem o wrapper 'players', formato ainda nao
    # mapeado por completo) -- crashava o `--all` inteiro (via
    # ProcessPoolExecutor, 1 excecao derruba o batch todo). Pula
    # graciosamente, mesmo padrao de erro ja usado pro resto do
    # pipeline (`if 'error' not in r['offense']`), em vez de tentar
    # suportar um schema desconhecido as pressas.
    if 'players' not in data.get('meta', {}):
        return {'error': f'schema de log antigo sem meta.players: {os.path.basename(parsed_path)}'}
    meta = data['meta']['players']
    turns_raw = data['turns']
    # Achado real 18/08 (bloco 617, escopo ampliado pros 124 logs
    # humano-vs-humano do banco, pedido do usuario "por que so 26 se
    # temos 150?"): `opp_side` era um flip binario hardcoded ('You'/
    # 'Opponent') -- so funcionava pra logs bot-vs-humano, que sempre
    # usam essa convencao fixa. Logs humano-vs-humano usam o NOME REAL
    # dos 2 jogadores (ex: "Karlmalone#2854"), entao o flip sempre
    # devolvia 'You' (nunca batendo com nenhum dos dois nomes reais),
    # quebrando a reconstrucao do lado oponente. Deriva do proprio meta
    # (qualquer um dos dois nomes que NAO seja o human_side_label) --
    # funciona igual pros dois formatos, sem regressao pro caminho
    # antigo (onde o resultado e identico ao flip binario).
    opp_side = meta['p2']['name'] if meta['p1']['name'] == human_side_label else meta['p1']['name']
    opp_leader_code = meta['p1' if meta['p1']['name'] == opp_side else 'p2']['leader'].get('code')
    # bloco 652: codigo do lider do lado AUDITADO -- alimenta o recorte por
    # lider do relatorio (ver comentario em `_print_report`)
    bot_leader_code = meta['p1' if meta['p1']['name'] == human_side_label else 'p2']['leader'].get('code')

    # Achado real 17/08: `attach_don_alvo` (mais abaixo) sempre pretendeu
    # incluir `attach_don_for_attack_events` (o top-up AUTOMATICO que
    # acontece durante a execucao de um ataque ja escolhido, ver docstring
    # do modulo) -- mas essa chamada nunca passava `capture_candidates=
    # True`, o UNICO jeito de `audit_one_game` popular esse campo. O
    # metodo ficava, sem querer, so vendo attach_don GERADO como candidato
    # PROPRIO do Turn Planner (raro), cego pro caminho principal (anexar
    # DON durante a execucao de um ataque ja decidido). Ficou mascarado
    # enquanto os decks eram genericos (bug de casamento de nome, ver
    # audit_real_losses._find_real_deck) -- com decks REAIS a metrica caiu
    # pra 0% EXATO, sinal forte demais pra ser coincidencia, o que expos
    # a lacuna. Fix: pede capture_candidates=True tambem.
    report = audit_one_game(parsed_path, human_side_label, cards_db, df_raw, urls,
                            capture_actions=True, capture_candidates=True)
    if report.get('error'):
        return {'error': report['error']}

    rows = []
    for t in report.get('turnos', []):
        if 'error' in t:
            continue
        turn_num = t['turn']
        hist_actions = t.get('historical_actions', [])
        motor_actions = t.get('chosen_actions', [])

        # Achado real 17/08 (bloco 597): o log historico rotula `type`
        # por CONVENCAO DA SIMULACAO, nao por categoria do motor -- jogar
        # uma carta EVENT/STAGE da mao aparece como `type: "activate"`
        # la, enquanto o motor sempre gera essa MESMA acao como `kind:
        # "play"`. EVENT/STAGE = "play" sempre (so podem ser jogados da
        # mao, nunca ficam "ativaveis" depois).
        #
        # Achado real 17/08, 2a rodada (pedido do usuario "temos que
        # subir essa porcentagem", censo amplo de 'activate' achou 79/81
        # casos "nunca gerado" -- quase todos Rocks D. Xebec OP17-039):
        # LEADER/CHARACTER com `type=="activate"` NAO significa
        # `[Activate:Main]` de verdade -- o rotulo historico e um
        # guarda-chuva pra QUALQUER efeito nao-play/nao-attack resolvido
        # (on_ko, when_attacking, on_opp_attack, end_of_turn,
        # leader_battle_reactive, on_play tambem aparecem como
        # "activate" no log). Xebec NEM TEM `activate_main` definido --
        # o "activate" dele no log e o `when_attacking` (ja investigado
        # a fundo no bloco 600) disparando JUNTO do proprio ataque, nao
        # uma acao de Main Phase separada que o Turn Planner geraria
        # como candidato proprio. Comparar isso contra `kind=='activate'`
        # do motor (que so existe pra `[Activate:Main]` real,
        # `_score_activate_main`) e categoria errada -- garantia de
        # falso mismatch pra QUALQUER carta sem `activate_main`, nao um
        # sinal de decisao ruim do motor. Fix: so classifica como
        # "activate" comparavel quando a carta REALMENTE tem
        # `activate_main` no card_effects_db; senao, EXCLUI da
        # comparacao (nem play nem activate -- e um efeito reativo
        # automatico, nao uma decisao independente do Turn Planner).
        #
        # Achado real 23/08 (bloco 650): a ordem dos dois primeiros gates
        # estava INVERTIDA pra STAGE. Uma STAGE fica EM CAMPO depois de
        # jogada e 33 das 49 STAGE do banco tem [Activate: Main] proprio --
        # o comentario acima ("so podem ser jogados da mao, nunca ficam
        # ativaveis depois") vale pra EVENT, nao pra STAGE. Com o gate de
        # card_type vindo primeiro, TODA ativacao de uma Stage ja em campo
        # era rotulada 'play' de uma carta que nao esta (nem podia estar) na
        # mao -- mismatch garantido em `play` E some do denominador de
        # `activate`, penalizando a MESMA acao humana duas vezes. Medido no
        # corpus: 134 turnos (14,5% do denominador de `play`), 7 Stages
        # distintas, 8 lideres -- concentrado em Imu OP13-079 (94), a Empty
        # Throne OP13-099 sozinha em 98. Fix generico pela FORMA: se o log
        # disse 'activate' e a carta TEM activate_main de verdade, e
        # activate, seja qual for o card_type. Seguro por construcao pra
        # EVENT: ZERO das 405 EVENT do banco tem activate_main, entao
        # nenhum play de Evento muda de categoria.
        def _hist_kind(card_type, code):
            return hist_action_kind({'type': 'activate', 'card': code}, cards_db)

        hist_play = {a['card'] for a in hist_actions if a.get('card') and (
            a.get('type') == 'play'
            or (a.get('type') == 'activate'
                and _hist_kind(cards_db.get(a['card'], {}).get('type'), a['card']) == 'play'))}
        motor_play = {a['card'] for a in motor_actions if a.get('kind') == 'play' and a.get('card')}

        hist_activate = {a['card'] for a in hist_actions if a.get('type') == 'activate' and a.get('card')
                         and _hist_kind(cards_db.get(a['card'], {}).get('type'), a['card']) == 'activate'}
        motor_activate = {a['card'] for a in motor_actions if a.get('kind') == 'activate' and a.get('card')}

        hist_don_alvo = {a['to'] for a in hist_actions if a.get('type') == 'attach_don' and a.get('to')}
        motor_don_alvo = {a['card'] for a in motor_actions if a.get('kind') == 'attach_don' and a.get('card')}
        for rec in t.get('attach_don_for_attack_events', []):
            if rec.get('card'):
                motor_don_alvo.add(rec['card'])

        hist_attacks = []
        for a in hist_actions:
            if a.get('type') != 'attack' or not a.get('attacker_code'):
                continue
            ttype, tcode = _hist_target_type_code(a.get('target'), opp_leader_code)
            hist_attacks.append((a['attacker_code'], ttype, tcode))
        motor_attacks = [(a['card'], a.get('target_type'), a.get('target'))
                         for a in motor_actions if a.get('kind') == 'attack' and a.get('card')]

        hist_atk_who = {a[0] for a in hist_attacks}
        motor_atk_who = {a[0] for a in motor_attacks}
        hist_atk_map = {a[0]: (a[1], a[2]) for a in hist_attacks}
        motor_atk_map = {a[0]: (a[1], a[2]) for a in motor_attacks}
        common_attackers = hist_atk_who & motor_atk_who
        alvo_matches = [hist_atk_map[c] == motor_atk_map[c] for c in common_attackers]

        # Achado real 17/08 (pedido do usuario: "e os outros efeitos,
        # mecanicas, sequencias?" -- ate aqui so comparava CONJUNTO de
        # cartas por categoria, nunca a ORDEM de execucao dentro do
        # turno nem o ALVO escolhido DENTRO de um efeito de play/
        # activate (so attack/attach_don tinham alvo comparado). Duas
        # extensoes:
        #
        # 1. SEQUENCIA: lista ORDENADA (kind, codigo) de play/activate/
        # attack/attach_don, na ordem real de execucao (o proprio
        # schema do log ja preserva ordem; chosen_actions tambem, pela
        # ordem que o decision_log registrou). match_exato = sequencia
        # IDENTICA start-a-fim; similaridade = razao de subsequencia
        # comum mais longa (LCS) sobre o maior dos dois -- mede "quanto
        # da ordem bate" sem exigir identidade total (empate tatico em
        # 1 passo nao deveria zerar a sequencia inteira).
        hist_seq = []
        for a in hist_actions:
            if a.get('type') == 'play' and a.get('card'):
                hist_seq.append(('play', a['card']))
            elif a.get('type') == 'activate' and a.get('card'):
                kind = _hist_kind(cards_db.get(a['card'], {}).get('type'), a['card'])
                if kind:  # None = efeito reativo automatico, nao comparavel -- fora da sequencia
                    hist_seq.append((kind, a['card']))
            elif a.get('type') == 'attack' and a.get('attacker_code'):
                hist_seq.append(('attack', a['attacker_code']))
            elif a.get('type') == 'attach_don' and a.get('to'):
                hist_seq.append(('attach_don', a['to']))
        motor_seq = [(a['kind'], a['card']) for a in motor_actions
                    if a.get('kind') in ('play', 'activate', 'attack', 'attach_don') and a.get('card')]

        def _lcs_len(x, y):
            m, n = len(x), len(y)
            if m == 0 or n == 0:
                return 0
            dp = [[0] * (n + 1) for _ in range(m + 1)]
            for ii in range(1, m + 1):
                for jj in range(1, n + 1):
                    if x[ii - 1] == y[jj - 1]:
                        dp[ii][jj] = dp[ii - 1][jj - 1] + 1
                    else:
                        dp[ii][jj] = max(dp[ii - 1][jj], dp[ii][jj - 1])
            return dp[m][n]

        seq_lcs = _lcs_len(hist_seq, motor_seq)
        seq_maxlen = max(len(hist_seq), len(motor_seq))

        # 2. ALVO dentro do efeito de play/activate (nao so attack) --
        # so comparavel quando os DOIS jogaram/ativaram a MESMA carta
        # neste turno (senao nao ha o que comparar). Historico: 1o
        # codigo mencionado no texto de `effects` que nao seja a
        # propria carta. Motor: 1o codigo mencionado na narrativa entre
        # o "Joga:"/"ativou" desta carta e a proxima acao -- best-effort
        # (narrativa e texto livre, nao um campo estruturado), rotulado
        # como tal no relatorio final.
        # Achado real 17/08 (ao validar esta metrica antes de reportar,
        # mesma disciplina de sempre -- 2 tentativas descartadas):
        # 1a: buscar CODIGO (formato `["COD">COD]`) na narrativa do
        # motor -- ZERO ocorrencias em qualquer narrativa gerada
        # (confirmado, grep de `">`  em 3 turnos = 0): a narrativa so
        # imprime NOME truncado (`card.name[:30]`), nunca o bracket-
        # code do log historico. CODE_RE nunca poderia bater ali.
        # 2a: nome com espaco ("Mr. 5 (Gem)" do cards_db) contra
        # narrativa sem espaco ("Mr.5(Gem)") -- tambem falhava, so por
        # formatacao. Fix final: INVERTE a direcao -- historico da o
        # CODIGO do alvo (formato bracket, confiavel), converte pra
        # NOME via cards_db, normaliza removendo espaco dos DOIS lados
        # (nome candidato E narrativa) antes de procurar substring.
        def _sem_espaco(s):
            return (s or '').replace(' ', '')

        narrativa = t.get('engine_hoje_narrativa', '')
        narrativa_sem_espaco = _sem_espaco(narrativa)
        cartas_ambos = (hist_play & motor_play) | (hist_activate & motor_activate)
        alvo_efeito_matches = []
        for code in cartas_ambos:
            hist_eff_text = ' '.join(
                e for a in hist_actions if a.get('card') == code for e in (a.get('effects') or []))
            hist_target_codes = {m for m in CODE_RE.findall(hist_eff_text) if m != code}
            if not hist_target_codes:
                continue
            # Achado real 17/08 (2a rodada de validacao): a 1a ocorrencia
            # do nome na narrativa costuma ser a linha "Comprou: X" (o
            # anuncio de compra no INICIO do turno, sempre impresso),
            # nao a jogada de verdade -- ancora a busca em "Joga:"/
            # "ativou" (os 2 prefixos que `_play_card`/o log de activate
            # usam), senao pega o trecho errado da narrativa.
            nome_carta = cards_db.get(code, {}).get('name', '')
            nome_curto = _sem_espaco(nome_carta.split(' (')[0].split(' [')[0]) if nome_carta else code
            idx = -1
            for prefixo in ('Joga:', 'ativou[Activate:Main]de'):
                pos = narrativa_sem_espaco.find(prefixo + nome_curto)
                if pos < 0:
                    # narrativa trunca nome em 30 chars -- tenta prefixo parcial tambem
                    pos = narrativa_sem_espaco.find(prefixo)
                    while pos >= 0:
                        if nome_curto[:10] and nome_curto[:10] in narrativa_sem_espaco[pos:pos+60]:
                            break
                        pos = narrativa_sem_espaco.find(prefixo, pos + 1)
                if pos >= 0:
                    idx = pos
                    break
            if idx < 0:
                continue
            trecho = narrativa_sem_espaco[idx:idx + 500]
            fim = trecho.find('>Joga:', 10)
            if fim < 0:
                fim = len(trecho)
            trecho = trecho[:fim]
            # converte cada alvo HISTORICO (codigo) pro nome truncado
            # (mesmo corte de 30 chars que a narrativa usa) e procura
            # esse nome, sem espaco, dentro do trecho.
            bateu = False
            for tcode in hist_target_codes:
                tnome = cards_db.get(tcode, {}).get('name', '')
                if not tnome:
                    continue
                tmarcador = _sem_espaco(tnome[:30])
                if tmarcador and tmarcador in trecho:
                    bateu = True
                    break
            alvo_efeito_matches.append(bateu)

        # Achado real 23/08 (bloco 650): as % de conjunto sao TUDO-OU-NADA
        # (`hist == motor`). Um turno em que o humano jogou {A,B} e o motor
        # jogou {A} pontua exatamente igual a um em que jogou {Z} -- a
        # metrica nao consegue expressar "chegou perto", entao ela nao sobe
        # quando o motor melhora PARCIALMENTE, e ate DESCE quando uma
        # correcao de fidelidade faz os dois lados compararem MAIS itens.
        # `*_inter`/`*_union` guardam a intersecao e a uniao brutas por
        # turno: somadas no agregado dao um Jaccard micro-medio, que mede
        # "quanto das decisoes do turno bateu" ao lado do "o turno inteiro
        # bateu". Nenhuma das % antigas muda -- so ganham companhia.
        def _io(h, m):
            return len(h & m), len(h | m)
        play_i, play_u = _io(hist_play, motor_play)
        act_i, act_u = _io(hist_activate, motor_activate)
        atk_i, atk_u = _io(hist_atk_who, motor_atk_who)
        don_i, don_u = _io(hist_don_alvo, motor_don_alvo)

        rows.append({
            'game': os.path.basename(parsed_path), 'turn': turn_num,
            # bloco 652: sem isto o recorte por lider tinha que ser
            # reconstruido por fora, cruzando com os logs
            'leader': bot_leader_code,
            'play_inter': play_i, 'play_union': play_u,
            # bloco 691: a CONTAGEM bruta de cada lado. Sem isto,
            # `inter`/`union` nao distinguem "motor jogou a MENOS" de
            # "jogou a MAIS" -- e a contagem e o teto aritmetico do
            # `play` (acerta quantas cartas jogar em so 52,7% dos
            # turnos, entao o match exato nao passa disso). Era preciso
            # rodar a regua inteira de novo so pra descobrir a direcao
            # do erro; agora sai de graca em qualquer medicao.
            'play_n_hum': len(hist_play), 'play_n_motor': len(motor_play),
            'activate_n_hum': len(hist_activate),
            'activate_n_motor': len(motor_activate),
            'activate_inter': act_i, 'activate_union': act_u,
            'attack_quem_inter': atk_i, 'attack_quem_union': atk_u,
            'don_alvo_inter': don_i, 'don_alvo_union': don_u,
            'play_match': hist_play == motor_play,
            'play_has_data': bool(hist_play or motor_play),
            'attack_quem_match': hist_atk_who == motor_atk_who,
            'attack_has_data': bool(hist_atk_who or motor_atk_who),
            'attack_alvo_common': len(common_attackers),
            'attack_alvo_match': sum(alvo_matches),
            'activate_match': hist_activate == motor_activate,
            'activate_has_data': bool(hist_activate or motor_activate),
            'don_alvo_match': hist_don_alvo == motor_don_alvo,
            'don_has_data': bool(hist_don_alvo or motor_don_alvo),
            'seq_exact_match': hist_seq == motor_seq,
            'seq_has_data': bool(hist_seq or motor_seq),
            'seq_lcs': seq_lcs,
            'seq_maxlen': seq_maxlen,
            'alvo_efeito_common': len(alvo_efeito_matches),
            'alvo_efeito_match': sum(alvo_efeito_matches),
        })
    return {'rows': rows}


# ── DEFESA (turno do oponente, ataque a ataque) ─────────────────────────

def _defense_verdict(parsed_path, human_side_label, cards_db, df_raw, urls):
    data = json.load(open(parsed_path, encoding='utf-8'))
    # Ver comentario equivalente em _offense_verdict (bloco 617).
    if 'players' not in data.get('meta', {}):
        return {'error': f'schema de log antigo sem meta.players: {os.path.basename(parsed_path)}'}
    meta = data['meta']['players']
    turns = data['turns']
    # Ver comentario equivalente em _offense_verdict (bloco 617).
    opp_side = meta['p2']['name'] if meta['p1']['name'] == human_side_label else meta['p1']['name']

    human_leader = meta['p1' if meta['p1']['name'] == human_side_label else 'p2']['leader']
    opp_leader = meta['p1' if meta['p1']['name'] == opp_side else 'p2']['leader']

    human_deck = _find_real_deck(human_leader['name'], cards_db, df_raw, urls, human_leader.get('code'))
    opp_deck = _find_real_deck(opp_leader['name'], cards_db, df_raw, urls, opp_leader.get('code'))
    if not human_deck or not opp_deck:
        return {'error': f'deck real nao encontrado (human={human_leader["name"]}, opp={opp_leader["name"]})'}

    rows = []
    for i, turn in enumerate(turns):
        if turn['player'] != opp_side or i == 0:
            continue
        before = turns[i - 1]['snapshot']
        if human_side_label not in before or opp_side not in before:
            continue
        human_snap = before[human_side_label]
        opp_snap = before[opp_side]

        don_on_attacker = {}
        don_est = DonEstimator()
        for j in range(i):
            don_est.apply_turn(turns[j]['player'], turns[j], cards_db)

        for act in turn.get('actions', []):
            if act.get('type') == 'attach_don':
                don_on_attacker[act.get('to')] = don_on_attacker.get(act.get('to'), 0) + int(act.get('amount', 0) or 0)
                continue
            if act.get('type') != 'attack':
                continue

            attacker_code = act.get('attacker_code')
            ttype, tcode = _hist_target_type_code(act.get('target'), human_leader.get('code'))

            human_leader_card = _cards_from_codes([human_leader['code']], cards_db)[0]
            opp_leader_card = _cards_from_codes([opp_leader['code']], cards_db)[0]
            human = GameState(leader=human_leader_card)
            opp = GameState(leader=opp_leader_card)
            human.hand = _cards_from_codes(human_snap.get('hand', []), cards_db)
            human.field_chars = _cards_from_codes(human_snap.get('board', []), cards_db, human_snap.get('rested', {}))
            human.trash = _cards_from_codes(human_snap.get('trash', []), cards_db)
            life_n = human_snap.get('life', 4)
            human.life = _cards_from_codes([human_leader['code']] * life_n, cards_db) if life_n else []

            opp.hand = _cards_from_codes(opp_snap.get('hand', []), cards_db)
            opp.field_chars = _cards_from_codes(opp_snap.get('board', []), cards_db, opp_snap.get('rested', {}))
            opp.trash = _cards_from_codes(opp_snap.get('trash', []), cards_db)
            opp_life_n = opp_snap.get('life', 4)
            opp.life = _cards_from_codes([opp_leader['code']] * opp_life_n, cards_db) if opp_life_n else []

            populate_full_deck_knowledge(human, human_deck[1], human_deck[0].code)
            populate_full_deck_knowledge(opp, opp_deck[1], opp_deck[0].code)
            human.don_available = don_est.available(human_side_label)

            attacker = opp.leader if opp.leader.code == attacker_code else next(
                (c for c in opp.field_chars if c.code == attacker_code), None)
            if attacker is None:
                continue
            attacker.don_attached = don_on_attacker.get(attacker_code, 0)
            atk_power = attack_time_power(attacker, human)

            target = None
            if ttype == 'character' and tcode:
                target = next((c for c in human.field_chars if c.code == tcode), None)

            eng = DecisionEngine(human, opp)
            try:
                blocker = eng.should_use_blocker(atk_power)
            except Exception as exc:
                rows.append({'game': os.path.basename(parsed_path), 'turn': turn['turn'], 'error': f'blocker: {exc}'})
                continue

            defend_power = (human.leader.power + human.leader.power_buff if ttype == 'leader'
                            else (target.power + target.power_buff if target else atk_power))
            needed = max(0, atk_power - defend_power + 1)
            try:
                escolha, gasto, total = eng.pick_counters(needed) if not blocker and needed > 0 else ([], 0.0, 0)
                would_counter = eng.should_use_counter(atk_power, defend_power) if not blocker else False
            except Exception:
                escolha, would_counter = [], False
            motor_counter_codes = [c.code for c in escolha] if would_counter else []

            hist_blocked = bool(act.get('blocked_by'))
            hist_countered_codes = [CODE_RE.search(x).group(1) if CODE_RE.search(x) else x
                                    for x in (act.get('countered_by') or [])]
            hist_ambiguous = (act.get('result') == 'blocked' and not hist_blocked and not hist_countered_codes)
            if hist_ambiguous:
                continue  # schema do log nao distingue blocker de counter aqui -- excluido, nao contado como erro

            rows.append({
                'game': os.path.basename(parsed_path), 'turn': turn['turn'],
                'attacker': attacker_code,
                'hist_blocked': hist_blocked,
                'engine_blocked': bool(blocker),
                'hist_blocker_card': act.get('blocked_by'),
                'engine_blocker_card': blocker.code if blocker else None,
                'hist_countered': bool(hist_countered_codes),
                'engine_countered': bool(motor_counter_codes),
                'hist_counter_codes': hist_countered_codes,
                'engine_counter_codes': motor_counter_codes,
            })
    return {'rows': rows}


def _run_one(task):
    parsed_path, human_side_label, human_leader, game_id = task
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()
    full_path = os.path.join(LOGS_DIR, parsed_path)
    off = _offense_verdict(full_path, human_side_label, cards_db, df_raw, urls)
    de = _defense_verdict(full_path, human_side_label, cards_db, df_raw, urls)
    return {'game_id': game_id, 'human_leader': human_leader, 'offense': off, 'defense': de}


def _pct(n, d):
    return f'{n}/{d} ({n / d * 100:.1f}%)' if d else 'sem dados'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--log')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--bot-only', action='store_true',
                     help='so os 26 logs bot-vs-humano (escopo antigo, pre-bloco-617)')
    ap.add_argument('--leader')
    ap.add_argument('--workers', type=int, default=1)
    # Bloco 683: subconjunto REPRODUTIVEL pra A/B rapido. O corpus inteiro
    # (274 lados) leva ~4h com 4 workers -- inviavel pra iterar. `--limit N`
    # pega os N PRIMEIROS jobs, que e uma ordem ESTAVEL (vem do index.json),
    # entao dois runs com o mesmo N comparam exatamente as MESMAS partidas.
    # Nunca usar --limit pra reportar numero ABSOLUTO do corpus; e pra
    # comparacao A/B (mesmo N nos dois lados).
    ap.add_argument('--limit', type=int, help='usa so os N primeiros jobs (A/B rapido)')
    # Bloco 688: CUIDADO com --limit sozinho -- os primeiros jobs sao os
    # logs mais ANTIGOS do indice, e nenhum deles tem os campos RZ1 (bloco
    # 684). Medir efeito de fidelidade com --limit 70 da resultado
    # IDENTICO por construcao (0 dos 70 tem RZ1) e parece "nao mudou nada".
    ap.add_argument('--only-rz1', action='store_true',
                     help='so logs COM os campos RZ1 (don_cost/life_cards)')
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.log:
        idx = json.load(open(os.path.join(LOGS_DIR, 'index.json'), encoding='utf-8'))
        entry = next((e for e in idx if e.get('parsed_file') == args.log or e.get('id') == args.log), None)
        if not entry or not entry.get('bot_side'):
            raise SystemExit(f'log nao encontrado ou sem bot_side: {args.log}')
        bs = entry['bot_side']
        human_key = 'p2' if bs == 'p1' else 'p1'
        jobs = [(entry['parsed_file'], 'Opponent' if bs == 'p1' else 'You',
                 entry[human_key]['leader_code'], entry['id'])]
    elif args.bot_only:
        jobs = find_bot_vs_human_logs(args.leader)
        if not jobs:
            raise SystemExit('nenhum log bot-vs-humano encontrado')
    else:
        # Achado real 18/08 (bloco 617, pedido do usuario "por que so 26
        # se temos 150 no banco?"): find_all_human_logs cobre os 150
        # logs (26 bot-vs-humano + 124 humano-vs-humano, auditando os 2
        # lados destes ultimos) -- default novo de --all. --bot-only
        # preserva o escopo antigo (26) pra quem precisar comparar
        # contra numeros historicos ja registrados no HANDOFF.
        jobs = find_all_human_logs(args.leader)
        if not jobs:
            raise SystemExit('nenhum log encontrado')

    if args.only_rz1:
        def _tem_rz1(pf):
            try:
                d = json.load(open(os.path.join(LOGS_DIR, pf), encoding='utf-8'))
            except Exception:
                return False
            return any('don_cost' in s for t in d.get('turns', [])
                       for s in (t.get('snapshot') or {}).values())
        jobs = [j for j in jobs if _tem_rz1(j[0])]
    if args.limit:
        jobs = jobs[:args.limit]
    print(f'{len(jobs)} log(s) a auditar (ofensiva + defesa)...')
    if args.workers <= 1:
        resultados = [_run_one(t) for t in jobs]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            resultados = list(ex.map(_run_one, jobs))

    off_rows, def_rows = [], []
    off_errors, def_errors = [], []
    for r in resultados:
        if 'error' not in r['offense']:
            off_rows.extend(r['offense']['rows'])
        elif r['offense'].get('error'):
            print(f"  ERRO ofensiva {r['game_id']}: {r['offense']['error']}")
            off_errors.append(r['offense']['error'])
        if 'error' not in r['defense']:
            def_rows.extend([row for row in r['defense']['rows'] if 'error' not in row])
        elif r['defense'].get('error'):
            print(f"  ERRO defesa {r['game_id']}: {r['defense']['error']}")
            def_errors.append(r['defense']['error'])

    print(f'\n{"="*72}')
    print(f'DECISION QUALITY FULL vs HUMANO -- {len(jobs)} partida(s)')
    print(f'{"="*72}')

    # Achado real 22/08 (bloco 642, pedido do usuario "melhore o decision
    # quality"): antes disto, o unico jeito de saber QUANTO da amostra
    # pretendida foi de fato excluida (e por que) era contar as linhas
    # "ERRO ..." espalhadas no meio do log a mao -- as PORCENTAGENS finais
    # ja mostravam "turnos com dado: X/Y" por CATEGORIA, mas nunca um
    # resumo de COBERTURA no nivel de JOGO/LOG (quantos dos N logs
    # pretendidos realmente entraram, agrupado por motivo de exclusao).
    # Investigado a fundo (nao um fix de codigo, uma descoberta real): os
    # 30 logs "schema antigo sem meta.players" (achado bloco 617) tem um
    # problema BEM mais profundo que so o wrapper 'players' ausente --
    # os 726 turnos deles tem `snapshot` chaveado por STRING VAZIA (''),
    # nao pelo nome de nenhum jogador (a reconstrucao de estado por lado
    # depende exatamente dessa chave) -- confirmado que NENHUM dos 726
    # turnos tem snapshot usavel, entao recuperar esses logs exigiria uma
    # metodologia de reconstrucao DIFERENTE (replay de acoes desde o
    # zero), nao um ajuste de schema -- fica fora de escopo por ora,
    # registrado aqui em vez de tentar um fix as pressas que arriscaria
    # dado incorreto silencioso.
    def _bucket(errors):
        buckets = {}
        for e in errors:
            key = e.split(':', 1)[0].strip()
            buckets[key] = buckets.get(key, 0) + 1
        return buckets

    n_off_ok = len(resultados) - len(off_errors)
    n_def_ok = len(resultados) - len(def_errors)
    print(f'\n--- COBERTURA DA AMOSTRA ---')
    print(f'  ofensiva: {_pct(n_off_ok, len(resultados))} logs usados')
    for reason, count in sorted(_bucket(off_errors).items(), key=lambda x: -x[1]):
        print(f'    excluido ({count}x): {reason}')
    print(f'  defesa:   {_pct(n_def_ok, len(resultados))} logs usados')
    for reason, count in sorted(_bucket(def_errors).items(), key=lambda x: -x[1]):
        print(f'    excluido ({count}x): {reason}')

    print(f'\n--- OFENSIVA (turno proprio, {len(off_rows)} turnos) ---')
    for label, key, has_key in [
        ('play (mesmas cartas jogadas)', 'play_match', 'play_has_data'),
        ('attack -- QUEM atacou (mesmo conjunto)', 'attack_quem_match', 'attack_has_data'),
        ('activate (mesmas cartas ativaram)', 'activate_match', 'activate_has_data'),
        ('attach_don -- MESMO alvo recebeu DON', 'don_alvo_match', 'don_has_data'),
    ]:
        base = [r for r in off_rows if r[has_key]]
        n_ok = sum(1 for r in base if r[key])
        print(f'  {label}: {_pct(n_ok, len(base))}  (turnos com dado: {len(base)}/{len(off_rows)})')

    # bloco 650: mesma comparacao, sem o tudo-ou-nada por turno -- soma
    # intersecao/uniao de TODOS os turnos (Jaccard micro-medio). Responde
    # "quanto das cartas certas o motor acertou", nao so "o turno inteiro
    # bateu". Nao substitui as % acima; existe pra que uma melhora PARCIAL
    # (acertar 2 de 3 em vez de 1 de 3) apareca em algum lugar.
    print('  -- mesmas categorias, medidas por SOBREPOSICAO (intersecao/uniao, '
          'credita acerto parcial) --')
    for label, ik, uk in [
        ('play', 'play_inter', 'play_union'),
        ('attack -- QUEM atacou', 'attack_quem_inter', 'attack_quem_union'),
        ('activate', 'activate_inter', 'activate_union'),
        ('attach_don -- alvo', 'don_alvo_inter', 'don_alvo_union'),
    ]:
        if any(uk in r for r in off_rows):
            i = sum(r.get(ik, 0) for r in off_rows)
            u = sum(r.get(uk, 0) for r in off_rows)
            print(f'     {label}: {_pct(i, u)}')

    # ── RECORTE POR LIDER (bloco 652, pedido explicito e REPETIDO do
    # usuario: "o bot nao pode so jogar bem de imu e mal com os outros") ──
    # Existe porque um agregado pode subir puxado por 1 ou 2 lideres de
    # volume alto e esconder lideres parados. Achado real que motivou:
    # depois dos fixes 650/651 o agregado de `play` subiu 10,6pp, mas o
    # recorte mostrou Katakuri OP11-062 (136 turnos, 3o maior volume do
    # banco) andando so +0,7pp e OP13-002 parado em 0,0pp -- invisivel no
    # numero unico. NAO reportar `play` agregado sem olhar esta tabela.
    por_lider = {}
    for r in off_rows:
        lid = r.get('leader')
        if not lid or not r.get('play_has_data'):
            continue
        agg = por_lider.setdefault(lid, [0, 0])
        agg[1] += 1
        if r.get('play_match'):
            agg[0] += 1
    if por_lider:
        print('')
        print('  -- play POR LIDER (>=8 turnos; o agregado pode esconder lider parado) --')
        linhas = sorted(por_lider.items(), key=lambda kv: -kv[1][1])
        for lid, (ok, tot) in linhas:
            if tot < 8:
                continue
            print(f'     {lid:<14} {_pct(ok, tot):<16} ({tot} turnos)')
        poucos = sum(1 for _, (_, t) in linhas if t < 8)
        if poucos:
            print(f'     ({poucos} lider(es) com <8 turnos omitidos)')

    total_common = sum(r['attack_alvo_common'] for r in off_rows)
    total_alvo_ok = sum(r['attack_alvo_match'] for r in off_rows)
    print(f'  attack -- MESMO ALVO (dos atacantes em comum): {_pct(total_alvo_ok, total_common)}')

    seq_base = [r for r in off_rows if r['seq_has_data']]
    seq_exact_ok = sum(1 for r in seq_base if r['seq_exact_match'])
    print(f'  SEQUENCIA -- identica start-a-fim: {_pct(seq_exact_ok, len(seq_base))}')
    total_lcs = sum(r['seq_lcs'] for r in off_rows)
    total_maxlen = sum(r['seq_maxlen'] for r in off_rows)
    print(f'  SEQUENCIA -- similaridade (LCS/maior sequencia): {_pct(total_lcs, total_maxlen)}')

    total_alvo_ef_common = sum(r['alvo_efeito_common'] for r in off_rows)
    total_alvo_ef_ok = sum(r['alvo_efeito_match'] for r in off_rows)
    print(f'  ALVO dentro do efeito (so quando ambos jogaram a MESMA carta, best-effort via narrativa): '
          f'{_pct(total_alvo_ef_ok, total_alvo_ef_common)}')

    print(f'\n--- DEFESA (turno do oponente, {len(def_rows)} ataques sofridos) ---')
    n = len(def_rows)
    blocker_ok = sum(1 for r in def_rows if r['hist_blocked'] == r['engine_blocked'])
    print(f'  blocker (bloquear ou nao): {_pct(blocker_ok, n)}')
    both_blocked = [r for r in def_rows if r['hist_blocked'] and r['engine_blocked']]
    blocker_card_ok = sum(1 for r in both_blocked if r['hist_blocker_card'] == r['engine_blocker_card'])
    print(f'  blocker -- MESMA CARTA (quando os 2 bloquearam): {_pct(blocker_card_ok, len(both_blocked))}')

    not_blocked = [r for r in def_rows if not r['hist_blocked'] and not r['engine_blocked']]
    counter_ok = sum(1 for r in not_blocked if r['hist_countered'] == r['engine_countered'])
    print(f'  counter (usar ou nao, so quando NAO bloqueou): {_pct(counter_ok, len(not_blocked))}')
    both_countered = [r for r in not_blocked if r['hist_countered'] and r['engine_countered']]
    cartas_ok = sum(1 for r in both_countered if set(r['hist_counter_codes']) == set(r['engine_counter_codes']))
    print(f'  counter -- MESMO CONJUNTO de cartas: {_pct(cartas_ok, len(both_countered))}')
    multi = [r for r in both_countered if len(r['hist_counter_codes']) > 1 or len(r['engine_counter_codes']) > 1]
    ordem_ok = sum(1 for r in multi if r['hist_counter_codes'] == r['engine_counter_codes'])
    print(f'  counter -- MESMA ORDEM (quando 2+ cartas): {_pct(ordem_ok, len(multi))}')

    # Bloco 683: run com `--limit` NUNCA sobrescreve `ultimo_resultado.json`.
    # Achado na pratica no mesmo dia: os dois lados de um A/B com --limit 70
    # sobrescreveram o resultado do corpus INTEIRO, deixando no repositorio
    # um arquivo que parece ser dos 274 lados e e de 70 -- armadilha certeira
    # pra uma sessao futura comparar contra ele sem saber. Subconjunto grava
    # em arquivo proprio, com o N no nome.
    nome = (f'parcial_limit{args.limit}.json' if args.limit
            else 'ultimo_resultado.json')
    out_path = os.path.join(OUT_DIR, nome)
    json.dump({'offense': off_rows, 'defense': def_rows}, open(out_path, 'w', encoding='utf-8'),
              indent=2, ensure_ascii=False)
    print(f'\nResultado completo salvo em {out_path}')


if __name__ == '__main__':
    main()
