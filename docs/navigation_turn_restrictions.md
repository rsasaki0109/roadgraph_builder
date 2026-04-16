# Navigation Maneuvers and Turn Restrictions

This note fixes the current `sd_nav` contract and records the planned shape for
explicit turn restrictions.

## Current contract

`nav/sd_nav.json` is a regulation-free SD routing seed. It contains topology,
edge lengths, and coarse maneuver hints:

- `allowed_maneuvers`: inferred at the digitized `end_node_id`.
- `allowed_maneuvers_reverse`: inferred at the digitized `start_node_id` when
  traversing the edge in reverse.
- Values are geometry hints only: `straight`, `left`, `right`, `u_turn`.

The hints are intentionally permissive. They come from 2D junction geometry and
must not be interpreted as surveyed legal permissions. A missing `left` or
`right` can mean the geometry did not show that branch, not that a sign, signal,
or traffic rule prohibits it.

Do not encode turn bans by deleting values from `allowed_maneuvers`. That would
mix observed topology with legal/regulatory data and make sparse trajectories
look like surveyed restrictions.

## Restriction model

When turn restriction data is available, add it as a separate layer instead of
changing the meaning of `allowed_maneuvers`.

Optional `sd_nav` extension:

```json
{
  "turn_restrictions": [
    {
      "id": "tr_001",
      "junction_node_id": "n12",
      "from_edge_id": "e7",
      "from_direction": "forward",
      "to_edge_id": "e9",
      "to_direction": "forward",
      "restriction": "no_left_turn",
      "source": "camera_detection",
      "confidence": 0.83
    }
  ]
}
```

Field notes:

| Field | Purpose |
| --- | --- |
| `junction_node_id` | Node where the transition is evaluated. |
| `from_edge_id` / `to_edge_id` | Directed transition being restricted. |
| `from_direction` / `to_direction` | `forward` follows digitization; `reverse` is opposite digitization. |
| `restriction` | Suggested enum: `no_left_turn`, `no_right_turn`, `no_straight`, `no_u_turn`, `only_left`, `only_right`, `only_straight`. |
| `source` | Provenance such as `manual`, `camera_detection`, `osm`, or `import`. |
| `confidence` | Optional 0..1 score for non-manual sources. |

`sd_nav.schema.json` accepts this optional top-level array while keeping
`schema_version: 1`. The schema validates field shape and enum values; it does
not cross-check that edge and node IDs exist in the same document.

## How to provide it

Two inputs are merged (manual wins on `id` clashes) and written into
`nav/sd_nav.json` by `export-bundle`.

### 1. Manual JSON file

Pass `--turn-restrictions-json PATH` to `export-bundle`. The file may be either
a bare list or an object with a `turn_restrictions` array:

```json
{
  "format_version": 1,
  "turn_restrictions": [
    {
      "junction_node_id": "n1",
      "from_edge_id": "e0",
      "to_edge_id": "e1",
      "restriction": "no_left_turn"
    }
  ]
}
```

Missing `id` values are filled as `tr_manual_{idx:04d}`; missing `source`
defaults to `manual`. `from_direction` / `to_direction` default to `forward`.
Validate standalone with `roadgraph_builder validate-turn-restrictions PATH`.
See `examples/turn_restrictions_sample.json`.

### 2. Camera detections

Any observation in `--detections-json` with `kind: "turn_restriction"` and a
`junction_node_id` is lifted into `turn_restrictions` with
`source: "camera_detection"`. Entries without a `junction_node_id` are
skipped because a bare `edge_id` cannot place the restriction at a specific
junction.

`metadata.export_bundle.turn_restrictions` records the final count and a
source breakdown (e.g. `{"manual": 1, "camera_detection": 2}`).

## Router behavior

A downstream router should read the data in this order:

1. Use graph topology to enumerate possible directed edge transitions.
2. Use `allowed_maneuvers` / `allowed_maneuvers_reverse` as display or coarse
   maneuver labels.
3. Apply `turn_restrictions` as a separate filter when present.
4. If no restriction layer is present, assume restrictions are unknown rather
   than surveyed unrestricted.
