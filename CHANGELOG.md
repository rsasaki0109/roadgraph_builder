# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Route CLI explain mode exposes routing engine diagnostics.**
  `roadgraph_builder route --explain` adds a `diagnostics` object to stdout
  with the selected search engine, whether the safe A* heuristic was enabled,
  fallback reason when Dijkstra is used, expanded / queued state counts, route
  edge count, and total length.

- **Route explain diagnostics are visible in docs and Pages.**
  `docs/assets/route_explain_sample.json` is generated from real
  `RoutePlanner` diagnostics and covers both a metric safe-A* route and the
  Paris turn-restriction route's Dijkstra fallback. README, Showcase, and the
  static Pages viewer now link to the sample. The Pages landing page also
  renders the JSON as an A* vs Dijkstra fallback comparison with expanded /
  queued state counts, edge counts, route lengths, heuristic state, and
  fallback reason. A committed README / Showcase screenshot is rendered by
  `scripts/render_route_diagnostics_screenshot.py` through headless Chrome so
  the comparison is visible before opening Pages.

- **The docs map is now a 2D/3D map console.**
  `docs/map.html` keeps the Leaflet OSM view and adds a Three.js graph preview,
  dataset inspector metrics, route / reachability / restriction overlay
  toggles, and dynamic-route synchronization so click-to-route updates both the
  2D and 3D representations.

- **Map-console hero screenshots for README and Showcase.**
  `docs/map.html` accepts `?view=2d|3d` and `?dataset=…` query parameters and
  exposes a `body[data-ready]` signal so headless tooling can capture stable
  frames. A new `scripts/render_map_console_screenshot.py` serves `docs/` over
  a local HTTP server and drives the Playwright CLI with system Chrome to
  produce committed `docs/images/map_console_2d.png` and `map_console_3d.png`.
  README "Visualization results" and `docs/SHOWCASE.md` embed the PNGs so the
  map-console product surface is visible on the GitHub README without running
  a server.

- **Opt-in browser smoke for the map console.**
  `tests/js/map_console_smoke.spec.mjs` (desktop 2D inspector counts, desktop
  3D non-blank WebGL canvas, mobile 390×844 horizontal-overflow check) runs
  under system Chrome via `@playwright/test`. The Python harness at
  `tests/test_map_console_browser_smoke.py` serves `docs/`, drives
  `npx -y -p @playwright/test playwright test`, and stays excluded from the
  default `pytest` run via the new `browser_smoke` marker. Invoke with
  `make viewer-smoke` or `pytest -m browser_smoke`; the test skips when
  `node`, `npx`, or a system Chrome/Chromium is missing.

- **Map console JS moved to `docs/js/map_console.js`.**
  `docs/map.html` is now markup plus a single external script tag; the ~1100
  lines of viewer code (Leaflet 2D + Three.js 3D bootstrap, JS Dijkstra,
  inspector metrics, overlay toggles, URL-param / ready-signal bootstrap) live
  in `docs/js/map_console.js`. `tests/js/test_viewer_dijkstra.mjs` extracts
  `buildRestrictionIndex` and `dijkstra` from the new location; behaviour and
  committed regression tests are unchanged.

- **3D map console supports raycaster-based hover and click picking.**
  The Three.js preview now tracks each centerline `Line` and the graph node
  `Points` cloud as pickables. Hovering the 3D canvas updates a new
  `#hover-card` in the inspector (kind, ID, length, endpoints) and pauses the
  auto-rotate while the pointer is over a pickable target. Clicking without
  dragging feeds node hits into the existing `onNodeClick` flow, so the JS
  Dijkstra click-to-route works from the 3D view too and updates the 2D map
  / route metric in lockstep. The opt-in browser smoke gained a 3D hover +
  click assertion covering the new path.

- **Map console deep-links via `?from=&to=` plus a route steps inspector.**
  `docs/map.html?from=nXXX&to=nYYY[&dataset=...&view=3d]` now restores a
  turn-restriction-aware route at bootstrap by running the same JS Dijkstra
  the click-to-route UI uses. Drawing or clearing a dynamic route mirrors the
  selection into the URL via `history.replaceState()`, so any Paris-grid
  route (or future dataset route) is copy-pasteable. The inspector gained a
  `#steps-card` that lists each route edge with direction, per-edge length,
  cumulative distance, edge count, and total length; the card appears after
  a route is drawn and clears with `Clear route` or dataset switch. The
  browser smoke covers the `n312 → n191` deep link, asserting the card is
  visible, multiple steps render, and the URL retains `from` / `to`.

- **Berlin Mitte gets full Paris-grade overlays: TR + route + reachable.**
  Berlin Mitte was the only committed map dataset without a turn-
  restrictions overlay, a demo route, or a service-area overlay — so
  switching the viewer dropdown from Paris to Berlin dropped most of
  the interactive narrative. This change closes that gap. Fetched 37
  OSM `type=restriction` relations into `/tmp` via the existing
  `scripts/fetch_osm_turn_restrictions.py`, snapped them to the
  committed graph (17 land cleanly), and shipped them as
  `docs/assets/berlin_mitte_turn_restrictions.json`. Wrote a TR-aware
  demo route from `n32` (south end of bbox) to `n327` (north end),
  2 659 m / 48 edges, into `route_berlin_mitte.geojson`. Generated a
  600 m reachability overlay from `n32` into
  `reachable_berlin_mitte.geojson` (12 reachable nodes / 34 directed
  spans). The legacy `_write_paris_grid_reachability_asset` was
  refactored into a generic `_write_reachability_asset(dataset_id,
  ...)` so Paris and Berlin share the implementation. The viewer's
  `ROUTE_URLS` / `REACHABLE_URLS` / `RESTRICTIONS_URLS` maps gained
  the Berlin entries, so switching datasets in the dropdown
  automatically loads the new overlays.

- **Per-lane lane_boundary `subtype` reflects outer-vs-interior position.**
  Autoware reads `subtype=solid` on a lane boundary as "no lane change
  allowed" and `subtype=dashed` as "lane change permitted". The
  per-lane export was previously emitting every boundary as `solid`,
  which contradicted the `lane_change` regulatory_element relations
  the same exporter wrote. The fix splits boundaries by position:
  outermost left of lane 0 and outermost right of lane N-1 stay
  `solid`, every interior boundary between adjacent lanes becomes
  `dashed`. When `lane_markings` data is available and classifies the
  paint as `solid`, that wins. Paris grid emits 2 162 `solid` outer
  boundaries + 808 `dashed` interior boundaries (114·2 + 91·4 +
  28·6 + 6·8 across the 2 / 3 / 4 / 5-lane edges). `validate-lanelet2-tags`
  continues to report `result: ok` with 0 errors.

- **Per-lane Lanelet2 export emits `lane_connection` regulatory_elements.**
  `export_lanelet2` (single-lanelet) had a block that bundled every
  junction's incident lanelets into a `type=regulatory_element,
  subtype=lane_connection` relation so Autoware's planner could
  traverse from one lanelet to the next across a graph junction. The
  per-lane variant skipped that step, so the committed Paris / Berlin
  Lanelet2 outputs were islands of lanelets that did not form a
  routable network. `export_lanelet2_per_lane` now applies the same
  logic against `lanelet_id_by_edge`, attaching each junction's
  `junction_type` / `junction_hint` as `roadgraph:` tags. Paris ships
  707 lane_connection relations across its junctions; Berlin ships
  1 476. `validate-lanelet2-tags` continues to report
  `result: ok` with 0 errors.

- **OSM stop / give_way nodes now ship as Lanelet2 stop_line ways.**
  Previously each `kind=stop_line` observation only landed in
  `edge.attributes.hd.semantic_rules` and was silently skipped by the
  Lanelet2 exporter (which needs a 2-point polyline, not a single
  point). `scripts/refresh_docs_assets.py` gains a
  `_perpendicular_polyline()` helper that projects the OSM point onto
  the nearest matched-edge segment, computes the normal direction, and
  builds a 4 m line centred on the projection. The synthesised
  `polyline_m` rides through to `_build_stop_line_way`, which emits a
  proper `type=line_thin, subtype=solid, roadgraph:kind=stop_line` way
  in the Lanelet2 OSM. Paris grid: 5 ways for the 5 OSM stop /
  give_way fixes inside the bbox. `validate-lanelet2-tags` continues
  to report `result: ok`.

- **SRTM elevations flow through committed Paris / Berlin datasets.**
  New `scripts/fetch_node_elevations.py` POSTs every `kind=node` point in a
  committed map GeoJSON to Open-Elevation's public SRTM-30m endpoint and
  caches the result under `/tmp/osm_real_data/<dataset>_node_elevations.json`.
  `scripts/refresh_docs_assets.py` gains `_apply_node_elevations()` that
  stamps `node.attributes.elevation_m` and builds a linearly interpolated
  `edge.attributes.polyline_z`, so `enrich_sd_to_hd` now produces real
  `hd.slope_deg` values (Paris avg 1.31° |slope|, max 55° on short
  rooftop-to-valley edges) and the Lanelet2 exporter emits
  `<tag k="ele" v="N.NN"/>` on every graph-node it writes. Paris gets
  855 elevations (range 27-65 m) + 1 081 slope_deg; Berlin Mitte gets
  1 883 elevations. `validate-lanelet2-tags` still reports
  `result: ok` / 0 errors on both outputs. Routing with
  `--uphill-penalty` / `--downhill-bonus` becomes meaningful for these
  datasets for the first time, and `build --3d` becomes a no-op for
  committed bundles because the elevation pass already ran.

- **OSM `width=` tag drives the HD-lite envelope and becomes a lanelet width attribute.**
  The OSM tag collector in `refresh_docs_assets.py` now also captures
  `width=` (metres) onto `edge.attributes.osm_width_m`.
  `_widen_hd_envelope_for_osm_lanes` gains a precedence ladder:
  OSM `width` wins over OSM `lanes * 3.5 m` wins over the single-lane
  default, and the edge's `hd.quality` now reflects which source
  produced the envelope (`osm_width_tag` / `osm_lanes_offset_hd_lite` /
  `centerline_offset_hd_lite`). Paris grid distribution:
  87 `osm_width_tag` / 239 `osm_lanes_offset_hd_lite` / 755 default
  envelopes. The Autoware lanelet-tag helper also emits
  `<tag k="width" v="N.NN m"/>` on every lanelet whose edge carries
  `osm_width_m`. `validate-lanelet2-tags` still reports `result: ok`
  with 0 errors.

- **Per-lane Lanelet2 export now emits regulatory_element relations from semantic_rules.**
  The single-lanelet `export_lanelet2` already wired `traffic_light` /
  `stop_line` detections into `type=regulatory_element` relations; the
  per-lane version did not, so the committed Paris Lanelet2 OSM had
  zero regulatory_element relations despite carrying 288 real OSM
  traffic signals in `edge.attributes.hd.semantic_rules`. `export_lanelet2_per_lane`
  now tracks `lanelet_id_by_edge` (first lanelet per edge, i.e. lane 0)
  and walks the edge's `semantic_rules` after the lane loop to call the
  same `_build_traffic_light_regulatory` / `_build_stop_line_way` helpers.
  `_osm_regulatory_observations` in `refresh_docs_assets.py` now attaches
  a `world_xy_m` fix derived from the OSM node's `lon` / `lat`, so the
  new traffic_light regulatory nodes land at the real OSM position.
  The committed `map_paris_grid.lanelet.osm` now carries 288
  `subtype=traffic_light` relations plus 404 `subtype=lane_change`
  relations. Also fixes a doubled-application bug where
  `apply_camera_detections_to_graph` was called twice around the lane
  inference step and inflated the semantic_rules list.

- **Berlin Mitte ships a per-lane Lanelet2 OSM + the viewer picks it automatically.**
  The Berlin Mitte refresh path now runs the same
  `infer_lane_counts` + `export_lanelet2_per_lane` pipeline as Paris, so
  `docs/assets/map_berlin_mitte.lanelet.osm` (≈5 MB, Autoware-spec tags
  including `one_way` / `participant:vehicle` / `speed_limit` / `name`)
  is committed alongside the GeoJSON. `validate-lanelet2-tags` reports
  `result: ok` with 0 errors. The map console's `Lanelet2 OSM` toolbar
  link now consults a per-dataset `LANELET_URLS` map and flips between
  the Paris and Berlin outputs as the user switches datasets; unsupported
  datasets hide the link entirely.

- **Paris regulatory overlay switches from synthetic samples to real OSM nodes.**
  A new `scripts/fetch_osm_regulatory_nodes.py` fetches
  `highway=traffic_signals | stop | crossing | give_way | speed_camera` from
  Overpass for a bbox, and `scripts/refresh_docs_assets.py` projects each
  node onto the nearest Paris-grid edge (point-to-polyline, 20 m cutoff) so
  the committed `paris_grid_camera_detections.json` now ships 456 real
  observations — 288 traffic lights, 160 crossings (capped for overlay
  density), 5 stop/give-way, 3 speed cameras — each tagged
  `source="osm_node"` with its `osm_id`, `confidence=1.0`, and
  `match_distance_m`. The file previously held 9 hand-authored synthetic
  markers; the new file is ODbL-attributed per OSM. `apply_camera_detections_to_graph`
  feeds the observations into `edge.attributes.hd.semantic_rules` so both
  the viewer overlay and the Lanelet2 export pick them up.

- **OSM `lanes=` tag promotes HD-lite output to real multi-lane Lanelet2.**
  `infer_lane_counts` gained an "OSM lanes tag" source between lane
  markings and trace_stats so `build-osm-graph` edges stamped with
  `osm_lanes` get their lane count from OpenStreetMap directly (instead
  of defaulting to 1). `scripts/refresh_docs_assets.py` now also calls a
  new `_widen_hd_envelope_for_osm_lanes()` after `enrich_sd_to_hd`, which
  rewrites `hd.lane_boundaries` on every multi-lane edge using
  `osm_lanes * 3.5 m` as the total road width so the HD-lite paint lines
  hug the real road. Paris grid widens 239 edges, and
  `docs/assets/map_paris_grid.lanelet.osm` now ships 1 485 lanelets
  (842 single-lane + 228 + 273 + 112 + 30 for 2 / 3 / 4 / 5-lane roads,
  one per lane) instead of 1 081. `validate-lanelet2-tags` still reports
  `result: ok` with zero errors.

- **Lanelet2 export emits Autoware-spec lanelet tags.**
  Every `type=lanelet` relation now carries `one_way=yes|no`,
  `participant:vehicle=yes`, `speed_limit=<N> km/h`, and an OSM street
  `name` alongside the existing `subtype=road` / `location=urban`. A new
  `_autoware_lanelet_tags_from_attributes()` helper reads edge
  `osm_oneway` / `osm_maxspeed` / `osm_name` (plus `hd.semantic_rules`
  for speed limits) and is used from both `export_lanelet2` and
  `export_lanelet2_per_lane`. The OSM tags land on the graph earlier
  now: `scripts/refresh_docs_assets.py` calls the new
  `_inject_osm_tags_into_graph_edges()` on the Paris grid and Berlin
  Mitte graphs before `export_map_geojson`, so the GeoJSON spreads them
  into feature properties at the same time the Lanelet2 exporter picks
  them up. The committed `docs/assets/map_paris_grid.lanelet.osm` now
  reports "result: ok" from `validate-lanelet2-tags`, the frozen sample
  bundle's `lanelet/map.osm` was refreshed to carry the same new tags,
  and the byte-gate test reports no drift.

- **Paris grid ships a per-lane Lanelet2 OSM artifact + an HD-lite scope notice.**
  `scripts/refresh_docs_assets.py` now runs
  `infer_lane_counts(base_lane_width_m=3.5)` on the committed Paris OSM grid
  and exports a committed
  [`docs/assets/map_paris_grid.lanelet.osm`](docs/assets/map_paris_grid.lanelet.osm)
  (1 081 `type=lanelet` relations + 2 162 boundary ways) via
  `export_lanelet2_per_lane()`. Camera detections are re-applied after the
  inference so the committed `semantic_rules` survive, and the map console
  toolbar gained a `Lanelet2 OSM` download link. README, Showcase, the
  Pages landing page, and `docs/assets/ATTRIBUTION.md` all now carry an
  honest "**HD-lite, not survey-grade**" scope notice that names the real
  gaps (3.5 m envelope lane widths, 1-lane fallback without markings,
  synthetic regulatory overlays, elevation absent without `z`), so
  visitors understand that Autoware can load the export but autonomous
  vehicle deployment still needs calibrated sensors and cm-class QA.

- **GitHub Pages entry point lands on the 2D / 3D map console.**
  Visitors opening `https://rsasaki0109.github.io/roadgraph_builder/` used
  to hit the SVG diagram viewer and see no map — the console lived at
  `/map.html`, one extra hop away. The old `docs/index.html` is now
  renamed to `docs/diagram.html` (keeping the diagram + route-explain
  diagnostics panel intact), and `docs/index.html` is a small
  landing page that shows the animated hero + tier table + explicit
  buttons for both entry points and redirects to `map.html` after three
  seconds via `<meta http-equiv="refresh">`. `docs/map.html`, README,
  Showcase, `tests/test_route_explain_asset.py`, and the `viewer.js`
  comment all moved from `index.html` to `diagram.html` where the
  diagnostics panel actually lives.

