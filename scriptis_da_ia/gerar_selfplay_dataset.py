"""
gerar_selfplay_dataset.py
=========================
Gera o dataset de AUTO-JOGO que treina a funcao de valor
(`optcg_engine/value_net.py` -> `treinar_value.py`).

Decisao do usuario (08/09/2026): caminho HIBRIDO, atras de flag.

O QUE ISTO PRODUZ, E POR QUE E DIFERENTE DO QUE JA FOI REPROVADO
-----------------------------------------------------------------
Uma linha por ESTADO visitado, com:
  - `feats`  -- vetor de `value_net.state_features(p, opp)` (fonte UNICA,
                a mesma que o motor monta em runtime)
  - `win`    -- 1 se o jogador daquele estado GANHOU a partida, 0 se nao
  - `leader` -- codigo do lider, usado SO como GRUPO na validacao
                (GroupKFold), NUNCA como feature

O rotulo e o RESULTADO DA PARTIDA, nao a escolha de um humano. Por isso
este caminho nao esbarra no que matou a clonagem de comportamento dos
blocos 680-706: o dado e ilimitado (o motor gera) e vem da propria
politica que joga, entao nao ha *distribution shift* por construcao.

O `leader` fora das features e deliberado, e vem de um defeito REAL: o
bloco 702 achou one-hot de lider em `policy.py:98` com split por partida
-- validacao que nunca poderia detectar falha de generalizacao pra deck
novo. Aqui o lider so agrupa o holdout.

PARALELISMO E REPRODUTIBILIDADE
-------------------------------
`--workers N` (convencao obrigatoria do projeto pra simulacao em lote).
Cada partida usa seed PROPRIA derivada por indice (`seed * 1_000_003 + i`)
-- nunca um `random.seed()` unico encadeado entre partidas, que quebra a
reprodutibilidade entre sequencial e paralelo (achado real do bloco 481).

Uso:
  python gerar_selfplay_dataset.py --n 200 --workers 4
  python gerar_selfplay_dataset.py --n 1000 --workers 8 --out metrics/selfplay_dataset.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Reprodutibilidade real (mesmo preambulo de baseline_metrics.py):
# PYTHONHASHSEED precisa existir antes do interpretador subir.
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    raise SystemExit(subprocess.call([sys.executable] + sys.argv))

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

from optcg_engine.decision_engine import (OPTCGMatch, build_real_deck,
                                          load_cards_db, validar_deck)
from optcg_engine import value_net

OUT_DEFAULT = 'metrics/selfplay_dataset.jsonl'

_DECK_CACHE: list | None = None


def _load_deck_list(limite: int = 64) -> list:
    """Decks REAIS de torneio (`decklists_raw.csv`), mesma fonte de
    `audit_replay.py`. Variedade de lider importa aqui mais que em
    qualquer outro script: o objetivo registrado do projeto e jogar bem
    com QUALQUER deck, e a validacao agrupa POR LIDER -- com poucos
    lideres o GroupKFold nao tem o que separar."""
    global _DECK_CACHE
    if _DECK_CACHE is not None:
        return _DECK_CACHE
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    deck_list = []
    vistos = set()
    for url, name in urls.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if not result:
            continue
        leader, cards, start_stage = result
        valido, _erros = validar_deck(leader, cards, cards_db)
        if not valido or len(cards) < 40:
            continue
        code = getattr(leader, 'code', None) or str(name)
        # 1 deck por lider: o dataset ganha mais com 24 lideres distintos
        # do que com 24 listas do mesmo lider (o holdout e por lider).
        if code in vistos:
            continue
        vistos.add(code)
        deck_list.append((code, (leader, cards, start_stage)))
        if len(deck_list) >= limite:
            break
    # DECKS DO SIMULADOR (bloco 934, pedido do usuario): o arquivo de torneio so
    # tem 16 LIDERES distintos (184 decks concentrados em poucos lideres), e o
    # objetivo do projeto e jogar bem com QUALQUER deck. A pasta de `.deck` do
    # simulador soma 26 lideres que o CSV nao tem (42 no total) e cartas que
    # nenhum deck de torneio usa. Mesmo carregador e mesma validacao do resto
    # (`sim_bridge.load_sim_deck`, `validar_deck`), 1 deck por lider.
    try:
        from optcg_engine import sim_bridge as _sb
        for _code, _nome in sorted(_sb._leader_deck_index_build().items()):
            if len(deck_list) >= limite:
                break
            try:
                _leader, _cards, _stage = _sb.load_sim_deck(_nome)
            except Exception:
                continue
            _ok, _erros = validar_deck(_leader, _cards, cards_db)
            if _ok and len(_cards) >= 40:
                deck_list.append((_code, (_leader, _cards, _stage)))
    except Exception:
        pass       # sem a pasta do simulador (outra maquina) fica so o CSV
    _DECK_CACHE = deck_list
    return deck_list


def _quem_joga(match, turn_num):
    p = (match.state_a if match.state_a.is_first else match.state_b) \
        if turn_num % 2 == 0 \
        else (match.state_b if match.state_a.is_first else match.state_a)
    return p, (match.state_b if p is match.state_a else match.state_a)


def _foto(match):
    """Copia do jogo inteiro no inicio de um turno, SEM as capturas (as listas
    crescem e nao pertencem ao ramo da revisao)."""
    from copy import deepcopy
    guarda = {k: getattr(match, k) for k in ('_q_captura', '_ml_captura')
              if hasattr(match, k)}
    for k in guarda:
        setattr(match, k, None)
    try:
        return deepcopy(match)
    finally:
        for k, v in guarda.items():
            setattr(match, k, v)


def _joga(match, inicio, i, code_a, code_b, geracao, guardar=False):
    """Joga do turno `inicio` ate o fim. Devolve (amostras, vencedor, fotos);
    amostras None se a partida estourou. `fotos[t]` = copia no inicio do turno t."""
    amostras, winner, fotos = [], None, {}
    match._ini_turno = {}
    for turn_num in range(inicio, match.MAX_TURNS * 2):
        p, opp = _quem_joga(match, turn_num)
        match._ini_turno[turn_num] = len(getattr(match, '_q_captura', None) or [])
        if guardar:
            try:
                fotos[turn_num] = _foto(match)
            except Exception:
                guardar, fotos = False, {}
        try:
            result = match.play_turn(p, opp)
        except Exception:
            # Partida que estoura no meio ainda tem estados validos ate
            # aqui, mas NAO tem rotulo confiavel -- descarta inteira.
            return None, None, None
        # Estado no FIM do meu turno: o ponto que a regua julga.
        lado = 'A' if p is match.state_a else 'B'
        amostras.append({
            'match': i, 'side': lado,
            'leader': code_a if lado == 'A' else code_b,
            'turn': turn_num,
            # `gen` = qual geracao do modelo jogou esta partida.
            'gen': geracao,
            # SUPERCONJUNTO rico; o treino escolhe o subconjunto (bloco 764).
            'feats': value_net.state_features(p, opp, nomes=value_net.FEATURE_NAMES_V3),
        })
        if result:
            winner = result
            break
    return amostras, winner, fotos


def _turnos_do_erro(fotos, lado, match, k=1):
    """Os `k` turnos do `lado` em que a posicao dele mais caiu ate o turno
    seguinte dele (regua do ciclo, ja com a resposta do oponente). So quedas
    positivas; maior queda primeiro."""
    try:
        from optcg_engine.decision_engine import MODELO_ORDENA_PATH as _MOP
        rg = value_net.load_value_net(
            getattr(match.state_a, 'modelo_ordena_path', None) or _MOP)
        if not rg:
            return []
        mod = rg['modelo']
        meus, linhas = [], []
        for t in sorted(fotos):
            f = fotos[t]
            p, opp = _quem_joga(f, t)
            if ('A' if p is f.state_a else 'B') != lado:
                continue
            meus.append(t)
            linhas.append(value_net.state_features(p, opp, nomes=value_net.FEATURE_NAMES_ALUNO))
        if len(meus) < 2:
            return []
        import numpy as np
        X = np.asarray(linhas, dtype=float)
        v = mod.predict_proba(X)[:, 1] if hasattr(mod, 'predict_proba') else mod.predict(X)
        quedas = sorted(((v[j] - v[j + 1], meus[j]) for j in range(len(v) - 1)), reverse=True)
        return [t for q, t in quedas[:k] if q > 0]
    except Exception:
        return []


EPS_REVISAO = 0.5   # exploracao no turno revisto (ponto de partida, nao calibrado)


def _revisa(foto, t_erro, id_rev, code_a, code_b, geracao, eps, seed):
    """Rejoga a partida a partir do turno do erro tentando outras jogadas
    naquele turno, e segue ate o fim. Devolve (amostras, linhas Q, vencedor)."""
    from copy import deepcopy
    try:
        m = deepcopy(foto)
    except Exception:
        return None
    random.seed(seed)
    m._q_captura = []
    if hasattr(m, '_ml_captura'):
        m._ml_captura = []
    m._explora_eps = max(eps or 0.0, EPS_REVISAO)
    p, opp = _quem_joga(m, t_erro)
    try:
        r = m.play_turn(p, opp)
    except Exception:
        return None
    n_turno = len(m._q_captura or [])
    m._explora_eps = eps
    lado = 'A' if p is m.state_a else 'B'
    am = [{'match': id_rev, 'side': lado, 'leader': code_a if lado == 'A' else code_b,
           'turn': t_erro, 'gen': geracao,
           'feats': value_net.state_features(p, opp, nomes=value_net.FEATURE_NAMES_V3)}]
    if r:
        w = r
    else:
        resto, w, _ = _joga(m, t_erro + 1, id_rev, code_a, code_b, geracao)
        if resto is None or w is None:
            return None
        am += resto
    return am, list(m._q_captura or []), w, n_turno


def _run_one_match(task) -> list:
    """Roda 1 partida de auto-jogo e devolve as amostras dela.

    Cada processo carrega o proprio banco -- sem estado global
    compartilhado, igual `audit_replay._run_one_match`."""
    # 6o elemento OPCIONAL (bloco 767): epsilon de EXPLORACAO.
    if len(task) == 9:
        (i, match_seed, peso, modelo_path, geracao, eps, pos_acao,
         ml_avaliador, modelo_decide) = task
        q_out = True
    else:
        i, match_seed, peso, modelo_path, geracao = task
        modelo_decide = None
        q_out = False
        eps, pos_acao, ml_avaliador = 0.0, False, False
    deck_list = _load_deck_list()
    rng = random.Random(match_seed)
    idx_a, idx_b = rng.sample(range(len(deck_list)), 2)
    code_a, deck_a = deck_list[idx_a]
    code_b, deck_b = deck_list[idx_b]

    # O motor usa `random.*` GLOBAL pra amostragem Monte Carlo/decisoes
    # internas -- precisa da mesma seed por partida, nao so o rng.sample
    # acima (que so escolhe o matchup).
    random.seed(match_seed)

    try:
        match = OPTCGMatch(deck_a, deck_b)
        match.setup()
    except Exception:
        return []

    # ── O PONTO DA ITERACAO ─────────────────────────────────────────────
    # As partidas sao jogadas COM o modelo da geracao atual ligado (nos
    # dois lados). E o que distingue este laco da tentativa de tiro unico
    # do bloco 753: la o dataset veio de partidas do motor SEM o modelo, e
    # o modelo foi usado COM ele -- treino e uso em distribuicoes
    # diferentes. Aqui cada geracao aprende sobre os estados que ela mesma
    # produz, que e a correcao classica desse problema.
    # QUAL MODELO DECIDE (bloco 785). Desde que o Monte Carlo saiu, quem
    # decide e a busca determinística com a rede na folha, e o modelo dela vem
    # de `modelo_ordena_path` -- NAO de `value_net_path`/`value_net_weight`,
    # que sao do desenho antigo (modelo somado a pontuacao, peso default 0,0).
    # Sem passar isto, o gerador jogava sempre com o arquivo global, e
    # retreinar no meio do laco nao mudava nada em quem estava jogando.
    if modelo_decide:
        for estado in (match.state_a, match.state_b):
            estado.modelo_ordena_path = modelo_decide

    if peso:
        for estado in (match.state_a, match.state_b):
            estado.value_net_weight = peso
            estado.value_net_path = modelo_path

    # POOL DE ADVERSARIOS (21/09/2026, pesquisa externa: self-play so contra
    # a versao ATUAL do campeao arrisca ciclo fechado -- o modelo aprende
    # truques que so funcionam contra si mesmo, sem ninguem perceber porque o
    # auto-jogo e cego a esse vicio por construcao (mesmo achado ja registrado
    # no projeto sobre o guarda-corpo). Literatura recomenda sortear entre
    # versoes PASSADAS do modelo, nao so a atual.
    #
    # Config por ENV (nao pela tupla posicional da task) -- mesmo padrao ja
    # usado por `_origem_padrao()`/`OPTCG_ORIGEM`: workers sao processos
    # filhos e herdam `os.environ`, entao chega igual sem mexer no contrato
    # de tamanho da tupla (`len(task) == 9`) que outro trecho ja usa pra
    # discriminar chamadas antigas.
    _pool_dir = os.environ.get('OPTCG_POOL_DIR', '').strip()
    _pool_frac = float(os.environ.get('OPTCG_POOL_FRAC', '0') or 0)
    if _pool_dir and _pool_frac > 0:
        _pool_rng = random.Random('pool-%s' % match_seed)
        if _pool_rng.random() < _pool_frac:
            try:
                _candidatos = [f for f in os.listdir(_pool_dir)
                               if f.endswith('.joblib')]
            except Exception:
                _candidatos = []
            if _candidatos:
                _escolhido = os.path.join(
                    _pool_dir, _pool_rng.choice(_candidatos))
                _lado_pool = _pool_rng.choice([match.state_a, match.state_b])
                _lado_pool.q_net_path = _escolhido

    # EXPLORACAO (bloco 767, pedido do usuario: "ele tem que ser capaz de
    # aprender e descobrir e nao so regular"). Sem isto o auto-jogo e um LACO
    # FECHADO: joga sempre a linha que ja considera melhor, entao o dataset so
    # contem o que ele ja fazia e o modelo aprende a prever o resultado das
    # PROPRIAS escolhas -- reforca, nao descobre. Com eps > 0 ele as vezes
    # joga fora do topo e VE no que deu, que e como se descobre que uma linha
    # preterida era boa.
    if eps:
        match._explora_eps = eps

    # CORPUS POS-ACAO (bloco 769). Com o ML como AVALIADOR ele julga a
    # posicao logo APOS a acao, nao no fim do turno -- e o corpus tem que ser
    # gravado nesse MESMO ponto, senao treino e uso ficam em distribuicoes
    # diferentes (o erro do bloco 753). Rende MUITO mais estado por partida:
    # varias acoes por turno, contra um estado por turno no modo antigo.
    if pos_acao:
        match._ml_captura = []

    # GERADOR RAPIDO (bloco 773). O modo ML_AVALIADOR foi REPROVADO como
    # JOGADOR (1x9, bloco 769) mas serve como GERADOR DE DADO: pra aprender a
    # avaliar posicao o que importa e cobrir muitas posicoes com rotulo de
    # vitoria correto, nao que o jogador seja otimo -- AlphaZero comeca de jogo
    # aleatorio. Custa 1,2s por partida contra 16s, entao viabiliza corpus 40x
    # maior.
    # RESSALVA: os estados vem de um jogador mais fraco. Mitigacao: exploracao
    # ligada e rotulo de vitoria REAL.
    if ml_avaliador:
        for estado in (match.state_a, match.state_b):
            estado.ml_avaliador = True
            if modelo_path:
                estado.value_net_path = modelo_path

    # COLETOR DE ALVOS Q (bloco 796): a busca calcula um valor por candidata
    # SIMULANDO aonde cada uma leva -- esse valor e o alvo que o modelo Q
    # aprende a devolver SEM simular. A arvore vira o professor; o Q, o aluno.
    # Marcado como lista => `_busca_determinista` passa a gravar.
    if q_out:
        # COLETAR ALVOS EXIGE O PROFESSOR NO COMANDO (bloco 798).
        #
        # Pego rodando: a primeira geracao do laco produziu 541 estados e
        # **ZERO alvos Q**. Causa: o Q agora DECIDE, entao ele responde antes e
        # `_busca_determinista` nunca roda -- e e a busca quem calcula o valor
        # por candidata, que E o alvo. O aluno substituiu o professor, e o
        # professor parou de ensinar.
        #
        # Entao, quando a partida existe pra COLETAR, o Q sai do comando e a
        # arvore decide. E o padrao de destilacao de busca: a busca gera o
        # dado, o modelo joga com ele.
        # No modo BOOTSTRAP (default, bloco 799) o alvo NAO vem da busca --
        # vem do estado que a acao produz. Entao o Q pode continuar decidindo
        # enquanto coleta, e a partida custa o que custa jogar.
        # Bloco 811: nem o modo 'busca' pede a arvore no comando. Ela roda
        # pra ENSINAR (produzir o alvo) e quem decide e o Q, sempre -- entao
        # nao ha mais nada pra desligar aqui.
        match._q_captura = []

    revisoes = int(os.environ.get('OPTCG_REVISOES', '2') or 0) if q_out else 0
    amostras, winner, fotos = _joga(match, 0, i, code_a, code_b, geracao,
                                    guardar=bool(revisoes))
    if amostras is None:
        return []
    if winner is None:
        # Sem desfecho (estourou MAX_TURNS) -- sem rotulo, fora do dataset.
        # Contado no resumo pra a taxa ficar visivel, nao escondida.
        return [{'_sem_desfecho': True, 'match': i}]

    if pos_acao:
        # Troca os estados de FIM DE TURNO pelos estados POS-ACAO que o
        # `_ml_captura` recolheu -- e o ponto onde o ML avaliador e de fato
        # consultado. O rotulo continua sendo quem ganhou a PARTIDA.
        amostras = [{'match': i, 'side': d['lado'],
                     'leader': code_a if d['lado'] == 'A' else code_b,
                     'turn': -1, 'gen': geracao, 'feats': d['feats']}
                    for d in (getattr(match, '_ml_captura', None) or [])]
    for a in amostras:
        a['win'] = 1 if a['side'] == winner else 0
    if q_out:
        for linha in (getattr(match, '_q_captura', None) or []):
            linha['match'] = i
        # REVISAO DA DERROTA (bloco 938, pedido do usuario 05/10/2026): "ao
        # perder, o bot reve onde errou ou tomou desvantagem e tenta entender
        # se outra coisa teria sido melhor". Volta ao turno do perdedor em que
        # a posicao dele mais caiu, joga aquele turno tentando OUTRAS jogadas
        # (exploracao alta so naquele turno) e deixa a partida seguir ate o FIM
        # de verdade. O que acontecer e resultado REAL (nao nota da regua):
        # entra no corpus como uma partida a mais, com as consequencias reais
        # das jogadas diferentes tentadas no ponto do erro.
        # REVISOES (bloco 942, pedido do usuario): os 2 piores turnos do
        # PERDEDOR e o pior do VENCEDOR (ganhou, mas onde jogou pior?), cada um
        # rejogado `OPTCG_REVISOES` vezes ate o fim. MUDOU: quando a revisao
        # termina com resultado diferente da partida original PARA QUEM foi
        # revisto, as jogadas daquele turno -- a original e a nova -- sao o
        # sinal mais direto que existe ("mesmo ponto, jogada diferente,
        # resultado real diferente") e ganham `mudou` (peso maior no treino).
        extra_q = []
        orig = list(getattr(match, '_q_captura', None) or [])
        ini_t = getattr(match, '_ini_turno', {}) or {}
        if revisoes and fotos:
            perdedor = 'B' if winner == 'A' else 'A'
            # SO O LADO QUE ESTA SENDO TREINADO (pedido do usuario): nas partidas
            # contra um adversario do POOL (geracao antiga, `q_net_path` proprio),
            # o lado antigo nao e revisto -- os erros dele nao sao do modelo atual.
            def _treinado(lado):
                st = match.state_a if lado == 'A' else match.state_b
                return not getattr(st, 'q_net_path', None)
            alvos = ([(t, perdedor) for t in _turnos_do_erro(fotos, perdedor, match, k=2)
                      if _treinado(perdedor)]
                     + [(t, winner) for t in _turnos_do_erro(fotos, winner, match, k=1)
                        if _treinado(winner)])
            n_ramo = 0
            for t_erro, lado_rev in alvos:
                for k in range(revisoes):
                    n_ramo += 1
                    id_rev = i + 1_000_000 * n_ramo
                    rev = _revisa(fotos[t_erro], t_erro, id_rev, code_a, code_b,
                                  geracao, eps, match_seed * 7 + n_ramo)
                    if rev is None:
                        continue
                    am_r, q_r, w_r, n_turno = rev
                    for x in am_r:
                        x['win'] = 1 if x['side'] == w_r else 0
                        x['revisao'] = True
                    for linha in q_r:
                        linha['match'] = id_rev
                        linha['revisao'] = t_erro
                    if (w_r == lado_rev) != (winner == lado_rev):
                        for linha in q_r[:n_turno]:
                            linha['mudou'] = True
                        a0 = ini_t.get(t_erro)
                        a1 = ini_t.get(t_erro + 1, len(orig))
                        if a0 is not None:
                            for linha in orig[a0:a1]:
                                linha['mudou'] = True
                    amostras = amostras + am_r
                    extra_q.extend(q_r)
        match._q_captura = list(getattr(match, '_q_captura', None) or []) + extra_q
        # Uma vez por PARTIDA, nao por linha. Vem do ambiente/hostname em vez
        # de viajar na task: a tupla e checada por TAMANHO (`len(task) == 9`) e
        # estender isso quebraria o outro caminho em silencio. Workers sao
        # processos filhos e herdam `os.environ`, entao o valor chega igual.
        _org = _origem_padrao()
        # QUAL MODELO decidiu esta linha (bloco 913, INSTRUCAO_MESTRA item 21):
        # hash do Q de cada lado -- o campeao ou um adversario do pool.
        # `geracoes.id_do_hash` traduz pra `generation_NNN`.
        from optcg_engine.decision_engine import Q_NET_PATH as _QP
        import geracoes as _ger
        _hash_lider = {}
        for _st in (match.state_a, match.state_b):
            _hash_lider.setdefault(getattr(_st.leader, 'code', None),
                                   _ger.hash_arquivo(getattr(_st, 'q_net_path', None) or _QP))
        for linha in (getattr(match, '_q_captura', None) or []):
            linha['gen'] = geracao
            linha['modelo'] = _hash_lider.get(linha.get('leader'))
            # DE QUAL MAQUINA veio esta linha (bloco 820, pedido do usuario ao
            # planejar gerar corpus em DUAS maquinas em paralelo).
            #
            # Sem isso, uma duplicata futura e INDIAGNOSTICAVEL: da pra ver que
            # a posicao repete, nao de onde veio a copia. Custo real ja medido:
            # em 13/09 o ciclo se re-executou sozinho e entraram 9.865 alvos
            # que eram 100% repeticao -- so deu pra separar porque havia UMA
            # origem e o corte era o fim do arquivo. Com duas maquinas
            # escrevendo, esse corte nao existe.
            #
            # O risco concreto do paralelismo: a seed de cada partida e
            # `seed * 1_000_003 + i`, entao duas maquinas com a MESMA --seed
            # geram as MESMAS partidas. Concatenar ai nao soma dado, duplica.
            linha['origem'] = _org
        # VANTAGEM de cada jogada escolhida, gravada na linha (bloco 932).
        try:
            import treinar_q as _tq
            from optcg_engine import value_net as _vn
            from optcg_engine.decision_engine import MODELO_ORDENA_PATH as _MOP
            _rp = getattr(match.state_a, 'modelo_ordena_path', None) or _MOP
            _tq.grava_vantagem(match._q_captura or [], amostras, _vn.load_value_net(_rp),
                               _ger.hash_arquivo(_rp))
        except Exception:
            pass          # sem regua/trajetoria a linha segue sem os campos; nunca derruba a partida
        return amostras, list(getattr(match, '_q_captura', None) or [])
    return amostras, []


def _origem_padrao() -> str:
    """Identidade desta maquina no corpus. `OPTCG_ORIGEM` manda; senao o
    hostname, que ja distingue as maquinas sem ninguem precisar configurar."""
    import os as _os
    import socket as _socket
    marca = (_os.environ.get('OPTCG_ORIGEM') or '').strip()
    if marca:
        return marca
    try:
        return _socket.gethostname() or 'desconhecida'
    except Exception:
        return 'desconhecida'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n', type=int, default=200, help='partidas de auto-jogo')
    ap.add_argument('--seed', type=int, default=77)
    ap.add_argument('--workers', type=int, default=__import__('multiprocessing').cpu_count() - 3,
                    help='processos paralelos (o projeto EXIGE escolher explicitamente)')
    ap.add_argument('--decks', type=int, default=24, help='quantos lideres distintos')
    ap.add_argument('--out', default=OUT_DEFAULT)
    ap.add_argument('--weight', type=float, default=0.0,
                    help='peso do valor aprendido nas partidas GERADAS '
                         '(0 = motor sem modelo, geracao 0)')
    ap.add_argument('--q-out', dest='q_out', default=None,
                    help='grava tambem os ALVOS Q (estado+acao -> valor da busca) '
                         'neste arquivo. E o corpus do modelo que substitui a '
                         'arvore (bloco 796).')
    ap.add_argument('--modelo-decide', dest='modelo_decide', default=None,
                    help='modelo que DECIDE (folha da busca determinística). '
                         'Default: o arquivo global MODELO_ORDENA_PATH.')
    ap.add_argument('--model', default=None,
                    help='modelo usado pra gerar (default: o de value_net.MODEL_PATH)')
    ap.add_argument('--ml-avaliador', dest='ml_avaliador', action='store_true',
                    help='gera com o modo ML_AVALIADOR (1,2s por partida em vez '
                         'de 16s). REPROVADO como jogador (1x9, bloco 769) mas '
                         'valido como GERADOR: o que importa pro aprendizado e '
                         'cobrir posicoes com rotulo correto (bloco 773)')
    ap.add_argument('--pos-acao', dest='pos_acao', action='store_true',
                    help='grava os estados POS-ACAO (o ponto onde o ML '
                         'AVALIADOR e consultado) em vez do fim do turno. '
                         'Rende varios estados por turno. Obrigatorio pra '
                         'treinar o modelo do ML_AVALIADOR (bloco 769)')
    # LIGADA POR DEFAULT desde o bloco 792. Estava em 0.0 -- ou seja, o bot
    # NUNCA tentava o que ainda nao escolheria, e o auto-jogo era eco: o corpus
    # so continha o que ele ja fazia. Isso contradizia frontalmente o que o
    # usuario pediu ("o ML vai testando as alternativas e esse criterio vai
    # surgindo"): sem tentar, nada emerge.
    # 0.17 (pedido do usuario, 19/09/2026). Desde o bloco 913 so explora onde
    # o modelo esta INCERTO (INSTRUCAO_MESTRA_ML item 7): a geracao nao pode
    # ser um bot pior -- ver `_explorar` em decision_engine.py.
    ap.add_argument('--explorar', type=float, default=0.30,
                    help='epsilon de EXPLORACAO: em epsilon das decisoes sorteia '
                         'SO entre as candidatas que o modelo nao distingue da '
                         'melhor (dentro do erro fora da amostra dele). Onde ele '
                         'tem certeza, joga como o bot real. NAO usar em duelo.')
    ap.add_argument('--gen', type=int, default=0, help='numero da geracao, gravado em cada amostra')
    ap.add_argument('--append', action='store_true',
                    help='ACRESCENTA ao arquivo em vez de sobrescrever -- '
                         'o corpus cresce a cada rodada')
    ap.add_argument('--pool-dir', dest='pool_dir', default=None,
                    help='pasta com snapshots .joblib de versoes PASSADAS do '
                         'Q (21/09/2026) -- com --pool-frac>0, uma fracao das '
                         'partidas poe um adversario sorteado dessa pasta em '
                         'vez do campeao atual dos dois lados. Evita self-play '
                         'ficar sempre modelo-atual-contra-modelo-atual.')
    ap.add_argument('--pool-frac', dest='pool_frac', type=float, default=0.0,
                    help='fracao das partidas (0.0-1.0) que sorteiam um lado '
                         'do --pool-dir. Default 0.0 (desligado).')
    args = ap.parse_args()

    if args.pool_dir and args.pool_frac > 0:
        os.environ['OPTCG_POOL_DIR'] = args.pool_dir
        os.environ['OPTCG_POOL_FRAC'] = str(args.pool_frac)

    tasks = [(i, args.seed * 1_000_003 + i, args.weight, args.model, args.gen,
              args.explorar, args.pos_acao, args.ml_avaliador, args.modelo_decide)
             for i in range(args.n)]
    print(f'[selfplay] {args.n} partidas, seed={args.seed}, workers={args.workers}, '
          f'gen={args.gen}, peso={args.weight}, explorar={args.explorar}')

    resultados = []
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for k, r in enumerate(ex.map(_run_one_match, tasks), 1):
                resultados.append(r)
                if k % 25 == 0:
                    print(f'  ... {k}/{args.n}')
    else:
        for k, t in enumerate(tasks, 1):
            resultados.append(_run_one_match(t))
            if k % 25 == 0:
                print(f'  ... {k}/{args.n}')

    linhas, sem_desfecho, vazias = [], 0, 0
    q_linhas = []
    for r in resultados:
        if not (r[0] if isinstance(r, tuple) else r):
            vazias += 1
            continue
        if len(r) == 1 and r[0].get('_sem_desfecho'):
            sem_desfecho += 1
            continue
        linhas.extend(r[0] if isinstance(r, tuple) else r)
        if args.q_out and isinstance(r, tuple):
            q_linhas.extend(r[1])

    if args.q_out and q_linhas:
        qp = Path(args.q_out)
        qp.parent.mkdir(parents=True, exist_ok=True)
        with qp.open('a' if args.append else 'w', encoding='utf-8') as fh:
            for a in q_linhas:
                fh.write(json.dumps(a, ensure_ascii=False) + chr(10))
        print(f'[selfplay] {len(q_linhas)} alvos Q -> {qp}')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('a' if args.append else 'w', encoding='utf-8') as fh:
        for a in linhas:
            fh.write(json.dumps(a, ensure_ascii=False) + '\n')

    lideres = sorted({a['leader'] for a in linhas})
    vitorias = sum(a['win'] for a in linhas)
    print(f'\n[selfplay] {len(linhas)} estados de {args.n - sem_desfecho - vazias} '
          f'partidas com desfecho -> {out}')
    print(f'  partidas sem desfecho (MAX_TURNS): {sem_desfecho}')
    print(f'  partidas descartadas por erro:     {vazias}')
    print(f'  lideres distintos:                 {len(lideres)}')
    print(f'  taxa de rotulo positivo:           {vitorias / max(1, len(linhas)):.1%}')


if __name__ == '__main__':
    main()
