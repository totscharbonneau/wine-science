"""Wine science project package."""

from pathlib import Path

# Project root: the directory that contains `src/`. Defined once here so modules
# can import it and never depend on their own depth in the tree.
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
