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
  if (r.status !== 204) console.log(`dispatch failed: ${r.status} ${await r.text()}`);
  return r.status;
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(kick(env)); },
  async fetch() { return new Response("xf-ecnl timer: runs every 15 minutes.\n"); },
};
