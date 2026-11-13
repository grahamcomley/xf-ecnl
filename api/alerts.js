// Alerts: which device gets which notification, and when.
//
// Storage (KV binding USERS, shared by UAT and live; SITE keeps them apart):
//   d:<site>:<device id> -> one device that turned alerts on:
//     {uid, sub: {endpoint, keys}, teams: [{k, f, n, a, our, lg, mo, rem, wr}], q: {on, s, e}, tz, badge, seen, created, upd}
//     our = our game's final score (and corrections); lg = "all" | "near" | "off" for other league games
//     ("near" = games with a team within 2 places of us); mo = big moments (a line on the score alert);
//     rem = game-day reminder "am" (morning of) | "2h" (2 hours before) | "off"; wr = Sunday wrap-up;
//     q = quiet hours (start/end "HH:MM", phone's time zone tz); seen = last time the app was opened.
//     KV metadata: {u: user, n: teams, t: "team,keys", tz} so the 5-minute check can skip most reads.
//   st:<site> -> one small state record written only when something changed:
//     {last: last alerts run handled, held: {device: [{c, t, kind, at}]}, ll: {"device|team": ms},
//      rem: {"device|game": ms} reminders sent, wrap: {device: "Sunday date"} wrap-ups sent, sent: {week: n}}
// Where the changes come from: site/data/alerts.json, written by scripts/alerts.py on each data update.
import {send as sendRaw, vapid, apnsSend, APNS_TOPICS} from "./push.js";
import {wrapLine} from "./pickem.js";
import {dbDevice} from "./log.js";

// Every notification sent is logged (kind, who, what, push service status).
let LOG = null;
export const setLog = l => { LOG = l; };
async function send(env, sub, msg, kind = "alert", d = null) {
  let s, why = "";
  try {
    if (sub.apns) { const r = await sendApp(env, sub, msg); s = r.status; why = r.reason; }
    else s = await sendRaw(env, sub, msg);
  } catch (e) { s = 0; why = String(e); LOG && LOG.error("push.error", {kind, uid: d && d.uid, app: !!sub.apns, title: msg.t, msg: String(e)}); }
  LOG && LOG.keep("push", Object.assign({kind, uid: d && d.uid, title: msg.t, body: String(msg.b || "").slice(0, 240), status: s}, sub.apns ? {app: true, reason: why} : {}));
  return s;
}
// App Store app: Apple push, plus the device's inbox (last 60 alerts) and red-number count kept here,
// because the app has no service worker receiving the alerts.
//   ib:<site>:<device id> -> {items: [{id, t, b, x, u, at, read}]}. The red number = unread items in this list.
const ibKey = (env, id) => `ib:${site(env)}:${id}`;
async function sendApp(env, sub, msg) {
  const id = await devId(sub.endpoint), ik = ibKey(env, id);
  const ib = await env.USERS.get(ik, "json") || {bc: 0, items: []};
  const nid = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const counts = msg.badge !== false, bc = (ib.items || []).filter(x => !x.read).length + 1;
  const aps = {alert: {title: msg.t || "Sideline Standings", body: String(msg.b || "").slice(0, 1500)}, sound: "default", "thread-id": "sideline"};
  if (counts) aps.badge = bc;
  const r = await apnsSend(env, sub.apns, {aps, u: msg.u || "/", id: nid}, {collapse: msg.tag, topic: sub.topic});
  if (r.status === 200) {
    ib.items = [{id: nid, t: msg.t || "Sideline Standings", b: msg.b || "", x: msg.x || null, u: msg.u || "/", at: Date.now(), read: false}, ...(ib.items || [])].slice(0, 60);
    await env.USERS.put(ik, JSON.stringify(ib), {expirationTtl: 90 * 86400});
    return {status: 201, reason: ""};
  }
  return r;
}

