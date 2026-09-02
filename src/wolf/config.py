"""Versioned persistent configuration for the WOLF installation."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

import yaml


SCHEMA = "wolf.config/v1"
CONFIG_KEYS = (
    "paths.data",
    "paths.packages",
    "paths.environments",
    "paths.cache",
    "workspace.default",
    "container.preferred_runtime",
    "shell.prompt",
)
_SECTIONS = {"paths", "workspace", "container", "shell", "registries"}


def config_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".config"
    return (base / "wolf" / "config.yaml").resolve()


def xdg_data_root() -> Path:
    root = os.environ.get("XDG_DATA_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".local" / "share"
    return (base / "wolf").resolve()


def xdg_cache_root() -> Path:
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".cache"
    return (base / "wolf").resolve()


def default_document() -> dict[str, Any]:
    data = xdg_data_root()
    return {
        "schema": SCHEMA,
        "paths": {
            "data": str(data),
            "packages": str(data / "packages"),
            "environments": str(data / "environments"),
            "cache": str(xdg_cache_root()),
        },
        "workspace": {"default": None},
        "container": {"preferred_runtime": None},
        "shell": {"prompt": True},
        "registries": {},
    }


def _validate_path(value: Any, key: str) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"configuration key {key} must be a path string or null")


def validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("WOLF configuration must be a mapping")
    if document.get("schema") != SCHEMA:
        raise ValueError(f"unsupported WOLF configuration schema {document.get('schema')!r}")
    unknown = set(document) - (_SECTIONS | {"schema"})
    if unknown:
        raise ValueError(f"unknown WOLF configuration key: {sorted(unknown)[0]}")
    result = deepcopy(document)
    for section in _SECTIONS:
        value = result.setdefault(section, {})
        if not isinstance(value, dict):
            raise ValueError(f"configuration section {section} must be a mapping")
    allowed = {
        "paths": {"data", "packages", "environments", "cache"},
        "workspace": {"default"},
        "container": {"preferred_runtime"},
        "shell": {"prompt"},
    }
    for section, keys in allowed.items():
        extra = set(result[section]) - keys
        if extra:
            raise ValueError(f"unknown WOLF configuration key: {section}.{sorted(extra)[0]}")
    for key in ("data", "packages", "environments", "cache"):
        _validate_path(result["paths"].get(key), f"paths.{key}")
    _validate_path(result["workspace"].get("default"), "workspace.default")
    runtime = result["container"].get("preferred_runtime")
    if runtime not in (None, "podman", "docker"):
        raise ValueError("container.preferred_runtime must be podman, docker, or null")
    prompt = result["shell"].get("prompt")
    if prompt is not None and not isinstance(prompt, bool):
        raise ValueError("shell.prompt must be true or false")
    for name, entry in result["registries"].items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise ValueError("registries must map names to registry configuration")
    return result


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = (path or config_path()).resolve()

    def load(self, *, effective: bool = False) -> dict[str, Any]:
        if self.path.exists():
            try:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as error:
                raise ValueError(f"cannot read WOLF configuration {self.path}: {error}") from error
            document = validate_document(raw)
        else:
            document = {"schema": SCHEMA}
            for section in _SECTIONS:
                document[section] = {}
            document = validate_document(document)
        if not effective:
            return document
        defaults = default_document()
        for section in ("paths", "workspace", "container", "shell"):
            defaults[section].update(document[section])
        defaults["registries"] = deepcopy(document["registries"])
        return defaults

    def write(self, document: Mapping[str, Any]) -> None:
        validated = validate_document(dict(document))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".config-", suffix=".yaml", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                yaml.safe_dump(validated, stream, sort_keys=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, key: str, *, effective: bool = True) -> Any:
        if key not in CONFIG_KEYS:
            raise ValueError(f"unknown WOLF configuration key {key!r}")
        section, field = key.split(".", 1)
        return self.load(effective=effective)[section].get(field)

    def set(self, key: str, value: Any, *, invocation_cwd: Path | None = None) -> Any:
        if key not in CONFIG_KEYS:
            raise ValueError(f"unknown WOLF configuration key {key!r}")
        if key.startswith("paths.") or key == "workspace.default":
            if not isinstance(value, str) or not value:
                raise ValueError(f"configuration key {key} requires a path")
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = (invocation_cwd or Path.cwd()) / path
            value = str(path.resolve())
        document = self.load()
        section, field = key.split(".", 1)
        document[section][field] = value
        self.write(document)
        return value

    def unset(self, key: str) -> None:
        if key not in CONFIG_KEYS:
            raise ValueError(f"unknown WOLF configuration key {key!r}")
        document = self.load()
        section, field = key.split(".", 1)
        document[section].pop(field, None)
        self.write(document)
