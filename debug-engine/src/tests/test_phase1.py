"""Unit tests for Phase 1: Core Infrastructure.

Tests:
- VectorStore: FAISS indexing and search
- FixStore: SQLite CRUD operations
- (Neo4j tests require running instance)
"""

import tempfile
import pytest
from pathlib import Path

import numpy as np

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from graphrag.vector_store import VectorStore, SearchResult
from graphrag.fix_store import FixStore, HistoricalFix


class TestVectorStore:
    """Tests for FAISS vector store."""
    
    def test_add_and_search(self):
        """Test adding vectors and searching."""
        store = VectorStore(dimension=128)
        
        # Add some vectors
        vec1 = np.random.randn(128).tolist()
        vec2 = np.random.randn(128).tolist()
        
        store.add("e1", vec1, {"label": "Entity 1", "type": "Symptom"})
        store.add("e2", vec2, {"label": "Entity 2", "type": "RootCause"})
        
        assert len(store) == 2
        
        # Search with vec1 - should find e1 first
        results = store.search(vec1, k=2)
        assert len(results) == 2
        assert results[0].entity_id == "e1"
        assert results[0].score > results[1].score
    
    def test_empty_search(self):
        """Test searching empty store."""
        store = VectorStore(dimension=128)
        results = store.search(np.random.randn(128).tolist(), k=5)
        assert results == []
    
    def test_save_and_load(self):
        """Test saving and loading index."""
        store = VectorStore(dimension=64)
        vec = np.random.randn(64).tolist()
        store.add("test", vec, {"label": "Test"})
        
        with tempfile.TemporaryDirectory() as tmpdir:
            store.save(tmpdir)
            
            loaded = VectorStore.load(tmpdir)
            assert len(loaded) == 1
            
            results = loaded.search(vec, k=1)
            assert results[0].entity_id == "test"
    
    def test_clear(self):
        """Test clearing the store."""
        store = VectorStore(dimension=64)
        store.add("e1", np.random.randn(64).tolist())
        assert len(store) == 1
        
        store.clear()
        assert len(store) == 0


class TestFixStore:
    """Tests for SQLite fix store."""
    
    def test_add_and_get_by_root_cause(self):
        """Test adding fixes and retrieving by root cause."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            store = FixStore(db_path)
            
            fix1 = HistoricalFix(
                case_id="case_001",
                root_cause="CM",
                symptom_summary="VCORE at 82.6%",
                metrics={"VCORE": 82.6, "DDR": 82.6},
                fix_description="Adjusted control policy",
            )
            
            fix2 = HistoricalFix(
                case_id="case_002",
                root_cause="CM",
                symptom_summary="VCORE at 29.3%",
                metrics={"VCORE": 29.3},
                fix_description="Modified PowerHal",
            )
            
            fix3 = HistoricalFix(
                case_id="case_003",
                root_cause="MMDVFS",
                symptom_summary="VCORE 600mV floor",
                metrics={"VCORE_floor": 600},
                fix_description="Adjusted MMDVFS OPP",
            )
            
            store.add_fix(fix1)
            store.add_fix(fix2)
            store.add_fix(fix3)
            
            assert len(store) == 3
            
            # Get by root cause
            cm_fixes = store.get_fixes_by_root_cause("CM")
            assert len(cm_fixes) == 2
            assert all(f.root_cause == "CM" for f in cm_fixes)
            
            mmdvfs_fixes = store.get_fixes_by_root_cause("MMDVFS")
            assert len(mmdvfs_fixes) == 1
            
            store.close()
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_delete_fix(self):
        """Test deleting a fix."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            store = FixStore(db_path)
            
            fix = HistoricalFix(
                case_id="to_delete",
                root_cause="TEST",
                symptom_summary="Test",
                metrics={},
                fix_description="Test fix",
            )
            store.add_fix(fix)
            assert len(store) == 1
            
            deleted = store.delete_fix("to_delete")
            assert deleted
            assert len(store) == 0
            
            # Delete non-existent
            deleted = store.delete_fix("nonexistent")
            assert not deleted
            
            store.close()
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_get_all_fixes(self):
        """Test getting all fixes."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            store = FixStore(db_path)
            
            for i in range(5):
                store.add_fix(HistoricalFix(
                    case_id=f"case_{i}",
                    root_cause="TEST",
                    symptom_summary=f"Symptom {i}",
                    metrics={},
                    fix_description=f"Fix {i}",
                ))
            
            all_fixes = store.get_all_fixes()
            assert len(all_fixes) == 5
            
            store.close()
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_update_existing_fix(self):
        """Test that adding fix with same case_id updates it."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            store = FixStore(db_path)
            
            fix_v1 = HistoricalFix(
                case_id="case_update",
                root_cause="OLD",
                symptom_summary="Old summary",
                metrics={},
                fix_description="Old fix",
            )
            store.add_fix(fix_v1)
            
            fix_v2 = HistoricalFix(
                case_id="case_update",
                root_cause="NEW",
                symptom_summary="New summary",
                metrics={},
                fix_description="New fix",
            )
            store.add_fix(fix_v2)
            
            assert len(store) == 1
            
            fixes = store.get_fixes_by_root_cause("NEW")
            assert len(fixes) == 1
            assert fixes[0].fix_description == "New fix"
            
            store.close()
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestHistoricalFix:
    """Tests for HistoricalFix dataclass."""
    
    def test_to_dict(self):
        """Test serialization."""
        fix = HistoricalFix(
            case_id="test",
            root_cause="CM",
            symptom_summary="Test",
            metrics={"a": 1},
            fix_description="Fix",
        )
        
        d = fix.to_dict()
        assert d["case_id"] == "test"
        assert d["root_cause"] == "CM"
        assert d["metrics"] == {"a": 1}
    
    def test_from_dict(self):
        """Test deserialization."""
        d = {
            "case_id": "test",
            "root_cause": "CM",
            "symptom_summary": "Test",
            "metrics": {"a": 1},
            "fix_description": "Fix",
            "resolution_notes": "",
            "created_at": "2024-01-01",
        }
        
        fix = HistoricalFix.from_dict(d)
        assert fix.case_id == "test"
        assert fix.created_at == "2024-01-01"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
