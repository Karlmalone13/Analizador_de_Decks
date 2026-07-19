import json
import unittest
from unittest.mock import patch
from pathlib import Path

import bot_efficiency_report as report
from compare_bot_reports import compare_reports
from collect_latest_match import _validate_bank_entry
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
             "commit": "abc", "latency_ms": 120.0,
             "chosen_action": {"score": 8},
             "scored_actions": [{"score": 10, "eligible": True}]},
            {"event": "execution", "decision_id": "a", "status": "sent",
             "state_after": {"turnNumber": 1}},
            {"event": "execution", "decision_id": "a", "status": "confirmed",
             "state_after": {"turnNumber": 1}},
            {"event": "decision", "decision_id": "b", "chosen_action": None,
             "commit": "abc", "latency_ms": 80.0, "timed_out": True,
             "scored_actions": []},
            {"event": "execution", "decision_id": "b", "status": "failed",
             "state_after": None},
        ]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        self.assertEqual(result["decisions"], 2)
        self.assertEqual(result["execution_success_pct"], 50.0)
        self.assertEqual(result["mean_immediate_score_gap"], 2.0)
        self.assertEqual(result["latency_ms"]["mean"], 100.0)
        self.assertEqual(result["latency_ms"]["timeout_count"], 1)
        self.assertFalse(result["commit_consistency"]["mixed"])
        self.assertIn("decision_timeouts", {a["code"] for a in result["alerts"]})

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

    def test_report_comparison_separates_improvement_and_regression(self):
        def wrapped(execution, regret, latency):
            return {"manifest": "same", "bootstrap_seed": 7,
                    "decision_logs": [{"execution_success_pct": execution,
                                       "mean_counterfactual_regret": regret,
                                       "latency_ms": {"p95": latency}}]}
        result = compare_reports(wrapped(90, 3, 200), wrapped(97, 1, 250))
        self.assertEqual(result["metrics"]["execution_success_pct"]["verdict"], "improved")
        self.assertEqual(result["metrics"]["mean_counterfactual_regret"]["verdict"], "improved")
        self.assertEqual(result["metrics"]["latency_p95"]["verdict"], "regressed")
        self.assertIn("latency_p95", result["regressions"])

    def test_semantic_confirmation_detects_false_positive_state_change(self):
        before = {"turnNumber": 2, "bot": {"hand": [], "board": [
                    {"deckUniqueId": 7, "rested": False, "donAttached": 0}]},
                  "opp": {"hand": [], "board": []}}
        after = {"turnNumber": 2, "bot": {"hand": [], "board": [
                    {"deckUniqueId": 7, "rested": False, "donAttached": 0}]},
                 "opp": {"hand": [1], "board": []}}
        events = [
            {"event": "decision", "decision_id": "atk", "decision_kind": "main",
             "state_before": before, "response": {"type": "attack", "cardId": 7},
             "scored_actions": [], "chosen_action": {"type": "attack"}},
            {"event": "execution", "decision_id": "atk", "status": "confirmed",
             "state_after": after},
        ]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        self.assertEqual(result["transition_semantics_summary"]["failed"], 1)
        self.assertIn("semantic_transition_failed", {a["code"] for a in result["alerts"]})

    def test_bot_confusion_aggregates_all_four_signals(self):
        events = [
            {"event": "decision", "decision_id": "a", "decision_kind": "main",
             "selection": "no_eligible_action", "scored_actions": [], "chosen_action": None},
            {"event": "decision_error", "decision_id": "err1", "match_id": "m1",
             "turn": 3, "error": "boom"},
            {"event": "client_timeout", "decision_id": "ct1", "match_id": "m1",
             "endpoint": "/decide", "turn": 4},
            {"event": "decision", "decision_id": "b", "decision_kind": "main",
             "scored_actions": [], "chosen_action": {"type": "attack"}},
            {"event": "execution", "decision_id": "b", "status": "failed",
             "error": "acao repetida 3x sem mudanca de estado"},
        ]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        self.assertEqual(result["bot_confusion"], {
            "total": 4,
            "no_eligible_action": 1,
            "engine_exceptions": 1,
            "client_timeouts": 1,
            "stuck_executions": 1,
        })
        self.assertIn("bot_confusion", {a["code"] for a in result["alerts"]})

    def test_bot_confusion_silent_when_no_signal_present(self):
        events = [
            {"event": "decision", "decision_id": "a", "decision_kind": "main",
             "selection": "immediate_score", "scored_actions": [], "chosen_action": {"type": "play"}},
            {"event": "execution", "decision_id": "a", "status": "confirmed"},
        ]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        self.assertEqual(result["bot_confusion"]["total"], 0)
        self.assertNotIn("bot_confusion", {a["code"] for a in result["alerts"]})

    def test_lethal_certified_correlates_with_match_outcome(self):
        events = [
            # match m1: lethal certificado no turno 5, fecha (win) no turno 6 -- 1 turno depois
            {"event": "decision", "decision_id": "d1", "decision_kind": "main",
             "match_id": "m1", "turn": 5, "can_lethal": True,
             "scored_actions": [], "chosen_action": {"type": "attack"}},
            {"event": "outcome", "decision_id": "o1", "match_id": "m1", "result": "win",
             "state_final": {"turnNumber": 6}},
            # match m2: lethal certificado no turno 2, mas a partida termina em derrota
            {"event": "decision", "decision_id": "d2", "decision_kind": "main",
             "match_id": "m2", "turn": 2, "can_lethal": True,
             "scored_actions": [], "chosen_action": {"type": "attack"}},
            {"event": "outcome", "decision_id": "o2", "match_id": "m2", "result": "loss",
             "state_final": {"turnNumber": 9}},
        ]
        result = report.analyze_decision_events(json.dumps(e) for e in events)
        summary = result["lethal_certified_summary"]
        self.assertEqual(summary["matches_with_lethal_certified"], 2)
        self.assertEqual(summary["matches_closed_after_lethal"], 1)
        self.assertEqual(summary["matches_not_closed_after_lethal"], 1)
        self.assertEqual(summary["mean_turns_to_close"], 1.0)

    def test_bank_confirmation_requires_canonical_name_and_artifacts(self):
        log = Path("2026-07-18T12.00.00.log")
        entry = {"id": log.stem,
                 "log_file": f"raw/Imu-B_x_Teach-BY_{log.stem}.log",
                 "parsed_file": f"parsed/Imu-B_x_Teach-BY_{log.stem}.json",
                 "deck_files": {"bot": f"decks/Imu-B_{log.stem}.json"}}
        with patch.object(Path, "is_file", return_value=True):
            found, stem = _validate_bank_entry(log, [entry], Path("db"))
        self.assertIs(found, entry)
        self.assertEqual(stem, f"Imu-B_x_Teach-BY_{log.stem}")
        bad = {**entry, "log_file": f"raw/{log.stem}.log"}
        with patch.object(Path, "is_file", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "nome fora do padrao"):
                _validate_bank_entry(log, [bad], Path("db"))


if __name__ == "__main__":
    unittest.main()
