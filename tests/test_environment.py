import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wolf.environment import load_environment, resolve_declarative_environment


class DeclarativeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-environment-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        self.environment = self.state / "envs" / "demo"
        self.environment.mkdir(parents=True)
        self.variables = patch.dict(
            os.environ,
            {"WOLF_HOME": str(self.state), "WOLF_REGISTRY": str(self.registry)},
        )
        self.variables.start()
        self._package("rtl", "ibex", "rtl-rev", {"design": {"name": "ibex", "top": "ibex_core"}})
        self._package("pdk", "asap7", "pdk-rev", {"technology": {"name": "asap7"}})
        self._package("flow", "orfs", "flow-rev", {"flow": {"name": "orfs", "backend": "orfs"}})

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def _package(self, kind, name, revision, metadata):
        manifest = {
            "schema_version": 1,
            "kind": kind,
            "name": name,
            "description": name,
            "source": {"type": "git", "url": f"https://example.test/{name}", "revision": revision},
            "validation": {"required_paths": []},
            "metadata": metadata,
        }
        directory = self.registry / kind
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        installation = self.state / "packages" / kind / name / revision
        content = installation / "source"
        content.mkdir(parents=True)
        (installation / "installed.yaml").write_text(
            yaml.safe_dump({
                "package": f"{kind}/{name}",
                "revision": revision,
                "source_revision": revision,
                "content_path": "source",
                "installed_at": "2026-09-02T00:00:00Z",
            }),
            encoding="utf-8",
        )

    def _write(self, text, name="wolf.yaml"):
        path = self.environment / name
        path.write_text(text, encoding="utf-8")
        return path

    def _complete_yaml(self, extra=""):
        return f"""schema: wolf.environment/v1
name: demo
design:
  package: rtl/ibex
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: ./work
constraints:
  clocks:
    - name: core_clock
      port: clk_i
      period_ps: 1050
backend:
  orfs:
    make:
      SWAP_ARITH_OPERATORS: ""
      OPENROAD_HIERARCHICAL: 0
{extra}"""

    def test_parse_and_resolve_declarative_environment(self):
        profile = load_environment(self._write(self._complete_yaml()), expected_name="demo")
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        self.assertEqual(context.format, "declarative-v1")
        self.assertEqual((context.design_name, context.design_top), ("ibex", "ibex_core"))
        self.assertEqual((context.process, context.flow_name, context.backend), ("asap7", "orfs", "orfs"))
        self.assertEqual(context.workspace_root, self.environment / "work")
        self.assertEqual(context.clocks[0].period_ps, 1050)
        self.assertEqual(context.package_revisions["rtl/ibex"], "rtl-rev")
        self.assertEqual(context.backend_overrides["orfs"]["make"]["OPENROAD_HIERARCHICAL"], 0)

    def test_environment_values_override_package_defaults(self):
        text = self._complete_yaml().replace("  package: rtl/ibex\ntechnology:", "  package: rtl/ibex\n  name: renamed\n  top: custom_top\ntechnology:")
        context = resolve_declarative_environment(
            load_environment(self._write(text)),
            state_root=self.state,
            environment_directory=self.environment,
        )
        self.assertEqual((context.design_name, context.design_top), ("renamed", "custom_top"))

    def test_rejects_unsupported_schema_unknown_field_and_invalid_clock(self):
        cases = (
            ("schema: wolf.environment/v2\nname: demo\n", "unsupported"),
            ("schema: wolf.environment/v1\nname: demo\ndesgin: {}\n", "desgin"),
            (self._complete_yaml().replace("period_ps: 1050", "period_ps: 0"), "period_ps"),
        )
        for index, (text, message) in enumerate(cases):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                load_environment(self._write(text, f"bad-{index}.yaml"))

    def test_partial_environment_loads_but_cannot_resolve_a_run(self):
        profile = load_environment(self._write("""schema: wolf.environment/v1
name: demo
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
"""))
        with self.assertRaisesRegex(ValueError, "unresolved required field: design, workspace.root"):
            resolve_declarative_environment(
                profile, state_root=self.state, environment_directory=self.environment
            )

    def test_cli_design_override_completes_partial_profile(self):
        profile = load_environment(self._write("""schema: wolf.environment/v1
name: demo
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: work
"""))
        context = resolve_declarative_environment(
            profile,
            state_root=self.state,
            environment_directory=self.environment,
            design_override="rtl/ibex",
        )
        self.assertEqual(context.design_name, "ibex")

    def test_resolution_is_independent_of_cwd(self):
        profile = load_environment(self._write(self._complete_yaml()))
        before = Path.cwd()
        try:
            os.chdir("/")
            first = resolve_declarative_environment(
                profile, state_root=self.state, environment_directory=self.environment
            )
            os.chdir("/tmp")
            second = resolve_declarative_environment(
                profile, state_root=self.state, environment_directory=self.environment
            )
        finally:
            os.chdir(before)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
