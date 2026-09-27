"""
Registro de GERACOES do ML (bloco 913, INSTRUCAO_MESTRA_ML item 21).

Responde sempre: *qual modelo produziu este jogo? com quais dados foi treinado?
contra qual geracao foi avaliado? por que foi promovido (ou rejeitado)?*

- `metrics/geracoes/index.json` (versionado): a geracao ATUAL, a linhagem de
  geracoes promovidas e todos os candidatos avaliados, com o motivo.
- `metrics/geracoes/generation_NNN.joblib` (versionado): o binario de cada
  geracao PROMOVIDA. `metrics/q_net.joblib` continua sendo o campeao em uso --
  e sempre uma copia da geracao atual.
- O corpus e o log ao vivo gravam o HASH do modelo que decidiu; `id_do_hash`
  traduz pra geracao.

Uso:
    python geracoes.py            # lista a linhagem e os candidatos
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DIR = RAIZ / 'metrics' / 'geracoes'
INDEX = DIR / 'index.json'
Q_CAMPEAO = RAIZ / 'metrics' / 'q_net.joblib'


def hash_arquivo(caminho) -> str | None:
    try:
        return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()[:12]
    except Exception:
        return None


def carrega() -> dict:
    if INDEX.exists():
        return json.loads(INDEX.read_text(encoding='utf-8'))
    return {'atual': None, 'geracoes': [], 'candidatos': []}


def _salva(d: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')


def commit_atual() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=RAIZ,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return 'unknown'


def atual() -> dict | None:
    d = carrega()
    return next((g for g in d['geracoes'] if g['id'] == d.get('atual')), None)


def id_do_hash(h: str | None) -> str | None:
    if not h:
        return None
    for g in carrega()['geracoes']:
        if g['hash'] == h:
            return g['id']
    return None


def registra_candidato(modelo, *, dataset: dict, config: dict, treino: dict,
                       duelo: dict, promovido: bool, motivo: str) -> str:
    """Registra um candidato avaliado contra a geracao atual. Se `promovido`,
    vira a nova geracao: binario copiado pra `generation_NNN.joblib`, marcado
    como atual e copiado pro campeao em uso. Devolve o id (geracao ou
    candidato)."""
    d = carrega()
    pai = d.get('atual')
    h = hash_arquivo(modelo)
    reg = {
        'hash': h, 'pai': pai, 'data': dt.datetime.now().isoformat(timespec='seconds'),
        'commit': commit_atual(), 'dataset': dataset, 'config': config,
        'treino': treino, 'duelo': duelo, 'promovido': bool(promovido), 'motivo': motivo,
    }
    reg['id'] = 'candidato_%03d' % (len(d['candidatos']) + 1)
    d['candidatos'].append(reg)
    ident = reg['id']
    if promovido:
        gid = 'generation_%03d' % (len(d['geracoes']) + 1)
        DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(modelo, DIR / (gid + '.joblib'))
        if Path(modelo).resolve() != Q_CAMPEAO.resolve():
            shutil.copyfile(modelo, Q_CAMPEAO)
        d['geracoes'].append(dict(reg, id=gid, candidato=reg['id'],
                                  arquivo='metrics/geracoes/%s.joblib' % gid))
        d['atual'] = gid
        reg['virou'] = gid
        ident = gid
    _salva(d)
    return ident


def main() -> int:
    d = carrega()
    print('geracao ATUAL:', d.get('atual'))
    for g in d['geracoes']:
        du = g.get('duelo') or {}
        print('  %s  hash=%s  pai=%s  %s  duelo %sx%s %s' % (
            g['id'], g['hash'], g.get('pai'), g['data'][:10],
            du.get('vitorias_desafiante'), du.get('derrotas_desafiante'),
            du.get('veredito') or ''))
    rej = [c for c in d['candidatos'] if not c['promovido']]
    print('candidatos rejeitados:', len(rej))
    for c in rej[-5:]:
        du = c.get('duelo') or {}
        print('  %s  contra %s  %sx%s  %s' % (c['id'], c.get('pai'),
              du.get('vitorias_desafiante'), du.get('derrotas_desafiante'), c.get('motivo')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
