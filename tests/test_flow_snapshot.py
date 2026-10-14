from pathlib import Path
import tempfile
import unittest

from wolf.flow_snapshot import content_digest, flows_directory, snapshot_flow


class ContentDigestTests(unittest.TestCase):
    def test_digest_is_order_independent(self):
        a = content_digest({"one.tcl": "a", "two.tcl": "b"})
        b = content_digest({"two.tcl": "b", "one.tcl": "a"})
        self.assertEqual(a, b)

    def test_digest_changes_with_content(self):
        a = content_digest({"one.tcl": "a"})
        b = content_digest({"one.tcl": "a2"})
        self.assertNotEqual(a, b)


class SnapshotFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-flow-snapshot-test-")
        self.project_root = Path(self.temporary.name)
        self.design_name = "demo"

    def tearDown(self):
        self.temporary.cleanup()

    def _snapshot(self, files, step_digests=None):
        return snapshot_flow(self.project_root, self.design_name, files, step_digests or {})

    def test_first_snapshot_creates_flow_1_with_checksum_and_changelog_header(self):
        result = self._snapshot({"a.tcl": "puts a\n"}, {"step_a": "abc123"})
        self.assertTrue(result.created)
        self.assertEqual(result.version, 1)
        self.assertEqual(result.changed_steps, ())
        base = flows_directory(self.project_root, self.design_name)
        self.assertEqual(result.directory, base / "flow.1")
        self.assertTrue((base / "flow.1" / "a.tcl").is_file())
        self.assertTrue((base / "flow.1" / "flow.sha256checksum").is_file())
        self.assertEqual((base / "flow.latest").resolve(), (base / "flow.1").resolve())
        changelog = (base / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("| 1 |", changelog)
        self.assertIn("(initial snapshot)", changelog)

    def test_unchanged_content_is_a_noop_second_call(self):
        self._snapshot({"a.tcl": "puts a\n"}, {"step_a": "abc123"})
        result = self._snapshot({"a.tcl": "puts a\n"}, {"step_a": "abc123"})
        self.assertFalse(result.created)
        self.assertEqual(result.version, 1)
        base = flows_directory(self.project_root, self.design_name)
        self.assertFalse((base / "flow.2").exists())

    def test_changed_content_cuts_flow_2_and_reports_changed_steps(self):
        self._snapshot({"a.tcl": "puts a\n"}, {"step_a": "abc123", "step_b": "same"})
        result = self._snapshot(
            {"a.tcl": "puts a2\n"}, {"step_a": "def456", "step_b": "same"},
        )
        self.assertTrue(result.created)
        self.assertEqual(result.version, 2)
        self.assertEqual(result.changed_steps, ("step_a",))
        base = flows_directory(self.project_root, self.design_name)
        self.assertTrue((base / "flow.2" / "a.tcl").is_file())
        self.assertEqual(
            (base / "flow.2" / "a.tcl").read_text(encoding="utf-8"), "puts a2\n",
        )
        changelog = (base / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("| 2 |", changelog)
        self.assertIn("step_a", changelog)
        self.assertEqual((base / "flow.latest").resolve(), (base / "flow.2").resolve())

    def test_added_and_removed_steps_are_reported_as_changed(self):
        self._snapshot({"a.tcl": "x\n"}, {"step_a": "abc"})
        result = self._snapshot({"a.tcl": "x2\n"}, {"step_b": "def"})
        self.assertEqual(result.changed_steps, ("step_a", "step_b"))
