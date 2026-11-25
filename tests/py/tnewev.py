import importlib.util, json, os, copy, tempfile, glob
from datetime import datetime, timedelta, timezone, date
spec = importlib.util.spec_from_file_location("alerts", "/home/claude/xf-ecnl/scripts/alerts.py")
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
tmp = tempfile.mkdtemp(); A.OUT = tmp
json.dump({"checked": "x", "mode": "full"}, open(os.path.join(tmp, "status.json"), "w"))
R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)
confs = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob("/tmp/xfo/site/data/conf/u17b-*.json")}
confs.update({os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob("/tmp/xfo/site/data/conf/u16b-*.json")})
today = date(2026, 11, 10)
# pick a team with an upcoming event that has real games
target = None
for cf, D in confs.items():
    for tid, idxs in (D.get("team_events") or {}).items():
        for i in idxs:
            ev = D["events"][i]
            ds = sorted(g["date"] for g in ev["games"])
            if ds and "2026-11-10" <= ds[0] <= "2026-12-08" and not ev.get("competition") and any(str(g.get("home_id")) == tid and g.get("away_id") and g.get("time") for g in ev["games"]):
                target = (cf, tid, i, ev["event_id"]); break
        if target: break
    if target: break
print("target", target)
cf, tid, idx, evid = target
hidden = copy.deepcopy(confs); hidden[cf]["team_events"][tid] = [i for i in hidden[cf]["team_events"][tid] if i != idx]
t0 = datetime(2026, 11, 10, 18, tzinfo=timezone.utc)
r1 = A.new_event_schedules(hidden, t0, today)
ok("first run: baseline, nothing", r1 == [], len(r1))
r2 = A.new_event_schedules(hidden, t0 + timedelta(minutes=15), today)
ok("nothing new: nothing", r2 == [], r2)
r3 = A.new_event_schedules(confs, t0 + timedelta(minutes=30), today)
ok("newly posted: pending, not sent yet", r3 == [], r3)
r4 = A.new_event_schedules(confs, t0 + timedelta(minutes=55), today)
mine = [x for x in r4 if x["k"].endswith("-" + tid) and x["ev"] == evid]
ok("confirmed on the next run", len(mine) == 1, r4)
if mine:
    m = mine[0]; print("item", json.dumps(m)[:400])
    ok("item has games with opponent/time", m["g"] and all(g["o"] and g["t"] for g in m["g"]), m["g"])
st = json.load(open(os.path.join(tmp, "status.json")))
ok("status.json evnew tag", str(evid) in st.get("evnew", {}), st.get("evnew"))
r5 = A.new_event_schedules(confs, t0 + timedelta(minutes=80), today)
ok("never repeats", r5 == [], r5)
# posted then pulled
idx2 = None
for cf2, D in confs.items():
    for tid2, idxs in (D.get("team_events") or {}).items():
        if (cf2, tid2) != (cf, tid) and idxs:
            idx2 = (cf2, tid2, idxs[0]); break
    if idx2: break
cf2, tid2, i2 = idx2
h2 = copy.deepcopy(confs); h2[cf2]["team_events"][tid2] = []
A.new_event_schedules(h2, t0 + timedelta(minutes=100), today)   # forget? no: already seen at baseline
ok("already-known schedules don't re-alert after a blip", A.new_event_schedules(confs, t0 + timedelta(minutes=130), today) == [])
# blip of a NEW one: appears once, disappears before confirm
tmp2 = tempfile.mkdtemp(); A.OUT = tmp2; json.dump({"mode": "full"}, open(os.path.join(tmp2, "status.json"), "w"))
A.new_event_schedules(hidden, t0, today)
A.new_event_schedules(confs, t0 + timedelta(minutes=30), today)
A.new_event_schedules(hidden, t0 + timedelta(minutes=55), today)
ok("posted then pulled before confirm: no alert", [x for x in A.new_event_schedules(hidden, t0 + timedelta(minutes=80), today) if x["ev"] == evid] == [])
far = A.new_event_schedules(confs, t0, date(2026, 9, 1))
ok("events > 28 days away ignored", far == [])
print(f"{sum(R)}/{len(R)} passed")
