"""CLI entrypoint for the Nomadomics engine.

Usage (from repo root or engine dir):
  python -m engine.cli next
  python -m engine.cli draft-one <slug>
  python -m engine.cli run-batch [N]
  python -m engine.cli drafts
  python -m engine.cli info
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the engine package is importable when run from the repo root.
_ENGINE_DIR = Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from pipeline_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
