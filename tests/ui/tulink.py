import asyncio, json
from playwright.async_api import async_playwright
U="http://localhost:8767/"; R=[]
def ok(n,c,d=""): R.append(c); print(("PASS " if c else "FAIL ")+n, "" if c else d)
INIT = """window.Capacitor={isNativePlatform:()=>true,Plugins:{App:{_cb:null,addListener(ev,cb){window.__appcb=cb;return {remove(){}}},getLaunchUrl:()=>Promise.resolve({url:"https://sidelinestandings.com/#t=a13b-9139,a13b-8288&add=1"})}}};"""
async def main():
  async with async_playwright() as p:
    b=await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    ctx=await b.new_context(viewport={"width":390,"height":844},service_workers="block",user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 SidelineShell/1")
    pg=await ctx.new_page(); errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
    await pg.route("**/api/**", lambda r: r.fulfill(status=200 if "config" in r.request.url else 401, body='{"gate":false}' if "config" in r.request.url else "{}", content_type="application/json"))
    await pg.goto(U); await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('gateCache','off');localStorage.setItem('xfFavs',JSON.stringify(['u17b-131393']))}")
    await ctx.add_init_script(INIT)
    await pg.goto(U+"#t=u17b-131393"); await pg.reload(); await pg.wait_for_timeout(3000)
    t=await pg.locator("#tshare").inner_text() if await pg.locator("#tshare").is_visible() else ""
    ok("cold start from a shared link: shared-teams sheet in the app", "2 teams shared with you" in t, t)
    await pg.evaluate("()=>{document.querySelector('#tshare').hidden=true;window.__appcb({url:'https://sidelinestandings.com/#t=a13b-8823'})}"); await pg.wait_for_timeout(1500)
    ok("link tapped while open: goes to that team", await pg.evaluate("()=>CUR")=="a13b-8823", await pg.evaluate("()=>CUR"))
    await pg.evaluate("()=>window.__appcb({url:'https://evil.com/#t=a13b-9139'})"); await pg.wait_for_timeout(500)
    ok("other sites ignored", await pg.evaluate("()=>CUR")=="a13b-8823")
    ok("no page errors", not errs, errs)
    await b.close()
  print(f"{sum(R)}/{len(R)}")
asyncio.run(main())
