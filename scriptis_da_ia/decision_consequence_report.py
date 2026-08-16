"""
Consequencia POR DECISAO INDIVIDUAL -- o que cada jogada especifica de fato
produziu, nao a media agregada.

Por que existe (pedido do usuario, 15/08/2026, bloco 548): o
`future_state_delta_by_decisions` do `bot_efficiency_report.py` ja mede
delta de estado 1/3/5 decisoes depois, mas so como MEDIA de todas as
decisoes juntas -- nunca liga UMA decisao especifica ao que aconteceu
depois dela. Com isso, o caso concreto que o usuario reclamou na partida
real de 15/08 ("insistencia em botar 5 dons em personagem [de poder base
0] so pra atacar, sendo que tem carta boa na mao") fica invisivel: a
media dilui o all-in que falhou junto com dezenas de decisoes normais.
Este relatorio responde "essa jogada de anexar 5 DON no Doc Q levou a
QUE, exatamente?" -- por decisao, com o turno/carta/score do contexto.

O que mede, por decisao de main com execucao CONFIRMADA:
- **investimento**: DON comprometido (custo da carta via `score_components.
  don_cost` + `donToAttach` da resposta real enviada ao plugin).
- **retorno**, em 4 horizontes: 1, 3 e 5 decisoes a frente, e ate o FIM DO
  TURNO (o mais relevante em OPTCG -- DON gasto num turno deveria pagar
  nesse mesmo turno, ja que desresta no refresh seguinte). Cada retorno e
  medido do `state_before` da propria decisao ate o `state_after` do
  horizonte, cobrindo o efeito da decisao em si:
  `dano` (vida do oponente perdida), `board_removido` (personagens do
  oponente que sairam), `board_ganho` (nossos personagens que entraram),
  `mao_delta`.
- **veredito automatico**: decisao com investimento alto (>= `--don-minimo`,
  default 3) e retorno ZERO em tudo ate o fim do turno vira
  `DON_SEM_RETORNO` -- o padrao exato da reclamacao acima.

LIMITACOES HONESTAS (leia antes de tratar um veredito como bug):
- `DON_SEM_RETORNO` NAO e prova de decisao ruim. Um ataque legitimo de
  pressao que o oponente respondeu com counter aparece aqui (foi o caso
  real da partida de 15/08 -- ver bloco 544: informacao oculta, nao falha
  de codigo). O relatorio prioriza o que MERECE leitura manual, exatamente
  como `triage_real_losses.py` faz com MATCH/DIVERGE -- nao e veredito.
- So enxerga decisoes com `state_before` E execucao confirmada com
  `state_after`. Cobertura parcial e reportada explicitamente.
- Deltas sao de CONTAGEM (quantas cartas), nao de valor estrategico -- um
  personagem de 1000 e um de 12000 contam igual no `board_removido`.
- Correlacao, nao causalidade: entre a decisao e o horizonte podem ter
  acontecido acoes do oponente (o horizonte "fim do turno" reduz isso, mas
  nao elimina -- counter/blocker do oponente entram na janela).

Uso:
    python decision_consequence_report.py                    # sessao mais recente
    python decision_consequence_report.py --session <nome>
    python decision_consequence_report.py --file <caminho.jsonl>
    python decision_consequence_report.py --don-minimo 4 --top 15
"""
import argparse
import glob
import json
import os
from collections import defaultdict

DECISIONS_DIR = os.path.join('..', 'BOT', 'engine_server', 'logs', 'decisions')


def _latest_decisions_file() -> str | None:
    files = sorted(glob.glob(os.path.join(DECISIONS_DIR, 'decisions_*.jsonl')))
    return files[-1] if files else None


def _load(path: str) -> list[dict]:
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _counts(state: dict | None) -> dict | None:
    """Contagens comparaveis de um snapshot de estado (bot/opp)."""
    if not isinstance(state, dict) or 'bot' not in state or 'opp' not in state:
        return None
    bot, opp = state.get('bot') or {}, state.get('opp') or {}
    return {
        'opp_life': len(opp.get('life') or []),
        'opp_board': len(opp.get('board') or []),
        'bot_board': len(bot.get('board') or []),
        'bot_hand': len(bot.get('hand') or []),
    }


