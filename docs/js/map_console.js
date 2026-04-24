// Map console viewer for docs/map.html.
//
// Keeps two views (Leaflet 2D + Three.js 3D) synced on a single dataset
// payload, a click-to-route directed-state JS Dijkstra that honours OSM
// turn_restrictions, overlay toggles, and a dataset inspector. The companion
// tests/js/test_viewer_dijkstra.mjs extracts `buildRestrictionIndex` and
// `dijkstra` from this file, so keep those top-level function names stable.

const map = L.map("map", { zoomControl: true });
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

const baseLayer = L.layerGroup().addTo(map);
const reachabilityOverlayLayer = L.layerGroup().addTo(map);
const routeOverlayLayer = L.layerGroup().addTo(map);
const restrictionsOverlayLayer = L.layerGroup().addTo(map);
const view2dButton = document.getElementById("view-2d");
const view3dButton = document.getElementById("view-3d");
const scene3d = document.getElementById("scene3d");
const scene3dCanvas = document.getElementById("scene3d-canvas");
const scene3dStatus = document.getElementById("scene3d-status");
const THREE_URL = "https://unpkg.com/three@0.160.0/build/three.module.js";

let activeView = "2d";
// SD / HD layer tier visibility. Each mode is a superset of the previous one.
// basic = pure graph (centerlines + nodes + trajectory)
// sd    = + route + turn restrictions
// hd    = + lane boundaries + semantic markers + reachability
// full  = everything (default)
const MAP_MODE_ORDER = ["basic", "sd", "hd", "full"];
const MAP_MODE_KINDS = {
  basic: new Set(["centerline", "lane_centerline", "node", "trajectory"]),
  sd: new Set([
    "centerline",
    "lane_centerline",
    "node",
    "trajectory",
    "route",
    "route_edge",
    "route_start",
    "route_end",
  ]),
  hd: null, // filled below after MAP_MODE_KINDS.sd is declared
};
MAP_MODE_KINDS.hd = new Set([
  ...MAP_MODE_KINDS.sd,
  "lane_boundary_left",
  "lane_boundary_right",
  "traffic_light",
  "stop_line",
  "crosswalk",
  "speed_limit",
  "reachable_edge",
  "reachable_node",
  "reachability_start",
]);
let mapMode = "full";

function isKindVisibleForMode(kind) {
  if (mapMode === "full") return true;
  const set = MAP_MODE_KINDS[mapMode];
  return set ? set.has(String(kind || "")) : true;
}

function showRouteOverlayForMode() {
  return mapMode !== "basic";
}

function showReachabilityForMode() {
  return mapMode === "hd" || mapMode === "full";
}

function showRestrictionsForMode() {
  return mapMode !== "basic";
}

// Rebuild every Leaflet layer from the current scenePayload snapshot so a
// mode change takes effect without re-fetching any GeoJSON. The base graph is
// always drawn with its per-mode filter; route / reachability / restrictions
// layers are gated by the mode tier (route needs SD+, reachability needs HD+,
// restrictions need SD+).
function rebuildLeafletLayers() {
  baseLayer.clearLayers();
  routeOverlayLayer.clearLayers();
  reachabilityOverlayLayer.clearLayers();
  restrictionsOverlayLayer.clearLayers();
  if (scenePayload.base) {
    const gj = L.geoJSON(scenePayload.base, {
      style: styleLine,
      pointToLayer: pointLayer,
      onEachFeature: bindCommonPopups,
      filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
    });
    baseLayer.addLayer(gj);
  }
  if (scenePayload.route && showRouteOverlayForMode()) {
    const rj = L.geoJSON(scenePayload.route, {
      style: styleLine,
      pointToLayer: pointLayer,
      onEachFeature: bindCommonPopups,
      filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
    });
    routeOverlayLayer.addLayer(rj);
  }
  if (scenePayload.reachable && showReachabilityForMode()) {
    const rj = L.geoJSON(scenePayload.reachable, {
      style: styleLine,
      pointToLayer: pointLayer,
      onEachFeature: bindCommonPopups,
      filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
    });
    reachabilityOverlayLayer.addLayer(rj);
  }
  if (showRestrictionsForMode() && scenePayload.restrictions.length) {
    const which = document.getElementById("dataset").value;
    const graph = graphCache[which];
    if (graph) drawRestrictionsOverlay(graph, scenePayload.restrictions);
  }
}

function setMapMode(mode) {
  if (!MAP_MODE_ORDER.includes(mode)) return;
  mapMode = mode;
  const sel = document.getElementById("map-mode");
  if (sel && sel.value !== mode) sel.value = mode;
  rebuildLeafletLayers();
  if (activeView === "3d") render3DScene();
}
let scenePayload = { base: null, route: null, reachable: null, restrictions: [] };
let activeStats = {};
let threeModule = null;
let threeState = null;

// Graph node colouring keyed off pipeline.junction_topology classification.
// junction_type (subtype of multi_branch: t/y/crossroads/x/complex) wins over
// junction_hint; "other" is the fallback for anything unexpected so the viewer
// always paints something. Order here doubles as display order in the legend
// and the inspector breakdown. Defined before the Leaflet legend so the
// legend's onAdd (called synchronously by legend.addTo) can reference them.
const JUNCTION_ORDER = [
  "t_junction",
  "y_junction",
  "crossroads",
  "x_junction",
  "complex_junction",
  "through_or_corner",
  "dead_end",
  "self_loop",
  "cul_de_sac",
  "other",
];
const JUNCTION_COLORS = {
  t_junction: "#f59e0b",
  y_junction: "#eab308",
  crossroads: "#10b981",
  x_junction: "#06b6d4",
  complex_junction: "#8b5cf6",
  through_or_corner: "#64748b",
  dead_end: "#ec4899",
  self_loop: "#f43f5e",
  cul_de_sac: "#d946ef",
  other: "#b91c1c",
};
const JUNCTION_LABELS = {
  t_junction: "T-junction",
  y_junction: "Y-junction",
  crossroads: "Crossroads",
  x_junction: "X-junction",
  complex_junction: "Complex",
  through_or_corner: "Through / corner",
  dead_end: "Dead end",
  self_loop: "Self-loop",
  cul_de_sac: "Cul-de-sac",
  other: "Other",
};

function junctionCategory(props) {
  const raw =
    (props && (props.junction_type || props.junction_hint)) || "other";
  return JUNCTION_COLORS[raw] ? raw : "other";
}

function junctionColor(props) {
  return JUNCTION_COLORS[junctionCategory(props)];
}

// OSM-highway road-class palette for centerlines. Higher-class ways run warmer
// (red → amber → yellow), lower-class cool down to cyan / slate. Link
// variants get a lighter tint of the parent colour. Must be declared before
// the Leaflet legend because legend.onAdd is called synchronously on
// legend.addTo() and references these constants.
const HIGHWAY_COLORS = {
  motorway: "#ef4444",
  motorway_link: "#fca5a5",
  trunk: "#f97316",
  trunk_link: "#fdba74",
  primary: "#f59e0b",
  primary_link: "#fcd34d",
  secondary: "#facc15",
  secondary_link: "#fef08a",
  tertiary: "#84cc16",
  tertiary_link: "#bef264",
  unclassified: "#22c55e",
  residential: "#06b6d4",
  living_street: "#3b82f6",
  service: "#64748b",
  road: "#94a3b8",
  other: "#ea580c",
};
const HIGHWAY_ORDER = [
  "motorway",
  "motorway_link",
  "trunk",
  "trunk_link",
  "primary",
  "primary_link",
  "secondary",
  "secondary_link",
  "tertiary",
  "tertiary_link",
  "unclassified",
  "residential",
  "living_street",
  "service",
  "road",
  "other",
];
const HIGHWAY_LABELS = {
  motorway: "Motorway",
  motorway_link: "Motorway link",
  trunk: "Trunk",
  trunk_link: "Trunk link",
  primary: "Primary",
  primary_link: "Primary link",
  secondary: "Secondary",
  secondary_link: "Secondary link",
  tertiary: "Tertiary",
  tertiary_link: "Tertiary link",
  unclassified: "Unclassified",
  residential: "Residential",
  living_street: "Living street",
  service: "Service",
  road: "Road",
  other: "Other",
};

function highwayCategory(props) {
  const raw = (props && props.highway) || null;
  if (raw && HIGHWAY_COLORS[raw]) return raw;
  return "other";
}

function highwayColor(props) {
  return HIGHWAY_COLORS[highwayCategory(props)];
}

function highwayColorHexInt(props) {
  const hex = highwayColor(props);
  return parseInt(hex.slice(1), 16);
}

