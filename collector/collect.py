#!/usr/bin/env python3
"""Collect the latest headlines (with photos) from every feed in sources.json, the newest
videos from news channels on YouTube, and one month of market prices.

Runs in GitHub Actions (full internet access) every morning and writes:
  out/latest.json   compact JSON the Claude routine reads to write the briefing
  out/img/<key>.jpg small JPEG copies of article photos and video thumbnails
                    (the Rotativa page cannot load images from other sites, so the
                    routine embeds these copies)

Usage: python collector/collect.py --out out/latest.json
"""
import argparse
import calendar
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import feedparser

try:
    from PIL import Image
except ImportError:  # photos are optional; the briefing still works without them
    Image = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# An honest feed-reader User-Agent: FAZ and others serve RSS to feed readers
# but show a bot-check page to browser-like agents.
UA = "NewsBriefingCollector/1.0 (personal RSS reader)"
TIMEOUT = 20
MAX_AGE_HOURS = 36          # default freshness window
SLOW_AGE_HOURS = 72         # for slow feeds (fetchNotes mention "slow" / "48")
MAX_ITEMS_PER_SOURCE = 15
UNDATED_KEEP = 8            # feeds without dates (e.g. Nikkei RSS 1.0): keep the first N
SUMMARY_CHARS = 220
PHOTOS_PER_SOURCE = 6       # download photos for the newest N items of each source
VIDEOS_PER_CHANNEL = 4
VIDEO_AGE_HOURS = 36
IMG_WIDTH = 480
IMG_QUALITY = 58
IMG_MAX_BYTES = 4_000_000

