# Swelter — HackPSU 2026 project handoff

Hackathon: HackPSU, Sat Oct 24 2pm → Sun Oct 25 2pm 2026 (State College, PA). Team of 3–5.
Planning doc (product concept, tracks, datasets, sponsor prizes): https://claude.ai/artifact/6MZbzi8amJxXQnbFcL2QDG

## What we're building
**Swelter**: a disaster what-if simulator for **Philadelphia** (pivoted from State College on Oct 24). A planner
picks a hazard (heatwave / wildfire smoke / flash flood / winter storm), a severity and an intervention; a map
replays a simulated day of synthetic residents (dots colored by exposure); a compare panel shows exposure by
group vs. doing nothing; clicking a resident gives a live LLM explanation of why they did what they did.

## Current state (Oct 24, evening)
Working end to end — see README.md for commands. `uv run server.py` → http://localhost:8000.
- Study area: Center City, University City, North Philly incl. Hunting Park (bbox `39.935,-75.215,40.030,-75.120`).
- 72 precomputed runs: 4 hazards × 3 levels × (none, refuge at 3 candidate sites, 2 hazard-specific interventions).
  Refuge sites: Parkway Central Library, Hunting Park NAC, Lillian Marrero Library.
- 1,560 residents / ~170 persona types from ACS 2024 tracts (via Census Reporter — the Census API now needs a key).
- Runs currently use the rule planner. LLM planner (`--planner llm`) is built and plumbing-tested with a stub, but
  has not been run against the real API yet (no key on this machine).
- Validation: Google mobility (Philly County) × NOAA PHL instead of ATUS — BLS blocks scripted downloads.
  ATUS is still the next step (download in a browser into data/raw/).

Judges should get it in 10 seconds. Demo opens on the map, not slides.

## Core design rules (borrowed from Claude + OpenAI hackathon winners)
- LLM decides behavior **inside a schema**: each hour's activity from a fixed list, each place from a
  fixed list of real map locations. No free text reaches the map.
- **Deterministic code** computes heat exposure (temperature by hour × time outdoors/indoors × AC at location).
- Heavy generation runs **offline as a batch**; the demo replays stored runs. Only the "why" explainer is live.
- Every persona traces back to the data pattern it came from.
- A plausibility verifier rejects impossible days (e.g. no-car resident 10 km away at noon) and regenerates.
- One validation chart + one error number: simulated vs. real hot-day behavior.

## Scenario grid (precomputed)
Per hazard: 3 levels × (none / refuge at chosen site / 2 hazard-specific interventions). Heat: cooling center,
free SEPTA to library cooling sites, early heat alert. Smoke: clean-air center, N95 giveaway, Code Red alert.
Flood: emergency shelter, pre-emptive road closures, early flood warning. Cold: warming center, outreach + open
SEPTA stations, early Code Blue.

Groups in the compare panel are hazard-specific (e.g. heat: older adults living alone, outdoor workers, no-AC
households, students, unhoused residents).

## App screens
1. Map replay (center): dots moving 6am–10pm, time slider, heat-index overlay.
2. Scenario bar (top): heat level + intervention toggles; switching is instant (precomputed).
3. Compare panel (right): dangerous-exposure hours by group, baseline vs. selected intervention.
4. Resident inspector (click a dot): persona card, day timeline, live "why" button (LLM call;
   optionally spoken via ElevenLabs).
5. Validation tab: simulated vs. real aggregates.

## Data (all public — no IRB dependency)
- **OpenStreetMap (Overpass API)** for State College places. Bounding box used: `40.760,-77.920,40.835,-77.790`.
  Pull: libraries, community centres, malls/supermarkets (cooling sites), parks, offices/university
  buildings (work), apartments/dormitories/residential landuse (homes), bus stops, and
  primary/secondary/tertiary roads (`out geom`). Query sketch:
  ```
  [out:json][timeout:60];
  (
   nwr["amenity"~"^(library|community_centre|hospital|clinic|cinema|social_facility|townhall|pharmacy|cafe|restaurant|fast_food|place_of_worship|school|college|university)$"](BBOX);
   nwr["shop"~"^(supermarket|mall|department_store|convenience)$"](BBOX);
   nwr["leisure"~"^(park|sports_centre|swimming_pool|stadium|playground)$"](BBOX);
   nwr["building"~"^(apartments|dormitory|retail|commercial|office|university)$"](BBOX);
   nwr["landuse"~"^(residential|commercial|retail)$"](BBOX);
   node["highway"="bus_stop"](BBOX);
  );
  out center tags;
  ```
- **American Time Use Survey 2025 microdata** (https://www.bls.gov/tus/data/datafiles-2025.htm):
  activity diaries with start/stop times and place type → persona day templates. Join diary date to
  NOAA temperature to split hot vs. normal days for validation.
- **NOAA GHCN-hourly** for hourly temperature/humidity (nearest station: University Park Airport, UNV).
- **NHTS 2022** (https://www.fhwa.dot.gov/policyinformation/nhts.cfm): car access, travel mode, trip timing.
- **EIA RECS 2020** (https://www.eia.gov/consumption/residential/data/2020/): AC prevalence.
- **CATA GTFS** (listed on Transitland for State College): bus routes/stops for the transit intervention.
- **Census ACS** (or RTI synthetic population code) for the population mix.
- Validation extras: Oxford heatwave activity-change dataset (https://zenodo.org/records/14039954),
  CDC Heat & Health Tracker (context slide).

## Tracks to enter
Grand Prize, Research Track (pitch as a behavioral sandbox for heat researchers; add CSV + methods-note
export), Nittany AI Challenge. Mystery Stack: TBD from opening-ceremony reveal. Skip AI Strategy Case.

## MLH sponsor prizes that fit the core flow
Tiger Data (scenario store as time series: one row per resident per hour), ElevenLabs (spoken "why"),
Gemini API (batch generator or explainer — decide before the batch job), Vultr (hosting),
GoDaddy Registry (demo domain), DEV Writing Challenge (post after). Skip Solana; Auth0 only if idle.

## Next steps (where we stopped)
1. Fetch State College OSM places + roads + bus stops → `data/places.json`, `data/roads.json`.
2. Build personas (a few hundred types) and the rules file (heat-behavior knowledge).
3. Batch-generate 12 scenario runs with the LLM inside the schema; verify; compute exposure.
4. Build the map app (Leaflet or deck.gl) reading stored runs; add compare panel + inspector.
5. Validation chart from ATUS × NOAA hot vs. normal days.
6. Reserve the last 2 hours Sunday for demo video + slides. Feature freeze 10am Sunday.

## Open questions
- Mystery Stack reveal: does it fit the pipeline?
- Which cooling-center candidate sites in State College to offer (e.g. Schlow Library, malls, community centers)?
- Gemini vs. another model for generation; Tiger Data yes/no — decide before writing storage code.
