#!/usr/bin/env python3
"""Collect the latest headlines from every feed in sources.json, plus market prices.

Runs in GitHub Actions (full internet access) every morning and writes one
compact JSON file that the Claude cloud routine reads to write the briefing.

Usage: python collector/collect.py --out out/latest.json
"""
import argparse
import calendar
import concurrent.futures as cf
import datetime as dt
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import feedparser

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

MARKETS = [
    ("IBEX 35", "^IBEX"), ("FTSE 100", "^FTSE"), ("Euro Stoxx 50", "^STOXX50E"),
    ("DAX", "^GDAXI"), ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"),
    ("Nikkei 225", "^N225"), ("Hang Seng", "^HSI"),
    ("EUR/USD", "EURUSD=X"), ("EUR/GBP", "EURGBP=X"),
    ("Brent", "BZ=F"), ("Oro", "GC=F"), ("Bitcoin", "BTC-USD"),
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text, limit=None):
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    text = WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip",
                                               "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read()
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
            items.append({
                "t": strip_google_suffix(title, url),
                "l": link,
                "s": clean(entry.get("summary") or entry.get("description"), SUMMARY_CHARS),
                "d": dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if ts else None,
                "f": feed_key,
            })
    items.sort(key=lambda i: i["d"] or "", reverse=True)
    return src["id"], {
        "name": src.get("name"),
        "ok": bool(items) or not errors,
        "errors": errors,
        "items": items[:MAX_ITEMS_PER_SOURCE],
    }


def collect_market(name, symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.request.quote(symbol) + "?range=5d&interval=1d")
    try:
        data = json.loads(fetch(url))
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        last = result["meta"].get("regularMarketPrice") or closes[-1]
        prev = closes[-2] if len(closes) >= 2 else result["meta"].get("chartPreviousClose")
        change = (last - prev) / prev * 100 if prev else None
        return {"name": name, "symbol": symbol, "value": round(last, 4),
                "changePct": round(change, 2) if change is not None else None,
                "asOf": dt.datetime.fromtimestamp(result["meta"].get("regularMarketTime", 0), dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    except Exception as exc:
        return {"name": name, "symbol": symbol, "error": f"{type(exc).__name__}: {str(exc)[:100]}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default=os.path.join(ROOT, "sources.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "out", "latest.json"))
    parser.add_argument("--only", help="comma-separated source ids (for testing)")
    args = parser.parse_args()

    with open(args.sources, encoding="utf-8") as fh:
        sources = json.load(fh)["sources"]
    if args.only:
        wanted = set(args.only.split(","))
        sources = [s for s in sources if s["id"] in wanted]

    now = time.time()
    started = time.monotonic()
    results = {}
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        for sid, res in pool.map(lambda s: collect_source(s, now), sources):
            results[sid] = res
        markets = list(pool.map(lambda m: collect_market(*m), MARKETS))

    out = {
        "collectedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round(time.monotonic() - started, 1),
        "sourceCount": len(results),
        "itemCount": sum(len(r["items"]) for r in results.values()),
        "failed": sorted(sid for sid, r in results.items() if not r["items"]),
        "markets": markets,
        "sources": results,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{out['itemCount']} items from {len(results)} sources in {out['seconds']}s; "
          f"empty: {', '.join(out['failed']) or 'none'}; "
          f"markets ok: {sum(1 for m in markets if 'error' not in m)}/{len(markets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
