"""Source check: can we read a new schedule/standings source, and what does it look like?

Repeatable for any new league source (GotSport, Sports Affinity, a league site...). For each page it
  1. reads the site's robots.txt and checks our user agent may fetch that page (skips it if not),
  2. notes any Crawl-delay the site asks for (and waits at least that long between pages),
  3. saves the page so a reader can be written against the real HTML/JSON,
  4. writes data/probe/REPORT.md: allowed or not, status, size, content type, crawl delay, page title.

Run by the probe workflow (Actions > "Probe sample pages" or `gh workflow run probe.yml -f urls="..."`).
Arguments are full URLs or shorthands:
  gotsport:<event id>            event home, schedules list, teams list and clubs list for that event
  gotsport:<event id>/<group id> that event's schedule + standings for one group (age/division)
  sportsaffinity:<tournament guid>  Sports Affinity (WYS) accepted-teams list for that tournament
Saved files go to data/probe/ (public repo: only public pages, never anything behind a login)."""
import os, re, sys, time, urllib.request, urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import urlparse

UA = "xf-ecnl-standings/1.0"
MIN_DELAY = 10   # seconds between pages, at least (more if the site's Crawl-delay asks)
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "probe")
os.makedirs(OUT, exist_ok=True)


def expand(arg):
    """Shorthand -> list of URLs."""
    m = re.match(r"gotsport:(\d+)(?:/(\d+))?$", arg)
    if m:
        ev, grp = m.groups()
        base = f"https://system.gotsport.com/org_event/events/{ev}"
        if grp:
            return [f"{base}/schedules?group={grp}", f"{base}/results?group={grp}"]
        return [base, f"{base}/schedules", f"{base}/teams?showall=true", f"{base}/clubs"]
    m = re.match(r"sportsaffinity:([0-9A-Fa-f-]{36})$", arg)
    if m:
        return [f"https://wys.sportsaffinity.com/tour/public/info/accepted_list.asp?Tournamentguid={m.group(1)}"]
    return [arg]


def main(args):
    pages = [u for a in args for u in expand(a.strip()) if a.strip()]
    robots, delays, rows = {}, {}, []
    last = 0.0
    for i, url in enumerate(pages):
        p = urlparse(url)
        host = f"{p.scheme}://{p.netloc}"
        if host not in robots:
            rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
            try:
                req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": UA})
                txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
                open(os.path.join(OUT, p.netloc + "_robots.txt"), "w").write(txt)
                rp.parse(txt.splitlines())
            except Exception as e:   # no robots.txt (404) = no rules; anything else = be careful, treat as unknown
                print("robots fetch failed", host, e)
                rp = None
            robots[host] = rp
            delays[host] = max(MIN_DELAY, int((rp and rp.crawl_delay(UA)) or 0))
        rp = robots[host]
        if rp is not None and not rp.can_fetch(UA, url):
            print("DISALLOWED by robots.txt:", url)
            rows.append((url, "NO (robots.txt)", "", "", "", ""))
            continue
        wait = delays[host] - (time.time() - last)
        if last and wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            r = urllib.request.urlopen(req, timeout=60)
            body = r.read().decode("utf-8", "ignore")
            last = time.time()
            ctype = r.headers.get("Content-Type", "")
            ext = "json" if "json" in ctype else "html"
            fn = f"{i:02d}_{p.netloc}.{ext}"
            open(os.path.join(OUT, fn), "w").write((f"<!-- {url} -->\n" if ext == "html" else "") + body)
            title = (re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I) or [None, ""])[1].strip()[:80]
            print("saved", url, len(body))
            rows.append((url, "yes" if rp is not None else "yes (no robots.txt)", r.status, f"{len(body) // 1024} KB",
                         ctype.split(";")[0], f"{fn} · {title}"))
        except Exception as e:
            last = time.time()
            print("failed", url, e)
            rows.append((url, "yes", f"failed: {e}", "", "", ""))
    with open(os.path.join(OUT, "REPORT.md"), "w") as f:
        f.write(f"# Source check {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n\n")
        f.write("Crawl delay used per site: " + ", ".join(f"{h} {d}s" for h, d in delays.items()) + "\n\n")
        f.write("| Page | Allowed | Status | Size | Type | Saved as · title |\n|---|---|---|---|---|---|\n")
        for row in rows:
            f.write("| " + " | ".join(str(x).replace("|", "/") for x in row) + " |\n")
    print(open(os.path.join(OUT, "REPORT.md")).read())


if __name__ == "__main__":
    main(sys.argv[1:])
