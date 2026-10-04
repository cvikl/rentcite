#!/usr/bin/env python3
"""Build data/addresses/addresses.csv: a sample of multifamily property addresses
with building facts for 9 cities, pulled from public open data (no API keys).

Run:  .venv/bin/python scripts/build_addresses.py [--per-city 52] [--seed 42] [--no-cache]

Raw API responses are cached under cache/addresses/ so re-runs are reproducible
offline. If a source is unreachable after retries, a clearly labelled synthetic
fallback is generated for that city (source == "synthetic_fallback").
See data/addresses/README.md for sources, licences and the exact queries.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data" / "addresses" / "addresses.csv"
CACHE_DIR = ROOT / "cache" / "addresses"

COLUMNS = ["address_id", "street", "postal_city", "state", "zip",
           "year_built", "units", "use_code", "source"]

TIMEOUT = 60
RETRIES = 3
HARD_CAP = 60

USE_CACHE = True


# ----------------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------------
def _cache_path(url: str, params: dict | None) -> Path:
    key = hashlib.sha1((url + "?" + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    return CACHE_DIR / f"{key}.json"


def fetch_json(url: str, params: dict | None = None, headers: dict | None = None, post: bool = False):
    """GET (or POST form) JSON with retries (3 x 60 s). Caches successful responses on disk."""
    cp = _cache_path(url, params)
    if USE_CACHE and cp.exists():
        return json.loads(cp.read_text())
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            if post:
                r = httpx.post(url, data=params, headers=headers, timeout=TIMEOUT, follow_redirects=True)
            else:
                r = httpx.get(url, params=params, headers=headers, timeout=TIMEOUT, follow_redirects=True)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "error" in data and "features" not in data:
                raise RuntimeError(f"API error: {str(data['error'])[:200]}")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(data))
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    attempt {attempt}/{RETRIES} failed for {url.split('?')[0]}: {str(e)[:120]}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError(f"unreachable after {RETRIES} attempts: {url} ({last})")


def arcgis_query(layer_url: str, where: str, out_fields: str, **extra):
    params = {"where": where, "outFields": out_fields, "f": "json", "returnGeometry": "false"}
    params.update(extra)
    # POST: long IN (...) lists exceed the GET URL limit (ArcGIS answers 404)
    data = fetch_json(layer_url.rstrip("/") + "/query", params, post=True)
    return [f["attributes"] for f in data.get("features", [])]


def arcgis_count(layer_url: str, where: str) -> int:
    data = fetch_json(layer_url.rstrip("/") + "/query", {"where": where, "returnCountOnly": "true", "f": "json"})
    return int(data.get("count", 0))


# ----------------------------------------------------------------------------
# Normalisation helpers
# ----------------------------------------------------------------------------
_SMALL = {"of", "the", "and", "de", "la", "del", "los", "las", "el", "en"}


def title_street(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    out = []
    for i, w in enumerate(s.split(" ")):
        if re.fullmatch(r"\d+(st|nd|rd|th)", w, re.I):
            out.append(w.lower().lstrip("0") or w.lower())  # EAS pads ordinals: 06TH -> 6th
        elif re.fullmatch(r"[NSEW]{1,2}", w, re.I):
            out.append(w.upper())
        elif w.lower() in _SMALL and i > 0:
            out.append(w.lower())
        elif "-" in w and not w[0].isdigit():
            out.append("-".join(p.capitalize() for p in w.split("-")))
        else:
            out.append(w.capitalize())
    return " ".join(out)


def clean_year(v) -> str:
    try:
        y = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return ""
    return str(y) if 1700 <= y <= 2030 else ""


def clean_units(v) -> str:
    try:
        u = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return ""
    return str(u) if u > 0 else ""


def clean_zip(v) -> str:
    s = re.sub(r"\D", "", str(v or ""))[:5]
    if len(s) < 5 and s:
        s = s.zfill(5)
    return s if re.fullmatch(r"\d{5}", s) else ""


def has_house_number(street: str) -> bool:
    return bool(re.match(r"^\d+", street.strip()))


def finalize(rows: list[dict], per_city: int, rng: random.Random) -> list[dict]:
    """Validate, dedupe, shuffle deterministically and cap."""
    seen, good = set(), []
    for r in rows:
        if not has_house_number(r["street"]) or not re.fullmatch(r"\d{5}", r["zip"]):
            continue
        key = (r["street"].lower(), r["zip"])
        if key in seen:
            continue
        seen.add(key)
        good.append(r)
    rng.shuffle(good)
    return good[: min(per_city, HARD_CAP)]


# ----------------------------------------------------------------------------
# City builders. Each returns a list of dicts with the non-id columns.
# ----------------------------------------------------------------------------
def build_san_francisco(per_city: int, rng: random.Random) -> list[dict]:
    src = "DataSF wv5m-vpq2 (roll 2025) + EAS 3mea-di5p"
    roll_url = "https://data.sf.gov/resource/wv5m-vpq2.json"
    rows = fetch_json(roll_url, {
        "$where": "closed_roll_year='2025' AND use_code='MRES' AND number_of_units>=5",
        "$select": "property_location,parcel_number,year_property_built,number_of_units,use_code,use_definition",
        "$order": "parcel_number",
        "$limit": 20000,
    })
    rng.shuffle(rows)
    cand = rows[: per_city * 3]
    # ZIP + canonical address come from the Enterprise Addressing System, joined on parcel_number
    eas_url = "https://data.sf.gov/resource/3mea-di5p.json"
    eas: dict[str, list[dict]] = {}
    pns = [r["parcel_number"] for r in cand]
    for i in range(0, len(pns), 50):
        chunk = pns[i:i + 50]
        q = ",".join(f"'{p}'" for p in chunk)
        for e in fetch_json(eas_url, {"$where": f"parcel_number in({q})",
                                      "$select": "parcel_number,address_number,street_full_street_name,zip_code",
                                      "$limit": 5000}):
            eas.setdefault(e["parcel_number"], []).append(e)
    out = []
    for r in cand:
        hits = eas.get(r["parcel_number"])
        if not hits:
            continue
        # roll property_location looks like "2926 2914 LARKIN  ST0000": the 2nd token is the low house number
        toks = r["property_location"].split()
        low = toks[1].lstrip("0") if len(toks) > 1 else ""
        pick = next((h for h in hits if h.get("address_number") == low), None)
        if pick is None:
            pick = min(hits, key=lambda h: int(re.sub(r"\D", "", h.get("address_number") or "0") or 0))
        if not pick.get("address_number"):
            continue
        out.append({
            "street": title_street(f"{pick['address_number']} {pick['street_full_street_name']}"),
            "postal_city": "San Francisco", "state": "CA", "zip": clean_zip(pick.get("zip_code")),
            "year_built": clean_year(r.get("year_property_built")),
            "units": clean_units(r.get("number_of_units")),
            "use_code": f"{r.get('use_code', '')} {r.get('use_definition', '')}".strip(),
            "source": src,
        })
    return finalize(out, per_city, rng)


def build_los_angeles(per_city: int, rng: random.Random) -> list[dict]:
    src = "LA County Assessor Parcel Data 2026 (ArcGIS Assessor_Parcel_Data_2026)"
    layer = "https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/Assessor_Parcel_Data_2026/FeatureServer/0"
    where = "SitusCity LIKE 'LOS ANGELES%' AND UseCode LIKE '05%'"
    total = arcgis_count(layer, where)
    fields = "SitusHouseNo,SitusFraction,SitusDirection,SitusStreet,SitusZIP5,YearBuilt,Units,UseCode,UseCodeDescChar2,UseCodeDescChar3"
    # the layer is ordered geographically by AIN, so take small pages at evenly spaced offsets
    pages = 8
    page_size = max(per_city, 30)
    out = []
    for k in range(pages):
        offset = int(total * k / pages)
        for a in arcgis_query(layer, where, fields, orderByFields="AIN", resultOffset=offset,
                              resultRecordCount=page_size):
            num = a.get("SitusHouseNo")
            if not num:
                continue
            frac = (a.get("SitusFraction") or "").strip()
            direc = (a.get("SitusDirection") or "").strip()
            street = " ".join(x for x in [f"{num}{(' ' + frac) if frac else ''}", direc, (a.get("SitusStreet") or "").strip()] if x)
            out.append({
                "street": title_street(street), "postal_city": "Los Angeles", "state": "CA",
                "zip": clean_zip(a.get("SitusZIP5")),
                "year_built": clean_year(a.get("YearBuilt")), "units": clean_units(a.get("Units")),
                "use_code": f"{a.get('UseCode', '')} {a.get('UseCodeDescChar2', '')}".strip(),
                "source": src,
            })
    return finalize(out, per_city, rng)


def build_san_diego(per_city: int, rng: random.Random) -> list[dict]:
    # The official SANDAG/SanGIS service (geo.sandag.org) refuses non-browser clients (HTTP 403),
    # so this uses a public ArcGIS Online republication of the SanGIS parcel layer.
    src = "SanGIS parcels via ArcGIS Online mirror (Hunsakersd SanGIS_Parcels, May 2025)"
    layer = "https://services7.arcgis.com/3kQCXzNCo2WKILzp/arcgis/rest/services/SanGIS_Parcels/FeatureServer/0"
    where = "SITUS_JURI='SD' AND UNITQTY>=5 AND ASR_LANDUS IN (14,15,16) AND SITUS_ZIP<>' '"
    total = arcgis_count(layer, where)
    fields = "SITUS_ADDR,SITUS_FRAC,SITUS_PRE_,SITUS_STRE,SITUS_SUFF,SITUS_POST,SITUS_COMM,SITUS_ZIP,YEAR_EFFEC,UNITQTY,ASR_LANDUS,NUCLEUS_US"
    pages, page_size = 8, max(per_city, 30)
    out = []
    for k in range(pages):
        offset = int(total * k / pages)
        for a in arcgis_query(layer, where, fields, orderByFields="APN", resultOffset=offset,
                              resultRecordCount=page_size):
            num = a.get("SITUS_ADDR")
            if not num:
                continue
            parts = [str(num) + ((" " + a["SITUS_FRAC"].strip()) if (a.get("SITUS_FRAC") or "").strip() else "")]
            for f in ("SITUS_PRE_", "SITUS_STRE", "SITUS_SUFF", "SITUS_POST"):
                v = (a.get(f) or "").strip()
                if v:
                    parts.append(v)
            yy = (a.get("YEAR_EFFEC") or "").strip()
            year = ""
            if re.fullmatch(r"\d{2}", yy) and yy != "00":
                y = int(yy)
                year = str(2000 + y if y <= 26 else 1900 + y)
            comm = (a.get("SITUS_COMM") or "").strip() or "SAN DIEGO"
            out.append({
                "street": title_street(" ".join(parts)), "postal_city": title_street(comm), "state": "CA",
                "zip": clean_zip(a.get("SITUS_ZIP")), "year_built": year,
                "units": clean_units(a.get("UNITQTY")),
                "use_code": f"{a.get('NUCLEUS_US', '')} (ASR_LANDUS {a.get('ASR_LANDUS', '')})".strip(),
                "source": src,
            })
    return finalize(out, per_city, rng)


def build_berkeley(per_city: int, rng: random.Random) -> list[dict]:
    src = "Berkeley Open Data rax9-nuvx (TaxParcel2017, Alameda County use codes)"
    url = "https://data.cityofberkeley.info/resource/rax9-nuvx.json"
    rows = fetch_json(url, {
        # keep the query minimal: the portal's WAF answers 403 to "IS NOT NULL" / $order variants
        "$where": "use_code in('2400','2500','2600','2700')",
        "$select": "situs_stree,situs_str_1,situs_city,situs_zip,use_code,apn",
        "$limit": 5000,
    })
    out = []
    for r in rows:
        num = (r.get("situs_stree") or "").strip()
        name = (r.get("situs_str_1") or "").strip()
        if not num or not name:
            continue
        out.append({
            "street": title_street(f"{num} {name}"), "postal_city": title_street(r.get("situs_city") or "Berkeley"),
            "state": "CA", "zip": clean_zip(r.get("situs_zip")), "year_built": "", "units": "",
            "use_code": r.get("use_code", ""), "source": src,
        })
    return finalize(out, per_city, rng)


def build_boston(per_city: int, rng: random.Random) -> list[dict]:
    rid = "ee73430d-96c0-423e-ad21-c4cfb54c8961"
    src = f"Analyze Boston property-assessment FY2026 ({rid[:8]})"
    sql = (f'SELECT "ST_NUM","ST_NAME","CITY","ZIP_CODE","YR_BUILT","RES_UNITS","NUM_BLDGS","LU","LU_DESC" '
           f'FROM "{rid}" WHERE "LU" IN (\'A\',\'R4\') LIMIT 20000')
    data = fetch_json("https://data.boston.gov/api/3/action/datastore_search_sql", {"sql": sql})
    out = []
    for r in data["result"]["records"]:
        num = (r.get("ST_NUM") or "").strip()
        name = (r.get("ST_NAME") or "").strip()
        if not re.fullmatch(r"\d+(\s*-\s*\d+)?[A-Z]?", num) or not name:
            continue
        out.append({
            "street": title_street(f"{num.replace(' ', '')} {name}"),
            "postal_city": title_street(r.get("CITY") or "Boston"), "state": "MA",
            "zip": clean_zip(r.get("ZIP_CODE")), "year_built": clean_year(r.get("YR_BUILT")),
            "units": clean_units(r.get("RES_UNITS")),
            "use_code": f"{r.get('LU', '')}: {r.get('LU_DESC', '')}".strip(": "), "source": src,
        })
    return finalize(out, per_city, rng)


def build_cambridge(per_city: int, rng: random.Random) -> list[dict]:
    src = "Cambridge Open Data eey2-rv59 (Property Database FY2026)"
    url = "https://data.cambridgema.gov/resource/eey2-rv59.json"
    apt_classes = "('4-8-UNIT-APT','>8-UNIT-APT','AFFORDABLE APT')"
    rows = fetch_json(url, {
        "$where": f"yearofassessment='2026' AND propertyclass in{apt_classes}",
        "$select": "address,owner_address,owner_city,owner_zip,condition_yearbuilt,interior_numunits,propertyclass,stateclasscode,map_lot",
        "$order": "map_lot", "$limit": 5000,
    })
    # The property database has no situs ZIP. Build a street -> (house number, ZIP) index from
    # owner-occupied Cambridge parcels (owner mailing address == parcel address) in the same dataset.
    occ = fetch_json(url, {
        "$where": "yearofassessment='2026' AND upper(address)=owner_address AND owner_city='CAMBRIDGE' AND owner_zip like '021%'",
        "$select": "address,owner_zip", "$limit": 20000,
    })
    index: dict[str, list[tuple[int, str]]] = {}

    def split(addr: str):
        m = re.match(r"^\s*(\d+)[\dA-Za-z\-/ ]*?\s+(.+)$", addr or "")
        if not m:
            return None, None
        return int(m.group(1)), m.group(2).strip().upper()

    for o in occ:
        n, st = split(o.get("address"))
        z = clean_zip(o.get("owner_zip"))
        if n is not None and z:
            index.setdefault(st, []).append((n, z))
    out = []
    for r in rows:
        addr = (r.get("address") or "").strip()
        n, st = split(addr)
        if n is None:
            continue
        zipc = ""
        if (r.get("owner_address") or "").strip().upper() == addr.upper() and (r.get("owner_city") or "").upper() == "CAMBRIDGE":
            zipc = clean_zip(r.get("owner_zip"))
        if not zipc and st in index:
            zipc = min(index[st], key=lambda t: abs(t[0] - n))[1]
        out.append({
            "street": title_street(addr), "postal_city": "Cambridge", "state": "MA", "zip": zipc,
            "year_built": clean_year(r.get("condition_yearbuilt")), "units": clean_units(r.get("interior_numunits")),
            "use_code": f"{r.get('stateclasscode', '')} {r.get('propertyclass', '')}".strip(), "source": src,
        })
    return finalize(out, per_city, rng)


NJ_PARCELS = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0"
NJ_ADDRPTS = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/AddressPoints/FeatureServer/0"


def build_nj(pcl_mun: str, default_city: str, per_city: int, rng: random.Random) -> list[dict]:
    src = "NJOGIS Parcels_Composite_NJ_WM (MOD-IV, class 4C) + NJ AddressPoints"
    where = f"PCL_MUN='{pcl_mun}' AND PROP_CLASS='4C'"
    fields = "PROP_LOC,YR_CONSTR,DWELL,BLDG_DESC,PCL_GUID,PAMS_PIN"
    rows = arcgis_query(NJ_PARCELS, where, fields, orderByFields="PAMS_PIN", resultRecordCount=2000)
    rows = [r for r in rows if r.get("PCL_GUID") and re.match(r"^\d", (r.get("PROP_LOC") or "").strip())]
    rng.shuffle(rows)
    cand = rows[: per_city * 2]
    # situs postal city + ZIP from the state address points, joined on parcel GUID
    pts: dict[str, list[dict]] = {}
    guids = [r["PCL_GUID"] for r in cand]
    for i in range(0, len(guids), 50):
        q = ",".join(f"'{g}'" for g in guids[i:i + 50])
        for p in arcgis_query(NJ_ADDRPTS, f"PCL_GUID IN ({q})", "FULLADDR,POST_COMM,POST_CODE,PCL_GUID,ADD_NUMBER",
                              resultRecordCount=2000):
            pts.setdefault(p["PCL_GUID"], []).append(p)
    out = []
    for r in cand:
        hits = pts.get(r["PCL_GUID"])
        if not hits:
            continue
        loc = re.sub(r"\.+$", "", (r.get("PROP_LOC") or "").strip())
        low = int(re.match(r"^(\d+)", loc).group(1))
        pick = next((h for h in hits if h.get("ADD_NUMBER") == low), hits[0])
        units = clean_units(r.get("DWELL"))
        if not units or int(units) < 2:
            m = re.search(r"(\d+)\s*U(?![A-Z])", r.get("BLDG_DESC") or "")
            units = clean_units(m.group(1)) if m else ""
        out.append({
            "street": title_street(loc), "postal_city": (pick.get("POST_COMM") or default_city).strip(),
            "state": "NJ", "zip": clean_zip(pick.get("POST_CODE")),
            "year_built": clean_year(r.get("YR_CONSTR")), "units": units,
            "use_code": f"4C {r.get('BLDG_DESC') or ''}".strip(), "source": src,
        })
    return finalize(out, per_city, rng)


# ----------------------------------------------------------------------------
# Synthetic fallback (only when a source is unreachable). Clearly labelled.
# ----------------------------------------------------------------------------
FALLBACK = {
    "San Francisco": ("CA", ["Mission St", "Valencia St", "Geary Blvd", "Folsom St", "Clement St", "Haight St",
                             "Divisadero St", "Polk St", "Larkin St", "Taraval St", "Irving St", "Fillmore St"],
                      ["94102", "94103", "94109", "94110", "94115", "94117", "94118", "94121", "94122", "94131"]),
    "Los Angeles": ("CA", ["Wilshire Blvd", "Sunset Blvd", "Vermont Ave", "Western Ave", "Pico Blvd", "Olympic Blvd",
                           "Normandie Ave", "Figueroa St", "Hollywood Blvd", "Ventura Blvd", "Sepulveda Blvd", "Crenshaw Blvd"],
                    ["90004", "90005", "90006", "90017", "90019", "90026", "90028", "90036", "90057", "91403"]),
    "San Diego": ("CA", ["University Ave", "El Cajon Blvd", "Adams Ave", "Park Blvd", "Garnet Ave", "Mission Blvd",
                         "Imperial Ave", "Clairemont Mesa Blvd", "Balboa Ave", "Broadway", "Market St", "30th St"],
                  ["92101", "92102", "92103", "92104", "92105", "92109", "92110", "92115", "92116", "92117"]),
    "Berkeley": ("CA", ["Shattuck Ave", "Telegraph Ave", "University Ave", "San Pablo Ave", "College Ave", "Dwight Way",
                        "Durant Ave", "Bancroft Way", "Haste St", "Channing Way", "Milvia St", "Sacramento St"],
                 ["94702", "94703", "94704", "94705", "94707", "94709", "94710"]),
    "Jersey City": ("NJ", ["Kennedy Blvd", "Bergen Ave", "Summit Ave", "Newark Ave", "Montgomery St", "Grand St",
                           "Ocean Ave", "West Side Ave", "Palisade Ave", "Central Ave", "Grove St", "Communipaw Ave"],
                    ["07302", "07304", "07305", "07306", "07307", "07310"]),
    "Hoboken": ("NJ", ["Washington St", "Hudson St", "Bloomfield St", "Garden St", "Park Ave", "Willow Ave",
                       "Clinton St", "Grand St", "Adams St", "Jefferson St", "Madison St", "Monroe St"], ["07030"]),
    "Newark": ("NJ", ["Broad St", "Market St", "Clinton Ave", "Springfield Ave", "Bloomfield Ave", "Mt Prospect Ave",
                      "Ferry St", "South Orange Ave", "Elizabeth Ave", "Bergen St", "Central Ave", "Frelinghuysen Ave"],
               ["07102", "07103", "07104", "07105", "07106", "07107", "07108", "07112", "07114"]),
    "Boston": ("MA", ["Commonwealth Ave", "Beacon St", "Tremont St", "Washington St", "Dorchester Ave", "Blue Hill Ave",
                      "Centre St", "Huntington Ave", "Massachusetts Ave", "Columbia Rd", "Hyde Park Ave", "Bennington St"],
               ["02115", "02116", "02118", "02119", "02121", "02124", "02125", "02128", "02130", "02134"]),
    "Cambridge": ("MA", ["Massachusetts Ave", "Cambridge St", "Broadway", "Harvard St", "Prospect St", "Western Ave",
                         "Putnam Ave", "Rindge Ave", "Concord Ave", "Huron Ave", "Pearl St", "Mt Auburn St"],
                  ["02138", "02139", "02140", "02141", "02142"]),
}


def build_synthetic(city: str, per_city: int, rng: random.Random) -> list[dict]:
    state, streets, zips = FALLBACK[city]
    out = []
    while len(out) < per_city:
        street = f"{rng.randint(10, 3999)} {rng.choice(streets)}"
        units = rng.choice([5, 6, 8, 9, 12, 16, 20, 24, 36, 48, 72, 120])
        year = rng.choice(list(range(1890, 1940)) * 3 + list(range(1940, 1990)) * 2 + list(range(1990, 2024)))
        out.append({"street": street, "postal_city": city, "state": state, "zip": rng.choice(zips),
                    "year_built": str(year), "units": str(units), "use_code": "multifamily (synthetic)",
                    "source": "synthetic_fallback"})
    return finalize(out, per_city, rng)


# ----------------------------------------------------------------------------
CITIES = [
    ("Los Angeles", lambda n, rng: build_los_angeles(n, rng)),
    ("San Francisco", lambda n, rng: build_san_francisco(n, rng)),
    ("San Diego", lambda n, rng: build_san_diego(n, rng)),
    ("Berkeley", lambda n, rng: build_berkeley(n, rng)),
    ("Jersey City", lambda n, rng: build_nj("0906", "Jersey City", n, rng)),
    ("Hoboken", lambda n, rng: build_nj("0905", "Hoboken", n, rng)),
    ("Newark", lambda n, rng: build_nj("0714", "Newark", n, rng)),
    ("Boston", lambda n, rng: build_boston(n, rng)),
    ("Cambridge", lambda n, rng: build_cambridge(n, rng)),
]


def main() -> int:
    global USE_CACHE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-city", type=int, default=52, help="rows per city (hard cap 60)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-cache", action="store_true", help="ignore cache/addresses/ and refetch")
    ap.add_argument("--out", type=Path, default=OUT_CSV)
    args = ap.parse_args()
    USE_CACHE = not args.no_cache

    all_rows: list[dict] = []
    summary = []
    for city, builder in CITIES:
        rng = random.Random(f"{args.seed}:{city}")
        print(f"== {city}", file=sys.stderr)
        try:
            rows = builder(args.per_city, rng)
            if len(rows) < max(10, args.per_city // 3):
                raise RuntimeError(f"only {len(rows)} usable rows")
            kind = "real"
        except Exception as e:  # noqa: BLE001
            print(f"   FAILED ({str(e)[:160]}); generating synthetic fallback", file=sys.stderr)
            rows = build_synthetic(city, args.per_city, random.Random(f"{args.seed}:{city}:synthetic"))
            kind = "synthetic_fallback"
        summary.append((city, len(rows), kind, rows[0]["source"] if rows else ""))
        all_rows.extend(rows)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for i, r in enumerate(all_rows, 1):
            w.writerow({"address_id": f"addr_{i:04d}", **{k: r.get(k, "") for k in COLUMNS[1:]}})
    print(f"\nwrote {len(all_rows)} rows to {args.out}", file=sys.stderr)
    for city, n, kind, src in summary:
        print(f"  {city:14s} {n:3d}  {kind:18s} {src}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
