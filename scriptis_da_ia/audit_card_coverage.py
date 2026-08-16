"""
audit_card_coverage.py -- varredura do banco INTEIRO respondendo as 3 perguntas
que o usuario formulou (16/08/2026, bloco 566), depois do bug do lider Luffy
OP13-001:

  1. O bot SABE o que a carta faz?     -> a carta tem efeito parseado?
  2. O bot CONSEGUE USAR o efeito?     -> o CUSTO tem deteccao no caminho ao vivo?
  3. O motor CONSEGUE EXECUTAR?        -> a ACTION tem implementacao no executor?

Por que existe: o bug do Luffy (bloco 565) nao era decisao ruim nem parser
errado -- o efeito era conhecido E executavel, mas a JANELA nunca era detectada
pelo plugin porque o custo era `rest_any_don` e o plugin so reconhecia custo de
trashar carta da mao. Resultado: 12 ataques sofridos na partida ao vivo e ZERO
decisoes de `reaction`. Um buraco assim e invisivel em teste de motor (o
simulador interno paga o custo sem passar pelo plugin) e so aparece ao vivo,
numa carta especifica -- exatamente o tipo de coisa que precisa de varredura,
nao de caso a caso.

LIMITACAO HONESTA (leia antes de tratar a saida como veredito): as checagens 2
e 3 sao ESTATICAS -- procuram o nome do custo/action como literal no codigo do
motor e do plugin. Isso pega o caso "nao existe tratamento nenhum" (o bug do
Luffy), que e o alvo. NAO prova que o tratamento existente esta CORRETO, e pode
dar falso-positivo se o codigo montar o nome dinamicamente. Cada achado e um
PONTO DE PARTIDA pra confirmar na mao, no mesmo espirito da ressalva do
`decision_quality_report.py`.

Uso:
    python audit_card_coverage.py                 # resumo das 3 perguntas
    python audit_card_coverage.py --detalhe custo # lista cartas afetadas
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
ENGINE = os.path.join(AQUI, 'optcg_engine', 'decision_engine.py')
BRIDGE = os.path.join(AQUI, 'optcg_engine', 'sim_bridge.py')
PLUGIN_DIR = os.path.join(RAIZ, 'BOT', 'OPTCGBotPlugin')

# Gatilhos que exigem uma JANELA do jogo pra serem oferecidos ao vivo (o bot
# precisa que o plugin detecte a tela). Gatilhos passivos/automaticos nao
# passam por isso -- resolvem sozinhos no motor.
TRIGGERS_INTERATIVOS = {
    'on_play', 'main', 'activate_main', 'when_attacking', 'counter',
    'on_opp_attack', 'trigger', 'on_block', 'leader_battle_reactive',
}


def _ler(path: str) -> str:
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read()
    except OSError:
        return ''


def _fonte_plugin() -> str:
    if not os.path.isdir(PLUGIN_DIR):
        return ''
    return '\n'.join(_ler(os.path.join(PLUGIN_DIR, f))
                     for f in os.listdir(PLUGIN_DIR) if f.endswith('.cs'))


def carregar_db():
    with open(os.path.join(AQUI, 'card_effects_db.json'), encoding='utf-8') as fh:
        return json.load(fh)


def carregar_textos():
    textos = {}
    csv.field_size_limit(10 ** 7)
    with open(os.path.join(AQUI, 'cards_rows.csv'), encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            textos[row['card_set_id']] = (row.get('card_text') or '',
                                          row.get('card_name') or '')
    return textos


def blocos_de(ef: dict):
    """Todo bloco de steps do efeito, incluindo as opcoes de um `choice`."""
    yield ef
    for opt in ef.get('choice') or []:
        yield {'steps': opt if isinstance(opt, list) else [opt]}


def varrer():
    db = carregar_db()
    textos = carregar_textos()
    engine_src = _ler(ENGINE) + _ler(BRIDGE)
    plugin_src = _fonte_plugin()

    acoes = Counter()
    custos = Counter()
    custo_cartas = defaultdict(list)
    acao_cartas = defaultdict(list)
    sem_efeito = []

    for code, e in db.items():
        efeitos = e.get('effects') or {}
        texto, nome = textos.get(code, ('', e.get('name', '')))

        # Pergunta 1: tem texto com gatilho mas nenhum efeito parseado?
        if not efeitos and re.search(r'\[(On Play|Activate: Main|When Attacking|'
                                     r'Counter|Trigger|On K\.O\.|On Block|'
                                     r"On Your Opponent's Attack)\]", texto, re.I):
            sem_efeito.append((code, nome, texto[:80]))

        for trig, ef in efeitos.items():
            if not isinstance(ef, dict):
                continue
            for b in blocos_de(ef):
                for s in b.get('steps') or []:
                    if isinstance(s, dict) and s.get('action'):
                        acoes[s['action']] += 1
                        acao_cartas[s['action']].append(code)
            for c in ef.get('costs') or []:
                if isinstance(c, dict) and c.get('type'):
                    t = c['type']
                    custos[t] += 1
                    if trig in TRIGGERS_INTERATIVOS:
                        custo_cartas[t].append(code)

    # Pergunta 3: a action aparece no motor?
    acoes_sem_motor = {a: n for a, n in acoes.items()
                       if f"'{a}'" not in engine_src and f'"{a}"' not in engine_src}
    # Pergunta 2: o custo aparece no motor (pagar) e no plugin (detectar janela)?
    custos_sem_motor = {c: n for c, n in custos.items()
                        if f"'{c}'" not in engine_src and f'"{c}"' not in engine_src}

    return {
        'db': db, 'acoes': acoes, 'custos': custos,
        'acao_cartas': acao_cartas, 'custo_cartas': custo_cartas,
        'sem_efeito': sem_efeito,
        'acoes_sem_motor': acoes_sem_motor,
        'custos_sem_motor': custos_sem_motor,
        'plugin_src': plugin_src,
    }


def _deteccao_plugin(plugin_src: str) -> dict:
    """
    Quais MOEDAS de custo o plugin sabe detectar como janela opcional ao vivo.
    Mapeia o campo do jogo (ActV3Effect) que cada deteccao usa -> tipos de custo
    do nosso banco que caem nela. Ampliar aqui quando uma deteccao nova entrar.
    """
    # Procura o CAMPO (`.TrashCard`), nao a expressao inteira: o plugin acessa
    # via variavel local (`ef.DonMinus`), nao `effect.DonMinus`. A 1a versao
    # disto casava a expressao completa e deu FALSO NEGATIVO nos 3 custos que
    # o bloco 566 acabara de cobrir -- achado ao rodar a varredura logo depois
    # do fix e ver "NAO" no que ja estava implementado.
    def tem(campo: str) -> bool:
        return re.search(r'\.\s*' + re.escape(campo) + r'\b', plugin_src) is not None

    return {
        'trash_from_hand':     tem('TrashCard'),
        'trash_any_from_hand': tem('TrashCard'),
        'trash_char_or_hand':  tem('TrashCard'),
        'rest_any_don':        tem('DonTap'),
        'rest_don':            tem('DonTap'),
        'rest_self':           tem('RestSelf'),
        'don_minus':           tem('DonMinus'),
        'trash_self':          tem('TrashSelf'),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--detalhe', choices=['custo', 'acao', 'parser'],
                    help='lista as cartas afetadas de uma das 3 perguntas')
    ap.add_argument('--top', type=int, default=25)
    args = ap.parse_args()

    r = varrer()
    det = _deteccao_plugin(r['plugin_src'])

    print('=' * 74)
    print(f"VARREDURA DE COBERTURA -- {len(r['db'])} cartas no banco")
    print('=' * 74)

    print('\n1) O BOT SABE O QUE A CARTA FAZ? (tem efeito parseado)')
    print(f"   cartas com gatilho no texto e SEM efeito parseado: {len(r['sem_efeito'])}")
    for code, nome, txt in r['sem_efeito'][:args.top]:
        print(f'     {code:12} {nome[:26]:28} {txt[:44]}')

    print('\n2) O BOT CONSEGUE USAR O EFEITO? (custo detectavel ao vivo)')
    print(f"   tipos de custo no banco: {len(r['custos'])}")
    if r['custos_sem_motor']:
        print('   -- custo SEM tratamento no motor (nao paga nem avalia):')
        for c, n in sorted(r['custos_sem_motor'].items(), key=lambda x: -x[1]):
            print(f'     {c:34} {n:4}x')
    else:
        print('   -- todo custo do banco tem tratamento no motor: OK')

    print('   -- deteccao da JANELA pelo plugin (o buraco do Luffy):')
    faltando = []
    for custo, tem in sorted(det.items()):
        cartas = r['custo_cartas'].get(custo, [])
        if not cartas:
            continue
        marca = 'OK ' if tem else 'NAO'
        print(f'     [{marca}] {custo:30} {len(cartas):4} cartas com gatilho interativo')
        if not tem:
            faltando.append((custo, cartas))
    nao_mapeados = [c for c in r['custos'] if c not in det and r['custo_cartas'].get(c)]
    if nao_mapeados:
        print('   -- custos SEM mapeamento de deteccao conhecido (verificar na mao):')
        for c in sorted(nao_mapeados, key=lambda x: -len(r['custo_cartas'][x]))[:args.top]:
            print(f'     [ ? ] {c:30} {len(r["custo_cartas"][c]):4} cartas')

    print('\n3) O MOTOR CONSEGUE EXECUTAR O EFEITO? (action implementada)')
    print(f"   actions distintas no banco: {len(r['acoes'])}")
    if r['acoes_sem_motor']:
        print('   -- action SEM implementacao no motor (efeito vira no-op):')
        for a, n in sorted(r['acoes_sem_motor'].items(), key=lambda x: -x[1])[:args.top]:
            exemplos = ', '.join(r['acao_cartas'][a][:3])
            print(f'     {a:34} {n:4}x  ex: {exemplos}')
    else:
        print('   -- toda action do banco aparece no motor: OK')

    if args.detalhe == 'custo' and faltando:
        print('\n--- cartas afetadas por custo sem deteccao ---')
        for custo, cartas in faltando:
            print(f'\n{custo} ({len(cartas)}):')
            for c in cartas[:args.top]:
                print('   ', c, r['db'][c].get('name', ''))
    elif args.detalhe == 'acao':
        print('\n--- cartas afetadas por action sem motor ---')
        for a in r['acoes_sem_motor']:
            print(f'\n{a}:')
            for c in r['acao_cartas'][a][:args.top]:
                print('   ', c, r['db'][c].get('name', ''))
    elif args.detalhe == 'parser':
        print('\n--- cartas com gatilho no texto e sem efeito parseado ---')
        for code, nome, txt in r['sem_efeito']:
            print(f'  {code:12} {nome[:28]:30} {txt}')

    print('\nLEITURA: checagens 2 e 3 sao ESTATICAS (procuram o nome no codigo).')
    print('Pegam "nao existe tratamento nenhum" -- que foi o bug do Luffy -- mas')
    print('NAO provam que o tratamento existente esta correto. Confirme na mao.')


if __name__ == '__main__':
    main()
