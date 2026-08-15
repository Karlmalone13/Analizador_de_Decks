"""
optcg_engine/decision_engine.py
================================
Motor de simulação OPTCG — sistema unificado.

Baseado nas 34k linhas do Assembly-CSharp.dll v1.40a.

Estrutura:
    Card          — carta (estado em jogo)
    GameState     — estado de um jogador
    EffectExecutor — executa efeitos do card_effects_db.json (único ponto)
    DecisionEngine — IA de decisão situacional
    OPTCGMatch    — motor de partida (fases, combate, turnos)
    simular_matchup — pipeline de N partidas

Fluxo de efeitos (baseado no DoV3ActionStep das 34k linhas):
    _play_card() → EffectExecutor.execute(card, trigger='on_play', p, opp)
    _execute_attack() → EffectExecutor.execute(card, trigger='when_attacking', p, opp)
    on_ko → EffectExecutor.execute(card, trigger='on_ko', p, opp)
    your_turn → EffectExecutor.apply_your_turn_buffs(p, opp)
"""

import re
import json
import os
import random
import pandas as pd
from copy import deepcopy as _deepcopy

# ── evaluate_state v2 (item 1 do PLANO_AVALIACAO_E_BUSCA.md) ──────────────────
# Régua ÚNICA de avaliação de estado: genéricos + eixos derivados do perfil do
# deck (deck_profile). Entra como DROP-IN no fim do Turn Planner atrás do flag
# abaixo, pra medir A/B com baseline_metrics antes de virar padrão. Import
# GUARDADO: se deck_profile/deck_analyzer não estiverem no path, cai no
# fallback (só termos genéricos) sem quebrar o motor.
USE_EVAL_V2 = True    # LIGADA 13/07: validação rigorosa (MC=6, n=50, Imu-v2 vs
#                       opp-v1) confirmou ganho SEM regressão nos 3 matchups —
#                       winrate Krieg 0.38→0.40, Kid 0.34→0.36, Teach 0.88→0.96;
#                       dano e %líder sobem nos três. Pesos tunados em
#                       eval_weights.json (dmg 120→180, counter_hand 6→9). Item 1
#                       CONCLUÍDO. (Pesos são globais/Imu-tunados por ora; cache
#                       per-deck = pipeline self-service do item 5, ainda a fazer.)

# Amostras Monte Carlo do Turn Planner por decisão. 6 no jogo real; a tunagem
# (tune_weights.py) baixa pra 4 pra acelerar a BUSCA (a validação final volta
# a 6). Knob global — não muda a régua, só o custo da simulação.
PLANNER_MC_SAMPLES = 6

# Amostragem ADAPTATIVA do main_phase (offline: self-play/replay/calibração),
# quando USE_OPPONENT_RESPONSE_SEARCH=True. Antes disto (blocos 380/477): N
# FIXO=3 (samples_min==samples_max==batch_size, degenerava a amostragem
# adaptativa em 1 lote só, sem teste de significância -- mesmo mecanismo do
# caminho ao vivo, só sem a parte "sobe até o teto quando o gap não é
# confiável"). Achado 10/08 (usuário: "vale a pena melhorar a precisão, no
# menor tempo possível, mudar estratégia se for o caso"): ligar o MESMO
# early-stop estatístico (CRN pareado, `_select_action_via_search`) já
# calibrado no caminho ao vivo (SEARCH_SAMPLES_MIN/MAX/BATCH_DEFAULT em
# sim_bridge.py, piso=12/teto=24 -- generoso demais pro regime de THROUGHPUT
# do offline, que roda até 30 sub-decisões/turno vezes muitos turnos vezes
# muitas partidas de calibração). Escolhido piso=3 (mesmo custo do N fixo
# anterior quando a decisão já é clara) / teto=6 (mesmo valor já validado
# em 13/07 pro caso USE_OPPONENT_RESPONSE_SEARCH=False, PLANNER_MC_SAMPLES)
# / batch=3. Medido via `calibrate_offline_mc_samples_10_08.py` (script
# descartável, mesma convenção dos blocos 449/459/468, não commitado): 3
# matchups reais x 5 seeds x 2 rodadas (N fixo vs adaptativo) — custo extra
# de tempo total = **+7,2%** (68,6s -> 73,6s) pra ganhar a precisão extra
# exatamente nas decisões ambíguas onde 3 amostras não bastam (a maioria
# das decisões já é clara com 3 e para aí, custo igual a antes).
OFFLINE_MC_SAMPLES_MIN = 3
OFFLINE_MC_SAMPLES_MAX = 6
OFFLINE_MC_SAMPLES_BATCH = 3

# Modo experimental de MEDICAO (bloco 524, ideia do usuario apos o GATE
# nao funcionar: "dar um jeito de simular a heuristica centenas de
# vezes" -- em vez de inventar uma camada aproximada nova (a
# "calibragem dinamica" original, ja tentada e descartada nos blocos
# 513-523), reusa a busca REAL de sempre (`_select_action_via_search`,
# regra completa via `_apply_action`, ZERO duplicacao de motor) com
# piso/teto de amostras bem maiores. So pra self-play de MEDICAO
# (offline) -- NUNCA pra producao ao vivo sem medir custo separado
# (cada amostra real custa ~3,7ms, ver HANDOFF bloco 521 -- centenas
# de amostras por candidata pode levar segundos por decisao).
USE_DEEP_REAL_SEARCH = False
DEEP_REAL_SEARCH_SAMPLES_MIN = 100
DEEP_REAL_SEARCH_SAMPLES_MAX = 300
DEEP_REAL_SEARCH_SAMPLES_BATCH = 50

# Componente de counter em `_counter_stat_bonus` (rede de segurança na mão
# vs jogar a carta). Promovido de literal solto pra constante nomeada
# (28/07, bloco HANDOFF 390) -- achado real via `compare_vs_human.py` em
# 20 partidas distintas (não 1 log só): jogadores reais SEGURAM cartas de
# counter>=1000 quando a vida está crítica (<=2) em 69% dos casos onde o
# Turn Planner sugeria jogar essa carta como topo, mas o desconto atual
# (15 * multiplicador de vida) nunca chega perto dos scores reais (200-540)
# que essas cartas atingem -- na prática, não muda a decisão quase nunca.
# Ver TODO.md pra validação/calibração em andamento antes de mudar este
# valor.
COUNTER_STAT_VALUE_PER_1000 = 15

# Score-base de atacar o LIDER (vida normal, sem lethal), usado em
# score_attack_target. Extraido de literal solto (29/07, bloco HANDOFF 395
# -- pedido do usuario pra calibrar decisoes rumo ao % do vencedor real,
# depois de validar via self-play pareado nos 5 lideres com log real
# confiavel: Imu-B, Dracule.Mihawk-G, Portgas.D.Ace-RB, Jinbe-B,
# Jewelry.Bonney-G). Achado: com o valor antigo (100), o bot atacava o
# lider MENOS que o vencedor real em 4/5 lideres (ex: Bonney 59% vs 100%
# real) -- o baseline flat de 100 perdia facil pra `target.board_value()
# * 15` de qualquer personagem razoavel em campo, MESMO quando o
# vencedor real prefere ir na cara.
#
# Calibrado via self-play PAREADO (mesma seed/matchups, 5 lideres x 10
# partidas cada, decks reais de decklists_raw.csv) testando 100/175/250/
# 400/600: win rate agregado 36%/44%/46%/52%/36% -- pico claro em 400
# (%lider foi de 76,2% pra 87,2%, bem perto do real 84,1%; DON/ataque
# tambem caiu de 1,9 pra 1,8 como efeito colateral, sem precisar mexer
# nisso separado). 600 ja reverte (win rate cai pra 36%, igual ao valor
# original) -- 400 e o valor validado, nao um palpite.
ATTACK_LEADER_BASE_SCORE = 400

# Teto de custo pra bloquear INCONDICIONALMENTE com vida critica (<=2) em
# should_use_blocker. Ate 29/07 (bloco HANDOFF 395/396) essa regra
# bloqueava SEMPRE que houvesse um blocker disponivel, sem nenhum check
# de custo/beneficio (diferente de should_use_counter, que ja pesa
# pitch_cost_as_counter vs o valor da vida) -- achado real via self-play
# vs vencedores reais: bot bloqueia mais que o vencedor em ~1,5x (109
# "IA queria bloquear" vs 72 opostos).
#
# Calibrado via self-play PAREADO (mesma seed/matchups do bloco 395, 5
# lideres x 10 partidas cada) testando None/150/100/60: win rate
# agregado 52%/52%/46%/50%, taxa de bloqueio em vida<=2 11,9%/8,9%/
# 5,5%/~0%. 150 empata o win rate do baseline (None) SEM regredir,
# reduzindo o bloqueio incondicional de verdade -- 100 e 60 JA pioram o
# win rate (restritivo demais, board fica exposto). 150 e o pico, nao
# um palpite.
BLOCK_CRITICAL_LIFE_MAX_COST = 150

# Fator de escala sobre a tabela `valor_vida` de should_use_counter
# (terceira frente do pedido do usuario, bloco HANDOFF 397 -- mesma
# metodologia dos blocos 395/396). Self-play vs vencedores reais achou
# o bot counterando ~1,9x mais que o vencedor real (304 "IA queria
# counterar" vs 159 opostos, bloco 394) -- hipotese inicial era que
# reduzir a escala aproximaria do vencedor.
#
# Achado CONTRA a hipotese, via self-play PAREADO (mesma seed/matchups
# dos blocos 395/396): reduzir a escala (0.7/0.5/0.3) so PIOROU o win
# rate agregado (44%/42%/38%/38%, baseline 1.0=44%), mesmo reduzindo a
# taxa de counter de verdade (31,3%->22,4%) -- diferente do bloqueio
# (bloco 396), aqui o jogador real medio parece estar SUBCONTERANDO, nao
# o bot supercounterando. Testando pra CIMA em vez de baixo: 1.3=52%
# (pico), 1.6=42% (reverte). 1.3 bate o proprio baseline de 1.0,
# confirmando que a direcao certa era o oposto da hipotese inicial.
COUNTER_VALOR_VIDA_SCALE = 1.3

# Fracao do DON ocioso ("margem de pressao gratis") de fato anexada em
# don_needed_for_attack, alem do deficit base obrigatorio pra passar o
# alvo. 1.0 = comportamento original (usa TODO o DON livre disponivel
# como margem). Quarta frente da calibracao pedida pelo usuario (blocos
# 395-397): self-play vs vencedores reais achou o bot anexando mais DON
# por ataque que o vencedor real em TODOS os 5 lideres com log confiavel
# (bloco 394) -- essa margem "gratis" e o unico lugar no calculo de DON
# por ataque com um numero solto pra reduzir (o resto da funcao e
# deficit OBRIGATORIO, nao ha o que cortar ali sem quebrar ataques que
# precisam do DON pra passar).
#
# Teste pareado (8 valores, 5 lideres/decks/seed=7, 50 partidas/valor,
# bloco HANDOFF 398, 29/07): win rate ficou ruidoso com esse tamanho de
# amostra (40%-60% sem tendencia clara) -- decisao pelo alvo real, nao
# pelo pico de win rate. DON/ataque agregado dos vencedores reais
# (5 lideres, logs/index.json) = 129/132 = 0.977. **0.7** da DON/ataque
# agregado = 1.128 (o mais perto do alvo real -- diff 0.15, o 2o melhor
# foi 0.4 com diff 0.31) SEM regredir o win rate (50% vs 52% baseline,
# dentro do ruido). Confirmado por um cross-check independente: nos SEUS
# jogos reais de Imu, vitorias tem DON/ataque=1.31 vs derrotas=0.38 --
# valores baixos (0.3 e abaixo) reproduzem o padrao de DERROTA, nao de
# vitoria, entao NAO foram escolhidos apesar do pico de win rate ruidoso
# em 0.3 (60%, cercado por vizinhos piores -- sinal de ruido, nao
# tendencia real).
ATTACK_MARGIN_DON_FRACTION = 0.7

# Score-base de _score_activate_main pra acao `give_don` (DON RESTADO
# -- so ajuda a partir do PROXIMO turno, distinto de add_don/
# set_don_active, que dao DON ATIVO imediato e tem categoria propria,
# base=90). Achado 29/07 (investigacao de activate:main por lider,
# bloco 399): `give_don` nao tinha categoria propria em
# _score_activate_main -- caia no fallback generico (60, sem nenhum
# desconto por ser DON delayed). Isso e usado por 49 cartas no banco
# (TODAS com rested=True -- nao existe give_don com DON ativo),
# incluindo o proprio lider Jinbe-B (OP14-040), que e o UNICO caso sem
# once_per_turn no banco -- sem esse cap E sem desconto proprio no
# score, o bot ativava em TODO turno proprio sem excecao (self-play:
# 4,9/jogo) vs vencedores reais em 2,0/jogo.
#
# Teste pareado (10 valores, 5 lideres/decks/seed=7, 10 partidas/valor):
# confirmado que NENHUM dos outros 4 lideres do pool tem carta com
# give_don no deck (0 cartas) -- so Jinbe-B e realmente afetado pela
# constante, entao a oscilacao de win rate dos outros 4 e ruido puro,
# nao efeito real. Olhando so Jinbe-B: ativacoes/jogo 60->5,1,
# 45->5,2, 30->5,0, 15->4,8, 0->3,9, -5->3,9, -8->2,8, **-10->2,2**
# (mais perto do alvo real 2,0, diff 0,2), -12->1,2, -15->0,5
# (undershoot, mesmo tipo de risco de "corrigir demais" ja visto em
# ATTACK_MARGIN_DON_FRACTION=0.3). **-10** tambem da o MELHOR win rate
# de Jinbe-B entre os valores proximos do alvo (60% vs 30% no
# baseline=60) -- ganha nos dois eixos, sem precisar escolher entre
# eles. Valor final aplicado.
GIVE_DON_RESTED_BASE_SCORE = -10

# Bonus somado a _score_play_action quando a carta "habilita ataque"
# (K.O./remocao/buff/rush/draw/busca/rest_opponent/when_attacking/
# activate_main) -- prioriza jogar ANTES de atacar no mesmo turno pra
# ativar o efeito a tempo. Promovido de literal `+60` inline pra
# constante nomeada (06/08), mesmo padrao de ATTACK_LEADER_BASE_SCORE/
# BLOCK_CRITICAL_LIFE_MAX_COST etc.
#
# Achado do bloco 449 (05/08): um teste pareado com politica GULOSA
# simplificada (nao o Turn Planner real -- substituia main_phase inteiro
# por "sempre jogar habilitador antes do 1o ataque, sem competir por
# score") mostrou efeito FORTE mas NAO uniforme por deck -- Enel se
# beneficia muito (+25-32pp de win rate em 3 matchups), Nami/Ace pioram
# bastante contra Mihawk (-21pp/-17pp), Imu fica perto de neutro. Esse
# teste NAO calibrou a constante real (bypassava o score, nao testava
# valores diferentes de bonus).
#
# Calibracao real (06/08, self-play pareado com o MOTOR de producao via
# `OPTCGMatch`/`ReplayMatch`, mesma metodologia de `gauntlet_matchup.py`
# -- 4 lideres do achado do bloco 449, cada um vs Mihawk + Enel tambem
# vs Nami, N=15 seeds/matchup, testando 0/60/120):
#
#   bonus   EnelvMihawk EnelvNami  NamivMihawk AcevMihawk ImuvMihawk agregado
#     0       73.3%      66.7%      26.7%      40.0%      20.0%      45.3%
#    60       46.7%      93.3%      20.0%       6.7%      13.3%      36.0%
#   120       60.0%      73.3%       6.7%      33.3%      26.7%      40.0%
#
# **Achado CONFIRMA o padrao do bloco 449 na constante REAL, nao so na
# politica simplificada**: nenhum valor unico e vitoria limpa em todos os
# decks. Nami vs Mihawk piora MONOTONICAMENTE com bonus maior (26.7% ->
# 20.0% -> 6.7%, o sinal mais limpo do sweep, mesma direcao do achado
# original) -- Enel vs Nami prefere fortemente o valor atual (93.3% em
# 60, contra 66.7-73.3% nos extremos). N=15/celula e RUIDOSO (cada
# partida vale ~6.7pp) -- Enel vs Mihawk e Ace vs Mihawk oscilam sem
# padrao monotonico limpo, provavelmente ruido de amostra pequena, nao
# tendencia real. **Decisao: MANTIDO em 60** -- nao existe candidato que
# vença o valor atual com confianca (o agregado favorece 0, mas isso so
# reflete a queda profunda de Enel vs Nami em 0/120, nao uma vitoria
# real; ver mesmo principio de "nao escolher pelo pico de win rate
# ruidoso" dos blocos 396/398). Amostra maior (N maior, mais seeds) seria
# necessaria pra uma calibracao com confianca de verdade -- fica
# registrado como pendencia futura, nao um valor final definitivo.
#
# Amostra maior (07/08, N=50/celula em vez de 15, mesmos 5 matchups/3
# valores, paralelizado em 4 workers -- 750 partidas): RESOLVE o ruido
# acima. O agregado INVERTE em relacao ao N=15 (que favorecia 0): agora
# 60 e o MELHOR valor agregado (41.6% vs 39.6% em 120 vs 36.0% em 0,
# N=250/valor). Ganho de confianca vem de EnelvMihawk, que a N=15 parecia
# favorecer fortemente 0 (73.3%) mas a N=50 se revela o OPOSTO -- 0 e o
# PIOR valor (26.0%, contra 42.0% empatado em 60/120), confirmando que o
# N=15 original era mesmo ruido de amostra pequena, nao sinal real. Com
# N=50, 60 fica empatado-melhor ou melhor isolado em 4 dos 5 matchups
# (EnelvMihawk empatado c/120, EnelvNami so 2pp atras de 120, NamivMihawk
# melhor isolado, ImuvMihawk empatado c/0) -- so perde claramente pra 0
# em AceMihawk (30% vs 32%, dentro do ruido de N=50, SE~7pp). **Decisao
# FINAL: CONFIRMADO em 60**, agora com amostra suficiente pra confiar na
# direcao do resultado (nao so "nenhum candidato vence com confianca" do
# bloco 459 -- aqui 60 efetivamente vence o agregado e a maioria dos
# matchups individuais). Fecha a pendencia de amostra maior registrada
# no paragrafo acima.
HABILITA_ATAQUE_BONUS = 60

# ── PREVENT_COMBO (achado 07/07, HANDOFF blocos 99-100/287, TODO "consciência
# de combos estratégicos do oponente") — extraídos de literais embutidos pra
# constantes de módulo (mesmo padrão de HABILITA_ATAQUE_BONUS acima), pedido
# do usuário 10/08/2026 (bloco 491): calibração formal via self-play pareado,
# mesmo protocolo maximin do fix de LETHAL (HANDOFF bloco 285) -- precisa
# poder trocar o valor sem editar 3 pontos espalhados do arquivo.
# magnitude>=N de opp_combo_threat() pra `analysis_priority()` retornar
# PREVENT_COMBO (ver GameAnalyzer.opp_combo_threat/analysis_priority).
PREVENT_COMBO_MAGNITUDE_THRESHOLD = 2
# Bonus pra carta defensiva (blocker/counter) em postura PREVENT_COMBO --
# "guardar recurso pro turno da virada do oponente" (_score_play_action).
PREVENT_COMBO_DEFENSIVE_CARD_BONUS = 80
# Bonus pra ataque de lider em postura PREVENT_COMBO -- "correr o clock
# antes da virada" (loop de scoring de ataque ao lider).
PREVENT_COMBO_LEADER_ATTACK_BONUS = 150

# ── Selecao de candidatas pra busca Monte Carlo (unificacao 26/07) ────────────
# Promovidos de variavel local do main_phase pra constante de modulo --
# `_select_search_candidates`/`_select_action_via_search` sao agora a FONTE
# UNICA usada tanto pelo Turn Planner offline (main_phase) quanto pelo
# caminho AO VIVO (sim_bridge.choose_action). Pedido explicito do usuario
# (26/07): "tem que ser o mesmo nos dois" -- antes, o caminho ao vivo tinha
# seu proprio laco de selecao/amostragem sem a janela de score, sem a
# diversidade de REMOVE_THREAT e SEM a guarda _is_unsafe_zero_life_leader_attack
# (que so existia no offline). So o TOP_K (quantas candidatas simular) e o
# piso/teto de amostras continuam variando por chamador -- isso e orcamento
# de tempo (recurso), nao politica de decisao.
SEARCH_MIN_CANDIDATES = 3
SEARCH_SCORE_WINDOW = 180

# ── camada barata / "calibragem dinamica" (bloco 508/509, escala bloco 514) ──
# Desenho acordado com o usuario 11/08: em vez de resolver o efeito de
# verdade (caro, precisa do motor de regras completo), `_cheap_rollout_value`
# usa SO as flags ja pre-parseadas (get_card_flags, mesma fonte que
# avaliar_carta ja usa) pra aproximar o resultado de uma acao -- muitas
# amostras rapidas, nao um substituto da busca real. O sinal alimenta
# `_select_search_candidates` como um segundo criterio (alem do score
# estatico de sempre) pra ALARGAR o shortlist que entra na busca cara --
# nunca substitui, nunca encolhe o que o score estatico ja garantia. A
# busca cara (heuristica de sempre, sem nenhum peso mexido) VALIDA/ESCOLHE
# entre as candidatas alargadas -- essa e a "fase fina" completa, nao
# precisa de um mecanismo separado que ajuste peso (tentativa registrada
# e descartada no bloco 513/514, ver HANDOFF: usuario esclareceu que a
# adaptacao por deck vem de QUAIS candidatas entram na busca, ja
# deck-agnostico via get_card_flags -- nao de mexer na regua fixa).
# Validado por self-play (bloco 510) antes de ligar -- ver USE_CHEAP_
# LAYER_SHORTLIST abaixo pro resultado. Extensao pro caminho AO VIVO
# (`sim_bridge.choose_action`) feita no bloco 511 -- reusa a MESMA flag,
# sem flag separada (a decisao "camada barata ligada ou nao" e unica
# pros dois chamadores).
# ESCALA (bloco 514/517/518): usuario pediu subir de 40 pra milhares
# ("igual ao NarutoSim, 8000 ou 1000x"). Primeira tentativa (bloco 517)
# testou CHEAP_LAYER_SAMPLES=3000 vs 40 e deu resultado NEGATIVO (3 de
# 4 matchups pioraram) -- investigado a fundo (bloco 518) e achado um
# CONFOUND real, nao "mais amostra e ruim de verdade": `_cheap_rollout_
# value`/`_compute_cheap_values` usavam `rng or random` (o MODULO
# global `random`, mesmo stream que `random.shuffle(p.deck)`/compras de
# carta usam em todo o motor). Sample count DIFERENTE consome uma
# quantidade DIFERENTE de numeros aleatorios do stream compartilhado a
# cada decisao, deslocando TODOS os sorteios seguintes da partida (mao
# vira outra, mesmo com a MESMA seed) -- a comparacao 40-vs-3000 nao
# estava isolando "qualidade da amostra", estava comparando partidas
# com maos DIFERENTES. Corrigido com `_CHEAP_LAYER_RNG` (instancia
# `random.Random` PROPRIA, isolada do stream do jogo, ver definicao
# abaixo). Valor ainda EM 40 (ja validado) ate re-medir 40-vs-3000 com
# o confound removido -- ver HANDOFF bloco 518 pro resultado real.
CHEAP_LAYER_SAMPLES = 40
CHEAP_LAYER_EXTRA_CANDIDATES = 3
# Profundidade de SEQUENCIA da camada barata (bloco 521, EXCECAO
# EXPLICITA a REGRA_SEM_DUPLICACAO autorizada pelo usuario 13/08 --
# ver HANDOFF bloco 521 pro registro completo do motivo e do escopo).
# `_cheap_playout_deltas` encadeia ate esse numero de jogadas 'play'
# fictícias (a 1a + N-1 seguintes, gulosas, so mao->campo, sem
# resolver regra real) -- da profundidade de verdade pra camada
# barata, que antes so olhava 1 acao isolada (por isso mais amostra
# nunca ajudava, nao tinha nada pra explorar). 4 = tamanho tipico de
# "quantas cartas cabem numa curva de turno" (mesmo MAX_ACOES/TOP_K
# usados no resto do motor como escala de referencia).
CHEAP_LAYER_PLAYOUT_STEPS = 4
# RNG ISOLADO pra camada barata (bloco 518) -- NUNCA usar o modulo
# `random` global aqui (contaminaria o stream do jogo, ver comentario
# acima). Seed fixa: a camada barata so estima uma MEDIA/tendencia, nao
# toma decisao nenhuma sozinha -- nao precisa variar entre partidas pra
# ser correta, so precisa ser reprodutivel e nao vazar entropia pro
# resto do motor.
_CHEAP_LAYER_RNG = random.Random(20260813)
# Knob global, mesmo padrao do USE_EVAL_V2/USE_OPPONENT_RESPONSE_SEARCH.
# LIGADO 11/08 (bloco 510) apos comparacao controlada (self-play, N=30,
# roster deconfundido Imu_v_{Mihawk,Ace,Lucy,Luffy-Y}, seeds pareadas):
# winrate melhorou nos 4 matchups (+3,3pp/+16,7pp/+6,7pp/+16,7pp,
# maximin=+0,033, sem regredir nenhum) ao custo de +60,6% de tempo por
# partida -- aceitavel pro offline (self-play/calibracao, sem orcamento
# de tempo real). Estendido pro caminho ao vivo no bloco 511 (timeout
# interno 3.0s->5.0s pra acomodar, folga real medida contra o limite
# fisico de 10s do plugin C#).
# DESLIGADO DE NOVO no bloco 526 -- pedido direto do usuario apos jogar
# ao vivo e observar o bot jogando PIOR que antes (sinal real de
# partida, mais forte que qualquer medicao de self-play desta sessao).
# Volta ao estado de decisao de ANTES do bloco 508 inteiro (heuristica
# pura, sem alargamento de shortlist nenhum) -- os mecanismos ficam no
# codigo (documentados/testados) mas NADA deles roda por padrao ate
# uma nova validacao ao vivo justificar religar. Ver HANDOFF bloco 526.
USE_CHEAP_LAYER_SHORTLIST = False
# Modo experimental de ABLACAO (bloco 519/520, pedido do usuario: medir
# separadamente "heuristica sozinha" x "heuristica+simulacao" x "so
# simulacao"). Quando True, `main_phase` aplica a acao de maior
# `cheap_value` DIRETO, sem NENHUMA busca cara -- so pra self-play de
# MEDICAO comparativa, NUNCA pra producao (offline OU ao vivo). Nunca
# ligar em `sim_bridge.py`.
CHEAP_LAYER_DECIDES_ALONE = False

# Modo "GATE" (bloco 522, pedido direto do usuario apos o achado do
# bloco 521: alargar SEMPRE o shortlist da busca cara com um sinal
# barato mais confiante sobrecarrega o orcamento apertado dela em vez
# de ajudar -- maximin=-0,050 medido no teste de producao). Design
# simplificado: roda a simulacao barata, e SO pula a busca cara
# (aplica a acao de maior cheap_value DIRETO) quando o resultado ja e
# CONFIANTE (gap >= CHEAP_LAYER_GATE_THRESHOLD entre a 1a e a 2a
# candidata) -- senao, cai no fluxo de sempre (score estatico + busca
# cara), SEM alargamento algum (mutuamente exclusivo com USE_CHEAP_
# LAYER_SHORTLIST). OFF por padrao ate validar com o mesmo protocolo
# multi-ancora de sempre.
USE_CHEAP_LAYER_GATE = False
# Limiar de confianca do gate -- mesma ordem de grandeza do `score`
# imediato de `_generate_and_score_actions` (a camada barata usa os
# MESMOS termos de EVAL_WEIGHTS, ver `_cheap_rollout_value`). Prior
# nao calibrado ainda -- ver HANDOFF bloco 522 pro processo de escolha.
CHEAP_LAYER_GATE_THRESHOLD = 50.0

# Calibragem dinamica pro `don_field` (bloco 530, pedido do usuario --
# "vamos fazer para o motor inteiro"): escala o valor de DON parado no
# campo pela curva do PROPRIO deck (GameAnalyzer.don_field_curve_scale,
# reusa deck_profile_type() ja existente -- analitico, ZERO self-play
# novo, mesma familia de leader_plan_alignment/_leader_ability_
# centrality). Diferente de leader_plan_alignment (prior 0.0, inerte):
# don_field JA tem peso ativo em producao, entao este flag muda
# comportamento AO VIVO pra QUALQUER deck aggressive/control assim que
# ligado -- OFF por padrao ate validacao real (nao so self-play, ver
# achado do bloco 528/529 de que self-play em N pequeno e ruidoso
# demais pra validar sozinho).
USE_DON_FIELD_CURVE_SCALE = False

# ── busca prof.2 / resposta do oponente (item 3 do PLANO_AVALIACAO_E_BUSCA.md) ─
# Depois de simular MINHA linha ate o fim do turno, simula o TURNO INTEIRO de
# resposta do oponente (proprio engine, modo GULOSO -- ver _play_turn_greedy,
# sem aninhar main_phase/Monte Carlo: evitaria explosao K x MC x K x MC) antes
# de avaliar. E o que torna visivel "ataquei seco -> ele countera barato e
# devolve" vs "anexei DON -> passa/drena counter", que a foto no fim do MEU
# turno sozinha nao capta. Knob global, mesmo padrao do USE_EVAL_V2 -- liga por
# padrao pro simulador OFFLINE (self-play/gauntlet/tunagem), onde o
# OpponentModel tem decklist REAL dos dois lados. NAO esta fiado no caminho AO
# VIVO ainda (choose_action/sim_bridge): o /decide hoje nao chama
# _simulate_sequence_once nenhuma vez (decide so pelo score imediato de
# _generate_and_score_actions) porque o OPTCGMatch ao vivo (server.py
# _get_match) usa um deck PLACEHOLDER pros dois lados (so pra ter a
# maquinaria) -- ligar a busca ali com esse deck errado geraria previsao de
# mao/vida do oponente LIXO, podendo piorar decisao ao vivo. Fio pendente
# documentado no TODO/HANDOFF: precisa de decklist REAL do oponente
# server-side (registro por partida ou lookup leader->arquivo .deck) antes de
# vale a pena religar ao vivo.
USE_OPPONENT_RESPONSE_SEARCH = True

# ── fix DON de lethal (achado 19/07, diag_lethal_don_alloc.py) ────────────────
# can_lethal_this_turn() certifica lethal alocando LIVREMENTE todo o DON entre
# os ataques (busca sem restricao, ve _lethal_search). Mas a execucao real
# (_don_livre_for_plan) reservava DON pro "resto do plano do turno" mesmo
# quando o lethal certificado ja tornava esse resto irrelevante -- medido em
# 3 partidas reais: 82% (1165/1413) dos momentos com lethal certificado
# tinham a alocacao REAL de DON menor que a certificada em pelo menos 1
# atacante. Knob global, mesmo padrao de USE_EVAL_V2/USE_OPPONENT_RESPONSE_
# SEARCH -- liga por padrao, permite desligar pra comparar A/B rapido sem
# reverter codigo enquanto a validacao de gauntlet nao fecha.
FIX_LETHAL_DON_ALLOCATION = True
try:
    from deck_profile import build_profile_from_codes as _build_profile_from_codes
except Exception:
    _build_profile_from_codes = None

# Pesos da evaluate_state_v2 — VETOR TUNÁVEL (item 5). O otimizador
# (tune_weights.py) varia estes valores por self-play e escreve o vencedor em
# eval_weights.json; aqui carregamos esse cache se existir. Defaults = os
# priors medidos em 13/07 (que regridem Krieg — por isso a tunagem).
EVAL_WEIGHTS = {
    'dmg': 120.0, 'life_mult': 1.0, 'board_mine': 1.0, 'board_opp': 0.8,
    'opp_blocker': 25.0, 'hand_first': 8.0, 'hand_extra': 3.0,
    'counter_hand': 6.0, 'don_field': 4.0, 'coverage': 7.0,
    'ax_trash': 0.05, 'ax_reanim': 12.0, 'ax_inversion': 0.5,
    # win-con JOGÁVEL (peça-motor na mão + fuel no trash + DON pro custo):
    # "arma carregada". Prior — a tunagem por self-play (item 5) ajusta.
    'wincon_ready': 20.0,
    # sobrevivencia ciente do plano: com win-con de combo caro ainda nao
    # disparavel E vida baixa (risco real de morrer antes), premio por ponto
    # de panico (vida<=3). Prior — tunagem (item 5) ajusta.
    'survival_premium': 25.0,
    # ameaça de virada por reanimação em massa do TRASH do oponente (achado
    # 07/07, ver opp_combo_threat/PREVENT_COMBO). Penalidade sobre o
    # threat_power estimado do estado avaliado -- linhas que reduzem o
    # combustível qualificado dele (ou o custo de ativar) recomputam menor
    # aqui, então a busca já prefere isso sem precisar de regra hardcoded.
    # Escala parecida com board_opp (mesma unidade: soma de board_value()).
    'opp_combo_threat': 0.8,
    # FASE B do plano do Turn Planner (usuario, 24/07: "pensar a frente").
    # 'wincon_ready' acima ja cobre "arma carregada" pro eixo bottleneck
    # (reanimacao) do PERFIL do deck -- generico so dentro desse padrao
    # especifico. Este termo e mais amplo: QUALQUER carta forte na mao que
    # ainda nao cabe no DON de agora, mas cabe no DON projetado do PROXIMO
    # turno (sem simular o turno de verdade -- so a projecao de ramp).
    #
    # Split em 2 pesos (achado 11/08, bloco 495): o antigo 'next_turn_
    # readiness' unico multiplicava DOIS sinais diferentes pelo MESMO
    # numero -- o ganho que EU tenho esperando o proximo turno (sinal
    # positivo, 'self') e a ameaca de ataque forte que o OPONENTE tera no
    # turno dele (sinal negativo, 'opp_threat'). A calibracao pareada do
    # bloco 494 zerou o combinado (0.6 -> 0.0) porque um dos dois estava
    # atrapalhando mais que o outro ajudava -- zerar os dois juntos pode
    # ter descartado sinal bom junto com o ruim. Cada um agora e tunavel
    # independente (`tune_weights.py._TUNABLE`). Prior — tunagem por
    # self-play ajusta, mesma convencao dos outros.
    'next_turn_readiness_self': 0.0,
    'next_turn_readiness_opp_threat': 0.0,
    # Alinhamento com o plano do PROPRIO lider (pedido do usuario 14/08,
    # bloco 526/527 -- generaliza wincon_ready pra QUALQUER lider com
    # [Activate: Main], nao so o eixo bottleneck do perfil do deck). Ver
    # GameAnalyzer.leader_plan_alignment. Prior 0.0 -- SEM efeito ate
    # calibracao isolada (multi-ancora, nao so 1 deck) validar um valor.
    'leader_plan_alignment': 0.0,
}
try:
    _wpath = os.path.join(os.path.dirname(__file__), '..', 'eval_weights.json')
    if os.path.exists(_wpath):
        with open(_wpath, encoding='utf-8') as _f:
            # ignora _meta (camada de confiança: procedência, não é peso)
            EVAL_WEIGHTS.update({k: v for k, v in json.load(_f).items()
                                 if k != '_meta'})
except Exception:
    pass


class _SimDeck(list):
    """Deck lazy para simulacao do Turn Planner: contem referencias rasas de
    Card (mesmos objetos do deck real), mas faz deepcopy sob demanda quando
    uma carta e REMOVIDA (pop). Garante que mutacoes aplicadas durante a
    simulacao (just_played, power_buff, etc.) nao contaminem o estado real.
    Insercoes (insert/append) aceitam cartas ja copiadas -- sem wrapper extra.
    Usado em _simulate_sequence_once para evitar deepcopiar ~82 Cards de uma
    vez, economizando ~0.5-0.7ms por chamada sem risco de corrupcao."""

    def pop(self, index=-1):
        return _deepcopy(list.pop(self, index))

    def __deepcopy__(self, memo):
        # Se o proprio _SimDeck for deepcopiado (improvavel no fluxo normal),
        # retorna lista normal -- evita recursao.
        return list(self)
from optcg_engine.opponent_model import OpponentModel
from optcg_engine.deck_census import deck_census
from dataclasses import dataclass, field
from typing import Callable, List, Optional
from copy import deepcopy


SIMULATED_WIN_SCORE = 50000.0


# ===========================================================================
# Carrega o banco de efeitos
# ===========================================================================

_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'card_effects_db.json')
_EFFECTS_DB: dict = {}
_EFFECTS_ENRICHED_CACHE: dict = {}

_ANALYSIS_PATH = os.path.join(os.path.dirname(__file__), '..', 'card_analysis_db.json')
_ANALYSIS_DB: dict = {}

_HUMAN_PATTERNS_PATH = os.path.join(os.path.dirname(__file__), '..', 'human_patterns.json')
_HUMAN_PATTERN_BONUS_BY_LEADER: dict = {}
_HUMAN_DEFENSE_BY_LEADER: dict = {}
_HUMAN_PATTERN_MIN_SUPPORT = 2
_HUMAN_PATTERN_MAX_BONUS = 30.0

def _load_effects_db():
    global _EFFECTS_DB
    if _EFFECTS_DB:
        return
    try:
        with open(_DB_PATH, 'r', encoding='utf-8') as f:
            _EFFECTS_DB = json.load(f)
    except FileNotFoundError:
        pass

_load_effects_db()


def _load_human_patterns():
    """Carrega sinais leves de pilotagem humana extraidos dos logs reais."""
    global _HUMAN_PATTERN_BONUS_BY_LEADER, _HUMAN_DEFENSE_BY_LEADER
    if _HUMAN_PATTERN_BONUS_BY_LEADER:
        return
    try:
        with open(_HUMAN_PATTERNS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        _HUMAN_PATTERN_BONUS_BY_LEADER = {}
        return

    by_leader: dict = {}
    defense_by_leader: dict = {}
    for row in data.get('heuristic_candidates', []):
        count = int(row.get('count') or 0)
        if count < _HUMAN_PATTERN_MIN_SUPPORT:
            continue
        leader = row.get('leader') or ''
        pattern = row.get('pattern') or ''
        if not leader or not pattern:
            continue
        leader_bonus = by_leader.setdefault(leader.split('|', 1)[0], {})
        for token in pattern.split(' > '):
            if ':' not in token:
                continue
            kind, code = token.split(':', 1)
            if kind not in ('play', 'activate', 'attack'):
                continue
            key = (kind, code)
            leader_bonus[key] = min(
                _HUMAN_PATTERN_MAX_BONUS,
                leader_bonus.get(key, 0.0) + min(4.0 + count * 2.0, 12.0),
            )
    for leader, rows in data.get('by_defender_response', {}).items():
        leader_code = leader.split('|', 1)[0]
        defense = defense_by_leader.setdefault(leader_code, {'counter': 0, 'blocker': 0})
        for row in rows:
            pattern = row.get('pattern') or ''
            count = int(row.get('count') or 0)
            if pattern.startswith('counter:'):
                defense['counter'] += count
            elif pattern.startswith('blocker:'):
                defense['blocker'] += count
    _HUMAN_PATTERN_BONUS_BY_LEADER = by_leader
    _HUMAN_DEFENSE_BY_LEADER = defense_by_leader


def _load_analysis_db():
    global _ANALYSIS_DB
    if _ANALYSIS_DB:
        return
    try:
        with open(_ANALYSIS_PATH, 'r', encoding='utf-8') as f:
            _ANALYSIS_DB = json.load(f)
    except FileNotFoundError:
        pass

_load_analysis_db()


def get_card_effects(code: str) -> dict:
    """Retorna os efeitos de uma carta pelo código."""
    return _EFFECTS_DB.get(code, {}).get('effects', {})


def _quoted_types_before_play_turn_attack(text: str) -> list[str]:
    marker = 'can attack characters on the turn in which it is played'
    low = (text or '').lower()
    idx = low.find(marker)
    if idx < 0:
        return []
    prefix = text[:idx]
    quoted = re.findall(r'["{]([^"}]+)["}]', prefix)
    out = []
    seen = set()
    for q in quoted:
        q = q.strip()
        key = q.lower()
        if q and key not in seen:
            out.append(q)
            seen.add(key)
    return out


def _enrich_effects_from_analysis_text(code: str, effects: dict) -> dict:
    """
    Corrige lacunas do card_effects_db usando texto ja presente no
    card_analysis_db. Caso real: OP11-031 Jinbe tinha Activate Main no texto,
    mas o effects_db so continha o On Play.
    """
    text = str(_ANALYSIS_DB.get(code, {}).get('text', '') or '')
    low = text.lower()
    if 'activate: main' in low and 'can attack characters on the turn in which it is played' in low:
        am = effects.setdefault('activate_main', {'steps': [], 'once_per_turn': True})
        am.setdefault('steps', [])
        has_step = any(s.get('action') == 'select_grant_can_attack_active_turn'
                       and s.get('allow_played_this_turn')
                       for s in am['steps'])
        if not has_step:
            step = {
                'action': 'select_grant_can_attack_active_turn',
                'allow_played_this_turn': True,
            }
            types = _quoted_types_before_play_turn_attack(text)
            if types:
                step['filter_types'] = types
            am['steps'].append(step)
        if 'may rest this character' in low:
            costs = am.setdefault('costs', [])
            if not any(c.get('type') == 'rest_self' for c in costs):
                costs.append({'type': 'rest_self'})
    return effects


def get_card_game_rules(code: str) -> list[dict]:
    """Regras estruturadas de construcao/setup/identidade da carta."""
    return get_card_effects(code).get('game_rules', {}).get('rules', [])


def get_card_effects(code: str) -> dict:
    """Retorna os efeitos de uma carta pelo codigo."""
    if code in _EFFECTS_ENRICHED_CACHE:
        return _EFFECTS_ENRICHED_CACHE[code]
    effects = deepcopy(_EFFECTS_DB.get(code, {}).get('effects', {}))
    effects = _enrich_effects_from_analysis_text(code, effects)
    _EFFECTS_ENRICHED_CACHE[code] = effects
    return effects


def effective_counter(card: 'Card', owner: 'GameState') -> int:
    """
    Counter efetivo de uma carta NA MAO do dono, aplicando estaticas tipo
    "The counter of all of your Character cards with N power in your
    hand becomes +M" (achado 17/07, OP16-118, unica carta no banco --
    mecanica nova de modificar o Counter impresso enquanto na mao, nao um
    buff_power/buff_cost de campo). Escopo deliberadamente estreito: so
    consumido nos pontos DECISIVOS de "vale usar como Counter"
    (counter_in_hand/escolha de qual carta jogar como counter), nao em
    toda heuristica secundaria de scoring que le card.counter direto.
    """
    base = card.counter
    for fonte in [owner.leader] + list(owner.field_chars):
        fpassive = get_card_effects(fonte.code).get('passive', {})
        for s in fpassive.get('steps', []):
            if (s.get('action') == 'set_hand_counter_by_power'
                    and card.power == s.get('power_eq')):
                return s.get('to_value', base)
            # "All Character cards in your hand without a Counter have a
            # +N Counter" (achado 05/08, OP17-063 Kaido LIDER) -- MASSA,
            # qualquer Character da mao com counter impresso 0.
            if (s.get('action') == 'buff_hand_counter_no_counter'
                    and card.card_type == 'CHARACTER' and base == 0):
                return base + s.get('amount', 0)
    # "If you only have Characters without a Counter, this card in your
    # hand has a +N Counter" (achado 05/08, OP17-118 Rocks.D.Xebec) --
    # SELF, condicionado a NENHUM OUTRO Character da mao ter counter
    # impresso (usa `.counter` cru dos outros, nao effective_counter, pra
    # nao recursar).
    own_passive = get_card_effects(card.code).get('passive', {})
    for s in own_passive.get('steps', []):
        if s.get('action') == 'buff_own_hand_counter_if_no_others' and base == 0:
            outros = [c for c in owner.hand if c is not card and c.card_type == 'CHARACTER']
            if all(c.counter == 0 for c in outros):
                return base + s.get('amount', 0)
    return base


def get_card_flags(code: str) -> dict:
    """
    Retorna as flags estruturadas de classificação da carta (card_analysis_db):
    kos, is_removal, is_blocker, is_searcher, draws, bounces, rests_opponent,
    power_buff, gives_don, gains_life, has_trigger, etc. Fonte única de
    classificação de efeito -- preferir SEMPRE sobre substring no texto cru.
    Retorna dict vazio se a carta não está no banco (degrada sem quebrar).
    """
    return _ANALYSIS_DB.get(code, {})


def compute_game_plan_from_cards(cards: list) -> dict:
    """
    Nucleo puro de compute_game_plan: deriva trash_target/win_con_code/
    don_target de uma lista de Card (nao GameState). Extraido 14/07 pra ser
    compartilhado por `compute_game_plan(p)` (zonas REVELADAS -- muda
    conforme a partida progride, so sabe o que ja viu) e o "plano completo"
    calculado UMA VEZ a partir do deck INTEIRO conhecido (pedido do usuario
    14/07: o bot deve saber arquetipo/combo do proprio deck como um jogador
    humano sabe, nao so o que ja comprou -- ver full_deck_plan_for).

    - trash_target: maior `trash_gte` declarado em `conditions` de
      qualquer carta do deck (ex: Imu — 5 Celestial Dragons com "7+ no
      trash = imune a remoção"). 0 se o deck não tem esse padrão.
    - win_con_code / don_target: carta com maior valor de reanimação via
      `play_from_trash` no próprio `activate_main` (ex: Five Elders,
      reanima até 5). don_target = custo dela. None se o deck não tem
      combo desse tipo.
    """
    trash_gte_contagem: dict[int, int] = {}
    win_con_code = None
    win_con_value = 0
    win_con_cost = None
    vistos = set()
    for c in cards:
        if c.code in vistos:
            continue
        vistos.add(c.code)
        effects = get_card_effects(c.code)
        for trig_data in effects.values():
            conds = trig_data.get('conditions', {}) if isinstance(trig_data, dict) else {}
            if 'trash_gte' in conds:
                v = conds['trash_gte']
                trash_gte_contagem[v] = trash_gte_contagem.get(v, 0) + 1

        am = effects.get('activate_main', {})
        for step in am.get('steps', []):
            if step.get('action') == 'play_from_trash':
                valor = step.get('count', 1)
                if valor > win_con_value:
                    win_con_value = valor
                    win_con_code = c.code
                    win_con_cost = c.cost

    trash_target = 0
    if trash_gte_contagem:
        trash_target = max(trash_gte_contagem, key=lambda v: (trash_gte_contagem[v], -v))

    return {
        'trash_target': trash_target,
        'win_con_code': win_con_code,
        'don_target': win_con_cost,
    }


def compute_game_plan(p: 'GameState') -> dict:
    """
    Plano de jogo do deck. PREFERE o plano COMPLETO ja calculado uma vez do
    deck inteiro (`p.full_deck_plan`, ver full_deck_plan_for -- pedido do
    usuario 14/07: bot deve saber o proprio deck como um jogador humano
    sabe) -- se nao disponivel (contexto sem lookup de deck, ex: testes
    isolados), cai no fallback ANTIGO: escaneia as zonas REVELADAS
    (deck+mão+campo+trash+vida+stage — a união reconstrói a lista completa
    do deck a qualquer momento da partida, já que cartas próprias não saem
    dessas zonas em jogo normal), que só sabe o que já foi visto.
    """
    if getattr(p, 'full_deck_plan', None) is not None:
        return p.full_deck_plan

    zonas = list(p.deck) + list(p.hand) + list(p.field_chars) + list(p.trash) + list(p.life)
    if getattr(p, 'field_stage', None) is not None:
        zonas.append(p.field_stage)
    return compute_game_plan_from_cards(zonas)


def populate_full_deck_knowledge(state: 'GameState', cards: list, leader_code: str) -> None:
    """
    Popula full_deck_census/full_deck_plan/full_deck_profile de `state` a
    partir de uma decklist COMPLETA conhecida (`cards`) -- extraido de
    OPTCGMatch.__init__ (achado 14/07, comentário original preservado nos
    3 campos abaixo) pra ser reusado tanto por ReplayMatch.__init__
    (replay_optcg.py, nunca populava) quanto por server.py:_dto_to_gs no
    lado hide_hidden do oponente (achado 03/08, bloco HANDOFF 426):
    `cards` pode ser a decklist REAL (OPTCGMatch/ReplayMatch, que conhecem
    os dois decks completos) ou a decklist APROXIMADA do fallback em 3
    camadas de `opponent_model_for_leader` (sim_bridge.py) quando o
    oponente é genuinamente oculto -- mesma aproximação já usada pro
    Monte Carlo do OpponentModel, nenhuma informação nova exposta.

    Sem isso, `compute_game_plan`/`deck_profile_for` caem no fallback caro
    (recalculado em TODO clone do Turn Planner, não só 1x por partida) e
    `posture()` sempre degrada pra 'midrange' (achado 14/07) -- pra
    QUALQUER deck, inclusive o do oponente durante a simulação do turno de
    resposta dele (USE_OPPONENT_RESPONSE_SEARCH).
    """
    state.full_deck_census = deck_census(cards)
    # Achado real 10/08 (auditoria Sanji OP12-041, bloco 484): deck_census()
    # (deck_census.py) não pode importar get_card_flags daqui (import
    # circular -- este módulo já importa deck_census no topo) -- calcula
    # aqui e enriquece o census depois de pronto. Conta ferramentas de
    # REMOÇÃO real (kos/is_removal/bounces) vs de SELEÇÃO de carta
    # (is_searcher/draws) -- usado por `GameAnalyzer.deck_lacks_removal_
    # tools()` pra dar crédito de busca/compra na postura CONTROL quando o
    # deck genuinamente não tem remoção (ver avaliar_carta).
    n_removal = n_selection = 0
    for c in cards:
        flags = get_card_flags(getattr(c, 'code', ''))
        if flags.get('kos') or flags.get('is_removal') or flags.get('bounces'):
            n_removal += 1
        if flags.get('is_searcher') or flags.get('draws'):
            n_selection += 1
    state.full_deck_census['removal_tools'] = n_removal
    state.full_deck_census['card_selection_tools'] = n_selection
    state.full_deck_plan = compute_game_plan_from_cards(cards)
    if _build_profile_from_codes is not None:
        try:
            state.full_deck_profile = _build_profile_from_codes(
                [c.code for c in cards] + [leader_code])
        except Exception:
            state.full_deck_profile = None


def deck_profile_for(p: 'GameState') -> dict | None:
    """
    Perfil do deck (arquetipo + eixos derivados) do jogador p -- MODULE-LEVEL
    (nao metodo de OPTCGMatch) pra poder ser chamado tambem de DecisionEngine
    (avaliar_carta, etc.), que nao tem acesso ao cache que so existia em
    OPTCGMatch._turn_profile_for. Decisao 14/07 (pedido do usuario: parar de
    so consertar o Imu -- o arquetipo universal (deck_profile.py, ja provado
    em Imu/Krieg/Kid/Sakazuki/Moria) so era usado em turn_order e no
    simulador OFFLINE (_evaluate_state_v2); NUNCA nas funcoes que realmente
    decidem jogada/ataque AO VIVO (avaliar_carta etc.) -- por isso so decks
    de combo/reanimacao (o padrao que compute_game_plan reconhece) sentiam
    os consertos recentes.

    PREFERE o perfil COMPLETO ja calculado uma vez do deck inteiro
    (`p.full_deck_profile` -- pedido do usuario 14/07: bot deve saber
    arquetipo/papeis/eixos do proprio deck como um jogador humano sabe, nao
    so o que ja comprou). Sem isso disponivel, cai no fallback ANTIGO:
    identidade instavel = uniao das zonas REVELADAS (mesma logica de
    compute_game_plan; cartas proprias nao saem dessas zonas), cacheado por
    assinatura DIRETO no GameState (p._profile_cache) -- estavel entre as
    MUITAS instancias de DecisionEngine/OPTCGMatch criadas por decisao, mas
    ainda incompleto ate a partida revelar tudo.
    """
    full = getattr(p, 'full_deck_profile', None)
    if full is not None:
        return full
    if _build_profile_from_codes is None:
        return None
    zonas = list(p.deck) + list(p.hand) + list(p.field_chars) + \
        list(p.trash) + list(p.life)
    if getattr(p, 'field_stage', None) is not None:
        zonas.append(p.field_stage)
    if p.leader is not None:
        zonas.append(p.leader)
    codes = [c.code for c in zonas]
    sig = tuple(sorted(codes))
    cache = getattr(p, '_profile_cache', None)
    if cache is not None and cache[0] == sig:
        return cache[1]
    try:
        prof = _build_profile_from_codes(codes)
    except Exception:
        prof = None
    p._profile_cache = (sig, prof)
    return prof


# ===========================================================================
# Estruturas de dados
# ===========================================================================

@dataclass(frozen=True)
class CardData:
    """
    Dados FIXOS de uma carta -- idênticos para QUALQUER cópia física dela
    em qualquer GameState, NUNCA mutados durante uma partida (confirmado
    por levantamento de todas as atribuições do engine em 24/06: zero
    mutações para estes campos especificamente). Uma única instância de
    CardData é compartilhada (referenciada, nunca copiada) por todas as
    cópias da mesma carta -- isso é o que reduz o custo de deepcopy(Card)
    de "recriar um objeto grande" para "copiar uma referência + campos
    pequenos mutáveis" (ver Card abaixo).

    IMPORTANTE: has_rush/has_blocker/has_double_attack/has_banish/
    has_unblockable NÃO estão aqui, mesmo sendo "nativas" no banco --
    elas são MUTADAS em tempo de execução por efeitos de OUTRAS cartas
    (ex: OP10-099 Eustass"Captain"Kid concede Blocker a um Character via
    `card.has_blocker = True`) e são lidas diretamente (sem passar por
    is_blocker()/etc) em ~55 pontos do engine. Separar "nativo" de
    "concedido" exigiria migrar todos esses 55 pontos com risco real de
    regressão silenciosa -- mantidas em Card (mutável) por segurança,
    iguais ao comportamento já existente. has_trigger fica aqui porque
    nunca é concedida por outra carta (sem 'gain_trigger' no banco,
    confirmado em 24/06) -- é genuinamente fixa.
    """
    code: str
    name: str
    card_type: str       # LEADER, CHARACTER, EVENT, STAGE
    color: str
    cost: int = 0
    power: int = 0
    counter: int = 0
    life: int = 0
    sub_types: str = ''
    attribute: str = ''  # Slash, Special, Strike, Wisdom, Ranged (pode ser combinado, ex: "Slash Special")
    card_text: str = ''
    has_trigger: bool = False  # nunca concedida por outra carta -- genuinamente fixa
    is_searcher: bool = False
    draw_power: int = 0
    draw_then_trash: int = 0
    draw_condition: str = 'always'
    has_on_play_ko: bool = False
    has_bounce: bool = False
    don_cond_keywords: tuple = None  # tupla de (keyword, don_req) -- imutável, dict não é hashable/frozen-safe
    has_rest_effect: bool = False
    has_start_of_game: bool = False
    has_power_minus: bool = False
    trash_opp_char: bool = False
    alternate_names: tuple = ()  # aliases oficiais de identidade, imutaveis

    def don_cond_keywords_dict(self) -> dict:
        """Converte a tupla imutável de volta para dict, para uso em _kw_active."""
        return dict(self.don_cond_keywords) if self.don_cond_keywords else {}


@dataclass
class Card:
    """
    Estado MUTÁVEL de uma cópia física de carta nesta partida. `data`
    referencia um CardData COMPARTILHADO (nunca copiado por deepcopy --
    ver __deepcopy__) com os valores base e campos genuinamente fixos.
    Todo o resto aqui (incluindo keywords has_rush/has_blocker/etc, que
    podem ser concedidas por outras cartas) é copiado normalmente.
    """
    data: CardData
    # Keywords (nativas do banco OU concedidas por outra carta em tempo de
    # execução -- ver docstring de CardData sobre por que ficam aqui)
    has_rush: bool = False
    has_rush_character: bool = False  # [Rush: Character] -- so pode atacar Characters no turno em que entra, NUNCA o Leader (mecanica distinta de has_rush)
    has_blocker: bool = False
    has_double_attack: bool = False
    has_banish: bool = False
    has_unblockable: bool = False
    # Estado em jogo
    rested: bool = False
    just_played: bool = False
    rush_character_only_this_turn: bool = False  # True so na janela em que Rush: Character libera o ataque (reseta junto com just_played)
    don_attached: int = 0
    cannot_attack_until: str = ''   # '', 'opp_turn_end', 'opp_end_phase', 'my_next_turn_start' -- trava de ataque (lock_opp_character_attack)
    cannot_block_until: str = ''    # mesma semantica de duracao, para lock_opp_blocker_turn (Limejuice OP09-014, Kuzan OP16-063) -- trava PERSISTENTE de 1 character especifico, DISTINTA de blocker_lock_battle (transitoria, campo todo/filtrado, so 1 batalha)
    unblockable_this_turn: bool = False  # Unblockable CONCEDIDO so neste turno (Sanji ST21-003, Diable Jambe ST01-016, OP13-057) -- DISTINTO de has_unblockable (nativo ou gain_unblockable permanente). Resetado no refresh_phase do DONO. Regra 10-1-7-1 confirma equivalencia: "[Unblockable] prevents the opponent from activating [Blocker] when attacked" -- mesma semantica, so com expiracao.
    rush_this_turn: bool = False  # Rush CONCEDIDO so neste turno (39 cards, ex: EB01-045 Brook, OP01-008 Cavendish) -- mesma logica de unblockable_this_turn. has_rush continua sendo o permanente/nativo (NUNCA tocar -- decisao de 24/06 contra unificar nativo/concedido por risco de regressao em 17 pontos; este campo PARALELO evita o risco). Resetado no refresh_phase.
    double_attack_this_turn: bool = False  # Double Attack CONCEDIDO so neste turno (12 cards) -- mesma logica. has_double_attack permanente intocado.
    blocker_this_turn: bool = False  # Blocker CONCEDIDO so neste turno (6 cards) -- mesma logica. has_blocker permanente intocado.
    banish_this_turn: bool = False  # Banish CONCEDIDO so neste turno (achado 19/07, OP10-043 Moocy) -- mesma logica. has_banish permanente intocado.
    extra_attribute_this_turn: str = ''  # atributo ADICIONAL concedido temporariamente (achado 19/07, OP15-093: "gains [Rush: Character] and the 'Slash' attribute") -- o atributo NATIVO (self.attribute, vem de CardData imutavel) nunca muda; este campo soma um 2o atributo pra fins de matching (filter_attribute), resetado no refresh_phase.
    can_attack_active: bool = False  # "This Character can also attack active Characters" PERMANENTE (Cavendish OP04-081, Luffy OP04-090) -- keyword nunca implementada antes (achado 27/06, 9 cartas).
    can_attack_active_this_turn: bool = False  # mesma habilidade, mas CONCEDIDA so neste turno via select (Hibari, Gyats, Borsalino, Aramaki, Kuzan, Koby) -- resetada no refresh_phase.
    cannot_be_rested_until: str = ''  # mesma semantica de duracao, para lock_opp_cannot_be_rested (mecanica DISTINTA de cannot_attack)
    effects_negated_until: str = ''  # mesma semantica de duracao, para negate_effect (OP09-093 etc: "negate the effect of up to N of your opponent's Leader/Character"). Serve tanto pra Character quanto pra Leader (p.leader e um Card). Checado no topo de EffectExecutor.execute() -- bloqueia QUALQUER trigger disparado via execute() enquanto ativo (on_play ja resolvido nao e afetado retroativamente, so triggers futuros: activate_main, when_attacking, on_ko, your_turn/opp_turn, trigger). NAO cobre passivas lidas fora de execute() (is_blocker(), immunity, keyword boosts direto de get_card_effects) -- limitacao conhecida, mesmo padrao de divida tecnica ja documentado pro sistema de imunidade (TODO.md).
    immunity_ko_until: str = ''       # imunidade a KO por efeito TEMPORARIA concedida por outro efeito (ex: OP09-033 Nico Robin -- "none of your X type Characters can be K.O.'d by effects until end of opp's next turn"). Mesma semantica de duracao. Checada em is_immune().
    attack_paywall: dict = field(default_factory=dict)  # {'cost_type','cost_amount'} ou {} -- lock_opp_attack_unless_pays (OP08-043): PODE atacar, mas o DONO paga o custo a cada ataque enquanto ativo. Distinto de cannot_attack_until (bloqueio total). Resetado no refresh_phase do dono junto com cannot_attack_until (mesma simplificacao de duration ja usada la).
    frozen_next_refresh: bool = False  # Freeze (lock_opp_character_refresh / lock_self_character_refresh com target='this_card') -- pula APENAS o untap (c.rested=False) na PROXIMA refresh_phase do dono, consumido uma vez (refresh_phase zera este campo, fica rested mesmo se nao tiver sido atacado/restado por outro motivo). DISTINTO de cannot_be_rested_until (que trava o character de FICAR rested -- aqui e o oposto, ele PERMANECE rested ignorando o untap).
    life_face_up: bool = False  # estado valido apenas enquanto a carta esta na zona de Life (ST13/face-up life)
    ko_on_opp_blocker_used_this_turn: bool = False  # [Once Per Turn] "When your opponent activates a [Blocker], K.O. up to N..." (achado 17/07, ST10-006) -- resolvido fora de execute() (hook em _execute_attack, mesma janela de win_game_on_opp_blocker), entao o once_per_turn precisa de flag propria no Card (nao _once_used de EffectExecutor, que e por-instancia descartavel). Resetada no refresh_phase.
    # Buffs temporários (resetados a cada turno)
    power_buff: int = 0
    base_power_override: Optional[int] = None
    base_power_override_opp_turn: Optional[int] = None  # override PERMANENTE de base power valido SO quando NAO e o turno do dono (achado 19/07, OP15-070/OP15-071: "[Opponent's Turn] ... base power become N") -- concedido via aura em apply_conditional_keyword_passives (GRANT-ONLY idempotente, nunca resetado), lido em effective_card_power(your_turn=False). Distinto de base_power_override (SEMPRE ativo, independente de turno).
    cost_buff: int = 0       # resetado no fim do turno do oponente (duration until_opp_turn_end)
    cost_buff_permanent: int = 0  # nunca resetado (duration permanent, ex: leader_type condicional)
    # Rastreio de combate (achado 15/07, OP12-020 Zoro lider e familia --
    # OP04-047, ST02-010, ST08-013 tambem usam "battles your opponent's
    # Character" como condicao/gatilho): True se esta carta participou de
    # uma batalha CONTRA UM CHARACTER do oponente (nao Leader) neste
    # turno -- setado em _execute_attack apos o alvo final (pos-blocker)
    # ser resolvido. Resetado no refresh_phase do dono, igual just_played.
    battled_opp_character_this_turn: bool = False
    # "cannot attack opponent's Characters with a cost of N or less
    # during this turn" (OP12-020) -- auto-restricao de ALVO, DISTINTA de
    # cannot_attack_until (bloqueio TOTAL de ataque). -1 = sem restricao.
    cannot_attack_opp_chars_cost_lte: int = -1
    # "This Character's effect is negated during this turn" (OP06-083,
    # OP14-056 -- ambas so tem 'cannot_attack_self' como passivo proprio,
    # entao negar "o efeito desta carta" na pratica libera o ataque por 1
    # turno). Checado em is_attack_locked_self() ANTES de cannot_attack_self.
    # Resetado no refresh_phase do dono, mesma convencao de duration
    # "this_turn" ja usada por rush_this_turn/unblockable_this_turn.
    own_effect_negated_this_turn: bool = False

    def __deepcopy__(self, memo):
        """
        deepcopy customizado: `self.data` é uma REFERÊNCIA compartilhada,
        NUNCA copiada (é frozen/imutável, copiar seria desperdício puro --
        este é o ganho de performance real desta refatoração, medido por
        profiling em 24/06 mostrando 94% do tempo de simulação em
        deepcopy). Todo o resto (campos mutáveis) é copiado normalmente.
        """
        from copy import deepcopy as _dc
        cls = self.__class__
        novo = cls.__new__(cls)
        memo[id(self)] = novo
        novo.data = self.data  # referência compartilhada, SEM copiar
        for campo in ('has_rush', 'has_rush_character', 'has_blocker',
                      'has_double_attack', 'has_banish', 'has_unblockable',
                      'rested', 'just_played', 'rush_character_only_this_turn',
                      'don_attached', 'cannot_attack_until', 'cannot_be_rested_until', 'cannot_block_until',
                      'effects_negated_until',
                      'unblockable_this_turn', 'rush_this_turn', 'double_attack_this_turn', 'blocker_this_turn',
                      'banish_this_turn', 'extra_attribute_this_turn',
                      'can_attack_active', 'can_attack_active_this_turn',
                      'power_buff', 'base_power_override', 'base_power_override_opp_turn',
                      'cost_buff', 'cost_buff_permanent', 'frozen_next_refresh',
                      'life_face_up', 'immunity_ko_until',
                      'battled_opp_character_this_turn', 'cannot_attack_opp_chars_cost_lte',
                      'own_effect_negated_this_turn'):
            setattr(novo, campo, getattr(self, campo))
        for campo in ('_db_base_power', '_attack_power_override'):
            if hasattr(self, campo):
                setattr(novo, campo, getattr(self, campo))
        novo.attack_paywall = self.attack_paywall  # dict sempre REASSIGNED (nunca mutado in-place), referencia compartilhada e segura
        return novo

    # ── Properties de delegação para os campos fixos de CardData ──────────
    # Mantém `card.code`, `card.name`, etc funcionando exatamente como
    # antes em TODOS os pontos do engine que já acessam esses campos --
    # nenhum dos call sites existentes precisa mudar.
    @property
    def code(self) -> str: return self.data.code
    @property
    def name(self) -> str: return self.data.name
    @property
    def card_type(self) -> str: return self.data.card_type
    @property
    def color(self) -> str: return self.data.color
    @property
    def cost(self) -> int: return self.data.cost
    @property
    def power(self) -> int: return self.data.power
    @property
    def counter(self) -> int: return self.data.counter
    @property
    def life(self) -> int: return self.data.life
    @property
    def sub_types(self) -> str: return self.data.sub_types
    @property
    def attribute(self) -> str: return self.data.attribute
    @property
    def card_text(self) -> str: return self.data.card_text
    @property
    def has_trigger(self) -> bool: return self.data.has_trigger
    @property
    def is_searcher(self) -> bool: return self.data.is_searcher
    @property
    def draw_power(self) -> int: return self.data.draw_power
    @property
    def draw_then_trash(self) -> int: return self.data.draw_then_trash
    @property
    def draw_condition(self) -> str: return self.data.draw_condition
    @property
    def has_on_play_ko(self) -> bool: return self.data.has_on_play_ko
    @property
    def has_bounce(self) -> bool: return self.data.has_bounce
    @property
    def don_cond_keywords(self) -> dict: return self.data.don_cond_keywords_dict()
    @property
    def has_rest_effect(self) -> bool: return self.data.has_rest_effect
    @property
    def has_start_of_game(self) -> bool: return self.data.has_start_of_game
    @property
    def has_power_minus(self) -> bool: return self.data.has_power_minus
    @property
    def trash_opp_char(self) -> bool: return self.data.trash_opp_char
    @property
    def alternate_names(self) -> tuple: return self.data.alternate_names

    def effective_cost(self) -> int:
        from optcg_engine.rules_facade import effective_card_cost
        return effective_card_cost(self)

    def _kw_active(self, kw: str, native: bool) -> bool:
        """Keyword ativa se nativa OU condicional a [DON!! ×N] com DON suficiente."""
        if native:
            return True
        cond = self.don_cond_keywords or {}
        req = cond.get(kw)
        if req is not None:
            return getattr(self, 'don_attached', 0) >= req
        return False

    def is_blocker(self) -> bool:
        return self._kw_active('blocker', self.has_blocker) or self.blocker_this_turn

    def is_double_attack(self) -> bool:
        return self._kw_active('double_attack', self.has_double_attack) or self.double_attack_this_turn

    def is_rush(self) -> bool:
        return self._kw_active('rush', self.has_rush) or self.rush_this_turn

    def is_rush_character(self) -> bool:
        return self._kw_active('rush_character', self.has_rush_character)

    def is_banish(self) -> bool:
        return self._kw_active('banish', self.has_banish) or self.banish_this_turn

    def effective_power(self, your_turn: bool = True) -> int:
        from optcg_engine.rules_facade import effective_card_power
        return effective_card_power(self, your_turn=your_turn)

    def board_value(self) -> int:
        v = self.power // 1000
        if self.has_rush or self.rush_this_turn:          v += 4
        if self.has_blocker or self.blocker_this_turn:       v += 3
        if self.has_double_attack or self.double_attack_this_turn: v += 3
        if self.has_banish or self.banish_this_turn:        v += 2
        if self.has_unblockable:   v += 4
        if self.has_trigger:       v += 2
        return v


def character_needs_rush(c: 'Card') -> bool:
    """Rush so importa pra quem ENTROU EM CAMPO NESTE TURNO (just_played) e
    ainda nao tem a permissao -- um Character de turno anterior ja ataca
    normal sem Rush, e um ja rested nao ataca de novo de qualquer forma
    (correcao do usuario 02/08). Fonte unica: usado tanto pela execucao real
    (_execute_step/select_grant_rush) quanto pela decisao (_step_is_viable)
    quanto pela ordenacao de alvo ao vivo (sim_bridge.order_target_candidates)
    -- sem isto, o jogo ao vivo concedia Rush a personagens ja restados via
    um heuristico de ordenacao generico que nao conhece essa regra."""
    return c.just_played and not c.rested and not c.is_rush()


def character_needs_rush_character(c: 'Card') -> bool:
    return c.just_played and not c.rested and not c.is_rush_character()


# Gatilhos que so resolvem DENTRO de uma janela de ataque/combate --
# mesma lista usada por sim_bridge.order_target_candidates pra filtrar
# quais blocos de efeito sao RELEVANTES pro contexto atual (achado real
# 20/07: cartas dual-mode tinham os blocos de [Counter] e [Main]
# misturados nas deteccoes de zona quando so um dos dois resolvia de
# verdade). Fonte unica -- nao duplicar esta lista em outro arquivo.
COMBAT_ONLY_TRIGGERS = {'counter', 'when_attacking', 'on_opp_attack', 'leader_battle_reactive'}

_HAND_ONLY_COST_TYPES = {'trash_from_hand', 'reveal_from_hand', 'trash_any_from_hand'}
_ORTHOGONAL_COST_TYPES = {'don_minus', 'rest_don', 'rest_self', 'trash_self'}
_NO_ZONE_TARGETS = {'self', 'own_play_self', 'this_card'}
_SAFE_NO_TARGET_ACTIONS = {
    'draw', 'gain_life', 'add_don', 'set_don_active', 'immunity',
    'set_active', 'buff_cost', 'debuff_cost', 'substitute_removal',
    'activate_main_effect',
}


def step_is_safe_no_target(step: dict) -> bool:
    """
    True quando um step SEM alvo implicito de fato NAO precisa de selecao
    de zona nenhuma pra resolver -- fonte unica usada tanto por
    actor_effect_is_hand_cost_only (abaixo) quanto por
    sim_bridge.order_target_candidates (deteccao de actor_opp_only/
    actor_battlefield_only) pra decidir quais steps "somem" da conta de
    alvos relevantes sem virar falso negativo (blocos 470-472/478).

    Excecao GENERICA a _SAFE_NO_TARGET_ACTIONS (nao amarrada a 1 carta,
    ver auditoria global obrigatoria do projeto pra grammar de parser):
    `gain_life` com source='trash'/'hand_or_trash' PRECISA escolher uma
    carta de verdade do trash (Shiryu OP16-108: "add up to 1 {Blackbeard
    Pirates} card cost<=6 FROM YOUR TRASH to life", ST13-003
    hand_or_trash) -- diferente de source='deck_top' (topo do proprio
    deck, sem zona clicavel visivel) ou source='hand'/'own_field' (zonas
    ja sempre disponiveis nas exclusoes duras existentes, own_hand/
    own_board nunca ficam de fora). Achado real 13/08 (partida ao vivo,
    usuario: "bot nao consegue ganhar vida com Shiryu"): own_trash sumia
    da lista de candidatos porque actor_effect_is_hand_cost_only tratava
    o step gain_life(source=trash) como "sem selecao real", excluindo a
    UNICA zona onde o alvo de verdade vive (auditado em todo o banco: só
    esses 2 codes usam source in trash/hand_or_trash em gain_life hoje).
    """
    action = step.get('action') or ''
    if action not in _SAFE_NO_TARGET_ACTIONS:
        return False
    if action == 'gain_life' and step.get('source') in ('trash', 'hand_or_trash'):
        return False
    return True


def actor_effect_is_hand_cost_only(actor_code: str, in_combat: bool) -> bool:
    """True quando TODOS os blocos de efeito relevantes do ator (filtrados
    por janela de combate, ver COMBAT_ONLY_TRIGGERS) so tem custo de mao
    (trash/reveal_from_hand) e nenhum step pede selecao de campo/oponente
    -- usado por sim_bridge.order_target_candidates pra saber quando e
    seguro EXCLUIR (nao so deprioritizar) qualquer zona que nao seja
    own_hand/DON dos candidatos de alvo ao vivo.

    CONSERVADOR de proposito: exige 'target' EXPLICITO em self/own_play_
    self/this_card, OU a acao estar na allowlist _SAFE_NO_TARGET_ACTIONS
    -- NAO trata target=None generico como seguro (varias acoes como
    play_from_trash/add_from_trash/look_top_deck/
    place_opp_character_bottom_deck escondem selecao real de outra zona
    -- trash/topo do deck/campo do oponente -- no NOME da acao, nao no
    campo 'target'). Achado real 02/08 (telemetria, log
    Portgas.D.Ace-R x Crocodile-B 2026-08-02T09.41.46): decisoes de alvo
    pro Luffy OP16-015 (custo SO de mao) chegavam com 65-73 candidatos
    (todas as zonas do jogo, porque CollectTargetCandidates/C# manda tudo
    e essa distincao nunca existia) -- correlacionado com ~27-31s de
    atraso por decisao (bot clicando candidato por candidato, cooldown de
    0.8s cada, ate acertar a mao por sorte)."""
    effects = get_card_effects(actor_code)
    blocks = [v for k, v in effects.items()
              if isinstance(v, dict)
              and (k in COMBAT_ONLY_TRIGGERS) == in_combat]
    tem_custo_mao = False
    for block in blocks:
        for cost in block.get('costs', []):
            ctype = cost.get('type')
            if ctype in _HAND_ONLY_COST_TYPES:
                tem_custo_mao = True
            elif ctype is not None and ctype not in _ORTHOGONAL_COST_TYPES:
                return False
        for s in block.get('steps', []):
            tgt = s.get('target')
            seguro = tgt in _NO_ZONE_TARGETS or (tgt is None and step_is_safe_no_target(s))
            if not seguro:
                return False
    return tem_custo_mao


def actor_effect_has_hand_cost(actor_code: str, in_combat: bool) -> bool:
    """True quando QUALQUER bloco de efeito relevante do ator (mesmo filtro
    de janela de combate de actor_effect_is_hand_cost_only) declara um
    custo de mao (trash_from_hand/reveal_from_hand/trash_any_from_hand),
    INDEPENDENTE do alvo do proprio efeito ser campo/lider (diferente de
    actor_effect_is_hand_cost_only, que exige que NENHUM step peca campo).

    Usado por sim_bridge.order_target_candidates pra NAO excluir own_hand
    quando actor_battlefield_only tambem e verdadeiro pro mesmo ator --
    achado real 09/08 (You're the One Who Should Disappear, OP06-115):
    [Counter] buff_power target=leader_or_character (campo, dispara
    actor_battlefield_only) com custo trash_from_hand=1 (paga descartando
    da mao). Excluir own_hand duro nesse caso quebra o pagamento do custo
    de verdade -- mesmo padrao do caso Edward Newgate ja documentado em
    actor_effect_is_hand_cost_only (reveal_from_hand + debuff_power
    target=opp_character no MESMO bloco: os dois custos ficam na mesma
    pergunta ao vivo)."""
    effects = get_card_effects(actor_code)
    blocks = [v for k, v in effects.items()
              if isinstance(v, dict)
              and (k in COMBAT_ONLY_TRIGGERS) == in_combat]
    for block in blocks:
        for cost in block.get('costs', []):
            if cost.get('type') in _HAND_ONLY_COST_TYPES:
                return True
    return False


# Acoes de campo (Character/Leader) que sim_bridge.order_target_candidates
# ja sabe mapear pra opp_board/own_board via _implied_target -- extraido
# aqui pra reusar a mesma lista na deteccao de filtro numerico abaixo.
_BATTLEFIELD_FILTERABLE_ACTIONS = {
    'ko', 'rest_opp_character', 'bounce_opp_character', 'debuff_power',
    'ko_own_character', 'rest_own_character', 'trash_own_character',
}


def actor_step_numeric_filter(actor_code: str, in_combat: bool):
    """Se o UNICO step relevante do ator (filtrado por janela de combate)
    que mira campo/oponente tiver filtro numerico (cost_lte/power_lte/
    power_gte), devolve (target_label, filtro) pra sim_bridge.
    order_target_candidates EXCLUIR (nao so deprioritizar) candidatos do
    campo que nao batem -- mesmo padrao de exclusao dura de actor_opp_only/
    actor_hand_cost_only, agora pro FILTRO do proprio step, nao so a zona.

    CONSERVADOR: exige exatamente 1 step de campo com filtro numerico
    entre os blocos relevantes -- 2+ steps ambiguos (podem exigir filtros
    DIFERENTES) abortam a generalizacao (None), preservando o
    comportamento antigo (so deprioridade) nesses casos raros.

    Achado real 08/08 (usuario, partida ao vivo -- "doc q chegou a
    escolher 1 alvo, travou no 2o por falta de alvo, anulou sem dar KO
    em ninguem"): Doc Q OP16-109 ("K.O. up to 2... com custo 1 ou
    menos") tinha SO 1 alvo valido em campo; a decisao de alvo pro 2o
    slot pediu a MESMA lista de 37 candidatos (deck+mao+trash+campo dos
    dois lados) duas vezes, 23s de diferenca -- nenhum filtro de custo
    excluia quem nao batia, o cliente clicou candidato por candidato
    (0.8s de cooldown) ate esgotar a lista e o efeito inteiro (incluindo
    o 1o alvo ja escolhido) foi cancelado."""
    effects = get_card_effects(actor_code)
    blocks = [v for k, v in effects.items()
              if isinstance(v, dict)
              and (k in COMBAT_ONLY_TRIGGERS) == in_combat]
    achado = None
    for block in blocks:
        for s in block.get('steps', []):
            if s.get('action') not in _BATTLEFIELD_FILTERABLE_ACTIONS:
                continue
            filtro = {k: s[k] for k in ('cost_lte', 'power_lte', 'power_gte')
                      if s.get(k) is not None}
            if not filtro:
                continue
            target = s.get('target') or ''
            lado = 'opp' if 'opp' in target else 'own' if target else None
            if lado is None:
                continue
            if achado is not None:
                return None  # 2+ steps com filtro -- ambiguo, nao generaliza
            achado = (lado, filtro)
    return achado


@dataclass
class GameState:
    leader: Card
    deck: List[Card] = field(default_factory=list)
    hand: List[Card] = field(default_factory=list)
    field_chars: List[Card] = field(default_factory=list)
    field_stage: Optional[Card] = None
    life: List[Card] = field(default_factory=list)
    don_deck: int = 10
    don_available: int = 0
    don_rested: int = 0
    frozen_don_count: int = 0  # Freeze de DON (lock_opp_don_refresh, OP10-033) -- N do don_rested NAO volta a ficar available na proxima refresh_phase deste jogador. Consumido uma vez (capado por min(frozen_don_count, don_rested) no momento do refresh, depois zerado).
    trash: List[Card] = field(default_factory=list)
    turn: int = 0
    global_turn: int = 0
    # Verdadeiro apenas para o jogador cujo turno esta em andamento. Usado
    # por eventos reativos que distinguem [Your Turn]/[Opponent's Turn].
    is_active_turn: bool = True
    # Auto-restrição "cannot play this turn" (combo set DON active + você se trava).
    # Resetados no início do próprio turno. Valores:
    #   cant_play_from_hand_this_turn: True = não pode jogar NADA da mão
    #   cant_play_chars_this_turn:     True = não pode jogar CHARACTER
    #   cant_play_cost_gte:            int  = não pode jogar com base cost >= N (0 = sem limite)
    cant_play_from_hand_this_turn: bool = False
    cant_play_chars_this_turn: bool = False
    cant_play_cost_gte: int = 0
    cannot_attack_leader_this_turn: bool = False
    cant_take_life_this_turn: bool = False  # ST15-001 Atmos: "cannot add Life cards to your hand using your own effects this turn"
    face_up_life_to_deck: bool = False      # ST13-003 Luffy Leader: face-up life cards go to BOTTOM of deck instead of hand when damaged
    # Snapshot da CONTAGEM de Life (minha e do oponente) na ULTIMA vez que
    # apply_your_turn_buffs rodou pra este jogador -- -1 = nunca rodou
    # ainda (sem baseline, condicao de "vida removida" default False).
    # Achado 29/07 (pente-fino nos lideres, Nami OP11-041): "This effect
    # can be activated when a card is removed from your or your
    # opponent's Life cards" e um gatilho REATIVO que o engine nao
    # suporta de verdade (your_turn so dispara 1x, no INICIO do main_phase,
    # antes de qualquer combate do proprio turno acontecer) -- a
    # aproximacao possivel e "alguma Life mudou (diminuiu) desde a
    # ULTIMA vez que este check rodou pra mim", que cobre o caso real
    # mais comum (dano recebido no turno do OPONENTE, entre meu ultimo
    # check e este). Comparado e ATUALIZADO em apply_your_turn_buffs, NAO
    # em _check_conditions (que precisa ficar um predicado puro, sem
    # side-effect, pra nao quebrar branches simulados do Turn Planner).
    life_count_snapshot_mine: int = -1
    life_count_snapshot_opp: int = -1
    is_first: bool = True
    # Estatísticas
    dmg_dealt: int = 0
    chars_played: int = 0
    counters_used: int = 0
    searchers_used: int = 0
    triggers_activated: int = 0
    full_deck_census: dict = None
    # ids (id(card), nao codigo -- pode haver copias da mesma carta na mao
    # com status de revelacao diferente) das instancias de Card atualmente
    # na mao que foram expostas ao oponente por um efeito de busca com
    # 'reveal' (confirmado pela regra oficial: o padrao "look at N; reveal
    # up to 1 [filtro] and add to hand" expoe a carta especifica escolhida,
    # mesmo sendo o texto mais comum do jogo -- distinto de dano normal na
    # vida, que NUNCA revela, e de busca sem a palavra 'reveal', que tambem
    # nao revela). Removido do set quando a carta sai da mao (jogada,
    # trashada, etc) -- usado pelo OpponentModel para saber quais cartas
    # specificas o oponente certamente tem, em vez de sortear via Monte Carlo.
    revealed_to_opponent: set = field(default_factory=set)
    # Memoria de INFORMACAO REVELADA (mesma ideia de revealed_to_opponent,
    # estendida pra vida e deck). ids (id(card)) de cartas cuja IDENTIDADE ja
    # foi vista por um efeito de "olhar/revelar" e que continuam na zona --
    # persistem entre turnos ate a carta sair (limpeza lazy em known_*_cards,
    # mesmo padrao seguro de known_hand_cards). Alimentam o OpponentModel
    # (reduz incerteza da vida do oponente) e decisoes de sequenciamento
    # (saber o topo do proprio deck/vida). Reveals que populam:
    #   revealed_life  -> peek/reveal de carta da Life (Katakuri, OP15-119
    #                     life_top_revealed_cost, etc.)
    #   revealed_deck  -> topo do deck visto por SEARCH (look at top N) ou peek
    #                     (peek_opp_deck_top da Pudding, reveal_opp_deck_top...)
    revealed_life: set = field(default_factory=set)
    revealed_deck: set = field(default_factory=set)
    # Trava TRANSITORIA de Blocker, escopo de UMA UNICA batalha (a que esta
    # sendo resolvida agora). Setada por lock_opp_blocker_battle (efeito
    # [When Attacking] do atacante) e LIMPA pelo proprio _resolve_battle
    # logo depois do block step -- nunca deve sobreviver pra proxima
    # batalha. None = sem trava. dict = {'power_lte'|'power_gte'|'cost_lte': N}.
    blocker_lock_battle: Optional[dict] = None
    end_of_turn_queue: List[dict] = field(default_factory=list)
    pending_play_cost_reductions: List[dict] = field(default_factory=list)
    # "Then, take an extra turn after this one" (achado 16/07, OP05-119,
    # unica carta no banco). Setado pelo executor de take_extra_turn,
    # consumido e resetado pelo loop de simulate() logo apos play_turn().
    extra_turn_pending: bool = False
    # Custos dos Events ativados/jogados NESTE turno (achado 16/07,
    # OP15-002 Lucy: "if you have activated an Event with a base cost of N
    # or more during this turn"). Populado em _play_card() sempre que um
    # EVENT sai da mao, resetado no inicio de cada turno do jogador
    # (refresh_phase, mesmo ponto onde as outras auto-restricoes "this
    # turn" sao limpas).
    events_activated_costs_this_turn: List[int] = field(default_factory=list)

    def __deepcopy__(self, memo):
        """
        Clone enxuto para o Turn Planner. `Card` ja tem __deepcopy__ proprio,
        entao aqui evitamos o caminho generico do dataclass e copiamos apenas
        as zonas/flags do estado.
        """
        from copy import deepcopy as _dc
        cls = self.__class__
        novo = cls.__new__(cls)
        memo[id(self)] = novo

        novo.leader = _dc(self.leader, memo)
        novo.deck = [_dc(c, memo) for c in self.deck]
        novo.hand = [_dc(c, memo) for c in self.hand]
        novo.field_chars = [_dc(c, memo) for c in self.field_chars]
        novo.field_stage = _dc(self.field_stage, memo) if self.field_stage else None
        novo.life = [_dc(c, memo) for c in self.life]
        novo.trash = [_dc(c, memo) for c in self.trash]

        novo.don_deck = self.don_deck
        novo.don_available = self.don_available
        novo.don_rested = self.don_rested
        novo.frozen_don_count = self.frozen_don_count
        novo.turn = self.turn
        novo.global_turn = self.global_turn
        novo.is_active_turn = self.is_active_turn
        novo.cant_play_from_hand_this_turn = self.cant_play_from_hand_this_turn
        novo.cant_take_life_this_turn = self.cant_take_life_this_turn
        novo.face_up_life_to_deck = self.face_up_life_to_deck
        novo.cant_play_chars_this_turn = self.cant_play_chars_this_turn
        novo.cant_play_cost_gte = self.cant_play_cost_gte
        novo.cannot_attack_leader_this_turn = self.cannot_attack_leader_this_turn
        novo.life_count_snapshot_mine = self.life_count_snapshot_mine
        novo.life_count_snapshot_opp = self.life_count_snapshot_opp
        novo.is_first = self.is_first

        novo.dmg_dealt = self.dmg_dealt
        novo.chars_played = self.chars_played
        novo.counters_used = self.counters_used
        novo.searchers_used = self.searchers_used
        novo.triggers_activated = self.triggers_activated
        # full_deck_census e INVARIANTE (setado no setup, nunca mutado durante
        # o jogo) -- compartilhamos a REFERENCIA em vez de deepcopiar o dict
        # inteiro a cada clone do Turn Planner (economiza ~0.1ms por clone
        # sem risco de corrupcao, confirmado por leitura de todos os call sites).
        novo.full_deck_census = self.full_deck_census
        # full_deck_plan/full_deck_profile: MESMO padrao acima (invariantes,
        # setados 1x no setup -- server.py:_dto_to_gs ou
        # OPTCGMatch.setup(), nunca mutados depois, confirmado por grep em
        # todo o arquivo). Achado real 02/08 (usuario pediu pra investigar
        # lentidao da busca ao vivo): faltavam aqui -- getattr(novo,
        # 'full_deck_plan', None) sempre voltava None em QUALQUER clone
        # (Turn Planner clona o estado dezenas/centenas de vezes por
        # decisao), forcando compute_game_plan() a cair no fallback caro
        # (escanear deck+mao+trash+vida inteiros + compute_game_plan_from_cards)
        # de novo a CADA clone -- profiling de 1 decisao real (12 amostras)
        # mostrou 4331 chamadas a compute_game_plan_from_cards, 0.7-1.3s
        # (de 5.8s totais) so nisso.
        novo.full_deck_plan = getattr(self, 'full_deck_plan', None)
        novo.full_deck_profile = getattr(self, 'full_deck_profile', None)
        # self_play_info_hidden/hidden_information_masked: atributos
        # DINAMICOS (getattr, nunca campos declarados) -- achado real 10/08
        # (bloco 490, ao ligar o simulador self x self): sem propagar aqui,
        # o UNICO call site que deepcopia GameState (_simulate_sequence_once,
        # Monte Carlo do Turn Planner, dezenas/centenas de clones por
        # decisao) perdia a flag em TODO turno simulado dentro da busca --
        # a partida real (state_a/state_b, nunca clonados diretamente)
        # mantinha a flag, mas qualquer lookahead do Turn Planner voltava a
        # info cheia silenciosamente, esvaziando o proposito da flag pro
        # caminho de decisao que mais importa (USE_OPPONENT_RESPONSE_SEARCH).
        if getattr(self, 'self_play_info_hidden', False):
            novo.self_play_info_hidden = True
        if getattr(self, 'hidden_information_masked', False):
            novo.hidden_information_masked = True
        # eval_weights/use_eval_v2: MESMO padrao de bug do self_play_info_
        # hidden acima -- achado real 11/08 (bloco 495, ao investigar por
        # que a calibracao pareada de next_turn_readiness_self/opp_threat
        # deu resultado IDENTICO pra todo candidato). `_evaluate_state_v2`
        # (a UNICA leitora de eval_weights, ver comentario dela "so roda em
        # p2/opp2") e chamada SEMPRE sobre o clone de _simulate_sequence_
        # once -- sem propagar aqui, QUALQUER override por-estado
        # (`state.eval_weights = {...}`, o mecanismo que tune_weights.py
        # usa pra dar pesos DIFERENTES a cada lado numa mesma partida)
        # nunca chegava na avaliacao de verdade: o clone caia sempre no
        # fallback `EVAL_WEIGHTS` global, entao toda busca Monte Carlo via
        # _simulate_sequence_once ignorava silenciosamente o candidato.
        # Efeito pratico: a calibracao pareada deste peso saiu com margem
        # zero pra TODOS os candidatos (nao so este par de pesos -- afeta
        # qualquer chamada de tune_weights.py que dependa do lado A/B
        # terem pesos v2 diferentes via este mecanismo).
        if hasattr(self, 'eval_weights'):
            novo.eval_weights = self.eval_weights
        if hasattr(self, 'use_eval_v2'):
            novo.use_eval_v2 = self.use_eval_v2
        novo.revealed_to_opponent = set(self.revealed_to_opponent)
        novo.revealed_life = set(self.revealed_life)
        novo.revealed_deck = set(self.revealed_deck)
        novo.blocker_lock_battle = _dc(self.blocker_lock_battle, memo)
        novo.end_of_turn_queue = _dc(self.end_of_turn_queue, memo)
        novo.pending_play_cost_reductions = _dc(self.pending_play_cost_reductions, memo)
        novo.extra_turn_pending = self.extra_turn_pending
        novo.events_activated_costs_this_turn = list(self.events_activated_costs_this_turn)
        return novo

    def known_hand_cards(self) -> List['Card']:
        """
        Subconjunto de `self.hand` que é conhecido pelo oponente (cartas
        reveladas por efeito de busca e que ainda estão na mão). Filtra de
        forma lazy contra `self.hand` em vez de exigir limpeza manual de
        `revealed_to_opponent` em cada um dos pontos do engine onde uma
        carta sai da mão (jogada, trashada, etc) -- mais seguro do que
        arriscar esquecer algum desses pontos e deixar um id() órfão
        apontando para memória já realocada para outra carta.
        """
        ids_na_mao = {id(c) for c in self.hand}
        # remove ids que não correspondem a nenhuma carta atual na mão
        # (carta já saiu -- ex: jogada, trashada). Faz isso aqui (lazy)
        # em vez de em cada ponto de remoção da mão.
        self.revealed_to_opponent &= ids_na_mao
        return [c for c in self.hand if id(c) in self.revealed_to_opponent]

    def known_life_cards(self) -> List['Card']:
        """Cartas da Life cuja identidade ja foi revelada por efeito e que
        AINDA estao na Life. Mesma limpeza lazy de known_hand_cards -- quando
        a carta sai da Life (dano, movida pro deck/mao), o id orfao some."""
        ids_na_vida = {id(c) for c in self.life}
        self.revealed_life &= ids_na_vida
        return [c for c in self.life if id(c) in self.revealed_life]

    def known_deck_cards(self) -> List['Card']:
        """Cartas do deck cuja identidade ja foi vista (search/peek do topo) e
        que AINDA estao no deck. Limpeza lazy identica -- a carta buscada pra
        mao ou movida pra outra zona deixa de contar automaticamente."""
        ids_no_deck = {id(c) for c in self.deck}
        self.revealed_deck &= ids_no_deck
        return [c for c in self.deck if id(c) in self.revealed_deck]

    def life_count(self) -> int:
        return len(self.life)

    def active_chars(self) -> List[Card]:
        return [c for c in self.field_chars
                if not c.rested and (not c.just_played or c.is_rush()
                                     or c.is_rush_character()
                                     or c.rush_character_only_this_turn)]

    def rested_chars(self, attacker: 'Card' = None) -> List[Card]:
        # "This Character can also attack active Characters" (permanente ou
        # so este turno, 9 cartas -- achado 27/06, nunca implementado antes).
        # Sem attacker (uso normal de scoring/heuristica) mantém o
        # comportamento de sempre -- só passa attacker explicitamente nos
        # pontos que decidem o ataque real, pra não arriscar a lógica de
        # múltiplos atacantes do planejador numa mudança apressada.
        if attacker is not None and (attacker.can_attack_active or attacker.can_attack_active_this_turn):
            return list(self.field_chars)
        return [c for c in self.field_chars if c.rested]

    def counter_in_hand(self) -> int:
        # Achado real 03/08 (usuario pediu pra investigar avaliar_carta/
        # _trash_value, hot spots do profiling pos-fix do bloco 426):
        # `effective_counter(c, self)` era chamado 2x por carta (uma vez no
        # filtro `if`, outra na soma) -- profiling confirmou 94% das
        # chamadas de effective_counter (115636/122388 numa partida real)
        # vinham daqui. Calcula 1x por carta e reusa.
        valores = [effective_counter(c, self) for c in self.hand]
        return sum(v for v in valores if v > 0)

    def blockers_active(self) -> List[Card]:
        elegiveis = [c for c in self.field_chars
                     if c.is_blocker() and not c.rested and not c.cannot_be_rested_until
                     and not c.cannot_block_until]
        lock = self.blocker_lock_battle
        if lock is None:
            return elegiveis
        power_lte = lock.get('power_lte')
        power_gte = lock.get('power_gte')
        cost_lte = lock.get('cost_lte')
        if power_lte is None and power_gte is None and cost_lte is None:
            return []   # sem filtro -- trava o campo inteiro
        def travado(c):
            if power_lte is not None and c.power <= power_lte: return True
            if power_gte is not None and c.power >= power_gte: return True
            if cost_lte is not None and c.cost <= cost_lte: return True
            return False
        return [c for c in elegiveis if not travado(c)]

    def board_score(self) -> int:
        return sum(c.board_value() for c in self.field_chars)

    def estimated_counter(self) -> int:
        return len(self.hand) * 1000

    def can_attack_this_turn(self) -> bool:
        return self.turn > 1

    def don_on_field(self) -> int:
        return self.don_available + self.don_rested


def _play_cost_rule_matches(card: Card, rule: dict) -> bool:
    if card.card_type != 'CHARACTER':
        return False
    if card.cost < rule.get('cost_gte', 0):
        return False
    if rule.get('filter_type') and _norm_type_text(rule['filter_type']) not in _norm_type_text(card.sub_types):
        return False
    if rule.get('filter_name') and rule['filter_name'].lower() not in card.name.lower():
        return False
    return True


def _hand_cost_conditions_match(p: GameState, opp: Optional[GameState],
                                card: Card, conds: dict) -> bool:
    if 'life_lte' in conds and p.life_count() > conds['life_lte']:
        return False
    if 'trash_gte' in conds and len(p.trash) < conds['trash_gte']:
        return False
    if 'events_in_trash_gte' in conds:
        events = sum(1 for c in p.trash if c.card_type == 'EVENT')
        if events < conds['events_in_trash_gte']:
            return False
    if 'leader_power_lte' in conds and p.leader.effective_power(True) > conds['leader_power_lte']:
        return False
    if 'leader_type' in conds:
        if _norm_type_text(conds['leader_type']) not in _norm_type_text(p.leader.sub_types):
            return False
    if 'leader_name_includes' in conds:
        if conds['leader_name_includes'].lower() not in p.leader.name.lower():
            return False
    if 'don_gte' in conds and p.don_on_field() < conds['don_gte']:
        return False
    if 'don_on_field_gte' in conds and p.don_on_field() < conds['don_on_field_gte']:
        return False
    if 'don_on_field_zero_or_gte' in conds:
        n = p.don_on_field()
        if not (n == 0 or n >= conds['don_on_field_zero_or_gte']):
            return False
    if 'other_char_power_gte' in conds:
        candidates = [c for c in p.field_chars if c is not card]
        filter_type = conds.get('other_char_power_gte_type')
        if filter_type:
            candidates = [c for c in candidates
                          if _norm_type_text(filter_type) in _norm_type_text(c.sub_types)]
        filter_names = [n.lower() for n in conds.get('other_char_power_gte_names', [])]
        if filter_names:
            candidates = [c for c in candidates
                          if any(n in c.name.lower() for n in filter_names)]
        power_of = ((lambda c: c.power) if conds.get('other_char_power_uses_base')
                    else (lambda c: c.effective_power(True)))
        if not any(power_of(c) >= conds['other_char_power_gte']
                   for c in candidates):
            return False
    if 'opp_char_power_gte' in conds:
        if opp is None or not any(
                c.power >= conds['opp_char_power_gte'] for c in opp.field_chars):
            return False
    if 'opp_char_cost_eq_or_gte' in conds:
        rule = conds['opp_char_cost_eq_or_gte']
        if opp is None or not any(
                c.cost == rule['eq'] or c.cost >= rule['gte'] for c in opp.field_chars):
            return False
    if 'opp_char_cost_eq' in conds:
        if opp is None or not any(c.cost == conds['opp_char_cost_eq']
                                  for c in opp.field_chars):
            return False
    if 'opp_rested_cards_gte' in conds:
        if opp is None:
            return False
        rested = opp.don_rested + sum(1 for c in opp.field_chars if c.rested)
        rested += int(bool(getattr(opp.leader, 'rested', False)))
        rested += int(bool(opp.field_stage and getattr(opp.field_stage, 'rested', False)))
        if rested < conds['opp_rested_cards_gte']:
            return False
    if conds.get('don_on_field_lte_opp'):
        if opp is None or p.don_on_field() > opp.don_on_field():
            return False
    if 'don_fewer_than_opp_by_gte' in conds:
        if opp is None or opp.don_on_field() - p.don_on_field() < conds['don_fewer_than_opp_by_gte']:
            return False
    return True


def effective_hand_play_cost(p: GameState, card: Card,
                             opp: Optional[GameState] = None) -> int:
    """Custo para jogar uma carta da mao no estado simplificado atual."""
    cost = card.effective_cost()
    stage = p.field_stage
    if stage:
        for entry in get_card_effects(stage.code).values():
            for step in entry.get('steps', []):
                if (step.get('action') == 'buff_cost'
                        and step.get('target') == 'own_play_hand'
                        and _play_cost_rule_matches(card, step)):
                    cost -= step.get('amount', 0)
    for rule in p.pending_play_cost_reductions:
        if _play_cost_rule_matches(card, rule):
            cost -= rule.get('amount', 0)
    passive = get_card_effects(card.code).get('passive', {})
    passive_conds = passive.get('conditions', {})
    if (passive_conds
            and _hand_cost_conditions_match(p, opp, card, passive_conds)):
        for step in passive.get('steps', []):
            if step.get('action') == 'debuff_cost' and step.get('target') == 'own_play_self':
                cost -= step.get('amount', 0)
            elif step.get('action') == 'set_play_cost' and step.get('target') == 'own_play_self':
                cost = step.get('amount', cost)
    return max(0, cost)


def consume_play_cost_reductions(p: GameState, card: Card) -> None:
    """Consome buffs one-shot que casam com a carta efetivamente jogada."""
    p.pending_play_cost_reductions = [
        rule for rule in p.pending_play_cost_reductions
        if not _play_cost_rule_matches(card, rule)
    ]


def _norm_type_text(text: str) -> str:
    """Normaliza typos conhecidos vindos do texto bruto da base."""
    return (text or '').lower().replace('whitebeard piratess', 'whitebeard pirates')


def _ko_sentence(card: 'Card') -> str:
    text = ((card.card_text or '') or get_card_flags(card.code).get('text', '')).lower()
    if not text:
        return ''
    text = (text.replace('&lt;', '<').replace('&gt;', '>')
                .replace('＜', '<').replace('＞', '>'))
    cannot_ko = re.search(r"cannot be k\.?o\.?'?d|can't be k\.?o", text)
    if not cannot_ko:
        return ''
    sentence_start = max(text.rfind('.', 0, cannot_ko.start()), text.rfind('\n', 0, cannot_ko.start()))
    sentence_end = text.find('.', cannot_ko.end())
    if sentence_end == -1:
        sentence_end = len(text)
    return text[sentence_start + 1:sentence_end]


def _source_matches_battle_ko_immunity(sentence: str, source_card: Optional['Card']) -> bool:
    if not source_card:
        return True

    src_type = (source_card.card_type or '').upper()
    src_attr = (source_card.attribute or '').lower()

    if 'by leaders' in sentence:
        return src_type == 'LEADER'
    if 'by characters without' in sentence and 'special' in sentence:
        return src_type == 'CHARACTER' and 'special' not in src_attr
    if 'by attribute cards' in sentence:
        return bool(src_attr)

    for attr in ('strike', 'slash', 'special', 'wisdom', 'ranged'):
        if attr in sentence and re.search(rf'by [^.]*(?:<|")?{attr}(?:>|")?[^.]*attribute', sentence):
            return attr in src_attr

    return True


def _ko_immunity_applies_to_context(card: 'Card', ko_context: str | None,
                                    source_card: Optional['Card'] = None) -> bool:
    if ko_context not in ('battle', 'effect'):
        return True

    sentence = _ko_sentence(card)
    if not sentence:
        return True

    battle_only = 'in battle' in sentence
    effect_only = 'by effect' in sentence or "by your opponent's effect" in sentence
    if ko_context == 'battle' and effect_only and not battle_only:
        return False
    if ko_context == 'effect' and battle_only and not effect_only:
        return False
    if ko_context == 'battle' and not _source_matches_battle_ko_immunity(sentence, source_card):
        return False
    return True


def is_immune(card: 'Card', imm_type: str, owner: 'GameState', opp: 'GameState',
              source_is_opp: bool = True, ko_context: str | None = None,
              source_card: Optional['Card'] = None) -> bool:
    """
    True se `card` está imune a `imm_type` ('ko' | 'removal' | 'rest') no
    estado atual. 'rest': autoproteção contra rest forçado por efeito do
    oponente (achado 01/07/2026, OP11-046/OP12-021/OP15-024) -- DISTINTA de
    `cannot_be_rested_until` (trava posta por OUTRA carta via
    `lock_opp_cannot_be_rested`, já checada separadamente).

    Lê a action 'immunity' nos effects da carta (parseada como passive/opp_turn/
    don_conditional). Respeita:
      - source: imunidade "by opponent's effects" (source='opp') só vale quando
        a remoção/KO VEM do oponente (source_is_opp=True). Imunidade 'any' sempre.
      - condição de DON: imunidade sob [DON!! xN] só vale com N DON anexados.
      - condição de turno: imunidade [Opponent's Turn] só vale no turno do oponente
        (= NÃO é o turno do dono da carta).
    KO em batalha vs por efeito: 'ko' cobre ambos aqui (o banco não distingue
    "in battle" vs "by effect" nas 68 cartas — todas são "cannot be K.O.'d").
    """
    effects = get_card_effects(card.code)
    for timing, blk in effects.items():
        if not isinstance(blk, dict):
            continue
        for step in blk.get('steps', []):
            if step.get('action') != 'immunity' or step.get('imm_type') != imm_type:
                continue
            if imm_type == 'ko' and not _ko_immunity_applies_to_context(card, ko_context, source_card):
                continue
            # source
            if step.get('source') == 'opp' and not source_is_opp:
                continue
            # "cannot be K.O.'d by effects of your opponent's Characters
            # with N (base) power or less" -- imunidade filtrada pela
            # FORCA da fonte (achado 19/07, OP14-003): so protege quando a
            # fonte e um Character conhecido com power <= limiar; fonte
            # desconhecida (None) ou mais forte que o limiar NAO conta
            # como imune.
            src_power_lte = step.get('source_power_lte')
            if src_power_lte is not None:
                if source_card is None or source_card.power > src_power_lte:
                    continue
            # condição de turno: [Opponent's Turn] só no turno do oponente
            if timing == 'opp_turn' and owner is _current_turn_owner(owner, opp):
                continue
            # condição de DON anexado ([DON!! xN])
            don_req = blk.get('don_requirement', 0)
            if don_req and getattr(card, 'don_attached', 0) < don_req:
                continue
            # condições estruturadas (If all DON rested, If life <= N, etc)
            conds = blk.get('conditions') or step.get('conditions')
            if conds and not _immunity_conds_met(conds, card, owner, opp):
                continue
            return True
    # Imunidade TEMPORARIA concedida via grant_ko_immunity_type (ex: OP09-033
    # Nico Robin). Campo immunity_ko_until no Card, setado pelo engine quando
    # o efeito e executado e limpo no refresh_phase do DONO da carta.
    if imm_type == 'ko' and getattr(card, 'immunity_ko_until', ''):
        if source_is_opp:  # imunidade valida contra efeitos do oponente
            return True
    # Aura PERMANENTE concedida por OUTRA carta no campo (distinta do
    # grant_ko_immunity_type acima, que e uma concessao TEMPORARIA
    # disparada por um step com duracao). Achado 19/07, OP08-029 Pekoms:
    # "If this Character is active, your {Minks} type Characters with a
    # cost of 3 or less other than [Pekoms] cannot be K.O.'d by effects"
    # -- vale enquanto a carta-fonte estiver em campo (e ativa, se
    # self_active_required), sem duracao/expiracao.
    if imm_type == 'ko':
        for other in owner.field_chars:
            if other is card:
                continue
            passive = get_card_effects(other.code).get('passive', {})
            for s in passive.get('steps', []):
                if s.get('action') != 'grant_ko_immunity_aura':
                    continue
                if s.get('self_active_required') and other.rested:
                    continue
                wanted_type = (s.get('filter_type') or '').lower()
                if wanted_type and wanted_type not in (card.sub_types or '').lower():
                    continue
                cost_lte = s.get('cost_lte')
                if cost_lte is not None and card.cost > cost_lte:
                    continue
                exclude = (s.get('exclude') or '').lower()
                if exclude and exclude in card.name.lower():
                    continue
                return True
    return False


def _current_turn_owner(owner, opp):
    """Heurística leve: quem tem o turno. owner.turn é incrementado no play_turn
    do jogador ativo, então comparamos quem agiu por último. Conservador:
    se indeterminado, retorna None (imunidade de opp_turn vale)."""
    # Sem um flag global de turno acessível aqui, usamos a convenção de que
    # durante a resolução de um ataque, o atacante é opp e o defensor é owner.
    # Para imunidade [Opponent's Turn] do defensor, é o turno do oponente => vale.
    return None


def _immunity_conds_met(conds, card, owner, opp):
    if 'all_don_rested' in conds:
        if owner.don_available > 0:
            return False
    if 'life_lte' in conds:
        if len(owner.life) > conds['life_lte']:
            return False
    if 'life_gte' in conds:
        if len(owner.life) < conds['life_gte']:
            return False
    if 'only_field_type' in conds:
        tipo = conds['only_field_type'].lower()
        if not owner.field_chars or any(tipo not in c.sub_types.lower() for c in owner.field_chars):
            return False
    # Achado 15/07 (OP12-021 Ipponmatsu, "If your Leader has the (Slash)
    # attribute and you have 6 or more rested DON!! cards..."): a imunidade
    # aplicava sempre porque _immunity_conds_met (checador DEDICADO desta
    # funcao, distinto de _check_conditions usado por on_play/main/trigger)
    # nunca tinha esses 2 campos, mesmo com parse_conditions ja gerando-os.
    if 'leader_attribute' in conds:
        my_attr = (getattr(owner.leader, 'attribute', '') or '').lower()
        if conds['leader_attribute'].lower() not in my_attr:
            return False
    if 'don_rested_gte' in conds:
        if owner.don_rested < conds['don_rested_gte']:
            return False
    # "if your opponent has a Leader or Character with a (base) power of N
    # or more" (achado 16/07, OP06-012, ordem invertida "power of N") --
    # distinta de opp_char_power_gte (so campo, checado em _check_conditions
    # noutro lugar): aqui inclui TAMBEM o lider do oponente.
    if 'opp_leader_or_char_power_gte' in conds:
        threshold = conds['opp_leader_or_char_power_gte']
        candidatos = [opp.leader] + list(opp.field_chars)
        if not any(c.power >= threshold for c in candidatos):
            return False
    if 'no_other_named' in conds:
        needle = conds['no_other_named'].lower()
        cost_eq = conds.get('no_other_named_cost_eq')
        outros = [c for c in owner.field_chars
                  if c is not card and needle in c.name.lower()]
        if cost_eq is not None:
            outros = [c for c in outros if c.cost == cost_eq]
        if outros:
            return False
    return True


def is_attack_locked_self(card: 'Card', owner: 'GameState', opp: 'GameState') -> bool:
    """
    True se `card` esta travada para atacar por um efeito PASSIVO PROPRIO
    (cannot_attack_self / cannot_attack_self_unless /
    cannot_attack_own_characters_by_cost), distinto de cannot_attack_until
    (que e trava posta por OUTRA carta via lock_opp_character_attack e ja
    e checada separadamente nos mesmos 6 pontos). Centraliza a logica aqui
    em vez de duplicar em GameAnalyzer/OPTCGMatch -- ambas as classes tem
    acesso a um GameState do dono e um do oponente em todo ponto que
    precisa decidir "esta carta pode atacar?".

    Condicoes suportadas (mesmo vocabulario de _check_conditions, mas
    replicado aqui de forma minima -- so os campos que cannot_attack_self_*
    de fato usa no banco hoje: board_has_power_gte,
    opp_chars_power_gte_count). Se 'conditions' nao foi reconhecida pelo
    parser (campo legado 'condition_text' presente em vez de 'conditions'),
    trata como travado SEMPRE -- mais seguro assumir o lock ativo do que
    liberar o ataque sem confirmar a condicao real.
    """
    # "This Character's effect is negated during this turn" (OP06-083,
    # OP14-056): a UNICA passiva propria dessas cartas e cannot_attack_self,
    # entao negar "o efeito desta carta" libera o ataque ate o fim do
    # turno. Checado ANTES do loop de passive abaixo.
    if getattr(card, 'own_effect_negated_this_turn', False):
        return False

    effects = get_card_effects(card.code)
    passive = effects.get('passive', {})
    # Achado real 03/08 (mesma investigacao do 'cannot attack' de lider):
    # `passive.conditions` (condicao do BLOCO inteiro, ex: Monkey.D.Luffy
    # OP11-058 "If you have 5+ cards in hand, this Character cannot
    # attack" -- vira {'hand_gte': 5} no nivel do bloco, nao dentro do
    # step) nunca era checado aqui pro step 'cannot_attack_self' simples
    # (so 'cannot_attack_self_unless' tinha condicao, embutida no PROPRIO
    # step). Resultado: Luffy(058) ficava travado pra atacar SEMPRE, mesmo
    # com mao < 5 (quando a trava real do jogo nao se aplica) -- o oposto
    # do bug do lider (aqui trava DEMAIS, la nao travava nada). Reusa
    # EffectExecutor._check_conditions (fonte unica ja usada em todo o
    # resto do motor) em vez de reimplementar mais um vocabulario de
    # condicoes ad-hoc aqui.
    block_conds = passive.get('conditions', {})
    if block_conds and not EffectExecutor(owner, opp)._check_conditions(block_conds, card):
        passive = {}  # condicao do bloco nao satisfeita -- nenhum step dele se aplica agora
    for step in passive.get('steps', []):
        action = step.get('action')
        if action == 'cannot_attack_self':
            return True
        if action == 'cannot_attack_self_unless':
            if 'condition_text' in step and 'conditions' not in step:
                return True  # condicao nao estruturada -- trava por seguranca
            conds = step.get('conditions', {})
            if 'board_has_power_gte' in conds:
                todos = list(owner.field_chars) + list(opp.field_chars)
                if not todos or max(c.effective_power(True) for c in todos) < conds['board_has_power_gte']:
                    return True  # condicao NAO satisfeita -> travada
            if 'opp_chars_power_gte_count' in conds:
                spec = conds['opp_chars_power_gte_count']
                n = sum(1 for c in opp.field_chars if c.effective_power(False) >= spec['power_gte'])
                if n < spec['count']:
                    return True
            # alguma condicao reconhecida e satisfeita (ou nenhuma condicao
            # suportada presente, caso futuro) -- nao trava.
    # mass_lock_conditional e um efeito de OUTRA carta no board (ex: P-084)
    # que trava `card` por filtro de custo -- precisa varrer todo o board
    # do dono (characters + leader) procurando alguma fonte com esse
    # trigger ativo, e nao apenas os efeitos da propria `card` sendo
    # avaliada (P-084 trava as OUTRAS cartas custo 3/4, nao trava P-084
    # nela mesma via este trigger -- P-084 se trava via cannot_attack_self
    # incondicional, ja checado acima).
    fontes_mass_lock = list(owner.field_chars) + [owner.leader]
    for fonte in fontes_mass_lock:
        fonte_effects = get_card_effects(fonte.code)
        mass_lock = fonte_effects.get('mass_lock_conditional')
        if not mass_lock:
            continue
        conds = mass_lock.get('conditions', {})
        leader_is = conds.get('leader_is', '').lower()
        if leader_is and leader_is not in owner.leader.name.lower():
            continue
        costs_alvo = set()
        for s in mass_lock.get('steps', []):
            if s.get('action') == 'cannot_attack_own_characters_by_cost':
                costs_alvo.update(s.get('costs', []))
        if card.cost in costs_alvo:
            return True
    return False


def can_afford_attack_paywall(card: 'Card', owner: 'GameState') -> bool:
    """
    True se `card` PODE atacar apesar de ter `attack_paywall` ativo
    (lock_opp_attack_unless_pays, ex: OP08-043 Edward.Newgate) -- ou se nao
    tem paywall nenhum. Simplificacao deliberada: paga sempre que pode (nao
    modela "vale a pena" como Opponent Reading faria), mesmo padrao do resto
    do engine pra custos de ativacao (so checa viabilidade material).
    """
    paywall = card.attack_paywall
    if not paywall:
        return True
    if paywall.get('cost_type') == 'trash_from_hand':
        return len(owner.hand) >= paywall.get('cost_amount', 1)
    return True


def character_can_attack_now(card: 'Card', owner: 'GameState', opp: 'GameState') -> bool:
    """True if a field character can be offered as an attacker right now."""
    if getattr(card, 'rested', False):
        return False
    if getattr(card, 'cannot_attack_until', False):
        return False
    if getattr(card, 'cannot_be_rested_until', False):
        return False
    if (getattr(card, 'just_played', False)
            and not (card.is_rush()
                     or card.is_rush_character()
                     or getattr(card, 'rush_character_only_this_turn', False))):
        return False
    if is_attack_locked_self(card, owner, opp):
        return False
    if not can_afford_attack_paywall(card, owner):
        return False
    return True


def active_taunt_character(defender: 'GameState', attacker_side: 'GameState') -> 'Card | None':
    """Retorna o Character do `defender` com `force_opp_attack_self` ativo
    AGORA (condicoes + don_requirement batendo) -- se existir, QUALQUER
    ataque de `attacker_side` neste momento so pode mirar essa carta
    (nem o Leader, nem outro Character). Achado 05/08 (Eustass Kid
    OP01-051, Captain John OP17-044, mecanica de "taunt" antes ausente
    do engine). Fonte unica: reusa `EffectExecutor._check_conditions`
    (mesmo predicado usado por qualquer outro efeito condicional), nao
    reimplementa a checagem de condicao a mao."""
    ee = EffectExecutor(defender, attacker_side)
    for c in defender.field_chars:
        effects = get_card_effects(c.code)
        for block in effects.values():
            if not isinstance(block, dict):
                continue
            if not any(s.get('action') == 'force_opp_attack_self'
                       for s in block.get('steps', [])):
                continue
            don_req = block.get('don_requirement', 0)
            if don_req and getattr(c, 'don_attached', 0) < don_req:
                continue
            if not ee._check_conditions(block.get('conditions', {}), c):
                continue
            return c
    return None


def _step_matching_targets(step: dict, chars: list) -> int:
    """Quantos personagens de `chars` passam nos FILTROS do step
    (cost_lte/gte/eq, power_lte/gte, rested_only, filter_type)."""
    n = 0
    for c in chars:
        if step.get('cost_lte') is not None and c.cost > step['cost_lte']:
            continue
        if step.get('cost_gte') is not None and c.cost < step['cost_gte']:
            continue
        if step.get('cost_eq') is not None and c.cost != step['cost_eq']:
            continue
        if step.get('power_lte') is not None and c.power > step['power_lte']:
            continue
        if step.get('power_gte') is not None and c.power < step['power_gte']:
            continue
        if step.get('rested_only') and not getattr(c, 'rested', False):
            continue
        filters = step.get('filter_types') or []
        ft = (step.get('filter_type') or '').lower()
        if ft:
            filters = [ft]
        if filters and not any(str(f).lower() in c.sub_types.lower() for f in filters):
            continue
        n += 1
    return n


def _on_ko_play_card_value(step: dict, owner: 'Optional[GameState]') -> float:
    """
    Valor do step play_card/play_from_trash de um on-KO: só conta se
    existir alvo de verdade na mão/trash do DONO da carta, e escala pelo
    valor situacional da melhor carta elegível — não um bônus fixo.

    Achado 07/07: partida real teve o Avalo Pizarro (on-KO: draw + play até
    1 Fullalead da mão/trash) escolhido como sacrifício do redirect do Teach
    em vez do Vasco Shot (on-KO: draw + restar personagem <= custo 6 do
    oponente, com o Kuma do oponente em campo como alvo real). O Fullalead
    já tinha sido jogado antes (nenhum alvo disponível), mas o bônus fixo de
    30 não sabia disso — Pizarro (15+30=45 fantasma) venceu o Vasco Shot
    (25+15=40 real) por pontos que não existiam.
    """
    if owner is None:
        return 30.0   # sem GameState do dono para checar — mantém o antigo
    from optcg_engine.rules_facade import eligible_cards
    cost_lte = step.get('cost_lte')
    if cost_lte == 99:   # "até custo X" usado como "sem limite" no parser
        cost_lte = None
    fontes = [owner.hand]
    if step.get('source_alt') == 'trash':
        fontes.append(owner.trash)
    elegiveis = []
    for fonte in fontes:
        elegiveis.extend(eligible_cards(
            fonte, cost_lte=cost_lte,
            name_or_code=step.get('filter_names') or step.get('filter_name', ''),
            filter_text=step.get('filter_type', ''), color=step.get('color', ''),
            exclude_name=step.get('exclude', ''),
        ))
    if not elegiveis:
        return 0.0   # sem alvo — jogar no vácuo não vale nada
    melhor = max(elegiveis, key=lambda c: c.board_value())
    return min(30.0, 12.0 + melhor.board_value() * 2.0)


def resolve_choice_for_scoring(block: dict, card: 'Card', me: 'GameState', opp: 'GameState') -> list:
    """
    Steps 'efetivos' de um bloco de efeito PRA FINS DE AVALIAÇÃO (scoring/
    viabilidade), não execução: `block['steps']` diretos quando existem,
    ou -- se vazios e o bloco usa "Choose one" (`choice`, uma lista de
    ramos alternativos) -- os steps do ramo de maior valor heurístico
    entre os viáveis agora, via `EffectExecutor._resolve_choice` (MESMA
    função que a execução real já usa pra resolver a escolha de verdade,
    sem duplicar heurística).

    Achado real 03/08 (usuário pediu pra investigar se o bot sabe ativar
    o efeito de cada líder/deck, testando ativação de líder): toda função
    de scoring do motor (`_score_activate_main`, as flags condicionais de
    `avaliar_carta`, `_rest_only_attack_value`, etc.) lia `bloco.get(
    'steps', [])` direto -- pra QUALQUER carta cujo efeito seja "Choose
    one" (guardado em `choice`, não em `steps`), isso sempre vinha vazio,
    fazendo o motor pontuar a ativação/carta como se o efeito não
    fizesse NADA. Achado no banco inteiro (não só líder): 23 cartas
    (líderes, personagens, eventos) em 5 gatilhos diferentes
    (`on_play`/`main`/`activate_main`/`when_attacking`/`on_ko`) têm esse
    padrão -- ex: líder Perona OP06-021, Vegapunk OP07-097, King
    OP08-057 (activate_main pontuava 60 fixo em vez do valor real de
    "compre 1 carta"/"jogue carta de graça").
    """
    steps = block.get('steps')
    if steps:
        return steps
    choice = block.get('choice')
    if not choice:
        return []
    return EffectExecutor(me, opp)._resolve_choice(choice, card, block.get('choice_chooser', 'self'))


def on_ko_value(code: str, opp: 'Optional[GameState]' = None,
                owner: 'Optional[GameState]' = None) -> float:
    """
    Valor dos efeitos [On K.O.] de uma carta — o que GANHAMOS se ela morrer.
    Usado para escolher sacrifícios (ex: redirect do Teach). Escala
    compatível com char_value_score.

    Os FILTROS dos steps são aplicados contra o campo REAL do oponente
    (partida 04/07: Doc Q "KO até 2 de custo <= 1" foi escolhido com o
    oponente sem nenhum custo <= 1 — morreu por um draw seco; o Vasco Shot,
    cujo rest custo <= 6 tinha alvo, era o sacrifício certo).

    `owner` (opcional): GameState de quem é dono da carta — usado só para
    validar play_card/play_from_trash contra a mão/trash reais dele (ver
    `_on_ko_play_card_value`). Sem `owner`, mantém o bônus fixo antigo.

    `choice` (achado real 03/08): esta função só recebe `code` (não uma
    instância de Card), então não dá pra reusar `resolve_choice_for_scoring`
    (que precisa de um Card pra checar `conditions` via `_check_conditions`
    de verdade). Pra "Choose one" (ex: Pedro OP08-030), pontua CADA ramo
    com a MESMA tabela abaixo e usa o de maior valor -- sem filtrar por
    viabilidade material (não temos o board ao vivo aqui do jeito que
    `_resolve_choice` tem), então superestima um pouco vs. a escolha real
    do jogo, mas é estritamente melhor que tratar o efeito como 0 (o
    comportamento antigo, que ignorava `choice` por completo).
    """
    def _score_steps(steps: list) -> float:
        total = 0.0
        for step in steps:
            action = step.get('action', '')
            count = int(step.get('count', 1) or 1)
            if action in ('ko', 'trash'):
                if opp is None:
                    total += 30 * count
                else:
                    total += 30 * min(count, _step_matching_targets(step, opp.field_chars))
            elif action in ('draw', 'draw_cards'):
                total += 15 * count
            elif action in ('rest_opp', 'rest_opp_character'):
                # restar personagem do oponente nega um ataque/bloqueio — tempo
                # real (partida 04/07: Vasco Shot era o sacrificio certo)
                if opp is None:
                    total += 25 * count
                else:
                    total += 25 * min(count, _step_matching_targets(step, opp.field_chars))
            elif action in ('play_card', 'play_from_trash'):
                total += _on_ko_play_card_value(step, owner)
            elif action == 'debuff_power':
                # enfraquece o oponente -- so vale se sobrar alvo que AINDA vai
                # agir este turno (duration tipicamente 'this_turn'). Achado
                # 07/07: caia no fallback generico (+8) e perdia pro play_card
                # do Pizarro mesmo sem alvo real, e depois de corrigido ainda
                # empatava (23 vs 23) com set_base_power do Sanjuan Wolf, um
                # efeito bem mais forte -- os dois ficavam invisiveis aqui.
                amount = step.get('amount', 0) or 0
                peso = 12 + min(amount / 1000 * 4, 20)
                if opp is None:
                    total += peso
                else:
                    tem_char_ativo = any(not getattr(c, 'rested', False) for c in opp.field_chars)
                    tem_lider_ativo = opp.leader is not None and not getattr(opp.leader, 'rested', False)
                    if tem_char_ativo or tem_lider_ativo:
                        total += peso
            elif action in ('set_base_power', 'buff_power') and 'opp' not in (step.get('target') or ''):
                # buff/fixa poder do NOSSO lado -- swing ofensivo real (ex:
                # Sanjuan Wolf: ate 1 dos nossos vira 7000 de poder este turno)
                amount = step.get('amount', 0) or 0
                total += 15 + min(amount / 1000 * 3, 25)
            elif action in ('life_to_hand', 'send_life_to_hand'):
                total += 10
            else:
                total += 8
        return total

    on_ko_effects = get_card_effects(code).get('on_ko', {})
    steps = on_ko_effects.get('steps')
    if steps:
        return _score_steps(steps)
    choice = on_ko_effects.get('choice')
    if choice:
        return max((_score_steps(opt if isinstance(opt, list) else [opt]) for opt in choice), default=0.0)
    return 0.0


def redirect_option_value(card: 'Card', atk_power: int,
                          opp: 'GameState', engine) -> float:
    """
    Valor LIQUIDO de redirecionar um ataque inimigo para `card` (personagem
    nosso), avaliado caso a caso no campo atual (regra do usuario):
    - sobrevive (poder > atacante): 0 — nada perdido, golpe anulado;
    - morre: on_ko_value - valor da carta. Um Doc Q (on-KO 75, valor ~20)
      da +55: MELHOR que um sobrevivente, porque QUEREMOS o efeito dele.
    """
    if card.power > atk_power:
        return 0.0
    return on_ko_value(card.code, opp, owner=engine.me) - engine.analyzer.char_value_score(card)


def life_redirect_cost(life_count: int) -> float:
    """
    Custo de deixar o golpe (ou mandar o golpe) na VIDA do lider, na mesma
    escala de char_value_score/on_ko_value. Vida alta = barato; cada vida a
    menos pesa mais.
    """
    if life_count >= 4:
        return 15.0
    return {3: 25.0, 2: 45.0, 1: 90.0}.get(life_count, 90.0)


def live_attack_power(attacker: 'Card') -> int:
    """Poder vivo de ataque vindo do jogo, sem projetar When Attacking."""
    atk_override = getattr(attacker, '_attack_power_override', None)
    if atk_override is None:
        return attacker.effective_power(True)
    # powerAtk vem do CardPower(..., attacking=true) do jogo sem DON.
    # Reaplica somente os buffs/custos simulados pelo engine e o DON
    # anexado, mantendo o jogo como fonte da passiva "ao atacar".
    #
    # SEM PISO em 0 aqui: o proprio CardPower do jogo nao pisa (achado
    # confirmado 06/07 -- Doc Q base 0, -2000 do Activate do lider Krieg,
    # fica -2000 vivo de verdade). Pisar ANTES de somar o DON ainda-nao-
    # anexado (em score_attack_target/don_needed_for_attack, que somam
    # don_disp*1000 por cima deste retorno) subestimava o deficit: achava
    # que 9 DON bastavam pra Doc Q -2000 vs Krieg 9000 (0+9000=9000), mas
    # o real e -2000+11000=9000 -- precisa de 11. Log da partida confirma:
    # com 9 DON anexados o combate saiu 7000 (-2000+9000), nunca 9000.
    base = int(atk_override)
    return base + attacker.power_buff + getattr(attacker, 'don_attached', 0) * 1000


def attack_time_power(attacker: 'Card', opp: 'GameState') -> int:
    """
    Poder do atacante NO MOMENTO do ataque: effective_power + buffs próprios
    de [When Attacking] (buff_power em si mesmo, ou set_base_power copiando
    um personagem do oponente — ex: Catarina Devon OP16-104, cuja base vira
    o poder do personagem escolhido). Sem isso o engine subestima esses
    atacantes e barra/superpaga ataques que na prática passam fácil.
    """
    power = live_attack_power(attacker)
    wa = get_card_effects(attacker.code).get('when_attacking')
    if not isinstance(wa, dict):
        return power
    req = wa.get('don_requirement', 0)
    if req and getattr(attacker, 'don_attached', 0) < req:
        return power
    for step in wa.get('steps', []):
        action = step.get('action', '')
        target = step.get('target', 'self')
        if target not in ('self', ''):
            continue
        if action == 'buff_power':
            power += int(step.get('amount', 0) or 0)
        elif action == 'set_base_power' and step.get('source') == 'selected_opp_character':
            if opp.field_chars:
                best = max(c.power for c in opp.field_chars)
                # Modificadores VIVOS do atacante (ex: -2000 do lider Krieg)
                # persistem depois da copia: base nova + mod, nao base crua.
                # _db_base_power e setado pelo server quando o poder vivo
                # difere do banco (partida 06/07: Devon copiou 7000 mas
                # bateu 6000 por causa do -1000 residual e o engine aprovou
                # ataque perdido).
                mod = attacker.power - getattr(attacker, '_db_base_power',
                                               attacker.power)
                ganho = (best + mod) - attacker.power
                if ganho > 0:
                    power += ganho
    return power


def don_needed_for_attack(attacker: 'Card', ttype: str, tgt: 'Optional[Card]',
                          p: 'GameState', opp: 'GameState', engine,
                          don_livre: 'Optional[int]' = None) -> int:
    """
    Quantos DON anexar ao atacante para este ataque (0 = nenhum). Função pura
    — quem anexa de fato é o chamador (_attach_don_for_attack na simulação;
    o plugin do bot via /decide). Duas parcelas distintas:

    1. DÉFICIT BASE (alvo - poder): obrigatório. Sem ele o ataque é
       matematicamente perdido — nunca declarar sem cobrir.
    2. MARGEM DE COUNTER (counter provável do oponente): LUXO. Atacar "seco"
       no empate (5000 vs 5000) é jogada legítima de pressão — força o
       oponente a escolher entre gastar counter/blocker ou perder a carta /
       tomar o dano (regra do usuário, 04/07/2026). A margem só é paga com
       `don_livre`: DON que o plano do turno deixaria OCIOSO depois das
       jogadas pretendidas e da reserva de defesa. don_livre=None mantém o
       comportamento antigo (margem limitada só pelo DON disponível).
    """
    if p.don_available <= 0:
        return 0
    # Achado 04/08 (investigacao Lucy no gauntlet, bloco HANDOFF 434):
    # faltava somar power_buff -- exatamente o que o combate REAL usa em
    # defend_power (_execute_attack, mais abaixo) e o que
    # defender_power_now ja soma corretamente. Sem isso, um lider com
    # buff de defesa ATIVO (ex: Lucy OP15-002, "[On Your Opponent's
    # Attack] trash Event/Stage da mao: +1000 power nesta batalha")
    # ficava invisivel pro calculo de deficit -- o motor achava que
    # bastava empatar no poder BASE (aqui sempre 5000, nunca mudava no
    # trace) enquanto o combate real comparava contra o poder JA
    # bufado (6000-10000 na partida investigada), garantindo que TODO
    # ataque saia sem DON nenhum e apanhe. Mesmo padrao de
    # `opp_counter_potential()` (achado 07/07): defesa que so aparece
    # no momento do combate precisa ser antecipada aqui, nao só o stat
    # parado da carta.
    if ttype == 'leader':
        alvo_power = opp.leader.power + opp.leader.power_buff
    else:
        alvo_power = (tgt.power + tgt.power_buff) if tgt else 0
    atk = attack_time_power(attacker, opp)

    # Achado real 27/07 (bloco HANDOFF 374, Katakuri OP11-062 x Ace):
    # attack_time_power ja soma o buff_power do proprio [When Attacking]
    # (ex: +1000 do Katakuri) como se fosse de graca. Se esse bloco tem
    # custo don_minus, na PIOR hipotese (sem DON sobrando de outra fonte)
    # o custo come um DON recem-anexado pra pagar o proprio buff -- perde
    # 1000 de poder (DON) pra "ganhar" 1000 (buff), liquido ZERO, nao o
    # +1000 assumido no planejamento. Resultado real: anexou 2 DON
    # (5000->7000, planejado 8000 com buff), o custo comeu 1 (->6000),
    # ataque saiu 2000 abaixo do planejado e perdeu pro lider do oponente
    # (8000). Em vez de tentar prever se vai sobrar folga (calculo que
    # colide com o teto de DON disponivel exatamente no caso que importa,
    # don_minus_count=1), assume o PIOR CASO direto: ignora a contribuicao
    # do buff self-canibalizavel no deficit, garantindo DON suficiente
    # mesmo se o custo comer o proprio ganho. Se sobrar DON de outra
    # fonte de verdade, o ataque so sai com poder EXTRA (sobra inofensiva).
    wa = get_card_effects(attacker.code).get('when_attacking')
    buff_liquido_incerto = 0
    if isinstance(wa, dict):
        self_buff_amount = sum(
            int(s.get('amount', 0) or 0) for s in wa.get('steps', [])
            if s.get('action') == 'buff_power' and s.get('target') in ('self', ''))
        don_minus_count = sum(
            int(c.get('count', 1) or 1) for c in wa.get('costs', [])
            if c.get('type') == 'don_minus')
        if self_buff_amount and don_minus_count:
            buff_liquido_incerto = min(self_buff_amount, don_minus_count * 1000)

    falta_base = alvo_power - (atk - buff_liquido_incerto)
    need_base = (falta_base + 999) // 1000 if falta_base > 0 else 0

    if need_base >= p.don_available:
        return min(p.don_available, need_base)

    # Counter REAL da mao do oponente (stat impresso + efeitos [Counter],
    # ex: Ground Death/Never Existed — achado 07/07: um flat "1000 if
    # opp.hand" nunca previa os +4000 desses efeitos). Achado 10/07,
    # simulacao Teach vs Imu (100 partidas, winrate 6.7%): um teto fixo de
    # 2000 aqui fazia o bot atacar sistematicamente "seco demais" contra
    # counters reais de 3000-4000 (Imu tem varios), levando ataque atras de
    # ataque bloqueado com DON ocioso sobrando no campo (visto no trace:
    # "Counter! +3000/+4000 -> defesa 8000/9000", ataque falha, personagens
    # nunca atacam pq so o lider e forte o bastante pra tentar). O teto de
    # 2000 vinha de uma regra de nao "afundar DON demais" -- mas
    # `livre_para_margem` (abaixo) ja e o limitador real: so paga margem
    # com DON que sobraria ocioso mesmo assim, nunca rouba DON do plano do
    # turno. Sem o teto fixo, a margem escala com a ameaca real, nao um
    # numero arbitrario.
    counter_prov = engine.analyzer.opp_counter_potential()
    need_margem = (counter_prov + 999) // 1000

    if don_livre is None:
        don_livre = p.don_available
    # O deficit base deste ataque tambem e gasto OBRIGATORIO do plano —
    # desconta antes de liberar margem (senao a margem rouba DON do plano)
    livre_para_margem = max(0, min(don_livre - need_base,
                                   p.don_available - need_base))
    # Margem PARCIAL vale: don_livre ja exclui plano e reserva, entao esse
    # DON esta OCIOSO — anexar e pressao gratis (força o oponente a pagar
    # mais counter para negar; visto em partida real 06/07: bot passou o
    # turno com 1 DON parado e atacou 5000 seco em vez de 6000).
    # ATTACK_MARGIN_DON_FRACTION (< 1.0): reduz quanto dessa margem "gratis"
    # e de fato anexada, sem tocar no deficit base (need_base, obrigatorio).
    margem = int(min(need_margem, livre_para_margem) * ATTACK_MARGIN_DON_FRACTION)
    return need_base + margem


def remove_by_identity(lst: list, obj) -> bool:
    """
    Remove de `lst` EXATAMENTE o objeto `obj` (comparando por identidade,
    `is`, nunca por __eq__ de valor). Retorna True se removeu.

    Necessario porque `Card` e um @dataclass SEM eq=False -- __eq__ e
    auto-gerado por VALOR (todos os campos), de proposito: `_remap_action`
    (linha ~5064) depende disso pra mapear uma acao do estado real pro
    clone via deepcopy do Turn Planner (`p.hand.index(obj)` so funciona
    cruzando a fronteira real->clone se a comparacao for por valor, ja que
    objetos pos-deepcopy nunca sao `is` o original). MUDAR Card pra
    eq=False quebraria isso (todo `_remap_action` passaria a sempre
    falhar com ValueError, zerando a pontuacao de toda acao simulada).

    Mas isso significa que `list.remove(card)`/`card in lista` DENTRO de
    um UNICO estado (sem cruzar real/clone) sao AMBIGUOS quando 2+ copias
    fisicas da mesma carta com o MESMO estado (recem compradas, por
    exemplo) coexistem na mesma zona -- list.remove()/in casam a PRIMEIRA
    ocorrencia "igual", nao necessariamente o objeto exato passado.
    Achado 28/06/2026 via auditoria de partida real instrumentada
    (replay_optcg.py + checagem de conservacao de DON): uma carta
    ("St. Topman Warcury", 2 copias na mao com estado identico) foi jogada
    -- e devido a esse bug, a copia "errada" ficou removida da mao,
    deixando a copia REALMENTE jogada ainda la; numa iteracao posterior do
    Turn Planner ela foi selecionada e jogada DE NOVO, resultando no MESMO
    objeto Card duas vezes em field_chars (inflando board_value e DON
    summado). Usar esta funcao em qualquer remocao DENTRO do mesmo estado
    corrige isso sem tocar em `_remap_action`.
    """
    for i, x in enumerate(lst):
        if x is obj:
            del lst[i]
            return True
    return False


def contains_identity(lst: list, obj) -> bool:
    """`obj in lista`, mas por identidade (`is`) -- ver remove_by_identity."""
    return any(x is obj for x in lst)


def pop_by_identity(lst: list, obj: 'Card') -> 'Card':
    """
    Remove `obj` de `lst` por identidade e RETORNA o objeto efetivamente
    removido -- via `lst.pop(idx)`, nunca `del lst[idx]`/`remove_by_identity`.

    Achado real 03/08 (bug de conservacao de DON, blocos 374/377/410/420/
    422/423 -- causa raiz nunca encontrada apesar de auditoria extensa):
    `_SimDeck` (linha ~261, usado por `_simulate_sequence_once` pra clonar
    o deck sem deepcopiar ~82 Cards) so protege contra corrupcao quando a
    remocao usa `.pop()` (unico metodo sobrescrito, faz deepcopy sob
    demanda). `play_from_deck`/`search_deck`/o `add_to_hand` de busca/
    `trash_from_looked_deck` removiam do deck via `remove_by_identity`
    (usa `del lst[i]`, NUNCA `.pop()`) -- durante simulacao do Turn
    Planner, isso retornava/reusava o objeto Card ORIGINAL (mesma
    referencia do deck REAL, ja que `_SimDeck` so envolve a LISTA, os
    elementos dentro sao as MESMAS instancias ate serem retiradas via
    `.pop()`), que entao ia pro campo/mao SIMULADOS mas TAMBEM continuava
    sendo, por identidade, o mesmo objeto do deck real -- qualquer DON!!
    anexado a ele numa linha hipotetica (nunca realmente jogada) vazava
    permanentemente pro estado real, aparecendo como "DON fantasma" so
    quando essa MESMA carta fosse comprada/jogada de verdade turnos
    depois. Confirmado via instrumentacao direta (script descartavel):
    `St. Ethanbaron V. Nusjuro` corrompida (`don_attached=1`) AINDA NO
    DECK real no turno 3, antes de qualquer ativacao real de Empty
    Throne -- so podia ter vindo de uma simulacao (Monte Carlo) que
    jogou essa carta hipoteticamente e nunca desfez a mutacao.

    Fonte unica: qualquer remocao de `me.deck`/`p.deck`/`opp.deck` que
    precise do objeto removido (pra por em field_chars/hand/trash) deve
    usar esta funcao, nunca `remove_by_identity` direto no deck.
    """
    for i, x in enumerate(lst):
        if x is obj:
            return lst.pop(i)
    raise ValueError('pop_by_identity: objeto nao encontrado na lista')


def remove_character_from_field(owner: 'GameState', card: 'Card', destino: str = 'trash') -> None:
    """
    Remove `card` de owner.field_chars e move pro destino indicado:
    'trash' | 'hand' | 'deck_bottom' | 'deck_top' | 'life_top' | 'life_bottom'.

    Regra oficial (comprehensive rules -- "When a Character with DON!!
    card(s) Leaves the Field"): qualquer DON anexado volta para a area
    de custo do DONO da carta (NUNCA de quem causou a remocao) e fica
    RESTED. Auditoria 27/06 encontrou esse retorno faltando em 12 pontos
    diferentes do engine (combate, KO por efeito, bounce, substituicao
    de custo, troca por campo-cheio), e mais 1 ponto (gain_life
    source='own_field', Kawamatsu OP06-103) achado ao corrigir essa
    mesma carta -- usava field_chars.pop(0) direto, fora do grep original
    (procurava so '.remove(', nao '.pop('). Esta funcao e o UNICO ponto
    que deve remover um Character do campo a partir de agora; nunca fazer
    owner.field_chars.remove(card)/pop(...) direto em codigo novo.
    """
    remove_by_identity(owner.field_chars, card)
    if card.don_attached > 0:
        owner.don_rested += card.don_attached
        card.don_attached = 0
    if destino == 'trash':
        owner.trash.append(card)
    elif destino == 'hand':
        card.rested = False
        owner.hand.append(card)
    elif destino == 'deck_bottom':
        card.rested = False
        owner.deck.insert(0, card)   # fundo do deck = início da lista
    elif destino == 'deck_top':
        card.rested = False
        owner.deck.append(card)
    elif destino == 'life_bottom':
        card.rested = False
        owner.life.insert(0, card)
    elif destino == 'life_top':
        card.rested = False
        owner.life.append(card)   # fim da lista = topo da vida (mesma convencao do deck)


# ===========================================================================
# EffectExecutor — único ponto de execução de efeitos
# Baseado no DoV3ActionStep das 34k linhas
# ===========================================================================

class EffectExecutor:
    """
    Executa efeitos de cartas conforme o banco card_effects_db.json.
    Cada 'action' corresponde a um efeito do DoV3ActionStep das 34k linhas.
    """

    def __init__(self, me: GameState, opp: GameState):
        self.me = me
        self.opp = opp
        self._once_used: set = set()  # (card_code, trigger)
        self._last_selected: Optional[Card] = None  # ver execute()
        self._is_my_turn = True  # ver execute() (contexto do [Your Turn][On Play])
        self._decision_engine_cache: Optional['DecisionEngine'] = None

    def reset_once_per_turn(self):
        self._once_used.clear()

    def _de(self) -> 'DecisionEngine':
        """
        DecisionEngine(self.me, self.opp) cacheado por instancia -- achado
        real 03/08 (usuario pediu pra investigar hot spots de performance,
        pos-fix do bloco 426): `_trash_value` criava um DecisionEngine NOVO
        a CADA carta comparada em `_choose_to_trash` (`min(hand, key=self.
        _trash_value)`), o que invalidava o cache de instancia de
        `posture()`/`_lethal_search()` (que so ajuda DENTRO da vida de UMA
        instancia) a cada carta -- profiling real mostrou 8102 recomputos
        de `_posture_uncached` numa unica partida, a maioria vindo daqui.
        Seguro reusar: `self.me`/`self.opp` sao fixos depois do construtor
        (mesmo invariante ja documentado em DecisionEngine.posture()),
        EffectExecutor tambem nunca reatribui os dois depois do __init__.
        """
        if self._decision_engine_cache is None:
            self._decision_engine_cache = DecisionEngine(self.me, self.opp)
        return self._decision_engine_cache

    def _reveal_from_hand_matches(self, cost: dict) -> list:
        """
        Cartas da mao que casam o filtro de um custo `reveal_from_hand`
        (tipo/power_eq/card_type). Extraido de `_pay_costs` (02/08) pra
        virar FONTE UNICA reusada tambem por `_worth_paying_optional_costs`
        -- antes so `_pay_costs` checava se existiam candidatos suficientes
        (no momento de PAGAR); `_worth_paying_optional_costs` (a decisao de
        ACEITAR o custo opcional, chamada pelo caminho ao vivo via
        `resolve_optional_effect`) nunca validava isso, so julgava se o
        efeito tinha alvo. Achado real 02/08 (log Portgas.D.Ace-R x
        Crocodile-B, 2026-08-02): Edward Newgate (OP16-003) "reveal 2
        Character cards com 8000 power" foi ACEITO pelo bot ao vivo com so
        1 carta na mao batendo o filtro (Marco, OP16-014) -- custo
        impagavel, o jogo ficou preso pedindo "Select 2 More Friendly
        Targets" que nunca completava (nao existe 2a carta valida).

        filter_type pode ser uma LISTA (OR de N tipos, achado 19/07,
        OP14-105: "reveal 3 {Amazon Lily} or {Kuja Pirates} type cards
        from your hand") -- string unica preserva o comportamento antigo.
        """
        filter_type_raw = cost.get('filter_type') or ''
        tipos_reveal = ([_norm_type_text(x) for x in filter_type_raw]
                        if isinstance(filter_type_raw, list)
                        else [_norm_type_text(filter_type_raw)])
        power_eq = cost.get('power_eq')
        card_type_req = cost.get('card_type')
        return [
            c for c in self.me.hand
            if (not any(tipos_reveal) or any(
                tp and tp in _norm_type_text(c.sub_types or '') for tp in tipos_reveal))
            and (power_eq is None or c.power == power_eq)
            and (not card_type_req or c.card_type == card_type_req)
        ]

    def _step_is_viable(self, step: dict, card: Card) -> bool:
        """
        Diz se um step PRODUZIRÁ efeito real no estado atual. Usado para não
        pagar custo de um efeito que não vai fazer nada (decisão 25/06: ampla
        — minimiza jogadas-erro). Default seguro: action desconhecida = viável
        (não aborta por engano). Só retorna False quando há CERTEZA de que o
        step é inócuo agora (falta material: alvo, carta na zona, deck vazio).
        """
        a = step.get('action', '')
        me, opp = self.me, self.opp

        # Condicao com escopo do proprio step deve participar da viabilidade
        # ANTES do pagamento. Sem isto, o executor pagaria custos para um
        # beneficio que _execute_step descartaria logo depois.
        if step.get('conditions') and not self._check_conditions(step['conditions'], card):
            return False

        # Efeito cuja fonte e "escolha 1 personagem do oponente" (ex: Catarina
        # Devon [When Attacking] "select up to 1 opponent Character, copia o
        # poder dele") -- sem NENHUM personagem no campo do oponente, o step
        # nao produz nada (fica no poder base). Achado real 10/07: sem essa
        # checagem, _rest_activates_effect() achava que atacar SEMPRE valia
        # a pena (so por ter [When Attacking]), mesmo com campo do oponente
        # vazio -- o bot atacava com 3000 de poder puro contra um lider de
        # 5000, sem chance de passar e sem nenhum beneficio.
        if step.get('source') == 'selected_opp_character':
            return bool(opp.field_chars)

        # ── Efeitos que precisam de ALVO no oponente ──────────────────────────
        if a in ('ko', 'rest_opp_character', 'debuff_power', 'debuff_cost',
                 'bounce', 'lock_opp_character_refresh', 'lock_opp_character_attack',
                 'opp_trash_from_hand', 'place_opp_character_bottom_deck'):
            if a == 'opp_trash_from_hand':
                return len(opp.hand) > 0
            # Alvo e o STAGE do oponente, nao personagem (ex: Never Existed
            # OP13-098, "KO up to 1 opponent's Stage cost<=7") -- achado real
            # 11/07 (log 00.49.30): a checagem generica abaixo olhava
            # field_chars e dava viavel com o oponente SEM stage nenhum; o
            # evento foi jogado no vacuo (1 DON + a carta, efeito nulo).
            if step.get('target') == 'opp_stage':
                stage = getattr(opp, 'field_stage', None)
                if stage is None:
                    return False
                cost_lte = self._resolve_cost_lte(step, default=None)
                return cost_lte is None or stage.cost <= cost_lte
            # Alvo e o LIDER (sempre existe) ou "lider OU personagem" -- o
            # lider sozinho ja cobre a viabilidade, mesma regra do
            # negate_effect logo abaixo (ex: OP05-099, debuff_power
            # target=opp_leader_or_character).
            if step.get('target') in ('opp_leader', 'opp_leader_or_character'):
                return True
            from optcg_engine.rules_facade import eligible_cards
            cost_lte = self._resolve_cost_lte(step, default=None)
            # Achado real 26/07 (bloco HANDOFF 372, Krieg OP15-001 -- usuario
            # reportou "nao entende o efeito do lider"): este bloco calculava
            # cost_lte/candidates mas NUNCA os usava -- o return ficava preso
            # dentro do `if a == 'play_from_life_top'` logo abaixo (bloco
            # inserido DEPOIS deste sem ajustar o fluxo), tornando o check de
            # candidatos codigo morto e caindo no fallback `return True` do
            # fim da funcao. Na pratica, TODA a familia (ko/rest_opp_character/
            # debuff_power/debuff_cost/bounce/lock_opp_character_refresh/
            # lock_opp_character_attack/place_opp_character_bottom_deck --
            # 895 ocorrencias no banco de efeitos) sempre era "viavel" mesmo
            # SEM nenhum alvo elegivel no campo do oponente (ex: Krieg exige
            # don_attached_gte=2, quase nunca satisfeito no early game).
            candidates = eligible_cards(
                opp.field_chars,
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                don_attached_gte=step.get('don_attached_gte'),
                rested_only=step.get('rested_only', False),
                active_only=(a == 'rest_opp_character'),
                filter_text=step.get('filter_type', ''),
                exclude_name=step.get('exclude', ''),
            )
            if candidates:
                return True
            # alt_target (ex: OP03-096 "K.O. 1 Character custo 0, ou o
            # Stage se nao houver"): sem candidato no alvo primario, ainda
            # e viavel se o alvo alternativo existir -- _execute_step ja
            # faz esse fallback, a viabilidade so precisa reconhecer o
            # mesmo caminho (senao aborta ANTES do fallback rodar).
            if step.get('alt_target') == 'opp_stage':
                stage = getattr(opp, 'field_stage', None)
                if stage is not None:
                    alt_cost_lte = step.get('alt_cost_lte')
                    return alt_cost_lte is None or stage.cost <= alt_cost_lte
            return False

        if a == 'play_from_life_top':
            if not me.life:
                return False
            top = me.life[-1]
            if step.get('filter_name') and step['filter_name'].lower() not in top.name.lower():
                return False
            if step.get('filter_type') and _norm_type_text(step['filter_type']) not in _norm_type_text(top.sub_types):
                return False
            if step.get('cost_eq') is not None and top.cost != step['cost_eq']:
                return False
            if step.get('cost_lte') is not None and top.cost > step['cost_lte']:
                return False
            return top.card_type == 'CHARACTER'
        # negate_effect: alvo pode ser opp_leader (sempre existe -- viavel),
        # opp_leader_or_character (idem, lider sempre cobre) ou opp_character
        # (precisa de personagem elegivel, mesmo filtro dos outros acima).
        if a == 'negate_effect':
            target = step.get('target', 'opp_character')
            if target in ('opp_leader', 'opp_leader_or_character'):
                return True
            from optcg_engine.rules_facade import eligible_cards
            cost_lte = self._resolve_cost_lte(step, default=None)
            return bool(eligible_cards(opp.field_chars, cost_lte=cost_lte))
        if a == 'opp_choose_trash_our_hand':
            return len(me.hand) > 0
        if a == 'opp_bounce_own_character':
            cost_lte = step.get('cost_lte')
            return any(cost_lte is None or c.cost <= cost_lte for c in opp.field_chars)

        # ── Jogar carta da mão com filtro ─────────────────────────────────────
        if a == 'play_card':
            if step.get('source') == 'self':
                return contains_identity(me.hand, card)  # GRUPO 1 (trigger): a própria carta
            from optcg_engine.rules_facade import eligible_cards

            # Achado real 06/08 (investigando os casos residuais do
            # Katakuri em audit_real_losses.py): so tratava o sentinela
            # 'don_count_self' na marra, sem passar por _resolve_cost_lte
            # (fonte unica que ja resolve TAMBEM 'don_count_opp', usado por
            # OP08-062 Charlotte Katakuri e P-090 Charlotte Smoothie) --
            # `card.cost > 'don_count_opp'` (str) explodia com TypeError em
            # qualquer chamada que passasse por aqui pra essas 2 cartas
            # (reproduzido via reconstrucao real, TypeError intermitente
            # dependendo da ordem embaralhada do deck). Mesmo bug em MAIS
            # 5 copias da mesma regra de elegibilidade neste arquivo (ver
            # comentario em _should_activate_main, "esta era a TERCEIRA
            # copia" -- na verdade sao pelo menos 6), todas corrigidas
            # juntas nesta sessao.
            cost_lte = self._resolve_cost_lte(step, default=None)
            # "Play 1 [tipo] ..." sem card_type explicito = CHARACTER — mesma
            # regra do _elegivel_para_play (sim_bridge). Achado real 12/07
            # (partida 23.03.36, 3a vez reportado pelo usuario): o EVENTO
            # "The Five Elders Are at Your Service!!!" (custo 1, 'five
            # elders' no NOME) passava neste filtro e o gate do Empty Throne
            # dizia "elegivel" — o jogo so aceita personagem, a ativacao
            # fizzlava (3 DON + stage restados por nada).
            req_type = (step.get('card_type') or 'CHARACTER').upper()
            return bool(eligible_cards(
                [c for c in me.hand if c.card_type == req_type],
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                filter_text=step.get('filter_type', ''),
                # filter_names (lista, ex: PRB02-018/ST13-006) tem
                # prioridade sobre filter_name singular -- os dois nunca
                # coexistem no mesmo step (parser so emite um ou outro).
                name_or_code=step.get('filter_names') or step.get('filter_name', ''),
                color=step.get('color', ''),
                exclude_name=step.get('exclude', ''),
            ))

        # ── Recuperar/jogar de zona que pode estar vazia ──────────────────────
        if a in ('play_from_trash', 'add_from_trash'):
            return len(me.trash) > 0
        if a in ('play_from_deck', 'trash_from_deck_top', 'deck_reorder_rest',
                 'deck_top_rest', 'deck_bottom_rest', 'look_top_deck', 'draw'):
            return len(me.deck) > 0
        if a in ('trash_from_hand', 'life_to_hand', 'hand_to_deck'):
            return len(me.hand) > 0 if a in ('trash_from_hand', 'hand_to_deck') else len(me.life) > 0
        if a == 'trash_own_life':
            return any(c.life_face_up for c in me.life) if step.get('face') == 'up' else len(me.life) > 0
        if a == 'attack_life':
            return len(opp.life) > 0
        if a == 'set_don_active':
            return me.don_rested > 0
        if a in ('peek_life', 'turn_life_face_up', 'turn_life_face_down'):
            owner = opp if step.get('target') == 'opponent' else me
            return len(owner.life) > 0
        if a == 'return_don_until_match_opp':
            return me.don_on_field() > opp.don_on_field()

        # select_grant_rush/select_grant_rush_character: so viavel se existir
        # pelo menos 1 Character PROPRIO elegivel que ENTROU EM CAMPO NESTE
        # TURNO (just_played) e ainda nao tem a permissao -- Rush so importa
        # pra pular a "doenca de invocacao" de quem acabou de entrar; um
        # Character de turno anterior ja ataca normal sem Rush, e um ja
        # rested nao ataca de novo de qualquer forma (correcao do usuario
        # 02/08: "rush só importa para cartas que entram no turno, se a
        # carta já estava lá antes, o rush não faz efeito"; mesmo criterio
        # do fix em _execute_step). Sem esta checagem, a ativacao aparecia
        # como viavel/pontuada mesmo sem NENHUM alvo que se beneficiasse
        # (achado real, lider Ace OP16-001 dando Rush pra Vista, deployada
        # 2 turnos antes e ja rested por ter atacado este turno --
        # ativacao once_per_turn desperdicada por inteiro).
        if a in ('select_grant_rush', 'select_grant_rush_character'):
            from optcg_engine.rules_facade import eligible_cards
            _precisa_de_rush = (character_needs_rush if a == 'select_grant_rush'
                               else character_needs_rush_character)

            if a == 'select_grant_rush' and step.get('filter_name'):
                pool_nome = eligible_cards(me.field_chars, name_or_code=step.get('filter_name', ''))
                pool_tipo = eligible_cards(
                    me.field_chars,
                    filter_text=step.get('filter_type', ''),
                    power_gte=step.get('power_gte'),
                )
                return any(_precisa_de_rush(c) for c in list(pool_nome) + list(pool_tipo))
            candidates = eligible_cards(
                me.field_chars,
                cost_lte=step.get('cost_lte'),
                filter_text=step.get('filter_type', ''),
                name_or_code=step.get('filter_name', ''),
                exclude_name=step.get('exclude', ''),
            )
            return any(_precisa_de_rush(c) for c in candidates)

        # Default: sem material a checar (buff próprio, keyword, add_don,
        # gain_life do deck, etc) = sempre viável.
        return True

    def _resolve_choice(self, options: list, card: Card, chooser: str = 'self') -> list:
        """Escolhe a opcao viavel de maior valor heuristico."""
        if not options:
            return []

        weights = {
            'attack_life': 4,
            'place_opp_character_bottom_deck': 3,
            # Mesmo peso de place_opp_character_bottom_deck -- remocao
            # forte equivalente (achado 16/07, OP05-096: essa acao nunca
            # tinha peso proprio aqui, caia no default=1 igual bounce,
            # subvalorizada na escolha entre as 3 opcoes do "Choose one").
            'place_opp_char_to_opp_life': 3,
            'ko': 2,
            'trash_character': 2,
            'bounce': 1,
            'draw': 1,
            'trash_opp_life': 3,
            'gain_life': 2,
        }

        def choice_step_viable(step: dict) -> bool:
            # Condicao por-OPCAO (ex: OP04-040 Queen -- so pode escolher
            # "add do deck pra Life" SE tambem tiver um Character de custo
            # 8+; sem essa condicao, a opcao nao e nem elegivel). Achado
            # 19/07: nunca checado aqui antes, so viabilidade de material.
            if step.get('conditions') and not self._check_conditions(step['conditions'], card):
                return False
            action = step.get('action', '')
            if action == 'draw':
                return True
            if action == 'gain_life':
                source = step.get('source', 'deck_top')
                if source == 'deck_top':
                    return bool(self.me.deck)
                if source == 'hand':
                    return bool(self.me.hand)
                if source == 'trash':
                    return bool(self.me.trash)
                if source == 'opp_life':
                    return bool(self.opp.life)
            return self._step_is_viable(step, card)

        best_steps = []
        best_score = None
        for option in options:
            steps = option if isinstance(option, list) else [option]
            viable = [s for s in steps if choice_step_viable(s)]
            if not viable:
                continue
            score = sum(weights.get(s.get('action', ''), 1) for s in viable)
            if best_score is None or (score > best_score if chooser != 'opponent' else score < best_score):
                best_score = score
                best_steps = steps

        return best_steps

    def _dispatch_don_given(self, target: Card) -> list[str]:
        logs = []
        for source in [self.me.leader] + list(self.me.field_chars):
            if get_card_effects(source.code).get('on_don_given'):
                logs.extend(self.execute(source, 'on_don_given'))
        return logs

    def execute(self, card: Card, trigger: str, verbose: bool = False, is_opp_turn: bool = False,
                is_my_turn: bool = True, battle_attacker: "Card | None" = None,
                battle_defender_power: "int | None" = None) -> list:
        """
        Executa todos os efeitos de um trigger para uma carta.
        Retorna lista de logs para o replay.

        is_opp_turn: relevante SO para trigger='on_ko' com a condicao
        'opp_turn_only' (gerada para blocos "[Opponent's Turn][On K.O.]",
        7 cards -- ex: EB03-055 Nico Robin). Era gerada pelo parser e NUNCA
        checada (achado em auditoria 27/06) -- o efeito disparava
        incondicionalmente, inclusive no turno do PROPRIO dono. Quem chama
        execute() deve passar True/False conforme o contexto real (ex:
        K.O. por combate = turno de quem ataca = opp_turn_only vale pro
        dono do alvo; K.O. como custo pago pelo proprio jogador = seu
        proprio turno = opp_turn_only NAO vale). Default False (conservador
        -- nao dispara de graca em contexto indeterminado, mesmo principio
        do don_requirement abaixo).

        is_my_turn: relevante SO para trigger='on_play' com a condicao
        'your_turn_only' (gerada para blocos "[Your Turn][On Play]", ex:
        ST22-011 Whitey Bay, EB03-058 Vegapunk -- achado 19/07/2026). O
        parser fundia esse padrao em DOIS blocos identicos ('on_play' e
        'your_turn'), fazendo o efeito disparar ao entrar em campo E
        reaplicar de novo TODO turno seguinte via apply_your_turn_buffs
        (deveria disparar no maximo 1x, e so quando de fato for o turno do
        dono). Default True: a esmagadora maioria dos on_play acontece no
        turno de quem joga a carta (Main Phase normal, ou play_card de
        OUTRO efeito, que so busca a propria mao e sempre resolve no turno
        de quem controla). So os 2 call-sites de resolucao de Trigger de
        vida (dano de combate/fora de combate) passam False explicitamente
        -- ali quem joga a carta e o DEFENSOR, durante o turno do ATACANTE.
        Propagado via self._is_my_turn pra _put_into_play (play_card
        aninhado dentro da resolucao do proprio 'trigger' de vida).
        """
        self._is_my_turn = is_my_turn
        # battle_attacker: quem esta atacando AGORA -- so preenchido pelo
        # call site real de resolucao de batalha (on_opp_attack), consumido
        # por set_base_power/source='opp_attacking_character' (OP04-069).
        # None em qualquer outro contexto (sem batalha em curso).
        self._battle_attacker = battle_attacker
        effects = get_card_effects(card.code)
        if trigger not in effects:
            return []

        # Efeito negado (negate_effect, ex: OP09-093): a carta nao produz
        # NENHUM efeito enquanto a negacao estiver ativa. So bloqueia
        # gatilhos FUTUROS -- nao desfaz um on_play que ja resolveu antes
        # da negacao ser aplicada (execute() e sempre disparo pontual no
        # momento do gatilho, nunca reexecucao de algo passado).
        if getattr(card, 'effects_negated_until', ''):
            return []

        ef_data = effects[trigger]

        # Once per turn
        key = (card.code, trigger)
        if ef_data.get('once_per_turn') and key in self._once_used:
            return []

        # [Opponent's Turn][On K.O.]: so dispara se o K.O. aconteceu de fato
        # no turno do oponente do dono da carta.
        if trigger == 'on_ko' and ef_data.get('conditions', {}).get('opp_turn_only') and not is_opp_turn:
            return []

        # [Your Turn][On Play]: so dispara se for de fato o turno do dono
        # da carta (ver docstring de execute() acima).
        if trigger == 'on_play' and ef_data.get('conditions', {}).get('your_turn_only') and not is_my_turn:
            return []

        # Verifica condições
        if not self._check_conditions(ef_data.get('conditions', {}), card):
            return []

        # [DON!! ×N]: o efeito só ativa se a carta tem N DON anexados.
        # Sem isso, a IA executaria o efeito de graça (vantagem ilegal).
        don_req = ef_data.get('don_requirement', 0)
        if don_req and getattr(card, 'don_attached', 0) < don_req:
            return []

        # VIABILIDADE (conserto estrutural, decisão 25/06): não pagar custo se
        # NENHUM step do efeito vai produzir resultado real no estado atual
        # (ex: "play up to 1" sem carta elegível, "KO 1" sem alvo, mill com deck
        # vazio). Minimiza jogadas-erro nas estatísticas. Só aborta se TODOS os
        # steps forem inviáveis; um único step viável já ativa o efeito.
        steps_all = ef_data.get('steps', [])
        if not steps_all and ef_data.get('choice'):
            steps_all = self._resolve_choice(ef_data.get('choice', []), card, ef_data.get('choice_chooser', 'self'))
        if steps_all and not any(self._step_is_viable(s, card) for s in steps_all):
            return []

        # Custo opcional ("you may pagar X: Y") vale a pena? Aplica em
        # on_play/main -- gatilhos que resolvem automaticamente ao jogar a
        # carta, sem uma etapa de scoring PRÉVIA que já tenha decidido se
        # vale ativar (diferente de activate_main, já filtrado por
        # _score_activate_main antes de chegar aqui) -- e também em
        # when_attacking/on_opp_attack, pelo MESMO motivo: também resolvem
        # automaticamente durante o combate, sem scoring prévio próprio.
        # Achado real 20/07 (partida ao vivo): sem isso, when_attacking/
        # on_opp_attack SEMPRE pagavam o custo quando viável (nunca
        # julgavam se compensava) enquanto o caminho ao vivo (resolve_reaction
        # em sim_bridge.py) usava uma régua TOTALMENTE diferente, pensada só
        # pra habilidades de REDIRECT de ataque (ex: Teach) -- dois motores
        # divergentes pra mesma pergunta, violando a regra "sem dois
        # motores". Katakuri (OP11-062, custo don_minus puro -- recurso, não
        # sacrifício) ficava com a ability sempre recusada ao vivo porque
        # resolve_reaction julgava "o ataque já perde sozinho" como motivo
        # pra recusar, uma pergunta que só faz sentido pra quem está
        # DEFENDENDO, não pra quem está usando o próprio gatilho de ataque.
        # Mesma pergunta feita ao vivo via resolve_optional_effect em
        # sim_bridge.py.
        if trigger in ('when_attacking', 'on_opp_attack', 'leader_battle_reactive'):
            combat_verdict = self._combat_buff_worth_paying(
                card, ef_data, trigger, battle_defender_power)
            if combat_verdict is not None:
                if not combat_verdict:
                    return []
            elif not self._worth_paying_optional_costs(ef_data.get('costs', []), card):
                return []
        elif trigger in ('on_play', 'main', 'trigger') \
                and not self._worth_paying_optional_costs(ef_data.get('costs', []), card):
            # 'trigger' (achado 23/07): [Trigger] de vida com custo de
            # recurso antes do ':' tambem e opcional pela regra oficial
            # (ver CLAUDE.md#regras-de-jogo) -- passava direto sem
            # julgamento nenhum. 'activate_main' fica de fora: ja e filtrado
            # por scoring proprio (_score_activate_main) ANTES de chegar
            # aqui; '[Counter]' de personagem/lider nao roda via execute()
            # hoje (so eventos [Counter] da mao, em try_counter_event_*),
            # entao nao ha gate pra estender aqui ainda.
            return []

        # Paga custos. _last_trashed_names zerado ANTES (nao depois, ao
        # contrario de _last_selected) porque e preenchido DENTRO de
        # _pay_costs (custo trash_from_hand) e precisa sobreviver ate os
        # steps rodarem logo abaixo -- ver "same_name_as_trashed" em
        # play_from_trash (achado 16/07, EB02-039).
        self._last_trashed_names = []
        # Contagem do custo trash_any_from_hand (achado 19/07, OP06-014 e
        # familia): usa atributo PROPRIO (nao self._last_moved_count),
        # porque este e resetado logo abaixo ANTES do loop de steps (linha
        # seguinte a _pay_costs) -- um valor setado DENTRO de _pay_costs
        # nunca sobreviveria ate o step buff_power_per_count/source=
        # trashed_hand_this_effect ler.
        self._last_cost_trash_any_count = 0
        # Mesma armadilha, agora pro custo bounce_any_own_character
        # (achado 19/07, P-059): atributo PROPRIO, nao self._last_moved_
        # count, pelo mesmo motivo (reset acontece antes do loop de steps).
        self._last_cost_bounce_any_count = 0
        # Mesma armadilha, agora pro custo rest_any_don (achado 29/07,
        # OP13-001 Luffy): atributo PROPRIO, mesmo motivo.
        self._last_cost_rest_any_don_count = 0
        if not self._pay_costs(ef_data.get('costs', []), card):
            return []

        # Executa steps. Os logs do CUSTO (pago acima) vêm primeiro, para o
        # replay mostrar o que foi pago antes do benefício.
        logs = list(getattr(self, '_cost_logs', []))
        # Memoria de alvo entre steps (SaveTargetName, achado 28/06/2026):
        # zerada a cada execute(), preenchida por um step de selecao
        # (buff_power target='select_filtered') e consumida por um step
        # POSTERIOR no MESMO bloco (target='selected') -- nunca atravessa
        # triggers/blocos diferentes.
        self._last_selected = None
        self._last_moved_count = 0
        for step in steps_all:
            log = self._execute_step(step, card)
            if log:
                logs.append(log)

        if ef_data.get('once_per_turn'):
            self._once_used.add(key)

        return logs

    def try_substitute(self, card: Card, removal_kind: str, verbose: bool = False) -> str | None:
        """
        Verifica se `card` (do lado self.me) tem substitute_ko (removal_kind
        == 'ko') ou substitute_removal (removal_kind in ('ko','bounce',
        'deck_bottom') -- substitute_removal cobre QUALQUER remocao, nao so
        K.O.) ativo, e se sim tenta pagar o custo da substituicao.
        Retorna uma string de log se substituiu (e quem chamou NAO deve
        prosseguir com a remocao real), ou None se nao ha substituto
        aplicavel/pagavel (remocao segue normalmente).
        """
        effects = get_card_effects(card.code)
        # Achado 01/07/2026: so checava 'passive', mas cartas com a tag
        # formal "[Opponent's Turn]"/"[Your Turn]" ANTES da clausula de
        # substituicao (ex: OP14-029, OP14-092) viram esse timing virar a
        # chave de topo no parser, nao 'passive' (mesmo padrao que
        # is_immune() ja trata corretamente ao iterar varios timings).
        for timing in ('passive', 'opp_turn', 'your_turn'):
            block = effects.get(timing, {})
            if not block:
                continue

            for step in block.get('steps', []):
                action = step.get('action')
                aplica = ((action == 'substitute_ko' and removal_kind == 'ko') or (action == 'substitute_removal' and removal_kind != 'rest') or (action == 'substitute_rest' and removal_kind == 'rest'))
                if not aplica:
                    continue
                negated_name = (step.get('negated_if_any_character_named') or '').lower()
                if negated_name and any(
                        negated_name in c.name.lower()
                        for c in self.me.field_chars + self.opp.field_chars):
                    continue

                # Once per turn (mesma chave de controle que efeitos normais)
                key = (card.code, f'{timing}_substitute')
                if block.get('once_per_turn') and key in self._once_used:
                    continue

                # Filtro de alvo: self_type (sub_types) ou self_name (nome
                # proprio) -- quando presentes, restringem quais cards desse
                # arquetipo podem usar o substituto.
                #
                # Vazamento de condicao de uma clausula IRMA (achado 06/08,
                # censo global): quando o bloco combina o substitute com
                # OUTRO(S) step(s) independente(s) sem tag formal separando
                # as duas clausulas (ex: OP17-095 "if Character custo 12+,
                # ganha +3000 power. If ONE OF YOUR Characters would be
                # removed..." -- ou OP07-029/ST15-005, "[Blocker]"/"[Rush]"
                # condicionado a leader_type seguido de "[Once Per Turn] If
                # this Character would be removed..." com a tag colada
                # ENTRE o ponto e o "if", quebrando a adjacencia que o
                # split de clausulas exige), a 'conditions' do BLOCO
                # pertence a essa clausula IRMA -- nunca ao substitute em
                # si, que ja e auto-contido (seu proprio "if X would be
                # K.O.'d/removed" ja foi reconhecido na hora de virar
                # step). Aplicar 'conditions' do bloco aqui so faz sentido
                # quando o substitute e o UNICO step do bloco (ai a
                # condicao so pode ser dele mesmo) -- mesmo principio ja
                # usado por `_source_conditions_met_for_substitute`
                # (substituto EXTERNO, concedido por outra carta) ao
                # descartar self_type/self_power_base_* antes de checar.
                outros_steps_no_bloco = [
                    s for s in block.get('steps', [])
                    if s is not step and s.get('action') not in
                    ('substitute_ko', 'substitute_removal', 'substitute_rest')]
                conds = dict(block.get('conditions', {}))
                if not outros_steps_no_bloco and not self._check_conditions(conds, card):
                    continue
                filter_type = step.get('filter_type', '')
                if filter_type and filter_type.lower() not in card.sub_types.lower():
                    continue
                filter_name = step.get('filter_name', '')
                if filter_name and filter_name.lower() not in card.name.lower():
                    continue

                cost = step.get('cost', {})
                if not self._de().should_pay_removal_substitute(card, cost):
                    continue
                log = self._pay_substitute_cost(cost, card)
                if log is None:
                    continue  # não conseguiu pagar -- tenta o próximo step (raro) ou desiste

                extra_logs = []
                for extra in step.get('extra_steps', []):
                    extra_log = self._execute_step(extra, card)
                    if extra_log:
                        extra_logs.append(extra_log)

                if block.get('once_per_turn'):
                    self._once_used.add(key)
                if extra_logs:
                    return log + ' | ' + ' | '.join(extra_logs)
                return log

        return None

    def _substitute_source_blocks(self, source: Card, source_is_opp: bool):
        effects = get_card_effects(source.code)
        # 'your_turn' adicionado em 01/07/2026 -- mesmo achado de
        # try_substitute(): cartas com a tag formal "[Your Turn]" antes da
        # clausula de substituicao (ex: OP14-034) usam essa chave de topo,
        # nao 'passive'. Sem gating extra por source_is_opp aqui (mesma
        # simplificacao ja usada no resto do engine pra essas tags de turno
        # -- is_immune()/_current_turn_owner() tambem trata como "sempre
        # vale" por falta de rastreamento fino de turno).
        for trigger in ('passive', 'opp_turn', 'your_turn'):
            if trigger == 'opp_turn' and not source_is_opp:
                continue
            block = effects.get(trigger, {})
            if block:
                yield trigger, block

    def _source_conditions_met_for_substitute(self, source: Card, block: dict) -> bool:
        conds = dict(block.get('conditions', {}))
        for key in ('self_type', 'self_power_base_lte', 'self_power_base_gte'):
            conds.pop(key, None)
        # Vazamento de condicao de clausula IRMA (achado 06/08, mesmo
        # principio ja aplicado em try_substitute() pro caminho de
        # AUTOPROTECAO -- ver comentario la): quando o bloco combina o
        # substitute com OUTRO(S) step(s) independente(s), a 'conditions'
        # restante (apos a limpeza de self_type acima) pertence a essa
        # clausula irma, nunca ao proprio substitute -- que e sempre
        # auto-contido. So aplica quando o substitute e o UNICO step do
        # bloco. Achado REAL confirmado (nao so teorico): OP17-095
        # (Roronoa Zoro) tem 'no_filter'=True no substitute_removal
        # ("if ONE OF YOUR Characters would be removed..." -- protege
        # QUALQUER personagem seu, uso EXTERNO valido) + o buff irmao
        # ("if Character custo 12+...") vazando 'board_has_cost_gte' pro
        # nivel do bloco -- sem este guard, Zoro nunca protegia um ALIADO
        # (so a si mesmo, e olhe la) quando nao havia Character custo 12+
        # no campo, apesar do texto do substitute nao mencionar essa
        # condicao em nenhum momento.
        outros_steps = [
            s for s in block.get('steps', [])
            if s.get('action') not in ('substitute_ko', 'substitute_removal', 'substitute_rest')]
        if outros_steps:
            conds = {}
        return self._check_conditions(conds, source)

    def _target_matches_external_substitute(self, target: Card, source: Card,
                                            step: dict, block: dict) -> bool:
        from optcg_engine.rules_facade import card_matches_filter

        if step.get('filter_type') and not card_matches_filter(target, step.get('filter_type')):
            return False
        if step.get('filter_name'):
            needle = step.get('filter_name', '').lower()
            if needle not in target.name.lower() and needle not in target.code.lower():
                return False
        if step.get('filter_color') and step.get('filter_color', '').lower() not in target.color.lower():
            return False
        if step.get('filter_attribute'):
            wanted_attr = step.get('filter_attribute', '').lower()
            atributos_alvo = [(target.attribute or '').lower(),
                              (getattr(target, 'extra_attribute_this_turn', '') or '').lower()]
            if not any(wanted_attr in a for a in atributos_alvo if a):
                return False
        if step.get('cost_lte') is not None and target.cost > step['cost_lte']:
            return False
        if step.get('cost_gte') is not None and target.cost < step['cost_gte']:
            return False
        if step.get('power_lte') is not None and target.power > step['power_lte']:
            return False
        if step.get('power_eq') is not None and target.power != step['power_eq']:
            return False
        if step.get('power_gte') is not None and target.power < step['power_gte']:
            return False
        if step.get('rested_only') and not target.rested:
            return False
        if step.get('exclude_self') and target is source:
            return False
        if step.get('exclude'):
            exclude = step.get('exclude', '').lower()
            if exclude in target.name.lower() or exclude in target.code.lower():
                return False

        conds = block.get('conditions', {})
        if conds.get('self_type') and conds['self_type'] not in target.sub_types.lower():
            return False
        if conds.get('self_power_base_lte') is not None and target.power > conds['self_power_base_lte']:
            return False
        if conds.get('self_power_base_gte') is not None and target.power < conds['self_power_base_gte']:
            return False

        target_keys = (
            'filter_type', 'filter_name', 'filter_color', 'filter_attribute', 'cost_lte', 'cost_gte',
            'power_lte', 'power_eq', 'power_gte', 'rested_only', 'exclude', 'exclude_self',
        )
        target_cond_keys = ('self_type', 'self_power_base_lte', 'self_power_base_gte')
        # 'no_filter': marcado explicitamente pelo parser quando o texto real
        # nao tem restricao nenhuma de alvo (ex: OP16-014 "if one of your
        # Characters would be removed..."). Distinto de "nenhuma chave
        # presente" generico (que continua tratado como "protecao desligada"
        # por seguranca, default pra falha de extracao de filtro).
        if step.get('no_filter'):
            return True
        return any(k in step for k in target_keys) or any(k in conds for k in target_cond_keys)

    def _try_external_substitute_from_source(self, source: Card, target: Card,
                                             removal_kind: str,
                                             source_is_opp: bool) -> str | None:
        for trigger, block in self._substitute_source_blocks(source, source_is_opp):
            if not self._source_conditions_met_for_substitute(source, block):
                continue
            don_req = block.get('don_requirement', 0)
            if don_req and getattr(source, 'don_attached', 0) < don_req:
                continue
            for step in block.get('steps', []):
                action = step.get('action')
                aplica = ((action == 'substitute_ko' and removal_kind == 'ko') or (action == 'substitute_removal' and removal_kind != 'rest') or (action == 'substitute_rest' and removal_kind == 'rest'))
                if not aplica:
                    continue
                key = (source.code, f'{trigger}_substitute')
                if block.get('once_per_turn') and key in self._once_used:
                    continue
                if not self._target_matches_external_substitute(target, source, step, block):
                    continue
                cost = step.get('cost', {})
                cost_card = target if cost.get('action') == 'debuff_power_self' else source
                if not self._de().should_pay_removal_substitute(
                        target, cost, payer=cost_card):
                    continue
                log = self._pay_substitute_cost(cost, cost_card)
                if log is None:
                    continue
                extra_logs = []
                for extra in step.get('extra_steps', []):
                    extra_log = self._execute_step(extra, source)
                    if extra_log:
                        extra_logs.append(extra_log)
                if block.get('once_per_turn'):
                    self._once_used.add(key)
                if extra_logs:
                    return log + ' | ' + ' | '.join(extra_logs)
                return log
        return None

    def try_any_substitute(self, target: Card, removal_kind: str,
                           source_is_opp: bool = True) -> str | None:
        log = self.try_substitute(target, removal_kind)
        if log:
            return log

        sources = [c for c in self.me.field_chars if c is not target]
        sources.append(self.me.leader)
        if self.me.field_stage:
            sources.append(self.me.field_stage)
        for source in sources:
            log = self._try_external_substitute_from_source(
                source, target, removal_kind, source_is_opp)
            if log:
                return log
        return None

    def try_counter_event_substitute(self, target: Card, removal_kind: str) -> str | None:
        """Ativa evento [Counter] da mao que substitui K.O./remocao em batalha."""
        for event in list(self.me.hand):
            if event.card_type != 'EVENT':
                continue
            block = get_card_effects(event.code).get('counter', {})
            if not block:
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue

            for step in block.get('steps', []):
                action = step.get('action')
                aplica = ((action == 'substitute_ko' and removal_kind == 'ko') or (action == 'substitute_removal' and removal_kind != 'rest') or (action == 'substitute_rest' and removal_kind == 'rest'))
                if not aplica:
                    continue
                target_keys = (
                    'filter_type', 'filter_name', 'filter_color', 'cost_lte', 'cost_gte',
                    'power_lte', 'power_eq', 'power_gte', 'rested_only', 'exclude',
                )
                if any(k in step for k in target_keys) and not self._target_matches_external_substitute(target, event, step, block):
                    continue

                cost = step.get('cost', {})
                if cost.get('action') != 'trash_from_hand':
                    continue
                count = cost.get('count', 1)
                if len([c for c in self.me.hand if c is not event]) < count:
                    continue

                remove_by_identity(self.me.hand, event)
                self.me.trash.append(event)
                self.me.don_available -= play_cost
                self.me.don_rested += play_cost

                log = self._pay_substitute_cost(cost, target)
                if log is None:
                    continue
                return f'Counter {event.name[:18]}: {log}'

        return None

    def _counter_event_cost_payable(self, event: Card, costs: list) -> bool:
        extra_discards = 0
        for cost in costs:
            ctype = cost.get('type')
            if ctype == 'trash_from_hand':
                extra_discards += cost.get('count', 1)
            elif ctype == 'don_minus' and not cost.get('optional', False):
                if self.me.don_available + self.me.don_rested < cost.get('count', 1):
                    return False
            elif ctype != 'don_minus':
                return False
        return len([c for c in self.me.hand if c is not event]) >= extra_discards

    def _pay_counter_event_costs(self, event: Card, costs: list) -> list[str] | None:
        logs = []
        for cost in costs:
            ctype = cost.get('type')
            if ctype == 'trash_from_hand':
                trashed = []
                for _ in range(cost.get('count', 1)):
                    candidates = [c for c in self.me.hand if c is not event]
                    if not candidates:
                        return None
                    worst = self._choose_to_trash(candidates)
                    remove_by_identity(self.me.hand, worst)
                    self.me.trash.append(worst)
                    trashed.append(worst.name[:15])
                logs.append(f'trashou da mao: {", ".join(trashed)}')
            elif ctype == 'don_minus' and not cost.get('optional', False):
                count = cost.get('count', 1)
                if not self._return_don_to_deck(count):
                    return None
                logs.append(f'devolveu {count} DON')
        return logs

    def _parse_counter_event_text_fallback(
        self, event: Card, target: Card, target_type: str
    ) -> dict | None:
        """
        Parseia o efeito [Counter] do texto bruto da carta para o caso padrão:
        "Your Leader [or Character] gains +X power during this battle."
        Cobre ~90% dos counter events; casos condicionais ou multi-step ficam
        fora de escopo aqui (retornam None e o engine ignora o evento como
        counter, sem catastrófico -- só não usa a carta).
        """
        text = event.card_text or ''
        # Extrai o bloco após [Counter]
        m_block = re.search(r'\[counter\](.*?)(?:\[|$)', text.lower(), re.DOTALL)
        if not m_block:
            return None
        counter_text = m_block.group(1)

        # Condições globais simples — usa as mesmas chaves de _check_conditions
        conditions: dict = {}
        m_leader = re.search(r'if your leader is \[(\w+)\]', counter_text)
        if m_leader:
            conditions['leader_is'] = m_leader.group(1).lower()
        m_trash = re.search(r'if you have (\d+) or more cards? in your trash', counter_text)
        if m_trash:
            conditions['trash_gte'] = int(m_trash.group(1))

        # Detecta o buff: "+X power during this battle"
        m_buff = re.search(r'\+(\d+)\s*power\s+during\s+this\s+battle', counter_text)
        if not m_buff:
            return None
        amount = int(m_buff.group(1))

        # Detecta o target
        if 'your leader or character' in counter_text:
            target_rule = 'leader_or_character'
        elif 'your leader' in counter_text:
            target_rule = 'leader'
        elif 'your character' in counter_text:
            target_rule = 'own_character'
        else:
            target_rule = 'leader_or_character'

        # Rejeita se target não bate com quem está sendo atacado
        if target_rule == 'leader' and target_type != 'leader':
            return None
        if target_rule == 'own_character' and target_type != 'character':
            return None

        return {
            'steps': [{
                'action': 'buff_power',
                'amount': amount,
                'target': target_rule,
                'duration': 'battle_only',
            }],
            'conditions': conditions,
        }

    def _counter_event_power_plan(self, event: Card, target: Card,
                                  target_type: str) -> tuple[int, list[dict]] | None:
        block = get_card_effects(event.code).get('counter', {})
        # Fallback: parser atual não parseia blocos [Counter] de EVENT cards
        # (armazena counter: 0). Para o padrão mais comum — "gains +X power
        # during this battle" — extrai o valor direto do texto.
        if not block:
            block = self._parse_counter_event_text_fallback(event, target, target_type)
            if block is None:
                return None
        if not self._check_conditions(block.get('conditions', {}), event):
            return None
        steps = block.get('steps', [])
        # 'this_turn' conta igual a 'battle_only' aqui: o Counter Step so
        # acontece DENTRO da resolucao desta batalha, e o resto do engine ja
        # trata as duas durations de forma identica na limpeza (reset de
        # power_buff no inicio do turno) -- achado 30/06/2026, 5 cartas reais
        # no banco usam 'this_turn' num buff que so faz sentido como defesa
        # de Counter (OP04-037, OP04-076, OP06-017, OP09-039, OP13-077).
        buff_steps = [
            step for step in steps
            if step.get('action') == 'buff_power' and step.get('duration') in ('battle_only', 'this_turn')
        ]
        if not buff_steps:
            return None
        buff_step_ids = {id(s) for s in buff_steps}
        extras = [step for step in steps if id(step) not in buff_step_ids]
        safe_extra_actions = {
            'draw', 'set_active', 'rest_opp_character', 'add_don', 'set_don_active',
            'ko', 'bounce', 'place_opp_character_bottom_deck', 'debuff_power',
            'trash_from_deck_top', 'peek_life', 'add_from_trash', 'gain_life',
            'character_to_owner_life', 'opp_bounce_own_character',
            'play_card', 'play_from_deck', 'look_top_deck', 'add_to_hand',
            'deck_bottom_rest', 'deck_reorder_rest', 'deck_top_rest',
        }
        if any(step.get('action') not in safe_extra_actions for step in extras):
            return None
        principal, *bonus_steps = buff_steps
        target_rule = principal.get('target')
        if target_rule == 'leader' and target_type != 'leader':
            return None
        if target_rule == 'own_character' and target_type != 'character':
            return None
        if target_rule == 'select_filtered':
            # "Up to 1 of your [Tipo] type Leader or Character cards gains
            # +X power" -- so conta como defesa se o ALVO REAL sob ataque
            # (target, o leader/character defendendo) bater no filtro; senao
            # o efeito buffaria outra carta qualquer, que nao impede o hit
            # nesta batalha (achado 30/06/2026, 9 cartas no banco).
            from optcg_engine.rules_facade import card_matches_filter
            if not card_matches_filter(target, principal.get('filter_type', '')):
                return None
        elif target_rule not in ('leader', 'own_character', 'leader_or_character'):
            return None
        if principal.get('conditions') and not self._check_conditions(principal.get('conditions', {}), event):
            return None
        amount = principal.get('amount', 0)
        # buff_power(battle_only) ADICIONAL com target='selected' -- texto
        # real confirmado em 10+ casos do banco: "Up to 1 of your Leader or
        # Character cards gains +X power... Then, if [cond], THAT CARD gains
        # an additional +Y power" (ex: EB03-020, OP04-095, OP07-035). Ate
        # 17/07 o parser mapeava "that card" como target='self' (usado aqui
        # so como MARCADOR interno de "mesma carta escolhida no step
        # anterior", nao o proprio Event -- nunca refletia o real
        # comportamento fora deste caminho). Generalizado pra
        # target='selected' (consistente com o resto do engine, ver
        # _last_selected/select_filtered) -- 'self' mantido tambem por
        # retrocompatibilidade, caso alguma variante ainda produza esse
        # valor.
        for bonus in bonus_steps:
            if bonus.get('target') not in ('self', 'selected'):
                return None
            if bonus.get('conditions') and not self._check_conditions(bonus.get('conditions', {}), event):
                continue
            amount += bonus.get('amount', 0)
        return amount, extras

    def try_counter_event_power(self, target: Card, target_type: str,
                                needed: int) -> tuple[int, str] | None:
        """Usa um evento [Counter] simples se o buff de batalha impedir o hit."""
        candidates = []
        for event in self.me.hand:
            if event.card_type != 'EVENT':
                continue
            plan = self._counter_event_power_plan(event, target, target_type)
            if plan is None:
                continue
            amount, extras = plan
            if amount < needed:
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue
            costs = get_card_effects(event.code).get('counter', {}).get('costs', [])
            if not self._counter_event_cost_payable(event, costs):
                continue
            candidates.append((amount - needed, play_cost, event, amount, costs, extras))

        if not candidates:
            return None

        _, play_cost, event, amount, costs, extras = min(candidates, key=lambda item: (item[0], item[1]))
        cost_logs = self._pay_counter_event_costs(event, costs)
        if cost_logs is None:
            return None
        remove_by_identity(self.me.hand, event)
        self.me.trash.append(event)
        self.me.don_available -= play_cost
        self.me.don_rested += play_cost
        log = f'Counter {event.name[:18]}: +{amount} power'
        extra_logs = []
        for extra in extras:
            if extra.get('conditions') and not self._check_conditions(extra.get('conditions', {}), event):
                continue
            extra_log = self._execute_step(extra, event)
            if extra_log:
                extra_logs.append(extra_log)
        if cost_logs:
            log += ' | custo: ' + '; '.join(cost_logs)
        if extra_logs:
            log += ' | ' + ' | '.join(extra_logs)
        return amount, log

    def _counter_event_debuff_plan(self, event: Card, attacker: Card,
                                   attacker_type: str) -> int | None:
        """Plano pra Counter events que enfraquecem o ATACANTE em vez de
        buffar a propria defesa -- mecanica distinta de
        _counter_event_power_plan, que so cobre 'Your Leader or Character
        gains power'. Achado 30/06/2026: 5 cartas no banco sao "[Counter]
        Give up to 1 of your opponent's Leader or Character cards -X power
        during this turn" (OP01-028, OP03-017, OP07-075, OP15-021,
        ST09-014) -- um unico debuff_power, sem extras, alvo escolhido pela
        IA = sempre o atacante (o que importa pra sobreviver A ESTE ataque).

        Generalizado 19/07/2026 (aprovacao explicita do usuario) pra
        aceitar ATE 2 debuff_power SEQUENCIAIS no mesmo bloco (OP04-017:
        -2000 incondicional + -1000 "if your Leader is active") e
        debuff_power combinado com negate_effect (OP09-097: "Negate...
        and give THAT CARD -4000 power"). Leitura assumida (unica sem
        ambiguidade real dado que um Counter so se joga DURANTE a
        batalha em curso): TODO debuff_power do bloco mira o MESMO alvo,
        o proprio ATACANTE -- nao ha razao de jogo pra split entre dois
        Characters do oponente quando so 1 esta atacando agora. Soma os
        amounts de todo debuff_power APLICAVEL (condicao bate e
        target_rule compativel com attacker_type); pula (nao rejeita o
        bloco inteiro) debuff_power cuja condicao/target nao se aplica
        agora -- so rejeita o bloco inteiro se target_rule for
        desconhecido OU se nenhum debuff aplicavel sobrar. negate_effect
        e QUALQUER outro step junto no bloco e ignorado pra fins deste
        calculo (simplificacao ja assumida: este mecanismo so responde
        "[Counter] jogado sozinho evita o hit?", nao simula o efeito
        negado)."""
        block = get_card_effects(event.code).get('counter', {})
        if not block or not self._check_conditions(block.get('conditions', {}), event):
            return None
        steps = block.get('steps', [])
        if not steps or any(s.get('action') not in ('debuff_power', 'negate_effect') for s in steps):
            return None
        total = 0
        for step in steps:
            if step.get('action') != 'debuff_power':
                continue
            target_rule = step.get('target')
            if target_rule not in ('opp_character', 'opp_leader_or_character'):
                return None
            if target_rule == 'opp_character' and attacker_type != 'character':
                continue
            if step.get('conditions') and not self._check_conditions(step.get('conditions', {}), event):
                continue
            total += step.get('amount', 0)
        return total or None

    def try_counter_event_debuff(self, attacker: Card, attacker_type: str,
                                 needed: int) -> tuple[int, str] | None:
        """Usa um evento [Counter] que enfraquece o ATACANTE (em vez de
        buffar a propria defesa) se isso sozinho impedir o hit."""
        candidates = []
        for event in self.me.hand:
            if event.card_type != 'EVENT':
                continue
            amount = self._counter_event_debuff_plan(event, attacker, attacker_type)
            if amount is None or amount < needed:
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue
            costs = get_card_effects(event.code).get('counter', {}).get('costs', [])
            if not self._counter_event_cost_payable(event, costs):
                continue
            candidates.append((amount - needed, play_cost, event, amount, costs))

        if not candidates:
            return None

        _, play_cost, event, amount, costs = min(candidates, key=lambda item: (item[0], item[1]))
        cost_logs = self._pay_counter_event_costs(event, costs)
        if cost_logs is None:
            return None
        remove_by_identity(self.me.hand, event)
        self.me.trash.append(event)
        self.me.don_available -= play_cost
        self.me.don_rested += play_cost
        attacker.power_buff -= amount
        log = f'Counter {event.name[:18]}: -{amount} power no atacante'
        if cost_logs:
            log += ' | custo: ' + '; '.join(cost_logs)
        return amount, log

    def _counter_event_ko_plan(self, event: Card, attacker: Card) -> bool:
        """Checa se um evento [Counter] da K.O. no ATACANTE especifico.
        Achado 30/06/2026: 4 cartas no banco sao "[Counter] K.O. up to 1 of
        your opponent's Characters with cost/power N or less[, rested
        only]" (EB01-010, OP08-094, OP10-040, OP13-039) -- cancelamento
        TOTAL do ataque (sem dano nenhum), distinto de buffar defesa ou
        debuffar o atacante. Escopo minimo: exige EXATAMENTE 1 step 'ko'
        com target='opp_character' (Leaders nunca aparecem como alvo nesses
        4 casos) e nenhum outro step."""
        block = get_card_effects(event.code).get('counter', {})
        if not block or not self._check_conditions(block.get('conditions', {}), event):
            return False
        steps = block.get('steps', [])
        if len(steps) != 1:
            return False
        step = steps[0]
        if step.get('action') != 'ko' or step.get('target') != 'opp_character':
            return False
        cost_lte = step.get('cost_lte')
        if cost_lte is not None and attacker.cost > cost_lte:
            return False
        power_lte = step.get('power_lte')
        if power_lte is not None and attacker.effective_power(False) > power_lte:
            return False
        if step.get('rested_only') and not attacker.rested:
            return False
        return True

    def try_counter_event_ko_attacker(self, attacker: Card) -> str | None:
        """Usa um evento [Counter] que da K.O. no atacante inteiro,
        cancelando o ataque (sem comparacao de power -- o ataque
        simplesmente nao acontece). Respeita imunidade/substituicao do
        atacante igual ao 'ko' generico (ko_context='effect': nao e KO em
        combate, e o efeito do proprio Counter event)."""
        candidates = []
        for event in self.me.hand:
            if event.card_type != 'EVENT':
                continue
            if not self._counter_event_ko_plan(event, attacker):
                continue
            play_cost = effective_hand_play_cost(self.me, event, self.opp)
            if self.me.don_available < play_cost:
                continue
            costs = get_card_effects(event.code).get('counter', {}).get('costs', [])
            if not self._counter_event_cost_payable(event, costs):
                continue
            candidates.append((play_cost, event, costs))

        if not candidates:
            return None

        play_cost, event, costs = min(candidates, key=lambda item: item[0])

        if is_immune(attacker, 'ko', self.opp, self.me, source_is_opp=True, ko_context='effect'):
            return None
        ee_attacker = EffectExecutor(self.opp, self.me)
        if ee_attacker.try_any_substitute(attacker, 'ko', source_is_opp=True):
            return None

        cost_logs = self._pay_counter_event_costs(event, costs)
        if cost_logs is None:
            return None
        remove_by_identity(self.me.hand, event)
        self.me.trash.append(event)
        self.me.don_available -= play_cost
        self.me.don_rested += play_cost
        remove_character_from_field(self.opp, attacker, 'trash')
        log = f'Counter {event.name[:18]}: K.O. no atacante {attacker.name[:15]}'
        if cost_logs:
            log += ' | custo: ' + '; '.join(cost_logs)
        return log

    def _pay_substitute_cost(self, cost: dict, card: Card) -> str | None:
        """Paga o custo de uma substituicao de K.O./remocao. Retorna log de
        sucesso, ou None se nao pode pagar (substituicao nao ocorre)."""
        ctype = cost.get('action')
        me = self.me

        if ctype == 'trash_self':
            if not contains_identity(me.field_chars, card):
                return None
            remove_character_from_field(me, card, 'trash')
            return f'{card.name[:18]} evitou K.O./remoção trashando a si mesmo'

        if ctype == 'rest_don':
            count = cost.get('count', 1)
            if me.don_available < count:
                return None
            me.don_available -= count
            me.don_rested += count
            return f'{card.name[:18]} evitou K.O./remoção restando {count} DON'

        if ctype in ('return_own_don', 'don_minus'):
            count = cost.get('count', 1)
            if not self._return_don_to_deck(count):
                return None
            return f'{card.name[:18]} evitou K.O./remoção devolvendo {count} DON ao deck'

        if ctype == 'trash_from_hand':
            from optcg_engine.rules_facade import eligible_cards

            count = cost.get('count', 1)
            candidatos = eligible_cards(
                me.hand,
                filter_text=cost.get('filter_type', ''),
                power_gte=cost.get('power_gte'),
                power_lte=cost.get('power_lte'),
            )
            if len(candidatos) < count:
                return None
            trashed = []
            for _ in range(count):
                worst = min(candidatos, key=lambda c: c.board_value())
                remove_by_identity(me.hand, worst)
                me.trash.append(worst)
                remove_by_identity(candidatos, worst)
                trashed.append(worst.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção trashando da mão: {", ".join(trashed)}'

        if ctype == 'debuff_power_self':
            amount = cost.get('amount', 0)
            card.power_buff -= amount
            return f'{card.name[:18]} evitou K.O./remoção perdendo {amount} de power'

        if ctype == 'debuff_power_self_leader':
            amount = cost.get('amount', 0)
            me.leader.power_buff -= amount
            return f'{card.name[:18]} evitou K.O./remoção (Leader perdeu {amount} de power)'

        if ctype == 'rest_self':
            if card.rested:
                return None
            card.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando-se'

        if ctype == 'bounce_self':
            if not contains_identity(me.field_chars, card):
                return None
            remove_character_from_field(me, card, 'hand')
            return f'{card.name[:18]} evitou K.O./remoção voltando para a mão'

        if ctype == 'rest_self_and_trash_hand':
            trash_count = cost.get('trash_count', cost.get('count', 1))
            if card.rested or len(me.hand) < trash_count:
                return None
            trashed = []
            for _ in range(trash_count):
                worst = self._choose_to_trash(me.hand)
                if worst is None:
                    return None
                remove_by_identity(me.hand, worst)
                me.trash.append(worst)
                trashed.append(worst.name[:15])
            card.rested = True
            return (
                f'{card.name[:18]} evitou K.O./remocao restando-se '
                f'e trashando da mao: {", ".join(trashed)}'
            )

        # ── Custos novos achados na auditoria de substituicao externa de
        # 01/07/2026 (11 cartas, ver TODO.md) ──────────────────────────────

        if ctype == 'rest_leader':
            # OP04-082: "you may rest your Leader or 1 [Corrida Coliseum]
            # instead" -- simplificacao deliberada: so a opcao do Leader (a
            # alternativa de stage nomeado e rara e exige modelar "OR" entre
            # dois tipos de carta bem diferentes).
            if me.leader.rested:
                return None
            me.leader.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando o Leader'

        if ctype == 'rest_own_filtered':
            # OP10-037/OP11-110: "you may rest 1 of your [Tipo] (type)
            # Characters instead" -- rest um PROPRIO Character que bate no
            # filtro de tipo do CUSTO (distinto do filtro de ALVO -- aqui o
            # filtro e sobre quem PAGA, nao sobre quem e protegido).
            from optcg_engine.rules_facade import eligible_cards

            candidatos = eligible_cards(
                [c for c in me.field_chars if not c.rested],
                filter_text=cost.get('filter_type', ''),
            )
            if not candidatos:
                return None
            alvo = max(candidatos, key=lambda c: c.board_value())
            alvo.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando {alvo.name[:15]}'

        if ctype == 'rest_own_character':
            # OP14-034 (substituicao EXTERNA): "you may rest 1 of your
            # Characters instead" -- qualquer Character proprio, sem filtro
            # de tipo (distinto de rest_own_filtered). cost_gte/exclude
            # opcionais (achado 17/07, OP05-032 Pica: "rest up to 1 of your
            # Characters with a cost of 3 or more other than [Pica]
            # instead" -- exclusao por nome, nao necessariamente self, mas
            # aqui coincide por ser substituicao propria).
            from optcg_engine.rules_facade import eligible_cards
            candidatos = eligible_cards(
                [c for c in me.field_chars if not c.rested],
                cost_gte=cost.get('cost_gte'),
                cost_lte=cost.get('cost_lte'),
                exclude_name=cost.get('exclude', ''),
            )
            if not candidatos:
                return None
            alvo = max(candidatos, key=lambda c: c.board_value())
            alvo.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando {alvo.name[:15]}'

        if ctype == 'rest_own_other_character':
            # PRB02-006 (Zoro): "you may rest 1 of your OTHER Characters
            # instead" -- substituicao PROPRIA (a carta se protege restando
            # uma ALIADA, nao qualquer character -- precisa excluir `card`,
            # a propria carta que esta se substituindo, dos candidatos.
            # Distinto de rest_own_character (substituicao EXTERNA, onde
            # `card` ja e outra carta e a exclusao nao se aplica).
            count = cost.get('count', 1)
            candidatos = [c for c in me.field_chars if not c.rested and c is not card]
            if len(candidatos) < count:
                return None
            restados = []
            for _ in range(count):
                alvo = max(candidatos, key=lambda c: c.board_value())
                alvo.rested = True
                remove_by_identity(candidatos, alvo)
                restados.append(alvo.name[:15])
            return f'{card.name[:18]} evitou rest restando: {", ".join(restados)}'

        if ctype == 'rest_own_card':
            # OP14-029/OP15-035: "you may rest N of your cards instead" --
            # qualquer carta propria (Character OU Leader), sem filtro.
            count = cost.get('count', 1)
            candidatos = [c for c in me.field_chars if not c.rested]
            if not me.leader.rested:
                candidatos.append(me.leader)
            if len(candidatos) < count:
                return None
            restados = []
            for _ in range(count):
                alvo = max(candidatos, key=lambda c: c.board_value())
                alvo.rested = True
                remove_by_identity(candidatos, alvo)
                restados.append(alvo.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção restando: {", ".join(restados)}'

        if ctype == 'life_to_hand':
            # OP10-034/OP12-061: "you may add N cards from the top of your
            # Life cards to your hand instead" -- perde vida (carta sai da
            # zona de Life) mas ganha a carta na mao, mesma logica da action
            # generica 'life_to_hand' (achado: aqui e usada como CUSTO de
            # substituicao, nao como efeito solto).
            count = cost.get('count', 1)
            if len(me.life) < count:
                return None
            taken = []
            for _ in range(count):
                c = me.life.pop()
                c.life_face_up = False
                me.hand.append(c)
                taken.append(c.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção comprando da vida: {", ".join(taken)}'

        if ctype == 'life_to_trash':
            # ST09-010/ST20-002: "you may trash N cards from the top [or
            # bottom] of your Life cards instead" -- perde vida igual
            # life_to_hand, mas a carta vai pro trash em vez da mao.
            count = cost.get('count', 1)
            if len(me.life) < count:
                return None
            trashed = []
            for _ in range(count):
                c = me.life.pop()
                c.life_face_up = False
                me.trash.append(c)
                trashed.append(c.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção trashando da vida: {", ".join(trashed)}'

        if ctype == 'trash_to_deck_bottom':
            # OP14-092: "you may place N cards from your trash at the
            # bottom of your deck in any order instead" -- mesma semantica
            # do custo 'place_from_trash_bottom_deck' ja usado em
            # _pay_costs (ativacao normal), replicada aqui pro contexto de
            # substituicao (funcoes de custo separadas, sem reuso direto).
            count = cost.get('count', 1)
            if len(me.trash) < count:
                return None
            movidas = []
            for _ in range(count):
                pior = min(me.trash, key=lambda c: c.board_value())
                remove_by_identity(me.trash, pior)
                me.deck.insert(0, pior)
                movidas.append(pior.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção mandando pro fundo do deck: {", ".join(movidas)}'

        if ctype == 'rest_opp_character':
            # OP07-029 (Basil Hawkins): "you may rest 1 of your opponent's
            # Characters instead" -- custo INVERTIDO, nao sacrifica nada
            # proprio, resta um Character do OPONENTE. Distingue de
            # rest_own_character (mesmo nome raiz, alvo oposto). Verifica
            # imunidade a rest da carta alvo (mesmo criterio do action
            # 'rest_opp_character' usado para efeitos diretos). Heuristica:
            # escolhe o MELHOR Character do oponente pra restar (maior
            # board_value), pois e um custo que beneficia quem ativa.
            from optcg_engine.rules_facade import eligible_cards, choose_highest_board_value
            count = cost.get('count', 1)
            candidatos = [
                c for c in self.opp.field_chars
                if not c.rested
                and not c.cannot_be_rested_until
                and not is_immune(c, 'rest', self.opp, me, source_is_opp=True)
            ]
            if len(candidatos) < count:
                return None
            restados = []
            for _ in range(count):
                alvo = choose_highest_board_value(candidatos)
                alvo.rested = True
                remove_by_identity(candidatos, alvo)
                restados.append(alvo.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção restando {", ".join(restados)} do oponente'

        if ctype == 'turn_life_face_up':
            # OP12-102/OP13-109/ST29-008: "you may turn N card(s) from the
            # top of your Life cards face-up instead" -- custo de
            # substituicao nunca reconhecido antes (achado 16/07); carta do
            # topo da vida vira face-up, sem sair da zona de Life.
            count = cost.get('count', 1)
            if len(me.life) < count:
                return None
            for c in me.life[-count:]:
                c.life_face_up = True
            return f'{card.name[:18]} evitou K.O./remoção virando {count} carta(s) de vida face-up'

        return None

    def apply_your_turn_buffs(self) -> list:
        """
        Aplica buffs passivos [Your Turn] de todas as cartas em campo.
        Baseado no CardV3PassiveFieldBuffs das 34k linhas.
        Inclui stages, líderes e personagens.
        """
        logs = []
        sources = self.me.field_chars + [self.me.leader]
        if self.me.field_stage:
            sources.append(self.me.field_stage)
        # Reset buffs temporários antes de aplicar novos. cost_buff_permanent
        # ENTRA aqui tambem (achado 16/07, ST25-002 e familia): apply_your_
        # turn_buffs() roda 1x por turno do proprio jogador e RECALCULA os
        # steps de 'passive'/'your_turn' do zero -- sem resetar
        # cost_buff_permanent antes, cada chamada SOMAVA de novo o mesmo
        # +N (acumulo sem limite, turno apos turno). O campo so precisa
        # sobreviver ao reset_your_turn_buffs() de FIM de turno (distinto
        # de cost_buff comum) -- nao precisa (nem deve) sobreviver a esta
        # recalculacao do INICIO do turno, que ja e a fonte da verdade.
        for c in self.me.field_chars + [self.me.leader]:
            c.power_buff = 0
            c.cost_buff = 0
            c.cost_buff_permanent = 0

        # "Vida removida desde o ultimo check" (achado 29/07, Nami OP11-041
        # e familia) -- calculado ANTES de checar qualquer condicao (pra
        # refletir o que mudou desde a ULTIMA vez que rodou pra este
        # jogador, tipicamente durante o turno anterior do oponente), e a
        # snapshot so e ATUALIZADA no fim desta funcao -- _check_conditions
        # continua um predicado puro, sem side-effect (branches simulados
        # do Turn Planner nao podem mutar a snapshot do estado real).
        self._vida_minha_removida_desde_ultimo_check = (
            self.me.life_count_snapshot_mine != -1
            and len(self.me.life) < self.me.life_count_snapshot_mine)
        self._vida_opp_removida_desde_ultimo_check = (
            self.me.life_count_snapshot_opp != -1
            and len(self.opp.life) < self.me.life_count_snapshot_opp)

        for source in sources:
            effects = get_card_effects(source.code)
            for trigger in ('your_turn', 'passive'):
                if trigger not in effects:
                    continue
                ef_data = effects[trigger]
                if not self._check_conditions(ef_data.get('conditions', {}), source):
                    continue
                don_req = ef_data.get('don_requirement', 0)
                if don_req and getattr(source, 'don_attached', 0) < don_req:
                    continue
                # LACUNA CONHECIDA: cartas com 'Choose one: • opcao A • opcao
                # B' tem ef_data['choice'] = [[steps_opcao_A], [steps_opcao_B]]
                # em vez de ef_data['steps'] (ver gerar_effects_db.py,
                # parse_block). O .get('steps', []) abaixo retorna [] para
                # essas cartas -- nenhuma opcao e executada (neutro, nao
                # quebra), mas tambem nenhum efeito real acontece. Decidir
                # qual opcao escolher e avaliacao de jogo (Opponent Reading /
                # Play Scoring), nao um parsing determinístico -- pendente.
                #
                # LACUNA CONHECIDA #2: cartas com 'Apply each of the
                # following effects based on N' (efeitos COEXISTENTES, nao
                # exclusivos como choice) tem ef_data['conditional_stack'] =
                # [{conditions, steps}, ...] em vez de ef_data['steps'].
                # Carta unica confirmada (OP15-092) -- mesma neutralidade:
                # nao quebra, mas nenhum item do stack e avaliado/executado
                # ainda. Pendente: iterar o stack, checar conditions de cada
                # item via _check_conditions, executar os steps dos que
                # passarem (sem early-return -- sao cumulativos, nao 'escolha
                # 1 e para').
                steps_to_run = list(ef_data.get('steps', []))
                for item in ef_data.get('conditional_stack', []):
                    if self._check_conditions(item.get('conditions', {}), source):
                        steps_to_run.extend(item.get('steps', []))
                if not steps_to_run and ef_data.get('choice'):
                    steps_to_run = self._resolve_choice(ef_data.get('choice', []), source, ef_data.get('choice_chooser', 'self'))

                for step in steps_to_run:
                    log = self._execute_step(step, source)
                    if log:
                        logs.append(log)

        # Atualiza a snapshot pro PROXIMO check (depois de usar a antiga
        # acima pra decidir "mudou desde a ultima vez") -- vira a nova
        # baseline pro proximo turno deste jogador.
        self.me.life_count_snapshot_mine = len(self.me.life)
        self.me.life_count_snapshot_opp = len(self.opp.life)

        return logs

    def reset_your_turn_buffs(self):
        """Reseta buffs temporários ao fim do turno."""
        for card in self.me.field_chars + [self.me.leader]:
            card.power_buff = 0
            card.cost_buff = 0

    # ── Verificação de condições ─────────────────────────────────────────────

    def _check_conditions(self, conds: dict, card: Card) -> bool:
        me = self.me
        opp = self.opp

        if not conds:
            return True

        # "if it is your Nth turn or later" (achado 29/07, OP15-058 Enel) --
        # me.turn e o contador POR-JOGADOR (incrementado so no proprio
        # turno, distinto do global_turn compartilhado), exatamente a
        # semantica de "seu Nth turno".
        if 'turn_gte' in conds and me.turn < conds['turn_gte']:
            return False
        if 'life_lte' in conds and me.life_count() > conds['life_lte']:
            return False
        if 'life_gte' in conds and me.life_count() < conds['life_gte']:
            return False
        if 'opp_life_lte' in conds and opp.life_count() > conds['opp_life_lte']:
            return False
        if 'opp_life_gte' in conds and opp.life_count() < conds['opp_life_gte']:
            return False
        if 'total_life_lte' in conds and (me.life_count() + opp.life_count()) > conds['total_life_lte']:
            return False
        if conds.get('battled_opp_character_this_turn') and not getattr(
                card, 'battled_opp_character_this_turn', False):
            return False
        if 'trash_gte' in conds and len(me.trash) < conds['trash_gte']:
            return False
        # Simetrico a trash_gte -- achado 16/07 (OP04-094), usado pra
        # modelar "if you have M or more cards in your trash, [X] instead
        # of [Y]" como 2 steps mutuamente exclusivos (trash_gte no
        # upgrade, trash_lte=M-1 no base).
        if 'trash_lte' in conds and len(me.trash) > conds['trash_lte']:
            return False
        if 'don_gte' in conds and me.don_available < conds['don_gte']:
            return False
        if 'don_lte' in conds and me.don_available > conds['don_lte']:
            return False
        # "vida removida desde o ultimo check" (achado 29/07, Nami OP11-041
        # e familia) -- aproximacao do gatilho reativo real (ver comentario
        # em apply_your_turn_buffs/GameState.life_count_snapshot_*). Default
        # False se o atributo nao existe (contexto fora de
        # apply_your_turn_buffs, ex: chamada isolada em teste).
        if conds.get('life_removed_recently') and not (
                getattr(self, '_vida_minha_removida_desde_ultimo_check', False)
                or getattr(self, '_vida_opp_removida_desde_ultimo_check', False)):
            return False
        if conds.get('opp_life_removed_recently') and not getattr(
                self, '_vida_opp_removida_desde_ultimo_check', False):
            return False
        # "if your Leader is active/rested" -- condicao POR-STEP (nao de
        # bloco inteiro), achada 19/07 em OP04-017 (2o de 2 debuffs
        # sequenciais no mesmo Counter, so aplica se o Leader estiver
        # ativo). me sempre se refere ao dono da carta que carrega o
        # efeito (o proprio Leader, nao o do oponente).
        if 'leader_state' in conds:
            quer_ativo = conds['leader_state'] == 'active'
            if me.leader.rested == quer_ativo:
                return False
        # "if this Character is rested" -- auto-referencia ao estado da
        # PROPRIA carta (`card`, nao o Leader -- distinto de leader_state
        # acima). Achado 05/08 (Eustass Kid OP01-051/Captain John OP17-044,
        # mecanica de "taunt"): tambem corrige, de bonus, 3 cartas
        # pre-existentes (OP04-119 Donquixote Rosinante, OP14-026 Kouzuki
        # Oden, OP14-027 Shanks) cujo `[Opponent's Turn] If this Character
        # is rested, ...` disparava INCONDICIONALMENTE ate agora -- a
        # condicao nunca era checada porque parse_conditions tambem nao
        # extraia essa frase (fix no mesmo commit).
        if conds.get('self_rested') and not card.rested:
            return False
        if conds.get('has_don_attached'):
            attached = getattr(me.leader, 'don_attached', 0) + sum(
                getattr(c, 'don_attached', 0) for c in me.field_chars)
            if attached <= 0:
                return False
        # "if you have a total of N or more given DON!! cards" -- limiar
        # numerico (achado 16/07, OP12-015/OP12-024/OP13-112), distinto
        # de has_don_attached (so checa >=1). Mesma soma lider+campo.
        if 'don_attached_total_gte' in conds:
            attached_total = getattr(me.leader, 'don_attached', 0) + sum(
                getattr(c, 'don_attached', 0) for c in me.field_chars)
            if attached_total < conds['don_attached_total_gte']:
                return False
        # "if you have activated an Event with a base cost of N or more
        # during this turn" -- rastreamento de EVENTO ativado NESTE turno
        # (achado 16/07, OP15-002 Lucy). Populado em _play_card()/
        # _put_into_play() sempre que um EVENT sai da mao.
        if 'event_activated_cost_gte_this_turn' in conds:
            threshold = conds['event_activated_cost_gte_this_turn']
            if not any(c >= threshold for c in me.events_activated_costs_this_turn):
                return False
        if 'don_on_field_gte' in conds and me.don_on_field() < conds['don_on_field_gte']:
            return False
        if 'don_on_field_lte' in conds and me.don_on_field() > conds['don_on_field_lte']:
            return False
        if 'don_on_field_zero_or_gte' in conds:
            n = me.don_on_field()
            if not (n == 0 or n >= conds['don_on_field_zero_or_gte']):
                return False
        if 'opp_don_on_field_gte' in conds and opp.don_on_field() < conds['opp_don_on_field_gte']:
            return False
        if 'opp_don_on_field_lte' in conds and opp.don_on_field() > conds['opp_don_on_field_lte']:
            return False
        if conds.get('don_on_field_lte_opp') and me.don_on_field() > opp.don_on_field():
            return False
        if ('don_fewer_than_opp_by_gte' in conds
                and opp.don_on_field() - me.don_on_field()
                < conds['don_fewer_than_opp_by_gte']):
            return False
        # "if the number of cards in your hand is at least N less than
        # the number in your opponent's hand" -- mesma semantica de
        # don_fewer_than_opp_by_gte, so que comparando o tamanho da MAO
        # (achado 19/07, OP09-092, unica carta no banco com essa forma).
        if ('hand_fewer_than_opp_by_gte' in conds
                and len(opp.hand) - len(me.hand)
                < conds['hand_fewer_than_opp_by_gte']):
            return False
        if 'chars_rested_gte' in conds:
            tipo_rc = conds.get('chars_rested_gte_type_filter')
            if tipo_rc:
                # "N or more rested [Tipo] type Characters" -- so conta
                # os restados que TAMBEM batem o filtro de tipo (achado
                # 19/07, OP10-033 Nami, unica carta no banco com essa
                # forma exata: condicao inteira sumia, lock disparava
                # sempre).
                n_rested = sum(1 for c in me.field_chars
                               if c.rested and _norm_type_text(tipo_rc) in _norm_type_text(c.sub_types))
            else:
                n_rested = sum(1 for c in me.field_chars if c.rested)
            if n_rested < conds['chars_rested_gte']:
                return False
        if 'opp_chars_rested_gte' in conds:
            # simetrico a chars_rested_gte, mas do lado do OPONENTE (achado
            # 16/07, ST24-004/OP01-032).
            n_rested_opp = sum(1 for c in opp.field_chars if c.rested)
            if n_rested_opp < conds['opp_chars_rested_gte']:
                return False
        if 'opp_hand_gte' in conds and len(opp.hand) < conds['opp_hand_gte']:
            return False
        if 'chars_gte' in conds:
            cost_filter = conds.get('chars_gte_cost_filter')
            type_filter = conds.get('chars_gte_type_filter')
            if cost_filter is not None:
                contagem = sum(1 for c in me.field_chars if c.cost >= cost_filter)
            elif type_filter is not None:
                # Lista de tipos (OR) -- "N or more [TipoA] or [TipoB] type
                # Characters" (achado 19/07, OP07-050: 2 tipos alternativos,
                # nao so 1). String unica preserva o comportamento antigo.
                tipos = type_filter if isinstance(type_filter, list) else [type_filter]
                matching = [c for c in me.field_chars
                            if any(tp.lower() in (c.sub_types or '').lower() for tp in tipos)]
                # 'chars_gte_color_filter' -- "a [Cor] [Tipo] type Character"
                # (achado 28/07, bloco HANDOFF 393: Scratchmen Apoo OP10-108,
                # Charlotte Anana OP11-065, Ripper OP11-096). 'chars_gte_
                # exclude_self' -- "...other than [Nome]"/"other than this
                # Character": exclui a propria `card` que carrega a condicao
                # (mesma exclusao de no_other_named, mas contando PRESENCA em
                # vez de ausencia -- sem isso a carta contava a si mesma e a
                # condicao virava sempre-verdadeira). Ambos combinam com
                # qualquer chars_gte_type_filter existente, nao so os casos
                # novos -- generaliza pra qualquer carta que use as duas
                # clausulas juntas.
                color_filter = conds.get('chars_gte_color_filter')
                if color_filter:
                    matching = [c for c in matching if c.color.lower() == color_filter.lower()]
                if conds.get('chars_gte_exclude_self'):
                    matching = [c for c in matching if c is not card]
                if conds.get('chars_gte_distinct_names'):
                    # "N [Tipo] type Characters with DIFFERENT card names"
                    # -- conta NOMES UNICOS entre os que batem o tipo, nao
                    # o total de cartas (achado 19/07, OP16-038, unica
                    # carta no banco com essa forma exata: 2 copias do
                    # mesmo nome nao deveriam contar como 2).
                    contagem = len({c.name for c in matching})
                else:
                    contagem = len(matching)
            else:
                contagem = len(me.field_chars)
            if contagem < conds['chars_gte']:
                return False
        if 'chars_lte' in conds:
            # 'chars_lte_power_filter' -- so conta Characters com power>=N
            # (achado 16/07, EB02-022/OP10-010), distinto do chars_lte puro
            # (conta todos).
            power_filter = conds.get('chars_lte_power_filter')
            contagem_lte = (sum(1 for c in me.field_chars if c.power >= power_filter)
                             if power_filter is not None else len(me.field_chars))
            if contagem_lte > conds['chars_lte']:
                return False
        if 'chars_fewer_than_opp_by_gte' in conds:
            diff = len(opp.field_chars) - len(me.field_chars)
            if diff < conds['chars_fewer_than_opp_by_gte']:
                return False
        if 'total_chars_cost_gte' in conds:
            if sum(c.cost for c in me.field_chars) < conds['total_chars_cost_gte']:
                return False
        if 'hand_lte' in conds and len(me.hand) > conds['hand_lte']:
            return False
        if 'hand_gte' in conds and len(me.hand) < conds['hand_gte']:
            return False
        if 'hand_eq' in conds and len(me.hand) != conds['hand_eq']:
            return False
        if 'life_and_hand_total_lte' in conds and \
                (me.life_count() + len(me.hand)) > conds['life_and_hand_total_lte']:
            return False
        if 'deck_lte' in conds and len(me.deck) > conds['deck_lte']:
            return False
        if conds.get('just_played') and not getattr(card, 'just_played', False):
            return False
        if 'leader_is' in conds:
            if conds['leader_is'].lower() not in me.leader.name.lower():
                return False
        # "if your Leader is [Nomeado] OR has {Tipo} type" -- OR entre as
        # duas alternativas (distinto de leader_is puro acima, que perdia
        # a metade do tipo). Achado 05/08, OP17-003/007.
        if 'leader_is_or_type' in conds:
            alvo = conds['leader_is_or_type']
            nome_ok = alvo['name'].lower() in me.leader.name.lower()
            tipo_ok = _norm_type_text(alvo['type']) in _norm_type_text(me.leader.sub_types)
            if not (nome_ok or tipo_ok):
                return False
        if 'opp_leader_attribute' in conds:
            opp_attr = (getattr(opp.leader, 'attribute', '') or '').lower()
            if conds['opp_leader_attribute'].lower() not in opp_attr:
                return False
        if 'leader_attribute' in conds:
            my_attr = (getattr(me.leader, 'attribute', '') or '').lower()
            if conds['leader_attribute'].lower() not in my_attr:
                return False
        if 'don_rested_gte' in conds and me.don_rested < conds['don_rested_gte']:
            return False
        if 'leader_type_includes' in conds:
            if _norm_type_text(conds['leader_type_includes']) not in _norm_type_text(me.leader.sub_types):
                return False
        if 'leader_type' in conds:
            if _norm_type_text(conds['leader_type']) not in _norm_type_text(me.leader.sub_types):
                return False
        if conds.get('leader_multicolor'):
            colors = set(me.leader.color.replace('/', ' ').split())
            if len(colors) < 2:
                return False
        if 'other_char_power_gte' in conds:
            outros = [c for c in me.field_chars if c is not card]
            filter_type = conds.get('other_char_power_gte_type')
            if filter_type:
                outros = [c for c in outros
                          if _norm_type_text(filter_type) in _norm_type_text(c.sub_types)]
            filter_names = [n.lower() for n in conds.get('other_char_power_gte_names', [])]
            if filter_names:
                outros = [c for c in outros
                          if any(n in c.name.lower() for n in filter_names)]
            power_of = ((lambda c: c.power) if conds.get('other_char_power_uses_base')
                        else (lambda c: c.effective_power(True)))
            if not outros or max(power_of(c) for c in outros) < conds['other_char_power_gte']:
                return False
        if 'other_char_cost_gte' in conds:
            outros = [c for c in me.field_chars if c is not card]
            # filtro de tipo (achado 17/07, EB01-001/OP12-098): mesma
            # FORMA ja coberta pra other_char_power_gte_type acima.
            filter_type_cost = conds.get('other_char_cost_gte_type')
            if filter_type_cost:
                outros = [c for c in outros
                          if _norm_type_text(filter_type_cost) in _norm_type_text(c.sub_types)]
            if not outros or max(c.cost for c in outros) < conds['other_char_cost_gte']:
                return False
        if 'no_other_named' in conds:
            # "if you have no other [Nome]" -- condicao SEM implementacao
            # nenhuma ate 16/07 (achado via OP12-102, generalizado por
            # busca global pra 7 cartas: EB01-012, EB02-018, EB04-031,
            # OP07-060, OP08-074, OP12-102, OP15-080). Verdadeira quando
            # NAO existe outra copia (por nome) da carta nomeada no proprio
            # campo, excluindo a propria `card` que carrega o efeito.
            needle = conds['no_other_named'].lower()
            cost_eq = conds.get('no_other_named_cost_eq')
            outros = [c for c in me.field_chars
                      if c is not card and needle in c.name.lower()]
            if cost_eq is not None:
                outros = [c for c in outros if c.cost == cost_eq]
            if outros:
                return False
        if 'no_char_power_gte' in conds:
            # "if/and you have NO Characters with N (base) power or more"
            # -- negacao de other_char_power_gte (achado 16/07, EB03-004).
            threshold = conds['no_char_power_gte']
            if any(c.power >= threshold for c in me.field_chars):
                return False
        if 'no_char_cost_gte' in conds:
            # "if you have NO Characters with a cost of N or more" --
            # mesma familia negada de no_char_power_gte, mas por CUSTO sem
            # filtro de tipo (achado 19/07, OP12-096: gate NEGADO do teto
            # baseline de um K.O., complementar ao other_char_cost_gte que
            # gate o teto UPGRADED).
            threshold_cc = conds['no_char_cost_gte']
            if any(c.cost >= threshold_cc for c in me.field_chars):
                return False
        if 'no_own_chars_cost_gte_count' in conds:
            # "if you do NOT have N Characters with a cost of M or more"
            # -- CONTAGEM (nao existencia) negada, SO dos proprios
            # field_chars (distinto de board_chars_cost_gte_count, que
            # soma os 2 lados). Achado 19/07, OP09-051.
            rule_cc = conds['no_own_chars_cost_gte_count']
            n_cc = sum(1 for c in me.field_chars if c.cost >= rule_cc['cost_gte'])
            if n_cc >= rule_cc['count_gte']:
                return False
        if 'no_char_type_cost_gte' in conds:
            # "if you have no Characters with a type including 'X' and a
            # cost of N or more" -- mesma familia negada, filtro de
            # TIPO+CUSTO (achado 19/07, OP16-017).
            rule = conds['no_char_type_cost_gte']
            tipo_ncc = _norm_type_text(rule['type'])
            if any(tipo_ncc in _norm_type_text(c.sub_types) and c.cost >= rule['cost_gte']
                   for c in me.field_chars):
                return False
        if 'has_named_character' in conds:
            # "if/and you have a [Nome] Character" -- presenca simples por
            # nome no proprio campo (achado 16/07, OP08-109 e familia:
            # OP02-031, OP07-030). Distinto de no_other_named (que exclui
            # a propria carta e checa AUSENCIA).
            needle = conds['has_named_character'].lower()
            if not any(needle in c.name.lower() for c in me.field_chars):
                return False
        if 'has_other_named' in conds:
            # "if you have a [Nome] other than this Character" -- presenca
            # de OUTRA copia (por nome) alem da propria `card` (achado
            # 28/07, bloco HANDOFF 393: Kung Fu Jugon OP04-005). Distinto
            # de has_named_character (nao exclui self -- daria sempre
            # verdadeiro quando o Nome e o proprio nome da carta). Espelha
            # no_other_named (mesma exclusao, condicao invertida: aqui
            # exige PRESENCA, la exige AUSENCIA).
            needle_other = conds['has_other_named'].lower()
            if not any(c is not card and needle_other in c.name.lower()
                       for c in me.field_chars):
                return False
        if 'has_named_card_on_field' in conds:
            # "if you have [Nome] on your field" -- presenca de uma carta
            # nomeada em QUALQUER zona de campo (Character OU Stage --
            # achado 28/07, Klabautermann EB02-033: "[Merry Go]" e um
            # Stage, has_named_character so cobre field_chars).
            needle_field = conds['has_named_card_on_field'].lower()
            candidatos_campo = list(me.field_chars)
            if me.field_stage is not None:
                candidatos_campo.append(me.field_stage)
            if not any(needle_field in c.name.lower() for c in candidatos_campo):
                return False
        if 'has_named_characters' in conds:
            # "if you have [Nome1] and [Nome2]" -- AMBOS precisam estar em
            # campo (achado 19/07, OP15-064/OP15-072).
            power_eq_mn = conds.get('has_named_characters_power_eq')
            for nome in conds['has_named_characters']:
                needle2 = nome.lower()
                matching = [c for c in me.field_chars if needle2 in c.name.lower()]
                if not matching:
                    return False
                # "[Nome1] and [Nome2] Characters with N base power" --
                # o nomeado TAMBEM precisa ter esse power exato (achado
                # 19/07, ST30-016, unica carta no banco com essa forma).
                if power_eq_mn is not None and not any(c.power == power_eq_mn for c in matching):
                    return False
        if 'has_named_characters_in_trash' in conds:
            # "if you have [Nome1] and [Nome2] in your trash" -- presenca
            # no TRASH, nao no campo (achado 19/07, OP08-006 Chessmarimo,
            # unica carta no banco com essa forma).
            for nome in conds['has_named_characters_in_trash']:
                needle3 = nome.lower()
                if not any(needle3 in c.name.lower() for c in me.trash):
                    return False
        if 'own_rested_cards_gte' in conds:
            # "if/and you have N or more rested cards" -- QUALQUER carta
            # rested do proprio lado (DON + Characters + Leader + Stage),
            # simetrico ao ja existente opp_rested_cards_gte. Achado 16/07
            # (ST16-003).
            rested = me.don_rested + sum(1 for c in me.field_chars if c.rested)
            rested += int(bool(getattr(me.leader, 'rested', False)))
            rested += int(bool(me.field_stage and getattr(me.field_stage, 'rested', False)))
            if rested < conds['own_rested_cards_gte']:
                return False
        if 'self_power_gte' in conds and card.effective_power(True) < conds['self_power_gte']:
            return False
        if 'leader_power_gte' in conds and me.leader.effective_power(True) < conds['leader_power_gte']:
            return False
        if 'leader_power_lte' in conds and me.leader.effective_power(True) > conds['leader_power_lte']:
            return False
        # "if your OPPONENT's Leader has N power or more" -- distinto do
        # par acima (que e sobre o PROPRIO lider). Achado 05/08, OP17-034
        # Rockstar, unica carta no banco.
        if ('opp_leader_power_gte' in conds
                and opp.leader.effective_power(True) < conds['opp_leader_power_gte']):
            return False
        if ('leader_name_includes' in conds
                and conds['leader_name_includes'].lower() not in me.leader.name.lower()):
            return False
        if 'opp_rested_cards_gte' in conds:
            rested = opp.don_rested + sum(1 for c in opp.field_chars if c.rested)
            rested += int(bool(getattr(opp.leader, 'rested', False)))
            rested += int(bool(opp.field_stage and getattr(opp.field_stage, 'rested', False)))
            if rested < conds['opp_rested_cards_gte']:
                return False
        if 'opp_char_cost_eq' in conds:
            if not any(c.cost == conds['opp_char_cost_eq'] for c in opp.field_chars):
                return False
        if 'events_in_trash_gte' in conds:
            n_events = sum(1 for c in me.trash if c.card_type.lower() == 'event')
            if n_events < conds['events_in_trash_gte']:
                return False
        if 'board_has_cost' in conds or 'board_has_cost_gte' in conds:
            # condicao de existencia: QUALQUER Character no jogo (os dois
            # campos) com custo == N exato ou >= M.
            todos = list(me.field_chars) + list(opp.field_chars)
            exatos = set(conds.get('board_has_cost', []))
            gte = conds.get('board_has_cost_gte')
            existe = any(
                c.cost in exatos or (gte is not None and c.cost >= gte)
                for c in todos)
            if not existe:
                return False
        if 'board_chars_cost_gte_count' in conds:
            # CONTAGEM (distinto de board_has_cost_gte, que so checa
            # existencia de 1) -- achado 16/07, EB04-045.
            spec = conds['board_chars_cost_gte_count']
            todos = list(me.field_chars) + list(opp.field_chars)
            n = sum(1 for c in todos if c.cost >= spec['cost_gte'])
            if n < spec['count_gte']:
                return False
        if 'opp_char_power_gte' in conds:
            if not opp.field_chars or max(c.effective_power(False) for c in opp.field_chars) < conds['opp_char_power_gte']:
                return False
        if 'opp_char_cost_eq_or_gte' in conds:
            rule = conds['opp_char_cost_eq_or_gte']
            if not any(c.cost == rule['eq'] or c.cost >= rule['gte'] for c in opp.field_chars):
                return False
        if 'board_has_power_gte' in conds:
            # condicao de existencia generica: QUALQUER Character no jogo
            # (os dois campos) com power >= N. Mesma semantica de
            # board_has_cost, mas para power -- usada por
            # cannot_attack_self_unless (ex: EB04-051).
            todos = list(me.field_chars) + list(opp.field_chars)
            if not todos or max(c.effective_power(True) for c in todos) < conds['board_has_power_gte']:
                return False
        if 'opp_chars_power_gte_count' in conds:
            # CONTAGEM (nao existencia): precisa de >= count Characters
            # distintos no campo do OPONENTE, cada um com power >= power_gte
            # -- usada por cannot_attack_self_unless (ex: EB04-005) e por
            # efeitos condicionais a board do oponente (ex: OP09-005).
            spec = conds['opp_chars_power_gte_count']
            n = sum(1 for c in opp.field_chars if c.effective_power(False) >= spec['power_gte'])
            if n < spec['count']:
                return False
        if 'opp_chars_gte' in conds and len(opp.field_chars) < conds['opp_chars_gte']:
            return False
        if 'opp_chars_lte' in conds and len(opp.field_chars) > conds['opp_chars_lte']:
            return False
        if 'self_type' in conds and conds['self_type'] not in card.sub_types.lower():
            return False
        if 'only_field_type' in conds:
            tipo = conds['only_field_type'].lower()
            if not me.field_chars or any(tipo not in c.sub_types.lower() for c in me.field_chars):
                return False
        if conds.get('has_face_up_life') and not any(c.life_face_up for c in me.life):
            return False

        return True

    # ── Pagamento de custos ──────────────────────────────────────────────────

    def _pay_costs(self, costs: list, card: Card) -> bool:
        """Verifica e paga custos. Retorna False se não pode pagar.
        Registra o que foi pago em self._cost_logs (para o replay mostrar)."""
        self._cost_logs = []
        # Preflight de trash -> fundo antes de qualquer mutacao. Em custos
        # compostos, rest_self aparece primeiro; sem isto a carta ficaria
        # restada mesmo quando o restante do custo fosse impagavel.
        from optcg_engine.rules_facade import eligible_cards
        for pending in costs:
            if pending.get('type') == 'place_from_trash_bottom_deck':
                source = self.me.trash
            elif pending.get('type') == 'place_own_character_bottom_deck':
                source = self.me.field_chars
            else:
                continue
            candidates = eligible_cards(
                source,
                filter_text=pending.get('filter_type', ''),
                power_eq=pending.get('power_eq'),
                exclude_card=card if pending.get('exclude_self') else None,
            )
            if len(candidates) < pending.get('count', 1):
                return False
        # Mesmo preflight para place_self_bottom_deck: se o custo exige um
        # parceiro nomeado do trash (Kin'emon OP10-026/027) que nao existe,
        # aborta ANTES de mover a propria carta (card) pro fundo do deck --
        # senao a carta-fonte iria pro fundo do deck sem o efeito nunca ser
        # pago (custo parcial, estado inconsistente).
        for pending in costs:
            if pending.get('type') != 'place_self_bottom_deck':
                continue
            if not pending.get('trash_partner_name'):
                continue
            candidates = eligible_cards(
                self.me.trash,
                name_or_code=pending.get('trash_partner_name', ''),
                power_eq=pending.get('trash_partner_power_eq'),
                power_gte=pending.get('trash_partner_power_gte'),
                power_lte=pending.get('trash_partner_power_lte'),
            )
            if len(candidates) < pending.get('trash_partner_count', 1):
                return False
        for cost in costs:
            ctype = cost['type']
            if ctype == 'rest_self':
                if card.rested:
                    return False
                card.rested = True
                self._cost_logs.append(f'custo: restou {card.name[:18]}')
            elif ctype == 'rest_self_and_leader_or_stage':
                # Custo composto: a propria carta E um Leader/Stage com
                # filtro de tipo, AMBOS precisam estar disponiveis (nao
                # rested) antes de pagar qualquer um -- pagamento parcial
                # deixaria o jogo em estado inconsistente (carta restada
                # sem o efeito ter sido de fato pago).
                if card.rested:
                    return False
                filter_type = cost.get('filter_type', '').lower()
                candidato = None
                if filter_type in self.me.leader.sub_types.lower() and not self.me.leader.rested:
                    candidato = self.me.leader
                elif (self.me.field_stage and filter_type in self.me.field_stage.sub_types.lower()
                      and not self.me.field_stage.rested):
                    candidato = self.me.field_stage
                if candidato is None:
                    return False
                card.rested = True
                candidato.rested = True
                self._cost_logs.append(
                    f'custo: restou {card.name[:15]} e {candidato.name[:15]}')
            elif ctype == 'rest_own_leader_or_stage':
                # Custo UNICO (nao composto, distinto de
                # rest_self_and_leader_or_stage acima): so o Leader/Stage
                # com filtro de tipo -- a propria carta ativadora NAO
                # resta. Achado 19/07, OP10-043 Moocy, unica carta no
                # banco com essa forma exata.
                filter_type = cost.get('filter_type', '').lower()
                candidato = None
                if filter_type in self.me.leader.sub_types.lower() and not self.me.leader.rested:
                    candidato = self.me.leader
                elif (self.me.field_stage and filter_type in self.me.field_stage.sub_types.lower()
                      and not self.me.field_stage.rested):
                    candidato = self.me.field_stage
                if candidato is None:
                    return False
                candidato.rested = True
                self._cost_logs.append(f'custo: restou {candidato.name[:15]}')
            elif ctype == 'rest_don':
                count = cost.get('count', 1)
                if self.me.don_available < count:
                    return False
                self.me.don_available -= count
                self.me.don_rested += count
                self._cost_logs.append(f'custo: restou {count} DON')
            elif ctype == 'reveal_from_hand':
                # Custo de REVELAR N cartas com filtro de tipo (achado
                # 15/07, OP08-044 Kingdew) OU de power+card_type (achado
                # 16/07, OP16-002/003/007/010/011, ST30-004: "you may
                # reveal N Character cards with X power from your hand")
                # -- so exige TER as cartas na mao, nao remove nada
                # (revelar != trashar/descartar).
                count = cost.get('count', 1)
                matches = self._reveal_from_hand_matches(cost)
                if len(matches) < count:
                    return False
                self._cost_logs.append(f'custo: revelou {count} carta(s) '
                                        f'com tipo {cost.get("filter_type","")}')
            elif ctype == 'trash_from_hand':
                count = cost.get('count', 1)
                # "trash N card(s) with a [Trigger] from your hand" (leader
                # Teach OP16-080 e outras 8 cartas): custo so pode ser pago
                # com carta que TEM [Trigger] -- sem esse filtro o engine
                # considerava a mao inteira como elegivel.
                from optcg_engine.rules_facade import eligible_cards
                pool = eligible_cards(
                    self.me.hand,
                    filter_text=cost.get('filter_type', ''),
                    color=cost.get('color', ''),
                    power_lte=cost.get('power_lte'),
                    power_gte=cost.get('power_gte'),
                    power_eq=cost.get('power_eq'),
                    cost_lte=cost.get('cost_lte'),
                    cost_gte=cost.get('cost_gte'),
                    cost_eq=cost.get('cost_eq'),
                )
                if cost.get('has_trigger'):
                    pool = [c for c in pool if c.has_trigger]
                if len(pool) < count:
                    return False
                trashed = []
                trashed_names_actual = []
                for _ in range(count):
                    worst = self._choose_to_trash(pool)
                    if worst:
                        remove_by_identity(self.me.hand, worst)
                        remove_by_identity(pool, worst)
                        self.me.trash.append(worst)
                        trashed.append(worst.name[:15])
                        trashed_names_actual.append(worst.name)
                if trashed:
                    self._cost_logs.append(f'custo: trashou da mão: {", ".join(trashed)}')
                # Memoria pra "play ... with the same card name as the
                # trashed card" (achado 16/07, EB02-039 GERMA 66) -- um step
                # POSTERIOR no mesmo bloco pode filtrar pelo nome do que foi
                # trashado aqui. Atributo dedicado (nao _last_selected) pra
                # nao colidir com o mecanismo de selecao entre steps ja
                # existente (negate_effect/play_from_deck/buff_power).
                self._last_trashed_names = trashed_names_actual
            elif ctype == 'trash_any_from_hand':
                # "you may trash ANY NUMBER of [filtro] cards from your
                # hand" -- quantidade VARIAVEL (0 ate o total elegivel),
                # distinto de trash_from_hand (contagem fixa). Sempre
                # pagavel (0 e uma escolha valida). Achado 19/07, OP03-001/
                # OP06-014/OP15-002/P-051/ST16-002: custo inteiro ausente
                # (o buff associado, buff_power_per_count/source=
                # trashed_hand_this_effect, virava um +1000 fixo sem
                # nenhum custo). Greedy: trasha TODAS as elegiveis --
                # efeito reativo imediato (defesa em combate), sem valor
                # de manter essas cartas na mao supera o buff de power.
                from optcg_engine.rules_facade import card_matches_filter
                pool = list(self.me.hand)
                filter_type = cost.get('filter_type', '')
                if filter_type:
                    pool = [c for c in pool if card_matches_filter(c, filter_type)]
                card_types = cost.get('card_types')
                if card_types:
                    pool = [c for c in pool if c.card_type in card_types]
                trashed = []
                for c in pool:
                    remove_by_identity(self.me.hand, c)
                    self.me.trash.append(c)
                    trashed.append(c.name[:15])
                self._last_cost_trash_any_count = len(trashed)
                if trashed:
                    self._cost_logs.append(f'custo: trashou da mão: {", ".join(trashed)}')
            elif ctype == 'bounce_any_own_character':
                # "you may return ANY NUMBER of Characters on your field
                # to the owner's hand" -- quantidade VARIAVEL (0 ate o
                # total em campo), companheiro de buff_power_per_count/
                # source=bounced_own_this_effect. Achado 19/07, P-059,
                # unica carta no banco. Greedy (devolve TODOS): mesma
                # aproximacao ja aceita pra trash_any_from_hand -- efeito
                # reativo em combate ([Counter]), as cartas voltam pra
                # mao (nao sao perdidas), podem ser rejogadas depois.
                bounced = []
                for c in list(self.me.field_chars):
                    remove_character_from_field(self.me, c, 'hand')
                    bounced.append(c.name[:15])
                self._last_cost_bounce_any_count = len(bounced)
                if bounced:
                    self._cost_logs.append(f'custo: devolveu do campo: {", ".join(bounced)}')
            elif ctype == 'rest_any_don':
                # "you may rest ANY NUMBER of your DON!! cards" -- quantidade
                # VARIAVEL (0 ate o total ativo), companheiro de
                # buff_power_per_count/source=rested_don_this_effect. Achado
                # 29/07, OP13-001 Luffy, unica carta no banco. Greedy (resta
                # TODO o DON ativo): condicao do bloco ja exige "5 ou menos
                # DON ativo" (don_lte) pra sequer chegar aqui, e o efeito e
                # reativo em [On Your Opponent's Attack] -- nao ha valor em
                # manter DON ativo parado durante o turno do OPONENTE (nao e
                # usado pra bloquear/counterar), entao restar tudo pro buff
                # de combate e estritamente melhor, mesma aproximacao ja
                # aceita pra trash_any_from_hand/bounce_any_own_character.
                rested_count = self.me.don_available
                self.me.don_rested += rested_count
                self.me.don_available = 0
                self._last_cost_rest_any_don_count = rested_count
                if rested_count:
                    self._cost_logs.append(f'custo: restou {rested_count} DON!! ativo')
            elif ctype == 'trash_typed_hand_or_named_hand_field':
                from optcg_engine.rules_facade import eligible_cards

                count = cost.get('count', 1)
                typed_hand = eligible_cards(
                    self.me.hand, filter_text=cost.get('filter_type', ''))
                named = (cost.get('alternate_name') or '').lower()
                named_hand = [c for c in self.me.hand if named in c.name.lower()]
                named_field = [c for c in self.me.field_chars if named in c.name.lower()]
                if self.me.field_stage and named in self.me.field_stage.name.lower():
                    named_field.append(self.me.field_stage)
                options = [('hand', c) for c in typed_hand + named_hand]
                options.extend(('field', c) for c in named_field)
                unique = []
                seen = set()
                for zone, candidate in options:
                    if id(candidate) not in seen:
                        unique.append((zone, candidate))
                        seen.add(id(candidate))
                if len(unique) < count:
                    return False
                for _ in range(count):
                    zone, chosen = min(
                        unique,
                        key=lambda item: (self._trash_value(item[1]) if item[0] == 'hand'
                                          else item[1].board_value() * 10))
                    if zone == 'hand':
                        remove_by_identity(self.me.hand, chosen)
                        self.me.trash.append(chosen)
                    elif chosen is self.me.field_stage:
                        self.me.field_stage = None
                        self.me.trash.append(chosen)
                    else:
                        # remove_character_from_field ja devolve DON!! anexado
                        # ao banco (rested) e ja poe a carta no trash -- nao
                        # remover na mao com remove_by_identity aqui (achado
                        # 01/08, investigando o bug de conservacao de DON:
                        # este era o unico ponto que ainda tirava um
                        # Character do campo sem passar pela funcao
                        # centralizada, vazando DON!! fantasma se a carta
                        # trashada tivesse DON anexado).
                        remove_character_from_field(self.me, chosen, 'trash')
                    unique = [item for item in unique if item[1] is not chosen]
                self._cost_logs.append(f'custo: trashou {count} carta(s) por tipo/nome')
            elif ctype == 'life_to_hand':
                count = cost.get('count', 1)
                if self.me.cant_take_life_this_turn or len(self.me.life) < count:
                    return False
                source = cost.get('source', 'life_top')
                taken = []
                for _ in range(count):
                    idx = 0 if source == 'life_bottom' else -1
                    life_card = self.me.life.pop(idx)
                    life_card.life_face_up = False
                    self.me.hand.append(life_card)
                    taken.append(life_card.name[:15])
                self._cost_logs.append(f'custo: pegou da Life: {", ".join(taken)}')
            elif ctype == 'trash_char_or_hand':
                from optcg_engine.rules_facade import eligible_cards

                # Custo com ESCOLHA (ex: leader Imu): trashar 1 character próprio
                # (com filtro de tipo) OU 1 carta da mão. Resolve gastando o
                # recurso de MENOR valor — naturalmente trasha um character só
                # quando ele vale menos que descartar da mão. (Escolha fina de
                # "trashar p/ encher o trash e ligar imunidade" = Bug B, futuro.)
                count = cost.get('count', 1)
                for _ in range(count):
                    chars = eligible_cards(
                        self.me.field_chars,
                        filter_text=cost.get('filter_type', ''),
                    )
                    pior_char = min(chars, key=lambda c: c.board_value(), default=None)
                    pior_mao = self._choose_to_trash(self.me.hand)
                    if pior_char is None and pior_mao is None:
                        return False
                    # Chars ATIVOS (podem atacar este turno) nunca são descartados
                    # enquanto há carta na mão disponível. O jogador correto ataca
                    # primeiro e só trasha o char depois (ou usa mão). MAS só
                    # protege quem tem poder > 0 -- um char de 0 poder (ex: Saint
                    # Shalria, cujo valor inteiro já foi gasto no On Play e nunca
                    # conecta um ataque) não ganha nada de ficar "ativo", e a
                    # guarda achava real 09/07 (log 19.25.50, usuário: "Imu pode
                    # dar alvo em Shalria") que a guarda protegia ele do mesmo
                    # jeito que um atacante de verdade, forçando trash de carta
                    # da mão sem necessidade.
                    if pior_mao is not None and pior_char is not None:
                        if (pior_char.power > 0 and not pior_char.rested
                                and not pior_char.just_played
                                and not getattr(pior_char, 'cannot_attack_until', False)):
                            # char ativo: forçar trash da mão
                            remove_by_identity(self.me.hand, pior_mao)
                            self.me.trash.append(pior_mao)
                            self._cost_logs.append(f'custo: trashou da mão {pior_mao.name[:14]}')
                            continue
                    # comparar perda real: campo e mao usam escalas proximas.
                    val_char = pior_char.board_value() * 10 if pior_char else 10**9
                    # GamePlan (HANDOFF #119): enquanto o trash ainda nao
                    # bateu o alvo do deck (ex: Imu, 7 pra imunidade dos
                    # Celestial Dragons), trashar personagem pesa MENOS —
                    # o proprio deck foi construido pra usar a lixeira como
                    # recurso, nao so como perda de campo.
                    if pior_char is not None:
                        plano = compute_game_plan(self.me)
                        if plano['trash_target'] and len(self.me.trash) < plano['trash_target']:
                            val_char *= 0.5
                    val_mao = self._trash_value(pior_mao) if pior_mao else 10**9
                    if pior_char is not None and val_char <= val_mao:
                        remove_character_from_field(self.me, pior_char, 'trash')
                        self._cost_logs.append(f'custo: trashou character {pior_char.name[:14]}')
                    elif pior_mao is not None:
                        remove_by_identity(self.me.hand, pior_mao)
                        self.me.trash.append(pior_mao)
                        self._cost_logs.append(f'custo: trashou da mão {pior_mao.name[:14]}')
            elif ctype == 'trash_self':
                if contains_identity(self.me.field_chars, card):
                    remove_character_from_field(self.me, card, 'trash')
                    self._cost_logs.append(f'custo: trashou {card.name[:18]} (ele mesmo)')
            elif ctype == 'place_self_bottom_deck':
                # Custo composto: move a PROPRIA carta (card, do campo) pro
                # fundo do PROPRIO deck, opcionalmente junto com N carta(s)
                # NOMEADA(s) do trash (mesmo criterio de power do custo
                # trash_own_character: eq/gte/lte contra card.power, ja base
                # power no nosso modelo). O preflight (topo de _pay_costs)
                # ja garantiu que o parceiro do trash existe ANTES de
                # qualquer mutacao aqui; ainda assim revalidamos ao vivo
                # (fresh eligible_cards) porque um custo ANTERIOR na mesma
                # lista pode ter alterado o trash entre o preflight e aqui
                # -- mesmo padrao do bloco place_from_trash_bottom_deck
                # abaixo. Achado 17/07: OP06-016/OP09-008/P-013 (self-only)
                # e Kin'emon OP10-026/027 (self + parceiro), custo inteiro
                # ausente antes -- tratado como gratis.
                partner_name = cost.get('trash_partner_name')
                partner_moved = []
                if partner_name:
                    candidatos = eligible_cards(
                        self.me.trash,
                        name_or_code=partner_name,
                        power_eq=cost.get('trash_partner_power_eq'),
                        power_gte=cost.get('trash_partner_power_gte'),
                        power_lte=cost.get('trash_partner_power_lte'),
                    )
                    partner_count = cost.get('trash_partner_count', 1)
                    if len(candidatos) < partner_count:
                        return False
                    for _ in range(partner_count):
                        alvo = candidatos.pop()
                        remove_by_identity(self.me.trash, alvo)
                        self.me.deck.insert(0, alvo)   # fundo do deck = inicio da lista
                        partner_moved.append(alvo.name[:14])
                if not contains_identity(self.me.field_chars, card):
                    return False
                remove_character_from_field(self.me, card, 'deck_bottom')
                log = f'custo: {card.name[:18]} foi para o fundo do deck'
                if partner_moved:
                    log += f' junto com (trash): {", ".join(partner_moved)}'
                self._cost_logs.append(log)
            elif ctype == 'return_own_character_to_hand':
                from optcg_engine.rules_facade import eligible_cards
                count = cost.get('count', 1)
                candidates = eligible_cards(
                    self.me.field_chars,
                    cost_gte=cost.get('cost_gte'),
                    filter_text=cost.get('filter_type', ''),
                    exclude_name=cost.get('exclude', ''),
                    exclude_card=card if cost.get('exclude_self') else None,
                )
                if len(candidates) < count:
                    return False
                returned = []
                for _ in range(count):
                    target = min(candidates, key=lambda c: c.board_value())
                    remove_character_from_field(self.me, target, 'hand')
                    remove_by_identity(candidates, target)
                    returned.append(target.name[:15])
                self._cost_logs.append(f'custo: devolveu para a mao: {", ".join(returned)}')
            elif ctype == 'place_own_character_bottom_deck':
                candidates = eligible_cards(
                    self.me.field_chars,
                    filter_text=cost.get('filter_type', ''),
                    power_eq=cost.get('power_eq'),
                    exclude_card=card if cost.get('exclude_self') else None,
                )
                count = cost.get('count', 1)
                if len(candidates) < count:
                    return False
                # Sacrifica os `count` de MENOR board_value (mantem os
                # melhores em campo -- essa parte ja estava certa), mas
                # insere no fundo do deck da mais forte pra mais fraca
                # ENTRE OS ESCOLHIDOS: cada insert(0, ...) empurra os
                # anteriores pra mais perto do topo, entao processar do
                # mais forte primeiro deixa exatamente ele mais perto do
                # topo (comprado antes). Achado 19/07: a versao antiga
                # (min() repetido, processando do mais fraco pro mais
                # forte) fazia o OPOSTO do que place_own_character_
                # bottom_deck (STEP, ja corrigido em 16/07 pra OP05-119) e
                # da dívida tecnica "in any order" exigem -- o mais FORTE
                # dos sacrificados acabava mais fundo no deck, pior
                # resultado possivel.
                escolhidos = sorted(candidates, key=lambda c: c.board_value())[:count]
                escolhidos.sort(key=lambda c: c.board_value(), reverse=True)
                moved = []
                for target in escolhidos:
                    remove_character_from_field(self.me, target, 'deck_bottom')
                    moved.append(target.name[:15])
                self._cost_logs.append(f'custo: fundo do deck: {", ".join(moved)}')
            elif ctype == 'rest_own_character':
                candidates = eligible_cards(
                    self.me.field_chars,
                    cost_gte=cost.get('cost_gte'),
                    cost_lte=cost.get('cost_lte'),
                    filter_text=cost.get('filter_type', ''),
                    name_or_code=cost.get('filter_name', ''),
                    active_only=True,
                    exclude_card=card if cost.get('exclude_self') else None,
                )
                count = cost.get('count', 1)
                if len(candidates) < count:
                    return False
                rested = []
                for _ in range(count):
                    target = min(candidates, key=lambda c: c.board_value())
                    target.rested = True
                    remove_by_identity(candidates, target)
                    rested.append(target.name[:15])
                self._cost_logs.append(f'custo: restou aliado: {", ".join(rested)}')
            elif ctype == 'return_trash_to_deck':
                count = cost.get('count', 1)
                if len(self.me.trash) < count:
                    return False
                chosen = sorted(self.me.trash, key=self._trash_value)[:count]
                for target in chosen:
                    remove_by_identity(self.me.trash, target)
                    self.me.deck.append(target)
                random.shuffle(self.me.deck)
                self._cost_logs.append(f'custo: devolveu {count} do trash ao deck')
            elif ctype == 'don_minus':
                count = cost.get('count', 1)
                if not self._return_don_to_deck(count, exclude_card=card):
                    return False
                self._cost_logs.append(f'custo: devolveu {count} DON ao deck')
            elif ctype == 'return_active_don_to_don_deck':
                # DISTINTO de don_minus: o texto exige DON ATIVO
                # especificamente ("return N of your active DON!! cards"),
                # entao paga so do banco ativo (me.don_available) -- nao
                # reusa _return_don_to_deck, que PREFERE devolver DON
                # restado/gasto (semantica oposta do que este custo exige).
                # Achado 17/07, EB02-061/OP16-060.
                count = cost.get('count', 1)
                if self.me.don_available < count:
                    return False
                self.me.don_available -= count
                self.me.don_deck += count
                self._cost_logs.append(f'custo: devolveu {count} DON ativo ao deck')
            elif ctype == 'place_hand_top_deck':
                # "you may place N cards from your hand at the top of
                # your deck: efeito" -- custo opcional, TOPO (fim da
                # lista), distinto do custo place_from_trash_bottom_deck
                # (fonte=trash, destino=fundo). Achado 17/07, ST17-005.
                count = cost.get('count', 1)
                if len(self.me.hand) < count:
                    return False
                movidos = []
                for _ in range(count):
                    worst = self._choose_to_trash(self.me.hand)
                    if not worst:
                        break
                    remove_by_identity(self.me.hand, worst)
                    self.me.deck.append(worst)
                    movidos.append(worst.name[:14])
                self._cost_logs.append(f'custo: topo do deck (da mão): {", ".join(movidos)}')
            elif ctype == 'place_hand_bottom_deck':
                # "you may place N cards from your hand at the bottom of
                # your deck [in any order] [and rest this Stage]: efeito"
                # -- mesma familia do custo TOPO acima (place_hand_top_
                # deck), mas destino=fundo. Achado 07/08, OP01-011 e
                # OP09-060.
                count = cost.get('count', 1)
                if len(self.me.hand) < count:
                    return False
                movidos = []
                for _ in range(count):
                    worst = self._choose_to_trash(self.me.hand)
                    if not worst:
                        break
                    remove_by_identity(self.me.hand, worst)
                    self.me.deck.insert(0, worst)
                    movidos.append(worst.name[:14])
                self._cost_logs.append(f'custo: fundo do deck (da mão): {", ".join(movidos)}')
            elif ctype == 'give_don_to_named':
                # "you may give N active DON!! cards to 1 of your [Nome]:
                # efeito" -- custo de anexar DON ATIVO (do banco) a um
                # Character PROPRIO NOMEADO especifico (nao "o mais
                # forte", como give_don faz -- aqui o alvo e FIXO pelo
                # nome). Achado 17/07, familia Silvers Rayleigh (EB04-009,
                # OP12-016, OP12-017, OP12-019).
                count = cost.get('count', 1)
                target_name = (cost.get('target_name') or '').lower()
                # o nomeado pode ser Leader OU Character (ex: Silvers
                # Rayleigh joga como Leader em alguns decks -- mesma
                # ambiguidade refletida no "...or [Silvers Rayleigh]" do
                # Counter irmao desta familia).
                candidatos_nome = list(self.me.field_chars) + [self.me.leader]
                alvo = next((c for c in candidatos_nome
                             if target_name in c.name.lower()), None)
                if alvo is None or self.me.don_available < count:
                    return False
                self.me.don_available -= count
                alvo.don_attached += count
                self._cost_logs.append(f'custo: deu {count} DON ativo a {alvo.name[:15]}')
            elif ctype == 'give_don_own':
                # "you may give N of your active DON!! cards to 1 of your
                # Leader or Character cards and [outro custo]:" -- mesmo
                # custo de give_don_to_named, mas SEM filtro de nome (o
                # alvo e qualquer Leader/Character proprio, escolhe o de
                # maior board_value). Achado 19/07, OP13-007.
                count = cost.get('count', 1)
                candidatos_own = list(self.me.field_chars) + [self.me.leader]
                if not candidatos_own or self.me.don_available < count:
                    return False
                alvo_own = max(candidatos_own, key=lambda c: c.board_value())
                self.me.don_available -= count
                alvo_own.don_attached += count
                self._cost_logs.append(f'custo: deu {count} DON ativo a {alvo_own.name[:15]}')
            elif ctype == 'ko_own_character':
                from optcg_engine.rules_facade import eligible_cards

                # Custo de K.O. de um Character PROPRIO (distinto de trash_self:
                # o alvo e OUTRO Character do jogador). K.O. != Trash -- precisa
                # disparar o [On K.O.] do Character escolhido. Ex: OP14-079
                # Crocodile (K.O. um Baroque Works), OP05-087 Hakuba.
                count = cost.get('count', 1)
                candidatos = eligible_cards(
                    self.me.field_chars,
                    filter_text=cost.get('filter_type', ''),
                    exclude_card=card,
                )
                if len(candidatos) < count:
                    return False
                koados = []
                for _ in range(count):
                    if not candidatos:
                        break
                    # escolhe o de menor valor de board (sacrifica o menos util),
                    # reaproveitando a heuristica de _choose_to_trash.
                    alvo = min(candidatos, key=lambda c: c.board_value())
                    remove_by_identity(candidatos, alvo)
                    remove_character_from_field(self.me, alvo, 'trash')
                    koados.append(alvo.name[:15])
                    # dispara [On K.O.] do Character K.O.ado (regra K.O. != Trash)
                    self.execute(alvo, 'on_ko', is_opp_turn=False)
                    self._dispatch_opp_char_ko()
                    self._dispatch_own_char_ko(alvo)
                    self._dispatch_any_char_ko(alvo)
                if koados:
                    self._cost_logs.append(f'custo: K.O. próprio: {", ".join(koados)}')
            elif ctype == 'trash_own_character':
                from optcg_engine.rules_facade import eligible_cards

                # Custo de TRASH (nao K.O.) de um Character PROPRIO do CAMPO
                # -- achado 16/07 (OP06-015/OP13-053/OP16-008/EB04-048/
                # OP07-085): distinto de ko_own_character (dispara [On
                # K.O.], regra K.O. != Trash) e de trash_from_hand (fonte
                # errada, texto nao menciona "from your hand"). power_eq
                # (ex: OP16-008 "10000 base power" sem "or more/or less")
                # compara contra card.power, que no nosso modelo JA E o
                # base power (buffs ficam isolados em power_buff, nunca
                # mutam .power) -- sem necessidade de campo dedicado.
                count = cost.get('count', 1)
                candidatos = eligible_cards(
                    self.me.field_chars,
                    filter_text=cost.get('filter_type', ''),
                    power_lte=cost.get('power_lte'),
                    power_gte=cost.get('power_gte'),
                    power_eq=cost.get('power_eq'),
                    color=cost.get('color', ''),
                    exclude_card=card,
                )
                if len(candidatos) < count:
                    return False
                trashed_own = []
                for _ in range(count):
                    if not candidatos:
                        break
                    alvo = min(candidatos, key=lambda c: c.board_value())
                    remove_by_identity(candidatos, alvo)
                    remove_character_from_field(self.me, alvo, 'trash')
                    trashed_own.append(alvo.name[:15])
                if trashed_own:
                    self._cost_logs.append(f'custo: trashou do campo: {", ".join(trashed_own)}')
            elif ctype == 'place_from_trash_bottom_deck':
                from optcg_engine.rules_facade import eligible_cards

                # Custo de colocar N cartas do PRÓPRIO trash no fundo do
                # PRÓPRIO deck. Achado em auditoria de buff_cost 27/06: 51
                # cartas usam esse custo, zero cobertura antes (Kaku
                # OP07-080, Trafalgar Law, Dragon...). "In any order" NÃO é
                # estética/irrelevante pra ORDEM de insercao (dívida técnica
                # registrada em TODO.md, 16/07 -- corrigida 19/07): entre as
                # `count` cartas ESCOLHIDAS, insere da mais forte pra mais
                # fraca -- a mais forte fica mais perto do topo do deck
                # (comprada primeiro se o deck chegar lá), mesma convenção
                # já usada em place_own_character_bottom_deck (STEP, achado
                # 16/07, OP05-119). A SELECAO em si (quais `count` cartas
                # saem do trash) fica INALTERADA -- ainda os ultimos `count`
                # elegiveis na ordem do trash (mesmo criterio de sempre,
                # candidatos[-count:] em vez de pop() repetido, resultado
                # identico) -- mudar a selecao quebraria blocos que tambem
                # recuperam uma carta ESPECIFICA do trash no mesmo efeito
                # (ex: OP05-088 Mansherry: custo move 2 do trash pro fundo E
                # o efeito seguinte recupera outra carta do MESMO trash --
                # priorizar por board_value na selecao levaria embora
                # justamente a carta que o proximo step precisa).
                count = cost.get('count', 1)
                candidatos = eligible_cards(
                    self.me.trash,
                    filter_text=cost.get('filter_type', ''),
                )
                if len(candidatos) < count:
                    return False
                escolhidos = candidatos[-count:] if count else []
                escolhidos.sort(key=lambda c: c.board_value(), reverse=True)
                movidos = []
                for alvo in escolhidos:
                    remove_by_identity(self.me.trash, alvo)
                    self.me.deck.insert(0, alvo)   # fundo do deck = inicio da lista
                    movidos.append(alvo.name[:14])
                self._cost_logs.append(f'custo: fundo do deck (do trash): {", ".join(movidos)}')
            elif ctype in ('turn_life_face_up', 'turn_life_face_down'):
                # count>1 (achado 19/07, OP08-058: "turn 2 cards from the
                # top of your Life cards face-up") -- vira as N cartas do
                # TOPO (fim da lista), nao so 1 fixo.
                count = cost.get('count', 1)
                if len(self.me.life) < count:
                    return False
                desired_face_up = (ctype == 'turn_life_face_up')
                if cost.get('position') == 'top_or_bottom':
                    # "from the top OR BOTTOM" (achado 30/07, ST36-005 Kid,
                    # unica carta no banco com a escolha de posicao) --
                    # prefere uma carta que JA esta no estado desejado (o
                    # verdadeiro custo de virar e zero: nada muda de
                    # verdade), so mexe numa carta que muda de estado se
                    # NENHUMA ja estiver no estado certo.
                    ja_no_estado = [c for c in self.me.life if c.life_face_up == desired_face_up]
                    alvos = (ja_no_estado[:count] if len(ja_no_estado) >= count
                             else self.me.life[-count:])
                else:
                    alvos = self.me.life[-count:]
                for alvo in alvos:
                    alvo.life_face_up = desired_face_up
                face = 'face-up' if desired_face_up else 'face-down'
                self._cost_logs.append(f'custo: virou {count} carta(s) da vida {face}')
        return True

    def _return_don_to_deck(self, count: int, estado: 'GameState' = None,
                            exclude_card: 'Card | None' = None) -> bool:
        """
        Paga um custo DON!! −X: devolve X DON do campo para o deck de DON.
        Preferência (regra do usuário): devolve primeiro o DON "sem trabalho" —
        anexado a quem JÁ atacou (restado) ou ao líder que já atacou, depois DON
        restado no banco. Evita DON ativo e DON anexado a quem ainda vai agir.
        Retorna False se não há DON suficiente devolvível.

        `estado`: por padrão self.me (uso normal, custo do PRÓPRIO jogador).
        Aceita self.opp também -- usado por opp_don_minus (achado 27/06,
        "Your opponent returns N DON!! cards from their field to their
        DON!! deck", FORÇADO no oponente, não custo próprio).

        `exclude_card`: o PRÓPRIO atacante, quando este custo é o
        `don_minus` do `[When Attacking]` dele mesmo (achado ao vivo 23/07,
        Baron Tamago & Pekoms ST34-005): declarar o ataque já resta o
        atacante ANTES do custo resolver, então "Fonte 1" (DON anexado a
        quem já atacou/restou) enxergava o PRÓPRIO atacante como fonte
        "sem trabalho" e devolvia o DON que tinha acabado de ser anexado
        para reforçar ESTE MESMO ataque -- o ataque voltava ao poder base,
        anulando o fix de attach_don-pra-poder-de-combate (bloco 330).
        Excluído só das fontes 1/2 (as "baratas"); permanece disponível na
        Fonte 4 (último recurso) se não houver outra origem -- melhor pagar
        o custo do que travar a habilidade por falta de DON.
        """
        me = estado if estado is not None else self.me
        devolvidos = 0

        # Fonte 1: DON anexado a personagens que JÁ atacaram (restados),
        # exceto o próprio atacante pagando o custo AGORA (ver docstring).
        for c in me.field_chars:
            if c is exclude_card:
                continue
            while c.don_attached > 0 and c.rested and devolvidos < count:
                c.don_attached -= 1
                me.don_deck += 1
                devolvidos += 1

        # Fonte 2: DON anexado ao líder se já atacou (restado), mesma
        # exceção quando o próprio líder é quem está pagando o custo.
        if me.leader is not exclude_card:
            while me.leader.don_attached > 0 and me.leader.rested and devolvidos < count:
                me.leader.don_attached -= 1
                me.don_deck += 1
                devolvidos += 1

        # Fonte 3: DON restado no banco (gasto, parado)
        while me.don_rested > 0 and devolvidos < count:
            me.don_rested -= 1
            me.don_deck += 1
            devolvidos += 1

        # Fonte 4 (último caso): DON anexado a quem ainda NÃO atacou / DON ativo
        # — só se for inevitável. Preferimos NÃO chegar aqui (o planner deve
        # ordenar para atacar antes). Mas se o custo é obrigatório, paga.
        if devolvidos < count:
            for c in me.field_chars:
                while c.don_attached > 0 and devolvidos < count:
                    c.don_attached -= 1
                    me.don_deck += 1
                    devolvidos += 1
            while me.leader.don_attached > 0 and devolvidos < count:
                me.leader.don_attached -= 1
                me.don_deck += 1
                devolvidos += 1
            while me.don_available > 0 and devolvidos < count:
                me.don_available -= 1
                me.don_deck += 1
                devolvidos += 1

        if devolvidos:
            self._dispatch_don_returned(me, devolvidos, source_owner=self.me)
        return devolvidos >= count

    def _dispatch_don_returned(self, owner: 'GameState', amount: int,
                               source_owner: 'GameState') -> None:
        """Dispara a familia parametrizada ``when_don_returned``.

        ``amount`` e a quantidade devolvida na MESMA resolucao. Portanto duas
        devolucoes separadas de 1 nao satisfazem um limiar 2. ``source_owner``
        permite respeitar o fraseado restrito "by your effect".
        """
        other = self.opp if owner is self.me else self.me
        cards = [owner.leader, *owner.field_chars]
        if owner.field_stage:
            cards.append(owner.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get('when_don_returned')
            if not entry or amount < entry.get('return_count_gte', 1):
                continue
            timing = entry.get('owner_turn')
            if timing == 'your' and not owner.is_active_turn:
                continue
            if timing == 'opponent' and owner.is_active_turn:
                continue
            if entry.get('by_own_effect') and source_owner is not owner:
                continue
            marker = (owner.global_turn, 'when_don_returned')
            if entry.get('once_per_turn') and getattr(source, '_event_once_marker', None) == marker:
                continue
            logs = EffectExecutor(owner, other).execute(source, 'when_don_returned')
            if logs and entry.get('once_per_turn'):
                source._event_once_marker = marker

    def _dispatch_damage_or_own_char_ko(self, owner: 'GameState',
                                        ko_card: 'Card | None' = None) -> None:
        """Dispara evento de dano recebido OU K.O. de Character proprio.

        ``ko_card=None`` representa dano. Com carta, valida o base power
        minimo antes de resolver. O requisito DON anexado e o once-per-turn
        continuam centralizados em ``execute``.
        """
        other = self.opp if owner is self.me else self.me
        cards = [owner.leader, *owner.field_chars]
        for source in list(cards):
            entry = get_card_effects(source.code).get(
                'when_damage_or_own_char_ko')
            if not entry:
                continue
            if (ko_card is not None
                    and ko_card.power < entry.get('own_char_base_power_gte', 0)):
                continue
            marker = (owner.global_turn, 'when_damage_or_own_char_ko')
            if (entry.get('once_per_turn')
                    and getattr(source, '_damage_ko_once_marker', None) == marker):
                continue
            logs = EffectExecutor(owner, other).execute(
                source, 'when_damage_or_own_char_ko')
            if logs and entry.get('once_per_turn'):
                source._damage_ko_once_marker = marker

    def _dispatch_opp_char_ko(self) -> None:
        """
        Dispara o gatilho generico ``on_opp_char_ko`` -- FASE 1.2 do
        mapeamento de combos pedido pelo usuario 24/07 ("quando o
        personagem do OPONENTE e K.O.'d"). Achado real: Kaido OP01-061
        (lider!) e Rob Lucci OP03-076 tinham esse gatilho no texto oficial,
        mas o parser derrubava a condicao inteira e o efeito virava
        incondicional todo turno seu -- bug de regra, nao so de pontuacao.

        Convencao: chamar SEMPRE logo apos `X.execute(victim, 'on_ko', ...)`
        resolver, na MESMA instancia `X` de EffectExecutor usada nesse
        execute -- em todo ponto de KO do motor (efeito, combate, blocker
        reativo, mutuo), `X.me` e o DONO do personagem morto e `X.opp` e o
        lado OPOSTO (quem observa "o personagem do oponente morreu", do
        ponto de vista dele). Nao precisa de parametro nenhum por isso.
        Mesmo padrao de `_dispatch_don_returned`/`_dispatch_damage_or_own_char_ko`
        (auditoria global: sao os 8 pontos que chamam `.execute(_, 'on_ko')`
        no motor inteiro).
        """
        watcher, victim_owner = self.opp, self.me
        cards = [watcher.leader, *watcher.field_chars]
        if watcher.field_stage:
            cards.append(watcher.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get('on_opp_char_ko')
            if not entry:
                continue
            marker = (watcher.global_turn, 'on_opp_char_ko')
            if (entry.get('once_per_turn')
                    and getattr(source, '_opp_char_ko_once_marker', None) == marker):
                continue
            logs = EffectExecutor(watcher, victim_owner).execute(source, 'on_opp_char_ko')
            if logs and entry.get('once_per_turn'):
                source._opp_char_ko_once_marker = marker

    def _dispatch_own_char_ko(self, victim: 'Card | None' = None) -> None:
        """
        Dispara ``on_own_char_ko`` -- espelho de `_dispatch_opp_char_ko`,
        mas o WATCHER e o DONO do personagem morto (nao o lado oposto).
        Achado 29/07 (pente-fino nos lideres, Buggy OP16-041: "This effect
        can be activated when your {Impel Down} type Character card is
        removed from the field"). Chamado nos MESMOS 8 pontos reais de
        K.O. do motor que ja chamam `_dispatch_opp_char_ko()` (mesma
        convencao, mesmo self.me/self.opp da chamada de on_ko).

        `victim` (opcional): a carta K.O.'ada, usada pra checar
        `victim_type_filter` (ex: Buggy exige que a VITIMA seja do tipo
        "Impel Down" -- diferente de `on_opp_char_ko`, cujas 2 cartas
        confirmadas ate agora nao tinham filtro de tipo na vitima) e
        `victim_power_gte` (achado 30/07, Boa Hancock OP14-041: "with
        5000 base power or more" -- `victim.power` ja e o BASE power,
        buffs vivem isolados em `power_buff`/`effective_power()`).
        Chamadores que nao tem a carta a mao (nenhum hoje) passam None --
        nesse caso, cartas com qualquer filtro de vitima simplesmente
        nunca disparam (conservador, nao dispara sem confirmar o filtro).

        ESCOPO CONHECIDO (documentado, nao e bug): o texto real diz
        "removed from the field" (generico), mas este dispatcher so cobre
        K.O. (a causa mais comum na pratica) -- remocao por bounce/deck-
        bottom via outros efeitos (`remove_character_from_field(...,
        'hand'|'deck_bottom')`) NAO dispara este evento ainda. Estender
        pra cobrir esses pontos tambem exigiria acesso ao lado oposto
        dentro de `remove_character_from_field` (funcao pura, sem
        `opp`), um refactor maior que tocaria ~19 pontos de chamada --
        avaliado como fora de escopo desta rodada (ver parser_audits/).
        """
        watcher = self.me
        cards = [watcher.leader, *watcher.field_chars]
        if watcher.field_stage:
            cards.append(watcher.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get('on_own_char_ko')
            if not entry:
                continue
            victim_filter = entry.get('victim_type_filter')
            victim_power_gte = entry.get('victim_power_gte')
            if victim_filter or victim_power_gte:
                if victim is None:
                    continue
                if victim_filter:
                    from optcg_engine.rules_facade import card_matches_filter
                    if not card_matches_filter(victim, victim_filter):
                        continue
                if victim_power_gte and victim.power < victim_power_gte:
                    continue
            marker = (watcher.global_turn, 'on_own_char_ko')
            if (entry.get('once_per_turn')
                    and getattr(source, '_own_char_ko_once_marker', None) == marker):
                continue
            logs = EffectExecutor(self.me, self.opp).execute(source, 'on_own_char_ko')
            if logs and entry.get('once_per_turn'):
                source._own_char_ko_once_marker = marker

    def _dispatch_any_char_ko(self, victim: 'Card | None' = None) -> None:
        """
        Dispara ``on_any_char_ko`` -- terceira variante da familia (junto
        de on_opp_char_ko/on_own_char_ko), pra gatilhos QUE NAO
        ESPECIFICAM o lado ("When a Character is K.O.'d", sem "your" nem
        "your opponent's"). Achado 29/07 (pente-fino nos lideres, Luffy
        ST08-001, unica carta no banco: "[Your Turn] When a Character is
        K.O.'d, give up to 1 rested DON!! card to this Leader."). Notifica
        os DOIS lados (qualquer K.O., de qualquer personagem).

        ESCOPO CONHECIDO: a tag "[Your Turn]" do texto original sugere que
        o gatilho so deveria contar durante o PROPRIO turno do watcher,
        mas este dispatcher nao filtra por isso ainda (dispara pros dois
        lados sempre que QUALQUER K.O. acontece, independente de turno) --
        mesmo criterio de escopo parcial ja aceito pra Buggy (estritamente
        melhor que o bug antigo, sem reivindicar cobertura 100% fiel ao
        texto).
        """
        for watcher, other in ((self.me, self.opp), (self.opp, self.me)):
            cards = [watcher.leader, *watcher.field_chars]
            if watcher.field_stage:
                cards.append(watcher.field_stage)
            for source in list(cards):
                entry = get_card_effects(source.code).get('on_any_char_ko')
                if not entry:
                    continue
                victim_filter = entry.get('victim_type_filter')
                if victim_filter:
                    if victim is None:
                        continue
                    from optcg_engine.rules_facade import card_matches_filter
                    if not card_matches_filter(victim, victim_filter):
                        continue
                marker = (watcher.global_turn, 'on_any_char_ko')
                if (entry.get('once_per_turn')
                        and getattr(source, '_any_char_ko_once_marker', None) == marker):
                    continue
                logs = EffectExecutor(watcher, other).execute(source, 'on_any_char_ko')
                if logs and entry.get('once_per_turn'):
                    source._any_char_ko_once_marker = marker

    def _dispatch_event_activated(self) -> None:
        """
        Dispara ``on_own_event_activated`` (campo de self.me) e
        ``on_opp_event_activated`` (campo de self.opp) -- FASE 1.1 do
        mapeamento de combos (usuario, 24/07). Chamar sempre que self.me
        acaba de jogar/ativar um Evento (mesma convencao dos outros
        dispatchers parametrizados: quem chama ja garante o `self.me`/
        `self.opp` certos pro momento do jogo).

        Achado real: 8 cartas com esse gatilho no texto oficial (Usopp,
        Franky, Gion, Camie, Luffy OP15-119, Crocodile OP01-062, Page One,
        Zeff), todas caindo em `your_turn`/`opp_turn` incondicional antes
        deste fix. Escopo: cobre so ativacao de EVENTO (a forma mais
        comum) -- Camie/Luffy/Zeff tem "ou [Trigger]"/"ou [Blocker]" como
        gatilho alternativo tambem, NAO coberto ainda (registrado em
        parser_audits/ como pendente); mesmo parcial, ja e estritamente
        melhor que o bug antigo (nunca disparava certo, disparava sempre).
        """
        self._dispatch_event_activated_side(
            'on_own_event_activated', self.me, self.opp, '_own_event_once_marker')
        self._dispatch_event_activated_side(
            'on_opp_event_activated', self.opp, self.me, '_opp_event_once_marker')

    def _dispatch_event_activated_side(self, trig_name: str, watcher: 'GameState',
                                       other: 'GameState', marker_attr: str) -> None:
        cards = [watcher.leader, *watcher.field_chars]
        if watcher.field_stage:
            cards.append(watcher.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get(trig_name)
            if not entry:
                continue
            marker = (watcher.global_turn, trig_name)
            if (entry.get('once_per_turn')
                    and getattr(source, marker_attr, None) == marker):
                continue
            logs = EffectExecutor(watcher, other).execute(source, trig_name)
            if logs and entry.get('once_per_turn'):
                setattr(source, marker_attr, marker)

    def _dispatch_char_played(self, played_card: 'Card', via_effect: bool = False) -> None:
        """
        Dispara ``on_own_char_played`` (campo de self.me) e
        ``on_opp_char_played`` (campo de self.opp) quando self.me acaba de
        jogar `played_card` (CHARACTER) -- FASE 1.3 do mapeamento de
        combos (usuario, 24/07). 4 cartas confirmadas: Sugar OP04-024
        (observa o OPONENTE), Sanji OP02-026, Bonney OP13-100, Boa Hancock
        OP14-041 (observam o PROPRIO lado).

        Filtros no texto da carta observadora (`play_filter_*`) sao
        checados contra `played_card` antes de disparar -- sem isso a
        habilidade dispararia pra QUALQUER personagem jogado, nao so os
        que batem o filtro real (Sanji so reage a personagem SEM efeito
        base; Bonney so a personagem COM [Trigger]).

        `via_effect`: True quando `played_card` entrou em campo pela
        resolucao de OUTRA carta (`_put_into_play`, chamado de dentro de
        `_execute_step` pro action `play_card`), False quando foi uma
        jogada normal da Main Phase/Counter (`_play_card`, decisao direta
        do turno). Achado 30/07 (Koala OP12-081): "This effect can be
        activated when your opponent plays a Character with a base cost
        of 8 or more, OR when your opponent plays a Character using a
        Character's effect" -- OU de 2 condicoes distintas, a 2a
        checando COMO a carta foi jogada, nao um atributo da carta em si.
        """
        if played_card.card_type != 'CHARACTER':
            return
        self._dispatch_char_played_side(
            'on_own_char_played', self.me, self.opp,
            '_own_char_played_once_marker', played_card, via_effect)
        self._dispatch_char_played_side(
            'on_opp_char_played', self.opp, self.me,
            '_opp_char_played_once_marker', played_card, via_effect)

    @staticmethod
    def _char_played_filter_matches(filt: dict, played_card: 'Card',
                                     via_effect: bool) -> bool:
        if filt.get('play_filter_no_base_effect') and get_card_effects(played_card.code):
            return False
        if filt.get('play_filter_has_trigger') and not played_card.has_trigger:
            return False
        cost_gte = filt.get('play_filter_cost_gte')
        if cost_gte and played_card.cost < cost_gte:
            return False
        if filt.get('play_filter_via_effect') and not via_effect:
            return False
        return True

    def _dispatch_char_played_side(self, trig_name: str, watcher: 'GameState',
                                   other: 'GameState', marker_attr: str,
                                   played_card: 'Card', via_effect: bool = False) -> None:
        cards = [watcher.leader, *watcher.field_chars]
        if watcher.field_stage:
            cards.append(watcher.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get(trig_name)
            if not entry:
                continue
            # play_filter_or: lista de filtros ALTERNATIVOS (Koala) -- basta
            # UM bater. Sem isso, a carta inteira usa a si mesma como o
            # unico filtro (comportamento AND de sempre, ja que so ha 1
            # alternativa possivel).
            alternativas = entry.get('play_filter_or') or [entry]
            if not any(self._char_played_filter_matches(alt, played_card, via_effect)
                       for alt in alternativas):
                continue
            marker = (watcher.global_turn, trig_name)
            if (entry.get('once_per_turn')
                    and getattr(source, marker_attr, None) == marker):
                continue
            logs = EffectExecutor(watcher, other).execute(source, trig_name)
            if logs and entry.get('once_per_turn'):
                setattr(source, marker_attr, marker)

    def _dispatch_own_effect_removes_char(self, removal_type: str, target_side: str) -> None:
        """
        Dispara ``on_own_effect_removes_char`` no campo de self.me quando o
        PROPRIO efeito de self.me acabou de remover um Character do campo
        (K.O., bounce ou fundo do deck) -- FASE 1.4 do mapeamento de combos
        (usuario, 24/07). 3 cartas confirmadas: Crocodile EB02-023 (so
        bounce de personagem do OPONENTE -- filtros removal_type='bounce'
        e target_side='opp' no banco), Boa Hancock OP07-038 e Shakuyaku
        OP08-046 (qualquer remocao, qualquer lado -- sem filtro no banco).

        Convencao: chamar SEMPRE logo apos `remove_character_from_field`
        nos 4 pontos de `_execute_step` onde uma HABILIDADE de carta
        remove um Character (ko/trash_character, ko_selected, bounce,
        place_opp_character_bottom_deck) -- nao em remocao por BATALHA
        (mesmo escopo do texto oficial, "removed... by your effect").
        `self.me` e sempre quem CONTROLA o efeito que esta removendo
        (dono da habilidade em execucao), nao o dono do alvo removido.
        """
        watcher = self.me
        cards = [watcher.leader, *watcher.field_chars]
        if watcher.field_stage:
            cards.append(watcher.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get('on_own_effect_removes_char')
            if not entry:
                continue
            if entry.get('removal_type') and entry['removal_type'] != removal_type:
                continue
            if entry.get('target_side') and entry['target_side'] != target_side:
                continue
            marker = (watcher.global_turn, 'on_own_effect_removes_char')
            if (entry.get('once_per_turn')
                    and getattr(source, '_own_effect_removes_char_once_marker', None) == marker):
                continue
            logs = EffectExecutor(watcher, self.opp).execute(source, 'on_own_effect_removes_char')
            if logs and entry.get('once_per_turn'):
                source._own_effect_removes_char_once_marker = marker

    def _dispatch_hand_card_trashed(self, owner: 'GameState', other: 'GameState') -> None:
        """
        Dispara ``on_hand_card_trashed`` no campo de `owner` quando uma
        carta acabou de ser trashada da MAO de `owner` por um efeito
        (proprio ou do oponente) -- FASE 1.4 do mapeamento de combos
        (usuario, 24/07). 3 cartas confirmadas, todas reagindo na PROPRIA
        mao: Kuroobi OP14-045/Jinbe OP14-049 (ganham [Rush] neste turno),
        Wadatsumi OP14-056 (o proprio efeito e negado neste turno).

        Convencao: chamar logo apos qualquer remocao de carta(s) da MAO de
        `owner` por efeito (custo `trash_from_hand`, acoes
        `trash_from_hand`/`opp_trash_from_hand`/`opp_choose_trash_our_hand`)
        -- nunca por jogar a carta (isso e `_dispatch_char_played`, mao ->
        campo, nao mao -> trash).
        """
        cards = [owner.leader, *owner.field_chars]
        if owner.field_stage:
            cards.append(owner.field_stage)
        for source in list(cards):
            entry = get_card_effects(source.code).get('on_hand_card_trashed')
            if not entry:
                continue
            marker = (owner.global_turn, 'on_hand_card_trashed')
            if (entry.get('once_per_turn')
                    and getattr(source, '_hand_card_trashed_once_marker', None) == marker):
                continue
            logs = EffectExecutor(owner, other).execute(source, 'on_hand_card_trashed')
            if logs and entry.get('once_per_turn'):
                source._hand_card_trashed_once_marker = marker

    # ── Execução de steps individuais ────────────────────────────────────────

    def _resolve_cost_lte(self, step: dict, default=99):
        """
        Resolve o valor de cost_lte de um step, tratando os dois casos:
        (1) valor FIXO (int), como ja era -- maioria dos casos.
        (2) valor DINAMICO ("equal to or less than the number of DON!! cards
            on your/your opponent's field"), confirmado em 5 cartas:
            OP13-099 (Empty Throne), OP08-098 (Kalgara), OP11-022
            (Shirahoshi) -- as 3 usam DON!! do PROPRIO campo
            ('don_count_self') -- e P-090 (Charlotte Smoothie) e OP08-062
            (Charlotte Katakuri, ability trash-self), que usam DON!! do
            campo do OPONENTE ('don_count_opp') -- texto da carta diz
            explicitamente "on your opponent's field", lado invertido das
            outras 3. Sem esta distincao, um simbolo generico unico erraria
            a Smoothie/Katakuri. OP08-062 tambem combina o sentinela com um
            cost_gte=3 fixo no MESMO step (dois filtros de custo
            simultaneos: "cost of 3 or more that is equal to or less than
            the number of DON!! cards...") -- resolvido perto do end() do
            match de step, nao aqui (gerar_effects_db.py, parse_play_generic).
        Antes desta funcao, o parser ja emitia cost_lte=99 (fixo, "sem
        limite") para as 5 cartas -- nao quebrava o engine, mas tornava o
        limite real do efeito (baseado em DON!! em campo) inexistente na
        pratica: qualquer carta de custo ate 99 passava, quando a regra real
        e mais restritiva na maioria das posicoes de jogo (DON!! em campo
        raramente chega a 99).
        Duas outras cartas com o MESMO texto-gatilho de DON!! no banco NAO
        usam o sentinela dinamico de verdade: OP07-070 (Big Bun) tem a
        frase "number of DON!! cards on your field" numa condicao SEPARADA
        (gate "don_on_field_lte_opp") que precede, na mesma sentenca, uma
        clausula de custo FIXA e literal ("with a cost of 4 or less") para a
        carta jogada -- ate 17/07 um bug de janela greedy no parser deixava
        essa frase da condicao vazar pro cost_lte do play_card e sequestrar
        o sentinela por engano, quando devia ser cost_lte=4 fixo. EB02-039
        (GERMA 66) tem o mesmo texto de condicao mas o alvo jogado e
        filtrado por NOME/faixa de power (play_from_trash), sem clausula de
        custo nenhuma -- nunca gerava cost_lte dinamico nem fixo.
        """
        cost_lte = step.get('cost_lte', default)
        if cost_lte == 'don_count_self':
            return self.me.don_available + self.me.don_rested
        if cost_lte == 'don_count_opp':
            return self.opp.don_available + self.opp.don_rested
        return cost_lte

    def _execute_step(self, step: dict, card: Card) -> str:
        from optcg_engine.rules_facade import eligible_cards

        action = step.get('action', '')
        me = self.me
        opp = self.opp

        # Condicao PROPRIA do step (distinta da condicao global do entry,
        # ja checada em _execute_trigger antes de chamar qualquer step).
        # Existe para separar "[A incondicional]. Then, if [cond], [B]" --
        # a condicao do "Then, if" deve bloquear SO o step B, nao o A que
        # vem antes dela no texto. Sem isto, qualquer condicao so podia
        # valer pro bloco inteiro (todos os steps), causando scope leakage
        # (confirmado em ST14-001/ST14-008 e ~44 outras cartas, 23/06).
        step_conds = step.get('conditions')
        if step_conds and not self._check_conditions(step_conds, card):
            return ''

        # "Your opponent may trash N cards from the top of their Life
        # cards. If they do not, [efeito]" -- gate GENERICO (funciona pra
        # qualquer action que venha depois dessa clausula, achado 19/07,
        # OP05-099): mesma simplificacao ja documentada em
        # lock_opp_attack_unless_pays ("paga sempre que pode, sem
        # modelar 'vale a pena'") -- se o oponente TEM Life suficiente,
        # ele sempre trasha pra PREVENIR o efeito seguinte; sem Life
        # suficiente, o efeito procede normalmente.
        unless_pays = step.get('unless_opp_pays')
        if unless_pays and unless_pays.get('type') == 'life_trash':
            count_life = unless_pays.get('count', 1)
            if len(opp.life) >= count_life:
                for _ in range(count_life):
                    life_card = opp.life.pop()
                    life_card.life_face_up = False
                    opp.trash.append(life_card)
                return f'oponente trashou {count_life} carta(s) da Life pra evitar o efeito'
        # Variante do custo de prevencao: devolver DON ATIVO (achado
        # 19/07, OP15-059) em vez de trashar Life -- mesmo gate generico,
        # custo diferente. Usa don_available especificamente (a carta
        # exige DON ATIVO, nao qualquer DON do banco).
        if unless_pays and unless_pays.get('type') == 'don_return':
            count_don = unless_pays.get('count', 1)
            if opp.don_available >= count_don:
                opp.don_available -= count_don
                opp.don_deck += count_don
                return f'oponente devolveu {count_don} DON ativo pra evitar o efeito'

        # "you may rest N of your Characters with a cost of M or
        # (more|less). If you do, [efeito]" -- custo OPCIONAL do proprio
        # jogador gating SO este step (achado 19/07, OP07-036). Mesma
        # simplificacao de lock_opp_attack_unless_pays: paga sempre que
        # pode (restando o candidato de MENOR board_value que atende o
        # filtro); sem candidato elegivel, o step inteiro e cancelado.
        own_cost = step.get('requires_own_cost')
        if own_cost and own_cost.get('type') == 'rest_own_character':
            cost_gte = own_cost.get('cost_gte')
            cost_lte = own_cost.get('cost_lte')
            candidates = [c for c in me.field_chars if not c.rested
                          and (cost_gte is None or c.cost >= cost_gte)
                          and (cost_lte is None or c.cost <= cost_lte)]
            if not candidates:
                return ''
            min(candidates, key=lambda c: c.board_value()).rested = True

        if step.get('timing') == 'end_of_turn' and not step.get('_from_queue'):
            queued = dict(step)
            queued['_from_queue'] = True
            me.end_of_turn_queue.append({'step': queued, 'card': card})
            return f'agendou {action} para o fim do turno'

        # ── Busca (StartTopDeck + AddToHand + FinalizeTopDeck) ────────────────
        if action == 'look_top_deck':
            # Apenas marca quantas cartas serão vistas — próximo step faz a seleção
            return ''

        if action == 'add_to_hand':
            from optcg_engine.rules_facade import eligible_cards

            if not me.deck:
                return ''
            # Número de cartas a olhar (do step anterior look_top_deck)
            # Busca o look_top_deck no mesmo bloco de efeitos
            effects = get_card_effects(card.code)
            look_count = 5  # padrão
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                        break

            look = min(look_count, len(me.deck))
            candidates = me.deck[-look:]
            # Memoria: o buscador VE todas as `look` cartas do topo. As que
            # sairem do deck (pra mao/trash) somem via limpeza lazy em
            # known_deck_cards; as que ficarem seguem conhecidas.
            for _seen in candidates:
                me.revealed_deck.add(id(_seen))

            exclude = step.get('exclude', [])
            cost_lte = self._resolve_cost_lte(step, default=99)
            filter_type_val = step.get('filter_type', '')
            filter_names = [n.lower() for n in step.get('filter_names', [])]
            base_kwargs = dict(cost_lte=cost_lte, cost_gte=step.get('cost_gte'),
                                power_lte=step.get('power_lte', 999999),
                                power_eq=step.get('power_eq'))
            if filter_type_val and filter_names:
                # "[Nome] or {Tipo} type cards" -- alternativas (OR), nao
                # filtro combinado (achado 19/07, OP15-101 Kalgara, unica
                # carta no banco com essa forma exata). Sem isso, um card
                # so batendo o TIPO mas nao o NOME (ou vice-versa) era
                # descartado por engano.
                pool_type = eligible_cards(candidates, filter_text=filter_type_val,
                                           include_text=True, **base_kwargs)
                pool_name = [c for c in eligible_cards(candidates, **base_kwargs)
                             if any(n in c.name.lower() for n in filter_names)]
                filtered = list(pool_type)
                for c in pool_name:
                    if not contains_identity(filtered, c):
                        filtered.append(c)
            else:
                filtered = eligible_cards(
                    candidates, filter_text=filter_type_val, include_text=True, **base_kwargs)
                if filter_names:
                    filtered = [c for c in filtered
                                if any(n in c.name.lower() for n in filter_names)]
            if exclude:
                filtered = [
                    c for c in filtered
                    if not any(ex.lower() in c.name.lower() for ex in exclude)
                ]

            count = step.get('count', 1)
            taken = []
            # _trash_value = avaliar_carta (situacional, achado 07/07: search
            # do Laffitte/Shiryu trazia sempre o corpo mais "parrudo",
            # ignorando cartas mais uteis pra situacao — preservado, e a
            # base da conta) + as protecoes de MANTER NA MAO: win-con do
            # GamePlan (+150 enquanto o DON nao bate o alvo), carta cara
            # (custo>=7), evento counter. "Qual carta eu mais quero na mao"
            # e exatamente a pergunta do search — achado real 12/07 (spy de
            # trash, 13x/20 partidas): searchers do Imu viam a Five Elders
            # no top 5, avaliar_carta puro (~45, sem protecao) perdia pra
            # qualquer corpo jogavel e a win-con ia pro trash com o resto
            # (mill do trash_rest) — e OP13-082 nao e reanimavel (o
            # play_from_trash dela filtra power 5000; a copia milada morre).
            for _ in range(min(count, len(filtered))):
                best = max(filtered, key=self._trash_value) if filtered else None
                if best:
                    taken.append(best)
                    remove_by_identity(filtered, best)

            for c in taken:
                # pop_by_identity (nao remove_by_identity) -- ver docstring
                # dela: respeita o deepcopy-on-pop de _SimDeck durante
                # simulacao do Turn Planner, evita vazar DON!! fantasma
                # pro objeto real do deck (achado 03/08).
                c = pop_by_identity(me.deck, c)
                me.hand.append(c)
                if step.get('revealed_to_opponent') is True:
                    me.revealed_to_opponent.add(id(c))

            # Resto permanece no deck (será tratado pelo próximo step)
            me.searchers_used += 1
            names = ', '.join(c.name[:15] for c in taken)
            if names:
                return f'olhou {look} do topo -> pegou: {names}'
            else:
                return f'olhou {look} do topo -> nada para pegar'

        # "look at N cards ... and trash up to M cards. Then, place the
        # rest at the bottom" -- MILL dentro do grupo olhado (OP03-083),
        # distinto de add_to_hand (nao adiciona nada a mao). Mesma
        # convencao de escopo (me.deck[-look:]) e de deixar "o resto" pro
        # deck_bottom_rest tratar depois.
        if action == 'trash_from_looked_deck':
            if not me.deck:
                return ''
            effects = get_card_effects(card.code)
            look_count = 5
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                        break
            look = min(look_count, len(me.deck))
            candidates = me.deck[-look:]
            # Memoria: o buscador VE todas as `look` cartas do topo. As que
            # sairem do deck (pra mao/trash) somem via limpeza lazy em
            # known_deck_cards; as que ficarem seguem conhecidas.
            for _seen in candidates:
                me.revealed_deck.add(id(_seen))
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(candidates))):
                worst = min(candidates, key=lambda c: c.board_value())
                remove_by_identity(candidates, worst)
                # pop_by_identity, nao remove_by_identity -- ver docstring
                # (respeita deepcopy-on-pop de _SimDeck, achado 03/08).
                worst = pop_by_identity(me.deck, worst)
                me.trash.append(worst)
                trashed.append(worst.name[:15])
            names = ', '.join(trashed)
            if names:
                return f'olhou {look} do topo -> trashou: {names}'
            else:
                return f'olhou {look} do topo -> nada para trashar'

        if action == 'search_deck':
            candidates = eligible_cards(
                me.deck,
                filter_text=step.get('filter_type', ''),
                name_or_code=step.get('filter_name', ''),
                cost_lte=step.get('cost_lte'),
                cost_gte=step.get('cost_gte'),
            )
            count = step.get('count', 1)
            taken = []
            for _ in range(min(count, len(candidates))):
                best = max(candidates, key=self._trash_value)
                remove_by_identity(candidates, best)
                # pop_by_identity, nao remove_by_identity -- ver docstring
                # (respeita deepcopy-on-pop de _SimDeck, achado 03/08).
                best = pop_by_identity(me.deck, best)
                me.hand.append(best)
                if step.get('revealed_to_opponent'):
                    me.revealed_to_opponent.add(id(best))
                taken.append(best.name[:15])
            random.shuffle(me.deck)
            return f'buscou no deck: {", ".join(taken)}' if taken else 'busca sem alvo'

        if action == 'reveal_opp_hand':
            count = min(step.get('count', 1), len(opp.hand))
            revealed = sorted(opp.hand, key=self._trash_value, reverse=True)[:count]
            for target in revealed:
                opp.revealed_to_opponent.add(id(target))
            if (step.get('if_event_opp_life_to_deck_bottom')
                    and any(c.card_type == 'EVENT' for c in revealed)
                    and opp.life):
                moved = opp.life.pop(0)
                opp.deck.insert(0, moved)
            return f'oponente revelou: {", ".join(c.name[:15] for c in revealed)}' if revealed else ''

        if action == 'both_trash_hand_until':
            limit = step.get('hand_size', 5)
            logs = []
            for owner, executor, label in (
                    (me, self, 'voce'),
                    (opp, EffectExecutor(opp, me), 'oponente')):
                trashed = []
                while len(owner.hand) > limit:
                    target = executor._choose_to_trash(owner.hand)
                    remove_by_identity(owner.hand, target)
                    owner.trash.append(target)
                    trashed.append(target.name[:12])
                if trashed:
                    logs.append(f'{label} trashou {", ".join(trashed)}')
            return ' | '.join(logs)

        if action == 'peek_opp_deck_top':
            # Efeito apenas informacional: nao move nem reordena a carta.
            # Memoria: passa a conhecer a identidade do topo do deck inimigo.
            if opp.deck:
                opp.revealed_deck.add(id(opp.deck[-1]))
            return 'olhou o topo do deck do oponente' if opp.deck else ''

        if action == 'reveal_opp_deck_top_choose_cost':
            # A escolha acontece ANTES da revelacao, portanto nunca usamos a
            # carta do topo para decidir o palpite. O censo representa a
            # informacao de decklist que a IA possui e escolhe o custo modal;
            # empates favorecem o menor custo para manter determinismo.
            if not opp.deck:
                return ''
            census = getattr(opp, 'full_deck_census', None) or {}
            by_cost = census.get('by_cost', {})
            if by_cost:
                chosen_cost = max(
                    ((int(cost), qty) for cost, qty in by_cost.items()),
                    key=lambda item: (item[1], -item[0]),
                )[0]
            else:
                # Estados unitarios/bridge antigos podem nao ter censo. Usa
                # um palpite fixo plausivel e, principalmente, nao consulta
                # o topo oculto para fabricar um acerto.
                chosen_cost = 3
            revealed = opp.deck[-1]
            opp.revealed_deck.add(id(revealed))  # memoria: topo do deck inimigo conhecido
            matched = revealed.cost == chosen_cost
            nested_logs = []
            if matched:
                for nested in step.get('on_match_steps', []):
                    nested_log = self._execute_step(nested, card)
                    if nested_log:
                        nested_logs.append(nested_log)
            result = (f'escolheu custo {chosen_cost}, revelou '
                      f'{revealed.name[:15]} (custo {revealed.cost})')
            if matched:
                result += ': acertou'
                if nested_logs:
                    result += ' | ' + ' | '.join(nested_logs)
            else:
                result += ': errou'
            return result

        if action == 'reveal_deck_top_conditional':
            # "Reveal 1 card from the top of your deck. If [condicao],
            # [efeito]. [Then, place the revealed card at the bottom of
            # your deck]." -- achado 16/07 (10 cartas: EB01-029, OP04-011,
            # OP14-044, OP15-065, ST17-001, ST22-003/006/007/012/016).
            # A carta revelada fica no TOPO por padrao (return_to=='top',
            # regra oficial de reveal sem mover) -- so vai pro fundo
            # quando o step diz explicitamente.
            if not me.deck:
                return ''
            revealed = me.deck[-1]
            cond = step.get('condition', {})
            matched = True
            if cond.get('revealed_card_type') and not _norm_type_text(
                    cond['revealed_card_type']) in _norm_type_text(revealed.sub_types):
                matched = False
            if matched and cond.get('revealed_card_cost_lte') is not None and \
                    revealed.cost > cond['revealed_card_cost_lte']:
                matched = False
            if matched and cond.get('revealed_card_cost_gte') is not None and \
                    revealed.cost < cond['revealed_card_cost_gte']:
                matched = False
            if matched and cond.get('revealed_card_power_gte') is not None and \
                    (revealed.card_type != 'CHARACTER' or revealed.power < cond['revealed_card_power_gte']):
                matched = False

            # "top_or_bottom" (jogador escolhe, achado 19/07, OP08-049):
            # sem escolha real modelada no engine, usa heuristica -- se
            # bateu a condicao, mantem no topo (a proxima compra ja e a
            # carta boa); se nao bateu, manda pro fundo (cicla a carta
            # inutil pra fora da proxima compra).
            if step.get('return_to') == 'bottom' or (
                    step.get('return_to') == 'top_or_bottom' and not matched):
                me.deck.pop()
                me.deck.insert(0, revealed)

            nested_logs = []
            if matched:
                for nested in step.get('on_match_steps', []):
                    nested_log = self._execute_step(nested, card)
                    if nested_log:
                        nested_logs.append(nested_log)

            result = f'revelou {revealed.name[:15]} do topo do deck'
            if matched:
                result += ': bateu a condicao'
                if nested_logs:
                    result += ' | ' + ' | '.join(nested_logs)
            else:
                result += ': nao bateu a condicao'
            return result

        if action == 'trash_deck_top_conditional':
            # "Trash N card(s) from the top of your deck. If the trashed
            # card has a cost of M or more/less, [efeito]." -- mesma
            # familia de reveal_deck_top_conditional, mas a carta MILHADA
            # (nao revelada) e quem determina a condicao. Achado 19/07,
            # OP08-096: mill = trash seco, sem disparar trigger da carta
            # milhada (regra do projeto), so a condicao de custo dela gate
            # o efeito seguinte.
            count = step.get('count', 1)
            trashed_cards = []
            for _ in range(min(count, len(me.deck))):
                c = me.deck.pop()
                me.trash.append(c)
                trashed_cards.append(c)
            if not trashed_cards:
                return ''
            last = trashed_cards[-1]
            cond = step.get('condition', {})
            matched = True
            if cond.get('trashed_card_cost_gte') is not None and last.cost < cond['trashed_card_cost_gte']:
                matched = False
            if matched and cond.get('trashed_card_cost_lte') is not None and last.cost > cond['trashed_card_cost_lte']:
                matched = False

            nested_logs = []
            if matched:
                for nested in step.get('on_match_steps', []):
                    nested_log = self._execute_step(nested, card)
                    if nested_log:
                        nested_logs.append(nested_log)

            result = f'trashou {", ".join(c.name[:12] for c in trashed_cards)} do topo do deck'
            if matched:
                result += ': bateu a condicao'
                if nested_logs:
                    result += ' | ' + ' | '.join(nested_logs)
            else:
                result += ': nao bateu a condicao'
            return result

        if action == 'trash_rest':
            # Cartas que foram vistas mas não pegas vão ao trash
            # Identifica quais cartas do topo foram vistas
            effects = get_card_effects(card.code)
            look_count = 5
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                        break
            # As cartas não tomadas ficam no topo do deck
            # Quantas foram tomadas: count do add_to_hand
            taken_count = 1
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') in ('add_to_hand', 'trash_from_looked_deck'):
                        taken_count = s.get('count', 1)
                        break
            # O resto = look_count - taken = vão ao trash
            rest_count = max(0, look_count - taken_count)
            trashed = []
            for _ in range(min(rest_count, len(me.deck))):
                if me.deck:
                    c = me.deck.pop()
                    me.trash.append(c)
                    trashed.append(c.name[:12])
            return f'trash resto: {", ".join(trashed)}' if trashed else ''

        if action == 'deck_bottom_rest':
            # Resto vai ao fundo do deck (já está no topo, move para o fundo)
            effects = get_card_effects(card.code)
            look_count = 5
            taken_count = 1
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                    if s.get('action') in ('add_to_hand', 'trash_from_looked_deck'):
                        taken_count = s.get('count', 1)
            rest_count = max(0, look_count - taken_count)
            moved = []
            for _ in range(min(rest_count, len(me.deck))):
                if me.deck:
                    c = me.deck.pop()  # tira do topo
                    me.deck.insert(0, c)  # coloca no fundo
                    moved.append(c)
            return f'{len(moved)} carta(s) no fundo do deck' if moved else ''

        if action in ('deck_reorder_rest', 'deck_top_rest'):
            # Achado 01/07/2026: 'deck_top_rest' e um nome de action
            # equivocado do parser -- TODAS as 21 ocorrencias reais no banco
            # (16 deck_reorder_rest + 5 deck_top_rest) sao o mesmo texto
            # "place the rest/them at the top OR BOTTOM of the deck in any
            # order" (escolha livre, nunca um "place at the top" puro sem
            # "or bottom"). 'deck_top_rest' nasceu de um regex que casa o
            # PREFIXO "place the rest at the top" antes de checar o sufixo
            # "or bottom" -- confirmado: nenhuma carta no banco tem so
            # "place the rest at the top" sem "or bottom". As duas actions
            # tem a MESMA semantica de execucao aqui (nao vale a pena tocar
            # o parser/regenerar DBs so por causa do nome).
            # Heuristica (mesmo principio do peek_life 'all'): a IA controla
            # a ordem livremente, entao bota a carta mais valiosa no TOPO
            # (fim da lista = proxima a ser comprada).
            effects = get_card_effects(card.code)
            look_count = 5
            taken_count = 0
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                    if s.get('action') in ('add_to_hand', 'trash_from_looked_deck'):
                        taken_count = s.get('count', 1)
            rest_count = max(0, look_count - taken_count)
            seen = []
            for _ in range(min(rest_count, len(me.deck))):
                seen.append(me.deck.pop())
            if not seen:
                return ''
            seen.sort(key=lambda c: c.board_value())  # pior primeiro, melhor por ultimo
            me.deck.extend(seen)  # melhor carta -> fim da lista = topo do deck
            return f'{len(seen)} carta(s) reordenada(s) no deck (melhor no topo)'

        if action == 'activate_main_effect':
            # Trigger que ativa o efeito Main da carta. CORRIGIDO 24/06:
            # antes chamava self.execute(card, 'main') DUAS vezes (uma no
            # if, outra no corpo) -- isso duplicava o efeito quando ambas
            # tinham sucesso, e causava IndexError quando a 2a chamada
            # retornava lista vazia (ex: 'main' tinha once_per_turn e já
            # havia sido consumido pela 1a chamada). Executa uma única vez
            # e junta os logs com segurança.
            logs = self.execute(card, 'main')
            return '; '.join(l for l in logs if l) if logs else ''

        if action == 'peek_life':
            target = step.get('target', 'any')
            count = step.get('count', 1)
            pools = ([(me, 'propria')] if target == 'self'
                     else [(opp, 'oponente')] if target == 'opponent'
                     else [(opp, 'oponente'), (me, 'propria')])
            for owner, label in pools:
                if not owner.life:
                    continue
                n = len(owner.life) if count == 'all' else min(int(count), len(owner.life))
                if count == 'all':
                    seen = owner.life[-n:]
                    owner.life[-n:] = sorted(
                        seen,
                        key=lambda c: c.board_value() + (2500 if c.has_trigger else 0),
                        reverse=(owner is me),
                    )
                    return f'olhou/reordenou {n} vida(s) ({label})'
                top = owner.life[-1]
                should_bottom = owner is opp and (top.has_trigger or top.counter > 0 or top.board_value() >= 5000)
                if should_bottom:
                    owner.life.insert(0, owner.life.pop())
                    return f'olhou vida do {label}: moveu topo para o fundo'
                return f'olhou vida do {label}: manteve topo'
            return ''

        if action == 'life_to_deck_top':
            if not me.life:
                return ''
            count = min(step.get('count', 1), len(me.life))
            moved = []
            for _ in range(count):
                # O controlador acabou de olhar toda a Life; coloca no topo
                # do deck a carta de maior valor estimado para a proxima compra.
                best = max(me.life, key=lambda c: c.board_value() + c.counter / 1000)
                remove_by_identity(me.life, best)
                best.life_face_up = False
                me.deck.append(best)
                moved.append(best.name[:15])
            return f'Life para topo do deck: {", ".join(moved)}'

        if action in ('turn_life_face_up', 'turn_life_face_down'):
            owner = opp if step.get('target') == 'opponent' else me
            if not owner.life:
                return ''
            count = len(owner.life) if step.get('count') == 'all' else min(int(step.get('count', 1)), len(owner.life))
            desired = action == 'turn_life_face_up'
            changed = 0
            for c in owner.life[-count:]:
                if c.life_face_up != desired:
                    c.life_face_up = desired
                    changed += 1
            face = 'face-up' if desired else 'face-down'
            return f'virou {changed} vida(s) {face}' if changed else f'vida ja estava {face}'

        if action == 'cannot_attack_leader_turn':
            me.cannot_attack_leader_this_turn = True
            return 'nao pode atacar Leader neste turno'

        if action == 'return_don_until_match_opp':
            target_total = opp.don_on_field()
            returned = 0
            while me.don_on_field() > target_total:
                before = me.don_on_field()
                if not self._return_don_to_deck(1, estado=me) or me.don_on_field() == before:
                    break
                returned += 1
            return f'devolveu {returned} DON ate igualar o oponente' if returned else ''

        # ── Draw ──────────────────────────────────────────────────────────────
        if action == 'draw':
            count = step.get('count', 1)
            # count_source='own_field_type_count': quantidade dinamica =
            # quantos Characters do proprio campo batem filter_type (ex:
            # EB04-011, "draw a card for each of your {Neptunian} type
            # Characters"), nao um numero fixo do banco.
            if step.get('count_source') == 'own_field_type_count':
                from optcg_engine.rules_facade import card_matches_filter
                filter_type = step.get('filter_type', '')
                count = sum(1 for c in me.field_chars if card_matches_filter(c, filter_type))
            drawn = []
            for _ in range(count):
                if me.deck:
                    c = me.deck.pop()
                    me.hand.append(c)
                    drawn.append(c.name[:12])
            # then_trash após draw
            then_trash = step.get('then_trash', 0)
            if step.get('then_trash_same_as_drawn'):
                # "Then, trash the same number of cards from your hand" --
                # sempre o total REALMENTE comprado (nao o count pretendido),
                # caso o deck tenha acabado antes de comprar tudo.
                then_trash = len(drawn)
            trashed_after = []
            for _ in range(then_trash):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    remove_by_identity(me.hand, worst)
                    me.trash.append(worst)
                    trashed_after.append(worst.name[:12])
            if not drawn:
                return ''
            msg = f'comprou: {", ".join(drawn)}'
            if trashed_after:
                msg += f' (e trashou: {", ".join(trashed_after)})'
            return msg

        # "Draw cards so that you have N cards in your hand" -- distinto de
        # 'draw' (quantidade fixa): aqui a quantidade e DINAMICA, calculada
        # no momento da execucao a partir do tamanho atual da mao. Se a mao
        # ja tem >= N cartas, nao compra nada (nunca DESCARTA pra baixo --
        # o texto so descreve "puxar ate", nunca "descer ate").
        if action == 'draw_to_hand_count':
            target = step.get('target_count', 0)
            need = max(0, target - len(me.hand))
            drawn = []
            for _ in range(need):
                if not me.deck: break
                c = me.deck.pop()
                me.hand.append(c)
                drawn.append(c.name[:12])
            return f'comprou ate {target} na mao: {", ".join(drawn)}' if drawn else ''

        if action == 'trash_to_hand_count':
            # "Trash cards from your hand until you have N cards in your
            # hand" -- espelho de draw_to_hand_count, direcao oposta
            # (achado 19/07, OP14-054 Fisher Tiger).
            target = step.get('target_count', 0)
            need = max(0, len(me.hand) - target)
            trashed = []
            for _ in range(need):
                worst = self._choose_to_trash(me.hand)
                if not worst:
                    break
                remove_by_identity(me.hand, worst)
                me.trash.append(worst)
                trashed.append(worst.name[:12])
            return f'descartou ate {target} na mao: {", ".join(trashed)}' if trashed else ''

        # ── KO ───────────────────────────────────────────────────────────────
        if action in ('ko', 'trash_character'):
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                choose_lowest_board_value,
                eligible_cards,
            )
            # 'trash_character' usa a MESMA mecanica de remocao de campo que
            # 'ko' (vai para o trash do dono). A diferenca de regra real do
            # jogo -- K.O. dispara o gatilho [On K.O.] do alvo, Trash de
            # personagem NAO dispara -- ainda nao tem efeito aqui porque o
            # engine hoje so dispara on_ko por morte em BATALHA (ver
            # _resolve_battle), nunca por efeito de carta de nenhum dos dois
            # tipos. Quando essa cascata for implementada para efeitos de
            # carta, ela deve checar `action == 'ko'` antes de disparar.
            count = step.get('count', 1)
            target_type = step.get('target', 'opp_character')
            cost_lte = self._resolve_cost_lte(step, default=None)
            cost_eq = step.get('cost_eq')
            power_lte = step.get('power_lte')
            rested_only = step.get('rested_only', False)
            total_power_lte = step.get('total_power_lte')

            if target_type == 'opp_stage':
                if opp.field_stage and (cost_lte is None or opp.field_stage.cost <= cost_lte):
                    ko_name = opp.field_stage.name[:20]
                    opp.trash.append(opp.field_stage)
                    opp.field_stage = None
                    return f'KO stage: {ko_name}'
                return ''

            # KO personagem(s) -- opp_character (so do oponente),
            # self_character (so o PROPRIO campo, ex: Five Elders OP13-082
            # "trash all of your Characters" -- distinto de all_character
            # por afetar so um lado), ou all_character (ambos os lados, ex:
            # board wipe simetrico do Kaido OP01-094/Kaido & Linlin OP08-119
            # -- exclude_self impede a propria carta se autodestruir,
            # confirmado por foto real "K.O. all Characters other than
            # this Character").
            def target_pool(cards):
                return eligible_cards(
                    cards,
                    cost_lte=cost_lte,
                    cost_eq=cost_eq,
                    power_lte=power_lte,
                    rested_only=rested_only,
                    filter_text=step.get('filter_type', ''),
                    exclude_card=card if step.get('exclude_self', False) else None,
                )

            if target_type == 'all_character':
                pools = [(opp, target_pool(opp.field_chars)),
                         (me, target_pool(me.field_chars))]
            elif target_type == 'self_character':
                pools = [(me, target_pool(me.field_chars))]
            else:
                pools = [(opp, target_pool(opp.field_chars))]

            koed = []
            sub_logs = []
            immune_skipped = []
            imm_kind = 'ko' if action == 'ko' else 'removal'
            for owner, candidates in pools:
                if total_power_lte is not None and owner is opp:
                    from itertools import combinations
                    feasible = []
                    for size in range(1, min(count, len(candidates)) + 1):
                        feasible.extend(combo for combo in combinations(candidates, size)
                                        if sum(c.power for c in combo) <= total_power_lte)
                    best_combo = max(
                        feasible,
                        key=lambda combo: (len(combo), sum(c.board_value() for c in combo)),
                        default=(),
                    )
                    candidates = list(best_combo)
                # Alvo no OPONENTE = remocao, mira o mais valioso. Alvo no
                # PROPRIO campo = sacrificio/drawback ("trash 1 dos seus"),
                # mira o MENOS valioso — mesma regua que
                # _worth_paying_optional_costs usou pra aprovar o custo
                # (min board_value); escolher o mais caro aqui pagaria um
                # custo aprovado como "quase gratis" com a melhor carta do
                # campo. Pra "trash all" (count 99, ex: Five Elders) a
                # ordem nao muda nada.
                escolhe = (choose_lowest_board_value if owner is me
                           else choose_highest_board_value)
                total_power_used = 0
                for _ in range(min(count, len(candidates))):
                    target = escolhe(candidates)
                    if (total_power_lte is not None
                            and total_power_used + target.power > total_power_lte):
                        remove_by_identity(candidates, target)
                        continue
                    # Imunidade: o alvo pode ser imune a KO/remoção por efeito do
                    # oponente. Pula o alvo (não conta como removido).
                    other = me if owner is opp else opp
                    source_is_opp = owner is opp
                    if is_immune(
                        target,
                        imm_kind,
                        owner,
                        other,
                        source_is_opp=source_is_opp,
                        ko_context='effect' if imm_kind == 'ko' else None,
                        # `card` = a carta cuja habilidade esta causando
                        # este KO/remocao -- necessario pra imunidade
                        # filtrada por power da FONTE (source_power_lte,
                        # achado 19/07, OP14-003). So passa quando `card`
                        # e de fato um Character (a clausula real so fala
                        # em "Characters" como fonte, nunca Event/Leader).
                        source_card=card if card.card_type == 'CHARACTER' else None,
                    ):
                        immune_skipped.append(target.name[:12])
                        remove_by_identity(candidates, target)
                        continue
                    # Antes de remover de fato, verifica se o ALVO tem
                    # substitute_ko/substitute_removal ativo -- e um efeito
                    # passivo do proprio target, avaliado do ponto de vista
                    # do SEU dono (quem paga o custo da substituicao).
                    ee_target = EffectExecutor(owner, me if owner is opp else opp)
                    sub_log = ee_target.try_any_substitute(
                        target,
                        'ko' if action == 'ko' else 'removal',
                        source_is_opp=source_is_opp,
                    )
                    if sub_log:
                        sub_logs.append(sub_log)
                        remove_by_identity(candidates, target)
                        continue
                    remove_character_from_field(owner, target, 'trash')
                    total_power_used += target.power
                    if action == 'ko':
                        ee_target.execute(target, 'on_ko', is_opp_turn=owner is opp)
                        ee_target._dispatch_damage_or_own_char_ko(owner, target)
                        ee_target._dispatch_opp_char_ko()
                        ee_target._dispatch_own_char_ko(target)
                        ee_target._dispatch_any_char_ko(target)
                    self._dispatch_own_effect_removes_char(
                        'ko' if action == 'ko' else 'trash',
                        'opp' if owner is opp else 'own')
                    remove_by_identity(candidates, target)
                    koed.append(target.name[:15])
            label = 'KO' if action == 'ko' else 'Trash'
            partes = []
            if koed:
                partes.append(f'{label}: {", ".join(koed)}')
            if immune_skipped:
                partes.append(f'imune: {", ".join(immune_skipped)}')
            partes.extend(sub_logs)

            # Alvo ALTERNATIVO ("... or your opponent's Stages with a cost
            # of N or less", achado 19/07, OP03-096): so tenta o Stage se
            # nao havia Character elegivel pro alvo principal (escolha
            # unica entre os dois, nao os dois juntos).
            if not koed and step.get('alt_target') == 'opp_stage' and opp.field_stage:
                alt_cost_lte = step.get('alt_cost_lte')
                if alt_cost_lte is None or opp.field_stage.cost <= alt_cost_lte:
                    stage_name = opp.field_stage.name[:20]
                    opp.trash.append(opp.field_stage)
                    opp.field_stage = None
                    partes.append(f'KO stage: {stage_name}')

            return ' | '.join(partes)

        # ── KO condicional sobre a carta selecionada anteriormente no bloco ──
        if action == 'ko_selected':
            # "Then, if that Character has a cost of N or less, K.O. it" --
            # segunda clausula encadeada apos negate_effect (achado 15/07,
            # OP09-098 Black Hole). Alvo = self._last_selected, gravado pelo
            # step anterior no MESMO bloco (negate_effect). Mira sempre o
            # campo do OPONENTE (e o unico caso ate agora).
            alvo = self._last_selected
            cost_lte = step.get('cost_lte')
            power_lte = step.get('power_lte')
            if alvo is None or alvo not in opp.field_chars:
                return ''
            if cost_lte is not None and alvo.cost > cost_lte:
                return ''
            if power_lte is not None and alvo.effective_power() > power_lte:
                return ''
            if is_immune(alvo, 'ko', opp, me, source_is_opp=True, ko_context='effect'):
                return f'imune: {alvo.name[:15]}'
            ee_target = EffectExecutor(opp, me)
            sub_log = ee_target.try_any_substitute(alvo, 'ko', source_is_opp=True)
            if sub_log:
                return sub_log
            ko_name = alvo.name[:15]
            remove_character_from_field(opp, alvo, 'trash')
            ee_target.execute(alvo, 'on_ko', is_opp_turn=True)
            ee_target._dispatch_damage_or_own_char_ko(opp, alvo)
            ee_target._dispatch_opp_char_ko()
            ee_target._dispatch_own_char_ko(alvo)
            ee_target._dispatch_any_char_ko(alvo)
            self._dispatch_own_effect_removes_char('ko', 'opp')
            return f'KO: {ko_name}'

        # ── Bounce ───────────────────────────────────────────────────────────
        if action == 'bounce':
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                eligible_cards,
            )
            count = step.get('count', 1)
            cost_lte = self._resolve_cost_lte(step, default=99)

            target_owner = me if step.get('target') == 'own_character' else opp
            candidates = eligible_cards(
                target_owner.field_chars,
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                power_gte=step.get('power_gte'),
                power_eq=step.get('power_eq'),
                rested_only=step.get('rested_only', False),
                active_only=step.get('active_only', False),
                filter_text=step.get('filter_type', ''),
            )
            bounced = []
            immune_skipped = []
            for _ in range(min(count, len(candidates))):
                target = (min(candidates, key=lambda c: c.board_value())
                          if target_owner is me else choose_highest_board_value(candidates))
                # Bounce é remoção do campo -> respeita imunidade a removal
                if (target_owner is opp
                        and is_immune(target, 'removal', opp, me, source_is_opp=True)):
                    immune_skipped.append(target.name[:12])
                    remove_by_identity(candidates, target)
                    continue
                remove_character_from_field(target_owner, target, 'hand')
                self._dispatch_own_effect_removes_char(
                    'bounce', 'opp' if target_owner is opp else 'own')
                remove_by_identity(candidates, target)
                bounced.append(target.name[:15])
                # Memoria (SaveTargetName, mesmo padrao ja usado por
                # buff_power/play_from_deck/negate_effect): um step
                # POSTERIOR no MESMO bloco pode referenciar "the returned
                # Character" (ex: Trafalgar Law OP01-002, "play up to 1
                # Character... that is a different color than the
                # returned Character" -- achado 30/07).
                self._last_selected = target
            out = []
            if bounced: out.append(f'bounce: {", ".join(bounced)}')
            if immune_skipped: out.append(f'imune: {", ".join(immune_skipped)}')
            return ' | '.join(out)

        # ── Restar oponente ───────────────────────────────────────────────────
        if action == 'rest_opp_character':
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                eligible_cards,
            )
            count = step.get('count', 1)
            cost_lte = self._resolve_cost_lte(step, default=99)

            # imunidade a rest forçado (achado 01/07/2026, ex: OP12-021,
            # OP15-024, OP11-046) -- DISTINTA de cannot_be_rested_until
            # (trava posta por OUTRA carta, mecanica oposta, ja filtrada
            # acima).
            candidates = eligible_cards(
                [c for c in opp.field_chars
                 if not c.cannot_be_rested_until
                 and not is_immune(c, 'rest', opp, self.me, source_is_opp=True)],
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                don_attached_gte=step.get('don_attached_gte'),
                active_only=True,
                filter_text=step.get('filter_types') or step.get('filter_type', ''),
            )
            rested = []
            sub_logs = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                # Substituicao de rest (achado 15/07, PRB02-006 Zoro): "If
                # this Character would be rested by your opponent's
                # Character's effect, you may rest 1 of your other
                # Characters instead". Checado do ponto de vista do DONO
                # do alvo (mesmo padrao ja usado por KO/removal acima --
                # EffectExecutor(opp, self.me), 'opp' aqui e quem SERIA
                # restado).
                ee_target = EffectExecutor(opp, self.me)
                sub_log = ee_target.try_any_substitute(target, 'rest', source_is_opp=True)
                if sub_log:
                    sub_logs.append(sub_log)
                    remove_by_identity(candidates, target)
                    continue
                target.rested = True
                remove_by_identity(candidates, target)
                rested.append(target.name[:15])
            out = []
            if rested: out.append(f'restou: {", ".join(rested)}')
            if sub_logs: out.append(' | '.join(sub_logs))
            if (not rested and not sub_logs and step.get('or_rest_opp_don')
                    and opp.don_available > 0):
                opp.don_available -= 1
                opp.don_rested += 1
                out.append('restou 1 DON do oponente')
            return ' | '.join(out)

        # ── rest_opp_don: restar DON!! do OPONENTE -- desvantagem de tempo
        # (ele tem menos DON ativo pro turno dele), DISTINTA de
        # rest_opp_character (alvo é Character, não DON!! card). Achado na
        # auditoria do censo 0_nao_classificado (27/06): P-060 Tot Musica,
        # ST02-008 Scratchmen Apoo. NUNCA confundir com don_minus (que
        # devolve DON ao deck do PRÓPRIO jogador como custo) -- aqui o DON
        # do oponente continua no campo dele, só fica rested.
        # "Rest your opponent's Leader." -- forcado, incondicional, alvo
        # sempre o Leader do oponente (achado 19/07, OP16-039).
        if action == 'rest_opp_leader':
            opp.leader.rested = True
            return 'restou o Lider do oponente'

        if action == 'rest_opp_don':
            count = step.get('count', 1)
            rested_n = min(count, opp.don_available)
            opp.don_available -= rested_n
            opp.don_rested += rested_n
            return f'restou {rested_n} DON do oponente' if rested_n else ''

        # ── opp_don_minus: FORÇA o oponente a devolver N DON!! do campo
        # dele pro DON deck DELE (perde DON pro resto da partida, mais forte
        # que rest_opp_don que só atrasa por 1 turno). DISTINTA de
        # don_minus (que devolve DON do PRÓPRIO jogador como custo). Achado
        # 27/06: Magellan OP02-085/OP16-074, Senor Pink OP14-065, Judgment
        # of Hell, Hydra, Venom Road. Reaproveita _return_don_to_deck
        # generalizada -- mesma preferência de "devolver o DON que menos
        # importa" vale pro oponente escolhendo por si mesmo.
        if action == 'opp_don_minus':
            count = step.get('count', 1)
            self._return_don_to_deck(count, estado=opp)
            return f'oponente devolveu até {count} DON pro deck'

        # "your opponent adds N card(s) from their Life area to their hand"
        # -- forca o oponente a mover da propria vida para a propria mao
        # (enfraquece a vida dele, da carta a ele na mao). P-009 Law.
        if action == 'opp_life_to_hand':
            count = step.get('count', 1)
            moved = []
            for _ in range(min(count, len(opp.life))):
                c = opp.life.pop()
                c.life_face_up = False
                opp.hand.append(c)
                moved.append(c.name[:12])
            return f'oponente moveu da vida pra mao: {", ".join(moved)}' if moved else ''

        # ── KO se custo == DON anexado (OP15-031 Purinpurin) ────────────────────
        # "Select up to 1 of your opponent's rested Characters. If the chosen
        # Character has a cost equal to the number of DON!! cards given to it,
        # K.O. it." -- escolhe o melhor rested do oponente que satisfaz a
        # condicao cost == don_attached; KO se achar.
        if action == 'ko_if_cost_eq_don':
            from optcg_engine.rules_facade import card_matches_filter
            filter_type = step.get('filter_type', '')
            rested_only = step.get('rested_only', True)
            candidates = [c for c in opp.field_chars
                          if (not rested_only or c.rested)
                          and card_matches_filter(c, filter_type)
                          and c.cost == c.don_attached
                          and not is_immune(c, 'ko', opp, me, source_is_opp=True)]
            if candidates:
                # escolhe o mais valioso que satisfaz a condicao
                alvo = max(candidates, key=lambda c: c.board_value())
                remove_character_from_field(opp, alvo, 'trash')
                ee_ko = EffectExecutor(opp, me)
                ee_ko.execute(alvo, 'on_ko', is_opp_turn=False)
                ee_ko._dispatch_opp_char_ko()
                ee_ko._dispatch_own_char_ko(alvo)
                ee_ko._dispatch_any_char_ko(alvo)
                self._dispatch_own_effect_removes_char('ko', 'opp')
                return f'K.O. {alvo.name[:15]} (cost=={alvo.cost}==DON!!)'
            return ''

        # ── Swap base power entre 2 Characters (OP14-001/OP14-017) ─────────────
        if action == 'swap_base_power':
            from optcg_engine.rules_facade import eligible_cards, card_matches_filter
            target = step.get('target', 'own_two_chars')
            filter_type = step.get('filter_type', '')
            power_lte = step.get('power_lte')
            if target == 'leader_and_own_character':
                # "Select your Leader and 1 Character. Swap the base
                # power of the selected cards" -- par FIXO (Leader +
                # melhor Character proprio por board_value), distinto de
                # own_two_chars (2 Characters, sem Leader). Achado 17/07,
                # OP14-009 (unica carta no banco).
                if not me.field_chars:
                    return ''
                alvo_char = max(me.field_chars, key=lambda c: c.board_value())
                pa = me.leader.effective_power(True)
                pb = alvo_char.effective_power(True)
                me.leader.base_power_override = pb
                alvo_char.base_power_override = pa
                return (f'trocou power: Lider({pa}->{pb}) / '
                        f'{alvo_char.name[:12]}({pb}->{pa})')
            pool = me.field_chars if 'own' in target else opp.field_chars
            cands = [c for c in pool
                     if card_matches_filter(c, filter_type)
                     and (power_lte is None or c.effective_power(True) <= power_lte)]
            if len(cands) >= 2:
                # Escolhe os dois com maior board_value
                cands.sort(key=lambda c: -c.board_value())
                a, b = cands[0], cands[1]
                pa = a.effective_power('own' in target)
                pb = b.effective_power('own' in target)
                a.base_power_override = pb
                b.base_power_override = pa
                return f'trocou power: {a.name[:12]}({pa}->{pb}) / {b.name[:12]}({pb}->{pa})'
            return ''

        # ── Mutual KO após batalha (ST08-013 Mr.2) ──────────────────────────────
        # "K.O. the opponent's Character you battled with. If you do, K.O. this
        # Character." -- simplificacao: KO o melhor char do oponente + KO self.
        if action == 'ko_battled_opp_char_and_self':
            if opp.field_chars:
                target_opp = max(opp.field_chars, key=lambda c: c.board_value())
                if not is_immune(target_opp, 'ko', opp, me, source_is_opp=True):
                    remove_character_from_field(opp, target_opp, 'trash')
                    ee_opp = EffectExecutor(opp, me)
                    ee_opp.execute(target_opp, 'on_ko', is_opp_turn=True)
                    ee_opp._dispatch_opp_char_ko()
                    ee_opp._dispatch_own_char_ko(target_opp)
                    ee_opp._dispatch_any_char_ko(target_opp)
                    # KO self (o proprio character que ativou o efeito)
                    if contains_identity(me.field_chars, card):
                        remove_character_from_field(me, card, 'trash')
                    return f'KO mutuo: {target_opp.name[:12]} e {card.name[:12]}'
            return ''

        # ── ST13-003 Luffy Leader: face-up Life → deck bottom rule ─────────────
        if action == 'face_up_life_to_deck_rule':
            me.face_up_life_to_deck = True
            return 'regra: vida face-up vai pro fundo do deck em vez da mao'

        # ── Redirect attack target (OP14-060) -- no-op engine, parser only ──────
        if action == 'redirect_attack_target':
            return ''  # complexidade de interrupcao de resolucao de ataque inviavel

        # ── Activate trash event Main (EB03-031) -- no-op engine, parser only ───
        if action == 'activate_trash_event_main':
            return ''  # executar efeito de evento do trash exige VM separada

        # ── Imunidade a KO temporária para tipo próprio (OP09-033 Nico Robin) ──
        # Concede immunity_ko_until a todos os PROPRIOS Characters que
        # correspondem ao filter_type. Limpo no refresh_phase do dono.
        if action == 'grant_ko_immunity_type':
            from optcg_engine.rules_facade import card_matches_filter
            filter_type = step.get('filter_type', '')
            cost_lte = step.get('cost_lte')
            dur = step.get('duration', 'opp_turn_end')
            # Sempre so os PROPRIOS Characters de campo -- o Leader nunca
            # entra nesta acao (o texto de toda carta conhecida usando
            # este mecanismo diz "Characters"/"[Tipo] type Characters",
            # nunca "Leader or Characters", e Leader nao tem custo de
            # deck comparavel). Corrigido 19/07 (achado ao implementar
            # OP08-038, sem filter_type/cost_lte nenhum): o antigo
            # `+ [me.leader]` quando cost_lte is None tambem alcancava
            # chamadas com SO filter_type (ex: OP09-033 Nico Robin) --
            # se o Leader tivesse o mesmo tipo, ganhava imunidade nunca
            # concedida pelo texto real da carta.
            power_lte = step.get('power_lte')
            pool = me.field_chars
            granted = []
            for c in pool:
                if cost_lte is not None and c.cost > cost_lte:
                    continue
                # filtro de POWER (base power, achado 19/07, OP10-070
                # Trebol) -- distinto de cost_lte, "N base power or less".
                if power_lte is not None and c.power > power_lte:
                    continue
                if filter_type and not card_matches_filter(c, filter_type):
                    continue
                c.immunity_ko_until = dur
                granted.append(c.name[:12])
            return f'imunidade a KO concedida: {", ".join(granted)}' if granted else ''

        # ── Coloca Character do oponente na VIDA DELE face-up ──────────────────
        # "Add up to N of your opponent's [X] Characters to the top/bottom of
        # your opponent's Life cards face-up." (OP04-097 Otama, OP05-111 Hotori,
        # EB02-057 Mad Treasure). Remove do campo do oponente e insere na vida
        # dele (face-up). Heuristica: escolhe o PIOR Character do oponente (menor
        # board_value) pra maximizar o dano ao campo dele; o destino dentro da
        # vida e o topo ('life_top') por padrao.
        if action == 'place_opp_char_to_opp_life':
            from optcg_engine.rules_facade import eligible_cards, card_matches_filter
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte')
            filter_type = step.get('filter_type', '')
            candidates = [c for c in opp.field_chars
                          if (cost_lte is None or c.cost <= cost_lte)
                          and card_matches_filter(c, filter_type)]
            placed = []
            for _ in range(min(count, len(candidates))):
                worst = min(candidates, key=lambda c: c.board_value())
                # Move direto campo -> Life. Usar 'hand' aqui duplicava a
                # carta na mao e na Life ao mesmo tempo.
                worst.life_face_up = True
                dest = step.get('dest', 'life_top')
                real_dest = 'life_bottom' if dest == 'life_bottom' else 'life_top'
                remove_character_from_field(opp, worst, real_dest)
                remove_by_identity(candidates, worst)
                placed.append(worst.name[:12])
            return f'mandou {", ".join(placed)} pra vida do oponente face-up' if placed else ''

        if action == 'character_to_owner_life':
            from optcg_engine.rules_facade import card_matches_filter
            target_scope = step.get('target', 'any')
            cost_lte = step.get('cost_lte')
            cost_eq = step.get('cost_eq')
            power_eq = step.get('power_eq')
            filter_type = step.get('filter_type', '')
            exclude = step.get('exclude', '').lower()

            def eligible(owner, c):
                return ((cost_lte is None or c.cost <= cost_lte)
                        and (cost_eq is None or c.cost == cost_eq)
                        and (power_eq is None or c.power == power_eq)
                        and card_matches_filter(c, filter_type)
                        and (not exclude or exclude not in c.name.lower()))

            pools = []
            if target_scope in ('own', 'any'):
                pools.extend((me, c, False) for c in me.field_chars if eligible(me, c))
            if target_scope in ('opponent', 'any'):
                pools.extend((opp, c, True) for c in opp.field_chars if eligible(opp, c))
            moved = []
            for _ in range(min(step.get('count', 1), len(pools))):
                # Para alvo livre, remover a maior ameaca adversaria tem
                # precedencia; em alvo proprio, salva o menor board value.
                opp_pool = [x for x in pools if x[2]]
                if opp_pool:
                    owner, chosen, is_opp = max(
                        opp_pool, key=lambda x: x[1].board_value())
                    if is_immune(chosen, 'removal', opp, me, source_is_opp=True):
                        pools.remove((owner, chosen, is_opp))
                        continue
                else:
                    owner, chosen, is_opp = min(
                        pools, key=lambda x: x[1].board_value())
                dest = step.get('dest', 'life_top')
                # top_or_bottom e escolha do controlador; topo e o default
                # deterministico atual, preservando a carta como proxima Life.
                real_dest = 'life_bottom' if dest == 'life_bottom' else 'life_top'
                remove_character_from_field(owner, chosen, real_dest)
                chosen.life_face_up = step.get('face') == 'up'
                pools.remove((owner, chosen, is_opp))
                moved.append(chosen.name[:14])
            return f'campo -> Life do dono: {", ".join(moved)}' if moved else ''

        # ── Trava de ataque / trava de rest / trava de Blocker (persistente) ────
        # Mecanicas DISTINTAS apesar de compartilharem estrutura de
        # implementacao: lock_opp_character_attack impede ATACAR;
        # lock_opp_cannot_be_rested impede o character de ficar RESTED por
        # qualquer meio (atacar, bloquear, ou efeito); lock_opp_blocker_turn
        # impede especificamente de usar [Blocker] (Limejuice OP09-014, Kuzan
        # OP16-063) -- DISTINTA de lock_opp_blocker_battle (essa aqui e
        # persistente, escolhe 1 character especifico e dura alem desta
        # batalha; a outra e transitoria e trava o campo todo/filtrado so na
        # batalha que esta sendo resolvida agora). Nunca tratar como
        # sinonimos -- confirmado por Arthur.
        if action in ('lock_opp_character_attack', 'lock_opp_cannot_be_rested', 'lock_opp_blocker_turn'):
            count = step.get('count', 1)
            cost_lte = self._resolve_cost_lte(step, default=None)
            power_lte = step.get('power_lte')
            exclude = step.get('exclude', '').lower()
            DUR_MAP = {
                'until_opp_turn_end': 'opp_turn_end',
                'until_opp_end_phase': 'opp_end_phase',
                'until_my_next_turn_start': 'my_next_turn_start',
            }
            dur = DUR_MAP.get(step.get('duration', 'until_opp_turn_end'), 'opp_turn_end')

            candidates = [c for c in opp.field_chars
                          if (cost_lte is None or c.cost <= cost_lte)
                          and (power_lte is None or c.power <= power_lte)
                          and (action != 'lock_opp_blocker_turn' or c.is_blocker())
                          and (not exclude or exclude not in c.name.lower())]

            locked = []
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                if action == 'lock_opp_character_attack':
                    target.cannot_attack_until = dur
                elif action == 'lock_opp_cannot_be_rested':
                    target.cannot_be_rested_until = dur
                else:
                    target.cannot_block_until = dur
                remove_by_identity(candidates, target)
                locked.append(target.name[:15])
            verbo = {'lock_opp_character_attack': 'atacar',
                     'lock_opp_cannot_be_rested': 'ficar rested',
                     'lock_opp_blocker_turn': 'bloquear'}[action]
            return f'travou (não pode {verbo}): {", ".join(locked)}' if locked else ''

        # ── Trava de ataque condicional a pagamento ─────────────────────────────
        # DISTINTA de lock_opp_character_attack: aqui o character do oponente
        # PODE atacar, mas o oponente paga um custo (ex: trash N cards) a cada
        # ataque enquanto a trava estiver ativa. Implementado em 01/07/2026:
        # `attack_paywall` (campo novo em Card) guarda {'cost_type',
        # 'cost_amount'}; os pontos que filtram "pode atacar" (mesmos 6 que
        # checam cannot_attack_until) tambem checam
        # `can_afford_attack_paywall()`; o pagamento de verdade acontece em
        # `_resolve_attack` no momento de declarar o ataque (simplificacao
        # deliberada: paga sempre que pode, sem modelar "vale a pena" --
        # mesmo padrao que o resto do engine usa pra custos de ativacao).
        # Unica carta no banco: OP08-043 Edward.Newgate, count=99 = "select
        # ALL of your opponent's Characters on their field" (sem escolha).
        if action == 'lock_opp_attack_unless_pays':
            count = step.get('count', 99)
            cost_type = step.get('cost_type', 'trash_from_hand')
            cost_amount = step.get('cost_amount', 1)
            DUR_MAP = {
                'until_opp_turn_end': 'opp_turn_end',
                'until_opp_end_phase': 'opp_end_phase',
                'until_my_next_turn_start': 'my_next_turn_start',
            }
            dur = DUR_MAP.get(step.get('duration', 'until_opp_turn_end'), 'opp_turn_end')
            targets = list(opp.field_chars)[:count]
            for t in targets:
                t.attack_paywall = {'cost_type': cost_type, 'cost_amount': cost_amount, 'until': dur}
            names = ', '.join(t.name[:15] for t in targets)
            return f'travou (so ataca pagando {cost_amount} cartas): {names}' if names else ''

        # ── Trava de Refresh Phase (Freeze -- nao fica ativo no proximo
        # refresh) ───────────────────────────────────────────────────────────
        # lock_opp_character_refresh / lock_opp_don_refresh: trava o character
        # ou DON do OPONENTE de virar active na proxima Refresh Phase dele.
        # lock_self_character_refresh: trava o PROPRIO character (geralmente
        # custo de um efeito forte do jogador) -- alvo OPOSTO dos dois
        # anteriores, nunca tratar como sinonimo. refresh_phase consome
        # frozen_next_refresh/frozen_don_count (implementado 28/06/2026).
        if action == 'lock_opp_character_refresh':
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte')
            cost_eq = step.get('cost_eq')
            power_lte = step.get('power_lte')
            don_attached_gte = step.get('don_attached_gte')
            candidates = [c for c in opp.field_chars
                          if c.rested
                          and (cost_lte is None or c.cost <= cost_lte)
                          and (cost_eq is None or c.cost == cost_eq)
                          and (power_lte is None or c.power <= power_lte)
                          and (don_attached_gte is None or c.don_attached >= don_attached_gte)]
            locked = []
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                target.frozen_next_refresh = True
                remove_by_identity(candidates, target)
                locked.append(target.name[:15])
            return f'congelou (não desvira no próx. refresh): {", ".join(locked)}' if locked else ''

        if action == 'lock_opp_don_refresh':
            count = step.get('count', 1)
            opp.frozen_don_count += count
            return f'congelou até {count} DON do oponente (não desvira no próx. refresh)'

        # Alvo MISTO: trava o Leader do oponente (sempre, se rested) E ate
        # N Characters rested dele (achado 19/07, OP07-059 -- unica carta
        # com essa selecao combinada; antes caia no fallback errado
        # lock_opp_don).
        if action == 'lock_opp_leader_and_character_refresh':
            count = step.get('count', 1)
            locked = []
            if opp.leader.rested:
                opp.leader.frozen_next_refresh = True
                locked.append(opp.leader.name[:15])
            candidates = [c for c in opp.field_chars if c.rested]
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                target.frozen_next_refresh = True
                remove_by_identity(candidates, target)
                locked.append(target.name[:15])
            return f'congelou (não desvira no próx. refresh): {", ".join(locked)}' if locked else ''

        if action == 'lock_self_character_refresh':
            if step.get('target') == 'this_card':
                card.frozen_next_refresh = True
                return f'{card.name[:15]} congelado (não desvira no próx. refresh)'
            # target == 'selected': alvo escolhido por um step ANTERIOR no
            # mesmo bloco (ex: EB02-021 "up to 1 Character gains +6000 power
            # ... THEN the selected Character will not become active") --
            # consome _last_selected (memoria de alvo entre steps,
            # implementado 28/06/2026 junto com buff_power
            # target='select_filtered'). Sem alvo memorizado, nao executa.
            alvo = self._last_selected
            if alvo is None:
                return ''
            alvo.frozen_next_refresh = True
            return f'{alvo.name[:15]} (selecionado antes) congelado (não desvira no próx. refresh)'

        # ── lock_opp_blocker_battle: trava o Blocker do oponente NESTA
        # batalha (quem está atacando agora) -- DISTINTA dos cannot_attack_*
        # acima e de lock_opp_character_refresh: aqui é transitória (só essa
        # batalha, _resolve_battle limpa logo depois) e afeta a ELEGIBILIDADE
        # de Blocker, não a capacidade de atacar. blockers_active() já lê
        # opp.blocker_lock_battle -- aqui só seta o filtro (ou None pra
        # campo todo) antes do block step rodar.
        if action == 'lock_opp_blocker_battle':
            lock = {}
            if step.get('power_lte') is not None: lock['power_lte'] = step['power_lte']
            if step.get('power_gte') is not None: lock['power_gte'] = step['power_gte']
            if step.get('cost_lte') is not None: lock['cost_lte'] = step['cost_lte']
            opp.blocker_lock_battle = lock
            filtro = ', '.join(f'{k}={v}' for k, v in lock.items()) or 'campo todo'
            return f'oponente nao pode usar Blocker nesta batalha ({filtro})'

        # ── Substituicao de power base (set_base_power) ─────────────────────────
        # Mecanica DISTINTA de buff_power/debuff_power: 'base power becomes N'
        # substitui o valor (ignora buffs aditivos anteriores aplicados sobre a
        # base), nao soma. `base_power_override` (campo em Card) e consumido
        # por `effective_card_power` em rules_facade.py -- JA implementado e
        # correto pra valor FIXO (target 'leader'/'self'/'own_character'/
        # 'leader_or_own_character', 8 cards, ex: OP15-092 Monkey.D.Luffy,
        # EB04-003/004). `source` (achado 28/06/2026, MatchLeaderToBasePower)
        # cobre o caso DINAMICO -- "becomes the same as [outra carta]",
        # sem numero literal no banco -- 12 cartas a mais.
        if action == 'set_base_power':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_effective_power,
            )
            amount = step.get('amount')
            source = step.get('source')
            if source:
                # MatchLeaderToBasePower (achado 28/06/2026, 12 cartas
                # reais): valor DINAMICO, calculado do estado atual em vez
                # de um amount fixo do banco. Sempre target='self' (a
                # propria carta do efeito, unico caso confirmado).
                if source == 'opp_leader':
                    amount = opp.leader.effective_power(False)
                elif source == 'own_leader':
                    amount = me.leader.effective_power(True)
                elif source == 'selected_opp_character':
                    from optcg_engine.rules_facade import (
                        eligible_cards,
                        choose_highest_effective_power,
                    )
                    candidatos = eligible_cards(opp.field_chars)
                    if not candidatos:
                        return ''
                    alvo = choose_highest_effective_power(candidatos,
                                                          your_turn=False)
                    amount = alvo.effective_power(False)
                elif source == 'opp_attacking_character':
                    # OP04-069: alvo = quem esta ATACANDO agora (nao
                    # qualquer Character do oponente) -- so disponivel
                    # via battle_attacker, setado pelo call site real de
                    # batalha (execute(..., battle_attacker=attacker) em
                    # on_opp_attack). Sem batalha em curso, nao executa
                    # (mais seguro que adivinhar um alvo).
                    atacante = getattr(self, '_battle_attacker', None)
                    if atacante is None:
                        return ''
                    # e o turno de ATAQUE do oponente -- do ponto de vista
                    # do proprio atacante, e o turno dele (your_turn=True).
                    amount = atacante.effective_power(True)
                else:
                    return None
                card.base_power_override = int(amount)
                return f'base power de {card.name[:15]} virou {amount} ({source})'
            if amount is None:
                return None

            target = step.get('target', 'self')
            filter_type = step.get('filter_type') or ''

            if target == 'self':
                candidates = [card] if card_matches_filter(card, filter_type) else []
            elif target == 'leader':
                candidates = [me.leader] if card_matches_filter(me.leader, filter_type) else []
            elif target == 'own_character':
                candidates = [c for c in me.field_chars
                              if card_matches_filter(c, filter_type)]
            elif target in ('leader_or_own_character', 'leader_or_character'):
                candidates = [c for c in [me.leader] + me.field_chars
                              if card_matches_filter(c, filter_type)]
            elif target == 'opp_character':
                # "Set the power of up to N of your opponent's Characters to X"
                # (Ain OP07-002). Escolhe o mais valioso -- beneficia mais
                # zerando o Character que ameaca mais.
                count = step.get('count', 1)
                candidates = sorted(
                    [c for c in opp.field_chars if card_matches_filter(c, filter_type)],
                    key=lambda c: -c.board_value()
                )[:count]
                for c in candidates:
                    c.base_power_override = int(amount)
                return f'power de {", ".join(c.name[:12] for c in candidates)} virou {amount}'
            else:
                candidates = []

            if not candidates:
                return None

            chosen = choose_highest_effective_power(candidates, your_turn=True)
            chosen.base_power_override = int(amount)
            return f'base power de {chosen.name[:15]} virou {amount}'

        # ── Self-lock de ataque (incondicional / condicional / em massa) ────────
        # Achado 01/07/2026: este comentario estava DESATUALIZADO -- a trava
        # ja e aplicada de verdade, so que por um caminho diferente deste
        # branch. `is_attack_locked_self()` (definida no topo do arquivo) le
        # `effects['passive']['steps']` DIRETO de `get_card_effects()` (sem
        # depender de nenhum estado setado aqui) e ja e chamada nos 5+
        # pontos que filtram "pode atacar" (my_attack_power, geracao de
        # acoes de ataque, Turn Planner). Esses steps TAMBEM passam por aqui
        # via `apply_your_turn_buffs()` (que executa TODO step de 'passive',
        # nao so buffs) -- mas como a trava real ja acontece em
        # is_attack_locked_self(), este branch e so um no-op silencioso
        # (evita logar a mensagem antiga de "nao implementado" toda vez que
        # uma dessas 6 cartas tem o turno passado em revista). Cartas
        # cobertas: cannot_attack_self (3: OP06-083, OP11-058, OP14-056,
        # mais P-084 que tambem usa esta action pra si mesmo), unless (2:
        # EB04-005, EB04-051), mass-lock condicional (1: P-084, via
        # `mass_lock_conditional` separado, nao por este branch).
        if action in ('cannot_attack_self', 'cannot_attack_self_unless', 'cannot_attack_own_characters_by_cost'):
            return ''

        # ── Power buff ────────────────────────────────────────────────────────
        if action == 'buff_power':
            amount = step.get('amount', 0)
            target = step.get('target', 'self')
            duration = step.get('duration', 'this_turn')

            if target == 'self':
                card.power_buff += amount
            elif target == 'leader':
                # "Up to 1 of your Leader with N power or less gains +X
                # power" (achado 16/07, OP09-007) -- power_lte filtra se o
                # buff se aplica, checado contra o power EFETIVO atual do
                # Leader (base + buffs ja acumulados), nao so o base.
                power_lte = step.get('power_lte')
                if power_lte is not None and me.leader.effective_power(True) > power_lte:
                    return ''
                me.leader.power_buff += amount
            elif target == 'leader_or_character':
                # "Up to a total of N of your Leader and Character cards
                # gain +X power" -- N>1 (achado 17/07, EB02-007, unica
                # carta no banco): repete a escolha do mais forte restante
                # ate N ou os candidatos acabarem, mesmo padrao ja usado
                # por own_character/opp_character count>1.
                count_lc = step.get('count', 1)
                pool = list(me.field_chars) + [me.leader]
                best = None
                for _ in range(min(count_lc, len(pool))):
                    best = max(pool, key=lambda c: c.effective_power(True))
                    best.power_buff += amount
                    remove_by_identity(pool, best)
                # grava a ULTIMA selecao (SaveTargetName) pra um step
                # POSTERIOR no MESMO bloco poder referenciar "that card
                # gains an additional +N power" (target='selected').
                # Achado 17/07, OP12-098.
                self._last_selected = best
            elif target == 'selected':
                # "that card gains an additional +N power" -- refere-se a
                # carta escolhida por um step ANTERIOR no MESMO bloco
                # (leader_or_character/select_filtered). Sem selecao previa
                # (_last_selected None), no-op silencioso -- mesmo criterio
                # ja usado por outras acoes com este target. Achado 17/07,
                # OP12-098.
                alvo_sel = getattr(self, '_last_selected', None)
                if alvo_sel is None:
                    return ''
                alvo_sel.power_buff += amount
            elif target in ('all_allies', 'all_allies_and_leader'):
                # filter_type: "all of your [Tipo] type Characters gain +N
                # power" (achado 16/07, OP12-102/ST05-001) -- sem isso o
                # buff aplicava em TODO character do campo, ignorando o
                # filtro de tipo do texto.
                from optcg_engine.rules_facade import card_matches_filter
                filter_type = step.get('filter_type', '')
                alvos = ([c for c in me.field_chars if card_matches_filter(c, filter_type)]
                         if filter_type else list(me.field_chars))
                # filter_names: "All of your [Nome1] and [Nome2] cards
                # gain +N power" -- lista de NOMES (nao tipo), achado
                # 19/07, ST30-001, unica carta no banco com essa forma
                # exata (o buff caia no fallback errado target=self).
                filter_names_all = step.get('filter_names') or []
                if filter_names_all:
                    alvos = [c for c in alvos
                             if any(n in c.name.lower() for n in filter_names_all)]
                cost_lte = step.get('cost_lte')
                if cost_lte is not None:
                    alvos = [c for c in alvos if c.cost <= cost_lte]
                cost_gte = step.get('cost_gte')
                if cost_gte is not None:
                    alvos = [c for c in alvos if c.cost >= cost_gte]
                filter_color = step.get('filter_color', '')
                if filter_color:
                    alvos = [c for c in alvos if filter_color.lower() in c.color.lower()]
                # "All of your Characters with N base power or less gain
                # +M power" -- filtro de POWER na aura em massa (achado
                # 19/07, P-027 General Franky, unica carta no banco com
                # essa forma exata: buff aplicava em TODOS os aliados,
                # ignorando o teto de power).
                power_lte_all = step.get('power_lte')
                if power_lte_all is not None:
                    alvos = [c for c in alvos if c.power <= power_lte_all]
                if step.get('exclude_self'):
                    alvos = [c for c in alvos if c is not card]
                for c in alvos:
                    c.power_buff += amount
                if target == 'all_allies_and_leader':
                    me.leader.power_buff += amount
            elif target == 'select_filtered':
                # "Select up to N of your [Tipo] Leader/Character cards and
                # that card gains +X power" (OP07-057, EB02-021) -- alvo NAO
                # e a propria carta do efeito, e sim escolhido por filtro de
                # tipo/categoria entre Leader+Characters. Guarda em
                # _last_selected para um step POSTERIOR no mesmo bloco poder
                # referenciar "the selected card" (lock_self_character_refresh
                # / select_grant_unblockable_turn com target='selected').
                from optcg_engine.rules_facade import (
                    card_matches_filter,
                    choose_highest_board_value,
                )
                filter_type = step.get('filter_type', '')
                candidatos = [c for c in me.field_chars + [me.leader]
                              if card_matches_filter(c, filter_type)]
                # "other than [Nome]" (achado 17/07, EB02-002 Sabo) --
                # exclusao de nome, mesma convencao ja usada em
                # own_character/all_allies.
                exclude_sel = (step.get('exclude') or '').lower()
                if exclude_sel:
                    candidatos = [c for c in candidatos if exclude_sel not in c.name.lower()]
                if candidatos:
                    alvo = choose_highest_board_value(candidatos)
                    alvo.power_buff += amount
                    self._last_selected = alvo
                    return f'{alvo.name[:18]} selecionado, +{amount} power'
                return ''
            elif target == 'own_character':
                # "Up to N of your Characters [with X power or less] [other
                # than [Nome]] gains +Y power" -- selecao entre os PROPRIOS
                # characters SEM filtro de tipo (distinto de
                # 'select_filtered'). Achado 28/06/2026: este target ja era
                # gerado pelo parser (15 cartas reais) mas nunca era
                # consumido aqui -- caia no fallback abaixo sem aplicar
                # nada (no-op silencioso).
                from optcg_engine.rules_facade import (
                    eligible_cards,
                    choose_highest_board_value,
                )
                candidatos = eligible_cards(
                    me.field_chars,
                    power_lte=step.get('power_lte'),
                    cost_lte=step.get('cost_lte'),
                    cost_gte=step.get('cost_gte'),
                    cost_eq=step.get('cost_eq'),
                    color=step.get('filter_color', ''),
                    exclude_name=step.get('exclude', ''),
                )
                type_or_trigger = step.get('filter_type_or_has_trigger')
                if type_or_trigger:
                    wanted = _norm_type_text(type_or_trigger)
                    candidatos = [c for c in candidatos
                                  if wanted in _norm_type_text(c.sub_types)
                                  or c.has_trigger]
                # filter_no_effect: "with no base effect" (achado 17/07,
                # EB03-009 Makino) -- mesma convencao ja usada em
                # gain_life(source='trash')/play_from_deck/debuff_cost.
                if step.get('filter_no_effect'):
                    candidatos = [c for c in candidatos if not get_card_effects(c.code)]
                # "Up to N of your Characters gain +X power" -- N>1
                # (achado 16/07, OP08-018): antes escolhia SEMPRE so 1,
                # mesmo com N=3 no texto.
                count_own = step.get('count', 1)
                alvos = []
                for _ in range(count_own):
                    if not candidatos:
                        break
                    alvo = choose_highest_board_value(candidatos)
                    remove_by_identity(candidatos, alvo)
                    alvo.power_buff += amount
                    alvos.append(alvo.name[:15])
                return f'+{amount} power em: {", ".join(alvos)}' if alvos else ''
            return f'+{amount} power em {target}'

        if action == 'debuff_power':
            # Espelha buff_power, mas do lado do oponente -- achado 30/06/2026:
            # a action ja era reconhecida em viabilidade (_step_is_viable) e em
            # heuristicas de score, mas nunca tinha handler de execucao aqui,
            # virando no-op silencioso em 142 steps reais no banco (on_play,
            # when_attacking, main, activate_main, counter, trigger, etc).
            # O parser (gerar_effects_db.py) nunca emite filtro/count pra estes
            # alvos -- sempre 1 alvo escolhido pela IA (o mais valioso do
            # oponente), exceto 'all_opp_characters' que afeta o campo inteiro.
            from optcg_engine.rules_facade import choose_highest_board_value

            amount = step.get('amount', 0)
            target = step.get('target', 'opp_character')

            if target == 'opp_leader':
                opp.leader.power_buff -= amount
                return f'Leader do oponente -{amount} power'
            if target == 'all_opp_characters':
                if not opp.field_chars:
                    return ''
                if step.get('per_don_attached'):
                    # "-N power for every DON!! card given to that
                    # Character" (achado 15/07, OP15-008 Krieg): escala
                    # POR ALVO, multiplicando pelo don_attached de CADA
                    # character, nao um -N fixo pra todos.
                    afetados = []
                    for c in opp.field_chars:
                        n_don = getattr(c, 'don_attached', 0)
                        if n_don <= 0:
                            continue
                        c.power_buff -= amount * n_don
                        afetados.append(f'{c.name[:12]}(-{amount * n_don})')
                    return f'debuff por DON anexado: {", ".join(afetados)}' if afetados else ''
                for c in opp.field_chars:
                    c.power_buff -= amount
                return f'-{amount} power em todos os Characters do oponente'
            if target == 'opp_leader_or_character':
                # duration='this_turn': só tem efeito em algo que ainda pode
                # agir neste turno -- achado em partida real 07/07: Van Augur
                # (on-KO, opp_turn_only) debuffou -3000 no St. Marcus Mars
                # bem depois dele já ter atacado e resolvido o combate (já
                # restado) -- board_value puro escolhia o "maior" personagem
                # sem checar se ele ainda ia agir, jogando o debuff fora.
                # Prioriza ativo (char não-restado ou líder não-restado);
                # só cai pra qualquer um se não sobrar nenhuma opção ativa
                # (debuff sem efeito nenhum é melhor que travar a execução).
                ativos = [c for c in opp.field_chars if not c.rested]
                if not getattr(opp.leader, 'rested', False):
                    ativos.append(opp.leader)
                candidatos = list(ativos or (list(opp.field_chars) + [opp.leader]))
                # "up to a total of N" com N>1 (achado 17/07, EB01-053/
                # OP02-089) -- mesmo padrao ja usado por opp_character
                # (achado 15/07): repete a escolha do melhor alvo restante
                # ate N ou os candidatos acabarem.
                count = step.get('count', 1)
                alvos = []
                for _ in range(min(count, len(candidatos))):
                    alvo = choose_highest_board_value(candidatos)
                    alvo.power_buff -= amount
                    remove_by_identity(candidatos, alvo)
                    alvos.append(alvo.name[:15])
                return f'-{amount} power em: {", ".join(alvos)}' if alvos else ''
            if target == 'opp_character':
                if not opp.field_chars:
                    return ''
                ativos = [c for c in opp.field_chars if not c.rested]
                candidatos = list(ativos or opp.field_chars)
                # "up to N" com N>1 (achado 15/07, ex: OP01-022/OP11-020,
                # 13 cartas reais): antes so debuffava 1 alvo sempre, mesmo
                # quando o texto pedia 2. count>1 agora repete a escolha do
                # melhor alvo restante ate N ou os candidatos acabarem.
                count = step.get('count', 1)
                alvos = []
                for _ in range(min(count, len(candidatos))):
                    alvo = choose_highest_board_value(candidatos)
                    alvo.power_buff -= amount
                    remove_by_identity(candidatos, alvo)
                    alvos.append(alvo.name[:15])
                return f'-{amount} power em: {", ".join(alvos)}' if alvos else ''
            return ''

        if action == 'negate_effect':
            # "Negate the effect of up to N of your opponent's Leader/
            # Character(s)" (OP09-093, OP09-097, OP09-098, OP16-115, etc):
            # marca effects_negated_until no(s) alvo(s) -- checado no topo
            # de execute() (bloqueia qualquer trigger FUTURO da carta
            # enquanto ativo). Achado real 09/07: a action ja aparecia em 4
            # cartas parseadas mas nunca tinha handler de execucao (virava
            # no-op silencioso), mesmo padrao do achado do debuff_power
            # (30/06) documentado acima.
            from optcg_engine.rules_facade import choose_highest_board_value

            target = step.get('target', 'opp_character')
            DUR_MAP = {
                'until_opp_turn_end': 'opp_turn_end',
                'until_opp_end_phase': 'opp_end_phase',
                'until_my_next_turn_start': 'my_next_turn_start',
            }
            dur = DUR_MAP.get(step.get('duration', 'this_turn'), 'opp_turn_end')
            cost_lte = self._resolve_cost_lte(step, default=None)

            def _negar_character():
                candidatos = eligible_cards(opp.field_chars, cost_lte=cost_lte)
                if not candidatos:
                    return None
                alvo = choose_highest_board_value(candidatos)
                alvo.effects_negated_until = dur
                return alvo

            if target == 'opp_leader':
                opp.leader.effects_negated_until = dur
                return f'negou o efeito do lider {opp.leader.name[:18]}'
            if target == 'opp_leader_or_character':
                # escolhe o mais ameacador entre lider e o melhor character
                # (mesma ideia do debuff_power opp_leader_or_character:
                # so vale negar quem ainda vai agir/importar)
                melhor_char = choose_highest_board_value(opp.field_chars) if opp.field_chars else None
                if melhor_char is None or opp.leader.board_value() >= melhor_char.board_value():
                    opp.leader.effects_negated_until = dur
                    return f'negou o efeito do lider {opp.leader.name[:18]}'
                melhor_char.effects_negated_until = dur
                return f'negou o efeito de {melhor_char.name[:18]}'
            alvo = _negar_character()
            if alvo is not None:
                # Grava pra um step POSTERIOR no mesmo bloco poder alvejar
                # "that Character" (ex: OP09-098 Black Hole, "negate the
                # effect... Then, if that Character has a cost of 4 or
                # less, K.O. it" -- achado 15/07). Mesma memoria ja usada
                # por play_from_deck/buff_power target='selected'.
                self._last_selected = alvo
            return f'negou o efeito de {alvo.name[:18]}' if alvo else ''

        if action == 'buff_power_per_count':
            source = step.get('source', 'trash')
            count_per = max(1, int(step.get('count_per', 1) or 1))
            amount_per = int(step.get('amount_per', 1000) or 0)
            target = step.get('target', 'self')

            if source == 'events_in_trash':
                n = sum(1 for c in me.trash if c.card_type == 'EVENT')
            elif source == 'trash':
                n = len(me.trash)
            elif source == 'rested_don':
                n = me.don_rested
            elif source == 'hand':
                n = len(me.hand)
            elif source == 'unique_character_names':
                n = len({c.name for c in me.field_chars})
            elif source == 'own_characters':
                n = len(me.field_chars)
            elif source == 'placed_bottom_deck_this_effect':
                n = getattr(self, '_last_moved_count', 0)
            elif source == 'trashed_hand_this_effect':
                n = getattr(self, '_last_cost_trash_any_count', 0)
            elif source == 'bounced_own_this_effect':
                n = getattr(self, '_last_cost_bounce_any_count', 0)
            elif source == 'rested_don_this_effect':
                # Achado 29/07, OP13-001 Luffy: "for every DON!! card rested
                # this way" -- contagem do custo VARIAVEL rest_any_don pago
                # NESTE efeito, mesma familia de trashed_hand_this_effect/
                # bounced_own_this_effect (nao o total de DON rested no
                # banco -- isso ja e o source='rested_don').
                n = getattr(self, '_last_cost_rest_any_don_count', 0)
            elif source == 'life_top_revealed_cost':
                # "reveal up to 1 card from the top of your Life cards.
                # This Character gains +N power per M cost on the
                # revealed card" -- PEEK (nao remove/nao move), so olha o
                # custo da carta (achado 19/07, OP15-119). Zero se a Life
                # estiver vazia.
                n = me.life[-1].cost if me.life else 0
                if me.life:  # memoria: topo da propria Life conhecido
                    me.revealed_life.add(id(me.life[-1]))
            else:
                n = 0

            amount = (n // count_per) * amount_per
            if amount <= 0:
                return ''

            if target == 'self':
                card.power_buff += amount
            elif target == 'leader':
                me.leader.power_buff += amount
            elif target == 'leader_or_character':
                # filter_type (achado 29/07, OP13-001 Luffy: "this Leader or
                # up to 1 of your [Tipo] type Characters") filtra so o lado
                # CHARACTER -- o Leader e sempre elegivel, sem filtro de
                # tipo (o texto nunca restringe o Leader por tipo aqui).
                filter_type = step.get('filter_type', '')
                if filter_type:
                    from optcg_engine.rules_facade import card_matches_filter
                    candidatos_char = [c for c in me.field_chars
                                       if card_matches_filter(c, filter_type)]
                else:
                    candidatos_char = list(me.field_chars)
                pool = candidatos_char + [me.leader]
                best = max(pool, key=lambda c: c.effective_power(True))
                best.power_buff += amount
            elif target in ('all_allies', 'all_allies_and_leader'):
                for c in me.field_chars:
                    c.power_buff += amount
                if target == 'all_allies_and_leader':
                    me.leader.power_buff += amount
            return f'+{amount} power em {target} ({n}/{count_per} {source})'

        if action == 'buff_cost_per_count':
            # "gains [Blocker] and +N cost for every M cards in your
            # trash" (achado 16/07, ST27-004) -- mesma semantica de
            # buff_power_per_count, so que muta cost_buff em vez de
            # power_buff. amount_per pode ser NEGATIVO (achado 16/07,
            # EB04-048: "+1000 power and -2 cost for every 5 cards in
            # your trash" -- reducao de custo, nao aumento).
            source = step.get('source', 'trash')
            count_per = max(1, int(step.get('count_per', 1) or 1))
            amount_per = int(step.get('amount_per', 1) or 0)
            target = step.get('target', 'self')

            n = len(me.trash) if source == 'trash' else 0
            amount = (n // count_per) * amount_per
            if amount == 0:
                return ''

            if target == 'self':
                card.cost_buff += amount
            else:
                for c in me.field_chars:
                    c.cost_buff += amount
            sinal = '+' if amount >= 0 else ''
            return f'{sinal}{amount} cost em {target} ({n}/{count_per} {source})'

        # ── Cost buff/debuff (buff_cost / debuff_cost) ──────────────────────────
        # NOTA DE LIMITACAO: assim como buff_power, o sistema geral de turnos
        # ainda nao distingue 'until_opp_turn_end' de 'this_turn' -- ambos sao
        # resetados no mesmo ciclo (apply_your_turn_buffs/reset_your_turn_buffs).
        # duration='permanent' (ex: condicionado a leader_type, sem prazo) usa
        # cost_buff_permanent, que nunca e resetado por esses dois pontos.
        if action in ('buff_cost', 'debuff_cost'):
            from optcg_engine.rules_facade import eligible_cards

            amount = step.get('amount', 0)
            if action == 'debuff_cost':
                amount = -amount
            target = step.get('target', 'self')
            duration = step.get('duration', 'this_turn')
            count = step.get('count', 1)
            filter_name = step.get('filter_name', '').lower()
            cost_gte = step.get('cost_gte')

            if target == 'own_play_hand':
                if duration == 'next_play_only':
                    me.pending_play_cost_reductions.append({
                        k: step[k] for k in
                        ('amount', 'filter_type', 'filter_name', 'cost_gte')
                        if k in step
                    })
                    return f'proxima carta elegivel custa -{amount}'
                # Auras de Stage sao lidas diretamente por
                # effective_hand_play_cost; nao mutam cartas na mao.
                return f'aura de custo -{amount} para cartas elegiveis'

            campo_alvo = me if target in ('self', 'own_character') else opp
            if target == 'self':
                candidatos = [card]
            else:
                candidatos = eligible_cards(
                    campo_alvo.field_chars,
                    cost_lte=step.get('cost_lte'),
                    power_lte=step.get('power_lte'),
                    filter_text=step.get('filter_type', ''),
                    color=step.get('color', ''),
                )
                if filter_name:
                    # Filtro por NOME PROPRIO (ex: Shinobu OP16-087, "up to 1
                    # of your [Kouzuki Momonosuke] gains +20 cost") -- DISTINTO
                    # de filter_type: aqui o alvo e 1 personagem especifico
                    # por nome, nao uma familia/tipo inteira. Achado 27/06:
                    # o parser confundia com filter_type antes da correcao.
                    candidatos = [c for c in candidatos if filter_name in c.name.lower()]
                if cost_gte is not None:
                    candidatos = [c for c in candidatos if c.cost >= cost_gte]
                # filter_no_effect: Characters sem efeito parseado no banco
                # ("with no base effect", OP03-091 Helmeppo). BUG achado
                # 17/07: get_card_effects() ja retorna o dict de efeitos
                # DESEMPACOTADO (chaves sao nomes de trigger, ex: 'on_play'),
                # entao chamar .get('effects') NELE de novo sempre retornava
                # None -- o filtro nunca filtrava nada (tratava QUALQUER
                # carta como "sem efeito base"). Mesmo bug replicado em
                # play_from_deck (ver abaixo).
                if step.get('filter_no_effect'):
                    candidatos = [c for c in candidatos
                                  if not get_card_effects(c.code)]

            to_value = step.get('to_value')  # "set cost to N" (OP03-091)
            afetados = []
            for c in candidatos[:count]:
                if to_value is not None:
                    real_amount = -(c.effective_cost() - to_value)
                else:
                    real_amount = amount
                if duration == 'permanent':
                    c.cost_buff_permanent += real_amount
                else:
                    c.cost_buff += real_amount
                afetados.append(c.name[:15])
            sinal = '+' if amount >= 0 else ''
            return f'{sinal}{amount} cost em {", ".join(afetados)}' if afetados else ''

        # ── Give DON ──────────────────────────────────────────────────────────
        if action == 'give_don':
            count = step.get('count', 1)
            rested = step.get('rested', False)
            # Dá DON ao personagem mais forte ativo
            targets = [c for c in me.field_chars if not c.rested] + [me.leader]
            # Filtro de NOME -- "give up to N DON!! cards to 1 of your
            # [Nome] cards" (achado 19/07, OP13-006/OP13-021/ST29-012/
            # P-096, 4 cartas): sem isso, o DON podia ir pra QUALQUER
            # character proprio, nao so o nomeado.
            target_name = step.get('target_name', '').lower()
            if target_name:
                targets = [c for c in targets if target_name in c.name.lower()]
            transferido = 0
            if targets:
                # Entre quem pode de fato ATACAR AINDA NESTE TURNO (lider
                # ainda ativo, ou Character apto via character_can_attack_
                # now -- cobre Rush), o DON!! muda o resultado do combate
                # de hoje: maximiza poder normalmente. Se NINGUEM pode
                # atacar mais este turno, o DON e so investimento
                # PERMANENTE -- prefere o LIDER (ataca praticamente todo
                # turno, nunca sai de campo) a um Character fragil que
                # pode ser K.O.'d e levar o DON junto. Sem isto,
                # max(effective_power) comparava poder bruto sem saber se
                # o alvo sequer podia usar o DON hoje -- achado real 02/08
                # (usuario, log Portgas.D.Ace-R x Portgas.D.Ace-R
                # 2026-08-02T16.38.43): Izo (on_play give_don rested=true)
                # deu o proprio DON pra si mesmo (recem-jogado, sem Rush,
                # nao podia atacar nem hoje) so por ter mais poder impresso
                # que o lider ja restado, quando o lider era o destino de
                # valor permanente mais seguro.
                podem_atacar_agora = [
                    c for c in targets
                    if (c is me.leader and not c.rested)
                    or (c is not me.leader and character_can_attack_now(c, me, opp))]
                pool = podem_atacar_agora or ([me.leader] if me.leader in targets else targets)
                best = max(pool, key=lambda c: c.effective_power(True))
                # "up to N" e um TETO que o jogador escolhe (0..N), nao uma
                # ordem fixa de sempre dar N -- achado 15/07 (usuario): o
                # motor sempre tentava dar o maximo do texto, mesmo quando
                # o personagem ja teria poder suficiente pra passar pelo
                # lider do oponente sem DON nenhum, desperdicando DON que
                # ficaria melhor reservado pra defesa. So se aplica ao
                # alvo PROPRIO (give_don) -- give_don_opp tem objetivo
                # oposto (sobrecarregar o oponente), la o maximo continua
                # sendo a jogada certa. Formula = mesmo deficit BASE de
                # don_needed_for_attack (secao 1, obrigatoria), sem a
                # margem de counter (exige contexto de ataque declarado,
                # que ainda nao existe neste ponto do efeito -- On Play/
                # Activate Main roda antes da fase de ataque).
                deficit = opp.leader.power - attack_time_power(best, opp)
                necessario = (deficit + 999) // 1000 if deficit > 0 else 0
                count = min(count, necessario)
                # Debita do banco de DON real (don_rested + don_available),
                # nunca de uma fonte gratuita externa -- ambos os tipos vêm
                # do mesmo banco do jogador. Achado 15/07 via
                # audit_parser_coverage.py (ST01-011 Brook): o comentario
                # ja dizia "a IA nao inventa DON", mas o codigo anexava
                # `count` cheio no character ANTES de saber quanto o banco
                # realmente tinha pra debitar -- se o banco tivesse MENOS
                # que `count`, o personagem recebia o valor cheio mesmo
                # assim (DON criado do nada, banco e campo dessincronizam).
                # Fix: anexa exatamente o que foi de fato debitado do banco.
                if rested:
                    # "give up to N RESTED DON" -- exige especificamente DON
                    # rested do banco. Se não houver o suficiente, usa o que
                    # tiver (parcial) -- a IA não inventa DON.
                    do_rested = min(count, me.don_rested)
                    me.don_rested -= do_rested
                    transferido = do_rested
                else:
                    # "give up to N DON" (sem qualificador) -- a IA escolhe.
                    # Prioriza DON rested primeiro (preserva don_available
                    # ativo para outras jogadas no mesmo turno); se não
                    # houver rested suficiente, completa com don_available.
                    do_rested = min(count, me.don_rested)
                    me.don_rested -= do_rested
                    restante = count - do_rested
                    do_available = min(restante, me.don_available) if restante > 0 else 0
                    me.don_available -= do_available
                    transferido = do_rested + do_available
                best.don_attached += transferido
                if transferido:
                    self._dispatch_don_given(best)
            return f'+{transferido} DON'

        # ── Give DON ao oponente (controle/setup) ───────────────────────────────
        # Mecanica distinta de give_don: o DON sai do BANCO DO OPONENTE (nao do
        # meu), e e anexado a um Character do OPONENTE. Geralmente usado para
        # travar o refresh dele depois (ex: combinado com lock_opp_don /
        # lock_opp_character_refresh), nao para dar vantagem ao oponente.
        if action == 'give_don_opp':
            count = step.get('count', 1)
            rested = step.get('rested', False)

            targets_opp = [c for c in opp.field_chars] + [opp.leader]
            transferido = 0
            if targets_opp:
                best = max(targets_opp, key=lambda c: c.effective_power(True))
                # Mesmo fix do give_don (15/07, achado via ST01-011 Brook):
                # anexa so o que foi de fato debitado do banco do oponente,
                # nunca o `count` cheio se o banco tiver menos que isso.
                if rested:
                    do_rested = min(count, opp.don_rested)
                    opp.don_rested -= do_rested
                    transferido = do_rested
                else:
                    # sem qualificador / "from cost area" -- usa o banco
                    # ativo do oponente primeiro (e o DON que ele "gastou"
                    # no turno, fica no cost area), completando com rested
                    # se nao houver ativo suficiente.
                    do_available = min(count, opp.don_available)
                    opp.don_available -= do_available
                    restante = count - do_available
                    do_rested = min(restante, opp.don_rested) if restante > 0 else 0
                    opp.don_rested -= do_rested
                    transferido = do_available + do_rested
                best.don_attached += transferido
            return f'deu {transferido} DON ao character do oponente'

        # ── Play from trash ───────────────────────────────────────────────────
        if action == 'play_from_trash':
            from optcg_engine.rules_facade import eligible_cards

            filter_type = step.get('filter_type', '').lower()
            filter_name = step.get('filter_name', '').lower()
            cost_lte = self._resolve_cost_lte(step, default=None)
            cost_eq = step.get('cost_eq')
            power_eq = step.get('power_eq')
            power_lte = step.get('power_lte')
            power_gte = step.get('power_gte')
            count = step.get('count', 1)
            enters_rested = step.get('rested', False)
            distinct_names = step.get('distinct_names', False)

            # filter_self: recupera a SI MESMO do trash (ex: substituicao de
            # remocao por auto-K.O. seguida de replay). Nao usa o pool geral
            # de candidatos, e sim a propria carta que acabou de ir ao trash.
            if step.get('filter_self'):
                self_card = next((c for c in me.trash if c.code == card.code), None)
                if self_card:
                    remove_by_identity(me.trash, self_card)
                    self_card.rested = enters_rested
                    if self_card.card_type == 'STAGE':
                        if me.field_stage:
                            me.trash.append(me.field_stage)
                        me.field_stage = self_card
                    else:
                        me.field_chars.append(self_card)
                        apply_conditional_keyword_passives(me, opp)
                        self_card.just_played = not (self_card.has_rush or self_card.rush_this_turn or self_card.is_rush_character())
                        self_card.rush_character_only_this_turn = self_card.is_rush_character() and not self_card.is_rush()
                    return f'jogou do trash (self): {self_card.name[:15]}'
                return ''

            candidates = eligible_cards(
                me.trash,
                cost_lte=cost_lte,
                cost_eq=cost_eq,
                power_eq=power_eq,
                power_lte=power_lte,
                power_gte=power_gte,
                has_trigger=step.get('has_trigger', False),
                filter_text=filter_type,
                name_or_code=filter_name,
                exclude_name=step.get('exclude', ''),
            )
            if step.get('same_name_as_trashed'):
                nomes = set(getattr(self, '_last_trashed_names', []) or [])
                candidates = [c for c in candidates if c.name in nomes]

            played = []
            played_names_lower = set()
            for _ in range(min(count, len(candidates))):
                pool = candidates
                if distinct_names:
                    pool = [c for c in candidates if c.name.lower() not in played_names_lower]
                if not pool:
                    break
                if any(c.card_type == 'STAGE' for c in pool):
                    best = max((c for c in pool if c.card_type == 'STAGE'), key=lambda x: x.cost)
                else:
                    best = max(pool, key=lambda x: x.board_value())

                remove_by_identity(me.trash, best)
                best.rested = enters_rested
                if best.card_type == 'STAGE':
                    if me.field_stage:
                        me.trash.append(me.field_stage)
                    me.field_stage = best
                else:
                    if len(me.field_chars) >= 5:
                        worst = min(me.field_chars, key=lambda x: x.board_value())
                        remove_character_from_field(me, worst, 'trash')
                    me.field_chars.append(best)
                    apply_conditional_keyword_passives(me, opp)
                    best.just_played = not (best.has_rush or best.rush_this_turn or best.is_rush_character())
                    best.rush_character_only_this_turn = best.is_rush_character() and not best.is_rush()

                played.append(best.name[:15])
                played_names_lower.add(best.name.lower())
                remove_by_identity(candidates, best)

            return f'jogou do trash: {", ".join(played)}' if played else ''

        # ── Play from deck ────────────────────────────────────────────────────
        if action == 'play_from_deck':
            from optcg_engine.rules_facade import eligible_cards

            filter_type = step.get('filter_type', '').lower()
            cost_lte = self._resolve_cost_lte(step, default=99)
            color = step.get('color', '')
            count = step.get('count', 1)

            # Se precedido de 'look_top_deck' (padrao "look at N cards from
            # the top of your deck; play up to 1 [filtro]"), restringe a
            # busca as N cartas do topo, igual a add_to_hand -- sem isto, a
            # IA "veria" o deck inteiro para escolher a melhor carta, o que
            # nao e a regra real (so as N cartas reveladas pelo look estao
            # disponiveis) e tambem nao embaralharia o deck no final (regra
            # de "look E play" deixa o resto no topo/fundo conforme o texto,
            # nao embaralha -- distinto do "play a card from anywhere in
            # your deck", que de fato revela o deck inteiro e embaralha).
            effects = get_card_effects(card.code)
            look_count = None
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count')
                        break
                if look_count:
                    break

            if look_count:
                look = min(look_count, len(me.deck))
                pool = me.deck[-look:]
            else:
                pool = me.deck

            candidates = eligible_cards(
                list(pool),
                cost_lte=cost_lte,
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                filter_text=filter_type,
                name_or_code=step.get('filter_name', ''),
                color=color,
            )

            played = []
            for _ in range(min(count, len(candidates))):
                best = max(candidates, key=lambda x: x.board_value())
                remove_by_identity(candidates, best)
                # pop_by_identity, nao remove_by_identity -- ver docstring
                # (respeita deepcopy-on-pop de _SimDeck durante simulacao
                # do Turn Planner; achado 03/08, causa raiz do bug de
                # conservacao de DON que persistia desde os blocos 374/377/
                # 410/420/422/423 -- Character jogado do deck via ESTA
                # acao entrava em campo com a MESMA referencia do deck
                # real, vazando DON!! anexado numa linha simulada/nunca
                # jogada de verdade pro estado real). Remove de `candidates`
                # ANTES (por identidade do objeto ORIGINAL) -- depois do
                # pop, `best` vira outra instancia (a copia), que nao
                # bateria mais no `candidates` original.
                best = pop_by_identity(me.deck, best)
                if len(me.field_chars) >= 5:
                    worst = min(me.field_chars, key=lambda x: x.board_value())
                    remove_character_from_field(me, worst, 'trash')
                me.field_chars.append(best)
                apply_conditional_keyword_passives(me, opp)
                best.just_played = not (best.has_rush or best.rush_this_turn or best.is_rush_character())
                best.rush_character_only_this_turn = best.is_rush_character() and not best.is_rush()
                played.append(best.name[:15])
                # Grava pra um step POSTERIOR no mesmo bloco poder alvejar
                # "that Character" (ex: OP12-058 Whitebeard, "gains [Rush]"
                # apos jogar do deck) -- mesma memoria ja usada por
                # buff_power/lock_self_character_refresh target='selected'.
                self._last_selected = best

            if not look_count:
                # so embaralha quando a busca expos o deck inteiro -- o
                # padrao "look at N; play" deixa o resto das N cartas vistas
                # para o step seguinte (trash_rest/deck_bottom_rest/etc)
                # tratar, sem tocar no resto do deck.
                random.shuffle(me.deck)
            return f'jogou do deck: {", ".join(played)}' if played else ''

        # ── Trash from hand ───────────────────────────────────────────────────
        if action == 'trash_from_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(me.hand))):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    remove_by_identity(me.hand, worst)
                    me.trash.append(worst)
                    trashed.append(worst.name[:12])
            # Guarda o total REAL trashado pro step seguinte no MESMO bloco
            # ler (ex: trash_from_deck_top com count_from_last_hand_trash,
            # OP09-059 -- "trash the same number ... as you did from your
            # hand"), mesmo padrao ja usado por _last_moved_count em
            # place_*_bottom_deck.
            self._last_moved_count = len(trashed)
            if trashed:
                self._dispatch_hand_card_trashed(me, opp)
            return f'descartou da mão: {", ".join(trashed)}' if trashed else ''

        # ── Trash from hand FORCADO no oponente (disrupcao de mao) ──────────────
        # Distinto de trash_from_hand: alvo e a mao do OPONENTE, nao a minha.
        # E um efeito DETERMINISTICO (sempre acontece, sem "se o oponente
        # quiser") -- a unica decisao real e QUAL carta ele descarta, e isso
        # reaproveita a mesma heuristica de _choose_to_trash (menor valor de
        # board) aplicada na mao dele. Simplificacao assumida: nao modela
        # blefe/retencao estrategica do oponente, so "descarta o que tem
        # menos valor para o lado que esta descartando" -- aproximacao
        # razoavel e nao tendenciosa para nenhum dos lados, mas e uma
        # simplificacao real, nao a decisao otima do oponente.
        if action == 'opp_trash_from_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(opp.hand))):
                # "your opponent trashes" = o dono da mao escolhe e
                # preserva suas melhores cartas. Ja "trash ... from your
                # opponent's hand" = controlador do efeito escolhe cartas
                # face-down (Q&A OP03-078), logo a escolha e cega/aleatoria.
                chosen = (random.choice(opp.hand)
                          if step.get('chosen_by') == 'effect_owner_blind'
                          else self._choose_to_trash(opp.hand))
                if chosen:
                    remove_by_identity(opp.hand, chosen)
                    opp.trash.append(chosen)
                    trashed.append(chosen.name[:12])
            if trashed:
                self._dispatch_hand_card_trashed(opp, me)
            return f'oponente descartou: {", ".join(trashed)}' if trashed else ''

        # ── Mesma familia: forca o OPONENTE a mover 1 dos PROPRIOS
        # characters dele (ele escolheria; aproximamos pelo pior por
        # board_value, mesmo criterio de toda escolha "sacrifique o pior"
        # já usada no engine). DISTINTO de bounce/
        # place_opp_character_bottom_deck (onde EU escolho o MELHOR do
        # oponente pra remover). Achado por foto real 27/06 (Tsuru
        # OP06-051, Luffy P-055).
        if action == 'opp_choose_trash_our_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(me.hand))):
                chosen = max(me.hand, key=lambda c: c.board_value())
                remove_by_identity(me.hand, chosen)
                me.trash.append(chosen)
                trashed.append(chosen.name[:12])
            if trashed:
                self._dispatch_hand_card_trashed(me, opp)
            return f'oponente escolheu descartar: {", ".join(trashed)}' if trashed else ''

        if action == 'opp_bounce_own_character':
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte')
            active_only = step.get('active_only', False)
            rested_only = step.get('rested_only', False)
            candidates = [
                c for c in opp.field_chars
                if (cost_lte is None or c.cost <= cost_lte)
                and (not active_only or not c.rested)
                and (not rested_only or c.rested)
            ]
            bounced = []
            for _ in range(min(count, len(candidates))):
                worst = min(candidates, key=lambda c: c.board_value())
                remove_character_from_field(opp, worst, 'hand')
                remove_by_identity(candidates, worst)
                bounced.append(worst.name[:12])
            return f'oponente devolveu pra mão: {", ".join(bounced)}' if bounced else ''

        if action == 'opp_place_own_character_bottom_deck':
            count = step.get('count', 1)
            placed = []
            for _ in range(min(count, len(opp.field_chars))):
                worst = min(opp.field_chars, key=lambda c: c.board_value())
                remove_character_from_field(opp, worst, 'deck_bottom')
                placed.append(worst.name[:12])
            return f'oponente colocou no fundo do deck: {", ".join(placed)}' if placed else ''

        # ── Mesma familia (forca o OPONENTE), mas a fonte e a MAO dele, nao
        # o campo -- destino e o FUNDO DO PROPRIO DECK do oponente (NUNCA
        # trash, distinto de opp_trash_from_hand). Reusa _choose_to_trash
        # (mesma heuristica de "descarta o pior" ja usada pra mao do
        # oponente) so pra escolher QUAL carta, ja que o destino e
        # diferente. Achado 02/07/2026 (EB03-026, EB04-022, EB04-025,
        # OP06-044, OP07-047, OP08-046, OP15-048, P-048, OP16-047).
        # ── hand_to_deck: coloca N cartas da PRÓPRIA mão de volta no deck
        # ("top or bottom... in any order" -- escolha estética do jogador,
        # sem efeito mecânico relevante; modela como fundo do deck, mesma
        # convenção de opp_place_hand_bottom_deck). Achado 15/07: clausula
        # "loot" (draw N, devolve M) que seguia um 'draw' ficava ausente
        # do parseado inteira (OP07-053, OP08-050, OP11-054 Nami).
        if action == 'hand_to_deck':
            count = step.get('count', 1)
            placed = []
            for _ in range(min(count, len(me.hand))):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    remove_by_identity(me.hand, worst)
                    me.deck.insert(0, worst)
                    placed.append(worst.name[:12])
            return f'colocou da mão no deck: {", ".join(placed)}' if placed else ''

        # "...and place N cards from your hand at the TOPO of your deck"
        # (SEM "or bottom") -- DISTINTO de hand_to_deck acima: aqui o
        # texto so oferece topo (a carta reaparece na proxima compra,
        # efeito mecanico real). Topo do deck = FIM da lista (convencao
        # do projeto, ver deck.pop() em vez de pop(0)). Achado 17/07,
        # EB03-034/ST17-001.
        if action == 'hand_to_deck_top':
            count = step.get('count', 1)
            placed = []
            for _ in range(min(count, len(me.hand))):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    remove_by_identity(me.hand, worst)
                    me.deck.append(worst)
                    placed.append(worst.name[:12])
            return f'colocou da mão no TOPO do deck: {", ".join(placed)}' if placed else ''

        if action == 'opp_place_hand_bottom_deck':
            count = step.get('count', 1)
            placed = []
            for _ in range(min(count, len(opp.hand))):
                worst = self._choose_to_trash(opp.hand)
                if worst:
                    remove_by_identity(opp.hand, worst)
                    opp.deck.insert(0, worst)
                    placed.append(worst.name[:12])
            return f'oponente colocou da mão no fundo do deck: {", ".join(placed)}' if placed else ''

        # ── Mesma familia, fonte = TRASH do oponente. filter_type='event'
        # restringe a Event cards (OP11-091). Achado 02/07/2026 (OP05-079,
        # OP06-092, OP11-072, OP11-091).
        if action == 'opp_place_trash_bottom_deck':
            count = step.get('count', 1)
            filter_type = step.get('filter_type')
            candidates = list(opp.trash)
            if filter_type == 'event':
                candidates = [c for c in candidates if c.card_type.lower() == 'event']
            placed = []
            for _ in range(min(count, len(candidates))):
                worst = min(candidates, key=lambda c: c.board_value())
                remove_by_identity(opp.trash, worst)
                remove_by_identity(candidates, worst)
                opp.deck.insert(0, worst)
                placed.append(worst.name[:12])
            return f'oponente colocou do trash no fundo do deck: {", ".join(placed)}' if placed else ''

        # "Place any number of Character cards with a cost of N or more
        # from your PRÓPRIO trash at the bottom of your deck" -- CONTAGEM
        # VARIAVEL (nao um count fixo como opp_place_trash_bottom_deck
        # acima): move TODAS as Characters elegiveis (maximiza o buff
        # seguinte que escala pelo resultado real deste step, ver
        # buff_power_per_count/source=placed_bottom_deck_this_effect).
        # self._last_moved_count guarda o total pro step seguinte no MESMO
        # bloco ler (mesmo padrao de _last_selected/_last_trashed_names).
        # Achado 17/07, OP07-091 (unica carta no banco).
        if action == 'place_trash_matching_bottom_deck':
            from optcg_engine.rules_facade import eligible_cards

            candidatos = eligible_cards(
                [c for c in me.trash if c.card_type.upper() == 'CHARACTER'],
                cost_gte=step.get('cost_gte'),
            )
            placed = []
            for alvo in list(candidatos):
                remove_by_identity(me.trash, alvo)
                me.deck.insert(0, alvo)
                placed.append(alvo.name[:12])
            self._last_moved_count = len(placed)
            return f'colocou do trash no fundo do deck: {", ".join(placed)}' if placed else ''

        # ── AUTO-RESTRIÇÃO: "Then, you cannot play ... this turn" ─────────────
        # Combo de ramp (set DON active) que cobra: você perde o direito de jogar.
        # Resetado no início do próprio turno (refresh).
        if action == 'self_cant_play':
            scope = step.get('scope', 'chars')   # 'hand' | 'chars'
            if scope == 'hand':
                me.cant_play_from_hand_this_turn = True
            else:
                me.cant_play_chars_this_turn = True
                gte = step.get('cost_gte', 0)
                if gte:
                    me.cant_play_cost_gte = gte
            return 'auto-restrição: não pode jogar mais este turno'

        # ── SHUFFLE/CYCLE mão no deck (+ recompra) = redesenhar a mão ─────────
        if action == 'shuffle_hand_into_deck':
            import random as _rnd
            n = len(me.hand)
            if n == 0:
                return ''
            dest = step.get('dest', 'deck')
            # move toda a mão para o deck
            cards = list(me.hand)
            me.hand.clear()
            if dest == 'deck_bottom':
                for c in cards:
                    me.deck.insert(0, c)        # fundo = início da lista
            else:
                me.deck.extend(cards)
                _rnd.shuffle(me.deck)
            # recompra N (= nº devolvido), do topo (= pop())
            if step.get('draw_back'):
                for _ in range(n):
                    if not me.deck: break
                    me.hand.append(me.deck.pop())
            return f'redesenhou a mão ({n} cartas)'

        # Versao OPONENTE de shuffle_hand_into_deck: forca o oponente a
        # reciclar sua mao inteira no deck e recomprar N cartas (OP06-047).
        if action == 'opp_shuffle_hand_into_deck':
            import random as _rnd
            n = len(opp.hand)
            if n == 0:
                return ''
            cards = list(opp.hand)
            opp.hand.clear()
            opp.deck.extend(cards)
            _rnd.shuffle(opp.deck)
            draw_back = step.get('draw_back', 0)
            for _ in range(draw_back):
                if not opp.deck: break
                opp.hand.append(opp.deck.pop())
            return f'oponente reciclou mão ({n} cartas) e comprou {draw_back}'

        # ── DON: reativar DON rested (set as active) = ramp dentro do turno ───
        if action == 'add_don':
            count = step.get('count', 1)
            moved = min(count, me.don_deck)
            me.don_deck -= moved
            if step.get('rested'):
                me.don_rested += moved
                return f'adicionou {moved} DON restado' if moved else ''
            me.don_available += moved
            return f'adicionou {moved} DON ativo' if moved else ''

        if action == 'set_don_active':
            count = step.get('count', 1)
            moved = min(count, me.don_rested)
            me.don_rested    -= moved
            me.don_available += moved
            return f'reativou {moved} DON' if moved else ''

        # "Then, take an extra turn after this one" (achado 16/07,
        # OP05-119, unica carta no banco). So SETA a flag -- quem decide
        # de fato repetir o mesmo jogador e o loop de simulate(), lido
        # logo apos play_turn() retornar (ver docstring de GameState.
        # extra_turn_pending). Nao mexe na fase atual em andamento.
        if action == 'take_extra_turn':
            me.extra_turn_pending = True
            return 'ganhou um turno extra'

        # ── set_active: desrestar Character(s)/Leader fora do Refresh normal
        # (26 cartas, censo padrão 8, nunca implementado antes -- ex:
        # Komurasaki OP01-042, Pica OP05-032, Zoro OP06-118). DISTINTO de
        # set_don_active (DON!! cards) -- nunca confundir. Sempre exige
        # candidato JÁ RESTED (reativar algo já ativo é no-op sem sentido,
        # mesmo quando o texto não diz "rested" explicitamente).
        # Auto-restricao de alvo de ataque (OP12-020 Zoro lider, achado
        # 15/07): "cannot attack your opponent's Characters with a cost
        # of N or less during this turn" -- distinta de
        # lock_opp_character_attack (trava o OPONENTE, mecanica oposta).
        # Consumida na geracao de acoes de ataque (_generate_and_score_actions).
        if action == 'lock_self_attack_opp_chars_cost_lte':
            card.cannot_attack_opp_chars_cost_lte = step.get('cost_lte', 0)
            return f'{card.name[:18]} nao pode atacar Characters custo<={step.get("cost_lte", 0)} este turno'

        if action == 'set_active':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_board_value,
                eligible_cards,
            )

            target = step.get('target', 'self')
            if target == 'self':
                if card.rested:
                    card.rested = False
                    return f'{card.name[:18]} ficou ativo'
                return ''
            if target == 'leader':
                if not card_matches_filter(me.leader, step.get('filter_type', '')):
                    return ''
                if me.leader.rested:
                    me.leader.rested = False
                    return f'{me.leader.name[:18]} (leader) ficou ativo'
                return ''
            if target == 'own_stage':
                stage = me.field_stage
                if not stage or not stage.rested:
                    return ''
                wanted_color = step.get('color', '')
                if wanted_color and wanted_color.lower() not in stage.color.lower():
                    return ''
                stage.rested = False
                return f'{stage.name[:18]} (stage) ficou ativo'

            count = step.get('count', 1)
            candidatos = eligible_cards(
                me.field_chars,
                rested_only=True,
                filter_text=step.get('filter_type', ''),
                name_or_code=step.get('filter_name', ''),
                color=step.get('color', ''),
                attribute=step.get('attribute', ''),
                cost_lte=step.get('cost_lte'),
                cost_gte=step.get('cost_gte'),
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                power_eq=step.get('power_eq'),
            )

            ativados = []
            for _ in range(count):
                if not candidatos:
                    break
                melhor = choose_highest_board_value(candidatos)
                melhor.rested = False
                remove_by_identity(candidatos, melhor)
                ativados.append(melhor.name[:14])

            if target == 'own_character_and_leader' and me.leader.rested:
                me.leader.rested = False
                ativados.append(f'{me.leader.name[:14]} (leader)')
            elif target == 'leader_or_character' and not ativados and me.leader.rested:
                # "leader OR character" sem candidato de character valido --
                # tenta o leader como alternativa (mesmo "ou" da carta).
                me.leader.rested = False
                ativados.append(f'{me.leader.name[:14]} (leader)')

            return f'ficou(ram) ativo(s): {", ".join(ativados)}' if ativados else ''

        # ── REMOÇÃO: enviar Character do oponente ao FUNDO do deck dele ───────
        # Remoção forte (ignora On-KO; enterra no deck). Respeita imunidade a
        # removal. Distinta de bounce (mão) e KO (trash).
        if action == 'place_opp_character_bottom_deck':
            from optcg_engine.rules_facade import (
                choose_highest_board_value,
                eligible_cards,
            )
            count = step.get('count', 1)
            cands = eligible_cards(
                opp.field_chars,
                cost_lte=step.get('cost_lte'),
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                filter_text=step.get('filter_type', ''),
            )
            placed = []
            immune = []
            for _ in range(min(count, len(cands))):
                if not cands: break
                target = choose_highest_board_value(cands)
                if is_immune(target, 'removal', opp, me, source_is_opp=True):
                    immune.append(target.name[:12])
                    remove_by_identity(cands, target)
                    continue
                remove_character_from_field(opp, target, 'deck_bottom')
                self._dispatch_own_effect_removes_char('deck_bottom', 'opp')
                remove_by_identity(cands, target)
                placed.append(target.name[:14])
            out = []
            if placed: out.append(f'fundo do deck: {", ".join(placed)}')
            if immune: out.append(f'imune: {", ".join(immune)}')
            return ' | '.join(out)

        if action == 'place_all_character_bottom_deck':
            from optcg_engine.rules_facade import eligible_cards
            moved = []
            for owner in (opp, me):
                candidates = eligible_cards(owner.field_chars,
                                            cost_lte=step.get('cost_lte'))
                for target in list(candidates):
                    # Remocao simetrica; cada dono recebe a propria carta no fundo.
                    if owner is opp and is_immune(
                            target, 'removal', opp, me, source_is_opp=True):
                        continue
                    remove_character_from_field(owner, target, 'deck_bottom')
                    moved.append(target.name[:12])
            return f'todos ao fundo: {", ".join(moved)}' if moved else ''

        # Variante do PROPRIO lado (achado 16/07, OP05-119 -- unica carta
        # no banco): manda os PROPRIOS personagens (opcionalmente
        # excluindo a fonte) pro fundo do PROPRIO deck. "in any order" NAO
        # e tratado como irrelevante aqui (pedido explicito do usuario,
        # ver HANDOFF/memoria "ordem no fundo do deck") -- remove_character_
        # from_field faz deck.insert(0, ...) a cada chamada, e cada insert
        # NOVO empurra os anteriores pra indices MAIORES (mais perto do
        # topo, ja que draw_phase compra via pop() do fim da lista).
        # Processar do MAIS FORTE pro MAIS FRACO deixa o mais forte com
        # indice maior (comprado mais cedo se o deck chegar la) e o mais
        # fraco no fundo de verdade (indice 0, comprado por ultimo).
        # "your opponent plays up to N Character card(s) with a cost of M
        # or less from their hand" -- FORCA o oponente a jogar da PROPRIA
        # mao dele (achado 19/07, OP13-119). Sempre GRATIS (regra do
        # projeto: play_card vindo de efeito nunca cobra DON); escolhe o
        # de maior board_value (jogar um corpo em campo e geralmente bom
        # pro dono, mesmo forcado). Troca o mais fraco se o campo ja tiver
        # 5, mesma regra generica de _put_into_play.
        if action == 'opp_play_card':
            count_op = step.get('count', 1)
            cost_lte_op = step.get('cost_lte', 99)
            candidatos_op = [c for c in opp.hand
                             if c.card_type == 'CHARACTER' and c.cost <= cost_lte_op]
            jogados_op = []
            for _ in range(min(count_op, len(candidatos_op))):
                escolhido_op = max(candidatos_op, key=lambda c: c.board_value())
                remove_by_identity(opp.hand, escolhido_op)
                remove_by_identity(candidatos_op, escolhido_op)
                if len(opp.field_chars) >= 5:
                    pior_op = min(opp.field_chars, key=lambda c: c.board_value())
                    remove_character_from_field(opp, pior_op, 'trash')
                escolhido_op.rested = False
                opp.field_chars.append(escolhido_op)
                jogados_op.append(escolhido_op.name[:15])
            return f'oponente jogou (forcado): {", ".join(jogados_op)}' if jogados_op else ''

        if action == 'place_own_character_bottom_deck':
            # target='self': SEMPRE a propria carta do efeito (nao uma
            # selecao entre candidatos) -- "place THIS Character at the
            # bottom of the owner's deck" (achado 19/07, OP09-051).
            if step.get('target') == 'self':
                remove_character_from_field(me, card, 'deck_bottom')
                return f'fundo do proprio deck: {card.name[:14]}'
            count = step.get('count', 1)
            candidatos = [c for c in me.field_chars
                          if not (step.get('exclude_self') and c is card)]
            candidatos.sort(key=lambda c: c.board_value(), reverse=True)
            movidos = []
            for alvo in candidatos[:count]:
                remove_character_from_field(me, alvo, 'deck_bottom')
                movidos.append(alvo.name[:14])
            return f'fundo do proprio deck: {", ".join(movidos)}' if movidos else ''

        # ── REMOÇÃO: enviar Character do oponente ao FUNDO do deck dele (fim) ──
        # ── MILL: trashar do topo do PRÓPRIO deck (sem disparar trigger) ──────
        # Regra (Arthur): trash do deck = carta vai ao trash SEM ativar Trigger.
        # Topo do deck = fim da lista (= draw_phase usa pop()).
        if action == 'trash_from_deck_top':
            # count_from_last_hand_trash: mill LIGADO ao total REAL do
            # trash_from_hand anterior no mesmo bloco (OP09-059 -- "trash
            # the same number ... as you did from your hand"), nao um
            # numero fixo do texto.
            count = (getattr(self, '_last_moved_count', 0) if step.get('count_from_last_hand_trash')
                     else step.get('count', 1))
            milled = 0
            for _ in range(count):
                if not me.deck: break
                me.trash.append(me.deck.pop())
                milled += 1
            return f'mill {milled} (topo do deck -> trash)' if milled else ''

        # ── LIFE: adicionar à própria vida (unifica o antigo 'heal') ──────────
        # Convenção confirmada no engine: fim da lista = TOPO da vida
        # (combate faz opp.life.pop() = último = próxima a revelar).
        # Logo: append = topo ; insert(0) = fundo.
        if action == 'gain_life':
            count  = step.get('count', 1)
            source = step.get('source', 'deck_top')
            dest   = step.get('dest', 'life_top')
            power_eq = step.get('power_eq')

            def _put_life(c):
                face = step.get('face')
                c.life_face_up = (face == 'up')
                if dest == 'life_bottom':
                    me.life.insert(0, c)
                else:
                    me.life.append(c)   # life_top e life_top_or_bottom → topo (default)

            added = 0
            for _ in range(count):
                c = None
                if source == 'deck_top':
                    if not me.deck: break
                    c = me.deck.pop()       # topo do deck = fim da lista (= draw_phase)
                elif source == 'hand':
                    # Filtros (cost_lte/cost_eq/filter_type) -- achado
                    # 16/07 (EB03-059/EB04-060/OP09-104/OP10-103/OP10-107):
                    # antes pegava SEMPRE a 1a carta da mao (pop(0)),
                    # ignorando qualquer filtro do step por completo,
                    # mesmo quando o parser ja o extraia corretamente.
                    from optcg_engine.rules_facade import (
                        choose_highest_board_value,
                        eligible_cards,
                    )
                    candidatos_hand = eligible_cards(
                        me.hand,
                        cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'),
                        filter_text=step.get('filter_type', ''),
                    )
                    if not candidatos_hand:
                        break
                    c = choose_highest_board_value(candidatos_hand)
                    remove_by_identity(me.hand, c)
                elif source == 'trash':
                    from optcg_engine.rules_facade import (
                        choose_highest_board_value,
                        eligible_cards,
                    )
                    candidatos_trash = eligible_cards(
                        me.trash,
                        cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'),
                        filter_text=step.get('filter_type', ''),
                    )
                    if not candidatos_trash:
                        break
                    c = choose_highest_board_value(candidatos_trash)
                    remove_by_identity(me.trash, c)
                elif source == 'hand_or_trash':
                    # Fonte COMBINADA (achado 16/07, ST13-003): elegiveis
                    # de AMBAS as zonas, escolhe o melhor entre as duas.
                    from optcg_engine.rules_facade import (
                        choose_highest_board_value,
                        eligible_cards,
                    )
                    candidatos_ht = eligible_cards(
                        me.hand, cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'), filter_text=step.get('filter_type', ''),
                    ) + eligible_cards(
                        me.trash, cost_lte=step.get('cost_lte'),
                        cost_eq=step.get('cost_eq'), filter_text=step.get('filter_type', ''),
                    )
                    if not candidatos_ht:
                        break
                    c = choose_highest_board_value(candidatos_ht)
                    if not remove_by_identity(me.hand, c):
                        remove_by_identity(me.trash, c)
                elif source == 'own_field':
                    # Character do PRÓPRIO campo virando life card (ex:
                    # Kawamatsu OP06-103, "with 0 power" -> power_eq=0).
                    # Usa remove_character_from_field (nao pop(0) direto)
                    # pra devolver DON anexado -- achado 27/06, faltava
                    # nesse ponto especifico (fora do grep original).
                    # cost_gte/power_gte (achado 17/07, ST13-001: "with a
                    # cost of 3 or more and 7000 power or more") -- filtro
                    # combinado, distinto do power_eq exato de Kawamatsu.
                    cost_gte = step.get('cost_gte')
                    power_gte = step.get('power_gte')
                    candidatos = [
                        x for x in me.field_chars
                        if (power_eq is None or x.power == power_eq)
                        and (cost_gte is None or x.cost >= cost_gte)
                        and (power_gte is None or x.power >= power_gte)
                    ]
                    if not candidatos: break
                    c = min(candidatos, key=lambda x: x.board_value())
                    remove_character_from_field(me, c, dest)
                    added += 1
                    continue
                elif source == 'opp_life':
                    if not opp.life: break
                    c = opp.life.pop()
                if c is None: break
                _put_life(c)
                added += 1
            return f'+{added} vida ({source}->{dest})' if added else ''

        # Revela o TOPO da propria Life e joga exatamente aquela carta se
        # os filtros baterem. Se falhar, a carta permanece na Life. Play por
        # efeito e gratuito; on_success_steps implementa o "If you do".
        if action == 'play_from_life_top':
            if not me.life:
                return ''
            candidate = me.life[-1]
            wanted_name = (step.get('filter_name') or '').lower()
            if wanted_name and wanted_name not in candidate.name.lower():
                return ''
            wanted_type = step.get('filter_type') or ''
            if wanted_type and _norm_type_text(wanted_type) not in _norm_type_text(candidate.sub_types):
                return ''
            if step.get('cost_eq') is not None and candidate.cost != step['cost_eq']:
                return ''
            if step.get('cost_lte') is not None and candidate.cost > step['cost_lte']:
                return ''
            if candidate.card_type != 'CHARACTER':
                return ''
            me.life.pop()
            candidate.life_face_up = False
            if len(me.field_chars) >= 5:
                worst = min(me.field_chars, key=lambda x: x.board_value())
                remove_character_from_field(me, worst, 'trash')
            me.field_chars.append(candidate)
            candidate.just_played = not (
                candidate.has_rush or candidate.rush_this_turn or candidate.is_rush_character())
            candidate.rush_character_only_this_turn = (
                candidate.is_rush_character() and not candidate.is_rush())
            apply_conditional_keyword_passives(me, opp)
            self._last_selected = candidate
            nested_logs = []
            for nested in step.get('on_success_steps', []):
                nested_log = self._execute_step(nested, card)
                if nested_log:
                    nested_logs.append(nested_log)
            suffix = f' | {" | ".join(nested_logs)}' if nested_logs else ''
            return f'jogou da Life: {candidate.name[:15]}{suffix}'

        # ── LIFE: "comprar" da própria vida para a mão (Hiyori OP06-106) ──────
        if action == 'life_to_hand':
            # ST15-001 Atmos: "cannot add Life cards to your hand using your
            # own effects during this turn" -- bloqueia esta action.
            if me.cant_take_life_this_turn:
                return ''
            count = step.get('count', 1)
            src   = step.get('source', 'life_top')
            taken = 0
            for _ in range(count):
                if not me.life: break
                # topo = pop() (fim) ; fundo = pop(0). top_or_bottom default topo.
                c = me.life.pop(0) if src == 'life_bottom' else me.life.pop()
                c.life_face_up = False
                me.hand.append(c)
                taken += 1
            return f'comprou {taken} da vida -> mao' if taken else ''

        # ── Restricao: nao pode adicionar Life cards a mao neste turno ──────────
        # ST15-001 Atmos: "you cannot add Life cards to your hand using your
        # own effects during this turn." -- ativo quando a carta ataca.
        if action == 'self_cant_take_life':
            me.cant_take_life_this_turn = True
            return 'restricao: nao pode pegar da vida este turno'

        # ── LIFE: remover da vida do OPONENTE ─────────────────────────────────
        if action == 'attack_life':
            count = step.get('count', 1)
            removed = 0
            for _ in range(count):
                if not opp.life: break
                c = opp.life.pop()              # topo da vida do oponente
                c.life_face_up = False
                opp.trash.append(c)
                removed += 1
            return f'-{removed} vida do oponente' if removed else ''

        # ── DANO direto, FORA de combate (ex: Nico Robin EB03-055, Reject
        # OP06-116) -- distinto de attack_life: aqui a vida vai pra MAO e,
        # se tiver [Trigger], pode ser revelada/ativada (regra 4-6, mesmo
        # fluxo que dano de combate ao Leader ja usa). NUNCA tratar como
        # attack_life -- la a vida vai pro trash sem trigger, e e o oposto
        # do que esse efeito faz.
        if action == 'deal_damage':
            count = step.get('count', 1)
            dealt = 0
            for _ in range(count):
                if not opp.life: break
                life_card = opp.life.pop()
                life_card.life_face_up = False
                opp.hand.append(life_card)
                dealt += 1
                if life_card.has_trigger:
                    opp.triggers_activated += 1
                    ee_opp = EffectExecutor(opp, me)
                    # is_my_turn=False: quem joga a carta (opp, dona da vida)
                    # nao e quem tem o turno agora (me, quem causou o dano).
                    ee_opp.execute(life_card, 'trigger', is_my_turn=False)
            return f'-{dealt} vida do oponente (dano, com trigger)' if dealt else ''

        # ── LIFE: descartar da própria vida (custo/troca) ─────────────────────
        if action == 'trash_own_life':
            if step.get('face') == 'up':
                face_up_cards = [c for c in list(me.life) if c.life_face_up]
                for c in face_up_cards:
                    remove_by_identity(me.life, c)
                    c.life_face_up = False
                    me.trash.append(c)
                return f'trashou {len(face_up_cards)} vida(s) face-up' if face_up_cards else ''
            if step.get('until_1'):
                trashed = 0
                while len(me.life) > 1:
                    c = me.life.pop()
                    c.life_face_up = False
                    me.trash.append(c)
                    trashed += 1
                return f'trashou {trashed} da propria vida (ate 1)' if trashed else ''
            count = step.get('count', 1)
            trashed = 0
            for _ in range(count):
                if not me.life: break
                c = me.life.pop()
                c.life_face_up = False
                me.trash.append(c)
                trashed += 1
            return f'trashou {trashed} da propria vida' if trashed else ''

        # ── Add from trash ────────────────────────────────────────────────────
        # ── PLAY_CARD: jogar carta de graça (não consome DON) ─────────────────
        # Regra confirmada (Arthur): "play card from effect" entra com custo ZERO.
        # Dois grupos no banco:
        #   GRUPO 1 (source='self', sempre [Trigger]): jogar a PRÓPRIA carta que
        #     virou da vida, em vez de mandá-la para a mão. OPCIONAL — a IA decide
        #     por score se vale jogar grátis ou guardar na mão (counter/uso futuro).
        #   GRUPO 2 (cost_lte/filter_type/color): jogar OUTRA carta da mão que bate
        #     o filtro, escolhendo a de maior valor. "up to" => pode não jogar.
        if action == 'play_card':

            def _score_to_play(c):
                # score local: board_value real + bônus por efeito útil, via
                # as MESMAS flags do analysis_db, gateadas pelo MESMO
                # checador de DecisionEngine.avaliar_carta (self._de(),
                # cache por instância -- ver bloco 03/08) pra não divergir
                # "dois motores" na mesma decisão. Achado real 10/08 (mesmo
                # bug do Sanji/Gum-Gum Giant OP09-078): sem o gate, esta
                # função de EXECUÇÃO podia escolher jogar uma carta que só
                # tem bloco [Counter] achando que ela ia comprar/buffar,
                # quando nada acontece fora de batalha -- a DECISÃO
                # (avaliar_carta, via _score_activate_main) já ganhou esse
                # gate neste mesmo fix; sem espelhar aqui, a execução real
                # continuaria escolhendo a carta errada mesmo com a decisão
                # de ativar já correta.
                f = get_card_flags(c.code)
                s = c.board_value()
                de = self._de()
                if (f.get('kos') or f.get('is_removal')) and de._step_condition_currently_holds(
                        c, lambda st: st.get('action') in (
                            'ko', 'trash_character', 'ko_selected', 'debuff_power', 'set_base_power',
                            'rest_opp_character', 'place_opp_character_bottom_deck',
                            'lock_opp_character_refresh', 'lock_opp_character_attack')):
                    s += 70
                if f.get('bounces') and de._step_condition_currently_holds(
                        c, lambda st: st.get('action') in ('bounce', 'opp_bounce_own_character')):
                    s += 45
                if f.get('rests_opponent') and de._step_condition_currently_holds(
                        c, lambda st: st.get('action') == 'rest_opp_character'):
                    s += 35
                if f.get('is_searcher') and de._step_condition_currently_holds(
                        c, lambda st: st.get('action') in ('look_top_deck', 'add_to_hand', 'add_from_trash')):
                    s += 40
                if f.get('draws') and de._step_condition_currently_holds(
                        c, lambda st: st.get('action') == 'draw'):
                    s += 35
                if f.get('is_blocker'):                 s += 30
                if f.get('power_buff') and de._step_condition_currently_holds(
                        c, lambda st: st.get('action') == 'buff_power'):
                    s += 20
                if f.get('has_trigger'):                s += 10
                # Carta CERTA do game_plan (a bomba do combo, ex: Five Elders):
                # 3a copia do MESMO bug ja corrigido em avaliar_carta (14/07) e
                # em order_target_candidates/own_hand (09/07) -- esta selecao
                # (usada pela EXECUCAO real de qualquer 'play_card' dentro de
                # QUALQUER trigger, incl. Empty Throne activate_main) nunca
                # tinha sido tocada. Sem isso, um searcher generico (+40 de
                # flag) batia a bomba de 12000 poder (board_value=12, zero
                # flags) por larga margem -- achado ao vivo indireto 14/07
                # (Empty Throne jogou Ju Peter em vez de Five Elders com
                # ambos na mao). Generico via compute_game_plan, zero nome de
                # carta.
                try:
                    if compute_game_plan(me).get('win_con_code') == c.code:
                        s += 90
                except Exception:
                    pass
                return s

            def _pior_para_trocar(field_chars):
                # Pior character pra eventual troca por um play gratis quando o
                # campo ja tem 5. EXCEÇÃO (aprovada por Arthur, audit PLAY):
                # nunca escolhe pra trocar quem tem has_blocker ou DON anexado
                # -- board_value() nao captura esse papel ativo (um Blocker de
                # power baixo seguraria o campo; um character com DON anexado
                # perde esse DON se for trashado, ja que nada devolve pra area
                # de custo nesse caminho -- bug separado, registrado, nao
                # corrigido aqui, só evitado com essa exceção).
                candidatos = [x for x in field_chars
                              if not (x.has_blocker or x.blocker_this_turn) and x.don_attached == 0]
                pool = candidatos if candidatos else field_chars  # se TODOS
                # tiverem papel ativo, nao trava a troca pra sempre -- usa o
                # pool completo como ultimo recurso.
                if not pool:
                    return None
                return min(pool, key=lambda x: x.board_value())

            def _put_into_play(c):
                # replica a parte de "entrar em campo" de _play_card, SEM cobrar
                # DON e sem o verbose do replay. Eventos vão pro trash (resolvem
                # efeito on_play depois), characters/stages pro campo.
                if c.card_type == 'CHARACTER':
                    if len(me.field_chars) >= 5:
                        worst = _pior_para_trocar(me.field_chars)
                        if worst is not None:
                            remove_character_from_field(me, worst, 'trash')
                    c.rested = False
                    me.field_chars.append(c)
                    apply_conditional_keyword_passives(me, opp)
                    c.just_played = not (c.has_rush or c.rush_this_turn or c.is_rush_character())
                    c.rush_character_only_this_turn = c.is_rush_character() and not c.is_rush()
                    self._dispatch_char_played(c, via_effect=True)
                elif c.card_type == 'STAGE':
                    if me.field_stage:
                        me.trash.append(me.field_stage)
                    me.field_stage = c
                elif c.card_type == 'EVENT':
                    me.trash.append(c)
                    me.events_activated_costs_this_turn.append(c.cost)
                    self._dispatch_event_activated()
                # dispara o efeito on_play da carta jogada (entrou agora).
                # Propaga self._is_my_turn: se este play_card esta rodando
                # dentro da resolucao do proprio 'trigger' de vida (GRUPO 1,
                # source='self'), o contexto e o mesmo passado pelo call-site
                # que resolveu a vida (is_my_turn=False, e o turno de quem
                # ataca); se veio do play_card de OUTRO efeito (GRUPO 2), o
                # contexto e o turno de quem controla (default True).
                self.execute(c, 'on_play', is_my_turn=self._is_my_turn)
                self.execute(c, 'main')

            source = step.get('source')

            # GRUPO 1 — jogar a própria carta (trigger de vida), opcional por score
            if source == 'self':
                if not contains_identity(me.hand, card):
                    return ''   # já saiu da mão / contexto inesperado
                # valor de jogar (corpo em campo) vs guardar na mão (counter/futuro)
                val_play = _score_to_play(card)
                val_keep = card.counter / 1000 * 15 + card.board_value() * 0.3
                # guarda de campo cheio: só descarta o pior se a nova supera
                campo_cheio = (card.card_type == 'CHARACTER' and len(me.field_chars) >= 5)
                if campo_cheio:
                    pior = _pior_para_trocar(me.field_chars)
                    if pior is None or card.board_value() <= pior.board_value():
                        return ''   # não vale trocar — mantém na mão
                if val_play <= val_keep:
                    return ''       # vale mais na mão — não joga
                remove_by_identity(me.hand, card)
                _put_into_play(card)
                return f'jogou {card.name[:18]} (grátis, do trigger)'

            # GRUPO 2 — jogar carta da mão (ou mão+trash) com filtro, escolhendo a melhor
            # Achado 06/08 (mesmo de _step_is_viable): so tratava
            # 'don_count_self', faltava 'don_count_opp' -- _resolve_cost_lte
            # ja cobre os dois.
            cost_lte = self._resolve_cost_lte(step, default=None)
            cost_eq = step.get('cost_eq')
            fontes = [me.hand]
            if step.get('source_alt') == 'trash':
                fontes.append(me.trash)

            elegiveis = []
            for fonte in fontes:
                elegiveis.extend(
                    c for c in eligible_cards(
                        fonte,
                        cost_lte=cost_lte,
                        cost_eq=cost_eq,
                        power_lte=step.get('power_lte'),
                        power_gte=step.get('power_gte'),
                        power_eq=step.get('power_eq'),
                        has_trigger=step.get('has_trigger', False),
                        filter_text=step.get('filter_type', ''),
                        # filter_names (lista, ex: PRB02-018/ST13-006) tem
                        # prioridade sobre filter_name singular -- os dois
                        # nunca coexistem no mesmo step (parser so emite um
                        # ou outro).
                        name_or_code=step.get('filter_names') or step.get('filter_name', ''),
                        color=step.get('color', ''),
                        exclude_name=step.get('exclude', ''),
                    )
                    # sem card_type explicito no step = CHARACTER (mesma regra
                    # de _step_is_viable e _elegivel_para_play — 12/07)
                    if c.card_type == (step.get('card_type') or 'CHARACTER').upper()
                )
            # "no base effect" -- so cartas sem efeito parseado no banco
            # (achado 16/07, EB02-022/EB03-003/EB03-007/EB03-039), mesma
            # convencao ja usada por gain_life (source=='trash').
            if step.get('filter_no_effect'):
                elegiveis = [c for c in elegiveis
                             if not get_card_effects(c.code)]
            # "that is a different color than the returned Character"
            # (achado 30/07, Trafalgar Law OP01-002) -- exclui candidatos
            # da MESMA cor que a carta salva pelo step de bounce anterior
            # no mesmo bloco (self._last_selected, ver action=='bounce').
            # Sem self._last_selected (bounce nao rodou por algum motivo),
            # nao filtra nada -- conservador, nao trava o play inteiro por
            # falta de memoria.
            if step.get('exclude_color_of_selected') and self._last_selected is not None:
                cor_excluida = self._last_selected.color
                elegiveis = [c for c in elegiveis if c.color != cor_excluida]

            if not elegiveis:
                return ''

            count = step.get('count', 1)
            jogadas = []
            # "N each of [A], [B], and [C]" (ex: ST13-006) -- ate N de CADA
            # nome da lista, independente uns dos outros (nao um total
            # compartilhado como o "OR" abaixo). Achado 17/07: sem esse
            # ramo, "play up to 1 each of [Sabo], [Portgas.D.Ace], and
            # [Monkey.D.Luffy]" jogaria so 1 carta no total (a de maior
            # score entre as 3), quando o texto permite ate 3 (1 por nome).
            if step.get('each') and step.get('filter_names'):
                for nome in step['filter_names']:
                    pool = [c for c in elegiveis if nome in c.name.lower()]
                    for _ in range(count):
                        if not pool:
                            break
                        melhor = max(pool, key=_score_to_play)
                        # guarda de campo cheio para characters
                        if melhor.card_type == 'CHARACTER' and len(me.field_chars) >= 5:
                            pior = _pior_para_trocar(me.field_chars)
                            if pior is None or melhor.board_value() <= pior.board_value():
                                remove_by_identity(pool, melhor)
                                remove_by_identity(elegiveis, melhor)
                                continue
                        if not remove_by_identity(me.hand, melhor):
                            remove_by_identity(me.trash, melhor)
                        remove_by_identity(pool, melhor)
                        remove_by_identity(elegiveis, melhor)
                        _put_into_play(melhor)
                        if step.get('enters_rested'):
                            melhor.rested = True
                        jogadas.append(melhor.name[:15])
            else:
                for _ in range(count):
                    if not elegiveis:
                        break
                    melhor = max(elegiveis, key=_score_to_play)
                    # guarda de campo cheio para characters
                    if melhor.card_type == 'CHARACTER' and len(me.field_chars) >= 5:
                        pior = _pior_para_trocar(me.field_chars)
                        if pior is None or melhor.board_value() <= pior.board_value():
                            remove_by_identity(elegiveis, melhor)
                            continue
                    if not remove_by_identity(me.hand, melhor):
                        remove_by_identity(me.trash, melhor)
                    remove_by_identity(elegiveis, melhor)
                    _put_into_play(melhor)
                    if step.get('enters_rested'):
                        melhor.rested = True
                    jogadas.append(melhor.name[:15])
            return f'jogou (grátis): {", ".join(jogadas)}' if jogadas else ''

        if action == 'add_from_trash':
            from optcg_engine.rules_facade import eligible_cards

            filter_name = step.get('filter_name', '').lower()
            count = step.get('count', 1)
            found = eligible_cards(
                me.trash,
                cost_lte=step.get('cost_lte'),
                cost_gte=step.get('cost_gte'),
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'),
                filter_text=step.get('filter_type', ''),
                name_or_code=filter_name,
                color=step.get('color', ''),
                exclude_name=step.get('exclude_name', ''),
            )
            added = []
            for c in found[:count]:
                remove_by_identity(me.trash, c)
                me.hand.append(c)
                added.append(c.name[:15])
            return f'recuperou do trash: {", ".join(added)}' if added else ''

        # ── Keywords ──────────────────────────────────────────────────────────
        if action == 'gain_rush':
            # target='selected': "that Character gains [Rush]" refere-se a
            # carta selecionada/jogada por um step ANTERIOR no mesmo bloco
            # (ex: OP12-058 Whitebeard, play_from_deck + gain_rush), nao a
            # propria `card` (o Event/Character que carrega o efeito).
            alvo = self._last_selected if step.get('target') == 'selected' else card
            if alvo is None:
                return ''
            if step.get('duration') == 'this_turn':
                alvo.rush_this_turn = True
                return 'ganhou Rush (so este turno)'
            alvo.has_rush = True
            return 'ganhou Rush'
        if action == 'gain_rush_character':
            card.has_rush_character = True
            # Se o character ja esta em campo (efeito concedido mid-jogo, nao
            # no momento em que entrou), a restricao de alvo so importa se
            # ele ainda nao atacou neste turno -- aproxima usando just_played
            # como sinal de 'ainda no turno em que pode usar a permissao'.
            # Quando concedido no proprio turno em que e jogado (ex:
            # EB04-007 via Activate:Main apos o On Play), marca a janela.
            card.rush_character_only_this_turn = not (card.has_rush or card.rush_this_turn)
            return 'ganhou Rush: Character'
        if action == 'grant_rush_character_type':
            wanted = _norm_type_text(step.get('filter_type') or '')
            granted = []
            for target in me.field_chars:
                if wanted and wanted in _norm_type_text(target.sub_types):
                    target.has_rush_character = True
                    if target.just_played:
                        target.rush_character_only_this_turn = True
                    granted.append(target.name[:14])
            return f'Rush: Character para tipo: {", ".join(granted)}' if granted else ''
        if action == 'select_grant_rush_character':
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            count = step.get('count', 1)
            # Mesmo achado do select_grant_rush (02/08) -- Rush: Character
            # so importa pra quem entrou em campo NESTE turno (just_played)
            # e ainda nao tem a permissao de nenhuma fonte.
            candidates = [c for c in eligible_cards(
                me.field_chars,
                filter_text=step.get('filter_type', ''),
                name_or_code=step.get('filter_name', ''),
            ) if character_needs_rush_character(c)]
            granted = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                target.has_rush_character = True
                if target.just_played:
                    target.rush_character_only_this_turn = True
                # atributo ADICIONAL temporario (achado 19/07, OP15-093:
                # "gains [Rush: Character] and the 'Slash' attribute
                # during this turn").
                if step.get('grant_attribute'):
                    target.extra_attribute_this_turn = step['grant_attribute']
                remove_by_identity(candidates, target)
                granted.append(target.name[:15])
            return f'ganhou Rush: Character: {", ".join(granted)}' if granted else ''
        if action == 'gain_blocker':
            if step.get('duration') == 'this_turn':
                card.blocker_this_turn = True
                return 'ganhou Blocker (so este turno)'
            card.has_blocker = True
            return 'ganhou Blocker'
        if action == 'select_grant_blocker':
            # "Up to N of your [Tipo] Characters [com filtro de custo]
            # [other than [Nome]] gains [Blocker]" -- SELECIONA outro
            # Character do proprio campo (por tipo/custo/exclusao),
            # DISTINTO de gain_blocker (sempre a propria carta-fonte, sem
            # selecao). 'until_opp_end_phase'/'until_opp_turn_end' mapeiam
            # pro MESMO blocker_this_turn -- o engine ja trata "this turn"
            # e "ate a proxima End Phase do oponente" como equivalentes
            # (mesma simplificacao documentada em refresh_phase pra
            # cannot_attack_until/cannot_be_rested_until: ambos so resetam
            # no refresh do DONO, entao a granularidade e identica).
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            count = step.get('count', 1)
            candidates = eligible_cards(
                me.field_chars,
                cost_lte=step.get('cost_lte'),
                filter_text=step.get('filter_type', ''),
                exclude_name=step.get('exclude', ''),
            )
            granted = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                target.blocker_this_turn = True
                remove_by_identity(candidates, target)
                granted.append(target.name[:15])
            return f'ganhou Blocker: {", ".join(granted)}' if granted else ''
        if action == 'select_grant_rush':
            # "Up to N of your [Nome] Characters OR up to M of your
            # Characters with a type including "Tipo", with X power or
            # more, gains [Rush]" -- OR entre nome exato E (tipo+power),
            # nao AND (achado 17/07, OP16-001). filter_name casa QUALQUER
            # power; filter_type exige power_gte tambem. Variante GENERICA
            # (sem filter_name, achado 17/07: EB03-001/OP04-001/OP12-007/
            # PRB01-001): filtro UNICO combinando tipo/custo/exclusao/
            # filter_no_tag (AND, nao OR).
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            count = step.get('count', 1)
            # Rush so importa pra quem ENTROU EM CAMPO NESTE TURNO
            # (just_played) e ainda nao tem Rush por nenhuma fonte -- e o
            # unico caso em que a "doenca de invocacao" existe (comprehensive
            # rules: "This card can attack the turn it's played"). Um
            # Character de turnos anteriores ja pode atacar normalmente sem
            # Rush nenhum (nao e mais just_played), e um ja rested nao ataca
            # de novo de qualquer forma -- os dois casos tornam a concessao
            # um no-op. Achado real 02/08 (correcao do usuario: "rush só
            # importa para cartas que entram no turno, se a carta já estava
            # lá antes, o rush não faz efeito"; log Portgas.D.Ace-R x
            # Charlotte.Katakuri-P, 2026-08-01): Ace deu Rush pra Vista
            # (OP16-011), deployada 2 turnos antes e ja rested por ter
            # atacado neste mesmo turno -- ativacao do lider (once_per_turn)
            # totalmente desperdicada, nenhum efeito real.
            _precisa_de_rush = character_needs_rush
            if step.get('filter_name'):
                pool_nome = [c for c in eligible_cards(me.field_chars, name_or_code=step.get('filter_name', ''))
                            if _precisa_de_rush(c)]
                pool_tipo = [c for c in eligible_cards(
                    me.field_chars,
                    filter_text=step.get('filter_type', ''),
                    power_gte=step.get('power_gte'),
                ) if _precisa_de_rush(c)]
                candidates = list(pool_nome)
                for c in pool_tipo:
                    if not contains_identity(candidates, c):
                        candidates.append(c)
            else:
                candidates = [c for c in eligible_cards(
                    me.field_chars,
                    cost_lte=step.get('cost_lte'),
                    filter_text=step.get('filter_type', ''),
                    exclude_name=step.get('exclude', ''),
                ) if _precisa_de_rush(c)]
                filter_no_tag = step.get('filter_no_tag')
                if filter_no_tag:
                    candidates = [
                        c for c in candidates
                        if filter_no_tag not in get_card_effects(c.code).get('effects', {})
                    ]
            granted = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                if step.get('duration') == 'this_turn':
                    target.rush_this_turn = True
                else:
                    target.has_rush = True
                remove_by_identity(candidates, target)
                granted.append(target.name[:15])
            return f'ganhou Rush: {", ".join(granted)}' if granted else ''
        if action == 'select_grant_banish':
            # "Up to N of your [Nome] Characters gains [Banish]" --
            # SELECAO por nome proprio (achado 19/07, OP10-043 Moocy,
            # unica carta no banco), distinta de gain_banish (sempre
            # self, permanente).
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            count = step.get('count', 1)
            candidates = eligible_cards(me.field_chars, name_or_code=step.get('filter_name', ''))
            granted = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                if step.get('duration') == 'this_turn':
                    target.banish_this_turn = True
                else:
                    target.has_banish = True
                remove_by_identity(candidates, target)
                granted.append(target.name[:15])
            return f'ganhou Banish: {", ".join(granted)}' if granted else ''
        if action == 'gain_double_attack':
            # target='leader'/'selected': mesmo padrao ja usado em
            # gain_rush (linha ~8093) -- "Your Leader gains [Double
            # Attack]" (achado real 02/08, Edward Newgate OP16-003 +
            # Flame Emperor OP03-016 + Buggy EB02-018, auditoria global
            # do parser): o motor SEMPRE aplicava Double Attack na
            # propria carta-fonte, mesmo com o texto explicito dizendo
            # "Your Leader gains..." -- o buff_power irmao no MESMO
            # step ja tinha target='leader' capturado certo (Newgate:
            # "+2000 power" ia pro lider certinho), so gain_double_attack
            # ignorava target por completo, sempre `card` (self).
            alvo_target = step.get('target')
            if alvo_target == 'leader':
                alvo = me.leader
            elif alvo_target == 'selected':
                alvo = self._last_selected
            else:
                alvo = card
            if alvo is None:
                return ''
            if step.get('duration') == 'this_turn':
                alvo.double_attack_this_turn = True
                return 'ganhou Double Attack (so este turno)'
            alvo.has_double_attack = True
            return 'ganhou Double Attack'
        if action == 'select_grant_double_attack':
            # "Up to N of your [Tipo] type Characters gains [Double
            # Attack]" -- SELECAO de OUTRO Character (por tipo), distinto
            # de gain_double_attack (sempre a propria carta-fonte, sem
            # selecao). Mesma familia de select_grant_blocker/rush.
            # Achado 17/07, EB03-050/OP04-115.
            from optcg_engine.rules_facade import choose_highest_board_value, eligible_cards
            count = step.get('count', 1)
            candidates = eligible_cards(
                me.field_chars,
                filter_text=step.get('filter_type', ''),
                color=step.get('color', ''),
                cost_eq=step.get('cost_eq'),
                cost_lte=step.get('cost_lte'),
                cost_gte=step.get('cost_gte'),
            )
            granted = []
            for _ in range(min(count, len(candidates))):
                target = choose_highest_board_value(candidates)
                if step.get('duration') == 'this_turn':
                    target.double_attack_this_turn = True
                else:
                    target.has_double_attack = True
                remove_by_identity(candidates, target)
                granted.append(target.name[:15])
            return f'ganhou Double Attack: {", ".join(granted)}' if granted else ''
        if action == 'gain_banish':
            card.has_banish = True
            return 'ganhou Banish'
        if action == 'gain_unblockable':
            if step.get('duration') == 'this_turn':
                card.unblockable_this_turn = True
                return 'ganhou Unblockable (so este turno)'
            card.has_unblockable = True
            return 'ganhou Unblockable'

        # ── select_grant_unblockable_turn: "Select up to 1 of your [Tipo]
        # Character(s)/Leader-or-Character... if that card attacks during
        # this turn, opponent cannot activate [Blocker]." Equivalente (regra
        # 10-1-7-1) a conceder [Unblockable] SO NESTE TURNO ao alvo
        # escolhido -- por isso seta unblockable_this_turn, NUNCA
        # has_unblockable (que e permanente/nativo). DISTINTA de
        # gain_unblockable: aqui tem selecao de alvo com filtro, lá o alvo
        # é sempre 'card' (a própria carta com o efeito).
        # Sanji ST21-003, Diable Jambe ST01-016, OP13-057 (target='leader_only').
        if action == 'select_grant_unblockable_turn':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_board_value,
                eligible_cards,
            )

            if step.get('target') == 'leader_only':
                me.leader.unblockable_this_turn = True
                return f'{me.leader.name[:18]} ganhou Unblockable este turno'
            if step.get('target') == 'selected':
                # "Then, if the selected card attacks during this turn, your
                # opponent cannot activate Blocker" (OP07-057, OP12-077) --
                # alvo e o card escolhido por um step ANTERIOR no mesmo
                # bloco (buff_power target='select_filtered'), nao uma nova
                # selecao. Sem alvo memorizado, nao executa (mais seguro do
                # que adivinhar).
                alvo = self._last_selected
                if alvo is None:
                    return ''
                alvo.unblockable_this_turn = True
                return f'{alvo.name[:18]} (selecionado antes) ganhou Unblockable este turno'
            if step.get('target') == 'don_recipient':
                # OP12-016 (Rayleigh): alvo = quem recebeu o DON!! do
                # custo give_don_to_named (mesmo nome, achado 17/07) --
                # busca direto por nome em vez de memoria entre steps,
                # ja que o nome e conhecido em tempo de parse (sempre o
                # mesmo em ambas as clausulas da carta).
                nome = (step.get('target_name') or '').lower()
                candidatos_nome = list(me.field_chars) + [me.leader]
                alvo = next((c for c in candidatos_nome if nome in c.name.lower()), None)
                if alvo is None:
                    return ''
                alvo.unblockable_this_turn = True
                return f'{alvo.name[:18]} (recebeu o DON!!) ganhou Unblockable este turno'
            filter_type = step.get('filter_type', '')
            candidatos = eligible_cards(
                me.field_chars,
                filter_text=filter_type,
                power_gte=step.get('power_gte'),
                # color: "up to N of your black {Tipo} type Characters
                # gains [Unblockable]" (achado 19/07, OP16-095, confirmado
                # por foto do usuario).
                color=step.get('color', ''),
            )
            if step.get('include_leader') and card_matches_filter(me.leader, filter_type):
                candidatos.append(me.leader)
            if not candidatos:
                return ''
            alvo = choose_highest_board_value(candidatos)
            alvo.unblockable_this_turn = True
            return f'{alvo.name[:18]} ganhou Unblockable este turno'

        # ── "can also attack active Characters" -- keyword nova (achada
        # 27/06, 9 cartas). gain_can_attack_active = PERMANENTE ("This
        # Character can also attack active Characters", sem seleção --
        # Cavendish OP04-081, Luffy OP04-090). select_grant_*_turn = mesma
        # estrutura de select_grant_unblockable_turn, mas concede
        # can_attack_active_this_turn (temporário) ao alvo escolhido.
        if action == 'gain_can_attack_active':
            card.can_attack_active = True
            return f'{card.name[:18]} pode atacar characters ativos (permanente)'

        # "This Character's effect is negated during this turn" (OP06-083,
        # OP14-056): libera o ataque nas cartas cuja UNICA passiva propria
        # e cannot_attack_self (ver is_attack_locked_self).
        if action == 'negate_own_effect':
            card.own_effect_negated_this_turn = True
            return f'{card.name[:18]}: efeito proprio negado este turno'

        if action == 'select_grant_can_attack_active_turn':
            from optcg_engine.rules_facade import (
                card_matches_filter,
                choose_highest_board_value,
                eligible_cards,
            )

            filter_type = step.get('filter_types') or step.get('filter_type', '')
            candidatos = eligible_cards(me.field_chars, filter_text=filter_type)
            if step.get('include_leader') and card_matches_filter(me.leader, filter_type):
                candidatos.append(me.leader)
            if not candidatos:
                return ''
            alvo = choose_highest_board_value(candidatos)
            alvo.can_attack_active_this_turn = True
            if step.get('allow_played_this_turn'):
                alvo.rush_character_only_this_turn = True
            return f'{alvo.name[:18]} pode atacar characters ativos este turno'

        # Keywords passivas (apenas registra, já vem do banco)
        if action in ('keyword_blocker', 'keyword_rush', 'keyword_double_attack',
                      'keyword_banish', 'keyword_trigger', 'keyword_unblockable'):
            return ''

        return ''

    # ── Helpers de IA ────────────────────────────────────────────────────────

    def _trash_value(self, card: Card) -> float:
        """Valor aproximado de manter uma carta na mao; menor = melhor descarte."""
        if card is None:
            return 10**9

        value = self._de().avaliar_carta(card)
        text = (card.card_text or '').lower()
        flags = get_card_flags(card.code)

        if card.card_type == 'EVENT':
            if '[counter]' in text:
                # Protecao com retorno decrescente: 1 counter na mao e uma
                # rede de seguranca real, mas o 2o/3o valem cada vez menos
                # (redundantes) -- achado 09/07: bot trashando evento
                # counter em vez de personagem reanimavel, mesmo com varios
                # counters acumulados na mao.
                counters_na_mao = sum(
                    1 for c2 in self.me.hand
                    if c2.card_type == 'EVENT' and '[counter]' in (c2.card_text or '').lower())
                value += 35 / max(1, counters_na_mao)
                if self.me.life_count() <= 2:
                    value += 35
            if flags.get('kos') or flags.get('is_removal') or flags.get('bounces'):
                value += 35
            if 'negate the effect' in text or 'cannot be removed' in text:
                value += 40
            if flags.get('draws') or flags.get('is_searcher'):
                value += 20

        # Carta cara OU corpo grande = win condition ou ameaça principal;
        # proteger mesmo sem DON disponível agora (provavelmente jogável
        # nos próximos turnos). Achado real 09/08 (partida ao vivo, log
        # Marshall.D.Teach-BY_x_Rocks.D.Xebec-B): o gate original (SO
        # custo>=7) nunca disparava pro Shiryu (custo 6, 8000 de poder --
        # a carta de maior impacto na mão inteira) — a carta foi
        # descartada como custo de um Counter (You're the One Who Should
        # Disappear) em vez de qualquer uma das outras 3 na mão, porque
        # nenhuma proteção de "carta grande" existia abaixo de custo 7.
        # Generalizado pra OR com poder>=7000: cobre tanto decks cuja
        # bomba é cara (custo alto) quanto decks cuja bomba é um corpo de
        # poder alto por custo relativamente baixo (o padrão de "Shiryu"),
        # sem depender do numero exato de nenhuma carta especifica.
        if card.card_type == 'CHARACTER' and (card.cost >= 7 or card.power >= 7000):
            # poder/1000 tetado em 14 (maior corpo real do jogo hoje) --
            # sem o teto, um poder fora da curva real (ex: fixture de
            # teste sintetico com 20000) inflava a protecao muito alem do
            # que o proprio ramo de custo>=7 alcanca (max +100, custo 10),
            # dominando indevidamente outras proteções (ex: evento
            # [Counter] unico na mão, +35) que a mesma função pondera.
            value += 20 + max(card.cost, min(card.power / 1000, 14)) * 8   # custo/poder 10 -> +100 extra

        # GamePlan (HANDOFF #119): a carta identificada como combo/bomba do
        # deck (maior play_from_trash, ex: Five Elders) ganha proteção
        # extra explícita enquanto o DON ainda não bate o custo dela —
        # diferente do bônus genérico de custo≥7 acima, este é ligado à
        # carta CERTA do deck, não a qualquer carta cara.
        plano = compute_game_plan(self.me)
        if (plano['win_con_code'] and card.code == plano['win_con_code']
                and plano['don_target'] and self.me.don_available < plano['don_target']):
            value += 150

        # Carta que ENCHE O TRASH no on_play (self-mill: trash_rest/
        # trash_from_hand/mill) e trash_SETUP do deck: enquanto o trash ainda
        # nao bateu o alvo do game_plan (ex: Imu precisa de 7 pra imunidade dos
        # Celestial Dragons + combo), joga-la ADIANTA o plano -> NAO trashar
        # como custo, guardar pra JOGAR. Pedido do usuario 14/07 (Shalria da mao
        # no early nao deve ser trashada). Generico via game_plan.trash_target +
        # acoes de trash no proprio on_play (zero nome de carta).
        if (card.card_type == 'CHARACTER' and plano.get('trash_target')
                and len(self.me.trash) < plano['trash_target']):
            _TRASH_FILL = {'trash_rest', 'trash_from_hand', 'mill', 'mill_self',
                           'trash_deck_top', 'self_mill'}
            op_steps = get_card_effects(card.code).get('on_play', {}).get('steps', [])
            if any(s.get('action') in _TRASH_FILL for s in op_steps):
                value += 50

        # Carta jogável ESTE turno vale ainda mais — perda dupla se trashada.
        custo = effective_hand_play_cost(self.me, card, self.opp)
        if custo <= self.me.don_available:
            value += 60 + custo * 6   # bônus adicional por ser jogável agora

        # Personagem recuperavel via play_from_trash da propria engine do
        # deck (ex: Five Elders OP13-082 reanima ate 5 copias de 5000 power
        # com esse mesmo nome/tipo) e descarte SEGURO: a perda e temporaria.
        # Achado 09/07 (log 17.52.14): bot trashando evento [Counter] em vez
        # de um Elder reanimavel para o custo trash_char_or_hand do lider
        # Imu -- generico pra qualquer carta+reanimador que bata o filtro,
        # nao hardcoded pro Five Elders.
        if card.card_type == 'CHARACTER':
            for src in list(self.me.field_chars) + list(self.me.hand):
                if src is card:
                    continue
                am = get_card_effects(src.code).get('activate_main', {})
                pft = next((s for s in am.get('steps', [])
                            if s.get('action') == 'play_from_trash'), None)
                if not pft:
                    continue
                conds = am.get('conditions', {})
                if conds and not EffectExecutor(self.me, self.opp)._check_conditions(conds, src):
                    continue
                ft = (pft.get('filter_type') or '').lower()
                if ft and ft not in (card.sub_types or '').lower():
                    continue
                peq = pft.get('power_eq')
                if peq is not None and card.power != peq:
                    continue
                value *= 0.4   # a maior parte do valor volta via reanimacao
                break

        return value

    def _choose_to_trash(self, hand: list) -> Optional[Card]:
        """Escolhe a carta de menor valor situacional para descartar."""
        if not hand:
            return None
        return min(hand, key=self._trash_value)

    _SACRIFICE_COST_TYPES = {'trash_from_hand', 'trash_hand', 'trash_char_or_hand',
                             'trash_typed_hand_or_named_hand_field',
                             'ko_own_character', 'trash_self', 'trash_own_life',
                             'trash_own_character', 'return_own_character_to_hand'}

    def _combat_buff_worth_paying(self, card: Card, ef_data: dict, trigger: str,
                                  battle_defender_power: 'int | None') -> 'bool | None':
        """
        Guard de VALOR pro padrao "custo de recurso (DON!!/rest) -> buff_power
        de batalha em self/leader": so paga se o buff VIRA o combate (empate
        vai pro atacante, buff_wins_combat). Achado real 22-23/07 (Katakuri
        OP11-062): esse guard so existia em resolve_optional_effect
        (sim_bridge.py, caminho AO VIVO) -- o simulador interno (self-play/
        line-search, que passa por execute() diretamente) tratava QUALQUER
        custo de recurso como "sempre vale a pena" via
        _worth_paying_optional_costs, uma divergencia real de "dois motores"
        (regra do usuario) que superestimava linhas simuladas com esse
        padrao. Consolidado aqui com informacao REAL (self-play conhece as
        duas maos, sem precisar da estimativa por incerteza que o bridge
        usa pro caminho mascarado ao vivo) -- generico, qualquer carta com
        esse padrao, nao so quem revelou o gap.
        Retorna None se o efeito nao casa com o padrao (deixa o caller cair
        no _worth_paying_optional_costs generico).
        """
        costs = ef_data.get('costs', [])
        steps = ef_data.get('steps', [])
        if not costs or not any(c.get('type') in ('don_minus', 'rest_don', 'rest_self')
                                 for c in costs):
            return None
        buffs = [s for s in steps
                 if s.get('action') == 'buff_power'
                 and s.get('target') in ('self', 'leader')
                 and s.get('duration') in ('battle_only', 'this_battle')]
        if not buffs or not all(
                s.get('action') in ('buff_power', 'peek_opp_deck_top', 'look_top_deck')
                for s in steps):
            return None
        if battle_defender_power is None:
            return None

        don_minus_count = sum(int(c.get('count', 1) or 1) for c in costs
                              if c.get('type') == 'don_minus')
        de = self._de()
        if don_minus_count and de.has_valuable_don_return_trigger(don_minus_count):
            return None  # retorno de DON pode valer mais que o guard simples

        # Prioridade de RAMP (pedido explicito do usuario, 23/07): sem
        # carta em campo que aproveita a devolucao (when_don_returned,
        # checado acima) e ainda LONGE do teto de 10 DON, a meta e acumular
        # DON, nao gastar 1 por vez num ganho marginal (peek+buff de 1000,
        # por exemplo) -- mesmo que o buff vire ESTE combate especifico.
        # So libera o gasto marginal se a vida ja esta critica (<=2): ai
        # defender pesa mais que a curva de ramp. Isso NAO se aplica a
        # outros custos don_minus fora deste padrao (ex: KO de Pekoms,
        # remocao real) -- so ao combo "recurso -> buff de batalha" que
        # este metodo cobre.
        if don_minus_count and self.me.don_on_field() < 10 and self.me.life_count() > 2:
            return False

        amount = max(s.get('amount', 0) for s in buffs)
        if trigger == 'when_attacking':
            attacker_power = live_attack_power(card)
            defender_power = battle_defender_power
            # Atacante: empate ja favorece quem ataca -- so vale a pena se
            # HOJE perde (attacker < defender) e o buff faz alcancar/superar.
            return attacker_power < defender_power <= attacker_power + amount
        elif trigger == 'on_opp_attack':
            attacker = self._battle_attacker
            if attacker is None:
                return None
            attacker_power = live_attack_power(attacker)
            defender_power = battle_defender_power
            return de.buff_wins_combat(defender_power, attacker_power, defender_power + amount)
        return None

    def _worth_paying_optional_costs(self, costs: list, card: Card) -> bool:
        """
        Em OPTCG, um bloco de efeito com custo é sempre "you may pagar X: Y"
        -- decide se vale a pena. ÚNICA fonte de verdade pra essa pergunta,
        usada tanto por `execute()` (simulador interno) quanto por
        `resolve_optional_effect()` em sim_bridge.py (caminho ao vivo).
        Achado real 09/07: existiam DUAS heurísticas diferentes pra essa
        MESMA decisão -- o simulador interno pagava sempre que havia alvo
        (sem julgar se compensava), e o caminho ao vivo tinha sua própria
        régua isolada, sem nem saber qual carta/efeito estava perguntando.
        Isso e exatamente o que a regra "sem dois motores" existe pra
        evitar (ver memory/feedback_dois_motores.md) -- consolidado aqui.
        Custos de RECURSO (rest_self/rest_don/don_minus) não entram nessa
        conta -- já são filtrados por pagabilidade antes de chegar aqui;
        só custos de SACRIFÍCIO (mão/campo/vida) exigem julgamento de valor.

        reveal_from_hand NÃO é recurso (não gasta nada) nem estava na
        tabela de sacrifício, mas ainda EXIGE ter N cartas específicas na
        mão -- nunca era checado aqui (só em `_pay_costs`, no momento de
        pagar de verdade). Achado real 02/08: o caminho ao vivo aceitava o
        custo achando "de graça" mesmo sem cartas suficientes, travando o
        jogo pedindo alvos que não existem (ver `_reveal_from_hand_matches`).
        """
        for c in costs:
            if c.get('type') != 'reveal_from_hand':
                continue
            if len(self._reveal_from_hand_matches(c)) < c.get('count', 1):
                return False

        if not any(c.get('type') in self._SACRIFICE_COST_TYPES for c in costs):
            return True

        # trash_char_or_hand (ex: lider Imu): o custo tambem pode ser pago
        # com um personagem do CAMPO -- um corpo de 0 poder cujo On Play ja
        # foi gasto (ex: Saint Shalria) e sacrificio quase gratis, e trashar
        # ele ainda alimenta o plano de lixeira do deck. Achado real 11/07
        # (log 00.49.30): sem esta checagem, a decisao olhava SO a mao --
        # mao com cartas valiosas => recusava o draw do lider todo turno,
        # mesmo com 2 Shalrias gastas paradas no campo. Mesmo criterio de
        # escala do _pay_costs (board_value*10 comparavel a _trash_value).
        for c in costs:
            if c.get('type') != 'trash_char_or_hand':
                continue
            from optcg_engine.rules_facade import eligible_cards
            chars = eligible_cards(self.me.field_chars,
                                   filter_text=c.get('filter_type', ''))
            if chars and min(ch.board_value() * 10 for ch in chars) <= 60:
                return True

        # ko_own_character/trash_own_character: custo PURAMENTE de campo
        # (K.O. ou trash de um Character proprio, nunca da mao). Achado
        # 16/07: ko_own_character ja existia ha tempos mas SEMPRE caia no
        # branch generico final, que so olha self.me.hand -- avaliando o
        # recurso ERRADO (mao) pra um custo que nunca toca a mao. Mesmo
        # criterio de escala do branch trash_char_or_hand acima
        # (board_value*10 <= 60), mas aqui o RETURN e definitivo (nao
        # "either/or" com a mao -- se o campo nao compensa, o custo nao
        # compensa, ponto final, nao cai no fallback de mao).
        for c in costs:
            if c.get('type') not in ('ko_own_character', 'trash_own_character'):
                continue
            from optcg_engine.rules_facade import eligible_cards
            chars = eligible_cards(
                self.me.field_chars,
                filter_text=c.get('filter_type', ''),
                power_lte=c.get('power_lte'),
                power_gte=c.get('power_gte'),
                power_eq=c.get('power_eq'),
                exclude_card=card,
            )
            return bool(chars) and min(ch.board_value() * 10 for ch in chars) <= 60

        # return_own_character_to_hand: mesmo criterio de ko_own_character/
        # trash_own_character (custo de CAMPO, nunca da mao) -- achado
        # 16/07 (OP10-047 e familia, 8 cartas): esse custo nunca tinha
        # branch proprio aqui, entao caia no `not any(... SACRIFICE...)`
        # do topo e SEMPRE era considerado "de graca" (sem julgar se
        # devolver o Character pra mao compensa o efeito). Devolver a mao
        # e menos definitivo que K.O./trash (a carta pode ser rejogada
        # depois), mas ainda e perda real de tempo/board -- mesmo limiar
        # de "sacrificio barato" (board_value*10 <= 60).
        for c in costs:
            if c.get('type') != 'return_own_character_to_hand':
                continue
            from optcg_engine.rules_facade import eligible_cards
            chars = eligible_cards(
                self.me.field_chars,
                cost_gte=c.get('cost_gte'),
                filter_text=c.get('filter_type', ''),
                exclude_name=c.get('exclude', ''),
                exclude_card=card if c.get('exclude_self') else None,
            )
            return bool(chars) and min(ch.board_value() * 10 for ch in chars) <= 60

        for c in costs:
            if c.get('type') != 'trash_typed_hand_or_named_hand_field':
                continue
            from optcg_engine.rules_facade import eligible_cards
            named = (c.get('alternate_name') or '').lower()
            hand = eligible_cards(self.me.hand, filter_text=c.get('filter_type', ''))
            hand.extend(x for x in self.me.hand if named in x.name.lower())
            field = [x for x in self.me.field_chars if named in x.name.lower()]
            if self.me.field_stage and named in self.me.field_stage.name.lower():
                field.append(self.me.field_stage)
            values = [self._trash_value(x) for x in hand]
            values.extend(x.board_value() * 10 for x in field)
            # _trash_value tem piso estrutural 75 mesmo para carta 0/0 sem
            # counter; usar 60 tornaria as alternativas da mao impossiveis.
            return bool(values) and min(values) <= 80

        if len(self.me.hand) < 2:
            return False
        worst = self._choose_to_trash(self.me.hand)
        if worst is None:
            return False
        # FASE B do Turn Planner (usuario, 24/07: combos mapeados devem
        # entrar na decisao). Se meu board tem um watcher on_hand_card_
        # trashed (fase 1.4, ex: Kuroobi OP14-045 ganha Rush, Wadatsumi
        # OP14-056 nega efeito proprio) pagar este custo generico de
        # trash_from_hand TAMBEM aciona esse payoff -- fica mais aceitavel
        # sacrificar uma carta um pouco mais valiosa.
        limiar = 60
        meus = [self.me.leader, *self.me.field_chars]
        if self.me.field_stage:
            meus.append(self.me.field_stage)
        if any(get_card_effects(c.code).get('on_hand_card_trashed') for c in meus):
            limiar += 25
        return self._trash_value(worst) <= limiar


# ===========================================================================
# Carregamento de dados
# ===========================================================================

def _leading_keyword(t: str, kw: str) -> bool:
    """
    True so se `kw` aparece entre os keyword tags no INICIO do texto (ex:
    "[Blocker] (After your opponent...)", "[Rush][Blocker] [On Play]...").
    Convencao do jogo: keywords INCONDICIONAIS sempre vem colados no
    comeco, um colchete atras do outro. Distingue de "gains [Blocker]"/
    "this Character gains [Rush]" embutido no MEIO de uma frase condicional
    ("If you have 7+ cards in your trash, ... gains [Blocker]") -- achado
    real 10/07 (St. Marcus Mars OP13-091 sempre contava como blocker na
    pontuacao de ataque, mesmo com a lixeira vazia no turno 1, porque
    `'[blocker]' in t` acha a substring em QUALQUER lugar do texto,
    inclusive dentro da condicao). NAO aplicar a has_trigger: [Trigger]
    e convenção OPOSTA (sempre no FINAL do texto, apos as outras
    habilidades) -- confirmado numericamente (so 42/475 cartas com
    [Trigger] teriam o tag "no inicio").
    """
    return bool(re.match(r'^(?:\[[^\]]+\]\s*)*\[' + re.escape(kw) + r'\]', t.strip()))


def parse_card_effects_basic(text: str, counter_amount: str) -> dict:
    """Parser básico de keywords para cartas sem entrada no banco."""
    t = (text or '').lower()
    c_val = 0
    try:
        c_str = str(counter_amount or '').replace('.0', '')
        if c_str.isdigit():
            c_val = int(c_str)
    except:
        pass
    return {
        'has_rush':          _leading_keyword(t, 'rush'),
        'has_blocker':       _leading_keyword(t, 'blocker'),
        'has_double_attack': _leading_keyword(t, 'double attack'),
        'has_banish':        _leading_keyword(t, 'banish'),
        'has_trigger':       '[trigger]' in t,
        'has_unblockable':   _leading_keyword(t, 'unblockable'),
        'counter':           c_val,
    }


def load_cards_db(csv_path: str = 'cards_rows.csv') -> dict:
    db = {}
    try:
        df = pd.read_csv(csv_path)
        for col in ['card_cost', 'card_power', 'life']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        for col in ['card_set_id', 'card_name', 'card_color', 'card_type',
                    'card_text', 'counter_amount', 'sub_types']:
            df[col] = df[col].fillna('').astype(str)

        for _, row in df.iterrows():
            code = row['card_set_id'].split('_')[0]
            if not code or code == 'nan':
                continue
            kws = parse_card_effects_basic(row['card_text'], row['counter_amount'])
            db[code] = {
                'name':      row['card_name'],
                'color':     row['card_color'],
                'type':      row['card_type'].upper(),
                'cost':      int(row['card_cost']),
                'power':     int(row['card_power']),
                'life':      int(row['life']),
                'text':      row['card_text'],
                'sub_types': row['sub_types'],
                **kws,
            }
            # Guarda URL de imagem para o replay viewer
            img_url = str(row.get('card_image', '') or '')
            if img_url and img_url != 'nan':
                _CARD_IMAGE_CACHE[code] = img_url
        print(f'  Banco de cartas: {len(db)} cartas carregadas')
    except Exception as e:
        print(f'  Erro ao carregar {csv_path}: {e}')
    return db


def validar_deck(leader: Card, cards: list, cards_db: dict) -> tuple:
    from collections import Counter
    erros = []
    if len(cards) != 50:
        erros.append(f'Total: {len(cards)} (deve ser 50)')
    contagem = Counter(c.code for c in cards)
    for code, qty in contagem.items():
        unlimited = any(r.get('type') == 'unlimited_copies'
                        for r in get_card_game_rules(code))
        if qty > 4 and not unlimited:
            erros.append(f'{code}: {qty} copias (max 4)')
    for rule in get_card_game_rules(leader.code):
        if rule.get('type') == 'forbid_cards_cost_gte':
            invalidos = sorted({c.code for c in cards if c.cost >= rule['cost_gte']})
            if invalidos:
                erros.append(f"{leader.code}: cartas de custo {rule['cost_gte']}+ proibidas: "
                             + ', '.join(invalidos))
        elif rule.get('type') == 'forbid_card_type_cost_gte':
            invalidos = sorted({c.code for c in cards
                                if c.card_type == rule['card_type']
                                and c.cost >= rule['cost_gte']})
            if invalidos:
                erros.append(f"{leader.code}: {rule['card_type']} de custo "
                             f"{rule['cost_gte']}+ proibidos: " + ', '.join(invalidos))
    return len(erros) == 0, erros


# Cache de CardData por código de carta -- garante referência compartilhada
# entre todas as cópias da mesma carta em qualquer GameState (ver
# _make_card e Card.__deepcopy__). Não é limpo entre partidas: CardData é
# imutável e idêntico para o mesmo código em qualquer contexto, então
# manter o cache ao longo de todo o processo é seguro e só economiza
# trabalho repetido.
_CARD_DATA_CACHE: dict = {}
# Cache de imagens: code -> URL da imagem (preenchido por load_cards_db)
_CARD_IMAGE_CACHE: dict = {}


def _make_card(code: str, data: dict) -> Card:
    """Cria Card a partir do banco de dados, usando o effects_db para keywords."""
    effects = get_card_effects(code)
    alternate_names = tuple(
        name
        for rule in get_card_game_rules(code)
        if rule.get('type') == 'alternate_names'
        for name in rule.get('names', [])
    )

    # Keywords do banco ou do parse básico
    has_blocker      = data.get('has_blocker', False)
    has_rush         = data.get('has_rush', False)
    has_rush_character = data.get('has_rush_character', False)
    has_double_attack= data.get('has_double_attack', False)
    has_banish       = data.get('has_banish', False)
    has_trigger      = data.get('has_trigger', False)
    has_unblockable  = data.get('has_unblockable', False)

    # Enriquece com o banco de efeitos
    if 'passive' in effects:
        for step in effects['passive'].get('steps', []):
            a = step.get('action', '')
            if a == 'keyword_blocker':      has_blocker = True
            elif a == 'keyword_rush':       has_rush = True
            elif a == 'keyword_rush_character': has_rush_character = True
            elif a == 'keyword_double_attack': has_double_attack = True
            elif a == 'keyword_banish':     has_banish = True
            elif a == 'keyword_trigger':    has_trigger = True
            elif a == 'keyword_unblockable': has_unblockable = True

    # Keywords CONDICIONAIS a [DON!! ×N]: só valem com N DON anexados.
    # Guardadas em dict {keyword: don_req}; a Card decide na hora se está ativa.
    don_cond_keywords = {}
    if 'don_conditional_keywords' in effects:
        for step in effects['don_conditional_keywords'].get('steps', []):
            a = step.get('action', '')
            req = step.get('don_requirement', 1)
            kw = a.replace('keyword_', '')
            don_cond_keywords[kw] = req

    # Campos extras detectados pelo banco ou pelo texto
    t = data.get('text', '').lower()
    is_searcher   = ('look at' in t or 'search your deck' in t or 'add up to' in t)
    has_start_of_game = 'at the start of the game' in t
    has_on_play_ko = 'on play' in t and ('k.o.' in t or 'trash' in t) and 'draw' not in t
    has_bounce    = 'return' in t and 'hand' in t
    has_rest_effect = 'rest' in t and 'opponent' in t
    has_power_minus = '-' in t and 'power' in t and 'opponent' in t
    trash_opp_char = 'opponent' in t and ('trash' in t or 'k.o.' in t) and 'on play' in t

    import re as _re
    raw_draw = (t.count('draw 1') + t.count('draw 2') * 2 +
                t.count('draw 3') * 3 + t.count('draw a card'))
    draw_then_trash = 0
    draw_condition  = 'always'
    m = _re.search(r'draw\s+(\d)\s+cards?.*?trash\s+(\d)\s+card', t)
    if m:
        raw_draw = int(m.group(1))
        draw_then_trash = int(m.group(2))
        lm = _re.search(r'if you have\s+(\d+)\s+or less life', t)
        if lm:
            draw_condition = f'life<={lm.group(1)}'

    # Cache de CardData por código: garante que TODAS as cópias da mesma
    # carta (em qualquer GameState, qualquer deepcopy) compartilham a
    # MESMA instância de CardData -- sem isto, cada chamada de _make_card
    # criaria um CardData novo e o ganho de deepcopy seria parcial (cada
    # Card ainda apontaria para um objeto distinto, mesmo que do mesmo
    # código, perdendo a vantagem de referência compartilhada).
    cache_key = code
    card_data = _CARD_DATA_CACHE.get(cache_key)
    if card_data is None:
        card_data = CardData(
            code=code,
            name=data.get('name', code),
            card_type=data.get('type') or 'CHARACTER',
            color=data.get('color', ''),
            cost=data.get('cost', 0),
            power=data.get('power', 0),
            counter=data.get('counter', 0),
            life=data.get('life', 0),
            sub_types=data.get('sub_types', ''),
            attribute=data.get('attribute', ''),
            card_text=data.get('text', ''),
            has_trigger=has_trigger,
            don_cond_keywords=tuple(don_cond_keywords.items()) if don_cond_keywords else None,
            is_searcher=is_searcher,
            draw_power=raw_draw,
            draw_then_trash=draw_then_trash,
            draw_condition=draw_condition,
            has_on_play_ko=has_on_play_ko,
            has_bounce=has_bounce,
            has_rest_effect=has_rest_effect,
            has_start_of_game=has_start_of_game,
            has_power_minus=has_power_minus,
            trash_opp_char=trash_opp_char,
            alternate_names=alternate_names,
        )
        _CARD_DATA_CACHE[cache_key] = card_data

    return Card(
        data=card_data,
        has_rush=has_rush,
        has_rush_character=has_rush_character,
        has_blocker=has_blocker,
        has_double_attack=has_double_attack,
        has_banish=has_banish,
        has_unblockable=has_unblockable,
    )


def build_real_deck(deck_name: str, deck_url: str,
                    df_raw: pd.DataFrame, cards_db: dict) -> Optional[tuple]:
    rows = df_raw[df_raw['deck_url'] == deck_url]
    if rows.empty:
        return None

    leader = None
    cards  = []

    for _, row in rows.iterrows():
        code = str(row['card_code'])
        qty  = int(row['qty'])
        data = cards_db.get(code, {})
        if not data:
            continue

        card = _make_card(code, data)

        if card.card_type == 'LEADER':
            leader = card
        else:
            for _ in range(qty):
                cards.append(deepcopy(card))

    if leader is None:
        leader = Card(data=CardData(code='UNK', name=deck_name, card_type='LEADER',
                                     color='', power=5000, life=5))

    return leader, cards, None  # start_stage detectada no setup


# ===========================================================================
# DecisionEngine — IA de decisão
# ===========================================================================


# ============================================================================
# NOVO DecisionEngine — Análise probabilística completa
# Substitui a classe DecisionEngine no decision_engine.py
# ============================================================================

class GameAnalyzer:
    """
    Analisador de estado do jogo — calcula probabilidades e avalia posições.
    Usado pelo DecisionEngine para tomar decisões informadas.
    """

    def __init__(self, me: 'GameState', opp: 'GameState'):
        self.me  = me
        self.opp = opp
        # Cache de _lethal_search por INSTANCIA (fase D, 24/07 -- achado por
        # profiling real: can_lethal_this_turn chamado 2979x num unico
        # main_phase, 5M+ chamadas recursivas de search_alloc, ~100s de 104s
        # do turno inteiro). Seguro: dentro do tempo de vida de UMA instancia
        # de GameAnalyzer, self.me/self.opp NUNCA sao mutados (e sempre
        # passada como o MESMO `engine.analyzer` reusado por todos os
        # candidatos de uma unica chamada de _generate_and_score_actions --
        # ver score_attack_target/analysis_priority chamando
        # can_lethal_this_turn() uma vez por candidato de ataque, sempre com
        # o MESMO resultado dentro dessa janela). None = ainda nao calculado.
        self._lethal_search_cache = None

    # ── Análise do deck (perfil early/mid/late) ──────────────────────────────

    def deck_profile(self) -> str:
        """
        Determina se o deck é early, mid ou late game
        baseado na curva de custo das cartas no campo e mão.
        """
        all_cards = self.me.field_chars + self.me.hand
        if not all_cards:
            return 'mid'
        avg_cost = sum(c.cost for c in all_cards) / len(all_cards)
        if avg_cost <= 2.5:   return 'early'
        elif avg_cost <= 5.0: return 'mid'
        else:                 return 'late'

    def game_phase(self) -> str:
        """
        FASE DA PARTIDA pelos DON na mesa (documento pág. 3):
        Early (0-4 DON), Mid (5-8), Late (9-10).
        É o MOMENTO da partida, não o tipo do deck.
        """
        don_total = self.me.don_available + self.me.don_rested
        if don_total <= 4:   return 'early'
        elif don_total <= 8: return 'mid'
        else:                return 'late'

    def deck_profile_type(self) -> str:
        """
        PERFIL do deck (aggressive/control/midrange) a partir do censo do deck
        completo. Diferente de deck_profile() (que é por curva de mão+campo).
        Usa o deck guardado em me.full_deck_census (setado no setup).
        """
        census = getattr(self.me, 'full_deck_census', None)
        if not census:
            return 'midrange'  # sem censo, neutro
        from optcg_engine.deck_census import deck_profile as classify
        return classify(census)['profile']

    def don_field_curve_scale(self) -> float:
        """
        Fator que escala o valor de DON parado no campo (`EVAL_WEIGHTS
        ['don_field']`) pela curva do PRÓPRIO deck -- calibragem dinâmica
        (bloco 530, pedido do usuário: "vamos fazer para o motor inteiro"),
        mesma família de `_leader_ability_centrality`: analítico, deriva
        da composição REAL do deck, zero self-play novo. Reusa
        `deck_profile_type()` (já existente, calibrado com dados reais do
        Limitless, não medido por partida simulada).

        Deck AGRESSIVO (curva baixa) já gasta o DON assim que compra --
        guardar DON parado no campo sem jogar vale menos pra esse plano.
        Deck CONTROLE (curva alta) precisa acumular DON pra bancar as
        cartas caras -- guardar DON vale mais. MIDRANGE ou sem censo
        disponível (ex: teste isolado) fica neutro (1.0, comportamento de
        sempre) -- não inventa direção sem dado real.
        """
        profile = self.deck_profile_type()
        if profile == 'aggressive':
            return 0.7
        if profile == 'control':
            return 1.3
        return 1.0

    def deck_lacks_removal_tools(self) -> bool:
        """
        Achado real 10/08 (auditoria do líder Sanji OP12-041, bloco 484 --
        pedido do usuário pra investigar mais fundo depois de 2 experimentos
        A/B não decisivos: reclassificar profile e evitar postura CONTROL
        de vez, nenhum dos dois moveu o winrate de forma consistente).
        `deck_profile_type()` classifica pela CURVA de custo (aggressive/
        control/midrange), sem saber se o deck tem remoção de verdade --
        um deck com 64% de Eventos baratos de busca/compra (Sanji) e só um
        punhado de remoção real cai em 'control' só por ter algumas cartas
        caras, mas o PLANO real dele é achar a resposta certa via busca,
        não remover ameaças. Sem isso, a postura CONTROL (ver avaliar_carta)
        só recompensava ko/bounce/rest -- remoção que esse tipo de deck não
        tem -- e não dava nenhum crédito pra busca/compra, que é a
        ferramenta de controle real dele.

        Genérico via censo do deck (kos/is_removal/bounces vs is_searcher/
        draws, contados em populate_full_deck_knowledge), não hardcoded por
        líder -- qualquer deck com essa mesma assimetria (pouca remoção,
        muita seleção de carta) se beneficia, não só o Sanji.
        """
        census = getattr(self.me, 'full_deck_census', None)
        if not census:
            return False
        removal = census.get('removal_tools', 0)
        selection = census.get('card_selection_tools', 0)
        return selection > 0 and removal < selection * 0.6

    # ── Potencial ofensivo ───────────────────────────────────────────────────

    def my_attack_power(self) -> int:
        """Poder total de ataque disponível (sem DON)."""
        # Achado real 03/08 (mesma investigacao do 'cannot attack' de
        # lider ignorado): faltava is_attack_locked_self aqui -- um lider
        # com "This Leader cannot attack" (Vegapunk, Iceburg, etc.) tinha
        # o poder dele somado ao potencial ofensivo mesmo sem poder atacar
        # de verdade.
        pode_lider_atacar = (not self.me.leader.rested
                             and not self.me.cannot_attack_leader_this_turn
                             and not is_attack_locked_self(self.me.leader, self.me, self.opp))
        total = attack_time_power(self.me.leader, self.opp) if pode_lider_atacar else 0
        for c in self.me.field_chars:
            if character_can_attack_now(c, self.me, self.opp):
                total += attack_time_power(c, self.opp)
        return total

    def my_available_don(self) -> int:
        return self.me.don_available

    def max_don_boost(self) -> int:
        """Máximo de boost de poder com DON disponível."""
        return self.me.don_available * 1000

    # ── Potencial defensivo do oponente ──────────────────────────────────────

    def opp_counter_potential(self) -> int:
        """
        Potencial de counter do oponente: soma REAL do stat impresso
        (counter) + efeitos [Counter] parseados (buff_power em
        effects.counter.steps, respeitando as condições do efeito contra o
        estado real dele) das cartas da mão. As cartas da mão dele existem
        como objetos Card tanto na simulação quanto no caminho do bot
        (SoloVSelf) — soma REAL, não estimativa estatística (a estimativa
        antiga por tamanho de mão devolvia 0 para mão de 2 cartas mesmo com
        2 Kobys de counter 2000; visto em partida real 06/07).

        Achado 07/07: cartas como Ground Death e "...Never Existed..." têm
        counter=0 no stat impresso — o bônus delas é um efeito [Counter]
        Activate condicional (+4000, ex: trash_gte 10 / leader_is imu), que
        esse cálculo ignorava por completo. Isso fazia o bot atacar
        empatado sem margem e falhar contra elas (Teach 5000 e depois 9000
        vs Ethanbaron bufado, mesma partida, duas vezes).

        Ao vivo a mão já chega mascarada (server.py troca cartas não
        reveladas por placeholders antes do GameState existir), então somar
        `self.opp.hand` direto já é seguro — nada muda aqui pra esse
        caminho. O self-play interno (OPTCGMatch/ReplayMatch) NUNCA passou
        por essa máscara (usa os objetos Card reais dos dois lados o tempo
        todo, porque a mecânica real precisa deles) — pedido do usuário
        (24/07): aproximar o self x self do ao vivo sem duplicar motor.
        `opp.self_play_info_hidden` (atributo dinâmico, default False via
        getattr — NUNCA setado hoje em lugar nenhum, só o futuro simulador
        self x self vai ligar) restringe a soma real às cartas já
        REVELADAS (`known_hand_cards()`) e completa o resto com a MESMA
        estimativa estatística que `opp_counter_chunks_for_lethal` já usa
        de forma conservadora — aqui, porém, soma um valor esperado (não
        zera), e usa a densidade REAL da decklist do oponente quando
        disponível (mesmo lookup usado no guard de buff de
        `resolve_optional_effect`, sim_bridge.py).
        """
        # `hidden_information_masked` e o sinal REAL ja ligado pelo caminho
        # ao vivo (server.py:_dto_to_gs, setado pro GameState do oponente
        # sempre que a mao dele vem mascarada com placeholders UNKNOWN-000)
        # -- ate 09/08 esta funcao so olhava `self_play_info_hidden`, um
        # atributo irmao que NUNCA e setado em lugar nenhum do projeto (nem
        # aqui nem no self-play), entao a estimativa estatistica abaixo
        # (por densidade de counter do deck do lider) nunca rodava de
        # verdade: toda carta oculta na mao do oponente ao vivo contava
        # como counter=0 na defesa do lider. `self_play_info_hidden`
        # continua respeitado pra permitir o self-play/gauntlet ligar essa
        # mascara manualmente no futuro (smoke_fast.py ja testa esse caso)
        # sem depender do caminho ao vivo.
        known_only = (getattr(self.opp, 'self_play_info_hidden', False)
                      or getattr(self.opp, 'hidden_information_masked', False))
        hand = self.opp.known_hand_cards() if known_only else self.opp.hand
        ee = EffectExecutor(self.opp, self.me)   # perspectiva do DONO da carta
        total = 0
        for c in hand:
            total += getattr(c, 'counter', 0)
            counter_block = get_card_effects(c.code).get('counter', {})
            steps = counter_block.get('steps', [])
            if not steps:
                continue
            if ee._check_conditions(counter_block.get('conditions', {}), c):
                total += sum(s.get('amount', 0) for s in steps
                            if s.get('action') == 'buff_power')
        if not known_only:
            return total

        n_unknown = max(0, len(self.opp.hand) - len(hand))
        from optcg_engine.counter_estimation import estimate_opp_counter
        from optcg_engine.sim_bridge import deck_cards_for_leader
        deck1000 = deck2000 = None
        _deck_opp = (deck_cards_for_leader(self.opp.leader.code)
                     if self.opp.leader is not None else None)
        if _deck_opp:
            deck1000 = sum(1 for c in _deck_opp if getattr(c, 'counter', 0) == 1000)
            deck2000 = sum(1 for c in _deck_opp if getattr(c, 'counter', 0) >= 2000)
            visiveis = list(self.opp.trash) + list(self.opp.field_chars) + list(hand)
            if self.opp.field_stage:
                visiveis.append(self.opp.field_stage)
            for c in visiveis:
                cv = getattr(c, 'counter', 0)
                if cv == 1000 and deck1000 > 0:
                    deck1000 -= 1
                elif cv >= 2000 and deck2000 > 0:
                    deck2000 -= 1
        est = estimate_opp_counter(n_unknown, deck_counter_1000=deck1000,
                                    deck_counter_2000=deck2000)
        return total + est['expected_counter_value']

    def opp_counter_chunks_for_lethal(self) -> list[int]:
        """
        Counter disponivel para analise de lethal GARANTIDO sem espiar a mao
        oculta. Cartas reveladas contam pelo valor real; slots desconhecidos
        contam como possiveis counters de 2000. Isso e conservador de proposito:
        se a mao e desconhecida, nao podemos chamar de lethal garantido.
        """
        known = self.opp.known_hand_cards()
        unknown_hand_size = max(0, len(self.opp.hand) - len(known))

        # Cartas reveladas: valor real de counter (inclui 0 para cartas sem counter)
        chunks = [c.counter for c in known]
        # Slots desconhecidos: não sabemos o counter — tratamos como 0 para
        # não inflar a defesa do oponente com suposições. O cálculo de lethal
        # é sobre o que podemos GARANTIR, não sobre o que o oponente pode ter.
        # (Se o oponente tiver counters ocultos ele escolherá usar, mas não
        # sabemos quantos são — ignorar é conservador para o atacante.)
        # Ignoramos slots ocultos: nenhum chunk adicional.
        _ = unknown_hand_size  # reservado para futura estimativa probabilística
        return sorted(chunks)

    def opp_counter_in_hand(self) -> int:
        """Counter real do oponente (se visível — normalmente 0 em simulação)."""
        return self.opp.counter_in_hand()

    def opp_has_active_don_for_events(self) -> bool:
        """Oponente tem DON para ativar eventos de defesa?"""
        return self.opp.don_available >= 1

    def opp_blocker_count(self) -> int:
        """Quantos blockers ativos o oponente tem."""
        return len(self.opp.blockers_active())

    def opp_attack_count(self) -> int:
        """Quantos personagens o oponente pode atacar no próximo turno."""
        count = sum(1 for c in self.opp.field_chars if not c.rested)
        # Achado real 03/08: o lider do oponente entrava na conta so por
        # nao estar restado, ignorando "This Leader cannot attack"
        # (Vegapunk, Iceburg, etc.) -- superestimava a ameaca de ataque
        # dele (bot ficava defensivo demais contra um lider que fisicamente
        # nao pode atacar).
        if not self.opp.leader.rested and not is_attack_locked_self(self.opp.leader, self.opp, self.me):
            count += 1
        return count

    # ── Análise de lethality ─────────────────────────────────────────────────

    def can_lethal_this_turn(self) -> bool:
        ok, _alloc, _refs = self._lethal_search()
        return ok

    def can_lethal_this_turn_alloc(self):
        """
        Como can_lethal_this_turn(), mas expoe a alocacao de DON que a busca
        encontrou pra certificar o lethal (diagnostico, 19/07 -- comparar
        contra o DON que a execucao real/simulada de fato anexa via
        don_needed_for_attack). Retorna (ok, [(attacker_ref, don_extra), ...])
        -- lista vazia/None se ok=False. attacker_ref e' 'leader' ou o Card do
        field_chars, na MESMA ordem que _lethal_search monta `ataques`.
        """
        ok, alloc, refs = self._lethal_search()
        if not ok:
            return False, None
        return True, list(zip(refs, alloc))

    def _lethal_search(self):
        """
        Posso GARANTIR a vitória neste turno, mesmo no pior caso de defesa do
        oponente (ele escolhe livremente blocker/counter por ataque, na ordem
        que mais o favorece)?

        Cacheada por instancia (fase D, 24/07) -- ver comentario em
        __init__. Chamadas repetidas na MESMA instancia (mesmo estado
        me/opp, nunca mutado durante a vida da instancia) retornam o
        resultado ja calculado em vez de refazer a busca recursiva inteira.

        Antes, esta funcao so contava NUMERO de ataques >= vida+1, ignorando
        poder/blocker/counter -- superestimava lethal contra qualquer
        oponente com blocker ou counter na mao. Agora simula o pior caso real:
          1. Lista os poderes de ataque disponiveis (com DON ja anexado via
             effective_power); double attack conta como 2 hits do MESMO poder
             (e o MESMO ataque -- um unico Blocker ou Counter resolve os 2
             hits dele, nao 2 blockers/counters separados).
          2. Ataques [Unblockable] NUNCA podem ser bloqueados -- sempre vao
             direto pro Leader.
          3. Os blocker do oponente (N ativos) desviam ate N ataques
             BLOQUEAVEIS -- ele escolhe bloquear os de MAIOR poder primeiro
             (sao os mais caros/dificeis de cobrir so com counter), pior caso
             pra mim.
          4. O que sobra (nao bloqueado) precisa ser coberto por counter
             conhecido/estimado do oponente. Cartas reveladas contam pelo
             valor real; slots ocultos usam estimativa por tamanho da mao.
             Sobrevive ao ataque de poder P se consegue somar counter total
             >= P - leader_power + 1.
             Distribui os counters da mao greedy: cobre primeiro os ataques
             que precisam de MENOS counter (maximiza quantos ataques
             sobrevive com o estoque de counter que tem).
          5. Lethal garantido = mesmo nessa defesa otima do oponente, a vida
             dele chega a 0 E ainda resta pelo menos 1 hit que conecta
             (regra: receber dano com 0 vidas = derrota).
        """
        if self._lethal_search_cache is not None:
            return self._lethal_search_cache

        # Taunt (Eustass Kid OP01-051, Captain John OP17-044): enquanto
        # ativo, NENHUM ataque meu pode mirar o Leader do oponente --
        # lethal via dano de vida fica impossivel, nao importa o poder
        # disponivel. Fonte unica: mesma active_taunt_character usada na
        # geracao real de acoes de ataque (_generate_and_score_actions/
        # _generate_attach_don_actions), REGRA_SEM_DUPLICACAO.
        if active_taunt_character(self.opp, self.me) is not None:
            self._lethal_search_cache = (False, None, None)
            return self._lethal_search_cache

        opp_life = self.opp.life_count()
        leader_power = self.opp.leader.effective_power(False)

        # Ataques disponiveis: (poder_base, eh_unblockable, hits). DON
        # disponivel ainda pode ser distribuido entre eles para garantir lethal.
        ataques = []
        attacker_refs = []
        if not self.me.cannot_attack_leader_this_turn and not self.me.leader.rested and not is_attack_locked_self(self.me.leader, self.me, self.opp):
            ataques.append((attack_time_power(self.me.leader, self.opp),
                            self.me.leader.has_unblockable or self.me.leader.unblockable_this_turn,
                            1))
            attacker_refs.append(self.me.leader)
        for c in self.me.field_chars:
            if character_can_attack_now(c, self.me, self.opp):
                hits = 2 if c.is_double_attack() else 1
                ataques.append((attack_time_power(c, self.opp),
                                c.has_unblockable or c.unblockable_this_turn,
                                hits))
                attacker_refs.append(c)

        if not ataques:
            self._lethal_search_cache = (False, None, None)  # sem atacantes disponiveis, nunca fecha o jogo
            return self._lethal_search_cache
        counters_base = sorted(self.opp_counter_chunks_for_lethal())
        n_blockers = len(self.opp.blockers_active())
        don_total = max(0, self.me.don_available)
        target_hits = opp_life + 1 if opp_life > 0 else 1

        def hits_after_best_defense(powered_attacks):
            unblockable = [a for a in powered_attacks if a[1]]
            bloqueaveis = sorted([a for a in powered_attacks if not a[1]],
                                 key=lambda a: -a[0])
            candidatos_dano = unblockable + bloqueaveis[n_blockers:]
            if not candidatos_dano:
                return 0

            sobrou_counters = list(counters_base)
            conecta = []
            for power, _is_unblockable, hits in sorted(candidatos_dano, key=lambda a: a[0]):
                necessario = power - leader_power + 1
                if necessario <= 0:
                    continue
                soma = 0
                usados = []
                for ctr in sobrou_counters:
                    if soma >= necessario:
                        break
                    soma += ctr
                    usados.append(ctr)
                if soma >= necessario:
                    for u in usados:
                        sobrou_counters.remove(u)
                else:
                    conecta.append((power, hits))
            return sum(h for _, h in conecta)

        # dons_found e' preenchido com a alocacao vencedora assim que
        # search_alloc acha uma (mesma recursao/logica de sempre -- so anexa
        # a captura da alocacao de DON por cima, sem mudar o resultado bool).
        dons_found = []

        def search_alloc(idx: int, don_left: int, current: list, dons: list):
            if idx == len(ataques):
                if hits_after_best_defense(current) >= target_hits:
                    dons_found[:] = dons
                    return True
                return False

            base_power, unblockable, hits = ataques[idx]
            # Tenta mais DON primeiro; se houver lethal garantido, acha cedo.
            for don in range(don_left, -1, -1):
                if search_alloc(
                    idx + 1,
                    don_left - don,
                    current + [(base_power + don * 1000, unblockable, hits)],
                    dons + [don],
                ):
                    return True
            return False

        ok = search_alloc(0, don_total, [], [])
        self._lethal_search_cache = (ok, (list(dons_found) if ok else None), attacker_refs)
        return self._lethal_search_cache

    # ── Análise de defesa ────────────────────────────────────────────────────

    def opp_lethal_threat(self) -> float:
        """
        Probabilidade do oponente me finalizar no próximo turno.
        Considera atacantes, DON disponível, minha vida.
        """
        opp_attacks = self.opp_attack_count()
        my_life = self.me.life_count()
        my_blockers = len(self.me.blockers_active())
        my_counter  = self.me.counter_in_hand()

        if opp_attacks == 0:
            return 0.0

        # Oponente precisa de (my_life + 1) hits para me finalizar
        hits_needed = my_life + 1
        available_hits = opp_attacks

        if available_hits < hits_needed:
            return 0.0

        # Chance base
        prob = max(0.0, (available_hits - hits_needed + 1) / max(available_hits, 1))

        # Meus blockers reduzem a ameaça
        prob *= max(0.1, 1.0 - my_blockers * 0.2)

        # Meus counters reduzem a ameaça
        if my_counter >= 2000:
            prob *= 0.7
        elif my_counter >= 1000:
            prob *= 0.85

        return min(prob, 0.95)

    # ── Vale a pena salvar um personagem? ────────────────────────────────────

    def char_value_score(self, card: 'Card') -> float:
        """
        Valor de um personagem para a partida.
        Usado para decidir se vale gastar blocker/counter para salvar.
        """
        score = card.board_value() * 10.0

        effects = get_card_effects(card.code)

        # Tem efeito ativável que ainda não usou
        if 'activate_main' in effects:
            score += 20

        # Tem efeito de ataque
        if 'when_attacking' in effects:
            score += 15

        # É um blocker valioso
        if (card.has_blocker or card.blocker_this_turn) and self.me.life_count() <= 2:
            score += 30

        # Tem double attack
        if card.has_double_attack or card.double_attack_this_turn:
            score += 20

        return score

    # ── Análise do campo ─────────────────────────────────────────────────────

    def field_advantage(self) -> float:
        """
        Vantagem de campo: positivo = eu estou na frente.
        Considera poder total, quantidade de cartas e efeitos.
        """
        my_score  = sum(c.board_value() for c in self.me.field_chars)
        opp_score = sum(c.board_value() for c in self.opp.field_chars)
        return my_score - opp_score

    def _effect_threat_weight(self, card: Card) -> float:
        """
        Peso de efeito/keyword que faz uma carta continuar relevante
        enquanto fica viva -- fonte ÚNICA usada tanto por
        `future_threat_value`/`critical_threats` (quanto essa carta AINDA
        pode produzir, pro board do oponente) quanto por
        `score_attack_target` (quanto vale MATAR essa carta agora, pro
        alvo de um ataque). Extraído em 09/08 (auditoria de cobertura da
        pontuação dinâmica, bloco 475): as duas leituras respondiam à
        MESMA pergunta ("esse corpo é ameaça de efeito?") com pesos e
        conjuntos de trigger diferentes, sem reuso -- exatamente o tipo de
        duplicação que `REGRA_SEM_DUPLICACAO.md` pede pra eliminar. Cada
        chamador ainda soma bônus próprios que só fazem sentido no
        contexto dele (ex: `on_ko` conta como "valor que ainda produz"
        aqui, mas como RISCO pra quem for matar a carta -- ver o `-20`
        específico em `score_attack_target`).
        """
        effects = get_card_effects(card.code)
        weight = 0.0
        future_blocks = {
            'activate_main': 50, 'when_attacking': 45, 'opp_turn': 45,
            'your_turn': 30, 'end_of_turn': 30, 'start_of_turn': 30,
            'on_opponent_attack': 40, 'passive': 25, 'continuous': 25,
            'on_ko': 15,
        }
        for trigger, w in future_blocks.items():
            if effects.get(trigger):
                weight += w
        if card.has_blocker or card.blocker_this_turn:
            weight += 45
        if card.has_double_attack or card.double_attack_this_turn:
            weight += 65
        return weight

    def future_threat_value(self, card: Card) -> float:
        """Valor que o corpo ainda pode produzir; On Play ja resolvido nao conta."""
        power_term = max(0.0, (card.power - self.me.leader.power) / 1000.0 * 12.0)
        return power_term + self._effect_threat_weight(card)

    def critical_threats(self) -> list:
        """
        Identifica AMEAÇAS CRÍTICAS no board do oponente (documento nível 3).
        Uma carta é ameaça crítica se:
        - poder alto (>= 6000), OU
        - tem efeito perigoso (gera vantagem recorrente, blocker que trava ataque),
        - (a ameaça de lethal é tratada à parte por opp_lethal_threat).
        Retorna a lista de cartas-ameaça, da mais perigosa para a menos.
        """
        ameacas = []
        for c in self.opp.field_chars:
            peso = self.future_threat_value(c)
            if peso >= 45:
                ameacas.append((peso, c))
        ameacas.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in ameacas]

    def opp_combo_threat(self) -> dict:
        """
        Ameaça de VIRADA por reanimação em massa do trash do oponente (achado
        07/07, HANDOFF blocos 99-100: Five Elders reanima 4-5 corpos fortes
        de uma vez e fecha o jogo — nenhum fix tático daquela sessão atacava
        isso porque `critical_threats()` só olha o board ATUAL, nunca o que
        o TRASH dele pode virar).

        Não depende de decklist do oponente (fog of war real): só olha
        cartas já PÚBLICAS (líder sempre visível desde o T1, board dele
        visível assim que jogado) e os efeitos delas — `get_card_effects` é
        estático por código, não exige saber o deck inteiro. Mesma conta do
        eixo `reanimation_bottleneck` de `deck_profile.py` (min(capacidade,
        combustível qualificado)), só que aplicada ao OPONENTE em vez do
        próprio deck do bot.

        Retorna {'magnitude': int, 'threat_power': float, 'sources': [...]}.
        `magnitude` = maior quantidade de corpos que uma única fonte
        conseguiria trazer de volta HOJE (combustível já qualificado no
        trash, não a capacidade teórica da carta). `threat_power` = soma de
        `board_value()` desses corpos (estimativa de quanto o board dele
        pode virar).

        Achado real 11/08 (bloco 502, ao investigar 0% de gatilho no
        pool de decks atual, bloco 498): a única carta do banco que
        dispara este padrão (Five Elders OP13-082) trasha A SI MESMA
        como parte do próprio [Activate: Main], antes de reanimar --
        tudo no mesmo turno em que é jogada+ativada (custo barato,
        rest_don+trash_from_hand). Isso significa que ela NUNCA fica
        visível em `field_chars` num turno em que o oponente ainda
        poderia reagir -- por design da própria carta, resolve-se
        atomicamente antes do próximo turno do oponente. Escaneando
        `self.opp.known_hand_cards()` (cartas na mão do oponente já
        REVELADAS a mim por efeito de busca/peek -- mesma infra de
        fairness usada por `opp_counter_potential`, não é informação
        que o bot não deveria ter) cobre o único cenário onde ainda
        existe janela real de aviso prévio: a carta sentada na mão
        aguardando DON/custo, revelada antes de ser jogada. Não resolve
        o caso em que ela nunca é revelada (fog of war genuíno) nem o
        caso em que é jogada+ativada no mesmo turno em que se torna
        pagável sem nunca ter sido revelada antes -- esses continuam
        estruturalmente sem aviso prévio possível.
        """
        sources = []
        pool = [self.opp.leader] + list(self.opp.field_chars) + list(self.opp.known_hand_cards())
        for c in pool:
            if c is None:
                continue
            effects = get_card_effects(c.code)
            for block in effects.values():
                if not isinstance(block, dict):
                    continue
                for s in block.get('steps', []):
                    if s.get('action') not in ('play_from_trash', 'add_from_trash'):
                        continue
                    count = s.get('count', 1)
                    if count < 2:
                        continue   # só "em massa" -- 1 corpo de volta não é a virada que procuramos
                    ft = (s.get('filter_type') or '').lower()
                    peq = s.get('power_eq')
                    fuel = [tc for tc in self.opp.trash
                            if tc.card_type == 'CHARACTER'
                            and (not ft or ft in (tc.sub_types or '').lower())
                            and (peq is None or tc.power == peq)]
                    if s.get('distinct_names'):
                        vistos = set()
                        fuel = [tc for tc in fuel
                                if tc.name not in vistos and not vistos.add(tc.name)]
                    if not fuel:
                        continue
                    fuel_ordenado = sorted(fuel, key=lambda tc: tc.board_value(), reverse=True)
                    qualificado = fuel_ordenado[:count]
                    sources.append({
                        'source': c.code,
                        'count_disponivel': len(qualificado),
                        'power_estimado': sum(tc.board_value() for tc in qualificado),
                    })
        if not sources:
            return {'magnitude': 0, 'threat_power': 0.0, 'sources': []}
        return {
            'magnitude': max(s['count_disponivel'] for s in sources),
            'threat_power': max(s['power_estimado'] for s in sources),
            'sources': sources,
        }

    def _leader_ability_centrality(self) -> float:
        """
        Fator ESTRUTURAL [0.3..1.0] de quanto a habilidade [Activate: Main]
        do líder é CENTRAL pro plano do PRÓPRIO deck -- não calibrado por
        self-play, derivado direto da composição real do deck
        (`full_deck_census`, já computado 1x por partida em
        `populate_full_deck_knowledge`, zero custo extra de simulação).

        Achado real 14/08 (pedido do usuário: "aumentar o N não vai
        resolver... precisamos de algo pra fazer com precisão essa
        calibragem dinâmica"): a calibração isolada de `leader_plan_
        alignment` via self-play (rodadas dos blocos 527/528) deu sinal
        inconsistente entre líderes -- Mihawk oscilou de sinal entre
        candidatos, sem tendência estável. Causa provável: não existe UM
        peso global certo, porque o quanto "usar a habilidade do líder"
        importa genuinamente VARIA por deck (uma habilidade de compra é
        vital pro deck que não tem outra fonte de vantagem de carta, e
        quase irrelevante pro deck que já tem 8 buscadores). Tentar achar
        essa resposta por média estatística entre decks incompatíveis é
        estruturalmente ruidoso, não importa quantas amostras -- a
        resposta certa não é uma constante. Este método resolve a
        variação ANALITICAMENTE (a partir do que o deck realmente tem),
        deixando pro peso global em EVAL_WEIGHTS só a sensibilidade geral
        (1 escalar grosseiro, não 1 número fino por deck).

        Único eixo coberto por ora (mais comum, com dado já disponível
        sem inventar census novo): habilidade de VANTAGEM DE CARTA
        (draw/look_top_deck/add_to_hand) -- escala pela ESCASSEZ de
        OUTRAS fontes do mesmo recurso no deck (`full_deck_census
        ['card_selection_tools']`, já conta buscadores/compra de
        `populate_full_deck_knowledge`). Zero outras fontes = 1.0
        (totalmente central, o deck depende dela). Muitas outras fontes =
        satura em 0.3 (nunca zera -- usar a própria carta sempre vale
        alguma coisa, só menos crítico). Outros tipos de efeito (ramp,
        play_card grátis, etc.) ou sem `full_deck_census` disponível
        (ex: testes isolados sem passar por OPTCGMatch/ReplayMatch) caem
        no neutro 1.0 -- sem dado estrutural pra ajustar, não inventa.
        """
        leader = self.me.leader
        am = get_card_effects(leader.code).get('activate_main')
        if not am:
            return 1.0
        actions = [s.get('action') for s in am.get('steps', [])]
        if any(a in ('draw', 'look_top_deck', 'add_to_hand') for a in actions):
            census = getattr(self.me, 'full_deck_census', None) or {}
            outras_fontes = census.get('card_selection_tools', 0)
            return max(0.3, 1.0 / (1.0 + outras_fontes * 0.15))
        return 1.0

    def leader_plan_alignment(self) -> float:
        """
        Sinal de estado: o quanto o estado atual está alinhado com o plano
        do PRÓPRIO líder (pedido do usuário, 14/08 -- "colocar um peso com
        relação ao entendimento do efeito do líder"). Generaliza
        `wincon_ready`/`_derived_axes_value` (que só cobrem o eixo
        BOTTLENECK específico do perfil do deck, ex: reanimação) para
        QUALQUER líder com [Activate: Main], lendo o efeito genericamente
        via `get_card_effects` -- sem hardcode de nome/código de carta.
        Escala pelo fator ESTRUTURAL de `_leader_ability_centrality` --
        calibragem dinâmica por deck sem depender de self-play pra achar
        o valor certo (ver docstring de `_leader_ability_centrality`).

        Não reimplementa elegibilidade real da ação (isso é
        `_generate_and_score_actions`/`_should_activate_main`, fonte única
        de verdade sobre "pode ativar agora", contra REGRA_SEM_DUPLICACAO):
        aqui é só um SINAL aproximado pra avaliação de ESTADO, tolerante a
        imprecisão de propósito (mesma lição do achado de robustez a ruído
        do bloco 518/519 -- filtro grosseiro não precisa ser exato).

        0.0 se o líder não tem [Activate: Main] (mesma convenção N/A do
        decision_quality_report.py). 1.0 se já foi usada neste turno
        (plano JÁ executado). 0.5 se ainda não foi usada mas o custo
        (rest_don) já é pagável agora ("arma carregada", pronta pra
        disparar). 0.0 se o custo ainda não é pagável.

        ACHADO REAL (14/08, calibração isolada multi-âncora): custo
        `rest_self` NÃO recebe o crédito parcial de 0.5 -- 1a versão dava
        0.5 flat só por "lider ativo, custo pagável" pra QUALQUER tipo de
        custo, e isso regrediu Vivi (EB03-001, único âncora testado com
        `rest_self`) em -20pp/-15pp em 2 candidatos de peso, único líder
        que piorou nos dois. Causa: `rest_self` RESTA o próprio líder --
        ativar e atacar são MUTUAMENTE EXCLUSIVOS este turno (mesmo achado
        de `decision_quality_report.py`, bloco 489/Nefeltari Vivi), então
        "pronta pra ativar" não é um estado bom por si só como é pra
        `rest_don` (compatível com atacar também) -- o trade-off real já é
        decidido por `_score_activate_main` na hora certa, e dano/board já
        capturam o valor de atacar em vez de ativar. Só dá crédito quando
        a habilidade rest_self foi de fato USADA (1.0), nunca por estar
        só "pronta".

        [Activate: Main] é once-per-turn por regra do jogo (não depende
        de flag no JSON do parser) -- trata como tal incondicionalmente.
        """
        leader = self.me.leader
        am = get_card_effects(leader.code).get('activate_main')
        if not am:
            return 0.0
        centralidade = self._leader_ability_centrality()
        if getattr(leader, '_am_used_turn', -1) == self.me.turn:
            return 1.0 * centralidade
        costs = am.get('costs', [])
        if any(c.get('type') == 'rest_self' for c in costs):
            return 0.0
        for c in costs:
            if c.get('type') == 'rest_don' and self.me.don_available < c.get('count', 0):
                return 0.0
        return 0.5 * centralidade

    def analysis_priority(self) -> str:
        """
        PRIORIDADE DE ANÁLISE (documento) — cascata de INCLINAÇÃO.
        Retorna o modo dominante deste momento. A ordem é respeitada (o nível
        mais alto satisfeito comanda), mas é inclinação, não bloqueio: o loop
        de pontuação ainda considera o contexto, com pesos ajustados por este modo.

        1. LETHAL       — posso vencer neste turno (sempre vence, topo)
        2. DEFENSIVE    — posso morrer no próximo turno (e não tenho lethal)
        3. PREVENT_COMBO — oponente pode reanimar 2+ corpos do trash de uma
           vez (achado 07/07 HANDOFF 99/100 — Five Elders etc.), virando o
           jogo no próximo turno dele. Distinto de REMOVE_THREAT: a ameaça
           ainda não está no board, está no TRASH dele — ver opp_combo_threat.
        4. REMOVE_THREAT — existe ameaça crítica no board
        5. DEVELOP      — posso/devo desenvolver board
        6. ATTACK       — atacar líder (padrão)
        """
        if self.can_lethal_this_turn():
            return 'LETHAL'
        if self.opp_lethal_threat() > 0.6:
            return 'DEFENSIVE'
        if self.opp_combo_threat()['magnitude'] >= PREVENT_COMBO_MAGNITUDE_THRESHOLD:
            return 'PREVENT_COMBO'
        if self.critical_threats():
            return 'REMOVE_THREAT'
        # desenvolver cedo / sem pressão; senão, atacar
        don_total = self.me.don_available + self.me.don_rested
        if don_total <= 4 and self.me.hand:
            return 'DEVELOP'
        return 'ATTACK'

    def should_clear_field(self) -> bool:
        """
        Vale a pena limpar o campo do oponente?
        Sim se oponente tem cartas com efeitos importantes ou muitos atacantes.
        """
        opp_threats = 0
        for c in self.opp.field_chars:
            effects = get_card_effects(c.code)
            if any(t in effects for t in ('activate_main', 'when_attacking', 'on_ko')):
                opp_threats += 2
            else:
                opp_threats += 1
        return opp_threats >= 3 or self.opp_attack_count() >= 3


_KEYWORD_GRANTS = {
    'gain_blocker':        'has_blocker',
    'gain_rush':           'has_rush',
    'gain_rush_character': 'has_rush_character',
    'gain_double_attack':  'has_double_attack',
    'gain_banish':         'has_banish',
    'gain_unblockable':    'has_unblockable',
}


def apply_conditional_keyword_passives(gs: 'GameState', opp: 'GameState') -> None:
    """
    Liga keywords vindas de PASSIVA CONDICIONAL (ex: Mars OP13-091
    gain_blocker e Nusjuro OP13-080 gain_rush, ambos com trash_gte 7).
    _make_card so aplica keyword_* incondicional — essas NUNCA ligavam,
    entao o engine nao via o Mars como blocker nem dava Rush ao Nusjuro
    mesmo com o trash cheio (achado real 12/07, partida 23.41.50 — duas
    reclamacoes do usuario com a mesma causa raiz).

    GRANT-ONLY e idempotente: as condicoes deste padrao (trash_gte) so
    crescem durante a partida; nao ha revogacao. Chamada barata (cartas
    visiveis x lookup cacheado) feita no __init__ do DecisionEngine —
    todo ponto de decisao passa por la.
    """
    ee = EffectExecutor(gs, opp)
    pool = list(gs.field_chars) + list(gs.hand)
    if gs.leader is not None:
        pool.append(gs.leader)
    if gs.field_stage is not None:
        pool.append(gs.field_stage)
    for c in pool:
        effects_c = get_card_effects(c.code)
        passive = effects_c.get('passive', {})
        steps = passive.get('steps', [])
        # "[Opponent's Turn] ... base power become N" vive sob a chave
        # 'opp_turn' (nao 'passive'), mas e uma aura ESTATICA igual as
        # outras desta funcao -- so o timing/tag no texto e diferente
        # (achado 19/07, OP15-070/OP15-071).
        opp_turn_block = effects_c.get('opp_turn', {})
        steps_opp_turn = opp_turn_block.get('steps', [])
        grants = [s for s in steps if s.get('action') in _KEYWORD_GRANTS]
        aura_grants = [s for s in steps if s.get('action') == 'grant_rush_character_type']
        # "All of your [Cor] Characters with a cost of N or more, other
        # than this Character, gain [Rush]" (achado 19/07, OP04-118) --
        # mesma ideia de aura_grants, mas filtro de COR+CUSTO (nao tipo) e
        # concede [Rush] nativo (has_rush), nao "Rush: Character".
        rush_aura_grants = [s for s in steps if s.get('action') == 'grant_rush_aura']
        # "All of your characters with a cost of N or more gain [Blocker]"
        # (achado 05/08, OP17-079 Monkey.D.Luffy LIDER) -- mesma ideia de
        # rush_aura_grants, mas SEM filtro de cor e concede has_blocker.
        blocker_aura_grants = [s for s in steps if s.get('action') == 'grant_blocker_aura']
        # "All of your [Nome] cards and this Character gain [Unblockable]/
        # [Double Attack]" -- aura por NOME (achado 19/07, OP15-070 Fuza/
        # OP15-071 Holly), SEMPRE inclui a propria carta-fonte (mesmo que
        # o nome dela nao bata o filtro -- "this Character" e explicito
        # no texto, distinto do filtro do grupo).
        named_kw_grants = [s for s in steps
                            if s.get('action') in ('grant_unblockable_aura_named',
                                                    'grant_double_attack_aura_named')]
        # "[Opponent's Turn] All of your [Nome] cards' base power and
        # this Character's base power become N" -- override PERMANENTE
        # de base power, so aplicado quando NAO e o turno do dono
        # (checado em effective_card_power via your_turn). Mesma carta
        # (OP15-070/071).
        base_power_group_grants = [s for s in steps_opp_turn
                                    if s.get('action') == 'set_base_power_group_opp_turn']
        # Keyword granted sob a tag "[Opponent's Turn]" (bloco 'opp_turn',
        # nao 'passive') -- achado 28/07 (bloco HANDOFF 393, auditoria
        # global de [Blocker] condicional): Pearl OP15-011 e Brook ST31-003
        # tem "[Opponent's Turn] If <condicao>, this Character gains
        # [Blocker]" -- o parser ja capturava certo sob 'opp_turn', mas
        # este loop so olhava 'steps' (de 'passive') pra _KEYWORD_GRANTS,
        # nunca 'steps_opp_turn'. Pratico: bloquear so importa durante o
        # turno do OPONENTE de qualquer forma (blockers_active() so e
        # consultado quando o oponente ataca), entao nao precisa de guarda
        # de timing extra alem da condicao do proprio bloco -- CONDICAO
        # PROPRIA (opp_turn_block), nao a de 'passive' (podem ser blocos
        # totalmente separados, sem 'passive' nenhum nestas 2 cartas).
        opp_turn_grants = [s for s in steps_opp_turn if s.get('action') in _KEYWORD_GRANTS]
        if opp_turn_grants and ee._check_conditions(opp_turn_block.get('conditions', {}), c):
            for s in opp_turn_grants:
                setattr(c, _KEYWORD_GRANTS[s['action']], True)
        if not (grants or aura_grants or rush_aura_grants or blocker_aura_grants
                or named_kw_grants or base_power_group_grants):
            continue
        if not ee._check_conditions(passive.get('conditions', {}), c):
            continue
        for s in grants:
            setattr(c, _KEYWORD_GRANTS[s['action']], True)
            if s.get('action') == 'gain_rush_character' and c.just_played:
                c.rush_character_only_this_turn = True
        for s in aura_grants:
            wanted = _norm_type_text(s.get('filter_type') or '')
            for target in gs.field_chars:
                if wanted and wanted in _norm_type_text(target.sub_types):
                    target.has_rush_character = True
                    if target.just_played:
                        target.rush_character_only_this_turn = True
        for s in rush_aura_grants:
            wanted_color = (s.get('color') or '').lower()
            cost_gte = s.get('cost_gte')
            for target in gs.field_chars:
                if s.get('exclude_self') and target is c:
                    continue
                if wanted_color and target.color.lower() != wanted_color:
                    continue
                if cost_gte is not None and target.cost < cost_gte:
                    continue
                target.has_rush = True
        for s in blocker_aura_grants:
            cost_gte_b = s.get('cost_gte')
            for target in gs.field_chars:
                if cost_gte_b is not None and target.cost < cost_gte_b:
                    continue
                target.has_blocker = True
        for s in named_kw_grants:
            campo = ('has_unblockable' if s['action'] == 'grant_unblockable_aura_named'
                     else 'has_double_attack')
            wanted_name = (s.get('filter_name') or '').lower()
            setattr(c, campo, True)
            for target in gs.field_chars:
                if target is c:
                    continue
                if wanted_name and wanted_name in target.name.lower():
                    setattr(target, campo, True)
        for s in base_power_group_grants:
            amount_bp = s.get('amount')
            wanted_name_bp = (s.get('filter_name') or '').lower()
            c.base_power_override_opp_turn = amount_bp
            for target in gs.field_chars:
                if target is c:
                    continue
                if wanted_name_bp and wanted_name_bp in target.name.lower():
                    target.base_power_override_opp_turn = amount_bp


class DecisionEngine:
    """
    Motor de decisão com análise probabilística completa.

    Toma decisões baseado em:
    - Perfil do deck (early/mid/late)
    - Análise de lethality (posso finalizar? oponente pode me finalizar?)
    - Distribuição ótima de DON
    - Ordem de ataque estratégica
    - Decisões de defesa (blocker vs counter)
    - Gerenciamento de mão e DON reservado
    """

    def __init__(self, me: 'GameState', opp: 'GameState'):
        self.me   = me
        self.opp  = opp
        self.analyzer = GameAnalyzer(me, opp)
        # Keywords de passiva condicional (trash_gte etc.) — ver docstring
        # de apply_conditional_keyword_passives. Nos DOIS lados: a decisão
        # também precisa saber que o blocker/rush DO OPONENTE está ativo.
        apply_conditional_keyword_passives(me, opp)
        apply_conditional_keyword_passives(opp, me)
        # Cache de posture() (achado real 02/08, investigando lentidao da
        # busca ao vivo): self.me/self.opp nunca sao reatribuidos depois do
        # __init__ (avaliar_carta so PONTUA, nunca executa/muta o board), e
        # posture() e chamada uma vez por CARTA avaliada dentro do MESMO
        # estado -- profiling de 1 decisao real mostrou ~3000 chamadas
        # redundantes (~1.3-1.4s de 5.8s totais) recomputando o MESMO
        # resultado sempre que a instancia nao muda de estado.
        self._posture_cache = None

    # ── Postura ──────────────────────────────────────────────────────────────

    def posture(self) -> str:
        """
        Postura do turno = PERFIL do deck (aggressive/control/midrange) +
        FASE da partida (early/mid/late pelos DON), conforme o documento.

        - Prioridades absolutas primeiro (lethal / evitar derrota).
        - Depois o PERFIL comanda:
          * aggressive: pressiona em todas as fases (busca dano cedo)
          * control: segue a fase (early desenvolve, mid controla, late finaliza)
          * midrange: equilíbrio pela fase

        Cacheada por instancia (ver __init__): self.me/self.opp sao fixos
        depois do construtor, entao o resultado nao muda entre chamadas da
        MESMA instancia -- so invalida ao criar um DecisionEngine novo pra
        um estado novo (padrao ja usado em qualquer ponto do engine que
        recria `engine = DecisionEngine(p, opp)` por simulacao/step).
        """
        if self._posture_cache is not None:
            return self._posture_cache
        resultado = self._posture_uncached()
        self._posture_cache = resultado
        return resultado

    def _posture_uncached(self) -> str:
        a = self.analyzer
        profile = a.deck_profile_type()   # aggressive / control / midrange
        phase   = a.game_phase()          # early / mid / late (pelos DON)
        my_life  = self.me.life_count()
        opp_life = self.opp.life_count()

        # ── Prioridades absolutas (independem de perfil/fase) ──
        if a.can_lethal_this_turn():
            return 'LETHAL'
        if a.opp_lethal_threat() > 0.6:
            return 'DEFENSIVE'

        # ── Perfil AGRESSIVO: pressiona em todas as fases ──
        # (deck de curva baixa com rush/buff ataca a vida desde cedo)
        if profile == 'aggressive':
            if my_life <= 1 and a.field_advantage() < 0:
                return 'DEFENSIVE'      # só recua se realmente prestes a morrer
            return 'AGGRESSIVE'

        # ── Perfil CONTROLE: segue o padrão das fases ──
        if profile == 'control':
            if phase == 'early':
                # desenvolver e preservar (board > dano)
                if opp_life <= 1: return 'AGGRESSIVE'
                return 'DEVELOP'
            if phase == 'mid':
                # disputar board, eliminar ameaças
                if my_life <= 1: return 'DEFENSIVE'
                if a.field_advantage() < -2: return 'CONTROL'
                if opp_life <= 2: return 'AGGRESSIVE'
                return 'CONTROL'
            # late: buscar letal / finalizar
            if my_life <= 2 and a.field_advantage() < 0: return 'DEFENSIVE'
            return 'AGGRESSIVE'

        # ── Perfil MIDRANGE: equilíbrio pela fase ──
        if opp_life <= 1:   return 'AGGRESSIVE'
        if my_life <= 1:    return 'DEFENSIVE'
        if phase == 'early':
            if a.field_advantage() < -2: return 'CONTROL'
            return 'DEVELOP'
        if phase == 'mid':
            if a.field_advantage() < -3: return 'CONTROL'
            if opp_life <= 2: return 'AGGRESSIVE'
            return 'MIDRANGE'
        # late
        return 'AGGRESSIVE'

    # ── Avaliação de cartas ──────────────────────────────────────────────────

    def _counter_stat_bonus(self, card: 'Card', life_mult: bool = True) -> float:
        """
        Componente de avaliar_carta que vem do STAT de counter da carta
        (rede de seguranca na mao). Extraido como metodo proprio porque
        pitch_cost_as_counter precisa recalcular exatamente este componente
        sem o multiplicador de urgencia (life_mult=False).
        """
        if card.counter <= 0:
            return 0.0
        my_life = self.me.life_count()
        v = card.counter / 1000 * COUNTER_STAT_VALUE_PER_1000
        if life_mult:
            if my_life <= 1: v *= 4.0
            elif my_life <= 2: v *= 2.5
            elif my_life <= 3: v *= 1.5
        # Penaliza se já tem muitos counters na mão
        counters_em_mao = sum(1 for c in self.me.hand
                              if c.counter > 0 and c is not card)
        if counters_em_mao >= 4: v *= 0.4
        elif counters_em_mao >= 2: v *= 0.7
        return v

    def pitch_cost_as_counter(self, card: 'Card') -> float:
        """
        Quanto se PERDE gastando a carta como counter AGORA: o valor
        situacional dela, trocando o componente de counter (que inclui um
        multiplicador de urgencia por vida baixa — circular na hora de
        USAR: a carta ficaria cara demais justamente quando o counter e
        mais necessario) pela OPCAO FUTURA de counter que se abre mao ao
        gastar. Essa opcao vale o componente-base cheio com vida alta
        (muitos golpes ainda por vir — guardar tem valor real) e quase
        nada com vida 1 (defender AGORA e o proprio uso pra que a carta
        foi guardada). Um Saturn jogavel (corpo + efeito) continua caro de
        pitchar em qualquer vida; uma vanilla injogavel de 2000 counter e
        quase gratis com vida baixa (achado real 11/07: bot pitchou Saturn
        num jab 5000v5000 com vida 4 e depois recusou counter com vida 2).
        """
        my_life = self.me.life_count()
        opcao_futura = {0: 0.0, 1: 0.1, 2: 0.4, 3: 0.7}.get(my_life, 1.0)
        return max(0.0, self.avaliar_carta(card)
                   - self._counter_stat_bonus(card)
                   + self._counter_stat_bonus(card, life_mult=False) * opcao_futura)

    _OPP_POWER_TARGETS = {'opp_character', 'opp_leader', 'opp_leader_or_character',
                          'all_opp_characters'}

    def _step_condition_currently_holds(self, card: 'Card', step_matches) -> bool:
        """
        Generaliza o mecanismo de _conditional_play_card_combo_value pra
        QUALQUER acao: acha o(s) step(s) de on_play/main da PROPRIA carta
        que `step_matches(step)` aceita, e checa se a condicao (bloco+step)
        bate com o estado ATUAL via _check_conditions (read-only, mesma
        funcao que o motor usa pra executar o efeito de verdade). Usado
        pelas flags estaticas de avaliar_carta (has_draw/has_ko/etc, que
        vem de get_card_flags/card_analysis_db e sao CEGAS a condicao) --
        antes essas flags somavam bonus incondicional mesmo quando o
        efeito real so dispara sob uma condicao que nao vale agora (achado
        23/07, pedido do usuario pra generalizar o fix do play_card da
        Pudding pra qualquer efeito, nao so aquele).
        Sem NENHUM step com essa acao em on_play/main (a flag pode vir de
        outro gatilho, tipo on_ko/passive/end_of_turn, que este scan nao
        cobre) -> True, conservador: mantem o comportamento antigo (sem
        regressao nas centenas de cartas ja tunadas com esse bonus fixo).

        EXCECAO (achado real 10/08, auditoria do lider Sanji OP12-041 --
        investigacao pedida pelo usuario apos 200 partidas em lote
        mostrarem winrate de 10% pra ele, muito abaixo dos demais):
        quando o UNICO lugar onde a acao aparece e um gatilho SO-DE-COMBATE
        (`COMBAT_ONLY_TRIGGERS` -- counter/when_attacking/on_opp_attack/
        leader_battle_reactive), o fallback conservador acima estava
        ERRADO -- esses gatilhos NUNCA resolvem quando a carta e jogada
        fora de batalha (habilidade do lider Sanji joga um Event da mao;
        qualquer outro `play_card`/`play_from_trash` de efeito tem o
        mesmo problema). Ex real: Gum-Gum Giant (OP09-078) so tem bloco
        `[Counter]` (draw 2 + buff, nunca dispara em Main) e pontuava
        IGUAL a uma carta de dig de verdade (78 vs 78) e ACIMA de uma
        carta de remocao real (52) em `avaliar_carta` -- o motor podia
        gastar a ativacao (1x por turno) numa carta que nao faz
        absolutamente nada. Distingue isso escaneando os OUTROS blocos:
        se achar a acao em algum gatilho NAO-so-de-combate (on_ko/
        passive/end_of_turn/etc, fora do scan de on_play/main de
        proposito), mantem o True conservador de sempre; se so achar em
        gatilho de combate, retorna False (a flag esta certa sobre o que
        a carta PODE fazer, mas errada sobre poder fazer isso agora,
        fora de uma batalha).
        """
        effects = get_card_effects(card.code)
        ee = EffectExecutor(self.me, self.opp)
        achou = False
        for trig in ('on_play', 'main'):
            ef = effects.get(trig)
            if not isinstance(ef, dict):
                continue
            block_conds = ef.get('conditions', {})
            block_ok = (not block_conds) or ee._check_conditions(block_conds, card)
            # Achado real 03/08: `ef.get('steps', [])` vinha vazio pra
            # "Choose one" (guardado em `choice`) -- sem isso, `achou`
            # nunca virava True pra essas cartas e a flag caia sempre no
            # fallback permissivo abaixo (correto por acidente, nao por
            # ter checado a condicao de verdade).
            for step in resolve_choice_for_scoring(ef, card, self.me, self.opp):
                if not step_matches(step):
                    continue
                achou = True
                step_conds = step.get('conditions', {})
                step_ok = (not step_conds) or ee._check_conditions(step_conds, card)
                if block_ok and step_ok:
                    return True
        if achou:
            return False
        so_gatilho_de_combate = False
        for trig, ef in effects.items():
            if trig in ('on_play', 'main') or not isinstance(ef, dict):
                continue
            for step in resolve_choice_for_scoring(ef, card, self.me, self.opp):
                if not step_matches(step):
                    continue
                if trig not in COMBAT_ONLY_TRIGGERS:
                    return True   # gatilho legitimo fora do scan (on_ko/passive/etc)
                so_gatilho_de_combate = True
        return not so_gatilho_de_combate

    def _conditional_play_card_combo_value(self, card: 'Card') -> float:
        """
        Bonus de avaliar_carta pro passo 'play_card' condicional (jogar
        OUTRA carta da mao DE GRACA) dentro do proprio on_play/main da
        carta -- ex: Charlotte Pudding PRB02-010, "[On Play] DON!! -2: se
        seu lider e Big Mom Pirates e o oponente tem 6+ DON, compra 2,
        depois joga ate 1 personagem Big Mom Pirates de 6000-8000 poder da
        mao". As flags de get_card_flags (has_draw/is_searcher/etc, usadas
        acima) sao FIXAS por carta e nunca cobriram esse passo -- Pudding
        pontuava so pelo corpo (5000 poder), cego pro combo real (achado
        ao vivo 23/07: virou counter fodder em vez de ser jogada). Generico
        via card_effects_db + _check_conditions com o estado ATUAL --
        qualquer carta futura com esse padrao entra automaticamente, nao
        so a Pudding.
        """
        from optcg_engine.rules_facade import eligible_cards
        effects = get_card_effects(card.code)
        ee = EffectExecutor(self.me, self.opp)
        bonus = 0.0
        for trig in ('on_play', 'main'):
            ef = effects.get(trig)
            if not isinstance(ef, dict):
                continue
            block_conds = ef.get('conditions', {})
            if block_conds and not ee._check_conditions(block_conds, card):
                continue
            # Achado real 03/08: resolve "Choose one" (choice) quando
            # `steps` vem vazio -- mesmo padrao do fix em
            # _step_condition_currently_holds acima.
            for step in resolve_choice_for_scoring(ef, card, self.me, self.opp):
                if step.get('action') != 'play_card':
                    continue
                step_conds = step.get('conditions', {})
                if step_conds and not ee._check_conditions(step_conds, card):
                    continue
                candidatos = [
                    c for c in eligible_cards(
                        self.me.hand, filter_text=step.get('filter_type', ''),
                        power_gte=step.get('power_gte'), power_lte=step.get('power_lte'),
                        cost_lte=step.get('cost_lte'), exclude_card=card)
                    if c.card_type in ('CHARACTER', 'STAGE', 'EVENT')]
                if candidatos:
                    melhor = max(candidatos, key=lambda c: c.board_value())
                    bonus += min(90.0, melhor.board_value() * 8)
        return bonus

    _OWN_BOARD_BUFF_TARGETS = {'own_character', 'select_filtered', 'all_allies'}

    # Valor generico por acao pra steps SEM escala numerica propria (amount)
    # -- concede um keyword/estado a um personagem PROPRIO ja em campo.
    # Mesma ordem de grandeza dos bonus ja usados em avaliar_carta pra "esta
    # carta TEM o keyword" (rush=30, double_attack=25, unblockable=20,
    # blocker=20/+vida, banish=15) -- reaproveitado aqui pro caso "esta
    # carta CONCEDE o keyword pra outro personagem em campo".
    _BOARD_COMBO_ACTION_VALUE = {
        'gain_rush': 30.0, 'keyword_rush': 30.0,
        'gain_double_attack': 25.0, 'keyword_double_attack': 25.0,
        'gain_unblockable': 20.0, 'keyword_unblockable': 20.0,
        'gain_blocker': 20.0, 'keyword_blocker': 20.0,
        'gain_banish': 15.0, 'keyword_banish': 15.0,
        'grant_ko_immunity_type': 20.0,
        'set_active': 20.0,        # desresta -- pode atacar/bloquear de novo
        'bounce': 20.0,            # protege da remocao do oponente
        'buff_cost': 12.0, 'debuff_cost': 12.0,
    }

    def _conditional_board_synergy_value(self, card: 'Card') -> float:
        """
        Espelho de _conditional_play_card_combo_value pro combo com carta
        JA EM CAMPO (nao na mao), pedido explicito do usuario (23/07,
        reforcado depois: "nao e so buff, tem rush/blocker/DON/custo extra/
        double strike tb"). QUALQUER step do proprio on_play/main mirando
        personagem PROPRIO filtrado (target='own_character'/
        'select_filtered'/'all_allies' + filter_type/filter_names) so vale
        a pena se existir ALGUM personagem correspondente em campo AGORA --
        exatamente como play_card so vale com alvo na mao. Cobre
        buff_power/set_base_power (escala pelo amount), e qualquer acao de
        _BOARD_COMBO_ACTION_VALUE (concessao de keyword/estado, valor fixo
        por tipo). buff_power de batalha (self/leader, battle_only) fica de
        fora -- guard proprio ja existe em _combat_buff_worth_paying.
        Achados reais no banco: EB03-032/EB04-040 (buff_power em nome
        especifico ja em campo), OP01-042 (set_active em personagens
        rested de tipo+custo, condicionado ao lider), OP14-098 (buff_cost),
        OP16-058 (set_base_power), OP07-062 (bounce da propria carta).
        """
        from optcg_engine.rules_facade import eligible_cards
        effects = get_card_effects(card.code)
        ee = EffectExecutor(self.me, self.opp)
        bonus = 0.0
        for trig in ('on_play', 'main'):
            ef = effects.get(trig)
            if not isinstance(ef, dict):
                continue
            block_conds = ef.get('conditions', {})
            if block_conds and not ee._check_conditions(block_conds, card):
                continue
            # Achado real 03/08: resolve "Choose one" quando `steps` vazio.
            for step in resolve_choice_for_scoring(ef, card, self.me, self.opp):
                action = step.get('action')
                escala_por_amount = action in ('buff_power', 'set_base_power')
                if not escala_por_amount and action not in self._BOARD_COMBO_ACTION_VALUE:
                    continue
                if step.get('target') not in self._OWN_BOARD_BUFF_TARGETS:
                    continue
                if action == 'buff_power' and step.get('duration') in ('battle_only', 'this_battle'):
                    continue  # buff so-de-combate, guard proprio ja cobre
                filtro = step.get('filter_type') or step.get('filter_names') or ''
                if not filtro:
                    continue  # sem filtro = "todos os aliados", ja no flat da flag
                step_conds = step.get('conditions', {})
                if step_conds and not ee._check_conditions(step_conds, card):
                    continue
                candidatos = eligible_cards(
                    self.me.field_chars, filter_text=filtro,
                    cost_eq=step.get('cost_eq'), cost_lte=step.get('cost_lte'),
                    power_eq=step.get('power_eq'), power_gte=step.get('power_gte'),
                    power_lte=step.get('power_lte'), exclude_card=card)
                if not candidatos:
                    continue
                if escala_por_amount:
                    amount = step.get('amount', 0)
                    bonus += min(60.0, len(candidatos) * (amount / 1000.0) * 8)
                else:
                    valor = self._BOARD_COMBO_ACTION_VALUE.get(action, 12.0)
                    bonus += min(60.0, len(candidatos) * valor)
        return bonus

    # FASE 2 do mapeamento de combos (usuario, 24/07: "temos que resolver
    # para abranger o maximo de cartas possiveis"). Auditoria 24/07 achou
    # 101 tipos de 'action' distintos em on_play/main no banco inteiro --
    # avaliar_carta so reconhecia 8 (via get_card_flags: draws/is_searcher/
    # kos-is_removal/bounces/rests_opponent/power_buff/gives_don/gains_life)
    # + play_card (_conditional_play_card_combo_value) + concessao de
    # keyword/estado a personagem PROPRIO ja em campo
    # (_conditional_board_synergy_value). O RESTO pontuava ZERO, mesmo
    # sendo o efeito real e principal da carta -- ex: Charlotte Katakuri
    # (add_don), Wapol (play_from_trash), Buggy (set_don_active).
    # Primeira passada: so os tipos de ALTO VOLUME/ALTA CONFIANCA (efeito
    # PRINCIPAL, sem ambiguidade de alvo/direcao) entram aqui -- steps de
    # LIMPEZA/companion do mesmo bloco (deck_bottom_rest, deck_reorder_rest,
    # trash_rest -- sempre acompanham look_top_deck/etc, contariam valor
    # 2x se pontuados soltos) e steps que sao CUSTO/DRAWBACK pro proprio
    # jogador (trash_from_hand, trash_own_life, give_don_opp, self_cant_*,
    # lock_self_*, reveal_* informativo) ficam DE FORA de proposito --
    # entram numa fase futura se algum combo real depender deles.
    _UNCOVERED_ACTION_VALUE = {
        'add_don': 20.0,                    # DON extra pro proprio campo
        'set_active': 15.0,                 # desresta (ataca/bloqueia de novo)
        'set_don_active': 15.0,             # desresta DON (recurso extra)
        'play_from_trash': 30.0,            # recursao -- mesma familia de is_searcher
        'play_from_deck': 25.0,             # desenvolve campo de graca
        'debuff_cost': 12.0,                # mesmo valor usado em _BOARD_COMBO_ACTION_VALUE
        'life_to_hand': 20.0,               # carta na mao + vida fica mais fina (defensivo)
        'opp_trash_from_hand': 15.0,        # disrupcao de mao do oponente
        'gain_double_attack': 25.0,         # concede a SI MESMA (mesmo valor do check estatico)
        'gain_blocker': 20.0,
        'gain_banish': 15.0,
        'gain_unblockable': 20.0,
        'grant_ko_immunity_type': 15.0,     # protege personagem(ns) proprio(s)
        # peek_life: informacao pura (olha 1 carta da propria vida), sem
        # mudanca de estado -- valor baixo, mesma familia do desconto
        # "info tem retorno decrescente" ja usado em _score_activate_main.
        # Conferido contra cartas reais (Myskina Olga, Shirley, Aisa): 3
        # delas tem SO esse step no on_play, hoje pontuam 0.
        'peek_life': 5.0,
        'negate_effect': 15.0,              # disrupcao/counter-play
        'lock_opp_blocker_turn': 15.0,      # nega blocker do oponente por 1 turno -- tempo forte
        'lock_opp_cannot_be_rested': 10.0,
        'place_opp_char_to_opp_life': 15.0, # remove do campo do oponente (vai pra vida dele)
        'opp_place_hand_bottom_deck': 15.0, # disrupcao de mao
        'opp_place_trash_bottom_deck': 10.0,
        'deal_damage': 15.0,
        'attack_life': 10.0,
        'character_to_owner_life': 10.0,
        'transfer_don': 10.0,
        'rest_opp_don': 10.0,
        # ── Segunda passada (24/07): familia select_grant_* -- mesma
        # concessao de keyword/estado que gain_X/keyword_X, so que via um
        # step de SELECAO (target='selected'/'don_recipient' em vez de
        # 'self') em vez de aplicar direto na propria carta. Mesmos
        # valores dos equivalentes diretos (gain_rush=30, double_attack=25,
        # unblockable/blocker=20, banish=15) e do check estatico no topo
        # de avaliar_carta -- MESMO risco ja aceito pelos outros flats
        # desta tabela (nao verifica se ha alvo elegivel, mesmo padrao de
        # add_don/deal_damage/etc).
        'select_grant_rush': 30.0,
        'select_grant_rush_character': 18.0,
        'select_grant_double_attack': 25.0,
        'select_grant_unblockable_turn': 20.0,
        'select_grant_blocker': 20.0,
        'select_grant_banish': 15.0,
        'select_grant_can_attack_active_turn': 15.0,  # desresta + libera ataque (~set_active)
        # opp_don_minus: reduz recurso de DON do oponente -- disrupcao de
        # ramp, mesma familia de rest_opp_don/transfer_don.
        'opp_don_minus': 15.0,
        # ── Terceira passada (24/07): sinal NEGATIVO, primeira vez que
        # este dicionario carrega valores negativos. Todos os 6 abaixo
        # foram conferidos contra cartas REAIS do banco antes de decidir
        # a direcao (nao supostos) -- cada um aparece SEMPRE como custo
        # tacado depois de um efeito real ja pontuado em outro lugar
        # (has_search/has_ko/buff_power/etc), nunca como o efeito
        # principal sozinho. `bonus += valor` ja soma negativo
        # corretamente (mesmo mecanismo, sem branch novo).
        'give_don_opp': -20.0,          # da DON pro OPONENTE -- sempre custo
        'trash_own_life': -15.0,        # trasha a PROPRIA vida -- fica mais perto de perder
        'self_cant_play': -20.0,        # trava jogar outras cartas este turno
        'self_cant_take_life': -15.0,   # trava pegar da propria vida este turno
        'lock_self_character_refresh': -15.0,  # personagem proprio nao desresta no proximo turno
        'trash_from_hand': -12.0,       # descarta da propria mao (STEP de efeito, nao custo)
    }

    def _uncovered_action_value(self, card: 'Card') -> float:
        """
        Bonus GENERICO (fase 2, 2 passadas) pros ~32 tipos de acao de alto
        volume/confianca do banco que nenhum outro mecanismo de
        avaliar_carta ainda reconhece (ver _UNCOVERED_ACTION_VALUE acima
        pra lista e criterio de inclusao). Mesma convencao de
        _conditional_play_card_combo_value/_conditional_board_synergy_value:
        so on_play/main, condicoes do bloco E do step checadas contra o
        estado ATUAL via _check_conditions, um bonus FLAT por tipo de acao
        encontrado (nao escala por count -- mesmo padrao do bonus fixo das
        8 flags antigas).
        """
        effects = get_card_effects(card.code)
        ee = EffectExecutor(self.me, self.opp)
        bonus = 0.0
        vistos = set()
        for trig in ('on_play', 'main'):
            ef = effects.get(trig)
            if not isinstance(ef, dict):
                continue
            block_conds = ef.get('conditions', {})
            if block_conds and not ee._check_conditions(block_conds, card):
                continue
            # Achado real 03/08: resolve "Choose one" quando `steps` vazio
            # -- este e o catch-all generico, o mais impactado das 4
            # funcoes da familia avaliar_carta pra "Choose one" invisivel.
            for step in resolve_choice_for_scoring(ef, card, self.me, self.opp):
                action = step.get('action')
                if action not in self._UNCOVERED_ACTION_VALUE or action in vistos:
                    continue
                step_conds = step.get('conditions', {})
                if step_conds and not ee._check_conditions(step_conds, card):
                    continue
                vistos.add(action)
                bonus += self._UNCOVERED_ACTION_VALUE[action]
        return bonus

    def _own_effect_removes_char_react_bonus(self, card: 'Card') -> float:
        """
        FASE B do Turn Planner (usuario, 24/07: combos mapeados devem
        entrar na decisao, "todas as possibilidades"). Meu board pode ter
        um watcher `on_own_effect_removes_char` (fase 1.4, ex: Crocodile
        EB02-023 -- so bounce do OPONENTE; Boa Hancock OP07-038/Shakuyaku
        OP08-046 -- qualquer remocao, qualquer lado) que reage quando MEU
        proprio efeito remove um Character do campo. `avaliar_carta` ja
        credita has_ko/has_bounce pelo valor da remocao em si -- nunca
        pelo watcher reagindo a ela.
        """
        meus = [self.me.leader, *self.me.field_chars]
        if self.me.field_stage:
            meus.append(self.me.field_stage)
        watchers = [(c, get_card_effects(c.code).get('on_own_effect_removes_char')) for c in meus]
        watchers = [(c, w) for c, w in watchers if w]
        if not watchers:
            return 0.0
        effects = get_card_effects(card.code)
        bonus = 0.0
        for trig in ('on_play', 'main'):
            ef = effects.get(trig)
            if not isinstance(ef, dict):
                continue
            # Achado real 03/08: resolve "Choose one" quando `steps` vazio.
            for step in resolve_choice_for_scoring(ef, card, self.me, self.opp):
                act = step.get('action')
                if act not in ('ko', 'bounce', 'trash_character', 'ko_selected',
                               'place_opp_character_bottom_deck'):
                    continue
                target = step.get('target', 'opp_character')
                side = 'own' if target in ('own_character', 'self_character') else 'opp'
                if act == 'bounce':
                    rtype = 'bounce'
                elif act == 'place_opp_character_bottom_deck':
                    rtype = 'deck_bottom'
                else:
                    rtype = 'ko'
                for _source, w in watchers:
                    if w.get('removal_type') and w['removal_type'] != rtype:
                        continue
                    if w.get('target_side') and w['target_side'] != side:
                        continue
                    bonus += 20.0
        return min(bonus, 40.0)

    def _event_activated_react_bonus(self, card: 'Card') -> float:
        """
        FASE B do Turn Planner (usuario, 24/07). Jogar um EVENT pode
        acionar `on_own_event_activated` (meu board, fase 1.1 -- ex:
        Usopp, Franky, Page One) ou `on_opp_event_activated` (board do
        OPONENTE reagindo a MIM jogar um evento -- penaliza, ex: Franky
        OP01-062).
        """
        if card.card_type != 'EVENT':
            return 0.0
        bonus = 0.0
        ee = EffectExecutor(self.me, self.opp)
        meus = [self.me.leader, *self.me.field_chars]
        if self.me.field_stage:
            meus.append(self.me.field_stage)
        for source in meus:
            entry = get_card_effects(source.code).get('on_own_event_activated')
            if not entry:
                continue
            req = entry.get('don_requirement', 0)
            if req and source.don_attached < req:
                continue
            conds = entry.get('conditions', {})
            if not conds or ee._check_conditions(conds, source):
                bonus += 20.0
        ee_opp = EffectExecutor(self.opp, self.me)
        opps = [self.opp.leader, *self.opp.field_chars]
        if self.opp.field_stage:
            opps.append(self.opp.field_stage)
        for source in opps:
            entry = get_card_effects(source.code).get('on_opp_event_activated')
            if not entry:
                continue
            req = entry.get('don_requirement', 0)
            if req and source.don_attached < req:
                continue
            conds = entry.get('conditions', {})
            if not conds or ee_opp._check_conditions(conds, source):
                bonus -= 15.0
        return bonus

    def _char_played_filter_matches(self, entry, played_card) -> bool:
        """
        Mesma logica de filtro de `EffectExecutor._dispatch_char_played_side`
        (fase 1.3 do mapeamento de combos), duplicada aqui de proposito: a
        versao do dispatcher EXECUTA o gatilho de verdade durante a
        partida; esta versao so PREVE se ele vai disparar, pra scoring
        (decidir se vale jogar `played_card` ANTES de outra coisa). Manter
        os dois pontos sincronizados se o formato do filtro mudar.
        """
        if entry.get('play_filter_no_base_effect') and get_card_effects(played_card.code):
            return False
        if entry.get('play_filter_has_trigger') and not played_card.has_trigger:
            return False
        cost_gte = entry.get('play_filter_cost_gte')
        if cost_gte and played_card.cost < cost_gte:
            return False
        return True

    def _char_played_react_bonus(self, card, p, opp) -> float:
        """
        FASE B do Turn Planner (usuario, 24/07): pontua jogar `card`
        (CHARACTER) levando em conta quem JA esta em campo e observa
        "quando um Character e jogado" (on_own_char_played no MEU board,
        on_opp_char_played no board do OPONENTE -- fase 1.3, 24/07). Flat
        e generico -- mesma ordem de grandeza dos outros bonus de combo ja
        calibrados nesta sessao (fase 2, ~15-30), nao tenta calcular o
        valor exato do efeito reativo (isso o proprio avaliar_carta do
        source ja credita quando ELE for avaliado).

        Movido de OPTCGMatch pra DecisionEngine (24/07, ao preparar
        telemetria): achado que estava na classe errada -- os 2 metodos
        irmaos (_own_effect_removes_char_react_bonus/
        _event_activated_react_bonus) ja viviam aqui, e action_score_components
        (sim_bridge.py) so tem acesso a um DecisionEngine, nao a um
        OPTCGMatch inteiro -- quebrava com AttributeError ao tentar
        expor este bonus na telemetria ao vivo.
        """
        if card.card_type != 'CHARACTER':
            return 0.0
        bonus = 0.0
        ee = EffectExecutor(p, opp)
        meus = [p.leader, *p.field_chars]
        if p.field_stage:
            meus.append(p.field_stage)
        for source in meus:
            entry = get_card_effects(source.code).get('on_own_char_played')
            if not entry or not self._char_played_filter_matches(entry, card):
                continue
            conds = entry.get('conditions', {})
            if not conds or ee._check_conditions(conds, source):
                bonus += 25.0
        ee_opp = EffectExecutor(opp, p)
        opps = [opp.leader, *opp.field_chars]
        if opp.field_stage:
            opps.append(opp.field_stage)
        for source in opps:
            entry = get_card_effects(source.code).get('on_opp_char_played')
            if not entry or not self._char_played_filter_matches(entry, card):
                continue
            conds = entry.get('conditions', {})
            if not conds or ee_opp._check_conditions(conds, source):
                bonus -= 20.0
        return bonus

    def avaliar_carta(self, card: 'Card', stage_redundancy: bool = True) -> float:
        """
        Avalia o valor situacional de uma carta para jogar/guardar/descartar.
        stage_redundancy=False: pula o desconto de "2a stage com stage em
        campo" — usado por stage_worth pra comparar substituicao com os
        valores CRUS dos dois lados (senao o desconto entra em dupla
        contagem e bloqueia ate upgrade legitimo).
        """
        a       = self.analyzer
        posture = self.posture()
        s       = 0.0
        my_life  = self.me.life_count()
        opp_life = self.opp.life_count()
        don_now  = self.me.don_available

        # Jogabilidade imediata -- empurrão de DESEMPATE entre cartas de
        # valor parecido, NÃO um substituto pro valor intrínseco da carta.
        # Achado #3 (multissessão, finalmente atacado 10/07): antes disso
        # tinha +40/+20/-15 (span de 55), maior que boa parte dos bônus de
        # keyword/flag abaixo -- uma vanilla barata e jogável agora (ex:
        # Saint Mjosgard, 0 de poder) pontuava ACIMA de uma bomba de custo
        # alto só injogável neste turno (ex: Five Elders, 12000 de poder),
        # mesmo a bomba tendo poder/impacto muito maior. Reduzido pra
        # span de 23 (+15/+8/-8) -- ainda favorece jogar o que cabe no DON
        # de agora quando os valores são próximos, mas não afoga mais a
        # diferença real de poder/efeito entre as opções.
        play_cost = effective_hand_play_cost(self.me, card, self.opp)
        if play_cost <= don_now:       s += 15
        elif play_cost <= don_now + 2: s += 8
        else:                          s -= 8

        s += card.power / 1000 * 5

        # Keywords
        if card.has_rush or card.rush_this_turn:
            v = 30
            if opp_life <= 2: v += 50
            if opp_life == 0: v += 100
            s += v

        if card.has_rush_character or card.rush_character_only_this_turn:
            v = 18
            if self.opp.field_chars: v += 18
            if a.should_clear_field(): v += 12
            s += v

        if card.has_double_attack or card.double_attack_this_turn:
            s += 25
            if opp_life <= 2: s += 35

        if card.has_unblockable or card.unblockable_this_turn:
            s += 20
            if opp_life <= 2: s += 30

        if card.has_banish:
            s += 15

        if card.has_blocker or card.blocker_this_turn:
            v = 20
            if my_life <= 1:   v += 100
            elif my_life <= 2: v += 60
            elif my_life <= 3: v += 30
            if a.opp_attack_count() >= 3: v += 20
            s += v

        s += self._counter_stat_bonus(card)

        if card.has_trigger:
            s += 10

        # Efeitos do banco — flags estruturadas do card_analysis_db (fonte única
        # de classificação; substituiu a detecção frágil por substring no texto).
        # As flags em si sao ESTATICAS (so dizem "a carta TEM esse tipo de
        # efeito", nao "a condicao dele vale AGORA") -- cada bonus abaixo so
        # e concedido se _step_condition_currently_holds confirmar, contra o
        # estado real, que o step correspondente dispara (ou nao achar
        # nenhum step condicionado em on_play/main, caso em que mantem o
        # comportamento antigo). Generalizacao do fix do combo play_card da
        # Pudding (achado 23/07) pra QUALQUER flag, pedido explicito do
        # usuario.
        flags = get_card_flags(card.code)
        has_draw   = flags.get('draws', False)
        has_search = flags.get('is_searcher', False)
        has_ko     = flags.get('kos', False) or flags.get('is_removal', False)
        has_bounce = flags.get('bounces', False)
        has_rest   = flags.get('rests_opponent', False)
        has_buff   = flags.get('power_buff', False)
        has_givdon = flags.get('gives_don', False)
        has_gainlf = flags.get('gains_life', False)

        def _is_ko_removal_step(step):
            act = step.get('action')
            # place_opp_character_bottom_deck/lock_opp_character_refresh/
            # lock_opp_character_attack: mesmo achado 24/07 do mapeamento de
            # combos (has_ko/is_removal em gerar_card_analysis_db.py) --
            # espelha aqui pra o gate de viabilidade (_step_condition_
            # currently_holds) reconhecer o step certo quando a flag bater.
            # trash_character: mesma mecanica de remocao de campo que 'ko'
            # (comentario do handler generico em _execute_step, "trash_
            # character usa a MESMA mecanica de remocao de campo que ko") --
            # achado 24/07 na fase 2 do mapeamento de combos, so 4 cartas no
            # banco mas o gate de viabilidade tratava como acao desconhecida.
            # ko_selected: KO de um alvo escolhido por step ANTERIOR no
            # mesmo bloco (Zephyr OP06-074, Black Hole OP09-098) -- mesma
            # mecanica de KO, so a fonte do alvo difere. opp_bounce_own_
            # character: forca o OPONENTE a devolver 1 dos PROPRIOS
            # personagens pra mao dele (Tsuru OP06-051, Muggy Ball
            # OP09-058) -- remocao do campo do oponente do MEU ponto de
            # vista, mesmo efeito liquido de bounce. Achados 24/07, segunda
            # passada da fase 2 do mapeamento de combos.
            if act in ('ko', 'bounce', 'rest_opp_character', 'trash_character',
                      'ko_selected', 'opp_bounce_own_character',
                      'place_opp_character_bottom_deck',
                      'lock_opp_character_refresh', 'lock_opp_character_attack'):
                return True
            return (act in ('debuff_power', 'set_base_power')
                    and step.get('target') in self._OPP_POWER_TARGETS)

        if has_draw and self._step_condition_currently_holds(
                card, lambda st: st.get('action') == 'draw'):
            s += 25 + (10 if len(self.me.hand) <= 3 else 0)
        if has_search and self._step_condition_currently_holds(
                card, lambda st: st.get('action') in
                ('look_top_deck', 'add_to_hand', 'add_from_trash')):
            s += 30 + (15 if self.me.turn <= 3 else 0)
        if has_ko and self._step_condition_currently_holds(card, _is_ko_removal_step):
            s += 35
            if a.field_advantage() < 0: s += 25
            # remoção sem alvo vale pouco -- não pontuar KO no vácuo. Achado
            # 09/08 (auditoria de cobertura, bloco 475): antes disso só
            # EXISTÊNCIA de personagem do oponente importava (mesmo bônus
            # com 1 ou 5 personagens no board dele) -- agora escala (limitado)
            # com quantos alvos reais existem, e soma um bônus extra se
            # `critical_threats()` (já existente, mesma fonte de peso de
            # `future_threat_value`) confirma que pelo menos um deles é
            # ameaça de efeito de verdade, não só um corpo qualquer.
            if not self.opp.field_chars:
                s -= 30
            else:
                s += min(15, 5 * (len(self.opp.field_chars) - 1))
                if a.critical_threats(): s += 20
        if has_bounce and self._step_condition_currently_holds(
                card, lambda st: st.get('action') == 'bounce'):
            s += 20
            if a.field_advantage() < 0: s += 15
            if not self.opp.field_chars:
                s -= 20
            else:
                s += min(10, 4 * (len(self.opp.field_chars) - 1))
                if a.critical_threats(): s += 15
        if has_ko or has_bounce:
            s += self._own_effect_removes_char_react_bonus(card)
        s += self._event_activated_react_bonus(card)
        if has_rest and self._step_condition_currently_holds(
                card, lambda st: st.get('action') == 'rest_opp_character'):
            # Restar abre personagens para ataque
            if a.should_clear_field(): s += 20
            else: s += 10
        if has_buff and self._step_condition_currently_holds(
                card, lambda st: st.get('action') == 'buff_power'):
            s += 15
        if has_givdon and self._step_condition_currently_holds(
                card, lambda st: st.get('action') == 'give_don'):
            s += 20
        if has_gainlf and self._step_condition_currently_holds(
                card, lambda st: st.get('action') in ('gain_life', 'heal')):
            v = 15
            if my_life <= 1:   v += 60
            elif my_life <= 2: v += 35
            s += v

        # Passivo when_don_returned: motor recorrente que gera valor toda vez
        # que DON!! volta pro deck (comum em decks com varios custos don_minus
        # OPCIONAIS -- este proprio lider ja tem on_opp_attack/when_attacking
        # com don_minus:1 opcional). As flags do banco (has_draw/has_ko/etc)
        # so cobrem acao de on_play/main -- when_don_returned nunca gerava
        # NENHUM bonus aqui, entao um corpo com esse passivo pontuava igual a
        # um vanilla puro do mesmo poder. Achado real 24/07 (usuario: "bot
        # ignora combo" -- Charlotte Katakuri ST34-001, when_don_returned
        # add_don:2, avaliava 50 -- identico a um vanilla 7000 sem efeito
        # nenhum). Flat, nao tenta contar quantos gatilhos de don_minus o
        # deck tem (informacao que so o `full_deck_plan` teria, e nem sempre
        # disponivel) -- so reconhece que o passivo existe e a condicao dele
        # (se houver, ex: leader_type) vale agora.
        dr = get_card_effects(card.code).get('when_don_returned')
        if dr and card.card_type == 'CHARACTER':
            dr_conds = dr.get('conditions', {})
            if not dr_conds or EffectExecutor(self.me, self.opp)._check_conditions(dr_conds, card):
                s += 35

        # Ajuste por postura
        if posture == 'LETHAL':
            if card.has_rush or card.rush_this_turn:          s += 50
            if card.has_rush_character or card.rush_character_only_this_turn: s += 20
            if card.has_double_attack or card.double_attack_this_turn: s += 40
            if card.has_unblockable or card.unblockable_this_turn:   s += 30
        elif posture == 'AGGRESSIVE':
            if card.has_rush or card.rush_this_turn:          s += 30
            if card.has_rush_character or card.rush_character_only_this_turn: s += 15
            if card.has_double_attack or card.double_attack_this_turn: s += 20
            if card.counter > 0:       s -= 10
        elif posture == 'DEFENSIVE':
            if card.has_blocker or card.blocker_this_turn:       s += 50
            if card.counter > 0:       s += 25
            if card.has_rush or card.rush_this_turn:          s -= 15
        elif posture == 'CONTROL':
            if has_ko:     s += 30
            if has_bounce: s += 20
            if has_rest:   s += 15
            # Achado real 10/08 (auditoria Sanji OP12-041, bloco 484): um
            # deck que genuinamente não tem remoção (ver
            # `deck_lacks_removal_tools()`) usa busca/compra COMO o
            # próprio jeito de "controlar" o jogo (achar a resposta
            # certa) -- sem isto, CONTROL só recompensava ko/bounce/rest,
            # que esse tipo de deck raramente tem, e a IA parava de
            # priorizar suas melhores cartas bem no momento em que mais
            # precisava continuar cavando.
            if a.deck_lacks_removal_tools():
                if has_search: s += 25
                if has_draw:   s += 20
        elif posture == 'DEVELOP':
            if has_search: s += 25
            if has_draw:   s += 20

        # Carta CERTA do game_plan (a bomba do combo do deck, ex: Five Elders):
        # avaliar_carta hoje trata qualquer character so pelos termos genericos
        # (poder/keyword/counter) — SEM nenhuma nocao de plano, diferente de
        # `_trash_value` (que ja protege o win-con no CUSTO de trash). Sem isso,
        # um corpo mais barato com counter alto (ex: Nosjuro, 1000 counter) podia
        # pontuar ACIMA da bomba de 12000 poder em vida baixa (multiplicador de
        # panico do counter), e a bomba nunca era jogada mesmo saindo DE GRACA
        # (ex: Empty Throne "play 1 Five Elders da mao") -- achado ao vivo 14/07
        # (log 12.02.31): bot jogou Nosjuro em vez do Five Elders com 10 DON no
        # pool. Generico via compute_game_plan (zero nome de carta).
        plano_bomba = compute_game_plan(self.me)
        if plano_bomba['win_con_code'] and card.code == plano_bomba['win_con_code']:
            s += 90

        s += self._conditional_play_card_combo_value(card)
        s += self._conditional_board_synergy_value(card)
        s += self._uncovered_action_value(card)

        # STAGE redundante: com stage propria ja em campo, a 2a copia na
        # mao so vale o UPGRADE liquido sobre a atual — e vira o pitch mais
        # barato pra custos/counter (achado real 12/07, 23.41.50: o custo
        # do lider trashou o Mars recem-descido tendo Mary Geoise inutil
        # na mao). Guarda `is not field_stage` corta a recursao (a stage
        # de campo avalia cheia).
        if (stage_redundancy
                and card.card_type == 'STAGE' and self.me.field_stage is not None
                and card is not self.me.field_stage):
            s = max(5.0, s - self.stage_worth(self.me.field_stage))

        return s

    def search_card_value(self, card: 'Card') -> float:
        """Valor contextual de uma carta oferecida por search/look.

        Mantem no motor unico a combinacao de qualidade intrinseca, curva,
        counter, aceleracao e GamePlan. O bridge apenas ordena os candidatos
        usando este valor.
        """
        value = float(self.avaliar_carta(card))
        next_don = min(10, self.me.don_on_field() + 2)
        playable_now = card.cost <= self.me.don_available
        playable_next = card.cost <= next_don
        expensive_dead = card.cost > next_don and card.counter <= 0
        bombs_in_hand = sum(1 for c in self.me.hand
                            if c.cost >= 7 and c.counter <= 0)

        if playable_now:
            value += 70
        elif playable_next:
            value += 45
        elif expensive_dead:
            value -= 35 + bombs_in_hand * 30

        counter_cards = sum(1 for c in self.me.hand if c.counter > 0)
        if card.counter > 0:
            value += min(60, card.counter / 1000 * 25)
            if counter_cards <= 1:
                value += 45

        effect_actions = {
            step.get('action')
            for block in get_card_effects(card.code).values()
            if isinstance(block, dict)
            for step in block.get('steps', [])
        }
        if effect_actions & {'add_don', 'set_don_active', 'give_don'}:
            value += 55

        plan = compute_game_plan(self.me)
        if card.code == plan.get('win_con_code'):
            copies = sum(1 for c in self.me.hand if c.code == card.code)
            value += 90 if copies == 0 else max(0, 35 - copies * 20)
        return value

    def stage_worth(self, stage: 'Card') -> float:
        """
        Valor de uma STAGE pra comparacao de substituicao: avaliar_carta +
        o motor recorrente de [Activate: Main] — o bonus equivalente em
        _score_play_action so existe pra CHARACTER, entao o Empty Throne
        (deploy gratis todo turno) avaliava quase nada e a Mary Geoise
        (custo 1, passiva situacional) o substituia (2x em partida real,
        12/07). Nao chamar para carta na MAO com stage em campo (avaliar
        ja desconta a redundancia nesse caso).
        """
        v = self.avaliar_carta(stage, stage_redundancy=False)
        am = get_card_effects(stage.code).get('activate_main', {})
        if am.get('steps'):
            v += 40
        return v

    # ── Escolher carta para jogar ─────────────────────────────────────────────

    def _effect_conditions_met(self, card) -> bool:
        """
        Verifica se as condições do efeito principal da carta estão satisfeitas
        no estado ATUAL. Evita jogar carta cujo efeito condicional não vai ativar
        (ex: Otama com 'life_lte:3' jogada com 4 vidas).

        Retorna True se não há condições, ou se as condições batem.
        """
        effects = get_card_effects(card.code)
        # pega o gatilho principal (on_play / main / activate_main)
        main_trig = None
        for t in ('on_play', 'main', 'activate_main'):
            if t in effects:
                main_trig = effects[t]
                break
        if not main_trig:
            return True  # sem efeito principal — sem condição a checar

        conds = main_trig.get('conditions', {})
        if not conds:
            return True

        me = self.me
        my_life  = me.life_count()
        my_hand  = len(me.hand)
        my_don   = me.don_available
        my_trash = len(me.trash)
        my_chars = len(me.field_chars)
        leader_types = set(str(getattr(me.leader, 'sub_types', '')).lower().split())

        for k, v in conds.items():
            if k == 'life_lte'  and not (my_life  <= v): return False
            if k == 'life_gte'  and not (my_life  >= v): return False
            if k == 'hand_lte'  and not (my_hand  <= v): return False
            if k == 'hand_gte'  and not (my_hand  >= v): return False
            if k == 'hand_eq'   and not (my_hand  == v): return False
            if k == 'deck_lte'  and not (len(me.deck) <= v): return False
            if k == 'life_and_hand_total_lte' and not ((my_life + my_hand) <= v): return False
            if k == 'don_gte'   and not (my_don   >= v): return False
            if k == 'has_don_attached' and v:
                attached = getattr(me.leader, 'don_attached', 0) + sum(
                    getattr(c, 'don_attached', 0) for c in me.field_chars)
                if attached <= 0: return False
            if k == 'don_attached_total_gte':
                attached_total = getattr(me.leader, 'don_attached', 0) + sum(
                    getattr(c, 'don_attached', 0) for c in me.field_chars)
                if attached_total < v: return False
            if k == 'event_activated_cost_gte_this_turn':
                if not any(c >= v for c in me.events_activated_costs_this_turn): return False
            if k == 'don_on_field_gte' and not ((my_don + me.don_rested) >= v): return False
            if k == 'don_on_field_lte' and not ((my_don + me.don_rested) <= v): return False
            if k == 'don_on_field_zero_or_gte':
                n = my_don + me.don_rested
                if not (n == 0 or n >= v): return False
            if k == 'opp_don_on_field_gte' and not (self.opp.don_on_field() >= v): return False
            if k == 'opp_don_on_field_lte' and not (self.opp.don_on_field() <= v): return False
            if k == 'don_on_field_lte_opp' and v:
                if not (me.don_on_field() <= self.opp.don_on_field()): return False
            if k == 'don_fewer_than_opp_by_gte':
                if not (self.opp.don_on_field() - me.don_on_field() >= v): return False
            if k == 'hand_fewer_than_opp_by_gte':
                if not (len(self.opp.hand) - len(me.hand) >= v): return False
            if k == 'opp_hand_gte' and not (len(self.opp.hand) >= v): return False
            if k == 'opp_chars_gte' and not (len(self.opp.field_chars) >= v): return False
            if k == 'trash_gte' and not (my_trash >= v): return False
            if k == 'trash_lte' and not (my_trash <= v): return False
            if k == 'just_played' and v and not getattr(card, 'just_played', False): return False
            if k == 'events_in_trash_gte':
                n_events = sum(1 for c in me.trash if c.card_type.lower() == 'event')
                if not (n_events >= v): return False
            if k == 'leader_power_lte':
                if not (me.leader.effective_power(True) <= v): return False
            if k == 'leader_name_includes':
                if v.lower() not in me.leader.name.lower(): return False
            if k == 'opp_rested_cards_gte':
                rested = self.opp.don_rested + sum(
                    1 for c in self.opp.field_chars if c.rested)
                rested += int(bool(getattr(self.opp.leader, 'rested', False)))
                rested += int(bool(self.opp.field_stage and getattr(
                    self.opp.field_stage, 'rested', False)))
                if rested < v: return False
            if k == 'other_char_power_gte':
                candidates = [c for c in me.field_chars if c is not card]
                ftype = conds.get('other_char_power_gte_type')
                if ftype:
                    candidates = [c for c in candidates
                                  if _norm_type_text(ftype) in _norm_type_text(c.sub_types)]
                fnames = [n.lower() for n in conds.get('other_char_power_gte_names', [])]
                if fnames:
                    candidates = [c for c in candidates
                                  if any(n in c.name.lower() for n in fnames)]
                power_of = ((lambda c: c.power) if conds.get('other_char_power_uses_base')
                            else (lambda c: c.effective_power(True)))
                if not any(power_of(c) >= v for c in candidates): return False
            if k == 'opp_char_power_gte':
                if not any(c.power >= v for c in self.opp.field_chars): return False
            if k == 'opp_char_cost_eq_or_gte':
                if not any(c.cost == v['eq'] or c.cost >= v['gte'] for c in self.opp.field_chars): return False
            if k == 'no_other_named':
                needle = v.lower()
                cost_eq = conds.get('no_other_named_cost_eq')
                outros = [c for c in me.field_chars
                          if c is not card and needle in c.name.lower()]
                if cost_eq is not None:
                    outros = [c for c in outros if c.cost == cost_eq]
                if outros: return False
            if k == 'no_char_power_gte':
                if any(c.power >= v for c in me.field_chars): return False
            if k == 'no_char_type_cost_gte':
                tipo_ncc2 = _norm_type_text(v['type'])
                if any(tipo_ncc2 in _norm_type_text(c.sub_types) and c.cost >= v['cost_gte']
                       for c in me.field_chars):
                    return False
            if k == 'has_named_character':
                needle = v.lower()
                if not any(needle in c.name.lower() for c in me.field_chars): return False
            if k == 'has_named_characters':
                power_eq_mn2 = conds.get('has_named_characters_power_eq')
                for nome in v:
                    needle2 = nome.lower()
                    matching2 = [cc for cc in me.field_chars if needle2 in cc.name.lower()]
                    if not matching2: return False
                    if power_eq_mn2 is not None and not any(cc.power == power_eq_mn2 for cc in matching2):
                        return False
            if k == 'has_named_characters_in_trash':
                for nome in v:
                    needle3 = nome.lower()
                    if not any(needle3 in cc.name.lower() for cc in me.trash): return False
            if k == 'own_rested_cards_gte':
                rested = me.don_rested + sum(1 for c in me.field_chars if c.rested)
                rested += int(bool(getattr(me.leader, 'rested', False)))
                rested += int(bool(me.field_stage and getattr(me.field_stage, 'rested', False)))
                if rested < v: return False
            if k in ('board_has_cost', 'board_has_cost_gte'):
                todos = list(me.field_chars) + list(self.opp.field_chars)
                exatos = set(conds.get('board_has_cost', []))
                gte = conds.get('board_has_cost_gte')
                if not any(c.cost in exatos or (gte is not None and c.cost >= gte)
                           for c in todos):
                    return False
            if k == 'chars_gte':
                cost_filter = conds.get('chars_gte_cost_filter')
                contagem = (sum(1 for c in me.field_chars if c.cost >= cost_filter)
                            if cost_filter is not None else my_chars)
                if not (contagem >= v): return False
            if k == 'chars_fewer_than_opp_by_gte':
                if not ((len(self.opp.field_chars) - my_chars) >= v): return False
            if k == 'total_chars_cost_gte':
                if not (sum(c.cost for c in me.field_chars) >= v): return False
            if k == 'leader_type':
                if str(v).lower() not in ' '.join(leader_types): return False
            if k == 'leader_is':
                if str(v).lower() not in str(getattr(me.leader, 'name', '')).lower(): return False
        return True

    def _can_play_card(self, card, don_usable: int | None = None) -> bool:
        """Decide se uma carta é jogável agora (mesma regra do choose_card_to_play)."""
        if card.card_type not in ('CHARACTER', 'EVENT', 'STAGE'):
            return False
        # Auto-restrição "cannot play this turn" (combo de ramp que trava você)
        if self.me.cant_play_from_hand_this_turn:
            return False
        if self.me.cant_play_chars_this_turn and card.card_type == 'CHARACTER':
            return False
        if self.me.cant_play_cost_gte and card.card_type == 'CHARACTER' \
                and card.cost >= self.me.cant_play_cost_gte:
            return False
        if don_usable is None:
            don_reserve = self._don_reserve_for_defense()
            don_usable  = max(0, self.me.don_available - don_reserve)
        if effective_hand_play_cost(self.me, card, self.opp) > don_usable:
            return False
        effects = get_card_effects(card.code)
        has_main = any(t in effects for t in ('on_play', 'main', 'activate_main'))
        # Eventos pure-counter (só trigger 'counter', sem 'main'): só usáveis
        # na vez do oponente via try_counter_event_*; não entram no main phase.
        # Eventos com AMBOS counter+main (ex: Ground Death, Never Existed) SÃO
        # jogáveis no main phase pelo efeito 'main'.
        if card.card_type == 'EVENT' and '[counter]' in card.card_text.lower() and not has_main:
            return False
        if card.card_type == 'EVENT' and not has_main:
            return False
        if not self._effect_conditions_met(card):
            # Efeito condicional nao dispara agora -- so vale jogar mesmo assim
            # se o CORPO em si (poder, counter, keywords, tudo que avaliar_carta
            # ja pondera, SEM o bonus das flags condicionais que exige a
            # condicao -- essas ja saem zeradas de avaliar_carta quando a
            # condicao nao vale) justificar ocupar campo/mao.
            #
            # FIX 24/07 (achado real, usuario: "distribui DON em carta fraca
            # pra empatar poder" + "so joga carta barata"): o gate antigo era
            # `card.power >= 5000` fixo -- excluia TOTALMENTE (nem aparecia
            # como opcao) qualquer carta on-curve mas < 5000 de poder, mesmo
            # com valor real por outro motivo (counter alto, etc). Confirmado
            # com ST18-001 (3000 poder, custo 3, counter 2000, condicao exige
            # DON!!8): sumia da lista inteira com so 4 DON, sobrando so
            # ataque/attach_don pra escolher -- e ai o DON ia pra empatar
            # poder num atacante fraco em vez de jogar essa carta. Auditoria
            # global: 86 cartas do banco tem esse padrao (poder<5000 + efeito
            # condicional). Usuario apontou que poder/custo sozinho tambem nao
            # basta (uma carta 0 poder pode valer muito por counter/timing) --
            # troca pro mesmo calculo completo (avaliar_carta) que decide toda
            # jogada/guarda no motor, em vez de reinventar uma regra estreita.
            # 40 e o piso: um corpo GENUINAMENTE vazio (0 poder, 0 counter,
            # nenhuma keyword) fica perto de 35 (so o desempate de
            # jogabilidade) -- continua fora, evitando "jogar no vacuo".
            if self.avaliar_carta(card) < 40.0:
                return False
        return True

    def _has_don_reactive_use(self) -> bool:
        """
        Existe algum jeito real de gastar DON reservado durante o turno do
        oponente? Sem isso, reservar é desperdício puro -- melhor
        concentrar tudo no ataque (auditoria 27/06, sugestão de Arthur).

        3 fontes, em ordem de confiabilidade:
          1. Counter event na mão que EXIGE DON no próprio custo (raro --
             a maioria de [Counter] só pede trashar a carta, sem DON).
          2. Character/Leader em campo com efeito [Counter]/[Opponent's
             Turn] que pede DON!! xN -- já estruturado no banco via
             don_requirement, nada novo a parsear.
          3. Proxy de EXPECTATIVA por composição: proporção de cartas com
             counter ainda não vistas em deck+vida. NÃO espia a ordem da
             vida (isso seria cheat) -- só conta quantas das restantes,
             agregadas, têm counter. Threshold 15%, aprovado por Arthur
             como número de partida (sem dado real por arquétipo ainda --
             isso fica pra quando Opponent Reading for retomado).
        """
        me = self.me

        for c in me.hand:
            if c.card_type == 'EVENT' and '[counter]' in c.card_text.lower():
                # Conta o custo de play da carta (DON!! necessário para jogá-la)
                # OU texto explícito de DON!! no efeito (efeitos paid-activate)
                play_cost = effective_hand_play_cost(me, c, self.opp)
                if play_cost > 0:
                    return True
                if re.search(r'don!!\s*[-x]?\s*\d', c.card_text.lower()):
                    return True

        for c in list(me.field_chars) + [me.leader]:
            effects = get_card_effects(c.code)
            for timing in ('counter', 'opp_turn'):
                blk = effects.get(timing)
                if blk and blk.get('don_requirement', 0) > 0:
                    return True

        pool = me.deck + me.life
        if pool:
            com_counter = sum(1 for c in pool
                               if c.counter >= 1000 or '[counter]' in c.card_text.lower())
            if com_counter / len(pool) >= 0.15:
                return True

        return False

    def _max_don_needed_for_reactive_use(self) -> int:
        """
        Quanto DON o MELHOR recurso reativo disponivel realmente precisa pra
        ser usado no turno do oponente -- MAXIMO entre as fontes que
        genuinamente custam DON (mesmas 2 primeiras de
        `_has_don_reactive_use`, fonte 3/proxy nao conta aqui porque counter
        impresso/generico nao custa DON nenhum pra jogar). 0 se nenhuma
        fonte com custo de DON existe (a reserva nao deveria travar DON
        nesse caso -- ver fix abaixo em `_don_reserve_for_defense`).
        """
        me = self.me
        maior = 0

        for c in me.hand:
            if c.card_type != 'EVENT' or '[counter]' not in c.card_text.lower():
                continue
            play_cost = effective_hand_play_cost(me, c, self.opp)
            if play_cost > 0:
                maior = max(maior, play_cost)
                continue
            m = re.search(r'don!!\s*[-x]?\s*(\d+)', c.card_text.lower())
            if m:
                maior = max(maior, int(m.group(1)))

        for c in list(me.field_chars) + [me.leader]:
            effects = get_card_effects(c.code)
            for timing in ('counter', 'opp_turn'):
                blk = effects.get(timing)
                if blk:
                    req = blk.get('don_requirement', 0)
                    if req > 0:
                        maior = max(maior, max(0, req - getattr(c, 'don_attached', 0)))

        return maior

    def _don_reserve_for_defense(self) -> int:
        """
        Quantos DON reservar para defesa no turno do oponente.
        Decisão baseada na ANÁLISE DE RISCO (regra do usuário):
        - Em PERIGO (pouca vida, ameaça alta, pouco counter na mão, ou tenho
          evento counter que preciso deixar DON em pé para usar) -> reserva mais.
        - SEGURO (muito counter na mão, blockers, vida alta, sem risco de perder
          no próximo turno) -> reserva pouco/nada, força ataque.
        """
        # Sem NENHUM jeito real de gastar DON na defesa, reservar é só
        # perder poder de ataque de graça -- corta aqui antes de qualquer
        # análise de ameaça/vida.
        if not self._has_don_reactive_use():
            return 0

        a = self.analyzer
        my_life = self.me.life_count()
        threat  = a.opp_lethal_threat()
        don_disp = self.me.don_available

        # Recursos defensivos que JÁ tenho na mão/campo
        counters_mao = sum(1 for c in self.me.hand if getattr(c, 'counter', 0) >= 1000)
        eventos_counter = sum(1 for c in self.me.hand
                              if c.card_type == 'EVENT' and '[counter]' in c.card_text.lower())
        blockers = len(self.me.blockers_active())

        # ── Estou SEGURO? muito counter + blocker + vida ok + sem ameaça ──
        seguro = (counters_mao >= 3 and my_life >= 3 and threat < 0.4) or \
                 (blockers >= 2 and my_life >= 4 and threat < 0.4)
        if seguro:
            return 0   # força ataque, não precisa guardar DON

        # ── Estou em PERIGO? reserva conforme a gravidade ──
        # FIX 24/07 (achado do usuario: "nao e necessario reservar don todo
        # turno" -- os tiers de vida baixa (my_life<=2/3) disparavam
        # INDEPENDENTE do que `threat` (opp_lethal_threat, o proprio calculo
        # de risco do motor) concluiu. Achado real: vida 3, ameaca 0.0 (o
        # oponente genuinamente nao consegue nada este turno) ainda
        # reservava 1 DON, turno apos turno, so por causa da vida. Os tiers
        # de vida agora exigem `threat > 0` tambem -- vida baixa sozinha,
        # sem NENHUM risco real calculado, nao e motivo pra guardar DON.
        reserva = 0
        if threat > 0.7:                    reserva = 3
        elif threat > 0.4:                  reserva = 2
        elif threat > 0 and my_life <= 2:   reserva = 2
        elif threat > 0 and my_life <= 3:   reserva = 1

        # Tenho evento counter mas POUCO counter de mão? vale deixar DON p/ o evento
        if threat > 0 and eventos_counter >= 1 and counters_mao <= 1 and my_life <= 3:
            reserva = max(reserva, 1)

        # Pouco counter na mão aumenta o risco de não conseguir defender
        if threat > 0 and counters_mao == 0 and my_life <= 3:
            reserva = max(reserva, 1)

        # FIX 24/07 (achado do usuario: "as vezes ele tem 1 evento custo 1
        # na mao e guarda 4 dons"): os tiers acima (ameaca/vida) escalam a
        # reserva ate 3-4 DON, mas SEM NENHUM teto ligado ao que o recurso
        # reativo disponivel REALMENTE custa -- counter impresso (stat na
        # carta) nao gasta DON nenhum pra usar, e um evento [Counter] com
        # custo 1 nunca precisa de mais que 1 DON guardado. Reservar mais
        # que isso e puro desperdicio de poder de ataque (o DON extra nunca
        # tem uso real na defesa). Teto = o maior custo de DON entre os
        # recursos reativos que EXISTEM de verdade agora (0 se so existem
        # counters impressos/genericos, que nao custam DON pra usar).
        reserva = min(reserva, self._max_don_needed_for_reactive_use())

        return min(reserva, don_disp)

    def _reserve_break_cost(self) -> float:
        """
        Quanto vale MANTER a reserva de DON pra defesa, na mesma regua de
        avaliar_carta -- usado por _can_spend_reserved_don_for_play pra decidir
        caso a caso (ganho liquido, regra do usuario) se uma jogada boa fura a
        reserva. Reaproveita os MESMOS sinais de risco de
        _don_reserve_for_defense (threat, vida, counters/blockers ja em
        mao/campo), so que devolvendo um VALOR comparavel a avaliar_carta em
        vez de uma quantidade de DON -- substitui o corte fixo por
        custo/poder que ignorava o efeito da carta e o momento do jogo.
        """
        if not self._has_don_reactive_use():
            return 0.0  # nada real pra defender com o DON -- reserva nao vale nada

        a = self.analyzer
        my_life = self.me.life_count()
        threat = a.opp_lethal_threat()
        counters_mao = sum(1 for c in self.me.hand if getattr(c, 'counter', 0) >= 1000)
        blockers = len(self.me.blockers_active())

        # Mesmo gate de "seguro" de _don_reserve_for_defense: colchao real
        # (counter/blocker/vida) = fura facil, sem nem entrar na conta de valor.
        seguro = (counters_mao >= 3 and my_life >= 3 and threat < 0.4) or \
                 (blockers >= 2 and my_life >= 4 and threat < 0.4)
        if seguro:
            return 0.0

        valor_vida = {1: 250.0, 2: 150.0, 3: 65.0}.get(my_life, 12.0)
        valor = valor_vida * max(threat, 0.4)
        # Colchao PARCIAL (nao o bastante pra "seguro", mas ja ajuda) desconta
        # proporcionalmente -- nao e tudo ou nada como o gate acima.
        colchao = min(1.0, counters_mao / 3.0) * 0.5 + min(1.0, blockers / 2.0) * 0.3
        return valor * (1.0 - colchao)

    def _can_spend_reserved_don_for_play(self, card) -> bool:
        """
        Reserva defensiva nao deve travar automaticamente uma jogada boa da
        lista de candidatas. GANHO LIQUIDO caso a caso (regra do usuario):
        fura a reserva se o valor de jogar a carta agora (avaliar_carta,
        effect-aware) supera o valor de manter a reserva (_reserve_break_cost,
        escalado por ameaca/vida/colchao ja em mao-campo) -- substitui o corte
        fixo `cost>=8 or power>=9000` que travava bombas de custo 6-7 atras da
        reserva mesmo com efeito forte e mesmo com o jogador seguro (achado ao
        vivo 23/07: Charlotte Pudding PRB02-010, custo 7/poder 5000, nunca
        jogada apesar de DON suficiente e 4 copias vistas na mao ao longo da
        partida contra o Mihawk, porque cost>=8 nunca a incluia).
        """
        if effective_hand_play_cost(self.me, card, self.opp) > self.me.don_available:
            return False
        if card.card_type != 'CHARACTER':
            return False
        return self.avaliar_carta(card) > self._reserve_break_cost()

    def _don_usable_for_play(self, card, don_reserve: int | None = None) -> int:
        if don_reserve is None:
            don_reserve = self._don_reserve_for_defense()
        don_usable = max(0, self.me.don_available - don_reserve)
        if effective_hand_play_cost(self.me, card, self.opp) > don_usable \
                and self._can_spend_reserved_don_for_play(card):
            return self.me.don_available
        return don_usable

    def don_minus_delays_hand_curve(self, count: int = 1) -> bool:
        """Retornar DON atrasa uma carta relevante que ainda esta na mao?"""
        total = self.me.don_on_field()
        if count <= 0 or total <= 0:
            return False
        future = [c for c in self.me.hand
                  if c.card_type in ('CHARACTER', 'STAGE', 'EVENT')
                  and c.cost > total
                  and (self.avaliar_carta(c) >= 60
                       or (c.cost >= 7 and c.counter <= 0))]
        if not future:
            return False
        target = min(c.cost for c in future)
        turns_without = max(0, (target - total + 1) // 2)
        turns_with = max(0, (target - (total - count) + 1) // 2)
        # Mesmo quando o ceil nao muda com uma unica devolucao, retornar
        # repetidamente consome a folga que permitiria atingir a bomba.
        return turns_with > turns_without or total < target

    def ramp_curve_value(self, amount: int = 1) -> float:
        """Valor marginal de ramp para as cartas que o plano quer jogar.

        Nao e bonus fixo de categoria: so vale quando o DON extra antecipa
        uma carta relevante da mao ou a win-con derivada do deck.
        """
        if amount <= 0:
            return 0.0
        total = self.me.don_on_field()
        relevant = [c for c in self.me.hand
                    if c.card_type in ('CHARACTER', 'STAGE', 'EVENT')
                    and c.cost > total
                    and self.avaliar_carta(c) >= 70]
        plan = compute_game_plan(self.me)
        target = plan.get('don_target')
        targets = [c.cost for c in relevant]
        if target:
            targets.append(int(target))
        if not targets:
            return 15.0 * amount
        nearest = min(t for t in targets if t > total) if any(t > total for t in targets) else total
        before = max(0, (nearest - total + 1) // 2)
        after = max(0, (nearest - (total + amount) + 1) // 2)
        value = 35.0 * amount
        if after < before:
            value += 55.0
        if nearest - total <= 3:
            value += 25.0
        return value

    def cheap_board_redundancy_penalty(self, card: 'Card') -> float:
        """Custo marginal de mais um corpo barato/repetido no campo."""
        if card.card_type != 'CHARACTER' or card.cost > 2:
            return 0.0
        cheap = sum(1 for c in self.me.field_chars if c.cost <= 2)
        copies = sum(1 for c in self.me.field_chars if c.code == card.code)
        penalty = max(0, cheap - 1) * 18.0 + copies * 55.0
        if card.power <= 2000:
            penalty += max(0, cheap - 2) * 15.0
        return penalty

    def don_opportunity_cost(self, count: int = 1) -> float:
        """Custo do DON agora, incluindo a melhor jogada que ele bloquearia."""
        if count <= 0:
            return 0.0
        playable = [c for c in self.me.hand
                    if effective_hand_play_cost(self.me, c, self.opp) <= self.me.don_available
                    and self.avaliar_carta(c) >= 70]
        base = 25.0 * count
        if playable and any(effective_hand_play_cost(self.me, c, self.opp)
                            > self.me.don_available - count for c in playable):
            base += min(90.0, max(self.avaliar_carta(c) for c in playable) * 0.45)
        return base

    def don_return_trigger_value(self, count: int = 1) -> float:
        """Valor dos efeitos proprios que uma devolucao de DON dispara agora."""
        if count <= 0:
            return 0.0
        cards = [self.me.leader, *self.me.field_chars]
        if self.me.field_stage:
            cards.append(self.me.field_stage)
        ee = EffectExecutor(self.me, self.opp)
        total = 0.0
        marker = (self.me.global_turn, 'when_don_returned')
        for source in cards:
            entry = get_card_effects(source.code).get('when_don_returned')
            if not entry or count < entry.get('return_count_gte', 1):
                continue
            timing = entry.get('owner_turn')
            if timing == 'your' and not self.me.is_active_turn:
                continue
            if timing == 'opponent' and self.me.is_active_turn:
                continue
            if (entry.get('once_per_turn')
                    and getattr(source, '_event_once_marker', None) == marker):
                continue
            if not ee._check_conditions(entry.get('conditions', {}), source):
                continue
            for step in entry.get('steps', []):
                if not ee._step_is_viable(step, source):
                    continue
                action = step.get('action')
                amount = int(step.get('count', 1) or 1)
                if action == 'add_don':
                    total += self.ramp_curve_value(amount) + 20.0 * amount
                elif action == 'draw':
                    total += 55.0 * amount
                elif action in ('set_don_active', 'set_active'):
                    total += 30.0 * amount
                elif action in ('ko', 'ko_opp', 'bounce',
                                'place_opp_character_bottom_deck'):
                    total += 70.0 * amount
                else:
                    total += 20.0
        return total

    def don_minus_opportunity_cost(self, count: int = 1) -> float:
        """Custo liquido de DON-minus depois dos triggers realmente ativos."""
        return max(0.0, self.don_opportunity_cost(count)
                   - self.don_return_trigger_value(count))

    def has_valuable_don_return_trigger(self, count: int = 1) -> bool:
        """A devolucao ativa algum beneficio material no estado atual?"""
        return self.don_return_trigger_value(count) > 0

    def should_pay_removal_substitute(self, target: 'Card', cost: dict,
                                      payer: 'Card | None' = None) -> bool:
        """
        Compara o corpo preservado com o recurso irreversivel da protecao.

        `payer`: quem PAGA o custo -- pode ser diferente de `target` (quem
        e SALVO) numa substituicao EXTERNA (ex: Zoro se trasha pra salvar
        um aliado Straw Hat Crew diferente). Default None = autoprotecao
        (target paga por si mesmo, payer=target).

        Achado real (bug ha muito tempo no banco, achado 24/07): pra
        action=='trash_self', o preco era fixado em `saved` (o MESMO
        valor de `target`) -- em autoprotecao isso vira `saved > saved`,
        SEMPRE falso, entao a substituicao nunca disparava (Thatch OP08-045
        nunca trocava a remocao por trash_self+draw). Em protecao externa
        o bug e o mesmo (o preco real e o valor do PAGADOR, nao do alvo
        salvo -- podem ser cartas bem diferentes).
        """
        saved = self.analyzer.char_value_score(target)
        action = cost.get('action')
        count = int(cost.get('count', 1) or 1)
        if action == 'trash_self':
            pagador = payer if payer is not None else target
            if pagador is target:
                # Autoprotecao: a carta ja seria perdida pela remocao
                # ORIGINAL de qualquer jeito -- substituir so troca COMO
                # ela e perdida (remocao do oponente sem nada -> descarte
                # proprio com o bonus dos extra_steps de graca). Preco
                # marginal e ~0, nao o valor da carta inteira.
                return True
            # Protecao externa: o pagador e sacrificado por INTEIRO pra
            # salvar um alvo DIFERENTE -- so nao vale se o protetor for
            # nitidamente MAIS valioso que quem esta sendo salvo. >=, nao
            # > estrito: cartas de protecao dedicadas (ex: Vista OP12-027,
            # Zoro OP15-094) sao pensadas pra proteger aliados de valor
            # parecido/maior, empate nao deve travar o efeito.
            return saved >= self.analyzer.char_value_score(pagador)
        if action in ('return_own_don', 'don_minus'):
            price = self.don_minus_opportunity_cost(count)
            if (self.don_minus_delays_hand_curve(count)
                    and self.don_return_trigger_value(count) <= 0):
                price += 45.0
        elif action == 'rest_don':
            price = self.don_opportunity_cost(count)
        else:
            return True
        return saved > price

    def combat_self_buff_has_relevant_actor(
            self, actor: 'Card', actor_defending: bool | None,
            defender_uid: int, attacker_power: int,
            defender_power: int) -> bool:
        """Valida se um buff de combate no proprio ator pode afetar a luta."""
        if attacker_power <= 0 or defender_power < 0:
            return False
        if actor_defending is True:
            return defender_uid == getattr(actor, '_deck_uid', 0)
        return True

    # ── Distribuição de DON ───────────────────────────────────────────────────

    # ── Ordem e escolha de ataques ────────────────────────────────────────────

    def _rest_activates_effect(self, card) -> bool:
        """
        Decide se restar este personagem (atacando) ativa um efeito útil,
        justificando o ataque mesmo sem chance de passar.

        Verdadeiro quando:
        - tem [When Attacking] que vai produzir efeito real agora (checado
          via _step_is_viable -- achado real 10/07: antes bastava TER a
          chave when_attacking, sem checar se o efeito tem alvo/material.
          Catarina Devon "select 1 personagem do oponente, copia o poder"
          contava como "vale atacar mesmo sem chance de passar" mesmo com
          o campo do oponente VAZIO -- o bot declarava um ataque de 3000
          contra lider de 5000 sem nenhum beneficio real, so por ter a
          chave presente), OU
        - tem efeito [Your Turn]/[Opponent's Turn] que depende de estar restado
          (ex: Shanks — restado dá -1000 a todos os personagens do oponente).
        """
        effects = get_card_effects(card.code)
        wa = effects.get('when_attacking')
        if wa:
            # Achado real 03/08: resolve "Choose one" (choice) quando
            # `steps` vem vazio -- Queen OP04-040 (lider) e Yosaku & Johnny
            # (personagem) tem when_attacking assim. Sem isso vazio =
            # "sem estrutura", cai no fallback permissivo True por
            # acidente em vez de checar viabilidade de verdade.
            steps = resolve_choice_for_scoring(wa, card, self.me, self.opp)
            # Ainda sem steps (texto cru sem parse nenhum, nem choice):
            # mantem comportamento antigo, nao ha como checar viabilidade
            # sem estrutura.
            if not steps:
                return True
            ee = EffectExecutor(self.me, self.opp)
            if any(ee._step_is_viable(s, card) for s in steps):
                return True
        # efeitos que se beneficiam de estar restado
        txt = (card.card_text or '').lower()
        if ('when this character becomes rested' in txt or
                'if this character is rested' in txt or
                'while this character is rested' in txt):
            return True
        return False

    def _rest_only_attack_value(self, attacker) -> float:
        """
        Valor de um ataque que só se justifica pelo gatilho de restar
        (nenhuma chance de causar dano/matar). Genérico — deriva o valor do
        que o [When Attacking] do PRÓPRIO atacante realmente faz (remoção,
        vantagem de carta, buff de poder, etc.), não de qual carta é.
        Sem [When Attacking] estruturado mas com efeito textual condicionado
        a estar restado (_rest_activates_effect via texto cru), usa um piso
        conservador — mesma categoria "efeito desconhecido" que o valorador
        de gatilhos condicionados a DON usa (OPTCGMatch._trigger_don_value),
        replicada aqui pois é uma classe diferente (DecisionEngine).
        """
        effects = get_card_effects(attacker.code)
        wa = effects.get('when_attacking')
        if not wa:
            return 40.0
        # Achado real 03/08: resolve "Choose one" quando `steps` vem vazio
        # -- sem isso, Queen OP04-040 caia sempre no piso 40 generico em
        # vez do valor real da opcao (ex: ko/rest_opp = 120).
        steps = resolve_choice_for_scoring(wa, attacker, self.me, self.opp)
        if not steps:
            return 40.0
        actions = [s.get('action') for s in steps]
        if any(x in ('ko', 'rest_opp', 'debuff_power', 'bounce') for x in actions):
            valor = 120
            if self.opp.field_chars: valor += 30
        elif any(x in ('draw', 'add_to_hand', 'look_top_deck') for x in actions):
            valor = 90
        elif any('power' in str(x) for x in actions):
            valor = 60
        else:
            valor = 40
        return valor

    def _rest_attack_has_material_benefit(self, card) -> bool:
        """Ataque sem alcance exige mudanca real de recurso ou de board.

        O buff do proprio combate ja esta em attack_time_power. Peek/reveal
        puro traz informacao, mas nao justifica um ataque que continua abaixo.

        FASE B do Turn Planner (usuario, 24/07): antes so reconhecia o
        gatilho "quando restado" via SUBSTRING no texto cru (fallback
        fragil, sem checar condicoes) -- agora checa primeiro o trigger
        ESTRUTURADO `when_rested` do banco (6 cartas confirmadas, ver
        TODO.md: OP14-021/027/028/032/035/119), respeitando `conditions`
        igual a qualquer outro gatilho -- a substring fica so como
        fallback pra texto que o parser ainda nao capturou.
        """
        wr = get_card_effects(card.code).get('when_rested')
        if wr:
            wr_conds = wr.get('conditions', {})
            if not wr_conds or EffectExecutor(self.me, self.opp)._check_conditions(wr_conds, card):
                return True
        wa = get_card_effects(card.code).get('when_attacking')
        if not wa:
            txt = (card.card_text or '').lower()
            return ('when this character becomes rested' in txt
                    or 'if this character is rested' in txt
                    or 'while this character is rested' in txt)
        # Achado real 03/08: resolve "Choose one" quando `steps` vem vazio.
        steps = resolve_choice_for_scoring(wa, card, self.me, self.opp)
        if not steps:
            return False
        informational_or_combat_only = {
            'buff_power', 'set_base_power', 'look_top_deck',
            'peek_opp_deck_top', 'reveal_deck_top',
        }
        ee = EffectExecutor(self.me, self.opp)
        return any(s.get('action') not in informational_or_combat_only
                   and ee._step_is_viable(s, card) for s in steps)

    def score_attack_target(self, attacker: 'Card',
                             target_type: str,
                             target: 'Optional[Card]') -> float:
        """
        Pontua um alvo de ataque levando em conta múltiplos fatores.
        """
        a = self.analyzer
        s = 0.0
        opp_life  = self.opp.life_count()
        # Poder NO ATAQUE: inclui buffs de [When Attacking] proprios
        # (ex: Devon OP16-104 copia o poder de um personagem do oponente)
        atk_power = attack_time_power(attacker, self.opp)

        # Custo de restar um atacante que tem [Activate: Main] útil:
        # atacar com ele perde o efeito do turno. Desconta, salvo letal/ameaça grande.
        activate_cost = self._activate_main_value(attacker)

        if target_type == 'leader':
            don_disp  = self.me.don_available
            # +power_buff: mesmo achado do bloco HANDOFF 434
            # (don_needed_for_attack) -- lider com defesa reativa/buff
            # ja ativo (ex: Lucy OP15-002) ficava invisivel aqui tb,
            # inflando pode_passar/passa_sem_don com o poder BASE em vez
            # do poder real de defesa (o que _execute_attack de fato usa).
            leader_power = self.opp.leader.power + self.opp.leader.power_buff

            # REGRA DURA (validada com o usuário):
            # Ataque ao líder só vale se:
            #  (a) poder do atacante >= poder-base do líder (passa sem DON), OU
            #  (b) poder + DON disponível >= poder-base do líder (passa com DON), OU
            #  (c) restar o personagem ativa um efeito útil (When Attacking, ou
            #      efeito Your Turn/Opp Turn que depende de estar restado).
            passa_sem_don = atk_power >= leader_power
            passa_com_don = (atk_power + don_disp * 1000) >= leader_power
            vale_restar   = self._rest_attack_has_material_benefit(attacker)
            pode_passar   = passa_sem_don or passa_com_don

            if not (pode_passar or vale_restar):
                return -999  # ataque inútil: não passa e não ativa nada — barra

            if not pode_passar:
                # Mesmo caso do alvo-personagem: ataque sem NENHUMA chance de
                # causar dano só vale pelo gatilho de restar, nunca pelos
                # bônus de pressão de vida abaixo (esses pressupõem que o
                # ataque tem chance real de conectar).
                s = self._rest_only_attack_value(attacker)
                if activate_cost > 0 and opp_life > 1:
                    s -= activate_cost
                return s

            # Pontua os ataques validos. Vida 0/1 so vira prioridade maxima
            # quando o conjunto de ataques realmente garante lethal; com
            # blockers/counters suficientes, atacar leader ainda e pressao,
            # mas nao deve soterrar as outras acoes.
            lethal_now = a.can_lethal_this_turn()
            s = ATTACK_LEADER_BASE_SCORE
            # Sem letal CERTIFICADO (can_lethal_this_turn exige sobreviver ao
            # pior caso de defesa do oponente), o valor "nao lethal" ainda
            # precisa superar de forma confiavel um ataque a Character
            # legitimamente valioso -- 220/130 nao garantiam isso. Achado
            # real 08/08 (usuario, primeira vitoria ao vivo -- "poderia ter
            # ganho 1 turno antes"): com vida 0, ataque ao lider com folga
            # real de poder (2000, sem precisar de DON) pontuava so 130,
            # perdendo pra matar um Character com ameaca recorrente (Stussy,
            # 220 -- lock_opp_character_attack em activate_main). Remover
            # uma ameaca so vale se o jogo CONTINUAR; um acerto na vida com
            # 0/1 restante pode ACABAR o jogo agora -- valor assimetrico que
            # os 130/220 antigos nao refletiam. Ainda abaixo do bonus de
            # prioridade LETHAL (+500, cenario com letal certificado de
            # verdade), preservando a ordem: certificado > vida critica > alvo generico.
            if opp_life == 1:
                s = 500 if lethal_now else 260
            if opp_life == 0:
                s = 10000 if lethal_now else 300

            # Penaliza levemente se precisa de muito DON (mas ainda é válido)
            opp_defense = leader_power + a.opp_counter_potential()
            if atk_power < opp_defense and not passa_sem_don:
                s -= 10

            # Unblockable: o ataque não pode ser bloqueado. Vale mais quando o
            # oponente tem blockers (passa onde os outros seriam interceptados).
            if (attacker.has_unblockable or attacker.unblockable_this_turn) and self.opp.blockers_active():
                s += 40

            # Double Attack/Banish só compõem valor de verdade contra a VIDA
            # (2 cartas de vida em vez de 1 / vida trashed em vez de ir pra
            # mão do oponente, negando trigger) -- contra um Character são
            # irrelevantes (Character não tem "vida dupla"). Sem isto, um
            # atacante com essas keywords pontuava o líder igual a um
            # atacante comum e podia preferir atacar um Character só porque
            # este tinha score de remoção mais alto (achado real 02/08, log
            # Portgas.D.Ace-R x Portgas.D.Ace-R: líder com Double Attack via
            # Edward Newgate [OP16-003] atacou um Character em vez da vida).
            if attacker.is_double_attack():
                s += 60
            if attacker.has_banish or attacker.banish_this_turn:
                s += 45

            # Custo de perder o Activate Main: desconta, salvo se for letal
            if activate_cost > 0 and opp_life > 1:
                s -= activate_cost
            return s

        elif target_type == 'character' and target:
            don_disp = self.me.don_available
            # REGRA DURA (mesma do líder, validada com o usuário):
            # só ataca personagem se:
            #  (a) poder >= poder do alvo (mata sem DON), OU
            #  (b) poder + DON disponível >= poder do alvo (mata com DON), OU
            # Contra Character nao existe excecao por gatilho: o alvo so e
            # estrategicamente valido quando o poder final do ataque pode
            # alcanca-lo. Um [When Attacking] util pode justificar declarar
            # um ataque, mas deve usar outro alvo alcancavel (inclusive o
            # Leader), nunca um Character maior que atacante + DON disponivel.
            # +power_buff: mesmo achado do bloco 434/leader acima -- alvo
            # com buff de poder ja ativo (battle_only ou nao) precisa da
            # mesma conta que _execute_attack usa de verdade.
            target_power = target.power + target.power_buff
            passa_sem_don = atk_power >= target_power
            passa_com_don = (atk_power + don_disp * 1000) >= target_power
            pode_matar    = passa_sem_don or passa_com_don

            if not pode_matar:
                return -999

            # Valor do alvo (quão importante é removê-lo) — só chega aqui
            # quando o ataque TEM chance real de matar (com ou sem DON).
            s = target.board_value() * 15
            don_needed = max(0, (target_power - atk_power + 999) // 1000)
            s -= self.don_opportunity_cost(don_needed)

            # Alvo COM EFEITO vale matar mesmo com poder baixo/0 (regra do
            # usuário) -- `threat_w` vem da MESMA fonte de peso que
            # `future_threat_value`/`critical_threats` usam pro board do
            # oponente (dedupe 09/08, auditoria bloco 475: esta função e
            # `future_threat_value` liam o mesmo conceito -- "esse corpo é
            # ameaça de efeito?" -- com pesos/triggers diferentes, sem
            # reuso; a versão antiga inclusive somava `activate_main` e
            # `blocker` DUAS vezes, uma via `efeito_ameaca`/`tem_efeito_
            # alvo` e outra via checagem individual, achado lateral desta
            # mesma auditoria). `on_ko`/`rush` continuam separados porque
            # têm semântica PRÓPRIA neste contexto (matar, não continuar
            # vivo) que não faz sentido do lado de `future_threat_value`.
            tgt_effects = get_card_effects(target.code)
            threat_w = a._effect_threat_weight(target)
            if threat_w and target.power <= 2000:
                s += 50   # remover utilidade do oponente vale, apesar do poder baixo
            s += threat_w

            if target.has_rush or target.rush_this_turn:  s += 40
            if 'on_ko' in tgt_effects:  s -= 20  # cuidado: matar pode ativar algo do oponente

            # FASE B do Turn Planner (usuario, 24/07: combos mapeados
            # devem entrar na ordem de ataque). Meu proprio board pode
            # observar "quando o personagem do OPONENTE e K.O.'d"
            # (on_opp_char_ko, fase 1.2, 24/07 -- ex: Kaido OP01-061,
            # Rob Lucci OP03-076). Sem isto, matar o alvo certo pra
            # acionar esse gatilho nunca pesava na escolha de alvo.
            meus = [self.me.leader, *self.me.field_chars]
            if self.me.field_stage:
                meus.append(self.me.field_stage)

            def _on_opp_char_ko_pronto(c):
                entry = get_card_effects(c.code).get('on_opp_char_ko')
                if not entry:
                    return False
                req = entry.get('don_requirement', 0)
                return not req or c.don_attached >= req

            if any(_on_opp_char_ko_pronto(c) for c in meus):
                s += 30

            # Custo de perder o Activate Main do ATACANTE: só compensa se o alvo
            # é ameaça grande (poder alto, blocker, rush, gera vantagem).
            ameaca_grande = (target.power >= 5000 or target.has_blocker or target.blocker_this_turn or
                             target.has_rush or target.rush_this_turn or target.has_double_attack or target.double_attack_this_turn)
            if activate_cost > 0 and not ameaca_grande:
                s -= activate_cost

            return s

        return s

    def _activate_main_value(self, card) -> float:
        """
        Valor do efeito [Activate: Main] de um personagem — o "custo" de restá-lo
        atacando (perde o efeito do turno). 0 se não tem efeito ativável OU se a
        condição do efeito NÃO está satisfeita agora (não há o que preservar:
        regra do usuário — se não pode ativar, ataca normalmente).
        """
        effects = get_card_effects(card.code)
        am = effects.get('activate_main')
        if not am:
            return 0.0
        # Se o efeito não pode ativar agora (condição não satisfeita), não há
        # nada a preservar — custo zero, a IA pode atacar com ela.
        if not self._effect_conditions_met(card):
            return 0.0
        # Respeita once_per_turn: se já usou, não há efeito a preservar neste turno
        if am.get('once_per_turn') and getattr(card, '_am_used_turn', -1) == self.me.turn:
            return 0.0
        # So existe custo real se a habilidade EXIGE a carta ativa (rest_self).
        # Sem isso, atacar nao impede usar o Activate:Main no mesmo turno --
        # achado 09/07 (log 18.39.46): o lider Imu (trash_char_or_hand -> draw,
        # SEM rest_self) sofria esse desconto como se atacar custasse a
        # habilidade, quando as duas coisas sao independentes. Descontava
        # score de ataque do lider ate ficar negativo e o turno terminava com
        # DON parado e nada mais pra fazer com ele.
        if not any(c.get('type') == 'rest_self' for c in am.get('costs', [])):
            return 0.0
        # Achado real 03/08: resolve "Choose one" quando `steps` vazio --
        # sem isso, Catarina Devon (OP09-084, activate_main via choice)
        # sempre caia no piso 40 em vez de reconhecer a opcao de busca/draw.
        steps = resolve_choice_for_scoring(am, card, self.me, self.opp)
        actions = [s.get('action') for s in steps]
        if any(x in ('draw', 'look_top_deck', 'add_to_hand') for x in actions):
            return 70.0
        return 40.0

    # ── Decisões de defesa ────────────────────────────────────────────────────

    def should_use_blocker(self, attacker_power: int) -> 'Optional[Card]':
        """
        Decide se usa blocker e qual usar.

        Fatores:
        - Valor da minha vida (poucos = mais defensivo)
        - Probabilidade de trigger na vida
        - Valor do personagem que está sendo atacado vs valor do blocker
        """
        a = self.analyzer
        my_life = self.me.life_count()
        opp_life = self.opp.life_count()

        # Com muita vida, não usa blocker
        if my_life > 4:
            return None

        blockers = self.me.blockers_active()
        if not blockers:
            return None

        # Analisa se vale usar blocker
        # Quanto mais baixa a vida, mais agressivo na defesa
        use_threshold = {5: False, 4: False, 3: True, 2: True, 1: True}
        if not use_threshold.get(my_life, True):
            # Com 4 vidas e oponente pressionando (≤ 2 vidas), vale bloquear
            if opp_life > 2:
                return None

        # Custo EFETIVO de sacrificar `c` como blocker: char_value_score
        # (quanto vale o corpo) MENOS o proprio [On K.O.] dele (achado
        # 24/07 -- deixar ele morrer nao e perda pura quando o K.O. em si
        # ja compensa parte do custo, ex: draw/vida/DON). Reusa
        # `on_ko_value` (modulo, ja usada por select_counter_cards/
        # redirect_option_value pro MESMO tipo de decisao) em vez de uma
        # tabela nova -- achado ao preparar telemetria (24/07): a 1a
        # versao desta funcao reimplementava uma tabela mais fraca sem
        # perceber que essa ja existia, cobrindo mais tipos de acao e
        # checando alvos REAIS no campo do oponente pra ko/rest_opp.
        def custo_sacrificio(c):
            return a.char_value_score(c) - on_ko_value(c.code, self.opp, owner=self.me)

        # Com 1-2 vidas, usa o blocker de menor custo -- mas so se o custo
        # couber no teto (BLOCK_CRITICAL_LIFE_MAX_COST), quando definido.
        # None preserva o comportamento antigo (sempre bloqueia, sem
        # check de custo).
        if my_life <= 2:
            melhor = min(blockers, key=custo_sacrificio)
            if (BLOCK_CRITICAL_LIFE_MAX_COST is None
                    or custo_sacrificio(melhor) <= BLOCK_CRITICAL_LIFE_MAX_COST):
                return melhor
            return None

        # Com 3 vidas, usa se o atacante é forte -- mesmo teto de custo de
        # vida<=2 (29/07, bloco HANDOFF 398: generaliza o cost-check pros
        # outros niveis de vida que ja tinham condicao de "atacante forte"
        # mas nenhum check de custo do blocker em si). Validado via self-play
        # pareado (5 lideres/decks/seed=7, 50 partidas por variante): COM
        # extensao 52% (26/50) vs SEM extensao 42% (21/50) -- bate o baseline
        # em 4/5 lideres, valor final aplicado.
        if my_life == 3 and attacker_power >= self.me.leader.power:
            melhor = min(blockers, key=custo_sacrificio)
            if (BLOCK_CRITICAL_LIFE_MAX_COST is None
                    or custo_sacrificio(melhor) <= BLOCK_CRITICAL_LIFE_MAX_COST):
                return melhor
            return None

        # Com 4 vidas e oponente com ≤ 2 vidas: bloqueia apenas atacantes fortes
        if my_life == 4 and opp_life <= 2 and attacker_power >= self.me.leader.power:
            melhor = min(blockers, key=custo_sacrificio)
            if (BLOCK_CRITICAL_LIFE_MAX_COST is None
                    or custo_sacrificio(melhor) <= BLOCK_CRITICAL_LIFE_MAX_COST):
                return melhor
            return None

        return None

    def pick_counters(self, needed: int,
                      pool: 'list[tuple[int, Card]] | None' = None
                      ) -> tuple[list['Card'], float, int]:
        """
        Escolhe o conjunto de counters que cobre `needed` MINIMIZANDO o
        valor perdido (pitch_cost_as_counter), nao o stat de counter.
        pool: [(valor_de_counter, carta)] — por padrao os personagens com
        stat impresso na mao; sim_bridge passa um pool maior incluindo
        EVENTOS [Counter] elegiveis.
        Retorna (cartas, gasto, total_coberto). total < needed = nao cobre
        (cartas vem vazias nesse caso — nunca counter parcial).
        Guloso por pitch crescente + alternativa de carta unica: cobre o
        caso "uma carta grande barata de pitchar vale mais que tres
        pequenas caras" sem precisar de knapsack completo.
        """
        if pool is None:
            pool = [(effective_counter(c, self.me), c) for c in self.me.hand
                     if effective_counter(c, self.me) > 0]
        if needed <= 0 or not pool:
            return [], 0.0, 0

        custo = {id(c): self.pitch_cost_as_counter(c) for _, c in pool}
        # pitch menor primeiro; empate = counter maior (cobre mais rapido)
        ordenado = sorted(pool, key=lambda item: (custo[id(item[1])], -item[0]))
        escolha, gasto, total = [], 0.0, 0
        for valor, c in ordenado:
            if total >= needed:
                break
            escolha.append(c)
            gasto += custo[id(c)]
            total += valor
        if total < needed:
            return [], 0.0, total

        # Alternativa: UMA carta que cobre sozinha por gasto menor
        singles = [(custo[id(c)], valor, c) for valor, c in pool if valor >= needed]
        if singles:
            g1, v1, c1 = min(singles, key=lambda t: t[0])
            if g1 < gasto:
                return [c1], g1, v1
        return escolha, gasto, total

    def buff_wins_combat(self, defender_power: int, threat_power: int,
                         buffed_power: int) -> bool:
        """
        Regra de COMBATE do OPTCG (motor unico): um defensor so sobrevive a uma
        ameaca se ficar ESTRITAMENTE acima -- EMPATE vai pro ATACANTE. Decide se
        um buff de poder (counter/reacao) SALVA quem esta/ficara sob ataque:
        `defender_power <= threat_power < buffed_power`. Generica (so numeros),
        serve pra QUALQUER carta/lider de qualquer deck. Consolidada aqui pra o
        sim_bridge (ordenacao de alvo de buff) NAO ter regua propria -- antes as
        duas checagens divergiam (`<` vs `<=`) e o buff ia pro corpo errado no
        empate (Ground Death, log 21.01.22).
        """
        return defender_power <= threat_power < buffed_power

    def debuff_flips_attack_in_my_favor(self, target_power: int, debuff_amount: int,
                                        my_attacker_power: int) -> bool:
        """
        Espelho de `buff_wins_combat`, do lado OFENSIVO: eu sou o ATACANTE
        (empate ja favorece MIM), entao um debuff no DEFENSOR vira o combate a
        meu favor se ele cair pra <= meu poder: `target_power - debuff <=
        my_attacker_power`. Motor unico, generico (so numeros) -- decide se um
        debuff [When Attacking] (ex: Nosjuro) deve mirar o alvo do MEU proprio
        ataque em vez de "a maior ameaca ativa" generica, que ignorava o
        combate em andamento (achado ao vivo 14/07, log 12.02.31: Nosjuro
        atacando Law 9000 com 7000 de poder debuffou Hawkins, sem ligacao
        nenhuma com esse ataque).
        """
        return target_power - debuff_amount <= my_attacker_power

    def would_lose_last_defender(self, p, card) -> bool:
        """
        Trashar/perder `card` deixa p SEM defensor real? = e o ultimo corpo E
        ele de fato defende (body_provides_defense). Motor unico decide se vale
        proteger o "ultimo corpo" no custo de trash; generico, sem nome de
        carta (log 01.23.31: corpo morto nao conta como ultimo defensor).
        """
        return len(p.field_chars) <= 1 and self.body_provides_defense(card)

    def body_provides_defense(self, card) -> bool:
        """
        Um personagem em campo oferece valor DEFENSIVO real (segura um golpe)?
        So com poder > 0 OU Blocker. Corpo de 0 poder sem blocker (ex: enabler
        ja usado) nao protege o lider de nada -- generico, sem nome de carta.
        Usado pra o custo de trash nao "proteger" um corpo morto como se fosse
        ultimo defensor (log 01.23.31).
        """
        if card is None:
            return False
        return (getattr(card, 'power', 0) > 0
                or getattr(card, 'has_blocker', False)
                or getattr(card, 'blocker_this_turn', False))

    def trash_cost_board_perda(self, card, p) -> float:
        """
        Custo situacional de trashar `card` do MEU campo pra pagar um custo de
        trash (draw do lider Imu, etc.). Motor unico, generico (zero nome de
        carta). Um corpo DEAD-WEIGHT (sem valor defensivo E que ja passou o
        turno de entrada -> 0 poder parado, nao ataca nem defende, on-play ja
        gasto) e o MAIS BARATO de largar: perda minima, pra vir antes de cartas
        da MAO (que guardam opcionalidade). Antes o corpo morto "sobrevivia"
        porque a comparacao cruzava duas reguas (char_value_score no campo vs
        _trash_value na mao) e um stage redundante da mao pontuava mais baixo --
        o lider trashava a mao e mantinha a Shalria morta no campo a partida
        toda (achado ao vivo 14/07, logs 01.23.31 e 02.34.18).
        """
        if card is None:
            return 0.0
        # dead weight = sem valor defensivo (0 poder, sem blocker) E sem efeito
        # ATIVO futuro (when_attacking/activate_main). Um corpo assim nao ataca,
        # nao defende e nao vai fazer nada -- mesmo RECEM-JOGADO (o on-play ja
        # resolveu na entrada). Largar nao perde nada -> trasha PRIMEIRO, antes
        # de cartas da mao. (So poder>0/blocker/efeito futuro merece o just_played
        # +35 abaixo; Shalria de 0 poder so tinha on_play.)
        if not self.body_provides_defense(card):
            _eff = get_card_effects(card.code)
            _wa = _eff.get('when_attacking', {})
            _am = _eff.get('activate_main', {})
            # Achado real 03/08: `.get('steps')` sozinho vinha vazio pra
            # "Choose one" (choice) -- Catarina Devon (activate_main) caia
            # como "sem efeito futuro" (score -999, trasha primeiro) mesmo
            # tendo uma opcao real disponivel.
            _tem_futuro = bool(_wa.get('steps') or _wa.get('choice')
                               or _am.get('steps') or _am.get('choice'))
            if not _tem_futuro:
                return -999.0
        perda = self.analyzer.char_value_score(card)
        if getattr(card, 'just_played', False):
            perda += 35            # recem-entrado: corpo+efeito a realizar
        if card.has_blocker or getattr(card, 'blocker_this_turn', False):
            perda += 25            # defesa recorrente
        if self.would_lose_last_defender(p, card):
            perda += 40            # ultimo defensor real: lider exposto
        return perda

    def should_use_counter(self, atk_power: int, def_power: int,
                           counter_avail: int | None = None,
                           gasto: float | None = None) -> bool:
        """
        Decide se countera um ataque no LIDER por GANHO LIQUIDO (regra do
        usuario: caso a caso, nunca threshold fixo por categoria):
        countera se o CUSTO das cartas gastas (pitch_cost_as_counter, que
        desconta o proprio papel de counter) fica ABAIXO do valor da vida
        que o golpe tiraria (life_redirect_cost — mesma regua ja usada em
        redirect/reaction). Substitui os gates fixos por faixa de vida
        (achado real 11/07, duas pontas do mesmo bug: com 4 vidas gastava
        counter em jab 5000v5000 [needed=1 passava no gate <=1000]; com
        menos vida recusava ataque serio porque needed>2000 estourava o
        gate da faixa — mesmo com +2000/+1000 na mao cobrindo).

        counter_avail/gasto: override de quem ja montou o pool completo
        (sim_bridge inclui eventos [Counter], que counter_in_hand() nao
        enxerga). Sem override, calcula dos personagens da mao via
        pick_counters (mesma selecao que use_counter executa).
        """
        if atk_power < def_power:
            return False  # defesa já suficiente
        needed = atk_power - def_power + 1
        my_life = self.me.life_count()

        if counter_avail is None or gasto is None:
            _, gasto, total = self.pick_counters(needed)
            counter_avail = total

        if counter_avail < needed:
            return False  # nunca counter parcial

        # Vida 0: qualquer golpe no líder = derrota. Paga o que for.
        if my_life <= 0:
            return True

        # Valor da vida na ESCALA do avaliar_carta (que roda bem mais
        # quente que a de char_value_score usada por life_redirect_cost —
        # um corpo jogavel de custo 5 avalia 100-150). Curva decrescente de
        # proposito: <=2 vidas = countera ate pitchando corpo bom (so nao
        # entrega a win-con, que avalia acima de 150 com a protecao do
        # GamePlan); vida alta = mais seletivo.
        #
        # FIX 24/07 (achado do usuario, partida real Katakuri x Jinbe): o
        # degrau antigo ({1:250, 2:150, 3:65}.get(my_life, 12.0)) caia de
        # 65 (vida 3) pra 12 (vida 4+) de uma vez so. Medido contra o
        # `gasto` REAL de counterar nessa partida (mesmo caminho ao vivo,
        # `select_counter_cards`): uma carta unica decente custa ~70-75
        # nessa conta com vida 4-5 (bem mais que os 100+ estimados no
        # comentario antigo, que nunca foi validado contra numero real) --
        # 12 ou mesmo um valor intermediario tipo 35 continuava MENOR que
        # isso, entao o bot seguia nunca counterando com 1 carta so.
        # Confirmado no log real: 9 ataques que deveriam ser counterados
        # (poder do golpe > defesa, counter elegivel na mao) com vida 4-5,
        # so 3 counterados; no historico completo (19 sessoes), 58/147
        # (~40%). Sem counter de carta, o bot caia pro fallback mais barato
        # -- a habilidade on_opp_attack do lider (+1000 poder por 1 DON,
        # opcional) -- esvaziando o DON que faltava depois pros proprios
        # ataques (ex: Pekoms ST34-005 sem DON pro K.O. do [When
        # Attacking], atacando "a toa").
        #
        # Escopo decidido com o usuario (24/07): cobrir SO o caso de 1
        # carta barata resolvendo um golpe normal (~70-75 de gasto) — golpes
        # grandes que exigem empilhar 2+ cartas (~100+ de gasto, visto no
        # mesmo log) continuam de fora, mudanca conservadora de proposito.
        valor_vida = {1: 250.0, 2: 150.0, 3: 65.0, 4: 85.0, 5: 75.0}.get(my_life, 12.0)
        valor_vida *= COUNTER_VALOR_VIDA_SCALE
        # MAO GORDA: com 6+ cartas o valor marginal de cada carta cai (nao
        # da pra jogar tudo) e counter fica proporcionalmente barato —
        # feedback real 12/07: "8 cartas na mao e levando dano toda hora".
        # +8 de orcamento por carta acima de 5 (mao 8 com 4+ vidas: 12->36,
        # cobre pitchar carta fraca num jab; nao chega perto de corpo bom).
        folga = len(self.me.hand) - 5
        if folga > 0:
            valor_vida += 8.0 * min(folga, 5)
        return gasto < valor_vida

    def use_counter(self, needed: int) -> int:
        """
        Usa counters cobrindo `needed` com o MENOR valor perdido (mesma
        selecao de pick_counters que should_use_counter usou pra decidir
        — as duas pontas nao podem divergir).
        """
        escolha, _, total = self.pick_counters(needed)
        for c in escolha:
            remove_by_identity(self.me.hand, c)
            self.me.trash.append(c)
            self.me.counters_used += c.counter
        return sum(c.counter for c in escolha)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def choose_to_trash(self, hand: list) -> 'Optional[Card]':
        """
        Escolhe a carta de menor valor situacional para descartar --
        delega pra EffectExecutor._choose_to_trash (fonte unica), que usa
        _trash_value (avaliar_carta + protecoes especificas: evento-counter
        com desconto por redundancia, removal/bounce, carta cara/win-con do
        game_plan, carta que enche o trash pro combo, jogavel neste turno,
        reanimavel via play_from_trash). Antes desta correcao (25/07) esta
        funcao reimplementava com so `min(hand, key=self.avaliar_carta)` --
        divergencia real de "dois motores": o bot AO VIVO (unico chamador,
        via sim_bridge.py.resolve_prompt_choice) descartava pior do que o
        motor interno (EffectExecutor, usado por custo trash_from_hand em
        qualquer efeito/self-play), mesma classe de bug do achado Katakuri
        OP11-062 (comentario em _combat_buff_worth_paying).
        """
        if not hand:
            return None
        return EffectExecutor(self.me, self.opp)._choose_to_trash(hand)



# ===========================================================================
# OPTCGMatch — motor de partida
# Baseado no fluxo de turno das 34k linhas
# ===========================================================================

class OPTCGMatch:
    MAX_TURNS = 15

    def __init__(self, deck_a: tuple, deck_b: tuple, hide_opponent_info: bool = False):
        """
        hide_opponent_info (achado real 10/08, bloco 490 -- fecha a
        pendencia do simulador self x self, TODO bloco 370): quando True,
        seta `self_play_info_hidden = True` nos DOIS `GameState` -- os 2
        pontos do motor que hoje leem mao/deck do oponente DIRETO
        (`opp_counter_potential`/`_opp_can_remove_stage`, unico vazamento
        real encontrado na auditoria do bloco 370) passam a usar so o que
        foi REVELADO de verdade (`known_hand_cards`/`known_deck_cards`) +
        estimativa estatistica pro resto, igual o bot ao vivo ja faz.
        Default False preserva 100% do comportamento de sempre (bot ao
        vivo via sim_bridge.py/server.py NUNCA passa por aqui; toda
        ferramenta de tuning/auditoria existente -- audit_replay.py,
        baseline_metrics.py, tune_weights.py, via ReplayMatch -- continua
        full-info de proposito, decisao explicita do bloco 370: mais
        deterministico pra calibracao). Usado por `simulation_worker.py`
        (API `/simulate` do front-end, o simulador self x self de
        verdade), default True la.
        """
        leader_a, cards_a, stage_a = deck_a if len(deck_a) == 3 else (*deck_a, None)
        leader_b, cards_b, stage_b = deck_b if len(deck_b) == 3 else (*deck_b, None)

        self.state_a = GameState(leader=deepcopy(leader_a),
                                 deck=[deepcopy(c) for c in cards_a])
        self.state_b = GameState(leader=deepcopy(leader_b),
                                 deck=[deepcopy(c) for c in cards_b])
        if hide_opponent_info:
            self.state_a.self_play_info_hidden = True
            self.state_b.self_play_info_hidden = True

        # full_deck_census/full_deck_plan/full_deck_profile: achado 14/07
        # (pedido do usuario -- parar de so consertar o Imu) -- nenhum
        # desses campos era populado em lugar nenhum do motor real,
        # posture() sempre caia no fallback 'midrange' e compute_game_plan
        # sempre recalculava do zero. Extraido pra populate_full_deck_knowledge
        # (achado 03/08, bloco 426) pra ser reusado tambem por
        # ReplayMatch.__init__ (replay_optcg.py) e por server.py:_dto_to_gs
        # no lado hide_hidden do oponente -- nenhum dos dois populava isso
        # antes, forcando o fallback caro em TODO clone do Turn Planner
        # durante a simulacao do turno de resposta do oponente
        # (USE_OPPONENT_RESPONSE_SEARCH), alem de qualquer self-play/
        # auditoria via ReplayMatch.
        populate_full_deck_knowledge(self.state_a, cards_a, leader_a.code)
        populate_full_deck_knowledge(self.state_b, cards_b, leader_b.code)

        if random.random() < 0.5:
            self.state_a.is_first = True
            self.state_b.is_first = False
        else:
            self.state_a.is_first = False
            self.state_b.is_first = True

        self.global_turn = 0
        # replay_log: lista de eventos estruturados gerados durante a partida.
        # None = modo normal (sem logging extra). Definida para uma lista vazia
        # por simulate_replay() antes de chamar setup()+play_turn().
        self.replay_log: list | None = None
        self._suppress_replay_log: bool = False
        # nomes dos jogadores para o replay (preenchidos por simulate_replay)
        self._name_a = 'Player A'
        self._name_b = 'Player B'
        # decision_log: lista de registros de auditoria de decisão.
        # None = desligado. Ligado via enable_decision_audit().
        self.decision_log: list | None = None

        # OpponentModel de cada lado: construído a partir da decklist
        # COMPLETA do ADVERSÁRIO (state_a usa o deck de state_b para saber
        # contra o que está jogando, e vice-versa) -- a decklist completa é
        # sempre conhecida neste produto (colada pelo usuário ou carregada
        # de meta_decklists/user_decks), nunca estimada por arquétipo.
        # Usado por _simulate_sequence via DecisionEngine para substituir a
        # mão/vida REAL do oponente por amostras Monte Carlo plausíveis.
        self.model_for_a = OpponentModel(full_decklist=list(self.state_b.deck))
        self.model_for_b = OpponentModel(full_decklist=list(self.state_a.deck))

    def _human_pattern_bonus(self, p: GameState, kind: str, card: Optional[Card]) -> float:
        """Pequeno bonus por padroes humanos observados para este leader."""
        if card is None or not p or not p.leader:
            return 0.0
        _load_human_patterns()
        if not _HUMAN_PATTERN_BONUS_BY_LEADER:
            return 0.0
        leader_bonus = _HUMAN_PATTERN_BONUS_BY_LEADER.get(p.leader.code, {})
        return float(leader_bonus.get((kind, card.code), 0.0))

    # ── Setup (CheckStartOfGameActions das 34k linhas) ───────────────────────

    def _place_start_stage(self, p: GameState, opp: GameState = None):
        """
        Coloca o Stage inicial (proc.StartOfGame). Para leaders que puxam um Stage
        do deck no início (ex: Imu — "play up to 1 [Mary Geoise] type Stage").

        Escolha condicional ao matchup (regra confirmada por Arthur):
          - Default: o Stage de MAIOR custo (ex: The Empty Throne) — mais valor.
          - Stage de MENOR custo (Mary Geoise barata) SE:
              (a) MIRROR — oponente é o mesmo leader (sempre tem como atacar Stage alto), OU
              (b) o deck do oponente contém remoção de Stage que ALCANÇA o Stage caro
                  (K.O./trash/return de Stage do oponente com custo >= custo do Stage caro).
          Ver deck do oponente no setup é legítimo (decklist é conhecida nas 3 análises;
          só a MÃO não pode ser vista).
        """
        rule = next((r for r in get_card_game_rules(p.leader.code)
                     if r.get('type') == 'start_stage_from_deck'), None)
        if not rule:
            return
        wanted = str(rule.get('filter_type', '')).lower()

        candidates = [c for c in p.deck if c.card_type == 'STAGE'
                      and (not wanted or wanted in c.sub_types.lower()
                           or wanted in c.name.lower())]
        if not candidates:
            return

        caro = max(candidates, key=lambda c: c.cost)
        barato = min(candidates, key=lambda c: c.cost)

        usar_barato = False
        if caro.cost != barato.cost and opp is not None:
            # (a) mirror
            if opp.leader.code == p.leader.code:
                usar_barato = True
            # (b) oponente remove Stage com alcance >= custo do Stage caro
            elif self._opp_can_remove_stage(opp, caro.cost):
                usar_barato = True

        best = barato if usar_barato else caro
        # pop_by_identity, nao remove_by_identity -- consistencia defensiva
        # com o resto das remocoes de .deck (ver docstring de
        # pop_by_identity, achado 03/08) -- este ponto so roda 1x no setup
        # real, mas mesma fonte unica pra qualquer remocao de zona deck.
        best = pop_by_identity(p.deck, best)
        p.field_stage = best

    @staticmethod
    def _opp_can_remove_stage(opp: GameState, reach_cost: int) -> bool:
        """True se o deck do oponente tem carta que K.O./trasha/devolve um Stage
        do oponente (= nosso) com alcance de custo >= reach_cost.

        Le `opp.deck` inteiro (texto de TODA carta restante) — vazamento
        real de informacao oculta no self-play (ninguem sabe o conteudo do
        deck do adversario). `opp.self_play_info_hidden` (mesmo atributo
        dinamico de opp_counter_potential, default False, nunca setado
        hoje) restringe a busca as cartas JA REVELADAS
        (`known_deck_cards()`) — conservador de proposito: se a carta de
        remocao nao foi vista, assume que nao esta la, igual
        opp_counter_chunks_for_lethal faz pra counter."""
        deck = opp.known_deck_cards() if getattr(
            opp, 'self_play_info_hidden', False) else opp.deck
        for c in deck:
            t = (c.card_text or '').lower()
            # K.O./trash explicito do "opponent's stage", respeitando filtro de custo
            for mm in re.finditer(r"(k\.?o\.?|trash)[^.]*?opponent's stages?(?:[^.]*?cost of (\d+) or less)?", t):
                cap = mm.group(2)
                if cap and int(cap) < reach_cost:
                    continue
                return True
            # return stage to owner (bounce), sem filtro baixo
            for mm in re.finditer(r"return[^.]*?\bstages?\b[^.]*?to (?:its|the) owner", t):
                seg = t[max(0, mm.start() - 15):mm.end()]
                if 'this stage' in seg:
                    continue
                cm = re.search(r'cost of (\d+) or less', seg)
                if cm and int(cm.group(1)) < reach_cost:
                    continue
                return True
        return False

    def _mulligan_decision(self, hand, deck=None) -> tuple:
        """
        Decide mulligan seguindo o documento (pág. 2) e as regras do usuário.
        Chamado por replay_optcg.ReplayMatch.setup().

        Avalia (contagem simples — sinais bons vs ruins):
        - Jogada para T1/T2/T3: consigo aproveitar o DON de cada turno com as
          cartas baratas da mão? (não é 1 carta — é gastar o DON do turno)
        - Trigger demais na mão: relativo a quantos o deck tem (triggers valem
          mais na vida; ter muitos na mão desperdiça)
        - Tem searcher (bom: busca peça)
        - Tem ramp de DON (bom: acelera)
        - Counter de menos (ruim: sem defesa)
        Se sinais ruins > bons -> mulligan.
        """
        from optcg_engine.deck_census import deck_census
        non_leader = [c for c in hand if c.card_type != 'LEADER']
        custos = sorted(c.cost for c in non_leader)

        bons, ruins, motivos = 0, 0, []

        def aproveita_don(don_disp):
            restante = don_disp
            usadas = 0
            for c in custos:
                if c <= restante and c > 0:
                    restante -= c
                    usadas += 1
            return usadas > 0

        t1 = aproveita_don(1)
        t2 = aproveita_don(3)
        t3 = aproveita_don(5)
        jogadas_cedo = sum([t1, t2, t3])
        if jogadas_cedo >= 2:
            bons += 1
            motivos.append(f'curva ok (T1:{"s" if t1 else "n"} T2:{"s" if t2 else "n"} T3:{"s" if t3 else "n"})')
        else:
            ruins += 1
            motivos.append('mao lenta (sem jogadas para os primeiros turnos)')

        tem_searcher = any(getattr(c, 'is_searcher', False) or 'search' in c.card_text.lower()
                           for c in non_leader)
        if tem_searcher:
            bons += 1; motivos.append('tem searcher')

        tem_ramp = any('don' in c.card_text.lower() and
                       ('add' in c.card_text.lower() or 'active' in c.card_text.lower())
                       for c in non_leader)
        if tem_ramp:
            bons += 1; motivos.append('tem ramp de DON')

        if deck:
            census = deck_census(deck)
            trig_no_deck = max(1, census['trigger'])
            trig_na_mao = sum(1 for c in non_leader if getattr(c, 'has_trigger', False))
            if trig_na_mao >= 2 and trig_na_mao >= trig_no_deck * 0.5:
                ruins += 1
                motivos.append(f'trigger demais na mao ({trig_na_mao} de {trig_no_deck} do deck)')

        counters_mao = sum(1 for c in non_leader if getattr(c, 'counter', 0) >= 1000)
        if counters_mao == 0:
            ruins += 1; motivos.append('sem counter na mao')

        deve_trocar = ruins > bons
        resumo = '; '.join(motivos)
        return deve_trocar, resumo

    def setup(self):
        """
        Setup inicial conforme sequência das 34k linhas:
        CheckStartOfGameActions → DrawCard(5) → OfferMulligan → StartGame
        """
        for p in [self.state_a, self.state_b]:
            don_rule = next((r for r in get_card_game_rules(p.leader.code)
                             if r.get('type') == 'don_deck_size'), None)
            p.don_deck = int(don_rule['count']) if don_rule else 10
            random.shuffle(p.deck)

        # Regra oficial: efeitos "at the start of the game" resolvem depois
        # de definir o primeiro jogador, mas antes da mao inicial.
        ordered = ([self.state_a, self.state_b] if self.state_a.is_first
                   else [self.state_b, self.state_a])
        for p in ordered:
            opp_state = self.state_b if p is self.state_a else self.state_a
            self._place_start_stage(p, opp_state)

        for p in [self.state_a, self.state_b]:
            p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]

            # Mulligan se mão sem cartas de custo <= 2
            if not any(c.cost <= 2 for c in p.hand if c.card_type != 'LEADER'):
                p.deck.extend(p.hand)
                random.shuffle(p.deck)
                p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]

            life_count = p.leader.life if p.leader.life > 0 else 5
            p.life = [p.deck.pop() for _ in range(min(life_count, len(p.deck)))]


    # ── Fases do turno ───────────────────────────────────────────────────────

    def refresh_phase(self, p: GameState, opp: 'GameState | None' = None):
        """
        PlayerUntap das 34k linhas:
        - Retorna DON dado a cartas
        - Reseta rested/just_played/power_buff
        - Reseta once_per_turn
        - Reseta travas de ataque/rest/blocker (cannot_attack_until,
          cannot_be_rested_until, cannot_block_until) quando este jogador
          comeca seu turno.
          NOTA: o engine nao modela 'End Phase' como passo distinto do
          turno -- por isso 'until end of next turn' e 'until end of next
          End Phase' sao tratados de forma equivalente aqui (ambos resetam
          no refresh do jogador travado). A diferenca de granularidade
          entre os dois so importaria se algum efeito pudesse agir
          especificamente NA End Phase antes do refresh, o que o engine
          ainda nao simula.

        `opp` (opcional, so usado por lock_both_character_refresh): passiva
        SIMETRICA de Stage (achado 15/07, OP05-040 Birdcage/Doflamingo) que
        trava "nao ficar ativo" em AMBOS os campos, cost<=N, enquanto a
        fonte estiver em jogo (nao e freeze-1x como frozen_next_refresh).
        A fonte pode estar no campo de QUALQUER um dos 2 jogadores -- por
        isso verifica os dois field_stage antes de decidir o cost_lte.
        """
        lock_both_cost_lte = None
        for owner in (p, opp):
            if owner is None or owner.field_stage is None:
                continue
            passive = get_card_effects(owner.field_stage.code).get('passive', {})
            for step in passive.get('steps', []):
                if step.get('action') != 'lock_both_character_refresh':
                    continue
                conds = passive.get('conditions', {})
                leader_is = conds.get('leader_is', '').lower()
                if leader_is and leader_is not in owner.leader.name.lower():
                    continue
                lock_both_cost_lte = step.get('cost_lte', 99)

        don_from_cards = sum(c.don_attached for c in p.field_chars) + p.leader.don_attached
        for c in p.field_chars:
            c.don_attached = 0
            # Freeze (lock_opp_character_refresh / lock_self_character_refresh
            # target='this_card'): pula SO o untap nesta refresh, consumido
            # uma vez -- card permanece rested mesmo sem ter sido restado de
            # novo por outro motivo. Resto do reset (buffs, travas de turno)
            # acontece normalmente, igual a qualquer outro character.
            if c.frozen_next_refresh:
                c.frozen_next_refresh = False
            elif lock_both_cost_lte is not None and c.cost <= lock_both_cost_lte:
                pass  # Birdcage: nao ativa, mas NAO consome frozen_next_refresh (persistente)
            else:
                c.rested = False
            c.just_played = False
            c.power_buff = 0
            c.cost_buff = 0
            c.cannot_attack_until = ''
            c.cannot_be_rested_until = ''
            c.cannot_block_until = ''
            c.effects_negated_until = ''
            c.attack_paywall = {}
            c.unblockable_this_turn = False
            c.rush_this_turn = False
            c.double_attack_this_turn = False
            c.blocker_this_turn = False
            c.banish_this_turn = False
            c.extra_attribute_this_turn = ''
            c.can_attack_active_this_turn = False
            c.ko_on_opp_blocker_used_this_turn = False
            c.immunity_ko_until = ''  # imunidade temporaria (grant_ko_immunity_type)
            c.battled_opp_character_this_turn = False
            c.cannot_attack_opp_chars_cost_lte = -1
            c.own_effect_negated_this_turn = False
        p.leader.don_attached = 0
        # Freeze do PROPRIO Leader (achado 19/07, OP07-059 -- lock_opp_
        # leader_and_character_refresh trava o Leader do oponente junto
        # com ate N Characters): mesma logica de frozen_next_refresh de
        # field_chars acima, nunca checada aqui antes (o Leader sempre
        # desrestava incondicionalmente).
        if p.leader.frozen_next_refresh:
            p.leader.frozen_next_refresh = False
        else:
            p.leader.rested = False
        p.leader.power_buff = 0
        p.leader.cost_buff = 0
        p.leader.cannot_attack_until = ''
        p.leader.effects_negated_until = ''
        p.leader.unblockable_this_turn = False
        p.leader.ko_on_opp_blocker_used_this_turn = False
        p.leader.battled_opp_character_this_turn = False
        p.leader.cannot_attack_opp_chars_cost_lte = -1
        if p.field_stage:
            if p.field_stage.frozen_next_refresh:
                p.field_stage.frozen_next_refresh = False
            else:
                p.field_stage.rested = False
        # Freeze de DON (lock_opp_don_refresh): N do don_rested fica congelado
        # (nao volta a ficar available nesta refresh), consumido uma vez.
        frozen = min(p.frozen_don_count, p.don_rested)
        p.don_available += (p.don_rested - frozen) + don_from_cards
        p.don_rested = frozen
        p.frozen_don_count = 0
        # Reset da auto-restrição "cannot play this turn" (vale só pelo turno em
        # que foi imposta; ao começar o próximo turno do jogador, ela cai).
        p.cant_play_from_hand_this_turn = False
        p.cant_play_chars_this_turn = False
        p.cant_play_cost_gte = 0
        p.cannot_attack_leader_this_turn = False
        p.cant_take_life_this_turn = False
        p.events_activated_costs_this_turn = []

    def draw_phase(self, p: GameState, verbose: bool = False):
        """PlayerDrawPhase — 1º jogador não compra no T1."""
        if p.turn == 1 and p.is_first:
            return
        if p.deck:
            drawn = p.deck.pop()
            p.hand.append(drawn)
            if verbose:
                print(f'  \033[90mComprou: {drawn.name[:30]}\033[0m')

    def don_phase(self, p: GameState, verbose: bool = False):
        """
        PlayerDonPhase:
        - T1 do 1º jogador: +1 DON
        - Outros turnos: +2 DON
        - Máximo 10 (limitado pelo don_deck)
        """
        gain = min(1 if (p.turn == 1 and p.is_first) else 2, p.don_deck)
        p.don_deck -= gain
        p.don_available += gain
        if verbose:
            print(f'  \033[93mDON!! +{gain} rampados │ '
                  f'{p.don_available} ativos │ '
                  f'{p.don_rested} restados\033[0m')

    def end_phase(self, p: GameState, opp: GameState, verbose: bool = False):
        """Resolve [End of Your Turn] e actions agendadas para o fim do turno."""
        ee = EffectExecutor(p, opp)
        sources = [p.leader] + list(p.field_chars)
        if p.field_stage:
            sources.append(p.field_stage)
        for source in sources:
            logs = ee.execute(source, 'end_of_turn')
            if verbose:
                for log in logs:
                    if log:
                        print(f'  \033[90m[end] {log}\033[0m')

        queue = list(p.end_of_turn_queue)
        p.end_of_turn_queue.clear()
        for item in queue:
            step = item.get('step', {})
            source = item.get('card') or p.leader
            log = ee._execute_step(step, source)
            if verbose and log:
                print(f'  \033[90m[end queued] {log}\033[0m')

    def _activate_main_effects(self, p, opp, ee, verbose=False):
        """
        Ativa efeitos [Activate: Main] disponíveis (líder, Stage, personagens).
        A IA decide ativar quando o benefício é claro e o custo é pagável.
        Respeita 'once_per_turn'.
        """
        # Fontes de efeito ativável: líder, stage, e personagens em campo
        sources = []
        if p.leader:
            sources.append(p.leader)
        if p.field_stage:
            sources.append(p.field_stage)
        sources.extend(p.field_chars)

        for src in sources:
            effects = get_card_effects(src.code)
            am = effects.get('activate_main')
            if not am:
                continue
            # once per turn: marca em atributo dinâmico
            if am.get('once_per_turn'):
                used = getattr(src, '_am_used_turn', -1)
                if used == p.turn:
                    continue
            # Decide se vale ativar (benefício claro): draw/search/play sempre vale;
            # efeitos que precisam de alvo, só se houver alvo.
            pode, motivo = self._should_activate_main(src, am, p, opp)
            if not pode:
                self._log_decision(p, src, 'activate_main', 'skip', motivo)
                continue
            # Marca uso e executa
            src._am_used_turn = p.turn
            self._log_decision(p, src, 'activate_main', 'activate', motivo)
            if verbose:
                print(f'    ⚙ ativou [Activate:Main] de {src.name[:22]}')
            logs = ee.execute(src, 'activate_main')
            if verbose:
                for log in logs:
                    if log:
                        print(f'      ↳ {log}')
            # Só loga no replay se o efeito produziu algo observável
            if any(logs):
                desc = ' | '.join(l for l in logs if l)
                self._log_event(p, 'activate_main', card=src, description=desc)

    def _should_activate_main(self, src, am, p, opp) -> tuple[bool, str]:
        """
        Decide se vale ativar um efeito [Activate: Main].
        Retorna (pode_ativar: bool, motivo: str).
        O motivo é usado pelo decision audit para categorizar por que um
        efeito não foi ativado — sem precisar caçar caso a caso.
        """
        # ── 0. Verifica condições do bloco (ex: board_has_cost) ─────────────
        conds = am.get('conditions', {})
        if conds:
            # Reutiliza _check_conditions do EffectExecutor para consistência
            dummy_ee = EffectExecutor(p, opp)
            if not dummy_ee._check_conditions(conds, src):
                return False, 'condições do efeito não satisfeitas (board/estado)'

        # Achado real 03/08: `am.get('steps', [])` vinha vazio pra
        # QUALQUER efeito "Choose one" (guardado em `am['choice']`, não em
        # `steps`) -- Perona OP06-021, Vegapunk OP07-097, King OP08-057.
        # `resolve_choice_for_scoring` resolve pro mesmo formato que a
        # execução real usa.
        steps = resolve_choice_for_scoring(am, src, p, opp)
        actions = [s.get('action') for s in steps]
        costs = am.get('costs', [])

        # ── 0b. play_card sem carta elegível na mão: ativar é jogar o custo
        # fora (achado real 11/07, log 01.36.16: Empty Throne ativado com a
        # mão só de custo-7+ e eventos, 3 DON + stage restados pra "Choose 0
        # Friendly Targets"). Usa o MESMO _step_is_viable do executor — fonte
        # única da regra de elegibilidade.
        if 'play_card' in actions:
            dummy_ee = EffectExecutor(p, opp)
            passos_play = [s for s in steps if s.get('action') == 'play_card']
            if not any(dummy_ee._step_is_viable(s, src) for s in passos_play):
                return False, 'play_card: nenhuma carta elegível na mão'

        # ── 1. Verifica pagabilidade de cada custo ───────────────────────────
        for c in costs:
            ctype = c.get('type')
            cnt   = c.get('count', 1)
            ftype = (c.get('filter_type') or '').lower()

            if ctype == 'rest_self':
                if getattr(src, 'rested', False):
                    return False, f'custo rest_self: {src.name} já está restado'

            elif ctype == 'rest_don':
                if p.don_available < cnt:
                    return False, f'custo rest_don {cnt}: só {p.don_available} DON disponível'

            elif ctype in ('trash_from_hand', 'trash_hand'):
                color = (c.get('color') or '').lower()
                if ftype or color or c.get('has_trigger'):
                    elegíveis = [
                        c2 for c2 in p.hand
                        if (not ftype or ftype in c2.sub_types.lower())
                        and (not color or color in c2.color.lower())
                        and (not c.get('has_trigger') or c2.has_trigger)
                    ]
                    if len(elegíveis) < cnt:
                        return False, (f'custo trash_hand ({ftype}): '
                                       f'só {len(elegíveis)} elegíveis na mão')
                elif len(p.hand) < cnt:
                    return False, f'custo trash_hand: mão com só {len(p.hand)} cartas'

            elif ctype == 'trash_typed_hand_or_named_hand_field':
                named = (c.get('alternate_name') or '').lower()
                typed = [c2 for c2 in p.hand if ftype in c2.sub_types.lower()]
                named_hand = [c2 for c2 in p.hand if named in c2.name.lower()]
                named_field = [c2 for c2 in p.field_chars if named in c2.name.lower()]
                if p.field_stage and named in p.field_stage.name.lower():
                    named_field.append(p.field_stage)
                available = {id(c2) for c2 in typed + named_hand + named_field}
                if len(available) < cnt:
                    return False, 'custo tipo/nome: nenhuma opcao valida na mao ou campo'

            elif ctype == 'life_to_hand':
                if p.cant_take_life_this_turn:
                    return False, 'custo life_to_hand bloqueado neste turno'
                if len(p.life) < cnt:
                    return False, f'custo life_to_hand: Life com so {len(p.life)} cartas'

            elif ctype == 'trash_char_or_hand':
                # "trash 1 [Tipo] Character (campo) OU 1 carta da mão"
                # O filtro de tipo aplica SOMENTE ao personagem de campo.
                # Qualquer carta da mão qualifica sem restrição de tipo.
                chars_ok = [c2 for c2 in p.field_chars
                            if not ftype or ftype in c2.sub_types.lower()]
                hand_ok  = p.hand   # qualquer carta da mão
                if len(chars_ok) + len(hand_ok) < cnt:
                    return False, (f'custo trash_char_or_hand ({ftype or "qualquer"}): '
                                   f'{len(chars_ok)} chars + {len(hand_ok)} na mão, precisa {cnt}')
                # Se a mão está vazia e só há chars ATIVOS elegíveis (que podem
                # atacar este turno) E que REALMENTE valem a pena atacar (poder
                # > 0 -- um corpo de 0 poder nunca conecta dano nem justifica
                # nada, "pode atacar" e so legalidade, nao valor), adia: melhor
                # atacar antes de trashar. SEM o filtro de poder, um corpo
                # dead-weight (ex: Shalria pos on-play, 0 poder) fica pra
                # SEMPRE "tecnicamente ativo" -- o bot corretamente nunca
                # ataca com ele (0 poder nao vale) -> ele nunca fica restado
                # -> este guard nunca libera -> DEADLOCK: o ciclo do lider
                # trava pro resto da partida (achado ao vivo 14/07, log
                # 13.08.24: Shalria nunca foi trashada em 10 turnos).
                if len(hand_ok) < cnt:
                    ativos = [c2 for c2 in chars_ok
                              if c2.power > 0 and character_can_attack_now(c2, p, opp)]
                    if len(ativos) >= cnt:
                        return False, 'adia trash_char: atacar com chars ativos antes de trashar'
                # Imu leader: mesmo com carta na mao para pagar o custo, o
                # alvo real do simulador pode acabar sendo um Elder ativo no
                # campo. Nao cicla antes de extrair ataques ja disponiveis
                # (mesmo filtro de poder>0 acima -- mesmo deadlock).
                if src is p.leader and any(a in ('draw', 'look_top_deck', 'add_to_hand')
                                           for a in actions):
                    ativos = [c2 for c2 in chars_ok
                              if c2.power > 0 and character_can_attack_now(c2, p, opp)]
                    if ativos:
                        return False, 'adia ciclo do lider: atacar com chars ativos antes de trashar'

            elif ctype == 'trash_char':
                chars_ok = [c2 for c2 in p.field_chars
                            if not ftype or ftype in c2.sub_types.lower()]
                if len(chars_ok) < cnt:
                    return False, (f'custo trash_char ({ftype or "qualquer"}): '
                                   f'só {len(chars_ok)} no campo')

            elif ctype == 'don_minus':
                don_total = (p.don_available + p.don_rested
                             + sum(x.don_attached for x in p.field_chars)
                             + p.leader.don_attached)
                if don_total < cnt:
                    return False, f'custo don_minus {cnt}: só {don_total} DON total'

        # ── 2. Avalia se o benefício compensa ────────────────────────────────
        tem_custo_trash = any(c.get('type') in
                              ('trash_from_hand', 'trash_hand',
                               'trash_char_or_hand', 'trash_char',
                               'trash_typed_hand_or_named_hand_field')
                              for c in costs)

        # Draw / search — vantagem pura, sempre vale se custo foi pago
        if any(a in ('draw', 'look_top_deck', 'add_to_hand') for a in actions):
            if tem_custo_trash:
                cnt_trash = next((c.get('count', 1) for c in costs
                                  if c.get('type') in ('trash_from_hand', 'trash_hand',
                                                        'trash_char_or_hand',
                                                        'trash_typed_hand_or_named_hand_field')), 1)
                if len(p.hand) <= cnt_trash:
                    return False, (f'custo-benefício draw: mão ({len(p.hand)}) '
                                   f'não sobra após trashar {cnt_trash}')
            return True, 'benefício draw/search compensa'

        # Efeitos sobre oponente — só com alvo
        control_actions = (
            'rest_opp', 'rest_opp_character', 'ko', 'ko_opp',
            'ko_if_cost_eq_don', 'debuff', 'debuff_power', 'debuff_cost',
            'bounce', 'place_opp_character_bottom_deck',
            'lock_opp_character_refresh', 'lock_opp_character_attack',
        )
        if any(a in control_actions for a in actions):
            if not opp.field_chars:
                return False, 'efeito sobre oponente: nenhum personagem alvo disponível'
            return True, 'alvo disponível no campo oponente'

        # select_grant_rush/select_grant_rush_character — so vale ativar se
        # existir um alvo PROPRIO que realmente se beneficia (entrou em
        # campo ESTE turno, just_played, ainda sem a permissao). Achado
        # real 02/08 (usuario, log Portgas.D.Ace-R x Crocodile-B
        # 2026-08-02): sem este caso, a acao caia no fallback generico
        # "ativa por omissao" e o lider Ace (OP16-001) era oferecido/
        # pontuado com score fixo TODO turno, mesmo sem nenhum Character
        # recem-deployado -- o fix anterior (bloco 412) so corrigiu a
        # EXECUCAO (_execute_step/_step_is_viable) pra nao fazer nada
        # nesse caso, mas a DECISAO de ativar (aqui, o gate real que
        # decide se a acao aparece como candidata) continuava cega ao
        # alvo. Reusa _step_is_viable (mesmo criterio just_played/not
        # rested/not is_rush*()) em vez de duplicar a logica.
        if any(a in ('select_grant_rush', 'select_grant_rush_character') for a in actions):
            dummy_ee = EffectExecutor(p, opp)
            passos_rush = [s for s in steps
                          if s.get('action') in ('select_grant_rush', 'select_grant_rush_character')]
            if not any(dummy_ee._step_is_viable(s, src) for s in passos_rush):
                return False, 'select_grant_rush: nenhum Character recem-deployado sem a permissao'
            return True, 'select_grant_rush: alvo recem-deployado disponivel'

        # DON ramp — sempre vale
        if any(a in ('add_don', 'set_don_active') for a in actions):
            return True, 'benefício DON ramp'

        # play_card de graça — vale se há carta elegível na mão.
        # ATENÇÃO (12/07): esta era a TERCEIRA cópia da regra de
        # elegibilidade (0b/_step_is_viable, executor, aqui), e foi assim
        # que o bug do "Empty Throne no vácuo" sobreviveu a 3 reports —
        # cada cópia com um detalhe faltando. Mesmo default de tipo aqui:
        # play_card sem card_type explícito = CHARACTER (o evento "The
        # Five Elders Are at Your Service!!!" tem 'five elders' nos
        # sub_types e passava neste laço).
        if 'play_card' in actions:
            for s in steps:
                if s.get('action') != 'play_card':
                    continue
                # Achado 06/08: so tratava 'don_count_self', faltava
                # 'don_count_opp' (OP08-062/P-090) -- reusa dummy_ee (ja
                # criado acima, mesmo `p`/`opp`) em vez de duplicar a
                # resolucao de novo.
                cost_lte = dummy_ee._resolve_cost_lte(s, default=None)
                ftype = (s.get('filter_type') or '').lower()
                fcolor = (s.get('color') or '').lower()
                req_type = (s.get('card_type') or 'CHARACTER').upper()
                for c in p.hand:
                    if c.card_type != req_type:                       continue
                    if cost_lte is not None and c.cost > cost_lte:   continue
                    if ftype and ftype not in c.sub_types.lower():    continue
                    if fcolor and fcolor not in c.color.lower():      continue
                    return True, f'play_card elegível: {c.name}'
            return False, 'play_card: sem carta elegível na mão com o filtro'

        # buff_power / debuff_power sem alvo explícito — aplica sempre
        if any(a in ('buff_power', 'set_base_power') for a in actions):
            if any(c.get('type') == 'ko_own_character' for c in costs):
                attackers = [c for c in p.field_chars
                             if character_can_attack_now(c, p, opp)]
                if not attackers and getattr(p.leader, 'rested', False):
                    return False, 'buff_power com K.O. proprio sem ataques para aproveitar'
            return True, 'buff_power incondicionado'

        # play_from_trash — vale se há carta no trash elegível
        if 'play_from_trash' in actions:
            for s in steps:
                if s.get('action') != 'play_from_trash':
                    continue
                ftype  = (s.get('filter_type') or '').lower()
                fcolor = (s.get('color') or '').lower()
                for c in p.trash:
                    if ftype  and ftype  not in c.sub_types.lower(): continue
                    if fcolor and fcolor not in c.color.lower():      continue
                    return True, f'play_from_trash elegível: {c.name}'
            return False, 'play_from_trash: sem carta elegível no trash'

        # Efeitos de descarte do oponente — vale se oponente tem mão
        if any(a in ('opp_trash_from_hand', 'opp_shuffle_hand_into_deck',
                     'opp_place_hand_bottom_deck') for a in actions):
            if not opp.hand:
                return False, 'discard oponente: oponente sem cartas na mão'
            return True, f'discard oponente ({len(opp.hand)} cartas na mão)'

        # Qualquer outra ação com custo já validado — ativa por omissão.
        # Melhor ativar e deixar o executor decidir do que silenciosamente ignorar.
        return True, f'ação ativada por omissão (heurística não cobre): {actions}'

    def _negate_effect_target_value(self, target) -> float:
        """Valor futuro de negar efeito; on_play ja resolvido nao conta."""
        if target is None or getattr(target, 'effects_negated_until', ''):
            return 0.0
        effects = get_card_effects(target.code)
        if not effects:
            return 0.0

        value = 0.0
        future_blocks = (
            'activate_main', 'when_attacking', 'on_ko', 'on_opponent_attack',
            'your_turn', 'opp_turn', 'end_of_turn', 'start_of_turn',
            'passive', 'continuous', 'trigger',
        )
        for key in future_blocks:
            if effects.get(key):
                value += 55 if key in ('activate_main', 'when_attacking') else 30

        if getattr(target, 'has_blocker', False) or getattr(target, 'blocker_this_turn', False):
            value += 25
        return value

    def _best_negate_effect_target_value(self, opp, target_scope='opp_leader_or_character') -> float:
        targets = []
        scope = (target_scope or 'opp_leader_or_character').lower()
        if 'leader' in scope and getattr(opp, 'leader', None) is not None:
            targets.append(opp.leader)
        if 'character' in scope or scope in ('opp', 'opponent'):
            targets.extend(getattr(opp, 'field_chars', []))
        return max((self._negate_effect_target_value(t) for t in targets), default=0.0)

    # Actions da categoria "remocao/controle" cujo alvo e SEMPRE o oponente
    # (confirmado nos steps reais do banco: nunca aparecem com target=self/
    # own_character). 'target' ausente no step tambem conta como oponente
    # implicito (convencao ja usada pela execucao real, ex: OP06-020 rest_
    # opp_character sem chave 'target').
    _REMOCAO_ACOES_ALVO_OPONENTE_IMPLICITO = (
        'rest_opp', 'rest_opp_character', 'ko_opp', 'ko_if_cost_eq_don',
        'debuff_power', 'debuff_cost', 'place_opp_character_bottom_deck',
        'lock_opp_character_attack',
    )
    # 'ko' e 'bounce' TEM variantes que alvejam o PROPRIO campo (ex: OP01-002
    # bounce target=own_character -- devolve a propria carta pra mao, combo
    # de re-trigger, NAO remocao; OP04-079 ko target=self_character --
    # sacrificio). Só entram na conta de valor quando o target do step diz
    # explicitamente que e o oponente -- caso contrario ficam de fora
    # (mantem o base=100 flat antigo pra esses casos, sem risco de regressao).
    _REMOCAO_ACOES_ALVO_OPONENTE_EXPLICITO = ('ko', 'bounce')

    def _best_removal_target_value(self, opp, steps, engine) -> float:
        """
        Valor do MELHOR alvo elegivel do oponente entre os steps de
        remocao/controle deste bloco (mesmos filtros de alvo usados na
        execucao real -- cost_lte/cost_gte/cost_eq/power_lte/power_gte/
        don_attached_gte/rested_only/filter_type -- delegados a
        eligible_cards, fonte unica, igual sim_bridge._choose_opp_target_
        filtered ja faz pro lado da execucao).

        Simplificacao consciente (achado 01/08, categoria "remocao/
        controle" tem 90+ cartas no banco, nao só os 15 lideres do
        levantamento inicial): usa o MELHOR alvo unico mesmo quando o step
        pede count>1 (ex: OP06-117 ko count=99 cost_lte=2, ST05-011 rest_
        opp_character count=2) -- subestima levemente o valor de efeitos
        em area, mas evita inflar o score por somatorio sem calibracao
        própria ainda. Tambem nao distingue remocao PERMANENTE (ko/bounce/
        place_bottom_deck) de temporaria (debuff_power/debuff_cost/rest) --
        os 2 ja compartilhavam o mesmo base=100 flat antes deste fix; essa
        diferenciacao fica pra uma proxima passada se algum caso real pedir.
        """
        from optcg_engine.rules_facade import eligible_cards
        melhor = 0.0
        for step in steps:
            action = step.get('action')
            tgt = step.get('target')
            if action in self._REMOCAO_ACOES_ALVO_OPONENTE_IMPLICITO:
                if tgt not in (None, 'opp_character', 'all_opp_characters', 'opp', 'opponent'):
                    continue
            elif action in self._REMOCAO_ACOES_ALVO_OPONENTE_EXPLICITO:
                if tgt not in ('opp_character', 'all_opp_characters'):
                    continue
            else:
                continue
            filtrados = eligible_cards(
                opp.field_chars,
                cost_lte=step.get('cost_lte'), cost_gte=step.get('cost_gte'),
                cost_eq=step.get('cost_eq'),
                power_lte=step.get('power_lte'), power_gte=step.get('power_gte'),
                don_attached_gte=step.get('don_attached_gte'),
                rested_only=step.get('rested_only', False),
                filter_text=step.get('filter_type') or step.get('filter_types') or '',
            )
            for c in filtrados:
                valor = engine.analyzer.char_value_score(c)
                melhor = max(melhor, valor)
        return melhor

    def _has_opponent_targeted_removal_step(self, steps) -> bool:
        """Existe pelo menos 1 step de remocao/controle cujo alvo declarado
        e o oponente (independente de haver alvo ELEGIVEL agora)? Usado
        pra decidir se o bloco entra na escala por valor ou fica no
        base=100 antigo (bloco que só tem bounce/ko self-target, ex:
        OP01-002 -- combo de auto-devolver, nao remocao de verdade)."""
        for step in steps:
            action = step.get('action')
            tgt = step.get('target')
            if action in self._REMOCAO_ACOES_ALVO_OPONENTE_IMPLICITO:
                if tgt in (None, 'opp_character', 'all_opp_characters', 'opp', 'opponent'):
                    return True
            elif action in self._REMOCAO_ACOES_ALVO_OPONENTE_EXPLICITO:
                if tgt in ('opp_character', 'all_opp_characters'):
                    return True
        return False

    def _stage_play_saves_don_for_card(self, p, card, opp=None) -> int:
        stage = getattr(p, 'field_stage', None)
        if stage is None or getattr(stage, 'rested', False):
            return 0
        effects = get_card_effects(stage.code)
        am = effects.get('activate_main', {})
        # Achado real 03/08: resolve "Choose one" quando `steps` vazio
        # (nenhuma stage do banco tem esse padrao hoje, mas a mesma
        # gramatica pode aparecer -- fix generico, nao so pras 23 cartas
        # ja encontradas).
        steps = resolve_choice_for_scoring(am, stage, p, opp if opp is not None else p)
        if not any(s.get('action') == 'play_card' for s in steps):
            return 0
        costs = am.get('costs', [])
        stage_don_cost = sum(c.get('count', 0) for c in costs if c.get('type') == 'rest_don')
        if p.don_available < stage_don_cost:
            return 0

        for step in steps:
            if step.get('action') != 'play_card':
                continue
            cost_lte = step.get('cost_lte')
            if cost_lte == 'don_count_self':
                cost_lte = p.don_available + p.don_rested
            # Achado 06/08: faltava 'don_count_opp' (nenhuma STAGE do banco
            # usa hoje -- so OP08-062/P-090, Characters -- mas fica
            # resolvido pra nao virar armadilha se aparecer uma no futuro,
            # mesmo padrao das outras 5 copias corrigidas nesta sessao).
            elif cost_lte == 'don_count_opp' and opp is not None:
                cost_lte = opp.don_available + opp.don_rested
            ftype = (step.get('filter_type') or '').lower()
            fcolor = (step.get('color') or '').lower()
            fcard_type = (step.get('card_type') or 'CHARACTER').upper()
            if fcard_type and card.card_type.upper() != fcard_type:
                continue
            if cost_lte is not None and card.cost > cost_lte:
                continue
            if ftype and ftype not in card.sub_types.lower():
                continue
            if fcolor and fcolor not in card.color.lower():
                continue
            opponent = self.state_b if p is self.state_a else self.state_a
            return max(0, effective_hand_play_cost(p, card, opponent) - stage_don_cost)
        return 0

    def _effect_costs_affordable_now(self, costs, p, source=None) -> bool:
        """Preflight conservador para nao oferecer efeito que o cliente nao paga."""
        for cost in costs or []:
            ctype = cost.get('type')
            count = int(cost.get('count', 1) or 1)
            if ctype == 'rest_don' and p.don_available < count:
                return False
            if ctype in ('don_minus', 'return_own_don') and p.don_on_field() < count:
                return False
            if ctype == 'rest_self' and source is not None and source.rested:
                return False
            if ctype in ('trash_from_hand', 'trash_hand') and len(p.hand) < count:
                return False
        return True

    def _score_play_action(self, card, engine) -> float:
        """
        Pontua JOGAR uma carta. Cartas cujo efeito HABILITA o ataque
        (On Play remoção, rush, buff, activate que ajuda) pontuam alto e saem
        ANTES dos ataques. Cartas só-desenvolvimento (blocker defensivo, vanilla)
        pontuam como dev e saem DEPOIS dos ataques (regra de ordem do usuário).
        """
        stage_saves = self._stage_play_saves_don_for_card(engine.me, card, opp=engine.opp)
        if stage_saves >= 3:
            return -999.0

        base = engine.avaliar_carta(card)
        flags = get_card_flags(card.code)
        effects = get_card_effects(card.code)

        # Valor MARGINAL, nao valor da categoria: a segunda/terceira copia de
        # um corpo barato compete pelo espaco de campo e repete o mesmo papel.
        base -= engine.cheap_board_redundancy_penalty(card)

        # Ramp vale pelo turno da curva que antecipa. Cobre qualquer carta com
        # add_don/set_don_active, sem hardcode de Cracker.
        ramp_amount = sum(int(s.get('count', 1) or 1)
                          for block in effects.values() if isinstance(block, dict)
                          for s in block.get('steps', [])
                          if s.get('action') in ('add_don', 'set_don_active'))
        if ramp_amount:
            base += engine.ramp_curve_value(ramp_amount)

        # Valor de QUALQUER play_card aninhado no proprio efeito desta carta
        # (ex: ST22-015 "I Am Whitebeard!!" jogando Edward Newgate de graca,
        # alem de buff+life-to-hand) -- achado real 27/07 (partida Katakuri
        # x Ace, investigacao pedida pelo usuario comparando o Turn Planner
        # com o humano vencedor): ate aqui `base` (avaliar_carta) so credita
        # bonus de FLAG generico e fixo (is_searcher etc) pro proprio efeito
        # de "jogar outra carta" -- nunca o valor REAL de QUEM esta sendo
        # trazido. Resultado: jogar ST22-015 pontuava 140, MENOS DA METADE
        # de jogar Edward Newgate direto (280), mesmo ST22-015 trazendo o
        # MESMO Newgate DE GRACA (sem custo de mao) mais 2 bonus extra (buff
        # de lider, life-to-hand) -- o humano achou essa linha, o Turn
        # Planner nunca considerou. Fix generico (nao hardcoded pra
        # ST22-015): qualquer step play_card na propria carta credita o
        # valor da MELHOR carta elegivel na mao que bate o filtro, reusando
        # eligible_cards (rules_facade) -- mesmo filtro que a EXECUCAO real
        # do GRUPO 2 de play_card ja usa (_execute_step), sem duplicar logica
        # de match.
        from optcg_engine.rules_facade import eligible_cards
        melhor_play_card_valor = 0.0
        if engine._effect_conditions_met(card):
            for block in effects.values():
                if not isinstance(block, dict):
                    continue
                for step in block.get('steps', []):
                    if step.get('action') != 'play_card':
                        continue
                    cost_lte = step.get('cost_lte')
                    if cost_lte == 'don_count_self':
                        cost_lte = engine.me.don_available + engine.me.don_rested
                    # Achado 06/08: faltava 'don_count_opp' (OP08-062/
                    # P-090), mesmo padrao das outras copias corrigidas.
                    elif cost_lte == 'don_count_opp':
                        cost_lte = engine.opp.don_available + engine.opp.don_rested
                    elegiveis = eligible_cards(
                        [c for c in engine.me.hand if c is not card],
                        cost_lte=cost_lte,
                        cost_eq=step.get('cost_eq'),
                        power_lte=step.get('power_lte'),
                        power_gte=step.get('power_gte'),
                        power_eq=step.get('power_eq'),
                        has_trigger=step.get('has_trigger', False),
                        filter_text=step.get('filter_type', ''),
                        name_or_code=step.get('filter_names') or step.get('filter_name', ''),
                        color=step.get('color', ''),
                        exclude_name=step.get('exclude', ''),
                    )
                    card_type_wanted = (step.get('card_type') or 'CHARACTER').upper()
                    for candidate in elegiveis:
                        if candidate.card_type.upper() != card_type_wanted:
                            continue
                        melhor_play_card_valor = max(melhor_play_card_valor,
                                                      engine.avaliar_carta(candidate))
        if melhor_play_card_valor:
            base += min(melhor_play_card_valor * 0.75, 400)

        # Passiva [Your Turn] que buffa o LIDER (buff_power/gain_double_attack,
        # target='leader') so vale a pena no ataque de HOJE se a carta for
        # jogada ANTES do lider atacar -- depois que ele ja atacou (rested),
        # o buff so serve pros PROXIMOS turnos. Achado real 02/08 (usuario,
        # mirror match Ace x Ace, comparando decisao-a-decisao): o humano
        # jogou Edward Newgate (OP16-003) ANTES de atacar, o ataque do lider
        # saiu com +2000 de poder e Double Attack de verdade (2 de dano); o
        # bot atacou 2x (outro character + o proprio lider) ANTES de jogar
        # o MESMO Newgate no mesmo turno, perdendo o bonus nos dois ataques
        # -- a pontuacao de 'play' (230) nunca refletia esse ganho, entao
        # 'attack' (376, ja maior por si so) sempre saia primeiro. Mesmo
        # padrao ja usado acima pro win-con do GamePlan (+600): joga a carta
        # que HABILITA o ataque ANTES do ataque competir pela vez.
        yt_steps = effects.get('your_turn', {}).get('steps', []) if isinstance(effects.get('your_turn'), dict) else []
        yt_leader_buff = sum(s.get('amount', 0) for s in yt_steps
                             if s.get('action') == 'buff_power' and s.get('target') == 'leader')
        yt_leader_da = any(s.get('action') == 'gain_double_attack' and s.get('target') == 'leader'
                           for s in yt_steps)
        if (yt_leader_buff or yt_leader_da) and character_can_attack_now(engine.me.leader, engine.me, engine.opp):
            base += min(yt_leader_buff * 0.1, 150)
            if yt_leader_da:
                base += 200  # Double Attack dobra o dano -- vale mais que so o poder

        # Contra-parte do bônus de counter em avaliar_carta: aquele bônus
        # existe pra contexto "vale manter essa carta na mão" (ex: _trash_value).
        # Jogar a carta FAZ O OPOSTO — ela sai da mão e perde o valor de counter
        # (e, se veio de um Life card recém-revelado, o próprio
        # resolve_trigger_choice já decidiu deliberadamente NÃO usar o trigger
        # porque a carta vale mais como counter garantido na mão). Sem este
        # desconto, cartas com counter alto e pouco poder (achado real 10/07:
        # Doc Q counter=2000/poder=0, Baby 5 counter=2000) herdavam o bônus de
        # avaliar_carta e pontuavam artificialmente alto pra JOGAR, esvaziando
        # a mão de counters — 2x Doc Q + 1x Baby 5 jogados em 2 turnos, bot
        # terminou o resto da partida sem nenhum counter na mão.
        #
        # Achado 28/07 (bloco HANDOFF 390): esta formula estava DUPLICADA à
        # mão aqui, byte a byte igual a `_counter_stat_bonus` (avaliar_carta)
        # -- corrigido pra chamar o método único, sem mudar o valor (mesmo
        # resultado, só elimina o risco de as duas derivarem sem querer).
        #
        # Achado 28/07 parte 2 (bloco HANDOFF 391, comparação sistemática em
        # 20 partidas reais distintas via compare_vs_human.py -- não 1 log
        # só, pedido explícito do usuário): `base` já é
        # `engine.avaliar_carta(card)`, que POR SUA VEZ já soma
        # `_counter_stat_bonus(card)` (linha ~9762). Subtrair o MESMO valor
        # de novo aqui não é um desconto -- é um cancelamento perfeito,
        # independente da magnitude da constante (confirmado testando
        # COUNTER_STAT_VALUE_PER_1000 em 15/30/45/60/90/120 contra 29 estados
        # reais: 0/29 mudaram de sugestão, scores idênticos byte a byte em
        # qualquer valor testado). Pra o desconto realmente existir, precisa
        # subtrair o bônus DUAS vezes: uma pra anular o crédito que
        # avaliar_carta somou, outra como a penalidade de fato por abrir mão
        # da carta como counter garantido.
        base -= 2 * engine._counter_stat_bonus(card)

        # GamePlan fase 2 (HANDOFF #119/#120): DON!! não é perdido entre
        # turnos (refresh no início do turno devolve TUDO que foi anexado,
        # + o ramp de +2) — o que trava a carta-bomba (ex: Five Elders,
        # custo 10) não é "não guardei DON ao longo de várias partidas", é
        # gastar o DON deste MESMO turno em margem de ataque ANTES dela
        # competir pela vez, no turno exato em que ela já ficou pagável.
        # Achado real 10/07 (log 23.38.05): don=9 no turno 5 foi todo pra
        # 2 ataques (top3 480/480/470, tudo 'attack') — no turno em que o
        # DON bater o alvo, a jogada precisa vencer qualquer ataque na
        # ordem, não só competir normalmente. Mesma lógica do ZEHAHAHAHA
        # do usuário: joga a bomba PRIMEIRO quando o DON permite, ataque
        # "seco" (sem margem) depois com o que sobrar.
        plano = compute_game_plan(engine.me)
        if (plano['win_con_code'] and card.code == plano['win_con_code']
                and plano['don_target']
                and engine.me.don_available >= plano['don_target']):
            base += 600

        # Guarda de campo cheio: jogar um Character com o campo cheio (5)
        # KO a pior carta ja em campo pra abrir espaco (main_phase, sem volta
        # depois de pago o custo). Se a nova carta nao supera a pior ja em
        # campo, a troca e liquido zero ou negativo -- desqualifica a jogada
        # aqui, ANTES do DON ser gasto (mesma regra que o outro caminho de
        # play_card, GRUPO 2, ja aplica). Achado em partida real 07/07: o
        # planner reofereceu "jogar Doc Q" repetidas vezes com o campo cheio
        # de Doc Qs/Laffittes, trocando carta fraca por carta fraca a troco
        # de nada, turno apos turno.
        if card.card_type == 'CHARACTER' and len(engine.me.field_chars) >= 5:
            pior = min(engine.me.field_chars, key=lambda c: c.board_value())
            if card.board_value() <= pior.board_value():
                return -999.0

        # FASE B do Turn Planner (usuario, 24/07: "adicione tambem... o
        # entendimento e possibilidades de combos que nos mapeamos"). Ate
        # aqui, `base` (via avaliar_carta) so olha os efeitos da PROPRIA
        # carta -- nunca quem JA esta em campo e REAGE a ela ser jogada
        # (on_own_char_played/on_opp_char_played, fase 1.3 do mapeamento
        # de combos, 24/07). Sem isto, jogar Sanji OP02-026 ANTES de uma
        # vanilla nunca pontuava diferente de jogar depois -- a ordem
        # "ativa o watcher primeiro" nao aparecia em lugar nenhum do score.
        base += engine._char_played_react_bonus(card, engine.me, engine.opp)

        # Carta que PRECISA entrar para ativar efeito que ajuda o ataque agora:
        # On Play de remoção/buff/rest/draw, ou rush. Bônus para sair antes do
        # ataque. Detecção via flags estruturadas (não substring no texto cru).
        habilita_ataque = False
        # Familia de remocao/controle (kos/is_removal/bounces/rests_opponent):
        # o motivo de existir deste bonus e SEQUENCIAMENTO relativo ao ataque
        # deste turno ("sai antes do ataque, senao remove/resta o alvo tarde
        # demais pra render efeito") -- MESMA logica ja aplicada em
        # `_score_activate_main` pra "remocao/controle" (achado 08/08, Teach
        # 10/bloco 467): sem NENHUM atacante disponivel este turno (nem o
        # lider, nem nenhum Character), nao ha corrida de ordem pra vencer.
        # O VALOR base da remocao (board control, independente de ataque) ja
        # fica capturado em `avaliar_carta` -- este bonus e so a prioridade
        # extra de ORDEM, que so faz sentido quando existe um ataque pra
        # proteger/habilitar. Achado 08/08 (revisao pedida pelo usuario apos
        # o fix do Teach 10, "vale a pena revisar consistencia"): antes desta
        # gate, `_score_play_action` dava o bonus incondicionalmente aqui,
        # unico caminho de scoring que ainda nao seguia esse principio.
        # `power_buff`/`draws`/`is_searcher` ficam de fora do gate de
        # proposito: duracao do buff nao e rastreada pela flag (pode ser
        # permanente, nao so "battle_only") e draw/search tem valor de
        # informacao/recurso independente de haver ataque este turno.
        tenho_atacante_agora = (character_can_attack_now(engine.me.leader, engine.me, engine.opp)
                                or any(character_can_attack_now(c, engine.me, engine.opp)
                                       for c in engine.me.field_chars))
        if 'on_play' in effects:
            if (flags.get('kos') or flags.get('is_removal') or flags.get('bounces')) and tenho_atacante_agora:
                habilita_ataque = True
            if flags.get('power_buff') or flags.get('draws') or flags.get('is_searcher'):
                habilita_ataque = True
            # rests_opponent só habilita ataque se o oponente tem alvo para
            # restar E se eu tenho atacante pra se beneficiar do alvo restado.
            if flags.get('rests_opponent') and engine.opp.field_chars and tenho_atacante_agora:
                habilita_ataque = True
        if card.has_rush or card.rush_this_turn:
            habilita_ataque = True
        # when_attacking: o personagem precisa estar em campo para disparar o
        # efeito; jogar ele agora HABILITA ataques com bônus no mesmo turno.
        if 'when_attacking' in effects and card.card_type == 'CHARACTER':
            habilita_ataque = True
        # activate_main: valor recorrente por turno em campo — priorizar colocar
        # em campo para acumular esse valor nos turnos seguintes.
        if 'activate_main' in effects and card.card_type == 'CHARACTER':
            am = effects['activate_main']
            # Achado real 03/08: resolve "Choose one" quando `steps` vazio.
            am_steps = resolve_choice_for_scoring(am, card, engine.me, engine.opp)
            recupera_trash = next((s for s in am_steps if s.get('action') == 'play_from_trash'), None)
            if recupera_trash:
                ft = (recupera_trash.get('filter_type') or '').lower()
                max_rec = recupera_trash.get('count', 1)
                # Conta alvos no trash + no campo (que o efeito vai trashar antes de recuperar)
                def _matches_ft(c2):
                    return c2.card_type == 'CHARACTER' and (
                        not ft or ft in (c2.sub_types or '').lower())
                trash_targets = sum(1 for c2 in engine.me.trash if _matches_ft(c2))
                field_targets = sum(1 for c2 in engine.me.field_chars if _matches_ft(c2) and c2 is not card)
                n = min(trash_targets + field_targets, max_rec)
                base += 30 + n * 50   # cada char recuperável vale ~50
            else:
                base += 30

        if habilita_ataque:
            base += HABILITA_ATAQUE_BONUS   # prioriza sair antes dos ataques

        # Penalização de AUTO-TRAVA (parte b): se jogar esta carta me trava de
        # jogar mais neste turno (self_cant_play no on_play), e ainda tenho cartas
        # que eu QUERERIA jogar antes de travar, penaliza — para o planner preferir
        # jogá-las primeiro (ou só ativar o combo quando a mão já foi gasta).
        op = effects.get('on_play')
        # Achado real 03/08: resolve "Choose one" quando `steps` vazio.
        op_steps_resolved = resolve_choice_for_scoring(op, card, engine.me, engine.opp) if op else []
        if any(s.get('action') == 'self_cant_play' for s in op_steps_resolved):
            scope = next((s.get('scope', 'chars') for s in op_steps_resolved
                          if s.get('action') == 'self_cant_play'), 'chars')
            gte = next((s.get('cost_gte', 0) for s in op_steps_resolved
                        if s.get('action') == 'self_cant_play'), 0)
            me = engine.me
            don_usable = me.don_available
            perdidas = 0
            for c in me.hand:
                if c is card or c.card_type not in ('CHARACTER', 'EVENT', 'STAGE'):
                    continue
                if effective_hand_play_cost(me, c, engine.opp) > don_usable:
                    continue   # não jogaria mesmo (sem DON) — não conta como perda
                # essa carta SERIA bloqueada pela trava?
                bloqueada = (scope == 'hand'
                             or (c.card_type == 'CHARACTER'
                                 and (gte == 0 or c.cost >= gte)))
                if bloqueada:
                    perdidas += engine.avaliar_carta(c)
            base -= perdidas * 0.5   # peso TUNÁVEL (fase 3)

        # EVENT cujo [Main] não PRODUZ nada no estado atual: jogar é pagar
        # custo + carta no vácuo. Era um caso hardcoded ko+opp_stage ("Never
        # Existed" sem stage, 11/07) — achado real 12/07 (partida 14.30.52):
        # Ground Death (negate_effect em opp_character) foi jogado com o
        # campo do oponente VAZIO porque o padrão não era coberto.
        # Generalizado via _step_is_viable/_check_conditions — a MESMA régua
        # do gate de activate_main (regra do projeto: viabilidade ampla,
        # nunca ativar no vácuo), cobre qualquer evento/step, não uma carta.
        if card.card_type == 'EVENT':
            main = effects.get('main', {})
            # Achado real 03/08: resolve "Choose one" quando `steps` vazio
            # -- sem isso, 8 EVENTs no banco (ex: "I Bid 500 Million!!"
            # OP05-096) pulavam este bloco de gate/valor inteiro (nem
            # bloqueio de "sem alvo" nem ajuste de valor), porque
            # `main_steps` vinha sempre [] pra um "Choose one".
            main_steps = resolve_choice_for_scoring(main, card, engine.me, engine.opp)
            if main_steps:
                if not self._effect_costs_affordable_now(main.get('costs', []),
                                                         engine.me, card):
                    return -999.0
                ee_viab = EffectExecutor(engine.me, engine.opp)
                cond_ok = ee_viab._check_conditions(main.get('conditions', {}), card)
                if not cond_ok or not any(ee_viab._step_is_viable(s, card)
                                          for s in main_steps):
                    # Evento cujo [Main] nao produz NADA agora: jogar e pagar
                    # custo + a carta no vacuo -- e, se ela tambem for um
                    # [Counter] (ex: Never Existed OP13-098, ko opp_stage sem
                    # stage do oponente), ainda QUEIMA a defesa por zero. Nunca
                    # vale na propria main phase. BLOQUEIO DURO: o -120 anterior
                    # era mole e o bot jogava quando sobrava DON e nada melhor
                    # (achado ao vivo 14/07, log 01.23.31 -- "Never Existed do
                    # nada"). A carta fica na mao pra defender.
                    return -999.0

                # Evento que apenas se repoe por draw nao gera vantagem de
                # carta: ele precisa entregar valor material adicional. E
                # DON-minus que atrasa a curva so passa com controle real.
                non_draw = [s for s in main_steps
                            if s.get('action') not in ('draw', 'look_top_deck',
                                                       'add_to_hand', 'deck_bottom_rest')]
                def _material_control(step):
                    action = step.get('action')
                    if action in ('rest_opp', 'rest_opp_character'):
                        limit = step.get('power_lte', 10**9)
                        return any(not c.rested and c.power <= limit
                                   for c in engine.opp.field_chars)
                    if action in ('ko', 'ko_opp', 'debuff_power', 'bounce',
                                  'place_opp_character_bottom_deck'):
                        return bool(engine.opp.field_chars) and ee_viab._step_is_viable(step, card)
                    return False
                useful_control = any(_material_control(s) for s in non_draw)
                if any(s.get('action') == 'draw' for s in main_steps):
                    base -= 35.0
                don_minus = sum(int(c.get('count', 1) or 1)
                                for c in main.get('costs', [])
                                if c.get('type') == 'don_minus')
                if don_minus:
                    base -= engine.don_minus_opportunity_cost(don_minus)
                    if (engine.don_minus_delays_hand_curve(don_minus)
                            and engine.don_return_trigger_value(don_minus) <= 0
                            and not useful_control):
                        return -999.0
                rest_don = sum(int(c.get('count', 1) or 1)
                               for c in main.get('costs', [])
                               if c.get('type') == 'rest_don')
                if rest_don:
                    base -= engine.don_opportunity_cost(rest_don)

        # STAGE com stage própria já em campo: jogar SUBSTITUI a atual (regra
        # do jogo, 1 stage por lado). A 1ª versão deste fix descontava só
        # avaliar_carta da atual — o Empty Throne (motor de deploy grátis)
        # avalia baixo e a Mary Geoise substituiu DE NOVO na partida
        # seguinte (23.41.50, 2º report). Agora régua composta stage_worth
        # (avaliar + motor de activate_main) dos DOIS lados: substituição
        # com ganho líquido <= 0 é bloqueada dura (-999, nunca compete);
        # uma stage genuinamente melhor continua podendo entrar.
        if card.card_type == 'EVENT':
            main = effects.get('main', {})
            # Achado real 03/08: resolve "Choose one" quando `steps` vazio.
            main_steps = resolve_choice_for_scoring(main, card, engine.me, engine.opp)
            if main_steps and any(s.get('action') == 'negate_effect' for s in main_steps):
                negate_value = max(
                    self._best_negate_effect_target_value(engine.opp, s.get('target'))
                    for s in main_steps if s.get('action') == 'negate_effect'
                )
                if negate_value <= 0:
                    base = min(base - 140, -80)  # on_play ja resolvido/sem texto futuro: nao gaste DON
                else:
                    base += min(negate_value, 70)

        if card.card_type == 'STAGE' and engine.me.field_stage is not None:
            worth_nova  = engine.stage_worth(card)
            worth_atual = engine.stage_worth(engine.me.field_stage)
            if worth_nova <= worth_atual:
                return -999.0
            base -= worth_atual

        # CHARACTER cujo on_play não dispara AGORA (condição falha ou nenhum
        # step com material): o play perde o valor de efeito e vira só o
        # corpo. Corpo de 0 poder com on_play morto é um play quase inútil
        # que ainda alimenta remoção/KO do oponente — reclamação real 12/07:
        # Mjosgard (on_play reanimar Mary Geoise custo 1, condição vida<=3)
        # descido com vida 4 e trash sem alvo, 2 DON num vanilla de 0 poder.
        if card.card_type == 'CHARACTER':
            op_block = effects.get('on_play', {})
            # Achado real 03/08: resolve "Choose one" quando `steps` vazio
            # -- sem isso, os 8 personagens com on_play via `choice` (ex:
            # Viola EB01-052, Trafalgar Law EB02-045) nunca disparavam
            # este guard, mesmo com um corpo fraco e nenhum alvo real.
            op_steps_v = resolve_choice_for_scoring(op_block, card, engine.me, engine.opp)
            if op_steps_v:
                ee_viab = EffectExecutor(engine.me, engine.opp)
                op_vivo = (ee_viab._check_conditions(op_block.get('conditions', {}), card)
                           and any(ee_viab._step_is_viable(s, card)
                                   for s in op_steps_v))
                if not op_vivo:
                    base -= 40 if card.power > 0 else 90

        # Vanilla fraca (custo ≤ 2, poder ≤ 3000, sem efeito) no early game:
        # humanos normalmente passam em vez de gastar o único DON do T1/T3 em
        # cartas que não mudam o estado do jogo significativamente.
        if (card.card_type == 'CHARACTER'
                and card.cost <= 2
                and card.power <= 3000
                and not effects
                and not card.has_blocker):
            personal_turn = (engine.me.turn + 1) // 2
            if personal_turn <= 2:
                base -= 60  # penaliza fortemente no early; o humano prefere passar

        return base

    def _score_activate_main(self, src, am, p, opp, priority, engine=None) -> float:
        """
        Pontua a ação de ATIVAR um efeito [Activate:Main].
        Permite que a ativação compita com plays e ataques no Turn Planner,
        em vez de sempre disparar no início do turno.
        """
        # Achado real 03/08 (mesmo de _should_activate_main): sem resolver
        # `choice`, Perona/Vegapunk/King caiam sempre no piso generico (60)
        # em vez do valor real da opção (ex: "compre 1 carta" = 170).
        steps = resolve_choice_for_scoring(am, src, p, opp)
        actions_list = [s.get('action') for s in steps]
        costs = am.get('costs', [])
        custo_don = sum(c.get('count', 0) for c in costs if c.get('type') == 'rest_don')

        # Benefício base pelo tipo de efeito
        if any(a in ('draw', 'look_top_deck', 'add_to_hand') for a in actions_list):
            # vantagem de carta — muito valioso, custa quase nada (rest) e
            # buscar PRIMEIRO e estritamente melhor (filtra o deck antes de
            # decidir os deploys). 170 para vir antes de deploys baratos:
            # em partida real (04/07) o search do Laffitte (105) perdia para
            # 3 deploys e o DON acabava antes de ativar.
            base = 170
            # Se ativar NAO trava o plano (sobra DON para continuar jogando
            # depois), buscar primeiro nao tem downside nenhum — bonus para
            # vencer qualquer deploy (partida 06/07: play 166 > activate 155
            # e o Laffitte ficou parado de novo, num turno de 3 DON).
            if p.don_available >= custo_don + 2:
                base += 60
        elif any(a in ('add_don', 'set_don_active') for a in actions_list):
            base = 90    # ramp de DON
            # set_don_active (11 cartas no banco, todas 'up_to') desresta
            # DON que JA existe -- o ganho real e limitado por quanto DON
            # restado ha pra converter, NUNCA o valor cheio de 90 quando
            # don_rested < count. Achado 30/07 (Mihawk-G OP14-020,
            # investigando gap residual de ativacao pos-fix de condicao):
            # a base FLAT de 90 nao refletia essa variacao -- com pouco
            # DON restado (comum no early/mid game), don_opportunity_cost
            # do custo rest_don(1) ja consumia quase todo o base=90,
            # deixando o score liquido perto de zero SEMPRE, mesmo nos
            # turnos em que don_rested>=count (ganho liquido real de ate
            # +2 DON utilizavel this turn, ativacao claramente boa).
            # Generico: soma o ganho real (min(count pedido, don_rested)
            # * valor-unidade de DON, mesma escala de DON_COST=25 usada
            # em todo o resto do motor pra "quanto vale 1 DON agora") em
            # cima do base fixo -- nao substitui o base=90 (que ja cobre
            # add_don, cujo ganho NAO depende de don_rested existente).
            for step in steps:
                if step.get('action') == 'set_don_active':
                    ganho_real = min(step.get('count', 1), p.don_rested)
                    base += ganho_real * 25
        elif any(a in ('play_card',) for a in actions_list):
            base = 110   # jogar carta grátis
            best_play_value = 0.0
            best_saved_don = 0
            best_candidate = None
            for step in steps:
                if step.get('action') != 'play_card':
                    continue
                cost_lte = step.get('cost_lte')
                if cost_lte == 'don_count_self':
                    cost_lte = p.don_available + p.don_rested
                # Achado 06/08: faltava 'don_count_opp' (OP08-062/P-090),
                # mesmo padrao das outras copias corrigidas.
                elif cost_lte == 'don_count_opp':
                    cost_lte = opp.don_available + opp.don_rested
                ftype = (step.get('filter_type') or '').lower()
                fcolor = (step.get('color') or '').lower()
                fcard_type = (step.get('card_type') or '').upper()
                for candidate in p.hand:
                    if cost_lte is not None and candidate.cost > cost_lte:
                        continue
                    if ftype and ftype not in candidate.sub_types.lower():
                        continue
                    if fcolor and fcolor not in candidate.color.lower():
                        continue
                    if fcard_type and candidate.card_type.upper() != fcard_type:
                        continue
                    value = engine.avaliar_carta(candidate) if engine is not None else candidate.board_value()
                    if value > best_play_value or best_candidate is None:
                        best_play_value = value
                        best_candidate = candidate
                    best_saved_don = max(best_saved_don, effective_hand_play_cost(p, candidate, opp) - custo_don)
            base += min(best_play_value * 0.55, 95)
            base += min(max(0, best_saved_don) * 18, 45)
            if src is getattr(p, 'field_stage', None) and best_saved_don >= 3:
                base += min(best_saved_don * 80, 520)
                base += min(best_play_value * 0.20, 180)

            # HABILITA_ATAQUE (achado 08/08, revisao de consistencia pedida
            # pelo usuario apos o fix do Teach 10/bloco 467): jogar de GRACA
            # via ability um Character com RUSH da um atacante NOVO este
            # turno -- vale priorizar sempre (mesma logica incondicional de
            # `card.has_rush` em `_score_play_action`, ja que quem fornece o
            # proprio atacante nao depende de ja existir um). Se o candidato
            # tem on_play de remocao/controle (kos/is_removal/bounces),
            # mesma gate `tenho_atacante_agora` ja aplicada tanto em
            # `_score_play_action` quanto na categoria "remocao/controle"
            # deste mesmo metodo -- so faz sentido sair primeiro se ha um
            # ataque de verdade pra proteger/habilitar.
            if best_candidate is not None:
                cand_flags = get_card_flags(best_candidate.code)
                if best_candidate.has_rush or best_candidate.rush_this_turn:
                    base += HABILITA_ATAQUE_BONUS
                elif cand_flags.get('kos') or cand_flags.get('is_removal') or cand_flags.get('bounces'):
                    tenho_atacante_pc = (character_can_attack_now(p.leader, p, opp)
                                         or any(character_can_attack_now(c, p, opp) for c in p.field_chars))
                    if tenho_atacante_pc:
                        base += HABILITA_ATAQUE_BONUS
        elif any(a == 'give_don' for a in actions_list):
            # DON RESTADO (delayed) -- distinto de add_don/set_don_active
            # (base=90, DON ATIVO imediato). Ver GIVE_DON_RESTED_BASE_SCORE.
            base = GIVE_DON_RESTED_BASE_SCORE
            # Sinergia com um ataque na MESMA janela (achado real 02/08,
            # usuario, log Portgas.D.Ace-R x Crocodile-B): o -10 flat nunca
            # considerava que o DON extra pode (a) fechar um deficit real
            # de poder contra o lider do oponente, ou (b) desbloquear o
            # proprio `don_requirement` de um `when_attacking` que o alvo
            # ainda nao atingia -- turno 2 (deficit contra o lider) e turno
            # 4 (Vista OP16-011, "KO ate 2 Characters power<=2000",
            # `don_requirement:1`) perderam valor real por causa disso. Usa
            # a MESMA escolha de alvo que a execucao real faz (maior
            # effective_power entre campo ativo+lider, ver
            # action=='give_don' em _execute_step) pra nao divergir "dois
            # motores". `attack_time_power` (delta antes/depois) so cobre
            # `when_attacking` que MEXE em poder (buff_power/set_base_power)
            # -- Vista e KO puro, sem ganho de poder nenhum, entao o
            # don_requirement precisa ser checado DIRETO (nao inferido pelo
            # delta), senao o caso mais valioso (desbloquear um efeito
            # inteiro, nao so poder) nunca pontua.
            if engine is not None:
                for step in steps:
                    if step.get('action') != 'give_don':
                        continue
                    count = step.get('count', 1)
                    candidatos_alvo = [c for c in p.field_chars if not c.rested] + [p.leader]
                    target_name = (step.get('target_name') or '').lower()
                    if target_name:
                        candidatos_alvo = [c for c in candidatos_alvo if target_name in c.name.lower()]
                    if not candidatos_alvo:
                        continue
                    melhor = max(candidatos_alvo, key=lambda c: c.effective_power(True))
                    if not character_can_attack_now(melhor, p, opp):
                        continue
                    antes = attack_time_power(melhor, opp)
                    # +power_buff: mesmo achado do bloco 434 -- sem isso o
                    # bonus de "fecha o deficit" pode disparar mesmo quando
                    # o lider tem buff de defesa ativo e o DON extra nao
                    # basta de verdade.
                    deficit_lider = (opp.leader.power + opp.leader.power_buff) - antes
                    if 0 < deficit_lider <= count * 1000:
                        base += 130  # fecha o deficit contra o lider do oponente
                    wa = get_card_effects(melhor.code).get('when_attacking')
                    if isinstance(wa, dict):
                        req = wa.get('don_requirement', 0)
                        don_atual = getattr(melhor, 'don_attached', 0)
                        if req and don_atual < req <= don_atual + count:
                            base += 100  # desbloqueia o when_attacking inteiro
        elif any(a in ('rest_opp', 'rest_opp_character', 'ko', 'ko_opp',
                       'ko_if_cost_eq_don', 'debuff_power', 'debuff_cost',
                       'bounce', 'place_opp_character_bottom_deck',
                       'negate_effect', 'lock_opp_character_attack') for a in actions_list):
            base = 100   # remoção/controle
            if 'negate_effect' in actions_list and engine is not None:
                negate_value = max(
                    self._best_negate_effect_target_value(opp, s.get('target'))
                    for s in steps if s.get('action') == 'negate_effect'
                )
                base = -60 if negate_value <= 0 else 100 + min(negate_value, 70)
            elif engine is not None and self._has_opponent_targeted_removal_step(steps):
                # Achado 01/08 (generalizando o mesmo bug do negate_effect
                # pro resto da categoria "remocao/controle"): as outras 9
                # acoes (rest_opp/rest_opp_character/ko/ko_opp/debuff_power/
                # debuff_cost/bounce/place_opp_character_bottom_deck/
                # lock_opp_character_attack) pontuavam base=100 FLAT
                # independente do alvo real ser uma ameaca grande (blocker
                # caro, double attack) ou um vanilla fraco -- a IA nao
                # discriminava QUAL Character do oponente valia a pena
                # remover. Mesma escala/formato ja usado pro negate_effect
                # (-60 sem alvo de valor, 100+min(valor,70) com alvo).
                alvo_valor = self._best_removal_target_value(opp, steps, engine)
                base = -60 if alvo_valor <= 0 else 100 + min(alvo_valor * 0.3, 70)
            # HABILITA_ATAQUE, agora tambem pra ACTIVATE (achado real
            # 08/08, usuario -- partida ao vivo): _score_play_action ja
            # da HABILITA_ATAQUE_BONUS (+60) pra carta que precisa
            # ENTRAR pra habilitar o ataque (kos/remocao/buff/draw),
            # priorizando sair antes do ataque no mesmo turno -- mas
            # _score_activate_main nunca tinha o equivalente. Teach 10
            # (OP09-093, negate_effect no lider/personagem do oponente +
            # trava ataque) atacou PRIMEIRO e so ativou DEPOIS, quando
            # deveria ser o inverso (anular a resposta do oponente ANTES
            # do ataque, senao o oponente ainda pode counterar/bloquear
            # normalmente). So aplica quando ha um alvo de valor real
            # (base>0, mesmo criterio ja usado acima) E ainda existe um
            # atacante disponivel este turno -- sem atacante, "sair
            # antes do ataque" nao significa nada.
            tenho_atacante = (character_can_attack_now(p.leader, p, opp)
                              or any(character_can_attack_now(c, p, opp) for c in p.field_chars))
            if base > 0 and tenho_atacante:
                base += HABILITA_ATAQUE_BONUS
                # negate_effect e categoricamente diferente do resto da
                # categoria (ko/bounce/debuff removem/enfraquecem UM alvo;
                # negar a resposta do oponente protege TODOS os meus
                # ataques deste turno, nao so um) -- bonus extra pra
                # garantir que sai antes mesmo quando ha um ataque de
                # score alto competindo. Validado com o cenario exato da
                # partida real (turno 5): sem este extra, 100+60=160
                # ainda perdia pro ataque de 288; com o extra, ativa
                # primeiro como deveria.
                if 'negate_effect' in actions_list:
                    base += 150
        elif any(a == 'play_from_trash' for a in actions_list):
            # Achado real 09/07 (Five Elders OP13-082 nunca ativava, mesmo
            # com o board quase morrendo e a lixeira cheia de alvos
            # reanimaveis): 'play_from_trash' nao estava em NENHUMA
            # categoria reconhecida acima, entao caia no fallback generico
            # de 60 -- a mesma pontuacao de um efeito qualquer sem
            # categoria, mesmo quando reanima ATE 5 personagens de uma vez
            # (Five Elders). Nao e um problema so dessa carta: e QUALQUER
            # carta cujo Activate:Main usa essa acao (Kuma tambem tem, em
            # menor escala). Fix generico: soma o valor real dos alvos
            # elegiveis na lixeira (respeitando filter_type/distinct_names/
            # count do proprio step), igual 'play_card' ja faz pra mao.
            base = 120
            reanimados_valor = 0.0
            reanimados_tem_rush = False
            reanimados_tem_removal = False
            for step in steps:
                if step.get('action') != 'play_from_trash':
                    continue
                count = step.get('count', 1)
                ftype = (step.get('filter_type') or '').lower()
                elegiveis = [c for c in p.trash
                             if c.card_type == 'CHARACTER'
                             and (not ftype or ftype in c.sub_types.lower())]
                if step.get('distinct_names'):
                    vistos, unicos = set(), []
                    for c in elegiveis:
                        if c.name not in vistos:
                            unicos.append(c)
                            vistos.add(c.name)
                    elegiveis = unicos
                elegiveis.sort(key=lambda c: -(engine.analyzer.char_value_score(c) if engine is not None else c.board_value()))
                for c in elegiveis[:count]:
                    reanimados_valor += engine.analyzer.char_value_score(c) if engine is not None else c.board_value()
                    # HABILITA_ATAQUE (achado 08/08, mesma revisao pedida
                    # pelo usuario do fix do Teach 10/play_card acima): um
                    # reanimado com RUSH da atacante NOVO este turno; um
                    # reanimado com on_play de remocao/controle so vale
                    # priorizar se ha atacante de verdade pra proteger.
                    if c.has_rush or c.rush_this_turn:
                        reanimados_tem_rush = True
                    c_flags = get_card_flags(c.code)
                    if c_flags.get('kos') or c_flags.get('is_removal') or c_flags.get('bounces'):
                        reanimados_tem_removal = True
            base += min(reanimados_valor * 0.4, 280)

            if reanimados_tem_rush:
                base += HABILITA_ATAQUE_BONUS
            elif reanimados_tem_removal:
                tenho_atacante_pt = (character_can_attack_now(p.leader, p, opp)
                                     or any(character_can_attack_now(c, p, opp) for c in p.field_chars))
                if tenho_atacante_pt:
                    base += HABILITA_ATAQUE_BONUS

            # Se o custo INCLUI trashar o proprio campo inteiro (Five
            # Elders: "trash all your Characters"), desconta o que esta
            # sendo sacrificado -- senao a IA acha que ganhou os
            # reanimados de graca quando na verdade TROCOU o campo atual
            # pelo novo. So desconta quando e "trash ALL" (count>=99,
            # convencao do parser pra "todos") -- custo de sacrificio
            # pontual (1 personagem) ja e capturado por tem_ko_own abaixo.
            if any(s.get('action') == 'trash_character' and s.get('count', 0) >= 99
                   for s in steps):
                sacrificio = sum(
                    (engine.analyzer.char_value_score(c) if engine is not None else c.board_value())
                    for c in p.field_chars if c is not src
                )
                base -= min(sacrificio * 0.5, 220)
        else:
            # Piso generico (achado 24/07, auditoria fase A do Turn Planner):
            # antes de cair no 60 fixo pra QUALQUER action nao categorizada
            # acima, reusa a MESMA tabela de _UNCOVERED_ACTION_VALUE ja
            # calibrada em avaliar_carta (fase 2) -- ex: gain_rush,
            # select_grant_*, opp_don_minus, life_to_hand num Activate:Main
            # caiam sempre no generico 60, mesmo sendo o efeito PRINCIPAL da
            # ativacao. Escala x3: os valores da tabela (10-30) foram
            # calibrados pra somar em avaliar_carta (varios termos aditivos
            # menores); aqui `base` compete sozinho contra as categorias
            # explicitas acima (90-170) -- x3 poe o piso na mesma ordem de
            # grandeza (30-90) sem ultrapassar a categoria mais forte.
            base = 60
            for a in actions_list:
                piso = DecisionEngine._UNCOVERED_ACTION_VALUE.get(a)
                if piso is not None:
                    base = max(base, piso * 3)

        # Custo real: quanto a ativação nos custa (trash de mão, DON, etc.)
        tem_trash_hand = any(c.get('type') in ('trash_from_hand', 'trash_hand', 'trash_char_or_hand',
                                               'trash_typed_hand_or_named_hand_field')
                             for c in costs)
        tem_ko_own = any(c.get('type') == 'ko_own_character' for c in costs)

        if engine is not None:
            base -= engine.don_opportunity_cost(custo_don)
        else:
            base -= custo_don * 25

        # Informacao pura tem retorno decrescente. Olhar o topo adversario
        # nao deve vencer desenvolvimento de campo, especialmente em copias
        # repetidas da mesma fonte barata.
        info_only = actions_list and all(
            a in ('peek_opp_deck_top', 'look_top_deck') for a in actions_list)
        if info_only:
            copies = sum(1 for c in p.field_chars if c.code == src.code)
            base = min(base, 35.0) - max(0, copies - 1) * 30.0

        if tem_ko_own:
            sacrifice_pool = []
            for card in p.field_chars:
                ok = True
                for cost in costs:
                    if cost.get('type') != 'ko_own_character':
                        continue
                    ftype = (cost.get('filter_type') or '').lower()
                    if ftype and ftype not in card.sub_types.lower():
                        ok = False
                        break
                if ok and card is not src:
                    sacrifice_pool.append(card)
            if sacrifice_pool:
                sacrifice_value = min(c.board_value() for c in sacrifice_pool)
                base -= min(sacrifice_value * 8, 80)
            else:
                base -= 100

        # place_self_bottom_deck: a PROPRIA carta (src) sai do campo pro
        # fundo do deck -- perda de board real, mesmo criterio de escala do
        # tem_ko_own acima (board_value*8, cap 80). O parceiro nomeado do
        # trash (Kin'emon OP10-026/027) NAO desconta -- ja estava fora do
        # campo, sem valor de board corrente (mesmo criterio de
        # place_from_trash_bottom_deck, que tambem nunca e descontado aqui).
        # Achado 17/07: sem isto, mandar o proprio atacante ativo pro fundo
        # do deck pontuaria como se fosse de graca, igual jogar carta grátis
        # normal (base=110 do bloco play_card acima).
        if any(c.get('type') == 'place_self_bottom_deck' for c in costs):
            base -= min(src.board_value() * 8, 80)

        if tem_trash_hand:
            # Comprar descartando da mao nao e vantagem liquida de carta.
            # Ex: leader Imu trasha 1 da mao/campo para comprar 1; isso filtra
            # a mao, mas nao deveria competir como draw puro de score 120 no
            # early quando ainda ha cartas jogaveis para desenvolver campo.
            draw_count = sum(s.get('count', 1) for s in steps
                             if s.get('action') == 'draw')
            trash_count = sum(c.get('count', 1) for c in costs
                              if c.get('type') in ('trash_from_hand',
                                                   'trash_hand',
                                                   'trash_char_or_hand',
                                                   'trash_typed_hand_or_named_hand_field'))
            is_ciclo_neutro = bool(draw_count) and draw_count <= trash_count

            # Estimar qual carta seria trashada e quanto ela vale. Só penaliza
            # aqui quando NAO for ciclo card-neutro (draw>=trash já cobre o
            # trade-off via o cap abaixo) -- achado 09/07: penalizar os dois
            # (perda*0.3 aqui E o cap min(base,45)+early-penalty embaixo)
            # duplo-conta o mesmo custo "abriu mao de 1 carta da mao" e
            # derrubava o score do Imu pra negativo mesmo sem nada melhor
            # pra fazer, encerrando o turno com mao cheia e DON parado.
            if p.hand and not is_ciclo_neutro:
                ee_tmp = EffectExecutor(p, opp)
                pior = min(p.hand, key=ee_tmp._trash_value)
                perda = ee_tmp._trash_value(pior)
                # Se a carta mais "barata" de trashar ainda é cara (jogável), penaliza
                base -= min(perda * 0.3, 60)

            if is_ciclo_neutro:
                base = min(base, 45)
                # GamePlan (HANDOFF #119/#121): num deck cujo plano usa a
                # LIXEIRA como recurso (trash_target > 0, ex: Imu — imunidade
                # com 7+ e Five Elders reanimando do trash), o ciclo "trasha 1
                # → compra 1" não é neutro: cada ativação alimenta o plano.
                # Auditor 11/07 (check F): com o cap de 45 + as penalidades
                # genéricas abaixo, o draw do líder Imu pontuava NEGATIVO em
                # ~25% dos turnos com material sobrando e nunca era ativado.
                plano = compute_game_plan(p)
                alimenta_plano = bool(plano['trash_target']) and len(p.trash) < plano['trash_target']
                if alimenta_plano:
                    base += 30
                playable = [
                    c for c in p.hand
                    if c.card_type in ('CHARACTER', 'STAGE', 'EVENT')
                    and effective_hand_play_cost(p, c, opp) <= p.don_available
                ]
                if (not alimenta_plano and playable and len(p.field_chars) <= 1
                        and GameAnalyzer(p, opp).game_phase() == 'early'):
                    base -= 35

        # Penalizacao de AUTO-TRAVA (achado 30/07, Mihawk-G OP14-020 --
        # unica carta no banco com self_cant_play dentro do PROPRIO
        # activate_main, mas generico pra qualquer carta futura com o
        # mesmo padrao): ativar travava "nao pode jogar Character cards
        # este turno", mas esse custo nunca era descontado do score --
        # self-play instrumentado achou ativacoes reais com don_rested=0
        # (beneficio ZERO de set_don_active) e a mao ainda com 5-9
        # cartas jogaveis, um desperdicio duplo (nem ganha DON de verdade
        # nem deixa jogar o resto da mao). Mesmo criterio/peso ja usado
        # pro self_cant_play de ON_PLAY em avaliar_carta (perdidas*0.5).
        if engine is not None and any(s.get('action') == 'self_cant_play' for s in steps):
            scope = next((s.get('scope', 'chars') for s in steps
                          if s.get('action') == 'self_cant_play'), 'chars')
            gte = next((s.get('cost_gte', 0) for s in steps
                        if s.get('action') == 'self_cant_play'), 0)
            perdidas = 0.0
            for c in p.hand:
                if c.card_type not in ('CHARACTER', 'EVENT', 'STAGE'):
                    continue
                if effective_hand_play_cost(p, c, opp) > p.don_available:
                    continue   # nao jogaria mesmo (sem DON) -- nao conta como perda
                bloqueada = (scope == 'hand'
                             or (c.card_type == 'CHARACTER'
                                 and (gte == 0 or c.cost >= gte)))
                if bloqueada:
                    perdidas += engine.avaliar_carta(c)
            base -= perdidas * 0.5

        # Penalizacoes de AUTO-TRAVA adicionais (achado 01/08, generalizando
        # o self_cant_play do Mihawk-G pras outras 3 cartas do banco com o
        # MESMO padrao -- drawback proprio dentro do PROPRIO activate_main
        # que nunca era descontado do score real): self_cant_take_life
        # (OP06-020 Hody Jones), lock_self_character_refresh (OP04-090
        # Luffy), lock_self_attack_opp_chars_cost_lte (OP12-020 Zoro).
        # _UNCOVERED_ACTION_VALUE ja tinha entrada NEGATIVA pras 2 primeiras,
        # mas so era consumida via max() no fallback generico (nunca reduz
        # o piso, so eleva) -- e nem entrava quando o bloco caia numa
        # categoria explicita antes do fallback (caso do Hody: 'rest_opp_
        # character' cai em "remocao/controle", que nunca olha essa
        # tabela). Na pratica NENHUMA das 3 descontava nada.
        if any(s.get('action') == 'self_cant_take_life' for s in steps):
            base += DecisionEngine._UNCOVERED_ACTION_VALUE['self_cant_take_life']

        if any(s.get('action') == 'lock_self_character_refresh' for s in steps):
            # o proprio src fica rested ate a refresh phase SEGUINTE a
            # proxima (pula 1 untap) -- board perdido por ~1 ciclo inteiro
            # (nao pode bloquear a resposta do oponente nem atacar no
            # proximo turno proprio), mesma familia de peso de
            # place_self_bottom_deck (board_value*8, cap 80) mas um pouco
            # mais leve pq o character CONTINUA no campo (ainda ocupa
            # espaco/ameaca visivel, so nao AGE por um tempo).
            base -= min(src.board_value() * 6, 70)

        if any(s.get('action') == 'lock_self_attack_opp_chars_cost_lte' for s in steps):
            lim = next((s.get('cost_lte', 0) for s in steps
                        if s.get('action') == 'lock_self_attack_opp_chars_cost_lte'),
                       0)
            alvos = [c for c in opp.field_chars if c.cost <= lim]
            if alvos:
                melhor = max(
                    (engine.analyzer.char_value_score(c) if engine is not None
                     else c.board_value())
                    for c in alvos)
                base -= min(melhor * 0.3, 50)

        # Ajustes por prioridade
        if priority == 'LETHAL':
            base -= 30   # prefere atacar quando pode ganhar
        elif priority == 'DEFENSIVE':
            base -= 20

        return base

    def _card_action_key(self, card):
        if card is None:
            return None
        return (
            getattr(card, 'code', ''),
            getattr(card, 'name', ''),
            getattr(card, 'card_type', ''),
            getattr(card, 'cost', 0),
            getattr(card, 'power', 0),
            getattr(card, 'power_buff', 0),
            getattr(card, 'don_attached', 0),
            bool(getattr(card, 'rested', False)),
            bool(getattr(card, 'just_played', False)),
            getattr(card, '_am_used_turn', -1),
        )

    def _action_dedupe_key(self, action):
        _score, kind, obj, ttype, tgt = action
        if kind == 'play':
            return (kind, getattr(obj, 'code', ''), getattr(obj, 'name', ''))
        if kind == 'activate':
            return (kind, self._card_action_key(obj))
        if kind == 'attack':
            return (kind, self._card_action_key(obj), ttype, self._card_action_key(tgt))
        if kind == 'attach_don':
            trig = tgt or {}
            trig_key = (
                trig.get('trigger') if isinstance(trig, dict) else str(trig),
                trig.get('action') if isinstance(trig, dict) else '',
            )
            return (kind, self._card_action_key(obj), ttype, trig_key)
        return (kind, self._card_action_key(obj), ttype, self._card_action_key(tgt))

    def _dedupe_scored_actions(self, actions):
        best_by_key = {}
        order = []
        for action in actions:
            key = self._action_dedupe_key(action)
            if key not in best_by_key:
                order.append(key)
                best_by_key[key] = action
            elif action[0] > best_by_key[key][0]:
                best_by_key[key] = action
        return [best_by_key[key] for key in order]

    def _is_unsafe_zero_life_leader_attack(self, action, p, opp, engine) -> bool:
        """Ataque ao leader com 0 vidas so deve sair se for lethal garantido
        ou se a simulacao Monte Carlo encontrar alguma linha vencedora."""
        _score, kind, _obj, target_type, _target = action
        return (
            kind == 'attack'
            and target_type == 'leader'
            and opp.life_count() == 0
            and not engine.analyzer.can_lethal_this_turn()
        )

    def _cheap_rollout_sample_deltas(self, p, opp, action, rng, don_disponivel=None):
        """
        Uma amostra da camada barata: (d_board_mine, d_opp_removed,
        d_hand, d_don, d_pressure) SEM peso nenhum aplicado ainda.
        Extraido de `_cheap_rollout_value` (13/08, bloco 513) -- passo
        de amostragem isolado numa funcao propria pra ficar claro qual
        parte tem aleatoriedade (alvo de KO/bounce ambiguo, chance de
        ataque conectar), separado da agregacao por peso.

        `don_disponivel`: DON a considerar pro custo de 'play' -- None
        (padrao) usa `p.don_available` (comportamento de sempre, 1 acao
        isolada). Passado explicito por `_cheap_playout_deltas` (bloco
        521) quando esta acao e a Nesima de uma SEQUENCIA fictícia, pra
        respeitar o DON ja "gasto" pelas acoes anteriores da mesma
        amostra -- sem isso, cada acao da sequencia contaria o custo
        contra o DON TOTAL original, sempre, nunca esgotando de verdade.
        """
        score, kind, obj, target_type, target = action
        if don_disponivel is None:
            don_disponivel = p.don_available
        d_board_mine = 0.0    # + = ganho de board_value pro meu lado
        d_opp_removed = 0.0   # + = board_value removido do oponente
        d_hand = 0.0          # + = cartas ganhas na mao
        d_don = 0.0           # + = DON disponivel ganho/poupado
        d_pressure = 0.0      # + = fracao de progresso rumo a dano no lider

        if kind == 'play':
            card = obj
            flags = get_card_flags(card.code)
            d_board_mine += card.board_value()
            d_don -= min(don_disponivel, card.cost)
            if flags.get('draws'):
                d_hand += 1.0
            if flags.get('is_searcher'):
                # busca nem sempre acha algo jogavel na hora -- fracao,
                # nao certeza cheia.
                d_hand += 0.5
            if (flags.get('kos') or flags.get('is_removal')) and opp.field_chars:
                alvo = rng.choice(opp.field_chars)
                d_opp_removed += alvo.board_value()
            if flags.get('bounces') and opp.field_chars:
                alvo = rng.choice(opp.field_chars)
                d_opp_removed += alvo.board_value()
            if flags.get('power_buff'):
                d_board_mine += 1.0
            if flags.get('gives_don'):
                d_don += 1.0
        elif kind == 'activate':
            source = obj
            flags = get_card_flags(source.code)
            if (flags.get('kos') or flags.get('is_removal')) and opp.field_chars:
                alvo = rng.choice(opp.field_chars)
                d_opp_removed += alvo.board_value()
            if flags.get('draws'):
                d_hand += 1.0
            if flags.get('gives_don'):
                d_don += 1.0
        elif kind == 'attack':
            attacker = obj
            atk_power = attacker.effective_power()
            if target_type == 'leader':
                defesa = opp.leader.power + opp.leader.power_buff
                # chance grosseira de conectar sem bloqueio/counter
                # relevante -- proxy rapido, nao substitui
                # opp_counter_potential/should_use_blocker de verdade.
                if atk_power >= defesa and rng.random() < 0.7:
                    d_pressure += 1.0
            elif target is not None:
                alvo_power = target.effective_power()
                if atk_power >= alvo_power:
                    d_opp_removed += target.board_value()

        return d_board_mine, d_opp_removed, d_hand, d_don, d_pressure

    def _cheap_playout_deltas(self, p, opp, first_action, max_steps, rng):
        """
        Sequencia de ate `max_steps` acoes baratas a partir de
        `first_action` (bloco 521). EXCECAO EXPLICITA, autorizada pelo
        usuario 13/08 ("pode abrir uma excecao dessa vez"), a
        REGRA_SEM_DUPLICACAO -- ver HANDOFF bloco 521 pro registro
        completo. Motivo: a camada barata de UM passo so (`_cheap_
        rollout_sample_deltas` sozinha) nunca melhorava com mais
        amostra porque nao tinha profundidade nenhuma pra explorar (so
        reduzia ruido de uma estimativa ja rasa) -- o usuario pediu uma
        "simulacao de verdade" estilo NarutoSim (sequencia de jogadas,
        nao 1 carta isolada), o que exige uma aproximacao de "jogar
        varias cartas seguidas" SEM pagar o custo da busca real
        (`_apply_action`/`EffectExecutor`, que resolve regra completa).

        Escopo restrito (mantem o "raso" barato, so acrescenta
        profundidade de SEQUENCIA):
        - Encadeia acoes 'play' da mao restante E 'attack' (ao lider,
          o caso mais universal) dos personagens reais que ainda podem
          atacar -- corrigido 13/08 (bloco 523, achado real: a versao
          anterior so encadeava 'play', o que enviesava sistematicamente
          a favor de "jogar mais carta" sobre "atacar agora" (so 'play'
          ganhava profundidade), medido causando REGRESSAO real quando
          usado como sinal de confianca -- ver HANDOFF bloco 522/523).
          Cada passo escolhe, entre TODAS as cartas jogaveis e TODOS os
          atacantes disponiveis, quem tem o maior delta PONDERADO (mesmos
          termos de EVAL_WEIGHTS usados no total final, pra comparar
          'play' e 'attack' na MESMA escala) -- nao so board_value().
        - So considera ataque ao LIDER (nao a personagens do oponente) --
          simplificacao deliberada, cobre o caso mais comum/universal
          sem precisar escolher alvo entre personagens.
        - Personagens jogados FICTICIAMENTE nesta amostra NAO viram
          atacantes validos nos passos seguintes (nao tem rush/sickness
          modelado aqui) -- so os que JA estavam em campo de verdade.
        - NAO rastreia quais personagens do oponente ja foram "removidos"
          por uma acao anterior da MESMA sequencia -- 2 remocoes na
          mesma amostra podem contar o mesmo alvo 2x. Ruido aceito (a
          media sobre muitas amostras ja dilui isso), documentado aqui
          em vez de escondido.
        - NUNCA usada pra decidir a acao final sozinha (mesmo principio
          da fase 1) -- so alimenta `cheap_values` que ALARGA o
          shortlist da busca cara de verdade, que continua sendo a
          FONTE UNICA da decisao real.

        Opera SEM mutar os objetos reais `p`/`opp` -- so acumula deltas
        e rastreia mao/DON/atacantes restantes em variaveis locais.
        """
        d_board_mine, d_opp_removed, d_hand, d_don, d_pressure = (
            self._cheap_rollout_sample_deltas(p, opp, first_action, rng))

        W = getattr(p, 'eval_weights', None) or EVAL_WEIGHTS

        def peso(deltas):
            dbm, dor, dh, dd, dp = deltas
            return (dbm * W['board_mine'] + dor * W['board_opp']
                    + dh * W['hand_first'] + dd * W['don_field']
                    + dp * W['dmg'] * 0.1)

        mao_restante = list(p.hand)
        kind0, obj0 = first_action[1], first_action[2]
        if kind0 == 'play' and obj0 in mao_restante:
            mao_restante.remove(obj0)
        don_restante = p.don_available + d_don   # d_don ja e <= 0 (custo)

        atacantes_disponiveis = [
            c for c in ([p.leader] + list(p.field_chars))
            if character_can_attack_now(c, p, opp)
               and not (kind0 == 'attack' and c is obj0)
        ]

        for _ in range(max(0, max_steps - 1)):
            candidatas = []
            for c in mao_restante:
                if c.cost <= don_restante:
                    acao_fake = (0.0, 'play', c, None, None)
                    deltas = self._cheap_rollout_sample_deltas(
                        p, opp, acao_fake, rng, don_disponivel=don_restante)
                    candidatas.append(('play', c, deltas))
            for att in atacantes_disponiveis:
                acao_fake = (0.0, 'attack', att, 'leader', None)
                deltas = self._cheap_rollout_sample_deltas(
                    p, opp, acao_fake, rng, don_disponivel=don_restante)
                candidatas.append(('attack', att, deltas))
            if not candidatas:
                break
            melhor_kind, melhor_obj, melhor_deltas = max(candidatas, key=lambda c: peso(c[2]))
            dm, dor, dh, dd, dp = melhor_deltas
            d_board_mine += dm
            d_opp_removed += dor
            d_hand += dh
            d_don += dd
            d_pressure += dp
            if melhor_kind == 'play':
                don_restante += dd   # dd <= 0
                mao_restante.remove(melhor_obj)
            else:
                atacantes_disponiveis = [a for a in atacantes_disponiveis if a is not melhor_obj]

        return d_board_mine, d_opp_removed, d_hand, d_don, d_pressure

    def _cheap_rollout_value(self, p, opp, action, n_samples=CHEAP_LAYER_SAMPLES,
                              rng=None, playout_steps=CHEAP_LAYER_PLAYOUT_STEPS):
        """
        Camada BARATA ("calibragem dinamica", bloco 508/509, profundidade
        de sequencia adicionada bloco 521): aproxima o valor de uma acao
        candidata SEM resolver o efeito de verdade (nao chama
        _execute_step/_apply_action) -- so olha as flags ja pre-parseadas
        (get_card_flags, MESMA fonte que avaliar_carta usa pros bonus de
        has_ko/has_search/etc, ver REGRA_SEM_DUPLICACAO: nao reimplementa
        deteccao propria) e aplica um delta grosseiro sobre um resumo
        generico do estado (board meu/dele, mao, DON, pressao de dano) --
        os MESMOS termos universais de EVAL_WEIGHTS, mesma escala, pra
        ficar comparavel. Desde o bloco 521, `_cheap_playout_deltas`
        estende essa unica acao numa SEQUENCIA de ate `playout_steps`
        jogadas (exececao explicita a REGRA_SEM_DUPLICACAO, autorizada
        pelo usuario -- ver HANDOFF bloco 521): sem isso, mais amostra
        (`n_samples`) nunca ajudava, porque uma acao isolada nao tem
        profundidade nenhuma pra explorar, so ruido de alvo ambiguo.

        Roda `n_samples` vezes com pequena aleatoriedade nas partes
        ambiguas (ex: qual corpo do oponente seria removido por um KO
        sem alvo declarado) e tira a media -- um sinal RAPIDO, nunca um
        substituto da busca real (_select_action_via_search). Usado por
        `_select_search_candidates` (via `cheap_values=`) so pra ALARGAR
        o shortlist que recebe a busca cara, nunca pra decidir a acao
        final sozinho.

        Retorna um float na mesma ordem de grandeza do `score` imediato
        de `_generate_and_score_actions` -- serve pra RANKEAR candidatas
        entre si, nao tem significado absoluto proprio.
        """
        # _CHEAP_LAYER_RNG (bloco 518), NUNCA o modulo `random` global --
        # contaminaria o stream de aleatoriedade REAL do jogo (deck
        # shuffle/compra), fazendo `CHEAP_LAYER_SAMPLES` mudar a MAO que
        # sai em partidas de self-play com a MESMA seed (achado real:
        # confundiu a comparacao 40-vs-3000 do bloco 517 inteira).
        rng = rng or _CHEAP_LAYER_RNG
        W = getattr(p, 'eval_weights', None) or EVAL_WEIGHTS

        total = 0.0
        for _ in range(max(1, n_samples)):
            d_board_mine, d_opp_removed, d_hand, d_don, d_pressure = (
                self._cheap_playout_deltas(p, opp, action, playout_steps, rng))
            total += (d_board_mine * W['board_mine']
                      + d_opp_removed * W['board_opp']
                      + d_hand * W['hand_first']
                      + d_don * W['don_field']
                      + d_pressure * W['dmg'] * 0.1)

        return total / max(1, n_samples)

    def _compute_cheap_values(self, p, opp, actions, n_samples=CHEAP_LAYER_SAMPLES,
                               rng=None):
        """
        Calcula `_cheap_rollout_value` pra TODA a lista de acoes
        (score>=0 apenas, mesmo corte de elegibilidade de
        `_select_search_candidates`), devolvendo um dict {id(acao): valor}
        pronto pra passar como `cheap_values=` la. Funcao separada (nao
        inline) pra poder ser chamada 1x e reusada tanto pelo corte do
        shortlist quanto pelo log de auditoria (mesmos valores, sem
        recalcular).
        """
        rng = rng or _CHEAP_LAYER_RNG
        return {id(a): self._cheap_rollout_value(p, opp, a, n_samples, rng)
                for a in actions if a[0] >= 0}

    def _select_search_candidates(self, actions, top_k, priority,
                                   min_candidates=SEARCH_MIN_CANDIDATES,
                                   score_window=SEARCH_SCORE_WINDOW,
                                   cheap_values=None):
        """
        Recorta, a partir da lista COMPLETA de ações pontuadas
        (`_generate_and_score_actions`, ordenada por score desc), quais
        entram na busca Monte Carlo (`_select_action_via_search`). FONTE
        ÚNICA usada tanto pelo Turn Planner offline (`main_phase`) quanto
        pelo caminho AO VIVO (`sim_bridge.choose_action`) -- unificação
        26/07 (pedido do usuário: "tem que ser o mesmo nos dois"). Só
        `top_k` (quantas candidatas custam simulação) varia por chamador,
        por orçamento de tempo; a POLÍTICA de quais candidatas valem a
        pena comparar (janela de score, diversidade em REMOVE_THREAT) é
        idêntica nos dois lugares.

        `actions` já deve vir filtrada pelo chamador por qualquer critério
        de ELEGIBILIDADE que só faça sentido nesse contexto (ex.: ao vivo,
        tipo executável pelo plugin / ativação já recusada este turno) --
        esta função só decide QUANTAS e QUAIS das elegíveis entram na
        comparação, não filtra elegibilidade.
        """
        if not actions:
            return []
        top_score = actions[0][0]
        candidatas = [
            acao for idx, acao in enumerate(actions[:top_k])
            if acao[0] >= 0
            and (idx < min_candidates or acao[0] >= top_score - score_window)
        ]
        if priority == 'REMOVE_THREAT':
            # A remoção de uma ameaça crítica pode receber score imediato
            # muito alto (ex.: Roger/Shanks), estreitando demais a janela.
            # Mantém essa pressão, mas garante diversidade para a
            # simulação comparar pelo menos algumas linhas de
            # desenvolvimento.
            seen_candidate_ids = {id(acao) for acao in candidatas}

            def include_best_kind(kind: str, limit: int):
                current = sum(1 for acao in candidatas if acao[1] == kind)
                for acao in actions:
                    if current >= limit:
                        break
                    if acao[0] < 0 or acao[1] != kind or id(acao) in seen_candidate_ids:
                        continue
                    candidatas.append(acao)
                    seen_candidate_ids.add(id(acao))
                    current += 1

            include_best_kind('play', 1)
            include_best_kind('activate', 1)
            candidatas.sort(key=lambda acao: acao[0], reverse=True)

        if cheap_values:
            # Fase 1 da "calibragem dinamica" (bloco 508/509): ALARGA o
            # shortlist com candidatas que o sinal barato aponta como
            # promissoras mesmo fora do top_k/janela do score estatico --
            # nunca remove nada que a politica de score ja garantiu acima,
            # so adiciona ate CHEAP_LAYER_EXTRA_CANDIDATES extras, e SO
            # quando o proprio sinal barato julga a candidata excluida tao
            # boa quanto a PIOR das ja incluidas (limiar auto-referente --
            # achado real ao testar: sem limiar, isto sempre completava ate
            # CHEAP_LAYER_EXTRA_CANDIDATES vagas com o que sobrasse, mesmo
            # com valor baixo, em vez de so promover candidata realmente
            # competitiva).
            ja_incluidas = {id(acao) for acao in candidatas}
            cheap_incluidas = [cheap_values[id(a)] for a in candidatas if id(a) in cheap_values]
            limiar = min(cheap_incluidas) if cheap_incluidas else float('-inf')
            pool_extra = [acao for acao in actions
                         if acao[0] >= 0 and id(acao) not in ja_incluidas
                         and id(acao) in cheap_values
                         and cheap_values[id(acao)] >= limiar]
            pool_extra.sort(key=lambda acao: cheap_values[id(acao)], reverse=True)
            adicionadas = pool_extra[:CHEAP_LAYER_EXTRA_CANDIDATES]
            for acao in adicionadas:
                candidatas.append(acao)
                ja_incluidas.add(id(acao))
            # Canal lateral pra auditoria (mesmo padrao de `engine.
            # _posture_cache`, cache de instancia, nao muda a assinatura de
            # retorno): `main_phase` le isto logo apos a chamada e repassa
            # pra `_log_turn_planner_decision` -- deixa `audit_cheap_layer.py`
            # medir se as candidatas que SO a camada barata promoveu (nao
            # entrariam no shortlist estatico sozinho) realmente viram a
            # melhor escolha na busca real, ou se o alargamento so gasta
            # orcamento a toa.
            self._last_cheap_layer_additions = {id(a) for a in adicionadas}
        else:
            self._last_cheap_layer_additions = set()

        return candidatas

    def _select_action_via_search(self, p, opp, engine, candidatas, model,
                                   max_steps, extra_own_turn_search,
                                   samples_min, samples_max, batch_size,
                                   z_threshold=2.0, rng=random):
        """
        Dado um conjunto de candidatas JÁ recortado (`_select_search_candidates`,
        `len(candidatas) >= 2`), decide a melhor via Monte Carlo. FONTE ÚNICA
        usada tanto pelo Turn Planner offline (`main_phase`) quanto pelo
        caminho AO VIVO (`sim_bridge.choose_action`) -- unificação 26/07
        (pedido do usuário: receio de "o bot receber dois comandos de
        decisão diferentes... tem que ser o mesmo nos dois"). Antes, cada
        lado tinha seu próprio laço reimplementado à mão, com resultado
        parecido mas NÃO idêntico -- o offline tinha janela/diversidade de
        candidatas e a guarda `_is_unsafe_zero_life_leader_attack`; o
        caminho ao vivo não tinha NENHuma das duas.

        Amostragem SEQUENCIAL em lotes: para no PISO (`samples_min`) assim
        que a diferença de valor entre a LÍDER e a VICE-LÍDER (maior e
        segunda maior média corrente, que podem trocar de identidade a
        cada lote) fica estatisticamente clara (teste pareado, mesmas
        amostras dos dois lados via CRN), só sobe até o TETO
        (`samples_max`) quando o gap ainda não é confiável (achado 26/07
        do sweep de qualidade: mais amostras melhora objetivamente a
        escolha, mas só vale gastar quando o gap não está resolvido).
        Generalizado pra N>=2 candidatas (13/08, bloco 512) -- antes só
        existia pra N==2 exatas; com N>=3 (comum desde a camada barata,
        bloco 508-510, que alarga o shortlist justamente pra trazer mais
        candidatas boas pra briga) o código sempre parava cego em
        `samples_min`, sem testar nada: gastava o piso inteiro numa
        decisão óbvia (desperdício) e nunca subia pro teto numa decisão
        genuinamente difícil (as 3+ candidatas empatadas ficavam com
        MENOS precisão adaptativa que um empate de só 2 teria). `samples_
        min == samples_max` degenera num N FIXO clássico (1 lote só, sem
        teste de significância, o break do loop nunca é alcançado) -- é
        assim que o offline chama hoje, preservando seu comportamento/
        custo atual byte a byte; o caminho ao vivo usa piso/teto de
        verdade (12/24).

        Retorna (melhor_action_ou_None, melhor_valor, search_records,
        amostras_usadas, sim_values_by_id). `melhor` vem `None` só se
        TODAS as candidatas forem descartadas pela guarda de segurança
        (nenhuma linha vencedora encontrada pra um ataque arriscado ao
        líder com vida 0) -- o chamador decide o que fazer nesse caso
        (offline: encerra o planejamento do turno; ao vivo: mantém o
        fallback de score imediato já calculado antes desta busca).
        """
        if model is None:
            # Sem modelo de oponente disponível (só acontece no caminho ao
            # vivo, quando nenhuma camada de fallback de `opponent_model_for_leader`
            # tem pool -- líder E cor totalmente desconhecidos): 1 simulação
            # determinística contra o estado público, sem amostragem.
            melhor, melhor_valor = None, None
            search_records = []
            sim_values = {}
            for cand in candidatas:
                valores = self._simulate_sequence_values(
                    p, opp, cand, max_steps=max_steps, amostras=None,
                    extra_own_turn_search=extra_own_turn_search)
                valor = sum(valores) / len(valores) if valores else -1e9
                search_records.append({"action": cand, "value": valor})
                sim_values[id(cand)] = {'avg': valor, 'wins': 0, 'samples': 0}
                if melhor_valor is None or valor > melhor_valor:
                    melhor_valor = valor
                    melhor = cand
            return melhor, melhor_valor, search_records, 0, sim_values

        valores_por_cand: list = [[] for _ in candidatas]
        n_coletadas = 0
        while n_coletadas < samples_max:
            batch = min(batch_size, samples_max - n_coletadas)
            novas_amostras = [model.sample(opp, rng=rng) for _ in range(batch)]
            for i, cand in enumerate(candidatas):
                valores_por_cand[i].extend(
                    self._simulate_sequence_values(
                        p, opp, cand, max_steps=max_steps, amostras=novas_amostras,
                        extra_own_turn_search=extra_own_turn_search))
            n_coletadas += batch
            if n_coletadas < samples_min:
                continue
            # Teste pareado generalizado (ver docstring) -- lider (maior
            # media corrente) vs vice (segunda maior). Com N==2 os dois
            # unicos indices SAO a lider/vice, byte-compativel com o teste
            # antigo (so muda o sinal possivel de `media`, irrelevante
            # porque so `abs(media)` importa abaixo).
            medias = [sum(v) / len(v) if v else float('-inf') for v in valores_por_cand]
            i_lider, i_vice = sorted(range(len(candidatas)), key=lambda i: medias[i], reverse=True)[:2]
            deltas = [a - b for a, b in zip(valores_por_cand[i_lider], valores_por_cand[i_vice])]
            media = sum(deltas) / len(deltas)
            if len(deltas) > 1:
                var = sum((d - media) ** 2 for d in deltas) / (len(deltas) - 1)
                stderr = (var / len(deltas)) ** 0.5
            else:
                stderr = 0.0
            if stderr == 0.0 or abs(media) > z_threshold * stderr:
                break

        melhor, melhor_valor = None, None
        search_records = []
        sim_values = {}
        for i, cand in enumerate(candidatas):
            valores = valores_por_cand[i]
            valor = sum(valores) / len(valores) if valores else -1e9
            wins = sum(1 for v in valores if v >= SIMULATED_WIN_SCORE)
            search_records.append({"action": cand, "value": valor})
            sim_values[id(cand)] = {'avg': valor, 'wins': wins, 'samples': len(valores)}
            if self._is_unsafe_zero_life_leader_attack(cand, p, opp, engine) and wins == 0:
                continue
            if melhor_valor is None or valor > melhor_valor:
                melhor_valor = valor
                melhor = cand
        return melhor, melhor_valor, search_records, n_coletadas, sim_values

    def _generate_and_score_actions(self, p, opp, engine, exclude_activate_uids=None):
        """
        Gera TODAS as ações possíveis no estado atual e as pontua.
        Retorna lista de (score, tipo, dados) ordenada por score desc.

        Ações: ('play', card) | ('activate', source) | ('attack', attacker, ttype, tgt)

        exclude_activate_uids: card_uids cuja ativação foi ENVIADA ao jogo
        real este turno e confirmada SEM efeito (ver exclude_failed_actions
        em sim_bridge.choose_action / _failed_actions_this_turn em
        server.py). Achado real 26/07 (bloco HANDOFF 370, OP09-093 x2 em
        campo): _dedupe_scored_actions (abaixo) agrupa múltiplas cópias da
        MESMA carta com o MESMO estado (código/power/custo/rested/
        _am_used_turn) numa única ação candidata — sem excluir a cópia que
        falhou ANTES do dedupe, filtrar depois (só no sim_bridge) não
        adianta: a cópia que falhou já é a única representante da dupla no
        candidato final, e a 2ª cópia nunca aparece pra ocupar o lugar
        dela. Filtrar aqui, na fonte, deixa a 2ª cópia sobrar como única
        candidata e virar a nova representante do dedupe.
        """
        actions = []
        a = engine.analyzer

        # Invalida o cache de posture() (achado real 02/08, otimizacao de
        # performance): `engine` e reutilizado pelo CHAMADOR (main_phase/
        # _play_turn_greedy) ao longo de VARIAS acoes aplicadas em sequencia
        # dentro do mesmo turno, cada uma mutando p/opp (jogar carta, atacar,
        # etc.) -- sem invalidar aqui, a postura calculada ANTES da 1a acao
        # ficaria presa pelo resto do turno, mesmo com vida/DON/board
        # diferentes depois. Reset 1x por CICLO de pontuacao (aqui), nao por
        # avaliar_carta (o cache ainda serve pra evitar recomputar dentro do
        # MESMO ciclo, so nao atravessa mutacao de estado).
        engine._posture_cache = None

        # PRIORIDADE DE ANÁLISE (cascata de inclinação): o modo dominante ajusta
        # os pesos das ações, respeitando a ordem do documento sem bloquear.
        priority = a.analysis_priority()
        threats = a.critical_threats() if priority == 'REMOVE_THREAT' else []
        don_reserve = engine._don_reserve_for_defense()

        # ── Ações de JOGAR carta ──
        for card in p.hand:
            don_usable = engine._don_usable_for_play(card, don_reserve)
            if not engine._can_play_card(card, don_usable=don_usable):
                continue
            score = self._score_play_action(card, engine)
            score += self._human_pattern_bonus(p, 'play', card)
            # Inclinação: desenvolver ganha peso no modo DEVELOP; perde no LETHAL/DEFENSIVE
            if priority == 'DEVELOP':
                score += 40
            elif priority == 'LETHAL':
                score -= 60   # não desenvolve quando pode ganhar — ataca
            # Carta defensiva (blocker/counter) ganha peso no modo DEFENSIVE ou
            # PREVENT_COMBO (guardar recurso pro turno da virada do oponente,
            # bônus menor que DEFENSIVE porque a ameaça ainda não é iminente)
            if (card.has_blocker or card.blocker_this_turn or card.counter > 0):
                if priority == 'DEFENSIVE':
                    score += 120
                elif priority == 'PREVENT_COMBO':
                    score += PREVENT_COMBO_DEFENSIVE_CARD_BONUS
            # Preservacao de mao (partida real 04/07: bot esvaziou a mao em
            # deploys e ficou sem counter/custo de reacao para defender).
            # Mao encolhendo = cada play adicional fica mais caro.
            if len(p.hand) <= 3:
                score -= (4 - len(p.hand)) * 30
            actions.append((score, 'play', card, None, None))

        # ── Ações de ATACAR (com risco de trigger descontado) ──
        # Orcamento da linha: um ataque nao pode se declarar alcancavel usando
        # DON que a propria geracao ja comprometeu com a melhor jogada. Antes
        # o score via todo o pool, mas a execucao reservava esse DON e atacava
        # abaixo do alvo. LETHAL continua livre para gastar tudo.
        planned_play_cost = 0
        positive_plays = [a for a in actions if a[1] == 'play' and a[0] >= 80]
        if positive_plays and priority != 'LETHAL':
            best_play = max(positive_plays, key=lambda a: a[0])
            planned_play_cost = effective_hand_play_cost(p, best_play[2], opp)
        attack_don_budget = max(0, p.don_available - planned_play_cost)

        if p.can_attack_this_turn():
            # "Taunt" (Eustass Kid OP01-051, Captain John OP17-044): se o
            # OPONENTE tem uma carta com force_opp_attack_self ativa agora,
            # QUALQUER ataque meu so pode mirar essa carta especifica --
            # calculado 1x aqui, aplicado nos dois loops de alvo abaixo
            # (lider e character).
            taunt_alvo = active_taunt_character(opp, p)
            attackers = [c for c in p.field_chars
                         if character_can_attack_now(c, p, opp)]
            # Achado real 03/08 (usuario pediu pra investigar a restricao
            # "cannot attack" ignorada, apos o teste de ativacao do lider
            # Vegapunk): o lider entrava na lista de atacantes so checando
            # `not p.leader.rested`, nunca passando por
            # `character_can_attack_now`/`is_attack_locked_self` -- mesma
            # checagem que field_chars ja usa. Qualquer lider com "This
            # Leader cannot attack" (Iceburg, Nefeltari Vivi, Rebecca x2,
            # Vegapunk, Shirahoshi) gerava e pontuava uma acao de ataque
            # que o jogo real recusaria.
            if character_can_attack_now(p.leader, p, opp):
                attackers.append(p.leader)
            for att in attackers:
                # Buff opcional com DON-minus so entra no poder planejado se
                # nao sacrifica a curva. Caso contrario a declaracao precisa
                # ser valida com o poder que ja existe no estado publico.
                atk_now_for_budget = attack_time_power(att, opp)
                wa = get_card_effects(att.code).get('when_attacking', {})
                wa_don_minus = sum(int(c.get('count', 1) or 1)
                                   for c in wa.get('costs', [])
                                   if c.get('type') == 'don_minus')
                if (wa_don_minus
                        and engine.don_minus_delays_hand_curve(wa_don_minus)
                        and engine.don_return_trigger_value(wa_don_minus) <= 0):
                    atk_now_for_budget = live_attack_power(att)
                # [Rush: Character] restringe o alvo a Characters do
                # oponente neste turno -- nao gera a opcao de atacar o Leader.
                # Taunt (taunt_alvo != None): lider NUNCA pode ser o alvo do
                # taunt, entao a opcao de atacar o lider some por completo
                # enquanto o taunt estiver ativo.
                pode_atacar_leader = (not getattr(att, 'rush_character_only_this_turn', False)
                                      and taunt_alvo is None)
                # alvo líder
                if pode_atacar_leader and not p.cannot_attack_leader_this_turn:
                    s_leader = engine.score_attack_target(att, 'leader', None)
                    atk_now = atk_now_for_budget
                    # +power_buff: mesmo achado do bloco 434 (re-check
                    # redundante de score_attack_target, precisa da MESMA
                    # conta pra nao divergir).
                    leader_power_now = opp.leader.power + opp.leader.power_buff
                    if (atk_now < leader_power_now
                            and atk_now + attack_don_budget * 1000 < leader_power_now
                            and not engine._rest_attack_has_material_benefit(att)):
                        s_leader = -999
                    if s_leader > -500:
                        s_leader += self._human_pattern_bonus(p, 'attack', att)
                        # Desconto de trigger, LIMITADO a no maximo metade do
                        # valor do proprio ataque (achado ao vivo 23-24/07,
                        # pedido do usuario pra investigar por que o bot
                        # ataca menos que um humano): antes era subtracao
                        # fixa (vida_opp*8, sem teto) igual pra qualquer
                        # ataque -- so o LIDER tem piso protetor (max(s,15)
                        # abaixo); um personagem atacando nao tem proteção
                        # nenhuma, entao esse desconto sozinho podia zerar/
                        # inverter um ataque que era bom por qualquer outro
                        # motivo (caso real: 2 ataques de 5000 empatando
                        # contra lider 5000 -- empate favorece quem ataca,
                        # ataque legitimo -- pontuaram -32 SO por causa do
                        # desconto de trigger, viraram vermelho e ficaram
                        # parados). O risco de trigger e real (so se
                        # materializa quando o dano de fato conecta), mas
                        # nao deve conseguir SOZINHO transformar um ataque
                        # bom em ataque ruim -- desconta ate metade do valor
                        # que o ataque tinha antes deste termo especifico.
                        penalidade_trigger = self._trigger_risk_penalty(opp)
                        s_leader -= min(penalidade_trigger, max(0.0, s_leader) * 0.5)
                        # Banish: prioriza atacar a vida (nega trigger e remove a carta
                        # de vez). Inclinação forte, mas a ameaça crítica ainda vem antes.
                        if att.has_banish:
                            s_leader += 150
                        # Com a vida do oponente critica (0 ou 1 carta), CONECTAR
                        # no lider vale mais que qualquer prioridade generica de
                        # postura -- as penalidades de DEFENSIVE/REMOVE_THREAT
                        # nao sabiam disso e descontavam o ataque ao lider do
                        # MESMO jeito que descontariam num turno qualquer.
                        # Achado real 08/08 (usuario, primeira vitoria ao vivo do
                        # bot -- "poderia ter ganho 1 turno antes"): com
                        # opp_life==0 e o ataque do lider com folga real de poder
                        # (sem precisar de letal CERTIFICADO), score_attack_target
                        # ja da 130 (nao 10000, pois can_lethal_this_turn exige
                        # garantia mesmo no pior caso de defesa) -- mas o -100 de
                        # REMOVE_THREAT (havia um Character ameacador em campo)
                        # derrubava pra 30, perdendo pro ataque ao Character. Vida
                        # 0/1 ja e o MESMO sinal que os bonus LETHAL/PREVENT_COMBO
                        # respeitam -- as penalidades de postura devem ceder aqui
                        # tambem, nao so os bonus.
                        opp_life_critica = opp.life_count() <= 1
                        if priority == 'LETHAL':       s_leader += 500   # foco em fechar
                        elif priority == 'DEFENSIVE' and not opp_life_critica:  s_leader -= 80    # não exponha à toa
                        elif priority == 'REMOVE_THREAT' and not opp_life_critica: s_leader -= 100 # remova antes
                        # PREVENT_COMBO (achado 07/07): oponente pode virar o
                        # jogo reanimando o trash no turno dele -- correr o
                        # clock agora (antes da virada) vale mais que o normal,
                        # mas menos que LETHAL (não é vitória garantida).
                        elif priority == 'PREVENT_COMBO': s_leader += PREVENT_COMBO_LEADER_ATTACK_BONUS
                        # Ataque de LÍDER validado é quase grátis (ele resta de
                        # qualquer jeito no fim do turno, não expõe personagem):
                        # postura defensiva + risco de trigger não podem
                        # negativá-lo a ponto de passar o turno sem atacar
                        # (visto em partida real: score -4 → líder ficou parado).
                        if att is p.leader:
                            s_leader = max(s_leader, 15)
                        actions.append((s_leader, 'attack', att, 'leader', None))
                # alvos personagem
                cost_lock = getattr(att, 'cannot_attack_opp_chars_cost_lte', -1)
                for tgt in opp.rested_chars(att):
                    # Taunt: so a carta com force_opp_attack_self ativo pode
                    # ser mirada enquanto ele estiver ativo -- qualquer outro
                    # Character do oponente fica fora de alcance.
                    if taunt_alvo is not None and tgt is not taunt_alvo:
                        continue
                    # Auto-restricao de alvo (OP12-020): nao pode atacar
                    # Characters do oponente com custo <= N neste turno.
                    if cost_lock >= 0 and tgt.cost <= cost_lock:
                        continue
                    s_char = engine.score_attack_target(att, 'character', tgt)
                    atk_now = atk_now_for_budget
                    # +power_buff: mesmo achado do bloco 434.
                    tgt_power_now = tgt.power + tgt.power_buff
                    if (atk_now < tgt_power_now
                            and atk_now + attack_don_budget * 1000 < tgt_power_now):
                        s_char = -999
                    if s_char > -500:
                        s_char += self._human_pattern_bonus(p, 'attack', att)
                        # Inclinação: remover a AMEAÇA CRÍTICA ganha prioridade alta
                        # -- MAS so se o ataque tem chance real de conectar/matar.
                        # Achado real 21/07 (partida ao vivo): Baron Tamago &
                        # Pekoms (ST34-005, when_attacking KO opp_character
                        # power<=2000, custo 1 DON) atacou Vergo (9000 de poder)
                        # com so 6000 (4000 + 2 DON, o maximo disponivel) --
                        # mesmo com score_attack_target ja corrigido pra nao
                        # empilhar bonus de remocao num ataque sem chance
                        # (achado 20/07), esse +300 de "alvo e ameaca critica"
                        # e aplicado AQUI, fora da funcao, sem checar a mesma
                        # coisa -- mesmo bug, lugar diferente. Vergo virou
                        # "ameaca critica" (score 450 = ~150 do gatilho +300),
                        # empatando/batendo outras opcoes reais na busca.
                        if tgt in threats:
                            atk_power = attack_time_power(att, opp)
                            pode_matar = (atk_power >= tgt.power
                                         or atk_power + attack_don_budget * 1000 >= tgt.power)
                            if pode_matar:
                                s_char += min(120.0, a.future_threat_value(tgt))
                        actions.append((s_char, 'attack', att, 'character', tgt))

        # ── Ações de ATIVAR efeitos [Activate:Main] ──
        sources = []
        if p.leader:
            sources.append(p.leader)
        if p.field_stage:
            sources.append(p.field_stage)
        sources.extend(p.field_chars)
        for src in sources:
            effects = get_card_effects(src.code)
            am = effects.get('activate_main')
            if not am:
                continue
            # Fonte RESTADA nao ativa: a maioria dos [Activate: Main] de
            # personagem custa restar a propria carta, e o parser nem sempre
            # captura o rest_self (Laffitte OP09-095 06/07: engine reofereceu
            # o activate com ele restado, o jogo recusou em silencio e o
            # guarda de loop encerrou o turno com 4 DON em pe).
            # EXCECAO (auditor 11/07, check F): o LIDER cujo activate nao
            # custa rest_self (ex: Imu — custo e so trash) PODE ativar
            # restado; regra oficial nao exige a fonte ativa. A guarda
            # derrubava o draw do lider em todo turno em que ele atacava
            # ANTES de ativar (~25% dos turnos auditados). Personagens/
            # stages continuam conservadores (risco de rest_self perdido
            # pelo parser).
            if getattr(src, 'rested', False):
                exige_rest_self = any(c.get('type') == 'rest_self'
                                      for c in am.get('costs', []))
                if exige_rest_self or src is not p.leader:
                    continue
            # Ja usado NESTE turno: rastreado pelo engine na simulacao, ou
            # pelo jogo (lb_ActionsUsed -> actionUsed no DTO) no caminho do
            # bot. Vale para qualquer activate, com ou sem once_per_turn —
            # o estado do jogo e a verdade (loops do Laffitte/Devon 06/07).
            if getattr(src, '_am_used_turn', -1) == p.turn:
                continue
            # Instancia especifica cuja ativacao ja foi tentada e o jogo
            # real confirmou SEM efeito este turno (ver docstring acima) --
            # exclui ANTES do dedupe pra 2a copia poder virar candidata.
            if exclude_activate_uids and getattr(src, '_deck_uid', 0) in exclude_activate_uids:
                continue
            # [DON!! xN] e requisito de estado, nao custo pago durante a
            # ativacao. Sem o DON ja anexado, o bot deve primeiro gerar a
            # acao attach_don e so oferecer activate na decisao seguinte.
            don_req = am.get('don_requirement', 0)
            if don_req and getattr(src, 'don_attached', 0) < don_req:
                continue
            pode, _ = self._should_activate_main(src, am, p, opp)
            if not pode:
                continue
            score = self._score_activate_main(src, am, p, opp, priority, engine=engine)
            score += self._human_pattern_bonus(p, 'activate', src)
            actions.append((score, 'activate', src, None, None))

        # ── Ações de ANEXAR DON para ligar efeitos/keywords [DON!! ×N] ──
        actions.extend(self._generate_attach_don_actions(p, opp, engine, priority=priority))

        actions = self._dedupe_scored_actions(actions)
        actions.sort(key=lambda x: x[0], reverse=True)
        return actions

    def _generate_attach_don_actions(self, p, opp, engine, priority=None):
        """
        Gera ações de ANEXAR DON para ligar efeitos/keywords [DON!! ×N].
        Avalia cada personagem em campo que tem efeito condicional a DON e ainda
        não atingiu o requisito. Vale anexar se o efeito ligado compensa prender
        o DON (custo ~25/DON), modulado pelo estado (postura/prioridade).
        """
        DON_COST = 25
        acts = []
        if p.don_available <= 0:
            return acts
        if priority is None:
            priority = engine.analyzer.analysis_priority()

        for card in p.field_chars:
            effects = get_card_effects(card.code)
            # 1) keywords condicionais a DON (blocker/double_attack/rush/banish)
            cond_kw = getattr(card, 'don_cond_keywords', None) or {}
            for kw, req in cond_kw.items():
                falta = req - card.don_attached
                if falta <= 0 or falta > p.don_available:
                    continue
                valor = self._keyword_don_value(kw, card, p, opp, priority)
                score = valor - falta * DON_COST
                if score > 0:
                    acts.append((score, 'attach_don', card, falta, kw))

            # 2) gatilhos condicionais a DON (when_attacking/on_play/etc.)
            for trig, ef in effects.items():
                if not isinstance(ef, dict):
                    continue
                req = ef.get('don_requirement', 0)
                if not req or card.don_attached >= req:
                    continue
                falta = req - card.don_attached
                if falta > p.don_available:
                    continue
                # só vale ligar gatilho de ataque se o personagem vai atacar
                valor = self._trigger_don_value(trig, ef, card, p, opp, priority)
                score = valor - engine.don_opportunity_cost(falta)
                # Fontes repetidas de informacao nao justificam prender um
                # DON em cada copia. A primeira ainda pode usar DON ocioso.
                # Achado real 03/08: resolve "Choose one" quando `steps` vazio.
                step_actions = [s.get('action') for s in resolve_choice_for_scoring(ef, card, p, opp)]
                if step_actions and all(a in ('peek_opp_deck_top', 'look_top_deck')
                                        for a in step_actions):
                    copies = sum(1 for c in p.field_chars if c.code == card.code)
                    score -= max(0, copies - 1) * 30.0
                if score > 0:
                    acts.append((score, 'attach_don', card, falta, trig))

        # 3) DON pra CRUZAR o poder de combate contra um alvo (achado ao
        # vivo 23/07): as categorias 1/2 acima so cobrem "desbloquear
        # habilidade/keyword condicionada a DON" -- nunca "anexar DON num
        # atacante pra vencer o combate", o uso mais basico de DON no jogo.
        # Sem isso, um corpo vanilla (sem habilidade condicionada) nunca
        # virava candidato de attach_don, mesmo quando +1000 decidia um
        # ataque na hora -- o DON escasso sempre ia pro desbloqueio de
        # habilidade por falta de concorrencia (caso real: Baron Tamago &
        # Pekoms 4000 atacou sozinho contra lider 5000 e perdeu, enquanto
        # o unico DON do turno foi pra Pudding SO pra desbloquear o
        # activate_main dela, que nem chegou a ser ativado depois). Mesma
        # regra "empate favorece o atacante": so precisa IGUALAR o alvo,
        # nao superar. Reaproveita score_attack_target (mesma regua da
        # geracao real de 'attack') pra nao inventar valor novo.
        if p.can_attack_this_turn():
            # DON verdadeiramente OCIOSO este turno: sobra DEPOIS de reservar
            # pra defesa (_don_reserve_for_defense -- ja cobre evento
            # [Counter] na mao, que PRECISA de DON!! pra ativar durante o
            # turno do oponente, distinto do stat Counter impresso que so
            # descarta, correcao do usuario 02/08) E nenhuma carta da mao
            # cabe nessa sobra. So essa fatia sobrando e elegivel pra margem
            # de seguranca abaixo -- nunca a reserva de defesa em si. Mesma
            # fonte de _don_reserve_for_defense/_can_play_card ja usada pra
            # gerar 'play' mais acima nesta funcao, nao duplica regra.
            don_reserve = engine._don_reserve_for_defense()
            don_sobra = max(0, p.don_available - don_reserve)
            don_idle = don_sobra > 0 and not any(
                engine._can_play_card(c, don_usable=don_sobra) for c in p.hand)
            attackers = [c for c in p.field_chars if character_can_attack_now(c, p, opp)]
            # Achado real 03/08: mesmo fix do outro ponto de geracao de
            # atacantes -- o lider precisa passar por
            # character_can_attack_now (cannot_attack_self incluso), nao
            # so checar `rested`.
            if character_can_attack_now(p.leader, p, opp):
                attackers.append(p.leader)
            # Taunt (mesmo achado/mesma fonte unica de _generate_and_score_
            # actions -- REGRA_SEM_DUPLICACAO: os dois pontos de geracao de
            # alvo de ataque tem que concordar, senao o orcamento de DON
            # calculado aqui pode mirar uma carta que o outro ponto nunca
            # deixaria atacar de verdade).
            taunt_alvo = active_taunt_character(opp, p)
            for att in attackers:
                atk_now = attack_time_power(att, opp)
                melhor_score, melhor_falta = 0.0, 0
                candidatos_alvo = []
                pode_atacar_leader = (not getattr(att, 'rush_character_only_this_turn', False)
                                      and not p.cannot_attack_leader_this_turn
                                      and taunt_alvo is None)
                # +power_buff nos dois casos: mesmo achado do bloco 434
                # (esse bloco calcula "melhor_falta" de DON pro attach_don,
                # e um buff ja ativo no alvo mudava o gap real).
                if pode_atacar_leader:
                    candidatos_alvo.append(('leader', None, opp.leader.power + opp.leader.power_buff))
                for tgt in opp.rested_chars(att):
                    if taunt_alvo is not None and tgt is not taunt_alvo:
                        continue
                    candidatos_alvo.append(('character', tgt, tgt.power + tgt.power_buff))
                for ttype, tgt, alvo_power in candidatos_alvo:
                    gap = alvo_power - atk_now
                    if gap > 0 and gap <= p.don_available * 1000:
                        falta = -(-gap // 1000)  # ceil division
                        valor = engine.score_attack_target(att, ttype, tgt)
                        if valor <= 0:
                            continue
                        score = valor - falta * DON_COST
                    elif gap == 0 and don_idle:
                        # Empate exato: "empate favorece o atacante" ja
                        # garante a vitoria do combate HOJE, sem anexar
                        # nada -- mas margem ZERO quebra com QUALQUER
                        # Counter do oponente. Sem custo de oportunidade
                        # real (DON idle), reforcar ate 2 DON e estritamente
                        # melhor que deixar parado. Achado real 02/08
                        # (usuario, log Portgas.D.Ace-R x Crocodile-B,
                        # turno 2): Ace(5000) empatava com o lider do
                        # oponente(5000), 3 DON idle (mao so custava >=4)
                        # nunca viravam candidato porque o gap<=0 cortava
                        # tudo antes -- ficaram parados o turno inteiro.
                        # Valor descontado (0.3x, nao o cheio do gap>0):
                        # e seguro opcional, nao o que decide o combate.
                        # Nunca usa a reserva de defesa (don_sobra, nao
                        # p.don_available).
                        falta = min(don_sobra, 2)
                        valor = engine.score_attack_target(att, ttype, tgt)
                        if valor <= 0:
                            continue
                        score = valor * 0.3
                    else:
                        continue
                    if score > melhor_score:
                        melhor_score, melhor_falta = score, falta
                if melhor_falta:
                    acts.append((melhor_score, 'attach_don', att, melhor_falta, 'attack_power'))
        return acts

    def _keyword_don_value(self, kw, card, p, opp, priority) -> float:
        """Valor de ligar uma keyword via DON, conforme o estado."""
        if kw == 'blocker':
            # defensivo: vale muito sob pressão / vida baixa
            base = 100
            if priority == 'DEFENSIVE': base += 80
            if p.life_count() <= 2:     base += 60
            return base
        if kw == 'double_attack':
            # ofensivo: vale se o oponente está em alcance de dano
            base = 80
            if opp.life_count() <= 3: base += 60
            if priority == 'LETHAL':  base += 150
            return base
        if kw == 'rush':
            return 90   # poder atacar já
        if kw == 'banish':
            return 70 + (40 if opp.life_count() <= 3 else 0)
        return 40

    def _trigger_don_value(self, trig, ef, card, p, opp, priority) -> float:
        """Valor de ligar um gatilho condicional a DON, pelo que o efeito faz."""
        # Achado real 03/08: resolve "Choose one" quando `steps` vazio.
        steps = resolve_choice_for_scoring(ef, card, p, opp)
        actions = [s.get('action') for s in steps]
        valor = 0
        # 'rest_opp_character' (nome real da action -- achado 24/07, auditoria
        # do Turn Planner fase A) tinha um typo aqui ('rest_opp', que nunca
        # bate contra nenhuma action real do banco): qualquer carta cujo
        # gatilho condicionado a DON usasse rest_opp_character caia direto no
        # fallback generico de 40, perdendo o bonus de remocao/controle (120)
        # que ko/debuff_power/bounce ja recebem.
        if any(x in ('ko', 'rest_opp_character', 'debuff_power', 'bounce') for x in actions):
            valor = 120   # remoção/controle — vale
            if opp.field_chars: valor += 30
        elif any(x in ('draw', 'add_to_hand', 'look_top_deck') for x in actions):
            valor = 90    # vantagem de carta
        elif actions and all(x == 'peek_opp_deck_top' for x in actions):
            valor = 40    # informacao, nao vantagem de carta
        elif any('power' in str(x) for x in actions):
            valor = 60    # buff de poder
        else:
            valor = 40
        # Piso generico (achado 24/07, mesma auditoria): reusa a MESMA tabela
        # de valor por acao ja calibrada em avaliar_carta (_UNCOVERED_ACTION_VALUE,
        # fase 2 do mapeamento de combos) em vez de deixar qualquer acao fora
        # das 4 categorias acima cair sempre no generico 40 -- ex: add_don,
        # play_from_trash, gain_double_attack, select_grant_* condicionados a
        # DON valiam so 40 antes, mesmo sendo o efeito PRINCIPAL da carta.
        for x in actions:
            piso = DecisionEngine._UNCOVERED_ACTION_VALUE.get(x)
            if piso is not None:
                valor = max(valor, piso)
        # gatilhos de ataque só valem se o personagem pode atacar
        if trig == 'when_attacking' and not character_can_attack_now(card, p, opp):
            valor = 0
        return valor

    def _trigger_risk_penalty(self, opp) -> float:
        """
        Risco de trigger ao atacar (documento pág. 21): desconta, mas não proíbe.
        Mais vidas do oponente = mais chance de trigger. Amarelo = risco maior.
        """
        vidas = opp.life_count()
        if vidas == 0:
            return 0
        base = vidas * 8   # desconto suave por vida (trigger é risco, não veto)
        cor = (getattr(opp.leader, 'color', '') or '').lower()
        if 'yellow' in cor or 'amarelo' in cor:
            base *= 1.8
        return base

    def _evaluate_state(self, p, opp) -> float:
        """
        Avalia quão bom é um estado para 'p' (ao fim de uma sequência simulada).
        Combina: dano causado, vida própria, vantagem de board, recursos.
        Usado pelo Turn Planner para comparar linhas de jogo.
        """
        score = 0.0
        # Dano causado ao oponente (vidas tiradas) — peso alto
        score += p.dmg_dealt * 200
        score -= opp.life_count() * 150          # quanto menos vida o opp tem, melhor
        # Vitoria real na simulacao ja retorna SIMULATED_WIN_SCORE em
        # _simulate_sequence_values. Vida 0 sem dano final conectado ainda
        # e apenas pressao, nao deve receber bonus de vitoria.
        # Board próprio vs oponente
        score += sum(c.board_value() for c in p.field_chars) * 10
        score -= sum(c.board_value() for c in opp.field_chars) * 8
        # Blockers do oponente vivos (ruim para mim)
        score -= len(opp.blockers_active()) * 30
        # Minha vida (defesa)
        score += p.life_count() * 40
        # Recursos: cartas na mão, DON ainda disponível (flexibilidade)
        score += len(p.hand) * 8
        score += p.don_available * 5
        # Chars no trash que podem ser recuperados por cartas na mão (ex: Five Elders)
        for hc in p.hand:
            hc_eff = get_card_effects(hc.code)
            am = hc_eff.get('activate_main', {})
            for step in am.get('steps', []):
                if step.get('action') == 'play_from_trash':
                    ft = (step.get('filter_type') or '').lower()
                    max_rec = step.get('count', 1)
                    targets = sum(1 for c2 in p.trash
                                  if c2.card_type == 'CHARACTER'
                                  and (not ft or ft in (c2.sub_types or '').lower()))
                    score += min(targets, max_rec) * 60
                    break
        return score

    # ── evaluate_state v2: régua ÚNICA (item 1) ───────────────────────────────
    # Curva de vida ÍNGREME (marginal decrescente): 1ª vida vale muito mais que
    # a 5ª. Índice = quantas vidas tenho; valor = soma dos marginais. Mesma
    # filosofia da curva de counter (vida 1 » vida alta).
    _LIFE_MARGINAL = [0, 95, 55, 35, 22, 15, 11, 9, 8, 8, 8]

    def _life_value(self, n: int) -> float:
        m = self._LIFE_MARGINAL
        return float(sum(m[1:min(n, len(m) - 1) + 1]))

    def _turn_profile_for(self, p) -> dict | None:
        """Compatibilidade: delega pro modulo (deck_profile_for), que cacheia
        no proprio GameState -- assim DecisionEngine.avaliar_carta usa o
        MESMO cache sem precisar de acesso a instancia de OPTCGMatch."""
        return deck_profile_for(p)

    def _derived_axes_value(self, p, profile) -> float:
        """
        Contribuição dos eixos DERIVADOS do perfil ao estado de p. Só os eixos
        de AUTO-MOTOR (trash/reanimação/inversão): o valor da disrupção já
        entra pelos termos simétricos (o estado degradado do oponente é contado
        no board/DON dele), então NÃO se adiciona de novo aqui (evita dupla
        contagem). Escalas são PRIORS — a tunagem do item 5 ajusta.
        """
        if not profile:
            return 0.0
        W = getattr(p, 'eval_weights', None) or EVAL_WEIGHTS
        total = 0.0
        trash_n = len(p.trash)
        for ax in profile.get('derived_axes', []):
            kind = ax.get('kind')
            if kind == 'resource_staircase' and str(ax.get('resource', '')).startswith('trash'):
                # progresso SATURANTE até cada degrau: cresce até o threshold,
                # depois não vale mais (anti "mill pra sempre").
                for step in ax.get('steps', []):
                    if step.get('pruned'):
                        continue
                    thr = step.get('threshold') or 1
                    frac = min(1.0, trash_n / thr)
                    total += step.get('impacto', 0) * frac * W['ax_trash']
            elif kind == 'bottleneck':   # reanimação = min(motor, combustível)
                eng = ax.get('engine_card', {})
                ff = ax.get('fuel_filter', {})
                has_engine = any(c.code == eng.get('code')
                                 for c in (list(p.hand) + list(p.deck)))
                ft = (ff.get('filter_type') or '').lower()
                peq = ff.get('power_eq')
                fuel = sum(1 for c in p.trash
                           if c.card_type == 'CHARACTER'
                           and (not ft or ft in (c.sub_types or '').lower())
                           and (peq is None or c.power == peq))
                val = min(eng.get('reanima_ate', 0), fuel) if has_engine else 0
                total += val * W['ax_reanim']
                # win-con JOGÁVEL = "arma carregada": a peça-motor está na MÃO
                # (não só buscável no deck), há fuel real no trash E há progresso
                # de DON NO CAMPO rumo ao custo. DON usado/anexado neste turno
                # volta ativo no refresh, então `don_available` sozinho
                # subvaloriza a linha no fim da simulação. Faz a busca preferir a linha que
                # PRESERVA/desenvolve rumo ao combo em vez de trocá-lo por dano
                # marginal — e, quando o custo já é pagável (ramp satura em 1),
                # valoriza fortemente o estado que dispara o payoff. Genérico:
                # código/custo/fuel vêm do perfil, zero nome de carta. (Achado
                # ao vivo 13/07: OP13-082 ficou na mão a partida inteira, fuel
                # pronto, mas o combo nunca foi valorizado — ver HANDOFF.)
                engine_in_hand = any(c.code == eng.get('code') for c in p.hand)
                custo = eng.get('custo') or 0
                if engine_in_hand and fuel >= 1 and custo:
                    ramp = min(1.0, p.don_on_field() / custo)
                    total += val * ramp * W['wincon_ready']
            elif kind == 'inversion':    # life_lte: achata o pânico
                try:
                    thr = int(str(ax.get('condition', '')).split()[-1])
                except (ValueError, IndexError):
                    thr = 0
                if p.life_count() <= thr:
                    total += ax.get('prior_weight', 0) * W['ax_inversion']
        return total

    def _project_next_turn_best_action(self, actor, other):
        """
        Projeta o estado de `actor` no INICIO do proximo turno dele (DON
        refrescado + rampado via a mesma conta de don_phase(), personagens
        e lider desrestados) e reusa `_generate_and_score_actions` DE
        VERDADE contra esse estado -- a mesma logica calibrada que decide
        o jogo real, nao uma tabela nova.

        FIX 24/07 (achado via audit_replay.py, "DON nao bate" -- Imu
        acumulava +8 DON permanentemente numa partida real): a 1a versao
        MUTAVA `actor` em campo (don_available/don_rested/rested) e
        restaurava com try/finally. Mesmo `actor` sendo sempre uma copia
        descartavel de simulacao (`_evaluate_state_v2` so roda em p2/opp2
        deepcopiados, nunca no estado real), o restore nao provou ser
        seguro na pratica -- confirmado isolando a chamada (audit_replay
        zerava as anomalias com esta funcao desligada). Troca de
        abordagem: DEEPCOPY dedicado (`actor2`) em vez de mutar+desfazer
        -- `actor` original NUNCA e tocado, elimina a classe inteira de
        risco em vez de tentar re-provar que o restore estava certo.
        `other` fica de fora do deepcopy (so leitura nesta chamada).

        Retorna a MELHOR acao ((score, tipo, ...)) que `actor` teria
        disponivel nesse estado projetado, ou None se score<=0 ou se o
        DON nao cresce (nada a projetar). Determinístico: mesmo estado de
        entrada sempre produz a mesma saida (sem Monte Carlo aqui).
        """
        ramp = min(2, max(0, actor.don_deck))
        don_next = actor.don_available + actor.don_rested + ramp
        if don_next <= actor.don_available:
            return None
        actor2 = deepcopy(actor)
        actor2.don_available = don_next
        actor2.don_rested = 0
        for c in actor2.field_chars:
            c.rested = False
        if actor2.leader:
            actor2.leader.rested = False
        engine = DecisionEngine(actor2, other)
        acts = self._generate_and_score_actions(actor2, other, engine)
        return acts[0] if acts and acts[0][0] > 0 else None

    def _next_turn_readiness_bonus(self, p, opp) -> float:
        """
        FASE B do plano do Turn Planner (usuario, 24/07, reforcado no
        mesmo dia: "nao pode ser barato, tem que ser algo com mais
        determinacao... proximo turno vou a X dons, posso fazer isso e
        aquilo, no turno do oponente ele vai a Y dons, pode fazer isso e
        aquilo, pode me atacar aqui e ali"). Primeira versao usava so
        aritmetica de DON contra `avaliar_carta` -- trocada por uma
        analise REAL dos dois lados via `_project_next_turn_best_action`:
        reusa o proprio motor de geracao/pontuacao de acoes sob o DON
        projetado de CADA jogador, sem simular o turno inteiro de verdade
        (sem deepcopy novo, sem Monte Carlo) -- deterministico.

        MEU lado: compara a melhor acao que eu teria HOJE contra a melhor
        que eu teria com o DON do proximo turno -- o GANHO (nao o valor
        absoluto, que ja conta duplicado com avaliar_carta/
        _score_play_action de hoje) vira bonus, saturado.

        Lado do OPONENTE: a melhor acao dele com o DON PROJETADO do turno
        dele -- se for um ATAQUE forte, penaliza (estou deixando ele numa
        posicao perigosa pro turno dele). `wincon_ready` (em
        _derived_axes_value) continua cobrindo separadamente o eixo
        bottleneck do PERFIL do deck (reanimacao em massa tipo Five
        Elders) -- este termo aqui e generico, nao especifico desse
        padrao.
        """
        W = getattr(p, 'eval_weights', None) or EVAL_WEIGHTS
        bonus_self = 0.0
        bonus_threat = 0.0

        melhor_proximo = self._project_next_turn_best_action(p, opp)
        if melhor_proximo is not None:
            acts_agora = self._generate_and_score_actions(p, opp, DecisionEngine(p, opp))
            score_agora = acts_agora[0][0] if acts_agora and acts_agora[0][0] > 0 else 0.0
            ganho = melhor_proximo[0] - score_agora
            if ganho > 0:
                bonus_self += min(60.0, ganho * 0.35)

        ameaca_opp = self._project_next_turn_best_action(opp, p)
        if ameaca_opp is not None and ameaca_opp[1] == 'attack':
            bonus_threat -= min(50.0, ameaca_opp[0] * 0.25)

        return (bonus_self * W['next_turn_readiness_self']
                + bonus_threat * W['next_turn_readiness_opp_threat'])

    def _evaluate_state_v2(self, p, opp) -> float:
        """
        Régua ÚNICA de estado (item 1): termos GENÉRICOS simétricos + eixos
        DERIVADOS do perfil do deck. Substitui o _evaluate_state ad-hoc.
        Recebe (p, opp) do estado a julgar — usa GameAnalyzer local ligado a
        ESSES args (não a self.me/self.opp, que são o estado real).
        """
        an = GameAnalyzer(p, opp)
        # pesos POR JOGADOR (tunagem per-deck) — cai no global se não setado
        W = getattr(p, 'eval_weights', None) or EVAL_WEIGHTS
        score = 0.0

        # dano feito NESTE turno — delta que faz o planner preferir a linha que
        # de fato conecta dano (não só "desenvolve")
        score += p.dmg_dealt * W['dmg']

        # vida (curva íngreme, simétrica)
        score += self._life_value(p.life_count()) * W['life_mult']
        score -= self._life_value(opp.life_count()) * W['life_mult']

        # SOBREVIVENCIA ciente do game_plan (pedido do usuario 14/07): se a
        # win-con do deck e um combo de CUSTO ALTO que ainda NAO da pra
        # disparar, minha propria vida vale mais — perder antes de chegar no
        # combo = derrota certa, entao o planner prefere a linha que preserva
        # vida/defesa a uma agressao arriscada. Generico via compute_game_plan
        # (zero nome de carta). Escala com a distancia ate poder disparar
        # (pending) e SATURA em 0 quando ja da (ai a "arma carregada"/dano
        # assumem) ou quando o deck nao tem combo caro (don_target baixo/None).
        # NAO impede racar: e premio sobre a MINHA vida, atacar o opp continua
        # valendo pelos termos de dano/vida do oponente.
        # So dispara sob RISCO REAL de morrer (vida <= 3): panico cresce quanto
        # mais baixa a vida. Vida alta = sem urgencia, NAO durdla (senao vira
        # passividade contra controle, que quer exatamente que voce durdle —
        # medido 14/07: premio ligado a vida cheia feria Krieg 0.53->0.27).
        try:
            _plano_surv = compute_game_plan(p)
            _dt = _plano_surv.get('don_target')
            if _dt and _dt >= 6:
                # So vale sobreviver pro combo se o OPONENTE me RACA (aggro): vs
                # CONTROLE, durdlar e exatamente o que ele quer -- ali eu preciso
                # PRESSIONAR. O perfil do opp decide (plano item 2 ponto 5: o
                # perfil do oponente muda o valor do MEU estado). Medido 14/07:
                # premio incondicional feria Krieg (controle) 0.53->0.27; gated
                # pelo arquetipo do opp, so liga vs Kid/aggro.
                _opp_prof = self._turn_profile_for(opp)
                _opp_ctrl = (_opp_prof or {}).get('archetype', {}).get('dominante') == 'Controle'
                if _opp_prof and not _opp_ctrl:
                    _pending = 1.0 - min(1.0, p.don_on_field() / _dt)
                    _panic = max(0, 4 - p.life_count())   # 0 em vida>=4, ate 3 em vida 1
                    if _pending > 0 and _panic > 0:
                        score += _panic * W['survival_premium'] * _pending
        except Exception:
            pass

        # board (reusa char_value_score — já vê blocker/rush/imunidade/efeito)
        score += sum(an.char_value_score(c) for c in p.field_chars) * W['board_mine']
        score -= sum(an.char_value_score(c) for c in opp.field_chars) * W['board_opp']

        # blockers do oponente vivos travam meu ataque
        score -= len(opp.blockers_active()) * W['opp_blocker']

        # ameaça de virada por reanimação em massa do trash dele (achado
        # 07/07, PREVENT_COMBO) -- penaliza pelo threat_power ESTIMADO no
        # estado avaliado; se a linha reduziu o combustível qualificado
        # (ex: jogou algo que suja o trash dele) ou gastou o custo da
        # habilidade, recomputa menor aqui e a busca já prefere essa linha.
        score -= an.opp_combo_threat()['threat_power'] * W['opp_combo_threat']

        # mão: retorno decrescente (as primeiras cartas valem mais)
        nh = len(p.hand)
        score += min(nh, 5) * W['hand_first'] + max(0, nh - 5) * W['hand_extra']
        # poder de counter na mão = vida futura
        score += p.counter_in_hand() / 1000 * W['counter_hand']

        # DON no campo (ramp = chegar na bomba) — leve. Escala pela curva do
        # PROPRIO deck quando USE_DON_FIELD_CURVE_SCALE ligado (bloco 530,
        # calibragem dinamica analitica -- ver don_field_curve_scale).
        don_scale = an.don_field_curve_scale() if USE_DON_FIELD_CURVE_SCALE else 1.0
        score += p.don_on_field() * W['don_field'] * don_scale

        # cobertura defensiva: counter na mão vs ataques que o opp faz no
        # próximo turno (líder + chars ativos). min = ter counter além do
        # necessário satura (não vale acumular counter infinito).
        opp_atk = 1 + sum(1 for c in opp.field_chars if not c.rested)
        cobertura = min(p.counter_in_hand(), opp_atk * 2000)
        score += cobertura / 1000 * W['coverage']

        # eixos derivados do perfil (auto-motor: trash/reanimação/inversão)
        score += self._derived_axes_value(p, self._turn_profile_for(p))

        # FASE B do Turn Planner (24/07): "quase la" pra proxima jogada
        # forte, generico (nao so o eixo bottleneck do perfil do deck).
        score += self._next_turn_readiness_bonus(p, opp)

        # alinhamento com o plano do PROPRIO lider (14/08) -- generaliza
        # wincon_ready pra QUALQUER lider com [Activate: Main].
        score += an.leader_plan_alignment() * W['leader_plan_alignment']

        return score

    def _apply_action(self, action, p, opp, ee, engine, verbose=False):
        """
        Executa UMA ação no estado dado (real ou cópia). Retorna True se venceu.
        Reúso entre o jogo real e a simulação do planner.

        Invalida o cache de _lethal_search (fase D, 24/07) ANTES de mutar
        o estado: `engine` (e o GameAnalyzer que ele carrega) é
        frequentemente reusado por VÁRIAS chamadas de
        _generate_and_score_actions dentro do MESMO loop de simulação
        (main_phase/_play_turn_greedy/_simulate_sequence_once), cada uma
        separada por um _apply_action que muda o board de verdade -- sem
        isto, a 2a+ chamada no mesmo loop leria um resultado de lethal
        JÁ DESATUALIZADO (cacheado antes da mutação). `_apply_action` é o
        ÚNICO ponto que executa ações de verdade (real e simulado), por
        isso é o lugar certo pra invalidar.
        """
        if engine is not None and getattr(engine, 'analyzer', None) is not None:
            engine.analyzer._lethal_search_cache = None
        score, kind, obj, ttype, tgt = action

        if kind == 'play':
            self._play_card(obj, p, opp, ee, verbose=verbose)

        elif kind == 'activate':
            src = obj
            am = get_card_effects(src.code).get('activate_main', {})
            src._am_used_turn = p.turn
            self._log_decision(p, src, 'activate_main', 'activate', 'ação no planner')
            logs = ee.execute(src, 'activate_main')
            if verbose:
                print(f'    ⚙ ativou [Activate:Main] de {src.name[:22]}')
                for log in logs:
                    if log:
                        print(f'      ↳ {log}')
            if any(logs):
                desc = ' | '.join(l for l in logs if l)
                self._log_event(p, 'activate_main', card=src, description=desc)

        elif kind == 'attach_don':
            card, falta, what = obj, ttype, tgt
            anexar = min(falta, p.don_available)
            if anexar > 0:
                card.don_attached += anexar
                p.don_available -= anexar
                ee._dispatch_don_given(card)
                if verbose:
                    print(f'    ⚡ anexou {anexar} DON em {card.name[:20]} para ligar [{what}]')

        elif kind == 'attack':
            attacker = obj
            if attacker.rested:
                return False
            attached = self._attach_don_for_attack(attacker, ttype, tgt, p, opp, engine, verbose)
            if verbose:
                tgt_name = 'Leader' if ttype == 'leader' else (tgt.name[:20] if tgt else '?')
                print(f'    {attacker.name[:20]} ({attack_time_power(attacker, opp)}pwr) ataca {tgt_name}')
            if self._execute_attack(attacker, ttype, tgt, p, opp, engine, verbose=verbose,
                                    attached_don=attached):
                return True
        return False

    def _simulate_sequence(self, p, opp, first_action, max_steps=8, amostras=None):
        """
        Simula uma LINHA DE JOGO começando por first_action, numa CÓPIA do estado.
        Após a primeira ação, segue gulosamente (melhor ação a cada passo) até o
        fim do turno. Retorna o valor do estado final (para comparar linhas).

        A mão e vida REAIS de `opp` NUNCA são lidas dentro da simulação --
        são substituídas pelas amostras em `amostras` (lista de
        (hand_sample, life_sample), uma por rodada Monte Carlo -- gerada
        UMA VEZ por turno em main_phase e reusada entre todas as TOP_K
        candidatas, não regerada aqui). O valor final é a MÉDIA das N
        rodadas. Isso corrige a "trapaça" original (a simulação via a mão
        exata do oponente real para decidir blocker/counter) sem mudar
        nada na lógica de should_use_blocker/should_use_counter, que
        continuam idênticas — só passam a operar sobre a mão fictícia.

        Se `amostras` for None (ex: chamada legada sem Monte Carlo
        disponível), cai numa única rodada contra o estado real de opp.
        """
        valores = self._simulate_sequence_values(p, opp, first_action, max_steps, amostras)
        return sum(valores) / len(valores) if valores else -1e9

    def _simulate_sequence_values(self, p, opp, first_action, max_steps=8, amostras=None,
                                   extra_own_turn_search=False):
        """Retorna os valores por amostra Monte Carlo para auditoria do planner.

        `extra_own_turn_search`: lookahead de 2 turnos meus (ver
        _simulate_sequence_once) -- SO deve ser True no caminho AO VIVO
        (sim_bridge.choose_action), que tem folga real de orcamento (medido
        24/07: 0.11s de 4s num board 5v5). O caminho OFFLINE (main_phase,
        usado em self-play/replay/calibracao) ja tem explosao O(board²)
        PRE-EXISTENTE (medido: ate 13.8s por turno late-game) -- adicionar
        mais um turno de busca ali pioraria isso sem necessidade, decisao
        do usuario 24/07.
        """
        old_suppress = self._suppress_replay_log
        self._suppress_replay_log = True
        try:
            if not amostras:
                return [self._simulate_sequence_once(p, opp, first_action, max_steps, amostra=None,
                                                      extra_own_turn_search=extra_own_turn_search)]

            return [
                self._simulate_sequence_once(p, opp, first_action, max_steps, amostra=amostra,
                                             extra_own_turn_search=extra_own_turn_search)
                for amostra in amostras
            ]
        finally:
            self._suppress_replay_log = old_suppress

    def _simulate_sequence_once(self, p, opp, first_action, max_steps=8, amostra=None,
                                 extra_own_turn_search=False):
        """
        Uma única rodada de simulação (ver _simulate_sequence para a versão
        agregada com Monte Carlo). `amostra` é uma tupla (hand_sample,
        life_sample) já sorteada -- esta função só aplica, não sorteia.
        Separada em método próprio para poder ser chamada N vezes com
        amostras diferentes sem duplicar a lógica de remap/apply/loop.
        """
        from copy import deepcopy
        # Optimizacao de deepcopy: zeramos os decks antes de clonar os estados
        # e os restauramos como copias rasas depois. Isso evita deepcopiar ~80+
        # Cards de uma vez (o gargalo dominante -- ~0.7ms dos ~1.2ms totais).
        #
        # Para opp.deck: seguro porque o oponente nao age durante a simulacao
        # do turno ativo, entao nenhuma carta sai do deck dele.
        # Para p.deck: usamos _SimDeck (lazy copy-on-pop) -- o wrapper faz
        # deepcopy SOMENTE das cartas efetivamente sacadas durante a simulacao
        # (normalmente 0-2 por chamada), nao de todo o deck de uma vez.
        # Correctness garantido: a carta original em p.deck nunca e mutada
        # (a mutacao ocorre no clone gerado pelo pop(), nao no objeto original).
        _p_deck = p.deck
        p.deck = []
        _opp_deck = opp.deck
        opp.deck = []
        p2 = deepcopy(p)
        opp2 = deepcopy(opp)
        p.deck = _p_deck
        opp.deck = _opp_deck
        p2.deck = _SimDeck(_p_deck)   # lazy copy-on-pop (ver _SimDeck no topo)
        # _SimDeck (nao list() rasa) -- achado real 03/08, causa raiz #3 do
        # mesmo bug de conservacao de DON (blocos 374/377/410/420/422/423,
        # ver bloco 425): o comentario antigo aqui ("opp nao age durante a
        # simulacao do turno ativo, entao nenhuma carta sai do deck dele")
        # e FALSO sempre que USE_OPPONENT_RESPONSE_SEARCH=True (default) --
        # `_play_turn_greedy(opp2, p2)`, chamado logo abaixo neste mesmo
        # metodo, roda o TURNO INTEIRO de resposta do oponente (refresh_
        # phase/draw_phase/don_phase/main_phase greedy), incluindo
        # `opp2.deck.pop()` de verdade no draw_phase. Com `list(_opp_deck)`
        # (lista rasa comum), esse `.pop()` retornava a MESMA referencia de
        # Card do deck REAL do oponente, sem NENHUMA protecao de deepcopy
        # -- qualquer mutacao durante o turno guloso simulado (jogar carta,
        # anexar DON, etc.) vazava permanentemente pro deck real. Mesmo
        # padrao ja resolvido pra p2.deck (_SimDeck), so faltava aplicar
        # aqui tambem.
        opp2.deck = _SimDeck(_opp_deck)

        if amostra is not None:
            # Substitui mão e vida REAIS de opp2 pela amostra Monte Carlo
            # ANTES de qualquer ação ser aplicada -- nenhum código de
            # combate (should_use_blocker, should_use_counter, trigger ao
            # tomar dano) vê a mão/vida real do oponente a partir daqui.
            # As instâncias de Card na amostra são reusadas (mesmo objeto)
            # entre as TOP_K chamadas que recebem a mesma `amostra` desta
            # lista -- isso é seguro porque cada chamada já faz seu próprio
            # deepcopy de opp2 seria necessário SE a amostra fosse mutada,
            # mas should_use_blocker/should_use_counter apenas leem
            # power/counter das cartas, nunca mutam o objeto Card em si
            # (mutam GameState.hand/life, que já são listas novas aqui).
            hand_sample, life_sample = amostra
            opp2.hand = list(hand_sample)
            opp2.life = list(life_sample)

        eng2 = DecisionEngine(p2, opp2)
        ee2 = EffectExecutor(p2, opp2)

        # Mapeia a primeira ação para os objetos da cópia (por índice/identidade)
        first2 = self._remap_action(first_action, p, p2, opp, opp2)
        if first2 is None:
            return -1e9
        won = self._apply_action(first2, p2, opp2, ee2, eng2, verbose=False)
        if won:
            return SIMULATED_WIN_SCORE   # essa linha vence

        # Continua gulosamente até o fim do turno
        # activate_main agora compete como ação no _generate_and_score_actions,
        # então não precisa mais de chamada separada aqui.
        for _ in range(max_steps):
            acts = self._generate_and_score_actions(p2, opp2, eng2)
            if not acts or acts[0][0] < 0:
                break
            if self._apply_action(acts[0], p2, opp2, ee2, eng2, verbose=False):
                return SIMULATED_WIN_SCORE

        # ITEM 3 do plano (busca prof.2): simula o TURNO INTEIRO de RESPOSTA
        # do oponente (proprio engine dele, guloso — ver _play_turn_greedy)
        # ANTES de avaliar. Sem isto a avaliacao so via a foto no fim do MEU
        # turno, cega pra "ataquei seco -> ele countera barato e devolve" vs
        # "anexei DON -> passa/drena counter" -- a passividade sistemica que
        # o marco-zero mediu (don_por_atk baixo). `amostra` (mao/vida
        # ficticia de opp2, ja aplicada acima) e a mesma usada na resposta —
        # ficcao interna consistente, nao resorteia.
        if USE_OPPONENT_RESPONSE_SEARCH:
            if self._play_turn_greedy(opp2, p2):
                return -SIMULATED_WIN_SCORE   # a resposta dele me mata -> linha ruim

        # LOOKAHEAD de 2 turnos meus, SO caminho ao vivo (usuario 24/07,
        # decisao apos profiling: offline ja tem explosao O(board²)
        # pre-existente, ao vivo tem folga real). Depois da resposta do
        # oponente, simula meu PROPRIO proximo turno inteiro, guloso (mesmo
        # _play_turn_greedy ja usado pra resposta -- sem Monte Carlo, sem
        # aninhar main_phase). Se essa linha me leva a vencer dentro do
        # meu proximo turno, essa e uma prova mais forte que os termos
        # estaticos de avaliacao (_next_turn_readiness_bonus so projeta
        # DON/melhor acao, nunca joga o turno de verdade).
        if extra_own_turn_search:
            if self._play_turn_greedy(p2, opp2):
                return SIMULATED_WIN_SCORE   # meu proprio proximo turno fecha o jogo -> linha otima

        # config de avaliação POR JOGADOR (p é quem age): permite Imu usar v2 e
        # o oponente v1 na mesma partida — como o sistema per-deck vai operar
        # (cada deck tem sua régua/pesos). None = cai no global USE_EVAL_V2.
        use_v2 = getattr(p, 'use_eval_v2', None)
        if use_v2 is None:
            use_v2 = USE_EVAL_V2
        if use_v2:
            return self._evaluate_state_v2(p2, opp2)
        return self._evaluate_state(p2, opp2)

    def _remap_action(self, action, p, p2, opp, opp2):
        """Remapeia uma ação do estado real para os objetos da cópia (por índice)."""
        score, kind, obj, ttype, tgt = action
        try:
            if kind == 'activate':
                # Remapeia source para o objeto equivalente na cópia
                if obj is p.leader:
                    return (score, kind, p2.leader, None, None)
                if obj is p.field_stage:
                    return (score, kind, p2.field_stage, None, None)
                if obj in p.field_chars:
                    return (score, kind, p2.field_chars[p.field_chars.index(obj)], None, None)
                return None
            if kind == 'play':
                idx = p.hand.index(obj)
                return (score, kind, p2.hand[idx], None, None)
            if kind == 'attach_don':
                idx = p.field_chars.index(obj) if obj in p.field_chars else None
                obj2 = p2.field_chars[idx] if idx is not None else (p2.leader if obj is p.leader else None)
                return (score, kind, obj2, ttype, tgt)
            if kind == 'attack':
                if obj is p.leader:
                    att2 = p2.leader
                else:
                    att2 = p2.field_chars[p.field_chars.index(obj)]
                if ttype == 'character' and tgt in opp.field_chars:
                    tgt2 = opp2.field_chars[opp.field_chars.index(tgt)]
                else:
                    tgt2 = None
                return (score, kind, att2, ttype, tgt2)
        except (ValueError, IndexError):
            return None
        return None

    def main_phase(self, p: GameState, opp: GameState, verbose: bool = False) -> bool:
        """
        Fase principal = LOOP DE PONTUAÇÃO DE JOGADAS (documento pág. 9).
        A cada passo: gera todas as ações possíveis, pontua, executa a melhor,
        reavalia o estado, repete. A ordem (jogar antes/depois de atacar) emerge
        das pontuações: cartas que habilitam ataque saem antes; desenvolvimento
        sai depois. Para quando nenhuma ação tem score acima do limiar.
        """
        engine = DecisionEngine(p, opp)
        ee     = EffectExecutor(p, opp)
        ee.apply_your_turn_buffs()

        if verbose:
            print('  -- Turno (Turn Planner: simula sequências) --')

        MAX_ACOES = 30
        # simula so as K acoes mais promissoras (custo controlado). Com a busca
        # de resposta do oponente (item 3) LIGADA, cada simulacao agora inclui
        # o turno INTEIRO de resposta dele -- medido 14/07: board cheio late-
        # game fez 1 partida ir de 5s pra 147s com K=6/S=6 (explosao O(board²)
        # por passo, multiplicada pelos dois turnos). Corta pro K≈3/S≈3 que o
        # PROPRIO plano ja recomendava ("top-K≈3 linhas minhas... S≈3
        # amostras") quando a busca de resposta esta ativa; K=6/S=6 (validado
        # em 13/07 sem a resposta) continua valendo com a flag desligada.
        TOP_K = 3 if USE_OPPONENT_RESPONSE_SEARCH else 6
        n = 0

        while n < MAX_ACOES:
            n += 1
            actions = self._generate_and_score_actions(p, opp, engine)
            if not actions or actions[0][0] < 0:
                break
            priority = engine.analyzer.analysis_priority()

            # Modo experimental "SO camada barata decide" (bloco 520,
            # ablacao pedida pelo usuario apos o achado do bloco 519: "a
            # gente pode... fazer so a simulacao barata milhares de vezes
            # ai comparamos bot so com heuristica x bot com heuristica e
            # simulacao x bot so com simulacao"). Aplica DIRETO a acao de
            # maior `cheap_value`, sem passar pela busca cara/heuristica
            # de verdade -- mede se o sinal barato, sozinho, basta.
            # OFF por padrao, so pra medicao -- nao e um modo de producao.
            if CHEAP_LAYER_DECIDES_ALONE:
                cv_alone = self._compute_cheap_values(p, opp, actions, n_samples=CHEAP_LAYER_SAMPLES)
                melhor_acao = (max((a for a in actions if id(a) in cv_alone), key=lambda a: cv_alone[id(a)])
                              if cv_alone else actions[0])
                if self._is_unsafe_zero_life_leader_attack(melhor_acao, p, opp, engine):
                    break
                self._log_turn_planner_decision(
                    p, opp, engine, priority, actions, [melhor_acao],
                    melhor_acao, cv_alone.get(id(melhor_acao)), {}, cheap_values=cv_alone
                )
                if self._apply_action(melhor_acao, p, opp, ee, engine, verbose=verbose):
                    return True
                continue

            # Modo "GATE" (bloco 522, pedido direto do usuario: "e so
            # fazer a simulacao... e depois jogar na heuristica ou nao
            # dependendo do resultado" -- simplifica o desenho anterior.
            # Achado do bloco 521/522: SEMPRE alargar o shortlist pra
            # busca cara (a fase 1 original) sobrecarrega o orcamento
            # apertado dela quando o sinal barato fica mais confiante
            # (mais candidatas dividindo o mesmo teto de amostras) --
            # regride em vez de ajudar. Em vez disso: roda a simulacao
            # barata, e SO pula a busca cara quando o resultado ja e
            # CONFIANTE (gap grande entre a 1a e a 2a candidata) --
            # senao, cai no fluxo de sempre (score estatico + busca
            # cara), SEM alargar. OFF por padrao ate validar.
            if USE_CHEAP_LAYER_GATE:
                cv_gate = self._compute_cheap_values(p, opp, actions, n_samples=CHEAP_LAYER_SAMPLES)
                ordenadas_gate = sorted(
                    (a for a in actions if id(a) in cv_gate),
                    key=lambda a: cv_gate[id(a)], reverse=True)
                if ordenadas_gate:
                    top = ordenadas_gate[0]
                    vice_valor = (cv_gate[id(ordenadas_gate[1])]
                                 if len(ordenadas_gate) > 1 else float('-inf'))
                    gap = cv_gate[id(top)] - vice_valor
                    if (gap >= CHEAP_LAYER_GATE_THRESHOLD
                            and not self._is_unsafe_zero_life_leader_attack(top, p, opp, engine)):
                        self._log_turn_planner_decision(
                            p, opp, engine, priority, actions, [top],
                            top, cv_gate.get(id(top)), {}, cheap_values=cv_gate
                        )
                        if self._apply_action(top, p, opp, ee, engine, verbose=verbose):
                            return True
                        continue
                # nao confiante (ou sem candidatas com cheap_value) --
                # cai no fluxo normal abaixo, SEM alargamento (cheap_
                # values forcado a None so nesta iteracao, pra nao
                # empilhar o gate com a fase 1 -- mecanismos separados).

            # GamePlan fase 2b (auditor 10/07, flag D_win_con_parado): quando a
            # acao do topo e JOGAR a carta-bomba do plano e o DON ja paga, executa
            # DIRETO, sem passar pelo Monte Carlo. O valor da bomba se realiza no
            # turno SEGUINTE (ex: Five Elders reanima via activate_main no
            # proximo turno) — a simulacao de fim de turno nao enxerga isso e
            # escolhia linhas que gastavam o DON em outra coisa (Empty Throne
            # 3 DON primeiro), deixando a bomba impagavel de novo, todo turno.
            # O caminho AO VIVO (choose_action) ja pega o topo da lista direto —
            # este bypass so alinha o simulador interno ao mesmo comportamento.
            # Nao dispara em LETHAL: fechar a partida vem antes de desenvolver.
            if actions[0][1] == 'play' and priority != 'LETHAL':
                _top_card = actions[0][2]
                _plano = compute_game_plan(p)
                if (_plano['win_con_code'] and _top_card.code == _plano['win_con_code']
                        and _plano['don_target']
                        and p.don_available >= _plano['don_target']):
                    if self._apply_action(actions[0], p, opp, ee, engine, verbose=verbose):
                        return True
                    continue

            # TURN PLANNER: para as TOP_K ações candidatas, simula a linha de jogo
            # resultante e escolhe a que leva ao MELHOR estado de fim de turno.
            # (Em vez de escolher gulosamente a de maior score imediato.)
            # Selecao/busca unificadas (26/07, pedido do usuario: "tem que
            # ser o mesmo nos dois") -- MESMAS funcoes usadas pelo caminho
            # AO VIVO (sim_bridge.choose_action), so o TOP_K/piso/teto de
            # amostras (orcamento de tempo) diferem por chamador.
            # Fase 1 da "calibragem dinamica" (bloco 508/509): opt-in via
            # USE_CHEAP_LAYER_SHORTLIST (desligado por padrao) -- calcula
            # o sinal barato 1x por decisao e passa pra alargar o corte
            # do shortlist. Log de auditoria recebe os mesmos valores
            # (audit_cheap_layer.py le o decision_log depois).
            #
            # n_samples=CHEAP_LAYER_SAMPLES passado EXPLICITO (nao confiar
            # no default do parametro): default de funcao e resolvido 1x
            # no IMPORT do modulo -- reatribuir `de.CHEAP_LAYER_SAMPLES`
            # em runtime (ex: script de calibracao comparando escalas)
            # NAO muda esse default ja fixado, so passar como argumento
            # explicito le o valor atual de verdade. Achado real 13/08
            # (bloco 515/516): uma comparacao 40-vs-3000 amostras deu
            # margem EXATAMENTE zero em TODOS os matchups -- sinal
            # classico desse bug (as duas condicoes rodaram com o mesmo
            # valor de fato).
            cheap_values = (self._compute_cheap_values(p, opp, actions, n_samples=CHEAP_LAYER_SAMPLES)
                            if USE_CHEAP_LAYER_SHORTLIST and not USE_CHEAP_LAYER_GATE else None)
            candidatas = self._select_search_candidates(
                actions, TOP_K, priority, cheap_values=cheap_values)
            if len(candidatas) == 1:
                melhor_acao = candidatas[0]
                if self._is_unsafe_zero_life_leader_attack(melhor_acao, p, opp, engine):
                    break
                self._log_turn_planner_decision(
                    p, opp, engine, priority, actions, candidatas,
                    melhor_acao, None, {}, cheap_values=cheap_values
                )
                if self._apply_action(melhor_acao, p, opp, ee, engine, verbose=verbose):
                    return True
                continue

            model = self.model_for_a if p is self.state_a else self.model_for_b
            # mesmo corte de custo do TOP_K acima (ver comentario la): S≈3 com
            # a busca de resposta ligada, S=6 (ja validado) sem ela.
            #
            # Amostragem ADAPTATIVA (piso/teto, ver OFFLINE_MC_SAMPLES_MIN/
            # MAX/BATCH acima) quando USE_OPPONENT_RESPONSE_SEARCH=True --
            # mesmo mecanismo de early-stop estatistico (CRN pareado) ja
            # calibrado no caminho ao vivo, so com piso/teto menores pro
            # regime de THROUGHPUT do offline (ate 30 sub-decisoes/turno,
            # muitos turnos, muitas partidas de calibracao). Achado 10/08
            # (pedido do usuario, custo medido em +7.2% de tempo total pra
            # ganhar precisao nas decisoes ambiguas -- ver comentario da
            # constante). Flag desligada continua no N FIXO de sempre
            # (PLANNER_MC_SAMPLES=6, nao investigado nesta sessao).
            if USE_DEEP_REAL_SEARCH:
                # Bloco 524: piso/teto bem maiores, MESMA busca real (nao
                # e um motor novo) -- so pra medicao offline, ver comentario
                # da constante.
                samples_min = DEEP_REAL_SEARCH_SAMPLES_MIN
                samples_max = DEEP_REAL_SEARCH_SAMPLES_MAX
                batch_size = DEEP_REAL_SEARCH_SAMPLES_BATCH
            elif USE_OPPONENT_RESPONSE_SEARCH:
                samples_min = OFFLINE_MC_SAMPLES_MIN
                samples_max = OFFLINE_MC_SAMPLES_MAX
                batch_size = OFFLINE_MC_SAMPLES_BATCH
            else:
                samples_min = samples_max = batch_size = PLANNER_MC_SAMPLES
            # rng=random (modulo, nao random.Random() novo) -- achado 26/07:
            # random.Random() semeia do SO/relogio, ignora random.seed() e
            # tornava main_phase() nao-reprodutivel mesmo com seed fixo
            # (ver opponent_model.py.sample() docstring).
            melhor_acao, melhor_valor, _records, _n_amostras, sim_values = (
                self._select_action_via_search(
                    p, opp, engine, candidatas, model,
                    max_steps=8, extra_own_turn_search=False,
                    samples_min=samples_min, samples_max=samples_max,
                    batch_size=batch_size, rng=random))

            if melhor_acao is None:
                break

            # Executa a primeira ação da melhor linha no estado REAL
            self._log_turn_planner_decision(
                p, opp, engine, priority, actions, candidatas,
                melhor_acao, sim_values.get(id(melhor_acao), melhor_valor), sim_values,
                cheap_values=cheap_values
            )
            if self._apply_action(melhor_acao, p, opp, ee, engine, verbose=verbose):
                return True

        for c in p.field_chars:
            c.just_played = False
        return False

    def _don_livre_for_plan(self, p, opp, engine) -> int:
        """
        DON ocioso do plano do turno: o que sobra do don_available depois
        (a) das jogadas/ativacoes que o Turn Planner ainda pretende fazer
        (acoes 'play'/'activate' com score >= 0, na ordem de preferencia,
        enquanto o DON alcanca) e (b) da reserva de defesa. So esse sobra
        vira margem de counter num ataque -- DON comprometido com o plano
        nunca e gasto a mais numa unica margem.

        'activate' entrou 14/07 (achado ao vivo, log 13.08.24): so 'play'
        reservava DON -- o Activate:Main da PROPRIA win-con ja em campo (ex:
        Five Elders, rest_don:1 pra reanimar 5 do trash) nunca tinha DON
        protegido, e o ataque seguinte (margem de counter) consumia o DON
        que faltava pra ativar o combo no MESMO turno. Mesmo padrao de
        reserva, so estende a cobertura pro tipo de acao que faltava.

        Fonte unica: antes so existia essa conta no caminho AO VIVO
        (sim_bridge.don_for_attack) -- o simulador interno
        (_attach_don_for_attack) chamava don_needed_for_attack sem
        don_livre (default None -> usa TODO o don_available como se
        estivesse ocioso). Achado real 10/07 (simulacao Teach vs Imu,
        winrate 6.7%): o Turn Planner anexava 9 DON numa unica declaracao
        de ataque (muito alem do necessario pra passar, sem ganho nenhum
        alem de 1 vida), esvaziando o DON que sobraria pra jogar Catarina
        Devon e outras cartas na mao no MESMO turno -- exatamente o padrao
        "desce carta barata, carta de peso fica parada" que o usuario
        reportou, so que a causa raiz era DON sendo desperdicado no
        ataque, nao um viés de avaliar_carta.

        FIX 19/07 (FIX_LETHAL_DON_ALLOCATION, ver diag_lethal_don_alloc.py):
        se o lethal esta GARANTIDO neste turno (can_lethal_this_turn no
        pior caso), nao reserva NADA pro "resto do plano"/defesa -- fechar
        o jogo agora domina qualquer jogada futura ou ataque do proximo
        turno do oponente, que so existiria se eu NAO tivesse fechado.
        Sem isto, 82% dos momentos de lethal certificado (medido em 3
        partidas reais) tinham a alocacao real de DON MENOR que a
        certificada, arriscando o ataque ser bloqueado/counterado por
        falta da margem que a certificacao assumia disponivel.
        """
        if FIX_LETHAL_DON_ALLOCATION and engine.analyzer.can_lethal_this_turn():
            return p.don_available

        planejado = 0
        try:
            acts = self._generate_and_score_actions(p, opp, engine)
            for a in acts:
                if a[0] < 0:
                    break
                if a[1] == 'play':
                    custo = effective_hand_play_cost(p, a[2], opp)
                    if planejado + custo <= p.don_available:
                        planejado += custo
                elif a[1] == 'activate':
                    am = get_card_effects(a[2].code).get('activate_main', {})
                    custo = sum(c.get('count', 0) for c in am.get('costs', [])
                               if c.get('type') == 'rest_don')
                    if custo and planejado + custo <= p.don_available:
                        planejado += custo
            reserva = engine._don_reserve_for_defense()
        except Exception:
            planejado, reserva = 0, 0
        return max(0, p.don_available - planejado - reserva)

    def _attach_don_for_attack(self, attacker, ttype, tgt, p, opp, engine, verbose):
        """Anexa DON a este ataque, se ajudar a passar a defesa."""
        don_livre = self._don_livre_for_plan(p, opp, engine)
        need = don_needed_for_attack(attacker, ttype, tgt, p, opp, engine, don_livre=don_livre)
        if need > 0:
            attacker.don_attached += need
            p.don_available -= need
            EffectExecutor(p, opp)._dispatch_don_given(attacker)
            if verbose:
                print(f'    anexou {need} DON em {attacker.name[:20]}')
        return need

    def _play_card(self, card: Card, p: GameState, opp: GameState,
                   ee: EffectExecutor, verbose: bool = False):
        """
        Joga uma carta.
        Efeitos executados APENAS via EffectExecutor — sem lógica duplicada.
        Com verbose=True, narra a jogada (para o replay). Silencioso por padrão
        (simulação em massa não passa verbose).
        """
        play_cost = effective_hand_play_cost(p, card, opp)
        # "The next time you play...": consome apenas regras cujo filtro
        # casa com ESTA carta. Jogar uma carta inelegivel nao gasta o buff.
        consume_play_cost_reductions(p, card)
        remove_by_identity(p.hand, card)
        p.don_rested  += play_cost
        p.don_available -= play_cost
        # Replay event: carta jogada
        self._log_event(p, 'play_card', card=card,
                        description=f'Jogou {card.name} (custo {play_cost} DON)',
                        phase='main')

        if verbose:
            don_txt = f'gastou {play_cost} DON' if play_cost > 0 else 'grátis'
            print(f'  > {don_txt} -> Joga: {card.name[:30]} '
                  f'({card.effective_power(True)}pwr) [{card.card_type}]')
            # Texto do efeito da carta (cinza) — para auditoria sem decorar
            txt = (card.card_text or '').strip()
            if txt:
                # primeira frase/linha do efeito, até ~90 chars
                short = txt.replace('\n', ' ')[:90]
                print(f'    \033[90mefeito: {short}{"..." if len(txt) > 90 else ""}\033[0m')

        if card.card_type == 'CHARACTER':
            if len(p.field_chars) >= 5:
                worst = min(p.field_chars, key=lambda c: c.board_value())
                remove_character_from_field(p, worst, 'trash')
                if verbose:
                    print(f'    campo cheio -> descartou {worst.name[:25]}')
            card.rested = False
            p.field_chars.append(card)
            apply_conditional_keyword_passives(p, opp)
            card.just_played = not (card.has_rush or card.rush_this_turn or card.is_rush_character())
            card.rush_character_only_this_turn = card.is_rush_character() and not card.is_rush()
            ee._dispatch_char_played(card)

        elif card.card_type == 'EVENT':
            p.trash.append(card)
            p.events_activated_costs_this_turn.append(card.cost)
            ee._dispatch_event_activated()

        elif card.card_type == 'STAGE':
            if p.field_stage:
                p.trash.append(p.field_stage)
            p.field_stage = card

        # Executa efeito ao jogar a carta via EffectExecutor (único ponto).
        # Eventos e personagens podem ter o efeito em 'on_play' OU em 'main'
        # (cartas cujo texto começa com [Main]). Ao jogar, ambos disparam.
        logs = []
        logs += ee.execute(card, 'on_play')
        logs += ee.execute(card, 'main')
        if verbose:
            for log in logs:
                if log:
                    print(f'    ↳ [{card.name[:20]}] {log}')
        # Replay: log effects that fired
        effect_descs = [l for l in logs if l]
        if effect_descs:
            self._log_event(p, 'effect', card=card,
                            description='; '.join(effect_descs[:3]),
                            phase='main')

    def _execute_attack(self, attacker: Card, target_type: str,
                        target: Optional[Card], p: GameState,
                        opp: GameState, engine: DecisionEngine,
                        verbose: bool = False, attached_don: int = 0) -> bool:
        """
        Sequência: tap atacante → blocker → counter → damage.
        Com verbose, narra blocker/counter/dano.
        """
        if target_type == 'leader' and p.cannot_attack_leader_this_turn:
            if verbose:
                print('      ataque ao Leader bloqueado por efeito neste turno')
            return False

        if attacker is p.leader:
            p.leader.rested = True
        else:
            attacker.rested = True
        # Replay event: ataque declarado
        tgt_name = 'Leader' if target_type == 'leader' else (target.name if target else '?')
        atk_power_preview = live_attack_power(attacker)
        don_txt = f' anexando {attached_don} DON' if attached_don else ' sem anexar DON'
        self._log_event(p, 'attack', card=attacker, target=target if target_type != 'leader' else opp.leader,
                        description=f'{attacker.name} ataca {tgt_name}{don_txt} ({atk_power_preview} poder)',
                        phase='attack',
                        extra={'attached_don': attached_don, 'attack_power': atk_power_preview})

        # Paga o custo de lock_opp_attack_unless_pays (OP08-043), se o
        # atacante estiver sob essa trava. A viabilidade ja foi checada na
        # geracao da acao (can_afford_attack_paywall); re-checa aqui por
        # seguranca (defensivo, nao deve faltar carta na pratica).
        if attacker.attack_paywall:
            paywall = attacker.attack_paywall
            if paywall.get('cost_type') == 'trash_from_hand':
                cost_amount = min(paywall.get('cost_amount', 1), len(p.hand))
                pagas = []
                for _ in range(cost_amount):
                    pior = min(p.hand, key=lambda c: c.board_value())
                    remove_by_identity(p.hand, pior)
                    p.trash.append(pior)
                    pagas.append(pior.name[:15])
                if verbose and pagas:
                    print(f'      💸 {attacker.name[:18]} pagou pra atacar (trava): {", ".join(pagas)}')

        # Dispara efeito "when this character becomes rested" (when_rested),
        # se houver. Ocorre imediatamente apos o atacante ser restado, antes
        # do When Attacking -- segue a ordem real do texto da carta
        # (ex: OP14-119 Mihawk: "When this Character becomes rested, [efeito]").
        ee = EffectExecutor(p, opp)
        wr_logs = ee.execute(attacker, 'when_rested')
        if verbose:
            for log in wr_logs:
                if log:
                    print(f'      [quando restou] {log}')

        # Executa efeito When Attacking. battle_defender_power (poder cru do
        # alvo ANTES desta reacao) alimenta o guard de valor de
        # _combat_buff_worth_paying -- so paga custo por buff de batalha se
        # ele realmente vira o combate (achado 23/07, fecha divergencia
        # "dois motores" com resolve_optional_effem em sim_bridge.py).
        defender_power_now = ((opp.leader.power + opp.leader.power_buff)
                               if target_type == 'leader'
                               else (target.power + target.power_buff) if target else None)
        wa_logs = ee.execute(attacker, 'when_attacking',
                             battle_defender_power=defender_power_now)
        if verbose:
            for log in wa_logs:
                if log:
                    print(f'      ↳ [when attacking] {log}')

        # "leader_battle_reactive": habilidade (do proprio LIDER ou de
        # QUALQUER Character em campo) que reage quando O LIDER ataca ou e
        # atacado -- distinta de when_attacking (que so roda pra quem de
        # fato ataca, nunca pra um Character espectador) e de on_opp_attack
        # (que roda pra qualquer carta do defensor, mas sem saber se o
        # ALVO real foi o lider). So dispara aqui quando quem ataca de
        # fato E o lider; a metade "e atacado" dispara mais abaixo, no
        # bloco de on_opp_attack, gatilhada por target_type=='leader'.
        # Achado 05/08 (Edward.Newgate OP17-040, habilidade PROPRIA da
        # carta reage ao combate do LIDER, nao ao proprio; Portgas.D.Ace
        # OP03-001, LIDER, onde fonte==lider coincide com o proprio
        # atacante/alvo -- varrer [p.leader]+p.field_chars cobre os dois
        # sem duplicar codigo por tipo de carta).
        if attacker is p.leader:
            for fonte in [p.leader] + list(p.field_chars):
                lb_logs = ee.execute(fonte, 'leader_battle_reactive',
                                     battle_defender_power=defender_power_now)
                if verbose:
                    for log in lb_logs:
                        if log:
                            print(f'      ↳ [lider ataca: {fonte.name[:15]}] {log}')

        # Executa [On Your Opponent's Attack] -- gatilho do DEFENSOR,
        # reage à declaração do ataque (qualquer Character/Leader dele
        # pode ter essa habilidade, não só o alvo). Achado 27/06: a tag
        # nunca tinha reconhecimento dedicado antes, caía em 'passive'
        # (nunca disparava de verdade -- 44 cartas, ex: Viola OP04-021,
        # Mr.9 EB01-037). Roda ANTES de calcular atk_power -- efeitos
        # como debuff_power (EB01-002 Izo) precisam valer pra ESTA
        # batalha, não depois que o dano já foi calculado.
        ee_react = EffectExecutor(opp, p)
        for reagente in [opp.leader] + list(opp.field_chars):
            oa_logs = ee_react.execute(
                reagente, 'on_opp_attack', battle_attacker=attacker,
                battle_defender_power=reagente.power + reagente.power_buff)
            if verbose:
                for log in oa_logs:
                    if log:
                        print(f'      ↳ [on opp attack: {reagente.name[:15]}] {log}')

        # Metade "e atacado" de leader_battle_reactive (ver comentario
        # acima, ao lado de when_attacking): so quando o ALVO real deste
        # ataque e o lider (nao qualquer Character do defensor).
        if target_type == 'leader':
            for fonte in [opp.leader] + list(opp.field_chars):
                lb_logs = ee_react.execute(
                    fonte, 'leader_battle_reactive', battle_attacker=attacker,
                    battle_defender_power=opp.leader.power + opp.leader.power_buff)
                if verbose:
                    for log in lb_logs:
                        if log:
                            print(f'      ↳ [lider e atacado: {fonte.name[:15]}] {log}')

        atk_power = live_attack_power(attacker)
        damage    = 2 if attacker.is_double_attack() else 1

        # Block step
        opp_engine = DecisionEngine(opp, p)
        blocker = opp_engine.should_use_blocker(atk_power)
        opp.blocker_lock_battle = None   # trava era so pra ESTA batalha -- limpa already-consumida
        if blocker and not attacker.has_unblockable and not attacker.unblockable_this_turn:
            target_type = 'character'
            target      = blocker
            blocker.rested = True
            if verbose:
                print(f'      🛡 Blocker! {blocker.name[:20]} intercepta')
            # [On Block]: efeito que dispara quando este personagem bloqueia.
            # Roda no contexto do oponente (dono do blocker).
            ob_effects = get_card_effects(blocker.code)
            if 'on_block' in ob_effects:
                ee_block = EffectExecutor(opp, p)
                ob_logs = ee_block.execute(blocker, 'on_block')
                if verbose:
                    for log in ob_logs:
                        if log:
                            print(f'      ⚡ [On Block] {log}')

            # Vitoria alternativa (OP09-118 Gol.D.Roger, achado 15/07):
            # "When your opponent activates [Blocker], if either you or
            # your opponent has 0 Life cards, you win the game." `p` aqui
            # e o ATACANTE (dono do Roger, se houver) -- `opp` acabou de
            # usar Blocker, ou seja e o "your opponent" da perspectiva de
            # `p`. Checa qualquer Character/Leader de `p` com essa
            # passiva; se algum tiver, e a vida de QUALQUER um dos dois
            # lados esta em 0, `p` vence a partida imediatamente.
            if p.life_count() == 0 or opp.life_count() == 0:
                fontes = [p.leader] + list(p.field_chars)
                for fonte in fontes:
                    passive = get_card_effects(fonte.code).get('passive', {})
                    if any(s.get('action') == 'win_game_on_opp_blocker'
                           for s in passive.get('steps', [])):
                        if verbose:
                            print(f'      🏆 {fonte.name[:20]}: vitoria alternativa '
                                  f'(oponente ativou Blocker com alguem em 0 vida)')
                        return True

            # K.O. reativo (ST10-006, achado 17/07): "When your opponent
            # activates a [Blocker], K.O. up to N of your opponent's
            # Characters with X power or less" -- mesma janela/perspectiva
            # de win_game_on_opp_blocker acima (`p` e o dono da carta,
            # `opp` acabou de ativar Blocker = "your opponent" do ponto de
            # vista de `p`). Alvo = Characters de `opp` (nao so o blocker).
            # once_per_turn rastreado via flag no proprio Card (nao
            # EffectExecutor._once_used, que e por-instancia descartavel
            # e nao sobreviveria entre ataques deste mesmo turno).
            for fonte in [p.leader] + list(p.field_chars):
                fpassive = get_card_effects(fonte.code).get('passive', {})
                ko_step = next((s for s in fpassive.get('steps', [])
                                if s.get('action') == 'ko_on_opp_blocker'), None)
                if not ko_step or fonte.ko_on_opp_blocker_used_this_turn:
                    continue
                from optcg_engine.rules_facade import eligible_cards, choose_highest_board_value
                count = ko_step.get('count', 1)
                candidatos = eligible_cards(opp.field_chars, power_lte=ko_step.get('power_lte'))
                ee_ko = EffectExecutor(opp, p)
                koed = []
                for _ in range(min(count, len(candidatos))):
                    alvo_ko = choose_highest_board_value(candidatos)
                    if is_immune(alvo_ko, 'ko', opp, p, source_is_opp=True, ko_context='effect'):
                        remove_by_identity(candidatos, alvo_ko)
                        continue
                    if ee_ko.try_any_substitute(alvo_ko, 'ko', source_is_opp=True):
                        remove_by_identity(candidatos, alvo_ko)
                        continue
                    remove_character_from_field(opp, alvo_ko, 'trash')
                    ee_ko.execute(alvo_ko, 'on_ko', is_opp_turn=True)
                    ee_ko._dispatch_opp_char_ko()
                    ee_ko._dispatch_own_char_ko(alvo_ko)
                    ee_ko._dispatch_any_char_ko(alvo_ko)
                    remove_by_identity(candidatos, alvo_ko)
                    koed.append(alvo_ko.name[:15])
                fonte.ko_on_opp_blocker_used_this_turn = True
                if verbose and koed:
                    print(f'      💀 {fonte.name[:20]}: K.O. reativo (oponente ativou '
                          f'Blocker) -- {", ".join(koed)}')

        # Define poder de defesa
        if target_type == 'leader':
            defend_power = opp.leader.power + opp.leader.power_buff
        elif target and target in opp.field_chars:
            defend_power = target.power + target.power_buff
            # Rastreio de combate (achado 15/07, OP12-020 Zoro lider e
            # familia -- OP04-047/ST02-010/ST08-013): alvo final (ja
            # pos-blocker) e um Character do oponente -- registra que o
            # ATACANTE "battled" um Character neste turno. Setado aqui (nao
            # so na declaracao) pra cobrir corretamente o caso de blocker
            # redirect (atacar o Leader mas acabar batendo num Character).
            attacker.battled_opp_character_this_turn = True
        else:
            return False

        # Counter step
        if opp_engine.should_use_counter(atk_power, defend_power):
            counter_add = opp_engine.use_counter(atk_power - defend_power + 1)
            defend_power += counter_add
            if verbose and counter_add > 0:
                print(f'      🛡 Counter! +{counter_add} -> defesa {defend_power}')

        if atk_power >= defend_power:
            counter_target = opp.leader if target_type == 'leader' else target
            counter_event = ee_react.try_counter_event_power(
                counter_target,
                target_type,
                atk_power - defend_power + 1,
            )
            if counter_event:
                amount, counter_log = counter_event
                defend_power += amount
                if verbose:
                    print(f'      🛡 {counter_log} -> defesa {defend_power}')

        attacker_type = 'leader' if attacker is p.leader else 'character'

        # Counter event que enfraquece o ATACANTE em vez de buffar a propria
        # defesa -- mecanica distinta (ex: OP01-028, ST09-014). So tentado se
        # o buff acima nao bastou.
        if atk_power >= defend_power:
            counter_debuff = ee_react.try_counter_event_debuff(
                attacker,
                attacker_type,
                atk_power - defend_power + 1,
            )
            if counter_debuff:
                amount, counter_log = counter_debuff
                atk_power -= amount
                if verbose:
                    print(f'      🛡 {counter_log} -> ataque {atk_power}')

        # Counter event que da K.O. no ATACANTE inteiro -- cancela o ataque
        # por completo (sem dano), distinto dos dois mecanismos acima que so
        # ajustam power. So aplica a Characters atacando (Leaders nao sao
        # alvo de 'opp_character').
        if atk_power >= defend_power and attacker_type == 'character':
            ko_log = ee_react.try_counter_event_ko_attacker(attacker)
            if ko_log:
                if verbose:
                    print(f'      🛡 {ko_log} -> ataque cancelado')
                return False

        # Damage step
        if atk_power >= defend_power:
            if target_type == 'leader':
                # Vitória só se o oponente JÁ estava com 0 vidas ANTES deste ataque.
                # (Receber dano com 0 vidas = derrota.)
                if not opp.life:
                    p.dmg_dealt += 1
                    # Achado 06/08 (investigando os 14 casos residuais do
                    # Katakuri em audit_real_losses.py/triage_real_losses.py):
                    # este e o UNICO caminho de dano/vitoria de TODA a
                    # funcao sem print nenhum em verbose=True (todos os
                    # outros -- dano normal, banish, bloqueio -- imprimem
                    # algo). Narrativa capturada (`engine_hoje_narrativa`)
                    # terminava ABRUPTAMENTE logo apos "ataca Leader", sem
                    # nenhum resultado -- fazia parecer que o motor "parou
                    # de atacar" quando na verdade ele GANHOU o jogo bem
                    # ali (2 dos 14 casos residuais eram exatamente este
                    # artefato de narrativa, nao decisao pior que a
                    # historica -- ver parser_audits N/A, registrado em
                    # HANDOFF/TODO por ser fix de engine, nao de parser).
                    if verbose:
                        print(f'      🏆 VITORIA! {attacker.name[:20]} zera a vida do oponente')
                    return True  # vitória: dano com 0 vidas

                # Tira até 'damage' vidas, UMA por vez, resolvendo trigger de cada.
                # Se a vida acabar durante o double attack, PARA — o dano extra
                # não causa derrota (regra: só compra as vidas que tem).
                vidas_tiradas = 0
                for _ in range(damage):
                    if not opp.life:
                        break   # acabou a vida durante este ataque — não é derrota
                    life_card = opp.life.pop()
                    vidas_tiradas += 1
                    p.dmg_dealt += 1
                    # Banish: a vida vai DIRETO para o trash, sem ir para a mão
                    # e sem direito a trigger (regra oficial).
                    if attacker.has_banish:
                        opp.trash.append(life_card)
                        self._log_event(p, 'life_damage', card=attacker, target=life_card,
                            description=f'BANISH! vida de {(self._name_b if p is self.state_a else self._name_a)}: {opp.life_count()}',
                            phase='attack')
                        if verbose:
                            print(f'      💥 DANO (BANISH)! vida -> trash: {opp.life_count()}')
                    else:
                        # ST13-003 Luffy Leader: face-up life cards go to deck
                        # bottom instead of hand (passive rule change).
                        if life_card.life_face_up and opp.face_up_life_to_deck:
                            life_card.life_face_up = False
                            opp.deck.insert(0, life_card)
                        else:
                            opp.hand.append(life_card)
                        opp_name = self._name_b if p is self.state_a else self._name_a
                        self._log_event(p, 'life_damage', card=attacker, target=life_card,
                            description=f'Dano! vida de {opp_name}: {opp.life_count()} restantes',
                            phase='attack')
                        if verbose:
                            print(f'      💥 DANO! vida do oponente: {opp.life_count()}')
                    # O dano foi recebido mesmo em Banish; apenas o Trigger
                    # da carta de Life e bloqueado por Banish.
                    EffectExecutor(opp, p)._dispatch_damage_or_own_char_ko(opp)
                    if life_card.has_trigger and not attacker.has_banish:
                        opp.triggers_activated += 1
                        ee_opp = EffectExecutor(opp, p)
                        # is_my_turn=False: opp (dono da vida) nao tem o
                        # turno agora -- p (atacante) tem.
                        tg_logs = ee_opp.execute(life_card, 'trigger', is_my_turn=False)
                        if verbose:
                            for log in tg_logs:
                                if log:
                                    print(f'      ⚡ [trigger] {log}')

                # Gatilho reativo "When this Character's/Leader's attack
                # deals damage to your opponent's Life, you may trash N
                # cards..." (achado 17/07, familia OP03-040/041/043/047/
                # 051) -- so dispara se o dano REALMENTE conectou nesta
                # batalha (>=1 vida removida), amarrado ao ATACANTE
                # especifico (nao a qualquer Character do dono) e
                # condicionado a don_requirement (DON!! xN ja anexado ao
                # atacante neste ataque). Ver parse_card_effect() em
                # gerar_effects_db.py -- chave 'on_damage_to_life',
                # distinta de 'passive' pra nao ser recalculada (mill
                # incondicional) a cada apply_your_turn_buffs.
                if vidas_tiradas > 0:
                    dmg_life = get_card_effects(attacker.code).get('on_damage_to_life')
                    if dmg_life:
                        don_req = dmg_life.get('don_requirement', 0)
                        if not don_req or getattr(attacker, 'don_attached', 0) >= don_req:
                            ee_dmg = EffectExecutor(p, opp)
                            for dl_step in dmg_life.get('steps', []):
                                dl_log = ee_dmg._execute_step(dl_step, attacker)
                                if verbose and dl_log:
                                    print(f'      ↳ [dano na vida] {dl_log}')
                                if dl_step.get('self_ko') and attacker in p.field_chars:
                                    remove_character_from_field(p, attacker, 'trash')
                                    ee_dmg.execute(attacker, 'on_ko')
                                    ee_dmg._dispatch_opp_char_ko()
                                    ee_dmg._dispatch_own_char_ko(attacker)
                                    ee_dmg._dispatch_any_char_ko(attacker)
                                    if verbose:
                                        print(f'      💀 {attacker.name[:20]}: K.O. (mill do proprio efeito)')

                return False   # tirou vida(s), mas oponente não estava em 0 — sem derrota
            elif target_type == 'character' and target and target in opp.field_chars:
                # Imunidade a KO em combate. `is_immune` separa esta janela de
                # KO por efeito quando o texto bruto diz "in battle"/"by effects".
                if is_immune(
                    target,
                    'ko',
                    opp,
                    p,
                    source_is_opp=True,
                    ko_context='battle',
                    source_card=attacker,
                ):
                    if verbose:
                        print(f'      🛡 {target.name[:20]} imune a KO!')
                    return False
                ee_opp = EffectExecutor(opp, p)
                sub_log = ee_opp.try_any_substitute(target, 'ko', source_is_opp=True)
                if sub_log:
                    if verbose:
                        print(f'      🔁 {sub_log}')
                    return False
                counter_sub_log = ee_opp.try_counter_event_substitute(target, 'ko')
                if counter_sub_log:
                    if verbose:
                        print(f'      🔁 {counter_sub_log}')
                    return False
                remove_character_from_field(opp, target, 'trash')
                if verbose:
                    print(f'      💀 {target.name[:20]} foi KO!')
                ko_logs = ee_opp.execute(target, 'on_ko', is_opp_turn=True)
                ee_opp._dispatch_damage_or_own_char_ko(opp, target)
                ee_opp._dispatch_opp_char_ko()
                ee_opp._dispatch_own_char_ko(target)
                ee_opp._dispatch_any_char_ko(target)
                if verbose:
                    for log in ko_logs:
                        if log:
                            print(f'      ↳ [on KO] {log}')
        else:
            if verbose:
                print(f'      ✗ Ataque bloqueado ({atk_power} < {defend_power})')

        return False

    # ── Decision audit logger ────────────────────────────────────────────────

    def enable_decision_audit(self):
        """Ativa o log de auditoria de decisão. Chamar antes de setup()/play_turn()."""
        self.decision_log = []
        self._card_count_baseline = {}

    def _check_invariants(self, turn: 'int | None' = None) -> None:
        """
        Verifica invariantes de conservacao (DON, poder, contagem de cartas)
        apos um turno -- migrado de audit_replay.py (achou o bug real de
        conservacao de DON do deck Ace, ver TODO.md) pra dentro do motor,
        unificado na MESMA lista de auditoria de _log_decision/
        _log_turn_planner_decision (pedido do usuario 25/07: uma lista so,
        nao um script externo com sua propria checagem). So roda com
        decision_log ativo (mesmo guard das outras 2 funcoes de log) --
        chamada direto por este proprio play_turn() (ver abaixo), entao
        cobre de graca QUALQUER consumidor de self-play que passe por ele,
        direto (audit_card_effects.py, audit_decision_quality.py,
        baseline_metrics.py, tune_weights.py) ou via
        ReplayMatch.play_turn() (replay_optcg.py, que desde 25/07 delega
        inteiro pra ca em vez de reimplementar a orquestracao de turno).
        So grava entrada quando ACHA violacao -- nunca
        por turno saudavel, pra nao inflar a lista em rodadas de centenas
        de partidas (tune_weights.py).

        NAO migrado: a checagem de 'nao implementado' no texto impresso
        (audit_replay.py) -- e uma varredura do stdout capturado da
        partida inteira, natureza diferente de um invariante de estado;
        continua so no script.
        """
        if self.decision_log is None or self._suppress_replay_log:
            return
        if not hasattr(self, '_card_count_baseline'):
            self._card_count_baseline = {}
        turn = turn if turn is not None else self.global_turn
        for gs, label in ((self.state_a, 'A'), (self.state_b, 'B')):
            field_don = sum(c.don_attached for c in gs.field_chars) + gs.leader.don_attached
            total_don = gs.don_available + gs.don_rested + field_don
            esperado_don = 10 - gs.don_deck
            if total_don != esperado_don:
                # Detalhe de duplicata por REFERENCIA -- foi assim que se
                # achou o bug de identidade do Card em 29/06/2026 (ver
                # TODO.md): mesmo objeto Python 2x em field_chars.
                ids = [id(c) for c in gs.field_chars]
                dups = [i for i in set(ids) if ids.count(i) > 1]
                detalhe = (f'available={gs.don_available} rested={gs.don_rested} '
                           f'field={field_don} soma={total_don} '
                           f'esperado(10-don_deck)={esperado_don}')
                if dups:
                    detalhe += (f' | DUPLICADO NA LISTA field_chars: '
                                f'{len(dups)} objeto(s) repetido(s), ids={dups}')
                self.decision_log.append({
                    'kind': 'invariant_violation',
                    'turn': turn,
                    'player': label,
                    'check': 'don_conservation',
                    'detail': detalhe,
                })
            for c in gs.field_chars + [gs.leader]:
                if c.effective_power() < 0:
                    self.decision_log.append({
                        'kind': 'invariant_violation',
                        'turn': turn,
                        'player': label,
                        'check': 'negative_power',
                        'detail': f'{c.name} com power negativo ({c.effective_power()})',
                    })
            atual = (len(gs.hand) + len(gs.field_chars) + len(gs.deck) + len(gs.trash)
                     + len(gs.life) + (1 if gs.field_stage else 0))
            baseline = self._card_count_baseline.get(label)
            if baseline is None:
                self._card_count_baseline[label] = atual
            elif atual != baseline:
                self.decision_log.append({
                    'kind': 'invariant_violation',
                    'turn': turn,
                    'player': label,
                    'check': 'card_count',
                    'detail': (f'total mudou de {baseline} para {atual} '
                               f'(hand={len(gs.hand)} field={len(gs.field_chars)} '
                               f'deck={len(gs.deck)} trash={len(gs.trash)} '
                               f'life={len(gs.life)})'),
                })

    def _log_decision(self, p: GameState, card, trigger: str,
                      decision: str, reason: str):
        """
        Registra uma decisão da IA sobre um efeito.
        decision: 'skip' | 'activate'
        reason:   texto livre explicando o motivo
        """
        if self.decision_log is None or self._suppress_replay_log:
            return
        player_id = 'A' if p is self.state_a else 'B'
        self.decision_log.append({
            'turn':    self.global_turn,
            'player':  player_id,
            'card':    card.code if card else '',
            'name':    card.name if card else '',
            'trigger': trigger,
            'decision': decision,
            'reason':  reason,
        })

    def _audit_card_brief(self, card):
        if card is None:
            return None
        if not hasattr(card, 'code'):
            return {'label': str(card)}
        return {
            'code': card.code,
            'name': card.name,
            'type': card.card_type,
            'cost': card.cost,
            'power': card.power,
            'current_power': card.effective_power(True),
            'rested': bool(getattr(card, 'rested', False)),
            'just_played': bool(getattr(card, 'just_played', False)),
            'don_attached': int(getattr(card, 'don_attached', 0)),
        }

    def _audit_action_brief(self, action, simulated_value=None, cheap_value=None,
                             added_by_cheap_layer=False):
        score, kind, obj, target_type, target = action
        sim_avg = simulated_value
        sim_wins = None
        sim_samples = None
        if isinstance(simulated_value, dict):
            sim_avg = simulated_value.get('avg')
            sim_wins = simulated_value.get('wins')
            sim_samples = simulated_value.get('samples')
        return {
            'score': round(float(score), 2),
            'simulated_value': (None if sim_avg is None
                                else round(float(sim_avg), 2)),
            'simulated_wins': sim_wins,
            'simulated_samples': sim_samples,
            # camada barata (bloco 508/509) -- None quando USE_CHEAP_LAYER_
            # SHORTLIST esta desligado ou a acao nao foi avaliada por ela.
            # `audit_cheap_layer.py` le este campo pra medir concordancia
            # com `simulated_value` (a busca real) nas candidatas que tem
            # os dois.
            'cheap_value': (None if cheap_value is None
                            else round(float(cheap_value), 2)),
            # True so pras candidatas que NAO entrariam no shortlist pelo
            # score estatico sozinho -- so a camada barata as promoveu
            # (`OPTCGMatch._last_cheap_layer_additions`). E o sinal chave
            # pra `audit_cheap_layer.py` responder "o alargamento pega
            # valor real, ou so gasta orcamento a toa?".
            'added_by_cheap_layer': bool(added_by_cheap_layer),
            'kind': kind,
            'card': self._audit_card_brief(obj),
            'target_type': target_type,
            'target': self._audit_card_brief(target),
        }

    def _log_turn_planner_decision(self, p: GameState, opp: GameState, engine,
                                   priority: str, actions: list, candidates: list,
                                   chosen, chosen_value, sim_values: dict,
                                   cheap_values: dict | None = None):
        """Registra o ranking que levou o Turn Planner a escolher uma acao."""
        if self.decision_log is None or self._suppress_replay_log:
            return
        player_id = 'A' if p is self.state_a else 'B'
        top_immediate = actions[0] if actions else None
        chosen_card = chosen[2] if chosen else None
        cv = cheap_values or {}
        added_ids = getattr(self, '_last_cheap_layer_additions', None) or set()
        self.decision_log.append({
            'kind': 'turn_planner',
            'turn': self.global_turn,
            'player': player_id,
            'decision': 'choose_action',
            'trigger': 'turn_planner',
            'card': chosen_card.code if chosen_card else '',
            'name': chosen_card.name if chosen_card else '',
            'reason': f'priority={priority}',
            'context': {
                'priority': priority,
                'posture': engine.posture(),
                'phase': engine.analyzer.game_phase(),
                'profile': engine.analyzer.deck_profile_type(),
                'life': p.life_count(),
                'opp_life': opp.life_count(),
                'hand': len(p.hand),
                'opp_hand': len(opp.hand),
                'field': len(p.field_chars),
                'opp_field': len(opp.field_chars),
                'don_available': p.don_available,
                'don_rested': p.don_rested,
                'can_lethal': engine.analyzer.can_lethal_this_turn(),
                'opp_lethal_threat': round(float(engine.analyzer.opp_lethal_threat()), 3),
                'opp_combo_threat': engine.analyzer.opp_combo_threat(),
                # bloco 508/509: visibilidade agregada da camada barata sem
                # precisar reconstruir por-candidata -- audit_cheap_layer.py
                # usa isto pra medir "quanto alargou" ao longo de muitas
                # partidas.
                'cheap_layer_active': cheap_values is not None,
                'n_candidates': len(candidates),
            },
            'chosen': (self._audit_action_brief(chosen, chosen_value, cv.get(id(chosen)),
                                                id(chosen) in added_ids)
                      if chosen else None),
            'top_immediate': (self._audit_action_brief(top_immediate, None, cv.get(id(top_immediate)),
                                                        id(top_immediate) in added_ids)
                              if top_immediate else None),
            'candidates': [
                self._audit_action_brief(a, sim_values.get(id(a)), cv.get(id(a)),
                                         id(a) in added_ids)
                for a in candidates[:8]
            ],
        })
        # DecisionTrace (ideia 2 do PDF): torna EXPLÍCITO "por que a alternativa
        # foi descartada" = margem de valor esperado abaixo da escolhida. Já
        # tínhamos os candidatos+valores; isto só rotula o gap pra leitura
        # humana/front (o valor bruto continua disponível pra depuração).
        rec = self.decision_log[-1]
        chosen_val = (rec['chosen'] or {}).get('simulated_value')
        if chosen_val is not None:
            for c in rec['candidates']:
                cv = c.get('simulated_value')
                if cv is None:
                    c['descartada_porque'] = 'linha inviável / sem simulação'
                elif abs(cv - chosen_val) < 1e-6:
                    c['descartada_porque'] = None   # é a escolhida (ou empate)
                else:
                    c['descartada_porque'] = f'valor esperado {round(chosen_val - cv, 1)} abaixo da escolhida'

    # ── Replay logger ────────────────────────────────────────────────────────

    def _log_event(self, p: GameState, event_type: str, card: 'Card' = None,
                   target: 'Card' = None, description: str = '', phase: str = 'main',
                   extra: dict = None):
        """Registra um evento estruturado se replay_log estiver ativo."""
        if self.replay_log is None or self._suppress_replay_log:
            return

        def card_dict(c):
            if c is None:
                return None
            return {
                'code':  c.code,
                'name':  c.name,
                'image': _CARD_IMAGE_CACHE.get(c.code, ''),
                'cost':  c.cost,
                'power': c.power,
                'type':  c.card_type,
                'color': c.color or '',
            }

        def state_dict(s: GameState):
            don_total = 10 - s.don_deck
            return {
                'leader': card_dict(s.leader),
                'life': s.life_count(),
                'hand': len(s.hand),
                'hand_cards': [
                    {
                        **card_dict(c),
                        'counter': c.counter,
                        'effective_cost': effective_hand_play_cost(
                            s, c, self.state_b if s is self.state_a else self.state_a),
                    }
                    for c in s.hand
                ],
                'deck': len(s.deck),
                'trash': len(s.trash),
                'don_available': s.don_available,
                'don_rested': s.don_rested,
                'don_total': don_total,
                'stage': card_dict(s.field_stage),
                'characters': [
                    {
                        **card_dict(c),
                        'rested': bool(getattr(c, 'rested', False)),
                        'current_power': c.effective_power(True),
                    }
                    for c in s.field_chars
                ],
                'stats': {
                    'damage': s.dmg_dealt,
                    'counters': s.counters_used,
                    'searchers': s.searchers_used,
                    'triggers': s.triggers_activated,
                },
            }

        player_id = 'A' if p is self.state_a else 'B'
        player_name = self._name_a if player_id == 'A' else self._name_b
        event = {
            'turn':        self.global_turn,
            'player':      player_id,
            'player_name': player_name,
            'phase':       phase,
            'type':        event_type,
            'card':        card_dict(card),
            'target':      card_dict(target),
            'description': description,
            'state':       {
                'A': state_dict(self.state_a),
                'B': state_dict(self.state_b),
            },
        }
        if extra:
            event.update(extra)
        self.replay_log.append(event)

    def simulate_replay(self, name_a: str = 'Player A', name_b: str = 'Player B') -> dict:
        """Roda uma partida completa capturando log estruturado de eventos.
        Retorna o mesmo dict de simulate() mais 'events' (lista de eventos
        por turno) e 'turns_detail' (eventos agrupados por turno)."""
        self.replay_log = []
        self._name_a = name_a
        self._name_b = name_b
        result = self.simulate()

        # Agrupa eventos por turno para o frontend navegar facilmente
        turns_detail = {}
        for ev in self.replay_log:
            t = ev['turn']
            turns_detail.setdefault(t, []).append(ev)

        result['events'] = self.replay_log
        result['turns_detail'] = [
            {'turn': t, 'events': evs}
            for t, evs in sorted(turns_detail.items())
        ]
        return result

    def _play_turn_greedy(self, p: 'GameState', opp: 'GameState', max_steps: int = 6) -> bool:
        """
        Joga UM turno completo de `p` (refresh->draw->don->acoes) GULOSAMENTE:
        sempre a acao de maior score IMEDIATO (_generate_and_score_actions),
        SEM Monte Carlo e SEM aninhar main_phase. Item 3 do plano
        (PLANO_AVALIACAO_E_BUSCA.md): usado por `_simulate_sequence_once` pra
        simular a RESPOSTA do oponente depois da MINHA linha, com o PROPRIO
        engine dele -- "modo guloso, sem aninhar" e explicito no plano
        justamente pra evitar explosao (main_phase ja roda TOP_K x MC
        simulacoes por decisao; chamar main_phase() de novo aqui multiplicaria
        isso por turno de resposta simulado). Motor unico: mesma
        _generate_and_score_actions/_apply_action que decide QUALQUER turno,
        sem regua propria -- serve pra qualquer deck de qualquer lado.

        Retorna True se `p` (quem esta jogando este turno) vence.
        """
        p.turn += 1
        p.is_active_turn = True
        opp.is_active_turn = False
        p.pending_play_cost_reductions.clear()
        self.refresh_phase(p, opp)
        self.draw_phase(p)
        self.don_phase(p)
        engine = DecisionEngine(p, opp)
        ee = EffectExecutor(p, opp)
        for _ in range(max_steps):
            acts = self._generate_and_score_actions(p, opp, engine)
            if not acts or acts[0][0] < 0:
                break
            if self._apply_action(acts[0], p, opp, ee, engine, verbose=False):
                return True
        self.end_phase(p, opp)
        for c in p.field_chars:
            c.just_played = False
        return False

    def play_turn(self, p: GameState, opp: GameState, verbose: bool = False,
                  post_don_hook: 'Callable[[GameState, GameState], None] | None' = None) -> Optional[str]:
        """
        post_don_hook: opcional, chamado logo apos don_phase e antes do
        main_phase -- unico ponto que replay_optcg.py precisa pra imprimir
        campo/perfil/postura no meio do turno (pedido do usuario 25/07: sem
        isso ReplayMatch.play_turn() reimplementava a orquestracao inteira
        do turno so pra conseguir esse print no meio, causando divergencia
        real com este metodo -- end_phase()/is_active_turn/
        pending_play_cost_reductions/deck_out_win_instead_of_loss ficavam
        de fora do replay). Nao usado no caminho ao vivo nem em simulate().
        """
        self.global_turn += 1
        p.turn += 1
        p.global_turn = self.global_turn
        opp.global_turn = self.global_turn
        p.is_active_turn = True
        opp.is_active_turn = False
        p.pending_play_cost_reductions.clear()

        self._log_event(p, 'turn_start', phase='refresh',
                        description=f'Turno {self.global_turn} — refresh/compra/DON')
        self.refresh_phase(p, opp)

        # Log de compra de carta
        hand_before = len(p.hand)
        self.draw_phase(p, verbose=verbose)
        drawn = len(p.hand) - hand_before
        if drawn > 0:
            self._log_event(p, 'draw', phase='draw',
                            description=f'Comprou {drawn} carta(s)',
                            extra={'count': drawn})

        self.don_phase(p, verbose=verbose)
        if post_don_hook is not None:
            post_don_hook(p, opp)

        won = self.main_phase(p, opp, verbose=verbose)
        # Invariantes de conservacao (DON/poder/contagem) -- mesmo guard
        # interno de decision_log ativo; cobre qualquer consumidor deste
        # metodo (audit_card_effects.py, audit_decision_quality.py,
        # ReplayMatch.play_turn() via _get_engine_match().play_turn(),
        # desde que ReplayMatch parou de reimplementar a propria
        # orquestracao de turno).
        self._check_invariants()
        if won:
            return 'A' if p is self.state_a else 'B'
        self.end_phase(p, opp, verbose=verbose)
        self._log_event(p, 'turn_end', phase='end',
                        description=f'Fim do turno {self.global_turn}')
        # deck_out_win_instead_of_loss (OP03-040 Nami lider): inverte o
        # resultado padrao de deck-out (quem zera o proprio deck normalmente
        # perde) especificamente pro dono desta carta.
        def _wins_on_own_deck_out(player: GameState) -> bool:
            return any(r.get('type') == 'deck_out_win_instead_of_loss'
                       for r in get_card_game_rules(player.leader.code))

        if not p.deck:
            p_wins = _wins_on_own_deck_out(p)
            return ('A' if p_wins else 'B') if p is self.state_a else ('B' if p_wins else 'A')
        if not opp.deck:
            opp_wins = _wins_on_own_deck_out(opp)
            return ('B' if opp_wins else 'A') if p is self.state_a else ('A' if opp_wins else 'B')
        return None

    def simulate(self) -> dict:
        self.setup()
        winner = None
        total_turns = 0

        # Ponteiro "quem joga agora" (achado 16/07, OP05-119 "take an
        # extra turn"): antes disso o loop decidia via turn_num % 2, uma
        # alternancia fixa sem estado -- nunca permitia o MESMO jogador
        # jogar duas vezes seguidas. Agora alterna normalmente apos cada
        # play_turn(), MAS repete o mesmo `p` (sem trocar pra `opp`) se
        # extra_turn_pending foi setado durante o turno que acabou de
        # rodar (consumido/resetado aqui, uma unica vez por turno extra
        # concedido). MAX_TURNS * 2 continua como teto de seguranca --
        # ainda conta CADA execucao de play_turn() como 1 iteracao, entao
        # turnos extras nao estouram o limite de chamadas, so mudam quem
        # joga em cada uma.
        p = self.state_a if self.state_a.is_first else self.state_b
        opp = self.state_b if p is self.state_a else self.state_a

        for _ in range(self.MAX_TURNS * 2):
            result = self.play_turn(p, opp)
            total_turns += 1
            if result:
                winner = result
                break
            if p.extra_turn_pending:
                p.extra_turn_pending = False
                # mesmo jogador de novo -- p/opp permanecem os mesmos
            else:
                p, opp = opp, p

        return {
            'winner':      winner or 'DRAW',
            'turns':       total_turns,
            'dmg_a':       self.state_a.dmg_dealt,
            'dmg_b':       self.state_b.dmg_dealt,
            'life_a':      self.state_a.life_count(),
            'life_b':      self.state_b.life_count(),
            'counters_a':  self.state_a.counters_used,
            'counters_b':  self.state_b.counters_used,
            'searchers_a': self.state_a.searchers_used,
            'searchers_b': self.state_b.searchers_used,
            'triggers_a':  self.state_a.triggers_activated,
            'triggers_b':  self.state_b.triggers_activated,
        }


# ===========================================================================
# Pipeline de simulação
# ===========================================================================

def simular_matchup(deck_a: tuple, deck_b: tuple, n: int = 100) -> dict:
    wins_a = wins_b = draws = 0
    total_turns = []
    counters_a = counters_b = searchers_a = searchers_b = triggers_a = triggers_b = 0

    for _ in range(n):
        match = OPTCGMatch(deck_a, deck_b)
        r = match.simulate()
        if r['winner'] == 'A':   wins_a += 1
        elif r['winner'] == 'B': wins_b += 1
        else:                    draws  += 1
        total_turns.append(r['turns'])
        counters_a  += r['counters_a'];  counters_b  += r['counters_b']
        searchers_a += r['searchers_a']; searchers_b += r['searchers_b']
        triggers_a  += r['triggers_a'];  triggers_b  += r['triggers_b']

    total     = wins_a + wins_b + draws
    avg_turns = sum(total_turns) / len(total_turns) if total_turns else 0

    return {
        'wins_a': wins_a, 'wins_b': wins_b, 'draws': draws,
        'winrate_a':      round(wins_a / total * 100, 1) if total > 0 else 50.0,
        'winrate_b':      round(wins_b / total * 100, 1) if total > 0 else 50.0,
        'avg_turns':      round(avg_turns, 1),
        'counters_pg_a':  round(counters_a  / total, 1) if total > 0 else 0,
        'counters_pg_b':  round(counters_b  / total, 1) if total > 0 else 0,
        'searchers_pg_a': round(searchers_a / total, 1) if total > 0 else 0,
        'searchers_pg_b': round(searchers_b / total, 1) if total > 0 else 0,
        'triggers_pg_a':  round(triggers_a  / total, 1) if total > 0 else 0,
        'triggers_pg_b':  round(triggers_b  / total, 1) if total > 0 else 0,
    }
