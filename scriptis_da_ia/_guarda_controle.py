"""Guarda: nenhum caractere de CONTROLE solto no codigo Python do projeto.

POR QUE EXISTE (30/08, perda de tempo real e reincidente no mesmo dia):

Ao escrever um regex atraves de heredoc, um escape de fronteira de palavra
virou o byte BACKSPACE (0x08) DENTRO do padrao: `r'...characters?<0x08>'`.
O arquivo compilava, o teste de sintaxe passava, e o regex simplesmente
NUNCA casava -- porque passou a exigir um backspace literal depois de
"characters". Foram tres tentativas em circulo ate imprimir
`inspect.getsource` da funcao que o interpretador de fato carregou e
enxergar o byte ali.

E aconteceu DE NOVO na hora de escrever este proprio teste: a primeira
versao, tambem via heredoc, injetou um byte NULO no `smoke_fast.py`. Por
isso a lista de bytes proibidos aqui e montada com `chr()` a partir de
numeros -- nao ha sequencia de escape nenhuma neste arquivo pra ser
mal-interpretada por quem o edita.

Permitidos: tab (0x09), \\n (0x0a), \\r (0x0d) e ESC (0x1b, usado de
proposito em `print` com cor ANSI).
"""
import glob
import os

# Montado por NUMERO de proposito -- ver o docstring. Sem escapes literais.
_PERMITIDOS = {9, 10, 13, 27}
BYTES_PROIBIDOS = frozenset(chr(n) for n in range(0x20) if n not in _PERMITIDOS)


def varre(raiz: str) -> list:
    """[(arquivo, linha, [bytes])] pra cada linha com caractere de controle."""
    achados = []
    for caminho in glob.glob(os.path.join(raiz, '**', '*.py'), recursive=True):
        if '__pycache__' in caminho:
            continue
        try:
            texto = open(caminho, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for n, linha in enumerate(texto.split('\n'), 1):
            ruins = sorted({hex(ord(c)) for c in linha if c in BYTES_PROIBIDOS})
            if ruins:
                achados.append((os.path.basename(caminho), n, ruins))
    return achados


if __name__ == '__main__':
    import sys
    r = varre(os.path.dirname(os.path.abspath(__file__)))
    for arq, n, b in r:
        print(f'{arq}:{n} {b}')
    print(f'{len(r)} linha(s) com caractere de controle')
    sys.exit(1 if r else 0)
