"""Event check (report only): what an AthleteOne event has published right now.

Usage: python scripts/event_check.py <event id> [<event id> ...]
Prints each division and flight: team count, whether a schedule is published, games, the teams named in
those games, and the flight's standings teams. Same public source and client as the daily data run.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import ecnl_api as api

out = ["## Event check (report only)\n"]
for ev in [a for a in sys.argv[1:] if a.isdigit()]:
    det = api.get(f"team/get-event-details-by-eventid/{ev}", cache=False)
    det = det[0] if isinstance(det, list) and det else det or {}
    d = api.get(f"Event/get-event-schedule-or-standings/{ev}", cache=False) or {}
    divs = (d.get("boysDivAndFlightList") or []) + (d.get("girlsDivAndFlightList") or [])
    out.append(f"### {ev} {det.get('name', '')} ({(det.get('startDate') or '')[:10]} to {(det.get('endDate') or '')[:10]}): {len(divs)} divisions\n")
    for dv in divs:
        for f in dv.get("flightList") or []:
            fid = f.get("flightID")
            s = api.get(f"Event/get-schedules-by-flight/{ev}/{fid}/0", cache=False)
            rows = s if isinstance(s, list) else []
            names = sorted({str(g.get(k) or "").strip() for g in rows if isinstance(g, dict) for k in ("homeTeam", "awayTeam", "homeTeamName", "awayTeamName") if g.get(k)})
            st = api.get(f"Event/get-standings-by-div-and-flight/{dv.get('divisionID')}/{fid}/{ev}", cache=False)
            st_rows = st if isinstance(st, list) else (st or {}).get("standings") or []
            st_names = sorted({str(r.get("teamName") or r.get("name") or r.get("team") or "").strip() for r in st_rows if isinstance(r, dict)} - {""})
            out.append(f"- **{dv.get('divisionName')} · {f.get('flightName')}** (flight {fid}): teams {f.get('teamsCount')}, schedule {'yes' if f.get('hasActiveSchedule') else 'no'}, games {len(rows)}")
            if names: out.append("  - in games: " + "; ".join(names[:20]))
            if st_names: out.append("  - standings: " + "; ".join(st_names[:20]))
            if os.environ.get("SHOW_GAMES") and str(fid) in os.environ["SHOW_GAMES"].split() and rows:
                out.append("  - full first game: " + json.dumps(rows[0], default=str)[:1500])
            if os.environ.get("SHOW_GAMES") and str(fid) in os.environ["SHOW_GAMES"].split():
                for g in rows:
                    out.append(f"  - #{g.get('gamenumber')} {str(g.get('gameDate'))[:10]} {g.get('gameTime') or g.get('gameTimeText') or ''} | {g.get('homeTeam') or '(blank)'} [{g.get('hometeamID')}] vs {g.get('awayTeam') or '(blank)'} [{g.get('awayteamID')}] | {g.get('complex') or ''} {g.get('venue') or ''} | flag {g.get('flagText') or ''}")
    out.append("")
print("\n".join(out))
