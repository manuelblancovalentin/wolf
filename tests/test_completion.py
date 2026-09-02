import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from wolf.cli import build_parser, main
from wolf.commands.completion import candidates, command_complete


class CompletionProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-completion-")
        self.root = Path(self.temporary.name)
        for name in ("alpha", "analog test", "beta"):
            (self.root / "envs" / name).mkdir(parents=True)
        self.environment = mock.patch.dict(
            os.environ,
            {"WOLF_HOME": str(self.root)},
            clear=False,
        )
        self.environment.start()
        self.parser = build_parser()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_top_level_commands_and_options_exclude_internal_protocols(self):
        values = candidates(self.parser, [""])
        self.assertIn("activate", values)
        self.assertIn("run", values)
        self.assertIn("--help", values)
        self.assertIn("--version", values)
        self.assertNotIn("_complete", values)
        self.assertNotIn("_shell-activate", values)

    def test_nested_commands_and_options_are_contextual(self):
        self.assertEqual(candidates(self.parser, ["env", ""]),
                         ["create", "list", "remove", "set", "show"])
        self.assertEqual(candidates(self.parser, ["env", "remove", "--"]),
                         ["--help", "--yes"])
        self.assertIn("--environment", candidates(self.parser, ["run", "--e"]))

    def test_environment_names_complete_by_prefix_and_preserve_spaces(self):
        self.assertEqual(candidates(self.parser, ["activate", "a"]),
                         ["alpha", "analog test"])
        self.assertEqual(candidates(self.parser, ["env", "show", "b"]), ["beta"])
        self.assertEqual(candidates(self.parser, ["env", "set", "alpha", ""]), [])
        self.assertEqual(candidates(self.parser, ["run", "--environment", "a"]),
                         ["alpha", "analog test"])

    def test_backend_names_complete_for_show_and_run(self):
        self.assertEqual(candidates(self.parser, ["backend", "show", "o"]), ["orfs"])
        self.assertEqual(candidates(self.parser, ["run", "--backend=o"]),
                         ["--backend=orfs"])

    def test_machine_protocol_has_no_ui_header(self):
        args = self.parser.parse_args(["_complete", "--", "activate", "b"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(command_complete(args), 0)
        self.assertEqual(output.getvalue(), "beta\n")

    def test_completing_help_option_does_not_emit_a_ui_header(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["_complete", "--", "run", "-h"]), 0)
        self.assertEqual(output.getvalue(), "-h\n")


if __name__ == "__main__":
    unittest.main()
