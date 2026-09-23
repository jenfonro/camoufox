"""Guard the native control path independently of Playwright and WebDriver."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
binary = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
if not binary:
    raise SystemExit("CAMOUFOX_EXECUTABLE_PATH must name the explicitly built binary")
raise SystemExit(subprocess.call([
    sys.executable, str(root / "tests/native-control/verify.py"),
    "--binary", binary, "--output", str(root / ".ci-work/native-control"),
], cwd=root))
