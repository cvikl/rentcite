"""Write JSON Schemas for the three output files from the pydantic models (data/schema/*.schema.json).

Run after any change to app/schema.py: .venv/bin/python scripts/make_schemas.py
If the official starter-pack schema arrives, place it next to these as rules.official.schema.json
and `python -m app.pipeline validate` will also check against it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schema import DATA, ChangeRecord, Lookup, Rule  # noqa: E402

out = DATA / "schema"
out.mkdir(parents=True, exist_ok=True)
for name, model in (("rules", Rule), ("lookups", Lookup), ("changes", ChangeRecord)):
    s = model.model_json_schema()
    arr = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": f"{name}.json", "type": "array", "items": {"$ref": "#/$defs/Item"},
           "$defs": {**s.pop("$defs", {}), "Item": s}}
    # pydantic emits local refs as #/$defs/X already; the Item wrapper keeps them valid
    (out / f"{name}.schema.json").write_text(json.dumps(arr, indent=1))
    print("wrote", out / f"{name}.schema.json")
