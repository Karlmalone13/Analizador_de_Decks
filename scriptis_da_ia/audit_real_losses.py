"""
Auditoria de derrota real: reconstrói o estado do jogo em cada turno do BOT
numa derrota REAL (log de partida contra humano, `logs/parsed/*.json`) e
pergunta pro motor de HOJE (`decision_engine.py`, fonte única — chama
`OPTCGMatch.play_turn()` de verdade, não reimplementa decisão nenhuma) o
que ele faria. Compara com o que o bot fez de verdade na época.

Criado 04/08/2026 a pedido do usuário: em vez de forçar uma linha de jogo
fixa (que quebra se a mão/board divergir), usa o HISTÓRICO REAL como
ground truth e o motor ATUAL como "segunda opinião" sobre cada decisão —
ferramenta permanente, ver CLAUDE.md/AGENTS.md ("Auditoria de derrotas
reais contra humano").

Limitações honestas (documentadas, não escondidas):
- `don_available` é uma RECONSTRUÇÃO best-effort (soma don_drawn por turno,
  subtrai custo de play/activate conhecido via cards_db/card_effects_db e
  os `attach_don` registrados) — pode divergir do valor real em jogos
  longos ou com efeitos que dão/tiram DON de formas não capturadas pelo
  parser. Sinalizado no relatório como `don_available_estimado`.
- O deck restante (cartas ainda não vistas) é aproximado: pega um deck
  REAL do mesmo líder em `decklists_raw.csv`, remove o que já apareceu em
  mão/campo/trash/vida, embaralha o resto — a COMPOSIÇÃO é real, a ORDEM
  não é (não tem como saber a ordem real do deck a partir do log).
- Mão do oponente é tratada com informação COMPLETA (mesmo padrão que o
  self-play/gauntlet já usa hoje — `self_play_info_hidden` nunca é ligado
  em lugar nenhum do projeto ainda), não mascarada como o caminho ao vivo
  faz. Ou seja: o motor aqui tem mais informação do oponente do que o bot
  real teve ao vivo — resultado tende a ficar "melhor" que o bot real
  teria conseguido nessa exata situação, não pior.
- Primeiro turno de cada jogador é pulado (não dá pra reconstruir o
  "antes" sem o snapshot da mão inicial, que não é registrado).

Uso:
    python audit_real_losses.py --log <caminho_do_parsed.json>
    python audit_real_losses.py --all [--limit N]
    python audit_real_losses.py --list   # só lista as derrotas reais disponíveis
"""
import argparse
import contextlib
import io
import json
import os
import glob
import re
import random
from collections import Counter
from copy import deepcopy

import pandas as pd

from optcg_engine.decision_engine import (
    Card, GameState, load_cards_db, build_real_deck, validar_deck,
    populate_full_deck_knowledge, get_card_effects, _make_card,
)
from replay_optcg import ReplayMatch
import sim_deck_registry

# Bloco 688: permite IGNORAR os campos RZ1 (bloco 684) e cair no caminho
# de estimativa antigo. Existe pra medir o EFEITO da fidelidade nos MESMOS
# logs -- sem isso nao da pra separar "o motor melhorou" de "o log
# melhorou", que e a comparacao que importa depois do bloco 684.
IGNORAR_RZ1 = os.environ.get('OPTCG_IGNORE_RZ1', '') == '1'

LOGS_DIR = 'logs'
INDEX_PATH = os.path.join(LOGS_DIR, 'index.json')
OUT_DIR = os.path.join('metrics', 'real_loss_audits')


def find_real_bot_losses():
    """Retorna [(parsed_file, bot_side)] pras derrotas reais do bot (You)
    contra humano (Opponent), na convenção já usada no projeto (bloco 432)."""
    idx = json.load(open(INDEX_PATH, encoding='utf-8'))
    out = []
    for e in idx:
        p1, p2 = e.get('p1', {}), e.get('p2', {})
        n1, n2 = p1.get('name', ''), p2.get('name', '')
        winner = e.get('winner')
        pf = e.get('parsed_file')
        if not pf:
            continue
        if n1 == 'You' and n2 == 'Opponent' and winner == 'p2':
            out.append((pf, 'You'))
        elif n2 == 'You' and n1 == 'Opponent' and winner == 'p1':
            out.append((pf, 'You'))
    return out


def _cards_from_codes(codes, cards_db, rested_map=None):
    rested_map = rested_map or {}
    out = []
    for code in codes:
        data = cards_db.get(code)
        if not data:
            continue
        card = _make_card(code, data)
        card.rested = bool(rested_map.get(code))
        out.append(card)
    return out


_DEPLOY_CODE_RE = re.compile(r'"([A-Za-z0-9\-]+)">')


def _field_stage_at(turns, upto_index, side, cards_db):
    """Reconstrói qual STAGE o jogador `side` tinha em campo ANTES do turno
    `upto_index`.

    Achado real 23/08 (bloco 650): o snapshot do log NÃO tem zona de Stage
    -- o plugin só emite `Hand:`/`Board:`/`Trash:`/`Life:`, e `Board:` traz
    só personagens (confirmado: `OP13-099` The Empty Throne nunca aparece em
    NENHUMA linha `Board:` das 150 partidas do banco, mesmo estando em jogo
    e sendo ativada 7 vezes na mesma partida). Sem isto, `p.field_stage`
    ficava SEMPRE None em toda reconstrução -- o motor jogava o turno sem um
    Stage que o humano de fato tinha, e nunca conseguia gerar o
    `[Activate: Main]` dele como candidato.

    A informação existe no histórico, só não no snapshot: uma Stage entra em
    campo por `type: "play"` (da mão) ou por um efeito `Deploy <nome>
    ["CODE">CODE]` de outra carta (ex: o líder Imu OP13-079 implanta a
    Empty Throne). Vale a ÚLTIMA que entrou (a zona tem 1 slot só -- jogar
    outra Stage manda a anterior pro trash) e só se ela não estiver no trash
    do snapshot anterior.

    Limitação aceita: `rested` da Stage não é recuperável do log. Assume
    ATIVA, que é o estado correto no início do turno do próprio dono (a
    refresh phase desvira a Stage junto com o resto) -- que é exatamente o
    momento em que esta reconstrução é usada.
    """
    def _entradas(ts):
        """{codigo_de_stage: indice do turno em que entrou em campo}"""
        out = {}
        for j, t in enumerate(ts):
            if t.get('player') != side:
                continue
            for a in t.get('actions') or []:
                code = a.get('card')
                if (code and cards_db.get(code, {}).get('type') == 'STAGE'
                        and hist_action_kind(a, cards_db) == 'play'):
                    out.setdefault(code, j)
                for eff in a.get('effects') or []:
                    if 'Deploy' not in eff:
                        continue
                    for cand in _DEPLOY_CODE_RE.findall(eff):
                        if cards_db.get(cand, {}).get('type') == 'STAGE':
                            out.setdefault(cand, j)
        return out

    entradas = _entradas(turns)

    # Stage implantada no SETUP (antes do turno 1) -- o parser nao guarda
    # nada de pre-turno-1, entao a entrada dela nao existe em `turns`. Caso
    # real: o lider Imu OP13-079 implanta The Empty Throne OP13-099 logo
    # apos o mulligan ("Imu [...]: Deploy The Empty Throne", linha do log
    # cru ANTES do primeiro turno). Deteccao: a carta e ATIVADA em algum
    # turno mas nunca ENTROU em nenhum -- so pode ter entrado no setup,
    # logo estava em campo desde o inicio. Nao e vazamento de informacao
    # futura: recupera um fato VERDADEIRO sobre o passado (a Stage ja
    # estava la), nao uma decisao que o jogador ainda nao tinha tomado.
    for t in turns:
        if t.get('player') != side:
            continue
        for a in t.get('actions') or []:
            code = a.get('card')
            if (a.get('type') == 'activate' and code
                    and cards_db.get(code, {}).get('type') == 'STAGE'
                    and code not in entradas):
                entradas[code] = -1

    ativas = [(j, c) for c, j in entradas.items() if j < upto_index]
    if not ativas:
        return None
    return max(ativas)[1]


