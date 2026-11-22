from pathlib import Path
import unittest
from unittest import mock
import urllib.error

from wolf import __version__
from wolf.upgrade import (
    UpgradeError, _is_newer, _parse_version, _version_from_tag, check_latest, download_and_install,
)


class VersionParsingTests(unittest.TestCase):
    def test_a_plain_release_version_parses_to_a_tuple(self):
        self.assertEqual(_parse_version("0.1.0"), (0, 1, 0))

    def test_a_dev_suffix_is_ignored(self):
        self.assertEqual(_parse_version("0.1.0.dev1"), (0, 1, 0))

    def test_something_with_no_leading_digits_parses_as_zero(self):
        self.assertEqual(_parse_version("unknown"), (0,))

    def test_a_v_prefixed_tag_loses_its_v(self):
        self.assertEqual(_version_from_tag("v0.2.0"), "0.2.0")

    def test_a_tag_with_no_v_prefix_is_unchanged(self):
        self.assertEqual(_version_from_tag("0.2.0"), "0.2.0")

    def test_is_newer_compares_numerically_not_lexically(self):
        self.assertTrue(_is_newer("0.10.0", "0.9.0"))
        self.assertFalse(_is_newer("0.9.0", "0.10.0"))

    def test_is_newer_is_false_for_the_same_version(self):
        self.assertFalse(_is_newer("0.1.0", "0.1.0"))


class CheckLatestTests(unittest.TestCase):
    def test_a_newer_tag_is_reported_as_newer(self):
        release = {"tag_name": "v99.0.0"}
        installed, latest, is_newer = check_latest(fetch_latest_release=lambda: release)
        self.assertEqual(installed, __version__)
        self.assertEqual(latest, "99.0.0")
        self.assertTrue(is_newer)

    def test_the_same_tag_as_installed_is_not_newer(self):
        release = {"tag_name": f"v{__version__}"}
        _, _, is_newer = check_latest(fetch_latest_release=lambda: release)
        self.assertFalse(is_newer)

    def test_a_release_with_no_tag_name_raises(self):
        with self.assertRaises(UpgradeError):
            check_latest(fetch_latest_release=lambda: {})

    def test_a_fetch_failure_propagates_as_upgrade_error(self):
        def fail():
            raise UpgradeError("cannot reach the releases API: boom")

        with self.assertRaises(UpgradeError):
            check_latest(fetch_latest_release=fail)


class DownloadAndInstallTests(unittest.TestCase):
    def test_downloads_the_wheel_asset_then_installs_it(self):
        release = {
            "tag_name": "v9.9.9",
            "assets": [
                {"name": "not-a-wheel.txt", "browser_download_url": "https://example.invalid/not-a-wheel.txt"},
                {"name": "wolf_eda-9.9.9-py3-none-any.whl",
                 "browser_download_url": "https://example.invalid/wolf_eda-9.9.9-py3-none-any.whl"},
            ],
        }
        downloaded = {}
        installed = {}

        def fake_download(url, destination):
            downloaded["url"] = url
            downloaded["destination"] = destination
            Path(destination).write_bytes(b"fake wheel content")

        def fake_pip_install(wheel_path):
            installed["path"] = wheel_path
            self.assertTrue(Path(wheel_path).is_file())

        version = download_and_install(
            fetch_latest_release=lambda: release, download=fake_download, pip_install=fake_pip_install,
        )
        self.assertEqual(version, "9.9.9")
        self.assertEqual(downloaded["url"], "https://example.invalid/wolf_eda-9.9.9-py3-none-any.whl")
        self.assertEqual(downloaded["destination"].name, "wolf_eda-9.9.9-py3-none-any.whl")
        self.assertEqual(installed["path"], downloaded["destination"])

    def test_no_wheel_asset_raises_before_downloading_anything(self):
        release = {"tag_name": "v9.9.9", "assets": [{"name": "source.tar.gz", "browser_download_url": "https://x"}]}
        download = mock.Mock()
        with self.assertRaises(UpgradeError):
            download_and_install(fetch_latest_release=lambda: release, download=download)
        download.assert_not_called()

    def test_an_asset_with_no_download_url_raises(self):
        release = {"tag_name": "v9.9.9", "assets": [{"name": "wolf.whl"}]}
        with self.assertRaises(UpgradeError):
            download_and_install(fetch_latest_release=lambda: release)

    def test_the_scratch_wheel_directory_is_cleaned_up_either_way(self):
        release = {
            "tag_name": "v9.9.9",
            "assets": [{"name": "wolf.whl", "browser_download_url": "https://example.invalid/wolf.whl"}],
        }
        captured_dir = {}

        def fake_download(url, destination):
            captured_dir["path"] = destination.parent
            Path(destination).write_bytes(b"x")

        download_and_install(fetch_latest_release=lambda: release, download=fake_download, pip_install=lambda p: None)
        self.assertFalse(captured_dir["path"].exists())


class DefaultFetchTests(unittest.TestCase):
    """The real urllib-based fetcher, with urlopen itself faked out --
    never touches the network."""

    def test_a_url_error_is_wrapped_as_upgrade_error(self):
        from wolf.upgrade import _default_fetch_latest_release

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
            with self.assertRaises(UpgradeError):
                _default_fetch_latest_release()

    def test_a_valid_response_is_parsed_as_json(self):
        from wolf.upgrade import _default_fetch_latest_release

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"tag_name": "v1.2.3"}'

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = _default_fetch_latest_release()
        self.assertEqual(result["tag_name"], "v1.2.3")

    def test_invalid_json_is_wrapped_as_upgrade_error(self):
        from wolf.upgrade import _default_fetch_latest_release

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"not json"

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaises(UpgradeError):
                _default_fetch_latest_release()


if __name__ == "__main__":
    unittest.main()
