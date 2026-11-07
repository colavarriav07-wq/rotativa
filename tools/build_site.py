#!/usr/bin/env python3
"""Build the public website (GitHub Pages, served from docs/) from page/index.html.

The same page runs inside Claude (private) and on GitHub Pages (public). The Claude
viewer wraps the page in its own <head>; for GitHub Pages this script adds one.
Run it after changing page/index.html, then commit docs/.

Usage: python tools/build_site.py
"""
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

HEAD = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="referrer" content="no-referrer">
<meta name="description" content="Rotativa: la prensa mundial del día en historias.">
<meta name="theme-color" content="#07090a">
<style>:root{color-scheme:dark}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head>
<body>
"""


def main():
    os.makedirs(os.path.join(DOCS, "editions"), exist_ok=True)
    with open(os.path.join(ROOT, "page", "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HEAD + page + "\n</body>\n</html>\n")
    shutil.copyfile(os.path.join(ROOT, "page", "countries-110m.json"), os.path.join(DOCS, "countries-110m.json"))
    shutil.copyfile(os.path.join(ROOT, "sources.json"), os.path.join(DOCS, "sources.json"))
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    index = os.path.join(DOCS, "editions", "index.json")
    if not os.path.exists(index):
        with open(index, "w", encoding="utf-8") as fh:
            json.dump({"editions": []}, fh)
    print("docs/ built")


if __name__ == "__main__":
    main()
