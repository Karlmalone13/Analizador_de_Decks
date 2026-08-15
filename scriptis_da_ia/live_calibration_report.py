"""
Relatorio pra investigar, numa sessao AO VIVO ja jogada, duas coisas que a
telemetria existente nao juntava antes:

1. QUANTO as flags de calibragem dinamica por curva do deck (USE_*_CURVE_
   SCALE, decision_engine.py, blocos 529-533) realmente pesaram nas
   decisoes reais dessa sessao -- usa o campo `calibration_scales` novo em
   `trace_out` (sim_bridge.choose_action, bloco 541), exposto so a partir
   deste commit. Sessoes ANTERIORES a este fix nao tem esse campo --
   aparece como "sem dado" no relatorio, nao um erro.
2. Deteccao automatica do padrao de bug ja visto varias vezes nesta sessao
   (blocos 371-374, 540): a MESMA acao (tipo/carta/alvo) sendo escolhida
   3+ vezes dentro do mesmo turno -- sinal de que o "Cancel" de selecao
   parcial (ou outro loop parecido) esta acontecendo de novo, mesmo sem
   olhar o LogOutput.log do plugin (que e local/gitignored e pode nao
   estar disponivel).

Uso:
    python live_calibration_report.py                  # sessao mais recente
    python live_calibration_report.py --session <nome>  # decisions_<nome>.jsonl
    python live_calibration_report.py --file <caminho.jsonl>
"""
import argparse
import glob
import json
import os
from collections import defaultdict

DECISIONS_DIR = os.path.join('..', 'BOT', 'engine_server', 'logs', 'decisions')


def _latest_decisions_file() -> str | None:
    files = sorted(glob.glob(os.path.join(DECISIONS_DIR, 'decisions_*.jsonl')))
    return files[-1] if files else None


def _load(path: str) -> list[dict]:
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def report_calibration(decisions: list[dict]) -> None:
    print('== Flags de calibragem dinamica (USE_*_CURVE_SCALE) ==')
    com_dado = [d for d in decisions
               if d.get('event') == 'decision' and d.get('decision_kind') == 'main'
               and d.get('calibration_scales')]
    total_main = sum(1 for d in decisions
                     if d.get('event') == 'decision' and d.get('decision_kind') == 'main')
    if not com_dado:
        print(f'  Sem dado -- 0 de {total_main} decisoes de main tem '
              f'`calibration_scales` (sessao rodou com codigo anterior ao '
              f'bloco 541, ou as flags simplesmente nunca foram lidas).')
        return

    print(f'  {len(com_dado)} de {total_main} decisoes de main com dado.')
    perfis = defaultdict(int)
    somas = defaultdict(float)
    ativos = defaultdict(int)  # quantas vezes o fator != 1.0
    for d in com_dado:
        cs = d['calibration_scales']
        perfis[cs.get('profile', '?')] += 1
        for termo, valor in cs.items():
            if termo == 'profile':
                continue
            somas[termo] += valor
            if abs(valor - 1.0) > 1e-6:
                ativos[termo] += 1

    print(f'  Perfil do deck por decisao: {dict(perfis)}')
    print(f'  {"termo":<16} {"media":>8} {"ativo (!=1.0)":>16}')
    for termo in sorted(somas):
        media = somas[termo] / len(com_dado)
        print(f'  {termo:<16} {media:>8.3f} {ativos.get(termo, 0):>10}/{len(com_dado)}')
    print()


def report_repeated_action_bug(decisions: list[dict]) -> None:
    print('== Deteccao do padrao "mesma acao 3x+ no mesmo turno" (bloco 371-374/540) ==')
    por_match_turno = defaultdict(list)
    for d in decisions:
        if d.get('event') != 'decision' or d.get('decision_kind') != 'main':
            continue
        ca = d.get('chosen_action') or {}
        if not ca.get('type'):
            continue
        chave = (ca.get('type'), ca.get('card_code'), ca.get('card_uid'),
                ca.get('target_uid'))
        por_match_turno[(d.get('match_id'), d.get('turn'))].append(chave)

    achados = []
    for (match_id, turno), acoes in por_match_turno.items():
        contagem = defaultdict(int)
        for a in acoes:
            contagem[a] += 1
        for chave, n in contagem.items():
            if n >= 3:
                achados.append((match_id, turno, chave, n))

    if not achados:
        print('  Nenhum padrao suspeito encontrado -- bom sinal.')
        print()
        return

    print(f'  {len(achados)} caso(s) suspeito(s) (mesma acao 3x+ no mesmo turno):')
    for match_id, turno, (tipo, carta, uid, alvo), n in achados:
        print(f'    match={(match_id or "")[:8]} turno={turno} '
              f'{tipo} {carta} uid={uid} alvo={alvo} -> {n}x')
    print()


def report_execution_failures(decisions: list[dict]) -> None:
    print('== Execucoes com status="failed" (acao enviada, jogo nao mudou) ==')
    falhas = [d for d in decisions if d.get('event') == 'execution'
             and d.get('status') == 'failed']
    if not falhas:
        print('  Nenhuma.')
        print()
        return
    print(f'  {len(falhas)} falha(s):')
    for f in falhas[:20]:
        print(f'    decision_id={f.get("decision_id", "")[:8]} erro={f.get("error")}')
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--session', help='nome da sessao (decisions_<nome>.jsonl)')
    ap.add_argument('--file', help='caminho direto pro .jsonl')
    args = ap.parse_args()

    if args.file:
        path = args.file
    elif args.session:
        path = os.path.join(DECISIONS_DIR, f'decisions_{args.session}.jsonl')
    else:
        path = _latest_decisions_file()

    if not path or not os.path.exists(path):
        print(f'Log de decisoes nao encontrado: {path}')
        return 1

    print(f'Lendo {path}\n')
    decisions = _load(path)
    report_calibration(decisions)
    report_repeated_action_bug(decisions)
    report_execution_failures(decisions)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
