// Game weather (Graham, Nov 24): one forecast per field location, fetched by this server from Apple Weather
// (WeatherKit REST API) and shared by every user, so everyone sees the same forecast for a time and field.
//
// Which locations: site/data/wxneed.json from the data run {zip: [lat, lon, first game date, last game date, tz]}
// (unplayed games in the next 10 days with a known field ZIP). Refresh: hourly once a location's first game is
// within 48 hours, every 6 hours before that; a few locations per 5-minute timer run, most overdue first.
// Stored in KV (shared by prod and UAT, so a location is fetched once for both):
//   wx:<zip>  {at, tz, d: {date: [high°F, low°F, rain %, condition]}, h: {"YYYY-MM-DDTHH" local: [°F, feels °F, rain %, mph, wind from °, condition]}}
//   wx:idx    {zip: last fetch ms}
//   wx:attr   Apple's required attribution {dark, light, legal, at}
// Apple's key: KV cfg:wxkey {p8, kid, sid} pasted by the owner in Admin (WeatherKit key + Services ID).
// Read by the page through GET /api/wx?z=98188,92130 (no sign-in; public forecasts only).
import {apnsKey, APNS_TEAM} from "./push.js";

const te = new TextEncoder();
const b64u = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const PER_RUN = 20, HOUR = 3600e3;
let KEY = null;

async function token(env) {
  const c = await env.USERS.get("cfg:wxkey", "json");
  if (!c || !c.p8 || !c.kid || !c.sid) return null;
  const now = Math.floor(Date.now() / 1000);
  if (KEY && KEY.kid === c.kid && KEY.sid === c.sid && now - KEY.iat < 1800) return KEY.jwt;
  const key = await apnsKey(c.p8);
  const head = b64u(te.encode(JSON.stringify({alg: "ES256", kid: c.kid, id: `${APNS_TEAM}.${c.sid}`})));
  const body = b64u(te.encode(JSON.stringify({iss: APNS_TEAM, iat: now, exp: now + 3600, sub: c.sid})));
  const sig = await crypto.subtle.sign({name: "ECDSA", hash: "SHA-256"}, key, te.encode(head + "." + body));
  KEY = {kid: c.kid, sid: c.sid, iat: now, jwt: `${head}.${body}.${b64u(sig)}`};
  return KEY.jwt;
}

const F = c => Math.round(c * 9 / 5 + 32), MPH = k => Math.round(k * 0.621371), PCT = x => Math.round((x || 0) * 100);
function localHour(iso, tz) {   // "YYYY-MM-DDTHH" in the field's zone
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23"}).formatToParts(new Date(iso)).map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}`;
}
export function compact(w, tz, first, last) {
  const out = {at: Date.now(), tz, d: {}, h: {}};
  for (const d of (w.forecastDaily || {}).days || []) {
    const date = localHour(d.forecastStart, tz).slice(0, 10);
    if (date < first || date > last) continue;
    out.d[date] = [F(d.temperatureMax), F(d.temperatureMin), PCT(d.precipitationChance), d.conditionCode];
  }
  for (const h of (w.forecastHourly || {}).hours || []) {
    const k = localHour(h.forecastStart, tz);
    if (k.slice(0, 10) < first || k.slice(0, 10) > last) continue;
    out.h[k] = [F(h.temperature), F(h.temperatureApparent), PCT(h.precipitationChance), MPH(h.windSpeed), Math.round(h.windDirection || 0), h.conditionCode];
  }
  return out;
}

async function fetchOne(env, jwt, lat, lon, tz, first, last) {
  const now = new Date(), end = new Date(Math.min(now.getTime() + 239 * HOUR, Date.parse(last + "T23:59:59Z") + 14 * HOUR));
  const q = new URLSearchParams({dataSets: "forecastDaily,forecastHourly", timezone: tz, countryCode: "US", hourlyStart: now.toISOString(), hourlyEnd: end.toISOString()});
  const r = await fetch(`https://weatherkit.apple.com/api/v1/weather/en/${lat}/${lon}?${q}`, {headers: {authorization: "Bearer " + jwt}});
  if (!r.ok) throw new Error("weatherkit " + r.status);
  return compact(await r.json(), tz, first, last);
}