def _investimento_don(decision: dict) -> int:
    """DON comprometido pela decisao.

    Duas fontes: `don_cost` (do `score_components` da acao ESCOLHIDA, o
    custo que o motor previu) e `donToAttach` (da resposta REAL enviada ao
    plugin, o DON de fato anexado).

    CUIDADO -- elas NAO somam sempre: numa acao `attach_don` as duas
    descrevem o MESMO DON (achado ao validar contra o log do plugin,
    15/08: uma decisao com `don_cost=3` + `donToAttach=3` virava
    "6 DON" no relatorio, enquanto o plugin registrou "attach_don: 3/3
    DON em OP16-110" -- o dobro do real, o que inflava o percentual de
    DON desperdicado). So somam quando sao gastos distintos (jogar uma
    carta de custo N e, noutra decisao, anexar DON num ataque).
    """
    chosen = decision.get('chosen_action') or {}
    custo = 0
    for acao in decision.get('scored_actions') or []:
        if (acao.get('type') == chosen.get('type')
                and acao.get('card_uid') == chosen.get('card_uid')
                and acao.get('target_uid') == chosen.get('target_uid')):
            valor = (acao.get('score_components') or {}).get('don_cost')
            if isinstance(valor, (int, float)):
                custo = int(valor)
            break
    anexado = (decision.get('response') or {}).get('donToAttach')
    anexado = int(anexado) if isinstance(anexado, (int, float)) else 0
    if chosen.get('type') == 'attach_don':
        return max(custo, anexado)
    return custo + anexado


