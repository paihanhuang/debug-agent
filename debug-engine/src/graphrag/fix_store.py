"""SQLite storage for historical fixes."""

from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class HistoricalFix:
    """A historical fix record."""
    case_id: str
    root_cause: str
    symptom_summary: str
    metrics: dict[str, Any]
    fix_description: str
    resolution_notes: str = ""
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HistoricalFix":
        return cls(**data)


class FixStore:
    """SQLite storage for historical fixes."""
    
    def __init__(self, db_path: str | Path = "fixes.db"):
        """Initialize the fix store.
        
        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._ensure_table()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def _ensure_table(self) -> None:
        """Create the table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute("""
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
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_root_cause 
            ON historical_fixes(root_cause)
        """)
        conn.commit()
    
    def add_fix(self, fix: HistoricalFix) -> None:
        """Add a historical fix.
        
        Args:
            fix: The fix to add
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO historical_fixes 
            (case_id, root_cause, symptom_summary, metrics_json, 
             fix_description, resolution_notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fix.case_id,
                fix.root_cause,
                fix.symptom_summary,
                json.dumps(fix.metrics),
                fix.fix_description,
                fix.resolution_notes,
                fix.created_at,
            ),
        )
        conn.commit()
    
    def get_fixes_by_root_cause(self, root_cause: str) -> list[HistoricalFix]:
        """Get all fixes for a specific root cause.
        
        Args:
            root_cause: The root cause to filter by
            
        Returns:
            List of matching fixes
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM historical_fixes WHERE root_cause = ?",
            (root_cause,),
        )
        
        fixes = []
        for row in cursor:
            fixes.append(HistoricalFix(
                case_id=row["case_id"],
                root_cause=row["root_cause"],
                symptom_summary=row["symptom_summary"],
                metrics=json.loads(row["metrics_json"]) if row["metrics_json"] else {},
                fix_description=row["fix_description"],
                resolution_notes=row["resolution_notes"] or "",
                created_at=row["created_at"] or "",
            ))
        
        return fixes
    
    def get_all_fixes(self) -> list[HistoricalFix]:
        """Get all historical fixes."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM historical_fixes")
        
        fixes = []
        for row in cursor:
            fixes.append(HistoricalFix(
                case_id=row["case_id"],
                root_cause=row["root_cause"],
                symptom_summary=row["symptom_summary"],
                metrics=json.loads(row["metrics_json"]) if row["metrics_json"] else {},
                fix_description=row["fix_description"],
                resolution_notes=row["resolution_notes"] or "",
                created_at=row["created_at"] or "",
            ))
        
        return fixes
    
    def delete_fix(self, case_id: str) -> bool:
        """Delete a fix by case ID.
        
        Args:
            case_id: The case ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM historical_fixes WHERE case_id = ?",
            (case_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    
    def clear_all(self) -> None:
        """Delete all fixes."""
        conn = self._get_conn()
        conn.execute("DELETE FROM historical_fixes")
        conn.commit()
    
    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __enter__(self) -> "FixStore":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    def __len__(self) -> int:
        """Number of fixes in the store."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM historical_fixes")
        return cursor.fetchone()[0]
