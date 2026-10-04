"""Module B, step 2: evaluate every rule against every address and write lookups.json."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import engine
from .schema import (APPLIES, CATEGORIES, DATA, OMIT, OUT, PENDING, UNKNOWN, Address, JurisdictionStack, Lookup,
                     ResultEntry, Rule, norm_place, parse_date, result_label)

ADDRESSES_CSV = DATA / "addresses" / "addresses.csv"
USE_CODE_TYPES = {
    # light normalisation of assessor use descriptions into property_type; unknown stays None
    "apartment": "multifamily", "apartments": "multifamily", "multi": "multifamily", "multifamily": "multifamily",
    "multi-family": "multifamily", "4c": "multifamily", "flats": "multifamily", "dwelling": "multifamily",
    "condo": "condominium", "condominium": "condominium", "single": "single_family", "sfr": "single_family",
    "duplex": "duplex", "two family": "duplex", "three family": "multifamily",
}


def load_addresses(path: Path = ADDRESSES_CSV) -> list[Address]:
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = {k.strip(): (v or "").strip() for k, v in row.items()}
            if not row.get("address_id"):
                continue
            out.append(Address(address_id=row["address_id"], street=row.get("street", ""), postal_city=row.get("postal_city", ""),
                               state=row.get("state", "").upper(), zip=row.get("zip", ""),
                               year_built=_int(row.get("year_built")), units=_int(row.get("units")),
                               use_code=row.get("use_code") or None, source=row.get("source") or None))
    return out


def _int(v: Optional[str]) -> Optional[int]:
    try:
        n = int(float(v)) if v not in (None, "") else None
    except ValueError:
        return None
    return n if n and n > 0 else None


def property_type(use_code: Optional[str]) -> Optional[str]:
    if not use_code:
        return None
    s = use_code.lower()
    for k, v in USE_CODE_TYPES.items():
        if k in s:
            return v
    return None


def building_facts(a: Address, as_of: date, overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw: dict[str, Any] = {"year_built": a.year_built, "units": a.units, "property_type": property_type(a.use_code)}
    if overrides:
        raw.update({k: v for k, v in overrides.items() if v not in (None, "")})
    return engine.derive_facts(raw, as_of)


def evaluate_address(a: Address, stack: JurisdictionStack, rules: list[Rule], as_of: date,
                     overrides: Optional[dict[str, Any]] = None) -> Lookup:
    facts = building_facts(a, as_of, overrides)
    st = {"state": stack.state, "county": stack.county, "city": stack.city}
    entries: list[ResultEntry] = []
    for r in rules:
        res, reason, missing = engine.decide(r, facts, as_of, st, rules)
        if res == OMIT:
            continue
        conflicts = engine.conflicts_for(r, facts, as_of, st, rules)
        conf = r.confidence * (0.6 + 0.4 * stack.confidence)
        if res == UNKNOWN:
            conf *= 0.7
        entries.append(ResultEntry(
            rule_id=r.rule_id, category=r.category, result=result_label(res), reason=reason,
            citation=r.source_citation, quoted_span=r.quoted_span, source_doc_id=r.source_doc_id,
            conflict_flag=bool(conflicts), conflict_reason="; ".join(c["reason"] for c in conflicts) or None,
            confidence=round(conf, 2), missing_facts=missing, plain_language=r.requirement, plain_language_es=r.requirement_es,
            status=r.status, effective_date=r.effective_date, level=r.jurisdiction.level))
    order = {APPLIES: 0, UNKNOWN: 1, "superseded": 2, "not_yet_effective": 3, PENDING: 4}
    entries.sort(key=lambda e: (list(CATEGORIES).index(e.category), order.get(e.result.replace(" ", "_"), 9), e.level != "city"))
    return Lookup(address_id=a.address_id, as_of_date=as_of.isoformat(),
                  jurisdiction_stack={"state": stack.state, "county": stack.county, "city": stack.city,
                                      "method": stack.method, "confidence": stack.confidence},
                  building_facts={k: v for k, v in facts.items()}, results=entries,
                  no_rule_findings=no_rule_findings(stack, rules))


def no_rule_findings(stack: JurisdictionStack, rules: list[Rule]) -> list[dict[str, Any]]:
    """Categories with no enacted rule at a given level for this jurisdiction: a positive finding, not a gap."""
    out = []
    levels = [("state", stack.state), ("city", stack.city)]
    for level, name in levels:
        if not name:
            continue
        for cat in CATEGORIES:
            has = any(r.category == cat and r.status == "enacted" and r.jurisdiction.level == level
                      and r.jurisdiction.state == stack.state
                      and (level == "state" or norm_place(r.jurisdiction.city or "") == norm_place(name)) for r in rules)
            if not has:
                out.append({"category": cat, "level": level, "jurisdiction": name, "finding": "no_rule_at_this_level"})
    return out


def run_lookups(addresses: list[Address], stacks: dict[str, JurisdictionStack], rules: list[Rule], as_of: date) -> list[Lookup]:
    return [evaluate_address(a, stacks[a.address_id], rules, as_of) for a in addresses if a.address_id in stacks]


def write_lookups(lookups: list[Lookup], path: Path = OUT / "lookups.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([l.model_dump() for l in lookups], ensure_ascii=False, indent=1))
