"""Check for, and install, a newer `wolf` release from GitHub.

For anyone who installed `wolf` from a built wheel rather than through the
owner's own `rebuild-wolf` (which builds from a working tree, not a
release): this checks the project's GitHub Releases for a newer tagged
build, and can download and `pip install` its wheel asset into the same
Python environment `wolf` is already running under. Every network call
goes through a seam (`fetch_latest_release`/`download`/`pip_install`) so
tests never touch the real network.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from wolf import __version__

RELEASES_API_URL = "https://api.github.com/repos/manuelblancovalentin/wolf/releases/latest"
_TIMEOUT_SECONDS = 10


class UpgradeError(ValueError):
    pass


def _default_fetch_latest_release(url: str = RELEASES_API_URL) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise UpgradeError(f"cannot reach {url}: {error}") from error
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise UpgradeError(f"invalid response from {url}: {error}") from error
    if not isinstance(data, dict):
        raise UpgradeError(f"invalid response from {url}: expected a JSON object")
    return data


def _wheel_asset(release: dict[str, Any]) -> dict[str, Any]:
    assets = release.get("assets") or []
    for asset in assets:
        if isinstance(asset, dict) and str(asset.get("name", "")).endswith(".whl"):
            return asset
    raise UpgradeError(f"release {release.get('tag_name', '?')!r} has no .whl asset to install")


def _version_from_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def _parse_version(value: str) -> tuple[int, ...]:
    """A leading run of dot-separated integers, ignoring anything after
    the first non-numeric component (e.g. "0.1.0.dev1" -> (0, 1, 0)) --
    enough to compare real release tags against each other without a
    third-party version-parsing dependency."""
    numeric: list[int] = []
    for part in re.split(r"[.\-]", value):
        if not part.isdigit():
            break
        numeric.append(int(part))
    return tuple(numeric) or (0,)


def _is_newer(candidate: str, current: str) -> bool:
    return _parse_version(candidate) > _parse_version(current)


def check_latest(
    *, fetch_latest_release: Callable[[], dict[str, Any]] = _default_fetch_latest_release,
) -> tuple[str, str, bool]:
    """Returns `(installed_version, latest_version, is_newer)`."""
    release = fetch_latest_release()
    tag = release.get("tag_name")
    if not tag:
        raise UpgradeError("the latest release has no tag_name")
    latest = _version_from_tag(str(tag))
    return __version__, latest, _is_newer(latest, __version__)


def _default_download(url: str, destination: Path) -> None:
    try:
        urllib.request.urlretrieve(url, destination)
    except urllib.error.URLError as error:
        raise UpgradeError(f"cannot download {url}: {error}") from error


def _default_pip_install(wheel_path: Path) -> None:
    command = [sys.executable, "-m", "pip", "install", "--upgrade", str(wheel_path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise UpgradeError(f"pip install failed: {detail}")


def download_and_install(
    *,
    fetch_latest_release: Callable[[], dict[str, Any]] = _default_fetch_latest_release,
    download: Optional[Callable[[str, Path], None]] = None,
    pip_install: Optional[Callable[[Path], None]] = None,
) -> str:
    """Downloads the latest release's wheel asset to a scratch folder and
    installs it with `pip`, using the current `sys.executable` so it lands
    in the same environment this `wolf` is already running from. Returns
    the installed version string. Raises `UpgradeError` on any failure;
    never partially leaves a half-downloaded wheel installed."""
    release = fetch_latest_release()
    asset = _wheel_asset(release)
    url = asset.get("browser_download_url")
    if not url:
        raise UpgradeError(f"asset {asset.get('name', '?')!r} has no download URL")
    with tempfile.TemporaryDirectory(prefix="wolf-upgrade-") as scratch:
        wheel_path = Path(scratch) / str(asset["name"])
        (download or _default_download)(str(url), wheel_path)
        (pip_install or _default_pip_install)(wheel_path)
    return _version_from_tag(str(release.get("tag_name", "")))