const legend = L.control({ position: "bottomright" });
legend.onAdd = function () {
  const div = L.DomUtil.create("div", "map-legend");
  const junctionRows = [
    "t_junction",
    "y_junction",
    "crossroads",
    "x_junction",
    "complex_junction",
    "through_or_corner",
    "dead_end",
  ]
    .map(
      (cat) =>
        '<div class="lg"><span class="sw dot" style="background:' +
        JUNCTION_COLORS[cat] +
        ';border:2px solid #fff;box-sizing:border-box"></span> Node · ' +
        JUNCTION_LABELS[cat] +
        "</div>"
    )
    .join("");
  const highwayRows = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "service",
  ]
    .map(
      (cat) =>
        '<div class="lg"><span class="sw" style="background:' +
        HIGHWAY_COLORS[cat] +
        '"></span> ' +
        HIGHWAY_LABELS[cat] +
        "</div>"
    )
    .join("");
  div.innerHTML =
    "<strong>Legend</strong>" +
    '<div class="lg"><span class="sw" style="background:#2563eb"></span> GPS trajectory</div>' +
    highwayRows +
    '<div class="lg"><span class="sw" style="background:#16a34a"></span> Lane boundary (L)</div>' +
    '<div class="lg"><span class="sw" style="background:#9333ea"></span> Lane boundary (R)</div>' +
    '<div class="lg"><span class="sw" style="background:#0f766e"></span> Reachable span</div>' +
    '<div class="lg"><span class="sw" style="background:#facc15"></span> Route (Dijkstra)</div>' +
    junctionRows +
    '<div class="lg"><span class="sw dot" style="background:#ef4444;border:2px solid #fef9c3;box-sizing:border-box"></span> Traffic light</div>' +
    '<div class="lg"><span class="sw dot" style="background:#fafafa;border:2px solid #0f172a;box-sizing:border-box"></span> Stop line</div>' +
    '<div class="lg"><span class="sw dot" style="background:#3b82f6;border:2px solid #fafafa;box-sizing:border-box"></span> Crosswalk</div>' +
    '<div class="lg"><span class="sw dot" style="background:#fde047;border:2px solid #0f172a;box-sizing:border-box"></span> Speed limit</div>' +
    '<div class="lg"><span class="sw dot" style="background:#0f766e;border:2px solid #fff;box-sizing:border-box"></span> Reachability start</div>' +
    '<div class="lg"><span class="sw dot" style="background:#10b981;border:2px solid #fff;box-sizing:border-box"></span> Route start</div>' +
    '<div class="lg"><span class="sw dot" style="background:#ef4444;border:2px solid #fff;box-sizing:border-box"></span> Route end</div>' +
    '<div class="lg"><span class="sw dot" style="background:#dc2626;border:2px solid #fff;box-sizing:border-box"></span> Turn restriction (OSM)</div>';
  L.DomEvent.disableClickPropagation(div);
  return div;
};
legend.addTo(map);

// Road-class palette keyed off OSM highway=*. Higher-class ways are warmer
// (red → amber → yellow) and lower-class ways cool down to slate; the
// `*_link` variants get a slightly brighter tint so motorway ramps and link
// roads still read against their parent. Defined before styleLine because
// the function uses it for every centerline feature.
function styleLine(f) {
  const k = f.properties && f.properties.kind;
  if (k === "trajectory") {
    return { color: "#2563eb", weight: 4, opacity: 0.75 };
  }
  if (k === "centerline" || k === "lane_centerline") {
    return {
      color: highwayColor(f.properties || {}),
      weight: 5,
      opacity: 0.92,
    };
  }
  if (k === "lane_boundary_left") {
    return { color: "#16a34a", weight: 3, opacity: 0.88, dashArray: "8 6" };
  }
  if (k === "lane_boundary_right") {
    return { color: "#9333ea", weight: 3, opacity: 0.88, dashArray: "4 6" };
  }
  if (k === "route") {
    return { color: "#facc15", weight: 7, opacity: 0.92 };
  }
  if (k === "route_edge") {
    // Per-edge features are hidden (merged route carries geometry).
    return { color: "#facc15", weight: 0, opacity: 0 };
  }
  if (k === "reachable_edge") {
    const complete = f.properties && f.properties.complete;
    return {
      color: "#0f766e",
      weight: complete ? 5 : 4,
      opacity: complete ? 0.58 : 0.68,
      dashArray: complete ? null : "8 7",
    };
  }
  return { color: "#64748b", weight: 2 };
}

function pointLayer(f, latlng) {
  const k = f.properties && f.properties.kind;
  if (k === "reachability_start") {
    return L.circleMarker(latlng, {
      radius: 8,
      fillColor: "#0f766e",
      color: "#fff",
      weight: 3,
      opacity: 1,
      fillOpacity: 1,
    });
  }
  if (k === "reachable_node") {
    return L.circleMarker(latlng, {
      radius: 3,
      fillColor: "#0f766e",
      color: "#fff",
      weight: 1,
      opacity: 0.75,
      fillOpacity: 0.72,
    });
  }
  if (k === "route_start" || k === "route_end") {
    return L.circleMarker(latlng, {
      radius: 8,
      fillColor: k === "route_start" ? "#10b981" : "#ef4444",
      color: "#fff",
      weight: 3,
      opacity: 1,
      fillOpacity: 1,
    });
  }
  if (k === "node") {
    return L.circleMarker(latlng, {
      radius: 6,
      fillColor: junctionColor(f.properties || {}),
      color: "#0f172a",
      weight: 1.5,
      opacity: 1,
      fillOpacity: 0.95,
    });
  }
  if (k === "traffic_light") {
    return L.circleMarker(latlng, {
      radius: 8,
      fillColor: "#ef4444",
      color: "#fef9c3",
      weight: 2.5,
      opacity: 1,
      fillOpacity: 0.95,
    });
  }
  if (k === "stop_line") {
    return L.circleMarker(latlng, {
      radius: 6,
      fillColor: "#fafafa",
      color: "#0f172a",
      weight: 2.5,
      opacity: 1,
      fillOpacity: 0.95,
    });
  }
  if (k === "crosswalk") {
    return L.circleMarker(latlng, {
      radius: 6,
      fillColor: "#3b82f6",
      color: "#fafafa",
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9,
    });
  }
  if (k === "speed_limit") {
    return L.circleMarker(latlng, {
      radius: 7,
      fillColor: "#fde047",
      color: "#0f172a",
      weight: 2,
      opacity: 1,
      fillOpacity: 0.95,
    });
  }
  return L.marker(latlng);
}

async function loadGeo(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(path + " " + res.status);
  return res.json();
}

async function ensureThree() {
  if (!threeModule) {
    scene3dStatus.textContent = "Loading 3D engine...";
    threeModule = await import(THREE_URL);
  }
  return threeModule;
}

function iterLineFeatures(data, include) {
  const out = [];
  for (const f of (data && data.features) || []) {
    const p = f.properties || {};
    const kind = p.kind || "";
    if (!include(kind)) continue;
    if (!f.geometry || f.geometry.type !== "LineString") continue;
    out.push(f);
  }
  return out;
}

function iterPointFeatures(data, include) {
  const out = [];
  for (const f of (data && data.features) || []) {
    const p = f.properties || {};
    const kind = p.kind || "";
    if (!include(kind)) continue;
    if (!f.geometry || f.geometry.type !== "Point") continue;
    out.push(f);
  }
  return out;
}

function geoBounds(payload) {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  function addCoord(c) {
    if (!Array.isArray(c) || c.length < 2) return;
    const lon = Number(c[0]);
    const lat = Number(c[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    minLon = Math.min(minLon, lon);
    minLat = Math.min(minLat, lat);
    maxLon = Math.max(maxLon, lon);
    maxLat = Math.max(maxLat, lat);
  }
  for (const data of [payload.base, payload.route, payload.reachable]) {
    for (const f of (data && data.features) || []) {
      if (!f.geometry) continue;
      if (f.geometry.type === "LineString") {
        for (const c of f.geometry.coordinates || []) addCoord(c);
      } else if (f.geometry.type === "Point") {
        addCoord(f.geometry.coordinates);
      }
    }
  }
  if (!Number.isFinite(minLon)) {
    return { minLon: 0, minLat: 0, maxLon: 1, maxLat: 1 };
  }
  return { minLon, minLat, maxLon, maxLat };
}

function colorFor3D(kind) {
  if (kind === "trajectory") return 0x60a5fa;
  if (kind === "route") return 0xfacc15;
  if (kind === "reachable_edge") return 0x14b8a6;
  if (kind === "lane_boundary_left") return 0x22c55e;
  if (kind === "lane_boundary_right") return 0xa855f7;
  return 0xf97316;
}

function heightFor3D(kind) {
  if (kind === "route") return 5.5;
  if (kind === "trajectory") return 4.0;
  if (kind === "reachable_edge") return 2.5;
  if (kind === "lane_boundary_left" || kind === "lane_boundary_right") return 1.0;
  return 0.0;
}

function initThreeState(THREE) {
  if (threeState) return threeState;
  const renderer = new THREE.WebGLRenderer({
    canvas: scene3dCanvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
  });
  renderer.setClearColor(0x0b1120, 1);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
  const root = new THREE.Group();
  scene.add(root);
  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 0.7);
  key.position.set(0.5, 1, 0.7);
  scene.add(key);

  threeState = {
    THREE,
    renderer,
    scene,
    camera,
    root,
    distance: 270,
    dragging: false,
    pressed: false,
    pressX: 0,
    pressY: 0,
    lastX: 0,
    pressTime: 0,
    raycaster: new THREE.Raycaster(),
    pointer: new THREE.Vector2(-1, -1),
    pointerActive: false,
    pickableLines: [],
    pickableNodePoints: null,
    nodeIds: [],
    nodePositions: [],
    hoverVersion: 0,
    lastHoverKey: null,
  };

  const DRAG_PX = 4;

  function updatePointer(event) {
    const rect = scene3dCanvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    threeState.pointer.x = (px / Math.max(1, rect.width)) * 2 - 1;
    threeState.pointer.y = -(py / Math.max(1, rect.height)) * 2 + 1;
    threeState.pointerActive = true;
  }

  scene3dCanvas.addEventListener("pointerdown", (event) => {
    threeState.pressed = true;
    threeState.dragging = false;
    threeState.pressX = event.clientX;
    threeState.pressY = event.clientY;
    threeState.lastX = event.clientX;
    threeState.pressTime = performance.now();
    scene3dCanvas.setPointerCapture(event.pointerId);
  });
  scene3dCanvas.addEventListener("pointermove", (event) => {
    updatePointer(event);
    if (!threeState.pressed) return;
    const total =
      Math.abs(event.clientX - threeState.pressX) +
      Math.abs(event.clientY - threeState.pressY);
    if (!threeState.dragging && total > DRAG_PX) threeState.dragging = true;
    if (threeState.dragging) {
      const dx = event.clientX - threeState.lastX;
      threeState.root.rotation.y += dx * 0.006;
      threeState.lastX = event.clientX;
    }
  });
  scene3dCanvas.addEventListener("pointerup", (event) => {
    const wasDragging = threeState.dragging;
    threeState.pressed = false;
    threeState.dragging = false;
    if (!wasDragging) {
      updatePointer(event);
      handleScenePick();
    }
  });
  scene3dCanvas.addEventListener("pointerleave", () => {
    threeState.pressed = false;
    threeState.dragging = false;
    threeState.pointerActive = false;
    setHoverCard(null);
  });
  scene3dCanvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      threeState.distance = Math.max(
        120,
        Math.min(620, threeState.distance + event.deltaY * 0.35)
      );
      updateThreeCamera();
    },
    { passive: false }
  );
  window.addEventListener("resize", resizeThree);
  animateThree();
  return threeState;
}

