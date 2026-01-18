from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class FixRecord:
    """A record compatible with debug-engine's FixStore schema."""

    case_id: str
    root_cause: str
    symptom_summary: str
    metrics: dict[str, Any]
    fix_description: str
    resolution_notes: str = ""
    created_at: str = ""

    def normalized(self) -> "FixRecord":
        ca = self.created_at or datetime.now().isoformat()
        return FixRecord(
            case_id=self.case_id,
            root_cause=(self.root_cause or "").strip(),
            symptom_summary=(self.symptom_summary or "").strip(),
            metrics=self.metrics or {},
            fix_description=(self.fix_description or "").strip(),
            resolution_notes=(self.resolution_notes or "").strip(),
            created_at=ca,
        )


@dataclass(frozen=True)
class FixDbDiff:
    inserted_case_ids: list[str]
    replaced_case_ids: list[str]
    skipped_invalid: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "inserted_case_ids": self.inserted_case_ids,
            "replaced_case_ids": self.replaced_case_ids,
            "skipped_invalid": self.skipped_invalid,
        }


def ensure_fix_db_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_fixes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT UNIQUE NOT NULL,
                root_cause TEXT NOT NULL,
                symptom_summary TEXT,
                metrics_json TEXT,
                fix_description TEXT NOT NULL,
                resolution_notes TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_root_cause
            ON historical_fixes(root_cause)
            """
        )
        conn.commit()
    finally:
        conn.close()


def copy_or_init_base_fix_db(*, base_db: Path | None, out_db: Path) -> None:
    """Prepare output db as a copy of base, or as a new empty db if no base."""
    if out_db.exists():
        raise FileExistsError(f"Refusing to overwrite existing fix DB: {out_db}")
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if base_db is None:
        ensure_fix_db_schema(out_db)
        return
    if not base_db.exists():
        raise FileNotFoundError(f"Base fix DB not found: {base_db}")
    shutil.copyfile(str(base_db), str(out_db))
    # Ensure schema exists (base might be empty/corrupt)
    ensure_fix_db_schema(out_db)


def stable_fix_case_id(*, report_id: str, root_cause: str, fix_description: str) -> str:
    h = hashlib.sha1(f"{root_cause}::{fix_description}".encode("utf-8")).hexdigest()[:10]
    safe_report = (report_id or "report").strip().replace(" ", "_")
    return f"fix_{safe_report}_{h}"


def upsert_fixes(db_path: Path, fixes: Iterable[FixRecord]) -> FixDbDiff:
    """Insert or replace fixes by case_id, compatible with FixStore.add_fix()."""
    ensure_fix_db_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        inserted: list[str] = []
        replaced: list[str] = []
        skipped: list[str] = []

        for raw in fixes:
            f = raw.normalized()
            if not f.case_id or not f.root_cause or not f.fix_description:
                skipped.append(f.case_id or "<missing_case_id>")
                continue
            # detect replace vs insert
            cur = conn.execute("SELECT 1 FROM historical_fixes WHERE case_id = ?", (f.case_id,))
            exists = cur.fetchone() is not None

            conn.execute(
                """
                INSERT OR REPLACE INTO historical_fixes
                (case_id, root_cause, symptom_summary, metrics_json,
                 fix_description, resolution_notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f.case_id,
                    f.root_cause,
                    f.symptom_summary,
                    json.dumps(f.metrics or {}, ensure_ascii=False),
                    f.fix_description,
                    f.resolution_notes,
                    f.created_at,
                ),
            )
            (replaced if exists else inserted).append(f.case_id)

        conn.commit()
        return FixDbDiff(inserted_case_ids=inserted, replaced_case_ids=replaced, skipped_invalid=skipped)
    finally:
        conn.close()

