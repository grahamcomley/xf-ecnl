// Sideline Standings API. Serves the static site, plus /api/* for signed-in accounts.
// Accounts are optional: everything public works without one. A signed-in account only stores
// the person's followed teams (so they follow them across devices) and when they were last on.
// Storage: one Cloudflare KV namespace (binding USERS), shared by UAT and live, one key per user:
//   u:<clerk user id> -> {favs: [team keys], email, created, seen}
// Sign-in is Clerk (clerk.sidelinestandings.com). Session tokens are checked here without a network
// call: RS256 signature against Clerk's public key (CLERK_JWT_KEY), then the time claims and the origin.

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
const cleanEmail = e => typeof e === "string" && e.length < 200 && /^[^@\s]+@[^@\s]+$/.test(e) ? e.toLowerCase() : "";
// Owner check uses only what Clerk signed (the "email" claim added to the session token, or a user id
// listed in OWNER_IDS) - never an email sent by the page, which anyone could fake.
let OWNER_IDS = [];
const isOwner = c => OWNERS.includes(cleanEmail(c.email)) || OWNER_IDS.includes(c.sub);

async function put(env, id, rec) {
  await env.USERS.put("u:" + id, JSON.stringify(rec), {metadata: {e: rec.email || "", n: rec.favs.length, s: rec.seen, c: rec.created}});
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url), p = url.pathname;
    if (!p.startsWith("/api/")) return env.ASSETS.fetch(req);
    OWNER_IDS = (env.OWNER_IDS || "").split(",").map(s => s.trim()).filter(Boolean);
    if (!env.USERS) return json({error: "storage not set up"}, 503);

    // Public: does the site require sign-in? (Owner switch on the Admin page; on unless turned off.)
    if (p === "/api/config" && req.method === "GET") {
      const g = await env.USERS.get("cfg:gate");
      return json({gate: g !== "off"});
    }
    const c = await who(req, env);
    if (!c) return json({signedIn: false}, p === "/api/me" && req.method === "GET" ? 200 : 401);
    const key = "u:" + c.sub, now = Date.now();
    let rec = await env.USERS.get(key, "json");

    // GET /api/me: the account's saved teams. Also notes "last seen".
    if (p === "/api/me" && req.method === "GET") {
      if (rec && now - (rec.seen || 0) > SEEN_EVERY) { rec.seen = now; await put(env, c.sub, rec); }
      return json({signedIn: true, exists: !!rec, favs: rec ? rec.favs : [], admin: isOwner(c)});
    }
    // PUT /api/me: save teams (and the email shown in the admin list).
    if (p === "/api/me" && req.method === "PUT") {
      let body = {}; try { body = await req.json(); } catch (e) {}
      rec = Object.assign({created: now}, rec || {}, {favs: cleanFavs(body.favs), seen: now});
      const em = cleanEmail(c.email) || cleanEmail(body.email); if (em) rec.email = em;
      await put(env, c.sub, rec);
      return json({ok: true, favs: rec.favs});
    }
    // DELETE /api/me: delete everything stored for this account.
    if (p === "/api/me" && req.method === "DELETE") {
      await env.USERS.delete(key);
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
      return json({total: users.length, users, top});
    }
    // PUT /api/admin/config: owner turns "Require sign-in" on or off.
    if (p === "/api/admin/config" && req.method === "PUT") {
      if (!isOwner(c)) return json({error: "not allowed"}, 403);
      let body = {}; try { body = await req.json(); } catch (e) {}
      await env.USERS.put("cfg:gate", body.gate ? "on" : "off");
      return json({ok: true, gate: !!body.gate});
    }
    return json({error: "not found"}, 404);
  }
};