function resizeThree() {
  if (!threeState || activeView !== "3d") return;
  const w = Math.max(1, scene3d.clientWidth);
  const h = Math.max(1, scene3d.clientHeight);
  threeState.renderer.setSize(w, h, false);
  threeState.camera.aspect = w / h;
  threeState.camera.updateProjectionMatrix();
}

function updateThreeCamera() {
  if (!threeState) return;
  const d = threeState.distance;
  threeState.camera.position.set(0, d * 0.64, d);
  threeState.camera.lookAt(0, 0, 0);
}

function animateThree() {
  requestAnimationFrame(animateThree);
  if (!threeState || activeView !== "3d") return;
  if (!threeState.dragging && !threeState.hoverFreeze) {
    threeState.root.rotation.y += 0.0012;
  }
  resizeThree();
  updateThreeCamera();
  runHoverPick();
  threeState.renderer.render(threeState.scene, threeState.camera);
}

function pickSceneHit() {
  if (!threeState || !threeState.pointerActive) return null;
  const s = threeState;
  s.raycaster.setFromCamera(s.pointer, s.camera);
  // Node points first — they sit above edges and want priority.
  if (s.pickableNodePoints) {
    s.raycaster.params.Points = s.raycaster.params.Points || {};
    s.raycaster.params.Points.threshold = 2.6;
    const inters = s.raycaster.intersectObject(s.pickableNodePoints, false);
    if (inters.length) {
      const index = inters[0].index || 0;
      const nodeId = s.nodeIds[index] || null;
      const category = s.nodeCategories ? s.nodeCategories[index] || null : null;
      return {
        kind: "node",
        nodeId,
        category,
        distance: inters[0].distance,
      };
    }
  }
  if (s.pickableLines.length) {
    s.raycaster.params.Line = s.raycaster.params.Line || {};
    s.raycaster.params.Line.threshold = 1.8;
    const inters = s.raycaster.intersectObjects(s.pickableLines, false);
    if (inters.length) {
      const obj = inters[0].object;
      return { kind: "edge", ...obj.userData, distance: inters[0].distance };
    }
  }
  return null;
}

function runHoverPick() {
  const hit = pickSceneHit();
  threeState.hoverFreeze = !!hit;
  const key = hit ? (hit.kind + "|" + (hit.nodeId || hit.edgeId || "")) : "none";
  if (threeState.lastHoverKey === key) return;
  threeState.lastHoverKey = key;
  setHoverCard(hit);
}

function handleScenePick() {
  const hit = pickSceneHit();
  if (!hit) return;
  setHoverCard(hit);
  if (hit.kind === "node" && hit.nodeId) {
    onNodeClick(hit.nodeId);
  }
}

function setHoverCard(hit) {
  const kindEl = document.getElementById("hover-kind");
  const labelEl = document.getElementById("hover-label-id");
  const idEl = document.getElementById("hover-id");
  const lenEl = document.getElementById("hover-length");
  const endEl = document.getElementById("hover-endpoints");
  const hintEl = document.getElementById("hover-hint");
  if (!kindEl) return;
  if (!hit) {
    kindEl.textContent = "—";
    labelEl.textContent = "ID";
    idEl.textContent = "—";
    lenEl.textContent = "—";
    endEl.textContent = "—";
    if (hintEl) {
      hintEl.textContent =
        "Hover an edge or node (2D or 3D) to see its metadata; click a node to route.";
    }
    return;
  }
  if (hit.kind === "node") {
    const categoryLabel = hit.category
      ? JUNCTION_LABELS[hit.category] || hit.category
      : "Node";
    kindEl.textContent = "Node · " + categoryLabel;
    labelEl.textContent = "Node ID";
    idEl.textContent = hit.nodeId || "—";
    lenEl.textContent = "—";
    endEl.textContent = "—";
    if (hintEl) hintEl.textContent = "Click a second node to route between them.";
    return;
  }
  const kindPieces = [labelForKind(hit.kind) || "Edge"];
  if (hit.highway) {
    kindPieces.push(HIGHWAY_LABELS[hit.highway] || hit.highway);
  }
  if (typeof hit.osmLanes === "number") {
    kindPieces.push(hit.osmLanes + " lane" + (hit.osmLanes === 1 ? "" : "s"));
  }
  kindEl.textContent = kindPieces.join(" · ");
  labelEl.textContent = "Edge ID";
  idEl.textContent = hit.edgeId || "—";
  lenEl.textContent = Number.isFinite(hit.lengthM)
    ? Number(hit.lengthM).toFixed(1) + " m"
    : "—";
  endEl.textContent = (hit.startNode || "?") + " → " + (hit.endNode || "?");
  if (hintEl) {
    const extras = [];
    if (hit.osmMaxspeed) extras.push(hit.osmMaxspeed);
    if (hit.osmName) extras.push(hit.osmName);
    if (hit.kind === "route") {
      hintEl.textContent =
        "Current dynamic / prebuilt route; click Clear route to reset.";
    } else if (extras.length) {
      hintEl.textContent = extras.join(" · ");
    } else {
      hintEl.textContent = "Edge centerline. Click a node marker to start routing.";
    }
  }
}

function labelForKind(kind) {
  switch (kind) {
    case "centerline":
      return "Centerline";
    case "lane_centerline":
      return "Lane centerline";
    case "route":
      return "Route";
    case "trajectory":
      return "Trajectory";
    case "reachable_edge":
      return "Reachable edge";
    case "lane_boundary_left":
      return "Lane boundary (L)";
    case "lane_boundary_right":
      return "Lane boundary (R)";
    default:
      return kind || "";
  }
}

async function render3DScene() {
  if (!scenePayload.base) return;
  try {
    const THREE = await ensureThree();
    const state = initThreeState(THREE);
    const root = state.root;
    while (root.children.length) {
      const child = root.children[0];
      root.remove(child);
      if (child.geometry) child.geometry.dispose();
      const materials = Array.isArray(child.material)
        ? child.material
        : child.material
          ? [child.material]
          : [];
      for (const material of materials) {
        if (material && material.dispose) material.dispose();
      }
    }
    const bounds = geoBounds(scenePayload);
    const lat0 = (bounds.minLat + bounds.maxLat) / 2;
    const cosLat = Math.cos((lat0 * Math.PI) / 180);
    const meter = (coord) => ({
      x: Number(coord[0]) * 111320 * cosLat,
      z: Number(coord[1]) * 110540,
    });
    const min = meter([bounds.minLon, bounds.minLat]);
    const max = meter([bounds.maxLon, bounds.maxLat]);
    const cx = (min.x + max.x) / 2;
    const cz = (min.z + max.z) / 2;
    const span = Math.max(Math.abs(max.x - min.x), Math.abs(max.z - min.z), 1);
    const scale = 210 / span;
    const point = (coord, kind) => {
      const p = meter(coord);
      return new THREE.Vector3((p.x - cx) * scale, heightFor3D(kind), -(p.z - cz) * scale);
    };

    // Wrap include predicates with the SD / HD mode filter so the 3D scene
    // mirrors what the 2D view shows.
    const modeInclude = (base) => (k) => base(k) && isKindVisibleForMode(k);
    const lineSpecs = [
      {
        data: scenePayload.base,
        include: modeInclude((k) => k === "centerline" || k === "lane_centerline"),
      },
      {
        data: scenePayload.base,
        include: modeInclude((k) => k === "trajectory"),
      },
      {
        data: scenePayload.base,
        include: modeInclude(
          (k) => k === "lane_boundary_left" || k === "lane_boundary_right"
        ),
      },
    ];
    if (overlayChecked("toggle-route") && showRouteOverlayForMode()) {
      lineSpecs.push({
        data: scenePayload.route,
        include: modeInclude((k) => k === "route"),
      });
    }
    if (overlayChecked("toggle-reachability") && showReachabilityForMode()) {
      lineSpecs.push({
        data: scenePayload.reachable,
        include: modeInclude((k) => k === "reachable_edge"),
      });
    }

    threeState.pickableLines = [];
    for (const spec of lineSpecs) {
      for (const feature of iterLineFeatures(spec.data, spec.include)) {
        const props = feature.properties || {};
        const kind = props.kind || "";
        const pts = (feature.geometry.coordinates || []).map((coord) => point(coord, kind));
        if (pts.length < 2) continue;
        const geom = new THREE.BufferGeometry().setFromPoints(pts);
        const lineColor =
          kind === "centerline" || kind === "lane_centerline"
            ? highwayColorHexInt(props)
            : colorFor3D(kind);
        const mat = new THREE.LineBasicMaterial({
          color: lineColor,
          transparent: true,
          opacity: kind === "reachable_edge" ? 0.68 : 0.95,
        });
        const line = new THREE.Line(geom, mat);
        line.userData = {
          kind,
          edgeId: props.edge_id || null,
          lengthM:
            typeof props.length_m === "number"
              ? props.length_m
              : typeof props.total_length_m === "number"
                ? props.total_length_m
                : null,
          startNode: props.start_node_id || props.from_node || null,
          endNode: props.end_node_id || props.to_node || null,
          direction: props.direction || null,
          highway: props.highway || null,
          osmLanes:
            typeof props.osm_lanes === "number" ? props.osm_lanes : null,
          osmMaxspeed: props.osm_maxspeed || null,
          osmName: props.osm_name || null,
        };
        root.add(line);
        if (kind === "centerline" || kind === "lane_centerline") {
          threeState.pickableLines.push(line);
        }
      }
    }

    const nodePoints = [];
    const nodeIds = [];
    const nodeColors = [];
    const nodeCategories = [];
    for (const feature of (scenePayload.base.features || [])) {
      if (feature.properties?.kind !== "node" || feature.geometry?.type !== "Point") continue;
      nodePoints.push(point(feature.geometry.coordinates, "node"));
      nodeIds.push(String(feature.properties.node_id || ""));
      const category = junctionCategory(feature.properties);
      nodeCategories.push(category);
      const col = new THREE.Color(JUNCTION_COLORS[category]);
      nodeColors.push(col.r, col.g, col.b);
    }
    threeState.pickableNodePoints = null;
    threeState.nodeIds = nodeIds;
    threeState.nodeCategories = nodeCategories;
    threeState.nodePositions = nodePoints;
    if (nodePoints.length) {
      const geom = new THREE.BufferGeometry().setFromPoints(nodePoints);
      geom.setAttribute(
        "color",
        new THREE.Float32BufferAttribute(nodeColors, 3)
      );
      const mat = new THREE.PointsMaterial({
        vertexColors: true,
        size: 3.4,
        sizeAttenuation: true,
      });
      const pts = new THREE.Points(geom, mat);
      root.add(pts);
      threeState.pickableNodePoints = pts;
    }

    const markerSpecs = [];
    if (overlayChecked("toggle-route") && showRouteOverlayForMode()) {
      markerSpecs.push(
        {
          data: scenePayload.route,
          include: modeInclude((k) => k === "route_start"),
          color: 0x10b981,
          size: 6.5,
          heightKind: "route",
        },
        {
          data: scenePayload.route,
          include: modeInclude((k) => k === "route_end"),
          color: 0xef4444,
          size: 6.5,
          heightKind: "route",
        }
      );
    }
    if (overlayChecked("toggle-reachability") && showReachabilityForMode()) {
      markerSpecs.push(
        {
          data: scenePayload.reachable,
          include: modeInclude((k) => k === "reachability_start"),
          color: 0x14b8a6,
          size: 6.0,
          heightKind: "reachable_edge",
        },
        {
          data: scenePayload.reachable,
          include: modeInclude((k) => k === "reachable_node"),
          color: 0x5eead4,
          size: 3.2,
          heightKind: "reachable_edge",
        }
      );
    }
    for (const spec of markerSpecs) {
      const pts = iterPointFeatures(spec.data, spec.include).map((feature) =>
        point(feature.geometry.coordinates, spec.heightKind)
      );
      if (!pts.length) continue;
      const geom = new THREE.BufferGeometry().setFromPoints(pts);
      const mat = new THREE.PointsMaterial({
        color: spec.color,
        size: spec.size,
        sizeAttenuation: true,
      });
      root.add(new THREE.Points(geom, mat));
    }

    if (
      overlayChecked("toggle-restrictions") &&
      showRestrictionsForMode() &&
      scenePayload.restrictions.length
    ) {
      const graph = graphCache[document.getElementById("dataset").value];
      const pts = [];
      for (const r of scenePayload.restrictions) {
        const ll = graph && graph.nodes.get(r.junction_node_id);
        if (!ll) continue;
        pts.push(point([ll.lon, ll.lat], "route"));
      }
      if (pts.length) {
        const geom = new THREE.BufferGeometry().setFromPoints(pts);
        const mat = new THREE.PointsMaterial({ color: 0xdc2626, size: 5.5, sizeAttenuation: true });
        root.add(new THREE.Points(geom, mat));
      }
    }

    const grid = new THREE.GridHelper(260, 20, 0x334155, 0x1e293b);
    grid.position.y = -2.0;
    root.add(grid);
    resizeThree();
    updateThreeCamera();
    threeState.lastHoverKey = null;
    scene3dStatus.textContent =
      "3D graph view · " +
      formatCount(activeStats.nodes) +
      " nodes · " +
      formatCount(activeStats.edges) +
      " centerlines";
  } catch (err) {
    scene3dStatus.textContent = "3D view unavailable: " + String(err.message || err);
    console.warn(err);
  }
}

