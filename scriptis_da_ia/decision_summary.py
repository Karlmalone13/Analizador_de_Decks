#!/usr/bin/env python3
"""
decision_summary.py -- Resumo legivel das decisoes do bot numa partida: pra
cada decisao com scored_actions, mostra o que foi ESCOLHIDO e as melhores
ALTERNATIVAS descartadas, pra calibrar o motor sem vasculhar o JSONL na
mao (pedido do usuario 23/07: leitura de telemetria vira obrigatoria toda
vez que um log de partida do bot entra no banco -- ver CLAUDE.md).

Le o receipt que o auto-collect grava em metrics/live_runs/ (liga
bank_entry_id + decision_log + match_id) e escreve um .txt legivel ao lado
dele -- fica junto da telemetria, nao so uma consulta ad-hoc.

Uso:
    python decision_summary.py --latest
    python decision_summary.py --receipt metrics/live_runs/receipt_<ts>.json
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent
LIVE_RUNS = ROOT / 'metrics' / 'live_runs'


def _load(path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _latest_receipt() -> Path:
    receipts = sorted(LIVE_RUNS.glob('receipt_*.json'))
    if not receipts:
        raise SystemExit('nenhum receipt encontrado em metrics/live_runs/')
    return receipts[-1]


def _fmt_action(a: dict | None) -> str:
    if a is None:
        return '(nenhuma)'
    parts = [str(a.get('type', '?'))]
    if a.get('card_code'):
        parts.append(str(a['card_code']))
    if a.get('target_type'):
        alvo = str(a['target_type'])
        if a.get('target_code'):
            alvo += f':{a["target_code"]}'
        parts.append(f'-> {alvo}')
    score = a.get('score')
    txt = ' '.join(parts)
    return f'{txt} (score={score:.1f})' if isinstance(score, (int, float)) else txt


def _same_action(a: dict, b: dict | None) -> bool:
    if not b:
        return False
    return (a.get('type') == b.get('type')
            and a.get('card_code') == b.get('card_code')
            and a.get('target_code') == b.get('target_code'))


def summarize(receipt_path: Path) -> str:
    receipt = _load(receipt_path)
    match_id = receipt['match_id']
    decision_log = Path(receipt['decision_log'])
    out = [f"# Resumo de decisoes -- {receipt.get('canonical_name', match_id)}",
           f"match_id={match_id}",
           f"decision_log={decision_log}"]
    if not decision_log.exists():
        out.append('')
        out.append('(decision_log nao encontrado no disco -- so o receipt sobreviveu)')
        return '\n'.join(out)

    count = 0
    corpo = []
    with decision_log.open(encoding='utf-8') as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if d.get('match_id') != match_id:
                continue
            kind = d.get('decision_kind')
            scored = d.get('scored_actions') or []
            chosen = d.get('chosen_action')
            if kind is None or (not scored and chosen is None):
                continue
            count += 1
            corpo.append(f"## turno {d.get('turn')} -- {kind}")
            corpo.append(f"  escolhido: {_fmt_action(chosen)}")
            elegiveis = sorted(
                (a for a in scored if a.get('eligible')),
                key=lambda a: a.get('score', 0), reverse=True)
            alternativas = [a for a in elegiveis if not _same_action(a, chosen)]
            for alt in alternativas[:3]:
                corpo.append(f"    alternativa: {_fmt_action(alt)}")
            corpo.append('')

    out.insert(3, f"decisoes com opcoes registradas: {count}")
    out.append('')
    out.extend(corpo)
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt', help='caminho do receipt_<ts>.json')
    ap.add_argument('--latest', action='store_true', help='usa o receipt mais recente')
    ap.add_argument('--out', help='onde salvar (default: ao lado do receipt)')
    args = ap.parse_args()

    receipt_path = Path(args.receipt) if args.receipt and not args.latest else _latest_receipt()
    texto = summarize(receipt_path)
    out_path = Path(args.out) if args.out else receipt_path.with_name(
        receipt_path.name.replace('receipt_', 'decisions_summary_').replace('.json', '.txt'))
    out_path.write_text(texto, encoding='utf-8')
    print(f'Resumo salvo em {out_path}')


if __name__ == '__main__':
    main()
