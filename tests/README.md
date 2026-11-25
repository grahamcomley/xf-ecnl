# Tests

Kept here so any session can run them before a push. None of them touch prod or UAT: they run against
a local copy of the site with the API mocked. They hold no passwords or user data (the PEM in
node/weather.mjs is generated fresh on each run).

## Setup (once per session)
1. Offline site copy: `cp -r . /tmp/xfo` (or rsync the repo there), then put a published `site/data/`
   in `/tmp/xfo/site/data/`. The UI tests were written against the real data snapshot of Nov 23, 2026
   (they use e.g. team `u17b-131393`, conf `u17b-4284-40525` with the Phoenix event Nov 20–22, and XF teams
   `u17b-62277`, `u16b-82130`, `u13g-92130`, `a19b-9594`). Without network: `python tests/make_fixture.py &&
   python scripts/update.py --offline` builds older fixture data (Nov 6), which some date-based checks won't match.
2. Copy the page you're testing: `cp site/index.html /tmp/xfo/site/index.html`
3. Serve it: `cd /tmp/xfo/site && nohup python3 -m http.server 8767 &`
4. Playwright (Python) with Chrome at `/usr/bin/google-chrome`.

## UI (Playwright, `python3 tests/ui/<file>.py`)
- `full.py` — the full app check (66 points): tabs, rows, layout, wrapping, sign-in states. Run before any push.
- `twx.py`, `twx2.py` — game weather: row tag, rain icon at 40%+, drop-downs, staleness, no-field tournaments, open bracket slots.
- `tadm2.py` — Admin: sections start closed, Setup last, one line per saved key.
- `tapp.py` — iPhone Safari: "Get the iPhone app" sheet/rows, App Store banner tag; Share my teams; shared-teams landing; Android unchanged.
- `tulink.py` — links open the app: fake Capacitor App plugin (cold start and while open).
- `tjust.py`, `tschedui.py`, `tsheet.py`, `tpass.py`, `t61.py` — "Just posted" label, schedule-change tags, team sheet, sign-in pass, older layout checks.
- `app_store_shots.py` — makes the App Store screenshots (1206 x 2622) into /tmp/ss/ with sample weather.

## Python (data scripts, `python3 tests/py/<file>.py`)
- `tsched.py`, `tnewev.py` — schedule-change and new-event-schedule detection in scripts/alerts.py.
- `twxneed.py` — which field ZIPs get weather (scripts/alerts.py weather_needs).
These load scripts from `/home/claude/xf-ecnl/scripts`; change the path if the repo is elsewhere.

## Node (API modules, `node tests/node/<file>.mjs`)
- `weather.mjs` — api/weather.js with a fake Apple service. Copy `api/weather.js` and `api/push.js` next to it first.
- `alerts_sched.mjs`, `alerts_newev.mjs` — api/alerts.js schedule/new-event alerts. Need a copy of api/alerts.js
  (plus log.js, pickem.js, push.js) next to them, with the send function stubbed to push into `globalThis.SENT`
  and an export line for the functions the test imports.