function setView(mode) {
  activeView = mode;
  view2dButton.classList.toggle("active", mode === "2d");
  view3dButton.classList.toggle("active", mode === "3d");
  document.getElementById("map").hidden = mode !== "2d";
  scene3d.hidden = mode !== "3d";
  if (threeState) {
    threeState.pointerActive = false;
    threeState.lastHoverKey = null;
  }
  setHoverCard(null);
  if (mode === "2d") {
    setTimeout(() => map.invalidateSize(), 0);
  } else {
    render3DScene();
  }
}

const DATASET_URLS = {
  paris_grid: "assets/map_paris_grid.geojson",
  berlin_mitte: "assets/map_berlin_mitte.geojson",
  paris: "assets/map_paris.geojson",
  osm: "assets/map_osm.geojson",
  toy: "assets/map_toy.geojson",
};
// Optional pre-baked route overlay. Dynamic click-to-route replaces this
// as soon as the user picks two nodes.
const ROUTE_URLS = {
  paris: "assets/route_paris.geojson",
  paris_grid: "assets/route_paris_grid.geojson",
};
const REACHABLE_URLS = {
  paris_grid: "assets/reachable_paris_grid.geojson",
};
// Optional turn_restrictions JSON overlay (drawn as markers).
// Per-dataset Lanelet2 OSM download (HD-lite, Autoware-compatible tags). The
// toolbar link flips between these as the dataset changes; unsupported
// datasets hide the link entirely.
const LANELET_URLS = {
  paris_grid: "assets/map_paris_grid.lanelet.osm",
  berlin_mitte: "assets/map_berlin_mitte.lanelet.osm",
};
const RESTRICTIONS_URLS = {
  paris_grid: "assets/paris_grid_turn_restrictions.json",
};

// Per-dataset graph cached for JS Dijkstra.
const graphCache = {};
let currentRouteSelection = { from: null, to: null };
let reachSelectionMode = false;

function setReachSelectionMode(enabled) {
  reachSelectionMode = !!enabled;
  const btn = document.getElementById("reach-from-click");
  if (btn) btn.classList.toggle("active", reachSelectionMode);
  if (reachSelectionMode) {
    statusText("Click a graph node to compute reachable spans — press the button again to cancel.");
  }
}

function statusText(msg) {
  document.getElementById("route-status").textContent = msg;
}

function text(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function formatCount(n) {
  return Number.isFinite(n) ? String(n) : "-";
}

function formatMeters(n) {
  if (!Number.isFinite(n)) return "-";
  if (n >= 1000) return (n / 1000).toFixed(2) + " km";
  return n.toFixed(0) + " m";
}

const SEMANTIC_KINDS = new Set([
  "traffic_light",
  "stop_line",
  "crosswalk",
  "speed_limit",
]);

function summarizeBase(data) {
  const stats = {
    nodes: 0,
    edges: 0,
    lanes: 0,
    trajectory: 0,
    routeLength: NaN,
    reachableEdges: 0,
    restrictions: 0,
    semantics: 0,
    junctionCounts: {},
    highwayCounts: {},
    highwayTagged: 0,
  };
  for (const f of data.features || []) {
    const p = f.properties || {};
    if (p.kind === "node") {
      stats.nodes += 1;
      const cat = junctionCategory(p);
      stats.junctionCounts[cat] = (stats.junctionCounts[cat] || 0) + 1;
    }
    if (p.kind === "centerline" || p.kind === "lane_centerline") {
      stats.edges += 1;
      if (p.highway) stats.highwayTagged += 1;
      const hcat = highwayCategory(p);
      stats.highwayCounts[hcat] = (stats.highwayCounts[hcat] || 0) + 1;
    }
    if (p.kind === "lane_boundary_left" || p.kind === "lane_boundary_right") stats.lanes += 1;
    if (p.kind === "trajectory") stats.trajectory += 1;
    if (SEMANTIC_KINDS.has(p.kind)) stats.semantics += 1;
  }
  return stats;
}

function renderClassesBreakdown(counts, taggedEdges, totalEdges) {
  const list = document.getElementById("classes-list");
  const total = document.getElementById("classes-total");
  const card = document.getElementById("classes-card");
  if (!list || !total || !card) return;
  list.innerHTML = "";
  let shown = 0;
  // Hide the card entirely when no edge carries a highway tag (e.g. toy).
  const hasAnyTag = taggedEdges > 0;
  if (!hasAnyTag) {
    total.textContent = "—";
    card.hidden = true;
    return;
  }
  for (const cat of HIGHWAY_ORDER) {
    const n = counts?.[cat] || 0;
    if (!n) continue;
    shown += 1;
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "cdot";
    dot.style.background = HIGHWAY_COLORS[cat];
    const label = document.createElement("span");
    label.className = "clabel";
    label.textContent = HIGHWAY_LABELS[cat] || cat;
    const count = document.createElement("span");
    count.className = "ccount";
    count.textContent = String(n);
    li.appendChild(dot);
    li.appendChild(label);
    li.appendChild(count);
    list.appendChild(li);
  }
  total.textContent =
    shown > 0
      ? `${shown} classes · ${taggedEdges}/${totalEdges} tagged`
      : `${totalEdges} edges`;
  card.hidden = !shown;
}

function renderJunctionsBreakdown(counts, totalNodes) {
  const list = document.getElementById("junctions-list");
  const total = document.getElementById("junctions-total");
  const card = document.getElementById("junctions-card");
  if (!list || !total || !card) return;
  list.innerHTML = "";
  let shown = 0;
  for (const cat of JUNCTION_ORDER) {
    const n = counts?.[cat] || 0;
    if (!n) continue;
    shown += 1;
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "jdot";
    dot.style.background = JUNCTION_COLORS[cat];
    const label = document.createElement("span");
    label.className = "jlabel";
    label.textContent = JUNCTION_LABELS[cat] || cat;
    const count = document.createElement("span");
    count.className = "jcount";
    count.textContent = String(n);
    li.appendChild(dot);
    li.appendChild(label);
    li.appendChild(count);
    list.appendChild(li);
  }
  total.textContent =
    shown > 0 ? `${shown} types · ${totalNodes} nodes` : `${totalNodes} nodes`;
  card.hidden = !shown;
}

function routeLengthFromGeo(data) {
  let routeLength = NaN;
  for (const f of data.features || []) {
    const p = f.properties || {};
    if (p.kind === "route" && typeof p.total_length_m === "number") {
      routeLength = p.total_length_m;
    }
  }
  return routeLength;
}

function reachableCountFromGeo(data) {
  let count = 0;
  for (const f of data.features || []) {
    const p = f.properties || {};
    if (p.kind === "reachable_edge") count += 1;
  }
  return count;
}

function updateInspector(which, stats) {
  activeStats = { ...activeStats, ...stats };
  const label =
    document.querySelector('#dataset option[value="' + which + '"]')?.textContent ||
    "Dataset";
  text("inspector-title", label);
  text("stat-nodes", formatCount(activeStats.nodes));
  text("stat-edges", formatCount(activeStats.edges));
  text("stat-lanes", formatCount(activeStats.lanes));
  text("stat-route", formatMeters(activeStats.routeLength));
  text("stat-reach", formatCount(activeStats.reachableEdges));
  text("stat-tr", formatCount(activeStats.restrictions));
  text("stat-semantics", formatCount(activeStats.semantics));
}

function overlayChecked(id) {
  const el = document.getElementById(id);
  return !el || el.checked;
}

function bindOverlayToggle(id, layer) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("change", () => {
    if (el.checked) layer.addTo(map);
    else layer.remove();
    if (activeView === "3d") render3DScene();
  });
}

