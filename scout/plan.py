"""Decide what this week's run focuses on: season, category rotation, sales."""
from __future__ import annotations

from datetime import date

# Climate -> month -> season label
SEASONS = {
    "north-india": {12: "winter", 1: "winter", 2: "late-winter", 3: "spring", 4: "summer", 5: "summer", 6: "summer",
                    7: "monsoon", 8: "monsoon", 9: "monsoon", 10: "autumn", 11: "early-winter"},
    "humid-coastal": {m: ("monsoon" if m in (6, 7, 8, 9) else "summer" if m in (3, 4, 5, 10) else "mild") for m in range(1, 13)},
    "mild-plateau": {m: ("monsoon" if m in (6, 7, 8, 9) else "summer" if m in (3, 4, 5) else "mild") for m in range(1, 13)},
}

# What each season wants. Keywords matched against title+description.
SEASON_PREFS = {
    "winter": {"boost": ["wool", "merino", "fleece", "flannel", "corduroy", "sweater", "cardigan", "jacket", "overshirt",
                          "hoodie", "sweatshirt", "full sleeve", "long sleeve", "turtleneck", "heavyweight", "boots", "puffer", "quilted"],
               "penalty": ["linen", "shorts", "half sleeve", "short sleeve", "sleeveless", "tank", "sandal", "slides"]},
    "early-winter": {"boost": ["overshirt", "sweater", "flannel", "corduroy", "full sleeve", "jacket", "knit", "sweatshirt", "light jacket"],
                     "penalty": ["linen", "shorts", "sleeveless", "tank", "sandal"]},
    "late-winter": {"boost": ["overshirt", "light jacket", "knit", "full sleeve", "sweatshirt", "flannel"],
                    "penalty": ["shorts", "sleeveless", "linen"]},
    "spring": {"boost": ["oxford", "cotton", "chino", "light", "polo", "overshirt"], "penalty": ["puffer", "heavyweight wool"]},
    "summer": {"boost": ["linen", "cotton", "seersucker", "short sleeve", "half sleeve", "breathable", "lightweight", "shorts", "loafers", "polo"],
               "penalty": ["wool", "fleece", "puffer", "corduroy", "sweater", "hoodie", "flannel", "jacket", "boots"]},
    "monsoon": {"boost": ["quick dry", "cotton", "lightweight", "short sleeve", "sneakers"],
                "penalty": ["suede", "wool", "heavy", "linen", "puffer", "white sneakers"]},
    "autumn": {"boost": ["full sleeve", "overshirt", "light jacket", "oxford", "chino", "knit polo"], "penalty": ["puffer", "linen shorts"]},
    "mild": {"boost": ["cotton", "overshirt", "polo", "oxford"], "penalty": ["puffer", "heavy wool"]},
}

# Rotation of focus groups; winter leans on layers.
ROTATIONS = {
    "cold": ["layers", "tops", "bottoms", "layers", "footwear", "tops"],
    "hot": ["tops", "bottoms", "tops", "footwear", "layers"],
    "default": ["tops", "layers", "bottoms", "footwear"],
}

# Approximate Indian sale windows (month, day) -> (month, day). Verified each run by web search.
SALES = [
    ("Winter end-of-season sales on brand sites", (1, 1), (2, 15)),
    ("Republic Day sales", (1, 15), (1, 27)),
    ("Summer end-of-season sales on brand sites", (6, 10), (7, 31)),
    ("Myntra End of Reason Sale (summer edition)", (5, 30), (6, 15)),
    ("Independence Day sales", (8, 5), (8, 16)),
    ("Flipkart Big Billion Days / Amazon Great Indian Festival", (9, 20), (10, 20)),
    ("Diwali sales", (10, 10), (11, 12)),
    ("Black Friday / Cyber Monday sales", (11, 20), (12, 3)),
    ("Myntra End of Reason Sale (winter edition)", (12, 5), (12, 22)),
]


def season_for(climate: str, d: date) -> str:
    return SEASONS.get(climate, SEASONS["north-india"])[d.month]


def rotation_for(season: str) -> list[str]:
    if season in ("winter", "early-winter", "late-winter"):
        return ROTATIONS["cold"]
    if season in ("summer",):
        return ROTATIONS["hot"]
    return ROTATIONS["default"]


def active_sales(d: date) -> list[str]:
    md = (d.month, d.day)
    return [name for name, a, b in SALES if a <= md <= b]


def make_plan(profile: dict, history: dict, d: date | None = None) -> dict:
    d = d or date.today()
    climate = profile.get("me", {}).get("climate", "north-india")
    season = season_for(climate, d)
    rot = rotation_for(season)
    idx = history.get("rotation", {}).get("index", 0)
    focus = rot[idx % len(rot)]
    sales = active_sales(d)
    n = int(profile.get("shopping", {}).get("picks_per_week", 5))
    return {
        "date": d.isoformat(),
        "run_id": d.isoformat(),
        "season": season,
        "climate": climate,
        "focus_group": focus,
        "next_focus": rot[(idx + 1) % len(rot)],
        "picks": n,
        "slots": {"focus": max(1, n - 1), "wildcard": 1},
        "sales_window": sales,
        "season_prefs": SEASON_PREFS.get(season, {}),
    }
