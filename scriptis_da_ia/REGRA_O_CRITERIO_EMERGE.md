# O CRITÉRIO EMERGE DO APRENDIZADO — não é para você inventar

**Leitura obrigatória antes de qualquer commit.** Impressa por inteiro pelo
hook `pre-commit`, mesmo tratamento de `MEMORY.md` e
`REGRA_SEM_DUPLICACAO.md`.

## A regra, na palavra do usuário (13/09/2026, bloco 790)

> *"Vou te explicar uma coisa óbvia que vc não entendeu até agora, o machine
> learning é para o Bot ir aprendendo, então o critério para materializar vai
> surgir com os testes, o ML vai testando as alternativas e esse critério vai
> surgindo."*

Ele disse isso depois de eu perguntar, ao remover a heurística da busca:
*"sem a ordem estática, preciso de outro critério de qual filho materializar"*.

**A pergunta estava errada.** Eu estava procurando uma regra nova para escrever
à mão no lugar da regra velha que estava sendo removida. Isso é trocar uma
heurística por outra — e é, de novo, exatamente o que o projeto inteiro está
tentando parar de fazer.

## O TESTE, antes de propor qualquer coisa

> Você acabou de remover uma regra fixa e está procurando **com o que
> substituí-la**?
>
> **Pare.** A resposta é: o modelo testa as alternativas e o critério emerge.
> Sua tarefa é deixar o modelo ALCANÇAR as alternativas e aprender com o
> resultado — não escolher por ele.

Se a proposta contém "critério", "prioridade", "ordem" ou "limiar" seguido de
um número ou de uma fórmula escrita por você, ela é uma heurística nova. O
nome não importa.

## O que FAZER no lugar

1. **Deixar o modelo ver as alternativas.** Se ele só pontua 6 de 14 opções,
   o problema é o alcance, não o critério — amplie o que ele enxerga.
2. **Deixar o modelo tentar o que ele ainda não escolheria.** É para isso que
   a exploração existe (`--explorar`, bloco 767): sem tentar, o auto-jogo é
   eco e o corpus só contém o que ele já fazia.
3. **Deixar o resultado ensinar.** O rótulo do professor (bloco 783) é o que
   transforma "tentei" em "aprendi".
4. **Medir depois**, com o AS-IS e com o portão — não antes, e não no lugar.

## O que isto NÃO autoriza

Não é "tire todas as regras e veja o que acontece". Regra de **jogo**
(legalidade, uma-vez-por-turno, reserva de defesa) é restrição, não critério —
ela define o que é possível, não o que é bom. O que sai são as regras de
**valor**: qual jogada é melhor, qual alvo vale mais, o que priorizar.

A distinção em uma linha:

> **O que é LEGAL: regra. O que é BOM: modelo.**

## Por que ficou registrado com hook

Porque eu esqueci. Repetidamente, no mesmo dia: o usuário teve que dizer
*"parece que vc esquece que estamos fazendo um ML e fica insistindo em coisas
antigas"*, e pediu explicitamente que isto virasse obrigação de leitura antes
de commitar.
