"""Girls Academy check (report only): what GA has published on AthleteOne right now.

Events: 4486 Girls Academy 2026/27 (league), 4472 GA Winter Showcase & Champions Cup,
4473 Aspire West Showcase, 4504 Aspire Winter Showcase 2027. Same public source and client as the
daily data run (scripts/ecnl_api.py). Prints divisions, flights, team counts and games per flight.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import ecnl_api as api

EVENTS = [(4486, "Girls Academy 2026/27"), (4472, "GA Winter Showcase & Champions Cup"), (4473, "Aspire West Showcase"), (4504, "Aspire Winter Showcase 2027")]
out = ["## Girls Academy check (report only)\n"]
for ev, name in EVENTS:
    d = api.get(f"Event/get-event-schedule-or-standings/{ev}", cache=False) or {}
    divs = (d.get("girlsDivAndFlightList") or []) + (d.get("boysDivAndFlightList") or [])
    out.append(f"### {ev} {name}: {len(divs)} divisions\n")
    out.append("| Division | Flight | Teams | Schedule? | Games | With score |\n|---|---|---|---|---|---|")
    for dv in divs:
        fl = dv.get("flightList") or []
        if not fl:
            out.append(f"| {dv.get('divisionName')} | (no flights yet) | | | | |")
        for f in fl:
            games = scored = 0
            if f.get("hasActiveSchedule") or f.get("teamsCount"):
                s = api.get(f"Event/get-schedules-by-flight/{ev}/{f.get('flightID')}/0", cache=False)
                rows = s if isinstance(s, list) else (s or {}).get("eventSchedule") or (s or {}).get("schedules") or []
                if isinstance(rows, list):
                    games = len(rows)
                    scored = sum(1 for g in rows if isinstance(g, dict) and g.get("homeTeamScore") not in (None, ""))
            out.append(f"| {dv.get('divisionName')} | {f.get('flightName')} | {f.get('teamsCount')} | {'yes' if f.get('hasActiveSchedule') else 'no'} | {games} | {scored} |")
    out.append("")
print("\n".join(out))
