"""RCL (Washington Youth Soccer, Sports Affinity) count check - report only.

Fetches ONE public page: the 2026-27 RCL accepted-teams list linked from washingtonyouthsoccer.org
("26-27 schedules, results & standings"), and counts the divisions (flights) it links to. That count is
how many pages a full data pull would read. Nothing is saved to the repo; the report goes to the run
summary. Per Graham's decision (Nov 23): polite (one request, identified user agent); if the site says
no (403/429 or a block page), stop and report it.
"""
import re, sys, urllib.request, html, collections

URL = "https://wys.sportsaffinity.com/tour/public/info/accepted_list.asp?Tournamentguid=6DBB3AF6-DEC3-4341-8D25-2DC23F01177B"
UA = "SidelineStandings/1.0 (+https://sidelinestandings.com; free schedules app for parents)"

def main():
    out = []
    try:
        r = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=60)
        status, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, ""
    except Exception as e:
        print(f"## RCL count\n\nCouldn't reach the page: {e}"); return
    out.append(f"## RCL count (report only)\n\nPage: {URL}\n\nHTTP {status}, {len(body) // 1024} KB")
    if status != 200 or not body:
        out.append("\n**The site said no or sent nothing. Stop here and talk options.**"); print("\n".join(out)); return
    links = re.findall(r'<a[^>]+href="([^"]*schedule_results2\.asp[^"]*)"[^>]*>(.*?)</a>', body, re.I | re.S)
    flights = collections.OrderedDict()
    for href, text in links:
        m = re.search(r"flightguid=([0-9A-Fa-f-]{36})", href, re.I)
        if m: flights.setdefault(m.group(1).upper(), re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", text))).strip())
    teams = len(re.findall(r"<tr", body, re.I))
    out.append(f"\nDivisions (flights) linked: **{len(flights)}**  ·  table rows on the page: {teams}")
    out.append(f"\nA full pull = 1 list page + {len(flights)} division pages = **{len(flights) + 1} requests**.")
    if not flights:
        out.append("\nNo division links found. First 600 characters of the page text:\n\n```\n" + re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", body))[:600] + "\n```")
    else:
        out.append("\n| # | Division |\n|---|---|")
        for i, (g, name) in enumerate(flights.items(), 1): out.append(f"| {i} | {name or '(no name)'} |")
    print("\n".join(out))

if __name__ == "__main__":
    main()
