#!/bin/bash
_wolf () {
  COMPREPLY=()
  local cur=${COMP_WORDS[COMP_CWORD]}
  local prev=${COMP_WORDS[COMP_CWORD-1]}

  case "$prev" in
   env)
       COMPREPLY=( $( compgen -W "list create remove activate deactivate update reload status history" -- $cur ) )
       return 0
       ;;
   activate)
       # List all environments
       _WOLF_ENV_DIR="${HOME}/.wolf/envs"
       _WOLF_ENVS_LIST=`find "$_WOLF_ENV_DIR" -maxdepth 1 -mindepth 1 -type d | sort -n | xargs -I{} basename {}`
       COMPREPLY=( $( compgen -W "$_WOLF_ENVS_LIST" -- $cur ) )
       return 0
       ;;
    *)
       COMPREPLY=($(compgen -W "run env create remove activate deactivate update reload history" -- $cur ) )
       return 0
       ;;
 esac

}
complete -F _wolf wolf