def _build_index(eventos: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Decisoes de main em ordem + o state_after confirmado de cada uma."""
    decisoes, state_after = [], {}
    for ev in eventos:
        if ev.get('event') == 'execution':
            if ev.get('status') == 'confirmed' and ev.get('state_after'):
                state_after[ev.get('decision_id')] = ev['state_after']
        elif ev.get('event') == 'decision' and ev.get('decision_kind') == 'main':
            decisoes.append(ev)
    return decisoes, state_after


def _retorno(antes: dict, depois: dict) -> dict:
    return {
        'dano': antes['opp_life'] - depois['opp_life'],
        'board_removido': antes['opp_board'] - depois['opp_board'],
        'board_ganho': depois['bot_board'] - antes['bot_board'],
        'mao_delta': depois['bot_hand'] - antes['bot_hand'],
    }


# Que metricas contam como RETORNO de cada tipo de acao. Achado ao validar
# na partida de 15/08: usar as 4 metricas pra tudo classificava errado o
# caso que o usuario reclamou -- o ataque do Doc Q (5 DON, dano zero em
# todo horizonte) aparecia como "pagou depois" so porque `board_ganho`
# subiu +1 num horizonte adiante... por causa de OUTRA decisao (jogar
# outra carta), nada a ver com o ataque. Um ataque so "paga" causando
# dano ou removendo personagem do oponente; crescer o proprio board/mao
# depois nao e obra dele.
_RETORNO_RELEVANTE = {
    'attack': ('dano', 'board_removido'),
    'play': ('dano', 'board_removido', 'board_ganho'),
    'activate': ('dano', 'board_removido', 'board_ganho', 'mao_delta'),
    'attach_don': ('dano', 'board_removido', 'board_ganho', 'mao_delta'),
}
_RETORNO_PADRAO = ('dano', 'board_removido', 'board_ganho', 'mao_delta')


def _sem_retorno(r: dict | None, acao: str | None = None) -> bool:
    """True se NENHUMA metrica relevante pra essa acao ficou positiva."""
    if r is None:
        return False
    chaves = _RETORNO_RELEVANTE.get(acao or '', _RETORNO_PADRAO)
    return all(r[k] <= 0 for k in chaves)


def analisar(eventos: list[dict], don_minimo: int = 3) -> dict:
    decisoes, state_after = _build_index(eventos)

    # Agrupa por partida preservando a ordem; o horizonte "fim do turno"
    # precisa saber qual e a ULTIMA decisao do mesmo turno.
    por_partida: dict[str, list[dict]] = defaultdict(list)
    for d in decisoes:
        por_partida[d.get('match_id') or 'legacy'].append(d)

    linhas, sem_cobertura = [], 0
    for partida, ds in por_partida.items():
        ultimo_indice_do_turno: dict[int, int] = {}
        for i, d in enumerate(ds):
            ultimo_indice_do_turno[d.get('turn')] = i

        for i, d in enumerate(ds):
            antes = _counts(d.get('state_before'))
            if antes is None:
                sem_cobertura += 1
                continue

            retornos: dict[str, dict | None] = {}
            for h in (1, 3, 5):
                alvo = i + h - 1
                if alvo >= len(ds):
                    retornos[str(h)] = None
                    continue
                depois = _counts(state_after.get(ds[alvo].get('decision_id')))
                retornos[str(h)] = _retorno(antes, depois) if depois else None

            fim = ultimo_indice_do_turno.get(d.get('turn'))
            depois_fim = (_counts(state_after.get(ds[fim].get('decision_id')))
                          if fim is not None and fim >= i else None)
            retornos['fim_do_turno'] = _retorno(antes, depois_fim) if depois_fim else None

            if all(v is None for v in retornos.values()):
                sem_cobertura += 1
                continue

            chosen = d.get('chosen_action') or {}
            don = _investimento_don(d)
            # O veredito usa o EFEITO DIRETO (horizonte 1 = o `state_after`
            # da PROPRIA decisao) -- a unica janela genuinamente atribuivel
            # a ela. Achado ao validar a ferramenta contra a partida real de
            # 15/08: julgar pelo fim do turno mascarava justamente o caso que
            # o usuario reclamou (ataque do Doc Q com 5 DON, dano 0), porque
            # a mao crescer/o board mudar por causa de OUTRAS decisoes do
            # mesmo turno contava como "teve retorno". Os horizontes 3/5/fim
            # do turno continuam no relatorio como CONTEXTO (mostram se a
            # jogada preparou algo que pagou depois), nunca como veredito.
            direto = retornos['1']
            # Distincao que separa o falso positivo do problema real (achado
            # ao validar na partida de 15/08): um `attach_don` pode ter
            # efeito direto zero e MESMO ASSIM ser a jogada certa -- o
            # horizonte 3 mostra o dano que ele viabilizou (anexar DON nao
            # causa dano sozinho, habilita o ataque seguinte). Ja o ataque
            # do Doc Q com 5 DON deu zero em TODOS os horizontes com dado.
            # `PERSISTENTE` e o sinal forte; `DON_SEM_RETORNO` sozinho pode
            # ser so preparacao legitima.
            acao = (chosen.get('type') or (d.get('response') or {}).get('type') or '-')
            com_dado = [v for v in retornos.values() if v is not None]
            nunca_pagou = bool(com_dado) and all(_sem_retorno(v, acao) for v in com_dado)
            veredito = 'ok'
            if don >= don_minimo and _sem_retorno(direto, acao):
                veredito = ('DON_SEM_RETORNO_PERSISTENTE' if nunca_pagou
                            else 'DON_SEM_RETORNO_DIRETO')
            linhas.append({
                'match_id': partida,
                'turno': d.get('turn'),
                'acao': acao,
                'carta': chosen.get('card_code'),
                'alvo': chosen.get('target_type'),
                'score': chosen.get('score'),
                'investimento_don': don,
                'retornos': retornos,
                'veredito': veredito,
            })

    return {
        'decisoes_main': len(decisoes),
        'analisadas': len(linhas),
        'sem_cobertura': sem_cobertura,
        'linhas': linhas,
        'don_minimo': don_minimo,
    }


def _fmt_retorno(r: dict | None) -> str:
    if r is None:
        return 'sem dado'
    return (f"dano={r['dano']:+d} board_rem={r['board_removido']:+d} "
            f"board_ganho={r['board_ganho']:+d} mao={r['mao_delta']:+d}")


def imprimir(rel: dict, top: int) -> None:
    print('== Consequencia por decisao individual ==')
    print(f"  {rel['analisadas']} de {rel['decisoes_main']} decisoes de main analisadas "
          f"({rel['sem_cobertura']} sem cobertura de estado suficiente)")
    if not rel['linhas']:
        print('  Nada a reportar -- sem decisoes com estado antes/depois neste log.')
        return

    total_don = sum(l['investimento_don'] for l in rel['linhas'])
    persistentes = [l for l in rel['linhas']
                    if l['veredito'] == 'DON_SEM_RETORNO_PERSISTENTE']
    so_direto = [l for l in rel['linhas'] if l['veredito'] == 'DON_SEM_RETORNO_DIRETO']
    don_persistente = sum(l['investimento_don'] for l in persistentes)
    print(f"  DON total comprometido: {total_don}")
    print(f"  DON que NUNCA pagou (zero em todo horizonte com dado): {don_persistente} "
          f"({(don_persistente / total_don * 100) if total_don else 0:.1f}%)")
    print(f"  DON com efeito direto zero mas que pagou depois: "
          f"{sum(l['investimento_don'] for l in so_direto)} "
          f"({len(so_direto)} decisao(oes) -- provavel preparacao legitima)")
    print()

    print(f"== [FORTE] DON >= {rel['don_minimo']} e retorno ZERO em TODOS os horizontes ==")
    print('   (o sinal que mais merece leitura manual. Ainda assim NAO e')
    print('    veredito: pressao legitima que o oponente respondeu com')
    print('    counter tambem cai aqui -- confira o combat log da jogada.)')
    if not persistentes:
        print('  Nenhuma -- bom sinal.')
    else:
        for l in sorted(persistentes, key=lambda x: -x['investimento_don'])[:top]:
            print(f"  turno {l['turno']:<3} {str(l['acao']):<11} {l['carta'] or '-':<10} "
                  f"alvo={str(l['alvo'] or '-'):<10} DON={l['investimento_don']:<3} "
                  f"score={l['score']}")
            for h in ('1', '3', '5', 'fim_do_turno'):
                rot = 'direto' if h == '1' else h
                print(f"      {rot:<13}: {_fmt_retorno(l['retornos'][h])}")
    print()

    if so_direto:
        print('== [FRACO] efeito direto zero, mas pagou num horizonte maior ==')
        print('   (tipicamente preparacao: anexar DON nao causa dano sozinho,')
        print('    habilita o ataque seguinte. Normalmente NAO e problema.)')
        for l in sorted(so_direto, key=lambda x: -x['investimento_don'])[:top]:
            print(f"  turno {l['turno']:<3} {str(l['acao']):<11} {l['carta'] or '-':<10} "
                  f"DON={l['investimento_don']:<3} | depois: "
                  f"{_fmt_retorno(l['retornos']['3'] or l['retornos']['fim_do_turno'])}")
        print()

    print('== Todas as decisoes, em ordem (investimento -> efeito DIRETO) ==')
    for l in rel['linhas'][:top * 3]:
        marca = ('!!' if l['veredito'] == 'DON_SEM_RETORNO_PERSISTENTE'
                 else ' ?' if l['veredito'] == 'DON_SEM_RETORNO_DIRETO' else '  ')
        print(f"  {marca} turno {l['turno']:<3} {str(l['acao']):<11} {l['carta'] or '-':<10} "
              f"DON={l['investimento_don']:<3} | {_fmt_retorno(l['retornos']['1'])}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--session', help='nome da sessao (decisions_<nome>.jsonl)')
    ap.add_argument('--file', help='caminho direto pro .jsonl')
    ap.add_argument('--don-minimo', type=int, default=3,
                    help='DON minimo pra marcar DON_SEM_RETORNO (default 3)')
    ap.add_argument('--top', type=int, default=10,
                    help='quantas decisoes suspeitas listar (default 10)')
    ap.add_argument('--json', dest='json_out',
                    help='salva o relatorio completo neste caminho .json')
    args = ap.parse_args()

    if args.file:
        path = args.file
    elif args.session:
        path = os.path.join(DECISIONS_DIR, f'decisions_{args.session}.jsonl')
    else:
        path = _latest_decisions_file()

    if not path or not os.path.exists(path):
        print(f'Log de decisoes nao encontrado: {path}')
        return 1

    print(f'Lendo {path}\n')
    rel = analisar(_load(path), don_minimo=args.don_minimo)
    imprimir(rel, top=args.top)

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(rel, f, indent=2, ensure_ascii=False)
        print(f'Relatorio completo salvo em {args.json_out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
