import asyncio, datetime, json
from playwright.async_api import async_playwright
U = "http://localhost:8767/"; R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)
NOW = datetime.datetime(2026, 11, 18, 18, tzinfo=datetime.timezone.utc); AT = int(NOW.timestamp()*1000) - 20*60e3
conf = json.load(open("/tmp/xfo/site/data/conf/u17b-4284-40525.json"))
for e in conf.get("events", []):
  for g in e.get("games", []):
    g["zip"] = "85001"
    if g["id"] == 1146612: g.pop("venue", None); g["zipx"] = 1
WXR = {"attr": {"dark": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='14'/%3E", "legal": "https://example.com/legal"},
       "z": {"85001": {"at": AT, "tz": "America/Phoenix", "d": {"2026-11-20": [81, 60, 10, "Clear"], "2026-11-21": [70, 52, 60, "Rain"], "2026-11-22": [68, 50, 20, "PartlyCloudy"]},
                        "h": {"2026-11-20T08": [64, 62, 5, 6, 200, "MostlyClear"], "2026-11-20T10": [70, 69, 0, 4, 90, "Clear"]}}}}
async def main():
  async with async_playwright() as p:
    b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    ctx = await b.new_context(viewport={"width": 400, "height": 900}, service_workers="block", timezone_id="America/Los_Angeles"); pg = await ctx.new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.clock.install(time=NOW)
    await pg.route("**/data/conf/u17b-4284-40525.json", lambda r: r.fulfill(status=200, body=json.dumps(conf), content_type="application/json"))
    async def api(r):
      u = r.request.url
      if "/api/wx" in u: return await r.fulfill(status=200, body=json.dumps(WXR), content_type="application/json")
      if "/api/config" in u: return await r.fulfill(status=200, body='{"gate":false}', content_type="application/json")
      return await r.fulfill(status=401, body="{}", content_type="application/json")
    await pg.route("**/api/**", api)
    await pg.goto(U)
    await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('xfFavs',JSON.stringify(['u17b-131393']));localStorage.setItem('lastTeam','u17b-131393')}")
    await pg.goto(U + "#t=u17b-131393"); await pg.reload(); await pg.wait_for_timeout(3500)
    row = await pg.evaluate("""()=>[...document.querySelectorAll(`.grow[data-gid='1146612'] .gsub`)].map(e=>e.textContent).join(' | ')""")
    ok("game with no field: weather from the complex", "68°" in row, row)
    await pg.evaluate("()=>showTab('events')"); await pg.wait_for_timeout(400)
    await pg.locator('.grow[data-gid="1146612"]').filter(visible=True).first.click(); await pg.wait_for_timeout(300)
    t = await pg.locator('.grow[data-gid="1146612"]').filter(visible=True).first.locator(".wxb").inner_text()
    ok("drop-down says forecast is for the main complex", "Field not posted yet" in t, t)
    # open bracket slot with two possible times (8:00 and 10:00 field time) on Nov 20
    r = await pg.evaluate("""()=>{const D=CONF_CACHE['u17b-4284-40525'];const ev=D.events.find(e=>e.games.some(g=>g.id==1146430));
      const g1=Object.assign({},ev.games.find(g=>g.id==1146430),{id:9001,time:"10:00",zipx:1}), g2=Object.assign({},g1,{id:9002,time:"08:00"});
      const day={items:[{g:g1,cond:[]},{g:g2,cond:[]}]};
      const a=document.createElement('div');a.innerHTML=evTbdRow(ev,day,131393,false);
      const c=document.createElement('div');c.innerHTML=evTbdRow(ev,day,131393,true);
      return {games:a.querySelector('.gsub').textContent, card:c.textContent}}""")
    ok("Games tab slot: weather for the first possible time", r["games"].endswith("64°"), r["games"])
    ok("Events tab slot: 'At kickoff · first possible time' + complex note", "At kickoff · first possible time" in r["card"] and "Field not posted yet" in r["card"], r["card"])
    ok("no page errors", not errs, errs)
    await b.close()
  print(f"{sum(R)}/{len(R)}")
asyncio.run(main())
