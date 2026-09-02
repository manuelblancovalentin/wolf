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
from wolf.backend.orfs import ORFS_STAGES, RuntimeDiagnostic
from wolf.commands import run as run_command
from wolf.context import ResolvedContext
from wolf.package import InstalledPackage, PackageRegistry


class OrfsPythonBackendTests(unittest.TestCase):
    def test_registry_exposes_orfs_and_native_stages(self):
        backend = get_backend("orfs")
        self.assertEqual(backend.name, "orfs")
        self.assertEqual(backend.stages(), ORFS_STAGES)

    def test_missing_orfs_root_is_reported_clearly(self):
        with tempfile.TemporaryDirectory(prefix="wolf-empty-packages-") as temporary, mock.patch.dict(
            os.environ, {"ORFS_ROOT": "", "WOLF_HOME": temporary}, clear=False
        ):
            checks = {item.name: item for item in get_backend("orfs").validate({})}
        self.assertFalse(checks["ORFS_ROOT"].available)
        self.assertEqual(checks["ORFS_ROOT"].detail, "not configured or installed")

    def test_installed_flow_package_supplies_orfs_root(self):
        manifest = PackageRegistry().get("flow/orfs")
        with tempfile.TemporaryDirectory(prefix="wolf-installed-orfs-") as temporary:
            content = Path(temporary) / "source"
            flow = content / "flow"
            (flow / "util").mkdir(parents=True)
            (flow / "Makefile").write_text("", encoding="utf-8")
            (flow / "util" / "docker_shell").write_text("", encoding="utf-8")
            installed = InstalledPackage(
                manifest=manifest,
                installation_path=Path(temporary),
                content_path=content,
                installed_at="test",
                source_revision=manifest.revision,
            )
            with mock.patch("wolf.backend.orfs.PackageStore.read", return_value=installed):
                metadata = get_backend("orfs").metadata({})
                execution = get_backend("orfs").execution_environment({})
        self.assertEqual(metadata.root, flow)
        self.assertEqual(metadata.root_source, "installed flow/orfs package")
        self.assertEqual(execution["ORFS_ROOT"], str(flow))

    def test_explicit_orfs_root_overrides_installed_package(self):
        with tempfile.TemporaryDirectory(prefix="wolf-explicit-orfs-") as temporary, mock.patch(
            "wolf.backend.orfs.PackageStore.read"
        ) as read:
            metadata = get_backend("orfs").metadata({"ORFS_ROOT": temporary})
        self.assertEqual(metadata.root, Path(temporary))
        self.assertEqual(metadata.root_source, "explicit/environment ORFS_ROOT")
        read.assert_not_called()

    def test_generic_run_injects_installed_orfs_root_into_backend_subprocess(self):
        manifest = PackageRegistry().get("flow/orfs")
        with tempfile.TemporaryDirectory(prefix="wolf-run-installed-orfs-") as temporary:
            root = Path(temporary)
            content = root / "source"
            flow = content / "flow"
            flow.mkdir(parents=True)
            installed = InstalledPackage(
                manifest=manifest,
                installation_path=root,
                content_path=content,
                installed_at="test",
                source_revision=manifest.revision,
            )
            context = ResolvedContext(
                state_root=root,
                environment_name="test",
                environment_directory=root / "env",
                workspace_root=root / "work",
                design_name="ibex",
                process="asap7",
                backend="orfs",
                run_tag="ibex",
                run_directory=root / "work" / "ibex" / "ibex.asap7" / "ibex",
                values={"WORKSPACE_DIR": str(root / "work")},
            )
            args = mock.Mock(
                plan=False, yes=False, from_stage=None, to_stage=None, passthrough=[]
            )
            with mock.patch("wolf.backend.orfs.PackageStore.read", return_value=installed), mock.patch(
                "wolf.commands.run._context", return_value=context
            ), mock.patch("wolf.commands.run.run_legacy", return_value=0) as legacy:
                self.assertEqual(run_command.command_run(args), 0)
        execution_environment = legacy.call_args.args[1]
        self.assertEqual(execution_environment["ORFS_ROOT"], str(flow))

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
            ), mock.patch(
                "wolf.backend.orfs.subprocess.run",
                return_value=subprocess.CompletedProcess(["docker", "info"], 0, "", ""),
            ):
                checks = {
                    item.name: item
                    for item in get_backend("orfs").validate({"ORFS_ROOT": str(root)})
                }
        self.assertTrue(checks["selected container runtime"].available)
        self.assertNotIn("yosys", {name.lower() for name in checks})
        self.assertNotIn("openroad", {name.lower() for name in checks})

    def test_validation_prefers_usable_podman_and_reports_docker_rejection(self):
        with mock.patch(
            "wolf.backend.orfs._runtime_diagnostic",
            side_effect=lambda name: RuntimeDiagnostic(
                name,
                name == "podman",
                "usable (/mock/podman)" if name == "podman" else "binary absent",
            ),
        ):
            checks = {item.name: item for item in get_backend("orfs").validate({})}
        self.assertTrue(checks["selected container runtime"].available)
        self.assertIn("podman", checks["selected container runtime"].detail)
        self.assertFalse(checks["docker runtime"].available)
        self.assertIn("binary absent", checks["docker runtime"].detail)


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
        self._write_executable(
            self.stub_bin / "docker",
            """#!/bin/sh
printf '%s\\n' "$@" >> "$ORFS_CALL_LOG"
if [ "$1" = info ] && [ -n "${ORFS_DOCKER_INFO_ERROR:-}" ]; then
    printf '%s\\n' "$ORFS_DOCKER_INFO_ERROR" >&2
    exit 1
fi
last=""
for argument in "$@"; do last="$argument"; done
if [ "${ORFS_FAIL_TARGET:-}" = "$last" ]; then exit 27; fi
exit 0
""",
        )
        self._write_executable(
            self.stub_bin / "podman",
            """#!/bin/sh
printf '%s\\n' "$@" >> "$ORFS_CALL_LOG"
if [ "$1" = info ] && [ -n "${ORFS_PODMAN_INFO_ERROR:-}" ]; then
    printf '%s\\n' "$ORFS_PODMAN_INFO_ERROR" >&2
    exit 1
fi
last=""
for argument in "$@"; do last="$argument"; done
if [ "${ORFS_FAIL_TARGET:-}" = "$last" ]; then exit 27; fi
exit 0
""",
        )
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
        self.assertIn("binary absent", result.stdout + result.stderr)

    def test_podman_is_preferred_when_usable(self):
        result = self.shell(self.prepare_script(), extra_env={"ORFS_CONTAINER_RUNTIME": ""})
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        prepared = (self.root / "snapshot" / "orfs.command").read_text(encoding="utf-8")
        self.assertIn("Container runtime: podman", prepared)

    def test_docker_is_used_when_podman_is_unusable(self):
        result = self.shell(
            self.prepare_script(),
            extra_env={
                "ORFS_CONTAINER_RUNTIME": "",
                "ORFS_PODMAN_INFO_ERROR": "socket unavailable",
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        prepared = (self.root / "snapshot" / "orfs.command").read_text(encoding="utf-8")
        self.assertIn("Container runtime: docker", prepared)

    def test_permission_denied_runtime_error_is_clear(self):
        result = self.shell(
            """
            source "$WOLF_BIN/utils"
            source "$WOLF_BIN/backend.sh"
            source "$WOLF_BIN/container_executor.sh"
            _wolf_load_backend orfs
            _wolf_backend_validate
            """,
            extra_env={
                "ORFS_CONTAINER_RUNTIME": "docker",
                "ORFS_DOCKER_INFO_ERROR": "permission denied while trying to connect to the docker API",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("permission denied", result.stdout + result.stderr)

    def test_missing_flow_variant_fails_before_execution(self):
        result = self.shell(
            """
            source "$WOLF_BIN/utils"
            source "$WOLF_BIN/backend.sh"
            source "$WOLF_BIN/container_executor.sh"
            _wolf_load_backend orfs
            _wolf_backend_validate
            """,
            extra_env={"ORFS_FLOW_VARIANT": ""},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ORFS_FLOW_VARIANT", result.stdout + result.stderr)

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

    def test_podman_executor_uses_explicit_image_and_work_mount(self):
        result = self.shell(
            self.prepare_script() + "\n_wolf_backend_run_stage synth\n",
            extra_env={
                "ORFS_CONTAINER_RUNTIME": "podman",
                "ORFS_CONTAINER_IMAGE": "example/orfs@sha256:test",
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = self.call_log.read_text(encoding="utf-8").splitlines()
        self.assertIn("run", calls)
        self.assertIn(f"{self.flow_root}:/work:Z", calls)
        self.assertIn("/OpenROAD-flow-scripts/flow", calls)
        self.assertIn("example/orfs@sha256:test", calls)
        self.assertIn("DESIGN_CONFIG=/work/designs/asap7/ibex/config.mk", calls)

    def test_headless_execution_sets_supported_qt_environment(self):
        result = self.shell(self.prepare_script() + "\n_wolf_backend_run_stage finish\n")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = self.call_log.read_text(encoding="utf-8").splitlines()
        self.assertIn("DISPLAY=", calls)
        self.assertIn("QT_QPA_PLATFORM=offscreen", calls)

    def test_non_gui_failure_still_propagates(self):
        result = self.shell(
            self.prepare_script() + "\n_wolf_backend_run_stage finish\n",
            extra_env={"ORFS_FAIL_TARGET": "finish"},
        )
        self.assertEqual(result.returncode, 27, msg=result.stderr)

    def test_legacy_runner_dispatches_orfs_through_generic_orchestration(self):
        result = self.shell(
            """
            mkdir -p "$WOLF_ENV_DIR"
            bash "$WOLF_BIN/wolf.run" \
                --backend orfs \
                --design ibex \
                --process asap7 \
                --runtag wolf-orfs-test \
                --yes \
                -from synth \
                -to floorplan
            """,
            extra_env={"WOLF_ENV_DIR": str(self.root / "wolf-home" / "envs" / "orfs")},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = self.call_log.read_text(encoding="utf-8").splitlines()
        targets = [value for value in calls if value in ORFS_STAGES]
        self.assertEqual(targets, ["synth", "floorplan"])

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
