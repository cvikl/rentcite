PY ?= .venv/bin/python
export PYTEST_DISABLE_PLUGIN_AUTOLOAD := 1
PORT ?= 8000

.PHONY: install run test extract geocode lookup changes all validate score hour16 schemas

install:
	python3 -m venv .venv && $(PY) -m pip install -r requirements.txt

run:
	$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

test:
	$(PY) -m pytest

# Module A: corpus -> out/rules.json (cached model calls; delete cache/llm to re-run from scratch)
extract:
	$(PY) -m app.pipeline extract

# Module B: addresses -> out/jurisdictions.json -> out/lookups.json
geocode:
	$(PY) -m app.pipeline geocode
lookup:
	$(PY) -m app.pipeline lookup $(if $(AS_OF),--as-of $(AS_OF),)

# Module C: data/changes/tests.json -> out/changes.json
changes:
	$(PY) -m app.pipeline changes

all:
	$(PY) -m app.pipeline all

validate:
	$(PY) -m app.pipeline validate

score:
	$(PY) -m app.score

schemas:
	$(PY) scripts/make_schemas.py

# The hour-16 drop: make hour16 FILE=path/to/ordinance.txt TITLE="..." STATE=MA CITY=Cambridge COUNTY=Middlesex
hour16:
	$(PY) -m app.pipeline add-doc "$(FILE)" --title "$(TITLE)" --state "$(STATE)" --city "$(CITY)" --county "$(COUNTY)" $(if $(CITATION),--citation "$(CITATION)",)
