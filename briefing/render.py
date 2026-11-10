#!/usr/bin/env python3
"""Turn briefing.json (written by Claude) into the Rotativa email and the web edition records.

Usage:
  python briefing/render.py --briefing /tmp/briefing.json --data /tmp/data --outdir /tmp/out

--data is the extracted `data` branch: latest.json plus img/<key>.jpg photos.
Writes to --outdir:
  email.html, email.txt, subject.txt   the email
  archive.json                         the web edition record   -> briefings/<ID>
  media-<n>.json                       embedded photos (chunks) -> media/<ID>-<n>
  writes.txt                           the ArtifactData calls to make, one per line

briefing.json schema (all text in Spanish):
{
  "date": "2026-11-07", "edition": "diaria" | "semanal",
  "headline": "max 100 chars, also the email subject",
  "essentials": ["3-5 key points"],
  "stories": [                       // 12 daily / 10 weekly, most important first
    {"topic": "Mundo" | "Economía" | "Tecnología" | "España y Reino Unido",
     "title": "...", "short": "one sentence for the email (max 170 chars)",
     "summary": "3-5 sentences for the web story",
     "sources": [{"name": "El País", "url": "https://..."}],
     "imageFrom": "link of a digest item marked [foto] about this story",
     "countries": ["US", "IR"],      // ISO 3166-1 alpha-2 of the places involved
     "coverage": 9,                  // how many outlets in the digest covered it
     "original": "optional: link of an ENGLISH-language digest article; its headline and
                  standfirst are shown word for word under the Spanish text (see INSTRUCTIONS.md)"}
  ],
  "figure": {"value": "7,6 %", "label": "...", "context": "...", "source": {"name": "...", "url": "..."}},
  "explainer": {"title": "Para entender ...", "body": "4-6 sentences", "sources": [{"name": "...", "url": "..."}]},
  "twoViews": [{"title": "...", "context": "...",
                "progressive": {"summary": "...", "sources": [...]},
                "conservative": {"summary": "...", "sources": [...]}}],
  "worldView": [{"title": "...", "views": [{"country": "China (medio estatal)", "iso": "CN",
                                            "source": "CGTN", "url": "...", "framing": "..."}]}],
  "marketNote": "1-2 sentences",
  "calendar": [{"time": "10:00", "place": "BCE", "event": "...", "url": "optional"}],
  "videos": [{"url": "exact video link from the digest VÍDEOS list", "note": "why watch it"}],
  "quiz": [{"q": "...", "options": ["a", "b", "c"], "answer": 0, "explain": "..."}],
  "trends": ["weekly only"],
  "sourcesUsed": ["elpais", "bbc"]
}
"""
import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE_URL_FILE = os.path.join(ROOT, "briefing", "page_url.txt")   # private Claude page (newspaper picker)
SITE_URL_FILE = os.path.join(ROOT, "briefing", "site_url.txt")   # public website (where the email links)


def read_url(path):
    return open(path, encoding="utf-8").read().strip() if os.path.exists(path) else ""
TOPICS = {"Mundo": "#e9b44c", "Economía": "#4fc08d", "Tecnología": "#a98bf5", "España y Reino Unido": "#f2899b"}
DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
MEDIA_CHUNK_CHARS = 220_000   # db documents are capped at 256 KiB

