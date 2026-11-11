// Network first (scores change often), falling back to the last copy when offline.
// Also shows alerts (push notifications) and keeps the red number on the app icon.
const CACHE = "standings-v2";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin || new URL(req.url).pathname.startsWith("/api/")) return;   // account calls never cached
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req, {ignoreSearch: true}))
  );
});

// Red number = alerts not opened yet (kept in a tiny cache entry; cleared when the app opens).
const BADGE = "badge-v1", BKEY = "/__badge";
async function badgeGet() { try { const r = await (await caches.open(BADGE)).match(BKEY); return r ? +(await r.text()) || 0 : 0; } catch (e) { return 0; } }
async function badgeSet(n) {
  try { await (await caches.open(BADGE)).put(BKEY, new Response(String(n))); } catch (e) {}
  try { if (n > 0 && self.navigator.setAppBadge) await self.navigator.setAppBadge(n); else if (self.navigator.clearAppBadge) await self.navigator.clearAppBadge(); } catch (e) {}
}
self.addEventListener("push", e => {
  let m = {};
  try { m = e.data ? e.data.json() : {}; } catch (x) { m = {t: "Sideline Standings", b: e.data ? e.data.text() : ""}; }
  e.waitUntil((async () => {
    await self.registration.showNotification(m.t || "Sideline Standings", {
      body: m.b || "", tag: m.tag || undefined, renotify: !!m.tag, icon: "icons/icon-192.png", badge: "icons/icon-192.png",
      data: {u: m.u || "/"}});
    if (m.badge !== false) await badgeSet((await badgeGet()) + 1);
  })());
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.u) || "/", self.location.origin).href;
  e.waitUntil((async () => {
    await badgeSet(0);
    const all = await self.clients.matchAll({type: "window", includeUncontrolled: true});
    for (const c of all) {
      if (new URL(c.url).origin === self.location.origin) {
        try { await c.focus(); } catch (x) {}
        try { await c.navigate(url); } catch (x) { c.postMessage({open: url}); }
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
self.addEventListener("message", e => { if (e.data && e.data.clearBadge) e.waitUntil(badgeSet(0)); });
