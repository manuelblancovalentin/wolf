from pathlib import Path
import tempfile
import unittest

from wolf.backend.cadence_genus_setup import DESIGN_SETUP_ALLOWED_KEYS, load_design_setup
from wolf.backend.design_setup_template import generate_or_refresh, render_wolf_section


class RenderWolfSectionTests(unittest.TestCase):
    """render_wolf_section -- WOLF's own fully commented section,
    documenting every DESIGN_SETUP_ALLOWED_KEYS key."""

    def test_every_allowed_key_is_documented(self):
        text = render_wolf_section()
        for key in DESIGN_SETUP_ALLOWED_KEYS:
            self.assertIn(f"# {key}:", text, key)

    def test_every_key_line_is_commented_out(self):
        text = render_wolf_section()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            self.assertTrue(stripped.startswith("#"), f"not commented out: {line!r}")

    def test_no_cell_names_anywhere(self):
        """Cell-valued keys get a shape + placeholder, never a real
        cell name -- the file lives in the project tree and is tracked
        in git (handoff point 4)."""
        text = render_wolf_section()
        self.assertIn("<cell_name>", text)
        # No real foundry-specific cell name markers ever appear
        # anywhere in the generated text (a generic illustrative
        # pattern like a bare "<prefix>*" placeholder is fine).
        for marker in ("TIEHIX", "TIELOX", "BWP", "tcbn"):
            self.assertNotIn(marker, text)

    def test_every_keys_own_stanza_parses_once_uncommented(self):
        """Each key's own stanza (description/shape/default lines
        excluded, just its `key: value` and any continuation lines),
        once uncommented, is valid YAML holding exactly that one key --
        confirms the generated shape itself is internally correct, not
        just the real flow template this was built against."""
        import yaml

        from wolf.backend.design_setup_template import _KEY_SPECS, _render_key_stanza

        # _render_key_stanza's own last lines (from the "key: ..."
        # line onward) are always the key's value/opening line plus
        # its only possible continuation lines.
        for spec in _KEY_SPECS:
            stanza_lines = _render_key_stanza(spec, None).splitlines()
            key_line_index = next(
                index for index, line in enumerate(stanza_lines)
                if line.startswith(f"# {spec.key}:")
            )
            uncommented = [line[1:].lstrip() if line[1:2] == " " else line[1:]
                           for line in stanza_lines[key_line_index:]]
            # Re-add the key's own two-space YAML indent for any
            # continuation line (the stanza strips a leading "#" only).
            rebuilt = [stanza_lines[key_line_index][2:]]
            for line in stanza_lines[key_line_index + 1:]:
                rebuilt.append(line[1:])
            document = yaml.safe_load("\n".join(rebuilt))
            self.assertIsInstance(document, dict, spec.key)
            self.assertEqual(set(document), {spec.key}, spec.key)


class GenerateOrRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-design-setup-template-")
        self.root = Path(self.temporary.name)
        self.path = self.root / "setup.demo.yaml"
        self.flow_template = self.root / "flow" / "design_setup.template.yaml"
        self.flow_template.parent.mkdir(parents=True)
        self.flow_template.write_text(
            "# A flow-only knob.\n"
            "# scalar, one of: express | standard. Default: standard.\n"
            "# design_flow_effort: standard\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_missing_file_is_generated_in_full(self):
        generate_or_refresh(self.path)
        self.assertTrue(self.path.is_file())
        text = self.path.read_text(encoding="utf-8")
        for key in DESIGN_SETUP_ALLOWED_KEYS:
            self.assertIn(f"# {key}:", text)

    def test_the_flow_section_is_appended_verbatim_under_its_own_header(self):
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("demoflow", text)
        self.assertIn("# design_flow_effort: standard", text)

    def test_no_flow_template_means_no_flow_section(self):
        generate_or_refresh(self.path)
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("design_flow_effort", text)

    def test_refresh_of_an_already_complete_file_changes_nothing(self):
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        before = self.path.read_text(encoding="utf-8")
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        after = self.path.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_refresh_appends_only_a_genuinely_missing_key(self):
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        text = self.path.read_text(encoding="utf-8")
        stripped = "\n".join(
            line for line in text.splitlines()
            if "cts_max_fanout" not in line and "number (ps)" not in line
        )
        self.path.write_text(stripped, encoding="utf-8")
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        refreshed = self.path.read_text(encoding="utf-8")
        self.assertEqual(refreshed.count("cts_max_fanout"), 1)
        # Every other key stays exactly once -- no duplication of
        # keys that were already present (commented or not).
        self.assertEqual(refreshed.count("active_views"), 1)

    def test_a_hand_added_comment_survives_a_refresh(self):
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        text = self.path.read_text(encoding="utf-8")
        text += "\n# A note I added by hand.\ncts_max_fanout: 16\n"
        self.path.write_text(text, encoding="utf-8")
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        after = self.path.read_text(encoding="utf-8")
        self.assertIn("# A note I added by hand.", after)
        self.assertEqual(load_design_setup(
            self.path, extra_keys=frozenset({"design_flow_effort"}),
        )["cts_max_fanout"], 16)

    def test_a_set_value_is_never_overwritten_by_a_refresh(self):
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        text = self.path.read_text(encoding="utf-8")
        text += "\ncts_max_fanout: 99\n"
        self.path.write_text(text, encoding="utf-8")
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        self.assertEqual(load_design_setup(
            self.path, extra_keys=frozenset({"design_flow_effort"}),
        )["cts_max_fanout"], 99)

    def test_changing_the_flow_template_appends_the_new_section(self):
        """An environment that never had a flow section (no template
        resolvable before) gets it appended once the template becomes
        available, without disturbing anything already there."""
        generate_or_refresh(self.path)
        before = self.path.read_text(encoding="utf-8")
        generate_or_refresh(self.path, flow_template_path=self.flow_template, flow_name="demoflow")
        after = self.path.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before))
        self.assertIn("demoflow", after)


if __name__ == "__main__":
    unittest.main()
