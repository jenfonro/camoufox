"""Keep address masking from corrupting SDP or DTLS fingerprints."""

import argparse
import ipaddress
import json
from pathlib import Path
import re
import traceback

from verify import Browser, save


PROBE = r"""(async (explicitOrigin) => {
  const pc = new RTCPeerConnection({iceServers: []});
  const candidates = [];
  let timer, offer;
  try {
    const complete = new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error("ICE gathering timed out")), 15000);
      pc.onicecandidate = event => {
        if (event.candidate) candidates.push({...event.candidate.toJSON(),
          address: event.candidate.address, relatedAddress: event.candidate.relatedAddress});
        else resolve();
      };
    });
    pc.createDataChannel("sdp-regression");
    pc.addTransceiver("audio", {direction: "recvonly"});
    pc.addTransceiver("video", {direction: "recvonly"});
    offer = await pc.createOffer();
    if (explicitOrigin) {
      offer.sdp = offer.sdp.replace(/^o=(.+) IN IP4 [^\r\n]+/m,
        "o=$1 IN IP6 " + explicitOrigin);
    }
    await pc.setLocalDescription(offer);
    await complete;
    const stats = [...(await pc.getStats()).values()]
      .filter(item => item.type === "local-candidate" || item.type === "remote-candidate");
    return {offer, sdp: pc.localDescription.sdp, candidates, stats};
  } catch (error) {
    return {offer, error: String(error)};
  } finally {
    clearTimeout(timer);
    pc.close();
  }
})"""


def verify(report, masks, explicit_origin=None):
    assert "error" not in report, report.get("error")
    sdp = report["sdp"]
    assert sdp.endswith("\r\n") and len(sdp.split("\r\n")) > 5
    assert "\r" not in sdp.replace("\r\n", "") and "\n" not in sdp.replace("\r\n", "")

    def fingerprints(value):
        return [line for line in value.split("\r\n") if line.startswith("a=fingerprint:")]

    original = fingerprints(report["offer"]["sdp"])
    assert original and fingerprints(sdp) == original, "DTLS fingerprint changed"
    if explicit_origin:
        origin = next(line for line in sdp.split("\r\n") if line.startswith("o="))
        expected = masks.get("webrtc:ipv6", explicit_origin)
        assert origin.endswith(" IN IP6 " + expected), f"Invalid masked origin: {origin}"
    assert report["candidates"] and report["stats"], "No ICE candidates were observed"
    if not masks:
        return
    for surface in ("candidates", "sdp", "stats"):
        text = json.dumps(report[surface])
        assert any(mask in text for mask in masks.values()), f"{surface} contains no masked address"
        for field in re.split(r'[\s",{}\[\]\\]+', text.replace(r"\r\n", " ")):
            try:
                address = ipaddress.ip_address(field)
            except ValueError:
                continue
            assert address.is_unspecified or str(address) in masks.values(), (
                f"{surface} exposed unmasked address {address}"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"binary": str(args.binary), "cases": {}, "passed": False}
    browser = None
    masks = {"webrtc:ipv4": "8.8.8.8", "webrtc:ipv6": "2001:4860:4860::8888"}
    try:
        for name, config, origin in (
            ("default", {}, None),
            ("explicit-ipv6-default", {}, "2001:db8:1234::5678"),
            ("both-addresses", masks, None),
            ("explicit-ipv6-masked", masks, "2001:db8:1234::5678"),
            ("mapped-ipv6-masked", masks, "::ffff:198.51.100.12"),
        ):
            browser = Browser(
                args.binary, args.output / name, config=config,
                preferences={"media.peerconnection.enabled": True},
            )
            value = browser.evaluate(PROBE + "(" + json.dumps(origin) + ")")
            report["cases"][name] = value
            save(args.output / "report.json", report)
            verify(value, config, origin)
            browser.close()
            assert browser.normal_exit, "Browser did not exit normally"
            browser = None
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
        print(report["error"], flush=True)
    finally:
        if browser:
            browser.close()
        save(args.output / "report.json", report)
    print(json.dumps({"passed": report["passed"], "report": str(args.output / "report.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
