"""Module A: rule extraction.

The model reads a document presented as numbered chunks and returns structured rule candidates.
It never types the quote: it names a chunk and the first and last words of the span, and the span
is sliced from the raw text in code (corpus.slice_quote). A second verifier call checks that the
structured fields are consistent with the sliced quote and may correct fields, never quotes.
Everything the model said is kept in cache/llm (the audit log) and summarised in out/audit/.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from .corpus import Chunk, Document, render_chunks, slice_quote
from .llm import LLM, get_llm
from .schema import CATEGORIES, FACT_FIELDS, OPERATORS, OUT, Condition, Exemption, Jurisdiction, KeyValue, Precedence, Rule

log = logging.getLogger("homerule.extract")
AUDIT_DIR = OUT / "audit"
WINDOW_CHARS = 90_000

CATEGORY_GUIDE = {
    "rent_increase_limit": "caps or formulas on rent increases, rent stabilization/rent control ordinances, AND state laws that prohibit or preempt local rent control (record the prohibition as a rule: the requirement is that no local rent cap may exist)",
    "just_cause_eviction": "limits on the grounds for eviction or non-renewal, notice requirements for those grounds, relocation assistance tied to no-fault evictions",
    "security_deposit": "maximum security deposit, what counts toward it, return deadlines and interest if they are part of the cap provision",
    "application_screening_fee": "caps on application or screening fees, receipts and refunds, limits on upfront charges a landlord or broker may demand at move-in, broker fee rules",
    "screening_restriction": "limits on criminal-history screening (fair chance), source-of-income protections, timing rules for screening steps",
    "algorithmic_rent_setting": "bans or limits on algorithmic devices, revenue management or common pricing algorithms using nonpublic competitor data to set rent, including definitions, prohibited conduct and penalties",
}

SYSTEM = """You are an extraction engine for a housing-law navigator. You read one legal document and return every distinct rule it contains that falls into six categories, as JSON. You never give legal advice, never invent provisions and never paraphrase a quote: for quotes you only point at a chunk and copy its first and last words exactly.
Rules of the job:
1. One record per distinct obligation, cap, prohibition or protection. A section with a cap AND a separate exemption list is one rule with exemptions, not two rules. A section that sets several different obligations in different categories gives several records.
2. Skip provisions outside the six categories (e.g. habitability, lead paint, condo conversion).
3. Status: "enacted" for law in force or chaptered/approved acts even if their operative date is in the future; "pending" for bills not yet passed; "struck" for measures the text says were invalidated, struck, removed from the ballot or failed; "repealed" if the text says repealed.
4. Dates: ISO YYYY-MM-DD. effective_date is the date the rule as described takes effect (if the text gives an operative date for the latest amendment, use that). Use null when the text states no date. Never guess a date.
5. Coverage conditions describe WHICH BUILDINGS or TENANCIES the rule reaches, as a boolean tree, using only the allowed fact fields. If the rule covers every rental in its jurisdiction, use {"type":"ALWAYS","clauses":[]}. Express "certificate of occupancy before DATE" as certificate_of_occupancy_date < "DATE". Express "built within the last N years" as building_age_years < N. Express unit-count tests with units. Do not put the jurisdiction itself in the conditions.
6. Exemptions: each with a description and its own condition tree. Exemptions whose test is not expressible with the allowed fields (e.g. "tenant is a government employee") still get a record with an empty ALWAYS-false shape: use {"type":"AND","clauses":[{"field":"owner_type","operator":"==","value":"__unknowable__"}]} so code reports unknown rather than guessing.
7. Precedence must come from explicit words in the text (preempt, notwithstanding any local ordinance, shall not apply where a local ordinance, supersede, in addition to). If the text is silent use "stacks_with" and target_scope "none".
8. requirement: 1-2 plain sentences a renter can act on (English). requirement_es: the same in Spanish. key_value: the single number or formula at the heart of the rule (e.g. label "annual cap", value "5% + CPI, max 10%").
9. quote: pick the 1-4 sentences that state the rule itself (the cap, the prohibition, the amount). "chunk" is the chunk id in square brackets. "start_words" are the first 4-8 words of the span copied exactly as written in that chunk; "end_words" the last 4-8 words copied exactly. Never alter spelling, punctuation or case.
10. confidence 0-1: how sure you are that this is a real rule in this category with correct fields.
Output only JSON: {"rules":[...]}"""


def _schema_text() -> str:
    fields = "\n".join(f"  - {k}: {v}" for k, v in FACT_FIELDS.items())
    cats = "\n".join(f"  - {k}: {CATEGORY_GUIDE[k]}" for k in CATEGORIES)
    return f"""Allowed categories:
{cats}

