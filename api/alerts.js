// Alerts: which device gets which notification, and when.
//
// Storage (KV binding USERS, shared by UAT and live; SITE keeps them apart):
//   d:<site>:<device id> -> one device that turned alerts on:
//     {uid, sub: {endpoint, keys}, teams: [{k, f, n, our, lg}], q: {on, s, e}, tz, badge, created, upd}
//     our = our game's final score (and corrections); lg = "all" | "off" for other league games;
//     q = quiet hours (start/end "HH:MM", phone's time zone tz).
//   st:<site> -> one small state record written at most once per check:
//     {last: last alerts run handled, held: {device: [{c, t, kind, at}]}, ll: {"device|team": ms}, sent: {week: n}}
// Where the changes come from: site/data/alerts.json, written by scripts/alerts.py on each data update.
import {send, vapid} from "./push.js";

const HOUR = 3600e3;
const DEF_Q = {on: true, s: "22:00", e: "07:00"};
const site = env => env.SITE === "live" ? "live" : "uat";
const devKey = (env, id) => `d:${site(env)}:${id}`;
export async function devId(endpoint) {
  const h = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint)));
  return [...h.slice(0, 12)].map(b => b.toString(16).padStart(2, "0")).join("");
}
const okEndpoint = e => typeof e === "string" && e.length < 1000 && /^https:\/\/[a-z0-9.-]+(:\d+)?\//i.test(e);
const hhmm = s => typeof s === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(s) ? s : null;
function cleanDevice(b) {
  const sub = b && b.sub;
  if (!sub || !okEndpoint(sub.endpoint) || !sub.keys || typeof sub.keys.p256dh !== "string" || typeof sub.keys.auth !== "string") return null;
  const teams = (Array.isArray(b.teams) ? b.teams : []).filter(t => t && /^[a-z0-9-]{3,40}$/.test(t.k)).slice(0, 60).map(t => ({
    k: t.k, f: typeof t.f === "string" && /^[a-z0-9-]{3,60}$/.test(t.f) ? t.f : "",
    n: String(t.n || "").slice(0, 40), our: t.our !== false, lg: t.lg === "off" ? "off" : "all"}));
  const q = b.q || {};
  let tz = typeof b.tz === "string" && b.tz.length < 60 ? b.tz : "America/Los_Angeles";
  try { new Intl.DateTimeFormat("en-US", {timeZone: tz}); } catch (e) { tz = "America/Los_Angeles"; }
  return {sub: {endpoint: sub.endpoint, keys: {p256dh: sub.keys.p256dh.slice(0, 200), auth: sub.keys.auth.slice(0, 100)}},
    teams, q: {on: q.on !== false, s: hhmm(q.s) || DEF_Q.s, e: hhmm(q.e) || DEF_Q.e}, tz, badge: b.badge !== false};
}

// ---------- the page's calls (signed in) ----------
export async function route(p, req, env, c, json) {
  if (p === "/api/push/key" && req.method === "GET") return json({key: (await vapid(env)).pub});
  let body = {}; if (req.method !== "GET") { try { body = await req.json(); } catch (e) {} }
  const ep = req.method === "GET" ? new URL(req.url).searchParams.get("endpoint") : (body.endpoint || (body.sub && body.sub.endpoint));
  if (!okEndpoint(ep)) return json({error: "no device"}, 400);
  const id = await devId(ep), key = devKey(env, id);
  if (p === "/api/push" && req.method === "GET") {
    const d = await env.USERS.get(key, "json");
    return json(d && d.uid === c.sub ? {on: true, teams: d.teams, q: d.q, badge: d.badge} : {on: false});
  }
  if (p === "/api/push" && req.method === "PUT") {
    const d = cleanDevice(body); if (!d) return json({error: "bad device"}, 400);
    const old = await env.USERS.get(key, "json");
    const rec = Object.assign(d, {uid: c.sub, email: (c.email || "").toLowerCase(), created: old && old.created || Date.now(), upd: Date.now()});
    await env.USERS.put(key, JSON.stringify(rec), {metadata: {u: c.sub, n: rec.teams.length}});
    return json({ok: true});
  }
  if (p === "/api/push" && req.method === "DELETE") {
    const d = await env.USERS.get(key, "json");
    if (d && d.uid === c.sub) await env.USERS.delete(key);
    return json({ok: true});
  }
  if (p === "/api/push/test" && req.method === "POST") {
    const d = await env.USERS.get(key, "json");
    if (!d || d.uid !== c.sub) return json({error: "alerts not on for this device"}, 404);
    const t = d.teams[0];
    const st = await send(env, d.sub, {t: "Test alert", b: t ? `Alerts are on. You'll hear about ${t.n || "your team"} here.` : "Alerts are on.",
      u: "/" + (t ? "#t=" + t.k : ""), tag: "test", badge: d.badge});
    if (st === 404 || st === 410) { await env.USERS.delete(key); return json({error: "gone"}, 410); }
    return json({ok: st >= 200 && st < 300, status: st});
  }
  return json({error: "not found"}, 404);
}

