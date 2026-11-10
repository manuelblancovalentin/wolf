import json
from pathlib import Path
import tempfile
import unittest

from wolf.backend.cadence_genus import genus_run_checks, stage_attempt_counts


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class StageAttemptCountsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-digest-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_no_status_directory_is_empty(self):
        self.assertEqual(stage_attempt_counts(self.root), {})

    def test_a_single_attempt_counts_as_one(self):
        directory = self.root / "flow.status.d"
        directory.mkdir()
        (directory / "postroute").write_text("", encoding="utf-8")
        self.assertEqual(stage_attempt_counts(self.root), {"postroute": 1})

    def test_retries_count_the_bare_name_plus_each_suffix(self):
        directory = self.root / "flow.status.d"
        directory.mkdir()
        for name in ("postroute", "postroute_1", "postroute_2", "postroute_3", "postroute_4"):
            (directory / name).write_text("", encoding="utf-8")
        self.assertEqual(stage_attempt_counts(self.root), {"postroute": 5})

    def test_a_name_that_is_not_a_known_stage_is_ignored(self):
        directory = self.root / "flow.status.d"
        directory.mkdir()
        (directory / "not_a_real_stage").write_text("", encoding="utf-8")
        (directory / "postroute").write_text("", encoding="utf-8")
        self.assertEqual(stage_attempt_counts(self.root), {"postroute": 1})


class CheckReportParsingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-digest-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    # Shapes below mirror a real run's masked geom.rpt/conn.rpt layout
    # (words/numbers/ids replaced, never the real report text).

    def test_the_confirmed_real_clean_geom_report_is_a_pass(self):
        _write(
            self.root / "mydesign.geom.rpt",
            "###############################################################\n"
            "# header lines only\n"
            "###############################################################\n"
            "\n"
            "No DRC violations were found\n",
        )
        self.assertEqual(genus_run_checks(self.root), {"drc": {"status": "pass", "violations": 0}})

    def test_an_unconfirmed_nonzero_geom_report_still_parses(self):
        _write(self.root / "mydesign.geom.rpt", "3 DRC violations were found\n")
        self.assertEqual(genus_run_checks(self.root), {"drc": {"status": "fail", "violations": 3}})

    def test_an_unrecognized_geom_report_contributes_nothing(self):
        _write(self.root / "mydesign.geom.rpt", "nothing this parser recognizes\n")
        self.assertEqual(genus_run_checks(self.root), {})

    def test_a_conn_report_with_a_total_summary_line_uses_that_count(self):
        _write(
            self.root / "mydesign.conn.rpt",
            "Verify Connectivity Report is clean on some design\n"
            "\n"
            "Summary\n"
            "    0 total violation(s)\n"
            "End Summary\n",
        )
        self.assertEqual(genus_run_checks(self.root), {"lvs": {"status": "pass", "violations": 0}})

    def test_a_conn_report_with_net_lines_and_a_nonzero_total_is_a_fail(self):
        _write(
            self.root / "mydesign.conn.rpt",
            "Verify Connectivity Report is dirty on some design\n"
            "\n"
            "Net A1 no driver\n"
            "Net A2 dangling Wire at (0, 0) (1, 1) on M1\n"
            "\n"
            "Summary\n"
            "    2 total violation(s)\n"
            "End Summary\n",
        )
        self.assertEqual(genus_run_checks(self.root), {"lvs": {"status": "fail", "violations": 2}})

    def test_a_conn_report_with_no_total_line_falls_back_to_counting_net_lines(self):
        _write(
            self.root / "mydesign.conn.rpt",
            "Verify Connectivity Report is dirty on some design\n"
            "Net A1 no driver\n"
            "Net A2 dangling Wire at (0, 0) (1, 1) on M1\n"
            "Net A3 dangling Wire at (0, 0) (1, 1) on M1\n",
        )
        self.assertEqual(genus_run_checks(self.root), {"lvs": {"status": "fail", "violations": 3}})

    def test_a_conn_report_with_neither_shape_contributes_nothing(self):
        _write(self.root / "mydesign.conn.rpt", "nothing this parser recognizes\n")
        self.assertEqual(genus_run_checks(self.root), {})

    def test_a_library_looking_line_never_reaches_the_result(self):
        # A planted library-shaped string in the report must never
        # surface anywhere in the parsed result -- only the violation
        # count/status, never report text.
        _write(
            self.root / "mydesign.conn.rpt",
            "Net LIBRARYNET_42 no driver at /asic/Library/not/real\n"
            "\n"
            "Summary\n"
            "    1 total violation(s)\n"
            "End Summary\n",
        )
        result = genus_run_checks(self.root)
        self.assertEqual(result, {"lvs": {"status": "fail", "violations": 1}})
        self.assertNotIn("LIBRARYNET_42", json.dumps(result))
        self.assertNotIn("/asic/Library", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
