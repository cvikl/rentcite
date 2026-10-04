"""Change tracking and lookups on hand-built rules and addresses. No model, no network."""
from datetime import date

from app import changes as ch
from app.lookup import evaluate_address, no_rule_findings
from app.schema import Address, Clause, Condition, Jurisdiction, JurisdictionStack, Precedence, Rule
from app import engine


def rule(rule_id, state, level="state", city=None, county=None, category="algorithmic_rent_setting", eff=None, status="enacted", prec=None, cov=None):
    return Rule(rule_id=rule_id, category=category, jurisdiction=Jurisdiction(level=level, state=state, city=city, county=county), title=rule_id,
                requirement="r", coverage_conditions=cov or Condition(), effective_date=eff, status=status, precedence=prec or Precedence(),
                source_citation=rule_id, quoted_span="q", source_doc_id="doc_" + rule_id, confidence=0.9)


ADDRS = [Address(address_id="a1", street="1 A St", postal_city="Hoboken", state="NJ", zip="07030", year_built=1960, units=10),
         Address(address_id="a2", street="2 B St", postal_city="Jersey City", state="NJ", zip="07302", year_built=2001, units=40),
         Address(address_id="a3", street="3 C St", postal_city="Newark", state="NJ", zip="07102", units=6),
         Address(address_id="a4", street="4 D St", postal_city="Dorchester", state="MA", zip="02125", year_built=1910, units=6)]
STACKS = {"a1": JurisdictionStack(state="NJ", county="Hudson", city="Hoboken", method="t", confidence=1),
          "a2": JurisdictionStack(state="NJ", county="Hudson", city="Jersey City", method="t", confidence=1),
          "a3": JurisdictionStack(state="NJ", county="Essex", city="Newark", method="t", confidence=1),
          "a4": JurisdictionStack(state="MA", county="Suffolk", city="Boston", method="t", confidence=1)}


def nj_rules():
    fair = rule("NJ-FAIR", "NJ", eff="2027-07-01", prec=Precedence(relationship="supersedes", target_scope="local", source_language="shall supersede"))
    hob = rule("HOB", "NJ", "city", "Hoboken", "Hudson", eff="2025-07-01")
    jc = rule("JC", "NJ", "city", "Jersey City", "Hudson", eff="2025-06-01")
    rules = [fair, hob, jc]
    engine.resolve_precedence_targets(rules)
    return rules


def test_t2_local_bans_only_in_their_city():
    rules = nj_rules()
    rec = ch.run_test({"test_id": "T2", "select": {"state": "NJ", "category": "algorithmic_rent_setting", "level": "city"}, "before": "2025-01-01", "after": "2026-10-01"}, rules, ADDRS, STACKS)
    assert set(rec.affected_addresses) == {"a1", "a2"}  # never Newark
    assert rec.query_before.status == "not_yet_effective" and rec.query_after.status == "applies"


def test_t3_state_preemption_future_with_conflicts():
    rules = nj_rules()
    rec = ch.run_test({"test_id": "T3", "select": {"state": "NJ", "category": "algorithmic_rent_setting", "level": "state"}, "before": "2026-10-01", "after": "2027-07-02"}, rules, ADDRS, STACKS)
    assert set(rec.affected_addresses) == {"a1", "a2", "a3"}
    assert rec.query_before.status == "not_yet_effective" and rec.query_after.status == "applies"
    assert {c["with_rule_id"] for c in rec.conflicts} == {"HOB", "JC"}


def test_t4_pending_never_in_force_but_lists_addresses():
    bill = rule("MA-S2983", "MA", status="pending")
    rec = ch.run_test({"test_id": "T4", "select": {"state": "MA", "status": "pending"}, "before": "2026-10-01", "after": "2027-01-01"}, [bill], ADDRS, STACKS)
    assert rec.affected_addresses == ["a4"]
    assert rec.query_before.status == "pending" and rec.query_after.status == "pending"


def test_t5_struck_measure_reaches_nobody():
    struck = rule("MA-BALLOT", "MA", category="rent_increase_limit", status="struck")
    rec = ch.run_test({"test_id": "T5", "select": {"state": "MA", "category": "rent_increase_limit", "status": "struck"}, "before": "2026-06-01", "after": "2026-10-01"}, [struck], ADDRS, STACKS)
    assert rec.affected_addresses == [] and rec.query_after.status == "struck"


def test_t6_new_document_test_uses_effective_date():
    new = rule("CAM", "MA", "city", "Cambridge", "Middlesex", eff="2027-03-01")
    t = ch.test_for_new_document("doc_CAM", [new], today=date(2026, 10, 5))
    assert t["after"] == "2027-03-02" and t["select"] == {"doc_ids": ["doc_CAM"]}


def test_lookup_only_reports_true_or_unknown_and_no_rule_findings():
    rules = nj_rules()
    lk = evaluate_address(ADDRS[2], STACKS["a3"], rules, date(2026, 10, 1))
    assert [e.rule_id for e in lk.results] == ["NJ-FAIR"] and lk.results[0].result == "not_yet_effective"
    cats = {(n["category"], n["level"]) for n in lk.no_rule_findings}
    assert ("algorithmic_rent_setting", "city") in cats and ("algorithmic_rent_setting", "state") not in cats
    lk2 = evaluate_address(ADDRS[0], STACKS["a1"], rules, date(2027, 8, 1))
    res = {e.rule_id: e.result for e in lk2.results}
    assert res == {"NJ-FAIR": "applies", "HOB": "superseded"}
    assert all(e.conflict_flag for e in lk2.results)
