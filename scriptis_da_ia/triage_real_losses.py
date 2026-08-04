"""
Triagem dos relatórios gerados por `audit_real_losses.py`
(`metrics/real_loss_audits/*.json`): para cada turno auditado, compara a
ação HISTÓRICA (o que o bot fez de verdade na derrota real) com a
narrativa do motor de HOJE, e classifica em:

- MATCH: motor de hoje faz basicamente a mesma coisa (mesmas cartas
  jogadas/ativadas, mesmo padrão de ataque) -- decisão HOJE ainda seria a
  mesma que perdeu a partida real. Candidato a investigação de causa raiz.
- DIVERGE: motor de hoje faz algo visivelmente diferente -- ou um fix já
  aplicado explica a diferença (bom sinal), ou é um comportamento novo
  ainda não investigado.
- ERROR: turno com erro na reconstrução (audit_real_losses.py já isola
  isso por turno, não derruba a auditoria).

Comparação é HEURÍSTICA (nomes de carta truncados/normalizados, contagem
de ataques) -- serve pra PRIORIZAR quais turnos merecem leitura manual,
não é veredito automático. Ver `audit_real_losses.py` pras limitações de
fundo (DON estimado, deck embaralhado, etc.) que também se aplicam aqui.

Uso:
    python triage_real_losses.py                  # tabela resumo
    python triage_real_losses.py --show-matches N  # imprime os N primeiros MATCH em detalhe
"""
import argparse
import glob
import json
import os
import re

IN_DIR = os.path.join('metrics', 'real_loss_audits')
OUT_PATH = os.path.join('metrics', 'real_loss_triage.json')

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
RE_PLAY = re.compile(r'Joga: (.+?) \(')
RE_ACTIVATE = re.compile(r'ativou \[Activate:Main\] de (.+?)(?:\n|$)')
RE_ATTACK = re.compile(r'^\s*(.+?) \(\d+pwr\) ataca (Leader|.+?)\s*$', re.MULTILINE)


def _norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())[:12]


def parse_engine_narrative(text: str) -> dict:
    text = ANSI_RE.sub('', text)
    plays = {_norm(m) for m in RE_PLAY.findall(text)}
    activates = {_norm(m) for m in RE_ACTIVATE.findall(text)}
    attacks = RE_ATTACK.findall(text)
    n_leader_atk = sum(1 for _, tgt in attacks if tgt.strip() == 'Leader')
    n_char_atk = sum(1 for _, tgt in attacks if tgt.strip() != 'Leader')
    return {'plays': plays, 'activates': activates,
            'n_leader_atk': n_leader_atk, 'n_char_atk': n_char_atk,
            'n_attacks_total': len(attacks)}


def parse_historical(actions: list) -> dict:
    plays = {_norm(a['card_name']) for a in actions
             if a.get('type') == 'play' and a.get('card_name')}
    activates = {_norm(a['card_name']) for a in actions
                 if a.get('type') == 'activate' and a.get('card_name')}
    atks = [a for a in actions if a.get('type') == 'attack']
    n_leader_atk = sum(1 for a in atks if 'Leader' in (a.get('target') or ''))
    n_char_atk = len(atks) - n_leader_atk
    return {'plays': plays, 'activates': activates,
            'n_leader_atk': n_leader_atk, 'n_char_atk': n_char_atk,
            'n_attacks_total': len(atks)}


def classify(hist: dict, hoje: dict) -> str:
    plays_match = bool(hist['plays']) and hist['plays'] <= hoje['plays']
    plays_empty_ok = not hist['plays'] and not hoje['plays']
    activates_match = bool(hist['activates']) and hist['activates'] <= hoje['activates']
    activates_empty_ok = not hist['activates'] and not hoje['activates']
    atk_leader_match = hist['n_leader_atk'] == hoje['n_leader_atk']
    atk_char_close = abs(hist['n_char_atk'] - hoje['n_char_atk']) <= 1

    cards_ok = (plays_match or plays_empty_ok) and (activates_match or activates_empty_ok)
    attack_ok = atk_leader_match and atk_char_close
    if cards_ok and attack_ok:
        return 'MATCH'
    return 'DIVERGE'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--show-matches', type=int, default=0)
    args = ap.parse_args()

    counts = {'MATCH': 0, 'DIVERGE': 0, 'ERROR': 0, 'SKIPPED': 0}
    matches = []
    diverges = []

    for path in sorted(glob.glob(os.path.join(IN_DIR, '*.json'))):
        report = json.load(open(path, encoding='utf-8'))
        if 'error' in report:
            continue
        for t in report.get('turnos', []):
            if 'error' in t:
                counts['ERROR'] += 1
                continue
            if 'engine_hoje_narrativa' not in t:
                counts['SKIPPED'] += 1
                continue
            hist = parse_historical(t['historical_actions'])
            hoje = parse_engine_narrative(t['engine_hoje_narrativa'])
            label = classify(hist, hoje)
            counts[label] += 1
            row = {
                'file': os.path.basename(path), 'turn': t['turn'],
                'hist_plays': sorted(hist['plays']), 'hoje_plays': sorted(hoje['plays']),
                'hist_activates': sorted(hist['activates']), 'hoje_activates': sorted(hoje['activates']),
                'hist_leader_atk': hist['n_leader_atk'], 'hoje_leader_atk': hoje['n_leader_atk'],
                'hist_char_atk': hist['n_char_atk'], 'hoje_char_atk': hoje['n_char_atk'],
            }
            (matches if label == 'MATCH' else diverges).append(row)

    total = sum(counts.values())
    print(f'{"Categoria":12} {"Qtd":>6} {"%":>7}')
    for k, v in counts.items():
        pct = (v / total * 100) if total else 0
        print(f'{k:12} {v:6d} {pct:6.1f}%')
    print(f'{"TOTAL":12} {total:6d}')

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump({'counts': counts, 'matches': matches, 'diverges': diverges}, f, indent=2, ensure_ascii=False)
    print(f'\nRelatorio completo -> {OUT_PATH}')

    if args.show_matches:
        print(f'\n--- {min(args.show_matches, len(matches))} MATCH (motor de hoje repete a decisao historica) ---')
        for row in matches[:args.show_matches]:
            print(json.dumps(row, ensure_ascii=False))


if __name__ == '__main__':
    main()
