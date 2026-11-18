import os
import sys
import tempfile
from pathlib import Path

# Isolated DB and fake provider for every test run; never touch the dev DB or the network.
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["LLM_PROVIDER"] = "fake"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
