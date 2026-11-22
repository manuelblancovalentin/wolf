import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from wolf.process_watch import run_is_alive, run_processes


class RunProcessesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-process-watch-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_no_process_in_an_empty_run_directory(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        self.assertEqual(run_processes(run_directory), ())
        self.assertFalse(run_is_alive(run_directory))

    def test_a_real_process_whose_cwd_is_the_run_directory_is_found(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        process = subprocess.Popen(["sleep", "5"], cwd=str(run_directory))
        try:
            deadline = time.time() + 2
            found = ()
            while time.time() < deadline:
                found = run_processes(run_directory)
                if found:
                    break
                time.sleep(0.05)
            self.assertEqual({p.pid for p in found}, {process.pid})
            self.assertTrue(run_is_alive(run_directory))
            self.assertFalse(found[0].orphaned)
            self.assertIn("sleep", found[0].command)
            self.assertGreater(found[0].rss_gib, 0)
        finally:
            process.terminate()
            process.wait()

    def test_a_process_in_a_subdirectory_of_the_run_is_still_found(self):
        run_directory = self.root / "run"
        nested = run_directory / "backend" / "cadence-genus"
        nested.mkdir(parents=True)
        process = subprocess.Popen(["sleep", "5"], cwd=str(nested))
        try:
            deadline = time.time() + 2
            found = ()
            while time.time() < deadline:
                found = run_processes(run_directory)
                if found:
                    break
                time.sleep(0.05)
            self.assertEqual({p.pid for p in found}, {process.pid})
        finally:
            process.terminate()
            process.wait()

    def test_a_process_outside_the_run_directory_is_not_found(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        process = subprocess.Popen(["sleep", "5"], cwd=str(elsewhere))
        try:
            time.sleep(0.2)
            self.assertEqual(run_processes(run_directory), ())
        finally:
            process.terminate()
            process.wait()

    def test_a_process_still_working_in_a_deleted_run_directory_is_flagged_orphaned(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        process = subprocess.Popen(["sleep", "5"], cwd=str(run_directory))
        try:
            deadline = time.time() + 2
            while time.time() < deadline and not run_processes(run_directory):
                time.sleep(0.05)
            os.rmdir(run_directory)
            found = run_processes(run_directory)
            self.assertEqual({p.pid for p in found}, {process.pid})
            self.assertTrue(found[0].orphaned)
        finally:
            process.terminate()
            process.wait()

    def test_a_finished_process_is_no_longer_found(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        process = subprocess.Popen(["true"], cwd=str(run_directory))
        process.wait()
        self.assertEqual(run_processes(run_directory), ())
        self.assertFalse(run_is_alive(run_directory))


if __name__ == "__main__":
    unittest.main()
