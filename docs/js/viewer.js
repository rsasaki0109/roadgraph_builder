/**
 * Road graph viewer: pan/zoom SVG, trajectory + centerlines + nodes.
 * Served from GitHub Pages; paths are relative to this page.
 */
(function () {
  "use strict";

  const W = 960;
  const H = 640; // must match docs/index.html viewBox
  const MARGIN = 0.08;

  const svg = document.getElementById("svg-root");
  const layerGrid = document.getElementById("layer-grid");
  const layerTraj = document.getElementById("layer-trajectory");
  const layerEdges = document.getElementById("layer-edges");
  const layerNodes = document.getElementById("layer-nodes");
  const hud = document.getElementById("hud");
  const selDataset = document.getElementById("dataset");

  let state = {
    bounds: null,
    traj: [],
    graph: null,
    /** viewBox in world-ish pixel space 0..W, 0..H before panzoom */
    vb: { x: 0, y: 0, w: W, h: H },
    pan: { x: 0, y: 0 },
    zoom: 1,
    dragging: false,
    last: { x: 0, y: 0 },
  };

  function parseCSV(text) {
    const lines = text.trim().split(/\r?\n/);
    if (lines.length < 2) return [];
    const out = [];
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(",");
      if (parts.length < 3) continue;
      const x = parseFloat(parts[1]);
      const y = parseFloat(parts[2]);
      if (Number.isFinite(x) && Number.isFinite(y)) out.push({ x, y });
    }
    return decimate(out, 8000);
  }

  function decimate(pts, max) {
    if (pts.length <= max) return pts;
    const step = Math.ceil(pts.length / max);
    const r = [];
    for (let i = 0; i < pts.length; i += step) r.push(pts[i]);
    return r;
  }

  function computeBounds(graph, traj) {
    let xmin = Infinity,
      ymin = Infinity,
      xmax = -Infinity,
      ymax = -Infinity;
    function add(x, y) {
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      xmin = Math.min(xmin, x);
      ymin = Math.min(ymin, y);
      xmax = Math.max(xmax, x);
      ymax = Math.max(ymax, y);
    }
    traj.forEach((p) => add(p.x, p.y));
    (graph.nodes || []).forEach((n) => add(n.position.x, n.position.y));
    (graph.edges || []).forEach((e) => (e.polyline || []).forEach((q) => add(q.x, q.y)));
    if (!Number.isFinite(xmin)) {
      return { xmin: 0, ymin: 0, xmax: 1, ymax: 1 };
    }
    return { xmin, ymin, xmax, ymax };
  }

  function worldToScreen(x, y, b) {
    const dx = b.xmax - b.xmin;
    const dy = b.ymax - b.ymin;
    const mx = dx * MARGIN;
    const my = dy * MARGIN;
    const px = ((x - (b.xmin - mx)) / (dx + 2 * mx)) * W;
    const py = (1 - (y - (b.ymin - my)) / (dy + 2 * my)) * H;
    return [px, py];
  }

  function drawGrid() {
    layerGrid.innerHTML = "";
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("opacity", "0.35");
    for (let i = 0; i <= 10; i++) {
      const x = (W * i) / 10;
      const y = (H * i) / 10;
      const v = document.createElementNS("http://www.w3.org/2000/svg", "line");
      v.setAttribute("x1", x);
      v.setAttribute("y1", 0);
      v.setAttribute("x2", x);
      v.setAttribute("y2", H);
      v.setAttribute("stroke", "#475569");
      v.setAttribute("stroke-width", "0.6");
      g.appendChild(v);
      const h = document.createElementNS("http://www.w3.org/2000/svg", "line");
      h.setAttribute("x1", 0);
      h.setAttribute("y1", y);
      h.setAttribute("x2", W);
      h.setAttribute("y2", y);
      h.setAttribute("stroke", "#475569");
      h.setAttribute("stroke-width", "0.6");
      g.appendChild(h);
    }
    layerGrid.appendChild(g);
  }

  function render() {
    const b = state.bounds;
    if (!b || !state.graph) return;

    layerTraj.innerHTML = "";
    state.traj.forEach((p) => {
      const [cx, cy] = worldToScreen(p.x, p.y, b);
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", cx);
      c.setAttribute("cy", cy);
      c.setAttribute("r", "1.8");
      c.setAttribute("fill", "#94a3b8");
      c.setAttribute("opacity", "0.75");
      layerTraj.appendChild(c);
    });

    layerEdges.innerHTML = "";
    (state.graph.edges || []).forEach((e) => {
      const pl = e.polyline || [];
      if (pl.length < 2) return;
      let d = "";
      for (let i = 0; i < pl.length; i++) {
        const [sx, sy] = worldToScreen(pl[i].x, pl[i].y, b);
        d += (i === 0 ? "M " : " L ") + sx.toFixed(2) + " " + sy.toFixed(2);
      }
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "#60a5fa");
      path.setAttribute("stroke-width", "3");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      path.setAttribute("filter", "url(#softGlow)");
      layerEdges.appendChild(path);
    });

    layerNodes.innerHTML = "";
    (state.graph.nodes || []).forEach((n) => {
      const [cx, cy] = worldToScreen(n.position.x, n.position.y, b);
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", cx);
      c.setAttribute("cy", cy);
      c.setAttribute("r", "6");
      c.setAttribute("fill", "#f87171");
      c.setAttribute("stroke", "#fff");
      c.setAttribute("stroke-width", "1.5");
      layerNodes.appendChild(c);
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", cx + 9);
      t.setAttribute("y", cy - 9);
      t.setAttribute("fill", "#e2e8f0");
      t.setAttribute("font-size", "12");
      t.setAttribute("font-family", "ui-monospace, monospace");
      t.textContent = n.id;
      layerNodes.appendChild(t);
    });

    const dx = b.xmax - b.xmin;
    const dy = b.ymax - b.ymin;
    hud.textContent =
      `Nodes: ${(state.graph.nodes || []).length} · Edges: ${(state.graph.edges || []).length} · Trajectory points: ${state.traj.length} · Span ≈ ${dx.toFixed(1)} × ${dy.toFixed(1)} (input units)`;

    applyViewTransform();
  }

  function applyViewTransform() {
    const g = document.getElementById("panzoom");
    const cx = W / 2;
    const cy = H / 2;
    const z = state.zoom;
    const px = state.pan.x;
    const py = state.pan.y;
    g.setAttribute(
      "transform",
      `translate(${px},${py}) translate(${cx},${cy}) scale(${z}) translate(${-cx},${-cy})`
    );
  }

  function fit() {
    state.zoom = 1;
    state.pan = { x: 0, y: 0 };
    applyViewTransform();
  }

  function screenToSvg(evt) {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }

  svg.addEventListener("mousedown", (e) => {
    state.dragging = true;
    state.last = screenToSvg(e);
  });
  window.addEventListener("mouseup", () => {
    state.dragging = false;
  });
  window.addEventListener("mousemove", (e) => {
    if (!state.dragging) return;
    const p = screenToSvg(e);
    state.pan.x += p.x - state.last.x;
    state.pan.y += p.y - state.last.y;
    state.last = p;
    applyViewTransform();
  });

  svg.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 0.92 : 1.08;
      state.zoom = Math.min(40, Math.max(0.15, state.zoom * factor));
      applyViewTransform();
    },
    { passive: false }
  );

  async function loadDataset(entry) {
    const [gRes, cRes] = await Promise.all([fetch(entry.graph), fetch(entry.csv)]);
    if (!gRes.ok) throw new Error("graph " + gRes.status);
    if (!cRes.ok) throw new Error("csv " + cRes.status);
    const graph = await gRes.json();
    const csvText = await cRes.text();
    const traj = parseCSV(csvText);
    state.graph = graph;
    state.traj = traj;
    state.bounds = computeBounds(graph, traj);
    drawGrid();
    render();
    fit();
  }

  async function init() {
    const cfgRes = await fetch("assets/viewer_config.json");
    const cfg = await cfgRes.json();
    selDataset.innerHTML = "";
    cfg.datasets.forEach((d, i) => {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = d.label;
      selDataset.appendChild(opt);
    });

    selDataset.addEventListener("change", async () => {
      const d = cfg.datasets[Number(selDataset.value)];
      await loadDataset(d);
    });

    document.getElementById("btn-fit").addEventListener("click", fit);
    document.getElementById("btn-reset").addEventListener("click", () => {
      state.zoom = 1;
      state.pan = { x: 0, y: 0 };
      applyViewTransform();
    });

    await loadDataset(cfg.datasets[0]);
  }

  init().catch((err) => {
    hud.textContent = "Failed to load: " + err.message + " (open via http server or GitHub Pages)";
    console.error(err);
  });
})();
