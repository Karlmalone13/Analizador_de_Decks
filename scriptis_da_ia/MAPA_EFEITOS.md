# Mapa Estrutural dos Efeitos do Engine

## Princípio (definido pelo usuário)
NÃO consertar carta por carta (milhares de cartas). Consertar os MECANISMOS
de execução de efeitos — cada gatilho ligado conserta centenas de cartas de uma vez.

## Estado dos gatilhos (carta-count no banco)

### ✅ EXECUTADOS pelo engine (funcionam)
- on_play (599) — efeito ao jogar
- main (202) — CORRIGIDO nesta sessão: _play_card agora executa 'main' além de
  'on_play'. Eram 202 eventos [Main] que não disparavam (Let's Crash, Five Elders, etc.)
- trigger (406) — efeito de vida ao tomar dano
- when_attacking (180) — efeito ao atacar
- on_ko (104) — efeito ao ser destruído

### ❌ NÃO EXECUTADOS (buracos estruturais, em ordem de prioridade)
1. passive (408) — efeitos contínuos (buffs permanentes tipo "+1000 a todos").
   O MAIOR buraco. Afeta cálculo de poder dinamicamente. Mais complexo.
2. activate_main (253) — efeitos [Activate: Main] ativáveis durante o turno.
   É o BUG 3 (Stage do Imu não ativa). O usuário já apontou. Falta a FASE de
   ativação no main_phase: percorrer cartas em campo (Stage + personagens) e
   decidir ativar.
3. counter (172) — eventos de counter para DEFESA. A IA usar evento de counter
   ao se defender (não só o counter impresso).
4. your_turn (74) / opp_turn (47) / end_of_turn (24) — momentos específicos.

## Próximo passo recomendado
Implementar activate_main (bug 3, já pedido) — adiciona a fase de ativação ao
main_phase. Depois passive (maior impacto). Cada um conserta centenas de cartas.

## Já corrigido nesta sessão (tudo GLOBAL, não por carta)
- Bug descarte duplo (parser) — 0 cartas duplicadas em todo o banco
- Bug condição de efeito (Otama) — função _effect_conditions_met checa life_lte,
  hand_lte, don_gte, trash_gte, leader_type etc. para TODAS as cartas com condição
- Eventos [Main] não disparavam — 202 eventos corrigidos
- Unificação replay→engine (fonte única)