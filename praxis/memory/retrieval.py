"""Lightweight, dependency-free similarity for the *tie-breaker* path.

Retrieval is keyed primarily on the structured intent-signature (see
`signature.py`). When several past instructions share a signature, this TF-IDF
cosine picks the closest by surface text. It is intentionally NOT the primary
mechanism — the assignment is explicit that memory must be structured knowledge,
not a vector store of prompts.
"""

from __future__ import annotations

import math
from collections import Counter

from .signature import tokenize


def _tf(tokens: list[str]) -> Counter:
    return Counter(tokens)


def cosine_similarity(a: str, b: str) -> float:
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    fa, fb = _tf(ta), _tf(tb)
    common = set(fa) & set(fb)
    if not common:
        return 0.0
    dot = sum(fa[t] * fb[t] for t in common)
    na = math.sqrt(sum(v * v for v in fa.values()))
    nb = math.sqrt(sum(v * v for v in fb.values()))
    return dot / (na * nb) if na and nb else 0.0


def best_match(query: str, candidates: list[str]) -> tuple[int, float]:
    """Return (index, score) of the most similar candidate, or (-1, 0.0)."""
    best_i, best_s = -1, 0.0
    for i, c in enumerate(candidates):
        s = cosine_similarity(query, c)
        if s > best_s:
            best_i, best_s = i, s
    return best_i, best_s
