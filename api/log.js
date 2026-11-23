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
// Admin page "Usage" section: prod (live) usage for today and the last 7 days, Pacific days. Totals only,
// no emails. Visitors = distinct devices that opened the site (people, not bots); signed in = distinct
// accounts that called the API; opens = every time the site or app started (people, not bots);
// errors = server errors. Version, where it was opened and load time come from the app's own log lines.
export async function usageStats(env) {
  if (!env.LOGS) return null;
  const now = new Date(), pt = new Date(now.toLocaleString("en-US", {timeZone: "America/Los_Angeles"}));
  const today = now.getTime() - (pt.getHours() * 3600 + pt.getMinutes() * 60 + pt.getSeconds()) * 1000 - now.getMilliseconds();
  const start = today - 6 * 864e5, day = "CAST((at - ?1) / 86400000 AS INTEGER)", W = "site = 'live' AND at >= ?1 AND json_valid(data)";
  const P = "json_extract(data, '$.p')", person = "coalesce(json_extract(data, '$.kind'), 'person') = 'person'";
  const all = (sql, ...b) => env.LOGS.prepare(sql).bind(start, ...b).all().then(r => r.results || []);
  const [vis, sig, opn, err, lines, wk] = await Promise.all([
    all(`SELECT ${day} d, count(DISTINCT coalesce(json_extract(data, '$.vid'), json_extract(data, '$.ua'))) n FROM events WHERE ${W} AND evt = 'api' AND ${P} = '/api/config' AND ${person} GROUP BY d`),
    all(`SELECT ${day} d, count(DISTINCT uid) n FROM events WHERE ${W} AND evt = 'api' AND uid IS NOT NULL GROUP BY d`),
    all(`SELECT ${day} d, count(*) n FROM events WHERE ${W} AND evt = 'api' AND ${P} = '/api/config' AND ${person} GROUP BY d`),
    all(`SELECT ${day} d, count(*) n FROM events WHERE ${W} AND (evt = 'api.error' OR (evt = 'api' AND json_extract(data, '$.s') >= 500)) GROUP BY d`),
    all(`SELECT ${P} p FROM events WHERE ${W} AND at >= ?2 AND evt = 'api' AND (${P} LIKE '/api/log/app/open/%' OR ${P} LIKE '/api/log/app/ready/%') AND ${person}`, today),
    all(`SELECT evt, count(*) n FROM events WHERE ${W} AND evt IN ('account.favs', 'picks.saved', 'account.created') GROUP BY evt`)]);
  // Sign-ups this week. New phones: first seen (any time in the logs) this week; "app" if any open was in the App Store app.
  // Asked: phones the app asked to sign in (since v1.60, with the tap that asked). Backed out: app sign-in sheet cancelled.
  const [np, asks, back] = await Promise.all([
    all(`SELECT count(*) n, coalesce(sum(app), 0) app FROM (SELECT min(at) first, max(CASE WHEN ${P} LIKE '/api/log/app/open/%~20app' THEN 1 ELSE 0 END) app FROM events
      WHERE site = 'live' AND evt = 'api' AND json_valid(data) AND json_extract(data, '$.vid') IS NOT NULL AND ${person} GROUP BY json_extract(data, '$.vid')) WHERE first >= ?1`),
    all(`SELECT ${P} p, count(*) n, count(DISTINCT json_extract(data, '$.vid')) v FROM events WHERE ${W} AND evt = 'api' AND ${P} LIKE '/api/log/app/ask/%' AND ${person} GROUP BY p`),
    all(`SELECT count(*) n FROM events WHERE ${W} AND evt = 'api' AND ${P} = '/api/log/app/signin-back/cancelled'`)]);
  // Gave up: phones that started signing in this week (asked, or the app's sign-in sheet came back) and have
  // not been signed in since. Expired: phones signed in before whose latest open this week was signed out
  // (Clerk's 7-day limit, or a sign-out). Should be near 0 once our own sign-in pass is live.
  const VID = "json_extract(data, '$.vid')";
  const [gave, exp] = await Promise.all([
    all(`SELECT count(*) n FROM (SELECT ${VID} vid, min(at) t FROM events WHERE ${W} AND evt = 'api' AND (${P} LIKE '/api/log/app/signin-back/%' OR ${P} LIKE '/api/log/app/ask/%') AND ${VID} IS NOT NULL GROUP BY 1) s
      WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.site = 'live' AND e.evt = 'api' AND e.uid IS NOT NULL AND json_valid(e.data) AND json_extract(e.data, '$.vid') = s.vid AND e.at >= s.t)`),
    all(`SELECT count(*) n FROM (SELECT ${VID} vid, max(at) lastopen FROM events WHERE ${W} AND evt = 'api' AND ${P} = '/api/config' AND ${person} AND ${VID} IS NOT NULL GROUP BY 1) w
      JOIN (SELECT ${VID} vid, max(at) lastin FROM events WHERE site = 'live' AND evt = 'api' AND uid IS NOT NULL AND json_valid(data) AND ${VID} IS NOT NULL GROUP BY 1) s ON s.vid = w.vid WHERE w.lastopen > s.lastin`)]);
  const days = [...Array(7)].map((_, i) => ({at: start + i * 864e5, signedIn: 0, visitors: 0, opens: 0, errors: 0}));
  const fill = (rows, f) => rows.forEach(r => { if (days[r.d]) days[r.d][f] = r.n; });
  fill(vis, "visitors"); fill(sig, "signedIn"); fill(opn, "opens"); fill(err, "errors");
  // today's open lines look like /api/log/app/open/v1.56~20app; ready lines /api/log/app/ready/740ms~20v1.56
  const dec = s => { try { return decodeURIComponent(s.replace(/~/g, "%")); } catch (e) { return s; } };
  const ver = {}, where = {}, ms = [];
  for (const {p} of lines) {
    const t = dec(p).split("/").pop();
    if (p.includes("/open/")) { const [v, w] = t.split(" "); ver[v] = (ver[v] || 0) + 1; where[w || "web"] = (where[w || "web"] || 0) + 1; }
    else { const n = parseInt(t, 10); if (n > 0) ms.push(n); }
  }
  ms.sort((a, b) => a - b);
  const n = e => (wk.find(r => r.evt === e) || {}).n || 0;
  const NAMES = {"tab:games": "Games", "tab:predict": "Predict", "tab:league": "League", "tab:events": "Events", star: "Follow", bell: "Alerts", settings: "Settings", share: "Share"};
  const taps = {};
  for (const r of asks) { const a = dec(r.p).split("/").pop(); const k = NAMES[a] || a; taps[k] = (taps[k] || 0) + r.n; }
  const askedPhones = await (asks.length ? all(`SELECT count(DISTINCT json_extract(data, '$.vid')) n FROM events WHERE ${W} AND evt = 'api' AND ${P} LIKE '/api/log/app/ask/%' AND ${person}`).then(r => r[0].n) : 0);
  const signups = {newPhones: np[0] ? np[0].n : 0, newApp: np[0] ? np[0].app : 0, asked: askedPhones, signedUp: n("account.created"), backedOut: back[0] ? back[0].n : 0, gaveUp: gave[0] ? gave[0].n : 0, expired: exp[0] ? exp[0].n : 0,
    taps: Object.entries(taps).sort((a, b) => b[1] - a[1]).slice(0, 3)};
  return {days, today: {ver, where, typical: ms.length ? ms[Math.floor(ms.length / 2)] : null, slowest: ms.length ? ms[ms.length - 1] : null, loads: ms.length},
    week: {follows: n("account.favs"), picks: n("picks.saved")}, signups, at: Date.now()};
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
