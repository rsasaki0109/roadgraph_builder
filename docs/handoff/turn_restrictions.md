# Codex handoff: turn_restrictions generation entry point

> **Status: DONE** — landed in commit `be0fcf0` (main). `export-bundle
> --turn-restrictions-json`, camera-detection extraction (`kind:
> turn_restriction`), `validate-turn-restrictions` CLI + schema, and the
> toy `examples/turn_restrictions_sample.json` are all live. Handoff kept
> for historical context.

Target PLAN.md priority 2. Paste the block below into `codex` (or similar) as the
prompt. Start from a clean branch (e.g. `git switch -c feat/turn-restrictions`).

---

```
You are working in the repo /media/sasaki/aiueo/ai_coding_ws/roadgraph_builder.
Implement the "turn_restrictions generation entry point" described below.
Do NOT change unrelated behavior. Keep changes minimal. Run the test suite
with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` before
finishing and fix any regression.

## Background
- `sd_nav.schema.json` already allows an optional top-level `turn_restrictions`
  array (see docs/navigation_turn_restrictions.md). Today nothing populates it.
- Goal: add an entry point that turns (a) a hand-edited JSON file and (b)
  camera detections with `kind == "turn_restriction"` into a normalized list
  that `export-bundle` writes into `nav/sd_nav.json`.
- Do NOT modify `allowed_maneuvers` / `allowed_maneuvers_reverse`. Legal
  restrictions live on their own layer on purpose.

## Files to create

1. `roadgraph_builder/navigation/turn_restrictions.py`
   Public API:
     - `load_turn_restrictions_json(path: str | Path) -> list[dict]`
         - Root may be `{"format_version": 1, "turn_restrictions": [...]}` or
           a bare list.
         - Default `source = "manual"`. Missing `id` → `tr_manual_{idx:04d}`.
     - `turn_restrictions_from_camera_detections(observations) -> list[dict]`
         - Take iterable of detection dicts; keep only
           `kind == "turn_restriction"`.
         - Default `source = "camera_detection"`. Missing `id` →
           `tr_camera_{idx:04d}`.
         - Skip entries missing `junction_node_id` (cannot emit safely from
           just an `edge_id`).
     - `merge_turn_restrictions(*groups) -> list[dict]`
         - Concatenate, de-dup by `id` (first occurrence wins), preserve order.
   Shared coercion rules:
     - Required fields: junction_node_id, from_edge_id, to_edge_id, restriction
     - from_direction / to_direction default "forward"; must be in
       {"forward","reverse"}
     - restriction must be one of the enum in sd_nav.schema.json
     - confidence, if present, must be in [0, 1]
     - Raise `ValueError` / `TypeError` with a clear message on bad input.
   Export from `roadgraph_builder/navigation/__init__.py`.

2. `roadgraph_builder/schemas/turn_restrictions.schema.json`
   Wrap the per-item shape already inlined in `sd_nav.schema.json`:
     { "format_version": 1 (const, optional), "turn_restrictions": [ ... ] }
   Reuse the same enum and field rules. Set `$id` similar to other schemas.

3. `roadgraph_builder/validation/turn_restrictions.py`
   `validate_turn_restrictions_document(data)` mirroring
   `validate_sd_nav_document` (Draft202012Validator, importlib.resources).
   Export it from `roadgraph_builder/validation/__init__.py`.

4. `examples/turn_restrictions_sample.json`
   Reference at least one entry aligned with the toy demo graph. Use
   `junction_node_id`, `from_edge_id`, `to_edge_id` that exist after running
   `export-bundle` on `examples/sample_trajectory.csv`. Inspect
   `nav/sd_nav.json` produced by the demo to pick valid ids. Include a
   `no_left_turn` example with `source: "manual"` and a second entry with
   `confidence`.

5. `tests/test_turn_restrictions.py`
   - `load_turn_restrictions_json` round-trips the sample and fills ids.
   - Bare-list JSON is accepted.
   - Camera path: mixed detections (speed_limit, traffic_light,
     turn_restriction) extract only the latter and default the source.
   - Detections missing `junction_node_id` are skipped, not raised.
   - `merge_turn_restrictions` dedupes by `id` and preserves order.
   - `validate_turn_restrictions_document` accepts the sample and rejects a
     bad enum.
   - Bundle integration: running `export_map_bundle` with the sample file
     results in `nav/sd_nav.json` containing the expected entries, and
     `validate_sd_nav_document` still passes. Manifest records
     `turn_restrictions_json`.

## Files to modify

6. `roadgraph_builder/io/export/bundle.py`
   - Add `turn_restrictions_json: str | Path | None = None` to
     `export_map_bundle`.
   - Change `build_sd_nav_document` signature to
     `build_sd_nav_document(graph, *, turn_restrictions=None)`:
       - When the list is non-empty, attach it under key `turn_restrictions`.
       - Do not add the key when empty (keeps existing tests green).
   - Inside `export_map_bundle`:
       a. If `turn_restrictions_json` is a file → load via new loader.
       b. If `detections_json` was already loaded, derive camera-based
          restrictions from the same observations (reuse, do not re-open).
       c. Merge manual first, camera second (manual wins on id clash).
       d. Pass merged list to `build_sd_nav_document`.
   - Record in `metadata.export_bundle.turn_restrictions` a count + source
     breakdown (e.g. {"manual": 1, "camera_detection": 2}).
   - Manifest: add optional `turn_restrictions_json` (basename or null) and
     `turn_restrictions_count` integer.

7. `roadgraph_builder/cli/main.py`
   - `export-bundle` gets `--turn-restrictions-json PATH` (optional,
     mirroring `--detections-json`).
   - New sub-command `validate-turn-restrictions` analogous to
     `validate-sd-nav` using `validate_turn_restrictions_document`.

8. `roadgraph_builder/schemas/manifest.schema.json`
   - Accept (not require) `turn_restrictions_json` (string|null) and
     `turn_restrictions_count` (integer, minimum 0).

9. `scripts/run_demo_bundle.sh`
   - Run `validate-turn-restrictions examples/turn_restrictions_sample.json`.
   - Pass `--turn-restrictions-json examples/turn_restrictions_sample.json`
     to `export-bundle`.

10. `.github/workflows/ci.yml`
    - Add a step that runs `roadgraph_builder validate-turn-restrictions
      examples/turn_restrictions_sample.json` and checks the bundle's
      `nav/sd_nav.json` still passes `validate-sd-nav`.

11. Docs
    - `docs/navigation_turn_restrictions.md`: add a "How to provide it"
      section with the JSON file shape and the camera-detection kind.
    - `CHANGELOG.md` [Unreleased] → add a bullet under **Added**:
      "Navigation restrictions (generator) — `export-bundle
      --turn-restrictions-json` plus extraction from camera detections
      (`kind: turn_restriction`) now populate `sd_nav.turn_restrictions`; new
      `validate-turn-restrictions` CLI + schema."
    - `docs/PLAN.md`: under 確認済み, add a line stating that
      `turn_restrictions` are now generated end-to-end in the bundle.
      Remove/adjust the matching 未確認 bullet.

## Definition of done

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` is green
  (baseline was 63 passing; expect ≥ baseline + new tests).
- `make demo` runs to completion and the resulting
  `nav/sd_nav.json` contains a non-empty `turn_restrictions` array that
  `validate-sd-nav` accepts.
- `git diff` shows no changes to unrelated modules.
- Commits are small and have no "Co-Authored-By" trailer (per repo
  convention).
```
