"""Decision engine: hand-built edge cases. No model, no network."""
from datetime import date

from app import engine
from app.schema import APPLIES, NOT_YET_EFFECTIVE, OMIT, PENDING, SUPERSEDED, UNKNOWN, Clause, Condition, Exemption, Jurisdiction, Precedence, Rule


def mk(rule_id, level="state", state="CA", city=None, county=None, category="rent_increase_limit", cov=None, ex=None,
       eff="2020-01-01", status="enacted", prec=None, sup=None):
    return Rule(rule_id=rule_id, category=category, jurisdiction=Jurisdiction(level=level, state=state, city=city, county=county),
                title=rule_id, requirement="r", coverage_conditions=cov or Condition(), exemptions=ex or [],
                effective_date=eff, superseded_date=sup, status=status, precedence=prec or Precedence(),
                source_citation="cite", quoted_span="q", source_doc_id="doc_" + rule_id, confidence=0.9)


SF = {"state": "CA", "county": "San Francisco", "city": "San Francisco"}
LA = {"state": "CA", "county": "Los Angeles", "city": "Los Angeles"}
AS_OF = date(2026, 10, 1)


def cov_before_1979():
    return Condition(type="AND", clauses=[Clause(field="certificate_of_occupancy_date", operator="<", value="1979-06-13")])


def test_three_valued_and_or_not():
    f = {"units": 20}
    c_true = Clause(field="units", operator=">=", value=5)
    c_unknown = Clause(field="owner_type", operator="==", value="natural_person")
    c_false = Clause(field="units", operator="<", value=5)
    assert engine.evaluate(Condition(type="AND", clauses=[c_true, c_unknown]), f) == engine.UNK
    assert engine.evaluate(Condition(type="AND", clauses=[c_false, c_unknown]), f) == engine.FALSE
    assert engine.evaluate(Condition(type="OR", clauses=[c_true, c_unknown]), f) == engine.TRUE
    assert engine.evaluate(Condition(type="OR", clauses=[c_false, c_unknown]), f) == engine.UNK
    assert engine.evaluate(Condition(type="NOT", clauses=[c_unknown]), f) == engine.UNK
    assert engine.evaluate(Condition(type="NOT", clauses=[c_false]), f) == engine.TRUE


def test_certificate_of_occupancy_derived_from_year_built():
    r = mk("SF", level="city", city="San Francisco", county="San Francisco", cov=cov_before_1979())
    assert engine.decide(r, engine.derive_facts({"year_built": 1962, "units": 20}, AS_OF), AS_OF, SF, [r])[0] == APPLIES
    assert engine.decide(r, engine.derive_facts({"year_built": 1995, "units": 20}, AS_OF), AS_OF, SF, [r])[0] == OMIT
    res, reason, missing = engine.decide(r, engine.derive_facts({"year_built": 1979, "units": 20}, AS_OF), AS_OF, SF, [r])
    assert res == UNKNOWN and "certificate_of_occupancy_date" in missing
    res, _, missing = engine.decide(r, engine.derive_facts({"units": 20}, AS_OF), AS_OF, SF, [r])
    assert res == UNKNOWN and missing == ["certificate_of_occupancy_date"]


def test_exemption_small_landlord_needs_owner_type():
    ex = Exemption(description="small landlord", conditions=Condition(type="AND", clauses=[
        Clause(field="units", operator="<=", value=2), Clause(field="owner_type", operator="==", value="natural_person")]))
    r = mk("DEP", category="security_deposit", ex=[ex])
    # 20 units: exemption definitively fails even with owner_type unknown -> applies
    assert engine.decide(r, engine.derive_facts({"units": 20}, AS_OF), AS_OF, SF, [r])[0] == APPLIES
    # 2 units, owner unknown -> unknown
    assert engine.decide(r, engine.derive_facts({"units": 2}, AS_OF), AS_OF, SF, [r])[0] == UNKNOWN


