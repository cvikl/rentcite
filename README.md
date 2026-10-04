# Homerule

**Which rental housing rules apply at this address today, and what is about to change.**

Homerule reads a corpus of real statute, ordinance and bill text, turns it into structured rule records with verbatim quotes, resolves any sample address to its legal jurisdiction (state, county, city), and decides per rule: **applies**, **unknown**, **superseded**, **not yet effective** or **pending**, as of any date. The model only reads; plain code decides. Every answer carries the exact words of the law, the source URL and the retrieval date. It is not legal advice.

Built for the 7th Hack-Nation Global AI Hackathon, Challenge 02 (RealPage), October 2026.

- Live demo: https://rentcite.agenticworld.uk
- Outputs the scorer reads: [`out/rules.json`](out/rules.json), [`out/lookups.json`](out/lookups.json), [`out/changes.json`](out/changes.json)

## How it works

```
data/corpus/*.txt + manifest.csv            data/addresses/addresses.csv
        │                                            │
        ▼                                            ▼
 Module A  extract.py                         geocode.py (Census Geocoder, cached)
   chunk with raw offsets                       legal city/county, not the postal city
   model names chunk + first/last words  ──►  jurisdiction stack per address
   quote sliced from the raw text in code            │
   verifier call checks fields vs quote              │
        │                                            │
        ▼                                            ▼
   out/rules.json  ───────────────►  Module B  engine.py + lookup.py
                                       three-valued coverage logic (true / false / unknown)
                                       status, effective and superseded dates, precedence
                                       ──► out/lookups.json
                                                     │
                                                     ▼
                                     Module C  changes.py (data/changes/tests.json)
                                       same engine at two dates, affected sets, conflicts
                                       ──► out/changes.json
```

### What the model does and does not do

The model receives one document as numbered chunks and returns, per rule: category, plain-language requirement (English and Spanish), the key number or formula, a boolean tree of coverage conditions over a fixed fact vocabulary, exemptions, effective date, status, precedence language, penalty, citation, and a pointer to the quote: a chunk id plus its first and last words. The quote itself is sliced from the raw file (`app/corpus.py`), so it is verbatim by construction. A second call verifies each record against its sliced quote and may correct fields, never quotes. Both calls are stored content-addressed in `cache/llm/` with the full prompt and answer: that directory is the audit log, and it lets the demo replay offline.

The decision engine (`app/engine.py`) is ~250 lines of plain Python. AND / OR / NOT over comparisons, with `unknown` propagating only when it could change the result. A certificate-of-occupancy date is derived from the year built when only the year is known (a 1962 building was certainly occupied before 1979; a 1979 building is unknown). Precedence comes from explicit statutory words only (preempt, notwithstanding any local ordinance, shall not apply where a local ordinance): `supersedes`, `yields_to` or the default `stacks_with`. Target rule ids are resolved in code from scope + category + jurisdiction overlap.

### Status and time

- `enacted` law with a future effective date is **not yet effective** before that date and **applies** from it.
- `pending` bills are reported as **pending**, with the addresses they would reach, never as in force.
- `struck` and `repealed` measures reach nobody; their affected set is empty by construction.
- `superseded_date` closes a rule's window so "what was the deposit cap before AB 12" resolves correctly.

Conflicts are flagged generically: same category, overlapping jurisdiction for the address, and a precedence relationship whose effect differs across time (for example a state preemption not yet in force over a local ban that applies today).

## Run it

```bash
make install                 # python venv + deps
cp .env.example .env         # add GEMINI_API_KEY (or ANTHROPIC_API_KEY with LLM_PROVIDER=anthropic)
make test                    # engine and corpus tests, offline
make all                     # extract -> geocode -> lookup -> changes -> validate
make run                     # http://localhost:8000
```

Single steps: `make extract`, `make geocode`, `make lookup AS_OF=2025-12-31`, `make changes`, `make validate`, `make score`.

### The hour-16 document

```bash
make hour16 FILE=path/to/ordinance.txt TITLE="Cambridge Ord. 2026-xx" STATE=MA CITY=Cambridge COUNTY=Middlesex
```

This appends the document to the manifest, extracts it with the unmodified pipeline, re-evaluates every address and appends a `T6` change test whose "after" date is the day after the extracted effective date. The same path is available in the UI under **Add a law**. A blind rehearsal with a synthetic ordinance (`data/samples/cambridge_test_ordinance.txt`, labelled as a fixture) is how the pipeline was tested before any real drop.

## Output files

`rules.json` is a list of rule records (schema in `data/schema/rules.schema.json`). `lookups.json` has one record per sample address with `results` (only rules whose coverage is true or unknown; confirmed non-matches are omitted) and `no_rule_findings` (categories with no enacted rule at the state or city level, a positive finding). `changes.json` has one record per test with `query_before`, `query_after`, `affected_addresses` and `conflicts`. All three validate against the JSON Schemas with `make validate`, which also checks that every `rule_id` in lookups exists in rules and that every quote is found verbatim in the corpus.

Result labels default to snake case (`not_yet_effective`). If the official scorer expects spaces, set `"result_label_style": "spaces"` in `data/schema/vocab.json`; category literals live in the same file.

## Data

- `data/corpus/`: official statute, ordinance and bill text fetched from government sites, with `manifest.csv` (doc id, title, kind, jurisdiction, citation, URL, retrieval date). See its README for what was reachable. Law-firm and news pages are never used.
- `data/addresses/`: 468 multifamily properties from public assessor open data in 9 cities (see its README for sources and gaps: Berkeley has no year built or units, Boston no units, San Diego an effective year).
- The jurisdiction of every address comes from the Census Geocoder (`cache/geocode/`), with a small postal-neighbourhood table as the fallback. The postal city is never trusted on its own: Dorchester is Boston, one "Berkeley" parcel is Oakland.
- No customer, resident or pricing data is used anywhere.

## Interface

A single page served from `static/`. The answer for an address is laid out as a public notice posted in that building's lobby: dated, stamped, bilingual, with the law quoted beneath each line.

- **Notice**: address search, jurisdiction stack with the geocoder method and confidence, building facts, rules by category with an in-force / unknown / not-yet-effective / proposed / superseded stamp, the exact quote, source link, retrieval date, model record, verifier result, and the condition tree. When a rule is unknown, the margin asks the specific missing fact; answering re-stamps the notice on screen only (the scored files keep `unknown`).
- **Time machine**: a date slider that re-runs the engine at any date; stamps flip in place.
- **Changes**: T1 to T6 as posted notices with before and after dates, affected counts, conflicts and the address lists.
- **Record**: every document read, its retrieval date, the model output and verifier records, and every pipeline run.
- **Add a law**: the hour-16 path from the browser.

"Not legal advice" is on every screen.

## Honesty notes

- The official starter pack (schema, dev key, score.py, 87-document corpus) was not on disk when this was built. The corpus here was fetched from the same official sources; the rule vocabulary is in one file to be aligned with the official schema. `app/score.py` is our approximation of the scorer for self-testing and says so.
- The model is Gemini 3.8 Flash (`LLM_MODEL` in `.env`). Rules carry the model name and extraction time.
- Confidence is the model's own estimate blended with the verifier's, scaled by jurisdiction confidence; it is a flag for human review, not a probability of legal correctness.
- Building facts come from assessor data and may be stale or wrong; the notice shows their source.

## Licence

MIT.
