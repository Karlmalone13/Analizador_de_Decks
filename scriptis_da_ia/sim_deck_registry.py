"""
sim_deck_registry.py -- registro do DECKLIST COMPLETO de cada jogador,
capturado no momento em que o log entra no banco.

POR QUE EXISTE (pedido do usuario, 23/08/2026, bloco 656)
---------------------------------------------------------
A reconstrucao de partidas (`audit_real_losses.audit_one_game`) precisa das
50 cartas de cada lado. Ate o bloco 655 ela montava o deck por SEMELHANCA DE
NOME em `decklists_raw.csv` -- e o resultado medido foi que **em 97,7% das
amostras do `OpponentModel` pelo menos uma carta que o oponente REALMENTE
tinha na mao nao existia no baralho assumido**. O motor nao via demais: ele
modelava o oponente ERRADO.

O deck de verdade sempre esta na pasta de decks do proprio simulador. Mas ler
essa pasta na hora da AUDITORIA e fragil por tres motivos:

  1. A pasta e LOCAL e nao versionada -- sessao remota/nuvem nao tem acesso e
     cai em silencio no fallback ruim.
  2. Ela MUDA com o tempo (o usuario cria decks novos, edita, apaga). Um log
     de julho auditado em setembro pode casar com um deck que nem existia, ou
     nao achar mais o que foi usado.
  3. Varios arquivos compartilham o mesmo lider (ex: 4 "Barba Negra") -- o
     desempate precisa das cartas observadas NAQUELA partida, informacao que
     esta fresca na ingestao e mais cara de recuperar depois.

Solucao: **capturar o decklist no momento da ingestao** (`parse_combat_log.py
--add-to-db`) e gravar um SNAPSHOT versionado em `logs/decks_full/`, junto do
raw/parsed/decks que o banco ja guarda. A auditoria le o snapshot primeiro --
reproduzivel, funciona em qualquer maquina, e imune a mudanca posterior na
pasta do jogo.

Diferenca pro que ja existia em `logs/decks/`: aqueles sao decks
RECONSTRUIDOS do que apareceu na partida -- parciais, mediana de 15 cartas de
50 (medido em 236 arquivos). Servem de piso pra desempate, nao de fonte.

FONTE
-----
`E:\\Games\\OnePieceSimulador\\Builds_Windows\\Decks` (override por
`OPTCG_SIM_DECKS_DIR`). Formato `NxCODIGO` por linha, PRIMEIRA carta = o
lider. Medido em 23/08: 39 arquivos, 38 completos (51 linhas-carta = lider +
50), cobrindo 30 lideres distintos = **92% dos 300 lados de partida do
banco**.
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter
from pathlib import Path

SIM_DECKS_DIR = os.environ.get(
    'OPTCG_SIM_DECKS_DIR',
    r'E:\Games\OnePieceSimulador\Builds_Windows\Decks')

_LINHA_RE = re.compile(r'^\s*(\d+)x([A-Za-z0-9\-]+)')
_cache = None


def carregar_decks_do_simulador(force: bool = False) -> dict:
    """{leader_code: [(nome_do_arquivo, Counter{codigo: qtd} SEM o lider)]}

    Silencioso quando a pasta nao existe (sessao remota) -- o chamador decide
    o que fazer com o dicionario vazio.
    """
    global _cache
    if _cache is not None and not force:
        return _cache
    por_lider: dict = {}
    try:
        arquivos = glob.glob(os.path.join(SIM_DECKS_DIR, '*.deck'))
    except OSError:
        arquivos = []
    for caminho in arquivos:
        linhas = []
        try:
            with open(caminho, encoding='utf-8', errors='replace') as fh:
                for ln in fh:
                    m = _LINHA_RE.match(ln.strip())
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
    _cache = por_lider
    return por_lider


def escolher_deck(leader_code: str, observed_codes=None) -> tuple | None:
    """(nome_do_arquivo, Counter) do deck do simulador pra este lider.

    Com varios candidatos pro mesmo lider (29,3% dos casos medidos), escolhe o
    que melhor COBRE as cartas observadas daquele jogador naquela partida --
    contagem de sobreposicao com multiplicidade, nao so presenca, pra
    distinguir versoes que diferem na quantidade de copias.
    """
    if not leader_code:
        return None
    candidatos = carregar_decks_do_simulador().get(leader_code)
    if not candidatos:
        return None
    obs = Counter(observed_codes or [])
    if len(candidatos) > 1 and obs:
        def cobertura(item):
            corpo = item[1]
            return sum(min(q, corpo.get(c, 0)) for c, q in obs.items())
        candidatos = sorted(candidatos, key=cobertura, reverse=True)
    return candidatos[0]


def _observadas_do_deck_parcial(deck_data: dict) -> list:
    """Cartas vistas na partida, do deck RECONSTRUIDO que o banco ja grava."""
    fora = []
    for c in (deck_data or {}).get('cards', []) or []:
        code = c.get('code')
        if code:
            fora.extend([code] * int(c.get('count') or 1))
    return fora


def registrar(db_root: Path, timestamp: str, jogadores: list) -> dict:
    """Grava o snapshot do decklist completo de cada jogador.

    `jogadores`: lista de dicts {'name', 'slug', 'leader_code', 'deck_parcial'}.
    Retorna {nome_do_jogador: caminho_relativo} pra ir no `index.json`.

    Jogador cujo lider nao tem deck na pasta (8% medido, ou pasta ausente)
    simplesmente nao entra no dicionario -- a auditoria cai no fallback e isso
    fica VISIVEL no index em vez de silencioso.
    """
    destino_dir = Path(db_root) / 'decks_full'
    destino_dir.mkdir(parents=True, exist_ok=True)
    saida = {}
    for j in jogadores:
        escolhido = escolher_deck(j.get('leader_code'),
                                  _observadas_do_deck_parcial(j.get('deck_parcial')))
        if not escolhido:
            continue
        nome_arquivo, corpo = escolhido
        slug = j.get('slug') or (j.get('name') or 'jogador').replace('#', '_')
        fname = f'{slug}_{timestamp}.json'
        conteudo = {
            'leader': j.get('leader_code'),
            'source_deck': nome_arquivo,
            'source_dir': SIM_DECKS_DIR,
            'captured_at_ingest': True,
            'cards': [{'code': c, 'count': n} for c, n in sorted(corpo.items())],
            'total': sum(corpo.values()),
        }
        (destino_dir / fname).write_text(
            json.dumps(conteudo, ensure_ascii=False, indent=2), encoding='utf-8')
        saida[j['name']] = f'decks_full/{fname}'
    return saida


def carregar_snapshot(db_root: Path, caminho_relativo: str) -> tuple | None:
    """(leader_code, Counter{codigo: qtd}) de um snapshot ja gravado."""
    if not caminho_relativo:
        return None
    p = Path(db_root) / caminho_relativo
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    corpo = Counter()
    for c in d.get('cards', []) or []:
        if c.get('code'):
            corpo[c['code']] += int(c.get('count') or 1)
    if not corpo:
        return None
    return d.get('leader'), corpo