# ── Decks REAIS do simulador (bloco 655) ────────────────────────────────
# Pasta do proprio OPTCGSim, apontada pelo usuario: contem o decklist EXATO
# que cada jogador usou, formato `NxCODIGO` por linha, PRIMEIRA carta = lider.
# 38 dos 39 arquivos tem 51 linhas-carta (lider + 50).
#
# Por que isso importa (medido 23/08, antes deste fix): `_find_real_deck`
# montava o deck por SEMELHANCA DE NOME em `decklists_raw.csv`, e o
# resultado era que **em 97,7% das amostras do OpponentModel pelo menos uma
# carta que o oponente REALMENTE tinha na mao nao existia no baralho que o
# motor assumia que ele jogava**. O motor nao ve demais -- ele modelava o
# oponente ERRADO, o que contamina simulacao do turno dele, estimativa de
# counter e toda decisao de ataque.
#
# Cobertura medida contra `logs/index.json`: **92% dos 300 lados de partida**
# casam por `leader_code` (8% sem, ex: Nami OP11-041). 29,3% tem mais de um
# candidato pro mesmo lider (ex: 4 arquivos "Barba Negra") -- desempatados
# pelas cartas OBSERVADAS daquele jogador naquela partida.
#
# Pasta e LOCAL, nao versionada: sessao remota nao tem acesso e cai no
# fallback antigo em silencio (por isso o retorno None nao e erro).
_SIM_DECKS_DIR = os.environ.get(
    'OPTCG_SIM_DECKS_DIR',
    r'E:\Games\OnePieceSimulador\Builds_Windows\Decks')
_SIM_DECK_RE = re.compile(r'^\s*(\d+)x([A-Za-z0-9\-]+)')
_SIM_DECKS_CACHE = None


def _load_sim_decks():
    """{leader_code: [(nome_arquivo, Counter{codigo: qtd_sem_o_lider})]}"""
    global _SIM_DECKS_CACHE
    if _SIM_DECKS_CACHE is not None:
        return _SIM_DECKS_CACHE
    por_lider = {}
    try:
        arquivos = glob.glob(os.path.join(_SIM_DECKS_DIR, '*.deck'))
    except Exception:
        arquivos = []
    for caminho in arquivos:
        linhas = []
        try:
            with open(caminho, encoding='utf-8', errors='replace') as fh:
                for ln in fh:
                    m = _SIM_DECK_RE.match(ln.strip())
                    if m:
                        linhas.append((m.group(2), int(m.group(1))))
        except OSError:
            continue
        if not linhas:
            continue
        lider = linhas[0][0]
        corpo = Counter()
        for code, qtd in linhas[1:]:
            corpo[code] += qtd
        por_lider.setdefault(lider, []).append(
            (os.path.basename(caminho)[:-5], corpo))
    _SIM_DECKS_CACHE = por_lider
    return por_lider


def _snapshot_do_banco(parsed_path, player_name, cards_db):
    """Decklist COMPLETO gravado na ingestao (`logs/decks_full/`, bloco 656).

    Preferido sobre ler a pasta do simulador na hora: e versionado, funciona
    em sessao remota e nao muda quando o usuario edita/apaga deck no jogo.
    """
    try:
        idx_path = os.path.join(LOGS_DIR, 'index.json')
        with open(idx_path, encoding='utf-8') as fh:
            idx = json.load(fh)
    except (OSError, ValueError):
        return None
    base = os.path.basename(parsed_path)
    for e in idx:
        if os.path.basename(e.get('parsed_file') or '') != base:
            continue
        rel = (e.get('deck_full_files') or {}).get(player_name)
        if not rel:
            return None
        got = sim_deck_registry.carregar_snapshot(LOGS_DIR, rel)
        if not got:
            return None
        leader_code, corpo = got
        data = cards_db.get(leader_code)
        if not data:
            return None
        cards = _cards_from_codes(list(corpo.elements()), cards_db)
        return (_make_card(leader_code, data), cards, None) if cards else None
    return None


def _deck_real_do_simulador(leader_code, cards_db, observed_codes=None):
    """Deck EXATO do simulador pra este lider. Com varios candidatos, escolhe
    o que melhor cobre as cartas OBSERVADAS daquele jogador na partida."""
    escolhido = sim_deck_registry.escolher_deck(leader_code, observed_codes)
    if not escolhido:
        return None
    _nome, corpo = escolhido
    leader_data = cards_db.get(leader_code)
    if not leader_data:
        return None
    leader = _make_card(leader_code, leader_data)
    cards = _cards_from_codes(list(corpo.elements()), cards_db)
    if not cards:
        return None
    return leader, cards, None


