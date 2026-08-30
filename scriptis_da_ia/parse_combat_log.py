#!/usr/bin/env python3
"""
parse_combat_log.py -- Converte um combat log do simulador oficial OPTCG
em JSON estruturado com decisoes turno a turno, extrai listas de deck e
gerencia o banco de logs (scriptis_da_ia/logs/).

Uso:
    python parse_combat_log.py partida.log
    python parse_combat_log.py partida.log --summary
    python parse_combat_log.py partida.log --add-to-db      (salva no banco)
    python parse_combat_log.py --list-db                    (lista partidas no banco)
"""

import re
import csv
import json
import shutil
import argparse
from pathlib import Path
from collections import Counter

# Raiz do banco de logs (relativo a este script)
DB_ROOT = Path(__file__).parent / 'logs'
DB_INDEX = DB_ROOT / 'index.json'

# Ordem canonica das cores OPTCG para montar a abreviacao
_COLOR_ORDER  = ['Red', 'Green', 'Blue', 'Purple', 'Black', 'Yellow']
_COLOR_LETTER = {'Red': 'R', 'Green': 'G', 'Blue': 'B',
                 'Purple': 'P', 'Black': 'B', 'Yellow': 'Y'}

# Cache do CSV de cartas
_CARDS_CSV: dict | None = None

