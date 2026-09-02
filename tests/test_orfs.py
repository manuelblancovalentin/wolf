import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
BASH = shutil.which("bash") or "/bin/bash"

import sys

sys.path.insert(0, str(SOURCE_ROOT))

from wolf.backend import get_backend
from wolf.backend.orfs import ORFS_STAGES


class OrfsPythonBackendTests(unittest.TestCase):
    def test_registry_exposes_orfs_and_native_stages(self):
        backend = get_backend("orfs")
        self.assertEqual(backend.name, "orfs")
        self.assertEqual(backend.stages(), ORFS_STAGES)

    def test_missing_orfs_root_is_reported_clearly(self):
        checks = {item.name: item for item in get_backend("orfs").validate({})}
        self.assertFalse(checks["ORFS_ROOT"].available)
        self.assertEqual(checks["ORFS_ROOT"].detail, "not configured")

    def test_invalid_orfs_root_is_reported_clearly(self):
        checks = {
            item.name: item
            for item in get_backend("orfs").validate({"ORFS_ROOT": "/missing/orfs"})
        }
        self.assertFalse(checks["ORFS_ROOT"].available)
        self.assertIn("not a directory", checks["ORFS_ROOT"].detail)

    def test_validation_does_not_require_host_openroad_tools(self):
        with tempfile.TemporaryDirectory(prefix="wolf-orfs-python-") as temporary:
            root = Path(temporary)
            (root / "Makefile").write_text("", encoding="utf-8")
            (root / "util").mkdir()
            (root / "util" / "docker_shell").write_text("", encoding="utf-8")
            with mock.patch(
                "wolf.backend.orfs.shutil.which",
                side_effect=lambda name: "/mock/docker" if name == "docker" else None,
            ):
                checks = {
                    item.name: item
                    for item in get_backend("orfs").validate({"ORFS_ROOT": str(root)})
                }
        self.assertTrue(checks["container runtime"].available)
        self.assertNotIn("yosys", {name.lower() for name in checks})
        self.assertNotIn("openroad", {name.lower() for name in checks})


class OrfsShellBackendTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="wolf-orfs-shell-")
        self.root = Path(self._temporary_directory.name)
        self.flow_root = self.root / "flow"
        self.flow_root.mkdir()
        (self.flow_root / "Makefile").write_text("", encoding="utf-8")
        config_dir = self.flow_root / "designs" / "asap7" / "ibex"
        config_dir.mkdir(parents=True)
        self.config = config_dir / "config.mk"
        self.config.write_text("DESIGN_NAME := ibex\n", encoding="utf-8")
        self.sdc = config_dir / "constraint.sdc"
        self.sdc.write_text("create_clock -period 1.050\n", encoding="utf-8")
        util_dir = self.flow_root / "util"
        util_dir.mkdir()
        self.call_log = self.root / "docker-shell-calls"
        self._write_executable(
            util_dir / "docker_shell",
            """#!/bin/sh
printf '%s\\n' "$@" >> "$ORFS_CALL_LOG"
if [ "${ORFS_FAIL_TARGET:-}" = "${!#}" ]; then
    exit 27
fi
""".replace("${!#}", "$(eval \"printf %s \\\"\\${$#}\\\"\")"),
        )
        self.stub_bin = self.root / "bin"
        self.stub_bin.mkdir()
        self._write_executable(self.stub_bin / "docker", "#!/bin/sh\nexit 0\n")
        self.runtime_missing_bin = self.root / "no-runtime-bin"
        self.runtime_missing_bin.mkdir()
        for command in ("sed", "tr", "id", "uname"):
            source = shutil.which(command)
            if source:
                (self.runtime_missing_bin / command).symlink_to(source)

    def tearDown(self):
        self._temporary_directory.cleanup()

    @staticmethod
    def _write_executable(path, content):
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def shell(self, body, *, extra_env=None):
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(self.stub_bin) + os.pathsep + environment.get("PATH", ""),
                "ORFS_ROOT": str(self.flow_root),
                "ORFS_DESIGN_CONFIG": "designs/asap7/ibex/config.mk",
                "ORFS_SDC_FILE": "designs/asap7/ibex/constraint.sdc",
                "ORFS_FLOW_VARIANT": "wolf-test",
                "ORFS_CALL_LOG": str(self.call_log),
                "ORFS_CONTAINER_RUNTIME": "docker",
                "WOLF_HOME": str(self.root / "wolf-home"),
                "WOLF_BIN": str(REPO_ROOT / "bin"),
                "SCRIPTS_DIR": str(self.root / "snapshot"),
            }
        )
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", textwrap.dedent(body)],
            cwd=self.root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def prepare_script(self):
        return """
            source "$WOLF_BIN/utils"
            source "$WOLF_BIN/backend.sh"
            source "$WOLF_BIN/container_executor.sh"
            _wolf_load_backend orfs
            _wolf_backend_validate
            mkdir -p "$SCRIPTS_DIR"
            _wolf_backend_plan
            _wolf_backend_prepare
        """

    def test_missing_root_fails_before_execution(self):
        result = self.shell(
            """
            source "$WOLF_BIN/utils"
            source "$WOLF_BIN/backend.sh"
            source "$WOLF_BIN/container_executor.sh"
            _wolf_load_backend orfs
            _wolf_backend_validate
            """,
            extra_env={"ORFS_ROOT": ""},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ORFS_ROOT", result.stdout + result.stderr)

    def test_invalid_checkout_fails_clearly(self):
        invalid = self.root / "not-orfs"
        invalid.mkdir()
        result = self.shell(
            """
            source "$WOLF_BIN/utils"
            source "$WOLF_BIN/backend.sh"
            source "$WOLF_BIN/container_executor.sh"
            _wolf_load_backend orfs
            _wolf_backend_validate
            """,
            extra_env={"ORFS_ROOT": str(invalid)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing Makefile", result.stdout + result.stderr)

    def test_missing_container_runtime_fails_clearly(self):
        result = self.shell(
            """
            source "$WOLF_BIN/utils"
            source "$WOLF_BIN/backend.sh"
            source "$WOLF_BIN/container_executor.sh"
            _wolf_load_backend orfs
            _wolf_backend_validate
            """,
            extra_env={
                "PATH": str(self.runtime_missing_bin),
                "ORFS_CONTAINER_RUNTIME": "docker",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("container runtime is unavailable", result.stdout + result.stderr)

    def test_stage_list_and_full_command_construction(self):
        result = self.shell(
            self.prepare_script()
            + """
            _wolf_backend_stages
            printf 'stages:%s\\n' "${WOLF_BACKEND_STAGES[*]}"
            for stage in "${WOLF_BACKEND_STAGES[@]}"; do
                _wolf_backend_run_stage "$stage"
            done
            """
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("stages:synth floorplan place cts route finish", result.stdout)
        calls = self.call_log.read_text(encoding="utf-8").splitlines()
        targets = [value for value in calls if value in ORFS_STAGES]
        self.assertEqual(targets, list(ORFS_STAGES))
        self.assertIn("DESIGN_CONFIG=/work/designs/asap7/ibex/config.mk", calls)
        self.assertIn("SDC_FILE=/work/designs/asap7/ibex/constraint.sdc", calls)
        self.assertIn("FLOW_VARIANT=wolf-test", calls)

    def test_passthrough_make_variables_preserve_empty_and_spaced_values(self):
        result = self.shell(
            self.prepare_script()
            + """
            _wolf_backend_run_stage synth SWAP_ARITH_OPERATORS= 'EXTRA_SETTING=value with spaces'
            """
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = self.call_log.read_text(encoding="utf-8").splitlines()
        self.assertIn("SWAP_ARITH_OPERATORS=", calls)
        self.assertIn("EXTRA_SETTING=value with spaces", calls)

    def test_generic_range_stops_after_orfs_failure(self):
        result = self.shell(
            self.prepare_script()
            + """
            _wolf_run_backend_stages place route ''
            """,
            extra_env={"ORFS_FAIL_TARGET": "cts"},
        )
        self.assertEqual(result.returncode, 27, msg=result.stderr)
        calls = self.call_log.read_text(encoding="utf-8").splitlines()
        targets = [value for value in calls if value in ORFS_STAGES]
        self.assertEqual(targets, ["place", "cts"])


if __name__ == "__main__":
    unittest.main()
