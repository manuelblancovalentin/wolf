#!/bin/bash

#####################################################################################
# MAKE SURE WE HAVE ALL SOURCE CODE WE NEED
#####################################################################################
_WOLF_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
_WOLF_DIR=`dirname "$_WOLF_DIR"`
_WOLF_BIN="${_WOLF_DIR}/bin"
if [[ ! -d ${_WOLF_BIN} || ! -f "${_WOLF_BIN}/utils" || ! -f "${_WOLF_BIN}/wolf.run" || ! -f "${_WOLF_BIN}/wolf.ipman" || ! -f "${_WOLF_BIN}/wolf.env" ]]; then
    printf "\033[1;7;31m [ERROR] - Invalid installation. Some binary files required to run wolf are either missing or unaccessible. Contact your cadadmin to fix this."
fi

######################################################################################
# Source definitions
#####################################################################################
source "${_WOLF_BIN}/defs"

#####################################################################################
# Source utilities
#####################################################################################
source "${_WOLF_BIN}/utils"

######################################################################################
# Source wolf.env
#####################################################################################
source "${_WOLF_BIN}/wolf.env"

######################################################################################
# Source wolf.ipman
#####################################################################################
source "${_WOLF_BIN}/wolf.ipman"

#####################################################################################
# MAIN WOLF ALIAS
#####################################################################################
wolf () {

    ###########################################
    # Init vars to default values
    ##########################################
    _WOLF_INIT_ARGS_COMMAND=

    ###########################################
    # Parse flags
    #
    ##########################################
    _WOLF_INIT_ARGS_POSITIONAL=()
    _WOLF_INIT_ARGS_INDEX=1
    while [[ $# -gt 0 ]]; do
        _WOLF_INIT_ARGS_KEY="$1"
        case $_WOLF_INIT_ARGS_KEY in
            -h|--help)
                if [[ $_WOLF_INIT_ARGS_INDEX -eq 1 ]]; then
                    cprintf "$_WOLF_HEADER\n"
                    # Help dialog
                    echo -e "Usage $(basename $BASH_SOURCE) [COMMANDS]... [EXTRA_ARGUMENTS]..."
                    echo "Wolf utility for digital flow management."
                    echo ""
                    echo "Main arguments taken $(basename $BASH_SOURCE):"
                    echo -e "\t-h, --help\t\tInvokes this dialog.\n"
                    echo "Commands:"
                    echo -e "\trun\t\tInvokes wolf.run (old flows.run) to run a specific digital flow."
                    return 0
                else
                    _WOLF_INIT_ARGS_POSITIONAL+=("$1")
                fi
                shift
                ;;
            run|env|create|remove|activate|deactivate|update|reload|history|ipman)
                _WOLF_INIT_ARGS_COMMAND="${_WOLF_INIT_ARGS_KEY^^}"
                shift
                ;;
        *)    # unknown option
            _WOLF_INIT_ARGS_POSITIONAL+=("$1") # save it in an array for later
            if [[ "$2" != "-"* ]]; then
                _WOLF_INIT_ARGS_POSITIONAL+=("$2")
                shift # past value
            fi
            shift # past argument
            ;;
        esac
        let _WOLF_INIT_ARGS_INDEX++
    done
    set -- "${_WOLF_INIT_ARGS_POSITIONAL[@]}" # restore positional parameters

    #############################################
    # Invoke _WOLF_INIT_ARGS_COMMAND
    #
    ############################################
    case $_WOLF_INIT_ARGS_COMMAND in
        RUN)
            # Parse all the variables that have to be passed to wolf.run; in case they exist in the current environment.
            _WOLF_INIT_ARGS_DEDUCED_ENV_VARS=()
            if [[ ! -z $WOLF_ENV_NAME ]]; then 
                if [[ -v PROCESS ]]; then _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("--process"); _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("$PROCESS"); fi
                if [[ -v DESIGN_NAME ]]; then _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("--design"); _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("$DESIGN_NAME"); fi
                if [[ -v RUNTAG ]]; then _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("--runtag"); _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("$RUNTAG"); fi
                if [[ -v YAML_TEMPLATE_FILE ]]; then _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("--conf"); _WOLF_INIT_ARGS_DEDUCED_ENV_VARS+=("$YAML_TEMPLATE_FILE"); fi
            fi
            if [[ -v WOLF_ENV_DIR && -f "$WOLF_ENV_DIR/vars.env" ]]; then 
                _WOLF_INIT_ARGS_CMD=`grep -v '#.*' $WOLF_ENV_DIR/vars.env | xargs`
                _WOLF_INIT_ARGS_CMD="${_WOLF_INIT_ARGS_CMD} ${_WOLF_BIN}/wolf.run "
                for v in "${_WOLF_INIT_ARGS_DEDUCED_ENV_VARS[@]}"; do 
                    _WOLF_INIT_ARGS_CMD="${_WOLF_INIT_ARGS_CMD} $v"
                done
                for v in "${_WOLF_INIT_ARGS_POSITIONAL[@]}"; do 
                    _WOLF_INIT_ARGS_CMD="${_WOLF_INIT_ARGS_CMD} $v"
                done
                echo "$_WOLF_INIT_ARGS_CMD"
                eval "$_WOLF_INIT_ARGS_CMD"
            else
                ${_WOLF_BIN}/wolf.run "$_WOLF_INIT_ARGS_DEDUCED_ENV_VARS[@]" "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            fi
            ;;
        IPMAN)
            # Call wolf ip-manager
            _wolf_ip_manager "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        ENV)
            # Call wolf env 
            _wolf_env "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        CREATE)
            # Call wolf env 
            _wolf_env create "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        REMOVE)
            # Call wolf env 
            _wolf_env remove "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        ACTIVATE)
            # Call wolf env 
            _wolf_env activate "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        DEACTIVATE)
            # Call wolf env 
            _wolf_env deactivate "$WOLF_ENV_NAME" "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        UPDATE)
            # Call wolf env 
            _wolf_env update "$WOLF_ENV_NAME" "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        RELOAD)
            # Call wolf env 
            _wolf_env reload "$WOLF_ENV_NAME" "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        HISTORY)
             # Call wolf env 
            _wolf_env "history" "$WOLF_ENV_NAME" "${_WOLF_INIT_ARGS_POSITIONAL[@]}"
            ;;
        *)
            _wolf_error "Invalid command passed to wolf. Wolf requires at least 1 command to be executed. Valid commands are: \"run\", \"env\""
            ;;
    esac
}

######################################################################################
# Source autocompletion script
#####################################################################################
source "${_WOLF_BIN}/wolf.autocomplete.sh"
