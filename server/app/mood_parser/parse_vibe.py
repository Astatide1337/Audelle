import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from .embedder import embed
from .vocabulary import VOCABULARY

EMBEDDINGS_PATH = Path(__file__).parent / "vocab_embeddings.json"
TOP_K = 3


@dataclass(frozen=True)
class MatchedAnchor:
    id: str
    similarity: float


@dataclass
class QueryPlan:
    # Preserve the user's words for catalog search. Semantic anchors describe
    # the mood, but they must not erase explicit artists, titles, characters, or
    # other named entities in the request.
    search_text: str = ''
    genre_seeds: list[str] = field(default_factory=list)
    keyword_seeds: list[str] = field(default_factory=list)
    # Anchor terms that matched, most similar first — useful for debugging/explainability.
    matched_anchors: list[MatchedAnchor] = field(default_factory=list)


@lru_cache(maxsize=1)
def _vocab_embeddings() -> dict[str, np.ndarray]:
    raw = json.loads(EMBEDDINGS_PATH.read_text())
    return {entry["id"]: np.array(entry["vector"], dtype=np.float64) for entry in raw}


def _dedup_capped(items: list[str], cap: int) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen[:cap]


def parse_vibe(text: str) -> QueryPlan:
    """
    Embeds free-text vibe input locally and matches it against a curated anchor
    vocabulary via cosine similarity — no LLM, no external API call.
    """
    vocab_embeddings = _vocab_embeddings()
    input_vector = embed(text)

    scored = sorted(
        (MatchedAnchor(id=anchor_id, similarity=float(np.dot(input_vector, vector))) for anchor_id, vector in vocab_embeddings.items()),
        key=lambda m: m.similarity,
        reverse=True,
    )

    top = scored[:TOP_K]
    anchors_by_id = {a.id: a for a in VOCABULARY}
    top_anchors = [anchors_by_id[m.id] for m in top]

    genre_seeds = _dedup_capped([g for a in top_anchors for g in a.genre_seeds], 5)
    keyword_seeds = _dedup_capped([k for a in top_anchors for k in a.keywords], 8)

    search_text = ' '.join(text.split())
    return QueryPlan(search_text=search_text, genre_seeds=genre_seeds, keyword_seeds=keyword_seeds, matched_anchors=top)
