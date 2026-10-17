from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)


class EmbeddingBackendError(RuntimeError):
    """Raised when the configured embedding backend cannot be loaded."""


class Embedder(ABC):
    name: str
    dimension: int

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class HashedEmbedder(Embedder):
    name = "hashed"

    def __init__(self, dimension: int = 64):
        self.dimension = dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                vector[index] += 1.0 if digest[4] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector] if norm else vector)
        return vectors


class SentenceTransformerEmbedder(Embedder):
    name = "sentence_transformer"
    model_name = "all-MiniLM-L6-v2"

    def __init__(self, batch_size: int = 32, device: str | None = None):
        self.batch_size = batch_size
        self.device = device or os.getenv("EMBEDDING_DEVICE", "cpu")
        self._model = None
        self.dimension = 0

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device=self.device)
            self.dimension = int(self._model.get_sentence_embedding_dimension())
            return self._model
        except Exception as exc:
            raise EmbeddingBackendError(
                "Could not load sentence-transformers/all-MiniLM-L6-v2. "
                "Install sentence-transformers and allow the first-run model download, "
                "or set EMBEDDING_BACKEND=hashed. "
                "Set EMBEDDING_ALLOW_FALLBACK=true to opt into a visible hashed fallback."
            ) from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        encoded = model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in encoded]


def create_embedder(
    backend: str | None = None,
    dimension: int = 64,
    allow_fallback: bool | None = None,
) -> Embedder:
    selected = backend or os.getenv("EMBEDDING_BACKEND", "sentence_transformer")
    allow = (
        allow_fallback
        if allow_fallback is not None
        else os.getenv("EMBEDDING_ALLOW_FALLBACK", "false").lower() == "true"
    )
    if selected == "hashed":
        return HashedEmbedder(dimension)
    if selected != "sentence_transformer":
        raise EmbeddingBackendError(
            f"Unsupported EMBEDDING_BACKEND={selected!r}; use sentence_transformer or hashed."
        )
    embedder = SentenceTransformerEmbedder()
    return _FallbackEmbedder(embedder, HashedEmbedder(dimension)) if allow else embedder


class _FallbackEmbedder(Embedder):
    def __init__(self, primary: Embedder, fallback: Embedder):
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.dimension = primary.dimension
        self._using_fallback = False

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self._using_fallback:
            return self.fallback.embed_texts(texts)
        try:
            vectors = self.primary.embed_texts(texts)
            self.dimension = self.primary.dimension
            return vectors
        except EmbeddingBackendError:
            logger.warning(
                "Embedding backend %s failed; explicitly falling back to hashed vectors.",
                self.primary.name,
            )
            self._using_fallback = True
            self.name = self.fallback.name
            self.dimension = self.fallback.dimension
            return self.fallback.embed_texts(texts)


def cosine_similarity(
    left: Iterable[float] | None,
    right: Iterable[float] | None,
    left_embedder: str | None = None,
    right_embedder: str | None = None,
) -> float:
    if left_embedder and right_embedder and left_embedder != right_embedder:
        raise ValueError(f"Cannot compare vectors from {left_embedder} and {right_embedder}")
    if left is None or right is None:
        return 0.0
    left_values, right_values = list(left), list(right)
    if not left_values or len(left_values) != len(right_values):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left_values, right_values)) / (left_norm * right_norm)
