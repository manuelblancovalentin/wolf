# Print source info
hline="-----------------------------------------------------------------------------------------------------------------------"
reset="\033[0m"
bold="\033[1m"
purple="\033[38;2;173;76;229m"
white="\033[0;38m"
green="\033[32m"
blue="\033[0;34m"
function printArray () {
    if [ -z "$1" ]; then
        printf "\r${purple} ${hline}-${reset}\n"
    else
        title="$1"
        printf "\r${purple} ${hline:0:-${#title}} $title${reset}\n"
    fi
    for key in "${@:2}";
    do  
        cmd="echo \$$key"
        val=$(eval $cmd)
        printf "${purple}| ${blue}$key${white}: $val\n"
    done
}


# Make sure DESIGN_NAME variable exists
vars_to_check=( "DESIGN_NAME" "METAL_STACK" "PROJ_DIR" "PROCESS" "VTHS")
for vv in ${vars_to_check[@]} ; do 
    if [[ ! -v $vv ]]; then
        _wolf_error "Variable $vv should be defined before using this script. Please, define it by using \"wolf set $vv <VALUE>\" before adding this bucket script or trying to use the environment itself."
        return 1 
    fi
done

# Print top separator
printArray
printf "${purple}|\n| SOURCING ${BASH_SOURCE[0]}\n|${reset}\n"

# Print title
vars_to_print=("USER")
printArray "" "${vars_to_print[@]}"

# Main vars
WORKSPACE_DIR="${PROJ_DIR}/workspace"
INPUTS_DIR="${PROJ_DIR}/inputs"

# Inputs
FLOORPLAN_FILE="${INPUTS_DIR}/floorplans/${DESIGN_NAME}/${DESIGN_NAME}.fp"
FLOORPLAN_IO_FILE="${INPUTS_DIR}/floorplans/${DESIGN_NAME}/${DESIGN_NAME}.save.io"
CONSTRAINTS_FILE="${INPUTS_DIR}/constraints/${DESIGN_NAME}.constraints.sdc"

# Other configs
if [[ ! -f "$YAML_TEMPLATE_FILE" ]]; then
    YAML_TEMPLATE_FILE="${INPUTS_DIR}/env/${DESIGN_NAME}/setup.${DESIGN_NAME}.template.yaml"
fi

# Metal Stack
ms=${METAL_STACK/thick/}
ms=$(echo "$ms" | tr -d '\\"')
ms=`echo ${ms}`
case $ms in 
    "7M_2Mx_4Cx_1Ix_LB"|"7M_2Mx_3Cx_1Ix_1Ox_LB"|"8M_2Mx_5Cx_1Ix_LB"|"8M_2Mx_4Cx_2Ix_LB"|"8M_2Mx_4Cx_1Ix_1Ox_LB"|"9M_2Mx_5Cx_1Jx_1Ox_LB"|"9M_2Mx_3Cx_2Bx_1Ix_1Ox_LB__eMRAM"|"9M_2Mx_5Cx_2Ix_LB"|"9M_2Mx_3Cx_2Bx_1Ix_1Ox_LB"|"10M_2Mx_4Cx_2Bx_2Jx_LB"|"10M_2Mx_4Cx_2Bx_2Jx_LB__eMRAM"|"10M_2Mx_5Cx_1Jx_2Qx_LB"|"10M_2Mx_6Cx_2Ix_LB")
        METAL_STACK_NUM_LAYERS="${METAL_STACK:0:1}"
        METAL_STACK_TECH="${METAL_STACK: -1}"
        METAL_STACK_DIR="${METAL_STACK}" #"1p${METAL_STACK_NUM_LAYERS}m$((${METAL_STACK_NUM_LAYERS} - 3))x1z1u"
        ;;
    *)
         _wolf_error "Unknown metal_stack \"$METAL_STACK\". Valid options are:\n\t7M_2Mx_4Cx_1Ix_LB\n\t7M_2Mx_3Cx_1Ix_1Ox_LB\n\t8M_2Mx_5Cx_1Ix_LB\n\t8M_2Mx_4Cx_2Ix_LB\n\t8M_2Mx_4Cx_1Ix_1Ox_LB\n\t9M_2Mx_5Cx_1Jx_1Ox_LB\n\t9M_2Mx_3Cx_2Bx_1Ix_1Ox_LB__eMRAM\n\t9M_2Mx_5Cx_2Ix_LB\n\t9M_2Mx_3Cx_2Bx_1Ix_1Ox_LB\n\t10M_2Mx_4Cx_2Bx_2Jx_LB\n\t10M_2Mx_4Cx_2Bx_2Jx_LB__eMRAM\n\t10M_2Mx_5Cx_1Jx_2Qx_LB\n\t10M_2Mx_6Cx_2Ix_LB"
        return 1
        ;;
esac 

# We are only going to use regular vt and 9 track
# VTHS=( "rvt" )
THRESHOLD_VOLTAGES=${VTHS[@]}
TRACKS="8T"

# It is important to change the PDK_DIR to the right dir according to the METAL_STACK
#PDK_DIR="$PDK_DIR/1p9m6x1z1u"

# RTL FILES (same for all FLORA modules, that is, flora_top, digTest, etc.)
RTL_YAML_FILE="${INPUTS_DIR}/env/${DESIGN_NAME}/${DESIGN_NAME}.src.yaml"


# Print rest of info and exit
vars_to_set=()
vars_to_print=("PROJ_DIR" "PROCESS_SCRIPTS" "WORKSPACE_DIR" "INPUTS_DIR" "FLOORPLAN_FILE" "FLOORPLAN_IO_FILE" "CONSTRAINTS_FILE" "METAL_STACK" "THRESHOLD_VOLTAGES" "TRACKS")
vars_to_set+=( "${vars_to_print[@]}" )
printArray "Main project vars" "${vars_to_print[@]}"

vars_to_print=("FLOW_YAML_FILE" "YAML_TEMPLATE_FILE" "RTL_YAML_FILE")
vars_to_set+=( "${vars_to_print[@]}" )
printArray "Stylus scripting vars" "${vars_to_print[@]}"

# Final separator
printArray

# Setup vars wolf-wise
for vv in ${vars_to_set[@]}; do      
    vw="\$${vv}"
    vw=`echo "$vw" | tr -d "\""`
    vw=`eval echo $vw`
    wolf set "$vv" "${vw[@]}"
done
#echo "${VTHS[@]}"
wolf set VTHS "${VTHS[@]}"
wolf set THRESHOLD_VOLTAGES "${VTHS[@]}"

unset vars_to_print
unset printArray
unset cmd
unset vv 
unset vars_to_set
