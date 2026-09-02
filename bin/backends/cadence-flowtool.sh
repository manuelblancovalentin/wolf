#!/bin/bash

WOLF_BACKEND_NAME="cadence-flowtool"
WOLF_BACKEND_DESCRIPTION="Cadence Flowtool/Genus/Innovus compatibility backend"

_wolf_backend_validate() {
    local executable variable value
    for executable in flowtool shyaml python3; do
        if ! command -v "$executable" >/dev/null 2>&1; then
            _wolf_error "Backend \"$WOLF_BACKEND_NAME\" requires $executable, but it is unavailable."
            return 1
        fi
    done

    for variable in \
        RTL_YAML_FILE \
        YAML_TEMPLATE_FILE \
        PROCESS_SETUP_COMMON_TEMPLATE \
        PROCESS_SETUP_HOST_TEMPLATE \
        PROCESS_FLOW_TEMPLATE; do
        value="${!variable}"
        if [[ -z "$value" || ( ! -f "$value" && ! -L "$value" ) ]]; then
            _wolf_error "Backend \"$WOLF_BACKEND_NAME\" requires a valid $variable file."
            return 1
        fi
    done
}

_wolf_backend_plan() {
    RTL_CONF=
    RTL_SV_FILES_ARGS=""
    RTL_SV_FILES=""
    RTL_VHDL_FILES_ARGS=""
    RTL_VHDL_FILES=""

    local key
    while read -r key; do
        if [[ "$key" =~ ^(init_hdl_search_path).*$ ]]; then
            INIT_HDL_SEARCH_PATH=$(shyaml get-values "RTL.${DESIGN_NAME}.init_hdl_search_path" < "$RTL_YAML_FILE" 2>/dev/null)
            INIT_HDL_SEARCH_PATH=$(eval echo "$INIT_HDL_SEARCH_PATH")
        elif [[ "$key" =~ ^(systemverilog).*$ ]]; then
            RTL_SV_FILES=$(shyaml get-values "RTL.${DESIGN_NAME}.${key}.files" < "$RTL_YAML_FILE" 2>/dev/null)
            RTL_SV_FILES=$(eval echo "$RTL_SV_FILES")
            RTL_SV_FILES_ARGS=$(shyaml get-values "RTL.${DESIGN_NAME}.${key}.args" < "$RTL_YAML_FILE" 2>/dev/null)
            RTL_SV_FILES_ARGS=$(eval echo "$RTL_SV_FILES_ARGS")
        elif [[ "$key" =~ ^(vhdl).*$ ]]; then
            RTL_VHDL_FILES=$(shyaml get-values "RTL.${DESIGN_NAME}.${key}.files" < "$RTL_YAML_FILE" 2>/dev/null)
            RTL_VHDL_FILES=$(eval echo "$RTL_VHDL_FILES")
            RTL_VHDL_FILES_ARGS=$(shyaml get-values "RTL.${DESIGN_NAME}.${key}.args" < "$RTL_YAML_FILE" 2>/dev/null)
            RTL_VHDL_FILES_ARGS=$(eval echo "$RTL_VHDL_FILES_ARGS")
        fi
    done < <(shyaml keys "RTL.${DESIGN_NAME}" < "$RTL_YAML_FILE")

    RTL_VHDL_FILES_CAT=$(vectorize "$RTL_VHDL_FILES")
    RTL_SV_FILES_CAT=$(vectorize "$RTL_SV_FILES")
    INIT_HDL_SEARCH_PATH_CAT=$(vectorize "$INIT_HDL_SEARCH_PATH")
    CONSTRAINTS_FILE_CAT=$(vectorize "$CONSTRAINTS_FILE")

    HDL_SEARCH_PATH="$INIT_HDL_SEARCH_PATH_CAT"
    HDL_SEARCH_PATH="${HDL_SEARCH_PATH//${DATA_DIR}/÷yellow÷\$DATA_DIR÷÷}"
    RTL_FILES="${RTL_SV_FILES_CAT} ${RTL_VHDL_FILES_CAT}"
    RTL_FILES="${RTL_FILES//${INIT_HDL_SEARCH_PATH_CAT}\//}"
    RTL_FILES="÷yellow÷${RTL_FILES}÷÷"

    _FLOORPLAN_FILE="$FLOORPLAN_FILE"
    FLOORPLAN_FILE="${FLOORPLAN_FILE//${DATA_DIR}/÷yellow÷\$DATA_DIR÷÷}"
    FLOORPLAN_FILE="$(dirname "$FLOORPLAN_FILE")÷yellow÷/$(basename "$FLOORPLAN_FILE")÷÷"
    _FLOORPLAN_IO_FILE="$FLOORPLAN_IO_FILE"
    FLOORPLAN_IO_FILE="${FLOORPLAN_IO_FILE//${DATA_DIR}/÷yellow÷\$DATA_DIR÷÷}"
    FLOORPLAN_IO_FILE="$(dirname "$FLOORPLAN_IO_FILE")÷yellow÷/$(basename "$FLOORPLAN_IO_FILE")÷÷"
    _CONSTRAINTS_FILE="$CONSTRAINTS_FILE"
    CONSTRAINTS_FILE="${CONSTRAINTS_FILE//${DATA_DIR}/÷yellow÷\$DATA_DIR÷÷}"
    CONSTRAINTS_FILE="$(dirname "$CONSTRAINTS_FILE")÷yellow÷/$(basename "$CONSTRAINTS_FILE")÷÷"

    if [[ ! -f "$FLOORPLAN_FILE" && ! -L "$FLOORPLAN_FILE" ]]; then
        FEATURES+=("-create_floorplan_flag")
    fi

    YAML_SETUP_FILE="setup.${DESIGN_NAME}.yaml"
    local cmd
    cmd="find ${SCRIPTS_DIR} -type f -maxdepth 1 -regextype posix-extended -regex '^.*${YAML_SETUP_FILE}.([0-9])$' -exec basename {} \\; 2>/dev/null | grep -o '[0-9]*' | sort -n | tail -1"
    YAML_SETUP_OUT_FILE=$(get_next_indexed_file "$cmd" "${SCRIPTS_DIR}/${YAML_SETUP_FILE}")
    SETUP_YAML="÷white÷${SCRIPTS_DIR}÷÷/÷yellow÷$(basename "$YAML_SETUP_OUT_FILE")÷÷"

    cmd="find ${SCRIPTS_DIR} -type f -maxdepth 1 -regextype posix-extended -regex '^.*flow.${DESIGN_NAME}.yaml.([0-9])$' -exec basename {} \\; 2>/dev/null | grep -o '[0-9]*' | sort -n | tail -1"
    FLOW_SETUP_OUT_FILE=$(get_next_indexed_file "$cmd" "${SCRIPTS_DIR}/flow.${DESIGN_NAME}.yaml")
    FLOW_YAML="÷white÷${SCRIPTS_DIR}÷÷/÷yellow÷$(basename "$FLOW_SETUP_OUT_FILE")÷÷"

    local log_cmd log_max_index log_file
    log_cmd="find ${RUNDIR} -maxdepth 1 -regextype posix-extended -regex '^.*wolf.run\\.log([0-9])*$' -exec basename {} \\; 2>/dev/null | grep -o '[0-9]*' | sort -n | tail -1"
    log_max_index=$(eval "$log_cmd")
    log_file="${RUNDIR}/wolf.run.log"
    if [[ $log_max_index -gt 0 ]]; then
        ((log_max_index++))
        log_file="${log_file}${log_max_index}"
    fi
    LOGFILE="÷white÷$RUNDIR÷÷/÷yellow÷$(basename "$log_file")÷÷"
}

