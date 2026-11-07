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
    s = re.sub(r"\b(ecnl|rl|[bg]\d{2,4}(/\d{2,4})?|u\d{2})\b", " ", s)
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


def build_pool(name, pc, cfg):
    """Return (games, team_conf, team_names, conf_names, club_conf)."""
    games, team_conf, names, conf_names = [], {}, {}, {}
    club_conf = {}
    conf_events = list(pc.get("conference_events") or [])
    if pc.get("discover_org_id"):
        for c in api.org_clubs(pc["discover_org_id"]):
            ev = to_int(c.get("eventID"))
            if ev:
                club_conf[to_int(c.get("clubID"))] = f"ev{ev}"
                if ev not in conf_events:
                    conf_events.append(ev)
    div = pc["division_name"]
    for ev in conf_events:
        _, flights = division_flights(ev, div)
        if not flights:
            continue
        ck = f"ev{ev}"
        conf_names[ck] = event_name(ev)
        for fl in flights:
            gs = normalize(api.flight_schedule(ev, fl), ck, neutral=False)
            for g in gs:
                for tid, tn, club in ((g["home_id"], g["home"], g["home_club"]), (g["away_id"], g["away"], g["away_club"])):
                    if tid:
                        team_conf[tid] = ck
                        names[tid] = tn
                        if club:
                            club_conf.setdefault(club, ck)
            games += gs
    for ev in pc.get("national_events") or []:
        _, flights = division_flights(ev, div)
        for fl in flights:
            games += normalize(api.flight_schedule(ev, fl), "national", neutral=True)
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
    for h in pc.get("history_events") or []:
        _, flights = division_flights(h["event_id"], h.get("division_name", div), permanent=True)
        for fl in flights:
            hist = normalize(api.flight_schedule(h["event_id"], fl, permanent=True), "national",
                             neutral=True, weight=cfg["model"]["history_weight"], source="history")
            for g in hist:
                for side in ("home", "away"):
                    tid, club = g[f"{side}_id"], g[f"{side}_club"]
                    if not tid:
                        continue
                    alias = (pc.get("team_aliases") or {}).get(g[side])
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


def backtest(games, team_conf, mcfg):
    """Replay the current season: predict each matchday using only earlier games."""
    cur = [g for g in rating_games(games) if g["source"] == "current"]
    dates = sorted({g["date"] for g in cur})
    if len(dates) < 4:
        return None
    n = ll = ll_base = correct = 0
    for d in dates[3:]:
        m = model.fit(rating_games(games), team_conf, mcfg, as_of=d, iters=40)
        if not m:
            continue
        prior = [g for g in cur if g["date"] < d]
        base_n = len(prior) + 3
        hw = (sum(1 for g in prior if g["hs"] > g["as"]) + 1) / base_n
        dr = (sum(1 for g in prior if g["hs"] == g["as"]) + 1) / base_n
        aw = 1 - hw - dr
        for g in (x for x in cur if x["date"] == d):
            lh, la = model.expected_goals(m, g["home_id"], g["away_id"], g["neutral"])
            w, dd, l, _ = model.outcome_probs(lh, la)
            res = 0 if g["hs"] > g["as"] else 1 if g["hs"] == g["as"] else 2
            p = [w, dd, l][res]
            ll += -math.log(max(p, 1e-6))
            ll_base += -math.log(max([hw, dr, aw][res], 1e-6))
            correct += int([w, dd, l].index(max(w, dd, l)) == res)
            n += 1
    if not n:
        return None
    return {"games": n, "accuracy": round(correct / n, 3),
            "logloss": round(ll / n, 3), "baseline_logloss": round(ll_base / n, 3)}


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
        bt = backtest(games, team_conf, cfg["model"]) if m else None
        print(f"  {len(games)} games, {len(rg)} rated, backtest={bt}")
        pools[pname] = dict(games=games, team_conf=team_conf, names=names,
                            conf_names=conf_names, model=m, backtest=bt,
                            links=conf_links(games, team_conf))

    index = []
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
        }
        with open(os.path.join(OUT, f"{comp['id']}.json"), "w") as f:
            json.dump(out, f, separators=(",", ":"))
        index.append({"id": comp["id"], "title": comp["title"], "kind": comp["kind"]})
        print(f"comp {comp['id']}: {len(games)} games, {len(teams)} teams")
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump({"updated": now, "competitions": index, "api": api.stats}, f)
    print("api", api.stats)


if __name__ == "__main__":
    main()
