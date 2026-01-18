from __future__ import annotations

import sys
from pathlib import Path

# Ensure tests can import `ckg_augment` when running pytest from repo root.
THIS = Path(__file__).resolve()
CKG_AUGMENT_ROOT = THIS.parents[1]  # .../ckg-augment
REPO_ROOT = THIS.parents[2]        # .../inference-engine

sys.path.insert(0, str(CKG_AUGMENT_ROOT))
sys.path.insert(0, str(REPO_ROOT))