_wolf_backend_prepare() {
    _wolf_info "Creating ÷blue÷setup.yaml÷÷ file at ÷yellow÷\"$YAML_SETUP_OUT_FILE\"."
    cp -L "$PROCESS_SETUP_COMMON_TEMPLATE" "$YAML_SETUP_OUT_FILE" || return $?
    tail -n +3 "$YAML_TEMPLATE_FILE" >> "$YAML_SETUP_OUT_FILE" || return $?
    tail -n +3 "$PROCESS_SETUP_HOST_TEMPLATE" >> "$YAML_SETUP_OUT_FILE" || return $?

    _wolf_info "Creating ÷blue÷flow.yaml÷÷ file at ÷yellow÷\"$FLOW_SETUP_OUT_FILE\"."
    cp -L "$PROCESS_FLOW_TEMPLATE" "$FLOW_SETUP_OUT_FILE" || return $?

    declare -A flow_maps
    flow_maps=( ["RTL_VHDL_FILES"]="$RTL_VHDL_FILES_CAT" \
                ["RTL_VHDL_FILES_ARGS"]="$RTL_VHDL_FILES_ARGS" \
                ["RTL_SV_FILES"]="$RTL_SV_FILES_CAT" \
                ["RTL_SV_FILES_ARGS"]="$RTL_SV_FILES_ARGS" \
                ["INIT_HDL_SEARCH_PATH"]="$INIT_HDL_SEARCH_PATH_CAT" \
                ["FLOW_YAML_FILE"]="$FLOW_SETUP_OUT_FILE" \
                ["CONSTRAINTS_FILES"]="$CONSTRAINTS_FILE_CAT" \
                ["SCRIPTS_DIR"]="$SCRIPTS_DIR" ["DATA_DIR"]="$DATA_DIR" \
                ["INPUTS_DIR"]="$INPUTS_DIR" ["WORKSPACE_DIR"]="$WORKSPACE_DIR" \
                ["RUNDIR"]="$RUNDIR" ["LIB_DIR"]="$LIB_DIR" \
                ["IO_LIB_DIR"]="$IO_LIB_DIR" ["METAL_STACK"]="$METAL_STACK" \
                ["METAL_STACK_DIR"]="$METAL_STACK_DIR" ["PDK_DIR"]="$PDK_DIR" \
                ["DESIGN_NAME"]="$DESIGN_NAME" ["FLOORPLAN_FILE"]="$_FLOORPLAN_FILE" \
                ["FLOORPLAN_IO_FILE"]="$_FLOORPLAN_IO_FILE" ["VTHS"]="$VTHS" \
                ["TRACKS"]="$TRACKS" )

    local file="$YAML_SETUP_OUT_FILE" subt ssv
    for subt in "${!flow_maps[@]}"; do
        ssv=$(eval echo "${flow_maps[$subt]}")
        sed -i -e "s;\${$subt};${ssv};g" "$file" || return $?
    done

    declare -A setup_maps
    setup_maps=(["DESIGN_YAML"]="$YAML_SETUP_OUT_FILE" \
                ["SCRIPTS_DIR"]="$SCRIPTS_DIR" ["FEATURES"]="${FEATURES[*]}")
    file="$FLOW_SETUP_OUT_FILE"
    for subt in "${!setup_maps[@]}"; do
        ssv=$(eval echo "${setup_maps[$subt]}")
        sed -i -e "s;\${$subt};${ssv};g" "$file" || return $?
    done

    ln -sf "$YAML_SETUP_OUT_FILE" "${RUNDIR}/$YAML_SETUP_FILE.latest"
    _wolf_info "Linking latest ÷green÷\"$YAML_SETUP_FILE.latest\"÷÷ file to ÷green÷\"$(basename "$YAML_SETUP_OUT_FILE")\"÷÷."
    ln -sf "$FLOW_SETUP_OUT_FILE" "${RUNDIR}/flow.yaml.latest"
    _wolf_info "Linking latest ÷green÷\"flow.yaml.latest\"÷÷ file to ÷green÷\"$(basename "$FLOW_SETUP_OUT_FILE")\"÷÷."

    WOLF_BACKEND_COMMAND_ARGS=(flowtool -files "$FLOW_SETUP_OUT_FILE" -run_tag "$RUNTAG" "${POSITIONAL[@]}" -directory "${WORKSPACE_DIR}/${DESIGN_NAME}/${DESIGN_NAME}.${PROCESS}" -log "${RUNDIR}/wolf.run")
    printf -v WOLF_BACKEND_COMMAND '%q ' "${WOLF_BACKEND_COMMAND_ARGS[@]}"
    WOLF_BACKEND_COMMAND="${WOLF_BACKEND_COMMAND% }"
}

