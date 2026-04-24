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
let scenePayload = { base: null, route: null, reachable: null, restrictions: [] };
let activeStats = {};
let threeModule = null;
let threeState = null;

const legend = L.control({ position: "bottomright" });
legend.onAdd = function () {
  const div = L.DomUtil.create("div", "map-legend");
  div.innerHTML =
    "<strong>Legend</strong>" +
    '<div class="lg"><span class="sw" style="background:#2563eb"></span> GPS trajectory</div>' +
    '<div class="lg"><span class="sw" style="background:#ea580c"></span> Centerline</div>' +
    '<div class="lg"><span class="sw" style="background:#16a34a"></span> Lane boundary (L)</div>' +
    '<div class="lg"><span class="sw" style="background:#9333ea"></span> Lane boundary (R)</div>' +
    '<div class="lg"><span class="sw" style="background:#0f766e"></span> Reachable span</div>' +
    '<div class="lg"><span class="sw" style="background:#facc15"></span> Route (Dijkstra)</div>' +
    '<div class="lg"><span class="sw dot" style="background:#b91c1c;border:2px solid #fff;box-sizing:border-box"></span> Graph node</div>' +
    '<div class="lg"><span class="sw dot" style="background:#0f766e;border:2px solid #fff;box-sizing:border-box"></span> Reachability start</div>' +
    '<div class="lg"><span class="sw dot" style="background:#10b981;border:2px solid #fff;box-sizing:border-box"></span> Route start</div>' +
    '<div class="lg"><span class="sw dot" style="background:#ef4444;border:2px solid #fff;box-sizing:border-box"></span> Route end</div>' +
    '<div class="lg"><span class="sw dot" style="background:#dc2626;border:2px solid #fff;box-sizing:border-box"></span> Turn restriction (OSM)</div>';
  L.DomEvent.disableClickPropagation(div);
  return div;
};
legend.addTo(map);

