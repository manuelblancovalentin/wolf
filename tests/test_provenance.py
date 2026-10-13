from pathlib import Path
import stat
import tempfile
import unittest

import yaml

from wolf.provenance import RUN_MANIFEST_FILENAME, freeze_run_manifest


class RunProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-provenance-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "planned.yaml"
        self.source.write_text(yaml.safe_dump({
            "schema": "wolf.resolved-run/v1",
            "environment": "golden",
            "design": {"package": "rtl/ibex", "name": "ibex", "top": "ibex_core"},
            "technology": {"package": "pdk/asap7", "name": "asap7"},
            "flow": {"package": "flow/orfs", "name": "orfs"},
            "backend": {"name": "orfs", "overrides": {}},
            "packages": [
                {"id": "rtl/ibex", "revision": "fixed-revision", "source_revision": "source-revision"}
            ],
            "workspace": {"root": str(self.root / "work"), "run_directory": "prospective"},
            "generated": {"directory": "planned"},
        }, sort_keys=False), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_freezes_exact_allocation_and_execution_metadata(self):
        run = self.root / "work" / "ibex" / "ibex.asap7" / "ibex.3"
        generated = run / "backend" / "orfs"
        destination = freeze_run_manifest(
            self.source,
            run,
            executor="container",
            runtime="podman",
            container_image="example/orfs@sha256:fixed",
            generated_directory=generated,
            generated_files={"design_config": str(generated / "config.mk")},
        )
        self.assertEqual(destination, run / RUN_MANIFEST_FILENAME)
        frozen = yaml.safe_load(destination.read_text(encoding="utf-8"))
        self.assertEqual(frozen["workspace"]["run_directory"], str(run))
        self.assertEqual(frozen["environment"], "golden")
        self.assertEqual(frozen["packages"][0]["revision"], "fixed-revision")
        self.assertEqual(frozen["packages"][0]["source_revision"], "source-revision")
        self.assertEqual(frozen["execution"]["runtime"], "podman")
        self.assertEqual(frozen["execution"]["container_image"], "example/orfs@sha256:fixed")
        self.assertEqual(frozen["generated"]["directory"], str(generated))
        self.assertFalse(destination.stat().st_mode & stat.S_IWUSR)

    def test_identical_continuation_reuses_but_changed_context_cannot_overwrite(self):
        run = self.root / "run"
        destination = freeze_run_manifest(self.source, run)
        original = destination.read_bytes()
        self.assertEqual(freeze_run_manifest(self.source, run), destination)

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["packages"][0]["revision"] = "later-revision"
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different immutable provenance"):
            freeze_run_manifest(self.source, run)
        self.assertEqual(destination.read_bytes(), original)

    def test_volatile_keys_allow_updating_in_place_when_identity_is_unchanged(self):
        """A run is a durable identity that may accumulate append-only
        executions (a later -from/-to, say) -- a key explicitly named
        volatile is allowed to differ between invocations of the *same*
        run without that being mistaken for a different run."""
        run = self.root / "run"
        destination = freeze_run_manifest(self.source, run, volatile_keys=("backend",))
        self.assertFalse(destination.stat().st_mode & stat.S_IWUSR)

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["backend"] = {"name": "orfs", "overrides": {"make": {"THREADS": "8"}}}
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        updated = freeze_run_manifest(self.source, run, volatile_keys=("backend",))
        self.assertEqual(updated, destination)
        frozen = yaml.safe_load(destination.read_text(encoding="utf-8"))
        self.assertEqual(frozen["backend"]["overrides"], {"make": {"THREADS": "8"}})
        # Still read-only after being updated in place.
        self.assertFalse(destination.stat().st_mode & stat.S_IWUSR)

    def test_volatile_keys_still_reject_a_real_identity_change(self):
        run = self.root / "run"
        freeze_run_manifest(self.source, run, volatile_keys=("backend",))

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["packages"][0]["revision"] = "later-revision"
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different immutable provenance"):
            freeze_run_manifest(self.source, run, volatile_keys=("backend",))

    def test_a_field_added_since_the_run_was_first_frozen_is_not_a_new_identity(self):
        """Regression: adding resolved["backend"] = {"name": ...} to
        run_genus's manifest (so wolf status can look up which backend a
        run used) must not break continuing a run that was allocated
        before that field existed -- schema growth, not a changed run."""
        run = self.root / "run"
        destination = freeze_run_manifest(self.source, run, volatile_keys=("from_stage",))
        original = yaml.safe_load(destination.read_text(encoding="utf-8"))
        self.assertNotIn("newly_tracked_field", original)

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["newly_tracked_field"] = {"name": "cadence-flowtool"}
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        updated = freeze_run_manifest(self.source, run, volatile_keys=("from_stage",))
        self.assertEqual(updated, destination)
        frozen = yaml.safe_load(destination.read_text(encoding="utf-8"))
        self.assertEqual(frozen["newly_tracked_field"], {"name": "cadence-flowtool"})

    def test_a_field_removed_since_the_run_was_first_frozen_is_still_a_new_identity(self):
        """The reverse must stay strict: a field the schema used to
        record and no longer does is a real change, not growth."""
        run = self.root / "run"
        freeze_run_manifest(self.source, run, volatile_keys=("from_stage",))

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        del data["packages"]
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different immutable provenance"):
            freeze_run_manifest(self.source, run, volatile_keys=("from_stage",))

    def test_a_deduplicated_snapshot_directory_bumping_is_not_a_new_identity(self):
        """Regression, hit for real continuing an actual synthesis run:
        scripts_directory/generated (a deduplicated scripts.<N> snapshot
        of the bundled flow Tcl, and the paths generated_files derives
        from it) legitimately get a new number the moment that Tcl's own
        content changes -- which happens mid-run during active flow
        development (fixing a real bug and continuing the same physical
        run with the fix, not starting over). Must not be mistaken for a
        different run identity, the way an unrelated field changing
        still must be."""
        run = self.root / "run"
        volatile = ("from_stage", "scripts_directory", "generated")
        destination = freeze_run_manifest(
            self.source, run, volatile_keys=volatile,
            generated_directory=run, generated_files={"x": str(run / "scripts.1" / "x.tcl")},
        )

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["scripts_directory"] = str(run / "scripts.2")
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        updated = freeze_run_manifest(
            self.source, run, volatile_keys=volatile,
            generated_directory=run, generated_files={"x": str(run / "scripts.2" / "x.tcl")},
        )
        self.assertEqual(updated, destination)
        frozen = yaml.safe_load(destination.read_text(encoding="utf-8"))
        self.assertEqual(frozen["scripts_directory"], str(run / "scripts.2"))
        self.assertEqual(frozen["generated"]["files"]["x"], str(run / "scripts.2" / "x.tcl"))

    def test_a_volatile_path_tolerates_a_nested_field_changing_without_exempting_its_whole_key(self):
        """Regression, hit for real continuing an actual run into
        floorplan: technology.cell_lefs/technology.rc_files were always
        hardcoded empty for a tracked PDK package before a WOLF bug fix,
        regardless of what the package manifest actually declared, so an
        already-allocated run from before that fix landed could never
        continue -- even though nothing about the run's actual identity
        (which package, which revision, which track/vth) had changed.
        volatile_paths must tolerate exactly that nested field changing
        without exempting the rest of "technology" from comparison."""
        run = self.root / "run"
        destination = freeze_run_manifest(
            self.source, run, volatile_paths=("technology.cell_lefs",),
        )

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["technology"]["cell_lefs"] = ["/pdk/cells.lef"]
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        updated = freeze_run_manifest(
            self.source, run, volatile_paths=("technology.cell_lefs",),
        )
        self.assertEqual(updated, destination)
        frozen = yaml.safe_load(destination.read_text(encoding="utf-8"))
        self.assertEqual(frozen["technology"]["cell_lefs"], ["/pdk/cells.lef"])

    def test_a_volatile_path_still_rejects_a_real_change_elsewhere_in_the_same_key(self):
        """The whole point: volatile_paths is scoped to the one nested
        field named, not a blanket exemption for its containing key -- a
        genuine mid-run PDK package swap (a different field inside the
        same "technology" dict) must still raise."""
        run = self.root / "run"
        freeze_run_manifest(self.source, run, volatile_paths=("technology.cell_lefs",))

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["technology"]["package"] = "pdk/tsmc65"
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different immutable provenance"):
            freeze_run_manifest(self.source, run, volatile_paths=("technology.cell_lefs",))

    def test_volatile_keys_and_volatile_paths_combine(self):
        """Both mechanisms apply together when a caller passes both --
        confirmed real, this is exactly how run_genus's own
        freeze_run_manifest call site uses them (scripts_directory/
        generated as top-level volatile_keys, technology.cell_lefs/
        technology.rc_files as nested volatile_paths, simultaneously)."""
        run = self.root / "run"
        destination = freeze_run_manifest(
            self.source, run,
            volatile_keys=("from_stage",), volatile_paths=("technology.cell_lefs",),
        )

        data = yaml.safe_load(self.source.read_text(encoding="utf-8"))
        data["from_stage"] = "floorplan"
        data["technology"]["cell_lefs"] = ["/pdk/cells.lef"]
        self.source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        updated = freeze_run_manifest(
            self.source, run,
            volatile_keys=("from_stage",), volatile_paths=("technology.cell_lefs",),
        )
        self.assertEqual(updated, destination)
        frozen = yaml.safe_load(destination.read_text(encoding="utf-8"))
        self.assertEqual(frozen["from_stage"], "floorplan")
        self.assertEqual(frozen["technology"]["cell_lefs"], ["/pdk/cells.lef"])


if __name__ == "__main__":
    unittest.main()
