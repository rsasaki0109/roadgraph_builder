"""CLI parser and command handlers for turn-by-turn guidance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, TextIO

from jsonschema import ValidationError


LoadJson = Callable[[str], object]


def add_guidance_parsers(sub) -> None:  # type: ignore[no-untyped-def]
    """Register guidance subcommands."""

    guid = sub.add_parser(
        "guidance",
        help="Build turn-by-turn navigation steps from a route GeoJSON + sd_nav.json.",
    )
    guid.add_argument("route_geojson", help="Route GeoJSON (from the route CLI --output).")
    guid.add_argument("sd_nav_json", help="SD nav JSON (nav/sd_nav.json from export-bundle).")
    guid.add_argument("--output", type=str, default="guidance.json", metavar="PATH", help="Output JSON path (default: guidance.json).")
    guid.add_argument("--slight-deg", type=float, default=20.0, metavar="DEG", help="Angle threshold for slight turns (degrees).")
    guid.add_argument("--sharp-deg", type=float, default=120.0, metavar="DEG", help="Angle threshold for sharp turns (degrees).")
    guid.add_argument("--u-turn-deg", type=float, default=165.0, metavar="DEG", help="Angle threshold for U-turns (degrees).")

    vguid = sub.add_parser(
        "validate-guidance",
        help="Validate a guidance.json against guidance.schema.json.",
    )
    vguid.add_argument("input_json", help="guidance.json produced by the guidance CLI.")


def guidance_steps_to_document(steps) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Serialize guidance steps to the CLI JSON shape."""

    return {
        "steps": [
            {
                "step_index": step.step_index,
                "edge_id": step.edge_id,
                "start_distance_m": step.start_distance_m,
                "length_m": step.length_m,
                "maneuver_at_end": step.maneuver_at_end,
                "heading_change_deg": step.heading_change_deg,
                "junction_type_at_end": step.junction_type_at_end,
                "description": step.description,
                "sd_nav_edge_maneuvers": step.sd_nav_edge_maneuvers,
            }
            for step in steps
        ]
    }


def run_guidance(
    args: argparse.Namespace,
    *,
    load_json: LoadJson,
    build_guidance_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``guidance`` from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    if build_guidance_func is None:
        from roadgraph_builder.navigation.guidance import build_guidance

        build_guidance_func = build_guidance

    route_data = load_json(args.route_geojson)
    sd_nav_data = load_json(args.sd_nav_json)
    if not isinstance(route_data, dict):
        print("guidance: route GeoJSON root must be an object.", file=err)
        return 1
    if not isinstance(sd_nav_data, dict):
        print("guidance: sd_nav JSON root must be an object.", file=err)
        return 1

    steps = build_guidance_func(
        route_data,
        sd_nav_data,
        slight_deg=args.slight_deg,
        sharp_deg=args.sharp_deg,
        u_turn_deg=args.u_turn_deg,
    )
    Path(args.output).write_text(
        json.dumps(guidance_steps_to_document(steps), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}: {len(steps)} steps.", file=err)
    return 0


def run_validate_guidance(
    args: argparse.Namespace,
    *,
    load_json: LoadJson,
    validate_guidance_func: Callable[[dict], object] | None = None,
    validation_error_func: Callable[[str, ValidationError], object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``validate-guidance`` from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    if validate_guidance_func is None:
        from roadgraph_builder.validation import validate_guidance_document

        validate_guidance_func = validate_guidance_document

    data = load_json(args.input_json)
    if not isinstance(data, dict):
        print("JSON root must be an object", file=err)
        return 1
    try:
        validate_guidance_func(data)
    except ValidationError as exc:
        if validation_error_func is not None:
            validation_error_func(args.input_json, exc)
        else:
            print(f"{args.input_json}: {exc.message}", file=err)
        return 1
    return 0
