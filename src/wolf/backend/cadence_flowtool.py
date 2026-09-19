"""Cadence Flowtool backend identity and local dependency checks."""

from __future__ import annotations

import shutil
from typing import Mapping, Optional, Sequence

from wolf.backend.base import Backend, ValidationItem
from wolf.backend.cadence_genus import GenusInputs, prepare_genus_inputs, validate_genus
from wolf.context import ResolvedContext


class CadenceFlowtoolBackend(Backend):
    name = "cadence-flowtool"
    description = "Cadence Flowtool/Genus/Innovus compatibility backend"
    adapter_filename = "cadence-flowtool.sh"

    def validate_genus(self, context: ResolvedContext):
        return validate_genus(context)

    def prepare_genus_inputs(self, context: ResolvedContext, destination) -> GenusInputs:
        return prepare_genus_inputs(context, destination)

    def validate(
        self, context: Optional[Mapping[str, str]] = None
    ) -> Sequence[ValidationItem]:
        items = []
        for executable in ("flowtool", "python3"):
            location = shutil.which(executable)
            items.append(
                ValidationItem(
                    name=executable,
                    available=location is not None,
                    detail=location or "unavailable",
                )
            )

        if context is not None:
            for key in (
                "RTL_YAML_FILE",
                "YAML_TEMPLATE_FILE",
                "PROCESS_SETUP_COMMON_TEMPLATE",
                "PROCESS_SETUP_HOST_TEMPLATE",
                "PROCESS_FLOW_TEMPLATE",
            ):
                value = context.get(key)
                items.append(
                    ValidationItem(
                        name=key,
                        available=bool(value),
                        detail=value or "not configured",
                    )
                )
        return tuple(items)


CADENCE_FLOWTOOL = CadenceFlowtoolBackend()
