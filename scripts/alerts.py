"""Find what changed for alerts: new final scores and corrected scores since the last run.

Runs after update.py. Reads the built conference files, compares every recent finished game with the
copy saved last run (site/data/_finals.json, kept in the Actions cache with the rest of site/data), and
appends what changed to site/data/alerts.json. The site's server (api/worker.js) checks that file every
few minutes and sends the notifications, so this script never contacts anyone.

alerts.json keeps the last 48 hours of runs:
  {"runs": [{"id": "2026-11-11T17:15:02Z", "c": [change, ...]}]}
  change = {"g": game id, "cf": conference file ("" for events), "h"/"a": team keys, "hn"/"an": short
            names, "hs"/"as": score, "d": date, "cn": conference or event name,
            "k": "new" | "fix", "ph"/"pa": previous score (fixes only)}
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "data")
KEEP_DAYS = 21        # games this recent are tracked
NEW_DAYS = 3          # a newly posted score alerts only if the game was this recent
FIX_DAYS = 14         # a corrected score alerts only if the game was this recent
RUNS_HOURS = 48


def tidy(name):
    """Shorter team name for a phone notification: "Boerne SC ECNL RL STXCL G2013/14 Red" -> "Boerne SC Red"."""
    s = re.sub(r"\s+(Pre-?\s?)?ECNL(\s+RL)?(\s+\S+?)*?\s+[BG]\d{2,4}(/\d{2,4})?\b", "", name or "")
    return re.sub(r"\s+", " ", s).strip() or name or "TBD"


def collect(today):
    since = (today - timedelta(days=KEEP_DAYS)).isoformat()
    finals = {}
    cdir = os.path.join(OUT, "conf")
    for fn in sorted(os.listdir(cdir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(cdir, fn)) as f:
            D = json.load(f)
        pk = D.get("pool_key")
        short = {t["id"]: t.get("short") or t.get("name") for t in D.get("teams", [])}

        def add(g, cf, cn, names):
            if g.get("bad") or g.get("hs") is None or g.get("as") is None or (g.get("date") or "") < since:
                return
            if not g.get("home_id") or not g.get("away_id"):
                return
            gid = str(g["id"])
            if gid in finals and finals[gid]["cf"]:
                return   # league copy wins over an event copy
            finals[gid] = {"g": gid, "cf": cf, "h": f"{pk}-{g['home_id']}", "a": f"{pk}-{g['away_id']}",
                           "hn": tidy(names.get(g["home_id"]) or g.get("home")),
                           "an": tidy(names.get(g["away_id"]) or g.get("away")),
                           "hs": g["hs"], "as": g["as"], "d": g["date"], "cn": cn}

        for g in D.get("games", []):
            add(g, D["key"], D.get("conf_name") or "", short)
        for ev in D.get("events", []):
            en = {t["id"]: t.get("short") or t.get("name") for t in ev.get("teams", [])}
            for g in ev.get("games", []):
                add(g, "", ev.get("name") or "Event", en)
    return finals


def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    if not os.path.isdir(os.path.join(OUT, "conf")):
        print("alerts: no conference files")
        return
    finals = collect(today)
    prev_path, out_path = os.path.join(OUT, "_finals.json"), os.path.join(OUT, "alerts.json")
    prev = None
    if os.path.exists(prev_path):
        try:
            with open(prev_path) as f:
                prev = json.load(f)
        except Exception:
            prev = None
    changes = []
    if prev is not None:   # first run ever: just remember, alert nothing
        new_from, fix_from = (today - timedelta(days=NEW_DAYS)).isoformat(), (today - timedelta(days=FIX_DAYS)).isoformat()
        for gid, g in finals.items():
            p = prev.get(gid)
            if p is None:
                if g["d"] >= new_from:
                    changes.append(dict(g, k="new"))
            elif (p["hs"], p["as"]) != (g["hs"], g["as"]) and g["d"] >= fix_from:
                changes.append(dict(g, k="fix", ph=p["hs"], pa=p["as"]))
    runs = []
    if os.path.exists(out_path):
        try:
            with open(out_path) as f:
                runs = json.load(f).get("runs", [])
        except Exception:
            runs = []
    cut = (now - timedelta(hours=RUNS_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = [r for r in runs if r.get("id", "") >= cut]
    if changes:
        changes.sort(key=lambda c: (c["cf"], c["d"], c["g"]))
        runs.append({"id": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": changes})
    with open(out_path, "w") as f:
        json.dump({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "runs": runs}, f, separators=(",", ":"))
    with open(prev_path, "w") as f:
        json.dump(finals, f, separators=(",", ":"))
    print(f"alerts: {len(finals)} recent finals tracked, {len(changes)} changes this run"
          + ("" if prev is not None else " (first run: nothing sent)"))


if __name__ == "__main__":
    main()
