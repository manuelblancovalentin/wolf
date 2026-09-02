import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from wolf.backend import UnknownBackendError, backend_names, get_backend


class BackendRegistryTests(unittest.TestCase):
    def test_builtin_registry_contains_cadence_flowtool(self):
        self.assertEqual(backend_names(), ("cadence-flowtool", "orfs"))
        backend = get_backend("cadence-flowtool")
        self.assertEqual(backend.name, "cadence-flowtool")
        self.assertEqual(backend.adapter_filename, "cadence-flowtool.sh")

    def test_unknown_backend_error_lists_available_backend(self):
        with self.assertRaisesRegex(
            UnknownBackendError,
            "unknown WOLF backend 'missing'.*cadence-flowtool",
        ):
            get_backend("missing")

    def test_cadence_validation_is_backend_local_and_mockable(self):
        with mock.patch(
            "wolf.backend.cadence_flowtool.shutil.which",
            side_effect=lambda name: "/mock/flowtool" if name == "flowtool" else None,
        ):
            checks = {item.name: item for item in get_backend("cadence-flowtool").validate()}
        self.assertTrue(checks["flowtool"].available)
        self.assertFalse(checks["python3"].available)


class ShellOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="wolf-backend-tests-")
        self.root = Path(self._temporary_directory.name)
        self.call_log = self.root / "calls"

    def tearDown(self):
        self._temporary_directory.cleanup()

    def run_fake_backend(self, *, fail_stage=""):
        script = r'''
WOLF_BIN="$1"
CALL_LOG="$2"
FAIL_STAGE="$3"
source "$WOLF_BIN/utils"
source "$WOLF_BIN/backend.sh"
BACKEND=fake

_wolf_backend_stages() {
    echo "stages" >> "$CALL_LOG"
    WOLF_BACKEND_STAGES=(a b c)
}

_wolf_backend_run_stage() {
    local stage="$1"
    shift
    printf 'run:%s:%s\n' "$stage" "$*" >> "$CALL_LOG"
    if [[ "$stage" == "$FAIL_STAGE" ]]; then
        return 19
    fi
}

_wolf_run_backend_stages b c "" passthrough "value with spaces"
'''
        environment = os.environ.copy()
        environment["HOME"] = str(self.root / "home")
        return subprocess.run(
            [
                "bash",
                "--noprofile",
                "--norc",
                "-c",
                script,
                "wolf-fake-backend",
                str(REPO_ROOT / "bin"),
                str(self.call_log),
                fail_stage,
            ],
            cwd=self.root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_generic_stage_range_delegates_discovery_and_execution(self):
        result = self.run_fake_backend()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            self.call_log.read_text().splitlines(),
            [
                "stages",
                "run:b:passthrough value with spaces",
                "run:c:passthrough value with spaces",
            ],
        )

    def test_backend_failure_propagates_and_stops_later_stages(self):
        result = self.run_fake_backend(fail_stage="b")
        self.assertEqual(result.returncode, 19, msg=result.stderr)
        self.assertEqual(
            self.call_log.read_text().splitlines(),
            ["stages", "run:b:passthrough value with spaces"],
        )


if __name__ == "__main__":
    unittest.main()
