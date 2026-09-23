"""Full BrowserScan reports across normal restarts, controlled only by native IPC.

The optional settled mode preserves the initial report, waits for the site's
own UI, and uses its visible Check again button once on every navigation. It is
separate from strict first-report comparison; no identity hash is exempted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import traceback

from verify import Browser, eventually, save

LABELS = (
    "visitor ID", "Canvas", "WebGL", "WebGL Report", "Unmasked Vendor", "Unmasked Renderer",
    "Audio", "Client Rects", "WebGPU Report", "Screen Resolution", "Available Screen Size",
    "Color Depth", "Touch Support", "Hardware Concurrency", "Media devices", "Incognito mode",
    "OS", "Browser", "Browser Version", "Header", "JavaScript", "Time Zone", "Languages",
    "Accept-Language header", "Internationalization API", "Do Not Track", "Javascript",
    "Flash", "ActiveX", "Java", "Cookie", "Fonts",
)
HASH_FIELDS = {
    "Canvas": ("hardware", "canvasHash"), "WebGL": ("hardware", "webGLHash"),
    "WebGL Report": ("hardware", "webGLReportHash"), "Audio": ("hardware", "audioHash"),
    "Client Rects": ("hardware", "clientRectHash"), "WebGPU Report": ("hardware", "webGPUHash"),
    "visitor ID": ("hardware", "visitorId"), "Fonts": ("software", "fontsHash"),
}
SNAPSHOT = r"""(() => {
  const root=document.getElementById('browserscan');
  const app=root?.__vue_app__ || root?.__vueParentComponent?.appContext?.app;
  const state=app?.config?.globalProperties?.$nuxt?.payload?.state;
  const cells={},rawCells={},excludedAds={};
  for(const cell of document.querySelectorAll('div._11xj7yu')){
    const label=cell.querySelector('h3')?.textContent.trim();
    if(!label)continue;
    const value=cell.lastElementChild;
    rawCells[label]=value.innerText.trim();
    const ads=Array.from(value.querySelectorAll('.google-anno-skip.google-anno-sc'));
    const styles=ads.map(ad=>ad.getAttribute('style'));
    if(ads.length)excludedAds[label]=ads.map(ad=>ad.innerText);
    try{
      for(const ad of ads)ad.style.setProperty('display','none','important');
      cells[label]=value.innerText.trim();
    }finally{
      ads.forEach((ad,i)=>styles[i]===null?ad.removeAttribute('style'):ad.setAttribute('style',styles[i]));
    }
  }
  return {cells,rawCells,excludedAds,state,text:document.body.innerText,
    chromeTag:window.chrome?.tagName,chromeIsNamedElement:window.chrome===document.getElementById('chrome')};
})()"""


def capture(browser, path):
    latest = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        latest = browser.evaluate(SNAPSHOT)
        if all(re.search(r"[0-9a-fA-F]{8}", latest["cells"].get(label, "")) for label in HASH_FIELDS):
            break
        time.sleep(.5)
    save(path, latest)
    assert latest and latest.get("state"), "BrowserScan report did not initialize; raw report saved"
    state = {key.removeprefix("$s"): value for key, value in latest["state"].items()}
    stable = {"cells": {}, "hashes": {}}
    for label in LABELS:
        assert label in latest["cells"], f"Missing identity field: {label}"
        stable["cells"][label] = latest["cells"][label]
    for label, (section, key) in HASH_FIELDS.items():
        value = state[section][key]
        assert re.fullmatch(r"[0-9a-fA-F]{32,128}", value), (label, value)
        assert value[:8].upper() in latest["cells"][label].upper(), (label, value)
        stable["hashes"][label] = value  # The complete value is compared.
    stable["fontsList"] = state["software"]["fontsList"]
    stable["webGPU"] = state["hardware"]["webGPU"]
    save(path.with_name(path.stem + "-identity.json"), stable)
    return stable


def ready(browser):
    latest = browser.evaluate(SNAPSHOT)
    complete = latest.get("state", {}).get("$scomplete", {})
    return latest if complete and all(complete.values()) and latest.get("chromeIsNamedElement") and latest.get("chromeTag") == "symbol" else None


def details(browser, root):
    results = {}
    for page, marker in [("canvas", "Canvas Fingerprint"), ("webgpu", "WebGPU Report Hash")]:
        browser.client.call("browsingContext.navigate", {"context": browser.context,
            "url": "https://www.browserscan.net/" + page}, timeout=60)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            value = browser.evaluate("""({text:document.body.innerText,
                tables:Array.from(document.querySelectorAll('table'),t=>Array.from(t.rows,r=>Array.from(r.cells,c=>c.innerText))),
                images:Array.from(document.images).filter(i=>i.src.startsWith('data:image/png')).map(i=>i.src)})""")
            hashes = [line.strip() for line in value["text"].splitlines()
                      if re.fullmatch(r"[0-9a-fA-F]{32,128}", line.strip())]
            if marker in value["text"] and hashes:
                break
            time.sleep(.5)
        save(root / f"{page}-detail.json", value)
        assert hashes and marker in value["text"], f"Missing detail hash: {page}"
        results[page] = {"hash": hashes[0], "tables": value["tables"], "images": value["images"]}
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--settled", action="store_true")
    args = parser.parse_args()
    assert args.iterations >= 3, "Acceptance requires at least three normal restarts"
    args.output.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    save(args.output / "profile.config.json", config)
    report = {"binary": str(args.binary), "transport": "native-control", "debugProtocols": [],
              "iterations": args.iterations, "settledAfterVisibleRecheck": args.settled,
              "comparedIdentityFields": LABELS, "runs": []}
    browser = None
    try:
        for index in range(args.iterations):
            root = args.output / f"run-{index + 1}"
            browser = Browser(args.binary, root, config, args.output / "fixed-profile",
                headed=args.headed, preferences={"intl.accept_languages": "en-US,en", "intl.locale.requested": "en-US"})
            browser.client.call("browsingContext.navigate", {"context": browser.context,
                "url": "https://www.browserscan.net/"}, timeout=60)
            initial = capture(browser, root / "initial.json")
            if args.settled:
                before = eventually(lambda: ready(browser), timeout=60)
                button = browser.query('svg:has(use[*|href="#refresh"])')[0]["node"]
                browser.client.call("input.click", {"context": browser.context, "node": button})
                after = eventually(lambda: ready(browser), timeout=60)
                save(root / "load-state.json", {"before": before, "after": after})
            value = capture(browser, root / "home.json")
            detail = details(browser, root)
            report["runs"].append({"hashes": value["hashes"], "initialHashes": initial["hashes"],
                                   "launchArgs": browser.args})
            if index == 0:
                baseline, detail_baseline = value, detail
            else:
                assert value == baseline, "Complete BrowserScan identity report changed on restart"
                assert detail == detail_baseline, "Full detail hash/table/image data changed on restart"
            browser.close()
            assert browser.normal_exit, "Browser did not shut down normally"
            browser = None
            print(json.dumps({"run": index + 1, "passed": True, "hashes": value["hashes"]}), flush=True)
        report["fullIdentitySha256"] = hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
        report["initialHashesEqual"] = all(item["initialHashes"] == report["runs"][0]["initialHashes"] for item in report["runs"])
        report["passed"] = True
    except BaseException:
        report["passed"] = False
        report["error"] = traceback.format_exc()
        print(report["error"], flush=True)
    finally:
        if browser:
            browser.close()
        save(args.output / "report.json", report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
