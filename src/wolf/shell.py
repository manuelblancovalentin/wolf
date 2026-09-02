"""Locate and explicitly install WOLF's small shell integration."""

from __future__ import annotations

from pathlib import Path
import sysconfig


BEGIN = "# >>> WOLF shell integration >>>"
END = "# <<< WOLF shell integration <<<"


def integration_path(shell: str = "bash") -> Path:
    source = Path(__file__).resolve().parents[2] / "shell" / f"wolf.{shell}"
    if source.is_file():
        return source
    return Path(sysconfig.get_path("data")) / "share" / "wolf" / "shell" / f"wolf.{shell}"


def install_bash_integration(rc_path: Path | None = None) -> bool:
    rc_path = (rc_path or Path.home() / ".bashrc").expanduser().resolve()
    script = integration_path("bash").resolve()
    if not script.is_file():
        raise ValueError(f"WOLF Bash integration is unavailable: {script}")
    block = f"{BEGIN}\nsource {str(script)!r}\n{END}\n"
    existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    if BEGIN in existing:
        return False
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    with rc_path.open("a", encoding="utf-8") as stream:
        stream.write(separator + block)
    return True
