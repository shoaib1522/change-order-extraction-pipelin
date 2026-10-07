from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))

from scripts.evaluate import run_evaluation


class EvaluationTests(unittest.TestCase):
    def test_labeled_benchmark_has_no_regressions(self) -> None:
        report = run_evaluation()
        self.assertEqual(4, report["cases"])
        self.assertEqual(31, report["field_checks"])
        self.assertEqual(1.0, report["exact_match_rate"], report["failures"])
        self.assertEqual([], report["failures"])


if __name__ == "__main__":
    unittest.main()
