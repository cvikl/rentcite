"""Data model for Homerule.

Everything the scorer reads (rules.json, lookups.json, changes.json) is defined here, in one place,
so that a change in the official schema is a change in one file. The controlled vocabularies
(categories, statuses, result labels, fact fields, operators) are the only strings the pipeline emits.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "out"

# ----------------------------------------------------------------------------- vocabularies
# Machine-readable category strings. If the official schema uses different literals, change them
# in data/schema/vocab.json; this module reads that file first.
_VOCAB_FILE = DATA / "schema" / "vocab.json"

DEFAULT_VOCAB: dict[str, Any] = {
    "categories": {
        "rent_increase_limit": "Rent increase limits",
        "just_cause_eviction": "Just-cause eviction",
        "security_deposit": "Security deposits",
        "application_screening_fee": "Application and screening fees",
        "screening_restriction": "Screening restrictions",
        "algorithmic_rent_setting": "Algorithmic rent-setting",
    },
    "statuses": ["enacted", "pending", "struck", "repealed"],
    # Result labels in lookups.json. The brief lists them in prose as
    # "applies, unknown, superseded, not yet effective, pending". Snake case is the default;
    # set "result_label_style": "spaces" to emit "not yet effective" instead.
    "result_label_style": "snake",
    "levels": ["state", "county", "city"],
}


def load_vocab() -> dict[str, Any]:
    v = dict(DEFAULT_VOCAB)
    if _VOCAB_FILE.exists():
        v.update(json.loads(_VOCAB_FILE.read_text()))
    return v


VOCAB = load_vocab()
CATEGORIES: dict[str, str] = VOCAB["categories"]
STATUSES: list[str] = VOCAB["statuses"]
LEVELS: list[str] = VOCAB["levels"]

# Internal result constants (never emitted directly; see result_label()).
APPLIES = "applies"
UNKNOWN = "unknown"
SUPERSEDED = "superseded"
NOT_YET_EFFECTIVE = "not_yet_effective"
PENDING = "pending"
OMIT = "omit"  # confirmed non-match or dead law: never written to lookups.json
RESULTS = [APPLIES, UNKNOWN, SUPERSEDED, NOT_YET_EFFECTIVE, PENDING]


def result_label(r: str) -> str:
    """The literal string written to lookups.json for an internal result."""
    if VOCAB.get("result_label_style") == "spaces":
        return r.replace("_", " ")
    return r


# Building facts the decision engine understands. The extractor may only use these field names.
FACT_FIELDS: dict[str, str] = {
    "units": "number of dwelling units in the building (integer)",
    "year_built": "year the building was built (integer, four digits)",
    "building_age_years": "years since the building was built, measured at the as-of date (integer)",
    "certificate_of_occupancy_date": "date the first certificate of occupancy was issued (ISO date). Derived from year_built when the exact date is unknown",
    "property_type": "one of: multifamily, single_family, condominium, duplex, mixed_use, mobile_home, other",
    "owner_type": "one of: natural_person, corporation, llc, reit, trust, government, nonprofit",
    "owner_occupied": "true if the owner lives in the building",
    "rent_subsidized": "true if the unit's rent is government-subsidized or the building is deed-restricted affordable",
    "tenancy_length_months": "months the current tenant has been in the unit (integer)",
    "lease_type": "one of: month_to_month, fixed_term",
    "new_construction": "true if the building was constructed within the lookback the law states (use building_age_years instead where possible)",
}
OPERATORS = ["==", "!=", "<", "<=", ">", ">=", "in", "not_in"]


# ----------------------------------------------------------------------------- condition trees
class Clause(BaseModel):
    field: str
    operator: Literal["==", "!=", "<", "<=", ">", ">=", "in", "not_in"]
    value: Any
    note: Optional[str] = None  # the words in the source the clause came from


class Condition(BaseModel):
    """Boolean tree: AND/OR/NOT of clauses. `type: ALWAYS` means no coverage test (covers everyone)."""

    type: Literal["AND", "OR", "NOT", "ALWAYS"] = "ALWAYS"
    clauses: list[Union["Condition", Clause]] = Field(default_factory=list)


Condition.model_rebuild()


class Exemption(BaseModel):
    description: str
    conditions: Condition


class Jurisdiction(BaseModel):
    level: Literal["state", "county", "city"]
    state: str  # two-letter code
    county: Optional[str] = None
    city: Optional[str] = None

    @field_validator("state")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    def key(self) -> str:
        if self.level == "state":
            return self.state
        if self.level == "county":
            return f"{self.state}/{norm_place(self.county or '')}"
        return f"{self.state}/{norm_place(self.county or '')}/{norm_place(self.city or '')}"


class Precedence(BaseModel):
    """Precedence declared by the source text itself.

    relationship:
      supersedes   this rule displaces rules of the same category at `target_scope` (e.g. a state preemption)
      yields_to    this rule steps aside where a rule of the same category at `target_scope` applies
                   (e.g. the CA state rent cap yields to a stricter local ordinance)
      stacks_with  both apply (default when the text is silent)
      none         the text says nothing and the rule is the only one at its level
    target_scope: state | county | city | local (county or city) | none
    target_rule_ids: resolved by code after extraction, never by the model.
    """

    relationship: Literal["supersedes", "yields_to", "stacks_with", "none"] = "stacks_with"
    target_scope: Literal["state", "county", "city", "local", "none"] = "none"
    source_language: Optional[str] = None
    target_rule_ids: list[str] = Field(default_factory=list)


class KeyValue(BaseModel):
    """The one number or formula the rule is about, for field accuracy scoring (e.g. '5% + CPI, max 10%')."""

    label: str
    value: str


class Rule(BaseModel):
    rule_id: str
    category: str
    jurisdiction: Jurisdiction
    title: str
    requirement: str
    requirement_es: Optional[str] = None
    key_value: Optional[KeyValue] = None
    coverage_conditions: Condition = Field(default_factory=Condition)
    exemptions: list[Exemption] = Field(default_factory=list)
    effective_date: Optional[str] = None  # ISO date or null when the text does not state one
    superseded_date: Optional[str] = None
    status: Literal["enacted", "pending", "struck", "repealed"] = "enacted"
    precedence: Precedence = Field(default_factory=Precedence)
    penalty: Optional[str] = None
    source_citation: str
    quoted_span: str
    source_doc_id: str
    source_url: Optional[str] = None
    source_char_offset: list[int] = Field(default_factory=lambda: [0, 0])
    retrieval_date: Optional[str] = None
    confidence: float = 0.5
    verification: dict[str, Any] = Field(default_factory=dict)
    extracted_at: Optional[str] = None
    model: Optional[str] = None

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"unknown category {v!r}")
        return v


# ----------------------------------------------------------------------------- addresses
class Address(BaseModel):
    address_id: str
    street: str
    postal_city: str
    state: str
    zip: str
    year_built: Optional[int] = None
    units: Optional[int] = None
    use_code: Optional[str] = None
    source: Optional[str] = None


class JurisdictionStack(BaseModel):
    state: str
    county: Optional[str] = None
    city: Optional[str] = None
    method: str = "unresolved"  # census_geocoder | zip_table | postal_city | manual
    confidence: float = 0.0
    matched_address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class ResultEntry(BaseModel):
    rule_id: str
    category: str
    result: str
    reason: str
    citation: str
    quoted_span: str
    source_doc_id: str
    conflict_flag: bool = False
    conflict_reason: Optional[str] = None
    confidence: float
    missing_facts: list[str] = Field(default_factory=list)
    plain_language: Optional[str] = None
    plain_language_es: Optional[str] = None
    status: str = "enacted"
    effective_date: Optional[str] = None
    level: str = "state"


class Lookup(BaseModel):
    address_id: str
    as_of_date: str
    jurisdiction_stack: dict[str, Any]
    building_facts: dict[str, Any]
    results: list[ResultEntry]
    no_rule_findings: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = "Not legal advice."


class ChangeQuery(BaseModel):
    as_of_date: str
    status: str
    affected_addresses: list[str]


class ChangeRecord(BaseModel):
    test_id: str
    description: str
    rule_ids: list[str]
    query_before: ChangeQuery
    query_after: ChangeQuery
    affected_addresses: list[str]
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    notes: Optional[str] = None


# ----------------------------------------------------------------------------- helpers
def norm_place(name: str) -> str:
    """Normalise a place name so 'City of Boston', 'BOSTON' and 'Boston city' compare equal."""
    s = (name or "").strip().lower()
    for pre in ("city and county of ", "city of ", "town of ", "county of ", "township of "):
        if s.startswith(pre):
            s = s[len(pre):]
    for suf in (" city", " town", " county", " township", " (city)", " (town)"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return " ".join(s.replace(".", "").split())


def parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def today_iso() -> str:
    return date.today().isoformat()
