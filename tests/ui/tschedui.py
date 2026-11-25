import asyncio, datetime, json
from playwright.async_api import async_playwright
U = "http://localhost:8767/"
R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)
async def main():
  async with async_playwright() as p:
    b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    ctx = await b.new_context(viewport={"width": 400, "height": 900}, service_workers="block", timezone_id="America/Los_Angeles"); pg = await ctx.new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.clock.install(time=datetime.datetime(2026, 10, 15, 18, tzinfo=datetime.timezone.utc))
    status = json.load(open("/tmp/xfo/site/data/status.json")); status["chg"] = {"1121594": [["t"], "2026-10-15T17:00:00Z"]}
    await pg.route("**/data/status.json", lambda r: r.fulfill(status=200, body=json.dumps(status), content_type="application/json"))
    await pg.route("**/api/**", lambda r: r.fulfill(status=200 if "/api/config" in r.request.url else 401, body='{"gate":false}' if "/api/config" in r.request.url else "{}", content_type="application/json"))
    await pg.goto(U)
    await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('xfFavs',JSON.stringify(['u17b-95205']));localStorage.setItem('lastTeam','u17b-95205')}")
    await pg.goto(U + "#t=u17b-95205"); await pg.reload(); await pg.wait_for_timeout(3000)
    await pg.evaluate("()=>showTab('games')"); await pg.wait_for_timeout(800)
    row = await pg.evaluate("()=>{const r=document.querySelector('[data-gid=\"1121594\"] .gsub');return r&&r.innerHTML}")
    ok("changed game shows 'Time changed' on its bottom line", row and 'class="chg">Time changed' in row, row)
    col = await pg.evaluate("()=>{const c=document.querySelector('[data-gid=\"1121594\"] .chg');return c&&getComputedStyle(c).color}")
    ok("tag is orange", col == "rgb(240, 153, 123)", col)
    others = await pg.evaluate("()=>[...new Set([...document.querySelectorAll('.chg')].map(e=>e.closest('[data-gid]').dataset.gid))]")
    ok("only that game is tagged", others == ['1121594'], others)
    await pg.screenshot(path="/tmp/sched_games.png", full_page=False)
    # Settings › Alerts: Options row
    await pg.evaluate("()=>{ME={id:'u',email:'p@example.com',admin:false};localStorage.setItem('alertsOn','1');window.pushSub=async()=>({endpoint:'https://x/'});}")
    html = await pg.evaluate("""async()=>{const b=document.createElement('div');document.body.appendChild(b);
      const real=PUSH_OK; try{ PUSH_OK=()=>true }catch(e){}
      STACK=['alerts'];document.querySelector('#pg').hidden=false;await drawAlertsPage(b);return b.innerHTML}""")
    ok("Alerts page: team summary lists Schedule changes; no device-wide row", "Schedule changes" in html and "data-team=\"__sched\"" not in html, html[:300])
    print("errors:", errs)
    await b.close()
  print(f"{sum(R)}/{len(R)} passed")
asyncio.run(main())
