#!/bin/bash

# Transitional backend loading and backend-neutral stage orchestration for the
# legacy Bash runner. Backend adapters deliberately share the runner's shell
# context so the existing run lifecycle does not need to be rewritten.

_wolf_load_backend() {
    local backend_name="$1"
    local backend_dir="${WOLF_BACKEND_DIR:-${WOLF_BIN}/backends}"
    local adapter

    if [[ ! "$backend_name" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
        _wolf_error "Invalid backend name \"$backend_name\". Backend names use lowercase letters, numbers, and hyphens."
        return 2
    fi

    case "$backend_name" in
        cadence-flowtool|orfs)
            ;;
        *)
            _wolf_error "Unknown WOLF backend \"$backend_name\"."
            return 2
            ;;
    esac

    adapter="${backend_dir}/${backend_name}.sh"
    if [[ ! -f "$adapter" ]]; then
        _wolf_error "Unknown WOLF backend \"$backend_name\"."
        return 2
    fi

    unset WOLF_BACKEND_NAME WOLF_BACKEND_DESCRIPTION
    unset -f _wolf_backend_validate _wolf_backend_plan _wolf_backend_prepare
    unset -f _wolf_backend_associate_run
    unset -f _wolf_backend_stages _wolf_backend_run_stage
    source "$adapter" || return 2

    if ! declare -F _wolf_backend_associate_run >/dev/null; then
        _wolf_backend_associate_run() { return 0; }
    fi

    local required_function
    for required_function in \
        _wolf_backend_validate \
        _wolf_backend_plan \
        _wolf_backend_prepare \
        _wolf_backend_stages \
        _wolf_backend_run_stage; do
        if ! declare -F "$required_function" >/dev/null; then
            _wolf_error "Backend \"$backend_name\" does not implement $required_function."
            return 2
        fi
    done

    if [[ "$WOLF_BACKEND_NAME" != "$backend_name" ]]; then
        _wolf_error "Backend adapter identity does not match requested backend \"$backend_name\"."
        return 2
    fi
    BACKEND="$backend_name"
}

_wolf_select_backend_stages() {
    local requested_from="$1"
    local requested_to="$2"
    local stage from_index=-1 to_index=-1 index max_fields=1 fields trimmed
    local -a normalized=()

    _wolf_backend_stages || return $?
    if [[ ${#WOLF_BACKEND_STAGES[@]} -eq 0 ]]; then
        _wolf_error "Backend \"$BACKEND\" did not provide any stages."
        return 1
    fi

    [[ -n "${requested_from// }" ]] || requested_from="${WOLF_BACKEND_STAGES[0]}"
    [[ -n "${requested_to// }" ]] || requested_to="${WOLF_BACKEND_STAGES[-1]}"

    IFS='.' read -r -a _wolf_from_parts <<< "$requested_from"
    IFS='.' read -r -a _wolf_to_parts <<< "$requested_to"
    if [[ ${#_wolf_from_parts[@]} -gt $max_fields ]]; then
        max_fields=${#_wolf_from_parts[@]}
    fi
    if [[ ${#_wolf_to_parts[@]} -gt $max_fields ]]; then
        max_fields=${#_wolf_to_parts[@]}
    fi

    for stage in "${WOLF_BACKEND_STAGES[@]}"; do
        IFS='.' read -r -a fields <<< "$stage"
        trimmed="${fields[0]}"
        for ((index=1; index<max_fields && index<${#fields[@]}; index++)); do
            trimmed="${trimmed}.${fields[index]}"
        done
        if [[ ${#normalized[@]} -eq 0 || "${normalized[-1]}" != "$trimmed" ]]; then
            normalized+=("$trimmed")
        fi
    done

    for index in "${!normalized[@]}"; do
        [[ "${normalized[index]}" == "$requested_from" ]] && from_index=$index
        [[ "${normalized[index]}" == "$requested_to" ]] && to_index=$index
    done
    if [[ $from_index -lt 0 ]]; then
        _wolf_error "Flow step \"$requested_from\" could not be found. Available stages: ${normalized[*]}"
        return 1
    fi
    if [[ $to_index -lt 0 ]]; then
        _wolf_error "Flow step \"$requested_to\" could not be found. Available stages: ${normalized[*]}"
        return 1
    fi
    if [[ $from_index -gt $to_index ]]; then
        _wolf_error "Flow stage range starts after it ends: $requested_from -> $requested_to."
        return 1
    fi

    FROM_STEP="$requested_from"
    TO_STEP="$requested_to"
    WOLF_SELECTED_STAGES=("${normalized[@]:from_index:to_index-from_index+1}")
}

_wolf_run_backend_stages() {
    local requested_from="$1"
    local requested_to="$2"
    local before_stage_hook="$3"
    shift 3

    _wolf_select_backend_stages "$requested_from" "$requested_to" || return $?

    local stage status
    for stage in "${WOLF_SELECTED_STAGES[@]}"; do
        if [[ -n "$before_stage_hook" ]] && ! "$before_stage_hook" "$stage"; then
            return 0
        fi
        _wolf_backend_run_stage "$stage" "$@"
        status=$?
        if [[ $status -ne 0 ]]; then
            return "$status"
        fi
    done
}
