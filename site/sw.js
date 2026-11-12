// Start: the page itself comes from the network when it answers within 3 s; icons and the team list open
// instantly from the phone's copy and are refreshed in the background (a new page version reloads itself once, see checkForUpdate). Scores
// (conference files, status) try the network first but fall back to the saved copy after 2.5 s.
const CACHE = "standings-v4";
const SHELL = /\/($|index\.html$|manifest\.webmanifest$|privacy\.html$|icons\/|data\/teams\.json$|data\/index\.json$)/;
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith("standings-") && k !== CACHE) await caches.delete(k);
  await self.clients.claim();
})()));
const put = (req, res) => { if (res && res.ok) { const c = res.clone(); caches.open(CACHE).then(x => x.put(req, c)); } return res; };
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname.endsWith("version.txt")) return;
  const key = req.mode === "navigate" ? new Request(url.origin + "/") : req;
  if (req.mode === "navigate" || SHELL.test(url.pathname)) {
    // The page itself: newest from the network when it answers within 3 s (so a new version shows on
    // the first open), else the phone's copy (no signal, slow field Wi-Fi). Icons and team lists: phone's
    // copy first, refreshed in the background.
    e.respondWith((async () => {
      const hit = await caches.match(key, {ignoreSearch: true});
      const net = fetch(req).then(r => put(key, r)).catch(() => null);
      if (hit && !(req.mode === "navigate" || /\/($|index\.html$)/.test(url.pathname))) { e.waitUntil(net); return hit; }
      if (!hit) return (await net) || new Response("Offline", {status: 503});
      const first = await Promise.race([net, new Promise(r => setTimeout(r, 3000, null))]);
      if (first) return first;
      e.waitUntil(net); return hit;
    })());
    return;
  }
  e.respondWith((async () => {
    const net = fetch(req).then(r => put(req, r));
    const slow = new Promise(r => setTimeout(r, 2500, null));
    try {
      const first = await Promise.race([net, slow]);
      if (first) return first;
      const hit = await caches.match(req, {ignoreSearch: true});
      if (hit) { e.waitUntil(net.catch(() => {})); return hit; }
      return await net;
    } catch (x) { return (await caches.match(req, {ignoreSearch: true})) || new Response("Offline", {status: 503}); }
  })());
});

// Red number = alerts not opened yet (kept in a tiny cache entry; cleared when the app opens).
const BADGE = "badge-v1", BKEY = "/__badge";
async function badgeGet() { try { const r = await (await caches.open(BADGE)).match(BKEY); return r ? +(await r.text()) || 0 : 0; } catch (e) { return 0; } }
async function badgeSet(n) {
  try { await (await caches.open(BADGE)).put(BKEY, new Response(String(n))); } catch (e) {}
  try { if (n > 0 && self.navigator.setAppBadge) await self.navigator.setAppBadge(n); else if (self.navigator.clearAppBadge) await self.navigator.clearAppBadge(); } catch (e) {}
}
// Alert inbox: every alert received is kept on the phone (last 60) so the app can list them
// (bell in the header). Each entry: {id, t, b, x, u, at, read}.
async function inboxGet() { try { const r = await (await caches.open(BADGE)).match("/__inbox"); return r ? await r.json() : []; } catch (e) { return []; } }
async function inboxPut(list) { try { await (await caches.open(BADGE)).put("/__inbox", new Response(JSON.stringify(list.slice(0, 60)))); } catch (e) {} }
async function tellPages(msg) { for (const c of await self.clients.matchAll({type: "window", includeUncontrolled: true})) c.postMessage(msg); }
self.addEventListener("push", e => {
  let m = {};
  try { m = e.data ? e.data.json() : {}; } catch (x) { m = {t: "Sideline Standings", b: e.data ? e.data.text() : ""}; }
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  e.waitUntil((async () => {
    await self.registration.showNotification(m.t || "Sideline Standings", {
      body: m.b || "", tag: m.tag || undefined, renotify: !!m.tag, icon: "icons/icon-192.png", badge: "icons/icon-192.png",
      data: {u: m.u || "/", x: m.x || null, id}});
    const list = await inboxGet();
    list.unshift({id, t: m.t || "Sideline Standings", b: m.b || "", x: m.x || null, u: m.u || "/", at: Date.now(), read: false});
    await inboxPut(list); await tellPages({inbox: true});
    if (m.badge !== false) await badgeSet((await badgeGet()) + 1);
  })());
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const d = e.notification.data || {};
  // The app opens with the full alert on screen first (iPhone cuts long alerts short); its
  // "Show in the app" button then goes to the exact game.
  const url = new URL((d.u || "/") + ((d.u || "").includes("#") ? "&n=" + Date.now() : ""), self.location.origin).href;
  e.waitUntil((async () => {
    try { await (await caches.open(BADGE)).put("/__note", new Response(JSON.stringify({id: d.id, t: e.notification.title, b: e.notification.body, x: d.x || null, u: d.u || "/"}))); } catch (x) {}
    if (d.id) { const list = await inboxGet(); const it = list.find(x => x.id === d.id); if (it) { it.read = true; await inboxPut(list); } }
    await badgeSet(0);
    // App already open: bring it forward and tell it which alert was tapped (no reload).
    const all = await self.clients.matchAll({type: "window", includeUncontrolled: true});
    const c = all.find(x => new URL(x.url).origin === self.location.origin);
    if (c) { try { await c.focus(); } catch (x) {} c.postMessage({open: url}); return; }
    await self.clients.openWindow(url);
  })());
});
self.addEventListener("message", e => { if (e.data && e.data.clearBadge) e.waitUntil(badgeSet(0)); });
