# Check process variables exist
vars_to_check=( "${PROCESS}" "${PROCESS}_METAL_STACK_OPTIONS" "${_WOLF_PROCESS_ARGS_PROCESS}_DIGITAL_LIB_OPTIONS" "${_WOLF_PROCESS_ARGS_PROCESS}_IO_LIB_OPTIONS")
for vv in ${vars_to_check[@]} ; do 
    if [[ ! -v $vv ]]; then
        _wolf_error "Variable $vv should be defined before using this script. Please, define it by using \"wolf set $vv <VALUE>\" before adding this bucket script or trying to use the environment itself."
        return 1 
    fi
done

################################## 
# METAL STACK variable expansion
##################################
#TSMC65_PDK_HOME=


# # Source metal
# ms=${METAL_STACK}
# ms=$(echo "$ms" | tr -d '\\"')
# ms=`echo ${ms}`
# case $ms in 
#     9lmT2|"9lmT2")
#         METAL_STACK_DIR="1p9m6x1z1u"
#         ;;
#     *)
#         METAL_STACK_DIR=""
#         echo "[ERROR] - Invalid METALSTACK ${METAL_STACK}."
#         ;;
# esac


################################################################################################################################
#
# [@manuelbv]: NOTE OF CAUTION HERE 
#
# Because of the structure of this library, we are required to define the variable METAL_STACK_DIR here at some point
#   when sourcing this. The structure of metal_stack_dir is something like "1p<num_metal_layers>m<num_metal_layer - 3>x1z1u"
#   so we need to set this dynamically. For now, what we are doing here, is literally putting here the string
#   "${METAL_STACK_DIR}" which once the string is evaluated it will be changed by its actual value (which is defined)
#   when sourcing the env file for the specific project we want to apply the digital flow to.
#
###############################################################################################################################
# export TSMC65_CDS_SEARCHDIR="${TSMC65_PDK_HOME}"
# export TSMC65_PDK_CDSINIT="${TSMC65_PDK_HOME}/cds.lib"
# #export TSMC65_DEVICE_SET_CONFIG="/asic/cad/device_set.config"

# export TSMC65_PROCESS_SCRIPTS="/asic/flows/${FOUNDRY}/TSMC65/digital/stylus"
# export TSMC65_STYLUS_FLOW_TEMPLATE="${TSMC65_PROCESS_SCRIPTS}/flow.tsmc65.template.yaml"
# export TSMC65_STYLUS_SETUP_TEMPLATE="${TSMC65_PROCESS_SCRIPTS}/setup.tsmc65.template.yaml"

# # Global definitions
# export LIB_DIR="${TSMC65_LIB_DIR}"
# export IO_LIB_DIR="${TSMC65_IO_LIB_DIR}"
# export PDK_DIR="$TSMC65_PDK_HOME"
# export TECHDIR_DRC="$PDK_DIR/Calibre/drc"
# export TECHDIR_LVS="$PDK_DIR/Calibre/lvs"

# # Display info
# function tsmc65_vars() {
#     reset="\033[0m"
#     bold="\033[1m"
#     purple="\033[38;2;173;76;229m"
#     white="\033[0;38m"
#     green="\033[32m"
#     blue="\033[0;34m"
#     printf "\r${purple}------------------------------------------------------------------------------------------------------\n"
#     printf "Sourcing $0\033[0m\n"

#     printf " ${blue}TSMC65_LIB_DIR${white}: $TSMC65_LIB_DIR\n"
#     printf " ${blue}TSMC65_IO_LIB_DIR${white}: $TSMC65_IO_LIB_DIR\n"
#     printf " ${blue}TSMC65_PDK_VERSION${white}: $TSMC65_PDK_VERSION\n"
#     printf " ${blue}TSMC65_PDK_HOME${white}: $TSMC65_PDK_HOME\n"
#     printf " ${blue}TSMC65_CDS_SEARCHDIR${white}: $TSMC65_CDS_SEARCHDIR\n"
#     printf " ${blue}TSMC65_PDK_CDSINIT${white}: $TSMC65_PDK_CDSINIT\n"
#     printf " ${blue}METAL_STACK_DIR${white}: $METAL_STACK_DIR\n"

#     printf " ${blue}TSMC65_PROCESS_SCRIPTS${white}: $TSMC65_PROCESS_SCRIPTS\n"
#     printf " ${blue}TSMC65_STYLUS_FLOW_TEMPLATE${white}: $TSMC65_STYLUS_FLOW_TEMPLATE\n"
#     printf " ${blue}TSMC65_STYLUS_SETUP_TEMPLATE${white}: $TSMC65_STYLUS_SETUP_TEMPLATE\n"
    
#     printf " ${blue}LIB_DIR${white}: $LIB_DIR\n"
#     printf " ${blue}PDK_DIR${white}: $PDK_DIR\n"
#     printf " ${blue}TECHDIR_DRC${white}: $TECHDIR_DRC\n"
#     printf " ${blue}TECHDIR_LVS${white}: $TECHDIR_LVS\n"
#     printf "${purple}------------------------------------------------------------------------------------------------------\n"
# }

# tsmc65_vars