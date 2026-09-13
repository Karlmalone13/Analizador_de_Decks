# -*- coding: utf-8 -*-
"""O CICLO DE UMA GERACAO, com ancora humana (bloco 804).

Desenhado com o usuario em 13/09/2026. A proposta original dele era jogar 3
partidas contra o humano a CADA geracao; o formato abaixo mantem a ancora e
muda a frequencia e o papel, pelas razoes medidas:

  * **3 partidas nao medem forca.** 3x0 acontece por acaso em ~12% das vezes
    mesmo com o bot em 50%. Servem como ALARME de deriva grosseira, nao como
    numero.
  * **Como dado, elas se afogam**: ~700 alvos contra ~540.000 do corpus =
    0,13%. Para pesarem, exigiriam um peso escrito a mao -- justamente o tipo
    de constante que o projeto passou o dia removendo.
  * **O gargalo viraria o usuario.** Uma geracao custa ~20 min de maquina; se
    cada uma exigir partidas dele, o laco anda na agenda dele.

Por isso: **partida humana e CHECKPOINT DE AVALIACAO, e so quando o portao
promove alguma coisa.** Se nada foi promovido, nao ha o que testar.

## As etapas

  1. GERA      -- partidas em auto-jogo, acumulando alvos Q (o professor
                  decide; ver `--q-out` em `gerar_selfplay_dataset.py`)
  2. TREINA    -- o Q desafiante, validado POR LIDER
  3. PORTAO    -- o Q desafiante contra a ARVORE: "o aluno ja bate o
                  professor?". Enquanto perder, o Q segue candidato e a
                  arvore segue decidindo em producao (medido no bloco 801:
                  0x13)
  4. AUDITORIA -- roda sobre o banco de partidas humanas REAIS. Nao custa
                  tempo do usuario e e o unico sinal que nao compartilha o
                  vicio do auto-jogo
  5. CHECKPOINT-- se o portao promoveu, PEDE as partidas contra o humano.
                  So ai.

## Por que a auditoria entra em TODO ciclo e o humano nao

O laco inteiro e auto-referente: o alvo vem do modelo, o dado vem do modelo
jogando contra si mesmo, e o portao compara o modelo com uma versao dele. Nada
disso esta ancorado em vencer um humano -- e um vicio COMPARTILHADO e invisivel
ao auto-jogo por construcao (achado do usuario, bloco 780).

As 41 partidas auditaveis do banco sao a ancora barata; as partidas contra o
usuario sao a ancora cara. O ciclo usa a barata sempre e a cara so quando ha
algo novo pra julgar.

Uso:
    python ciclo.py --partidas 40           # um ciclo
    python ciclo.py --partidas 40 --ciclos 5
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
ESTADO = RAIZ / 'metrics' / 'ciclo_estado.json'
Q_CAMPEAO = RAIZ / 'metrics' / 'q_net.joblib'
Q_DESAFIANTE = RAIZ / 'metrics' / 'q_net_desafiante.joblib'
Q_CORPUS = RAIZ / 'metrics' / 'q_alvos.jsonl'
CORPUS = RAIZ / 'metrics' / 'selfplay_v2.jsonl'


def _rodar(cmd, titulo) -> bool:
    print('  $ %s' % ' '.join(str(c) for c in cmd[1:]), flush=True)
    r = subprocess.run([sys.executable, '-u'] + cmd, cwd=str(RAIZ))
    if r.returncode != 0:
        print('  [FALHOU] %s (codigo %d)' % (titulo, r.returncode), flush=True)
        return False
    return True


def gera(n, seed) -> bool:
    return _rodar(['gerar_selfplay_dataset.py', '--n', str(n), '--workers', '1',
                   '--decks', '24', '--seed', str(seed), '--append',
                   '--out', str(CORPUS), '--q-out', str(Q_CORPUS)],
                  'geracao de partidas')


def treina() -> dict | None:
    if not _rodar(['treinar_q.py', '--dataset', str(Q_CORPUS),
                   '--out', str(Q_DESAFIANTE)], 'treino do Q'):
        return None
    try:
        import joblib
        return joblib.load(Q_DESAFIANTE)
    except Exception:
        return None


def portao(seed, max_pares) -> dict:
    """O Q desafiante contra a ARVORE. Enquanto o aluno perder, ele nao entra."""
    import os
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    import treino_continuo as tc
    return tc.duelar_sprt(
        workers=1, seed=seed, peso_camp=0.0, peso_desaf=0.0,
        max_pares=max_pares,
        extras={'desafiante': {'usa_q': True, 'q_net_path': str(Q_DESAFIANTE)},
                'campeao': {'usa_q': False}})


def auditoria(limite) -> bool:
    """Sinal independente: o motor de hoje contra derrotas REAIS pra humano."""
    return _rodar(['audit_real_losses.py', '--all', '--limit', str(limite)],
                  'auditoria de derrotas reais')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=40)
    ap.add_argument('--ciclos', type=int, default=1)
    ap.add_argument('--seed', type=int, default=9000)
    ap.add_argument('--max-pares', dest='max_pares', type=int, default=60)
    ap.add_argument('--auditar', type=int, default=5,
                    help='quantas derrotas reais auditar por ciclo (0 desliga)')
    args = ap.parse_args()

    estado = {}
    if ESTADO.exists():
        try:
            estado = json.loads(ESTADO.read_text(encoding='utf-8'))
        except Exception:
            estado = {}
    historico = estado.get('ciclos', [])

    for k in range(args.ciclos):
        n_ciclo = len(historico) + 1
        seed = args.seed + n_ciclo * 101
        print()
        print('=' * 66)
        print('CICLO %d' % n_ciclo)
        print('=' * 66, flush=True)

        print('[1/4] GERA %d partidas (acumulando alvos Q)' % args.partidas,
              flush=True)
        if not gera(args.partidas, seed):
            break

        print('[2/4] TREINA o Q desafiante', flush=True)
        b = treina()
        if b is None:
            break
        print('      erro fora da amostra %.4f | %.1f%% melhor que a media'
              % (b.get('erro_fora_amostra', 0), b.get('ganho_pct', 0)), flush=True)

        print('[3/4] PORTAO: o Q ja bate a ARVORE?', flush=True)
        d = portao(seed + 13, args.max_pares)
        wr = d['winrate_desafiante']
        print('      %dx%d em %d pares decididos (%d divididos) | %s'
              % (d['vitorias_desafiante'], d['derrotas_desafiante'],
                 d['decididas'], d['pares_divididos'], d['veredito']), flush=True)

        promoveu = bool(d.get('promove'))
        if promoveu:
            import shutil
            shutil.copyfile(Q_DESAFIANTE, Q_CAMPEAO)
            print('      PROMOVIDO -- o Q vira campeao', flush=True)

        if args.auditar:
            print('[4/4] AUDITORIA contra derrotas REAIS pra humano', flush=True)
            auditoria(args.auditar)

        historico.append({
            'ciclo': n_ciclo,
            'quando': datetime.now().isoformat(timespec='seconds'),
            'partidas': args.partidas,
            'alvos_corpus': sum(1 for _ in Q_CORPUS.open(encoding='utf-8'))
                            if Q_CORPUS.exists() else 0,
            'erro_q': b.get('erro_fora_amostra'),
            'ganho_pct': b.get('ganho_pct'),
            'portao': {k2: d.get(k2) for k2 in
                       ('vitorias_desafiante', 'derrotas_desafiante',
                        'decididas', 'pares_divididos', 'veredito', 'llr')},
            'promovido': promoveu,
            'winrate': wr,
        })
        estado['ciclos'] = historico
        estado['checkpoint_humano_pendente'] = (
            estado.get('checkpoint_humano_pendente') or promoveu)
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(estado, indent=2, ensure_ascii=False),
                          encoding='utf-8')

    print()
    print('=' * 66)
    print('HISTORICO')
    print('=' * 66)
    print(' ciclo |   alvos | erro Q |        portao        | promovido')
    for h in historico[-10:]:
        p = h.get('portao') or {}
        print(' %5d | %7s | %6s | %3sx%-3s %-12s | %s'
              % (h['ciclo'], h.get('alvos_corpus'),
                 ('%.4f' % h['erro_q']) if h.get('erro_q') else '-',
                 p.get('vitorias_desafiante'), p.get('derrotas_desafiante'),
                 (p.get('veredito') or '')[:12], 'SIM' if h.get('promovido') else 'nao'))

    if estado.get('checkpoint_humano_pendente'):
        print()
        print('=' * 66)
        print('  >>> CHECKPOINT HUMANO PENDENTE <<<')
        print('=' * 66)
        print('  O portao promoveu um Q novo. Antes de seguir gerando, jogue')
        print('  3 partidas contra o bot no OPTCGSim e adicione os logs:')
        print()
        print('    python parse_combat_log.py <log> --add-to-db --bepinex-log <LogOutput.log>')
        print()
        print('  Isso NAO e medicao de forca (3 partidas nao medem), e ALARME:')
        print('  o laco inteiro e auto-referente e um vicio compartilhado e')
        print('  invisivel ao auto-jogo. Voce e a unica fonte que nao compartilha.')
        print()
        print('  Depois: python ciclo.py --limpar-checkpoint')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
