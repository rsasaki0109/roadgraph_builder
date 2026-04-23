#!/usr/bin/env python3
"""Render the README / Showcase map-console hero screenshots.

Serves ``docs/`` on a local HTTP server, then invokes the Playwright CLI
(``npx -y -p @playwright/test playwright screenshot``) with system Chrome to
capture 2D and 3D views of ``docs/map.html``.

External dependencies pulled at runtime (OSM tiles, Leaflet CDN, Three.js
CDN) are baked into the PNG and carry the OSM attribution already rendered
inside the viewer.
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
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DEFAULT_2D = DOCS / "images" / "map_console_2d.png"
DEFAULT_3D = DOCS / "images" / "map_console_3d.png"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextlib.contextmanager
def _docs_server():
    handler = functools.partial(QuietHandler, directory=str(DOCS))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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


def _resolve_npx(explicit: str | None) -> str:
    for candidate in (explicit, os.environ.get("ROADGRAPH_NPX"), "npx"):
        if not candidate:
            continue
        resolved = shutil.which(candidate) if os.sep not in candidate else candidate
        if resolved and Path(resolved).exists():
            return str(resolved)
    raise SystemExit("Could not find npx. Install Node.js or pass --npx.")


def _assert_png(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 32 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"Playwright did not write a valid PNG: {path}")


def _quantize_png(path: Path, colors: int = 256) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as im:
        quantized = im.quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG)
        quantized.save(path, optimize=True)


def _screenshot(
    *,
    url: str,
    output: Path,
    width: int,
    height: int,
    npx: str,
    channel: str,
    settle_ms: int,
    timeout_ms: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.stem + ".tmp" + output.suffix)
    if tmp.exists():
        tmp.unlink()
    cmd = [
        npx,
        "-y",
        "-p",
        "@playwright/test",
        "playwright",
        "screenshot",
        "--channel",
        channel,
        "--viewport-size",
        f"{width},{height}",
        "--wait-for-selector",
        "body[data-ready]",
        "--wait-for-timeout",
        str(settle_ms),
        "--timeout",
        str(timeout_ms),
        url,
        str(tmp),
    ]
    subprocess.run(cmd, check=True)
    _assert_png(tmp)
    _quantize_png(tmp)
    tmp.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-2d", type=Path, default=DEFAULT_2D)
    parser.add_argument("--output-3d", type=Path, default=DEFAULT_3D)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--dataset", default="paris_grid")
    parser.add_argument(
        "--channel",
        default="chrome",
        help="Playwright Chromium distribution channel (default: chrome).",
    )
    parser.add_argument("--npx", help="npx executable path or name")
    parser.add_argument(
        "--settle-ms",
        type=int,
        default=4500,
        help="Extra wait after body[data-ready] so OSM tiles and 3D canvas settle.",
    )
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument(
        "--only",
        choices=["2d", "3d"],
        help="Render only one view; default is both.",
    )
    args = parser.parse_args(argv)

    npx = _resolve_npx(args.npx)

    with _docs_server() as base:
        preflight = f"{base}map.html"
        _wait_for_http(preflight)
        url_2d = f"{base}map.html?dataset={args.dataset}&view=2d"
        url_3d = f"{base}map.html?dataset={args.dataset}&view=3d"
        if args.only != "3d":
            _screenshot(
                url=url_2d,
                output=args.output_2d,
                width=args.width,
                height=args.height,
                npx=npx,
                channel=args.channel,
                settle_ms=args.settle_ms,
                timeout_ms=args.timeout_ms,
            )
            print(f"Wrote {_rel(args.output_2d)}")
        if args.only != "2d":
            _screenshot(
                url=url_3d,
                output=args.output_3d,
                width=args.width,
                height=args.height,
                npx=npx,
                channel=args.channel,
                settle_ms=args.settle_ms,
                timeout_ms=args.timeout_ms,
            )
            print(f"Wrote {_rel(args.output_3d)}")
    return 0


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