Allowed fact fields for conditions:
{fields}
Allowed operators: {', '.join(OPERATORS)}. Values: numbers, ISO dates, strings, booleans, or lists for in/not_in.

Record shape:
{{
  "category": "<category>",
  "title": "short name, e.g. 'Statewide rent cap (AB 1482)'",
  "requirement": "...", "requirement_es": "...",
  "key_value": {{"label": "...", "value": "..."}} or null,
  "coverage_conditions": {{"type": "AND|OR|NOT|ALWAYS", "clauses": [ {{"field": "...", "operator": "...", "value": ..., "note": "words from the text"}} or nested tree ]}},
  "exemptions": [ {{"description": "...", "conditions": {{...tree...}}}} ],
  "effective_date": "YYYY-MM-DD" or null,
  "superseded_date": "YYYY-MM-DD" or null,
  "status": "enacted|pending|struck|repealed",
  "precedence": {{"relationship": "supersedes|yields_to|stacks_with|none", "target_scope": "state|county|city|local|none", "source_language": "exact words or null"}},
  "penalty": "..." or null,
  "source_citation": "e.g. Cal. Civ. Code § 1947.12(a)(1)",
  "quote": {{"chunk": "c12", "start_words": "...", "end_words": "..."}},
  "confidence": 0.0-1.0
}}"""


VERIFY_SYSTEM = """You are a verifier. For each extracted rule you receive the structured record and the exact quote that was sliced from the source. Check that the quote supports the category, the key value, the effective date, the status and the coverage conditions. Reply with JSON {"checks":[{"index": i, "supported": true|false, "issues": ["..."], "corrections": {field: value}, "confidence": 0.0-1.0}]}.
Corrections may only touch: category, key_value, effective_date, status, coverage_conditions, exemptions, precedence, penalty, requirement, requirement_es, source_citation. Never rewrite the quote. If the quote does not state the rule at all set supported=false. Do not add rules."""


def _window_chunks(doc: Document) -> list[list[Chunk]]:
    windows: list[list[Chunk]] = []
    cur: list[Chunk] = []
    size = 0
    for c in doc.chunks:
        if size + len(c.text) > WINDOW_CHARS and cur:
            windows.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += len(c.text)
    if cur:
        windows.append(cur)
    return windows


def _doc_header(doc: Document) -> str:
    j = doc.state + (f" / {doc.county} County" if doc.county else "") + (f" / {doc.city}" if doc.city else "")
    return (f"Document {doc.doc_id}: {doc.title}\nKind: {doc.kind}. Jurisdiction: {j} ({doc.level} level). "
            f"Citation: {doc.citation}. Source: {doc.url}. Retrieved: {doc.retrieval_date}.")


def _prompt(doc: Document, chunks: list[Chunk], part: str) -> str:
    return (f"{_doc_header(doc)}\n{part}\n\n{_schema_text()}\n\nThe document, as numbered chunks:\n\n"
            f"{render_chunks(doc, chunks)}\n\nReturn {{\"rules\": [...]}} now.")


CAT_CODE = {"rent_increase_limit": "RENT", "just_cause_eviction": "EVICT", "security_deposit": "DEPOSIT",
            "application_screening_fee": "FEE", "screening_restriction": "SCREEN", "algorithmic_rent_setting": "ALGO"}


def _rule_id(doc: Document, category: str, n: int) -> str:
    place = (doc.city or doc.county or "STATE").upper()
    place = re.sub(r"[^A-Z]", "", place)[:6] or "STATE"
    return f"{doc.state}-{place}-{CAT_CODE.get(category, 'RULE')}-{doc.doc_id.split('_')[-1]}-{n:02d}"


def _coerce_condition(raw: Any) -> Condition:
    if not raw or not isinstance(raw, dict):
        return Condition()
    t = str(raw.get("type", "ALWAYS")).upper()
    if t not in ("AND", "OR", "NOT", "ALWAYS"):
        t = "AND"
    clauses = []
    for c in raw.get("clauses") or []:
        if not isinstance(c, dict):
            continue
        if "field" in c:
            if c.get("field") not in FACT_FIELDS or c.get("operator") not in OPERATORS:
                # unknown field: keep as an unknowable clause so the engine reports unknown, not a guess
                clauses.append({"field": "owner_type", "operator": "==", "value": "__unknowable__", "note": c.get("note") or str(c.get("field"))})
            else:
                clauses.append({"field": c["field"], "operator": c["operator"], "value": c.get("value"), "note": c.get("note")})
        else:
            clauses.append(_coerce_condition(c))
    if t == "ALWAYS" or not clauses:
        return Condition(type="ALWAYS", clauses=[])
    return Condition.model_validate({"type": t, "clauses": clauses})


def _to_rule(doc: Document, raw: dict[str, Any], n: int, model: str) -> Optional[Rule]:
    cat = raw.get("category")
    if cat not in CATEGORIES:
        return None
    q = raw.get("quote") or {}
    quote, offs = slice_quote(doc, str(q.get("chunk", "")), str(q.get("start_words", "")), str(q.get("end_words", "")))
    if not quote.strip():
        return None
    prec_raw = raw.get("precedence") or {}
    rel = prec_raw.get("relationship") if prec_raw.get("relationship") in ("supersedes", "yields_to", "stacks_with", "none") else "stacks_with"
    scope = prec_raw.get("target_scope") if prec_raw.get("target_scope") in ("state", "county", "city", "local", "none") else "none"
    if rel in ("stacks_with", "none"):
        scope = "none"
    kv = raw.get("key_value")
    try:
        rule = Rule(
            rule_id=_rule_id(doc, cat, n), category=cat,
            jurisdiction=Jurisdiction(level=doc.level, state=doc.state, county=doc.county or None, city=doc.city or None),
            title=str(raw.get("title") or doc.title)[:160],
            requirement=str(raw.get("requirement") or "").strip(), requirement_es=(raw.get("requirement_es") or None),
            key_value=KeyValue(label=str(kv.get("label", "")), value=str(kv.get("value", ""))) if isinstance(kv, dict) and kv.get("value") else None,
            coverage_conditions=_coerce_condition(raw.get("coverage_conditions")),
            exemptions=[Exemption(description=str(e.get("description", "")), conditions=_coerce_condition(e.get("conditions")))
                        for e in (raw.get("exemptions") or []) if isinstance(e, dict)],
            effective_date=_iso(raw.get("effective_date")), superseded_date=_iso(raw.get("superseded_date")),
            status=raw.get("status") if raw.get("status") in ("enacted", "pending", "struck", "repealed") else ("pending" if doc.kind == "bill" else "enacted"),
            precedence=Precedence(relationship=rel, target_scope=scope, source_language=prec_raw.get("source_language") or None),
            penalty=(raw.get("penalty") or None), source_citation=str(raw.get("source_citation") or doc.citation),
            quoted_span=quote, source_doc_id=doc.doc_id, source_url=doc.url or None, source_char_offset=offs,
            retrieval_date=doc.retrieval_date or None, confidence=float(raw.get("confidence") or 0.5),
            extracted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), model=model,
        )
    except (ValidationError, ValueError, TypeError) as e:
        log.warning("dropping malformed rule from %s: %s", doc.doc_id, e)
        return None
    # exemptions that are literally the whole coverage make no sense; keep only if they have a tree
    rule.exemptions = [e for e in rule.exemptions if e.conditions.type != "ALWAYS"]
    # a doc that is a bill and the model says enacted without a chapter: trust the manifest hint if present
    hint = (doc.extra.get("status_hint") or "").strip()
    if hint in ("enacted", "pending", "struck", "repealed"):
        rule.status = hint  # the manifest row is data from the starter pack, not a per-rule hand edit
    return rule


def _iso(v: Any) -> Optional[str]:
    if not v or not isinstance(v, str):
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _apply_corrections(rule: Rule, corr: dict[str, Any]) -> list[str]:
    changed = []
    for k, v in (corr or {}).items():
        if k == "quote" or k not in Rule.model_fields:
            continue
        try:
            if k in ("coverage_conditions",):
                rule.coverage_conditions = _coerce_condition(v)
            elif k == "exemptions":
                rule.exemptions = [Exemption(description=str(e.get("description", "")), conditions=_coerce_condition(e.get("conditions"))) for e in v if isinstance(e, dict)]
            elif k == "precedence" and isinstance(v, dict):
                rel = v.get("relationship") if v.get("relationship") in ("supersedes", "yields_to", "stacks_with", "none") else rule.precedence.relationship
                scope = v.get("target_scope") if v.get("target_scope") in ("state", "county", "city", "local", "none") else rule.precedence.target_scope
                rule.precedence = Precedence(relationship=rel, target_scope=scope, source_language=v.get("source_language") or rule.precedence.source_language)
            elif k == "key_value":
                rule.key_value = KeyValue(label=str(v.get("label", "")), value=str(v.get("value", ""))) if isinstance(v, dict) and v.get("value") else None
            elif k in ("effective_date", "superseded_date"):
                setattr(rule, k, _iso(v))
            elif k == "status":
                if v in ("enacted", "pending", "struck", "repealed"):
                    rule.status = v
            elif k == "category":
                if v in CATEGORIES:
                    rule.category = v
            else:
                setattr(rule, k, v)
            changed.append(k)
        except (ValidationError, ValueError, TypeError, AttributeError):
            continue
    return changed


def extract_document(doc: Document, llm: Optional[LLM] = None, verify: bool = True) -> tuple[list[Rule], dict[str, Any]]:
    llm = llm or get_llm()
    rules: list[Rule] = []
    audit: dict[str, Any] = {"doc_id": doc.doc_id, "title": doc.title, "url": doc.url, "retrieval_date": doc.retrieval_date,
                             "model": f"{llm.provider}:{llm.model}", "windows": [], "verification": [], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    windows = _window_chunks(doc)
    n = 0
    for wi, chunks in enumerate(windows):
        part = f"Part {wi + 1} of {len(windows)}." if len(windows) > 1 else ""
        try:
            data, resp = llm.complete_json(_prompt(doc, chunks, part), system=SYSTEM, temperature=0.0)
        except Exception as e:  # keep going on one bad document
            audit["windows"].append({"window": wi, "error": str(e)[:300]})
            log.error("extraction failed for %s window %d: %s", doc.doc_id, wi, e)
            continue
        raw_rules = data.get("rules") if isinstance(data, dict) else data
        raw_rules = raw_rules if isinstance(raw_rules, list) else []
        got = []
        for raw in raw_rules:
            if not isinstance(raw, dict):
                continue
            n += 1
            r = _to_rule(doc, raw, n, f"{llm.provider}:{llm.model}")
            if r is not None:
                got.append(r)
        audit["windows"].append({"window": wi, "chunks": len(chunks), "cache_key": resp.cache_key, "cached": resp.cached,
                                 "candidates": len(raw_rules), "kept": len(got), "elapsed_ms": resp.elapsed_ms})
        rules.extend(got)
    if verify and rules:
        try:
            payload = [{"index": i, "record": r.model_dump(exclude={"quoted_span", "source_char_offset", "extracted_at", "model", "verification"}), "quote": r.quoted_span}
                       for i, r in enumerate(rules)]
            data, resp = llm.complete_json(f"{_doc_header(doc)}\n\nExtracted rules with their sliced quotes:\n{json.dumps(payload, ensure_ascii=False, indent=1)}",
                                           system=VERIFY_SYSTEM, temperature=0.0)
            checks = data.get("checks") if isinstance(data, dict) else []
            for ch in checks or []:
                i = ch.get("index")
                if not isinstance(i, int) or i < 0 or i >= len(rules):
                    continue
                r = rules[i]
                changed = _apply_corrections(r, ch.get("corrections") or {})
                supported = bool(ch.get("supported", True))
                conf = ch.get("confidence")
                if isinstance(conf, (int, float)):
                    r.confidence = round(min(1.0, max(0.0, (r.confidence + float(conf)) / 2)), 2)
                if not supported:
                    r.confidence = round(min(r.confidence, 0.35), 2)
                r.verification = {"supported": supported, "issues": ch.get("issues") or [], "corrected_fields": changed, "cache_key": resp.cache_key}
            audit["verification"].append({"cache_key": resp.cache_key, "cached": resp.cached, "checked": len(checks or [])})
        except Exception as e:
            audit["verification"].append({"error": str(e)[:300]})
            log.warning("verification failed for %s: %s", doc.doc_id, e)
    # drop rules the verifier rejected outright with no support and low confidence
    rules = [r for r in rules if r.confidence >= 0.3 or r.verification.get("supported", True)]
    audit["rules"] = [r.rule_id for r in rules]
    return rules, audit


def extract_corpus(docs: list[Document], llm: Optional[LLM] = None, workers: int = 4, verify: bool = True) -> tuple[list[Rule], list[dict[str, Any]]]:
    llm = llm or get_llm()
    results: dict[str, tuple[list[Rule], dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(extract_document, d, llm, verify): d.doc_id for d in docs}
        for fut, doc_id in futs.items():
            try:
                results[doc_id] = fut.result()
            except Exception as e:  # pragma: no cover
                log.error("document %s failed: %s", doc_id, e)
                results[doc_id] = ([], {"doc_id": doc_id, "error": str(e)})
    rules: list[Rule] = []
    audits: list[dict[str, Any]] = []
    for d in docs:
        rs, a = results.get(d.doc_id, ([], {}))
        rules.extend(rs)
        audits.append(a)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    with (AUDIT_DIR / "extraction_log.jsonl").open("a", encoding="utf-8") as f:
        for a in audits:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    return rules, audits
