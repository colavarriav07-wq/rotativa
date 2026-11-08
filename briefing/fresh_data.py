#!/usr/bin/env python3
"""Get fresh headlines for today's edition and extract them to /tmp/data.

The GitHub collector runs on a schedule, but GitHub sometimes delays or skips
scheduled runs (on 2026-11-08 every morning run was skipped and the edition was
written from 19-hour-old headlines). So this script:

1. uses the collected data straight away if it is less than FRESH_MIN minutes old;
2. otherwise asks for a collection right now, by pushing a throwaway commit to the
   `collect-now` branch (a push there starts .github/workflows/collect.yml);
3. waits for the new data and extracts the `data` branch to --out.

Each call waits at most about WAIT_S seconds, so it fits in one shell command.
It prints one of:
  LISTO ...      /tmp/data is ready (fresh, or the best available after waiting)
  ESPERANDO ...  the collection is still running: run the script again
  SIN DATOS ...  there is no data branch at all

Usage: python3 briefing/fresh_data.py [--out /tmp/data]
"""
import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time

STATE_FILE = os.path.join(tempfile.gettempdir(), "rotativa-collect.json")
FRESH_MIN = 50       # data younger than this is used as it is
WAIT_S = 100         # longest wait in one call
GIVE_UP_MIN = 12     # after this long since the request, use whatever data exists

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="Rotativa", GIT_AUTHOR_EMAIL="rotativa@users.noreply.github.com",
               GIT_COMMITTER_NAME="Rotativa", GIT_COMMITTER_EMAIL="rotativa@users.noreply.github.com")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, env=GIT_ENV)


def now():
    return dt.datetime.now(dt.timezone.utc)


def parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def minutes_since(ts):
    return int((now() - parse(ts)).total_seconds() // 60)


def collected_at():
    """collectedAt of the data branch on GitHub, or None if there is none."""
    if git("fetch", "-q", "origin", "data").returncode != 0:
        return None
    shown = git("show", "origin/data:latest.json")
    if shown.returncode != 0:
        return None
    try:
        return json.loads(shown.stdout)["collectedAt"]
    except (ValueError, KeyError):
        return None


def extract(out):
    subprocess.run(f"rm -rf {shlex.quote(out)} && mkdir -p {shlex.quote(out)} && "
                   f"git archive origin/data | tar -x -C {shlex.quote(out)}", shell=True, check=True)


def request_collection():
    """Push a commit with main's files to `collect-now`; returns an error text or None."""
    tree = git("rev-parse", "HEAD^{tree}").stdout.strip()
    head = git("rev-parse", "HEAD").stdout.strip()
    made = git("commit-tree", tree, "-p", head, "-m", "Recoger noticias " + now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    if made.returncode != 0:
        return made.stderr.strip() or "git commit-tree failed"
    pushed = git("push", "-q", "-f", "origin", made.stdout.strip() + ":refs/heads/collect-now")
    if pushed.returncode != 0:
        return pushed.stderr.strip() or "git push failed"
    return None


def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ready(out, stamp, note=""):
    extract(out)
    print(f"LISTO: titulares recogidos {stamp} (hace {minutes_since(stamp)} min){note}. Datos en {out}.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/data")
    out = ap.parse_args().out

    state = load_state()
    stamp = collected_at()

    if "requested" not in state:
        if stamp and minutes_since(stamp) < FRESH_MIN:
            return ready(out, stamp)
        error = request_collection()
        state = {"requested": now().isoformat(), "before": stamp, "error": error}
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))
        if error:
            if not stamp:
                print("SIN DATOS: no hay rama data y no pude pedir una recogida: " + error)
                return 1
            return ready(out, stamp, f"; no pude pedir datos nuevos ({error})")
        print("Recogida pedida a GitHub; esperando a que termine…", flush=True)

    deadline = time.time() + WAIT_S
    while True:
        if stamp and stamp != state.get("before"):
            return ready(out, stamp)
        if time.time() >= deadline:
            break
        time.sleep(15)
        stamp = collected_at()

    waited = int((now() - parse(state["requested"])).total_seconds() // 60)
    if waited >= GIVE_UP_MIN:
        if not stamp:
            print("SIN DATOS: no hay rama data en GitHub.")
            return 1
        return ready(out, stamp, f"; la recogida nueva no llegó en {waited} min")
    print(f"ESPERANDO: la recogida sigue en marcha ({waited} min). Vuelve a ejecutar este mismo comando.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
