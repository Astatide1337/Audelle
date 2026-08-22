from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureRange:
    min: float
    max: float


@dataclass(frozen=True)
class AudioFeatureRanges:
    energy: FeatureRange
    valence: FeatureRange
    tempo: FeatureRange
    danceability: FeatureRange
    acousticness: FeatureRange


@dataclass(frozen=True)
class AnchorTerm:
    id: str
    # Natural-language description embedded to match against user input.
    text: str
    audio_features: AudioFeatureRanges
    genre_seeds: list[str]
    keywords: list[str]


FEATURE_KEYS = ("energy", "valence", "tempo", "danceability", "acousticness")


def e(lo: float, hi: float) -> FeatureRange:
    return FeatureRange(lo, hi)


VOCABULARY: list[AnchorTerm] = [
    AnchorTerm(
        id="euphoric-happy",
        text="Euphoric, joyful, pure happiness and celebration, feeling on top of the world",
        audio_features=AudioFeatureRanges(e(0.7, 1), e(0.75, 1), e(115, 160), e(0.6, 0.9), e(0, 0.3)),
        genre_seeds=["pop", "dance", "disco"],
        keywords=["happy", "joy", "celebration", "euphoric", "elated"],
    ),
    AnchorTerm(
        id="melancholic-sad",
        text="Melancholic, sad, quiet sorrow, feeling low and reflective",
        audio_features=AudioFeatureRanges(e(0.1, 0.4), e(0, 0.3), e(60, 95), e(0.1, 0.4), e(0.4, 0.9)),
        genre_seeds=["sad", "singer-songwriter", "indie folk"],
        keywords=["sad", "melancholy", "sorrow", "down", "blue"],
    ),
    AnchorTerm(
        id="heartbreak",
        text="Heartbreak, mourning a lost relationship, aching and bittersweet",
        audio_features=AudioFeatureRanges(e(0.15, 0.45), e(0.05, 0.3), e(60, 100), e(0.1, 0.4), e(0.3, 0.8)),
        genre_seeds=["sad", "r&b", "singer-songwriter"],
        keywords=["heartbreak", "breakup", "lost love", "ex"],
    ),
    AnchorTerm(
        id="angry-aggressive",
        text="Angry, aggressive, furious energy, wanting to break something",
        audio_features=AudioFeatureRanges(e(0.8, 1), e(0.1, 0.4), e(120, 180), e(0.3, 0.7), e(0, 0.15)),
        genre_seeds=["metal", "punk", "hardcore"],
        keywords=["angry", "rage", "furious", "mad"],
    ),
    AnchorTerm(
        id="calm-relaxed",
        text="Calm, relaxed, peaceful and unhurried, easing into stillness",
        audio_features=AudioFeatureRanges(e(0.1, 0.35), e(0.4, 0.7), e(60, 90), e(0.2, 0.5), e(0.4, 0.9)),
        genre_seeds=["ambient", "acoustic", "chill"],
        keywords=["calm", "relaxed", "peaceful", "chill"],
    ),
    AnchorTerm(
        id="romantic-love",
        text="Romantic, in love, warm intimate feelings for someone special",
        audio_features=AudioFeatureRanges(e(0.3, 0.6), e(0.5, 0.85), e(70, 110), e(0.3, 0.6), e(0.2, 0.6)),
        genre_seeds=["r&b", "soul", "pop"],
        keywords=["romantic", "love", "crush", "intimate"],
    ),
    AnchorTerm(
        id="nostalgic",
        text="Nostalgic, wistfully remembering the past, bittersweet fondness",
        audio_features=AudioFeatureRanges(e(0.3, 0.55), e(0.35, 0.65), e(80, 115), e(0.3, 0.55), e(0.3, 0.7)),
        genre_seeds=["indie pop", "dream pop"],
        keywords=["nostalgia", "memories", "reminiscing"],
    ),
    AnchorTerm(
        id="anxious-tense",
        text="Anxious, tense, nervous energy and racing thoughts",
        audio_features=AudioFeatureRanges(e(0.5, 0.8), e(0.15, 0.4), e(100, 150), e(0.2, 0.5), e(0, 0.3)),
        genre_seeds=["electronic", "industrial"],
        keywords=["anxious", "nervous", "tense", "stressed"],
    ),
    AnchorTerm(
        id="confident-empowered",
        text="Confident, empowered, walking tall, unstoppable self-assurance",
        audio_features=AudioFeatureRanges(e(0.65, 0.95), e(0.55, 0.85), e(100, 140), e(0.55, 0.85), e(0, 0.25)),
        genre_seeds=["hip hop", "pop", "r&b"],
        keywords=["confident", "empowered", "boss", "unstoppable"],
    ),
    AnchorTerm(
        id="dreamy-ethereal",
        text="Dreamy, ethereal, floating and otherworldly, hazy soundscapes",
        audio_features=AudioFeatureRanges(e(0.2, 0.5), e(0.35, 0.65), e(70, 105), e(0.2, 0.5), e(0.3, 0.7)),
        genre_seeds=["dream pop", "shoegaze", "ambient"],
        keywords=["dreamy", "ethereal", "hazy", "floating"],
    ),
    AnchorTerm(
        id="focus-study",
        text="Studying for an exam, locking in on homework or finals, deep concentration with minimal distraction",
        audio_features=AudioFeatureRanges(e(0.15, 0.4), e(0.3, 0.6), e(60, 100), e(0.1, 0.4), e(0.3, 0.8)),
        genre_seeds=["lo-fi", "instrumental", "classical"],
        keywords=["focus", "study", "finals", "homework", "lock in", "concentration"],
    ),
    AnchorTerm(
        id="workout-hype",
        text="Intense workout, gym hype, pushing through the last rep",
        audio_features=AudioFeatureRanges(e(0.8, 1), e(0.5, 0.85), e(125, 175), e(0.5, 0.85), e(0, 0.15)),
        genre_seeds=["hip hop", "edm", "hard rock"],
        keywords=["workout", "gym", "hype", "pump up"],
    ),
    AnchorTerm(
        id="party-dance",
        text="Party, dancing all night, club energy with everyone on the floor",
        audio_features=AudioFeatureRanges(e(0.75, 1), e(0.6, 0.95), e(118, 135), e(0.7, 0.95), e(0, 0.15)),
        genre_seeds=["dance", "house", "pop"],
        keywords=["party", "dance", "club", "night out"],
    ),
    AnchorTerm(
        id="sleep-winddown",
        text="Winding down before sleep, soft and slow, drifting off",
        audio_features=AudioFeatureRanges(e(0, 0.2), e(0.3, 0.6), e(50, 75), e(0.1, 0.3), e(0.6, 1)),
        genre_seeds=["ambient", "acoustic", "piano"],
        keywords=["sleep", "wind down", "bedtime", "drowsy"],
    ),
    AnchorTerm(
        id="rainy-day",
        text="Rainy day, watching drops on the window, cozy introspection",
        audio_features=AudioFeatureRanges(e(0.15, 0.4), e(0.25, 0.55), e(65, 95), e(0.15, 0.4), e(0.4, 0.85)),
        genre_seeds=["indie folk", "lo-fi", "jazz"],
        keywords=["rain", "rainy day", "window", "cozy"],
    ),
    AnchorTerm(
        id="late-night-drive",
        text="Late night drive through the city, streetlights blurring past",
        audio_features=AudioFeatureRanges(e(0.35, 0.65), e(0.25, 0.55), e(85, 118), e(0.4, 0.7), e(0, 0.35)),
        genre_seeds=["synthwave", "chillwave", "r&b"],
        keywords=["night drive", "city", "streetlights", "cruising"],
    ),
    AnchorTerm(
        id="road-trip",
        text="Road trip, open highway, windows down, the excitement of going somewhere new",
        audio_features=AudioFeatureRanges(e(0.55, 0.85), e(0.5, 0.85), e(100, 140), e(0.4, 0.7), e(0.1, 0.5)),
        genre_seeds=["rock", "indie", "country"],
        keywords=["road trip", "highway", "adventure", "windows down"],
    ),
    AnchorTerm(
        id="morning-coffee",
        text="Slow morning with coffee, gentle start to the day",
        audio_features=AudioFeatureRanges(e(0.25, 0.5), e(0.45, 0.75), e(75, 105), e(0.3, 0.55), e(0.35, 0.75)),
        genre_seeds=["indie pop", "acoustic", "jazz"],
        keywords=["morning", "coffee", "slow start", "sunrise"],
    ),
    AnchorTerm(
        id="lofi-chill",
        text="Lo-fi chill beats, laid back and unhurried background texture",
        audio_features=AudioFeatureRanges(e(0.2, 0.45), e(0.35, 0.65), e(70, 95), e(0.3, 0.6), e(0.3, 0.7)),
        genre_seeds=["lo-fi", "chillhop", "instrumental"],
        keywords=["lofi", "chill beats", "laid back"],
    ),
    AnchorTerm(
        id="summer-vibes",
        text="Bright summer day, sunshine and warmth, easy breezy feeling",
        audio_features=AudioFeatureRanges(e(0.55, 0.85), e(0.6, 0.9), e(100, 130), e(0.55, 0.85), e(0.1, 0.5)),
        genre_seeds=["pop", "reggae", "tropical house"],
        keywords=["summer", "sunshine", "beach", "warm"],
    ),
    AnchorTerm(
        id="cozy-winter",
        text="Cozy winter evening, blankets and warm light, gentle stillness",
        audio_features=AudioFeatureRanges(e(0.15, 0.4), e(0.4, 0.7), e(65, 95), e(0.2, 0.45), e(0.5, 0.9)),
        genre_seeds=["acoustic", "folk", "piano"],
        keywords=["winter", "cozy", "fireplace", "snow"],
    ),
    AnchorTerm(
        id="beach-tropical",
        text="Beach day, tropical and carefree, waves and warm sand",
        audio_features=AudioFeatureRanges(e(0.5, 0.8), e(0.6, 0.9), e(95, 125), e(0.55, 0.85), e(0.15, 0.5)),
        genre_seeds=["reggae", "tropical house", "pop"],
        keywords=["beach", "tropical", "ocean", "vacation"],
    ),
    AnchorTerm(
        id="city-walk",
        text="Walking through the city, headphones in, watching the world go by",
        audio_features=AudioFeatureRanges(e(0.4, 0.7), e(0.4, 0.7), e(90, 125), e(0.4, 0.7), e(0.1, 0.45)),
        genre_seeds=["indie", "alternative", "hip hop"],
        keywords=["city walk", "urban", "streets", "wandering"],
    ),
    AnchorTerm(
        id="meditation-yoga",
        text="Meditation and yoga, breathing slowly, grounded and present",
        audio_features=AudioFeatureRanges(e(0, 0.2), e(0.4, 0.65), e(50, 75), e(0.1, 0.3), e(0.6, 1)),
        genre_seeds=["ambient", "new age", "instrumental"],
        keywords=["meditation", "yoga", "mindfulness", "breathe"],
    ),
    AnchorTerm(
        id="cooking-kitchen",
        text="Cooking in the kitchen, upbeat and playful background energy",
        audio_features=AudioFeatureRanges(e(0.5, 0.75), e(0.55, 0.85), e(95, 125), e(0.5, 0.8), e(0.15, 0.5)),
        genre_seeds=["funk", "pop", "soul"],
        keywords=["cooking", "kitchen", "dinner party"],
    ),
    AnchorTerm(
        id="gaming-focus",
        text="Gaming session, energetic and immersive, staying locked in",
        audio_features=AudioFeatureRanges(e(0.55, 0.85), e(0.4, 0.7), e(100, 150), e(0.3, 0.6), e(0, 0.2)),
        genre_seeds=["electronic", "synthwave", "dubstep"],
        keywords=["gaming", "video games", "boss fight"],
    ),
    AnchorTerm(
        id="cleaning-house",
        text="Cleaning the house, upbeat motivation to get chores done fast",
        audio_features=AudioFeatureRanges(e(0.65, 0.9), e(0.55, 0.85), e(110, 140), e(0.6, 0.9), e(0, 0.3)),
        genre_seeds=["pop", "disco", "dance"],
        keywords=["cleaning", "chores", "housework"],
    ),
    AnchorTerm(
        id="celebration",
        text="Big celebration, milestone moment, triumphant and joyful",
        audio_features=AudioFeatureRanges(e(0.7, 1), e(0.7, 1), e(105, 140), e(0.6, 0.9), e(0, 0.3)),
        genre_seeds=["pop", "dance", "hip hop"],
        keywords=["celebration", "milestone", "achievement", "party"],
    ),
    AnchorTerm(
        id="rebellious-punk",
        text="Rebellious, punk attitude, defiant and raw energy",
        audio_features=AudioFeatureRanges(e(0.75, 1), e(0.35, 0.65), e(130, 190), e(0.3, 0.6), e(0, 0.15)),
        genre_seeds=["punk", "garage rock", "grunge"],
        keywords=["rebellious", "punk", "defiant", "raw"],
    ),
    AnchorTerm(
        id="dark-moody",
        text="Dark, moody, brooding atmosphere with tension underneath",
        audio_features=AudioFeatureRanges(e(0.35, 0.65), e(0.1, 0.35), e(75, 115), e(0.25, 0.55), e(0.1, 0.4)),
        genre_seeds=["dark wave", "alternative", "trip hop"],
        keywords=["dark", "moody", "brooding", "shadowy"],
    ),
    AnchorTerm(
        id="jazzy-late-night",
        text="Jazzy late night lounge, smooth and sophisticated atmosphere",
        audio_features=AudioFeatureRanges(e(0.25, 0.5), e(0.4, 0.7), e(70, 110), e(0.35, 0.65), e(0.4, 0.8)),
        genre_seeds=["jazz", "soul", "lounge"],
        keywords=["jazz", "lounge", "smooth", "sophisticated"],
    ),
    AnchorTerm(
        id="hiphop-hype",
        text="Hip hop hype, bold swagger and rhythmic confidence",
        audio_features=AudioFeatureRanges(e(0.65, 0.95), e(0.45, 0.8), e(85, 145), e(0.65, 0.95), e(0, 0.2)),
        genre_seeds=["hip hop", "trap", "rap"],
        keywords=["hip hop", "rap", "swagger", "bars"],
    ),
    AnchorTerm(
        id="edm-festival",
        text="EDM festival, huge drops, crowd jumping together under lights",
        audio_features=AudioFeatureRanges(e(0.85, 1), e(0.6, 0.95), e(125, 150), e(0.7, 0.95), e(0, 0.1)),
        genre_seeds=["edm", "house", "dubstep"],
        keywords=["edm", "festival", "rave", "drop"],
    ),
    AnchorTerm(
        id="coffee-shop-indie",
        text="Cozy indie coffee shop, gentle acoustic ambience",
        audio_features=AudioFeatureRanges(e(0.25, 0.5), e(0.45, 0.7), e(80, 110), e(0.3, 0.55), e(0.4, 0.8)),
        genre_seeds=["indie folk", "acoustic", "indie pop"],
        keywords=["coffee shop", "cafe", "acoustic"],
    ),
    AnchorTerm(
        id="classical-calm-focus",
        text="Classical music for calm concentration, orchestral stillness",
        audio_features=AudioFeatureRanges(e(0.1, 0.35), e(0.3, 0.6), e(60, 100), e(0.05, 0.3), e(0.7, 1)),
        genre_seeds=["classical", "instrumental"],
        keywords=["classical", "orchestral", "piano", "focus"],
    ),
    AnchorTerm(
        id="ambient-background",
        text="Ambient background texture, minimal and unobtrusive",
        audio_features=AudioFeatureRanges(e(0, 0.25), e(0.35, 0.6), e(50, 85), e(0.05, 0.25), e(0.5, 0.9)),
        genre_seeds=["ambient", "drone", "instrumental"],
        keywords=["ambient", "background", "minimal", "texture"],
    ),
    AnchorTerm(
        id="sad-autumn",
        text="Sad girl autumn, melancholy wrapped in falling leaves and soft rain",
        audio_features=AudioFeatureRanges(e(0.15, 0.4), e(0.1, 0.35), e(65, 95), e(0.15, 0.4), e(0.4, 0.8)),
        genre_seeds=["indie folk", "sad", "singer-songwriter"],
        keywords=["autumn", "sad girl", "melancholy", "falling leaves"],
    ),
    AnchorTerm(
        id="pre-event-confidence",
        text="Getting ready before a big event, building confidence and excitement",
        audio_features=AudioFeatureRanges(e(0.6, 0.9), e(0.55, 0.85), e(105, 140), e(0.55, 0.85), e(0, 0.3)),
        genre_seeds=["pop", "hip hop", "dance"],
        keywords=["getting ready", "before event", "hype up"],
    ),
    AnchorTerm(
        id="grief-loss",
        text="Grief, mourning a profound loss, heavy and tender sorrow",
        audio_features=AudioFeatureRanges(e(0.05, 0.3), e(0, 0.25), e(55, 85), e(0.05, 0.3), e(0.5, 0.9)),
        genre_seeds=["sad", "classical", "singer-songwriter"],
        keywords=["grief", "mourning", "loss", "funeral"],
    ),
    AnchorTerm(
        id="gym-rage",
        text="Releasing anger through intense exercise, aggressive workout energy",
        audio_features=AudioFeatureRanges(e(0.85, 1), e(0.3, 0.6), e(130, 180), e(0.4, 0.7), e(0, 0.1)),
        genre_seeds=["metal", "hard rock", "hip hop"],
        keywords=["gym rage", "aggressive workout", "anger release"],
    ),
    AnchorTerm(
        id="creative-flow",
        text="Creative flow state, writing or making art, absorbed and inspired",
        audio_features=AudioFeatureRanges(e(0.25, 0.55), e(0.4, 0.7), e(75, 110), e(0.25, 0.5), e(0.3, 0.7)),
        genre_seeds=["instrumental", "post-rock", "ambient"],
        keywords=["creative flow", "writing", "art", "inspired"],
    ),
    AnchorTerm(
        id="new-beginnings",
        text="New beginnings, hopeful about what's ahead, a fresh start",
        audio_features=AudioFeatureRanges(e(0.5, 0.8), e(0.55, 0.85), e(95, 130), e(0.4, 0.7), e(0.15, 0.5)),
        genre_seeds=["indie pop", "pop", "folk"],
        keywords=["new beginnings", "fresh start", "hopeful"],
    ),
    AnchorTerm(
        id="sunset-golden-hour",
        text="Golden hour sunset, warm light fading, wistful beauty",
        audio_features=AudioFeatureRanges(e(0.3, 0.6), e(0.45, 0.75), e(80, 115), e(0.35, 0.65), e(0.2, 0.6)),
        genre_seeds=["indie pop", "dream pop", "r&b"],
        keywords=["sunset", "golden hour", "dusk"],
    ),
]