- **README and Showcase reorganised around the map console.**
  `README.md` and `docs/SHOWCASE.md` now lead with the animated map-console
  hero and a **From SD to HD** tier table that walks visitors through
  Basic / SD / HD / Full with the matching pipeline step for each tier
  (`build-osm-graph`, `convert-osm-restrictions` + `route`,
  `enrich --lane-width-m` + `apply-camera` + `reachable`). The older
  "Visualization results" section is consolidated into the top so every
  GitHub reader sees the animated + static previews, inspector
  explanation, and local-run snippet before the feature table. No code
  changes.

- **SD / HD layer tier toggle in the map console.**
  A new `Mode` select in the toolbar switches between four layer tiers:
  **Basic** (centerlines + nodes + trajectory), **SD** (+ route + turn
  restrictions), **HD** (+ lane boundaries + semantic markers + reachability),
  and **Full** (everything, the default). Both the 2D Leaflet layers and
  the 3D Three.js scene honour the active tier — a single `MAP_MODE_KINDS`
  set drives a `filter:` on every `L.geoJSON(...)` call and wraps each
  `render3DScene` include predicate, while `drawDynamicRoute` /
  `drawDynamicReachability` gate on the tier without dropping
  `scenePayload.*` data. A `rebuildLeafletLayers()` helper rebuilds all
  Leaflet layers from the current snapshot on mode change (no re-fetch).
  Browser smoke walks Full → Basic → HD and asserts the SVG path count
  collapses, then grows again, as tiers disappear and come back.

- **Hover card updates when you mouse over 2D Leaflet features.**
  Previously the inspector's `#hover-card` only reacted to the 3D
  raycaster. A new `hoverHitFromProps()` helper turns a feature property
  bag into the shape `setHoverCard()` already accepts, and
  `bindHoverSync(feature, layer)` wires `mouseover` / `mouseout` on every
  Leaflet layer so the 2D map surfaces the same edge / node metadata
  (Edge ID, Primary · 3 lanes, Node · T-junction, reachable spans, etc.)
  as the 3D view. The empty-card hint now reads "Hover an edge or node
  (2D or 3D) …". Browser smoke asserts the helper produces the expected
  shapes for node / centerline / reachable_edge and that
  `setHoverCard(null)` resets the card.

- **Live reachability-from-click in the map console.**
  `docs/map.html` gains a `Reach` budget select (250 / 500 / 1000 / 2000 m,
  default 500) and a `Reach from click` toggle button. Activating the toggle
  flips the next node click from routing to reachability: a new JS
  `reachableWithin(graph, start, budgetM, restrictions)` runs a directed-
  state Dijkstra with a metre cap (mirroring the CLI `reachable`
  semantics) and returns per-edge spans including a `reachable_fraction`
  for partial edges. `buildReachableFeatures()` emits a FeatureCollection
  that matches the committed `reachable_paris_grid.geojson` shape, with
  `clipLineToFraction()` trimming partial edges to their reachable length.
  `drawDynamicReachability()` replaces the prebaked overlay on the 2D
  Leaflet layer, refreshes the 3D scene payload, and updates
  `#stat-reach`. Browser smoke asserts the flow end-to-end (button toggles
  active, `onNodeClick('n191')` produces a `reach n191 (500 m) …` status
  with a populated span count, and the button returns to inactive).

- **Synthetic camera / regulatory overlay on the Paris grid viewer.**
  A committed, hand-authored
  `docs/assets/paris_grid_camera_detections.json` carries nine synthetic
  detections (three `traffic_light`, two `stop_line`, two `crosswalk`, two
  `speed_limit`) placed along the committed Paris TR route.
  `scripts/refresh_docs_assets.py` applies them through
  `apply_camera_detections_to_graph` before exporting, then post-processes
  the GeoJSON to add one Point feature per detection at a sensible
  position along the owning centerline (traffic lights at 0.92 of the
  polyline length, stop lines at 0.85, crosswalks / speed limits at the
  midpoint). The viewer renders each kind with a distinct colour-coded
  marker, popups show the kind / edge id / confidence / source, the
  Leaflet legend documents the palette, and a new `#stat-semantics`
  inspector tile surfaces the count. Browser smoke asserts the count is
  populated on Paris grid. Labels are synthetic repo-licensed data and
  not real perception output; the JSON's `notes` field spells this out.

- **Route engine diagnostics surface inside the map console.**
  The viewer's directed-state JS Dijkstra now counts expanded states,
  queued states, and heap pops during its heap loop and returns them on
  a `diagnostics` field that matches the shape the CLI's `route --explain`
  emits. `drawDynamicRoute()` pipes the numbers into a new
  `#engine-card` inspector block (engine badge, expanded / queued /
  pops / TR indexed, plus a hint that identifies the engine as the
  Dijkstra fallback the CLI also uses when safe A* is unavailable).
  `clearRoute()` hides the card. The opt-in browser smoke asserts the
  card appears for the Paris TR deep link with the `dijkstra` badge and
  a non-zero expanded-state count.

- **Animated map-console hero GIF for the README and Showcase.**
  `scripts/record_map_console_hero.py` serves `docs/`, drives system Chrome
  through Playwright's `recordVideo` context for a scripted demo (Paris
  `n312 → n191` deep link → 2D soak → 3D toggle with auto-rotate), and pipes
  the resulting WebM through ffmpeg's two-pass `palettegen` / `paletteuse`
  to produce a committed `docs/images/map_console_hero.gif`
  (720×420, 8 fps, 64 colours, ~4.2 MB). README "Visualization results" and
  `docs/SHOWCASE.md` lead with the GIF so the map-console motion is visible
  before anyone runs the viewer locally. Requires Playwright's bundled
  ffmpeg (`npx playwright install ffmpeg`) in addition to system Chrome
  and system ffmpeg.

- **Centerlines are coloured by OSM road class with OSM lane counts exposed.**
  `scripts/refresh_docs_assets.py` now re-reads the raw Overpass highways JSON
  after graph construction and stamps `highway` / `osm_lanes` / `osm_maxspeed`
  / `osm_name` / `osm_oneway` onto every centerline feature via a
  point-to-polyline nearest-way match. For the Paris grid, 1 080 of 1 081
  centerlines end up tagged (residential 429, service 172, living_street 140,
  secondary 138, tertiary 99, primary 68, unclassified 31, primary_link 3);
  Berlin Mitte runs through the same helper. The map console added a
  `HIGHWAY_COLORS` / `HIGHWAY_LABELS` palette so both the 2D Leaflet polylines
  and the 3D Three.js lines draw every centerline in its road-class colour
  (motorway → red through residential → cyan), the Leaflet popups and
  `#hover-card` now show `Edge · Primary · 3 lanes` plus maxspeed / street
  name when known, and a new `#classes-card` in the inspector lists the
  active dataset's class counts with matching colour swatches. Browser smoke
  asserts the card is populated (≥ 4 classes with the expected `N classes ·
  N/N tagged` header). Hero screenshots were regenerated so the committed 2D
  and 3D captures carry the road-class palette.

- **Graph nodes in the map console are coloured by junction type.**
  `docs/js/map_console.js` now reads `junction_type` / `junction_hint` from
  every node feature and paints markers with a shared palette across the 2D
  Leaflet view (per-marker fill) and the 3D Three.js scene (per-vertex
  `THREE.Float32BufferAttribute('color')` + `vertexColors: true`). T / Y /
  crossroads / X / complex junctions, through-or-corner spans, dead ends,
  self-loops, and cul-de-sacs each get a distinct colour. A new
  `#junctions-card` in the inspector lists the active dataset's category
  counts with matching swatches, the hover card renders as `Node · T-junction`
  (etc.) when picking in 3D, and the Leaflet legend grew colour rows for the
  same palette. Browser smoke asserts the junctions breakdown is populated
  (≥ 4 categories with the expected `N types · N nodes` header) on Paris grid.

