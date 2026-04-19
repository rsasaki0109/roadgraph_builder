# Camera pipeline — end-to-end demo

`project-camera` takes three inputs — a camera calibration, a per-image pixel
detection list, and a road graph — and writes an edge-keyed
`camera_detections.json` that `apply-camera` / `export-bundle` already
consume. This note walks through a self-contained demo that round-trips
known ground-truth world points through a wide-angle camera and back, plus a
recipe for plugging in real data.

## Shipped demo (synthetic but realistic)

`scripts/generate_camera_demo.py` produces

- `examples/demo_camera_calibration.json` — 1280×800 forward-facing camera,
  `fx=fy=900`, Brown-Conrady distortion `(-0.27, 0.09, 0.0005, -0.0003, -0.02)`
  (mild wide-angle barrel), mounted 1.5 m above the vehicle origin.
- `examples/demo_image_detections.json` — four vehicle poses along `+x` at
  5 m spacing; each image records pixel coordinates of known world features
  (two lane marks at `±1.75 m`, a stop line at `(18, 0)`, and two speed-limit
  signs at `(20, ±3.5)`). Each detection carries its `_world_ground_truth_m`
  so the pipeline's recovery can be verified.

Run it against any road-along-x graph, e.g.

```bash
cat > /tmp/demo_graph.json <<'EOF'
{
  "schema_version": 1,
  "nodes": [
    {"id": "n0", "position": {"x": 0, "y": 0}, "attributes": {}},
    {"id": "n1", "position": {"x": 30, "y": 0}, "attributes": {}}
  ],
  "edges": [
    {
      "id": "e0",
      "start_node_id": "n0",
      "end_node_id": "n1",
      "polyline": [{"x": 0, "y": 0}, {"x": 30, "y": 0}],
      "attributes": {}
    }
  ]
}
EOF

roadgraph_builder project-camera \
  examples/demo_camera_calibration.json \
  examples/demo_image_detections.json \
  /tmp/demo_graph.json \
  /tmp/demo_camera_detections.json \
  --max-edge-distance-m 10

roadgraph_builder apply-camera \
  /tmp/demo_graph.json \
  /tmp/demo_camera_detections.json \
  /tmp/demo_graph_with_semantics.json
```

On the shipped demo the maximum round-trip error is **~1 cm** (the only
material error source is rounding pixel coordinates to 0.1 px before handing
them to `project-camera`). `tests/test_camera_demo_roundtrip.py` asserts the
error stays under 10 cm — that's the regression guard.

## Plugging in real data

The pipeline doesn't read image pixels directly — it reads *pixel detections*
(a JSON list of `(u, v)` coordinates with `kind` / `value`). Any detector
(manual annotation, a trained model, a simulator exporter) produces this
shape.

### Calibration

Fill in `fx`, `fy`, `cx`, `cy` from the manufacturer data sheet or a
checkerboard calibration. Distortion coefficients are OpenCV's 5-coef
Brown-Conrady form `(k1, k2, p1, p2, k3)`. `CameraCalibration.camera_to_
vehicle` uses body FLU (`+x` fwd, `+y` left, `+z` up); a forward-facing
camera 1.5 m above the vehicle origin is `rotation_rpy_rad: [0, 0, 0]` plus
`translation_m: [0, 0, 1.5]`.

### Per-image pose

Each image needs a vehicle pose in the same meter frame as the graph (the one
that matches `metadata.map_origin` on the graph JSON). Upstream sources:

- An IMU / GNSS trajectory resampled at image timestamps.
- The output of `roadgraph_builder match-trajectory` if you trust the map
  matcher to pin the vehicle to a specific edge (less accurate for images
  at junctions — use the raw pose where possible).

Rotation can be RPY or an explicit 3×3 matrix.

### Mapillary (CC-BY-SA) recipe

Mapillary exposes free imagery with per-image camera parameters; the catch is
that the image license is **CC-BY-SA** and every downstream artefact must
carry attribution. The v4 Graph API is the current entry point — see
<https://www.mapillary.com/developer/api-documentation>. In short:

1. Register a free app and get an access token.
2. List image ids in the bbox of interest (endpoint `images`, filter by
   `bbox`).
3. For each image fetch the `thumb_original_url`, plus
   `camera_parameters` (intrinsic) and `computed_geometry` /
   `computed_compass_angle` (extrinsic).
4. Run a detector on the image or hand-annotate pixel features. Pack them
   into `image_detections.json` with the pose fields above.
5. Run `roadgraph_builder project-camera` on the pair.
6. Record the Mapillary source and CC-BY-SA attribution in `ATTRIBUTION.md`
   for any derived artefact you commit or publish.

The repo intentionally does **not** ship Mapillary imagery — the CC-BY-SA
viral clause would bind every file in the same release. Generate the pixel
detections locally and commit only the graph-space outputs (an edge-keyed
camera_detections JSON is a derivative of the map graph, not the image).

### KITTI / nuScenes

Both require non-commercial / attribution terms plus click-through
registration. Same recipe — calibration is shipped with every log, per-image
poses come from the GPS/IMU data, detections from the benchmark annotations.
The repo can't ship these either, but all three pieces plug into
`project-camera` unchanged.
