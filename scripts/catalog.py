"""Catalog of every event on the AthleteOne platform this season (ECNL Boys and
Girls, both Regional Leagues, Pre-ECNL, and outside tournaments that use it),
plus the age-group rules that decide which divisions belong in a pool.

The catalog is built once by scanning event IDs, saved to
data/current_catalog.json, and then only new IDs are checked on later runs.
"""
import json
import os
import re
import sys
from datetime import date

import ecnl_api as api

ROOT = os.path.join(os.path.dirname(__file__), "..")
PATH = os.path.join(ROOT, "data", "current_catalog.json")


def _details(ev):
    d = api.get(f"team/get-event-details-by-eventid/{ev}", cache=False)
    if isinstance(d, list) and d:
        d = d[0]
    if isinstance(d, dict) and d.get("name"):
        return {"event_id": ev, "name": d.get("name"), "org_id": d.get("orgID"),
                "org_season_id": d.get("orgSeasonID"), "gender": d.get("orgGender") or d.get("gender"),
                "start": (d.get("startDate") or "")[:10], "end": (d.get("endDate") or "")[:10]}
    return None


_CACHE = {}


def current_catalog(start_id=4240, tail=40):
    """All events from start_id up. Each run re-checks the `tail` IDs just past the
    highest real event found, so newly created events are always picked up."""
    if "events" in _CACHE:
        return _CACHE["events"]
    cat = {"events": []}
    if os.path.exists(PATH):
        with open(PATH) as f:
            cat = json.load(f)
    if "--offline" in sys.argv:
        _CACHE["events"] = cat["events"]
        return cat["events"]
    known = {e["event_id"] for e in cat["events"]}
    ev = (max(known) + 1) if known else start_id
    misses, new = 0, 0
    while misses < tail and ev < start_id + 5000:
        if ev not in known:
            d = _details(ev)
            if d:
                cat["events"].append(d)
                known.add(ev)
                new += 1
                misses = 0
            else:
                misses += 1
        ev += 1
    cat["events"].sort(key=lambda e: e["event_id"])
    cat.pop("max_probed", None)
    with open(PATH, "w") as f:
        json.dump(cat, f, indent=1)
    print(f"  catalog: {len(cat['events'])} events ({new} new), highest {max(known) if known else '-'}")
    _CACHE["events"] = cat["events"]
    return cat["events"]


def is_league(e):
    """Season-long competitions (conferences/leagues) vs. weekend events."""
    try:
        a, b = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
        return (b - a).days > 45
    except ValueError:
        return False


def div_gender(name, event_gender=None):
    n = (name or "").upper()
    if re.search(r"\bGIRLS?\b|\bGU-?\d|\bG\d{2}|\bU-?\d{1,2}\s?G\b|\bG20\d\d", n):
        return "G"
    if re.search(r"\bBOYS?\b|\bBU-?\d|\bB\d{2}|\bU-?\d{1,2}\s?B\b|\bB20\d\d", n):
        return "B"
    eg = (event_gender or "").lower()
    return "B" if eg in ("m", "male", "b") else "G" if eg in ("f", "female", "g") else None


def division_matches(div_name, event, rules):
    """Age rules (2026-27 school-year change):
       - from `new_age_from` (Aug 1): new age label (U16) or explicit years (2010/11) count;
       - from `since` (Jun 1) until then: only explicit new-group years (2010/11) count;
       - earlier games are handled as last-season history elsewhere."""
    if div_gender(div_name, event.get("gender")) != rules["gender"]:
        return False
    start = event.get("start") or ""
    if start < rules["since"]:
        return False
    n = (div_name or "").upper().replace(" ", "")
    explicit = any(tok.upper().replace(" ", "") in n for tok in rules["explicit"])
    if explicit:
        return True
    if start >= rules["new_age_from"]:
        age = rules["age"]
        return bool(re.search(rf"(?<!\d)U-?{age}(?!\d)", n))
    return False
