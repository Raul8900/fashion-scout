"""Wardrobe-from-scratch: which essential slot does an item fill, and what's still empty."""
from __future__ import annotations

import re

from .common import DATA, load_json

COLD = {"early-winter", "winter", "late-winter"}
HOT = {"spring", "summer", "monsoon"}


def slots() -> list[dict]:
    return load_json(DATA / "capsule.json", {"slots": []})["slots"]


def in_season(slot: dict, season: str) -> bool:
    ss = slot.get("seasons")
    if not ss:
        return True
    return ("cold" in ss and season in COLD) or ("hot" in ss and season in HOT)


def _has(word: str, text: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def matching_slots(item: dict, text: str | None = None) -> list[dict]:
    """All slots this item could fill (most specific first: keyword slots before keyword-less)."""
    t = (text or f"{item.get('title','')} {' '.join(item.get('colours') or [])} {item.get('description','')[:400]}").lower()
    title = (item.get("title") or "").lower()
    out = []
    for s in slots():
        if item.get("category") not in s["categories"]:
            continue
        if any(_has(x, title) for x in s.get("exclude", [])):
            continue
        kws = s.get("keywords", [])
        if kws and not any(_has(k, t) for k in kws):
            continue
        out.append(s)
    out.sort(key=lambda s: 0 if s.get("keywords") else 1)
    return out


def filled(history: dict) -> dict:
    return history.setdefault("capsule", {})


def best_open_slot(item: dict, history: dict, season: str | None = None) -> dict | None:
    have = filled(history)
    for s in matching_slots(item):
        if s["id"] not in have and (season is None or in_season(s, season)):
            return s
    return None


def fill(history: dict, item_id: str, item: dict, slot_id: str | None = None, date: str = "") -> str | None:
    have = filled(history)
    if slot_id is None:
        s = best_open_slot(item, history)
        slot_id = s["id"] if s else None
    if slot_id:
        have[slot_id] = {"item_id": item_id, "title": item.get("title"), "store": item.get("store"), "date": date}
    return slot_id


def progress(history: dict) -> dict:
    have = filled(history)
    all_s = slots()
    core = [s for s in all_s if s.get("core")]
    return {
        "filled": len([s for s in all_s if s["id"] in have]), "total": len(all_s),
        "core_filled": len([s for s in core if s["id"] in have]), "core_total": len(core),
        "missing_core": [s["name"] for s in core if s["id"] not in have],
        "owned": {k: v.get("title") for k, v in have.items()},
    }
