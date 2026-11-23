"""Turn messy store data into: category, group, gender, colours."""
from __future__ import annotations

import re

# Order matters: first match wins, most specific first.
CATEGORY_RULES: list[tuple[str, str]] = [
    ("loafers", r"\bloafers?\b|\bmoccasins?\b|\bdrivers?\b|horsebit|penny"),
    ("boots", r"\bboots?\b|chelsea|chukka"),
    ("formal-shoes", r"\boxfords?\b.*(shoe|leather)|\bderby\b|\bderbies\b|\bbrogues?\b|monk strap"),
    ("sneakers", r"sneakers?|trainers?|\bkicks\b|low[- ]top|high[- ]top|court shoe|tabi|\bshoes?\b"),
    ("sandals", r"sandals?|slides?|flip[- ]?flops?|slippers?|clogs?"),
    ("accessory", r"\bcaps?\b|\bhats?\b|\bbelts?\b|\bwallets?\b|\bbags?\b|backpacks?|duffle|beanies?|scarf|scarves|mufflers?|sunglasses|perfume|gift card|socks|gloves"),
    ("innerwear", r"boxers?|briefs?|trunks?|innerwear|vests? pack"),
    ("coord", r"co-?ords?\b|co-?ord set|\btracksuits?\b|\b(two|2)[- ]piece\b|\bset of\b|\bcombo\b|pack of|\b\d[- ]pack\b"),
    ("sweater", r"sweaters?|pullovers?|cardigans?|jumpers?|knitwear|crew knit"),
    ("polo", r"\bpolos?\b"),
    ("tshirt", r"t-?shirts?\b|\btees?\b"),
    ("blazer", r"\bblazers?\b|\bsuits?\b|sport coat|waistcoat|bandhgala|nehru"),
    ("overshirt", r"overshirts?|shackets?|shirt[- ]jackets?"),
    ("jacket", r"jackets?|bombers?|puffers?|parkas?|coats?|gilets?|gillets?|windcheaters?|varsity|trucker"),
    ("sweatshirt", r"sweatshirts?|hoodies?|hooded|crewneck sweat|fleece top|zip[- ]?up"),
    ("tshirt", r"henleys?|tank|\bvest\b|\bcrew\b"),
    ("shirt", r"\bshirts?\b|oxford|button[- ]down|kurta shirt"),
    ("sweater", r"\bknit(ted)?\b|turtle ?neck|mock ?neck"),
    ("jeans", r"\bjeans?\b|denims?\b(?!.*(shirt|jacket))"),
    ("chinos", r"chinos?|khakis?"),
    ("joggers", r"joggers?|track ?pants?|trackpants|sweatpants|cargos?|parachute"),
    ("shorts", r"\bshorts?\b|bermudas?"),
    ("trousers", r"trousers?|pants?\b|slacks|korean pants|pleated pants"),
    ("ethnic", r"kurta|sherwani|dhoti|pathani|jodhpuri"),
]

GROUPS = {
    "tops": ["shirt", "tshirt", "polo"],
    "layers": ["overshirt", "sweater", "sweatshirt", "jacket", "blazer"],
    "bottoms": ["trousers", "chinos", "jeans", "joggers", "shorts"],
    "footwear": ["sneakers", "loafers", "boots", "formal-shoes", "sandals"],
}
CATEGORY_GROUP = {c: g for g, cs in GROUPS.items() for c in cs}

WOMEN = re.compile(
    r"\bwom[ae]n'?s?\b|\bfemale\b|\bladies\b|\bgirls?\b|\bher\b|\bdress(es)?\b|\bkurti\b|\bsaree\b|"
    r"\bskirts?\b|\bblouse\b|\bbra\b|lehenga|\bcrop top\b|co-?ord set for women|\bkids?\b|\bboys?\b|\binfant\b|\bbaby\b|"
    r"for women|womens|\bdupatta\b|\bjumpsuit\b|\bbodycon\b|\bpalazzo\b|\bleggings\b"
)
MEN = re.compile(r"\bm[ae]n'?s?\b|\bmale\b|\bunisex\b|\bhim\b|for men|mens\b")

COLOURS = {
    # name: family
    "off-white": "neutral", "off white": "neutral", "white": "neutral", "ecru": "neutral", "cream": "neutral",
    "ivory": "neutral", "beige": "neutral", "sand": "neutral", "stone": "neutral", "khaki": "neutral",
    "taupe": "neutral", "camel": "neutral", "tan": "earth", "brown": "earth", "chocolate": "earth",
    "coffee": "earth", "mocha": "earth", "rust": "earth", "olive": "earth", "sage": "earth",
    "grey": "neutral", "gray": "neutral", "charcoal": "neutral", "black": "neutral", "navy": "neutral",
    "ink": "neutral", "indigo": "blue", "blue": "blue", "sky blue": "blue", "light blue": "blue",
    "teal": "blue", "green": "green", "bottle green": "green", "forest": "green", "mint": "pastel",
    "maroon": "deep", "wine": "deep", "burgundy": "deep", "red": "bright", "mustard": "earth",
    "yellow": "bright", "orange": "bright", "pink": "pastel", "lavender": "pastel", "lilac": "pastel",
    "purple": "bright", "peach": "pastel", "neon": "bright", "fluorescent": "bright", "multi": "multi",
}
_colour_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, COLOURS), key=len, reverse=True)) + r")\b")


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def strip_html(s: str | None) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
         .replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"[ \t]+", " ", s).strip()


def categorize(title: str, product_type: str = "", tags: list[str] | None = None) -> str:
    # Title is most reliable, then product_type, then tags.
    for text in (norm(title), norm(product_type), norm(" ".join(tags or []))):
        if not text:
            continue
        for cat, pat in CATEGORY_RULES:
            if re.search(pat, text):
                return cat
    return "other"


def gender(title: str, product_type: str = "", tags: list[str] | None = None, url: str = "") -> str:
    text = " ".join([norm(title), norm(product_type), norm(" ".join(tags or [])), url.lower()])
    w, m = bool(WOMEN.search(text)), bool(MEN.search(text))
    if w and not m:
        return "women"
    if m and not w:
        return "men"
    if w and m:
        # e.g. "unisex" + "women" tag soup; title decides
        t = norm(title)
        if WOMEN.search(t) and not MEN.search(t):
            return "women"
        return "unisex"
    return "unknown"


def colours(*texts: str) -> list[str]:
    found: list[str] = []
    for t in texts:
        for m in _colour_re.findall(norm(t)):
            c = "grey" if m == "gray" else ("off-white" if m == "off white" else m)
            if c not in found:
                found.append(c)
    return found


def colour_family(c: str) -> str:
    return COLOURS.get(c, "other")
