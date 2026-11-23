"""GotSport check (report only): can we read the Girls Academy 2026/27 league schedule page?

ONE request to the public page linked from girlsacademyleague.com ("League Schedule"), identified as
Sideline Standings. Counts the age-group/division schedule links, i.e. how many pages a full pull
would read. Nothing is saved to the repo; the report goes to the run summary. Per Graham's decision
(Nov 23): if the site says no (403/429 or a block page), stop and report it.
"""
import re, html, collections, urllib.request, urllib.error

URL = "https://system.gotsport.com/org_event/events/56497"
UA = "SidelineStandings/1.0 (+https://sidelinestandings.com; free schedules app for parents)"

out = ["## GotSport check: Girls Academy 2026/27 (report only)\n", f"Page: {URL}\n"]
try:
    r = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=60)
    status, body = r.status, r.read().decode("utf-8", "replace")
except urllib.error.HTTPError as e:
    status, body = e.code, ""
except Exception as e:
    status, body = None, ""; out.append(f"Couldn't reach it: {e}")
out.append(f"HTTP {status}, {len(body) // 1024} KB")
title = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
if title: out.append(f"\nTitle: {html.unescape(title.group(1)).strip()}")
m = re.search(r"access denied|attention required|cf-chl|are you a robot|verify you are human", body, re.I)
for w in re.finditer(r"captcha", body, re.I):   # a captcha script on a normal page isn't a block; show where it is
    out.append("\ncaptcha mention: `" + re.sub(r"\s+", " ", body[max(0, w.start() - 80):w.end() + 40]).replace("`", "'") + "`"); break
if status != 200 or not body or m:
    if m: out.append("\nBlock text: `" + body[max(0, m.start() - 80):m.end() + 40].replace("`", "'") + "`")
    out.append("\n**The site said no or sent a block page. Stop here and talk options.**")
else:
    links = re.findall(r'href="([^"]*/org_event/events/56497/schedules\?[^"]*)"[^>]*>(.*?)</a>', body, re.I | re.S)
    groups = collections.OrderedDict()
    for href, text in links:
        g = re.search(r"group=(\d+)", href)
        if g: groups.setdefault(g.group(1), re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", text))).strip())
    out.append(f"\nSchedule groups linked: **{len(groups)}**. A full pull = 1 + {len(groups)} = **{len(groups) + 1} requests**.")
    if groups:
        out.append("\n| # | Group |\n|---|---|")
        for i, (g, n) in enumerate(groups.items(), 1): out.append(f"| {i} | {n or g} |")
    else:
        out.append("\nNo schedule links found. Page text start:\n\n```\n" + re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", body))[:800] + "\n```")
print("\n".join(out))
