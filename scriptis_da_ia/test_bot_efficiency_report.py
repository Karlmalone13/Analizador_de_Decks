import json
import unittest
from pathlib import Path

import bot_efficiency_report as report
from optcg_engine.sim_bridge import action_to_trace


ROOT = Path(__file__).resolve().parent


class BotEfficiencyReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = json.loads(report.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        cls.results = {
            cohort["label"]: report.analyze_cohort(cohort, report.PARSED_ROOT, 100, 7)
            for cohort in manifest["cohorts"]
        }

    def metric(self, cohort, name):
        return self.results[cohort]["metrics"][name]["value"]

    def test_reproduces_historical_human_baseline(self):
        self.assertAlmostEqual(self.metric("human_before", "atk_por_turno"), 2.031, places=3)
        self.assertAlmostEqual(self.metric("human_before", "pct_atk_lider"), 81.538, places=3)
        self.assertAlmostEqual(self.metric("human_before", "dano_por_jogo"), 4.2, places=3)
        self.assertAlmostEqual(
            self.metric("human_before", "counters_arrancados_por_jogo"), 5.2, places=3
        )

    def test_reproduces_historical_bot_baseline(self):
        self.assertAlmostEqual(self.metric("bot_before", "atk_por_turno"), 0.88, places=3)
        self.assertAlmostEqual(self.metric("bot_before", "pct_atk_lider"), 42.424, places=3)
        self.assertAlmostEqual(self.metric("bot_before", "dano_por_jogo"), 1.333, places=3)
        self.assertAlmostEqual(self.metric("bot_before", "turnos_passivos_por_jogo"), 1.5, places=3)

    def test_unobservable_layers_are_not_fabricated(self):
        availability = self.results["bot_before"]["availability"]
        self.assertIsNone(availability["state_fidelity"])
        self.assertIsNone(availability["decision_quality"])
        self.assertIsNone(availability["execution_success"])

    def test_action_trace_marks_executor_eligibility(self):
        class FakeCard:
            code = "TEST-001"
            _deck_uid = 17

        traced = action_to_trace((12.5, "play", FakeCard(), None, None), {"play"}, set())
        self.assertEqual(traced["card_uid"], 17)
        self.assertTrue(traced["eligible"])

    def test_decision_log_joins_decision_and_execution(self):
        events = [
            {"event": "decision", "decision_id": "a",
             "chosen_action": {"score": 8},
             "scored_actions": [{"score": 10, "eligible": True}]},
            {"event": "execution", "decision_id": "a", "status": "sent",
             "state_after": {"turnNumber": 1}},
            {"event": "execution", "decision_id": "a", "status": "confirmed",
             "state_after": {"turnNumber": 1}},
            {"event": "decision", "decision_id": "b", "chosen_action": None,
             "scored_actions": []},
            {"event": "execution", "decision_id": "b", "status": "failed",
             "state_after": None},
        ]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        self.assertEqual(result["decisions"], 2)
        self.assertEqual(result["execution_success_pct"], 50.0)
        self.assertEqual(result["mean_immediate_score_gap"], 2.0)

    def test_multiphase_outcome_and_future_state_are_separate(self):
        def state(life, opp_life, hand=5, board=1):
            return {"bot": {"life": [0] * life, "hand": [0] * hand,
                            "board": [0] * board, "activeDon": 1, "restedDon": 1},
                    "opp": {"life": [0] * opp_life, "hand": [0] * 5,
                            "board": [], "activeDon": 1, "restedDon": 1}}

        events = [
            {"event": "decision", "decision_id": "m", "decision_kind": "mulligan",
             "state_before": {"hand": []}, "scored_actions": [], "chosen_action": {"type": "keep"}},
            {"event": "execution", "decision_id": "m", "status": "sent"},
            {"event": "decision", "decision_id": "a", "decision_kind": "main",
             "state_before": state(4, 4), "scored_actions": [], "chosen_action": {"type": "attack"}},
            {"event": "execution", "decision_id": "a", "status": "confirmed"},
            {"event": "decision", "decision_id": "t", "decision_kind": "target",
             "state_before": state(4, 3), "scored_actions": [], "chosen_action": {"type": "target_order"}},
            {"event": "outcome", "decision_id": "match", "result": "win"},
        ]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        self.assertEqual(result["decision_kinds"]["mulligan"]["pending"], 1)
        self.assertEqual(result["decision_kinds"]["main"]["confirmed"], 1)
        self.assertEqual(result["outcomes"]["win_rate_pct"], 100.0)
        self.assertEqual(
            result["future_state_delta_by_decisions"]["1"]["mean_delta"]["life_diff"], 1.0)

    def test_counterfactual_regret_uses_only_simulated_alternatives(self):
        chosen = {"type": "play", "card_uid": 7, "target_uid": 0}
        events = [{"event": "decision", "decision_id": "x", "decision_kind": "main",
                   "chosen_action": chosen, "scored_actions": [],
                   "search_values": [
                       {"action": chosen, "value": 3.0},
                       {"action": {"type": "attack", "card_uid": 9, "target_uid": 0},
                        "value": 5.5},
                   ]}]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        self.assertEqual(result["mean_counterfactual_regret"], 2.5)
        self.assertEqual(result["counterfactual_coverage_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
