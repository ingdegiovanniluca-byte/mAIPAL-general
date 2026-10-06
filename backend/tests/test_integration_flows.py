"""Runs every tests/integration/it_*.py script (fake in-memory MongoDB, simulated AI models)
as its own process: each one exercises a whole flow - lists, search, task/to-do, actions,
watch... - and prints "ALL OK" when all its checks pass. They guard the general features
while the verticals are built on top of them."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = sorted((HERE / "integration").glob("it_*.py"))


@pytest.mark.parametrize("script", SCRIPTS, ids=[s.stem for s in SCRIPTS])
def test_flow(script):
    env = {**os.environ, "MONGO_URL": "mongodb://x", "DB_NAME": "t", "OPENAI_API_KEY": "x"}
    proc = subprocess.run([sys.executable, str(script)], cwd=HERE.parent, env=env,
                          capture_output=True, text=True, timeout=600)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0 and "ALL OK" in proc.stdout, out[-4000:]
