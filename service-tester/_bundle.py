import http.server
import json
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

from _constants import BUILD_TESTER_DIR


def _revive(value):
    if isinstance(value, list):
        return [_revive(item) for item in value]
    if isinstance(value, dict):
        if "__undefined__" in value:
            return None
        if "__nonfinite__" in value:
            return float(value["__nonfinite__"])
        return {key: _revive(item) for key, item in value.items()}
    return value


async def collect_results(page, timeout=120000):
    # The shared test page publishes to this DOM node. Juggler's isolated
    # evaluation world cannot read the page's private window globals.
    await page.wait_for_selector("#__camoufoxResults__", state="attached", timeout=timeout)
    raw = await page.locator("#__camoufoxResults__").text_content()
    if not raw:
        return None, "results node was empty"
    payload = _revive(json.loads(raw))
    if payload.get("error"):
        return None, payload["error"]
    if not isinstance(payload.get("results"), dict):
        return None, "results payload was missing"
    return payload["results"], None


def ensure_bundle() -> Path:
    bundle_path = BUILD_TESTER_DIR / "scripts" / "checks-bundle.js"
    if bundle_path.exists():
        return bundle_path

    node_modules = BUILD_TESTER_DIR / "node_modules"
    if not node_modules.exists():
        print("ERROR: build-tester/node_modules not found. Run 'npm install' in build-tester/ first.", file=sys.stderr)
        sys.exit(1)

    esbuild_name = "esbuild.cmd" if sys.platform == "win32" else "esbuild"
    esbuild = BUILD_TESTER_DIR / "node_modules" / ".bin" / esbuild_name
    print("Building checks bundle (first run)...")
    entry = BUILD_TESTER_DIR / "src" / "lib" / "checks" / "index.ts"
    result = subprocess.run(
        [
            str(esbuild),
            str(entry),
            "--bundle",
            "--platform=browser",
            "--target=es2017",
            "--format=iife",
            "--global-name=CamoufoxChecks",
            f"--outfile={bundle_path}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: esbuild failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Bundle built: {bundle_path}")
    return bundle_path


def start_http_server() -> int:
    scripts_dir = BUILD_TESTER_DIR / "scripts"
    template_path = scripts_dir / "test_page_template.html"
    bundle_path = scripts_dir / "checks-bundle.js"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path in ("/test", "/test/"):
                self._serve(template_path, "text/html; charset=utf-8")
            elif self.path == "/checks-bundle.js":
                self._serve(bundle_path, "application/javascript")
            else:
                self.send_response(404)
                self.end_headers()

        def _serve(self, path: Path, content_type: str):
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port
