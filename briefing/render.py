#!/usr/bin/env python3
"""Render briefing.json (written by Claude) into a compact HTML email, a plain-text
version, the subject line, and the archive document for the Rotativa page.

Usage:
  python briefing/render.py --briefing briefing.json --latest latest.json --outdir out/
Writes out/email.html, out/email.txt, out/subject.txt and out/archive.json.

briefing.json schema (all text in Spanish):
{
  "date": "2026-11-07",
  "edition": "diaria" | "semanal",
  "headline": "One sentence that sums up the day",
  "essentials": ["3-5 short key points"],
  "marketNote": "1-2 sentences on what moved markets (optional)",
  "calendar": [{"time": "10:00", "place": "BCE", "event": "..."}],
  "sections": [{"topic": "Geopolítica y mundo",
                "stories": [{"title": "...", "summary": "2-4 sentences",
                             "sources": [{"name": "El País", "url": "https://..."}]}]}],
  "twoViews": [{"title": "...", "context": "one neutral sentence",
                "progressive": {"summary": "...", "sources": [{"name": "...", "url": "..."}]},
                "conservative": {"summary": "...", "sources": [{"name": "...", "url": "..."}]}}],
  "worldView": [{"title": "...", "views": [{"country": "China", "source": "CGTN",
                                            "url": "https://...", "framing": "..."}]}],
  "trends": ["weekly edition only: 3-5 trends of the week"],
  "sourcesUsed": ["elpais", "bbc"]
}
"""
import argparse
import datetime as dt
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE_URL_FILE = os.path.join(ROOT, "briefing", "page_url.txt")

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]

# Gmail keeps <style> blocks with class selectors, which keeps the email small.
CSS = """
body{margin:0;padding:0;background:#f3f4f2}
.o{background:#f3f4f2;padding:20px 10px}
.s{max-width:640px;margin:0 auto;background:#fff;border:1px solid #dfe2df;padding:26px 26px 18px}
.f,.s td,.s li,.s p{font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;color:#15191d}
.m{font-family:Georgia,'Times New Roman',serif;font-size:30px;letter-spacing:6px;font-weight:700;color:#15191d;margin:0}
.m b{color:#1d5b4f}
.dt{font-size:12px;color:#5d6670;margin:4px 0 0}
.hl{font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.3;margin:18px 0 8px;color:#15191d}
ul{padding-left:18px;margin:8px 0 0}
li{font-size:15px;line-height:1.5;margin:0 0 6px}
.h{font-size:11px;letter-spacing:2px;text-transform:uppercase;font-weight:700;border-bottom:2px solid #15191d;padding-bottom:6px;margin:28px 0 4px;color:#15191d}
.t{font-family:Georgia,'Times New Roman',serif;font-size:18px;line-height:1.3;font-weight:700;margin:14px 0 4px;color:#15191d}
.p{font-size:15px;line-height:1.55;margin:0}
.x{font-size:12px;color:#5d6670;margin:4px 0 8px}
.x a,.lk{color:#1d5b4f;text-decoration:none;font-weight:600}
.n{font-size:13px;color:#5d6670;margin:6px 0 0}
table.k{border-collapse:collapse;width:100%}
table.k td{padding:7px 8px;border-bottom:1px solid #e6e8e5;font-size:13px}
.r{text-align:right;white-space:nowrap}
.up{color:#1e7a46}.dn{color:#b3261e}
table.c td{padding:5px 12px 5px 0;font-size:14px;line-height:1.45;vertical-align:top}
.tm{color:#5d6670;white-space:nowrap;font-size:13px}
.v{border-left:4px solid #7a828a;background:#f6f7f5;padding:8px 12px;margin:8px 0}
.v.pr{border-color:#b3443f}.v.co{border-color:#2e5e8e}
.vl{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;margin:0 0 4px}
.pr .vl{color:#b3443f}.co .vl{color:#2e5e8e}
.ft{font-size:12px;line-height:1.5;color:#5d6670;border-top:1px solid #dfe2df;margin-top:28px;padding-top:12px}
"""


def esc(text):
    return html.escape(str(text or ""), quote=True)


def safe_url(url):
    url = str(url or "")
    return url if url.startswith(("https://", "http://")) else ""


def long_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{DAYS[d.weekday()]} {d.day} de {MONTHS[d.month - 1]} de {d.year}"


