from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ckg_augment.report_archive import (
    ArchiveInputs,
    archive_report_and_query,
    parse_combined_report,
    upsert_bundle_index,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_parse_combined_report_extracts_human_and_query() -> None:
    raw = "human line\n---\nE2E Test Query (judgement-free):\nA=1\nB=2\n"
    human, query = parse_combined_report(raw)
    assert human == "human line"
    assert query == "A=1\nB=2"


def test_archive_stores_raw_report_and_raw_query_and_is_dedup_no_overwrite(tmp_path: Path) -> None:
    library = tmp_path / "report_library"
    report_id = "case1"
    raw_report = "human\n---\nE2E Test Query (judgement-free):\nVCORE 82.6%\n"
    human, parsed_query = parse_combined_report(raw_report)
    assert parsed_query is not None

    inputs = ArchiveInputs(
        report_id=report_id,
        raw_report_text=raw_report,
        raw_debug_query_text=parsed_query,
        source_report_path="/abs/data/first",
        source_query_path=None,
        query_source="parsed_from_report",
        parsed_human_report=human,
        parsed_debug_query=parsed_query,
    )

    meta1 = {"k": 1}
    res1 = archive_report_and_query(library_root=library, inputs=inputs, meta=meta1, no_overwrite=True)
    assert res1.bundle_dir.exists()
    assert _read(res1.bundle_dir / "raw_report_input.txt") == raw_report
    assert _read(res1.bundle_dir / "raw_debug_query.txt") == parsed_query
    assert _read(res1.bundle_dir / "meta.json") == json.dumps(meta1, indent=2, ensure_ascii=False)

    # Second time: should not overwrite bundle files
    meta2 = {"k": 2}
    res2 = archive_report_and_query(library_root=library, inputs=inputs, meta=meta2, no_overwrite=True)
    assert res2.existed is True
    assert res2.bundle_id == res1.bundle_id
    assert _read(res2.bundle_dir / "meta.json") == json.dumps(meta1, indent=2, ensure_ascii=False)


def test_archive_with_explicit_query_stores_raw_query_and_keeps_parsed_debug_query(tmp_path: Path) -> None:
    library = tmp_path / "report_library"
    raw_report = "human\n---\nE2E Test Query (judgement-free):\nFROM_REPORT\n"
    human, parsed_query = parse_combined_report(raw_report)
    assert parsed_query == "FROM_REPORT"

    explicit_query = "EXPLICIT_QUERY"
    inputs = ArchiveInputs(
        report_id="r",
        raw_report_text=raw_report,
        raw_debug_query_text=explicit_query,
        source_report_path="/abs/data/x",
        source_query_path="/abs/prompt.txt",
        query_source="explicit_file",
        parsed_human_report=human,
        parsed_debug_query=parsed_query,
    )
    res = archive_report_and_query(library_root=library, inputs=inputs, meta={"x": 1}, no_overwrite=True)
    assert _read(res.bundle_dir / "raw_debug_query.txt") == explicit_query
    assert _read(res.bundle_dir / "parsed_debug_query.txt") == "FROM_REPORT"


def test_bundle_index_upsert(tmp_path: Path) -> None:
    library = tmp_path / "report_library"
    db = library / "report_index.db"
    bundle_path = library / "bundles" / "b1"
    bundle_path.mkdir(parents=True)

    upsert_bundle_index(
        db_path=db,
        bundle_id="b1",
        report_sha256="r" * 64,
        query_sha256="q" * 64,
        bundle_path=bundle_path,
        report_id="case1",
        source_report_path="/abs/data/first",
        source_query_path="/abs/prompt.txt",
        query_source="explicit_file",
        run_id="run1",
        case_num=1,
        iter_num=1,
        ckg_in_path=None,
        ckg_out_path="/abs/out_ckg.json",
        fix_db_in_path=None,
        fix_db_out_path="/abs/fixes.db",
    )

    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute("SELECT bundle_id, run_id, case_num, iter_num FROM bundle_index WHERE bundle_id = ?", ("b1",))
        row = cur.fetchone()
        assert row == ("b1", "run1", 1, 1)
    finally:
        conn.close()

