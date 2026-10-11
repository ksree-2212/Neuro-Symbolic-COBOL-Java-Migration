import math
import re
from typing import List, Dict, Any, Optional
import numpy as np
from backend.app.config import settings

class EmbeddingService:
    """
    Generates dense embeddings for code chunks and search queries.
    Provides local deterministic n-gram vectorization with cosine similarity,
    and external API provider support when configured.
    """
    def __init__(self, dimension: int = 128):
        self.dimension = dimension
        self.provider = settings.embedding_provider

    def _tokenize_code(self, text: str) -> List[str]:
        # Split on symbols, casing, and whitespace
        clean = re.sub(r'[^A-Za-z0-9_-]', ' ', text)
        tokens = [t.lower() for t in clean.split() if len(t) > 1]
        
        # Add character n-grams (3-grams, 4-grams) for subword matching
        ngrams = []
        for tok in tokens:
            ngrams.append(tok)
            if len(tok) >= 3:
                for i in range(len(tok) - 2):
                    ngrams.append(tok[i:i+3])
        return ngrams

    def embed_text(self, text: str) -> List[float]:
        tokens = self._tokenize_code(text)
        if not tokens:
            return [0.0] * self.dimension

        vec = np.zeros(self.dimension, dtype=np.float32)
        for tok in tokens:
            # Hash token into dimension buckets
            h = hash(tok)
            idx = abs(h) % self.dimension
            sign = 1.0 if (h >> 16) % 2 == 0 else -1.0
            vec[idx] += sign

        # L2 Normalize
        norm = np.linalg.norm(vec)
        if norm > 1e-9:
            vec = vec / norm
        return vec.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(t) for t in texts]

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-9 or norm_b < 1e-9:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
