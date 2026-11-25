import asyncio, datetime, json
from playwright.async_api import async_playwright
U = "http://localhost:8767/"
R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)
NOW = datetime.datetime(2026, 11, 18, 18, tzinfo=datetime.timezone.utc)
AT = int(NOW.timestamp()*1000) - 20*60e3
conf = json.load(open("/tmp/xfo/site/data/conf/u17b-4284-40525.json"))
for e in conf.get("events", []):
  for g in e.get("games", []): g["zip"] = "85001"
for g in conf["games"]: g["zip"] = "98012"
WXR = {"attr": {"dark": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='14'/%3E", "legal": "https://example.com/legal"},
       "z": {"85001": {"at": AT, "tz": "America/Phoenix", "d": {"2026-11-20": [81, 60, 10, "Clear"], "2026-11-21": [70, 52, 60, "Rain"], "2026-11-22": [68, 50, 20, "PartlyCloudy"]},
                        "h": {"2026-11-20T08": [64, 62, 5, 6, 200, "MostlyClear"]}}}}
STATE = {"wx": WXR}
async def main():
  async with async_playwright() as p:
    b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    ctx = await b.new_context(viewport={"width": 400, "height": 900}, service_workers="block", timezone_id="America/Los_Angeles"); pg = await ctx.new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.clock.install(time=NOW)
    await pg.route("**/data/conf/u17b-4284-40525.json", lambda r: r.fulfill(status=200, body=json.dumps(conf), content_type="application/json"))
    async def api(r):
      u = r.request.url
      if "/api/wx" in u: STATE.setdefault("calls", []).append(u); return await r.fulfill(status=200, body=json.dumps(STATE["wx"]), content_type="application/json")
      if "/api/config" in u: return await r.fulfill(status=200, body='{"gate":false}', content_type="application/json")
      return await r.fulfill(status=401, body="{}", content_type="application/json")
    await pg.route("**/api/**", api)
    await pg.goto(U)
    await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('xfFavs',JSON.stringify(['u17b-131393']));localStorage.setItem('lastTeam','u17b-131393')}")
    await pg.goto(U + "#t=u17b-131393"); await pg.reload(); await pg.wait_for_timeout(3500)
    ok("fetched /api/wx with the field ZIPs", any("z=" in c and "85001" in c for c in STATE.get("calls", [])), STATE.get("calls"))
    rows = await pg.evaluate("""()=>Object.fromEntries(['1146430','1146518','1146612'].map(id=>[id,[...document.querySelectorAll(`.grow[data-gid='${id}'] .gsub`)].map(e=>e.textContent).join(' | ')]))""")
    print(rows)
    print(await pg.evaluate("()=>{const D=CONF_CACHE['u17b-4284-40525'];const g=D.events.flatMap(e=>e.games).find(g=>g.id==1146430);return JSON.stringify({wx:Object.keys(WX),g:{zip:g.zip,date:g.date,time:g.time,tz:g.tz},f:wxFor(g),n:document.querySelectorAll('.grow[data-gid=\"1146430\"]').length, html:(document.querySelector('.grow[data-gid=\"1146430\"]')||{}).outerHTML?.slice(0,600)})}"))
    ok("within 48h: kickoff-hour temp on the row", "64°" in rows.get("1146430", "") and "rain" not in rows.get("1146430", ""), rows.get("1146430"))
    ok("rain 60%: temp + rain % on the row", "70° · 60% rain" in rows.get("1146518", ""), rows.get("1146518"))
    ok("20% rain: no rain text", "68°" in rows.get("1146612", "") and "rain" not in rows.get("1146612", ""), rows.get("1146612"))
    icon = await pg.evaluate("()=>{const r=document.querySelector('.grow[data-gid=\"1146518\"] .wxs svg');return r?r.innerHTML:''}")
    ok("rain row shows the rain icon", "M8 17l-1 3" in icon, icon)
    nowrap = await pg.evaluate("()=>[...document.querySelectorAll('.gsub')].every(e=>e.scrollHeight<=e.clientHeight+2)")
    ok("bottom lines stay one line", nowrap)
    await pg.evaluate("()=>showTab('events')"); await pg.wait_for_timeout(400)
    vis = await pg.evaluate("()=>[...document.querySelectorAll('.grow[data-gid=\"1146430\"]')].map(e=>e.offsetParent!==null)")
    print("visible", vis)
    await pg.locator('.grow[data-gid="1146430"]').filter(visible=True).first.click(); await pg.wait_for_timeout(300)
    d1 = await pg.locator('.grow[data-gid="1146430"]').filter(visible=True).first.locator(".wxb").inner_text()
    ok("drop-down within 48h: At kickoff, feels, wind, updated, mark, Data sources", all(x in d1 for x in ["AT KICKOFF", "64° · Mostly sunny", "Feels 62°", "Rain 5%", "Wind 6 mph S", "Updated", "Data sources"]), d1)
    mk = await pg.evaluate("()=>!!document.querySelector('.grow[data-gid=\"1146430\"] .wxb img.wxmark')")
    ok("Apple Weather mark image shown", mk)
    await pg.locator('.grow[data-gid="1146430"]').filter(visible=True).first.scroll_into_view_if_needed()
    await pg.screenshot(path="/tmp/wx_open1.png")
    await pg.locator('.grow[data-gid="1146518"]').filter(visible=True).first.click(); await pg.wait_for_timeout(300)
    d2 = await pg.locator('.grow[data-gid="1146518"]').filter(visible=True).first.locator(".wxb").inner_text()
    ok("drop-down 2-10 days: Game day forecast, high/low, rain", all(x in d2 for x in ["GAME DAY FORECAST", "High 70° · Low 52° · Rain", "Rain 60%", "Data sources"]), d2)
    await pg.locator('.grow[data-gid="1146518"]').filter(visible=True).first.scroll_into_view_if_needed()
    await pg.screenshot(path="/tmp/wx_open2.png")
    # stale: hourly older than 2h -> falls back to daily (12h); daily older than 12h -> nothing
    await pg.evaluate("at=>{WX['85001'].at=at; wxRedraw()}", AT - 3*3600e3); await pg.wait_for_timeout(300)
    r3 = await pg.evaluate("()=>[...document.querySelectorAll('.grow[data-gid=\"1146430\"] .gsub')].map(e=>e.textContent).join(' | ')")
    ok("hourly forecast 3h old: falls back to the day forecast", "81°" in r3, r3)
    await pg.evaluate("at=>{WX['85001'].at=at; wxRedraw()}", AT - 13*3600e3); await pg.wait_for_timeout(300)
    r4 = await pg.evaluate("()=>[...document.querySelectorAll('.wxs')].length")
    ok("forecast 13h old: hidden", r4 == 0, r4)
    # >10 days: nothing; past games: nothing
    await pg.clock.set_fixed_time(datetime.datetime(2026, 11, 9, 18, tzinfo=datetime.timezone.utc))
    await pg.evaluate("at=>{WX['85001'].at=Date.now(); wxRedraw()}", 0); await pg.wait_for_timeout(300)
    r5 = await pg.evaluate("()=>{return [...document.querySelectorAll('.grow[data-gid=\"1146612\"] .gsub')].map(e=>e.textContent).join(' | ')}")
    ok("more than 10 days out: no weather", "°" not in r5, r5)
    ok("no page errors", not errs, errs)
    await b.close()
  print(f"{sum(R)}/{len(R)}")
asyncio.run(main())
