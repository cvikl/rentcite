"""The decision engine. Plain code, three-valued logic, no model anywhere.

decide(rule, facts, as_of, all_rules, stack) -> (result, reason, missing_facts)

Results: applies | unknown | superseded | not_yet_effective | pending | omit
`omit` means a confirmed non-match (coverage false, exempt, dead law, outside the jurisdiction,
or already superseded by date) and is never written to lookups.json.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from .schema import (APPLIES, NOT_YET_EFFECTIVE, OMIT, PENDING, SUPERSEDED, UNKNOWN, VOCAB, Clause, Condition, Jurisdiction,
                     Rule, norm_place, parse_date)

NEVER_IN_DATA = set(VOCAB.get("facts_never_in_data", []))
FLAG_UNKNOWN_EXEMPTIONS = VOCAB.get("unknown_exemption_policy", "flag") == "flag"

TRUE, FALSE, UNK = "true", "false", "unknown"
NOT_TABLE = {TRUE: FALSE, FALSE: TRUE, UNK: UNK}


# ----------------------------------------------------------------------------- facts
def derive_facts(raw: dict[str, Any], as_of: date) -> dict[str, Any]:
    """Building facts plus the values code can derive from them. Unknown stays None."""
    f: dict[str, Any] = {k: v for k, v in raw.items() if v not in ("", None)}
    yb = f.get("year_built")
    if isinstance(yb, (int, float)) and yb > 0:
        f["year_built"] = int(yb)
        f["building_age_years"] = as_of.year - int(yb)
    else:
        f.pop("year_built", None)
    if "units" in f:
        try:
            f["units"] = int(f["units"])
        except (TypeError, ValueError):
            f.pop("units")
    return f


def _cmp_value(a: Any, op: str, b: Any) -> Optional[bool]:
    """Compare with light coercion. Returns None when the values cannot be compared."""
    if op in ("in", "not_in"):
        opts = b if isinstance(b, list) else [b]
        opts_n = [str(x).strip().lower() for x in opts]
        hit = str(a).strip().lower() in opts_n
        return hit if op == "in" else not hit
    da, db = parse_date(a) if isinstance(a, str) else None, parse_date(b) if isinstance(b, str) else None
    if da and db:
        a, b = da, db
    else:
        try:
            if isinstance(a, bool) or isinstance(b, bool):
                a, b = bool(a) if not isinstance(a, str) else a.lower() in ("true", "yes", "1"), bool(b) if not isinstance(b, str) else b.lower() in ("true", "yes", "1")
            elif not isinstance(a, str) or not isinstance(b, str):
                a, b = float(a), float(b)
            else:
                a, b = a.strip().lower(), b.strip().lower()
        except (TypeError, ValueError):
            return None
    try:
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
    except TypeError:
        return None
    return None


def _eval_leaf(c: Clause, facts: dict[str, Any], missing: list[str]) -> str:
    field, val = c.field, facts.get(c.field)
    # Certificate-of-occupancy dates are derived from year_built when only the year is known:
    # a building built in 1962 was certainly occupied before 1979; a 1979 building is unknown.
    if field == "certificate_of_occupancy_date" and val is None and facts.get("year_built") is not None:
        target = parse_date(c.value)
        if target is None:
            missing.append(field)
            return UNK
        yb = facts["year_built"]
        if yb < target.year:
            co_before = True
        elif yb > target.year:
            co_before = False
        else:
            missing.append(field)
            return UNK
        if c.operator in ("<", "<="):
            return TRUE if co_before else FALSE
        if c.operator in (">", ">="):
            return FALSE if co_before else TRUE
        missing.append(field)
        return UNK
    if val is None:
        missing.append(field)
        return UNK
    r = _cmp_value(val, c.operator, c.value)
    if r is None:
        missing.append(field)
        return UNK
    return TRUE if r else FALSE


def evaluate(cond: Condition | Clause | None, facts: dict[str, Any], missing: Optional[list[str]] = None) -> str:
    if missing is None:
        missing = []
    if cond is None:
        return TRUE
    if isinstance(cond, Clause):
        return _eval_leaf(cond, facts, missing)
    if cond.type == "ALWAYS" or (cond.type in ("AND", "OR") and not cond.clauses):
        return TRUE
    if cond.type == "AND":
        rs = [evaluate(c, facts, missing) for c in cond.clauses]
        if FALSE in rs:
            return FALSE
        if UNK in rs:
            return UNK
        return TRUE
    if cond.type == "OR":
        rs = [evaluate(c, facts, missing) for c in cond.clauses]
        if TRUE in rs:
            return TRUE
        if UNK in rs:
            return UNK
        return FALSE
    if cond.type == "NOT":
        inner = evaluate(cond.clauses[0], facts, missing) if cond.clauses else TRUE
        return NOT_TABLE[inner]
    return UNK


# ----------------------------------------------------------------------------- jurisdiction
def in_jurisdiction(j: Jurisdiction, stack: dict[str, Any]) -> bool:
    if (stack.get("state") or "").upper() != j.state:
        return False
    if j.level == "state":
        return True
    if j.level == "county":
        return norm_place(stack.get("county") or "") == norm_place(j.county or "")
    return bool(stack.get("city")) and norm_place(stack.get("city") or "") == norm_place(j.city or "")


def scope_matches(scope: str, other: Jurisdiction) -> bool:
    if scope == "local":
        return other.level in ("county", "city")
    return scope == other.level


# ----------------------------------------------------------------------------- decide
def coverage_outcome(rule: Rule, facts: dict[str, Any]) -> tuple[str, list[str]]:
    """TRUE / FALSE / UNK for 'this building is covered and not exempt', plus the missing facts.

    Under the "flag" policy an exemption that rests entirely on facts the address data never holds
    is reported as a possible exemption (TRUE with the facts listed) rather than blocking. An exemption
    that also tests a data fact (e.g. units <= 2 AND owner is a natural person) still yields unknown."""
    missing: list[str] = []
    cov = evaluate(rule.coverage_conditions, facts, missing)
    if cov == FALSE:
        return FALSE, []
    ex = FALSE
    flagged: list[str] = []
    if rule.exemptions:
        exs = []
        for e in rule.exemptions:
            m: list[str] = []
            r = evaluate(e.conditions, facts, m)
            fields = {c.field for c in _leaves(e.conditions)}
            if r == UNK and FLAG_UNKNOWN_EXEMPTIONS and fields and fields <= NEVER_IN_DATA:
                flagged.extend(m)
                r = FALSE
            else:
                missing.extend(m)
            exs.append(r)
        ex = TRUE if TRUE in exs else (UNK if UNK in exs else FALSE)
    if cov == TRUE and ex == TRUE:
        return FALSE, []
    if cov == UNK or ex == UNK:
        return UNK, sorted(set(missing))
    return TRUE, sorted(set(flagged))


def _window_ok(rule: Rule, as_of: date) -> str:
    """NOT_YET_EFFECTIVE / OMIT / 'live' for the date window."""
    eff = parse_date(rule.effective_date)
    if eff and as_of < eff:
        return NOT_YET_EFFECTIVE
    sup = parse_date(rule.superseded_date)
    if sup and as_of >= sup:
        return OMIT
    return "live"


def decide(rule: Rule, facts: dict[str, Any], as_of: date, stack: dict[str, Any], rules: list[Rule],
           _depth: int = 0) -> tuple[str, str, list[str]]:
    if not in_jurisdiction(rule.jurisdiction, stack):
        return OMIT, "outside this rule's jurisdiction", []
    cov, missing = coverage_outcome(rule, facts)
    if cov == FALSE:
        return OMIT, "coverage conditions not met or building exempt", []
    if rule.status in ("struck", "repealed"):
        return OMIT, f"law is {rule.status}; never in force", []
    if rule.status == "pending":
        return PENDING, "proposed law, not enacted" + (f"; would depend on {', '.join(missing)}" if missing else ""), missing
    win = _window_ok(rule, as_of)
    if win == NOT_YET_EFFECTIVE:
        return NOT_YET_EFFECTIVE, f"effective {rule.effective_date}, after the as-of date {as_of.isoformat()}", missing
    if win == OMIT:
        return OMIT, f"superseded on {rule.superseded_date}", []
    if cov == UNK:
        return UNKNOWN, "coverage depends on facts not in the data: " + ", ".join(missing), missing
    # Precedence, resolved from explicit statutory language only.
    if _depth < 2:
        sup_by = superseding_rules(rule, facts, as_of, stack, rules, _depth)
        if sup_by:
            ids = ", ".join(r.rule_id for r in sup_by)
            return SUPERSEDED, f"displaced by {ids}", []
    reason = _applies_reason(rule, facts)
    if missing:
        reason += "; a stated exemption could apply if " + ", ".join(missing) + " were known"
    return APPLIES, reason, missing


def superseding_rules(rule: Rule, facts: dict[str, Any], as_of: date, stack: dict[str, Any], rules: list[Rule],
                      depth: int = 0) -> list[Rule]:
    """Rules of the same category that displace `rule` for this address today."""
    out = []
    for other in rules:
        if other.rule_id == rule.rule_id or other.category != rule.category:
            continue
        if not in_jurisdiction(other.jurisdiction, stack):
            continue
        relation = None
        p_other, p_self = other.precedence, rule.precedence
        if p_other.relationship == "supersedes" and rule.rule_id in p_other.target_rule_ids:
            relation = "supersedes"
        elif p_self.relationship == "yields_to" and other.rule_id in p_self.target_rule_ids:
            relation = "yields_to"
        if relation is None:
            continue
        if other.status != "enacted":
            continue
        if _window_ok(other, as_of) != "live":
            continue
        cov, _ = coverage_outcome(other, facts)
        if cov != TRUE:
            continue
        r, _, _ = decide(other, facts, as_of, stack, rules, depth + 1)
        if r == APPLIES:
            out.append(other)
    return out


def _applies_reason(rule: Rule, facts: dict[str, Any]) -> str:
    bits = []
    for c in _leaves(rule.coverage_conditions):
        v = facts.get(c.field)
        if c.field == "certificate_of_occupancy_date" and v is None and facts.get("year_built"):
            v = f"built {facts['year_built']}"
        if v is not None:
            bits.append(f"{c.field}={v} satisfies {c.operator} {c.value}")
    if rule.exemptions:
        bits.append("no exemption applies")
    return "; ".join(bits) if bits else "rule covers every rental in its jurisdiction"


def _leaves(cond: Condition | Clause) -> list[Clause]:
    if isinstance(cond, Clause):
        return [cond]
    out: list[Clause] = []
    for c in cond.clauses:
        out.extend(_leaves(c))
    return out


# ----------------------------------------------------------------------------- conflicts
def conflicts_for(rule: Rule, facts: dict[str, Any], as_of: date, stack: dict[str, Any], rules: list[Rule]) -> list[dict[str, Any]]:
    """Generic conflict detection: same category, overlapping jurisdiction for this address, and an
    explicit precedence relationship whose effect differs across time, or two live rules at different
    levels with no stacking language."""
    out = []
    for other in rules:
        if other.rule_id == rule.rule_id or other.category != rule.category:
            continue
        if not in_jurisdiction(other.jurisdiction, stack) or other.status in ("struck", "repealed"):
            continue
        cov_o, _ = coverage_outcome(other, facts)
        if cov_o == FALSE:
            continue
        rel = _relation(rule, other)
        if rel is None:
            continue
        win_self, win_other = _window_ok(rule, as_of), _window_ok(other, as_of)
        if win_self == OMIT or win_other == OMIT:
            continue
        if other.status == "pending":
            out.append({"with_rule_id": other.rule_id, "reason": f"pending {other.jurisdiction.level} law would {rel} this rule"})
        elif win_other == NOT_YET_EFFECTIVE or win_self == NOT_YET_EFFECTIVE:
            out.append({"with_rule_id": other.rule_id, "reason": f"{rel}: overlapping scope, effective windows differ ({rule.effective_date} vs {other.effective_date})"})
        else:
            out.append({"with_rule_id": other.rule_id, "reason": f"{rel}: both in force, {other.jurisdiction.level} rule displaces {rule.jurisdiction.level} rule"})
    return out


def _relation(a: Rule, b: Rule) -> Optional[str]:
    pa, pb = a.precedence, b.precedence
    if pb.relationship == "supersedes" and a.rule_id in pb.target_rule_ids:
        return "superseded by"
    if pa.relationship == "supersedes" and b.rule_id in pa.target_rule_ids:
        return "supersedes"
    if pa.relationship == "yields_to" and b.rule_id in pa.target_rule_ids:
        return "yields to"
    if pb.relationship == "yields_to" and a.rule_id in pb.target_rule_ids:
        return "is yielded to by"
    return None


_LOCAL_WORDS = re.compile(r"\b(ordinance|ordinances|local|city|cities|county|counties|municipal|municipality|municipalities|political subdivision|charter|town|towns)\b", re.I)
_STATE_WORDS = re.compile(r"\b(state law|state statute|statute|general laws?|civil code|government code|state)\b", re.I)


def explicit_precedence(source_language: Optional[str], target_scope: str) -> bool:
    """A supersession or deference counts only when the quoted words name the rules it reaches:
    local ordinances for a local target, state law for a state target. 'Notwithstanding any other
    provision of law' names nothing and does not displace a local rent cap."""
    text = (source_language or "").strip()
    if not text:
        return False
    if target_scope in ("local", "city", "county"):
        return bool(_LOCAL_WORDS.search(text))
    if target_scope == "state":
        return bool(_STATE_WORDS.search(text))
    return False


