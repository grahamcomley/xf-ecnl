import asyncio, json
from playwright.async_api import async_playwright
U="http://localhost:8767/"; R=[]
def ok(n,c,d=""): R.append(c); print(("PASS " if c else "FAIL ")+n, "" if c else d)
us=json.load(open("/tmp/us.json"))
API="""(a)=>{const [us,saved]=a;ME={admin:true,email:"owner"};const t=Date.parse("2026-11-11T12:00:00");window.api=async(m,p)=>{
  if(p==="/api/admin/usage")return us;
  if(p==="/api/admin")return {total:34,users:[{email:"a",teams:2,seen:Date.now(),created:Date.now()}],top:[{k:"u17b-131393",n:3}],alerts:{people:20,devices:22,week:22,lastWeek:30,lastCheck:Date.now()}};
  if(p==="/api/admin/pickem")return {players:[]};
  if(!saved)return {saved:false};
  if(p==="/api/admin/apns")return {saved:true,kid:"PFC93KP5HV",at:t,chk:{ok:true}};
  if(p==="/api/admin/wxkey")return {saved:true,kid:"97Q84R92F3",sid:"com.sidelinestandings.weather",at:Date.parse("2026-11-24T11:00:00"),chk:{ok:true}};
  if(p==="/api/admin/clerk")return {saved:true,at:t};
  if(p==="/api/admin/reviewer")return {email:"appreview@x",password:"p",demo:{email:"d",password:"q"}};
  return {};};for(const k in ADM_OPEN)delete ADM_OPEN[k];openPage("admin",true);}"""
async def main():
  async with async_playwright() as p:
    b=await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for w in (440,375):
      ctx=await b.new_context(viewport={"width":w,"height":1100},service_workers="block");pg=await ctx.new_page()
      errs=[];pg.on("pageerror",lambda e:errs.append(str(e)))
      await pg.route("**/api/**",lambda r:r.fulfill(status=401,body="{}",content_type="application/json"))
      await pg.goto(U);await pg.wait_for_timeout(1500)
      await pg.evaluate(API,[us,True]); await pg.wait_for_timeout(800)
      r=await pg.evaluate("""()=>({folds:[...document.querySelectorAll('.pgin > details.fold')].map(d=>d.dataset.fold+':'+d.open),
        setup:document.querySelector('[data-fold=setup] summary').innerText.replace(/\\n/g,' | '),
        subs:[...document.querySelectorAll('[data-fold=setup] details.fold.sub')].map(d=>[...d.querySelector('summary > span').childNodes].map(n=>n.textContent).join(' | ')+':'+d.open),
        demo:document.body.innerText.includes('Demo login'), info:!!document.querySelector('#appinfo')})""")
      print(w, r)
      ok(f"[{w}] every section starts closed", all(f.endswith(":false") for f in r["folds"]), r["folds"])
      ok(f"[{w}] Setup is last", r["folds"][-1].startswith("setup:"), r["folds"])
      ok(f"[{w}] Setup line says all saved", "Setup | Keys and logins · all saved" == r["setup"], r["setup"])
      ok(f"[{w}] saved boxes are one closed line each", r["subs"]==["Apple push key | Saved · Nov 11:false","Apple Weather key | Saved · Nov 24:false","Clerk secret key | Saved · Nov 11:false","App Review login | Set up:false"], r["subs"])
      ok(f"[{w}] demo login and bridge text gone", not r["demo"] and not r["info"])
      await pg.evaluate("()=>{document.querySelector('[data-fold=setup]').open=true;document.querySelector('[data-fold=s_wx]').open=true}"); await pg.wait_for_timeout(200)
      t=await pg.evaluate("()=>document.querySelector('[data-fold=s_wx] .foldin').innerText")
      ok(f"[{w}] opening a box shows details and the replace form", "Key ID 97Q84R92F3" in t and "working" in t and await pg.evaluate("()=>!!document.querySelector('#wxsave')"), t)
      wrap=await pg.evaluate("()=>[...document.querySelectorAll('[data-fold=setup] details.sub>summary')].filter(e=>e.getBoundingClientRect().height>60).length")
      ok(f"[{w}] one-line rows don't wrap", wrap==0, wrap)
      await pg.locator('[data-fold=setup]').scroll_into_view_if_needed(); await pg.screenshot(path=f"/tmp/adm2_{w}.png", full_page=False)
      # nothing saved: boxes open, counter
      await pg.evaluate(API,[us,False]); await pg.wait_for_timeout(800)
      r2=await pg.evaluate("()=>({s:document.querySelector('[data-fold=setup] summary').innerText, o:[...document.querySelectorAll('[data-fold=setup] details.sub')].map(d=>d.open)})")
      ok(f"[{w}] nothing saved: boxes open, says 4 needed", "4 needed" in r2["s"] and all(r2["o"]), r2)
      ok(f"[{w}] no page errors", not errs, errs)
      await ctx.close()
    await b.close()
  print(f"{sum(R)}/{len(R)}")
asyncio.run(main())
