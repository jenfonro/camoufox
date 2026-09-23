"""Verify pre-authentication page state, reconnect and simultaneous instances."""
import argparse
import json
from pathlib import Path
import threading
import traceback

from verify import Browser, ControlClient, TestServer, eventually, expect_error, save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    server = TestServer()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    browser = other = None
    report = {"binary": str(args.binary), "debugProtocols": []}
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        config = {"disableTheming": True, "showcursor": False,
                  "window:profile": {"window.innerWidth": 777, "window.innerHeight": 555}}
        browser = Browser(args.binary, args.output / "first", config, connect=False, initial_url=url)
        before = json.loads(eventually(lambda: next((s for s in server.reports if '"startup"' in s), None)))["startup"]
        browser.client = ControlClient(browser.endpoint, browser.token)
        browser.context = browser.client.call("browsingContext.getTree")["contexts"][0]["context"]
        eventually(lambda: browser.evaluate("typeof pageReport==='function'"))
        connected = browser.evaluate("pageReport()")
        assert connected == before, (before, connected)
        first = browser.client.call("browser.getInfo", {"diagnostics": True})
        assert all(not c["jugglerActor"] and not c["overrideHasFocus"] and not c["forceActiveState"]
                   and not c["disallowBFCache"] for c in first["contexts"])
        browser.client.close()
        assert browser.process.poll() is None
        browser.client = ControlClient(browser.endpoint, browser.token)
        reconnected = browser.evaluate("pageReport()")
        assert before == reconnected, (before, reconnected)
        assert before["controls"] == [] and before["webdriver"] is False
        report.update(beforeAuthentication=before, connected=connected, reconnected=reconnected,
                      diagnostics=first, launchArgs=browser.args)

        other = Browser(args.binary, args.output / "second", config)
        second = other.client.call("browser.getInfo")
        assert first["processId"] != second["processId"]
        assert browser.client.connection["instance"] != other.client.connection["instance"]
        expect_error("authentication failed", lambda: ControlClient(other.endpoint, browser.token))
        assert browser.evaluate("document.title") == "Native control test"
        other.close()
        assert other.normal_exit
        assert browser.process.poll() is None
        other = None
        report["multipleInstances"] = {"first": first["processId"], "second": second["processId"]}
        browser.close()
        assert browser.normal_exit
        browser = None
        report["passed"] = True
    except BaseException:
        report["passed"] = False
        report["error"] = traceback.format_exc()
        print(report["error"], flush=True)
    finally:
        if other:
            other.close()
        if browser:
            browser.close()
        server.shutdown()
        save(args.output / "report.json", report)
    print(json.dumps({"passed": report["passed"], "report": str(args.output / "report.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
