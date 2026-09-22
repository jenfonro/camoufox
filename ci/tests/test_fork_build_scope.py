"""Execute the workflow's source-selection branch without building or fetching."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    "event,repository,changed,expected",
    [
        ("workflow_dispatch", "jenfonro/camoufox", "README.md", "true"),
        ("pull_request", "jenfonro/camoufox", "pythonlib/camoufox/utils.py", "true"),
        ("pull_request", "daijro/camoufox", "pythonlib/camoufox/utils.py", "false"),
        ("pull_request", "camoufox/camoufox", "pythonlib/camoufox/utils.py", "false"),
        ("pull_request", "daijro/camoufox", "patches/example.patch", "true"),
    ],
)
def test_build_scope_uses_fork_sources(event, repository, changed, expected):
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/tests.yml"
    config = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    scope = next(step["run"] for step in config["jobs"]["resolve"]["steps"]
                 if step.get("id") == "scope")
    scope = scope.replace("${{ github.event_name }}", event)
    scope = scope.replace("${{ github.repository }}", repository)
    scope = scope.replace("${{ github.event.pull_request.base.sha }}", "base")
    # Read the action outputs on stdout; the git stub supplies only a filename,
    # so neither test repositories nor external services are needed.
    scope = scope.replace(' >> "$GITHUB_OUTPUT"', "")
    git_stub = "git() { printf '%s\\n' '" + changed + "'; }\n"
    bash = os.environ.get("CAMOUFOX_TEST_BASH") or shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to execute the workflow's shell")
    proc = subprocess.run(
        [bash, "-c", git_stub + scope], capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    outputs = [line for line in proc.stdout.splitlines() if line.startswith("browser_changed=")]
    assert outputs == [f"browser_changed={expected}"]
