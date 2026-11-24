"""Find what changed for alerts: new final scores and corrected scores since the last run.

Runs after update.py. Reads the built conference files, compares every recent finished game with the
copy saved last run (site/data/_finals.json, kept in the Actions cache with the rest of site/data), and
appends what changed to site/data/alerts.json. The site's server (api/worker.js) checks that file every
few minutes and sends the notifications, so this script never contacts anyone.

Also written to alerts.json, for A2 alerts:
  "up":  league/event games today and tomorrow (Pacific) with no score yet, for game-day reminders
         [id, conf, home key, away key, home, away, date, time (field's local time), venue, field's time zone or ""]
         [game id, conf file, home key, away key, home name, away name, date, time, venue]
  "wk":  last weekend's results (Fri-Sun) per team, for the Sunday wrap-up
         {team key: [place, teams in conf, points, latest result's run id, [[opponent, us, them], ...]]}
  each run's "m": big moments per team ({team key: ["Moved into 1st", ...]}) and "pos": places in
         each conference that had a change ({conf file: {team key: place}}), for "games near us".
Big moments: moved into 1st, into / below the playoff places, clinched a playoff place, clinched
1st, can no longer reach the playoff places. Each fires once per change (state in _moments.json).

alerts.json keeps the last 48 hours of runs:
  {"runs": [{"id": "2026-11-11T17:15:02Z", "c": [change, ...]}]}
  change = {"g": game id, "cf": conference file ("" for events), "h"/"a": team keys, "hn"/"an": short
            names, "hs"/"as": score, "d": date, "cn": conference or event name,
            "k": "new" | "fix", "ph"/"pa": previous score (fixes only)}
"""
import json
import os
import re
from zoneinfo import ZoneInfo
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
    return re.sub(r"\s+", " ", s).strip(" -") or name or "TBD"


PT = ZoneInfo("America/Los_Angeles")


def table(D):
    """Current table for one conference file, plus each team's best/worst possible final PPG."""
    pk = D.get("pool_key")
    ids = [t["id"] for t in D.get("teams", [])]
    t = {i: {"gp": 0, "pts": 0, "gf": 0, "ga": 0, "left": 0} for i in ids}
    for g in D.get("games", []):
        h, a = t.get(g.get("home_id")), t.get(g.get("away_id"))
        if h is None or a is None or g.get("bad"):
            continue
        if g.get("hs") is None or g.get("as") is None:
            h["left"] += 1; a["left"] += 1
            continue
        for me, f, ag in ((h, g["hs"], g["as"]), (a, g["as"], g["hs"])):
            me["gp"] += 1; me["gf"] += f; me["ga"] += ag
            me["pts"] += 3 if f > ag else 1 if f == ag else 0
    for r in t.values():
        r["ppg"] = r["pts"] / r["gp"] if r["gp"] else 0.0
        n = r["gp"] + r["left"]
        r["lo"] = r["pts"] / n if n else 0.0                 # loses every game left
        r["hi"] = (r["pts"] + 3 * r["left"]) / n if n else 0.0   # wins every game left
    order = sorted(ids, key=lambda i: (-t[i]["ppg"], -t[i]["pts"], -(t[i]["gf"] - t[i]["ga"]), -t[i]["gf"]))
    for n, i in enumerate(order):
        t[i]["pos"] = n + 1
    return {f"{pk}-{i}": t[i] for i in ids}, len(ids)


def flags(tab, k, spots):
    """[1st, in the playoff places, clinched playoff places, clinched 1st, out of the playoff places]"""
    me = tab[k]
    if me["gp"] < 2:
        return None
    others = [v for kk, v in tab.items() if kk != k]
    can_pass = sum(1 for v in others if v["hi"] >= me["lo"])   # could still finish level or above us
    sure_above = sum(1 for v in others if v["lo"] > me["hi"])  # will finish above us whatever happens
    s = spots or 0
    return [me["pos"] == 1, bool(s) and me["pos"] <= s, bool(s) and can_pass < s, can_pass < 1 and me["left"] < 99,
            bool(s) and sure_above >= s]


