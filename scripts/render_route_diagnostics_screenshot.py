#!/usr/bin/env python3
"""Render the README route diagnostics comparison screenshot with headless Chrome."""

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
DEFAULT_OUTPUT = DOCS / "images" / "route_diagnostics_compare.png"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _find_chrome(explicit: str | None) -> str:
    candidates = [
        explicit,
        os.environ.get("ROADGRAPH_CHROME"),
        "google-chrome",
        "chromium",
        "chromium-browser",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) if os.sep not in candidate else candidate
        if resolved and Path(resolved).exists():
            return str(resolved)
    raise SystemExit(
        "Could not find Chrome/Chromium. Set ROADGRAPH_CHROME or pass --chrome."
    )


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
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as res:
                if res.status == 200:
                    return
        except URLError as exc:
            last_error = exc
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _assert_png(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 32 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"Chrome did not write a valid PNG: {path}")


def render(output: Path, chrome: str, width: int, height: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with _docs_server() as base_url, tempfile.TemporaryDirectory() as user_data:
        url = base_url + "route_diagnostics_preview.html"
        _wait_for_http(url)
        tmp_output = output.with_name(output.stem + ".tmp" + output.suffix)
        if tmp_output.exists():
            tmp_output.unlink()
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--user-data-dir={user_data}",
            f"--window-size={width},{height}",
            "--virtual-time-budget=5000",
            f"--screenshot={tmp_output}",
            url,
        ]
        subprocess.run(cmd, check=True)
        _assert_png(tmp_output)
        tmp_output.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"PNG path to write (default: {DEFAULT_OUTPUT.relative_to(ROOT)})",
    )
    parser.add_argument("--chrome", help="Chrome/Chromium executable path or name")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=620)
    args = parser.parse_args(argv)

    chrome = _find_chrome(args.chrome)
    render(args.output, chrome, args.width, args.height)
    try:
        shown = args.output.resolve().relative_to(ROOT)
    except ValueError:
        shown = args.output
    print(f"Wrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