- **Paris grid and new Berlin Mitte viewer datasets ship HD-lite lanes.**
  `scripts/refresh_docs_assets.py` now runs `enrich_sd_to_hd(lane_width_m=
  3.5)` on the OSM-highway Paris grid, so `docs/assets/map_paris_grid.geojson`
  carries 2 162 `lane_boundary_{left,right}` features alongside its 1 081
  centerlines. The 2D and 3D map console views finally show the green /
  purple paint envelopes the legend advertised. When
  `/tmp/berlin_mitte_raw.json` is present, the refresh step also writes
  `docs/assets/map_berlin_mitte.geojson` (1 883 nodes / 2 063 centerlines /
  4 126 HD-lite lane boundaries) plus `berlin_mitte_origin.json`, and the
  viewer dropdown grows a **Berlin Mitte (OSM highways, HD-lite lanes,
  ODbL)** option. ATTRIBUTION.md documents the Berlin source / refetch
  recipe and the lane-boundary provenance. The opt-in browser smoke gains
  a Berlin switch case asserting `#stat-lanes` exceeds 1 000 after the
  dropdown change, and the committed hero screenshots were refreshed so
  the HD-lite paint lines are visible in both 2D and 3D captures.

- **Route export, deep-link auto-fit, and route-aware hero screenshots.**
  A new `Download route GeoJSON` button next to `Clear route` becomes
  enabled once a route is drawn and streams the current
  `scenePayload.route` FeatureCollection as
  `route_<dataset>_<from>_<to>.geojson`. Opening the console through a
  deep link now re-fits the 2D map to the route polyline's bounds
  (padding 48, max zoom 17) so users land on the route rather than the
  dataset-wide view. `scripts/render_map_console_screenshot.py` picked
  up `--from-node` / `--to-node`, defaulting to `n312 → n191`, so the
  committed `docs/images/map_console_{2d,3d}.png` hero shots now show
  the Paris TR-aware route, the populated Route steps card, the
  deep-link status line, and the enabled download button. Browser
  smoke asserts the download produces a valid GeoJSON FeatureCollection
  with a `kind=route` LineString and preserved `from_node` / `to_node`.

- **Reachability / service-area analysis is available from the routing CLI.**
  New `routing.reachability.reachable_within` and `roadgraph_builder reachable`
  report nodes and directed edge spans reachable from a start node within a
  routing cost budget. The command supports node ids or `--start-latlon`,
  optional turn restrictions, the existing observed/confidence/slope cost
  hooks, JSON output, and clipped GeoJSON via `--output`.

- **The docs map now ships a Paris reachability overlay.**
  `scripts/refresh_docs_assets.py` writes `docs/assets/reachable_paris_grid.geojson`
  from the committed Paris grid map and turn restrictions, and the Leaflet map
  plus static README/Site preview render the 500 m service-area spans alongside
  the TR-aware route.

- **Launch and showcase docs are ready for public discovery.**
  `docs/SHOWCASE.md` gives a 30-second product tour with reproducible signals,
  and `docs/LAUNCH.md` collects public announcement copy for X / Bluesky,
  LinkedIn, Hacker News, Reddit, and quick demos.

### Changed

- **Repeated functional shortest-path calls reuse a default planner cache.**
  The public `shortest_path(...)` wrapper now caches a graph-local default
  `RoutePlanner` for the common no-restrictions / no-extra-cost-hooks case,
  using exact cache validation on small graphs and fixed node / edge samples
  on larger graphs to avoid scanning every coordinate on each wrapper call.
  The new `shortest_path_grid_120_functional` benchmark covers 120 repeated
  wrapper calls on a 55x55 grid and dropped from local passes around 4.6-5.7 s
  to about 0.7-1.0 s, with a committed no-warmup baseline of 0.812 s. Explicit
  `RoutePlanner` remains the strongest choice when routing over a graph that is
  being mutated between queries.

- **Shortest-path routing now uses a safe A* fast path.**
  `RoutePlanner` uses cached straight-line node distance as an A* heuristic
  only when the configured edge costs preserve the base metric lower bound;
  discounted observed/downhill costs and graphs whose node positions do not
  bound edge costs fall back to Dijkstra. Equal-priority A* candidates now
  prefer lower remaining distance. `shortest_path_grid_120` dropped from about
  0.96 s to about 0.60 s in the committed baseline.

- **Repeated shortest-path queries can reuse prepared routing state.**
  `routing.shortest_path.RoutePlanner` prepares the routing index, weighted
  adjacency, parsed turn policy, and lane counts once for many route queries.
  The functional `shortest_path(...)` API remains as a one-query wrapper, while
  `shortest_path_grid_120` now uses the planner and dropped from about 1.71 s
  to about 0.96 s in the committed baseline, with warm direct passes around
  0.60 s locally.

- **Routing search internals now share one core policy layer.**
  `roadgraph_builder.routing._core` owns routing topology caching, weighted
  adjacency construction, edge-cost hooks, and parsed turn policies used by
  both `shortest_path` and reachability. Focused tests now cover that shared
  layer directly so future routing performance work has a smaller blast radius.

- **Repeated reachability queries can reuse prepared routing state.**
  `routing.reachability.ReachabilityAnalyzer` prepares the routing index,
  weighted adjacency, and turn-restriction policy once for many service-area
  queries. The no-turn-restriction path now uses node-level Dijkstra, and
  `reachable_grid_120` dropped from about 2.6 s to about 0.27 s locally.

- **Benchmark coverage now includes reachability queries.**
  `scripts/run_benchmarks.py` now includes `reachable_grid_120`, a 120-query
  service-area workload on the same 55x55 routing grid as
  `shortest_path_grid_120`. The benchmark consumes reached node and directed
  edge-span counts, and `docs/benchmarks.md` records the current local timing
  at about 2.6 s with a 60 m cost budget.

- **Benchmark results can be saved and compared from a committed baseline.**
  `scripts/run_benchmarks.py --output PATH` writes result JSON in the same shape
  accepted by `--baseline`, and `docs/assets/benchmark_baseline_0.7.2-dev.json`
  records the current deterministic suite for the 3x regression gate.

- **Packaging metadata now uses a SPDX license expression.**
  `pyproject.toml` now declares `license = "MIT"` with `license-files`, and
  the legacy license classifier was removed so modern setuptools builds no
  longer warn about deprecated license metadata.

- **Main is reopened for 0.7.2 development.**
  Package metadata and `roadgraph_builder.__version__` now report
  `0.7.2.dev0` after the `v0.7.1` tag, avoiding new post-release artifacts
  that reuse the shipped `0.7.1` version.

- **GitHub Actions workflows now use Node 24 action majors.**
  CI, release, benchmark, city-scale, and PyPI workflows were moved to
  `actions/*` / release action tags whose `action.yml` declares `node24`,
  so they no longer need the temporary
  `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` environment flag.

- **GitHub star-growth surfaces now show the current product shape.**
  README now leads with why the project is useful, the GitHub About copy was
  refreshed for OSM / LiDAR / camera / Lanelet2 / routing support, package
  metadata uses the broader GPS/OSM description, and GitHub issue / PR
  templates make bug reports, feature requests, and showcases easier to open.

- **Repeated routing queries now reuse a cached topology index.**
  `shortest_path` caches node ids, edge lengths, edge lookup, and base
  adjacency on each `Graph` instance, invalidating when node/edge list shape
  or edge polyline objects change. The no-turn-restriction path now uses a
  node-level Dijkstra fast path instead of the directed incoming-edge state
  machine, while turn-restricted and lane-level routing keep the existing
  stateful search. A 55x55 synthetic grid with 120 queries dropped from about
  7.0 s / 6.5 s to 2.7 s / 2.3 s / 1.9 s across repeated local passes, and
  `scripts/run_benchmarks.py` now includes `shortest_path_grid_120` to keep
  this route-heavy workload visible.

- **Repeated nearest-node queries now use a spatial hash index.**
  `nearest_node` caches graph nodes into per-Graph spatial cells and searches
  nearby cells with exact distance checks, falling back to cell-boundary
  lower bounds for far-out queries. A 300x300 node grid with 2000 queries
  dropped from about 59.3 s / 53.6 s with the old Python full scan to about
  0.63 s / 0.57 s / 0.59 s locally, and `scripts/run_benchmarks.py` now
  includes `nearest_node_grid_2000`.

- **Map matching now uses a shared nearest-edge spatial index.**
  `routing.edge_index` caches edge polyline segments into spatial cells and is
  shared by `snap_trajectory_to_graph` and HMM candidate generation. The
  nearest-edge matcher still applies exact segment projection and graph-order
  tie-breaking, but samples query only nearby cells instead of scanning every
  edge. The new `map_match_grid_5000` benchmark covers 5000 snaps on a 120x120
  grid graph and records a committed baseline of 1.519 s.

- **Map matching can explain its projection hot path.**
  `roadgraph_builder match-trajectory --explain` keeps the normal stats and
  sample JSON shape, then adds a `stats.diagnostics` object with elapsed
  milliseconds, projection/candidate query counts, and edge-index details such
  as segment count, cell count, cell size, and overflow segment count. The docs
  now include `docs/assets/map_match_explain_sample.json` with nearest-edge and
  HMM examples generated from the frozen toy bundle.

- **HMM map matching uses along-edge transition distances.**
  `hmm_match_trajectory` now carries each candidate's projection arc length and
  edge length through Viterbi, so transition penalties include the distance from
  the previous projection to an endpoint, graph distance between endpoints, and
  the distance from the next endpoint to the current projection. This removes a
  shortcut that treated connected edge transitions as endpoint-to-endpoint only.
  The benchmark suite now includes `hmm_match_bridge_500`, which covers 500
  boundary-straddling HMM samples with nearby disconnected bridge distractors.
  Transition Dijkstra now reuses the routing index's cached base adjacency and
  candidates carry precomputed endpoint tail costs. The new
  `hmm_match_long_grid_2000` benchmark extends the same correctness signal to a
  2000-sample snake-grid trajectory with disconnected alias edges.

- **Edge projection index cells are tighter for map matching.**
  The spatial index now sizes cells at 2.0x nominal segment spacing instead of
  4.0x, reducing candidate segment fan-out while keeping the long-segment
  overflow fallback. The committed baselines are now `map_match_grid_5000` at
  0.613 s, `hmm_match_bridge_500` at 0.034 s, and
  `hmm_match_long_grid_2000` at 0.131 s.

- **Routing caches now detect more graph mutations.**
  `nearest_node` cache signatures now cover every node on small/medium graphs
  and evenly sampled node positions on very large graphs, so middle-node
  position replacement no longer reuses a stale spatial index. `shortest_path`
  routing signatures now include a polyline coordinate checksum, so in-place
  geometry edits invalidate cached edge lengths.

- **Large synthetic graph builds avoid quadratic endpoint scans.**
  Endpoint union-find now uses a uniform spatial grid instead of checking every
  endpoint pair, and near-parallel edge merging now evaluates only edge pairs
  whose endpoint neighborhoods can satisfy the existing distance-sum rule. The
  50x50 synthetic grid build dropped from about 42-46 s local passes to about
  1.2-1.7 s, with local `python scripts/run_benchmarks.py --no-warmup`
  runs measuring `polylines_to_graph_10k_synth` around 1.0-1.4 s.

- **T-junction splitting now projects only nearby segments.**
  The fast T-junction splitter indexes expanded segment bounding boxes instead
  of expanded whole-polyline boxes, then applies the same global-nearest
  projection and interior guard semantics per endpoint/polyline pair. The
  50x50 synthetic grid build now runs around 0.5 s on warm local passes, and
  `python scripts/run_benchmarks.py --no-warmup` measured
  `polylines_to_graph_10k_synth` at 0.819 s locally.

- **Near-parallel merge candidate checks do less per-edge work.**
  `merge_near_parallel_edges` now reuses precomputed edge endpoint lists,
  inlines the candidate-neighborhood walk, and avoids sorted temporary
  candidates and endpoint-pair set construction in the hot loop. A local
  benchmark run measured `polylines_to_graph_10k_synth` at 0.471 s.

