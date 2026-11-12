// Web Push sending (no outside libraries): VAPID sign-in (RFC 8292) and message encryption
// (RFC 8291, aes128gcm). Works for iPhone home-screen apps, Android and desktop browsers.
// The VAPID key pair is made once and kept in KV (cfg:vapid); the public half is given to the page.

const te = new TextEncoder();
export const b64u = buf => {
  const b = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = ""; for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
export const unb64u = s => {
  s = String(s).replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "=";
  const bin = atob(s), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
};
const cat = (...parts) => {
  const n = parts.reduce((a, p) => a + p.length, 0), out = new Uint8Array(n);
  let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};
async function hmac(key, data) {
  const k = await crypto.subtle.importKey("raw", key, {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, data));
}

let VAPID = null;
export async function vapid(env) {
  if (VAPID) return VAPID;
  let v = await env.USERS.get("cfg:vapid", "json");
  if (!v) {
    const kp = await crypto.subtle.generateKey({name: "ECDSA", namedCurve: "P-256"}, true, ["sign", "verify"]);
    const jwk = await crypto.subtle.exportKey("jwk", kp.privateKey);
    const pub = b64u(await crypto.subtle.exportKey("raw", kp.publicKey));
    // another run may have made one at the same moment: keep whichever landed first
    const again = await env.USERS.get("cfg:vapid", "json");
    if (again) v = again; else { v = {pub, jwk}; await env.USERS.put("cfg:vapid", JSON.stringify(v)); }
  }
  const key = await crypto.subtle.importKey("jwk", v.jwk, {name: "ECDSA", namedCurve: "P-256"}, false, ["sign"]);
  VAPID = {pub: v.pub, key, jwts: {}};
  return VAPID;
}
async function vapidHeader(env, endpoint) {
  const V = await vapid(env), aud = new URL(endpoint).origin, now = Math.floor(Date.now() / 1000);
  const c = V.jwts[aud];
  if (!c || c.exp - now < 3600) {
    const exp = now + 12 * 3600;
    const head = b64u(te.encode(JSON.stringify({typ: "JWT", alg: "ES256"})));
    const body = b64u(te.encode(JSON.stringify({aud, exp, sub: "https://sidelinestandings.com"})));
    const sig = await crypto.subtle.sign({name: "ECDSA", hash: "SHA-256"}, V.key, te.encode(head + "." + body));
    V.jwts[aud] = {exp, t: `${head}.${body}.${b64u(sig)}`};
  }
  return `vapid t=${V.jwts[aud].t}, k=${V.pub}`;
}

// Encrypt one message for one subscription (RFC 8291). Exported for the self-test.
export async function encrypt(sub, payload, salt = crypto.getRandomValues(new Uint8Array(16)), local = null) {
  const uaPub = unb64u(sub.keys.p256dh), auth = unb64u(sub.keys.auth);
  const kp = local || await crypto.subtle.generateKey({name: "ECDH", namedCurve: "P-256"}, true, ["deriveBits"]);
  const asPub = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
  const uaKey = await crypto.subtle.importKey("raw", uaPub, {name: "ECDH", namedCurve: "P-256"}, false, []);
  const secret = new Uint8Array(await crypto.subtle.deriveBits({name: "ECDH", public: uaKey}, kp.privateKey, 256));
  const prkKey = await hmac(auth, secret);
  const ikm = await hmac(prkKey, cat(te.encode("WebPush: info\0"), uaPub, asPub, new Uint8Array([1])));
  const prk = await hmac(salt, ikm);
  const cek = (await hmac(prk, cat(te.encode("Content-Encoding: aes128gcm\0"), new Uint8Array([1])))).slice(0, 16);
  const nonce = (await hmac(prk, cat(te.encode("Content-Encoding: nonce\0"), new Uint8Array([1])))).slice(0, 12);
  const key = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const plain = cat(te.encode(payload), new Uint8Array([2]));
  const ct = new Uint8Array(await crypto.subtle.encrypt({name: "AES-GCM", iv: nonce}, key, plain));
  const head = new Uint8Array(21); head.set(salt, 0); new DataView(head.buffer).setUint32(16, 4096); head[20] = 65;
  return cat(head, asPub, ct);
}

// Send one notification. Returns the push service's status: 201 = sent; 404/410 = this device
// unsubscribed (delete it).
export async function send(env, sub, msg, opts = {}) {
  const body = await encrypt(sub, JSON.stringify(msg));
  const r = await fetch(sub.endpoint, {method: "POST", body, headers: {
    authorization: await vapidHeader(env, sub.endpoint), "content-encoding": "aes128gcm",
    "content-type": "application/octet-stream", ttl: String(opts.ttl || 86400), urgency: opts.urgency || "normal"}});
  return r.status;
}

// ---------- Apple push (the App Store app) ----------
// The native app can't use web push, so iPhones running the app get alerts straight from Apple's
// push service. Needs Apple's push key (.p8), pasted once by the owner in Admin › Apple push key and
// kept in KV cfg:apns {p8, kid, team, topic}. Sign-in token: ES256, reused for 40 minutes.
let APNS = null;
export const APNS_TOPIC = "com.sidelinestandings.app", APNS_TEAM = "55FGL4DVG5";
// Apps the push key may send to: the App Store app and the UAT app (TestFlight only).
export const APNS_TOPICS = ["com.sidelinestandings.app", "com.sidelinestandings.app.uat"];
export async function apnsKey(p8) {
  const der = Uint8Array.from(atob(String(p8).replace(/-----[^-]+-----/g, "").replace(/\s+/g, "")), c => c.charCodeAt(0));
  return crypto.subtle.importKey("pkcs8", der, {name: "ECDSA", namedCurve: "P-256"}, false, ["sign"]);
}
async function apnsCfg(env) {
  if (APNS && Date.now() - APNS.at < 10 * 60e3) return APNS;
  const c = await env.USERS.get("cfg:apns", "json");
  if (!c || !c.p8 || !c.kid) { APNS = null; return null; }
  if (!APNS || APNS.kid !== c.kid || APNS.p8 !== c.p8) APNS = {kid: c.kid, p8: c.p8, team: c.team || APNS_TEAM, topic: c.topic || APNS_TOPIC, key: await apnsKey(c.p8), jwt: null, iat: 0};
  APNS.at = Date.now();
  return APNS;
}
async function apnsJwt(c) {
  const now = Math.floor(Date.now() / 1000);
  if (!c.jwt || now - c.iat > 2400) {
    const head = b64u(te.encode(JSON.stringify({alg: "ES256", kid: c.kid})));
    const body = b64u(te.encode(JSON.stringify({iss: c.team, iat: now})));
    const sig = await crypto.subtle.sign({name: "ECDSA", hash: "SHA-256"}, c.key, te.encode(head + "." + body));
    c.jwt = `${head}.${body}.${b64u(sig)}`; c.iat = now;
  }
  return c.jwt;
}
// Returns Apple's status: 200 = sent; 410 = this app was deleted or the token is no good (delete the device);
// 0 = no push key yet. reason (when Apple gives one) is kept for the log.
export async function apnsSend(env, token, payload, opts = {}) {
  const c = await apnsCfg(env); if (!c) return {status: 0, reason: "no push key"};
  const h = {authorization: "bearer " + await apnsJwt(c), "apns-topic": APNS_TOPICS.includes(opts.topic) ? opts.topic : c.topic, "apns-push-type": "alert", "apns-priority": "10",
    "apns-expiration": String(Math.floor(Date.now() / 1000) + 86400), "content-type": "application/json"};
  if (opts.collapse) h["apns-collapse-id"] = String(opts.collapse).slice(0, 64);
  const r = await fetch(`https://${opts.sandbox ? "api.sandbox.push.apple.com" : "api.push.apple.com"}/3/device/${token}`, {method: "POST", headers: h, body: JSON.stringify(payload)});
  let reason = ""; if (r.status !== 200) { try { reason = (await r.json()).reason || ""; } catch (e) {} }
  if (r.status === 403 && reason === "ExpiredProviderToken") c.jwt = null;
  const gone = r.status === 410 || (r.status === 400 && /BadDeviceToken|DeviceTokenNotForTopic/.test(reason));
  return {status: gone ? 410 : r.status, reason};
}
