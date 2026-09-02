from pathlib import Path
import tempfile
import unittest

from wolf.context import resolve_cli_path, resolve_context, resolve_stored_path


class ResolvedContextTests(unittest.TestCase):
    def test_stored_paths_resolve_from_environment_directory(self):
        with tempfile.TemporaryDirectory(prefix="wolf-context-") as temporary:
            root = Path(temporary)
            environment = root / "state" / "envs" / "demo"
            environment.mkdir(parents=True)
            context = resolve_context(
                {
                    "DESIGN_NAME": "ibex",
                    "PROCESS": "asap7",
                    "BACKEND": "orfs",
                    "WORKSPACE_DIR": "./work",
                    "ORFS_ROOT": "../../sources/orfs/flow",
                    "ORFS_DESIGN_CONFIG": "../../sources/orfs/flow/designs/asap7/ibex/config.mk",
                    "ORFS_SDC_FILE": "../../sources/orfs/flow/designs/asap7/ibex/constraint.sdc",
                },
                state_root=root / "state",
                environment_name="demo",
                environment_directory=environment,
                invocation_directory=Path("/tmp"),
            )
            self.assertEqual(context.workspace_root, environment / "work")
            self.assertEqual(
                context.run_directory,
                environment / "work" / "ibex" / "ibex.asap7" / "ibex",
            )
            self.assertEqual(
                context.values["ORFS_ROOT"], str((environment / "../../sources/orfs/flow").resolve())
            )

    def test_equivalent_cwds_resolve_identically(self):
        with tempfile.TemporaryDirectory(prefix="wolf-context-") as temporary:
            root = Path(temporary)
            environment = root / "env"
            environment.mkdir()
            values = {
                "DESIGN_NAME": "ibex",
                "PROCESS": "asap7",
                "BACKEND": "orfs",
                "WORKSPACE_DIR": "work",
                "DATA_DIR": "rtl",
            }
            first = resolve_context(values, state_root=root, environment_directory=environment,
                                    invocation_directory=Path("/"))
            second = resolve_context(values, state_root=root, environment_directory=environment,
                                     invocation_directory=Path("/tmp"))
            self.assertEqual(first.workspace_root, second.workspace_root)
            self.assertEqual(first.run_directory, second.run_directory)
            self.assertEqual(first.values["DATA_DIR"], second.values["DATA_DIR"])

    def test_cli_paths_resolve_from_invocation_directory(self):
        with tempfile.TemporaryDirectory(prefix="wolf-context-") as temporary:
            root = Path(temporary)
            self.assertEqual(resolve_cli_path("output", root), root / "output")
            self.assertEqual(resolve_stored_path("output", root / "environment"), root / "environment" / "output")

    def test_absolute_paths_remain_absolute(self):
        path = Path("/var/tmp/wolf-work")
        self.assertEqual(resolve_stored_path(str(path), Path("/irrelevant")), path)
        self.assertEqual(resolve_cli_path(str(path), Path("/irrelevant")), path)

    def test_incomplete_context_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "incomplete WOLF run context"):
            resolve_context({}, state_root=Path("/tmp/wolf-state"))

    def test_backends_do_not_use_cwd_as_output_state(self):
        repository = Path(__file__).resolve().parents[1]
        for adapter in ("cadence-flowtool.sh", "orfs.sh"):
            source = (repository / "bin" / "backends" / adapter).read_text(encoding="utf-8")
            self.assertNotIn("$PWD", source)
            self.assertNotIn("$(pwd)", source)
