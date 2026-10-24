# Swelter — Philadelphia disaster what-if simulator

Pick a hazard (heatwave, wildfire smoke, flash flood, winter storm), a severity, and a city intervention. The map
replays a simulated day (6am–10pm) of 1,560 synthetic Philadelphians, colored by exposure. The compare panel shows
dangerous-exposure hours by group vs. doing nothing; click a resident for their persona, day timeline, and a live
"why" explanation.

## Run the demo

```bash
uv run server.py
```

Open http://localhost:8000. Set `ANTHROPIC_API_KEY` first to make the "Why?" button call Claude live; without
it the button gives an offline explanation built from the planner's reason codes.

All runs are precomputed in `app/data/`. The server only serves files and `/api/why`.

## Rebuild the data

```bash
python3 scripts/fetch_osm.py      # OSM places + roads (Overpass)       -> data/places.json, data/roads.json
python3 scripts/fetch_extra.py    # waterways + ACS 2024 tract stats    -> data/waterways.json, data/tracts.json
python3 scripts/simulate.py       # 72 runs with the rule planner (~45s) -> app/data/
python3 scripts/validate.py       # Google mobility × NOAA validation   -> app/data/validation.json
```

LLM-generated runs (Claude plans each persona type inside a JSON schema of enums; anything the verifier rejects
is re-prompted once, then falls back to the rule planner):

```bash
uv run scripts/simulate.py --planner llm --only heat_severe
```

Cost: about 250 persona types per scenario, batched 6 per call (~40 calls per run). Start with one hazard and
level (6 runs) before you generate everything. Uses `claude-opus-5-5` at low effort, with server-side refusal
fallbacks enabled; override with `--model`.

## How it works

| Piece | File | Notes |
|---|---|---|
| World | `scripts/swelter/world.py` | 5,460 real OSM places; flood-prone = near river/creek or I-676; heat-island proxy from park density + river |
| People | `scripts/swelter/personas.py` | Sampled from 194 Census tracts (ACS 2024 5-yr); every attribute keeps a `trace` to the tract stat that set it |
| Hazards | `scripts/swelter/hazards.py` | Hourly intensity curves, 4 interventions each, 3 refuge sites, danger thresholds (NWS / EPA / wind chill) |
| Schema + verifier | `scripts/swelter/plan.py` | Fixed activity list + place slots; rejects closed places, impossible trips, housed "unsheltered", etc. |
| Rule planner | `scripts/swelter/rules.py` | ATUS-style templates + hazard behavior rules; every hour carries a reason code |
| LLM planner | `scripts/swelter/llm.py` | Claude, structured output with enums only — no free text reaches the map |
| Exposure | `scripts/swelter/exposure.py` | Deterministic: intensity × time outdoors × AC / heat / HEPA / flood-prone ground floor |
| App | `app/` | MapLibre + deck.gl (vendored, works offline except basemap tiles), vanilla JS |

Same residents, same random draws in every scenario (common random numbers), so differences between runs come
from the intervention, not noise.

## Validation

Real Philadelphia County mobility (Google Community Mobility Reports, summer weekdays 2020–22) on hot days
(PHL Tmax ≥ 92°F) vs. typical days, compared with the simulated moderate heatwave vs. a normal day. Current
mean absolute error is 2.0 percentage points across 6 categories, down from 5.6 before calibration. The
simulation still over-predicts park avoidance. See the Validation button in the app.
