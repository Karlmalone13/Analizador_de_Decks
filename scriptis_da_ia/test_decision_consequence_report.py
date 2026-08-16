"""
Testes do `decision_consequence_report.py` (bloco 548).

Cobrem os 3 erros REAIS que a validacao contra a partida ao vivo de
15/08 revelou antes do commit -- todos achados rodando a ferramenta
contra o log de verdade e conferindo contra o log do plugin, nao
inventados depois:

1. `attach_don` contava o mesmo DON duas vezes (don_cost + donToAttach).
2. Ataque era creditado por `board_ganho`/`mao_delta` que vieram de OUTRA
   decisao do mesmo turno -- mascarava justamente o all-in que falhou.
3. Veredito unico nao separava "preparacao que pagou depois" de "nunca
   pagou em horizonte nenhum".
"""
import unittest

import decision_consequence_report as rep


def _estado(opp_life=4, opp_board=0, bot_board=0, bot_hand=5, turn=1):
    return {
        'turnNumber': turn,
        'bot': {'life': [{}] * 3, 'board': [{}] * bot_board,
                'hand': [{}] * bot_hand},
        'opp': {'life': [{}] * opp_life, 'board': [{}] * opp_board,
                'hand': []},
    }


def _decisao(did, turn, tipo, card='X', don_cost=None, don_attach=0,
             state_before=None, card_uid=1, target_uid=0):
    chosen = {'type': tipo, 'card_code': card, 'card_uid': card_uid,
              'target_uid': target_uid, 'target_type': 'leader'}
    scored = [{'type': tipo, 'card_uid': card_uid, 'target_uid': target_uid,
               'score_components': ({'don_cost': don_cost}
                                    if don_cost is not None else {})}]
    return {'event': 'decision', 'decision_id': did, 'decision_kind': 'main',
            'match_id': 'm1', 'turn': turn, 'chosen_action': chosen,
            'scored_actions': scored,
            'response': {'type': tipo, 'donToAttach': don_attach},
            'state_before': state_before or _estado(turn=turn)}


def _execucao(did, state_after):
    return {'event': 'execution', 'decision_id': did, 'status': 'confirmed',
            'state_after': state_after}


class DecisionConsequenceTests(unittest.TestCase):

    def test_attach_don_nao_conta_o_mesmo_don_duas_vezes(self):
        # Achado real 15/08: don_cost=3 + donToAttach=3 descrevem os MESMOS
        # 3 DON (o log do plugin registrou "attach_don: 3/3 DON"), mas o
        # investimento saia 6 -- inflando o percentual de DON desperdicado.
        d = _decisao('a', 1, 'attach_don', don_cost=3, don_attach=3)
        self.assertEqual(rep._investimento_don(d), 3)

    def test_play_com_custo_soma_normalmente(self):
        # Fora de attach_don as parcelas sao gastos distintos e SOMAM --
        # o fix acima nao pode virar um "sempre max()".
        d = _decisao('a', 1, 'play', don_cost=4, don_attach=2)
        self.assertEqual(rep._investimento_don(d), 6)

    def test_ataque_nao_e_creditado_por_board_ganho_de_outra_decisao(self):
        # O caso concreto reclamado pelo usuario: ataque com 5 DON que nao
        # causou dano nenhum. Se `board_ganho` (que veio de jogar outra
        # carta depois) contasse como retorno do ataque, o all-in falho
        # seria classificado como "pagou depois" e sumiria do relatorio.
        retorno = {'dano': 0, 'board_removido': 0, 'board_ganho': 1, 'mao_delta': 2}
        self.assertTrue(rep._sem_retorno(retorno, 'attack'))
        # Para um `play`, desenvolver o board E o retorno esperado.
        self.assertFalse(rep._sem_retorno(retorno, 'play'))

    def test_ataque_que_conectou_conta_como_retorno(self):
        retorno = {'dano': 1, 'board_removido': 0, 'board_ganho': 0, 'mao_delta': 0}
        self.assertFalse(rep._sem_retorno(retorno, 'attack'))

    def test_veredito_persistente_quando_nunca_pagou(self):
        # Ataque de 5 DON, dano zero na propria decisao e no horizonte
        # seguinte -> PERSISTENTE (sinal forte).
        eventos = [
            _decisao('a', 1, 'attack', don_attach=5, state_before=_estado()),
            _execucao('a', _estado()),
            _decisao('b', 1, 'attack', don_attach=0, state_before=_estado()),
            _execucao('b', _estado()),
        ]
        rel = rep.analisar(eventos, don_minimo=3)
        primeira = rel['linhas'][0]
        self.assertEqual(primeira['investimento_don'], 5)
        self.assertEqual(primeira['veredito'], 'DON_SEM_RETORNO_PERSISTENTE')

    def test_veredito_fraco_quando_efeito_direto_zero_mas_pagou_depois(self):
        # attach_don nao causa dano sozinho (efeito direto zero), mas
        # habilita o ataque seguinte que conecta -> sinal FRACO, nao forte.
        eventos = [
            _decisao('a', 1, 'attach_don', don_cost=3, don_attach=3,
                     state_before=_estado(opp_life=4)),
            _execucao('a', _estado(opp_life=4)),
            _decisao('b', 1, 'attack', state_before=_estado(opp_life=4)),
            _execucao('b', _estado(opp_life=3)),   # dano conectou
        ]
        rel = rep.analisar(eventos, don_minimo=3)
        self.assertEqual(rel['linhas'][0]['veredito'], 'DON_SEM_RETORNO_DIRETO')

    def test_decisao_barata_nunca_vira_suspeita(self):
        # don_minimo protege contra ruido: jogada de 1 DON sem retorno
        # direto e normal, nao merece entrar no relatorio de suspeitas.
        eventos = [
            _decisao('a', 1, 'attack', don_attach=1, state_before=_estado()),
            _execucao('a', _estado()),
        ]
        rel = rep.analisar(eventos, don_minimo=3)
        self.assertEqual(rel['linhas'][0]['veredito'], 'ok')

    def test_decisao_sem_state_before_nao_quebra_e_e_contabilizada(self):
        eventos = [
            {'event': 'decision', 'decision_id': 'a', 'decision_kind': 'main',
             'match_id': 'm1', 'turn': 1, 'chosen_action': {'type': 'play'},
             'scored_actions': [], 'response': {}},
        ]
        rel = rep.analisar(eventos)
        self.assertEqual(rel['analisadas'], 0)
        self.assertEqual(rel['sem_cobertura'], 1)


if __name__ == '__main__':
    unittest.main()