function styleLine(f) {
  const k = f.properties && f.properties.kind;
  if (k === "trajectory") {
    return { color: "#2563eb", weight: 4, opacity: 0.75 };
  }
  if (k === "centerline" || k === "lane_centerline") {
    return { color: "#ea580c", weight: 5, opacity: 0.9 };
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
      fillColor: "#b91c1c",
      color: "#fff",
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
      return { kind: "node", nodeId, distance: inters[0].distance };
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
      hintEl.textContent = activeView === "3d"
        ? "Hover an edge or node in the 3D view; click a node to set route endpoints."
        : "Switch to 3D to hover or click graph elements.";
    }
    return;
  }
  if (hit.kind === "node") {
    kindEl.textContent = "Node";
    labelEl.textContent = "Node ID";
    idEl.textContent = hit.nodeId || "—";
    lenEl.textContent = "—";
    endEl.textContent = "—";
    if (hintEl) hintEl.textContent = "Click a second node to route between them.";
    return;
  }
  kindEl.textContent = labelForKind(hit.kind) || "Edge";
  labelEl.textContent = "Edge ID";
  idEl.textContent = hit.edgeId || "—";
  lenEl.textContent = Number.isFinite(hit.lengthM)
    ? Number(hit.lengthM).toFixed(1) + " m"
    : "—";
  endEl.textContent = (hit.startNode || "?") + " → " + (hit.endNode || "?");
  if (hintEl) {
    hintEl.textContent = hit.kind === "route"
      ? "Current dynamic / prebuilt route; click Clear route to reset."
      : "Edge centerline. Click a node marker (red) to start routing.";
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

    const lineSpecs = [
      { data: scenePayload.base, include: (k) => k === "centerline" || k === "lane_centerline" },
      { data: scenePayload.base, include: (k) => k === "trajectory" },
      {
        data: scenePayload.base,
        include: (k) => k === "lane_boundary_left" || k === "lane_boundary_right",
      },
    ];
    if (overlayChecked("toggle-route")) {
      lineSpecs.push({ data: scenePayload.route, include: (k) => k === "route" });
    }
    if (overlayChecked("toggle-reachability")) {
      lineSpecs.push({ data: scenePayload.reachable, include: (k) => k === "reachable_edge" });
    }

    threeState.pickableLines = [];
    for (const spec of lineSpecs) {
      for (const feature of iterLineFeatures(spec.data, spec.include)) {
        const props = feature.properties || {};
        const kind = props.kind || "";
        const pts = (feature.geometry.coordinates || []).map((coord) => point(coord, kind));
        if (pts.length < 2) continue;
        const geom = new THREE.BufferGeometry().setFromPoints(pts);
        const mat = new THREE.LineBasicMaterial({
          color: colorFor3D(kind),
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
        };
        root.add(line);
        if (kind === "centerline" || kind === "lane_centerline") {
          threeState.pickableLines.push(line);
        }
      }
    }

    const nodePoints = [];
    const nodeIds = [];
    for (const feature of (scenePayload.base.features || [])) {
      if (feature.properties?.kind !== "node" || feature.geometry?.type !== "Point") continue;
      nodePoints.push(point(feature.geometry.coordinates, "node"));
      nodeIds.push(String(feature.properties.node_id || ""));
    }
    threeState.pickableNodePoints = null;
    threeState.nodeIds = nodeIds;
    threeState.nodePositions = nodePoints;
    if (nodePoints.length) {
      const geom = new THREE.BufferGeometry().setFromPoints(nodePoints);
      const mat = new THREE.PointsMaterial({ color: 0xef4444, size: 2.8, sizeAttenuation: true });
      const pts = new THREE.Points(geom, mat);
      root.add(pts);
      threeState.pickableNodePoints = pts;
    }

    const markerSpecs = [];
    if (overlayChecked("toggle-route")) {
      markerSpecs.push(
        {
          data: scenePayload.route,
          include: (k) => k === "route_start",
          color: 0x10b981,
          size: 6.5,
          heightKind: "route",
        },
        {
          data: scenePayload.route,
          include: (k) => k === "route_end",
          color: 0xef4444,
          size: 6.5,
          heightKind: "route",
        }
      );
    }
    if (overlayChecked("toggle-reachability")) {
      markerSpecs.push(
        {
          data: scenePayload.reachable,
          include: (k) => k === "reachability_start",
          color: 0x14b8a6,
          size: 6.0,
          heightKind: "reachable_edge",
        },
        {
          data: scenePayload.reachable,
          include: (k) => k === "reachable_node",
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

    if (overlayChecked("toggle-restrictions") && scenePayload.restrictions.length) {
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
const RESTRICTIONS_URLS = {
  paris_grid: "assets/paris_grid_turn_restrictions.json",
};

// Per-dataset graph cached for JS Dijkstra.
const graphCache = {};
let currentRouteSelection = { from: null, to: null };

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

function summarizeBase(data) {
  const stats = {
    nodes: 0,
    edges: 0,
    lanes: 0,
    trajectory: 0,
    routeLength: NaN,
    reachableEdges: 0,
    restrictions: 0,
  };
  for (const f of data.features || []) {
    const p = f.properties || {};
    if (p.kind === "node") stats.nodes += 1;
    if (p.kind === "centerline" || p.kind === "lane_centerline") stats.edges += 1;
    if (p.kind === "lane_boundary_left" || p.kind === "lane_boundary_right") stats.lanes += 1;
    if (p.kind === "trajectory") stats.trajectory += 1;
  }
  return stats;
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

function bindCommonPopups(f, layer) {
  const p = f.properties || {};
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
  while (heap.length) {
    const [d, u, inEdge, inDir] = popMin();
    const key = stateKey(u, inEdge, inDir);
    if (d > (dist.get(key) ?? Infinity)) continue;
    if (u === toNode && d < bestGoalDist) {
      bestGoalDist = d;
      bestGoalKey = key;
      continue;
    }
    if (d >= bestGoalDist) continue;
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
      }
    }
  }
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
  };
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
  const line = L.polyline(
    coords.map((p) => [p[1], p[0]]),
    { color: "#facc15", weight: 7, opacity: 0.92 }
  );
  line.bindPopup(
    "route " +
      dij.nodes[0] +
      " → " +
      dij.nodes[dij.nodes.length - 1] +
      "<br>" +
      dij.totalLength.toFixed(1) +
      " m<br>" +
      dij.edges.length +
      " edges"
  );
  routeOverlayLayer.addLayer(line);

  const startLL = graph.nodes.get(dij.nodes[0]);
  const endLL = graph.nodes.get(dij.nodes[dij.nodes.length - 1]);
  if (startLL) {
    routeData.features.push({
      type: "Feature",
      properties: { kind: "route_start", node_id: dij.nodes[0] },
      geometry: { type: "Point", coordinates: [startLL.lon, startLL.lat] },
    });
    routeOverlayLayer.addLayer(
      L.circleMarker([startLL.lat, startLL.lon], {
        radius: 8,
        fillColor: "#10b981",
        color: "#fff",
        weight: 3,
        opacity: 1,
        fillOpacity: 1,
      }).bindPopup("start: " + dij.nodes[0])
    );
  }
  if (endLL) {
    routeData.features.push({
      type: "Feature",
      properties: { kind: "route_end", node_id: dij.nodes[dij.nodes.length - 1] },
      geometry: { type: "Point", coordinates: [endLL.lon, endLL.lat] },
    });
    routeOverlayLayer.addLayer(
      L.circleMarker([endLL.lat, endLL.lon], {
        radius: 8,
        fillColor: "#ef4444",
        color: "#fff",
        weight: 3,
        opacity: 1,
        fillOpacity: 1,
      }).bindPopup("end: " + dij.nodes[dij.nodes.length - 1])
    );
  }
  scenePayload.route = routeData;
  updateInspector(document.getElementById("dataset").value, {
    routeLength: dij.totalLength,
  });
  renderRouteSteps(graph, dij);
  syncRouteDeepLink(dij);
  if (activeView === "3d") render3DScene();
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
  syncRouteDeepLink(null);
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

  const gj = L.geoJSON(data, {
    style: styleLine,
    pointToLayer: pointLayer,
    onEachFeature: bindCommonPopups,
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
      drawRestrictionsOverlay(graphCache[which], list);
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
      const rj = L.geoJSON(reachableData, {
        style: styleLine,
        pointToLayer: pointLayer,
        onEachFeature: bindCommonPopups,
      });
      reachabilityOverlayLayer.addLayer(rj);
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
      const rj = L.geoJSON(routeData, {
        style: styleLine,
        pointToLayer: pointLayer,
        onEachFeature: bindCommonPopups,
      });
      routeOverlayLayer.addLayer(rj);
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