def moment_lines(old, new, spots):
    out = []
    if not old or not new:
        return out
    first, above, cs, cf, gone = new
    if cf and not old[3]:
        out.append("Clinched 1st")
    elif first and not old[0]:
        out.append("Moved into 1st")
    if spots:
        if cs and not old[2]:
            out.append(f"Clinched a top {spots} place")
        elif above and not old[1] and not first:
            out.append(f"Moved into the top {spots}")
        elif old[1] and not above:
            out.append(f"Dropped out of the top {spots}")
        if gone and not old[4]:
            out.append(f"Can no longer finish top {spots}")
    return out


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


SCHED_TRACK_DAYS = 60   # games this far ahead are remembered, so a move into the next 28 days is seen
SCHED_ALERT_DAYS = 28   # a change alerts only if the old or new date is within this many days (Graham: 28, Nov 23)
NEWEV_DAYS = 28         # new tournament schedules alert for events starting within this many days
NEWEV_TAG_DAYS = 3      # the Events tab shows "Just posted" this long (or until opened on that phone)


def new_event_schedules(confs, now, pt_today):
    """New event schedules (Graham, Nov 23): the first time a team's games (with a real opponent) appear in a
    tournament starting within NEWEV_DAYS. Confirmed when a later run (≥ SCHED_CONFIRM_MIN minutes on) still
    shows them; once per team per tournament; never for leagues (league files aren't "events" here) or other
    competitions. State: site/data/_evnew.json {"seen": {"team|event": run}, "pend": {key: run}, "tags": {event: run}}.
    Returns this run's confirmed items for alerts.json runs[].e; writes "evnew" {event id: when} into status.json."""
    path = os.path.join(OUT, "_evnew.json")
    try:
        with open(path) as f:
            state = json.load(f)
    except Exception:
        state = None
    first = state is None
    state = state or {}
    seen, pend, tags = state.get("seen", {}), state.get("pend", {}), state.get("tags", {})
    run_id = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today, to = pt_today.isoformat(), (pt_today + timedelta(days=NEWEV_DAYS)).isoformat()
    cur = {}
    for cf, D in confs.items():
        pk = D.get("pool_key")
        evs = D.get("events", [])
        for tid, idxs in (D.get("team_events") or {}).items():
            for i in idxs:
                ev = evs[i] if isinstance(i, int) and i < len(evs) else None
                if not ev or ev.get("competition"):
                    continue
                games = ev.get("games", [])
                dates = sorted(g["date"] for g in games if g.get("date"))
                if not dates or not (today <= dates[0] <= to):
                    continue
                tnames = {str(t["id"]): t.get("short") or t.get("name") for t in ev.get("teams", [])}
                ours = sorted([g for g in games if str(g.get("home_id")) == str(tid) or str(g.get("away_id")) == str(tid)],
                              key=lambda g: (g.get("date") or "", g.get("time") or ""))
                real = [g for g in ours if g.get("home_id") and g.get("away_id") and g.get("time") and g["time"] != "00:00"]
                if not real:
                    continue
                key = f"{pk}-{tid}|{ev['event_id']}"
                if key in cur:
                    continue
                last_real = real[-1]["date"]
                later = sorted({g["date"] for g in games if (not g.get("home_id") or not g.get("away_id")) and g.get("date") and g["date"] >= last_real})
                me_name = tnames.get(str(tid)) or ""
                for t in D.get("teams", []):
                    if str(t["id"]) == str(tid):
                        me_name = t.get("short") or t.get("name") or me_name
                def opp(g):
                    o = g["away_id"] if str(g["home_id"]) == str(tid) else g["home_id"]
                    return tidy(tnames.get(str(o)) or (g.get("away") if str(g["home_id"]) == str(tid) else g.get("home")))
                cur[key] = {"k": f"{pk}-{tid}", "tn": tidy(me_name), "ev": ev["event_id"], "fl": ev.get("flight_id"),
                            "en": re.sub(r"\s*20\d\d(-\d\d)?$", "", ev.get("name") or "Event").strip(), "first": dates[0],
                            "n": len(real), "g": [{"id": str(g["id"]), "d": g["date"], "t": g["time"], "tz": g.get("tz") or "",
                                                  "o": opp(g), "h": str(g["home_id"]) == str(tid), "v": (g.get("venue") or "")[:80]} for g in real[:3]],
                            "later": [later[0], later[-1]] if later else []}
    out = []
    new_seen, new_pend = dict(seen), {}
    for key, it in cur.items():
        if key in seen:
            continue
        if first:
            new_seen[key] = run_id
            continue
        since = pend.get(key)
        if since and (now - datetime.fromisoformat(since.replace("Z", "+00:00"))).total_seconds() / 60 >= SCHED_CONFIRM_MIN:
            out.append(it); new_seen[key] = run_id; tags[str(it["ev"])] = run_id
        else:
            new_pend[key] = since or run_id
    cut_seen = (now - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_seen = {k: v for k, v in new_seen.items() if v >= cut_seen or k in cur}
    cut = (now - timedelta(days=NEWEV_TAG_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tags = {k: v for k, v in tags.items() if v >= cut}
    with open(path, "w") as f:
        json.dump({"seen": new_seen, "pend": new_pend, "tags": tags}, f, separators=(",", ":"))
    status_path = os.path.join(OUT, "status.json")
    try:
        with open(status_path) as f:
            status = json.load(f)
        status["evnew"] = tags
        with open(status_path, "w") as f:
            json.dump(status, f, separators=(",", ":"))
    except Exception:
        pass
    out.sort(key=lambda x: (x["first"], x["k"]))
    return out
SCHED_CONFIRM_MIN = 20  # a change must still be there on a later run at least this many minutes on
SCHED_TAG_DAYS = 7      # the games list shows "Time changed" etc. this long


def _tbd(t):
    return not t or t == "00:00"


def schedule_changes(confs, now, pt_today):
    """Schedule changes (Graham, Nov 23): a new date, kickoff time or field for an upcoming game.
    Confirmed only when a later run still shows it (at least SCHED_CONFIRM_MIN minutes on, and on a full
    data run unless the game is today or tomorrow), so a one-run glitch never alerts. Never alerts for a
    TBD time getting its first time, an opponent being filled in (games without both teams aren't
    tracked), or a game leaving the schedule. State: site/data/_sched.json. Returns this run's
    confirmed changes for alerts.json, and writes the last SCHED_TAG_DAYS of them into status.json
    ("chg": {game id: [fields, when]}) for the games list."""
    path = os.path.join(OUT, "_sched.json")
    try:
        with open(path) as f:
            state = json.load(f)
    except Exception:
        state = None
    status_path = os.path.join(OUT, "status.json")
    try:
        with open(status_path) as f:
            status = json.load(f)
    except Exception:
        status = {}
    full = status.get("mode") != "quick"
    if os.environ.get("ALERTS_FULL"):   # testing only
        full = os.environ["ALERTS_FULL"] == "1"
    run_id = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    first = state is None
    state = state or {}
    base, pend, tags = state.get("base", {}), state.get("pend", {}), state.get("tags", {})
    start, end = pt_today.isoformat(), (pt_today + timedelta(days=SCHED_TRACK_DAYS)).isoformat()
    alert_to = (pt_today + timedelta(days=SCHED_ALERT_DAYS)).isoformat()
    soon = {pt_today.isoformat(), (pt_today + timedelta(days=1)).isoformat()}
    cur = {}
    for cf, D in confs.items():
        pk = D.get("pool_key")
        short = {t["id"]: t.get("short") or t.get("name") for t in D.get("teams", [])}
        lists = [(cf, D.get("conf_name") or "", D.get("games", []), short)] + [
            ("", ev.get("name") or "Event", ev.get("games", []), {t["id"]: t.get("short") or t.get("name") for t in ev.get("teams", [])})
            for ev in D.get("events", [])]
        for c2, cn, games, names in lists:
            for g in games:
                gid = str(g.get("id"))
                if g.get("hs") is not None or g.get("bad") or g.get("pending") or not g.get("home_id") or not g.get("away_id"):
                    continue
                if not (start <= (g.get("date") or "") <= end) or (gid in cur and cur[gid]["cf"]):
                    continue
                cur[gid] = {"d": g["date"], "t": "" if _tbd(g.get("time")) else g["time"], "v": (g.get("venue") or "")[:80],
                            "tz": g.get("tz") or "", "cf": c2, "cn": cn, "h": f"{pk}-{g['home_id']}", "a": f"{pk}-{g['away_id']}",
                            "hn": tidy(names.get(g["home_id"]) or g.get("home")), "an": tidy(names.get(g["away_id"]) or g.get("away"))}
    out, new_base, new_pend = [], {}, {}
    for gid, c in cur.items():
        now_v = [c["d"], c["t"], c["v"]]
        old = base.get(gid)
        if old is None or first:
            new_base[gid] = now_v + [c["tz"]]
            continue
        od, ot, ov = old[0], old[1], old[2]
        fields = []
        if c["d"] != od:
            fields.append("d")
        if c["t"] != ot and ot and c["t"]:   # TBD -> first time, or a time going back to TBD: no alert
            fields.append("t")
        if c["v"] != ov and ov and c["v"]:
            fields.append("v")
        if not fields or (min(od, c["d"]) > alert_to):
            new_base[gid] = now_v + [c["tz"]]   # nothing to tell (or too far ahead): just remember it
            continue
        p = pend.get(gid)
        if p and p["n"] == now_v:
            waited = (now - datetime.fromisoformat(p["since"].replace("Z", "+00:00"))).total_seconds() / 60
            if waited >= SCHED_CONFIRM_MIN and (full or c["d"] in soon):
                out.append({"g": gid, "cf": c["cf"], "cn": c["cn"], "h": c["h"], "a": c["a"], "hn": c["hn"], "an": c["an"],
                            "f": fields, "d": c["d"], "t": c["t"], "v": c["v"], "tz": c["tz"],
                            "od": od, "ot": ot, "ov": ov, "otz": old[3] if len(old) > 3 else ""})
                tags[gid] = [fields, run_id]
                new_base[gid] = now_v + [c["tz"]]
                continue
            new_pend[gid] = p
        else:
            new_pend[gid] = {"n": now_v, "since": run_id}
        new_base[gid] = old   # keep the old value until the change is confirmed
    cut = (now - timedelta(days=SCHED_TAG_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tags = {k: v for k, v in tags.items() if v[1] >= cut and k in cur}
    with open(path, "w") as f:
        json.dump({"base": new_base, "pend": new_pend, "tags": tags}, f, separators=(",", ":"))
    if status:
        status["chg"] = tags
        with open(status_path, "w") as f:
            json.dump(status, f, separators=(",", ":"))
    out.sort(key=lambda c: (c["d"], c["g"]))
    return out


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
    run_id = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for gid, g in finals.items():   # when we first saw each score (for the Sunday wrap-up)
        p = (prev or {}).get(gid)
        g["ts"] = p.get("ts", run_id) if p and (p["hs"], p["as"]) == (g["hs"], g["as"]) else run_id
    changes = []
    if prev is not None:   # first run ever: just remember, alert nothing
        new_from, fix_from = (today - timedelta(days=NEW_DAYS)).isoformat(), (today - timedelta(days=FIX_DAYS)).isoformat()
        for gid, g in finals.items():
            p = prev.get(gid)
            if p is None:
                if g["d"] >= new_from:
                    changes.append({k: v for k, v in dict(g, k="new").items() if k != "ts"})
            elif (p["hs"], p["as"]) != (g["hs"], g["as"]) and g["d"] >= fix_from:
                changes.append({k: v for k, v in dict(g, k="fix", ph=p["hs"], pa=p["as"]).items() if k != "ts"})
    # tables, big moments, places near us
    confs = {}
    cdir = os.path.join(OUT, "conf")
    for fn in os.listdir(cdir):
        if fn.endswith(".json"):
            with open(os.path.join(cdir, fn)) as f:
                confs[fn[:-5]] = json.load(f)
    tables = {cf: table(D) for cf, D in confs.items()}
    mpath = os.path.join(OUT, "_moments.json")
    try:
        with open(mpath) as f:
            mstate = json.load(f)
    except Exception:
        mstate = None
    changed_cf = {c["cf"] for c in changes if c["cf"]}
    moments, positions, new_state = {}, {}, {}
    for cf, (tab, n) in tables.items():
        spots = confs[cf].get("playoff_spots")
        for k in tab:
            fl = flags(tab, k, spots)
            if fl is None:
                continue
            key = cf + "|" + k
            new_state[key] = fl
            if mstate is not None and cf in changed_cf:
                lines = moment_lines(mstate.get(key), fl, spots)
                if lines:
                    moments.setdefault(k, []).extend(lines)
        if cf in changed_cf:
            positions[cf] = {k: v["pos"] for k, v in tab.items()}
    with open(mpath, "w") as f:
        json.dump(new_state, f, separators=(",", ":"))

    # upcoming games (today and tomorrow, Pacific) for game-day reminders
    pt_today = now.astimezone(PT).date()
    if os.environ.get("ALERTS_TODAY"):   # testing only
        pt_today = datetime.fromisoformat(os.environ["ALERTS_TODAY"]).date()
    days = {pt_today.isoformat(), (pt_today + timedelta(days=1)).isoformat()}
    up, seen_up = [], set()
    for cf, D in confs.items():
        pk = D.get("pool_key")
        short = {t["id"]: t.get("short") or t.get("name") for t in D.get("teams", [])}
        lists = [(cf, D.get("games", []), short)] + [("", ev.get("games", []), {t["id"]: t.get("short") or t.get("name") for t in ev.get("teams", [])}) for ev in D.get("events", [])]
        for c2, games, names in lists:
            for g in games:
                if g.get("date") not in days or g.get("hs") is not None or g.get("bad") or not g.get("home_id") or not g.get("away_id") or g["id"] in seen_up:
                    continue
                seen_up.add(g["id"])
                up.append([str(g["id"]), c2, f"{pk}-{g['home_id']}", f"{pk}-{g['away_id']}",
                           tidy(names.get(g["home_id"]) or g.get("home")), tidy(names.get(g["away_id"]) or g.get("away")),
                           g["date"], g.get("time") or "", (g.get("venue") or "")[:80], g.get("tz") or ""])

    # last weekend's results per team (Friday-Sunday, Pacific), for the Sunday wrap-up
    wd = pt_today.weekday()   # Mon=0 .. Sun=6
    fri = pt_today - timedelta(days=(wd - 4) % 7)
    sun = fri + timedelta(days=2)
    wk = {}
    if wd in (4, 5, 6, 0):   # Friday to Monday
        for g in finals.values():
            if not (fri.isoformat() <= g["d"] <= sun.isoformat()):
                continue
            for us_k, them, us_s, them_s in ((g["h"], g["an"], g["hs"], g["as"]), (g["a"], g["hn"], g["as"], g["hs"])):
                e = wk.setdefault(us_k, [0, 0, 0, "", []])
                e[4].append([them, us_s, them_s])
                e[3] = max(e[3], g["ts"])
        for cf, (tab, n) in tables.items():
            for k, v in tab.items():
                if k in wk and wk[k][1] == 0:
                    wk[k][0], wk[k][1], wk[k][2] = v["pos"], n, v["pts"]

    # last full weekend's results, for the owner's "Replay last weekend" test button
    last_sun = pt_today - timedelta(days=(pt_today.weekday() + 1) % 7 or 7) if pt_today.weekday() != 6 else pt_today - timedelta(days=7)
    last_fri = last_sun - timedelta(days=2)
    rep = [{k: v for k, v in g.items() if k != "ts"} for g in finals.values() if last_fri.isoformat() <= g["d"] <= last_sun.isoformat()]
    with open(os.path.join(OUT, "replay.json"), "w") as f:
        json.dump({"from": last_fri.isoformat(), "to": last_sun.isoformat(), "c": sorted(rep, key=lambda c: (c["d"], c["g"]))}, f, separators=(",", ":"))

    sched = schedule_changes(confs, now, pt_today)
    newev = new_event_schedules(confs, now, pt_today)

    runs = []
    if os.path.exists(out_path):
        try:
            with open(out_path) as f:
                runs = json.load(f).get("runs", [])
        except Exception:
            runs = []
    cut = (now - timedelta(hours=RUNS_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = [r for r in runs if r.get("id", "") >= cut]
    if changes or sched or newev:
        changes.sort(key=lambda c: (c["cf"], c["d"], c["g"]))
        r = {"id": run_id, "c": changes, "m": moments, "pos": positions}
        if sched:
            r["s"] = sched
        if newev:
            r["e"] = newev
        runs.append(r)
    with open(out_path, "w") as f:
        json.dump({"updated": run_id, "runs": runs, "up": up, "wk": wk}, f, separators=(",", ":"))
    with open(prev_path, "w") as f:
        json.dump(finals, f, separators=(",", ":"))
    print(f"alerts: {len(finals)} recent finals tracked, {len(changes)} changes, {len(sched)} schedule changes, {len(newev)} new event schedules, {sum(map(len, moments.values()))} big moments, {len(up)} upcoming, {len(wk)} weekend teams"
          + ("" if prev is not None else " (first run: nothing sent)"))


if __name__ == "__main__":
    main()
