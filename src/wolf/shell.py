"""Locate and explicitly install WOLF's small shell integration."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sysconfig


BEGIN = "# >>> WOLF shell integration >>>"
END = "# <<< WOLF shell integration <<<"


def integration_path(shell: str = "bash") -> Path:
    source = Path(__file__).resolve().parents[2] / "shell" / f"wolf.{shell}"
    if source.is_file():
        return source
    return Path(sysconfig.get_path("data")) / "share" / "wolf" / "shell" / f"wolf.{shell}"


def detect_shell() -> str | None:
    """Best-effort detection of the interactive parent shell."""
    candidates = []
    for variable in ("WOLF_SHELL", "ZSH_VERSION", "BASH_VERSION"):
        value = os.environ.get(variable)
        if value:
            candidates.append("zsh" if variable == "ZSH_VERSION" else
                              "bash" if variable == "BASH_VERSION" else Path(value).name)
    parent = os.getppid()
    try:
        process = subprocess.run(["ps", "-p", str(parent), "-o", "comm="],
                                 text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, check=False)
        if process.returncode == 0:
            candidates.insert(0, Path(process.stdout.strip()).name)
    except OSError:
        pass
    shell = os.environ.get("SHELL", "")
    candidates.append(Path(shell).name if shell else "")
    for candidate in candidates:
        if candidate in {"bash", "zsh"}:
            return candidate
    return None


def install_shell_integration(shell: str, rc_path: Path | None = None) -> bool:
    if shell not in {"bash", "zsh"}:
        raise ValueError("WOLF shell integration currently supports Bash and zsh")
    rc_path = (rc_path or Path.home() / (".bashrc" if shell == "bash" else ".zshrc")).expanduser().resolve()
    script = integration_path(shell).resolve()
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


def install_bash_integration(rc_path: Path | None = None) -> bool:
    return install_shell_integration("bash", rc_path)
