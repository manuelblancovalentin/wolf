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
            _wolf_command _shell-activate "$2" >/dev/null
            _wolf_status=$?
            if [ "$_wolf_status" -ne 0 ]; then
                return "$_wolf_status"
            fi
            if [ -z "${_WOLF_ORIGINAL_PS1+x}" ]; then
                _WOLF_ORIGINAL_PS1=${PS1-}
            fi
            PS1="${_WOLF_ORIGINAL_PS1} [${2}]"
            export WOLF_ACTIVE_ENV="$2"
            ;;
        deactivate)
            if [ -z "${WOLF_ACTIVE_ENV-}" ]; then
                printf '%s\n' 'No WOLF environment is active.' >&2
                return 0
            fi
            unset WOLF_ACTIVE_ENV
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
