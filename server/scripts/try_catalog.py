import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.catalog_service.search_candidates import build_search_term_candidates, search_candidates
from app.mood_parser.parse_vibe import parse_vibe
from app.shared.types import Filters

SAMPLES = [
    ("late night drive through the city, a little melancholic", Filters()),
    ("hyped up for leg day at the gym", Filters()),
    ("beach vacation with friends, sun's out", Filters(year_range=(2015, 2024))),
]


async def main():
    for text, filters in SAMPLES:
        plan = parse_vibe(text)
        print(f'\n"{text}"')
        print("  term variants:", build_search_term_candidates(plan, filters))
        candidates = await search_candidates(plan, filters)
        print(f"  {len(candidates)} candidates, first 5:")
        for c in candidates[:5]:
            print(f"    - {c.name} — {', '.join(c.artists)} ({c.year}) views~{c.popularity:,}")


asyncio.run(main())
