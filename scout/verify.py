"""Verify a single product URL right now: live price, per-size stock, in-stock-in-MY-size.

Methods, in order:
  1. Shopify product JSON (`<url>.js`), works for any Shopify store, even ones not in the registry.
  2. Headless Chromium + JSON-LD (Flipkart, Tata CLiQ, M&S, Souled Store, most big shops).
  3. Give up honestly -> status 'unverified'.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
from datetime import datetime, timezone

from . import catalog, classify, quality, sizing
from .common import ROOT, http_json, load_profile, store_for_domain


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _shopify_js(url: str) -> dict | None:
    u = urllib.parse.urlsplit(url)
    m = re.search(r"/products/([^/?#]+)", u.path)
    if not m:
        return None
    js = f"{u.scheme}://{u.netloc}/products/{m.group(1)}.js"
    try:
        p = http_json(js, timeout=30)
    except Exception:
        return None
    # .js has prices in paise and options as list of {name, values}
    variants = []
    for v in p.get("variants", []):
        variants.append({
            "option1": v.get("option1"), "option2": v.get("option2"), "option3": v.get("option3"),
            "title": v.get("title"), "available": v.get("available"),
            "price": (v.get("price") or 0) / 100, "compare_at_price": (v.get("compare_at_price") or 0) / 100 or None,
        })
    raw = {
        "id": p.get("id"), "title": p.get("title"), "handle": p.get("handle"),
        "product_type": p.get("type", ""), "tags": p.get("tags", []), "body_html": p.get("description", ""),
        "options": [{"name": o.get("name"), "values": o.get("values", [])} if isinstance(o, dict) else {"name": o, "values": []}
                    for o in p.get("options", [])],
        "variants": variants,
        "images": [{"src": ("https:" + s if s.startswith("//") else s)} for s in p.get("images", [])],
        "published_at": p.get("published_at"),
    }
    store = store_for_domain(u.netloc) or {"name": u.netloc.removeprefix("www."), "domain": u.netloc, "tier": "unknown"}
    item = catalog.normalize(raw, store)
    item["url"] = f"{u.scheme}://{u.netloc}/products/{m.group(1)}"
    item["method"] = "shopify"
    return item


def _walk_ld(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _walk_ld(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "hasVariant", "offers", "itemListElement"):
            if k in obj:
                yield from _walk_ld(obj[k])


def _avail(s) -> bool | None:
    if s is None:
        return None
    s = str(s).lower()
    if "instock" in s or "limitedavailability" in s or "preorder" in s:
        return True
    if "outofstock" in s or "soldout" in s or "discontinued" in s:
        return False
    return None


def _browser(url: str) -> dict | None:
    try:
        r = subprocess.run(["node", str(ROOT / "tools" / "pagefetch.js"), url], capture_output=True, text=True, timeout=150)
        page = json.loads(r.stdout or "{}")
    except Exception as e:
        return {"method": "browser", "error": str(e)}
    if page.get("error") or (page.get("status") or 0) >= 400:
        return {"method": "browser", "error": page.get("error") or f"HTTP {page.get('status')}"}
    name = desc = brand = None
    images: list[str] = []
    prices: list[float] = []
    mrp = 0.0
    sizes: dict[str, bool] = {}
    overall = None
    for node in _walk_ld(page.get("jsonld", [])):
        t = node.get("@type")
        t = " ".join(t) if isinstance(t, list) else str(t or "")
        if "Product" in t:
            name = name or node.get("name")
            desc = desc or node.get("description")
            b = node.get("brand")
            brand = brand or (b.get("name") if isinstance(b, dict) else b)
            img = node.get("image")
            for i in (img if isinstance(img, list) else [img]):
                if isinstance(i, dict):
                    i = i.get("url") or i.get("contentUrl")
                if isinstance(i, str) and i.startswith("//"):
                    i = "https:" + i
                if isinstance(i, str) and i not in images:
                    images.append(i)
            sz = node.get("size")
            if sz and isinstance(node.get("offers"), (dict, list)):
                offs = node["offers"] if isinstance(node["offers"], list) else [node["offers"]]
                a = any(_avail(o.get("availability")) for o in offs if isinstance(o, dict))
                sizes[str(sz)] = sizes.get(str(sz), False) or bool(a)
        if "Offer" in t:
            for k in ("price", "lowPrice"):
                try:
                    if node.get(k) not in (None, ""):
                        prices.append(float(str(node[k]).replace(",", "")))
                except ValueError:
                    pass
            try:
                if node.get("highPrice"):
                    mrp = max(mrp, float(node["highPrice"]))
            except ValueError:
                pass
            a = _avail(node.get("availability"))
            overall = a if overall is None else (overall or bool(a))
    og = page.get("og", {})
    name = name or og.get("og:title") or page.get("title")
    if not images and og.get("og:image"):
        images = [og["og:image"]]
    if not prices and og.get("product:price:amount"):
        try:
            prices.append(float(og["product:price:amount"]))
        except ValueError:
            pass
    if not sizes and page.get("sizes"):
        sizes = {k: bool(v) for k, v in page["sizes"].items()}
        sizes_src = "page buttons (best effort)"
    else:
        sizes_src = "structured data" if sizes else None
    if not name:
        return {"method": "browser", "error": "no product data on page"}
    u = urllib.parse.urlsplit(page.get("url") or url)
    store = store_for_domain(u.netloc) or {"name": u.netloc.removeprefix("www."), "domain": u.netloc, "tier": "unknown"}
    cat = classify.categorize(name or "")
    price = min([p for p in prices if p > 0], default=0.0)
    return {
        "id": f"{u.netloc}:{u.path}", "store": store["name"], "domain": u.netloc, "tier": store.get("tier"),
        "source": "browser", "method": "browser", "title": name, "brand": brand, "url": page.get("url") or url,
        "category": cat, "group": classify.CATEGORY_GROUP.get(cat, "other"),
        "gender": classify.gender(name or "", url=url), "colours": classify.colours(name or "", desc or ""),
        "description": classify.strip_html(desc)[:2500] if desc else (page.get("text") or "")[:1500],
        "price": price, "mrp": mrp if mrp > price else 0.0, "sizes": sizes, "sizes_source": sizes_src,
        "any_available": overall if overall is not None else (any(sizes.values()) if sizes else None),
        "images": images[:4],
    }


def verify(url: str, category: str | None = None, profile: dict | None = None, learned_sizes: dict | None = None) -> dict:
    profile = profile or load_profile()
    item = _shopify_js(url)
    if item is None:
        item = _browser(url)
    if not item or item.get("error"):
        st = store_for_domain(urllib.parse.urlsplit(url).netloc)
        return {"url": url, "status": "unverified", "reason": (item or {}).get("error", "could not read page"),
                "store": st["name"] if st else None, "checked_at": _now()}
    if category:
        item["category"] = category
        item["group"] = classify.CATEGORY_GROUP.get(category, "other")
    want = sizing.wanted_size(profile, item["category"], item["store"], learned_sizes)
    status, label = sizing.size_status(item.get("sizes") or {}, want)
    if status == "no_sizes" and item.get("any_available") is not None:
        status = "in_stock_size_unknown" if item["any_available"] else "sold_out"
    item["size_status"], item["size_label"] = status, label
    item["want_size"] = want
    item["quality"] = quality.score(f"{item['title']} {item.get('product_type','')} {' '.join(item.get('tags', []))} {item.get('description','')}",
                                    item["category"])
    item["status"] = "verified" if status in ("in_stock", "sold_out", "not_offered") else "partial"
    item["checked_at"] = _now()
    return item
