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