_wolf_backend_stages() {
    if [[ $CLEAN == true || $COPY_SCRIPTS_OVER == true || ! -L "$WOLF_ENV_DIR/flow.sum.latest" ]]; then
        _wolf_info "Creating new ÷blue÷flow summary file÷÷ and saving to ÷yellow÷\"$WOLF_ENV_DIR/flow.sum.latest\"."
        FLOW_SUMMARY="$WOLF_ENV_DIR/runs/$WOLF_RUN_UUID.flow.sum"
        FLOW_STEPS="$WOLF_ENV_DIR/runs/$WOLF_RUN_UUID.flow.steps"
        local -a current_flows
        current_flows=($(sed -n 's/flow_current://p' "$FLOW_SETUP_OUT_FILE"))
        grep -Pzo 'flows:(.*\n)*' "$FLOW_SETUP_OUT_FILE" | sed '/^[[:space:]]*$/d' | sed 's/\t/  /g' | sed '/^#/d' | sed '/enabled:/d' | sed '/args:/d' | sed '/features:/d' | awk -F':' '{print $1":"}' > "$FLOW_SUMMARY.tmp"
        sed -i '$ d' "$FLOW_SUMMARY.tmp"
        local stages
        stages=$(python3 "${WOLF_BIN}/flow_yaml_parser.py" "$FLOW_SUMMARY.tmp" "${current_flows[@]}") || return $?
        echo "$stages" | tr ' ' '\n' > "$FLOW_STEPS"
        echo "$stages" | tr ' ' '\n' | sort -u | tr '\n' ' ' > "$FLOW_SUMMARY"
        ln -sf "$FLOW_SUMMARY" "$WOLF_ENV_DIR/flow.sum.latest"
        ln -sf "$FLOW_STEPS" "$WOLF_ENV_DIR/flow.steps.latest"
    else
        FLOW_SUMMARY="$WOLF_ENV_DIR/flow.sum.latest"
        FLOW_STEPS="$WOLF_ENV_DIR/flow.steps.latest"
    fi

    if [[ ! -f "$FLOW_STEPS" ]]; then
        _wolf_error "No flow steps found. Check if the Flowtool setup file is correct."
        return 1
    fi
    mapfile -t WOLF_BACKEND_STAGES < "$FLOW_STEPS"
}

