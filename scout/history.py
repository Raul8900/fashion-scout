"""Persistent memory in data/history.json (committed to git after each run)."""
from __future__ import annotations

from datetime import date

from .common import HISTORY, load_json, save_json

EMPTY = {
    "version": 1,
    "runs": [],          # one per weekly digest
    "items": {},         # every product ever shown, keyed by item id
    "learned": {"sizes": {}, "weights": {}},
    "rotation": {"index": 0},
    "taste_notes": [],   # free-text feedback distilled by Claude
}

VERDICT_DELTA = {"like": 0.6, "bought": 1.0, "save": 0.35, "skip": -0.6}


def load() -> dict:
    h = load_json(HISTORY) or {}
    for k, v in EMPTY.items():
        h.setdefault(k, v if not isinstance(v, (dict, list)) else type(v)(v))
    h["learned"].setdefault("sizes", {})
    h["learned"].setdefault("weights", {})
    return h


def save(h: dict) -> None:
    save_json(HISTORY, h)


def seen_ids(h: dict) -> set[str]:
    return set(h["items"].keys())


def seen_urls(h: dict) -> set[str]:
    return {v.get("url", "").split("?")[0].rstrip("/") for v in h["items"].values()}


def weight_keys(item: dict) -> list[str]:
    keys = [f"store:{item.get('store')}", f"cat:{item.get('category')}"]
    keys += [f"colour:{c}" for c in (item.get("colours") or [])[:2]]
    return keys


def apply_verdict(h: dict, item_id: str, verdict: str, note: str = "", size: str | None = None) -> None:
    it = h["items"].get(item_id)
    if not it:
        return
    prev = it.get("verdict")
    it["verdict"] = verdict
    if note:
        it.setdefault("notes", []).append(note)
    w = h["learned"]["weights"]
    if prev in VERDICT_DELTA:  # undo previous verdict's effect
        for k in weight_keys(it):
            w[k] = round(w.get(k, 0) - VERDICT_DELTA[prev], 3)
    for k in weight_keys(it):
        w[k] = round(max(-3.0, min(3.0, w.get(k, 0) + VERDICT_DELTA.get(verdict, 0))), 3)
    if verdict == "bought" and size:
        from .sizing import size_kind
        kind = size_kind(it.get("category", ""))
        key = {"top": "top", "waist": "waist_in", "shoe": "shoe_uk"}[kind]
        val: str | float = size.upper()
        if kind != "top":
            try:
                val = float(size.upper().replace("UK", "").strip())
            except ValueError:
                return
        h["learned"]["sizes"].setdefault(it["store"], {})[key] = val


def record_run(h: dict, run_id: str, focus: str, picks: list[dict]) -> None:
    today = date.today().isoformat()
    for n, p in enumerate(picks, 1):
        it = h["items"].setdefault(p["id"], {})
        it.update({
            "url": p["url"], "title": p["title"], "store": p["store"], "category": p["category"],
            "colours": p.get("colours", []), "price_at_pick": p.get("price"), "last_price": p.get("price"),
            "image": (p.get("images") or [None])[0], "run_id": run_id, "pick_no": n,
            "first_shown": it.get("first_shown", today), "verdict": it.get("verdict"),
            "size_label": p.get("size_label"),
        })
        it["times_shown"] = it.get("times_shown", 0) + 1
    runs = [r for r in h["runs"] if r["run_id"] != run_id]
    runs.append({"run_id": run_id, "date": today, "focus": focus, "picks": [p["id"] for p in picks],
                 "thread_id": None, "message_id": None, "feedback_done": False})
    h["runs"] = runs
    h["rotation"]["index"] = h["rotation"].get("index", 0) + 1


def pending_feedback_runs(h: dict) -> list[dict]:
    return [r for r in h["runs"] if r.get("thread_id") and not r.get("feedback_done")]


def watchlist(h: dict) -> list[tuple[str, dict]]:
    return [(k, v) for k, v in h["items"].items() if v.get("verdict") in ("like", "save")]
