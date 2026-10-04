"""Module B, step 1: resolve the legal jurisdiction of an address.

Primary: the Census Geocoder (no key, public). It returns the incorporated place and county the
point falls in, which is the legal city, not the postal city. Fallback when the geocoder has no
match: a small table of postal neighbourhoods that are legally part of a city (Dorchester is
Boston), then the postal city itself at low confidence. Every result is cached on disk.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import httpx

from .schema import ROOT, Address, JurisdictionStack, norm_place

log = logging.getLogger("homerule.geocode")
CACHE_DIR = ROOT / "cache" / "geocode"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"

# Postal cities that are neighbourhoods of a legal city. Used only when the geocoder cannot match.
POSTAL_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    # (state, postal city) -> (county, legal city)
    **{("MA", n): ("Suffolk", "Boston") for n in ("dorchester", "roxbury", "jamaica plain", "brighton", "allston", "charlestown",
                                                   "east boston", "hyde park", "mattapan", "roslindale", "south boston", "west roxbury",
                                                   "roxbury crossing", "mission hill", "dorchester center", "boston", "chestnut hill")},
    ("MA", "cambridge"): ("Middlesex", "Cambridge"),
    ("NJ", "jersey city"): ("Hudson", "Jersey City"),
    ("NJ", "hoboken"): ("Hudson", "Hoboken"),
    ("NJ", "newark"): ("Essex", "Newark"),
    ("CA", "san francisco"): ("San Francisco", "San Francisco"),
    ("CA", "berkeley"): ("Alameda", "Berkeley"),
    ("CA", "san diego"): ("San Diego", "San Diego"),
    ("CA", "santa ana"): ("Orange", "Santa Ana"),
    **{("CA", n): ("Los Angeles", "Los Angeles") for n in ("los angeles", "hollywood", "north hollywood", "van nuys", "sherman oaks",
                                                           "encino", "studio city", "canoga park", "woodland hills", "reseda", "northridge",
                                                           "venice", "san pedro", "wilmington", "sylmar", "sun valley", "tarzana", "chatsworth",
                                                           "granada hills", "pacoima", "panorama city", "valley village", "winnetka", "west hills",
                                                           "mission hills", "porter ranch", "playa del rey", "harbor city", "tujunga", "sunland",
                                                           "eagle rock", "highland park", "boyle heights", "echo park", "silver lake", "los feliz",
                                                           "westwood", "brentwood", "pacific palisades", "mar vista", "palms", "west los angeles")},
}
STATE_FIPS = {"06": "CA", "34": "NJ", "25": "MA"}


def _cache_path(q: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(q.encode()).hexdigest() + ".json")


def _census(oneline: str, client: httpx.Client) -> Optional[dict[str, Any]]:
    p = _cache_path(oneline)
    if p.exists():
        return json.loads(p.read_text())
    params = {"address": oneline, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "format": "json"}
    data = None
    for attempt in range(3):
        try:
            r = client.get(CENSUS_URL, params=params, timeout=45)
            if r.status_code == 200:
                data = r.json()
                break
        except httpx.HTTPError as e:
            log.warning("census attempt %d failed for %r: %s", attempt + 1, oneline, e)
        time.sleep(1.5 * (attempt + 1))
    if data is None:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return data


def _from_census(data: dict[str, Any]) -> Optional[JurisdictionStack]:
    matches = (data.get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    m = matches[0]
    g = m.get("geographies") or {}
    states = g.get("States") or []
    counties = g.get("Counties") or []
    places = g.get("Incorporated Places") or []
    subs = g.get("County Subdivisions") or []
    state = STATE_FIPS.get((states[0].get("GEOID") or "")[:2]) if states else None
    if not state:
        st = (states[0].get("STUSAB") if states else None) or ""
        state = st or None
    county = counties[0].get("BASENAME") if counties else None
    city = places[0].get("BASENAME") if places else None
    if not city and subs:
        # New England towns are county subdivisions; Boston and Cambridge are also places, but keep the fallback
        city = subs[0].get("BASENAME")
    coords = m.get("coordinates") or {}
    return JurisdictionStack(state=state or "", county=county, city=city, method="census_geocoder",
                             confidence=0.95 if city else 0.6, matched_address=m.get("matchedAddress"),
                             lat=coords.get("y"), lon=coords.get("x"))


def _fallback(a: Address) -> JurisdictionStack:
    key = (a.state.upper(), norm_place(a.postal_city))
    if key in POSTAL_ALIASES:
        county, city = POSTAL_ALIASES[key]
        return JurisdictionStack(state=a.state.upper(), county=county, city=city, method="postal_alias_table", confidence=0.7)
    return JurisdictionStack(state=a.state.upper(), county=None, city=a.postal_city.title(), method="postal_city", confidence=0.4)


def resolve(a: Address, client: Optional[httpx.Client] = None) -> JurisdictionStack:
    oneline = f"{a.street}, {a.postal_city}, {a.state} {a.zip}"
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": "homerule/0.1 (hackathon; census geocoder)"})
    try:
        data = _census(oneline, client)
    finally:
        if own:
            client.close()
    st = _from_census(data) if data else None
    if st and st.state and st.city:
        return st
    fb = _fallback(a)
    if st and st.state and st.county and not fb.county:
        fb.county = st.county
    fb.method = fb.method + ("+census_nomatch" if data else "+census_unreachable")
    return fb


def resolve_all(addresses: list[Address], workers: int = 6) -> dict[str, JurisdictionStack]:
    out: dict[str, JurisdictionStack] = {}
    with httpx.Client(headers={"User-Agent": "homerule/0.1 (hackathon; census geocoder)"}) as client:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for a, st in zip(addresses, ex.map(lambda x: resolve(x, client), addresses)):
                out[a.address_id] = st
    return out
