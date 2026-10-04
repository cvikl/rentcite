"""FastAPI app: JSON API over the pipeline outputs plus the static front end.

Nothing here decides anything. Every answer is engine.decide() over rules.json; the as-of date and
optional fact overrides (the renter answering a missing-fact question) are inputs to the same code.
"""
from __future__ import annotations

import json
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import changes as changes_mod
from .corpus import load_corpus, read_manifest
from .geocode import resolve
from .llm import LLMUnavailable, get_llm
from .lookup import evaluate_address, load_addresses
from .pipeline import CHANGES_FILE, LOOKUPS_FILE, RULES_FILE, load_rules, load_stacks, step_add_doc
from .schema import CATEGORIES, FACT_FIELDS, OUT, Address, JurisdictionStack, parse_date

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
DISCLAIMER = "Homerule shows what the law says and where. It is not legal advice."

app = FastAPI(title="Homerule", version="0.1.0", docs_url="/api/docs", redoc_url=None)
_lock = threading.Lock()
_state: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    with _lock:
        mtime = RULES_FILE.stat().st_mtime if RULES_FILE.exists() else 0
        if _state.get("mtime") != mtime or not _state:
            rules = load_rules()
            addresses = load_addresses()
            _state.update({
                "mtime": mtime, "rules": rules, "rules_by_id": {r.rule_id: r for r in rules},
                "addresses": addresses, "addr_by_id": {a.address_id: a for a in addresses}, "stacks": load_stacks(),
                "docs": {d.doc_id: d for d in load_corpus()}, "manifest": read_manifest(),
            })
        return _state


@app.get("/api/health")
def health():
    s = _load()
    llm = get_llm()
    return {"ok": True, "rules": len(s["rules"]), "addresses": len(s["addresses"]), "documents": len(s["docs"]),
            "provider": llm.provider, "model": llm.model, "disclaimer": DISCLAIMER}


@app.get("/api/meta")
def meta():
    s = _load()
    cities: dict[str, int] = {}
    for a in s["addresses"]:
        st = s["stacks"].get(a.address_id)
        key = f"{st.city}, {st.state}" if st and st.city else f"{a.postal_city}, {a.state}"
        cities[key] = cities.get(key, 0) + 1
    return {"categories": CATEGORIES, "fact_fields": FACT_FIELDS, "cities": cities, "disclaimer": DISCLAIMER,
            "today": date.today().isoformat(), "documents": [{"doc_id": r["doc_id"], "title": r["title"], "citation": r["citation"],
                                                             "url": r["url"], "retrieval_date": r["retrieval_date"], "state": r["state"],
                                                             "city": r.get("city", ""), "kind": r["kind"], "status": r.get("status", "ok")}
                                                            for r in s["manifest"]]}


@app.get("/api/addresses")
def addresses(q: str = "", city: str = "", limit: int = 50):
    s = _load()
    out = []
    ql = q.lower().strip()
    for a in s["addresses"]:
        st = s["stacks"].get(a.address_id)
        label = f"{a.street}, {a.postal_city}, {a.state} {a.zip}"
        if ql and ql not in label.lower() and ql not in a.address_id:
            continue
        if city and not (st and st.city and st.city.lower() == city.lower()):
            continue
        out.append({"address_id": a.address_id, "label": label, "year_built": a.year_built, "units": a.units, "use_code": a.use_code,
                    "jurisdiction": st.model_dump() if st else None})
        if len(out) >= limit:
            break
    return out


def _lookup_payload(a: Address, st: JurisdictionStack, as_of: date, overrides: Optional[dict[str, Any]]) -> dict[str, Any]:
    s = _load()
    lk = evaluate_address(a, st, s["rules"], as_of, overrides)
    payload = lk.model_dump()
    payload["address"] = {"address_id": a.address_id, "street": a.street, "postal_city": a.postal_city, "state": a.state, "zip": a.zip,
                          "year_built": a.year_built, "units": a.units, "use_code": a.use_code, "source": a.source}
    payload["jurisdiction_stack"].update({"matched_address": st.matched_address, "lat": st.lat, "lon": st.lon})
    for e in payload["results"]:
        r = s["rules_by_id"][e["rule_id"]]
        d = s["docs"].get(r.source_doc_id)
        e["rule"] = {"title": r.title, "key_value": r.key_value.model_dump() if r.key_value else None, "penalty": r.penalty,
                     "coverage_conditions": r.coverage_conditions.model_dump(), "exemptions": [x.model_dump() for x in r.exemptions],
                     "precedence": r.precedence.model_dump(), "jurisdiction": r.jurisdiction.model_dump(), "status": r.status,
                     "effective_date": r.effective_date, "superseded_date": r.superseded_date, "source_url": r.source_url,
                     "retrieval_date": r.retrieval_date, "source_char_offset": r.source_char_offset, "model": r.model,
                     "extracted_at": r.extracted_at, "verification": r.verification, "rule_confidence": r.confidence,
                     "doc_title": d.title if d else None}
    payload["disclaimer"] = DISCLAIMER
    return payload


