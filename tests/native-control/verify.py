"""Exercise a built binary directly, using only the native control transport.

All profiles, files and HTTP data belong to this test. No manager data or
debugging protocol is accessed. Full probe values are saved in the output.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from native_control_client import ControlClient, ControlError


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


PAGE = r"""<!doctype html><html><meta charset=utf-8><title>Native control test</title>
<style>body{margin:0;font:16px Arial}button,input{margin:15px;padding:15px}
#drag,#drop{display:inline-block;width:120px;height:70px;margin:20px;background:#9bd}
#drop{background:#bda}iframe{display:block;margin:12px;width:500px;height:180px;border:6px solid #bbb}
#shadow{display:block;margin:12px}#spacer{height:2000px}
</style><button id=button>Click</button><input id=text><input id=file type=file multiple>
<div id=drag draggable=true>Drag</div><div id=drop>Drop here</div><div id=shadow></div>
<iframe id=frame src="/frame"></iframe><div id=spacer></div><button id=bottom>Bottom</button>
<script>
window.records=[];
window.siteValue=41;
const shadow=document.querySelector('#shadow').attachShadow({mode:'open'});
shadow.innerHTML='<button id="shadow-button">Shadow button</button>';
for(const type of ['pointermove','pointerdown','pointerup','mousedown','mouseup','click','dblclick',
 'contextmenu','keydown','keyup','input','change','compositionstart','compositionend',
 'dragstart','dragover','drop','dragend','wheel']) {
 document.addEventListener(type,e=>{
  records.push({type:e.type,id:e.composedPath()[0].id||'',trusted:e.isTrusted,key:e.key,code:e.code,
   ctrl:e.ctrlKey,shift:e.shiftKey,button:e.button,buttons:e.buttons,x:e.clientX,y:e.clientY,
   active:navigator.userActivation?.isActive});
  if(e.type==='contextmenu') e.preventDefault();
 },true);
}
document.querySelector('#drag').ondragstart=e=>e.dataTransfer.setData('text/plain','native-drag');
document.querySelector('#drop').ondragover=e=>e.preventDefault();
document.querySelector('#drop').ondrop=e=>{e.preventDefault();window.dropped=e.dataTransfer.getData('text/plain');};
window.pageReport=()=>({webdriver:navigator.webdriver,
  controls:Object.getOwnPropertyNames(window).filter(k=>/camoufox|juggler|webdriver|__control/i.test(k)),
  chrome:typeof window.chrome,focused:document.hasFocus(),visibility:document.visibilityState});
