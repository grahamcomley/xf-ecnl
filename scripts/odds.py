"""Season odds, worked out once per conference on the server so every phone shows the same numbers.

Same rules as the page's simulator: the rest of the season is played many times with the team ratings
(Poisson goals: exp(mu + home + attack - other's defence)); each simulated season is ranked by
PPG, points, head-to-head (only when exactly two teams share the points), goal difference, goals for,
fewer goals against. Points already on the table include ECNL's own adjustments (D["adj"]).

Output (added to the conference file):
  odds   = {"n": runs, "pos": {team id: [chance of finishing 1st, 2nd, ...]}}
  impact = {game id: {"H"|"D"|"A": [[chance of 1st per member], [chance of top-N per member]]}, "now": [...]}
           for the games the page shows with an impact line (roughly the next 10 days).
"""
import numpy as np

N_SEASON = 12000
N_IMPACT = 4000
IMPACT_DAYS = 10


def _setup(D):
    mids = D.get("members") or [t["id"] for t in D["teams"]]
    ix = {t: i for i, t in enumerate(mids)}
    n = len(mids)
    T = {t["id"]: t for t in D["teams"]}
    mu = (D.get("model") or {}).get("mu", 0.3)
    home = (D.get("model") or {}).get("home", 0.0)
    valid = [g for g in D["games"] if g.get("home_id") and g.get("away_id") and not g.get("bad")]
    played = [g for g in valid if g.get("hs") is not None and g.get("as") is not None]
    remaining = [g for g in valid if g.get("hs") is None or g.get("as") is None]
    remaining = [g for g in remaining if g["home_id"] in ix or g["away_id"] in ix]
    pts = np.zeros(n, np.int32); gp = np.zeros(n, np.int32); gf = np.zeros(n, np.int32); ga = np.zeros(n, np.int32)
    h2h = np.zeros((n, n), np.int32)
    for g in played:
        h, a, x, y = ix.get(g["home_id"]), ix.get(g["away_id"]), g["hs"], g["as"]
        ph, pa = (3 if x > y else 1 if x == y else 0), (3 if y > x else 1 if x == y else 0)
        if h is not None:
            gp[h] += 1; gf[h] += x; ga[h] += y; pts[h] += ph
        if a is not None:
            gp[a] += 1; gf[a] += y; ga[a] += x; pts[a] += pa
        if h is not None and a is not None:
            h2h[h, a] += ph; h2h[a, h] += pa
    for k, v in (D.get("adj") or {}).items():
        i = ix.get(int(k)) if str(k).lstrip("-").isdigit() else ix.get(k)
        if i is not None:
            pts[i] += v

    def p(tid):
        t = T.get(tid) or {}
        q = t.get("p") or [0, 0]
        return q[0], q[1]
    lh, la = [], []
    for g in remaining:
        (ha, hd), (aa, ad) = p(g["home_id"]), p(g["away_id"])
        lh.append(np.exp(mu + home + ha - ad)); la.append(np.exp(mu + aa - hd))
    gh = np.array([ix.get(g["home_id"], -1) for g in remaining], np.int64)
    gaw = np.array([ix.get(g["away_id"], -1) for g in remaining], np.int64)
    return mids, n, remaining, np.array(lh), np.array(la), gh, gaw, pts, gp, gf, ga, h2h


def _rank(P, GP, GF, GA, H2H):
    """P..GA: (N, n). H2H: (N, n, n) points i took off j. Returns order (N, n): team index at each place."""
    N, n = P.shape
    ppg = np.where(GP > 0, P / np.maximum(GP, 1), 0.0)
    gd = GF - GA
    order = np.lexsort((GA, -GF, -gd, -P, -ppg), axis=1)
    # head-to-head for exactly-two-way ties on points (and same PPG): neighbours after the sort
    rows = np.arange(N)[:, None]
    sp, sppg = P[rows, order], ppg[rows, order]
    cnt = np.zeros((N, n), np.int32)
    for r in range(n):   # how many teams share each team's points
        cnt[:, r] = (P == sp[:, r:r + 1]).sum(axis=1)
    for r in range(n - 1):
        a, b = order[:, r], order[:, r + 1]
        tie = (sp[:, r] == sp[:, r + 1]) & (sppg[:, r] == sppg[:, r + 1]) & (cnt[:, r] == 2)
        if not tie.any():
            continue
        s = np.nonzero(tie)[0]
        swap = H2H[s, b[s], a[s]] > H2H[s, a[s], b[s]]
        if swap.any():
            ss = s[swap]
            order[ss, r], order[ss, r + 1] = b[ss], a[ss]
    return order


