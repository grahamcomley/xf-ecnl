// Pick'em: each weekend (Fri-Sun), pick the score of every league game in your conference.
// 3 points for the exact score, 1 for the right result. Each game locks at kickoff. After a game
// locks, everyone in that conference can see everyone's picks for it.
//
// Storage (KV USERS, kept apart by SITE like alerts):
//   pk:<site>:<user> -> {name, hidden, picks: {conf file: {game id: [home, away, when]}}}
//   KV metadata: {n: name, h: hidden, f: "conf,files"} so a leaderboard reads only its players.
// Game times and scores come from the published conference files (data/conf/<file>.json).
const site = env => env.SITE === "live" ? "live" : "uat";
const pkKey = (env, uid) => `pk:${site(env)}:${uid}`;

// Game times are the field's local time; we don't know the field's zone, so we use the
// conference's region (unknown regions use Eastern, which locks earliest, never late).
const TZ = [[/Northwest|NorCal|Northern Cal|Southern Cal|SoCal|Far West|Golden State|Nevada|Pacific/i, "America/Los_Angeles"],
  [/Southwest|Arizona/i, "America/Phoenix"], [/Mountain|Rocky|Utah|Colorado/i, "America/Denver"],
  [/Texas|STXCL|Frontier|Gulf Coast|Heartland|Midwest|Chicago|Lake Michigan|Mid-America|Twin Cities|Minnesota|Iowa|Missouri|Oklahoma/i, "America/Chicago"]];
