"""Console entry point for `uv run fnt-demo`."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fnt_demo import main as _main


def main() -> None:
    raise SystemExit(_main())


if __name__ == "__main__":
    main()