fetch('/report',{method:'POST',body:JSON.stringify({startup:pageReport()})});
</script></html>"""
FRAME = r"""<!doctype html><meta charset=utf-8><title>frame</title><style>button{margin:25px;padding:20px}</style>
<button id=frame-button>Frame</button><script>
window.frameClicks=[];document.querySelector('button').onclick=e=>frameClicks.push({trusted:e.isTrusted,active:navigator.userActivation.isActive});
</script>"""


class TestServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.reports = []
        self.requests_seen = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.reports.append(data.decode("utf-8", errors="replace"))
        self.reply(b"ok", "text/plain")

    def reply(self, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        self.server.requests_seen.append({"path": self.path, "headers": dict(self.headers)})
        path = urlparse(self.path).path
        if path == "/frame":
            self.reply(FRAME, "text/html; charset=utf-8")
        elif path == "/data":
            self.reply("native-body-✓", "text/plain; charset=utf-8")
        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/?redirected")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/download":
            body = b"native-control-download\n" * 1024
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="native-test.txt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/fingerprint-persistence.js":
            self.reply((ROOT / "tests/patches/fingerprint-persistence.js").read_bytes(), "application/javascript")
        elif path == "/fingerprint":
            self.reply("""<!doctype html><meta charset=utf-8><title>Fixed fingerprint</title>
              <script src="/fingerprint-persistence.js"></script>
              <script>fpMainProbe().then(v=>{window.fpResult=v;fetch('/report',{method:'POST',body:JSON.stringify({fingerprint:v})});})
              .catch(e=>window.fpError=String(e));</script>""", "text/html")
        elif path == "/csp":
            body = "<!doctype html><title>CSP</title><p id=content>CSP</p>".encode()
            self.send_response(200)
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'none'")
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.reply(PAGE, "text/html; charset=utf-8")


class Browser:
    def __init__(self, binary, root, config=None, profile=None, headed=False, preferences=None,
                 connect=True, initial_url=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.profile = Path(profile) if profile else self.root / "profile"
        self.profile.mkdir(parents=True, exist_ok=True)
        self.endpoint = self.root / f"endpoint-{secrets.token_hex(5)}.json"
        self.token = secrets.token_urlsafe(32)
        self.config = {**(config or {}), "control:enabled": True, "control:token": self.token,
                       "control:port": 0, "control:endpoint": str(self.endpoint)}
        download_dir = self.root / "downloads"
        download_dir.mkdir(exist_ok=True)
        prefs = {
            "browser.shell.checkDefaultBrowser": False, "browser.aboutwelcome.enabled": False,
            "browser.tabs.warnOnClose": False, "browser.warnOnQuit": False,
            "browser.sessionstore.resume_from_crash": False, "browser.startup.page": 0,
            "browser.download.folderList": 2, "browser.download.dir": str(download_dir),
            "browser.download.useDownloadDir": True, "browser.download.alwaysOpenPanel": False,
            "browser.helperApps.neverAsk.saveToDisk": "application/octet-stream",
            "browser.sessionstore.max_resumed_crashes": 0,
            "fission.autostart": True, "fission.webContentIsolationStrategy": 1,
            **(preferences or {}),
        }
        (self.profile / "user.js").write_text(
            "".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items()), encoding="utf-8"
        )
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CAMOU_CONFIG") and k != "MOZ_MARIONETTE"}
        env["CAMOU_CONFIG"] = json.dumps(self.config, ensure_ascii=True)
        env["MOZ_CRASHREPORTER_DISABLE"] = "1"
        env["MOZ_NO_REMOTE"] = "1"
        self.log = (self.root / "browser.log").open("wb")
        self.args = [str(binary), "-no-remote", "-wait-for-browser", "-profile", str(self.profile)]
        if not headed:
            self.args.append("-headless")
        self.args.append(initial_url or "about:blank")
        self.process = subprocess.Popen(self.args, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Browser exited: {self.process.returncode}; see {self.root / 'browser.log'}")
            if self.endpoint.exists():
                try:
                    data = json.loads(self.endpoint.read_text())
                    if data.get("port"):
                        break
                except (ValueError, OSError):
                    pass
            time.sleep(.1)
        else:
            self.close()
            raise TimeoutError(f"No endpoint; see {self.root / 'browser.log'}")
        if not connect:
            return
        self.client = ControlClient(self.endpoint, self.token)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            contexts = self.client.call("browsingContext.getTree")["contexts"]
            if contexts:
                self.context = contexts[0]["context"]
                break
            time.sleep(.1)
        else:
            raise TimeoutError("No browsing context")

    def evaluate(self, expression, context=None, world="main", timeout=30):
        result = self.client.call("script.evaluate", {"context": context or self.context,
            "expression": expression, "world": world}, timeout=timeout)
        return result.get("value")

    def query(self, selector, context=None, **kwargs):
        return self.client.call("dom.query", {"context": context or self.context,
                                             "selector": selector, **kwargs})["nodes"]

    def close(self):
        self.normal_exit = False
        if getattr(self, "client", None):
            try:
                self.client.call("browser.close", timeout=5)
            except (OSError, RuntimeError, TimeoutError):
                pass
            self.client.close()
        if getattr(self, "process", None):
            try:
                self.process.wait(timeout=20)
                self.normal_exit = self.process.returncode == 0 and not self.endpoint.exists()
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
        if getattr(self, "log", None):
            self.log.close()


def eventually(fn, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(.1)
    raise TimeoutError("Expected condition did not become true")


def expect_error(code, fn):
    try:
        fn()
    except ControlError as error:
        assert error.code == code, (error.code, code)
        return
    raise AssertionError(f"Expected {code}")


def wait_event(client, method, predicate=lambda _: True, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = client.events.get(timeout=max(.01, deadline - time.monotonic()))
        if item.get("method") == method and predicate(item["params"]):
            return item["params"]
    raise TimeoutError(method)


def run_smoke(browser, url, report):
    c, context = browser.client, browser.context
    report["browser"] = c.call("browser.getInfo")
    report["capabilities"] = c.connection["capabilities"]
    c.subscribe("*")
    report["navigation"] = c.call("browsingContext.navigate", {"context": context, "url": url})
    assert browser.evaluate("document.title") == "Native control test"
    report["startupDiagnostics"] = c.call("browser.getInfo", {"diagnostics": True})
    for item in report["startupDiagnostics"]["contexts"]:
        assert not item.get("error"), item
        assert not item["jugglerActor"] and not item["overrideHasFocus"] and not item["forceActiveState"] and not item["disallowBFCache"], item
        assert not any(name in uri for uri in item["modules"] for name in ("FrameTree", "PageAgent", "Runtime", "content/main.js"))
    assert browser.evaluate("siteValue+1") == 42
    assert browser.evaluate("typeof siteValue", world="isolated") == "undefined"
    assert browser.evaluate("document.querySelector('#button').textContent", world="isolated") == "Click"
    report["pageBefore"] = browser.evaluate("pageReport()")
    assert report["pageBefore"]["controls"] == []
    assert report["pageBefore"]["webdriver"] is False
    node = browser.query("#button")[0]
    c.call("input.click", {"context": context, "node": node["node"]})
    clicks = browser.evaluate("records.filter(e=>e.type==='click'&&e.id==='button')")
    assert clicks and clicks[-1]["trusted"] and clicks[-1]["active"], clicks
    report["click"] = clicks
    c.call("input.click", {"context": context, "node": node["node"], "count": 2})
    assert browser.evaluate("records.some(e=>e.type==='dblclick'&&e.trusted)")
    text = browser.query("#text")[0]
    c.call("input.click", {"context": context, "node": text["node"]})
    c.call("input.insertText", {"context": context, "text": "你好 Native ✓"})
    assert browser.evaluate("document.querySelector('#text').value") == "你好 Native ✓"
    for event in [("keydown", "Control"), ("keydown", "a"), ("keyup", "a"), ("keyup", "Control")]:
        c.call("input.dispatchKey", {"context": context, "type": event[0], "key": event[1]})
    c.call("input.insertText", {"context": context, "text": "replacement"})
    assert browser.evaluate("document.querySelector('#text').value") == "replacement"
    frame = c.call("browsingContext.getTree", {"root": context})["contexts"][0]["children"][0]["context"]
    frame_button = browser.query("#frame-button", context=frame)[0]
    c.call("input.click", {"context": frame, "node": frame_button["node"]})
    assert browser.evaluate("frameClicks", context=frame)[-1]["trusted"]
    shadow = browser.query("#shadow-button", pierce=True)[0]
    c.call("input.click", {"context": context, "node": shadow["node"]})
    assert browser.evaluate("records.some(e=>e.id==='shadow-button'&&e.type==='click'&&e.trusted)")
    report["geometry"] = c.call("page.info", {"context": context})
    report["reportedGeometry"] = browser.evaluate("({width:innerWidth,height:innerHeight,screenWidth:screen.width,dpr:devicePixelRatio})")
    if browser.config.get("window:profile"):
        assert report["reportedGeometry"]["width"] == 777
        assert report["geometry"]["viewport"]["width"] != 777
    c.call("input.dispatchPointer", {"context": context, "type": "pointerMove", "x": 0, "y": 0})
    c.call("input.dispatchPointer", {"context": context, "type": "pointerMove", "x": 0, "y": 0})
    screenshot = c.call("browsingContext.captureScreenshot", {"context": context})
    image = base64.b64decode(screenshot.pop("data"))
    assert image.startswith(b"\x89PNG")
    (browser.root / "viewport.png").write_bytes(image)
    report["screenshot"] = {**screenshot, "sha256": hashlib.sha256(image).hexdigest()}
    c.call("storage.set", {"context": context, "entries": {"native-key": "persistent-value"}})
    assert c.call("storage.get", {"context": context})["entries"]["native-key"] == "persistent-value"
    c.call("storage.setCookie", {"context": context, "cookie": {
        "url": url, "name": "native-cookie", "value": "cookie-value", "sameSite": "Lax"}})
    assert any(item["name"] == "native-cookie" for item in c.call("storage.getCookies", {"context": context})["cookies"])
    path = browser.root / "upload.txt"
    path.write_text("native-upload-✓", encoding="utf-8")
    c.call("dom.setFiles", {"context": context, "node": browser.query("#file")[0]["node"], "files": [str(path)]})
    assert browser.evaluate("document.querySelector('#file').files[0].name") == "upload.txt"
    report["fileEvents"] = browser.evaluate("records.filter(e=>e.id==='file')")
    assert {e["type"] for e in report["fileEvents"]} >= {"input", "change"}
    assert all(e["trusted"] for e in report["fileEvents"])
    c.call("network.enable", {"contexts": [context]})
    assert browser.evaluate("fetch('/data').then(r=>r.text())") == "native-body-✓"
    response = wait_event(c, "network.responseCompleted", lambda p: "/data" in (p.get("url") or ""))
    assert base64.b64decode(c.call("network.getResponseBody", {"request": response["request"]})["data"]).decode() == "native-body-✓"
    rule = c.call("network.addIntercept", {"contexts": [context], "urlPatterns": [url + "intercept*"]})["intercept"]
    request_id, future = c.request("script.evaluate", {"context": context, "world": "main",
        "expression": "fetch('/intercept').then(r=>r.text())"})
    blocked = wait_event(c, "network.beforeRequestSent", lambda p: p.get("blocked"))
    c.call("network.provideResponse", {"request": blocked["request"], "status": 200,
        "headers": [{"name": "Content-Type", "value": "text/plain"}],
        "body": base64.b64encode(b"fulfilled").decode()})
    assert future.result(10)["value"] == "fulfilled"
    c.call("network.removeIntercept", {"intercept": rule})
    request_id, future = c.request("script.evaluate", {"context": context, "world": "main",
        "expression": "new Promise(()=>{})"})
    c.call("control.cancel", {"request": request_id})
    expect_error("cancelled", lambda: future.result(5))
    expect_error("timeout", lambda: browser.evaluate("new Promise(()=>{})", timeout=.2))
    c.call("browsingContext.navigate", {"context": context, "url": url + "?second"})
    c.call("browsingContext.traverseHistory", {"context": context, "delta": -1})
    assert browser.evaluate("location.href") == url
    c.call("browsingContext.traverseHistory", {"context": context, "delta": 1})
    assert browser.evaluate("location.search") == "?second"
    c.call("browsingContext.reload", {"context": context})
    new = c.call("browsingContext.create", {"background": True})["context"]
    c.call("browsingContext.navigate", {"context": new, "url": url + "csp"})
    assert c.call("page.info", {"context": new})["title"] == "CSP"
    assert browser.evaluate("document.title", context=new) == "CSP"
    assert browser.evaluate("(()=>{try{eval('1');return 'allowed'}catch(e){return e.name}})()", context=new) == "EvalError"
    assert browser.evaluate("typeof ChromeUtils", context=new) == "undefined"
    report["nativeExecutionWithCSP"] = True
    c.call("browsingContext.close", {"context": new})
    expect_error("no such context", lambda: c.call("page.info", {"context": new}))
    report["pageAfter"] = browser.evaluate("pageReport()")
    c.close()
    browser.client = ControlClient(browser.endpoint, browser.token)
    assert browser.evaluate("document.title") == "Native control test"
    report["reconnected"] = True


def run_extended(browser, url, report):
    c, context = browser.client, browser.context
    c.subscribe("*")
    expect_error("authentication failed", lambda: ControlClient(browser.endpoint, "x" * 43))
    metadata = json.loads(browser.endpoint.read_text())
    assert "token" not in metadata and browser.token not in browser.endpoint.read_text()
    stale = {**metadata, "instance": "wrong-instance"}
    try:
        ControlClient(stale, browser.token)
    except RuntimeError as error:
        assert "different browser instance" in str(error)
    else:
        raise AssertionError("Stale endpoint was accepted")
    with socket.create_connection((metadata["host"], metadata["port"]), 3) as raw:
        raw.sendall(b'{"id":1,"method":"browser.getInfo"}\n')
        error = json.loads(raw.makefile("rb").readline())
        assert error["error"]["code"] == "authentication failed"
    report["authorization"] = True

    c.call("browsingContext.navigate", {"context": context, "url": url})
    browser.evaluate("records=[];null")
    drag, drop = browser.query("#drag")[0], browser.query("#drop")[0]
    c.call("input.performActions", {"context": context, "actions": [{
        "id": "mouse", "type": "pointer", "parameters": {"pointerType": "mouse"}, "actions": [
            {"type": "pointerMove", **drag["point"]},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "x": drop["point"]["x"], "y": drop["point"]["y"], "duration": 200},
            {"type": "pointerUp", "button": 0},
        ]}]})
    assert browser.evaluate("window.dropped") == "native-drag"
    report["drag"] = browser.evaluate("records.filter(e=>e.type.startsWith('drag')||e.type==='drop')")
    assert all(item["trusted"] for item in report["drag"])

    c.call("input.dispatchPointer", {"context": context, "type": "pointerDown", "button": 0,
                                    "x": 5, "y": 5})
    second = ControlClient(browser.endpoint, browser.token)
    try:
        expect_error("input busy", lambda: second.call("input.click", {"context": context, "x": 5, "y": 5}))
        c.call("input.releaseActions", {"context": context})
        second.call("input.click", {"context": context, "x": 5, "y": 5})
    finally:
        second.close()
    c.call("input.dispatchWheel", {"context": context, "x": 5, "y": 100, "deltaY": 200})
    eventually(lambda: browser.evaluate("scrollY>0"))
    bottom = browser.query("#bottom")[0]
    c.call("input.click", {"context": context, "node": bottom["node"]})
    assert browser.evaluate("records.some(e=>e.id==='bottom'&&e.type==='click'&&e.trusted)")
    picture = c.call("browsingContext.captureScreenshot", {"context": context, "fullPage": True, "format": "jpeg"})
    assert base64.b64decode(picture["data"]).startswith(b"\xff\xd8")
    report["fullPageScreenshot"] = {key: value for key, value in picture.items() if key != "data"}
    c.call("browsingContext.navigate", {"context": context, "url": url})
    cross_url = url.replace("127.0.0.1", "localhost") + "frame"
    browser.evaluate(f"document.querySelector('#frame').src={json.dumps(cross_url)};null")
    frame = eventually(lambda: next((child["context"] for child in
        c.call("browsingContext.getTree", {"root": context})["contexts"][0]["children"]
        if child["url"] == cross_url), None))
    eventually(lambda: browser.query("#frame-button", context=frame))
    frame_button = browser.query("#frame-button", context=frame)[0]
    c.call("input.click", {"context": frame, "node": frame_button["node"]})
    diagnostics = c.call("browser.getInfo", {"diagnostics": True})
    report["crossProcessFrames"] = diagnostics["contexts"]
    report["crossProcessInput"] = {"node": frame_button,
        "frame": browser.query("#frame")[0],
        "frameInfo": c.call("page.info", {"context": frame}),
        "clicks": browser.evaluate("frameClicks", context=frame),
        "rootEvents": browser.evaluate("records.slice(-15)") }
    assert report["crossProcessInput"]["clicks"][-1]["trusted"]
    processes = {item["context"]: item["processId"] for item in diagnostics["contexts"]}
    assert processes[frame] != processes[context], processes
    assert all(not item["jugglerActor"] for item in diagnostics["contexts"])

    request_id, prompt = c.request("script.evaluate", {"context": context, "world": "main",
        "expression": "prompt('native-dialog','old')"})
    dialogs = eventually(lambda: c.call("page.getDialogs", {"context": context})["dialogs"])
    report["dialogs"] = dialogs
    c.call("page.handleDialog", {"context": context, "dialog": dialogs[0]["dialog"], "accept": True, "text": "native-answer"})
    assert prompt.result(10)["value"] == "native-answer"
    c.call("permissions.set", {"context": context, "origin": url, "name": "geolocation", "state": "granted"})
    assert browser.evaluate("navigator.permissions.query({name:'geolocation'}).then(p=>p.state)") == "granted"
    c.call("permissions.reset", {"context": context, "origin": url, "name": "geolocation"})
    container = c.call("browsingContext.create", {"userContextId": 1})["context"]
    c.call("browsingContext.navigate", {"context": container, "url": url})
    assert not c.call("storage.get", {"context": container})["entries"].get("native-key")
    assert not any(k["name"] == "native-cookie" for k in c.call("storage.getCookies", {"context": container})["cookies"])
    c.call("browsingContext.close", {"context": container})
    private = c.call("browsingContext.create", {"type": "window", "private": True})["context"]
    c.call("browsingContext.navigate", {"context": private, "url": url})
    assert not c.call("storage.get", {"context": private})["entries"].get("native-key")
    c.call("browsingContext.close", {"context": private})
    c.call("browsingContext.activate", {"context": context})
    c.call("browsingContext.navigate", {"context": context, "url": url + "download", "wait": "none"})
    downloads = eventually(lambda: [item for item in c.call("downloads.get")["downloads"] if item["succeeded"]])
    report["downloads"] = downloads
    assert Path(downloads[-1]["path"]).read_bytes() == b"native-control-download\n" * 1024
    report["extended"] = True


def run_contracts(browser, url, report):
    """Regression checks for object lifetime, real geometry and cleanup."""
    c, context = browser.client, browser.context
    c.call("browsingContext.navigate", {"context": context, "url": url})
    c.subscribe("browsingContext.*", contexts=[context])
    existing = {item["context"] for item in
        c.call("browsingContext.getTree", {"root": context})["contexts"][0]["children"]}
    while not c.events.empty():
        c.events.get_nowait()
    browser.evaluate("(()=>{let f=document.createElement('iframe');f.id='lifecycle-frame';"
                     "f.src='/frame?lifecycle';document.body.append(f);return null})()")
    created = wait_event(c, "browsingContext.created",
                         lambda p: p.get("parent") == context and p["context"] not in existing)
    frame = created["context"]
    browser.evaluate("document.querySelector('#lifecycle-frame').remove();null")
    destroyed = wait_event(c, "browsingContext.destroyed", lambda p: p["context"] == frame)
    assert context in destroyed["ancestors"]
    expect_error("no such context", lambda: c.call("page.info", {"context": frame}))
    report["frameLifecycle"] = {"created": created, "destroyed": destroyed}

    node = browser.query("#button")[0]["node"]
    with ControlClient(browser.endpoint, browser.token) as other:
        expect_error("stale element", lambda: other.call("dom.get", {"context": context, "node": node}))
    c.call("dom.release", {"context": context, "nodes": [node]})
    expect_error("stale element", lambda: c.call("dom.get", {"context": context, "node": node}))
    c.call("storage.set", {"context": context, "area": "session", "entries": {"__proto__": "literal-value"}})
    assert c.call("storage.get", {"context": context, "area": "session"})["entries"]["__proto__"] == "literal-value"
    c.call("storage.remove", {"context": context, "area": "session", "key": "__proto__"})

    # Reported DPR is 2 in this fixture; every command below must still target
    # native geometry, including a transformed, independently scrolling OOP frame.
    cross_url = url.replace("127.0.0.1", "localhost") + "frame?wheel"
    browser.evaluate(f"document.querySelector('#frame').src={json.dumps(cross_url)};null")
    frame = eventually(lambda: next((item["context"] for item in
        c.call("browsingContext.getTree", {"root": context})["contexts"][0]["children"]
        if item["url"] == cross_url), None))
    eventually(lambda: browser.query("#frame-button", context=frame))
    browser.evaluate("document.body.style.height='2000px';window.wheelEvents=[];"
                     "document.addEventListener('wheel',e=>wheelEvents.push({trusted:e.isTrusted}));null", context=frame)
    browser.evaluate("document.querySelector('#frame').style.cssText='transform:scale(.8);transform-origin:0 0';null")
    c.call("input.click", {"context": frame, "node": browser.query("#frame-button", context=frame)[0]["node"]})
    assert browser.evaluate("frameClicks.at(-1).trusted", context=frame)
    c.call("input.dispatchWheel", {"context": frame, "x": 20, "y": 100, "deltaY": 200})
    eventually(lambda: browser.evaluate("scrollY>0&&wheelEvents.some(e=>e.trusted)", context=frame))
    expect_error("move target out of bounds", lambda: c.call("input.dispatchWheel",
        {"context": frame, "x": 20, "y": 1000, "deltaY": 200}))
    report["crossProcessWheel"] = True

    c.call("input.click", {"context": context, "node": browser.query("#button")[0]["node"], "button": 2})
    assert browser.evaluate("records.some(e=>e.type==='contextmenu'&&e.trusted)")
    # Browser zoom comes from native keyboard input, never from profile DPR.
    before_zoom = c.call("page.info", {"context": context})["viewport"]
    for kind, key in [("keydown", "Control"), ("keydown", "+"), ("keyup", "+"), ("keyup", "Control")]:
        c.call("input.dispatchKey", {"context": context, "type": kind, "key": key})
    after_zoom = eventually(lambda: (value if value["width"] != before_zoom["width"] else None)
        if (value := c.call("page.info", {"context": context})["viewport"]) else None)
    browser.evaluate("(()=>{const b=document.createElement('button');b.id='zoom-target';"
        "b.style.cssText='position:fixed;left:80vw;top:50vh;width:8px;height:8px;margin:0;padding:0';"
        "document.body.append(b);return null})()")
    c.call("input.click", {"context": context, "node": browser.query("#zoom-target")[0]["node"]})
    report["fullPageZoom"] = {"before": before_zoom, "after": after_zoom,
        "node": browser.query("#zoom-target")[0], "events": browser.evaluate("records.slice(-10)"),
        "input": c.call("browser.getInfo", {"diagnostics": True})["input"]}
    assert browser.evaluate("records.some(e=>e.type==='click'&&e.id==='zoom-target'&&e.trusted)")
    c.call("input.click", {"context": frame, "node": browser.query("#frame-button", context=frame)[0]["node"]})
    assert browser.evaluate("frameClicks.at(-1).trusted", context=frame)
    browser.evaluate("document.querySelector('#zoom-target').remove();null")
    for kind, key in [("keydown", "Control"), ("keydown", "0"), ("keyup", "0"), ("keyup", "Control")]:
        c.call("input.dispatchKey", {"context": context, "type": kind, "key": key})
    report["fullPageZoom"] = {"before": before_zoom, "after": after_zoom,
                            "profile": browser.evaluate("({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})")}
    image = c.call("browsingContext.captureScreenshot", {"context": context, "format": "webp",
        "clip": {"x": 0, "y": 0, "width": 120, "height": 80}, "scale": 1})
    assert base64.b64decode(image["data"])[8:12] == b"WEBP"
    assert (image["width"], image["height"]) == (120, 80)

    # Cancelling a multi-tick operation releases the already delivered modifier.
    browser.evaluate("records=[];null")
    request, pending = c.request("input.performActions", {"context": context, "actions": [
        {"id": "held-key", "type": "key", "actions": [{"type": "keyDown", "key": "Control"}, {"type": "pause", "duration": 10000}]},
        {"id": "held-mouse", "type": "pointer", "actions": [{"type": "pause"}, {"type": "pointerMove", "x": 100, "y": 100, "duration": 10000}]},
    ]})
    eventually(lambda: browser.evaluate("records.some(e=>e.type==='keydown'&&e.key==='Control')"))
    c.call("control.cancel", {"request": request})
    expect_error("cancelled", lambda: pending.result(5))
    c.call("input.releaseActions", {"context": context})
    with ControlClient(browser.endpoint, browser.token) as other:
        other.call("input.click", {"context": context, "x": 5, "y": 5})
    assert browser.evaluate("records.filter(e=>e.type==='click').at(-1).ctrl") is False
    report["cancelledInputReleased"] = True

    c.call("network.enable", {"contexts": [context]})
    with ControlClient(browser.endpoint, browser.token) as interceptor:
        interceptor.call("network.addIntercept", {"contexts": [context], "urlPatterns": [url + "data*"]})
        _, fetch = c.request("script.evaluate", {"context": context, "world": "main",
            "expression": "fetch('/data?disconnect').then(r=>r.text())"})
        blocked = wait_event(interceptor, "network.beforeRequestSent", lambda p: p["blocked"])
        expect_error("no such request", lambda: c.call("network.failRequest", {"request": blocked["request"]}))
    assert fetch.result(10)["value"] == "native-body-✓"
    rule = c.call("network.addIntercept", {"contexts": [context], "urlPatterns": [url + "data*"],
                                        "timeout": 250})["intercept"]
    _, fetch = c.request("script.evaluate", {"context": context, "world": "main",
        "expression": "fetch('/data?timeout').then(r=>r.text())"})
    wait_event(c, "network.interceptExpired")
    assert fetch.result(10)["value"] == "native-body-✓"
    c.call("network.removeIntercept", {"intercept": rule})
    rule = c.call("network.addIntercept", {"contexts": [context], "urlPatterns": [url + "data*"]})["intercept"]
    _, fetch = c.request("script.evaluate", {"context": context, "world": "main",
        "expression": "fetch('/data?continue').then(r=>r.text())"})
    blocked = wait_event(c, "network.beforeRequestSent", lambda p: p["blocked"] and "continue" in p["url"])
    expect_error("invalid argument", lambda: c.call("network.continueRequest",
        {"request": blocked["request"], "method": "GET\r\nBad"}))
    c.call("network.continueRequest", {"request": blocked["request"],
        "headers": [{"name": "X-Native-Control-Test", "value": "continued"}]})
    assert fetch.result(10)["value"] == "native-body-✓"
    _, fetch = c.request("script.evaluate", {"context": context, "world": "main",
        "expression": "fetch('/data?abort').then(()=>false,()=>true)"})
    blocked = wait_event(c, "network.beforeRequestSent", lambda p: p["blocked"] and "abort" in p["url"])
    c.call("network.failRequest", {"request": blocked["request"]})
    assert fetch.result(10)["value"] is True
    c.call("network.removeIntercept", {"intercept": rule})
    c.call("browsingContext.navigate", {"context": context, "url": url + "redirect"})
    assert browser.evaluate("location.search") == "?redirected"
    c.call("network.disable")
    report["networkCleanup"] = True
    report["finalDiagnostics"] = c.call("browser.getInfo", {"diagnostics": True})
    assert not any(name in uri for uri in report["finalDiagnostics"]["modules"]
                   for name in ("FrameTree", "PageAgent", "Runtime", "content/main.js"))
    report["contracts"] = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--mode", choices=["smoke", "persistence"], default="smoke")
    parser.add_argument("--config", type=Path, help="Fixed complete fingerprint JSON, for persistence mode")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    server = TestServer()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    report = {"binary": str(args.binary.resolve()), "debugProtocols": [],
              "headed": args.headed, "url": url, "mode": args.mode}
    browser = None
    try:
        config = {"disableTheming": True, "showcursor": False,
                  "canvas:seed": 123456789, "audio:seed": 234567891, "fonts:spacing_seed": 345678912}
        if args.mode == "smoke":
            config["window:profile"] = {"screen.width": 1920, "screen.height": 1080,
                                       "window.innerWidth": 777, "window.innerHeight": 555,
                                       "window.devicePixelRatio": 2}
            browser = Browser(args.binary, args.output, config, headed=args.headed,
                              preferences={"browser.zoom.full": True})
            report["launchArgs"] = browser.args
            run_smoke(browser, url, report)
            run_extended(browser, url, report)
            run_contracts(browser, url, report)
        else:
            if args.config:
                config = json.loads(args.config.read_text(encoding="utf-8"))
            else:
                config["window:profile"] = {"screen.width": 1920, "screen.height": 1080,
                    "window.innerWidth": 1280, "window.innerHeight": 800,
                    "window.outerWidth": 1280, "window.outerHeight": 900,
                    "window.screenX": 30, "window.screenY": 40, "window.devicePixelRatio": 1}
            save(args.output / "profile.config.json", config)
            values = []
            for index in range(3):
                browser = Browser(args.binary, args.output / f"run-{index}", config,
                                  profile=args.output / "fixed-profile", headed=args.headed)
                browser.client.call("browsingContext.navigate", {"context": browser.context, "url": url + "fingerprint"})
                value = eventually(lambda: browser.evaluate("window.fpResult || window.fpError"), timeout=60)
                assert isinstance(value, dict), value
                if args.headed and config.get("webgpu:enabled"):
                    assert value["gpu"]["adapter"], "Configured WebGPU adapter was not available"
                    assert value["webgl"]["supported"] and value["webgl2"]["supported"]
                save(args.output / f"fingerprint-{index}.json", value)
                values.append(value)
                browser.close()
                assert browser.normal_exit, "Fingerprint run did not close normally"
                browser = None
            assert values[0] == values[1] == values[2], "Full fixed-input fingerprints changed on restart"
            report["fullFingerprintSha256"] = hashlib.sha256(
                json.dumps(values[0], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            report["normalRestarts"] = 3
        report["passed"] = True
    except BaseException as error:
        report["passed"] = False
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
        print(report["traceback"], flush=True)
    finally:
        if browser:
            browser.close()
            report["normalExit"] = browser.normal_exit
            if report.get("passed") and not browser.normal_exit:
                report["passed"] = False
                report["error"] = "Browser did not shut down normally or left its endpoint file"
        report["serverReports"] = server.reports
        report["requests"] = server.requests_seen
        server.shutdown()
        save(args.output / "report.json", report)
    print(json.dumps({"passed": report["passed"], "report": str(args.output / "report.json")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
