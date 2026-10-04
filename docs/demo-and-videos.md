# Demo script and video plan

Written for: the team recording the three submission videos (team, demo, tech). Each must show the scores on screen.

## Submission checklist (both app.hack-nation.ai and the backup Google Form)

- [ ] GitHub repo public, README explains how to run, `out/rules.json`, `out/lookups.json`, `out/changes.json` committed
- [ ] Live demo link: https://rentcite.agenticworld.uk (not localhost)
- [ ] Team video (who we are)
- [ ] Demo video (problem, solution, the tool running; T1 to T6 results on screen)
- [ ] Tech video (pipeline, models, APIs, architecture; score.py report on screen; hour-16 document processed on camera)
- [ ] All team members listed on both forms, before 9:00 AM ET

## Demo video, about 3 minutes

1. **Problem (20 s).** Renting comes with rules from the state, the county and the city; they differ everywhere and change often. Which ones apply to one apartment, today?
2. **The notice (60 s).** Open the live site. Type "Mission St", pick a San Francisco building from 1926. Read the notice: NOTICE TO TENANTS, jurisdiction stack from the Census Geocoder (postal city is not trusted), building facts with their source, rules by category with stamps. Open "Show the law" on the rent-cap rule: the exact quote, source URL, retrieval date, model record, verifier result, and the condition tree.
3. **Unknown is an answer (30 s).** Pick a Berkeley address (no year built or units in the open data). Rules that depend on those facts are stamped UNKNOWN with the missing fact named. Answer the margin question ("What year was the building built?"): the stamp flips in place. Say out loud: the scored files keep "unknown", because the records do not hold the fact.
4. **Time machine (30 s).** Drag the slider to 2025-12-31: California's algorithmic-pricing rule is NOT YET EFFECTIVE; to 2026-01-02 it is IN FORCE. Drag to 2027-07-02 on a Hoboken address: the NJ FAIR Act applies and the local ban is SUPERSEDED, both flagged as a conflict.
5. **Changes board (30 s).** Open Changes. T1 to T6 as posted notices: before and after dates, affected counts, conflicts, the address lists. T5 shows an empty set by construction. T4 shows pending, never in force.
6. **Responsible design (20 s).** Point at: "not legal advice" on every screen, the as-of stamp, enacted vs proposed labels, the Record view (documents, retrieval dates, model records, pipeline runs), Spanish toggle.

## Tech video, about 3 minutes

1. Architecture slide (README diagram). The model reads; plain code decides.
2. Terminal: `make test` (engine, corpus and change tests), then `make all` with the cache on: extraction replays from `cache/llm`, geocode from `cache/geocode`, lookups and changes recompute live, `validate` checks the JSON Schemas, dangling ids and verbatim quotes.
3. `make score`: the self-score report (or the official `score.py` once in the repo), full report visible.
4. **Hour-16 document on camera.** `make hour16 FILE=... TITLE=... STATE=MA CITY=Cambridge COUNTY=Middlesex`. Show the manifest gaining a row, the extraction log, the new rule with its effective date and verbatim quote, the T6 record with affected addresses. Then show the same in the UI under "Add a law". Say: no file in `out/` was edited by hand; the git log proves it.
5. Scalability: a new jurisdiction is one manifest row and one document; conditions use a fixed fact vocabulary so any assessor feed plugs in; precedence comes from statutory words, not per-city code.

## Honesty lines to keep in the videos

- Confidence is a review flag, not a probability the law is right.
- The self-scorer is ours; the official script is the spec.
- Building facts are assessor data and can be stale.