def _find_real_deck(leader_name, cards_db, df_raw, urls, leader_code=None,
                    observed_codes=None):
    """Acha QUALQUER deck real (decklists_raw.csv) com o mesmo nome de
    líder do log -- serve só de fonte pra compor o RESTO do deck (ver
    limitações no topo do arquivo). Sem decklist real disponível pra esse
    líder (ex: Marshall D. Teach/Krieg/Kid -- confirmado ausentes do
    decklists_raw.csv em investigação anterior desta sessão), cai num
    deck GENÉRICO (mesma cor do líder, sem fidelidade real) só pra não
    travar a auditoria -- qualidade do reconstruído pra ESSE lado fica
    mais fraca, mas o lado que importa pra auditoria (bot_side) quase
    sempre tem decklist real (Imu/Jinbe/Crocodile confirmados presentes).

    Achado real 17/08 (pedido do usuario, "nao e possivel que isso e o
    maximo que conseguimos" -- fui verificar a fundo em vez de aceitar
    o teto): `deck_name` em decklists_raw.csv usa o NOME CURTO do lider
    ("Red/Blue Aceby You got a bye", "Yellow Luffyby..."), nunca o nome
    COMPLETO da carta que o log usa ("Portgas D. Ace", "Monkey D.
    Luffy"). O match antigo (`leader_name.lower() in name.lower()`) so
    funcionava por acidente pra lideres de UMA palavra so (ex:
    "Crocodile", que E substring de "Black Crocodileby..."). Pra
    QUALQUER lider de nome composto -- a MAIORIA -- nunca batia, mesmo
    com decklists reais fartas disponiveis: confirmado 20 decks de Ace
    e 17 de Luffy no CSV, mas `_find_real_deck('Portgas D. Ace', ...)`
    caia no fallback GENERICO (50 cartas UNICAS, sem sinergia nenhuma
    com o arquetipo real) porque "portgas d. ace" nunca e substring de
    "red/blue aceby...". Confirmado com o banco de 26 partidas: 5 dos 6
    lideres humanos (todos exceto Crocodile) usavam o fallback generico
    -- afetando NAO SO a ordem do deck (ja corrigida nos blocos 596/
    598), mas a COMPOSICAO inteira, incluindo `populate_full_deck_
    knowledge`/`compute_game_plan` (arquetipo, sinergias, plano de jogo
    que o motor usa pra avaliar toda decisao estrategica do turno).

    Fix: tenta o nome COMPLETO primeiro (mantem compatibilidade com
    lideres de uma palavra), e SE isso nao achar nada, tenta a ULTIMA
    palavra significativa do nome (o sobrenome/apelido distintivo que
    os decks reais usam -- "Ace", "Luffy", "Xebec", "Teach", "Kid" --
    confirmado esse padrao em todos os nomes do banco). `validar_deck`
    (chamado logo abaixo, ja existia) continua sendo o guarda-chuva de
    seguranca contra falso-positivo -- um match errado nunca passa."""
    # bloco 655: o deck REAL do simulador vem PRIMEIRO -- ver
    # `_deck_real_do_simulador`. So cai na busca por nome quando nao existe
    # arquivo pra este lider (8% do banco) ou a pasta nao esta acessivel.
    _real = _deck_real_do_simulador(leader_code, cards_db, observed_codes)
    if _real:
        return _real

    def _tentar(termo):
        termo_low = termo.lower()
        for url, name in urls.items():
            if termo_low in name.lower():
                result = build_real_deck(name, url, df_raw, cards_db)
                if not result:
                    continue
                leader, cards, stage = result
                # Achado real 18/08 (bloco 618, censo do banco completo
                # achou Marshall D. Teach reconstruido com o lider NAMI):
                # a busca por substring rodava contra o `deck_name`
                # INTEIRO, que inclui "...by NomeDoJogador" -- pra
                # "Teach" isso batia em "Blue/Yellow Namiby BigTeach"
                # (usuario "BigTeach", nao o lider Teach), um deck de
                # Nami completamente diferente. `validar_deck` (a
                # "rede de seguranca" que o comentario original desta
                # funcao dizia impedir falso-positivo) so confere que o
                # deck e ESTRUTURALMENTE legal -- nunca que o LIDER
                # bate com quem foi buscado. Adicionado o check direto
                # que faltava: se o CODIGO do lider foi passado, o
                # lider do deck encontrado TEM que ser o mesmo -- um
                # match por substring que aponta pro lider errado nunca
                # passa, nao importa quao "valido" o deck errado seja.
                if leader_code and leader.code != leader_code:
                    continue
                valido, _ = validar_deck(leader, cards, cards_db)
                if valido:
                    return leader, cards, stage
        return None

    achou = _tentar(leader_name)
    if achou:
        return achou
    palavras = [w.strip('"().,') for w in leader_name.split()]
    palavras_significativas = [w for w in palavras if len(w) >= 3 and w.lower() not in ('the',)]
    if palavras_significativas:
        achou = _tentar(palavras_significativas[-1])
        if achou:
            return achou
    if leader_code and leader_code in cards_db:
        leader = _make_card(leader_code, cards_db[leader_code])
        # Achado real 14/08 (pedido do usuario: "diversos outros pra gente
        # poder usar" -- investigando a qualidade da reconstrucao, achei um
        # bug real aqui): `color` no banco vem separado por "/" OU por
        # ESPACO dependendo da carta (ex: OP16-080 Teach = "Black Yellow",
        # sem "/"). O split('/')[0] antigo, pra cores espaco-separadas,
        # devolvia a string INTEIRA ("Black Yellow") e nunca batia como
        # substring em nenhuma carta -- candidatos ficava vazio, gerando um
        # deck de 0 CARTAS (fallback quebrado, nao so "generico"). Afeta
        # 65 dos 141 lideres do banco (46%, checado via grep de cores sem
        # "/"), nao so o Teach. Fix: separa por "/" OU espaco (regex) e
        # casa por QUALQUER cor individual, nao a string inteira.
        cores = [c for c in re.split(r'[/\s]+', leader.color or '') if c]
        candidatos = [code for code, d in cards_db.items()
                      if d.get('type') == 'CHARACTER' and cores
                      and any(c in (d.get('color') or '') for c in cores)]
        random.shuffle(candidatos)
        cards = []
        i = 0
        while len(cards) < 50 and candidatos:
            code = candidatos[i % len(candidatos)]
            cards.append(_make_card(code, cards_db[code]))
            i += 1
        return leader, cards, None
    return None


def hist_action_kind(action, cards_db):
    """Classifica UMA acao do log historico em 'play' / 'activate' / None.

    FONTE UNICA desta regra (bloco 650) -- `decision_quality_full._hist_
    kind` chama esta funcao em vez de ter a sua propria copia, e
    `_known_gains_this_turn` usa o mesmo criterio pra saber se a carta saiu
    da MAO neste turno. Ter duas leituras diferentes de "isto foi um play?"
    ja custou dois bugs medidos, ver abaixo.

    O rotulo `type` do log nao mapeia 1:1 nas categorias do motor:
      - `type == 'play'`  -> sempre play.
      - `type == 'activate'` e um GUARDA-CHUVA pra qualquer efeito que nao
        seja play/attack (on_ko, when_attacking, on_play, [Main] de Evento,
        [Activate: Main] de verdade...). Desempate:
          * carta TEM `activate_main` -> activate de verdade (inclusive
            STAGE ja em campo, que continua ativavel turno apos turno).
          * senao, EVENT/STAGE -> so podem sair da MAO, entao e play.
          * senao (CHARACTER/LEADER sem activate_main) -> efeito reativo
            automatico, nao e decisao propria do Turn Planner: None.
    """
    code = action.get('card')
    if not code:
        return None
    if action.get('type') == 'play':
        return 'play'
    if action.get('type') != 'activate':
        return None
    if get_card_effects(code).get('activate_main'):
        return 'activate'
    if cards_db.get(code, {}).get('type') in ('EVENT', 'STAGE'):
        return 'play'
    return None


