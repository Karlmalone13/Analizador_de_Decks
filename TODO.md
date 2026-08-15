# TODO — Analisador de Decks OPTCG

**Última atualização:** 15 de agosto de 2026

> 15/08/2026 (bloco 536): **2ª fonte de não-determinismo achada e
> corrigida** em `audit_real_losses.py` — fixar `random.seed()` só
> uma vez antes de CADA chamada de `audit_one_game` (fix do bloco 534)
> não bastava: o motor consome quantidade DIFERENTE de `random.*`
> (Monte Carlo, desempate) dependendo de quais flags de calibragem
> estão ligadas, então o RNG global driftava entre OFF/ON a partir do
> 1º turno com decisão diferente, contaminando a mão embaralhada dos
> turnos SEGUINTES do mesmo jogo. Fix: reseed determinístico por
> (arquivo, turno). Script `compare_human_vs_engine.py` (scratchpad,
> nunca commitado) recriado como `audit_curve_calibration_flags.py`
> (permanente). **Resultado, agora nas 66 partidas disponíveis (não
> só 10)**: 46/307 turnos divergentes (**15.0%**, determinístico/
> reproduzível). Leitura qualitativa mista — achou 1 exemplo claro de
> linha melhor com a calibragem ligada (dano real vs ataque bloqueado)
> e 1 exemplo pior (evento que não achou nada vs personagem que
> achou). **Limitação**: comparação é por TEXTO da narrativa, não por
> ação estruturada — parte da divergência pode ser diferença de LOG,
> não de decisão real (ex: mesmo attach de DON gerando texto
> diferente). **Pendente**: refinar pra comparação semântica antes de
> confiar no número; decidir se vale ir atrás de validação real
> (self-play já mostrou ser ruidoso demais, blocos 528/529) ou só
> telemetria ao vivo; decisão de manter/reverter `is_closing_mode`
> (bloco 534) continua sem resposta do usuário. Ver bloco 536 do
> HANDOFF.

> 14/08/2026 (bloco 535): **bug real corrigido em `audit_real_losses.
> py._find_real_deck`** — fallback genérico (quando o líder não tem
> decklist real no banco) gerava deck de **0 CARTAS** para 65/141
> líderes (46%, cor armazenada com espaço em vez de "/", ex: Marshall
> D. Teach). Corrigido (regex separa por "/" ou espaço, casa por cor
> individual). Impacto medido: re-rodando o teste de 10 partidas reais
> (vitórias do humano) do bloco 534, divergência entre flags OFF/ON
> sobe de 8/75 (11%) para **24/75 (32%) dos turnos** — a conclusão
> anterior era em parte artefato do bug (3 partidas com Teach estavam
> reconstruídas com deck vazio). Pendente: investigar a fundo os 24
> turnos divergentes agora revelados antes de decidir sobre `is_
> closing_mode`/as flags de calibragem dinâmica. Ver bloco 535 do
> HANDOFF.
>
> 14/08/2026 (bloco 534): **`is_closing_mode` implementado, mas a
> evidência que motivou ele estava contaminada** — auditoria de
> partida real humano x bot (humano venceu, `audit_real_losses.py`
> reaproveitado do lado do humano) achou 3 turnos onde a calibragem
> dinâmica parecia mudar decisão; corrigi um bug de seed não-fixada no
> script de comparação e, re-rodando corretamente, **as 9 flags não
> mudam NENHUMA decisão real nessa partida** — os 3 turnos "divergentes"
> eram ruído do teste, não efeito do código. `is_closing_mode` (deck
> controle vira agressivo quando oponente tem vida<=3) fica implementado
> e testado — é logicamente defensável por conta própria — mas a
> justificativa original não se sustentou. **Pergunta feita ao usuário
> (manter ou reverter) ainda pendente de resposta** nesta sessão. Lição
> registrada: `audit_real_losses.py` tem uma fonte de não-determinismo
> (`_remaining_deck`) que exige `random.seed()` fixa antes de CADA
> chamada comparada — não coberta pelo `PYTHONHASHSEED=0` já usado nos
> scripts de self-play. Ver bloco 534 do HANDOFF.
>
> 14/08/2026 (bloco 533): **reinvestigação dos 3 termos "universais"
> restantes** (pedido: "investigue de novo para aver se não tem razão
> mesmo") — `counter_hand`/`coverage` são proxies de sobrevivência
> (mesma direção de `life_value_curve_scale_self`), `opp_blocker` é
> obstáculo pro plano de dano (mesma direção de `board_value_curve_
> scale`). Reusam os métodos já existentes, zero código novo — só 3
> flags novas (`False`). 6 testes novos, `smoke_fast`/`smoke_test`
> 100%. **TODOS os 17 termos de `EVAL_WEIGHTS` agora variam por deck**
> de alguma forma — fecha o pedido de "calibragem dinâmica pro motor
> inteiro". Tudo desligado, pendente validação via telemetria real
> (não self-play, achado 528/529: ruidoso demais pra efeitos pequenos
> por termo). Ver bloco 533 do HANDOFF.
>
> 14/08/2026 (bloco 532): **`dmg_value_curve_scale`** (pedido: "acho
> que dmg tb influência se o deck for agro") — mesma família analítica
> dos blocos 530/531. Agressivo=1.3 (dano é o plano), controle=0.7
> (dano secundário). `dmg` é o peso mais calibrado/sensível do motor
> (120→270 em sessão anterior) — não mexi no valor base, só multiplico
> por um fator atrás de `USE_DMG_VALUE_CURVE_SCALE` (nova, `False`).
> 6 testes novos, `smoke_fast`/`smoke_test` 100%. **Estado consolidado
> (529-532)**: 12 dos 17 termos de `EVAL_WEIGHTS` agora variam por
> deck (6 novos + 6 já dinâmicos de antes). Restam `counter_hand`/
> `coverage`/`opp_blocker` universais. Tudo desligado, pendente
> validação real. Ver bloco 532 do HANDOFF.
>
> 14/08/2026 (bloco 531): **completa o levantamento de calibragem
> dinâmica analítica** (pedido: "Hand first dá, valor do board tb e
> valor da vida tb") — `hand_value_curve_scale`/`board_value_curve_
> scale`/`life_value_curve_scale_self`/`_opp`, mesma família do
> `don_field_curve_scale` (bloco 530), reusando `deck_profile_type()`.
> Vida é ASSIMÉTRICA por design (controle valoriza mais a própria vida,
> agressivo valoriza mais a vida do oponente). 3 flags novas e
> separadas (`USE_HAND_VALUE_CURVE_SCALE`/`USE_BOARD_VALUE_CURVE_SCALE`/
> `USE_LIFE_VALUE_CURVE_SCALE`, todas `False`) — mesma cautela do
> `don_field` (esses termos já têm peso ativo em produção). 15 testes
> novos, `smoke_fast`/`smoke_test` 100%. **Estado consolidado**: 5
> termos com escala analítica nova + 6 já dinâmicos de antes = 11 dos
> 17 termos de `EVAL_WEIGHTS` variam por deck; restam `dmg`/`counter_
> hand`/`coverage`/`opp_blocker` como constante universal (sem sinal
> estrutural levantado ainda). Tudo desligado por padrão, pendente
> validação via telemetria real. Ver bloco 531 do HANDOFF.
>
> 14/08/2026 (bloco 530): **`don_field_curve_scale`** — 2º eixo de
> calibragem dinâmica analítica (pedido: "vamos fazer para o motor
> inteiro"). Levantamento de `EVAL_WEIGHTS`: 6 termos já são dinâmicos
> por deck (de sessões anteriores), `don_field` foi o próximo candidato
> claro (curva baixa = guardar DON vale menos; curva alta = vale mais),
> reusando `deck_profile_type()` já existente (dados reais do
> Limitless, não self-play). `dmg` ficou de fora — peso mais sensível/
> calibrado do motor, risco alto sem necessidade clara. Atrás de flag
> nova `USE_DON_FIELD_CURVE_SCALE=False` (diferente do `leader_plan_
> alignment`: `don_field` já tem peso ativo em produção, então a escala
> mudaria comportamento ao vivo imediatamente sem o flag). 6 testes
> novos, `smoke_fast`/`smoke_test` 100%. Ver bloco 530 do HANDOFF.
>
> 14/08/2026 (bloco 529): **`_leader_ability_centrality`**
> — resposta ao pedido do usuário ("aumentar o N não vai resolver...
> precisamos de algo pra fazer com precisão essa calibragem dinâmica").
> Em vez de caçar 1 peso global via self-play (ruidoso porque a resposta
> certa VARIA por deck), novo fator estrutural `[0.3..1.0]` derivado da
> composição real do deck (`full_deck_census`, já computado, zero custo
> de simulação) escala `leader_plan_alignment` pela ESCASSEZ de outras
> fontes do mesmo recurso (ex: habilidade de compra vale mais num deck
> sem outros buscadores). 5 testes novos, `smoke_fast`/`smoke_test`
> 100%. Sanity check leve (N=20, 1 candidato) rodando — não é mais
> busca de peso ótimo por força bruta, só confirmação de que o
> mecanismo estrutural não regride antes de aceitar um valor
> conservador. Ver bloco 529 do HANDOFF.
>
> 14/08/2026 (bloco 528): **1a calibração isolada do
> `leader_plan_alignment` (bloco 527) FALHOU** (maximin=-0,200/-0,150
> nos 2 candidatos testados) — Vivi (EB03-001) foi o único líder que
> regrediu nos dois, e é o único ancora com custo `rest_self`. Causa
> raiz: dar crédito parcial (0.5) só por "pronta pra ativar" ignorava
> que `rest_self` resta o líder — ativar e atacar viram mutuamente
> exclusivos, então "pronta mas ainda não decidiu" não é um estado bom
> por si só (diferente de `rest_don`, que não resta o líder). **Fix
> aplicado**: `rest_self` só ganha crédito (1.0) quando de fato
> USADA, nunca crédito parcial por estar só pagável. Testes ajustados,
> `smoke_fast`/`smoke_test` 100%. Recalibrando com o fix — resultado
> pendente. Ver bloco 528 do HANDOFF.
>
> 14/08/2026 (bloco 527): **achado real sobre a causa do
> "bot joga bem só com Imu/Teach"** — `tune_weights.py`/`eval_weights.json`
> (o vetor de pesos GLOBAL, usado por todo deck) foi calibrado quase
> inteiramente jogando como Imu (10/11 rodadas salvas usam gauntlet
> `Imu_v_X`; `baseline_metrics.py` tem "Imu vs Teach BY" como default do
> projeto inteiro) — nunca passou pelo padrão multi-âncora que o resto do
> projeto usa. Plano de 2 partes com o usuário: (1) recalibrar com
> gauntlet rotacionado por arquétipo (ainda não iniciado); (2) **termo
> novo `leader_plan_alignment`** em `EVAL_WEIGHTS` (generaliza
> `wincon_ready` pra QUALQUER líder com `[Activate: Main]`, não só o
> eixo bottleneck do perfil do deck) — implementado, testado
> (9 checks novos, `smoke_fast`/`smoke_test` 100%), **prior 0.0 (SEM
> efeito em produção ainda)**. Calibração ISOLADA (pedido do usuário,
> antes de misturar com os perfis por arquétipo) rotacionando 4 líderes-
> âncora (Mihawk/Vivi/Sanji/Imu, cobrindo os tipos de custo `rest_don`/
> `rest_self`/genérico) contra 2 oponentes fixos — **rodando quando o
> container reiniciou, resultado pendente pra próxima sessão**. Ver
> bloco 527 do HANDOFF.
>
> 14/08/2026 (bloco 526): **REVERTE a fase 1 também** —
> `USE_CHEAP_LAYER_SHORTLIST` voltou pra `False`. Motivo: sinal REAL de
> partida ao vivo (usuário testou no próprio PC — "a bot passou a jogar
> pior que antes") anula a conclusão do bloco 525 ("só a fase 1
> continua válida"), porque essa conclusão veio só de self-play. Volta
> ao estado de decisão de ANTES do bloco 508 inteiro — heurística pura,
> sem nenhum alargamento de shortlist da camada barata.
> `smoke_fast`/`smoke_test` 100% após o revert. **Pondering**
> (`OPTCG_PONDER_ENABLED`) confirmado deixado de lado — já OFF por
> padrão, decisão foi manter o código dormente (não remover): já é
> seguro, não foi a causa da piora relatada, e um revert cirúrgico
> multi-arquivo teria custo/risco maior que valor — mas **provavelmente
> carrega o mesmo bug de GIL que o `main` já achou e reverteu** (thread
> Python não dá paralelismo real, compete com `/decide` e causa
> timeout) se algum dia for ligado; não ligar sem migrar pra
> `multiprocessing` primeiro. **Nenhum mecanismo do arco 508-526 roda
> em produção agora** — todos ficam no código, testados, exigindo nova
> validação AO VIVO (não só self-play) antes de religar qualquer um.
> **Próximo passo pedido pelo usuário**: repensar calibragem dinâmica
> pra generalizar entre decks desde o zero, informado pelos 4-5
> fracassos de hoje E pela lição de que self-play sozinho não é
> suficiente pra validar. Ver bloco 526 do HANDOFF.
>
> 13/08/2026 (bloco 525): **FECHA o arco inteiro de "calibragem
> dinâmica"** (blocos 508-525) — as 4 tentativas pós-fase-1 foram
> TODAS descartadas, medidas com o mesmo rigor de sempre (multi-âncora,
> maximin): (1) ajuste dinâmico de peso — `maximin` negativo; (2)
> escalar a camada barata pra milhares — neutro (`soma=+0,033`), não
> compensa o custo; (3) GATE (pular busca cara quando a camada barata
> fica confiante) — melhorou após corrigir um viés real (play vs
> attack) mas nenhum limiar passou; (4) busca real com centenas de
> amostras — nem melhora winrate (`maximin=-0,083`) nem é viável em
> custo (20-40x mais lento, 123-278s/partida). **Estado final**: só a
> fase 1 original (`CHEAP_LAYER_SAMPLES=40`, com a profundidade de
> sequência do bloco 521/523 já com viés corrigido) continua ativa em
> produção — exatamente como validado antes desta sessão. Os 4
> mecanismos experimentais ficam no código (documentados/testados,
> flags `False`) pra não precisar reimplementar do zero no futuro, mas
> nenhum deve ligar sem repetir a medição. Ver bloco 525 do HANDOFF.
>
> **Log real adicionado ao banco**: partida humano-vs-humano
> (Karlmalone/Rocks D. Xebec x AcesWife/Charlotte Linlin, 15 turnos,
> compartilhada pelo usuário). **Achado de infraestrutura**: arquivo
> de upload encolheu sozinho de 75KB pra 117 bytes 2x seguidas (bug do
> ambiente, não do log) — recuperado via `_p2.log` que `parse_combat_
> log.py` já tinha salvo. Achado um bug real (não corrigido ainda) em
> `split_multigame_log`: trata QUALQUER linha "Version is" como início
> de nova partida, mas ela aparece 2x por partida normal (1x por
> jogador conectando) — precisa de critério mais específico. Registrado
> pra próxima sessão corrigir.

> 13/08/2026 (bloco 524, EM ANDAMENTO): re-teste do GATE (correção do
> viés play/attack do bloco 523) — os 3 limiares AINDA regridem
> (`maximin=-0,133/-0,267/-0,067`), melhor que antes mas nenhum passa
> (limiar 15 chegou mais perto, `soma=+0,033`). **Pivot do usuário**:
> em vez de insistir na camada barata (aproximação), reusar a BUSCA
> REAL de sempre (`_select_action_via_search`, zero motor novo) com
> piso/teto de amostras bem maiores (centenas, não 3-6) — testa
> isolado antes de reviver ajuste de peso em cima (já descartado nos
> blocos 513-515 com sinal fraco). Implementado `USE_DEEP_REAL_SEARCH`
> (OFF por padrão) + constantes de amostra (100/300/50).
> `smoke_fast`/`smoke_test` 100%. **Comparação exploratória rodando em
> segundo plano, resultado ainda não saiu**. Ver bloco 524 do HANDOFF.

> 13/08/2026 (bloco 523, EM ANDAMENTO): calibração do limiar do GATE
> (bloco 522) mostrou os 3 valores testados (3,0/8,0/15,0) TODOS
> regredindo produção. Investigada a causa: `_cheap_playout_deltas`
> só encadeava jogadas 'play' nos passos seguintes, nunca 'attack' —
> viés sistemático a favor de "jogar mais carta" sobre "atacar agora".
> **Corrigido**: cada passo agora compara 'play' e 'attack' na MESMA
> escala (delta ponderado por `EVAL_WEIGHTS`, não `board_value()` cru).
> Custo subiu ~2,6x (esperado, agora avalia todos os candidatos por
> passo). `smoke_fast`/`smoke_test` 100%. **Re-validação dos mesmos 3
> limiares com a correção EM ANDAMENTO**, resultado ainda não saiu.
> Ver bloco 523 do HANDOFF.

> 13/08/2026 (bloco 522, EM ANDAMENTO): sinal barato mais confiante
> (samples=1000/depth=8) usado pra ALARGAR o shortlist da fase 1
> original **regride** produção (`maximin=-0,050`) — orçamento da
> busca cara offline é apertado demais pra receber mais candidatas
> sem perder precisão. Pedido do usuário pra simplificar: novo modo
> **GATE** (`USE_CHEAP_LAYER_GATE`, `False` por padrão) — só pula a
> busca cara quando a simulação barata já está confiante (gap grande
> entre a 1ª e 2ª candidata), senão cai no fluxo de sempre sem
> alargar. Implementado, testado (`smoke_fast`/`smoke_test` 100%),
> **mas o limiar de confiança (`CHEAP_LAYER_GATE_THRESHOLD=50.0`)
> ainda não foi calibrado nem validado com o protocolo completo**.
> Próxima sessão: terminar a calibração do limiar e validar com
> matchups multi-âncora antes de decidir se liga por padrão. Ver
> bloco 522 do HANDOFF.

> 13/08/2026 (bloco 521): **EXCEÇÃO EXPLÍCITA a REGRA_SEM_DUPLICACAO,
> autorizada pelo usuário** ("Pode abrir uma exceção dessa vez dessa
> regra, se não não vamos avançar"), depois de eu propor uma alternativa
> mais segura e o usuário preferir a exceção mesmo assim. Motivo: a
> camada barata só olhava 1 ação isolada — não é uma simulação de
> verdade (sem sequência de jogadas), por isso mais amostra nunca
> ajudava. `_cheap_playout_deltas` (novo, `decision_engine.py`) encadeia
> até 4 jogadas 'play' fictícias gulosas, respeitando DON restante —
> escopo deliberadamente restrito e documentado (só 'play', não
> rastreia alvo de remoção repetido). Custo medido: 3000 amostras com
> sequência = 42,8ms/decisão, ainda muito mais barato que 1 amostra da
> busca real (~3,7ms). 3 testes novos, `smoke_fast`/`smoke_test` 100%.
> **Em andamento**: re-rodando a comparação de 3 vias do bloco 520 com
> essa profundidade nova. Resultado em bloco separado. Ver bloco 521 do
> HANDOFF.

> 13/08/2026 (bloco 520): **Modo experimental `CHEAP_LAYER_DECIDES_
> ALONE` implementado** — comparação de 3 vias pedida pelo usuário
> pra separar "a camada barata capta sinal bom?" de "confiamos demais/
> de menos nela?": (A) heurística sozinha, (B) heurística + camada
> barata (produção atual), (C) só a camada barata decide direto (sem
> busca cara), testada com `CHEAP_LAYER_SAMPLES=3000` ("milhares").
> `smoke_fast`/`smoke_test` 100% (flag OFF por padrão, zero impacto em
> produção). **Comparação em andamento** — resultado no próximo bloco.

> 13/08/2026 (bloco 519): **FECHAMENTO da "calibragem dinâmica"** —
> re-teste 40-vs-3000 sem o confound de RNG (bloco 518) deu
> `maximin=+0,000, soma=+0,033`: não regride, mas ganho quase nulo (3
> de 4 matchups empatados exatos). Verificação ponto-a-ponto explicou
> o porquê: o ranking interno da camada barata muda 33% com mais
> amostra, mas o CONJUNTO de candidatas que entram no shortlist não
> mudou em nenhum caso testado (0%) — os números ficam mais precisos,
> mas a decisão que importa já estava certa com 40. Diferença
> arquitetural pro NarutoSim explicada ao usuário: lá as simulações
> SÃO a decisão final (MCTS); aqui elas só filtram grosseiramente quem
> entra na busca cara (que já decide bem). A busca cara em si não pode
> escalar pra "milhares" como o NarutoSim — cada amostra simula um
> turno real completo (~3,7ms/amostra medido, 8000 amostras custaria
> ~30s só pra 1 candidata).
>
> **Decisão final do usuário**: manter a camada barata RASA (só
> flags, `CHEAP_LAYER_SAMPLES=40`), sem investir numa camada
> intermediária. Estado consolidado: só a fase 1 original (blocos
> 509-511) sobrevive da "calibragem dinâmica"; fase 2 (ajuste de peso)
> e escala maior de amostra foram exploradas e descartadas — mas 2
> bugs reais e permanentes foram corrigidos no processo (confound de
> RNG, default de parâmetro não dinâmico). Ver bloco 519 do HANDOFF.

> 13/08/2026 (bloco 518): **CONFOUND real achado no resultado negativo
> do bloco 517** (pedido do usuário pra investigar antes de desistir).
> `_cheap_rollout_value`/`_compute_cheap_values` usavam o MÓDULO
> `random` global (mesmo stream de `random.shuffle(p.deck)`/compras de
> carta) quando nenhum `rng=` era passado — sample count diferente
> consumia quantidade diferente de números aleatórios a cada decisão,
> deslocando TODOS os sorteios seguintes da partida. A comparação
> 40-vs-3000 do bloco 517 comparava partidas com MÃOS diferentes, não
> "qualidade da amostra". **Corrigido** com `_CHEAP_LAYER_RNG` isolado
> (seed fixa, nunca toca o stream do jogo) — confirmado que o stream
> real fica intacto agora. `smoke_fast`/`smoke_test` 100%.
> `CHEAP_LAYER_SAMPLES` mantido em 40 até o re-teste (em andamento) dar
> resultado. Ver bloco 518 do HANDOFF.

> 13/08/2026 (bloco 517): **RESULTADO FINAL — subir `CHEAP_LAYER_
> SAMPLES` pra milhares PIORA o bot**. Comparação re-rodada após o fix
> do bug do bloco 516 (agora varia de verdade): 3 de 4 matchups
> pioraram, 1 empatou, NENHUM melhorou (`maximin=-0,133, soma=-0,333`)
> — reprova o critério maximin, contrário à expectativa ("igual ao
> NarutoSim, milhares deveria ser mais confiável"). Causa raiz não
> investigada a fundo (hipótese não confirmada no HANDOFF). **Revertido
> pro valor já validado (40, bloco 510)**. `smoke_fast`/`smoke_test`
> 100%.
>
> **Estado final da "calibragem dinâmica" nesta sessão**: só a fase 1
> (camada barata alargando o shortlist, `CHEAP_LAYER_SAMPLES=40`)
> sobrevive — exatamente como ficou nos blocos 510/511. Tanto o ajuste
> de peso (fase 2, blocos 513-515) quanto escalar a amostra (blocos
> 514/517) foram medidos e descartados por regredir/não melhorar,
> apesar de ambos parecerem boas ideias em teoria. Ver bloco 517 do
> HANDOFF.

> 13/08/2026 (bloco 516): **Bug real na comparação de escala (40 vs
> 3000 amostras)**: margem deu EXATAMENTE zero em todos os 4 matchups —
> sinal de bug, não "efeito zero de verdade". Causa: `_compute_cheap_
> values` usava `CHEAP_LAYER_SAMPLES` como valor PADRÃO de parâmetro —
> Python fixa isso no import, reatribuir `de.CHEAP_LAYER_SAMPLES` em
> runtime (o script de comparação) nunca mudava o default já fixado.
> Corrigido passando `n_samples=` explícito nos 2 chamadores de
> produção (`main_phase`/`sim_bridge.choose_action`) — não é bug de
> produção (a constante nunca é reatribuída fora de teste), mas
> invalidava qualquer comparação futura que tentasse variar essa
> constante. Validado manualmente (tempos agora variam de verdade:
> 0,14ms vs 6,6ms). `smoke_fast.py` 100%. Comparação re-rodando com o
> fix. Ver bloco 516 do HANDOFF.

> 13/08/2026 (bloco 515): **Fase 2 (ajuste de peso) REMOVIDA por pedido
> do usuário** — reiterou a ideia original ("igual ao NarutoSim: rodar
> milhares de vezes, achar boas alternativas, passar pra heurística
> validar/escolher") e esclareceu que isso já é o fluxo da fase 1 + a
> busca cara existente, sem precisar mexer em peso nenhum (nem
> multiplicativo nem aditivo). A adaptação por deck vem de QUAIS
> candidatas entram na busca (deck-agnóstico via `get_card_flags`), não
> de ajustar a régua fixa (`EVAL_WEIGHTS`, calibrada nos blocos
> 493-507, permanece intocada). Código do mecanismo de ajuste removido
> por inteiro (registrado como tentativa descartada, mesmo tratamento
> das 2 tentativas do bloco 508). Único ajuste que sobrou: escala da
> camada barata (`CHEAP_LAYER_SAMPLES`) de 40 pra 3000 amostras — custo
> medido (~19-29ms/decisão, trivial ao vivo, mensurável offline).
> Comparação de escala (40 vs 3000, mesmo roster multi-âncora do bloco
> 514) rodando — resultado no próximo bloco. `smoke_fast.py` 100%. Ver
> bloco 515 do HANDOFF.

> 13/08/2026 (bloco 514): **Correção metodológica na medição da fase 2**
> (usuário: "não adianta fazer igual vc tá fazendo, calibrando 1 deck
> só" + "milhares de vezes", não 40). Duas correções: (1)
> `DYNAMIC_WEIGHT_ADJUSTMENT_SAMPLES = 3000` (separado de
> `CHEAP_LAYER_SAMPLES=40` da fase 1, não mexida) — custo medido
> ~13,6ms/decisão, negligível; (2) comparação OFF-vs-ON refeita com
> roster MULTI-ÂNCORA (cada deck aparece 1x como lado rastreado, 1x
> como oponente) em vez do Imu fixo do bloco 513 — mesmo erro já achado
> nos blocos 505/506, repetido sem perceber na medição da fase 2.
> `smoke_fast.py` 100%. **Comparação com roster corrigido rodando —
> resultado no próximo bloco.**

> 13/08/2026 (bloco 513): **FASE 2 da "calibragem dinâmica" implementada**
> (`USE_DYNAMIC_WEIGHT_ADJUSTMENT`, desligada por padrão até medir
> isolada — mesmo protocolo da fase 1). Mecanismo: reusa os rollouts
> baratos da fase 1 (`_cheap_rollout_components`, decomposição por
> termo de `EVAL_WEIGHTS`) pra achar qual termo mais explica a vantagem
> da candidata líder sobre a vice numa decisão específica, e reforça
> ele TRANSITORIAMENTE (`peso_final = peso_estático × (1+ajuste)`, teto
> ±20%, só durante a busca cara daquela decisão — nunca persiste,
> deck-agnóstico de verdade). Wired nos dois caminhos (offline e ao
> vivo). 4 testes novos em `smoke_fast.py`, suíte completa 100%,
> comportamento de produção inalterado (flag OFF).
>
> **RESULTADO da comparação OFF-vs-ON** (mesmo roster/protocolo do
> bloco 510, N=30/matchup): **NÃO passa no critério maximin** —
> Imu_v_Mihawk regrediu -13,3pp, Imu_v_Ace ficou igual, Imu_v_Lucy
> melhorou +16,7pp (maximin=-0,133, soma=+0,033). Diferente da fase 1
> (bloco 510, maximin=+0,033 positivo em TODOS). **Decisão:
> `USE_DYNAMIC_WEIGHT_ADJUSTMENT` continua `False`** — fase 2 fica
> implementada/testada/auditável, mas não liga em produção. Hipótese
> não confirmada registrada pro futuro (alocação proporcional do teto
> pode estar super-reforçando com sinal ruidoso de 1 decisão só) — ver
> bloco 513 do HANDOFF pras ideias não testadas (reduzir cap, exigir
> gap mínimo, mais seeds antes de descartar de vez).

> 13/08/2026 (bloco 512): **`_select_action_via_search` generaliza a
> parada antecipada de 2 pra N candidatas** (achado ao investigar o
> pior caso de tempo do bloco 511, pedido do usuário "acha que tem
> alguma coisa errada que possa ser corrigida?"). Antes, o teste
> pareado adaptativo (piso/teto de amostras) só existia pra
> `len(candidatas)==2` — com 3+ (cada vez mais comum desde a camada
> barata), o código sempre rodava exatamente o piso, sem testar nada:
> desperdiçava amostras numa decisão óbvia E nunca subia pro teto numa
> decisão genuinamente empatada. Corrigido comparando a LÍDER atual vs
> a VICE (recalculadas a cada lote), generaliza pra qualquer N>=2, sem
> mudar o comportamento de N==2. 2 testes novos em `smoke_fast.py`,
> `smoke_test.py` 100%, `audit_replay.py --n 20`: 0 exceções/anomalias.
> Afeta os dois caminhos (offline e ao vivo, mesma fonte única).
>
> **ALERTA de infraestrutura, leia antes de editar qualquer coisa**: o
> ambiente reverteu sozinho o repo local (e pacotes pip) pra um commit
> bem mais antigo no meio desta sessão, sem aviso explícito — só um
> `ModuleNotFoundError` reaparecendo pra pacote que já estava
> instalado foi o sinal. Nada foi perdido (o push anterior já tinha ido
> pro GitHub), mas exige `git fetch`+comparar antes de continuar
> editando se `git log` parecer suspeito. Ver bloco 512 do HANDOFF pro
> procedimento de recuperação.
>
> **Não medido nesta sessão**: impacto em winrate/custo agregado desta
> mudança específica (só ausência de exceções/anomalias foi validada).

> 13/08/2026 (bloco 511): **Camada barata ESTENDIDA pro caminho AO VIVO**
> (`sim_bridge.choose_action`/`server.py`, pedido explícito do usuário
> "vamos estender para o aovivo" após o veredito do bloco 510).
>
> Antes de mexer em código, medi custo REAL no orçamento ao vivo
> (TOP_K=2, piso/teto 12/24, muito mais apertado que o offline) com um
> benchmark de N=403 pontos de decisão de self-play real (3 matchups):
> **overhead médio +266ms (+36,3%)** — média SEM=734ms/COM=1001ms.
> Achado que mudou a decisão de timeout: mesmo SEM a camada barata, o
> pior caso já passava de 3s (4,7s) — comportamento pré-existente, não
> criado por esta mudança, mas reforça que a margem já era apertada.
>
> **Mudanças**: `sim_bridge.py` agora calcula `cheap_values` e passa
> pra `_select_search_candidates` (reusa a MESMA flag
> `USE_CHEAP_LAYER_SHORTLIST`, já `True` por padrão desde o bloco 510 —
> nenhuma flag nova, contra REGRA_SEM_DUPLICACAO.md); 2 campos novos de
> auditoria em `trace_out["line_search"]` (`cheap_layer_active`,
> `cheap_layer_additions`); `server.py:1264` `timeout=3.0` → `5.0`
> (mantém ~5s de folga sob o limite real de 10s do `HttpClient` do
> plugin C#, confirmado no bloco 510).
>
> `smoke_fast`/`smoke_test` 100%. Sanity check manual adicional
> (`OPTCGMatch` real + `GameState`s de self-play avançado) confirmou
> `selection: counterfactual_search`, `cheap_layer_active: True`,
> alargamento de até 3 candidatas, sem exceção. Ver bloco 511 do
> HANDOFF.
>
> **Ressalva**: mesma limitação de 1 líder-âncora (Imu); benchmark mede
> CUSTO, não qualidade de decisão ao vivo real (exigiria partida contra
> humano, fora do alcance remoto). Fase 2 (calibragem dinâmica, bloco
> 508) continua NÃO iniciada.

> 11/08/2026 (bloco 510): **VEREDITO da fase 1 — `USE_CHEAP_LAYER_
> SHORTLIST` LIGADO por padrão** (offline). Comparação controlada
> (mesmo roster deconfundido, N=30/matchup, seeds pareadas): winrate
> melhora nos **4 matchups** (+3,3pp/+16,7pp/+6,7pp/+16,7pp,
> **maximin=+0,033**, zero regressão — resultado mais forte da sessão)
> ao custo de **+60,6%** de tempo por partida. Custo aceitável porque só
> afeta o caminho OFFLINE (`sim_bridge.py`, ao vivo, não foi tocado).
>
> **Esclarecimento pro usuário**: existem 2 timeouts no caminho ao
> vivo — limite real/rígido de 10s (plugin C#, `HttpClient`, fora do
> nosso controle) vs orçamento interno de busca de 3s (escolha própria
> em `server.py`, com folga sob os 10s reais). **Sim, dá pra estender**
> (ex: 5-6s) se algum dia quisermos levar a camada barata pro caminho ao
> vivo — decisão separada, fora do escopo desta sessão.
>
> `smoke_fast`/`smoke_test` 100%, `audit_replay.py --n 30 --workers 4`
> (novo padrão): 0 exceções/anomalias. Ver bloco 510 do HANDOFF.
>
> **Ressalva**: N=30, só 1 líder-âncora (Imu) testado — mesma lição do
> bloco 505/506 sobre generalizar de 1 deck só.
>
> **Estado**: fase 1 CONCLUÍDA e ligada em produção (offline). Fase 2
> (calibragem dinâmica) e extensão pro caminho ao vivo continuam NÃO
> iniciadas — próximos passos naturais se o usuário quiser continuar.

> 11/08/2026 (bloco 509): **FASE 1 implementada** — camada barata
> (`_cheap_rollout_value`, baseada nas flags já existentes de
> `get_card_flags`, sem resolver efeito de verdade) alargando o
> shortlist de `_select_search_candidates` (opt-in via
> `USE_CHEAP_LAYER_SHORTLIST`, desligado por padrão — zero mudança de
> comportamento em produção). Só o offline (`main_phase`) recebeu a
> integração; `sim_bridge.py` (ao vivo) não foi tocado ainda.
>
> **Ferramenta de auditoria permanente criada**: `audit_cheap_layer.py`
> (pedido explícito do usuário) — mede concordância entre o sinal
> barato e a busca real, quanto o shortlist alarga, e se as candidatas
> adicionadas viram escolha final. Achado ao testar a própria
> ferramenta: métrica de concordância contra limiar fixo de 50% é
> ingênua (conjuntos com 3+ candidatas têm chance de concordar por
> acaso menor que 50%) — corrigida pra comparar contra o acaso esperado
> de verdade.
>
> **Primeiro resultado real** (N=20, líder Imu, 548 decisões):
> concordância bate o acaso por **+18,3pp** (sinal carrega informação
> real, não ruído); 20% das candidatas que só a camada barata promoveu
> viraram a escolha final depois da busca real reavaliar (resgata
> jogada boa que o score estático perderia).
>
> **Testes novos** (`smoke_fast.py`, incl. um bug real pego — limiar
> ausente no alargamento, corrigido antes de aceitar). `smoke_fast`/
> `smoke_test` 100%, `audit_replay.py --n 30 --workers 4` (feature
> desligada): 0 exceções/anomalias. Ver bloco 509 do HANDOFF.
>
> **Leitura honesta**: valida que o MECANISMO funciona, não prova ainda
> ganho de winrate/eficiência agregada — só testado com 1 líder (Imu).
>
> **Próximo**: comparação de eficiência real (self-play com/sem a
> camada, mesmos matchups deconfundidos, N grande) antes de decidir se
> fica. Fase 2 (calibragem dinâmica) continua não iniciada, aguardando
> esse resultado primeiro.

> 11/08/2026 (bloco 508): **Desenho FINAL em 2 fases acordado** pra
> "calibragem dinâmica" (nasceu de "como não descalibrar um deck pro
> outro"). 2 tentativas de escopo erradas antes de chegar aqui (perfil
> por matchup — ainda é calibragem por deck; pergunta fechada A/B —
> nenhuma capturou certo), registradas no bloco 508 do HANDOFF.
>
> **Fase 1 (a construir agora)**: camada barata baseada nas flags já
> existentes (`get_card_flags` — `has_ko`/`has_search`/etc, sem resolver
> efeito de verdade), rodada muitas vezes, alimentando
> `_select_search_candidates` (achado: é a função "FONTE ÚNICA", hoje
> 100% score estático, que decide quais ações entram na busca cara do
> Turn Planner — offline E ao vivo) como sinal adicional pra widen o
> shortlist, sem tocar na busca cara em si.
>
> **Fase 2 (especificada, só construir depois de medir a fase 1
> isolada)**: reusa os rollouts baratos da fase 1 (sem simulação nova),
> aplica um ajuste com teto (±20%) em cima do `eval_weights.json` já
> validado — `peso_final = peso_estático × (1 + ajuste)` —, via o mesmo
> `state.eval_weights` já usado/corrigido o dia inteiro. Degrada suave
> pro comportamento de hoje se o sinal for fraco/ruidoso.
>
> **Por que sequenciar**: combinar as 2 fases num prototipo só impediria
> saber qual peça causou qualquer resultado — mesmo raciocínio de
> isolar variável usado o dia inteiro. Medir fase 1 sozinha primeiro
> (self-play, N grande, matchups já deconfundidos) contra o baseline de
> hoje, DEPOIS fase 2 em cima.
>
> **Nada implementado ainda** — próximo passo real é construir a fase 1.

> 11/08/2026 (bloco 507): **Verificação final — `decision_quality_
> report.py` em 4 líderes** (Imu, Mihawk, Ace, Lucy, N=20 cada) com os
> pesos finais de hoje. Utilização da habilidade do líder saudável nos 3
> que têm uma (94,6%-100%), DON limpo em faixa razoável nos 4
> (33%-66%). **Nenhum sinal de deck "descalibrado"** pelas 7 mudanças de
> peso desta sessão. Só verificação, nenhum código/peso mudou. Ver bloco
> 507 do HANDOFF.
>
> **FECHA o arco de calibração 493-507**: bug real corrigido
> (`__deepcopy__`), 14 pesos de `EVAL_WEIGHTS` revalidados (7 mudaram),
> 1 mecanismo redesenhado (`opp_combo_threat`), metodologia corrigida de
> single-anchor pra multi-anchor, verificação final em 4 arquétipos sem
> regressão.
>
> **Pendências pro futuro** (nenhuma nova): (1) ligar `opp_counter_
> potential()` em `avaliar_carta()`; (2) expandir multi-âncora pra mais
> arquétipos; (3) os 2 casos sem cobertura de `opp_combo_threat`
> (aceitos, não bug); (4) ideia de cache-MC tipo NarutoSim, direção de
> longo prazo não escopada.

> 11/08/2026 (bloco 506): **2ª iteração multi-âncora CONCLUÍDA — os 10
> pesos universais confirmam robustos contra Imu+Mihawk**. Nenhum dos 10
> (`dmg`, `board_mine`, `board_opp`, `life_mult`, `hand_first`,
> `counter_hand`, `don_field`, `coverage`, `opp_blocker`, `hand_extra`)
> mudou — os valores derivados só de self-play do Imu (blocos 499-504)
> passaram no teste cruzado contra Mihawk (arquétipo bem diferente) sem
> precisar de ajuste. **Resposta direta pra pergunta do usuário**
> ("como não descalibrar um deck pro outro"): evidência real, não
> suposição — essa parte da calibração não ficou "boa só pro Imu".
> 2 pesos condicionais refinaram mais: `opp_combo_threat` 1.2→**0.804**,
> `survival_premium` 15.0→**22.5** (continuam Imu-ancorados, correto —
> só o Imu tem os eixos/`don_target` relevantes). `smoke_fast`/
> `smoke_test` 100%, `audit_replay.py --n 30 --workers 4`: 0
> exceções/anomalias. Ver bloco 506 do HANDOFF.
>
> **Próximo passo mais barato registrado** (não iniciado): ligar
> `opp_counter_potential()` (já existe, barato, fairness-aware) dentro
> de `avaliar_carta()` — hoje ela não usa nem essa peça simples, muito
> menos o `OpponentModel` completo (que só alimenta a busca profunda,
> `_adaptive_counterfactual_search`, nunca a heurística de carta usada
> em 16 pontos do código). Passo natural antes de cogitar sampling
> completo em `avaliar_carta` (caro — chamada bem mais vezes por decisão
> que a busca profunda).

> 11/08/2026 (bloco 505, PARCIAL): **ACHADO METODOLÓGICO do usuário**:
> a calibração dos blocos 499-504 usou **Imu como âncora única** até pros
> pesos UNIVERSAIS (`dmg`, `board_mine`, `hand_first`, `don_field`, etc.)
> — necessário pros pesos condicionais a eixo de perfil (só o Imu tem os
> eixos no pool de 193 decks), mas pros universais foi conveniência,
> arriscando otimizar pro ESTILO do Imu em vez de generalizar. 1ª
> tentativa da 2ª iteração (Imu-only) morta a meio caminho, nada mudou
> em `eval_weights.json`. **Redesenhada**: pesos universais agora testam
> com 2 âncoras de arquétipo diferente (Imu combo/reanimação + Mihawk
> agressivo/counter-denso), mesmo total de partidas de antes, só
> redistribuído. Pesos condicionais continuam Imu-ancorados (correto pra
> eles). Relançado em background, resultado pendente. Ver bloco 505 do
> HANDOFF.
>
> **Nota permanente pra sessões futuras**: calibração de peso universal
> sempre precisa de pelo menos 2 arquétipos-âncora distintos, não só o
> deck mais conveniente/já testado.
>
> **Addendum (contexto de backlog, NADA implementado)**: usuário
> discutiu per-deck vs global vs "MC puro tipo Naruto cacheado" —
> conclusão: motor já suporta pesos por-estado (`state.eval_weights`),
> vários termos já são híbridos (formula global + gating condicional,
> ex. `wincon_ready`/`survival_premium`), e cache-de-MC-massivo tem a
> MESMA tensão de amostra que pesos escalares, só em forma de buckets.
> Usuário (outra ferramenta/sessão com browser) inspecionou o
> `narutosim.theramenbowl.net` — CPU de lá é MCTS/UCT real com
> dificuldade = só orçamento de busca, avaliação linear de 8 features
> sem conhecimento de carta. **Confirmado contra o código real**:
> `opponent_model.py` existe, `counterfactual_search`/
> `sampled_opponent_model` existem, blocos 471/475 são reais. Conclusão:
> confirma por ângulo independente que MC puro ao vivo é inviável aqui
> (cada rollout nosso precisaria do motor de regras completo, não uma
> soma linear de 8 números). **Achado mais acionável**: `opponent_model.py`
> já existe mas está subutilizado (só alimenta o Turn Planner, não
> `avaliar_carta`) — candidato a próximo passo mais barato que um
> subsistema de cache novo. Registrado como direção futura, não
> iniciado.

> 11/08/2026 (bloco 504): **FECHA os 3 itens aprovados pelo usuário**
> (redesign `opp_combo_threat`, calibrar 3 pesos nunca testados, refinar
> `don_field`/`ax_inversion`). Refinamento final: `don_field` testado dos
> dois lados (5.0, 7.5), nenhum bateu — **6.0 confirmado teto local de
> verdade**. `ax_inversion` refinou mais: 0.75 → **0.625** (0.625 vs 1.0,
> ambos empatam maximin mas 0.625 tem soma maior). `smoke_fast`/
> `smoke_test` 100%, `audit_replay.py --n 30 --workers 4`: 0
> exceções/anomalias. Ver bloco 504 do HANDOFF.
>
> **Resumo do arco 493-504** (nasceu de "como melhoramos o
> simulated_value"): achado e corrigido 1 bug real (`__deepcopy__` não
> propagava `eval_weights`, invalidando silenciosamente calibração via
> Monte Carlo desde sempre); revalidados os 14 pesos numéricos de
> `EVAL_WEIGHTS` (7 mudaram: `dmg`, `don_field`, `ax_inversion`,
> `opp_blocker`, `hand_extra`, `opp_combo_threat`,
> `next_turn_readiness` dividido em 2); redesenhado 1 mecanismo de
> detecção que estava estruturalmente morto. Toda mudança validada
> antes de commitar.
>
> **Pendências pro futuro** (nenhuma nova): 2ª iteração completa de
> coordinate-ascent (esta sessão fez só 1 passada por peso); os 2 casos
> que `opp_combo_threat` ainda não cobre (fog of war genuíno; jogado+
> ativado no mesmo turno sem revelação prévia) — aceitos como limite
> honesto, não bug.

> 11/08/2026 (bloco 503): **3 pesos nunca testados calibrados**
> (`opp_blocker`, `hand_extra`, `survival_premium` — nunca estiveram em
> `_TUNABLE`) + **`opp_combo_threat` recalibrado** (redesenhado no bloco
> 502). Confound checado antes de rodar (`survival_premium` é gated pelo
> meu `don_target`, roster padrão confirmado sem risco). Resultado:
> `opp_blocker` 25.0→**16.75**, `hand_extra` 3.0→**2.01** (evidência mais
> forte deste lote), `opp_combo_threat` 0.8→**1.2** (valida o redesign —
> peso saiu de inerte pra responder de verdade), `survival_premium`
> mantido (15.0, validado). `smoke_fast`/`smoke_test` 100%,
> `audit_replay.py --n 30 --workers 4`: 0 exceções/anomalias. Ver bloco
> 503 do HANDOFF.
>
> **Próximo**: refinar `don_field`/`ax_inversion` (item 3 aprovado pelo
> usuário) — os dois só bateram o baseline empatando o pior matchup, vale
> testar valores adicionais.

> 11/08/2026 (bloco 502): **`opp_combo_threat` REDESENHADO** — usuário
> aprovou (dos 3 itens propostos) corrigir a causa raiz do bloco 498.
> `opp_combo_threat()` agora também escaneia `known_hand_cards()` (cartas
> reveladas na mão do oponente — mesma infra de fairness de
> `opp_counter_potential`), cobrindo o cenário real de aviso prévio que
> faltava. **Impacto real medido**: gatilho subiu de 0% pra **38,7%**
> nas mesmas 15 partidas do probe original. Teste novo prova as 2 pontas
> (carta oculta invisível, carta revelada detectada) + scan antigo
> preservado. `smoke_fast`/`smoke_test` 100%, `audit_replay.py --n 30
> --workers 4`: 0 exceções/anomalias. Ver bloco 502 do HANDOFF.
>
> **Próximo**: `opp_combo_threat` (peso, ainda prior 0.8) agora é
> candidato viável de calibração de verdade — vai entrar no próximo lote
> junto com `opp_blocker`/`hand_extra`/`survival_premium` (também
> aprovados pelo usuário).

> 11/08/2026 (bloco 501): **3º e ÚLTIMO lote — FECHA a revalidação dos
> 11 pesos originais de `tune_weights.py._TUNABLE`** (suspeita do bloco
> 495). `ax_reanim`/`ax_trash`/`ax_inversion` são eixos derivados
> condicionais (mesmo risco de confound do `wincon_ready`) — escaneei o
> pool completo e montei roster LIMPO por peso antes de rodar (licão do
> 497 aplicada proativamente). `ax_inversion` mudou: 0.5 → **0.75**
> (maximin=+0,000, empata 3 matchups, melhora 1). `ax_reanim`/`ax_trash`
> mantidos (validados). **Placar final dos 11 pesos**: 3 mudaram (`dmg`
> 180→270, `don_field` 4→6, `ax_inversion` 0.5→0.75), 8 validados sem
> mudança. `smoke_fast`/`smoke_test` 100%, `audit_replay.py --n 30
> --workers 4`: 0 exceções/anomalias. Ver bloco 501 do HANDOFF.
>
> **Pendências pro futuro** (nenhuma nova iniciada): (1) `opp_combo_
> threat` — decisão de mecanismo pendente (bloco 498); (2)
> `opp_blocker`/`hand_extra`/`survival_premium` nunca estiveram em
> `_TUNABLE`, ainda prior puro — próxima fronteira natural; (3) 2ª
> iteração de coordinate-ascent nos pesos já aceitos com margem fraca
> (`don_field`, `ax_inversion`, maximin=+0,000 nos dois) poderia refinar
> mais.

> 11/08/2026 (bloco 500): **2º lote da revalidação dos 11 pesos
> originais** — `life_mult`, `hand_first`, `counter_hand`, `don_field`,
> `coverage` (universais, sem risco de confound). Só `don_field` mudou
> (4.0 → **6.0**, maximin=+0,000 — empata o pior matchup, melhora 2
> outros, aceito pela mesma regra do `tune_weights.py`). Os outros 4
> ficaram como estavam (nenhum candidato bateu o baseline). **Placar
> acumulado (8/11 pesos testados)**: 2 mudaram (`dmg`, `don_field`), 6
> validados sem mudança. `smoke_fast`/`smoke_test` 100%,
> `audit_replay.py --n 30 --workers 4`: 0 exceções/anomalias. Ver bloco
> 500 do HANDOFF.
>
> **Pendente pra próxima rodada**: os 3 últimos — `ax_trash`,
> `ax_reanim`, `ax_inversion` (eixos derivados de perfil, precisam do
> mesmo cuidado de confound/probe que `wincon_ready` exigiu).

> 11/08/2026 (bloco 499): **1º peso original de `tune_weights.py.
> _TUNABLE` confirmado mal calibrado** — `dmg` (180.0) testado junto com
> `board_mine`/`board_opp` (os 3 mais centrais, universais, sem risco do
> confound do bloco 497). Coordinate-ascent N=30, roster deconfundido:
> `dmg=270.0` (x1.5) teve **maximin=+0,067, melhora TODOS os 4 matchups,
> zero regressão** — aceito. `board_mine`/`board_opp`: nenhum candidato
> bateu o baseline, mantidos (1.0 e 0.8). **Valida a suspeita do bloco
> 495**: pelo menos 1 dos 11 pesos originais estava preso num valor pior
> por causa do bug do `__deepcopy__`. `dmg` é o termo de maior peso
> absoluto da fórmula — mudança pode ter efeito sistêmico, vale observar
> em partidas reais futuras. `smoke_fast`/`smoke_test` 100%,
> `audit_replay.py --n 30 --workers 4`: 0 exceções/anomalias. Ver bloco
> 499 do HANDOFF.
>
> **Pendente pra próxima rodada**: os 8 pesos restantes de
> `tune_weights.py._TUNABLE` — `life_mult`, `hand_first`, `counter_hand`,
> `don_field`, `coverage`, `ax_trash`, `ax_reanim`, `ax_inversion` (os 3
> últimos, eixos derivados de perfil, podem precisar do mesmo cuidado de
> confound/probe que `wincon_ready` exigiu).

> 11/08/2026 (bloco 498): **`opp_combo_threat` — causa raiz do 0% de
> gatilho achada, NÃO é sample size**. Só 4 cartas em todo o banco têm a
> assinatura que o termo procura (`play_from_trash`/`add_from_trash`
> count≥2); das 193 decklists, só o Imu roda uma delas (Five Elders
> OP13-082). Rastreando turno a turno: Five Elders **nunca aparece em
> campo** nos checkpoints porque o próprio `[Activate: Main]` dela manda
> ela mesma pro trash (`trash_character self_character`) ANTES de
> reanimar, tudo no mesmo turno — não existe janela de "ameaça pendente,
> ainda dá tempo de reagir" pra essa carta específica, o que o termo foi
> desenhado pra detectar. Rodar mais partidas ou jogos mais longos NÃO
> resolveria isso (padrão estrutural, não estatístico). **Calibração não
> feita** — fica documentado como pendência de DECISÃO (não de dado):
> aceitar que o termo só importa se aparecer outra carta sem auto-trash
> com esse padrão, ou redesenhar `opp_combo_threat()` pra cobrir ameaças
> que se resolvem no mesmo turno (mudança de mecanismo, precisa decisão
> explícita do usuário — fora do escopo de "calibrar peso"). Nenhum
> código/peso mudou. Ver bloco 498 do HANDOFF.

> 11/08/2026 (bloco 497): **`wincon_ready` revalidado** — usuário
> perguntou "só testou com Imu?" sobre o bloco 496 e achou um problema
> real: escaneando o pool completo (193 decks), **84 (43%) têm o eixo
> bottleneck**, não só o Imu — e 2 dos 4 "oponentes" usados no bloco 496
> (Enel/Mirko Zanelli, Nami/AceOfSpades) também tinham o eixo, quebrando
> o isolamento da comparação (peso é aplicado simétrico nos 2 lados).
> Revalidado com 4 oponentes confirmados LIMPOS (Mihawk, Ace, Lucy,
> Luffy-Amarelo) e N=100/matchup (>3x, pedido do usuário por mais
> confiança). **Mesmo resultado**: nenhum candidato (x1.5=30.0,
> x0.67=13.4) bate o baseline sem regredir — prior 20.0 mantido, agora
> validado de forma robusta (não só a 1ª tentativa menor/confundida).
> Nenhum valor numérico mudou. `smoke_fast.py` 100%. Ver bloco 497 do
> HANDOFF.
>
> **Lição**: em calibração pareada com peso simétrico, sempre checar se
> os "oponentes" escolhidos também têm o eixo/termo sendo testado — um
> oponente que compartilha o eixo quebra o isolamento mesmo com
> maximin/N grande.
>
> (Ideia trazida pelo usuário de outra sessão — Monte Carlo puro sem
> heurística tipo o simulador do Naruto TCG — avaliada e descartada pra
> uso AO VIVO nesta sessão: custo proibitivo no orçamento de tempo real
> e exigiria um 2º motor simplificado, o que viola a regra "sem dois
> motores" do projeto. Alternativa aceita: mais amostra self-play
> OFFLINE com o motor real, que é o que já fazemos.)

> 11/08/2026 (bloco 496): **`wincon_ready`/`opp_combo_threat`** (os 2
> pesos restantes do achado do bloco 494) testados com o `__deepcopy__`
> já corrigido. Lição do 491/492 aplicada PROATIVAMENTE desta vez:
> probe rápido (N=6) ANTES de escalar — `wincon_ready` disparou em
> 71-76% dos turnos (Imu, único deck do roster com o eixo bottleneck);
> `opp_combo_threat` deu **0% em 166 turnos/4 matchups** (provável causa:
> só conta ameaça se o trash do oponente já tiver ≥1 corpo qualificado,
> e jogos self-play curtos podem terminar antes disso acontecer) —
> **calibração pulada**, não vale gastar amostra grande num termo que
> não dispara nestas condições.
>
> **`wincon_ready` calibrado de verdade** (N=30, 4 matchups
> Imu_v_{Mihawk,Enel,Ace,Nami}): candidatos x1.5 (30.0, maximin=-0,100)
> e x0.67 (13.4, maximin=-0,067) diferenciaram bem do baseline (prova
> que o mecanismo funciona), mas nenhum bateu sem regredir o pior
> matchup (Imu_v_Mihawk). **Prior 20.0 mantido — resultado negativo mas
> conclusivo**, agora validado por teste real em vez de nunca calibrado.
> Nenhum valor numérico mudou em `eval_weights.json`, só `_meta`.
> `smoke_fast.py` 100%. Ver bloco 496 do HANDOFF.
>
> **Fecha os 3 pesos do achado do bloco 494**: next_turn_readiness
> (dividido e calibrado), wincon_ready (validado, sem mudança),
> opp_combo_threat (pulado, dado insuficiente).
>
> **Pendências pra próxima sessão**: (1) repetir `opp_combo_threat` com
> jogos mais longos ou matchups onde o trash do oponente acumula fuel
> mais cedo; (2) a suspeita maior do bloco 495 — revalidar os 11 pesos
> originais de `tune_weights.py._TUNABLE`, calibrados possivelmente sob
> o bug do `__deepcopy__` (só corrigido no bloco 495).

> 11/08/2026 (bloco 495): **`next_turn_readiness` dividido em 2 pesos
> independentes** (`next_turn_readiness_self` / `next_turn_readiness_
> opp_threat`) — o peso único do bloco 494 multiplicava dois sinais
> diferentes (ganho projetado pro meu lado vs ameaça de ataque projetada
> do oponente) pelo mesmo escalar; zerar os dois juntos (decisão do 494)
> descartava sinal bom junto com o ruim.
>
> **ACHADO MAIOR não planejado**: 1ª calibração deu margem **ZERO em
> TODOS os 5 candidatos** (idêntico demais, mesmo alerta do
> bloco 491/492) — investigado a fundo, achado bug real em
> `GameState.__deepcopy__`: `eval_weights`/`use_eval_v2` são atributos
> DINÂMICOS nunca propagados pro clone (mesma categoria do bug do
> `self_play_info_hidden`, bloco 490), e `_evaluate_state_v2` (única
> leitora de `eval_weights`) SEMPRE roda sobre o clone de
> `_simulate_sequence_once` — todo override por-estado (o mecanismo que
> `tune_weights.py` usa pra dar pesos candidatos ao lado A) caía
> silenciosamente no fallback global. Fix aplicado + teste novo
> (`test_deepcopy_propaga_eval_weights_e_use_eval_v2_11_08`).
>
> **Calibração relançada após o fix — desta vez diferenciou de
> verdade**: `next_turn_readiness_self=0.6` (maximin=+0,067, melhora os
> 3 matchups sem regredir nenhum — bate com o prior original de antes
> do bloco 494); `next_turn_readiness_opp_threat=0.0` (0,3 e 0,6
> regrediram, maximin=-0,033 nos dois). Aplicado em `eval_weights.json`.
> Leitura: o sinal "self" sempre foi bom — o sinal "threat" era o que
> prejudicava no peso combinado do bloco 494. `smoke_fast`/`smoke_test`
> 100%, `audit_replay.py --n 30 --workers 4`: 0 exceções/anomalias. Ver
> bloco 495 do HANDOFF.
>
> **Pendência pra próxima sessão**: `wincon_ready`/`opp_combo_threat`
> continuam no prior — agora com `__deepcopy__` corrigido, calibrá-los
> deve produzir sinal real pela 1ª vez. E a suspeita maior: **re-validar
> os 11 pesos originais de `tune_weights.py._TUNABLE`** no
> `eval_weights.json` — calibrados possivelmente sob o mesmo bug, o
> resultado "learned" pode não refletir diferença real entre candidatos.

> 10/08/2026 (bloco 494): **`next_turn_readiness` CALIBRADO de verdade
> pela 1ª vez — prior 0,6 → 0,0**, fechando 1 dos 3 pesos de
> `_evaluate_state_v2` que nunca passaram por `tune_weights.py`
> (`wincon_ready`/`opp_combo_threat`/`next_turn_readiness` — extensão
> do `_TUNABLE` feita, fix permanente). Self-play pareado real (3
> matchups, N=30): **0,0 teve maximin=+0,000** (não regride nenhum
> matchup, melhora 2 de 3: Ace_v_Mihawk +13,3pp, Nami_v_Enel +3,3pp);
> **2,0 teve maximin=-0,033** (regrediu Nami_v_Enel), reprovado pela
> mesma regra de não-regressão do `tune_weights.py`. Aplicado em
> `eval_weights.json` com `_meta` registrando o protocolo. Teste
> `smoke_fast.py` corrigido (lia o peso de produção sem perceber,
> quebraria com 0,0 — decoplado via `eval_weights` explícito no teste).
> `smoke_fast`/`smoke_test` 100%, `audit_replay.py --n 30 --workers 4`:
> 0 exceções. **Pendente**: `wincon_ready`/`opp_combo_threat` continuam
> no prior — `opp_combo_threat` pode ter o mesmo problema estrutural do
> PREVENT_COMBO (blocos 491/492), checar frequência de disparo antes de
> aceitar qualquer resultado. Ver bloco 494 do HANDOFF.

> 10/08/2026 (bloco 493): **investigadas 2 hipóteses de viés (attach_don
> sobre "descer bomba"; atacar líder sobre focar board) — NENHUMA
> confirmada**. Self-play real (5 líderes, 6 partidas cada,
> `decision_log`). 1ª passada comparando `score` raso achou 6 casos
> aparentes de "líder escolhido com score MENOR que Character
> disponível" — investigação mais funda mostrou que o Turn Planner
> decide por `simulated_value` (Monte Carlo), não pelo `score` raso (só
> usado pra selecionar candidatos do lookahead). Conferido em JSON real:
> Character já restado/neutralizado tinha score maior mas
> `simulated_value` menor que atacar o líder — o lookahead capta
> corretamente que matar um alvo já neutralizado vale pouco. Mesmo
> padrão confirmado pro DON (`attach_don` vencendo por `simulated_value`
> mesmo com `score` menor que a "bomba"/ataque ao líder). **Lição
> metodológica registrada**: nunca comparar só `score` entre candidatos
> — sempre conferir `simulated_value` quando presente (`simulated_
> samples` não-nulo). Contexto: `ATTACK_LEADER_BASE_SCORE` (bloco 395)
> já foi calibrado contra vencedores humanos reais (bot atacava líder
> MENOS que humanos antes do fix). Nenhuma mudança de código — não havia
> bug pra corrigir. Ver bloco 493 do HANDOFF.

> 10/08/2026 (bloco 492): **2ª tentativa de calibrar o PREVENT_COMBO —
> causa raiz REAL encontrada, não é falta de amostra**. Reescrito com
> `ProcessPoolExecutor` (N=60/matchup, Mihawk/Ace vs Imu). Taxa de
> disparo melhorou pra 26,7% (32/120), mas os 3 lotes continuaram
> **idênticos até o dígito**. Investigado a fundo: `analysis_priority()`
> é uma cascata com LETHAL e DEFENSIVE ACIMA de PREVENT_COMBO — nos
> matchups escolhidos (Mihawk 75%/Ace 60% de winrate vs Imu, vitórias
> decisivas), quando `opp_combo_threat` sobe o próprio lado já costuma
> estar perto de LETHAL, que sempre vence a cascata primeiro. Confirmado
> numa partida real: 3 de 4 decisões no turno com magnitude=4 tinham
> `priority=LETHAL`, não `PREVENT_COMBO`. **Não é problema de N — mais
> amostra não resolveria isso.** Uma calibração de verdade precisa de
> matchups mais equilibrados (sem LETHAL/DEFENSIVE disponível com
> frequência) ou medir a qualidade das decisões nos momentos em que
> `priority==PREVENT_COMBO` de fato ocorre, não o winrate agregado da
> partida inteira. Valores de produção (2/150/80) mantidos. Ver bloco
> 492 do HANDOFF.

> 10/08/2026 (bloco 491): **tentativa de calibração formal do
> PREVENT_COMBO — subdimensionada, valores de produção MANTIDOS**
> (item aberto desde 19/07). Extraídos os 3 literais numéricos pra
> constantes nomeadas (`PREVENT_COMBO_MAGNITUDE_THRESHOLD`/
> `PREVENT_COMBO_DEFENSIVE_CARD_BONUS`/`PREVENT_COMBO_LEADER_ATTACK_
> BONUS`) — refactor puro, mantido, zero mudança de comportamento.
> Self-play pareado (baseline vs 2 candidatos, Mihawk/Ace vs Imu,
> N=12/matchup) deu resultado **idêntico partida-por-partida nos 3
> lotes** — investigado e explicado: `opp_combo_threat()['magnitude']`
> só chegou a `>=1` em 2/12 partidas por matchup (2/247 e 6/205
> decisões individuais) — o gatilho é raro demais pra N=12 gerar
> qualquer sinal, não é evidência de que os valores não importam.
> **Decisão**: manter valores de produção (2/150/80), sem base pra
> mudar. **Pendência real registrada, não fechada**: uma calibração de
> verdade precisa de N bem maior ou curadoria de seeds que garantam o
> gatilho disparando cedo — fora do orçamento desta sessão. Ver bloco
> 491 do HANDOFF.

> 10/08/2026 (bloco 490): **SIMULADOR SELF X SELF do front-end LIGADO**
> (pendência mais antiga do TODO, bloco 370, 25/07 → fechada). O ponto
> de entrada já existia: `api.py POST /simulate` (usado por
> `src/app/simulate/page.tsx`) → `simulation_worker.run_single_match()`
> → `OPTCGMatch.simulate()`. `OPTCGMatch` ganhou
> `hide_opponent_info: bool = False`; `run_single_match` passou a usar
> `True` como default — o simulador do front-end já esconde mão/deck
> real de cada lado sem nenhuma mudança em `api.py`.
> `baseline_metrics.py`/`tune_weights.py`/`audit_replay.py` continuam
> full-info de propósito (decisão do bloco 370 mantida). **Bug real
> achado ao ligar de verdade**: `GameState.__deepcopy__` não propagava
> `self_play_info_hidden` — o único call site que deepcopia GameState
> (Monte Carlo do Turn Planner, dezenas/centenas de clones por decisão)
> perdia a flag em todo turno SIMULADO dentro da busca, esvaziando o
> propósito silenciosamente. Corrigido. Auditoria adicional achou
> `opp_counter_in_hand()` sem gate, mas é código morto (zero call
> sites) — registrado, não corrigido (sem impacto hoje). Teste novo em
> `smoke_fast.py` prova a flag, a propagação via `__deepcopy__` e uma
> divergência real de comportamento (2000 vs 320 no
> `opp_counter_potential()`). `smoke_fast`/`smoke_test` 100%,
> `audit_replay.py --n 30 --workers 4`: 0 exceções. Ver bloco 490 do
> HANDOFF e a seção "SIMULADOR SELF X SELF" mais abaixo (agora 🟢).

> 10/08/2026 (bloco 489): **outlier da Nefeltari Vivi (bloco 488, 56,4%
> de ativação) fechado — NÃO é bug**. Causa: a habilidade dela custa
> `rest_self` (restar o PRÓPRIO líder), mutuamente exclusivo com atacar
> nesse turno — diferente do resto do pool (custo em DON, compatível
> com atacar também). Rastreamento real confirmou: toda vez que
> "activate" perdeu, foi pra "attack" do MESMO líder, nunca outra coisa
> — trade-off de design real da carta, não erro de avaliação.
> `decision_quality_report.py` agora detecta `rest_self` no custo do
> líder-alvo e avisa explicitamente no item 1 que a taxa não é
> comparável a líderes de custo-DON. Mesma ressalva no `CLAUDE.md`/
> `AGENTS.md` (byte-idêntica). `decision_engine.py` não tocado —
> `smoke_fast`/`smoke_test` 100%. Ver bloco 489 do HANDOFF.

> 10/08/2026 (bloco 488): **`decision_quality_report.py` rodado nos 17
> líderes distintos do pool** (baseline de referência, pedido do
> usuário "rodar em mais líderes") + `--pool-size` novo (default 30 só
> alcançava 9 dos 17 líderes do banco de 193 decks). **Achado 1**:
> Luffy EB02-010 repete a assinatura do Sanji — winrate baixíssimo
> (6,7%) mas ativação de habilidade altíssima (98,8%), segunda
> confirmação de que winrate baixo ≠ bot não usa o mecanismo central.
> **Achado 2, NÃO investigado ainda**: Nefeltari Vivi (EB03-001) com
> 56,4% de ativação — único outlier real, todo o resto do pool com
> habilidade parseada ficou ≥88%. Candidato a próxima investigação
> pontual (mesmo método do bloco 487: rastrear no `decision_log` se é
> competição legítima por DON ou algo diferente). `smoke_fast`/
> `smoke_test` 100%, `decision_engine.py` não tocado. Ver bloco 488 do
> HANDOFF pra tabela completa dos 17 líderes.

> 10/08/2026 (bloco 487): **fechados os 2 achados pendentes do item 3**
> (bloco 486) — `Boeuf Burst` (14,3%) e `Gum-Gum Jet Culverin` (0%) no
> Sanji. Rastreamento manual de cada ocorrência no `decision_log`:
> **NÃO são bug** — em toda ocorrência não escolhida, perderam pra uma
> alternativa com score legitimamente maior no mesmo turno (habilidade
> do líder, atacar, outra carta) — competição real por DON escasso num
> deck com mais opções boas do que orçamento pra jogar todas. **Lição
> genérica registrada** (docstring/saída do script + `CLAUDE.md`/
> `AGENTS.md`): taxa baixa no item 3 é ponto de partida pra investigar,
> nunca veredito automático — só escalar se a alternativa vencedora for
> consistentemente pouco melhor ou claramente pior. `decision_engine.py`
> não foi tocado. Ver bloco 487 do HANDOFF.

> 10/08/2026 (bloco 486): **`decision_quality_report.py` ganha item 3
> (utilização POR CARTA, não só líder)** — pedido do usuário logo após
> ver o item 1 do bloco 485: "preciso saber se os efeitos das outras
> cartas estão sendo utilizados". Mesmo mecanismo (candidata-vs-
> escolhida, por turno, direto do `decision_log`), generalizado por
> código de carta. Tabela ordenada do pior aproveitamento pro melhor,
> `--top-cartas`/`--min-ofertas` configuráveis. Limitação honesta:
> `decision_log` só grava top-8 candidatos por decisão, carta que nunca
> chega perto do topo não aparece na tabela. **Achado real no Sanji,
> não investigado ainda**: `Boeuf Burst` (OP12-060, um dos poucos com
> remoção real no deck) ofertado 14x, escolhido só 2x (14,3%) — bem
> abaixo da maioria das outras cartas do mesmo deck. Validado também em
> Mihawk e Ace (incl. caminho N/A). `CLAUDE.md`/`AGENTS.md` atualizados
> (mesma seção do bloco 485, byte-idêntica). `decision_engine.py` não
> foi tocado — `smoke_fast`/`smoke_test` 100% sem mudança. Ver bloco
> 486 do HANDOFF.

> 10/08/2026 (bloco 485): **`decision_quality_report.py` NOVO,
> ferramenta permanente e agora OBRIGATÓRIA** — placar de qualidade de
> decisão por líder, independente de winrate (pedido do usuário depois
> do bloco 484: "como saberemos se o bot sabe jogar com o deck?").
> Mede, direto do `decision_log`/estado real (sem reimplementar
> elegibilidade): (1) taxa de utilização da habilidade do líder
> ([Activate: Main], candidata-vs-escolhida), (2) DON deixado na mesa
> no fim do turno. `--leader CODIGO --n N --workers W`. Validado em 3
> líderes reais: **Sanji OP12-041 ativa a habilidade em 98,3% dos
> turnos elegíveis mesmo perdendo 85% das partidas** — confirma que o
> mecanismo central do deck está sendo usado, a fraqueza (se houver)
> não é "não sabe ativar a própria habilidade". Mihawk (88,2%) e Imu
> (99,1%) na mesma faixa, validação cruzada. Tornado obrigatório em
> `CLAUDE.md`/`AGENTS.md` (mesma seção, byte-idêntica): rodar este
> relatório ANTES de olhar winrate sempre que a pergunta for "o bot
> sabe jogar esse líder?". Complementa a comparação já obrigatória com
> `IA_Compendium/RESUMO_ESTRATEGICO.md`. `decision_engine.py` não foi
> tocado neste bloco — `smoke_fast`/`smoke_test` 100% sem mudança. Ver
> bloco 485 do HANDOFF.

> 10/08/2026 (bloco 484): **`deck_lacks_removal_tools()`** — postura
> `CONTROL` passa a dar crédito a busca/compra (`has_search`/`has_draw`,
> mesmo bônus de `DEVELOP`) quando o deck genuinamente não tem remoção
> real, além do bônus de remoção que já dava. Achado ao investigar mais
> fundo o Sanji (pedido do usuário) depois de 2 experimentos A/B não
> decisivos (forçar profile→midrange: 8,2%→10,2%, ruído; forçar postura
> nunca-CONTROL: 8,2%→12,2%, ainda ruído). Causa raiz real:
> `deck_profile_type()` classifica só pela curva de custo — um deck 64%
> Evento barato de busca (Sanji, 32/50 cartas, só 12 remoção real) cai
> em `control` só por ter 2-3 personagens caros, e a postura `CONTROL`
> só recompensava remoção que esse deck não tem, nunca a busca que É a
> ferramenta real dele. Confirmado GENÉRICO (não só Sanji): 26/30 decks
> do pool testado caem em `control` pela classificação por curva. Fix
> via censo do deck (`removal_tools`/`card_selection_tools`, calculados
> em `populate_full_deck_knowledge`), limiar genérico (removal <
> selection*0.6), não hardcoded por líder. Teste novo em
> `smoke_fast.py` isolando o branch com censo sintético. `smoke_fast`/
> `smoke_test` 100%, `audit_replay.py --n 40 --workers 4`: 0 exceções.
> **Validação real (3ª rodada do mesmo lote de 200 partidas, seed
> idêntica)**: Sanji continua EXATAMENTE em 10,0% — mesmo número após 3
> mudanças de código diferentes (bloco 483 + 2 experimentos A/B + este
> fix). **Por pedido explícito do usuário, isso NÃO é falha**: o
> critério de sucesso desta investigação é qualidade de decisão dado o
> deck real ("garantir que o bot entende o deck e toma as melhores
> decisões, maximizando a play com o deck"), não winrate agregado — o
> bug de classificação era real e foi corrigido, independente do
> resultado agregado não ter mudado. A estagnação em 3 tentativas
> diferentes é evidência de que a explicação restante (se houver) não
> está mais na área postura/perfil — hipóteses que restam e não foram
> testadas: pool de decks maior (descartar azar de amostra, só 30
> decks hoje) ou mecanismo específico não investigado (DON turno a
> turno, timing de ataque). Ver bloco 484 do HANDOFF.

> 10/08/2026 (bloco 483): **fix em `_step_condition_currently_holds`
> CONFIRMADO e correto, mas NÃO resolveu o outlier de winrate do Sanji**
> — achado ao investigar o bloco 482 (Sanji OP12-041, 10% em 50 jogos).
> Causa raiz GENÉRICA (não específica do Sanji): a função só varria
> blocos `on_play`/`main` pra confirmar se uma flag condicional
> (`draws`/`power_buff`/etc.) vale agora — sem achar step lá, caía num
> fallback que retornava `True` mesmo quando a flag só existe porque a
> carta tem um bloco `[Counter]` (nunca resolve fora de batalha). Prova
> real: Gum-Gum Giant (`OP09-078`, só `[Counter]`) pontuava **igual** a
> uma carta de dig real do deck do Sanji e **acima** de uma carta de
> remoção real. Fix em dois pontos (decisão E execução, pra não divergir
> "dois motores"): `_step_condition_currently_holds` + `_score_to_play`
> (via `self._de()`). Teste novo em `smoke_fast.py`, `smoke_fast`/
> `smoke_test` 100%, `audit_replay.py --n 40 --workers 4`: 0 exceções.
> **Validação real (re-rodada do MESMO lote de 200 partidas do bloco
> 482, seed idêntica)**: o fix É exercitado de verdade — outros líderes
> no mesmo lote mudaram de winrate (Mihawk 69,1%→72,8%, Enel 71,1%→
> 62,2%, Nami 51,3%→59,0%, Imu 51,9%→55,6%, Lucy 55,6%→44,4%) — mas o
> **Sanji ficou EXATAMENTE em 10,0% (50 jogos), idêntico ao baseline**.
> Conclusão honesta: o bug era real e vale a correção (protege qualquer
> deck Event dual-mode/Counter-only no futuro), mas NÃO é a causa
> principal do desempenho ruim do Sanji. **Pista levantada, não fechada**:
> o pool de 49 confrontos do Sanji nesta amostra pesa pra líderes fortes
> do mesmo lote (Imu×7/Mihawk×5/Enel×6/Nami×4 = 22/49 contra os 4
> líderes de melhor winrate geral) — pode ser só azar de amostra (pool
> de 30 decks) ou fraqueza estrutural real do matchup, não investigado a
> fundo ainda. **Próximo passo proposto**: auditar 2-3 derrotas reais do
> Sanji decisão-a-decisão (adaptar o padrão de `audit_real_losses.py`
> pra self-play) pra achar a causa raiz de verdade, em vez de mais
> hipóteses agregadas. Ver bloco 483 do HANDOFF pros números completos.

> 10/08/2026 (bloco 482): **200 partidas reais em lote** (usando o
> paralelismo do bloco 481, `--workers 4`) pra capturar bugs + tempo +
> tendências de winrate por líder, a pedido do usuário. **BUGS**: 0
> exceções, 0 anomalias de invariante — nenhum sinal de regressão dos
> blocos recentes (469/479/480/481). **TEMPO**: lote 275.5s (~3,6x vs
> ~989.4s sequencial estimado); turnos#5-9 (meio de jogo) são
> consistentemente os mais caros, não o fim de jogo; as 5 partidas mais
> lentas têm o líder Enel (OP15-058) em 4 de 5. **TENDÊNCIA — achado
> que precisa de investigação**: **Sanji (OP12-041) com 10,0% de
> winrate em 50 jogos**, único líder com amostra grande E resultado tão
> fora da faixa (demais líderes ficaram 45-71%). Causa ainda NÃO
> apurada — pode ser deck genuinamente fraco no formato simulado,
> gameplan mal capturado por `deck_profile`/heurística do Turn Planner,
> ou lacuna de parser específica de cartas Sanji. **Próximo passo
> proposto, ainda não iniciado**: auditoria pente-fino do líder Sanji
> (texto-real vs efeito-parseado vs comportamento, igual blocos
> 400-401), cruzando com `IA_Compendium/RESUMO_ESTRATEGICO.md` se ele
> estiver no catálogo de 60 decks. Ver bloco 482 do HANDOFF pros números
> completos (tempo por turno, tabela de winrate completa).

> 10/08/2026 (bloco 481): **paralelismo em `audit_replay.py`/
> `gauntlet_matchup.py`/`baseline_metrics.py`** — os 3 rodavam partidas
> em sequência mesmo sendo independentes. Adicionado `--workers N`
> (default 1 = sequencial, comportamento de sempre) via
> `ProcessPoolExecutor`. Medido em `audit_replay.py`: **1m49s → 30s com
> 4 workers (~3,6x), resultado idêntico** entre sequencial/paralelo.
> `audit_replay.py` ganhou `if __name__ == "__main__":` (exigido pro
> multiprocessing no Windows/spawn). **Bug pego antes de commitar** em
> `baseline_metrics.py`: sequencial e paralelo davam resultados
> DIFERENTES pro mesmo `--seed` (esquemas de seed diferentes) —
> corrigido, unificado pra seed-por-índice nos dois casos. **Mudança de
> comportamento documentada nos 3**: `--seed` continua determinístico,
> mas a composição exata de cada partida individual mudou (não depende
> mais da ordem de execução acumulada). `smoke_fast`/`smoke_test` 100%
> (precaução — nenhum dos 3 scripts é testado por eles diretamente,
> `decision_engine.py` não foi tocado). **Virou regra obrigatória** em
> `CLAUDE.md`/`AGENTS.md` (pedido do usuário): escolher `--workers N`
> antes de qualquer simulação em lote, e scripts de calibração novos
> devem nascer com seed-por-índice, não `random.seed()` encadeado. Ver
> bloco 481 do HANDOFF.

> 10/08/2026 (bloco 480): **amostragem ADAPTATIVA ligada no `main_phase()`
> offline** (self-play/replay/calibração/`/simulate` do front-end) —
> **fecha pendência antiga (blocos 380/477)**: trocado N FIXO=3 por
> piso=3/teto=6 (mesmo mecanismo de early-stop estatístico já calibrado
> no caminho ao vivo, `OFFLINE_MC_SAMPLES_MIN/MAX/BATCH` novas). Custo
> medido ANTES de commitar (30 partidas reais, N fixo vs adaptativo):
> **+7,2% de tempo total** — decisões já claras custam o mesmo de antes,
> só as ambíguas gastam a amostra extra, exatamente onde a precisão
> importa. `smoke_fast`/`smoke_test` 100%, `audit_replay.py --n 20`: 0
> exceções, 0 anomalias. **Investigação relacionada, sem ação**: ideia de
> cache/memoização dentro da busca (motivada por "68% do tempo em
> generate_and_score_actions", bloco 477) foi **rejeitada pelo usuário**
> depois de confirmar que ~8% dos casos reais divergem entre amostras
> (cache ingênuo erraria decisões) — não implementado, registrado como
> descartado. `search_alloc`/lethal search confirmados caros por
> natureza (O(board²) já conhecido), não por desperdício. Ver bloco 480
> do HANDOFF.

> 10/08/2026 (bloco 479): **pondering implementado** (design aprovado do
> bloco 478) — `server.py` ganhou `ponder_fingerprint`/`_get_ponder_match`/
> `_trigger_pondering`/`_ponder_worker`/`_try_consume_ponder` + a extração
> de `_package_action` (empacotamento de action→payload, agora reusado
> por `/decide` E pelo pondering — mesma função, nunca duas versões
> divergentes). Gatilho em `/defense` (blocker/counter/trigger), consumo
> no topo de `/decide`, reset em `/mulligan`. **Flag `OPTCG_PONDER_
> ENABLED` OFF por padrão — zero mudança de comportamento em produção
> até alguém ligar explicitamente.** 4 testes novos em `smoke_fast.py`
> (exigidos pelo design), incluindo o mais importante — payload do
> pondering byte-idêntico ao caminho normal com instâncias de
> `OPTCGMatch` diferentes. `smoke_fast`/`smoke_test` 100%.
> **PENDÊNCIA CRÍTICA, não feita nesta sessão**: nenhum teste AO VIVO —
> ambiente remoto sem cliente OPTCGSim. Antes de considerar ligar por
> padrão, precisa de sessão local com a flag ligada + leitura obrigatória
> de telemetria (mesma disciplina do CLAUDE.md pra qualquer log de
> partida do bot). **Follow-up na mesma sessão** (revisão pedida pelo
> usuário): achado real — o fingerprint podia ficar descolado do estado
> realmente usado se um `/reveal` concorrente mudasse `_match_memory`
> entre o gatilho e o cálculo do pondering; corrigido recalculando o
> fingerprint dentro da própria thread do pondering. Consideração
> registrada mas NÃO implementada: várias threads de pondering podem
> rodar em paralelo se o oponente gerar `/defense` em sequência rápida
> (custo de CPU, não gera resultado errado) — item pra observar na
> sessão ao vivo, não corrigido preventivamente sem dado real. Ver
> bloco 479 do HANDOFF.

> **REGRA NOVA (bloco 473)**: `audit_real_losses.py` (+ `triage_real_
> losses.py`) agora é OBRIGATÓRIO rodar sempre que um log de DERROTA do
> bot é banco (não só "existe, use se quiser"). Ver `CLAUDE.md`/
> `AGENTS.md` e `.claude/skills/optcg-live-log-triage/SKILL.md` (Step 4).

> **PRÓXIMA SESSÃO COMEÇA AQUI (bloco 481) — 2 bugs reais de ordenação de
> alvo corrigidos** (investigação das reclamações do usuário nas partidas
> de hoje: "bot não dá K.O. com Doc Q", "bot não ganha vida com Shiryu").
> Ver bloco 481 do HANDOFF pro relato completo. Resumo:
> - **Doc Q**: zonas de DON tinham prioridade incondicional na lista de
>   candidatos de alvo, mesmo pra efeitos que nunca aceitam DON — o alvo
>   real (Streusen) ficava enterrado atrás de ~12 tokens de DON, ~8s+ de
>   cliques inúteis. Fix: `sim_bridge.order_target_candidates` só prioriza
>   DON quando o ator tem custo/alvo de DON de verdade
>   (`actor_needs_own_don`/`actor_needs_opp_don`).
> - **Shiryu**: `gain_life` estava na allowlist "nunca precisa de zona
>   real" (`_SAFE_NO_TARGET_ACTIONS`), certo pra `source='deck_top'` mas
>   errado pra `source='trash'`/`'hand_or_trash'` (só Shiryu OP16-108 e
>   ST13-003 no banco inteiro) — `own_trash` era excluído da lista de
>   candidatos mesmo com alvos válidos. Fix: `step_is_safe_no_target`
>   (decision_engine.py, fonte única, substitui os 2 pontos que liam a
>   allowlist crua).
> - Validado: 4 checks novos + 2 testes existentes corrigidos (precisavam
>   de `attacker_power` explícito pro custo de DON do Katakuri, que vive
>   em gatilhos só-de-combate). `smoke_fast.py` 100%, 0 falhas.
> - **Não confirmado via replay ao vivo** (log de clique-a-clique não
>   sobreviveu à reinstalação do BepInEx de hoje) — evidência forte
>   (combat log + leitura de código), não prova absoluta. Registrar se o
>   sintoma reaparecer numa partida real.
>
> **ACHADO NOVO (bloco 482), NÃO relacionado ao fix acima**: partida de
> validação pós-fix teve 10 timeouts de busca (`decision_kind=main`,
> turnos 3-6, todos ~3.0-3.06s no teto do `/decide`) — confirmado que
> NENHUM é `target` (a parte que o bloco 481 mexeu), então não é
> regressão de hoje. Hipótese não confirmada: boards mais complexos no
> meio-jogo esbarrando no custo já conhecido da busca. Vale investigar
> performance da busca AO VIVO como item separado numa sessão futura
> (não é ordenação de alvo, é a busca Monte Carlo em si). Também apareceu
> `semantic_transition_failed: 2` (93% de sucesso), não investigado.
>
> **PENDÊNCIA ANTERIOR (bloco 480) — pondering foi implementado, testado
> AO VIVO e REVERTIDO** (`git revert 5fe0966`, commit `60d133c` — motor
> de volta ao estado do commit `cc68d30`, código idêntico ao
> pré-pondering). **NÃO tentar reimplementar do mesmo jeito** sem ler o
> bloco 480 do HANDOFF primeiro:
>
> **Causa raiz real da derrota de teste** (não foi qualidade de decisão —
> a propriedade "payload idêntico" já tinha sido provada em smoke test):
> `threading` em Python não dá paralelismo de CPU de verdade (GIL) —
> rodar a busca Monte Carlo do pondering em background ROUBOU tempo de
> CPU da busca real, causando 4 timeouts de `/decide` (3+ segundos, turnos
> 3-4) e 4 `no_eligible_action` (bot "sem saber o que fazer", turno
> desperdiçado). Confirmado lendo `metrics/live_runs/live_
> 2026-08-13T22.23.59.json` (`gate_status: "fail"`) — partida real
> `Marshall.D.Teach-BY_x_Rocks.D.Xebec-B_2026-08-13T22.23.56`, já banco.
>
> ~~Despriorizado pro objetivo atual (fortalecer o bot contra
> humano) — amostragem adaptativa no modo OFFLINE/self-play (hoje N
> fixo de 3-6 em `main_phase`, usado por `baseline_metrics.py` e pelo
> `/simulate` do front-end): serve mais a fidelidade do simulador do
> front-end e das próprias calibrações futuras que o bot ao vivo (que já
> tem o orçamento maior). Pendência antiga, ainda válida, só reordenada.~~
> **FEITO no bloco 480 (10/08)** — usuário pediu pra investigar/resolver
> antes do previsto, custo medido em +7,2% de tempo. Ver bloco 480 no
> topo deste arquivo e do HANDOFF.
>
> **Se isso [pondering] for retomado no futuro**: precisa de `multiprocessing` (processo
> separado, sem GIL compartilhado) em vez de `threading`, ou pausar/
> despriorizar o job de pondering quando uma requisição `/decide` real
> chega — nenhuma das duas é trivial. Não é uma ideia descartada, só a
> implementação testada não funciona. **ALERTA (bloco 525, mesclagem de
> branches)**: a branch `claude/execute-remote-control-3qzqgm` tinha uma
> implementação PRÓPRIA e independente de pondering (mesmo desenho,
> `threading`, nunca testada ao vivo) — muito provavelmente tem o MESMO
> bug de GIL. Ver bloco 525 do HANDOFF antes de decidir o que fazer com
> ela.
>
> **Foco volta pra calibração/auditoria da pontuação dinâmica** (pedido
> explícito do usuário, "continuar a calibração de lá" — já estava feita
> nos blocos 475-477, sem pendência nova aberta agora). Próximos itens
> ainda válidos, sem urgência:
> - Verificar se o piso/teto de amostragem AO VIVO (12/24, bloco 381) tem
>   folga pra subir, olhando telemetria real de latência.
> - Amostragem adaptativa no modo OFFLINE/self-play (N fixo de 3-6 hoje)
>   — serve mais a fidelidade do simulador do front-end que o bot ao
>   vivo, despriorizado.
>
> Contexto/evidência que motivou o pedido: calibração `_score_play_
> action` vs `attach_don`/`attack` quando competem pelo mesmo DON — 2
> fontes de evidência já levantadas (telemetria da partida ao vivo:
> Teach 119 score=190 perdeu pro Doc Q attach_don+ataque=265;
> `audit_real_losses.py`: no turno em que o Teach 119 foi jogado de
> verdade, o motor de hoje preferiria remover 2 personagens do oponente
> via ataque em vez de jogar a carta). Achado à parte, real mas NÃO
> explica esse caso específico: `_score_play_action` nunca desconta
> custo de oportunidade do DON gasto, diferente de `attach_don` —
> assimetria que FAVORECE "play", então não é a causa da divergência
> observada. Ver bloco 472/473 do HANDOFF pro relato completo.

> 09/08/2026 (bloco 472): **corrige regressão SEVERA introduzida pelos
> próprios blocos 470/471** — `_relevant_blocks` sempre misturou
> `on_play` e `trigger` da MESMA carta (nenhum dos dois é gatilho de
> combate), então uma carta com os dois blocos resolvendo em momentos
> DIFERENTES (Marshall D. Teach OP16-119: on_play sem alvo battlefield
> nenhum + trigger de vida com alvo opp_character) cravava
> `actor_opp_only`/`actor_battlefield_only` errado — os steps do
> on_play sem alvo implícito "somem" da conta, sobrando só os do
> trigger. Antes só deprioritizava (lento, mas funcionava); com a
> exclusão DURA dos blocos 470/471, isso zerava `own_hand`/`top_deck`
> por completo — o "look at top 3, add 1 to hand" do Teach 119 nunca
> completava (usuário: "jogou o teach 8 mas não ganhou vida", 68
> candidatos reais → só 24 sobreviviam, nenhum top_deck/own_hand). Fix:
> qualquer step sem alvo implícito cuja ação não está na allowlist seg
> ura (`_SAFE_NO_TARGET_ACTIONS`) agora "envenena" as duas detecções em
> vez de ser ignorado silenciosamente — reproduzido com o candidato
> real da partida, 67/68 sobrevivem agora. Investigado também: turno 5,
> por que anexou DON no Doc Q em vez de jogar o Teach 8 — jogada
> DEFENSÁVEL (Teach 8 não tem Rush, não ataca no turno que entra;
> attach_don+atacar converte o mesmo pool de DON em dano AGORA), não
> corrigido, fica como pendência secundária se o padrão se repetir.
> `smoke_fast`/`smoke_test` 100%, `audit_replay.py --n 20` (seed=98)
> validado. Ver bloco 472 do HANDOFF.

> **RESOLVIDO (bloco 471, fechado 09/08/2026 na sessão do bloco 476)**:
> `decisions_2026-08-09T09.57.32.jsonl` idx 78 (turno 4) — o motor tinha
> `attack OP16-104 -> character OP17-042` disponível com `score=277.0`
> (eligible/não-excluído, matava o alvo) e escolheu `attack OP16-104 ->
> leader` com `score=268.0`, o score MENOR. **Não é bug** — confirmado
> lendo `search_values`/`line_search` da própria decisão:
> `selection: "counterfactual_search"`, a busca (`line_search.depth=4`,
> `counterfactual_basis: "sampled_opponent_model"`) atribuiu VALOR de
> sequência completa de 313.0 pro ataque ao líder contra só 129.67 pro
> ataque ao personagem — mesmo com a postura marcada `REMOVE_THREAT`, a
> busca projetada (que simula o resto do turno + resposta provável do
> oponente) achou que pressionar o líder rendia mais valor esperado que
> remover aquele personagem específico ali. O score bruto de
> `score_attack_target` é só sinal de geração de candidato, não o
> critério final quando há mais de 1 candidato — a busca decide. Não
> mexer em heurística de ataque por causa deste caso específico.

> 09/08/2026 (bloco 471): **investiga as 4 observações do usuário** na
> mesma partida do bloco 470 (Marshall.D.Teach-BY_x_Rocks.D.Xebec-B).
> 2 bugs reais achados e corrigidos: (a) Shiryu (custo 6/8000 poder, a
> carta de maior impacto da mão) foi trashada como custo de um Counter
> em vez de qualquer outra carta — `_trash_value` só protegia custo≥7,
> nunca cobria um corpo grande de custo mais baixo; generalizado pra
> `cost≥7 OR power≥7000`. (b) Regressão no PRÓPRIO fix do bloco 470
> (pega antes de subir): a exclusão dura de `actor_battlefield_only`
> quebrava o pagamento de custo de mão pra cartas como "You're the One
> Who Should Disappear" (alvo do efeito é campo, mas o CUSTO é
> trash_from_hand) — `actor_effect_has_hand_cost` mantém own_hand
> liberado nesse caso, + fix no `sort_key` que empatava own_hand em
> vez de ordenar por `_trash_value`. 2 observações investigadas e
> explicadas como jogadas CORRETAS, não bugs: redirect pro Doc Q
> (sacrifício de corpo morto, protege vida) e redirect pro Burgess em
> vez do Vasco Shot (Burgess tem imunidade a K.O. do oponente — redirect
> sem risco nenhum, "Attack Fails"). 1 achado real NÃO corrigido (ver
> pendência prioritária acima). `smoke_fast`/`smoke_test` 100%,
> `audit_replay.py --n 20` (seed=97): 0 exceções, 0 anomalias. Ver
> bloco 471 do HANDOFF.

> 09/08/2026 (bloco 470): **RETIFICA o bloco 466** — Doc Q travou de novo
> numa partida real nova (`Marshall.D.Teach-BY_x_Rocks.D.Xebec-B_
> 2026-08-09T10.23.52`, mesmo sintoma: K.O. "up to 2" com só 1 alvo
> elegível, 2º slot nunca fecha, efeito inteiro cancelado). O fix
> anterior (filtro numérico cost_lte/power_lte/power_gte) SÓ excluía
> dentro de `opp_board`/`own_board` — `opp_hand` (mão oculta do
> oponente) nunca foi tocada, só deprioritizada pelo mecanismo mais
> antigo `actor_battlefield_only` (nunca excluída de verdade, igual o
> `own_trash` do achado 20/07). Fix real: `actor_battlefield_only` agora
> EXCLUI DURO qualquer zona fora de campo/líder (mesmo padrão já usado
> pro `actor_opp_only`/Pekoms). Teste antigo endurecido (era "por
> último", agora "excluído") + teste novo com lista realista (opp_hand
> junto do opp_board). `smoke_fast`/`smoke_test` 100%, `audit_replay.py
> --n 20` rodando. **Pendente, ainda não investigado**: 4 observações do
> usuário na mesma partida — Doc Q vs Vasco Shot no turno 6 (lookahead),
> bot nunca jogou "bomba" nenhuma, bot focou em vida sem remover
> Character do oponente, redirect do turno 6 deveria mirar Vasco Shot em
> vez de Burgess. Ver bloco 470 do HANDOFF.

> 08/08/2026 (bloco 469): **fecha a inconsistência do `HABILITA_ATAQUE_
> BONUS`** notada revisando o commit `1805815` (bloco 467) — a gate
> `tenho_atacante` (só dá o bônus de "sair antes do ataque" quando há
> atacante disponível pra proteger) tinha ficado só em
> `_score_activate_main`/"remoção-controle". Propagada pra
> `_score_play_action` (jogar carta da mão com on_play de kos/
> is_removal/bounces/rests_opponent) — `power_buff`/`draws`/
> `is_searcher`/`has_rush`/`when_attacking` ficam de fora de propósito
> (semântica diferente, não é "só simetria"). **Revisão ampla também
> pedida** encontrou 2 gaps reais em `_score_activate_main`: categorias
> `play_card` (33 cartas, jogar de graça via habilidade) e `play_from_
> trash` (8 cartas, reanimação via habilidade) nunca davam prioridade
> de sequenciamento pro candidato jogado/reanimado ter rush (atacante
> novo) ou remoção (gate por atacante) — mesmo gap do Teach 10, em 2
> caminhos que ainda não tinham sido revisados. `add_don`/`set_don_
> active`/`give_don` ficaram de fora (já têm lógica própria calibrada,
> mais precisa que um bônus genérico). 3 testes novos, cada um provando
> a diferença exata de 60 pontos com/sem atacante disponível.
> `smoke_fast`/`smoke_test` 100%, `audit_replay.py --n 20`: 0 exceções,
> 0 anomalias. Ver bloco 469 do HANDOFF.

> 08/08/2026 (bloco 468): **fecha a pendência do bloco 462/459** —
> amostra maior (N=50, 750 partidas) CONFIRMA `HABILITA_ATAQUE_BONUS`
> em 60 com confiança real (diferente do bloco 459, "mantido por falta
> de confiança pra mudar"). A N=50 o agregado INVERTE em relação ao
> N=15 (que favorecia 0): 60 vence o agregado (41.6% vs 36.0% em 0 vs
> 39.6% em 120) — caso mais claro é Enel vs Mihawk, que a N=15 parecia
> favorecer fortemente 0 (73.3%) mas a N=50 revela como o PIOR valor
> (26.0%), confirmando ruído de amostra pequena. Valor não mudou (já
> era 60), só o comentário da constante. Sessão remota (bloco 462
> original) mesclada com 5 blocos de uma sessão LOCAL em paralelo
> (463-467, ver abaixo) via `git merge origin/main` a pedido do
> usuário. Ver bloco 468 do HANDOFF.

> 08/08/2026 (bloco 467): **fecha a pendência do bloco 466** — Teach 10
> (OP09-093, `negate_effect`) atacava antes de ativar, quando deveria
> ser o inverso. `_score_activate_main` nunca tinha o equivalente do
> `HABILITA_ATAQUE_BONUS` que `_score_play_action` já tem pra "sair
> antes do ataque". Fix: categoria remoção/controle ganha o bônus
> (+60) quando há atacante disponível e o alvo tem valor real;
> `negate_effect` especificamente ganha +150 extra (protege TODOS os
> ataques do turno, não só remove um alvo). Validado com o cenário
> exato da partida real: activate foi de 170 (perdia pro ataque de
> 288) pra 380 (agora supera). 2 testes novos, `smoke_fast.py`/
> `smoke_test.py` 100%, `audit_replay.py --n 20 --seed 84`: 0
> exceções, 0 anomalias. Ver bloco 467 do HANDOFF.

> 08/08/2026 (bloco 466): **corrigido bug real do Doc Q** —
> `order_target_candidates` nunca excluía candidato de campo que batia
> a zona certa mas não o filtro numérico (`cost_lte`/`power_lte`/
> `power_gte`) do próprio efeito. Com só 1 alvo válido pro "K.O. até 2
> com custo ≤1", o 2º slot pedia a mesma lista de 37 candidatos sem
> filtro 2x seguidas (23s de diferença) até esgotar e cancelar o
> efeito inteiro — nem o 1º alvo já escolhido resultava em KO. Fix
> conservador (só aplica quando há exatamente 1 step de campo com
> filtro numérico), sweep nas 2747 cartas do banco sem erros, 231
> cartas com impacto potencial. 2 testes novos, `smoke_fast.py`/
> `smoke_test.py` 100%, `audit_replay.py --n 20`: 0 exceções, 0
> anomalias. **Pendências da mesma rodada**: Teach 10 (OP09-093)
> ativado DEPOIS do ataque em vez de antes (mesma classe do fix do
> Newgate, mas pra `activate` em vez de `play` — não corrigido,
> precisa generalizar `HABILITA_ATAQUE_BONUS`); Teach 8 "não ganhou
> vida" investigado mas os dados do log contradizem o relato (vida foi
> ganha) — sem bug confirmado, pedir turno exato se acontecer de novo.
> Ver bloco 466 do HANDOFF.

> 08/08/2026 (bloco 465): **fechado o achado do bloco 464** — causa
> raiz do "poderia ter ganho 1 turno antes". Bug de 2 partes: (1)
> `REMOVE_THREAT`/`DEFENSIVE` descontava -100/-80 do ataque ao líder
> mesmo com a vida do oponente já crítica (0/1), onde qualquer conexão
> vence o jogo — agora só desconta com `opp_life > 1`. (2) mesmo
> corrigido (1), o valor-base "vida crítica, sem letal certificado"
> (130/220) ainda perdia pra um ataque a Character bem pontuado —
> subido pra 300/220→260, validado batendo o cenário exato da partida
> real (300 agora vence os 220 do Character-ameaça). 2 testes novos,
> `smoke_fast.py`/`smoke_test.py` 100%, `audit_replay.py --n 20` 2x
> (seeds 51 e 62): 0 exceções, 0 anomalias. Ver bloco 465 do HANDOFF.

> 08/08/2026 (bloco 464): 🎉 **primeira vitória real do bot ao vivo**
> (`Rocks.D.Xebec-B_x_Portgas.D.Ace-R_2026-08-08T10.55.01`). Achado
> real (não corrigido) investigando a observação do usuário ("poderia
> ter ganho 1 turno antes atacando a vida"): no turno 5, com o
> oponente já em 0 vida, a decisão de atacar a vida com o líder (folga
> de poder de +2000, deveria pontuar alto) registrou score **30** ao
> vivo, mas reconstruindo o EXATO mesmo estado e chamando
> `score_attack_target` isoladamente o resultado é **130** — mesmos
> dados, resultado diferente. Aponta pra um bug real onde a busca
> contrafactual usa um estado interno diferente do que fica gravado em
> `state_before` na telemetria. Causa raiz não localizada — precisa de
> instrumentação por dentro da busca (não só reconstrução externa) na
> próxima sessão. Ver bloco 464 do HANDOFF.

> 08/08/2026 (bloco 463): 3 logs pedidos pelo usuário bancados (humano
> x humano, sem bot — sem telemetria aplicável). Achado operacional
> importante: `CombatLogs`/`AutoSaved` são sobrescritos AO VIVO pelo
> client enquanto uma partida está rodando — 6 dos 10 arquivos
> investigados encolheram pra um stub de 3 linhas entre uma leitura e
> outra, e uma cópia de resgate em `/tmp` (em vez do scratchpad
> correto) também sumiu numa pausa. Recuperação via variante `_p2.log`
> (perspectiva do outro jogador, nome de arquivo diferente, sobreviveu)
> funcionou pros 3 pedidos. **3 partidas extras perdidas de verdade**
> (sem `_p2`) — não recuperáveis. Ver bloco 463 do HANDOFF pra lição
> completa antes de mexer em CombatLogs/AutoSaved de novo.

> 07/08/2026 (bloco 461): **fecha a última pendência da linha "draw N
> Then/and [...]"** — EB02-024 (Sogeking) tinha a cláusula "place 2
> cards from your hand at the bottom of your deck in any order" **inteira
> ausente** do parseado (gap de COBERTURA, distinto dos bugs de ORDEM já
> fechados nos blocos 456/457). Censo global achou **9 cartas base** em 2
> formas: 7 STEP (efeito obrigatório ausente — EB02-024, OP04-053,
> OP05-046, OP05-054, OP06-045, OP07-056, ST22-002) + 2 CUSTO (tratado
> como grátis — OP01-011, OP09-060). Fix: `parse_draw` ganhou regex STEP
> reusando a action `hand_to_deck` já existente (guardado contra a
> variante custo via "sem `:` antes do próximo `.`"); `parse_costs`
> ganhou cost type novo `place_hand_bottom_deck` espelhando
> `place_hand_top_deck`, pago em `_pay_costs` (decision_engine.py).
> Efeito colateral: 1 teste pré-existente (Page One/OP04-053) tinha
> asserção calibrada só pro draw, sem saber da 2ª cláusula ausente na
> MESMA carta — corrigida. Registrado em `parser_audits/2026-08-07_
> familia_place_hand_bottom_deck.json`. `diff_parser.py` PERDEU=0,
> `smoke_fast`/`smoke_test` 100%. **Linha "draw N Then/and [...]" agora
> integralmente fechada** (blocos 456/457/461), nenhuma pendência nova.
> Pendência restante não perseguida: `HABILITA_ATAQUE_BONUS` (bloco 459)
> se beneficiaria de amostra de self-play maior que N=15. Ver bloco 461
> do HANDOFF.

> 06/08/2026 (bloco 460): **lidos os 14 casos residuais do Katakuri**
> (pendência dos blocos 442/443, "16 casos não lidos") — **2 bugs reais
> de engine achados e corrigidos**. (1) 3 dos 14 casos eram VITÓRIAS
> SILENCIOSAS: `_execute_attack` não imprimia nada no caminho "dano com
> 0 vidas" (verbose=True), fazendo a narrativa parecer que o motor
> "parou de atacar" quando na verdade tinha GANHO o jogo ali. Fix: 1
> print adicionado. (2) **Mais sério**: crash intermitente
> (`TypeError: '>' not supported between 'int' and 'str'`) reproduzido
> rodando `audit_real_losses.py` repetidamente — `cost_lte='don_count_opp'`
> (sentinela dinâmico, só usado por Charlotte Katakuri OP08-062 e
> Charlotte Smoothie P-090) nunca era resolvido em **6 cópias
> diferentes** da mesma regra de elegibilidade espalhadas pelo motor
> (`_step_is_viable`, `_execute_step`, `_should_activate_main`,
> `_stage_play_saves_don_for_card`, `_score_play_action`,
> `_score_activate_main`) — todas tratavam `'don_count_self'` mas
> nenhuma tratava `'don_count_opp'`. Fix: 2 cópias passaram a delegar
> pra `_resolve_cost_lte()` (fonte única já correta), as outras 4
> ganharam o `elif` que faltava. Reproduzido ANTES (15 tentativas, ~5
> crashes) e confirmado 0 crashes DEPOIS (15/15). **Os outros ~11 casos
> não mostraram padrão claro de bug** — DON alocado diferente, às vezes
> até melhor (ex: Krieg-RG turno 9, motor de hoje nocauteia um Blocker
> que a linha histórica não pegou) ou diferença de composição de
> baralho plausível (reconstrução embaralha ordem). `smoke_fast` (3
> testes novos)/`smoke_test` 100%. Relatórios de auditoria regenerados
> durante a investigação mas revertidos antes do commit (reconstrução
> não-determinística, regenerar os 55 arquivos só introduziria ruído
> aleatório). Ver bloco 460 do HANDOFF.

> 06/08/2026 (bloco 459): **calibração de `HABILITA_ATAQUE_BONUS`
> concluída — CONFIRMA dependência de deck na constante REAL** (não só
> na política gulosa simplificada do bloco 449). Sweep de self-play com
> o motor de produção (Enel/Nami/Ace/Imu vs Mihawk + Enel vs Nami, N=15,
> valores 0/60/120): Nami vs Mihawk piora **monotonicamente** com bonus
> maior (26.7%→20.0%→6.7%, sinal mais limpo), Enel vs Nami prefere
> fortemente o valor atual (93.3% em 60). **Decisão: MANTIDO em 60** —
> nenhum candidato vence com confiança dado o ruído (N=15). Amostra
> maior fica registrada como pendência futura pra calibração com
> confiança de verdade. `smoke_fast`/`smoke_test` 100%. Ver bloco 459 do
> HANDOFF.

> 06/08/2026 (bloco 458): **confirma e fecha o gap da PROTEÇÃO EXTERNA**
> de substitute (pendência teórica registrada no bloco 455).
> `_source_conditions_met_for_substitute()` (protetor ≠ protegido) não
> tinha o mesmo guard que `try_substitute()` (autoproteção) já tinha
> ganhado — confirmado REAL (não só teórico) com Roronoa Zoro (OP17-095,
> `no_filter=True`, protege qualquer personagem seu): sem o fix, Zoro só
> protegia A SI MESMO, nunca um aliado, quando faltava a condição do buff
> irmão (que não tem nada a ver com o substitute). Mesmo princípio do
> bloco 455 aplicado no gêmeo. `smoke_fast` (1 teste novo)/`smoke_test`
> 100%. Sem `parser_audits/` novo (fix 100% em decision_engine.py). Ver
> bloco 458 do HANDOFF.

> 06/08/2026 (bloco 457): **fecha a variante "Draw N AND [...]"**
> (conjunção, não "Then,") — última pendência da família de ordem de
> steps, pedido explícito do usuário. Censo refinado (excluindo o idioma
> atômico "draw N and trash 1 card from your hand", já tratado certo
> como 1 step só): 61 ocorrências / 33 códigos-base, lidas
> individualmente. **9 cartas com inversão real** — OP13-102 (achado
> original), OP14-002, OP14-038, OP14-049, OP16-109, OP16-110, OP17-027,
> OP17-031 (pré-existentes) + EB02-024. Fix genérico: 'draw' sempre move
> pra posição 0 quando o padrão bate (confirmado ser sempre a 1ª
> cláusula gramatical nessa forma). Sem impacto de jogo confirmado.
> **Achado colateral não corrigido**: EB02-024 tem uma cláusula inteira
> ("place 2 cards... at the bottom of your deck") que nunca vira step —
> gap de COBERTURA, não de ordem, pendência nova registrada. `diff_parser`
> MUDOU=25 (15 anteriores + 10 novos), 0 regressões, `smoke_fast`(6 testes
> novos)/`smoke_test` 100%. **Com isso, as duas variantes da família
> "draw N [conector] [...]" estão integralmente auditadas.** Ver bloco
> 457 do HANDOFF e `parser_audits/2026-08-06b_familia_draw_n_and_conjuncao.json`.

> 06/08/2026 (bloco 456): **auditoria COMPLETA da família "Draw N. Then,
> [...]"** — fecha a pendência residual deixada em aberto no bloco 454
> (só o par draw+lock de OP17-065 tinha sido corrigido; a família mais
> ampla tinha sido censada mas não auditada carta por carta). Leu as 44
> cartas-base do censo uma a uma: **39/44 já corretas**, **1 inversão
> real** — ST22-017 (Fire Fist), "Draw 1 card. Then, place... at the
> bottom of the owner's deck" saía com `place_opp_character_bottom_deck`
> ANTES do `draw`. Fix pontual (mesma técnica do bloco 454), sem impacto
> de jogo confirmado (consistência com a ordem real de execução).
> Achado colateral fora do escopo: OP13-102 usa "and" (simultaneidade),
> não "then," (sequência) — pendência menor separada, não corrigida.
> `diff_parser` MUDOU=15 (14 do bloco 454 + ST22-017), 0 regressões,
> `smoke_fast`/`smoke_test` 100%. Ver bloco 456 do HANDOFF e
> `parser_audits/2026-08-06_familia_draw_n_then_auditoria_completa.json`.

> 06/08/2026 (bloco 455): **fechada a pendência do guard `is_substitute_fb`**
> (registrada desde o bloco 448, protegia até 38 cartas). Quando um bloco
> sem tag formal mistura um `substitute_ko`/`substitute_removal` com OUTRO
> step independente, a 'conditions' do BLOCO INTEIRO vazava e gateava
> TAMBÉM o substitute (que deve ser sempre auto-contido). Censo achou 5
> cartas — OP07-029, OP14-034, ST15-005, ST25-003 (**pré-existentes**) +
> OP17-095 (achado original). **1ª tentativa de fix no PARSER foi
> REVERTIDA** — quebrava `apply_conditional_keyword_passives` (gateia
> gain_blocker/gain_rush pela 'conditions' do NÍVEL DO ENTRY, não por
> step) para OP07-029/ST15-005. Fix real ficou no CONSUMIDOR
> (`try_substitute()`, decision_engine.py) — zero mudança no parser/JSON.
> `smoke_fast`/`smoke_test` 100% (1 teste novo, 4 asserts, prova que o fix
> não vazou pro outro consumidor). Sem `parser_audits/` novo (nenhum
> arquivo de parser tocado). **Pendência residual**: proteção EXTERNA
> (`_try_external_substitute_from_source`) tem gap teórico similar, sem
> carta real confirmada ainda. Ver bloco 455 do HANDOFF.

> 05/08/2026 (bloco 454): fechados os **2 ÚLTIMOS achados do bloco 450**
> — auditoria completa do OP17 (10/10) **CONCLUÍDA**. (D) OP17-040
> Edward.Newgate: "When your Leader attacks or is attacked" (reativo
> BIDIRECIONAL sem tag formal) estava fundido dentro do [On Play],
> disparando ao JOGAR a carta em vez de na batalha do líder — vira
> trigger dedicado `leader_battle_reactive` (2 pontos novos em
> `_execute_attack`), não uma duplicação simples em when_attacking/
> on_opp_attack (essa abordagem inicial foi corrigida antes de commitar —
> só funciona quando a fonte É o líder, não quando um CHARACTER concede a
> habilidade a ele, como Newgate). Bônus: OP03-001 (Portgas.D.Ace, LÍDER)
> tinha a MESMA cláusula, caía em 'passive' e nunca disparava — corrigido
> junto. (J) Ordem de steps É a ordem de execução real (não cosmética) —
> "Rest ... Then, K.O. ... rested ..." saía com o K.O. ANTES do rest que
> gera o alvo, bug de jogo real. 5 cartas achadas — OP04-038, OP10-024,
> OP10-041, OP12-029 (**pré-existentes**) + OP17-036. Sub-achado OP17-065
> (draw/lock) mesmo tratamento, sem efeito de jogo confirmado. `diff_parser`
> MUDOU=8, 0 regressões, `smoke_fast`/`smoke_test` 100% (2 testes novos).
> Ver bloco 454 do HANDOFF e `parser_audits/2026-08-05g_...json`.

> 05/08/2026 (bloco 453): fechados **3 dos 5 achados de mecânica NOVA**
> que faltavam do bloco 450 — Rockstar (OP17-034, nova condição
> `opp_leader_power_gte` — poder do LÍDER DO OPONENTE, nunca existia),
> Kaido+Xebec (OP17-063/OP17-118, 2 sub-mecânicas de counter em mão:
> `buff_hand_counter_no_counter` em massa e
> `buff_own_hand_counter_if_no_others` self-referencial) e
> `leader_is_or_type` + filtro de alvo com 2 tipos OR (OP17-003/004/007
> — achado durante o censo: o regex genérico do 2º tipo também pegava
> ST12-003 por engano, "Slash" ali é ATRIBUTO não TYPE — corrigido com
> lookahead negativo antes de commitar). `diff_parser` MUDOU=6, 0
> regressões, `smoke_fast`/`smoke_test` 100% (2 testes novos). **Faltam
> D, J** do bloco 450 (bug de timing/ordem de step) — não tocados. Ver
> bloco 453 do HANDOFF e `parser_audits/2026-08-05f_...json`.

> 05/08/2026 (bloco 452): fechados os 3 achados **baratos/isolados**
> restantes do bloco 450 — Blenheim (OP17-012, "play card" genérico sem
> "Character"), Don Marlon (OP17-052, custo exato faltando em
> `add_from_trash` — achou 2 cartas pré-existentes de bônus: Mr.1
> Daz.Bonez, Saint Mjosgard) e Ulti & Page One (OP17-060, faltava a
> palavra "card" após "DON!!"). Escopo do achado F reduzido de propósito
> (não fiz o filtro Event/Character — tentativa inicial afetaria 25
> cartas de uma vez, revertido). `diff_parser` MUDOU=5, 0 regressões,
> `smoke_fast`/`smoke_test` 100%. **Faltam A, C, D, H, J** do bloco 450
> (mecânica nova, maior escopo) — não tocados. Ver bloco 452 do HANDOFF.

> 05/08/2026 (bloco 451): implementados os 2 achados de **maior
> impacto** do bloco 450. **Taunt** ("opponent cannot attack any card
> other than [Nome]") — afeta Eustass Kid (OP01-051, meta) e Captain
> John (OP17-044) — novo `force_opp_attack_self` + `self_rested`
> (bônus: corrige 3 cartas pré-existentes que disparavam
> incondicionalmente — Rosinante, Kouzuki Oden, Shanks) +
> `active_taunt_character()` chamada nos 3 pontos que decidem
> ataque/lethal. **Aura de Blocker do líder Luffy** (OP17-079) — a
> habilidade central dele estava vazia — novo `grant_blocker_aura`
> (mesmo padrão de `grant_rush_aura`). 2 testes novos permanentes em
> `smoke_fast.py`. `diff_parser` MUDOU=7, 0 regressões,
> `smoke_fast`/`smoke_test` 100%. **Faltam 8 achados** do bloco 450 (A,
> B, C, D, F, G, H, J), menor impacto — não tocados. Ver bloco 451 do
> HANDOFF e `parser_audits/2026-08-05d_...json`.

> 05/08/2026 (bloco 450): **auditoria completa das 103 cartas do OP17**
> (texto vs mecânica), pendência aberta desde o bloco 447. **7 bugs
> genéricos corrigidos** (censo global antes de cada um, `diff_parser`
> PERDEU=0): `[Rush:Character]` sem espaço, "rest ALL"/"place ALL" sem
> suporte a "all", `type including X` faltando em `set_active`, custo
> exato (`cost_eq`) faltando no parser E no executor de
> `place_opp_character_bottom_deck`, bullet "-" não reconhecido em
> "opponent chooses one" (bug sério: os 2 efeitos aplicavam juntos em
> vez de escolher 1), e o maior — "rest N DON!! **and this Character**"
> (ordem invertida) fazia a habilidade disparar **sem restar a própria
> carta** (custo real a menos). A maioria dos bugs afetava cartas
> **PRÉ-EXISTENTES** também (7 cartas jogáveis de verdade: Rosinante,
> Laffitte, Sugar, Ishilly, Shirahoshi, Kouzuki Hiyori, Luffy ST23-004),
> não só a transcrição manual do OP17. **10 achados registrados, SEM
> fix** (exigem mecânica nova, mais arriscado) — destaque pros 2 de
> maior impacto: Eustass Kid (OP01-051, carta de meta) e o líder
> Monkey.D.Luffy (OP17-079) têm mecânicas centrais (taunt / aura de
> Blocker em massa) **completamente ausentes**. `smoke_fast`/`smoke_test`
> 100%. Ver bloco 450 do HANDOFF e
> `parser_audits/2026-08-05c_...json` pra lista completa.

> 05/08/2026 (bloco 449): **teste pareado BARATO** do achado do bloco
> 446/448 (Marco/Ohm/Satori jogados depois do último ataque) — a
> tentativa anterior (447 Parte 3) travou >20min; redesenho substitui
> `main_phase` por loop guloso simples (sem Monte Carlo) nos dois lados,
> rodou 10 matchups x 60 seeds x 2 variantes em 1min45s. **Achado real,
> mas DEPENDENTE de deck**: Enel se beneficia MUITO forçando a ordem
> (70%→95%, 80%→92%, 52%→63% win rate), Nami/Ace pioram bastante contra
> Mihawk (38%→17%, 40%→23%), Imu fica quase neutro. Não existe veredito
> uniforme — qualquer fix futuro no bônus de ordem precisa ser calibrado
> por deck, não um valor fixo universal. **Sem fix aplicado**, script
> descartável não commitado. Ver bloco 449 do HANDOFF.

> 05/08/2026 (bloco 448): **auditoria global do bloco 447 concluída**.
> Causa raiz do bug do OP17-005 não era gramática — era um `\n` literal
> (2 caracteres, não quebra de linha real) na transcrição manual do
> OP17, quebrando a detecção de tag pra QUALQUER bloco. Achado em **72
> cartas** (100% OP17, 0 no resto do banco). **Fix de dado**: `\n`
> literal → quebra real nas 72 linhas — resolve **65 cartas** (`diff_parser`
> GANHOU=0 PERDEU=0 MUDOU=65). **Fix genérico de código**: `parse_add_from_trash`
> não aceitava "other than [X]" depois de "from your trash" (só antes) —
> generalizado, 1 carta beneficiada (Gerd OP17-081) após censo global.
> **Pendência nova, não corrigida**: OP17-095 ainda funde 2 cláusulas
> independentes por causa de um guard (`is_substitute_fb`) que protege
> até 38 cartas no banco — mexer nele precisa de investigação própria,
> registrado pra sessão futura. `smoke_fast`/`smoke_test` 100%. Ver
> bloco 448 do HANDOFF e `parser_audits/2026-08-05b_...json`.

> 05/08/2026 (bloco 447): **Branch remota trazida pra `main`** (23
> commits) — bug histórico de conservação de DON confirmado resolvido
> (`audit_replay.py --n 20`: 0 anomalias, incluindo Black Imu). **OP17
> ingerido pela primeira vez** (103 cartas, transcritas manualmente das
> imagens do jogo — nem Supabase nem a API optcgapi.com têm o set ainda).
> 100/103 já parseiam com a gramática existente (3 vanillas corretamente
> vazias). **Pendências reais**: (1) 1 bug de classificação achado em
> OP17-005 (cláusulas condicional/incondicional misturadas no mesmo
> bloco) — não corrigido, precisa de auditoria global da mesma forma;
> (2) as ~95 cartas restantes só tiveram cobertura checada, não
> corretude semântica linha a linha; (3) não verificado se mecânicas
> novas do set (gatilho "Character custo 12+", seleção coletiva
> [King]/[Queen]/[Jack]) têm suporte real em `_execute_step` ou geram
> step ignorado silenciosamente. Ver bloco 447 do HANDOFF.
>
> **Teste pareado do achado do bloco 446 (efeito habilitador jogado
> depois do último ataque) tentado e abandonado** — script travou
> consumindo CPU por >20min sem terminar 1 partida sequer (monkeypatch
> forçando score máximo o tempo todo provavelmente inflou demais a
> busca contrafactual). Matado, apagado, sem conclusão — achado do
> bloco 446 continua nem confirmado nem descartado.

> 05/08/2026 (bloco 446): investigado sequenciamento DENTRO do turno
> (atacar vs blocker vs ramp vs ativação, pedido do usuário). Self-play
> instrumentado, 80 jogos/976 turnos: ramp de uso imediato e
> Activate:Main habilitador estão sólidos (quase 0 violações de ordem).
> Achado que sobra: **~115 casos (11,8% dos turnos)** de carta com
> efeito on-play habilitador (K.O./buff/bounce, mesmo critério do bônus
> real `habilita_ataque`) jogada DEPOIS do último ataque do turno —
> mesma classe do bug já corrigido do Edward Newgate (bloco 02/08), mas
> **não confirmado como perda real** (não dá pra saber pela narrativa
> verbose se o alvo removido bloquearia o ataque anterior). Cartas
> concentradas: Marco (Alternate Art) 26x, Ohm (Alternate Art) 22x,
> Satori 11x. **Sem fix aplicado** — precisa de instrumentação mais
> funda ou teste pareado (ordem forçada) antes de mexer em código. Ver
> bloco 446 do HANDOFF.

> 04/08/2026 (bloco 445): investigado o item aberto "consciência de
> combos estratégicos do oponente" (`opp_combo_threat`/PREVENT_COMBO,
> nunca calibrado formalmente). Dispara **208x em 15 partidas**
> (Enel vs Imu) — limiar `magnitude>=2` é bem mais permissivo do que
> parecia. Teste pareado (N=25, atual vs desligado) mostrou impacto
> **praticamente nulo** no win rate real (Enel/Nami idênticos, Ace só
> 1/25 partida mudou) — nem ajuda nem atrapalha nestes 3 matchups.
> **Sem fix aplicado**, achado honesto/inconclusivo. Próximo passo
> (não feito): testar contra adversário com mais counter/blocker, ou
> isolar o turno exato do combo de verdade. Ver bloco 445 do HANDOFF.

> 04/08/2026 (bloco 444): **item 6 fechado** (último dos itens 4-6
> pedidos pelo usuário) — threat-assessment de efeitos "rest"/"freeze"
> do oponente (tipo Carrot/`lock_opp_character_refresh`, 153 cartas).
> Não existe modelo preditivo (diferente de Counter/Blocker, que têm
> sinal visível), mas validado em self-play real (Imu x Mihawk) que a
> execução REATIVA funciona certo e o bot não desperdiça ação tentando
> usar um personagem congelado — segue o plano com outros recursos.
> **Sem bug confirmado.** Itens 4-6 do pedido original encerrados
> nesta sessão. Pendente não-prioritário: 16 dos 18 casos residuais do
> Katakuri (bloco 442/443) ainda não lidos manualmente. Ver bloco 444
> do HANDOFF.

> 04/08/2026 (bloco 443): **item 5** (Mihawk, mais dado) — +60 seeds
> focados (sem log real desse matchup no banco), combinado N=90:
> **24,4% de vitória** (bem melhor que os 16,7% isolados de N=30),
> DON/atk 1,54 saudável. Confirma que era parcialmente ruído — Mihawk
> segue o matchup mais difícil, mas não catastrófico. **Katakuri**: li
> 2 dos 18 casos residuais do bloco 442, ambos parecem trade-offs de
> orçamento de DON legítimos, não bug claro (16 casos ainda não lidos).
> **Item 6 (threat-assessment de efeitos "rest" do oponente) não
> iniciado** — pendente. Ver bloco 443 do HANDOFF.

> 04/08/2026 (bloco 442): **RETIFICA o achado do bloco 440/441**. Lendo
> os turnos residuais manualmente, achei 2 bugs em
> `triage_real_losses.py` (detecção de ataque ao líder buscava a
> string literal "Leader", que o log nunca usa; e um segundo bug de
> case-sensitivity em `card_type`). Números corretos: motor ataca líder
> **mais** em 132 casos (não 246), **menos** em 44 (não zero — a
> "sem regressão" reportada antes estava errada), igual em 87. O sinal
> do fix de 29/07 ainda existe mas é bem mais fraco/ruidoso que os
> "92% confirmação limpa" anunciados antes. **Novo achado não
> investigado**: 18 dos 44 casos de "ataca menos" envolvem partidas do
> líder Charlotte Katakuri — pista pra próxima sessão. Ver bloco 442
> do HANDOFF pra lição aprendida (validar ferramenta de medição contra
> caso manual antes de aceitar percentual agregado).

> 04/08/2026 (bloco 441): investigando o resíduo do bloco 440 (caso
> Bartholomew Kuma), achei bug **conceitual** no `DonEstimator` — DON
> gasto em play/activate NÃO é perda permanente (desresta sozinho no
> refresh do próximo turno; só `attach_don` fica preso de verdade).
> Reescrito, re-rodado (0 erros). **Confirmado**: motor de hoje passa a
> jogar o Kuma no mesmo turno que o histórico após o fix — era bug da
> FERRAMENTA, não do bot. Resultado final: MATCH 0,7%, DIVERGE 99,3%
> (92,5% ainda é o padrão já confirmado do fix `ATTACK_LEADER_BASE_
> SCORE`). 20 turnos residuais sobram, parte é artefato de
> normalização de nome (Imu vs Imu Alternate Art) na própria
> ferramenta de triagem, não bug do motor. **Nenhum bug novo
> confirmado no motor nesta rodada** — investigação real, causa raiz
> achada, só que na camada da ferramenta. Ver bloco 441 do HANDOFF.

> 04/08/2026 (bloco 440): **primeira triagem dos 268 turnos** (nova
> ferramenta `triage_real_losses.py`, registrada em CLAUDE.md/AGENTS.md).
> Achado forte: 92% da "divergência" é o motor de hoje atacando o líder
> MUITO mais que o histórico, correlacionado (212/238) com logs
> **anteriores a 29/07** — confirma em dado REAL o fix
> `ATTACK_LEADER_BASE_SCORE` (bloco 395). Zero casos de atacar menos
> (sem regressão). **Bug achado e corrigido na própria ferramenta**:
> `DonEstimator` não contava efeitos "Activate N Don"
> (`set_don_active`, mecânica central do Mihawk) — corrigido, re-rodado
> nas 59 partidas, 0 erros. **Pendente**: ~20 turnos residuais não
> explicados pelo fix de 29/07 — próximo passo é investigar se são
> achado real. Ver bloco 440 do HANDOFF.

> 04/08/2026 (bloco 439): **nova ferramenta permanente**
> `scriptis_da_ia/audit_real_losses.py` — reconstrói o estado de uma
> derrota REAL do bot contra humano turno a turno e pergunta pro motor
> de hoje o que ele faria, comparando com o que aconteceu de verdade.
> Registrada em CLAUDE.md **e** AGENTS.md (seção nova, espelhada) pra
> nenhuma sessão futura esquecer/reinventar. Validada: 59/59 derrotas
> reais processadas, 268 turnos, só 2 com erro interno (não derrubou a
> auditoria). Relatórios em `metrics/real_loss_audits/*.json`
> (commitados). **Próximo passo pendente, não feito ainda**: triar os
> 268 turnos — separar "motor já mudou de decisão" (bom sinal) de
> "motor repete a mesma escolha que perdeu" (achado real, investigar).
> Ver bloco 439 do HANDOFF.

> 04/08/2026 (bloco 438): **encerra a auditoria do bloco 434** — os 6
> pontos sinalizados com o mesmo padrão "power sem power_buff" foram
> todos resolvidos: 1 falso positivo (~7184, já usava
> `effective_power()`) e 5 corrigidos de verdade (`score_attack_target`
> líder/character, bônus de `give_don` fecha-deficit, re-check
> redundante em `_generate_and_score_actions`, candidatos de
> `attach_don`). `smoke_fast.py`/`smoke_test.py` 100%. **Validado com
> gauntlet N=30 direto** (sem repetir o susto do N=10 do bloco 434):
> total 35,7%→36,7% estável, DON/atk 1,22→1,26, Ace melhorou mais
> (43,3%→53,3%), Mihawk idêntico (16,7% — confirma o bloco 435, não
> tinha esse bug atuando ali). **Fix mantido e commitado.** Ver bloco
> 438 do HANDOFF.

> 04/08/2026 (bloco 437): **fecha a pendência do bloco 436** — auditei
> `avaliar_carta` especificamente pra `rest_opp_character` (trava tipo
> Carrot/Jewelry Bonney) vs `ko`/`bounce`. Motor **já diferencia
> corretamente**: rest dá só +10/+20, bem abaixo de ko (+35, até +60
> com bônus) e bounce (+20, até +35). Sem bug, sem fix. Ver bloco 437
> do HANDOFF.

> 04/08/2026 (bloco 436): adicionada **nova seção 10** no
> `IA_Compendium/RESUMO_ESTRATEGICO.md` — guia de deck externo (Cards
> Realm) do Mihawk, colado pelo usuário (fetch direto bloqueado pela
> política de rede da sessão em 4 domínios testados). Corrige o
> resumo impreciso da linha 16/seção 8 ("corta o campo" → na real é
> **rest/tempo control**, trava descansando peças próprias E do
> oponente, sem K.O.). Confirmado que o deck do gauntlet
> ("Green Mihawkby Phi Nguyen") tem o mesmo núcleo do guia — lista
> competitiva real. **Pendente registrado, não investigado**: motor
> precisa diferenciar "descansar oponente" (tempo) de remoção
> permanente ao avaliar Carrot/Jewelry Bonney/Hody Jones-like effects.
> Usuário quer expandir essa seção com mais líderes/decks do mesmo
> site. Ver bloco 436 do HANDOFF.

> 04/08/2026 (bloco 435): investigação do Mihawk (pior matchup pós-fix,
> 16,7%) via IA_Compendium + replay verbose — **sem bug novo achado**.
> Catálogo (linha 16, `OP14-020`) descreve o efeito do líder como
> "corta o campo", mas o texto real da carta é só ramp/reciclagem de
> DON, sem remoção nenhuma — divergência catálogo-vs-carta registrada
> (imprecisão do resumo, não bug do bot). Replay de uma derrota apertada
> mostrou DON/ataque já saudável (fix do 434 ajudando aqui também) e uma
> corrida legítima decidida por quem jogou primeiro, não decisão ruim.
> Ver bloco 435 do HANDOFF.

> 04/08/2026 (bloco 434): **RETIFICA o bloco 433** — não era só
> "matchup difícil", era bug real. `don_needed_for_attack`
> (`decision_engine.py`) ignorava `power_buff` do alvo (lider/character)
> ao calcular deficit de poder pro ataque, enquanto o combate real já
> somava isso há tempos — confirmado via trace instrumentado contra a
> defesa reativa da Lucy (OP15-002). **Fix aplicado e MANTIDO** (2
> linhas + teste permanente novo em `smoke_fast.py`,
> `smoke_fast.py`/`smoke_test.py` 100%). Validação em 2 rodadas: N=10
> deu resultado ambíguo (Lucy caiu pra 0%, usuário pediu mais seeds via
> AskUserQuestion) — **N=30 (210 partidas) confirmou efeito líquido
> estável/positivo**: total 34,3%→35,7%, com Ace (10%→43,3%) e
> Luffy-Amarelo (30%→46,7%) melhorando muito, Mihawk (10%→16,7%) e Lucy
> (20%→26,7%) melhorando também, custando um pouco de Enel/Nami/Espelho
> (já fortes). `gauntlet_matchup.py` agora usa `N_SEEDS=30` (era 10,
> ruidoso demais). **Pendente, não tocado**: mesmo padrão "power sem
> power_buff" aparece em outros pontos de scoring já calibrados
> (blocos 394-398) — precisa de auditoria própria, não fix às cegas.
> Ver bloco 434 do HANDOFF.

> 04/08/2026 (bloco 433, RETIFICADO pelo bloco 434): **Gauntlet controlado Imu vs 7 decks reais do
> meta** (`gauntlet_matchup.py`, novo, reusável — 70 partidas self-play,
> seeds fixas) confirma sinal forte: Imu vence Enel (60%)/Nami (70%),
> os 2 decks mais jogados do meta real, mas perde muito pra Ace (10%),
> Mihawk (10%) e Lucy (20%). Replay verbose de uma derrota de Ace
> mostrou Imu atacando "seco" (1 DON) contra Counters grandes enquanto
> DON sobrava parado — mas a constante que rege essa margem
> (`ATTACK_MARGIN_DON_FRACTION=0.7`) já foi calibrada/cross-validada
> com dados reais no bloco 398 (29/07) e o padrão bate com o já
> conhecido. **Sem fix aplicado** — conclusão é dificuldade de matchup
> real (aggro/counter-denso vs controle do Imu), não bug novo.
> Recomendação explícita: não mexer na constante sem log real desses
> matchups específicos pra cross-validar. Ver bloco 433 do HANDOFF.

> 04/08/2026 (bloco 432): comparação de performance bot-Imu vitória vs
> derrota (`bot_efficiency_report.py`, cohort novo
> `metrics/imu_win_vs_loss_04_08.json`) — bot pilotando Imu = 1
> vitória/25 derrotas no banco (vs 5/4 quando humano pilotava). DON
> médio por ataque: 1,11 (vitória, n=1 baixa confiança) vs 0,26
> (derrota). Validado contra o código de HOJE via 8 partidas self-play
> frescas: 2/8 vitórias (25%), DON por ataque agregado 0,83. **Sem fix
> aplicado** — padrão é consistente com o game plan de controle do Imu
> vs matchups mais rápidos, não há evidência forte de bug novo (e sem
> telemetria de decisão nesta sessão remota não dá pra confirmar). Two
> próximos passos concretos registrados (gauntlet controlado; partida
> real com telemetria) — nenhum executado ainda, aguardando decisão do
> usuário. Ver bloco 432 do HANDOFF.

> 04/08/2026 (bloco 431): **Calibração do combo de reanimação do Imu
> (Five Elders) — bug histórico CONFIRMADO já corrigido** por sessões
> anteriores (commits `87ad7b3` 12/07 e `d063ec3` 14/07). Análise de 35
> jogos reais do banco (6 vitórias/29 derrotas): TODAS as derrotas
> mostram Five Elders sendo trashado como custo/descarte colateral
> (custo do líder Imu, ou perdido em buscas tipo St. Shalria) — 0 dessas
> derrotas é depois dos 2 commits acima. Reconstruí os cenários exatos
> com `GameState`/`EffectExecutor` reais e confirmei que o motor de HOJE
> protege Five Elders corretamente nos dois pontos (trash_value=397,
> busca escolhe Five Elders sobre outras cartas). **Yamato/Crocodile/
> Lucci não são decks de reanimação em massa** (confirmado via
> `card_effects_db.json`/`compute_game_plan` — só recursão de alvo
> único, bate com o catálogo do IA_Compendium). **Moria** tem recursão
> incremental (não bomba), **Perona** não tem líder funcional no banco.
> Nenhum fix de código necessário. Ver bloco 431 do HANDOFF.

> 04/08/2026 (bloco 430): pequeno fechamento do bloco 429 — generalizado
> também o strip de texto "this character cannot attack unless" pra
> aceitar "leader" (2 pontos residuais em `gerar_effects_db.py`, mesma
> gramática, ainda hardcoded). **0 cartas afetadas hoje** (nenhum líder
> usa a forma condicional "unless" no banco atual) — puramente
> preventivo. Ver bloco 430 do HANDOFF.

> 04/08/2026 (bloco 429): **"This Leader cannot attack" era 100% ignorado
> (parser E engine) — 6 líderes reais atacavam apesar do próprio texto
> proibir**. Usuário pediu confirmação de que o bot ativa efeito de líder
> (bloco 428); validando Vegapunk (OP07-097) via `_generate_and_score_actions`
> real, o motor ainda gerava/pontuava um ataque com o líder dele. Causa
> raiz em 3 camadas: (1) parser — o *gate* que decide se chama
> `parse_lock_attack` exigia "opponent" no texto OU "this character
> cannot attack" literal, nunca "this leader"; (2) parser — o regex
> interno tinha o mesmo hardcode; (3) motor — `_generate_and_score_actions`
> (2 pontos), `my_attack_power()` e `opp_attack_count()` adicionavam o
> líder como atacante só checando `not rested`, nunca chamando
> `is_attack_locked_self`/`character_can_attack_now` (já usados pra
> field_chars). Busca no banco inteiro achou 6 líderes afetados (Iceburg,
> Nefeltari Vivi, Rebecca x2, Vegapunk, Shirahoshi). Bônus: achado um bug
> IRMÃO na direção oposta — Monkey.D.Luffy (OP11-058) ficava travado pra
> atacar SEMPRE (mesmo com mão<5, quando a restrição real não vale) porque
> `is_attack_locked_self` ignorava condição no NÍVEL DO BLOCO
> (`passive.conditions`), só olhava condição por-step. Validado:
> `diff_parser.py` GANHOU=0/PERDEU=0/MUDOU=6 (exatamente os 6 líderes),
> `smoke_fast.py`/`smoke_test.py` 100% (7 testes novos), `audit_replay.py`
> --seed 11 e --seed 23 0 anomalias/0 exceções. Registro obrigatório em
> `scriptis_da_ia/parser_audits/2026-08-04_lideres_this_leader_cannot_attack_ignorado.json`.
> Ver bloco 429 do HANDOFF.

> 03/08/2026 (bloco 428): **Motor cego a efeitos "Choose one" (`choice`)
> em TODA função de scoring — 23 cartas (4 líderes, personagens,
> eventos) pontuavam como se o efeito não fizesse nada**. Usuário pediu
> pra testar se o bot sabe ativar o efeito de cada líder. Achado: 3
> líderes (Perona OP06-021, Vegapunk OP07-097, King OP08-057) têm
> `activate_main` "Choose one" guardado em `choice` (não `steps`) —
> parser está CORRETO, execução já resolve `choice`, mas toda função de
> SCORING (`_score_activate_main`, etc.) só lia `steps` direto, sempre
> vazio pra essas cartas — `_score_activate_main` pontuava King com o
> piso genérico 60 em vez do valor real (170, "compre 1 carta"). Busca
> no banco inteiro achou o MESMO padrão em 23 cartas / 5 gatilhos
> (`on_play`, `main`/evento, `activate_main`, `when_attacking` — inclui
> líder Queen OP04-040 —, `on_ko` — Pedro OP08-030). Fix genérico: novo
> helper `resolve_choice_for_scoring` aplicado em ~15 funções de scoring
> (não só nas cartas que revelaram o bug). Validado: `smoke_fast.py`/
> `smoke_test.py` 100% (6 testes novos), `audit_replay.py --seed 11` e
> `--seed 23` 0 anomalias/0 exceções. **Pendente**: nenhum deck de
> `decklists_raw.csv` usa os líderes afetados — falta validação de
> self-play/telemetria ao vivo com esses líderes. Ver bloco 428 do
> HANDOFF.

> 03/08/2026 (bloco 427): **Mais 2 achados de performance — -21,5% em
> cima do bloco 426 (total -45,6% desde a linha de base original)**.
> `GameState.counter_in_hand()` chamava `effective_counter(c, self)` 2x
> por carta (filtro `if` + soma) — 94% de todas as chamadas de
> `effective_counter` numa partida real vinham só daqui. E
> `EffectExecutor._trash_value`/`should_pay_removal_substitute`/
> `has_valuable_don_return_trigger` recriavam `DecisionEngine(self.me,
> self.opp)` do zero em CADA carta comparada em `_choose_to_trash`,
> zerando o cache de instância de `posture()`/`_lethal_search()` a cada
> chamada. Fixes: computa `effective_counter` 1x e reusa; novo
> `EffectExecutor._de()` cacheia o `DecisionEngine` por instância (mesmo
> invariante de `posture()`: `me`/`opp` fixos depois do construtor).
> Validado: `smoke_fast.py`/`smoke_test.py` 100% (2 testes novos),
> `audit_replay.py --seed 11` e `--seed 23` 0 anomalias/0 exceções (sem
> regressão do bloco 425), reprofiling da mesma partida 7.25s → 5.69s.
> Pendente: medir ao vivo se isso já elimina os timeouts de 3s do bloco
> 411. Ver bloco 427 do HANDOFF.

> 03/08/2026 (bloco 426): **`full_deck_plan`/`full_deck_census`/
> `full_deck_profile` nunca populados em `ReplayMatch` nem no lado
> oculto (oponente) ao vivo — -30,7% no tempo de partida real medido
> por profiling**. Usuário perguntou se dava pra melhorar o Monte
> Carlo; profiling (`cProfile` em partida real de self-play) achou
> `compute_game_plan_from_cards` consumindo 26% do tempo total —
> deveria rodar 1x/partida (cache dedicado já existe), mas o cache
> nunca era POPULADO em `ReplayMatch.__init__` (usada por
> `audit_replay.py`/`smoke_test.py`) nem em `server.py:_dto_to_gs` pro
> lado `hide_hidden` do oponente (só o lado próprio populava, achado
> 14/07). Efeito colateral pior que performance: `posture()` do
> oponente SIMULADO (durante `USE_OPPONENT_RESPONSE_SEARCH`, ligado por
> padrão) sempre degradava pra 'midrange', nunca lia o perfil real do
> deck dele. Fix: lógica extraída pra `populate_full_deck_knowledge`
> (`decision_engine.py`), reusada por `OPTCGMatch.__init__`,
> `ReplayMatch.__init__` (decklist real) e `_dto_to_gs` lado oculto
> (decklist aproximada, mesmo fallback em 3 camadas do bloco 378 já
> usado pro `OpponentModel`). Validado: `smoke_fast.py`/`smoke_test.py`
> 100%, `audit_replay.py --n 20 --seed 11` 0 anomalias/0 exceções
> (sem regressão do bloco 425), reprofiling da mesma partida 10.46s →
> 7.25s. **Nota**: isso é sobre velocidade/cache do motor, NÃO é a
> mesma pendência do `IA_Compendium` (bot "não entende" o líder —
> fidelidade de arquétipo, não performance) — não confundir. Ver bloco
> 426 do HANDOFF.

> 03/08/2026 (bloco 425): **Bug de conservação de DON — causa raiz
> FINALMENTE encontrada e corrigida**, pendente desde 25/07 (blocos
> 374/377/410/420/422/423). `OpponentModel.sample()` nunca fazia
> `deepcopy` das cartas da amostra fictícia do oponente (apesar da
> própria docstring prometer isso) — mutações durante simulação de
> turno de resposta completo (`_play_turn_greedy`) vazavam pro deck
> REAL do oponente (mesmos objetos Card, referência compartilhada).
> Fix + achado colateral (`_SimDeck` bypassado por 5 pontos que usavam
> `remove_by_identity` em vez de `.pop()`, corrigido com `pop_by_
> identity`). Validado: `audit_replay.py --n 20 --seed 11` — 23
> anomalias → 0, 0 exceções. `smoke_fast.py`/`smoke_test.py` 100%. Ver
> seção própria abaixo e bloco 425 do HANDOFF.

> 02/08/2026 (bloco 424): **Partida nova (Ace x Kid) confirma os 4
> fixes de hoje funcionando ao vivo** (Izo deu DON pro líder, Rush foi
> pra Vista recém-jogada) — nenhuma regressão visível. **Achado novo,
> NÃO corrigido**: a busca do Turn Planner estourou o timeout de 3s 7x
> nesta partida (`decision_timeouts` na telemetria, ausente nas
> partidas anteriores). Investigado com cProfile + bissecção via `git
> worktree`: **confirmado pré-existente** (reproduz idêntico no commit
> de antes de todos os fixes de hoje) — não é regressão, é um board
> específico (mão=5 com 2x Vista, Izo em campo) que já era lento.
> Maior parte do tempo em `avaliar_carta`/`don_opportunity_cost`
> chamadas repetidas dentro da busca contrafactual. Pendência de
> performance registrada pra próxima sessão que for atrás disso. Ver
> bloco 424 do HANDOFF.

> 02/08/2026 (bloco 423): **Bloco 418 fechado — causa raiz da lentidão
> de `/choose_target` confirmada e corrigida**. Decisões de alvo pra
> cartas com custo só de mão (ex: Luffy OP16-015) chegavam com 65-73
> candidatos (todas as zonas do jogo), correlacionado com ~27-31s de
> atraso por decisão — `order_target_candidates` nunca reconhecia "só
> precisa de 1 carta da mão" pra excluir o resto. Fix: exclusão dura
> (mesmo padrão do `actor_opp_only`) restrita a uma allowlist estrita de
> ações comprovadamente auto-contidas — 34 cartas do banco se
> beneficiam. 3 testes novos cobrindo o caso positivo (Luffy) e dois
> casos negativos (Newgate com target de campo, GERMA 66 com
> `play_from_trash` sem `target` explícito) pra não excluir zona que o
> efeito realmente precisa. O outro ponto pendente (turno 3, "atacaria
> Miss Valentine + jogaria Luffy") foi confirmado **não-bug** — a
> escolha do bot (pressionar vida em vez de matar um corpo já "gasto")
> é defensável. `smoke_fast.py`/`smoke_test.py` 100%.
>
> **Bissecção confirmou**: uma anomalia de DON nova em
> `audit_replay.py --n 20 --seed 23` (Red/Blue Ace x Blue/Purple Sanji)
> NÃO é regressão deste fix — reproduz idêntica no commit anterior
> (`f239823`). O bug de conservação de DON pré-existente (antes só
> documentado em Black Imu + Empty Throne) também afeta decks Red/Blue
> Ace — escopo mais amplo do que se sabia, causa raiz ainda não
> encontrada. Ver bloco 423 do HANDOFF.

> 02/08/2026 (bloco 422): **`give_don` corrigido — dava o DON pro alvo
> de maior PODER bruto, sem checar se ele podia usar o DON este turno**.
> Izo (EB01-002, on_play "dá 1 DON restado") deu o próprio DON pra si
> mesmo (recém-jogado, sem Rush, não podia atacar nem hoje) em vez do
> líder já restado, só por ter mais poder impresso — quando o líder é o
> destino de valor permanente mais seguro (ataca todo turno, nunca sai
> de campo). Fix: entre quem pode atacar ainda hoje, maximiza poder
> (normal); se ninguém pode, prefere o líder. Corrigido nos 2 lugares
> (execução + ordenação de alvo ao vivo — mesmo padrão "duas fontes de
> verdade" do bloco 421). Um 2º ponto reportado (DON parado no fim do
> turno) **não é bug** — o ataque "seco" já era vitória garantida pelo
> que o bot sabia (empate favorece o atacante); só perdeu pra um Counter
> vindo de informação ESCONDIDA (mão do oponente). Fica registrado como
> pendência de investigação, não uma correção. 2 testes novos,
> `smoke_fast.py`/`smoke_test.py` 100%. `audit_replay.py --n 20 --seed
> 11`: 0 exceções, 23 anomalias de DON — todas no matchup pré-existente
> "Black Imu + Empty Throne" (blocos 374/377/410/420), confirmado sem
> relação com o fix de hoje. Ver bloco 422 do HANDOFF.
>
> **Pendência nova**: investigar se vale a pena ensinar o motor a tratar
> um ataque "empatado, sem margem" como arriscado quando
> `opp_counter_potential()` é > 0 mesmo com a mão mascarada (ex: usar
> densidade média de counter do deck do oponente, já existe uma
> estimativa estatística equivalente em `counter_estimation.py` usada
> em outro lugar) — isso pode reduzir esse tipo de "ataque seco perde
> pra counter escondido" sem exigir informação que o bot não tem.

> 02/08/2026 (bloco 421): **"Duas fontes de verdade" achada e corrigida**
> — `order_target_candidates` (`sim_bridge.py`, resolve prompts de alvo
> AO VIVO) não conhecia regras que já existiam em `decision_engine.py`
> (simulação interna). (1) Rush ainda ia pra um personagem já restado
> (Vista) em vez do recém-jogado (Newgate) mesmo com o fix dos blocos
> 419-420 — porque esse fix só cobria a simulação, não a ordenação de
> alvo ao vivo. Fix: critério extraído pra 2 funções compartilhadas
> (`character_needs_rush`/`character_needs_rush_character`), reusadas
> nos 3 lugares que precisam dele. (2) Debuff `[On Play]` do Newgate
> (-6000) não coordenava com o ataque planejado no mesmo turno — a
> lógica que já existia (Nosjuro, 14/07) só cobria debuffs `[When
> Attacking]` já em janela de ataque declarada. Fix: estendida pra
> projetar, fora de janela de ataque, se o debuff destrava algum
> atacante disponível. (3) `score_attack_target` nunca somava bônus pela
> keyword do PRÓPRIO atacante (Double Attack/Banish) ao pontuar o
> líder como alvo — só valem em dobro contra vida, nunca contra
> Character. Fix: +60/+45. Um 4º ponto reportado (stage não deu DON)
> **não era bug** — score -10 correto, nada se beneficiava do DON
> restado naquele momento específico. 3 testes novos, `smoke_fast.py`/
> `smoke_test.py` 100%, `audit_replay.py --n 20 --seed 7`: 0 exceções, 0
> anomalias. **Pendente**: se `counterfactual_search` ainda prefere
> atacar Character mesmo com os bônus novos quando o oponente pode
> counterar o ataque ao líder — não investigado a fundo, log futuro
> parecido deve conferir. Ver bloco 421 do HANDOFF.

> 02/08/2026 (bloco 420): **2 bugs reais corrigidos, achados comparando
> decisões do usuário com as do bot (mirror match Ace x Ace)** — (1)
> `gain_double_attack` ignorava `target` por completo, sempre aplicando
> na própria carta-fonte mesmo quando o texto dizia "Your Leader
> gains..." (Edward Newgate, Flame Emperor, Buggy) ou selecionava outro
> personagem por nome (Twin Jet Pistol, Prometheus) — auditoria global
> achou 5 cartas erradas de 15 no banco. Fix no executor (suporte a
> `target='leader'/'selected'`, reusa o padrão do `gain_rush`) + parser
> (nova regex pra "your leader gains... double attack" + `type`/
> `characters` viraram opcionais em `select_grant_double_attack`).
> Registro em `parser_audits/`. (2) Mesmo com o efeito corrigido, o
> motor ainda atacaria antes de jogar Newgate — `_score_play_action`
> nunca considerava que uma passiva `[Your Turn]` que buffa o líder só
> vale a pena HOJE se jogada antes do ataque. Fix: bonus quando o líder
> ainda pode atacar (score de jogar Newgate subiu de ~230 pra 432,
> agora compete com o ataque de ~376; fica em 82, sem bonus, quando o
> líder já atacou). 4 testes novos, `smoke_fast.py`/`smoke_test.py`
> 100%. **`audit_replay.py` reproduziu 3 anomalias de conservação de
> DON** (deck Imu + Empty Throne + Five Elders) — confirmado ser o bug
> PRÉ-EXISTENTE dos blocos 374/377/410 (nenhuma mudança de hoje toca
> mecânica de DON), não uma regressão nova. `server.py` precisa
> reiniciar. Ver bloco 420 do HANDOFF.

> 02/08/2026 (bloco 419): **Fix aplicado — item 1 do bloco 418**. Score
> de `give_don` (stage Moby Dick/qualquer carta com essa ação) agora
> soma +130 quando fecha um deficit real de poder contra o líder do
> oponente, e +100 quando desbloqueia um `don_requirement` de
> `when_attacking` que o alvo ainda não atingia (checado direto, não
> pelo delta de poder — o caso real do Vista é KO puro, sem ganho de
> poder, só pontuou depois de checar o `don_requirement` na marra). 3
> testes novos, `smoke_fast.py`/`smoke_test.py` 100% +
> `audit_replay.py --n 5` (0 anomalias). **Ainda pendentes do bloco
> 418**: lentidão de `/choose_target` (item 3), Namule turno 2 não
> investigado (item 4), comparação do turno 3 (item 5), e — importante
> pra quem pegar a sessão remota — **o fix do plugin C# (2+ gatilhos
> simultâneos) segue sem confirmação ao vivo**, só compilou limpo.
> `server.py` precisa reiniciar. Ver bloco 419 do HANDOFF.

> 02/08/2026 (bloco 418): **Fix do plugin C# pendente de teste ao
> vivo** — 2+ cartas disparando gatilho ao mesmo tempo travavam o bot
> (ex: 2 Izou) porque nenhum código tratava o estado
> `acaActive==null`+`lgo_ActionChoices` populado (jogo esperando qual
> ativa primeiro). Fix em `BotExecutor.cs`/`BotDriver.cs` via reflexão
> Harmony, clica a 1ª opção (efeitos independentes, ordem não importa).
> Compilado (0 erros), instalado, **ainda não confirmado numa partida
> real**. **5 novos achados de uma partida real** (Ace x Crocodile,
> 09.41.46): (1) **causa raiz confirmada, fix pendente** — `activate`
> do stage Moby Dick (dar 1 DON restado) sempre pontua -10 fixo
> (`GIVE_DON_RESTED_BASE_SCORE`), nunca considera sinergia com um
> ataque na mesma janela (turno 2: teria dado 8000 em vez de 7000;
> turno 4: teria desbloqueado o `when_attacking` do Vista,
> `don_requirement:1`, "KO até 2 personagens ≤2000"). (2) turno 5 não
> atacou com Vista — **confirmado não-bug**, `cantAttack:True` por
> efeito do oponente. (3) Luffy/Marco/Newgate "demoram pra decidir" —
> decisão é instantânea (2-4ms), a demora real é na resolução de alvo
> depois — mesmo padrão de `/choose_target` sem filtro já suspeito
> antes (2 Izou, Newgate), ainda não confirmado linha a linha. (4) **em
> aberto** — Namule turno 2, custo pagável e alvo válido pro KO, mas
> nem `defense`/`optional` decision aparece no log nem o KO aconteceu —
> hipótese não confirmada: `reveal_from_hand` pode nem passar pela
> tela de aceitar/recusar no C#, pulando o fix do bloco 417. (5) turno
> 3, comentário do usuário sobre o que ele faria diferente — não
> comparado contra a decisão real do bot ainda. Ver bloco 418 do
> HANDOFF pro detalhe completo de cada item.

> 02/08/2026 (bloco 417): **Bug real corrigido (fecha o achado do
> bloco 416)** — bot ao vivo aceitava custos `reveal_from_hand`
> (ex: Edward Newgate, "revele 2 Character 8000 power") sem checar
> se existiam cartas suficientes na mão — `_worth_paying_optional_costs`
> (a decisão de aceitar) nunca validava isso, só `_pay_costs` (o
> momento de pagar) validava, tarde demais pro caminho ao vivo. Caso
> real: mão só tinha 1/2 cartas válidas, jogo travou pedindo "Select 2
> More Friendly Targets" que nunca completava (confirmado na
> telemetria: 2 decisões `target` idênticas, 34s de intervalo real).
> Fix: `_reveal_from_hand_matches` extraída como fonte única, reusada
> nos dois lugares. 2 testes novos, `smoke_fast.py`/`smoke_test.py`
> 100%. **Pendente**: não foi feita auditoria exaustiva se outros
> tipos de custo fora de `_SACRIFICE_COST_TYPES` têm o mesmo gap — só
> `reveal_from_hand` foi confirmado (achado de 1 log real). `server.py`
> precisa reiniciar. Ver bloco 417 do HANDOFF.

> 02/08/2026 (bloco 416): **Achado novo, NÃO investigado a fundo** —
> seleção de MÚLTIPLOS alvos amigos trava/repete. Usuário reportou
> (screenshot) turno 7 preso em "Select 2 More Friendly Targets"
> (custo do Edward Newgate, `reveal_from_hand=2`). Telemetria confirma:
> 3 decisões `target` seguidas com a MESMA lista de candidatos, 34s e
> 60s de intervalo REAL entre elas (não é latência do motor, teto é
> 3s). Causa exata não lida ainda — próxima sessão deve começar pelo
> endpoint `/choose_target` em `server.py` e o lado C#
> (`BotDriver.cs`) que trata prompts "Select N More Targets", antes de
> tentar fix. Ver bloco 416 do HANDOFF. Lado positivo: só 1 timeout
> nessa partida (vs 3-5 antes), confirma que o fix de performance do
> bloco 415 funcionou na prática (latência p95 caiu de ~3000ms pra
> 1911ms).

> 02/08/2026 (bloco 415): **Performance da busca ao vivo, ~25% mais
> rápida, achada por profiling real (não chute)** — usuário pediu pra
> investigar a lentidão em vez de cortar qualidade (amostras/
> profundidade). 2 causas reais: (1) `GameState.__deepcopy__`
> esquecia de propagar `full_deck_plan`/`full_deck_profile` (cache
> invariante, só o `full_deck_census` era propagado) — qualquer clone
> do Turn Planner (dezenas/centenas por decisão) perdia o cache e
> escaneava o deck inteiro de novo; 4331 chamadas evitáveis numa
> decisão real. (2) `posture()` nunca era cacheada — ~3000 chamadas
> redundantes recomputando o mesmo resultado dentro do mesmo estado.
> Fix com cuidado de correção: cache invalidado 1x por ciclo de
> pontuação (`_generate_and_score_actions`), não pela vida inteira da
> instância, porque `engine` é reutilizado ao longo de várias ações
> que mutam o estado no mesmo turno. Medido: mesma decisão real,
> mesmo profiler, 5.8s → 4.37s. `smoke_fast.py`/`smoke_test.py` 100%
> + `audit_replay.py --n 6` (0 anomalias, confirma DON ainda
> conservado no `__deepcopy__` corrigido). **Pendente**: `_trash_value`
> ainda constrói uma `DecisionEngine` nova por carta avaliada em loop
> (mais uma oportunidade de cache, não explorada). Board muito cheio
> pode continuar batendo no timeout de 3s mesmo com o ganho — validar
> na próxima partida ao vivo. `server.py` precisa reiniciar. Ver
> bloco 415 do HANDOFF.

> 02/08/2026 (bloco 414): **2 bugs reais corrigidos** — (1)
> `select_grant_rush` continuava cego mesmo depois do fix do bloco 412:
> a camada de EXECUÇÃO estava corrigida, mas `_should_activate_main`
> (decide se "activate" aparece como candidata) nunca tinha caso pra
> essa família, oferecia o líder Ace com score fixo 90.0 em TODOS os 7
> turnos de uma partida real, só achando alvo de verdade no turno 7.
> Fix reusa `_step_is_viable`. (2) `attach_don` nunca era oferecido em
> EMPATE EXATO ("empate favorece o atacante" = "não precisa de nada"),
> mesmo quando o DON disponível não tinha NENHUM outro uso no turno
> (mão toda cara demais) — 3 DON ficaram parados achando a vitória já
> garantida, sem margem nenhuma contra Counter do oponente (que tinha
> vários). Fix: em empate exato + DON sobrando após reserva de defesa +
> nenhuma carta jogável, considera até 2 DON de margem (0.3x do valor
> cheio). Reserva de defesa (`_don_reserve_for_defense`, já cobre
> eventos `[Counter]` na mão) nunca é tocada pela margem — correção do
> usuário durante a investigação. 2 testes novos, `smoke_fast.py`/
> `smoke_test.py` 100%. **Pendente**: achado da telemetria (lethal
> certificado no turno 6 não fechou a partida) não foi aprofundado,
> suspeita de ser o mesmo padrão sistêmico (ataque "certo" não pondera
> Counter possível do oponente). `server.py` **precisa reiniciar** antes
> do próximo teste ao vivo. Ver bloco 414 do HANDOFF.

> 02/08/2026 (bloco 413): **`bot_side` agora automático** —
> `collect_latest_match.py` (`_apply_winner`) já recebia `bot_seat`
> (fonte autoritativa, de `BotDriver.cs`/`BotPlayerIndex`, sempre
> conhecida) em todo `/outcome`, mas só usava pra calcular `winner`,
> nunca gravava `bot_side` no index. Corrigido — todo log coletado ao
> vivo daqui pra frente já sai do banco com `bot_side` correto, sem
> precisar do `--bepinex-log` manual (feature do bloco 389, que só
> funcionava se Shift+P tivesse sido apertado). 2 testes novos,
> `smoke_fast.py` 100%. Logs já no banco de antes deste fix continuam
> com `bot_side=null` (sem backfill retroativo). `server.py` reiniciado
> (PID 1652) com este fix + o do bloco 412 (Rush) ativos.

> 02/08/2026 (bloco 412): **Bug real corrigido** — `select_grant_rush`/
> `select_grant_rush_character` (lider Ace OP16-001 e outras cartas da
> mesma família) concediam Rush sem checar se o alvo realmente se
> beneficiava. Achado ao vivo (usuário): Ace deu Rush pra Vista já
> `rested` (tinha atacado no mesmo turno) e deployada 2 turnos antes —
> ativação `once_per_turn` totalmente desperdiçada. Critério certo
> (correção do usuário): Rush só importa pra quem `just_played` (entrou
> em campo ESTE turno) — um Character antigo, mesmo ativo, já ataca
> normal sem precisar de Rush. Fix em `_execute_step` (2 pontos) +
> `_step_is_viable` (nova branch, antes caía no fallback "sempre
> viável"). 3 testes existentes ajustados (não setavam `just_played`
> explicitamente) + 1 teste novo reproduzindo o cenário exato do log.
> `smoke_fast.py`/`smoke_test.py` 100%. Ver bloco 412 do HANDOFF.

> 01/08/2026 (bloco 410): bug de conservação de DON — achado 1 bypass
> real da função centralizada de remoção de campo (`OP06-033`, corrigido),
> mas NÃO é a causa raiz do leak original (Empty Throne + Five Elders).
> Teste de reprodução com a seed antiga saiu limpo, mas é inconclusivo
> (pareamento de deck mudou desde então). Causa raiz continua
> desconhecida — próximo passo é instrumentação direta, não auditoria
> estática. Ver bloco 410 do HANDOFF.

## 🟢 Investigação NEGATIVA: sequenciamento do Turn Planner e timing de reserva de DON (01/08/2026, bloco 409)

Pedido do usuário: checar se existe bug REAL de ordem/timing dentro do
turno (distinto dos bugs de magnitude/drawback já corrigidos nos blocos
407-408) e se a reserva de DON (`_don_livre_for_plan`) funciona de
verdade na prática.

- [x] **Sequenciamento** (carta com buff/rush/double-attack pro próprio
  lado aplicada DEPOIS de já ter atacado no mesmo turno, desperdiçando o
  benefício): 0 casos em 10/10 partidas reais de self-play instrumentado
  (65 cartas do banco têm esse padrão de efeito, nenhuma pegou o padrão
  de ordem errada na amostra).
- [x] **Timing de reserva de DON** (carta que `_don_livre_for_plan`
  reservou DON pra jogar/ativar, mas que não foi de fato aplicada no
  mesmo turno por falta de DON): 0 casos em 10/10 partidas.
- [x] Contexto: sequenciamento JÁ foi bug real e documentado (bloco 25,
  01/07 — planner só via a 1ª ação do turno), corrigido arquiteturalmente
  depois (`main_phase` em loop + lookahead `max_steps=8` via Monte Carlo
  + `_don_livre_for_plan` desde 14/07). A investigação não achou
  regressão nem caso novo não coberto.
- [x] **Limitação declarada**: amostra pequena (~20 partidas no total,
  não exaustiva), só cobre os 2 padrões específicos pedidos — não é
  garantia formal de zero bugs de sequenciamento em qualquer cenário.

Sem mudança de código (investigação pura). Scripts de instrumentação não
commitados (descartáveis, scratchpad da sessão).

## 🟢 Auditoria "outros efeitos com sequência errada no Turn Planner": 3 cartas com drawback nunca descontado, corrigidas (01/08/2026, bloco 407)

Confirmado pro usuário: a redução de ativações desperdiçadas do Mihawk-G
(bloco 406) foi de **40,6% → 20,0%** (queda de ~51% relativa, passa dos
"mais de 20%" pedidos).

Auditoria por analogia (mesma classe de bug do `self_cant_play` do
Mihawk-G — drawback próprio dentro do PRÓPRIO `activate_main` nunca
descontado do score) achou 3 cartas:

- [x] **`OP06-020` Hody Jones** (`self_cant_take_life`): tabela
  `_UNCOVERED_ACTION_VALUE` já tinha `-15` calibrado, mas nunca era
  consultada (bloco cai direto em "remoção/controle", `base=100`, sem
  passar pelo fallback que lê essa tabela). Fix: desconta os -15 direto.
- [x] **`OP04-090` Luffy** (`lock_self_character_refresh`): mesma tabela,
  mesmo problema (só era lida via `max()` no fallback — nunca REDUZ o
  score). Fix: desconta `min(board_value(src)*6, 70)`.
- [x] **`OP12-020` Zoro** (`lock_self_attack_opp_chars_cost_lte`): nem
  estava na tabela. Fix: desconta `min(melhor_alvo_elegivel*0.3, 50)` só
  quando o oponente TEM Character(s) de custo≤7 em campo (sem alvo, sem
  penalidade).

Validado só via `smoke_fast.py` (3 testes de magnitude EXATA, comparação
controlada com/sem o step de drawback) — **nenhuma das 3 cartas tem log
real no banco** (não estão no pool de 18 líderes com partidas reais), sem
alvo de comparação humana disponível. `smoke_fast.py`/`smoke_test.py`
100%, sem mudança de parser.

**Resolvido no bloco 408** (usuário pediu "pode ir por aí"): a categoria
inteira "remoção/controle" agora escala por valor real do alvo. Ver
seção própria abaixo.

## 🟢 Categoria "remoção/controle" (90+ cartas) escala por valor real do alvo, não base=100 flat (01/08/2026, bloco 408)

Escopo real maior que o levantamento inicial do bloco 407: buscando
`target` em TODO o banco (não só líderes), `rest_opp`/`rest_opp_
character`/`ko`/`ko_opp`/`debuff_power`/`debuff_cost`/`bounce`/`place_
opp_character_bottom_deck`/`lock_opp_character_attack` aparecem em
**90+ cartas** (maioria Characters, não só líderes). Todas pontuavam
`base=100` flat — remover um vanilla fraco valia o mesmo que remover o
maior blocker do oponente.

- [x] Fix genérico: `_best_removal_target_value`/`_has_opponent_
  targeted_removal_step` (novos em `OPTCGMatch`), delegando filtro de
  alvo a `eligible_cards` (mesma fonte da execução real) e valor a
  `GameAnalyzer.char_value_score`. Mesmo formato do `negate_effect`
  (`-60` sem alvo de valor, `100+min(valor*0.3,70)` com alvo).
- [x] Cuidado que evitou regressão real: `bounce`/`ko` com variante
  self-target (`OP01-002` bounce a própria carta — combo de re-trigger,
  NÃO remoção) só escala quando o `target` do step diz explicitamente
  `opp_character`/`all_opp_characters` — as outras 7 ações (nunca
  observadas com variante própria no banco) tratam `target` ausente
  como oponente implícito.
- [x] Validado: `smoke_fast.py` (4 checks: sem alvo→negativo, forte>fraco,
  fraco>sem-alvo, guarda de regressão pro bounce self-target) +
  `smoke_test.py` completo, **0 regressões** nos ~1500 testes existentes
  (inclui testes que já tocavam `OP01-002`/`ST03-001`/`ST06-001`/
  `ST10-001`, entre outras cartas afetadas).
- [x] Sem baseline humano disponível pra nenhuma carta desta categoria
  (só `OP14-079` está no pool real de 18 líderes, e mesmo esse sem
  logs) — validação é só por auto-consistência/testes de unidade,
  declarado explicitamente.

## 🟢 Mihawk-G (OP14-020): 2 causas reais corrigidas, alvo de "5,4/jogo" reconsiderado (30/07/2026, blocos 405-406)

Self-play instrumentado (20-15 partidas, `decklists_raw.csv`) achou e
corrigiu 2 causas reais do gap de ativação:

- [x] **Causa 1 (bloco 405)**: `set_don_active` pontuava `base=90` FLAT
  sem escalar pelo DON realmente RESTADO disponível
  (`min(count, don_rested)`). Fix generalizado pras 11 cartas do banco
  que usam essa ação. Validado: 1,75 → 2,10 ativações/jogo (+20%).
- [x] **Causa 2 (bloco 406, achada ao continuar investigando)**:
  filtrando só decisões REAIS (211 de 25 mil eram reais, resto era
  simulação interna), achei que ~40% das ativações reais aconteciam com
  `don_rested=0` (benefício ZERO) E mão ainda com 5-9 cartas jogáveis —
  `self_cant_play` (único caso no banco dentro do próprio
  `activate_main`) nunca era penalizado. Fix: mesmo peso já calibrado
  pro `self_cant_play` de `on_play` (`perdidas * 0.5`). Validado:
  ativações desperdiçadas caíram de 13/32 (40%) pra 5/25 (20%).
- [x] **Investigado e descartado como bug real**: a reserva de DON pra
  ações 'activate' futuras (`_don_livre_for_plan`) já existe e protege
  corretamente — quando `don_rested>=1` de verdade, a ativação compete
  bem (topo da lista 54-58% das vezes). O gap residual é tensão real de
  economia de DON do deck, não um problema de busca/sequenciamento do
  Turn Planner.
- [x] **Alvo "5,4 ativações/jogo" (dos logs humanos) reconsiderado**:
  não é mais tratado como alvo cego — jogadores reais provavelmente
  ativam por hábito (custo baixo) sem pesar o custo de travar a mão. As
  2 correções tornam o bot mais criterioso (menos ativações
  desperdiçadas), o que é o resultado certo mesmo que a contagem bruta
  não convirja pro número humano.

`smoke_fast.py`/`smoke_test.py` 100% (teste expandido com o cenário de
`self_cant_play`). Sem mudança de parser em nenhum dos 2 fixes.

## 🟢 DOCUMENTAÇÃO CORRIGIDA: should_use_blocker/should_use_counter já estava calibrado (30/07/2026, bloco 404)

Usuário pediu pra eu procurar a próxima frente; escaneei o TODO/HANDOFF
inteiros e apresentei 2 candidatos (Mihawk-G residual e a "decisão
pendente" de calibração do bloco 394). Usuário escolheu a segunda —
investigação mostrou que **já estava resolvida** (blocos 396-398
calibraram exatamente isso via self-play pareado), só o `TODO.md` nunca
foi atualizado pra fechar aquela seção. Corrigido (ver seção do bloco
394 mais abaixo, agora marcada 🟢 RESOLVIDO). Nenhuma mudança de código.

Candidato ainda genuinamente aberto, se o usuário quiser continuar:
**Mihawk-G (OP14-020)**, gap residual de ativação de Activate:Main
(1,6 vs 5,4/jogo dos vencedores reais — bloco 399, suspeita de
prioridade/score no Turn Planner, nunca investigado a fundo).

## 🟢 IMPLEMENTADO: resolve_reaction/redirect RETOMADO E FECHADO (30/07/2026, bloco 403)

Auditados os 4 únicos redirects do banco. Teach/Doflamingo/EB01-038 já
estavam corretos. **Kid (ST36-005) tinha 3 bugs reais**:

- [x] Tag "[On Opponent's Attack]" sem "your" (única carta no banco)
  não era reconhecida pela família `on_opp_attack` — caía em `passive`
  incondicional.
- [x] Custo real das DUAS habilidades de Kid ("turn 1 card from the
  **top or bottom** of your Life Cards face-X") sumia por completo — o
  regex só aceitava "top". Ambas rodavam de graça.
- [x] Após corrigir a tag isoladamente, o texto duplicava em
  `on_opp_attack` E `passive` — a lista mestre `TODAS_TAGS` também
  precisava do "your" opcional, não só o regex específico.

Fix: tag tolerante em 2 pontos; custo ganhou `position: top_or_bottom`;
`_pay_costs` prefere virar uma carta de vida já no estado desejado
(custo real zero) antes de cair no fallback do topo. `resolve_reaction`
não mudou de comportamento (decisão deliberada, documentada).
`diff_parser.py` PERDEU=0 MUDOU=1. Novo teste permanente + teste antigo
corrigido (não afirma mais que Kid "não tem custo nenhum").
`smoke_fast.py`/`smoke_test.py` 100%.

**Cross-check líder/deck adicional (Enel, antes de retomar redirect)**:
usuário confirmou que o mix de arquétipo espalhado do Enel (Aggro 37% /
Controle 36,5% / Ramp 26%) é fiel ao deck real dele ("faz um pouco de
tudo"), não um erro. Achado residual: o único consumidor de
`archetype.dominante` no motor usa comparação binária de string, sem
olhar a margem — vira cara-ou-coroa em empates técnicos como esse.
**Usuário decidiu deixar como está por enquanto** (baixo impacto, só 1
ponto de consumo) — registrado, não corrigido.

Nenhum item pendente desta rodada. `resolve_optional_effect` (fallback
de reações não-redirect) não foi reauditado — fica como possível
próximo passo se o usuário quiser aprofundar.

## 🟢 IMPLEMENTADO: IA_Compendium virou referência OBRIGATÓRIA (30/07/2026, bloco 402)

Usuário pediu explicitamente pra tornar `IA_Compendium/` referência
obrigatória, pra garantir que o bot "sabe o que cada líder faz".

- [x] Extraído/mapeado `ONE_PIECE_AI_COMPENDIUM_Volume_1.docx`/`.pdf`
  pra `IA_Compendium/RESUMO_ESTRATEGICO.md` (git-diffável/grepável).
  Catálogo de 60 decks (Seção 8) mapeado pra códigos reais de carta
  (53/60 únicos, 7 com candidatos ambíguos marcados explicitamente).
- [x] Nova regra OBRIGATÓRIA em `CLAUDE.md`/`AGENTS.md` ("Referência
  estratégica obrigatória"): ler o resumo antes de auditar/tunar
  comportamento de líder, ou mexer em `decision_engine.py`/
  `deck_analyzer.py`/`deck_profile.py`/`compute_game_plan`. Documenta o
  limite do próprio compêndio (preliminar, será refinado) e que líderes
  antigos (OP01-002, ST08-001) não estão no catálogo.
- [x] Cross-check real dos 6 achados do bloco 401 contra o catálogo:
  Shanks, Buggy, Boa Hancock, Koala **batem** com a diretriz de IA do
  catálogo (Boa Hancock quase literalmente — catálogo previu
  "manipular Life" e foi exatamente a 2ª habilidade que faltava).
  Trafalgar Law (OP01-002) e Luffy (ST08-001) não têm linha no catálogo
  (líderes antigos demais pra "Recommended Decks" da época) — sem
  divergência real encontrada nesta rodada.
- [ ] Se um Volume 2 (análise individual por deck) chegar, atualizar
  `RESUMO_ESTRATEGICO.md` e a regra em `CLAUDE.md`/`AGENTS.md`.

`resolve_reaction`/redirect segue pendente (adiado há 2 sessões).

## 🟢 IMPLEMENTADO: revisão de TODOS os líderes do jogo (135, não só os 17 do pool real) (30/07/2026, bloco 401)

Usuário pediu pra revisar TODOS os líderes (não só os 17 com deck real
no pool de self-play). 6 achados confirmados via varredura automática +
revisão manual; usuário pediu pra implementar todos. **Os 6 foram
implementados nesta rodada.**

- [x] Shanks (OP09-001): "this effect can be activated when your
  opponent attacks" reconhecido como sinônimo em prosa de
  `[On Your Opponent's Attack]` (reaproveita `on_opp_attack`
  existente). Bônus: OP16-048 (não-líder, mesma frase) corrigido de
  graça.
- [x] Buggy (OP16-041): novo evento `on_own_char_ko` (espelho de
  `on_opp_char_ko`, watcher=dono da vítima) com `victim_type_filter`.
  Disparado nos 8 pontos reais de K.O. do motor. Escopo conhecido: só
  cobre K.O., não bounce/deck-bottom (documentado no código).
- [x] Luffy (ST08-001): novo evento `on_any_char_ko` (notifica os dois
  lados, sem qualificador de lado). Bônus: EB01-047 (não-líder, mesma
  forma) corrigido de graça. Escopo conhecido: não filtra por
  "[Your Turn]".
  `diff_parser.py` PERDEU=0 MUDOU=5. 3 novos testes permanentes.
  `smoke_fast.py`/`smoke_test.py` 100%.
- [x] Trafalgar Law (OP01-002): passo de bounce, condição "5
  personagens" (exata) e filtro "cor diferente do devolvido"
  implementados. Bônus: EB01-020 (mesma forma) corrigido de graça.
  **Descoberto de brinde**: bug estrutural no mecanismo genérico
  "condição depois do delimitador de custo" (`[custo]: If C, efeito`)
  — anexava a condição a CADA step em vez de 1x no entry; o próprio
  bounce mudava o recurso (contagem de Characters) que o play_card
  re-checava depois, quebrando o play_card mesmo com o gate original
  satisfeito. Corrigido pra nível de entry (`execute()` já checa 1x
  antes do loop de steps) — mais correto pras ~150 cartas que passam
  por esse mecanismo, sem mudar comportamento de nenhuma. 8 testes
  existentes precisaram apontar pro lugar certo (entry, não per-step).
  `diff_parser.py` PERDEU=0 MUDOU=152 (2 gramática nova + 150
  relocação). `smoke_fast.py`/`smoke_test.py` 100%.
- [x] Boa Hancock (OP14-041): segunda habilidade (Amazon Lily/Kuja
  Pirates 5000+ power K.O.'d → dano ao oponente via deal_damage, "the
  owner's hand" = mão do PRÓPRIO oponente, não roubo) implementada.
  `on_own_char_ko` generalizado pra aceitar lista de tipos (OR) +
  `victim_power_gte`. **Bug de brinde**: tag `[DON!!x1]` sem espaço
  quebrava don_requirement em ~16 regex do parser inteiro (só esta
  carta usa essa grafia das 218 com a tag) — tolerância a espaço
  aplicada globalmente. Escopo conhecido não corrigido: tag
  "[Opponent's Turn]" na 1ª habilidade (draw ao jogar Character) ainda
  não filtra por turno (dispara em qualquer turno) — exigiria propagar
  `is_my_turn` por ~15 pontos que também afetam Sugar/Sanji/Bonney,
  fora de escopo. `diff_parser.py` PERDEU=0 MUDOU=3.
  `smoke_fast.py`/`smoke_test.py` 100%. `parser_snapshot.json`
  re-gerado (recuperou re-snapshot que faltou no item anterior).
- [x] Koala (OP12-081): gatilho OU de 2 condições ("custo≥8" OU "jogado
  via efeito de outra carta") — novo campo genérico `play_filter_or`
  (lista de filtros alternativos) + novo parâmetro `via_effect` em
  `_dispatch_char_played` (True quando vem de `_put_into_play`/efeito de
  outra carta, False/default em `_play_card`/jogada normal). Não afeta
  Sugar/Sanji/Bonney/Boa Hancock (mesma família, comportamento AND
  preservado quando não há OR). `diff_parser.py` PERDEU=0 MUDOU=1.
  `smoke_fast.py`/`smoke_test.py` 100% (3 cenários reais).
  `parser_snapshot.json` re-gerado.

**Revisão dos 135 líderes ENCERRADA — 6/6 corrigidos.** Próximos
passos: (1) retomar `resolve_reaction`/redirect; (2) ler/cruzar
`IA_Compendium/ONE_PIECE_AI_COMPENDIUM_Volume_1.pdf` (documento de
estratégia por deck mencionado pelo usuário, ainda não aberto nesta
sessão) contra os achados desta revisão.

## 🟢 IMPLEMENTADO (bloco 400): pente-fino texto-real vs efeito-parseado nos 17 líderes do pool de decks reais (29/07/2026)

Usuário pediu (1) continuar `resolve_reaction`/redirect e (2) auditar
cada um dos 17 líderes do pool real (`decklists_raw.csv`) comparando
texto real vs efeito parseado, pra confirmar que o bot entende cada
habilidade.

- [x] Enel (OP15-058, líder MAIS comum do pool, 56/161 decks): 2 bugs
  reais no próprio Activate:Main — condição "second turn or later"
  ausente (disponível já no turno 1), e `give_don` sempre emitido ANTES
  de `add_don` na ordem de steps (bug de ORDEM, não de conteúdo) — como
  o executor roda em ordem de lista, o DON dado nunca existia ainda,
  virando no-op silencioso no efeito principal da carta. Fix genérico
  em `gerar_effects_db.py` (nova condição `turn_gte` via tabela de
  ordinais; `parse_give_don` reescrito pra ordenar steps por posição
  textual, não pela ordem em que o código checa os regexes). Auditoria
  global: só Enel tinha os 2 padrões. `diff_parser.py` PERDEU=0
  MUDOU=1. Novo teste permanente. `smoke_fast.py`/`smoke_test.py` 100%.
- [x] Luffy (OP13-001): condição "5 ou menos DON ativo" ausente
  (`don_lte`, novo), custo "rest ANY NUMBER of DON" não existia
  (`rest_any_don`, novo), buff virava FIXO em vez de escalar (novo
  `source=rested_don_this_effect` em `buff_power_per_count`, `target`
  `leader_or_character` ganhou `filter_type`). Auditoria global: só
  Luffy(001) tem os 3 padrões. `diff_parser.py` PERDEU=0 MUDOU=1. Novo
  teste permanente. `smoke_fast.py`/`smoke_test.py` 100%.
- [x] Nami (OP11-041): trigger reativo ("quando uma carta é removida
  da Life") era tratado como check incondicional todo turno — confirmado
  real (mais 2 cartas: OP08-105 variante só-oponente, OP12-099 mesma
  forma). Exigiu ESTADO NOVO no engine (não só parser): `GameState`
  ganhou `life_count_snapshot_mine`/`life_count_snapshot_opp`
  (propagados em `clone()`), comparados a cada `apply_your_turn_buffs`
  contra a snapshot da vez anterior (aproximação do gatilho reativo real
  — `your_turn` só dispara 1x no início do turno, antes de qualquer
  combate próprio). Novas condições `life_removed_recently`/
  `opp_life_removed_recently`. `diff_parser.py` PERDEU=0 MUDOU=3. Novo
  teste permanente (3 checagens: sem baseline, vida inalterada, vida do
  oponente reduzida). `smoke_fast.py`/`smoke_test.py` 100%.

**Os 3 achados pedidos (Enel, Luffy, Nami) concluídos.** Próximo passo
pedido pelo usuário:

- [ ] Revisar TODOS os líderes do jogo (não só os 17 do pool de decks
  reais) — escopo ainda não levantado (quantos líderes existem no total
  em `cards_rows.csv`).
- [ ] `resolve_reaction`/redirect: ainda não retomado — fica por último,
  depois da revisão de todos os líderes.

## 🟡 EM ANDAMENTO (fechado no bloco 399): investigando activate:main e resolve_reaction por líder (29/07/2026, bloco 399)

Usuário pediu pra seguir com os 2 itens pendentes (bloco 398) e avisar
sempre que aparecer uma regra/calibração específica de carta/líder.

- [x] Mihawk-G (OP14-020) sub-ativa Activate:Main — **bug de parser
  real**, não heurística: "cost of 5 or more" parseado como EXATO
  (`board_has_cost:[5]`) em vez de MÍNIMO (`board_has_cost_gte:5`).
  Auditoria global achou +2 cartas (OP10-058, OP11-095). Regex
  corrigido, registro em `parser_audits/`, `diff_parser.py` PERDEU=0
  MUDOU=3, `smoke_fast.py`/`smoke_test.py` 100%. Self-play pós-fix:
  1,1→1,6 ativações/jogo (melhora real, vencedores reais=5,4 — gap
  residual provavelmente é prioridade/score no Turn Planner, não mais
  condição; fica pendente).
- [x] Jinbe-B (OP14-040) super-ativa Activate:Main (trash 1 mão → 2 DON
  rested, sem once_per_turn): ativava TODO turno sem exceção (4,9/jogo)
  vs vencedores reais 2,0/jogo. Causa: `give_don` caía no fallback
  genérico de `_score_activate_main` (base=60), sem refletir que o DON
  é *rested* (delayed), diferente de `add_don`/`set_don_active` (DON
  ativo imediato, base=90 correto). Escopo real: 49 cartas no banco
  usam `give_don` (todas rested=True) — fix é por AÇÃO, não hardcoded
  a Jinbe (confirmado: nenhum outro líder do pool de teste tem carta
  com `give_don`). Nova constante `GIVE_DON_RESTED_BASE_SCORE`. Teste
  pareado (10 valores, mesmos 5 líderes/decks/seed): **-10** dá 2,2
  ativações/jogo (mais perto do alvo real 2,0) E o melhor win rate de
  Jinbe-B entre os candidatos próximos do alvo (60% vs 30% baseline) —
  valor final aplicado. Novo teste permanente.
  `smoke_fast.py`/`smoke_test.py` 100%.
- [ ] `resolve_reaction`/redirect: lido `sim_bridge.py`, função já
  existe e é effect-aware (Teach/Doflamingo/Kid/EB01-038). Investigação
  de calibração ainda em andamento.

## 🟢 IMPLEMENTADO: mais alvos de calibração após as 3 primeiras frentes (29/07/2026, bloco 398)

Usuário pediu pra continuar calibrando os itens citados como pendentes:
activate:main, DON/ataque, EVAL_WEIGHTS/tune_weights.py, outros branches
de `should_use_blocker`, resolve_reaction.

- [x] `tune_weights.py`/`EVAL_WEIGHTS`: investigado e DEPRIORIZADO —
  sistema separado (Imu-específico, baselines hardcoded, path Windows).
  Sem evidência direta de miscalibração. Não avançado.
- [x] Extensão do cost-check de bloqueio (`BLOCK_CRITICAL_LIFE_MAX_COST`,
  já calibrado em 150 no bloco 396) pros branches `my_life==3`/`==4` de
  `should_use_blocker` (antes só tinham condição de "atacante forte",
  sem cost-check no blocker em si). Teste pareado (com vs sem extensão,
  mesmos 5 líderes/decks/seed, 50 partidas/variante): COM extensão 52%
  (26/50) vs SEM 42% (21/50) — bate baseline em 4/5 líderes. Mantida.
  Novo teste permanente. `smoke_fast.py`/`smoke_test.py` 100%.
- [x] Nova constante `ATTACK_MARGIN_DON_FRACTION` (escala a margem de
  DON "grátis" anexada além do déficit obrigatório em
  `don_needed_for_attack`). Teste pareado com 8 valores (1.0 a 0.0, mesmos
  5 líderes/decks/seed): win rate ficou ruidoso nesse tamanho de amostra
  (40%-60%, sem tendência clara) — decisão pelo alvo real, não pelo pico.
  DON/ataque agregado dos vencedores reais = 0,977; **0.7** dá o valor
  mais próximo (1,128, diff 0,15) sem regredir o win rate (50% vs 52%).
  Confirmado por cross-check independente pedido pelo usuário (jogos
  reais de Imu: vitória=1,31 DON/ataque vs derrota=0,38 — descarta o pico
  ruidoso em 0.3, que reproduzia o padrão de DERROTA). Valor final: 0.7.
  Novo teste permanente. `smoke_fast.py`/`smoke_test.py` 100%.

**As 4 frentes de calibração concluídas nesta sessão**: ataque (bloco
395), bloqueio crítico + extensão vida 3/4 (blocos 396/398), counter
(bloco 397), margem de DON por ataque (bloco 398).

- [ ] `activate:main` por líder: maior evidência (ex: Mihawk bot=1.4/jogo
  vs real=5.4; Jinbe-B bot=5.6 vs real=2.0), mas NÃO é um parâmetro
  único — precisa investigação qualitativa por carta/líder. Não
  iniciado.
- [ ] `resolve_reaction`/redirect: candidato citado, não investigado
  ainda.

## 🟢 IMPLEMENTADO: COUNTER_VALOR_VIDA_SCALE calibrado (1.3) via self-play pareado — achado CONTRA a hipótese inicial (29/07/2026, bloco 397)

Terceira frente do pedido do usuário (mesma metodologia dos blocos
395/396). Hipótese inicial (reduzir a escala, já que o bot countera
mais que o vencedor real) estava ERRADA — self-play mostrou o oposto.

- [x] Nova constante `COUNTER_VALOR_VIDA_SCALE` — multiplica a tabela
  `valor_vida` inteira por igual.
- [x] Teste pareado pra baixo (1.0/0,7/0,5/0,3): win rate agregado
  44%/42%/38%/38% — reduzir SÓ piorou, mesmo reduzindo a taxa de
  counter de verdade (31,3%→22,4%). Diferente do bloqueio: aqui o
  jogador real médio está SUBCONTERANDO, não o bot supercounterando.
- [x] Teste pareado pra cima (1,3/1,6): win rate 52% (pico)/42%
  (reverte). **1,3 bate o próprio baseline de 1.0** (52% vs 44%).
  Valor final aplicado.
- [x] Ajuste em `smoke_fast.py` (caso delicado): um teste refletia uma
  decisão de escopo deliberada com o usuário (24/07 — "empilhar 2+
  cartas caras continua recusado"). Cenário revisado (gasto 100→150)
  pra preservar essa intenção sob a nova escala, não só destravar o
  assert.
- [x] Novo teste permanente (`test_counter_valor_vida_scale_calibrado_29_07`).
  `smoke_fast.py`/`smoke_test.py` 100%.

**As três calibrações pedidas concluídas**: ataque (bloco 395, 100→400),
bloqueio (bloco 396, None→150), counter (este bloco, 1.0→1.3).

## 🟢 IMPLEMENTADO: BLOCK_CRITICAL_LIFE_MAX_COST calibrado (150) via self-play pareado (29/07/2026, bloco 396)

Segunda frente do pedido do usuário (mesma metodologia do bloco 395).

- [x] Nova constante `BLOCK_CRITICAL_LIFE_MAX_COST`. Quando finito,
  exige `custo_sacrificio(melhor) <= valor` mesmo com vida<=2 (antes:
  sempre bloqueava, sem check nenhum).
- [x] Teste pareado (None/150/100/60, mesmos 5 líderes/decks/seed do
  bloco 395): win rate 52%/52%/46%/50%, bloqueios em vida≤2
  11,9%/8,9%/5,5%/~0%. **150** empata o win rate do baseline sem
  regredir, reduzindo o bloqueio incondicional de verdade — 100 e 60
  já pioram o win rate. Valor final aplicado.
- [x] Ajuste em `smoke_fast.py` (não regressão): teste de ponta a ponta
  do K.O. reativo (ST10-006) tinha vida=0 no cenário sintético,
  calibrado pro comportamento antigo — ajustado pra vida=3 (branch sem
  o cost-check novo), preservando o propósito original do teste.
- [x] Novo teste permanente (`test_block_critical_life_max_cost_calibrado_29_07`).
  `smoke_fast.py`/`smoke_test.py` 100%.
- [ ] `should_use_counter`: ainda não iniciado — decisão do usuário se
  quer continuar essa rodada de calibração ou considerar encerrada.
  Duas calibrações pedidas (ataque + defesa) já concluídas.

## 🟢 IMPLEMENTADO: ATTACK_LEADER_BASE_SCORE calibrado 100→400 via self-play pareado (29/07/2026, bloco 395)

Usuário decidiu (resolve a pendência do bloco 394): calibrar de verdade,
usando self-play pareado com decks reais (`decklists_raw.csv`) como
validação, não só teoria/dado de log.

- [x] Validado: `ReplayMatch`/`audit_replay.py` delega 100% pro motor
  real (`OPTCGMatch.play_turn`), 3 partidas de teste rodadas aqui, 0
  exceções.
- [x] Self-play bot vs pool de 161 decks reais comparado aos vencedores
  reais (5 líderes com amostra confiável): bot ataca o líder MENOS que
  o vencedor real em 4/5 casos, anexa mais DON por ataque em todos os 5.
- [x] `ATTACK_LEADER_BASE_SCORE` (extraído do literal `100` em
  `score_attack_target`): teste pareado com 5 valores (100/175/250/
  400/600, mesma seed/matchups, 5 líderes x 10 partidas cada). Pico
  claro em **400** — win rate agregado 36%→52%, %líder 76,2%→87,2%
  (perto do real 84,1%), DON/ataque 1,9→1,8 (efeito colateral, sem
  calibração separada). 600 reverte pro win rate original — não vale
  subir mais. Valor final aplicado.
- [x] Ajuste em `smoke_fast.py` (não regressão): cenário sintético do
  teste de teto de desconto-de-trigger foi calibrado pro baseline
  antigo (100) — recalcula a vida mínima a partir de
  `ATTACK_LEADER_BASE_SCORE` em vez de hardcoded.
  `smoke_fast.py`/`smoke_test.py` 100%.
- [ ] `should_use_blocker`/`should_use_counter`: ainda não iniciado.
  Alvo identificado — regra incondicional "sempre bloqueia com
  vida<=2" em `should_use_blocker` (~linha 10922, `decision_engine.py`).
  Mesma metodologia (self-play pareado com os mesmos 5 líderes/decks).

## 🟢 RESOLVIDO (texto desta seção estava desatualizado): should_use_blocker/should_use_counter FORAM calibrados nos blocos 396-398 (28-29/07/2026, bloco 394 original)

> **Achado 30/07 ao revisitar esta seção**: o texto abaixo (original do
> bloco 394) ficou parado dizendo "decisão pendente" mesmo depois da
> decisão ter sido tomada e EXECUTADA em blocos posteriores — o usuário
> escolheu a opção (b)/self-play pareado (ver abertura do bloco 395:
> "Usuário decidiu... calibrar de verdade, usando self-play pareado com
> decks reais"), e os blocos 396/397/398 fizeram exatamente isso pros 2
> itens citados aqui. Confirmado lendo o código atual
> (`decision_engine.py`): `BLOCK_CRITICAL_LIFE_MAX_COST = 150` (bloco
> 396) e a regra incondicional "sempre bloqueia com vida≤2" citada
> abaixo **não existe mais** — `should_use_blocker` (~linha 11353) já
> tem cost-check (`custo_sacrificio(melhor) <= BLOCK_CRITICAL_LIFE_MAX_COST`)
> pra vida≤2, ESTENDIDO pra vida==3 e vida==4 no bloco 398 (validado via
> self-play pareado, 52% vs 42% win rate). `COUNTER_VALOR_VIDA_SCALE =
> 1.3` (bloco 397) já está aplicado em `should_use_counter` (~linha
> 11580). Ambos os itens desta seção estão FECHADOS — apagar/arquivar
> esta seção era o certo, mantida aqui só como registro de que a
> "pendência" listada abaixo já não reflete o estado real do código.

Texto original (histórico, não mais válido — mantido só pra contexto):
Com os números REAIS pós-fix do gap de Blocker (ver item abaixo): IA
mais "defensiva" que o jogador real em bloqueio (109 "IA queria
bloquear, humano não" vs 72 no sentido oposto, ~1,5x) e counter (304 vs
159, ~1,9x). MAS o dado puro do log (sem reconstrução, bloco 393) já
mostra que VENCEDORES bloqueiam/counteram mais que PERDEDORES — ou
seja, "a IA é mais agressiva na defesa que o jogador médio" não é
obviamente um bug, pode ser só uma extrapolação correta da mesma
tendência que já favorece vencedores. 63/109 dos casos de bloqueio
acontecem na regra incondicional de `should_use_blocker` pra vida≤2
("sempre bloqueia se tiver bloqueador", `decision_engine.py` ~linha
10922) — o ponto óbvio pra afrouxar, mas SEM evidência de que afrouxar
melhoraria o bot (poderia piorar). ~~Decisão pendente: (a) aceitar o fix
do banco como entregável sem mexer em pesos; (b) calibrar mesmo sem
validação via self-play; (c) esperar sessão local rodar
`baseline_metrics.py`/gauntlet antes de decidir.~~ (b) foi a escolhida e
executada.

## 🟢 CORRIGIDO: gap de [Blocker] condicional — auditoria global, 32 cartas (28/07/2026, bloco 394)

Busca global (`gains? \[Blocker\]` em `cards_rows.csv` inteiro) achou 83
cartas, não as 3 vistas nos logs. 4 causas raiz distintas, todas
corrigidas pela FORMA (não hardcoded pros codes que revelaram cada
uma) — ver `scriptis_da_ia/parser_audits/2026-07-28_blocker_condicional_e_reminder_text_como_custo_fantasma.json`
pro detalhe completo:

- [x] Custo fantasma `rest_self` (reminder text do keyword casando com
  o regex de custo) — ~30 cartas, `parse_costs()` corrigido.
- [x] 6 condições novas: `has_other_named`, `has_named_card_on_field`,
  `chars_gte_color_filter`+`chars_gte_exclude_self` — cobriu também 2
  bugs LATENTES pré-existentes (OP10-053, OP13-009) que já usavam
  "other than" sem a exclusão de self aplicada.
- [x] `gain_blocker` sob a tag `[Opponent's Turn]` (bloco `opp_turn`)
  nunca era escaneado por `apply_conditional_keyword_passives` — agora
  é (Pearl OP15-011, Brook ST31-003).
- [x] 4 cartas com `[Blocker]` ausente do `card_text` na FONTE
  (`cards_rows.csv`), confirmado nos logs reais que bloqueiam de
  verdade: Trafalgar Law OP10-119, Killer ST36-002, Basil Hawkins
  OP10-109, Morgan OP15-017 — corrigido com edição cirúrgica (4
  inserções/4 deleções no CSV, não reescrita inteira).
- [x] `diff_parser.py` GANHOU=0 PERDEU=0 MUDOU=32 (esperado).
  `gerar_dbs.py` rodado. `smoke_fast.py` ganhou
  `test_blocker_condicional_auditoria_global_28_07` (12 asserts).
  `smoke_test.py` 100%.

## 🟢 investigação de "ordem de defesa" (bloqueio/counter) + fix de reconstrução (28/07/2026, blocos 393/394)

- [x] Achado real (dados puros do log, sem reconstrução): vencedores
  bloqueiam mais (10,2% vs 7,4%), counteram mais (37,6% vs 29,3%) e
  ainda assim tomam menos dano (43,5% vs 54,7% dos ataques acertam) do
  que perdedores.
- [x] Bug real corrigido: `_apply_rested_counts` (criada no bloco 392)
  só era aplicada ao board do OPONENTE — pra avaliar a decisão de
  BLOQUEIO do próprio defensor, ele precisa ser reconstruído como
  jogador "ativo" (pra ter a mão real dele), e nesse papel o board dele
  não recebia o mesmo tratamento. Generalizada pra os dois lados.
  `smoke_fast.py`/`smoke_test.py` 100%.
- [x] Números de ataque do bloco 392 recalculados com o fix (mais
  precisos agora): concordância de alvo caiu de 58,4% pra 52,3%.
- [x] **Números REAIS pós-fix do gap de Blocker** (corrigindo a
  ESTIMATIVA especulativa do bloco 393, que tinha subtraído os 47 casos
  "artefato" sem reprocessar de verdade): bloqueio 85,0% de concordância
  (109 "IA queria bloquear, humano não" vs 72 no sentido oposto, ~1,5x —
  não os 3,4x estimados); counter 62% (inalterado pelo fix de Blocker,
  não depende de board — 304 vs 159, ~1,9x). Em ambos os eixos, a IA
  tende a ser MAIS defensiva que o jogador real.
- [ ] Nenhum peso de scoring foi ajustado — achado ambíguo, ver item
  no topo deste arquivo.

## 🟢 IMPLEMENTADO: parse_combat_log.py rastreia active/rested do oponente (28/07/2026, bloco 392)

Sem isso, a comparação IA-vs-humano de ALVO de ataque (líder vs
personagem) era inválida — todo personagem do oponente nascia "ativo"
por padrão na reconstrução, e a regra do jogo só permite atacar o líder
OU um personagem REALMENTE rested, então a IA nunca conseguia sugerir
legalmente um ataque em personagem (dava "100% prefere líder", artefato
de ferramenta, não achado real).

- [x] `parse_combat_log.py`: rastreio incremental (Deploy entra rested,
  atacar resta o atacante, refresh no início do próprio turno, efeitos
  "Rest X"/"Destroy X" no texto livre) + reconciliação contra o board
  real a cada turno (nunca gera contagem maior que a real, mesmo com
  verbo de remoção não coberto).
- [x] Reparse retroativo: 84/114 raw logs ainda presentes reparseados
  (30 mais antigos usam caminho `autosaved_log` sem raw neste ambiente —
  ficam sem o dado novo). Validado como aditivo puro (dry-run + diff)
  antes de sobrescrever os JSON git-tracked.
- [x] `compare_vs_human.py` (`build_game_states`) aplica a contagem nas
  N primeiras cópias de cada code no board do oponente reconstruído.
- [x] Teste permanente em `smoke_fast.py`
  (`test_parse_combat_log_rastreia_rested_active_do_oponente`, log real,
  não sintético). `smoke_fast.py` + `smoke_test.py` 100%.
- [x] Resultado (comparação de alvo agora válida): 689 turnos, 1114
  pares mesmo-atacante — concordância de alvo 58,4%. Dos 463
  desacordos, 82% são "humano foi na cara, IA queria trocar" (só 18% o
  oposto) — bate com vencedores atacando o líder 83% vs 62% dos
  perdedores (achado já registrado antes, ver bloco 392 do HANDOFF).
- [x] **Achado forte específico em Imu-B** (pedido do usuário pra
  aprofundar nesse líder — pior recorte da base, 6V/29D): 38% de TODOS
  os desacordos da base inteira vêm só de partidas com Imu-B, 79% deles
  "líder Imu foi na cara, IA queria trocar". Conferido manualmente
  contra o log cru (não é falso positivo do rastreio novo).
- [ ] **NÃO implementado**: nenhum ajuste de peso de scoring de ataque
  em cima disso — mesma cautela anti-overfitting do bloco 391 (a
  comparação usa `_generate_and_score_actions` isolado, não o Turn
  Planner com Monte Carlo completo que roda ao vivo). Fica pra decisão
  do usuário se/como calibrar.
- [ ] 30 logs sem raw local (caminho `autosaved_log`) continuam sem
  `rested` — só logs com raw disponível neste ambiente foram
  reparseados.

## 🟢 IMPLEMENTADO: identifica lado do bot via Shift+P em vez de assumir vencedor (28/07/2026, bloco 389)

Usuário pediu explicitamente pra não tratar "vencedor" como proxy de
"humano" — quer o dado real do Shift+P (`BotDriver.cs` já loga "agora
controla P1/P2" no `LogOutput.log` do BepInEx a cada toggle).

- [x] `parse_combat_log.py` ganhou `detectar_lado_bot_via_bepinex_log`
  + `--bepinex-log <caminho>` — grava `bot_side` ('p1'/'p2') no
  `index.json` quando dado. Testado com arquivo sintético (3 cenários)
  + fluxo completo de `add_to_db`.
- [ ] **PENDENTE, importante**: nunca testado contra um `LogOutput.log`
  REAL (sessão remota não tem acesso). Validar na próxima partida ao
  vivo — rodar `--add-to-db --bepinex-log "caminho\LogOutput.log"`
  logo após a partida e conferir se `bot_side` bate com o que você
  sabe que jogou.
- [ ] **PENDENTE**: os 114 logs já banco não têm `bot_side` (feature
  não existia quando foram adicionados) — ficam `None` pra sempre,
  a não ser que o `LogOutput.log` daquelas sessões ainda exista em
  algum lugar. Só logs novos, adicionados com `--bepinex-log` a partir
  de agora, terão esse dado.
- [ ] **PENDENTE**: `LogOutput.log` não tem timestamp correlacionável
  com o combat log oficial — se trocar de lado no meio de uma sessão
  com várias partidas, só reflete o estado FINAL do arquivo. Rodar
  `--add-to-db --bepinex-log` logo após CADA partida (antes de trocar
  de lado de novo) pra manter a correlação certa.

## 🟢 CORRIGIDO: desconto de counter em vida baixa era um cancelamento perfeito, não "subcalibrado" (28/07/2026, bloco 391)

A pendência do bloco 388 (abaixo, framing antigo mantido riscado pra
histórico) estava **errada no diagnóstico**: não era questão de
magnitude pequena — era um bug de cancelamento. `_score_play_action`
faz `base = engine.avaliar_carta(card)`, que JÁ soma
`_counter_stat_bonus(card)` (linha ~9762). O "desconto" em
`_score_play_action` (linha ~12052) subtraía esse MESMO valor de volta
— cancelamento perfeito, **independente da magnitude da constante**.
Confirmado testando `COUNTER_STAT_VALUE_PER_1000` em 15/30/45/60/90/120
contra 29 estados reais: 0/29 mudaram de sugestão, scores idênticos
byte a byte em qualquer valor.

Usuário pediu explicitamente pra não calibrar em cima de 1 partida só
("tenho certeza que isso não acontece só em uma partida") — scan
sistemático em TODOS os 114 logs confirmou: 130 turnos com vida<=2, 29
com carta de counter>=1000 como topo da IA, 20-21 desses (~69-72%,
número varia um pouco por causa de reprocessamento) SEGURADOS (não
jogados) pelo jogador real vencedor, em ~20 partidas distintas,
jogadores diferentes, datas diferentes.

- [x] Fix: `base -= 2 * engine._counter_stat_bonus(card)` (anula o
  crédito de `avaliar_carta` + aplica a penalidade real de fato).
- [x] Validado nos MESMOS 29 estados reais (antes/depois do fix, script
  descartável, não commitado): 3/29 flips de "topo = jogar a carta de
  counter" pra outra ação — as 3 flippadas eram TODAS casos onde o
  humano vencedor tinha SEGURADO a carta (direção certa). As 26
  restantes (18 held + 8 played) tiveram score reduzido de verdade
  (deltas de -15 a -60), sem nenhum caso "played" virando "held"
  incorretamente (sem overcorreção visível nessa amostra).
- [x] `smoke_fast.py` 100% após o fix.
- [ ] Não validado via self-play/gauntlet completo (`baseline_metrics.py`
  não roda nesta sessão remota — path Windows hardcoded pra decks).
  Se possível numa sessão local, rodar antes/depois pra confirmar que
  não piora resultado agregado.

<!-- histórico (framing superado, ver correção acima):
🟡 PENDENTE DE CALIBRAÇÃO (não bug): desconto de counter em vida baixa
pode estar subcalibrado (28/07/2026, bloco 388) -->

## 🟢 IMPLEMENTADO: 3 melhorias em compare_vs_human.py/parse_combat_log.py (28/07/2026, bloco 388)

- [x] Rótulo `activate`→`play` normalizado pra cartas EVENT (resolveu
  3 dos 7 casos originais de "supervalorização de play" — era
  rotulagem, não bug de scoring).
- [x] Categorização automática de misses (`miss_patterns`, todos os
  misses agregados por padrão, não só os 12 primeiros) + `--summary`
  agora aceita `--player`.
- [x] `parse_combat_log.py` detecta o vencedor de verdade
  (`detectar_vencedor`) e preenche `winner` em `add_to_db()` — antes
  sempre `None` nesse caminho. Backfill rodado: 48 entradas antigas
  ganharam `winner` (42 já tinham de outra fonte, não sobrescritas; 24
  continuam sem dado suficiente).
- [ ] **NÃO implementado ainda** (maiores, escopo pra outra sessão):
  comparação por sequência (aplicar ação real + reavaliar próximo
  passo), pipeline real com Monte Carlo na comparação (precisa
  `OpponentModel` do deck revelado em `logs/decks/`), fallback do
  turno 1 continua imperfeito. Ver bloco 388 do HANDOFF pro motivo de
  cada um não ter sido feito agora (risco de bug sutil numa ferramenta
  cuja função é ser confiável, melhor escopar com calma).

## 🟢 compare_vs_human.py rodado em TODOS os logs banco (28/07/2026, bloco 387)

Resultado agregado (só turnos do lado VENCEDOR, detectado por
heurística de último-ataque/Quits — ver bloco 387 do HANDOFF pro
método, `winner` do index.json é cosmético): 343 turnos, 150 erros de
reconstrução (concentrados em logs antigos de Imu), 193 comparações
válidas. **top1 exact 62.7%, top5 exact 90.7%** — o Turn Planner bate
com o vencedor na grande maioria dos casos; a percepção de "joga muito
mal" provavelmente vem dos casos dramáticos isolados (como o ST22-015)
ou de decisões fora do escopo desta comparação (defesa, mulligan,
sequenciamento multi-ação por turno).

- [x] Achado importante registrado: rótulo `You`/`Opponent` NÃO
  identifica o bot de forma confiável entre sessões (Shift+P troca o
  lado) — qualquer análise futura precisa detectar o VENCEDOR (última
  ação de ataque antes de GameOver/Quits), não assumir o rótulo.
- [ ] **PENDENTE, o mais concreto**: padrão de divergência mais comum
  (7/193) é vencedor fazendo `activate+attach_don+attack` (usa o board
  já existente) enquanto a IA top-1 sugeria `play` (desenvolver mão).
  Não investigado a fundo — precisa achar exemplos específicos e ver
  se é super-valorização genérica de desenvolvimento vs capitalizar
  ataque, ou caso a caso.
- [ ] **PENDENTE**: alternativas de melhoria pro `compare_vs_human.py`
  catalogadas no bloco 387 do HANDOFF (comparação por sequência em vez
  de 1 decisão por turno, usar o pipeline real com Monte Carlo em vez
  de só score imediato, corrigir rótulo activate/play de EVENT,
  registrar vencedor explicitamente no parse do log). Nenhuma
  implementada ainda — são só alternativas catalogadas, priorizar
  antes de implementar.

## 📚 Catálogo de ferramentas criado: `scriptis_da_ia/FERRAMENTAS.md` (28/07/2026, bloco 387)

Usuário relatou não lembrar que `compare_vs_human.py` existia — criado
documento resumindo as ~49 ferramentas Python do projeto por propósito
(comparação com humano, eficiência, parser, banco de logs, replay,
análise de deck, backend, bot ao vivo, testes, ML experimental) com
tabela de "qual ferramenta usar quando". Manter atualizado quando uma
ferramenta nova for criada — é fácil esquecer o que já existe numa base
de ~50 scripts.

## 🟢 IMPLEMENTADO: play_card aninhado agora credita o valor de quem é trazido (28/07/2026, bloco 386)

Usuário pediu método concreto pra "bot joga mal": comparar Turn Planner
vs jogada vencedora do humano num log real (`compare_vs_human.py`, já
existia no repo). Achado real na partida Katakuri x Ace (T10): `ST22-015`
("I Am Whitebeard!!") joga Edward Newgate de graça + buff + life-to-hand,
mas pontuava 140 — menos da metade de jogar Newgate direto (280). Causa:
`_score_play_action` só credita bônus de flag genérico pro efeito "jogar
outra carta", nunca o valor real de quem é trazido (gap que já existia
resolvido em `_score_activate_main`, nunca replicado aqui).

- [x] Fix genérico implementado (não hardcoded pra ST22-015): credita
  `min(valor_da_melhor_carta_elegivel * 0.75, 400)`, reusando
  `eligible_cards` (mesmo filtro da execução real). ST22-015 sobe pra
  305 (acima de Newgate direto). Teste novo em `smoke_fast.py`,
  `compare_vs_human.py --summary` rodado nos 114 logs sem exceção nova.
- [ ] **PENDENTE, cosmético**: `compare_vs_human.py` ainda acusa
  "DIVERGENCIA" no T10 mesmo com o fix — rotulagem, não bug de decisão.
  O parser do log registra a jogada como 2 `activate` separados
  (`ST22-015`, `OP13-042`), o motor trata como 1 `play` só (resto é
  cascata automática) — `_ai_match_label`/`_human_action_key` comparam
  `(type, card)` literal e nunca batem `play` com `activate` da mesma
  jogada real. Se for mexer em `compare_vs_human.py` de novo, considerar
  tratar EVENT resolvido (que o log rotula "activate") como equivalente
  a `play` na comparação.
- [ ] **PENDENTE (maior, registrado explicitamente)**: esse foi UM
  achado de UM log. O usuário quer o bot jogando "parecido/idêntico" ao
  humano — isso pede repetir esse MESMO método
  (`compare_vs_human.py --player <vencedor>`) em MAIS logs onde o
  humano venceu, catalogar os padrões de divergência recorrentes (não
  só scoring de carta — pode ter padrão em ordem de ataque, uso de
  DON, decisão de bloqueio), e só então generalizar mais fixes — nunca
  copiar uma linha específica de 1 partida (overfitting), sempre a
  FORMA do problema.

> 28/07/2026 (bloco HANDOFF 385): merge com a sessão remota (blocos
> 375-384) depois de divergência no push — resolvido mantendo os dois
> lados (unificação do Turn Planner + fixes de hoje). Ver bloco 385 do
> HANDOFF pro detalhe. **Resposta parcial ao item urgente abaixo (bot
> só passando o turno, bloco 384)**: as partidas ao vivo desta sessão
> local não reproduziram o sintoma, mas rodaram com código de ANTES
> deste merge — não é confirmação de que sumiu. Próximo passo: uma
> partida ao vivo com o `server.py` reiniciado neste commit merged.

> 27/07/2026 (bloco HANDOFF 374): **Bug real corrigido** —
> `GameState.is_active_turn` nunca era setado no caminho ao vivo
> (default `True` sempre, nos dois lados). Quebrava qualquer lógica
> `timing='your'/'opponent'` — especificamente o guard "só paga
> don_minus se o buff vira o combate" do líder Katakuri era pulado
> inteiro sempre que ST34-001 (carta do próprio deck, ramp de DON "só
> no meu turno") estava em campo, porque o motor achava que era sempre
> o turno do bot. Resultado real reportado pelo usuário: Katakuri
> pagando `-1 DON` toda vez que era atacado, mesmo já vencendo o
> combate sem precisar do buff — ficou sem DON a partida inteira.
> Corrigido em 3 pontos (`/decide`, `/defense` por fase,
> `resolve_optional_effect` via `actor_defending`). 2 testes novos,
> `smoke_fast`/`smoke_test` 100%. **2º bug corrigido no mesmo bloco**:
> no mesmo log, o Turn Planner planejou um ataque de líder pra 8000
> power (2 DON anexados + buff próprio do Katakuri) mas o custo `Minus
> 1 Don` da habilidade comeu 1 dos DON recém-anexados (não sobrava
> outra fonte), resultando em ataque real de só 6000 contra o líder do
> oponente a 8000 — "Attack Fails", Katakuri quase morreu. Fix em
> `don_needed_for_attack`: assume o PIOR CASO no cálculo do déficit
> (buff self-canibalizável não conta de graça) em vez de tentar prever
> "sobra folga?" — essa previsão colidia com o teto de DON disponível
> exatamente no caso real (don_minus_count=1). 2 testes novos,
> `smoke_fast`/`smoke_test` 100%. **Pendente**: mesmo com DON
> suficiente calculado corretamente, se o bot não TIVER esse DON
> disponível o ataque ainda sai declarado insuficiente — decidir se
> vale atacar mesmo assim (pressão) ou recusar é decisão de scoring,
> separada, fica pra investigar se aparecer ao vivo de novo.

> 27/07/2026 (bloco HANDOFF 373): **Achado agregado sobre "não entende
> sinergia"** — escaneei os 25 arquivos de decision log históricos
> procurando o padrão "mesma ação escolhida 3x+ no mesmo turno": achei
> 20 ocorrências, quase todas (19/20) do MESMO bug — `activate`
> Charlotte Pudding (OP11-070, `peek_opp_deck_top`) travando em loop.
> Acontece em praticamente TODO turno com ela em campo, confirmado em
> 6+ partidas históricas (20-22/07). **Duas tentativas de correção
> anteriores** (commits `846652f` 21/07 e `bae86b6` 22/07) não
> resolveram — o loop reproduziu de novo DEPOIS dos dois fixes.
> Hipótese: `peek_opp_deck_top` é um reveal sem escolha real, e o
> fallback de `CancelPendingAction` (BotDriver.cs) reverte a ativação
> inteira incluindo o custo `rest_self` já pago, deixando a carta
> sempre "reativável". **Ação**: log de diagnóstico adicionado no
> ponto do Cancel, plugin recompilado e reinstalado. **Pendente**:
> teste ao vivo com Katakuri pra capturar o log e achar a causa raiz
> definitiva (2 tentativas anteriores já falharam sem esse log).
> Bot vs bot automático (pedido do usuário) e loop de N partidas
> automáticas continuam pendentes pra depois da investigação de combo.

> 26/07/2026 (bloco HANDOFF 372): **Bug estrutural achado e corrigido**
> em `_step_is_viable` (decision_engine.py) — código morto (`return`
> preso dentro de um `if` inserido depois, nunca alcançado) fazia TODA
> a família `ko`/`rest_opp_character`/`debuff_power`/`debuff_cost`/
> `bounce`/`lock_opp_character_refresh`/`lock_opp_character_attack`/
> `place_opp_character_bottom_deck` (895 ocorrências no banco de
> efeitos) sempre "viável" mesmo sem NENHUM alvo elegível no campo do
> oponente. Achado investigando reclamação do usuário sobre o Krieg
> ("não usou o efeito nenhuma vez") — na verdade o engine ESCOLHEU
> ativar o efeito do líder corretamente (confirmado no combat log,
> "Rest Sengoku"), só que cedo demais nos primeiros turnos não havia
> alvo válido ainda (exige DON≥2 no character do oponente). Mas a
> investigação revelou esse bug bem maior por trás. Fix: move o
> `return` pro lugar certo + trata 2 casos que a checagem genérica não
> cobria (`target=opp_leader`/`opp_leader_or_character` sempre viável,
> `alt_target` como fallback quando o alvo primário não existe).
> `smoke_fast`/`smoke_test` 100% (achou e corrigiu 6 falhas reais no
> processo — todas casos legítimos que só "funcionavam" antes por
> acidente do bug). **Pendente**: validar ao vivo com qualquer deck
> que tenha cartas dessas 8 ações. **"Não entende sinergias/combos"
> continua pendente** — isso é diferente (scoring/priorização entre
> cartas, não viabilidade de alvo) e precisa de exemplo concreto do
> usuário pra investigar.

> 26/07/2026 (bloco HANDOFF 371): **Item 1 do bloco 370 corrigido**
> (loop travado de `once_per_turn`) — causa real era mais funda que o
> guard do BotDriver.cs: `_dedupe_scored_actions` agrupava 2 cópias
> idênticas de OP09-093 numa única candidata `activate` (por
> assinatura da carta, não por `card_uid`), então a 2ª cópia nunca
> era sequer OFERECIDA como opção. Fix em 2 camadas: `server.py`
> rastreia ações que falharam confirmação este turno
> (`_failed_actions_this_turn`, mesmo padrão do `_declined_optional`
> já existente), e `decision_engine.py`/`sim_bridge.py` excluem essas
> instâncias ANTES do dedupe (não só depois), deixando a cópia
> saudável virar candidata. Teste novo em `smoke_fast.py` reproduz o
> cenário sem depender do jogo real. `smoke_fast`/`smoke_test` 100%.
> **Pendente**: causa exata do clique não mudar o estado do jogo real
> na 1ª tentativa continua desconhecida (Unity-side, não investigada
> — o fix trata o sintoma/turno perdido, não essa causa). **Itens 2 e
> 3 do bloco 370 continuam pendentes**: efeito da Charlotte Linlin
> (ST34-004) não resolve após custo opcional, e overplay de carta
> custo 1 (51.9% das jogadas). **Próximo passo: validar este fix ao
> vivo** (Barba Negra, cenário de 2 cópias custo 10).

> 26/07/2026 (bloco HANDOFF 370): **Primeiro teste ao vivo pós-Fase D** —
> 3 partidas (Katakuri x2, Barba Negra x1). 2 bugs de execução achados,
> não relacionados ao Fase D (pré-existentes, só apareceram agora por
> ser o primeiro volume de jogo com esses decks):
> 1. **Prioridade alta, em correção agora**: loop travado de
>    `once_per_turn` em `activate_main` — bot reoferece/reescolhe uma
>    habilidade `[Activate: Main]` já usada no turno (OP09-093, Barba
>    Negra custo 10) em vez de reconhecer que já foi gasta, até travar
>    a execução e perder o turno inteiro (nenhum ataque declarado — é
>    isso que pareceu "esqueceu de dar alvo no líder"). 2ª cópia da
>    carta nunca chega a ativar.
> 2. **Pendente investigar**: efeito on_play de Charlotte Linlin
>    (ST34-004) não resolve após pagar o custo opcional `don_minus`
>    (Minus 4 Don loga, mas nem o debuff nem o gain_life aparecem no
>    combat log nem geram decisão de alvo). Root cause diferente do
>    item 1.
> 3. **Pendente investigar**: overplay de carta custo 1 confirmado com
>    número (51.9% das 27 jogadas do dia foram custo 1) — pode ser peso
>    de curva/ramp desbalanceado no scorer.
>
> `gate_status: fail` nos 3 jogos, `bot_confusion` subindo
> (6→11→16 acumulado), 1 lethal certificado que não fechou a partida.
> Ver bloco HANDOFF 370 pros detalhes/evidência completa.

## 🟢 RESOLVIDO NA PRÁTICA: bot só passando o turno ao vivo (bloco 384; confirmado bloco 411)

Usuário reportou, jogando contra o bot depois dos blocos 381/382, que o
bot só passa o turno (`end_turn`), sem jogar/atacar. Suspeita maior:
`server.py` do usuário não tinha sido reiniciado depois do `git pull`.

- [x] **Confirmado ao vivo (02/08/2026, bloco 411)**: matei o `server.py`
  antigo (rodando código de antes de todos os merges) e subi de novo em
  `10a59a8`. Partida real (Katakuri vs Ace, 10 turnos) — bot jogou
  `activate`/`play`/`attack` normalmente em quase todo turno, nunca
  travou. As 5 ocorrências de `no_eligible_action` na telemetria são o
  sinal CORRETO de "acabou as ações, encerra o turno" (1 por turno
  próprio, confirmado no código `sim_bridge.py:629-632` — só dispara com
  lista de candidatos genuinamente vazia), não o bug relatado.
- [x] **Achado novo, separado (bloco 411)**: a busca ao vivo bateu no
  timeout de 3s **5 vezes** nesta única partida, todas nos turnos 3-5
  (meio de jogo). Não causa "sem ação" — existe fallback de score
  imediato ANTES da busca Monte Carlo rodar (`sim_bridge.py:634-641`),
  então o bot sempre manda uma ação válida, só sem o refino de
  simulação/contrafactual nesses momentos. Ver item novo abaixo.

## 🟡 PARCIAL (02/08/2026, bloco 411; causa parcial corrigida 03/08, bloco 426): busca ao vivo bate no timeout de 3s com frequência real — degrada pra score imediato sem refino

Numa única partida real (10 turnos), 5 timeouts de busca
(`timed_out=True`, latência ~3014-3039ms contra o timeout de 3.0s
configurado em `server.py`), concentrados nos turnos 3-5 (meio de jogo,
board mais cheio/mais candidatos). Não é bug de correção (o fallback de
score imediato já protege contra "sem ação"), mas é perda real de
qualidade de decisão nesses momentos — a IA decide sem o lookahead
Monte Carlo que normalmente teria.

- [x] **Causa parcial encontrada e corrigida (03/08, bloco 426)**:
  `full_deck_plan`/`full_deck_census`/`full_deck_profile` do lado do
  oponente nunca eram populados ao vivo (só o lado próprio), forçando
  `compute_game_plan`/`posture()` a recalcular do zero em toda simulação
  do turno de resposta do oponente — 26% do tempo de uma partida real de
  self-play nisso (profiling). Fix: `populate_full_deck_knowledge`
  reusada em `_dto_to_gs` (decklist aproximada via
  `opponent_model_for_leader`). Reprofiling da mesma partida: -30,7% no
  tempo total. Ainda não medido ao vivo (telemetria `decision_timeouts`)
  se isso sozinho já elimina os timeouts de 3s ou só reduz a frequência
  — próxima partida real deve conferir.
- [ ] Se ainda bater timeout depois deste fix: investigar mais
  (board mais cheio? mais candidatos em `SEARCH_TOP_K`? amostragem
  adaptativa subindo até o teto com frequência?).
- [ ] Juntar mais partidas reais antes de decidir se vale subir o
  timeout, reduzir `SEARCH_SAMPLES_MAX`/`SEARCH_TOP_K`, ou otimizar o
  hot path ainda mais.

## ✅ doc: `BOT/README.md` passou a documentar Shift+P (bloco 383)

Fix pontual, sem pendência — Shift+P (troca de lado que o bot controla)
já existia no código (`BotDriver.cs`) mas só aparecia no GUI label
in-game, não no README. Documentado ao lado do Shift+B.

## 🟢 IMPLEMENTADO: Turn Planner offline e busca ao vivo unificados numa função só (26/07/2026, bloco 382)

Usuário temia "o bot receber dois comandos de decisão diferentes... tem
que ser o mesmo nos dois" entre `main_phase` (offline) e
`sim_bridge.choose_action` (ao vivo). Investigação confirmou: o laço
externo ("dado candidatas pontuadas, amostra e escolhe a melhor") estava
duplicado com comportamento DIFERENTE — offline tinha janela de score,
diversidade em `REMOVE_THREAT` e a guarda `_is_unsafe_zero_life_leader_attack`;
ao vivo não tinha nenhuma das duas.

- [x] Unificado em 2 métodos novos de `OPTCGMatch` (`decision_engine.py`):
  `_select_search_candidates` e `_select_action_via_search` — FONTE
  ÚNICA chamada pelos dois caminhos agora. `sim_bridge._adaptive_counterfactual_search`
  (bloco 381) foi apagada; virou `_select_action_via_search` com
  `samples_min==samples_max` pro offline (N fixo, byte-idêntico ao
  comportamento antigo) e piso=12/teto=24 de verdade pro caminho ao vivo.
- [x] Validado: `smoke_fast.py`/`smoke_test.py` 100% + 4 partidas reais de
  self-play (`OPTCGMatch.simulate()`, decks de `decklists_raw.csv`) até o
  fim sem exceção, 3-8s/partida — sem regressão de tempo no offline.
- [ ] **PENDENTE**: nenhum smoke suite roda `simulate()`/self-play real
  de ponta a ponta hoje — só mecânica isolada. Validação desta unificação
  foi só via script descartável (não commitado). Vale adicionar 1 teste
  leve de regressão (1-2 partidas reais rápidas até o fim) pra pegar
  erros que só aparecem num jogo completo.
- [x] **FEITO no bloco 480 (10/08)**: amostragem adaptativa ligada no
  offline (piso=3/teto=6, `OFFLINE_MC_SAMPLES_MIN/MAX/BATCH`), custo
  medido primeiro (+7,2% de tempo total, 30 partidas reais N fixo vs
  adaptativo) antes de commitar, como esta pendência já pedia.
- [ ] **PENDENTE (pedido do usuário, 26/07)**: até agora só validei que a
  unificação NÃO regride (testes + self-play sintético) e que o caminho
  ao vivo ganhou a guarda `_is_unsafe_zero_life_leader_attack` + a
  janela/diversidade de candidatas — não medi se isso muda a EFICÁCIA de
  verdade em partida real. Validação real exige: (a) uma partida ao vivo
  (ou lote de partidas) depois desta mudança, (b) ler
  `metrics/live_runs/live_<timestamp>.json` + `decision_summary.py
  --latest` (telemetria obrigatória de decisão, ver regra no
  CLAUDE.md/AGENTS.md) e (c) rodar `bot_efficiency_report.py` com um
  cohort atualizado, comparando com o histórico anterior a este bloco.
  Ficar de olho especificamente em quantas vezes
  `_is_unsafe_zero_life_leader_attack` filtra uma candidata no
  `trace_out` (hoje não é um campo próprio da telemetria — se o sinal
  não aparecer implícito o suficiente em `search_values`, considerar
  adicionar um campo dedicado antes da próxima partida real).

## 🟢 IMPLEMENTADO: amostragem sequencial/adaptativa (piso 12/teto 24) substitui N fixo=6 (26/07/2026, bloco 381)

Usuário pediu pra implementar uma melhoria de verdade em cima do achado
do bloco 380 (abaixo). `SEARCH_SAMPLES_DEFAULT` fixo foi substituído por
amostragem sequencial em lotes: para no PISO (`SEARCH_SAMPLES_MIN_DEFAULT=12`)
assim que a diferença de valor entre as 2 candidatas é estatisticamente
clara (teste pareado com CRN), só sobe pro TETO
(`SEARCH_SAMPLES_MAX_DEFAULT=24`) quando o gap ainda não é confiável —
gasta menos orçamento em decisões óbvias, mais em empates genuínos.
(Nota pós-bloco 382: a implementação foi movida de `sim_bridge._adaptive_counterfactual_search`
pra `OPTCGMatch._select_action_via_search` em `decision_engine.py`,
unificada com o Turn Planner offline — ver seção acima.)

- [x] Implementado e testado (2 testes novos em `smoke_fast.py`, suítes
  100%). Validado com piso=12 após descobrir que piso=4/8 sofria de
  "confirmação por ruído" (poucos graus de liberdade tornam o teste
  pareado não-confiável) — ver bloco 381 do HANDOFF pro detalhe.
- [x] Tempo real validado: cenário de empate técnico (bloco 380) ~193ms
  médio/490ms máximo com a nova calibração — longe do timeout de 3-4s.
  Pior caso estimado pra board pesado: teto=24 ~1.22s, ainda seguro.
- [ ] **NÃO ESQUECER**: `SEARCH_TOP_K_DEFAULT=2` — o teste pareado só
  cobre exatamente 2 candidatas. Se algum dia SEARCH_TOP_K subir (>2
  candidatas na busca), o caminho adaptativo cai num modo sem
  early-stop (usa só o piso, sem parar antes) — documentado na função,
  mas nunca testado de verdade porque hoje sempre são só 2.
- [ ] Validar em partida real (telemetria `adaptive_samples_used`) se a
  distribuição piso/teto observada ao vivo bate com o que foi medido
  offline (~30-50% no piso no cenário de empate técnico testado).

## 🟢 QUALIDADE (não só estabilidade) do Monte Carlo vs N — sinal real existe, mas é pequeno demais pra mudar o default (26/07/2026, bloco 380)

Usuário questionou o achado do bloco 379: "estabilidade caindo é ruim?"
levou a "tem que ver se com mais amostras as escolhas foram melhores e
não as mesmas decisões" — ou seja, medir QUALIDADE contra um gabarito,
não só auto-consistência (repetir a mesma ação). Método: N=300 (média de
15 repetições) como gabarito de alto sinal do valor esperado de cada
candidato no cenário de "empate técnico"; depois, pra cada N pequeno (2 a
40), 30 repetições medindo accuracy (bateu com o melhor do gabarito?) e
regret (quanto perdeu vs o melhor do gabarito).

**Gabarito revelou que NÃO é um empate perfeito** — `play` (546.62) é
realmente um pouco melhor que `attack` (544.65), diferença de ~1.95
pontos (~0.36% relativo). Accuracy sobe com N (3.3% em N=2/4 → 20% em
N=6 → oscila → 40% em N=30 → 50% em N=40) e regret médio cai pela
metade (1.90 em N=2/4 → 0.98 em N=40) — ou seja, **mais amostras SIM
melhora a qualidade da escolha nesse cenário**, contradizendo a leitura
anterior (bloco 379) de "empate de verdade, nenhum N resolve". A leitura
anterior estava certa só na superfície (estabilidade não converge pra
100% em nenhum N testado) mas errada na causa: não é um empate exato,
é uma vantagem real só que pequena demais pro nível de ruído por
amostra — mesmo em N=40 (teto de tempo real) ainda erra a escolha
metade das vezes.

- [x] Confirmado que existe sinal de qualidade real (não é ruído puro) —
  accuracy/regret melhoram com N, mesmo que devagar.
- [x] **RESOLVIDO pelo bloco 381**: em vez de reavaliar um N fixo maior
  caso a caso, implementada amostragem sequencial/adaptativa que já
  gasta mais orçamento automaticamente quando o gap é pequeno — ver
  seção "IMPLEMENTADO" acima.
- [ ] Script do sweep de qualidade era descartável (não commitado, igual
  ao do bloco 379) — se precisar reproduzir, reescrever usando
  `trace_out["search_values"]` (valor por candidato) em vez de só
  `trace_out["chosen_action"]`, comparando contra um gabarito de N alto.

## 🟢 SWEEP DE SEARCH_SAMPLES — mantido em 6, teto real e limite de amostragem encontrados (26/07/2026, bloco 379)

`SEARCH_TOP_K`/`SEARCH_SAMPLES`/`SEARCH_MAX_STEPS` promovidos de
variável local pra constante de módulo (`*_DEFAULT` em `sim_bridge.py`)
— permite sweep/calibração futura sem editar a função.

Sweep real (320 chamadas, 2 cenários x 8 valores de amostra): board
pesado (5v5) escala quase linear, N=40 estourou 3s no pior caso (teto
real de tempo). Cenário de "empate técnico" mostrou que **mais
amostras não estabiliza sempre** — quando duas ações têm valor esperado
genuinamente próximo, nenhum N razoável resolve a instabilidade (não é
ruído de amostragem, é empate de verdade).

- [x] Mantido `SEARCH_SAMPLES_DEFAULT=6` — melhor ponto encontrado
  (100% estável no cenário pesado, folga grande de tempo).
- [ ] Se aparecer decisão inconsistente ao vivo numa situação de score
  muito próximo, não assumir que é bug — pode ser um empate real em
  valor esperado (ver achado acima), checar `search_values`/
  `opponent_model_source` na telemetria antes de investigar mais.

## 🟢 MONTE CARLO AO VIVO REALMENTE LIGADO — fallback lider→cor→genérico (26/07/2026, bloco 378)

Achado: `sim_bridge.choose_action` (produção, via `/decide`) nunca ligava
Monte Carlo de verdade — `hidden_information_masked=True` (sempre ao
vivo) forçava `model=None` antes de tentar qualquer coisa.
`opponent_model_for_leader` agora tem 3 camadas de fallback (deck real do
MESMO líder → deck real da MESMA cor → pool genérico por cor, regra dura
de construção de deck) que nunca exige saber a decklist exata do
oponente. `SEARCH_SAMPLES` (2→6) também subiu, já que agora realmente
importa (antes não tinha efeito nenhum no caminho mascarado).

- [x] Implementado e validado (profiling real: ~220-315ms de line_search
  no pior caso testado, board 5v5, contra timeout de 3-4s — folga
  grande). 2 testes novos em `smoke_fast.py`, suítes 100%.
- [ ] **REFINAMENTO FUTURO, NÃO ESQUECER (pedido explícito do usuário)**:
  a camada 3 (pool genérico por cor) é uniforme — toda carta daquela cor
  pesa igual, sem favorecer staples de torneio reais sobre cartas nunca
  jogadas. Precisa de alguma proxy de popularidade pra pesar isso melhor.
- [ ] Banco `decklists_raw.csv` ainda escasso pras camadas 1/2 (193 decks,
  só 19 líderes/12 combinações de cor únicas) — enriquecer com mais
  decks scrapeados melhoraria a precisão das camadas 1/2 sem depender só
  da camada 3 genérica.
- [ ] Ainda não testado ao vivo — próxima partida real deve conferir
  `opponent_model_source` na telemetria (`decision`/`scored_actions` do
  `/decide`) pra ver qual camada está sendo usada na prática contra
  oponentes reais.

## 🟢 VARREDURA RETROATIVA bot_optcgsim.py/server.py — RESULTADO LIMPO (25/07/2026, bloco 375)

Pendência do bloco 373 fechada. Leitura manual + scan mecânico dos dois
arquivos inteiros: **nenhuma duplicação de decisão encontrada** — toda
decisão real já delega pro motor único (`bridge.*`/`DecisionEngine.*`)
em ambos. `bot_optcgsim.py` é um bot standalone separado do par
C#/`server.py` (chama `sim_bridge` direto, sem HTTP), mas segue a mesma
regra; sua única particularidade é nunca jogar defesa ativa (sempre
"Pass" no turno do oponente) — limitação de escopo, não heurística
duplicada.

- [x] Investigado, sem achado de bug.
- [x] `bot_optcgsim.py` adicionado ao `BRIDGE_FILES`/`ENGINE_TOUCHPOINTS`
  do hook `pre-commit` (nunca esteve coberto pelo gate mecânico antes) —
  fortalece a rede de segurança pra mudanças futuras nesse arquivo.

## 🟢 NÃO-DETERMINISMO NO MOTOR — RESOLVIDO (26/07/2026, bloco 377)

Causa raiz encontrada e corrigida: `OpponentModel.sample()` e seus 2
call sites reais (`decision_engine.py` main_phase, `sim_bridge.py`
`choose_action`) usavam `rng=random.Random()` — instância NOVA, semeada
do relógio/SO, que ignora `random.seed()`. Amostragem Monte Carlo do
Turn Planner roda a cada decisão (não 1x por partida), então qualquer
self-play virava não-reprodutível mesmo com seed fixo. Fix: os 2 call
sites + o default interno passaram a usar o **módulo** `random` (o
gerador global que `random.seed()` de fato controla), não uma instância
nova — mesmo padrão já usado em todo o resto do motor.

- [x] Validado: `audit_replay.py --n 8 --seed 7` rodado 2x seguidas
  (processos separados) → output byte-a-byte idêntico (antes divergia).
  2 testes novos em `smoke_fast.py`. `smoke_fast.py`+`smoke_test.py` 100%.
- [x] Efeito colateral esperado (não bug): o pareamento de decks pra uma
  dada seed mudou em relação a antes do fix (Monte Carlo agora consome
  o stream global) — qualquer baseline/resultado registrado ANTES deste
  commit não é mais comparável direto, precisa ser re-gerado.

## 🟢 BUG DE CONSERVAÇÃO DE DON — CAUSA RAIZ ENCONTRADA E CORRIGIDA (03/08/2026, bloco 425)

Pendente desde 25/07/2026 (bloco 374), reproduzido estável no 377,
auditoria estática esgotada no 410, escopo ampliado (Red/Blue Ace
também) nos blocos 420/422/423 — nenhuma sessão anterior tinha rodado a
instrumentação direta que o próprio bloco 374 já recomendava. Esta
sessão rodou.

- [x] **Causa raiz real**: `OpponentModel.sample()` (`opponent_model.py`)
  nunca fazia `deepcopy` das cartas da amostra fictícia do oponente,
  apesar da própria docstring prometer isso ("objetos distintos... não
  compartilhadas entre chamadas") — retornava referências RASAS pro
  `full_decklist`, que compartilha os MESMOS objetos Card do deck REAL do
  oponente. Qualquer mutação numa simulação de turno de resposta completo
  (`_play_turn_greedy`, usado por `USE_OPPONENT_RESPONSE_SEARCH`) vazava
  permanentemente pro deck real — só virava "DON!! fantasma" visível
  turnos depois, quando a MESMA carta física fosse comprada/jogada de
  verdade. Fix: `sample()` agora faz `deepcopy` de cada carta retornada.
- [x] **Achado colateral real (mas insuficiente sozinho)**: `_SimDeck`
  (clona o deck sem deepcopiar tudo, usado por `_simulate_sequence_once`)
  só protegia remoção via `.pop()` — 5 pontos (`add_to_hand`-busca,
  `trash_from_looked_deck`, `search_deck`, `play_from_deck`, escolha de
  Stage inicial) removiam via `remove_by_identity`/`del`, bypassando essa
  proteção. Corrigido com `pop_by_identity` (nova função), mas sozinho
  NÃO resolveu o caso observado (Empty Throne joga do hand, não do
  deck) — mantido por ser o mesmo padrão de risco, defesa em profundidade.
- [x] **Causa raiz #3, a mais impactante das 3**: mesmo com os 2 fixes
  acima, `audit_replay.py --n 20 --seed 23` ainda dava 10 anomalias.
  `_simulate_sequence_once` fazia `opp2.deck = list(_opp_deck)` (cópia
  RASA, comentário dizia "opp não age durante a simulação" — falso
  sempre que `USE_OPPONENT_RESPONSE_SEARCH=True`, o default: `_play_
  turn_greedy(opp2, p2)` roda o turno de resposta INTEIRO do oponente,
  incluindo `draw_phase` que faz `opp2.deck.pop()` sem proteção nenhuma
  numa lista comum, vazando o objeto real do deck do oponente). Fix:
  `opp2.deck = _SimDeck(_opp_deck)`, mesmo wrapper já usado em `p2.deck`.
- [x] **Validado (com os 3 fixes juntos)**: `audit_replay.py --n 20
  --seed 11` (mesma seed estável desde o bloco 377/422): **23 → 0
  anomalias**. `audit_replay.py --n 20 --seed 23` (a seed que expôs a
  causa #3): **10 → 0 anomalias**. 0 exceções nas duas, 40 partidas
  reais no total. `smoke_fast.py`/`smoke_test.py` 100% (teste novo
  isolando `_SimDeck` real).
- [x] **Por que a auditoria estática nunca achou**: a mutação em si
  (`attach_don`, `play_card`, `draw_phase`, etc.) está correta — o bug é
  o objeto manipulado ser compartilhado com o estado real, não a lógica
  de mutação. Só apareceu rastreando `id()` de cartas específicas turno
  a turno via instrumentação direta, e precisou de 2 seeds diferentes
  pra expor as 3 causas (a 1ª seed só bateu na causa #2).

## 🟢 REGRA "SEM FUNÇÃO DUPLICADA" registrada + 2 duplicatas reais corrigidas (25/07/2026, bloco 373)

Usuário pediu para caçar OUTRAS "duas funções fazendo a mesma coisa" além
da orquestração de turno (bloco 372), corrigir, e registrar como
obrigatoriedade do projeto com leitura obrigatória antes de commit/push.

Achadas e corrigidas 2 duplicatas reais (caminho ao vivo com heurística
mais pobre que o motor interno já tinha):
- `DecisionEngine.choose_to_trash` (só ao vivo) → agora delega pra
  `EffectExecutor._choose_to_trash`/`_trash_value` (protege evento
  `[Counter]`, carta cara/win-con, reanimável — antes não protegia nada
  disso no bot ao vivo).
- `sim_bridge._choose_opp_target_filtered` reimplementava o filtro que
  `eligible_cards()` (rules_facade) já centraliza — agora delega. Mais
  2 pontos de `min/max(..., key=board_value)` na mão trocados por
  `choose_lowest_board_value`/`choose_highest_board_value`.

- [x] Ambas corrigidas, 2 testes novos em `smoke_fast.py` provando
  divergência real de comportamento (não só "roda sem erro").
  `smoke_fast.py` + `smoke_test.py` 100%.
- [x] Regra registrada em
  [`scriptis_da_ia/REGRA_SEM_DUPLICACAO.md`](scriptis_da_ia/REGRA_SEM_DUPLICACAO.md)
  — leitura obrigatória, impressa por inteiro pelo hook `pre-commit`
  (mesmo tratamento do `MEMORY.md`) e referenciada em `CLAUDE.md`.
- [x] `bot_optcgsim.py` e `BOT/engine_server/server.py` — varredura
  retroativa feita, **resultado limpo** (ver bloco 375 acima).

## 🟢 ReplayMatch.play_turn() DUPLICADO APAGADO — delega 100% pra OPTCGMatch.play_turn() (25/07/2026, bloco 372)

Resolve o achado lateral do bloco 371 (linha abaixo). Usuário perguntou
"Não dá para apagar não? E usar só 1?" — investigado e era pior do que
só o `global_turn` travado: `ReplayMatch.play_turn()` nunca chamava
`end_phase()` (efeitos `[End of Your Turn]` nunca resolviam no replay),
nem sincronizava `is_active_turn`/`pending_play_cost_reductions`, nem
checava `deck_out_win_instead_of_loss` (líder Nami OP03-040).

Fix: `OPTCGMatch.play_turn()` ganhou parâmetro opcional
`post_don_hook(p, opp)` (default `None`, zero mudança pro caminho ao
vivo/`simulate()`), chamado entre `don_phase()` e `main_phase()` —
único ponto que o replay precisava pra imprimir campo/perfil/postura no
meio do turno. `ReplayMatch.play_turn()` virou wrapper fino: imprime
cabeçalho, define o hook, chama `OPTCGMatch.play_turn()` uma vez só,
sincroniza `self.global_turn`. `_check_invariants()` agora usa o
`global_turn` do motor corretamente (o travamento em 0 sumiu de graça).

- [x] `smoke_fast.py` + `smoke_test.py` 100% verdes, zero regressão.
- [x] Validado com partida real via `ReplayMatch(...).run()` +
  `audit_replay.py --n 6`: output visual idêntico, `global_turn`
  batendo entre `ReplayMatch` e `OPTCGMatch` interno, mesma anomalia
  conhecida (DON Ace/Imu) detectada sem alteração.

## 🟢 AUDITORIA DE INVARIANTE UNIFICADA — audit_replay.py migrado pro decision_log (25/07/2026, bloco 371)

Pedido do usuário: "apenas 1 motor, apenas um engine de decisão e apenas
uma telemetria". Confirmado 1 motor (`_generate_and_score_actions`
chamado por ao vivo E self-play). Telemetria: unificadas as 2 partes
self-play-only (`_log_decision` + checagens do `audit_replay.py`) numa
lista só (`decision_log`, `kind='invariant_violation'`) — `write_event`/
`telemetry.py`/`server.py` (ao vivo) **não foram tocados**, de propósito.

`OPTCGMatch._check_invariants()` roda automaticamente (com
`enable_decision_audit()` ligado) via `ReplayMatch.play_turn()` E
`OPTCGMatch.play_turn()` — cobre `audit_replay.py`, `baseline_metrics.py`,
`tune_weights.py`, `audit_card_effects.py`, `audit_decision_quality.py`
sem exceção. `audit_replay.py` ficou fino (só lê `decision_log`).
Validado: 6 checks novos em `smoke_fast.py`, `smoke_test.py` 100%, os 5
scripts rodados de verdade sem exceção.

- [x] Migração concluída e testada.
- [x] Achado lateral (não é bug desta migração): `ReplayMatch` reimplementava
  a própria orquestração de turno em vez de chamar `OPTCGMatch.play_turn()`
  — **resolvido no bloco 372** (ver acima), apagado de vez.

## 🟢 SIMULADOR SELF X SELF (front-end) — RESOLVIDO: `OPTCGMatch(hide_opponent_info=True)`, ligado por padrão no `/simulate` (25/07/2026, bloco 370; fechado 10/08/2026, bloco 490)

Objetivo do projeto: front-end vai ter um simulador deck-vs-deck (self x
self) que precisa se aproximar do ao vivo — os dois lados não podem
"ver" a mão/deck real um do outro, igual o bot ao vivo já não vê (blocos
300/301).

**Feito (bloco 370):** os 2 únicos vazamentos reais de informação
encontrados em `decision_engine.py` (`opp_counter_potential` — counter
da mão; `_opp_can_remove_stage` — texto do deck) agora respeitam um
atributo novo `opp.self_play_info_hidden` (default ausente/False = 100%
comportamento de hoje, usado por bot ao vivo e toda ferramenta de
self-play existente). Quando `True`, usam só o que foi **revelado de
verdade** (`known_hand_cards`/`known_deck_cards`) + estimativa
estatística pro resto (mesma infra do `counter_estimation.py`).

- [x] **Construir o simulador self x self em si** — resolvido bloco 490.
  `OPTCGMatch.__init__` ganhou `hide_opponent_info: bool = False`; quando
  True, liga `self_play_info_hidden` nos DOIS `GameState`.
  `simulation_worker.run_single_match()` (chamado pela API `POST
  /simulate`, o endpoint que `src/app/simulate/page.tsx` já usa — não
  precisou de script novo, o ponto de entrada JÁ existia) passou a usar
  `hide_opponent_info: bool = True` como default — o simulador do
  front-end agora esconde mão/deck real de cada lado por padrão, sem
  nenhuma mudança em `api.py`.
- [x] **Bug real achado ao ligar a flag de verdade**: `GameState.
  __deepcopy__` não propagava `self_play_info_hidden`/
  `hidden_information_masked` (atributos dinâmicos, não campos
  declarados) — o ÚNICO call site que deepcopia `GameState`
  (`_simulate_sequence_once`, Monte Carlo do Turn Planner, dezenas/
  centenas de clones por decisão) perdia a flag em TODO turno simulado
  dentro da busca, mesmo com `state_a`/`state_b` da partida real
  mantendo ela certa. Corrigido: `__deepcopy__` agora propaga os dois
  atributos quando presentes.
- [x] Decidido: `baseline_metrics.py`/`tune_weights.py`/`audit_replay.py`
  (via `ReplayMatch`) continuam full-info de propósito (mais
  determinístico pra calibração) — só o simulador NOVO do front-end usa
  a flag. Nenhum desses 3 scripts foi tocado.
- [x] Auditoria adicional feita (bloco 490, além dos 2 vazamentos já
  achados no bloco 370): varredura de todo acesso a `opp.hand`/
  `opp.deck` em `decision_engine.py`. Achado 1 caso a mais —
  `opp_counter_in_hand()` lê `opp.hand` sem gate nenhum — mas é **código
  morto** (nenhum call site no arquivo inteiro), sem impacto
  comportamental hoje; registrado aqui pra quem for usar essa função no
  futuro saber que precisa do mesmo gate. Todo o resto (`len(opp.hand)`,
  `opp.deck` vazio) é tamanho de mão/deck (informação pública mesmo num
  jogo real) ou execução legítima de efeito que revela/olha a mão/deck
  do oponente de propósito (parte da resolução da carta, não um
  "espiar" da IA).
- Teste novo em `smoke_fast.py`
  (`test_optcgmatch_hide_opponent_info_propaga_e_muda_comportamento_10_08`):
  prova a flag nos dois lados, a propagação via `__deepcopy__`, e uma
  divergência de comportamento real (`opp_counter_potential()` com uma
  carta de counter 2000 não revelada: 2000 com info cheia vs valor
  estatístico bem menor oculto). `smoke_fast`/`smoke_test` 100%,
  `audit_replay.py --n 30 --workers 4` (full-info, default preservado):
  0 exceções/anomalias. `simulation_worker.run_single_match()` rodado
  de verdade (5 partidas reais, hidden vs full) sem exceção.

> 25/07/2026 (bloco HANDOFF 368): **Turn Planner Fase D fechada** —
> cache por instância de `GameAnalyzer._lethal_search` (invalidado em
> `_apply_action`), turno late-game real caiu de 103.78s pra 2.583s
> (~40x). `smoke_fast`/`smoke_test` 100%. **Achado novo, NÃO
> relacionado ao Fase D**: `audit_replay.py` mostra um bug de
> conservação de DON pré-existente, isolado ao deck Red/Blue Aceby
> (leader Portgas.D.Ace) — offset consistente de +1 no somatório
> disponível+rested+campo a partir de certo turno em partidas longas
> (confirmado presente COM e SEM o fix do Fase D via `git stash`,
> mesmo padrão nos dois casos, então não é a causa). **Pendente
> investigar**: rodar `audit_replay.py --n 8 --seed 7`, dump completo
> em `%TEMP%/don_dump_match_N.txt`, focar em qual efeito do
> Ace/Marco/Newgate/Izo dá DON sem descontar de algum lugar. **Status
> do plano do Turn Planner: A ✅ B ✅ C ✅ D ✅ — plano completo.**
> Pendências que sobram: calibrar pesos do Fase B (adiado pelo
> usuário), bug de DON do deck Ace (novo, acima), nenhum teste ao vivo
> nem push desde o commit `7b61a26`.

> 24/07/2026 (bloco HANDOFF 367): Telemetria preparada pra medir as
> mudanças de hoje — `action_score_components` decompõe os novos
> bônus da fase 2/B (`uncovered_action_value`, `char_played_react_bonus`,
> `own_effect_removes_char_react_bonus`, `event_activated_react_bonus`,
> `on_opp_char_ko_ready`); `line_search` ganha
> `two_turn_lookahead_wins_found`; `/defense` fase "blocker" ganha
> `blocker_candidates` (char_value_score vs on_ko_value por candidato).
> **Achado e corrigido no processo**: `_on_ko_upside_value` (bloco 364)
> era uma reimplementação parcial mais fraca de `on_ko_value` já
> existente (usada por `select_counter_cards`) — removida a duplicata.
> `_char_played_react_bonus` (bloco 360) estava na classe errada
> (`OPTCGMatch` em vez de `DecisionEngine`) — só apareceu ao tentar
> usar na telemetria (`action_score_components` só tem acesso a
> `DecisionEngine`). `smoke_test.py` 100% após as correções. Nenhum
> teste ao vivo ainda — campos novos só aparecem na próxima partida
> real. **Próximo: Fase D (performance)**, conforme combinado com o
> usuário.

> 24/07/2026 (bloco HANDOFF 366): Fase C do Turn Planner investigada
> com partidas reais (não pulada) — ~550 decisões auditadas em 13
> partidas (Turn Planner geral via `decision_log` + `should_use_blocker`/
> `should_use_counter` via monkeypatch temporário, que o log padrão
> não cobre). **0 achados concretos de bug.** Um "suspeito" inicial de
> 18 casos era falso-positivo do próprio script de análise (esqueceu
> de checar `atk_power < def_power`, defesa já suficiente). Fecha como
> "investigada, sem achado" — scripts de auditoria não commitados
> (descartáveis, ficaram só em scratchpad), metodologia documentada no
> HANDOFF 366 pra repetir/estender depois. **Status do plano do Turn
> Planner**: A ✅, B ✅ (bem além do escopo original), C ✅
> investigada/fechada, D parcial (profiling feito, correção da
> lentidão offline pré-existente ainda pendente). Nenhum teste ao vivo
> nem push ainda.

> 24/07/2026 (bloco HANDOFF 365): Fase 2 terceira passada — primeira
> vez com valores NEGATIVOS em `_UNCOVERED_ACTION_VALUE`
> (`give_don_opp`, `trash_own_life`, `self_cant_play`,
> `self_cant_take_life`, `lock_self_character_refresh`,
> `trash_from_hand`-como-step), todos conferidos contra cartas reais
> antes de decidir a direção. `peek_life` ganhou +5 (info pura, antes
> pontuava 0). `hand_to_deck`/`shuffle_hand_into_deck` continuam fora
> — pareciam drawback mas cartas reais mostram que são filtro de mão,
> não custo puro. `smoke_test.py` 100%. **OS 4 ITENS PEDIDOS PELO
> USUÁRIO 24/07 ESTÃO COMPLETOS** (on_ko próprio, profiling,
> lookahead multi-turno ao vivo, fase 2 terceira passada). Restam
> ~65 ações de baixo volume/ambíguas sem direção clara (não
> revisitadas, baixa prioridade). Nenhum teste ao vivo nem push ainda.

> 24/07/2026 (bloco HANDOFF 364): `on_ko` do PRÓPRIO personagem agora
> conta como valor (não só risco) na decisão de bloquear. Novo
> `_on_ko_upside_value` reduz o custo efetivo de sacrificar um blocker
> em `should_use_blocker` quando o `[On K.O.]` dele compensa (draw,
> vida, busca, remoção). Testado com Marco PRB02-008 (blocker + K.O.
> draw 2) vs Perona EB03-045 (mesmo custo/poder, sem K.O.) — Marco é
> escolhido pro sacrifício. `smoke_test.py` 100%. **3 dos 4 itens
> pedidos hoje feitos** (on_ko próprio, profiling, lookahead
> multi-turno). **Falta**: fase 2 segunda passada (~77 ações de baixo
> volume/ambíguas, ver bloco HANDOFF 356 pra lista completa).

> 24/07/2026 (bloco HANDOFF 363): Profiling real feito — offline
> (`main_phase`) tem explosão O(board²) PRÉ-EXISTENTE (até 13.8s/turno
> late-game, confirmado sem nenhuma mudança de hoje); ao vivo
> (`choose_action`) tem folga enorme (0.1-0.24s de 4s). Usuário decidiu:
> lookahead de 2 turnos SÓ no caminho ao vivo
> (`extra_own_turn_search=True`, default `False` mantém offline
> intocado) — simula meu próprio próximo turno inteiro via
> `_play_turn_greedy` (mesmo mecanismo já usado pra resposta do
> oponente) depois da resposta dele. Validado a 0.2s no board real de
> profiling. `smoke_test.py` 100%. **Pendente do pedido do usuário
> (4 itens)**: falta 1) valor de `on_ko` próprio na decisão de
> bloquear/trocar, e 4) fase 2 segunda passada (~77 ações de baixo
> volume/ambíguas). Explosão O(board²) offline continua sem tratar —
> registrada, não é bloqueio pro que foi pedido hoje.

> 24/07/2026 (bloco HANDOFF 362): `audit_replay.py` consertado
> (`replay_optcg.py._get_engine_match()` faltava 2 atributos numa
> lista manual de inicializacao). Ao rodar de verdade contra 8
> partidas reais, achou uma **REGRESSAO REAL** introduzida hoje: a
> fase B (`_next_turn_readiness_bonus`) vazava DON permanentemente
> numa partida (Imu, +8 DON do nada). Confirmado via worktree isolado
> que NAO existia antes desta sessao. **Causa exata nao 100%
> identificada** (mutar+restaurar `don_available`/`.rested` deveria
> ser seguro em copias descartaveis, mas na pratica nao foi) — corrigido
> de forma estrutural trocando mutacao+restore por `deepcopy` dedicado
> em `_project_next_turn_best_action`, eliminando a classe de risco em
> vez de caçar a causa exata. `audit_replay.py --n 8 --seed 7`: 0
> excecoes, 0 anomalias (era 6). `smoke_test.py` 100%. **Pendente**:
> se aparecer bug parecido (recurso "sumindo/duplicando") no futuro,
> revisitar — pode ser algo mais profundo em `GameState.__deepcopy__`.

> 24/07/2026 (bloco HANDOFF 361): Turn Planner Fase B — cobertura
> COMPLETA de todos os 6 gatilhos de combo mapeados nas fases 1.1-1.4.
> Faltavam 3: `on_own_effect_removes_char` (bônus em `avaliar_carta`
> quando o board reage a um KO/bounce meu), `on_own/opp_event_activated`
> (bônus/penalidade ao jogar EVENT), e `on_hand_card_trashed` (sobe o
> limiar de "vale pagar" um custo opcional de `trash_from_hand` de 60
> pra 85 quando há payoff no board). 6 smoke tests novos com cartas
> reais. `smoke_test.py` 100%. **Fase B está completa** — todos os
> gatilhos de combo mapeados nesta sessão agora pesam na decisão.
> Nenhum teste ao vivo nem push ainda.

> 24/07/2026 (bloco HANDOFF 360): Turn Planner Fase B estendida —
> combos mapeados nas fases 1.1-1.4 (`on_own/opp_char_played`,
> `on_opp_char_ko`, `when_rested`) agora pesam na ORDEM de
> jogadas/ataques, não só disparam quando executados. Novo
> `_char_played_react_bonus` (jogar carta que ativa/sofre watcher em
> campo), `score_attack_target` considera `on_opp_char_ko` pronto
> (respeitando `don_requirement`), `_rest_attack_has_material_benefit`
> checa `when_rested` estruturado em vez de só substring frágil. 8
> smoke tests novos com cartas reais (Sanji, Sugar, Kaido, Issho).
> `smoke_test.py` 100%. Nenhum teste ao vivo nem push ainda.

> 24/07/2026 (bloco HANDOFF 359): Turn Planner Fase B REFEITA — usuário
> rejeitou a 1a versão (aritmética "barata"), pediu análise real dos
> dois lados. Novo `_project_next_turn_best_action(actor, other)`
> projeta DON refrescado/rampado + personagens desrestados e reusa
> `_generate_and_score_actions` DE VERDADE (mesmo motor calibrado, sem
> tabela nova) contra esse estado hipotético — determinístico, sem
> Monte Carlo, sem deepcopy (muta + restaura com try/finally).
> `_next_turn_readiness_bonus` usa isso dos dois lados: meu ganho vs
> ameaça de ataque do oponente no turno projetado dele. Custo ~2.5ms/
> call (~3x mais caro que a v1, ainda bem dentro do orçamento). 5 smoke
> tests novos (v1 tinha 3, todos reescritos). `smoke_test.py` 100%.
> Nenhum teste ao vivo nem push ainda.

> 24/07/2026 (bloco HANDOFF 358): Turn Planner Fase B feita —
> `_next_turn_readiness_bonus` generaliza o `wincon_ready` existente
> (que só cobria o eixo bottleneck/reanimação do perfil do deck) pra
> QUALQUER carta forte na mão perto de virar jogável (DON projetado
> pro próximo turno, sem simular o turno de verdade). Novo peso
> `next_turn_readiness` em `EVAL_WEIGHTS`. Custo medido ~0.8ms/call,
> irrelevante no orçamento atual (K/S pequenos, timeout de 4s ao vivo).
> `smoke_test.py` 100%. **Fase A + B completas.** Fase C (qualidade)
> vazia por ora — nada concreto achado que já não esteja coberto. Fase
> D (performance) só entra se necessário depois de calibrar ao vivo.
> Nenhum teste ao vivo nem push ainda.

> 24/07/2026 (bloco HANDOFF 357): Turn Planner — plano em 4 fases
> aprovado (A cobertura → B lookahead → C qualidade → D performance,
> ver `C:\Users\arthu\.claude\plans\lively-honking-sedgewick.md`).
> **Fase A feita**: 2 bugs reais de scoring achados fora de
> `avaliar_carta` — typo `'rest_opp'` (nunca bate, nome real é
> `'rest_opp_character'`) em `_trigger_don_value` subvalorizava
> `attach_don` pra remoção/controle; `_score_activate_main` tinha
> fallback fixo `base=60` pra qualquer action fora de 5 categorias,
> agora usa o mesmo piso genérico da fase 2
> (`_UNCOVERED_ACTION_VALUE`). `smoke_test.py` 100%. **Achado de
> tooling** (não-bug desta sessão, confirmado via `git stash` que já
> quebrava antes): `audit_replay.py` quebra com
> `AttributeError: 'OPTCGMatch' object has no attribute
> '_suppress_replay_log'` — `replay_optcg.py._get_engine_match()` cria
> o match sem esses atributos. Bloqueia validação por replay real até
> alguém investigar (fora do escopo do Turn Planner). **Próximo: Fase
> B** (lookahead barato pra combos/finalização, sem simular 2+ turnos
> completos — ver plano salvo).

> 24/07/2026 (bloco HANDOFF 356): Fase 2 segunda passada feita —
> `select_grant_*` (7 variantes), `opp_don_minus`, `ko_selected` e
> `opp_bounce_own_character` (removal). **Fase 2 encerrada por
> diminishing returns** — o que sobrou (deck_bottom_rest e outros
> steps de limpeza, custo/drawback próprio, ambíguos, cauda de
> count=1) precisa de mecanismo novo (sinal invertido) ou leitura
> carta-a-carta, não mais generalização direta. `smoke_test.py` 100%.
> **PRÓXIMO ITEM: Turn Planner** (usuário vai pra esse agora) — sem
> escopo definido ainda, próxima sessão precisa perguntar o que
> especificamente está errado/faltando antes de mexer. Ver bloco 356
> do HANDOFF pra lista completa de pendências.

> 24/07/2026 (bloco HANDOFF 355): Fase 2 (primeira passada) feita —
> `_uncovered_action_value()` pontua ~24 tipos de ação de alto
> volume/alta confiança que `avaliar_carta` ignorava por completo (ex:
> Ulti OP01-093 com `add_don` incondicional pontuava igual a uma
> vanilla). Escopo deliberadamente limitado: fora ficam steps de
> limpeza/companion (`deck_bottom_rest`, 159 ocorrências — sempre
> acompanha `look_top_deck`, contaria 2x) e custos/drawback do próprio
> jogador (precisam de sinal invertido, não bônus). Bônus lateral:
> `trash_character` (5 cartas) agora conta como `is_removal`, mesma
> mecânica de `ko`. `smoke_test.py` 100%. **Ordem combinada de 24/07
> (Fase 1 completa + Fase 2 primeira passada) está INTEIRA.** Pendente
> não-urgente: ~77 tipos de ação de baixo volume ficaram fora desta
> passada (registrados no HANDOFF 355) — segunda passada só se um combo
> real aparecer ignorado ao vivo. Próxima sessão: decidir com o usuário
> se testa ao vivo agora ou faz a segunda passada primeiro.

> 24/07/2026 (bloco HANDOFF 354): Fase 1.4 feita — gatilhos
> `on_own_effect_removes_char` (Crocodile EB02-023, Boa Hancock OP07-038,
> Shakuyaku OP08-046) e `on_hand_card_trashed` (Kuroobi OP14-045, Jinbe
> OP14-049, Wadatsumi OP14-056), 6 cartas. **1 bug pego e corrigido na
> própria validação** (`diff_parser.py`): duplicata de "gains [Rush]"
> em Kuroobi/Jinbe — corrigido de forma GENÉRICA com
> `_sem_steps_ja_dedicados()`, que filtra qualquer segmento solto que já
> pertence a um trigger parametrizado das fases 1.1–1.4, não só o par de
> cartas que revelou o bug. `smoke_test.py` 100%. **FASE 1 (bugs de
> regra) COMPLETA: ✅ 1.1, ✅ 1.2, ✅ 1.3, ✅ 1.4.** Falta só a ⬜ Fase 2
> (sistema unificado de pontuação de combos em `avaliar_carta`, hoje só
> 8 flags hardcoded pra ~114 tipos de ação já catalogados). Usuário
> pediu pra seguir sem parar — próxima sessão pode ir direto pra Fase 2.

> 24/07/2026 (bloco HANDOFF 353): Fase 1.3 feita — gatilho
> `on_own_char_played`/`on_opp_char_played` (5 cartas: Sugar, Sanji,
> Bonney, Boa Hancock, Koala), com filtro estruturado sobre qual
> personagem conta (sem efeito base / com Trigger / custo≥N) checado
> contra a carta REAL jogada. **2 bugs pegos e corrigidos na própria
> validação** (`diff_parser.py` antes de fechar): vazamento de captura
> em Boa Hancock (delimitador não parava em `[DON!!x1]` sem espaço) e
> duplicata em Koala (helper de recuperação de texto solto não
> comparava contra todas as entradas já existentes). `smoke_test.py`
> 100%. **Status das 4 etapas**: ✅ 1.1, ✅ 1.2, ✅ 1.3. Falta ⬜ 1.4
> (removido/descartado por efeito, ~3 cartas) e ⬜ Fase 2 (combos de
> pontuação). Usuário pediu pra seguir todas sem parar, só perguntar se
> houver dúvida real — nenhuma apareceu até agora.

> 24/07/2026 (bloco HANDOFF 352): Fase 1.1 feita — gatilho
> `on_own_event_activated`/`on_opp_event_activated` (9 cartas: Usopp,
> Gion, Franky, Camie, Luffy `OP15-119`, Crocodile `OP01-062`, Page One,
> Zeff, Sugar). **Regressão real pega e corrigida durante a própria
> validação** (`diff_parser.py` antes de fechar): Luffy `OP15-119`
> perderia o `[Rush]` condicional a 6+ DON por um efeito colateral do
> fix — corrigido com helper que preserva texto solto sem tag como
> `passive` separado. `smoke_test.py` 100%. **Status das 4 etapas**: ✅
> 1.1, ✅ 1.2. Faltam ⬜ 1.3 (personagem jogado, ~4 cartas), ⬜ 1.4
> (removido/descartado por efeito, ~3 cartas), ⬜ Fase 2 (combos de
> pontuação). **Não testar ao vivo/dar push** até essas avançarem mais
> (pedido do usuário).

> 24/07/2026 (bloco HANDOFF 351): mapeamento de combos amplo achou
> padrão sistêmico de bug de regra — gatilhos que observam uma ação do
> oponente/própria (não só pontuação) somem no parser, viram efeito
> incondicional. **20 cartas confirmadas, incluindo o líder Kaido
> `OP01-061`**. Ordem de correção combinada com o usuário (sempre por
> padrão genérico, nunca carta por carta):
> - ✅ **Fase 1.2 feita**: gatilho `on_opp_char_ko` (personagem do
>   oponente K.O.'d) — Kaido, Rob Lucci. Novo evento parametrizado no
>   parser + `_dispatch_opp_char_ko()` nos 8 pontos reais de K.O. do
>   motor. `diff_parser.py` PERDEU=0, `smoke_test.py` 100%.
> - ⬜ **Fase 1.1**: ativação de Evento/Blocker (~8 cartas: Usopp,
>   Franky, Gion, Camie, Luffy OP15-119, Crocodile OP01-062, Page One,
>   Zeff) — maior volume de uma família só.
> - ⬜ **Fase 1.3**: personagem jogado (~4 cartas: Sugar, Sanji, Bonney,
>   Boa Hancock OP14-041).
> - ⬜ **Fase 1.4**: removido/descartado por efeito (~3 cartas:
>   Crocodile EB02-023, Boa Hancock OP07-038, Kuroobi).
> - ⬜ **Fase 2**: combos de pontuação (~700+ ocorrências: DON ~130,
>   vida ~131, mão ~85, trash ~50, custo ~36, poder/líder ~26, tribo
>   ~28, cor ~22, `play_card` ~117) — trocar as 8 flags fixas do
>   `avaliar_carta` por tabela genérica de valor por ação, não 14 fixes
>   separados.
> **Usuário pediu pra não testar ao vivo/dar push até essas etapas
> avançarem mais** — não fazer push sozinho sem confirmar.

> 24/07/2026 (bloco HANDOFF 350): mais um ajuste na reserva de DON —
> vida baixa (≤2/3) reservava DON mesmo com `threat` (ameaça calculada)
> em 0.0 (oponente sem chance real nenhuma). Achado em 42% dos casos com
> reserva>0 nas sessões de 23/07. Fix: tiers de vida baixa agora exigem
> `threat > 0` também. `smoke_test.py` 100%. **Status das 4 etapas**: 1
> (combos) e 4 (reserva DON) feitas; **faltam 2 (Turn Planner) e 3
> (`_don_livre_for_plan`)** antes de testar ao vivo/push de novo.

> 24/07/2026 (bloco HANDOFF 349): etapa 4/4 do pedido do usuário —
> `_don_reserve_for_defense` reservava DON por tiers de ameaça/vida (até
> 3-4) sem teto ligado ao custo REAL do recurso reativo disponível.
> Usuário: "às vezes tem 1 evento custo 1 na mão e guarda 4 dons". Fix:
> nova `_max_don_needed_for_reactive_use()` calcula o maior custo de DON
> entre os recursos reativos reais (evento `[Counter]` com DON próprio,
> `don_requirement` de personagem/líder) — reserva nunca passa disso
> (0 se só existe counter impresso, que não custa DON pra usar). Testado,
> `smoke_test.py` 100%. **Status das 4 etapas pedidas antes de
> testar/push**: 1 (combos) e 4 (reserva DON) feitas; **faltam 2 (Turn
> Planner) e 3 (`_don_livre_for_plan`)**.

> 24/07/2026 (bloco HANDOFF 348): usuário pediu 4 melhorias antes de
> testar/dar push de novo — **1/4 feita** (mapeamento de combos: 114 das
> 136 ações do banco sem reconhecimento na pontuação; corrigidas as 3 de
> maior volume que eram controle/remoção disfarçada —
> `place_opp_character_bottom_deck`/`lock_opp_character_refresh`/
> `lock_opp_character_attack`, 76 cartas viraram `is_removal=true`).
> **Faltam**: 2) melhorar o Turn Planner, 3) melhorar
> `_don_livre_for_plan`, 4) melhorar `_don_reserve_for_defense` (guarda
> DON demais sem necessidade, segundo o usuário). `smoke_test.py` 100%
> depois da etapa 1. **NÃO fazer push ainda** — usuário quer as 4 etapas
> prontas antes de testar ao vivo de novo.

> 24/07/2026 (bloco HANDOFF 347): causa raiz real do "só joga carta de
> custo <=4" + "distribui DON em carta fraca pra empatar poder" —
> `_can_play_card` excluía TOTALMENTE (não só pontuava baixo) qualquer
> carta com efeito condicional que não pode disparar agora e poder <5000
> fixo, mesmo carta on-curve (ST18-001, 3000/custo3/counter2000, sumia
> com DON!!8 não batendo). Sem `play` na lista, DON ia pra empatar poder
> em ataque em vez de jogar a carta. 86 cartas do banco com esse padrão.
> Fix: troca o gate por `avaliar_carta(card) >= 40` (mesmo cálculo
> completo do motor, não só poder/custo — usuário pediu isso
> especificamente, carta 0 poder pode valer muito por counter). Testado,
> `smoke_test.py` 100%. **Pendente**: validar ao vivo; usuário pediu pra
> melhorar `avaliar_carta` mais amplamente e a função de planejamento de
> turno/turnos seguintes — escopo ainda não definido.

> 24/07/2026 (bloco HANDOFF 346): `avaliar_carta` nunca dava bônus pro
> passivo `when_don_returned` (add_don quando um DON!! volta pro deck) —
> carta com esse passivo pontuava igual a um vanilla puro. Achado real com
> Charlotte Katakuri ST34-001 (usuário: "bot ignora combo"). Auditoria
> global achou **19 cartas** do banco com esse passivo, não só a que
> revelou o gap. Fix genérico (+35 se a condição do bloco valer agora),
> testado nas 19 sem erro. Teste novo em `smoke_fast.py`, `smoke_test.py`
> 100%. **Pendente**: validar ao vivo se muda a frequência de jogo dessas
> cartas; a queixa mais ampla "só joga carta de custo <=4" ainda não tem
> causa raiz isolada além desta — próxima sessão deve reavaliar depois de
> mais partidas com este fix.

> 24/07/2026 (bloco HANDOFF 345): achado real e fix aplicado — o bot
> praticamente nunca counterizava com carta enquanto tinha vida 4-5
> (`should_use_counter` tinha `valor_vida=12` nessa faixa, MENOR que o
> custo real de qualquer carta útil, ~70-75). Explicava 3 queixas do
> usuário de uma vez: usar a habilidade do líder pra defender em vez de
> counter (fallback mais barato), esvaziar DON com isso, e Pekoms
> (ST34-005) atacar sem efeito (sem DON sobrando pro próprio custo). Fix
> conservador: cobre só golpe normal resolvido com 1 carta barata (~70-75
> de gasto), não golpe grande que precisa empilhar 2+ cartas (~100+).
> Teste novo em `smoke_fast.py`, `smoke_test.py` 100%. **Pendente**:
> validar ao vivo em mais partidas (win-rate deve subir, mas 1 partida não
> confirma); investigar a queixa ainda aberta do usuário — bot insiste em
> JOGAR Pekoms pro campo em vez de guardar como counter (mecanismo
> diferente, não instigado ainda — provavelmente em `avaliar_carta`/
> `_score_play_action`).

> 24/07/2026 (bloco HANDOFF 344): leitura COMPLETA de toda a telemetria
> local (22 `live_runs`, 22 arquivos de decisão, 1932 decisões) confirma e
> QUANTIFICA o gap de eficiência: nas 21 derrotas com dado completo, o bot
> sempre chega a vida 0 enquanto o oponente sobra com **vida média 3,48/5**
> — ou seja, o bot causa em média só **~1,5 de dano por partida inteira**.
> Padrão consistente 17/07-23/07, não é fase ruim isolada. **Alvo
> numérico claro pra próxima sessão de fix**: fechar esse gap
> vida-causada-vs-vida-perdida, provavelmente abrindo
> `decide_don_for_attack`/`_score_to_play`/objective='destroy' —
> causa raiz ainda NÃO investigada, só quantificada. Achados secundários
> (nenhum é a causa raiz sozinho): só 1 timeout severo (LETHAL com
> `scored_actions` vazio, já corrigido pra virar item registrado);
> 78 falhas de confirmação de execução mas concentradas em sessões
> 20-22/07, zero em 23/07 (parece já resolvido); `client_timeouts` em
> `/choose_target` seguem raros mas não investigados; alerta
> `bot_confusion` provavelmente superestima severidade (conta fim normal
> de Main Phase como confusão).

> 21/07/2026 (bloco HANDOFF 298): usuário propôs a hipótese correta —
> "o bot tem dificuldade com qualquer efeito de DON!! -N" — CONFIRMADA
> no código decompilado do jogo: pagar custo `don_minus` exige clicar
> DON na `DonCostArea`, zona que `CollectTargetCandidates` nunca
> coletava. Isso explica TODOS os "líder sem efeito" (Katakuri, Pudding
> PRB02-010, Mamaragan) — não era lista desatualizada (fix do bloco 296),
> era zona de candidato inexistente. Fix em C# (`own_don` como zona nova)
> + Python (prioridade máxima incondicional pra essa zona). Precisa
> `setup_bepinex.bat` + partida real pra confirmar.

> 21/07/2026 (bloco HANDOFF 297): usuário questionou se o fix da Linlin
> foi isolado demais — achado um gap SISTÊMICO real por trás:
> `is_removal`/`power_buff` nunca reconheciam `debuff_power`/
> `set_base_power` mirando o oponente (97 cartas com debuff_power no
> banco, nenhuma marcada como removal). Corrigido — 118 cartas ganharam
> `is_removal=True`. Score de jogar Linlin foi de 90→245 no total (alvo +
> flag). Essa é provavelmente a explicação real e ampla do "bot quase
> nunca joga carta boa e cara" — precisa de partida real pra confirmar o
> efeito prático (é fix de flag/dado, não de execução).

> 21/07/2026 (blocos HANDOFF 296/297): as 3 investigações pedidas pelo
> usuário fecharam com achados reais:
> 1. **Líder sem efeito (Pudding/Katakuri/Mamaragan)**: hipótese forte —
>    `CollectTargetCandidates` só roda 1x quando `iActionStep` muda; se a
>    carta revelada do topo do deck do oponente aparece 1+ frames DEPOIS,
>    o snapshot fica sem o alvo real pra sempre. Fix em `BotDriver.cs`:
>    busca a lista de novo 1x antes de desistir. Compilado OK, **precisa
>    rebuild/redeploy do plugin (`setup_bepinex.bat`) + partida real pra
>    confirmar** — não é fix Python, restart do server não basta.
> 2. **DON em personagem fraco**: não era sobre DON — Charlotte Linlin
>    (ST34-004) tinha o ALVO do próprio efeito parseado errado
>    (`own_character` em vez de `opp_character`), fazendo o motor achar
>    que ela sabotava o PRÓPRIO lado. Fix de parser isolado (1 carta),
>    score subiu 90→150. Registrado em `parser_audits/`.
> 3. **Mamaragan ordem de step**: fix aplicado (bloco 295), 5 cartas
>    corrigidas globalmente.

> 21/07/2026 (bloco HANDOFF 294): 4a partida ao vivo pos-fixes 289-293.
> Achado novo: bônus de "+300 alvo é ameaça crítica" em
> `_generate_and_score_actions` tinha o MESMO bug do fix 289 (aplicado
> sem checar se o ataque conecta) — corrigido. Progresso real no gatilho
> do Katakuri (custo agora é ACEITO, "USAR efeito" em vez de sempre
> "Cancel"), mas `peek_opp_deck_top` ainda trava no mesmo ciclo de
> cliques inválidos da Pudding — causa raiz ainda não resolvida, precisa
> debug C# ao vivo. **Pendente de aprovação**: Mamaragan tem ordem de
> step invertida no `card_effects_db.json` vs o texto oficial (draw
> deveria vir ANTES do rest_opp_character, não depois) — não implementado,
> precisa registro em `parser_audits/` e checagem global da mesma
> gramática antes de commitar (regra do CLAUDE.md). DON "desperdiçado"
> continua inconclusivo.

> 21/07/2026 (bloco HANDOFF 292): `resolve_reaction()` tinha o
> roteamento genérico, mas a conta de CUSTO do redirect era hardcoded em
> torno do padrão do Teach (sempre "líder + bloco on_opp_attack + custo =
> perder carta da mão"). Doflamingo (mesmo redirect, paga com 1 DON), Kid
> (redirect via 'passive', sem custo nenhum) e EB01-038 (via 'counter',
> DON opcional) não seriam avaliados certo. Fix: busca o bloco certo por
> `redirect_attack_target` real (qualquer trigger, não só on_opp_attack)
> e computa custo pelos custos DESSE bloco (trash_from_hand vs don_minus/
> rest_don vs sem custo). Teste isolado só, **sem validação em partida
> real ainda** (nenhum desses líderes apareceu nos logs até agora).

> 21/07/2026 (bloco HANDOFF 291): quando_attacking/on_opp_attack com
> custo opcional (ex: Katakuri OP11-062, `don_minus:1`) eram roteados por
> `BotDriver.cs` pra `resolve_reaction()` (regra pensada só pra REDIRECT
> de ataque, Teach-style) sempre que a oferta acontecia numa janela de
> combate — mesmo quando o bot era o ATACANTE usando o próprio gatilho, não
> alguém se defendendo. `if atk_power < def_power: recusa` (certo pra
> "devo me defender de um ataque que já perde sozinho") ficava invertido
> nesse caso, e o Katakuri recusava a própria habilidade 7 de 8 vezes numa
> partida real. Fix: `_worth_paying_optional_costs` (já usado por on_play/
> main/activate_main) passou a cobrir when_attacking/on_opp_attack também
> (simulador E caminho ao vivo); `resolve_reaction` só roda a lógica de
> redirect se a carta tiver `redirect_attack_target` de verdade, senão
> delega pro crivo genérico. Sem mudança em C#. **Pendente**: confirmar em
> partida real que a habilidade passa a disparar de fato; reconfirmar se o
> sintoma "distribui DON em vez de descer carta boa" ainda aparece (achado
> anterior sobre telemetria de DON foi CORRIGIDO — o campo `donToAttach` já
> existe em `response`, só não tinha sido olhado no lugar certo).
**Estado:** VARREDURA COMPLETA ENCERRADA em 19/07/2026; 100 suspeitos restantes, TODOS confirmados falso-positivo (revisão manual carta-a-carta)
**Baseline do código:** ver `git log --oneline -1`
**Repo:** github.com/Karlmalone13/Analizador_de_Decks

> 20/07/2026 (bloco HANDOFF 290): mesma sessão, partida seguinte —
> Mamaragan (OP15-078) e Divine Departure (OP13-076) confirmadas presas
> no MESMO bug: cartas EVENT dual-mode (`[Counter]` mira o PRÓPRIO lado,
> `[Main]` mira só o OPONENTE) tinham `order_target_candidates()`
> misturando os alvos dos dois blocos, então o próprio líder/board
> entravam como candidato "válido" pro `[Main]` — bot clicava neles
> primeiro, nunca chegava no alvo legal, carta ia pro trash sem efeito.
> Fix genérico: filtra os blocos pelo contexto (`attacker_power>0` =
> janela de combate/counter; senão só blocos não-combate) + infere o lado
> pelo NOME da ação quando não há `target` explícito (`rest_opp_character`
> etc.). **Achado aberto, não corrigido**: o `[When Attacking]` de
> Katakuri (custo do `vale_restar` do fix anterior) nunca dispara de
> verdade na execução — 0/4 ataques mostraram o custo/efeito no combat
> log. Mesma família de bug (habilidade com custo opcional que não
> completa), mas no caminho de ATAQUE, não de PLAY — precisa investigação
> em `BotDriver.cs`/estado do jogo. Também ainda não investigado: DON
> alocado em ataque vai embutido em `donToAttach` da própria ação
> `attack`, não como `attach_don` separado — a investigação anterior
> (bloco 289) sobre "DON acumulado na Pudding" pode ter procurado no
> lugar errado.

> 20/07/2026 (continuação, bloco HANDOFF 289): mais uma partida ao vivo
> revelou bug de scoring genérico em `score_attack_target` — ataque sem
> NENHUMA chance de conectar (poder + todo o DON disponível ainda menor
> que o alvo) pontuava alto (405) só porque o `[When Attacking]` do
> próprio atacante fazia `vale_restar=True`; os bônus de "vale matar o
> alvo" eram somados mesmo sem chance de matar. Fix aplicado e genérico
> (qualquer atacante com essa forma, não só o líder que revelou o bug) +
> teste novo em `smoke_fast.py`. **Pendente**: (1) Pudding (OP11-070)
> acumulou 7 DON parada num personagem de 0 power num turno — só 1 DON é
> explicado pela via legítima (`don_requirement:1`), os outros 6 têm
> origem desconhecida, possivelmente ligado ao travamento do
> `activate_main` dela (ainda sem handler funcional apesar do fix de
> `ConfirmRevealedCard` da sessão anterior — confirmado que esse estado
> nunca dispara pra essa carta). (2) `client_timeouts: 1` e
> `latency max: 169609ms` na sessão `decisions_2026-07-20T16.45.37.jsonl`
> — não investigados ainda.

> 20/07/2026: primeira sessão de teste ao vivo real dos fixes 285-287.
> Captura de log 100% validada (DownloadLogLines + coleta automática +
> winner). 2 achados reais em partida: (1) `ConfirmRevealedCard` sem
> handler no `BotDriver.cs` travava QUALQUER carta com efeito "olhar/
> revelar sem escolha" (achado com Charlotte Pudding OP11-070, 69% das
> decisões de Main falhando) — fix genérico aplicado e validado (16/16
> decisões confirmadas na partida seguinte). (2) Sets ST31-36 (lançados
> este mês) estavam 100% ausentes do `cards_rows.csv` — `server.py`
> filtra silenciosamente cartas de código desconhecido da mão, então o
> motor "não via" as cartas fortes do próprio deck. `optcgapi.com`/
> `apitcg.com` ainda não têm esses sets (confirmado ao vivo); as 30
> cartas exclusivas foram transcritas manualmente das imagens locais do
> jogo. Achado lateral: projeto Supabase estava PAUSADO (plano free,
> reativado durante a sessão — front-end de produção também estava fora
> do ar). Ver HANDOFF bloco 288.
>
> Pendências abertas: rodar `setup_bepinex.bat` antes da próxima partida
> (fix do `BotDriver.cs` ainda não reinstalado no jogo); confirmar que o
> padrão "peek sem handler" não se repete em outras cartas; LETHAL/
> PREVENT_COMBO ainda não exercitados ao vivo; `set_name`/atributo de
> ST34-002 são provisórios, revisar quando possível; sincronizar
> ST31-36 via `/api/sync-cards` quando `optcgapi.com`/`apitcg.com`
> atualizarem (evita depender da transcrição manual pra sempre).

> 19/07/2026: proxy ganhou sinais de "bot confuso"/timeout ao vivo
> (`[ALERTA]` no console + novo alerta agregado `bot_confusion` em
> `bot_efficiency_report.py`), telemetria de `priority`/`can_lethal` direto
> no `/decide` (correlaciona com o `outcome` real da partida — novo
> `lethal_certified_summary`), timeout de HTTP real do C# agora chega em
> telemetria (`/client_timeout`, antes não deixava rastro nenhum). Achado
> extra: o combat log só sai completo se `DownloadLogLines()` for chamado
> (normalmente só no clique do botão "Download Log") — bot nunca clicava,
> por isso o AutoSaved sempre cortava o fim. `BotDriver.cs` agora chama o
> método direto no GameOver; `collect_latest_match.py` aponta pra
> `CombatLogs` (pasta cheia) em vez de `CombatLogs/AutoSaved`. **Precisa
> validação em partida real.** Ver HANDOFF bloco 286.

> 19/07/2026: primeiro fix real de eficiência do motor (não do bot-executor):
> `can_lethal_this_turn()` certificava lethal alocando DON livremente, mas
> `_don_livre_for_plan` reservava DON pro "resto do plano" mesmo quando o
> lethal certificado tornava isso irrelevante — confirmado por
> instrumentação (`diag_lethal_don_alloc.py`) em 82,4% dos momentos LETHAL
> reais. Fix atrás de `FIX_LETHAL_DON_ALLOCATION` (default True). Medição
> pareada (`measure_lethal_don_fix.py`, N=20/matchup): Kid +0,25 winrate,
> Krieg +0,05, Teach −0,05 (perto do teto, prováv. ruído) — turnos até
> fechar caem nos 3 sem exceção. Maximin reprova pela regra estrita, mas
> usuário decidiu aceitar o fix como está (seguro/reversível, smokes 100%)
> e deixar a confirmação vir dos logs ao vivo. Cruzamento com os 79 logs
> reais BLOQUEADO estruturalmente: AutoSaved corta as linhas finais antes
> de GameOver em TODOS os 5 casos que chegaram perto do fim — só partida
> nova com captura completa resolve. Ver HANDOFF bloco 285 e
> `scriptis_da_ia/GUIA_AUDITORIA_DECISOES.md` (novo, referência viva do
> Turn Planner pra auditorias futuras).

> 19/07/2026: retomadas as 3 pendências do proxy/telemetria adiadas desde
> 18/07 (bloco 268) agora que a varredura fechou. `semantic_transition_failed`
> era 2 falsos-positivos (OP15-026 `activate` com custo de auto-trash) + 1
> alerta duplicado (checagem semântica rodando sobre execução já `failed`) —
> corrigido em `bot_efficiency_report.py`, confirmado reprocessando o JSONL
> real de 18/07 (alerta sumiu). `winner: null` no `logs/index.json` —
> causa raiz real era `/outcome` já saber `win/loss` mas nunca repassar pro
> `collect_latest_match.py`; `_apply_winner()` nova mapeia win→p1/loss→p2
> (p1 sempre "You", confirmado via `RE_LEADER`). `state_after_coverage_pct`
> 88,5%/12 `target` pendentes pra sempre — causa raiz real achada por leitura
> estática do `BotDriver.cs`: branch "remaining==0" confirma e `return`s antes
> do único lugar que reportava `sent` pro decisionId recém-pedido, orfanando
> a decisão. Fix aplicado e compilado (`dotnet build` limpo), **mas precisa
> validação em partida real** (não declarar resolvido sem log ao vivo) —
> próxima sessão ao vivo deve rodar `BOT\setup_bepinex.bat` e conferir se o
> gate de 95% é atingido. Ver HANDOFF bloco 284.

> 19/07/2026: ST30-001/002/017 + ST10-003 — pedido explícito do usuário
> pra revisar TODOS os 103 suspeitos restantes até o fim do dia. 2
> candidatos reais achados (ST30-001 líder: auto-debuff "this Leader"
> nunca reconhecido, mesma família de OP16-017 mas pro sujeito Leader +
> lista de 2 nomes em buff de massa nunca suportada; ST30-002/017:
> power exato sem qualificador nunca filtrado em add_to_hand). Os
> outros ~98 confirmados falso-positivo genuíno (sem bug real por
> trás). **FECHA a sessão de varredura**: janelas 1-109 revisadas em 5
> lotes ao longo do dia, 139 -> 100 suspeitos. Ver HANDOFF bloco 282 e
> `parser_audits/2026-07-19_encerramento_st30-001_st30-002.json`.
> Auditor: 103 -> 100 suspeitos.

> 19/07/2026: cauda final da varredura desta sessão (OP06-057 a
> OP15-119), 8 cartas via 5 fixes. Destaques: `play_from_deck` ganhou
> `cost_eq` (mesmo suporte que `play_card` já tinha); mecânica nova
> `life_top_revealed_cost` (escala power pelo custo da carta revelada
> da Life via peek); conversão "[Opponent's Turn] When this Character
> is K.O.'d..." em PROSA pra `on_ko` real (generalização da lógica já
> usada pra colisão de tags formais). **Fecha a sessão**: janelas 1-109
> do audit revisadas em 4 lotes — 139 -> 103 suspeitos ao longo do dia.
> Ver HANDOFF blocos 278-281 e
> `parser_audits/2026-07-19_ultimos_5_op06-057_a_op15-119.json`.
> Auditor: 109 -> 103 suspeitos.

> 19/07/2026: lote de 16 itens (OP09-051 a OP15-059), ~38 cartas via
> generalização (janela 51-100, taxa de acerto alta). Destaques: bug
> ESTRUTURAL real (OP12-096 — condição travava o K.O. inteiro em vez de
> só fazer upgrade do teto de custo); mecânica nova `opp_play_card`
> (força o OPONENTE a jogar da própria mão, nunca visto antes);
> generalização de `m_select_buff` pra N tipos em OR expôs e corrigiu
> uma 2ª bug no mesmo mecanismo (duration errada dentro de Counter, 9
> cartas extras); `unless_opp_pays` estendido pra aceitar custo de
> devolver DON (não só trashar Life). **Tentativa de fix ampla pra
> OP13-046 causou duplicação em ~25 cartas não relacionadas, detectada
> via diff_parser.py e REVERTIDA antes de aceitar o lote** — lição
> registrada: preferir ampliar rede de segurança específica a alargar
> regex sem contexto posicional. Ver HANDOFF bloco 280 e
> `parser_audits/2026-07-19_lote_16_op09-051_a_op15-059.json`.
> Auditor: 127 -> 109 suspeitos.

> 19/07/2026: OP05-099 + OP07-036, 2 mecânicas novas de gating
> condicional (janela de 50, taxa de acerto baixa — maioria já
> falso-positivo conhecido). `unless_opp_pays` (OP05-099: oponente pode
> pagar Life pra PREVENIR um efeito — oposto do padrão "you may X. If
> you do, Y" onde a escolha é do próprio jogador) e
> `requires_own_cost` (OP07-036: custo condicional do próprio jogador
> gating só um step específico do bloco, não o bloco inteiro). Ambos
> genéricos, resolvidos no engine antes do dispatch por `action`,
> seguindo a mesma simplificação já usada em
> `lock_opp_attack_unless_pays` ("paga sempre que pode"). Ver HANDOFF
> bloco 279 e
> `parser_audits/2026-07-19_op05-099_op07-036_custos_condicionais_gating.json`.
> Auditor: 129 -> 127 suspeitos.

> 19/07/2026: lote de 11 bugs reais (OP14-054 a ST07-017), 46 cartas no
> total via generalização (janela 151-200+). Destaques: 2 mecânicas
> novas (`trash_to_hand_count` irmã de `draw_to_hand_count`;
> `bounce_any_own_character` custo de quantidade variável +
> `buff_power_per_count(source='bounced_own_this_effect')`); nova
> condição `chars_gte` de existência pura (sem qualificador de
> power/cost) — generalização de alto impacto, 5 cartas extras de
> graça; normalização de dígito circulado Unicode (①-⑳) no custo DON;
> `filter_type` como LISTA em custos `reveal_from_hand` (OR de 2 tipos
> bracketed); typo "K.O up to" (verbo sem ponto final, classe diferente
> do "K.O'd" do lote anterior). **Bug de duplicação encontrado e
> corrigido DURANTE a própria validação do lote**: um fix inicial via
> check local dentro de `parse_look_at` duplicava `trash_from_hand` em
> OP16-067 (mesmo texto de OP16-077, mas já coberto por um mecanismo
> genérico separado) — corrigido estendendo a whitelist genérica
> existente em vez de duplicar a lógica; lição registrada em HANDOFF.
> Ver HANDOFF bloco 278 e
> `parser_audits/2026-07-19_lote_10_op14-054_a_st07-017.json`.
> Auditor: 139 -> 129 suspeitos.

> 19/07/2026: lote de 15 bugs reais (OP15-020 a OP16-038), 26 cartas no
> total — o lote mais produtivo até agora (janela 101-150, ~10-12% de
> acerto). 1 falso-positivo confirmado (OP15-020, mesma simplificação de
> OP05-038). Destaques: bug ESTRUTURAL real em `parse_power_buff` (o
> ramo de debuff nunca checava se o alvo era a própria carta antes de
> assumir "sempre oponente" — corrigido na origem, já capturou uma
> carta extra de graça); 2 mecânicas novas (aura de keyword por NOME +
> override condicional de base power "só no turno do oponente", e
> seleção por nome de [Rush: Character] + concessão de atributo
> temporário); nova condição `has_named_characters` (presença composta
> de 2 nomeados, com variantes para trash e para exigir power exato);
> typo "K.O'd" (faltando 1 ponto) bloqueava uma substituição inteira.
> Ver HANDOFF bloco 277 e
> `parser_audits/2026-07-19_lote_9_op15-020_a_op16-038.json`.
> Auditor: 161 -> 139 suspeitos.

> 19/07/2026: lote de 8 bugs reais (OP09-051 a OP10-080), 24 cartas no
> total (via diff_parser + generalização): OP09-068/070/073+família
> (OP09-065/076/119 — custo "return 1 or more DON!! cards" inteiro
> ausente, habilidade grátis), OP09-092 (condição de comparação de mão
> ausente — nova `hand_fewer_than_opp_by_gte`), OP09-105+OP06-115
> ("trash N from hand" sumia em blocos [Trigger] — whitelist ampliada),
> OP10-033+P-078/P-079 (condição "2+ rested tipo X" sem filtro de tipo
> suportado), OP10-043+família (OP10-044/048/056/081/095 — custo "rest
> Leader/Stage" isolado ausente + Banish mirava self em vez do
> selecionado — nova ação select_grant_banish), OP10-070 (imunidade a
> KO com filtro de POWER, mesma família do OP06-096 mas mis-roteada),
> OP10-080 (condição composta DON+mão, metade da mão sumia). Achado
> colateral: 4 cartas (EB03-001/OP03-058/OP06-020/OP15-039) tinham o
> custo "rest this Leader" inteiro ausente. Ver HANDOFF bloco 276 e
> `parser_audits/2026-07-19_lote_8_op09-051_a_op10-080.json`.
> Auditor: 172 -> 161 suspeitos.

> 19/07/2026: mudança de ritmo na varredura (usuário pediu pra acelerar
> após 3 dias na mesma tarefa) — a partir daqui, revisar lotes de 50
> suspeitos por vez (em vez de 10-25), pré-filtrando falsos-positivos já
> conhecidos e trazendo só os candidatos reais pro usuário aprovar de uma
> vez. Lote de 6 bugs reais (OP08-029 a OP08-096), 9 cartas no total:
> OP08-029 Pekoms (aura de imunidade a KO virava auto-imunidade genérica
> sem filtro — nova ação `grant_ko_immunity_aura`, novo loop em
> `is_immune()`), OP08-038 (bloco Main inteiro sumia — custo "rest N of
> your Characters" sem filtro e concessão "None of your Characters..."
> sem tipo nunca eram reconhecidos; achado colateral real: pool de
> `grant_ko_immunity_type` incluía o Leader por engano quando não havia
> filtro nenhum, nunca exercitado até agora), OP08-049 (condição do
> reveal sumia por causa de uma cláusula de destino inline antes do
> "If" — Rush disparava sempre), OP08-052+OP08-054 (cost_lte caía no
> fallback 99 por não tolerar "and a cost of" além de "with a cost
> of"), OP08-058 (custo "turn N cards da vida face-up" só tolerava N=1
> literal, sumia com N>1), OP08-096 (mecânica nova: mill condicionado ao
> custo da carta milhada — nova ação `trash_deck_top_conditional`).
> 2 capturas extras da mesma generalização: OP01-055 (custo inteiro
> sumia, draw 2 virava grátis) e OP04-083 Sabo (mesmo gap do item 2). Ver
> HANDOFF bloco 275 e
> `parser_audits/2026-07-19_lote_7_op08-029_a_op08-096.json`.
> Auditor: 178 -> 172 suspeitos.

> 19/07/2026: lote de 6 bugs reais (OP07-009 a OP07-097), 8 cartas no
> total: OP07-009 (filtro de cor ausente em select_grant_double_attack),
> OP07-036 (número trocado — regex desescopado pegava o número de uma
> cláusula de custo anterior), OP07-050+OP07-052 (condição "OR
> multi-tipo" nunca suportada), OP07-059 (trava mista Leader+Character
> ausente — achado colateral: refresh_phase nunca checava o freeze do
> Leader, mecânica de congelar líder era sempre no-op no engine),
> OP07-094+OP07-055 (auto-bounce condicional e bloco [Trigger] inteiro
> sumiam — 2 variantes novas de fraseado em parse_bounce), OP07-097
> (mecânica de escolha jogar-ou-vida inteira ausente, virava gain_life
> fixo do deck errado). Ver HANDOFF bloco 274 e
> `parser_audits/2026-07-19_lote_6_op07-009_a_op07-097.json`.
> Auditor: 183 -> 178 suspeitos.

> 19/07/2026: lote de 10 suspeitos severidade-1 (itens 33-53), 12 fixes/19
> cartas reais: OP03-096 (KO com alvo alternativo Stage ausente),
> OP04-028+034 (condição "N+ DON ativo" quebrada pelo qualificador
> "active"), OP04-040 (escolha mutuamente exclusiva draw/gain_life nunca
> modelada, disparavam juntos), OP04-118 (concessão de Rush em massa
> virava self-buff sem sentido), OP05-099 (investigado, confirmado
> falso-positivo — já segue simplificação aceita em outro lugar),
> OP06-011+família (custo "rest N of your [Nome]" ausente), OP06-014+4
> cartas (buff dinâmico "por carta descartada" virava fixo sem custo),
> OP06-063 (filtro de power ausente em busca no trash), OP06-074
> (variante por power de um mecanismo já existente), OP06-083+OP14-056
> (negar o próprio efeito libera "cannot attack" — mecânica nova),
> OP06-096 (imunidade de KO em massa sem filtro de custo, alcance maior
> que o pretendido), OP06-117 (2º componente de custo composto ausente).
> Ver HANDOFF bloco 273 e `parser_audits/2026-07-19_lote_12_op03-096_a_op06-117.json`.
> Auditor: 196 -> 183 suspeitos.

> 19/07/2026: lote de 10 suspeitos severidade-1 (itens 21-32). 5 fixes/12
> cartas reais: OP03-021+família (custo "rest N de tipo X" ausente),
> OP03-040 (regra "vence ao invés de perder no deck-out" ausente por usar
> frase-preâmbulo diferente da esperada), OP03-045/049/053 (condição "20
> ou menos cartas no deck" nova), OP03-070+família (custo perdia filtro
> de custo exato, aceitava qualquer carta da mão), OP03-083 (parsing
> ERRADO — inventava um add_to_hand que não existe no texto real, quando
> o certo era "olhe 5, descarte até 2, resto no fundo"). Ver HANDOFF
> bloco 272 e `parser_audits/2026-07-19_lote_5_op03-021_a_op03-083.json`.
> Auditor: 204 -> 196 suspeitos.

> 19/07/2026: lote de 10 suspeitos severidade-1 (itens 11-20). 6 fixes/8
> cartas reais: OP02-030 (`[On K.O.]` inteiro sumia por janela de regex
> curta + custo exato virava "qualquer custo"), OP02-049 (condicao "0
> cartas na mao" ausente, draw disparava sempre), OP02-051/OP02-069
> (mecanica nova "draw ate ter N na mao"), OP02-059/OP02-070/OP09-059
> ("trash up to N da mao" como 2a clausula, nunca capturada em
> activate_main/counter), OP09-059 (mill ligado ao trash real da mao),
> OP03-012 (custo virava trash da MAO em vez do CAMPO, faltava filtro de
> cor). Achado colateral fora de escopo: EB04-011 tinha mecanica "draw 1
> por cada Character de um tipo" ainda nao suportada. **Implementado
> depois, no mesmo dia** — novo `count_source='own_field_type_count'` +
> `then_trash_same_as_drawn` no action `draw` (parser e engine), ver
> `parser_audits/2026-07-19_eb04-011_draw_por_contagem_de_tipo.json`. Ver
> HANDOFF bloco 271 e `parser_audits/2026-07-19_lote_8_op02-030_a_op03-012.json`
> pro achado original. Auditor: 212 -> 204 suspeitos.

> 19/07/2026: bug no audit_parser_coverage.py corrigido (valores negativos
> no JSON nunca batiam com o texto sem sinal) -- 213 -> 212 suspeitos. Ver
> HANDOFF bloco 270.

> 19/07/2026: lote de 10 suspeitos severidade-1 revisado. A maioria era
> falso-positivo conhecido (`give_don`/`buff_power`/`debuff_power` "up to 1"
> = alvo unico implicito). Achado real: 15 cartas com `[Your Turn][On Play]`
> disparavam 2x (ao entrar em campo E todo turno seguinte via
> apply_your_turn_buffs) -- corrigido com gate `your_turn_only` +
> `EffectExecutor.execute(is_my_turn=...)`, preservando o caso real de
> jogar via Trigger de vida no turno do oponente (usuario mostrou carta
> nao lancada ainda, Killer ST36-002, com o mesmo padrao). Ver HANDOFF
> bloco 269 e `parser_audits/2026-07-19_your_turn_on_play_disparo_unico.json`.
> Nao reduz o contador do audit (bug era de execucao, nao de extracao de
> numero) -- 213 suspeitos continuam.

> 19/07/2026: usuario decidiu ADIAR as 3 pendencias do proxy/telemetria abaixo
> (state_after_coverage_pct, semantic_transition_failed, winner:null) ate
> terminar a varredura do parser (213 suspeitos restantes nesta data). NAO
> retomar bot/proxy antes disso sem pedido explicito -- prioridade e fechar
> os lotes de cartas pendentes primeiro.

> 18/07/2026: 2 partidas ao vivo testando o proxy. Achada e corrigida a causa
> raiz do gap de confirmacao/outcome: DLL do plugin desatualizada (3 dias
> atras dos commits de telemetria). Rebuild via `setup_bepinex.ps1` resolveu
> `/outcome` (0% -> 100% coverage) e `/execution` (null -> 98.9% confirmado).
> Pendente (adiado, ver nota acima): `state_after_coverage_pct` ainda em
> 88.5% (< gate 95%, 12 decisoes de `target` sem confirmar), 3
> `semantic_transition_failed`, e `winner: null` cosmetico em
> `logs/index.json`. Ver HANDOFF bloco 267.

> 18/07/2026: proxy ganhou verificacao do nome canonico/banco, match_id estavel,
> latencia, alertas, confirmacao semantica Main Phase e comparacao entre commits.
> Sem teste ao vivo ainda: GameOver/AutoSaved, prompts auxiliares e calibracao.

> 18/07/2026: lote 2 de 10 pendencias concluido; OP02-016 tambem foi
> corrigida pela familia de filtro cor+custo. Auditor caiu de 228 para 217.
> Evidencia em `scriptis_da_ia/parser_audits/2026-07-18_lote_10_op01-063_a_op05-100.json`.

> 18/07/2026: lote 1 de 10 pendencias concluido; cinco parentes adicionais
> receberam os fixes de familia. Auditor caiu de 241 para 228. Evidencia em
> `scriptis_da_ia/parser_audits/2026-07-18_lote_10_eb01-011_a_op05-007.json`.

> 17/07/2026: instrumentacao ampliada para Main Phase, defesa, mulligan e
> alvos, com resultado final, deltas futuros 1/3/5 e contrafactual simulado.
> Coleta real pendente conforme `metrics/evidence_collection_plan.json`.
> Coleta pos-partida automatizada por `collect_latest_match.py` no evento
> `GameOver`; validar ao vivo na proxima partida.
> Confirmacao visual e via LogOutput implementada; validar cores/texto ao vivo.

---

## 🟣 ORGANIZAÇÃO PROFISSIONAL DO CONTEXTO — regras, especificações e skills (17/07/2026, avançado 25/07/2026 bloco 376)

Objetivo: reduzir contexto repetido sem esconder decisões arquiteturais em memória
local ou em prompts enormes. Não mover tudo para skills; cada informação deve ter
uma fonte canônica conforme sua função:

- [x] **`AGENTS.md` = constituição curta do projeto** — **achado 25/07**: o
  arquivo já existia (não "não criado" como este item dizia), mas estava
  dessincronizado do `CLAUDE.md` há semanas — faltavam regra sem-duplicação,
  regra dos dois-pontos, gate do parser, seções de telemetria/eficiência.
  Ressincronizado por inteiro; os dois arquivos ganharam nota "Espelho" no
  topo alertando pra replicar edições futuras nos dois. Não elimina o risco
  de divergir de novo (isso é o item de de-duplicação abaixo, adiado de
  propósito), só torna visível.
- [x] **`specs/` = comportamento verificável:** criada a primeira especificação
  em `specs/metrics-protocol.md`; continuar com especificações pequenas por
  domínio (`engine-rules.md`, `parser-contract.md`, `bot-bridge.md`,
  `metrics-protocol.md`). Cada regra deve apontar para teste/evidência e definir
  entrada, saída, invariantes e critério de aceite. Evitar repetir o `AGENTS.md`.
- [x] **Skills extraídas (25/07, bloco 376)**: `.claude/skills/optcg-parser-audit`,
  `.claude/skills/optcg-live-log-triage`, `.claude/skills/optcg-release-handoff`
  — cada uma aponta de volta pro `AGENTS.md`/`CLAUDE.md`/`TODO.md` pro "porquê",
  só o "como executar passo a passo" fica na skill.
- [x] **Scripts determinísticos em vez de instrução textual:** criado
  `scriptis_da_ia/bot_efficiency_report.py`, com cohorts explícitos, bootstrap
  IC95%, proxy opcional e JSON reproduzível. Próximos scripts devem seguir o
  mesmo padrão e ser chamados pelas skills.
- [ ] **`HANDOFF.md` = deltas recentes:** manter registro cronológico do que mudou,
  evidências e próximo passo; consolidar fatos estáveis nas specs.
- [x] ~~**Gate de consistência documental**~~ — **descartado pelo usuário
  25/07** ("acho que esse gate não precisa, não entendi direito o que ele
  faz"). Não reabrir sem pedido explícito.

### Ordem recomendada de implantação

1. ~~Criar `specs/metrics-protocol.md` e o script de relatório antes/depois.~~
   **Concluído em 17/07/2026.**
2. ~~Extrair o workflow estável do parser para `optcg-parser-audit`.~~ **Concluído 25/07/2026.**
3. ~~Extrair triagem de combat log para `optcg-live-log-triage`.~~ **Concluído 25/07/2026.**
4. **Pendente, de propósito adiado**: reduzir textos duplicados de
   `AGENTS.md`/`CLAUDE.md`/`HANDOFF.md` (hoje são espelhos quase completos
   um do outro — funciona, mas ainda tem o risco de divergir nas edições
   futuras que a nota "Espelho" só mitiga, não elimina).

---

## ✅ TELEMETRIA DE DECISÃO NUNCA PERSISTE — resolvido como REGRA, não como pipeline (24/07/2026)

**Achado original (bloco HANDOFF 342, sessão remota):** telemetria de
decisão (`decision`/`execution`/`outcome` no JSONL, relatório agregado,
`decision_summary.py`) funciona bem durante a partida, mas nunca vai pro
banco versionado — `BOT/engine_server/logs/` e
`scriptis_da_ia/metrics/live_runs/` são `gitignored` por design. Uma
sessão remota (nuvem) nunca tem acesso a essa telemetria, nem da partida
mais recente — investigar uma partida antiga virava reconstruir a
intenção do bot lendo só o combat log bruto.

**Decisão do usuário (24/07, sessão local): NÃO commitar/versionar essa
telemetria no Git.** Ela já existe e persiste normalmente no disco local
de quem roda o bot — o gap real não era falta de dado, era a regra do
`CLAUDE.md` não deixar claro que (a) isso só é possível numa sessão com
acesso ao filesystem local, e (b) tem que ser incondicional, não algo que
passa despercebido. Fix aplicado só em `CLAUDE.md` (seção "Telemetria de
decisão — OBRIGATÓRIO"): sessão local lê sempre que um log do bot for pro
banco; sessão remota declara explicitamente que a telemetria está
indisponível em vez de reconstruir via combat log cru e reportar como
investigação completa. Sem código novo, sem `collect_latest_match.py`
alterado, sem `.jsonl`/`.gz` no banco.

Investigação de tamanho/formato feita mas descartada como não-necessária:
`state_before`/`state_after` são ~91% do peso de um decision log
(1-4 MB/partida), gzip reduziria pra ~35 KB/partida — fica registrado
aqui caso a decisão de versionar mude no futuro.

---

## 🔴 EFICIÊNCIA DO BOT — baseline percentual e medição pós-fix (17/07/2026)

Não existe hoje uma porcentagem única cientificamente válida de “eficiência”.
Win rate mede resultado; ataques/DON/dano medem comportamento. Não misturar tudo
num percentual arbitrário. Se houver score composto, fixar os pesos em
`specs/metrics-protocol.md` antes de olhar o resultado.

**Antes (bot Imu ao vivo, amostra histórica) comparado ao humano Imu:**

| métrica | humano | bot antes | eficiência relativa |
|---|---:|---:|---:|
| ataques por turno | 2,03 | 0,88 | **43,3%** |
| ataques no líder | 82% | 42% | **51,2%** |
| dano de vida por partida | 4,2 | 1,3 | **31,0%** |
| counters arrancados por partida | 5,2 | 2,4 | **46,2%** |

**Proxy pós-correções, ainda não equivalente a teste ao vivo:** motor com informação
completa fez 1,28 ataques/turno (**63,1%** do humano; ganho relativo de **45,5%**
sobre 0,88) e 91% dos ataques no líder (**111,0%** da taxa humana; +49 pontos
percentuais sobre o bot antigo). Isso demonstra que o estado completo resolve boa
parte da seleção de alvo, mas não prova a eficiência atual do bot/bridge.

- [ ] **Medir o agora ao vivo:** reinstalar o plugin com `BOT\setup_bepinex.bat`,
  jogar no mínimo 5 partidas Imu (ideal: mesmos matchups ou espelho) e adicionar
  todos os combat logs ao banco com `parse_combat_log.py --add-to-db`.
- [x] **Gerar relatório reproduzível:** `bot_efficiency_report.py` usa cohorts
  explícitos, a mesma janela de turnos e definições
  para ataques/turno, % líder, dano, DON/ataque, counters arrancados, duração e
  win rate quando disponível; inclui tamanho da amostra e IC95% bootstrap. A
  qualidade da decisão e o sucesso de execução permanecem `null` até existir
  telemetria pré-ação com `decision_id` nos logs antigos. **Instrumentação nova
  implementada em 17/07:** decisões de Main Phase agora registram estado pré/pós,
  ações pontuadas, escolha e `sent/confirmed/failed`; falta coletar partidas reais
  e estender o mesmo envelope a defesa, mulligan e escolhas de alvo.
- [ ] **Critério mínimo de melhora ao vivo:** ≥1,28 ataques/turno, ≥80% no líder,
  dano/partida maior que 1,3 e nenhuma regressão nas invariantes/smokes. Meta
  posterior: aproximar 2,03 ataques/turno sem sacrificar win rate.
- [ ] **Gauntlet fixo motor-vs-motor:** manter Imu vs Teach/Krieg/Kid + espelho,
  seeds e decks congelados; comparar cada mudança contra os JSONs de 13/07.
- [ ] **Não chamar proxy de “depois”:** publicar porcentagem final somente após a
  rodada ao vivo pós-fix; até lá usar `antes`, `proxy engine` e `agora pendente`.

Fonte: `scriptis_da_ia/analise_imu_humano_vs_bot_2026-07-12.md` e
`scriptis_da_ia/PLANO_AVALIACAO_E_BUSCA.md`.

---

## 🟣 PLANO MESTRE DE EVOLUÇÃO DO MOTOR (13/07/2026) — LER PRIMEIRO

Depois de 3 dias de whack-a-mole de heurística (patch local por report →
pêndulos), foi decidido com o usuário mudar de método: núcleo de avaliação
único + busca, em vez de dezenas de notas locais. **Plano completo e vivo
em [PLANO_AVALIACAO_E_BUSCA.md](scriptis_da_ia/PLANO_AVALIACAO_E_BUSCA.md).**
Ordem: 0) baseline medido → 1) `evaluate_state` (régua única) → 2) extrator
de perfil do deck (termos derivados do banco, sem hardcode) → 3) resposta do
oponente (busca prof. 2) → 4) defesa pela mesma régua → 5) tunagem de pesos
por self-play. ML/MCTS descartados por ora. Estado atual: **item 0 em
execução.**

---

## 🔴 PASSIVIDADE DO BOT (12/07/2026) — análise humano vs bot pronta, teste ao vivo pendente

Ver [analise_imu_humano_vs_bot_2026-07-12.md](scriptis_da_ia/analise_imu_humano_vs_bot_2026-07-12.md)
(números completos + já-corrigido vs a-corrigir). Resumo: bot ao vivo
atacava 0.88/turno (humano 2.03), 42% no líder (humano 82%, motor com
info completa 91%) — causa raiz principal era o DTO sem trash (Nusjuro
sem Rush/imunidade, Ground Death nunca counterava), JÁ corrigida junto
com a política de counter por ganho líquido. **Próximo passo: rodar
`BOT\setup_bepinex.bat` e jogar 1-2 partidas de validação.** Se a
passividade persistir: (a) volume de ataque 1.28/t vs 2.03 mesmo com
info completa — peso de corpo agressivo vs utilitário em _score_to_play;
(b) `_don_reserve_for_defense` possivelmente guardando DON demais;
(c) attach de DON do bot não aparece no combat log (gap de logging do
plugin — subconta agressividade nas análises).

---

## 🟡 IMPLEMENTADO 19/07/2026, falta calibrar: consciência de combos estratégicos do oponente

**Estado atual**: `GameAnalyzer.opp_combo_threat()` (novo) generaliza a
detecção sem hardcode (líder/board público + `get_card_effects` estático,
sem depender de decklist do oponente); nova prioridade `PREVENT_COMBO`
(entre `DEFENSIVE`/`REMOVE_THREAT`); termo simétrico em
`_evaluate_state_v2` (peso `opp_combo_threat`). Confirmado em self-play
real (`PREVENT_COMBO` disparou 8x em 276 decisões, `--n 8 --seed 7`).
**Falta**: calibração formal (limiar `magnitude>=2`, pesos 150/80/0.8) via
self-play pareado com seeds fixos, mesmo protocolo maximin do fix de
LETHAL (ver HANDOFF bloco 285); e — quando surgir partida ao vivo nova —
confirmar que o padrão observado em 07/07 (Five Elders reanimando 4-5
corpos) realmente é neutralizado/reduzido. Ver HANDOFF bloco 287 pro
detalhe completo.

**Tentativa 10/08/2026 (bloco 491)**: os 3 literais viraram constantes
nomeadas (`PREVENT_COMBO_MAGNITUDE_THRESHOLD`/`PREVENT_COMBO_DEFENSIVE_
CARD_BONUS`/`PREVENT_COMBO_LEADER_ATTACK_BONUS`, mantido — melhoria
válida por si só). Self-play pareado (baseline vs 2 candidatos,
Mihawk/Ace vs Imu, N=12/matchup) **subdimensionado**: o gatilho
(`opp_combo_threat()['magnitude']>=1`) só apareceu em 2/12 partidas por
matchup — não deu sinal suficiente pra decidir entre baseline/candidatos,
valores de produção mantidos sem mudança.

**2ª tentativa 10/08/2026 (bloco 492), N=60/matchup — causa raiz REAL
encontrada, não é falta de amostra**: taxa de disparo subiu pra 26,7%
(32/120), mas os 3 lotes continuaram idênticos até o dígito. Investigado
a fundo: `analysis_priority()` é uma cascata com LETHAL/DEFENSIVE ACIMA
de PREVENT_COMBO — nos matchups escolhidos (vitórias decisivas, 60-75%
de winrate), quando `opp_combo_threat` sobe o próprio lado já costuma
estar perto de LETHAL, que sempre vence a cascata primeiro. Confirmado
numa partida real (magnitude=4 no turno 11): 3 de 4 decisões daquele
turno tinham `priority=LETHAL`, não `PREVENT_COMBO`. **Mais amostra não
resolve isso** — é insensibilidade estrutural do teste, não tamanho de
N. Calibração real ainda **pendente**, mas agora com um design mais
claro pro futuro: precisa de matchups mais equilibrados (sem LETHAL/
DEFENSIVE disponível com frequência) ou medir a qualidade das decisões
diretamente nos momentos em que `priority==PREVENT_COMBO` de fato
ocorre, não o winrate agregado da partida inteira (que raramente
depende dessas poucas decisões nos matchups testados até agora).

Descrição original do problema abaixo, preservada pra contexto:

4 partidas reais instrumentadas na sessão de 07/07 (ver HANDOFF 99/100) — o
bot perdeu as 4, e as 4 pelo **mesmo padrão exato**: o oponente (Imu/Five
Elders) monta uma mão de custo alto no trash (Ju Peter, Ethanbaron, Warcury,
Marcus Mars, Saturn) através de descartes forçados de outros efeitos, e
depois o Five Elders reanima TODOS eles de uma vez num único turno
("Deployed X from Trash" 4-5x seguidas), fechando o jogo com o Ethanbaron
bufado (DON + counters empilhados) num único ataque de 8-9k que o bot não
tem resposta pra segurar.

Os 8+ fixes táticos da sessão de 07/07 (redirect com alvo real, margem de
counter effect-aware, guarda de campo cheio, etc. — ver HANDOFF 99/100)
são todos válidos e testados, mas **nenhum deles ataca esse padrão**,
porque são todos correções de qualidade de decisão PONTUAL (qual carta
sacrificar agora, quanto DON anexar neste ataque). O buraco real é
ESTRATÉGICO: o motor não tem noção de "esse oponente está montando um
combo de virada, preciso desarmar/acelerar/guardar recurso ANTES dele
disparar" — só reage turno a turno sem olhar pro padrão.

**Ideia (ainda não desenhada)**: usar os logs de partidas reais (`CombatLogs/`)
pra identificar, por arquétipo/deck, qual é o "combo de virada" característico
(ex: Five Elders = reanimação em massa; outros decks vão ter outros
padrões — DON ramp pra lethal, mill, etc.), e alimentar isso de volta no
motor como um sinal de ameaça agregada (não só "quanto poder esse
personagem tem agora", mas "quanto poder esse BOARD PODE virar se o
oponente disparar o combo dele"). Precisa decidir:
- Onde isso vive: um módulo novo de "leitura de combo" (parecido com
  `opponent_model.py`, que já faz leitura probabilística de mão) ou uma
  extensão do `GameAnalyzer` (`opp_lethal_threat`/`critical_threats` já
  fazem algo parecido pra ameaça imediata — talvez baste generalizar pra
  ameaça "daqui a N turnos" olhando o trash do oponente).
- Como detectar o padrão sem hardcode por card_id: contar characters de
  alto custo/poder no trash do oponente + presença de uma carta com
  `play_from_trash`/`play_card source_alt=trash` em massa (o Five Elders é
  um caso desse tipo) já dá pra generalizar sem precisar saber o nome da
  carta.
- Resposta esperada do motor quando o sinal aparece: acelerar o clock
  (raça), guardar counter/blocker pro turno da virada, ou remover peças-chave
  do trash antes (`exile`/negação de recursão, se o deck do bot tiver isso).

~~Não escopado nem começado ainda~~ — implementado 19/07/2026 (ver nota no
topo desta seção e HANDOFF bloco 287). Os 4 logs de 07/07 citados abaixo
não foram encontrados (nunca arquivados no banco) — trabalhado em cima da
descrição já registrada em HANDOFF 99/100.

---

## Dívida técnica ativa — Turn Planner

- [x] **Reduzir `deepcopy` em `_simulate_sequence*`** — **implementado (02/07/2026).** `_SimDeck` (list subclass copy-on-pop lazy) aplicada ao `p.deck` + mesmo truque do `opp.deck`. Speedup 2.8× (0.85ms → 0.30ms/call, 31ms → 11ms/main_phase). Ver HANDOFF (13). a poda de orçamento já
  melhorou o runtime; a reserva defensiva agora é calculada uma vez por estado
  em `_generate_and_score_actions()`; e `GameState.__deepcopy__` já tem cópia
  manual mais enxuta. `main_phase()` também passou a simular no mínimo 3
  candidatas e só incluir a 4ª-6ª quando estiverem perto da melhor por score.
  Ainda assim, o gargalo estrutural continua sendo clonar estados demais dentro
  do planner. Próxima melhoria real deve atacar clone incremental ou cache
  seguro de avaliações por estado, medindo impacto em qualidade de decisão.
- [x] **Cache de `_lethal_search`** — **implementado (25/07/2026, Fase D,
  bloco HANDOFF 368).** Turno late-game real: 103.78s → 2.583s (~40x).
- [ ] **`compute_game_plan_from_cards` sem cache** — re-profiling pós-fix
  do Fase D (25/07/2026) mostrou essa função como o próximo maior
  `tottime` isolado depois de `hits_after_best_defense`: 2803 chamadas,
  0.411s cumtime / 0.229s tottime num turno de 2.316s (~18% do turno).
  Mesmo padrão do fix de `_lethal_search`: função pura sobre estado
  não-mutado, chamada repetidamente dentro do mesmo batch de scoring
  (`_generate_and_score_actions`) sem cache. `_lethal_search` também
  continua custando ~40% do turno MESMO com cache (0.926s de 2.316s),
  porque cada branch simulado (`_simulate_sequence_once`) muta o
  estado de verdade — o cache só evita recomputar dentro do MESMO
  estado, não entre branches. Baixa prioridade: o essencial já foi
  resolvido (offline caiu de >100s pra poucos segundos por turno,
  ao vivo já tinha folga generosa no timeout de 4s antes até do fix).
  Só atacar se um profiling futuro mostrar isso virando gargalo real de
  novo (ex: partidas muito mais longas/pesadas que as testadas aqui).

---

## ✅ Dívida técnica — "in any order" tratado como irrelevante em vários pontos (16/07/2026, fechada 19/07/2026)

Pedido explícito do usuário: o engine deve escolher a MELHOR ordem
quando o texto oficial diz "in any order" (não é estética/irrelevante
como o código vinha assumindo em múltiplos comentários). Corrigido
originalmente pro caso `place_own_character_bottom_deck` (STEP, ordena
por `board_value()` descendente — mais forte fica mais perto do topo do
deck, comprado mais cedo se o deck chegar lá; ver HANDOFF bloco 199).

**Atualização (19/07/2026) — os 2 pontos pendentes foram auditados:**

- `place_from_trash_bottom_deck` (custo, `_pay_costs` em
  `decision_engine.py`): **corrigido.** Escolhia via `candidatos.pop()`
  sem critério de ORDEM (mesmo comentário "irrelevante"). Fix: entre as
  `count` cartas ESCOLHIDAS (a seleção em si — quais cartas saem do
  trash — ficou INALTERADA, ainda os últimos `count` elegíveis na ordem
  do trash, mesmo critério de sempre), insere no fundo do deck da mais
  forte pra mais fraca (mesma convenção de `place_own_character_
  bottom_deck`). Deliberadamente NÃO mudei a seleção (qual card sai do
  trash): 25 cartas reais usam esse custo com `count>1`, e pelo menos
  uma (OP05-088 Mansherry) tem um EFEITO seguinte no MESMO bloco que
  recupera outra carta específica do MESMO trash — priorizar a seleção
  por `board_value` levaria embora justamente a carta que o próximo
  step precisa (achado direto ao rodar `smoke_fast.py`, teste
  `test_custo_composto_trash_para_fundo` quebrou e expôs o problema).
  Ver `parser_audits/2026-07-19_in_any_order_bottom_deck_custos.json`.
  De graça, achado colateral: o mesmo bug de ORDEM (sem o problema de
  seleção, já que não há filtro concorrente) existia também no CUSTO
  `place_own_character_bottom_deck` (distinto do STEP homônimo já
  corrigido) — 0 cartas reais com `count>1` hoje, corrigido
  preventivamente pra qualquer carta futura.
- Reordenação de topo do deck em efeitos de busca (`deck_reorder_rest`/
  `deck_top_rest`, "look at N cards... place the rest at the top or
  bottom of the deck in any order"): **já estava corrigido antes desta
  sessão** (ver comentário datado 01/07/2026 em `decision_engine.py`,
  função do action `deck_reorder_rest`/`deck_top_rest` — heurística
  "melhor carta vai pro topo do deck" já implementada, 21 cartas
  cobertas). Nota antiga em TODO.md estava desatualizada.
- Qualquer novo mecanismo futuro que mencione "in any order" — checar
  este item ANTES de assumir que não importa.

Não fazer tudo de uma vez (escopo grande, muitos mecanismos distintos)
— tratar como fila própria, 1 mecanismo por vez, mesmo protocolo já em
uso (censo → confirmação do usuário → fix → smoke completo → registro).

---

## 🟢 FEITO NESTA SESSÃO (25-26/06)

Sessão focada em destravar mecânicas sem branch no engine (auditoria por mecânica,
não carta-a-carta). Método: levantamento por mecânica → confirma regra com Arthur →
implementa → valida (snapshot/diff PERDEU=0 + partidas reais instrumentadas).

### Blocos implementados (commits 961b881, 16c616c, bbb4d31, + viabilidade)

- [x] **Life unificada** (961b881): parse_heal deletada (bug top/bottom), parse_life
  reescrita com eixos (source: deck_top/hand/own_field/opp_life/trash; dest: life_top/
  bottom/top_or_bottom; count; up_to; face). 4 branches: gain_life, life_to_hand (novo,
  Hiyori OP06-106), attack_life, trash_own_life. life_to_hand como CUSTO suprimido
  (deixado p/ parse_costs). PERDEU=0, GANHOU=10.

- [x] **avaliar_carta usa flags do analysis_db** (16c616c): loader _ANALYSIS_DB +
  get_card_flags(). Trocada detecção por substring frágil pelas flags limpas
  (kos/is_removal/bounces/etc), cobertura ampliada (gives_don/gains_life/power_buff),
  guarda KO-no-vácuo. _score_play_action também migrado.

- [x] **play_card no engine** (232 cartas, maior bloco): regra = jogar GRÁTIS.
  GRUPO 1 (114, trigger-self): própria carta da vida, OPCIONAL por score.
  GRUPO 2 (118, da mão): melhor carta elegível por filtro, "up to", guarda campo cheio.
  _should_activate_main reconhece play_card. cost_lte dinâmico. Instrumentado: 943+3611
  execuções reais antes no-op. Empty Throne ATIVA (replay confirma).

- [x] **mill** (bbb4d31): trash_from_deck_top como efeito (51). Trash seco do topo.
  Bug corrigido de brinde: convenção topo do deck no gain_life (pop(0)→pop()).

- [x] **set_don_active** (bbb4d31): 56 cartas. Parser ganhou count/up_to; engine ganhou
  branch (rested→available). PERDEU=0.

- [x] **Viabilidade transacional** (a commitar): _step_is_viable + checagem antes de
  pagar custo. Se NENHUM step produz efeito real, não ativa e não paga. Regra AMPLA
  (minimiza jogadas-erro). Resolve desperdício Empty Throne (replay T7/9/11 ativava 3x
  sem jogar). Vale p/ TODA mecânica opcional. Validado.

### Comparação com simulador oficial (26/06)
- [x] Cruzamento ActV3 (simulador) × nossas actions — ver comparacao_simulador_vs_IA.md.
  Fonte: DLL 34.127 linhas, 100% lida. 39 cobertos, 28 ausentes (8 relevantes, 7 médios,
  13 raros). CONCLUSÃO: arquitetura está certa (trigger/condition/cost/step espelha
  proc/details/effect). Buracos são de cobertura, finitos.

---

## 🔴 PRÓXIMO (decisão via log real)

- [ ] **Comparação IA vs humano a partir do parse_combat_log**: dado um turno do JSON gerado pelo parser, instanciar o GameState equivalente no engine e ver o que a IA escolheria. Identificar divergências concretas para tunar scores/heurísticas. Script ainda não existe — próxima sessão.
- [ ] **[B] handlers sem log**: `look_top_deck`, `negate_effect`, `activate_trash_event_main`, `lock_opp_don` — efeitos que executam sem emitir evento no replay.

---

## 🔴 PROBLEMAS ABERTOS (replay Imu vs Sanji, 26/06)

- [x] ~~**Problema 2 — _choose_to_trash não avalia qualidade**~~: corrigido em
  29/06/2026. O descarte agora usa valor situacional e preserva eventos
  defensivos/removal como Ground Death quando há descarte pior.
- [x] ~~**Problema 3 — Five Elders (c10) nunca jogada**~~: corrigido em
  29/06/2026. Mary Geoise reduz o custo para 9; corpos premium agora podem
  disputar DON reservado em vez de serem filtrados antes do Turn Planner.

---

## 🔴 BURACOS DE MECÂNICA (cruzamento com simulador) — priorizados

> **CORRIGIDO em 28/06/2026** — lista original (`comparacao_simulador_vs_IA.md`)
> buscou só por nome literal no C#, sem checar sinônimos no Python. Re-auditada
> item a item contra `decision_engine.py`: DealDamage, ShuffleHandIntoDeck e
> CycleEntireHandToDeckBottom **já estavam implementados**. Lista abaixo reflete
> o estado real, verificado por linha de código.

### Achado/corrigido em 29/06/2026 — bug de identidade em `Card` (auditoria via replay real)
- [x] ~~Carta duplicada por REFERÊNCIA (mesmo objeto Python 2x) em
  `field_chars`~~ — achado pela auditoria #3 do plano do usuário (rodar
  partidas reais instrumentadas em vez de só seguir a lista teórica de
  gaps), não por nenhum gap conhecido. `Card` é `@dataclass` sem
  `eq=False`, então `__eq__`/`__hash__` são gerados por VALOR (todos os
  campos), de propósito — `_remap_action` (Turn Planner, ~linha 5064)
  depende disso pra mapear uma ação do estado real pro clone (deepcopy)
  via `.index(obj)`, já que objetos pós-deepcopy nunca são `is` o
  original. Efeito colateral: quando 2+ cópias físicas da MESMA carta
  com o MESMO estado (ex: recém compradas) coexistem na mesma zona,
  `list.remove(card)`/`card in lista` ficam ambíguos — podem
  remover/casar uma cópia IRMÃ em vez da carta exata. Reproduzido em 2 de
  25 partidas reais aleatórias (seed=42): "St. Topman Warcury" e
  "Roronoa Zoro - PRB" jogados, mas a remoção da mão removeu a cópia
  errada, deixando a carta realmente jogada ainda lá; numa iteração
  seguinte do Turn Planner ela foi selecionada e jogada DE NOVO, virando
  o MESMO objeto duas vezes em `field_chars` (inflava DON somado e
  board_value — quebrava a invariante "don_available + don_rested +
  don_attached em campo == 10 − don_deck"). Corrigido com 2 helpers de
  identidade (`remove_by_identity`/`contains_identity`,
  `decision_engine.py` ~linha 591) e substituição de ~35 call sites de
  `.remove(card)`/`in`/`not in` em zonas (`hand`, `field_chars`, `trash`,
  `deck`, listas de candidatos temporárias) por versão baseada em `is`,
  SEM tocar em `_remap_action` (continua por valor, de propósito).
  Validado: `smoke_test.py` 100%, `smoke_test_broad.py` 40/40, e
  `audit_replay.py` 25/25 partidas reais sem nenhuma anomalia (antes da
  correção: 6 anomalias de conservação de DON em 2 partidas). O script de
  auditoria foi formalizado como ferramenta permanente em
  `scriptis_da_ia/audit_replay.py` (`python audit_replay.py [--n N]
  [--seed S]`, exit code 1 se achar exceção/anomalia) — útil pra rodar
  depois de qualquer mudança no `decision_engine.py` que não seja
  parser-only, complementar ao `smoke_test_broad.py` (que só checa "não
  lançou excecao", não invariantes de estado).
- [x] ~~Dead code `_main_phase_OLD_fixed`~~ — removido (`decision_engine.py`).
  Versão antiga de `main_phase` (pré Turn Planner), confirmada sem
  nenhuma chamada no código (`grep` não achou uso fora da própria
  definição). Continha um bug de conservação de DON (`don_rested +=
  don_amt` duplicava o valor) que NUNCA foi a causa de nada em produção
  por estar morta — removida só por higiene, sem efeito funcional.

### Achado/corrigido em 28/06/2026, 3ª rodada do dia (fora dos gaps originais)
- [x] ~~`buff_power` target='own_character' não consumido pelo engine~~ —
  achado ao investigar o gap de memória de alvo acima. O parser já gerava
  esse target (15 cartas reais: EB04-009, OP03-039, OP08-018, OP08-019 (x2),
  OP08-095, OP08-103, OP10-092, OP12-001, OP12-016, OP12-018, OP12-019,
  OP13-022, P-011, ST13-001) mas o engine não tinha handler — caía no
  fallback sem aplicar nada (no-op silencioso). Implementado: seleciona
  entre `me.field_chars` (sem filtro de tipo, distinto de
  `select_filtered`) via `eligible_cards`, escolhe o melhor por
  `choose_highest_board_value`. Também corrigido o parser, que não
  capturava os filtros do texto (`power_lte` — "with N power or less",
  `exclude` — "other than [Nome]") — 3 cartas afetadas (OP10-092, OP12-001,
  OP13-022). `PERDEU=0`, smoke tests 100%, testado manualmente (sem
  filtro/com power_lte/com exclude, todos corretos).

### Gaps reais confirmados — 0 (todos resolvidos em 28/06/2026)
- [x] ~~"Memória de alvo entre steps" (`SaveTargetName`)~~ — **implementado em
  28/06/2026**: `EffectExecutor._last_selected` (zerado a cada `execute()`,
  preenchido por `buff_power` `target='select_filtered'`, consumido por
  `select_grant_unblockable_turn`/`lock_self_character_refresh`
  `target='selected'`). Resolveu OP07-057, OP12-077 (residuais de
  `OppNoBlockerThisTurn`) e EB02-021 (residual de Freeze). Exigiu também
  corrigir um bug PRÉ-EXISTENTE de ordem de despacho (sub-parsers do
  `parse_block` não seguem a ordem do texto — `steps.sort()` estável
  garante que quem seleciona executa antes de quem consome) e um bug
  pré-existente de target errado em `parse_power_buff` (padrão "up to N of
  your [Tipo] cards gains +X power" caía em `target='self'` por engano —
  corrigido para `select_filtered` com seleção real por filtro, afetando
  48 cartas que tinham esse padrão, todas verificadas como correção real,
  não regressão). `PERDEU=0`, smoke tests 100%, testes diretos do
  mecanismo (select_filtered + selected, com e sem memória prévia)
  passando. **Atualização (19/07/2026): OP12-016 (Rayleigh, alvo = quem
  recebeu DON!! de um CUSTO, não de um step) foi implementado numa sessão
  posterior** — `target='don_recipient'` em `select_grant_unblockable_turn`
  (`decision_engine.py`) busca por nome (`target_name`) em
  `me.field_chars + [me.leader]`, memória custo→efeito via nome (conhecido
  em tempo de parse) em vez de um slot genérico entre steps. Não era mais
  um gap — a nota acima ficou desatualizada.
- [x] ~~CantPlayAnyCardsFromHand / CantPlayAnyCharactersToField direcionado ao
  oponente~~ — **investigado em 28/06/2026, 0 cartas reais no banco**.
  Buscado "opponent cannot play"/"can't play" em todas as formas — as 18
  cartas com "cannot play" são TODAS auto-aplicadas (custo de ramp de DON,
  já cobertas por `self_cant_play`). O exemplo "Imu" do doc original não
  corresponde a carta real do nosso pool. Não implementar especulativo —
  reabrir só se aparecer carta real.
- [x] ~~Freeze (don/stage/card)~~ — **implementado em 28/06/2026**:
  `frozen_next_refresh` (Card) + `frozen_don_count` (GameState), consumidos
  em `refresh_phase`. Cobre `lock_opp_character_refresh` (18 cartas,
  filtro cost_lte/cost_eq), `lock_opp_don_refresh` (1 carta),
  `lock_self_character_refresh` target='this_card' (1 carta, OP04-090).
  target='selected' (EB02-021) fica no item de memória de alvo acima.
  `PERDEU=0`, smoke tests 100%, testado manualmente (character/stage/DON
  congelados ficam rested 1 refresh e voltam ao normal na seguinte).
- [x] ~~DealDamage/TakeDamage~~ — já implementado (`deal_damage`)
- [x] ~~ShuffleHandIntoDeck / CycleEntireHandToDeckBottom~~ — já implementado
  (`shuffle_hand_into_deck`, parâmetro `dest`)
- [x] ~~OppNoBlockerThisTurn (maior parte)~~ — **implementado em 28/06/2026**:
  parser estendido (`gerar_effects_db.py`, regex `m_block_filtered`) para as
  3 variantes de texto que faltavam (OP11-013 "All", OP12-051 custo, ST21-016
  power). `PERDEU=0`, smoke tests OK. 17 de 20 cartas reais cobertas agora.
- [x] ~~Buff dinâmico (BuffSelf1KPerXTargets/BuffXPerGivenDon/BuffXPerTopDeckCost)~~
  — já estava implementado num commit anterior (`4f41178`) que nunca teve o
  snapshot/db regenerado; feito em 28/06/2026 (`gerar_dbs.py` + novo
  snapshot). 9 cartas corrigidas (estavam parseadas como buff FIXO, errado —
  ex: "+1000 per 3 rested DON" tratava como +1000 sempre).

### Fechado em 29/06/2026 -- 5 gaps medios restantes
- [x] ~~PeekSelfLife/OppLife~~ -- parser gera `peek_life`; engine olha/reordena Life propria ou do oponente com heuristica simples.
- [x] ~~TrashAllFaceUpLife~~ -- `Card.life_face_up` modela face da carta na Life; `gain_life face='up'`, `turn_life_face_up/down` e `trash_own_life face='up'` implementados.
- [x] ~~ForceOpponent~~ -- `choice_chooser='opponent'`, `opp_bounce_own_character` com escolha defensiva/filtro de custo, e `opp_choose_trash_our_hand`.
- [x] ~~QueueUpEndOfTurnAction/OppMainPhase~~ -- `GameState.end_of_turn_queue` + `OPTCGMatch.end_phase()`; cobre `set_active`, `set_don_active`, `gain_life` agendados e Black Maria (`return_don_until_match_opp`). OppMainPhase segue sem carta real prioritaria.
- [x] ~~FieldCantAttackLeader~~ -- `cannot_attack_leader_this_turn` bloqueia ataques ao Leader durante o turno (ex: OP06-026 Koushirou), distinto de `cannot_attack_self`.

Validacao: `python smoke_test.py`; `python audit_replay.py --n 5 --seed 42`; teste direto dos 5 gaps. `smoke_test_broad.py` completo ficou lento demais para fechar em 300s; 10 partidas aleatorias terminaram sem excecao em ~289s (risco/performance a observar).

### "Médios" — resolvidos (SaveTargetName e MatchLeaderToBasePower implementados em 28/06/2026)
- [x] ~~MatchLeaderToBasePower~~ — **implementado em 28/06/2026**: novo campo
  `source` em `set_base_power` (`gerar_effects_db.py`, regex `m_dyn` em
  `parse_set_base_power`), valor calculado em tempo de execução via
  `effective_power()` em vez de `amount` fixo do banco. 3 fontes
  confirmadas: `opp_leader` (5 cartas: EB04-052, OP06-009, OP16-036,
  OP16-055 + dup), `own_leader` (1 carta, OP14-053), `selected_opp_character`
  (2 cartas: EB01-061, OP16-104 — seleção e cópia no MESMO step, sem
  precisar de memória entre steps). `PERDEU=0`, smoke tests 100%, 4
  cenários manuais (opp_leader/own_leader/selected com escolha do melhor
  candidato/sem candidato não quebra). **Atualização (19/07/2026): OP04-069
  implementado numa sessão posterior** — novo `source='opp_attacking_character'`
  + `EffectExecutor.execute(battle_attacker=...)` (contexto de batalha
  threaded desde o call site real de resolução de ataque). Ver
  `parser_audits/2026-07-19_op04-069_base_power_atacante_do_oponente.json`.

Os 5 medios restantes foram fechados em 29/06/2026. Ainda ficam a familia grande
de imunidade e stubs antigos listados abaixo.

### Dívida técnica grande — imunidade
- [x] **Completar auditoria de imunidade — encerrada (01/07/2026).** Em
  29/06/2026 foi confirmado que `ko`/`removal` já têm 52 actions parseadas e
  os caminhos principais chamam `is_immune()`. Corrigido bug de fonte: imunidade
  "by opponent's effects" não protege mais contra efeito próprio. A
  substituição "would be removed/K.O.'d ... instead" foi fechada em
  01/07/2026 (ver entradas acima). Investigação direta de `EffectImmune`/
  `CombatImmune`/`ImmuneToStrikes`: são nomes de MECANISMOS INTERNOS do
  código oficial decompilado (`_referencias/simulador-oficial/`,
  `ActV3Effect.cs`/`GameplayLogicScript.cs`), não padrões de texto
  adicionais nas cartas. Busca direta em `cards_rows.csv` por variantes
  textuais mais amplas ("cannot be affected", "immune to", "cannot be
  targeted/selected/chosen", "unaffected", "ignores effects") não achou
  NENHUMA carta real usando esses padrões além do que `cannot be K.O.'d`/
  `cannot be removed from the field` já cobre — e isso já está
  implementado, incluindo a parte de atributo do atacante (Strike/Slash/
  Special/Wisdom/Ranged/Leaders, que É literalmente "ImmuneToStrikes" na
  prática) feita em 30/06/2026. Confirmado com exemplos reais (OP01-024,
  EB03-018) já parseados corretamente como `action: 'immunity'`. Item
  fechado — não há mais gap de cobertura conhecido nesta família.
- [x] **Imunidade a `rest` forçado — implementada (01/07/2026).** Um
  segundo agente de investigação (disparado em paralelo, voltou depois do
  item acima já fechado) achou um gap real: "cannot be rested by your
  opponent's effects" — autoproteção contra REST forçado, DISTINTA de
  `lock_opp_cannot_be_rested` (que trava o character DO OPONENTE,
  mecânica oposta, beneficia quem ativa — já implementada, sem gap).
  O agente reportou 11 cartas, mas 8 delas (EB02-011, EB03-017, OP11-034,
  OP13-032, OP14-033, OP14-069, OP15-029) já são `lock_opp_cannot_be_rested`
  funcionando — falso positivo do agente por similaridade textual
  superficial ("cannot be rested" aparece nos dois textos com semântica
  oposta). Gap real: só 3 cartas — OP11-046, OP12-021, OP15-024. Novo
  `imm_type='rest'` em `parse_immunity` (`gerar_effects_db.py`), aceita
  também a forma composta "cannot be K.O.'d OR rested by your opponent's
  effects" (OP11-046). `is_immune()` já funcionava genérico pra qualquer
  `imm_type` sem mudança — só documentado. Checagem plugada em
  `rest_opp_character` (`decision_engine.py`), o único ponto real de
  "rest forçado por efeito do oponente" no banco hoje. 4 smoke tests novos.
  Validado com `diff_parser.py` (`PERDEU=0`, exatamente as 3 cartas
  esperadas), `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  exceções, 0 anomalias.
  **Gaps menores não corrigidos** (achados de raspão, baixo
  impacto): OP14-119 (`lock_opp_cannot_be_rested` com gatilho "when this
  Character becomes rested", trigger condicional não reconhecido, perde o
  efeito — **resolvido depois, ver `when_rested` mais abaixo neste
  arquivo**) e OP16-032 (mesma action, exclusão `other than [Nome]`).
  **Verificado em 19/07/2026: OP16-032 NÃO tem mais esse gap** — o regex
  principal de `lock_opp_cannot_be_rested`/`lock_opp_character_attack`
  (`gerar_effects_db.py`) já tem o grupo opcional `(?: other than
  \[([^\]]+)\])?` produzindo `step['exclude']`, e o handler no engine já
  filtra `exclude not in c.name.lower()` antes de escolher o alvo —
  `card_effects_db.json` confirma `exclude: "monkey.d.luffy"` presente.
  Nota antiga ficou desatualizada (o fix genérico de outra carta
  provavelmente cobriu este caso de graça); não havia mais bug real aqui.
- Fatia seguinte feita: KO por efeito e KO em batalha agora passam contexto para
  `is_immune()`, e o helper usa o texto bruto para impedir que imunidade
  `cannot be K.O.'d in battle` proteja contra efeito, ou `by effects` proteja
  contra batalha.
- Fatia seguinte feita (30/06/2026): KO em batalha agora também restringe por
  atributo/fonte do atacante (`Strike`, `Slash`, `Special`, `Leaders`, "by
  Characters without [Special]"). `_source_matches_battle_ko_immunity()` lê o
  atacante (`source_card`) e compara com o texto da sentença de imunidade.
- Auditoria de OP11-005/OP11-046 (30/06/2026): achou um bug de parser, não um
  caso não suportado. `'blocker'` está em `TODAS_TAGS` (delimita os OUTROS
  blocos, que param ao bater em `[Blocker]`), mas não tem `trigger_pattern`
  próprio — então qualquer texto que vem DEPOIS do parêntese de regra do
  Blocker era descartado por inteiro (nem o loop principal, nem o segmento
  solto "antes da 1ª tag", nem o fallback final cobriam esse caso). Afetava
  4 cartas no banco: OP11-005, OP11-046, OP11-088, ST10-014. Corrigido com um
  novo segmento "pós-Blocker" em `parse_card_effect` (`gerar_effects_db.py`).
  De brinde: achado e corrigido um 2º bug — a condição `only_field_type`
  ("if you only have Characters with type X") era parseada desde 29/06 mas
  NUNCA checada nem em `_check_conditions` (EffectExecutor) nem em
  `_immunity_conds_met` (caminho de imunidade) — tratava o efeito como
  incondicional para as 6 cartas que já a usavam (EB02-010, OP05-084,
  OP05-092, OP13-097, OP15-001, OP16-022) além da nova OP11-046. Ambos os
  checkers agora respeitam `only_field_type`. `diff_parser.py` confirmou
  `PERDEU=0`; `audit_replay.py` 0 anomalias (turnos mudaram em 2 das 5
  partidas do seed 42, esperado — comportamento real mudou).
- [x] **`debuff_power` sem handler de execução (30/06/2026):** achado durante
  a auditoria dos Counter events — a action já era reconhecida em
  `_step_is_viable` e em heurísticas de score, mas `_execute_step` nunca
  tinha um `if action == 'debuff_power':` — virava no-op silencioso em TODOS
  os 142 steps reais do banco (on_play 31, when_attacking 27, main 25,
  activate_main 17, counter 14, trigger 10, on_opp_attack 6, demais 12), não
  só em Counter events. Implementado handler espelhando `buff_power` mas do
  lado do oponente, 4 targets: `opp_character`/`opp_leader_or_character`
  (escolhe o alvo mais valioso via `choose_highest_board_value`, com
  `opp_leader_or_character` caindo no Leader quando o campo do oponente está
  vazio), `all_opp_characters` (afeta todos) e `opp_leader` (direto, raro/0
  cartas hoje). Parser nunca emite filtro/count pra esses alvos — sempre 1
  escolha automática. Adicionado também a `safe_extra_actions` dos Counter
  events (objetivo original desta fatia), desbloqueando OP08-017, OP10-018,
  OP12-018, ST29-015. **Bug-side-effect descoberto pelo `audit_replay.py`:**
  com debuff de verdade acontecendo, Characters podiam ficar com power
  negativo (Otama, Jozu na auditoria) — `effective_card_power()`
  (`rules_facade.py`) não tinha piso em 0. Corrigido com `max(0, ...)` no
  retorno (regra real do jogo: power nunca é negativo). Validado com
  `audit_replay.py --n 20 --seed 7`: 0 exceções, 0 anomalias.
- [x] **Counter events: 2º buff battle_only + extras simples (30/06/2026):**
  `_counter_event_power_plan` exigia exatamente 1 `buff_power(battle_only)`.
  Achado: 8 cartas no banco têm 2 (EB03-020, OP04-095, OP05-114, OP06-038,
  OP07-035, OP07-095, OP11-059, OP12-098) — texto real confirma que o 2º
  (sempre `target='self'`) é um BÔNUS condicional ao MESMO alvo escolhido no
  1º ("Up to 1 of your Leader or Character cards gains +X power... Then, if
  [cond], **that card** gains an additional +Y power"), não um 2º alvo
  independente. Generalizado para somar quantos `buff_power(battle_only)`
  existirem, desde que os adicionais tenham `target='self'` (aplica o bônus
  só se a condição do step passar; se não tiver condição, soma sempre).
  Também adicionados a `safe_extra_actions`: `trash_from_deck_top`,
  `peek_life`, `add_from_trash`, `gain_life` — ações simples com handler
  genérico já existente, sem seleção complexa. Desbloqueia OP03-054,
  OP03-055, OP08-096 (trash_from_deck_top), ST07-016, ST13-017 (peek_life),
  OP11-097, OP12-115 (add_from_trash), ST09-015 (gain_life). Cobertura de
  Counter events com `buff_power(battle_only)` subiu de 102/180 pra 114/180.
  Ainda fora: `play_card`/`play_from_deck` (7), `look_top_deck`+`add_to_hand`
  (2, busca complexa), os 44 sem nenhum buff `battle_only` (padrões
  totalmente diferentes: KO puro, debuff puro do atacante, bounce puro já
  coberto, etc.) — ver auditoria detalhada no HANDOFF.md de 30/06/2026 (4).
- [x] **Counter events: duration='this_turn' + select_filtered (30/06/2026):**
  dos 44 sem `buff_power(battle_only)`, 14 tinham SO um `buff_power` com
  `duration='this_turn'` (nao `battle_only`) — o planner exigia
  `battle_only` estritamente. Como o Counter Step so acontece DENTRO da
  resolucao da batalha em curso, e o resto do engine ja trata as duas
  durations de forma identica na limpeza (reset de `power_buff` no inicio do
  turno), ampliei o filtro pra aceitar as duas. Desbloqueia 5 cartas com
  `target` ja suportado (leader/leader_or_character): OP04-037, OP04-076,
  OP06-017, OP09-039, OP13-077. As outras 9 usam `target='select_filtered'`
  ("Up to 1 of your [Tipo] Leader or Character cards gains +X power") —
  adicionado como novo `target_rule`, mas so conta como defesa valida se o
  ALVO REAL sob ataque bater no `filter_type` (via `card_matches_filter`);
  senao a carta buffaria outro aliado que nao impede o hit desta batalha.
  Desbloqueia EB03-029, EB04-019, EB04-029, OP07-018, OP14-117, OP15-038,
  OP15-074, OP15-075, OP15-076. Cobertura subiu de 114/180 pra 128/180.
  Validado com `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  excecoes, 0 anomalias.
- [x] **Counter events que enfraquecem o ATACANTE (30/06/2026):** mecanica
  distinta de tudo anterior — em vez de buffar a propria defesa,
  "[Counter] Give up to 1 of your opponent's Leader or Character cards -X
  power during this turn" reduz o `atk_power` do atacante diretamente. Nova
  funcao `try_counter_event_debuff` + `_counter_event_debuff_plan` em
  `decision_engine.py`, chamada como fallback no fluxo de batalha logo apos
  `try_counter_event_power` nao bastar (`atk_power -= amount`, mutando
  `attacker.power_buff` de verdade, nao so o calculo de defesa). Escopo
  minimo e deliberado: exige EXATAMENTE 1 `debuff_power` no bloco `counter`
  e nenhum outro step. Desbloqueia OP01-028, OP03-017, OP07-075, OP15-021,
  ST09-014 (5 cartas). Validado com `audit_replay.py --n 20 --seed 7` e
  `--n 15 --seed 99`: 0 excecoes, 0 anomalias.
  **Atualização (19/07/2026), ambiguidade de alvo resolvida:** OP02-089
  ("total of 2... -3000") na verdade já funcionava sem mudança nenhuma —
  é um ÚNICO step com `count=2` (não 2 steps sequenciais), e a função
  nunca checava `count`; a nota de "distribuição ambígua" estava
  desatualizada. OP04-017 (2 debuffs sequenciais, o 2º condicionado a
  "if your Leader is active") e OP09-097 (`debuff_power` combinado com
  `negate_effect`) foram generalizados: `_counter_event_debuff_plan`
  agora itera por TODOS os steps do bloco `counter`, soma o `amount` de
  cada `debuff_power` aplicável (mesma leitura assumida — todo debuff do
  bloco mira o MESMO alvo, o atacante, única leitura sem ambiguidade real
  já que um Counter só se joga durante a batalha em curso) e ignora
  `negate_effect` (fora do escopo desta simplificação). Achado colateral:
  a condição "if your Leader is active" nunca era parseada — novo
  `conditions['leader_state']` (parser) + branch em `_check_conditions`
  (engine), genérico pra "active" ou "rested". Ver
  `parser_audits/2026-07-19_counter_event_debuff_2_steps_op04-017_op09-097.json`.
- [x] **KO via Counter event (30/06/2026):** implementado — terceiro
  mecanismo de Counter event, distinto de buffar a propria defesa e de
  debuffar o atacante. "[Counter] K.O. up to 1 of your opponent's
  Characters with cost/power N or less[, rested only]" remove o atacante
  inteiramente ANTES do dano, cancelando o ataque por completo (sem
  comparacao de power). Novas funcoes `_counter_event_ko_plan` +
  `try_counter_event_ko_attacker`, chamadas no fluxo de `_resolve_attack`
  logo apos o debuff do atacante nao bastar e antes do Damage Step; se
  ativar, `return False` direto (ataque cancelado). Respeita
  imunidade/substituicao do atacante (mesma checagem do 'ko' generico,
  `ko_context='effect'`). `rested_only` e trivialmente satisfeito (o
  atacante ja fica `rested=True` ao declarar o ataque, bem antes do Counter
  Step). Escopo minimo: exige EXATAMENTE 1 step 'ko' com
  `target='opp_character'` e nenhum outro step. Desbloqueia as 4 cartas:
  EB01-010, OP08-094, OP10-040, OP13-039. Validado com `audit_replay.py
  --n 20 --seed 7` e `--n 15 --seed 99`: 0 excecoes, 0 anomalias.
- [x] **Counter events: buff + play_card/busca em deck (30/06/2026):**
  ultima fatia da auditoria de Counter events. `play_card`, `play_from_deck`,
  `look_top_deck`, `add_to_hand`, `deck_bottom_rest` ja tinham handler
  generico (usados em on_play/trigger/etc.) — adicionados a
  `safe_extra_actions` como bonus de valor junto de um buff `battle_only`
  que ja defende sozinho (mesmo raciocinio dos extras anteriores: o buff e
  o que importa pra decisao, a busca/play e so ganho extra). Desbloqueia
  EB01-019, EB02-059, OP01-088 (exceto a parte de `deck_reorder_rest`, ver
  abaixo), OP02-045, OP05-018, OP08-054, OP08-115, OP14-116, ST12-017 (8 de
  9 cartas do grupo).
  **Achado novo, nao corrigido:** `deck_reorder_rest` (1 carta, OP01-088:
  "look at 3 cards from top, place at top or bottom in any order") e
  parseada e referenciada em `_step_is_viable` mas NUNCA teve handler de
  execucao — mesmo padrao do bug do `debuff_power` (achado 30/06/2026,
  sessao anterior), so que aqui afeta 1 unica carta. Deixado de fora desta
  fatia por escopo (baixo impacto), registrado aqui pra nao se perder.
  **Deliberadamente fora de escopo:** os 4 Counter events SEM nenhum buff
  que so jogam/buscam carta (EB01-009, OP01-087, OP04-036, OP10-078) — nao
  swingam `defend_power`/`atk_power` de jeito nenhum, entao nao cabem no
  framework de "isso impede o hit". Tratá-los exigiria um criterio de
  decisao totalmente diferente ("vale a pena gastar DON/carta por puro
  valor, mesmo sem impedir o ataque?"), fora do escopo desta auditoria.
  Cobertura final de Counter events com buff: 128/180 pra 136/180.
  Validado com `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  excecoes, 0 anomalias.
- [x] **Substituição externa — executor/filtro: fechado.** Auditoria de
  29/06/2026 achou ~38 textos onde uma fonte em campo/líder protege outro
  alvo (`if your Character would be removed/K.O.'d...`). Implementado em
  fatias: `try_any_substitute()` separa `target`/`source`, parser extrai
  filtros estruturados do alvo protegido (`filter_name`, `filter_color`,
  `filter_type`, `cost_lte`/`gte`, `power_eq`/`lte`/`gte`, `exclude`).
  `EB02-030` (Counter event) ganhou suporte estreito próprio. Eventos
  `[Counter]` com buff defensivo + extras (draw, set_active,
  rest_opp_character, add_don, KO, bottom-deck, debuff do atacante, KO do
  atacante, play_card/busca em deck) ficaram prontos na sequência de
  30/06/2026 — ver entradas de HANDOFF.md daquele dia. Auditoria de
  01/07/2026 confirmou: 21 de 33 steps de substituição têm filtro
  estruturado; os 12 sem filtro são todos self-referentes (10 `this
  Character` + OP07-042 self composto + EB02-030 já coberto) — **não havia
  bug de "fonte externa sem filtro protegendo qualquer alvo"**:
  `_target_matches_external_substitute` já bloqueia (retorna False) quando
  um step não tem NENHUM filtro estruturado, comportamento seguro
  confirmado por leitura direta do código.
- [x] **Substituição externa — gap real de PARSER achado e corrigido
  (01/07/2026):** a auditoria de 01/07 achou que `parse_substitute_ko` e
  `parse_substitute_removal` tinham listas de padrões de custo PARALELAS
  mas DESSINCRONIZADAS — vários padrões existiam só numa das duas funções
  (`return_own_don` só em removal, `trash this character instead`/`rest
  this character instead` só em KO). 17 cartas reais com texto "would be
  removed/K.O.'d ... instead" ficaram sem NENHUMA action `substitute_*`
  parseada por causa disso. Corrigido com `_parse_substitute_cost()`
  (`gerar_effects_db.py`), função única compartilhada pelas duas, união de
  todos os padrões de custo + 2 bugs extras corrigidos na mesma auditoria:
  "you CAN [custo] instead" (regex só aceitava "you MAY") e variante
  power-or-less pro `trash_from_hand` (só existia power-or-more, e em duas
  redações: "N power or less" e "a power of N or less"). Desta fatia, 6
  cartas fechadas com cobertura completa (custo + alvo, quando aplicável):
  EB04-030, EB04-031 (`return_own_don` para KO), EB04-044 (verbo "can"),
  OP15-003 (`trash_from_hand` power_lte), OP12-027 (substituição EXTERNA,
  precisou de filtro novo `filter_attribute` pra Slash/Strike/Special/
  Wisdom/Ranged), OP15-094 (substituição EXTERNA — achado bônus: o
  early-return de "this character" em `_apply_substitute_target_filters`
  descartava o filtro de tipo inteiro quando o texto era "X type Character
  OTHER THAN this Character", tratando como self-target por engano; a
  exclusão de si mesma já é garantida estruturalmente pelo executor
  — `sources = [c for c in self.me.field_chars if c is not target]` — então
  só precisava parar de descartar o filtro). 8 smoke tests novos.
  Validado com `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0
  exceções, 0 anomalias.
- [x] **Substituição externa — 11 das 13 cartas pendentes fechadas
  (01/07/2026):** 7 cost-types novos em `_pay_substitute_cost`:
  `rest_leader` (OP04-082, ignora a alternativa de stage nomeado),
  `rest_own_filtered` (OP10-037, OP11-110 — rest 1 Character próprio de um
  tipo específico, ignora a alternativa "ou Leader" de OP11-110),
  `rest_own_character` (OP14-034, externa), `rest_own_card` (OP14-029;
  OP15-035, externa, count=2), `life_to_hand` (OP10-034, OP12-061),
  `life_to_trash` (ST09-010, ST20-002), `trash_to_deck_bottom` (OP14-092).
  Parser: novos padrões em `_parse_substitute_cost`. **Bônus reais
  encontrados pelos mesmos padrões** (cartas fora da lista original, todas
  confirmadas corretas por leitura do texto bruto): EB04-043 (`filter_color`
  black + cost_lte 5 + `trash_to_deck_bottom`), **OP11-001** (Leader Koby —
  primeira fonte de substituição que é um Leader, já funciona sem mudança
  de engine porque `try_any_substitute()` já incluía `self.me.leader` na
  lista de fontes externas), OP15-098, OP15-105 (`life_to_hand`).
  **2 bugs estruturais achados e corrigidos na mesma fatia:**
  (1) `parse_substitute_ko`/`parse_substitute_removal` reivindicavam o
  BLOCO INTEIRO de texto ao achar a cláusula de substituição, descartando
  silenciosamente qualquer efeito incondicional que viesse ANTES dela no
  mesmo bloco (ex: OP14-034 perdia um `buff_power` que vinha antes do texto
  de substituição sob a mesma tag `[Your Turn]`) — corrigido extraindo o
  prefixo e reparseando via `parse_block` recursivo; corrigiu também
  ST25-003 (achado bônus, perdia `draw`+`play_card`) sem nenhuma
  intervenção minha além de generalizar o fix. (2) `try_substitute()` e
  `_substitute_source_blocks()` só checavam a chave `'passive'`, mas cartas
  com a tag formal `[Opponent's Turn]`/`[Your Turn]` ANTES da cláusula de
  substituição (ex: OP14-029, OP14-092, OP14-034) fazem esse timing virar a
  chave de topo no parser, não `passive` — mesmo padrão que `is_immune()`
  já tratava corretamente. Ambas agora iteram `('passive', 'opp_turn',
  'your_turn')`. 11 smoke tests novos. Validado com `diff_parser.py`
  (`PERDEU=0`), `audit_replay.py --n 20 --seed 7`, `--n 15 --seed 99` e
  `--n 25 --seed 321` (0 exceções, 0 anomalias nas três).
- [x] ~~Substituição externa — OP07-029 e OP16-014~~ — **implementados em
  02/07/2026** (ver commits anteriores desta sessão).

---

## 🔴 FILA ANTERIOR ainda aberta

### Stubs sem lógica de decisão
- [x] ~~choice (19) — heurística de valor~~ — JÁ IMPLEMENTADO (auditoria
  01/07/2026, este item estava desatualizado). `_resolve_choice`
  (`decision_engine.py:853-897`) tem heurística de valor real por peso de
  ação (`attack_life`=4, `trash_opp_life`/`place_opp_character_bottom_deck`=3,
  `ko`/`trash_character`/`gain_life`=2, `bounce`/`draw`=1), filtra por
  viabilidade e escolhe a opção de maior score (menor se `chooser='opponent'`).
  Consumido em `execute()` e no passive-loop. Contagem real: 17 cartas (não
  19). Smoke tests dedicados em `smoke_test.py:120-161`.
- [x] ~~conditional_stack (OP15-092) — custo-benefício por threshold~~ — JÁ
  IMPLEMENTADO (auditoria 01/07/2026). `decision_engine.py:1610-1613` itera
  `conditional_stack`, checa `conditions` de cada item via
  `_check_conditions` e ACUMULA (`extend`) os blocos que passam — cumulativo,
  não exclusivo. 1 carta confirmada (OP15-092), igual ao TODO. Smoke test em
  `smoke_test.py:161-184`.
- [x] ~~set_base_power (8) — integrar em effective_power()~~ — JÁ
  IMPLEMENTADO (auditoria 01/07/2026, contagem estava desatualizada).
  Handler completo em `decision_engine.py:2512-2566`: resolve target
  (self/leader/own_character/leader_or_own_character), filtra por
  `filter_type`, seta `card.base_power_override`, consumido por
  `effective_card_power` (`rules_facade.py`). Inclui caso dinâmico
  (`source=opp_leader/own_leader/selected_opp_character`, achado
  28/06/2026). Contagem real: 15 cartas (não 8 — dobrou desde a estimativa
  original).
- [x] **lock_opp_attack_unless_pays (OP08-043) — implementado (01/07/2026):**
  campo novo `Card.attack_paywall` (dict `{cost_type, cost_amount, until}`,
  resetado em `refresh_phase` junto com `cannot_attack_until` — mesma
  simplificação de duration já usada lá). Execução do step seleciona TODOS
  os Characters do oponente no campo no momento (texto real: "select all of
  your opponent's Characters", sem escolha — `count=99`). Novo helper
  `can_afford_attack_paywall(card, owner)` adicionado aos 5 pontos que já
  filtravam `not c.cannot_attack_until` como "pode atacar"
  (`my_attack_power`, geração de ações de ataque em 3 lugares, Turn
  Planner) — simplificação deliberada: paga sempre que a mão tem cartas
  suficientes, sem modelar "vale a pena" (mesmo padrão do resto do engine
  pra custos de ativação, evita reabrir a fase "Opponent Reading" só por
  causa de 1 carta). Pagamento real acontece em `_execute_attack` no
  momento de declarar o ataque (trasha as N piores cartas da mão por
  `board_value`). 4 smoke tests novos: trava aplicada a todos os
  characters, `can_afford_attack_paywall` com/sem paywall e mão
  insuficiente, e integração real via `OPTCGMatch._execute_attack`
  confirmando o trash automático. Validado com `audit_replay.py --n 20
  --seed 7` e `--n 15 --seed 99`: 0 exceções, 0 anomalias.
- [x] **deck_reorder_rest / deck_top_rest — implementado (01/07/2026):**
  achado importante durante a implementação: `deck_top_rest` é um nome de
  action EQUIVOCADO do parser (`gerar_effects_db.py:467-470`) — o regex
  casa o prefixo `'place the rest at the top'` antes de checar o sufixo
  `'or bottom'`, então TODA carta real com texto "place the rest at the top
  or bottom of the deck in any order" cai em `deck_top_rest` em vez de
  `deck_reorder_rest`. Confirmado varrendo `cards_rows.csv`: nenhuma das 5
  cartas de `deck_top_rest` (OP02-057, OP05-043, OP08-053, OP11-040,
  OP11-104) tem texto "top" sem "or bottom" — são o MESMO mecanismo de
  `deck_reorder_rest` (escolha livre de ordem/posição), só com nome
  diferente. Não vale a pena tocar o parser/regenerar DBs só por causa do
  nome — as duas actions agora compartilham o mesmo handler em
  `_execute_step`. Heurística (mesmo princípio do `peek_life` 'all'): a IA
  bota a carta mais valiosa de volta no topo do deck (próxima a ser
  comprada), o resto fica ordenado por `board_value` crescente abaixo dela.
  Também adicionadas a `safe_extra_actions` dos Counter events — desbloqueia
  OP01-088 (que tinha ficado de fora na fatia de Counter events por causa
  desse handler faltando). 3 smoke tests novos (deck_reorder_rest,
  deck_top_rest, integração via Counter event OP01-088). Validado com
  `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0 exceções, 0
  anomalias.
- [x] **cannot_attack_self / cannot_attack_self_unless /
  cannot_attack_own_characters_by_cost (01/07/2026) — já estava
  implementado, só faltava teste:** não era item formal do TODO.md, só um
  comentário inline em `decision_engine.py` dizendo "reconhecidas sem
  travar nada ainda" (6 cartas: Oars, Luffy OP11-058, Wadatsumi, P-084
  Buggy, Trafalgar Law EB04-005, Emet EB04-051). Auditoria confirmou que
  `is_attack_locked_self()` já lê `effects['passive']`/
  `mass_lock_conditional` direto do banco (sem depender de execução) e já
  estava plugada nos 5 pontos de "pode atacar" — a trava JÁ funcionava.
  O placeholder em `_execute_step` não bloqueava nada, mas também não era
  morto: `apply_your_turn_buffs()` roda todo step de `'passive'` (não só
  buffs), então gerava um log confuso de "não implementado" todo turno
  mesmo a trava real já estando ativa em paralelo. Trocado por `return ''`
  silencioso + comentário corrigido. 6 smoke tests novos cobrindo os 3
  sub-mecanismos. Validado com `audit_replay.py --n 20 --seed 7` e `--n 15
  --seed 99`: 0 exceções, 0 anomalias.

### Reserva de DON em combate
- [x] ~~plan_don_distribution não subtrai reserva defensiva (usa don_available cru)~~
  — STALE, já corrigido (auditoria 01/07/2026). `decision_engine.py:4678-4778`
  já chama `_don_reserve_for_defense()` (linha 4720) e subtrai do
  `don_available` antes de distribuir DON nos modos CLEAR FIELD/NORMAL — só
  ignora a reserva no modo LETHAL deliberadamente (decisão confirmada pelo
  usuário em 27/06/2026: "ir pro lethal vale mais que guardar DON").
- [x] ~~on_opponent_attack timing não existe (72 cards em "passive")~~ —
  STALE, já corrigido em 27/06/2026 (confirmado de novo em 30/06/2026 durante
  a auditoria de Counter events). O timing `on_opp_attack` já existe no
  parser (`gerar_effects_db.py:3160`) e já é executado em
  `_resolve_attack` (`decision_engine.py`, `ee_react.execute(reagente,
  'on_opp_attack')`, ANTES de calcular `atk_power` — necessário pra debuffs
  do tipo Izo EB01-002 valerem nesta batalha).

### Turn Planner
- [x] ~~can_lethal_this_turn ainda cheata lendo self.opp.hand para counters~~ —
  corrigido em 29/06/2026. Agora usa counters revelados + estimativa por tamanho
  de mão oculta.
- [x] **5 funções órfãs — deletadas (02/07/2026).** Na contagem real eram 6
  (mais `_mulligan_decision` que parecia orfã mas é chamada por
  `replay_optcg.py` — restaurada depois de deletada por engano). As 5
  efetivamente mortas e removidas: `_count_available_attacks` (GameAnalyzer),
  `choose_card_to_play` (DecisionEngine, supersedida pelo Turn Planner),
  `plan_don_distribution` (DecisionEngine, idem), `plan_attacks`
  (DecisionEngine, idem), `_distribute_don` (OPTCGMatch). -345 linhas.
- [ ] Otimização estrutural de performance: reduzir `deepcopy` no Turn Planner
  ou cachear cálculos caros (`_don_reserve_for_defense`, defesa/counter,
  geração de ações). Em 29/06/2026 foi feita só uma poda de orçamento
  (`max_steps=8`, Monte Carlo=6) para recuperar o tempo do broad; não é a
  solução definitiva. Em 02/07/2026 foram feitas 2 otimizações menores de
  `deepcopy` em `GameState.__deepcopy__`: (a) `full_deck_census` agora é
  compartilhado por referência (é invariante durante o jogo, jamais mutado
  — economiza deepcopy de dict de ~50 entradas por clone); (b) `opp.deck`
  em `_simulate_sequence_once` é copiado como lista rasa (não deepcopy de
  cada Card) pois o oponente não age durante a simulação do turno ativo —
  economiza ~0.5-0.7ms por chamada. A dívida estrutural mais profunda
  (clone incremental ou cache de avaliações) permanece aberta.

### Parser — cobertura
- [x] **cartas com card_text mas effects vazio — revalidado e parcialmente
  corrigido (2 rodadas: 02/07/2026).** Total atual: **2314/2614 com efeito**
  (era 2148 antigo → 2286 após rodada 1 → 2314 após rodada 2). **24 gaps
  reais restantes** — maioria exige mecânica genuinamente nova: swap de
  poder (OP14-001/017), redirect ataque (OP14-060), trigger reativo ao descarte
  do oponente (OP12-040 Kuzan), "end of battle" trigger (OP04-047/ST08-013),
  adicionar character do oponente à vida dele (OP04-097/OP05-111/EB02-057),
  etc. Ver HANDOFF.md (6) para lista completa e categorização.
- [x] **cartas com card_text mas effects vazio — revalidado (02/07/2026).**
  Contagem anterior "2148 com efeito" estava desatualizada. Resultado atual:
  **2286/2614 com efeito** (+138 desde o início da sessão). Gaps restantes
  reais: **~54 cartas** (excluindo NULL, variantes de ID e cards erratados),
  classificados em 3 grupos: (A) falsos positivos de ID de variante (9 cards
  — efectivamente parsed sob ID canônico); (B) mecânicas novas que requerem
  design próprio (~30+: swap de poder, redirecionar ataque, triggers de
  "opponent trashes from hand", "set power to 0", play específico por nome
  do deck, etc.); (C) gaps de parser menores corrigidos nesta auditoria (9
  cartas novas: `gain_can_attack_active` com variante "your opponent's
  active" — OP01-021, OP02-014 + 1 bônus; `give_don` com target-first —
  ST01-001 + 6 bônus em cartas existentes; `opp_place_trash_bottom_deck`
  player-iniciado — OP15-091; `rest_opp_character` sem "up to" e com "cards"
  — P-008, OP13-033; `play_from_trash filter_self` em on_ko — P-071;
  set_active+set_don_active combinado — OP13-035). Mecânicas do grupo B
  listadas em item separado abaixo conforme aparecerem prioritárias.
- [x] **opponent has N+ DON — implementado (02/07/2026), 8 cartas exatas
  (EB02-061, OP02-089, OP02-090, OP02-091, OP08-060, OP14-063, PRB02-010,
  ST26-005).** Novo `opp_don_on_field_gte` em `parse_conditions`
  (`gerar_effects_db.py`), simétrico a `don_on_field_gte` mas sobre o
  campo do OPONENTE. Infra de `conditions` já era genérica (anexada por
  entry/step, checada em `_check_conditions` antes de executar) — só
  faltava o regex; nenhuma mudança extra de engine necessária além de
  plugar a chave em `_check_conditions` (linha ~1792) e no pre-filtro do
  Turn Planner (linha ~4686). Achado real: OP02-089/090/091 tinham o
  trigger "opponent returns 1 DON!! card" **sem gate algum** — disparava
  sempre, mesmo com oponente em 0 DON. `PERDEU=0`, 8/8 mudanças
  corretas no diff, 2 smoke tests novos, `audit_replay.py --n 20 --seed 7`
  e `--n 15 --seed 99`: 0 exceções, 0 anomalias.
- [x] **place-at-bottom-of-deck — implementado (02/07/2026), 13 cartas
  (EB03-026, EB04-022, EB04-025, OP05-079, OP06-044, OP06-092, OP07-047,
  OP08-046, OP11-072, OP11-091, OP15-048, P-048, OP16-047).** Escopo real
  era mais amplo do que o "~14" original sugeria — boa parte do que
  apareceu numa busca textual ampla por "bottom of deck" já estava
  coberta (`deck_top_rest`/`deck_reorder_rest`/custos de trash-pro-fundo
  já existentes). O gap genuíno era uma família nova e coerente:
  disrupção FORÇADA no oponente com destino o FUNDO DO PRÓPRIO DECK dele
  (nunca trash) — 2 actions novas em `decision_engine.py`:
  `opp_place_hand_bottom_deck` (fonte = mão do oponente, escolhe a pior
  carta por `_choose_to_trash`, mesma heurística de `opp_trash_from_hand`)
  e `opp_place_trash_bottom_deck` (fonte = trash do oponente, aceita
  `filter_type='event'` p/ OP11-091). Parser estendido em
  `parse_opp_self_move_character` (`gerar_effects_db.py`), reconhece
  variantes de redação "your opponent places/must place" e "they place"
  (OP16-047, gatilho já deixa "opponent" implícito antes). Bônus: achado
  no caminho que OP06-092 (Brook) tinha uma estrutura `Choose one:` com
  bullet corrompido (`�` em vez de `•` no `card_text` bruto) que já
  era reconhecida pelo split de `parse_block` — só faltava a 2ª opção
  (`opp_place_trash_bottom_deck`) ter parser pra virar uma `choice` de
  verdade em vez de cair no fallback de "só a 1ª opção conta".
  `PERDEU=0`, 7 GANHOU + 6 MUDOU = 13/13, 2 smoke tests novos,
  `audit_replay.py --n 20 --seed 7` e `--n 15 --seed 99`: 0 exceções, 0
  anomalias.
- [x] **opp_hand_gte — corrigido (02/07/2026), 13 cartas.** Item acima
  tinha ficado registrado como "simplificação consciente" (ação dispara
  sempre, mesmo com a mão do oponente abaixo do limiar — só coincidia com
  a regra real quando a mão estava em 0). Usuário pediu correção
  explícita: "não pode ser simplificado porque interfere na partida".
  Nova condição `opp_hand_gte` em `parse_conditions` (mesmo molde de
  `hand_gte` já existente, mas sobre `opp.hand`), plugada em
  `_check_conditions` e no pre-filtro do Turn Planner. Escopo real maior
  do que os 5 cards de place-at-bottom-of-deck — o mesmo gap afetava TODA
  a família `opp_trash_from_hand`/`attack_life` com esse prefixo
  condicional: EB02-045, EB03-026, EB04-022, OP05-082, OP06-093,
  OP07-047, OP08-046, OP09-087, OP10-087, OP10-118, OP12-087, OP16-047,
  ST13-009. `PERDEU=0`, 13/13 MUDOU (só ganharam o gate, nenhum efeito
  novo nem perdido), 4 smoke tests novos (2 unidade + 2 end-to-end via
  carta real OP08-046 abaixo/no limiar), `audit_replay.py --n 20 --seed 7`
  e `--n 15 --seed 99`: 0 exceções, 0 anomalias.
- [x] ~~OP15-074 Varie — DON sem sinal, aguarda foto~~: **resolvido
  (19/07/2026).** Foto confirmada pelo usuário mostra `DON!! −1:` explícito
  no texto real da carta — o parser já produz `don_minus` count=1/
  optional=False corretamente. Não era bug, só uma dúvida de dado bruto
  pendente de confirmação visual.
- ~~OP14-119 (Mihawk) — trigger "becomes rested" sem parser~~: **resolvido
  (02/07/2026).** Novo timing `when_rested` no parser (`gerar_effects_db.py`,
  trigger_patterns antes de `your_turn`, com lookahead negativo pra evitar
  duplicar o mesmo bloco como `your_turn`). 6 cartas afetadas: OP14-021,
  OP14-027, OP14-028, OP14-032, OP14-035 (antes ficavam como `your_turn`,
  disparavam passivamente no início do turno) + OP14-119 (estava totalmente
  vazia — também tinha o typo "cost or 9" em vez de "cost of 9" no CSV, regex
  do parser corrigido para aceitar ambos). Engine: `when_rested` disparado em
  `_execute_attack` após restar o atacante (único ponto de resting durante o
  turno ativo que cobre todos os casos práticos; resting via custo de
  Activate:Main não dispara — simplificação documentada, sem carta real
  afetada hoje).

---

## ⚠️ SEGURANÇA — antes de deploy público
- [ ] Rotacionar chaves Supabase (service_role exposta). Migrar p/ sb_secret/sb_publishable.

---

## 📚 REGRAS (NUNCA quebrar)
- K.O. ≠ Trash · Rush ≠ Rush:Character · give_don_opp tira do próprio
- Sinal de custo só com texto explícito · play_card do efeito = GRÁTIS
- Pagar custo só se algum step produz efeito (viabilidade ampla, 25/06)
- Topo do deck = fim da lista (pop()) — confirmado no source do simulador
- Mill do deck = trash seco (sem trigger)

### Workflow
```
# parser: snapshot → fix → diff PERDEU=0 → gerar_dbs → re-snapshot → commit
# engine puro: editar → partida real instrumentada → commit (sem gerar_dbs)
# NUNCA git add -A · commit single-line (CMD)
```

---

## 📊 BANCO DE LOGS — análise estatística (planejado)

Banco de partidas reais em `scriptis_da_ia/logs/` (arquivos nomeados por líder+cor).
Uso: `python parse_combat_log.py partida.log --summary --add-to-db`

### Próximos usos planejados (em ordem de prioridade)

- [x] **Comparação IA vs humano** — `compare_vs_human.py` implementado. Reconstrói
  GameState do snapshot, roda Turn Planner, mostra divergências turno a turno.
  **Próximos fixes identificados (01/07/2026):**
  - [ ] Reconstrução de estado usa snapshot do fim do turno (pós-ação) em vez do
    início do turno — gera falsos positivos onde IA "quer atacar" com chars que
    já atacaram. Fix: usar snapshot do turno ANTERIOR como estado inicial.
  - [ ] Activate do Imu supervalorizado no early (DON=1-2, campo vazio): IA prefere
    activate a jogar Shalria no T01 (mutuamente exclusivos com 1 DON). Penalizar
    `_score_activate_main` quando campo vazio e poucos DON.

- [ ] **Win rate por matchup** — filtrar `logs/decks/` e `logs/index.json` por líder.
  Ex: quantas partidas Teach-BY × Lucy-RB existem, e qual a taxa de vitória de cada lado.

- [ ] **Curva de vida por turno** — média de vida restante em cada turno por líder.
  Ajuda a entender ritmo de jogo e quando o matchup costuma ser decidido.

- [ ] **Deck popularity por líder** — quais cartas aparecem em mais listas do mesmo líder.
  Base para calibrar heurísticas de valor de carta por arquétipo.

- [ ] **ML (futuro)** — behavioral cloning a partir do que os humanos fazem em cada
  estado. Só faz sentido depois de ter volume (50+ partidas) e de a base heurística
  estar afinada. Não antes.

---

## ROADMAP
1. Consertar lógica — EM ANDAMENTO (vários blocos fechados nesta sessão)
2. Auditar via replay — iniciado (Imu vs Sanji revelou Problemas 1/2/3)
3. Tunar heurísticas por simulação em volume — AQUI MORA QUASE TODO O GANHO
   3a. Comparação IA vs humano via banco de logs reais (ver seção acima)
4. ML — só se 1-3 prontos e baterem teto. Descartado por ora (25/06): herdaria bugs de
   execução; não "aprende conforme ensina" — quem faz isso é o parser por mecânica.
