#!/bin/bash

WOLF_BACKEND_NAME="orfs"
WOLF_BACKEND_DESCRIPTION="OpenROAD Flow Scripts compatibility backend"
WOLF_ORFS_STAGES=(synth floorplan place cts route finish)

_wolf_orfs_error() {
    _wolf_error "ORFS backend: $1"
    return 1
}

_wolf_orfs_absolute_file() {
    local path="$1" directory filename
    if [[ "$path" != /* ]]; then
        path="${ORFS_ROOT}/${path#./}"
    fi
    if [[ ! -f "$path" ]]; then
        _wolf_orfs_error "required file does not exist: $path"
        return 1
    fi
    directory=$(cd -P -- "$(dirname -- "$path")" && pwd) || return 1
    filename=$(basename -- "$path")
    printf '%s/%s\n' "$directory" "$filename"
}

_wolf_orfs_container_path() {
    local host_path="$1" relative_path
    case "$host_path" in
        "${ORFS_ROOT}"/*)
            relative_path="${host_path#"${ORFS_ROOT}"/}"
            printf '/work/%s\n' "$relative_path"
            ;;
        *)
            _wolf_orfs_error "host file must be inside ORFS_ROOT so it is mounted in the container: $host_path"
            return 1
            ;;
    esac
}

_wolf_orfs_select_runtime() {
    if [[ -n "${ORFS_CONTAINER_RUNTIME:-}" ]]; then
        :
    elif [[ -n "${WOLF_CONTAINER_RUNTIME:-}" ]]; then
        ORFS_CONTAINER_RUNTIME="$WOLF_CONTAINER_RUNTIME"
    elif _wolf_container_runtime_available docker; then
        ORFS_CONTAINER_RUNTIME="docker"
    elif _wolf_container_runtime_available podman; then
        ORFS_CONTAINER_RUNTIME="podman"
    else
        _wolf_orfs_error "requires Docker or Podman, but neither runtime is available"
        return 1
    fi

    case "$ORFS_CONTAINER_RUNTIME" in
        docker|podman)
            ;;
        *)
            _wolf_orfs_error "unsupported container runtime: $ORFS_CONTAINER_RUNTIME"
            return 1
            ;;
    esac
    if ! _wolf_container_runtime_available "$ORFS_CONTAINER_RUNTIME"; then
        _wolf_orfs_error "container runtime is unavailable: $ORFS_CONTAINER_RUNTIME"
        return 1
    fi
}

_wolf_backend_validate() {
    if [[ -z "${ORFS_ROOT:-}" ]]; then
        _wolf_orfs_error "ORFS_ROOT must name an external OpenROAD-flow-scripts/flow checkout"
        return 1
    fi
    if [[ ! -d "$ORFS_ROOT" ]]; then
        _wolf_orfs_error "ORFS_ROOT is not a directory: $ORFS_ROOT"
        return 1
    fi
    ORFS_ROOT=$(cd -P -- "$ORFS_ROOT" && pwd) || return 1
    for required_path in Makefile designs util; do
        if [[ ! -e "${ORFS_ROOT}/${required_path}" ]]; then
            _wolf_orfs_error "ORFS_ROOT is not a flow checkout; missing ${required_path}"
            return 1
        fi
    done

    ORFS_DOCKER_SHELL="${ORFS_DOCKER_SHELL:-${ORFS_ROOT}/util/docker_shell}"
    _wolf_orfs_select_runtime || return $?
    if [[ "$ORFS_CONTAINER_RUNTIME" == "docker" && ! -x "$ORFS_DOCKER_SHELL" ]]; then
        _wolf_orfs_error "Docker execution requires an executable util/docker_shell: $ORFS_DOCKER_SHELL"
        return 1
    fi
    if [[ "$ORFS_CONTAINER_RUNTIME" == "podman" && -z "${ORFS_CONTAINER_IMAGE:-}" ]]; then
        _wolf_orfs_error "Podman execution requires ORFS_CONTAINER_IMAGE"
        return 1
    fi

    if [[ -z "${ORFS_DESIGN_CONFIG:-}" ]]; then
        _wolf_orfs_error "ORFS_DESIGN_CONFIG must name a design config within ORFS_ROOT"
        return 1
    fi
    ORFS_DESIGN_CONFIG=$(_wolf_orfs_absolute_file "$ORFS_DESIGN_CONFIG") || return $?
    ORFS_CONTAINER_DESIGN_CONFIG=$(_wolf_orfs_container_path "$ORFS_DESIGN_CONFIG") || return $?

    if [[ -n "${ORFS_SDC_FILE:-}" ]]; then
        ORFS_SDC_FILE=$(_wolf_orfs_absolute_file "$ORFS_SDC_FILE") || return $?
        ORFS_CONTAINER_SDC_FILE=$(_wolf_orfs_container_path "$ORFS_SDC_FILE") || return $?
    fi

    local design_directory platform_directory
    design_directory=$(dirname -- "$ORFS_DESIGN_CONFIG")
    platform_directory=$(dirname -- "$design_directory")
    ORFS_DESIGN_NAME="${ORFS_DESIGN_NAME:-${DESIGN_NAME:-$(basename -- "$design_directory")}}"
    ORFS_PLATFORM="${ORFS_PLATFORM:-$(basename -- "$platform_directory")}"
    ORFS_FLOW_VARIANT="${ORFS_FLOW_VARIANT:-base}"

    # Transitional values let the existing generic run lifecycle allocate and
    # snapshot a WOLF run without imposing Cadence configuration on ORFS.
    DESIGN_NAME="$ORFS_DESIGN_NAME"
    PROCESS="$ORFS_PLATFORM"
    WORKSPACE_DIR="${WOLF_WORKSPACE_DIR:-${WOLF_HOME:-${HOME}/.wolf}/workspaces}"
    PROCESS_SCRIPTS="${ORFS_SNAPSHOT_SCRIPTS:-${WOLF_BIN}/backends}"
    ORFS_GIT_REVISION=$(git -C "$ORFS_ROOT" rev-parse HEAD 2>/dev/null || true)
}

_wolf_orfs_make_arguments() {
    local make_var
    WOLF_ORFS_MAKE_ARGS=(
        "DESIGN_CONFIG=${ORFS_CONTAINER_DESIGN_CONFIG}"
        "FLOW_VARIANT=${ORFS_FLOW_VARIANT}"
    )
    if [[ -n "${ORFS_CONTAINER_SDC_FILE:-}" ]]; then
        WOLF_ORFS_MAKE_ARGS+=("SDC_FILE=${ORFS_CONTAINER_SDC_FILE}")
    fi

    while IFS= read -r make_var || [[ -n "$make_var" ]]; do
        [[ -z "$make_var" ]] && continue
        if [[ ! "$make_var" =~ ^[A-Za-z_][A-Za-z0-9_]*=.*$ ]]; then
            _wolf_orfs_error "invalid ORFS_MAKE_VARS entry: $make_var"
            return 2
        fi
        WOLF_ORFS_MAKE_ARGS+=("$make_var")
    done <<< "${ORFS_MAKE_VARS:-}"

    for make_var in "$@"; do
        if [[ ! "$make_var" =~ ^[A-Za-z_][A-Za-z0-9_]*=.*$ ]]; then
            _wolf_orfs_error "ORFS passthrough arguments must be Make assignments (NAME=VALUE): $make_var"
            return 2
        fi
        WOLF_ORFS_MAKE_ARGS+=("$make_var")
    done
}

_wolf_backend_plan() {
    SETUP_YAML="ORFS design config: ${ORFS_DESIGN_CONFIG}"
    FLOW_YAML="ORFS flow variant: ${ORFS_FLOW_VARIANT}"
    LOGFILE="ORFS reports: ${ORFS_ROOT}/reports/${ORFS_PLATFORM}/${ORFS_DESIGN_NAME}/${ORFS_FLOW_VARIANT}"
    FEATURES=()
}

_wolf_backend_prepare() {
    _wolf_orfs_make_arguments || return $?

    if [[ "$ORFS_CONTAINER_RUNTIME" == "docker" ]]; then
        WOLF_CONTAINER_LAUNCHER="$ORFS_DOCKER_SHELL"
    else
        unset WOLF_CONTAINER_LAUNCHER
        WOLF_CONTAINER_IMAGE="$ORFS_CONTAINER_IMAGE"
        WOLF_CONTAINER_HOST_ROOT="$ORFS_ROOT"
        WOLF_CONTAINER_CONTAINER_ROOT="/work"
        WOLF_CONTAINER_WORKDIR="${ORFS_CONTAINER_WORKDIR:-/OpenROAD-flow-scripts/flow}"
    fi

    WOLF_BACKEND_COMMAND_ARGS=(make "${WOLF_ORFS_MAKE_ARGS[@]}")
    printf -v WOLF_BACKEND_COMMAND '%q ' "${WOLF_BACKEND_COMMAND_ARGS[@]}"
    WOLF_BACKEND_COMMAND="${WOLF_BACKEND_COMMAND% }"
    {
        printf '# ORFS backend command (stage target is appended at execution time)\n'
        printf '%s\n' "$WOLF_BACKEND_COMMAND"
        printf '# ORFS checkout revision: %s\n' "${ORFS_GIT_REVISION:-unavailable}"
        printf '# Container runtime: %s\n' "$ORFS_CONTAINER_RUNTIME"
    } > "${SCRIPTS_DIR}/orfs.command"
}

_wolf_backend_stages() {
    WOLF_BACKEND_STAGES=("${WOLF_ORFS_STAGES[@]}")
}

_wolf_backend_run_stage() {
    local stage="$1" status
    shift
    _wolf_orfs_make_arguments "$@" || return $?

    _wolf_info "Running ORFS stage ÷blue÷${stage}÷÷ with ÷yellow÷${ORFS_CONTAINER_RUNTIME}÷÷."
    (
        cd "$ORFS_ROOT" || exit 1
        _wolf_container_execute "$ORFS_CONTAINER_RUNTIME" make "${WOLF_ORFS_MAKE_ARGS[@]}" "$stage"
    )
    status=$?
    if [[ $status -ne 0 ]]; then
        _wolf_error "ORFS exited with status $status while running $stage. Stopping sequence."
        return "$status"
    fi
}
