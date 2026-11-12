// Sideline Standings API. Serves the static site, plus /api/* for signed-in accounts.
// Accounts are optional: everything public works without one. A signed-in account only stores
// the person's followed teams (so they follow them across devices) and when they were last on.
// Alerts (push notifications): api/alerts.js (who gets what) and api/push.js (sending).
// Storage: one Cloudflare KV namespace (binding USERS), shared by UAT and live, one key per user:
//   u:<clerk user id> -> {favs: [team keys], email, created, seen}
// Sign-in is Clerk (clerk.sidelinestandings.com). Session tokens are checked here without a network
// call: RS256 signature against Clerk's public key (CLERK_JWT_KEY), then the time claims and the origin.

import {makeLog, dbPerson, dbDailySync} from "./log.js";
import {apnsKey, apnsSend, APNS_TEAM, APNS_TOPIC} from "./push.js";
import {route as pickRoute, adminList as pickList, adminSet as pickSet} from "./pickem.js";
import {setLog as pushSetLog, route as pushRoute, check as pushCheck, deleteUser as pushDeleteUser, adminStats as pushStats, testOwner as pushTestOwner, replayOwner as pushReplay} from "./alerts.js";

const ORIGINS = ["https://sidelinestandings.com", "https://www.sidelinestandings.com", "https://uat.sidelinestandings.com"];
const OWNERS = ["grahamcomley@gmail.com"];
const SEEN_EVERY = 6 * 3600 * 1000;   // write "last seen" at most every 6 hours (keeps KV writes low)

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: {"content-type": "application/json", "cache-control": "no-store"}});

const b64urlToBytes = s => {
  s = s.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "=";
  const bin = atob(s), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
};
let KEY = null;
async function publicKey(pem) {
  if (KEY) return KEY;
  const body = pem.replace(/\\n/g, "\n").replace(/-----(BEGIN|END) PUBLIC KEY-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(body), c => c.charCodeAt(0));
  KEY = await crypto.subtle.importKey("spki", der, {name: "RSASSA-PKCS1-v1_5", hash: "SHA-256"}, false, ["verify"]);
  return KEY;
}
async function verify(token, pem) {
  const p = token.split(".");
  if (p.length !== 3) throw new Error("malformed");
  const head = JSON.parse(new TextDecoder().decode(b64urlToBytes(p[0])));
  if (head.alg !== "RS256") throw new Error("alg");
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", await publicKey(pem), b64urlToBytes(p[2]), new TextEncoder().encode(p[0] + "." + p[1]));
  if (!ok) throw new Error("signature");
  const c = JSON.parse(new TextDecoder().decode(b64urlToBytes(p[1]))), t = Date.now() / 1000;
  if (typeof c.exp === "number" && t > c.exp + 10) throw new Error("expired");
  if (typeof c.nbf === "number" && t + 10 < c.nbf) throw new Error("not yet valid");
  if (c.azp && !ORIGINS.includes(c.azp)) throw new Error("origin");
  if (!c.sub) throw new Error("no user");
  return c;
}
async function who(req, env) {
  const m = (req.headers.get("authorization") || "").match(/^Bearer (.+)$/);
  if (!m || !env.CLERK_JWT_KEY) return null;
  try { return await verify(m[1], env.CLERK_JWT_KEY); } catch (e) { return null; }
}
const cleanFavs = a => Array.isArray(a) ? [...new Set(a.filter(k => typeof k === "string" && /^[a-z0-9-]{3,40}$/.test(k)))].slice(0, 60) : [];
// Saved picks: p = their pick (H/D/A), o = our pick when they made it, t = when.
function cleanPicks(x) {
  const out = {}; let n = 0;
  if (!x || typeof x !== "object") return out;
  for (const [fk, games] of Object.entries(x)) {
    if (!/^[a-z0-9-]{3,60}$/.test(fk) || !games || typeof games !== "object") continue;
    for (const [g, v] of Object.entries(games)) {
      if (!/^\d{1,12}$/.test(g) || !v || !["H", "D", "A"].includes(v.p) || n >= 4000) continue;
      (out[fk] = out[fk] || {})[g] = {p: v.p, o: ["H", "D", "A"].includes(v.o) ? v.o : "", t: typeof v.t === "number" ? Math.round(v.t) : 0};
      n++;
    }
  }
  return out;
}
const cleanEmail = e => typeof e === "string" && e.length < 200 && /^[^@\s]+@[^@\s]+$/.test(e) ? e.toLowerCase() : "";
// Owner check uses only what Clerk signed (the "email" claim added to the session token, or a user id
// listed in OWNER_IDS) - never an email sent by the page, which anyone could fake.
let OWNER_IDS = [];
const isOwner = c => OWNERS.includes(cleanEmail(c.email)) || OWNER_IDS.includes(c.sub);

