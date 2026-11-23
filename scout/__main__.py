"""Fashion Scout CLI.  Run from the repo root:  python3 -m scout <command>

  plan                         what this week focuses on (season, rotation, sales)
  harvest [--group G ...]      pull live catalogs, filter, score -> out/candidates.json
  sheet [--top N]              contact sheet of candidate photos -> out/sheet.png (for visual review)
  verify URL [--category C]    re-check one product right now (price, my size in stock, fabric)
  pick N|URL ... [--wildcard N|URL]   live-verify chosen candidates (by number) or any product URL -> out/picks.json
  digest picks.json            build email (HTML + inline photos) -> out/email.json
  record picks.json            save this week's picks to history (anti-repeat + feedback targets)
  set-thread RUN THREAD [MSG]  remember the Gmail thread the digest went out in
  feedback RUN --text "..."    apply a reply like "1 love, 2 skip collar looks cheap, 3 bought L"
  watch                        re-check liked/saved items for price drops or restocks -> out/watch.json
  stats                        what the scout has learned so far
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

from . import catalog, history, plan as planmod, rank, verify as verifymod
from .common import OUT, load_profile, save_json, load_json


def cmd_plan(a):
    p = planmod.make_plan(load_profile(), history.load())
    print(json.dumps(p, indent=2))


def _slim(it: dict) -> dict:
    keep = ("id", "store", "title", "url", "category", "group", "price", "mrp", "colours", "size_status", "size_label",
            "score", "breakdown", "notes", "price_vs_median", "images", "tier", "source")
    d = {k: it.get(k) for k in keep}
    q = it.get("quality") or {}
    d["quality"] = {"score": q.get("score"), "reasons": q.get("reasons"), "composition": q.get("composition")}
    d["description"] = (it.get("description") or "")[:600]
    d["sizes"] = it.get("sizes")
    return d


def cmd_harvest(a):
    t0 = time.time()
    prof, h = load_profile(), history.load()
    p = planmod.make_plan(prof, h)
    items, report = catalog.fetch_all(refresh=a.refresh, only=a.store)
    cats = Counter(i["category"] for i in items)
    groups = a.group or None
    ranked, rejected = rank.rank(items, prof, p, h, groups=groups, per_store=a.per_store, limit=a.limit)
    out = {"plan": p, "scanned": len(items), "stores": report, "categories_seen": dict(cats.most_common()),
           "rejected": dict(rejected.most_common()), "candidates": [_slim(x) for x in ranked],
           "seconds": round(time.time() - t0, 1)}
    save_json(OUT / "candidates.json", out)
    print(f"scanned {len(items)} products from {len(report)} stores in {out['seconds']}s; "
          f"{len(ranked)} candidates -> out/candidates.json")
    print("rejected:", dict(rejected.most_common(8)))
    for i, c in enumerate(ranked[: a.show], 1):
        q = c["quality"]
        print(f"{i:>2}. {c['score']:>5}  ₹{c['price']:<6.0f} q{q['score']:<4} {c['category']:<10} {c['store'][:16]:<16} "
              f"{c['title'][:60]}  [{c.get('size_label') or c.get('size_status')}]")


def cmd_sheet(a):
    from .digest import contact_sheet
    data = load_json(OUT / "candidates.json")
    if not data:
        sys.exit("run harvest first")
    path = contact_sheet(data["candidates"][: a.top], OUT / "sheet.png")
    print(path)


def cmd_verify(a):
    h = history.load()
    r = verifymod.verify(a.url, category=a.category, learned_sizes=h["learned"].get("sizes"))
    r.pop("description", None) if not a.full else None
    print(json.dumps(r, indent=2, ensure_ascii=False))


def cmd_pick(a):
    """Re-verify each chosen item live and write the picks skeleton Claude then annotates."""
    prof, h = load_profile(), history.load()
    data = load_json(OUT / "candidates.json") or {"candidates": [], "plan": planmod.make_plan(prof, h)}
    cands = data["candidates"]

    def resolve(ref: str) -> dict:
        base = {}
        if ref.isdigit():
            base = cands[int(ref) - 1]
            url = base["url"]
        else:
            url = ref
        r = verifymod.verify(url, category=base.get("category"), profile=prof, learned_sizes=h["learned"].get("sizes"))
        if r.get("status") == "unverified":
            print(f"  ! could not verify {url}: {r.get('reason')}", file=sys.stderr)
            r = {**base, **r, "size_status": "unverified"}
        if r.get("size_status") in ("sold_out", "not_offered"):
            print(f"  ! {r.get('title')}: your size is {r['size_status'].replace('_', ' ')} -> pick another", file=sys.stderr)
        slim = _slim({**base, **{k: v for k, v in r.items() if v not in (None, "", [], {})}})
        slim["checked_at"] = r.get("checked_at")
        slim.update({"display_name": "", "why": "", "pairs_with": ""})
        return slim

    picks = [resolve(x) for x in a.refs]
    wild = resolve(a.wildcard) if a.wildcard else None
    out = {"run_id": data["plan"]["run_id"], "focus": data["plan"]["focus_group"], "plan": data["plan"],
           "headline": "", "intro": "", "outfit": "", "sale_note": "", "picks": picks, "wildcard": wild}
    save_json(OUT / "picks.json", out)
    for i, p in enumerate(picks + ([wild] if wild else []), 1):
        print(f"{i}. [{p.get('size_status')}] ₹{p.get('price')} {p.get('store')} | {p.get('title')}")
    print("-> out/picks.json  (now fill headline, intro, display_name, why, pairs_with, outfit)")


def cmd_digest(a):
    from .digest import build_email
    picks = load_json(a.picks)
    prof = load_profile()
    email = build_email(picks, prof, history.load(), watch=load_json(OUT / "watch.json", default=None))
    save_json(OUT / "email.json", email)
    print(f"out/email.json  subject: {email['subject']}  ({len(email['attachments'])} inline photos)")
    print(f"preview: {OUT / 'digest_preview.html'}")


def cmd_record(a):
    picks = load_json(a.picks)
    h = history.load()
    p = planmod.make_plan(load_profile(), h)
    all_picks = picks["picks"] + ([picks["wildcard"]] if picks.get("wildcard") else [])
    history.record_run(h, picks.get("run_id") or p["run_id"], picks.get("focus") or p["focus_group"], all_picks)
    history.save(h)
    print(f"recorded {len(all_picks)} picks for run {picks.get('run_id') or p['run_id']}")


def cmd_set_thread(a):
    h = history.load()
    for r in h["runs"]:
        if r["run_id"] == a.run:
            r["thread_id"], r["message_id"] = a.thread, a.message
            history.save(h)
            print("ok")
            return
    sys.exit(f"no run {a.run}")


def cmd_feedback(a):
    from .feedback import apply_reply
    h = history.load()
    text = a.text if a.text is not None else open(a.file, encoding="utf-8").read()
    res = apply_reply(h, a.run, text)
    history.save(h)
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_watch(a):
    h = history.load()
    out = []
    for item_id, it in history.watchlist(h):
        r = verifymod.verify(it["url"], category=it.get("category"), learned_sizes=h["learned"].get("sizes"))
        if r.get("status") == "unverified":
            continue
        old = it.get("last_price") or it.get("price_at_pick") or 0
        new = r.get("price") or 0
        event = None
        if old and new and new <= old * 0.9:
            event = f"price drop ₹{old:.0f} → ₹{new:.0f}"
        elif it.get("last_size_status") in ("sold_out", "not_offered") and r.get("size_status") == "in_stock":
            event = "back in stock in your size"
        it["last_price"], it["last_size_status"], it["last_checked"] = new, r.get("size_status"), r.get("checked_at")
        if event:
            out.append({"id": item_id, "title": it["title"], "store": it["store"], "url": it["url"], "event": event,
                        "price": new, "images": r.get("images", [])[:1], "size_status": r.get("size_status")})
    history.save(h)
    save_json(OUT / "watch.json", out)
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_stats(a):
    h = history.load()
    v = Counter(it.get("verdict") or "no reply" for it in h["items"].values())
    w = sorted(h["learned"]["weights"].items(), key=lambda kv: kv[1])
    print(json.dumps({"runs": len(h["runs"]), "items_shown": len(h["items"]), "verdicts": v,
                      "learned_sizes": h["learned"]["sizes"], "most_disliked": w[:6], "most_liked": w[-6:][::-1],
                      "taste_notes": h["taste_notes"][-5:]}, indent=2, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scout", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").set_defaults(f=cmd_plan)
    s = sub.add_parser("harvest")
    s.add_argument("--group", action="append", choices=["tops", "layers", "bottoms", "footwear"])
    s.add_argument("--store", action="append")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--limit", type=int, default=60)
    s.add_argument("--per-store", type=int, default=4)
    s.add_argument("--show", type=int, default=30)
    s.set_defaults(f=cmd_harvest)
    s = sub.add_parser("sheet"); s.add_argument("--top", type=int, default=30); s.set_defaults(f=cmd_sheet)
    s = sub.add_parser("verify"); s.add_argument("url"); s.add_argument("--category"); s.add_argument("--full", action="store_true")
    s.set_defaults(f=cmd_verify)
    s = sub.add_parser("pick"); s.add_argument("refs", nargs="+"); s.add_argument("--wildcard"); s.set_defaults(f=cmd_pick)
    s = sub.add_parser("digest"); s.add_argument("picks"); s.set_defaults(f=cmd_digest)
    s = sub.add_parser("record"); s.add_argument("picks"); s.set_defaults(f=cmd_record)
    s = sub.add_parser("set-thread"); s.add_argument("run"); s.add_argument("thread"); s.add_argument("message", nargs="?")
    s.set_defaults(f=cmd_set_thread)
    s = sub.add_parser("feedback"); s.add_argument("run"); s.add_argument("--text"); s.add_argument("--file")
    s.set_defaults(f=cmd_feedback)
    sub.add_parser("watch").set_defaults(f=cmd_watch)
    sub.add_parser("stats").set_defaults(f=cmd_stats)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
