"""Filter + score catalog items against the profile, season, quality-for-price and learned taste."""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import capsule, quality, sizing
from .classify import CATEGORY_GROUP, norm

WEARABLE_GROUPS = {"tops", "layers", "bottoms", "footwear"}

VIBE_WORDS = {
    "minimal": {"plus": ["solid", "plain", "basic", "essential", "textured", "clean", "minimal", "classic", "everyday", "neutral"],
                "minus": ["graphic", "printed", "print", "slogan", "typography", "embroidered logo", "patch"]},
    "smart-casual": {"plus": ["oxford", "chino", "polo", "overshirt", "loafer", "knit", "button-down", "button down", "trouser",
                              "pleated", "linen", "cuban", "resort collar", "camp collar", "derby", "blazer", "cardigan", "henley"],
                     "minus": []},
    "streetwear": {"plus": ["oversized", "boxy", "relaxed", "baggy", "cargo", "drop shoulder", "drop-shoulder", "heavyweight",
                            "washed", "acid wash", "hoodie", "sneaker", "korean", "parachute", "wide leg", "workwear", "utility"],
                   "minus": []},
}


def _text(item: dict) -> str:
    return norm(" ".join([item.get("title", ""), item.get("product_type", ""), " ".join(item.get("tags", [])),
                          item.get("description", "")]))


def _has(words, text) -> list[str]:
    return [w for w in words if re.search(r"\b" + re.escape(w.lower()) + r"\b", text)]


def hard_filter(item: dict, profile: dict, seen: set[str], learned_sizes: dict) -> tuple[bool, str]:
    st = profile.get("style", {})
    q = profile.get("quality", {})
    if item.get("gender") == "women":
        return False, "womenswear"
    if item.get("group") not in WEARABLE_GROUPS:
        return False, f"category {item.get('category')}"
    if not item.get("any_available"):
        return False, "sold out"
    price = item.get("price") or 0
    cap = q.get("footwear_cap_inr", 10000) if item["group"] == "footwear" else q.get("hard_cap_inr", 9000)
    if price <= 0:
        return False, "no price"
    if price > cap:
        return False, "over cap (luxury)"
    if item["id"] in seen or item.get("url", "").split("?")[0].rstrip("/") in seen:
        return False, "already shown"
    if item.get("store") in profile.get("shopping", {}).get("avoid_stores", []):
        return False, "avoided store"
    head = norm(item.get("title", "") + " " + " ".join(item.get("tags", [])) + " " + item.get("product_type", ""))
    full = _text(item)
    bad = _has(st.get("avoid", []), head) + _has(q.get("avoid_materials", []), full)
    if bad:
        return False, f"dealbreaker: {bad[0]}"
    if "plus size" in head and profile.get("me", {}).get("build") != "heavier":
        return False, "fit: plus size line"
    fit_bad = _has(profile.get("fit", {}).get("avoid", []), head)
    if fit_bad:
        return False, f"fit: {fit_bad[0]}"
    want = sizing.wanted_size(profile, item["category"], item["store"], learned_sizes)
    status, label = sizing.size_status(item.get("sizes") or {}, want)
    item["size_status"], item["size_label"] = status, label
    if status in ("sold_out", "not_offered"):
        return False, f"my size {status.replace('_', ' ')}"
    return True, ""


