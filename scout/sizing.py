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


def wanted_size(profile: dict, category: str, store_name: str, learned: dict | None = None) -> dict:
    """Return {'kind', 'letter', 'number'} the user wears for this category at this store."""
    sz = profile.get("sizes", {})
    kind = size_kind(category)
    brand = dict(sz.get("brand", {}).get(store_name, {}))
    brand.update((learned or {}).get(store_name, {}))
    if kind == "shoe":
        n = brand.get("shoe_uk") or sz.get("shoe_uk") or 0
        return {"kind": kind, "letter": None, "number": float(n) if n else None}
    if kind == "waist":
        n = brand.get("waist_in") or sz.get("waist_in") or 0
        letter = brand.get("bottom") or None
        return {"kind": kind, "letter": letter, "number": float(n) if n else None}
    letter = (brand.get("top") or sz.get("top") or "").upper() or None
    letter = _ALIASES.get(letter, letter) if letter else None
    n = brand.get("chest_in") or sz.get("chest_in") or (LETTER_TO_CHEST.get(letter) if letter else None)
    return {"kind": kind, "letter": letter, "number": float(n) if n else None}


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
    if want["kind"] == "shoe":
        if want["number"] is None:
            return False
        up = label.upper()
        if "EU" in up and "UK" not in up:
            # EU ~= UK + 33 (rough), accept within half a size
            return any(abs((n - 33) - want["number"]) <= 0.5 for n in _numbers_of(label))
        nums = _numbers_of(label)
        # "UK 9", "9", "UK9 / EU43": first number is UK by convention on Indian sites
        return bool(nums) and abs(nums[0] - want["number"]) < 0.01
    letter = _letter_of(label)
    if want["letter"] and letter:
        return letter == want["letter"]
    nums = _numbers_of(label)
    if want["number"] and nums:
        return any(abs(n - want["number"]) < 0.01 for n in nums)
    return False


def size_status(sizes: dict[str, bool], want: dict) -> tuple[str, str | None]:
    """-> (status, matched_label). status: in_stock | sold_out | not_offered | unknown_profile | no_sizes"""
    if want["letter"] is None and want["number"] is None:
        return "unknown_profile", None
    if not sizes:
        return "no_sizes", None
    if len(sizes) == 1 and next(iter(sizes)).lower() in ("default title", "one size", "free size", "os", "freesize"):
        lbl, ok = next(iter(sizes.items()))
        return ("in_stock" if ok else "sold_out"), lbl
    hits = [(lbl, ok) for lbl, ok in sizes.items() if label_matches(lbl, want)]
    if not hits:
        return "not_offered", None
    for lbl, ok in hits:
        if ok:
            return "in_stock", lbl
    return "sold_out", hits[0][0]
