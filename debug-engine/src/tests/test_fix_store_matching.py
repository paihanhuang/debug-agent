from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.fix_store import FixStore, HistoricalFix


def test_fix_store_root_cause_substring_matching(tmp_path: Path) -> None:
    db = tmp_path / "fixes.db"
    store = FixStore(db)
    try:
        store.add_fix(
            HistoricalFix(
                case_id="c1",
                root_cause="CM",
                symptom_summary="high vcore",
                metrics={"VCORE": "82.6%"},
                fix_description="Adjust CM policy.",
            )
        )

        # Query label is longer than stored root cause
        fixes = store.get_fixes_by_root_cause("CM causing VCORE increase")
        assert len(fixes) == 1
        assert fixes[0].root_cause == "CM"

        # Query label is shorter than stored root cause
        store.add_fix(
            HistoricalFix(
                case_id="c2",
                root_cause="PowerHal voting issue",
                symptom_summary="",
                metrics={},
                fix_description="Check PowerHal votes.",
            )
        )
        fixes2 = store.get_fixes_by_root_cause("PowerHal")
        assert any(f.case_id == "c2" for f in fixes2)
    finally:
        store.close()

