from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wolf.cell_browser import (
    CellInfo, analysis_view_names_for_technology, cells_for_technology,
    routing_layers_for_technology,
)
from wolf.context import ResolvedTechnology, ResolvedTimingCorner

# Synthetic LEF content only -- made-up cell/layer names, never real PDK data.
_FAKE_LEF = """\
VERSION 5.8 ;
MACRO FAKEBUFX2
  CLASS CORE ;
  SIZE 1.5 BY 2.0 ;
END FAKEBUFX2
MACRO FAKEINVX1
  CLASS CORE ;
  SIZE 0.8 BY 2.0 ;
END FAKEINVX1
MACRO FAKETIEHIX1
  CLASS CORE ;
  SIZE 0.5 BY 2.0 ;
END FAKETIEHIX1
LAYER METAL1
  TYPE ROUTING ;
END METAL1
LAYER VIA12
  TYPE CUT ;
END VIA12
LAYER METAL2
  TYPE ROUTING ;
END METAL2
"""


class CellBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-cell-browser-")
        self.root = Path(self.temporary.name)
        self.lef = self.root / "fake_tech.lef"
        self.lef.write_text(_FAKE_LEF, encoding="utf-8")
        self.cache = self.root / "cache"
        self.patcher = patch("wolf.cell_browser.cache_dir", return_value=self.cache)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temporary.cleanup()

    def _technology(self, **overrides) -> ResolvedTechnology:
        fields = dict(
            package="pdk/faketech", revision="1", name="faketech", root=self.root,
            technology_lefs=(self.lef,),
        )
        fields.update(overrides)
        return ResolvedTechnology(**fields)

    def test_no_technology_returns_none(self):
        self.assertIsNone(cells_for_technology(None))
        self.assertIsNone(routing_layers_for_technology(None))
        self.assertIsNone(analysis_view_names_for_technology(None))

    def test_technology_with_no_lef_returns_none(self):
        technology = self._technology(technology_lefs=(), cell_lefs=())
        self.assertIsNone(cells_for_technology(technology))
        self.assertIsNone(routing_layers_for_technology(technology))

    def test_cell_names_and_area_are_extracted(self):
        cells = cells_for_technology(self._technology())
        self.assertEqual(
            {cell.name: cell.area for cell in cells},
            {"FAKEBUFX2": 3.0, "FAKEINVX1": 1.6, "FAKETIEHIX1": 1.0},
        )

    def test_only_routing_type_layers_are_extracted(self):
        layers = routing_layers_for_technology(self._technology())
        self.assertEqual(layers, ["METAL1", "METAL2"])
        self.assertNotIn("VIA12", layers)

    def test_second_call_reuses_the_cache_without_rescanning(self):
        technology = self._technology()
        first = cells_for_technology(technology)
        original_mtime = self.lef.stat().st_mtime_ns
        # Corrupt the real file but preserve its mtime -- the cache key is
        # (identity, each file's own mtime), so this isolates "same
        # resolved file set, cache reused" from mtime-based invalidation
        # (covered separately below) rather than conflating the two.
        self.lef.write_text("not valid lef at all", encoding="utf-8")
        import os
        os.utime(self.lef, ns=(original_mtime, original_mtime))
        second = cells_for_technology(technology)
        self.assertEqual(first, second)
        cache_files = list((self.cache / "cells" / "macros").glob("*.json"))
        self.assertEqual(len(cache_files), 1)

    def test_cache_is_written_under_the_state_cache_dir_not_the_project(self):
        cells_for_technology(self._technology())
        cache_files = list((self.cache / "cells" / "macros").glob("*.json"))
        self.assertEqual(len(cache_files), 1)
        content = cache_files[0].read_text(encoding="utf-8")
        # Only names/areas -- never the source LEF's own path or content.
        self.assertNotIn(str(self.lef), content)
        self.assertIn("FAKEBUFX2", content)

    def test_a_changed_file_mtime_invalidates_the_cache(self):
        technology = self._technology()
        cells_for_technology(technology)
        self.lef.write_text(_FAKE_LEF + "MACRO FAKENEWCELL\n  SIZE 1.0 BY 1.0 ;\nEND FAKENEWCELL\n",
                             encoding="utf-8")
        import os
        os.utime(self.lef, None)
        names = {cell.name for cell in cells_for_technology(technology)}
        self.assertIn("FAKENEWCELL", names)

    def test_analysis_view_names_come_from_resolved_timing_corners(self):
        technology = self._technology(timing_corners=(
            ResolvedTimingCorner(name="faketypical", libraries=()),
            ResolvedTimingCorner(name="fakeworst", libraries=()),
        ))
        self.assertEqual(
            analysis_view_names_for_technology(technology), ["faketypical", "fakeworst"],
        )

    def test_on_file_is_called_on_a_real_scan_but_not_on_a_cache_hit(self):
        technology = self._technology()
        calls = []
        cells_for_technology(technology, on_file=calls.append)
        self.assertEqual(calls, [self.lef])
        calls.clear()
        cells_for_technology(technology, on_file=calls.append)
        self.assertEqual(calls, [])

    def test_no_timing_corners_returns_none(self):
        self.assertIsNone(analysis_view_names_for_technology(self._technology()))


if __name__ == "__main__":
    unittest.main()
