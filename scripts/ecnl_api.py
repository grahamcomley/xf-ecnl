"""Small client for the public AthleteOne / TGS API that powers theecnl.com.

The API is undocumented, so every call is defensive: retries, a polite delay,
and an on-disk cache so a broken upstream never blanks the site.
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.athleteone.com/api/"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
DELAY = 0.4  # seconds between live requests
_last = [0.0]
stats = {"live": 0, "cached": 0, "failed": 0}


def _cache_path(path):
    safe = path.strip("/").replace("/", "__")
    return os.path.join(CACHE_DIR, safe + ".json")


def get(path, max_age_hours=0.0, permanent=False, cache=True):
    """GET an API path. Returns the `data` field, or None.

    permanent=True: use the cache forever once fetched (past seasons).
    max_age_hours: reuse a cached copy younger than this.
    On failure, falls back to any cached copy.
    """
    cp = _cache_path(path)
    if cache and os.path.exists(cp):
        age_h = (time.time() - os.path.getmtime(cp)) / 3600
        if permanent or age_h < max_age_hours:
            stats["cached"] += 1
            with open(cp) as f:
                return json.load(f)
    data = None
    for attempt in range(3):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(
                BASE + path,
                headers={"User-Agent": "xf-ecnl-standings/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode("utf-8"))
            if isinstance(body, dict) and "data" in body:
                data = body["data"]
            else:
                data = body
            break
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"  ! {path} attempt {attempt + 1}: {e}")
            time.sleep(2 * (attempt + 1))
    if data is None:
        stats["failed"] += 1
        if cache and os.path.exists(cp):
            with open(cp) as f:
                return json.load(f)
        return None
    stats["live"] += 1
    if not cache:
        return data
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cp, "w") as f:
        json.dump(data, f)
    return data


# --- endpoint helpers -------------------------------------------------------

def org_clubs(org_id):
    return get(f"Event/get-org-club-list-by-orgID/{org_id}", max_age_hours=24) or []


def event_divisions(event_id, permanent=False):
    """Returns list of {divisionID, divisionName, flightList:[...]} for boys+girls."""
    d = get(f"Event/get-event-schedule-or-standings/{event_id}", max_age_hours=24, permanent=permanent)
    if not d:
        return []
    out = []
    for key in ("boysDivAndFlightList", "girlsDivAndFlightList"):
        out.extend(d.get(key) or [])
    return out


def flight_schedule(event_id, flight_id, permanent=False):
    return get(f"Event/get-schedules-by-flight/{event_id}/{flight_id}/0", permanent=permanent) or []


def flight_standings(event_id, division_id, flight_id):
    d = get(f"Event/get-standings-by-div-and-flight/{division_id}/{flight_id}/{event_id}")
    rows = []
    if isinstance(d, list):
        for block in d:
            if isinstance(block, dict):
                rows.extend(block.get("teamStandings") or [])
    return rows
