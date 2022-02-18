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
   activate|-n|--name)
       # List all environments
       _WOLF_ENV_DIR="${HOME}/.wolf/envs"
       _WOLF_ENVS_LIST=`find "$_WOLF_ENV_DIR" -maxdepth 1 -mindepth 1 -type d | sort -n | xargs -I{} basename {}`
       COMPREPLY=( $( compgen -W "$_WOLF_ENVS_LIST" -- $cur ) )
       return 0
       ;;
   create|remove)
       COMPREPLY=( $( compgen -W "--name" -- $cur ) )
       return 0
       ;;
   run)
      # Flowtool flags
      COMPREPLY=($(compgen -W "-from -to -interactive -interactive_run -predict -status -db -dist -run_tag -branch -directory -display -enabled -files -flow -inject_tcl -isolate -metrics_file -no_check -no_gui -no_db -ref_run -reset -simple_output -verbose -version" -- $cur ) )
      return 0
      ;;
   -from|-to|-flow)
      COMPREPLY=()
      if [ -z  $WOLF_ENV_DIR ]; then 
         echo ""
         _wolf_error "No wolf environment detected. Please, activate an environment first and then try autocomplete again."
         return 0
      else 
         if [[ -L "$WOLF_ENV_DIR/flow.sum.latest" ]]; then
            t=`cat "$WOLF_ENV_DIR/flow.sum.latest"`
            COMPREPLY=($(compgen -W "$t" -- $cur ) )
            
         fi
      fi
      return 0
      ;;
    *)
       COMPREPLY=($(compgen -W "run env create remove activate deactivate update reload history --help" -- $cur ) )
       return 0
       ;;
 esac

}
complete -F _wolf wolf
