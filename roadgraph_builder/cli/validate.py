"""CLI parser and command handlers for schema validation commands."""

from __future__ import annotations

import argparse
import sys
from typing import Callable, TextIO

from jsonschema import ValidationError


LoadJson = Callable[[str], object]
ValidateDocument = Callable[[dict[str, object]], object]
ValidationErrorReporter = Callable[[str, ValidationError], None]

VALIDATION_COMMANDS = (
    "validate",
    "validate-detections",
    "validate-sd-nav",
    "validate-manifest",
    "validate-turn-restrictions",
    "validate-lane-markings",
)


class CliValidationError(ValueError):
    """User-facing validation CLI error."""


def add_validation_parsers(sub) -> None:  # type: ignore[no-untyped-def]
    """Register JSON schema validation subcommands."""

    val = sub.add_parser("validate", help="Validate a road graph JSON file against the schema.")
    val.add_argument("input_json", help="JSON file produced by `build`")

    vd = sub.add_parser(
        "validate-detections",
        help="Validate camera/perception detections JSON (camera_detections.schema.json).",
    )
    vd.add_argument("input_json", help="detections.json with observations[]")

    vsd = sub.add_parser(
        "validate-sd-nav",
        help="Validate navigation SD seed JSON (sd_nav.schema.json, e.g. export-bundle nav/sd_nav.json).",
    )
    vsd.add_argument("input_json", help="sd_nav.json")

    vm = sub.add_parser(
        "validate-manifest",
        help="Validate export-bundle manifest.json (manifest.schema.json).",
    )
    vm.add_argument("input_json", help="manifest.json")

    vtr = sub.add_parser(
        "validate-turn-restrictions",
        help="Validate a turn-restrictions JSON (turn_restrictions.schema.json).",
    )
    vtr.add_argument("input_json", help="turn_restrictions.json")

    vlm = sub.add_parser(
        "validate-lane-markings",
        help="Validate a lane_markings.json against lane_markings.schema.json.",
    )
    vlm.add_argument("input_json", help="lane_markings.json produced by detect-lane-markings.")


def require_json_object(data: object) -> dict[str, object]:
    """Return ``data`` as a JSON object or raise a CLI-facing validation error."""

    if not isinstance(data, dict):
        raise CliValidationError("JSON root must be an object")
    return data


def print_validation_error(
    path_str: str,
    err: ValidationError,
    *,
    stderr: TextIO | None = None,
) -> None:
    """Print a compact schema validation error."""

    out = stderr if stderr is not None else sys.stderr
    print(f"{path_str}: {err.message}", file=out)


def validator_for_command(command: str) -> ValidateDocument:
    """Resolve the schema validator for a validation subcommand."""

    from roadgraph_builder.validation import (
        validate_camera_detections_document,
        validate_lane_markings_document,
        validate_manifest_document,
        validate_road_graph_document,
        validate_sd_nav_document,
        validate_turn_restrictions_document,
    )

    validators: dict[str, ValidateDocument] = {
        "validate": validate_road_graph_document,
        "validate-detections": validate_camera_detections_document,
        "validate-sd-nav": validate_sd_nav_document,
        "validate-manifest": validate_manifest_document,
        "validate-turn-restrictions": validate_turn_restrictions_document,
        "validate-lane-markings": validate_lane_markings_document,
    }
    try:
        return validators[command]
    except KeyError as exc:
        raise CliValidationError(f"Unsupported validation command: {command}") from exc


def run_validate_document(
    args: argparse.Namespace,
    *,
    load_json: LoadJson,
    validate_func: ValidateDocument | None = None,
    validation_error_func: ValidationErrorReporter | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute a JSON schema validation subcommand from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    data = load_json(args.input_json)
    try:
        document = require_json_object(data)
    except CliValidationError as exc:
        print(str(exc), file=err)
        return 1

    try:
        validator = validate_func if validate_func is not None else validator_for_command(args.command)
        validator(document)
    except ValidationError as exc:
        if validation_error_func is None:
            print_validation_error(args.input_json, exc, stderr=err)
        else:
            validation_error_func(args.input_json, exc)
        return 1
    except CliValidationError as exc:
        print(str(exc), file=err)
        return 1
    return 0
