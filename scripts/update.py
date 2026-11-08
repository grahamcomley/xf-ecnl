"""Fetch ECNL data, rate every team, and write the JSON the website reads.

Run:  python scripts/update.py            (live, used by GitHub Actions)
      python scripts/update.py --offline  (use only data/cache, for testing)
"""
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
import ecnl_api as api  # noqa: E402
import model  # noqa: E402
import catalog  # noqa: E402
import matcher  # noqa: E402
import surf  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "site", "data")
BAD_STATUS = re.compile(r"cancel|forfeit|abandon|void", re.I)


def load_config():
    with open(os.path.join(ROOT, "config.json")) as f:
        return json.load(f)


def short_name(name):
    if not name:
        return name
    s = re.sub(r"\s+ECNL(\s+RL)?\s+[BG]\d{2,4}(/\d{2,4})?", "", name)
    return s.strip()


def norm_key(club_id, name):
    s = (name or "").lower()
    s = re.sub(r"\b(ecnl|rl|academy|cda|fc|sc|soccer|club|[bg]\d{2,4}(/\d{2,4})?|u\d{2})\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return f"{club_id}|{s}"


def to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalize(raw, conf_key, neutral, weight=1.0, source="current"):
    out = []
    for g in raw or []:
        hid, aid = to_int(g.get("hometeamID")), to_int(g.get("awayteamID"))
        date = (g.get("gameDate") or "")[:10]
        status = " ".join(str(g.get(k) or "") for k in ("status", "flagText"))
        out.append({
            "id": g.get("matchID"),
            "num": to_int(g.get("gamenumber")),
            "event_id": g.get("eventID"),
            "flight": g.get("flight"),
            "type": g.get("type"),
            "date": date,
            "time": (g.get("gameTime") or "")[:5],
            "home_id": hid, "away_id": aid,
            "home": g.get("homeTeam"), "away": g.get("awayTeam"),
            "home_club": to_int(g.get("homeTeamClubID")), "away_club": to_int(g.get("awayTeamClubID")),
            "hs": to_int(g.get("hometeamscore")), "as": to_int(g.get("awayteamscore")),
            "hpk": to_int(g.get("hometeamPKscore")), "apk": to_int(g.get("awayteamPKscore")),
            "venue": " · ".join(x for x in (g.get("complex"), g.get("venue")) if x),
            "status": status.strip(),
            "bad": bool(BAD_STATUS.search(status)),
            "conf": conf_key, "neutral": neutral, "weight_mult": weight, "source": source,
        })
    return out


def division_flights(event_id, division_name, permanent=False):
    for d in api.event_divisions(event_id, permanent=permanent):
        if (d.get("divisionName") or "").strip().upper() == division_name.upper():
            return d.get("divisionID"), [f.get("flightID") for f in d.get("flightList") or []]
    return None, []


def event_name(event_id, permanent=False):
    d = api.get(f"team/get-event-details-by-eventid/{event_id}", max_age_hours=168, permanent=permanent)
    if isinstance(d, list) and d:
        d = d[0]
    if isinstance(d, dict):
        for k in ("eventName", "name", "EventName"):
            if d.get(k):
                return d[k]
    return f"Event {event_id}"


def discover_history(name, dh):
    """Last season's events for one ECNL org. The event-ID range is scanned once (all
    orgs) and saved in data/history_catalog.json; delete the file to rescan."""
    path = os.path.join(ROOT, "data", "history_catalog.json")
    cat = {}
    if os.path.exists(path):
        with open(path) as f:
            cat = json.load(f)
    lo, hi = dh["id_range"]
    rkey = f"range-{lo}-{hi}"
    if rkey not in cat:
        old = cat.get(f"{dh['org_id']}-{dh.get('org_season_id', 70)}")
        if "--offline" in sys.argv or "--quick" in sys.argv or QUICK:
            return old or []
        print(f"  scanning events {lo}-{hi} for last season's events (one time)")
        found = []
        for ev in range(lo, hi + 1):
            d = api.get(f"team/get-event-details-by-eventid/{ev}", cache=False)
            if isinstance(d, list) and d:
                d = d[0]
            if isinstance(d, dict) and d.get("name"):
                found.append({"event_id": ev, "label": d.get("name"), "org_id": d.get("orgID"),
                              "org_season_id": d.get("orgSeasonID")})
        cat[rkey] = found
        with open(path, "w") as f:
            json.dump(cat, f, indent=1)
        seasons = sorted({(e["org_id"], e["org_season_id"]) for e in found if e["org_id"]}, key=str)
        print(f"    found {len(found)} events; org/season pairs: {seasons}")
    evs = [e for e in cat[rkey] if e.get("org_id") == dh["org_id"]]
    if "org_season_id" in dh:
        return [e for e in evs if e.get("org_season_id") == dh["org_season_id"]]
    prior = [e["org_season_id"] for e in evs if e.get("org_season_id") and e["org_season_id"] < dh["season_lt"]]
    if not prior:
        return []
    last = max(prior)
    return [e for e in evs if e.get("org_season_id") == last]


def _decide_mode():
    """--auto: full refresh if the last full run is older than 2 hours on game weekends
    (Fri-Sun, Pacific) or 6 hours on weekdays; otherwise a quick check of live games."""
    if "--auto" not in sys.argv:
        return
    path = os.path.join(ROOT, "data", "last_full.txt")
    last = None
    if os.path.exists(path):
        try:
            last = datetime.fromisoformat(open(path).read().strip())
        except ValueError:
            last = None
    now = datetime.now(timezone.utc)
    pacific_weekday = (now - timedelta(hours=8)).weekday()  # Mon=0 .. Sun=6
    limit = timedelta(hours=2 if pacific_weekday >= 4 else 6)
    if last and now - last < limit:
        sys.argv.append("--quick")


_decide_mode()
QUICK = "--quick" in sys.argv
HOT = {"refetched": 0}


def flight_raw(event_id, flight_id, done):
    """Schedule for one flight. Finished events: cached forever. A flight with a game in the
    last two days still missing its score is re-fetched every run (so new scores show fast);
    otherwise reuse a copy younger than 2 hours (full run) or 24 hours (quick run)."""
    path = f"Event/get-schedules-by-flight/{event_id}/{flight_id}/0"
    if done:
        return api.get(path, permanent=True) or []
    cp = api._cache_path(path)
    hot = False
    if os.path.exists(cp):
        try:
            with open(cp) as f:
                cached = json.load(f) or []
            today = datetime.now(timezone.utc).date()
            lo = (today - timedelta(days=2)).isoformat()
            hi = (today + timedelta(days=1)).isoformat()
            hot = any(lo <= (g.get("gameDate") or "")[:10] <= hi and g.get("hometeamscore") is None
                      and g.get("hometeamID") for g in cached if isinstance(g, dict))
        except (ValueError, OSError):
            hot = True
    if hot:
        HOT["refetched"] += 1
        return api.get(path, max_age_hours=0) or []
    return api.get(path, max_age_hours=24 if QUICK else 2) or []


def build_pool(name, pc, cfg):
    """Return (games, team_conf, team_names, conf_names, club_conf)."""
    games, team_conf, names, conf_names = [], {}, {}, {}
    club_conf = {}
    rules = pc["age_rules"]
    events = catalog.current_catalog(cfg.get("catalog", {}).get("start_id", 4240))
    today = datetime.now(timezone.utc).date().isoformat()
    matched = 0
    for e in events:
        if (e.get("start") or "") < rules["since"]:
            continue
        done = (e.get("end") or "9999") < today  # finished events never change: cache forever
        divs = [d for d in api.event_divisions(e["event_id"], permanent=done)
                if catalog.division_matches(d.get("divisionName"), e, rules)]
        if not divs:
            continue
        league = catalog.is_league(e)
        ck = f"ev{e['event_id']}" if league else "event"
        if league:
            conf_names[ck] = e["name"]
        for d in divs:
            for fl in d.get("flightList") or []:
                raw = flight_raw(e["event_id"], fl.get("flightID"), done)
                gs = normalize(raw, ck, neutral=not league)
                for g in gs:
                    g["event_name"] = e["name"]
                    g["event_id"] = e["event_id"]
                    g["flight_id"] = fl.get("flightID")
                    g["division_id"] = d.get("divisionID")
                    g["flight_name"] = fl.get("flightName")
                    for tid, tn, club in ((g["home_id"], g["home"], g["home_club"]), (g["away_id"], g["away"], g["away_club"])):
                        if tid:
                            names.setdefault(tid, tn)
                            if league:
                                team_conf.setdefault(tid, ck)  # a team's league never gets overwritten
                                if club:
                                    club_conf.setdefault(club, ck)
                games += gs
                matched += 1
    print(f"  {matched} matching flights from {len(events)} catalog events")
    # A team entered in an outside tournament may get a new ID there: map it back to its
    # league team when club and name match.
    league_by_key = {}
    for g in games:
        if g["conf"] != "event":
            for side in ("home", "away"):
                if g[f"{side}_id"]:
                    league_by_key.setdefault(norm_key(g[f"{side}_club"], g[side]), g[f"{side}_id"])
                    k = norm_key(g[f"{side}_club"], g[side])
                    if k.endswith(" 1"):
                        league_by_key.setdefault(k[:-2], g[f"{side}_id"])
    remapped = 0
    for g in games:
        if g["conf"] == "event":
            for side in ("home", "away"):
                tid = g[f"{side}_id"]
                if tid and tid not in team_conf:
                    m = league_by_key.get(norm_key(g[f"{side}_club"], g[side]))
                    if m:
                        g[f"{side}_id"] = m
                        remapped += 1
    print(f"  remapped {remapped} tournament entries onto league teams")
    # Surf Sports events (Surf Cup etc.): match their team names to our league teams.
    sc = pc.get("surf")
    if sc:
        sg = surf.pool_games(sc["division"], rules["since"])
        other = {}
        for g in sg:
            other[g["home_id"]] = g["home"]
            other[g["away_id"]] = g["away"]
        ours = {t: names.get(t) for t in team_conf if names.get(t)}
        mp, review = matcher.match_all(other, ours, {k: v for k, v in (sc.get("team_aliases") or {}).items() if not k.startswith("_")})
        for g in sg:
            for side in ("home", "away"):
                oid = g[f"{side}_id"]
                if oid in mp:
                    g[f"{side}_id"] = mp[oid]
                else:
                    names.setdefault(oid, g[side])
        for g in sg:
            g["weight_mult"] = sc.get("weight", 1.0)
        games += sg
        rv_path = os.path.join(ROOT, "data", f"surf_review_{name}.json")
        with open(rv_path, "w") as f:
            json.dump({"matched": {other[k]: names.get(v) for k, v in mp.items()}, "check_these": review}, f, indent=1)
        print(f"  surf: {len(sg)} games, matched {len(mp)} of {len(other)} teams ({len(review)} to review)")
    # past seasons: map teams onto this season's team ids by club + name
    current_by_key, current_by_name = {}, {}
    for g in games:
        for tid, tn, club in ((g["home_id"], g["home"], g["home_club"]), (g["away_id"], g["away"], g["away_club"])):
            if tid:
                current_by_name.setdefault(tn, tid)
                k = norm_key(club, tn)
                current_by_key.setdefault(k, tid)
                if k.endswith(" 1"):  # "XF ... 1" was probably plain "XF ..." last season
                    current_by_key.setdefault(k[:-2], tid)
    club_alias = {int(k): v for k, v in (pc.get("club_aliases") or {}).items() if k.isdigit()}
    team_alias = {k: v for k, v in (pc.get("team_aliases") or {}).items() if not k.startswith("_")}
    for oc, nc in club_alias.items():
        if nc in club_conf:
            club_conf[oc] = club_conf[nc]
    dw = pc.get("history_division_weight", 1.0)
    hist_events = list(pc.get("history_events") or [])
    if pc.get("discover_history"):
        known = {h["event_id"] for h in hist_events}
        default_divs = pc.get("history_division_names") or []
        for h in discover_history(name, pc["discover_history"]):
            if h["event_id"] not in known:
                hist_events.append({**h, "division_names": default_divs})
    for h in hist_events:
        for dname in h.get("division_names") or pc.get("history_division_names") or []:
            _, flights = division_flights(h["event_id"], dname, permanent=True)
            for fl in flights:
                hist = normalize(api.flight_schedule(h["event_id"], fl, permanent=True), "national",
                                 neutral=True, weight=cfg["model"]["history_weight"] * dw, source="history")
                for g in hist:
                    for side in ("home", "away"):
                        tid, club = g[f"{side}_id"], g[f"{side}_club"]
                        if not tid:
                            continue
                        club = club_alias.get(club, club)
                        g[f"{side}_club"] = club
                        alias = team_alias.get(g[side])
                        mapped = current_by_name.get(alias) if alias else current_by_key.get(norm_key(club, g[side]))
                        if mapped:
                            g[f"{side}_id"] = mapped
                        else:
                            g[f"{side}_id"] = f"h{tid}"
                            names.setdefault(f"h{tid}", g[side])
                games += hist
    # teams seen only at national events: conference from their club
    for g in games:
        for side in ("home", "away"):
            tid = g[f"{side}_id"]
            if tid and tid not in team_conf:
                team_conf[tid] = club_conf.get(g[f"{side}_club"], "other")
                names.setdefault(tid, g[side])
    seen = set()
    uniq = []
    for g in games:
        key = (g["id"], g["source"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(g)
    return uniq, team_conf, names, conf_names


def rating_games(games):
    return [g for g in games if g["home_id"] and g["away_id"] and not g["bad"]
            and g["hs"] is not None and g["as"] is not None]


def standings_from_games(games, team_ids):
    t = {i: {"id": i, "gp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0} for i in team_ids}
    for g in games:
        if g["hs"] is None or g["as"] is None or g["home_id"] not in t or g["away_id"] not in t:
            continue
        h, a = t[g["home_id"]], t[g["away_id"]]
        for me, them, f, ag in ((h, a, g["hs"], g["as"]), (a, h, g["as"], g["hs"])):
            me["gp"] += 1; me["gf"] += f; me["ga"] += ag
            if f > ag: me["w"] += 1
            elif f == ag: me["d"] += 1
            else: me["l"] += 1
    for r in t.values():
        r["pts"] = 3 * r["w"] + r["d"]
        r["ppg"] = round(r["pts"] / r["gp"], 2) if r["gp"] else 0.0
        r["gd"] = r["gf"] - r["ga"]
    return list(t.values())


def team_params(m, tid):
    c = m["conf"].get(tid, "__none__")
    return [round(m["att"].get(tid, 0.0) + m["catt"].get(c, 0.0), 4),
            round(m["dfn"].get(tid, 0.0) + m["cdfn"].get(c, 0.0), 4)]


def conf_links(games, team_conf):
    """Count weighted cross-conference games per conference (for confidence)."""
    links = {}
    for g in rating_games(games):
        a, b = team_conf.get(g["home_id"]), team_conf.get(g["away_id"])
        if a and b and a != b:
            links[a] = links.get(a, 0) + g["weight_mult"]
            links[b] = links.get(b, 0) + g["weight_mult"]
    return links


def backtest(games, team_conf, mcfg, start="2025-11-01", step_days=14):
    """Replay both seasons: every two weeks, refit using only earlier games and
    predict the next two weeks. Reports accuracy, calibration and log-loss."""
    rg = [g for g in rating_games(games) if g.get("weight_mult", 1) > 0]
    # Score on league-team games (ECNL / ECNL RL), not outside-tournament games between unknown teams.
    ev = sorted((g for g in rg if g["date"] >= start and g["home_id"] in team_conf and g["away_id"] in team_conf),
                key=lambda g: g["date"])
    if len(ev) < 30:
        return None
    from datetime import date, timedelta

    def d2o(d):
        y, m, dd = (int(x) for x in d.split("-"))
        return date(y, m, dd)
    cur = d2o(ev[0]["date"])
    end = d2o(ev[-1]["date"])
    n = correct = notlose = 0
    ll = ll_base = 0.0
    buckets = {}
    while cur <= end:
        nxt = cur + timedelta(days=step_days)
        a, b = cur.isoformat(), nxt.isoformat()
        chunk = [g for g in ev if a <= g["date"] < b]
        if chunk:
            m = model.fit(rg, team_conf, mcfg, as_of=a, iters=30)
            prior = [g for g in rg if g["date"] < a]
            if m and prior:
                k = len(prior) + 3
                base = [(sum(1 for g in prior if g["hs"] > g["as"]) + 1) / k,
                        (sum(1 for g in prior if g["hs"] == g["as"]) + 1) / k]
                base.append(1 - base[0] - base[1])
                for g in chunk:
                    lh, la = model.expected_goals(m, g["home_id"], g["away_id"], g["neutral"])
                    w, d, l, _ = model.outcome_probs(lh, la)
                    p = [w, d, l]
                    res = 0 if g["hs"] > g["as"] else 1 if g["hs"] == g["as"] else 2
                    pick = p.index(max(p))
                    n += 1
                    correct += int(pick == res)
                    nl = (pick == 0 and res != 2) or (pick == 2 and res != 0) or pick == 1
                    notlose += int(nl)
                    ll += -math.log(max(p[res], 1e-6))
                    ll_base += -math.log(max(base[res], 1e-6))
                    bk = "70+" if max(p) >= 0.7 else "60-69" if max(p) >= 0.6 else "50-59" if max(p) >= 0.5 else "<50"
                    B = buckets.setdefault(bk, [0, 0, 0])
                    B[0] += 1; B[1] += int(pick == res); B[2] += int(nl)
        cur = nxt
    if not n:
        return None
    return {"games": n, "accuracy": round(correct / n, 3), "fav_not_lose": round(notlose / n, 3),
            "logloss": round(ll / n, 3), "baseline_logloss": round(ll_base / n, 3),
            "buckets": {k: {"games": v[0], "won": round(v[1] / v[0], 3), "not_lose": round(v[2] / v[0], 3)}
                        for k, v in buckets.items()}}


LOG_PATH = os.path.join(ROOT, "data", "prediction_log.json")
DRAW_GAP = 0.03  # must match site/index.html


def update_prediction_log(comp, games, m, log):
    """Record our pick for each upcoming game once (before it's played), then
    fill in the result when the score is posted. Gives a live accuracy record."""
    entries = log.setdefault(comp["id"], {})
    for g in games:
        if not (g["home_id"] and g["away_id"]) or g["bad"]:
            continue
        key = str(g["id"])
        played = g["hs"] is not None and g["as"] is not None
        if key not in entries and not played and m:
            lh, la = model.expected_goals(m, g["home_id"], g["away_id"], comp["kind"] != "conference")
            w, d, l, _ = model.outcome_probs(lh, la)
            pick = "D" if abs(w - l) < DRAW_GAP else ("H" if w > l else "A")
            entries[key] = {"date": g["date"], "home": g["home"], "away": g["away"],
                            "p": [round(w, 3), round(d, 3), round(l, 3)], "pick": pick}
        if key in entries and played and "result" not in entries[key]:
            entries[key]["result"] = "H" if g["hs"] > g["as"] else "D" if g["hs"] == g["as"] else "A"
            entries[key]["score"] = f"{g['hs']}-{g['as']}"
    done = [e for e in entries.values() if "result" in e]
    fav_ok = sum(1 for e in done if e["result"] == e["pick"] or (e["pick"] != "D" and e["result"] == "D"))
    return {"games": len(done), "correct": sum(1 for e in done if e["result"] == e["pick"]),
            "not_lost": fav_ok,
            "picks": {k: e["pick"] for k, e in entries.items()},
            "recent": sorted(done, key=lambda e: e["date"], reverse=True)[:10]}


GAME_KEYS = ("id", "num", "type", "date", "time", "home_id", "away_id", "home", "away",
             "hs", "as", "hpk", "apk", "venue", "status", "bad")


def league_type(name):
    n = (name or "").lower()
    rl = "rl" in n.split() or "regional league" in n
    girls = "girls" in n
    if "pre-ecnl" in n or "pre ecnl" in n:
        return f"Pre-ECNL {'Girls' if girls else 'Boys'}"
    if "ecnl" in n:
        return f"ECNL {'RL ' if rl else ''}{'Girls' if girls else 'Boys'}"
    return "Other leagues"


def playoff_for(cfg, league, conf_name, age, flight_count):
    """Automatic ECNL playoff spots for one conference table, or (None, None)."""
    if flight_count > 1:   # conference split into divisions: qualification isn't one table
        return None, None
    region = re.sub(r"^(ECNL|Pre-ECNL)\s+(RL\s+)?(Boys|Girls)\s+", "", conf_name).strip()
    v = ((cfg.get("playoffs") or {}).get(league) or {}).get(region, {}).get(str(age))
    if not v:
        return None, None
    n, cl = (v, 0) if isinstance(v, int) else (v[0], v[1])
    label = f"Top {n} = {'RL' if ' RL ' in f' {league} ' else 'ECNL'} Playoffs"
    if cl:
        label += f" · {n + 1}th{'' if cl == 1 else f'–{n + cl}th'} = Conference League Playoffs"
    return n, label


def short_conf(name):
    return re.sub(r"\s*20\d\d-\d\d$", "", name or "").strip()


def main():
    offline = "--offline" in sys.argv
    if offline:
        api.DELAY = 0
        orig = api.get

        def cached_only(path, max_age_hours=0, permanent=False, cache=True):
            if not os.path.exists(api._cache_path(path)):
                return None
            return orig(path, permanent=True)
        api.get = cached_only
    cfg = load_config()
    os.makedirs(os.path.join(OUT, "conf"), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    today = datetime.now(timezone.utc).date().isoformat()
    log = {}
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            log = json.load(f)
    bt_path = os.path.join(ROOT, "data", "backtests.json")
    saved_bt = {}
    if os.path.exists(bt_path):
        with open(bt_path) as f:
            saved_bt = json.load(f)
    featured = {(c["event_id"], c["flight_id"]): c for c in cfg["competitions"] if c["kind"] == "conference"}
    # carry the live prediction record over from the old per-tab names
    for c in featured.values():
        newk = f"{cfg['pools'][c['pool']]['key']}-{c['event_id']}-{c['flight_id']}"
        if c["id"] in log and newk not in log:
            log[newk] = log.pop(c["id"])
    teams_index, legacy, written = {}, {}, set()

    for pname, pc in cfg["pools"].items():
        pkey = pc["key"]
        print(f"pool {pname}")
        games, team_conf, names, conf_names = build_pool(pname, pc, cfg)
        rg = rating_games(games)
        m = model.fit(rg, team_conf, cfg["model"])
        if QUICK and pname in saved_bt:
            bt = saved_bt[pname]
        else:
            bt = backtest(games, team_conf, cfg["model"], start=pc["age_rules"]["new_age_from"]) if m else None
            saved_bt[pname] = bt
        print(f"  {len(games)} games, {len(rg)} rated, backtest={bt and (bt['games'], bt['accuracy'])}")
        links = conf_links(games, team_conf)
        ranked = sorted(m["att"].keys(), key=lambda t: -model.strength(m, t)) if m else []
        rank_of = {t: i + 1 for i, t in enumerate(ranked)}
        new_from = pc["age_rules"]["new_age_from"]
        rated_count, new_count = {}, {}
        for g in rg:
            for t in (g["home_id"], g["away_id"]):
                rated_count[t] = rated_count.get(t, 0) + 1
                if g["date"] >= new_from:
                    new_count[t] = new_count.get(t, 0) + 1
        conf_record_cache = {}

        def conf_record(tid):
            c = team_conf.get(tid)
            if not c:
                return None
            if c not in conf_record_cache:
                cg = [g for g in games if g["conf"] == c and g["source"] == "current"]
                peers = {i for g in cg for i in (g["home_id"], g["away_id"]) if i}
                conf_record_cache[c] = {r["id"]: r for r in standings_from_games(cg, peers)}
            return conf_record_cache[c].get(tid)

        def team_obj(tid, with_record=False):
            c = team_conf.get(tid, "other")
            o = {"id": tid, "name": names.get(tid), "short": short_name(names.get(tid)),
                 "p": team_params(m, tid) if m else [0, 0],
                 "strength": round(model.strength(m, tid), 2) if m else 0,
                 "pool_rank": rank_of.get(tid), "conf": c, "conf_name": short_conf(conf_names.get(c, "Other")),
                 "conf_links": round(links.get(c, 0), 1),
                 "games_rated": rated_count.get(tid, 0), "games_new": new_count.get(tid, 0)}
            if with_record:
                o["conf_record"] = conf_record(tid)
            return o

        # Events (national events, tournaments) happening soon or just played: attach to their teams.
        ev_groups = {}
        for g in games:
            if g["conf"] == "event" and g["source"] == "current" and g.get("flight_id"):
                ev_groups.setdefault((g["event_id"], g["flight_id"]), []).append(g)
        soon = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
        recent = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()
        events_by_team = {}
        for (eid, fid), gs in ev_groups.items():
            dates = [g["date"] for g in gs]
            if max(dates) < recent or min(dates) > soon:
                continue
            tids = sorted({t for g in gs for t in (g["home_id"], g["away_id"]) if t}, key=str)
            block = {"event_id": eid, "flight_id": fid, "name": gs[0].get("event_name"),
                     "flight": gs[0].get("flight_name"),
                     "bracket": any(g["type"] == "Bracket" or re.search(r"winner|loser", (g["home"] or ""), re.I) for g in gs),
                     "ecnl_link": f"https://app.athleteone.com/public/event/{eid}/schedules-standings",
                     "games": [{k: g[k] for k in GAME_KEYS} for g in gs],
                     "teams": [team_obj(t, with_record=True) for t in tids]}
            for t in tids:
                events_by_team.setdefault(t, []).append(block)

        # One file per league flight (conference).
        flights = {}
        for g in games:
            if re.match(r"ev\d+$", g["conf"]) and g["source"] == "current" and g.get("flight_id"):
                flights.setdefault((g["event_id"], g["flight_id"]), []).append(g)
        div_flights = {}
        for (eid, fid), gs in flights.items():
            if len({t for g in gs for t in (g["home_id"], g["away_id"]) if t}) >= 3:
                div_flights.setdefault((eid, gs[0].get("division_id")), set()).add(fid)
        for (eid, fid), gs in flights.items():
            tids = sorted({t for g in gs for t in (g["home_id"], g["away_id"]) if t}, key=str)
            if len(tids) < 3:
                continue
            fkey = f"{pkey}-{eid}-{fid}"
            comp = featured.get((eid, fid), {})
            cname = short_conf(gs[0].get("event_name"))
            official = []
            if comp:
                for r in api.flight_standings(eid, comp["division_id"], fid):
                    official.append({"id": to_int(r.get("teamID")), "gp": to_int(r.get("gp")),
                                     "pts": to_int(r.get("standingpoints"))})
            # each event stored once; teams point to it by index
            ev_list, ev_index, evs = [], {}, {}
            for t in tids:
                for b in events_by_team.get(t, []):
                    k = (b["event_id"], b["flight_id"])
                    if k not in ev_index:
                        ev_index[k] = len(ev_list)
                        ev_list.append(b)
                    evs.setdefault(str(t), []).append(ev_index[k])
            spots, spots_label = playoff_for(cfg, league_type(gs[0].get("event_name")), cname,
                                             pc["age_rules"]["age"], len(div_flights.get((eid, gs[0].get("division_id")), ())))
            pseudo = {"id": fkey, "kind": "conference"}
            out = {
                "key": fkey, "pool": pname, "pool_key": pkey, "updated": now,
                "conf_name": cname, "league": league_type(gs[0].get("event_name")),
                "age_label": pc.get("label", ""), "flight": gs[0].get("flight_name"),
                "playoff_spots": spots, "playoff_label": spots_label,
                "ecnl_link": f"https://app.athleteone.com/public/event/{eid}/schedules-standings",
                "model": {"mu": round(m["mu"], 4), "home": round(m["home"], 4)} if m else None,
                "pool_stats": {"teams_rated": len(ranked), "games_rated": len(rg), "backtest": bt},
                "teams": [team_obj(t) for t in tids],
                "games": [{k: g[k] for k in GAME_KEYS} for g in gs],
                "official": official, "computed": standings_from_games(gs, tids),
                "events": ev_list, "team_events": evs,
                "live_record": update_prediction_log(pseudo, gs, m, log),
            }
            with open(os.path.join(OUT, "conf", fkey + ".json"), "w") as f:
                json.dump(out, f, separators=(",", ":"))
            written.add(fkey + ".json")
            for t in tids:
                tk = f"{pkey}-{t}"
                # a team can sit in several league flights (stages, league cups): keep the one with most games
                score = (sum(1 for g in gs if t in (g["home_id"], g["away_id"])), "cup" not in cname.lower())
                if tk not in teams_index or score > teams_index[tk][0]:
                    teams_index[tk] = (score, {"k": tk, "n": names.get(t), "s": short_name(names.get(t)), "c": cname,
                                               "l": out["league"], "a": pc.get("label", ""), "f": fkey})
                if comp and names.get(t) == comp.get("focus_team"):
                    legacy[comp["id"]] = tk
        print(f"  wrote {len([w for w in written if w.startswith(pkey)])} conference files")

    # remove conference files no longer produced
    for fn in os.listdir(os.path.join(OUT, "conf")):
        if fn not in written:
            os.remove(os.path.join(OUT, "conf", fn))
    teams_index = sorted((e for _, e in teams_index.values()), key=lambda x: (x["a"], x["l"], x["c"], x["s"] or ""))
    with open(os.path.join(OUT, "teams.json"), "w") as f:
        json.dump(teams_index, f, separators=(",", ":"))
    legacy.update({c["id"]: legacy.get(c.get("legacy_of", ""), "") for c in cfg["competitions"] if c.get("legacy_of")})
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump({"updated": now, "legacy": legacy, "pools": [p.get("label") for p in cfg["pools"].values()]}, f)
    with open(os.path.join(OUT, "status.json"), "w") as f:
        json.dump({"checked": now, "mode": "quick" if QUICK else "full", "refetched_flights": HOT["refetched"]}, f)
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=1)
    with open(bt_path, "w") as f:
        json.dump(saved_bt, f)
    if not QUICK and not offline:
        with open(os.path.join(ROOT, "data", "last_full.txt"), "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    print("mode", "quick" if QUICK else "full", "api", api.stats, "hot flights refetched", HOT["refetched"])


if __name__ == "__main__":
    main()
