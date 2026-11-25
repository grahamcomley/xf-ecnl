import asyncio, datetime, json
from playwright.async_api import async_playwright
U = "http://localhost:8767/"
NOW = datetime.datetime(2026, 11, 19, 17, tzinfo=datetime.timezone.utc)   # Thu Nov 19, 9 AM PST
AT = int(NOW.timestamp()*1000) - 25*60e3
conf = json.load(open("/tmp/xfo/site/data/conf/u17b-4284-40525.json"))
for e in conf.get("events", []):
  for g in e.get("games", []): g["zip"] = "85001"
WX = {"attr": {"dark": "", "legal": "https://weatherkit.apple.com/legal-attribution.html"},
      "z": {"85001": {"at": AT, "tz": "America/Phoenix", "d": {"2026-11-20": [79, 55, 0, "Clear"], "2026-11-21": [74, 52, 10, "MostlyClear"], "2026-11-22": [71, 50, 50, "Rain"]},
                       "h": {"2026-11-20T16": [76, 75, 0, 7, 270, "Clear"]}}}}
FAVS = ["u17b-62277", "u16b-82130", "u13g-92130", "a19b-9594"]
async def main():
  async with async_playwright() as p:
    b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    ctx = await b.new_context(viewport={"width": 402, "height": 874}, device_scale_factor=3, service_workers="block", timezone_id="America/Los_Angeles",
                              user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 SidelineShell/1")
    pg = await ctx.new_page()
    await pg.clock.install(time=NOW)
    await pg.route("**/data/conf/u17b-4284-40525.json", lambda r: r.fulfill(status=200, body=json.dumps(conf), content_type="application/json"))
    async def api(r):
      u = r.request.url
      if "/api/wx" in u: return await r.fulfill(status=200, body=json.dumps(WX), content_type="application/json")
      if "/api/config" in u: return await r.fulfill(status=200, body='{"gate":false}', content_type="application/json")
      return await r.fulfill(status=401, body="{}", content_type="application/json")
    await pg.route("**/api/**", api)
    await pg.goto(U)
    await pg.evaluate("f=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('gateCache','off');localStorage.setItem('xfFavs',JSON.stringify(f));localStorage.setItem('lastTeam',f[0]);localStorage.setItem('alertCardNo','1');localStorage.setItem('appOffered','1');localStorage.setItem('a2hsOffered','1')}", FAVS)
    async def go(hash, tab, name, prep=None):
      await pg.goto(U + "#t=" + hash); await pg.reload(); await pg.wait_for_timeout(2500)
      await pg.evaluate(f"()=>showTab('{tab}')"); await pg.wait_for_timeout(1200)
      if prep: await pg.evaluate(prep); await pg.wait_for_timeout(600)
      await pg.screenshot(path=f"/tmp/ss/{name}.png")
    await go("u16b-82130", "team", "1-standings")
    await go("u17b-62277", "games", "2-games", "()=>{const r=[...document.querySelectorAll('.grow[data-gid]')].find(e=>e.offsetParent&&/76°/.test(e.textContent));if(r){r.click();r.scrollIntoView({block:'center'})}}")
    await go("u17b-62277", "events", "3-events")
    await go("u16b-82130", "predict", "4-predict")
    await b.close()
asyncio.run(main())
