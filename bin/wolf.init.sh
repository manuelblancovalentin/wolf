#!/bin/bash

#####################################################################################
# MAKE SURE WE HAVE ALL SOURCE CODE WE NEED
#####################################################################################
WOLF_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WOLF_DIR=`dirname "$WOLF_DIR"`
WOLF_BIN="${WOLF_DIR}/bin"
if [[ ! -d ${WOLF_BIN} || ! -f "${WOLF_BIN}/utils" || ! -f "${WOLF_BIN}/wolf.run" ]]; then
    printf "\033[1;7;31m [ERROR] - Invalid installation. Some binary files required to run wolf are either missing or unaccessible. Contact your cadadmin to fix this."
fi

######################################################################################
# Source definitions
#####################################################################################
source "${WOLF_BIN}/defs"

#####################################################################################
# Source utilities
#####################################################################################
source "${WOLF_BIN}/utils"

######################################################################################
# Source wolf.env
#####################################################################################
source "${WOLF_BIN}/wolf.env"

#####################################################################################
# MAIN WOLF ALIAS
#####################################################################################
wolf () {

    ###########################################
    # Init vars to default values
    #
    ##########################################
    COMMAND=

    ###########################################
    # Parse flags
    #
    ##########################################
    POSITIONAL=()
    index=1
    while [[ $# -gt 0 ]]; do
        key="$1"
        case $key in
            -h|--help)
                if [[ $index -eq 1 ]]; then
                    cprintf "$h\n"
                    # Help dialog
                    echo -e "Usage $(basename $BASH_SOURCE) [COMMANDS]... [EXTRA_ARGUMENTS]..."
                    echo "Wolf utility for digital flow management."
                    echo ""
                    echo "Main arguments taken $(basename $BASH_SOURCE):"
                    echo -e "\t-h, --help\t\tInvokes this dialog.\n"
                    echo "Commands:"
                    echo -e "\trun\t\tInvokes wolf.run (old flows.run) to run a specific digital flow."
                else
                    POSITIONAL+=("$1")
                fi
                shift
                ;;
            run|env|create|remove|activate|deactivate|update|reload)
                COMMAND="${key^^}"
                shift
                ;;
        *)    # unknown option
            POSITIONAL+=("$1") # save it in an array for later
            POSITIONAL+=("$2")
            shift # past argument
            shift # past value
            ;;
        esac
        let index++
    done
    set -- "${POSITIONAL[@]}" # restore positional parameters

    #############################################
    # Invoke COMMAND
    #
    ############################################
    case $COMMAND in
        RUN)
            # Parse all the variables that have to be passed to wolf.run; in case they exist in the current environment.
            DEDUCED_ENV_VARS=()
            if [[ ! -z $WOLF_ENV_NAME ]]; then 
                if [[ -v PROCESS ]]; then DEDUCED_ENV_VARS+=("--process"); DEDUCED_ENV_VARS+=("$PROCESS"); fi
                if [[ -v DESIGN_NAME ]]; then DEDUCED_ENV_VARS+=("--design"); DEDUCED_ENV_VARS+=("$DESIGN_NAME"); fi
                if [[ -v RUNTAG ]]; then DEDUCED_ENV_VARS+=("--runtag"); DEDUCED_ENV_VARS+=("$RUNTAG"); fi
                if [[ -v YAML_TEMPLATE_FILE ]]; then DEDUCED_ENV_VARS+=("--conf"); DEDUCED_ENV_VARS+=("$YAML_TEMPLATE_FILE"); fi
            fi
            if [[ -v WOLF_ENV_DIR && -f "$WOLF_ENV_DIR/vars.env" ]]; then 
                cmd=`grep -v '#.*' $WOLF_ENV_DIR/vars.env | xargs`
                cmd="${cmd} ${WOLF_BIN}/wolf.run "
                for v in "${DEDUCED_ENV_VARS[@]}"; do 
                    cmd="${cmd} $v"
                done
                for v in "${POSITIONAL[@]}"; do 
                    cmd="${cmd} $v"
                done
                echo "$cmd"
                eval $cmd
            else
                ${WOLF_BIN}/wolf.run "$DEDUCED_ENV_VARS[@]" "${POSITIONAL[@]}"
            fi
            ;;
        ENV)
            # Call wolf env 
            _wolf_env "${POSITIONAL[@]}"
            ;;
        CREATE)
            # Call wolf env 
            _wolf_env create "${POSITIONAL[@]}"
            ;;
        REMOVE)
            # Call wolf env 
            _wolf_env remove "${POSITIONAL[@]}"
            ;;
        ACTIVATE)
            # Call wolf env 
            _wolf_env activate "${POSITIONAL[@]}"
            ;;
        DEACTIVATE)
            # Call wolf env 
            _wolf_env deactivate "$WOLF_ENV_NAME" "${POSITIONAL[@]}"
            ;;
        UPDATE)
            # Call wolf env 
            _wolf_env update "$WOLF_ENV_NAME" "${POSITIONAL[@]}"
            ;;
        RELOAD)
            # Call wolf env 
            _wolf_env reload "$WOLF_ENV_NAME" "${POSITIONAL[@]}"
            ;;
        *)
            _wolf_error "Invalid command passed to wolf. Wolf requires at least 1 command to be executed. Valid commands are: \"run\", \"env\""
            ;;
    esac
}