- **Large GeoJSON exports do less repeated coordinate math and can be compact.**
  `export_map_geojson` now precomputes the WGS84 conversion constants once per
  map, preserving default pretty output while reducing large-map feature build
  time. `export_map_geojson(compact=True)`, `export_map_bundle(...,
  compact_geojson=True)`, and `export-bundle --compact-geojson` write
  `sim/map.geojson` without indentation for faster, smaller large bundle
  exports. On a local 180x180 synthetic grid, GeoJSON document build dropped
  from about 1.42 s to 0.70 s, default pretty export from about 7.03 s to
  3.05 s, and compact export wrote the same parsed document in about 1.76 s
  while shrinking output from about 42.8 MB to 23.6 MB.

- **Large bundle JSON outputs can be compact without changing defaults.**
  JSON serialization now goes through a shared writer that keeps pretty output
  by default and supports compact separators when requested. `export_graph_json`
  accepts `compact=True`, and `export_map_bundle(..., compact_bundle_json=True)`
  / `export-bundle --compact-bundle-json` compact `nav/sd_nav.json`,
  `sim/road_graph.json`, and `manifest.json` while leaving GeoJSON under the
  separate `--compact-geojson` flag. On a local 180x180 synthetic grid,
  `road_graph.json` export dropped from about 1.59 s / 21.3 MB to 0.43 s /
  10.5 MB, and an `sd_nav`-shaped document dropped from about 0.65 s /
  17.0 MB to 0.15 s / 11.6 MB.

- **README quick-start smoke now covers route guidance and compact bundle flags.**
  The CLI end-to-end regression now runs from a fresh checkout even when the
  console script has not been installed, drives `export-bundle` through
  validators, `route --output`, `guidance`, and `validate-guidance`, and adds a
  compact bundle smoke for `--compact-geojson --compact-bundle-json`.

### Fixed

- **Paris splitter golden length check now tolerates Python/Numpy drift.**
  The real-data splitter regression still pins edge/node IDs, but its aggregate
  length tolerance now allows the few-meter variation observed on the Python
  3.10 CI lane while keeping topology drift guarded.

- **Benchmark script direct execution works from a source checkout.**
  `python scripts/run_benchmarks.py --no-warmup` now inserts the repository
  root into `sys.path`, so the documented command works even when the package
  has not been installed into the active Python environment.

## [0.7.1] — 2026-04-21

### Changed

- **README measured results are more compact.**
  The current-main validation numbers now sit near the top of `README.md` in a
  compact routing / accuracy / tuning / memory table, with the longer duplicate
  post-release table removed so the docs preview and quick-start sections are
  easier to scan.

- **Docs viewer result cards are easier to scan.**
  `docs/index.html` now has a clearer post-release results section with
  structured metric labels and updated float32 messaging. `docs/css/viewer.css`
  refreshes the palette, card spacing, focus states, and responsive metric
  grid so the SVG preview and validation numbers hold up better on desktop and
  mobile.

- **Manifest release policy is documented.**
  README and the frozen bundle notes now spell out that release-bundle tests
  normalize only `roadgraph_builder_version` and `generated_at_utc` in
  `manifest.json`; every other manifest field is part of the stable release
  surface unless changed intentionally.

- **Release bundle tests now include a byte-identity gate for stable outputs.**
  The default `export-bundle` path is rebuilt from the sample trajectory,
  detections, turn restrictions, and LiDAR fixture during tests, and stable
  generated artefacts (`sd_nav.json`, `road_graph.json`, `map.geojson`,
  `trajectory.csv`, Lanelet2 OSM, and generated README files) must match
  `examples/frozen_bundle/` byte-for-byte. The manifest is also compared after
  normalizing only `roadgraph_builder_version` and `generated_at_utc`, so
  provenance drift is caught without pinning release-time metadata.

- **Float32 drift comparison is now reproducible as a script.**
  `scripts/compare_float32_drift.py` builds float64 and opt-in float32
  bundles from the same trajectory CSV, then compares `road_graph.json`,
  `sd_nav.json`, `map.geojson`, and Lanelet2 OSM topology plus coordinate
  drift. It can write JSON/Markdown reports and fail as a release gate on
  topology change or max coordinate drift.

- **Float32 memory profiling now includes a 1M-row synthetic workload.**
  A `/tmp`-only 1,000,000-row trajectory profile shows the expected
  `Trajectory.xy` allocation drop from 24,000,568 B to 16,000,568 B and a
  tracemalloc peak drop of about 19 MB, while process RSS after full
  `export-bundle` only falls by about 2.6 MB because large temporary build and
  GeoJSON serialization allocations dominate the high-water mark.

- **Float32 memory profiling now includes an OSM public-trace replay stress.**
  A `/tmp`-only replay built from Paris, Tokyo, and Berlin public trackpoints
  shows the same direct XY allocation saving, but full `export-bundle` RSS on
  a 75k-row replay only falls by about 4 MB and the drift comparator reports
  edge / Lanelet ID instability under float32. The default therefore remains
  float64.

- **README release surface is now explicit about shipped vs post-release work.**
  The README separates the v0.7.0 shipped command surface from v0.7.1
  measured results, so validation numbers, docs preview status, and float32
  drift measurements read as patch-release follow-up work rather than part of
  the original v0.7.0 tag. It also removes stale "trajectory CSV only" and shell
  completion caveats.

- **CLI command boundaries are now split by domain.**
  `roadgraph_builder/cli/main.py` is now a thin dispatcher with shared loading
  helpers. Command parser/handler code lives in domain modules:
  `build`, `validate`, `routing`, `export`, `camera`, `lidar`, `osm`,
  `guidance`, `trajectory`, `hd`, `incremental`, and `dataset`.
  Each split adds direct handler tests with injected I/O so command behavior
  can be verified without subprocess-only coverage.

- **README / GitHub Pages now surface measured results.**
  README adds a compact measured-results table for the Paris TR-aware route,
  lane-count accuracy baselines, cross-city bundle tuning, and float32 drift
  report. The GitHub Pages diagram viewer adds matching metric cards below the
  Paris route preview so the live docs show both the visualization and the
  latest validation numbers.

- **README / GitHub Pages now show a polished Paris route visualization.**
  `docs/images/paris_grid_route.svg` is generated from the committed Paris
  OSM-highway GeoJSON, TR-aware route overlay, and turn-restriction JSON.
  README embeds the preview and links to the interactive Pages map; the Pages
  diagram viewer adds a compact result card below the live SVG viewer.

- **Bundle tuning now includes a Berlin Mitte public-GPS sweep.**
  `docs/bundle_tuning.md` adds a third real-data OSM public trackpoints
  sample (`13.3700,52.5100,13.4000,52.5250`, 7500 points) with the same
  `max-step-m` / `merge-endpoint-m` sweep used for Paris and Tokyo. The
  result keeps `--max-step-m 40 --merge-endpoint-m 8` as the conservative
  cross-city starting point, with bundle validation passing for the Berlin
  `40/8` artefact.

- **CLI completions now cover the v0.6/v0.7 command surface.**
  Bash and zsh completions include the lane-count, Lanelet2 validation,
  camera lane-detection, incremental update, and dataset batch commands added
  after v0.5, with common new flags such as `--per-lane`,
  `--allow-lane-change`, `--ground-plane`, and `--lane-markings-json`.
  The completion smoke test now derives the expected subcommands from the
  argparse parser so future CLI additions cannot silently drift.

- **V1 follow-up: Paris 20e now uses the same canonical 20 m accuracy run.**
  `docs/accuracy_report.md` replaces the placeholder shipped-CSV note with a
  live Overpass measurement for bbox `2.3900,48.8450,2.4120,48.8620`:
  794 ways / 3471 nodes, 245 ways with `lanes=`, 997-edge graph,
  193/997 matched at 20 m, **MAE = 0.938 lanes**.

- **V1 follow-up: real-data α accuracy numbers for Tokyo Ginza + Berlin Mitte.**
  `docs/accuracy_report.md` replaces the `[not yet measured]` rows with
  Overpass-fetched numbers captured 2026-04-20: Tokyo Ginza (`139.7600,
  35.6680,139.7750,35.6750`, 415 ways / 1891 nodes) → 598-edge graph,
  113/598 matched at 20 m, **MAE = 0.903 lanes**; Berlin Mitte (`13.3700,
  52.5100,13.4000,52.5250`, 1659 ways / 4748 nodes) → 1640-edge graph,
  531/1640 matched at 20 m, **MAE = 1.220 lanes**. Both are `source=default`
  baselines (no LiDAR markings / trace_stats) and document the 20 m canonical
  tolerance vs the original 5 m recipe.

- **V3 follow-up: float32 trajectory optimization now has an opt-in prototype.**
  `docs/handoff/float32_trajectory.md` records the dtype flow and
  byte-identity impact matrix. `load_trajectory_csv(..., xy_dtype="float32")`,
  `BuildParams(trajectory_xy_dtype="float32")`, CLI `--trajectory-dtype
  float32`, and `scripts/profile_memory.py --trajectory-dtype float32` now
  allow explicit coordinate-array memory experiments while default trajectory
  loading remains float64. `docs/float32_drift_report.md` records the first
  float64/float32 comparison: topology unchanged on Paris and Berlin samples,
  <1 mm max coordinate drift, but no process-level RSS win large enough to
  justify a default change.

### Fixed

- **V1: `measure_lane_accuracy.py` now handles meter-frame graphs.** When the
  graph JSON carries `metadata.map_origin` (written by `build-osm-graph` with
  an origin), OSM node lon/lat are converted to the same local ENU frame
  before the centroid-distance check, instead of silently comparing meters to
  degrees. Synthetic fixtures without `map_origin` keep the original
  haversine path. New unit test:
  `test_map_origin_converts_osm_to_meter_frame`.

- **3D2: silence `RuntimeWarning: invalid value encountered in divide` from
  `_rgb_to_hsv`.**  Line `delta / cmax` at `lane_detection.py:100` warned on
  pure-black pixels (0/0) because `np.where` evaluates both branches before
  selecting; rewritten to `np.divide(..., where=cmax > 0)` with a
  zero-initialised out buffer.  Running the full suite under
  `-W error::RuntimeWarning` now reports zero warnings (previously 6 tests
  raised on this path).

- **Perf flake: isolate the 50×50 grid wall-time test under `@pytest.mark.slow`.**
  `test_50x50_grid_within_budget` sat at ~22 s against a 30 s budget, so
  loaded CI would intermittently breach the budget. Budget widened to 60 s
  and tagged `slow`; `pyproject.toml` now excludes both `city_scale` and
  `slow` markers from the default run (`-m 'not city_scale and not slow'`).
  Opt-in: `pytest -m slow`. Side effect: default `make test` drops from
  ~56 s → ~27 s.

## [0.7.0] — 2026-04-20

### Added

- **V2: City-scale OSM regression tests** — `tests/test_city_scale.py` (3 parametrised tests: Paris 20e arr., Tokyo Setagaya, Berlin Neukölln) fetches OSM highways via Overpass, builds a graph, exports a bundle to `/tmp/`, and asserts edge_count ≥ threshold + zero degenerate self-loops. Tests are tagged `@pytest.mark.city_scale`; `pyproject.toml` registers the marker and adds `addopts = "-m 'not city_scale'"` so plain `pytest` / `make test` skips them (3 deselected). Run with `pytest -m city_scale`. `.github/workflows/city-bench.yml` is a manual `workflow_dispatch` workflow (no `on: push` / `on: schedule`); stores bundle artefacts + console output as GitHub Actions artefacts.

- **V1: Real-data α lane-count accuracy campaign** — `scripts/measure_lane_accuracy.py` matches graph edges (with `hd.lane_count` from `infer-lane-count`) to OSM way `lanes=` tags via centroid proximity (default 5 m) and tangent alignment (cosine ≥ 0.7). Emits confusion matrix, MAE, per-pair detail JSON. `docs/accuracy_report.md` records the Paris 20e arr. / Tokyo Ginza / Berlin Mitte bbox recipe; Paris numbers are from the shipped OSM public GPS graph (all edges default `lane_count=1` without lane markings); Tokyo Ginza and Berlin Mitte are marked `[not yet measured]` pending a live Overpass fetch. Not run by CI (`make accuracy-report` recipe in docs).

