# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.45", "httpx>=0.27", "html2text>=2024.2", "mcp>=1.2,<2", "pypdf>=4", "tzdata"]
# ///
"""Legacy entry point: `uv run mcp_server.py`. Same as `dtu-learn mcp`; data in this folder unless DTU_LEARN_HOME is set."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent / "src"))
os.environ.setdefault("DTU_LEARN_HOME", str(HERE.parent))
os.environ.setdefault("DTU_LEARN_SHIM", str(HERE.parent / "dtu_learn.py"))

from dtulearn.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