async function put(env, id, rec) {
  await env.USERS.put("u:" + id, JSON.stringify(rec), {metadata: {e: rec.email || "", n: rec.favs.length, s: rec.seen, c: rec.created}});
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url), p = url.pathname;
    if (!p.startsWith("/api/")) return env.ASSETS.fetch(req);
    // Every API call is logged: method, path, status, who, how long (+ kept events, see api/log.js).
    const L = makeLog(env, ctx), t0 = Date.now(), who0 = {uid: null};
    pushSetLog(L);
    let res;
    try { res = await handle(req, env, url, p, L, who0); }
    catch (e) { L.error("api.error", {m: req.method, p, uid: who0.uid, msg: String(e && e.message || e), stack: String(e && e.stack || "").slice(0, 800)}); res = json({error: "server error"}, 500); }
    L.info("api", {m: req.method, p, s: res.status, uid: who0.uid, ms: Date.now() - t0, ua: (req.headers.get("user-agent") || "").slice(0, 120)});
    L.flush();
    return res;
  },
  // Every 5 minutes: send alerts for scores that changed in the latest data update.
  async scheduled(evt, env, ctx) {
    if (!env.USERS) return;
    const L = makeLog(env, ctx); pushSetLog(L);
    ctx.waitUntil(dbDailySync(env).then(r => r && L.info("mirror.sync", r)).catch(e => L.error("mirror.error", {msg: String(e)})));
    // Apple push: once per saved key, check this server can reach Apple and the key is accepted. A made-up
    // device token is used, so Apple answering "BadDeviceToken" means the connection and the key both work.
    const apnsCheck = (async () => {
      const k = await env.USERS.get("cfg:apns", "json");
      if (!k || !k.p8 || (k.chks || {})[env.SITE] === k.at) return;   // once per key, per site
      let r; try { r = await apnsSend(env, "0".repeat(64), {aps: {alert: {title: "check", body: "check"}}}); } catch (e) { r = {status: -1, reason: String(e && e.message || e)}; }
      const ok = r.status === 410 && /BadDeviceToken/.test(r.reason);
      L.keep("apns.check", {site: env.SITE, kid: k.kid, status: r.status, reason: r.reason, ok});
      k.chks = Object.assign({}, k.chks, {[env.SITE]: k.at}); k.chkr = {status: r.status, reason: r.reason, ok, when: Date.now(), site: env.SITE};
      await env.USERS.put("cfg:apns", JSON.stringify(k));
    })().catch(e => L.error("apns.check.error", {msg: String(e)}));
    // the log is saved once, after the alerts check: wait for the Apple check too
    ctx.waitUntil(apnsCheck.then(() => pushCheck(env)).then(r => { const busy = r && (r.sent || r.gone || r.init || r.remErr || r.wrapErr); (busy ? L.keep : L.info).call(L, "check", r); })
      .catch(e => L.error("check.error", {msg: String(e && e.message || e), stack: String(e && e.stack || "").slice(0, 800)}))
      .then(() => L.flush()));
  }
};

