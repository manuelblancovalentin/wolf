import json
import re
import unittest

from wolf.catalog import build_catalog

# Paths/hosts that must never appear anywhere in the catalog. Anchored to
# the start so prose that merely contains a slash (e.g. "Genus/Innovus")
# does not false-positive; a real absolute path is the actual risk.
_PATH_LIKE = re.compile(r"^(/[\w.\-]+){2,}")
_ADDRESS_LIKE = re.compile(r"[\w.\-]+@[\w.\-]+|://|:\d{2,5}\b")
_LIBRARY_TREE_HINTS = ("Library", "/ip", "/asic", "raid")

_REQUIRED_VARIABLE_KEYS = {
    "name", "meaning", "type", "source", "required", "scope", "example",
    "visibility", "since",
}
_REQUIRED_PROCESS_KEYS = {
    "name", "purpose", "gating_group", "proj_bundle", "visibility", "since",
}
_REQUIRED_FLOW_KEYS = {"backend", "purpose", "stages", "since"}
_REQUIRED_COMMAND_KEYS = {"command", "purpose"}


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


class CatalogContentTests(unittest.TestCase):
    def setUp(self):
        self.catalog = build_catalog()

    def test_schema_and_version_are_present(self):
        self.assertEqual(self.catalog["schema"], "wolf.catalog/v1")
        self.assertTrue(self.catalog["wolf_version"])

    def test_every_variable_has_the_required_keys(self):
        for variable in self.catalog["variables"]:
            self.assertEqual(_REQUIRED_VARIABLE_KEYS, set(variable))
            self.assertIn(variable["type"], {"text", "choice", "list", "path"})
            self.assertIn(variable["visibility"], {"public", "internal"})

    def test_every_process_has_the_required_keys(self):
        for process in self.catalog["processes"]:
            self.assertEqual(_REQUIRED_PROCESS_KEYS, set(process))
            self.assertIn(process["visibility"], {"public", "internal"})

    def test_every_flow_has_the_required_keys_and_ordered_stages(self):
        for flow in self.catalog["flows"]:
            self.assertEqual(_REQUIRED_FLOW_KEYS, set(flow))
            self.assertTrue(flow["stages"])
            for stage in flow["stages"]:
                self.assertEqual({"name", "tool_suite"}, set(stage))

    def test_every_command_has_the_required_keys(self):
        self.assertTrue(self.catalog["commands"])
        for command in self.catalog["commands"]:
            self.assertEqual(_REQUIRED_COMMAND_KEYS, set(command))
            self.assertTrue(command["command"].startswith("wolf "))

    def test_metal_stack_and_vth_choices_stay_out_of_the_public_bible(self):
        # These names are internal-site-only by rule; the public section
        # (top-level "choices") must not carry real stack/vth value lists
        # that haven't been confirmed safe -- today that means empty.
        self.assertEqual(self.catalog["choices"]["metal_stack"], [])
        self.assertEqual(self.catalog["choices"]["vth"], [])

    def test_internal_process_names_are_marked_internal(self):
        internal_only = {"tsmc65", "tsmc28", "gf22"}
        for process in self.catalog["processes"]:
            if process["name"] in internal_only:
                self.assertEqual(process["visibility"], "internal")

    def test_no_string_in_the_catalog_looks_like_a_library_path(self):
        for text in _walk_strings(self.catalog):
            self.assertNotRegex(
                text, _PATH_LIKE, msg=f"path-shaped string found: {text!r}",
            )
            for hint in _LIBRARY_TREE_HINTS:
                self.assertNotIn(
                    hint, text, msg=f"library-tree hint {hint!r} found in: {text!r}",
                )

    def test_no_string_in_the_catalog_looks_like_an_address(self):
        for text in _walk_strings(self.catalog):
            self.assertNotRegex(
                text, _ADDRESS_LIKE, msg=f"address-shaped string found: {text!r}",
            )


class CatalogJsonTests(unittest.TestCase):
    def test_is_valid_json_round_trip(self):
        data = build_catalog()
        reparsed = json.loads(json.dumps(data))
        self.assertEqual(data, reparsed)


if __name__ == "__main__":
    unittest.main()
