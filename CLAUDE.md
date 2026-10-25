# Swelter — HackPSU 2026 project handoff

Hackathon: HackPSU, Sat Oct 24 2pm → Sun Oct 25 2pm 2026 (State College, PA). Team of 3–5.
**Start with AGENTS.md** (handoff: state, open work, conventions), then README.md.
Planning doc (product concept, tracks, datasets, sponsor prizes): https://claude.ai/artifact/6MZbzi8amJxXQnbFcL2QDG

## What we're building
**Swelter**: a disaster what-if simulator for **Philadelphia** (pivoted from State College on Oct 24). A planner
picks a hazard (heatwave / wildfire smoke / flash flood / winter storm), a severity and an intervention; a map
replays a simulated day of synthetic residents (dots colored by exposure); a compare panel shows exposure by
group vs. doing nothing; clicking a resident gives a live LLM explanation of why they did what they did.

## Current state (Oct 24, late evening) — everything runs on real data
Working end to end — see README.md for commands. `uv run server.py` → http://localhost:8000.
- Study area: Center City, University City, North Philly incl. Hunting Park (bbox `39.935,-75.215,40.030,-75.120`).
- 48 precomputed runs: 4 hazards × 3 levels × 4 interventions. Each level replays a **real day** (median event day,
  95th-percentile day, worst on record): NOAA hourly at PHL for heat index / wind chill / 3-h rain, EPA AQS NowCast for
  smoke (22 days 2010–2025 at AQI ≥ 101 under a NOAA HMS satellite smoke plume, May–Sept). Refuges are the city's **real 31 cooling/warming sites** with posted hours (no more site picker).
- Residents: ACS 2024 tracts (age, employment by age, occupation, college, 65+ alone, poverty, cars), RECS 2020 PA
  (AC / heat by poverty), CDC PLACES 2024 release (asthma + COPD; the 2025 release has no PA values).
  FEMA 2023 flood zones and the city's Heat Exposure Index replace the river-distance / park-density proxies.
- Each housed resident's weekday is a **real ATUS diary** (2018–2024, Philadelphia metro first, then Northeast metros;
  lockdown months excluded). BLS's multi-year respondent/CPS zips are corrupt on their server, and per-year files
  start in 2018 — downloaded through Chrome into data/raw/atus/.
- Behavior parameters (cancel / shift / vulnerable-stay) are grid-fit to Google mobility 2020–21 and validated on
  2022: held-out MAE 0.6 pp. ATUS × NOAA hot-day analysis was too noisy to fit (95% CI −55%…+160%); reported as evidence.
- Runs use the rule planner. LLM planner (`--planner llm`) gets the diary day in each persona card but has not been run
  against the real API (no key on this machine).
- Still assumed (listed in the Methods modal): indoor temperatures/filtration, HEI→°F scale, flood-zone weights,
  riverfront wind, warning awareness, refuge travel limits, unhoused schedule.

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
Per hazard: 3 real days × (none / open the city's real refuge sites / 2 hazard-specific interventions). Heat: cooling
sites, free SEPTA to cooling, early heat alert. Smoke: clean-air rooms, N95 giveaway, Code Red alert. Flood: shelters
outside the FEMA zone, pre-emptive road closures, early flood warning. Cold: warming sites, outreach to 24-hour
sites, early Code Blue.

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
The State College data plan is superseded. The sources actually used, and how to rebuild them, are in README.md
("Data" and "Rebuild the data").

## Tracks to enter
Grand Prize, Research Track (pitch as a behavioral sandbox for heat researchers; add CSV + methods-note
export), Nittany AI Challenge. Mystery Stack: TBD from opening-ceremony reveal. Skip AI Strategy Case.

## MLH sponsor prizes that fit the core flow
Tiger Data (scenario store as time series: one row per resident per hour), ElevenLabs (spoken "why"),
Gemini API (batch generator or explainer — decide before the batch job), Vultr (hosting),
GoDaddy Registry (demo domain), DEV Writing Challenge (post after). Skip Solana; Auth0 only if idle.

## Next steps and open questions
See AGENTS.md: current state, what is done, open work in priority order, and conventions.
