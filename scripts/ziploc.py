"""US ZIP code -> (latitude, longitude), for game weather (Graham, Nov 24).

The table comes from the US Census Bureau's ZIP Code Tabulation Area gazetteer (public domain): each ZCTA's
internal point, rounded to 2 decimals (~1 km, plenty for a forecast). Built once into data/zip_ll.json
(downloaded in the data run the first time it's missing) and kept in the repo.
"""
import io, json, os, urllib.request, zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
PATH = os.path.join(ROOT, "data", "zip_ll.json")
URLS = [f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{y}_Gazetteer/{y}_Gaz_zcta_national.zip" for y in (2025, 2024, 2023)]
_table = None


def _build():
    for url in URLS:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "SidelineStandings/1.0"}), timeout=60).read()
            z = zipfile.ZipFile(io.BytesIO(raw))
            text = z.read(z.namelist()[0]).decode("utf-8", "replace")
        except Exception as e:
            print("  ziploc: couldn't get", url, e)
            continue
        lines = text.lstrip("\ufeff").splitlines()
        head = [h.strip().lstrip("\ufeff").upper() for h in lines[0].split("\t")]
        col = lambda *names: next((i for i, h in enumerate(head) if h in names), None)
        gi, la, lo = col("GEOID", "GEOID20", "ZCTA5", "ZCTA5CE20"), col("INTPTLAT"), col("INTPTLONG")
        if None in (gi, la, lo):
            print("  ziploc: unexpected columns in", url, head[:8])
            continue
        out = {}
        for ln in lines[1:]:
            c = ln.split("\t")
            try:
                out[c[gi].strip()] = [round(float(c[la]), 2), round(float(c[lo]), 2)]
            except (ValueError, IndexError):
                pass
        if len(out) > 30000:
            os.makedirs(os.path.dirname(PATH), exist_ok=True)
            with open(PATH, "w") as f:
                json.dump(out, f, separators=(",", ":"), sort_keys=True)
            print(f"  ziploc: built {len(out)} ZIPs from {url}")
            return out
    return {}


def latlon(zip5):
    """(lat, lon) for a 5-digit ZIP, or None."""
    global _table
    if _table is None:
        try:
            with open(PATH) as f:
                _table = json.load(f)
        except Exception:
            _table = _build() if "--offline" not in os.sys.argv else {}
    return _table.get(str(zip5 or "")[:5])
