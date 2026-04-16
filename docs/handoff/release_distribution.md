# Codex handoff: sample-bundle distribution + tagged release

Target PLAN.md priority 4. Paste the block below into `codex`. Do this track
after the turn_restrictions handoff has landed so the frozen bundle reflects
the latest schema.

---

```
You are working in the repo /media/sasaki/aiueo/ai_coding_ws/roadgraph_builder.
Implement the "distribution" track from docs/PLAN.md priority 4: a frozen
sample bundle committed to the repo, reproducible build script, and a GitHub
Actions release workflow that attaches the bundle to a tag. Keep changes
minimal and do not touch unrelated modules.

## Files to create

1. `scripts/build_release_bundle.sh`
   - Deterministic wrapper around `roadgraph_builder export-bundle` using
     `examples/sample_trajectory.csv` + `examples/toy_map_origin.json` +
     `examples/camera_detections_sample.json`.
   - Output: `dist/roadgraph_sample_bundle/` (clean + rebuild each run).
   - Also produce `dist/roadgraph_sample_bundle.tar.gz` and
     `dist/roadgraph_sample_bundle.sha256` (sha256 of the tar.gz).
   - After writing outputs, run `roadgraph_builder validate-*` on the bundle
     files. Exit non-zero on any validation failure.
   - Make it callable from CI (no interactive prompts, `set -euo pipefail`).

2. `examples/frozen_bundle/` (committed sample bundle)
   - Produced by `scripts/build_release_bundle.sh`, committed so users can
     browse the shape without building. Keep under a few hundred KB
     (trajectory.csv is already ~small). If the bundle is >1 MB, commit only
     `manifest.json` + `nav/sd_nav.json` + `sim/map.geojson` and add a
     README pointing at the script.
   - Add `examples/frozen_bundle/README.md` that records:
     - How the bundle was generated (command line).
     - `roadgraph_builder_version` at time of freeze.
     - Note: "regenerate with `bash scripts/build_release_bundle.sh`".

3. `.github/workflows/release.yml`
   - Trigger: `push` with tag matching `v*`.
   - Jobs:
     a. Set up Python (same matrix slot as CI, single version is fine).
     b. Install the package editable with `[dev]` extras.
     c. Run `bash scripts/build_release_bundle.sh`.
     d. Create a GitHub Release for the tag using the standard
        `softprops/action-gh-release` action (or `gh release create` via
        `actions/github-script`), attaching
        `dist/roadgraph_sample_bundle.tar.gz` and
        `dist/roadgraph_sample_bundle.sha256`.
   - Pin action versions with commit SHAs or concrete tags; do not use `@main`.
   - Document in the workflow comments that the job runs only on tag push.

4. `tests/test_release_bundle.py`
   - Skipped unless `ROADGRAPH_RUN_RELEASE_TEST=1` is set (pytest `skipif`),
     because it shells out. When enabled, invoke
     `scripts/build_release_bundle.sh` into a `tmp_path` override and assert
     that the output tree contains the expected files and the tar.gz exists.
   - Also add a fast, always-on test that only checks the frozen bundle
     shape: `examples/frozen_bundle/manifest.json` validates via
     `validate_manifest_document` and `nav/sd_nav.json` via
     `validate_sd_nav_document`.

## Files to modify

5. `README.md`
   - Add a "Sample bundle" section pointing at `examples/frozen_bundle/` and
     the release artifact.

6. `CHANGELOG.md` [Unreleased] → new bullet under **Added**:
   "Distribution — `scripts/build_release_bundle.sh` + `.github/workflows/
   release.yml` attach a validated `roadgraph_sample_bundle.tar.gz` (plus
   sha256) to every `v*` tag; a trimmed `examples/frozen_bundle/` is
   committed for quick inspection."

7. `docs/PLAN.md`
   - Under **確認済み**, add a line confirming tagged releases produce a
     validated sample bundle.
   - Update or remove the matching 未確認 bullet.

8. `Makefile`
   - Add a `release-bundle:` target that runs
     `bash scripts/build_release_bundle.sh`.

## PyPI (optional, do last)

If time permits:
9. `pyproject.toml` already declares the package — add a separate workflow
   `.github/workflows/pypi.yml` triggered only on `workflow_dispatch`, using
   `pypa/gh-action-pypi-publish` with a trusted-publisher config note in the
   PR description. Do NOT add secrets; just scaffold so the maintainer can
   enable it.

## Definition of done

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` is green.
- `bash scripts/build_release_bundle.sh` succeeds locally and produces
  `dist/roadgraph_sample_bundle.tar.gz` + sha256.
- `actionlint` (or manual review) shows the release workflow is well-formed.
- Commits are small, no "Co-Authored-By" trailer, PR description has no
  "🤖 Generated with Claude Code" marker (per repo convention).
```
