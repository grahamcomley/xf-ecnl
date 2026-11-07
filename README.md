# xf-ecnl

Standings, schedules and predictions for ECNL teams, rebuilt automatically from the
official ECNL schedule data.

**Site:** https://grahamcomley.github.io/xf-ecnl/

## How it works

- `.github/workflows/update.yml` runs every 2 hours on game weekends and twice a day
  otherwise. It runs `scripts/update.py`, saves the data, and publishes `site/`.
- `scripts/update.py` pulls every ECNL Boys U16 game (all conferences plus national
  events) and the Girls RL U13 Northwest games, rates every team, and writes `site/data/*.json`.
- `scripts/model.py` holds the ratings. Every team has an attack and a defence rating,
  and every conference has a shared offset, so results flow through the whole network
  ("A beat B, who beat C..."). Recent games count more, blowouts are capped at 5 goals,
  and teams with few games stay close to average.
- `site/index.html` is the whole website. Simulations and what-if toggles run in the browser.

## Add a team

Copy a block in `config.json` → `competitions` and change the IDs. The IDs come from the
team's ECNL schedule page: `app.athleteone.com/public/event/<eventID>/schedules-standings`.

## Run it yourself

    python scripts/update.py              # live
    python tests/make_fixture.py && python scripts/update.py --offline   # test data only

Unofficial. Data is from the public ECNL / AthleteOne schedule.
