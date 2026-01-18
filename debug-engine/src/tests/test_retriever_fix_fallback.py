from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.fix_store import FixStore, HistoricalFix
from graphrag.retriever import Retriever


class _Dummy:
    pass


def test_retriever_fallback_fix_lookup(tmp_path: Path) -> None:
    db = tmp_path / "fixes.db"
    fs = FixStore(db)
    try:
        fs.add_fix(
            HistoricalFix(
                case_id="c1",
                root_cause="CM",
                symptom_summary="",
                metrics={},
                fix_description="Adjust CM policy.",
            )
        )
        fs.add_fix(
            HistoricalFix(
                case_id="c2",
                root_cause="MMDVFS",
                symptom_summary="",
                metrics={},
                fix_description="Verify OPP3 floor behavior.",
            )
        )

        r = Retriever(vector_store=_Dummy(), neo4j_store=_Dummy(), fix_store=fs, embedding_service=_Dummy())  # type: ignore[arg-type]
        hits = r._fallback_fix_lookup("MMDVFS at OPP3; CM suspected")  # intentional private call in unit test
        assert {h.case_id for h in hits} == {"c1", "c2"}
    finally:
        fs.close()