export const confTz = name => (TZ.find(([re]) => re.test(name || "")) || [0, "America/New_York"])[1];
function tzOffset(tz, ms) {
  const p = new Intl.DateTimeFormat("en-US", {timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"}).formatToParts(new Date(ms));
  const g = t => +p.find(x => x.type === t).value;
  return Date.UTC(g("year"), g("month") - 1, g("day"), g("hour") % 24, g("minute"), g("second")) - Math.floor(ms / 1000) * 1000;
}
export function kickoff(g, tz) {
  const [y, m, d] = g.date.split("-").map(Number);
  const [hh, mm] = g.time && g.time !== "00:00" ? g.time.split(":").map(Number) : [8, 0];   // no time yet: lock at 8 AM
  const guess = Date.UTC(y, m - 1, d, hh, mm), off = tzOffset(tz, guess);
  let t = guess - off; const off2 = tzOffset(tz, t); if (off2 !== off) t = guess - off2;
  return t;
}

// ---------- names ----------
// Letters, numbers, spaces and . ' - only; 2-20 characters; no links or emails; checked against
// words that aren't OK, including look-alike spellings (sh1t, f@ck, spaced-out letters).
// Checked anywhere in the name (squashed, look-alikes undone):
const BAD_ANY = ["fuck", "shit", "bitch", "cunt", "pussy", "whore", "slut", "nigg", "nigr", "retard", "porn", "penis", "vagina", "boob",
  "jizz", "wank", "twat", "bastard", "douche", "nazi", "hitler", "molest", "pedo", "dildo", "horny", "milf", "tranny", "wetback", "beaner", "faggot"];
// Checked as whole words only (so names like Cassidy, Dickson, Essex or Van Dyke are fine):
const BAD_WORD = ["ass", "arse", "asshole", "cum", "tit", "tits", "hoe", "ho", "gay", "sex", "sexy", "anal", "cock", "dick", "fag", "coon", "gook",
  "spic", "kike", "chink", "dyke", "rape", "queer", "kkk", "fart", "poop", "pee", "piss", "crap", "damn", "hell", "suck", "sucks", "kill",
  "die", "hate", "loser", "idiot", "stupid", "dumb", "fat", "ugly"];
const LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "@": "a", "$": "s", "!": "i", "|": "i", "+": "t"};
const norm = s => s.toLowerCase().replace(/[01345789@$!|+]/g, c => LEET[c]);
export function checkName(raw) {
  const name = String(raw || "").replace(/\s+/g, " ").trim();
  if (name.length < 2 || name.length > 20) return {ok: false, why: "Use 2 to 20 characters."};
  if (!/^[A-Za-z0-9 .'-]+$/.test(name)) return {ok: false, why: "Letters, numbers and spaces only."};
  if (/https?|www|\.com|\.net|\.org|@/i.test(name)) return {ok: false, why: "No links or emails."};
  const n = norm(name), squashed = n.replace(/[^a-z]/g, ""), dedup = squashed.replace(/(.)\1+/g, "$1");
  if (BAD_ANY.some(w => squashed.includes(w) || dedup.includes(w))) return {ok: false, why: "Please pick a different name."};
  const words = n.split(/[^a-z]+/).filter(Boolean);
  if (BAD_WORD.includes(squashed) || BAD_WORD.includes(dedup) || words.some(w => BAD_WORD.includes(w) || BAD_WORD.includes(w.replace(/(.)\1+/g, "$1"))))
    return {ok: false, why: "Please pick a different name."};
  return {ok: true, name};
}

// ---------- scoring ----------
const sign = (a, b) => a > b ? 1 : a < b ? -1 : 0;
export const points = (p, g) => g.hs == null || g.as == null ? null : (p[0] === g.hs && p[1] === g.as ? 3 : sign(p[0], p[1]) === sign(g.hs, g.as) ? 1 : 0);

const CONF = new Map();   // per request: conference files already read
async function conf(env, fk) {
  if (!/^[a-z0-9-]{3,60}$/.test(fk)) return null;
  if (!CONF.has(fk)) {
    const r = await env.ASSETS.fetch(new Request(`https://assets.local/data/conf/${fk}.json`));
    CONF.set(fk, r.ok ? await r.json() : null);
  }
  return CONF.get(fk);
}

async function players(env, fk) {
  const out = []; let cursor;
  do {
    const r = await env.USERS.list({prefix: `pk:${site(env)}:`, cursor, limit: 1000});
    for (const k of r.keys) if (((k.metadata || {}).f || "").split(",").includes(fk)) out.push(k.name);
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return Promise.all(out.map(async k => [k.split(":")[2], await env.USERS.get(k, "json")]));
}

// Leaderboard + everyone's picks on locked games, for one conference.
export async function board(env, fk, from, to, me, now = Date.now()) {
  const D = await conf(env, fk); if (!D) return null;
  const tz = confTz(D.conf_name), games = new Map(D.games.map(g => [String(g.id), g]));
  const rows = [], seen = {};
  for (const [uid, rec] of await players(env, fk)) {
    if (!rec) continue;
    const picks = (rec.picks || {})[fk] || {};
    let wk = 0, wkx = 0, wkn = 0, se = 0, sex = 0, sen = 0;
    for (const [gid, p] of Object.entries(picks)) {
      const g = games.get(gid); if (!g) continue;
      const locked = now >= kickoff(g, tz);
      if (locked) (seen[gid] = seen[gid] || []).push({name: rec.hidden && uid !== me ? null : rec.name, me: uid === me, p: [p[0], p[1]]});
      const pts = points(p, g); if (pts == null) continue;
      se += pts; sen++; if (pts === 3) sex++;
      if (g.date >= from && g.date <= to) { wk += pts; wkn++; if (pts === 3) wkx++; }
    }
    if (rec.hidden && uid !== me) continue;
    rows.push({name: rec.name || "Player", me: uid === me, wk, wkx, wkn, se, sex, sen});
  }
  for (const k of Object.keys(seen)) seen[k] = seen[k].filter(x => x.name || x.me);
  const rank = (list, f, x) => list.slice().sort((a, b) => b[f] - a[f] || b[x] - a[x] || a.name.localeCompare(b.name))
    .map((r, i, arr) => Object.assign({}, r, {rank: i && arr[i - 1][f] === r[f] && arr[i - 1][x] === r[x] ? null : i + 1}));
  const fix = l => { let last = 1; return l.map(r => { if (r.rank) last = r.rank; return Object.assign(r, {rank: last}); }); };
  return {tz, week: fix(rank(rows.filter(r => r.wkn), "wk", "wkx")), season: fix(rank(rows.filter(r => r.sen), "se", "sex")), seen};
}

// ---------- the page's calls ----------
export async function route(p, req, env, c, json, L) {
  CONF.clear();
  const key = pkKey(env, c.sub), url = new URL(req.url);
  let rec = await env.USERS.get(key, "json");
  const save = r => env.USERS.put(key, JSON.stringify(r), {metadata: {n: r.name || "", h: !!r.hidden, f: Object.keys(r.picks || {}).slice(0, 40).join(",")}});
  if (p === "/api/pickem" && req.method === "GET") {
    const fk = url.searchParams.get("fk") || "", from = url.searchParams.get("from") || "", to = url.searchParams.get("to") || "";
    if (!/^\d{4}-\d\d-\d\d$/.test(from) || !/^\d{4}-\d\d-\d\d$/.test(to)) return json({error: "bad dates"}, 400);
    const b = await board(env, fk, from, to, c.sub);
    if (!b) return json({error: "no such conference"}, 404);
    return json(Object.assign({name: rec && rec.name || "", picks: rec && rec.picks && rec.picks[fk] || {}}, b));
  }
  let body = {}; try { body = await req.json(); } catch (e) {}
  if (p === "/api/pickem/name" && req.method === "PUT") {
    const chk = checkName(body.name);
    if (!chk.ok) { L && L.info("pickem.name.rejected", {uid: c.sub, name: String(body.name || "").slice(0, 30)}); return json({error: chk.why}, 422); }
    rec = Object.assign({picks: {}}, rec || {}, {name: chk.name});
    await save(rec);
    L && L.keep("pickem.name", {uid: c.sub, name: chk.name});
    return json({ok: true, name: chk.name});
  }
  if (p === "/api/pickem" && req.method === "PUT") {
    const fk = String(body.fk || ""), gid = String(body.g || "");
    const D = await conf(env, fk); if (!D) return json({error: "no such conference"}, 404);
    const g = D.games.find(x => String(x.id) === gid); if (!g) return json({error: "no such game"}, 404);
    if (Date.now() >= kickoff(g, confTz(D.conf_name))) return json({error: "locked", locked: true}, 409);
    rec = Object.assign({picks: {}}, rec || {});
    if (!rec.name) { const chk = checkName(body.name); rec.name = chk.ok ? chk.name : "Player"; }
    const mine = rec.picks[fk] = rec.picks[fk] || {};
    if (body.clear) delete mine[gid];
    else {
      const h = Math.max(0, Math.min(20, Math.round(+body.h))), a = Math.max(0, Math.min(20, Math.round(+body.a)));
      if (!Number.isFinite(h) || !Number.isFinite(a)) return json({error: "bad score"}, 400);
      mine[gid] = [h, a, Date.now()];
    }
    if (!Object.keys(mine).length) delete rec.picks[fk];
    await save(rec);
    L && L.info("pickem.pick", {uid: c.sub, fk, g: gid, pick: body.clear ? "clear" : `${mine[gid][0]}-${mine[gid][1]}`});
    return json({ok: true, name: rec.name});
  }
  return json({error: "not found"}, 404);
}

// ---------- admin: rename or hide players ----------
export async function adminList(env) {
  const out = []; let cursor;
  do {
    const r = await env.USERS.list({prefix: `pk:${site(env)}:`, cursor, limit: 1000});
    for (const k of r.keys) out.push({uid: k.name.split(":")[2], name: (k.metadata || {}).n || "", hidden: !!(k.metadata || {}).h, confs: ((k.metadata || {}).f || "").split(",").filter(Boolean).length});
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return out;
}
export async function adminSet(env, uid, body) {
  const key = pkKey(env, uid), rec = await env.USERS.get(key, "json");
  if (!rec) return {error: "no such player"};
  if (typeof body.hidden === "boolean") rec.hidden = body.hidden;
  if (typeof body.name === "string") { const chk = checkName(body.name); if (!chk.ok) return {error: chk.why}; rec.name = chk.name; }
  await env.USERS.put(key, JSON.stringify(rec), {metadata: {n: rec.name || "", h: !!rec.hidden, f: Object.keys(rec.picks || {}).slice(0, 40).join(",")}});
  return {ok: true, name: rec.name, hidden: !!rec.hidden};
}

// Sunday wrap-up line: this weekend's Pick'em points and place, per conference played.
export async function wrapLine(env, uid, from, to) {
  const rec = await env.USERS.get(pkKey(env, uid), "json");
  if (!rec || !rec.picks) return "";
  const parts = [];
  for (const fk of Object.keys(rec.picks)) {
    const b = await board(env, fk, from, to, uid);
    const me = b && b.week.find(r => r.me);
    if (me) parts.push(`${me.wk} pts, ${me.rank === 1 ? "1st" : ordinal(me.rank)} of ${b.week.length}`);
  }
  return parts.length ? "Pick'em: " + parts.join(" · ") : "";
}
const ordinal = n => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");
