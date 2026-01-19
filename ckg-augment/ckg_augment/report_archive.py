from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArchiveInputs:
    report_id: str
    raw_report_text: str
    raw_debug_query_text: str
    source_report_path: str
    source_query_path: str | None
    query_source: str  # "explicit_file" | "parsed_from_report"

    # Optional parsed convenience copies (from combined report format)
    parsed_human_report: str | None = None
    parsed_debug_query: str | None = None


@dataclass(frozen=True)
class ArchiveResult:
    bundle_id: str
    bundle_dir: Path
    existed: bool
    report_sha256: str
    query_sha256: str


def sha256_hex(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def parse_combined_report(raw: str) -> tuple[str | None, str | None]:
    """Parse (human_report, query) from a data/<case> combined file if possible."""
    lines = (raw or "").splitlines()
    marker = None
    for i, l in enumerate(lines):
        if "E2E Test Query" in l:
            marker = i
            break
    if marker is None:
        return None, None

    report_end = marker
    for j in range(marker - 1, -1, -1):
        if lines[j].strip() == "---":
            report_end = j
            break

    human_report = "\n".join(lines[:report_end]).strip()
    query = "\n".join(lines[marker + 1 :]).strip()
    return (human_report or None), (query or None)


def ensure_report_index_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bundle_index (
              bundle_id TEXT PRIMARY KEY,
              report_sha256 TEXT NOT NULL,
              query_sha256 TEXT NOT NULL,
              bundle_path TEXT NOT NULL,
              created_at TEXT NOT NULL,
              report_id TEXT NOT NULL,
              source_report_path TEXT NOT NULL,
              source_query_path TEXT,
              query_source TEXT NOT NULL,
              run_id TEXT,
              case_num INTEGER,
              iter_num INTEGER,
              ckg_in_path TEXT,
              ckg_out_path TEXT,
              fix_db_in_path TEXT,
              fix_db_out_path TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_bundle_index(
    *,
    db_path: Path,
    bundle_id: str,
    report_sha256: str,
    query_sha256: str,
    bundle_path: Path,
    report_id: str,
    source_report_path: str,
    source_query_path: str | None,
    query_source: str,
    run_id: str | None,
    case_num: int | None,
    iter_num: int | None,
    ckg_in_path: str | None,
    ckg_out_path: str | None,
    fix_db_in_path: str | None,
    fix_db_out_path: str | None,
) -> None:
    ensure_report_index_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO bundle_index (
              bundle_id, report_sha256, query_sha256, bundle_path, created_at,
              report_id, source_report_path, source_query_path, query_source,
              run_id, case_num, iter_num, ckg_in_path, ckg_out_path, fix_db_in_path, fix_db_out_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bundle_id) DO UPDATE SET
              -- keep created_at stable; but allow linking fields to be refreshed
              run_id = COALESCE(excluded.run_id, bundle_index.run_id),
              case_num = COALESCE(excluded.case_num, bundle_index.case_num),
              iter_num = COALESCE(excluded.iter_num, bundle_index.iter_num),
              ckg_in_path = COALESCE(excluded.ckg_in_path, bundle_index.ckg_in_path),
              ckg_out_path = COALESCE(excluded.ckg_out_path, bundle_index.ckg_out_path),
              fix_db_in_path = COALESCE(excluded.fix_db_in_path, bundle_index.fix_db_in_path),
              fix_db_out_path = COALESCE(excluded.fix_db_out_path, bundle_index.fix_db_out_path)
            """,
            (
                bundle_id,
                report_sha256,
                query_sha256,
                str(bundle_path),
                now,
                report_id,
                source_report_path,
                source_query_path,
                query_source,
                run_id,
                case_num,
                iter_num,
                ckg_in_path,
                ckg_out_path,
                fix_db_in_path,
                fix_db_out_path,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def archive_report_and_query(
    *,
    library_root: Path,
    inputs: ArchiveInputs,
    meta: dict[str, Any],
    no_overwrite: bool = True,
) -> ArchiveResult:
    """Archive raw report + raw query as an immutable bundle (dedup by hashes)."""
    report_sha = sha256_hex(inputs.raw_report_text)
    query_sha = sha256_hex(inputs.raw_debug_query_text)
    rid = (inputs.report_id or "report").strip().replace(" ", "_")

    bundle_id = f"bundle_{rid}_r{report_sha[:12]}_q{query_sha[:12]}"
    bundle_dir = library_root / "bundles" / bundle_id
    existed = bundle_dir.exists()
    if existed and no_overwrite:
        return ArchiveResult(
            bundle_id=bundle_id,
            bundle_dir=bundle_dir,
            existed=True,
            report_sha256=report_sha,
            query_sha256=query_sha,
        )

    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Raw inputs (always)
    (bundle_dir / "raw_report_input.txt").write_text(inputs.raw_report_text, encoding="utf-8")
    (bundle_dir / "raw_debug_query.txt").write_text(inputs.raw_debug_query_text, encoding="utf-8")

    # Parsed convenience copies (optional)
    if inputs.parsed_human_report is not None:
        (bundle_dir / "human_report.txt").write_text(inputs.parsed_human_report, encoding="utf-8")
    if inputs.parsed_debug_query is not None:
        (bundle_dir / "parsed_debug_query.txt").write_text(inputs.parsed_debug_query, encoding="utf-8")

    # Meta (kept inside bundle; note: if no_overwrite is True, existing bundles won't be updated)
    (bundle_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    return ArchiveResult(
        bundle_id=bundle_id,
        bundle_dir=bundle_dir,
        existed=existed,
        report_sha256=report_sha,
        query_sha256=query_sha,
    )

