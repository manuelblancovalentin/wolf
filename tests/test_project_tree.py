from pathlib import Path
import tempfile
import unittest

from wolf.project_tree import scan_design, scan_project_tree


class ProjectTreeScanTests(unittest.TestCase):
    """Built against a real legacy WOLF project tree
    (sandboxes/manuelbv/wolf_tutorials/ALU): per-design subdirectories for
    most categories, but a flat <design>.constraints.sdc file for
    constraints specifically -- both shapes have to resolve to the same
    design name."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-project-tree-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _touch(self, relative: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        return path

    def test_empty_directory_scans_as_nothing_found_not_an_error(self):
        scan = scan_project_tree(self.root)
        self.assertFalse(scan.inputs_exists)
        self.assertFalse(scan.outputs_exists)
        self.assertFalse(scan.workspace_exists)
        self.assertEqual(scan.design_names, ())
        for category in scan.categories.values():
            self.assertFalse(category.exists)
            self.assertEqual(category.designs, {})

    def test_mixed_subdirectory_and_flat_file_shapes_both_resolve_to_the_design_name(self):
        """hdl/hvt as a per-design subdirectory, constraints as a flat
        <design>.constraints.sdc file -- the real shape found in
        sandboxes/manuelbv/wolf_tutorials/ALU, not a synthetic
        simplification."""
        self._touch("inputs/hdl/ALU_MIPS_32b/top.sv")
        self._touch("inputs/constraints/ALU_MIPS_32b.constraints.sdc")
        self._touch("inputs/lib/lef/some.lef")

        scan = scan_project_tree(self.root)
        self.assertTrue(scan.inputs_exists)
        self.assertEqual(scan.design_names, ("ALU_MIPS_32b",))
        self.assertTrue(scan.categories["hdl"].exists)
        self.assertEqual(scan.categories["hdl"].designs["ALU_MIPS_32b"].name, "ALU_MIPS_32b")
        self.assertTrue(scan.categories["constraints"].designs["ALU_MIPS_32b"].name.endswith(".sdc"))
        self.assertTrue(scan.lib_subdirs["lef"])
        self.assertFalse(scan.lib_subdirs["gds"])
        # Categories with nothing at all still report as a real, present
        # absence, not silently omitted.
        self.assertFalse(scan.categories["tb"].exists)
        self.assertEqual(
            scan.designs_missing_categories("ALU_MIPS_32b"),
            ("calibre", "env", "floorplans", "flows", "scripts", "tb"),
        )

    def test_scan_design_collects_hdl_files_constraints_and_run_counts(self):
        self._touch("inputs/hdl/top/a.sv")
        self._touch("inputs/hdl/top/b.v")
        self._touch("inputs/hdl/top/notes.txt")  # not an HDL suffix -- excluded
        self._touch("inputs/constraints/top.constraints.sdc")
        self._touch("outputs/top/top.1/placeholder")
        self._touch("outputs/top/top.2/placeholder")
        self._touch("workspace/top/top.tsmc65/top.1/placeholder")
        self._touch("workspace/top/top.tsmc65/top.2/placeholder")
        self._touch("workspace/top/top.tsmc65/top.3/placeholder")
        (self.root / "workspace/top/top.tsmc65/top.latest").symlink_to(
            self.root / "workspace/top/top.tsmc65/top.3",
        )

        design = scan_design(self.root, "top")
        self.assertEqual(len(design.hdl_files), 2)
        self.assertEqual(len(design.constraint_files), 1)
        self.assertTrue(design.constraint_files[0].name.endswith(".sdc"))
        self.assertEqual(design.output_run_count, 2)
        # Exactly the 3 numbered run directories -- the ".latest" symlink
        # does not count as a run of its own.
        self.assertEqual(design.workspace_run_count, 3)
        self.assertEqual(design.missing_categories, ("calibre", "env", "floorplans", "flows", "scripts", "tb"))

    def test_unknown_design_scans_as_empty_not_an_error(self):
        self._touch("inputs/hdl/top/a.sv")
        design = scan_design(self.root, "nonexistent")
        self.assertEqual(design.hdl_files, ())
        self.assertEqual(design.constraint_files, ())
        self.assertEqual(design.output_run_count, 0)
        self.assertEqual(design.workspace_run_count, 0)


@unittest.skipUnless(
    Path("/mnt/raid0/asic/projects/NU/sandboxes/manuelbv/wolf_tutorials/ALU").is_dir(),
    "only runs on kona, against the real legacy ALU_MIPS_32b tutorial tree",
)
class RealAluTreeScanTests(unittest.TestCase):
    """Characterization test against the actual tree this module's shape
    was derived from -- read-only, asserts on what's really there."""

    ROOT = Path("/mnt/raid0/asic/projects/NU/sandboxes/manuelbv/wolf_tutorials/ALU")

    def test_shallow_scan_finds_the_one_real_design(self):
        scan = scan_project_tree(self.ROOT)
        self.assertTrue(scan.inputs_exists)
        self.assertTrue(scan.workspace_exists)
        self.assertEqual(scan.design_names, ("ALU_MIPS_32b",))
        # "flows" is a newer category than this real tutorial tree predates;
        # legitimately missing until `wolf env auto-setup`/`wolf flow
        # snapshot` is run against it.
        self.assertEqual(scan.designs_missing_categories("ALU_MIPS_32b"), ("flows",))

    def test_deep_scan_matches_the_real_file_counts(self):
        design = scan_design(self.ROOT, "ALU_MIPS_32b")
        self.assertEqual(len(design.hdl_files), 10)
        self.assertEqual(len(design.constraint_files), 1)
        self.assertEqual(design.workspace_run_count, 8)


if __name__ == "__main__":
    unittest.main()