// One timer run: refresh the most overdue locations (at most PER_RUN). Returns {due, fetched, failed}.
export async function wxRefresh(env, now = Date.now()) {
  const jwt = await token(env); if (!jwt) return {off: "no key"};
  let need = {};
  try { const r = await env.ASSETS.fetch(new Request("https://assets.local/data/wxneed.json")); if (r.ok) need = await r.json(); } catch (e) {}
  const idx = (await env.USERS.get("wx:idx", "json")) || {};
  const soon = new Date(now + 2 * 86400e3).toISOString().slice(0, 10);
  const due = Object.entries(need).map(([z, n]) => ({z, n, every: n[2] <= soon ? HOUR : 6 * HOUR, last: idx[z] || 0}))
    .filter(x => now - x.last >= x.every - 5 * 60e3).sort((a, b) => (now - b.last) / b.every - (now - a.last) / a.every);
  let fetched = 0, failed = 0;
  for (const x of due.slice(0, PER_RUN)) {
    const [lat, lon, first, last, tz] = x.n;
    try {
      const w = await fetchOne(env, jwt, lat, lon, tz || "America/Los_Angeles", first, last);
      await env.USERS.put("wx:" + x.z, JSON.stringify(w), {expirationTtl: 12 * 86400});
      idx[x.z] = now; fetched++;
    } catch (e) { failed++; if (failed >= 3) break; }   // Apple not answering: try again next run
  }
  for (const z of Object.keys(idx)) if (!need[z] && now - idx[z] > 2 * 86400e3) delete idx[z];
  if (fetched || failed) await env.USERS.put("wx:idx", JSON.stringify(idx));
  await attribution(env, jwt, now);
  return {locations: Object.keys(need).length, due: due.length, fetched, failed};
}

async function attribution(env, jwt, now) {
  const a = await env.USERS.get("wx:attr", "json");
  if (a && now - a.at < 86400e3) return a;
  try {
    const r = await fetch("https://weatherkit.apple.com/attribution/en", {headers: {authorization: "Bearer " + jwt}});
    if (!r.ok) return a;
    const j = await r.json(), abs = u => u && (u.startsWith("http") ? u : "https://weatherkit.apple.com" + u);
    const v = {dark: abs(j.logoDark1x || j.logoDark2x), light: abs(j.logoLight1x || j.logoLight2x), dark2: abs(j.logoDark2x), light2: abs(j.logoLight2x),
      legal: j.legalPageURL || "https://developer.apple.com/weatherkit/data-source-attribution/", name: j.serviceName || "Weather", at: now};
    await env.USERS.put("wx:attr", JSON.stringify(v));
    return v;
  } catch (e) { return a; }
}

// GET /api/wx?z=98188,92130 → {attr, z: {zip: wx}}. Public: forecasts only.
export async function wxRoute(env, url) {
  const zs = [...new Set((url.searchParams.get("z") || "").split(",").map(s => s.trim()).filter(s => /^\d{5}$/.test(s)))].slice(0, 40);
  const z = {};
  await Promise.all(zs.map(async k => { const v = await env.USERS.get("wx:" + k, "json"); if (v) z[k] = v; }));
  const attr = await env.USERS.get("wx:attr", "json");
  return new Response(JSON.stringify({attr, z}), {headers: {"content-type": "application/json", "cache-control": "public, max-age=300"}});
}

// Admin: GET → saved?; PUT {p8, kid, sid} checks the key opens, then tries one real forecast (Seattle).
export async function wxAdmin(env, req) {
  if (req.method === "GET") { const k = await env.USERS.get("cfg:wxkey", "json"); return {saved: !!(k && k.p8), kid: k ? k.kid : "", sid: k ? k.sid : "", at: k ? k.at : 0, chk: k ? k.chk : null}; }
  let b = {}; try { b = await req.json(); } catch (e) {}
  const p8 = String(b.p8 || "").trim(), kid = String(b.kid || "").trim().toUpperCase(), sid = String(b.sid || "").trim();
  if (!/^[A-Z0-9]{10}$/.test(kid)) return {error: "The Key ID is the 10 letters and numbers next to the key in Apple's list."};
  if (!/^[A-Za-z0-9.-]{3,}$/.test(sid)) return {error: "The Services ID looks like com.sidelinestandings.weather."};
  try { await apnsKey(p8); } catch (e) { return {error: "That doesn't look like the .p8 key file's contents. Open the file and copy everything, including the BEGIN and END lines."}; }
  const rec = {p8, kid, sid, at: Date.now()};
  await env.USERS.put("cfg:wxkey", JSON.stringify(rec));
  KEY = null;
  let chk;
  try { const jwt = await token(env); const t = new Date().toISOString().slice(0, 10); const w = await fetchOne(env, jwt, 47.61, -122.33, "America/Los_Angeles", t, t); chk = {ok: true, hours: Object.keys(w.h).length}; }
  catch (e) { chk = {ok: false, msg: String(e && e.message || e)}; }
  rec.chk = chk; await env.USERS.put("cfg:wxkey", JSON.stringify(rec));
  await env.USERS.delete("wx:attr");
  return {ok: true, chk};
}