def _load_cards_csv() -> dict:
    global _CARDS_CSV
    if _CARDS_CSV is not None:
        return _CARDS_CSV
    csv_path = Path(__file__).parent / 'cards_rows.csv'
    _CARDS_CSV = {}
    if csv_path.exists():
        with open(csv_path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                _CARDS_CSV[row['id']] = row
    return _CARDS_CSV


# Cache do banco de analise (tem has_rush -- cards_rows.csv nao tem esse dado)
_CARDS_ANALYSIS_DB: dict | None = None

def _load_cards_analysis_db() -> dict:
    global _CARDS_ANALYSIS_DB
    if _CARDS_ANALYSIS_DB is not None:
        return _CARDS_ANALYSIS_DB
    db_path = Path(__file__).parent / 'card_analysis_db.json'
    _CARDS_ANALYSIS_DB = {}
    if db_path.exists():
        with open(db_path, encoding='utf-8') as f:
            _CARDS_ANALYSIS_DB = json.loads(f.read())
    return _CARDS_ANALYSIS_DB


def _has_rush(code: str) -> bool:
    return bool(_load_cards_analysis_db().get(code, {}).get('has_rush'))


# ---------------------------------------------------------------------------
# Rastreio de active/rested por personagem (achado 28/07, bloco HANDOFF 391:
# a comparacao IA-vs-humano de ALVO de ataque -- lider vs personagem -- so e
# valida se o motor souber quais personagens do oponente estao REALMENTE
# rested no snapshot, ja que so pode declarar ataque contra o lider ou um
# personagem rested (rules_facade/decision_engine: `opp.rested_chars(att)`).
# O snapshot original (Hand/Board/Trash/Life que o proprio simulador
# imprime) NUNCA teve esse dado -- so lista codes. Reconstruido aqui via
# simulacao incremental (Deploy/attacking/efeitos "Rest X"/"Destroy X" no
# log), com RECONCILIACAO contra o board REAL a cada turno pra nao deixar
# o rastreio "solto" divergir sem controle (nem todo verbo de remocao de
# campo esta coberto -- a reconciliacao clampa/completa pelo board de
# verdade, entao um verbo faltando so custa precisao, nunca gera contagem
# maior que a real).
# ---------------------------------------------------------------------------

def _board_add(board_state: dict, side: str, code: str, rested: bool) -> None:
    board_state.setdefault(side, []).append({'code': code, 'rested': rested})


def _board_rest_one(board_state: dict, side: str, code: str) -> bool:
    """Restaura UMA copia ativa de `code` no lado `side` (custo de atacar)."""
    for e in board_state.get(side, []):
        if e['code'] == code and not e['rested']:
            e['rested'] = True
            return True
    return False


def _board_rest_one_any_side(board_state: dict, p1: str, p2: str, code: str) -> bool:
    """Restaura UMA copia ativa de `code` em QUALQUER lado (efeito de texto
    livre nao diz de quem e o alvo -- pode ser custo no proprio lider/
    personagem, ou remocao no lado oponente)."""
    for side in (p1, p2):
        if _board_rest_one(board_state, side, code):
            return True
    return False


def _board_remove_one(board_state: dict, side: str, code: str) -> bool:
    lst = board_state.get(side, [])
    for i, e in enumerate(lst):
        if e['code'] == code:
            lst.pop(i)
            return True
    return False


def _board_remove_one_any_side(board_state: dict, p1: str, p2: str, code: str) -> bool:
    for side in (p1, p2):
        if _board_remove_one(board_state, side, code):
            return True
    return False


def _rest_and_remove_codes_in_text(text: str) -> tuple[list[str], list[str]]:
    """Acha codes restados e removidos num texto livre de efeito (`fx` de
    RE_EFFECT). Retorna (codes_restados, codes_removidos)."""
    rested = [m.group(1) for m in _RE_REST_VERB.finditer(text)]
    removed = [m.group(1) for m in _RE_REMOVE_VERB.finditer(text)]
    return rested, removed


def _reconcile_board_state(board_state: dict, side: str, real_board_codes: list[str]) -> None:
    """Corrige o rastreio incremental pelo board REAL deste snapshot (autoridade
    final) -- adiciona copias nao detectadas como ativas (default conservador,
    igual ao comportamento antes deste rastreio existir) e remove excesso
    (prioriza remover as ATIVAS extras, preservando a informacao de rested
    que de fato foi detectada)."""
    real_counts = Counter(real_board_codes)
    lst = board_state.setdefault(side, [])
    tracked_counts = Counter(e['code'] for e in lst)

    for code, real_n in real_counts.items():
        tracked_n = tracked_counts.get(code, 0)
        if tracked_n < real_n:
            for _ in range(real_n - tracked_n):
                lst.append({'code': code, 'rested': False})

    for code in list(tracked_counts):
        real_n = real_counts.get(code, 0)
        tracked_n = tracked_counts[code]
        if tracked_n <= real_n:
            continue
        idxs = [i for i, e in enumerate(lst) if e['code'] == code]
        idxs.sort(key=lambda i: lst[i]['rested'])  # ativas (False) primeiro
        for i in sorted(idxs[:tracked_n - real_n], reverse=True):
            lst.pop(i)


def _board_rested_counts(board_state: dict, side: str) -> dict:
    return dict(Counter(e['code'] for e in board_state.get(side, []) if e['rested']))


def _color_abbrev(color_str: str) -> str:
    """'Black Yellow' -> 'BY', 'Blue Red' -> 'RB' (ordem canonica)."""
    colors = [c.strip() for c in color_str.split() if c.strip()]
    # ordena pela posicao canonica
    ordered = sorted(colors, key=lambda c: _COLOR_ORDER.index(c)
                     if c in _COLOR_ORDER else 99)
    return ''.join(_COLOR_LETTER.get(c, c[0]) for c in ordered)


def _leader_slug(leader_name: str, leader_code: str) -> str:
    """
    Retorna 'Marshall.D.Teach-BY' a partir do nome e code do lider.
    Busca a cor no cards_rows.csv; se nao encontrar, omite a cor.
    """
    cards = _load_cards_csv()
    row = cards.get(leader_code, {})
    color_str = row.get('card_color', '')

    # Limpa o nome: remove sufixo " (NNN)", colapsa espacos em ponto,
    # mas nao duplica pontos (nome ja pode ter "D." no meio)
    name = re.sub(r'\s*\(\d+\)\s*$', '', leader_name).strip()
    name = re.sub(r'["\'/\\|<>:*?]', '', name)  # remove chars ilegais em filesystem
    name = re.sub(r'\s+', '.', name)
    name = re.sub(r'\.{2,}', '.', name)   # colapsa pontos duplos

    if color_str:
        return f'{name}-{_color_abbrev(color_str)}'
    return name


def _match_slug(p1_slug: str, p2_slug: str) -> str:
    """'Marshall.D.Teach-BY_x_Lucy-RB'"""
    return f'{p1_slug}_x_{p2_slug}'

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_LEADER   = re.compile(r'^\[(.+?)\] Leader is (.+?) \["([A-Z0-9]+-\d+)">')
RE_DRAW_DON = re.compile(r'^\[(.+?)\] Draw (\d+) Don')
RE_DREW     = re.compile(r'^\[(.+?)\] Drew card from deck: (.+?) \["([A-Z0-9]+-\d+)">')
RE_DEPLOY   = re.compile(r'^\[(.+?)\] Deploy (.+?) \["([A-Z0-9]+-\d+)">')
# Formato do log: ["CODE">DisplayName]  -- o fechamento e ">NAME]", nao somente "]"
# Por isso os patterns de card ref usam  \["(CODE)">[^\]]*\]  em vez de  \["(CODE)"\]
_CR  = r'\["([A-Z0-9]+-\d+)"[^\]]*\]'   # captura code, ignora o resto ate fechar ]
_CRn = r'\["[A-Z0-9]+-\d+"[^\]]*\]'     # sem captura (so consome o token)

RE_ATTACH   = re.compile(r'^\[(.+?)\] Attach (\d+) Don to (.+?) ' + _CR + r' \((\d+) Total\)')
RE_ATTACK   = re.compile(r'^\[(.+?)\] (.+?) ' + _CR + r' attacking (.+)')
RE_BLOCKS   = re.compile(r'^\[(.+?)\] (.+?) ' + _CR + r' Blocks')
RE_HIT      = re.compile(r'^(.+?) hit for (\d+) damage')
RE_FAILS    = re.compile(r'^Attack Fails')
RE_DISCARD  = re.compile(r'^\[(.+?)\] Discard (.+?) ' + _CR + r' for Counter')
RE_EFFECT   = re.compile(r'^\[(.+?)\] (.+?) ' + _CR + r': (.+)')
RE_END      = re.compile(r'^\[(.+?)\] End Turn')
# Linha narrativa solta (sem ":"), diferente de RE_EFFECT -- registra saida
# de campo por K.O. Usada pra reconciliar o rastreio de rested/active
# (ver _rest_target_codes/_removed_target_codes).
RE_DESTROYED = re.compile(r'^\[(.+?)\] (.+?) ' + _CR + r' Destroyed\b')
# Dentro do texto livre de um efeito (`fx` de RE_EFFECT) ou de uma linha
# "X attacking Y", acha codes de carta RESTADOS/REMOVIDOS por verbo. O
# `_CR` exige o padrao LETRAS-DIGITOS (ex: OP14-020), entao nunca casa
# "Rest 1 Don"/"Rest Don [\"Don\">Don]" (sem hifen+digito) -- sem risco de
# confundir rest de DON com rest de carta.
_RE_REST_VERB    = re.compile(r'Rest (?:up to \d+ )?.+?' + _CR)
_RE_REMOVE_VERB  = re.compile(r'(?:Destroy|K\.O\.|Return|Bounce|Trash) (?:up to \d+ )?.+?' + _CR)
# Tag do jogador nestas 4 vem VAZIA (`[] Hand: [...]`) na maioria dos
# snapshots do jogo -- achado 14/07 ao construir o comparador de decisao
# humana: `(.+?)` (1+ char) nunca casava `[]`, entao _collect_snap parava
# no PRIMEIRO snapshot de cada bloco (nunca eram 4 linhas coletadas) e o
# campo `snapshot` de cada turno saia vazio. `(.*?)` (0+ char) aceita os
# dois formatos; a atribuicao do dono (tag vazia) e feita por POSICAO em
# _parse_snap (blocos de 4 linhas alternam You/Opponent -- ver ali).
RE_HAND     = re.compile(r'^\[(.*?)\] Hand: \[(.*?)\]')
RE_BOARD    = re.compile(r'^\[(.*?)\] Board: \[(.*?)\]')
RE_TRASH    = re.compile(r'^\[(.*?)\] Trash: \[(.*?)\]')
RE_LIFE     = re.compile(r'^\[(.*?)\] Life: (\d+)')
RE_CHOSE    = re.compile(r'^\[(.+?)\] Chose to go (First|Second)')
RE_DREW_RAW = re.compile(r'^\[(.+?)\] Drew card from deck: .+? \["([A-Z0-9]+-\d+)">')
RE_CARD_REF = re.compile(r'"([A-Z0-9]+-\d+)">')   # qualquer referencia a codigo no log


def _codes(s: str) -> list:
    return [c.strip() for c in s.split(',') if c.strip()] if s.strip() else []


def _clean(line: str) -> str:
    # Logs AUTOSAVED vem com rich-text do Unity nas referencias de carta:
    #   Imu [<mark><link="OP13-079">OP13-079</link></mark>]
    # enquanto o log final salvo pelo jogo vem sem as tags:
    #   Imu ["OP13-079">OP13-079]
    # Converte o markup pro formato final ANTES dos patterns (achado 12/07:
    # parse de autosaved falhava em 'Nao encontrei 2 jogadores' porque
    # RE_LEADER nao casava). O codigo vive no ATRIBUTO do <link=...> — e
    # preciso preserva-lo como o prefixo "CODE"> do formato final, nao
    # apagar a tag inteira.
    line = re.sub(r'<link=("[A-Z0-9]+-\d+")>', r'\1>', line)
    line = line.replace('<mark>', '').replace('</mark>', '').replace('</link>', '')
    return line.replace('​', '').strip()


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

def _leader_name_by_code(code: str) -> str:
    """Nome do lider a partir do codigo. O RZ1 so carrega o CODIGO, e o
    resto do pipeline (slug do arquivo, `_find_real_deck`) espera o nome.
    Tenta o `id` exato e cai pro `card_set_id` -- reprint/alt art tem `id`
    proprio (OP09-086_p1) com o mesmo `card_set_id`."""
    db = _load_cards_csv()
    row = db.get(code)
    if row is None:
        for r in db.values():
            if r.get('card_set_id') == code:
                row = r
                break
    # Devolve o CODIGO quando a linha do CSV nao e de um LEADER. O banco
    # esta atras da versao do jogo (achado 29/08: `OP17-058` e Kaido em
    # 1.42c.22 e um Evento azul no CSV), e usar o nome errado contamina o
    # slug da partida e o `_find_real_deck`. Codigo cru e feio mas honesto,
    # e o cruzamento por `leader_code` continua funcionando.
    if row is None or str(row.get('card_type', '')).strip().lower() != 'leader':
        return code
    return row.get('card_name') or code


def parse_log(log_path: str) -> tuple:
    """
    Retorna (data_dict, raw_lines_cleaned).
    raw_lines e necessario para a reconstrucao de decks.
    """
    raw = Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines()
    lines = [_clean(l) for l in raw]

    # 1. Cabecalho
    players, leaders, goes_first = [], {}, None
    for line in lines:
        m = RE_LEADER.match(line)
        if m:
            p, lname, lcode = m.group(1), m.group(2), m.group(3)
            if p not in leaders:
                players.append(p)
                leaders[p] = {'name': lname, 'code': lcode}
        m = RE_CHOSE.match(line)
        if m and m.group(2) == 'First':
            goes_first = m.group(1)

    # ── FALLBACK 1: arquivo COMPANHEIRO (29/08) ───────────────────────
    # O jogo grava DOIS arquivos por partida, um por cliente: `<ts>.log`
    # (host) e `<ts>_p2.log` (convidado). Cada um so anuncia
    # "[X] Leader is ..." do PROPRIO jogador -- nenhum dos dois sozinho
    # tem os dois lados. Eles sao complementares, entao o par resolve o
    # cabecalho sem depender do banco de cartas.
    #
    # Preferir esta fonte a RZ1 importa: aqui o NOME do lider vem do
    # proprio jogo. Achado real ao banir estes logs -- `OP17-058` e
    # **Kaido** no jogo (1.42c.22) e um EVENTO azul no nosso
    # `cards_rows.csv`, que esta atras da versao do jogo. Resolver o nome
    # pelo CSV produzia um slug de partida com o nome da carta errada.
    if len(players) < 2:
        origem = Path(log_path)
        nome = origem.stem
        companheiro = (origem.with_name(nome[:-3] + origem.suffix)
                       if nome.endswith('_p2')
                       else origem.with_name(nome + '_p2' + origem.suffix))
        if companheiro.exists():
            try:
                extra = companheiro.read_text(encoding='utf-8',
                                              errors='replace').splitlines()
            except OSError:
                extra = []
            for line in (_clean(l) for l in extra):
                m = RE_LEADER.match(line)
                if m and m.group(1) not in leaders:
                    players.append(m.group(1))
                    leaders[m.group(1)] = {'name': m.group(2), 'code': m.group(3)}
                if goes_first is None:
                    mc = RE_CHOSE.match(line)
                    if mc and mc.group(2) == 'First':
                        goes_first = mc.group(1)

    # ── FALLBACK 2: cabecalho pelo protocolo RZ1 ──────────────────────
    # Um log gravado pelo CLIENTE so anuncia "[X] Leader is ..." do
    # PROPRIO jogador -- o adversario nunca aparece nesse formato. Como o
    # jogo escreve DOIS arquivos por partida (`<ts>.log` e `<ts>_p2.log`,
    # um por cliente), nenhum dos dois passava no `len(players) < 2` e a
    # partida inteira era rejeitada. Foi assim que 7 partidas humano-x-
    # humano ficaram de fora do banco ate hoje.
    #
    # O proprio jogo ja escreve os dois jogadores em `RZ1|PLY|<slot>|
    # <nome>|<codigo_do_lider>` -- mesmo protocolo que o bloco 684 ja
    # decodifica pras zonas. Aqui ele resolve o cabecalho, e o `slot` da a
    # ordem (1 = p1, 2 = p2) sem depender de qual cliente gravou.
    if len(players) < 2:
        rz1 = {}
        for line in lines:
            if not line.startswith('RZ1|PLY|'):
                continue
            partes = line.split('|')
            if len(partes) >= 5 and partes[2].isdigit():
                rz1[int(partes[2])] = (partes[3].strip(), partes[4].strip())
        if len(rz1) >= 2:
            players, leaders = [], {}
            for slot in sorted(rz1):
                nome, code = rz1[slot]
                if nome in leaders:
                    continue
                players.append(nome)
                leaders[nome] = {'name': _leader_name_by_code(code), 'code': code}

    if len(players) < 2:
        raise ValueError('Nao encontrei 2 jogadores no log.')

    # "Chose to go Second" identifica o primeiro por eliminacao -- nos logs
    # de cliente so a escolha do PROPRIO jogador e impressa, entao exigir a
    # linha "First" deixava `goes_first` vazio em metade dos arquivos.
    if goes_first is None:
        for line in lines:
            m = RE_CHOSE.match(line)
            if m and m.group(2) == 'Second':
                outro = [p for p in players if p != m.group(1)]
                if len(outro) == 1:
                    goes_first = outro[0]
                break

    p1, p2 = players[0], players[1]
    known_codes = _build_known_codes(lines, p1, p2)

    # 2. Blocos de turno
    turn_blocks = []
    current_player = None
    current_lines = []
    game_started = False
    last_player_idx = -1

    i = 0
    while i < len(lines):
        line = lines[i]

        if not game_started:
            m = RE_DRAW_DON.match(line)
            if m:
                game_started = True
                current_player = m.group(1)
                if current_player in players:
                    last_player_idx = players.index(current_player)
                current_lines = [line]
            else:
                m2 = RE_END.match(line)
                if m2:
                    p0 = m2.group(1)
                    turn_blocks.append({
                        'player': p0,
                        'lines': current_lines + [line],
                        'snap_lines': _collect_snap(lines, i + 1),
                        'snap_at': i + 1,   # bloco 684: indice pro replay RZ1
                    })
                    if p0 in players:
                        last_player_idx = players.index(p0)
                    i = _skip_snap(lines, i + 1)
                    current_lines = []
                    continue
            i += 1
            continue

        m_end = RE_END.match(line)
        if m_end:
            current_lines.append(line)
            snap_lines = _collect_snap(lines, i + 1)
            turn_blocks.append({
                'player': current_player,
                'lines': current_lines,
                'snap_lines': snap_lines,
                'snap_at': i + 1,   # bloco 684: indice pro replay RZ1
            })
            if current_player in players:
                last_player_idx = players.index(current_player)
            i = _skip_snap(lines, i + 1)
            current_player = None
            current_lines = []
            continue

        if current_player is None:
            detected = None
            m_don  = RE_DRAW_DON.match(line)
            m_draw = re.match(r'^\[(.+?)\] Draw \d+ Card', line)
            m_drew = RE_DREW.match(line)
            if m_don:   detected = m_don.group(1)
            elif m_draw: detected = m_draw.group(1)
            elif m_drew: detected = m_drew.group(1)

            if detected and detected in players:
                current_player = detected
            elif last_player_idx >= 0 and len(players) == 2:
                current_player = players[1 - last_player_idx]

        current_lines.append(line)
        i += 1

    # ULTIMO TURNO DA PARTIDA (achado 30/08, bloco 739).
    #
    # Um bloco de turno so era emitido quando casava `RE_END` (o marcador
    # de fim de turno). O turno FINAL nao tem esse marcador: a partida
    # acaba em `GameOver`, e `current_lines` era descartado em silencio.
    #
    # Nao e caso de borda raro -- e sistematico e ENVIESADO por tipo de
    # acao, porque o turno final e o turno letal (voce ataca e anexa DON,
    # nao desenvolve board). Medido no banco inteiro antes do conserto:
    #
    #     attach_don   1328 no log cru -> 1001 parseados   (-24,6%)
    #     attack       2492 no log cru -> 2114 parseados   (-15,2%)
    #     play         1461 no log cru -> 1417 parseados   ( -3,0%)
    #
    # 98 logs afetados, 327 anexacoes perdidas, **100% delas nos ultimos
    # 20% do arquivo e ZERO fora do fim** -- o que identificou a causa.
    #
    # Por que importa alem da contagem: este corpus alimenta
    # `human_patterns.json` (calibragem que o motor USA), a metrica
    # oficial de `decision_quality_full.py`, e as medicoes de
    # sequenciamento. Com a anexacao humana subcontada em 1/4, o desvio
    # "motor abre o turno com attach_don 26,8% x 7,8% do humano" estava
    # medido contra uma regua torta -- a 2a vez que esse mesmo numero
    # aparece contaminado (a 1a foi o bloco 732, populacoes desiguais).
    if current_lines and any(not l.startswith('RZ1') and l.strip()
                             for l in current_lines):
        p_final = current_player
        if p_final is None and last_player_idx >= 0 and len(players) == 2:
            p_final = players[1 - last_player_idx]
        if p_final in players:
            turn_blocks.append({
                'player': p_final,
                'lines': current_lines,
                'snap_lines': [],
                'snap_at': len(lines),
            })

    # 3. Parsear blocos
    parsed_turns = []
    board_state = {p1: [], p2: []}
    # bloco 684: estado das zonas reconstruido do protocolo `RZ1|` do jogo,
    # avancado INCREMENTALMENTE bloco a bloco -- precisa ser o estado NAQUELE
    # ponto do log, nao o final da partida. Ver rz1_replay.py.
    try:
        from rz1_replay import replay_por_linha as _rz1_replay, casar_donos as _rz1_casar
        _rz1_por_linha = _rz1_replay(lines)
    except Exception:
        _rz1_por_linha, _rz1_casar = {}, None

    def _rz1_em(inicio, qtd):
        """Estado RZ1 no FIM do bloco de snapshot que comeca em `inicio`."""
        if not _rz1_por_linha:
            return None
        janela = [k for k in _rz1_por_linha if inicio <= k <= inicio + max(qtd, 1) + 4]
        if not janela:
            return None
        return _rz1_por_linha[max(janela)]

    for t_idx, block in enumerate(turn_blocks):
        _rz1_estado = _rz1_em(block.get('snap_at', -1), len(block.get('snap_lines') or []))
        player  = block['player']
        blines  = block['lines']
        actions = []
        don_drawn, card_drawn, current_attack = 0, None, None

        # Refresh Phase: personagens do proprio jogador ativo voltam a ficar
        # ativos no inicio do turno dele (o lado oponente NAO refresca agora).
        for e in board_state.get(player, []):
            e['rested'] = False

        for line in blines:
            if line.startswith('RZ1') or not line:
                continue

            m = RE_DRAW_DON.match(line)
            if m and m.group(1) == player:
                don_drawn = int(m.group(2)); continue

            m = RE_DREW.match(line)
            if m and m.group(1) == player:
                card_drawn = {'name': m.group(2), 'code': m.group(3)}; continue

            m = RE_DEPLOY.match(line)
            if m and m.group(1) == player:
                current_attack = None
                actions.append({'type': 'play', 'card': m.group(3),
                                'card_name': m.group(2), 'effects': []})
                _board_add(board_state, player, m.group(3),
                          rested=not _has_rush(m.group(3)))
                continue

            m = RE_ATTACH.match(line)
            if m and m.group(1) == player:
                current_attack = None
                actions.append({'type': 'attach_don', 'amount': int(m.group(2)),
                                'to': m.group(4), 'to_name': m.group(3),
                                'total': int(m.group(5))})
                continue

            m = RE_ATTACK.match(line)
            if m:
                # Fecha ataque anterior sem resultado (hit sem "hit for N damage")
                if current_attack and current_attack['result'] is None:
                    current_attack['result'] = 'hit'
                    current_attack = None
                if m.group(1) == player:
                    current_attack = {'type': 'attack', 'attacker': m.group(2),
                                      'attacker_code': m.group(3),
                                      'target': m.group(4), 'result': None,
                                      'damage': None, 'blocked_by': None,
                                      'countered_by': []}
                    actions.append(current_attack)
                    # Atacar e o custo -- rests o proprio atacante (se for o
                    # lider atacando, nao ha entrada em board_state pra ele,
                    # sem-efeito por design: alvo de ataque nunca depende do
                    # rested do LIDER).
                    _board_rest_one(board_state, player, m.group(3))
                continue

            m = RE_BLOCKS.match(line)
            if m and m.group(1) != player and current_attack:
                current_attack['blocked_by'] = m.group(3); continue

            m = RE_DISCARD.match(line)
            if m and m.group(1) != player and current_attack:
                current_attack['countered_by'].append(m.group(3)); continue

            m = RE_HIT.match(line)
            if m and current_attack:
                current_attack['result'] = 'hit'
                current_attack['damage'] = int(m.group(2))
                current_attack = None; continue

            if RE_FAILS.match(line) and current_attack:
                current_attack['result'] = 'blocked'
                current_attack = None; continue

            m = RE_DESTROYED.match(line)
            if m:
                _board_remove_one(board_state, m.group(1), m.group(3))
                continue

            m = RE_EFFECT.match(line)
            if m and m.group(1) == player:
                src_name, src_code, fx = m.group(2), m.group(3), m.group(4)
                last_play = next((a for a in reversed(actions)
                                  if a['type'] == 'play' and a['card'] == src_code), None)
                last_act  = next((a for a in reversed(actions)
                                  if a['type'] == 'activate' and a.get('card') == src_code), None)
                if last_play and not last_act:
                    last_play['effects'].append(fx)
                elif last_act:
                    last_act.setdefault('effects', []).append(fx)
                else:
                    actions.append({'type': 'activate', 'card': src_code,
                                    'card_name': src_name, 'effects': [fx]})
                rest_codes, remove_codes = _rest_and_remove_codes_in_text(fx)
                for code in rest_codes:
                    _board_rest_one_any_side(board_state, p1, p2, code)
                for code in remove_codes:
                    _board_remove_one_any_side(board_state, p1, p2, code)
                continue

        # Fecha ataque pendente ao fim do turno (acertou sem linha "hit for N")
        if current_attack and current_attack['result'] is None:
            current_attack['result'] = 'hit'

        all_snap = ([l for l in blines
                     if RE_HAND.match(l) or RE_BOARD.match(l)
                     or RE_TRASH.match(l) or RE_LIFE.match(l)]
                    + block['snap_lines'])
        snap = _parse_snap(all_snap, p1, p2, known_codes)

        # bloco 684: enriquece o snapshot com as zonas que o TEXTO do log nao
        # tem, lidas do protocolo `RZ1|` que o proprio jogo ja escreve --
        # STAGE, conteudo do LIFE, DON anexado por carta, DON no cost area,
        # deck restante e quais cartas estao RESTADAS. Ver rz1_replay.py
        # (validado: 93,75% dos 14400 snapshots do banco batem exatamente com
        # as linhas de texto, 105 de 120 logs 100%).
        #
        # ADITIVO por construcao: so acrescenta chaves novas e NUNCA
        # sobrescreve `hand`/`board`/`trash`/`life` ja existentes -- se o
        # casamento de dono falhar, o snapshot fica exatamente como era.
        if _rz1_estado is not None:
            try:
                mapa = _rz1_casar(_rz1_estado,
                                  {lado: (snap.get(lado, {}).get('hand') or [])
                                   for lado in (p1, p2)})
                for lado, dono in mapa.items():
                    extra = _rz1_estado.snapshot(dono)
                    destino = snap.setdefault(lado, {})
                    for chave, valor in extra.items():
                        if chave not in destino:
                            destino[chave] = valor
            except Exception:
                pass       # nunca deixa o enriquecimento quebrar o parse

        # Reconcilia o rastreio active/rested pelo board REAL (autoridade)
        # e anexa `rested` (contagem por code) ao snapshot de cada lado.
        for side in (p1, p2):
            _reconcile_board_state(board_state, side,
                                   snap.get(side, {}).get('board', []))
            counts = _board_rested_counts(board_state, side)
            if counts:
                snap.setdefault(side, {})['rested'] = counts

        parsed_turns.append({
            'turn': t_idx + 1,
            'player': player,
            'card_drawn': card_drawn,
            'don_drawn': don_drawn,
            'actions': actions,
            'snapshot': snap,
        })

    data = {
        'meta': {
            'players': {
                'p1': {'name': p1, 'leader': leaders.get(p1, {})},
                'p2': {'name': p2, 'leader': leaders.get(p2, {})},
            },
            'goes_first': goes_first,
        },
        'total_turns': len(parsed_turns),
        'turns': parsed_turns,
    }
    return data, lines


# ---------------------------------------------------------------------------
# Reconstrucao de deck
# ---------------------------------------------------------------------------

def reconstruct_decks(data: dict, raw_lines: list) -> dict:
    """
    Reconstroi a lista de deck de cada jogador.
    Retorna {player: [{code, name, count}, ...]} ordenado por count desc.

    Estrategia:
      1. Para cada snapshot (hand+board+trash simultaneos), conta quantas copias
         de cada codigo estao visiveis ao mesmo tempo.
      2. Toma o maximo por codigo em todos os snapshots.
      3. Complementa com cartas vistas em draw events que nao apareceram nos snapshots.
      4. Remove o lider (nao faz parte do deck de 50).
    """
    p1 = data['meta']['players']['p1']['name']
    p2 = data['meta']['players']['p2']['name']
    leader = {
        p1: data['meta']['players']['p1']['leader'].get('code', ''),
        p2: data['meta']['players']['p2']['leader'].get('code', ''),
    }
    # Nomes vistos no log: {code: name}
    name_map = {}
    for line in raw_lines:
        m = RE_DREW.match(line)
        if m: name_map[m.group(3)] = m.group(2)
        m = RE_DEPLOY.match(line)
        if m: name_map[m.group(3)] = m.group(2)

    # max simultaneous count por jogador e codigo
    max_seen: dict = {p1: {}, p2: {}}

    def _update(player, codes):
        cnt = Counter(codes)
        d = max_seen[player]
        for code, n in cnt.items():
            d[code] = max(d.get(code, 0), n)

    for turn in data['turns']:
        snap = turn.get('snapshot', {})
        for player in (p1, p2):
            if player not in snap:
                continue
            st = snap[player]
            visible = (st.get('hand', []) + st.get('board', [])
                       + st.get('trash', []))
            _update(player, visible)

    # draw events do log (cartas que nunca chegaram a aparecer em snapshot)
    for line in raw_lines:
        m = RE_DREW_RAW.match(line)
        if m:
            p, code = m.group(1), m.group(2)
            if p in max_seen:
                max_seen[p][code] = max(max_seen[p].get(code, 0), 1)
        m = RE_DISCARD.match(line)
        if m:
            p, code = m.group(1), m.group(3)
            if p in max_seen:
                max_seen[p][code] = max(max_seen[p].get(code, 0), 1)

    result = {}
    for player in (p1, p2):
        ldr = leader[player]
        deck = []
        total = 0
        for code, cnt in sorted(max_seen[player].items(),
                                 key=lambda x: -x[1]):
            if code == ldr:
                continue
            deck.append({
                'code': code,
                'name': name_map.get(code, code),
                'count': cnt,
            })
            total += cnt
        result[player] = {'cards': deck, 'total_seen': total,
                          'leader': leader[player]}
    return result


# ---------------------------------------------------------------------------
# Banco de dados de logs
# ---------------------------------------------------------------------------

def _load_index() -> list:
    if DB_INDEX.exists():
        return json.loads(DB_INDEX.read_text(encoding='utf-8'))
    return []


def _save_index(idx: list):
    DB_INDEX.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )


