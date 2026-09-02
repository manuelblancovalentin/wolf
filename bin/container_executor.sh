#!/bin/bash

# Minimal container execution bridge for shell backends.

_wolf_container_runtime_available() {
    command -v "$1" >/dev/null 2>&1
}

_wolf_container_runtime_diagnostic() {
    local runtime="$1" output status
    if ! _wolf_container_runtime_available "$runtime"; then
        printf 'binary absent\n'
        return 1
    fi

    output=$("$runtime" info 2>&1)
    status=$?
    if [[ $status -eq 0 ]]; then
        printf 'usable\n'
        return 0
    fi
    if [[ "$output" == *"permission denied"* || "$output" == *"Permission denied"* ]]; then
        printf 'installed but permission denied: %s\n' "${output%%$'\n'*}"
    else
        printf 'installed but daemon/socket unavailable: %s\n' "${output%%$'\n'*}"
    fi
    return "$status"
}

_wolf_container_execute() {
    local runtime="$1"
    shift

    if [[ -z "${WOLF_CONTAINER_IMAGE:-}" || -z "${WOLF_CONTAINER_HOST_ROOT:-}" || -z "${WOLF_CONTAINER_WORKDIR:-}" ]]; then
        _wolf_error "Container executor is missing image, host root, or working directory configuration."
        return 2
    fi

    local -a user_args environment_args volume_args
    environment_args=(
        -e "FLOW_HOME=${WOLF_CONTAINER_FLOW_HOME:-/OpenROAD-flow-scripts/flow}"
        -e "WORK_HOME=${WOLF_CONTAINER_WORK_HOME:-${WOLF_CONTAINER_CONTAINER_ROOT:-/work}}"
    )
    if [[ "${WOLF_CONTAINER_HEADLESS:-0}" == "1" ]]; then
        # ORFS uses this upstream-supported Qt mode for final report images.
        # An empty DISPLAY also activates ORFS's headless Makefile setting.
        environment_args+=(-e "DISPLAY=" -e "QT_QPA_PLATFORM=offscreen")
    fi
    if [[ "$runtime" == "podman" ]]; then
        user_args=(--userns=keep-id --user "$(id -u):$(id -g)")
    else
        user_args=(--user "$(id -u):$(id -g)")
    fi

    volume_args=(-v "${WOLF_CONTAINER_HOST_ROOT}:${WOLF_CONTAINER_CONTAINER_ROOT:-/work}:Z")
    local mount_host mount_container mount_mode mount_suffix
    while IFS='|' read -r mount_host mount_container mount_mode || [[ -n "$mount_host" ]]; do
        [[ -z "$mount_host" ]] && continue
        if [[ "$mount_host" != /* || "$mount_container" != /* || ! -e "$mount_host" ]]; then
            _wolf_error "Invalid additional container mount: ${mount_host}|${mount_container}"
            return 2
        fi
        case "$mount_mode" in
            ""|ro) mount_suffix="ro,Z" ;;
            rw) mount_suffix="Z" ;;
            *)
                _wolf_error "Invalid additional container mount mode: ${mount_mode}"
                return 2
                ;;
        esac
        volume_args+=(-v "${mount_host}:${mount_container}:${mount_suffix}")
    done <<< "${WOLF_CONTAINER_MOUNTS:-}"

    "$runtime" run --rm -i \
        "${user_args[@]}" \
        "${environment_args[@]}" \
        "${volume_args[@]}" \
        -w "$WOLF_CONTAINER_WORKDIR" \
        "$WOLF_CONTAINER_IMAGE" "$@"
}
