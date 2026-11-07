"""Surf Sports events (Surf Cup, Surf College Cup, Surf Challenge, ...) from
somsports.athletes2events.com. Its robots.txt allows these pages; we read one
page every 10 seconds and cache finished events forever.

Surf events use the new school-year age groups (e.g. Boys-U16 = born Aug 2010 -
Jul 2011), so their summer games count as the new age group.
"""
import html as H
import json
import os
import re
import sys
import time
import urllib.request
import urllib.robotparser
from datetime import date, datetime

BASE = "https://somsports.athletes2events.com"
UA = "xf-ecnl-standings/1.0"
ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE = os.path.join(ROOT, "data", "cache", "surf")
DELAY = 10
_last = [0.0]
_rp = []
stats = {"live": 0, "cached": 0, "failed": 0}


def _allowed(url):
    if not _rp:
        rp = urllib.robotparser.RobotFileParser(BASE + "/robots.txt")
        try:
            req = urllib.request.Request(BASE + "/robots.txt", headers={"User-Agent": UA})
            rp.parse(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore").splitlines())
        except Exception:
            rp = None
        _rp.append(rp)
    return _rp[0] is None or _rp[0].can_fetch(UA, url)


def fetch(path, permanent=False, max_age_hours=6):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") + ".html")
    if os.path.exists(fn):
        age = (time.time() - os.path.getmtime(fn)) / 3600
        if permanent or age < max_age_hours or "--offline" in sys.argv:
            stats["cached"] += 1
            return open(fn, encoding="utf-8").read()
    if "--offline" in sys.argv:
        return None
    url = BASE + path
    if not _allowed(url):
        print("  surf: robots.txt disallows", url)
        return None
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
    except Exception as e:
        print("  surf: failed", url, e)
        stats["failed"] += 1
        return open(fn, encoding="utf-8").read() if os.path.exists(fn) else None
    stats["live"] += 1
    open(fn, "w", encoding="utf-8").write(html)
    return html


def _txt(s):
    return H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def events():
    """[(event_id, name)] from the home page."""
    h = fetch("/", max_age_hours=24) or ""
    out = []
    for m in re.finditer(r'/events/(\d+)/details">\s*<h3[^>]*>(.*?)</h3>', h, re.S):
        out.append((int(m.group(1)), _txt(m.group(2))))
    return out


def event_dates(eid):
    h = fetch(f"/events/{eid}/details", max_age_hours=24) or ""
    m = re.search(r"From\s+([A-Z][a-z]{2} \d{1,2}, \d{4})\s+to\s+([A-Z][a-z]{2} \d{1,2}, \d{4})", _txt(h))
    if not m:
        return None, None
    f = lambda s: datetime.strptime(s, "%b %d, %Y").date().isoformat()
    return f(m.group(1)), f(m.group(2))


def flights(eid, division, permanent):
    """Flight ids for a division name like 'Boys-U16'."""
    h = fetch(f"/events/{eid}/groups", permanent=permanent, max_age_hours=12) or ""
    out = []
    for block in re.split(r'<table[^>]*clean-table-box[^>]*>', h)[1:]:
        head = re.search(r'class="col-age">(.*?)</th>', block, re.S)
        if head and _txt(head.group(1)).split(" ")[0].strip() == division:
            out += [int(x) for x in re.findall(r"schedules\?flight-id=(\d+)", block)]
    return sorted(set(out))


def flight_games(eid, fid, permanent):
    h = fetch(f"/events/{eid}/schedules?flight-id={fid}", permanent=permanent, max_age_hours=3) or ""
    tables = [h[i:h.find("</table>", i)] for i in [m.start() for m in re.finditer("matches-table", h)]]
    games, day = [], None
    rows = [r for t in tables for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)]
    for row in rows:
        th = re.search(r'<th colspan="\d+">(.*?)</th>', row, re.S)
        if th:
            try:
                day = datetime.strptime(_txt(th.group(1)), "%a %b %d, %Y").date().isoformat()
            except ValueError:
                pass
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(tds) < 7 or not day:
            continue
        num = _txt(tds[0]).lstrip("#")
        ht = re.search(r"team-id=(\d+)\">(.*?)</a>", tds[4], re.S)
        at = re.search(r"team-id=(\d+)\">(.*?)</a>", tds[6], re.S)
        if not (ht and at):
            continue
        sc = re.match(r"\s*(\d+)\s*-\s*(\d+)", _txt(tds[5]))
        tm = _txt(tds[3])
        try:
            t24 = datetime.strptime(tm, "%I:%M %p").strftime("%H:%M")
        except ValueError:
            t24 = ""
        games.append({
            "id": f"surf-{eid}-{num}", "num": int(num) if num.isdigit() else None, "event_id": f"surf{eid}",
            "flight": _txt(tds[1]), "type": "Surf", "date": day, "time": t24,
            "home_id": f"s{ht.group(1)}", "away_id": f"s{at.group(1)}",
            "home": _txt(ht.group(2)), "away": _txt(at.group(2)), "home_club": None, "away_club": None,
            "hs": int(sc.group(1)) if sc else None, "as": int(sc.group(2)) if sc else None,
            "hpk": None, "apk": None, "venue": _txt(tds[8]) if len(tds) > 8 else "",
            "status": "", "bad": False, "conf": "event", "neutral": True, "weight_mult": 1.0,
            "source": "current",
        })
    return games


def pool_games(division, since):
    """All games for a Surf division (e.g. 'Boys-U16') in events starting on/after `since`."""
    today = date.today().isoformat()
    out = []
    for eid, name in events():
        start, end = event_dates(eid)
        if not start or start < since:
            continue
        done = end < today
        for fid in flights(eid, division, done):
            for g in flight_games(eid, fid, done):
                g["event_name"] = name
                out.append(g)
    print(f"  surf {division}: {len(out)} games, requests {stats}")
    return out
