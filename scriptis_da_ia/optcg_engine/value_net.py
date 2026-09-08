"""
value_net.py -- FUNCAO DE VALOR APRENDIDA POR AUTO-JOGO (self-play).

Decisao do usuario (08/09/2026): caminho HIBRIDO, atras de flag. Ver o
bloco correspondente no HANDOFF.md.

O QUE ISTO E, E O QUE NAO E
---------------------------
NAO e a clonagem de comportamento dos blocos 680-706 (`policy.py`), que
foi REPROVADA quatro vezes e continua reprovada -- aquela aprendia "que
carta o humano escolheu" a partir de 171 logs finitos, sem nenhuma nocao
de vitoria, e falhava por *distribution shift* (bloco 683: AUC 0,851
isolado e MESMO ASSIM piora ligada no laco de decisao).

Isto e outra coisa: aprende **quanto vale um ESTADO**, com rotulo vindo
de **quem ganhou a partida**, sobre dado gerado pelo proprio motor em
auto-jogo. Duas consequencias que atacam exatamente o que matou a
clonagem:

  1. **Dado ilimitado** -- o motor gera. Nao depende do banco de 171 logs
     humanos, que a `curva_aprendizado.py` ja mostrou SATURADO em ~26%
     (bloco 707): mais partidas humanas do mesmo tipo nao desbloqueiam
     aquele caminho.
  2. **Sem distribution shift por construcao** -- o dado vem da politica
     que esta jogando. Os estados de treino SAO os estados de uso.

HIBRIDO: o que ele NAO substitui
--------------------------------
O valor aprendido **soma** a `_evaluate_state_v2` (heuristica de hoje) e
convive com `bonus_alinhamento` (`human_alignment`/`human_sequence_
alignment`), que continua sendo o termo de semelhanca com o humano. Isso e
deliberado, e e a razao de o usuario ter escolhido a opcao 3: auto-jogo
otimiza GANHAR, e a metrica oficial do projeto e SEMELHANCA COM O HUMANO
(agregado de acerto por decisao, 49,3% -> meta 85-90%). Um valor aprendido
solto pode ficar mais forte e PIORAR a metrica oficial. Mantendo os tres
termos na mesma soma, a semelhanca humana age como regularizador -- e o
peso relativo vira um numero MEDIDO, nao uma aposta.

FONTE UNICA DE FEATURES (mesma disciplina de `policy.py`)
---------------------------------------------------------
`state_features()` e importada TANTO pelo gerador de dataset QUANTO pelo
motor em runtime. Featurizacao duplicada entre treino e uso e a forma
classica de o modelo receber em producao um vetor diferente do que viu no
treino, e falhar em silencio. E a `REGRA_SEM_DUPLICACAO.md` aplicada a ML.

SEM ONE-HOT DE LIDER -- de proposito
------------------------------------
Defeito real, achado no bloco 702: `policy.py:98` tinha one-hot de LIDER e
o split de validacao era POR PARTIDA. Aquela validacao **nunca poderia
detectar falha de generalizacao pra deck novo** -- o modelo decorava o
lider. Aqui todas as features sao quantidades GENERICAS de estado (vida,
board, mao, DON, counter), sem identidade de carta ou de lider, porque o
objetivo registrado do projeto e jogar bem com QUALQUER deck. O treino
valida sob GroupKFold POR LIDER (`treinar_value.py`) pela mesma razao.

DEGRADACAO GRACIOSA: sem arquivo de modelo, `load_value_net()` devolve
None e o motor segue exatamente como sempre. O modelo e artefato opcional,
nunca dependencia dura.
"""
from __future__ import annotations

import os

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'metrics', 'value_net.joblib')

# Nomes na MESMA ordem que `state_features` monta o vetor. Existe pra o
# relatorio de treino poder dizer QUAL feature pesa, e pra conferir
# dimensao contra o modelo salvo.
FEATURE_NAMES = [
    'life_mine', 'life_opp', 'life_diff',
    'hand_mine', 'hand_opp', 'hand_diff',
    'don_field_mine', 'don_field_opp', 'don_diff',
    'don_available_mine',
    'chars_mine', 'chars_opp', 'chars_diff',
    'power_mine', 'power_opp', 'power_diff',
    'cost_mine', 'cost_opp',
    'blockers_mine', 'blockers_opp', 'blockers_diff',
    'active_mine', 'active_opp',
    'rested_mine', 'rested_opp',
    'counter_hand_mine', 'counter_hand_opp',
    'deck_mine', 'deck_opp',
    'trash_mine', 'trash_opp',
    'turn',
]

_CACHE: dict = {}
_AVISOU: set = set()