// Devices for this site (optionally just one person's).
async function devices(env, uid) {
  const out = []; let cursor;
  do {
    const r = await env.USERS.list({prefix: `d:${site(env)}:`, cursor, limit: 1000});
    for (const k of r.keys) if (!uid || (k.metadata && k.metadata.u === uid)) out.push(k.name);
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return out;
}
export async function deleteUser(env, uid) {
  for (const s of ["uat", "live"]) {
    const e = Object.assign({}, env, {SITE: s});
    for (const k of await devices(e, uid)) await env.USERS.delete(k);
  }
}
export async function adminStats(env) {
  const st = await env.USERS.get(`st:${site(env)}`, "json") || {};
  const keys = await devices(env), people = new Set();
  let cursor;
  do {
    const r = await env.USERS.list({prefix: `d:${site(env)}:`, cursor, limit: 1000});
    r.keys.forEach(k => k.metadata && people.add(k.metadata.u));
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return {devices: keys.length, people: people.size, week: (st.sent || {})[weekKey(Date.now())] || 0,
    lastWeek: (st.sent || {})[weekKey(Date.now() - 7 * 864e5)] || 0, lastCheck: st.checked || 0};
}
export async function testOwner(env, uid) {
  let n = 0;
  for (const k of await devices(env, uid)) {
    const d = await env.USERS.get(k, "json"); if (!d) continue;
    const s = await send(env, d.sub, {t: "Admin test", b: "Test alert to every device you've turned alerts on.", u: "/", tag: "test", badge: d.badge});
    if (s === 404 || s === 410) await env.USERS.delete(k); else if (s < 300) n++;
  }
  return n;
}

// ---------- the check (every 5 minutes) ----------
const weekKey = ms => { const d = new Date(ms); d.setUTCHours(0, 0, 0, 0); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10); };
function localHM(tz, ms) {
  const p = new Intl.DateTimeFormat("en-US", {timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).formatToParts(new Date(ms));
  const h = p.find(x => x.type === "hour").value, m = p.find(x => x.type === "minute").value;
  return `${h === "24" ? "00" : h}:${m}`;
}
export function quiet(d, ms) {
  if (!d.q || !d.q.on) return false;
  const t = localHM(d.tz || "America/Los_Angeles", ms), s = d.q.s, e = d.q.e;
  if (s === e) return false;
  return s < e ? (t >= s && t < e) : (t >= s || t < e);
}
const dash = "–";
function ourLine(c, k) {
  const home = c.h === k, us = home ? c.hn : c.an, them = home ? c.an : c.hn;
  const a = home ? c.hs : c.as, b = home ? c.as : c.hs;
  const res = a > b ? "Won" : a < b ? "Lost" : "Draw";
  return {us, line: `${us} ${a}${dash}${b} ${them}`, res,
    fix: c.k === "fix" ? ` (corrected, was ${home ? c.ph : c.pa}${dash}${home ? c.pa : c.ph})` : ""};
}
const resLine = c => `${c.hn} ${c.hs}${dash}${c.as} ${c.an}`;
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

// Turn one device's items into notifications: one per team, our game first.
export function compose(d, items, overnight) {
  const byTeam = new Map();
  for (const it of items) { if (!byTeam.has(it.t)) byTeam.set(it.t, {our: [], lg: []}); byTeam.get(it.t)[it.kind].push(it.c); }
  const notes = [];
  for (const [k, g] of byTeam) {
    const team = d.teams.find(t => t.k === k) || {k, n: ""};
    const conf = (g.lg[0] || g.our[0] || {}).cn || "the league";
    const also = g.lg.length ? `${plural(g.lg.length, "new result")} in ${conf}` : "";
    if (g.our.length === 1) {
      const o = ourLine(g.our[0], k);
      notes.push({t: o.line, b: [`Final · ${o.res}${o.fix}`, also && "Also " + also].filter(Boolean).join(" · "), u: `/#t=${k}`, tag: "g" + g.our[0].g});
    } else if (g.our.length > 1) {
      const lines = g.our.map(c => { const o = ourLine(c, k); return `${o.line}${o.fix}`; });
      notes.push({t: `${team.n || ourLine(g.our[0], k).us}: ${plural(g.our.length, "new result")}`, b: lines.concat(also ? ["Also " + also] : []).join("\n"), u: `/#t=${k}`, tag: "t" + k});
    } else {
      const shown = g.lg.slice(0, 3).map(resLine), more = g.lg.length - shown.length;
      notes.push({t: `${plural(g.lg.length, "new result")} in ${conf}`, b: shown.join("\n") + (more > 0 ? `\n+${more} more` : ""), u: `/#t=${k}`, tag: "l" + k});
    }
  }
  if (overnight && notes.length > 1) {   // morning summary: one notification for everything held overnight
    return [{t: "Overnight results", b: notes.map(n => n.t).join("\n"), u: notes[0].u, tag: "overnight"}];
  }
  if (overnight && notes.length === 1) notes[0].t = "Overnight: " + notes[0].t;
  return notes;
}

// Which changes this device should hear about (each game once per device; our game beats league).
export function match(d, changes) {
  const items = [], used = new Set();
  for (const c of changes) {
    const ours = d.teams.find(t => t.our && (t.k === c.h || t.k === c.a));
    if (ours) { items.push({c, t: ours.k, kind: "our"}); used.add(c.g); }
  }
  for (const c of changes) {
    if (used.has(c.g) || !c.cf) continue;
    if (d.teams.some(t => t.k === c.h || t.k === c.a)) continue;   // our team's game with alerts off for it
    const t = d.teams.find(x => x.lg === "all" && x.f === c.cf);
    if (t) { items.push({c, t: t.k, kind: "lg"}); used.add(c.g); }
  }
  return items;
}

export async function check(env, now = Date.now()) {
  const sk = `st:${site(env)}`;
  const st = await env.USERS.get(sk, "json") || {};
  const before = JSON.stringify(Object.assign({}, st, {checked: 0}));
  let data;
  try {
    const r = await env.ASSETS.fetch(new Request("https://assets.local/data/alerts.json"));
    data = r.ok ? await r.json() : null;
  } catch (e) { data = null; }
  if (!data) return {skipped: "no alerts file"};
  const runs = data.runs || [];
  if (!st.last) {   // first check on this site: start from now, send nothing old
    st.last = runs.length ? runs[runs.length - 1].id : (data.updated || "0");
    st.checked = now; await env.USERS.put(sk, JSON.stringify(st));
    return {init: st.last};
  }
  const fresh = runs.filter(r => r.id > st.last);
  st.held = st.held || {}; st.ll = st.ll || {}; st.sent = st.sent || {};
  const due = Object.keys(st.held).filter(id => st.held[id].some(h => (h.at || 0) <= now));
  if (!fresh.length && !due.length) return {nothing: true};

  const changes = fresh.flatMap(r => r.c || []);
  const ids = new Set(due);
  let keys = [];
  if (changes.length) keys = await devices(env);
  else keys = due.map(id => devKey(env, id));
  let sent = 0, gone = 0;
  for (const key of keys) {
    const id = key.split(":")[2], d = await env.USERS.get(key, "json");
    if (!d) { delete st.held[id]; continue; }
    const items = changes.length ? match(d, changes) : [];
    const held = st.held[id] || [];
    if (!items.length && !ids.has(id)) continue;
    let out = [], keep = [], overnight = false;
    if (quiet(d, now)) {
      keep = held.concat(items.map(i => Object.assign(i, {at: 0, q: 1})));   // released when quiet hours end
    } else {
      const ready = held.filter(h => (h.at || 0) <= now);
      overnight = ready.some(h => h.q);
      keep = held.filter(h => (h.at || 0) > now);
      const all = ready.concat(items);
      // league-only notifications: at most one per team per hour (our game's score always goes now)
      for (const it of all) {
        const ourTeam = all.some(x => x.t === it.t && x.kind === "our");
        const last = st.ll[id + "|" + it.t] || 0;
        if (it.kind === "lg" && !ourTeam && !overnight && now - last < HOUR) keep.push(Object.assign(it, {at: last + HOUR}));
        else out.push(it);
      }
    }
    if (keep.length) st.held[id] = keep.slice(-200); else delete st.held[id];
    if (!out.length) continue;
    for (const n of compose(d, out, overnight)) {
      const s = await send(env, d.sub, Object.assign(n, {badge: d.badge}));
      if (s === 404 || s === 410) { await env.USERS.delete(key); delete st.held[id]; gone++; break; }
      if (s < 300) sent++;
    }
    for (const t of new Set(out.map(i => i.t))) st.ll[id + "|" + t] = now;
  }
  // tidy: forget hourly timers older than a day, keep 8 weeks of counts
  for (const k of Object.keys(st.ll)) if (now - st.ll[k] > 24 * HOUR) delete st.ll[k];
  const wk = weekKey(now); if (sent) st.sent[wk] = (st.sent[wk] || 0) + sent;
  for (const k of Object.keys(st.sent).sort().slice(0, -8)) delete st.sent[k];
  if (fresh.length) st.last = fresh[fresh.length - 1].id;
  // write only when something changed (a quiet night re-checks held alerts without writing)
  if (JSON.stringify(Object.assign({}, st, {checked: 0})) !== before) { st.checked = now; await env.USERS.put(sk, JSON.stringify(st)); }
  return {runs: fresh.length, changes: changes.length, sent, gone};
}
