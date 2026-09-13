# O ML é para o bot IR APRENDENDO — o critério surge dos testes

**Leitura obrigatória antes de qualquer commit.** Impressa por inteiro pelo
hook `pre-commit`, mesmo tratamento de `MEMORY.md` e
`REGRA_SEM_DUPLICACAO.md`.

## A regra, na palavra do usuário (13/09/2026, bloco 790)

> *"Vou te explicar uma coisa óbvia que vc não entendeu até agora, o machine
> learning é para o Bot ir aprendendo, então o critério para materializar vai
> surgir com os testes, o ML vai testando as alternativas e esse critério vai
> surgindo."*

Ele disse isso depois de eu perguntar, ao remover a heurística da busca:
*"sem a ordem estática, preciso de outro critério de qual filho
materializar"*.

## O que isso quer dizer

O critério **não existe no momento do desenho**. Ele é um **resultado** do
bot jogando: o ML testa as alternativas, vê o que dá certo, e o critério vai
se formando com os testes. Perguntar "qual é o critério?" antes de rodar é
perguntar por uma resposta que só a partida produz.

Consequência direta para qualquer desenho:

- **A pergunta certa não é "qual critério?", é "o bot consegue testar as
  alternativas e aprender com o resultado?"**
- Se o modelo só enxerga parte das opções, ele não tem como o critério
  emergir sobre as que ele nunca viu.
- Se o bot nunca tenta o que ainda não escolheria, os testes só confirmam o
  que ele já fazia — e nada emerge. É para isso que a exploração existe
  (`--explorar`, bloco 767).
- Se o resultado não volta como sinal de aprendizado, o teste não ensina
  nada. É o papel do rótulo do professor (bloco 783).

## O erro que isto corrige

Eu tratei "critério" como algo que **eu** precisava fornecer — e, não tendo,
fui procurar um substituto para escrever à mão. Isso inverte o sentido do
projeto: o ML não está aqui para executar um critério meu, está aqui **para
aprender o dele**.

> **Uma coisa óbvia que eu não tinha entendido:** o machine learning é para o
> bot IR APRENDENDO. O que emerge do aprendizado não precisa ser projetado
> antes.

## O que isto NÃO significa

Não é "tire todas as regras". Regra de **jogo** (legalidade, uma-vez-por-turno,
reserva de defesa) define o que é **possível** — não é critério, e não emerge
de teste nenhum. O que emerge é o julgamento de **valor**: qual jogada é
melhor, qual alvo vale mais, o que priorizar.

## Por que ficou preso ao hook

Pedido explícito dele: *"registra isso para vc não esquecer e coloque como
obrigação para vc lembrar antes de um commit"* — depois de ter dito, no mesmo
dia, que eu *"esqueço que estamos fazendo um ML e fico insistindo em coisas
antigas"*.

> **Registro de honestidade:** a primeira versão deste arquivo trocou a frase
> dele por uma regra sobre o meu comportamento ("você protege o que existe por
> reflexo"). Ele corrigiu na hora: *"a regra não é essa, isso aí vc inventou,
> leia de novo o que eu escrevi"*. Ficou aqui porque parafrasear o que ele
> disse já é uma forma de não ouvir.
