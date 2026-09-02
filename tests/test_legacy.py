import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import textwrap
import unittest
import uuid

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WOLF_INIT = REPO_ROOT / "bin" / "wolf.init.sh"
WOLF_RUN = REPO_ROOT / "bin" / "wolf.run"


class TemporaryWolfHome(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="wolf-tests-")
        self.root = Path(self._temporary_directory.name)
        self.home = self.root / "home"
        self.home.mkdir()

    def tearDown(self):
        self._temporary_directory.cleanup()

    def shell(self, script, *, extra_env=None):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", script],
            cwd=self.root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )


class LegacyRunTests(TemporaryWolfHome):
    def setUp(self):
        super().setUp()
        self.caller_dir = self.root / "caller"
        self.caller_dir.mkdir()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        self.process_scripts = self.root / "process-scripts"
        self.process_scripts.mkdir()
        (self.process_scripts / "flow.tcl").write_text("puts baseline\n")

        self.templates = self.root / "templates"
        self.templates.mkdir()
        self.design_template = self.templates / "design.yaml"
        self.design_template.write_text(
            "%TAG ! tag:design.stylus.cadence.com,0.1:\n"
            "---\n"
            "design: ${DESIGN_NAME}\n"
            "constraints: ${CONSTRAINTS_FILES}\n"
        )
        self.common_template = self.templates / "common.yaml"
        self.common_template.write_text(
            "%TAG ! tag:design.stylus.cadence.com,0.1:\n---\ncommon: true\n"
        )
        self.host_template = self.templates / "host.yaml"
        self.host_template.write_text(
            "%TAG ! tag:design.stylus.cadence.com,0.1:\n---\nhost: test\n"
        )
        self.flow_template = self.templates / "flow.yaml"
        self.flow_template.write_text(
            textwrap.dedent(
                """\
                flow_current: main
                flows:
                  main:
                    steps:
                      synth: {}
                      floorplan: {}
                      place: {}
                      cts: {}
                      route: {}
                      finish: {}
                """
            )
        )

        self.rtl_yaml = self.inputs / "rtl.yaml"
        self.rtl_yaml.write_text("RTL: {}\n")
        self.constraints = self.inputs / "constraints.sdc"
        self.constraints.write_text("# test constraints\n")
        self.floorplan = self.inputs / "floorplan.tcl"
        self.floorplan.write_text("# test floorplan\n")
        self.floorplan_io = self.inputs / "floorplan.io"
        self.floorplan_io.write_text("# test IO\n")

        self.wolf_env_dir = self.home / ".wolf" / "envs" / "test"
        self.wolf_env_dir.mkdir(parents=True)

        self.stub_bin = self.root / "stub-bin"
        self.stub_bin.mkdir()
        self.call_log = self.root / "flowtool-calls.jsonl"
        self._write_executable(
            self.stub_bin / "shyaml",
            """#!/bin/sh
# RTL is deliberately empty in these tests.
exit 0
""",
        )
        self._write_executable(
            self.stub_bin / "flowtool",
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ["FLOWTOOL_CALL_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\\n")

def option(name):
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        return ""

stage = option("-from")
log_base = option("-log")
if log_base:
    log_file = Path(log_base + ".log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if os.environ.get("FLOWTOOL_LOG_FAILURE_STAGE") == stage:
        log_file.write_text("Flow failed\\n", encoding="utf-8")
    else:
        log_file.write_text("Flow succeeded\\n", encoding="utf-8")

exit_code = int(os.environ.get("FLOWTOOL_EXIT_CODE", "0"))
fail_stage = os.environ.get("FLOWTOOL_FAIL_STAGE")
if fail_stage and fail_stage != stage:
    exit_code = 0
sys.exit(exit_code)
""",
        )

        self.base_env = os.environ.copy()
        self.base_env.update(
            {
                "HOME": str(self.home),
                "PATH": str(self.stub_bin) + os.pathsep + os.environ.get("PATH", ""),
                "WORKSPACE_DIR": str(self.workspace),
                "DESIGN_NAME": "environment_design",
                "PROCESS": "ENV_PROCESS",
                "PROCESS_SCRIPTS": str(self.process_scripts),
                "RTL_YAML_FILE": str(self.rtl_yaml),
                "DATA_DIR": str(self.data),
                "INPUTS_DIR": str(self.inputs),
                "FLOORPLAN_FILE": str(self.floorplan),
                "FLOORPLAN_IO_FILE": str(self.floorplan_io),
                "CONSTRAINTS_FILE": str(self.constraints),
                "PROCESS_SETUP_COMMON_TEMPLATE": str(self.common_template),
                "PROCESS_SETUP_HOST_TEMPLATE": str(self.host_template),
                "PROCESS_FLOW_TEMPLATE": str(self.flow_template),
                "WOLF_ENV_DIR": str(self.wolf_env_dir),
                "WOLF_ENV_NAME": "test",
                "FLOWTOOL_CALL_LOG": str(self.call_log),
                "LIB_DIR": str(self.root / "lib"),
                "IO_LIB_DIR": str(self.root / "io-lib"),
                "PDK_DIR": str(self.root / "pdk"),
                "METAL_STACK": "test-stack",
                "VTHS": "rvt",
                "TRACKS": "test-track",
            }
        )

    @staticmethod
    def _write_executable(path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_wolf(
        self,
        *args,
        design="chip",
        process="TEST",
        cwd=None,
        flowtool_exit=0,
        fail_stage=None,
        log_failure_stage=None,
    ):
        command = [
            "bash",
            str(WOLF_RUN),
            "-y",
            "-f",
            str(self.design_template),
            "--design",
            design,
            "--process",
            process,
            *args,
        ]
        env = self.base_env.copy()
        env["FLOWTOOL_EXIT_CODE"] = str(flowtool_exit)
        if fail_stage:
            env["FLOWTOOL_FAIL_STAGE"] = fail_stage
        if log_failure_stage:
            env["FLOWTOOL_LOG_FAILURE_STAGE"] = log_failure_stage
        return subprocess.run(
            command,
            cwd=cwd or self.caller_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def process_root(self, design="chip", process="TEST"):
        return self.workspace / design / f"{design}.{process}"

    def calls(self):
        if not self.call_log.exists():
            return []
        return [json.loads(line) for line in self.call_log.read_text().splitlines()]

    def assert_success(self, result):
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_characterization_first_run_and_latest_links(self):
        result = self.run_wolf("-flow", "main.synth")
        self.assert_success(result)

        run_dir = self.process_root() / "chip.1"
        self.assertTrue(run_dir.is_dir())
        self.assertEqual((self.process_root() / "chip.latest").resolve(), run_dir)
        self.assertEqual((run_dir / "scripts.latest").resolve(), run_dir / "scripts")
        self.assertEqual((run_dir / "scripts" / "flow.tcl").read_text(), "puts baseline\n")
        self.assertTrue((run_dir / "setup.chip.yaml.latest").is_symlink())
        self.assertTrue((run_dir / "flow.yaml.latest").is_symlink())
        self.assertTrue((run_dir / "setup.chip.yaml.latest").resolve().is_file())
        self.assertTrue((run_dir / "flow.yaml.latest").resolve().is_file())

    def test_characterization_clean_runs_are_numbered(self):
        self.assert_success(self.run_wolf("-flow", "main.synth"))
        self.assert_success(self.run_wolf("--clean", "-flow", "main.synth"))
        self.assert_success(self.run_wolf("--clean", "-flow", "main.synth"))

        root = self.process_root()
        self.assertTrue((root / "chip.1").is_dir())
        self.assertTrue((root / "chip.2").is_dir())
        self.assertTrue((root / "chip.3").is_dir())
        self.assertEqual((root / "chip.latest").resolve(), root / "chip.3")

    def test_characterization_default_run_continues_latest_existing_run(self):
        self.assert_success(self.run_wolf("-flow", "main.synth"))
        self.assert_success(self.run_wolf("--clean", "-flow", "main.synth"))
        self.assert_success(self.run_wolf("-flow", "main.place"))

        root = self.process_root()
        self.assertFalse((root / "chip.3").exists())
        self.assertEqual((root / "chip.latest").resolve(), root / "chip.2")

    def test_characterization_explicit_runtag_is_created_then_continued(self):
        self.assert_success(
            self.run_wolf("--runtag", "experiment", "-flow", "main.synth")
        )
        self.assert_success(
            self.run_wolf("--runtag", "experiment", "-flow", "main.place")
        )

        root = self.process_root()
        self.assertTrue((root / "experiment").is_dir())
        self.assertFalse((root / "experiment.1").exists())
        self.assertEqual((root / "chip.latest").resolve(), root / "experiment")

    def test_regression_unchanged_scripts_reuse_snapshot(self):
        self.assert_success(self.run_wolf("-flow", "main.synth"))
        self.assert_success(self.run_wolf("-flow", "main.place"))

        run_dir = self.process_root() / "chip.1"
        self.assertTrue((run_dir / "scripts").is_dir())
        self.assertFalse((run_dir / "scripts.1").exists())
        self.assertEqual((run_dir / "scripts.latest").resolve(), run_dir / "scripts")

    def test_characterization_changed_scripts_create_numbered_snapshot(self):
        self.assert_success(self.run_wolf("-flow", "main.synth"))
        (self.process_scripts / "flow.tcl").write_text("puts changed\n")
        self.assert_success(self.run_wolf("-flow", "main.place"))

        run_dir = self.process_root() / "chip.1"
        self.assertTrue((run_dir / "scripts.1").is_dir())
        self.assertEqual((run_dir / "scripts.latest").resolve(), run_dir / "scripts.1")

    def test_regression_cli_design_process_and_runtag_select_run(self):
        result = self.run_wolf(
            "--runtag",
            "cli-tag",
            "-flow",
            "main.synth",
            design="cli_design",
            process="CLI_PROCESS",
        )
        self.assert_success(result)

        run_dir = self.process_root("cli_design", "CLI_PROCESS") / "cli-tag"
        self.assertTrue(run_dir.is_dir())
        generated_setup = (run_dir / "setup.cli_design.yaml.latest").resolve()
        self.assertIn("design: cli_design", generated_setup.read_text())

    def test_characterization_from_to_and_passthrough_arguments(self):
        result = self.run_wolf(
            "-from",
            "main.synth",
            "-to",
            "main.place",
            "-verbose",
            "value with spaces",
        )
        self.assert_success(result)

        calls = self.calls()
        self.assertEqual(
            [call[call.index("-from") + 1] for call in calls],
            ["main.synth", "main.floorplan", "main.place"],
        )
        for call in calls:
            verbose_index = call.index("-verbose")
            self.assertEqual(call[verbose_index + 1], "value with spaces")

    def test_characterization_flow_selects_single_stage(self):
        result = self.run_wolf("-flow", "main.route")
        self.assert_success(result)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("-from") + 1], "main.route")
        self.assertEqual(calls[0][calls[0].index("-to") + 1], "main.route")

    def test_regression_cleanup_never_removes_caller_files(self):
        unrelated = [
            self.caller_dir / "unrelated.out",
            self.caller_dir / "unrelated.cmd.keep",
            self.caller_dir / "unrelated.log",
        ]
        for path in unrelated:
            path.write_text("do not delete\n")

        result = self.run_wolf("-flow", "main.synth", cwd=self.caller_dir)
        self.assert_success(result)
        for path in unrelated:
            self.assertEqual(path.read_text(), "do not delete\n")

    def test_regression_history_is_valid_and_round_trips_values(self):
        result = self.run_wolf(
            "-flow",
            "main.synth",
            "--label",
            'value: "quoted"',
        )
        self.assert_success(result)

        history_path = self.wolf_env_dir / "history"
        history = yaml.safe_load(history_path.read_text())
        self.assertEqual(len(history), 1)
        run_uuid, entry = next(iter(history.items()))
        uuid.UUID(str(run_uuid))
        self.assertIn("wolf run", entry["cmd1"])
        self.assertIn("--design chip", entry["cmd1"])
        self.assertIn("flowtool", entry["cmd2"])
        cmd1_args = shlex.split(entry["cmd1"])
        cmd2_args = shlex.split(entry["cmd2"])
        self.assertEqual(cmd1_args[cmd1_args.index("--label") + 1], 'value: "quoted"')
        self.assertEqual(cmd2_args[cmd2_args.index("--label") + 1], 'value: "quoted"')
        self.assertTrue(entry["date"])
        self.assertRegex(entry["date"], r"\b20\d\d\b")
        self.assertEqual(
            Path(entry["dir"]).resolve(),
            (self.process_root() / "chip.1").resolve(),
        )

    def test_characterization_successful_tool_stage_returns_success(self):
        result = self.run_wolf("-flow", "main.synth")
        self.assert_success(result)
        self.assertEqual(len(self.calls()), 1)

    def test_regression_nonzero_tool_stage_stops_and_propagates_status(self):
        result = self.run_wolf(
            "-from",
            "main.synth",
            "-to",
            "main.route",
            flowtool_exit=23,
            fail_stage="main.synth",
        )
        self.assertEqual(
            result.returncode,
            23,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertEqual(len(self.calls()), 1)

    def test_characterization_log_failure_remains_compatibility_check(self):
        result = self.run_wolf(
            "-flow",
            "main.synth",
            log_failure_stage="main.synth",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 1)


class LegacyEnvironmentAndProcessTests(TemporaryWolfHome):
    def test_characterization_environment_creation_writes_metadata(self):
        result = self.shell(
            f"source {shlex.quote(str(WOLF_INIT))}\n"
            "wolf env create --name demo\n"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        env_dir = self.home / ".wolf" / "envs" / "demo"
        self.assertTrue((env_dir / "activate").is_file())
        self.assertTrue((env_dir / "deactivate").is_file())
        self.assertIn('WOLF_ENV_NAME="demo"', (env_dir / "activate").read_text())
        self.assertIn(f'WOLF_ENV_DIR="{env_dir}"', (env_dir / "activate").read_text())

    def test_characterization_environment_stores_variables(self):
        result = self.shell(
            f"source {shlex.quote(str(WOLF_INIT))}\n"
            "wolf env create --name demo\n"
            "wolf activate demo\n"
            "wolf set TEST_VALUE stored\n"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        vars_file = self.home / ".wolf" / "envs" / "demo" / "vars.env"
        self.assertEqual(vars_file.read_text(), 'TEST_VALUE="stored"\n')

    def test_regression_unset_command_removes_stored_variable(self):
        result = self.shell(
            f"source {shlex.quote(str(WOLF_INIT))}\n"
            "wolf env create --name demo\n"
            "wolf activate demo\n"
            "wolf set TEST_VALUE stored\n"
            "wolf unset TEST_VALUE\n"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        vars_file = self.home / ".wolf" / "envs" / "demo" / "vars.env"
        self.assertNotIn("TEST_VALUE=", vars_file.read_text())

    def test_regression_auto_setup_missing_variable_uses_error_helper(self):
        env_dir = self.home / ".wolf" / "envs" / "demo"
        env_dir.mkdir(parents=True)
        result = self.shell(
            f"source {shlex.quote(str(WOLF_INIT))}\n"
            "export WOLF_ENV_NAME=demo\n"
            f"export WOLF_ENV_DIR={shlex.quote(str(env_dir))}\n"
            "unset PROCESS\n"
            "_wolf_env auto-setup\n"
        )
        combined = result.stdout + result.stderr
        self.assertIn('Variable "PROCESS" not set', combined)
        self.assertNotIn("syntax error", combined.lower())

    def test_regression_auto_setup_overwrite_uses_boolean_value(self):
        project = self.root / "project"
        setup_file = project / "inputs" / "env" / "design" / "setup.design.template.yaml"
        script = f"""
            source {shlex.quote(str(WOLF_INIT))}
            wolf env create --name demo
            wolf activate demo
            export PROCESS=no_templates
            export DESIGN_NAME=design
            export PROJ_DIR={shlex.quote(str(project))}
            export METAL_STACK=test_stack
            export VTHS=rvt
            _wolf_env auto-setup -y
            printf 'marker\\n' >> {shlex.quote(str(setup_file))}
            _wolf_env auto-setup -y
        """
        result = self.shell(textwrap.dedent(script))
        combined = result.stdout + result.stderr
        self.assertNotIn("OVERWRITE: command not found", combined)
        self.assertTrue(setup_file.is_file())
        self.assertNotIn("marker", setup_file.read_text())

    def test_regression_process_creation_uses_committed_template(self):
        result = self.shell(
            f"source {shlex.quote(str(WOLF_INIT))}\n"
            "_wolf_process create --name tsmc65\n"
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        process_dir = self.home / ".wolf" / "config" / "tsmc65"
        self.assertTrue(process_dir.is_dir())
        self.assertTrue(list(process_dir.glob("tsmc65.*.bucket.csh")))
        self.assertNotIn("Invalid installation", result.stdout + result.stderr)

    def test_regression_unknown_technode_returns_failure_without_creation(self):
        result = self.shell(
            f"source {shlex.quote(str(WOLF_INIT))}\n"
            "_wolf_process create --name not_a_technode\n"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / ".wolf" / "config" / "not_a_technode").exists())


if __name__ == "__main__":
    unittest.main()
