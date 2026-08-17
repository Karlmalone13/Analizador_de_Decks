"""
gerar_dbs.py
============
Gera os DOIS bancos (effects + analysis) numa execução só, da mesma fonte.
Única porta de geração — os geradores individuais estão bloqueados.

Uso:
    python gerar_dbs.py
"""

import copy
import json

from gerar_effects_db import generate_effects_db
from gerar_card_analysis_db import generate_analysis_db

CSV = 'cards_rows.csv'

# ---------------------------------------------------------------------------
# Codigos que o SIMULADOR usa e que divergem do codigo IMPRESSO na carta.
#
# O banco (cards_rows.csv) e indexado pelo codigo impresso, que e o correto --
# confirmado lendo a arte da propria carta no jogo. Mas o OPTCGSim identifica
# algumas cartas por outro codigo, e ao vivo o bot recebe o codigo DELE. Sem
# alias, a carta chega desconhecida e vira "copia cega": sem efeito, sem
# custo, sem nome (achado 16/08, bloco 570 -- 4 copias do Thousand Sunny no
# deck real do usuario cairam nesse buraco).
#
# Mapa alias(jogo) -> codigo real(banco). Cada entrada aqui deve sair da
# varredura de `audit_game_code_divergence.py`, NUNCA de suposicao: o jogo
# atualiza e traz sets novos, entao rode aquele script depois de cada
# atualizacao do simulador em vez de manter esta lista na mao.
#
#   ST31-005 -> ST31-006  divergencia de NUMERO. O arquivo ST31-005.jpg do
#                         jogo contem a carta impressa "ST31-006" (Thousand
#                         Sunny); o set inteiro tem 5 cartas nos dois lados,
#                         so a ultima esta renumerada. ST31-004.jpg confere
#                         com o impresso, entao nao e o set todo deslocado.
#   St22-012 -> ST22-012  divergencia de CAIXA ('St' em vez de 'ST'), mesma
#                         carta (Marco). A busca no banco e case-sensitive.
# ---------------------------------------------------------------------------
ALIASES_DO_SIMULADOR = {
    'ST31-005': 'ST31-006',
    'St22-012': 'ST22-012',
}


def aplicar_aliases(banco: dict, nome_banco: str) -> int:
    """
    Adiciona as chaves-alias apontando para o MESMO conteudo da carta real.

    Feito aqui, na unica porta de geracao, de proposito: todo consumidor
    (decision_engine, api.py, bot_optcgsim) le os JSONs gerados, entao o
    alias vale pros tres sem nenhum resolvedor duplicado em cada ponto de
    lookup. A entrada carrega 'alias_de' pra continuar rastreavel.
    """
    aplicados = 0
    for alias, real in ALIASES_DO_SIMULADOR.items():
        if real not in banco:
            print(f'  AVISO ({nome_banco}): alias {alias} aponta para {real}, '
                  f'que nao existe no banco -- alias ignorado.')
            continue
        if alias in banco:
            print(f'  AVISO ({nome_banco}): {alias} JA existe como carta real '
                  f'-- alias nao aplicado (o banco manda).')
            continue
        entry = copy.deepcopy(banco[real])
        entry['alias_de'] = real
        banco[alias] = entry
        aplicados += 1
    return aplicados

TESTES = {
    'OP13-086': 'Saint Shalria',
    'OP13-099': 'The Empty Throne',
    'OP13-092': 'Saint Mjosgard',
    'OP13-082': 'Five Elders',
    'PRB02-008': 'Marco',
    'OP13-042': 'Edward Newgate SP',
    'OP13-046': 'Vista',
    'OP03-004': 'rush condicional a DON (regressao das 4 cartas)',
}


def main():
    # 1. effects_db (motor de jogo)
    print('[1/2] Gerando card_effects_db.json ...')
    effects = generate_effects_db(CSV)
    with open('card_effects_db.json', 'w', encoding='utf-8') as f:
        json.dump(effects, f, ensure_ascii=False, indent=2)
    print(f'      {len(effects)} cartas.')

    # 2. analysis_db (frontend/analisador)
    print('[2/2] Gerando card_analysis_db.json ...')
    analysis, skipped = generate_analysis_db(CSV)
    with open('card_analysis_db.json', 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=1)
    print(f'      {len(analysis)} cartas ({skipped} ignoradas).')

    # 2b. Aliases do simulador — aplicados aos DOIS bancos, senao a checagem
    # de chaves do passo 3 acusaria dessincronia (e o bot leria so um deles).
    n_ef = aplicar_aliases(effects, 'effects')
    n_an = aplicar_aliases(analysis, 'analysis')
    print(f'      aliases do simulador: {n_ef} em effects, {n_an} em analysis.')
    with open('card_effects_db.json', 'w', encoding='utf-8') as f:
        json.dump(effects, f, ensure_ascii=False, indent=2)
    with open('card_analysis_db.json', 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=1)

    # 3. Sanidade: chaves batem entre os dois
    ka, kb = set(effects), set(analysis)
    if ka != kb:
        print(f'  AVISO: chaves divergentes! so-effects={len(ka-kb)} so-analysis={len(kb-ka)}')
    else:
        print(f'OK: {len(ka)} cartas sincronizadas nos dois bancos.')

    # 4. Sanidade de parsing — checa os DOIS bancos (pega dessincronia)
    print()
    print('--- Sanidade de parsing (cartas-chave, effects + analysis) ---')
    for code, nome in TESTES.items():
        if code not in effects or code not in analysis:
            print(f'  {code} ({nome}): NAO ENCONTRADA')
            continue
        ef_effects = effects[code]['effects']
        ef_analysis = analysis[code]['effects']
        if ef_effects and not ef_analysis:
            print(f'  {code} ({nome}): DESSINCRONIZADA  <-- effects tem, analysis perdeu')
        elif not ef_effects:
            print(f'  {code} ({nome}): SEM EFEITOS  <-- verificar parser')
        else:
            triggers = ', '.join(ef_effects.keys())
            print(f'  {code} ({nome}): OK [{triggers}]')


if __name__ == '__main__':
    main()