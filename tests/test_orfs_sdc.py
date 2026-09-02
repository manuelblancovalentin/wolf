from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SDC = REPO_ROOT / "tests" / "integration" / "prepare_orfs_ibex_sdc.py"


class OrfsGoldenSdcTests(unittest.TestCase):
    def prepare(self, source: Path, target: Path):
        return subprocess.run(
            [sys.executable, str(PREPARE_SDC), str(source), str(target)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_creates_namespaced_1050_ps_sdc_without_changing_stock_sdc(self):
        with tempfile.TemporaryDirectory(prefix="wolf-orfs-sdc-") as temporary:
            root = Path(temporary)
            source = root / "constraint.sdc"
            target = root / "constraint.wolf_ibex_asap7_1050ps.sdc"
            source.write_text("set clk_period 1000\n", encoding="utf-8")
            result = self.prepare(source, target)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(source.read_text(encoding="utf-8"), "set clk_period 1000\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "set clk_period 1050\n")

    def test_refuses_to_overwrite_wrong_existing_namespaced_sdc(self):
        with tempfile.TemporaryDirectory(prefix="wolf-orfs-sdc-") as temporary:
            root = Path(temporary)
            source = root / "constraint.sdc"
            target = root / "constraint.wolf_ibex_asap7_1050ps.sdc"
            source.write_text("set clk_period 1000\n", encoding="utf-8")
            target.write_text("set clk_period 1000\n", encoding="utf-8")
            result = self.prepare(source, target)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not contain", result.stderr)
