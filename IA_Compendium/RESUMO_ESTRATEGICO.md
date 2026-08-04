# ONE PIECE AI COMPENDIUM — Volume 1 (resumo estratégico)

> **Este arquivo é a referência OBRIGATÓRIA, extraída e mapeada a partir de
> `ONE_PIECE_AI_COMPENDIUM_Volume_1.docx`/`.pdf` (mesma pasta) — ver a regra
> em [`CLAUDE.md`](../CLAUDE.md#referência-estratégica-obrigatória-ia_compendium)/
> [`AGENTS.md`](../AGENTS.md). Os `.docx`/`.pdf` continuam sendo a fonte
> original (não editar aqui o conteúdo interpretativo sem conferir lá), mas
> este `.md` é a versão git-diffável/grepável que qualquer sessão deve
> consultar — os PDFs não são lidos diretamente por rotina, só quando este
> resumo não bastar.
>
> A Seção 8 abaixo (catálogo de 60 decks) foi **mapeada para códigos reais
> de carta** (`cards_rows.csv`) nesta sessão (30/07/2026) — o documento
> original só tinha nome + cor. Onde houve mais de 1 código candidato
> (mesmo nome+cor, catálogo original não desambigua), a lista de
> candidatos aparece entre colchetes — **resolva antes de usar** (não
> assuma o primeiro da lista).

Preparado para Arthur Augusto Pinto Cunha, julho de 2026. Versão do
documento original: 1.0 (13/07/2026).

## Escopo

Este volume não substitui nem reimplementa o simulador existente. É uma
camada de conhecimento estratégico e um projeto técnico pra comparar com a
arquitetura já construída (`decision_engine.py`). Fonte primária: ONE PIECE
CARD GAME Official Web Site — regras e Recommended Decks (índice salvo em
13/07/2026).

## Princípio central

O livro separa quatro coisas que costumam ser misturadas: **regras do
jogo** (o simulador garante legalidade e resolve efeitos), **estratégia
humana** (a base estratégica descreve objetivos/prioridades/exceções),
**mecanismo de busca** (compara linhas possíveis) e **aprendizado** (ajusta
estimativas com dados de partidas).

---

## 1. Como pensar estrategicamente no jogo

1. **Estado, recursos e iniciativa** — uma posição não é só Life ou nº de
   personagens: envolve mão, DON!! ativo/descansado, campo, trash,
   informação revelada, efeitos contínuos, ordem dos ataques, e a
   possibilidade de representar Counter Event. Iniciativa = obrigar o
   adversário a responder antes de executar o próprio plano.
2. **Card advantage e card quality** — mais cartas não é necessariamente
   melhor; considerar qualidade contextual, Counter disponível, busca,
   redundância e valor futuro (um Counter de 2000 pode valer mais que um
   corpo mediano perto do letal).
3. **Tempo** — quem converte DON!!/ações em pressão útil. Remover algo caro
   com uma ação barata, jogar múltiplos corpos num turno, ou forçar o
   adversário a gastar DON!! defensivamente = ganho de tempo.
4. **Pressão sobre a Life** — atacar a Life NÃO é automaticamente correto
   (pode dar carta ao adversário, ativar Trigger, ampliar defesa). Pergunta
   certa: aproxima o letal, força Counter relevante, reduz flexibilidade do
   rival, ou só melhora a mão dele?
5. **Controle de mesa** — atacar personagens cria vantagem persistente mas
   gastar ataques demais na mesa pode deixar a Life do adversário
   estabilizar. Comparar dano imediato vs redução do valor futuro do campo
   inimigo.
6. **Ordem dos ataques** — revela informação. Menores primeiro testam
   disposição a usar Counter; maiores primeiro impedem reserva de efeito
   defensivo. `[When Attacking]`, Leader effects, Blockers e DON!!
   disponível mudam a ordem ótima.
7. **DON!! aberto como informação** — tem valor efetivo E representacional
   (ameaça mesmo sem o Event na mão). Distinguir recurso realmente
   utilizável de recurso mantido só pra representar ameaça.
8. **Proteção de personagens** — correta quando o valor futuro esperado
   supera o custo de Counter gasto (novos ataques, efeitos por turno,
   sinergias, quanto restringe o adversário).
9. **Aceitar dano** — pode ser racional pra preservar Counter, buscar peças,
   aumentar a mão. Considerar distância até o letal, ataques restantes,
   risco de Double Attack/Banish, Blockers, distribuição provável de
   Counter do adversário.
10. **Condição de vitória** — cada deck deve ter condições explícitas
    (enxame/pressão, valor incremental, remoção total, combo, ramp pra
    finalizadores, controle de mão, manipulação de Life, exaustão de
    recursos). Avaliar ações pela contribuição a ESSAS condições, não por
    um score genérico isolado.

## 2. Arquétipos e comportamento esperado

| Arquétipo | Objetivo | Prioridade | Risco típico | Sinal de transição |
|---|---|---|---|---|
| Aggro | Reduzir a Life antes da estabilização | Curva, ataques eficientes, múltiplas ameaças | Esvaziar a mão cedo | Adversário entra na faixa de letal |
| Midrange | Ganhar por qualidade de mesa | Corpos eficientes e flexibilidade | Ficar atrás de controle puro | Finalizadores passam a dominar trocas |
| Control | Negar valor e vencer no late game | Remoção, mão, estabilização | Pressão inicial excessiva | Campo rival perde capacidade de reconstrução |
| Tempo | Ganhar ações enquanto pressiona | Rest, bounce, redução, ataques | Perder valor em jogo longo | Vantagem de iniciativa vira dano |
| Ramp | Acelerar DON!! pra ameaças altas | Curva de aceleração e payoff | Acelerar sem payoff | 1º turno de ameaça acima da curva |
| Combo | Reunir peças pra sequência decisiva | Busca, proteção, janela de execução | Mãos inconsistentes | Probabilidade de combo supera linha de valor |
| Swarm | Criar muitos corpos rapidamente | Eficiência por carta, buff coletivo | Remoções em área | Quantidade de ataques supera defesa |
| Stall/Defesa | Alongar a partida e negar letal | Blockers, Counter, recuperação | Não criar condição de vitória | Recursos adversários entram em exaustão |

## 3. Base de conhecimento estruturada (referência de schema, não implementado)

Camadas de confiança sugeridas: `official` (regras/carta/guia oficial),
`derived` (interpretação estratégica), `empirical` (valor estimado por
partidas simuladas/dados reais), `learned` (peso de treinamento,
versionado). Vocabulário de papéis de carta sugerido: `searcher`,
`draw_engine`, `attacker`, `finisher`, `blocker`, `counter_2000`,
`removal`, `power_reduction`, `cost_reduction`, `rest`, `freeze`, `bounce`,
`ramp`, `DON_recovery`, `life_manipulation`, `trigger_payoff`,
`trash_setup`, `recursion`, `combo_piece`, `protector`, `tech_card`.

*(Este projeto já tem `compute_game_plan`/`deck_analyzer.py`/
`deck_profile.py` — ao tocar esse código, comparar contra o schema sugerido
aqui em vez de reinventar do zero.)*

## 4. IA de alto nível sobre o simulador existente

**Limite do projeto** (citação direta): "O livro recomenda interfaces e
testes. Ele não presume como suas 100 mil linhas estão organizadas. O
Claude Code deverá mapear as interfaces recomendadas para as classes reais
e apontar incompatibilidades."

Interfaces mínimas sugeridas: `GameState`, `Observation`,
`LegalActionGenerator`, `Transition/ApplyAction`, `Clone`/`Undo`,
`TerminalEvaluator`, `Policy`, `ValueEvaluator`, `SearchController`,
`DecisionTrace`.

Busca com informação oculta: minimax puro não basta (mão/deck do
adversário são ocultos) — amostrar estados ocultos consistentes com o
histórico + buscar em cada amostra + agregar valor esperado; ou MCTS com
determinizações.

Pipeline recomendado: observação → gerar ações legais → poda heurística →
amostrar informação oculta plausível → buscar (MCTS/beam/expectimax) →
avaliar folhas/terminais → agregar valor esperado e risco → selecionar
ação → produzir `DecisionTrace`.

Função de avaliação inicial (antes de aprendizado, componentes
registrados separadamente pra depuração/explicação):

```
V(s) = w_life * life_security + w_hand * hand_quality + w_board * board_value
     + w_don * DON_efficiency + w_pressure * lethal_pressure
     + w_engine * recurring_effects + w_matchup * matchup_features
     - w_risk * opponent_counterplay
```

| Método | Vantagem | Limitação | Uso sugerido |
|---|---|---|---|
| Heurísticas | Rápidas e explicáveis | Frágeis fora dos casos previstos | Baseline e poda |
| Beam Search | Controla explosão combinatória | Pode descartar linha tardia forte | Turnos com muitas sequências |
| Expectimax | Modela respostas probabilísticas | Depende de modelo do oponente | Mão oculta e efeitos aleatórios |
| MCTS | Flexível e anytime | Simulações caras, rollout crítico | Decisão geral com orçamento variável |
| Rede de valor/política | Generaliza padrões | Exige dataset e validação | Acelerar busca após self-play |
| Híbrido | Combina conhecimento e aprendizado | Mais componentes pra manter | Recomendação principal |

## 5. Self-play e aprendizado

Ciclo: campeão joga contra (cópia atual / versões históricas / políticas
heurísticas / decks e estilos variados) → registrar (observação, máscara
de ações, política escolhida, valor previsto, resultado) → treinar
candidato → avaliar em bateria fixa → promover só se superar critérios de
força/estabilidade/diversidade.

O que registrar: `game_id`+seed, versão do simulador, versão da base
estratégica, decklists e líder, jogador inicial, estado observável
serializado, hash do estado completo, ações legais e máscara, ação
escolhida, scores das alternativas, tempo/nós consumidos, recompensa
final, motivo de término, `DecisionTrace`.

Recompensa: principal deve ser o resultado final; recompensas
intermediárias aceleram treino mas arriscam ensinar objetivo errado (ex:
valorizar mesa quando o deck deveria sacrificar recursos pro letal) — se
usadas, pequenas/auditáveis/específicas por arquétipo.

Controle de qualidade: teste de regressão de regras ANTES de qualquer
treino; avaliação cruzada entre líderes (não só mirror match); pool de
adversários históricos (evitar esquecimento catastrófico); métricas por
posição/matchup/fase; reprodução exata por seed; promoção por intervalo
de confiança, não por poucas vitórias.

## 6. IA explicável

A explicação não deve ser um texto gerado DEPOIS da jogada — nasce do
MESMO processo que escolheu a ação (mecanismo registra fatores,
alternativas, incertezas; a camada textual só converte em linguagem
clara).

```json
{
  "chosen_action": "attack_leader_7000",
  "chosen_value": 0.643,
  "alternatives": [
    {"action": "attack_character_5000", "value": 0.571},
    {"action": "play_character_X", "value": 0.533}
  ],
  "factors": [
    {"name": "counter_pressure", "impact": 0.081},
    {"name": "next_turn_lethal", "impact": 0.064},
    {"name": "trigger_risk", "impact": -0.022}
  ],
  "uncertainty": 0.18,
  "counterfactual": "se o adversário tivesse 1 carta a mais, atacar o personagem seria preferível"
}
```

Níveis de explicação: Rápida (1 frase, motivo dominante) / Treinador
(alternativas, recursos preservados, plano do próximo turno) / Técnica
(valores, incerteza, amostras, componentes) / Pós-partida (decisões com
maior perda de valor, linhas melhores).

Evitar explicações enganosas: diferença pequena entre 2 ações → dizer que
é marginal; dependência de suposição sobre a mão adversária → explicitar
a crença; busca interrompida por orçamento → indicar baixa confiança.

## 7. Checklist (comparar contra o simulador real)

- [ ] Estado clonável/revertível com segurança?
- [ ] Execução determinística com seed fixa?
- [ ] Gerador retorna TODAS as ações legais (ordem de efeitos, escolha de alvo)?
- [ ] Separação entre estado completo e observação do jogador?
- [ ] Ações com identificadores estáveis pra dataset?
- [ ] Milhares de partidas sem interface gráfica?
- [ ] Logs reproduzem uma partida exatamente?
- [ ] Testes unitários pra efeitos e regras?
- [ ] Motor suporta políticas diferentes por jogador?
- [ ] Limite de tempo/nós por decisão?
- [ ] Simulador expõe eventos suficientes pra `DecisionTrace`?
- [ ] Decklists e cartas com IDs canônicos?

## 8. Catálogo de decks (arquétipo preliminar + diretriz de IA)

> **Aviso do próprio documento**: "Os resumos abaixo são uma classificação
> inicial baseada na descrição da página oficial... Arquétipos e
> comportamento da IA são interpretações preliminares e serão refinados
> nos volumes de decks." Ou seja: **ponto de partida pra comparação, não
> verdade absoluta**. Divergência entre esta tabela e o comportamento real
> do bot pode significar bug no bot OU que esta classificação precisa de
> refinamento — registre os dois lados quando houver dúvida real.

| # | Líder (nome/cor no catálogo) | Código(s) | Arquétipo preliminar | Resumo | Diretriz inicial pra IA |
|---|---|---|---|---|---|
| 1 | Portgas.D.Ace — Vermelho | `OP16-001` ou `OP03-001` (2 candidatos, mesmo nome+cor — desambiguar antes de usar) | Aggro/pressão | Usa vínculos familiares e ritmo rápido pra consumir a Life | Priorizar curva, ataques que forçam Counter, janela de finalização |
| 2 | Monkey.D.Luffy — Verde/Azul | `OP16-022` | Tempo/Aggro | Prisioneiros de Impel Down aceleram desenvolvimento e pressão | Sequenciar corpos e efeitos pra manter iniciativa |
| 3 | Buggy — Azul | `OP16-041` ou `OP09-042` (2 candidatos) | Swarm/cheat | Constrói força pela quantidade de subordinados e convicts | Maximizar valor por carta, preservar densidade de ataques |
| 4 | Sengoku — Roxo | `OP16-060` | Ramp/Midrange | Reúne os Três Almirantes e personagens de alto custo | Acelerar DON!! sem perder estabilidade, converter em finalizadores |
| 5 | Yamato — Preto | `OP16-079` | Trash/Tempo | Personagens transformáveis atacam rápido e exploram o trash | Preparar trash, escolher momento de converter recursos em pressão |
| 6 | Marshall.D.Teach — Preto/Amarelo | `OP16-080` | Controle/Life | Atrai ataques e manipula destino/Life pra virar a partida | Aceitar dano só quando manipulação posterior superar o risco |
| 7 | Krieg — Vermelho/Verde | `OP15-001` | Controle de DON/Tempo | Manipula DON!! no campo e domina o tabuleiro | Usar controle de recursos pra ataques e remoções favoráveis |
| 8 | Lucy — Vermelho/Azul | `OP15-002` | Event/Aggro | Deck de Events com perfil ofensivo e remoção por poder | Manter Events suficientes sem sacrificar presença de mesa |
| 9 | Brook — Verde/Preto | `OP15-022` | Combo | Busca retorno dramático mesmo após o deck acabar | Proteger peças, rastrear condição de combo, evitar consumo prematuro |
| 10 | Rebecca — Azul | `OP15-039` | Low-cost swarm | Ataca repetidamente com personagens de custo 3 de Dressrosa | Gerar múltiplas ameaças, explorar eficiência por custo |
| 11 | Enel — Roxo | `OP15-058` | DON especial/Ramp | Opera com estrutura incomum de 6 DON!! e recuperação | Planejar ciclos de DON!!, evitar turnos mortos |
| 12 | Monkey.D.Luffy — Amarelo | `OP15-098` (dentro do bloco OP15; candidatos alternativos por nome+cor: `ST13-003`, `ST29-001`, desambiguar se necessário) | Life/Combo | Sky Island que coloca a própria Life em risco | Converter Life em vantagem sem entrar em alcance de letal |
| 13 | Jewelry Bonney — Vermelho/Amarelo | `EB04-001` | Leader power/Aggro | Forma Nika aumenta o poder do Líder pra vencer | Concentrar recursos em ataques decisivos, calcular Counter adversário |
| 14 | Nefeltari Vivi — Vermelho/Azul | `EB03-001` ou `OP04-001` (2 candidatos) | Rush/Power reduction | Combina Rush com redução de poder | Reduzir alvos pra remover enquanto mantém dano no Líder |
| 15 | Trafalgar Law — Vermelho | `OP14-001` | Toolbox/Tempo | Manipula o poder dos aliados com Chambres | Escolher alvos que transformem efeitos de poder em vantagem de ações |
| 16 | Dracule Mihawk — Verde | `OP14-020` | Rest/Tempo control (refinado, ver §10) | Efeito do Líder gira em torno de DESCANSAR cartas (próprias E do oponente), não remover — "corta o campo" do resumo original é impreciso | Planejar ativação do Líder junto com o pacote de rest próprio/travas no oponente (ver §10 pra decklist e linhas de jogo reais) |
| 17 | Jinbe — Azul | `OP14-040` | Aggro | Ataques grandes e ritmo ofensivo | Priorizar dano e desenvolvimento que mantenha mão suficiente |
| 18 | Boa Hancock — Azul/Amarelo | `OP14-041` | Trigger/Value | Explora Trigger e flexibilidade de duas cores | Modelar probabilidades de Trigger, manipular Life quando possível |
| 19 | Donquixote Doflamingo — Roxo | `OP14-060` | Defesa/Controle | Amarra o oponente em um plano defensivo | Negar ataques eficientes, vencer por vantagem acumulada |
| 20 | Crocodile — Preto | `OP14-079` | Cost control | Reduz custo e usa Baroque Works pra remoção | Sincronizar redução de custo com K.O., não desperdiçar peças |
| 21 | Gecko Moria — Preto/Amarelo | `OP14-080` | Trigger/Recursion | Triggers revivem personagens | Preparar trash e Life pra maximizar ressurreições |
| 22 | Monkey.D.Luffy — Vermelho/Verde | `OP13-001` (bloco OP13; candidatos alternativos: `OP01-003`, `ST30-001`) | Defesa/FILM | Manipula DON!! e se especializa em defesa | Equilibrar proteção com transição pra contra-ataque |
| 23 | Portgas.D.Ace — Vermelho/Azul | `OP13-002` | Hand burn/Midrange | Converte dor e mão em resistência e pressão | Controlar consumo de mão pra não perder opções no late game |
| 24 | Gol.D.Roger — Vermelho/Roxo | `OP13-003` | Ramp/Finisher | Usa personagens de poder extremamente alto | Acelerar até ameaças finais, calcular turnos de exposição |
| 25 | Sabo — Vermelho/Preto | `OP13-004` (bloco OP13; candidato alternativo: `OP05-001`) | Late-game midrange | Fortalece aliados de custo alto e cresce no fim | Sobreviver ao início, proteger ameaças que acumulam valor |
| 26 | Imu — Preto | `OP13-079` | Trash control | Manipula o trash de forma incomum | Tratar trash como recurso, negar recursão adversária |
| 27 | Jewelry Bonney — Amarelo | `OP13-100` | Trigger/Egghead | Aposta na força de Trigger | Avaliar risco da Life, manter linhas alternativas sem Trigger |
| 28 | Yamato — Verde/Amarelo | `OP06-022` | Starter upgrade | Versão reforçada por Premium Boosters | Identificar novas peças, recalibrar curva e consistência |
| 29 | Marshall.D.Teach — Preto | `OP09-081` | Starter upgrade | Aprimoramento do deck de Teach | Preservar identidade de negação, aumentar eficiência |
| 30 | Monkey.D.Luffy — Roxo/Preto | `OP09-061` | Starter upgrade/Ramp | Melhora uso de DON!! e cartas Straw Hat | Acelerar com segurança, converter em presença de alto custo |
| 31 | Buggy — Azul | `OP16-041` ou `OP09-042` (mesmo par ambíguo da linha 3) | Starter upgrade | Reforça o plano de subordinados e personagens grandes | Avaliar quando desenvolver largo ou guardar pra cheat |
| 32 | Jewelry Bonney — Verde | `OP07-019` | Starter upgrade/Defense | Reforça controle de descanso e defesa | Usar DON!! pra impedir ataques decisivos, ganhar tempo |
| 33 | Shanks — Vermelho | `OP09-001` | Starter upgrade/Midrange | Melhora equilíbrio ofensivo e defensivo | Trocar de postura conforme a mão e o estado do campo |
| 34 | Koala — Preto/Amarelo | `OP12-081` | Revolutionary/Control | Protege fracos e enfrenta personagens fortes | Converter diferenças de custo/poder em remoções eficientes |
| 35 | Donquixote Rosinante — Roxo/Amarelo | `OP12-061` | Protection/Character | Protege Trafalgar Law, foco em personagens | Priorizar sobrevivência da peça central e valor recorrente |
| 36 | Kuzan — Azul | `OP12-040` | Hand control | Navy focado em manipular a mão | Pressionar quantidade e qualidade da mão adversária |
| 37 | Sanji — Azul/Roxo | `OP12-041` | Event/Technique | Event deck com técnicas variadas | Manter flexibilidade, selecionar o Event de maior impacto contextual |
| 38 | Silvers Rayleigh — Vermelho | `OP12-001` | Event/Aggro | Haki e Events em ritmo acelerado | Transformar Events em tempo sem ficar sem corpos |
| 39 | Roronoa Zoro — Verde | `OP12-020` | Swordsmen/Tempo | Corta personagens e Líderes com espadachins | Explorar descanso e ataques eficientes em alvos vulneráveis |
| 40 | Katakuri — Roxo | `OP11-062` | Information/Control | Observation Haki antecipa movimentos | Usar informação pra reduzir incerteza, otimizar sequência |
| 41 | Koby — Vermelho/Preto | `OP11-001` | Navy/Midrange | Combina pressão e disciplina da Marinha | Balancear redução/remoção com ataques de alto poder |
| 42 | Shirahoshi — Verde/Amarelo | `OP11-022` | Cheat/Board | Coloca Neptunians poderosos em campo | Preparar condição de invocação, proteger payoff |
| 43 | Jinbe — Verde | `OP11-021` | Active/Rest control | Controla cartas ativas e descansadas | Negar ações, criar ataques seguros em personagens |
| 44 | Nami — Azul/Amarelo | `OP11-041` | Draw/Defense | Constrói mão e defesa estável | Valorizar cartas, sobreviver, evitar overdraw sem propósito |
| 45 | Monkey.D.Luffy — Azul/Roxo | `OP11-040` | Deck manipulation/Ramp | Manipula topo e traz personagens grandes, acelerando DON!! | Preparar topo, acelerar, executar combos no turno correto |
| 46 | Monkey.D.Luffy — Verde/Roxo | `EB02-010` | Straw Hat/Midrange | Celebra várias fases do anime com tripulação | Usar sinergias amplas, adaptar a curva |
| 47 | Trafalgar Law — Verde/Amarelo | `OP10-022` | Life combo/Control | Manipula Life pra jogar personagens e controlar campo | Planejar Life como zona de recurso e combo |
| 48 | Eustass Kid — Amarelo | `OP10-099` | Defense/Blocker | Concede Blocker, constrói defesa impenetrável | Distribuir proteção, identificar quando abandonar defesa pra atacar |
| 49 | Usopp — Azul/Preto | `OP10-042` | Dressrosa control | Resiste e protege cartas Dressrosa | Manter peças-chave, remover ameaças, vencer por valor |
| 50 | Sugar — Vermelho/Roxo | `OP10-003` | Counter/Ramp | Aumenta defesa e controla campo enquanto acelera DON!! | Guardar Counter suficiente, usar ramp pra virar postura |
| 51 | Caesar Clown — Vermelho/Azul | `OP10-002` | Removal | Punk Hazard especializado em remoção | Reduzir poder, escolher ameaças que geram maior swing |
| 52 | Smoker — Vermelho/Verde | `OP10-001` | High-power tempo | Ataca repetidamente com alto poder e recupera DON!! | Sequenciar recuperação pra multiplicar ataques eficientes |
| 53 | Marshall.D.Teach — Preto | `OP09-081` (mesmo código da linha 29 — provável duplicata do catálogo original, ou 2 páginas oficiais diferentes pro mesmo líder) | Effect denial/Control | Nega efeitos On Play | Avaliar quais efeitos merecem negação, quando desenvolver mesa |
| 54 | Nico Robin — Roxo/Amarelo | `OP09-062` | Banish/Life pressure | Ataca mão e Life com Banish | Selecionar ataques que negam compras, comprimem recursos |
| 55 | Monkey.D.Luffy — Roxo/Preto | `OP09-061` (mesmo código da linha 30 — idem) | DON utilization/Ramp | Extrai valor máximo do DON!! com Straw Hats | Planejar curva, evitar retorno negativo de DON!! |
| 56 | Buggy — Azul | `OP16-041` ou `OP09-042` (mesmo par ambíguo das linhas 3/31) | Cheat high-cost | Usa subordinados e coloca personagens de custo 10 | Chegar ao payoff sem perder tempo, manter consistência |
| 57 | Shanks — Vermelho | `OP09-001` (mesmo código da linha 33 — idem) | Balanced midrange | Combina ataque e defesa com Haki | Ajustar postura, usar poder pra neutralizar ataques |
| 58 | Lim — Verde/Roxo | `OP09-022` | ODYSSEY tempo | Deck rápido com personagens ODYSSEY | Usar sinergia tribal pra ganhar ações |
| 59 | Tony Tony.Chopper — Vermelho/Verde | `OP08-001` | Animal swarm | Chama muitos aliados e ataca em grupo | Maximizar quantidade de corpos e buffs coletivos |
| 60 | Marco — Vermelho/Azul | `OP08-002` | Removal/Hand control | Combina K.O. vermelho e manipulação de mão azul | Criar vantagem dupla: remover mesa e limitar reconstrução |

**Nota sobre as linhas 29/53, 30/55, 33/57** (mesmo código repetido no
catálogo original): o documento fonte lista esses líderes 2x com resumos
levemente diferentes — pode ser 2 páginas oficiais distintas pro mesmo
líder (ex: página do deck base + página de "upgrade") que acabaram
mapeando pro mesmo código no nosso banco, ou um erro de catalogação do
volume original. Não investigado a fundo nesta sessão — sinalizado aqui
pra quem for usar essas linhas numa auditoria real.

## 9. Próximo volume (não existe ainda)

"Cada página oficial será convertida em uma ficha completa com decklist,
curva, cartas-chave, plano de jogo, sequências, regras, exceções e JSON.
Informações não presentes no guia oficial serão identificadas como análise
derivada. Matchups e pesos numéricos só serão classificados como empíricos
quando houver dados ou simulações suficientes." — ainda não recebido/lido
nesta sessão (30/07/2026). Se chegar, atualizar este arquivo e a regra em
`CLAUDE.md`/`AGENTS.md`.

## 10. Fontes externas — deck guides da comunidade

> **Camada de confiança**: distinta de `official`/`derived`/`empirical`/
> `learned` (seção 3) — isto é fonte **`community`**, escrita por
> jogadores competitivos (não Bandai, não este projeto). Útil pra
> entender plano de jogo/linhas reais com mais profundidade que o
> catálogo da seção 8 (que é só arquétipo+1 frase), mas sujeito a viés
> de autor/meta local. Adicionado a pedido do usuário (04/08/2026),
> depois de investigação real do matchup Imu-vs-Mihawk apontar que o
> resumo da seção 8 pra Mihawk era impreciso. Fetch direto do site
> (`cardsrealm.com`) bloqueado pela política de rede das sessões
> remotas deste projeto — conteúdo abaixo foi colado pelo usuário
> diretamente na conversa, não lido pela IA via ferramenta de web.
> **Plano**: usuário quer expandir esta seção com mais líderes/decks do
> mesmo site conforme forem necessários — seguir o mesmo template
> (fonte+data+URL, resumo do plano por fase, decklist real quando
> disponível, comparação com o deck usado em `decklists_raw.csv` se
> houver).

### Dracule Mihawk (OP14-020) — Verde

- **Fonte**: Cards Realm, "Guia de Deck OP15: Dracule Mihawk", Pedro
  Braga (revisão Tabata Marques), publicado 21/04/2026.
  <https://onepiece.cardsrealm.com/pt-pt/articles/guia-de-deck-op15-dracule-mihawk>
- **Líder**: `OP14-020`, Verde, 5000 poder, 5 vidas, atributo Slash
  (+1000 poder contra líder com atributo Slash). Habilidade: 1x/turno,
  ao virar (rest) uma carta própria — personagem, Stage ou DON!! —, SE
  houver personagem de custo 5+ em campo, ativa até 3 DON!!, depois não
  pode jogar personagens naquele turno.
- **Arquétipo real (corrige a linha 16 da seção 8)**: não é remoção de
  mesa ("corta o campo"). É um deck de **rest/tempo control**
  construído em torno de GOSTAR de virar cartas — tanto as próprias
  (o líder, e peças como Laboon OP15-035/Tashigi OP14-029 que
  convertem "virar 1-2 cartas" em proteção pro board) quanto as do
  oponente (Jewelry Bonney OP07-026, Carrot OP08-023, Hody Jones
  OP06-035, Trafalgar Law OP13-031, Shanks OP14-027, Dracule Mihawk
  OP14-119, Law & Bepo ST24-004 — todos travam/descansam peças
  adversárias, sem K.O.). O plano não é "esvaziar o campo do
  oponente", é "negar as ações dele enquanto o líder converte o
  próprio descanso em mais DON!! e pressão".
- **Linhas de jogo por fase**:
  - **Early**: buscar consistência (Jewelry Bonney ST02-007, Perona
    OP12-034, Kid & Killer ST24-002) — prioridade é garantir a peça de
    custo 5+ que liga o líder pros turnos seguintes, não pressão
    imediata.
  - **Mid**: travar a mesa do oponente (Jewelry Bonney OP07-026,
    Carrot OP08-023) pra atacar a cara sem reação; Smoker OP10-030
    ativa DON!! sem perder ritmo; Trafalgar Law OP13-031 recicla
    searchers/reorganiza mão e campo.
  - **Late**: fechadores que reforçam a MESMA lógica (não mudam de
    plano) — Shanks OP14-027 (trava alvo ao ser virado + debuff geral
    no turno do oponente), Dracule Mihawk OP14-119 (trava peça +
    defesa via descarte), Law & Bepo ST24-004 (trava + buff se oponente
    tem descansados), Hody Jones OP06-035 (Rush 8000, descansa
    personagens/DON!! do oponente ao entrar — o "finalizador" que pula
    defesas).
- **Decklist citada no guia** (Jc Samson, campeão de torneio nas
  Filipinas): 4 Laboon OP15-035, 4 Perona OP12-034, 3 Scratchmen Apoo
  EB01-015, 1 Jewelry Bonney ST02-007, 4 Kid & Killer ST24-002, 3
  Tashigi OP14-029, 2 Jewelry Bonney OP12-118, 2 Smoker OP10-030, 3
  Carrot OP08-023, 2 Jewelry Bonney OP07-026, 3 Trafalgar Law OP13-031,
  2 Shanks OP14-027, 1 Hody Jones OP06-035, 2 Dracule Mihawk OP14-119,
  4 Law & Bepo ST24-004; eventos: 3 "I Know You're Strong...", 2 Demon
  Aura Nine Sword Style, 2 The Billion-fold World Trichiliocosm; stage:
  1 Coffin Boat OP14-039.
- **Comparação com o deck usado no gauntlet** (`decklists_raw.csv`,
  "Green Mihawkby Phi Nguyen", usado nos blocos 433-435): MESMO núcleo
  (Perona x4, Kid & Killer x4, ambas Jewelry Bonney OP07-026/ST02-007,
  Tashigi, Trafalgar Law, Shanks, Dracule Mihawk OP14-119 x2, Law &
  Bepo x4, Carrot, Coffin Boat, os mesmos 2 eventos principais) —
  confirma que o deck usado no self-play É uma lista competitiva real
  do mesmo arquétipo, não uma lista fraca/atípica. Difere em tech
  slots: falta Laboon (proteção) e Smoker/Hody Jones (habilitador de
  DON!!/fechador), tem no lugar Karmic Punishment, Roronoa Zoro
  PRB02-006 (SP), Paradise Waterfall, Spiderweb — uma variante real de
  outro jogador (Phi Nguyen), não a mesma lista exata do guia.
- **Implicação pra auditoria do bot** (não investigado ainda, próximo
  passo se for continuar esta linha): o motor precisa diferenciar
  "descansar personagem do oponente" (tempo, reversível no refresh
  dele) de K.O./remoção permanente ao avaliar o valor de efeitos como
  os de Carrot/Jewelry Bonney/Hody Jones, e o replay verbose do bloco
  435 não checou especificamente se o Imu reconhece e reage a esse tipo
  de trava (só confirmou que o DON por ataque já está saudável
  pós-fix). Fica como possível próxima investigação, não uma conclusão
  fechada.
