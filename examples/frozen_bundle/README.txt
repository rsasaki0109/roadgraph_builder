roadgraph_builder export-bundle — three targets in one directory:
  manifest.json       — provenance (version, origin, inputs)
  nav/sd_nav.json     — SD-style routing seed (lengths + topology)
  sim/                — full graph + GeoJSON + trajectory
  lanelet/map.osm     — Lanelet2 / JOSM interchange
