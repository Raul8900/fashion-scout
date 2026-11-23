"""Match a product's size labels against the profile (plus learned per-brand sizes)."""
from __future__ import annotations

import re

LETTERS = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL", "5XL"]
_ALIASES = {"2XL": "XXL", "XXXL": "3XL", "SMALL": "S", "MEDIUM": "M", "LARGE": "L", "X-LARGE": "XL",
            "XLARGE": "XL", "XX-LARGE": "XXL", "EXTRA LARGE": "XL", "2X": "XXL", "3X": "3XL"}
# Typical Indian letter <-> chest(in) mapping, used only when a store labels by number.
LETTER_TO_CHEST = {"XS": 36, "S": 38, "M": 40, "L": 42, "XL": 44, "XXL": 46, "3XL": 48}

SIZE_OPTION_NAMES = ("size", "sizes", "uk size", "shoe size", "waist", "waist size")


def size_kind(category: str) -> str:
    from .classify import CATEGORY_GROUP
    g = CATEGORY_GROUP.get(category, "")
    if g == "footwear":
        return "shoe"
    if g == "bottoms":
        return "waist"
    return "top"


def _as_list(v) -> list:
    if v in (None, "", 0, []):
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def wanted_size(profile: dict, category: str, store_name: str, learned: dict | None = None) -> dict:
    """Return {'kind', 'letters': [...], 'numbers': [...]}: ANY of these is acceptable.
    The profile may list a range (top = ["M", "L"]); a learned/brand size narrows it for that store."""
    sz = profile.get("sizes", {})
    kind = size_kind(category)
    brand = dict(sz.get("brand", {}).get(store_name, {}))
    brand.update((learned or {}).get(store_name, {}))
    tops = [_ALIASES.get(str(x).upper(), str(x).upper()) for x in _as_list(brand.get("top") or sz.get("top"))]
    if kind == "shoe":
        nums = [float(x) for x in _as_list(brand.get("shoe_uk") or sz.get("shoe_uk"))]
        return {"kind": kind, "letters": [], "numbers": nums}
    if kind == "waist":
        nums = [float(x) for x in _as_list(brand.get("waist_in") or sz.get("waist_in"))]
        # joggers/cargos are often sold S/M/L: fall back to the top letter sizes
        return {"kind": kind, "letters": [str(x).upper() for x in _as_list(brand.get("bottom"))] or tops, "numbers": nums}
    chest = [float(x) for x in _as_list(brand.get("chest_in") or sz.get("chest_in"))] or \
        [float(LETTER_TO_CHEST[l]) for l in tops if l in LETTER_TO_CHEST]
    return {"kind": kind, "letters": tops, "numbers": chest}


def _letter_of(label: str) -> str | None:
    up = label.upper().replace("_", " ").strip()
    up = _ALIASES.get(up, up)
    for tok in re.split(r"[\s/\-|(),]+", up):
        tok = _ALIASES.get(tok, tok)
        if tok in LETTERS:
            return tok
    return None


def _numbers_of(label: str) -> list[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", label)]


def label_matches(label: str, want: dict) -> bool:
    if not label:
        return False
    wn = want.get("numbers") or []
    if want["kind"] == "shoe":
        if not wn:
            return False
        up = label.upper()
        nums = _numbers_of(label)
        if "EU" in up and "UK" not in up:
            # EU ~= UK + 33 (rough), accept within half a size
            return any(abs((n - 33) - w) <= 0.5 for n in nums for w in wn)
        # "UK 9", "9", "UK9 / EU43": first number is UK by convention on Indian sites
        return bool(nums) and any(abs(nums[0] - w) < 0.01 for w in wn)
    letter = _letter_of(label)
    if letter:
        return letter in (want.get("letters") or [])
    nums = _numbers_of(label)
    return bool(wn and nums) and any(abs(n - w) < 0.01 for n in nums for w in wn)


def size_status(sizes: dict[str, bool], want: dict) -> tuple[str, str | None]:
    """-> (status, label). status: in_stock | sold_out | not_offered | unknown_profile | no_sizes.
    label lists every acceptable size that is in stock, e.g. "M, L"."""
    if not want.get("letters") and not want.get("numbers"):
        return "unknown_profile", None
    if not sizes:
        return "no_sizes", None
    if len(sizes) == 1 and next(iter(sizes)).lower() in ("default title", "one size", "free size", "os", "freesize"):
        lbl, ok = next(iter(sizes.items()))
        return ("in_stock" if ok else "sold_out"), lbl
    hits = [(lbl, ok) for lbl, ok in sizes.items() if label_matches(lbl, want)]
    if not hits:
        return "not_offered", None
    good = [lbl for lbl, ok in hits if ok]
    if good:
        return "in_stock", ", ".join(good)
    return "sold_out", ", ".join(l for l, _ in hits)
