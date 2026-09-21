# TODO — Analisador de Decks OPTCG

**Última atualização:** 21 de setembro de 2026 (bloco 882)

> **5 MELHORIAS DE ML implementadas (bloco 882)**, a pedido do usuario apos
> pesquisa externa (AlphaZero, NNUE, Prioritized Experience Replay, pool de
> adversarios): (1) `_forward_rapido` -- inferencia numpy 3,1x mais rapida
> que `Pipeline.predict()`, validada por igualdade numerica; (2) pool de
> adversarios historicos no self-play (`--pool-dir`/`--pool-frac`, 25%);
> (3) busca do professor mais profunda (6/3/3 -> 8/4/4, ~2x mais cara,
> aceitavel); (4) replay priorizado por erro no treino do Q (`--priorizar`,
> default ligado); (5) volume de self-play por ciclo 40 -> 200 partidas
> (ainda ordens de grandeza abaixo do minimo AlphaZero-scale, mas passo
> pratico). **NENHUM ciclo completo rodado com os 5 juntos ainda** -- cada
> item foi validado ISOLADO (custo medido, numero bate, nao quebra), nao
> houve duelo provando que o CONJUNTO joga melhor. **PROXIMO PASSO**: rodar
> `ciclo.py --partidas 200` e comparar contra o historico do bloco 881.
>
> **ACHADO NOVO, FORA DO ESCOPO DOS 5 ITENS, NAO CORRIGIDO**: o AS-IS pos-
> mudanca mostrou que o maior custo de tempo (55% de uma partida) NAO vem do
> Q (`q_net.joblib`, ja acelerado pelo item 1) -- vem de
> `metrics/value_net_aluno.joblib`, o modelo que ORDENA o shortlist antes da
> decisao final (`_ordena_pelo_modelo`), que ainda e `HistGradientBoosting-
> Regressor` (arvores, lento) em vez de rede. Retreinar esse arquivo como
> rede exigiria adicionar `--modelo rede` em `treinar_value.py` (hoje so tem
> HistGradientBoosting*) -- nao decidido nem feito, fica pra quando o
> usuario quiser.

> **DIAGNOSTICO DO TREINO OFFLINE (bloco 881): 9 ciclos, ZERO promocoes,
> sempre.** `ciclo_estado.json` mostra 8/9 "INCONCLUSIVO (teto de pares)" --
> `ciclo.py` capa o portao em 60 pares e ~75% saem divididos (matchup decide,
> nao o modelo), sobrando pouco pro SPRT decidir. Erro Q fora da amostra SOBE
> 6 ciclos seguidos (0,0498->0,0581). **Hipotese "corpus mistura 2 criterios
> de rotulo" foi TESTADA E DERRUBADA**: treinar so com o rotulo 'busca' (mais
> confiavel, mas so 95k linhas) PERDEU 0x9 em duelo real contra o corpus
> inteiro misturado -- ver entrada nova em `REPROVADOS.md`. **Achado grave**:
> o guarda-corpo de semelhanca com humano nunca rodou desde que o Q virou
> decisor unico (13/09), porque so dispara apos promocao e nunca houve uma.
> Medido direto agora: `play` caiu de 43,5% (era heuristica) pra 33,0%,
> `attach_don` de 23,5% pra 9,9-18,0% -- queda ampla, ainda sem veredito
> fechado (regra do projeto: precisa de mais evidencia de deriva), mas real.
> **PROXIMO PASSO**: abrir decisoes especificas erradas em `play`/`attach_don`
> via `decision_summary.py` contra o que o professor 'busca' escolheria, pra
> achar se e bug de execucao, feature faltando, ou capacidade do modelo (rede
> 64/32 neuronios) -- nao testado ainda, so hipotese.

> **CICLO 5 rodado com o fix do bloco 879: gerou dado de verdade (721.008 ->
> 740.861, +19.853 via busca), ciclo caiu pra 9,7min (era 30,9min no ciclo 3).
> Portao continua INCONCLUSIVO (9x8) e erro Q subiu (0,0534) -- MAS isso NAO e
> evidencia de que o professor busca piora nada: a tabela historica mistura
> DUAS mudancas de metodologia da mesma sessao (professor bootstrap->busca +
> validacao 5-fold/tudo -> 2-fold/amostra-200k), ciclos 1-3 e 4-5 nao sao a
> mesma regua. Um ciclo de 40 partidas tambem e incremento pequeno (~2,7% do
> corpus) pra decidir algo sozinho. NAO concluir "busca ajuda" nem "busca
> atrapalha" ainda -- falta MAIS ciclos com a metodologia atual (ja fixada)
> pra virar comparavel.**
>
> **PROXIMO PASSO**: rodar mais ciclos seguidos (mesma metodologia de agora)
> ate ter volume suficiente pra julgar de verdade. Resumo do que mudou nesta
> sessao pra quem assumir: geracao usa professor 'busca' (nao bootstrap);
> `treinar_q.py` usa 2 folds + amostra 200k pra validacao (modelo final ve
> tudo) e ganhou tabela POR LIDER; `--explorar` default 0,17 com exploracao
> "longe" (30% pra qualquer candidata, nao so top-4); corpus ganhou campo
> `modo` em linhas novas (nao foi reduzido). `when_attacking` via pondering
> (bloco 876) segue aberto, nao investigado mais fundo.

> **CORRIGIDO (bloco 879): modo 'busca' coletava ZERO alvos desde o bloco 811
> (13/09), sem erro nem aviso.** O ciclo 4 (bloco 878's teste) confirmou: 40
> partidas em modo busca, corpus ficou EXATAMENTE igual (721.008) -- gerou
> nada. Causa: a captura de 'busca' ficava num trecho que so roda quando o Q
> NAO decide, e o Q SEMPRE decide em producao desde que existe um
> `q_net.joblib` (desde o 1o ciclo) -- o trecho era inalcancavel. Fix:
> `_busca_determinista` tambem roda ANTES do Q decidir (mesmo lugar do
> bootstrap), so pelo efeito colateral de captura. Validado isolado (1856
> alvos, 100% `modo=busca`) e com teste permanente no `smoke_fast.py`. **O
> ciclo 4 nao conta como medicao real** (retreinou no corpus velho, sem dado
> novo -- erro_q 0,0498 e ruido de metodologia, nao regressao). **PENDENTE**:
> rodar o ciclo de novo, agora com o fix, e ai sim comparar.

> **MEDIDO (bloco 878): treino caiu de 1451s pra 180s (8,1x), sem tirar a
> validacao por lider.** Causa real (AS-IS mediu -- a suspeita de "ler linha a
> linha" estava ERRADA, so 1,5% do tempo): eram 6 fits completos de rede
> neural (5 folds de `GroupKFold` + 1 final), e os 5 de validacao nunca viram
> o modelo salvo. Fix em `treinar_q.py`: `--folds` 5->2 (minimo que ainda
> garante lider nunca visto) + `--amostra-validacao 200000` (folds rodam numa
> amostra, o modelo FINAL continua vendo o corpus INTEIRO). Concordancia com o
> professor: 59,9% (+23pp do acaso). Bonus: relatorio ganhou tabela POR LIDER
> individual (nao existia, so fold-agregado e familia-agregado existiam antes)
> -- mostrou generalizacao uniforme (52-68% na maioria), MAS tambem que 4
> lideres raros (Krieg, Imu, Xebec, 1 Ace) ficaram com amostra de menos
> (21-70 alvos) pra medir concordancia -- amostragem aleatoria pura nao
> garante piso por lider, pendente trocar por estratificada se importar.
> **PENDENTE**: rodar 1 ciclo inteiro com todas as mudancas da sessao juntas
> (busca em vez de bootstrap + explorar 0,17 + folds/amostra novos) e medir
> o portao -- ainda nao rodado.

> **MUDADO (bloco 877): o treino deixa de ser bootstrap.** 3 ciclos seguidos
> INCONCLUSIVOS com erro Q parado (~0,042) levaram a trocar o professor da
> geracao offline de `bootstrap` (aluno julgando a si mesmo) pra `busca`
> (simulacao real, professor independente) -- so em `ciclo.py`, o caminho ao
> vivo continua bootstrap por latencia. `--explorar` subiu de 0,10 pra 0,17,
> e ganhou uma exploracao "longe" (30% das exploracoes vao pra QUALQUER
> candidata, nao so as 3 seguintes ao topo -- unico jeito de descobrir o que
> o modelo nunca cogitaria). Corpus (721k linhas) NAO foi reduzido -- e 100%
> bootstrap hoje (0% busca), sem campo de data pra podar cirurgicamente;
> linhas novas ganham `'modo': 'busca'/'bootstrap'` pra permitir filtrar o
> treino MAIS TARDE sem apagar nada agora. **PENDENTE**: rodar 1 ciclo com o
> professor novo e comparar concordancia contra o baseline de 56,1% (bloco
> 817); decidir com o usuario quando/se truncar o corpus bootstrap legado.

> **ABERTO (bloco 876): atacante do OPONENTE via pondering ainda escapa do fix
> do bloco 875.** Validando ao vivo (4 partidas CPU x CPU), o fix funciona
> 100% pros ataques do PROPRIO turno do bot (inclusive multi-passo). Mas a
> Vista (Ace R) continua `atk=0` sem correcao -- a decision_log mostra o MESMO
> ataque dela registrado em 3 turnos diferentes (3, 4, 5), sinal de que o
> PONDERING especula o ataque adiantado sob um `trigger_turn` que nao bate com
> o turno real em que o `when_attacking` pergunta o alvo. `consume_attacker_
> power` exige turno exato -- e por isso nunca acha o registro certo nesses
> casos. Prognostico: ou trocar a exigencia de turno exato por "mais recente
> pra esse codigo", ou achar outro sinal que nao dependa de `trigger_turn`.
> Nao investigado mais fundo (pedido do usuario foi validar e seguir pro
> treino).

> **CORRIGIDO (bloco 875): `when_attacking` mirava a propria mao.** Causa
> fechada (pendencia aberta desde o bloco 862/871): `/choose_target` so
> recebia `attackerPower>0` do plugin em cenario de DEFESA/redirect -- quando
> era o PROPRIO atacante resolvendo o `when_attacking` dele mesmo (Vista
> OP16-011), chegava 0 e `_relevant_blocks` escolhia o bloco de efeito
> ERRADO (on_play em vez de when_attacking), contaminando a zona com
> `own_hand`. Fix em `server.py`: o servidor reconstroi o `attacker_power`
> a partir do que ELE MESMO decidiu no `/decide` real (novo tracker
> `_ultimo_ataque_real`), sem depender do plugin. Teste permanente em
> `smoke_fast.py` (camada `sim_bridge`), `smoke_fast.py` inteiro OK.
> **NAO validado ao vivo ainda** -- proxima partida com carta `when_attacking`
> deve mostrar `atk=0->N(proprio ataque)` no log `[TGT]`.

> **CORRIGIDO (bloco 874): Enel ativava o lider no vacuo.** Investigando os 2
> ultimos logs banked (Krieg x Luffy RG limpo; Enel x Imu com 1 bug real),
> achado que `_should_activate_main` liberava QUALQUER `add_don`/
> `set_don_active` sem checar se sobrava DON no deck/restado -- Enel (deck de
> DON reduzido, `don_deck_size: 6`) ativava o lider no turno 5 sem deck
> sobrando, queimava o `once_per_turn`, e nao movia nada. Afeta 32 cartas do
> banco (nao so o Enel). Fix percorre os `steps` em ORDEM: um
> `return_don_until_match_opp` (devolve DON do campo, incl. ANEXADO, pro
> deck) ANTES de um `add_don`/`set_don_active` na mesma cadeia libera mesmo
> com o deck zerado AGORA (pedido do usuario -- "a sequencia importa").
> Teste permanente em `smoke_fast.py`, `smoke_fast.py` inteiro OK.
>
> **PENDENTE de sempre**: telemetria individual (`live_`/`efeitos_`/
> `receipt_`) de Krieg x Luffy e Enel x Imu nao existe como artefato (bug do
> bloco 871) -- a auditoria foi reconstruida na mao do decision log cru.

> **COMMITADO: fix `pick_counters` (bloco 872, commit `1320ceb`)** --
> `effective_counter` era chamado 2x por carta, mesmo padrao ja corrigido em
> `counter_in_hand` no bloco de 03/08.
>
> **RESOLVIDO (bloco 873): `get_card_effects` duplicada removida.** A primeira
> definicao (linha ~2102, sem cache) era sombreada pela segunda (linha ~2196,
> com `_EFFECTS_ENRICHED_CACHE`) -- codigo morto, nunca executava. Removida,
> `smoke_fast.py` OK.

> **CORRIGIDO -- a coleta pegava a partida ERRADA e abortava a telemetria
> (19/09/2026, bloco 871)**, achado rodando tres CPU x CPU seguidas.
>
> **O OPTCGSim reescreve a SESSAO INTEIRA a cada fim de partida**, com o mesmo
> mtime em todos os arquivos:
>
> ```
> 22:43:06   22.43.05.log                          <- 1a partida
> 23:57:43   23.57.39.log  +  _p2.log              <- 2a (a nova e a _p2)
> 03:13:18   03.13.13.log  +  _p2.log  +  _p3.log  <- 3a (a nova e a _p3)
> ```
>
> O arquivo BASE contem a partida ANTERIOR (com `[You] Quits!` e um cabecalho
> `RZ1|HDR|` novo no fim). `_latest_log` usava `max(mtime)`, que EMPATA e
> devolve o base. Ai `_validate_bank_entry` procurava no index um id que o
> parser tinha pulado de proposito -- ja bancado, a trava por `impressao` do
> bloco 856 -- e levantava excecao.
>
> **A gravidade estava SUBESTIMADA na primeira versao deste item.** Eu escrevi
> "o risco nao e perder dado". **E.** A excecao aborta a coleta INTEIRA: toda
> partida que nao e a primeira da sessao ficava SEM `live_`, `efeitos_`,
> `consequence_` e `receipt_`. Medido no disco: as partidas 2 e 3 desta sessao
> tinham ZERO artefato. O log bruto sobrevive; a telemetria nao -- e ela e dois
> dos quatro itens da meta desta fase.
>
> **Fix**: agrupa pelo PREFIXO de sessao e escolhe o MAIOR sufixo, em vez de
> confiar no mtime (o empate e o caso normal, e a ordem entre iguais nao e
> garantida). `smoke_fast.py ::
> test_coleta_escolhe_a_partida_NOVA_da_sessao_bloco_871`, 5 checagens, com
> controle para a 1a partida (sem sufixo, o base vale) e para sessao antiga na
> mesma pasta. **Verificado que o controle reprova a versao antiga**: ela
> escolhia `03.13.13` em vez de `03.13.13_p3`.
>
> **ABERTO**: a telemetria das partidas 2 e 3 desta sessao nao existe como
> artefato. A auditoria de efeitos foi reconstruida do decision log do server
> (`decisions_2026-09-18T20.02.02.jsonl`, cobre as 3); `live_`/`consequence_`
> das duas nao foram regeradas.


> **CPU x CPU ACHOU DOIS BUGS E A AUDITORIA TINHA TRES PONTOS CEGOS
> (18/09/2026, bloco 870)** -- os dois apontados pelo usuario na hora, os dois
> dados como VERDES pela telemetria.
>
> **FECHOU: o 52x2 do bloco 869 VALE.** Controle A/A com dois lados identicos
> deu **0 pares decididos** (o certo para pares espelhados iguais -- mais forte
> que o "~50%" que o script prometia); o duelo real reproduziu 54 decididos,
> 52x2, Wilson 87,5%. Tirar o corte do shortlist melhora o JOGO. Continua sendo
> AUTO-JOGO, cego pra vicio compartilhado.
>
> **FECHOU: Loki OP17-119** -- o `[On Play]` nunca existiu no banco; entrou em
> campo 2x com `effects: []` tendo alvo valido. Regex de orcamento somado
> generalizado nos DOIS eixos (quantificador x grandeza). Motor alterado junto,
> senao o K.O. sairia sem limite. PERDEU=0, 1 carta mudada, 3 testes novos.
>
> **FECHOU: [Unblockable] no turno 1** -- keyword de combate `this_turn` num
> turno em que atacar e impossivel por regra. Gate em `_step_is_viable`. A
> telemetria mostrou `candidatas: 1`: nao havia alternativa, entao nao adianta
> esperar que o ML aprenda.
>
> **FECHOU: a auditoria de efeitos enxerga o que nao via** -- (a) Event jogado
> da mao ficava fora do ciclo de vida (**285 Events** do banco tem `main` e nao
> `on_play`); (b) secao `CONCLUIU E NAO VALIA NADA`; (c) secao `O TEXTO DA CARTA
> TEM GATILHO QUE O BANCO NAO TEM`, a unica que compara fora do parser.
> Controle rodado nos dois sentidos.
>
> **ABERTO -- 12 cartas com o MESMO defeito do Loki**, achadas pela checagem (c)
> e NAO corrigidas (cada uma precisa do seu gate global):
> `OP02-066` `OP06-023` `OP15-042` `OP17-117` `ST26-001` e 7 promos
> (`P-063` `P-072` `P-075` `P-081` `P-082` `P-097` `P-100`).
> Classe "a acao nao existe pro modelo" -- nada no projeto detectava antes.
>
> **ABERTO -- NADA disto rodou ao vivo.** So `smoke_fast.py` OK, `diff_parser`
> PERDEU=0 e auditoria sobre log antigo. **A proxima CPU x CPU tem que
> REINICIAR o server da 8765** (o desta sessao subiu antes das edicoes). Sem
> portao SPRT: o efeito das duas correcoes no resultado de partida e desconhecido.

> **DUELO DO SHORTLIST: flag por jogador pronto, resultado NAO VERIFICADO
> (18/09/2026, bloco 869)** -- `shortlist_sem_corte` por JOGADOR (padrao de
> `modelo_ordena`/`value_net_weight`), default True = comportamento novo. NAO e
> knob de compatibilidade: e o instrumento pra derrotar o antigo com numero.
>
> **O duelo deu 52x2 (96,3%, Wilson 87,5%) a favor de tirar o corte -- e esse
> numero NAO pode ser citado como validacao ainda.**
>
> Motivo: o controle A/A **nunca rodou**. Minha flag do controle estava
> invertida (`not args.controle_aa`), entao as duas execucoes rodaram a MESMA
> configuracao e sairam identicas, numero por numero. Eu li isso como "o
> instrumento esta quebrado"; na verdade o controle e que nao existia.
> **Bug ja corrigido no script**; o A/A continua PENDENTE.
>
> O que ESTA verificado: o flag chega de verdade (diagnostico: 14 chamadas com
> `sem_corte=True` e 6 com `False` na mesma partida) e o Q esta no comando em
> 100% das decisoes (26 de 26).
>
> **PROXIMO PASSO, uma linha:**
> `cd scriptis_da_ia && python duela_shortlist.py --n 200 --workers 4 --controle-aa`
> Tem que dar ~50%. Se der 96% de novo, o instrumento esta cego e o 52x2 nao
> vale. So depois disso o resultado pode ser reportado.

> **A HEURISTICA SAIU DO SHORTLIST (18/09/2026, bloco 868)** -- pedido do
> usuario, *"tira a heuristica do shortlist"*. Fecha o buraco estrutural que
> ele mandou resolver em 12/09 (*"o que nao vira candidato nao existe"*).
>
> | | antes | depois |
> |---|---|---|
> | acoes geradas por decisao | 12,1 | 13,6 |
> | chegam ao modelo | **3,7** | **13,6** |
> | DESCARTADAS | **69,1%** | **0,0%** |
> | shortlist ordenado pelo modelo | 0 de 505 | n/a (nao ha corte) |
>
> Sairam o corte por `TOP_K`/janela **e** o piso `score estatico >= 0`. O piso
> era julgamento de VALOR por regra fixa -- `REGRA_O_CRITERIO_EMERGE`: o que e
> LEGAL e regra, o que e BOM e modelo.
>
> **Por que pode sair**: o corte existia porque "cada candidata a mais custa
> amostras Monte Carlo" (blocos 593/594/677) -- e **o Monte Carlo saiu no bloco
> 785**. O Q pontua tudo em lote. A justificativa morreu e o corte sobreviveu a
> ela por um mes.
>
> **PENDENCIA PRINCIPAL: nao foi medido se GANHA.** O duelo pareado exige flag
> por jogador (padrao de `modelo_ordena`/`executa_lethal`) e nao foi rodado. O
> portao mede DEPOIS e nao e pre-requisito, mas ate rodar ninguem pode dizer que
> a troca melhorou o jogo -- so que o modelo passou a enxergar tudo.
>
> Custo NAO explodiu: `gerar/pontuar candidatas` = 1,3% do tempo, modelo 53,5%.
> (O s/partida caiu de 0,61 pra 0,49, mas as PARTIDAS mudaram -- 45 turnos
> contra 29 -- entao isso NAO e ganho de velocidade comparavel.)

> **`q_fallback` LIGADO NO `live_<ts>.json` (18/09/2026, bloco 867)** -- fecha a
> pendencia aberta no bloco 866. O passo 1 da telemetria agora responde
> **"esta partida foi decidida pelo modelo?"**: `total: 0` = sim; qualquer
> numero = decisao SEM o modelo, com a quebra por motivo.
>
> **A armadilha que isto teve que contornar**: `bot_efficiency_report.py` roda
> em SUBPROCESSO, com estado de modulo zerado -- ele enxergaria `{}` SEMPRE, e
> um contador vazio pareceria "esta tudo bem". A medicao e feita no processo do
> SERVIDOR (retrato no mulligan, delta no `/outcome`) e passada adiante, entao
> o numero e POR PARTIDA e nao herda o da anterior.
>
> Alerta tambem no stdout (`[AUTO-COLLECT][ATENCAO]`) e no
> `receipt_<ts>.json`. `teste_q_fallback.py` permanente, 9/9.

> **O FALLBACK SILENCIOSO FOI CONSERTADO (18/09/2026, bloco 866)** -- e era
> PIOR do que o bloco 865 reportou. Nao caia "na heuristica": caia em
> `candidatas[0]`, o primeiro da ordenacao estatica, **sem avaliacao nenhuma**.
> Medido no controle: **180 quedas numa UNICA partida** com modelo quebrado, e
> nenhuma delas produzia qualquer sinal.
>
> Agora `_nota_fallback_q` conta e avisa, por motivo (`sem_modelo`, `erro`,
> `sem_valor`, `primeiro_candidato`), 1 aviso por processo;
> `q_fallback_resumo()` expoe os totais. **A degradacao continua graciosa** --
> o motor nao pode cair, regra permanente -- mas deixou de ser muda.
> Verificado: com o modelo bom o resumo vem **vazio** (o Q decide sempre).
>
> **PENDENCIA AINDA ABERTA**: ligar `q_fallback_resumo()` no
> `live_<ts>.json`, pra que uma partida ao vivo denuncie a queda sem ninguem
> ler stderr.
>
> **DIVERGENCIA DE ESPELHO ACHADA E CORRIGIDA**: o `AGENTS.md` estava sem a
> **disciplina inteira de passagem de sessao** (commitar antes de parar,
> escrever HANDOFF, espelhar no TODO, ler antes de editar) **e sem a instrucao
> de instalar os hooks** (`sh scripts/setup-git-hooks.sh`). Num clone novo uma
> sessao Codex ficaria sem o `pre-push` inteiro -- hoje isso inclui as
> checagens de corpus e de index. E o mesmo modo de falha do achado de
> 25/07/2026, que a regra do espelho existe pra impedir.

> **DUAS PENDENCIAS NOVAS, achadas ao revisar o CLAUDE.md contra o CODIGO
> (18/09/2026, bloco 865)** -- as duas sao do tipo que o projeto mais paga:
> falha silenciosa.
>
> **1. FALLBACK SILENCIOSO PRA HEURISTICA.** A decisao do Q
> (`decision_engine.py`, "Sem chave e sem alternativa: e o unico decisor")
> esta dentro de um `try:` que termina em `except Exception: pass`. Se o
> modelo nao carregar, for incompativel ou errar em qualquer feature, o motor
> **cai na heuristica sem emitir nada** -- sem log, sem aviso. Degradacao
> graciosa e desejada; **silenciosa nao**. Pode-se estar rodando na heuristica
> sem ninguem saber. Minimo: contar as quedas e reportar no `live_<ts>.json`.
>
> **2. O SHORTLIST AINDA E ORDENADO PELA HEURISTICA.** O `CLAUDE.md` afirmava
> que "desde os blocos 790-791 a heuristica nao decide mais nada" -- **esta
> pela metade** e o texto ja foi corrigido. O Q decide o VENCEDOR da acao de
> topo, mas `NULLIFY_EVALUATE_STATE_V2 = False` e o shortlist tem cota por
> tipo de acao ordenada pelo score estatico: **a heuristica escolhe os
> FINALISTAS que o modelo tem permissao de considerar**. E exatamente o buraco
> que o usuario mandou resolver em 12/09 (*"o que nao vira candidato nao
> existe"*), agora com o mecanismo localizado.
>
> Corrigido no mesmo bloco: a lista `ENGINE_TOUCHPOINTS` do gate `pre-commit`
> so tinha nomes de funcao HEURISTICA -- levar o MODELO pro caminho ao vivo
> seria **barrado como "segundo motor"**. Somados `value_net|q_valores|
> win_prob|q_net|load_value_net`.
>
> **`human_patterns.json` deixou de ser OBRIGATORIO** (decisao do usuario): ele
> premia PARECER com humano e alimenta a ordenacao do shortlist, enquanto a
> meta desde 10/09 e VENCER o humano, com semelhanca so como guarda-corpo.

> **UM COMANDO DE CADA LADO (18/09/2026, bloco 864)** -- `sincroniza.py entrega`
> / `chega` cobre **corpus E logs** juntos, a pedido do usuario: *"a ideia e
> pegar os treinos de uma maquina e os logs, e quando a outra maquina for
> atualizar, tb atualizar os logs e os treinos"*.
>
> **Zipar os logs foi DESCARTADO por medicao**: eles tem 27,0 MB em disco e
> **1,7 MB dentro do .git** -- exatamente o que um `tar.gz` daria. O git ja
> comprime na mesma taxa; zipar nao economizaria um byte e quebraria as 11
> ferramentas que leem `logs/parsed/*.json` direto. **A solucao para os logs
> nao era formato, era automacao.**
>
> Fecha a causa raiz dos 13 arquivos: a ferramenta que banca o log nunca
> versionava nada, e o hook do bloco 863 so reclamava. Agora `entrega` corrige.
> `verifica_push.py` passou a IMPORTAR a varredura em vez de duplicar.

> **O CORPUS PASSA A VIAJAR PELO GIT, EM FATIAS (18/09/2026, bloco 863)** --
> pedido do usuario, depois de perder meia sessao: ele chegou ao trabalho sem
> conexao com a Arthur_PC e o corpus so existia como zip de uma conversa
> daquela maquina. **O zip do `q_alvos` acabou.**
>
> A regra antiga recusava git com um argumento CERTO -- "cada commit guardaria
> uma copia inteira nova, ~13 MB por ciclo" -- que vale para um zip UNICO.
> Medido hoje: o corpus comprime **37,4x** (465 MB -> 12,9 MB) e, FATIADO, um
> ciclo custa **1,3 MB** permanentes, porque cada fatia e escrita uma vez e
> nunca reescrita.
>
> `scriptis_da_ia/corpus_git.py` (`status`/`importa`/`exporta`). Os tres
> leitores nao foram tocados. **OBRIGATORIO**: `ciclo.py` e `treino_continuo.py`
> se recusam a rodar com fatia pendente; o `pre-push` bloqueia push com linha
> fora do git. No PUSH e nao no commit, por decisao do usuario.
>
> **Dois erros meus pegos por teste antes de estragar dado**: deduplicar por
> hash de linha teria descartado 25.846 linhas legitimas (3,7% -- candidatos
> identicos na MESMA decisao); e a fatia saia com CRLF contra o LF do corpus.
> `teste_corpus_git.py` e permanente e tem o controle que reprova a v1.
>
> **ABERTO**: 13 arquivos referenciados pelo `logs/index.json` estao so no disco
> da Arthur_PC -- so ela pode versiona-los. O `pre-push` agora avisa (nao
> bloqueia quem nao tem como consertar). E o **ciclo 3 segue sem ser rodado**.
>
> **REGISTRADO A PEDIDO**: quando o projeto terminar, as fatias saem do git.
> Exige reescrita de historico e corpus salvo fora antes -- nunca por
> iniciativa de sessao.

> **A ZONA DO ALVO PASSA A FILTRAR (18/09/2026, bloco 862)** -- implementa o
> achado do bloco 861, a pedido do usuario. `_ALVO_ZONAS` em
> `order_target_candidates`, espelho do `_CUSTO_ZONAS`, mais a familia
> `select_grant_*` mapeada pela ACAO (nunca traz `target`; evitou regerar o
> banco). **Lider Ace OP16-001 sai de 6 zonas com `own_hand` escolhida para
> `['own_board']`** -- era o 0% de conclusao.
>
> **O smoke derrubou DUAS versoes minhas**, as duas por premissa errada, e as
> duas da MESMA classe do bloco 858 (afirmar zona com base em algo que nao
> responde a pergunta): (1) pular steps sem `target` -- mas `look_top_deck`
> quer `top_deck`; (2) **`target` e onde o efeito CAI, `source` e o que o
> jogador SELECIONA** -- a Devon OP16-104 tem `target:self` com
> `source:selected_opp_character`. Sao 308 steps com `source`; qualquer um
> desliga o filtro.
>
> **ALCANCE: 939 de 3.632 blocos (25%), 830 cartas** -- menor que os 1.417
> steps estimados porque `_relevant_blocks` junta todos os blocos nao-combate:
> um `look_top_deck` no `on_play` desliga o `activate_main` da mesma carta. O
> **Thousand Sunny ST31-005 fica ABERTO** por isso.
>
> **ABERTO**: mapear zona para as acoes SEM `target` (`look_top_deck`,
> `add_to_hand`, `play_from_trash`...) alcancaria os outros 75% -- nao feito
> porque cada acao nao mapeada e uma chance de apagar a resposta certa.
>
> **CUIDADO NA MEDICAO**: o bloco 858 nao sera mais medido sozinho. O que
> separa: o Mihawk usa `set_don_active`, que cai no filtro `actor_don_target`
> e nao no novo.

> **ACHADO ABERTO -- a zona legal do alvo esta PARSEADA e o motor nao usa
> (18/09/2026, bloco 861)**: auditoria de efeitos dos adversarios do Mihawk.
> **Portgas D. Ace (OP16-001), lider, 0%** -- a habilidade da Rush a um
> Personagem EM CAMPO e o bot mirou `ST23-001 em own_hand`. O Thousand Sunny
> (ST31-005) e pior: o step tem **`target: leader_or_own_character`** escrito
> no efeito parseado e o bot mirou a MAO assim mesmo.
>
> `order_target_candidates` restringe zona para 3 familias (mira DON, nao mira
> DON, custo), cada uma adicionada apos um achado ao vivo. **Falta a regra
> geral `target -> zonas`, a mesma FORMA do `_CUSTO_ZONAS`**: sao **1.417
> steps** com `target` ja parseado (`opp_character` 581, `leader_or_character`
> 167, `leader` 105, `own_character` 88...).
>
> Metade e do PARSER: a familia `select_grant_*` nunca traz `target` --
> `select_grant_rush` sozinho afeta **6 lideres**. Sem o campo nao ha o que
> consultar.
>
> **NAO implementado de proposito**: seriam 2 mudancas no mesmo caminho antes
> de medir o bloco 858. Provavelmente MAIOR que completar o detector de
> `purpose` (1.417 steps contra uma janela de custo) -- decidir a ordem depois
> da medicao.
>
> O que esta certo: **Xebec OP17-039 fecha 9 de 9** em `when_attacking`, e 8
> cartas fecham 100%. O problema e concentrado em efeitos que pedem alvo em
> campo, nao amplo.

> **REGUA E `effect_option` (18/09/2026, bloco 860)**: a 13a falha semantica
> tambem era regua -- o `state_after` da ULTIMA acao de uma partida e capturado
> na abertura da SEGUINTE (turno 6 -> turno 1, outro lider, tudo vazio), e os
> `match_id` provam. 1 caso em 667, ou seja 1 ERROR por partida pra sempre.
> Agora transicao entre partidas diferentes e INDISPONIVEL, nao falha:
> **`semantic_transition_failed` 13 -> 0**, 98 de 98 passando.
> (Hipotese do uid negativo DESCARTADA por medicao: 17.974 negativos contra
> 16.029 positivos -- e o proprio jogo que numera assim.)
>
> **`effect_option` nao registrava execucao em 48 de 48 (100%)** -- as outras
> familias ficam em 0-3%. O bot escolhia a opcao e nada gravava se o jogo
> aceitou; ja custou o achado do Enel (bloco 838), que so apareceu por outra
> ferramenta. O callback `onDecision` ja existia e o BotDriver nunca usava.
> Corrigido com `TrackAuxDecision`, o mecanismo das outras familias.
>
> **NAO mexer no detector de `purpose` antes de medir o bloco 858** -- seriam
> duas mudancas no mesmo caminho e a medicao nao diria qual pegou (licao do
> bloco 788). Esta entra porque so REPORTA, nao muda decisao nem clique.

> **OS TRES ALERTAS DA TELEMETRIA -- ATACADOS (18/09/2026, bloco 859)**:
> 1. `semantic_transition_failed` **13 -> 1**: era REGUA TORTA. 12 eram
>    `end_turn` com `turnNumber` inalterado -- e o end_turn tinha funcionado
>    (o lider do lado que age mudou). Neste jogo o `turnNumber` cobre os DOIS
>    jogadores. A regua aceita as duas formas do sinal agora. A 1 que sobra e
>    real (`attack` com OP12-023 sem restar o atacante) e fica ABERTA.
> 2. `bot_confusion` 7x: **2 benignos** (nenhuma carta cabia no DON; a
>    auto-restricao do bloco 853 barrando o unico Personagem) + 2 cujas cartas
>    so tem bloco `counter`/`trigger` (nao jogaveis na main). Os restantes sao
>    reais e ficam ABERTOS. O conserto de fundo: `/decide` passa a gravar
>    `sem_acao_contexto` (DON, restricoes em vigor, mao com custo e blocos
>    parseados) -- investigar isso exigia arqueologia.
> 3. `decision_timeouts`: **nao era a busca**. Turno 1, 4 candidatas, board
>    vazio, `latency_segments_ms` nulo -- carga preguicosa na 1a chamada.
>    Quando estoura, o bot cai no FALLBACK: decisao real perdida todo turno 1.
>    `_aquece_motor()` no startup, medido em **2.442 ms** pagos fora da
>    partida.
>
> **ABERTO, nao e desta leva**: `test_bot_efficiency_report` tem 2 baselines
> falhando (2.031 vs 2.143) -- ja falhavam antes desta sessao (o `live_*.json`
> das 22:48 de 17/09 ja trazia 2.143) e os arquivos do cohort existem.

> **REGRESSAO DO BLOCO 854 -- CORRIGIDA (18/09/2026, bloco 858)**: o `purpose`
> quebrou a habilidade do lider Mihawk. `TargetPurpose` fazia
> `IsOptionalCostWindow ? "cost" : "effect"`, tratando ausencia de evidencia de
> custo como evidencia de efeito -- e o Mihawk pede `rest_own_card`, fora das 5
> formas que o plugin conhece. O motor entao removia as zonas de custo dos
> candidatos e a ativacao morria com "estado inalterado".
>
> ```
> 17/09 21.49 e 22.15 (bloco 853) : 26 ativacoes, 0 falhas
> 17/09 22.41 e 23.34 (bloco 854) : 16 ativacoes, 8 falhas (50%)
> ```
>
> **CORRIGE o diagnostico do bloco 854**: ele atribuiu o "nao pagou" a
> COBERTURA (9 de 105 como `cost`). Errado -- cobertura baixa e inofensiva
> (`unknown` = comportamento anterior); o estrago foi o `effect` FALSO apagando
> candidatos validos. `TargetPurpose` agora so devolve `cost` ou `unknown`.
>
> **Lacuna fechada**: o evento de `target` nao gravava `purpose`/`step_index`
> (so o stdout), entao nao dava pra ligar execucao FALHADA ao proposito da
> janela. Agora grava. **PENDENTE: medir** (esperado voltar a 0 falhas).

> **RECUSA DE COUNTER ERA MUDA -- CORRIGIDO (17/09/2026, bloco 857)**:
> `select_counter_cards` tem 4 saidas e so a ultima registrava. O bot recusava
> com `[Counter]` na mao e o log saia VAZIO -- o buraco de "46 janelas com
> counter, 0 aceitas". Agora as 4 registram com MOTIVO (`ataque_nao_passa`,
> `sem_counter_elegivel`, `nao_cobre`, `troca_de_recursos`,
> `aceito_defendendo_lider`), reusando `_log_defesa`.
>
> **DOIS LADOS NO CPU x CPU (pedido do usuario): CONFERIDO E TESTADO.** O
> plugin ja estava certo (`BotPlayerIndex` segue `iPlayerAction` a cada frame);
> o evento separa os lados por `board_no_ataque.defensor.leader`. Testado
> batendo no `/defense` com cada lado defendendo.
>
> **ADVERSARIOS DO MIHAWK (banco limpo, 26 partidas): 13-12.** O "7-2" que eu
> tinha reportado era so de hoje E todas `cpu_vs_cpu` -- bot contra ele mesmo.
> Contra `com_bot` e pior (0-3 vs Xebec em 13/09). Katakuri 4-5 (9 partidas),
> Xebec 2-4, Luffy 2-1.

> **BANCO DE LOGS RE-BANCAVA A MESMA PARTIDA -- FECHADO (17/09/2026, bloco
> 856)**: `LogOutput.log` acumula, o auto-collect re-parseia o arquivo INTEIRO
> a cada `/outcome` e re-bancava as partidas anteriores com nome novo. A trava
> comparava o `id` (timestamp da COLETA, novo a cada vez) e nunca disparava --
> Enel x Teach estava no banco **6 vezes**. Agora a trava usa
> `impressao_da_partida` (md5 dos TURNOS), gravada no index como `impressao` e
> retroalimentada nas 195 entradas.
>
> **271 arquivos removidos, index 241 -> 195** (184 partidas distintas).
> `human_patterns.json` regenerado (acoes 6.286 -> 6.227), `smoke_fast` OK.
>
> **CORRECAO DO USUARIO que evitou perda de dado**: *"eu jogo partidas
> repetidas com os mesmos lideres"* -- e o controle confirma (Teach x Xebec:
> 16 arquivos, 16 conteudos DISTINTOS). Par de lideres repetido NAO e
> duplicata; so conteudo de turnos identico e. O `.log` cru tambem nao serve
> de identidade: a fatia capturada CRESCE a cada coleta (43.644 -> 44.118 B na
> mesma partida).
>
> **ABERTO -- 4 partidas com rotulo contraditorio**: copias da mesma partida
> (conferido a mao) com `winner`/`bot_side` TROCADOS entre si -- Katakuri x
> Ace, Katakuri x Teach, Kaido x Luffy, Luffy x Xebec. Nao deduplicadas de
> proposito: escolher a copia seria escolher qual rotulo virar verdade.
> Precisa de decisao/conferencia antes de limpar.

> **TELEMETRIA DE DEFESA AO VIVO -- LIGADA (17/09/2026, bloco 855)**: o motor
> JA raciocinava sobre defesa e JA sabia registrar (`_log_defesa`), mas a
> auditoria so era ligada no AUTO-JOGO -- ao vivo o raciocinio era calculado e
> jogado fora. O `/defense` agora liga a auditoria do motor em volta da chamada
> e DRENA (nada reimplementado), somando o contexto do servidor: **quem
> atacou** (`attacker_code` -- o plugin ja tinha o atacante e mandava so o
> PODER), **quem defendeu**, o **board dos dois lados na hora do ataque**
> (tirado ANTES da decisao), e os efeitos ativaveis **na janela**
> (`on_opp_attack`/`counter`/`on_block`/`opp_turn`) e **depois** (`on_ko`) --
> lidos do bloco PARSEADO, nunca por codigo de carta.
>
> **POR QUE**: 54 decisoes de counter, 46 com counter real na mao, **0
> aceitas**, e o bot indo de 5 pra 0/1 de vida -- e sem o atacante no evento
> nao dava pra separar "recusou e estava certo" de "recusou e tomou dano a
> toa". **PENDENTE: medir** (2 partidas; a DLL nova so vale no proximo start
> do jogo).

