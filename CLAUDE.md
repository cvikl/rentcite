# Homerule, notes for Claude Code

Rental Housing Law Navigator for the 7th Hack-Nation Global AI Hackathon (RealPage challenge). Read `README.md` first.

## Non-negotiables

- The model only extracts (app/extract.py). Plain code decides (app/engine.py). Never move a decision into a prompt.
- Quotes are sliced from the raw corpus text in code (app/corpus.py slice_quote). Never let a model-typed quote reach rules.json.
- `unknown` is a correct answer. Three-valued logic; a missing fact only yields unknown when it could change the outcome.
- No per-rule hand edits in out/. The hour-16 document must pass through `make hour16` untouched.
- Every screen says "not legal advice". Pending and struck law are never shown as in force.
- Output vocab (categories, statuses, result labels) lives in data/schema/vocab.json. When the official score.py is on disk, align the literals there, nowhere else.

## Run

```
make test            # engine + corpus tests, offline
make all             # extract (cached model calls) -> geocode -> lookup -> changes -> validate
make run             # http://localhost:8000
make hour16 FILE=... TITLE=... STATE=MA CITY=Cambridge COUNTY=Middlesex
```

## Design

Impeccable is set up (PRODUCT.md, .impeccable/surfaces). The UI is a public tenant notice posted on a lobby wall; see DESIGN.md once written. Fonts are self-hosted (Archivo, Public Sans). No em dashes in copy.
