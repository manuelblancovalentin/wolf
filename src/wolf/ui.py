"""Shared terminal presentation for the installed WOLF CLI."""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.text import Text


WOLF_PURPLE = "#ad4ce5"

WOLF_HEADER = """\
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░██╗░░░░░░░██╗░█████╗░██╗░░░░░███████╗░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░██║░░██╗░░██║██╔══██╗██║░░░░░██╔════╝░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░╚██╗████╗██╔╝██║░░██║██║░░░░░█████╗░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░████╔═████║░██║░░██║██║░░░░░██╔══╝░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░╚██╔╝░╚██╔╝░╚█████╔╝███████╗██║░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░╚═╝░░░╚═╝░░░╚════╝░╚══════╝╚═╝░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░"""

ENV_HEADER = """\
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░░░░░░░░░░░██╗░░░░░░░██╗░█████╗░██╗░░░░░███████╗░░░███████╗███╗░░██╗██╗░░░██╗░░░░░░░░░░
░░░░░░░░░░░░░██║░░██╗░░██║██╔══██╗██║░░░░░██╔════╝░░░██╔════╝████╗░██║██║░░░██║░░░░░░░░░░
░░░░░░░░░░░░░╚██╗████╗██╔╝██║░░██║██║░░░░░█████╗░░░░░█████╗░░██╔██╗██║╚██╗░██╔╝░░░░░░░░░░
░░░░░░░░░░░░░░████╔═████║░██║░░██║██║░░░░░██╔══╝░░░░░██╔══╝░░██║╚████║░╚████╔╝░░░░░░░░░░░
░░░░░░░░░░░░░░╚██╔╝░╚██╔╝░╚█████╔╝███████╗██║░░░░░██╗███████╗██║░╚███║░░╚██╔╝░░░░░░░░░░░░
░░░░░░░░░░░░░░░╚═╝░░░╚═╝░░░╚════╝░╚══════╝╚═╝░░░░░╚═╝╚══════╝╚═╝░░╚══╝░░░╚═╝░░░░░░░░░░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░"""

PROCESS_HEADER = """\
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░░██╗░░░░░░░██╗░█████╗░██╗░░░░░███████╗░░░██████╗░██████╗░░█████╗░░█████╗░███████╗░██████╗░██████╗░░░
░░░██║░░██╗░░██║██╔══██╗██║░░░░░██╔════╝░░░██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔════╝██╔════╝░░░
░░░╚██╗████╗██╔╝██║░░██║██║░░░░░█████╗░░░░░██████╔╝██████╔╝██║░░██║██║░░╚═╝█████╗░░╚█████╗░╚█████╗░░░░
░░░░████╔═████║░██║░░██║██║░░░░░██╔══╝░░░░░██╔═══╝░██╔══██╗██║░░██║██║░░██╗██╔══╝░░░╚═══██╗░╚═══██╗░░░
░░░░╚██╔╝░╚██╔╝░╚█████╔╝███████╗██║░░░░░██╗██║░░░░░██║░░██║╚█████╔╝╚█████╔╝███████╗██████╔╝██████╔╝░░░
░░░░░╚═╝░░░╚═╝░░░╚════╝░╚══════╝╚═╝░░░░░╚═╝╚═╝░░░░░╚═╝░░╚═╝░╚════╝░░╚════╝░╚══════╝╚═════╝░╚═════╝░░░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░"""

_HEADERS = {
    "wolf": WOLF_HEADER,
    "env": ENV_HEADER,
    "process": PROCESS_HEADER,
}

console = Console()
error_console = Console(stderr=True)


def _banner_text(value: str) -> Text:
    rendered = Text(value)
    rendered.highlight_regex("░+", style=WOLF_PURPLE)
    return rendered


def header(kind: str = "wolf", section_title: Optional[str] = None) -> None:
    """Print a command-appropriate WOLF banner and optional section band."""
    console.print(_banner_text(_HEADERS.get(kind, WOLF_HEADER)), soft_wrap=True)
    if section_title:
        console.print(Text(f" {section_title} ", style="bold white on blue"))


def success(message: object) -> None:
    console.print(
        Text(" ➤ [OK]", style="bold green"),
        "-",
        Text(str(message)),
        soft_wrap=True,
    )


def info(message: object) -> None:
    console.print(
        Text(" ➤ [INFO]", style="bold yellow"),
        "-",
        Text(str(message)),
        soft_wrap=True,
    )


def error(message: object) -> None:
    error_console.print(
        Text(" [ERROR]", style="bold red"),
        "-",
        Text(str(message)),
        soft_wrap=True,
    )


def entry(value: object) -> None:
    console.print(
        Text(" ➤", style="bold"),
        Text(str(value), style="yellow"),
        soft_wrap=True,
    )


def key_value(key: object, value: object) -> None:
    line = Text("  ")
    line.append(str(key), style="bold blue")
    line.append(": ")
    line.append(str(value))
    console.print(line, soft_wrap=True)


def section(title: str) -> None:
    """Print a bold banded section title, e.g. within a pre-run summary."""
    console.print(Text(f" {title} ", style="bold white on blue"), soft_wrap=True)


def confirm(prompt: str, *, assume_yes: bool = False) -> bool:
    """Ask the user to proceed, honoring an already-affirmed -y/--yes flag."""
    if assume_yes:
        return True
    line = Text()
    line.append(" ", style="bold red")
    line.append(prompt, style="bold red")
    line.append(" ")
    line.append("[y/N]: ", style="bold yellow")
    console.print(line, end="", soft_wrap=True)
    try:
        reply = input()
    except EOFError:
        reply = ""
    return reply.strip().lower() in ("y", "yes")