def _tally(base, X, Y, gh, gaw, n):
    pts0, gp0, gf0, ga0, h2h0 = base
    N, G = X.shape
    P = np.tile(pts0, (N, 1)).astype(np.int32); GP = np.tile(gp0, (N, 1)).astype(np.int32)
    GF = np.tile(gf0, (N, 1)).astype(np.int32); GA = np.tile(ga0, (N, 1)).astype(np.int32)
    H2H = np.tile(h2h0, (N, 1, 1)).astype(np.int16)
    for g in range(G):
        x, y, h, a = X[:, g], Y[:, g], gh[g], gaw[g]
        ph = np.where(x > y, 3, np.where(x == y, 1, 0)); pa = np.where(y > x, 3, np.where(x == y, 1, 0))
        if h >= 0:
            P[:, h] += ph; GP[:, h] += 1; GF[:, h] += x; GA[:, h] += y
        if a >= 0:
            P[:, a] += pa; GP[:, a] += 1; GF[:, a] += y; GA[:, a] += x
        if h >= 0 and a >= 0:
            H2H[:, h, a] += ph.astype(np.int16); H2H[:, a, h] += pa.astype(np.int16)
    return P, GP, GF, GA, H2H


def _forced(rng, lh, la, outcome, N):
    x, y = rng.poisson(lh, N), rng.poisson(la, N)
    ok = lambda x, y: (x > y) if outcome == "H" else (x == y) if outcome == "D" else (x < y)
    bad = ~ok(x, y)
    for _ in range(60):
        if not bad.any():
            break
        k = int(bad.sum())
        x[bad], y[bad] = rng.poisson(lh, k), rng.poisson(la, k)
        bad = ~ok(x, y)
    if bad.any():
        x[bad], y[bad] = {"H": (1, 0), "D": (1, 1), "A": (0, 1)}[outcome]
    return x, y


def season_odds(D, today, seed=20261116):
    mids, n, remaining, lh, la, gh, gaw, pts, gp, gf, ga, h2h = _setup(D)
    if n < 2:
        return None, None
    rng = np.random.default_rng(seed)
    G = len(remaining)
    X = rng.poisson(lh, (N_SEASON, G)) if G else np.zeros((N_SEASON, 0), np.int64)
    Y = rng.poisson(la, (N_SEASON, G)) if G else np.zeros((N_SEASON, 0), np.int64)
    base = (pts, gp, gf, ga, h2h)
    order = _rank(*_tally(base, X, Y, gh, gaw, n))
    pos = np.zeros((n, n))
    for r in range(n):
        pos[:, r] = np.bincount(order[:, r], minlength=n) / N_SEASON
    odds = {"n": N_SEASON, "pos": {str(mids[i]): [round(float(v), 4) for v in pos[i]] for i in range(n)}}

    spots = D.get("playoff_spots") or 0
    kS = max(0, min(n, spots) - 1) if spots else 0

    def keys(order):
        place = np.empty_like(order)
        rows = np.arange(order.shape[0])[:, None]
        place[rows, order] = np.arange(n)[None, :]
        return [[round(float(v), 4) for v in (place == 0).mean(axis=0)],
                [round(float(v), 4) for v in (place <= kS).mean(axis=0)]]
    from datetime import date, timedelta
    end = (date.fromisoformat(today) + timedelta(days=IMPACT_DAYS)).isoformat()
    # games the page shows with an impact line: everything in the next 10 days, plus each team's next 3 games
    nxt = set()
    for i in range(n):
        mine = sorted((g for g in range(G) if gh[g] == i or gaw[g] == i), key=lambda g: (remaining[g].get("date") or "", remaining[g].get("time") or ""))
        nxt.update(mine[:3])
    soon = [g for g, r in enumerate(remaining) if (r.get("date") or "") <= end or g in nxt]
    impact = None
    if soon:
        Ni = N_IMPACT
        Xi, Yi = X[:Ni].copy(), Y[:Ni].copy()
        T0 = _tally(base, Xi, Yi, gh, gaw, n)
        impact = {"now": keys(_rank(*T0))}
        for g in soon:
            res = {}
            for o in ("H", "D", "A"):
                x, y = _forced(rng, lh[g], la[g], o, Ni)
                P, GF, GA = T0[0].copy(), T0[2].copy(), T0[3].copy()
                GP, H2H = T0[1], T0[4]   # games played don't change; head-to-head changed in place below, then put back
                h, a = gh[g], gaw[g]
                ox, oy = Xi[:, g], Yi[:, g]
                d = lambda u, v: np.where(u > v, 3, np.where(u == v, 1, 0))
                if h >= 0:
                    P[:, h] += d(x, y) - d(ox, oy); GF[:, h] += x - ox; GA[:, h] += y - oy
                if a >= 0:
                    P[:, a] += d(y, x) - d(oy, ox); GF[:, a] += y - oy; GA[:, a] += x - ox
                both = h >= 0 and a >= 0
                if both:
                    sh, sa = H2H[:, h, a].copy(), H2H[:, a, h].copy()
                    H2H[:, h, a] += (d(x, y) - d(ox, oy)).astype(np.int16); H2H[:, a, h] += (d(y, x) - d(oy, ox)).astype(np.int16)
                res[o] = keys(_rank(P, GP, GF, GA, H2H))
                if both:
                    H2H[:, h, a], H2H[:, a, h] = sh, sa
            impact[str(remaining[g]["id"])] = res
    return odds, impact