CSS = """
body{margin:0;padding:0;background:#ecebe7}
.w{max-width:600px;margin:0 auto;background:#ffffff}
.f{font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif}
.g{font-family:Georgia,'Times New Roman',serif}
.top{background:#101315;padding:18px 22px}
.mast{font-size:24px;letter-spacing:5px;font-weight:700;color:#ffffff;margin:0}
.mast b{color:#e9b44c}
.meta{font-size:12px;color:#b9c0c5;margin:6px 0 0}
.pad{padding:18px 22px 4px}
.chip{display:inline-block;font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;padding:5px 8px;border-radius:3px;color:#101315}
.h1{font-size:26px;line-height:1.2;font-weight:700;color:#101315;margin:10px 0 8px}
.p{font-size:15px;line-height:1.55;color:#2a3035;margin:0}
.b{display:inline-block;font-size:12px;font-weight:600;color:#0e5a4d;border:1px solid #0e5a4d;border-radius:14px;padding:6px 10px;margin:8px 6px 0 0;text-decoration:none}
.ess{background:#f4f2ec;border-left:4px solid #e9b44c;padding:12px 16px;margin:14px 22px 0}
.ess p{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;color:#7a6a3a;margin:0 0 6px}
.ess li{font-size:14px;line-height:1.5;color:#101315;margin:0 0 5px}
.cta{display:block;background:#0e5a4d;color:#ffffff;text-align:center;font-size:15px;font-weight:700;line-height:1.35;padding:15px 18px;border-radius:8px;text-decoration:none;margin:20px 22px 4px}
.sec{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#101315;border-bottom:2px solid #101315;padding-bottom:6px;margin:26px 22px 6px}
.row{width:100%;border-collapse:collapse}
.row td{vertical-align:top;padding:10px 0;border-bottom:1px solid #ebe9e4}
.t{font-size:17px;line-height:1.25;font-weight:700;color:#101315;margin:4px 0 4px}
.s{font-size:14px;line-height:1.45;color:#2a3035;margin:0}
.lab{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase}
.fig{font-size:44px;line-height:1;font-weight:700;color:#0e5a4d;margin:4px 0 6px}
.k{width:100%;border-collapse:collapse}
.k td{padding:6px 4px;border-bottom:1px solid #ebe9e4;font-size:13px;color:#101315;white-space:nowrap}
.up{color:#1e7a46}.dn{color:#b3261e}
.v{padding:10px 14px;margin:8px 22px 0;background:#f6f6f4;border-left:4px solid #7a828a}
.v.pr{border-color:#c0443e}.v.co{border-color:#2e5e9e}
.ag td{padding:5px 12px 5px 0;font-size:14px;line-height:1.4;color:#101315;vertical-align:top}
.o{font-size:13px;line-height:1.45;color:#4a5258;background:#f4f2ec;border-left:3px solid #c9c6be;padding:7px 10px;margin:8px 0 0}
.o i{color:#101315}
.ft{font-size:12px;line-height:1.6;color:#6a7278;padding:18px 22px 26px;border-top:1px solid #ebe9e4;margin-top:24px}
.ft a{color:#0e5a4d}
"""


def esc(text):
    return html.escape(str(text or ""), quote=True)


def safe_url(url):
    url = str(url or "")
    return url if url.startswith(("https://", "http://")) else ""


def long_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{DAYS[d.weekday()]} {d.day} de {MONTHS[d.month - 1]} de {d.year}"


def fmt_value(v):
    s = f"{v:,.4f}" if v < 10 else f"{v:,.0f}" if v > 1000 else f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v):
    return "—" if v is None else f"{v:+.2f} %".replace(".", ",")


# ---------------------------------------------------------------- validation

SKIP_KEYS = {"original", "url", "imageFrom", "sources", "countries", "sourcesUsed", "iso", "date", "edition", "topic"}
SCALE_WORDS = {   # per source language: (thousand-million words, million-million words)
    "en": (r"\bbillions?\b|\d\s?bn\b", r"\btrillions?\b|\d\s?(?:tn|trn)\b"),
    "de": (r"\bmilliarden?\b|\d\s?mrd\b", r"\bbillionen\b|\bbillion\b"),
    "fr": (r"\bmilliards?\b|\d\s?mds?\b", r"\bbillions?\b"),
    "es": (r"\bmil millones\b", r"\bbill[oó]n(?:es)?\b"),
}