@app.get("/api/lookup/{address_id}")
def lookup(address_id: str, as_of: str = "", facts: str = ""):
    s = _load()
    a = s["addr_by_id"].get(address_id)
    if not a:
        raise HTTPException(404, "unknown address_id")
    st = s["stacks"].get(address_id)
    if not st:
        raise HTTPException(409, "address not geocoded yet; run the geocode step")
    d = parse_date(as_of) or date.today()
    overrides = json.loads(facts) if facts else None
    return _lookup_payload(a, st, d, overrides)


@app.get("/api/lookup-free")
def lookup_free(street: str, city: str, state: str, zip: str = "", as_of: str = "", year_built: Optional[int] = None,
                units: Optional[int] = None, facts: str = ""):
    """Any address: geocode live (Census), then the same engine."""
    a = Address(address_id="adhoc", street=street, postal_city=city, state=state.upper(), zip=zip or "", year_built=year_built, units=units)
    st = resolve(a)
    d = parse_date(as_of) or date.today()
    overrides = json.loads(facts) if facts else None
    return _lookup_payload(a, st, d, overrides)


@app.get("/api/rules")
def rules(state: str = "", category: str = ""):
    s = _load()
    out = []
    for r in s["rules"]:
        if state and r.jurisdiction.state != state.upper():
            continue
        if category and r.category != category:
            continue
        out.append(r.model_dump())
    return out


@app.get("/api/rules/{rule_id}")
def rule(rule_id: str):
    s = _load()
    r = s["rules_by_id"].get(rule_id)
    if not r:
        raise HTTPException(404, "unknown rule")
    d = s["docs"].get(r.source_doc_id)
    payload = r.model_dump()
    if d:
        lo, hi = r.source_char_offset
        payload["context_before"] = d.text[max(0, lo - 600):lo]
        payload["context_after"] = d.text[hi:hi + 600]
        payload["doc"] = {"title": d.title, "url": d.url, "retrieval_date": d.retrieval_date, "citation": d.citation, "kind": d.kind}
    return payload


@app.get("/api/changes")
def changes():
    if not CHANGES_FILE.exists():
        return []
    return json.loads(CHANGES_FILE.read_text())


@app.get("/api/changes/{test_id}/addresses")
def change_addresses(test_id: str):
    s = _load()
    recs = json.loads(CHANGES_FILE.read_text()) if CHANGES_FILE.exists() else []
    rec = next((r for r in recs if r["test_id"] == test_id), None)
    if not rec:
        raise HTTPException(404, "unknown test")
    out = []
    for aid in rec["affected_addresses"]:
        a = s["addr_by_id"].get(aid)
        st = s["stacks"].get(aid)
        if a:
            out.append({"address_id": aid, "label": f"{a.street}, {a.postal_city}, {a.state} {a.zip}", "city": st.city if st else None,
                        "lat": st.lat if st else None, "lon": st.lon if st else None})
    return out


@app.get("/api/timeline")
def timeline(address_id: str, start: str = "2024-01-01", end: str = "2028-01-01"):
    """Rule results at every date where something changes for this address (the Time Machine)."""
    s = _load()
    a = s["addr_by_id"].get(address_id)
    st = s["stacks"].get(address_id)
    if not a or not st:
        raise HTTPException(404, "unknown address")
    dates = {parse_date(start), parse_date(end)}
    for r in s["rules"]:
        for d in (r.effective_date, r.superseded_date):
            pd = parse_date(d)
            if pd:
                dates.add(pd)
    points = []
    for d in sorted(x for x in dates if x):
        lk = evaluate_address(a, st, s["rules"], d)
        points.append({"date": d.isoformat(), "results": {e.rule_id: e.result for e in lk.results}})
    return points


@app.get("/api/audit")
def audit():
    log = OUT / "audit" / "extraction_log.jsonl"
    runs = OUT / "audit" / "runs.jsonl"
    ex = [json.loads(l) for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
    rn = [json.loads(l) for l in runs.read_text().splitlines() if l.strip()] if runs.exists() else []
    return {"extractions": ex[-200:], "runs": rn[-100:]}


@app.get("/api/llm-record/{cache_key}")
def llm_record(cache_key: str):
    p = ROOT / "cache" / "llm" / f"{cache_key}.json"
    if not p.exists() or not cache_key.isalnum():
        raise HTTPException(404, "no such record")
    return json.loads(p.read_text())


@app.post("/api/add-doc")
async def add_doc(file: UploadFile = File(...), title: str = Form(...), state: str = Form(...), city: str = Form(""),
                  county: str = Form(""), kind: str = Form("ordinance"), citation: str = Form(""), url: str = Form("")):
    """The hour-16 path, from the browser: the file goes through the unmodified pipeline."""
    data = await file.read()
    with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        res = step_add_doc(tmp_path, title, state, city, county, kind, citation, url)
    except LLMUnavailable as e:
        return JSONResponse(status_code=503, content={"error": "llm_unavailable", "detail": str(e)})
    finally:
        tmp_path.unlink(missing_ok=True)
    _state.clear()
    recs = json.loads(CHANGES_FILE.read_text()) if CHANGES_FILE.exists() else []
    res["change"] = next((r for r in recs if r["test_id"] == "T6"), None)
    return res


@app.get("/api/outputs/{name}")
def outputs(name: str):
    if name not in ("rules.json", "lookups.json", "changes.json"):
        raise HTTPException(404)
    p = OUT / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/json", filename=name)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
