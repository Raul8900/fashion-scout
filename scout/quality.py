"""Fabric / construction quality from product text.

Gives a 0-10 quality score with human-readable reasons. The point is the user's rule:
"price must be justified by quality" -> we need evidence of quality, not vibes.
"""
from __future__ import annotations

import math
import re

from .classify import CATEGORY_GROUP

# (pattern, points, label, applies_to_groups or None for all)
SIGNALS: list[tuple[str, float, str, tuple[str, ...] | None]] = [
    (r"\b100\s*%\s*(pure\s+)?cotton\b|\bpure cotton\b|\ball[- ]cotton\b", 2.5, "100% cotton", None),
    (r"\bsupima\b|\bpima\b|\begyptian cotton\b|\bgiza\b|\blong[- ]staple\b", 2.5, "long-staple cotton", None),
    (r"\bmerceri[sz]ed\b", 1.0, "mercerised", None),
    (r"\b100\s*%\s*linen\b|\bpure linen\b", 2.5, "pure linen", None),
    (r"\blinen\b", 1.0, "linen", None),
    (r"\bmerino\b", 3.0, "merino wool", None),
    (r"\blambswool\b|\bwool\b(?!\s*(look|feel|touch))", 1.8, "wool", None),
    (r"\bcashmere\b", 1.5, "cashmere blend", None),
    (r"\boxford\b", 1.2, "oxford weave", ("tops", "layers")),
    (r"\btwill\b|\bgabardine\b", 1.0, "twill", None),
    (r"\bselvedge\b|\bselvage\b", 2.0, "selvedge denim", None),
    (r"\bcorduroy\b|\bcord\b", 0.8, "corduroy", None),
    (r"\bflannel\b|\bbrushed\b", 0.8, "flannel/brushed", None),
    (r"\bfrench terry\b|\bloopback\b|\bloop[- ]knit\b", 1.5, "french terry", ("layers", "tops", "bottoms")),
    (r"\bpique\b|\bpiqué\b", 1.0, "pique knit", ("tops",)),
    (r"\bheavy ?weight\b|\bheavy[- ]gauge\b|\bthick\b", 1.0, "heavyweight", None),
    (r"\bgarment[- ]dyed\b|\bpigment[- ]dyed\b", 1.0, "garment-dyed", None),
    (r"\bbio[- ]?wash(ed)?\b|\benzyme[- ]wash(ed)?\b|\bpre[- ]?shrunk\b|\bsanfori[sz]ed\b", 0.6, "pre-washed/shrink-controlled", None),
    (r"\blyocell\b|\btencel\b|\bmodal\b", 0.8, "lyocell/modal", None),
    (r"\bslub\b|\bdobby\b|\bseersucker\b|\bwaffle\b|\bjacquard\b|\bherringbone\b|\bchambray\b", 0.6, "textured weave", None),
    (r"\bfull[- ]grain\b|\btop[- ]grain\b", 2.5, "full/top-grain leather", ("footwear",)),
    (r"\bgenuine leather\b|\b(100\s*%\s*)?leather upper\b|\bsuede\b|\bnubuck\b", 1.5, "real leather/suede", ("footwear",)),
    (r"\bgoodyear\b|\bwelted?\b", 2.5, "welted construction", ("footwear",)),
    (r"\bblake\b|\bhand[- ]?stitched\b|\bhandcrafted\b|\bhand[- ]?made\b", 1.2, "hand/blake stitched", ("footwear",)),
    (r"\bvulcani[sz]ed\b|\bnatural rubber\b|\bmemory foam\b|\bortholite\b|\bcushioned insole\b", 0.6, "good sole/insole", ("footwear",)),
    (r"\bmother[- ]of[- ]pearl\b|\bcorozo\b|\bhorn buttons?\b|\bykk\b|\briri\b", 0.8, "quality trims", None),
    (r"\bdouble[- ]needle\b|\bflat[- ]?lock\b|\bfelled seams?\b|\bsingle[- ]needle\b|\bbar[- ]?tack", 0.7, "good stitching", None),
]

