"""Check every text/background color pair used by site/index.html meets WCAG AA (4.5:1)."""
PAIRS = [  # (text, background, where)
    ("#e8eaed", "#0d1015", "body text"), ("#e8eaed", "#161a21", "card text"), ("#a3acb9", "#161a21", "muted on card"),
    ("#a3acb9", "#1e232c", "muted on stat"), ("#a3acb9", "#0d1015", "muted on page"), ("#8ab4ff", "#161a21", "links"),
    ("#8ab4ff", "#1e232c", "links on list"), ("#ff6b7d", "#07090c", "brand"), ("#ffffff", "#c8102e", "red chip / pill"),
    ("#e5e7eb", "#2f3743", "league chip"), ("#d1d5db", "#252b35", "past chip"), ("#e8eaed", "#3a1520", "our row"),
    ("#e8eaed", "#18202c", "chance cell"), ("#e8eaed", "#1c2533", "chance cell alt"), ("#e8eaed", "#12161c", "zebra row"),
    ("#4ade80", "#161a21", "up delta"), ("#fb7185", "#161a21", "down delta"), ("#4ade80", "#1f2530", "root-for on gray card"),
    ("#fb7185", "#1f2530", "loss on gray card"), ("#ffffff", "#2563eb", "bar: win"), ("#ffffff", "#4b5563", "bar: draw"),
    ("#ffffff", "#c2410c", "bar: loss"), ("#86efac", "#14361f", "good pill"), ("#fcd34d", "#3a2a07", "medium pill"),
    ("#fda4af", "#3d1218", "low pill"), ("#111827", "#e5e7eb", "matters tag"), ("#ffffff", "#3a4250", "our pick button"),
    ("#111827", "#f3f4f6", "your pick button"), ("#e8eaed", "#1e232c", "toggle button"), ("#fcd34d", "#2a2108", "warning"),
    ("#ffffff", "#15803d", "W badge"), ("#ffffff", "#b91c1c", "L badge"), ("#e8eaed", "#172036", "picks bar"),
    ("#e8eaed", "#1f2530", "matters card"), ("#fde047", "#1e232c", "star"),
]


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = sorted([lum(a), lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


if __name__ == "__main__":
    bad = 0
    for fg, bg, where in PAIRS:
        r = ratio(fg, bg)
        ok = r >= 4.5
        bad += not ok
        print(f"{'ok ' if ok else 'LOW'} {r:5.2f}  {where}")
    raise SystemExit(1 if bad else 0)
