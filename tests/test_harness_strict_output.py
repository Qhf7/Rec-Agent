"""Exercise the native Harness output boundary through Node's test runner."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_native_harness_output_boundary():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the native Harness plugin tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "rec-agent-preset/strict-output.test.js"],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
