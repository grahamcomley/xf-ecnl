import asyncio, json
from playwright.async_api import async_playwright
U = "http://localhost:8767/"; R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)
IPH = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
AND = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
K = ["u17b-131393", "a13b-9139", "a13b-8288", "a13b-8823"]
async def page(b, ua, favs=None, gate=False):
  ctx = await b.new_context(viewport={"width": 390, "height": 844}, service_workers="block", user_agent=ua); pg = await ctx.new_page()
  errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
  async def api(r):
    u = r.request.url
    if "/api/config" in u: return await r.fulfill(status=200, body=json.dumps({"gate": gate}), content_type="application/json")
    return await r.fulfill(status=401, body="{}", content_type="application/json")
  await pg.route("**/api/**", api)
  await pg.goto(U)
  await pg.evaluate("f=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('gateCache','off');if(f)localStorage.setItem('xfFavs',JSON.stringify(f));localStorage.setItem('appOffered','1')}", favs)
  return ctx, pg, errs
async def main():
  async with async_playwright() as p:
    b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    # iPhone Safari
    ctx, pg, errs = await page(b, IPH, K)
    await pg.goto(U + "#t=" + K[0]); await pg.reload(); await pg.wait_for_timeout(2500)
    meta = await pg.evaluate("()=>document.querySelector('meta[name=apple-itunes-app]').content")
    ok("App Store banner tag", meta == "app-id=6833709358", meta)
    await pg.evaluate("()=>{ME={id:'u',email:'p@x',admin:false};openPage('settings')}"); await pg.wait_for_timeout(400)
    t = await pg.locator("#pages").inner_text() if await pg.locator("#pages").count() else await pg.evaluate("()=>document.body.innerText")
    ok("iPhone Settings: Get the iPhone app", "Get the iPhone app" in t and "Add to Home Screen" not in t, t[:400])
    ok("Settings: Share my teams (2+ teams)", "Share my teams" in t)
    await pg.evaluate("()=>openA2hs()"); await pg.wait_for_timeout(200)
    h = await pg.locator("#a2hs").inner_text()
    href = await pg.locator("#a2hsapp").get_attribute("href")
    ok("iPhone sheet: App Store", "Get the iPhone app" in h and "Get it on the App Store" in h and href == "https://apps.apple.com/app/sideline-standings/id6833709358", h)
    await pg.screenshot(path="/tmp/app_sheet.png")
    await pg.evaluate("()=>document.querySelector('#a2hs').hidden=true")
    bl = await pg.evaluate("()=>alertsBlocker()")
    ok("iPhone alerts message points to the app", bl and "free app" in bl["msg"] and bl["btn"][1] == "Get the iPhone app", bl)
    # share sheet
    await pg.evaluate("()=>{closePages();shareTeamsSheet()}"); await pg.wait_for_timeout(200)
    t = await pg.locator("#tshare").inner_text()
    ok("share sheet lists 4 teams, button 'Share 4 teams'", t.count("\n") > 3 and "Share 4 teams" in t, t)
    await pg.locator("#tshare input").nth(1).uncheck(); await pg.wait_for_timeout(100)
    ok("untick: 'Share 3 teams'", "Share 3 teams" in await pg.locator("#tsharego").inner_text())
    await pg.screenshot(path="/tmp/share_sheet.png")
    await pg.evaluate("()=>{window.__sh=null;navigator.share=async d=>{window.__sh=d}}")
    await pg.click("#tsharego"); await pg.wait_for_timeout(200)
    sh = await pg.evaluate("()=>window.__sh")
    ok("share link has 3 teams + add=1", sh and sh["url"].count(",") == 2 and sh["url"].endswith("&add=1") and "3 teams" in sh["title"], sh)
    await pg.evaluate("()=>{document.querySelector('#tshare').hidden=true;ME=null;openPage('settings')}"); await pg.wait_for_timeout(300)
    ok("signed out Settings: Get the iPhone app still there", "Get the iPhone app" in await pg.evaluate("()=>document.body.innerText"))
    await pg.evaluate("()=>closePages()")
    ok("no page errors (iPhone)", not errs, errs)
    await ctx.close()
    # receiving: already follows one of them
    ctx, pg, errs = await page(b, IPH, [K[0]])
    link = "#t=" + ",".join(K[:3]) + "&add=1"
    await pg.goto(U + link); await pg.wait_for_timeout(3000)
    t = await pg.locator("#tshare").inner_text()
    ok("landing: '3 teams shared with you', one marked Following", "3 teams shared with you" in t and "Following" in t and "Follow 2 teams" in t, t)
    await pg.screenshot(path="/tmp/share_land.png")
    await pg.click("#tsharego"); await pg.wait_for_timeout(300)
    f = await pg.evaluate("()=>favs()")
    ok("follow adds the 2 new teams", f == K[:3], f)
    ok("address cleaned to the first team", await pg.evaluate("()=>location.hash") == "#t=" + K[0])
    await pg.goto(U + "#t=" + ",".join(K[:2]) + "&add=1"); await pg.wait_for_timeout(1500)
    tt = await pg.evaluate("()=>document.body.innerText")
    ok("all already followed: says so", "You already follow these 2 teams" in tt and await pg.locator("#tshare").is_hidden(), tt[-300:])
    ok("no page errors (landing)", not errs, errs)
    await ctx.close()
    # signed out with the gate on: kept for after sign-in
    ctx, pg, errs = await page(b, IPH, None, True)
    await pg.evaluate("()=>{localStorage.setItem('gateCache','on');localStorage.removeItem('signedInOnce')}")
    await pg.goto(U + link); await pg.wait_for_timeout(2500)
    ok("signed out: saved for after sign-in", await pg.evaluate("()=>localStorage.getItem('shareAdd')") == ",".join(K[:3]))
    await ctx.close()
    # Android keeps Add to Home Screen / install
    ctx, pg, errs = await page(b, AND, K)
    await pg.goto(U + "#t=" + K[0]); await pg.reload(); await pg.wait_for_timeout(2000)
    await pg.evaluate("()=>openA2hs()"); await pg.wait_for_timeout(200)
    h = await pg.locator("#a2hs").inner_text()
    ok("Android: unchanged (no App Store sheet)", "App Store" not in h and "Home Screen" in h, h)
    ok("no page errors (Android)", not errs, errs)
    await ctx.close(); await b.close()
  print(f"{sum(R)}/{len(R)}")
asyncio.run(main())
