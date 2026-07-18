import json
import unittest
from pathlib import Path

import bot_efficiency_report as report


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


if __name__ == "__main__":
    unittest.main()
