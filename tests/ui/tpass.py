import asyncio, json
from playwright.async_api import async_playwright
U = "http://localhost:8767/"
R = []
def ok(n, c, d=""): R.append(c); print(("PASS " if c else "FAIL ") + n, "" if c else d)

async def run(b, mode):
  ctx = await b.new_context(viewport={"width": 400, "height": 900}, service_workers="block"); pg = await ctx.new_page()
  errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
  seen = []
  await pg.route("**/clerk.sidelinestandings.com/**", lambda r: r.abort())   # Clerk's 7 days are over / Clerk down
  async def api(r):
    u = r.request.url; auth = r.request.headers.get("authorization", "")
    seen.append((u.split("/api/")[1], auth[:12]))
    if "/api/config" in u: return await r.fulfill(status=200, body='{"gate":true,"pickem":false}', content_type="application/json")
    if mode == "cancelled": return await r.fulfill(status=200 if "/api/me" in u and r.request.method == "GET" else 401, body='{"signedIn":false,"pass":"cancelled"}', content_type="application/json")
    if "/api/me" in u and r.request.method == "GET":
      return await r.fulfill(status=200, body=json.dumps({"signedIn": True, "exists": True, "favs": ["u17b-62277"], "picks": {}, "admin": False}), content_type="application/json", headers={"x-pass": "sp1.NEW.sig"})
    return await r.fulfill(status=200, body='{"ok":true}', content_type="application/json")
  await pg.route("**/api/**", api)
  await pg.goto(U)
  await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('merged:user_1','1');localStorage.setItem('xfFavs',JSON.stringify(['u17b-62277']));localStorage.setItem('lastTeam','u17b-62277');localStorage.setItem('spass',JSON.stringify({t:'sp1.OLD.sig',id:'user_1',email:'parent@example.com'}))}")
  await pg.goto(U + "#t=u17b-62277"); await pg.reload(); await pg.wait_for_timeout(3500)
  st = await pg.evaluate("()=>({me: ME && ME.id, email: ME && ME.email, pass: localStorage.getItem('spass')})")
  if mode == "ok":
    ok("signed in from our pass with Clerk gone", st["me"] == "user_1" and st["email"] == "parent@example.com", st)
    ok("API calls carry our pass", any(a.startswith("Bearer sp1.") for _, a in seen), seen[:4])
    ok("renewed pass saved", st["pass"] and "sp1.NEW.sig" in st["pass"], st)
    await pg.evaluate("()=>openPage('account', true)"); await pg.wait_for_timeout(300)
    ok("account page has Sign out on all devices", await pg.evaluate("()=>!!document.querySelector('#acctoutall')"))
    await pg.click("#acctoutall"); await pg.wait_for_timeout(1500)
    st2 = await pg.evaluate("()=>({me: ME, pass: localStorage.getItem('spass')})")
    ok("sign out on all devices: asked the server, then signed out here", any(p.startswith("pass/all") for p, _ in seen) and not st2["me"] and not st2["pass"], (st2, seen[-3:]))
  else:
    ok("cancelled pass: signed out, pass removed", not st["me"] and not st["pass"], st)
  ok("no page errors (" + mode + ")", not errs, errs)
  await ctx.close()

async def main():
  async with async_playwright() as p:
    b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    await run(b, "ok"); await run(b, "cancelled")
    await b.close()
  print(f"{sum(R)}/{len(R)} passed")
asyncio.run(main())
