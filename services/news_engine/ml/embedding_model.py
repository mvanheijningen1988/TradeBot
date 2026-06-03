"""Embedding model for article similarity and duplicate detection.

Uses sentence-transformers (all-MiniLM-L6-v2) for computing
article embeddings.  This is optional and loaded lazily —
the core pipeline works without it.
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Sentence embedding model for similarity computation."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None

    def _ensure_loaded(self) -> bool:
        """Lazily load the sentence-transformers model."""
        if self._model is not None:
            return True
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            logger.info("Embedding model loaded: %s", self._model_name)
            return True
        except Exception as exc:
            logger.warning(
                "Could not load embedding model '%s': %s",
                self._model_name,
                exc,
            )
            return False

    def encode(self, text: str) -> Optional[np.ndarray]:
        """Compute embedding vector for a text string."""
        if not self._ensure_loaded():
            return None
        return self._model.encode(text, convert_to_numpy=True)

    def similarity(self, text_a: str, text_b: str) -> float:
        """Compute cosine similarity between two texts."""
        vec_a = self.encode(text_a)
        vec_b = self.encode(text_b)
        if vec_a is None or vec_b is None:
            return 0.0
        cosine = float(
            np.dot(vec_a, vec_b)
            / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b) + 1e-9)
        )
        return cosine
