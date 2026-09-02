#!/bin/bash

# Minimal container execution bridge for shell backends. Backends supply either
# a launcher compatible with their checkout or generic image/mount settings.

_wolf_container_runtime_available() {
    command -v "$1" >/dev/null 2>&1
}

_wolf_container_execute() {
    local runtime="$1"
    shift

    if [[ -n "${WOLF_CONTAINER_LAUNCHER:-}" ]]; then
        "$WOLF_CONTAINER_LAUNCHER" "$@"
        return $?
    fi

    if [[ -z "${WOLF_CONTAINER_IMAGE:-}" || -z "${WOLF_CONTAINER_HOST_ROOT:-}" || -z "${WOLF_CONTAINER_WORKDIR:-}" ]]; then
        _wolf_error "Container executor is missing image, host root, or working directory configuration."
        return 2
    fi

    "$runtime" run --rm \
        -v "${WOLF_CONTAINER_HOST_ROOT}:${WOLF_CONTAINER_CONTAINER_ROOT:-/work}:Z" \
        -w "$WOLF_CONTAINER_WORKDIR" \
        "$WOLF_CONTAINER_IMAGE" "$@"
}
