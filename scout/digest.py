"""Picks -> Gmail-ready email (HTML with inline photos) + a contact sheet for visual review."""
from __future__ import annotations

import hashlib
import html
import io
import re
from datetime import datetime
from pathlib import Path

from .common import OUT, http_get

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # Pillow optional: email still works with original images
    Image = None

INK, MUTED, LINE, BG, CARD, ACCENT, GOOD, WARN = "#1d1d1b", "#6b6862", "#e6e1d8", "#f6f3ee", "#ffffff", "#2f4a3a", "#2f6b46", "#9a5b13"


def _sized_url(u: str, width: int) -> str:
    if "cdn.shopify.com" in u or "/cdn/shop/" in u:
        u = re.sub(r"([?&])width=\d+", r"\1", u)
        return u + ("&" if "?" in u else "?") + f"width={width}"
    return u


def fetch_image(url: str, dest: Path, width: int = 560) -> Path | None:
    try:
        raw = http_get(_sized_url(url, width), timeout=40)
    except Exception:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if Image is None:
        dest.write_bytes(raw)
        return dest
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        # crop to 4:5 so cards line up
        target_h = round(im.width * 5 / 4)
        if im.height > target_h:
            top = max(0, (im.height - target_h) // 6)
            im = im.crop((0, top, im.width, top + target_h))
        im.save(dest, "JPEG", quality=82, optimize=True, progressive=True)
        return dest
    except Exception:
        dest.write_bytes(raw)
        return dest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inr(x) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ""
    s = f"{x:,.0f}"
    # Indian grouping: 1,23,456
    n = f"{int(round(x))}"
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return "₹" + s


def _size_badge(p: dict) -> tuple[str, str]:
    st, lbl = p.get("size_status"), p.get("size_label")
    if st == "in_stock":
        return f"Your size ({lbl}) in stock", GOOD
    if st == "in_stock_size_unknown":
        return "In stock · check your size", WARN
    if st == "unknown_profile":
        return "In stock · add your size to profile", WARN
    if st == "sold_out":
        return f"{lbl} sold out", "#a33"
    return "Stock not verified", WARN


def _card(n: int, p: dict, cid: str | None, label: str = "") -> str:
    e = html.escape
    name = e(p.get("display_name") or p.get("title", ""))
    price = _inr(p.get("price"))
    mrp = p.get("mrp") or 0
    off = ""
    if mrp and mrp > (p.get("price") or 0):
        off = (f' <span style="color:{MUTED};text-decoration:line-through;font-weight:400">{_inr(mrp)}</span>'
               f' <span style="color:{GOOD};font-weight:600">{round((1 - p["price"] / mrp) * 100)}% off</span>')
    badge, colour = _size_badge(p)
    q = p.get("quality") or {}
    qr = ", ".join(r.lstrip("+") for r in (q.get("reasons") or []) if r.startswith("+"))[:120]
    qline = f'Quality {q.get("score", "–")}/10' + (f" · {e(qr)}" if qr else "")
    img = (f'<a href="{e(p["url"])}"><img src="cid:{cid}" width="260" alt="{name}" '
           f'style="display:block;width:100%;max-width:260px;height:auto;border-radius:6px;border:0"></a>') if cid else ""
    why = e(p.get("why", ""))
    pairs = e(p.get("pairs_with", ""))
    tag = f'<div style="font:600 11px/1.2 Helvetica,Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:{ACCENT};margin:0 0 6px">{e(label)}</div>' if label else ""
    return f"""
<tr><td style="padding:0 0 18px">
 <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD};border:1px solid {LINE};border-radius:10px">
  <tr>
   <td width="42%" valign="top" style="padding:14px 0 14px 14px">{img}</td>
   <td valign="top" style="padding:14px 16px;font:14px/1.45 Helvetica,Arial,sans-serif;color:{INK}">
    {tag}<div style="font:700 13px/1 Helvetica,Arial,sans-serif;color:{MUTED};margin-bottom:6px">#{n} · {e(p.get('store',''))}</div>
    <div style="font:600 17px/1.3 Georgia,serif;margin:0 0 6px"><a href="{e(p['url'])}" style="color:{INK};text-decoration:none">{name}</a></div>
    <div style="font-size:16px;font-weight:700;margin:0 0 8px">{price}{off}</div>
    <div style="display:inline-block;font-size:12px;font-weight:600;color:{colour};border:1px solid {colour};border-radius:20px;padding:2px 9px;margin:0 0 10px">{e(badge)}</div>
    <div style="font-size:12px;color:{MUTED};margin:0 0 10px">{qline}</div>
    {f'<div style="margin:0 0 8px">{why}</div>' if why else ''}
    {f'<div style="margin:0 0 12px;color:{MUTED}"><b style="color:{INK}">Wear it with:</b> {pairs}</div>' if pairs else ''}
    <a href="{e(p['url'])}" style="display:inline-block;background:{INK};color:#fff;text-decoration:none;font-weight:600;font-size:13px;padding:8px 14px;border-radius:6px">View at {e(p.get('store',''))} →</a>
   </td>
  </tr>
 </table>
</td></tr>"""


def build_email(picks: dict, profile: dict, history: dict, watch: list | None = None) -> dict:
    run_id = picks.get("run_id") or datetime.now().date().isoformat()
    items = list(picks["picks"]) + ([picks["wildcard"]] if picks.get("wildcard") else [])
    missing = [p.get("title") for p in items if not p.get("why")]
    if missing:
        raise SystemExit(f"picks missing 'why' text: {missing}. Write it before building the digest.")
    img_dir = OUT / "img"
    attachments, cards = [], []
    for n, p in enumerate(items, 1):
        cid = None
        src = (p.get("images") or [None])[0]
        if src:
            path = fetch_image(src, img_dir / f"{run_id}_pick{n}.jpg")
            if path:
                cid = f"att{len(attachments)}"
                attachments.append({"filename": path.name, "mimeType": "image/jpeg", "inline": True,
                                    "content": f"sha256:{_sha(path)}:{path.resolve().as_posix()}"})
        label = "Wildcard" if picks.get("wildcard") is p else ""
        cards.append(_card(n, p, cid, label))
    watch_html = ""
    if watch:
        rows = "".join(
            f'<li style="margin:0 0 6px"><a href="{html.escape(w["url"])}" style="color:{INK}">{html.escape(w["title"])}</a> '
            f'({html.escape(w["store"])}): <b style="color:{GOOD}">{html.escape(w["event"])}</b></li>' for w in watch)
        watch_html = (f'<tr><td style="padding:0 0 18px;font:14px/1.5 Helvetica,Arial,sans-serif;color:{INK}">'
                      f'<div style="font:600 16px Georgia,serif;margin:0 0 8px">From your watchlist</div><ul style="margin:0;padding-left:18px">{rows}</ul></td></tr>')
    p0 = picks.get("plan", {})
    d = datetime.fromisoformat(run_id).strftime("%-d %b")
    focus = (picks.get("focus") or p0.get("focus_group") or "").title()
    sale = picks.get("sale_note") or ""
    intro = html.escape(picks.get("intro", ""))
    outfit = html.escape(picks.get("outfit", ""))
    n = len(items)
    subject = picks.get("subject") or f"Fashion Scout · {d} · {n} picks ({focus})"
    reply_help = (f"Reply to this email to teach me. One line per pick, e.g.<br>"
                  f"<code>1 love</code> · <code>2 skip, collar looks flimsy</code> · <code>3 bought L</code> · <code>4 save</code><br>"
                  f"Saved items get watched for price drops; <i>bought</i> teaches me your size at that brand.")
    body = f"""<!doctype html><html><body style="margin:0;padding:0;background:{BG}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%">
 <tr><td style="padding:0 0 4px;font:700 12px/1 Helvetica,Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:{ACCENT}">Fashion Scout · week of {d}</td></tr>
 <tr><td style="padding:6px 0 6px;font:600 26px/1.2 Georgia,serif;color:{INK}">{html.escape(picks.get('headline') or f'{focus} edit')}</td></tr>
 <tr><td style="padding:0 0 18px;font:14px/1.5 Helvetica,Arial,sans-serif;color:{MUTED}">{intro}{('<br><b style="color:' + GOOD + '">' + html.escape(sale) + '</b>') if sale else ''}</td></tr>
 {f'<tr><td style="padding:0 0 18px"><div style="padding:10px 14px;border-left:3px solid {ACCENT};background:{CARD};font:13px/1.5 Helvetica,Arial,sans-serif;color:{INK}"><b>From your last reply:</b> {html.escape(picks["learned_note"])}</div></td></tr>' if picks.get("learned_note") else ''}
 {''.join(cards)}
 {f'<tr><td style="padding:0 0 18px;font:14px/1.5 Helvetica,Arial,sans-serif;color:{INK}"><div style="font:600 16px Georgia,serif;margin:0 0 6px">One outfit from this week</div>{outfit}</td></tr>' if outfit else ''}
 {watch_html}
 <tr><td style="padding:14px 16px;background:{CARD};border:1px dashed {LINE};border-radius:10px;font:13px/1.6 Helvetica,Arial,sans-serif;color:{MUTED}">{reply_help}</td></tr>
 <tr><td style="padding:14px 0 0;font:11px/1.5 Helvetica,Arial,sans-serif;color:{MUTED}">Prices and stock checked live {html.escape(picks.get('checked_note', 'just before sending'))}; they can change. Size and stock come from each store's own product data.</td></tr>
</table></td></tr></table></body></html>"""
    plain = [f"Fashion Scout, week of {d}: {focus}", picks.get("intro", ""), ""]
    for i, p in enumerate(items, 1):
        plain += [f"{i}. {p.get('display_name') or p['title']} ({p['store']}) {_inr(p.get('price'))}",
                  f"   {_size_badge(p)[0]}", f"   {p.get('why','')}", f"   {p['url']}", ""]
    plain += ["Reply: '1 love', '2 skip, reason', '3 bought L', '4 save'"]
    (OUT / "digest_preview.html").write_text(
        re.sub(r'src="cid:att(\d+)"', lambda m: f'src="img/{Path(attachments[int(m.group(1))]["filename"]).name}"', body),
        encoding="utf-8")
    to = profile.get("delivery", {}).get("email") or ""
    return {"to": [to] if to else [], "subject": subject, "htmlBody": body, "body": "\n".join(plain),
            "attachments": attachments}


def contact_sheet(cands: list[dict], dest: Path, cols: int = 6, w: int = 220) -> str:
    """Grid of candidate photos with index numbers, for Claude to eyeball style before choosing."""
    if Image is None:
        return "Pillow not installed; open candidate image URLs individually instead."
    h = round(w * 5 / 4)
    cap = 44
    rows = (len(cands) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + cap)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 13)
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = big = ImageFont.load_default()
    tmp = OUT / "img" / "sheet"
    for i, c in enumerate(cands):
        x, y = (i % cols) * w, (i // cols) * (h + cap)
        src = (c.get("images") or [None])[0]
        if src:
            p = fetch_image(src, tmp / f"c{i}.jpg", width=w)
            if p:
                try:
                    im = Image.open(p).convert("RGB")
                    im = im.resize((w, round(im.height * w / im.width)))
                    sheet.paste(im.crop((0, 0, w, min(h, im.height))), (x, y))
                except Exception:
                    pass
        draw.rectangle([x, y, x + 34, y + 26], fill="black")
        draw.text((x + 5, y + 3), str(i + 1), fill="white", font=big)
        draw.text((x + 4, y + h + 3), f"{c['store'][:14]} ₹{c['price']:.0f}", fill="black", font=font)
        draw.text((x + 4, y + h + 21), c["title"][:30], fill="#555", font=font)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "PNG")
    return str(dest)
