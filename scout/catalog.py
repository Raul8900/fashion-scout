"""Live catalogs from Shopify stores -> normalized items. Cached for a day in .cache/."""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import classify
from .common import CACHE, http_json, load_stores

CACHE_TTL = 20 * 3600
MAX_PAGES = 12          # x250 = up to 3000 products per store
PAGE_SIZE = 250


def _size_option_index(options: list[dict]) -> int | None:
    for i, o in enumerate(options):
        if o.get("name", "").strip().lower() in ("size", "sizes", "uk size", "shoe size", "waist", "waist size", "size (uk)"):
            return i
    for i, o in enumerate(options):
        vals = [str(v).upper() for v in o.get("values", [])]
        if vals and sum(v in ("XS", "S", "M", "L", "XL", "XXL") or v.replace(".", "").isdigit() or v.startswith("UK")
                        for v in vals) >= max(1, len(vals) // 2):
            return i
    return None


def _colour_option(options: list[dict]) -> int | None:
    for i, o in enumerate(options):
        if o.get("name", "").strip().lower() in ("color", "colour", "colors", "colours", "shade"):
            return i
    return None


def normalize(p: dict, store: dict) -> dict:
    domain = store["domain"]
    title = p.get("title", "")
    ptype = p.get("product_type", "") or ""
    tags = p.get("tags", []) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    desc = classify.strip_html(p.get("body_html"))
    cat = classify.categorize(title, ptype, tags)
    if store.get("only") == "footwear" and classify.CATEGORY_GROUP.get(cat) != "footwear":
        t = classify.norm(title + " " + ptype)
        cat = ("loafers" if "loafer" in t or "mocc" in t else
               "boots" if "boot" in t else
               "formal-shoes" if any(k in t for k in ("oxford", "derby", "brogue", "monk")) else
               "sneakers" if cat in ("other", "shirt", "tshirt") else cat)
    options = p.get("options", []) or []
    si, ci = _size_option_index(options), _colour_option(options)
    sizes: dict[str, bool] = {}
    prices = []
    compare = []
    colour_vals = set()
    for v in p.get("variants", []) or []:
        opts = [v.get("option1"), v.get("option2"), v.get("option3")]
        label = str(opts[si]) if si is not None and opts[si] is not None else v.get("title", "")
        avail = bool(v.get("available", False))
        sizes[label] = sizes.get(label, False) or avail
        try:
            prices.append(float(v.get("price") or 0))
            if v.get("compare_at_price"):
                compare.append(float(v["compare_at_price"]))
        except (TypeError, ValueError):
            pass
        if ci is not None and opts[ci]:
            colour_vals.add(str(opts[ci]))
    price = min([x for x in prices if x > 0], default=0.0)
    mrp = max(compare, default=0.0)
    imgs = [i.get("src") for i in (p.get("images") or []) if i.get("src")]
    return {
        "id": f"{domain}:{p.get('id')}",
        "store": store["name"],
        "domain": domain,
        "tier": store.get("tier"),
        "source": "shopify",
        "title": title,
        "handle": p.get("handle"),
        "url": f"https://{domain}/products/{p.get('handle')}",
        "product_type": ptype,
        "tags": tags,
        "category": cat,
        "group": classify.CATEGORY_GROUP.get(cat, "other"),
        "gender": classify.gender(title, ptype, tags),
        "colours": classify.colours(title, " ".join(colour_vals), " ".join(tags)),
        "description": desc[:2500],
        "price": price,
        "mrp": mrp if mrp > price else 0.0,
        "sizes": sizes,
        "any_available": any(sizes.values()),
        "images": imgs[:4],
        "published_at": p.get("published_at") or p.get("created_at"),
    }


def fetch_store(store: dict, refresh: bool = False, max_pages: int = MAX_PAGES) -> list[dict]:
    CACHE.mkdir(exist_ok=True)
    cpath = CACHE / f"catalog_{store['domain']}.json"
    if not refresh and cpath.exists() and time.time() - cpath.stat().st_mtime < CACHE_TTL:
        raw = json.loads(cpath.read_text())
    else:
        raw = []
        for page in range(1, max_pages + 1):
            url = f"https://{store['domain']}/products.json?limit={PAGE_SIZE}&page={page}"
            try:
                batch = http_json(url, timeout=40).get("products", [])
            except Exception as e:
                print(f"  ! {store['name']} page {page}: {e}", file=sys.stderr)
                break
            raw.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        if raw:
            cpath.write_text(json.dumps(raw))
    return [normalize(p, store) for p in raw]


def fetch_all(refresh: bool = False, only: list[str] | None = None, workers: int = 8) -> tuple[list[dict], dict]:
    stores = [s for s in load_stores() if s.get("enabled") and s["kind"] == "shopify"]
    if only:
        o = {x.lower() for x in only}
        stores = [s for s in stores if s["name"].lower() in o or s["domain"].lower() in o]
    items: list[dict] = []
    report: dict[str, int | str] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_store, s, refresh): s for s in stores}
        for f in as_completed(futs):
            s = futs[f]
            try:
                got = f.result()
                items.extend(got)
                report[s["name"]] = len(got)
            except Exception as e:  # never let one store kill the run
                report[s["name"]] = f"error: {e}"
    return items, report
