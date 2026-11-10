import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "wolf_digest_backfill.py"


class DigestBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-backfill-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "workspace" / "mydesign" / "mydesign.gf22" / "mydesign.3"
        self.run_directory.mkdir(parents=True)
        self.environment = {"PYTHONPATH": str(REPO_ROOT / "src")}
        import os
        self.environment.update(os.environ)
        self.environment["PYTHONPATH"] = str(REPO_ROOT / "src")

    def tearDown(self):
        self.temporary.cleanup()

    def _run(self, *arguments):
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments],
            env=self.environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_identity_is_derived_from_the_run_directory_path(self):
        result = self._run(str(self.run_directory))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        digest = json.loads((self.run_directory / "wolf.digest.json").read_text(encoding="utf-8"))
        self.assertEqual(digest["design"], "mydesign")
        self.assertEqual(digest["process"], "gf22")
        self.assertEqual(digest["run_number"], "3")

    def test_output_is_counts_only_no_report_text_or_values(self):
        reports = self.run_directory / "reports" / "DRC"
        reports.mkdir(parents=True)
        (reports / "check.rpt").write_text(
            "net LIBRARYNET_1 at /asic/Library/secret\nTotal Violations: 2\n", encoding="utf-8",
        )
        result = self._run(str(self.run_directory))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("LIBRARYNET_1", result.stdout)
        self.assertNotIn("/asic/Library", result.stdout)
        self.assertNotIn("2", result.stdout.split("digest_bytes=")[0].split("drc_found=")[1])

    def test_a_run_directory_that_cannot_be_written_to_is_reported_and_does_not_stop_the_batch(self):
        # A plain file where a run directory is expected: mkdir(parents=True)
        # fails cleanly here, a real-world stand-in for "this one run can't
        # be backfilled" without needing real permission games.
        not_a_directory = self.root / "not_a_directory"
        not_a_directory.write_text("", encoding="utf-8")
        broken = not_a_directory / "sub" / "run.1"
        result = self._run(str(broken), str(self.run_directory))
        self.assertIn("FAILED", result.stdout)
        self.assertTrue((self.run_directory / "wolf.digest.json").is_file())

    def test_project_root_also_writes_the_shared_copy(self):
        project_root = self.root / "project"
        result = self._run(str(self.run_directory), "--project-root", str(project_root))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        shared = project_root / "shared" / "wolf-digests" / "mydesign.3.json"
        self.assertTrue(shared.is_file())


if __name__ == "__main__":
    unittest.main()
