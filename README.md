<!-- Current UI scope: heat/cold, two responses, ML predictions and site-access metrics. The data-pipeline sections below also document retained training archives. -->
# Swelter — Philadelphia disaster what-if simulator

Pick Heatwave or Winter storm, a severity, and one of two responses: Standard city or Open cooling/warming sites. The map
replays a real day (6am–10pm) for 20,000 synthetic Philadelphians, colored by exposure. The app uses two trained random forests for risk predictions and model-driven shelter priorities. Compare predicted risk-hours, site coverage and uncovered risk by group and hour. Click a resident for their persona, baseline routine and a model-grounded explanation.

Everything the simulation runs on is real data: the hazard days, the people, their routines, the flood and heat maps,
and the city's cooling and warming sites. Remaining assumptions are listed in the app's Methods modal.

## Run the demo

```bash
SWELTER_DEV_LOGIN=1 uv run --env-file .env server.py
```

Open http://localhost:8000. The planner page is for government accounts: sign in with Auth0
([docs/auth0-setup.md](docs/auth0-setup.md)) or, with `SWELTER_DEV_LOGIN=1`, the demo account Jordan Ellis. The
About page (`/about.html`) is public. The current interface uses trained-model outputs for risk and site coverage. Its explanation action describes those model estimates. The server also retains the older /api/why endpoint (government accounts only) for archived simulation workflows.

The normal server serves precomputed ML predictions and rankings; it does not need scikit-learn at runtime.
The server also serves the iPhone app's API.

## Ask the simulation (Gemini + SQL)

The **Ask** button opens a chat with preset demo questions. Gemini Flash (`GEMINI_API_KEY`) turns the question into
one read-only SQL query over the simulation tables (`backend/simdb.py`): `residents`, `resident_hours` (one row
per resident per hour per scenario, with the model's danger probability), `weather`, `sites`, `site_rankings`,
`coverage`, `groups`, `places`. The server checks the query (one SELECT, no writes, row cap, 8 s limit), runs
it and Gemini answers from the rows; the answer shows its SQL and data.

The tables go to Tiger Data when `DATABASE_URL` is a Postgres URL (schema `sim`, `resident_hours` as a TimescaleDB
hypertable on `ts`), else to a local SQLite file `data/simulation.db`. The server loads them on the first question;
to (re)load by hand:

```bash
uv run --env-file .env --extra tiger scripts/load_sql.py
```

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
python3 scripts/simulate.py --residents 19940  # 19,940 housed + 60 unhoused = 20,000; 48 runs (~5 min) -> app/data/
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


## Trained heat/cold shelter priorities

The **Shelter priorities** tab is available for heatwaves and winter storms. Choose 1, 3, or 5 real city-designated sites, inspect their marginal coverage, and click a ranked site to locate it on the map. Smoke and flood retain their existing behavior. The planning layer does not reassign residents or alter the original replay.

Two separate random-forest classifiers predict the probability of baseline simulated dangerous exposure for each resident-hour. Their target comes from stored simulation levels, not observed injuries, demand, or shelter outcomes. Inputs include weather, simulated baseline activity, resident attributes, and local heat/wind modifiers. A greedy coverage optimizer uses those probabilities to rank real facilities by open hours, straight-line access, vulnerability, and proximity. These are priorities among existing facilities, not approved construction locations.

Each hazard has 1,020,000 examples (20,000 synthetic residents × 17 hourly slots × 3 real historical weather days). All hours and severities sharing an ATUS diary stay in the same train/test group; assumed unhoused schedules are grouped by home anchor. Held-out scores compare against a constant-risk baseline. Separate tests also withhold a weather day and the test diary groups. Final ranking models are refit on all examples after evaluation. Models do not establish real-world or future-event validity; geography is not independently held out.

Reachable risk-hours sum predicted danger probabilities during opening hours. They are **not hours prevented**. Site coverage is uncapacitated; routes, current operating conditions, accessibility and facility capacity are unverified. Unhoused residents are oversampled, so counts are simulation counts rather than estimates of Philadelphia's population. The optimizer's vulnerability weights and access radii are documented assumptions, not learned effects.

Reproduce the tested training environment in WSL (Python 3.12):

```bash
python3 -m venv .venv-ml
.venv-ml/bin/python -m pip install -r models/shelters/requirements.txt
.venv-ml/bin/python scripts/train_shelters.py
.venv-ml/bin/python -m unittest discover -s tests -v
```

Alternatively install the optional dependency with `uv sync --extra ml` and run the script with `uv run --extra ml python scripts/train_shelters.py`. The normal app server does not require ML packages: it serves the precomputed report and rankings.

Artifacts: `models/shelters/heat.joblib` and `cold.joblib`; adjacent manifests record source hashes, feature order, library versions, group splits and evaluation. Load only trusted joblib artifacts. Browser results and the model card are in `app/data/shelter_models.json`. Retrain after changing residents, baseline runs or metadata. Training dependencies are recorded in `models/shelters/requirements.txt`.

Current held-out diary-group daily exposure MAE: heat 0.519 h/person; cold 0.318 h/person. On jointly held-out weather days and diary groups, MAE ranges from 0.543–0.950 h for heat and 0.552–0.951 h for cold. The typical cold-day fold has worse Brier score than the constant-risk baseline (0.04132 vs 0.03516); the interface flags this limitation prominently. These are simulator agreement scores.

## Current two-response workflow (Oct 25)

The active app includes only heatwaves and winter storms, each with Standard city and Open cooling/warming sites. Legacy hazard and intervention files remain as archived data but are not loaded by the UI. Removed-hazard deep links fall back to Heatwave; unsupported response links fall back to Standard city.

Standard city shows ML-predicted baseline risk with zero model-selected sites. Open sites displays the top 1/3/5 real facilities selected from model predictions and reports risk-hours within reach, outside coverage, unique at-risk synthetic residents within reach, and hourly/group breakdowns. All metrics aggregate published ML probabilities and cumulative coverage masks; no old intervention exposure summaries are used. The baseline routine files supply positions, activities and weather only. Map risk colors and resident risk summaries use the ML predictions. Opening sites does not assert attendance or prevented exposure.

The active Validation dialog reports the two trained models, and explanations describe predicted risk and reach without invoking historical intervention outcomes. The historical explainer endpoint and pipeline archives are retained for reproducibility, but are not used by the current interface. The About page reflects the two-hazard workflow.