def spanish_texts(node, path="briefing"):
    """Every Spanish text in briefing.json, with where it is (links and English originals left out)."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from spanish_texts(v, f"{path}[{i}]")
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in SKIP_KEYS:
                yield from spanish_texts(v, f"{path}.{k}")


def check_numbers(b, items, langs):
    """Billion / trillion: an English billion is 'mil millones'; only an English trillion is a 'billón'."""
    problems, warnings = [], []
    for where, text in spanish_texts(b):
        for m in re.finditer(r"\btrill[oó]n(?:es)?\b|\bmillardos?\b", text, re.I):
            problems.append(f"{where}: '{m.group(0)}' is wrong here. English billion = 'mil millones'; "
                            f"English trillion = 'billón'. Never 'trillón' or 'millardo'")
        for m in re.finditer(r"\b(?:billions?|trillions?)\b|\d\s?(?:bn|tn|trn)\b", text, re.I):
            ctx = text[max(0, m.start() - 40):m.end() + 20]
            warnings.append(f"{where}: English number word '{m.group(0)}' in the Spanish text (…{ctx}…). "
                            f"Translate it, unless it is the original figure kept in brackets")
        for m in re.finditer(r"\bbill[oó]n(?:es)?\b", text, re.I):
            ctx = text[max(0, m.start() - 50):m.end() + 25]
            warnings.append(f"{where}: check '…{ctx}…' translates an English TRILLION (10^12). "
                            f"If the source says billion, write 'mil millones'")
    for n, st in enumerate(b.get("stories", []), 1):
        mine = " ".join(t for _, t in spanish_texts(st)).lower()
        has_billon = re.search(r"\bbill[oó]n(?:es)?\b", mine)
        has_milmill = re.search(r"\bmil millones\b", mine)
        if not (has_billon or has_milmill):
            continue
        small = big = False
        for link in [st.get("imageFrom")] + [x.get("url") for x in st.get("sources", [])]:
            it = items.get(link or "")
            words = SCALE_WORDS.get(langs.get(it.get("source")) if it else None)
            if not words:
                continue
            text = f"{it.get('t', '')} {it.get('s', '')}".lower()
            small = small or bool(re.search(words[0], text))
            big = big or bool(re.search(words[1], text))
        where = f"story {n} ('{(st.get('title') or '')[:40]}')"
        if has_billon and small and not big:
            problems.append(f"{where} says 'billón/billones', but its sources speak of billions "
                            f"(= miles de millones). Write 'mil millones', e.g. $5bn = 5.000 millones de dólares")
        if has_milmill and big and not small:
            problems.append(f"{where} says 'mil millones', but its sources speak of trillions (= billones). "
                            f"Write 'billón/billones', e.g. $1.2tn = 1,2 billones de dólares")
    return problems, warnings


def validate(b, video_index, items=None, langs=None):
    problems, warnings = [], []
    items, langs = items or {}, langs or {}
    for key in ("date", "edition", "headline", "stories"):
        if not b.get(key):
            problems.append(f"missing '{key}'")
    try:
        dt.date.fromisoformat(b.get("date", ""))
    except (ValueError, TypeError):
        problems.append("date must be YYYY-MM-DD")
    if b.get("edition") not in ("diaria", "semanal"):
        problems.append("edition must be 'diaria' or 'semanal'")
    if len(b.get("headline", "")) > 110:
        problems.append("headline is longer than 110 characters: shorten it")
    for n, st in enumerate(b.get("stories", []), 1):
        where = f"story {n} ('{(st.get('title') or '')[:40]}')"
        for key in ("title", "short", "summary"):
            if not st.get(key):
                problems.append(f"{where} has no '{key}'")
        if st.get("topic") not in TOPICS:
            problems.append(f"{where}: topic must be one of {', '.join(TOPICS)}")
        if not st.get("sources"):
            problems.append(f"{where} has no sources")
        for src in st.get("sources", []):
            if not safe_url(src.get("url")):
                problems.append(f"{where}: source '{src.get('name')}' has no http(s) url")
        if st.get("original"):
            it = items.get(st["original"]) if isinstance(st["original"], str) else None
            if not it:
                problems.append(f"{where}: 'original' must be the exact link of a digest article")
            elif langs.get(it.get("source")) != "en":
                problems.append(f"{where}: 'original' must be an English-language article "
                                f"({it.get('source')} is not in English)")
    for tv in b.get("twoViews", []):
        for side in ("progressive", "conservative"):
            if not (tv.get(side) or {}).get("summary"):
                problems.append(f"twoViews '{tv.get('title')}' missing {side} summary")
    for q in b.get("quiz", []):
        opts = q.get("options") or []
        if not q.get("q") or len(opts) < 2 or not isinstance(q.get("answer"), int) or not 0 <= q["answer"] < len(opts):
            problems.append(f"quiz question '{(q.get('q') or '')[:40]}' needs q, 2-4 options and a valid answer index")
    for v in b.get("videos", []):
        if v.get("url") not in video_index:
            warnings.append(f"video not in the digest, dropped: {v.get('url')}")
    n = len(b.get("stories", []))
    if not 8 <= n <= 15:
        warnings.append(f"{n} stories (expected 12 daily / 10 weekly)")
    p2, w2 = check_numbers(b, items, langs)
    return problems + p2, warnings + w2


# ---------------------------------------------------------------- resolving data

def build_indexes(latest, meta):
    items, videos = {}, {}
    for sid, res in (latest.get("sources") or {}).items():
        for it in res.get("items", []):
            items.setdefault(it["l"], dict(it, source=sid))
    channels = {c["id"]: c for c in meta.get("videoChannels", [])}
    for cid, res in (latest.get("videos") or {}).items():
        ch = channels.get(cid, {})
        for v in res.get("videos", []):
            videos[v["l"]] = dict(v, channel=ch.get("name", res.get("name")), lang=ch.get("lang"))
    return items, videos


def resolve_story_image(st, items):
    for link in [st.get("imageFrom")] + [s.get("url") for s in st.get("sources", [])]:
        it = items.get(link or "")
        if it and it.get("k"):
            return it["k"], it.get("i")
    for link in [st.get("imageFrom")] + [s.get("url") for s in st.get("sources", [])]:
        it = items.get(link or "")
        if it and it.get("i"):
            return None, it["i"]
    return None, None


def data_uri(path):
    with open(path, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode("ascii")


# ---------------------------------------------------------------- email

def buttons(sources, limit=4):
    out = []
    for s in (sources or [])[:limit]:
        url = safe_url(s.get("url"))
        if url:
            out.append(f'<a class="b f" href="{esc(url)}">{esc(s.get("name"))} &#8599;</a>')
    return "".join(out)


def original_box(st):
    o = st.get("original")
    if not o or not o.get("title"):
        return ""
    text = f' {esc(o["text"])}' if o.get("text") else ""
    return (f'<p class="o f" lang="en"><b>Tal cual, en inglés ({esc(o.get("source"))}):</b> '
            f'<i>{esc(o["title"])}</i>{text}</p>')


def chip(topic):
    return f'<span class="chip f" style="background:{TOPICS.get(topic, "#d9d9d9")}">{esc(topic)}</span>'


def markets_rows(markets):
    rows = []
    for m in markets:
        ch = m.get("changePct") or 0
        width = min(44, int(abs(ch) / 3 * 44)) or 2
        color = "#1e7a46" if ch > 0 else "#b3261e" if ch < 0 else "#9aa1a6"
        neg = f'<div style="width:{width}px;height:8px;background:{color};margin-left:auto"></div>' if ch < 0 else ""
        pos = f'<div style="width:{width}px;height:8px;background:{color}"></div>' if ch >= 0 else ""
        cls = "up" if ch > 0 else "dn" if ch < 0 else ""
        rows.append(
            f'<tr><td class="f">{esc(m["name"])}</td><td class="f" align="right">{fmt_value(m["value"])}</td>'
            f'<td class="f {cls}" align="right">{pct(m.get("changePct"))}</td>'
            f'<td width="96"><table role="presentation" cellpadding="0" cellspacing="0" width="96"><tr>'
            f'<td width="47" align="right" style="border:0;padding:0">{neg}</td>'
            f'<td width="2" style="border:0;padding:0;background:#c9c6be"></td>'
            f'<td width="47" style="border:0;padding:0">{pos}</td></tr></table></td></tr>')
    return "".join(rows)


def render_email(arc, page_url):
    b = arc["briefing"]
    stories = b["stories"]
    weekly = b["edition"] == "semanal"
    site = read_url(SITE_URL_FILE) or page_url
    web = f"{site}#d-{arc['id']}" if site else ""
    o = []
    a = o.append
    a(f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      f'<title>{esc(b["headline"])}</title><style>{CSS.strip()}</style></head><body>')
    a(f'<div style="display:none;max-height:0;overflow:hidden">{esc(" · ".join(b.get("essentials", [])[:2]))}</div>')
    a('<div class="w">')
    label = "La semana en 10 historias" if weekly else "Informe diario"
    a(f'<div class="top"><p class="mast g">ROTA<b>TIVA</b></p><p class="meta f">{label} · '
      f'{esc(long_date(b["date"]).capitalize())} · {len(stories)} historias · {len(b.get("sourcesUsed", []))} fuentes</p></div>')

    lead = stories[0]
    if lead.get("imgUrl"):
        a(f'<a href="{esc(web or safe_url(lead["sources"][0]["url"]))}"><img src="{esc(lead["imgUrl"])}" alt="" width="600" '
          f'style="display:block;width:100%;max-width:600px;height:auto;border:0"></a>')
    a(f'<div class="pad">{chip(lead["topic"])}<p class="h1 g">{esc(lead["title"])}</p>'
      f'<p class="p f">{esc(lead.get("short") or lead["summary"])}</p>{original_box(lead)}{buttons(lead.get("sources"))}</div>')

    if b.get("essentials"):
        a('<div class="ess"><p class="f">Lo esencial</p><ul style="margin:0;padding-left:18px">'
          + "".join(f'<li class="f">{esc(e)}</li>' for e in b["essentials"]) + "</ul></div>")
    if web:
        a(f'<a class="cta f" href="{esc(web)}">Abrir la edición completa: {len(stories)} historias con fotos, mapa, vídeos y test &#8594;</a>')

    a('<p class="sec f">Más noticias</p><div style="padding:0 22px">'
      '<table class="row" role="presentation" cellpadding="0" cellspacing="0">')
    for st in stories[1:7]:
        img = ""
        if st.get("imgUrl"):
            img = (f'<td width="112" style="padding-right:12px"><img src="{esc(st["imgUrl"])}" alt="" width="104" height="78" '
                   f'style="display:block;width:104px;height:78px;object-fit:cover;border-radius:4px;border:0"></td>')
        a(f'<tr>{img}<td><span class="lab f" style="color:#7d858b">{esc(st["topic"])}</span>'
          f'<p class="t g">{esc(st["title"])}</p><p class="s f">{esc(st.get("short") or st["summary"])}</p>'
          f'{original_box(st)}{buttons(st.get("sources"), 3)}</td></tr>')
    a("</table></div>")

    fig = b.get("figure")
    if fig:
        src = fig.get("source") or {}
        a(f'<p class="sec f">La cifra del día</p><div style="padding:0 22px"><p class="fig g">{esc(fig.get("value"))}</p>'
          f'<p class="p f"><b>{esc(fig.get("label"))}</b> {esc(fig.get("context"))}</p>{buttons([src] if src else [])}</div>')

    mk = arc.get("markets") or []
    if mk:
        a('<p class="sec f">Mercados</p>')
        if b.get("marketNote"):
            a(f'<p class="s f" style="padding:0 22px 6px">{esc(b["marketNote"])}</p>')
        a(f'<div style="padding:0 22px"><table class="k" role="presentation" cellpadding="0" cellspacing="0">{markets_rows(mk)}</table></div>')

    if b.get("twoViews"):
        tv = b["twoViews"][0]
        a(f'<p class="sec f">Dos miradas</p><p class="t g" style="padding:0 22px">{esc(tv["title"])}</p>')
        if tv.get("context"):
            a(f'<p class="s f" style="padding:0 22px;color:#6a7278">{esc(tv["context"])}</p>')
        for key, cls, label, color in (("progressive", "pr", "Visión progresista", "#c0443e"), ("conservative", "co", "Visión conservadora", "#2e5e9e")):
            v = tv.get(key) or {}
            a(f'<div class="v {cls}"><p class="lab f" style="color:{color};margin:0 0 4px">{label}</p>'
              f'<p class="s f">{esc(v.get("summary"))}</p>{buttons(v.get("sources"), 3)}</div>')
        if web and len(b["twoViews"]) > 1:
            a(f'<p class="s f" style="padding:8px 22px 0"><a href="{esc(web)}" style="color:#0e5a4d;font-weight:700">'
              f'Ver las {len(b["twoViews"])} dos miradas de hoy &#8594;</a></p>')

    vids = arc.get("videos") or []
    if vids:
        v = vids[0]
        a(f'<p class="sec f">Vídeo destacado</p><div style="padding:0 22px"><a href="{esc(v["url"])}" style="text-decoration:none">'
          f'<img src="{esc(v.get("imgUrl"))}" alt="" width="556" style="display:block;width:100%;height:auto;border-radius:6px;border:0">'
          f'<p class="t g" style="margin-top:8px">&#9654; {esc(v.get("title"))}</p></a>'
          f'<p class="s f" style="color:#6a7278">{esc(v.get("channel"))} · {esc(v.get("note"))}</p></div>')

    cal = b.get("calendar") or []
    if cal:
        a('<p class="sec f">Agenda</p><div style="padding:0 22px"><table class="ag" role="presentation" cellpadding="0" cellspacing="0">')
        for c in cal[:3]:
            ev = esc(c.get("event"))
            if safe_url(c.get("url")):
                ev = f'<a href="{esc(c["url"])}" style="color:#101315">{ev}</a>'
            a(f'<tr><td class="f" style="color:#6a7278;white-space:nowrap">{esc(c.get("time"))}</td>'
              f'<td class="f"><b>{esc(c.get("place"))}</b> {ev}</td></tr>')
        a("</table></div>")

    if web:
        a(f'<a class="cta f" href="{esc(web)}">Ver las {len(stories)} historias, el mapa, los vídeos y el test &#8594;</a>')
    outlets = arc.get("outlets") or []
    links = " · ".join(f'<a href="{esc(o["homepage"])}">{esc(o["name"])}</a>' if o.get("homepage") else esc(o["name"]) for o in outlets)
    a(f'<div class="ft f"><b>Fuentes de hoy:</b> {links}<br><br>Resúmenes elaborados con IA a partir de estas fuentes; '
      f'abre el enlace original antes de citar una noticia.'
      + (f' <a href="{esc(page_url)}#periodicos">Cambiar mis periódicos</a>' if page_url else "")
      + (f' · <a href="{esc(site)}#archivo">Archivo</a>' if site else "")
      + "</div></div></body></html>")
    return "".join(o)


def render_text(arc, page_url):
    b = arc["briefing"]
    lines = [f"ROTATIVA — {long_date(b['date'])}", "", b["headline"], ""]
    lines += [f"• {e}" for e in b.get("essentials", [])]
    site = read_url(SITE_URL_FILE) or page_url
    if site:
        lines += ["", f"Edición completa: {site}#d-{arc['id']}"]
    for st in b["stories"][:7]:
        lines += ["", f"[{st['topic']}] {st['title']}", st.get("short") or st["summary"]]
        if (st.get("original") or {}).get("title"):
            o = st["original"]
            lines += [f"  Tal cual, en inglés ({o.get('source')}): {o['title']}" + (f" {o['text']}" if o.get("text") else "")]
        lines += [f"  {s.get('name')}: {s.get('url')}" for s in st.get("sources", [])[:3]]
    return "\n".join(lines)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefing", required=True)
    ap.add_argument("--data", required=True, help="extracted data branch (latest.json + img/)")
    ap.add_argument("--sources", default=os.path.join(ROOT, "sources.json"))
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--page-url", default=None)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    b = json.load(open(args.briefing, encoding="utf-8"))
    latest = json.load(open(os.path.join(args.data, "latest.json"), encoding="utf-8"))
    meta = json.load(open(args.sources, encoding="utf-8"))
    items, video_index = build_indexes(latest, meta)
    langs = {x["id"]: x.get("lang") for x in meta.get("sources", [])}
    names = {x["id"]: x.get("name") for x in meta.get("sources", [])}
    problems, warnings = validate(b, video_index, items, langs)
    if problems:
        print("INVALID briefing.json — fix these and run again:\n- " + "\n- ".join(problems))
        for w in warnings:
            print("warning: " + w)
        return 1
    for w in warnings:
        print("warning: " + w)

    page_url = args.page_url
    if page_url is None and os.path.exists(PAGE_URL_FILE):
        page_url = open(PAGE_URL_FILE, encoding="utf-8").read().strip()
    img_dir = os.path.join(args.data, "img")
    ed_id = f"{b['date']}-{b['edition']}"

    needed = []   # photo keys to embed for the web edition
    missing_photos = 0
    for st in b["stories"]:
        if st.get("original"):   # the English headline and standfirst, word for word
            it = items[st["original"]]
            st["original"] = {"url": it["l"], "source": names.get(it["source"]) or it["source"], "lang": "en",
                              "title": it.get("t", ""), "text": it.get("s", "")}
        key, url = resolve_story_image(st, items)
        st["img"], st["imgUrl"] = key, url
        st["countries"] = [c.upper() for c in st.get("countries", []) if isinstance(c, str) and len(c) == 2]
        if key and os.path.exists(os.path.join(img_dir, key + ".jpg")):
            needed.append(key)
        else:
            st["img"] = None
            missing_photos += 1

    videos = []
    for v in b.get("videos", []):
        meta_v = video_index.get(v.get("url"))
        if not meta_v:
            continue
        key = meta_v.get("k") if meta_v.get("k") and os.path.exists(os.path.join(img_dir, meta_v["k"] + ".jpg")) else None
        if key:
            needed.append(key)
        videos.append({"url": meta_v["l"], "note": v.get("note", ""), "title": meta_v["t"], "channel": meta_v.get("channel"),
                       "lang": meta_v.get("lang"), "date": meta_v.get("d"), "img": key, "imgUrl": meta_v.get("i")})
    b.pop("videos", None)  # resolved videos live at the top level of the record

    by_id = {s["id"]: s for s in meta["sources"]}
    used = [by_id[i] for i in dict.fromkeys(b.get("sourcesUsed", [])) if i in by_id]
    balance = {"side": {}, "region": {}}
    regions = {r["id"]: r["name"] for r in meta["regions"]}
    for s in used:
        balance["side"][s["side"]] = balance["side"].get(s["side"], 0) + 1
        rn = regions.get(s["region"], s["region"])
        balance["region"][rn] = balance["region"].get(rn, 0) + 1

    markets = [m for m in latest.get("markets", []) if "error" not in m and m.get("value") is not None]
    lead_key = b["stories"][0].get("img")
    cover_path = os.path.join(img_dir, f"{lead_key}_s.jpg") if lead_key else ""
    arc = {
        "id": ed_id, "date": b["date"], "edition": b["edition"], "headline": b["headline"],
        "briefing": b, "videos": videos, "markets": markets, "balance": balance,
        "outlets": [{"id": s["id"], "name": s["name"], "homepage": s.get("homepage"), "side": s["side"]} for s in used],
        "cover": data_uri(cover_path) if cover_path and os.path.exists(cover_path) else None,
        "collectedAt": latest.get("collectedAt"),
        "createdAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # Pack embedded photos into documents under the 256 KiB limit.
    chunks, current, size = [], {}, 0
    for key in dict.fromkeys(needed):
        uri = data_uri(os.path.join(img_dir, key + ".jpg"))
        if current and size + len(uri) > MEDIA_CHUNK_CHARS:
            chunks.append(current)
            current, size = {}, 0
        current[key] = uri
        size += len(uri)
    if current:
        chunks.append(current)
    arc["mediaDocs"] = [f"{ed_id}-{n}" for n in range(1, len(chunks) + 1)]

    os.makedirs(args.outdir, exist_ok=True)
    out = lambda name: os.path.join(args.outdir, name)
    writes = [f"set briefings/{ed_id} file_path={out('archive.json')}"]
    for n, chunk in enumerate(chunks, 1):
        with open(out(f"media-{n}.json"), "w", encoding="utf-8") as fh:
            json.dump({"edition": ed_id, "date": b["date"], "images": chunk}, fh)
        writes.append(f"set media/{ed_id}-{n} file_path={out(f'media-{n}.json')}")
    with open(out("archive.json"), "w", encoding="utf-8") as fh:
        json.dump(arc, fh, ensure_ascii=False)

    email_html = render_email(arc, page_url)
    with open(out("email.html"), "w", encoding="utf-8") as fh:
        fh.write(email_html)
    with open(out("email.txt"), "w", encoding="utf-8") as fh:
        fh.write(render_text(arc, page_url))
    d = dt.date.fromisoformat(b["date"])
    prefix = "Rotativa semanal" if b["edition"] == "semanal" else "Rotativa"
    subject = f"{prefix} · {DAYS[d.weekday()].capitalize()} {d.day} de {MONTHS[d.month - 1]}: {b['headline']}".rstrip(".")
    if len(subject) > 130:
        subject = subject[:129].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    with open(out("subject.txt"), "w", encoding="utf-8") as fh:
        fh.write(subject)
    with open(out("writes.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(writes) + "\n")

    print(f"OK: email.html ({len(email_html.encode('utf-8')) // 1024} KB), {len(b['stories'])} stories, "
          f"{len(b['stories']) - missing_photos} with photos, {len(videos)} videos, {len(chunks)} media docs.")
    print("ArtifactData writes to make (collection/doc_id and file):")
    print("\n".join("  " + w for w in writes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
