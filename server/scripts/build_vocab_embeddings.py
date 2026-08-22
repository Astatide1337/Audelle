import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.mood_parser.embedder import embed
from app.mood_parser.vocabulary import VOCABULARY

OUT_PATH = Path(__file__).parent.parent / "app" / "mood_parser" / "vocab_embeddings.json"


def main() -> None:
    entries = []
    for anchor in VOCABULARY:
        vector = embed(anchor.text)
        entries.append({"id": anchor.id, "vector": vector.tolist()})
        print(f"embedded {anchor.id}")
    OUT_PATH.write_text(json.dumps(entries))
    print(f"wrote {len(entries)} vectors to {OUT_PATH}")


if __name__ == "__main__":
    main()
