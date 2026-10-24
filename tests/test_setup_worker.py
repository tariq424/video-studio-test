"""The laptop setup script: bash syntax and every embedded Python snippet must parse (a broken heredoc stopped a real run)."""
import re
import shutil
import subprocess
from pathlib import Path

SH = Path(__file__).resolve().parents[1] / "scripts" / "linux" / "setup-worker.sh"


def test_python_heredocs_compile():
    s = SH.read_text(encoding="utf-8")
    blocks = re.findall(r"python3 - [^\n]*<<'PY'\n(.*?)\nPY\n", s, re.S)
    assert len(blocks) == s.count("<<'PY'") and blocks
    for b in blocks: compile(b, "setup-worker.sh heredoc", "exec")


def test_bash_syntax():
    if shutil.which("bash"): assert subprocess.run(["bash", "-n", str(SH)]).returncode == 0