bindOverlayToggle("toggle-route", routeOverlayLayer);
bindOverlayToggle("toggle-reachability", reachabilityOverlayLayer);
bindOverlayToggle("toggle-restrictions", restrictionsOverlayLayer);

// Translate a GeoJSON feature's property bag into the shape setHoverCard()
// accepts so 2D Leaflet hover mirrors the 3D raycaster hover.
function hoverHitFromProps(p) {
  if (!p || !p.kind) return null;
  if (p.kind === "node" && p.node_id) {
    return {
      kind: "node",
      nodeId: String(p.node_id),
      category: junctionCategory(p),
    };
  }
  if ((p.kind === "centerline" || p.kind === "lane_centerline") && p.edge_id) {
    return {
      kind: p.kind,
      edgeId: String(p.edge_id),
      lengthM: typeof p.length_m === "number" ? p.length_m : null,
      startNode: p.start_node_id || null,
      endNode: p.end_node_id || null,
      highway: p.highway || null,
      osmLanes:
        typeof p.osm_lanes === "number" ? p.osm_lanes : null,
      osmMaxspeed: p.osm_maxspeed || null,
      osmName: p.osm_name || null,
    };
  }
  if (p.kind === "route") {
    return {
      kind: "route",
      edgeId: null,
      lengthM: typeof p.total_length_m === "number" ? p.total_length_m : null,
      startNode: p.from_node || null,
      endNode: p.to_node || null,
    };
  }
  if (p.kind === "reachable_edge") {
    const cost =
      typeof p.end_cost_m === "number" && typeof p.start_cost_m === "number"
        ? p.end_cost_m - p.start_cost_m
        : null;
    return {
      kind: "reachable_edge",
      edgeId: p.edge_id ? String(p.edge_id) : null,
      lengthM: cost,
      startNode: p.from_node || null,
      endNode: p.to_node || null,
    };
  }
  return null;
}

function bindHoverSync(f, layer) {
  const hit = hoverHitFromProps(f.properties || {});
  if (!hit) return;
  layer.on("mouseover", () => setHoverCard(hit));
  layer.on("mouseout", () => setHoverCard(null));
}

function bindCommonPopups(f, layer) {
  const p = f.properties || {};
  bindHoverSync(f, layer);
  if (p.kind === "node" && p.node_id) {
    let txt = String(p.node_id);
    if (p.degree != null) txt += "<br>degree: " + p.degree;
    if (p.junction_hint) txt += "<br>hint: " + p.junction_hint;
    if (p.junction_type) txt += "<br>type: " + p.junction_type;
    layer.bindPopup(txt);
    layer.on("click", (ev) => {
      L.DomEvent.stopPropagation(ev);
      onNodeClick(p.node_id);
    });
  } else if ((p.kind === "centerline" || p.kind === "lane_centerline") && p.edge_id) {
    let txt = String(p.edge_id);
    if (p.highway) {
      txt +=
        "<br/>" +
        (HIGHWAY_LABELS[p.highway] || p.highway) +
        (typeof p.osm_lanes === "number"
          ? " · " + p.osm_lanes + " lane" + (p.osm_lanes === 1 ? "" : "s")
          : "");
    }
    if (p.osm_maxspeed) {
      txt += "<br/>maxspeed: " + p.osm_maxspeed;
    }
    if (p.osm_name) {
      txt += "<br/>" + p.osm_name;
    }
    if (p.semantic_summary) {
      txt += "<br/>" + String(p.semantic_summary);
    }
    if (p.length_m != null) {
      txt += "<br/>" + Number(p.length_m).toFixed(1) + " m";
    }
    if (p.direction_observed) {
      txt += "<br/>dir: " + String(p.direction_observed);
    }
    if (p.merged_edge_count && p.merged_edge_count > 1) {
      txt += "<br/>merged passes: " + p.merged_edge_count;
    }
    layer.bindPopup(txt);
  } else if (p.kind === "route") {
    let txt = "route " + String(p.from_node) + " → " + String(p.to_node);
    if (p.total_length_m != null) {
      txt += "<br>" + Number(p.total_length_m).toFixed(1) + " m";
    }
    if (p.edge_count != null) {
      txt += "<br>" + p.edge_count + " edges";
    }
    layer.bindPopup(txt);
  } else if (p.kind === "route_start" || p.kind === "route_end") {
    layer.bindPopup(
      (p.kind === "route_start" ? "start: " : "end: ") + String(p.node_id)
    );
  } else if (
    p.kind === "traffic_light" ||
    p.kind === "stop_line" ||
    p.kind === "crosswalk" ||
    p.kind === "speed_limit"
  ) {
    const parts = [
      p.kind === "speed_limit" && p.value_kmh
        ? "speed_limit " + p.value_kmh + " km/h"
        : String(p.kind).replace(/_/g, " "),
    ];
    if (p.edge_id) parts.push("edge " + p.edge_id);
    if (typeof p.confidence === "number") parts.push("conf " + p.confidence.toFixed(2));
    if (p.source) parts.push("src: " + p.source);
    layer.bindPopup(parts.join("<br>"));
  } else if (p.kind === "reachable_edge") {
    let txt = "reachable " + String(p.edge_id) + " (" + String(p.direction) + ")";
    if (p.reachable_fraction != null) {
      txt += "<br>" + (Number(p.reachable_fraction) * 100).toFixed(0) + "% of edge";
    }
    if (p.start_cost_m != null) {
      txt += "<br>from " + Number(p.start_cost_m).toFixed(1) + " m";
    }
    if (p.complete) {
      txt += "<br>complete";
    }
    layer.bindPopup(txt);
  } else if (p.kind === "reachability_start" || p.kind === "reachable_node") {
    let txt =
      (p.kind === "reachability_start" ? "reachability start: " : "reachable node: ") +
      String(p.node_id);
    if (p.cost_m != null) txt += "<br>" + Number(p.cost_m).toFixed(1) + " m";
    layer.bindPopup(txt);
  }
}

// Build adjacency + node lookup from a map GeoJSON FeatureCollection.
function buildGraph(data) {
  const adj = new Map(); // node_id -> Array<{edge_id, length_m, neighbor, coords}>
  const nodes = new Map(); // node_id -> {lat, lon}
  const edges = new Map(); // edge_id -> {coords, start, end}
  for (const f of data.features) {
    const p = f.properties || {};
    if (p.kind === "node" && p.node_id && f.geometry && f.geometry.type === "Point") {
      const c = f.geometry.coordinates;
      nodes.set(p.node_id, { lat: c[1], lon: c[0] });
    } else if (
      (p.kind === "centerline" || p.kind === "lane_centerline") &&
      p.edge_id &&
      p.start_node_id &&
      p.end_node_id &&
      typeof p.length_m === "number" &&
      f.geometry &&
      f.geometry.type === "LineString"
    ) {
      const coords = f.geometry.coordinates;
      edges.set(p.edge_id, { coords, start: p.start_node_id, end: p.end_node_id, length: p.length_m });
      if (!adj.has(p.start_node_id)) adj.set(p.start_node_id, []);
      adj.get(p.start_node_id).push({
        edge_id: p.edge_id,
        length: p.length_m,
        neighbor: p.end_node_id,
        reverse: false,
      });
      if (p.start_node_id !== p.end_node_id) {
        if (!adj.has(p.end_node_id)) adj.set(p.end_node_id, []);
        adj.get(p.end_node_id).push({
          edge_id: p.edge_id,
          length: p.length_m,
          neighbor: p.start_node_id,
          reverse: true,
        });
      }
    }
  }
  return { adj, nodes, edges };
}

// Build lookup tables from a turn_restrictions list. Keys are
// "junction|from_edge|from_direction" strings.
//  - noTransitions: key -> Set of banned "to_edge|to_direction"
//  - onlyTransitions: key -> allowed "to_edge|to_direction" (exactly one)
// If a key has an only_* entry, every transition other than the allowed
// one is banned regardless of no_* data.
function buildRestrictionIndex(list) {
  const noT = new Map();
  const onlyT = new Map();
  if (!Array.isArray(list)) return { noT, onlyT };
  for (const r of list) {
    if (!r || !r.junction_node_id || !r.from_edge_id || !r.to_edge_id) continue;
    const fromKey =
      r.junction_node_id + "|" + r.from_edge_id + "|" + (r.from_direction || "forward");
    const toKey = r.to_edge_id + "|" + (r.to_direction || "forward");
    const k = String(r.restriction || "");
    if (k.startsWith("only_")) {
      onlyT.set(fromKey, toKey);
    } else if (k.startsWith("no_")) {
      if (!noT.has(fromKey)) noT.set(fromKey, new Set());
      noT.get(fromKey).add(toKey);
    }
  }
  return { noT, onlyT };
}

