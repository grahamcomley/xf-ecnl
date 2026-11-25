import importlib.util, json, os, sys, tempfile
from datetime import datetime, timedelta, timezone, date
spec = importlib.util.spec_from_file_location("alerts", "/home/claude/xf-ecnl/scripts/alerts.py")
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
tmp = tempfile.mkdtemp(); A.OUT = tmp
R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)
today = date(2026, 12, 1)
def game(i, d, t, v, h=1, a=2, **kw): return dict({"id": i, "date": d, "time": t, "venue": v, "home_id": h, "away_id": a, "home": "XF 1", "away": "Barca", "tz": "America/Phoenix"}, **kw)
def confs(games): return {"u16b-1-1": {"pool_key": "u16b", "key": "u16b-1-1", "conf_name": "ECNL Boys Southwest", "teams": [{"id": 1, "short": "XF 1 U16"}, {"id": 2, "short": "Barca"}, {"id": 3, "short": "Seattle United"}], "games": games}}
def status(mode): json.dump({"checked": "x", "mode": mode}, open(os.path.join(tmp, "status.json"), "w"))
t0 = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)
G = {
 "A": game(101, "2026-12-06", "08:00", "Field 4"),            # time change, confirmed
 "B": game(102, "2026-12-06", "10:00", "Field 1", 1, 3),      # glitch, reverts
 "C": game(103, "2026-12-07", "", "Field 2"),                  # TBD -> first time
 "D": game(104, "2026-12-07", "12:00", "Field 3", 1, None),    # opponent filled later
 "E": game(105, "2026-12-08", "09:00", "Field 5"),             # removed
 "F": game(106, "2026-12-09", "11:00", "Field 6"),             # field change, confirmed
 "G": game(107, "2027-01-10", "11:00", "Field 7"),             # far ahead: date moves, still > 14 days
 "H": game(108, "2026-12-10", "11:00", "Field 8"),             # date change
}
def run(gs, mins, mode="full"):
    status(mode)
    return A.schedule_changes(confs(list(gs)), t0 + timedelta(minutes=mins), today)
r1 = run(G.values(), 0)
ok("first run: nothing", r1 == [], r1)
G2 = dict(G); G2["A"] = dict(G["A"], time="09:30"); G2["B"] = dict(G["B"], time="11:00"); G2["C"] = dict(G["C"], time="10:00")
G2["D"] = dict(G["D"], away_id=2); del G2["E"]; G2["F"] = dict(G["F"], venue="Reach 11 Field 2"); G2["G"] = dict(G["G"], date="2027-01-12"); G2["H"] = dict(G["H"], date="2026-12-11")
r2 = run(G2.values(), 15)
ok("second run (15 min later): nothing yet, all pending", r2 == [], r2)
G3 = dict(G2); G3["B"] = dict(G["B"])   # glitch reverted
r3q = run(G3.values(), 30, "quick")
ok("quick run, games not today/tomorrow: not confirmed yet", r3q == [], r3q)
r3 = run(G3.values(), 45)
got = {c["g"]: c for c in r3}
ok("time change confirmed (A)", "101" in got and got["101"]["f"] == ["t"] and got["101"]["ot"] == "08:00" and got["101"]["t"] == "09:30", got.get("101"))
ok("glitch that reverted: no alert (B)", "102" not in got)
ok("TBD -> first time: no alert (C)", "103" not in got)
ok("opponent filled in: no alert (D)", "104" not in got)
ok("removed game: no alert (E)", "105" not in got)
ok("field change confirmed (F)", "106" in got and got["106"]["f"] == ["v"] and got["106"]["ov"] == "Field 6", got.get("106"))
ok("far-ahead date move: no alert (G)", "107" not in got)
ok("date change confirmed (H)", "108" in got and got["108"]["f"] == ["d"] and got["108"]["od"] == "2026-12-10", got.get("108"))
ok("names and teams carried", got["101"]["hn"] == "XF 1 U16" and got["101"]["h"] == "u16b-1" and got["101"]["tz"] == "America/Phoenix")
st = json.load(open(os.path.join(tmp, "status.json")))
ok("status.json has the tags", set(st.get("chg", {})) == {"101", "106", "108"}, st.get("chg"))
r4 = run(G3.values(), 60)
ok("next run: no repeat alerts", r4 == [], r4)
G5 = dict(G3); G5["A"] = dict(G3["A"], time="10:00", date="2026-12-02")
r5a = run(G5.values(), 80, "quick")
r5b = run(G5.values(), 105, "quick")
ok("game tomorrow: confirmed on a quick run", [c["g"] for c in r5b] == ["101"] and set(r5b[0]["f"]) == {"d", "t"}, r5b)
st = json.load(open(os.path.join(tmp, "status.json")))
r6 = A.schedule_changes(confs(list(G5.values())), t0 + timedelta(days=8), today)
st = json.load(open(os.path.join(tmp, "status.json")))
ok("tags drop after 7 days", "106" not in st.get("chg", {}), st.get("chg"))
print(f"{sum(R)}/{len(R)} passed")
