import pytest

from app.mood_parser.parse_vibe import parse_vibe

CASES = [
    ("late night drive through the city, a little melancholic", "late-night-drive"),
    ("hyped up for leg day at the gym", "workout-hype"),
    ("getting over a breakup, still stings", "heartbreak"),
    ("study session, need to lock in for finals", "focus-study"),
    ("beach vacation with friends, sun's out", "beach-tropical"),
]


@pytest.mark.parametrize("text,expected_top_anchor", CASES)
def test_matches_top_anchor(text, expected_top_anchor):
    plan = parse_vibe(text)
    assert plan.matched_anchors[0].id == expected_top_anchor


def test_dedups_genre_and_keyword_seeds():
    plan = parse_vibe("party all night, dancing with friends")
    assert len(set(plan.genre_seeds)) == len(plan.genre_seeds)
    assert len(set(plan.keyword_seeds)) == len(plan.keyword_seeds)
