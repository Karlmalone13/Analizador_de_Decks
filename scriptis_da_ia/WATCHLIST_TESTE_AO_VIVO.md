# WATCH-LIST — teste ao vivo (Imu vs humano)

Consolidação do que observar na próxima partida ao vivo. Junta o que estava
espalhado: DTO trash (HANDOFF bloco 122), leva 7 (blocos 122/123) e o fix de
logging de DON desta sessão. Objetivo: a partida cara vira **confirmação
medida**, não sessão de debug. Regra: nada é "resolvido" só por impressão de
uma partida — ver memória `feedback_nao_declarar_resolvido_sem_partida_real`.

## 0. Setup (antes de jogar)
- [ ] Fechar o jogo → rodar `BOT\setup_bepinex.bat` (recompila+copia a DLL nova,
      já com o fix do log de DON). DLL compilada nesta sessão: 0 erros.
- [ ] Reabrir o jogo (DLL nova só carrega em processo novo).
- [ ] Engine server no ar.

## 1. Fix do log de DON do bot (NOVO nesta sessão) — habilitador de medição
Causa: o bot anexa DON via `AttachDonToCard` direto e pulava o `LogLine`, então
o DON dele **nunca aparecia no combat log** — a métrica `don_por_atk` (a mais
sensível da investigação de passividade) subcontava o bot. Fix: `TryAttachDon`
(`BotExecutor.cs`) agora emite a mesma linha `Log.AttachDonMulti` do arraste
humano.
- [ ] No combat log, procurar linhas **`[You] Attach N Don to X (... Total)`** —
      antes só existiam `[Opponent] Attach...`. Se aparecerem = fix funcionou.
- [ ] `python parse_combat_log.py <log> --add-to-db` → conferir que o bot tem
      `attach_don` > 0 nos turnos dele (antes: zero).

## 2. Passividade (a métrica-alvo) — agora mensurável
Baseline motor-vs-motor: bot ~0.6 DON/ataque vs oponente ~1.2–1.5.
- [ ] `don_por_atk` do bot **sobe** vs ~0.6.
- [ ] Volume de ataque/turno sobe (era 0.88 ao vivo vs 2.03 humano).
- [ ] % de ataques no líder (motor com info completa já dava ~91%).

Se persistir passivo MESMO medindo, suspeitos do TODO: (a) peso de corpo
agressivo vs utilitário em `_score_to_play`; (b) `_don_reserve_for_defense`
guardando DON demais. (Suspeito (c), logging, foi resolvido nesta sessão.)

## 3. Leva 7 (blocos 122/123) — validar ao vivo
- [ ] **Mars blocker** (keyword condicional `gain_blocker` trash_gte 7): com
      trash ≥ 7, Mars deve poder bloquear e o bot deve usá-lo como blocker.
- [ ] **Never Existed (OP13-098) no defensor**: +4000 vai pra carta que está
      **levando** o golpe (líder sob ataque), não pro Mars parado.
- [ ] **1º/2º por curva**: Imu (curva alta, 0 rush) deve escolher **SEGUNDO**.
- [ ] **Mars recém-descido não é sacrificado** pelo custo do líder/Shalria.
- [ ] **Empty Throne não é substituído** por stage redundante (Mary Geoise).

## 4. DTO trash/deckCount (bloco 122) — NUNCA testado ao vivo
- [ ] **Ground Death (OP14-096)** counterando com `trash ≥ 10`.
- [ ] **Imunidade Celestial Dragons** (`trash_gte:7`): remoção do oponente não
      mira os Celestial Dragons quando trash ≥ 7.
- [ ] **Progresso do GamePlan** (Five Elders) > 0.

## 5. Depois da partida (OBRIGATÓRIO)
- [ ] `python parse_combat_log.py <caminho_do.log> --add-to-db` (banco de logs —
      ver CLAUDE.md, não pular).
