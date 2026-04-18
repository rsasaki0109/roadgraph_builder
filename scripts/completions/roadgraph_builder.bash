# Bash completion for `roadgraph_builder`.
#
# Install (user):
#     mkdir -p ~/.local/share/bash-completion/completions
#     cp scripts/completions/roadgraph_builder.bash \
#        ~/.local/share/bash-completion/completions/roadgraph_builder
#
# Or source it directly from your ~/.bashrc:
#     source /path/to/scripts/completions/roadgraph_builder.bash
#
# Completes the subcommand list and common file-path arguments. Updated
# alongside roadgraph_builder/cli/main.py; run this file through the test
# suite (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_cli_version.py -v`)
# after changing the subcommand set.

_roadgraph_builder_completions() {
    local cur prev words cword
    _init_completion || return

    local subcommands="doctor build visualize validate validate-detections \
validate-sd-nav validate-manifest validate-turn-restrictions enrich \
inspect-lidar nearest-node route stats fuse-lidar export-lanelet2 \
apply-camera export-bundle"

    # Top-level position: either a flag or a subcommand.
    if ((cword == 1)); then
        if [[ $cur == -* ]]; then
            COMPREPLY=($(compgen -W "-h --help -V --version" -- "$cur"))
        else
            COMPREPLY=($(compgen -W "$subcommands" -- "$cur"))
        fi
        return 0
    fi

    local sub="${words[1]}"

    # Flag-value pairs that always want a file path.
    case "$prev" in
        --origin-json | --detections-json | --turn-restrictions-json | \
        --lidar-points | --points-path | --output | --input_json | --input_las | \
        --input_csv | --output_json | --output_svg | --output_osm | --output_dir | \
        --points_csv | --points_path | --extra-csv)
            _filedir
            return 0
            ;;
    esac

    # Sub-command specific: show common flags when the user types `-`.
    if [[ $cur == -* ]]; then
        case "$sub" in
            build|visualize|export-bundle)
                COMPREPLY=($(compgen -W "\
--max-step-m --merge-endpoint-m --centerline-bins --simplify-tolerance \
--lane-width-m --dataset-name --origin-json --origin-lat --origin-lon \
--detections-json --turn-restrictions-json --lidar-points --fuse-max-dist-m \
--fuse-bins --width --height --extra-csv" -- "$cur"))
                ;;
            enrich)
                COMPREPLY=($(compgen -W "--lane-width-m" -- "$cur"))
                ;;
            fuse-lidar)
                COMPREPLY=($(compgen -W "--max-dist-m --bins" -- "$cur"))
                ;;
            export-lanelet2)
                COMPREPLY=($(compgen -W "--origin-lat --origin-lon" -- "$cur"))
                ;;
            nearest-node)
                COMPREPLY=($(compgen -W "--latlon --xy --origin-lat --origin-lon" -- "$cur"))
                ;;
            route)
                COMPREPLY=($(compgen -W "\
--turn-restrictions-json --output --origin-lat --origin-lon \
--from-latlon --to-latlon" -- "$cur"))
                ;;
            stats)
                COMPREPLY=($(compgen -W "--origin-lat --origin-lon" -- "$cur"))
                ;;
            *)
                COMPREPLY=($(compgen -W "-h --help" -- "$cur"))
                ;;
        esac
        return 0
    fi

    # Default: filesystem paths for positional args.
    _filedir
}

complete -F _roadgraph_builder_completions roadgraph_builder
