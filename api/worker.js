// Sideline Standings API. Serves the static site, plus /api/* for signed-in accounts.
// Accounts are optional: everything public works without one. A signed-in account only stores
// the person's followed teams (so they follow them across devices) and when they were last on.
// Alerts (push notifications): api/alerts.js (who gets what) and api/push.js (sending).
// Storage: one Cloudflare KV namespace (binding USERS), shared by UAT and live, one key per user:
//   u:<clerk user id> -> {favs: [team keys], email, created, seen}
// Sign-in is Clerk (clerk.sidelinestandings.com). Session tokens are checked here without a network
// call: RS256 signature against Clerk's public key (CLERK_JWT_KEY), then the time claims and the origin.

import {makeLog} from "./log.js";
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
    ctx.waitUntil(pushCheck(env).then(r => { const busy = r && (r.sent || r.gone || r.init || r.remErr || r.wrapErr); (busy ? L.keep : L.info).call(L, "check", r); })
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
      if (rec && now - (rec.seen || 0) > SEEN_EVERY) { rec.seen = now; await put(env, c.sub, rec); L.keep("account.active", {uid: c.sub, email: rec.email || c.email || "", teams: rec.favs.length}); }
      return json({signedIn: true, exists: !!rec, favs: rec ? rec.favs : [], picks: rec && rec.picks || {}, admin: isOwner(c)});
    }
    // PUT /api/me: save teams (and the email shown in the admin list).
    if (p === "/api/me" && req.method === "PUT") {
      let body = {}; try { body = await req.json(); } catch (e) {}
      const isNew = !rec;
      rec = Object.assign({created: now}, rec || {}, {favs: cleanFavs(body.favs), seen: now});
      const em = cleanEmail(c.email) || cleanEmail(body.email); if (em) rec.email = em;
      await put(env, c.sub, rec);
      (isNew ? L.keep : L.info).call(L, isNew ? "account.created" : "account.favs", {uid: c.sub, email: rec.email || "", favs: rec.favs.join(" ")});
      return json({ok: true, favs: rec.favs});
    }
    // PUT /api/picks: the person's saved Predict picks (private), {conf file: {game id: {p, o, t}}}.
    if (p === "/api/picks" && req.method === "PUT") {
      let body = {}; try { body = await req.json(); } catch (e) {}
      if (!rec) rec = {created: now, favs: [], seen: now};
      rec.picks = cleanPicks(body.picks);
      await put(env, c.sub, rec);
      L.info("picks.saved", {uid: c.sub, n: Object.values(rec.picks).reduce((a, g) => a + Object.keys(g).length, 0)});
      return json({ok: true});
    }
    // Pick'em: weekend score picks, names, leaderboard (api/pickem.js).
    if (p === "/api/pickem" || p === "/api/pickem/name") return pickRoute(p, req, env, c, json, L);
    // Alerts (push notifications) for this device: settings, test, turn off.
    if (p === "/api/push" || p === "/api/push/test" || p === "/api/push/seen") return pushRoute(p, req, env, c, json);
    // DELETE /api/me: delete everything stored for this account.
    if (p === "/api/me" && req.method === "DELETE") {
      await env.USERS.delete(key);
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
    return json({error: "not found"}, 404);
  }
}

