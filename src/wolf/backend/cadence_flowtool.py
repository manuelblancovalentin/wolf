"""Cadence Flowtool backend identity and local dependency checks."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Mapping, Optional, Sequence

from wolf.backend.base import Backend, ValidationItem
from wolf.backend.cadence_genus import (
    STAGE_ORDER, GenusInputs, genus_run_active_elapsed, genus_run_metrics, genus_run_qor,
    genus_run_status, prepare_genus_inputs, rollup_stage_states, run_genus, stage_step_detail,
    validate_genus,
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

    def extract_metrics(self, run_directory):
        """`wolf status`'s real backend-local hook -- parses Flowtool's
        own `flow.metrics` (see genus_run_metrics's own docstring),
        confirmed real alongside flow.status for any run that has
        actually invoked Flowtool, plus WOLF's own live
        "cadence.active_stage_elapsed_seconds" (see
        genus_run_active_elapsed's own docstring) for however long the
        current invocation has actually been running -- independent of
        flow.metrics' own total_real_seconds, which like flow.status is
        confirmed not promptly updated during a manually-typed
        run_flow."""
        metrics = genus_run_metrics(Path(run_directory))
        active_elapsed = genus_run_active_elapsed(Path(run_directory))
        if active_elapsed is not None:
            metrics["cadence.active_stage_elapsed_seconds"] = active_elapsed
        qor = genus_run_qor(Path(run_directory))
        if qor:
            metrics["cadence.qor_by_stage"] = qor
        return metrics

    def stage_step_detail(self, run_directory, stage: str):
        """`wolf status --watch`'s expanded live view hook -- the real
        create_flow membership tree, qualified by flow.status's own
        current states (see stage_step_detail's own docstring)."""
        return stage_step_detail(Path(run_directory), stage)

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
