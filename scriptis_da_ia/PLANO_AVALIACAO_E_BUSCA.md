# PLANO — Núcleo de avaliação + busca (evolução do motor de decisão)

**Aberto:** 13/07/2026 · **Status:** EM EXECUÇÃO (item 0)
**Origem:** debate com o usuário após 3 dias de whack-a-mole de heurística
(cada report vira patch local com peso no olho → pêndulos: trash só-mão↔só-campo,
counter tudo↔nada). Diagnóstico: faltam UMA função de avaliação global e busca.
Não é hora de ML/rede neural (precisa de milhões de partidas + o mesmo
encanamento saudável que qualquer técnica exige). Caminho = etapas 2→3→4 da
literatura de IA de card game (avaliação de posição → busca → resposta do
oponente), reaproveitando o simulador que já temos.

> **Regra de ouro deste plano:** nossa opinião (usuário + Claude) entra só na
> GRAMÁTICA de padrões que o extrator reconhece. Alvo, peso, forma de curva e
> até a sobrevivência de cada eixo saem de MEDIÇÃO (self-play + ablação), nunca
> de debate. Ver memória [[feedback_fixes_globais_nao_pontuais]].

> **Princípio DECK-AGNÓSTICO (confirmado com o usuário 13/07):** NADA neste
> sistema é específico de um deck. O extrator lê QUALQUER deck do banco (mesmo
> código, zero nome de carta — Imu foi só exemplo pra criticar). Corolário
> operacional exigido pelo usuário: **pipeline self-service** — deck novo
> largado no banco é automaticamente (a) perfilado pelo deck_profile e (b)
> tem os pesos da evaluate_state tunados por self-play contra o pool existente,
> resultado cacheado por hash do deck. Zero trabalho manual por deck. A
> gramática de padrões é UNIVERSAL: completá-la (ex: família de disrupção)
> melhora a leitura de todos os decks, não de um.

---

## 📊 MARCO-ZERO medido (13/07, 50 jogos/matchup, seed=1, motor-vs-motor)

Reproduzir: `python baseline_metrics.py --deck-a Imu --deck-b <X>`. JSONs em
`baseline_imu_vs_{teach,krieg,kid}.json`. Toda etapa compara contra ISTO.

| matchup | winrate Imu | atk/turno (Imu·opp) | %líder (Imu·opp) | dano/jogo (Imu·opp) | **DON/atk (Imu·opp)** |
|---|---|---|---|---|---|
| vs Teach BY | **0.88** | 1.41 · 1.54 | 86.7 · 81.3 | 3.94 · 2.70 | **0.56 · 1.53** |
| vs Krieg | **0.38** | 1.67 · 1.84 | 67.5 · 76.9 | 2.76 · 3.76 | **0.60 · 1.22** |
| vs Kid | **0.34** | 1.46 · 1.65 | 77.4 · 83.5 | 3.78 · 2.90 | **0.65 · 1.25** |

**Leituras que guiam o plano:**
1. **A passividade é sistêmica e está na régua do DON, não do alvo.** Em TODOS
   os matchups o Imu anexa ~0.6 DON/ataque vs ~1.2–1.5 do oponente — ataca
   quase seco, oponente countera barato e devolve. Mira do líder já está ok
   (67–87%, a cegueira do trash foi resolvida). → **`don_por_atk` e
   `dano_por_jogo` são as métricas SENSÍVEIS pra medir as etapas 1–3.** É o
   gap que a busca do item 3 ("anexo DON ou ataco seco?") deve fechar.
2. **Winrate vs Teach (0.88) é TETO — sinal fraco pra tunagem.** Motor-vs-motor
   o Imu esmaga o Teach; a dificuldade que o usuário sente é a assimetria
   humano-vs-bot, não força do deck. → **Gauntlet do item 5 deve priorizar os
   matchups EQUILIBRADOS (Krieg 0.38, Kid 0.34) + espelho Imu-vs-Imu**, onde
   há gradiente. Teach entra só como sanity, não como alvo de otimização.
   (Decisão pendente do usuário sobre o gauntlet agora é INFORMADA por isto.)

## Ordem de prioridade

### 0. Baseline medido — PRÉ-REQUISITO DE TUDO
Bateria fixa ANTES de mexer: ~50 partidas motor-vs-motor, seeds fixas
(`PYTHONHASHSEED=0` já garante reprodutibilidade). Métricas: winrate,
ataques/turno, dano feito no líder, % de ataques no líder, DON anexado/ataque.
Sem baseline não sabemos se as etapas melhoram ou só deslocam.
*Esforço: pequeno (infra já existe em audit_antipatterns.py / OPTCGMatch).*