async function handle(req, env, url, p, L, who0) {
  {
    OWNER_IDS = (env.OWNER_IDS || "").split(",").map(s => s.trim()).filter(Boolean);
    if (!env.USERS) return json({error: "storage not set up"}, 503);

    // Public: does the site require sign-in? (Owner switch on the Admin page; on unless turned off.)
    if (p === "/api/config" && req.method === "GET") {
      const g = await env.USERS.get("cfg:gate");
      return json({gate: g !== "off"});
    }
    if (p === "/api/push/key" && req.method === "GET") return pushRoute(p, req, env, null, json);
    const c = await who(req, env);
    if (!c) return json({signedIn: false}, p === "/api/me" && req.method === "GET" ? 200 : 401);
    who0.uid = c.sub;
    const key = "u:" + c.sub, now = Date.now();
    let rec = await env.USERS.get(key, "json");

    // GET /api/me: the account's saved teams. Also notes "last seen".
    if (p === "/api/me" && req.method === "GET") {
      if (rec && now - (rec.seen || 0) > SEEN_EVERY) { rec.seen = now; await put(env, c.sub, rec); dbPerson(env, null, c.sub, rec); L.keep("account.active", {uid: c.sub, email: rec.email || c.email || "", teams: rec.favs.length}); }
      return json({signedIn: true, exists: !!rec, favs: rec ? rec.favs : [], picks: rec && rec.picks || {}, admin: isOwner(c)});
    }
    // PUT /api/me: save teams (and the email shown in the admin list).
    if (p === "/api/me" && req.method === "PUT") {
      let body = {}; try { body = await req.json(); } catch (e) {}
      const isNew = !rec;
      rec = Object.assign({created: now}, rec || {}, {favs: cleanFavs(body.favs), seen: now});
      const em = cleanEmail(c.email) || cleanEmail(body.email); if (em) rec.email = em;
      await put(env, c.sub, rec); dbPerson(env, null, c.sub, rec);
      (isNew ? L.keep : L.info).call(L, isNew ? "account.created" : "account.favs", {uid: c.sub, email: rec.email || "", favs: rec.favs.join(" ")});
      return json({ok: true, favs: rec.favs});
    }
    // PUT /api/picks: the person's saved Predict picks (private), {conf file: {game id: {p, o, t}}}.
    if (p === "/api/picks" && req.method === "PUT") {
      let body = {}; try { body = await req.json(); } catch (e) {}
      if (!rec) rec = {created: now, favs: [], seen: now};
      rec.picks = cleanPicks(body.picks);
      await put(env, c.sub, rec); dbPerson(env, null, c.sub, rec);
      L.info("picks.saved", {uid: c.sub, n: Object.values(rec.picks).reduce((a, g) => a + Object.keys(g).length, 0)});
      return json({ok: true});
    }
    // Pick'em: weekend score picks, names, leaderboard (api/pickem.js).
    if (p === "/api/pickem" || p === "/api/pickem/name") return pickRoute(p, req, env, c, json, L);
    // Alerts (push notifications) for this device: settings, test, turn off.
    if (p === "/api/push" || p === "/api/push/test" || p === "/api/push/seen" || p === "/api/push/inbox") return pushRoute(p, req, env, c, json);
    // DELETE /api/me: delete everything stored for this account.
    if (p === "/api/me" && req.method === "DELETE") {
      await env.USERS.delete(key); dbPerson(env, null, c.sub, null);
      await pushDeleteUser(env, c.sub);
      L.keep("account.deleted", {uid: c.sub, email: rec && rec.email || ""});
      return json({ok: true});
    }
    // GET /api/admin: owner only. Everyone who has signed in, and the most-followed teams.
    if (p === "/api/admin" && req.method === "GET") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      const users = [], count = {};
      let cursor;
      do {
        const r = await env.USERS.list({prefix: "u:", cursor, limit: 1000});
        for (const k of r.keys) {
          const m = k.metadata || {};
          users.push({email: m.e || "", teams: m.n || 0, seen: m.s || 0, created: m.c || 0});
        }
        cursor = r.list_complete ? null : r.cursor;
      } while (cursor);
      if (users.length <= 500) {   // small enough to read everyone's teams for the "most followed" list
        const r = await env.USERS.list({prefix: "u:", limit: 1000});
        await Promise.all(r.keys.map(async k => { const v = await env.USERS.get(k.name, "json"); (v && v.favs || []).forEach(f => count[f] = (count[f] || 0) + 1); }));
      }
      users.sort((a, b) => b.seen - a.seen);
      const top = Object.entries(count).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([k, n]) => ({k, n}));
      let alerts = null; try { alerts = await pushStats(env); } catch (e) {}
      return json({total: users.length, users, top, alerts});
    }
    // PUT /api/admin/config: owner turns "Require sign-in" on or off.
    if (p === "/api/admin/config" && req.method === "PUT") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      let body = {}; try { body = await req.json(); } catch (e) {}
      await env.USERS.put("cfg:gate", body.gate ? "on" : "off");
      L.keep("admin.gate", {uid: c.sub, gate: !!body.gate});
      return json({ok: true, gate: !!body.gate});
    }
    // Pick'em players: list, rename, hide (owner only).
    if (p === "/api/admin/pickem" && req.method === "GET") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      const list = await pickList(env);
      const emails = {};
      await Promise.all(list.map(async x => { const u = await env.USERS.get("u:" + x.uid, "json"); emails[x.uid] = u && u.email || ""; }));
      return json({players: list.map(x => Object.assign(x, {email: emails[x.uid]}))});
    }
    if (p === "/api/admin/pickem" && req.method === "PUT") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      let body = {}; try { body = await req.json(); } catch (e) {}
      const r = await pickSet(env, String(body.uid || ""), body);
      L.keep("admin.pickem", Object.assign({uid: c.sub, player: body.uid}, r));
      return json(r, r.error ? 422 : 200);
    }
    // POST /api/admin/replay: owner gets last weekend's real results as alerts on their own devices.
    if (p === "/api/admin/replay" && req.method === "POST") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      const r = await pushReplay(env, c.sub);
      L.keep("admin.replay", Object.assign({uid: c.sub}, r));
      return json(Object.assign({ok: true}, r));
    }
    // POST /api/admin/pushtest: owner sends a test alert to every device they turned alerts on.
    if (p === "/api/admin/pushtest" && req.method === "POST") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      return json({ok: true, sent: await pushTestOwner(env, c.sub)});
    }
    // POST /api/app/ticket: the App Store app's sign-in. The app opens /app-signin.html in the iPhone's own
    // sign-in sheet (shares Safari: saved Google login, passwords, Face ID for Apple). Once signed in there,
    // that page asks here for a one-time sign-in pass for the same person (Clerk sign-in token, 2 minutes),
    // and the app signs itself in with it. Needs the Clerk secret key (Admin › App Store app; KV cfg:clerk).
    if (p === "/api/app/ticket" && req.method === "POST") {
      const k = await env.USERS.get("cfg:clerk", "json");
      if (!k || !k.sk) { L.error("app.ticket", {uid: c.sub, why: "no clerk key"}); return json({error: "not set up"}, 503); }
      const r = await fetch("https://api.clerk.com/v1/sign_in_tokens", {method: "POST", headers: {authorization: "Bearer " + k.sk, "content-type": "application/json"},
        body: JSON.stringify({user_id: c.sub, expires_in_seconds: 120})});
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.token) { L.error("app.ticket", {uid: c.sub, status: r.status, why: (j.errors && j.errors[0] && j.errors[0].code) || ""}); return json({error: "couldn't sign in"}, 502); }
      L.keep("app.ticket", {uid: c.sub});
      return json({ticket: j.token});
    }
    // /api/admin/clerk: the Clerk secret key for the app's sign-in passes. GET says whether one is saved;
    // PUT {sk} checks it with Clerk, then saves it (KV cfg:clerk). Shared by UAT and live.
    if (p === "/api/admin/clerk") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      if (req.method === "GET") { const k = await env.USERS.get("cfg:clerk", "json"); return json({saved: !!(k && k.sk), at: k ? k.at : 0}); }
      if (req.method === "PUT") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        const sk = String(b.sk || "").trim();
        if (!/^sk_live_[A-Za-z0-9]+$/.test(sk)) return json({error: "That isn't a live secret key. In Clerk: Configure › API keys › Secret keys, copy the one starting sk_live_."}, 400);
        const t = await fetch("https://api.clerk.com/v1/users?limit=1", {headers: {authorization: "Bearer " + sk}});
        if (!t.ok) return json({error: "Clerk didn't accept that key (" + t.status + ")."}, 400);
        await env.USERS.put("cfg:clerk", JSON.stringify({sk, at: Date.now()}));
        L.keep("admin.clerk", {uid: c.sub});
        return json({ok: true});
      }
    }
    // /api/admin/reviewer: the login for Apple's App Review (they can't receive email codes). POST makes the
    // Clerk account appreview@sidelinestandings.com with a new password (or resets it) and follows XF 1;
    // GET shows it. Owner only; kept in KV cfg:reviewer. Needs password sign-in turned on in Clerk.
    if (p === "/api/admin/reviewer") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      if (req.method === "GET") { const r = await env.USERS.get("cfg:reviewer", "json"); return json(r || {}); }
      if (req.method === "POST") {
        const k = await env.USERS.get("cfg:clerk", "json"); if (!k || !k.sk) return json({error: "Save the Clerk secret key first."}, 400);
        const H = {authorization: "Bearer " + k.sk, "content-type": "application/json"}, email = "appreview@sidelinestandings.com";
        const abc = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789", rnd = crypto.getRandomValues(new Uint8Array(14));
        const password = "Sideline-" + [...rnd].map(b => abc[b % abc.length]).join("");
        const err = j => (j && j.errors && j.errors[0] && (j.errors[0].long_message || j.errors[0].message)) || "Clerk said no.";
        const found = await (await fetch("https://api.clerk.com/v1/users?email_address=" + encodeURIComponent(email), {headers: H})).json().catch(() => []);
        let id = Array.isArray(found) && found[0] && found[0].id, r;
        if (id) r = await fetch("https://api.clerk.com/v1/users/" + id, {method: "PATCH", headers: H, body: JSON.stringify({password, skip_password_checks: true})});
        else r = await fetch("https://api.clerk.com/v1/users", {method: "POST", headers: H, body: JSON.stringify({email_address: [email], password, skip_password_checks: true, first_name: "App", last_name: "Review"})});
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { L.error("admin.reviewer", {status: r.status, why: err(j)}); return json({error: err(j)}, 400); }
        id = id || j.id;
        const u = await env.USERS.get("u:" + id, "json") || {created: Date.now()};
        if (!(u.favs || []).length) { u.favs = ["u16b-82130"]; u.email = email; await env.USERS.put("u:" + id, JSON.stringify(u)); }
        const rec = {email, password, at: Date.now()};
        await env.USERS.put("cfg:reviewer", JSON.stringify(rec));
        L.keep("admin.reviewer", {uid: c.sub, reviewer: id});
        return json(rec);
      }
    }
    // /api/admin/apns: Apple push key for the App Store app. GET says whether one is saved (never returns it);
    // PUT {p8, kid} checks the key opens and saves it to KV cfg:apns. Shared by UAT and live.
    if (p === "/api/admin/apns") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      if (req.method === "GET") { const k = await env.USERS.get("cfg:apns", "json"); return json({saved: !!(k && k.p8), kid: k ? k.kid : "", at: k ? k.at : 0, chk: k && k.chkr || null}); }
      if (req.method === "PUT") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        const p8 = String(b.p8 || "").trim(), kid = String(b.kid || "").trim().toUpperCase();
        if (!/^[A-Z0-9]{10}$/.test(kid)) return json({error: "The Key ID is the 10 letters and numbers next to the key in Apple's list."}, 400);
        try { await apnsKey(p8); } catch (e) { return json({error: "That doesn't look like the .p8 key file's contents. Open the file and copy everything, including the BEGIN and END lines."}, 400); }
        await env.USERS.put("cfg:apns", JSON.stringify({p8, kid, team: APNS_TEAM, topic: APNS_TOPIC, at: Date.now()}));
        L.keep("admin.apns", {uid: c.sub, kid});
        return json({ok: true});
      }
    }
    return json({error: "not found"}, 404);
  }
}

