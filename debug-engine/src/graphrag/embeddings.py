"""OpenAI embedding service for entity vectorization."""

from __future__ import annotations
import os
from typing import Any

from openai import OpenAI


class EmbeddingService:
    """Service for generating embeddings using OpenAI."""
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
    ):
        """Initialize the embedding service.
        
        Args:
            api_key: OpenAI API key (default: from OPENAI_API_KEY env)
            model: Embedding model to use
        """
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var.")
        
        self._client = OpenAI(api_key=self._api_key)
        self._model = model
        self._dimension = 1536  # text-embedding-3-small dimension
    
    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        return self._dimension
    
    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector
        """
        response = self._client.embeddings.create(
            input=text,
            model=self._model,
        )
        return response.data[0].embedding
    
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        response = self._client.embeddings.create(
            input=texts,
            model=self._model,
        )
        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
    
    def embed_entity(self, entity: dict[str, Any]) -> list[float]:
        """Generate embedding for a CKG entity.
        
        Combines label and description for richer embedding.
        
        Args:
            entity: Entity dict with 'label' and optional 'description'
            
        Returns:
            Embedding vector
        """
        label = entity.get("label", "")
        description = entity.get("description", "")
        entity_type = entity.get("type", "")
        
        # Combine for richer representation
        text = f"{entity_type}: {label}"
        if description:
            text += f". {description}"
        
        return self.embed_text(text)
