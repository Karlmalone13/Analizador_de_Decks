# -*- coding: utf-8 -*-
"""Recupera `bot_side` dos registros ANONIMOS cruzando com os recibos de
partida ao vivo (bloco 803, item 2 da proposta do usuario).

## Por que o indice sozinho nao resolve

Nos logs `You`/`Opponent`, o nome diz de quem e a PERSPECTIVA do log, nao quem
era o bot. Prova, no proprio banco: nos registros que TEM `bot_side`, `p1` e
sempre `You` e mesmo assim `bot_side` varia entre p1 e p2 -- houve log exportado
da perspectiva do HUMANO, com o bot do outro lado.

## O sinal externo

`metrics/live_runs/receipt_*.json` so existe quando **o BOT jogou** -- e cada
recibo aponta pro registro do banco (`bank_entry_id`, `bank_parsed`,
`canonical_name`). Entao:

    recibo aponta pro registro  ->  o bot jogou essa partida
    nenhum recibo aponta        ->  provavelmente nao foi partida do bot

O LADO vem do `decision_log` do recibo, que grava as decisoes do bot com o
`player_id`. Sem esse campo, marcamos apenas que HOUVE bot, sem cravar o lado --
meia resposta e melhor que resposta errada.

## Honestidade do metodo

Isto e INFERENCIA, nao registro. O resultado vai em `bot_side_origem` como
`recibo_live_run`, separado do dado firme (`bepinex_log`/declarado). Uma sessao
futura que precise de rigor pode filtrar so o firme.

RESSALVA: `metrics/live_runs/` e gitignored e LOCAL. Numa sessao remota este
script nao tem o que cruzar, e deve dizer isso em vez de marcar nada.

Uso:
    python recupera_bot_side.py            # mostra o que faria
    python recupera_bot_side.py --aplicar  # grava
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
from pathlib import Path

RAIZ = Path(__file__).parent
INDEX = RAIZ / 'logs' / 'index.json'
LIVE = RAIZ / 'metrics' / 'live_runs'
ANONIMOS = {'You', 'Opponent'}


def cartas_que_o_bot_jogou(caminho) -> set:
    """Codigos que o BOT escolheu jogar, lidos do `chosen_action`.

    O `decision_log` NAO grava de que lado o bot estava -- conferido: o
    `state_before` so tem `hand`. Mas grava O QUE ele decidiu, e o log da
    partida grava o que CADA lado jogou. Cruzando os dois, o lado sai.
    """
    try:
        p = Path(caminho)
        if not p.is_absolute():
            p = RAIZ / p
        if not p.exists():
            return set()
        codigos = set()
        with p.open(encoding='utf-8', errors='replace') as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    d = json.loads(linha)
                except Exception:
                    continue
                ca = d.get('chosen_action') or {}
                cod = ca.get('card_code')
                if cod:
                    codigos.add(str(cod))
        return codigos
    except Exception:
        return set()


def lado_por_cartas(parsed_file, codigos_bot) -> str | None:
    """Qual lado do log jogou as cartas que o bot decidiu jogar.

    Conta, por jogador do log (`You`/`Opponent`), quantos codigos batem. O
    lado com MAIS coincidencias e o bot -- e so aceita quando a diferenca e
    clara (o dobro do outro, com pelo menos 3 coincidencias), pra nao cravar
    lado em empate.
    """
    if not codigos_bot:
        return None
    try:
        p = RAIZ / 'logs' / parsed_file
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding='utf-8'))
        por_jogador = collections.Counter()
        for t in (d.get('turns') or []):
            quem = t.get('player')
            texto = json.dumps(t.get('actions') or [], ensure_ascii=False)
            for cod in codigos_bot:
                if cod in texto:
                    por_jogador[quem] += 1
        if len(por_jogador) < 1:
            return None
        (lider, n), *resto = por_jogador.most_common()
        segundo = resto[0][1] if resto else 0
        if n < 3 or n < 2 * max(1, segundo):
            return None
        # `You` e sempre p1 no indice (a perspectiva do log), `Opponent` p2
        return {'You': 'p1', 'Opponent': 'p2'}.get(lider)
    except Exception:
        return None


def _antigo_lado_do_decision_log(caminho) -> str | None:
    """(sem uso) 'p1'/'p2' pelo player_id -- o campo nao existe no log."""
    try:
        p = Path(caminho)
        if not p.is_absolute():
            p = RAIZ / p
        if not p.exists():
            return None
        ids = collections.Counter()
        with p.open(encoding='utf-8', errors='replace') as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    d = json.loads(linha)
                except Exception:
                    continue
                pid = d.get('player_id') or d.get('player')
                if pid:
                    ids[str(pid).upper()] += 1
        if not ids:
            return None
        maior = ids.most_common(1)[0][0]
        return {'A': 'p1', 'B': 'p2', 'P1': 'p1', 'P2': 'p2'}.get(maior)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--aplicar', action='store_true')
    args = ap.parse_args()

    if not LIVE.exists():
        print()
        print('  metrics/live_runs/ NAO EXISTE nesta maquina.')
        print('  Ele e gitignored e local-only: so existe no disco de quem')
        print('  rodou o bot. Sem ele nao ha o que cruzar -- nada foi marcado.')
        return 0

    recibos = sorted(LIVE.glob('receipt_*.json'))
    por_entrada, por_parsed = {}, {}
    for f in recibos:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        alvo = {'recibo': f.name,
                'cartas': cartas_que_o_bot_jogou(d.get('decision_log') or '')}
        if d.get('bank_entry_id'):
            por_entrada[str(d['bank_entry_id'])] = alvo
        for chave in ('bank_parsed', 'canonical_name'):
            if d.get(chave):
                por_parsed[Path(str(d[chave])).name] = alvo

    dados = json.loads(INDEX.read_text(encoding='utf-8'))
    regs = dados if isinstance(dados, list) else dados.get('logs', [])

    com_lado, so_tinha_bot, sem_recibo = [], [], 0
    for r in regs:
        if r.get('bot_side') or r.get('tipo') == 'humano_vs_humano':
            continue
        n1 = (r.get('p1') or {}).get('name')
        if n1 not in ANONIMOS:
            continue
        achado = (por_entrada.get(str(r.get('id')))
                  or por_parsed.get(Path(str(r.get('parsed_file') or '')).name))
        if not achado:
            sem_recibo += 1
        elif lado_por_cartas(r.get('parsed_file') or '', achado.get('cartas')):
            achado['lado'] = lado_por_cartas(r.get('parsed_file') or '',
                                             achado.get('cartas'))
            com_lado.append((r, achado))
        else:
            so_tinha_bot.append((r, achado))

    print()
    print('  recibos de partida ao vivo      : %d' % len(recibos))
    print('  anonimos sem bot_side           : %d'
          % (len(com_lado) + len(so_tinha_bot) + sem_recibo))
    print('    -> LADO recuperado            : %d' % len(com_lado))
    print('    -> houve bot, lado incerto    : %d' % len(so_tinha_bot))
    print('    -> sem recibo (provavel humano): %d' % sem_recibo)

    if not args.aplicar:
        print()
        print('  (simulacao -- rode com --aplicar pra gravar)')
        return 0

    for r, a in com_lado:
        r['bot_side'] = a['lado']
        r['bot_side_origem'] = 'recibo_live_run:%s' % a['recibo']
    for r, a in so_tinha_bot:
        r['tipo'] = 'com_bot'
        r['bot_side_origem'] = 'recibo_live_run (lado nao recuperado):%s' % a['recibo']

    shutil.copyfile(INDEX, INDEX.with_suffix('.json.bak2'))
    INDEX.write_text(json.dumps(dados, indent=2, ensure_ascii=False),
                     encoding='utf-8')
    print()
    print('  gravado (backup em index.json.bak2)')
    print('  INFERENCIA, nao registro: marcado em `bot_side_origem`.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
