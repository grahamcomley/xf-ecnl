"""Match team names from other sites (e.g. Surf Cup) to our ECNL / ECNL RL teams.

Rules (conservative on purpose):
  - only names that say ECNL or ECNL RL are matched, and the tier must agree;
  - every word of our team's club name must appear in the other name;
  - a team number (1, 2) must agree when either side has one;
  - if two of our teams fit equally well, nothing is matched and it goes on the review list.
"""
import re

AGE = r"\b(?:[bg]u-?\d{1,2}|u-?\d{1,2}[bg]?|[bg]?20\d\d(?:/(?:20)?\d\d)?|[bg]?\d\d/\d\d|[bg]\d\d)\b"
NOISE = {"fc", "sc", "soccer", "club", "academy", "the", "ca", "wa", "or", "az", "nv", "ut", "tx", "co", "id"}


def tier(name):
    n = name.lower().replace("-", " ")
    if re.search(r"\becnl\s*rl\b|\brl\b|regional league", n):
        return "RL"
    if re.search(r"\becnl\b", n):
        return "ECNL"
    return None


def tokens(name):
    n = name.lower().replace("ecnl-rl", " ").replace("-", " ")
    n = re.sub(AGE, " ", n)
    n = re.sub(r"\b(ecnl|rl|regional|league)\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return [t for t in n.split() if t]


def number(toks):
    nums = [t for t in toks if t in ("1", "2", "3")]
    return nums[-1] if nums else None


def match_all(other_names, our_names, aliases=None):
    """other_names: {other_id: name}; our_names: {our_id: name}.
    Returns (mapping other_id -> our_id, review list)."""
    aliases = aliases or {}
    by_name = {v: k for k, v in our_names.items()}
    ours = []
    for tid, nm in our_names.items():
        t = tier(nm)
        if not t:
            continue
        toks = tokens(nm)
        club = [x for x in toks if x not in NOISE and x not in ("1", "2", "3")]
        if club:
            ours.append((tid, nm, t, set(club), number(toks)))
    mapping, review = {}, []
    for oid, onm in other_names.items():
        if onm in aliases:
            if aliases[onm] in by_name:
                mapping[oid] = by_name[aliases[onm]]
            continue
        t = tier(onm)
        if not t:
            continue
        otoks = tokens(onm)
        oset, onum = set(otoks), number(otoks)
        cands = []
        for tid, nm, tt, club, num in ours:
            if tt != t or not club <= oset:
                continue
            if (num or onum) and (num or "1") != (onum or "1"):
                continue
            cands.append((len(club), tid, nm))
        if not cands:
            review.append({"name": onm, "reason": "no ECNL/RL team with that club name"})
            continue
        cands.sort(reverse=True)
        if len(cands) > 1 and cands[0][0] == cands[1][0]:
            review.append({"name": onm, "reason": "ambiguous", "candidates": [c[2] for c in cands[:4]]})
            continue
        mapping[oid] = cands[0][1]
    return mapping, review
