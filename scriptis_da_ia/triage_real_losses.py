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
    return re.sub(r'[^a-z0-9]', '', name.lower())


_INDICE_NOMES = None


def _indice_nomes() -> list:
    """[(nome normalizado, codigo BASE)] do banco de cartas -- variantes de
    arte (`OP17-054_p1`) contam como o codigo base."""
    global _INDICE_NOMES
    if _INDICE_NOMES is None:
        import pandas as pd
        df = pd.read_csv('cards_rows.csv', usecols=['id', 'card_name'])
        _INDICE_NOMES = sorted({(_norm(str(n)), str(i).split('_')[0])
                                for i, n in zip(df['id'], df['card_name'])
                                if isinstance(n, str) and _norm(n)})
    return _INDICE_NOMES


def _codigos_do_nome(nome: str) -> frozenset:
    """Codigos compativeis com o nome que o MOTOR imprime (nome do banco,
    as vezes da arte alternativa, as vezes TRUNCADO: "Miss Buckingham Stussy
    (Altern"). Bloco 977: a triagem comparava NOMES cortados em 12 letras, e
    o log do simulador chama a mesma carta de outro nome ("Stussy" x "Miss
    Buckingham Stussy", OP17-054) -> DIVERGE falso. Agora a comparacao e por
    CODIGO; o nome so serve pra achar os codigos possiveis do lado do motor."""
    n = _norm(nome)
    if not n:
        return frozenset()
    return frozenset(c for nm, c in _indice_nomes()
                     if nm == n or nm.startswith(n) or n.startswith(nm))


def _codigo_historico(a: dict) -> str:
    """Codigo da acao historica (o log ja traz `card`); sem ele, o nome."""
    c = a.get('card')
    if c:
        return str(c).split('_')[0]
    return 'nome:' + _norm(a.get('card_name') or '')


def parse_engine_narrative(text: str) -> dict:
    text = ANSI_RE.sub('', text)
    plays = [_codigos_do_nome(m) for m in RE_PLAY.findall(text)]
    activates = [_codigos_do_nome(m) for m in RE_ACTIVATE.findall(text)]
    attacks = RE_ATTACK.findall(text)
    n_leader_atk = sum(1 for _, tgt in attacks if tgt.strip() == 'Leader')
    n_char_atk = sum(1 for _, tgt in attacks if tgt.strip() != 'Leader')
    return {'plays': plays, 'activates': activates,
            'n_leader_atk': n_leader_atk, 'n_char_atk': n_char_atk,
            'n_attacks_total': len(attacks)}


RE_TARGET_CODE = re.compile(r'">(.+?)\]')


def _is_leader_target(target: str, leader_codes: set) -> bool:
    """Achado real 04/08 (bug na propria triagem, achado auditando o
    residuo): o log historico NUNCA registra o alvo como a string
    literal "Leader" -- usa o NOME+CODIGO real da carta (ex:
    'Marshall D. Teach [\"OP16-080\">OP16-080]'), mesmo quando o alvo E
    o lider do oponente. O check antigo (`'Leader' in target`) dava
    SEMPRE False pra ataques reais ao lider, inflando artificialmente
    hist_leader_atk pra 0 -- fazia hoje_leader_atk>hist_leader_atk
    parecer um sinal forte quando na real boa parte era esse bug.
    Corrigido: extrai o CODIGO do alvo e confere se e um LEADER de
    verdade (`cards_db`/card_type), nao um match de string ingenuo."""
    if not target:
        return False
    if 'Leader' in target:  # mantem compat com qualquer formato que use a palavra
        return True
    m = RE_TARGET_CODE.search(target)
    if not m:
        return False
    return m.group(1) in leader_codes


def parse_historical(actions: list, leader_codes: set) -> dict:
    plays = {_codigo_historico(a) for a in actions
             if a.get('type') == 'play' and (a.get('card') or a.get('card_name'))}
    activates = {_codigo_historico(a) for a in actions
                 if a.get('type') == 'activate' and (a.get('card') or a.get('card_name'))}
    atks = [a for a in actions if a.get('type') == 'attack']
    n_leader_atk = sum(1 for a in atks if _is_leader_target(a.get('target'), leader_codes))
    n_char_atk = len(atks) - n_leader_atk
    return {'plays': plays, 'activates': activates,
            'n_leader_atk': n_leader_atk, 'n_char_atk': n_char_atk,
            'n_attacks_total': len(atks)}


def _contido(hist_codigos: set, hoje_opcoes: list) -> bool:
    """Toda carta historica aparece entre as jogadas de hoje (cada jogada de
    hoje e o CONJUNTO de codigos compativeis com o nome impresso)."""
    return all(any(h in op for op in hoje_opcoes) for h in hist_codigos)


def classify(hist: dict, hoje: dict) -> str:
    plays_match = bool(hist['plays']) and _contido(hist['plays'], hoje['plays'])
    plays_empty_ok = not hist['plays'] and not hoje['plays']
    activates_match = bool(hist['activates']) and _contido(hist['activates'], hoje['activates'])
    activates_empty_ok = not hist['activates'] and not hoje['activates']
    atk_leader_match = hist['n_leader_atk'] == hoje['n_leader_atk']
    atk_char_close = abs(hist['n_char_atk'] - hoje['n_char_atk']) <= 1

    cards_ok = (plays_match or plays_empty_ok) and (activates_match or activates_empty_ok)
    attack_ok = atk_leader_match and atk_char_close
    if cards_ok and attack_ok:
        return 'MATCH'
    return 'DIVERGE'


def _all_leader_codes() -> set:
    import pandas as pd
    df = pd.read_csv('cards_rows.csv')
    # card_type tem grafia inconsistente no CSV ("Leader" pra 285 linhas,
    # "LEADER" so pra 3) -- comparacao tinha que ser case-insensitive,
    # senao a maioria dos lideres reais nao entra no set.
    return set(df.loc[df['card_type'].str.upper() == 'LEADER', 'id'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--show-matches', type=int, default=0)
    args = ap.parse_args()

    leader_codes = _all_leader_codes()
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
            hist = parse_historical(t['historical_actions'], leader_codes)
            hoje = parse_engine_narrative(t['engine_hoje_narrativa'])
            label = classify(hist, hoje)
            counts[label] += 1
            row = {
                'file': os.path.basename(path), 'turn': t['turn'],
                'hist_plays': sorted(hist['plays']),
                'hoje_plays': [sorted(op) for op in hoje['plays']],
                'hist_activates': sorted(hist['activates']),
                'hoje_activates': [sorted(op) for op in hoje['activates']],
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