def _known_gains_this_turn(turn, before_hand_codes, after_hand_codes, cards_db):
    """Achado real 17/08 (pedido do usuario: "e so seguir as cartas que o
    humano tem na mao... se for dar draw e so comprar a mesma carta que
    o humano pegou" -- rejeitando a abordagem anterior de baralho
    embaralhado pra QUALQUER compra dentro do turno simulado).

    Devolve um Counter {codigo: qtd} das cartas que REALMENTE entraram
    na mao do jogador NESTE turno (compra padrao do inicio do turno +
    qualquer "Draw N"/efeito de compra, nomeado ou nao) -- sem precisar
    parsear o texto do efeito, so a diferenca de MULTISET entre a mao
    ANTES (snapshot do turno anterior) e a mao DEPOIS (snapshot deste
    turno, que no schema do log representa o estado ao FINAL do turno):

        ganho = (mao_depois + jogadas_este_turno) - mao_antes

    O `+ jogadas_este_turno` cobre o caso de uma carta comprada E jogada
    no MESMO turno (nunca aparece em "mao_depois" porque saiu de novo,
    sem isso o diff a perderia). Confirmado contra um caso real (Mr. 5
    Draw 2 Card + compra padrao do turno = 3 ganhos, todos SEM nome no
    texto do efeito, so recuperaveis via este diff) -- e o UNICO jeito
    de saber a carta certa quando o efeito nao nomeia (ex: "Draw 2
    Card" generico vs "Reveal and Draw Thousand Sunny [cod]" nomeado).

    Limitacao aceita: se uma carta sai da mao por TRASH-DE-CUSTO (nao
    play, ex: "Trash 1 card from hand" como custo de outro efeito), o
    diff simplesmente nao a conta como ganha (correto) mas TAMBEM nao
    detecta que ela saiu por outro motivo que nao draw -- nao afeta o
    calculo de GANHOS, so poderia mascarar uma perda, irrelevante aqui.
    Ordem entre draws SEM nome no mesmo turno nao e recuperavel (quem
    veio da compra padrao vs de um "Draw N" generico) -- aceito, o
    CONJUNTO exato de cartas ja e a parte que importa pra decisao do
    Turn Planner, nao a ordem de chegada dentro do turno.
    """
    # Achado real 23/08 (bloco 650): contava so `type == 'play'`. Um
    # EVENTO comprado e jogado no MESMO turno aparece no log como
    # `type: 'activate'` (o rotulo guarda-chuva, ver hist_action_kind) --
    # ficava fora de `played`, entao o diff nao via que ele tinha sido
    # ganho: nao esta na mao DEPOIS (saiu) nem entrava como ganho. Efeito
    # pratico: a carta nunca era colocada no topo do deck simulado e o
    # motor NUNCA podia jogar aquilo que o humano jogou -- mismatch
    # garantido. Medido no corpus: 39 EVENTOS nessa situacao. Usa o mesmo
    # classificador do resto do pipeline em vez de um segundo criterio.
    played = Counter(a['card'] for a in turn.get('actions', [])
                     if hist_action_kind(a, cards_db) == 'play')
    return (Counter(after_hand_codes) + played) - Counter(before_hand_codes)


def _remaining_deck(full_cards, seen_codes_with_qty):
    """full_cards: lista de Card (deck completo real, sem líder). Remove
    até a quantidade vista de cada código (mão+campo+trash+vida)."""
    pool = list(full_cards)
    remaining = []
    seen = dict(seen_codes_with_qty)
    for card in pool:
        if seen.get(card.code, 0) > 0:
            seen[card.code] -= 1
            continue
        remaining.append(card)
    random.shuffle(remaining)
    return remaining


class DonEstimator:
    """Reconstrução best-effort de don_available por jogador, turno a
    turno, a partir do stream de ações do log (ver limitações no topo).

    Achado real 04/08 (investigando Bartholomew Kuma OP16-093 nao jogado
    hoje mas jogado no historico, Imu x Jinbe 2026-07-13T22.54.47):
    DON gasto como CUSTO de play/activate (rest_don) NAO e uma perda
    permanente -- regra real do jogo: rest a no ato, mas DESRESTA
    sozinho no refresh phase do PROXIMO turno do dono (igual qualquer
    outra carta descansada). A versao anterior deste estimador subtraia
    esses custos de play/activate como se fossem gasto definitivo (like
    uma mana pool que so encolhe), o que ficava sistematicamente baixo
    demais -- conferido contra o log real: turno 1 (don_drawn=1, gastou
    1 em Saint Shalria) + turno 3 (don_drawn=2) = 3 DON acumulados, e o
    historico JOGOU Bartholomew Kuma custo 3 no turno 3 -- só bate com
    "todo play/activate cost refresca", nao com "gasto e permanente".
    RETIFICACAO 23/08 (bloco 650) -- o paragrafo acima continha uma
    afirmacao ERRADA sobre a regra, e ela custava DON em toda
    reconstrucao. A versao anterior dizia que o DON anexado via
    `attach_don` "gruda no personagem ate ele sair de campo, nao volta
    sozinho no refresh" e subtraia `attached` de forma CUMULATIVA e
    PERMANENTE pelo jogo inteiro. A regra oficial diz o oposto
    (`_referencias/regras_do_jogo/rule_comprehensive.pdf`, Refresh
    Phase):

        6-2-3. "Return all DON!! cards given to cards in your Leader area
               and Character area to your cost area and rest them."
        6-2-4. "Set all rested cards placed in your Leader area, Character
               area, Stage area, and cost area as active."

    Ou seja: no inicio do PROPRIO turno todo DON anexado volta pro cost
    area E fica ativo -- exatamente o instante que esta reconstrucao
    modela. E o MESMO erro conceitual que ja tinha sido achado e
    corrigido em 04/08 pros custos de play/activate; o ramo de
    `attach_don` ficou pra tras com o modelo errado, defendido por essa
    frase sobre a regra que nao se sustenta no texto oficial.

    Medido no banco antes do fix: o estimador escondia em media 1,2 a 2,1
    DON por turno a partir do 4o turno de cada jogador (pico no 6o), com
    casos extremos de 11 DON reais reportados como 0. O motor recebia um
    estado de recurso progressivamente mais pobre quanto mais longa a
    partida -- justo onde estao as jogadas caras.

    Limitacao que CONTINUA valendo: DON entregue ao OPONENTE (`give_don_
    opp`) sai do proprio pool de verdade, mas o schema do log so registra
    `attach_don` (confirmado: e o unico `type` com "don" em 80 logs
    amostrados), entao esse caso nao e rastreavel aqui."""

    def __init__(self):
        self.drawn = {}

    def apply_turn(self, player, turn, cards_db):
        self.drawn.setdefault(player, 0)
        self.drawn[player] += turn.get('don_drawn', 0) or 0

    def available(self, player):
        # Teto do cost area = tamanho do DON!! deck (GameState.don_deck=10).
        return max(0, min(10, self.drawn.get(player, 0)))

    def deck_left(self, player):
        """Quantos DON ainda restam no DON!! deck deste jogador.

        Achado real 23/08 (bloco 651): a reconstrucao setava
        `p.don_available` mas deixava `p.don_deck` no valor de partida (10),
        entao a `don_phase` do turno simulado sacava +2 EM CIMA do total ja
        acumulado -- o motor chegava a jogar turnos tardios com **12 DON**,
        acima do maximo fisico do jogo. Sem isto o estado tardio fica
        generoso demais e as decisoes caras do fim de partida nao
        correspondem ao que o humano tinha."""
        return max(0, 10 - self.drawn.get(player, 0))


