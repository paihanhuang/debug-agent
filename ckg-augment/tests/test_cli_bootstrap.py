from __future__ import annotations

import json
from pathlib import Path

from ckg_augment.augmenter import load_or_init_ckg


def test_load_or_init_ckg_init_empty(tmp_path: Path) -> None:
    g = load_or_init_ckg(None, init_empty=True)
    assert g is not None
    assert len(g.get_entities()) == 0


def test_load_or_init_ckg_requires_input() -> None:
    try:
        load_or_init_ckg(None, init_empty=False)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Use --ckg or --init-empty" in str(e)

