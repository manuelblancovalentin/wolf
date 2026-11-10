import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from wolf.env_describe import DESCRIBE_SCHEMA, build_description, description_path, safe_value, write_description

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"


class SafeValueTests(unittest.TestCase):
    def test_a_short_identifier_passes_through(self):
        self.assertEqual(safe_value("rvt"), "rvt")

    def test_a_decimal_number_passes_through(self):
        self.assertEqual(safe_value("1050"), "1050")

    def test_none_stays_none_not_hidden(self):
        self.assertIsNone(safe_value(None))

    def test_a_value_with_a_dollar_sign_is_hidden(self):
        self.assertEqual(safe_value("$HOME/foo"), "hidden")

    def test_a_value_with_a_space_is_hidden(self):
        self.assertEqual(safe_value("has a space"), "hidden")

    def test_a_value_over_64_characters_is_hidden(self):
        self.assertEqual(safe_value("x" * 65), "hidden")

    def test_a_value_at_64_characters_passes_through(self):
        self.assertEqual(safe_value("x" * 64), "x" * 64)

    def test_an_absolute_path_inside_the_project_becomes_relative(self):
        with tempfile.TemporaryDirectory() as root:
            project_root = Path(root) / "project"
            (project_root / "inputs").mkdir(parents=True)
            inside = project_root / "inputs" / "constraints.sdc"
            inside.touch()
            self.assertEqual(safe_value(str(inside), project_root), "inputs/constraints.sdc")

    def test_an_absolute_path_outside_the_project_is_hidden(self):
        with tempfile.TemporaryDirectory() as root:
            project_root = Path(root) / "project"
            project_root.mkdir()
            outside = Path(root) / "elsewhere" / "file.sdc"
            self.assertEqual(safe_value(str(outside), project_root), "hidden")

    def test_a_library_looking_path_becomes_the_library_marker_even_inside_the_project(self):
        self.assertEqual(safe_value("/asic/Library/cells/foo.lib"), "<library>")
        self.assertEqual(safe_value("/ip/vendor/thing"), "<library>")

    def test_no_project_root_and_outside_path_is_hidden_not_an_error(self):
        self.assertEqual(safe_value("/some/absolute/path"), "hidden")


class BuildDescriptionTests(unittest.TestCase):
    def test_schema_and_activation_commands(self):
        description = build_description(
            "demo", {"DESIGN_NAME": "demo_design"}, design_name="demo_design",
            process="demo_process", metal_stack="M9",
        )
        self.assertEqual(description["schema"], DESCRIBE_SCHEMA)
        self.assertEqual(
            description["activation_commands"], ["wolf activate demo", "wolf run"],
        )

    def test_a_library_value_never_reaches_the_description_as_a_real_path(self):
        description = build_description(
            "demo", {"CONSTRAINTS_FILE": "/asic/Library/secret/path.sdc"},
        )
        rendered = json.dumps(description)
        self.assertNotIn("/asic/Library/secret", rendered)
        self.assertEqual(description["variables"]["CONSTRAINTS_FILE"], "<library>")

    def test_seventy_variables_all_come_through_sanitized(self):
        variables = {f"VAR_{i}": "ok_value" for i in range(70)}
        variables["BAD"] = "has space"
        description = build_description("demo", variables)
        self.assertEqual(len(description["variables"]), 71)
        self.assertEqual(description["variables"]["VAR_0"], "ok_value")
        self.assertEqual(description["variables"]["BAD"], "hidden")


class WriteDescriptionTests(unittest.TestCase):
    def test_writes_a_real_file_never_a_link(self):
        with tempfile.TemporaryDirectory() as root:
            project_root = Path(root)
            description = build_description("demo", {})
            path = write_description(project_root, "demo_design", "demo", description)
            self.assertEqual(path, description_path(project_root, "demo_design", "demo"))
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], DESCRIBE_SCHEMA)


class EnvDescribeCliTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="wolf-describe-tests-")
        self.root = Path(self._temporary_directory.name)
        self.wolf_home = self.root / "wolf-state"
        self.project_root = self.root / "project"
        self.environment = os.environ.copy()
        self.environment.update({
            "HOME": str(self.root / "home"),
            "WOLF_HOME": str(self.wolf_home),
            "WOLF_REGISTRY": str(REPO_ROOT / "registry"),
            "PYTHONPATH": str(SOURCE_ROOT),
        })
        for key in ("WOLF_ENV_NAME", "WOLF_ENV_DIR", "WOLF_ACTIVE_ENV"):
            self.environment.pop(key, None)
        (self.root / "home").mkdir()
        (self.wolf_home / "envs" / "demo").mkdir(parents=True)
        (self.wolf_home / "envs" / "demo" / "wolf.yaml").write_text(
            "schema: wolf.environment/v1\n"
            "name: demo\n"
            "design:\n  name: demo_design\n"
            "technology:\n  name: demo_process\n  metal_stack: M9\n"
            f"project:\n  root: {self.project_root}\n"
            "env:\n"
            "  DESIGN_NAME: demo_design\n"
            "  VTHS: rvt\n"
            "  LEAK: \"$HOME/secret path\"\n"
            "  LIBRARY_PATH: /asic/Library/not/real.lib\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._temporary_directory.cleanup()

    def wolf(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *arguments],
            cwd=self.root, env=self.environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_describe_json_sanitizes_and_never_leaks_the_planted_strings(self):
        result = self.wolf("env", "describe", "demo", "--json")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("/asic/Library", result.stdout)
        self.assertNotIn("secret", result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["variables"]["LEAK"], "hidden")
        self.assertEqual(data["variables"]["LIBRARY_PATH"], "<library>")
        self.assertEqual(data["variables"]["VTHS"], "rvt")

    def test_describe_writes_a_real_file_next_to_the_environment_definition(self):
        result = self.wolf("env", "describe", "demo", "--json")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        written = self.project_root / "inputs" / "env" / "demo_design" / "wolf.demo.description.json"
        self.assertTrue(written.is_file())
        self.assertFalse(written.is_symlink())

    def test_describe_includes_the_activation_lines(self):
        result = self.wolf("env", "describe", "demo", "--json")
        data = json.loads(result.stdout)
        self.assertEqual(data["activation_commands"], ["wolf activate demo", "wolf run"])


if __name__ == "__main__":
    unittest.main()
