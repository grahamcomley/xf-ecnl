import importlib.util, json, os, sys, tempfile
from datetime import date
sys.path.insert(0, "/home/claude/xf-ecnl/scripts")
import ziploc; ziploc._table = {"85001": [33.45, -112.07], "98012": [47.84, -122.2]}
spec = importlib.util.spec_from_file_location("alerts", "/home/claude/xf-ecnl/scripts/alerts.py")
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
A.OUT = tempfile.mkdtemp()
confs = {"x": {"games": [{"date": "2026-11-25", "zip": "98012", "tz": "America/Los_Angeles"}, {"date": "2026-11-20", "zip": "98012", "hs": 1},
  {"date": "2026-12-20", "zip": "98012"}, {"date": "2026-11-26", "zip": None}, {"date": "2026-11-27", "zip": "00000"}],
  "events": [{"games": [{"date": "2026-11-21", "zip": "85001", "tz": "America/Phoenix"}, {"date": "2026-11-23", "zip": "85001", "tz": "America/Phoenix"}, {"date": "2026-11-22", "zip": "85001", "bad": True}]}]}}
n = A.weather_needs(confs, date(2026, 11, 18))
print(n)
assert n == {"85001": [33.45, -112.07, "2026-11-21", "2026-11-23", "America/Phoenix"], "98012": [47.84, -122.2, "2026-11-25", "2026-11-25", "America/Los_Angeles"]}
assert json.load(open(os.path.join(A.OUT, "wxneed.json"))) == n
print("PASS weather_needs")