def test_jurisdiction_and_dates():
    r = mk("SF", level="city", city="San Francisco", county="San Francisco")
    assert engine.decide(r, {}, AS_OF, LA, [r])[0] == OMIT
    fut = mk("FUT", eff="2027-07-01")
    assert engine.decide(fut, {}, AS_OF, SF, [fut])[0] == NOT_YET_EFFECTIVE
    assert engine.decide(fut, {}, date(2027, 7, 2), SF, [fut])[0] == APPLIES
    old = mk("OLD", eff="2000-01-01", sup="2024-07-01")
    assert engine.decide(old, {}, AS_OF, SF, [old])[0] == OMIT
    assert engine.decide(old, {}, date(2024, 6, 30), SF, [old])[0] == APPLIES


def test_status_pending_struck():
    p = mk("P", status="pending", eff=None)
    assert engine.decide(p, {}, AS_OF, SF, [p])[0] == PENDING
    s = mk("S", status="struck")
    assert engine.decide(s, {}, AS_OF, SF, [s])[0] == OMIT


def test_state_cap_yields_to_local_ordinance():
    state = mk("CA-RENT", prec=Precedence(relationship="yields_to", target_scope="local", source_language="shall not apply to ... local ordinance"))
    sf = mk("SF-RENT", level="city", city="San Francisco", county="San Francisco", cov=cov_before_1979())
    rules = [state, sf]
    engine.resolve_precedence_targets(rules)
    assert state.precedence.target_rule_ids == ["SF-RENT"]
    f = engine.derive_facts({"year_built": 1962, "units": 20}, AS_OF)
    assert engine.decide(state, f, AS_OF, SF, rules)[0] == SUPERSEDED
    assert engine.decide(sf, f, AS_OF, SF, rules)[0] == APPLIES
    # newer building: SF ordinance omitted, state cap applies
    f2 = engine.derive_facts({"year_built": 2000, "units": 20}, AS_OF)
    assert engine.decide(state, f2, AS_OF, SF, rules)[0] == APPLIES
    # in LA the SF ordinance is out of jurisdiction; state applies
    assert engine.decide(state, f, AS_OF, LA, rules)[0] == APPLIES


def test_state_preemption_not_yet_effective_flags_conflict_with_local():
    fair = mk("NJ-FAIR", state="NJ", category="algorithmic_rent_setting", eff="2027-07-01",
              prec=Precedence(relationship="supersedes", target_scope="local", source_language="shall supersede any ordinance"))
    hob = mk("HOB", state="NJ", level="city", city="Hoboken", county="Hudson", category="algorithmic_rent_setting", eff="2025-07-01")
    jc = mk("JC", state="NJ", level="city", city="Jersey City", county="Hudson", category="algorithmic_rent_setting", eff="2025-06-01")
    rules = [fair, hob, jc]
    engine.resolve_precedence_targets(rules)
    HOB = {"state": "NJ", "county": "Hudson", "city": "Hoboken"}
    NEW = {"state": "NJ", "county": "Essex", "city": "Newark"}
    assert engine.decide(fair, {}, AS_OF, HOB, rules)[0] == NOT_YET_EFFECTIVE
    assert engine.decide(hob, {}, AS_OF, HOB, rules)[0] == APPLIES
    assert engine.decide(jc, {}, AS_OF, HOB, rules)[0] == OMIT
    assert engine.decide(hob, {}, AS_OF, NEW, rules)[0] == OMIT
    c = engine.conflicts_for(hob, {}, AS_OF, HOB, rules)
    assert c and c[0]["with_rule_id"] == "NJ-FAIR"
    later = date(2027, 7, 2)
    assert engine.decide(fair, {}, later, HOB, rules)[0] == APPLIES
    assert engine.decide(hob, {}, later, HOB, rules)[0] == SUPERSEDED


def test_stacking_by_default_no_conflict():
    state = mk("CA-ALGO", category="algorithmic_rent_setting", eff="2026-01-01")
    sf = mk("SF-ALGO", level="city", city="San Francisco", county="San Francisco", category="algorithmic_rent_setting", eff="2024-10-01")
    rules = [state, sf]
    engine.resolve_precedence_targets(rules)
    assert engine.decide(state, {}, AS_OF, SF, rules)[0] == APPLIES
    assert engine.decide(sf, {}, AS_OF, SF, rules)[0] == APPLIES
    assert engine.conflicts_for(sf, {}, AS_OF, SF, rules) == []
    assert engine.decide(state, {}, date(2025, 12, 31), SF, rules)[0] == NOT_YET_EFFECTIVE
