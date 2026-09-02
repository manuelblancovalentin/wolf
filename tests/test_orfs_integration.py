import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "tests" / "integration" / "check_orfs_ibex.py"


class OrfsIntegrationHarnessTests(unittest.TestCase):
    def run_checker(self, metrics):
        with tempfile.TemporaryDirectory(prefix="wolf-orfs-metrics-") as temporary:
            results = Path(temporary) / "results"
            results.mkdir()
            (results / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CHECKER), str(results)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    def test_checker_accepts_timing_and_drc_clean_metrics(self):
        result = self.run_checker(
            {
                "finish__timing__setup__violating_paths": 0,
                "finish__timing__hold__violating_paths": 0,
                "finish__timing__setup__ws": 0.0147,
                "detailedroute__route__drc_errors": 0,
            }
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("14.700 ps", result.stdout)

    def test_checker_rejects_nonzero_drc_errors(self):
        result = self.run_checker(
            {
                "finish__timing__setup__violating_paths": 0,
                "finish__timing__hold__violating_paths": 0,
                "finish__timing__setup__ws": 0.0147,
                "detailedroute__route__drc_errors": 1,
            }
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("DRC errors are nonzero", result.stderr)