### 1. `evaluate_state(eu, ele) → nota` — a régua única  ★ PIVÔ
Uma função só, escala só, simétrica. Termos GENÉRICOS (universais do OPTCG):
- **Vida** — curva íngreme (vida 1 » 5ª vida), reusa a curva do counter.
- **Board** — Σ `char_value_score` (já vê blocker/rush/imunidade condicional) + `stage_worth`.
- **Mão** — contagem com retorno decrescente + poder de counter na mão.
- **DON no campo** — ramp = chegar na bomba.
- **Cobertura defensiva** — `min(counter na mão, ataques esperados dele)`.
- **Tempo/iniciativa** — meus corpos que atacam no próximo turno vs os dele ativos.

Disciplina anti-pêndulo: réguas antigas (`_trash_value`, `char_value_score`,
curvas de vida) viram INSUMOS normalizados na entrada; NENHUMA decisão volta a
comparar duas escalas cruas. Rollout sem big-bang: entra primeiro só onde o MC
de fim de turno do Turn Planner avalia hoje (swap drop-in), mede, depois migra
os outros consumidores (defesa, escolha de alvo) um a um.
*Esforço: 1 sessão. Junto com o item 2.*

### 2. Extrator de perfil do deck — os termos ESPECÍFICOS sem hardcode
A `evaluate_state` se instancia sozinha varrendo o `card_effects_db` do deck
(generalização do `compute_game_plan`). Não citar carta nenhuma. Com as 6
melhorias debatidas:
1. **Peso por IMPACTO, não contagem** — `Σ(cópias × magnitude do que a condição destrava)`; `trash_gte 7` que dá imunidade+Rush a 5 corpos » `trash_gte 19` de bônus de 1 carta.
2. **Escadaria com saturação** — degraus nos thresholds do histograma (não só a moda); trash 6→7 vale muito, 2→3 pouco, >7 quase nada até o próximo degrau.
3. **Eixo com FILTRO, não contagem cega** — carrega o filtro do efeito. Nusjuro milado = combustível; Five Elders milada = carta MORTA (`play_from_trash` filtra power 5000). Já custou partida.
4. **Estrutura de GARGALO (min), não soma** — reanimação = `min(acesso ao motor na mão/buscável, progresso do combustível no trash)`. Soma superestima "muito combustível, zero motor" (o bug da semana).
5. **Varredura DOS DOIS lados** — perfil do deck do oponente (via `OpponentModel`, decklist já conhecida) muda o valor do MEU estado: imunidade-trash dele → segurar remoção vale menos; aggro-rush dele → cobertura de counter vale mais desde o t1.
6. **Eixos de INVERSÃO** — `life_lte X` inverte parte da curva de pânico (tomar hit = ATIVAÇÃO, ex. Mjosgard); auto-mill = eixo negativo de deck-out. Condição sobre recurso "ruim" muda o SINAL do termo.

**Perfil vira artefato inspecionável** (1 JSON por deck): usuário lê e critica em
português sem conhecer a lista; dobra como auditoria do parser (eixo ausente =
condição não parseada).

**ARQUÉTIPO no topo (convergência com o front, feita 13/07):** o usuário nomeou
o conceito — cada deck tem seu arquétipo, e o perfil deve mapeá-lo. O
`deck_profile.py` REUSA a gramática de arquétipo do `deck_analyzer.py`
(`ACTION_WEIGHTS` × `TRIGGER_RELIABILITY`, fonte única) → o perfil abre com
`archetype: {dominante, mix%}` e os derived_axes REFINAM dentro dele. 4ª família
de eixo adicionada: **disrupção/denial** (give_don_opp, lock, rest_opp, debuff,
bounce, ko, negate — mira o oponente). Resultado universal (mesmo código, zero
nome de carta):
- **Imu** → Controle 40%/Aggro 30%/Tempo 30%; eixos: trash_staircase(968),
  disruption(664), reanimation(250), life_inversion(32).
- **Krieg** → Controle 64%; eixo disruption(227): give_don_opp×15, debuff,
  lock, rest_opp. (Antes saía VAZIO — era gramática incompleta, não deck sem
  arquétipo. LIÇÃO: perfil vazio = alerta de gramática, nunca "validação".)
- **Kid** → Vida/Triggers 39%/Aggro 29%; eixo disruption(95).

Perfis salvos: `perfil_{imu,krieg,kid}.json`. Reproduzir: `python deck_profile.py <Deck>`.
*Esforço: junto com o item 1.*

