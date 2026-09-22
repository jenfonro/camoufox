"""The CI entry point must run each guard with its actual CLI and platform."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ci import run_patch_guards as runner


@pytest.fixture
def harness(tmp_path, monkeypatch):
    scripts = tmp_path / "guards"
    scripts.mkdir()
    names = [
        "ordinary", "window-resolution-windows", "webgpu-windows",
        "fingerprint-persistence-windows", "fingerprint-seed-contexts", "helpers",
    ]
    for name in names:
        (scripts / f"{name}.py").write_text("", encoding="utf-8")
    binary = tmp_path / "browser" / "camoufox.exe"
    binary.parent.mkdir()
    binary.touch()
    evidence = tmp_path / "results"
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    calls = []
    failures = set()

    def run(command, **kwargs):
        calls.append((command, kwargs))
        failed = Path(command[1]).stem in failures
        return SimpleNamespace(
            ok=not failed, code=2 if failed else 0,
            combined=lambda: "guard failed" if failed else "",
        )

    monkeypatch.setattr(runner, "GUARD_DIR", scripts)
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(
        runner, "sys", SimpleNamespace(executable=sys.executable, platform="win32")
    )
    args = [
        "--binary", str(binary), "--evidence-dir", str(evidence),
        "--seed-profile", str(profile),
    ]
    return SimpleNamespace(
        args=args, binary=binary, evidence=evidence, profile=profile,
        calls=calls, failures=failures,
        report=lambda: json.loads((evidence / "patch_guards.json").read_text()),
    )


def test_windows_dispatch_preserves_all_standalone_arguments(harness):
    assert runner.main(harness.args) == 0
    commands = {Path(cmd[1]).stem: cmd[2:] for cmd, _ in harness.calls}
    output = harness.evidence / "patch-output"
    assert set(commands) == {
        "ordinary", "window-resolution-windows", "webgpu-windows",
        "fingerprint-persistence-windows", "fingerprint-seed-contexts",
    }
    assert commands["ordinary"] == []
    assert commands["window-resolution-windows"] == [
        "--executable", str(harness.binary),
        "--report-dir", str(output / "window-resolution-windows"),
    ]
    for name in ("webgpu-windows", "fingerprint-persistence-windows"):
        assert commands[name] == [str(harness.binary), "--output", str(output / name)]
    assert commands["fingerprint-seed-contexts"] == [
        str(harness.binary), "--config", str(harness.profile), "--output",
        str(output / "fingerprint-seed-contexts" / "results.json"),
    ]
    for _, kwargs in harness.calls:
        assert kwargs["env"]["CAMOUFOX_EXECUTABLE_PATH"] == str(harness.binary)
    assert harness.report()["metrics"]["tally"] == {"pass": 5, "total": 5}


def test_linux_runs_context_guard_and_records_windows_skips(harness, monkeypatch):
    monkeypatch.setattr(
        runner, "sys", SimpleNamespace(executable=sys.executable, platform="linux")
    )
    assert runner.main(harness.args) == 0
    assert {Path(cmd[1]).stem for cmd, _ in harness.calls} == {
        "ordinary", "fingerprint-seed-contexts",
    }
    report = harness.report()
    assert report["metrics"]["tally"] == {"pass": 2, "skip": 3, "total": 5}
    assert report["tests"]["patches/webgpu-windows.py"] == "skip"


def test_explicit_selection_cannot_pass_without_running_anything(harness, monkeypatch):
    monkeypatch.setattr(
        runner, "sys", SimpleNamespace(executable=sys.executable, platform="linux")
    )
    assert runner.main(harness.args + ["--only", "webgpu-windows"]) == 1
    assert not harness.calls
    assert harness.report()["status"] == "error"


def test_unknown_selection_does_not_silently_drop_coverage(harness):
    assert runner.main(harness.args + ["--only", "ordinary", "misspelled"]) == 1
    assert not harness.calls
    assert harness.report()["status"] == "error"


def test_failing_guard_is_reported_and_remaining_guards_still_run(harness):
    harness.failures.add("webgpu-windows")
    assert runner.main(harness.args) == 1
    report = harness.report()
    assert report["status"] == "fail"
    assert report["metrics"]["tally"] == {"pass": 4, "fail": 1, "total": 5}
    assert len(harness.calls) == 5
