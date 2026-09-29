from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parent
FIXTURES = REPO / "tests" / "fixtures"
SAMPLES = TOOLS / "splitter" / "samples"
sys.path.insert(0, str(TOOLS))


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
