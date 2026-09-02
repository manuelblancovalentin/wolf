"""Backend identity and backend-local validation metadata."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Optional, Sequence

if TYPE_CHECKING:
    from wolf.context import ResolvedContext


@dataclass(frozen=True)
class ValidationItem:
    name: str
    available: bool
    detail: str


class Backend(ABC):
    """Installed-CLI view of a built-in execution backend.

    Legacy execution remains in the shell adapter named by ``adapter_filename``.
    The shell adapter implements validate/plan/prepare/stages/run_stage until the
    generic run lifecycle migrates to Python.
    """

    name: str
    description: str
    adapter_filename: str

    @abstractmethod
    def validate(
        self, context: Optional[Mapping[str, str]] = None
    ) -> Sequence[ValidationItem]:
        """Return backend-local dependency/configuration checks."""

    def execution_environment(
        self, context: Optional[Mapping[str, str]] = None
    ) -> Mapping[str, str]:
        """Return backend-local values resolved for the execution subprocess."""
        return {}

    def prepare_execution(self, context: "ResolvedContext") -> Mapping[str, str]:
        """Prepare backend-native inputs and return subprocess-only values."""
        return self.execution_environment(context.values)

    def extract_metrics(self, run_directory):
        """Return optional semantic metrics parsed from a completed run."""
        return {}
