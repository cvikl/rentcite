---
version: 1
slug: "static-index-html"
primary_target: "static/index.html"
related_targets: ["static/app.js","static/styles.css"]
---

# Surface: static/index.html (the Homerule app shell: lookup, time machine, changes, audit, add-document)

Scope: whole app, one page, Operate mode. Audience: a renter at one address (phone, after a rent letter), an advocate scanning many addresses, a judge watching the demo. Task: type or pick an address, read which rules apply as of a date, open the proof, answer a missing fact, move the date, see what changes, inspect the audit trail, drop a new law in. Constraints: "not legal advice" on every screen; pending and struck law never shown as in force; unknown is a first-class state; everything shown comes from out/*.json through the API.

## Direction contract

THESIS: The answer for an address is a public notice posted in that building's lobby: dated, stamped, bilingual, with the law quoted beneath each line. It refuses the category default (a results list of cards with status chips) and its opposite (a dark data dashboard).

OWN-WORLD: Lobby wall ground (cool warm-gray plaster, #D9D6CF family) carrying one white notice sheet with heavy black rules, a condensed grotesque headline face (Archivo, narrow and black weights) for NOTICE lines and category headings, Public Sans for body, citations and controls. Status is rubber-stamp ink: blue "IN FORCE" for applies, red for NOT YET EFFECTIVE / PROPOSED, pencil-gray margin question for UNKNOWN, a single strike rule for SUPERSEDED. One accent: stamp red. Date stamps are the only rounded objects; everything else is ruled rectangles. Tear-off tab strip at the sheet's foot for the three output files.

STORY: The visitor sees their address at the top of a notice, understands within seconds which rules are in force today and which are coming, believes it because every line shows the exact words of the law and where they were retrieved, and acts: answers the missing-fact question, moves the as-of date, opens the audit, downloads the files.

FIRST VIEWPORT: Top strip: wordmark HOMERULE left, address search (one wide input with a suggestions list) center, as-of date stamp control right. Below, the notice sheet fills the column (max 980px): "NOTICE TO TENANTS OF <street>" in condensed black caps, the jurisdiction stack as three posted-by lines (state, county, city) with the geocoder method and confidence, building facts line. Then category sections ruled by double hairlines; each rule row is: English requirement in bold, Spanish line in regular beneath, citation + effective date strip, stamp at the right edge, "Show the law" disclosure opening the verbatim quote with document title, URL, retrieval date, model record link. Primary action sits in the search input (Enter) and in the as-of stamp.

FORM: Public bilingual tenant notice posted in a lobby; candidate 4 of 7 on the grounded list (ranked: assessor parcel card, annotated code book, certificate of occupancy placard, tenant notice, title abstract ledger, clerk's ordinance stamp, parcel/zoning map sheet). Seed key 06c42478. Code-led (no image generation available).

Raises from the dealt hand (declined and competitive challengers):
- From the split-flap concourse (declined): state changes restyle the row in place; moving the as-of date re-stamps rows without layout shift, stamps flip with one short motion.
- From Japanese high-density web (competitive on advocate clarity): density courage; a rule row packs requirement, citation, dates, stamp and the quote toggle in one ruled block; the change-tests board tiles six notices without card padding inflation.
- From the midnight transit diagram (competitive on jurisdiction clarity): the jurisdiction stack is three layers with the one that governs a given rule burning brightest; context never shrinks.
- From the character catalog (declined): whole-cell reflow; change-test and address lists reflow in whole blocks on phones.
- From the Factory catalog sleeve (declined): nothing is labelled twice; the citation appears once per rule, the quote carries the document, not a repeated citation.

Signature interaction: the as-of date stamp. Dragging the timeline or typing a date re-stamps every rule in place (stamp rotates in, 180ms, exponential ease-out), the sheet header's AS OF stamp updates, and rules whose status changed get a brief margin tick. Motion grammar: 150-220ms, ease-out, transform + opacity + a one-step clip-path reveal for the quote; no page-load choreography.

Memorable moment: a renter types a year built into the pencil margin question and the UNKNOWN stamp flips to IN FORCE in place.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
