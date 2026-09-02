# Zsh integration for WOLF. Source once per shell session or from ~/.zshrc.

_wolf_command() {
    command wolf "$@"
}

_wolf_zsh_prompt() {
    [ -n "${WOLF_ACTIVE_ENV-}" ] || return 0
    if [ -n "${_WOLF_ZSH_MARKER-}" ]; then
        PROMPT=${PROMPT%" ${_WOLF_ZSH_MARKER}"}
    fi
    _WOLF_ZSH_BASE_PROMPT=$PROMPT
    _WOLF_ZSH_MARKER="[%F{yellow}${WOLF_ACTIVE_ENV}%f]"
    PROMPT="${PROMPT} ${_WOLF_ZSH_MARKER}"
}

wolf() {
    case "${1-}" in
        activate)
            if [ "$#" -ne 2 ]; then
                _wolf_command activate "$@"
                return $?
            fi
            _wolf_command _shell-activate "$2" >/dev/null
            local status=$?
            [ "$status" -eq 0 ] || return "$status"
            export WOLF_ACTIVE_ENV="$2"
            _wolf_zsh_prompt
            ;;
        deactivate)
            if [ -z "${WOLF_ACTIVE_ENV-}" ]; then
                print -u2 -- 'No WOLF environment is active.'
                return 0
            fi
            unset WOLF_ACTIVE_ENV
            if [ -n "${_WOLF_ZSH_BASE_PROMPT+x}" ]; then
                PROMPT=$_WOLF_ZSH_BASE_PROMPT
                unset _WOLF_ZSH_BASE_PROMPT _WOLF_ZSH_MARKER
            fi
            ;;
        *)
            _wolf_command "$@"
            ;;
    esac
}

autoload -Uz add-zsh-hook
add-zsh-hook precmd _wolf_zsh_prompt
