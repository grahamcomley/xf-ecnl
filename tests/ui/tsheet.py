import asyncio, datetime, json
from playwright.async_api import async_playwright
U = "http://localhost:8767/"
R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)
async def main():
  async with async_playwright() as p:
    b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for w in (1900, 400):
      ctx = await b.new_context(viewport={"width": w, "height": 800}, service_workers="block"); pg = await ctx.new_page()
      errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
      await pg.route("**/api/**", lambda r: r.fulfill(status=200 if "/api/config" in r.request.url else 401, body='{"gate":false}' if "/api/config" in r.request.url else "{}", content_type="application/json"))
      await pg.goto(U)
      await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('xfFavs',JSON.stringify(['u17b-95205']));localStorage.setItem('lastTeam','u17b-95205');localStorage.setItem('alertsOn','1')}")
      await pg.goto(U + "#t=u17b-95205"); await pg.reload(); await pg.wait_for_timeout(3000)
      await pg.evaluate("()=>{ME={id:'u',email:'p@example.com',admin:false};teamSheet()}"); await pg.wait_for_timeout(400)
      info = await pg.evaluate("""()=>{const card=document.querySelector('#tpbody').getBoundingClientRect(), head=document.querySelector('.tphead span').getBoundingClientRect(),
        rows=[...document.querySelectorAll('.tpal .opt')].map(o=>o.firstChild.firstChild.textContent.trim()), seg=document.querySelector('.tpal .seg').getBoundingClientRect(), main=document.querySelector('main').getBoundingClientRect();
        return {pad:head.left-card.left, headLeft:head.left, segRight:seg.right, mainL:main.left, mainR:main.right, rows}}""")
      print(w, info)
      ok(f"{w}: Schedule changes row on the team sheet", "Schedule changes" in info["rows"] and info["rows"][-1] == "New event schedules", info["rows"])
      ok(f"{w}: text has left padding", info["pad"] >= 16, info["pad"])
      if w > 1000: ok(f"{w}: sheet content lines up with the page column", abs(info["headLeft"] - info["mainL"]) < 30 and info["segRight"] <= info["mainR"] + 10, info)
      await pg.click('.tpal .seg[data-seg="sc"] button[data-v="0"]'); await pg.wait_for_timeout(300)
      cfg = await pg.evaluate("()=>JSON.parse(localStorage.getItem('alertCfg')).teams['u17b-95205']")
      ok(f"{w}: switching it off saves per team", cfg.get("sc") is False, cfg)
      await pg.screenshot(path=f"/tmp/sheet{w}.png")
      ok(f"{w}: no page errors", not errs, errs)
      await ctx.close()
    await b.close()
  print(f"{sum(R)}/{len(R)} passed")
asyncio.run(main())
