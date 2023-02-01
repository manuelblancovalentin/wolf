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
        cmd="echo \${$key[@]}"
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
# 1p10m_5x2y2r 1p10m_5x2y2z 1p9m_6x1z1u
ms=${METAL_STACK}
ms=$(echo "$ms" | tr -d '\\"')
ms=`echo ${ms}`
case $ms in 
    1p10m_5x2y2r|"1p10m_5x2y2r")
        METAL_STACK_NUM_LAYERS="10"
        METAL_STACK_TECH="R"
        METAL_STACK_DIR="1p10m_5x2y2r"
        ;;
    1p10m_5x2y2z|"1p10m_5x2y2z")
        METAL_STACK_NUM_LAYERS="10"
        METAL_STACK_TECH="Z"
        METAL_STACK_DIR="1p10m_5x2y2z"
        ;;
    1p9m_6x1z1u|"1p9m_6x1z1u")
        METAL_STACK_NUM_LAYERS="9"
        METAL_STACK_TECH="U"
        METAL_STACK_DIR="1p9m_6x1z1u"
        ;;
    *)
         _wolf_error "Unknown metal_stack \"$METAL_STACK\". Valid options are: 1p10m_5x2y2r, 1p10m_5x2y2z, 1p9m_6x1z1u"
        return 1
        ;;
esac 


# We are only going to use regular vt and 9 track
# VTHS=( "rvt" )
THRESHOLD_VOLTAGES=( ${VTHS[@]} )
TRACKS="9T"

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
