"""Opt-in browser smoke for docs/map.html.

Serves ``docs/`` on a local HTTP server, then drives the Playwright CLI
(``npx -y -p @playwright/test playwright test tests/js/map_console_smoke.spec.mjs``)
against system Chrome so the regression covers the real 2D / 3D / mobile
layouts of the map console.

Marked ``@pytest.mark.browser_smoke`` and excluded from the default ``pytest``
run because the test requires Node.js, npx, and a system Chrome/Chromium, and
because ``npx`` may fetch ``@playwright/test`` from the npm registry the first
time it runs. Opt in with ``pytest -m browser_smoke`` or ``make viewer-smoke``.

The test skips (rather than fails) when any of the required tools is absent so
it stays safe to enable on developer machines that do not have a browser stack
installed.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import os
import shutil
import socketserver
import subprocess
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SPEC = ROOT / "tests" / "js" / "map_console_smoke.spec.mjs"

pytestmark = pytest.mark.browser_smoke


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
        yield f"http://{host}:{port}/map.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _first_on_path(*names: str) -> str | None:
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def test_map_console_browser_smoke():
    if SPEC.stat().st_size < 100:
        pytest.fail(f"Playwright spec missing or truncated: {SPEC}")
    if not _first_on_path("node"):
        pytest.skip("node not on PATH; install Node.js for browser smoke")
    npx = _first_on_path("npx")
    if not npx:
        pytest.skip("npx not on PATH; install Node.js for browser smoke")
    if not _first_on_path("google-chrome", "chromium", "chromium-browser"):
        pytest.skip("system Chrome/Chromium not on PATH; needed for channel:chrome")

    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")
    # ``npx -y -p @playwright/test`` drops @playwright/test into a temp directory
    # and exposes the ``playwright`` binary on PATH, but Node's ESM resolver does
    # not honour NODE_PATH for ``import`` statements, so the spec's
    # ``import { test } from "@playwright/test"`` cannot be resolved from an
    # out-of-tree location. Work around this by running ``playwright test`` from
    # a scratch workdir that has a ``node_modules`` symlink to npx's cache, and
    # copying the committed spec into that workdir.
    shell_cmd = (
        'set -e\n'
        'NP="$(dirname "$(dirname "$(command -v playwright)")")"\n'
        'WORK="$(mktemp -d)"\n'
        'trap "rm -rf \\"$WORK\\"" EXIT\n'
        'ln -s "$NP" "$WORK/node_modules"\n'
        'cp "$1" "$WORK/map_console_smoke.spec.mjs"\n'
        'cd "$WORK"\n'
        'exec playwright test map_console_smoke.spec.mjs '
        '--reporter=list --workers=1'
    )
    with _docs_server() as url:
        env["MAP_URL"] = url
        cmd = [
            npx,
            "-y",
            "-p",
            "@playwright/test",
            "sh",
            "-c",
            shell_cmd,
            "browser_smoke",
            str(SPEC),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=ROOT,
            timeout=240,
        )

    assert result.returncode == 0, (
        f"playwright test exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