- **A2: Autoware `lanelet2_validation` round-trip bridge** — new `roadgraph_builder/io/export/lanelet2_validator_bridge.py` module shells out to `lanelet2_validation --map-file <path>` when it is on PATH and parses stdout/stderr for error / warning counts (summary-line regex with line-count fallback). Returns a structured dict `{status, errors, warnings, error_lines, return_code}`. CLI: `validate-lanelet2 map.osm [--timeout N]` — exits 0 when the tool is absent (skip JSON `{"status": "skipped"}` on stdout + warning on stderr) or when errors=0; exits 1 on ≥1 error with structured JSON on stdout and error summaries on stderr. Distinct from `validate-lanelet2-tags` (tag completeness only).
- **A3: Lane-change routing + Lanelet2 `lane_change` relation** — `shortest_path` gains `allow_lane_change` / `lane_change_cost_m` parameters extending the Dijkstra state to `(node, incoming_edge, direction, lane_index)`. Lane swaps within the same edge cost `lane_change_cost_m` (default 50 m). The returned `Route.lane_sequence` carries the per-step lane index (None when `allow_lane_change=False`). `export_lanelet2_per_lane` gains a `lane_markings` parameter and now tags each `lane_change` relation with `sign=solid` (solid boundary → prohibited) or `sign=dashed` (dashed / unknown → permitted); without `lane_markings` the sign defaults to `dashed`. CLI: `route --allow-lane-change [--lane-change-cost-m M]`.
- **A1: Full traffic_light / stop_line regulatory_element wiring** — `export_lanelet2` gains a `camera_detections` parameter (and the `export-lanelet2 --camera-detections-json` CLI flag) that wires detections from a `camera_detections.json` into the Lanelet2 OSM output. `kind=traffic_light` observations produce a `type=regulatory_element, subtype=traffic_light` relation with a `refers` node at the detection world position; `kind=stop_line` observations with a `polyline_m` produce a `type=line_thin, subtype=solid` way. When `camera_detections` is `None` (the default), output is byte-identical to v0.6.0 δ. Existing `validate-lanelet2-tags` passes on the enriched output.
- **3D2: Camera-only lane detection** — `roadgraph_builder/io/camera/lane_detection.py` adds pure-NumPy HSV conversion (`_rgb_to_hsv`), 4-connected component labeling (`_fast_connected_components`), and the main detector `detect_lanes_from_image_rgb` which returns `LinePixel` objects for white and yellow markings without any cv2/scipy dependency. `project_camera_lanes_to_graph_edges` back-projects pixel centroids through a pinhole camera model (`CameraCalibration` + `pixel_to_ground`) into world frame and snaps them to the nearest graph edge within a distance gate, returning `LaneMarkingCandidate` results. CLI: `detect-lane-markings-camera --image ... --calibration-json ... --graph-json ... --pose-json ...`; result is a JSON list of candidates. Omitting the command leaves all other outputs byte-identical.
- **3D3: LiDAR ground-plane RANSAC + true-3D fuse** — `fit_ground_plane_ransac` in `roadgraph_builder/hd/lidar_fusion.py` fits a dominant plane from an (N,3) point cloud using RANSAC (seeded, NumPy only, 200-iter default). Returns normalised plane normal (always z ≥ 0) and offset. `fuse_lane_boundaries_3d` applies the filter before the existing binned-median 2D fusion: only points within `height_band_m` (default 0–0.3 m) above the ground plane pass through, discarding vegetation and overhead structures. `metadata.lidar` gains `ground_plane_normal`, `ground_plane_d`, `ground_plane_height_band_m`, `ground_plane_filtered_out`, `ground_plane_kept`. CLI: `fuse-lidar --ground-plane` gate; omitting it is byte-identical to v0.6.0. `io/lidar/las.py` gains `load_points_xyz_from_las` (N,3 XYZ); `io/lidar/points.py` gains `load_points_xyz_csv` (N,3 or N,4 XYZ[I]).
- **3D1: 3D / elevation throughout** — `build --3d` reads optional `z` column from trajectory CSV and propagates elevation data through the graph. `edge.attributes.polyline_z` (per-vertex z list), `edge.attributes.slope_deg` (signed, positive = uphill in forward direction), and `node.attributes.elevation_m` are added in 3D mode. `enrich_sd_to_hd` mirrors slope_deg and elevation_m into `hd` blocks. `export-lanelet2` emits `<tag k="ele" .../>` on graph nodes when elevation data is present. `route --uphill-penalty` / `--downhill-bonus` multiply edge cost based on slope direction; omitting these flags leaves routing byte-identical to v0.6.0. `road_graph.schema.json` gains optional `point2or3` (x/y/z polyline vertex), `slope_deg`, `polyline_z`, and `elevation_m` fields — all optional so existing 2D graphs validate unchanged.
- **P3: Dataset-level batch CLI (`process-dataset`)** — `roadgraph_builder/cli/dataset.py` adds `process_dataset()` which iterates CSV files in a directory, calls `export_map_bundle` on each, and aggregates results into `dataset_manifest.json`. Per-file errors are isolated by default (`--continue-on-error`); the manifest records `status=failed` + error message for any failed file. `--parallel N` distributes work across N worker processes via `ProcessPoolExecutor`. CLI: `roadgraph_builder process-dataset input_dir/ output_dir/ --origin-json ... --pattern "*.csv"`.
- **P2: Incremental / streaming build (`update-graph` CLI)** — `roadgraph_builder/pipeline/incremental.py` adds `update_graph_from_trajectory` which merges a new trajectory into an existing graph without a full rebuild. New polylines that fall entirely within `absorb_tolerance_m` of an existing edge bump `trace_observation_count` rather than creating a new edge; unabsorbed polylines go through a restricted X/T split + endpoint union-find restricted to nearby edges. CLI: `roadgraph_builder update-graph existing.json new.csv --output merged.json`.

### Changed

- **V3: Memory profile + optimization** — `scripts/profile_memory.py` uses `tracemalloc` to snapshot allocations at four pipeline stages (imports / trajectory load / build / export-bundle) and writes `docs/memory_profile_v0.7.md` with top-20 allocator table and peak RSS per stage. Hotspot fix: `export_lanelet2` / `export_lanelet2_per_lane` replaced the `minidom.parseString → toprettyxml` round-trip with a direct `_et_to_pretty_bytes` recursive chunk-writer that produces byte-identical output while eliminating ~900 KB of DOM object allocation. Measured peak RSS on Paris trackpoints CSV: **61 028 KB → 54 944 KB (−10.0 %)**.

- **P1: X/T-junction split O(N²) → O(N log N)** — new `roadgraph_builder/pipeline/crossing_splitters.py` module replaces the brute-force pair scan in `split_polylines_at_crossings` / `split_polylines_at_t_junctions` with a uniform grid hash. X-crossings index segments per cell; T-junctions use a polyline-bbox grid with inverted endpoint→polyline lookup. Result is numerically identical to the O(N²) path on all inputs including Paris real data. `scripts/run_benchmarks.py` benchmark `polylines_to_graph_10k_synth` restored to a 50×50 grid (~25 000 points); target ≤ 30 s on the fast path.

## [0.6.0] — 2026-04-20

### Added

- **`infer-lane-count` CLI + per-lane Lanelet2 export (`export-lanelet2 --per-lane`)** — `roadgraph_builder/hd/lane_inference.py` infers per-edge lane count and per-lane centerlines from `lane_markings.json` (1-D agglomerative clustering of paint-marker lateral offsets) with fallback to `trace_stats.perpendicular_offsets` mode counting; results written into `attributes.hd.lane_count` / `attributes.hd.lanes[]`. `export_lanelet2_per_lane` expands each edge with `hd.lanes` data into one lanelet per lane (with `roadgraph:lane_index` tag) and emits `lane_change` regulatory_element relations for adjacent pairs; edges without lane data fall back to the standard 1-lanelet/edge output. `road_graph.schema.json` gains optional `lane_count` (int, 1–6) and `lanes[]` (array with `lane_index` / `offset_m` / `centerline_m` / `confidence`) fields in the `hd_block` definition.
- **Lanelet2 fidelity upgrade (`export-lanelet2 --speed-limit-tagging` / `--lane-markings-json` + `validate-lanelet2-tags` CLI)** — `export-lanelet2` gains `--speed-limit-tagging regulatory-element` (emits a separate `type=regulatory_element, subtype=speed_limit` relation instead of an inline tag, matching the Lanelet2 spec) and `--lane-markings-json` (derives `subtype=solid|dashed` on boundary ways from paint intensity heuristic). New `validate-lanelet2-tags` CLI parses an OSM file and reports missing required tags (`subtype`, `location`) on lanelet relations as errors and missing `speed_limit` as warnings; exits 1 on schema-level violations. Four helper functions added to `io/export/lanelet2.py`: `_speed_limit_tags`, `_lane_marking_subtype`, `_build_speed_limit_regulatory`, `_build_right_of_way_regulatory`. All new flags default to 0.5.0 behavior when omitted.
- **Uncertainty-aware routing (`route --prefer-observed` / `--min-confidence`)** — `shortest_path` gains optional cost hooks: `prefer_observed=True` multiplies observed-edge costs by `observed_bonus` (default 0.5) and unobserved-edge costs by `unobserved_penalty` (default 2.0), favouring edges with `trace_observation_count > 0`; `min_confidence` excludes edges whose `hd_refinement.confidence` is below the threshold from Dijkstra expansion, exiting with a clear error message when the destination is unreachable. Both hooks default to off so existing callers are byte-identical to 0.5.0. `total_length_m` is now always the true arc length (not the weighted Dijkstra cost), ensuring route distances stay in real meters regardless of cost multipliers.

## [0.5.0] — 2026-04-20

### Added

- **`detect-lane-markings` CLI** — per-edge LiDAR intensity-peak extraction that recovers left/right/center lane marking candidates from a LAS point cloud without ML; writes `lane_markings.json` validated by `lane_markings.schema.json`.
- **`guidance` CLI** — converts a route GeoJSON + sd_nav.json into a turn-by-turn GuidanceStep sequence (depart/arrive/straight/left/right/…) with signed heading-change angles; writes `guidance.json` validated by `guidance.schema.json`.
- **`make bench` + `scripts/run_benchmarks.py`** — deterministic wall-clock benchmarks for graph build, synthetic grid, 100 shortest-path queries, and export-bundle; `--baseline` mode exits 1 on ≥ 3× regression; `docs/benchmarks.md` records v0.5.0 baseline numbers.
- **HD-lite multi-source refinement (`enrich --lane-markings-json` / `--camera-detections-json`)** — `roadgraph_builder/hd/refinement.py` fuses lane-marking candidates, trace_stats, and camera observations into per-edge `hd_refinement` metadata with refined half-width and confidence; `enrich_sd_to_hd` accepts an optional `refinements=` list; `export-bundle` exposes `--lane-markings-json` / `--camera-detections-refine-json` flags.

## [0.4.0] — 2026-04-19

### Changed

- **CI activates the optional-dependency regression paths** — `.github/workflows/ci.yml` now installs `[dev,laz]` + `opencv-python-headless` + `actions/setup-node@v4` before running pytest, so the three previously-skipping regression paths run on every push: `tests/test_las_cross_format.py` (12 parametrised LAS version × PDRF combos via `laspy`), `tests/test_camera_distortion.py::test_undistortion_matches_cv2` (our fixed-point inversion vs `cv2.undistortPointsIter`), and `tests/test_viewer_js_dijkstra.py` (the viewer TR-aware Dijkstra smoke via Node.js 24). Skip-on-missing logic is preserved so a bare `[dev]` local install still passes.

### Added

