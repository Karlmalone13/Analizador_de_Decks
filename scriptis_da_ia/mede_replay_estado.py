"""Bloco 958 -- ONDE o motor e o OPTCGSim se separam, acao por acao.

Mesmo estado => mesma decisao (verificado: Otama x passar deu os mesmos
valores do Q ao vivo e no motor). Entao a diferenca motor x jogo real
(Mihawk 76% x 0/20) vem de como o ESTADO EVOLUI. Para cada par de decisoes
`main` seguidas do MESMO lado no MESMO turno de uma partida real:
  1. reconstroi o estado como o servidor (`_dto_to_gs` + mundo);
  2. confere que o motor escolhe a mesma acao que o bot escolheu ao vivo;
  3. aplica a acao no motor (`OPTCGMatch._apply_action`, a do auto-jogo);
  4. compara com o estado que o JOGO mandou na decisao seguinte.
So play/activate/attach_don (ataque envolve a defesa do outro lado).
Diferenca esperada e ignorada: carta comprada vira UNKNOWN no motor (o deck
ao vivo e oculto).
"""
import collections, glob, json, os, sys
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, '..', 'BOT', 'engine_server'))


def _foto(g):
    def ch(c):
        return (c.code, bool(c.rested), int(getattr(c, 'don_attached', 0)),
                int(c.effective_power(your_turn=True)))
    return {
        'mao': collections.Counter(c.code for c in g.hand if c.code != 'UNKNOWN-000'),
        'mao_n': len(g.hand),
        'campo': sorted(ch(c) for c in g.field_chars),
        'lider': ch(g.leader),
        'stage': getattr(g.field_stage, 'code', None),
        'don_ativo': g.don_available, 'don_restado': getattr(g, 'don_rested', 0),
        'vida_n': g.life_count(),
        'trash': collections.Counter(c.code for c in g.trash),
    }


def _difs(a, b):
    out = []
    for k in a:
        if a[k] != b[k]:
            if k == 'mao':
                falta, sobra = a[k] - b[k], b[k] - a[k]
                out.append(f'mao: motor tem a mais {dict(falta)}, jogo tem a mais {dict(sobra)}')
            elif k == 'trash':
                out.append(f'trash: motor {dict(a[k] - b[k])} | jogo {dict(b[k] - a[k])}')
            else:
                out.append(f'{k}: motor {a[k]} | jogo {b[k]}')
    return out


def main(receipts):
    import server
    from optcg_engine.decision_engine import EffectExecutor, DecisionEngine
    br, mt = server._get_bridge(), server._get_match()
    tot = collections.Counter(); por_carta = collections.defaultdict(list)
    for rp in receipts:
        r = json.load(open(rp, encoding='utf-8'))
        mid = r.get('match_id')
        if not mid or not r.get('decision_log'):
            continue
        evs = []
        with open(r['decision_log'], encoding='utf-8', errors='ignore') as f:
            for l in f:
                if mid in l[:400] and '"decision_kind":"main"' in l:
                    d = json.loads(l)
                    if d.get('event') == 'decision' and d.get('state_before'):
                        evs.append(d)
        for d, d2 in zip(evs, evs[1:]):
            s1, s2 = d['state_before'], d2['state_before']
            if (s1['bot']['leader']['code'] != s2['bot']['leader']['code']
                    or s1['turnNumber'] != s2['turnNumber']):
                continue
            ca = d.get('chosen_action') or {}
            if ca.get('type') not in ('play', 'activate', 'attach_don'):
                continue
            st1, st2 = server.GameStateDto(**s1), server.GameStateDto(**s2)
            gs = server._dto_to_gs(st1.bot, st1.turnNumber)
            op = server._dto_to_gs(st1.opp, st1.turnNumber, hide_hidden=True)
            br.aplica_mundo_completo(gs, op, st1.bot, st1.opp, st1.combatLog, st1.botLogName)
            gs.is_active_turn, op.is_active_turn = True, False
            act = br.choose_action(gs, op, mt, timeout=5.0,
                                   allowed_types={"play", "attack", "attach_don", "activate"})
            cod = getattr(act[2], 'code', None) if act and len(act) > 2 else None
            if not act or act[1] != ca.get('type') or cod != ca.get('card_code'):
                tot['decisao_diferente'] += 1
                continue
            try:
                mt._apply_action(act, gs, op, EffectExecutor(gs, op), DecisionEngine(gs, op))
            except Exception as e:
                tot['erro_ao_aplicar'] += 1; continue
            g2 = server._dto_to_gs(st2.bot, st2.turnNumber)
            o2 = server._dto_to_gs(st2.opp, st2.turnNumber, hide_hidden=True)
            dm, do = _difs(_foto(gs), _foto(g2)), _difs(_foto(op), _foto(o2))
            chave = f"{ca.get('type')} {ca.get('card_code')}"
            tot['comparadas'] += 1
            if dm or do:
                tot['divergiu'] += 1
                por_carta[chave].append((r.get('bank_entry_id'), s1['turnNumber'],
                                         dm, [f'OPONENTE {x}' for x in do]))
    print(dict(tot))
    for k, v in sorted(por_carta.items(), key=lambda kv: -len(kv[1])):
        print(f'\n== {k}: {len(v)} divergencia(s)')
        for pid, t, dm, do in v[:3]:
            print(f'   {pid} turno {t}')
            for x in dm + do:
                print(f'      {x}')


if __name__ == '__main__':
    pad = sys.argv[1] if len(sys.argv) > 1 else 'metrics/live_runs/receipt_2026-10-10T1[67]*.json'
    main(sorted(glob.glob(pad)))
