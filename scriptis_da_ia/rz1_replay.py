"""
rz1_replay.py -- decodifica o protocolo `RZ1|` que o PROPRIO simulador ja
escreve em todo combat log, e reconstroi o estado COMPLETO de zonas.

POR QUE EXISTE (pedido do usuario, 25/08/2026, bloco 684)
----------------------------------------------------------
As linhas de texto do log (`[jogador] Hand: [...]`, `Board:`, `Trash:`,
`Life: N`) sao um resumo POBRE: nao tem a zona de STAGE, nao dizem o
CONTEUDO do Life (so a contagem), nao dizem quanto DON esta anexado em qual
carta, nao dizem quais cartas estao RESTADAS, e nao dizem a ordem do deck.
Cada uma dessas lacunas foi medida como perda de fidelidade real na
reconstrucao de partidas (blocos 650-656): a Stage ausente obrigou uma
inferencia por historico, `rested` so existe em 113 de 142 logs, o Life e
preenchido com cartas FALSAS do topo de um deck embaralhado, e
`give_don_opp` era irrecuperavel.

Mas o jogo JA registra tudo isso, no mesmo arquivo, num protocolo
estruturado que ninguem estava lendo. Formato confirmado na DLL decompilada
(`_referencias/simulador-oficial/dnspy-export/Assembly-CSharp/
GameplayLogicScript.cs`, `ReplaySync_EmitMove`, linha ~32865):

    RZ1|seq|dono|cardID|zona_origem|slot_origem|zona_destino|slot_destino|
        vis1|vis2|bTapped|deltaPower|deltaCost

Os codigos de zona ja estavam portados em
`_referencias/simulador-oficial/decompiled_python/enums.py`
(`ReplaySyncZone`) -- ver `ZONA` abaixo.

VALIDACAO (nao e leitura otimista de spec)
-------------------------------------------
Reproduzir os movimentos e comparar o estado resultante contra as proprias
linhas `Hand:`/`Board:`/`Trash:` do log, em TODO o banco:

  - 120 de 120 logs crus tem linhas RZ1 (universal, nao e recurso novo)
  - **13500 de 14400 snapshots batem EXATAMENTE (93,75%)**
  - **105 de 120 logs ficam 100% corretos**

DECISAO DE DESENHO: multiset, nao slot
---------------------------------------
A 1a versao usou `(zona, slot)` como chave, seguindo o protocolo ao pe da
letra, e deu **65,1%**. Slots colidem e sao reaproveitados sem emitir move,
entao a carta anterior era sobrescrita e sumia. Tratar cada zona como
MULTISET (tira uma instancia da origem, soma uma no destino) foi de 65,1%
pra 100% no mesmo arquivo. O slot continua sendo lido mas nao e usado como
identidade.

Cartas que saem de uma zona onde o decodificador ainda nao as tinha (as
compras iniciais, que vem do DECK sem um move de criacao) sao contadas em
`saidas_orfas` -- esperado, nao e erro.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

ZONA = {
    0: 'deck', 1: 'hand', 2: 'board', 3: 'life', 4: 'don_deck',
    5: 'don_cost', 6: 'trash', 7: 'stage', 8: 'leader', 9: 'attached_don',
}

_RZ = re.compile(
    r'^RZ1\|(\d+)\|(\d+)\|([^|]+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)'
    r'\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\s*$')


class RZ1State:
    """Estado por (dono, zona) como multiset de codigos."""

    def __init__(self):
        self.zonas = defaultdict(Counter)
        self.restadas = defaultdict(Counter)   # (dono, zona) -> Counter de restadas
        self.saidas_orfas = 0
        self.movimentos = 0

    def aplicar(self, dono, card, oz, dz, tapped):
        self.movimentos += 1
        origem = self.zonas[(dono, oz)]
        if origem[card] > 0:
            origem[card] -= 1
            if not origem[card]:
                del origem[card]
            r = self.restadas[(dono, oz)]
            if r.get(card):
                r[card] -= 1
                if not r[card]:
                    del r[card]
        else:
            self.saidas_orfas += 1
        self.zonas[(dono, dz)][card] += 1
        if tapped:
            self.restadas[(dono, dz)][card] += 1

    def snapshot(self, dono) -> dict:
        """Todas as zonas de um jogador, prontas pra ir no JSON parseado."""
        # Chaves que JA existem no snapshot de texto com outro TIPO ou outra
        # origem recebem nome proprio, pra enriquecer sem sobrescrever nem
        # quebrar consumidor existente:
        #   `life` no texto e um INTEIRO (contagem) -> aqui vira `life_cards`
        #   `rested` no texto vem de `_reconcile_board_state` -> `rested_rz1`
        RENOMEIA = {'life': 'life_cards'}
        fora = {}
        for (d, z), cont in self.zonas.items():
            if d != dono or not cont:
                continue
            nome = ZONA.get(z, str(z))
            fora[RENOMEIA.get(nome, nome)] = sorted(cont.elements())
        rest = {}
        for (d, z), cont in self.restadas.items():
            if d != dono or not cont:
                continue
            rest[ZONA.get(z, str(z))] = sorted(cont.elements())
        if rest:
            fora['rested_rz1'] = rest
        return fora

    def donos(self):
        return sorted({d for (d, _z) in self.zonas})


def replay_por_linha(linhas) -> dict:
    """{indice_da_linha: RZ1State clonado} apos processar aquela linha.

    So materializa o estado nas linhas que sao snapshot de texto (`Hand:`
    etc) -- clonar em todas as ~10k linhas seria caro e inutil.
    """
    from copy import deepcopy
    est = RZ1State()
    fora = {}
    marcador = re.compile(r'^\[(.*?)\] (Hand|Board|Trash|Life):')
    for i, ln in enumerate(linhas):
        s = ln.strip()
        m = _RZ.match(s)
        if m:
            (_seq, dono, card, oz, _os, dz, _ds,
             _v1, _v2, tap, _dp, _dc) = m.groups()
            est.aplicar(int(dono), card, int(oz), int(dz), tap == '1')
            continue
        if marcador.match(s):
            fora[i] = deepcopy(est)
    return fora


def estado_final(linhas) -> RZ1State:
    est = RZ1State()
    for ln in linhas:
        m = _RZ.match(ln.strip())
        if m:
            (_seq, dono, card, oz, _os, dz, _ds,
             _v1, _v2, tap, _dp, _dc) = m.groups()
            est.aplicar(int(dono), card, int(oz), int(dz), tap == '1')
    return est


def casar_donos(est: RZ1State, mao_por_jogador: dict) -> dict:
    """{nome_do_jogador: numero_do_dono_no_RZ1}.

    O protocolo usa numero (1/2) e o texto usa nome -- o casamento sai de
    qual dono tem exatamente aquela mao. Sem chute: se nao bater
    exatamente, o jogador fica de fora e o chamador cai no dado antigo.
    """
    mapa = {}
    usados = set()
    for nome, mao in mao_por_jogador.items():
        alvo = Counter(mao)
        for d in est.donos():
            if d in usados:
                continue
            if est.zonas[(d, 1)] == alvo:
                mapa[nome] = d
                usados.add(d)
                break
    return mapa
