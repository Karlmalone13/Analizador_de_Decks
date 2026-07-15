# Mapa vivo da varredura do parser

Atualizado em 15/07/2026 apos os commits `1ed24a8`, `d333c0e` e `70207a7`.

## Regra de classificacao

1. `audit_parser_coverage.py` encontra candidatos comparando numeros do texto
   local com o JSON parseado.
2. O texto local e o JSON servem para localizar a divergencia, nao para provar
   a regra da carta.
3. `CONFIRMADO` exige comparacao com Card List oficial da Bandai e, quando
   existir duvida semantica, com o Q&A oficial.
4. `SUSPEITO FORTE` significa que o JSON perdeu informacao aparente, mas a
   fonte oficial ainda nao foi conferida nesta rodada.
5. `FALSO POSITIVO` exige que toda a semantica relevante esteja representada
   ou executada, mesmo que um numero implicito nao apareca literalmente no
   JSON.

## Estado da fila

- Suspeitos antes da retomada: 433.
- Apos condicoes de vida encadeadas: 429.
- Apos OP02-110 Hina: 428.

## Mapa dos primeiros candidatos por uso real

| Carta | Estado | Divergencia atual | Fonte oficial |
|---|---|---|---|
| OP06-115 | CONFIRMADO ERRO | Trigger perdeu `life_lte: 0`; hoje ganha Life mesmo com Life > 0 | Card List oficial confirma o gate de 0 Life |
| OP15-008 | PROVAVEL FALSO POSITIVO | Numero 1 e o alvo unico implicito de `give_don_opp`; demais campos estao presentes | Pendente reconferencia nesta rodada |
| OP06-022 | PROVAVEL FALSO POSITIVO | Numero 1 e alvo unico implicito de `give_don`; `count=2` e `opp_life_lte=3` existem | Pendente reconferencia nesta rodada |
| OP03-078 | CONFIRMADO ERRO | `[On Play]` inteiro ausente: `opp_hand_gte=6` + trash 2 da mao oponente | Card List oficial confirma texto integral |
| ST13-010 | SUSPEITO FORTE | Reveal da Life, filtro Ace custo 5 e play da carta ausentes | Pendente Card List/Q&A oficial |
| EB02-019 | CONFIRMADO ERRO | `gain_rush` incondicional e amplo; texto exige 2+ Characters oponentes e so permite atacar Characters | Card List oficial confirma texto; Q&A oficial existe |
| EB02-035 | SUSPEITO FORTE | Falta limiar de 2 DON retornados e comparacao relativa de DON no On Play | Pendente Card List/Q&A oficial |
| OP05-088 | SUSPEITO FORTE | Custo de devolver 2 cartas do trash ao deck ausente | Pendente Card List/Q&A oficial |
| OP05-097 | SUSPEITO FORTE | Reducao perdeu filtro de custo 2+ | Pendente Card List/Q&A oficial |
| OP06-097 | SUSPEITO FORTE | `[Main] trash 1` da mao oponente ausente; so Trigger sobreviveu | Pendente Card List/Q&A oficial |
| OP07-064 | SUSPEITO FORTE | Debuff de custo perdeu condicao relativa de DON (2 a menos) | Pendente Card List/Q&A oficial |
| OP09-118 | PROVAVEL FALSO POSITIVO | Zero Life e checado pelo handler especial de vitoria, nao gravado como campo numerico | Pendente reconferencia oficial nesta rodada |
| OP11-070 | SUSPEITO FORTE | Filtro `cost_gte=2` ausente no On Play e Activate Main inteiro ausente | Pendente Card List/Q&A oficial |
| OP12-117 | SUSPEITO FORTE | JSON modela `gain_life` do deck, mas texto aparenta mover Character para Life do dono com custo <=9 | Pendente Card List/Q&A oficial |
| OP13-002 | SUSPEITO FORTE | Dois gatilhos distintos parecem fundidos; threshold de base power 6000 sumiu | Pendente Card List/Q&A oficial |
| OP13-016 | SUSPEITO FORTE | So Sabo sobreviveu da lista de Leaders e `cost_gte=3` sumiu | Pendente Card List/Q&A oficial |
| OP13-079 | REVISAR ESCOPO | Numero 2 pertence a regra de construcao do deck, nao necessariamente a efeito executavel em partida | Pendente regra oficial e decisao de escopo |
| OP13-080 | PROVAVEL FALSO POSITIVO | Numero 1 e alvo unico implicito; thresholds 7/10 e Rush/imunidade estao presentes | Pendente reconferencia oficial nesta rodada |

## Proxima ordem

1. Corrigir OP06-115, ja confirmado oficialmente.
2. Corrigir OP03-078, ja confirmado oficialmente.
3. Validar e corrigir EB02-019 com o Q&A oficial para preservar a diferenca
   entre Rush e permissao de atacar apenas Characters.
4. Buscar fonte oficial de ST13-010 antes de implementar.
5. Continuar o mapa em lotes pequenos, sempre registrando a URL oficial usada.