// Directed-state binary-heap Dijkstra. State is
//   (node, incoming_edge_id | null, incoming_direction | null)
// so we can honour turn_restrictions at each junction. Initial state at
// the start node has no incoming edge (unrestricted first step).
function dijkstra(graph, fromNode, toNode, restrictions) {
  if (!graph.adj.has(fromNode)) return null;
  if (!graph.adj.has(toNode) && fromNode !== toNode) return null;
  const rx = restrictions || { noT: new Map(), onlyT: new Map() };

  const stateKey = (node, inEdge, inDir) =>
    node + "|" + (inEdge || "") + "|" + (inDir || "");
  const startKey = stateKey(fromNode, null, null);

  const dist = new Map();
  const prev = new Map();
  dist.set(startKey, 0);
  const heap = [[0, fromNode, null, null]];
  const popMin = () => {
    const top = heap[0];
    const last = heap.pop();
    if (heap.length) {
      heap[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = 2 * i + 2;
        let best = i;
        if (l < heap.length && heap[l][0] < heap[best][0]) best = l;
        if (r < heap.length && heap[r][0] < heap[best][0]) best = r;
        if (best === i) break;
        [heap[i], heap[best]] = [heap[best], heap[i]];
        i = best;
      }
    }
    return top;
  };
  const push = (entry) => {
    heap.push(entry);
    let i = heap.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (heap[parent][0] <= heap[i][0]) break;
      [heap[i], heap[parent]] = [heap[parent], heap[i]];
      i = parent;
    }
  };

  let bestGoalKey = null;
  let bestGoalDist = Infinity;
  let popCount = 0;
  let expandedCount = 0;
  let pushCount = 1; // initial entry on the heap
  while (heap.length) {
    const [d, u, inEdge, inDir] = popMin();
    popCount += 1;
    const key = stateKey(u, inEdge, inDir);
    if (d > (dist.get(key) ?? Infinity)) continue;
    if (u === toNode && d < bestGoalDist) {
      bestGoalDist = d;
      bestGoalKey = key;
      continue;
    }
    if (d >= bestGoalDist) continue;
    expandedCount += 1;
    const outs = graph.adj.get(u) || [];
    for (const out of outs) {
      const outDir = out.reverse ? "reverse" : "forward";
      // Turn-restriction check: only applies when we have an incoming edge.
      if (inEdge) {
        const fromKey = u + "|" + inEdge + "|" + inDir;
        const outKey = out.edge_id + "|" + outDir;
        if (rx.onlyT.has(fromKey) && rx.onlyT.get(fromKey) !== outKey) continue;
        const banned = rx.noT.get(fromKey);
        if (banned && banned.has(outKey)) continue;
      }
      const nd = d + out.length;
      const nkey = stateKey(out.neighbor, out.edge_id, outDir);
      if (nd < (dist.get(nkey) ?? Infinity)) {
        dist.set(nkey, nd);
        prev.set(nkey, { fromKey: key, edge_id: out.edge_id, direction: outDir, node: u });
        push([nd, out.neighbor, out.edge_id, outDir]);
        pushCount += 1;
      }
    }
  }
  const trCount = rx.noT.size + rx.onlyT.size;
  if (bestGoalKey === null) return null;

  const nodesSeq = [toNode];
  const edgesSeq = [];
  const dirSeq = [];
  let cur = bestGoalKey;
  while (prev.has(cur)) {
    const step = prev.get(cur);
    edgesSeq.push(step.edge_id);
    dirSeq.push(step.direction);
    nodesSeq.push(step.node);
    cur = step.fromKey;
  }
  nodesSeq.reverse();
  edgesSeq.reverse();
  dirSeq.reverse();
  return {
    totalLength: bestGoalDist,
    nodes: nodesSeq,
    edges: edgesSeq,
    directions: dirSeq,
    diagnostics: {
      engine: "dijkstra",
      heuristicEnabled: false,
      fallbackReason: null,
      expandedStates: expandedCount,
      queuedStates: pushCount,
      popCount: popCount,
      edgeCount: edgesSeq.length,
      restrictionsIndexed: trCount,
    },
  };
}

// Clip a lon/lat polyline to a fraction of its Euclidean path length. Good
// enough at the Paris-bbox scale (sub-km extents) and identical to how the
// committed `reachable_paris_grid.geojson` clips partial edges.
function clipLineToFraction(coords, fraction) {
  if (!Array.isArray(coords) || coords.length === 0) return [];
  if (fraction <= 0) return [coords[0].slice()];
  if (fraction >= 1) return coords.map((c) => c.slice());
  const cum = [0];
  for (let i = 1; i < coords.length; i++) {
    const dx = coords[i][0] - coords[i - 1][0];
    const dy = coords[i][1] - coords[i - 1][1];
    cum.push(cum[i - 1] + Math.sqrt(dx * dx + dy * dy));
  }
  const total = cum[cum.length - 1];
  if (total <= 0) return [coords[0].slice()];
  const target = total * fraction;
  const out = [coords[0].slice()];
  for (let i = 1; i < coords.length; i++) {
    if (cum[i] >= target) {
      const prev = cum[i - 1];
      const f = (target - prev) / (cum[i] - prev);
      const x = coords[i - 1][0] + f * (coords[i][0] - coords[i - 1][0]);
      const y = coords[i - 1][1] + f * (coords[i][1] - coords[i - 1][1]);
      out.push([x, y]);
      break;
    }
    out.push(coords[i].slice());
  }
  return out;
}

// Directed-state Dijkstra capped at a metre budget. Shares the turn-
// restriction handling with dijkstra() above. Returns reachable nodes (min
// cost seen) and directed edge spans with a reachable_fraction for edges
// whose far endpoint is beyond the budget.
function reachableWithin(graph, startNode, budgetM, restrictions) {
  if (!graph || !graph.adj || !graph.adj.has(startNode)) return null;
  const budget = Number(budgetM);
  if (!Number.isFinite(budget) || budget <= 0) return null;
  const rx = restrictions || { noT: new Map(), onlyT: new Map() };
  const stateKey = (node, inEdge, inDir) =>
    node + "|" + (inEdge || "") + "|" + (inDir || "");

  const nodeCost = new Map();
  nodeCost.set(startNode, 0);
  const edgeSpans = new Map();

  const dist = new Map();
  dist.set(stateKey(startNode, null, null), 0);
  const heap = [[0, startNode, null, null]];
  const popMin = () => {
    const top = heap[0];
    const last = heap.pop();
    if (heap.length) {
      heap[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = 2 * i + 2;
        let best = i;
        if (l < heap.length && heap[l][0] < heap[best][0]) best = l;
        if (r < heap.length && heap[r][0] < heap[best][0]) best = r;
        if (best === i) break;
        [heap[i], heap[best]] = [heap[best], heap[i]];
        i = best;
      }
    }
    return top;
  };
  const push = (entry) => {
    heap.push(entry);
    let i = heap.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (heap[parent][0] <= heap[i][0]) break;
      [heap[i], heap[parent]] = [heap[parent], heap[i]];
      i = parent;
    }
  };

  let popCount = 0;
  let expandedCount = 0;
  while (heap.length) {
    const [d, u, inEdge, inDir] = popMin();
    popCount += 1;
    const key = stateKey(u, inEdge, inDir);
    if (d > (dist.get(key) ?? Infinity)) continue;
    if (d > budget) continue;
    if (!nodeCost.has(u) || nodeCost.get(u) > d) nodeCost.set(u, d);
    expandedCount += 1;
    const outs = graph.adj.get(u) || [];
    for (const out of outs) {
      const outDir = out.reverse ? "reverse" : "forward";
      if (inEdge) {
        const fromKey = u + "|" + inEdge + "|" + inDir;
        const outKey = out.edge_id + "|" + outDir;
        if (rx.onlyT.has(fromKey) && rx.onlyT.get(fromKey) !== outKey) continue;
        const banned = rx.noT.get(fromKey);
        if (banned && banned.has(outKey)) continue;
      }
      const startCost = d;
      const endCost = d + out.length;
      const reachableEnd = Math.min(endCost, budget);
      const reachableCost = reachableEnd - startCost;
      if (reachableCost <= 0) continue;
      const fraction = out.length > 0 ? reachableCost / out.length : 0;
      const spanKey = out.edge_id + "|" + outDir;
      const existing = edgeSpans.get(spanKey);
      if (!existing || existing.reachable_fraction < fraction) {
        edgeSpans.set(spanKey, {
          edge_id: out.edge_id,
          from_node: u,
          to_node: out.neighbor,
          direction: outDir,
          start_cost_m: startCost,
          end_cost_m: endCost,
          reachable_cost_m: reachableEnd,
          reachable_fraction: Math.max(0, Math.min(1, fraction)),
          complete: endCost <= budget,
        });
      }
      if (endCost <= budget) {
        const nkey = stateKey(out.neighbor, out.edge_id, outDir);
        if (endCost < (dist.get(nkey) ?? Infinity)) {
          dist.set(nkey, endCost);
          push([endCost, out.neighbor, out.edge_id, outDir]);
        }
      }
    }
  }
  return {
    nodeCost,
    edgeSpans,
    diagnostics: {
      engine: "dijkstra",
      heuristicEnabled: false,
      fallbackReason: null,
      expandedStates: expandedCount,
      popCount,
      budget_m: budget,
    },
  };
}

