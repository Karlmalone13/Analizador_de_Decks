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
import os
import re
import subprocess
import sys
import time

# ── TRAVA CONTRA RE-EXECUCAO (bloco 810) ───────────────────────────────────
# `treino_continuo.py` re-executa o processo INTEIRO no import quando
# `PYTHONHASHSEED != '0'` (`subprocess.call([sys.executable] + sys.argv)`),
# pra garantir duelo reprodutivel. O `ciclo.py` importa esse modulo TARDE,
# dentro de `portao()` -- entao a re-execucao caia no MEIO do ciclo e
# relancava `ciclo.py` do inicio: o ciclo rodava DUAS vezes, os dois
# processos gerando com a MESMA seed e escrevendo no MESMO corpus.
#
# Medido quando aconteceu de verdade: 9.865 alvos duplicados em
# `q_alvos.jsonl`, 100% repetindo posicao+alvo ja existentes -- eco puro,
# exatamente o que o corpus NAO pode ter.
#
# A trava e fazer a re-execucao acontecer AQUI, no t=0, antes de qualquer
# trabalho. Mesmo idiomatismo que `gerar_selfplay_dataset.py` ja usa.
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    # `sys.argv` NAO carrega as flags do interpretador, entao o `-u` da linha
    # de comando se perde na re-execucao e a saida do ciclo vira buffer --
    # o log fica VAZIO ate o fim, justamente num processo que demora dezenas
    # de minutos e precisa ser acompanhado.
    os.environ['PYTHONUNBUFFERED'] = '1'
    raise SystemExit(subprocess.call([sys.executable, '-u'] + sys.argv))
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
ESTADO = RAIZ / 'metrics' / 'ciclo_estado.json'
Q_CAMPEAO = RAIZ / 'metrics' / 'q_net.joblib'
Q_DESAFIANTE = RAIZ / 'metrics' / 'q_net_desafiante.joblib'
Q_CORPUS = RAIZ / 'metrics' / 'q_alvos.jsonl'
CORPUS = RAIZ / 'metrics' / 'selfplay_v2.jsonl'


class Cronometro:
    """Tempo de PAREDE por etapa do ciclo -- o AS-IS do proprio laco.

    Existe porque o ciclo nao registrava quanto cada etapa custava: sem isso
    nao ha como saber se uma geracao ficou mais cara, e a regra do AS-IS
    (13/09) exige medir o processo ATUAL em vez de herdar diagnostico de
    bloco anterior. O `as_is.py` mede a PARTIDA; isto mede o CICLO, que e a
    unidade de tempo que decide quantas geracoes cabem num dia.
    """

    def __init__(self):
        self.etapas = {}
        self._t0 = None
        self._nome = None

    def inicia(self, nome):
        self._nome, self._t0 = nome, time.time()

    def fecha(self):
        if self._nome is None:
            return
        self.etapas[self._nome] = round(time.time() - self._t0, 1)
        self._nome = None

    def total(self):
        return round(sum(self.etapas.values()), 1)


def _rodar(cmd, titulo) -> bool:
    print('  $ %s' % ' '.join(str(c) for c in cmd[1:]), flush=True)
    r = subprocess.run([sys.executable, '-u'] + cmd, cwd=str(RAIZ))
    if r.returncode != 0:
        print('  [FALHOU] %s (codigo %d)' % (titulo, r.returncode), flush=True)
        return False
    return True


