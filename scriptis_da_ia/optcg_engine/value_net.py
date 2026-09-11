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

# VISAO RICA (bloco 764) -- as 32 acima sao TODAS contagens e agregados, sem
# nenhuma nocao de QUEM esta no board. Medido no bloco 763: ligar a escolha de
# alvo na busca empatou 96% dos pares, e a suspeita e justamente esta -- KOar o
# personagem A ou o B com poder parecido deixa as 32 IDENTICAS, entao a regua
# nao tem como preferir e escolhe arbitrariamente do mesmo jeito que a
# heuristica fixa fazia. Estas descrevem QUALIDADE do board, nao so quantidade.
FEATURE_NAMES_RICAS = FEATURE_NAMES + [
    'power_max_mine', 'power_max_opp', 'power_max_diff',
    'cost_max_mine', 'cost_max_opp',
    'don_attached_mine', 'don_attached_opp',
    'rush_mine', 'rush_opp',
    'double_attack_mine', 'double_attack_opp',
    'unblockable_mine', 'unblockable_opp',
    'banish_mine', 'banish_opp',
    'com_efeito_mine', 'com_efeito_opp',
]

# ONDA 1 (bloco 766) -- principio do usuario: "nosso ML nao pode ser cego para
# nenhuma informacao". Auditoria de `GameState` achou 39 campos, dos quais o
# modelo enxergava derivados de 8. Esta onda traz o que FALTAVA de mais
# gritante, em tres grupos:
#
#  a) EVENTOS DO TURNO -- as 49 descrevem a FOTO do board; estes sabem o que
#     ACONTECEU (quanto dano saiu, o que morreu, quanto DON queimou). E de
#     onde vem boa parte dos 16 termos da heuristica (ideia do usuario de
#     aproveitar o conhecimento dela como feature em vez de peso).
#  b) `is_first` -- vantagem estrutural conhecida neste jogo, e o modelo nao
#     tinha como saber quem comecou.
#  c) DON completo e RESTRICOES ativas -- o que esta proibido neste turno
#     muda o valor de um board identico.
FEATURE_NAMES_V3 = FEATURE_NAMES_RICAS + [
    # (a) eventos do turno
    'dmg_dealt_mine', 'dmg_dealt_opp',
    'char_kill_value_mine', 'char_kill_value_opp',
    'don_spent_combat_mine', 'don_spent_combat_opp',
    'chars_played_mine', 'chars_played_opp',
    'counters_used_mine', 'counters_used_opp',
    'searchers_used_mine', 'searchers_used_opp',
    'triggers_activated_mine', 'triggers_activated_opp',
    # (b) quem comecou
    'is_first_mine',
    # (c) DON completo
    'don_rested_mine', 'don_rested_opp',
    'don_deck_mine', 'don_deck_opp',
    'frozen_don_mine', 'frozen_don_opp',
    # (c) restricoes ativas
    'cant_play_hand_mine', 'cant_play_hand_opp',
    'cant_attack_leader_mine', 'cant_attack_leader_opp',
    'cant_take_life_mine', 'cant_take_life_opp',
    'cant_play_cost_gte_mine', 'cant_play_cost_gte_opp',
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


def state_features(p, opp, nomes=None) -> list:
    """Vetor que descreve o estado do ponto de vista de `p`.

    Sem identidade de CARTA (nada de codigo ou nome -- ver o docstring do
    modulo): as features ricas descrevem PROPRIEDADES do board (keywords,
    DON anexado, quem e o maior), nao qual carta e.

    `nomes` = lista de features a devolver, NESSA ordem. Default: as 32
    originais. Existe pra o modelo velho (32) e o novo (49) conviverem no
    MESMO processo -- `win_prob` passa `bundle['feature_names']`, entao o
    duelo entre duas geracoes com visoes diferentes e possivel. Sem isso, o
    A/B nao teria como ser feito (bloco 764)."""
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

    def _mx(chars, attr, pad=0.0):
        return max((float(getattr(c, attr, 0) or 0) for c in chars), default=pad)

    def _conta(chars, *attrs):
        return float(sum(1 for c in chars
                         if any(getattr(c, a, False) for a in attrs)))

    def _com_efeito(chars):
        # Personagem que TEM habilidade vs vanilla -- KOar um ou outro e
        # decisao muito diferente, e nada nas 32 originais distingue os dois.
        # Import TARDIO: `decision_engine` importa este modulo, entao um
        # import no topo seria circular.
        from optcg_engine.decision_engine import get_card_effects
        n = 0
        for c in chars:
            try:
                if get_card_effects(getattr(c, 'code', '')):
                    n += 1
            except Exception:
                pass
        return float(n)

    pw_max_m, pw_max_o = _mx(ch_m, 'power') / 1000.0, _mx(ch_o, 'power') / 1000.0
    valores = {
        'power_max_mine': pw_max_m, 'power_max_opp': pw_max_o,
        'power_max_diff': pw_max_m - pw_max_o,
        'cost_max_mine': _mx(ch_m, 'cost'), 'cost_max_opp': _mx(ch_o, 'cost'),
        'don_attached_mine': float(sum(int(getattr(c, 'don_attached', 0) or 0) for c in ch_m)),
        'don_attached_opp': float(sum(int(getattr(c, 'don_attached', 0) or 0) for c in ch_o)),
        'rush_mine': _conta(ch_m, 'has_rush', 'rush_this_turn'),
        'rush_opp': _conta(ch_o, 'has_rush', 'rush_this_turn'),
        'double_attack_mine': _conta(ch_m, 'has_double_attack'),
        'double_attack_opp': _conta(ch_o, 'has_double_attack'),
        'unblockable_mine': _conta(ch_m, 'has_unblockable', 'unblockable_this_turn'),
        'unblockable_opp': _conta(ch_o, 'has_unblockable', 'unblockable_this_turn'),
        'banish_mine': _conta(ch_m, 'has_banish'), 'banish_opp': _conta(ch_o, 'has_banish'),
        'com_efeito_mine': _com_efeito(ch_m), 'com_efeito_opp': _com_efeito(ch_o),
    }

    def _g(x, campo, pad=0.0):
        try:
            v = getattr(x, campo, pad)
            return float(v) if v is not None else float(pad)
        except Exception:
            return float(pad)

    # ONDA 1 (bloco 766). `_g` e tolerante de proposito: campo que sumir numa
    # versao futura do estado vira 0.0 em vez de derrubar o motor -- mesmo
    # principio do `win_prob`, que degrada em vez de quebrar.
    for campo, base_nome in (
            ('dmg_dealt', 'dmg_dealt'), ('char_kill_value', 'char_kill_value'),
            ('don_spent_on_combat', 'don_spent_combat'),
            ('chars_played', 'chars_played'), ('counters_used', 'counters_used'),
            ('searchers_used', 'searchers_used'),
            ('triggers_activated', 'triggers_activated'),
            ('don_rested', 'don_rested'), ('don_deck', 'don_deck'),
            ('frozen_don_count', 'frozen_don'),
            ('cant_play_from_hand_this_turn', 'cant_play_hand'),
            ('cannot_attack_leader_this_turn', 'cant_attack_leader'),
            ('cant_take_life_this_turn', 'cant_take_life'),
            ('cant_play_cost_gte', 'cant_play_cost_gte')):
        valores[base_nome + '_mine'] = _g(p, campo)
        valores[base_nome + '_opp'] = _g(opp, campo)
    valores['is_first_mine'] = 1.0 if getattr(p, 'is_first', False) else 0.0

    # ESTRUTURA NOMEADA (bloco 766, pedido do usuario). Antes isto era uma
    # lista POSICIONAL montada a mao, em paralelo a `FEATURE_NAMES` -- modo de
    # falha silencioso e grave: inserir uma feature no meio de uma lista e
    # esquecer da outra DESLOCA tudo (life vira hand, power vira don) e o
    # modelo treina em dado embaralhado SEM erro nenhum aparecer. Com a
    # estrutura, nome e valor viajam juntos e o desalinhamento e impossivel.
    #
    # A saida antecipada das 32 continua: producao nao pode pagar pelas
    # features ricas (`_com_efeito` consulta o banco por personagem) que ela
    # nao usa.
    base_vals = [
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
    por_nome = dict(zip(FEATURE_NAMES, base_vals))
    if nomes is None or list(nomes) == FEATURE_NAMES:
        return [por_nome[n] for n in FEATURE_NAMES]
    por_nome.update(valores)
    # Nome desconhecido vira 0.0 em vez de estourar: modelo antigo/novo nunca
    # derruba o motor por causa de feature (mesmo principio do `win_prob`,
    # que degrada pra None quando o bundle nao bate).
    return [float(por_nome.get(n, 0.0)) for n in nomes]


def fingerprint_estado(p, opp) -> dict:
    """Impressao digital RICA do estado -- diagnostico, nao producao.

    Existe para responder uma pergunta especifica (bloco 756): quando duas
    irmas da mesma decisao produzem o MESMO vetor de `state_features`, isso
    e porque a posicao e de fato identica (a linha convergiu, e a diferenca
    de desfecho e ruido de RNG), ou porque as 32 features -- que sao so
    contagens e agregados, sem NENHUMA identidade de carta -- achatam duas
    posicoes realmente diferentes?

    As duas respostas tem correcoes OPOSTAS, entao nao da pra supor.
    Nao e chamada em producao: so pelo seam `_cf_captura_fp`, que fica
    None por padrao.
    """
    def _cod(cards):
        return sorted(str(getattr(c, 'code', '?')) for c in cards)

    def _lado(x):
        chars = _chars(x)
        return {
            'mao': _cod(getattr(x, 'hand', []) or []),
            'campo': sorted(
                '%s|p=%s|r=%s|d=%s' % (
                    getattr(c, 'code', '?'),
                    getattr(c, 'power', 0),
                    int(bool(getattr(c, 'rested', False))),
                    len(getattr(c, 'attached_don', []) or []),
                ) for c in chars),
            'trash': _cod(getattr(x, 'trash', []) or []),
            'vida': _num(x.life_count),
            'n_deck': _num(lambda: len(x.deck)),
            'don_campo': _num(x.don_on_field),
            'don_disp': _num(lambda: getattr(x, 'don_available', 0)),
        }

    return {'eu': _lado(p), 'opp': _lado(opp)}


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


_WP_CACHE: dict = {}
_WP_STATS = {'hit': 0, 'miss': 0}


def limpar_cache_win_prob() -> None:
    """Zera o memo de `win_prob`. Chamar entre PARTIDAS, nao entre turnos --
    a chave e o vetor de features + o modelo, entao ela ja distingue estados
    diferentes; limpar so evita o dict crescer sem fim ao longo de um lote."""
    _WP_CACHE.clear()


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
    # Cada modelo diz QUAIS features ele quer (bloco 764). Sem isto, um
    # modelo treinado nas 49 ricas receberia as 32 basicas e cairia no
    # `check_dims` -- e, pior, dois modelos com visoes diferentes nao
    # poderiam duelar no mesmo processo, que e justamente o A/B a fazer.
    nomes = bundle.get('feature_names') if isinstance(bundle, dict) else None
    feats = state_features(p, opp, nomes=nomes)
    if not check_dims(bundle, len(feats)):
        return None
    # MEMO por vetor de features (bloco 766). `predict_proba` de UMA linha
    # custa 2,1ms -- caro e desproporcional (o mesmo modelo faz 0,88ms/linha
    # em lote). E medimos que **58% das linhas irmas convergem pro MESMO
    # estado** (bloco 756, 65/65 confirmados): estado igual => features iguais
    # => o modelo esta sendo consultado duas vezes pra dar a MESMA resposta.
    #
    # Funcao PURA de (features, modelo), entao nao ha risco de atribuir
    # resposta errada -- diferente de adiar a previsao pra fazer lote, que
    # exigiria reatribuir resultado por candidata e erraria em silencio.
    chave = (id(modelo), tuple(feats))
    hit = _WP_CACHE.get(chave)
    if hit is not None:
        _WP_STATS['hit'] += 1
        return hit
    try:
        v = float(modelo.predict_proba([feats])[0][1])
    except Exception:
        return None
    _WP_STATS['miss'] += 1
    _WP_CACHE[chave] = v
    return v
