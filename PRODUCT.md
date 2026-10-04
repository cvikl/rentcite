# Product

<!-- impeccable:product-schema 1 -->

All facts below are inferred from the challenge brief (RealPage x Hack-Nation, Challenge 02), the team build brief and the kick-off transcript. The user asked for an unattended build, so no interview was held; every section is an inference unless it quotes the brief.

## Platform

web

## Stack

delegated: vanilla HTML/CSS/JS served as static files by the FastAPI back end (same as the sibling NoticeGuard project), no build step, deployable as one container on the shared Hetzner box.

## Users

- Renters at a specific address who want to know which rent, deposit, fee, screening, eviction and algorithmic-pricing rules protect them today. Scene: on a phone or laptop, often after a rent-increase letter or a lease offer, no lawyer.
- Housing advocates and agency staff who look across many addresses and need to see what a pending or newly signed law changes, and where.
- Small housing providers without legal teams who want to know their obligations before acting.
- Hackathon judges (inferred): they watch a demo and tech video and read the three output files; they score plain language, responsible design and scalability.

## Product Purpose

Homerule answers one question for any apartment address in the data set: which housing rules apply here today, and what is about to change. Every answer carries a verbatim quote from the source law, a citation, an as-of date and a status (applies, unknown, superseded, not yet effective, pending). Success is a correct, cited, honest answer: "unknown" when a fact is missing is a correct output, never a failure state.

## Positioning

The model only reads and structures the law; plain code decides. Quotes are sliced from the source text, never retyped by the model, so every citation is verbatim by construction. Three-valued logic (true / false / unknown) runs each rule's coverage conditions against the building facts, so the tool says "unknown" exactly when a missing fact could change the answer. A new law dropped into the corpus is handled by the unmodified pipeline, end to end.

## Operating Context

- Scope: California (Los Angeles, San Francisco, San Diego, Berkeley, Santa Ana), New Jersey (Jersey City, Hoboken, Newark), Massachusetts (Boston, Cambridge); six rule categories.
- Inputs: a corpus of official statute, ordinance and bill text with a manifest (URL, retrieval date); about 500 multifamily addresses from public assessor data (street, postal city, ZIP, year built, units, use code); the Census Geocoder for the legal jurisdiction.
- Outputs the judges' script reads: rules.json, lookups.json, changes.json. The UI is a window onto the same engine.
- Change tests T1-T6, including a fictional ordinance released at hour 16 that must be processed with zero manual edits.

## Capabilities and Constraints

- Address lookup with jurisdiction stack (state, county, city), per-rule result, reason, citation, quote, confidence, conflict flag, missing facts.
- As-of date query over any date (version fields on every rule).
- Fact completion: when a result is unknown, the UI asks the specific missing question and re-evaluates; the scored files still say unknown.
- Change tracking: before/after address sets per test, conflict flags, affected addresses.
- Audit log: source document, retrieval date, model output record, verification result, run history.
- Add a document from the browser: runs the same extraction and recomputes everything.
- Plain-language view in English and Spanish (requirement and requirement_es per rule).
- Must say "not legal advice" on every screen. Must never present pending or struck law as in force. Must never suggest ways around a rule. No customer, resident or pricing data anywhere.
- Undecided: the official starter pack's exact field names and enum spellings are not on disk; the vocab lives in one file (data/schema/vocab.json) to be aligned when score.py is read.

## Brand Commitments

- Name: Homerule. Byline: "Which rules apply here today, and what is about to change." Venture: Rule & Record (ruleandrecord.com), sibling product NoticeGuard uses an editorial legal identity (paper ground, ink type, serif headings). Inferred commitment: Homerule should read as the same family without copying NoticeGuard's screens.
- Voice: plain, specific, never advisory. "Not legal advice" is a sentence the product says in its own voice, not a legal footer.

## Evidence on Hand

- Challenge brief PDF and team build brief (in ../). Kick-off transcript.
- Corpus and addresses are being assembled from official and open-data sources into data/corpus and data/addresses; where a source was unreachable the README of that folder says so. No testimonials, customers, benchmarks or scores exist yet; the demo must not claim any.
- A synthetic Cambridge test ordinance (data/samples/) exists for the blind hour-16 rehearsal and is labelled as a test fixture.

## Product Principles

1. The quote is the proof. No sentence in the UI about a rule stands without its source span one click away.
2. Unknown is an answer. Show what fact is missing and let the renter supply it; never guess around it.
3. Time is a first-class input. Every answer is "as of" a date; pending and struck law are shown apart from law in force.
4. Code decides, the model reads. Make that visible: the audit trail is part of the product, not a debug page.
5. Nothing here is advice. The product tells people what the law says and where to check, never what to do.

## Accessibility & Inclusion

Renters may read on small phones in poor light; Spanish-language view is a stated stretch goal of the brief. Keyboard operability and 4.5:1 contrast are the floor.