function buildReachableFeatures(graph, result, startNode, budgetM) {
  const features = [];
  const startLL = graph.nodes.get(startNode);
  if (startLL) {
    features.push({
      type: "Feature",
      properties: {
        kind: "reachability_start",
        node_id: startNode,
        cost_m: 0,
        budget_m: Number(budgetM),
      },
      geometry: { type: "Point", coordinates: [startLL.lon, startLL.lat] },
    });
  }
  for (const span of result.edgeSpans.values()) {
    const edge = graph.edges.get(span.edge_id);
    if (!edge) continue;
    let coords = edge.coords.map((c) => c.slice());
    if (span.direction === "reverse") coords.reverse();
    if (!span.complete && span.reachable_fraction < 1) {
      coords = clipLineToFraction(coords, span.reachable_fraction);
    }
    if (coords.length < 2) continue;
    features.push({
      type: "Feature",
      properties: {
        kind: "reachable_edge",
        edge_id: span.edge_id,
        from_node: span.from_node,
        to_node: span.to_node,
        direction: span.direction,
        start_cost_m: span.start_cost_m,
        end_cost_m: span.end_cost_m,
        reachable_cost_m: span.reachable_cost_m,
        reachable_fraction: span.reachable_fraction,
        complete: !!span.complete,
      },
      geometry: { type: "LineString", coordinates: coords },
    });
  }
  for (const [nid, cost] of result.nodeCost) {
    if (nid === startNode) continue;
    const ll = graph.nodes.get(nid);
    if (!ll) continue;
    features.push({
      type: "Feature",
      properties: { kind: "reachable_node", node_id: nid, cost_m: cost },
      geometry: { type: "Point", coordinates: [ll.lon, ll.lat] },
    });
  }
  return { type: "FeatureCollection", features };
}

function drawDynamicReachability(which, startNode, budgetM) {
  const graph = graphCache[which];
  if (!graph) {
    statusText("dataset graph not loaded yet");
    return;
  }
  if (!graph.adj.has(startNode)) {
    statusText("unknown node " + startNode + " — click another");
    return;
  }
  const result = reachableWithin(graph, startNode, budgetM, graph.restrictions);
  if (!result) {
    statusText("reachable failed: bad budget or node");
    return;
  }
  const data = buildReachableFeatures(graph, result, startNode, budgetM);
  reachabilityOverlayLayer.clearLayers();
  scenePayload.reachable = data;
  const spans = data.features.filter((f) => f.properties.kind === "reachable_edge").length;
  const reachedNodes = data.features.filter((f) => f.properties.kind === "reachable_node").length;
  if (showReachabilityForMode()) {
    const gj = L.geoJSON(data, {
      style: styleLine,
      pointToLayer: pointLayer,
      onEachFeature: bindCommonPopups,
      filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
    });
    reachabilityOverlayLayer.addLayer(gj);
  }
  updateInspector(which, { reachableEdges: spans });
  const hintParts = [
    "reach " + startNode + " (" + Number(budgetM) + " m)",
    spans + " spans",
    reachedNodes + " nodes",
  ];
  if (result.diagnostics) {
    hintParts.push(result.diagnostics.expandedStates + " expanded");
  }
  statusText(hintParts.join(" · "));
  if (activeView === "3d") render3DScene();
}

function drawDynamicRoute(graph, dij) {
  routeOverlayLayer.clearLayers();
  const coords = [];
  for (let i = 0; i < dij.edges.length; i++) {
    const e = graph.edges.get(dij.edges[i]);
    const c = e.coords.slice();
    if (dij.directions[i] === "reverse") c.reverse();
    if (!coords.length) coords.push(...c);
    else coords.push(...c.slice(1));
  }
  if (!coords.length) return;
  const routeData = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {
          kind: "route",
          from_node: dij.nodes[0],
          to_node: dij.nodes[dij.nodes.length - 1],
          total_length_m: dij.totalLength,
          edge_count: dij.edges.length,
        },
        geometry: { type: "LineString", coordinates: coords },
      },
    ],
  };
  const startLL = graph.nodes.get(dij.nodes[0]);
  const endLL = graph.nodes.get(dij.nodes[dij.nodes.length - 1]);
  if (startLL) {
    routeData.features.push({
      type: "Feature",
      properties: { kind: "route_start", node_id: dij.nodes[0] },
      geometry: { type: "Point", coordinates: [startLL.lon, startLL.lat] },
    });
  }
  if (endLL) {
    routeData.features.push({
      type: "Feature",
      properties: { kind: "route_end", node_id: dij.nodes[dij.nodes.length - 1] },
      geometry: { type: "Point", coordinates: [endLL.lon, endLL.lat] },
    });
  }
  scenePayload.route = routeData;
  if (showRouteOverlayForMode()) {
    const rj = L.geoJSON(routeData, {
      style: styleLine,
      pointToLayer: pointLayer,
      onEachFeature: bindCommonPopups,
      filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
    });
    routeOverlayLayer.addLayer(rj);
  }
  updateInspector(document.getElementById("dataset").value, {
    routeLength: dij.totalLength,
  });
  renderRouteSteps(graph, dij);
  renderRouteEngine(dij);
  syncRouteDeepLink(dij);
  setDownloadRouteEnabled(true);
  if (activeView === "3d") render3DScene();
}

function renderRouteEngine(dij) {
  const card = document.getElementById("engine-card");
  const badge = document.getElementById("engine-badge");
  const expanded = document.getElementById("engine-expanded");
  const queued = document.getElementById("engine-queued");
  const pops = document.getElementById("engine-pops");
  const trEl = document.getElementById("engine-tr");
  const hint = document.getElementById("engine-hint");
  if (!card) return;
  const diag = dij && dij.diagnostics;
  if (!diag) {
    card.hidden = true;
    return;
  }
  const engine = String(diag.engine || "dijkstra");
  badge.textContent = engine;
  badge.className = "engine-badge " + (engine === "safe_astar" ? "safe_astar" : "dijkstra");
  if (diag.fallbackReason) badge.classList.add("fallback");
  expanded.textContent = Number(diag.expandedStates || 0).toLocaleString();
  queued.textContent = Number(diag.queuedStates || 0).toLocaleString();
  pops.textContent = Number(diag.popCount || 0).toLocaleString();
  trEl.textContent = Number(diag.restrictionsIndexed || 0).toLocaleString();
  if (hint) {
    if (diag.fallbackReason) {
      hint.innerHTML =
        "Fallback: <code>" + String(diag.fallbackReason) + "</code>.";
    } else if (engine === "dijkstra") {
      hint.innerHTML =
        "Same directed-state Dijkstra the CLI <code>route</code> falls back to.";
    } else {
      hint.textContent = "Safe A* over the directed-state graph.";
    }
  }
  card.hidden = false;
}

function clearRouteEngine() {
  const card = document.getElementById("engine-card");
  if (!card) return;
  card.hidden = true;
  const badge = document.getElementById("engine-badge");
  if (badge) {
    badge.textContent = "—";
    badge.className = "engine-badge";
  }
  for (const id of ["engine-expanded", "engine-queued", "engine-pops", "engine-tr"]) {
    const el = document.getElementById(id);
    if (el) el.textContent = "—";
  }
}

function setDownloadRouteEnabled(enabled) {
  const btn = document.getElementById("download-route");
  if (btn) btn.disabled = !enabled;
}

function fitMapToRoute(coords) {
  if (!coords || !coords.length) return;
  try {
    const latlngs = coords.map((c) => [c[1], c[0]]);
    const bounds = L.latLngBounds(latlngs);
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 17 });
    }
  } catch (_err) {
    // best-effort; never break routing because of a fit hiccup.
  }
}