_wolf_backend_run_stage() {
    local stage="$1"
    shift
    local log_cmd log_max_index log_file display_command tracker_dir inject_tcl status
    log_cmd="find ${RUNDIR} -maxdepth 1 -regextype posix-extended -regex '^.*wolf.run\\.log([0-9])*$' -exec basename {} \\; 2>/dev/null | grep -o '[0-9]*' | sort -n | tail -1"
    log_max_index=$(eval "$log_cmd")
    log_file="${RUNDIR}/wolf.run.log"
    if [[ $log_max_index -gt 0 ]]; then
        ((log_max_index++))
        log_file="${log_file}${log_max_index}"
    fi

    display_command="flowtool\n  -files ${FLOW_SETUP_OUT_FILE}\n  -run_tag ${RUNTAG}\n  -from ${stage}\n  -to ${stage}\n  $*\n  -directory ${WORKSPACE_DIR}/${DESIGN_NAME}/${DESIGN_NAME}.${PROCESS}\n  -log ${log_file}"
    _wolf_info "Now running $stage: \n÷white÷÷Blue÷$display_command÷÷\n"

    tracker_dir="${WOLF_HOME:-${HOME}/.wolf}/tracker"
    if [[ ! -d "$tracker_dir" && ! -L "$tracker_dir" ]]; then
        _wolf_info "First runtime detected. Creating wolf tracker dir at ÷yellow÷\"$tracker_dir\"÷÷"
        mkdir -p "$tracker_dir"
    fi
    inject_tcl="exec echo \"[pid]\" > $tracker_dir/$WOLF_RUN_UUID.pid"
    ln -sf "$log_file" "${RUNDIR}/wolf.run.log.latest"

    flowtool -files "$FLOW_SETUP_OUT_FILE" -run_tag "$RUNTAG" -inject_tcl "$inject_tcl" -from "$stage" -to "$stage" "$@" -directory "${WORKSPACE_DIR}/${DESIGN_NAME}/${DESIGN_NAME}.${PROCESS}" -log "${RUNDIR}/wolf.run"
    status=$?
    rm -f "$tracker_dir/$WOLF_RUN_UUID.pid"
    if [[ $status -ne 0 ]]; then
        _wolf_error "Flowtool exited with status $status while running $stage. Stopping sequence."
        return "$status"
    fi
    if [[ -f "$log_file" ]] && grep -Fq "Flow failed" "$log_file"; then
        _wolf_error "Error in the Flowtool flow detected. Stopping sequence."
        return 1
    fi
}
