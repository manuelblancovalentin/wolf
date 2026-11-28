from pathlib import Path
import tempfile
import unittest

from wolf.backend.cadence_genus_setup import (
    design_setup_path, flow_design_setup_keys, load_design_setup, set_design_setup_value,
    write_design_setup,
)


class DesignSetupPathTests(unittest.TestCase):
    def test_path_is_under_inputs_env_design(self):
        self.assertEqual(
            design_setup_path(Path("/proj"), "demo"),
            Path("/proj/inputs/env/demo/setup.demo.yaml"),
        )


class LoadDesignSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-design-setup-")
        self.path = Path(self.temporary.name) / "setup.demo.yaml"

    def tearDown(self):
        self.temporary.cleanup()

    def test_missing_file_is_empty_mapping(self):
        self.assertEqual(load_design_setup(self.path), {})

    def test_unknown_top_level_key_is_rejected(self):
        self.path.write_text("bogus_key: 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported setup.yaml key: bogus_key"):
            load_design_setup(self.path)

    def test_non_mapping_content_is_rejected(self):
        self.path.write_text("- a\n- b\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be a YAML mapping"):
            load_design_setup(self.path)

    def test_known_keys_round_trip(self):
        write_design_setup(self.path, {"add_tieoffs_cells": ["TIEHIX1", "TIELOX1"]})
        self.assertEqual(
            load_design_setup(self.path), {"add_tieoffs_cells": ["TIEHIX1", "TIELOX1"]},
        )

    def test_a_flow_declared_extra_key_is_accepted_when_passed(self):
        self.path.write_text("design_flow_effort: extreme\n", encoding="utf-8")
        self.assertEqual(
            load_design_setup(self.path, extra_keys=frozenset({"design_flow_effort"})),
            {"design_flow_effort": "extreme"},
        )

    def test_a_flow_declared_extra_key_is_still_rejected_without_it(self):
        self.path.write_text("design_flow_effort: extreme\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported setup.yaml key: design_flow_effort"):
            load_design_setup(self.path)


class WriteDesignSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-design-setup-")
        self.path = Path(self.temporary.name) / "nested" / "setup.demo.yaml"

    def tearDown(self):
        self.temporary.cleanup()

    def test_write_creates_parent_directories(self):
        write_design_setup(self.path, {"cts_buffer_cells": ["BUFX*"]})
        self.assertTrue(self.path.is_file())

    def test_write_rejects_unknown_key(self):
        with self.assertRaisesRegex(ValueError, "unsupported setup.yaml key"):
            write_design_setup(self.path, {"bogus": 1})

    def test_write_leaves_no_tmp_file_behind(self):
        write_design_setup(self.path, {"cts_buffer_cells": ["BUFX*"]})
        self.assertFalse(self.path.with_suffix(".yaml.tmp").exists())


class SetDesignSetupValueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-design-setup-")
        self.path = Path(self.temporary.name) / "setup.demo.yaml"

    def tearDown(self):
        self.temporary.cleanup()

    def test_set_a_flat_key(self):
        set_design_setup_value(self.path, "add_tieoffs_max_fanout", 10)
        self.assertEqual(load_design_setup(self.path), {"add_tieoffs_max_fanout": 10})

    def test_set_a_nested_key_creates_parents(self):
        set_design_setup_value(self.path, "active_views.setup", ["wcl"])
        self.assertEqual(load_design_setup(self.path), {"active_views": {"setup": ["wcl"]}})

    def test_set_a_second_nested_sibling_key_preserves_the_first(self):
        set_design_setup_value(self.path, "active_views.setup", ["wcl"])
        set_design_setup_value(self.path, "active_views.hold", ["bc"])
        self.assertEqual(
            load_design_setup(self.path), {"active_views": {"setup": ["wcl"], "hold": ["bc"]}},
        )

    def test_unset_a_nested_key_prunes_the_now_empty_parent(self):
        set_design_setup_value(self.path, "active_views.setup", ["wcl"])
        set_design_setup_value(self.path, "active_views.setup", None)
        self.assertEqual(load_design_setup(self.path), {})

    def test_unset_a_nested_key_keeps_a_nonempty_parent(self):
        set_design_setup_value(self.path, "active_views.setup", ["wcl"])
        set_design_setup_value(self.path, "active_views.hold", ["bc"])
        set_design_setup_value(self.path, "active_views.setup", None)
        self.assertEqual(load_design_setup(self.path), {"active_views": {"hold": ["bc"]}})

    def test_unset_a_key_that_is_not_set_is_a_noop(self):
        set_design_setup_value(self.path, "add_tieoffs_max_fanout", None)
        self.assertEqual(load_design_setup(self.path), {})

    def test_unsupported_top_level_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported setup.yaml key: 'bogus'"):
            set_design_setup_value(self.path, "bogus.nested", 1)

    def test_empty_key_segment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid setup key"):
            set_design_setup_value(self.path, "active_views.", 1)

    def test_a_flow_declared_extra_key_is_accepted_when_passed(self):
        set_design_setup_value(
            self.path, "design_flow_effort", "extreme",
            extra_keys=frozenset({"design_flow_effort"}),
        )
        self.assertEqual(
            load_design_setup(self.path, extra_keys=frozenset({"design_flow_effort"})),
            {"design_flow_effort": "extreme"},
        )

    def test_a_flow_declared_extra_key_is_rejected_without_it(self):
        with self.assertRaisesRegex(ValueError, "unsupported setup.yaml key: 'design_flow_effort'"):
            set_design_setup_value(self.path, "design_flow_effort", "extreme")


class FlowDesignSetupKeysTests(unittest.TestCase):
    """flow_design_setup_keys -- extracting a flow's own extra
    design-setup key names from its commented template, by a narrow
    regex over `# key: ...` lines, never a full YAML parse (the
    template also has plain prose description lines that aren't valid
    YAML once merely uncommented)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-flow-design-setup-")
        self.path = Path(self.temporary.name) / "design_setup.template.yaml"

    def tearDown(self):
        self.temporary.cleanup()

    def test_no_path_at_all_returns_empty(self):
        self.assertEqual(flow_design_setup_keys(None), frozenset())

    def test_a_missing_file_returns_empty(self):
        self.assertEqual(flow_design_setup_keys(self.path), frozenset())

    def test_commented_keys_are_extracted_ignoring_prose_and_examples(self):
        self.path.write_text(
            "#========================================\n"
            "# Design setup template header prose, not a key at all.\n"
            "#========================================\n"
            "# Optimisation effort of synthesis and implementation.\n"
            "# scalar, one of: express | standard | extreme. Default: standard.\n"
            "# design_flow_effort: standard\n"
            "\n"
            "# Hard macros of the project, by name.\n"
            "# list of names. Default: [] (none).\n"
            "# project_macros:\n"
            "#   - <macro_name>\n",
            encoding="utf-8",
        )
        self.assertEqual(
            flow_design_setup_keys(self.path), frozenset({"design_flow_effort", "project_macros"}),
        )

    def test_an_uncommented_line_is_not_treated_as_a_declared_key(self):
        """Only commented `# key: ...` lines count -- this function
        only ever reads a flow's own pristine template (always fully
        commented), never a generated setup.<design>.yaml that may
        have live, uncommented keys of its own."""
        self.path.write_text("design_flow_effort: extreme\n", encoding="utf-8")
        self.assertEqual(flow_design_setup_keys(self.path), frozenset())
