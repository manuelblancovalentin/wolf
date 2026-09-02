"""Built-in WOLF backend registry."""

from __future__ import annotations

import re
from typing import Tuple

from wolf.backend.base import Backend
from wolf.backend.cadence_flowtool import CADENCE_FLOWTOOL
from wolf.backend.orfs import ORFS


class UnknownBackendError(ValueError):
    pass


_BACKEND_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_BUILTINS = {
    CADENCE_FLOWTOOL.name: CADENCE_FLOWTOOL,
    ORFS.name: ORFS,
}


def backend_names() -> Tuple[str, ...]:
    return tuple(sorted(_BUILTINS))


def get_backend(name: str) -> Backend:
    if not _BACKEND_NAME.fullmatch(name):
        raise UnknownBackendError(
            f"invalid backend name {name!r}; use lowercase letters, numbers, and hyphens"
        )
    try:
        return _BUILTINS[name]
    except KeyError as error:
        available = ", ".join(backend_names())
        raise UnknownBackendError(
            f"unknown WOLF backend {name!r}; available backends: {available}"
        ) from error
