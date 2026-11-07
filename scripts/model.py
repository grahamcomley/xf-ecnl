"""Team ratings from every game in a pool (all conferences + national events).

Each team has an attack and a defence rating; each conference also has a shared
attack/defence offset, so one cross-conference result moves the whole
conference a little, not just the two teams that played.

  log(expected goals for home) = mu + home + att[h] + catt[conf h] - dfn[a] - cdfn[conf a]
  log(expected goals for away) = mu        + att[a] + catt[conf a] - dfn[h] - cdfn[conf h]

Fitted by weighted Poisson likelihood with shrinkage toward average:
recent games count more, blowouts are capped, and teams with few games stay
close to average until results say otherwise.
"""
import math
from datetime import date

MAX_GOALS = 10


def _days(d):
    y, m, dd = (int(x) for x in d[:10].split("-"))
    return date(y, m, dd).toordinal()


def cap_score(hs, as_, max_margin):
    if hs - as_ > max_margin:
        hs = as_ + max_margin
    elif as_ - hs > max_margin:
        as_ = hs + max_margin
    return hs, as_


def fit(games, team_conf, cfg, as_of=None, iters=60):
    """games: dicts with home_id, away_id, hs, as, date, neutral, weight_mult."""
    played = [g for g in games if g["hs"] is not None and g["as"] is not None]
    if as_of:
        played = [g for g in played if g["date"] < as_of]
    if not played:
        return None
    today = _days(as_of) if as_of else max(_days(g["date"]) for g in played)
    hl = cfg["half_life_days"]
    rows = []
    for g in played:
        age = max(0, today - _days(g["date"]))
        w = 0.5 ** (age / hl) * g.get("weight_mult", 1.0)
        hs, as_ = cap_score(g["hs"], g["as"], cfg["max_margin"])
        rows.append((g["home_id"], g["away_id"], hs, as_, w, 0.0 if g.get("neutral") else 1.0))

    teams = sorted({r[0] for r in rows} | {r[1] for r in rows})
    confs = sorted({team_conf.get(t, "other") for t in teams})
    att = {t: 0.0 for t in teams}
    dfn = {t: 0.0 for t in teams}
    catt = {c: 0.0 for c in confs}
    cdfn = {c: 0.0 for c in confs}
    tw = sum(r[4] for r in rows)
    mu = math.log(max(0.3, sum((r[2] + r[3]) * r[4] for r in rows) / (2 * tw)))
    home = 0.0
    kt, kc, kh = cfg["team_shrink"], cfg["conf_shrink"], cfg["home_shrink"]
    cf = {t: team_conf.get(t, "other") for t in teams}

    params = {"att": att, "dfn": dfn, "catt": catt, "cdfn": cdfn}

    def lams():
        out = []
        for h, a, hs, as_, w, ih in rows:
            lh = math.exp(mu + home * ih + att[h] + catt[cf[h]] - dfn[a] - cdfn[cf[a]])
            la = math.exp(mu + att[a] + catt[cf[a]] - dfn[h] - cdfn[cf[h]])
            out.append((lh, la))
        return out

    # Block coordinate Newton: refresh expected goals after every block so the
    # overlapping parameters (mu / conference / team) cannot drift together.
    for _ in range(iters):
        L = lams()
        g = sum(w * (hs - lh + as_ - la) for (h, a, hs, as_, w, ih), (lh, la) in zip(rows, L))
        hsum = sum(w * (lh + la) for (h, a, hs, as_, w, ih), (lh, la) in zip(rows, L))
        mu += g / hsum
        L = lams()
        g = sum(w * (hs - lh) * ih for (h, a, hs, as_, w, ih), (lh, la) in zip(rows, L))
        hsum = sum(w * lh * ih for (h, a, hs, as_, w, ih), (lh, la) in zip(rows, L))
        home += (g - kh * home) / (hsum + kh)
        for block, keyf, k in (("catt", "conf", kc), ("cdfn", "conf", kc), ("att", "team", kt), ("dfn", "team", kt)):
            L = lams()
            gr, cu = {}, {}
            for (h, a, hs, as_, w, ih), (lh, la) in zip(rows, L):
                kh_ = cf[h] if keyf == "conf" else h
                ka_ = cf[a] if keyf == "conf" else a
                if block in ("catt", "att"):
                    pairs = ((kh_, w * (hs - lh), w * lh), (ka_, w * (as_ - la), w * la))
                else:  # defence: higher = fewer goals conceded
                    pairs = ((ka_, -w * (hs - lh), w * lh), (kh_, -w * (as_ - la), w * la))
                for key, gg, cc in pairs:
                    gr[key] = gr.get(key, 0.0) + gg
                    cu[key] = cu.get(key, 0.0) + cc
            P = params[block]
            for key in P:
                P[key] += (gr.get(key, 0.0) - k * P[key]) / (cu.get(key, 0.0) + k)

    return {
        "mu": mu, "home": home,
        "att": att, "dfn": dfn, "catt": catt, "cdfn": cdfn, "conf": cf,
    }


def expected_goals(m, h, a, neutral=False):
    def A(t):
        return m["att"].get(t, 0.0) + m["catt"].get(m["conf"].get(t, "__none__"), 0.0)

    def D(t):
        return m["dfn"].get(t, 0.0) + m["cdfn"].get(m["conf"].get(t, "__none__"), 0.0)
    lh = math.exp(m["mu"] + (0 if neutral else m["home"]) + A(h) - D(a))
    la = math.exp(m["mu"] + A(a) - D(h))
    return lh, la


def outcome_probs(lh, la):
    ph = [math.exp(-lh) * lh ** k / math.factorial(k) for k in range(MAX_GOALS + 1)]
    pa = [math.exp(-la) * la ** k / math.factorial(k) for k in range(MAX_GOALS + 1)]
    w = d = l = 0.0
    best, best_p = (0, 0), -1
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            p = x * y
            if i > j: w += p
            elif i == j: d += p
            else: l += p
            if p > best_p:
                best, best_p = (i, j), p
    s = w + d + l
    return w / s, d / s, l / s, best


def strength(m, t):
    """Single number: expected goal difference vs an average team on neutral ground."""
    lh, la = expected_goals(m, t, "__avg__", neutral=True)
    return lh - la
