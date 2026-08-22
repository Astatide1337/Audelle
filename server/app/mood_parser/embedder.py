from functools import lru_cache

import numpy as np
from fastembed import TextEmbedding

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(model_name=MODEL_NAME)


def embed(text: str) -> np.ndarray:
    """L2-normalized sentence embedding. Model loads once and stays warm (~90MB, local, no API call)."""
    return next(_model().embed([text]))


def warm_up() -> None:
    embed("warm up")