def _num(fn, default: float = 0.0) -> float:
    """Uma feature nunca pode derrubar o motor. O estado clonado da busca
    pode estar numa configuracao que um acessor nao espera -- aqui o
    fallback e explicito e LOCAL, feature a feature, em vez de um
    `try/except` gigante em volta do vetor inteiro (que esconderia um
    vetor meio-montado, o tipo de falha silenciosa do bloco 682)."""
    try:
        v = fn()
        return float(v) if v is not None else default
    except Exception:
        return default


def _chars(estado) -> list:
    try:
        return list(estado.field_chars or [])
    except Exception:
        return []


def state_features(p, opp) -> list:
    """Vetor que descreve o estado do ponto de vista de `p`.

    SO quantidades genericas -- nada de identidade de carta/lider (ver o
    docstring do modulo). Ordem identica a `FEATURE_NAMES`."""
    ch_m, ch_o = _chars(p), _chars(opp)
    n_ch_m, n_ch_o = float(len(ch_m)), float(len(ch_o))

    def _power(chars):
        return sum(float(getattr(c, 'power', 0) or 0) for c in chars) / 1000.0

    def _cost(chars):
        return sum(float(getattr(c, 'cost', 0) or 0) for c in chars)

    def _rested(chars):
        return float(len([c for c in chars if getattr(c, 'rested', False)]))

    life_m = _num(p.life_count)
    life_o = _num(opp.life_count)
    hand_m = _num(lambda: len(p.hand))
    hand_o = _num(lambda: len(opp.hand))
    don_m = _num(p.don_on_field)
    don_o = _num(opp.don_on_field)
    pw_m, pw_o = _power(ch_m), _power(ch_o)
    bl_m = _num(lambda: len(p.blockers_active()))
    bl_o = _num(lambda: len(opp.blockers_active()))

    return [
        life_m, life_o, life_m - life_o,
        hand_m, hand_o, hand_m - hand_o,
        don_m, don_o, don_m - don_o,
        _num(lambda: getattr(p, 'don_available', 0)),
        n_ch_m, n_ch_o, n_ch_m - n_ch_o,
        pw_m, pw_o, pw_m - pw_o,
        _cost(ch_m), _cost(ch_o),
        bl_m, bl_o, bl_m - bl_o,
        _num(lambda: len(p.active_chars())),
        _num(lambda: len(opp.active_chars())),
        _rested(ch_m), _rested(ch_o),
        _num(p.counter_in_hand) / 1000.0,
        _num(opp.counter_in_hand) / 1000.0,
        _num(lambda: len(p.deck)),
        _num(lambda: len(opp.deck)),
        _num(lambda: len(p.trash)),
        _num(lambda: len(opp.trash)),
        _num(lambda: getattr(p, 'turn', 0)),
    ]


def load_value_net(path: str | None = None):
    """Carrega (com cache) o modelo. None se indisponivel -- sem
    sklearn/joblib, ou sem modelo treinado ainda."""
    caminho = path or MODEL_PATH
    if caminho in _CACHE:
        return _CACHE[caminho]
    bundle = None
    try:
        if os.path.exists(caminho):
            import joblib
            bundle = joblib.load(caminho)
    except Exception:
        bundle = None       # nunca derruba o motor por causa do modelo
    _CACHE[caminho] = bundle
    return bundle


def check_dims(bundle, n: int) -> bool:
    """Confere que o vetor de runtime tem o MESMO tamanho que o modelo viu
    no treino, e AVISA ALTO (stderr, 1x) quando nao tem.

    Mesma protecao de `policy.py:check_dims`, pela mesma falha real
    (bloco 682): modelo re-treinado com features novas ENQUANTO uma
    medicao rodava, `except` generico engolindo o erro de dimensao, e a
    medicao saindo com o modelo DESLIGADO em silencio -- um numero errado
    em que alguem vai acreditar."""
    modelo = bundle.get('modelo') if isinstance(bundle, dict) else None
    esperado = getattr(modelo, 'n_features_in_', None)
    if esperado is not None and n != esperado:
        chave = (n, esperado)
        if chave not in _AVISOU:
            _AVISOU.add(chave)
            import sys
            print(f'[VALUE_NET] AVISO: modelo espera {esperado} features, '
                  f'runtime montou {n} -- valor aprendido DESLIGADO. '
                  f'Re-treine (treinar_value.py) ou confira '
                  f'optcg_engine/value_net.py.', file=sys.stderr)
        return False
    return True


def win_prob(p, opp, bundle=None) -> float | None:
    """Probabilidade estimada de `p` VENCER a partida a partir deste
    estado. None quando o modelo nao esta disponivel/compativel -- o
    chamador entao nao soma nada e o motor segue identico."""
    bundle = bundle if bundle is not None else load_value_net()
    if not bundle:
        return None
    modelo = bundle.get('modelo') if isinstance(bundle, dict) else None
    if modelo is None:
        return None
    feats = state_features(p, opp)
    if not check_dims(bundle, len(feats)):
        return None
    try:
        return float(modelo.predict_proba([feats])[0][1])
    except Exception:
        return None