function downloadRouteGeoJSON() {
  const route = scenePayload.route;
  if (!route) return;
  const json = JSON.stringify(route, null, 2);
  const blob = new Blob([json], { type: "application/geo+json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const which = document.getElementById("dataset").value || "route";
  const mainFeature = (route.features || []).find((f) => f.properties?.kind === "route");
  const from = mainFeature?.properties?.from_node || "from";
  const to = mainFeature?.properties?.to_node || "to";
  anchor.href = url;
  anchor.download = `route_${which}_${from}_${to}.geojson`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderRouteSteps(graph, dij) {
  const card = document.getElementById("steps-card");
  const list = document.getElementById("steps-list");
  const count = document.getElementById("steps-count");
  if (!card || !list || !count) return;
  list.innerHTML = "";
  let cum = 0;
  for (let i = 0; i < dij.edges.length; i++) {
    const eid = dij.edges[i];
    const dir = dij.directions[i] || "forward";
    const edge = graph.edges.get(eid);
    const len = edge ? Number(edge.length) || 0 : 0;
    cum += len;
    const li = document.createElement("li");
    const addSpan = (cls, text) => {
      const s = document.createElement("span");
      s.className = cls;
      s.textContent = text;
      li.appendChild(s);
    };
    addSpan("step-id", eid);
    addSpan("step-dir", " · " + dir);
    addSpan("step-len", " · " + len.toFixed(1) + " m");
    addSpan("step-cum", " (" + cum.toFixed(1) + " m)");
    list.appendChild(li);
  }
  count.textContent =
    dij.edges.length + " edges · " + dij.totalLength.toFixed(1) + " m";
  card.hidden = false;
}

function clearRouteSteps() {
  const card = document.getElementById("steps-card");
  const list = document.getElementById("steps-list");
  const count = document.getElementById("steps-count");
  if (!card) return;
  if (list) list.innerHTML = "";
  if (count) count.textContent = "—";
  card.hidden = true;
}

// Mirror the current route endpoints into the URL so the page can be
// copy-pasted and restored elsewhere. Uses history.replaceState so there is
// no new browsing history entry per click.
function syncRouteDeepLink(dij) {
  if (!window.history || !window.history.replaceState) return;
  try {
    const url = new URL(window.location.href);
    if (dij && dij.nodes && dij.nodes.length >= 2) {
      url.searchParams.set("from", dij.nodes[0]);
      url.searchParams.set("to", dij.nodes[dij.nodes.length - 1]);
    } else {
      url.searchParams.delete("from");
      url.searchParams.delete("to");
    }
    window.history.replaceState(null, "", url.toString());
  } catch (_err) {
    // best-effort; deep-link sync must never break routing.
  }
}

function onNodeClick(nodeId) {
  // When reach-from-click mode is active, the next node click computes a live
  // reachability overlay from that node with the currently selected budget,
  // instead of routing.
  if (reachSelectionMode) {
    const which = document.getElementById("dataset").value;
    const budgetSel = document.getElementById("reach-budget");
    const budget = Number(budgetSel ? budgetSel.value : 500) || 500;
    setReachSelectionMode(false);
    drawDynamicReachability(which, nodeId, budget);
    return;
  }
  const sel = currentRouteSelection;
  if (!sel.from) {
    sel.from = nodeId;
    sel.to = null;
    statusText("from = " + nodeId + " — click another node to route");
    return;
  }
  if (sel.from === nodeId) {
    statusText("same node — pick a different destination");
    return;
  }
  sel.to = nodeId;
  const which = document.getElementById("dataset").value;
  const graph = graphCache[which];
  if (!graph) {
    statusText("dataset graph not loaded yet");
    return;
  }
  const dij = dijkstra(graph, sel.from, sel.to, graph.restrictions);
  if (!dij) {
    statusText("no path " + sel.from + " → " + sel.to + " (restrictions or disconnected)");
    return;
  }
  drawDynamicRoute(graph, dij);
  const trCount = graph.restrictions
    ? graph.restrictions.noT.size + graph.restrictions.onlyT.size
    : 0;
  statusText(
    "route " +
      sel.from +
      " → " +
      sel.to +
      ": " +
      dij.totalLength.toFixed(1) +
      " m · " +
      dij.edges.length +
      " edges" +
      (trCount ? " · " + trCount + " TR honoured" : "") +
      " · click another node for a new from"
  );
  // Leave from empty so the next click sets a new "from".
  sel.from = null;
  sel.to = null;
}

function clearRoute() {
  routeOverlayLayer.clearLayers();
  scenePayload.route = null;
  updateInspector(document.getElementById("dataset").value, { routeLength: NaN });
  clearRouteSteps();
  clearRouteEngine();
  syncRouteDeepLink(null);
  setDownloadRouteEnabled(false);
  if (activeView === "3d") render3DScene();
  currentRouteSelection = { from: null, to: null };
  statusText("Click two graph nodes to route between them.");
}

function drawRestrictionsOverlay(graph, restrictions) {
  restrictionsOverlayLayer.clearLayers();
  for (const r of restrictions) {
    const ll = graph.nodes.get(r.junction_node_id);
    if (!ll) continue;
    const marker = L.circleMarker([ll.lat, ll.lon], {
      radius: 7,
      fillColor: "#dc2626",
      color: "#fff",
      weight: 2,
      opacity: 1,
      fillOpacity: 0.95,
    });
    const popup =
      "<b>" +
      String(r.restriction).replace(/_/g, " ") +
      "</b><br>junction " +
      String(r.junction_node_id) +
      "<br>from " +
      String(r.from_edge_id) +
      " (" +
      String(r.from_direction) +
      ")<br>to " +
      String(r.to_edge_id) +
      " (" +
      String(r.to_direction) +
      ")<br>source: " +
      String(r.source || "osm");
    marker.bindPopup(popup);
    restrictionsOverlayLayer.addLayer(marker);
  }
}

async function show(which) {
  baseLayer.clearLayers();
  reachabilityOverlayLayer.clearLayers();
  restrictionsOverlayLayer.clearLayers();
  clearRoute();
  setReachSelectionMode(false);
  if (threeState) {
    threeState.pointerActive = false;
    threeState.lastHoverKey = null;
  }
  setHoverCard(null);
  const url = DATASET_URLS[which] || DATASET_URLS.osm;
  const data = await loadGeo(url);
  graphCache[which] = buildGraph(data);
  scenePayload = { base: data, route: null, reachable: null, restrictions: [] };
  activeStats = summarizeBase(data);
  updateInspector(which, activeStats);
  renderJunctionsBreakdown(activeStats.junctionCounts, activeStats.nodes);
  renderClassesBreakdown(
    activeStats.highwayCounts,
    activeStats.highwayTagged,
    activeStats.edges
  );
  const laneletUrl = LANELET_URLS[which];
  const laneletLink = document.getElementById("lanelet-download");
  if (laneletLink) {
    if (laneletUrl) {
      laneletLink.href = laneletUrl;
      laneletLink.hidden = false;
      laneletLink.textContent =
        "Lanelet2 OSM (" +
        (which === "paris_grid"
          ? "Paris"
          : which === "berlin_mitte"
            ? "Berlin"
            : which) +
        ")";
    } else {
      laneletLink.hidden = true;
    }
  }

  const gj = L.geoJSON(data, {
    style: styleLine,
    pointToLayer: pointLayer,
    onEachFeature: bindCommonPopups,
    filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
  });
  baseLayer.addLayer(gj);

  const restrictionsUrl = RESTRICTIONS_URLS[which];
  if (restrictionsUrl) {
    try {
      const trData = await loadGeo(restrictionsUrl);
      const list = Array.isArray(trData) ? trData : trData.turn_restrictions || [];
      graphCache[which].restrictions = buildRestrictionIndex(list);
      scenePayload.restrictions = list;
      updateInspector(which, { restrictions: list.length });
      if (showRestrictionsForMode()) {
        drawRestrictionsOverlay(graphCache[which], list);
      }
    } catch (err) {
      console.warn("restrictions overlay failed:", err);
    }
  }

  const reachableUrl = REACHABLE_URLS[which];
  if (reachableUrl) {
    try {
      const reachableData = await loadGeo(reachableUrl);
      scenePayload.reachable = reachableData;
      updateInspector(which, { reachableEdges: reachableCountFromGeo(reachableData) });
      if (showReachabilityForMode()) {
        const rj = L.geoJSON(reachableData, {
          style: styleLine,
          pointToLayer: pointLayer,
          onEachFeature: bindCommonPopups,
          filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
        });
        reachabilityOverlayLayer.addLayer(rj);
      }
    } catch (err) {
      console.warn("reachability overlay failed:", err);
    }
  }

  const routeUrl = ROUTE_URLS[which];
  if (routeUrl) {
    try {
      const routeData = await loadGeo(routeUrl);
      scenePayload.route = routeData;
      updateInspector(which, { routeLength: routeLengthFromGeo(routeData) });
      if (showRouteOverlayForMode()) {
        const rj = L.geoJSON(routeData, {
          style: styleLine,
          pointToLayer: pointLayer,
          onEachFeature: bindCommonPopups,
          filter: (feat) => isKindVisibleForMode(feat.properties?.kind),
        });
        routeOverlayLayer.addLayer(rj);
      }
    } catch (err) {
      console.warn("route overlay failed:", err);
    }
  }

  const b = gj.getBounds();
  if (b.isValid()) {
    map.fitBounds(b, { padding: [28, 28], maxZoom: 17 });
  } else {
    map.setView([52.52, 13.41], 12);
  }
  if (activeView === "3d") {
    render3DScene();
  }
}

document.getElementById("dataset").addEventListener("change", (e) => {
  show(e.target.value).catch((err) => alert(String(err)));
});
document.getElementById("clear-route").addEventListener("click", clearRoute);
const downloadRouteBtn = document.getElementById("download-route");
if (downloadRouteBtn) {
  downloadRouteBtn.addEventListener("click", downloadRouteGeoJSON);
}
const reachFromClickBtn = document.getElementById("reach-from-click");
if (reachFromClickBtn) {
  reachFromClickBtn.addEventListener("click", () => {
    setReachSelectionMode(!reachSelectionMode);
  });
}
const mapModeSelect = document.getElementById("map-mode");
if (mapModeSelect) {
  mapModeSelect.addEventListener("change", (e) => setMapMode(e.target.value));
}
view2dButton.addEventListener("click", () => setView("2d"));
view3dButton.addEventListener("click", () => setView("3d"));

fetch("assets/site.json")
  .then((r) => r.json())
  .then((s) => {
    const a = document.getElementById("repo");
    if (s.repository_url) a.href = s.repository_url;
  })
  .catch(() => {});

async function bootstrap() {
  const params = new URLSearchParams(window.location.search);
  const allowed = new Set(Object.keys(DATASET_URLS));
  const requested = params.get("dataset");
  const initialDataset = allowed.has(requested) ? requested : "paris_grid";
  const initialView = params.get("view") === "3d" ? "3d" : "2d";
  const fromParam = params.get("from");
  const toParam = params.get("to");
  const datasetSel = document.getElementById("dataset");
  if (datasetSel.value !== initialDataset) datasetSel.value = initialDataset;
  await show(initialDataset);
  if (initialView === "3d") {
    setView("3d");
    await render3DScene();
  }
  if (fromParam && toParam && fromParam !== toParam) {
    applyDeepLinkRoute(initialDataset, fromParam, toParam);
  }
  document.body.dataset.ready = initialView;
}

function applyDeepLinkRoute(which, fromId, toId) {
  const graph = graphCache[which];
  if (!graph) return;
  if (!graph.adj.has(fromId) || !graph.adj.has(toId)) {
    statusText("deep link skipped: unknown node " + (graph.adj.has(fromId) ? toId : fromId));
    return;
  }
  const dij = dijkstra(graph, fromId, toId, graph.restrictions);
  if (!dij) {
    statusText("deep link skipped: no path " + fromId + " → " + toId);
    return;
  }
  drawDynamicRoute(graph, dij);
  // Deep-link entry: zoom 2D to the route so users land on the full polyline
  // rather than the dataset-wide view. Click-to-route keeps the current zoom
  // because the user is already oriented.
  const routeFeature = scenePayload.route?.features?.find(
    (f) => f.properties?.kind === "route"
  );
  if (routeFeature) fitMapToRoute(routeFeature.geometry.coordinates);
  const trCount = graph.restrictions
    ? graph.restrictions.noT.size + graph.restrictions.onlyT.size
    : 0;
  statusText(
    "deep link " +
      fromId +
      " → " +
      toId +
      ": " +
      dij.totalLength.toFixed(1) +
      " m · " +
      dij.edges.length +
      " edges" +
      (trCount ? " · " + trCount + " TR honoured" : "")
  );
}

bootstrap().catch((err) => {
  document.querySelector(".bar").appendChild(document.createTextNode(" Load error: " + err));
});
