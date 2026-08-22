from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequestModel(BaseModel):
    """Shared boundary rules for untrusted JSON request bodies."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


ShortText = Annotated[str, Field(min_length=1, max_length=64)]
# Canonical YouTube video IDs are exactly eleven URL-safe characters.
VideoId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{11}$")]
# JavaScript can represent integers exactly through 2^53 - 1. Keeping the
# public replay seed in that range prevents the browser from rounding it.
MAX_PLAYLIST_SEED = 2**53 - 1


class FiltersIn(RequestModel):
    year_from: int | None = Field(default=None, ge=1, le=2100)
    year_to: int | None = Field(default=None, ge=1, le=2100)
    genres: list[ShortText] = Field(default_factory=list, max_length=5)
    language: ShortText | None = None
    min_views: int | None = Field(default=None, ge=0, le=10**15)

    @model_validator(mode="after")
    def validate_year_range(self):
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("year_from must not be later than year_to")
        return self


class PlaylistRequest(RequestModel):
    text: str = Field(min_length=1, max_length=500)
    filters: FiltersIn = Field(default_factory=FiltersIn)
    limit: int = Field(default=25, ge=1, le=50)
    # Optional replay/debug hook. The server generates a fresh seed when the
    # browser omits it, so repeated prompts do not converge on one playlist.
    seed: int | None = Field(default=None, ge=0, le=MAX_PLAYLIST_SEED)


class MatchedAnchorOut(BaseModel):
    id: str
    similarity: float


class QueryPlanOut(BaseModel):
    genre_seeds: list[str]
    keyword_seeds: list[str]
    matched_anchors: list[MatchedAnchorOut]


class TrackOut(BaseModel):
    id: str
    name: str
    artists: list[str]
    year: int
    popularity: int
    watch_url: str
    album_art: str | None


class PlaylistResponse(BaseModel):
    plan: QueryPlanOut
    tracks: list[TrackOut]
    seed: int
