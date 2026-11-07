"""One-time probe: honours each site's robots.txt, then saves a few sample pages
so the parsers can be written against the real HTML. Run by probe.yml."""
import os, sys, time, urllib.request, urllib.robotparser
from urllib.parse import urlparse

UA = "xf-ecnl-standings/1.0"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "probe")
os.makedirs(OUT, exist_ok=True)
PAGES = [l.strip() for l in sys.argv[1:] if l.strip()]
robots = {}
for i, url in enumerate(PAGES):
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
        try:
            req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": UA})
            txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
            open(os.path.join(OUT, urlparse(url).netloc + "_robots.txt"), "w").write(txt)
            rp.parse(txt.splitlines())
        except Exception as e:
            print("robots fetch failed", host, e); rp = None
        robots[host] = rp
    rp = robots[host]
    if rp is not None and not rp.can_fetch(UA, url):
        print("DISALLOWED by robots.txt:", url); continue
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        fn = f"{i:02d}_{urlparse(url).netloc}.html"
        open(os.path.join(OUT, fn), "w").write(f"<!-- {url} -->\n" + html)
        print("saved", url, len(html))
    except Exception as e:
        print("failed", url, e)
    time.sleep(10)
