from pathlib import Path
import tempfile
import unittest

from wolf.backend.cadence_genus_setup import (
    design_setup_path, flow_design_setup_keys, load_design_setup, set_design_setup_value,
    set_design_setup_value_preserving_comments, write_design_setup,
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

    def test_a_top_level_key_is_recognized_whether_commented_or_not(self):
        """The same depth-aware top-level-key pattern
        `_stanza_bounds` relies on (so a key's declaration is
        recognized consistently everywhere) -- in practice a flow's
        own template is always fully commented, but a live key line
        is still a real top-level key declaration, not a continuation
        line, and must not be missed."""
        self.path.write_text("design_flow_effort: extreme\n", encoding="utf-8")
        self.assertEqual(flow_design_setup_keys(self.path), frozenset({"design_flow_effort"}))

    def test_a_deeply_indented_commented_line_is_not_a_top_level_key(self):
        """Two or more spaces between a leading `#` and the key name
        (or any indentation at all with no `#`) is a nested/
        continuation line, never another top-level key -- confirmed
        real need: a mapping-valued key's own commented example
        (`clock_routing_width_multiplier`'s layer-range sub-key) must
        not be mistaken for a second top-level key."""
        self.path.write_text(
            "# clock_routing_width_multiplier:\n"
            "#  M4:M3: 2.0\n",
            encoding="utf-8",
        )
        self.assertEqual(
            flow_design_setup_keys(self.path), frozenset({"clock_routing_width_multiplier"}),
        )


class SetDesignSetupValuePreservingCommentsTests(unittest.TestCase):
    """set_design_setup_value_preserving_comments -- the same set/unset
    semantics as set_design_setup_value, but editing the file's own
    text in place: only the one key's own stanza is ever replaced,
    every other line (including a user's own added comments) stays
    byte-for-byte untouched, in its original order."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-design-setup-preserve-")
        self.path = Path(self.temporary.name) / "setup.demo.yaml"

    def tearDown(self):
        self.temporary.cleanup()

    def test_no_file_at_all_falls_back_to_a_plain_write(self):
        set_design_setup_value_preserving_comments(self.path, "cts_max_fanout", 16)
        self.assertEqual(load_design_setup(self.path), {"cts_max_fanout": 16})

    def test_setting_a_commented_key_uncomments_it_in_place(self):
        self.path.write_text(
            "# A description of this key.\n"
            "# integer. Default: unset.\n"
            "# cts_max_fanout: 16\n"
            "\n"
            "# A different key's own description.\n"
            "# boolean. Default: false.\n"
            "# export_spef: true\n",
            encoding="utf-8",
        )
        set_design_setup_value_preserving_comments(self.path, "cts_max_fanout", 16)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# A description of this key.\n", text)
        self.assertIn("cts_max_fanout: 16\n", text)
        self.assertNotIn("# cts_max_fanout: 16", text)
        # The unrelated key's own stanza (and its description) is
        # completely untouched.
        self.assertIn("# A different key's own description.\n", text)
        self.assertIn("# export_spef: true\n", text)

    def test_setting_a_list_valued_key_replaces_only_its_own_continuation_lines(self):
        self.path.write_text(
            "# Cell names.\n"
            "# list. Default: [].\n"
            "# add_fillers_cells:\n"
            "#  - <cell_name>\n"
            "\n"
            "# Another key.\n"
            "# export_spef: true\n",
            encoding="utf-8",
        )
        set_design_setup_value_preserving_comments(
            self.path, "add_fillers_cells", ["FILL1", "FILL2"],
        )
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(
            load_design_setup(self.path)["add_fillers_cells"], ["FILL1", "FILL2"],
        )
        self.assertIn("# Another key.\n", text)
        self.assertIn("# export_spef: true\n", text)

    def test_unsetting_recomments_the_live_stanza_instead_of_deleting_it(self):
        self.path.write_text("cts_max_fanout: 16\nexport_spef: true\n", encoding="utf-8")
        set_design_setup_value_preserving_comments(self.path, "cts_max_fanout", None)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# cts_max_fanout: 16", text)
        self.assertIn("export_spef: true", text)
        self.assertEqual(load_design_setup(self.path), {"export_spef": True})

    def test_unsetting_a_nested_sub_key_keeps_the_sibling_live(self):
        self.path.write_text(
            "active_views:\n  setup:\n  - wcl\n  hold:\n  - bc\n", encoding="utf-8",
        )
        set_design_setup_value_preserving_comments(self.path, "active_views.setup", None)
        self.assertEqual(load_design_setup(self.path), {"active_views": {"hold": ["bc"]}})

    def test_a_key_with_no_stanza_at_all_is_appended(self):
        self.path.write_text("export_spef: true\n", encoding="utf-8")
        set_design_setup_value_preserving_comments(self.path, "cts_max_fanout", 16)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("export_spef: true", text)
        self.assertEqual(load_design_setup(self.path)["cts_max_fanout"], 16)

    def test_a_hand_added_comment_elsewhere_in_the_file_survives(self):
        self.path.write_text(
            "# My own note about this design.\n"
            "cts_max_fanout: 16\n"
            "# Another note.\n"
            "export_spef: true\n",
            encoding="utf-8",
        )
        set_design_setup_value_preserving_comments(self.path, "cts_max_fanout", 32)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# My own note about this design.\n", text)
        self.assertIn("# Another note.\n", text)
        self.assertEqual(load_design_setup(self.path)["cts_max_fanout"], 32)

    def test_a_flow_declared_extra_key_round_trips(self):
        set_design_setup_value_preserving_comments(
            self.path, "design_flow_effort", "extreme",
            extra_keys=frozenset({"design_flow_effort"}),
        )
        self.assertEqual(
            load_design_setup(self.path, extra_keys=frozenset({"design_flow_effort"})),
            {"design_flow_effort": "extreme"},
        )

    def test_an_unsupported_key_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported setup.yaml key: 'bogus'"):
            set_design_setup_value_preserving_comments(self.path, "bogus", 1)
