"""FAISS vector store for semantic similarity search."""

from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass

import faiss
import numpy as np


@dataclass
class SearchResult:
    """Result from vector search."""
    entity_id: str
    label: str
    entity_type: str
    score: float  # Higher = more similar


class VectorStore:
    """FAISS-based vector store for entity embeddings."""
    
    def __init__(self, dimension: int = 1536):
        """Initialize vector store.
        
        Args:
            dimension: Embedding dimension (1536 for OpenAI text-embedding-3-small)
        """
        self._dimension = dimension
        self._index = faiss.IndexFlatIP(dimension)  # Inner product for cosine sim
        self._id_to_idx: dict[str, int] = {}
        self._idx_to_metadata: dict[int, dict] = {}
        self._next_idx = 0
    
    def add(
        self,
        entity_id: str,
        embedding: list[float] | np.ndarray,
        metadata: dict | None = None,
    ) -> None:
        """Add an entity embedding to the index.
        
        Args:
            entity_id: Unique entity identifier
            embedding: Embedding vector
            metadata: Optional metadata (label, type, etc.)
        """
        # Normalize for cosine similarity
        vec = np.array(embedding, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(vec)
        
        # Add to index
        self._index.add(vec)
        self._id_to_idx[entity_id] = self._next_idx
        self._idx_to_metadata[self._next_idx] = {
            "entity_id": entity_id,
            **(metadata or {}),
        }
        self._next_idx += 1
    
    def search(
        self,
        query_embedding: list[float] | np.ndarray,
        k: int = 5,
    ) -> list[SearchResult]:
        """Search for similar entities.
        
        Args:
            query_embedding: Query vector
            k: Number of results to return
            
        Returns:
            List of SearchResult, sorted by similarity
        """
        if self._index.ntotal == 0:
            return []
        
        # Normalize query
        query = np.array(query_embedding, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(query)
        
        # Search
        k = min(k, self._index.ntotal)
        scores, indices = self._index.search(query, k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            metadata = self._idx_to_metadata.get(idx, {})
            results.append(SearchResult(
                entity_id=metadata.get("entity_id", ""),
                label=metadata.get("label", ""),
                entity_type=metadata.get("type", ""),
                score=float(score),
            ))
        
        return results
    
    def save(self, path: str | Path) -> None:
        """Save the index to disk.
        
        Args:
            path: Directory path to save to
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        # Save FAISS index
        faiss.write_index(self._index, str(path / "faiss.index"))
        
        # Save metadata
        with open(path / "metadata.json", "w") as f:
            json.dump({
                "id_to_idx": self._id_to_idx,
                "idx_to_metadata": {str(k): v for k, v in self._idx_to_metadata.items()},
                "next_idx": self._next_idx,
                "dimension": self._dimension,
            }, f)
    
    @classmethod
    def load(cls, path: str | Path) -> "VectorStore":
        """Load an index from disk.
        
        Args:
            path: Directory path to load from
            
        Returns:
            Loaded VectorStore
        """
        path = Path(path)
        
        # Load metadata
        with open(path / "metadata.json") as f:
            data = json.load(f)
        
        store = cls(dimension=data["dimension"])
        store._index = faiss.read_index(str(path / "faiss.index"))
        store._id_to_idx = data["id_to_idx"]
        store._idx_to_metadata = {int(k): v for k, v in data["idx_to_metadata"].items()}
        store._next_idx = data["next_idx"]
        
        return store
    
    def __len__(self) -> int:
        """Number of entities in the index."""
        return self._index.ntotal
    
    def clear(self) -> None:
        """Clear all entries from the index."""
        self._index = faiss.IndexFlatIP(self._dimension)
        self._id_to_idx.clear()
        self._idx_to_metadata.clear()
        self._next_idx = 0
