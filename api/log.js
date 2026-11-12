// Logging. Every API call, every alerts check and every notification sent is written to the D1
// database "sideline-logs" (binding LOGS), table events. Claude reads it directly (Cloudflare D1
// query) - nothing goes to the public GitHub logs. The same database keeps a mirror of who has an
// account (people) and which devices have alerts (devices), refreshed on every change and daily.
// Also printed to Workers Logs. If LOGS isn't bound, important events fall back to KV (14 days).
const siteOf = env => env.SITE === "live" ? "live" : "uat";
export function makeLog(env, ctx) {
  const site = siteOf(env), rows = [], kept = [];
  const add = (lvl, evt, data, keep) => {
    const at = Date.now(), uid = data && data.uid || null;
    try { console[lvl](JSON.stringify(Object.assign({evt, site, at: new Date(at).toISOString()}, data))); } catch (e) {}
    const rest = Object.assign({}, data); delete rest.uid;
    rows.push([at, site, evt, uid, JSON.stringify(rest).slice(0, 4000)]);
    if (keep) kept.push(Object.assign({evt, at}, data));
  };
  return {
    info(evt, data = {}) { add("log", evt, data, false); },
    keep(evt, data = {}) { add("log", evt, data, true); },
    error(evt, data = {}) { add("error", evt, Object.assign({error: true}, data), true); },
    flush() {
      let p;
      if (env.LOGS && rows.length) {
        const st = env.LOGS.prepare("INSERT INTO events (at, site, evt, uid, data) VALUES (?, ?, ?, ?, ?)");
        p = env.LOGS.batch(rows.splice(0).map(r => st.bind(...r))).catch(e => console.error("log write failed", String(e)));
        kept.length = 0;
      } else if (kept.length && env.USERS) {
        const key = `ev:${site}:${new Date().toISOString()}:${Math.random().toString(36).slice(2, 6)}`;
        p = env.USERS.put(key, JSON.stringify(kept.splice(0)), {expirationTtl: 14 * 86400}).catch(() => {});
        rows.length = 0;
      }
      if (p && ctx && ctx.waitUntil) ctx.waitUntil(p);
      return p;
    }
  };
}
// Mirror of accounts and alert devices (full detail, private to the Cloudflare account).
export function dbPerson(env, ctx, uid, rec) {
  if (!env.LOGS) return;
  const picks = rec ? Object.values(rec.picks || {}).reduce((a, g) => a + Object.keys(g).length, 0) : 0;
  const q = rec ? env.LOGS.prepare("INSERT INTO people (uid, email, created, seen, favs, picks, updated) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET email=excluded.email, created=excluded.created, seen=excluded.seen, favs=excluded.favs, picks=excluded.picks, updated=excluded.updated")
      .bind(uid, rec.email || "", rec.created || 0, rec.seen || 0, (rec.favs || []).join(" "), picks, Date.now())
    : env.LOGS.prepare("DELETE FROM people WHERE uid = ?").bind(uid);
  const p = q.run().catch(e => console.error("people write failed", String(e)));
  if (ctx && ctx.waitUntil) ctx.waitUntil(p);
  return p;
}
export function dbDevice(env, ctx, dev, d) {
  if (!env.LOGS) return;
  const site = siteOf(env);
  let q;
  if (d) {
    const settings = {q: d.q, badge: d.badge, teams: (d.teams || []).map(t => ({k: t.k, our: t.our, lg: t.lg, mo: t.mo, rem: t.rem, wr: t.wr}))};
    let host = ""; try { host = d.sub.apns ? "app" : new URL(d.sub.endpoint).host; } catch (e) {}
    q = env.LOGS.prepare("INSERT INTO devices (site, dev, uid, service, tz, settings, created, seen, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(site, dev) DO UPDATE SET uid=excluded.uid, service=excluded.service, tz=excluded.tz, settings=excluded.settings, created=excluded.created, seen=excluded.seen, updated=excluded.updated")
      .bind(site, dev, d.uid || "", host, d.tz || "", JSON.stringify(settings), d.created || 0, d.seen || 0, Date.now());
  } else q = env.LOGS.prepare("DELETE FROM devices WHERE site = ? AND dev = ?").bind(site, dev);
  const p = q.run().catch(e => console.error("device write failed", String(e)));
  if (ctx && ctx.waitUntil) ctx.waitUntil(p);
  return p;
}
// Once a day: refresh the whole mirror from KV and drop events older than 60 days.
export async function dbDailySync(env) {
  if (!env.LOGS || !env.USERS) return null;
  const site = siteOf(env), day = new Date().toISOString().slice(0, 10), flag = `cfg:d1sync:${site}`;
  if (await env.USERS.get(flag) === day) return null;
  await env.USERS.put(flag, day);
  const list = async prefix => { const out = []; let cursor; do { const r = await env.USERS.list({prefix, cursor, limit: 1000}); out.push(...r.keys.map(k => k.name)); cursor = r.list_complete ? null : r.cursor; } while (cursor); return out; };
  let people = 0, devices = 0;
  if (site === "uat") for (const k of await list("u:")) { await dbPerson(env, null, k.slice(2), await env.USERS.get(k, "json")); people++; }
  for (const k of await list(`d:${site}:`)) { await dbDevice(env, null, k.split(":")[2], await env.USERS.get(k, "json")); devices++; }
  await env.LOGS.prepare("DELETE FROM events WHERE at < ?").bind(Date.now() - 60 * 864e5).run();
  return {people, devices};
}
