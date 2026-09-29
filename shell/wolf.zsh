# Zsh integration for WOLF. Source once per shell session or from ~/.zshrc.

# Remove the marker used by the first zsh integration revision, which appended
# to PROMPT and could appear immediately before the command line in multiline
# themes.  Keep WOLF's marker in RPROMPT instead.
if [ -n "${_WOLF_ZSH_MARKER-}" ]; then
    PROMPT=${PROMPT%" ${_WOLF_ZSH_MARKER}"}
fi
if [ -n "${_WOLF_ZSH_BASE_RPROMPT+x}" ]; then
    RPROMPT=$_WOLF_ZSH_BASE_RPROMPT
fi
unset _WOLF_ZSH_BASE_PROMPT _WOLF_ZSH_MARKER
unset _WOLF_ZSH_BASE_RPROMPT _WOLF_ZSH_RPROMPT_MARKER

_wolf_command() {
    command wolf "$@"
}

_wolf_zsh_prompt() {
    if [ -z "${WOLF_ACTIVE_ENV-}" ]; then
        if [ -n "${_WOLF_ZSH_BASE_RPROMPT+x}" ]; then
            RPROMPT=$_WOLF_ZSH_BASE_RPROMPT
            unset _WOLF_ZSH_BASE_RPROMPT _WOLF_ZSH_RPROMPT_MARKER
        fi
        return 0
    fi
    if [ -z "${_WOLF_ZSH_BASE_RPROMPT+x}" ]; then
        _WOLF_ZSH_BASE_RPROMPT=$RPROMPT
    fi
    _WOLF_ZSH_RPROMPT_MARKER="[%F{yellow}${WOLF_ACTIVE_ENV}%f]"
    RPROMPT="${_WOLF_ZSH_BASE_RPROMPT} ${_WOLF_ZSH_RPROMPT_MARKER}"
}

wolf() {
    case "${1-}" in
        activate)
            if [ "$#" -ne 2 ]; then
                _wolf_command activate "$@"
                return $?
            fi
            local _wolf_activate_json
            _wolf_activate_json=$(_wolf_command _shell-activate "$2")
            local wolf_status=$?
            [ "$wolf_status" -eq 0 ] || return "$wolf_status"
            export WOLF_ACTIVE_ENV="$2"
            # Export the environment's declared env: map. Each key's prior
            # value (or absence) is saved once so deactivate can restore it,
            # the same save-once/restore-on-deactivate pattern used for the
            # RPROMPT marker below.
            _WOLF_ACTIVE_ENV_VAR_NAMES=""
            local _wolf_env_key _wolf_env_value _wolf_saved_var
            while IFS= read -r -d '' _wolf_env_key && IFS= read -r -d '' _wolf_env_value; do
                _wolf_saved_var="_WOLF_SAVED_ENV_${_wolf_env_key}"
                if (( ! ${(P)+_wolf_saved_var} )); then
                    if (( ${(P)+_wolf_env_key} )); then
                        typeset -g "${_wolf_saved_var}=${(P)_wolf_env_key}"
                    else
                        typeset -g "${_wolf_saved_var}=__WOLF_UNSET__"
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
            _wolf_zsh_prompt
            ;;
        deactivate)
            if [ -z "${WOLF_ACTIVE_ENV-}" ]; then
                print -u2 -- 'No WOLF environment is active.'
                return 0
            fi
            unset WOLF_ACTIVE_ENV
            local _wolf_env_key _wolf_saved_var
            for _wolf_env_key in ${=_WOLF_ACTIVE_ENV_VAR_NAMES-}; do
                _wolf_saved_var="_WOLF_SAVED_ENV_${_wolf_env_key}"
                if (( ${(P)+_wolf_saved_var} )); then
                    if [ "${(P)_wolf_saved_var}" = "__WOLF_UNSET__" ]; then
                        unset "$_wolf_env_key"
                    else
                        export "${_wolf_env_key}=${(P)_wolf_saved_var}"
                    fi
                    unset "$_wolf_saved_var"
                fi
            done
            unset _WOLF_ACTIVE_ENV_VAR_NAMES
            _wolf_zsh_prompt
            ;;
        *)
            _wolf_command "$@"
            ;;
    esac
}

_wolf_zsh_completion_candidates() {
    local output
    output=$(_wolf_command _complete -- "$@") || return $?
    if [ -n "$output" ]; then
        reply=("${(@f)output}")
    else
        reply=()
    fi
}

_wolf_complete() {
    local index
    local -a query reply
    for (( index = 2; index <= CURRENT; index++ )); do
        query+=("${words[index]}")
    done
    _wolf_zsh_completion_candidates "${query[@]}" || return $?
    (( ${#reply} )) && _describe 'WOLF value' reply
}

autoload -Uz add-zsh-hook
add-zsh-hook precmd _wolf_zsh_prompt
_wolf_zsh_prompt

if (( $+functions[compdef] )); then
    compdef _wolf_complete wolf
fi

# Announce presence in the dots welcome table, if dots is loaded. This is
# presentation-only: dots does not discover or manage WOLF.
if (( $+functions[dots_register_tool] )); then
    local -a _wolf_info=()
    man -w wolf >/dev/null 2>&1 && _wolf_info+=('man wolf')
    _wolf_info+=('tldr wolf')
    dots_register_tool wolf '🐺' \
        'Reproducible environment/execution manager for ASIC implementation flows.' \
        "${_wolf_info[@]}"
    unset _wolf_info
fi
