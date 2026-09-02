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


if __name__ == "__main__":
    unittest.main()
