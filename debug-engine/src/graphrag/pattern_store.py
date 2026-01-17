"""Pattern store for anomaly detection rules (authoritative source)."""

from __future__ import annotations
from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any


@dataclass
class Pattern:
    id: str
    name: str
    metric_key: str
    operator: str  # gt, lt, eq, between
    threshold: float | None
    threshold_hi: float | None
    anomaly_type: str
    severity_map: dict[str, float]
    indicated_causes: list[str]
    description: str = ""


@dataclass
class ExclusionCondition:
    id: str
    pattern_id: str
    metric_key: str
    operator: str  # eq, in, lt, gt
    value: str
    reason: str = ""


class PatternStore:
    """SQLite-backed store for anomaly patterns and exclusion rules."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            output_dir = Path("output")
            output_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(output_dir / "pattern_store.db")
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pattern (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                metric_key TEXT NOT NULL,
                operator TEXT NOT NULL,
                threshold REAL,
                threshold_hi REAL,
                anomaly_type TEXT NOT NULL,
                severity_map TEXT NOT NULL,
                indicated_causes TEXT NOT NULL,
                description TEXT DEFAULT ''
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pattern_exclusion (
                id TEXT PRIMARY KEY,
                pattern_id TEXT NOT NULL,
                metric_key TEXT NOT NULL,
                operator TEXT NOT NULL,
                value TEXT NOT NULL,
                reason TEXT DEFAULT '',
                FOREIGN KEY(pattern_id) REFERENCES pattern(id)
            );
            """
        )
        self._conn.commit()

    def add_pattern(self, pattern: Pattern) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO pattern (
                id, name, metric_key, operator, threshold, threshold_hi,
                anomaly_type, severity_map, indicated_causes, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern.id,
                pattern.name,
                pattern.metric_key,
                pattern.operator,
                pattern.threshold,
                pattern.threshold_hi,
                pattern.anomaly_type,
                json.dumps(pattern.severity_map),
                json.dumps(pattern.indicated_causes),
                pattern.description,
            ),
        )
        self._conn.commit()

    def add_exclusion(self, exclusion: ExclusionCondition) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO pattern_exclusion (
                id, pattern_id, metric_key, operator, value, reason
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                exclusion.id,
                exclusion.pattern_id,
                exclusion.metric_key,
                exclusion.operator,
                exclusion.value,
                exclusion.reason,
            ),
        )
        self._conn.commit()

    def list_patterns(self) -> list[Pattern]:
        cur = self._conn.cursor()
        rows = cur.execute("SELECT * FROM pattern ORDER BY id").fetchall()
        return [self._row_to_pattern(row) for row in rows]

    def list_exclusions(self, pattern_id: str) -> list[ExclusionCondition]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT * FROM pattern_exclusion WHERE pattern_id = ? ORDER BY id",
            (pattern_id,),
        ).fetchall()
        return [self._row_to_exclusion(row) for row in rows]

    def ensure_defaults(self) -> None:
        cur = self._conn.cursor()
        count = cur.execute("SELECT COUNT(*) FROM pattern").fetchone()[0]
        if count:
            return

        defaults = [
            Pattern(
                id="pattern_vcore_ceiling",
                name="VCORE 725mV Usage High",
                metric_key="vcore_725mv_pct",
                operator="gt",
                threshold=10.0,
                threshold_hi=None,
                anomaly_type="VCORE_CEILING",
                severity_map={"low": 10.0, "medium": 11.0, "high": 15.0},
                indicated_causes=["rc_cm", "rc_powerhal"],
                description="VCORE 725mV usage exceeds 10%, indicates CM/PowerHal.",
            ),
            Pattern(
                id="pattern_vcore_floor",
                name="VCORE Floor Elevated",
                metric_key="vcore_floor_mv",
                operator="gt",
                threshold=575.0,
                threshold_hi=None,
                anomaly_type="VCORE_FLOOR",
                severity_map={"low": 575.0, "medium": 600.0, "high": 650.0},
                indicated_causes=["rc_mmdvfs"],
                description="VCORE floor above 575mV indicates MMDVFS OPP3 issue.",
            ),
            Pattern(
                id="pattern_ddr_high",
                name="DDR Total Usage High",
                metric_key="ddr_total_pct",
                operator="gt",
                threshold=30.0,
                threshold_hi=None,
                anomaly_type="DDR_HIGH",
                severity_map={"low": 30.0, "medium": 40.0, "high": 50.0},
                indicated_causes=["rc_cm", "rc_powerhal"],
                description="DDR total usage above 30% indicates CM/PowerHal pressure.",
            ),
            Pattern(
                id="pattern_mmdvfs_opp3",
                name="MMDVFS OPP3 High Usage",
                metric_key="mmdvfs_opp3_pct",
                operator="gt",
                threshold=50.0,
                threshold_hi=None,
                anomaly_type="MMDVFS_ABNORMAL",
                severity_map={"low": 50.0, "medium": 75.0, "high": 90.0},
                indicated_causes=["rc_mmdvfs"],
                description="MMDVFS OPP3 high usage indicates abnormal floor behavior.",
            ),
        ]
        for pattern in defaults:
            self.add_pattern(pattern)

        self.add_exclusion(
            ExclusionCondition(
                id="ex_vcore_floor_opp4",
                pattern_id="pattern_vcore_floor",
                metric_key="mmdvfs_opp",
                operator="eq",
                value="OPP4",
                reason="OPP4 is normal operation; rule out floor anomaly.",
            )
        )
        self.add_exclusion(
            ExclusionCondition(
                id="ex_mmdvfs_opp3_opp4",
                pattern_id="pattern_mmdvfs_opp3",
                metric_key="mmdvfs_opp",
                operator="eq",
                value="OPP4",
                reason="OPP4 is normal operation; do not flag MMDVFS abnormal.",
            )
        )

    def _row_to_pattern(self, row: sqlite3.Row) -> Pattern:
        return Pattern(
            id=row["id"],
            name=row["name"],
            metric_key=row["metric_key"],
            operator=row["operator"],
            threshold=row["threshold"],
            threshold_hi=row["threshold_hi"],
            anomaly_type=row["anomaly_type"],
            severity_map=json.loads(row["severity_map"]),
            indicated_causes=json.loads(row["indicated_causes"]),
            description=row["description"] or "",
        )

    def _row_to_exclusion(self, row: sqlite3.Row) -> ExclusionCondition:
        return ExclusionCondition(
            id=row["id"],
            pattern_id=row["pattern_id"],
            metric_key=row["metric_key"],
            operator=row["operator"],
            value=row["value"],
            reason=row["reason"] or "",
        )