def score(item: dict, profile: dict, plan: dict, learned: dict, ref_price: dict[str, float], history: dict) -> dict:
    st = profile.get("style", {})
    text = _text(item)
    title = norm(item.get("title", ""))
    br: dict[str, float] = {}
    notes: list[str] = []

    q = quality.score(text, item["category"])
    item["quality"] = q
    br["quality"] = round((q["score"] - 5) * 0.7, 2)

    ref = ref_price.get(item["category"]) or item["price"]
    ratio = item["price"] / ref if ref else 1
    # Value = "does the quality justify the price?" (user: budget is not the issue, quality-for-money is).
    # Expensive + mediocre is punished hard; cheap is only mildly rewarded; suspiciously cheap + no fabric info is punished.
    lr = math.log2(max(ratio, 0.05))
    price_term = -1.6 * lr if ratio > 1 else min(0.8, -0.5 * lr)
    justify = (q["score"] - 6.0) * 0.5 * (1 if ratio > 1 else 0.5)
    v = price_term + justify
    if ratio < 0.45 and not q["known"]:
        v -= 1.0
    br["value"] = round(max(-3, min(2, v)), 2)
    item["price_vs_median"] = round(ratio, 2)

    vibe = 0.0
    for v in st.get("vibes", []):
        w = VIBE_WORDS.get(v, {})
        vibe += 0.5 * len(_has(w.get("plus", []), text))
    if "minimal" in st.get("vibes", []) and "streetwear" not in st.get("vibes", []):
        vibe -= 0.8 * len(_has(VIBE_WORDS["minimal"]["minus"], title))
    br["style"] = round(min(vibe, 2.0), 2)

    dis = _has(st.get("dislike", []), title + " " + norm(" ".join(item.get("tags", []))))
    br["dislikes"] = -min(3.0, 1.5 * len(dis))
    if dis:
        notes.append("has: " + ", ".join(dis))

    # Fit: user likes things a bit loose, never tight. (Colour and brand deliberately carry no weight.)
    fit = profile.get("fit", {})
    loose = _has(fit.get("prefer", []), text)
    tight = _has(fit.get("soft_avoid", []), title + " " + norm(" ".join(item.get("tags", []))))
    br["fit"] = round(min(1.0, 0.5 * len(loose)) - 1.2 * min(1, len(tight)), 2)
    if tight:
        notes.append("cut: " + tight[0])

    sp = plan.get("season_prefs", {})
    s = 0.5 * len(_has(sp.get("boost", []), text)) - 0.9 * len(_has(sp.get("penalty", []), title))
    br["season"] = round(max(-2.5, min(1.5, s)), 2)

    br["focus"] = 2.0 if item.get("group") == plan.get("focus_group") else 0.0

    w = learned.get("weights", {})
    br["learned"] = round(sum(w.get(k, 0) for k in [f"store:{item['store']}", f"cat:{item['category']}"]), 2)

    # Wardrobe from scratch: filling an empty essential slot matters most, foundations first.
    slot = capsule.best_open_slot(item, history, plan.get("season"))
    if slot:
        br["capsule"] = 1.6 if slot.get("core") else 0.9
        item["capsule_slot"] = {"id": slot["id"], "name": slot["name"], "core": bool(slot.get("core"))}
    else:
        br["capsule"] = 0.0
        item["capsule_slot"] = None
    fresh = 0.0
    try:
        pub = datetime.fromisoformat((item.get("published_at") or "").replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - pub).days
        if days <= 21:
            fresh = 0.6
            notes.append("new drop")
    except ValueError:
        pass
    br["fresh"] = fresh
    disc = (1 - item["price"] / item["mrp"]) if item.get("mrp") else 0
    if disc >= 0.2:
        notes.append(f"{round(disc*100)}% off")
    br["deal"] = 0.5 if disc >= 0.2 else 0.0
    if plan.get("sales_window") and disc >= 0.3:
        br["deal"] += 0.3
    if item.get("size_status") == "unknown_profile":
        notes.append("size not checked (profile size missing)")

    total = round(sum(br.values()), 2)
    item["score"] = total
    item["breakdown"] = br
    item["notes"] = notes
    return item


def rank(items: list[dict], profile: dict, plan: dict, history: dict, groups: list[str] | None = None,
         per_store: int = 3, per_category: int = 8, limit: int = 40, per_slot: int = 3) -> tuple[list[dict], Counter]:
    seen = set(history["items"].keys()) | {v.get("url", "").split("?")[0].rstrip("/") for v in history["items"].values()}
    learned = history.get("learned", {})
    rejected: Counter = Counter()
    ok = []
    for it in items:
        good, why = hard_filter(it, profile, seen, learned.get("sizes", {}))
        if not good:
            rejected[why.split(":")[0]] += 1
            continue
        if groups and it["group"] not in groups:
            rejected["other group"] += 1
            continue
        ok.append(it)
    by_cat = defaultdict(list)
    for it in ok:
        by_cat[it["category"]].append(it["price"])
    ref = {c: statistics.median(v) for c, v in by_cat.items() if v}
    for it in ok:
        score(it, profile, plan, learned, ref, history)
    ok.sort(key=lambda x: x["score"], reverse=True)

    # de-dupe near-identical colourways: same store + same title minus colour words
    pool, keys = [], set()
    for it in ok:
        code = re.match(r"^([A-Z0-9]{3,})-[A-Z.]{1,5}$", it["title"].strip())
        key = (it["store"], code.group(1)) if code else (it["store"], re.sub(r"\b(" + "|".join(map(re.escape, it.get("colours", []) or ["~"])) + r")\b", "", norm(it["title"])).strip())
        if key not in keys:
            keys.add(key)
            pool.append(it)

    # 1) Reserve the best few for every still-empty, in-season wardrobe slot in scope, so an essential is never
    #    crowded out just because its category scores lower overall (e.g. puffers rarely state their fill).
    chosen: dict[str, dict] = {}
    slot_ids = [s["id"] for s in capsule.slots()
                if s["id"] not in capsule.filled(history) and capsule.in_season(s, plan.get("season", ""))
                and (not groups or s["group"] in groups)]
    for sid in slot_ids:
        got, stores_here = 0, set()
        for it in pool:
            if (it.get("capsule_slot") or {}).get("id") == sid and it["store"] not in stores_here:
                chosen[it["id"]] = it
                stores_here.add(it["store"])
                got += 1
                if got >= per_slot:
                    break
    # 2) Fill the rest by score, with store/category caps for variety.
    store_n, cat_n = Counter(), Counter()
    for it in chosen.values():
        store_n[it["store"]] += 1
        cat_n[it["category"]] += 1
    for it in pool:
        if len(chosen) >= limit:
            break
        if it["id"] in chosen or store_n[it["store"]] >= per_store or cat_n[it["category"]] >= per_category:
            continue
        chosen[it["id"]] = it
        store_n[it["store"]] += 1
        cat_n[it["category"]] += 1
    out = sorted(chosen.values(), key=lambda x: x["score"], reverse=True)
    return out, rejected
