# Data attribution

The interactive viewer at `docs/map.html` ships a few pre-computed
`*.geojson` assets derived from public inputs. Each derivative is licensed
under **ODbL 1.0** — the same terms as the OpenStreetMap data it was built
from — and credits OpenStreetMap contributors.

| Asset | Source | License |
| --- | --- | --- |
| `map_toy.geojson` | Hand-written synthetic trajectory (`examples/sample_trajectory.csv`). No real-world GPS data. | Repo license (none set yet) |
| `map_osm.geojson` | OSM public GPS trackpoints API, Berlin bbox `13.40,52.51,13.42,52.52`, ~800 points (committed as `examples/osm_public_trackpoints.csv`). | **© OpenStreetMap contributors, ODbL 1.0** |
| `map_paris.geojson` | OSM public GPS trackpoints API, Paris bbox `2.3370,48.8570,2.3570,48.8770`, pages 0-4 merged to ~6634 deduped points. **Raw CSV is not committed**; only the derived centerlines / boundaries / nodes are shipped here. Built with `export-bundle --max-step-m 40 --merge-endpoint-m 8 --lane-width-m 3.5`. | **© OpenStreetMap contributors, ODbL 1.0** |
| `route_paris.geojson` | Shortest path produced by `roadgraph_builder route /tmp/paris_bundle/sim/road_graph.json n111 n53 --output ...` on the same Paris bundle above: 3 edges, ~1268 m. Loaded as a yellow overlay on top of `map_paris.geojson` in the Leaflet viewer. | **© OpenStreetMap contributors, ODbL 1.0** |

To refetch / regenerate:

```bash
for p in 0 1 2 3 4; do
  python scripts/fetch_osm_trackpoints.py \
    --bbox "2.3370,48.8570,2.3570,48.8770" --max-points 1500 --page $p \
    -o /tmp/osm_real_data/paris_trackpoints_p${p}.csv
done
# (Merge the 5 page WGS84 outputs through a single bbox-center origin;
# see docs/bundle_tuning.md for the recipe.)
roadgraph_builder export-bundle /tmp/osm_real_data/paris_merged.csv /tmp/paris_bundle \
  --origin-json /tmp/osm_real_data/paris_merged_origin.json \
  --lane-width-m 3.5 --max-step-m 40 --merge-endpoint-m 8
cp /tmp/paris_bundle/sim/map.geojson docs/assets/map_paris.geojson
```
