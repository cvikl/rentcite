"""Self-scorer: an approximation of the judges' score.py, for self-testing against a dev key.

The official script is the spec; when it is on disk (starter/score.py) run that instead. This one
mirrors the brief's components so the team sees the same failure modes early:

  extraction (25)   key rules matched by jurisdiction + category + citation tokens; field accuracy on
                    effective_date, status, key_value
  coverage (20)     per key address: expected rule results vs ours; missing an applies costs 2,
                    unknown earns 0.5 when the key says applies
  citations (15)    share of "applies" entries whose quoted_span is found verbatim in the corpus
  changes (15)      Jaccard overlap of affected sets per test, plus the T3 conflict flag

Dev key format (data/dev_key.json): {"rules": [{"jurisdiction": {"state","city"?}, "category", "citation",
"effective_date"?, "status"?, "key_value"?}], "addresses": {"addr_0001": {"<category>": "applies"|...}},
"changes": {"T1": {"affected": [...], "conflict": true|false}}}
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .corpus import load_corpus
from .schema import DATA, OUT, norm_place

KEY = DATA / "dev_key.json"


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+(?:\.[0-9a-z]+)*", (s or "").lower()) if len(t) > 1 and t not in {"code", "section", "sec", "the", "of", "and", "ch", "art"}}


def _cite_match(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    nums_a = {t for t in ta if any(c.isdigit() for c in t)}
    nums_b = {t for t in tb if any(c.isdigit() for c in t)}
    if nums_a and nums_b:
        return bool(nums_a & nums_b)
    return len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.5


def score(key: dict[str, Any], rules: list[dict], lookups: list[dict], changes: list[dict], corpus_text: dict[str, str]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    # ---- extraction
    kr = key.get("rules", [])
    matched, field_hits, field_total = 0, 0, 0
    details = []
    for k in kr:
        kj = k.get("jurisdiction", {})
        cands = [r for r in rules if r["category"] == k["category"] and r["jurisdiction"]["state"] == kj.get("state")
                 and norm_place(r["jurisdiction"].get("city") or "") == norm_place(kj.get("city") or "")
                 and _cite_match(r["source_citation"], k.get("citation", ""))]
        if cands:
            matched += 1
            r = cands[0]
            for f in ("effective_date", "status"):
                if k.get(f) is not None:
                    field_total += 1
                    field_hits += int(r.get(f) == k[f])
            if k.get("key_value"):
                field_total += 1
                kv = (r.get("key_value") or {}).get("value", "")
                field_hits += int(bool(_tokens(kv) & _tokens(k["key_value"])))
            details.append({"key": k.get("citation"), "matched": r["rule_id"]})
        else:
            details.append({"key": k.get("citation"), "matched": None})
    ext = 0.0
    if kr:
        ext = 25 * (0.6 * matched / len(kr) + 0.4 * (field_hits / field_total if field_total else 1.0))
    report["extraction"] = {"points": round(ext, 2), "of": 25, "matched": matched, "key_rules": len(kr), "field_accuracy": f"{field_hits}/{field_total}", "details": details}
    # ---- coverage
    ka = key.get("addresses", {})
    by_addr = {l["address_id"]: l for l in lookups}
    cov_pts, cov_max = 0.0, 0.0
    cov_details = []
    for aid, expected in ka.items():
        ours = by_addr.get(aid, {"results": []})
        got = {}
        for e in ours["results"]:
            got.setdefault(e["category"], e["result"].replace(" ", "_"))
        for cat, exp in expected.items():
            exp_n = exp.replace(" ", "_")
            cov_max += 2 if exp_n == "applies" else 1
            g = got.get(cat, "omit")
            if g == exp_n:
                cov_pts += 2 if exp_n == "applies" else 1
            elif exp_n == "applies" and g == "unknown":
                cov_pts += 1
            elif exp_n == "omit" and g == "unknown":
                cov_pts += 0.5
            cov_details.append({"address": aid, "category": cat, "expected": exp_n, "got": g})
    cov = 20 * (cov_pts / cov_max) if cov_max else 0.0
    report["coverage"] = {"points": round(cov, 2), "of": 20, "raw": f"{cov_pts}/{cov_max}", "details": cov_details}
    # ---- citations
    applies = [e for l in lookups for e in l["results"] if e["result"].replace(" ", "_") == "applies"]
    ok = sum(1 for e in applies if e.get("quoted_span") and e["quoted_span"] in corpus_text.get(e.get("source_doc_id", ""), ""))
    cit = 15 * (ok / len(applies)) if applies else 0.0
    report["citations"] = {"points": round(cit, 2), "of": 15, "verbatim": ok, "applies_entries": len(applies)}
    # ---- changes
    kc = key.get("changes", {})
    by_test = {c["test_id"]: c for c in changes}
    ch_pts = 0.0
    ch_details = []
    for tid, exp in kc.items():
        ours = by_test.get(tid)
        a, b = set(exp.get("affected", [])), set((ours or {}).get("affected_addresses", []))
        j = 1.0 if not a and not b else len(a & b) / max(1, len(a | b))
        pts = j
        if "conflict" in exp:
            got_conf = bool((ours or {}).get("conflicts"))
            pts = 0.7 * j + 0.3 * (1.0 if got_conf == exp["conflict"] else 0.0)
        ch_pts += pts
        ch_details.append({"test": tid, "jaccard": round(j, 3), "expected": len(a), "got": len(b)})
    ch = 15 * (ch_pts / len(kc)) if kc else 0.0
    report["changes"] = {"points": round(ch, 2), "of": 15, "details": ch_details}
    report["total_auto"] = round(ext + cov + cit + ch, 2)
    report["of"] = 75
    return report


def main() -> int:
    if not KEY.exists():
        print(f"no dev key at {KEY}; drop the starter pack's key there (see app/score.py docstring for the format)")
        return 1
    key = json.loads(KEY.read_text())
    rules = json.loads((OUT / "rules.json").read_text()) if (OUT / "rules.json").exists() else []
    lookups = json.loads((OUT / "lookups.json").read_text()) if (OUT / "lookups.json").exists() else []
    changes = json.loads((OUT / "changes.json").read_text()) if (OUT / "changes.json").exists() else []
    corpus = {d.doc_id: d.text for d in load_corpus()}
    rep = score(key, rules, lookups, changes, corpus)
    (OUT / "score_report.json").write_text(json.dumps(rep, indent=1))
    print(f"SELF-SCORE (approximation of the official script)  total {rep['total_auto']} / 75")
    for k in ("extraction", "coverage", "citations", "changes"):
        r = rep[k]
        print(f"  {k:<11} {r['points']:>6} / {r['of']}   " + ", ".join(f"{a}={b}" for a, b in r.items() if a not in ("points", "of", "details")))
    print(f"-> {OUT / 'score_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
