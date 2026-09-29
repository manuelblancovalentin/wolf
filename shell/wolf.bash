# Bash integration for WOLF. Source once per shell session or from ~/.bashrc.

_wolf_command() {
    command wolf "$@"
}

wolf() {
    case "${1-}" in
        activate)
            if [ "$#" -ne 2 ]; then
                _wolf_command activate "$@"
                return $?
            fi
            _wolf_activate_json=$(_wolf_command _shell-activate "$2")
            _wolf_status=$?
            if [ "$_wolf_status" -ne 0 ]; then
                return "$_wolf_status"
            fi
            if [ -z "${_WOLF_ORIGINAL_PS1+x}" ]; then
                _WOLF_ORIGINAL_PS1=${PS1-}
            fi
            PS1="${_WOLF_ORIGINAL_PS1} [${2}]"
            export WOLF_ACTIVE_ENV="$2"
            # Export the environment's declared env: map. Each key's prior
            # value (or absence) is saved once so deactivate can restore it,
            # the same save-once/restore-on-deactivate pattern used for PS1.
            _WOLF_ACTIVE_ENV_VAR_NAMES=""
            while IFS= read -r -d '' _wolf_env_key && IFS= read -r -d '' _wolf_env_value; do
                _wolf_saved_var="_WOLF_SAVED_ENV_${_wolf_env_key}"
                if [ -z "${!_wolf_saved_var+x}" ]; then
                    if [ -n "${!_wolf_env_key+x}" ]; then
                        printf -v "$_wolf_saved_var" '%s' "${!_wolf_env_key}"
                    else
                        printf -v "$_wolf_saved_var" '%s' "__WOLF_UNSET__"
                    fi
                fi
                export "${_wolf_env_key}=${_wolf_env_value}"
                _WOLF_ACTIVE_ENV_VAR_NAMES="${_WOLF_ACTIVE_ENV_VAR_NAMES}${_wolf_env_key} "
            done < <(printf '%s' "$_wolf_activate_json" | python3 -c '
import json, sys
for key, value in (json.load(sys.stdin).get("env") or {}).items():
    sys.stdout.write(key + "\0" + value + "\0")
')
            export _WOLF_ACTIVE_ENV_VAR_NAMES
            unset _wolf_activate_json _wolf_env_key _wolf_env_value _wolf_saved_var
            ;;
        deactivate)
            if [ -z "${WOLF_ACTIVE_ENV-}" ]; then
                printf '%s\n' 'No WOLF environment is active.' >&2
                return 0
            fi
            unset WOLF_ACTIVE_ENV
            for _wolf_env_key in ${_WOLF_ACTIVE_ENV_VAR_NAMES-}; do
                _wolf_saved_var="_WOLF_SAVED_ENV_${_wolf_env_key}"
                if [ -n "${!_wolf_saved_var+x}" ]; then
                    if [ "${!_wolf_saved_var}" = "__WOLF_UNSET__" ]; then
                        unset "$_wolf_env_key"
                    else
                        export "${_wolf_env_key}=${!_wolf_saved_var}"
                    fi
                    unset "$_wolf_saved_var"
                fi
            done
            unset _WOLF_ACTIVE_ENV_VAR_NAMES _wolf_env_key _wolf_saved_var
            if [ -n "${_WOLF_ORIGINAL_PS1+x}" ]; then
                PS1=$_WOLF_ORIGINAL_PS1
                unset _WOLF_ORIGINAL_PS1
            fi
            ;;
        *)
            _wolf_command "$@"
            ;;
    esac
}

_wolf_complete() {
    local candidate
    COMPREPLY=()
    while IFS= read -r candidate; do
        [ -n "$candidate" ] && COMPREPLY+=("$candidate")
    done < <(_wolf_command _complete -- "${COMP_WORDS[@]:1}")
}

complete -F _wolf_complete wolf
