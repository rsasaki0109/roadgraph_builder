#!/usr/bin/env python3
"""Record the map console hero GIF for the README / Showcase.

Serves ``docs/`` over a local HTTP server, drives the Playwright CLI with
system Chrome through a scripted demo (Paris grid deep link → 2D soak →
switch to 3D → auto-rotate soak → back to 2D), captures a WebM video via
``recordVideo`` and converts it to a GIF with ffmpeg's two-pass palette
pipeline.

External dependencies are the same as
``scripts/render_map_console_screenshot.py`` (system Chrome + Playwright via
``npx``) plus ``ffmpeg`` on ``PATH``. The script skips cleanly when any is
missing.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DEFAULT_OUTPUT = DOCS / "images" / "map_console_hero.gif"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextlib.contextmanager
def _docs_server():
    handler = functools.partial(_QuietHandler, directory=str(DOCS))
    server = _ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _wait_for_http(url: str, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as res:
                if res.status == 200:
                    return
        except URLError as exc:
            last = exc
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for {url}: {last}")


def _resolve_tool(*names: str) -> str | None:
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


PLAYWRIGHT_SPEC = r"""
import { test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test.use({
  channel: "chrome",
  viewport: { width: 1200, height: 720 },
});

const MAP_URL = process.env.MAP_URL;
const OUTPUT_DIR = process.env.OUTPUT_DIR;
if (!MAP_URL || !OUTPUT_DIR) {
  throw new Error("MAP_URL and OUTPUT_DIR are required");
}

test("hero", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 1200, height: 720 },
    recordVideo: { dir: OUTPUT_DIR, size: { width: 1200, height: 720 } },
  });
  try {
    const page = await context.newPage();
    // 1) Land on the deep link so the Paris TR route and Route steps card are
    //    visible from the very first frame.
    await page.goto(
      MAP_URL + "?dataset=paris_grid&view=2d&from=n312&to=n191",
      { waitUntil: "domcontentloaded" },
    );
    await page.waitForSelector("body[data-ready='2d']", { timeout: 45000 });
    // Short 2D soak so OSM tiles settle and the inspector is readable.
    await page.waitForTimeout(2500);

    // 2) Flip to 3D and let auto-rotate show the scene in motion.
    await page.click("#view-3d");
    await page.waitForTimeout(400);
    await page.waitForSelector("body[data-ready]", { timeout: 15000 });
    await page.waitForTimeout(4200);

    const video = page.video();
    await context.close();
    if (video) {
      const src = await video.path();
      const dest = path.join(OUTPUT_DIR, "hero.webm");
      fs.copyFileSync(src, dest);
    }
  } finally {
    await context.close().catch(() => {});
  }
});
"""


def _run_playwright_record(
    *, map_url: str, output_dir: Path, npx: str, timeout_ms: int
) -> Path:
    spec_text = PLAYWRIGHT_SPEC
    # Playwright's temp-dir wiring is the same as the opt-in browser smoke:
    # npx -y -p @playwright/test drops the package into a temp cache, but
    # Node's ESM resolver does not honour NODE_PATH, so we symlink the
    # node_modules dir into a scratch workdir and copy the spec in.
    shell_cmd = (
        "set -e\n"
        'NP="$(dirname "$(dirname "$(command -v playwright)")")"\n'
        'WORK="$(mktemp -d)"\n'
        'trap "rm -rf \\"$WORK\\"" EXIT\n'
        'ln -s "$NP" "$WORK/node_modules"\n'
        'printf "%s" "$SPEC_BODY" > "$WORK/hero.spec.mjs"\n'
        'cd "$WORK"\n'
        "exec playwright test hero.spec.mjs "
        "--reporter=list --workers=1"
    )
    env = os.environ.copy()
    env["MAP_URL"] = map_url
    env["OUTPUT_DIR"] = str(output_dir)
    env["SPEC_BODY"] = spec_text
    env.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")
    cmd = [
        npx,
        "-y",
        "-p",
        "@playwright/test",
        "sh",
        "-c",
        shell_cmd,
        "hero_record",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=timeout_ms / 1000.0,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "playwright test failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    webm = output_dir / "hero.webm"
    if not webm.is_file():
        raise RuntimeError(
            "Playwright finished but hero.webm was not produced in "
            f"{output_dir}"
        )
    return webm


def _webm_to_gif(
    webm: Path,
    gif: Path,
    *,
    ffmpeg: str,
    fps: int,
    width: int,
    max_colors: int,
) -> None:
    gif.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        palette = Path(tmp) / "palette.png"
        vf_common = f"fps={fps},scale={width}:-1:flags=lanczos"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(webm),
                "-vf",
                f"{vf_common},palettegen=max_colors={max_colors}",
                str(palette),
            ],
            check=True,
        )
        tmp_gif = gif.with_name(gif.stem + ".tmp" + gif.suffix)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(webm),
                "-i",
                str(palette),
                "-lavfi",
                f"{vf_common} [x]; [x][1:v] paletteuse=dither=sierra2_4a",
                "-loop",
                "0",
                str(tmp_gif),
            ],
            check=True,
        )
        head = tmp_gif.read_bytes()[:6]
        if head not in (b"GIF87a", b"GIF89a"):
            raise RuntimeError(f"ffmpeg did not write a GIF: {tmp_gif}")
        tmp_gif.replace(gif)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--max-colors", type=int, default=64)
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=180_000,
        help="Timeout for the Playwright subprocess.",
    )
    parser.add_argument("--npx", help="npx executable path")
    parser.add_argument("--ffmpeg", help="ffmpeg executable path")
    args = parser.parse_args(argv)

    npx = args.npx or _resolve_tool("npx")
    ffmpeg = args.ffmpeg or _resolve_tool("ffmpeg")
    chrome = _resolve_tool("google-chrome", "chromium", "chromium-browser")
    missing = []
    if not npx:
        missing.append("npx")
    if not ffmpeg:
        missing.append("ffmpeg")
    if not chrome:
        missing.append("system Chrome/Chromium")
    if missing:
        raise SystemExit(
            "Cannot record hero GIF: missing "
            + ", ".join(missing)
            + " on PATH."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_out, _docs_server() as base:
        tmp_dir = Path(tmp_out)
        preflight = f"{base}map.html"
        _wait_for_http(preflight)
        map_url = base + "map.html"
        webm = _run_playwright_record(
            map_url=map_url,
            output_dir=tmp_dir,
            npx=npx,
            timeout_ms=args.timeout_ms,
        )
        _webm_to_gif(
            webm,
            args.output,
            ffmpeg=ffmpeg,
            fps=args.fps,
            width=args.width,
            max_colors=args.max_colors,
        )
    try:
        shown = args.output.resolve().relative_to(ROOT)
    except ValueError:
        shown = args.output
    print(f"Wrote {shown} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
