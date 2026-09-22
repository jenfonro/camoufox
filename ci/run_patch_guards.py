#!/usr/bin/env python3
"""Patch-guard gate: tests/patches/*.py, one standalone guard per shipped behaviour.

These are the assertions that each spoofing patch still does what it claims --
isolated evaluate, trusted events, font spoofing, mouse trajectories and so on.
They are the most direct evidence that a Firefox bump did not quietly neuter a
patch that still applies cleanly, which is the failure mode a compile check
cannot catch.

Each guard is a standalone script exiting 0 or 1. Policy allows zero failures.

Run:
    python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import results as evidence
from ._util import EVIDENCE_DIR, REPO_ROOT, log, run

GUARD_DIR = REPO_ROOT / "tests" / "patches"
SEED_PROFILE = GUARD_DIR / "assets" / "fingerprint-seed-profile.json"
WINDOWS_GUARDS = {
    "window-resolution-windows",
    "webgpu-windows",
    "fingerprint-persistence-windows",
}


def guards() -> List[Path]:
    """Every guard script. helpers.py is a library, not a guard."""
    return sorted(p for p in GUARD_DIR.glob("*.py") if p.name != "helpers.py")


def guard_command(
    guard: Path, binary: Path, output: Path, seed_profile: Path
) -> List[str]:
    """Keep each standalone guard's public CLI when running it through CI."""
    command = [sys.executable, str(guard)]
    if guard.stem == "window-resolution-windows":
        return command + ["--executable", str(binary), "--report-dir", str(output)]
    if guard.stem in {"webgpu-windows", "fingerprint-persistence-windows"}:
        return command + [str(binary), "--output", str(output)]
    if guard.stem == "fingerprint-seed-contexts":
        return command + [
            str(binary), "--config", str(seed_profile),
            "--output", str(output / "results.json"),
        ]
    return command


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--timeout", type=int, default=600, help="per guard")
    parser.add_argument("--only", nargs="*", help="run only these guard names")
    parser.add_argument(
        "--seed-profile", type=Path, default=SEED_PROFILE,
        help="fixed config for the font/audio context guard",
    )
    args = parser.parse_args(argv)

    from ._pytest import built_binary

    result = evidence.GateResult(gate="patch_guards")
    binary = (args.binary or built_binary()).resolve()
    if not binary.exists():
        result.note(f"no built binary at {binary}")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    env = {
        "CAMOUFOX_EXECUTABLE_PATH": str(binary),
        # The guards drive the browser through the Python package, which resolves
        # the binary from this variable rather than a packaged install.
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(REPO_ROOT / "pythonlib"), os.environ.get("PYTHONPATH", "")])
        ),
    }

    available = guards()
    unknown = set(args.only or ()) - {g.stem for g in available}
    if unknown:
        result.note(f"unknown guard names: {', '.join(sorted(unknown))}")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1
    selected = [g for g in available if not args.only or g.stem in args.only]
    if not selected:
        result.note("no guards found -- tests/patches/ is empty or the filter matched nothing")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    failed: List[str] = []
    executed = 0
    skipped = 0
    output_root = args.evidence_dir.resolve() / "patch-output"
    seed_profile = args.seed_profile.resolve()
    for guard in selected:
        if guard.stem in WINDOWS_GUARDS and sys.platform != "win32":
            result.record(f"patches/{guard.name}", evidence.SKIP)
            result.note(f"{guard.name} requires Windows; current platform is {sys.platform}")
            skipped += 1
            continue
        command = guard_command(guard, binary, output_root / guard.stem, seed_profile)
        executed += 1
        proc = run(command, cwd=REPO_ROOT, env=env, timeout=args.timeout)
        outcome = evidence.PASS if proc.ok else evidence.FAIL
        result.record(f"patches/{guard.name}", outcome)
        if not proc.ok:
            failed.append(guard.name)
            tail = proc.combined().strip().splitlines()[-6:]
            result.note(f"{guard.name} failed ({proc.code}): " + " | ".join(t.strip() for t in tail))
        else:
            log(f"  ✓ {guard.name}")

    passed = executed - len(failed)
    result.note(f"{passed}/{executed} executed guards passed; {skipped} not applicable")
    if executed == 0:
        result.note("no applicable guard ran; this does not establish a passing result")
        status = evidence.ERROR
    else:
        status = evidence.PASS if not failed else evidence.FAIL
    result.finish(status).save(args.evidence_dir)
    return 0 if status == evidence.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
