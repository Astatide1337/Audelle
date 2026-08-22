import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.mood_parser.parse_vibe import parse_vibe
from app.playlist_service.generate_playlist import generate_playlist
from app.shared.types import Filters

SAMPLES = [
    ("late night drive through the city, a little melancholic", Filters()),
    ("hyped up for leg day at the gym", Filters(year_range=(2018, 2024))),
    ("study session, need to lock in for finals", Filters(genres=["classical"])),
]


async def main():
    for text, filters in SAMPLES:
        plan = parse_vibe(text)
        playlist = await generate_playlist(plan, filters, 10)
        print(f'\n"{text}" filters={filters}')
        print(f"  {len(playlist.tracks)} tracks:")
        for t in playlist.tracks:
            print(f"    - {t.name} — {', '.join(t.artists)} ({t.year}) views~{t.popularity:,}")


asyncio.run(main())
