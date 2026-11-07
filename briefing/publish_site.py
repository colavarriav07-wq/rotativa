#!/usr/bin/env python3
"""Add one edition to the public website (docs/editions/), from render.py's archive.json.

Usage: python briefing/publish_site.py --archive /tmp/out/archive.json
Then commit and push docs/editions (see INSTRUCTIONS.md, step 7).

The public site loads photos straight from the newspapers (imgUrl), so the embedded
photo copies used by the private Claude page are left out.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITIONS = os.path.join(ROOT, "docs", "editions")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True)
    args = ap.parse_args()

    arc = json.load(open(args.archive, encoding="utf-8"))
    arc.pop("cover", None)          # data: URI thumbnail, only for the private page
    arc.pop("mediaDocs", None)
    stories = (arc.get("briefing") or {}).get("stories") or []
    cover_url = next((s.get("imgUrl") for s in stories if s.get("imgUrl")), None)
    arc["coverUrl"] = cover_url

    os.makedirs(EDITIONS, exist_ok=True)
    with open(os.path.join(EDITIONS, arc["id"] + ".json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(arc, fh, ensure_ascii=False, separators=(",", ":"))

    index_path = os.path.join(EDITIONS, "index.json")
    try:
        index = json.load(open(index_path, encoding="utf-8"))
    except (OSError, ValueError):
        index = {"editions": []}
    entries = [e for e in index.get("editions", []) if e.get("id") != arc["id"]]
    entries.append({"id": arc["id"], "date": arc["date"], "edition": arc["edition"], "headline": arc["headline"],
                    "coverUrl": cover_url, "createdAt": arc.get("createdAt")})
    entries.sort(key=lambda e: (e["date"], e["edition"] == "semanal"), reverse=True)
    with open(index_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"editions": entries}, fh, ensure_ascii=False, indent=1)
    print(f"OK: docs/editions/{arc['id']}.json written; index has {len(entries)} editions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