- **Embedded attribution + license on OSM-derived assets** — `export_map_geojson`, `write_route_geojson` and `convert-osm-restrictions` now accept optional `attribution` / `license_name` / `license_url` parameters that get embedded in the output file's top-level `properties` (geojson) or as top-level siblings of `turn_restrictions` (TR JSON). `turn_restrictions.schema.json` gained three optional fields for the same trio. All six shipped OSM-derived assets (`map_osm.geojson`, `map_paris.geojson`, `route_paris.geojson`, `map_paris_grid.geojson`, `route_paris_grid.geojson`, `paris_grid_turn_restrictions.json`) are rebaked with `"© OpenStreetMap contributors"` + `"ODbL-1.0"` + the opendatacommons URL, so consumers who see only one file still know where it came from. `docs/assets/ATTRIBUTION.md` still ships as the canonical attribution manifest alongside. `tests/test_attribution.py` guards the pass-through on both exporters plus a shipped-asset regression so future re-bakes can't accidentally drop the fields.
- **Turn-restriction-aware client-side routing in the Leaflet viewer** — `docs/map.html`'s JS Dijkstra is now a directed-state router over `(node, incoming_edge, direction)` that honours both `no_*` and `only_*` turn restrictions loaded from `RESTRICTIONS_URLS`. Click-to-route on the `paris_grid` dataset respects the 10 OSM restrictions baked into `docs/assets/paris_grid_turn_restrictions.json`, and the status line reports `… TR honoured` when restrictions are active. `tests/test_viewer_js_dijkstra.py` + `tests/js/test_viewer_dijkstra.mjs` pull the two functions out of `map.html` and smoke-test them against a tiny fixture that forces a 30 m detour from the unrestricted 20 m baseline (verified separately for `no_left_turn` and `only_right_turn`). Skipped gracefully when Node.js isn't on PATH.
- **Brown-Conrady lens distortion (`CameraIntrinsic.distortion` + `undistort_pixel_to_normalized`)** — `CameraIntrinsic` now carries an optional 5-coefficient distortion tuple `(k1, k2, p1, p2, k3)` in OpenCV order. A fixed-point iteration inverts the Brown-Conrady forward model to recover the undistorted normalized camera ray for a distorted pixel. `pixel_to_ground` picks this path automatically whenever distortion is present; the no-distortion case falls back to the original `K^{-1} * [u, v, 1]`. Cross-checked against `cv2.undistortPointsIter` at ≤ 1e-6 on realistic automotive-grade wide-angle distortion. Calibration JSON round-trips the coefficients via the `distortion: {k1, k2, p1, p2, k3}` object so existing calibration files without a `distortion` key continue to load as undistorted.
- **Self-contained camera pipeline demo** — `scripts/generate_camera_demo.py` forward-projects a handful of ground-truth world-frame features (lane marks at ±1.75 m, a stop line, two speed-limit signs) through a 1280×800 wide-angle camera with Brown-Conrady distortion `(-0.27, 0.09, 0.0005, -0.0003, -0.02)` across a four-pose simulated drive. Writes `examples/demo_camera_calibration.json` + `examples/demo_image_detections.json` with each detection carrying its ground truth in `_world_ground_truth_m`. `tests/test_camera_demo_roundtrip.py` runs the shipped demo through `project_image_detections_to_graph_edges` and asserts the max recovery error stays under 10 cm — on the shipped files it's ~1 cm, bounded by the 0.1-px pixel rounding. `docs/camera_pipeline_demo.md` walks through the demo and points at a real-data recipe (Mapillary CC-BY-SA or KITTI).
- **Camera image → graph-edge pipeline (`project-camera` CLI + `roadgraph_builder.io.camera`)** — pinhole projection from image pixels to the world ground plane, followed by nearest-edge snap, producing the same `camera_detections.schema.json` shape that `apply-camera` already consumes. Three new layers: `CameraCalibration` (intrinsic K + rigid `camera_to_vehicle` mount in body FLU, loaded from JSON with `rotation_rpy_rad` or an explicit 3×3 matrix), `pixel_to_ground` (per-pixel ray construction through `K^{-1}` → body frame → world, intersected with a horizontal ground plane at `--ground-z-m`), and `project_image_detections_to_graph_edges` (full image-detections → projections → `snap_trajectory_to_graph` within `--max-edge-distance-m`). Above-horizon rays and detections without a nearby edge are dropped and counted in the returned `CameraProjectionResult`. The CLI takes calibration JSON + per-image pixel detections JSON + graph JSON and writes the edge-keyed observations, so the end-to-end chain `images → detections → export-bundle` now has a real first stage. Example files (`examples/camera_calibration_sample.json`, `examples/image_detections_sample.json`) + 11 new tests (principal-pixel horizontal miss, 45° ground-hit, right-side projection, vehicle yaw rotation, above-horizon drop, example-file roundtrip, edge-snap end-to-end, no-nearby-edge drop, CLI smoke).
- **Cross-format LAS regression tests + real-data verification** — `tests/test_las_cross_format.py` uses `laspy` (the existing `[laz]` extra) to generate a LAS file for every point data record format we claim to support (PDRF 0-10, LAS 1.2 / 1.3 / 1.4) and asserts our pure-Python `read_las_header` / `load_points_xy_from_las` produce byte-identical XY to `laspy.read`. Includes a 70 000-point LAS 1.4 PDRF 6 file that exercises the 64-bit extended point count field at header offset 247. Skipped when `laspy` isn't installed so CI without the extra still passes. Verified out-of-band against 7 real PDAL test LAS files (autzen_trim 3.7 MB / 110 K pts, 4_1 LAS 1.4 PDRF 1, 4_6 LAS 1.4 PDRF 6, mvk-thin LAS 1.2 PDRF 1, interesting / simple / 100-points LAS 1.2 PDRF 3) — all 7 parse and cross-match laspy; `fuse-lidar` on autzen_trim writes per-edge `lane_boundaries` with real 110 K-point coverage.
- **OSM turn restrictions → graph-space `turn_restrictions.json`** — new `build-osm-graph` and `convert-osm-restrictions` CLI subcommands (+ `roadgraph_builder.io.osm.{build_graph_from_overpass_highways,convert_osm_restrictions_to_graph}`). The first rebuilds a topologically honest road graph by treating each drivable `way["highway"~...]` as a polyline and running the existing X/T-split + endpoint union-find pipeline, so every OSM junction becomes a graph node with `metadata.map_origin` preserved. The second snaps OSM `type=restriction` relations onto that graph: via-node to nearest graph node within `--max-snap-m` (default 15 m), then picks incident edges whose tangent at the junction best aligns (`cos ≥ --min-alignment`, default 0.3) with each OSM way's direction away from the via-node. `no_u_turn` / same-way from+to allow `from_edge == to_edge`. Unsupported `restriction` tags and unmappable relations land in `--skipped-json` with explicit reasons. Paris 2.3370–2.3570°E × 48.8570–48.8770°N verification: **10 / 11 real OSM restrictions mapped** (the 11th references a way classified outside the drivable set); the restricted-`route` detour from `n312 → n191` extends from 878 m → 909 m compared to the unrestricted shortest path.
- **OSM fetch scripts** — `scripts/fetch_osm_turn_restrictions.py` and `scripts/fetch_osm_highways.py` pull raw Overpass JSON for a bbox. Both support `--endpoint` / `OVERPASS_ENDPOINT` so users can fall back to mirrors (`overpass.kumi.systems`, `overpass.private.coffee`) when the main instance is saturated. Output stays under `/tmp` by policy — derivatives (graph JSON, turn_restrictions JSON) are what gets committed.
- **Paris turn_restrictions viewer demo** — `docs/assets/map_paris_grid.geojson` (855 nodes / 1081 edges, compact JSON, ~470 KB), `docs/assets/paris_grid_turn_restrictions.json` (10 OSM restrictions) and `docs/assets/route_paris_grid.geojson` (the restriction-aware `n312 → n191` path) are now the default overlay of `docs/map.html`. Restrictions render as red dots at each junction_node with popups showing the restriction type + from/to edges; the legend gets a matching entry. Selecting the older **Paris (OSM public GPS traces)** layer still works — the new dataset is added alongside, not replacing. `docs/assets/ATTRIBUTION.md` documents the provenance and includes the refetch recipe.



