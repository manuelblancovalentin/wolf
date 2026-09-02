from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
YAML_HELPER = REPO_ROOT / "bin" / "yaml_helper.py"


class YamlHelperTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="wolf-yaml-tests-"
        )
        self.root = Path(self._temporary_directory.name)
        self.yaml_file = self.root / "test.yaml"
        self.yaml_file.write_text(
            textwrap.dedent(
                """\
                RTL:
                  chip:
                    description: Example design
                    search_path:
                      - src
                      - rtl/common
                flows:
                  main:
                    steps:
                      synth: {}
                      place: {}
                """
            )
        )

    def tearDown(self):
        self._temporary_directory.cleanup()

    def helper(self, *args):
        return subprocess.run(
            [sys.executable, str(YAML_HELPER), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_keys_and_sequence_values(self):
        keys = self.helper("keys", str(self.yaml_file), "RTL.chip")
        self.assertEqual(keys.returncode, 0, msg=keys.stderr)
        self.assertEqual(keys.stdout.splitlines(), ["description", "search_path"])

        values = self.helper(
            "get-values", str(self.yaml_file), "RTL.chip.search_path"
        )
        self.assertEqual(values.returncode, 0, msg=values.stderr)
        self.assertEqual(values.stdout.splitlines(), ["src", "rtl/common"])

    def test_scalar_value_round_trips_spaces(self):
        result = self.helper("get-value", str(self.yaml_file), "RTL.chip.description")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout, "Example design\n")

    def test_flowtool_stage_discovery(self):
        result = self.helper("stages", str(self.yaml_file), "main")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["main", "main.synth", "main.place"],
        )

    def test_missing_path_fails_clearly(self):
        result = self.helper("get-value", str(self.yaml_file), "RTL.missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wolf YAML error", result.stderr)


if __name__ == "__main__":
    unittest.main()
