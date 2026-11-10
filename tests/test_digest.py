import json
from pathlib import Path
import tempfile
import unittest

from wolf.backend.cadence_genus import STAGE_ORDER, genus_run_checks, genus_run_qor, stage_attempt_counts
from wolf.context import ResolvedContext, ResolvedTechnology
from wolf.digest import DIGEST_SCHEMA, _SIZE_CAP_BYTES, build_digest, write_digest


def _context(root: Path, **overrides) -> ResolvedContext:
    technology = ResolvedTechnology(
        package="pdk/demo", revision="rev1", name="demo", root=root, metal_stack="M9",
    )
    fields = dict(
        state_root=root, environment_name="demo", environment_directory=root,
        workspace_root=root, design_name="demo_design", process="demo_process",
        backend="cadence-flowtool", run_tag="demo_design.3", run_directory=root / "run",
        values={}, technology=technology,
    )
    fields.update(overrides)
    return ResolvedContext(**fields)


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


class BuildDigestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-digest-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "run"
        self.run_directory.mkdir()
        manifest = {
            "backend": {"name": "cadence-flowtool"},
            "environment": "demo",
        }
        (self.run_directory / "wolf.resolved.yaml").write_text(
            json.dumps(manifest), encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_schema_and_identity_fields(self):
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        self.assertEqual(digest["schema"], DIGEST_SCHEMA)
        self.assertEqual(digest["design"], "demo_design")
        self.assertEqual(digest["process"], "demo_process")
        self.assertEqual(digest["metal_stack"], "M9")
        self.assertEqual(digest["run_number"], "3")

    def test_every_stage_in_order_with_zero_attempts_when_never_reached(self):
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        names = [stage["name"] for stage in digest["stages"]]
        self.assertEqual(tuple(names), STAGE_ORDER)
        for stage in digest["stages"]:
            self.assertEqual(stage["status"], "pending")
            self.assertEqual(stage["attempts"], 0)

    def test_a_retried_stage_reports_its_real_attempt_count(self):
        status_directory = self.run_directory / "flow.status.d"
        status_directory.mkdir()
        for name in ("postroute", "postroute_1", "postroute_2"):
            (status_directory / name).write_text("", encoding="utf-8")
        # genus_run_status with no flow.status file at all reports no
        # states, so the stage still shows "pending" overall -- attempts
        # are independent of whether flow.status itself has caught up.
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        postroute = next(stage for stage in digest["stages"] if stage["name"] == "postroute")
        self.assertEqual(postroute["attempts"], 3)

    def test_an_older_flow_revisions_status_is_marked_inferred_in_the_digest(self):
        (self.run_directory / "flow.status").write_text(
            "{status success time 1700000000 errors {} "
            "steps_run {str some.older.postroute.weird_leaf_name}}\n",
            encoding="utf-8",
        )
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        postroute = next(stage for stage in digest["stages"] if stage["name"] == "postroute")
        self.assertEqual(postroute["status"], "succeeded")
        self.assertTrue(postroute["inferred"])
        other = next(stage for stage in digest["stages"] if stage["name"] == "syn_generic")
        self.assertFalse(other["inferred"])

    def test_a_failed_stage_with_no_attempt_file_still_counts_as_one_attempt(self):
        # infer_stage_results/genus_run_status is the source of "failed"
        # here, not flow.status.d -- a backend too old to write
        # flow.status.d at all must not report zero attempts on a stage
        # that visibly ran.
        from wolf.backend import cadence_flowtool

        original = cadence_flowtool.genus_run_status
        cadence_flowtool.genus_run_status = lambda run_directory: ("", {"block.implementation.postroute.block_start": "failed"})
        try:
            context = _context(self.root, run_directory=self.run_directory)
            digest = build_digest(context, self.run_directory, run_number="3")
        finally:
            cadence_flowtool.genus_run_status = original
        postroute = next(stage for stage in digest["stages"] if stage["name"] == "postroute")
        self.assertEqual(postroute["status"], "failed")
        self.assertEqual(postroute["attempts"], 1)

    def test_a_run_in_progress_has_no_ended_at(self):
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3", started_at="2026-01-01T00:00:00Z")
        self.assertEqual(digest["started_at"], "2026-01-01T00:00:00Z")
        self.assertIsNone(digest["ended_at"])

    def test_qor_metrics_are_tagged_with_their_stage(self):
        _write(
            self.run_directory / "reports" / "postroute" / "area.postroute.rpt",
            "---\ntop_module          10  100.0  50.0  150.0\n",
        )
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        area_metrics = [m for m in digest["metrics"] if m["name"] == "total_area_um2"]
        self.assertEqual(len(area_metrics), 1)
        self.assertEqual(area_metrics[0]["stage"], "postroute")
        self.assertEqual(area_metrics[0]["unit"], "um2")

    def test_drc_and_lvs_checks_are_included(self):
        _write(self.run_directory / "mydesign.geom.rpt", "No DRC violations were found\n")
        _write(
            self.run_directory / "mydesign.conn.rpt",
            "Net A1 no driver\nNet A2 no driver\n\nSummary\n    2 total violation(s)\nEnd Summary\n",
        )
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        self.assertEqual(digest["checks"]["drc"], {"status": "pass", "violations": 0})
        self.assertEqual(digest["checks"]["lvs"], {"status": "fail", "violations": 2})

    def test_a_library_looking_string_never_reaches_the_digest(self):
        _write(
            self.run_directory / "mydesign.conn.rpt",
            "Net LIBRARYNET_99 driven from /asic/Library/foo\n\nSummary\n    1 total violation(s)\nEnd Summary\n",
        )
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        rendered = json.dumps(digest)
        self.assertNotIn("LIBRARYNET_99", rendered)
        self.assertNotIn("/asic/Library", rendered)

    def test_digest_never_exceeds_the_size_cap(self):
        context = _context(self.root, run_directory=self.run_directory)
        digest = build_digest(context, self.run_directory, run_number="3")
        digest["metrics"] = [
            {"name": "total_area_um2", "value": float(i), "unit": "um2", "stage": "postroute"}
            for i in range(5000)
        ]
        from wolf.digest import _trim_to_size_cap

        trimmed = _trim_to_size_cap(digest)
        self.assertLessEqual(len(json.dumps(trimmed, sort_keys=True).encode("utf-8")), _SIZE_CAP_BYTES)


class WriteDigestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-digest-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_writes_atomically_into_the_run_directory(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        write_digest(run_directory, {"schema": DIGEST_SCHEMA}, design_name="demo")
        self.assertTrue((run_directory / "wolf.digest.json").is_file())
        # No stray temp file left behind.
        leftovers = [p for p in run_directory.iterdir() if p.name.startswith(".wolf.digest.json.")]
        self.assertEqual(leftovers, [])

    def test_writes_a_second_real_file_under_the_project_shared_folder(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        project_root = self.root / "project"
        write_digest(
            run_directory, {"schema": DIGEST_SCHEMA, "run_number": "7"},
            project_root=project_root, design_name="demo_design",
        )
        shared_path = project_root / "shared" / "wolf-digests" / "demo_design.7.json"
        self.assertTrue(shared_path.is_file())
        self.assertFalse(shared_path.is_symlink())

    def test_no_project_root_skips_the_shared_copy_cleanly(self):
        run_directory = self.root / "run"
        run_directory.mkdir()
        write_digest(run_directory, {"schema": DIGEST_SCHEMA}, design_name="demo")
        self.assertFalse((self.root / "shared").exists())


if __name__ == "__main__":
    unittest.main()
