// Team watch links (Graham, Nov 24): one link per team (the club's Veo / YouTube / Trace / BallerTV / Pixellot page),
// not per game. Any signed-in person can send one; it shows only after the owner approves it in Admin.
// KV (shared by prod and UAT):
//   tl:links  {team key: {u: url, s: site name, at}}             approved, public
//   tl:queue  [{id, t: team key, n: team name, u, s, by: uid, e: email, at}]   waiting for review (owner only)
// Routes: GET /api/links (public), POST /api/links {team, name, url} (signed in),
//         GET /api/admin/links, PUT /api/admin/links {id, act: "approve" | "reject"} or {team, act: "remove"} (owner).

export const SITES = [
  [/(^|\.)veo\.co$/, "Veo"],
  [/(^|\.)(youtube\.com|youtu\.be)$/, "YouTube"],
  [/(^|\.)traceup\.com$/, "Trace"],
  [/(^|\.)ballertv\.com$/, "BallerTV"],
  [/(^|\.)pixellot\.tv$/, "Pixellot"],
];
const TEAM = /^[a-z0-9-]{3,40}$/;

export function checkUrl(raw) {
  let u;
  try { u = new URL(String(raw || "").trim()); } catch (e) { return {error: "That doesn't look like a link. Copy it from the address bar and paste it here."}; }
  if (u.protocol !== "https:") return {error: "Use the https:// link from the address bar."};
  const host = u.hostname.toLowerCase(), hit = SITES.find(([re]) => re.test(host));
  if (!hit) return {error: "Only Veo, YouTube, Trace, BallerTV or Pixellot links can be added."};
  u.hash = "";
  return {url: u.toString().slice(0, 300), site: hit[1]};
}

const get = async (env, k, d) => (await env.USERS.get(k, "json")) || d;

export async function linksPublic(env) {
  const links = await get(env, "tl:links", {});
  return new Response(JSON.stringify({links}), {headers: {"content-type": "application/json", "cache-control": "public, max-age=60"}});
}

// POST /api/links from a signed-in person. Returns {ok, site} or {error}.
export async function linksSend(env, req, c, rec) {
  let b = {}; try { b = await req.json(); } catch (e) {}
  const t = String(b.team || ""), n = String(b.name || "").replace(/[<>]/g, "").slice(0, 60);
  if (!TEAM.test(t)) return {error: "Unknown team."};
  const chk = checkUrl(b.url); if (chk.error) return chk;
  const links = await get(env, "tl:links", {});
  if (links[t] && links[t].u === chk.url) return {error: "That's already this team's link."};
  let q = await get(env, "tl:queue", []);
  if (q.filter(x => x.by === c.sub).length >= 5) return {error: "You have 5 links waiting for review already."};
  q = q.filter(x => !(x.t === t && x.by === c.sub));   // their newer link for the team replaces their older one
  const item = {id: crypto.randomUUID().slice(0, 8), t, n, u: chk.url, s: chk.site, by: c.sub, e: (rec && rec.email) || c.email || "", at: Date.now()};
  q.push(item);
  await env.USERS.put("tl:queue", JSON.stringify(q.slice(-100)));
  return {ok: true, site: chk.site, item};
}

export async function linksAdmin(env, req) {
  if (req.method === "GET") return {queue: await get(env, "tl:queue", []), links: await get(env, "tl:links", {})};
  let b = {}; try { b = await req.json(); } catch (e) {}
  const links = await get(env, "tl:links", {});
  let q = await get(env, "tl:queue", []);
  if (b.act === "remove") {
    if (!links[b.team]) return {error: "No link for that team."};
    const item = Object.assign({t: b.team}, links[b.team]);
    delete links[b.team]; await env.USERS.put("tl:links", JSON.stringify(links));
    return {ok: true, act: "remove", item};
  }
  const it = q.find(x => x.id === b.id);
  if (!it) return {error: "That one was already handled."};
  if (b.act === "approve") {
    links[it.t] = {u: it.u, s: it.s, n: it.n, at: Date.now()};
    await env.USERS.put("tl:links", JSON.stringify(links));
    q = q.filter(x => x.id !== it.id && !(x.t === it.t && x.u === it.u));
  } else if (b.act === "reject") q = q.filter(x => x.id !== it.id);
  else return {error: "Unknown action."};
  await env.USERS.put("tl:queue", JSON.stringify(q));
  return {ok: true, act: b.act, item: it};
}