def guarda_corpo(workers) -> dict:
    """SEMELHANCA com humano -- ALARME, nao meta (regra oficial de 10/09).

    Nao existe numero a atingir e ninguem deve otimizar pra ele subir. O que
    ele detecta e o modo de falha classico do auto-jogo: o bot fica forte
    explorando peculiaridades do PROPRIO motor, vence a si mesmo cada vez
    melhor e piora contra gente -- e o duelo NAO acusa isso, por construcao.
    Uma queda GRANDE e ABRUPTA e o sintoma. Queda pequena ou gradual e o
    resultado ESPERADO de um bot que joga melhor que humano.

    So roda quando o portao PROMOVE: e caro (replay do banco inteiro) e so
    tem sentido comparado contra a promocao anterior.

    Le as porcentagens da SAIDA do `decision_quality_full.py` em vez de
    recalcular: a metrica mora la, e refazer a conta aqui seria a duplicata
    que a `REGRA_SEM_DUPLICACAO` proibe.
    """
    print('      guarda-corpo: semelhanca com humano (so por causa da promocao)',
          flush=True)
    try:
        r = subprocess.run([sys.executable, '-u', 'decision_quality_full.py',
                            '--all', '--workers', str(workers)],
                           cwd=str(RAIZ), capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
    except Exception as e:
        print('      (nao rodou: %s)' % e, flush=True)
        return {}
    saida = (r.stdout or '') + (r.stderr or '')
    if r.returncode != 0:
        print('      (falhou, codigo %d)' % r.returncode, flush=True)
        return {}
    achados = {}
    for rot, chave in [('play (mesmas cartas jogadas)', 'play'),
                       ('attack -- QUEM atacou (mesmo conjunto)', 'attack_quem'),
                       ('activate (mesmas cartas ativaram)', 'activate'),
                       ('attach_don -- MESMO alvo recebeu DON', 'attach_don')]:
        m = re.search(re.escape(rot) + r'.*?\(([\d.]+)%\)', saida)
        if m:
            achados[chave] = float(m.group(1))
    for rot, chave in [
            ('blocker (bloquear ou nao)', 'blocker'),
            ('blocker -- MESMA CARTA (quando os 2 bloquearam)', 'blocker_carta'),
            ('counter (usar ou nao, so quando NAO bloqueou)', 'counter'),
            ('counter -- MESMO CONJUNTO de cartas', 'counter_cartas'),
            ('counter -- MESMA ORDEM (quando 2+ cartas)', 'counter_ordem')]:
        m = re.search(re.escape(rot) + r'.*?\(([\d.]+)%\)', saida)
        if m:
            achados[chave] = float(m.group(1))
    # A METRICA OFICIAL (28/08) tem formato proprio: `= NN.N%`, sem parenteses.
    m = re.search(r'ACERTO POR JOGADA:.*?=\s*([\d.]+)%', saida)
    if m:
        achados['acerto_por_jogada'] = float(m.group(1))
    if achados:
        print('      ' + ' | '.join('%s %.1f%%' % (k, v)
                                    for k, v in achados.items()), flush=True)
    return achados


def gera(n, seed, workers) -> bool:
    return _rodar(['gerar_selfplay_dataset.py', '--n', str(n), '--workers', str(workers),
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


def portao(seed, max_pares, workers) -> dict:
    """O Q DESAFIANTE contra o Q CAMPEAO -- geracao contra geracao.

    Era "o Q contra a ARVORE". Deixou de fazer sentido no bloco 811: a busca
    saiu de decidir, entao nao ha com o que duelar do outro lado -- um campeao
    "sem Q" simplesmente pegaria a primeira candidata da ordem.

    E este e o duelo que o projeto sempre registrou como ALVO DE TRABALHO:
    *"cada geracao do ML tem que bater a anterior"*, espelho pareado + SPRT.
    """
    import os
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    import treino_continuo as tc
    return tc.duelar_sprt(
        workers=workers, seed=seed, peso_camp=0.0, peso_desaf=0.0,
        max_pares=max_pares,
        extras={'desafiante': {'q_net_path': str(Q_DESAFIANTE)},
                'campeao': {'q_net_path': str(Q_CAMPEAO)}})


def auditoria(limite) -> bool:
    """Sinal independente: o motor de hoje contra derrotas REAIS pra humano."""
    return _rodar(['audit_real_losses.py', '--all', '--limit', str(limite)],
                  'auditoria de derrotas reais')


def avaliacao_humana(limite) -> dict:
    """As medidas ancoradas em partida humana REAL (bloco 805/807).

    **Isto estava documentado como parte da etapa 4 e NAO era chamado por
    ninguem** -- `avalia_contra_humano.py` dizia no proprio cabecalho "chamado
    pelo `ciclo.py` na etapa 4" e o `ciclo.py` so rodava `audit_real_losses`.
    Achado ao responder "falta alguma coisa na telemetria?" (bloco 808): o
    pedido era *"coloque essas avaliacoes onde a gente nao vai esquecer de
    usa-las"*, e elas estavam onde seriam esquecidas.

    Roda em processo separado (o script escreve `metrics/avaliacao_humana/
    ultimo.json`) e o ciclo LE o json -- assim o numero entra no historico e
    da pra ver a serie entre geracoes, que e o que torna a ancora util: uma
    medida isolada nao diz se o modelo esta derivando.
    """
    _rodar(['avalia_contra_humano.py', '--limite', str(limite)],
           'avaliacao contra partidas humanas')
    f = RAIZ / 'metrics' / 'avaliacao_humana' / 'ultimo.json'
    try:
        return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _logs_do_bot_desde(quando_iso) -> int:
    """Quantas partidas do BOT entraram no banco depois desse instante.

    O checkpoint existe pra que partidas contra o usuario sejam JOGADAS, e a
    unica evidencia disso e log novo no banco com `bot_side` -- o estado do
    ciclo nao tem como saber sozinho. Conta, nao bloqueia: quem decide se o
    checkpoint foi cumprido e ele.
    """
    idx = RAIZ / 'logs' / 'index.json'
    if not idx.exists() or not quando_iso:
        return 0
    try:
        dados = json.loads(idx.read_text(encoding='utf-8'))
        regs = dados if isinstance(dados, list) else dados.get('logs', [])
        n = 0
        for r in regs:
            if not r.get('bot_side'):
                continue
            q = str(r.get('added_at') or r.get('timestamp') or '')
            if q and q > str(quando_iso):
                n += 1
        return n
    except Exception:
        return 0


def limpar_checkpoint(estado) -> int:
    """Baixa o checkpoint humano -- o passo citado no fim de todo ciclo que
    promove, e que ate o bloco 807 nao existia (a saida mandava rodar um flag
    inexistente).

    Ele NAO valida que as partidas foram jogadas: isso e declaracao do
    usuario, nao medicao. O que da pra fazer honestamente e CONTAR os logs de
    bot que entraram no banco desde que o checkpoint subiu, e mostrar -- se o
    numero for zero, dizer, e limpar assim mesmo. Travar aqui seria inventar
    criterio.
    """
    if not estado.get('checkpoint_humano_pendente'):
        print()
        print('  nao ha checkpoint humano pendente -- nada a limpar.')
        return 0

    desde = estado.get('checkpoint_desde')
    n = _logs_do_bot_desde(desde)
    print()
    print('  checkpoint humano: BAIXADO')
    if desde:
        print('    pendente desde        : %s' % desde)
    print('    logs do bot no banco  : %d desde entao' % n)
    if n == 0:
        print('    ATENCAO: nenhum log de partida do bot entrou no banco desde')
        print('    que o checkpoint subiu. Se voce jogou, os logs nao foram')
        print('    adicionados -- rode parse_combat_log.py --add-to-db antes de')
        print('    seguir, senao as partidas nao viram dado nem auditoria.')

    estado['checkpoint_humano_pendente'] = False
    estado['checkpoint_limpo_em'] = datetime.now().isoformat(timespec='seconds')
    estado['checkpoint_logs_no_intervalo'] = n
    estado.pop('checkpoint_desde', None)
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(estado, indent=2, ensure_ascii=False),
                      encoding='utf-8')
    print()
    print('  proximo: python ciclo.py --partidas 40')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=40)
    ap.add_argument('--ciclos', type=int, default=1)
    ap.add_argument('--seed', type=int, default=9000)
    ap.add_argument('--max-pares', dest='max_pares', type=int, default=60)
    ap.add_argument('--ancora', type=int, default=150,
                    help='posicoes humanas reais na ancora da etapa 5')
    ap.add_argument('--workers', type=int, default=4,
                    help='partidas em paralelo (regra do projeto: escolher SEMPRE)')
    ap.add_argument('--auditar', type=int, default=5,
                    help='quantas derrotas reais auditar por ciclo (0 desliga)')
    ap.add_argument('--limpar-checkpoint', dest='limpar_checkpoint',
                    action='store_true',
                    help='baixa o checkpoint humano depois de jogar as partidas '
                         'contra o bot (nao roda ciclo)')
    args = ap.parse_args()

    # PORTAO OBRIGATORIO (18/09/2026): o corpus viaja pelo git em fatias, e
    # rodar um ciclo com fatia pendente treinaria com um corpus MENOR sem erro
    # nenhum -- o modo de falha silencioso do bloco 851.
    from corpus_git import exige_sincronizado
    exige_sincronizado('o ciclo')

    estado = {}
    if ESTADO.exists():
        try:
            estado = json.loads(ESTADO.read_text(encoding='utf-8'))
        except Exception:
            estado = {}
    historico = estado.get('ciclos', [])

    if args.limpar_checkpoint:
        return limpar_checkpoint(estado)

    for k in range(args.ciclos):
        n_ciclo = len(historico) + 1
        seed = args.seed + n_ciclo * 101
        print()
        print('=' * 66)
        print('CICLO %d' % n_ciclo)
        print('=' * 66, flush=True)

        cron = Cronometro()
        print('[1/5] GERA %d partidas (acumulando alvos Q)' % args.partidas,
              flush=True)
        cron.inicia('gera')
        ok = gera(args.partidas, seed, args.workers)
        cron.fecha()
        if not ok:
            break

        print('[2/5] TREINA o Q desafiante', flush=True)
        cron.inicia('treina')
        b = treina()
        cron.fecha()
        if b is None:
            break
        print('      erro fora da amostra %.4f | %.1f%% melhor que a media'
              % (b.get('erro_fora_amostra', 0), b.get('ganho_pct', 0)), flush=True)

        print('[3/5] PORTAO: o Q ja bate a ARVORE?', flush=True)
        cron.inicia('portao')
        d = portao(seed + 13, args.max_pares, args.workers)
        cron.fecha()
        wr = d['winrate_desafiante']
        print('      %dx%d em %d pares decididos (%d divididos) | %s'
              % (d['vitorias_desafiante'], d['derrotas_desafiante'],
                 d['decididas'], d['pares_divididos'], d['veredito']), flush=True)

        promoveu = bool(d.get('promove'))
        gc = {}
        if promoveu:
            import shutil
            shutil.copyfile(Q_DESAFIANTE, Q_CAMPEAO)
            print('      PROMOVIDO -- o Q vira campeao', flush=True)
            cron.inicia('guarda_corpo')
            gc = guarda_corpo(args.workers)
            cron.fecha()

        if args.auditar:
            print('[4/5] AUDITORIA contra derrotas REAIS pra humano', flush=True)
            cron.inicia('auditoria')
            auditoria(args.auditar)
            cron.fecha()

        print('[5/5] ANCORA HUMANA: modelo de oponente + custo da incerteza',
              flush=True)
        cron.inicia('ancora')
        ah = avaliacao_humana(args.ancora)
        cron.fecha()

        print()
        print('      TEMPO DO CICLO (AS-IS do proprio laco): %.1f min'
              % (cron.total() / 60.0))
        print('      ' + ' | '.join('%s %.0fs' % (k, v)
                                    for k, v in cron.etapas.items()), flush=True)

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
            # Recorte POR LIDER do portao: regra obrigatoria do projeto --
            # um ganho agregado que so aparece em 2 lideres NAO generalizou.
            'portao_por_lider': d.get('por_lider') or {},
            # AS-IS do laco: segundos por etapa, pra saber se uma geracao
            # ficou mais cara em vez de descobrir isso por sensacao.
            'tempo_s': cron.etapas,
            'tempo_total_s': cron.total(),
            # ALARME, sem numero a atingir. So existe quando houve promocao.
            'guarda_corpo': gc,
            'ancora_humana': {
                'modelo_oponente': (ah.get('modelo_oponente') or {}).get('acerto_pct'),
                'modelo_oponente_sem_observar':
                    (ah.get('modelo_oponente') or {}).get('acerto_pct_sem_observar'),
                'custo_incerteza':
                    (ah.get('custo_incerteza') or {}).get('diferenca_mediana'),
            },
        })
        estado['ciclos'] = historico
        ja_pendente = estado.get('checkpoint_humano_pendente')
        estado['checkpoint_humano_pendente'] = bool(ja_pendente or promoveu)
        if promoveu and not ja_pendente:
            estado['checkpoint_desde'] = datetime.now().isoformat(timespec='seconds')
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

    if any(h.get('tempo_total_s') for h in historico):
        print()
        print('  TEMPO POR CICLO (AS-IS do laco)')
        print('   ciclo | total | ' + ' | '.join(
            ['gera', 'treina', 'portao', 'ancora']))
        for h in historico[-10:]:
            t = h.get('tempo_s') or {}
            print('   %5d | %4.1fm | %4.0fs | %5.0fs | %5.0fs | %5.0fs'
                  % (h['ciclo'], (h.get('tempo_total_s') or 0) / 60.0,
                     t.get('gera', 0), t.get('treina', 0),
                     t.get('portao', 0), t.get('ancora', 0)))

    ult = historico[-1] if historico else {}
    pl = ult.get('portao_por_lider') or {}
    if pl:
        print()
        print('  PORTAO POR LIDER (ultimo ciclo) -- agregado sozinho nao prova')
        print('  que um ganho generalizou:')
        ordenados = sorted(pl.items(),
                           key=lambda kv: -(kv[1]['vit'] + kv[1]['der']))
        for cod, c in ordenados[:12]:
            dec = c['vit'] + c['der']
            tx = ('%.0f%%' % (100.0 * c['vit'] / dec)) if dec else '--'
            print('    %-12s %2dx%-2d  %4s  (%d divididos)'
                  % (cod, c['vit'], c['der'], tx, c['div']))
        if len(ordenados) > 12:
            print('    ... e mais %d lideres' % (len(ordenados) - 12))

    serie = [h for h in historico if (h.get('ancora_humana') or {}).get('modelo_oponente')]
    if serie:
        print()
        print('  ANCORA HUMANA (a unica que nao compartilha o vicio do auto-jogo)')
        print('   ciclo | oponente | sem observar | custo da incerteza')
        for h in serie[-10:]:
            a2 = h['ancora_humana']
            print('   %5d | %7.1f%% | %11.1f%% | %.4f'
                  % (h['ciclo'], a2['modelo_oponente'],
                     a2.get('modelo_oponente_sem_observar') or 0.0,
                     a2.get('custo_incerteza') or 0.0))

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