PENALTIES: list[tuple[str, float, str, tuple[str, ...] | None]] = [
    (r"\bacrylic\b", -2.5, "acrylic", None),
    (r"\b(pu|faux|vegan|synthetic|artificial)\s+leather\b|\bpu\b|\bleatherette\b|\brexine\b", -2.5, "synthetic leather", None),
    (r"\b100\s*%\s*polyester\b|\bpure polyester\b", -3.0, "100% polyester", ("tops", "layers", "bottoms")),
    (r"\bcotton[- ]?blend\b|\bpoly[- ]?cotton\b|\bcotton[- ]poly\b", -0.8, "cotton blend", ("tops", "bottoms")),
    (r"\bviscose\b|\brayon\b", -0.6, "viscose/rayon", ("layers", "bottoms")),
    (r"\bfusible\b|\bglued\b|\bcemented\b", -0.5, "glued/fused", None),
]

_pct = re.compile(r"(\d{1,3})\s*%\s*([a-z]+(?:\s+[a-z]+)?)")
_gsm = re.compile(r"(\d{3})\s*gsm\b")


def composition(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for pct, fib in _pct.findall(text):
        f = fib.split()[0]
        if f in {"cotton", "linen", "wool", "merino", "polyester", "poly", "viscose", "rayon", "elastane",
                 "spandex", "lycra", "nylon", "polyamide", "acrylic", "modal", "lyocell", "tencel", "cashmere",
                 "silk", "hemp", "leather"}:
            f = {"poly": "polyester", "spandex": "elastane", "lycra": "elastane", "polyamide": "nylon",
                 "tencel": "lyocell"}.get(f, f)
            out[f] = max(out.get(f, 0), int(pct))
    return out


def score(text: str, category: str) -> dict:
    """-> {'score': 0-10, 'known': bool, 'reasons': [...], 'composition': {...}, 'gsm': int|None}"""
    t = re.sub(r"\s+", " ", text.lower())
    group = CATEGORY_GROUP.get(category, "other")
    pts, reasons, seen = 0.0, [], set()
    for pat, p, label, groups in SIGNALS + PENALTIES:
        if groups and group not in groups:
            continue
        if label in seen:
            continue
        if re.search(pat, t):
            # avoid double-counting "linen" when "pure linen" already hit, etc.
            if label == "linen" and "pure linen" in seen:
                continue
            if label == "wool" and "merino wool" in seen:
                continue
            pts += p
            seen.add(label)
            reasons.append(("+" if p > 0 else "-") + label)

    comp = composition(t)
    synth = comp.get("polyester", 0) + comp.get("nylon", 0) + comp.get("acrylic", 0)
    natural = sum(comp.get(k, 0) for k in ("cotton", "linen", "wool", "merino", "cashmere", "silk", "hemp", "lyocell", "modal"))
    if comp:
        if synth >= 50 and group in ("tops", "bottoms") and "100% polyester" not in seen:
            pts -= 2.0; reasons.append(f"-{synth}% synthetic")
        elif synth >= 60 and group == "layers" and not re.search(r"puffer|padded|windcheater|rain|shell", t):
            pts -= 1.5; reasons.append(f"-{synth}% synthetic")
        if natural >= 95 and "100% cotton" not in seen and "pure linen" not in seen:
            pts += 1.5; reasons.append(f"+{natural}% natural fibre")
        if comp.get("elastane", 0) > 5:
            pts -= 0.5; reasons.append(f"-{comp['elastane']}% elastane")

    gsm = None
    m = _gsm.search(t)
    if m:
        gsm = int(m.group(1))
        if category in ("tshirt", "polo"):
            if gsm >= 220: pts += 1.5; reasons.append(f"+{gsm} GSM heavyweight")
            elif gsm >= 180: pts += 0.8; reasons.append(f"+{gsm} GSM")
            elif gsm < 150: pts -= 0.8; reasons.append(f"-{gsm} GSM thin")
        elif category in ("sweatshirt",) and gsm >= 300:
            pts += 1.2; reasons.append(f"+{gsm} GSM")

    known = bool(comp) or any(r.lstrip("+-") in {s[2] for s in SIGNALS + PENALTIES} for r in reasons) or bool(
        re.search(r"\bcotton\b|\bpolyester\b|\bleather\b|\bdenim\b|\bfleece\b|\bknit\b", t))
    if not known:
        pts -= 1.0
        reasons.append("-fabric not stated")
    # diminishing returns: marketing copy that name-drops five fabrics shouldn't max out the scale
    final = 5.0 + 5.0 * math.tanh(pts / 5.0)
    return {"score": round(final, 1), "known": known, "reasons": reasons,
            "composition": comp, "gsm": gsm}