def validate(b):
    problems = []
    for key in ("date", "edition", "headline", "sections"):
        if not b.get(key):
            problems.append(f"missing '{key}'")
    try:
        dt.date.fromisoformat(b.get("date", ""))
    except (ValueError, TypeError):
        problems.append("date must be YYYY-MM-DD")
    if b.get("edition") not in ("diaria", "semanal"):
        problems.append("edition must be 'diaria' or 'semanal'")
    for s in b.get("sections", []):
        if not s.get("topic") or not s.get("stories"):
            problems.append(f"section without topic/stories: {s.get('topic')}")
        for st in s.get("stories", []):
            if not st.get("title") or not st.get("summary"):
                problems.append(f"story without title/summary in {s.get('topic')}")
            if not st.get("sources"):
                problems.append(f"story without sources: {st.get('title')}")
            for src in st.get("sources", []):
                if not safe_url(src.get("url")):
                    problems.append(f"source without http(s) url in '{st.get('title')}': {src.get('name')}")
    for tv in b.get("twoViews", []):
        for side in ("progressive", "conservative"):
            if not (tv.get(side) or {}).get("summary"):
                problems.append(f"twoViews '{tv.get('title')}' missing {side} summary")
    return problems


def links(sources):
    out = []
    for s in sources or []:
        url = safe_url(s.get("url"))
        out.append(f'<a href="{esc(url)}">{esc(s.get("name"))}</a>' if url else esc(s.get("name")))
    return " · ".join(out)


def fmt_value(v):
    s = f"{v:,.4f}" if v < 10 else f"{v:,.0f}" if v > 1000 else f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def good_markets(latest):
    return [m for m in (latest or {}).get("markets", []) if "error" not in m and m.get("value") is not None]


def render_html(b, latest, page_url):
    weekly = b.get("edition") == "semanal"
    o = []
    a = o.append
    a(f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      f'<title>{esc(b["headline"])}</title><style>{CSS.strip()}</style></head><body>')
    a(f'<div style="display:none;max-height:0;overflow:hidden">{esc(" · ".join(b.get("essentials", [])[:2]))}</div>')
    a('<div class="o"><div class="s">')
    a('<p class="m">ROTA<b>TIVA</b></p>')
    a(f'<p class="dt f">{"Edición semanal" if weekly else "Informe diario"} · {esc(long_date(b["date"]))}</p>')
    a(f'<p class="hl">{esc(b["headline"])}</p>')
    if b.get("essentials"):
        a("<ul>" + "".join(f"<li>{esc(e)}</li>" for e in b["essentials"]) + "</ul>")
    if b.get("trends"):
        a('<p class="h f">Tendencias de la semana</p><ul>' + "".join(f"<li>{esc(t)}</li>" for t in b["trends"]) + "</ul>")

    mk = good_markets(latest)
    if mk:
        a('<p class="h f">Mercados</p>')
        if b.get("marketNote"):
            a(f'<p class="p f" style="margin:6px 0 8px">{esc(b["marketNote"])}</p>')
        rows = []
        for m in mk:
            ch = m.get("changePct")
            cls = "up" if (ch or 0) > 0 else "dn" if (ch or 0) < 0 else ""
            arrow = "▲" if (ch or 0) > 0 else "▼" if (ch or 0) < 0 else ""
            chs = f"{ch:+.2f}%".replace(".", ",") if ch is not None else "—"
            rows.append(f'<tr><td>{esc(m["name"])}</td><td class="r">{fmt_value(m["value"])}</td><td class="r {cls}">{arrow} {chs}</td></tr>')
        a('<table class="k" role="presentation">' + "".join(rows) + "</table>")

    if b.get("calendar"):
        a('<p class="h f">Agenda de hoy</p><table class="c" role="presentation">')
        for c in b["calendar"]:
            a(f'<tr><td class="tm">{esc(c.get("time"))}</td><td><b>{esc(c.get("place"))}</b> {esc(c.get("event"))}</td></tr>')
        a("</table>")

    for section in b.get("sections", []):
        a(f'<p class="h f">{esc(section["topic"])}</p>')
        for st in section.get("stories", []):
            a(f'<p class="t">{esc(st["title"])}</p><p class="p f">{esc(st["summary"])}</p><p class="x f">{links(st.get("sources"))}</p>')

    if b.get("twoViews"):
        a('<p class="h f">Dos miradas</p><p class="n f">La misma noticia contada por la prensa progresista y por la conservadora.</p>')
        for tv in b["twoViews"]:
            a(f'<p class="t">{esc(tv["title"])}</p>')
            if tv.get("context"):
                a(f'<p class="n f">{esc(tv["context"])}</p>')
            for key, cls, label in (("progressive", "pr", "Visión progresista"), ("conservative", "co", "Visión conservadora")):
                v = tv.get(key) or {}
                a(f'<div class="v {cls}"><p class="vl f">{label}</p><p class="p f">{esc(v.get("summary"))}</p><p class="x f">{links(v.get("sources"))}</p></div>')

    if b.get("worldView"):
        a('<p class="h f">Cómo lo cuenta el mundo</p>')
        for wv in b["worldView"]:
            a(f'<p class="t">{esc(wv["title"])}</p><table class="c" role="presentation">')
            for v in wv.get("views", []):
                url = safe_url(v.get("url"))
                src = f'<a class="lk" href="{esc(url)}">{esc(v.get("source"))}</a>' if url else esc(v.get("source"))
                a(f'<tr><td><b>{esc(v.get("country"))}</b></td><td>{esc(v.get("framing"))} <span class="tm">({src})</span></td></tr>')
            a("</table>")

    n = len(b.get("sourcesUsed", []))
    foot = (f"Elaborado con IA a partir de {n} fuentes. " if n else "Elaborado con IA. ")
    foot += "Los resúmenes pueden contener errores: abre el enlace original antes de citar una noticia."
    if page_url:
        foot += f'<br>Cambia tus periódicos o lee el archivo: <a class="lk" href="{esc(page_url)}">Rotativa</a>'
    a(f'<p class="ft f">{foot}</p></div></div></body></html>')
    return "".join(o)


