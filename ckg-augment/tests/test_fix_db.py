from __future__ import annotations

import sqlite3
from pathlib import Path

from ckg_augment.fix_db import FixRecord, copy_or_init_base_fix_db, stable_fix_case_id, upsert_fixes


def _count_rows(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM historical_fixes")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _get_columns(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("PRAGMA table_info(historical_fixes)")
        return [row[1] for row in cur.fetchall()]
    finally:
        conn.close()


def test_fix_db_init_and_schema(tmp_path: Path) -> None:
    out = tmp_path / "fixes.db"
    copy_or_init_base_fix_db(base_db=None, out_db=out)
    cols = _get_columns(out)
    # Must be compatible with debug-engine FixStore schema
    for required in [
        "id",
        "case_id",
        "root_cause",
        "symptom_summary",
        "metrics_json",
        "fix_description",
        "resolution_notes",
        "created_at",
    ]:
        assert required in cols


def test_fix_db_upsert_and_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "fixes.db"
    copy_or_init_base_fix_db(base_db=None, out_db=out)

    f1 = FixRecord(
        case_id=stable_fix_case_id(report_id="r1", root_cause="CM", fix_description="Adjust CM policy"),
        root_cause="CM",
        symptom_summary="High VCORE 725mV usage with DDR voting",
        metrics={"VCORE 725mV": "29.32%"},
        fix_description="Adjust CM policy to reduce ceiling votes.",
    )
    diff1 = upsert_fixes(out, [f1])
    assert len(diff1.inserted_case_ids) == 1
    assert _count_rows(out) == 1

    # Apply again should replace same case_id, not add a new row
    diff2 = upsert_fixes(out, [f1])
    assert len(diff2.replaced_case_ids) == 1
    assert _count_rows(out) == 1


def test_fix_db_copy_base_and_merge(tmp_path: Path) -> None:
    base = tmp_path / "base.db"
    copy_or_init_base_fix_db(base_db=None, out_db=base)
    f1 = FixRecord(
        case_id=stable_fix_case_id(report_id="r1", root_cause="CM", fix_description="Adjust CM policy"),
        root_cause="CM",
        symptom_summary="s",
        metrics={},
        fix_description="Adjust CM policy.",
    )
    upsert_fixes(base, [f1])
    assert _count_rows(base) == 1

    out = tmp_path / "out.db"
    copy_or_init_base_fix_db(base_db=base, out_db=out)
    assert _count_rows(out) == 1

    f2 = FixRecord(
        case_id=stable_fix_case_id(report_id="r2", root_cause="MMDVFS", fix_description="Investigate OPP3 floor"),
        root_cause="MMDVFS",
        symptom_summary="VCORE floor stuck at 600mV",
        metrics={"VCORE floor": "600mV"},
        fix_description="Investigate why MMDVFS stays at OPP3 and adjust policy if needed.",
    )
    upsert_fixes(out, [f2])
    assert _count_rows(out) == 2