- **Junction cluster consolidation** — new `consolidate_clustered_junctions` pass runs at the end of `polylines_to_graph`. It finds pairs of `multi_branch` nodes within `1.75 × merge_endpoint_m` of each other, union-finds them into a single cluster, collapses each cluster to one node at the centroid, and rewrites incident edges. Cleans up the case where one real intersection is split across two or three anchor points because different polylines reached the junction from slightly different directions. Paris: 1 node absorbed (conservative tolerance keeps the effect small).
- **Near-parallel edge merge** — new `merge_near_parallel_edges` pass runs after the exact-duplicate merge. For every pair of edges whose endpoint-to-endpoint distance sum is below `2 * merge_endpoint_m` (both forward and reversed pairings are considered), the corresponding node ids are union-found into a single cluster. Each cluster collapses to one node at the cluster's centroid, edges are rewritten, and the follow-up duplicate merge averages what are now identical endpoint pairs. Paris OSM: edges 247 → 242, nodes 254 → 250, LCC unchanged at 53 %. Catches the "same road walked twice, each pass anchoring to a slightly different junction cluster" case that exact-duplicate folding missed.
- **Duplicate edge merge** — `polylines_to_graph` now folds edges that share the same (start, end) node pair (regardless of direction) into a single edge. Each polyline is resampled at `centerline_bins` arc-length-uniform samples, reversed when walked in the opposite canonical direction, and per-sample averaged. The merged edge stores `attributes.merged_edge_count`, so downstream consumers can see "this centerline is the average of N passes". On the Paris OSM trace: edges 347 → **247** (100 redundant passes absorbed into 71 averaged centerlines). The largest connected component is unchanged (135 / 53 %); previously-phantom `multi_branch` nodes that were only branching via duplicates collapse back to `through_or_corner`, so the node classification distribution is more honest (`multi_branch` 112 → 67).
- **Miter-joined lane offsets** — `centerline_lane_boundaries` replaces the previous central-difference unit-normal offset with a proper miter join: interior vertices sit on the angle bisector of the two adjacent edge normals at the miter length that keeps perpendicular distance to each incident infinite edge-line equal to the configured half-width. Near-180° reversals fall back to a bevel (two separate offset vertices) once the miter would exceed `miter_limit * half_width`. The old code kept the ribbon a roughly constant chord-distance from the centerline, which under-offset on the inside of sharp curves and flared on the outside; the new version behaves correctly on straight, 90°, and hairpin samples. No public API break; `centerline_lane_boundaries(polyline, lane_width_m)` still returns `(left, right)` polylines, optionally with `miter_limit=4.0` for custom join clamping.
- **X-junction splitting in `build`** — `polylines_to_graph` now runs `split_polylines_at_crossings` before the T-junction / union-find passes. Every pair of polylines whose interiors strictly cross is cut at the intersection, so crossings become real junction nodes instead of phantom unrelated edges. Bounding-box pre-filter keeps the pair scan tractable. On the Paris OSM trace the accumulated splitting (X + T + endpoint merge) now yields 347 edges / 254 nodes, a **135-node largest connected component (53 % of the graph)**, and correct labelling of 18 `x_junction` + 8 `crossroads` nodes that used to collapse into `complex_junction`. The viewer now draws a 19-edge 1923 m Dijkstra route across the LCC.
- **T-junction splitting in `build`** — `polylines_to_graph` now calls a new `split_polylines_at_t_junctions` pass before endpoint union-find: whenever one polyline's endpoint lands within `merge_endpoint_m` of another polyline's *interior* (not its own endpoint), the target polyline is split at the projection so both sides share a junction vertex the union-find can fuse. Guarded by `min_interior_m=1.0` so we don't double-split at tip-to-tip cases the old endpoint-merge already handles. Paris OSM result (`--max-step-m 40 --merge-endpoint-m 8`): edges 123 → 221, largest connected component 5 → **84 nodes** (40 % of the graph), `multi_branch` nodes 3 → 72 (12 `t_junction` + 37 `y_junction` + 23 `complex_junction`). The viewer now draws a 3 km 6-edge route along the connected component; before, no path longer than ~1 km existed.
- **Centerline smoothing upgrade** — `centerline_from_points` now walks the time-ordered segment, computes cumulative arc length, and resamples at ``num_bins`` positions using a Gaussian window in arc-length space (raw first/last points are anchored so the endpoint-merge union-find still fuses adjacent segments). Replaces the previous PCA-major-axis + bin-median approach, which projected curved roads onto a straight axis and produced wobbly / self-folding polylines. Measured on the Paris OSM trace (107 segments): mean absolute per-vertex turning angle drops from 0.456 rad → 0.127 rad (**−72%**), and mean RMS perpendicular residual drops from 1.62 m → 0.95 m (**−41%**). See `docs/bundle_tuning.md` for the table and the `polyline_mean_abs_curvature` / `polyline_rms_residual` helpers.
- **Trace fusion (`fuse-traces` CLI + `fuse_traces_into_graph()`)** — hold the graph fixed, overlay multiple trajectories (typically one per day / per drive), and record per-edge observation stats in `attributes.trace_stats`: `trace_observation_count` (how many independent traces hit this edge), `matched_samples`, `first_observed_timestamp` / `last_observed_timestamp`, plus hour-of-day and weekday bin counts (UTC; populated only when timestamps look epoch-like). `coverage_buckets()` groups edges by 0 / 1 / 2+ / 5+ trace observations to surface "backbone vs. observed once" at a glance. Paris 5-trace public-GPS verification (same 242-edge graph, 5 separate pages re-projected to a shared origin): **240 / 242 edges observed; 118 validated by ≥ 2 traces**; the busiest edge appears on 4 traces spanning hours 9 / 11 / 14 / 20.
- **Signalized-junction inference (`infer-signalized-junctions` CLI + `infer_signalized_junctions()`)** — detect stop windows in the trajectory (median speed below `--stop-speed-mps` held for ≥ `--stop-min-duration-s`), snap each stop centroid to the nearest graph node within `--max-distance-m`, and tag nodes that accumulate ≥ `--min-stops` independent stops with `attributes.signalized_candidate = true`, `stop_event_count`, and `stop_event_total_seconds`. Not a ground-truth signal detector — catches signals, stop signs, congestion hot-spots, parking pauses alike — but useful as candidate review signal. `detect_stop_events()` is exported as a lower-level helper. Paris OSM verification: **13 nodes** flagged, top candidate with 8 observed stops.
- **Trip reconstruction (`reconstruct-trips` CLI + `reconstruct_trips()`)** — partition a long GPS trace into discrete trips using three signals: time gaps (`--max-time-gap-s`), spatial gaps (`--max-spatial-gap-m`), and stop windows (`--stop-speed-mps` held for ≥ `--stop-min-duration-s`). Each trip is snapped to the graph (configurable `--snap-max-distance-m`) and returned as `Trip(trip_id, start/end index/timestamp/xy, start/end edge id, edge_sequence, sample/matched counts, total_distance_m, mean_speed_mps)`. `trip_stats_summary` aggregates the batch. Small / short trips are filtered out (`--min-trip-samples`, `--min-trip-distance-m`). Paris OSM public-GPS verification (6634 samples merged from 5 separate traces): **130 trips reconstructed, 91 % samples matched, 36.4 km total distance / 7 h 14 m total duration, longest trip 1.3 km over 29 edges**.
- **Lanelet2 lane-connection relations** — `export-lanelet2` now emits a `type=regulatory_element, subtype=lane_connection` relation per graph junction node that touches ≥ 2 lanelets. Members are the incident lanelet relations with role `from_start` / `from_end` (indicating which endpoint of the underlying edge anchors the junction). Tags include `roadgraph:junction_node_id`, `roadgraph:junction_type`, and `roadgraph:junction_hint` so downstream Lanelet2 tooling can reconstruct SD-level graph connectivity directly from the OSM document instead of re-inferring it from shared boundary points.
- **HMM map matching (`match-trajectory --hmm` + `hmm_match_trajectory`)** — Viterbi-decode the trajectory over per-sample candidate edges within `--max-distance-m`. Emission cost is a Gaussian on the GPS distance (`--gps-sigma-m`); transition cost penalises large differences between the GPS step and the graph shortest-path distance between candidate projections (capped at `--transition-limit-m`). Resolves the "parallel streets alias" failure mode of the per-sample nearest-edge matcher. Same CLI subcommand as before — just pass `--hmm` to switch algorithms. The stats block reports `algorithm: "hmm_viterbi"` vs `"nearest_edge"` so downstream analytics can tell the outputs apart.
- **Road class inference (`infer-road-class` CLI + `infer_road_class()`)** — snap the source trajectory onto the built graph, compute per-edge speeds from consecutive same-edge samples, and classify each edge as `highway` / `arterial` / `residential` by the median observed speed. Writes `attributes.observed_speed_mps_median`, `attributes.observed_speed_samples`, and `attributes.road_class_inferred` on every edge that saw ≥ `--min-samples` observations. Thresholds are configurable (`--highway-mps` / `--arterial-mps`). Paris measurement: 175 of 242 edges classified (174 residential + 1 arterial; 67 lacked enough observations).
- **Map matching (`match-trajectory` CLI + `snap_trajectory_to_graph`)** — nearest-edge projection of a trajectory CSV onto an existing graph. Returns a `SnappedPoint(index, edge_id, projection_xy_m, distance_m, arc_length_m, edge_length_m, t)` per input sample (or `None` when the sample is farther than `--max-distance-m` / `max_distance_m`). `coverage_stats` gives the aggregate summary (matched ratio, edges touched, mean / max distance). CLI writes the per-sample details to `--output PATH.json`; the summary block is always printed to stdout. Paris self-match at 5 m tolerance: 5162 / 6634 samples matched (78 %), 239 edges touched, mean distance 1.6 m.
- **`BuildParams.post_simplify_tolerance_m`** (default 0.3 m) — final Douglas-Peucker pass runs on every edge polyline *after* X / T splits, duplicate / near-parallel merge, and junction consolidation. Drops the over-sampling the fixed-bin resample introduced (32 vertices on a 10 m straight edge → 0.3 m spacing) while keeping curvature. Paris result: total edge vertices 4905 → **1113 (−77 %)**, average vertex count 20.3 → 4.6; 8 m straight edges collapse from 32 to 2 vertices, a 1.4 km curved edge keeps 28 of its 32. Set the parameter to `None` or `0` to disable.
- **`build` / `export-bundle --extra-csv`** — primary trajectory CSV stays positional; `--extra-csv PATH` (repeatable) concatenates additional CSVs that share the same meter origin. Downstream gap-splitter still treats cross-file spatial jumps as new segments, so non-overlapping passes land as separate polylines while overlapping ones get fused by the duplicate / near-parallel merge passes. New `roadgraph_builder.io.trajectory.load_multi_trajectory_csvs()` helper for library use.
- **`sd_nav.json` respects `direction_observed`** — each edge dict now carries the `direction_observed` label and `allowed_maneuvers_reverse` is emitted as `[]` whenever the source edge was only observed `forward_only`. Edges that flip to `bidirectional` keep the full reverse-direction maneuver hints. Missing / unknown labels fall back to the pre-0.3.0 permissive behaviour (both sides populated) so hand-built graphs and legacy fixtures keep validating. `sd_nav.schema.json` documents the new field; `manifest.schema.json` is unchanged.
- **`attributes.direction_observed` on every edge** — `forward_only` when only the digitized start → end direction was observed in the source trajectory, `bidirectional` when `merge_duplicate_edges` / `merge_near_parallel_edges` folded in at least one pass that traversed the edge in the opposite direction. Downstream SD / routing consumers get an honest upper bound on one-way likelihood. `docs/map.html` popups show the label alongside the `merged_edge_count`. Paris: 38 / 242 edges are bidirectional.
- **Polyline quality metrics** — `polyline_mean_abs_curvature()` and `polyline_rms_residual()` in `roadgraph_builder.utils.geometry`. Smoothness + data-fit metrics for regression-guarding any future centerline work.
- **`LICENSE` (MIT)** — repository now ships an MIT license file, © 2026 Ryohei Sasaki; `pyproject.toml` declares `license = { file = "LICENSE" }`, author metadata, and the matching PyPI classifier. README "License" section updated from TODO to the actual notice.
- **`CONTRIBUTING.md`** — dev-setup recipe, commit / schema / data-hygiene conventions, end-to-end demo commands.
- **README badges** — CI status, MIT license, Python 3.10 / 3.12 shields.io badges at the top of the README.
- **`make docs` (pdoc)** — new optional `[docs]` extra (`pdoc>=14.0`) and a Make target that renders the public API into `build/docs/`. `build/` added to `.gitignore`.
- **`--version` / `-V` flag** — top-level argparse flag on `roadgraph_builder` prints the installed package version (`roadgraph_builder 0.3.0`) and exits 0.
- **Shell completions** — hand-written bash (`scripts/completions/roadgraph_builder.bash`) and zsh (`scripts/completions/_roadgraph_builder`) scripts cover every subcommand, the top-level `--version` / `--help`, and the common file-path arguments (`--turn-restrictions-json`, `--output`, `--origin-json`, `--lidar-points`, etc.). Install instructions added to README. A smoke test cross-checks the completion scripts against the argparse subparser list so drift gets caught on CI.
- **`docs/ARCHITECTURE.md`** — a single-page map of the codebase with Mermaid diagrams (data flow, package layout, `export-bundle` sequence, schema graph, routing subsystem, CI/release). Linked from README and PLAN so new contributors (and future sessions) can orient in one read.
- **End-to-end CLI regression test** — `tests/test_cli_end_to_end.py` shells the installed `roadgraph_builder` entry point and drives a full pipeline (`build → validate`, `export-bundle` with every optional input, then `validate-*` / `stats` / `route --output`), plus negative cases for missing input files and a `doctor` smoke. Guards argparse, exit codes, file writes, and inter-step JSON compatibility — things the in-process unit tests can miss.
- **Click-to-route in the Leaflet viewer** — `docs/map.html` now loads the map GeoJSON into a JS-side adjacency and runs a binary-heap Dijkstra when you click two graph nodes. The computed route replaces the pre-baked overlay, and a "Clear route" button / status line sits in the top bar. Works on any dataset because the data is self-contained.
- **Centerline adjacency in map GeoJSON** — `build_map_geojson` now emits `start_node_id`, `end_node_id`, and `length_m` on each centerline feature, and pins `kind: "centerline"` after the edge-attribute spread so the GeoJSON layer tag no longer collides with the internal `kind: "lane_centerline"` attribute. Existing consumers that ignored those properties are unaffected; the Leaflet viewer uses them for the client-side routing.
- **`nearest-node` CLI + `roadgraph_builder.routing.nearest_node`** — given a query point in lat/lon (with origin from `--origin-lat/--origin-lon` or `metadata.map_origin`) or in the graph's meter frame (`--xy`), return the closest `Node` id plus the straight-line distance. Returns a `NearestNode(node_id, distance_m, query_xy_m)` dataclass from Python and a JSON summary from the CLI.
- **`route --from-latlon` / `--to-latlon`** — the `route` CLI no longer forces you to know internal node ids. `from_node` / `to_node` positionals are now optional; passing `--from-latlon LAT LON` (or the `--to-*` twin) auto-snaps to the nearest node via `nearest_node`. Output adds `snapped_from` / `snapped_to` blocks with the query lat/lon and the matched node's distance, so callers can confirm the snap.
- **Route overlay in the Leaflet viewer** — `docs/map.html` now loads a dataset-specific `ROUTE_URLS` overlay on top of the primary map. `docs/assets/route_paris.geojson` ships a precomputed Paris shortest path (`n111 → n53`, 3 edges, 1267 m) so the default view shows a real route in yellow with green/red start/end dots. Legend updated to match. ODbL attribution added to `docs/assets/ATTRIBUTION.md`.
- **Route GeoJSON export** — `route --output PATH.geojson` writes a FeatureCollection with a merged route LineString (`kind="route"`), one per-edge LineString (`kind="route_edge"`, `direction`, `step`, `from_node`, `to_node`), and two Point features for the start / end nodes. Polylines walked in `reverse` direction are flipped before concatenation so the merged geometry stays in travel order. WGS84 origin is read from `--origin-lat`/`--origin-lon` or from `metadata.map_origin`; missing origin exits 1. Public helpers: `roadgraph_builder.routing.build_route_geojson` / `write_route_geojson`.
- **Turn-restriction-aware routing** — `shortest_path(..., turn_restrictions=[...])` and `route --turn-restrictions-json PATH` now search over directed states `(node, incoming_edge, direction)` and honour both `no_*` (forbid that transition) and `only_*` (whitelist at the given junction/approach). The restriction file can be a standalone `turn_restrictions.json` or any JSON with a `turn_restrictions` array (so `nav/sd_nav.json` works as-is). `Route.edge_directions` is new; the CLI output adds `edge_directions` and `applied_restrictions`.
- **`stats` CLI + public `graph_stats` / `junction_stats`** — `roadgraph_builder stats PATH.json` prints a `{graph_stats, junctions}` summary without parsing the graph yourself (edge/node count, edge length min/median/max/total, bbox in meters, optional WGS84 bbox, junction-hint and junction-type counts). Reads the WGS84 origin from `metadata.map_origin` if present, or from `--origin-lat`/`--origin-lon`. The bundle writer (`export-bundle` manifest) now shares this helper, so manifest `graph_stats` / `junctions` and the CLI output stay in sync.
- **Paris map asset for the Leaflet viewer** — `docs/assets/map_paris.geojson` (123 edges / 223 nodes, Paris 8th arr. ~2 km × 2 km, ODbL) is now the default dataset in `docs/map.html`, next to the existing Berlin OSM sample and the synthetic toy. Showcases `junction_type` on real multi-branch nodes (2× `y_junction` + 1× `complex_junction`). Raw GPS CSV is **not** committed; only the derived centerlines / boundaries / nodes ship. `docs/assets/ATTRIBUTION.md` records the sources and license.
- **`route` CLI + `roadgraph_builder.routing`** — undirected Dijkstra shortest path across the graph by edge polyline length. Usage: `roadgraph_builder route PATH.json FROM_NODE TO_NODE` prints `{from_node, to_node, total_length_m, edge_sequence, node_sequence}` as JSON. Unknown node ids exit 1 with a helpful message; disjoint components raise `ValueError`. Turn restrictions in `nav/sd_nav.json` are intentionally not applied (quick reachability, not legal routing).
- **LAZ decoding via optional `[laz]` extra** — `pip install 'roadgraph-builder[laz]'` pulls in `laspy[lazrs]`. `load_points_xy_from_las()` (and `fuse-lidar` / `export-bundle --lidar-points`) now route `.laz` through `laspy.read` when the extra is installed, otherwise raise a clear `ImportError` pointing at the install command. Uncompressed `.las` still works without the extra.

