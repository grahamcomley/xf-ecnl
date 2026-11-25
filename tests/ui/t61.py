import asyncio, datetime, sys
from playwright.async_api import async_playwright
U="http://localhost:8767/"
WHEN = sys.argv[1] if len(sys.argv) > 1 else "2026-11-21T16:00"
async def main():
  async with async_playwright() as p:
    b=await p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for w in (440, 375):
      ctx=await b.new_context(viewport={"width":w,"height":956},device_scale_factor=2,service_workers="block");pg=await ctx.new_page()
      errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
      await pg.clock.install(time=datetime.datetime.fromisoformat(WHEN).replace(tzinfo=datetime.timezone.utc))
      await pg.route("**/api/**",lambda r:r.fulfill(status=200 if "/api/config" in r.request.url else 401,body='{"gate":false}' if "/api/config" in r.request.url else "{}",content_type="application/json"))
      await pg.goto(U); await pg.evaluate("()=>{localStorage.clear();localStorage.setItem('signedInOnce','1');localStorage.setItem('xfFavs',JSON.stringify(['u17b-62277','u16b-82130','u13g-92130']));localStorage.setItem('lastTeam','u17b-62277')}")
      await pg.goto(U+"#t=u17b-62277"); await pg.wait_for_timeout(3000)
      await pg.evaluate("()=>showTab('games')"); await pg.wait_for_timeout(500)
      await pg.evaluate("()=>setGv('mine')"); await pg.wait_for_timeout(500)
      info = await pg.evaluate("""()=>({btns:[...document.querySelectorAll('#gviews button')].map(b=>b.innerText+(b.classList.contains('on')?'*':'')+(b.scrollWidth>b.clientWidth?'(cut)':'')),
        title:document.querySelector('.gv[data-gv=mine] details.sec summary')?.innerText.replace(/\\n/g,' | '), rows:[...document.querySelectorAll('.gv[data-gv=mine] details.sec')][0]?.querySelectorAll('.grow').length,
        link:document.querySelector('.gv[data-gv=mine] .evgo')?.innerText})""")
      print(w, "mine", info)
      await pg.screenshot(path=f"/tmp/v61_team{w}.png", full_page=True)
      await pg.evaluate("()=>setGv('every')"); await pg.wait_for_timeout(1500)
      info = await pg.evaluate("""()=>({allmine:document.body.classList.contains('allmine'), title:document.querySelector('#ttl .ttn').textContent, lit:[...document.querySelectorAll('#tstrip .tpill')].map(p=>getComputedStyle(p).backgroundColor),
        secs:[...document.querySelectorAll('#allmine details.sec summary')].map(x=>x.innerText.replace(/\\n/g,' | ')), rows:document.querySelectorAll('#allmine .grow').length, none:document.querySelector('#allmine .nogames')?.innerText, link:document.querySelector('#allmine .evgo')?.innerText,
        cut:[...document.querySelectorAll('#allmine .gl,#allmine .gr')].filter(e=>e.scrollWidth>e.clientWidth+1).length})""")
      print(w, "every", info)
      await pg.screenshot(path=f"/tmp/v61_all{w}.png", full_page=True)
      await pg.evaluate("()=>showTab('team')"); await pg.wait_for_timeout(300)
      print(w, "after tab switch", await pg.evaluate("()=>[document.body.classList.contains('allmine'), document.querySelector('#ttl .ttn').textContent]"))
      await pg.evaluate("()=>showTab('games')"); await pg.wait_for_timeout(300)
      await pg.click("#tstrip .tpill[data-k='u16b-82130']"); await pg.wait_for_timeout(1500)
      print(w, "after pill", await pg.evaluate("()=>[document.body.classList.contains('allmine'), document.querySelector('#ttl .ttn').textContent, localStorage.getItem('gview'), TAB, [...document.querySelectorAll('#gviews button')].map(b=>b.innerText+(b.classList.contains('on')?'*':''))]"))
      print("errors:", errs)
      await ctx.close()
    await b.close()
asyncio.run(main())
