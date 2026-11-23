"""Filter + score catalog items against the profile, season, quality-for-price and learned taste."""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import quality, sizing
from .classify import CATEGORY_GROUP, colour_family, norm

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
    if set(item.get("colours", [])[:1]) & set(st.get("colours_avoid", [])):
        return False, "colour avoided"
    want = sizing.wanted_size(profile, item["category"], item["store"], learned_sizes)
    status, label = sizing.size_status(item.get("sizes") or {}, want)
    item["size_status"], item["size_label"] = status, label
    if status in ("sold_out", "not_offered"):
        return False, f"my size {status.replace('_', ' ')}"
    return True, ""


def score(item: dict, profile: dict, plan: dict, learned: dict, ref_price: dict[str, float], wardrobe_cats: set[str]) -> dict:
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
    br["tier"] = {"premium": 0.4, "mid": 0.2}.get(item.get("tier"), 0.0)
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

    cols = item.get("colours", [])
    c = 0.0
    if cols:
        main = cols[0]
        if main in st.get("colours_love", []):
            c = 1.0
        elif main in st.get("colours_ok", []):
            c = 0.3
        elif colour_family(main) in ("bright", "pastel"):
            c = -0.8
    br["colour"] = c

    sp = plan.get("season_prefs", {})
    s = 0.5 * len(_has(sp.get("boost", []), text)) - 0.9 * len(_has(sp.get("penalty", []), title))
    br["season"] = round(max(-2.5, min(1.5, s)), 2)

    br["focus"] = 2.0 if item.get("group") == plan.get("focus_group") else 0.0

    w = learned.get("weights", {})
    br["learned"] = round(sum(w.get(k, 0) for k in [f"store:{item['store']}", f"cat:{item['category']}"] +
                              [f"colour:{x}" for x in cols[:2]]), 2)

    br["gap"] = 0.4 if item["category"] not in wardrobe_cats else 0.0
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
    br["prefer_store"] = 0.5 if item["store"] in profile.get("shopping", {}).get("prefer_stores", []) else 0.0

    total = round(sum(br.values()), 2)
    item["score"] = total
    item["breakdown"] = br
    item["notes"] = notes
    return item


def rank(items: list[dict], profile: dict, plan: dict, history: dict, groups: list[str] | None = None,
         per_store: int = 3, per_category: int = 8, limit: int = 40) -> tuple[list[dict], Counter]:
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
    wardrobe_cats = {w.get("category") for w in profile.get("wardrobe", []) if not str(w.get("item", "")).startswith("example")}
    for it in ok:
        score(it, profile, plan, learned, ref, wardrobe_cats)
    ok.sort(key=lambda x: x["score"], reverse=True)
    # de-dupe near-identical colourways: same store + same title minus colour words
    out, store_n, cat_n, keys = [], Counter(), Counter(), set()
    for it in ok:
        code = re.match(r"^([A-Z0-9]{3,})-[A-Z]{1,3}$", it["title"].strip())
        key = (it["store"], code.group(1)) if code else (it["store"], re.sub(r"\b(" + "|".join(map(re.escape, it.get("colours", []) or ["~"])) + r")\b", "", norm(it["title"])).strip())
        if key in keys:
            continue
        if store_n[it["store"]] >= per_store or cat_n[it["category"]] >= per_category:
            continue
        keys.add(key)
        store_n[it["store"]] += 1
        cat_n[it["category"]] += 1
        out.append(it)
        if len(out) >= limit:
            break
    return out, rejected