### Changed

- **CI runs `roadgraph_builder doctor`** — every CI run now exercises the doctor self-check (schema load + LAS header read) in addition to the existing validate / export-bundle steps.

## [0.3.0] — 2026-04-17

### Added

- **Distribution** — `scripts/build_release_bundle.sh` + `.github/workflows/release.yml` attach a validated `roadgraph_sample_bundle.tar.gz` (plus sha256) to every `v*` tag; a trimmed `examples/frozen_bundle/` is committed for quick inspection. `make release-bundle` wraps the script.
- **PyPI workflow scaffold** — `.github/workflows/pypi.yml` (workflow_dispatch only, PyPI / TestPyPI) builds sdist + wheel and publishes via `pypa/gh-action-pypi-publish`. Wired for Trusted Publisher OIDC; no repository secrets required. Enabling requires configuring Trusted Publishers on PyPI and a matching GitHub Environment.
- **`junction_hint: "self_loop"`** — nodes whose only incident edge is a legitimate self-loop (round trip / block circuit) are now classified as `self_loop` instead of `through_or_corner`, making large loops discoverable from topology alone.
- **`junction_type` classification** — `annotate_junction_types()` tags every `multi_branch` node with a finer geometry-derived label (`t_junction`, `y_junction`, `crossroads`, `x_junction`, `complex_junction`) based on pairwise incident-edge tangent angles. Runs automatically in `build`; non-multi-branch nodes are untouched.
- **Bundle manifest junctions** — `export-bundle`'s `manifest.json` now carries a `junctions` block with `total_nodes`, a `junction_hint` count, and a `multi_branch_types` breakdown; the same block is mirrored into `graph.metadata.export_bundle.junctions`. `docs/map.html` popups show `junction_hint` / `junction_type` for nodes.
- **Bundle manifest graph_stats** — `manifest.json` adds `graph_stats` with `edge_count`, `node_count`, `edge_length` (min/median/max/total in meters), `bbox_m`, and `bbox_wgs84_deg`; consumers can size / locate the graph without parsing `sim/road_graph.json`. Validated by `manifest.schema.json`.
- **LAS public-header reader** — `read_las_header()` (and new `LASHeader` dataclass) parses version, point count (including the LAS 1.4 extended 64-bit field), point data format / record length, scale, offset, and bbox from the fixed LAS preamble without requiring `laspy` or touching point records. Supports LAS 1.0 – 1.4; LAZ decoding still out of scope. New CLI `inspect-lidar PATH.las` prints the summary as JSON.
- **Sample LAS artefact** — `scripts/make_sample_las.py` and committed `examples/sample_lidar.las` (52 points, ~1.3 KB). `scripts/run_demo_bundle.sh` and CI now run `inspect-lidar` on the sample so LAS parsing stays exercised.
- **LAS point loader** — `load_points_xy_from_las()` returns an `(N, 2)` float64 array of X/Y in meters (scale + offset applied) without depending on `laspy`. `fuse-lidar` now dispatches on file extension: `.las` uses the LAS loader, anything else continues to read text-format CSV. CLI argument renamed `points_csv` → `points_path`.
- **`export-bundle --lidar-points PATH`** — one-shot pipeline: trajectory → HD-lite enrich → LiDAR point fusion (CSV or LAS) → camera detections → turn restrictions → three-way export. `--fuse-max-dist-m` / `--fuse-bins` tune the fusion. Manifest records `lidar_points` (path / point_count / max_dist_m / bins); `metadata.export_bundle.lidar_fuse` mirrors it. `scripts/build_release_bundle.sh` now runs with the sample LAS, so `examples/frozen_bundle/` ships LiDAR-fused boundaries.

### Changed

- **CI Node.js 24 opt-in** — every workflow sets `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` ahead of the GitHub runner switch on 2026-06-02, suppressing the deprecation warning from `actions/checkout@v4` and `actions/setup-python@v5`.
- **`doctor` self-check expanded** — checks now cover the full example tree (`turn_restrictions_sample.json`, `sample_lidar.las`, `frozen_bundle/manifest.json`, `build_release_bundle.sh`), loads every shipped JSON Schema from the package resources, and reads the bundled LAS header. Missing example files remain non-fatal, but schema-load / LAS-header failures return exit 1.

### Fixed

- **Degenerate self-loops** — `build` now drops edges whose endpoints collapse onto the same node via endpoint-merging *and* whose polyline arc length is below `2 × merge-endpoint-m`. Large legitimate loops (round trips, block circuits) are preserved. Noisy public GPS data that used to produce tens of zero-length self-loops now yields a clean graph.
- **Guard rails** — `build` / `visualize` / `export-bundle` fail with a clear message when the trajectory yields **no graph edges** (e.g. too few samples per segment), instead of writing an unusable empty graph.
- **CLI errors** — Missing input JSON/CSV files print `File not found: …` and exit 1; schema validation errors are prefixed with the file path.

### Added (pipeline backlog landed)

- **Navigation restrictions (generator)** — `export-bundle --turn-restrictions-json` plus extraction from camera detections (`kind: turn_restriction`) now populate `sd_nav.turn_restrictions`; new `validate-turn-restrictions` CLI + schema.
- **Navigation + HD** — `nav/sd_nav.json` `allowed_maneuvers` inferred at the digitized **end node** from 2D junction geometry (`topology_geometry_v1`); `metadata.sd_to_hd.navigation_hints` points consumers at `sd_nav` and describes pairing with HD lane boundaries.
- **Navigation restrictions schema** — optional `sd_nav.turn_restrictions` validates directed edge transition restrictions separately from geometry-derived maneuver hints.
- **Bundle tuning** — `docs/bundle_tuning.md` and `scripts/run_tuning_bundle.sh`; `make tune` runs a minimal `export-bundle` + validation for exploring `max-step-m` / `merge-endpoint-m` with `sim/map.geojson`.
- **Planning / handoff** — `docs/PLAN.md` for roadmap, facts vs intent, and Codex continuation checklist (linked from README).
- **SD→HD envelope** — `enrich_sd_to_hd()` + CLI `enrich`: optional `metadata.sd_to_hd`, per-edge/node `attributes.hd` placeholders (empty lane boundaries); `load_graph_json()`; optional document `metadata` on `Graph`.
- **HD-lite boundaries** — `enrich --lane-width-m` + `centerline_lane_boundaries()`: offset left/right polylines from edge centerlines (not LiDAR/survey-grade).
- **Map GeoJSON** — `build_map_geojson()` emits `lane_boundary_left` / `lane_boundary_right` LineStrings; `docs/map.html` styles them; `refresh_docs_assets.py` runs HD-lite enrich (3.5 m) before exporting bundled maps.
- **Map legend** — `docs/map.html` bottom-right Leaflet control explains trajectory / centerline / lane L&R / nodes.
- **LiDAR (minimal)** — `load_points_xy_csv()`, `attach_lidar_points_metadata()`; sample `examples/sample_lidar_points.csv`. LAS/LAZ still `NotImplementedError`.
- **LiDAR fusion** — `fuse_lane_boundaries_from_points()` + CLI `fuse-lidar`: proximity to centerline, left/right via cross product, binned median polylines per edge.
- **OSM / Lanelet2 interchange** — `export_lanelet2()` writes OSM XML 0.6 (nodes, ways, `roadgraph:*` tags); CLI `export-lanelet2` with `--origin-lat`/`--lon` or `metadata.map_origin`.
- **Lanelet relations** — when both lane boundary ways exist, emit `type=lanelet` with `left`/`right` (+ optional `centerline`) members.
- **Camera semantics (JSON)** — `load_camera_detections_json` / `apply_camera_detections_to_graph`, CLI `apply-camera`; `export_lanelet2` adds `speed_limit` and `regulatory_element` from `hd.semantic_rules`.
- **Detections schema** — `camera_detections.schema.json`, `validate_camera_detections_document`, CLI `validate-detections`; GeoJSON `semantic_summary` on centerlines; `refresh_docs_assets.py` runs sample `apply-camera`; map popups show `semantic_summary`.
- **Road graph schema** — `road_graph.schema.json` documents optional `attributes.hd` (`lane_boundaries`, `semantic_rules` with required `kind`); CI runs `validate-detections` on the bundled example.
- **CI** — `validate` on `docs/assets/sample_graph.json` and `docs/assets/osm_graph.json` (Pages-bundled graphs).
- **export-bundle** — `export_map_bundle()` + CLI: `nav/sd_nav.json`, `sim/{road_graph,map,trajectory}`, `lanelet/map.osm` in one directory (SD / sim / Lanelet three-way export).
- **sd_nav schema** — `sd_nav.schema.json`, `validate_sd_nav_document`, CLI `validate-sd-nav`; CI runs `export-bundle` + `validate-sd-nav` on the sample trajectory.
- **Bundle manifest + CI** — `export-bundle` writes `manifest.json` (version, UTC time, origin, inputs); CI also `validate`s `sim/road_graph.json` from the bundle.
- **Manifest schema** — `manifest.schema.json`, `validate_manifest_document`, CLI `validate-manifest`; CI and `run_demo_bundle.sh` validate `manifest.json` after bundle export.
- **Practical UX** — `export-bundle --origin-json` (lat0/lon0 file); `load_wgs84_origin_json`; `scripts/run_demo_bundle.sh`; manifest records `origin_source` / `origin_json` basename.
- **Developer ergonomics** — CLI `doctor`; `Makefile` (`make install|test|demo|doctor`); `sd_nav` edges include `allowed_maneuvers` (default `["straight"]`; schema allows future routing values).
- **Douglas–Peucker** polyline simplification (`BuildParams.simplify_tolerance_m`, CLI `--simplify-tolerance`).
- **Node topology attributes:** `degree` and `junction_hint` (dead-end / through / multi-branch) via `annotate_node_degrees()`.
- **`Node.attributes`** on export (optional in JSON schema).
- **GeoJSON + Leaflet** — `docs/map.html` overlays trajectory / centerlines / nodes on **OpenStreetMap** tiles; `export_map_geojson()` and `utils/geo.py` (meters ↔ WGS84).
- **OSM fetch** — writes `*_origin.json` and `*_wgs84.csv` next to the meters CSV.

### Changed

- **Navigation maneuvers** — T/Y junction hints stay permissive when sparse geometry shows a straight continuation plus only one side branch, avoiding accidental one-sided turn restrictions in `sd_nav`.
- **`visualize` SVG** — map-inspired styling (grid, trajectory polyline, road-width stroke under centerline, scale bar, refreshed `docs/images` for README).

### Documentation

- **Navigation restrictions:** documented that `allowed_maneuvers` is a permissive geometry hint, plus a future `turn_restrictions` extension shape.
- **README:** SD map vs HD map table (how this repo relates to each).

## [0.2.0] — 2026-04-15

### Added

- **`docs/`** static site: interactive pan/zoom viewer for graph JSON + trajectory CSV (GitHub Pages–ready).
- **`scripts/refresh_docs_assets.py`** — rebuild `docs/assets` and README preview SVGs from `examples/`.
- **README** preview images under `docs/images/` (toy + OSM samples).

### Changed

- **`visualize` SVG** — gradient background and soft glow on centerlines.

## [0.1.0] — 2026-04-15

### Added

- Graph-first JSON export (`schema_version`, nodes, edges with centerline polylines).
- CLI: `build`, `visualize` (SVG), `validate` (JSON Schema).
- Trajectory CSV loader and MVP pipeline (gap segmentation, PCA centerline, endpoint merge).
- OSM public GPS sample (`examples/osm_public_trackpoints.csv`) and fetch script.
- Tests and CI (Python 3.10 / 3.12).
- Stubs: LiDAR, camera, Lanelet2 export.

[0.7.1]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.7.1
[0.7.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.7.0
[0.6.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.6.0
[0.5.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.5.0
[0.4.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.4.0
[0.3.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.3.0
[0.2.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.2.0
[0.1.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.1.0
