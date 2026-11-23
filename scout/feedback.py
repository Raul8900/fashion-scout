"""Parse an email reply into verdicts.

Accepted shapes (one pick per line or comma/semicolon separated):
  1 love                    -> like
  2 skip collar looks cheap -> skip, note "collar looks cheap"
  3 bought L                -> bought, learns "L" as my size at that brand
  4 save / later / watch    -> save (watch for price drops)
  1,3 yes                   -> like both
  5 👍  / 5 👎
  wildcard skip             -> the wildcard is the last pick
Anything not tied to a number is returned as 'unparsed' for Claude to read and distil into taste notes.
"""
from __future__ import annotations

import re

VERBS = [
    ("bought", r"bought|ordered|purchased|got it|buying|order(ed)? it"),
    ("skip", r"skip|no\b|nah|pass|nope|hate|dislike|meh|not for me|don'?t like|👎|❌|ugly|cheap[- ]looking"),
    ("save", r"save|later|watch|maybe|wishlist|hold|if (it )?drops|price drop"),
    ("like", r"love|like|yes|yep|nice|great|good|cool|want|👍|❤️|😍|🔥|more like"),
]
SIZE = re.compile(r"\b(?:size\s*)?(XXS|XS|S|M|L|XL|XXL|2XL|3XL|UK\s?\d{1,2}(?:\.5)?|\d{2})\b", re.I)


def strip_quoted(text: str) -> str:
    """Remove the quoted original email from a reply."""
    lines = []
    for ln in text.splitlines():
        if ln.startswith(">"):
            continue
        if re.match(r"^\s*On .{5,120}wrote:\s*$", ln) or re.match(r"^-{2,}\s*Original Message", ln, re.I):
            break
        lines.append(ln)
    return "\n".join(lines).strip()


def parse(text: str, n_picks: int) -> tuple[list[dict], list[str]]:
    text = strip_quoted(text)
    chunks = [c.strip() for c in re.split(r"[\n;]+|,(?=\s*(?:#?\d|wildcard)\b)", text) if c.strip()]
    out: list[dict] = []
    unparsed: list[str] = []
    for c in chunks:
        m = re.match(r"^\s*(?:#|no\.?\s*|pick\s*)?((?:\d+\s*(?:,|&|and|\+|/)\s*)*\d+|wildcard|w)\b[\s:.)\-–—]*(.*)$", c, re.I)
        if not m:
            unparsed.append(c)
            continue
        nums_raw, rest = m.group(1), m.group(2).strip()
        if nums_raw.lower() in ("wildcard", "w"):
            nums = [n_picks]
        else:
            nums = [int(x) for x in re.findall(r"\d+", nums_raw)]
        nums = [n for n in nums if 1 <= n <= n_picks]
        if not nums:
            unparsed.append(c)
            continue
        verdict = None
        low = rest.lower()
        for v, pat in VERBS:
            if re.search(pat, low):
                verdict = v
                break
        size = None
        if verdict == "bought":
            sm = SIZE.search(rest)
            size = sm.group(1).upper().replace(" ", "") if sm else None
        note = re.sub(r"^(" + "|".join(p for _, p in VERBS) + r")[\s,:.\-–—]*", "", rest, flags=re.I).strip()
        for n in nums:
            out.append({"pick": n, "verdict": verdict or ("pending" if not rest else "note"), "note": note,
                        "size": size, "raw": c})
    # "1, 3 yes" splits into "1" and "3 yes": a bare number takes the next verdict.
    nxt = None
    for p in reversed(out):
        if p["verdict"] == "pending":
            p["verdict"] = nxt or "note"
        else:
            nxt = p["verdict"] if p["verdict"] != "note" else None
    return out, unparsed


def apply_reply(h: dict, run_id: str, text: str) -> dict:
    from .history import apply_verdict
    run = next((r for r in h["runs"] if r["run_id"] == run_id), None)
    if not run:
        return {"error": f"no run {run_id}"}
    picks = run["picks"]
    parsed, unparsed = parse(text, len(picks))
    applied = []
    for p in parsed:
        item_id = picks[p["pick"] - 1]
        if p["verdict"] == "note":
            h["items"][item_id].setdefault("notes", []).append(p["note"] or p["raw"])
        else:
            apply_verdict(h, item_id, p["verdict"], p["note"], p["size"])
        applied.append({**p, "title": h["items"][item_id]["title"], "store": h["items"][item_id]["store"]})
    run["feedback_done"] = True
    run["feedback_raw"] = strip_quoted(text)[:2000]
    return {"run": run_id, "applied": applied, "unparsed": unparsed}
