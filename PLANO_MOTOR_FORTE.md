# PLANO DO MOTOR FORTE — o padrão dos jogos que jogam bem de verdade

**Decisão do usuário (24/10/2026):** *"Temos que fazer ele jogar bem urgente, tem que
ser difícil de ganhar dele"* … *"Se for preciso trocar a linguagem a gente troca, se
precisar mudar alguma estrutura a gente muda, o que for preciso a gente faz"*. Escolhida
a **opção 1: ir direto para a arquitetura nova** (sem o modo forte provisório em
Python). **Níveis de dificuldade: NÃO agora.**

Leitura obrigatória antes de mexer em motor, busca, auto-jogo ou treino. Apontado no
`CLAUDE.md`/`AGENTS.md`.

## Diagnóstico: por que o bot não ficou forte em meses

Os jogos com IA forte de cartas (competição de IA de Hearthstone 2018–2020, IA de
Magic, Spades da AI Factory, AlphaZero) usam TRÊS peças que se alimentam:

| Peça | Nos fortes | No nosso (medido 24/10) |
|---|---|---|
| **Simulador** | estado compacto, compilado, 10⁵–10⁶ jogadas/s | objetos Python + `deepcopy`, ~200 jogadas/s (`_apply_action` ~4,7 ms) |
| **Busca** | ISMCTS / MCTS determinizado: vários turnos (inclui o do oponente), muitos mundos sorteados, guiada pela rede | só o próprio turno, 1 mundo (3 na defesa), 3 candidatas, ~30 ms usados de 3 s |
| **Aprendizado** | Expert Iteration / AlphaZero: a BUSCA joga melhor que a rede e a rede aprende a imitá-la (política) + o resultado (valor) | o Q aprende com as próprias jogadas, sem busca melhor que ele -> platô (ciclos 77–92 sem promover) |

Sem simulador rápido não há busca forte; sem busca forte não há professor que puxe a
rede pra cima. O portão mede o bot contra ele mesmo e não enxerga erro que os dois
lados cometem; o usuário vence com facilidade.

## Arquitetura alvo

1. **Núcleo do jogo em Rust** (módulo Python via PyO3/maturin):
   - estado compacto (cartas/zonas como structs de números), cópia barata ou desfazer;
   - interpreta o MESMO `card_effects_db.json` (os ~186 tipos de ação de efeito), não
     2.839 cartas escritas à mão — é o que torna a reescrita viável;
   - meta: 100–1000x a velocidade do motor Python.
2. **Busca ISMCTS no núcleo**, com orçamento de tempo (anytime): mãos do oponente
   sorteadas SÓ do observável (regra de informação oculta da INSTRUCAO_MESTRA), vários
   turnos (o meu e o dele), prioridade dos ramos e nota das folhas vindas da rede.
3. **Aprendizado AlphaZero / Expert Iteration**: no auto-jogo a BUSCA escolhe; a rede
   aprende a distribuição de visitas da busca (política) e o resultado (valor). A rede
   atual (MLP 64×32) roda dentro do núcleo.
4. ML, servidor ao vivo e front-end continuam chamando o motor por uma API Python.

## Fases (cada uma com prova e commit)

- **A — Núcleo Rust com PARIDADE.** O motor Python é o GABARITO: partidas de auto-jogo
  e logs reais rodados jogada a jogada nos dois, comparando o estado depois de cada
  jogada (teste diferencial). O Rust só decide algo quando a paridade for ~100%.
  Durante a fase os dois coexistem só como gabarito/teste — nunca decidindo juntos
  (REGRA_SEM_DUPLICACAO). Fase mais longa (semanas).
- **B — ISMCTS no núcleo**, guiado pelo Q atual. Medir: portão contra o campeão E
  partidas contra o usuário (a medida que importa).
- **C — Aprendizado AlphaZero**: auto-jogo com a busca ensinando a rede.
- **D — Troca no servidor ao vivo/front-end**; motor Python aposentado.

## Regras que continuam valendo

INSTRUCAO_MESTRA_ML (um motor, informação oculta, CPU×CPU com a mesma inteligência,
portão SPRT, recorte por líder), REGRA_SEM_DUPLICACAO, REGRA_DADOS_BINARIOS (o
estado do núcleo novo É binário/matriz por construção), AS-IS antes de mudar.

## Estado

- [x] Toolchain: Rust 1.99.1 em `E:ust` (CARGO_HOME/RUSTUP_HOME no E:, PATH do Windows
      NAO alterado -- usar `E:ust\cargoin\cargo.exe` ou exportar no comando),
      instalador conferido por SHA-256 oficial; `maturin` 1.15 no `.venv`.
      Esqueleto `optcg_core/` (PyO3 0.23) compila e importa: `optcg_core.versao()`.
      Compilar: `cd optcg_core && ../.venv/Scripts/python.exe -m maturin develop --release`
      (com `CARGO_HOME='E:ust\cargo' RUSTUP_HOME='E:ustustup'` e cargo no PATH).
- [~] Fase A.0 — especificação. Catálogo do `card_effects_db.json` (24/10): 2.839 cartas
      (2.542 com efeito); 31 gatilhos (on_play 954, passive 620, trigger 487,
      activate_main 381, main 286, when_attacking 256, counter 199, on_ko 170...);
      **140 tipos de ação**; 88 condições; 34 tipos de custo; 95 parâmetros de passo.
      Cobertura por ondas: 10 ações -> 1.796 cartas (71%), 20 -> 2.177 (86%),
      40 -> 2.406 (95%), 140 -> 2.523. Mais usadas: buff_power 468, draw 380,
      play_card 316, keyword_blocker 307, ko 288, look_top_deck 232, add_to_hand 198,
      deck_bottom_rest 185, rest_opp_character 155, debuff_power 151. Falta: campos do
      estado (`GameState`/`Card`) e o fluxo do turno/combate do motor Python.
- [ ] Fase A.1 — esqueleto do núcleo + teste diferencial
