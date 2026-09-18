from pathlib import Path
import tempfile
import unittest

from wolf.backend.orfs_native import prepare_native_orfs
from wolf.context import ResolvedContext
from wolf.environment import ClockConstraint


class ExternalOrfsDesignTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-orfs-external-")
        self.root = Path(self.temporary.name)
        self.orfs = self.root / "flow"
        (self.orfs / "designs" / "asap7").mkdir(parents=True)
        (self.orfs / "Makefile").write_text("", encoding="utf-8")
        self.design = self.root / "fabulous-minimal"
        (self.design / "include").mkdir(parents=True)
        (self.design / "rtl.v").write_text("module fabulous_minimal_core(input clk); endmodule\n", encoding="utf-8")
        self.context = ResolvedContext(
            state_root=self.root / "state",
            environment_name="fabulous-asap7",
            environment_directory=self.root / "environment",
            workspace_root=self.root / "work",
            design_name="fabulous-minimal",
            process="asap7",
            backend="orfs",
            run_tag="fabulous-minimal",
            run_directory=self.root / "work" / "fabulous-minimal.asap7" / "fabulous-minimal",
            values={},
            format="declarative-v1",
            design_top="fabulous_minimal_core",
            design_package="rtl/fabulous-minimal",
            technology_package="pdk/asap7",
            flow_package="flow/orfs",
            package_revisions={
                "rtl/fabulous-minimal": "rtl-revision",
                "pdk/asap7": "pdk-revision",
                "flow/orfs": "flow-revision",
            },
            package_paths={"design": self.design},
            source_files=(self.design / "rtl.v",),
            include_directories=(self.design / "include",),
            clocks=(ClockConstraint("core_clock", "clk", 1050.0),),
            threads=8,
            backend_overrides={
                "orfs": {"make": {"OPENROAD_HIERARCHICAL": 0}},
            },
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_external_design_gets_deterministic_platform_base_config(self):
        first = prepare_native_orfs(
            self.context,
            self.orfs,
            runtime="podman",
            container_image="registry.example/orfs@sha256:fixed",
        )
        second = prepare_native_orfs(
            self.context,
            self.orfs,
            runtime="podman",
            container_image="registry.example/orfs@sha256:fixed",
        )
        config = Path(first["ORFS_DESIGN_CONFIG"])
        base = config.with_name("base-config.mk")

        self.assertTrue(base.is_file())
        self.assertEqual(config.read_bytes(), Path(second["ORFS_DESIGN_CONFIG"]).read_bytes())
        self.assertEqual(base.read_bytes(), Path(second["ORFS_DESIGN_CONFIG"]).with_name("base-config.mk").read_bytes())
        self.assertIn("include /wolf/generated/base-config.mk", config.read_text(encoding="utf-8"))
        self.assertIn("export PLATFORM = asap7", base.read_text(encoding="utf-8"))
        text = config.read_text(encoding="utf-8")
        self.assertIn("override DESIGN_NICKNAME := fabulous-minimal", text)
        self.assertIn("override DESIGN_NAME := fabulous_minimal_core", text)
        self.assertIn("/wolf/design/rtl.v", text)
        self.assertIn("/wolf/design/include", text)
        self.assertIn("override SDC_FILE := /wolf/generated/constraints.sdc", text)
        self.assertIn("override NUM_CORES := 8", text)
        self.assertIn("/wolf/design", first["WOLF_CONTAINER_MOUNTS"])
        self.assertIn("/wolf/generated", first["WOLF_CONTAINER_MOUNTS"])
        self.assertEqual(first["ORFS_CONTAINER_WORKDIR"], "/work")
        self.assertEqual(first["ORFS_CONTAINER_FLOW_HOME"], "/work")
        self.assertIn("set clk_period 1050", Path(first["ORFS_SDC_FILE"]).read_text(encoding="utf-8"))
        manifest = Path(first["WOLF_RESOLVED_MANIFEST"]).read_text(encoding="utf-8")
        self.assertIn("base_config:", manifest)
        self.assertIn("base_config_source: generated", manifest)
        self.assertIn("runtime: podman", manifest)
        self.assertIn("container_image: registry.example/orfs@sha256:fixed", manifest)

    def test_explicit_design_config_takes_precedence(self):
        native = self.root / "project" / "config.mk"
        native.parent.mkdir()
        native.write_text("export PLATFORM = custom\n", encoding="utf-8")
        context = self.context.__class__(
            **{**self.context.__dict__, "backend_overrides": {"orfs": {"design_config": str(native)}}}
        )
        output = prepare_native_orfs(context, self.orfs)
        config = Path(output["ORFS_DESIGN_CONFIG"]).read_text(encoding="utf-8")
        self.assertIn("include /wolf/native-config/config.mk", config)
        self.assertNotIn("base-config.mk", config)
        self.assertIn(str(native.parent) + "|/wolf/native-config", output["WOLF_CONTAINER_MOUNTS"])

    def test_missing_explicit_design_config_remains_an_error(self):
        context = self.context.__class__(
            **{**self.context.__dict__, "backend_overrides": {"orfs": {"design_config": str(self.root / "missing.mk")}}}
        )
        with self.assertRaisesRegex(ValueError, "explicit ORFS design_config does not exist"):
            prepare_native_orfs(context, self.orfs)


if __name__ == "__main__":
    unittest.main()
