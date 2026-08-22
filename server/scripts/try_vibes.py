import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.mood_parser.parse_vibe import parse_vibe

samples = [
    "late night drive through the city, a little melancholic",
    "hyped up for leg day at the gym",
    "rainy sunday, just want to curl up and do nothing",
    "getting over a breakup, still stings",
    "study session, need to lock in for finals",
    "beach vacation with friends, sun's out",
    "just won the championship, over the moon",
]

for text in samples:
    plan = parse_vibe(text)
    print(f'\n"{text}"')
    print("  matched:", ", ".join(f"{m.id} ({m.similarity:.3f})" for m in plan.matched_anchors))
    print("  genreSeeds:", plan.genre_seeds)
    print("  keywordSeeds:", plan.keyword_seeds)
