"""Command line for the whole pipeline.

  python -m app.pipeline extract            corpus -> out/rules.json
  python -m app.pipeline geocode            addresses -> out/jurisdictions.json
  python -m app.pipeline lookup [--as-of D] rules + addresses -> out/lookups.json
  python -m app.pipeline changes            tests -> out/changes.json
  python -m app.pipeline all                everything above
  python -m app.pipeline add-doc FILE --title T --state CA --city X [--county Y] [--kind ordinance] [--citation C] [--url U]
                                            drop a new law in, extract it unaided, rerun lookups and changes, append a change test
  python -m app.pipeline validate           schema-check the three output files
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import changes as changes_mod
from . import engine
from .corpus import CORPUS_DIR, MANIFEST, load_corpus, load_document, read_manifest
from .extract import extract_corpus
from .geocode import resolve_all
from .llm import get_llm
from .lookup import load_addresses, run_lookups, write_lookups
from .schema import DATA, OUT, JurisdictionStack, Rule, parse_date, today_iso

log = logging.getLogger("homerule")
RULES_FILE = OUT / "rules.json"
JUR_FILE = OUT / "jurisdictions.json"
LOOKUPS_FILE = OUT / "lookups.json"
CHANGES_FILE = OUT / "changes.json"
RUNLOG = OUT / "audit" / "runs.jsonl"


def _log_run(step: str, **info: Any) -> None:
    RUNLOG.parent.mkdir(parents=True, exist_ok=True)
    with RUNLOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"step": step, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **info}, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------------------- io
def load_rules(path: Path = RULES_FILE) -> list[Rule]:
    if not path.exists():
        return []
    return [Rule.model_validate(r) for r in json.loads(path.read_text())]


def write_rules(rules: list[Rule], path: Path = RULES_FILE) -> None:
    engine.resolve_precedence_targets(rules)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.model_dump() for r in rules], ensure_ascii=False, indent=1))


def load_stacks(path: Path = JUR_FILE) -> dict[str, JurisdictionStack]:
    if not path.exists():
        return {}
    return {k: JurisdictionStack.model_validate(v) for k, v in json.loads(path.read_text()).items()}


def write_stacks(stacks: dict[str, JurisdictionStack], path: Path = JUR_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: v.model_dump() for k, v in stacks.items()}, ensure_ascii=False, indent=1))


# ----------------------------------------------------------------------------- steps
def step_extract(doc_ids: Optional[list[str]] = None, verify: bool = True) -> list[Rule]:
    docs = load_corpus()
    if doc_ids:
        docs = [d for d in docs if d.doc_id in doc_ids]
    llm = get_llm()
    t0 = time.time()
    new_rules, audits = extract_corpus(docs, llm, verify=verify)
    if doc_ids:
        rules = [r for r in load_rules() if r.source_doc_id not in doc_ids] + new_rules
    else:
        rules = new_rules
    write_rules(rules)
    _log_run("extract", docs=len(docs), rules=len(new_rules), llm_calls=llm.calls, cache_hits=llm.cache_hits,
             model=f"{llm.provider}:{llm.model}", seconds=round(time.time() - t0, 1))
    print(f"extracted {len(new_rules)} rules from {len(docs)} documents ({llm.calls} model calls, {llm.cache_hits} cached) -> {RULES_FILE}")
    return rules


def step_geocode() -> dict[str, JurisdictionStack]:
    addresses = load_addresses()
    stacks = resolve_all(addresses)
    write_stacks(stacks)
    methods: dict[str, int] = {}
    for s in stacks.values():
        methods[s.method] = methods.get(s.method, 0) + 1
    _log_run("geocode", addresses=len(addresses), methods=methods)
    print(f"resolved {len(stacks)} addresses {methods} -> {JUR_FILE}")
    return stacks


def step_lookup(as_of: Optional[date] = None) -> None:
    as_of = as_of or date.today()
    rules, addresses, stacks = load_rules(), load_addresses(), load_stacks()
    missing = [a.address_id for a in addresses if a.address_id not in stacks]
    if missing:
        print(f"{len(missing)} addresses have no jurisdiction yet; run geocode first", file=sys.stderr)
    lookups = run_lookups(addresses, stacks, rules, as_of)
    write_lookups(lookups)
    counts: dict[str, int] = {}
    for l in lookups:
        for e in l.results:
            counts[e.result] = counts.get(e.result, 0) + 1
    _log_run("lookup", as_of=as_of.isoformat(), addresses=len(lookups), results=counts)
    print(f"evaluated {len(rules)} rules x {len(lookups)} addresses as of {as_of}: {counts} -> {LOOKUPS_FILE}")


def step_changes() -> None:
    rules, addresses, stacks = load_rules(), load_addresses(), load_stacks()
    tests = changes_mod.load_tests()
    records = changes_mod.run_all(tests, rules, addresses, stacks)
    changes_mod.write_changes(records)
    _log_run("changes", tests=[r.test_id for r in records])
    for r in records:
        print(f"{r.test_id}: {len(r.rule_ids)} rule(s); before {r.query_before.as_of_date} {r.query_before.status} ({len(r.query_before.affected_addresses)}); "
              f"after {r.query_after.as_of_date} {r.query_after.status} ({len(r.query_after.affected_addresses)}); conflicts {len(r.conflicts)}")
    print(f"-> {CHANGES_FILE}")


def step_add_doc(file: Path, title: str, state: str, city: str = "", county: str = "", kind: str = "ordinance",
                 citation: str = "", url: str = "", status_hint: str = "", test_id: str = "T6") -> dict[str, Any]:
    """The hour-16 path: new law in, no manual edits anywhere."""
    rows = read_manifest()
    n = max([int(r["doc_id"].split("_")[-1]) for r in rows if r.get("doc_id", "").startswith("doc_")] + [0]) + 1
    doc_id = f"doc_{n:03d}"
    dest_name = f"{doc_id}.txt"
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    text = Path(file).read_text(encoding="utf-8", errors="replace")
    (CORPUS_DIR / dest_name).write_text(text, encoding="utf-8")
    fieldnames = ["doc_id", "title", "kind", "state", "county", "city", "citation", "url", "retrieval_date", "file", "status", "status_hint", "added_at"]
    existing_fields = list(rows[0].keys()) if rows else fieldnames
    for f in fieldnames:
        if f not in existing_fields:
            existing_fields.append(f)
    row = {"doc_id": doc_id, "title": title, "kind": kind, "state": state.upper(), "county": county, "city": city, "citation": citation or title,
           "url": url or f"file://{Path(file).name}", "retrieval_date": today_iso(), "file": dest_name, "status": "ok",
           "status_hint": status_hint, "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=existing_fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in existing_fields})
        w.writerow({k: row.get(k, "") for k in existing_fields})
    rules = step_extract([doc_id])
    stacks = load_stacks()
    if not stacks:
        stacks = step_geocode()
    step_lookup()
    tests = changes_mod.load_tests()
    tests = [t for t in tests if t.get("test_id") != test_id]
    tests.append(changes_mod.test_for_new_document(doc_id, rules, test_id))
    changes_mod.TESTS_FILE.write_text(json.dumps(tests, ensure_ascii=False, indent=1))
    step_changes()
    new_rules = [r for r in rules if r.source_doc_id == doc_id]
    _log_run("add-doc", doc_id=doc_id, title=title, rules=[r.rule_id for r in new_rules])
    return {"doc_id": doc_id, "rules": [r.model_dump() for r in new_rules]}


def step_validate() -> bool:
    import jsonschema

    ok = True
    for name, schema_file in (("rules.json", "rules.schema.json"), ("lookups.json", "lookups.schema.json"), ("changes.json", "changes.schema.json")):
        p, s = OUT / name, DATA / "schema" / schema_file
        if not p.exists():
            print(f"{name}: missing")
            ok = False
            continue
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            print(f"{name}: invalid JSON: {e}")
            ok = False
            continue
        if s.exists():
            try:
                jsonschema.validate(data, json.loads(s.read_text()))
                print(f"{name}: {len(data)} records, schema OK")
            except jsonschema.ValidationError as e:
                print(f"{name}: schema error at {list(e.path)}: {e.message[:200]}")
                ok = False
        else:
            print(f"{name}: {len(data)} records (no schema file)")
    # cross-file checks
    if (OUT / "rules.json").exists() and (OUT / "lookups.json").exists():
        rules = {r["rule_id"]: r for r in json.loads((OUT / "rules.json").read_text())}
        bad = 0
        docs = {d.doc_id: d for d in load_corpus()}
        for l in json.loads((OUT / "lookups.json").read_text()):
            for e in l["results"]:
                if e["rule_id"] not in rules:
                    bad += 1
        notfound = sum(1 for r in rules.values() if r["source_doc_id"] in docs and r["quoted_span"] not in docs[r["source_doc_id"]].text)
        print(f"cross-check: {bad} dangling rule_ids in lookups; {notfound} quotes not found verbatim in corpus")
        ok = ok and bad == 0 and notfound == 0
    return ok


# ----------------------------------------------------------------------------- main
def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="homerule")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--doc", action="append", help="only these doc_ids")
    e.add_argument("--no-verify", action="store_true")
    sub.add_parser("geocode")
    lk = sub.add_parser("lookup")
    lk.add_argument("--as-of", default=None)
    sub.add_parser("changes")
    al = sub.add_parser("all")
    al.add_argument("--as-of", default=None)
    sub.add_parser("validate")
    ad = sub.add_parser("add-doc")
    ad.add_argument("file")
    ad.add_argument("--title", required=True)
    ad.add_argument("--state", required=True)
    ad.add_argument("--city", default="")
    ad.add_argument("--county", default="")
    ad.add_argument("--kind", default="ordinance")
    ad.add_argument("--citation", default="")
    ad.add_argument("--url", default="")
    ad.add_argument("--status-hint", default="")
    ad.add_argument("--test-id", default="T6")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        step_extract(a.doc, verify=not a.no_verify)
    elif a.cmd == "geocode":
        step_geocode()
    elif a.cmd == "lookup":
        step_lookup(parse_date(a.as_of))
    elif a.cmd == "changes":
        step_changes()
    elif a.cmd == "all":
        step_extract()
        step_geocode()
        step_lookup(parse_date(a.as_of))
        step_changes()
        step_validate()
    elif a.cmd == "validate":
        return 0 if step_validate() else 1
    elif a.cmd == "add-doc":
        res = step_add_doc(Path(a.file), a.title, a.state, a.city, a.county, a.kind, a.citation, a.url, a.status_hint, a.test_id)
        print(json.dumps({"doc_id": res["doc_id"], "rules": [r["rule_id"] for r in res["rules"]]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
