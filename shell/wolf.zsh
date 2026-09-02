# Zsh integration for WOLF. Source once per shell session or from ~/.zshrc.

# Remove the marker used by the first zsh integration revision, which appended
# to PROMPT and could appear immediately before the command line in multiline
# themes.  Keep WOLF's marker in RPROMPT instead.
if [ -n "${_WOLF_ZSH_MARKER-}" ]; then
    PROMPT=${PROMPT%" ${_WOLF_ZSH_MARKER}"}
fi
unset _WOLF_ZSH_BASE_PROMPT _WOLF_ZSH_MARKER

_wolf_command() {
    command wolf "$@"
}

_wolf_zsh_prompt() {
    [ -n "${WOLF_ACTIVE_ENV-}" ] || return 0
    if [ -n "${_WOLF_ZSH_RPROMPT_MARKER-}" ]; then
        RPROMPT=${RPROMPT%" ${_WOLF_ZSH_RPROMPT_MARKER}"}
    fi
    _WOLF_ZSH_BASE_RPROMPT=$RPROMPT
    _WOLF_ZSH_RPROMPT_MARKER="[%F{yellow}${WOLF_ACTIVE_ENV}%f]"
    RPROMPT="${RPROMPT} ${_WOLF_ZSH_RPROMPT_MARKER}"
}

wolf() {
    case "${1-}" in
        activate)
            if [ "$#" -ne 2 ]; then
                _wolf_command activate "$@"
                return $?
            fi
            _wolf_command _shell-activate "$2" >/dev/null
            local wolf_status=$?
            [ "$wolf_status" -eq 0 ] || return "$wolf_status"
            export WOLF_ACTIVE_ENV="$2"
            _wolf_zsh_prompt
            ;;
        deactivate)
            if [ -z "${WOLF_ACTIVE_ENV-}" ]; then
                print -u2 -- 'No WOLF environment is active.'
                return 0
            fi
            unset WOLF_ACTIVE_ENV
            if [ -n "${_WOLF_ZSH_BASE_RPROMPT+x}" ]; then
                RPROMPT=$_WOLF_ZSH_BASE_RPROMPT
                unset _WOLF_ZSH_BASE_RPROMPT _WOLF_ZSH_RPROMPT_MARKER
            fi
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
