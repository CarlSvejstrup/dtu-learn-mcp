# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.45", "httpx>=0.27", "html2text>=2024.2", "mcp>=1.2,<2", "pypdf>=4", "tzdata"]
# ///
"""Legacy entry point: `uv run dtu_learn.py <command>` from a checkout of this repo.

Same as the `dtu-learn` command. Data stays in this folder (DTU_LEARN_HOME = repo) unless you set DTU_LEARN_HOME.
New installs: `uv tool install git+https://github.com/CarlSvejstrup/dtu-learn-mcp`, then `dtu-learn setup`.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent / "src"))
os.environ.setdefault("DTU_LEARN_HOME", str(HERE.parent))
os.environ.setdefault("DTU_LEARN_SHIM", str(HERE))

from dtulearn.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
