"""Shared paths, HTTP and JSON helpers. Standard library only."""
from __future__ import annotations

import gzip
import json
import os
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROFILE = ROOT / "profile" / "profile.toml"
HISTORY = DATA / "history.json"
STORES = DATA / "stores.json"
CACHE = ROOT / ".cache"
OUT = ROOT / "out"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def http_get(url: str, timeout: int = 30, retries: int = 2) -> bytes:
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                     "Accept-Encoding": "gzip", "Accept-Language": "en-IN,en;q=0.9"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 403, 401):
                raise
        except Exception as e:  # network hiccup
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def http_json(url: str, timeout: int = 30):
    return json.loads(http_get(url, timeout))


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_profile(path: Path = PROFILE) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_stores(path: Path = STORES) -> list[dict]:
    return [s for s in load_json(path)["stores"]]


def store_for_domain(domain: str) -> dict | None:
    d = domain.lower().removeprefix("www.").removeprefix("www2.")
    for s in load_stores():
        if s["domain"].lower().removeprefix("www.").removeprefix("www2.") == d:
            return s
    return None
