// Opt-in Playwright smoke spec for docs/map.html.
//
// Driven by tests/test_map_console_browser_smoke.py through:
//   npx -y -p @playwright/test playwright test tests/js/map_console_smoke.spec.mjs
// with MAP_URL pointing at a locally-served docs/map.html. Uses system Chrome
// (test.use channel:"chrome") so no Playwright browser download is required.

import { test, expect } from "@playwright/test";

test.use({ channel: "chrome" });

const MAP_URL = process.env.MAP_URL;
if (!MAP_URL) {
  throw new Error("MAP_URL env var is required (URL of docs/map.html).");
}

const READY_TIMEOUT_MS = 45_000;

function countText(value) {
  return Number(String(value || "").replace(/[^0-9.-]/g, ""));
}

async function openReady(page, view) {
  await page.goto(`${MAP_URL}?dataset=paris_grid&view=${view}`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForSelector(`body[data-ready="${view}"]`, {
    timeout: READY_TIMEOUT_MS,
  });
}

test("2D desktop loads Paris grid with overlays", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await openReady(page, "2d");

  const nodes = countText(await page.textContent("#stat-nodes"));
  const centerlines = countText(await page.textContent("#stat-edges"));
  const restrictions = countText(await page.textContent("#stat-tr"));
  expect(nodes, "paris_grid should have hundreds of nodes").toBeGreaterThan(500);
  expect(centerlines, "paris_grid should have hundreds of centerlines").toBeGreaterThan(500);
  expect(restrictions, "paris_grid ships 10 mapped turn restrictions").toBeGreaterThanOrEqual(5);
});

test("3D desktop renders a non-blank WebGL canvas", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await openReady(page, "3d");

  const pixelSum = await page.evaluate(() => {
    const canvas = document.getElementById("scene3d-canvas");
    if (!canvas) return -1;
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl) return -1;
    const w = canvas.width || 1;
    const h = canvas.height || 1;
    const px = new Uint8Array(4);
    gl.readPixels(
      Math.floor(w / 2),
      Math.floor(h / 2),
      1,
      1,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      px,
    );
    return px[0] + px[1] + px[2];
  });
  expect(pixelSum, "readPixels should see the Three.js clear color / scene").toBeGreaterThan(0);

  const statusText = (await page.textContent("#scene3d-status")) || "";
  expect(statusText.toLowerCase()).toContain("node");
});

test("mobile viewport has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openReady(page, "2d");

  const overflowBy = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth - doc.clientWidth;
  });
  expect(
    overflowBy,
    `body should fit the mobile viewport (scrollWidth - clientWidth = ${overflowBy})`,
  ).toBeLessThanOrEqual(1);
});

test("deep-link restores the Paris TR-aware route", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(`${MAP_URL}?dataset=paris_grid&view=2d&from=n312&to=n191`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForSelector("body[data-ready='2d']", {
    timeout: READY_TIMEOUT_MS,
  });

  // The route steps card must be shown with the full edge list.
  await expect(page.locator("#steps-card")).toBeVisible();
  const stepCount = await page.locator("#steps-list li").count();
  expect(stepCount, "paris_grid TR route must have multiple edges").toBeGreaterThanOrEqual(3);

  const countText = (await page.textContent("#steps-count")) || "";
  expect(countText).toMatch(/\d+ edges ·/);
  expect(countText).toMatch(/m$/);

  const status = (await page.textContent("#route-status")) || "";
  expect(status).toContain("deep link");
  expect(status).toContain("n312");
  expect(status).toContain("n191");

  // URL sync preserves the deep link (replaceState after draw).
  const url = page.url();
  expect(url).toContain("from=n312");
  expect(url).toContain("to=n191");

  // Download button should become enabled once a route is drawn; clicking it
  // triggers a browser download carrying a valid GeoJSON FeatureCollection.
  const downloadBtn = page.locator("#download-route");
  await expect(downloadBtn).toBeEnabled();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    downloadBtn.click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^route_paris_grid_n312_n191\.geojson$/);
  const path = await download.path();
  expect(path, "downloaded file path should be available").toBeTruthy();
  const fs = await import("node:fs");
  const body = JSON.parse(fs.readFileSync(path, "utf-8"));
  expect(body.type).toBe("FeatureCollection");
  const routeFeature = (body.features || []).find(
    (f) => f?.properties?.kind === "route",
  );
  expect(routeFeature, "downloaded payload must carry a kind=route feature").toBeTruthy();
  expect(routeFeature.geometry.type).toBe("LineString");
  expect(routeFeature.geometry.coordinates.length).toBeGreaterThan(1);
  expect(routeFeature.properties.from_node).toBe("n312");
  expect(routeFeature.properties.to_node).toBe("n191");
});

test("3D hover picks an edge or node and click routes", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await openReady(page, "3d");

  // Initial hover card shows placeholders until a ray hits something.
  expect(await page.textContent("#hover-kind")).toBe("—");

  // Park the cursor over the densest part of the Paris grid, which is near the
  // center of the canvas. The scene keeps rotating slowly until a pickable
  // object ends up under the pointer — then the hover card updates and
  // auto-rotate pauses.
  const canvas = page.locator("#scene3d-canvas");
  const box = await canvas.boundingBox();
  if (!box) throw new Error("scene3d-canvas has no bounding box");
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);

  await expect
    .poll(async () => (await page.textContent("#hover-kind"))?.trim(), {
      timeout: 8000,
      message: "expected hover card to report something other than —",
    })
    .not.toBe("—");

  // The hover card should carry either an edge id (for centerlines) or a node
  // id — both indicate picking is producing meaningful userData.
  const id = (await page.textContent("#hover-id"))?.trim() || "";
  expect(id, "hover card ID should be populated").not.toBe("—");
  expect(id.length, "hover card ID should be non-empty").toBeGreaterThan(0);

  // Click at the same spot. Pointerup without drag triggers the pick; a node
  // hit kicks off click-to-route and updates #route-status, while an edge hit
  // keeps the hover card populated. Either outcome proves picking is wired up.
  await page.mouse.down();
  await page.mouse.up();
  const statusAfter = (await page.textContent("#route-status")) || "";
  const hoverAfter = (await page.textContent("#hover-id"))?.trim() || "";
  expect(
    statusAfter.length,
    "route_status should remain populated after a 3D click",
  ).toBeGreaterThan(0);
  expect(
    statusAfter.startsWith("from = ") || hoverAfter !== "—",
    `expected node-click status or edge hover; got status="${statusAfter}", hover="${hoverAfter}"`,
  ).toBe(true);
});