def detectar_vencedor(log_path, p1_name: str, p2_name: str) -> str | None:
    """
    Detecta quem venceu a partida a partir do combat log CRU, sem
    confiar no campo `winner` que o proprio simulador as vezes deixa
    None (achado 28/07, bloco HANDOFF 387 -- o `winner` do index.json e
    cosmetico/nao confiavel na maioria dos logs desta fonte). Heuristica:
    o ultimo ATAQUE registrado antes do fim da partida geralmente e o
    golpe que fecha o jogo (o lado que ataca vence); se alguem desistiu
    (`Quits!`), esse lado perdeu. Validada manualmente contra 2 casos
    confirmados (ver HANDOFF 386/387) antes de virar heuristica padrao.

    Retorna 'p1'/'p2' (mesma convencao ja usada por
    importar_logs_autosaved.py) ou None se nao conseguir determinar.
    """
    try:
        text = Path(log_path).read_text(encoding='utf-8', errors='ignore')
    except (FileNotFoundError, OSError):
        return None

    def _to_p1_p2(bracket_label: str) -> str | None:
        if bracket_label == p1_name:
            return 'p1'
        if bracket_label == p2_name:
            return 'p2'
        return None

    for line in text.splitlines():
        m = re.match(r'\[(.+?)\] Quits!', line)
        if m:
            loser = _to_p1_p2(m.group(1))
            if loser == 'p1':
                return 'p2'
            if loser == 'p2':
                return 'p1'
            return None

    last_attacker = None
    for line in text.splitlines():
        m = re.match(r'\[(.+?)\] .+ attacking ', line)
        if m:
            last_attacker = m.group(1)
    if last_attacker:
        return _to_p1_p2(last_attacker)
    return None