def resolve_precedence_targets(rules: list[Rule]) -> None:
    """Fill precedence.target_rule_ids in code from target_scope + category + jurisdiction overlap."""
    for r in rules:
        p = r.precedence
        # Precedence must rest on explicit statutory words naming the displaced level; otherwise it stacks.
        if p.relationship in ("supersedes", "yields_to") and not explicit_precedence(p.source_language, p.target_scope):
            p.relationship, p.target_scope = "stacks_with", "none"
        if p.relationship not in ("supersedes", "yields_to") or p.target_scope == "none":
            p.target_rule_ids = []
            continue
        ids = []
        for o in rules:
            if o.rule_id == r.rule_id or o.category != r.category or o.jurisdiction.state != r.jurisdiction.state:
                continue
            if o.source_doc_id == r.source_doc_id or o.jurisdiction.level == r.jurisdiction.level:
                continue  # a document never displaces its own rules; precedence runs across levels of government
            if not scope_matches(p.target_scope, o.jurisdiction):
                continue
            # the two jurisdictions must overlap: a state rule overlaps every local rule in the state;
            # a city rule overlaps the state and its own county
            if r.jurisdiction.level == "state" or o.jurisdiction.level == "state":
                ids.append(o.rule_id)
            elif norm_place(r.jurisdiction.county or "") == norm_place(o.jurisdiction.county or ""):
                ids.append(o.rule_id)
        p.target_rule_ids = sorted(ids)