def render_text(b, latest, page_url):
    lines = [f"ROTATIVA — {long_date(b['date'])}", "", b["headline"], ""]
    lines += [f"• {e}" for e in b.get("essentials", [])]
    mk = good_markets(latest)
    if mk:
        lines += ["", "MERCADOS"] + [f"  {m['name']}: {fmt_value(m['value'])} ({m.get('changePct')}%)" for m in mk]
    for section in b.get("sections", []):
        lines += ["", section["topic"].upper(), ""]
        for st in section.get("stories", []):
            lines += [st["title"], st["summary"],
                      "  " + " · ".join(f"{s.get('name')}: {s.get('url')}" for s in st.get("sources", [])), ""]
    for tv in b.get("twoViews", []):
        lines += ["", "DOS MIRADAS — " + tv["title"],
                  "Visión progresista: " + (tv.get("progressive") or {}).get("summary", ""),
                  "Visión conservadora: " + (tv.get("conservative") or {}).get("summary", "")]
    if page_url:
        lines += ["", f"Tus periódicos y el archivo: {page_url}"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefing", required=True)
    ap.add_argument("--latest")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--page-url", default=None)
    args = ap.parse_args()

    b = json.load(open(args.briefing, encoding="utf-8"))
    problems = validate(b)
    if problems:
        print("INVALID briefing.json — fix these and run again:\n- " + "\n- ".join(problems))
        return 1
    latest = json.load(open(args.latest, encoding="utf-8")) if args.latest else {}
    page_url = args.page_url
    if page_url is None and os.path.exists(PAGE_URL_FILE):
        page_url = open(PAGE_URL_FILE, encoding="utf-8").read().strip()

    os.makedirs(args.outdir, exist_ok=True)
    email_html = render_html(b, latest, page_url)
    with open(os.path.join(args.outdir, "email.html"), "w", encoding="utf-8") as fh:
        fh.write(email_html)
    with open(os.path.join(args.outdir, "email.txt"), "w", encoding="utf-8") as fh:
        fh.write(render_text(b, latest, page_url))
    d = dt.date.fromisoformat(b["date"])
    prefix = "Rotativa semanal" if b["edition"] == "semanal" else "Rotativa"
    subject = f"{prefix} · {DAYS[d.weekday()].capitalize()} {d.day} de {MONTHS[d.month - 1]}: {b['headline']}"
    with open(os.path.join(args.outdir, "subject.txt"), "w", encoding="utf-8") as fh:
        fh.write(subject[:200])
    archive = {
        "date": b["date"],
        "edition": b["edition"],
        "headline": b["headline"],
        "briefing": b,
        "markets": good_markets(latest),
        "collectedAt": (latest or {}).get("collectedAt"),
        "createdAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(os.path.join(args.outdir, "archive.json"), "w", encoding="utf-8") as fh:
        json.dump(archive, fh, ensure_ascii=False)
    print(f"OK: email.html ({len(email_html.encode('utf-8')) // 1024} KB), email.txt, subject.txt, archive.json in {args.outdir}")
    print("Archive doc id: " + f"{b['date']}-{b['edition']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
