#!/usr/bin/env python3
"""Print a compact, token-light digest of the collected headlines for the chosen sources.

Usage:
  python briefing/digest.py --latest /tmp/data/latest.json --ids elpais,elmundo,bbc
  python briefing/digest.py --latest /tmp/data/latest.json --defaults
Output is plain text grouped by region, one line per headline:
  - HH:MM | headline [foto] — summary | link
`[foto]` means the article has a photo the briefing can use (`imageFrom`).
A final VÍDEOS section lists the news videos of the last 36 hours.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", required=True)
    ap.add_argument("--sources", default=os.path.join(ROOT, "sources.json"))
    ap.add_argument("--ids", help="comma-separated source ids")
    ap.add_argument("--defaults", action="store_true", help="use the defaultOn sources")
    ap.add_argument("--max-per-source", type=int, default=12)
    ap.add_argument("--no-summary", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    meta = json.load(open(args.sources, encoding="utf-8"))
    latest = json.load(open(args.latest, encoding="utf-8"))
    regions = {r["id"]: r["name"] for r in meta["regions"]}
    by_id = {s["id"]: s for s in meta["sources"]}

    if args.ids:
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    elif args.defaults:
        ids = [s["id"] for s in meta["sources"] if s.get("defaultOn")]
    else:
        sys.exit("give --ids or --defaults")

    unknown = [i for i in ids if i not in by_id]
    ids = [i for i in ids if i in by_id]
    print(f"# Titulares recogidos {latest['collectedAt']} — {len(ids)} fuentes seleccionadas")
    if unknown:
        print(f"# IDs desconocidos ignorados: {', '.join(unknown)}")

    print("\n## MERCADOS (último valor, variación diaria, variación en un mes)")
    for m in latest.get("markets", []):
        if "error" in m:
            print(f"- {m['name']}: sin dato")
        else:
            print(f"- {m['name']}: {m['value']} (día {m.get('changePct')} %, mes {m.get('monthPct')} %) a {m.get('asOf')}")

    empty = []
    for region_id, region_name in regions.items():
        group = [i for i in ids if by_id[i]["region"] == region_id]
        if not group:
            continue
        print(f"\n## {region_name.upper()}")
        for sid in group:
            s = by_id[sid]
            res = latest["sources"].get(sid) or {"items": []}
            items = res["items"][: args.max_per_source]
            if not items:
                empty.append(s["name"])
                continue
            print(f"\n### [{sid}] {s['name']} — {s['country']}, {s['lang']}, {s['leaning']}, lado: {s['side']}, {s['paywall']}")
            for it in items:
                when = (it.get("d") or "")[11:16] or "--:--"
                line = f"- {when} | {it['t']}" + (" [foto]" if it.get("k") else "")
                if it.get("s") and not args.no_summary and it["s"] != it["t"]:
                    line += f" — {it['s']}"
                print(line + f" | {it['l']}")

    videos = latest.get("videos") or {}
    if videos:
        print("\n## VÍDEOS (últimas 36 h; usa el enlace exacto en `videos`)")
        for ch in meta.get("videoChannels", []):
            res = videos.get(ch["id"])
            if not res or not res.get("videos"):
                continue
            for v in res["videos"]:
                print(f"- {(v.get('d') or '')[11:16]} | [{ch['name']}, {ch['lang']}] {v['t']} | {v['l']}")

    if empty:
        print(f"\n# Sin titulares hoy (feed caído o sin novedades): {', '.join(empty)}")


if __name__ == "__main__":
    main()
