import shutil
import subprocess
from pathlib import Path


def test_live_chat_markdown_drafts_and_input_handling():
    node = shutil.which("node")
    if node is None:
        return
    script = Path(__file__).with_suffix(".js")
    result = subprocess.run(
        [node, "--test", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
