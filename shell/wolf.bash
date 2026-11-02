# Bash integration for WOLF. Source once per shell session or from ~/.bashrc.

_wolf_command() {
    command wolf "$@"
}

# proj (kona's project/environment manager) owns the prompt while one of its
# own environments is active, and draws a wolf emoji of its own in that case
# (PROJ_PROMPT_TOKENS, space-separated token names, set while proj is active
# and removed on proj deactivate -- see docs/CLI.md's "Active environments").
# Never calls proj itself -- it only reads the variable proj already exports.
_wolf_hidden_by_proj() {
    case " ${PROJ_PROMPT_TOKENS-} " in
        *" wolf "*) return 0 ;;
        *) return 1 ;;
    esac
}

# Recomputed at every prompt (via PROMPT_COMMAND below), not frozen at
# activation time, so a `wolf activate`/`wolf deactivate` typed while a proj
# environment is active, or a `proj activate`/`proj deactivate` typed while a
# wolf environment is active, both take effect at the next prompt either way.
_wolf_bash_prompt() {
    if [ -z "${WOLF_ACTIVE_ENV-}" ]; then
        if [ -n "${_WOLF_ORIGINAL_PS1+x}" ]; then
            PS1=$_WOLF_ORIGINAL_PS1
            unset _WOLF_ORIGINAL_PS1
        fi
        return 0
    fi
    if [ -z "${_WOLF_ORIGINAL_PS1+x}" ]; then
        _WOLF_ORIGINAL_PS1=${PS1-}
    fi
    if _wolf_hidden_by_proj; then
        PS1=$_WOLF_ORIGINAL_PS1
    else
        PS1="\[\033[38;5;135m\]«${WOLF_ACTIVE_ENV}»\[\033[0m\] ${_WOLF_ORIGINAL_PS1}"
    fi
}

# Idempotent: adds _wolf_bash_prompt to PROMPT_COMMAND exactly once, in
# whichever form (string or array, bash >=5.1 supports both) it already has.
_wolf_bash_install_prompt_command() {
    if declare -p PROMPT_COMMAND 2>/dev/null | grep -q '^declare -a'; then
        local _wolf_already=0 _wolf_item
        for _wolf_item in "${PROMPT_COMMAND[@]}"; do
            [ "$_wolf_item" = "_wolf_bash_prompt" ] && _wolf_already=1
        done
        [ "$_wolf_already" -eq 1 ] || PROMPT_COMMAND+=(_wolf_bash_prompt)
    else
        case ";${PROMPT_COMMAND-};" in
            *";_wolf_bash_prompt;"*) ;;
            *) PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_wolf_bash_prompt" ;;
        esac
    fi
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
            export WOLF_ACTIVE_ENV="$2"
            _wolf_bash_prompt
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
            _wolf_bash_prompt
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

_wolf_bash_install_prompt_command
_wolf_bash_prompt
