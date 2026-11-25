import {compact, wxRefresh, wxRoute, wxAdmin} from "./weather.js";
let pass = 0, fail = 0; const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log((c ? "PASS " : "FAIL ") + n, c ? "" : JSON.stringify(d)); };
// compact
const w = {forecastDaily: {days: [{forecastStart: "2026-11-21T07:00:00Z", temperatureMax: 21, temperatureMin: 11, precipitationChance: 0.6, conditionCode: "Rain"},
  {forecastStart: "2026-12-10T07:00:00Z", temperatureMax: 5, temperatureMin: 1, precipitationChance: 0, conditionCode: "Clear"}]},
  forecastHourly: {hours: [{forecastStart: "2026-11-20T15:00:00Z", temperature: 17.8, temperatureApparent: 16.7, precipitationChance: 0.05, windSpeed: 9.7, windDirection: 200, conditionCode: "MostlyClear"}]}};
const c = compact(w, "America/Phoenix", "2026-11-20", "2026-11-22");
ok("daily in °F with rain %", JSON.stringify(c.d["2026-11-21"]) === JSON.stringify([70, 52, 60, "Rain"]), c.d);
ok("days outside the game window dropped", !c.d["2026-12-10"]);
ok("hourly keyed by field-local hour", JSON.stringify(c.h["2026-11-20T08"]) === JSON.stringify([64, 62, 5, 6, 200, "MostlyClear"]), c.h);
// env
const kv = new Map(); const USERS = {get: async (k, t) => { const v = kv.get(k); return v == null ? null : t === "json" ? JSON.parse(v) : v; }, put: async (k, v) => kv.set(k, v), delete: async k => kv.delete(k)};
const now = Date.parse("2026-11-18T18:00:00Z");
const need = {"85001": [33.45, -112.07, "2026-11-19", "2026-11-22", "America/Phoenix"], "98012": [47.84, -122.2, "2026-11-25", "2026-11-26", "America/Los_Angeles"]};
const ASSETS = {fetch: async () => new Response(JSON.stringify(need))};
const env = {USERS, ASSETS};
let calls = []; let mode = "ok";
globalThis.fetch = async (u, o) => { calls.push(String(u)); if (mode === "down") return new Response("x", {status: 503});
  if (String(u).includes("/attribution/")) return new Response(JSON.stringify({"logoDark@1x": "/assets/dark.png", "logoDark@2x": "/assets/dark@2x.png", legalPageURL: "https://weatherkit.apple.com/legal-attribution.html", serviceName: "Weather"}));
  return new Response(JSON.stringify(w)); };
ok("no key: does nothing", (await wxRefresh(env, now)).off === "no key" && calls.length === 0);
// key: real EC P-256 key in PKCS8
const kp = await crypto.subtle.generateKey({name: "ECDSA", namedCurve: "P-256"}, true, ["sign", "verify"]);
const der = Buffer.from(await crypto.subtle.exportKey("pkcs8", kp.privateKey)).toString("base64");
const p8 = `-----BEGIN PRIVATE KEY-----\n${der.match(/.{1,64}/g).join("\n")}\n-----END PRIVATE KEY-----`;
const req = b => ({method: "PUT", json: async () => b});
ok("admin rejects bad Key ID", !!(await wxAdmin(env, req({p8, kid: "abc", sid: "com.x.weather"}))).error);
ok("admin rejects bad Services ID", !!(await wxAdmin(env, req({p8, kid: "ABCDE12345", sid: "a b"}))).error);
ok("admin rejects junk key", !!(await wxAdmin(env, req({p8: "nope", kid: "ABCDE12345", sid: "com.x.weather"}))).error);
calls = [];
const sv = await wxAdmin(env, req({p8, kid: "abcde12345", sid: "com.sidelinestandings.weather"}));
ok("admin saves and checks one real forecast", sv.ok && sv.chk.ok && calls.some(u => u.includes("/47.61/-122.33")), sv);
const g = await wxAdmin(env, {method: "GET"});
ok("admin GET shows saved, never the key", g.saved && g.kid === "ABCDE12345" && !("p8" in g), g);
// refresh
calls = [];
const r1 = await wxRefresh(env, now);
ok("first run fetches both locations", r1.fetched === 2 && kv.has("wx:85001") && kv.has("wx:98012"), r1);
const hdr = calls.find(u => u.includes("/33.45/-112.07"));
ok("asks for daily + hourly in the field's zone", hdr && hdr.includes("dataSets=forecastDaily%2CforecastHourly") && hdr.includes("timezone=America%2FPhoenix"), hdr);
ok("attribution stored with full logo URL", JSON.parse(kv.get("wx:attr")).dark === "https://weatherkit.apple.com/assets/dark.png");
calls = [];
const r2 = await wxRefresh(env, now + 30 * 60e3);
ok("30 min later: nothing due", r2.fetched === 0 && calls.length === 0, r2);
const r3 = await wxRefresh(env, now + 61 * 60e3);
ok("1 hour later: only the game within 48 h", r3.fetched === 1 && calls.some(u => u.includes("/33.45/")) && !calls.some(u => u.includes("/47.84/")), r3);
calls = [];
const r4 = await wxRefresh(env, now + 6 * 3600e3 + 60e3);
ok("6 hours later: the far one too", r4.fetched === 2, r4);
// failure keeps last forecast
const before = kv.get("wx:85001"); mode = "down";
const r5 = await wxRefresh(env, now + 8 * 3600e3);
ok("Apple down: keeps last forecast, counts failures", r5.failed >= 1 && kv.get("wx:85001") === before, r5);
mode = "ok";
// route
const rr = await (await wxRoute(env, new URL("https://x/api/wx?z=85001,98012,abc,85001"))).json();
ok("route returns requested ZIPs + attribution", Object.keys(rr.z).sort().join() === "85001,98012" && rr.attr.legal, Object.keys(rr.z));
console.log(`${pass}/${pass + fail}`);
