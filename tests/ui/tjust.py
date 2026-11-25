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
    await pg.clock.install(time=datetime.datetime(2026, 11, 18, 18, tzinfo=datetime.timezone.utc))
    status = json.load(open("/tmp/xfo/site/data/status.json")); status["evnew"] = {"4429": "2026-11-17T20:00:00Z"}
    await pg.route("**/data/status.json", lambda r: r.fulfill(status=200, body=json.dumps(status), content_type="application/json"))
    await pg.route("**/api/**", lambda r: r.fulfill(status=200 if "/api/config" in r.request.url else 401, body='{"gate":false}' if "/api/config" in r.request.url else "{}", content_type="application/json"))
    await pg.goto(U)
    await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('xfFavs',JSON.stringify(['u17b-131393']));localStorage.setItem('lastTeam','u17b-131393');localStorage.setItem('alertsOn','1')}")
    await pg.goto(U + "#t=u17b-131393"); await pg.reload(); await pg.wait_for_timeout(3000)
    lab = await pg.evaluate("()=>[...document.querySelectorAll('.pane[data-tab=events] .evcard .evnew')].map(e=>e.closest('.evcard').dataset.ev+':'+e.textContent)")
    ok("Just posted label on the newly posted event", any(x.startswith("4429-") and "Just posted" in x for x in lab), lab)
    await pg.evaluate("()=>showTab('events')"); await pg.wait_for_timeout(500)
    await pg.screenshot(path="/tmp/justposted.png")
    seen = await pg.evaluate("()=>Object.keys(localStorage).filter(k=>k.startsWith('evSeen:'))")
    ok("marked seen once shown", len(seen) >= 1, seen)
    await pg.reload(); await pg.wait_for_timeout(3000)
    lab2 = await pg.evaluate("()=>document.querySelectorAll('.evcard .evnew').length")
    ok("gone after it was viewed", lab2 == 0, lab2)
    await pg.evaluate("()=>{ME={id:'u',email:'p@example.com',admin:false};teamSheet()}"); await pg.wait_for_timeout(300)
    rows = await pg.evaluate("()=>[...document.querySelectorAll('.tpal .opt')].map(o=>o.firstChild.firstChild.textContent.trim())")
    ok("team sheet has New event schedules row", rows[-1] == "New event schedules" and "Schedule changes" in rows, rows)
    sub = await pg.evaluate("()=>[...document.querySelectorAll('.tpal .opt .ddsub')].map(e=>e.textContent)")
    ok("Schedule changes says 28 days", any("next 28 days" in x for x in sub), sub)
    await pg.click('.tpal .seg[data-seg="ne"] button[data-v="0"]'); await pg.wait_for_timeout(300)
    cfg = await pg.evaluate("()=>JSON.parse(localStorage.getItem('alertCfg')).teams['u17b-131393']")
    ok("switching it off saves per team", cfg.get("ne") is False, cfg)
    await pg.screenshot(path="/tmp/sheet_ne.png")
    ok("no page errors", not errs, errs)
    await b.close()
  print(f"{sum(R)}/{len(R)} passed")
asyncio.run(main())