MARKETS = [
    ("IBEX 35", "^IBEX"), ("FTSE 100", "^FTSE"), ("Euro Stoxx 50", "^STOXX50E"),
    ("DAX", "^GDAXI"), ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"),
    ("Nikkei 225", "^N225"), ("Hang Seng", "^HSI"),
    ("EUR/USD", "EURUSD=X"), ("EUR/GBP", "EURGBP=X"),
    ("Brent", "BZ=F"), ("Oro", "GC=F"), ("Bitcoin", "BTC-USD"),
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
IMG_SRC_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def clean(text, limit=None):
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    text = WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def fetch(url, accept="application/rss+xml, application/atom+xml, application/xml, text/xml, */*", limit=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": accept})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read(limit + 1) if limit else resp.read()
    if limit and len(body) > limit:
        raise ValueError("too large")
    # Some servers (e.g. The Independent) gzip the body whether asked or not.
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body


def entry_time(entry):
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return calendar.timegm(value)
            except (TypeError, ValueError, OverflowError):
                pass
    return None


def strip_google_suffix(title, url):
    # Google News fallback feeds append " - Publisher" (e.g. " - AFP.com") to every title.
    if "news.google.com" in url and " - " in title:
        return title.rsplit(" - ", 1)[0]
    return title


def bigger(url):
    """Ask for a larger version of feed thumbnails whose URL encodes the size."""
    url = re.sub(r"(ichef\.bbci\.co\.uk/(?:ace/)?(?:standard|ws)/)\d+/", r"\g<1>976/", url)
    if "i.guim.co.uk" in url:
        url = re.sub(r"([?&]width=)\d+", r"\g<1>1000", url)
    return url


def entry_image(entry):
    """Best photo URL for a feed entry, or None."""
    url = _entry_image(entry)
    return bigger(url) if url else None


def _entry_image(entry):
    candidates = []
    for m in entry.get("media_content") or []:
        url = m.get("url")
        if url and (m.get("medium") == "image" or (m.get("type") or "").startswith("image") or re.search(r"\.(jpe?g|png|webp)", url, re.I)):
            candidates.append((int(m.get("width") or 0), url))
    for m in entry.get("media_thumbnail") or []:
        if m.get("url"):
            candidates.append((int(m.get("width") or 0), m["url"]))
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image") and link.get("href"):
            candidates.append((0, link["href"]))
    if candidates:
        return max(candidates, key=lambda c: c[0])[1]
    for field in ("summary", "description"):
        m = IMG_SRC_RE.search(entry.get(field) or "")
        if m:
            return m.group(1)
    for c in entry.get("content") or []:
        m = IMG_SRC_RE.search(c.get("value") or "")
        if m:
            return m.group(1)
    return None


def img_key(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def save_photo(url, img_dir):
    """Download, shrink and save one photo. Returns its key, or None."""
    if Image is None:
        return None
    key = img_key(url)
    path = os.path.join(img_dir, key + ".jpg")
    if os.path.exists(path):
        return key
    try:
        raw = fetch(url, accept="image/avif,image/webp,image/jpeg,image/png,*/*", limit=IMG_MAX_BYTES)
        im = Image.open(io.BytesIO(raw))
        im.draft("RGB", (IMG_WIDTH * 2, IMG_WIDTH * 2))
        im = im.convert("RGB")
        if im.width < 240 or im.height < 120:   # icons, logos, tracking pixels
            return None
        if im.height > im.width * 0.75:          # crop tall photos to 4:3 around the upper third
            h = int(im.width * 0.75)
            top = max(0, int((im.height - h) * 0.3))
            im = im.crop((0, top, im.width, top + h))
        im.thumbnail((IMG_WIDTH, IMG_WIDTH))
        im.save(path, "JPEG", quality=IMG_QUALITY, optimize=True, progressive=True)
        small = im.copy()
        small.thumbnail((200, 200))   # cover thumbnail for the archive grid
        small.save(os.path.join(img_dir, key + "_s.jpg"), "JPEG", quality=55, optimize=True)
        return key
    except Exception:
        return None


def collect_source(src, now):
    notes = (src.get("fetchNotes") or "").lower()
    max_age = SLOW_AGE_HOURS if ("slow" in notes or "48" in notes or "72" in notes) else MAX_AGE_HOURS
    max_age = src.get("maxAgeHours", max_age)
    cutoff = now - max_age * 3600
    items, seen, errors = [], set(), []
    for feed_key, url in (src.get("feeds") or {}).items():
        if not url:
            continue
        try:
            parsed = feedparser.parse(fetch(url))
        except Exception as exc:  # network, HTTP, TLS
            errors.append(f"{feed_key}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        undated = 0
        for entry in parsed.entries:
            link = entry.get("link") or ""
            title = clean(entry.get("title"))
            if not title or not link or link in seen or title.isdigit():
                continue
            ts = entry_time(entry)
            if ts is None:
                undated += 1
                if undated > UNDATED_KEEP:
                    continue
            elif ts < cutoff or ts > now + 3600:
                continue
            seen.add(link)
            item = {
                "t": strip_google_suffix(title, url),
                "l": link,
                "s": clean(entry.get("summary") or entry.get("description"), SUMMARY_CHARS),
                "d": dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if ts else None,
                "f": feed_key,
            }
            image = entry_image(entry)
            if image and image.startswith(("https://", "http://")):
                item["i"] = html.unescape(image)
            items.append(item)
    items.sort(key=lambda i: i["d"] or "", reverse=True)
    return src["id"], {
        "name": src.get("name"),
        "ok": bool(items) or not errors,
        "errors": errors,
        "items": items[:MAX_ITEMS_PER_SOURCE],
    }


def collect_channel(ch, now):
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + ch["channelId"]
    try:
        parsed = feedparser.parse(fetch(url))
    except Exception as exc:
        return ch["id"], {"name": ch["name"], "errors": [f"{type(exc).__name__}: {str(exc)[:100]}"], "videos": []}
    videos = []
    for e in parsed.entries:
        link = e.get("link") or ""
        vid = e.get("yt_videoid")
        ts = entry_time(e)
        if not vid or "/shorts/" in link or ts is None or ts < now - VIDEO_AGE_HOURS * 3600:
            continue
        videos.append({
            "t": clean(e.get("title")),
            "l": f"https://www.youtube.com/watch?v={vid}",
            "d": dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "i": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
            "s": clean((e.get("media_description") or e.get("summary") or ""), 160),
        })
        if len(videos) >= VIDEOS_PER_CHANNEL:
            break
    return ch["id"], {"name": ch["name"], "lang": ch.get("lang"), "country": ch.get("country"), "errors": [], "videos": videos}


def collect_market(name, symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.request.quote(symbol) + "?range=1mo&interval=1d")
    try:
        data = json.loads(fetch(url, accept="application/json"))
        result = data["chart"]["result"][0]
        stamps = result.get("timestamp") or []
        raw = result["indicators"]["quote"][0]["close"]
        hist = [(t, c) for t, c in zip(stamps, raw) if c is not None]
        closes = [c for _, c in hist]
        last = result["meta"].get("regularMarketPrice") or closes[-1]
        prev = closes[-2] if len(closes) >= 2 else result["meta"].get("chartPreviousClose")
        change = (last - prev) / prev * 100 if prev else None
        month = (last - closes[0]) / closes[0] * 100 if closes else None
        return {"name": name, "symbol": symbol, "value": round(last, 4),
                "changePct": round(change, 2) if change is not None else None,
                "monthPct": round(month, 2) if month is not None else None,
                "hist": [round(c, 4) for c in closes],
                "histDates": [dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d") for t, _ in hist],
                "asOf": dt.datetime.fromtimestamp(result["meta"].get("regularMarketTime", 0), dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    except Exception as exc:
        return {"name": name, "symbol": symbol, "error": f"{type(exc).__name__}: {str(exc)[:100]}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default=os.path.join(ROOT, "sources.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "out", "latest.json"))
    parser.add_argument("--only", help="comma-separated source ids (for testing)")
    parser.add_argument("--no-photos", action="store_true")
    args = parser.parse_args()

    with open(args.sources, encoding="utf-8") as fh:
        meta = json.load(fh)
    sources = meta["sources"]
    channels = meta.get("videoChannels", [])
    if args.only:
        wanted = set(args.only.split(","))
        sources = [s for s in sources if s["id"] in wanted]
        channels = [c for c in channels if c["id"] in wanted]

    out_dir = os.path.dirname(os.path.abspath(args.out))
    img_dir = os.path.join(out_dir, "img")
    os.makedirs(img_dir, exist_ok=True)

    now = time.time()
    started = time.monotonic()
    results, videos = {}, {}
    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        for sid, res in pool.map(lambda s: collect_source(s, now), sources):
            results[sid] = res
        for cid, res in pool.map(lambda c: collect_channel(c, now), channels):
            videos[cid] = res
        markets = list(pool.map(lambda m: collect_market(*m), MARKETS))

        if not args.no_photos:
            jobs = []
            for res in results.values():
                for item in [i for i in res["items"] if i.get("i")][:PHOTOS_PER_SOURCE]:
                    jobs.append(item)
            for res in videos.values():
                jobs.extend(res["videos"])
            for item, key in zip(jobs, pool.map(lambda it: save_photo(it["i"], img_dir), jobs)):
                if key:
                    item["k"] = key

    out = {
        "collectedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round(time.monotonic() - started, 1),
        "sourceCount": len(results),
        "itemCount": sum(len(r["items"]) for r in results.values()),
        "photoCount": sum(1 for r in results.values() for i in r["items"] if i.get("k")),
        "videoCount": sum(len(r["videos"]) for r in videos.values()),
        "failed": sorted(sid for sid, r in results.items() if not r["items"]),
        "markets": markets,
        "sources": results,
        "videos": videos,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    img_bytes = sum(os.path.getsize(os.path.join(img_dir, f)) for f in os.listdir(img_dir))
    print(f"{out['itemCount']} items from {len(results)} sources, {out['photoCount']} photos "
          f"({img_bytes // 1024} KB), {out['videoCount']} videos, in {out['seconds']}s; "
          f"empty: {', '.join(out['failed']) or 'none'}; "
          f"markets ok: {sum(1 for m in markets if 'error' not in m)}/{len(markets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
