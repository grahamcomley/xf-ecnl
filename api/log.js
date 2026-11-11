// Logging. Every API call and every alerts check writes one structured line to Workers Logs
// (console). Important events are also kept in KV for 14 days (ev:<site>:<time>:<random>), one
// write per request/check at most, so the daily diag job (.github/workflows/diag.yml) can read
// everything that happened without anyone opening a dashboard.
export function makeLog(env, ctx) {
  const site = env.SITE === "live" ? "live" : "uat", kept = [];
  const line = (lvl, evt, data) => { try { console[lvl](JSON.stringify(Object.assign({evt, site, at: new Date().toISOString()}, data))); } catch (e) {} };
  return {
    info(evt, data = {}) { line("log", evt, data); },
    keep(evt, data = {}) { line("log", evt, data); kept.push(Object.assign({evt, at: Date.now()}, data)); },
    error(evt, data = {}) { line("error", evt, data); kept.push(Object.assign({evt, at: Date.now(), error: true}, data)); },
    flush() {
      if (!kept.length || !env.USERS) return;
      const key = `ev:${site}:${new Date().toISOString()}:${Math.random().toString(36).slice(2, 6)}`;
      const p = env.USERS.put(key, JSON.stringify(kept.splice(0)), {expirationTtl: 14 * 86400}).catch(() => {});
      if (ctx && ctx.waitUntil) ctx.waitUntil(p);
      return p;
    }
  };
}
