# -*- coding: utf-8 -*-
"""Treina o modelo Q: (estado + acao) -> valor, SEM simular.

Passo 2 de 3 da substituicao da ARVORE (bloco 796, pedido do usuario).

## O que este modelo faz, e por que ele existe

Hoje, pra saber aonde cada acao leva, o motor SIMULA: clona o estado, aplica a
acao, gera as acoes legais do no e avalia. Sao ~64 estados materializados por
decisao, e e de onde vem **77% do tempo de partida** (AS-IS, bloco 795) -- o
modelo em si e so 23%.

O Q aprende a devolver o MESMO valor que a busca calculou, a partir de
(estado, acao), sem clonar e sem aplicar nada. Uma consulta por candidata (~8)
no lugar de ~64 estados materializados.

E o **DQN** da lista de metodos que o usuario trouxe: *"o agente joga contra si
mesmo e aprende o valor Q -- retorno futuro acumulado de CADA ACAO numa
posicao"*.

## Professor e aluno, um nivel acima

A **busca e o professor**: ela ja produz um valor por candidata, simulando.
Esse valor e o alvo. O **Q e o aluno**: aprende a responder sem simular. Mesma
estrutura que o projeto ja usou pro rotulo (bloco 783), aplicada agora a
ACAO em vez do estado.

A arvore nao desaparece -- ela continua rodando OFFLINE pra gerar alvos. O que
ela deixa de fazer e decidir.

## Validacao POR LIDER, como o resto do projeto

`GroupKFold` por lider: o objetivo registrado e jogar bem com QUALQUER deck,
entao o teste tem que ser em lider que o modelo nao viu treinando. Sem isso, um
modelo que decorou lider passa e quebra no deck novo. NAO reduzir isso por
velocidade -- discutido explicitamente com o usuario 19/09/2026: jogar bem nao
e "ganhar a partida", e extrair o melhor do deck que se tem, e um modelo que so
aprendeu "este lider costuma vencer" erraria isso silenciosamente. O corte por
velocidade tem que vir de OUTRO lugar (ver abaixo), nunca de tirar o holdout.

## AS-IS que motivou a mudanca de 19/09/2026 (bloco 878)

Medido isolado: ler+parsear o corpus inteiro (721k linhas) custa 22s: **1,5%**
do tempo de "treina" no ciclo (1451s). O resto e o `MLPRegressor.fit()` --
210,6s pra UM fit em ~577k linhas. E o codigo fazia **6 fits completos**: 5
(GroupKFold) + 1 final no corpus inteiro (`modelo = novo().fit(X, y)`, o que
realmente vai pro `.joblib`). Os folds de validacao NUNCA viram modelo de
producao -- so medem generalizacao -- entao nao precisam ver o corpus
INTEIRO pra isso. Duas mudancas, nenhuma delas mexendo no holdout por lider:

1. `--folds` cai de 5 pra 2 (o MINIMO que ainda garante "testado em lider
   nao visto") -- 5 fits de validacao viram 2.
2. `--amostra-validacao` (default 200.000): os folds rodam numa AMOSTRA do
   corpus, nao no corpus inteiro. O modelo FINAL (o que e salvo) continua
   treinando no corpus INTEIRO, sem amostragem -- a amostra e so pra medir
   generalizacao mais barato.

Ganho estimado (nao ainda remedido com AS-IS formal): ~1451s -> ~350-400s.

## Relatorio POR LIDER individual (achado no mesmo pedido)

Ate aqui o relatorio so mostrava erro/concordancia POR FOLD (uma MISTURA de
varios lideres, ja que cada fold segura ~n_lideres/folds lideres de uma vez)
e POR FAMILIA de acao -- nunca por lider individual, embora a lista de
lideres ja estivesse salva no bundle sem uso nenhum. E exatamente o tipo de
agregado que o projeto ja proibe em outras ferramentas (regra "nenhum
resultado agregado vale sem o recorte POR LIDER", `decision_quality_full.py`
ja obrigado a mostrar isso). Um lider especifico podia estar generalizando
mal e sumir na media do fold. Corrigido: cada lider so aparece no fold em
que foi held-out, entao da pra tabular por lider sem custo extra de treino.

## Filtro por CRITERIO DE ROTULO (`--modo`, 20/09/2026) -- HIPOTESE TESTADA E DERRUBADA

O corpus mistura dois criterios de rotulo: 'bootstrap' (o proprio modelo
avaliando o estado que a candidata produz -- linhas antigas nao tem o campo
`modo`, mas o bloco 877 ja mediu que 100% delas sao bootstrap) e 'busca'
(professor independente, simula de verdade). A hipotese inicial era que
misturar os dois contamina o alvo -- erro fora da amostra SUBIU 6 ciclos
seguidos (0,0498 -> 0,0581) enquanto a fracao 'busca' crescia.

**MEDIDO E DERRUBADO no mesmo dia**: um Q treinado SO com 'busca' (95k linhas,
alguns lideres com so 35-104 decisoes de validacao) perdeu **0x9** (11
empates) contra o Q treinado com o corpus INTEIRO misturado, em duelo real
(espelho pareado, `treino_continuo.duelar_sprt`) -- nao so pior em metrica
estatica, pior JOGANDO. O corpus 'busca' ainda nao tem volume suficiente pra
treinar sozinho; misturar com 'bootstrap' hoje ajuda mais do que atrapalha,
mesmo que o criterio nao seja o mesmo. **Default volta a ser 'todos'** -- o
flag fica pra quando o volume de 'busca' crescer o bastante pra re-testar
(o campo `modo` grava certo desde o bloco 877, entao a comparacao pode ser
refeita a qualquer momento sem precisar gerar dado novo).

**REVISTO 27/09/2026 (bloco 906): default passa a ser 'bootstrap'.** O teste
de 20/09 comparou 'busca' SOZINHO contra 'todos'; faltava a celula que
decide -- 'todos' contra 'todos MENOS busca'. Mesma receita, duelo contra o
campeao: prefixo + linhas 'busca' deu 24x39 (DESCARTA); prefixo + linhas
'bootstrap' deu 75x46 (PROMOVE). As linhas 'busca' PIORAM o modelo. Causa
provavel, ja apontada no bloco 888 e nunca testada: a busca que gera esse
rotulo roda com a mao REAL do oponente visivel (`self_play_info_hidden` nao e
ligado na geracao), entao o alvo e otimista (media 0,581 x 0,503) e
inalcancavel pra quem so ve o observavel. Nada e apagado do corpus: 'todos'
continua disponivel, e linhas 'busca' geradas com o professor cego podem
voltar a entrar quando existirem.

Uso:
    python treinar_q.py --dataset metrics/q_alvos.jsonl --out metrics/q_net.joblib
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).parent
import sys  # noqa: E402
sys.path.insert(0, str(RAIZ))
import corpus_escolhidas  # noqa: E402
MODO_PADRAO = 'bootstrap'


def passa_filtro_modo(linha: dict, modo: str = MODO_PADRAO) -> bool:
    """Linha sem o campo `modo` e bootstrap (bloco 877).

    BUG CORRIGIDO (bloco 944): desde os blocos 939/942 a coleta grava linhas
    do MESMO modo bootstrap so que sem simular ('sem_simulacao'), auditadas
    ('auditoria') ou puladas ('conhecida'). Este filtro as tratava como outro
    modo e DESCARTAVA do treino -- ~30 mil jogadas escolhidas por ciclo (37k ->
    126k descartadas nos ciclos 57-60). O rotulo delas e a consequencia real,
    igual as outras; so faltava a nota da simulacao, que nao ensina mais."""
    m = linha.get('modo') or 'bootstrap'
    if m in ('sem_simulacao', 'auditoria', 'conhecida'):
        m = 'bootstrap'
    return modo == 'todos' or m == modo


# TODAS as decisoes do jogo que o ML tem que aprender (bloco 910). A cobertura
# por familia sai em todo treino: familia com ZERO jogada rotulada pela
# consequencia e familia que o ML NAO aprende -- o numero nao da pra fingir.
FAMILIAS_JOGO = ('attack', 'play', 'pass', 'activate', 'attach_don',
                 'block', 'counter', 'target', 'descarte', 'counter_evento',
                 'custo_restar', 'custo_sacrificar', 'busca', 'pagar_custo', 'opcao_efeito')
SELFPLAY = RAIZ / 'metrics' / 'selfplay_v2.jsonl'


def modelo_do_campeao(caminho, n_cols: int):
    """O campeao pronto pra CONTINUAR o treino (bloco 913, INSTRUCAO_MESTRA
    item 14.7: "o proximo treinamento obrigatoriamente parte do modelo
    promovido"). Copia o Pipeline(StandardScaler, MLP) dele; se ele foi
    treinado sem as 4 colunas de defesa/alvo (bloco 910), a 1a camada ganha
    essas entradas com PESO ZERO e o scaler com media 0/escala 1 -- o modelo
    comeca respondendo EXATAMENTE como o campeao. None se nao der pra continuar
    (sem arquivo, outra familia de modelo, dimensao incompativel)."""
    import copy
    import joblib
    import numpy as np
    try:
        b = joblib.load(caminho)
        m = copy.deepcopy(b.get('modelo') if isinstance(b, dict) else None)
        sc, mlp = m.steps[0][1], m.steps[-1][1]
        n_in = mlp.coefs_[0].shape[0]
        k = n_cols - n_in          # colunas novas (sempre no FIM do vetor)
        if 0 < k <= 40:
            mlp.coefs_[0] = np.vstack([mlp.coefs_[0], np.zeros((k, mlp.coefs_[0].shape[1]))])
            mlp.n_features_in_ = n_cols
            sc.mean_ = np.concatenate([sc.mean_, np.zeros(k)])
            sc.scale_ = np.concatenate([sc.scale_, np.ones(k)])
            sc.var_ = np.concatenate([sc.var_, np.ones(k)])
            sc.n_features_in_ = n_cols
        elif k != 0:
            return None
        return m
    except Exception:
        return None


def carrega_trajetorias(caminho=SELFPLAY, avaliador=None) -> dict:
    """(gen, partida, lider) -> [(turno, life_diff no fim do turno, venceu,
    valor da posicao no fim do turno)]. `avaliador` (bundle de valor de
    posicao) preenche o 4o campo; sem ele fica None."""
    regs = []
    if not Path(caminho).exists():
        return {}
    with open(caminho, encoding='utf-8') as fh:
        for linha in fh:
            d = json.loads(linha)
            if not d.get('gen'):
                continue   # gen 0 junta rodadas antigas com ids repetidos
            regs.append(d)
    return monta_trajetorias(regs, avaliador)


def monta_trajetorias(regs: list, avaliador=None) -> dict:
    """Mesma estrutura de `carrega_trajetorias`, a partir de registros ja em
    memoria (estados de fim de turno com `gen`, `match`, `leader`, `turn`,
    `feats` V3 e `win`). FONTE UNICA: o treino le do arquivo; o gerador de
    partidas usa isto direto pra gravar a vantagem de cada jogada (bloco 932)."""
    import numpy as np
    from optcg_engine import value_net as vn
    i_ld = list(vn.FEATURE_NAMES_V3).index('life_diff')
    traj = {}
    vals = [None] * len(regs)
    if avaliador is not None and regs:
        try:
            nomes = avaliador['feature_names']
            idx = [list(vn.FEATURE_NAMES_V3).index(nm) for nm in nomes]
            X = np.asarray([[d['feats'][i] for i in idx] for d in regs], dtype=float)
            m = avaliador['modelo']
            vals = list(m.predict_proba(X)[:, 1] if hasattr(m, 'predict_proba') else m.predict(X))
        except Exception:
            vals = [None] * len(regs)
    for d, v in zip(regs, vals):
        traj.setdefault((d['gen'], d['match'], d['leader']), []).append(
            (d['turn'], d['feats'][i_ld], d['win'], None if v is None else float(v)))
    for t in traj.values():
        t.sort(key=lambda r: r[0])
    return traj


def grava_vantagem(linhas: list, amostras: list, regua, hash_regua=None) -> int:
    """Grava em cada jogada ESCOLHIDA a sua VANTAGEM (bloco 932, pedido do
    usuario: a qualidade de cada jogada fica no corpus, nao so calculada na
    hora da analise):

        consequencia = `alvo_consequencia` (o que a jogada causou)
        v_antes      = regua(estado antes da jogada)
        vantagem     = consequencia - v_antes   (>0: deixou o bot melhor)
        regua        = hash da regua que julgou (a regua muda a cada ciclo)

    Sao o julgamento DA EPOCA. O treino continua recalculando com a regua do
    ciclo (nao usa estes valores -- seriam notas velhas); `qualidade_jogadas.py`
    recalcula com UMA regua pra comparar geracoes. Uso aqui: serie historica e
    auditoria. Devolve quantas linhas receberam."""
    import numpy as np
    from optcg_engine import value_net as vn
    if not regua or not amostras:
        return 0
    traj = monta_trajetorias(amostras, regua)
    i_ld = list(vn.FEATURE_NAMES_ALUNO).index('life_diff')
    n_est = len(vn.FEATURE_NAMES_ALUNO)
    alvo, cons = [], []
    for d in linhas:
        if not d.get('escolhida') or not d.get('feats'):
            continue
        d2 = dict(d)
        d2['ld_agora'] = d['feats'][i_ld]
        c = alvo_consequencia(d2, traj)
        if c is None:
            continue
        alvo.append(d)
        cons.append(float(c))
    if not alvo:
        return 0
    m = regua['modelo']
    X = np.asarray([d['feats'][:n_est] for d in alvo], dtype=float)
    v = m.predict_proba(X)[:, 1] if hasattr(m, 'predict_proba') else m.predict(X)
    for d, c, vv in zip(alvo, cons, v):
        vv = float(vv)
        d['consequencia'] = round(c, 4)
        d['v_antes'] = round(vv, 4)
        d['vantagem'] = round(c - vv, 4)
        if hash_regua:
            d['regua'] = hash_regua
    return len(alvo)


def alvo_consequencia(d: dict, traj: dict, n: int = 2, lam: float = 0.5,
                      modo: str = 'td'):
    """Rotulo pela CONSEQUENCIA da jogada escolhida (bloco 910): o que aconteceu
    DEPOIS dela na propria partida -- mesma formula da Fase 1
    (`rotulo_professor.py`): (1-lam)*logistica(vantagem de vida em n turnos
    proprios) + lam*resultado. Sem continuacao registrada -> None (fica o
    rotulo bootstrap). So a ESCOLHIDA tem continuacao; e a exploracao que faz
    alternativas ruins virarem escolhidas e receberem a consequencia delas."""
    import math
    if not d.get('escolhida') or d.get('decisao') is None:
        return None
    t = traj.get((d.get('gen'), d.get('match'), d.get('leader')))
    k = int(d.get('turn') or 0)
    ld_agora = d.get('ld_agora')
    # `turn` e a contagem de turnos PROPRIOS. Decisao no proprio turno (vez)
    # fecha no fim DESTE turno (indice k-1); defesa no turno do oponente
    # (counter/bloqueio) fecha no fim do PROXIMO turno proprio (indice k).
    base = k - 1 if d.get('vez', True) else k
    if not t or base < 0 or base >= len(t) or ld_agora is None:
        return None
    if modo == 'td':
        # RETORNO DE n PASSOS (bloco 913, INSTRUCAO_MESTRA item 9): o valor
        # da POSICAO n turnos proprios depois -- ja inclui a resposta do
        # oponente no meio -- e NAO o resultado distante da partida. Se a
        # partida acabou dentro do horizonte, o fim E a consequencia direta.
        j = base + n - 1
        if j >= len(t):
            return float(t[-1][2])
        return t[j][3]
    j = min(base + n - 1, len(t) - 1)
    vant = t[j][1] - ld_agora
    return (1 - lam) / (1 + math.exp(-vant)) + lam * float(t[j][2])


CAMADAS = (64, 32)


def alarga_rede(pipe, camadas, X_amostra):
    """Copia o MLP do campeao numa rede de camadas maiores sem mudar o que ela
    calcula (pesos novos de saida = 0). Devolve um pipeline novo pronto pra
    `warm_start`."""
    import copy
    import numpy as np
    from sklearn.neural_network import MLPRegressor
    sc, velho = pipe.steps[0][1], pipe.steps[-1][1]
    if any(n < v for n, v in zip(camadas, velho.hidden_layer_sizes))             or len(camadas) != len(velho.hidden_layer_sizes):
        raise ValueError('so alarga (mesmo numero de camadas, cada uma >=)')
    novo = MLPRegressor(hidden_layer_sizes=camadas, activation=velho.activation,
                        solver='adam', learning_rate_init=velho.learning_rate_init,
                        max_iter=1, random_state=0)
    Xs = sc.transform(X_amostra)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        novo.fit(Xs, velho.predict(Xs))       # so pra criar os atributos
    rng = np.random.RandomState(0)
    for k, (W, b) in enumerate(zip(velho.coefs_, velho.intercepts_)):
        Wn, bn = novo.coefs_[k], novo.intercepts_[k]
        Wn[:] = 0.0
        bn[:] = 0.0
        Wn[:W.shape[0], :W.shape[1]] = W
        bn[:b.shape[0]] = b
        if k < len(velho.coefs_) - 1:
            # entrada dos neuronios NOVOS: pequena e aleatoria (pra poderem
            # aprender); a SAIDA deles para a proxima camada fica 0 abaixo
            Wn[:W.shape[0], W.shape[1]:] = rng.normal(0, 0.01, (W.shape[0], Wn.shape[1] - W.shape[1]))
    # linhas dos neuronios novos na camada seguinte = 0 (ja zeradas): a rede
    # calcula o mesmo que o campeao
    novo.set_params(max_iter=velho.max_iter, early_stopping=velho.early_stopping,
                    n_iter_no_change=velho.n_iter_no_change)
    if hasattr(novo, '_optimizer'):
        del novo._optimizer
    novo.n_iter_ = 0
    novo._no_improvement_count = 0
    novo.loss_curve_ = []
    novo.best_loss_ = np.inf
    novo.validation_scores_ = [] if velho.early_stopping else None
    novo.best_validation_score_ = -np.inf if velho.early_stopping else None
    out = copy.deepcopy(pipe)
    out.steps[-1] = (out.steps[-1][0], novo)
    d = float(np.max(np.abs(novo.predict(Xs) - velho.predict(Xs))))
    print('  alargada: diferenca maxima pro campeao na amostra = %.2e' % d)
    return out



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='metrics/q_alvos.jsonl')
    ap.add_argument('--out', default='metrics/q_net.joblib')
    ap.add_argument('--folds', type=int, default=2,
                    help='GroupKFold por lider. MINIMO 2 (garante lider nunca '
                         'visto no treino) -- default ate 19/09 era 5, cortado '
                         'pro minimo que ainda cumpre a garantia (bloco 878, '
                         'AS-IS: cada fold a mais e outro fit completo, ~210s '
                         'em ~577k linhas)')
    ap.add_argument('--amostra-validacao', dest='amostra_validacao', type=int,
                    default=200_000,
                    help='os FOLDS de validacao rodam nesta amostra do corpus, '
                         'nao no corpus inteiro -- o modelo FINAL salvo sempre '
                         've tudo (bloco 878). 0 desliga a amostragem (usa o '
                         'corpus inteiro tambem na validacao, comportamento '
                         'antigo).')
    ap.add_argument('--modelo', choices=('rede', 'arvores'), default='rede',
                    help='REDE por default desde o bloco 800: medido em 120 mil '
                         'alvos, ela erra 18%% MENOS que as 300 arvores (0,0554 '
                         'x 0,0676) e a previsao custa 0,100 ms contra 8,47 -- '
                         '85x. Nao ha troca entre qualidade e velocidade aqui.')
    ap.add_argument('--modo', choices=('busca', 'bootstrap', 'todos'),
                    default=MODO_PADRAO,
                    help='qual CRITERIO DE ROTULO usar pra treinar (ver '
                         'docstring do modulo). Linha sem o campo `modo` conta '
                         'como \'bootstrap\'. Default \'bootstrap\' desde o '
                         'bloco 906: as linhas \'busca\' vem de um professor '
                         'que ESPIA a mao do oponente, e somadas ao corpus '
                         'fazem o modelo PERDER (24x39) do mesmo corpus sem '
                         'elas (75x46 PROMOVE).')
    ap.add_argument('--priorizar', dest='priorizar', action='store_true',
                    default=True,
                    help='replay PRIORIZADO (21/09/2026, pesquisa externa: '
                         'Prioritized Experience Replay) -- reamostra o '
                         'corpus com peso na VANTAGEM de cada jogada (o que '
                         'ela causou menos o valor da posicao antes dela, bloco '
                         '928): jogada muito ruim ou muito boa pesa mais, a '
                         'neutra menos. Default ligado; sem regua compativel '
                         'cai pra amostra uniforme, sem quebrar.')
    ap.add_argument('--sem-priorizar', dest='priorizar', action='store_false',
                    help='desliga o replay priorizado (comportamento antigo, '
                         'amostra uniforme).')
    ap.add_argument('--priorizar-alpha', type=float, default=0.6,
                    help='quanto o erro pesa na reamostragem (0=uniforme, '
                         '1=proporcional puro ao erro). Default 0,6, o mesmo '
                         'usado no paper original de Prioritized Experience '
                         'Replay (Schaul et al 2016) pra nao deixar a '
                         'distribuicao extrema demais.')
    ap.add_argument('--continua-de', dest='continua_de',
                    default=str(RAIZ / 'metrics' / 'q_net.joblib'),
                    help='modelo PROMOVIDO de onde o treino CONTINUA (bloco 913, '
                         'INSTRUCAO_MESTRA item 14.7). Default: o campeao atual.')
    ap.add_argument('--do-zero', dest='do_zero', action='store_true',
                    help='treina do zero em vez de continuar do promovido '
                         '(so pra experimento controlado).')
    ap.add_argument('--selfplay', default=str(SELFPLAY),
                    help='estados de fim de turno com o resultado, de onde sai a '
                         'consequencia de cada jogada (default: o do ciclo).')
    ap.add_argument('--rotulo', choices=('td', 'vitoria'), default='td',
                    help='td (default, bloco 913): valor da POSICAO 2 turnos '
                         'proprios depois (inclui a resposta do oponente); fim '
                         'de partida dentro do horizonte vale o resultado. '
                         'vitoria: formula do bloco 910 (metade vantagem de vida, '
                         'metade resultado final) -- so pra A/B.')
    ap.add_argument('--sem-consequencia', dest='consequencia', action='store_false',
                    default=True,
                    help='desliga o rotulo pela consequencia (bloco 910) e volta '
                         'a usar so o bootstrap do juiz fixo. Default LIGADO: o '
                         'ML tem que aprender com o que as jogadas causaram.')
    ap.add_argument('--camadas', default='64,32',
                    help='tamanho das camadas da rede (bloco 941: 128,64 do zero perdeu 5x23).')
    ap.add_argument('--queda-forte', dest='queda_forte', type=float, default=0.25,
                    help='so jogadas MUDOU de revisoes com queda >= isto ganham peso (bloco 946).')
    ap.add_argument('--peso-mudou', dest='peso_mudou', type=float, default=3.0,
                    help='peso das jogadas cuja revisao mudou o resultado (bloco 942).')
    ap.add_argument('--peso-revisao', dest='peso_revisao', type=float, default=2.0,
                    help='peso das jogadas das partidas de revisao da derrota (bloco 940).')
    ap.add_argument('--gen-min', dest='gen_min', type=int, default=0,
                    help='so linhas desta geracao em diante (experimento, bloco 940).')
    ap.add_argument('--peso-alternativas', dest='peso_alternativas', type=float,
                    default=0.0,
                    help='DESLIGADO (bloco 937: ciclos 45/46 deram 7x24 e 6x26, '
                         'contra 8-20 vitorias sem). simulacao como ensino (bloco 937): jogadas NAO feitas '
                         'das ultimas geracoes entram com a nota da simulacao, ate '
                         'N x as linhas reais. 0 desliga.')
    args = ap.parse_args()
    global CAMADAS
    CAMADAS = tuple(int(x) for x in args.camadas.split(','))

    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.model_selection import GroupKFold

    caminho = RAIZ / args.dataset
    if args.consequencia and caminho.resolve() == corpus_escolhidas.ORIGEM.resolve():
        # O treino so usa jogada com consequencia real (bloco 923), que e
        # subconjunto das ESCOLHIDAS: le o indice delas (~10% do corpus, mesma
        # ordem, mesmos bytes) em vez de reler os 3 GB (bloco 931). Com
        # --sem-consequencia o treino usa as alternativas tambem -> corpus todo.
        caminho = corpus_escolhidas.atualiza()
    X, y, grupos = [], [], []
    decisoes, escolhidas, familias = [], [], []
    revisao = []
    mudou = []
    n_lidas = n_filtradas_modo = n_sem_consequencia = 0
    from optcg_engine import value_net as _vn
    i_ld_q = list(_vn.FEATURE_NAMES_ALUNO).index('life_diff')
    n_cols = len(_vn.FEATURE_NAMES_ALUNO) + len(_vn.FEATURE_NAMES_ACAO) + len(_vn.FEATURE_NAMES_CORRIDA)
    traj = {}
    if args.consequencia:
        _aval = None
        if args.rotulo == 'td':
            # A regua do CICLO (bloco 917): o `ciclo.py` a retreina logo antes
            # deste passo, com TD dela mesma + resultado real. Nao e mais um
            # professor congelado.
            from optcg_engine.decision_engine import MODELO_ORDENA_PATH
            _aval = _vn.load_value_net(MODELO_ORDENA_PATH)
        traj = carrega_trajetorias(args.selfplay, avaliador=_aval)
    cobertura = {f: [0, 0, 0] for f in FAMILIAS_JOGO}   # linhas, escolhidas, consequencia
    ancora = {}
    with caminho.open(encoding='utf-8') as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            d = json.loads(linha)
            n_lidas += 1
            if not passa_filtro_modo(d, args.modo):
                n_filtradas_modo += 1
                continue
            if args.gen_min and (d.get('gen') or 0) < args.gen_min:
                continue
            feats, alvo = d.get('feats'), d.get('alvo')
            if not feats:
                continue
            if n_cols - 40 <= len(feats) < n_cols:
                # linha anterior as colunas mais novas (blocos 910/925): 0 e o
                # valor certo -- aquela decisao nao existia quando foi gravada.
                feats = feats + [0.0] * (n_cols - len(feats))
            fam = d.get('acao') or '?'
            cob = cobertura.get(fam)
            if cob is not None:
                cob[0] += 1
                cob[1] += 1 if d.get('escolhida') else 0
            if traj:
                d['ld_agora'] = feats[i_ld_q]
                _c = alvo_consequencia(d, traj, modo=args.rotulo)
                if _c is None:
                    # SO O QUE ACONTECEU ENSINA (decisao do usuario, 01/10/2026,
                    # bloco 923): linha sem consequencia real -- as alternativas
                    # que o bot NAO jogou e a gen 0 -- levava a NOTA que a regua
                    # deu na epoca. Era ~90% do treino: o Q imitava uma regua em
                    # vez de aprender com o resultado. Fica so a jogada
                    # escolhida (inclusive a de exploracao) com o desfecho dela.
                    n_sem_consequencia += 1
                    continue
                if d.get('escolhida') and alvo is not None:
                    # ancora das alternativas da MESMA decisao (bloco 937b):
                    # nota da simulacao da escolhida e a consequencia real dela
                    ancora[(d.get('gen'), d.get('match'), d.get('leader'),
                            d.get('decisao'))] = (float(alvo), float(_c))
                alvo = _c
                if cob is not None:
                    cob[2] += 1
            if alvo is None:
                continue   # decisao de defesa/alvo sem continuacao registrada
            X.append(feats)
            y.append(float(alvo))
            grupos.append(d.get('leader') or '?')
            # Quais linhas competiram na MESMA decisao, quem o professor
            # escolheu, e de que familia era a acao. Linhas antigas nao tem
            # `decisao` e ficam de fora da concordancia (nao do treino).
            # A GERACAO entra na chave (bloco 910): os ids de partida
            # recomecam do 0 a cada ciclo, e sem ela decisoes de partidas
            # diferentes eram tratadas como a mesma.
            decisoes.append(('%s:%s' % (d.get('gen'), d.get('match')), d.get('decisao')))
            escolhidas.append(bool(d.get('escolhida')))
            familias.append(d.get('acao') or '?')
            revisao.append(d.get('revisao') is not None)
            # PESO EXTRA SO NA QUEDA GRANDE (bloco 946): com controle de sorte,
            # a virada so supera a sorte de verdade acima de 0,25 de queda
            # (47% x 26%); abaixo disso `mudou` e quase todo sorte. Linha antiga
            # sem `queda` nao ganha peso extra.
            mudou.append(bool(d.get('mudou')) and (d.get('queda') or 0.0) >= args.queda_forte)

    print()
    print('  corpus: %d linhas lidas | %d descartadas pelo filtro --modo=%s '
          '| %d sem consequencia real (nota da regua, fora) | %d usadas'
          % (n_lidas, n_filtradas_modo, args.modo, n_sem_consequencia, len(X)))
    print()
    print('  O QUE O ML APRENDE, por decisao do jogo (bloco 910):')
    print('  %-11s %9s %10s %22s' % ('decisao', 'linhas', 'escolhidas', 'rotulo pela consequencia'))
    for fam in FAMILIAS_JOGO:
        n, e, c = cobertura[fam]
        aviso = '   <-- NAO APRENDE esta decisao' if c == 0 else ''
        print('  %-11s %9d %10d %22d%s' % (fam, n, e, c, aviso))

    if len(X) < 500:
        raise SystemExit('corpus pequeno demais (%d alvos) -- gere mais antes, '
                         'ou use --modo todos/bootstrap se \'busca\' ainda nao '
                         'acumulou volume' % len(X))
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    grupos = np.asarray(grupos)
    decisoes = np.asarray([('%s|%s' % dc) for dc in decisoes])
    escolhidas = np.asarray(escolhidas)
    familias = np.asarray(familias)
    n_lideres = len(set(grupos.tolist()))

    print()
    print('  alvos: %d | features: %d | lideres: %d'
          % (len(X), X.shape[1], n_lideres))
    print('  alvo: media %.3f | desvio %.3f | distintos %d'
          % (y.mean(), y.std(), len(set(np.round(y, 4).tolist()))))

    # AMOSTRA SO PRA VALIDACAO (bloco 878) -- os folds nunca viram o modelo
    # salvo (esse treina no X/y INTEIROS mais abaixo), entao nao precisam do
    # corpus inteiro pra medir generalizacao. Semente FIXA (reprodutivel).
    if args.amostra_validacao and len(X) > args.amostra_validacao:
        idx_val = np.random.RandomState(0).choice(
            len(X), size=args.amostra_validacao, replace=False)
        idx_val.sort()  # mantem a ordem original (decisoes agrupadas)
        Xv, yv, gruposv = X[idx_val], y[idx_val], grupos[idx_val]
        decisoesv = decisoes[idx_val]
        escolhidasv = escolhidas[idx_val]
        familiasv = familias[idx_val]
        print('  validacao rodando numa amostra de %d (o modelo final treina '
              'nos %d inteiros)' % (len(Xv), len(X)))
    else:
        Xv, yv, gruposv = X, y, grupos
        decisoesv, escolhidasv, familiasv = decisoes, escolhidas, familias
    n_lideres_val = len(set(gruposv.tolist()))

    def novo():
        # REDE LEVE (NNUE-style), default desde o bloco 800. A previsao e duas
        # multiplicacoes de matriz -- 0,100 ms em numpy puro contra 8,47 ms das
        # 300 arvores percorridas em Python, e com erro 18% MENOR.
        #
        # O `--modelo arvores` fica pra reproduzir a comparacao, nao pra uso.
        if args.modelo == 'arvores':
            return HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.02, max_depth=3,
                min_samples_leaf=60, early_stopping=True,
                validation_fraction=0.15, l2_regularization=1.0, random_state=0)
        return make_pipeline(
            StandardScaler(),
            MLPRegressor(hidden_layer_sizes=CAMADAS, activation='relu',
                         solver='adam', learning_rate_init=3e-3, max_iter=60,
                         early_stopping=True, n_iter_no_change=5,
                         random_state=0))

    folds = min(args.folds, n_lideres_val)
    if folds < 2:
        raise SystemExit('precisa de pelo menos 2 lideres pra validar por lider')

    # BASE DE COMPARACAO: prever sempre a media. Sem isto, um R2 qualquer
    # parece bom -- e a regra do projeto e ter um controle que pode falhar.
    erros_modelo, erros_base = [], []
    # CONCORDANCIA TOP-1: por decisao, o argmax do aluno bate a escolha do
    # professor? E o que decide se o Q substitui a arvore -- erro absoluto
    # mede o VALOR, e quem decide e o ARGMAX.
    conc_ok = conc_tot = 0
    conc_fam = {}
    # POR LIDER individual (bloco 878) -- cada lider so aparece no fold em
    # que foi held-out, entao acumula direto sem custo extra de treino.
    # erro_lider: lider -> lista de |erro| das linhas dele; conc_lider: lider
    # -> [acertos, total] de concordancia, mesmo formato de conc_fam.
    erro_lider = {}
    conc_lider = {}
    # CONTROLE QUE PODE FALHAR (regra do projeto): escolher no ACASO entre as
    # candidatas da decisao. Com ~4,8 candidatas isso ja da ~21%, entao a
    # concordancia sozinha nao diz nada -- o que informa e a distancia ate aqui.
    conc_acaso = 0.0
    gkf = GroupKFold(n_splits=folds)
    print()
    print('  fold | lideres no teste | erro medio do MODELO | erro da MEDIA')
    for k, (tr, te) in enumerate(gkf.split(Xv, yv, gruposv), 1):
        m = novo().fit(Xv[tr], yv[tr])
        pred = m.predict(Xv[te])
        em = float(np.mean(np.abs(pred - yv[te])))
        eb = float(np.mean(np.abs(yv[tr].mean() - yv[te])))
        erros_modelo.append(em)
        erros_base.append(eb)

        for pos, i in enumerate(te):
            erro_lider.setdefault(gruposv[i], []).append(abs(pred[pos] - yv[i]))

        # so as decisoes do fold de TESTE, e so as que tem id e escolhida
        grupos_dec = {}
        for pos, i in enumerate(te):
            dec = decisoesv[i]
            if dec.endswith('|None') or dec.startswith('None|'):
                continue
            grupos_dec.setdefault(dec, []).append((pos, i))
        for dec, itens in grupos_dec.items():
            if len(itens) < 2:
                continue          # decisao de uma candidata so nao decide nada
            alvo_prof = [i for _p, i in itens if escolhidasv[i]]
            if len(alvo_prof) != 1:
                continue          # sem professor marcado, nao ha o que comparar
            melhor = max(itens, key=lambda t: pred[t[0]])[1]
            acertou = (melhor == alvo_prof[0])
            conc_ok += 1 if acertou else 0
            conc_acaso += 1.0 / len(itens)
            conc_tot += 1
            fam = familiasv[alvo_prof[0]]
            d2 = conc_fam.setdefault(fam, [0, 0])
            d2[1] += 1
            d2[0] += 1 if acertou else 0
            lid = gruposv[alvo_prof[0]]
            d3 = conc_lider.setdefault(lid, [0, 0])
            d3[1] += 1
            d3[0] += 1 if acertou else 0
        print('  %4d | %16d | %20.4f | %13.4f'
              % (k, len(set(gruposv[te].tolist())), em, eb))

    em = float(np.mean(erros_modelo))
    eb = float(np.mean(erros_base))
    ganho = 100.0 * (eb - em) / max(1e-9, eb)
    print()
    print('  erro medio FORA DA AMOSTRA : %.4f' % em)
    print('  erro de prever a MEDIA     : %.4f' % eb)
    print('  o modelo erra %.1f%% menos que a media' % ganho)
    if ganho < 5.0:
        print('  => NAO APRENDEU. O Q nao distingue acao boa de ruim ainda.')
    else:
        print('  => APRENDEU a ordenar acao. Proximo: ligar e medir no motor.')

    conc = (100.0 * conc_ok / conc_tot) if conc_tot else None
    print()
    if conc is None:
        print('  CONCORDANCIA TOP-1: sem amostra -- o corpus nao tem `decisao`/')
        print('  `escolhida` (linhas anteriores ao bloco 809). Gere um ciclo novo.')
    else:
        acaso = 100.0 * conc_acaso / conc_tot
        print('  CONCORDANCIA TOP-1 COM O PROFESSOR: %.1f%% (%d decisoes)'
              % (conc, conc_tot))
        print('     escolher no ACASO daria %.1f%%  ->  %+.1f pp acima do acaso'
              % (acaso, conc - acaso))
        print('     a mesma acao que a arvore escolheria, FORA DA AMOSTRA.')
        print('     E ISTO, nao o erro acima, que decide se o Q substitui a')
        print('     arvore: o motor escolhe por argmax, nao por valor.')
        if conc_fam:
            print()
            print('     por familia de acao:')
            for fam, (ok, tot) in sorted(conc_fam.items(), key=lambda kv: -kv[1][1]):
                print('       %-12s %5.1f%%  (%d decisoes)'
                      % (fam, 100.0 * ok / max(1, tot), tot))

    # POR LIDER individual (bloco 878) -- ate aqui o relatorio so mostrava
    # fold (mistura varios lideres) e familia; um lider especifico podia
    # generalizar mal e sumir na media. Ordenado por volume de decisoes,
    # mesma convencao de `decision_quality_full.py`.
    por_lider = {}
    for lid in set(list(erro_lider.keys()) + list(conc_lider.keys())):
        erros = erro_lider.get(lid, [])
        ok, tot = conc_lider.get(lid, [0, 0])
        por_lider[lid] = {
            'erro_medio': round(float(np.mean(erros)), 4) if erros else None,
            'n_alvos': len(erros),
            'concordancia_pct': round(100.0 * ok / tot, 1) if tot else None,
            'decisoes': tot,
        }
    if por_lider:
        print()
        print('  POR LIDER (validacao, cada lider held-out em 1 fold):')
        print('    %-14s %10s %12s %14s %10s'
              % ('lider', 'alvos', 'erro medio', 'concordancia', 'decisoes'))
        for lid, d in sorted(por_lider.items(), key=lambda kv: -kv[1]['decisoes']):
            erro_txt = '%.4f' % d['erro_medio'] if d['erro_medio'] is not None else '?'
            conc_txt = ('%.1f%%' % d['concordancia_pct']
                       if d['concordancia_pct'] is not None else '?')
            print('    %-14s %10d %12s %14s %10d'
                  % (lid, d['n_alvos'], erro_txt, conc_txt, d['decisoes']))

    # ── REPLAY PRIORIZADO (21/09/2026) ──────────────────────────────────────
    # MLPRegressor do sklearn nao aceita `sample_weight` -- a forma
    # compativel de priorizar e REAMOSTRAR com reposicao, peso proporcional
    # ao erro (aproximacao padrao de PER quando o treinador nao suporta peso
    # de amostra direto). O erro vem do CAMPEAO ja salvo (`Q_CAMPEAO`), nao
    # de um fit extra -- FORA DA AMOSTRA de treino dele (o campeao foi salvo
    # ANTES desta chamada), e barato pra medir agora gracas ao
    # `_forward_rapido` (ganho de 3,1x medido no mesmo dia). Sem campeao
    # compativel (1o ciclo, cold start, ou dimensao de feature mudou),
    # degrada pra amostra UNIFORME -- nunca trava o treino por falta dele.
    X_treino, y_treino = X, y
    campeao = (None if (args.do_zero or args.modelo != 'rede')
               else modelo_do_campeao(args.continua_de, X.shape[1]))
    if args.priorizar:
        pesos = None
        try:
            # PRIORIDADE = a VANTAGEM da propria jogada (bloco 928, pedido do
            # usuario: jogada ruim pesa mais, a boa tambem e estudada pra ser
            # mantida, a neutra pouco): |consequencia - valor da posicao ANTES
            # da jogada|. Antes pesava pelo erro do campeao -- em qualquer
            # direcao e medido contra um modelo antigo, nao pelo quao boa ou
            # ruim a jogada foi.
            _rg = _vn.load_value_net(
                __import__('optcg_engine.decision_engine', fromlist=['x']).MODELO_ORDENA_PATH)
            _n_est = len(_vn.FEATURE_NAMES_ALUNO)
            if _rg and list(_rg.get('feature_names') or []) == list(_vn.FEATURE_NAMES_ALUNO):
                _m = _rg['modelo']
                _v = (_m.predict_proba(X[:, :_n_est])[:, 1] if hasattr(_m, 'predict_proba')
                      else _m.predict(X[:, :_n_est]))
                vantagem = y - np.asarray(_v, dtype=float)
                prio = (np.abs(vantagem) + 1e-3) ** args.priorizar_alpha
                pesos = prio / prio.sum()
        except Exception:
            pesos = None
        if pesos is not None:
            idx_prio = np.random.RandomState(1).choice(
                len(X), size=len(X), replace=True, p=pesos)
            X_treino, y_treino = X[idx_prio], y[idx_prio]
            print()
            print('  replay priorizado: reamostrado com peso na VANTAGEM de cada '
                  'jogada (alpha=%.2f, %d linhas unicas de %d)'
                  % (args.priorizar_alpha, len(set(idx_prio.tolist())), len(X)))
        else:
            print()
            print('  replay priorizado pedido mas sem regua compativel -- '
                  'treinando com amostra uniforme')

    # PESO DA REVISAO DA DERROTA (bloco 940, pedido do usuario): as jogadas
    # das partidas rejogadas a partir do turno do erro sao o sinal de "joguei
    # diferente e o resultado mudou". Entram com peso extra (copias a mais) --
    # `--peso-revisao` 2 = o dobro de uma jogada comum (ponto de partida).
    _rev = np.asarray(revisao, dtype=bool)
    n_rev = int(_rev.sum())
    if n_rev and args.peso_revisao > 1:
        _extra = int(round(args.peso_revisao)) - 1
        X_treino = np.vstack([X_treino] + [X[_rev]] * _extra)
        y_treino = np.concatenate([y_treino] + [y[_rev]] * _extra)
        _o = np.random.RandomState(4).permutation(len(X_treino))
        X_treino, y_treino = X_treino[_o], y_treino[_o]
    print()
    print('  revisao da derrota: %d jogadas, peso %.0fx' % (n_rev, args.peso_revisao))
    # MUDOU O RESULTADO (bloco 942): mesmo ponto, jogada diferente, resultado
    # real diferente -- peso `--peso-mudou` (3 = ponto de partida).
    _mud = np.asarray(mudou, dtype=bool)
    n_mud = int(_mud.sum())
    if n_mud and args.peso_mudou > 1:
        _extra = int(round(args.peso_mudou)) - 1
        X_treino = np.vstack([X_treino] + [X[_mud]] * _extra)
        y_treino = np.concatenate([y_treino] + [y[_mud]] * _extra)
        _o = np.random.RandomState(5).permutation(len(X_treino))
        X_treino, y_treino = X_treino[_o], y_treino[_o]
    print('  jogadas em que a revisao MUDOU o resultado: %d, peso %.0fx' % (n_mud, args.peso_mudou))

    # SIMULACAO COMO ENSINO (bloco 937, decisao do usuario 04/10/2026): as
    # jogadas que o bot NAO fez entram com a nota que a simulacao deu a elas
    # (valor do estado que cada uma produz, media dos mundos cegos). Antes so a
    # escolhida ensinava, e o Q so aprendia o valor do que ja costumava fazer.
    # So as ultimas geracoes (`corpus_escolhidas.GERACOES_ALT`): a nota vem da
    # regua da epoca. Peso MENOR que o resultado real: no maximo
    # `--peso-alternativas` x o numero de linhas reais (ponto de partida, nao
    # calibrado). Se a regua errar, a exploracao + a consequencia real corrigem.
    # So no modelo final -- a validacao acima continua medindo so o real.
    n_alt = 0
    if args.peso_alternativas > 0 and traj and corpus_escolhidas.ALTERNATIVAS.exists():
        Xa, ya = [], []
        with corpus_escolhidas.ALTERNATIVAS.open(encoding='utf-8') as fh:
            for linha in fh:
                d = json.loads(linha)
                f, a = d.get('feats'), d.get('alvo')
                if not f or a is None or d.get('acao') not in FAMILIAS_JOGO:
                    continue
                # MESMA REGUA da escolhida (bloco 937b): a nota crua da
                # simulacao e o valor LOGO apos a jogada, sem a resposta do
                # oponente; a escolhida aprende o valor 2 turnos depois. Misturar
                # as duas ensinava 'jogada nao feita parece melhor' (ciclo 45,
                # 7x24). Agora a simulacao entra so como DIFERENCA dentro da
                # decisao: consequencia real da escolhida + (sim desta - sim da
                # escolhida). Sem escolhida com consequencia, a linha nao entra.
                anc = ancora.get((d.get('gen'), d.get('match'), d.get('leader'),
                                  d.get('decisao')))
                if anc is None:
                    continue
                a = anc[1] + (float(a) - anc[0])
                if not passa_filtro_modo(d, args.modo):
                    continue
                if n_cols - 40 <= len(f) < n_cols:
                    f = f + [0.0] * (n_cols - len(f))
                if len(f) != X.shape[1]:
                    continue
                Xa.append(f)
                ya.append(float(a))
        teto = int(args.peso_alternativas * len(X_treino))
        if Xa:
            Xa, ya = np.asarray(Xa, dtype=float), np.asarray(ya, dtype=float)
            if len(Xa) > teto:
                ia = np.random.RandomState(2).choice(len(Xa), size=teto, replace=False)
                Xa, ya = Xa[ia], ya[ia]
            n_alt = len(Xa)
            X_treino = np.vstack([X_treino, Xa])
            y_treino = np.concatenate([y_treino, ya])
            ordem = np.random.RandomState(3).permutation(len(X_treino))
            X_treino, y_treino = X_treino[ordem], y_treino[ordem]
        print()
        print('  simulacao como ensino: +%d jogadas NAO feitas com a nota da '
              'simulacao (teto %.2f x %d reais)' % (n_alt, args.peso_alternativas,
                                                    len(X)))

    if campeao is not None and tuple(campeao.steps[-1][1].hidden_layer_sizes) != CAMADAS:
        # REDE MAIOR QUE O PROMOVIDO (bloco 941): ALARGA o campeao em vez de
        # treinar do zero (do zero perdeu 5x23 -- jogava sem o acumulo de
        # treinos do campeao). Os pesos dele sao copiados; os neuronios novos
        # entram com saida ZERO, entao a rede nova comeca calculando EXATAMENTE
        # o mesmo que o campeao, e o treino continua dali.
        _antes = tuple(campeao.steps[-1][1].hidden_layer_sizes)
        campeao = alarga_rede(campeao, CAMADAS, X_treino[:256])
        print()
        print('  rede alargada do promovido: %s -> %s' % (_antes, CAMADAS))
    if campeao is not None:
        # CONTINUA do promovido: mesma normalizacao do campeao (reajustar o
        # scaler tiraria o sentido dos pesos) e o treino da rede segue dos
        # pesos dele (warm_start).
        _sc, _mlp = campeao.steps[0][1], campeao.steps[-1][1]
        _mlp.set_params(warm_start=True)
        _mlp.fit(_sc.transform(X_treino), y_treino)
        modelo = campeao
        print()
        print('  treino CONTINUADO do modelo promovido: %s' % args.continua_de)
    else:
        modelo = novo().fit(X_treino, y_treino)
        print()
        print('  treino DO ZERO (%s)' % ('--do-zero' if args.do_zero
                                         else 'sem promovido compativel'))
    bundle = {
        'modelo': modelo,
        'tipo': 'q',
        'familia': args.modelo,
        'n_alvos': int(len(X)),
        'n_features': int(X.shape[1]),
        'n_lideres': int(n_lideres),
        'erro_fora_amostra': em,
        'concordancia_top1': conc,
        'concordancia_acaso': (100.0 * conc_acaso / conc_tot) if conc_tot else None,
        'concordancia_decisoes': conc_tot,
        'concordancia_por_familia': {k: {'acerto_pct': round(100.0 * v[0] / max(1, v[1]), 1),
                                         'decisoes': v[1]}
                                     for k, v in conc_fam.items()},
        'por_lider': por_lider,
        'amostra_validacao': int(len(Xv)),
        'erro_da_media': eb,
        'ganho_pct': ganho,
        'dataset': args.dataset,
        'lideres': sorted(set(grupos.tolist())),
        'replay_priorizado': bool(args.priorizar and X_treino is not X),
        'alternativas_simulacao': int(n_alt),
        'revisao_linhas': n_rev, 'peso_revisao': args.peso_revisao,
        'cobertura': {f: {'linhas': v[0], 'escolhidas': v[1], 'consequencia': v[2]}
                      for f, v in cobertura.items()},
        'rotulo_consequencia': (args.rotulo if traj else None),
        'continuado_de': (args.continua_de if campeao is not None else None),
    }
    import joblib
    saida = RAIZ / args.out
    saida.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, saida)
    print('  modelo Q -> %s' % saida)
    print('  alvos por lider: %s ...' % Counter(grupos.tolist()).most_common(4))
    print()
    print('  ISTO E ERRO DE PREVISAO, NAO E GANHO NO MOTOR. O que decide se o Q')
    print('  substitui a arvore e a medicao no jogo: velocidade E se ele escolhe')
    print('  a mesma acao que o professor escolheria.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
