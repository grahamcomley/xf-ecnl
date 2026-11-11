"""MLS NEXT: games, teams and official tables from the public data file behind mlssoccer.com's
MLS NEXT schedule and standings pages (Kitman Labs "League Viewer";
https://mls-assist.theintelligenceplatform.com, robots.txt allows reading).

One file has everything for the season: every game (league, Pro Player Pathway and Flex) with UTC
kickoff + local time zone, field and score, plus the official tables for every bracket. We turn it
into the same game records update.py builds from the ECNL API, so the rest of the pipeline (ratings,
conference files, predictions, alerts) works unchanged.

Each bracket (e.g. U16 Northwest, U16 Central (Pro Player Pathway), U16 Flex Frontier) becomes one
"conference". The file is fetched at most every 30 minutes and cached.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SEASON = "mls-next-league-26-27"
URL = f"https://mls-assist.theintelligenceplatform.com/data/standings/{SEASON}.json"
CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "mlsnext_standings.json")
UA = "xf-ecnl-standings/1.0 (+https://sidelinestandings.com)"
MAX_AGE = 30 * 60
STAGE_NAME = {"League": "MLS NEXT", "Flex": "MLS NEXT Flex"}
_data = None


def load():
    """The season file (cached; a failed fetch falls back to the last copy)."""
    global _data
    if _data is not None:
        return _data
    fresh = os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < MAX_AGE
    if not fresh:
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept": "application/json"})
            raw = urllib.request.urlopen(req, timeout=60).read()
            json.loads(raw)   # only keep it if it parses
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "wb") as f:
                f.write(raw)
            print(f"  mlsnext: fetched {len(raw) // 1024} KB")
        except Exception as e:
            print(f"::warning::MLS NEXT fetch failed ({e}); using the last copy")
    if not os.path.exists(CACHE):
        _data = {}
        return _data
    with open(CACHE) as f:
        _data = json.load(f).get("competition_season") or {}
    return _data


def _local(start, tz):
    try:
        t = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ZoneInfo(tz or "America/New_York"))
    except Exception:
        t = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")


def pool(age):
    """Games for one age group ("U16"), in update.py's game format, plus official tables.

    Returns (games, team_conf, names, conf_names, official) where official is
    {(bracket id, bracket id): [{"id", "gp", "pts", "rank"}]} for brackets with a points table."""
    S = load()
    if not S:
        return [], {}, {}, {}, {}
    ages = {a["id"]: a["name"] for a in S.get("age_groups", [])}
    orgs = {o["id"]: o["name"] for o in S.get("organisations", [])}
    places = {p["id"]: p["name"] for p in S.get("event_locations", [])}
    brackets, member, comp_of = {}, {}, {}
    for st in S.get("competition_season_stages", []):
        for b in st.get("competition_brackets", []):
            if ages.get(b.get("age_group_id")) != age:
                continue
            brackets[b["id"]] = (st.get("name"), b.get("name"), b.get("standings") or [])
            for r in b.get("standings") or []:
                member.setdefault(r["squad_id"], set()).add(b["id"])
    for e in S.get("events", []):
        if e.get("competition_bracket_id") in brackets:
            comp_of[e["competition_bracket_id"]] = e.get("competition_id")

    def conf_label(bid):
        stage, name, _ = brackets[bid]
        return f"{STAGE_NAME.get(stage, 'MLS NEXT')} {name}"

    names, team_conf, conf_names, games = {}, {}, {}, []
    sq_name = {}
    for e in S.get("events", []):
        for side in ("home", "away"):
            sq_name[e[f"{side}_squad_id"]] = (e.get(f"{side}_organisation_id"), e.get(f"{side}_squad_name") or "")
    for e in S.get("events", []):
        if e.get("home_squad_name") != age and e.get("away_squad_name") != age:
            continue
        h, a = e["home_squad_id"], e["away_squad_id"]
        bid = e.get("competition_bracket_id")
        if bid not in brackets:   # no bracket on the game: the one bracket both teams share in that competition
            common = [b for b in (member.get(h, set()) & member.get(a, set())) if comp_of.get(b) in (None, e.get("competition_id"))]
            bid = common[0] if len(common) == 1 else None
        if bid is None:
            continue
        date, tm = _local(e["start_time"], e.get("local_timezone"))
        done = bool(e.get("completed")) and e.get("home_score") is not None and e.get("away_score") is not None
        for sid in (h, a):
            org, sn = sq_name.get(sid, (None, ""))
            base = orgs.get(org, "Team")
            names.setdefault(sid, base + (" II" if sn.upper().endswith("B") else ""))
        g = {"id": e["id"], "num": None, "event_id": bid, "flight": None,
             "type": {1606: "Pro Player Pathway", 1607: "Flex"}.get(e.get("competition_id"), "League"),
             "date": date, "time": tm, "home_id": h, "away_id": a,
             "home": names[h], "away": names[a], "home_club": sq_name.get(h, (None,))[0], "away_club": sq_name.get(a, (None,))[0],
             "hs": e.get("home_score") if done else None, "as": e.get("away_score") if done else None,
             # a draw goes to a shootout: winner 2 points, loser 1 (MLS NEXT's table)
             "hpk": e.get("home_penalty_shootout_score") if done and e["home_score"] == e["away_score"] and (e.get("home_penalty_shootout_score") or e.get("away_penalty_shootout_score")) else None,
             "apk": e.get("away_penalty_shootout_score") if done and e["home_score"] == e["away_score"] and (e.get("home_penalty_shootout_score") or e.get("away_penalty_shootout_score")) else None,
             "pkp": True, "venue": places.get(e.get("event_location_id"), ""),
             "status": "Final" if done else "", "bad": False,
             "conf": f"ev{bid}", "neutral": False, "weight_mult": 1.0, "source": "current",
             "event_name": conf_label(bid), "flight_id": bid, "division_id": None, "flight_name": brackets[bid][1],
             "tz": e.get("local_timezone")}
        games.append(g)
        conf_names[f"ev{bid}"] = conf_label(bid)
    # a team's home conference: its regular league bracket (not Flex)
    for bid, (stage, _, rows) in brackets.items():
        for r in rows:
            sid = r["squad_id"]
            if stage == "League" or sid not in team_conf:
                team_conf[sid] = f"ev{bid}"
            names.setdefault(sid, r.get("name") or "Team")
    official = {}
    for bid, (stage, _, rows) in brackets.items():
        if stage != "League":   # Flex tables also count games outside the bracket: not comparable game by game
            continue
        tab = []
        for r in rows:
            tv = r.get("tiebreaker_values") or {}
            if "points_penalty_shootout" not in tv:
                continue
            tab.append({"id": r["squad_id"], "gp": int(float(tv.get("matches_played") or 0)),
                        "pts": int(float(tv.get("points_penalty_shootout") or 0)), "rank": r.get("position")})
        if tab:
            official[(bid, bid)] = tab
    return games, team_conf, names, conf_names, official
