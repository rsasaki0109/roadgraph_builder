/**
 * Route diagnostics comparison panel for the docs landing page.
 */
(function () {
  "use strict";

  const diagnosticsCompare = document.getElementById("route-diagnostics-compare");

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function formatCount(value) {
    if (!Number.isFinite(value)) return "n/a";
    return Math.round(value).toLocaleString("en-US");
  }

  function formatMeters(value) {
    if (!Number.isFinite(value)) return "n/a";
    if (value >= 100) return value.toFixed(0) + " m";
    return value.toFixed(1) + " m";
  }

  function fallbackText(reason) {
    return reason || "none";
  }

  function renderDiagnosticsCard(sample) {
    const d = sample.diagnostics || {};
    const isFallback = Boolean(d.fallback_reason);
    const card = node("div", "diagnostics-engine" + (isFallback ? " fallback" : ""));
    const title = d.search_engine === "astar" ? "Safe A*" : "Dijkstra fallback";
    card.appendChild(node("span", "metric-kicker", title));
    card.appendChild(node("strong", "", formatCount(d.expanded_states) + " expanded states"));
    card.appendChild(node("span", "", sample.label || sample.id || "Route sample"));

    const pills = node("div", "diagnostics-pill-row");
    pills.appendChild(
      node("span", "diagnostics-pill", d.heuristic_enabled ? "heuristic on" : "heuristic off")
    );
    pills.appendChild(
      node(
        "span",
        "diagnostics-pill" + (isFallback ? " warn" : ""),
        "fallback: " + fallbackText(d.fallback_reason)
      )
    );
    pills.appendChild(
      node("span", "diagnostics-pill", formatCount(sample.applied_restrictions || 0) + " restrictions")
    );
    card.appendChild(pills);
    return card;
  }

  function renderDiagnosticsTable(samples) {
    const wrap = node("div", "diagnostics-table-wrap");
    const table = node("table", "diagnostics-table");
    const thead = node("thead");
    const headRow = node("tr");
    ["Sample", "Engine", "Expanded", "Queued", "Edges", "Length", "Fallback"].forEach((label) => {
      headRow.appendChild(node("th", "", label));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = node("tbody");
    samples.forEach((sample) => {
      const d = sample.diagnostics || {};
      const row = node("tr");
      [
        sample.id,
        d.search_engine || "n/a",
        formatCount(d.expanded_states),
        formatCount(d.queued_states),
        formatCount(d.route_edge_count),
        formatMeters(d.total_length_m || sample.total_length_m),
        fallbackText(d.fallback_reason),
      ].forEach((value) => {
        row.appendChild(node("td", "", value));
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function renderDiagnosticsNote(samples) {
    const astar = samples.find((sample) => sample.diagnostics?.search_engine === "astar");
    const fallback = samples.find((sample) => sample.diagnostics?.fallback_reason);
    if (!astar || !fallback) return null;

    const astarExpanded = astar.diagnostics.expanded_states;
    const fallbackExpanded = fallback.diagnostics.expanded_states;
    if (!Number.isFinite(astarExpanded) || !Number.isFinite(fallbackExpanded) || astarExpanded <= 0) {
      return null;
    }

    const ratio = fallbackExpanded / astarExpanded;
    const ratioText = ratio >= 100 ? ratio.toFixed(0) + "x" : ratio.toFixed(1) + "x";
    return node(
      "div",
      "diagnostics-note",
      "The Paris fallback expands " +
        ratioText +
        " more states than the metric A* sample, which makes the safety fallback visible in the UI."
    );
  }

  function renderDiagnosticsComparison(doc) {
    if (!diagnosticsCompare) return;
    const samples = (doc.samples || []).filter((sample) => sample && sample.diagnostics);
    if (!samples.length) throw new Error("no diagnostics samples");

    diagnosticsCompare.innerHTML = "";
    const summary = node("div", "diagnostics-summary");
    samples.forEach((sample) => summary.appendChild(renderDiagnosticsCard(sample)));
    diagnosticsCompare.appendChild(summary);
    diagnosticsCompare.appendChild(renderDiagnosticsTable(samples));

    const note = renderDiagnosticsNote(samples);
    if (note) diagnosticsCompare.appendChild(note);
  }

  async function loadRouteDiagnostics() {
    if (!diagnosticsCompare) return;
    try {
      const res = await fetch("assets/route_explain_sample.json");
      if (!res.ok) throw new Error("diagnostics " + res.status);
      renderDiagnosticsComparison(await res.json());
    } catch (err) {
      diagnosticsCompare.innerHTML = "";
      diagnosticsCompare.appendChild(
        node("div", "diagnostics-error", "Failed to load route diagnostics: " + err.message)
      );
    }
  }

  loadRouteDiagnostics();
})();