def _don_rested_lower_bound(turn, cards_db):
    """Estimativa CONSERVADORA (limite inferior, nunca inventa DON) de
    quanto DON ficou RESTADO pro dono deste turno, a partir de sinais
    100% estruturados do log de acoes -- sem adivinhar custo de 'play'
    (cartas jogadas de graca via efeito nao tem custo real, e o schema do
    log nao distingue play pago de play gratis, entao contar o custo
    impresso da carta arriscaria inventar DON restado que nunca existiu).

    Conta so o que e inequivocamente DON saindo do banco do jogador:
    (a) `attach_don` (amount explicito no proprio log);
    (b) custo textual 'Rest N Don' dentro de `effects` de qualquer acao
        (ex: 'The Outcome Will Tell Us Who's Strong and Who's Weak':
        'Rest 1 Don, Reveal and Draw ...').

    Achado real 24/08 (pedido do usuario 'olhe essa pendencia', apos o
    fix de give_don_opp pro Arlong/Alvida/Morgan/Krieg OP15-008): usado
    pra popular `opp.don_rested`/`opp.don_available` em audit_one_game,
    que antes deste fix NUNCA reconstruia o banco de DON do OPONENTE
    (so `opp.don_deck`) -- qualquer custo que dependa do banco de DON do
    OPONENTE especificamente (give_don_opp) sempre aparecia como
    impagavel nessa ferramenta, mesmo quando o oponente real tinha DON
    restado disponivel. Por ser um LIMITE INFERIOR (nunca superestima),
    o pior caso remanescente e o mesmo de antes (custo real pagavel
    reportado como impagavel), nunca o oposto (nunca inventa
    payabilidade que nao existia)."""
    total = 0
    for a in turn.get('actions', []):
        if a.get('type') == 'attach_don':
            total += a.get('amount', 0) or 0
        for eff in a.get('effects') or []:
            m = re.search(r'\bRest (\d+) Don\b', eff)
            if m:
                total += int(m.group(1))
    return total


