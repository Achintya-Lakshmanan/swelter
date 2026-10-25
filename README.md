# Swelter — Philadelphia disaster what-if simulator

Pick a hazard (heatwave, wildfire smoke, flash flood, winter storm), a severity, and a city intervention. The map
replays a real day (6am–10pm) for 1,560 synthetic Philadelphians, colored by exposure. The compare panel shows
dangerous-exposure hours by group vs. doing nothing; click a resident for their persona, day timeline, and a live
"why" explanation.

Everything the simulation runs on is real data: the hazard days, the people, their routines, the flood and heat maps,
and the city's cooling and warming sites. Remaining assumptions are listed in the app's Methods modal.

## Run the demo

```bash
uv run server.py
```

Open http://localhost:8000. Set `ANTHROPIC_API_KEY` first to make the "Why?" button call Claude live; without
it the button gives an offline explanation built from the planner's reason codes.

All runs are precomputed in `app/data/`. The server serves the files, `/api/why`, and the iPhone app's API.

## iPhone app

A resident and responder app on live city and NWS data lives in `ios/`, served by the same
`server.py`. Setup, data sources and gaps: `docs/iphone-app.md`.

## Rebuild the data

```bash
python3 scripts/fetch_osm.py       # OSM places + roads (Overpass)                 -> data/places.json, roads.json
python3 scripts/fetch_extra.py     # waterways + ACS 2024 tract stats              -> data/waterways.json, tracts.json
python3 scripts/fetch_real.py      # city layers, PLACES, RECS, NOAA, EPA          -> data/raw/ (~400 MB)
python3 scripts/atus.py            # ATUS diaries -> hourly days                   -> data/atus_diaries.json
python3 scripts/derive_inputs.py   # real hazard days, RECS/PLACES rates, refuges  -> data/hazard_days.json, inputs.json, ...
python3 scripts/validate.py        # fit behavior on 2020-21 mobility, test 2022   -> data/behavior_fit.json, app/data/validation.json
python3 scripts/simulate.py        # 48 runs with the rule planner (~30s)          -> app/data/
python3 scripts/replay_hours.py     # every hour of the 12 replay days (iPhone app)  -> app/data/replay_hours.json
```

ATUS is downloaded by hand (BLS blocks scripted downloads): from https://www.bls.gov/tus/data.htm, save
`atusact-0324.zip`, `atusrost-0324.zip`, and the per-year `atusresp-YYYY.zip` and `atuscps-YYYY.zip` for 2018–2024
into `data/raw/atus/`. The multi-year respondent and CPS zips are corrupt on BLS's server, and per-year files only go
back to 2018.

To generate runs with the LLM planner instead (Claude plans each persona type inside a JSON schema of enums;
anything the verifier rejects is re-prompted once, then falls back to the rule planner):

```bash
uv run scripts/simulate.py --planner llm --only heat_severe
```

Cost: about 250 persona types per scenario, batched 6 per call (~40 calls per run). Start with one hazard and
level (4 runs) before you generate everything. Uses `claude-opus-5-5` at low effort, with server-side refusal
fallbacks enabled; override with `--model`.

## Data

| What | Source |
|---|---|
| Hazard days | NOAA ISD hourly at PHL 2010–2024 (heat index, wind chill, 3-h rain); EPA AQS hourly PM2.5 2010–2025 (NowCast AQI), smoke days confirmed by NOAA HMS satellite plumes. Each level is a real day: median event, 95th percentile, worst on record |
| Places | OpenStreetMap (5,460 places) + City of Philadelphia cooling/warming sites with posted hours (31) |
| Flood / heat | FEMA 2023 flood zones; City of Philadelphia Heat Exposure Index 2023 (2010 tracts where 2023 is blank) |
| People | ACS 2024 5-yr tracts (B01001, B23001, C24010, B14001, B11007, B17001, B08201); EIA RECS 2020 PA (AC, heat by poverty); CDC PLACES 2024 release (asthma, COPD) |
| Routines | BLS ATUS 2018–2024 weekday diaries, Philadelphia metro first (465 diaries), then Northeast metros |
| Behavior fit + validation | Google Community Mobility Reports (Philadelphia County) × NOAA GHCN-Daily |

## How it works

| Piece | File | Notes |
|---|---|---|
| World | `scripts/swelter/world.py` | OSM places + city refuge sites; FEMA zone and Heat Exposure Index lookups |
| People | `scripts/swelter/personas.py` | Every attribute keeps a `trace` to the statistic that set it, including the ATUS diary id |
| Routines | `scripts/atus.py`, `scripts/swelter/diaries.py` | Diary episodes → 17 hourly steps in the simulator's schema; sampled by role, age, season. Each move keeps the respondent's real departure minute; the map animates it at walk / car / transit speed (exposure is still scored per hour) |
| Hazards | `scripts/swelter/hazards.py` | Real hourly days, 4 interventions each, danger thresholds (NWS / EPA / wind chill) |
| Schema + verifier | `scripts/swelter/plan.py` | Fixed activity list + place slots; rejects closed places, impossible trips, housed "unsheltered", etc. |
| Rule planner | `scripts/swelter/rules.py` | Diary day + hazard behavior rules; every hour carries a reason code |
| LLM planner | `scripts/swelter/llm.py` | Claude, structured output with enums only — no free text reaches the map |
| Exposure | `scripts/swelter/exposure.py` | Deterministic: intensity × time outdoors × AC / heat / HEPA / flood zone |
| App | `app/` | MapLibre + deck.gl (vendored, works offline except basemap tiles), vanilla JS |

Same residents, same random draws in every scenario (common random numbers), so differences between runs come
from the intervention, not noise.

## Validation

The planner's three behavior parameters (share of warned residents who cancel or shift outdoor plans, and whether
vulnerable residents always stay in) are grid-fit to Philadelphia County hot-day mobility in 2020–21 (Google CMR,
hot = PHL high ≥ 92°F vs 78–88°F, within month). On held-out 2022 the simulation's hot-day change across 6 activity
categories is off by 0.6 percentage points on average (the hand-tuned prototype on synthetic days scored 2.0). The fit
says warned residents mostly shift outdoor plans to cooler hours rather than cancel them. ATUS diaries from five I-95
metros were also checked against NOAA highs, but the hot-day change was too uncertain to fit (95% interval −55% to
+160%), so ATUS sets the routines, not the hot-day parameters.
