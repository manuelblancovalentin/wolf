import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "tests" / "integration" / "check_orfs_ibex.py"
HARNESS = REPO_ROOT / "tests" / "integration" / "run_orfs_ibex"


class OrfsIntegrationHarnessTests(unittest.TestCase):
    def run_checker(self, metrics, setup_violations=0, hold_violations=0):
        with tempfile.TemporaryDirectory(prefix="wolf-orfs-metrics-") as temporary:
            reports = Path(temporary) / "reports"
            reports.mkdir()
            (reports / "metadata.json").write_text(json.dumps(metrics), encoding="utf-8")
            (reports / "6_finish.rpt").write_text(
                "\n".join(
                    (
                        "finish setup_violation_count",
                        f"setup violation count {setup_violations}",
                        "finish hold_violation_count",
                        f"hold violation count {hold_violations}",
                    )
                ),
                encoding="utf-8",
            )
            return subprocess.run(
                [sys.executable, str(CHECKER), str(reports)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    def test_checker_accepts_timing_and_drc_clean_metrics(self):
        result = self.run_checker(
            {
                "finish__timing__setup__ws": 14.7,
                "detailedroute__route__drc_errors": 0,
            }
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("14.700 ps", result.stdout)

    def test_checker_rejects_nonzero_drc_errors(self):
        result = self.run_checker(
            {
                "finish__timing__setup__ws": 14.7,
                "detailedroute__route__drc_errors": 1,
            }
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("DRC errors are nonzero", result.stderr)

    def test_checker_rejects_nonzero_timing_violations(self):
        result = self.run_checker(
            {
                "finish__timing__setup__ws": 14.7,
                "detailedroute__route__drc_errors": 0,
            },
            setup_violations=1,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("setup violations are nonzero", result.stderr)

    def test_harness_uses_derived_1050_ps_sdc_and_official_metadata_target(self):
        harness = HARNESS.read_text(encoding="utf-8")
        self.assertIn("constraint.wolf_ibex_asap7_1050ps.sdc", harness)
        self.assertIn("prepare_orfs_ibex_sdc.py", harness)
        self.assertIn("metadata-generate", harness)
        self.assertIn('"$ORFS_REPORTS_DIR"', harness)
