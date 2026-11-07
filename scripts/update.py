"""Fetch ECNL data, rate every team, and write the JSON the website reads.

Run:  python scripts/update.py            (live, used by GitHub Actions)
      python scripts/update.py --offline  (use only data/cache, for testing)
"""
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

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
    """Find last season's events once (by org + season id); cached in data/history_catalog.json."""
    path = os.path.join(ROOT, "data", "history_catalog.json")
    cat = {}
    if os.path.exists(path):
        with open(path) as f:
            cat = json.load(f)
    key = f"{dh['org_id']}-{dh['org_season_id']}"
    if key in cat:
        return cat[key]
    if "--offline" in sys.argv:
        return []
    found = []
    lo, hi = dh["id_range"]
    print(f"  scanning events {lo}-{hi} for org {dh['org_id']} season {dh['org_season_id']} (one time)")
    for ev in range(lo, hi + 1):
        d = api.get(f"team/get-event-details-by-eventid/{ev}", cache=False)
        if isinstance(d, list) and d:
            d = d[0]
        if isinstance(d, dict) and d.get("orgID") == dh["org_id"] and d.get("orgSeasonID") == dh["org_season_id"]:
            found.append({"event_id": ev, "label": d.get("name") or f"Event {ev}"})
            print(f"    {ev}: {d.get('name')}")
    cat[key] = found
    with open(path, "w") as f:
        json.dump(cat, f, indent=1)
    return found


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
                raw = api.get(f"Event/get-schedules-by-flight/{e['event_id']}/{fl.get('flightID')}/0",
                              max_age_hours=2, permanent=done) or []
                gs = normalize(raw, ck, neutral=not league)
                for g in gs:
                    g["event_name"] = e["name"]
                    for tid, tn, club in ((g["home_id"], g["home"], g["home_club"]), (g["away_id"], g["away"], g["away_club"])):
                        if tid:
                            names.setdefault(tid, tn)
                            if league:
                                team_conf[tid] = ck
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
    rg = rating_games(games)
    ev = sorted((g for g in rg if g["date"] >= start), key=lambda g: g["date"])
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
            "recent": sorted(done, key=lambda e: e["date"], reverse=True)[:10]}


def main():
    offline = "--offline" in sys.argv
    if offline:
        api.DELAY = 0
        orig = api.get

        def cached_only(path, max_age_hours=0, permanent=False):
            if not os.path.exists(api._cache_path(path)):
                return None
            return orig(path, permanent=True)
        api.get = cached_only
    cfg = load_config()
    os.makedirs(OUT, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    pools = {}
    for pname, pc in cfg["pools"].items():
        print(f"pool {pname}")
        games, team_conf, names, conf_names = build_pool(pname, pc, cfg)
        rg = rating_games(games)
        m = model.fit(rg, team_conf, cfg["model"])
        # Accuracy is scored on this season's games (new age groups) only.
        bt = backtest(games, team_conf, cfg["model"], start=pc["age_rules"]["new_age_from"]) if m else None
        print(f"  {len(games)} games, {len(rg)} rated, backtest={bt}")
        pools[pname] = dict(games=games, team_conf=team_conf, names=names,
                            conf_names=conf_names, model=m, backtest=bt,
                            links=conf_links(games, team_conf))

    index = []
    log = {}
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            log = json.load(f)
    for comp in cfg["competitions"]:
        P = pools[comp["pool"]]
        m = P["model"]
        raw = api.flight_schedule(comp["event_id"], comp["flight_id"])
        ck = f"ev{comp['event_id']}" if comp["kind"] == "conference" else "national"
        games = normalize(raw, ck, neutral=(comp["kind"] != "conference"))
        team_ids = sorted({i for g in games for i in (g["home_id"], g["away_id"]) if i})
        tnames = {}
        for g in games:
            if g["home_id"]: tnames[g["home_id"]] = g["home"]
            if g["away_id"]: tnames[g["away_id"]] = g["away"]
        computed = standings_from_games(games, team_ids)
        official = []
        if comp["kind"] == "conference":
            for r in api.flight_standings(comp["event_id"], comp["division_id"], comp["flight_id"]):
                official.append({"id": to_int(r.get("teamID")), "gp": to_int(r.get("gp")),
                                 "w": to_int(r.get("wins")), "d": to_int(r.get("draws")),
                                 "l": to_int(r.get("losses")), "gf": to_int(r.get("goalsfor")),
                                 "ga": to_int(r.get("goalsagainst")), "pts": to_int(r.get("standingpoints")),
                                 "ppg": r.get("ppg")})
        # rating rank across the whole pool
        ranked = []
        if m:
            ranked = sorted(m["att"].keys(), key=lambda t: -model.strength(m, t))
        rank_of = {t: i + 1 for i, t in enumerate(ranked)}
        teams = []
        for tid in team_ids:
            conf = P["team_conf"].get(tid, "other")
            conf_games = [g for g in P["games"] if g["conf"] == conf and g["source"] == "current"]
            rec = None
            if comp["kind"] == "bracket":
                peers = {i for g in conf_games for i in (g["home_id"], g["away_id"]) if i}
                rec = next((r for r in standings_from_games(conf_games, peers) if r["id"] == tid), None)
            teams.append({
                "id": tid, "name": tnames.get(tid), "short": short_name(tnames.get(tid)),
                "p": team_params(m, tid) if m else [0, 0],
                "strength": round(model.strength(m, tid), 2) if m else 0,
                "pool_rank": rank_of.get(tid), "conf": conf,
                "conf_name": P["conf_names"].get(conf, "Other"),
                "conf_links": round(P["links"].get(conf, 0), 1),
                "games_rated": sum(1 for g in rating_games(P["games"]) if tid in (g["home_id"], g["away_id"])),
                "games_new": sum(1 for g in rating_games(P["games"]) if tid in (g["home_id"], g["away_id"])
                                 and g["date"] >= cfg["pools"][comp["pool"]]["age_rules"]["new_age_from"]),
                "conf_record": rec,
            })
        out = {
            "comp": comp, "updated": now,
            "model": {"mu": round(m["mu"], 4), "home": round(m["home"], 4)} if m else None,
            "pool": {"name": comp["pool"], "teams_rated": len(ranked),
                     "games_rated": len(rating_games(P["games"])), "backtest": P["backtest"]},
            "teams": teams, "games": [{k: g[k] for k in ("id", "num", "type", "date", "time", "home_id", "away_id",
                                                          "home", "away", "hs", "as", "hpk", "apk", "venue", "status", "bad")}
                                      for g in games],
            "official": official, "computed": computed,
            "live_record": update_prediction_log(comp, games, m, log),
        }
        with open(os.path.join(OUT, f"{comp['id']}.json"), "w") as f:
            json.dump(out, f, separators=(",", ":"))
        index.append({"id": comp["id"], "title": comp["title"], "kind": comp["kind"]})
        print(f"comp {comp['id']}: {len(games)} games, {len(teams)} teams")
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=1)
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump({"updated": now, "competitions": index, "api": api.stats}, f)
    print("api", api.stats)


if __name__ == "__main__":
    main()