> **`step_index` + `purpose` -- CONSTRUIDO e NAO PAGOU (17/09/2026, bloco
> 854)**: primeiro clique 59% -> **55%**, nunca-acerta 34% -> **40%** (pior
> episodio caiu de 64 pra 34 cliques). Causa medida e do lado do PLUGIN: das
> 105 requisicoes carimbadas so **9 chegaram como `cost`** --
> `IsOptionalCostWindow` reconhece **5 formas** de custo e `_CUSTO_ZONAS`
> mapeia **10** (falta "devolva 1 Personagem seu" do Law, entre outras). O
> mecanismo fica no codigo (correto, testado, `unknown` = comportamento
> anterior); **proximo passo: completar o detector**.
>
> **CORRECAO ao bloco 849**: `LogOutput.log` **RESETA quando o jogo
> reinicia** -- acumula so dentro de uma sessao. Conferir o TAMANHO do
> arquivo contra a marca antes de confiar nela (marca 2.296, arquivo 1.207
> depois do restart -- ler a partir da marca teria reportado "zero recusas =
> sucesso").

> **AUTO-RESTRICAO "cannot play this turn" AO VIVO -- FECHADO (17/09/2026, bloco 853)**:
> o achado aberto do bloco 850. Medido por lado: o lado do Mihawk fez 16 plays
> antes de ativar (16 ok) e **6 depois (6 recusados, 100%)** -- e o plugin
> encerra o turno apos 2 falhas seguidas, entao o bot **abandonava o resto do
> turno**.
>
> O motor JA tinha as 3 flags, JA as setava offline e JA as lia; **so o caminho
> ao vivo nunca setava** (`_dto_to_gs` reconstroi o estado a cada `/decide`).
> Corrigido no `server.py` com o idioma de memoria por turno que ja existia,
> GENERICO pela forma (`self_cant_play` do efeito parseado): 8 cartas com
> `scope=chars` + 1 com `scope=hand`. Ao vivo pegou sozinho uma 2a carta
> (`OP13-118`).
>
> **VALIDADO em 2 partidas**: recusas 6 -> **0**, "2 falhas seguidas" -> **0**,
> e o controle que podia falhar: 3 Events jogados apos a ativacao, todos
> aceitos (a restricao so proibe Personagem) e o adversario nao bloqueado.
>
> **BUG DENTRO DO FIX, corrigido**: usei `cardId` (nome do campo no
> decision_log) onde o `CardDto` usa `code` -- a chave `(turno, lider)` ficava
> `(turno, "")` e a restricao de um lado valia pro outro. **O meu teste nao
> pegou porque o duble repetia a mesma suposicao errada do codigo** -- onde o
> valor vem de DTO externo, testar contra o schema real.

> **MERGE DE HISTORICOS DIVERGENTES + `id` NAO E UNICO (17/09/2026, bloco 852)**:
> a Arthur_PC tinha **3 commits nunca empurrados** quando a Arthur_Trabalho
> assumiu o bastao, entao as duas avancaram da mesma base e o `pull --ff-only`
> falhou. A regra do bastao protege a SEED (`ciclo_estado.json`), **nao o
> historico** -- quem sai tem que empurrar ANTES. Resolvido por merge, com
> backup em `backup-arthurpc-2026-09-17`.
>
> **ARMADILHA**: unir `logs/index.json` por `id` APAGA entradas em silencio --
> partidas do mesmo lote (`_p2`, `_p3`...) compartilham o timestamp. Chavear
> sempre por `parsed_file`. Banco final: 228 registros.
>
> **Os zips da outra maquina nao chegam aqui**: sessoes do Claude Code sao
> LOCAIS (`list_sessions` devolve vazio nesta maquina). Mas quase tudo viaja
> pelo git; falta so o corpus, e sao **383 linhas (0,05%)**, nao as 73.477 que o
> bloco 851 estimou -- ele nao contava que a Arthur_PC ja tinha o zip de 14/09.

> **Escopo deste arquivo** (revisto em 12/09/2026): lista VIVA — o que
> está aberto e o fluxo recente (setembro/2026, blocos 748-779). O
> histórico de julho/agosto e as seções já concluídas foram para
> [`TODO_ARQUIVO.md`](TODO_ARQUIVO.md).

> **CPU x CPU PASSA A ALIMENTAR O CORPUS DO Q (14/09/2026, bloco 831)**: pedido
> do usuario -- *"quero que a cpu x cpu tb seja um treino, so que com um
> diferencial que eu consigo vizualizar e acompanhar turno a turno"*. Eu tinha
> respondido *"nao treina"* (bloco 816, argumento de VOLUME) -- **mecanicamente
> certo e a resposta errada**: ele nao pediu volume, pediu pra nao jogar fora o
> dado de uma partida que ja esta sendo gerada.
>
> **ZERO motor novo.** O captador ja existia e e opt-in (`_q_captura`,
> `decision_engine.py:19053`); o caminho ao vivo usa o MESMO `OPTCGMatch`.
> Provado empiricamente antes de codar: `choose_action` com o captador ligado
> devolveu 2 linhas de **101 feats**, com `alvo` e `escolhida` -- formato
> identico ao self-play. `REGRA_SEM_DUPLICACAO` intacta.
>
> **Construido**: `scriptis_da_ia/coleta_q_ao_vivo.py` + 2 enganches finos no
> `server.py` (`/decide` capta e drena; `/outcome` grava). **PONDER fica de
> fora** (especula jogadas que nunca acontecem); **so grava com desfecho**
> (draw/aborted descartam); `origem` = `<base>_simulador` (bloco 820), pra ser
> mensuravel e removivel. Desligavel por `OPTCG_COLETA_AO_VIVO=0`.
> `smoke_fast.py`: **1.430 OK, 0 FALHOU**.
>
> **LIMITE HONESTO**: ~dezenas de alvos por partida contra ~72.000 por ciclo de
> 300 = **~0,1%**. NAO e fonte de volume. O valor e FIDELIDADE (estados
> adjudicados pelo JOGO, nao pelo nosso codigo) -- a mesma diferenca que fez o
> CPU x CPU achar o bug do Shiki que o auto-jogo jamais acharia.
> **NAO MEDIDO** se ajuda, atrapalha ou e neutro no treino; a `origem` existe
> pra medir depois. Nao afirmar ganho antes de medir.

> **PASSAGEM DE BASTAO -> Arthur_PC (17/09/2026, bloco 851)**: a
> `Arthur_Trabalho` PARA de treinar. **O passo que quebra em silencio**: o
> corpus NAO viaja pelo git -- aqui tem **698.838** linhas, a Arthur_PC tem
> **625.361**. Sem descompactar o `.gz` enviado, ela treina 10,5% menor e joga
> fora 73.477 linhas SEM ERRO NENHUM.
>
> **Ao chegar**: `git pull` -> descompactar `q_alvos.jsonl.gz` em
> `metrics/q_alvos.jsonl` -> conferir os 3 pontos (corpus 698.838 com 3 origens;
> `ciclo_estado` com 2 ciclos, proximo e o **3, seed 9303**; sklearn 1.9.0 +
> `q_net.joblib` abrindo) -> so entao rodar.
>
> **FECHADO e validado em partida**: Enel (0->80%), Mihawk (0->71%), Streusen.
> **ABERTO por custo**: (1) `cant_play_chars_this_turn` nunca setada ao vivo --
> 6 de 6 plays recusados (bloco 850); (2) MEDICAO de qualidade de alvo
> (obrigatoria, bloco 848); (3) 27 das 28 cartas do bloco 845 sem teste; (4)
> ciclo 3 nunca rodado.

> **O FIX DESTRAVOU UM SEGUNDO BUG (17/09/2026, bloco 850)**: a habilidade do
> Mihawk tem `self_cant_play(chars)` -- **proibe jogar Personagens no turno**.
> Enquanto ela nunca completava, a restricao nunca existia; agora que funciona,
> vale -- e o motor continua tentando jogar personagens. **6 de 6 plays
> recusados estao no MESMO turno de uma ativacao do Mihawk.**
>
> **NAO e regressao do fix**: as falhas sao `on_play` com `alvo=nao` (sem
> decisao de alvo), e o bloco 847 so mexe em filtro de candidatos a ALVO. O log
> do plugin diz `play: jogo recusou OP12-034 (custo? restricao?)`.
>
> **Causa**: `decision_engine.py:2887` tem `cant_play_chars_this_turn`; o
> `server.py` seta isso **0 vezes**. Mesma classe do bloco 830 (flags de runtime
> que o ao vivo nunca preenche), 3a vez na semana.
>
> **Fix NAO feito**: exige memoria por `(match_id, turno)` no server -- o
> `_dto_to_gs` reconstroi o estado a cada decisao, entao um `setattr` nao
> sobrevive. **Custo medido**: 6 plays recusados/sessao, desperdicio garantido.
>
> Telemetria: +114 alvos, corpus **698.838**, `efeitos_error=None`. Recusas de
> clique no trecho novo: **37,8%** (contra 30,5%/31,5%) -- subiu, e os 6 plays
> explicam parte; quanto, nao medido. Mihawk `activate_main` 71%, com as 2
> falhas do tipo `restado 0->0` (sem DON), nao bug.

> **FIX DO MIHAWK VALIDADO EM PARTIDA (17/09/2026, bloco 849)**: `activate_main`
> **0% -> 67%**, e confirmado pelo ESTADO: `ativo 0->3 | restado 10->7` nos
> turnos 5 e 6 -- exatamente os 3 DON que a carta promete. A "falha" do t3 NAO e
> falha (`restado 0->0`, nao havia DON pra ativar). Cliques: antes **12, todos
> `Don`, 0 sucessos**; agora 24 espalhados por personagens, **2 de 3 funcionando**.
>
> **ERRO MEU corrigido antes de virar "regressao"**: eu ia reportar cliques
> recusados subindo 687 -> 990. **O `LogOutput.log` e CUMULATIVO** -- comparei o
> mesmo arquivo crescendo. Por trecho normalizado: **30,5% antes x 31,5%
> depois** = **sem regressao**.
>
> **Propriedade a nao esquecer**: `LogOutput.log` ACUMULA entre sessoes; o
> `server_stdout.log` e TRUNCADO a cada restart (bloco 841). Comportam-se ao
> CONTRARIO e confundi-los da comparacao falsa nos dois sentidos.
>
> Coleta: +94 alvos, corpus **698.724**, simulador **1.245**, `efeitos_error=None`.
> **ABERTO**: as outras 27 cartas do bloco 845 sem teste, e a MEDICAO de
> qualidade de alvo (bloco 848) continua impossivel.

> ## PENDENCIA ABERTA E OBRIGATORIA: MEDIR A QUALIDADE DO ALVO
>
> **Registrado a pedido do usuario (17/09/2026)**: *"registra que a medicao de
> qualidade deve ser feita"*. Nao e "seria bom ter" -- fica como trabalho
> devido, e nenhuma sessao deve dar o assunto por encerrado sem isto.
>
> **O QUE FALTA, concretamente**: o `/choose_target` recebe e loga `actor_code`,
> mas **nao diz DE QUAL PASSO de qual efeito** aquele pedido veio. Sem isso o
> casamento possivel e por `(ator, turno)` -- e num turno cabem anexar DON,
> pagar custo, e alvos de gatilhos DIFERENTES da mesma carta. Foi exatamente
> isso que produziu 2 falsos positivos no bloco 846.
>
> **O campo que resolve**: `step_index` + `purpose` (`custo` x `efeito`) no
> request e no `decision_log`.
>
> **O que isso DESTRAVA**:
> * dizer se o alvo foi o **MELHOR**, nao so se foi do LADO certo (hoje: 36 de
>   39 coerentes com o lado, e nada alem disso);
> * atacar com dado a familia `alvo dentro do efeito` -- **16,4%**, a PIOR
>   categoria medida do projeto.
>
> **Estado**: o bloco 847 corrigiu o COMPORTAMENTO (o bot agora recebe o
> candidato certo pra clicar). A MEDICAO continua impossivel. **Sao dois
> trabalhos e so um foi feito.**

> **MIHAWK CORRIGIDO (17/09/2026, bloco 847)**: a causa nao era nenhuma das 2
> hipoteses anteriores. Reproduzido isoladamente: `order_target_candidates`
> **descartava 28 de 33 candidatos** e devolvia so os 5 DON -- que ela mesma ja
> marcava como "nunca e alvo valido" (chave 9.0). O bot nao tinha o que clicar.
>
> **Culpado**: o filtro `actor_don_target` (criado em 30/08 por achado legitimo
> da Nami OP14-031) mantem SO zonas de DON quando o efeito e `set_don_active`.
> O Mihawk tem esse efeito **e** um CUSTO (`rest_own_card`) que pede uma CARTA
> -- apagada pelo filtro. **Efeito e custo sao perguntas diferentes.**
>
> **Fix pela FORMA**: `_CUSTO_ZONAS` (tipo de custo -> zonas exigidas) entra
> junto no filtro; vale pras **28 cartas** do bloco 845. A ordenacao ja resolve
> a prioridade sozinha (DON tem chave 9.0, custo vem na frente).
>
> **Medido**: Mihawk 33 -> 9 com personagem em 1o e DON em ultimo; **Nami 5 -> 2,
> so DON, SEM REGRESSAO**. `smoke_fast`: 1.430 OK, 0 FALHOU.
>
> **NAO resolve** a medicao de qualidade de alvo (bloco 846) -- falta o
> `step_index`/`purpose` no `/choose_target`. **NAO validado em partida**: a
> proxima CPU x CPU com Mihawk deve mostrar `activate_main` concluindo.

> **"FOI NO ALVO CERTO?" -- NAO DA PRA RESPONDER HOJE (17/09/2026, bloco 846)**:
> pedido do usuario. Resultado honesto: **nenhum bug de alvo estabelecido**, e o
> motivo de nao dar pra responder e ESTRUTURAL.
>
> **Erro meu #1 (corrigido)**: `_detalhe_do_alvo` pegava a PRIMEIRA decisao de
> alvo do (ator,turno) -- mas cabem varias (anexar DON, custo, efeito), e a 1a
> costuma ser DON. Gerava suspeitos falsos. Agora devolve `todas_do_turno`.
>
> **Medicao corrigida**: 36 coerentes, 3 incoerentes, 15 sem regra.
>
> **Erro meu #2**: os 3 incoerentes NAO sao bug -- conferidos no combat log,
> **OP17-054 FUNCIONOU** (`Stussy: Enel can't attack next turn`), **OP15-061** eu
> cruzei o `when_attacking` com o alvo do `on_play` da MESMA carta, e OP12-031
> ficou inconclusivo.
>
> **O LIMITE**: a telemetria grava QUE um alvo foi escolhido, nao a QUAL PASSO de
> qual efeito ele pertence -- o casamento e por `(ator,turno)` e num turno cabem
> DON, custo e varios gatilhos. **O que falta**: `/choose_target` receber e logar
> `step_index`/`purpose` (custo x efeito). **E a MESMA lacuna do bug do Mihawk
> (bloco 844) -- uma correcao resolve os dois.**
>
> Ate la: da pra afirmar **36 de 39 coerentes com o LADO (92%)**, nao se foi o
> MELHOR alvo daquele lado.

> **ALCANCE MEDIDO: 28 cartas, nao 144 (17/09/2026, bloco 845)**: consulta
> pedida pelo usuario. Exposicao ESTRUTURAL da 144 cartas com custo escolhivel
> + efeito que mira algo (`trash_from_hand` sozinho = 100). **Mas cruzando com
> as auditorias reais: `trash_from_hand` conclui 20 de 20** -- o tipo dominante
> FUNCIONA. So `rest_own_card` falha (**Mihawk, 0 de 4**).
>
> **Escopo real**: 29 efeitos em **28 cartas** (1,0% do banco) com custo de
> RESTAR carta propria + efeito mirando outra coisa -- `rest_own_leader_or_stage
> -> bounce/ko` (6), `rest_own_character -> set_active/ko/buff` (11),
> `rest_own_card -> set_don_active/draw/ko` (12). **So o Mihawk foi testado**;
> as outras 27 sao a lista pra conferir quando o fix sair.
>
> **Prioridade**: bug real e confirmado (6 ocorrencias em 3 sessoes), mas 1,0%
> do banco e nenhuma das mais jogadas -- **nao e emergencia**, nao passa na
> frente do laco de ML.
>
> **Metodo**: 2o caso no MESMO DIA de numero grande que era exposicao
> estrutural, nao defeito medido (o outro foi "o bot nunca se defende", bloco
> 837). Contar quantos PODEM quebrar, depois olhar quantos QUEBRARAM.

> **CAUSA RAIZ DO MIHAWK ACHADA (17/09/2026, bloco 844)**: investigado o
> `LogOutput.log` do BepInEx. O bot ativa, o jogo pede **1 alvo**, e ele clica
> **DON um por um, 12 vezes, todos recusados**.
>
> **Causa**: o custo da carta e *"You may rest 1 of your **cards**"* e o efeito
> parseado JA separa (`costs:[{rest_own_card}]` x `steps:[set_don_active]`). O
> jogo pede o alvo do **CUSTO** (qual CARTA restar); o motor manda o alvo do
> **EFEITO** (qual DON ativar). **O bot responde o prompt errado** -- nao e alvo
> mal escolhido, e a LISTA da pergunta errada.
>
> **Discriminante** (687 cliques recusados na sessao, entao recusa sozinha nao
> prova nada -- o Enel tem **328** e FUNCIONA): o Mihawk clicou **12 de 12 em
> `Don`**, nunca um personagem; o Enel varia entre cartas reais. O Enel nao
> sofre porque o efeito dele E sobre DON, entao custo e efeito coincidem.
>
> **ABERTO, nao corrigido**: o fix exige o caminho ao vivo distinguir alvo de
> CUSTO de alvo de EFEITO -- hoje ha uma lista so. **Medir antes de priorizar**:
> quantas cartas tem `costs` com alvo proprio E efeito com alvo diferente.
> **Sinal separado**: os 687 cliques recusados (classe do bloco 813) -- o Enel
> acerta "por insistencia", varrendo candidatos. Nao investigado.

> **2 PARTIDAS: ENEL CONFIRMADO, MIHAWK E O ACHADO ABERTO (17/09/2026, bloco
> 843)**: coleta 100% automatica, `efeitos_error=None` nas duas, corpus
> 698.352 -> **698.567** (+215; simulador em 1.088).
>
> **ENEL funcionando** -- confirmado pelo ESTADO: `DON campo 1->6, 5->6, 5->6`.
> As 2 "falhas" sao `6->6`, com o DON no TETO (DON deck de 6 cartas): e o
> esgotamento previsto no bloco 839, nao bug. O rotulo deveria ser `?` e nao
> `NAO` -- refinamento ja registrado como pendente.
>
> **MIHAWK OP14-020 = achado REAL**, 2 `status=failed` em partida nova (+4 no
> bloco 832 = 6 ocorrencias independentes). **Minha hipotese anterior esta
> DESMENTIDA**: eu tinha escrito que o motor oferecia sem a condicao
> `board_has_cost_gte: 5`; conferido no `state_before`, `OP12-031(c5)` estava em
> campo nos DOIS turnos -- **a condicao estava satisfeita**.
>
> **ESTABELECIDO**: o bot escolheu alvo coerente (`Don` em `own_don_rested`), o
> estado nao mudou (`ativo 1->1` com 5 DON restados), e o **combat log NAO tem
> nenhuma linha da habilidade disparando** (o Enel tem) -- a ativacao nunca
> chegou ao jogo. **NAO estabelecido**: o custo e *"rest 1 of your cards"* e nao
> ha registro de escolha de qual carta RESTAR -- pista, nao diagnostico.
> **Proximo passo**: `LogOutput.log` do BepInEx, que tem a sequencia de cliques.

> **AUDITORIA DIZ QUAL ALVO E POR QUE (17/09/2026, bloco 842)**: pedido do
> usuario. O dado sempre esteve no `decision_log` (`card_code`, `zone`, `rank`,
> **`rank_key`** por candidato) e nao era lido -- a auditoria so dizia
> `alvo=sim/nao`.
>
> **Desfechos agora distintos**: `ATIVADO E CONCLUIDO`, `ATIVADO E CANCELADO
> PELO JOGO` (status=failed), `ATIVADO E NAO SURTIU EFEITO`, `CONCLUIU (efeito
> invisivel do proprio lado)`, `ENVIADO SEM CONFIRMACAO`.
>
> **Saida nova**: turno, carta, gatilho, desfecho, alvo escolhido + zona + rank
> + a chave que decidiu, e **quem ficou em segundo**. *Erro meu corrigido*: a 1a
> versao mostrava os 3 PIORES descartados; pra explicar a escolha quem importa e
> o VICE.
>
> **Medido antes de construir**: 461 de 461 decisoes de alvo escolheram algo --
> "nenhum alvo" nao existe no caminho ao vivo. Cobertura: 17 de 18 disparos com
> detalhe. `smoke_fast`: 1.430 OK, 0 FALHOU.
>
> **Destrava**: a familia `alvo dentro do efeito` e a PIOR do projeto (16,4%) --
> agora da pra ver em quem mirou e por que, caso a caso.

> **AUDITORIA DE EFEITOS = 3o PASSO OBRIGATORIO (17/09/2026, bloco 841)**:
> exigencia do usuario (*"eles tem que rodar como obrigacao, se nao vamos perder
> dados"*). Conferido que JA roda sozinha (prova: `efeitos_2026-09-17T14.04.42`
> gerado na partida de hoje) -- mas **rodar e SER LIDA sao coisas diferentes**: a
> ordem obrigatoria do `CLAUDE.md` tinha 2 passos e uma sessao podia cumpri-la
> sem nunca abrir o relatorio de efeitos, que e onde o Enel e o Streusen foram
> achados.
>
> Registrado nos DOIS espelhos (`CLAUDE.md` + `AGENTS.md`), com a exigencia de
> **conferir `efeitos_error` no recibo** -- a auditoria e best-effort, entao
> campo preenchido = NAO rodou, e isso tem que ser reportado.
>
> **Achado de operacao**: o `server_stdout.log` e **TRUNCADO a cada restart do
> server**. Nenhum dado se perde (os relatorios em `live_runs/` persistem e os
> alertas ficam nos `session_<ts>.log`), mas quem buscar historico ali vai achar
> so a sessao atual.

> **ULTIMO MENU CEGO FECHADO (17/09/2026, bloco 840)**: eram **um**, nao dois --
> `Confirm Revealed Card` tem **opcao unica**, nao ha escolha e pegar a primeira
> esta certo (eu tinha listado como bug sem olhar as opcoes).
>
> **Streusen OP17-050**: *olha 2, posiciona topo/fundo, DEPOIS compra 1*. O bot
> escolhia Fundo em 100% -- enterrava as duas e comprava as cegas. A decisao
> chega **sem dizer quais cartas sao** (o plugin nao manda), entao a regra sai do
> **efeito parseado do ator**: ha posicionamento + `draw` -> topo entrega carta ja
> vista. Sem `draw` devolve None (chutar seria inventar criterio).
>
> **Alcance honesto**: dos 393 efeitos com posicionamento, so **8** tem `draw`.
> Generico na FORMA, estreito no alcance.
>
> `actorCode` ja vinha no request e nao era repassado -- uma linha no server.
> Medido sem regressao: Streusen -> **Top**; Enel -> **Max**; `Trash x Opponent
> Draws` inalterado. `smoke_fast`: 1.430 OK, 0 FALHOU.

> **FIX DO ENEL VALIDADO EM PARTIDA (17/09/2026, bloco 839)**: os dois testes
> definidos antes de rodar passaram. **(1)** 4 de 4 decisoes de opcao escolheram
> `Gain Max Don` com motivo `'ganho de N (mais e melhor)'` -- o fallback cego
> sumiu. **(2)** `activate_main` do Enel **0% -> 80%**; geral 45% -> **89%**.
>
> **Verdade do estado** (nao so a contagem): turno 2 o DON no campo vai de
> **2 pra 6** e **3 DON sao anexados a um personagem**; turnos 3-5 idem.
>
> **A unica "falha" NAO e falha**: turno 6 com DON ja em 6, que e o TETO (o
> lider tem DON deck de 6 cartas) -- a habilidade nao tinha mais o que dar.
> Isso **confirma a ressalva do bloco 838**: `Max` esgota o DON deck no turno 6,
> entao a escolha fina (1 x Max, e QUANDO) e julgamento de VALOR e deveria vir
> do MODELO. Fila do ML, agora com evidencia de partida.
>
> **Refinamento menor NAO feito**: "up to N" com N disponivel = 0 deveria sair
> `?` e nao `NAO` na auditoria. **Seguem abertos**: `Start Placing on
> Bottom/Top` e `Confirm Revealed Card` no fallback cego.

> **CAUSA RAIZ DO ENEL ACHADA (17/09/2026, bloco 838)**: o bot escolhia
> **"Gain 0 Active Don"**. `escolher_opcao_de_efeito` so reconhecia
> `opponent draw`/`trash`/`discard`; todo outro rotulo caia em "primeira
> opcao", e em menu de QUANTIDADE a primeira e sempre o ZERO. **27 de 27
> decisoes de opcao (100%) nesse fallback** -- nao so o Enel (`Start Placing on
> Bottom` 5x, `Confirm Revealed Card` 4x). 2o bug ao lado: `_quantidade` tem
> `max(1,...)` e leria "Gain 0" como 1.
>
> **Fix pela FORMA**: `_ganho_por_quantidade` detecta ganho por verbo, exclui
> `opponent`, entende `max`, e o custo negativo faz o `min` existente pegar o
> maior. Vale pra qualquer menu de quantidade. Medido: `Gain 0/1/Max` -> **Max**;
> `Trash x Opponent Draws` inalterado. `smoke_fast`: 1.430 OK, 0 FALHOU.
>
> **ABERTO**: (a) **"Max" nem sempre e otimo** -- o Enel tem DON deck de **6
> cartas**, entao pegar o maximo cedo pode esgotar; zero nunca e certo, mas a
> escolha fina (1 x Max) e julgamento de VALOR e deveria vir do MODELO; (b)
> `Start Placing on Bottom/Top` e `Confirm Revealed Card` seguem no fallback
> cego, NAO corrigidos; (c) efeito real em partida **nao medido** -- precisa de
> CPU x CPU novo com o Enel.

> **RETRATACAO -- "o bot nunca se defende" era ERRO DE MEDICAO (17/09/2026,
> bloco 837)**: reportado em DOIS commits (834 e 836) como o achado mais caro em
> aberto, e era **falso**. `auditoria_efeitos.py` julgava todas as fases por
> `chosen_action.accepted`, que **so existe em optional/trigger/reaction** -- em
> `counter` a resposta e `counter_ids` e em `blocker` e `blocker_id`, entao os
> dois davam zero por construcao.
>
> **REAL**: counter **56 de 144 com opcao (39%)**, blocker **11 de 21 (52%)**. A
> evidencia estava no mesmo log o tempo todo (`[DEF] counter ... -> 4 cartas`).
>
> **Por que passou**: o numero batia com a expectativa registrada no `CLAUDE.md`
> (defesa e heuristica fixa; `quais cartas de counter` 18,5%), e eu tratei como
> confirmacao em vez de checar -- depois de ter me queimado com o MESMO erro
> duas vezes no mesmo dia (blocos 828 e 832).
>
> **SOBREVIVE**: (a) `blocker` -- **149 de 170 decisoes sem blocker em campo**
> (88%), problema de COMPOSICAO, nao de decisao; (b) `trigger` **0 de 16** numa
> sessao (22% no total), ponta real NAO investigada; (c) o **Enel OP15-058**
> segue de pe (vem de `execution.status` + delta, caminho diferente).

> **NOTA (17/09/2026, fecha o bloco 836)**: ao conferir o ultimo push a pedido
> do usuario, o push estava integro (local == remoto, arvore limpa) mas o
> **docstring do `auditoria_efeitos.py` estava embaralhado** -- editado em tres
> camadas (blocos 832/833/835), a secao `O QUE COBRE` tinha caido DENTRO de
> `LIMITES HONESTOS`, a linha `--json` ficou orfa fora do bloco "Uso:", e a
> tabela de cobertura listava **2 familias quando ja eram 3** (faltavam os
> REATIVOS do bloco 835). A ferramenta rodava normal -- era documentacao errada,
> que neste projeto e problema por si ("nome errado e documentacao errada",
> commit do bloco 833). Reescrito inteiro, com as 3 familias, os limites num
> lugar so e o registro do falso positivo que custou o 18% -> 45%.

> **2 PARTIDAS NOVAS -- OS DOIS ACHADOS REPRODUZIRAM (14/09/2026, bloco 836)**:
> tudo automatico, nada a mao. Corpus 697.709 -> **698.222** (+513, total 743
> de `Arthur_Trabalho_simulador`). A auditoria de efeitos rodou sozinha e
> alertou nas duas partidas.
>
> **1. O ENEL (OP15-058) reproduziu** em partida DIFERENTE, turnos 2/3/4: ativa,
> o jogo CONFIRMA, nada muda. Reproducao independente **tira de "suspeita" e
> torna bug de comportamento**.
>
> **2. A defesa segue em ZERO**: `counter` 0/45, `blocker` 0/44 (antes 0/114 e
> 0/108). E `trigger` apareceu **0 de 16** (antes 8/38) -- piorou ou e outro
> matchup, NAO investigado. **Duas sessoes independentes** dizendo que o bot
> nao se defende nunca; somado a defesa ser heuristica fixa sem consulta ao
> modelo, o quadro fecha.
>
> **PRIORIDADE**: 22% das decisoes, define se o bot toma dano. **Achado mais
> caro em aberto.** Pontos de partida: Enel -> `_execute_step` do
> `activate_main` de OP15-058; defesa -> `should_use_counter` /
> `_should_use_blocker_inner`.

> **3a FAMILIA: OS REATIVOS (14/09/2026, bloco 835)**: `on_ko` e cia. O usuario
> mandou conferir o banco e estava certo -- **30 familias de gatilho**, `on_ko`
> sozinho e **168 cartas**, e o mapa tinha 4. Foi a 3a correcao dele na mesma
> ferramenta, as tres procedentes.
>
> Os reativos GERAM decisao (o jogo pergunta ao bot) e saem com `actor_code`:
> OP11-041 45x, OP16-109 9x, OP14-111 8x. Novo quadro: `on_opp_attack` 52/24,
> `trigger` 46/5, `your_turn` 45/0, `on_ko` 23/4, **`opp_turn` 3/21**,
> **`when_rested` 0/2** -- as duas ultimas sao pontas NAO investigadas.
>
> **Cobertura completa**: `main` (4 gatilhos) + `defense` (5 fases) + reativos
> (por `actor_code`). So ficam de fora `passive`/`game_rules`, que o jogo
> resolve sem perguntar -- nunca contados como falha.

> **AUDITORIA COBRE TODAS AS FAMILIAS (14/09/2026, bloco 834)**: correcao do
> usuario (*"nao e so on play"*) -- `counter`/`blocker`/`trigger`/opcional/
> reacao vem de decisao `defense`, que nao era percorrida (**338 decisoes, zero
> auditadas**). **DOIS achados graves no 1o uso completo:**
>
> **1. O ENEL (OP15-058)**: turnos 2,3,4,5 -- habilidade do lider ativou, o jogo
> CONFIRMOU, e **nada mudou**. Diferente do Mihawk (jogo RECUSOU): duas causas
> distintas, so separaveis porque a auditoria distingue estagios.
>
> **2. O BOT NUNCA COUNTERA NEM BLOQUEIA**: `counter` **0 aceitos / 94
> recusados** (20 sem opcao); `blocker` **0 / 13** (95 sem opcao) -- com ate 6
> counters elegiveis na mao. Isto da MECANISMO ao `quais cartas de counter`
> 18,5%, uma das 3 piores categorias do projeto. **Causa NAO investigada**
> (elegibilidade? limiar? caminho ao vivo?). E 22% das decisoes e define se o
> bot toma dano -- **achado mais caro em aberto**.

> **AUDITORIA DE EFEITOS LIGADA NO AUTO-COLLECT (14/09/2026, bloco 833)**: a
> pedido do usuario. Roda a cada `/outcome`, best-effort (se quebrar, grava
> `efeitos_error` e a partida NAO se perde). Saida em
> `metrics/live_runs/efeitos_<ts>.json`/`.txt`, com `efeitos_nao_concluidos` no
> recibo, e alerta no stdout igual aos outros.
>
> **Correcao de ESCOPO (dele)**: *"nao e auditoria so para efeito de lider, e
> para qualquer efeito"*. Sempre foi -- 50 dos 76 disparos da 1a medicao eram
> `on_play` de PERSONAGEM, so 4 do lider -- mas a flag `--lider` dizia o
> contrario. Renomeada pra **`--codigo`**. Nome errado e documentacao errada.

> **TELEMETRIA DE EFEITO (14/09/2026, bloco 832)**: `auditoria_efeitos.py` --
> pedido do usuario (*"verifique se um efeito foi disparado e concluido ou nao,
> e porque"*). Cruza `decision_log` com `card_effects_db` em 4 estagios:
> OFERECIDO -> ESCOLHIDO -> ALVO -> CONCLUIDO. O dado ja existia
> (`execution.status` + `transition_observation`); ninguem cruzava com os
> gatilhos da carta.
>
> **1o uso ja achou**: `on_play` 100% concluido, **`activate_main` 45%**,
> `when_attacking` 75%. E `--lider OP14-020` (Mihawk) da **0%, 4 de 4
> RECUSADAS pelo jogo** (`status=failed`, turnos 3-6) -- o sintoma que o usuario
> descreveu no Enel, agora com numero e turno. **Hipotese NAO confirmada**: o
> motor oferece/paga sem a condicao `board_has_cost_gte: 5` estar satisfeita.
> **Primeiro alvo da ferramenta.**
>
> **Erro meu pego antes de virar achado**: a 1a versao dizia 18% e 3 dos "NAO"
> eram FALSO POSITIVO -- efeito com mao neutra (OP09-099, e o `deck` nao estava
> no delta), efeito so no oponente (OP09-093) e efeito so de poder (OP16-104).
> Corrigido de forma GENERICA (expectativa vinda dos passos parseados; `deck` no
> delta). 18% -> **45%**, e os NAO restantes sao quase todos o JOGO recusando.

> **NOTA (14/09/2026, fecha o bloco 831)**: os dois untracked que sobraram
> foram pro `.gitignore` depois de o usuario perguntar se dariam problema entre
> as maquinas. **Dariam, se commitados**:
> `metrics/avaliacao_humana/ultimo.json` e passagem entre `avalia_contra_humano.py`
> e `ciclo.py` (linha 249) na MESMA execucao, e os numeros dele ja vao pro
> `ciclo_estado.json` versionado (ciclo 1: 26,9/25,2/0,032; ciclo 2:
> 22,8/22,0/0,032). Versiona-lo nao acrescenta historico E cria o modo de falha
> das duas maquinas -- as duas sobrescrevem por ciclo, JSON nao tem merge, quem
> empurra depois apaga o da outra **em silencio**. Mesmo defeito do
> `q_net.joblib`, sem o ganho que justifica aquele estar no git.
> `.claude/launch.json` e config de editor por maquina.

> **VARREDURA DAS FLAGS DE RUNTIME AO VIVO (14/09/2026, bloco 830)**: a tarefa
> que o bloco 818 deixou explicita (*"vale varrer as outras"*) e ninguem tinha
> feito. O `_dto_to_gs` seta 11 campos, mas **NAO seta 10 flags**:
> `rush_this_turn`, `blocker_this_turn`, `double_attack_this_turn`,
> `unblockable_this_turn`, `banish_this_turn`, `frozen_next_refresh`,
> `can_attack_active_this_turn`, `own_effect_negated_this_turn`,
> `ko_on_opp_blocker_used_this_turn`, `battled_opp_character_this_turn`.
>
> **O erro e o ESPELHO do Shiki**: la a flag ausente deixava o bot PERMISSIVO
> demais (jogada ilegal -> travamento, barulhento); aqui deixa RESTRITIVO demais
> (jogada legal nunca oferecida, **silencioso**). Keyword IMPRESSA funciona (vem
> de `card.data`); keyword CONCEDIDA por efeito e invisivel ao vivo.
>
> **Tamanho medido (nao inflar)**: 35 cartas de 2.839 (**1,2%**) concedem
> keyword por efeito; nos 11 decks instalados, **3**. Lacuna real mas ESTREITA.
> As outras 5 flags nao foram dimensionadas -- registradas como NAO-MEDIDAS.
>
> **Fix exige o PLUGIN** (o `CardDto` nao tem campo de keyword concedida) = C#.
> **E .NET 10.0.400 ESTA instalado nesta maquina** -- da pra recompilar aqui,
> sem depender da Arthur_PC. Nenhum bloco tinha registrado isso.
>
> **Confirmado de passagem**: CPU x CPU NAO treina o modelo (so `ciclo.py`,
> `treinar_q.py` e `treino_continuo.py` escrevem em `q_alvos.jsonl`), mas
> MELHORA o motor achando o que o auto-jogo nao acha -- porque no auto-jogo quem
> julga a legalidade e o nosso proprio codigo.

> **`human_patterns.json` PARA DE APRENDER COM O PROPRIO BOT (14/09/2026, bloco
> 829)**: fecha o achado grave do bloco 827. Criterio confirmado pelo usuario --
> *"tem que separar humano_humano de botxhumano de cpu x cpu"*. Filtro **POR
> LADO**: `cpu_vs_cpu` pula o log inteiro (4), `com_bot` entra so pelo lado
> humano (69), `humano_vs_humano` pelos dois (50); os 55 indeterminados foram
> MANTIDOS (40 deles anteriores a 1a partida com bot).
>
> **Contaminacao medida (A/B no mesmo banco)**: 373 turnos (**15,1%**) e 1.410
> acoes (**18,3%**) eram jogada do bot. O arquivo em producao ainda estava
> defasado (165 logs contra 178). Regenerado com filtro; `--sem-filtro-bot`
> reproduz o antigo; o `meta` agora grava quanto foi descartado.
>
> **`smoke_fast.py`: 1.430 OK, 0 FALHOU** -- verde pela 1a vez na sessao. A
> falha do Imu (bloco 824) era teste de controle cravado num lider que a
> recoleta do bloco 750 tirou do CSV; agora escolhe o lider DINAMICAMENTE
> (OP16-022 hoje), entao acompanha recoletas futuras.
>
> **Relatorio de consequencia** agora diz de qual partida e cada linha (o dado
> ja existia, o `imprimir()` e que descartava). Achado no teste: **o splitter
> numera na ordem do ARQUIVO e o ULTIMO segmento e a partida MAIS RECENTE**.
>
> **ABERTO**: o efeito do filtro na QUALIDADE DE JOGO nao foi medido (exigiria
> `decision_quality_full.py`). E correcao, nao tuning -- mas nao afirmar ganho
> sem medir. Copia pre-filtro guardada pra comparacao.

> **AUTO-COLLECT CONFIRMADO PONTA A PONTA (14/09/2026, bloco 828)**: depois do
> fix do bloco 827, `[AUTO-COLLECT] OK` e `metrics/live_runs/` nasceu com os 4
> arquivos. Coletou o log certo (nao o residuo de 14:00). **Banco 176 -> 178**:
> o download trouxe DUAS partidas e o `split_multigame_log` separou -- **nao e
> duplicata** (md5 diferente do log de 13:57). *Armadilha*: `_p2` significa duas
> coisas no codigo (arquivo companheiro do JOGO x sufixo do SPLITTER).
>
> **Telemetria**: cobertura **98,1%** (51/52 decisoes de main), contra 67,1% na
> sessao anterior. DON comprometido 63, 4 (6,3%) nunca pagaram. O alerta FORTE
> (Gloriosa OP17-046, DON=4, retorno zero) foi auditado no combat log e **NAO e
> bug**: o `[On Play]` disparou (devolveu personagem ao fundo do deck) e a carta
> bloqueou depois.
>
> **ABERTO -- relatorio de consequencia nao recorta por partida**: ele le o
> `decision_log` da SESSAO inteira (2 partidas aqui) e numera turnos sem dizer
> de qual. "turno 2" fica ambiguo justamente no passo que o relatorio exige
> (conferir a jogada no combat log) -- procurei na partida errada por causa
> disso. O `match_id` ja esta em todo registro, so nao e usado no recorte.

> **LOG NAO SALVO = CAMINHO CRAVADO, PELA 11a VEZ (14/09/2026, bloco 827)**: a
> 1a partida CPU x CPU da 2a maquina nao foi pro banco --
> `[AUTO-COLLECT] falhou: nenhum .log encontrado em E:\Games\...`, com o log na
> pasta certa o tempo todo. **Nada perdido**; bancado como
> `Marshall.D.Teach-BY_x_Rocks.D.Xebec-B_2026-09-14T13.57.01` (`cpu_vs_cpu`,
> `winner=p2`, 14 turnos, banco em 176).
>
> **Varredura global** (o que faltou nos blocos 722/748/824, que remendaram o
> MESMO bug 3x amarrado ao arquivo que o revelou): **11 copias em 10 arquivos**.
> Fix da FORMA em `scriptis_da_ia/game_paths.py` -- fonte unica, mesma ordem de
> resolucao do `instalar.ps1`. `smoke_fast`: 1.429 OK, 1 FALHOU (a do Imu,
> pre-existente), sem regressao.
>
> **Telemetria**: recibo agregado NAO existe pra esta partida (`live_runs/` nem
> foi criada -- consequencia do bug, nao de sessao remota). Do `decision_log`:
> **cobertura de 67,1%** das decisoes `main` (49/73) -- 1/3 sem dado pra
> auditar; 1 `engine_error`; latencia max 3.932ms. Os 2 `match_id` **nao** violam
> a invariante (cada um com mulligan->outcome proprio).
>
> **ABERTO E GRAVE -- `human_patterns.json` treina com o PROPRIO BOT**:
> `audit_human_patterns.py` varre `logs/parsed/*.json` e extrai padroes dos DOIS
> lados de TODO log, **sem filtrar `tipo` nem `bot_side`**. Do banco: so **50 de
> 176** sao `humano_vs_humano` (28 `com_bot`, 2 `cpu_vs_cpu`, 96 sem tipo); **59
> tem `bot_side`**. A calibragem que ensina a imitar o humano aprende em parte
> com o proprio bot -- eco, mesmo modo de falha do bloco 820.
> **NAO regenerei** (pioraria, e muda comportamento padrao). **Decisao do
> usuario.** Perguntas a resolver antes: o filtro deve ser POR LADO (em
> `com_bot` o lado humano e dado legitimo), e as 96 entradas sem `tipo`
> precisam ser classificadas primeiro.

> **CPU x CPU HABILITADO NA 2a MAQUINA (14/09/2026, bloco 826)**: responde
> *"posso testar cpu x cpu sem dar paralelismo?"* -- **sim**. CPU x CPU e
> bancada de VALIDACAO, nao caminho de DADO (bloco 816): nao escreve no corpus,
> nao treina, nao toca `q_net.joblib`/`ciclo_estado.json`. Pela regra, e JOGAR,
> e todas as maquinas podem.
>
> **O bloqueio era outro**: a DLL instalada era de 31/08 (67.584 bytes) e **nao
> tinha o Shift+C** (`CPU x CPU` ausente) -- teria "falhado" em silencio, a tecla
> nao fazendo nada. Trocada pela de `BOT/dist/` (69.632 bytes, MD5 conferido).
> *Erro de metodo registrado*: `grep` ASCII da FALSO NEGATIVO em DLL .NET
> (strings sao UTF-16LE) -- conferir em UTF-16.
>
> **Politica corporativa**: `MachinePolicy=RemoteSigned` **vence
> `-ExecutionPolicy Bypass`**; `instalar.ps1` veio com marca da internet e o erro
> mente (*"nao assinado"*). `Unblock-File` resolve.
>
> **Estado**: venv com sklearn 1.9.0, engine server HTTP 200 em :8765,
> `DECKS_DIR` achando os 7 decks reais. **Falta o usuario**: abrir o OPTCGSim em
> Solo vs Self e apertar Shift+C.
>
> **CORRIGIDO -- 2a vez no dia**: `.venv/` (347 MB) e `iniciar_bot.bat` (gerado
> com caminhos ABSOLUTOS da maquina) **nao eram ignorados**. Foram pro
> `.gitignore`. Padrao, nao coincidencia: o que o setup GERA nao estava sendo
> pensado como coisa a ignorar.

> **PORTAO DO CICLO 2 DECIDIDO ATE ONDE DA (14/09/2026, bloco 825)**: rodado
> com `--max-pares 400` (ciclo usa 60), mesma seed -- lotes 1-3 identicos, logo
> e continuacao do SPRT e nao re-sorteio. **66x42 em 108 decididos, LLR +2,336,
> `INCONCLUSIVO` no teto.**
>
> **A distincao que importa**: o SPRT testa H1=65% e nao consegue afirmar essa
> margem. Mas contra 50% o desafiante **e melhor com significancia**: 61,1%,
> binomial **p=0,0264**, IC95 **[51,3%; 70,3%]** (50% fora, 65% dentro). Nao e
> "quase promoveu" -- o LLR oscilou o tempo todo.
>
> **Recorte por lider**: 11 melhoram, **5 PIORAM** (OP15-058 22%, OP14-041 25%,
> OP16-001 40%, OP15-098 44%, OP16-022 45%). Pela regra "qualquer deck", esse e
> o dado que mais pesa contra promover.
>
> **DECISAO ABERTA (do usuario)**: promover o desafiante ou nao. Nada foi
> promovido; `q_net.joblib` inalterado.
>
> **RESOLVIDO -- os "31 erros" nao eram erros**: a chave `'erros'` de `duelar`
> somava par com ERRO **e** par com EMPATE, e os dois `except Exception` de
> `_duelo` DESCARTAVAM a excecao (mesmo modo de falha do bloco 754). Separados
> e instrumentados: **0 crash, 31 empate**. Sem bug escondido.
>
> **ABERTO -- dois descompassos de configuracao** (mudam default, nao mexidos):
> (a) `duelar_sprt` tem `max_pares=200` mas `ciclo.py` passa **60**, e o
> docstring registra rodada que so decidiu em 140 -- o portao do ciclo tende a
> INCONCLUSIVO por construcao; (b) **8 workers estouram a RAM no portao**
> (`BrokenProcessPool`): 16 nucleos mas 15,7 GB, e o portao carrega DOIS
> modelos por worker. Usar **4** no portao (400 pares em 223s).

> **CICLO 2 RODADO NA 2a MAQUINA (14/09/2026, bloco 824)**: primeira execucao
> real do `REGRA_DUAS_MAQUINAS.md`. `Arthur_Trabalho` assumiu como treinadora,
> seed 9202 (sem colisao), corpus 625.361 -> **697.479** alvos, todos com
> `origem` (625.361 `Arthur_PC` + 72.118 `Arthur_Trabalho`).
>
> **Numeros**: erro fora da amostra 0,0438 -> **0,0423**; ganho 79,5% ->
> **80,2%**; concordancia top-1 com o professor **55,1%** (+30,7pp acima do
> acaso); ciclo em **11,5 min** contra 30,0 (mas 8 workers x 4, maquina
> diferente -- **nao mede o laco**, mede hardware).
>
> **PORTAO VIROU DE LADO E NAO DECIDIU**: 5x12 `DESCARTA` (LLR -2,97) ->
> **12x7 `INCONCLUSIVO` (LLR +0,65)**. Parou por **teto de pares** (19
> decididos de 52), nao por limiar -- **nao e promocao**. Nada promovido,
> `q_net.joblib` inalterado. Recorte por lider mostra sinal MISTO (100% pro
> desafiante em OP16-080/OP16-079/EB02-010/OP12-061/OP14-020; 0% em OP14-041).
> **Proximo passo obvio**: repetir com `--max-pares` maior pra decidir.
>
> **ABERTO -- teste obsoleto no `smoke_fast.py`** (1 falha em 1.430; conferida
> como PRE-EXISTENTE no `HEAD` limpo): o teste do Imu (OP13-079) afirma que a
> decklist real esta no banco desde o bloco 609, mas a recoleta de 184 decks
> meta OP16 (bloco 750) deixou **ZERO** decks do Imu em `decklists_raw.csv`.
> Afeta `audit_real_losses.py`, nao o treino. Decidir: recolher a decklist ou
> atualizar o teste.
>
> **CORRIGIDO -- a regra do corpus fora do git nao estava enforcada**: o
> `q_alvos.jsonl` de **444 MB** (e `selfplay_v2.jsonl`, `q_net_desafiante.joblib`)
> aparecia como untracked comum, a um `git add` de entrar no historico pra
> sempre. So a disciplina de nunca usar `git add -A` segurava. Os tres foram
> pro `.gitignore`; `q_net.joblib` (campeao) segue rastreado.
>
> **Portabilidade**: `sim_bridge.py` ainda tinha `DECKS_DIR` cravado em
> `E:\Games\...` no remoto -- agora respeita `OPTCG_GAME_DIR`, mesmo padrao do
> `.csproj` (bloco 722) e do `setup_bepinex.ps1`.

> **REGRA_DUAS_MAQUINAS.md (14/09/2026, bloco 823)**: as regras de trabalhar em
> mais de uma maquina viraram arquivo OBRIGATORIO de inicio de sessao, com
> ponteiro no `CLAUDE.md` e no `AGENTS.md` (regra do espelho). Num arquivo
> proprio e nao em bloco de HANDOFF porque e informacao de INICIO, nao de
> historico -- mesmo idioma de `REGRA_SEM_DUPLICACAO.md`.
>
> Conteudo: a regra (*uma maquina treina por vez; todas geram e jogam*), os tres
> motivos pelos quais treinar em duas quebra em silencio, o token
> (`ciclo_estado.json` + `pull` antes / `push` depois), a tabela git x zip com o
> criterio, os passo a passo de instalar e de passar a vez, o que dizer a uma
> sessao nova, e as armadilhas ja pagas.

> **GIT x ZIP -- a divisao, num lugar so (14/09/2026, bloco 822)**:
> **git** = codigo, `HANDOFF`/`TODO`, banco de `logs/`, `q_net.joblib`,
> `ciclo_estado.json`. **zip pela sessao** = corpus (`q_alvos.jsonl`,
> `selfplay_v2.jsonl`), telemetria (`live_runs/`, `engine_server/logs/`).
>
> CRITERIO, e nao e tamanho: git pra o que precisa de MERGE e HISTORICO; zip pra
> o que cresce sempre e nao tem semantica de merge. O corpus fica fora porque
> cresce a cada ciclo e gz nao faz delta -- 13 MB permanentes por ciclo. O
> codigo fica dentro porque **zip nao funde**: quem descompacta por ultimo
> sobrescreve o outro em silencio.
>
> **CORRECAO**: eu vinha dizendo que o `.git` tinha 1,1 GB e usei isso como
> argumento. Errado -- eram objetos SOLTOS. `size-pack` real: 28 MB, e
> `git gc --prune=now` levou a pasta de 1,1 GB pra **47 MB** em 31s. `du -sh
> .git` nao e o tamanho do repositorio; o numero e `git count-objects -vH`.

> **PASSAR A VEZ ENTRE MAQUINAS (14/09/2026, bloco 821)**: `ciclo_estado.json`
> e versionado e a seed sai de `args.seed + n_ciclo * 101`, entao a outra
> maquina que der `pull` vira ciclo 2 (seed 9202) e **nao colide** com o 9101 ja
> gerado. O estado do ciclo e o TOKEN de quem tem a vez.
>
> FLUXO: aqui push -> la pull -> descompactar o corpus (vem pela sessao, nao
> pelo git) -> `ciclo.py` -> CPU x CPU -> la commit+push (`ciclo_estado.json`,
> `q_net.joblib` se promover, HANDOFF/TODO) -> aqui pull.
> **INVARIANTE: uma maquina so treina por vez.** Gerar partidas as duas podem.
>
> SE AS DUAS TREINAREM: `q_net.joblib` e binario sem merge -- conflito que o git
> nao resolve, e quem empurra depois descarta a geracao do outro em silencio.
>
> **`scikit-learn` NAO estava no requirements.txt** e treinar_q/value_net
> dependem dele (import lazy escondia). Adicionado e FIXADO em 1.9.0: joblib
> serializa objetos do sklearn, entao versao diferente entre maquinas quebra o
> `q_net.joblib` que viaja pelo git.
>
> PENDENTE: `requirements.txt` pede numpy 2.5.2 / joblib 1.6.0 e o instalado
> aqui e 2.2.2 / 1.5.3 -- divergencia pre-existente, nao mexida.

> **CORPUS COM `origem` + TREINO EM DUAS MAQUINAS (14/09/2026, bloco 820)**:
> cada linha do corpus passa a gravar de qual maquina veio
> (`_origem_padrao()`: `OPTCG_ORIGEM` ou hostname). As 625.361 linhas
> existentes foram carimbadas com `Arthur_PC`. Sem isso, duplicata gerada por
> duas maquinas seria indiagnosticavel -- e o custo ja foi medido em 13/09
> (9.865 alvos 100% repetidos, separaveis so porque havia uma origem so).
>
> **ARMADILHA do paralelismo**: a seed de cada partida e `seed * 1_000_003 + i`
> -- duas maquinas com a MESMA `--seed` geram as MESMAS partidas. Usar faixas
> distintas (ex: A=9000+, B=500000+).
>
> **ARQUITETURA**: paraleliza o DADO (as duas geram), centraliza o TREINO (uma
> so). Modelos NAO se fundem; corpus concatena trivialmente. E o portao so
> significa "cada geracao bate a anterior" se houver UM campeao.
>
> **O corpus viaja FORA do git** (ideia do usuario): 381 MB -> 12,7 MB em gz,
> enviado pela sessao. Commitar o gz seria pior -- ele cresce a cada ciclo e nao
> faz delta entre versoes, somando ~13 MB permanentes por ciclo num `.git` que
> ja tem 1,1 GB.

> **BOT EM OUTRA MAQUINA (14/09/2026, bloco 819)**: `BOT/dist/OPTCGBotPlugin.dll`
> commitada pela primeira vez. O fluxo existia desde o bloco 727 e o
> `BOT/.gitignore` ja tinha a excecao, mas o arquivo nunca foi gerado -- entao
> toda maquina nova ainda exigia .NET SDK. Agora: `BOT\instalar.bat` na outra
> maquina copia a DLL pronta, cria o venv e gera `iniciar_bot.bat`.
>
> LIMITE: a DLL e ligada contra as DLLs do JOGO -- se a outra maquina tiver outra
> versao do OPTCGSim (ou o jogo atualizar), e preciso recompilar numa maquina com
> .NET e recommitar. Sintoma: o bot nao reage a nada.
>
> A outra maquina serve pra JOGAR e COLETAR (o banco de logs e versionado e
> volta pelo git), **nao pra treinar**: o corpus (`q_alvos.jsonl`,
> `selfplay_v2.jsonl`) e a telemetria (`live_runs/`) estao fora do git.

> **[Rush:Character] ATACANDO O LIDER -- jogada ILEGAL corrigida (14/09/2026, bloco 818)**:
> o travamento do CPU x CPU em `Attack_SelectingTarget` era o motor propondo
> ataque ilegal. Shiki OP17-048 (`[Rush:Character]`, so pode atacar Personagem
> no turno em que entra) foi mandado atacar o Lider; o jogo recusou e o plugin
> ficou pendurado. O `[DIAG]` deu a pista: `faltam=-1` = `acaActive == null`,
> ou seja nao era selecao de alvo de EFEITO.
>
> CAUSA: `rush_character_only_this_turn` e estado de RUNTIME, marcado onde o
> MOTOR joga a carta. Ao vivo quem joga e o JOGO, e `_dto_to_gs` so copiava
> `just_played` -- a flag ficava False e o lider virava alvo legal. Uma linha em
> `server.py`. `SMOKE FAST OK`.
>
> **CLASSE A VARRER**: toda flag de runtime marcada ao JOGAR uma carta pode
> estar ausente no caminho ao vivo pelo mesmo motivo. Esta foi achada por
> acidente; as outras nao foram procuradas.
>
> **PRODUCAO**: `q_net.joblib` (539.570 alvos) foi sobrescrito por treino
> DIRETO em 13/09 19:58, nao por promocao. O desafiante de hoje perdeu o portao
> 5x12 e NAO entrou.

> **CICLO DE 300 PARTIDAS (14/09/2026, bloco 817)**: concordancia top-1 do Q
> saltou de **+0,4pp** (piloto, 1.799 alvos) pra **+31,7pp acima do acaso**
> (56,1% contra 24,4%, em 15.210 decisoes, corpus de 625.361). Pior familia
> segue `attach_don` (23,5%) -- que e exatamente o que se viu ao vivo (o bot
> anexou DON no lider 4x seguidas sem tirar dano).
>
> **Portao NAO promoveu**: 5x12 em 17 pares, 30 divididos, "DESCARTA
> (equivalentes)". Concordancia alta com forca nao comprovada nao e
> contradicao -- a concordancia mede "escolhe o que a busca escolheria", e a
> busca nunca foi provada otima.
>
> **AS-IS do laco**: 30,0 min por ciclo, e o **treino e 74% disso** (1324s de
> 1800s) porque roda sobre o corpus inteiro a cada geracao. Proximo gargalo
> obvio, agora com numero em vez de sensacao.
>
> **PENDENTE -- nomes legado no banco**: os logs de setembro estao 100% no
> padrao e o indice tem 0 ponteiros quebrados. Fora do padrao ha ~40 arquivos
> LEGADO: 33 `parsed/` de junho (`<timestamp>_autosaved.json`, anteriores a
> convencao) e 7 em `raw/`/`decks/` com nome de jogador ou sem sufixo de cor.
> NAO renomeados: exigiria atualizar `index.json`, os recibos de
> `metrics/live_runs/` e relatorios de auditoria que citam nomes -- risco de
> quebrar referencia por estetica. Fazer so com backup e reconferindo ponteiros.
> (O sufixo `_pN` NAO e desvio: e desempate de timestamp igual.)

> **CPU x CPU NO SIMULADOR -- Shift+C (13/09/2026, bloco 816, ideia do usuario)**:
> o plugin so roda em `GameStyle.SoloVSelf` (um cliente, dois assentos) e todo o
> driver decide a vez por `iPlayerAction == BotPlayerIndex` -- entao CPU x CPU e
> o bot assumir sempre quem o jogo mandar agir.
>
> **Nao e caminho de DADO**: uma partida no simulador leva 15-30 min de relogio
> contra ~0,6s no motor; centenas seriam dias. E **bancada de VALIDACAO** -- todo
> bug de 13/09 (309 cliques recusados, o custo que sumia do parse, o NameError
> ao vivo) era invisivel ao auto-jogo, porque la quem julga legalidade e o nosso
> proprio codigo. O simulador e o juiz que o motor nao tem.
>
> Banco: rotulo PROPRIO `tipo='cpu_vs_cpu'` com `bot_side=None`
> (`parse_combat_log.py --cpu-vs-cpu`). Nao reusa `--sem-bot`, que gravaria
> `humano_vs_humano`. A normalizacao do `collect_latest_match.py` (escrita 1h
> antes) transformaria `cpu_vs_cpu` em `p1` silenciosamente -- pego antes de rodar.
>
> PENDENTE: rodar de fato uma partida CPU x CPU e conferir que os dois lados
> alternam sem travar, e que o log entra no banco com o tipo certo.

> **PARSER: custo com ALTERNANCIA "<X> or DON!! cards" (13/09/2026, bloco 815)**:
> medindo as 162 recusas em cartas comuns, o Kin'emon ST32-001 saia do parse
> **sem custo nenhum** ("rest 1 of your (Slash) attribute Leaders **or** DON!!
> cards:" -- o regex exigia `of your don!!` colado). 78 de 82 cliques recusados
> numa partida. Censo global: 80 cartas usam a gramatica, 59 ja capturadas, 20
> sao artes alternativas, **1 carta real faltava**. Corrigido pela FORMA, com
> `rest_own_card` + `don_allowed` em vez de um tipo inedito (que viraria custo
> ignorado em silencio). Diff: 1 carta, PERDEU=0.
>
> **E o filtro de DON do bloco 814 estava ESCONDENDO UM ALVO VALIDO aqui** -- o
> custo permite DON, o parse nao mencionava, o filtro removia. Um filtro que le
> o efeito parseado e tao bom quanto o parse. Fechado: ele passa a ler as FLAGS
> do custo, nao so o `type`.
>
> ABERTO: familia `then_trash` (o descarte da mao nao e um step com alvo, entao
> a ordenacao nao sabe que a MAO e a zona pedida); Mihawk OP14-020 (127
> recusas, precisa do plugin dizer QUAL selecao esta aberta); Coffin Boat
> OP14-039 (92, nao investigado).

> **ALVO EM DON CONSERTADO PELA RAIZ (13/09/2026, bloco 814)**:
> `order_target_candidates` exclui as zonas de DON quando o efeito do ator nao
> menciona DON em nenhum step nem custo (detectado pelo vocabulario do parser,
> nao por lista de cartas). Espelho do fix de 30/08 (Nami), que ja tratava o
> caso oposto. **Era a QUARTA vez que o mesmo bug era remendado** (21/07, 02/08
> Luffy, 13/08 Doc Q) -- as tres anteriores mexeram em PRIORIDADE; esta mexe em
> VALIDADE. Dois testes do smoke codificavam a permissividade antiga e foram
> reescritos pra garantia mais forte. `SMOKE FAST OK`.
>
> Cobre 146 dos 248 cliques recusados da partida. **ABERTO**: os 44 do Mihawk
> OP14-020 -- na mesma carta, "rest 1 of your cards" (DON invalido) e "set up to
> 3 DON!! active" (so DON serve) sao indistinguiveis, porque a funcao nao recebe
> QUAL selecao esta em aberto. Exige o plugin informar o passo. Nao tentado.
>
> Tambem: a linha de atalhos voltou pra popup do bot, a pedido do usuario.

> **ABERTO -- 248 CLIQUES DE ALVO RECUSADOS NUMA PARTIDA (13/09/2026, bloco 813)**:
> investigando os 5 `execucao falhou` da primeira partida ao vivo, o log do
> plugin mostrou **248 cliques de alvo recusados pelo jogo, 154 deles (62%) em
> cartas de DON**, e 2 confirmacoes com ZERO alvos. Os 5 alertas eram so a
> ponta. Atores: Yasopp OP17-031 (102), Mihawk OP14-020 (44), OP06-038 (36),
> OP13-040 (16), OP17-039 (5), OP17-118 (3).
>
> CAUSA: o plugin manda TODAS as zonas como candidatas (incl. `own_don`,
> `opp_don`) porque algumas cartas miram DON; quem filtra deveria ser
> `order_target_candidates` (`sim_bridge.py`) e ela nao filtra. Agravante:
> `BotDriver.cs` desiste apos 2 recusas seguidas e confirma com zero alvos
> quando a contagem e livre.
>
> **NAO CORRIGIDO a pedido do usuario** ("eu jogo depois vc conserta"). Conserto
> pela FORMA do efeito, nao amarrado as 6 cartas que apareceram.
>
> (O parse do Mihawk NAO esta errado: o texto e "rest 1 of your cards" + "if
> there is a Character with a cost of 5 or more" -- condicao de tabuleiro, nao
> filtro da carta a restar.)

> **CAMINHO AO VIVO CONSERTADO (13/09/2026, bloco 812)**: o usuario foi jogar e
> nada funcionava. (1) `BepInEx/` tinha sumido do jogo; (2) `setup_bepinex.ps1`
> tinha caminho FIXO pra uma maquina antiga e morria justamente quando era
> necessario -- agora PROCURA o jogo; (3) **regressao minha**: a trava de
> ingestao (`--bot-side` obrigatorio) derrubava TODA coleta ao vivo, porque
> `collect_latest_match.py` nao repassava o lado que ele **ja tinha**; (4)
> `NameError: bridge` fazia todo `/choose_effect_option` estourar 500 ao vivo;
> (5) popup do bot encolhida a pedido dele.
>
> Partida salva no banco a mao: `Dracule.Mihawk-G_x_Rocks.D.Xebec-B_2026-09-13T22.16.03`.
>
> PENDENTE: 5x `execucao falhou: estado inalterado` na partida (Q escolhendo
> mal ou bug de execucao -- nao investigado); `pos_log_novo.sh`/
> `human_patterns.json`; telemetria da partida nao lida (log entrou a mao,
> sem recibo automatico).

> **UM CEREBRO SO (13/09/2026, bloco 811)**: o usuario pegou a duplicata numa
> pergunta minha (*"qual cerebro o bot usa na partida contra voce?"* -- que num
> projeto de UM MOTOR SO nao deveria poder existir). Havia duas funcoes
> decidindo a mesma acao, com `USA_Q` (default = comportamento antigo)
> escolhendo entre elas. **A busca saiu de decidir**; ela continua como
> PROFESSOR na coleta. `USA_Q`/`usa_q` removidos do projeto.
>
> Consequencias: (a) **o bot joga pior agora** -- o Q perdeu 0x13 e ficou
> +0,4pp acima do acaso; e o ponto, so decidindo ele gera dado das proprias
> escolhas; (b) o **portao virou geracao x geracao** (campeao x desafiante),
> porque sem a arvore decidindo nao ha com o que duelar; (c) a concordancia
> ganhou `escolhida_por` pra nao virar circular (~100% por construcao) no modo
> bootstrap; (d) o teste do smoke que afirmava "a escolha vem da busca" foi
> REESCRITO pra invariante nova. `SMOKE FAST OK`.
>
> **CICLO RODAVA DUAS VEZES (bloco 810)**: `treino_continuo.py` re-executa o
> processo no import (`PYTHONHASHSEED`), e o `ciclo.py` o importa dentro de
> `portao()` -- a re-execucao relancava o ciclo do zero no meio. 9.865 alvos
> duplicados (100% repetidos) removidos, corpus de volta a 549.435. Trava no
> t=0. Licao: import com efeito colateral de processo nao pode ficar no meio.

> **A METRICA QUE DECIDE PASSOU A EXISTIR (13/09/2026, bloco 809)**: o
> `treinar_q.py` ja dizia na propria saida que o que decide e *"se ele escolhe a
> mesma acao que o professor escolheria"* -- e esse numero **nunca foi
> calculado**. Faltavam tres campos no corpus (`decisao`, `acao`, e a
> `escolhida` que no modo bootstrap saia SEMPRE False porque a coleta ocorre
> antes da decisao). Construidos, mais a concordancia top-1 fora da amostra por
> familia no `treinar_q.py`.
>
> **Piloto (1.799 alvos, NAO e o corpus de producao de 549.435)**: erro
> 0,1858 => "erra 45% menos que a media, APRENDEU"; concordancia **25,8%**
> contra **25,4% do acaso** = **+0,4pp**. As duas reguas discordam sobre o mesmo
> modelo. Pior familia: `attach_don` 6,7%. Ja explica o portao 0x13 do bloco
> 801 -- e o erro de 0,0453 nunca teria avisado.
>
> **O numero de producao sai no ciclo 2** (as linhas ja gravadas nao tem
> `decisao`). Pode ser muito melhor: a quantidade de dado e a alavanca que ja
> se mediu mover (10,0% -> 31,8% com 23x de corpus).

> **TELEMETRIA DO CICLO FECHADA (13/09/2026, bloco 808)**: quatro buracos, um
> deles meu. (1) **`avalia_contra_humano.py` nao era chamado por ninguem** --
> o cabecalho dele afirmava "chamado pelo `ciclo.py` na etapa 4" e era falso;
> agora e a **etapa 5** e o numero entra no historico, com serie entre
> geracoes. (2) **`--limpar-checkpoint` nao existia** apesar de a saida de todo
> ciclo promovido mandar roda-lo; implementado, conta os logs de bot que
> entraram no banco desde o checkpoint mas NAO trava (declaracao do usuario nao
> e medicao). (3) **portao sem recorte POR LIDER** -- regra obrigatoria, e
> `_duelo` ja conhecia os dois lideres e os descartava; agora credita o par
> decidido aos dois. (4) **AS-IS do laco**: tempo por etapa no historico. Mais
> o **guarda-corpo** (`decision_quality_full.py`) rodando na promocao, sem
> veredito automatico, e `--workers` que estava hardcoded em 1.
>
> Ciclo 1 rodou com o codigo ANTERIOR -- tudo isto vale do ciclo 2.
>
> AINDA FALTA na telemetria: quantos alvos Q vieram de posicoes NOVAS (corpus
> crescendo com posicao repetida e eco, nao dado -- mediu-se 95,3% distintas
> uma vez e nunca mais) e POR QUE o par foi dividido (iniciativa ou matchup).

> **MEDIDO 13/09/2026 (bloco 807) -- o modelo de oponente**: `avalia_contra_humano.py`
> (etapa 4 do `ciclo.py`) passou a rodar de verdade. Ele acerta **26,9%** da mao
> real do adversario em 149 posicoes contra humano; o controle de **lider errado
> cai pra 0,5%** (o instrumento e real) e o controle **sem observar** fica em
> **25,2%** -- ou seja, assistir a partida agrega so **+1,7pp** sobre conhecer a
> decklist. O sorteio uniforme que ignora o comportamento do oponente (Fase 4
> candidata, bloco 781) deixou de ser observacao sobre o codigo e virou numero.
> **Nao promovido a prioridade**: a medida irma diz que abrir a mao inteira move
> a avaliacao so 0,0320 de mediana, entao ate a leitura perfeita renderia pouco.
>
> PENDENTE no mesmo arquivo/ciclo: `ciclo.py --limpar-checkpoint` e citado na
> saida e **nao existe**; o Q segue candidato (perdeu 0x13 pra arvore); 58
> registros tem as duas maos e lado desconhecido.

> **PENDENTE, NAO rodado (10/09/2026)**: a confirmacao da promocao da
> geracao 4 (`confirma_gen4.py`, 150 pares / 300 partidas com os MESMOS
> dois modelos) foi disparada e **INTERROMPIDA a pedido do usuario**, que
> ia sair e nao queria deixar a maquina rodando sem supervisao. **Nao ha
> resultado.** O campeao foi restaurado a mao e CONFERIDO por hash:
> `metrics/value_net.joblib` = `1243016abfb3` (gen4), com `git status`
> limpo.
>
> **Rodar quando houver ~45 min de maquina livre:**
>
> ```
> cd scriptis_da_ia && python confirma_gen4.py
> ```
>
> (com `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1`, senao
> os workers disputam os 2 nucleos -- ver bloco 759). Ele troca o campeao
> pelo antigo e restaura no `finally`; se morrer no meio, recuperar com
> `git checkout b7c879b -- scriptis_da_ia/metrics/value_net.joblib`.
> Hashes: gen4 = `1243016abfb3`, antigo = `1628efa6671e`.
>
> **Por que importa**: a promocao passou por MARGEM (11x3 em 14 pares
> decididos, Wilson 52,4% contra portao de 50%; 10x4 teria dado 45,4% e
> reprovado). Ate esta confirmacao rodar, **a geracao 4 e evidencia
> sugestiva, nao estabelecida**.

> 13/09/2026 (bloco 800): **O METODO ERA PESADO** — achado do usuario: *"nao faz
> sentido cortar [arvores], isso vai fazer perder qualidade, deve ter outra coisa
> gastando tempo, ou entao estamos usando um metodo pesado"*. Estava: o modelo era
> **47% do tempo** (300 arvores em Python, ~10 ms/previsao). Eu tinha proposto
> cortar arvores, que custava **49% de erro a mais**; ele recusou e apontou a
> causa certa.
> **REDE LEVE (a linha NNUE da lista dele)**: erro **0,0554 contra 0,0676** das
> arvores (**18% MENOS**) e **0,100 ms contra 8,47** (**85x**). Sem troca entre
> qualidade e velocidade. Criterio fixado ANTES de medir. Abre a atualizacao
> incremental do NNUE, que so existe sobre rede.
> **ANTES (bloco 799)**: o alvo virou **BOOTSTRAP** — o DQN nao precisa de busca
> pra formar alvo, ~8 clones por decisao contra ~64, coleta de **11,37 -> 3,02
> s/partida**. E `_ordena_pelo_modelo` saiu quando o Q decide (30% do tempo).
> **⚠️ ERRO DE METODO MEU**: `TaskStop` **nao para um laco de shell** — matei o
> shell, os python seguiram; matei os python, o laco lancou a fatia seguinte. **A
> coleta rodou durante quase todas as medicoes do dia**, inclusive a que apresentei
> como "maquina limpa". Os tempos 8,06 / 11,37 / 2,52 / 1,41 / 2,86 estao inflados.
> **Regra: CONFERIR que parou, via `Get-CimInstance Win32_Process` pela linha de
> comando** — nao confiar no retorno do stop. Efeito colateral: corpus de 40.678
> para **539.570 alvos**, sem ninguem decidir.
> **PENDENTE**: (2) concordancia da rede com a arvore e (3) tempo real — erro
> menor NAO garante ordenacao melhor.

> 13/09/2026 (bloco 797): **O LACO DE TREINO ESTAVA QUEBRADO** — achado ao
> perguntar "ja podemos treinar?". `_duelo` punha campeao e desafiante lado a
> lado por `value_net_weight`, o desenho SOMADO que **nao decide mais nada**
> (peso 0,0 e a heuristica saiu). O portao colocaria **dois bots IDENTICOS**
> frente a frente: todo par empata, o SPRT nunca decide, e o laco rodaria a
> noite inteira **sem promover uma geracao**.
> **RELIGADO**: gera alvos Q (`--q-out`), treina o Q (`treinar_q.py`), duela
> trocando o **artefato que decide** (`q_net_path` por lado) e promove o Q.
> Verificado: Q x arvore deu 1x1 com 2 divididos em 4 pares — antes seria
> empate total por construcao.
> **LIMITE DE MAQUINA**: portao com 2 workers quebra (`BrokenProcessPool`), e
> **nao e o Q** — sao **2,4 GB de RAM livres de 11,9**. Usar `--workers 1`.
> **A CURVA NO CORPUS NOVO NAO DECIDE**: 414/828/1.657 estados dando
> 0,6936 → 0,6764 → 0,7203. O script cravou "aprende", **eu nao aceito**: a
> curva **desce no meio** (ruido) e 1.657 estados e minusculo perto dos 18.455
> em que o velho ja saturava (0,8082). **O que decidiria**: corpus novo ate ~18
> mil estados e comparar no MESMO tamanho — ~1.300 partidas, **~40 min** a 1,87
> s/partida.

> 13/09/2026 (bloco 796): **A ARVORE SAI DO CAMINHO DE DECISAO** — o modelo Q
> responde sem simular. Veio da pergunta dele (podar perde qualidade? ha
> alternativa que nao seja arvore?) e do **DQN da lista que ele trouxe**. A
> arvore materializava ~64 estados por decisao (77% do tempo); o Q responde de
> (estado, acao) numa consulta em lote. **A arvore virou o PROFESSOR**: o valor
> que ela calculava simulando E o alvo Q.
> **CONSTRUIDO**: `acao_features` (24, sem identidade de carta), `q_features`
> (77+24), `q_valores` (lote, `state_features` calculada uma vez), coletor via
> `--q-out`, `treinar_q.py` (GroupKFold POR LIDER + controle que pode falhar),
> e a decisao pelo Q com queda pra arvore se o Q nao existir.
> **MEDIDO**: corpus **31.056 alvos / 120 partidas / 16 lideres**; o Q erra
> **66,2% menos que prever a media** fora da amostra. Velocidade **6,61 → 1,65
> s/partida (4,00x)**; AS-IS **6,20 → 1,87**.
> **CONCORDANCIA 49,7%** — e o numero de capa engana: das 68 divergencias,
> **52,9% sao EMPATE** na regua do professor (perda < 0,01) e so 8,8% sao caras,
> ou seja **4,3% das decisoes pioram de verdade**. Top-2 do Q contem a escolha
> do professor em 74,5%.
> `smoke_fast`: **0 falhas**. **RESSALVA**: isto mede concordancia com o
> professor e velocidade, **nao mede FORCA** — o portao continua sem rodar.

> 13/09/2026 (bloco 794): **AS DUAS ULTIMAS HEURISTICAS DE DECISAO SAIRAM.**
> **SE counteria**: era `gasto < valor_protegido`; agora compara a soma de
> `delta_gastar_da_mao` das cartas que serao gastas contra `delta_perder_vida()`
> (ou `delta_remover(alvo)` defendendo personagem). `alvo` passou a viajar ate a
> decisao. **Pagar custo opcional**: o limiar de constantes (60, +25, +peso*15)
> **saiu** — a busca ja avalia a acao INTEIRA, custo e efeito juntos, entao o
> portao so pre-filtrava com informacao pior. **Corrigido pelos testes**: a 1a
> versao pagava sempre que houvesse modelo e 2 testes reprovaram, os dois casos
> de **pagar por NADA** — isso e VIABILIDADE, nao valor. Ficou: **o modelo
> decide o QUANTO, a regra decide o SE EXISTE**.
> **ESTADO**: nenhuma decisao de VALOR do motor e mais escrita a mao. O que
> sobra de heuristica e regra de JOGO e a degradacao sem modelo. `smoke_fast`:
> **0 falhas**. **Nada passou por duelo.**

> 13/09/2026 (bloco 793): **INCERTEZA POR QUANTIL — construida, medida e
> REPROVADA.** Veio de duas perguntas dele, as duas certas: *"porque vc esta
> fazendo elas decidirem em probabilidade de vitoria se eu te dei uma lista de
> metodos?"* (tudo que construi sai da mesma consulta ao mesmo modelo, e a
> lista tem a peca que falta — GPR entrega a INCERTEZA junto da previsao) e
> *"porque diversos modelos?"* (tres surrogates = tres reguas concorrentes, o
> "dois motores" proibido; PCE/RSM nem decidem, sao ferramenta de analise).
> Tentativa com UM modelo so: cabecas de quantil 10%/90% no mesmo bundle.
> **RESULTADO: `incerteza` = 0,5000 EXATO em toda posicao** — q10 prediz 0,0
> constante, q90 prediz 1,0 constante, porque o alvo do corpus tem **2 valores
> distintos**. Quantil de alvo binario e sempre [0,1]. Ligada, tornava **8 de 8**
> decisoes de defesa um empate. Desligada nos dois lugares, entrada em
> `REPROVADOS.md`.
> **ERRO CONCEITUAL MEU, registrado**: confundi dispersao do RESULTADO com erro
> da ESTIMATIVA — a segunda exige incerteza de MODELO (posterior de GPR, ou
> ensemble/bootstrap), nao quantil do rotulo.
> **O problema segue aberto**: a defesa decide comparando deltas da ordem de
> 0,06 sem nocao de erro. **GPR agora tem fundamento MEDIDO**, com a ressalva de
> O(n^3) contra 73.821 estados. `smoke_fast`: 0 falhas.

> 13/09/2026 (bloco 792): **AUDITORIA DAS REGRAS** (pedido dele) — **mais TRES
> bloqueios** alem do revogado no 791: (1) a **segunda copia** da regra circular
> ("so entao a busca pode encolher", "a heuristica sai por partes, cada remocao
> passando pelo portao") → **revogada**; (2) `VALUE_NET_WEIGHT` "exige
> autorizacao" → marcado **legado**; (3) **`--explorar` com default 0.0, a
> exploracao estava DESLIGADA** → **ligada (0.1)**. O terceiro e grave: ele
> pediu que o ML fosse testando as alternativas, e o bot **nunca tentava o que
> nao escolheria** — sem exploracao o auto-jogo e eco e nada emerge.
> **A DEFESA PASSA A SER DECIDIDA PELO MODELO**: medida nova
> `delta_perder_vida` (quanto piora ao levar um golpe) — era a ponta que
> faltava. Bloqueia se `delta_remover(blocker)` doer menos que
> `delta_perder_vida()`, os dois em probabilidade de vitoria, **sem limiar**.
> **UM BUG MEU pego por teste antigo**: tratei "o blocker sobrevive" como custo
> zero olhando so o ataque ATUAL; corrigido pra `_pior_ataque_restante_este_turno`.
> 3 testes de limiar repontados pra degradacao, com **gap honesto** registrado:
> `delta_remover` nao dispara o [On K.O.] da carta, entao o modelo ainda nao ve
> que blocker com On K.O. e mais barato de sacrificar.
> `smoke_fast`: **1436 checagens, 0 falhas**. Tempo 6,20 s/partida (8,04 no
> inicio do dia).
> **AINDA HEURISTICO**: SE counteria (`_should_use_counter_inner` — o conjunto
> de cartas so e conhecido em `pick_counters`) e `_worth_paying_optional_costs`
> (precisa medir o BENEFICIO do efeito, que nenhuma medida do `value_net` cobre).

> 13/09/2026 (bloco 791): **A REGRA QUE TRAVAVA O PROJETO, ACHADA E REVOGADA.**
> Ele perguntou *"tem alguma regra aqui no projeto?"* — tinha: a secao "COMO
> fazer — por partes e COM PORTAO, nunca de uma vez" (10/09) dizia
> *"substituicao nao autorizada em bloco"* e *"**enquanto o ML nao ganhar UM
> duelo sequer, nao ha o que substituir**"*. **Circular: nunca libera**, porque
> o ML nao vence duelo enquanto a heuristica decide por ele. Contradizia "O QUE
> EXISTE NAO E SAGRADO" (12/09) no mesmo arquivo. Revogada; no lugar: tirar a
> heuristica e o TRABALHO, o portao MEDE DEPOIS e nao e pre-requisito.
> **A HEURISTICA SAIU DO PONTO DE DECISAO**: `main_phase` chama
> `sem_pontuacao=True`; quem ordena o shortlist e o MODELO e quem encerra o
> turno e a BUSCA contra `PASS_ACTION`, nao mais o `ACTION_SCORE_FLOOR`.
> **MEDIDO**: 6,51 → **5,80 s/partida** (−10,9%); acumulado no dia **8,04 →
> 5,80 (−28%)**. `avaliar_carta` de **26,5% / 34.367 chamadas** para **1,8% /
> 20.211** (o resto vem de caminhos fora da decisao). A funcao mais cara do
> motor agora e o **MODELO**. `smoke_fast`: **0 falhas**.
> **PENDENTE**: nada passou por duelo; o portao segue escrito e nao rodado — e
> agora ele mede DEPOIS.

> 13/09/2026 (bloco 790): **A HEURISTICA SAI DE DENTRO DA BUSCA.**
> `_generate_and_score_actions(sem_pontuacao=True)` na arvore — as 4 pontuacoes
> caras nao sao mais calculadas em cada no. Fundamento: 96,4% dos scores
> estaticos eram jogados fora (bloco 789).
> **MEDIDO (AS-IS)**: **8,04 → 6,51 s/partida (−19,0%)**; modelo de 17,1% para
> **22,9%** do tempo (ele virou a maior parte do trabalho, que e a direcao);
> prova de lethal 7,3% → 1,6%; `avaliar_carta` **saiu do topo do perfil**, que e
> o teste registrado pra saber se a substituicao aconteceu. `smoke_fast`: **0
> falhas**.
> **REGRA CORRIGIDA POR ELE**: eu tinha registrado `REGRA_O_CRITERIO_EMERGE.md`
> com uma frase MINHA ("voce protege o que existe por reflexo"); ele corrigiu —
> *"a regra nao e essa, isso ai vc inventou"*. O que ele disse e sobre o
> SISTEMA, nao sobre mim: **o criterio nao existe no desenho, e resultado do bot
> jogando** — o ML testa as alternativas e o criterio vai surgindo. Arquivo
> reescrito, ponteiros e memoria corrigidos, e a correcao registrada dentro do
> proprio arquivo.
> **PENDENTE**: a heuristica ainda roda no PONTO DE DECISAO real (shortlist e
> piso). E **nada passou por duelo** — o portao de 3 celulas segue escrito e nao
> rodado.

> 13/09/2026 (bloco 789): **O USUARIO ESTAVA CERTO — a heuristica cara nunca
> saiu.** Medido: **13.240 scores estaticos calculados, 480 chegam a uma
> decisao, 96,4% jogados fora**; `avaliar_carta` e **26,5% do tempo** (34.367
> chamadas). O modelo foi posto POR CIMA da heuristica e o custo dela continua
> pago inteiro. **Regra nova**: quando o modelo decide, a heuristica nao deve
> nem ser CALCULADA — se `avaliar_carta` aparece no topo do perfil, a
> substituicao nao aconteceu.
> **DOIS ALVOS MEUS ERRADOS**: a prova de lethal e **6,5% do tempo** (0,16 ms
> cada) — a transposicao foi construida, deu 81,8% de acerto, **ganho zero** e
> foi REVERTIDA; construi antes de testar a premissa, contra a regra que eu
> mesmo escrevi no 787. A clonagem ficou 3,07x mais barata mas e ~6% do tempo.
> **O INSTRUMENTO ESTAVA MENTINDO**: `as_is.py` cronometrava sem aquecer o
> processo, e os primeiros ciclos sao MAIS RAPIDOS que o regime estavel (9,60 →
> 15,30s na mesma carga). **Os "6,3s/partida" e "portao em 13 min" que reportei
> estao RETIRADOS.** Corrigido: aquecimento descartado, 3 voltas, variacao
> reportada junto.
> **CATALOGO DE SURROGATE MODELS registrado** (ele mandou duas vezes): PCE,
> Processo Gaussiano/Krigagem (da a INCERTEZA da previsao), DNN, RSM, e
> LHS/Quasi-Monte Carlo. Correcao de escopo: a ressalva "QMC nao se aplica" era
> sobre o rollout, que saiu no 785 — agora LHS/QMC valem pra escolher QUAIS
> posicoes simular pra treinar o substituto.
> **CUSTO DA ARVORE** (processo limpo): 6x3 hoje 10,6-15,5s · 4x3 8,9s · 6x2
> 4,6s · 4x1 1,7s · **3x3 (antes do item 2) 5,8s** — o item 2 dobrou o custo.
> **PORTAO NAO RODOU**: interrompido pelo usuario, corretamente.
> **PROXIMO PASSO**: tirar a heuristica de DENTRO da busca — nao pagar pelo
> caminho que nao vai ser usado.

> 13/09/2026 (bloco 788): **clonagem 3,07x mais barata** + **BUG DE FIDELIDADE
> achado na conferencia campo a campo**.
> `Card.__deepcopy__` listava 36 campos com um `getattr`+`setattr` cada (~8M de
> chamadas em 2 partidas); virou `dict(self.__dict__)`, uma operacao em C.
> Micro-benchmark: **0,203 -> 0,066 ms por clone de estado (3,07x)**; no AS-IS,
> clonagem de **14,0% para 6,1%** e `getattr` de 10,3M para 2,7M chamadas.
> **O BUG**: dois campos existiam nas cartas e NAO estavam na lista, entao todo
> clone os perdia — `_am_used_turn` ([Activate: Main] once_per_turn) e
> `ko_on_opp_blocker_used_this_turn`. **A linha simulada podia reativar a
> habilidade que a partida real ja tinha gasto no turno**, e a busca
> superestimava justamente as linhas dessas cartas.
> **A MEDICAO QUASE FOI LIDA ERRADO**: a primeira leitura deu +7,7% e pareceria
> "a otimizacao deixou mais lento". Isolando (controle de aquecimento + A/B/A/B
> em 6 partidas): as **partidas MUDARAM** em 2 das 6 seeds e ficaram mais LONGAS
> (12->17 e 11->22 turnos). O clone ficou 3x mais barato E o total subiu, sem
> contradicao — um numero agregado nao conseguia dizer isso. Regras dos blocos
> 779 e 780 cobrando na mesma mudanca.
> **ISOLAMENTO**: `clone_perde_once_per_turn`, bandeira por jogador que viaja no
> `memo` do deepcopy (`Card` nao enxerga o jogador). ⚠️ **o portao TEM que medir
> esta correcao numa celula propria** — muda partida e e da familia que custou
> 9x15 no bloco 779.
> `smoke_fast`: **0 falhas**, teste permanente novo. Tempo: **~6,1-6,4s/partida**
> (o ganho do clone pagou as partidas mais longas). Portao de 240: ~13 min com 2
> workers.
> **PROXIMO se a velocidade voltar a incomodar** (pelo AS-IS): prova de lethal
> (`hits_after_best_defense` 261.332 chamadas, `search_alloc`) e `state_features`.
> **PENDENTE — ITEM 1, MEDIR**: blocos 785-788, nenhum duelo.

> 13/09/2026 (bloco 787): **AS-IS OBRIGATORIO** (pedido do usuario, teoria de
> Sistemas de Informacao: AS-IS -> TO-BE -> AS-IS de novo). Regra em `CLAUDE.md`
> **e** `AGENTS.md` (espelho) + ferramenta nova `scriptis_da_ia/as_is.py`, que
> grava historico versionado em `metrics/as_is/` e compara com `--comparar`.
> **POR QUE ERA NECESSARIO**: um diagnostico MEU do bloco 784 ("falta avaliacao
> incremental das features") continuou sendo repetido depois que o Monte Carlo
> saiu e a composicao do tempo mudou — inclusive pra decidir NAO fazer algo.
> **O gargalo real, medido**: consulta ao modelo **uma linha por vez**, 14,52
> ms/linha contra **0,86 em lote de 6** (16,9x) e 0,05 em lote de 200 — 944.100
> travessias de arvore para 3.147 previsoes.
> **TO-BE**: `value_net.win_prob_lote`, ligada no feixe da busca (6 filhos -> 1
> chamada) e na ordenacao das candidatas (ate 24 -> 1), com correspondencia
> POSICIONAL (nao e o "adiar previsao" recusado no bloco 766).
> **GANHO MEDIDO**: **17,16s -> 11,27s por partida (-34,3%)**, modelo de 32,9%
> para 13,9% do tempo; na carga de 4 partidas, **11,3s -> 6,3s** com os MESMOS
> vencedores e turnos — decisao identica, so mais rapida. Portao de 240
> partidas: **~13 min com 2 workers** (era ~45 min, e ~2,5h no inicio do 785).
> Teste permanente novo provando lote == consulta unica. `smoke_fast`: **1426
> checagens, 0 falhas**.
> **PROXIMO GARGALO, agora medido**: `__deepcopy__` (clonagem de estado, 14,0%,
> 229.594 chamadas) + primitivas do interpretador (18,7%). Nao atacado.
> **PENDENTE — ITEM 1, MEDIR**: nada dos blocos 785/786/787 passou por duelo.

> 13/09/2026 (bloco 786): **os 7 itens da lista de pendencias, feitos** (pedido
> do usuario: "faca do item 2 ao 8, ai depois a gente faz o 1").
> **(2) O MODELO ABRE OS RAMOS**: a busca expandia `acts[:BUSCA_FEIXE]`, os 3
> melhores pela pontuacao ESTATICA - era o achado dele no bloco 778 ("o ML julga
> o DESTINO e a heuristica escolhe o CAMINHO"). Agora materializa 6 filhos,
> pontua cada um pelo estado que produz e recursa nos 3 melhores. As 4 seeds de
> teste **mudaram de vencedor**.
> **(3) FASE 0**: `AUTO_JOGO_CEGO` **LIGADO por default** - o corpus era gerado
> com o motor lendo a mao do oponente. O portao **nao valida isto**; quem julga e
> o banco humano.
> **(6) "O que nao vira candidata nao existe"**: medido em **10,3% dos turnos**
> (12/116) terminando com acao LEGAL na mesa. Dois portoes estaticos derrubados
> (o piso nao encerra mais o turno; o shortlist aceita score negativo quando e o
> que ha) - quem encerra o turno agora e a BUSCA, contra `PASS_ACTION`. Caiu pra
> 6,5%, e os restantes sao "avaliou e preferiu passar".
> **(4) LETHAL x [TRIGGER]**: a prova tinha **zero** mencoes a trigger. Agora
> conta com ele via composicao do deck (`full_deck_codes`), nunca via qual carta
> esta em qual vida; premissa declarada de **no maximo 1 trigger disruptivo**.
> Declaracoes caem **1786 -> 1367 (-23%)**. **ITEM MAIS ARRISCADO**: e a mesma
> familia que no bloco 779 fez o bot GANHAR MENOS (9x15) ao ser consertada -
> ganhou override por jogador (`lethal_ve_trigger`) e **o portao TEM que
> isola-lo**.
> **(5) RETREINO A CADA 3 PARTIDAS**: `--retreino-a-cada` default 3, e o alvo do
> retreino corrigido para o modelo que REALMENTE decide (`value_net_aluno`, via
> `--modelo-decide` novo no gerador) - o laco retreinava o campeao do desenho
> somado, que nao decide mais nada.
> **(7) RESTOS**: orcamento de amostras apagado; **telemetria ao vivo corrigida**
> (dizia `counterfactual_search`/`sampled_opponent_model`, uma amostragem que nao
> existe mais). **Avaliacao incremental NAO feita de proposito** - 11,3s/partida
> contra 16s do baseline, fazer agora seria otimizar ao redor do ML sem
> necessidade medida.
> **(8) `confirma_gen4.py` ENCERRADO por obsolescencia**, nao confirmado: ele
> duela o desenho somado (peso 200) que nao decide mais nada. Aviso no topo do
> script.
> `smoke_fast`: **0 falhas**. Tempo: **11,3s/partida** (portao de 240 ~22 min com
> 2 workers).
> **PENDENTE - ITEM 1, MEDIR**: 6 mudancas de comportamento empilhadas, **zero
> partidas de evidencia**.

> 13/09/2026 (bloco 785): **O MONTE CARLO SAIU DO PONTO DE DECISAO** (344
> linhas), e o achado que reescreve o bloco 784: `_busca_determinista`
> **nunca tinha rodado** — a chave da transposicao era dict aninhado,
> levantava `TypeError`, a excecao era engolida e a busca devolvia `None` em
> **48 de 49 decisoes**. O "custo-neutro" de ontem comparou Monte Carlo com
> Monte Carlo.
> **VELOCIDADE: 36,9s → 8,4s por partida (4,4x)**, abaixo do baseline
> historico (~16s). Portao de 240 partidas: ~2,5h → **~34 min sequencial,
> ~17 min com 2 workers**. Degrau do meio: `pick_counters` consultava o modelo
> **7.379x por partida** dentro do rollout — era a unica chamada sem o guard
> `_EM_SIMULACAO`.
> **CONSERTADOS**: (a) a ordenacao pelo modelo era desfeita pelo `sorted`
> estatico do shortlist — so sobrevivia como desempate; (b) `MODELO_SACRIFICIO`
> e `ARVORE_DON_EXTRA` ganharam override POR JOGADOR, sem o qual o duelo
> espelhado **nao conseguia medi-los**; (c) as 3 falhas de `smoke_fast` que o
> push do 784 deixou — o modelo estava **descartando evento [Counter]**; a
> reserva de defesa virou RESTRICAO e a valoracao de custo parou de misturar
> duas reguas.
> `smoke_fast`: **1420 checagens, 0 falhas**. 3 testes da amostragem adaptativa
> removidos (mecanismo deixou de existir), 1 teste novo trancando os
> invariantes.
> **PENDENTE — e continua sendo tudo**: **nenhum duelo rodou**. A busca nova
> nunca tinha executado antes de hoje; os numeros sao de estrutura e TEMPO,
> **nao de forca**. Proximo passo: portao SPRT, que agora custa ~17 min.

> 13/09/2026 (bloco 784): **⚠️ PRODUÇÃO MUDOU E NADA FOI MEDIDO.**
> `MODELO_ORDENA`, `MODELO_SACRIFICIO`, `ALVO_EFEITO_NA_BUSCA` e
> `ARVORE_DON_EXTRA` estão **LIGADOS por default** e **nenhum passou por
> duelo**. O motor ficou **lento**: ~34,5s/partida com tudo desligado contra
> ~16s do baseline — a árvore alargou e o Monte Carlo continua por baixo, com
> orçamento fixo dividido entre mais candidatas. Com tudo ligado, 55-95s.
> **Para voltar ao comportamento anterior, desligue os quatro knobs.**
> **CONSTRUÍDO**: o modelo decide **8 famílias** (topo, DON por ataque, alvo do
> efeito, blocker, counter, search, trash, descarte); árvore **4,9 → 8,4**
> candidatas, DON por ataque **1,00 → 2,51**; 3 medidas novas em `value_net`.
> **SUBSTITUIÇÃO DO MONTE CARLO construída e CUSTO-NEUTRA**: busca
> determinística no próprio turno + rede na folha + transposição deu **55,1s
> contra 54,5s**. Falta o **"U" do NNUE** — avaliação incremental; hoje cada
> consulta clona o estado e recalcula 78 features do zero. **É a próxima
> tarefa.**
> **4 bugs meus pegos antes de medir**, incluindo o caminho AO VIVO devolvendo
> `None` (o bot ficaria sem ação contra o usuário) e a expansão da árvore sendo
> desfeita em silêncio pelo dedupe. Um quinto, de custo: a precificação rodava
> dentro da simulação — 18.392 chamadas/partida, corrigido (`win_prob` 38.785 →
> 19.218).
> **PRÓXIMO PASSO: MEDIR.** Há muita coisa construída e zero evidência de que
> alguma ajuda.

> 12/09/2026 (bloco 783): **AS 4 FASES DO PLANO PROFESSOR/ALUNO CONSTRUÍDAS**,
> sem simulação (pedido do usuário).
> **Fase 1 (rótulo)**, medido só reanalisando o corpus: 100,0% da variação do
> rótulo vem da PARTIDA, variância dentro dela **0,0000 exato** — os ~18,5
> estados de uma partida levam a MESMA etiqueta. O alvo do professor vai de 2
> para **20 valores distintos** e a variância dentro da partida para 0,0076.
> **Fase 2 (aluno)**: `counter_hand_opp` era a única das 78 features que exige
> ver a mão do oponente — removida. AUC 0,8080 contra 0,8144 do modelo
> privilegiado: **a feature não sustentava a previsão**.
> **Fase 3 (árvore)**: candidatas por decisão **4,9 → 8,1**, valores de DON por
> ataque **1,00 → 2,31**, atacantes com um só valor 100% → 36,4%. A ação de
> ataque passou a carregar o DON e o modelo passou a ordenar as candidatas.
> Quase não funcionou: o dedupe **desfazia a expansão em silêncio**.
> **DOIS BUGS MEUS pegos na triagem**: (a) `sim_bridge` desempacotava 5
> elementos fixos → o caminho **AO VIVO devolvia `None`**, o bot ficaria sem
> ação em partida real; (b) a ordenação estourava o orçamento de 3s ao vivo.
> `smoke_fast` de volta a **0 falhas**.
> **FASE 3 ESTÁ PARCIAL** (lembrete do usuário: *"não é só distribuição de don
> que temos que melhorar"*). Só o DON ramifica. Continuam FORA da árvore:
> **bloquear e com quem**, **usar counter e quais cartas**, **alvo do efeito**
> (mecanismo existe e está desligado), **carta do search**, **reviver do
> trash**, **descarte**, **o que sacrificar pra pagar custo**. As 3 piores
> categorias medidas contra humano — counter 18,5%, alvo de efeito 16,4%,
> sequenciamento 36,4% — são justamente famílias que não ramificam.
> **PENDENTE — e é tudo**: nenhuma das 4 fases foi medida em duelo. Os números
> são de estrutura e AUC, **não de força**.

> 12/09/2026 (bloco 781): **PLANO OFICIAL professor/aluno aprovado** + veredito
> do lethal + o achado do dia.
> **LETHAL, 3 células / 800 partidas**: executor+prova 9x15 · prova com executor
> nos dois lados 19x6 · prova sozinha 12x11. **O EXECUTOR era o culpado** (minha
> hipótese inicial estava errada). `EXECUTA_LETHAL_CERTIFICADO` → **desligado**;
> `LETHAL_VE_MAO_OCULTA` fica ligado **por correção, medido NEUTRO**.
> **SURROGATE de meio de turno**: 73.821 estados novos, curva 0,778 → 0,834,
> modelo com **AUC 0,814**. A tese "meio de turno é intrinsecamente difícil"
> (769) cai — era fome de dado.
> **E MESMO ASSIM PERDE o duelo: 7x15 (31,8%) — placar IDÊNTICO ao do modelo
> de FIM de turno (bloco 775, AUC 0,856), verificado que não é artefato.
> Dois modelos diferentes, mesmo desempenho: **o gargalo não é o modelo.** Achado do dia: **o problema não é ONDE
> o modelo avalia, é O QUE ele foi ensinado a prever** — o rótulo é "a partida
> terminou em vitória?", então um estado do turno 4 leva crédito por uma vitória
> no turno 22. **O usuário já tinha apontado isso em 11/09** e a sessão tratou
> como refinamento.
> **ÁRVORE ESTREITA, medido**: 4,9 candidatas/decisão, 34,2% com ≤2 opções;
> 59,1% das decisões sem nenhuma candidata de DON; 97,6% dos atacantes com um
> único valor de DON. A ação de ataque **não carrega DON** — decidido depois por
> regra fixa, e a busca nunca compara "atacar com 2" contra "atacar com 4".
> **PLANO (em `CLAUDE.md`)**: 0. FIDELIDADE (parar de espiar) → 1. PROFESSOR
> (rótulo melhor) → 2. ALUNO (features observáveis) → 3. ÁRVORE larga.
> **2 armadilhas registradas**: o portão **não valida a Fase 0** (quem espia
> ganha) — julga o banco humano; e o professor **não pode ver demais** (alvo
> inalcançável) — busca exata por mundo, média sobre mundos.
> **Monte Carlo é PLANO** (sem árvore/UCB) — daí "olhar mais custa olhar pior".

> 12/09/2026 (bloco 780): **revisão das regras + o receio do usuário sobre
> AUTO-JOGO corrige o escopo da medição de alavanca.**
> **Regras**: 3 achados ativamente perigosos corrigidos — *"ML só se 1-3
> baterem teto"* (`CLAUDE.md`) e *"ML/MCTS descartados por ora"* (`TODO.md`,
> seção **LER PRIMEIRO**) contradiziam a direção oficial de 10/09; e a AGENDA do
> ALCANCE sobrevivia 40 linhas depois da própria refutação.
> **`TODO.md` voltou a ser lista viva**: 10.248 → 1.139 linhas, resto em
> `TODO_ARQUIVO.md` (379 entradas de bloco antes e depois — nada apagado). 4
> itens antigos seguem abertos; 6 estavam 🔴/🟡 com conteúdo todo `[x]`.
> **2 regras de método novas**: listar os consumidores antes de consertar valor
> compartilhado; e todo experimento precisa de um controle que possa falhar.
> **CORREÇÃO DE ESCOPO (achado do usuário)**: `mede_alavanca.py` roda em
> auto-jogo, então "chutar o blocker não perdeu 80 partidas" significa **"o
> nosso motor não sabe punir bloqueio ruim"**, não "bloquear bem é
> irrelevante". Vício compartilhado é invisível ao auto-jogo por construção — e
> as 3 piores categorias contra humano são exatamente os vícios citados
> (sequenciamento 36,4%, DON/combos 23,5%, counter 18,5%). **Nenhuma família
> pode ser descartada com base só em auto-jogo.**
> **EM ESCOPO por pedido explícito**: o buraco estrutural *"o que não vira
> candidato não existe"* — teto mais duro que os outros, porque é sobre
> **existir** o que escolher, não sobre escolher melhor. Exploração não
> resolve (sorteia dentro da lista já gerada).
> **Conferido**: `--explorar` está com **default 0.0** — desligada. Banco
> humano: 171 partidas / ~3.000 decisões, **27x menor** que o corpus de
> auto-jogo — não sustenta como professor, é insubstituível como juiz.

> 12/09/2026 (bloco 779): **a causa do lethal falso NAO era trigger.**
> Medido antes de consertar (como manda a regra): em 65,2% dos turnos com
> lethal declarado a partida nao acabava.
> **Achado 1** — `_lethal_search` devolve a SEQUÊNCIA vencedora (quais
> atacantes, quanto DON em cada) e **o motor jogava fora**: o único consumidor
> da alocação era um script de diagnóstico. Rastreados 6 casos reais, **6 de 6**
> divergiram (5 ataques certificados → 2 executados; `líder +7 DON` → `0 DON`;
> ataque em personagem onde a prova mira o Leader). Corrigido com
> `_executa_lethal_certificado` — sem motor novo: a escolha continua sendo a de
> `_lethal_search`, só passa a ser EXECUTADA.
> **Achado 2 (a causa real)** — executar a linha certa não mudou nada
> (65,2% → 64,6%). A prova contava as cartas **não reveladas** da mão do
> oponente como **ZERO counter** (`_ = unknown_hand_size  # reservado para
> futura estimativa`), enquanto **três docstrings** afirmavam que a estimativa
> existia. Medido em 40 partidas: mão de 7,5 cartas com 0,56 conhecidas, a
> prova assumia **460** de counter e o oponente gastava **2.416** (5,2x);
> **94,5%** dos lethals que falharam são explicados por isso. O trigger
> apontado pelo usuário é lacuna real mas é a MINORIA.
> Corrigido reusando `counter_estimation.py` (o mesmo módulo que
> `opp_counter_potential` já usava — eram duas funções respondendo à mesma
> pergunta com respostas 5x diferentes, contra `REGRA_SEM_DUPLICACAO`), com
> densidade da decklist real do líder adversário → deck-agnóstico.
> **Resultado após os dois fixes: 35,1% (era 65,2%) -- mas as DECLARACOES cairam de 113 pra 57, ver ressalva.**
> **PORTÃO: REPROVADO — 9x15, winrate 37,5%** (SPRT espelhado, 240 partidas).
> O conserto está certo e **piora o jogo**. Hipótese da causa: a flag de lethal
> alimenta **7 pontos** do motor (entre eles o `FIX_LETHAL_DON_ALLOCATION` de
> 19/07, medido como BOM, que despeja todo o DON no ataque) — as declarações
> caíram de 113 para 57, então o conserto **desligou pela metade um gatilho de
> agressividade que pagava**, junto com os lethals falsos. Em `REPROVADOS.md`.
> **EM CURSO**: isolar as duas metades (`--so-mao-oculta`). O executor da linha
> certificada **não foi medido sozinho** — não descartar citando o 9x15.

> 12/09/2026 (bloco 778): **BUG DE CORREÇÃO achado pelo usuário —
> `_lethal_search` declara "vitória GARANTIDA" ignorando TRIGGERS.**
> Confirmado no código: zero menções a trigger nas linhas ~12253-12360. Ela
> considera atacantes, poder, unblockable, double attack, **todas** as
> distribuições de DON, blockers e counters (estes até conservadoramente) — mas
> **não os triggers da vida do oponente**, que podem anular o ataque. A função
> existe para dar uma GARANTIA e a garantia é falsa. Mesma categoria dos bugs
> já corrigidos em `opp_reactive_field_buffs` (564) e
> `opp_counter_chunks_for_lethal` (17/08).
> Lacuna irmã, do outro lado: **ativação de efeitos própria** também fica fora
> — aí o erro é **perder vitórias reais** que exigem ativar antes de atacar.
> **SEGUNDO ACHADO**: a continuação gulosa da busca escolhe cada passo pela
> pontuação **estática da heurística**; o modelo só julga a posição final.
> **O ML julga o destino, a heurística escolhe o caminho** — então a linha que
> exige uma primeira jogada "ruim pela heurística" nunca chega ao modelo.
> **TERCEIRO**: o laço só retreina depois de 2.000 partidas; das partidas 2 a
> 2.000 o bot joga com o modelo velho. Pedido do usuário: retreinar **a cada 3
> partidas** (ressalva dele: 3 e não 1, "para ter margem de erro").
> **MEDIDO junto** (dúvida dele sobre eco): das 81.645 posições, **77.797 são
> distintas (95,3%)** — a exploração do bloco 767 produz diversidade real.
> **ORDEM definida por ele**: (1) o bug do lethal, (2) busca guiada pelo ML,
> (3) retreino a cada 3 partidas.

> 12/09/2026 (bloco 777): **A TESE DO ALCANCE CAI POR MEDIÇÃO.** Instrumento
> novo (`mede_alavanca.py`): um lado decide a família **no aleatório**, o outro
> pela regra — se o aleatório não perder, decidir bem ali não paga.
>
> | família | empate | pares que decidiram | winrate ALEATÓRIO |
> |---|---|---|---|
> | **blocker** | **100%** | **0 de 80** | — |
> | alvo | 91% | 7 de 80 | 0,0% |
> | descarte | 81% | 15 de 80 | 40,0% |
>
> **Escolher o defensor no chute nunca mudou quem ganhou, em 80 pares.**
> **CORRIGE a tese do bloco 774** ("o ML participa de 1 de 6 famílias, e isso é
> o teto"), registrada com destaque no `CLAUDE.md`: o inventário de 81 decisões
> fixas continua correto como FATO, mas **decidi-las bem quase não muda o
> resultado** — levar o ML até elas não pagaria. A alavanca está na **ação de
> topo** (72% de empate, a menor medida), **exatamente onde o ML já atua**.
> **Onde investir**: quantidade de dado, a única alavanca com ganho medido —
> 3.614 → 81.645 estados levou o AUC de 0,632 a 0,856 e o ML autônomo de 10,0%
> a 31,8%.
> **Ressalvas**: amostras pequenas (7, 0, 15 discordantes); blocker é forte, os
> outros indicativos. **Não medidas**: pagar custo, search/trash.

> 11/09/2026 (bloco 776): **ALVO precificado pelo MODELO — 96% de empate,
> 3 × 4, INCONCLUSIVO.** Primeira fatia do ALCANCE, com o modelo bom (AUC
> 0,856): a régua do alvo virou `delta_remover = win_prob(sem a carta) −
> win_prob(agora)`. Knob `ALVO_PRECO_ML`, default OFF, tipo A.
> **Junto com o bloco 763** (alvo na busca, também 96% de empate, 1 × 6):
> **dois mecanismos completamente diferentes, mesma família, o mesmo 96%** —
> **escolher melhor o alvo não decide partidas neste jogo.**
> **CORRIGE UM ERRO MEU DE RACIOCÍNIO**: tratei "alvo dentro do efeito" como
> alavanca grande por ser a pior categoria de concordância com humano (16,4%),
> mas **concordar com humano e mudar o resultado são coisas diferentes**. Isso
> enfraquece a priorização por concordância que vinha sendo usada.
> **INSTRUMENTO que isso revela**: a taxa de empate do duelo pareado **é** a
> medida de quanto uma família importa (alvo 96% = quase nada; modelo como
> avaliador 72% = muito). Dá para **medir a alavanca de cada família ANTES de
> construir para ela**, ~20 min cada, em vez de implementar as quatro restantes
> e descobrir depois quais não valiam.

> 11/09/2026 (bloco 775): **A FOME ERA REAL — o modelo não era fraco, estava
> faminto.** Corpus de **81.645 estados** (2.000 partidas em ~30 min usando o
> modo rápido como GERADOR; com o motor de produção teria levado ~9 h).
> **AUC fora da amostra 0,6318 → 0,8560 (+22 pontos)** e o vão treino-teste de
> **0,363 → 0,021** — melhor modelo que o projeto já teve. Inverte também o
> achado do bloco 771 ("16 features batem 49"): aquilo era sintoma de corpus
> pequeno, e com 81 mil estados as 78 features treinam sem decorar.
> **Teste TIPO A** (ML decidindo sozinho, sem heurística somada): **7 × 15,
> winrate 31,8%** — contra **1 × 9 (10,0%)** no bloco 769. **De 10% para 31,8%
> mudando só a quantidade de dado.** Ainda perde, mas a trajetória é
> inequívoca.
> **O QUE FALTA, e amarra com o inventário do 774**: mesmo "decidindo sozinho",
> o ML decide **1 de 6 famílias** — `ML_AVALIADOR` trocou a AVALIAÇÃO, mas as
> **81 escolhas fixas** continuam `max(board_value)`. O teste mediu um modelo
> muito melhor fazendo a mesma fração pequena do jogo; que tenha ido de 10%
> para 31,8% assim é argumento A FAVOR.
> **Duas alavancas restantes, com tamanho**: mais dado (23x rendeu +22pp) e
> **ALCANCE** — trocar as duas réguas, nunca testado, atinge as outras 5
> famílias de uma vez. Agora a rede de valor é boa (0,856), o que torna a
> precificação por modelo confiável pela primeira vez.

> 11/09/2026 (blocos 773-774): **O ML PARTICIPA DE 1 DE 6 FAMÍLIAS DE
> DECISÃO.** Três achados do usuário, todos verificados no código: (a) *"o
> atacante não morre"* — **regra, e eu errei** no exemplo; (b) *"não é só vida,
> board e mão também sufocam"* — o modelo **já enxerga**, e `trash_opp` foi a
> 3ª feature mais usada; (c) *"precisamos treinar defesa"* — **buraco real**,
> `should_use_blocker`/`should_use_counter`/`pick_counters` fazem **zero**
> consultas ao modelo.
> **Inventário** (`audita_decisoes_fixas.py`, a pedido dele): **81 escolhas
> fixas em 28 funções** — `_execute_step` sozinha tem **27** (toda vez que uma
> carta faz algo, quem escolhe é `max`/`min`), pagar custo 16, **bot AO VIVO 9**
> (responde prompts do jogo por regra fixa em partida real).
> **1 de 6 famílias**, e isso explica os 78-96% de empate nos duelos: a maior
> parte do jogo não passa pelo modelo. **Não é teto de qualidade, é de
> ALCANCE** — bate com `quais cartas de counter` em 18,5%, uma das três piores
> categorias.
> **O CAMINHO — não são 28 problemas, são DOIS**: quase todas usam as mesmas
> chaves, `board_value()` e `_trash_value`. Basta **trocar a régua**. E dá para
> fazer **sem treinar nada novo**: `valor(carta) = P(vencer | posição) −
> P(vencer | posição sem a carta)`, precificando por consequência medida em vez
> de `power//1000 + keyword`. Custo a medir (2,1 ms por precificação, ou o memo
> do bloco 766). **Desenhado, não adotado.**

> 11/09/2026 (bloco 772): **REDE DE POLÍTICA REPROVADA OFFLINE em ~30 min** —
> o baseline que construí para matar a ideia matou. Em vez de ESCOLHER a
> jogada, a política PODARIA o shortlist (assimetria de erro: se erra, a busca
> ainda avalia as sobreviventes). Desenho respeitou os 4 pontos que o
> `REPROVADOS.md` exigia (auto-jogo, podar, destilação de busca, exploração).
> **Medição offline, 626 decisões, 4 líderes nunca vistos**: política 82,9% no
> top-3 contra **81,6% do score estático que já é calculado de graça** — ganho
> de 0,5 a 2,1 pontos, que não justifica um modelo.
> **CAUSA ESTRUTURAL**: a árvore é **estreita** — 4,5 candidatas por decisão,
> 31,9% das decisões com ≤3 (podar não faz nada). Podar serve para árvore
> larga. **A ideia nasceu de um número MEU errado**: o mapa AS-IS dizia "10,7
> candidatas", mas eram 10,7 SIMULAÇÕES (Monte Carlo simula cada candidata
> várias vezes) — a oportunidade era 2,4x menor.
> **Falso achado descartado**: com 56 decisões o score estático parecia pior
> que o sorteio; com 626 ele ganha com folga. Era ruído, e a ressalva estava
> escrita antes de medir.
> **FICA**: `politica.py` + seam `_pol_captura` (default OFF) e **o padrão de
> teste** — construir o baseline que pode matar a própria ideia e rodar offline
> antes de gastar duelo: 30 min contra ~1h por experimento antes.
> **ONDE O ML ESTÁ**: tentadas e medidas — valor somado (nulo 3x), valor
> substituindo busca (1×9), busca pela metade (3×12), política para podar (sem
> margem). **O que NÃO foi tentado: corpus muito maior.** Todos os modelos
> vieram de 1.582-3.614 estados, e o bloco 771 mediu que **menos feature bate
> mais feature** nesse tamanho — sinal clássico de fome de dado.

> 11/09/2026 (bloco 771): **TERCEIRA medição dizendo o mesmo — modelo melhor
> NÃO é bot melhor.** Fechadas as duas últimas pendências do roteiro de ML
> (`tunar_value.py`): hiperparâmetros buscados levaram o AUC de teste de
> **0,7761 → 0,8145** e o vão treino-teste de **0,201 → 0,056**. Adotado em
> `treinar_value.py`: árvore rasa, folha grande, parada antecipada.
> **Achado que contraria a onda de features de 10/09**: **16 features batem
> 49** — quanto mais coluna, pior. O princípio "o ML não pode ser cego para
> nenhuma informação" não está errado no limite, mas com 1.582 estados ele
> **exige crescer o corpus primeiro**, senão se vira contra o modelo.
> **E o duelo reprova**: TUNADO **11 × 18**, winrate 37,9%, LLR −3,534 (com
> n=29, "pior" não está provado; "não melhor" está).
> **O PADRÃO, agora com 3 medições independentes**: blocos 680-683 (AUC 0,851
> piorou), bloco 753 (AUC 0,77, `play` 26,6 → 26,5), bloco 771 (+0,038 de AUC,
> 11 × 18). **Melhorar o modelo pelas métricas padrão de ML não produz um bot
> melhor nesta arquitetura.**
> **SÍNTESE — as duas coisas são verdadeiras ao mesmo tempo**: o ML está
> algemado a ±100 pontos sobre a heurística (modelo melhor, algemado, continua
> algemado) **e** não sustenta a decisão sozinho (1×9 sem rollout, 3×12
> cortando metade). É a confirmação mais forte da tese do usuário: **a
> arquitetura é o gargalo, não a qualidade do modelo**.
> **PRÓXIMO: REDE DE POLÍTICA** (temos só a de valor) — em vez de avaliar
> melhor, **reduz o que precisa ser avaliado**. **ATENÇÃO**: já está em
> `REPROVADOS.md` (680-683) na versão por IMITAÇÃO DO HUMANO, que piorou por
> *distribution shift*; retomar exige (a) auto-jogo em vez de imitação, (b)
> PODAR o shortlist em vez de escolher a ação, (c) laço iterativo estilo
> DAgger, (d) a exploração do bloco 767 como pré-requisito.

> 11/09/2026 (bloco 770): **MEIO-TERMO também REPROVA (3×12) — não dá para
> comprar velocidade cortando busca.** Cortar só a simulação da resposta do
> oponente deu **5,1x** (15,3 s → 3,0 s), mais que os ~2x estimados, mas o bot
> perdeu: 3 × 12, winrate 20%, Wilson 7,0%.
> **ERRO DE LEITURA MEU, registrado**: eu tinha cravado antes do teste que
> "DESCARTA" seria vitória prática. O SPRT aqui testa "é MELHOR?" contra "é
> equivalente?" — cruzar o limite inferior significa **"não é melhor"**, e não
> distingue equivalente de PIOR. O dado aponta pior (20% onde equivalente daria
> ~50%; IC exclui 50%). **Lição**: quando a pergunta é "é tão bom quanto?", o
> instrumento é teste de EQUIVALÊNCIA, não de superioridade.
> **As duas tentativas juntas** (ML avaliador 1×9 sem rollout, meio-termo 3×12
> cortando metade) estabelecem que **a profundidade de busca ganha o que custa,
> proporcionalmente** — o rollout compensa o modelo ainda ser fraco.
> **Consequência**: velocidade não sai de cortar busca; sobram força bruta
> (PyPy, núcleos) ou **um modelo bom o bastante para justificar menos busca**.
> **ORDEM definida**: (1) tornar o modelo bom — corpus grande, sobre-ajuste
> (0,99 × 0,63), contexto de turno, exploração; (2) só então encolher a busca;
> (3) heurística sai por partes com portão SPRT.
> Registrado no `CLAUDE.md`/`AGENTS.md` como **EXIGÊNCIA CENTRAL** do usuário,
> com as citações e o histórico do adiamento da sessão.

> 11/09/2026 (bloco 769): **A ESTRUTURA ERA O PROBLEMA — o usuário estava
> certo.** Cobrança dele: pedi migração da heurística para ML e a sessão
> entregou portão, cache, features, PyPy — tudo em volta. Procede (a
> arquitetura de regulador é anterior a esta sessão, mas o adiamento foi meu).
> **`ML_AVALIADOR`** (knob, default OFF): o modelo avalia a posição **logo após
> a ação**, sem simular turno nenhum — deixa de ser termo somado de ±100 e
> passa a SER a função de avaliação. **Medido: 17,4 s → 1,2 s por partida,
> 14,8x.** Nenhum PyPy ou núcleo extra chegaria perto. A cegueira de 58% do
> bloco 756 some junto (ela existia por avaliar no fim do turno).
> **Corpus PÓS-AÇÃO** (`--pos-acao`): captura on-policy por wrapper em
> `_apply_action`; rende **3,4x mais dado por partida** (45 estados contra 13).
> **MAS PERDE O DUELO: 1 × 9, winrate 10%, LLR −2,948, fechou no primeiro lote
> em 3,9 min.** Causa medida: o modelo pós-ação prevê muito pior — **AUC 0,6318
> contra 0,7591** do fim de turno, com sobre-ajuste severo (0,9947 no treino).
> **O rollout não era desperdício**: fazia trabalho real que o modelo, julgando
> um turno pela metade, não substitui.
> **DOIS GANHOS que sobrevivem**: o laço de experimento ficou **18x mais
> rápido** (3,9 min contra 60-79), e a taxa de empate caiu de 84-96% para
> **50%** — pela primeira vez um experimento com alto rendimento de informação.
> **PRÓXIMO PASSO — o meio-termo**: a resposta do oponente é **42,5%** do custo;
> cortá-la mantém a avaliação no fim do meu turno (onde o AUC é 0,76) por
> ~metade do preço. Não são 15x, mas é ganho sem perder precisão.
> Produção intacta: `ML_AVALIADOR` default OFF, nada ligado.

> 10/09/2026 (bloco 768): **EDA feita pela 1ª vez, e ela REFUTA uma afirmação
> MINHA.** O usuário trouxe um roteiro padrão de ML; a comparação apontou 4
> buracos nunca fechados (EDA, seleção de atributos, conjunto de TESTE, métricas
> além do AUC). Ferramenta nova: `analise_ml.py`, com teste em líderes **nunca
> vistos** e importância por **permutação**.
> **O achado que me corrige**: afirmei no bloco 764 que `com_efeito` era "a
> principal" das features novas — a EDA mediu **correlação 1,000 com a contagem
> de personagens**. Nesses decks todo personagem tem efeito, então a feature é a
> contagem outra vez: **zero informação nova**. Mais 4 pares redundantes
> (`power ↔ cost`, ~0,96).
> **23 das 49 features o modelo NÃO usa** (importância ≤ 0), e entre elas estão
> **TODAS as keywords que adicionei** (`rush`, `double_attack`, `unblockable`,
> `banish`, `com_efeito`). O que ele usa: **`life_diff` (0,0885)**, que vale 4x
> a segunda (`power_max_diff`, 0,0219). O modelo é essencialmente "quem tem mais
> vida".
> **Métricas completas** (teste em 3 líderes nunca vistos): AUC teste **0,7761**
> batendo com a validação cruzada 0,7623 — **generalização honesta, sem
> vazamento**. Acurácia 66,4%, precisão 75,5%, recall 61,5%, F1 67,8%, Brier
> 0,197. Matriz de confusão mostra **52 falsos negativos × 27 falsos positivos**:
> o modelo é PESSIMISTA.
> **CONSEQUÊNCIA**: adicionar feature às cegas não estava funcionando, e sem
> isso eu teria gasto mais uma hora de duelo para um resultado nulo de causa
> invisível. **Medir utilidade ANTES de duelar** (2 min) nas ondas 2 e 3.
> **PENDÊNCIAS que sobraram**: hiperparâmetros no chute; **overfitting detectado
> e não tratado** (0,977 treino × 0,776 teste) — e isso muda a ORDEM: se já
> sobre-ajusta, adicionar as 29 features da onda 1 tende a PIORAR. Tratar o
> sobre-ajuste antes de adicionar mais visão.

> 10/09/2026 (blocos 766-767): **EXPLORAÇÃO no auto-jogo — o laço era FECHADO
> e por isso o bot nunca descobria nada.** Pedido do usuário: *"tem que ser
> capaz de aprender e descobrir e não só regular"*. Diagnóstico: o auto-jogo
> era **guloso**, sempre jogava a linha que já considerava melhor — então nunca
> experimentava, o dataset só continha o que ele já fazia, e o modelo aprendia
> a prever o resultado das próprias escolhas. **Não descobria porque nunca
> tentava**, e nenhuma melhoria de MODELO resolve isso (é geração de dado).
> Limite irmão registrado: **o ML só escolhe entre o que as REGRAS geram** —
> descoberta é limitada pela GERAÇÃO, não pela avaliação.
> **Implementado** `_explorar` (ε-guloso na escolha final, nos dois caminhos da
> busca) + `--explorar EPS` no gerador. Default **0.0** — duelo não explora,
> lá mediria ruído. Medido: ε=0,15 deu 6 de 51 decisões exploradas e **mudou o
> vencedor**. O projeto já tinha metade disso no coletor contrafactual, isolado
> fora do laço de aprendizado.
> **VISÃO ONDA 1 (49 → 78)**: auditoria achou **39 campos em `GameState` e o
> modelo via derivados de 8**. Entraram eventos do turno, `is_first`, DON
> completo e restrições. Medido: 17 das 29 variam; 12 ficam em zero (raras de
> verdade, ficam). **`chars_played` sempre zero é SUSPEITO — não investigado.**
> **Estrutura nomeada**: fechado o modo de falha silencioso em que inserir uma
> feature no meio deslocava tudo e o modelo treinava embaralhado sem erro.
> **Memo de `win_prob`** no lugar do lote: revisei minha própria proposta —
> lote entre candidatas exige reatribuir resultado por candidata e erraria em
> silêncio, para ~4% de ganho. Memo é função pura, sem risco: **27,2% de
> acerto** (previ 58% e saiu menos da metade — aqueles eram das irmãs do topo).
> **PENDENTE**: investigar `chars_played`; corpus maior com exploração;
> treinar v3 e duelar; lote de verdade só quando o ML virar avaliador.

> 10/09/2026 (bloco 765): **MAPA AS-IS — 85% do tempo é SIMULAR, 7% é
> DECIDIR.** A pedido do usuário, troquei otimização de *função* por
> otimização de *processo* (mapear AS-IS, achar onde trava, priorizar por
> Pareto). Ferramenta: `mapa_fluxo.py`, instrumenta por fora sem tocar no motor.
> **Repartição**: resposta do oponente **42,5%**, continuação gulosa do próprio
> turno **42,2%**, clone/remap 8,4%, avaliação (heurística + ML) 6,9%.
> Volume: **70 decisões, 747 simulações (10,7 candidatas por decisão), 726
> turnos do oponente por partida — ~48 por turno real jogado**.
> Brinde: o lookahead do próprio turno tem **ZERO chamadas** offline.
> **PRIORIZAÇÃO MEDIDA**: o gargalo não é "simulação lenta", é que **todas as
> 10,7 candidatas recebem o tratamento caro, sem triagem**. Avaliação em duas
> etapas (resposta do oponente só nas finalistas) dá **34,3% com 2 finalistas,
> 30,2% com 3, 26,1% com 4**. Risco de qualidade é medível: só muda a decisão
> se uma candidata fora do top-3 barato virasse a melhor depois da resposta.
> **NÃO adianta**: trocar `sklearn` (6,6% no experimento, **zero em produção**),
> otimizar a heurística (0,3%), mais micro-otimização (resta 1,2-1,5x).
> **Força bruta**, se o processo não bastar: PyPy (5-10x, **não instalado**,
> só serviria para gerar corpus porque `pandas`/`sklearn` funcionam mal nele,
> e exige baixar ~100 MB — não autorizado), mais núcleos (8x), busca rasa
> (vetada pelo usuário por perder qualidade).
> **DIREÇÃO NOVA** no `CLAUDE.md`/`AGENTS.md`: o ML vai **substituir** a
> heurística por partes, não só corrigi-la — *"a heurística já se provou
> complexa e de baixa efetividade"*. Com a ressalva registrada de que **não há
> o que substituir enquanto o ML não vencer um duelo sequer**.

> **IDEIA DO USUÁRIO (melhor caminho de substituição que apareceu)**: a
> heurística é literalmente `score = Σ(valor_i × peso_i)` sobre **16 termos**.
> Separar as duas partes — os **valores** viram FEATURE do ML (conhecimento de
> jogo real, meses de trabalho), os **pesos** ajustados à mão são jogados fora
> e o modelo aprende, inclusive as **interações** que a soma linear não captura.
> Achado ao levantar a lista: vários termos têm informação que as 49 features
> **não têm**, porque são de outra natureza — as features são a FOTO do board,
> e `dmg`, `char_kill_value`, `don_combat_cost`, `survival_premium`,
> `opp_combo_threat`, `coverage` e `don_ocioso` sabem **o que ACONTECEU no
> turno**. O modelo está cego para tudo isso. **Próximo passo**: expor os 16
> valores como features (49 → ~65), re-treinar no mesmo corpus e duelar.

> 10/09/2026 (bloco 764): **VISÃO RICA — o modelo passa a enxergar QUALIDADE
> do board, não só contagem.** Diagnóstico do bloco 763 (alvo na busca empatou
> 96%): as 32 features são todas contagens, sem noção de *quem* está no board,
> então KOar o personagem A ou o B com poder parecido deixa tudo idêntico —
> dar mais decisões a quem não enxerga não resolve. Decisão do usuário: **visão
> primeiro**, aprendizado depois se não bastar.
> **17 features novas** (32 → 49): `power_max`, `cost_max`, `don_attached`,
> `rush`, `double_attack`, `unblockable`, `banish` e **`com_efeito`** (quantos
> personagens TÊM habilidade vs. corpo pelado) — esta última é a principal, e
> nenhuma das 32 a via. Sem identidade de carta, só propriedades.
> **Costura que vale por si**: `state_features` calcula o superconjunto e
> devolve os nomes pedidos; `win_prob` passa `bundle['feature_names']` — com
> isso **dois modelos com visões diferentes duelam no mesmo processo**, sem o
> que o A/B seria impossível. O corpus grava as 49 e `treinar_value.py --features
> basicas|ricas` recorta, então **o mesmo corpus treina os dois lados** e a
> comparação isola a visão, não o volume.
> **Resultado**: corpus novo com 1.582 estados / 16 líderes / 0 erros. AUC fora
> da amostra **0,7484 (32) → 0,7591 (49), +1,1 ponto**. Modesto, e os dois
> decoram (0,96 treino × 0,75 fora) — esperado com 1.582 estados.
> **RESSALVA**: 1.582 é pouco para 49 features; se o duelo der negativo, não dá
> para separar "visão não ajuda" de "corpus pequeno demais".
> **EM CURSO**: `ab_visao.py`, duelo SPRT ricas × básicas. **AUC não é ganho no
> motor** (blocos 680-683: AUC 0,851 piorou ao ser ligado) — só o duelo decide.
> Nada ligado em produção: `VALUE_NET_WEIGHT` segue 0.0 e o default de
> `state_features` segue as 32.

> 10/09/2026 (bloco 763): **ALVO na busca MEDIDO pela 1ª vez — 96% dos pares
> EMPATAM.** O knob `ALVO_EFEITO_NA_BUSCA` (pronto desde 29/08, nunca ligado)
> foi testado com knob LIGADO no desafiante e DESLIGADO no campeão na mesma
> partida — o que exigiu costura nova, porque knob é do processo e ligaria
> para os dois lados (override por jogador `_alvo_efeito_na_busca(p)` +
> `extras` viajando na tarefa até o SPRT).
> Resultado: 200 pares / 400 partidas, **193 empates (96%)**, só 7
> discordantes, **INCONCLUSIVO**. O placar (1×6) não diz nada com n=7 — o
> número que importa é o empate de 96%, contra 78% do A/B do `value_net`.
> Ligar alvo na busca quase nunca muda quem ganha.
> **Sanidade antes do lote**: knob=False gera 0 variantes, knob=True gera 125
> numa partida — o código funciona, há material para escolher.
> **HIPÓTESE A TESTAR**: a busca está mesmo escolhendo alvo DIFERENTE da
> heurística? A avaliação é no fim do turno e as 32 features são CONTAGENS —
> eliminar o personagem A ou o B com poder parecido deixa tudo quase idêntico,
> então a régua não distinguiria e escolheria arbitrariamente do mesmo jeito.
> Se confirmado, o problema não é "alvo fora da busca", é **a régua não
> enxergar diferença entre alvos** — mesmo erro de forma do bloco 755.
> Medição barata que decide (NÃO rodada): contar quantas vezes a busca escolhe
> alvo diferente de `max(board_value)`.
> **NÃO concluir** que "alvo na busca não funciona": deu inconclusivo, não
> negativo. E o knob não foi testado COM o `value_net` ligado.
> `ALVO_REGUA_UNIFICADA` segue sem medição.

> 10/09/2026 (bloco 762): **A PROMOÇÃO DA GERAÇÃO 4 ERA FALSO POSITIVO.**
> Passou com 11×3 em 14 pares discordantes (Wilson 52,4%); o re-teste por SPRT
> deu **12×19 em 31 discordantes (38,7%)** e cruzou o limite inferior em 140
> pares. Era sorte de amostra pequena — e **o portão novo pegou o próprio
> erro**, o que o antigo (10,9% de poder) jamais faria.
> **Duas correções**: promoção DESFEITA (`value_net.joblib` voltou ao modelo
> antigo `1628efa6671e`; manter um campeão promovido por engano envenenaria
> todas as gerações seguintes) e **portão trocado pelo SPRT** (`duelar_sprt`,
> agora default; `--portao-wilson` guardado para A/B).
>
> **ACHADO ESTRUTURAL** (o usuário apontou a contradição na minha explicação e
> estava certo): o modelo **vê 32 features mas só DECIDE a ação de topo** —
> `win_prob` é alcançado por um único caminho, `_select_action_via_search`.
> Ficam FORA: em quem o efeito mira, quais cartas de counter, bloquear ou não.
> Isso explica de uma vez o AUC alto que não vira vitória e os 78% de duelos
> empatados. Medição nova: das escolhas de alvo com 2+ candidatos, **44,6%
> têm empate EXATO no topo** — a régua não discorda, está cega.
>
> **O trabalho de alvo JÁ EXISTE e nunca foi medido**: commit `3c3f4a0`
> (29/08) costurou 23 sítios atrás dos knobs `ALVO_EFEITO_NA_BUSCA`,
> `ALVO_REGUA_UNIFICADA` e `ALVO_EFEITO_MAX_CANDIDATOS`, todos desligados e
> sem registro em nenhum dos três documentos. **Próximo passo**: medir esses
> knobs, depois encurtar o horizonte do rótulo (ideia do usuário).

> 10/09/2026 (bloco 760): **A META OFICIAL DO PROJETO MUDOU** — de "jogar
> IDÊNTICO ao humano (85-90%)" para **VENCER O HUMANO**. Decisão do usuário:
> *"eu tinha estipulado essa meta de 85-90% porque a gente estava trabalhando
> com pesos e o bot estava jogando ruim, como agora estamos com machine
> learning, o objetivo muda"*. Três níveis: **objetivo final** = vencer o
> usuário em partidas reais (periodicamente); **alvo de trabalho** = cada
> geração do ML bate a anterior no duelo pareado; **guarda-corpo** =
> semelhança com humano, medida junto mas **sem número a atingir**.
> A meta antiga não foi abandonada por ser difícil — **deixou de ser
> necessária**. Reescrito em `CLAUDE.md` e `AGENTS.md` (espelho byte-a-byte);
> memória local atualizada.
>
> **PRIMEIRA PROMOÇÃO DO PROJETO**: geração 4 passou o portão novo — 71 pares,
> 11×3 nos decididos, winrate 78,6%, limite de Wilson 52,4%. Corpus 8.729,
> AUC 0,7682 → 0,7785. **Três ressalvas**: (a) passagem **marginal** — 10/14
> daria 45,4% e reprovaria, uma partida de distância; (b) **meu planejamento
> errou por 2x** — previ 58% de divididos e saiu 80%, então para 30 pares
> decididos são ~150 pares (300 partidas), não 71; (c) **produção não mudou**,
> `VALUE_NET_WEIGHT` segue 0.0 e ligar por default continua sendo mudança
> SÉRIA.
>
> **Em aberto**: confirmar o portão com lote maior, ou medir o guarda-corpo
> (`decision_quality_full.py --all`, peso 200 vs 0, com recorte por líder).
> Com a meta nova, o guarda-corpo é diagnóstico, não aprovação.

> 10/09/2026 (bloco 759): **`don_opportunity_cost` congelada por ESCOPO
> EXPLÍCITO** — 86,6% das chamadas restantes de `avaliar_carta` (527.894 por
> partida) saíam do filtro dela, chamada ~88.000 vezes, e a lista `jogaveis`
> não depende de `count`. **Rejeitei o carimbo de estado** (caminho óbvio,
> igual a `opp_lethal_threat`): `avaliar_carta` lê board, vida, postura e
> identidade de carta, e um carimbo incompleto faria o bot decidir diferente
> **em silêncio** — contaminando a métrica oficial sem dar sinal. Em vez
> disso, wrapper fino que congela, chama a função original (sem reindentar
> nada) e descongela num `finally`.
> **Validado por 3 vias**: `smoke_fast` OK; **8 seeds** com assinatura
> idêntica (dobrei de 3 por ser a mudança mais arriscada da série); e um
> **detector de violação** (`OPTCG_VERIFICA_ESCOPO=1`) que recalcula e compara
> a cada geração de ação e **nunca disparou** em 3 partidas completas — essa
> via testa a PREMISSA, não só o desfecho.
> **Ganho ~12%** (20,7 → 18,4 s), e o balanço é honesto: **12% pelo maior
> risco da série**. As anteriores eram provas; esta depende de uma premissa
> que uma edição futura pode quebrar — por isso o detector. **Ligue
> `OPTCG_VERIFICA_ESCOPO=1` ao mexer em
> `_generate_attach_don_actions_inner`.**
> **Acumulado: 41,2 → 18,4 s, −55,3%, motor 2,2x mais rápido.**
> **Ideia do usuário (banco estático em cache global)**: já feita em 3 pontos
> (`_DECK_CACHE`, `_EFFECTS_ENRICHED_CACHE`, `_CACHE` do modelo). Mas a pista
> **FECHADA por medição** (`_stat_conta.py`, por fase): `_load_deck_list` em
> cache custa **0,00 s**, e o **`OPTCGMatch` + `setup()` que roda POR PARTIDA
> no laço de duelo custa 0,04 s com ZERO acesso a disco** — não há o que
> otimizar. Ressalva de método: meu contador embrulha `os.stat`, mas o
> `importlib` chama `nt.stat` direto no nível C e escapa dele, então **não
> provei onde estão os 5.650** — provei, por outro caminho, que o setup por
> partida é irrelevante e que aquilo é custo único de inicialização de
> processo, amortizado pelos workers.

> 10/09/2026 (bloco 758): **`itemgetter` no lugar de `lambda` em
> `hits_after_best_defense`** — ela é chamada 2,8 M de vezes pelas folhas de
> `search_alloc` e fazia DUAS ordenações por chamada, somando 5,6 M de
> `sorted` e 27,5 M de chamadas Python só para as chaves. Trocado por
> `itemgetter` (C) + partição numa passada. Equivalência garantida inclusive
> no desempate (`sorted` é estável e `reverse=True` preserva a ordem dos
> iguais). **Validado**: `smoke_fast` OK + 3 seeds idênticos (B/A/B,
> 15/16/12). **MEDIDO pelo protocolo** de 4 repetições, comparando mínimos:
> baseline 41,2 s → 757: 33,8 s → **758: 20,7 s**. **O motor está 2x mais
> rápido** (−49,8% no acumulado), com separação limpa entre as versões — a
> execução mais lenta desta (22,8 s) fica muito abaixo da mais rápida da
> anterior (33,8 s). O `itemgetter` sozinho valeu **−38,8%**, muito acima
> dos 11,4 s que o perfil sugeria: em CPython, cortar 27,5 M de chamadas de
> função-de-chave vale desproporcionalmente mais que o `tottime` delas
> indica, porque ele não contabiliza o overhead de despacho por chamada.
> Re-perfil mostrou que a poda do 757 cortou `search_alloc` de 8.533 para
> 3.362 chamadas de topo (−61%). **Próximo alvo**: `avaliar_carta` segue com
> o maior custo acumulado (45,5 s), todas as 527.894 chamadas vindas do
> filtro de `don_opportunity_cost` (~88.000 chamadas por partida). Caminho
> preferido é cache de escopo explícito, não carimbo de estado.

> 09/09/2026 (bloco 757): **MOTOR 18% MAIS RÁPIDO**, com duas mudanças
> provadamente sem efeito em decisão (3 seeds: mesmos vencedores B/A/B e
> mesmos turnos 15/16/12; `smoke_fast` OK). Nasceu da reclamação do
> usuário de que o teste do portão demora demais.
>
> **Minha 1ª hipótese estava ERRADA e foi refutada por medição**: achei
> que o gargalo fosse o `sklearn` (`predict_proba` de 1 linha custa
> 2,1 ms) — mas `win_prob` é só **4% da partida** (2,0 s de 47,5 s).
> Trocar o modelo renderia no máximo 4%.
>
> **(1) Poda de impossibilidade no lethal search**: `search_alloc`
> enumerava todas as ~530 distribuições de DON e só no fim via que não
> fechava. Como DON só muda o PODER (nunca cria hit nem remove blocker),
> existe um teto de hits calculável de fora — se `target_hits` já passa
> dele, retorna False sem recursão. É prova, não heurística.
> **(2) `don_opportunity_cost` numa passada só**: contagem por CHAMADOR
> mostrou que **91,8% das 861.034 chamadas de `avaliar_carta` saíam dessa
> única função** — ela avaliava a carta no filtro E de novo no `max`.
> Resultado determinístico: **861.034 → 527.894 chamadas (−38,7%)**.
>
> **LIÇÃO DE MEDIÇÃO (erro meu, corrigido no meio)**: reportei "−11,5%" e
> "−18,3%" a partir de execuções únicas, e depois a MESMA mudança deu
> tempo MAIOR. Medi o piso: **mesmo código, mesma partida, 4 repetições =
> 17% de variação no relógio e 14% na CPU**. Os três percentuais estavam
> dentro do ruído. Com protocolo correto (4 reps por versão, comparar
> mínimos) as 8 execuções ficaram **perfeitamente separadas** (p ≈ 0,014):
> ganho real **−18,0% no relógio e −17,3% na CPU**.
> **Regra para esta máquina**: nunca reportar ganho de tempo de UMA
> execução — o piso é ~15%; abaixo disso, só métrica determinística
> (contagem de chamadas) ou repetição comparando mínimos.
>
> **PENDENTE**: sobraram **86,6% das chamadas** de `avaliar_carta` vindas
> do FILTRO de `don_opportunity_cost`. A lista `jogaveis` não depende de
> `count` e é idêntica para todas as candidatas da mesma decisão —
> memoizar é o ganho grande restante, **mas exige carimbo de estado**, e
> se ele deixar algo de fora o bot passa a decidir diferente EM SILÊNCIO.
> Há precedente (`opp_lethal_threat`/`_lethal_threat_stamp`), mas aquele
> carimbo não cobre o que `avaliar_carta` lê. Não fazer sem validar em
> muitos seeds.

> 09/09/2026 (bloco 756): **A CEGUEIRA DO 755 É REAL MAS INOFENSIVA — e o
> que estava quebrado era a RÉGUA.** O 755 perguntou se o vetor pós-linha
> converge (sim, 58%), mas não perguntou se a **posição** também é a
> mesma. As 32 features são só contagens e agregados, **sem nenhuma
> identidade de carta** — duas posições diferentes colapsam no mesmo
> vetor com facilidade, e as duas hipóteses tinham correções OPOSTAS.
> Medido com impressão digital rica (códigos de carta na mão/campo/trash,
> DON anexado por personagem, vida, deck): **65 de 65 pares convergidos
> são a MESMA POSIÇÃO**, em duas amostras independentes (seed 909: 30/30;
> seed 2001, as mesmas do corpus: 35/35 — reproduzindo o 58,3% do 755).
> **Quando a linha converge, não há o que ver: a decisão é genuinamente
> indiferente.** As duas saídas propostas pelo 755 consertariam o lugar
> errado — a saída (1) ensinaria o modelo a preferir uma de duas coisas
> iguais. **Ambas saem de pauta**, e o lote grande de pares segue suspenso
> por outro motivo que não o do 755.
>
> **62,5% dos rótulos "informativos" são RUÍDO de RNG** (10 dos 16 pares
> de `pares_cf_v2.jsonl` têm posição idêntica e desfecho diferente — só
> pode ser o fluxo aleatório dessincronizado). Casa com `REPROVADOS.md`
> linha 249 ("a curva ACHATA após ~4.000 estados"): mais partidas do mesmo
> regime injetam mais ruído na mesma proporção. A taxa real de par útil é
> **~10%**, não os 26,7% reportados como "informativos".
>
> **ACHADO PRINCIPAL — o portão de promoção tinha 10,9% de poder
> estatístico.** Exigia média ≥ 55% com ~54 partidas decididas; para 80%
> de poder precisaria de **~782**. Uma geração genuinamente 55% melhor
> seria **descartada em 89% das vezes**. As 3 gerações rejeitadas
> (48,2%/49,1%/53,1%, todas com IC95 de ±13pp incluindo 50%) são
> **inconclusivas, não negativas** — e o modelo de fato melhora conforme
> joga (AUC 0,7612 → 0,7682 com corpus +33%). Mesma classe de erro que o
> `REPROVADOS.md` já registra: a régua estava torta, não o motor.
>
> **CONSERTADO — espelho pareado + limite inferior de Wilson** (desenho
> escolhido pelo usuário entre pareado/SPRT/aumentar n; não é mecanismo
> novo: é o mesmo do commit `41731f5` que resolveu variância idêntica na
> calibragem do score de mão). Cada par roda a MESMA seed — logo o mesmo
> par de decks e o mesmo embaralhamento — com os lados trocados; só conta
> quem vence dos DOIS lados, e par dividido entra como **sem informação**.
> `_duelo` continua a única função que roda uma partida (motor único
> intacto). **Validado por teste A/A**: motores idênticos → 8 pares, todos
> divididos, 0 decididos, exatamente o previsto. O pareamento cria um
> risco NOVO (n decidido pequeno → média alta em 2 de 3 é ruído), corrigido
> junto: o portão passou a olhar o **limite inferior do IC95 (Wilson)** em
> vez da média — 2/3 dá limite 20,8% e barra; 60/100 dá 50,2% e passa.
> Flags `--nao-pareado` e `--portao-media` preservam o desenho antigo pra
> A/B.
>
> **A/B REAL MEDIDO — o desenho é praticável.** 12 pares / 24 partidas
> (peso 0 × peso 200): **7 divididos (58%), 5 decididos (42% de
> aproveitamento)**, zero descartes. O portão recusou promover (2×3,
> limite de Wilson 11,8%) — coerente com o bloco 753, que já media que
> peso 200 não paga. Custo: **22,7 s/partida** com 2 workers → 30 pares
> decididos = 142 partidas = **54 min**, e nesse n o desafiante precisa
> vencer 21 (70%) para passar.
>
> **PENDENTE, não assumir resolvido**: (a) o **ganho de PODER continua não
> medido** — o A/A valida correção e o A/B mede custo/aproveitamento, mas
> nenhum dos dois prova que o pareado detecta melhoria real melhor que o
> desenho antigo para o mesmo número de partidas; exigiria dois motores
> com diferença de força CONHECIDA, e **não vale afirmar "N vezes melhor"
> sem esse número**; (b) limpar os rótulos convergidos na coleta é o
> **próximo passo acordado com o usuário**, depois do portão; (c) nenhuma
> geração foi rodada com o portão novo ainda.
>
> **Achado de ambiente — oversubscription de threads BLAS**: com
> `peso=200` o `value_net` é consultado em cada simulação e cada processo
> abria threads próprias de `sklearn`/`numpy` — **1,34 núcleo por worker**
> numa máquina de 2 núcleos (2 workers pedindo ~2,7). Fixando
> `OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS=1`: **0,93 núcleo por worker**.
> Pendente fixar isso dentro dos scripts de ML em vez de depender de
> exportar a variável na mão.
>
> **Ambiente**: máquina do usuário é i3-8130U de **2 núcleos** — os
> exemplos de `--workers 4` do `CLAUDE.md` a travam; usar `--workers 2`.

> 09/09/2026 (bloco 755): **A FUNÇÃO DE VALOR É CEGA EM 58% DAS
> DECISÕES.** `_simulate_sequence_once` não avalia o estado logo após a
> ação escolhida — simula **o resto do turno inteiro** e só então chama
> `_evaluate_state_v2`/`value_net`. Escolher `attack` primeiro ou `play`
> primeiro leva, na maioria das vezes, ao **mesmo estado de fim de
> turno** (as duas acabam sendo feitas, em ordem diferente). Medido em 60
> pares: **35 (58%) têm vetor pós-linha IDÊNTICO** entre as duas irmãs;
> 20% diferem em 1-7 features; 22% em 8+. Não é bug do coletor —
> candidatas são ações genuinamente diferentes e `pos != estado_pre` em
> 60/60.
>
> **Fecha o quebra-cabeça dos blocos 753-754 com uma causa única**:
> `play` parado em 26,6%, separabilidade 0,52, duelos em 50%, os 80% de
> decisões que não mudam o vencedor, e o paradoxo do AUC 0,77 que nunca
> virou ganho — o modelo é bom, mas é consultado num ponto onde as
> alternativas já colapsaram.
>
> **MUDANÇA DE RUMO**: o lote grande de pares contrafactuais (~4,5h)
> está **SUSPENSO** — 58% dos pares nascem sem sinal, por construção.
> Duas saídas, ambas **SÉRIAS** (exigem autorização, regra de 28/08):
> (1) avaliar logo após a primeira ação em vez do fim da linha — mata a
> cegueira na raiz, mas muda o significado da busca inteira; (2) manter a
> linha e alimentar o modelo com a **descrição da ação** junto do estado
> — o que a convergência apaga é *qual* foi a primeira ação, e o coletor
> já grava isso. **Aguardando decisão do usuário.**
>
> Dado novo: `metrics/pares_cf_v2.jsonl` (60 pares, coletor corrigido,
> 60/60 válidos e **zero erros** após o fix do `filter_type`, 26,7%
> informativos contra 20,6% antes). `pares_contrafactuais.jsonl` (180)
> segue **obsoleto**, mantido só como histórico.
>
> **Correção**: minha afirmação de "4x de desperdício" com `--workers 4`
> não se confirmou nessa proporção — medição controlada deu 200s (4
> workers) × 156s (13 workers) = 1,28x, não 3,25x.

> 09/09/2026 (bloco 754): **80% DAS DECISÕES DO BOT NÃO MUDAM QUEM
> GANHA.** Medido de frente com contrafactual real (180 pares, 2
> partidas completas cada — só 20,6% informativos). Isso reinterpreta
> todos os resultados nulos do ML de uma vez: o termo de valor **troca
> decisão em 100% das partidas** e muda o vencedor em 28%, mas o winrate
> fica em ~50% e a distribuição de estados não muda (separabilidade
> 0,52) — **troca muito, e as trocas são neutras**. Vale além do ML:
> existe um **teto estrutural** para qualquer mecanismo que atue na
> escolha entre irmãs, incluindo os já reprovados nos blocos 641-706.
>
> **BUG DO MOTOR, corrigido**: `filter_type` pode ser LISTA e
> `_should_activate_main` fazia `.lower()` direto — a exceção subia pelos
> rollouts e **matava a partida inteira**. Explica as **41 de 300
> partidas (13,7%)** que saíam como "descartadas por erro" na geração do
> corpus, sem causa apurada. Corrigido pela FORMA (`_ftypes`/`_ftype_in`).
> **PENDENTE — mesma bomba em ~9 pontos**: linhas 3068, 3362, 10960,
> 12527, 16330, 16355, 16517, 16775, 17025 de `decision_engine.py`.
>
> **Construído**: `treino_continuo.py` (laço de gerações com portão
> campeão × desafiante), config de valor POR JOGADOR, seam contrafactual
> em `_select_action_via_search`, `gerar_pares_contrafactuais.py`,
> `avaliar_pares_contrafactuais.py`, `analisar_corpus_valor.py`,
> `medir_taxa_troca.py`. Produção **inalterada** (`VALUE_NET_WEIGHT=0.0`).
>
> **Laço: 3 gerações, 3 descartes** (48,2 / 49,1 / 53,1%). **Ainda não é
> iteração** — como nada foi promovido, as 3 jogaram com o mesmo campeão.
>
> **REFUTADO (hipótese minha)**: "subir o peso" — o termo nunca esteve
> inerte (100% de divergência). Não tentar.
>
> **Erros meus corrigidos na sessão**: (a) a curva de aprendizado
> **achata** depois de ~4.000 estados, não sobe; (b) o `value_net` **não**
> é cego entre irmãs (avalia o estado pós-linha) — cego era meu script,
> e por isso os 180 pares coletados **não servem para treino**; (c) a
> estimativa de 11h estava errada — a sessão rodou com `--workers 4` numa
> máquina de **16 núcleos**. Já corrigidos: workers, features pós-linha e
> escolha de decisão disputada.
>
> **PRÓXIMO PASSO, pergunta única**: com o coletor corrigido, **o ranker
> de irmãs sai de 50%?** (última medição 54,1%, IC [38,0; 70,1] —
> inconclusivo). Se sair, plugar e rodar o laço com portão duplo (força +
> métrica oficial). Se continuar cruzando 50%, o caminho contrafactual
> morre com número e vai-se para a destilação da busca.

> 08/09/2026 (bloco 753): **A MÉTRICA OFICIAL ESTAVA INAUDITÁVEL DESDE
> 05/09.** `decision_quality_full.py --all` reportava "sem dados (0/0)"
> em `play`/`activate`/`attack_quem`/`attach_don`/`sequenciamento` —
> todo turno ofensivo morria em `'OPTCGMatch' object has no attribute
> 'search_top_k_override'`. Causa: `replay_optcg._get_engine_match()`
> monta o match via `__new__` com **lista manual** de atributos, e o
> bloco 750 adicionou o parâmetro ao `__init__` sem atualizar a lista.
> **Bug reincidente** (o mesmo aconteceu em 24/07) e que falhava em
> SILÊNCIO — as categorias de defesa continuavam saindo normais.
> Corrigido de forma **genérica** (preenche todo parâmetro opcional do
> `__init__` via `inspect`), validado 7 turnos/7 erros → 7/0.
> **Qualquer medição da métrica oficial feita entre 05/09 e 08/09 por
> esse caminho mediu zero turnos ofensivos — desconfiar dela.**
>
> Junto: **1ª tentativa de ML por AUTO-JOGO** (escolha do usuário:
> híbrido atrás de flag). Infra nova — `optcg_engine/value_net.py`,
> `gerar_selfplay_dataset.py`, `treinar_value.py`, knob
> `VALUE_NET_WEIGHT` (**default 0.0, produção inalterada**). O modelo
> **aprende bem** (AUC fora da amostra 0,707, 5/5 folds, GroupKFold por
> líder) e **NÃO paga** no motor: `play` 26,6% → 26,5% (peso 200) e
> 26,4% (peso 50); `seq idêntica` 5,7 → 4,7; por líder 9 sobem × 9
> descem. **REPROVADO por medição**, registrado em `REPROVADOS.md`.
> Diferente das reprovações anteriores, **não** foi por *distribution
> shift* (não existe aqui) nem por não aprender. Duas hipóteses abertas
> e não testadas: (a) redundância com a busca Monte Carlo; (b) **alvo
> errado** — o modelo prevê VITÓRIA e a métrica mede SEMELHANÇA COM O
> HUMANO, e as categorias que mais caíram são de sequenciamento, ao qual
> "quem ganha" é indiferente. Testar (b) exige trocar o RÓTULO, não o
> mecanismo — a infra já está pronta.
>
> **Pendências**: `smoke_fast.py` tem 1 falha **pré-existente**
> (`lider com decklist real do codigo exato (Imu)`), confirmada por
> `git stash`, não investigada. `scikit-learn` não estava instalado e
> **não** foi adicionado ao `requirements.txt` (só necessário pra
> treinar; o runtime só precisa se o knob for ligado) — decidir antes de
> qualquer deploy que ligue o knob. O `play` desta sessão (26,6%) **não
> é comparável** aos 28,2% do `CLAUDE.md` (corpus diferente).

> 06/09/2026 (bloco 752): **Redundancia da tela de analise + faxina de
> lint que desenterrou 219 cartas sem imagem.**
> (1) Funcoes do deck agrupadas em Ofensivo/Defensivo/Consistencia com
> popup; Custo medio duplicado removido; painel do lider com arte grande.
> (2) **Draw Power 6 -> 2**: o front contava `draw` de `[Trigger]`, que so
> dispara ao virar da vida. Fix na FONTE (`draws_ativo` no
> `gerar_card_analysis_db.py`), nao no consumidor.
> (3) **`cohesion_pct` REMOVIDO** do `tribal_cohesion.py` -- numero unico
> misturava concentracao de tipo com ganchos e contradizia a propria tela.
> Virou 2 eixos com cortes calibrados nos 184 decks reais.
> (4) **Lint: 51 problemas e 1 erro -> 0.** Correcao: os "11 warnings" que
> eu havia reportado eram so do `analysis/page.tsx`. O erro (`any` no
> `/simulate`) foi introduzido por mim na leva anterior.
> (5) **Achado**: `next/image` lanca em `src` vazio e **219 das 4557
> cartas nao tem `card_image`** (as promos `P-` transcritas na mao). As 26
> imagens passaram a usar `src/components/CardImage.tsx`, com placeholder
> pra `src` vazio e pra 404. `remotePatterns` no `next.config.ts`.
> (6) **Conferido na tela real com o deck Krieg** (usuario logou e mandou
> screenshot): imagens migradas OK, mas a propria tela revelou 2 bugs meus.
> **"DEFENSIVO 104% do deck"** -- o `%` do grupo somava funcoes que se
> SOBREPOEM (10 blocker + 36 counter + 6 trigger = 52 num deck de 50);
> agora conta cartas distintas, **104% -> 80%**. E **"Counter 36" contra
> "ideal 8-12"** -- a linha somava counter 1000+2000 enquanto
> `deck_analyzer.py:280` conta so >= 2000; o deck tem **10 de 2000, dentro
> do ideal**, e 26 de 1000. Virou duas linhas separadas.
> (7) Numeros do painel aumentados a pedido do usuario (contagem
> `text-xl` + `tabular-nums`, funcao `text-base`, grupo/ideal `text-sm`).
> (8) **Analisador Inteligente**: os 8 `ideal >= X%` eram constantes
> inventadas em TS -- medidos contra os 184 decks reais, 4 deles passavam em
> ~93-100% dos decks (tiles que so diziam "Excelente"). Trocados por quartis
> do meta via `calibrar_percentis_abertura.py` ->
> `/analyze:opening_benchmarks`. Krieg: Draw Power "Regular" -> "Ultimos 25%
> do meta"; Carta <=2 "Excelente" -> "Abaixo da mediana".
> (9) **BUG LATENTE**: `counter_amount` tem formato misto no banco (519
> cartas `'2000.0'` x 28 `'2000'`) e o front comparava string exata --
> perdia a maioria dos counters em qualquer deck montado hoje. Corrigido
> com `parseFloat`. Registrada tambem a correcao de um erro meu: eu disse
> que o ideal de Draw Power era inalcancavel; a mediana do meta e 76,3%.
> (10) Fallback do tile sem benchmark: a 1a versao devolvia um travessao
> CINZA quando `opening_benchmarks` faltava, e bastou a API reiniciar no
> meio do carregamento pra tela inteira aparecer SEM COR pro usuario.
> Degradar != apagar -- agora cai numa escala absoluta, ainda colorida.
> (11) **Trigger na MAO nao e metrica** (achado do usuario): [Trigger] so
> dispara virando da VIDA, e o tile pintava de verde a chance de te-lo na
> mao. Trocado por trigger na VIDA (n = life do lider); calibracao nova
> `trigger_vida` (mediana do meta 29,1%). Krieg da 40,9%.
> Conferido tambem que 48,7% para 6 copias esta certo (2M de maos simuladas
> deram 48,84%) -- contraintuitivo, mas correto.
> (12) **O Score contradizia os tiles**: usava as constantes ja
> desacreditadas, entao `low2` dava 20/20 pontos enquanto o tile dizia
> "Ultimos 25% do meta", e `draw` (o tile mais vermelho) valia ZERO. Cada
> componente agora vale pela posicao no meta, com `draw` incluido e
> `custo_medio` calibrado (a faixa "ideal <=3.5" reprovava mais da metade
> dos decks de torneio -- mediana real **3,74**). Krieg **89 -> 49**, e
> **50 passou a significar "deck mediano de torneio"** (legenda refeita).
> (13) Menores: "Acima da mediana" com p == mediana virou "Na mediana";
> tile de custo 1 some quando conta as mesmas cartas do <=2 (dava 84,7%
> verde colado em 84,7% vermelho); bloco "Diagnostico Automatico" removido
> a pedido do usuario (repetia em prosa os 8 tiles).
> (14) **Ranquear contra meta espremido = ruido** (achado do usuario):
> `counter1k` tem o meta inteiro entre 92,0% e 94,4% (2,4pp) e `low2` 7,3pp
> -- "Top 25%" e "Ultimos 25%" ali nao significam nada, e o Krieg ficava
> VERMELHO por 4 pontos abaixo da mediana. Com espalhamento < 15pp o tile so
> relata ("Padrao do meta"), sem veredito.
> (15) Tile de **Custo medio** ficou com a regua velha ("ideal <=3.5") quando
> o score ja tinha migrado pro meta -- duas reguas pro mesmo numero na mesma
> tela. Corrigido.
> (16) Trigger na vida com 6 copias = **41,1%**, conferido com 2M de setups
> reais simulados (41,03%). Os 48,7% eram do tile ANTIGO de mao (n=5).
> (17) **Eixos SINERGIA/DEFESA/ATAQUE** (`deck_axes.py`, novo): o numero
> unico saia so da mao inicial; agora tres eixos saem dos efeitos parseados
> no motor, calibrados nos 184 decks. Krieg: Sinergia 100, Defesa 58,
> Ataque 90. Pesos ainda nao validados contra vitoria (declarado no modulo).
> (19) **Compras futuras**: a conta era enviesada pra baixo (encolhia as
> copias proporcionalmente) -- Counter 1000 dava 51,2% no T2 contra 57,8%
> exatos. Trocada pela condicional exata `1 - C(45-K,X)/C(45,X)`. Ganhou a
> linha da BOMBA (Krieg OP15-008 x4: 8,9% / 17,2% / 32,0%) e virou popup
> com tabela maior e grafico de barras.
> (20) **Golden Ratios e Sinergias abrem em popup** com as cartas: o motor
> passou a devolver `ratios[].codes` e `synergies[].creator_codes/
> exploiter_codes` (e `api.py` a anexar `code` nas entradas do analysis_db,
> que sao indexadas por codigo mas nao o carregavam). O front so exibe.
> (18) **RESOLVIDO**: as 6 falhas do `smoke_fast.py` eram o `next-dev` no ar
> ha 12h com **4269 s de CPU e 2,7 GB**, sufocando testes com `timeout=3.0`
> num i3 de 2 nucleos. Matando o processo: **SMOKE FAST OK**. Dois erros
> meus de medicao no caminho (bissecao com maquina carregada apontou um
> commit de front; e declarei a hipotese descartada medindo cedo demais) --
> os dois em `REPROVADOS.md`.
> (35) **`c2k_excesso` investigado**: efeito bruto 51,7% com IC95 [44,3;
> 59,0] -- indistinguivel de zero, so 356 de 4.938 pares. Na escala
> PADRONIZADA cai pra +0,076, abaixo da cobertura de curva. E a investigacao
> achou um **confundidor de POSICAO**: colunas separadas por posicao
> (`c2k`/`c2k_indo_depois`) tem correlacao +0,67/-0,66 com quem vai primeiro
> -- o coeficiente media POSICAO, nao counter; a interacao testada deu ZERO.
> Colunas unificadas + **porta de suporte minimo (400 pares)**.
> **Resultado: AUC 0,5666 -> 0,5986 (+3,20, 4/5 folds), e a CURVA passou na
> frente do counter** (3 turnos = 27,6 contra 21,4 de dois counters; a 3a
> copia voltou a penalizar). A observacao do usuario estava certa.
> (34) **A COLINEARIDADE era o problema de fundo** (achado a partir do
> usuario: "ainda ta faltando carta custo 6"). As 7 colunas de curva viraram
> UMA ordinal `cobertura_t1_t3` (0-3): AUC do modelo puro 0,6000 -> 0,6040,
> e com porta+fallback **0,5661 -> 0,5987 (+3,26, 5/5 folds)**. A cobertura
> passou a ser adotada com **100% de estabilidade e sinal positivo**, e os
> absurdos (`t1 -22,3`, `sem_nada +21`) sumiram junto com as colunas que os
> geravam. Efeito BRUTO pareado medido pra todas as features -- e ele mostra
> que `curva_completa` (57,0% em 971 pares) era forte e estava sendo
> rejeitada, enquanto `c2k_excesso` (51,7% em 178) recebia peso alto.
> **SUSPEITO que sobra**: `c2k_excesso +20,1`, amostra pequena com
> coeficiente grande.
> (32) **T4/T5: metade da partida estava fora do score de mao** (achado do
> usuario). A cobertura parava no T3 e uma carta de custo 8 indo em segundo
> valia ZERO -- "searcher+1+4+6+8" pontuava igual a "searcher+1+4+6+1".
> Adicionados com fallback 0; a calibracao rejeitou `t4` (60% estab) e
> adotou `t5` em **-20,3** (100%). Ganho fora da amostra subiu pra **+3,33**.
> Rigor da porta escolhido por medicao (90% > 95% > 99% fora da amostra).
> **RESSALVA**: `t1` foi adotado como -22,3 com 92%, e na rodada anterior
> deu 89% e foi rejeitado -- fica em cima do corte. E efeito PARCIAL, nao
> marginal; ver HANDOFF antes de concluir que o folclore estava errado.
> (33) Faixa de botoes virou 4 (entrou "Chance de tirar a peca", que morava
> no rodape do Analisador) e texto de Sinergias/Coesao Tribal aumentado.
> (31) **PESOS DO SCORE DE MAO CALIBRADOS** contra winrate simulado:
> AUC fora da amostra **0,5613 -> 0,5897**, melhor em **5/5 folds**. 11 de 23
> pesos medidos; 12 mantidos por sinal instavel (porta de bootstrap 90%).
> Duas tentativas reprovadas antes (decks diferentes -> forca de deck vazou;
> espelho sem porta -> colinearidade fez `sem_nada` virar +21) -- ambas em
> REPROVADOS. Desenho final: espelho + pareado + posicao como controle.
> Achado de brinde: **`_is_searcher` do motor tinha o bug do bloco 751**
> (substring `'look at the top'`) e detectava 0 de 50 cartas num deck real;
> agora le o `card_analysis_db` e detecta 12. Duplicacao `hand_scorer` x
> `avaliarMao` fechada: os PESOS agora moram num lugar so.
> (30) **Maos de abertura: a escolha era amostragem de 1,4% do espaco** e
> mudava a cada recarga, com a tela anunciando "Top 3 de 30.000 simulacoes"
> como fato. Trocada por **enumeracao exata** das 11.109 maos distintas
> (multiconjunto de 5 entre 15 cartas), deterministica, e cada mao mostra a
> chance real de sair. Junto: o bug do `counter_amount` (formato misto)
> **sobreviveu em 4 pontos**, incluindo `avaliarMao` -- a pontuacao tratava
> counter como jogada normal em deck salvo no formato .0. E o rotulo do 1o
> jogador contradizia o codigo logo abaixo ("T2=custo 2" x codigo 2-3).
> **Aberto**: os pesos de `avaliarMao` seguem escolhidos a mao, sem
> validacao contra vitoria (mesmo debito dos eixos).
> (29) **Os emojis eram o que estava pequeno** (eu tinha lido "icone" como
> imagem de carta): estavam no MESMO span do texto e herdavam `text-xs`,
> saindo com ~12px. Componente `Icone` separa num span com tamanho proprio.
> Junto: `next build` quebrou em `.next/dev/types/routes.d.ts`, arquivo
> GERADO e truncado ao matar o dev server -- `rm -rf .next` resolve, nao e
> codigo-fonte.
> (28) Cartas dos popups aumentadas: Plano de Jogo **28x40 -> 80x112** e
> Melhores Maos **56x80 -> 96x134** (nome de 9px pra text-xs). Os tamanhos
> vinham de quando os blocos eram inline e disputavam espaco -- restricao
> que morreu na mudanca pra popup e ninguem tinha revisado.
> (27) Botao "Lista do deck" saiu da faixa e foi pro espaco vazio abaixo do
> lider, a pedido do usuario. Faixa voltou a 3 botoes.
> (26) Faixa dos 4 botoes movida pra logo ABAIXO do Perfil de Jogo (estava
> no fim da pagina, so aparecia depois de rolar tudo) e com texto maior --
> titulo `text-base`, subtitulo `text-sm`, e o "abrir" de `text-xs` cinza
> pra `text-base` laranja que acende no hover. Mesmo tratamento no botao de
> "Chance de tirar a peca", que tinha ficado com o estilo antigo.
> (25) **Mais 4 blocos viraram botao + popup** (incl. a Lista do Deck) (Risco de mao travada,
> Melhores maos, Plano de jogo) -- eram a maior parte da rolagem. Criterio:
> inline o que responde "meu deck e bom?", popup o que e consulta ocasional.
> Um shell de modal com 4 conteudos, nao 4 modais. A Lista do Deck perdeu o
> `maxHeight: 600px` dentro do popup -- ele existia pra ela nao dominar a
> pagina, restricao que deixa de valer quando o modal ja rola.
> (22) **Golden Ratios calibrados no meta**: as faixas fixas reprovavam o
> proprio meta -- `finishers 2-4` deixava so **6,5%** dos 184 decks dentro,
> `searchers 4-8` 30,4%, `events 0-6` 41,8%. Trocadas por p25-p75 real
> (fixas viraram fallback). Krieg perdeu o falso alerta "eventos demais".
> (23) **Cores**: "Na mediana do meta" saia VERDE (verde = bom, mas mediana
> = media) -> amarelo; "Padrao do meta" era cinza com barra apagada,
> parecendo quebrado -> azul informativo.
> (24) **A/B fechou a causa das 6 falhas do smoke**: dev server no ar -> 6
> falhas, parado -> SMOKE FAST OK, repetido nos dois sentidos. REGRA: rodar
> `smoke_fast.py` com o dev server PARADO.
> (21) Bloco "Validacao por Simulacao" REMOVIDO a pedido do usuario: quebrava
> 24 partidas em 5 faixas (2 a 7 partidas por faixa) e o ruido dominava --
> "Ruim" com 80% de WR e "Abaixo da media" com 20%, ordem INVERTIDA, e ainda
> recomendava threshold de mulligan em cima disso. O fetch de `/hand-stats`
> saiu junto: disparava lote de simulacao de minutos sem consumidor.
> **Pendente**: 219 cartas seguem sem arte (placeholder e paliativo).

> 05/09/2026 (bloco 751): **Tela de analise mentia em dois lugares, mesma
> causa raiz** -- consumidor reinterpretando `card_text` por substring em
> vez de usar o efeito PARSEADO.
> (1) **Searcher 0,0% num deck com 8**: o TS procurava "look at the top" e
> as cartas dizem "Look at 5 cards from the top". Idem blocker/rush/
> trigger/draw/bomba, e o ARQUETIPO aparecia duplicado e divergente na
> mesma tela ("Controle 75%" do motor x "Midrange" do TS). Fix: `/analyze`
> passou a devolver `cards` (classificacao por carta do
> `card_analysis_db.json`) e o front so EXIBE -- heuristicas de texto em TS
> apagadas. Searcher na abertura: **0,0% -> 59,9%**.
> (2) **Coesao tribal**: deck 100% do tipo rotulado "moderadamente focado"
> (50,8%). Tres causas: gancho subcontado (regex perdia as buscadoras de
> tipo -- 9 de 17), comentario dizendo peso 1 enquanto o codigo usava 3, e
> escala que exigia 50% das cartas com gancho pra chegar em "altamente
> focado". Fix: campo `referenced_types` novo no analysis_db (generico por
> sufixo `_type`/`_types`) + peso alinhado ao 2:1 documentado. Deck do
> usuario: **50,8% -> 78,0%**, "altamente focado". Nos 184 decks reais a
> distribuicao segue espalhada (78/61/45).
> Registro em `parser_audits/2026-09-05_gancho_tribal_por_efeito_parseado.json`.
> **REGRA**: dado sobre "o que a carta faz" sai do parser; se nao estiver
> estruturado la, conserta-se o parser -- nunca um regex novo no consumidor.

> 05/09/2026 (bloco 750): Botao **"Analisar"** do front ligado ao motor
> real (`/analyze` ja existia, so faltava o servidor -- `analyzer-api` novo
> em `.claude/launch.json`, `uvicorn scriptis_da_ia/api.py --port 8000`).
> **`/hand-stats`** (validacao de mao por simulacao) virou **assincrono
> com cache** (`scriptis_da_ia/hand_stats_cache/<hash>.json`, hash =
> composicao do deck): cache-hit responde na hora; cache-miss dispara
> `BackgroundTasks` e responde `{"status":"computing"}` de imediato.
> **Achado real, nao bug**: uma partida simulada leva **~88s** (perfilado
> -- busca Monte Carlo do Turn Planner fazendo lookahead de verdade),
> nao os "1-3s" do docstring antigo (desatualizado ha meses). Adicionado
> modo rapido OPT-IN no motor (`OPTCGMatch(mc_samples_override=(1,1,1))`,
> default `None` preserva 100% do comportamento existente pra qualquer
> outro chamador) -- reduz pra ~11s/partida isolada, mas o LOTE inteiro
> (24 jogos x 8 decks de meta) ainda mede ~6-7min por variancia real entre
> matchups, mesmo com `ProcessPoolExecutor` (4 workers). `smoke_fast.py`
> OK (confirma default inalterado). Front: eslint/tsc/next build limpos.
> **PENDENTE**: `hand_stats_cache/` e arquivo local -- se a API for pra
> producao (Railway, filesystem efemero), precisa virar tabela no
> Supabase. Front nao faz polling automatico durante `computing` --
> usuario reabre a pagina manualmente pra ver o resultado pronto.
>
> **Botao "Simular" (`/simulate`) tambem conserto nesta sessao**: caia
> com "Erro de conexao" porque `DATABASE_URL` (connection string DIRETA
> do Postgres via `asyncpg`, DIFERENTE de `SUPABASE_SERVICE_ROLE_KEY`)
> nunca esteve configurada nesta maquina -- nem no `.env.local`, nem
> como env var do Windows. `db.py` ganhou `_load_env_local_fallback()`
> (le `.env.local` da raiz se a env var nao existir, `setdefault` -- nao
> sobrescreve producao/Railway, que define a propria env var sem esse
> arquivo). Usuario colou a connection string do Supabase mas deixou o
> placeholder `[YOUR-PASSWORD]` literal -- resetou a senha do banco e
> substituiu certo. `/simulate` cria job e completa (`status:"done"`)
> de verdade agora.
>
> **Cronometro adicionado no modal de progresso** (`/simulate`, tempo
> decorrido + estimativa). Testando de verdade, usuario achou o MESMO bug
> de fundo do `/hand-stats` numa rota diferente: `simulation_worker.py`
> chamava a partida real do motor direto dentro de uma `async def`, sem
> `asyncio.to_thread` -- travava o servidor INTEIRO durante cada partida
> (nao so lento, travado de verdade). Mesmo fix aplicado. **NAO** apliquei
> o modo rapido/cache aqui (`/simulate` continua com busca PADRAO,
> completa mas mais lenta com os defaults do front, 50 partidas) --
> resolvido depois: usuario confirmou que quer.
>
> **Modo rapido aplicado em `/simulate` tambem** (`SIMULATE_FAST_MC_OVERRIDE`
> em `simulation_worker.py`, mesma tripla `(1,1,1)`). Achado ao testar com
> deck real: 1 partida especifica ficou rodando MINUTOS mesmo no modo
> rapido (CPU confirmada subindo -- jogo raro/degenerado, nao deadlock).
> Adicionado **`PER_MATCH_TIMEOUT_S = 90`** (`asyncio.wait_for` em volta
> do `to_thread` -- abandona a espera, conta como pulada, nao trava o
> lote). Isso EXPOS um bug real: matchup com TODAS as partidas puladas
> quebrava `aggregate_results` (`KeyError: 'wins'`) -- corrigido, agora
> devolve o mesmo shape zerado.
>
> **Botao Cancelar + minimizar** (pedido explicito do usuario): `POST
> /simulate/{job_id}/cancel` (`db.cancel_job`, so afeta jobs pending/
> running) -- o loop confere status ANTES de cada partida nova e para de
> disparar mais (a que ja estiver rodando termina sozinha). Precisou de
> **migration nova** (`migrations/002_add_cancelled_status.sql` --
> `status` tinha CHECK de 4 valores so) -- **aplicada** direto via
> `DATABASE_URL` (autorizado pelo usuario). "Continuar navegando"
> minimiza o modal pra uma pilula flutuante sem bloquear a tela -- job
> continua igual no servidor (polling nao depende da visibilidade do
> modal). Testado ponta a ponta: cancelamento no meio de uma partida real
> funcionou (parou em 1/9, nunca mais progrediu). `smoke_fast.py` OK,
> eslint/tsc/next build limpos.
> **PENDENTE (fora de escopo, nao pedido)**: persistir o job entre
> NAVEGACOES de pagina inteiras (sair de `/simulate` e ir pra outra
> pagina do site) -- hoje so cobre "minimizar e continuar na mesma
> pagina", nao "sair e voltar depois". `hand_stats_cache/` continua local
> ao disco (pendencia antiga, ver bloco 750 acima).
>
> ### ⚠️ BUG ANTIGO CORRIGIDO: decks OPONENTES tinham ate 500 cartas
>
> `build_real_deck` somava a decklist uma vez por `placing` (o mesmo
> `deck_url` aparece no CSV varias vezes, uma por colocacao em torneio,
> com qty identica). Decks oponentes saiam com **50 a 500 cartas** em vez
> de 50. Valia pra **TODA** simulacao: `/hand-stats`, `/simulate`,
> `gauntlet_matchup`, `audit_replay`, `baseline_metrics`. O CSV de junho
> ja tinha o padrao -> **bug antigo**, nao veio da recoleta.
> Corrigido (`drop_duplicates(subset='card_code')`): os 184 decks agora
> dao exatamente 50 cartas.
> **NAO comparar winrate/gauntlet medido antes de 05/09/2026 com numero
> novo sem refazer a medicao** -- o oponente estava errado.
>
> ### Tela de simulacao: ~14min -> 29s (200 partidas contra 20 decks)
>
> **Modo guloso** (`search_top_k_override=0` no motor +
> `SIMULATE_GREEDY_MODE` em `simulation_worker.py`): aplica a acao de
> maior score estatico sem busca -- a "Abordagem 1" que o Naruto Card
> Game Simulator usa (conferido: IA deles roda 100% em JS no navegador).
> Medido com mesmas seeds: **40,0s -> 1,3s por partida**, e as partidas
> NAO ficam mais longas (14,2 x 13,6 turnos). Custo ja medido em
> REPROVADOS.md bloco 700: `play` -2,7pp. **So no simulador do front** --
> o bot que joga contra humanos continua com a busca completa.
> **Bug corrigido junto**: `run_single_match` tinha `mc_samples_override`
> na assinatura mas nunca repassava pro `OPTCGMatch` (o "modo rapido"
> anterior nunca valeu de fato).
>
> **Licoes de MEDICAO desta sessao** (erros meus, pra nao repetir):
> extrapolar tempo de job pela METADE engana (10,5s virou 15,9s no fim --
> so medir lote inteiro); paralelismo conta nucleo **FISICO** (4 workers
> em 2 nucleos = ganho ZERO, `SIMULATE_WORKERS` usa `cpu_count()//2`);
> `TOP_K=1` **nao** e "sem busca" e ficou mais LENTO (24,8s x 16,5s).
>
> ### Decklists de meta: recoletadas (OP15 -> OP16) e carregadas no banco
>
> `/simulate` tinha so **6 oponentes** (lia a tabela `meta_decklists`)
> enquanto `/hand-stats` lia `decklists_raw.csv` com 193 -- fontes
> diferentes, dado ja existia. Coletor re-executado (estava parado desde
> junho; `time=past_year` sempre traz o periodo corrente, o `FORMATS`
> hardcoded so afeta winrates do leaderboard): **184 decks, era OP16**.
> Ferramenta nova **`carregar_meta_decklists.py`** (idempotente por
> `source_url`, tem `--dry-run`) inseriu as 184 na tabela.
> **Coletor morre com `UnicodeEncodeError`** (emoji nos `print`, console
> cp1252) -- rodar com `PYTHONIOENCODING=utf-8`.
> `smoke_fast.py` fixava um deck POR NOME que sumiu na safra nova; virou
> fallback deterministico (o docstring do teste ja dizia "qualquer deck
> real serve").
> **PENDENTE**: OP17 ainda nao aparece nas decklists (set novo demais pra
> ter torneio no Limitless). O usuario apontou
> `onepiecetopdecks.com/deck-list/` como fonte alternativa, com meta
> JAPONES separado do ingles -- nao raspado nesta sessao.

> 01/09/2026 (bloco 749): Os **83 promos `P-` restantes** (pendencia do
> bloco 748) foram transcritos manualmente via imagem do jogo (agente em
> background) -> **so P-998 continua ausente** (arte alt de DON!!, fora de
> escopo por design). Achados: (1) 3 cores erradas corrigidas contra a
> arte (Miss.Goldenweek/Miss.Valentine/Mr.3 sao Black, nao Red/Yellow/
> Purple -- Baroque Works); (2) **OUTRA colisao de codigo** (mesma classe
> do bloco 747): `P-086.jpg` (arquivo do jogo) traz "P-088" impresso, mas
> `P-088` ja e uma carta REAL diferente no banco -- resolvido mantendo
> `id=P-086` (o codigo que o jogo manda ao vivo), registrado pra sessao
> futura nao reabrir do zero; (3) **bug de gramatica generico corrigido**
> em `gerar_effects_db.py`: `P-085` parseava efeito TOTALMENTE vazio por
> chave dupla `{{X}}` impressa de verdade na carta + fraseado alternativo
> de preview ("place...on...their life" em vez de "add...to...the
> owner's life cards") que nem o gate de pre-filtro reconhecia. Fix
> generico (normalizacao de chave dupla + regex/gate alargados), nao
> hardcoded pra essa carta. `smoke_fast.py`/`smoke_test.py` OK. Banco:
> 2765 -> 2839 cartas, reenviado pro Supabase (paridade com o local).
> **PENDENTE menor**: condicao secundaria de `P-085` ("vida <= do
> oponente") nao parseada -- carta ultra-rara, unica copia no banco, gap
> documentado no parser_audit, nao critico.

> 01/09/2026 (bloco 748): **Atualizacao do banco de cartas** (pedido do
> usuario: front-end vs motor, "o do bot ta mais completo"). Rodei
> `/api/sync-cards` (rota do front, ja existia -- puxa optcgapi.com +
> apitcg.com, upsert em Supabase.cards). 100 codigos ausentes do banco
> (17 OP17 + 83 promos `P-`) -> **17** (so restam os promos). `OP17-058`
> (Kaido, bloco 747) e `OP17-059` (Aramaki, carta distinta antes ausente)
> agora tem DADO REAL, nao so alias.
> **ALERTA/LICAO:** sobrescrever `cards_rows.csv` cego com o export fresco
> do Supabase REVERTEU 10 correcoes manuais ja auditadas (sinal `-5000` do
> `EB03-006`, `[Blocker]` ausente da fonte em 4 cartas do achado 28/07,
> reformulacao de texto do `ST36-005`/Kid) -- pego pelo `smoke_fast.py`
> ANTES do commit, nao depois. Conserto: fusao id-a-id (base = CSV
> anterior, soma so os ids novos, 2 excecoes documentadas no HANDOFF
> bloco 748) em vez de overwrite. `cards_rows.csv` corrigido foi reenviado
> pro Supabase (senao o FRONT ficaria com o texto sujo). `P-096` (so
> existia local, nunca no Supabase) recolocado nos dois lados.
> **PENDENTE:** os 83 promos `P-` (P-038...P-159, P-998/999) continuam
> ausentes -- nenhuma API externa cobre. Precisa transcricao manual via
> imagem da carta (local do jogo confirmado no HANDOFF 748) ou outra
> fonte. `op17_cards_rows.csv` (raiz de `scriptis_da_ia/`) ficou obsoleto,
> pode ser removido numa proxima sessao.
**Última atualização:** 31 de agosto de 2026

---

# ITENS ANTIGOS AINDA ABERTOS

> Triados um a um em **12/09/2026 (bloco 780)** na revisão das regras. O
> resto do histórico foi para [`TODO_ARQUIVO.md`](TODO_ARQUIVO.md) — nada
> apagado, só movido. Os números de linha abaixo são do arquivo.

| item | estado | onde |
|---|---|---|
| **Busca ao vivo bate no timeout de 3s** — 5 timeouts em 10 turnos numa partida real; degrada pra score imediato, sem lookahead. Não é bug de correção, é perda de qualidade no meio de jogo | 🟡 parcial (bloco 411/426) | `TODO_ARQUIVO.md` |
| **Combos estratégicos do oponente** — `opp_combo_threat()` + prioridade `PREVENT_COMBO` implementados e confirmados em self-play; **falta calibração formal** dos limiares/pesos | 🟡 falta calibrar (19/07) | `TODO_ARQUIVO.md` |
| **Passividade do bot ao vivo** — causa raiz principal já corrigida; **falta a partida de validação ao vivo** (`BOT\setup_bepinex.bat` + 1-2 partidas) | 🔴 pendente de teste ao vivo | `TODO_ARQUIVO.md` |
| **Eficiência do bot: baseline percentual** — nota de método que continua valendo (não misturar winrate com comportamento num percentual arbitrário; fixar pesos em `specs/metrics-protocol.md` ANTES de olhar o resultado) | 🔴 método, sempre válido | `TODO_ARQUIVO.md` |

**Arquivados por já estarem fechados**, apesar do rótulo vermelho/amarelo que
carregavam: "EM ANDAMENTO (fechado no bloco 399)", "ORGANIZAÇÃO PROFISSIONAL
DO CONTEXTO" (itens todos `[x]`), "PROBLEMAS ABERTOS (replay Imu vs Sanji)"
(todos `[x]`), "BURACOS DE MECÂNICA" (o próprio texto diz "todos resolvidos"),
"FILA ANTERIOR ainda aberta" (itens `[x]`), e "PRÓXIMO (decisão via log real)"
— este último pedia um script que **já existe** há tempos
(`compare_vs_human.py`, `audit_real_losses.py`).

**SUPERADO, não arquivado por engano**: o "PLANO MESTRE DE EVOLUÇÃO DO MOTOR"
(13/07) dizia *"ML/MCTS descartados por ora"* numa seção marcada **LER
PRIMEIRO**. Contradiz a direção oficial de 10/09. Ficou no arquivo com aviso
no topo.
