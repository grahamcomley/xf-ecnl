// Starts the xf-ecnl "Update data and publish site" GitHub Action.
// DISPATCH_TOKEN is a Worker secret (fine-grained GitHub token, Actions read/write on this one repo).
const URL = "https://api.github.com/repos/grahamcomley/xf-ecnl/actions/workflows/update.yml/dispatches";

async function kick(env) {
  const r = await fetch(URL, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${(env.DISPATCH_TOKEN || "").trim()}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "xf-ecnl-timer",
    },
    body: JSON.stringify({ ref: "main", inputs: { mode: "auto" } }),
  });
  const body = r.status === 204 ? "" : await r.text();
  if (r.status !== 204) console.log(`dispatch failed: ${r.status} ${body}`);
  return { status: r.status, body: body.slice(0, 300) };
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(kick(env)); },
  async fetch(req, env) {
    // /check starts one update now and shows GitHub's answer (204 = working). Harmless: it only refreshes the site.
    if (new URL(req.url).pathname === "/check") {
      const r = await kick(env);
      return new Response(JSON.stringify({ ...r, token_set: !!env.DISPATCH_TOKEN }) + "\n", { headers: { "content-type": "application/json" } });
    }
    return new Response("xf-ecnl timer: runs every 15 minutes.\n");
  },
};