# `You` = Lps_Players[0] = P1 (baixo), `Opponent` = P2 (cima) -- ver
# BotDriver.cs (comentario "Lado do bot em Lps_Players: 0 = 'You' =
# baixo (LoadMyDeck), 1 = 'Opponent' = cima"). O plugin loga essa troca
# como texto puro ("[Bot] agora controla P1 (Shift+P)"), sem timestamp
# proprio de partida -- so da pra saber o estado ATUAL do toggle, nao
# reconstruir o historico por partida se Shift+P foi apertado varias
# vezes na mesma sessao do jogo.
_BOT_SIDE_BY_PLAYER_INDEX = {'1': 'You', '2': 'Opponent'}


def detectar_lado_bot_via_bepinex_log(log_output_path) -> str | None:
    """
    Le o `LogOutput.log` do BepInEx (plugin do bot) e descobre qual lado
    (`You`/`Opponent`) o bot estava controlando -- pedido explicito do
    usuario 28/07 (bloco HANDOFF 388): "nao trate eu como o vencedor,
    quero que leia se o Shift+P esta em P1 ou P2 pra identificar o bot"
    -- em vez de assumir que o usuario sempre venceu (heuristica
    anterior, valida so como fallback quando este dado nao existe).

    Pega a ULTIMA ocorrencia de "agora controla P<N>" no arquivo inteiro
    -- reflete o estado mais recente do toggle Shift+P. Limitacao
    conhecida: se o LogOutput.log acumular VARIAS partidas com trocas de
    lado no meio, isso so da o estado FINAL, nao por partida -- o
    arquivo nao tem timestamp correlacionavel com o combat log oficial.
    Se o usuario trocar de lado no meio de uma sessao de partidas, rode
    isso logo apos cada partida (antes de reabrir o jogo/trocar de novo)
    pra nao perder a correlacao.

    Retorna 'You', 'Opponent', ou None (arquivo nao encontrado, ou
    nenhuma troca de lado registrada nele -- BotDriver.cs comeca em
    BotPlayerIndex=0 ('You') por padrao, mas so registra Shift+P
    EFETIVAMENTE apertado, entao "nenhuma linha" nao prova que e 'You',
    so que nao sabemos -- fica None de proposito, sem assumir).
    """
    try:
        text = Path(log_output_path).read_text(encoding='utf-8', errors='ignore')
    except (FileNotFoundError, OSError):
        return None

    lado = None
    for line in text.splitlines():
        m = re.search(r'agora controla P([12])', line)
        if m:
            lado = _BOT_SIDE_BY_PLAYER_INDEX.get(m.group(1))
    return lado