def audit_one_game(parsed_path, bot_side, cards_db, df_raw, urls, verbose=False,
                   capture_actions=False, capture_candidates=False):
    """
    capture_actions: alem da narrativa em texto (`engine_hoje_narrativa`),
    inclui em cada turno `chosen_actions` -- lista ESTRUTURADA (kind, carta,
    alvo) extraida do `decision_log` interno do motor (`_log_turn_planner_
    decision`), uma entrada por decisao de main phase no turno. Pensado pra
    comparacoes automatizadas (ex: `audit_curve_calibration_flags.py`)
    que precisam saber se a AÇÃO mudou, nao so se o TEXTO do log mudou --
    achado real 15/08: duas acoes identicas podem gerar texto de log
    ligeiramente diferente dependendo do caminho de codigo, inflando uma
    comparacao por string. False por padrao (custo extra de habilitar o
    decision_log), comportamento de quem nao passa o parametro é idêntico
    a antes.

    capture_candidates: inclui em cada turno `decisions` -- lista CRUA de
    registros `turn_planner` do `decision_log` (chosen + top-8 candidatos
    com score/simulated_value, ja produzidos por `_log_turn_planner_
    decision`/`_audit_action_brief`, sem reprocessar nada). Existe pra
    responder "a jogada X nem foi GERADA como candidata, ou foi gerada e
    perdeu pra outra com score maior?" -- distincao que `chosen_actions`
    sozinho nao da (so mostra o que venceu). Achado real 17/08 (pedido do
    usuario, comparar motor x humano turno a turno): sem isto, um gap
    tipo "motor ativa 3x menos que o humano" fica sem causa raiz
    identificavel. Tambem liga `enable_decision_audit()` (independente de
    `capture_actions`). False por padrao, sem custo extra pra quem nao usa.
    """
    data = json.load(open(parsed_path, encoding='utf-8'))
    meta = data['meta']['players']
    turns = data['turns']
    # Achado real 18/08 (bloco 617, pedido do usuario "por que so 26 se
    # temos 150 no banco?" -- decision_quality_full.py passou a auditar
    # tambem os 124 logs humano-vs-humano, que usam o NOME REAL dos 2
    # jogadores em vez da convencao fixa 'You'/'Opponent'): o flip
    # binario hardcoded so funcionava pra logs bot-vs-humano -- pra um
    # log humano-vs-humano, `bot_side` chega como um nome real (ex:
    # "Karlmalone#2854"), nunca igual a 'You', entao o flip SEMPRE
    # devolvia 'You' (nunca batendo com nenhum dos 2 nomes reais),
    # quebrando a reconstrucao do lado oponente. Deriva do proprio meta
    # -- funciona identico pro caminho antigo (onde o resultado bate
    # exatamente com o flip binario) e correto pro caso novo.
    opp_side = meta['p2']['name'] if meta['p1']['name'] == bot_side else meta['p1']['name']

    bot_leader = meta['p1' if meta['p1']['name'] == bot_side else 'p2']['leader']
    opp_leader = meta['p1' if meta['p1']['name'] == opp_side else 'p2']['leader']
    bot_leader_name, bot_leader_code = bot_leader['name'], bot_leader.get('code')
    opp_leader_name, opp_leader_code = opp_leader['name'], opp_leader.get('code')

    # Achado real 17/08: pra lideres SEM decklist real no banco (Teach/
    # Krieg/Kid confirmados ausentes), _find_real_deck cai no fallback
    # generico (linha ~128, random.shuffle(candidatos)) -- e isso roda
    # AQUI, uma vez por jogo, ANTES do reseed deterministico por-turno
    # la embaixo (`random.seed(f'{parsed_path}:{turn}')`). Sem seed
    # proprio aqui, o fallback usava o estado GLOBAL do random (ambiente,
    # nao determinismo do projeto) -- resultado: rodar o MESMO audit_one_
    # game duas vezes (ou em processos paralelos com PYTHONHASHSEED
    # diferente) montava um deck generico DIFERENTE pro Teach, mudando a
    # mao reconstruida turno a turno e o veredito agregado inteiro
    # (confirmado: decision_quality_vs_human.py dava 84.7%/86.5%/90.1%
    # em runs identicos ate este fix). Seed determinista por (arquivo,
    # lider) cobre o fallback sem tocar no reseed por-turno existente.
    random.seed(f'{os.path.basename(parsed_path)}:deck:{bot_leader_code}:{opp_leader_code}')
    # bloco 655: cartas OBSERVADAS de cada lado na partida inteira (mao,
    # board e trash de todos os snapshots + o que foi jogado). Servem pra
    # desempatar entre varios decks do mesmo lider na pasta do simulador
    # (29,3% dos casos, ex: 4 arquivos "Barba Negra").
    def _observadas(lado):
        vistos = []
        for t in turns:
            snap = (t.get('snapshot') or {}).get(lado) or {}
            for zona in ('hand', 'board', 'trash'):
                vistos.extend(snap.get(zona) or [])
            if t.get('player') == lado:
                for a in t.get('actions') or []:
                    if a.get('card'):
                        vistos.append(a['card'])
        return vistos

    # snapshot da ingestao vem PRIMEIRO (bloco 656)
    bot_deck = (_snapshot_do_banco(parsed_path, bot_side, cards_db)
                or _find_real_deck(bot_leader_name, cards_db, df_raw, urls,
                                   bot_leader_code, observed_codes=_observadas(bot_side)))
    opp_deck = (_snapshot_do_banco(parsed_path, opp_side, cards_db)
                or _find_real_deck(opp_leader_name, cards_db, df_raw, urls,
                                   opp_leader_code, observed_codes=_observadas(opp_side)))
    if not bot_deck or not opp_deck:
        return {'error': f'deck real nao encontrado (bot={bot_leader_name}, opp={opp_leader_name})'}

    don_est = DonEstimator()
    bot_turn_count = 0
    results = []

    for i, turn in enumerate(turns):
        player = turn['player']
        if player == bot_side:
            bot_turn_count += 1
        if i == 0:
            # sem snapshot "antes" pro 1o turno de qualquer um dos lados
            don_est.apply_turn(player, turn, cards_db)
            continue
        if player != bot_side:
            don_est.apply_turn(player, turn, cards_db)
            continue

        before = turns[i - 1]['snapshot']
        if bot_side not in before or opp_side not in before:
            don_est.apply_turn(player, turn, cards_db)
            continue

        bot_snap = before[bot_side]
        opp_snap = before[opp_side]

        match = ReplayMatch(bot_deck, opp_deck, 'Bot(hoje)', 'Oponente')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            match.setup()
        p = match.state_a
        opp = match.state_b
        # Achado real 17/08 (pedido do usuario, censo amplo de "jogada
        # nunca gerada como candidata" -- Kyo OP17-045, custo 2, turno 2
        # do jogo, so 1 DON estimado disponivel): is_first ERA fixo em
        # True pro lado auditado, SEMPRE -- mesmo quando esse lado
        # realmente jogou em SEGUNDO na partida real (confirmado neste
        # caso: turns[0]['player']=='You', bot_side=='Opponent' foi o
        # 2o jogador). O motor da 1 DON no 1o turno de quem vai PRIMEIRO
        # e 2 DON no 1o turno de quem vai SEGUNDO (`decision_engine.py`,
        # linha ~14180) -- com is_first errado, todo turno inicial de um
        # jogador que realmente foi o 2o subestimava o DON disponivel em
        # 1, cascateando pro resto da partida via DonEstimator (que
        # acumula don_drawn por turno). Fix: deriva de quem jogou o
        # PRIMEIRO turno de verdade no log (`turns[0]['player']`), nao
        # mais um palpite fixo.
        bot_is_first = turns[0]['player'] == bot_side
        p.is_first = bot_is_first
        opp.is_first = not bot_is_first

        p.hand = _cards_from_codes(bot_snap.get('hand', []), cards_db)
        p.field_chars = _cards_from_codes(bot_snap.get('board', []), cards_db,
                                           bot_snap.get('rested', {}))
        p.trash = _cards_from_codes(bot_snap.get('trash', []), cards_db)
        # bloco 684: `stage` vem do RZ1 -- verdade direta, sem inferencia.
        # `_field_stage_at` (bloco 650) fica como fallback pros logs antigos.
        _stage_rz1 = None if IGNORAR_RZ1 else (bot_snap.get('stage') or [None])[0]
        _stage_code = _stage_rz1 or _field_stage_at(turns, i, bot_side, cards_db)
        if _stage_code and _stage_code not in (bot_snap.get('trash') or []):
            _st = _cards_from_codes([_stage_code], cards_db)
            p.field_stage = _st[0] if _st else None
        # bloco 684: `life_cards` vem do protocolo RZ1 do jogo -- e o conteudo
        # REAL do Life. Antes o Life era preenchido com cartas FALSAS do topo
        # de um deck embaralhado, o que errava trigger, o que vai pra mao ao
        # tomar dano, e toda avaliacao que olha Life.
        life_n = bot_snap.get('life', 4)
        _lc = None if IGNORAR_RZ1 else bot_snap.get('life_cards')
        if _lc:
            p.life = _cards_from_codes(list(_lc), cards_db)
        else:
            p.life = [deepcopy(c) for c in p.deck[:life_n]] if p.deck else []

        opp.hand = _cards_from_codes(opp_snap.get('hand', []), cards_db)
        opp.field_chars = _cards_from_codes(opp_snap.get('board', []), cards_db,
                                             opp_snap.get('rested', {}))
        opp.trash = _cards_from_codes(opp_snap.get('trash', []), cards_db)
        _stage_rz1_opp = None if IGNORAR_RZ1 else (opp_snap.get('stage') or [None])[0]
        _stage_code_opp = _stage_rz1_opp or _field_stage_at(turns, i, opp_side, cards_db)
        if _stage_code_opp and _stage_code_opp not in (opp_snap.get('trash') or []):
            _st_o = _cards_from_codes([_stage_code_opp], cards_db)
            opp.field_stage = _st_o[0] if _st_o else None
        opp_life_n = opp_snap.get('life', 4)
        _lco = None if IGNORAR_RZ1 else opp_snap.get('life_cards')
        if _lco:
            opp.life = _cards_from_codes(list(_lco), cards_db)
        else:
            opp.life = [deepcopy(c) for c in opp.deck[:opp_life_n]] if opp.deck else []

        # Achado real 15/08 (continuacao do bloco 534/535): fixar
        # random.seed() so uma vez ANTES da chamada inteira de
        # audit_one_game nao basta pra comparar OFF vs ON turno a turno --
        # eng.play_turn() consome random (Monte Carlo, desempate) em
        # quantidade DIFERENTE dependendo de quais flags de calibragem
        # estao ligadas (caminhos de decisao diferentes = numero diferente
        # de chamadas random.*), entao o estado global do random DRIFTA
        # entre as duas condicoes a partir do 1o turno com decisao
        # diferente -- turnos POSTERIORES do MESMO jogo comparavam mao
        # embaralhada de formas diferentes por acidente, nao por efeito
        # real das flags (confirmado: turno 11 de um jogo mostrava carta
        # comprada diferente entre OFF/ON ANTES de qualquer decisao rodar
        # nesse turno). Fix: reseed DETERMINISTICO por (arquivo, turno),
        # imune a quanto random foi consumido por decisoes de turnos
        # anteriores -- cada turno embaralha exatamente igual nas duas
        # condicoes, only a decisao em si pode divergir.
        random.seed(f'{os.path.basename(parsed_path)}:{turn["turn"]}')
        seen_bot = {}
        for c in p.hand + p.field_chars + p.trash + p.life:
            seen_bot[c.code] = seen_bot.get(c.code, 0) + 1

        # Achado real 17/08 (pedido do usuario, ver docstring de
        # _known_gains_this_turn): as cartas que o motor vai COMPRAR
        # durante este turno simulado nao precisam ser um palpite
        # aleatorio -- o log ja diz exatamente quais cartas entraram na
        # mao do humano neste turno (diff de snapshot antes/depois).
        # Remove essas cartas do pool "desconhecido" (senao sobrariam
        # DUPLICADAS: uma copia forcada no topo + outra ainda solta no
        # resto do baralho embaralhado) e as recoloca no TOPO (fim da
        # lista, convencao pop() do projeto) depois do embaralhamento --
        # exatamente as cartas que o motor vai comprar primeiro.
        after_bot_hand = turn.get('snapshot', {}).get(bot_side, {}).get('hand', [])
        known_gains_bot = _known_gains_this_turn(turn, bot_snap.get('hand', []), after_bot_hand, cards_db)
        for code, qty in known_gains_bot.items():
            seen_bot[code] = seen_bot.get(code, 0) + qty
        p.deck = _remaining_deck(bot_deck[1], seen_bot)
        # ORDEM dos ganhos no topo (achado 25/08, correcao pedida
        # explicitamente pelo usuario: "voce tem que contar a carta
        # comprada como candidata sim"): o humano frequentemente ganha
        # VARIAS cartas num turno (compra padrao + "Draw N" de efeitos),
        # mas o motor simulado so compra 1 no inicio do turno -- as
        # outras so chegam se ele disparar os MESMOS efeitos de compra.
        # Qual das N o motor recebe nessa unica compra era decidido pela
        # ordem ARBITRARIA de `Counter.elements()`.
        #
        # Caso real que expos (Mihawk OP14-020, T7): humano ganhou
        # [ST32-003, OP07-022, OP12-034, OP14-039] e JOGOU OP12-034
        # (Perona); `elements()` deixou OP14-039 (Coffin Boat) por
        # ultimo = topo, entao o motor comprou Coffin Boat e Perona
        # ficou enterrada -- a carta cuja decisao a auditoria quer
        # comparar nunca chegou a ser uma opcao. Isso contaminava o
        # diagnostico inteiro de `play`: turnos assim apareciam como
        # "motor nao jogou a carta" quando na verdade o motor nunca a
        # teve em maos, por acaso de ordenacao.
        #
        # Fix: ordena os ganhos pela ORDEM EM QUE O HUMANO OS JOGOU --
        # o jogado PRIMEIRO vai por ultimo no extend (= TOPO do deck,
        # `pop()`), entao e o primeiro que o motor compra; depois o
        # jogado em 2o, e assim por diante; ganhos que o humano NAO
        # jogou ficam por baixo de todos.
        #
        # Ordenar so por "foi jogada ou nao" NAO resolve (tentado
        # primeiro, e falhou neste mesmo caso): o humano jogou Perona E
        # Coffin Boat no mesmo turno, entao as duas empatavam e a ordem
        # arbitraria seguia mandando. A ordem de JOGO desempata pela
        # informacao certa -- a 1a carta jogada e tipicamente a que
        # habilita o resto do turno (aqui: jogar Perona e que comprou
        # ST32-003, e Kin'emon comprou mais 2), entao dar ela primeiro
        # ao motor e o que mais aproxima a simulacao da sequencia real.
        #
        # Nao inventa carta nenhuma -- todos os codigos continuam sendo
        # ganhos REAIS do log. O motor continua LIVRE pra nao jogar a
        # carta (e exatamente isso que a auditoria mede); o que muda e
        # ele passar a TER a chance, em vez de ser privado dela por
        # acaso de ordenacao.
        _ordem_de_jogo = {}
        for _idx, _a in enumerate(turn.get('actions', [])):
            _cod = _a.get('card')
            if (_cod and _cod not in _ordem_de_jogo
                    and hist_action_kind(_a, cards_db) == 'play'):
                _ordem_de_jogo[_cod] = _idx
        _gains_ordenados = sorted(
            known_gains_bot.elements(),
            key=lambda c: (c in _ordem_de_jogo, -_ordem_de_jogo.get(c, 0)))
        p.deck.extend(_cards_from_codes(_gains_ordenados, cards_db))
        populate_full_deck_knowledge(p, bot_deck[1], bot_deck[0].code)

        seen_opp = {}
        for c in opp.hand + opp.field_chars + opp.trash + opp.life:
            seen_opp[c.code] = seen_opp.get(c.code, 0) + 1
        opp.deck = _remaining_deck(opp_deck[1], seen_opp)
        populate_full_deck_knowledge(opp, opp_deck[1], opp_deck[0].code)

        p.turn = bot_turn_count - 1
        # bloco 684: `don_cost` (cost area) e `rested_rz1` vem do RZ1 -- DON
        # REAL, nao estimado. O `DonEstimator` continua como fallback pros
        # logs sem RZ1; foi corrigido 2x hoje (regra 6-2-3 no bloco 650, teto
        # no 651) justamente por ser inferencia.
        _don_cost = None if IGNORAR_RZ1 else bot_snap.get('don_cost')
        if _don_cost is not None:
            _rest = ((bot_snap.get('rested_rz1') or {}).get('don_cost') or [])
            # Bloco 690: o DON ANEXADO em personagens (zona 9 do RZ1,
            # `attached_don`) tem que entrar na conta. `don_cost` e SO a
            # area de custo -- o DON que o jogador anexou durante o turno
            # esta na zona 9, e pela regra 6-2-3 volta INTEIRO pra area de
            # custo, ATIVO, no refresh do proprio turno. Ignora-lo fazia o
            # motor comecar o turno com menos DON do que o humano tinha,
            # e portanto jogar menos carta -- nao por decisao, por recurso
            # que sumiu na reconstrucao.
            #
            # Medido contra a verdade do proprio log (708 turnos, sendo a
            # verdade `don_cost + attached_don`, ja que nada sai do
            # sistema): **53% -> 82% de acerto EXATO**, erro medio 0,83 ->
            # 0,25. Entra como `don_rested` porque o `refresh_phase` do
            # motor ja soma `don_rested` em `don_available` -- o efeito
            # liquido no inicio do turno e o DON total correto e ativo.
            #
            # NOTA sobre a medicao anterior (bloco 688), que dizia 34% e
            # concluiu "RZ1 e estimador sao equivalentes": aquela conta
            # usava `don_cost` como VERDADE, e `don_cost` exclui o
            # anexado -- a propria regua estava errada. O numero certo do
            # metodo em uso e 53%, e a conclusao de equivalencia nao vale.
            _att = (bot_snap.get('attached_don') or [])
            p.don_available = max(0, len(_don_cost) - len(_rest))
            p.don_rested = len(_rest) + len(_att)
        else:
            p.don_available = don_est.available(bot_side)
        # ver DonEstimator.deck_left -- sem isto a don_phase do turno
        # simulado estoura o teto de 10 DON
        p.don_deck = don_est.deck_left(bot_side)
        opp.don_deck = don_est.deck_left(opp_side)
        # Achado real 24/08 (pedido do usuario "olhe essa pendencia"):
        # opp.don_available/opp.don_rested NUNCA eram populados antes
        # deste fix (so opp.don_deck) -- qualquer custo que dependa do
        # banco de DON do OPONENTE (ex: give_don_opp, familia Arlong/
        # Alvida/Morgan/Krieg OP15-008) sempre aparecia como impagavel
        # nesta ferramenta. don_rested vem do limite inferior conservador
        # de `_don_rested_lower_bound` aplicado ao ULTIMO turno PROPRIO
        # do oponente antes deste ponto (o DON so refresca de novo no
        # proximo turno DELE, que ainda nao aconteceu) -- o resto do pool
        # (don_est.available, ja rastreado) fica como don_available.
        opp_ultimo_turno = next(
            (turns[j] for j in range(i - 1, -1, -1) if turns[j]['player'] == opp_side),
            None)
        opp_total = don_est.available(opp_side)
        opp_rested_estimado = (
            min(opp_total, _don_rested_lower_bound(opp_ultimo_turno, cards_db))
            if opp_ultimo_turno is not None else 0)
        opp.don_rested = opp_rested_estimado
        opp.don_available = opp_total - opp_rested_estimado
        # Achado real 17/08 (pedido do usuario, censo de "jogada nunca
        # gerada" -- don_antes_do_ramp aparecia 0 em quase TODO turno,
        # ate em turnos tardios T8/T9/T10 onde deveria ter acumulado
        # DON de sobra): `don_available_estimado` abaixo lia `p.don_
        # available` DEPOIS de `eng.play_turn()` rodar -- ou seja,
        # mostrava o que SOBROU apos o motor gastar no proprio turno
        # simulado, nao o que ele TINHA no inicio (a simulacao em si
        # sempre usou o valor certo, pre-turno -- isto e so um bug de
        # RELATORIO/diagnostico, nao de decisao). Captura o valor ANTES
        # de play_turn() mutar `p.don_available`.
        don_disponivel_pre_turno = p.don_available

        eng = match._get_engine_match()
        if capture_actions or capture_candidates:
            eng.enable_decision_audit()
        # Observabilidade de attach_don (29/08): `AD_DEBUG_LOG` e uma lista
        # GLOBAL que so acumula com OPTCG_DEBUG_AD=1. Zerar aqui e copiar
        # depois do play_turn e o que da recorte POR TURNO -- sem isso o
        # motivo da recusa nao da pra cruzar com o alvo que o humano usou
        # naquele turno especifico. Custo zero com a flag desligada.
        from optcg_engine.decision_engine import AD_DEBUG, AD_DEBUG_LOG
        if AD_DEBUG:
            AD_DEBUG_LOG.clear()
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            try:
                eng.play_turn(p, opp, verbose=True)
            except Exception as exc:  # nunca deixa uma reconstrucao ruim derrubar a auditoria inteira
                results.append({
                    'turn': turn['turn'], 'error': str(exc),
                    'historical_actions': turn.get('actions', []),
                })
                don_est.apply_turn(player, turn, cards_db)
                continue
        engine_log = buf2.getvalue()

        entry = {
            'turn': turn['turn'],
            'don_available_estimado': don_disponivel_pre_turno,
            'historical_actions': turn.get('actions', []),
            'engine_hoje_narrativa': engine_log,
        }
        if AD_DEBUG:
            entry['ad_debug'] = list(AD_DEBUG_LOG)
        if capture_actions:
            # p e sempre match.state_a (ver acima) -- player_id 'A' em
            # _log_turn_planner_decision. Cada entrada e 1 decisao de main
            # phase (play/attack/activate/attach_don); ordem preservada.
            entry['chosen_actions'] = [
                {
                    'kind': (rec.get('chosen') or {}).get('kind'),
                    # bloco 656: a acao `pass` grava `card: None` (presente,
                    # mas nulo) -- `.get('card', {})` devolve None nesse caso,
                    # nao o default, e quebrava com AttributeError
                    'card': ((rec.get('chosen') or {}).get('card') or {}).get('code'),
                    'target_type': (rec.get('chosen') or {}).get('target_type'),
                    'target': (rec.get('chosen') or {}).get('target', {}).get('code')
                              if (rec.get('chosen') or {}).get('target') else None,
                }
                for rec in (eng.decision_log or [])
                if rec.get('kind') == 'turn_planner' and rec.get('player') == 'A'
            ]
        if capture_candidates:
            entry['decisions'] = [
                rec for rec in (eng.decision_log or [])
                if rec.get('kind') == 'turn_planner' and rec.get('player') == 'A'
            ]
            # Achado real 17/08 (bloco 589/590): DON anexado via top-up
            # AUTOMATICO de _attach_don_for_attack (quando um 'attack' ja
            # ESCOLHIDO precisa de DON pra passar a defesa) e um kind
            # PROPRIO no decision_log, separado de 'turn_planner' -- sem
            # isto, ferramentas que so leem `decisions` (filtrado acima)
            # subestimam quanto DON o motor de fato investe em ataque.
            entry['attach_don_for_attack_events'] = [
                rec for rec in (eng.decision_log or [])
                if rec.get('kind') == 'attach_don_for_attack' and rec.get('player') == 'A'
            ]
            # bloco 732: SEQUENCIA na ordem real, com os dois tipos de
            # registro INTERCALADOS. As duas listas acima sao filtradas
            # por tipo e perdem a ordem relativa entre elas -- quem quiser
            # medir SEQUENCIAMENTO precisa da ordem, e reconstruir a
            # partir delas e impossivel.
            #
            # Sem isto o diagnostico de sequencia comparava mal: no motor,
            # o DON anexado PRA ATACAR e aplicado dentro da execucao do
            # ataque e nunca aparece como decisao `attach_don` -- entao a
            # sequencia do motor so tinha as anexacoes que HABILITAM
            # efeito, enquanto a do humano tem TODAS. Comparacao entre
            # populacoes diferentes (achado ao investigar o bloco 731; e o
            # MESMO erro ja documentado no bloco 589/590 por outro
            # caminho).
            _ordem = []
            for rec in (eng.decision_log or []):
                if rec.get('player') != 'A':
                    continue
                if rec.get('kind') == 'attach_don_for_attack':
                    _ordem.append('attach_don')
                elif rec.get('kind') == 'turn_planner':
                    _k = (rec.get('chosen') or {}).get('kind')
                    if _k in ('play', 'activate', 'attach_don', 'attack'):
                        _ordem.append(_k)
            entry['seq_kinds'] = _ordem
        results.append(entry)
        if verbose:
            print(f'--- turno {turn["turn"]} (real vs motor de hoje) ---')
            print('HISTORICO:', json.dumps(turn.get('actions', []), ensure_ascii=False)[:300])
            print('HOJE:', engine_log[:600])

        don_est.apply_turn(player, turn, cards_db)

    return {
        'parsed_file': os.path.basename(parsed_path),
        'bot_side': bot_side,
        'bot_leader': bot_leader_name,
        'opp_leader': opp_leader_name,
        'turnos_auditados': len(results),
        'turnos': results,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--log', help='caminho de um parsed json especifico')
    ap.add_argument('--all', action='store_true', help='roda em todas as derrotas reais do bot')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    if args.list:
        for pf, side in find_real_bot_losses():
            print(pf)
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    if args.log:
        jobs = [(args.log, 'You')]
    else:
        jobs = find_real_bot_losses()
        if args.limit:
            jobs = jobs[:args.limit]

    for pf, side in jobs:
        full_path = os.path.join(LOGS_DIR, pf) if not os.path.isabs(pf) and not pf.startswith(LOGS_DIR) else pf
        print(f'Auditando {pf}...')
        try:
            report = audit_one_game(full_path, side, cards_db, df_raw, urls, verbose=args.verbose)
        except Exception as exc:
            report = {'parsed_file': os.path.basename(pf), 'error': str(exc)}
        out_path = os.path.join(OUT_DIR, os.path.basename(pf))
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        if 'error' in report:
            print(f'  ERRO: {report["error"]}')
        else:
            print(f'  {report["turnos_auditados"]} turno(s) auditado(s) -> {out_path}')


if __name__ == '__main__':
    main()