### 3. Resposta do oponente — profundidade 2 (onde a passividade morre)
Minimax no nível de LINHA DE TURNO (não por ação — ramificação explode):
top-K≈3 linhas minhas (podadas pelo score barato atual = nosso alpha-beta
pragmático) → simula o turno INTEIRO de resposta dele → avalia com
`evaluate_state`. Informação oculta: mão dele amostrada da decklist − vistas
(`OpponentModel`), S≈3 amostras, média. Oponente simulado joga com o próprio
engine em modo GULOSO (sem aninhar — evita recursão). Efeito: "ataque seco → ele
countera barato → nota ruim" vs "anexo 2 DON → passa/drena counter → nota boa".
Agressividade vira RESULTADO da busca, não regra. **Risco a vigiar:** K×S≈9
simulações por `/decide` dentro do timeout de 3s — perfilar; se estourar, reduz
K/S ao vivo, profundidade cheia só no auditor/tunagem.
*Esforço: 1 sessão.*

### 4. Defesa pela mesma régua
Counter/blocker via `eval(tomar o hit)` vs `eval(gastar counter X)` — aposenta
as curvas manuais (12/65/150/250, mão gorda). Barato, sem simulação.
*Esforço: meia sessão, depois do item 1 estabilizar.*

### 5. Tunagem automática de pesos — PIPELINE SELF-SERVICE (o "ML" útil)
**Exigência do usuário (13/07, reforçada 2×):** "toda vez que um deck novo for
adicionado no banco ele otimiza o peso sozinho". NADA de gauntlet manual — o
sistema se auto-tuna. Desenho travado:

**Registry** `deck_weights.json`: `hash(decklist) -> {profile, weights, gauntlet,
winrates, timestamp}`. O hash da lista é a chave — muda a lista, muda o hash,
re-tuna. Só isso já dá o "self-service": nada de nome de deck hardcoded.

**Gatilho (automático):** ao carregar um deck cujo hash não está no registry (ou
mudou), dispara o pipeline:
  1. `deck_profile` → perfil (eixos + arquétipo). Cacheia.
  2. **Gauntlet = o próprio banco de decks existentes** (todos os `.deck`) +
     ESPELHO (deck vs si mesmo). Sem lista curada — é "contra tudo que existe".
     Cresce sozinho conforme o banco cresce.
  3. Self-play determinístico (seed fixa, `baseline_metrics` como juiz):
     otimiza o VETOR DE PESOS dos eixos (genéricos + derivados do perfil) por
     winrate agregado no gauntlet. Ablação liga/desliga cada eixo → eixo que não
     move winrate morre; peso→0 = ruído.
  4. Cacheia os pesos por hash. (Opcional/lazy: re-tunar os decks do banco que
     enfrentam o novato — custo alto, fazer sob demanda, não a cada inserção.)

**Cold-start:** antes da tunagem terminar, o deck joga com os PRIORS do perfil
(impacto×dependentes que o `deck_profile` já calcula) — funcional na hora; a
tunagem só REFINA, offline, quando rodar.

**Sinal (do baseline, item 0):** matchup-teto (winrate >85%, ex: Imu vs Teach)
dá gradiente fraco — o otimizador pondera pelo quão contestado é o matchup
(peso maior onde 40–60%, ex: Krieg/Kid). Não exclui nenhum: o teto vira
sanity-check ("não regredir onde já ganho").

**O que é universal vs por-deck:** a `evaluate_state` e a gramática de eixos são
UMA só (universais). O que é por-deck = as SAÍDAS geradas sozinhas: o perfil e o
vetor de pesos cacheado. Zero código por deck.
*Esforço: roda offline; setup 1 sessão após o item 1. Otimizador: começar com
coordinate-ascent/CMA simples sobre poucos pesos; sem ML pesado.*

### Descartado por ora (reavaliar SÓ se 1–5 baterem teto)
- **MCTS** — sem throughput pra milhares de rollouts/decisão; info oculta vira determinized-MCTS (pesquisa).
- **Rede neural** — precisa de milhões de partidas; item 5 entrega o essencial antes. A avaliação + self-play são pré-requisitos dela de qualquer jeito → nada se perde.

### Limites honestos assumidos
- Teto da avaliação = teto do parser (condição não parseada = eixo invisível). Qualidade do parser virou qualidade da avaliação.
- Sinergias sutis (combos que não viram condição estrutural) ficam de fora — tunagem compensa parte; é aqui que MCTS/NN entrariam lá na frente.

---

## Pendências fora deste plano (não esquecer)
- **VALIDAR AO VIVO a leva 7** (Mars blocker, Never Existed no defensor, 1º/2º por curva) — usuário precisa REABRIR o jogo (DLL nova); server já no ar.
- Borderlines do auditor (2 counter-H, 1 DON ocioso).
- TODO antigo: chave Supabase exposta; flag D postura LETHAL.

## Regra de conclusão de cada etapa
Só é "feita" se a bateria baseline NÃO regredir E as métricas de passividade
moverem na direção certa. Sem impressão de partida isolada. Ver memória
[[feedback_nao_declarar_resolvido_sem_partida_real]].