const HOUR = 3600e3;
const DEF_Q = {on: true, s: "22:00", e: "07:00"};
const site = env => env.SITE === "live" ? "live" : "uat";
const devKey = (env, id) => `d:${site(env)}:${id}`;
export async function devId(endpoint) {
  const h = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint)));
  return [...h.slice(0, 12)].map(b => b.toString(16).padStart(2, "0")).join("");
}
const isApp = e => typeof e === "string" && /^apns:[0-9a-f]{32,200}$/i.test(e);   // Capacitor gives the token in capitals
const okEndpoint = e => isApp(e) || (typeof e === "string" && e.length < 1000 && /^https:\/\/[a-z0-9.-]+(:\d+)?\//i.test(e));
const hhmm = s => typeof s === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(s) ? s : null;
function cleanDevice(b) {
  const sub = b && b.sub;
  const app = sub && isApp(sub.endpoint);
  if (!sub || !okEndpoint(sub.endpoint) || (!app && !sub.keys) || (!app && typeof sub.keys.p256dh !== "string") || (!app && typeof sub.keys.auth !== "string")) return null;
  const teams = (Array.isArray(b.teams) ? b.teams : []).filter(t => t && /^[a-z0-9-]{3,40}$/.test(t.k)).slice(0, 60).map(t => ({
    k: t.k, f: typeof t.f === "string" && /^[a-z0-9-]{3,60}$/.test(t.f) ? t.f : "",
    n: String(t.n || "").slice(0, 40), a: String(t.a || "").slice(0, 20), our: t.our !== false,
    lg: t.lg === "off" ? "off" : t.lg === "near" ? "near" : "all", mo: t.mo !== false,
    rem: t.rem === "am" || t.rem === "off" ? t.rem : "2h", wr: t.wr !== false}));
  const q = b.q || {};
  let tz = typeof b.tz === "string" && b.tz.length < 60 ? b.tz : "America/Los_Angeles";
  try { new Intl.DateTimeFormat("en-US", {timeZone: tz}); } catch (e) { tz = "America/Los_Angeles"; }
  return {sub: app ? Object.assign({endpoint: sub.endpoint, apns: sub.endpoint.slice(5).toLowerCase()}, APNS_TOPICS.includes(sub.topic) ? {topic: sub.topic} : {}) : {endpoint: sub.endpoint, keys: {p256dh: sub.keys.p256dh.slice(0, 200), auth: sub.keys.auth.slice(0, 100)}},
    teams, q: {on: q.on !== false, s: hhmm(q.s) || DEF_Q.s, e: hhmm(q.e) || DEF_Q.e}, tz, badge: b.badge !== false};
}

// ---------- the page's calls (signed in) ----------
export async function route(p, req, env, c, json) {
  if (p === "/api/push/key" && req.method === "GET") return json({key: (await vapid(env)).pub});
  let body = {}; if (req.method !== "GET") { try { body = await req.json(); } catch (e) {} }
  const ep = req.method === "GET" ? new URL(req.url).searchParams.get("endpoint") : (body.endpoint || (body.sub && body.sub.endpoint));
  if (!okEndpoint(ep)) { LOG && LOG.error("alerts.nodevice", {uid: c.sub, p, start: String(ep || "").slice(0, 6), len: String(ep || "").length}); return json({error: "no device"}, 400); }
  const id = await devId(ep), key = devKey(env, id);
  if (p === "/api/push" && req.method === "GET") {
    const d = await env.USERS.get(key, "json");
    return json(d && d.uid === c.sub ? {on: true, teams: d.teams, q: d.q, badge: d.badge} : {on: false});
  }
  if (p === "/api/push" && req.method === "PUT") {
    const d = cleanDevice(body); if (!d) { LOG && LOG.error("alerts.bad", {uid: c.sub, kind: isApp(ep) ? "app" : "web", teams: Array.isArray(body.teams) ? body.teams.length : -1}); return json({error: "bad device"}, 400); }
    const old = await env.USERS.get(key, "json");
    const rec = Object.assign(d, {uid: c.sub, email: (c.email || "").toLowerCase(), seen: Date.now(), created: old && old.created || Date.now(), upd: Date.now()});
    await putDev(env, key, rec);
    if (LOG) (old ? LOG.info : LOG.keep).call(LOG, old ? "alerts.settings" : "alerts.on", {uid: c.sub, dev: id, teams: rec.teams.map(t => `${t.k}:${t.our ? "S" : ""}${t.lg !== "off" ? "L" : ""}${t.mo ? "M" : ""}${t.rem}${t.wr ? "W" : ""}`).join(" "), q: rec.q.on ? rec.q.s + "-" + rec.q.e : "off", badge: rec.badge, tz: rec.tz, service: rec.sub.apns ? "app" : new URL(rec.sub.endpoint).host});
    return json({ok: true});
  }
  // The app was opened (sent at most every few hours on weekends): the Sunday wrap-up skips people
  // who have already seen the weekend's results.
  if (p === "/api/push/seen" && req.method === "POST") {
    const d = await env.USERS.get(key, "json");
    if (!d || d.uid !== c.sub) return json({ok: false});
    if (Date.now() - (d.seen || 0) > HOUR) { d.seen = Date.now(); await putDev(env, key, d); LOG && LOG.info("alerts.seen", {uid: c.sub, dev: id}); }
    return json({ok: true});
  }
  // App Store app: its alert inbox, marking alerts read, and "the app was opened" (red number back to 0).
  if (p === "/api/push/inbox") {
    const d = await env.USERS.get(key, "json");
    if (!d || d.uid !== c.sub) return json({items: []});
    const ik = ibKey(env, id), ib = await env.USERS.get(ik, "json") || {bc: 0, items: []};
    const unread = () => (ib.items || []).filter(x => !x.read).length;
    if (req.method === "GET") return json({items: ib.items || [], unread: unread()});
    let ch = false;
    const ids = body.read === "all" ? (ib.items || []).map(x => x.id) : Array.isArray(body.read) ? body.read : [];
    (ib.items || []).forEach(x => { if (ids.includes(x.id) && !x.read) { x.read = true; ch = true; } });
    if (ch) await env.USERS.put(ik, JSON.stringify(ib), {expirationTtl: 90 * 86400});
    return json({ok: true, unread: unread()});
  }
  if (p === "/api/push" && req.method === "DELETE") {
    const d = await env.USERS.get(key, "json");
    if (d && d.uid === c.sub) { (dbDevice(env, null, key.split(":")[2], null), await env.USERS.delete(key), await env.USERS.delete(ibKey(env, id))); LOG && LOG.keep("alerts.off", {uid: c.sub, dev: id}); }
    return json({ok: true});
  }
  if (p === "/api/push/test" && req.method === "POST") {
    const d = await env.USERS.get(key, "json");
    if (!d || d.uid !== c.sub) return json({error: "alerts not on for this device"}, 404);
    const t = d.teams[0];
    const st = await send(env, d.sub, {t: "Test alert", b: "Alerts are on. You'll get Sideline Standings alerts on this device.",
      u: "/" + (t ? "#t=" + t.k : ""), tag: "test", badge: d.badge}, "test", d);
    if (st === 404 || st === 410) { (dbDevice(env, null, key.split(":")[2], null), await env.USERS.delete(key)); return json({error: "gone"}, 410); }
    return json({ok: st >= 200 && st < 300, status: st});
  }
  return json({error: "not found"}, 404);
}

const putDev = (env, key, rec) => { dbDevice(env, null, key.split(":")[2], rec); return env.USERS.put(key, JSON.stringify(rec), {metadata: {u: rec.uid, n: rec.teams.length,
  t: rec.teams.slice(0, 50).map(t => t.k).join(","), tz: rec.tz}}); };
// All device keys + metadata for this site.
async function deviceMeta(env) {
  const out = []; let cursor;
  do {
    const r = await env.USERS.list({prefix: `d:${site(env)}:`, cursor, limit: 1000});
    out.push(...r.keys);
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return out;
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
    for (const k of await devices(e, uid)) (dbDevice(e, null, k.split(":")[2], null), await env.USERS.delete(k), await env.USERS.delete(`ib:${s}:${k.split(":")[2]}`));
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
// A short alert to the owner's own devices (e.g. a Pick'em name was reported). Ignores quiet hours.
export async function notifyOwner(env, uid, t, b) {
  let n = 0;
  for (const k of await devices(env, uid)) {
    const d = await env.USERS.get(k, "json"); if (!d) continue;
    const s = await send(env, d.sub, {t, b, u: "/#admin", tag: "owner-" + Date.now(), badge: d.badge}, "owner", d);
    if (s < 300) n++;
  }
  return n;
}
export async function testOwner(env, uid) {
  let n = 0;
  for (const k of await devices(env, uid)) {
    const d = await env.USERS.get(k, "json"); if (!d) continue;
    const s = await send(env, d.sub, {t: "Admin test", b: "Test alert to every device you've turned alerts on.", u: "/", tag: "test", badge: d.badge}, "admin-test", d);
    if (s === 404 || s === 410) (dbDevice(env, null, k.split(":")[2], null), await env.USERS.delete(k)); else if (s < 300) n++;
  }
  return n;
}

// Owner test: last weekend's real results, sent to the owner's own devices exactly as alerts would
// compose them (per team, combined, with "Replay:" in front). Ignores quiet hours and hourly limits.
export async function replayOwner(env, uid) {
  const r = await env.ASSETS.fetch(new Request("https://assets.local/data/replay.json"));
  if (!r.ok) return {sent: 0, note: "no replay file yet"};
  const rp = await r.json();
  let sent = 0, notes = 0;
  for (const k of await devices(env, uid)) {
    const d = await env.USERS.get(k, "json"); if (!d) continue;
    const out = compose(d, match(d, rp.c || [])).slice(0, 8);
    notes += out.length;
    for (const n of out) {
      const s = await send(env, d.sub, Object.assign(n, {t: "Replay: " + n.t, tag: "replay-" + n.tag, badge: d.badge}), "replay", d);
      if (s < 300) sent++;
    }
  }
  return {sent, notes, from: rp.from, to: rp.to, games: (rp.c || []).length};
}

// ---------- the check (every 5 minutes) ----------
const weekKey = ms => { const d = new Date(ms); d.setUTCHours(0, 0, 0, 0); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10); };
function localHM(tz, ms) {
  const p = new Intl.DateTimeFormat("en-US", {timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).formatToParts(new Date(ms));
  const h = p.find(x => x.type === "hour").value, m = p.find(x => x.type === "minute").value;
  return `${h === "24" ? "00" : h}:${m}`;
}
function tzOffset(tz, ms) {
  const p = new Intl.DateTimeFormat("en-US", {timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"}).formatToParts(new Date(ms));
  const g = t => +p.find(x => x.type === t).value;
  return Date.UTC(g("year"), g("month") - 1, g("day"), g("hour") % 24, g("minute"), g("second")) - Math.floor(ms / 1000) * 1000;
}
// A wall-clock date + time in a time zone -> ms.
export function zonedMs(date, time, tz) {
  const [y, m, d] = date.split("-").map(Number), [hh, mm] = time.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm), off = tzOffset(tz, guess);
  let t = guess - off; const off2 = tzOffset(tz, t); if (off2 !== off) t = guess - off2;
  return t;
}
function localParts(tz, ms) {
  const p = new Intl.DateTimeFormat("en-US", {timeZone: tz, hourCycle: "h23", weekday: "short", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit"}).formatToParts(new Date(ms));
  const g = t => p.find(x => x.type === t).value;
  return {day: g("weekday"), date: `${g("year")}-${g("month")}-${g("day")}`, hour: +g("hour") % 24};
}
const time12 = t => { if (!t || t === "00:00") return "Time TBD"; const [h, m] = t.split(":").map(Number); return `${(h % 12) || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };
const ordn = n => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");
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
  for (const it of items) { if (!byTeam.has(it.t)) byTeam.set(it.t, {our: [], lg: [], mo: []}); byTeam.get(it.t)[it.kind].push(it.kind === "mo" ? it.text : it.c); }
  const notes = [];
  for (const [k, g] of byTeam) {
    if (!g.our.length && !g.lg.length) continue;   // big moments never go out on their own
    const mo = [...new Set(g.mo)].map(x => "Big moment: " + x);
    const team = d.teams.find(t => t.k === k) || {k, n: ""};
    const conf = (g.lg[0] || g.our[0] || {}).cn || "the league";
    const also = g.lg.length ? `${plural(g.lg.length, "new result")} in ${conf}` : "";
    if (g.our.length === 1) {
      const o = ourLine(g.our[0], k);
      const x = [`Final · ${o.res}${o.fix}`].concat(mo, g.lg.length ? ["", `Also in ${conf}:`].concat(g.lg.map(resLine)) : []);
      notes.push({t: o.line, b: [`Final · ${o.res}${o.fix}`].concat(mo, also ? ["Also " + also] : []).join("\n"), x, u: `/#t=${k}&g=${g.our[0].g}&v=games`, tag: "g" + g.our[0].g});
    } else if (g.our.length > 1) {
      const lines = g.our.map(c => { const o = ourLine(c, k); return `${o.line}${o.fix}`; });
      const x = lines.concat(mo, g.lg.length ? ["", `Also in ${conf}:`].concat(g.lg.map(resLine)) : []);
      notes.push({t: `${team.n || ourLine(g.our[0], k).us}: ${plural(g.our.length, "new result")}`, b: lines.concat(mo, also ? ["Also " + also] : []).join("\n"), x, u: `/#t=${k}&g=${g.our.map(c => c.g).join(",")}&v=games`, tag: "t" + k});
    } else {
      const shown = g.lg.slice(0, 3).map(resLine), more = g.lg.length - shown.length;
      notes.push({t: `${plural(g.lg.length, "new result")} in ${conf}`, b: mo.concat(shown).join("\n") + (more > 0 ? `\n+${more} more` : ""), x: mo.concat(g.lg.map(resLine)), u: `/#t=${k}&g=${g.lg.map(c => c.g).join(",")}&v=league`, tag: "l" + k});
    }
  }
  if (overnight && notes.length > 1) {   // morning summary: one notification for everything held overnight
    return [{t: "Overnight results", b: notes.map(n => n.t).join("\n"), x: notes.flatMap(n => [n.t].concat(n.x || [n.b], [""])), u: notes[0].u, tag: "overnight"}];
  }
  if (overnight && notes.length === 1) notes[0].t = "Overnight: " + notes[0].t;
  for (const n of notes) if (n.x && n.x.length > 40) n.x = n.x.slice(0, 39).concat([`+${n.x.length - 39} more`]);   // push messages are capped at 4 KB
  return notes;
}

// Which changes this device should hear about (each game once per device; our game beats league).
export function match(d, changes, moments = {}, pos = {}) {
  const items = [], used = new Set();
  for (const c of changes) {
    const ours = d.teams.find(t => t.our && (t.k === c.h || t.k === c.a));
    if (ours) { items.push({c, t: ours.k, kind: "our"}); used.add(c.g); }
  }
  for (const c of changes) {
    if (used.has(c.g) || !c.cf) continue;
    if (d.teams.some(t => t.k === c.h || t.k === c.a)) continue;   // our team's game with alerts off for it
    const P = pos[c.cf] || {};
    const near = x => { const me = P[x.k]; return me && [P[c.h], P[c.a]].some(q => q && Math.abs(q - me) <= 2); };
    const t = d.teams.find(x => x.f === c.cf && (x.lg === "all" || (x.lg === "near" && near(x))));
    if (t) { items.push({c, t: t.k, kind: "lg"}); used.add(c.g); }
  }
  // big moments ride along on that team's score alert only (never on their own)
  const has = new Set(items.map(i => i.t));
  for (const t of d.teams) if (t.mo && moments[t.k] && has.has(t.k)) for (const text of moments[t.k]) items.push({t: t.k, kind: "mo", text});
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
  st.held = st.held || {}; st.ll = st.ll || {}; st.sent = st.sent || {}; st.rem = st.rem || {}; st.wrap = st.wrap || {};
  const due = Object.keys(st.held).filter(id => st.held[id].some(h => (h.at || 0) <= now));
  let sent = 0, gone = 0;
  const out = {runs: fresh.length};
  if (fresh.length || due.length) Object.assign(out, await scores(env, st, fresh, due, now, n => sent += n, () => gone++));
  try { out.reminders = await reminders(env, st, data.up || [], now); sent += out.reminders; } catch (e) { out.remErr = String(e); }
  try { out.wrapups = await wrapups(env, st, data.wk || {}, now); sent += out.wrapups; } catch (e) { out.wrapErr = String(e); }
  try { out.drift = await driftAlert(env, st, now); sent += out.drift; } catch (e) { out.driftErr = String(e); }
  // tidy: forget hourly timers older than a day, reminders older than 2 days, wrap-ups older than 3 weeks; keep 8 weeks of counts
  for (const k of Object.keys(st.ll)) if (now - st.ll[k] > 24 * HOUR) delete st.ll[k];
  for (const k of Object.keys(st.rem)) if (now - st.rem[k] > 48 * HOUR) delete st.rem[k];
  for (const k of Object.keys(st.wrap)) if (now - Date.parse(st.wrap[k] + "T12:00:00Z") > 21 * 24 * HOUR) delete st.wrap[k];
  const wk = weekKey(now); if (sent) st.sent[wk] = (st.sent[wk] || 0) + sent;
  for (const k of Object.keys(st.sent).sort().slice(0, -8)) delete st.sent[k];
  if (fresh.length) st.last = fresh[fresh.length - 1].id;
  // write only when something changed (a quiet night re-checks held alerts without writing)
  if (JSON.stringify(Object.assign({}, st, {checked: 0})) !== before) { st.checked = now; await env.USERS.put(sk, JSON.stringify(st)); }
  return Object.assign(out, {sent, gone});
}

// New and corrected scores (+ big moments) for every device that follows those teams or leagues.
async function scores(env, st, fresh, due, now, addSent, addGone) {
  const changes = fresh.flatMap(r => r.c || []);
  const moments = {}, pos = {};
  for (const r of fresh) {
    for (const [k, v] of Object.entries(r.m || {})) (moments[k] = moments[k] || []).push(...v);
    Object.assign(pos, r.pos || {});
  }
  const ids = new Set(due);
  let keys = [];
  if (changes.length) keys = await devices(env);
  else keys = due.map(id => devKey(env, id));
  let sent = 0, gone = 0;
  for (const key of keys) {
    const id = key.split(":")[2], d = await env.USERS.get(key, "json");
    if (!d) { delete st.held[id]; continue; }
    const items = changes.length ? match(d, changes, moments, pos) : [];
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
        if (it.kind !== "our" && !ourTeam && !overnight && now - last < HOUR) keep.push(Object.assign(it, {at: last + HOUR}));
        else out.push(it);
      }
    }
    if (keep.length) st.held[id] = keep.slice(-200); else delete st.held[id];
    if (!out.length) continue;
    for (const n of compose(d, out, overnight)) {
      const s = await send(env, d.sub, Object.assign(n, {badge: d.badge}), overnight ? "overnight" : "score", d);
      if (s === 404 || s === 410) { (dbDevice(env, null, key.split(":")[2], null), await env.USERS.delete(key)); delete st.held[id]; gone++; break; }
      if (s < 300) sent++;
    }
    for (const t of new Set(out.map(i => i.t))) st.ll[id + "|" + t] = now;
  }
  addSent(sent); for (let i = 0; i < gone; i++) addGone();
  return {changes: changes.length};
}

// Daily drift check: when our table's games played / points don't match ECNL's for a conference,
// tell the owner (only when the list of problems changes, at most once every 20 hours).
const OWNER_EMAILS = ["grahamcomley@gmail.com"];
async function driftAlert(env, st, now) {
  const r = await env.ASSETS.fetch(new Request("https://assets.local/data/drift.json"));
  if (!r.ok) return 0;
  const dr = await r.json(), probs = dr.points || [];
  const sig = probs.map(p => p.conf + ":" + p.teams.map(t => t.id + "=" + t.ours.join("/") + "~" + t.ecnl.join("/")).join(",")).sort().join("|");
  const prev = st.drift || {};
  if (sig === (prev.sig || "") || (prev.at && now - prev.at < 20 * HOUR && prev.sig)) { if (!sig) st.drift = {sig: "", at: prev.at || 0}; return 0; }
  st.drift = {sig, at: now};
  // Logged only (Claude reads the logs); no alert to the owner (Graham, 2026-11-11).
  LOG && LOG.keep("drift", {conferences: probs.length, list: probs.slice(0, 20).map(p => `${p.name}: ` + p.teams.slice(0, 4).map(t => `${t.team} ${t.ours.join("/")} vs ${t.ecnl.join("/")}`).join("; "))});
  return 0;
}

// Game-day reminders: "morning of" (8 AM, or when quiet hours end) or 2 hours before kickoff.
// Game times are the field's local time; we read them in the phone's time zone.
async function reminders(env, st, up, now) {
  if (!up.length) return 0;
  const pt = localParts("America/Los_Angeles", now);
  const soon = up.some(g => { if (!g[7] || g[7] === "00:00") return false; const k = zonedMs(g[6], g[7], "America/Los_Angeles"); return k > now && k - now < 4 * HOUR; });
  const morning = pt.hour >= 5 && pt.hour < 13 && up.some(g => g[6] === pt.date);
  if (!soon && !morning) return 0;   // nothing could be due: skip listing devices
  const byTeam = new Map();
  for (const g of up) for (const k of [g[2], g[3]]) { if (!byTeam.has(k)) byTeam.set(k, []); byTeam.get(k).push(g); }
  let n = 0;
  for (const m of await deviceMeta(env)) {
    const tk = ((m.metadata || {}).t || "").split(",").filter(k => byTeam.has(k));
    if (!tk.length) continue;
    const id = m.name.split(":")[2], d = await env.USERS.get(m.name, "json");
    if (!d) continue;
    const tz = d.tz || "America/Los_Angeles";
    for (const t of d.teams) {
      if (t.rem === "off" || !byTeam.has(t.k)) continue;
      for (const g of byTeam.get(t.k)) {
        const key = id + "|" + g[0]; if (st.rem[key]) continue;
        const timed = g[7] && g[7] !== "00:00", kick = timed ? zonedMs(g[6], g[7], tz) : zonedMs(g[6], "20:00", tz);
        const target = t.rem === "2h" && timed ? kick - 2 * HOUR : zonedMs(g[6], "08:00", tz);
        if (now < target || now >= kick || quiet(d, now)) continue;
        const home = g[2] === t.k, us = home ? g[4] : g[5], them = home ? g[5] : g[4];
        const title = (t.rem === "2h" && timed ? "In 2 hours: " : "Game day: ") + `${us} ${home ? "vs" : "@"} ${them}`;
        const s = await send(env, d.sub, {t: title, b: [time12(g[7]), g[8]].filter(Boolean).join(" · "), u: `/#t=${t.k}&g=${g[0]}&v=games`, tag: "r" + g[0], badge: d.badge}, "reminder", d);
        st.rem[key] = now;
        if (s === 404 || s === 410) { (dbDevice(env, null, m.name.split(":")[2], null), await env.USERS.delete(m.name)); break; }
        if (s < 300) n++;
      }
    }
  }
  return n;
}

// Sunday-night wrap-up at 7 PM on the phone's clock: only if their teams played this weekend and the
// person hasn't opened the app since the last of those results.
async function wrapups(env, st, wk, now) {
  if (!Object.keys(wk).length) return 0;
  const u = new Date(now), day = u.getUTCDay(), h = u.getUTCHours();
  if (!((day === 0 && h >= 16) || (day === 1 && h < 10))) return 0;   // Sunday evening somewhere in the US
  let n = 0;
  for (const m of await deviceMeta(env)) {
    const meta = m.metadata || {}, id = m.name.split(":")[2], tz = meta.tz || "America/Los_Angeles";
    const L = localParts(tz, now);
    if (L.day !== "Sun" || L.hour < 19 || L.hour > 22 || st.wrap[id] === L.date) continue;
    if (!(meta.t || "").split(",").some(k => wk[k])) { st.wrap[id] = L.date; continue; }
    const d = await env.USERS.get(m.name, "json");
    if (!d) continue;
    const mine = d.teams.filter(t => t.wr && wk[t.k]);
    if (!mine.length) { st.wrap[id] = L.date; continue; }
    const latest = Math.max(...mine.map(t => Date.parse(wk[t.k][3]) || 0));
    if (d.seen && d.seen > latest) { st.wrap[id] = L.date; continue; }   // already looked
    if (quiet(d, now)) continue;
    const lines = mine.map(t => {
      const [place, of, , , res] = wk[t.k];
      const r = res.map(([opp, a, b]) => `${a > b ? "W" : a < b ? "L" : "D"} ${a}${dash}${b} ${opp}`).join(", ");
      return `${t.a ? t.a + " " : ""}${t.n}: ${r}${place ? ` · ${ordn(place)} of ${of}` : ""}`;
    });
    try { const fri = new Date(Date.parse(L.date + "T12:00:00Z") - 2 * 864e5).toISOString().slice(0, 10); const pl = await wrapLine(env, d.uid, fri, L.date); if (pl) lines.push(pl); } catch (e) {}
    const s = await send(env, d.sub, {t: "Weekend wrap-up", b: lines.join("\n"), x: lines, u: `/#t=${mine[0].k}&v=games`, tag: "wrap", badge: d.badge}, "wrapup", d);
    st.wrap[id] = L.date;
    if (s === 404 || s === 410) { (dbDevice(env, null, m.name.split(":")[2], null), await env.USERS.delete(m.name)); continue; }
    if (s < 300) n++;
  }
  return n;
}

