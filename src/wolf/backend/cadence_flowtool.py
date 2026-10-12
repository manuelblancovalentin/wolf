"""Cadence Flowtool backend identity and local dependency checks."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Mapping, Optional, Sequence

from wolf.backend.base import Backend, ValidationItem
from wolf.backend.cadence_genus import (
    STAGE_ORDER, GenusInputs, genus_run_status, prepare_genus_inputs, rollup_stage_states,
    run_genus, validate_genus,
)
from wolf.context import ResolvedContext


class CadenceFlowtoolBackend(Backend):
    name = "cadence-flowtool"
    description = "Cadence Flowtool/Genus/Innovus compatibility backend"
    adapter_filename = "cadence-flowtool.sh"

    def validate_genus(self, context: ResolvedContext, *, physical: bool = False):
        return validate_genus(context, physical=physical)

    def prepare_genus_inputs(self, context: ResolvedContext, destination) -> GenusInputs:
        return prepare_genus_inputs(context, destination)

    def run_genus(
        self, context: ResolvedContext, *, clean: bool = False, interactive: bool = False,
        from_stage: Optional[str] = None, to_stage: Optional[str] = None,
    ):
        return run_genus(context, clean=clean, interactive=interactive,
                          from_stage=from_stage, to_stage=to_stage)

    def stages(self) -> Sequence[str]:
        return STAGE_ORDER

    def infer_stage_results(self, run_directory):
        """`wolf status`'s real backend-local hook -- queries Flowtool's
        own `flowtool -status` for the already-allocated run rather than
        guessing stage completion from which output files exist on disk
        (see genus_run_status's own docstring), then rolls per-step
        detail up to each STAGE_ORDER name via the real create_flow
        membership tree (rollup_stage_states) -- load_status only ever
        asks about stages() names, so step-level detail alone would
        otherwise be silently dropped if -status doesn't also report a
        line for the stage name itself."""
        _, states = genus_run_status(Path(run_directory))
        return rollup_stage_states(states)

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
