"""Writes a fake data/cache built from real results seen on 2026-11-06,
so the pipeline and page can be tested without network access.
Run: python tests/make_fixture.py && python scripts/update.py --offline
"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
C = os.path.join(ROOT, "data", "cache")
os.makedirs(C, exist_ok=True)


def put(path, data):
    with open(os.path.join(C, path.replace("/", "__") + ".json"), "w") as f:
        json.dump(data, f)


NW = {"3RSC": (134995, 2229), "Columbia": (69797, 2322), "Eastside": (71905, 398), "PacNW": (68796, 2331),
      "Seattle": (62227, 1643), "Snohomish": (131395, 2522), "Washington": (81102, 112),
      "XF1": (82130, 3476), "XF2": (82135, 3476)}
NWN = {"3RSC": "3RSC ECNL B2010/11", "Columbia": "Columbia Premier SC ECNL B2010/11",
       "Eastside": "Eastside FC ECNL B2010/11", "PacNW": "PacNW SC ECNL B2010/11",
       "Seattle": "Seattle United ECNL B2010/11", "Snohomish": "Snohomish United ECNL B2010/11",
       "Washington": "Washington Premier ECNL B2010/11", "XF1": "XF ECNL B2010/11 1", "XF2": "XF ECNL B2010/11 2"}
nw_rows = """2026-08-30|15:00|3RSC|Washington|3|1
2026-09-12|13:00|Eastside|Columbia|2|0
2026-09-12|14:00|XF1|Snohomish|3|1
2026-09-13|09:00|PacNW|Snohomish|1|1
2026-09-13|10:00|XF2|Eastside|0|7
2026-09-13|11:00|Columbia|XF1|0|3
2026-09-13|15:00|3RSC|Seattle|2|2
2026-09-19|09:00|XF2|XF1|0|3
2026-09-19|09:00|Snohomish|Eastside|1|7
2026-09-19|11:00|Columbia|3RSC|1|2
2026-09-19|13:00|Washington|PacNW|2|4
2026-09-26|09:00|Washington|XF1|0|4
2026-09-26|09:00|XF2|Seattle|1|3
2026-09-26|15:00|PacNW|Columbia|1|2
2026-09-27|15:00|Snohomish|3RSC|0|1
2026-10-03|15:00|Snohomish|Washington|0|3
2026-10-04|11:00|Columbia|XF2|3|1
2026-10-04|14:00|XF1|Seattle|1|1
2026-10-04|15:00|3RSC|Eastside|1|1
2026-10-10|13:00|Seattle|PacNW|1|0
2026-10-17|09:00|Snohomish|Seattle|0|5
2026-10-17|11:00|Columbia|Washington|0|2
2026-10-17|12:00|XF2|XF1|0|4
2026-10-17|13:00|Eastside|PacNW|2|3
2026-10-18|13:00|XF1|3RSC|6|1
2026-10-24|12:30|XF2|Snohomish|2|1
2026-10-24|13:00|Seattle|Columbia|5|0
2026-10-24|15:00|Washington|Eastside|0|1
2026-10-25|11:00|3RSC|PacNW|4|2
2026-11-01|00:00|PacNW|XF1||
2026-11-01|15:00|3RSC|XF2|4|0
2026-11-01|15:30|Seattle|Washington|4|0
2026-11-08|11:00|Snohomish|Columbia||
2026-11-08|13:00|Eastside|Seattle||
2026-11-08|15:30|XF2|PacNW||
2026-11-14|09:00|XF1|Eastside||
2026-11-14|09:00|Snohomish|PacNW||
2026-11-14|13:00|Seattle|XF2||
2026-11-14|15:00|Washington|Columbia||
2026-12-05|00:00|3RSC|Snohomish||
2026-12-05|13:00|Eastside|Washington||
2026-12-06|13:00|Washington|XF2||
2026-12-12|00:00|XF1|Columbia||
2026-12-12|00:00|XF2|Washington||
2026-12-12|15:00|Eastside|3RSC||
2026-12-19|00:00|PacNW|Eastside||
2027-01-09|00:00|XF2|Columbia||
2027-01-09|00:00|PacNW|Washington||
2027-01-09|08:00|Seattle|3RSC||
2027-01-09|11:00|Eastside|XF1||
2027-01-16|00:00|XF1|Washington||
2027-01-16|00:00|PacNW|3RSC||
2027-01-16|11:00|Columbia|Eastside||
2027-01-16|13:00|Snohomish|XF2||
2027-01-17|06:01|PacNW|Seattle||
2027-01-30|00:00|3RSC|Columbia||
2027-01-30|00:00|PacNW|XF2||
2027-01-30|09:00|Snohomish|XF1||
2027-01-30|11:00|Washington|Seattle||
2027-02-06|00:00|3RSC|XF1||
2027-02-06|11:00|Columbia|Seattle||
2027-02-06|11:00|Eastside|XF2||
2027-02-07|13:00|Washington|Snohomish||
2027-02-13|00:00|Columbia|PacNW||
2027-02-13|08:00|Seattle|XF1||
2027-02-13|11:00|Washington|3RSC||"""


def game(mid, ev, fl, date, time, h, a, hs, as_, ids, names, typ="Group Play", num=None):
    hi, hc = ids.get(h, (None, None))
    ai, ac = ids.get(a, (None, None))
    return {"matchID": mid, "gamenumber": num, "eventID": ev, "flight": fl, "type": typ,
            "gameDate": date + "T00:00:00", "gameTime": time + ":00",
            "hometeamID": hi, "awayteamID": ai, "homeTeam": names.get(h, h), "awayTeam": names.get(a, a),
            "homeTeamClubID": hc, "awayTeamClubID": ac,
            "hometeamscore": int(hs) if hs != "" else None, "awayteamscore": int(as_) if as_ != "" else None,
            "complex": "Field", "venue": "1", "status": "On Time", "flagText": ""}


nw = [game(1000 + i, 4284, "ECNL", *r.split("|")[:4], *r.split("|")[4:], NW, NWN)
      for i, r in enumerate(nw_rows.splitlines())]
put("Event/get-schedules-by-flight/4284/40524/0", nw)
put("Event/get-event-schedule-or-standings/4284", {"boysDivAndFlightList": [
    {"divisionID": 22392, "divisionName": "BU16", "flightList": [{"flightID": 40524, "flightName": "ECNL"}]}],
    "girlsDivAndFlightList": []})
put("team/get-event-details-by-eventid/4284", {"eventName": "ECNL Boys Northwest 2026-27"})

# Southwest (partial, CDA Slammers' real games; other SW games invented to connect the table)
SW = {"CDA": (90001, 3360), "SDSC": (90002, 900), "WestCoast": (90003, 901), "LegendsDM": (90004, 902),
      "LVHeat": (90005, 903), "Breakers": (90006, 904), "Pateadores": (90007, 905), "Rebels": (90008, 906),
      "LAFC": (90009, 82)}
SWN = {k: k + " ECNL B2010/11" for k in SW}
SWN["CDA"] = "CDA Slammers FC ECNL B2010/11"; SWN["LAFC"] = "LAFC So Cal ECNL B2010/11"
sw_rows = """2026-09-13|10:00|CDA|SDSC|2|2
2026-09-19|10:00|WestCoast|CDA|0|2
2026-09-26|10:00|LegendsDM|CDA|1|5
2026-10-04|10:00|CDA|LVHeat|1|2
2026-10-17|10:00|SDSC|CDA|0|2
2026-10-18|10:00|Breakers|CDA|0|4
2026-10-24|10:00|CDA|Pateadores|1|1
2026-10-25|10:00|CDA|Rebels|2|1
2026-11-01|10:00|CDA|LegendsDM|5|1
2026-09-13|12:00|LAFC|LVHeat|3|0
2026-09-20|12:00|LAFC|Pateadores|2|1
2026-10-04|12:00|SDSC|LAFC|1|2
2026-10-18|12:00|LAFC|Rebels|1|1"""
sw = [game(2000 + i, 4287, "ECNL", *r.split("|")[:4], *r.split("|")[4:], SW, SWN)
      for i, r in enumerate(sw_rows.splitlines())]
put("Event/get-schedules-by-flight/4287/41625/0", sw)
put("Event/get-event-schedule-or-standings/4287", {"boysDivAndFlightList": [
    {"divisionID": 22211, "divisionName": "BU16", "flightList": [{"flightID": 41625, "flightName": "ECNL"}]}],
    "girlsDivAndFlightList": []})
put("team/get-event-details-by-eventid/4287", {"eventName": "ECNL Boys Southwest 2026-27"})

put("Event/get-org-club-list-by-orgID/12", [
    {"clubID": c, "eventID": 4284} for _, c in NW.values()] + [{"clubID": c, "eventID": 4287} for _, c in SW.values()])

# Phoenix bracket (real structure)
PX = dict(NW); PX.update(SW)
PX.update({"Dallas": (91001, 37), "Utah": (91002, 107), "PDX": (91003, 2536), "AFC": (91004, 3065), "Neb": (91005, 1726)})
PXN = dict(NWN); PXN.update(SWN)
PXN.update({"Dallas": "Dallas Texans Academy ECNL B2010/11", "Utah": "Utah Avalanche ECNL B2010/11",
            "PDX": "United PDX ECNL B2010/11", "AFC": "Association FC ECNL B10/11", "Neb": "Sporting Nebraska FC ECNL B2010/11"})
br = """1|2026-11-20|14:00|Utah|PDX
2|2026-11-20|16:00|AFC|Neb
3|2026-11-20|08:00|XF1|CDA
4|2026-11-20|08:00|Dallas|LAFC
5|2026-11-21|14:00|Winner Game 1|Winner Game 2
6|2026-11-21|14:00|Winner Game 3|Winner Game 4
7|2026-11-22|08:00|Winner Game 5|Winner Game 6
8|2026-11-22|08:00|Loser Game 5|Loser Game 6
9|2026-11-21|14:00|Loser Game 1|Loser Game 2
10|2026-11-21|14:00|Loser Game 3|Loser Game 4
11|2026-11-22|08:00|Winner Game 9|Winner Game 10
12|2026-11-22|08:00|Loser Game 9|Loser Game 10"""
px = []
for r in br.splitlines():
    n, d, t, h, a = r.split("|")
    px.append(game(1145548 + int(n), 4429, "Zoom", d, t, h, a, "", "", PX, PXN, typ="Bracket", num=int(n)))
put("Event/get-schedules-by-flight/4429/42012/0", px)
put("Event/get-event-schedule-or-standings/4429", {"boysDivAndFlightList": [
    {"divisionID": 22974, "divisionName": "BU16", "flightList": [{"flightID": 42012, "flightName": "Zoom"}]}],
    "girlsDivAndFlightList": []})
put("team/get-event-details-by-eventid/4429", {"eventName": "ECNL Phoenix"})

# Girls RL U13 (XF's 8 real results + Eastside's; remaining invented as unplayed)
GI = {"XF": (70001, 3476), "Snoh": (70002, 2522), "Whatcom": (70003, 1), "CWS": (70004, 4333), "Valor": (70005, 2),
      "Surf": (70006, 3), "PacNW": (70007, 2331), "Seattle": (70008, 1643), "3RSC": (70009, 2229),
      "Eastside": (70010, 398), "NWU": (70011, 4551), "WPFC": (70012, 112)}
GIN = {k: k + " ECNL RL G2013/14" for k in GI}
GIN["XF"] = "XF ECNL RL G2013/14"
g_rows = """2026-09-12|10:00|XF|Snoh|7|0
2026-09-19|10:00|Whatcom|XF|0|3
2026-09-20|10:00|CWS|XF|1|3
2026-09-26|10:00|XF|Valor|9|0
2026-10-03|10:00|Surf|XF|1|3
2026-10-17|10:00|XF|PacNW|2|1
2026-10-18|10:00|Seattle|XF|0|3
2026-10-25|10:00|3RSC|XF|1|2
2026-09-12|12:00|Valor|Eastside|0|2
2026-09-19|12:00|Eastside|PacNW|1|4
2026-09-20|12:00|NWU|Eastside|0|1
2026-09-26|12:00|Snoh|Eastside|3|0
2026-10-03|12:00|3RSC|Eastside|3|0
2026-10-18|12:00|WPFC|Eastside|3|0
2026-10-24|12:00|Eastside|Whatcom|1|2
2026-10-31|12:00|Eastside|Seattle|0|3
2026-11-07|09:00|Eastside|XF||
2026-11-14|13:30|WPFC|XF||
2026-11-14|11:00|CWS|Eastside||
2026-12-05|00:00|XF|Whatcom||"""
gi = [game(3000 + i, 4311, "ECNL Regional League", *r.split("|")[:4], *r.split("|")[4:], GI, GIN)
      for i, r in enumerate(g_rows.splitlines())]
put("Event/get-schedules-by-flight/4311/41483/0", gi)
put("Event/get-event-schedule-or-standings/4311", {"boysDivAndFlightList": [], "girlsDivAndFlightList": [
    {"divisionID": 22256, "divisionName": "GU13", "flightList": [{"flightID": 41483, "flightName": "ECNL Regional League"}]}]})
put("team/get-event-details-by-eventid/4311", {"eventName": "ECNL RL Girls Northwest 2026-27"})
put("Event/get-standings-by-div-and-flight/22392/40524/4284", [{"teamStandings": [
    {"teamID": 82130, "gp": 7, "wins": 6, "draws": 1, "losses": 0, "goalsfor": 24, "goalsagainst": 3,
     "standingpoints": 19, "ppg": 2.71}]}])
print("fixture written to", C)
