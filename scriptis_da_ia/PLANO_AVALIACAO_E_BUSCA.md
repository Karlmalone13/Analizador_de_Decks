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

---

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
condição não parseada) e futuro conteúdo do analisador do front-end
(`deck_analyzer.py` — mesma família de sinal, convergir depois).
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

### 5. Tunagem automática de pesos (self-play) — o "ML" útil
Otimiza os pesos da `evaluate_state` por winrate em milhares de partidas
determinísticas contra um GAUNTLET. Ablação liga/desliga cada eixo (mesma
bateria de seeds) → eixo que não move winrate é descartado pelo sistema, não
por debate; peso→0 = termo é ruído. Pesos cacheados por hash do deck; deck novo
joga com priors (impacto×proximidade) e tuna offline depois.
**DECISÃO PENDENTE DO USUÁRIO:** gauntlet = Teach BY, Krieg RG, Kid Y (os que
ele pilota) + espelho? Quanto mais variado, menos overfit.
*Esforço: roda offline; setup 1 sessão após o item 1.*

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
