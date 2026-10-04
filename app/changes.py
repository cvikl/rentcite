"""Module C: change tracking.

A change test selects rules (by state, category, and words in the citation or title, or by the
document they came from) and two as-of dates. The engine is run on every address at both dates;
the affected set is every address the selected rules reach (coverage not false, inside the
jurisdiction). Struck and repealed laws reach nobody by construction. Conflicts come from the same
generic detector the lookups use. Nothing here is specific to T1-T6.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from . import engine
from .schema import DATA, OMIT, OUT, Address, ChangeQuery, ChangeRecord, JurisdictionStack, Rule, parse_date, result_label
from .lookup import building_facts

TESTS_FILE = DATA / "changes" / "tests.json"


def load_tests(path: Path = TESTS_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def select_rules(sel: dict[str, Any], rules: list[Rule]) -> list[Rule]:
    out = []
    pat = re.compile(sel["match"], re.I) if sel.get("match") else None
    for r in rules:
        if sel.get("state") and r.jurisdiction.state != sel["state"].upper():
            continue
        if sel.get("category") and r.category != sel["category"]:
            continue
        if sel.get("level") and r.jurisdiction.level != sel["level"]:
            continue
        if sel.get("city") and (r.jurisdiction.city or "").lower() != sel["city"].lower():
            continue
        if sel.get("status") and r.status != sel["status"]:
            continue
        if sel.get("doc_ids") and r.source_doc_id not in sel["doc_ids"]:
            continue
        if pat and not (pat.search(r.source_citation) or pat.search(r.title) or pat.search(r.requirement) or pat.search(r.quoted_span)):
            continue
        out.append(r)
    return out


def _reach(rule: Rule, a: Address, stack: JurisdictionStack, as_of: date) -> bool:
    if rule.status in ("struck", "repealed"):
        return False
    st = {"state": stack.state, "county": stack.county, "city": stack.city}
    if not engine.in_jurisdiction(rule.jurisdiction, st):
        return False
    cov, _ = engine.coverage_outcome(rule, building_facts(a, as_of))
    return cov != engine.FALSE


def _query(selected: list[Rule], rules: list[Rule], addresses: list[Address], stacks: dict[str, JurisdictionStack], as_of: date) -> tuple[ChangeQuery, list[dict[str, Any]]]:
    affected: list[str] = []
    statuses: Counter[str] = Counter()
    conflicts: dict[str, dict[str, Any]] = {}
    for a in addresses:
        stack = stacks.get(a.address_id)
        if not stack:
            continue
        st = {"state": stack.state, "county": stack.county, "city": stack.city}
        facts = building_facts(a, as_of)
        hit = False
        for r in selected:
            if not _reach(r, a, stack, as_of):
                continue
            hit = True
            res, _, _ = engine.decide(r, facts, as_of, st, rules)
            statuses[res] += 1
            for c in engine.conflicts_for(r, facts, as_of, st, rules):
                conflicts.setdefault(c["with_rule_id"], {"with_rule_id": c["with_rule_id"], "reason": c["reason"], "rule_id": r.rule_id})
        if hit:
            affected.append(a.address_id)
    if not selected:
        status = "no_rule"
    elif all(r.status in ("struck", "repealed") for r in selected):
        status = selected[0].status
    elif statuses:
        status = result_label(statuses.most_common(1)[0][0])
    else:
        status = "no_addresses_in_scope"
    return ChangeQuery(as_of_date=as_of.isoformat(), status=status, affected_addresses=affected), list(conflicts.values())


def run_test(test: dict[str, Any], rules: list[Rule], addresses: list[Address], stacks: dict[str, JurisdictionStack]) -> ChangeRecord:
    selected = select_rules(test.get("select", {}), rules)
    before = parse_date(test.get("before")) or date.today()
    after = parse_date(test.get("after"))
    if after is None:
        effs = [parse_date(r.effective_date) for r in selected if parse_date(r.effective_date)]
        after = (max(effs) + timedelta(days=1)) if effs else before
    qb, cb = _query(selected, rules, addresses, stacks, before)
    qa, ca = _query(selected, rules, addresses, stacks, after)
    conflicts = {c["with_rule_id"]: c for c in cb + ca}
    affected = qa.affected_addresses if selected and selected[0].status not in ("struck", "repealed") else []
    notes = test.get("notes")
    if not selected:
        notes = (notes + " " if notes else "") + "No rule matched the selector in rules.json."
    return ChangeRecord(test_id=test["test_id"], description=test.get("description", ""), rule_ids=[r.rule_id for r in selected],
                        query_before=qb, query_after=qa, affected_addresses=affected,
                        conflicts=list(conflicts.values()), notes=notes)


def run_all(tests: list[dict[str, Any]], rules: list[Rule], addresses: list[Address], stacks: dict[str, JurisdictionStack]) -> list[ChangeRecord]:
    return [run_test(t, rules, addresses, stacks) for t in tests]


def write_changes(records: list[ChangeRecord], path: Path = OUT / "changes.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.model_dump() for r in records], ensure_ascii=False, indent=1))


def test_for_new_document(doc_id: str, rules: list[Rule], test_id: str = "T6", today: Optional[date] = None) -> dict[str, Any]:
    """Build a change test for a document that just entered the corpus (the hour-16 drop)."""
    today = today or date.today()
    sel = [r for r in rules if r.source_doc_id == doc_id]
    effs = [parse_date(r.effective_date) for r in sel if parse_date(r.effective_date)]
    after = (max(effs) + timedelta(days=1)) if effs else today
    return {"test_id": test_id, "description": f"New document {doc_id}: " + (sel[0].title if sel else "no rules extracted"),
            "select": {"doc_ids": [doc_id]}, "before": today.isoformat(), "after": after.isoformat(),
            "notes": "Generated automatically when the document was added; no manual edits."}
