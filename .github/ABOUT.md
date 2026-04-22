# GitHub "About" (copy into the repository description)

Use **Settings → General → About → Description** (or `gh repo edit`).

**Short (≤350 characters recommended):**

> Build road graphs from GPS trajectories, OSM, LiDAR, and camera data. Exports navigation JSON, simulation GeoJSON, and Lanelet2-style OSM with routing, turn restrictions, reachability, and validation.

**Topics to add:** `python`, `road-graph`, `trajectory`, `mapping`, `openstreetmap`, `gis`, `geojson`, `lanelet2`, `lidar`, `camera-calibration`, `routing`, `autonomous-driving`

**Website (optional):** your GitHub Pages URL when Pages is available, e.g. `https://<user>.github.io/roadgraph_builder/`

**GitHub CLI:**

```bash
gh repo edit rsasaki0109/roadgraph_builder \
  --description "Build road graphs from GPS trajectories, OSM, LiDAR, and camera data. Exports navigation JSON, simulation GeoJSON, and Lanelet2-style OSM with routing, turn restrictions, reachability, and validation." \
  --add-topic python \
  --add-topic road-graph \
  --add-topic trajectory \
  --add-topic mapping \
  --add-topic openstreetmap \
  --add-topic gis \
  --add-topic geojson \
  --add-topic lanelet2 \
  --add-topic lidar \
  --add-topic camera-calibration \
  --add-topic routing \
  --add-topic autonomous-driving
```