def _bot_side_to_p1_p2(bepinex_log_path, p1_name: str, p2_name: str) -> str | None:
    """Converte o `You`/`Opponent` de `detectar_lado_bot_via_bepinex_log`
    pra 'p1'/'p2' (mesma convencao de `winner`). None se o caminho nao
    foi dado ou a deteccao falhou -- NAO assume nada nesse caso."""
    if not bepinex_log_path:
        return None
    lado = detectar_lado_bot_via_bepinex_log(bepinex_log_path)
    if lado is None:
        return None
    if lado == p1_name:
        return 'p1'
    if lado == p2_name:
        return 'p2'
    return None


def add_to_db(log_path: str, data: dict, decks: dict, bepinex_log_path=None):
    """
    Copia o .log para logs/raw/, salva o JSON em logs/parsed/,
    salva os decks em logs/decks/ e atualiza o index.json.

    `bepinex_log_path`: caminho opcional pro `LogOutput.log` do BepInEx
    (mesma sessao do jogo) -- se dado, detecta qual lado (`You`/
    `Opponent`) o bot estava controlando via Shift+P
    (`detectar_lado_bot_via_bepinex_log`) e grava em `bot_side`
    ('p1'/'p2'). Sem isso, `bot_side` fica None -- NAO assume mais que
    o usuario e sempre o vencedor (pedido explicito 28/07, bloco
    HANDOFF 388).
    """
    DB_ROOT.mkdir(parents=True, exist_ok=True)
    (DB_ROOT / 'raw').mkdir(exist_ok=True)
    (DB_ROOT / 'parsed').mkdir(exist_ok=True)
    (DB_ROOT / 'decks').mkdir(exist_ok=True)

    log_path = Path(log_path)
    timestamp = log_path.stem   # ex: "2026-07-01T12.46.16"
    if timestamp.endswith('.log'):
        timestamp = timestamp[:-4]

    # Verifica duplicata pelo timestamp. get() em vez de e['id']: entradas
    # antigas do lote 'autosaved_log' (schema diferente, sem campo 'id' --
    # usam 'original_file') quebravam isso com KeyError (achado 09/07).
    idx = _load_index()
    if any(e.get('id') == timestamp for e in idx):
        print(f'  [aviso] {timestamp} ja esta no banco — ignorado.')
        return

    # Monta slugs dos lideres para nome amigavel
    p1d = data['meta']['players']['p1']
    p2d = data['meta']['players']['p2']
    slug1 = _leader_slug(p1d['leader'].get('name', ''), p1d['leader'].get('code', ''))
    slug2 = _leader_slug(p2d['leader'].get('name', ''), p2d['leader'].get('code', ''))
    match_slug = _match_slug(slug1, slug2)
    friendly_stem = f'{match_slug}_{timestamp}'

    # Copia log original com nome amigavel
    raw_dest = DB_ROOT / 'raw' / f'{friendly_stem}.log'
    shutil.copy2(log_path, raw_dest)

    # Salva JSON parsed
    parsed_dest = DB_ROOT / 'parsed' / f'{friendly_stem}.json'
    parsed_dest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )

    # Salva decks
    deck_files = {}
    players_ordered = [p1d['name'], p2d['name']]
    slugs = {p1d['name']: slug1, p2d['name']: slug2}
    for player, deck_data in decks.items():
        player_slug = slugs.get(player, player.replace('#', '_'))
        fname = f'{player_slug}_{timestamp}.json'
        dest  = DB_ROOT / 'decks' / fname
        dest.write_text(
            json.dumps(deck_data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        deck_files[player] = f'decks/{fname}'

    # bloco 656 (pedido do usuario): captura o DECKLIST COMPLETO de cada
    # jogador AGORA, na ingestao, em vez de adivinhar na hora da auditoria.
    # A pasta de decks do simulador e local, nao versionada e MUDA com o tempo
    # -- o snapshot em `logs/decks_full/` torna a reconstrucao fiel,
    # reproduzivel e utilizavel por sessao remota. Ver sim_deck_registry.py.
    deck_full_files = {}
    try:
        from sim_deck_registry import registrar as _registrar_decks
        deck_full_files = _registrar_decks(DB_ROOT, timestamp, [
            {'name': p1d['name'], 'slug': slug1,
             'leader_code': p1d['leader'].get('code', ''),
             'deck_parcial': decks.get(p1d['name'])},
            {'name': p2d['name'], 'slug': slug2,
             'leader_code': p2d['leader'].get('code', ''),
             'deck_parcial': decks.get(p2d['name'])},
        ])
    except Exception as exc:   # nunca deixa o registro derrubar a ingestao
        print(f'  [aviso] decklist completo nao registrado: {exc}')

    # Entrada no index
    entry = {
        'id': timestamp,
        'friendly_name': match_slug,
        'date': timestamp[:10],
        'p1': {'name': p1d['name'],
               'leader_code': p1d['leader'].get('code', ''),
               'leader_name': p1d['leader'].get('name', ''),
               'slug': slug1},
        'p2': {'name': p2d['name'],
               'leader_code': p2d['leader'].get('code', ''),
               'leader_name': p2d['leader'].get('name', ''),
               'slug': slug2},
        'turns': data['total_turns'],
        'winner': detectar_vencedor(log_path, p1d['name'], p2d['name']),
        'bot_side': _bot_side_to_p1_p2(bepinex_log_path, p1d['name'], p2d['name']),
        'log_file': f'raw/{friendly_stem}.log',
        'parsed_file': f'parsed/{friendly_stem}.json',
        'deck_files': deck_files,
        # snapshot do decklist COMPLETO (50 cartas) por jogador -- vazio
        # quando o lider nao tem deck na pasta do simulador, e isso fica
        # VISIVEL aqui em vez de virar fallback silencioso
        'deck_full_files': deck_full_files,
    }
    idx.append(entry)
    _save_index(idx)
    print(f'  Adicionado ao banco: {friendly_stem}')
    print(f'    {p1d["name"]} ({slug1}) vs {p2d["name"]} ({slug2})')
    for player, deck_data in decks.items():
        total = deck_data['total_seen']
        n_unique = len(deck_data['cards'])
        print(f'    deck {player}: {n_unique} codigos unicos, '
              f'{total} cartas vistas (de 50)')


def list_db():
    idx = _load_index()
    if not idx:
        print('Banco vazio. Use --add-to-db para adicionar partidas.')
        return
    print(f'\n{"Data":10s}  {"Partida":52s}  Turnos')
    print('-' * 72)
    for e in idx:
        # Entradas antigas do lote 'autosaved_log' (schema diferente, sem
        # 'date'/'turns' -- usam 'original_file'/'total_turns') quebravam
        # isto com KeyError (achado 09/07, mesma causa do bug em add_to_db).
        date = e.get('date') or e.get('original_file', '')[:10] or '?'
        turns = e.get('turns', e.get('total_turns', '?'))
        slug1 = e['p1'].get('slug') or e['p1']['leader_code']
        slug2 = e['p2'].get('slug') or e['p2']['leader_code']
        match = f"{e['p1']['name'][:10]}({slug1}) x {e['p2']['name'][:10]}({slug2})"
        print(f"{date:10s}  {match[:52]:52s}  {turns}")
    print(f'\nTotal: {len(idx)} partidas\n')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_snap(lines, start):
    result, j = [], start
    while j < len(lines) and j < start + 30:
        l = _clean(lines[j])
        if RE_HAND.match(l) or RE_BOARD.match(l) or RE_TRASH.match(l) or RE_LIFE.match(l):
            result.append(l); j += 1
        elif l.startswith('RZ1') or not l:
            j += 1
        else:
            break
    return result


def _skip_snap(lines, start):
    j = start
    while j < len(lines) and j < start + 30:
        l = _clean(lines[j])
        if RE_HAND.match(l) or RE_BOARD.match(l) or RE_TRASH.match(l) or RE_LIFE.match(l):
            j += 1
        elif l.startswith('RZ1') or not l:
            j += 1
        else:
            break
    return j


def _build_known_codes(raw_lines, p1, p2):
    """
    Codigos de carta ja vistos com tag REAL ([You]/[Opponent], via Deploy/
    Draw/Attack/etc, que sempre tem tag preenchida) -- usado por _parse_snap
    pra atribuir os blocos de snapshot com tag VAZIA por CRUZAMENTO de
    carta, nao posicao (achado 14/07: a ordem do par de snapshot NAO e fixa
    -- o par logo apos o mulligan sai numa ordem, os pares seguintes saem
    na ordem OPOSTA -- atribuicao posicional simples deu resultado
    invertido num teste real).
    """
    known = {p1: set(), p2: set()}
    for line in raw_lines:
        for tag in (p1, p2):
            if line.startswith(f'[{tag}]'):
                known[tag].update(RE_CARD_REF.findall(line))
                break
    return known


def _parse_snap(snap_lines, p1=None, p2=None, known_codes=None):
    """
    A maioria dos snapshots do jogo vem com tag VAZIA (`[] Hand: [...]`),
    sempre em blocos de 4 linhas (1x Hand/Board/Trash/Life, ORDEM interna
    varia) por jogador -- achado 14/07: sem atribuicao, esses blocos
    ficavam colididos numa chave '' ou eram descartados (regex antiga nem
    casava tag vazia). A ordem do PAR (quem vem primeiro) NAO e fixa entre
    blocos -- por isso a atribuicao e por CRUZAMENTO de codigo de carta
    contra `known_codes` (cartas ja vistas com tag real de cada lado),
    nao por posicao. Fallback pra alternancia posicional so se nenhuma
    carta do bloco bater com nenhum lado (bloco bem no inicio do jogo,
    antes de qualquer acao tagueada).
    """
    known_codes = known_codes or {}
    snap = {}
    bloco_linhas, bloco_dono_fixo = [], None
    tag_atual, count_no_bloco = None, 0

    def _flush(linhas, dono):
        for line in linhas:
            m = RE_HAND.match(line)
            if m: snap.setdefault(dono, {})['hand']  = _codes(m.group(2)); continue
            m = RE_BOARD.match(line)
            if m: snap.setdefault(dono, {})['board'] = _codes(m.group(2)); continue
            m = RE_TRASH.match(line)
            if m: snap.setdefault(dono, {})['trash'] = _codes(m.group(2)); continue
            m = RE_LIFE.match(line)
            if m: snap.setdefault(dono, {})['life']  = int(m.group(2))

    for line in snap_lines:
        m = RE_HAND.match(line) or RE_BOARD.match(line) or RE_TRASH.match(line) or RE_LIFE.match(line)
        if not m:
            continue
        tag = m.group(1)
        if tag:
            _flush([line], tag)
            continue

        bloco_linhas.append(line)
        count_no_bloco += 1
        if count_no_bloco == 4:
            codigos_bloco = set()
            for l in bloco_linhas:
                codigos_bloco.update(RE_CARD_REF.findall(l) or _codes(
                    (RE_HAND.match(l) or RE_BOARD.match(l) or RE_TRASH.match(l)).group(2)
                ) if (RE_HAND.match(l) or RE_BOARD.match(l) or RE_TRASH.match(l)) else [])
            score_p1 = len(codigos_bloco & known_codes.get(p1, set()))
            score_p2 = len(codigos_bloco & known_codes.get(p2, set()))
            if score_p1 != score_p2:
                dono = p1 if score_p1 > score_p2 else p2
            else:
                # empate (ou bloco sem cruzamento nenhum): alterna por
                # posicao como ultimo recurso
                tag_atual = p1 if (tag_atual is None or tag_atual == p2) else p2
                dono = tag_atual
            _flush(bloco_linhas, dono)
            bloco_linhas, count_no_bloco = [], 0

    return snap


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(data: dict, decks: dict):
    meta = data['meta']
    p1   = meta['players']['p1']
    p2   = meta['players']['p2']
    print(f'\n{"="*65}')
    print(f'  {p1["name"]} ({p1["leader"]["name"]}) vs '
          f'{p2["name"]} ({p2["leader"]["name"]})')
    print(f'  Primeiro: {meta.get("goes_first") or "?"} | '
          f'{data["total_turns"]} turnos')
    print(f'{"="*65}')

    for t in data['turns']:
        if not t.get('player'):
            continue
        snap = t['snapshot']
        p    = t['player']
        opp  = next((k for k in snap if k != p), None)

        life_p = snap.get(p,   {}).get('life', '?')
        life_o = snap.get(opp, {}).get('life', '?') if opp else '?'
        board  = snap.get(p,   {}).get('board', [])
        drawn  = t['card_drawn']['code'] if t['card_drawn'] else '-'

        plays  = [a for a in t['actions'] if a['type'] == 'play']
        acts   = [a for a in t['actions'] if a['type'] == 'activate']
        atks   = [a for a in t['actions'] if a['type'] == 'attack']

        print(f'\n  T{t["turn"]:02d} {p[:18]:18s} | '
              f'+{t["don_drawn"]}DON drew={drawn}')
        print(f'       vida: eu={life_p}  opp={life_o}  board={len(board)} chars')
        for a in plays:
            fx = '  -> ' + ' | '.join(a['effects'][:2]) if a['effects'] else ''
            print(f'       > play  {a["card"]:12s} {a["card_name"][:22]}{fx}')
        for a in acts:
            fx = '  -> ' + ' | '.join(a.get('effects', [])[:2])
            print(f'       * activ {a["card"]:12s} {a["card_name"][:22]}{fx}')
        for a in atks:
            res = f'HIT({a["damage"]})' if a['result'] == 'hit' else 'BLOCKED'
            blk = f'  [bloq: {a["blocked_by"][:10]}]' if a['blocked_by'] else ''
            ctr = f'  [ctr: {",".join(a["countered_by"][:2])}]' if a['countered_by'] else ''
            print(f'       ! atk   {a["attacker"][:18]} -> {res}{blk}{ctr}')

    # Decks reconstruidos
    print(f'\n{"="*65}')
    print('  DECKS RECONSTRUIDOS')
    print(f'{"="*65}')
    for player, deck_data in decks.items():
        total  = deck_data['total_seen']
        cards  = deck_data['cards']
        leader = deck_data['leader']
        print(f'\n  [{player}] lider={leader} | {total}/50 cartas vistas')
        for c in cards:
            print(f'    {c["count"]}x {c["code"]:12s} {c["name"][:35]}')


def split_multigame_log(log_path: str) -> list[str]:
    """
    Um arquivo .log pode conter VARIAS partidas concatenadas (rematch salvo
    no mesmo download) -- achado 14/07: um arquivo real tinha 2 partidas,
    a 2a com os lados [You]/[Opponent] TROCADOS em relacao a 1a (mesmo
    jogador, deck diferente por partida). Processar como uma partida so
    corrompe a reconstrucao de estado (mistura mao/campo de 2 jogos
    diferentes). Detecta por "Version is" (aparece 1x no INICIO de cada
    partida) e escreve cada uma em um .log temporario separado (sufixo
    _p2, _p3...), devolvendo os caminhos. Se so ha 1 partida, devolve
    [log_path] sem tocar em nada.
    """
    raw = Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines()
    starts = [i for i, l in enumerate(raw) if l.strip().startswith('Version is')]
    if len(starts) <= 1:
        return [log_path]

    paths = []
    base = Path(log_path)
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(raw)
        segmento = raw[start:end]
        sufixo = '' if idx == 0 else f'_p{idx + 1}'
        out_path = base.with_name(f'{base.stem}{sufixo}{base.suffix}')
        out_path.write_text('\n'.join(segmento), encoding='utf-8')
        paths.append(str(out_path))
    return paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='Parse OPTCG combat log -> JSON + banco')
    ap.add_argument('log_file',  nargs='?', help='Caminho para o .log')
    ap.add_argument('--output',  '-o',      help='Arquivo de saida .json')
    ap.add_argument('--summary', '-s', action='store_true',
                    help='Imprimir resumo e decks no terminal')
    ap.add_argument('--add-to-db', action='store_true',
                    help='Adicionar esta partida ao banco (logs/)')
    ap.add_argument('--list-db', action='store_true',
                    help='Listar partidas no banco')
    ap.add_argument('--bepinex-log', default=None,
                    help='Caminho pro LogOutput.log do BepInEx (mesma sessao) -- '
                         'detecta qual lado (You/Opponent) o bot controlava via '
                         'Shift+P, gravado em bot_side no index.json. Sem isso, '
                         'bot_side fica None (nao assume mais que o usuario '
                         'venceu -- pedido 28/07, bloco HANDOFF 388).')
    args = ap.parse_args()

    if args.list_db:
        list_db()
        return

    if not args.log_file:
        ap.print_help()
        return

    sub_logs = split_multigame_log(args.log_file)
    if len(sub_logs) > 1:
        print(f'Detectadas {len(sub_logs)} partidas concatenadas no mesmo arquivo -- separando.')

    for log_file in sub_logs:
        print(f'Parseando {log_file} ...')
        data, raw_lines = parse_log(log_file)

        out = (args.output if len(sub_logs) == 1 and args.output
               else str(Path(log_file).with_suffix('.json')))
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'OK {data["total_turns"]} turnos -> {out}')

        decks = reconstruct_decks(data, raw_lines)

        if args.summary:
            print_summary(data, decks)

        if args.add_to_db:
            add_to_db(log_file, data, decks, bepinex_log_path=args.bepinex_log)


if __name__ == '__main__':
    main()
