import shutil
import subprocess
from pathlib import Path

import pytest


def test_streamed_text_chunks_are_rendered_as_one_assistant_bubble():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is optional for UI behavior tests")
    assert node is not None
    script = Path(__file__).with_suffix(".js")
    result = subprocess.run(
        [node, "--test", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
