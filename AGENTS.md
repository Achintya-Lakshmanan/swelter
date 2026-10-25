# Agent handoff: Swelter

Read this first, then `README.md` (how to run, the data pipeline, which file does what) and `CLAUDE.md` (product
brief and design rules). This file is the current state and the open work; keep it up to date when you finish
something.

Last updated: Oct 24 2026, late evening (HackPSU 2026, Sat 2pm → Sun 2pm; feature freeze Sun 10am, last 2 hours for
the demo video and slides).

## What it is, in one paragraph

Swelter is a disaster what-if simulator for Philadelphia. A planner picks a hazard (heatwave, wildfire smoke, flash
flood, winter storm), a severity (each one a real day on record) and a city response. The map replays that day
(6 AM–10 PM) for 20,000 synthetic residents built from Census tracts and real time-use diaries, coloured by exposure.
A compare panel shows dangerous hours per group against doing nothing; clicking a resident shows their day and a
live "why" explanation. All 48 runs (4 hazards × 3 levels × 4 responses) are precomputed; only `/api/why` is live.

## Run it

```bash
SWELTER_DEV_LOGIN=1 uv run --env-file .env server.py   # http://localhost:8000 (map, government sign-in) and /about.html (public)
```

Deep links: `/?hazard=smoke&level=extreme&iv=n95` (hazard: heat|smoke|flood|cold; level: moderate|severe|extreme;
iv: none|refuge|transit|alert|n95|closures|outreach, per hazard). `ANTHROPIC_API_KEY` makes the "why" button call
Claude; without it the server answers from the planner's reason codes.

## Where things are

| Path | What |
|---|---|
| `app/index.html`, `main.js`, `style.css` | The map app (MapLibre + deck.gl, vendored in `app/vendor/`, vanilla JS) |
| `app/about.*`, `app/img/` | Showcase page; screenshots, clips and 2 credited photos (`app/img/credits.json`) |
| `app/data/` | Precomputed runs (`runs/{hazard}_{level}_{iv}.json`), `meta.json`, `validation.json` |
| `scripts/` | Data pipeline and simulator (see README "Rebuild the data" for the order) |
| `scripts/swelter/` | World, personas, hazards, schema + verifier, rule planner, LLM planner, exposure |
| `data/` | Derived inputs (committed). `data/raw/` is gitignored (~400 MB; ATUS must be downloaded by hand) |
| `server.py` | Static server + `/api/why` + `/api/status` |
| `.claude/skills/` | Project skills: design-taste-frontend, web-design-guidelines, awesome-design-md, image-to-code, playwright-cli |
| `.taste-skill/direction.json` | The design direction the About page follows (Schibsted Grotesk, frost and slate) |

## Done

- Real data end to end: NOAA hourly at PHL, EPA AQS PM2.5 2010–2025 with NOAA HMS satellite smoke plumes (22 smoke
  days), ACS 2024, RECS 2020, CDC PLACES, FEMA flood zones, city Heat Exposure Index, the city's 31 cooling/warming
  sites, OSM, ATUS 2018–2024 diaries.
- Behaviour fitted to Google mobility 2020–21, held-out 2022 error 0.6 pp (Validation modal in the app).
- Movement uses each diary's real departure minute, animated at walk / car / transit speed; playback 1× = 15 min/s.
- Compare panel, intervention grid, resident inspector with "why", Methods modal listing every assumption, caution
  note on the typical smoke day (AQI 101–150, so no one reaches danger).
- About page redesigned (passes the taste-skill lint and inspector: 0 FAIL).
- Web Interface Guidelines pass on the map: aria-pressed on scenario buttons, live play/pause label, focus ring.

## The iPhone app (built Oct 24)

Everyone signs in with Auth0. Residents see the city's cooling and warming sites with crowd levels and can ask for
help; responders (an organiser grants the role in Auth0) get a pop-up for each new request, accept it and navigate
there. The demo uses two demo accounts: Kayla (the simulator's resident #1484) and Marisol Rivera (responder). The code is in `ios/` (SwiftUI, XcodeGen) and `backend/` (API served by
`server.py`). For how to run it, where every number comes from, the data gaps, sponsor setup and what's unverified,
read `docs/iphone-app.md`. The plan is in `docs/iphone-app-plan.md`, and the designs are on the Claude Design
canvas https://claude.ai/artifact/9wK7K5wgAtZ5E75buTAu7m (private).

## Open work, roughly in priority order

1. **LLM planner has never run against the real API** (no key on the dev machine). With a key:
   `uv run scripts/simulate.py --planner llm --only heat_severe`, check the verifier reject rate, then decide
   whether to regenerate all 48 runs. Runs currently use the rule planner.
2. **Live "why" with a key**: check `/api/why` answers with Claude and stays grounded in the resident's facts.
3. **Research track export**: CSV of a run (one row per resident per hour) plus a short methods note download.
   Not built yet.
4. **Sponsor keys**: Auth0 (tenant dev-ml8dvjy6kigpgvxb), Tiger Data, Gemini, ElevenLabs and Vultr are live. **Live server: https://144-202-2-216.sslip.io/** (Vultr vc2-1c-2gb, New York, $10/mo; `deploy/vultr.sh 144.202.2.216` pushes new code; the URL is in the Auth0 planner app; the phone build points at it via `SWELTER_API_BASE`). GoDaddy is still open: point an A record at the IP and pass that name to `deploy/vultr.sh`.
5. **Demo**: 2-minute video and slides; demo opens on the map, record heat day, then "Show me someone whose day
   changed".
6. `image-to-code` skill is installed but needs an image-generation tool, so it was not used.

## Conventions and gotchas

- Commit only when asked; work on a branch, then fast-forward `main`. End commit messages with the co-author line
  the team uses.
- No free text from an LLM reaches the map: activities and places are enums, a verifier rejects impossible days.
- Same residents and random draws in every scenario, so differences come from the intervention.
- Bump the `?v=` query on CSS/JS links in the HTML when you change those files; the browser caches hard.
- `window.swelter` exposes `state`, `select`, `featured`, `run`, `residentPos` for scripted screenshots.
- This Mac has Reduce Motion on: headless browsers inherit it. The taste-skill inspector was patched to emulate the
  motion preference explicitly (`scripts/lib/cdp.mjs`); for playwright use `page.emulateMedia({ reducedMotion: 'no-preference' })`.
- BLS blocks scripted ATUS downloads; do not try to work around it. Download by hand (README).
- Danger thresholds live in `scripts/swelter/hazards.py` (AQI bands differ for vulnerable residents).

## UI redesign — Oct 24, 2026
- Presentation updated on branch codex/minimal-ui: neutral dark workspace, teal actions, labeled scenario controls, compact About page, no decorative entrance motion or glass surfaces.
- Group highlights support Enter/Space; native buttons keep their own Space behavior.
- Verified all 48 scenario selections, playback controls, resident inspector, Methods/Validation, deep links, About form, and 390px overflow in Chrome. No page errors. Offline explanation function checked in WSL; live Claude and audible speech not verified.
- APIs, simulation data, routes, and backend unchanged. No commit created.


## Trained thermal shelter models — Oct 25, 2026
- Branch codex/thermal-shelter-models. Separate heat and cold RandomForestClassifier artifacts trained from baseline simulated exposure labels, 79,560 resident-hours per hazard across three observed weather days. These are simulator surrogates, not validated health/shelter outcome predictors.
- scripts/train_shelters.py trains, evaluates grouped diary holdouts plus unseen-day folds, saves models/shelters artifacts/manifests and app/data/shelter_models.json. Optional ml dependency; normal server has no ML dependency. Reproduction dependencies in models/shelters/requirements.txt.
- Shelter priorities tab ranks real cooling/warming sites for 1/3/5-site budgets using predicted baseline risk, opening hours, explicit vulnerability weights and straight-line access. Click a site to focus its numbered map marker. Replay assignments, all 48 runs, smoke/flood and APIs are preserved.
- Eight unit tests cover artifact/input hashes, group overlap, baseline performance, marginal coverage, hours, distance and hazard eligibility. Chrome checks cover original scenarios, model panels, loading/error/retry, keyboard, mobile and live offline explanation API.
- Heat held-out daily MAE 0.519h, cold 0.318h. Typical cold-day unseen-weather fold fails to beat constant-risk Brier baseline; shown prominently in UI. No real-world generalization claim. No route safety, capacity or current facility verification. Unhoused residents are oversampled; counts are synthetic.


## Active scope update — Oct 25, two hazards and two responses
- Supersedes the earlier four-hazard / 48-run UI description: active app is Heatwave or Winter storm, each Standard city or Open cooling/warming sites. Removed links fall back safely. Underlying training archives are retained.
- Site budget 1/3/5 controls only model-selected facilities. All displayed risk/coverage metrics and map risk labels derive from trained-model probabilities. Baseline _none files supply routine geometry, activities and weather; old intervention files are never requested.
- train_shelters.py now publishes risk_milli matrices and cumulative coverage_masks for each budget. Nine Python tests include reconstruction of all published coverage metrics.
- Resident animation remains the baseline routine: site opening does not assume attendance or prevented harm. Explain action uses model predictions and access assumptions, not the archived intervention explanation endpoint. Validation and About now describe the two-model scope.
- Chrome checked all 12 hazard/severity/response combinations, 1/3/5 budgets, probability totals, resident explanations, dialogs, mobile layouts, removed deep links and About form; no JavaScript errors or old response-run requests.

## Sidebar cleanup — Oct 25
- Removed the four top-line KPI blocks, the planning-estimates paragraph and the Model quality and data disclosure from the main sidebar at user request. Calculations, ranked site details and Methods/Validation remain available.

## Resident UI cleanup — Oct 25
- Removed the resident risk explanation/Listen section and priority-resident button/handler. Direct map-dot inspection remains. The sidebar hint now explains population categories, examples and how to clear the highlight.

## Auth0 gate, Ask chat, SQL store — Oct 25 (branch iphone-app)
- Merged main's new dashboard into iphone-app. The planner page sits behind the Auth0 government gate (`app/auth.js`;
  demo account Jordan Ellis with `SWELTER_DEV_LOGIN=1`). Static data files are still public; the gate is the UI and the APIs.
- **Ask** (top bar): preset demo questions or free text → `POST /api/ask` (government only) → Gemini Flash writes one
  SQL query (`backend/ask.py`) → `backend/simdb.py` checks it (single SELECT, deny-list, 500-row cap, 8 s) and runs it
  read-only → Gemini answers from the rows. Answers show model, engine, SQL and rows.
- Simulation tables (heat/cold × 3 days, 2,040,000 resident-hours at 20,000 residents): Tiger Data with `DATABASE_URL`
  (schema `sim`, hypertable on `ts`), else `data/simulation.db`. Loaded on first question or `scripts/load_sql.py`.
  Not yet run against a real Tiger Data service (no `DATABASE_URL` on this machine).
- Scaling: `simulate.py --residents 10000` takes ~6 s per run (2.2 MB run JSON, 11 MB meta.json); the browser replay
  is the limit past ~10–20k, SQL aggregates are not. Scaling also needs `train_shelters.py` re-run for risk matrices.

## Further sidebar cleanup — Oct 25
- Removed hourly coverage disclosure/table/note, population-category guidance, historical context paragraph, shelter planning heading/intro and duplicate open-sites action. Standard city hides the empty site section; City response still opens the selected-site list and map markers.

## Simulator restyle — Oct 25 (branch ui-redesign)
- Merged origin/iphone-app (20k residents, Auth0 gate, Ask, slider fixes) into ui-redesign, then restyled the planner page: black "Instrument" look, Schibsted Grotesk, full-bleed map with a live finding over it (`app/hud.js`), green lower-risk dots, hazard-coloured elevated dots, numbered white site rings, opens at 11 AM (`?t=` overrides), paused under Reduce Motion.
- Inspector: danger-hours figure, 17-hour strip, live "why" button (`/api/why` with `swelterAuth.headers()`), chips, hour-by-hour and data trace collapsed.
- Removed Validation, Methods and About from the bar (their modals too). about.html still exists but is unlinked. The redesign landing page was discarded.
- Slider: fixed-size thumb; spark and tick labels are inset by half the thumb so thumb, playhead and labels match to the pixel.
- Local testing: `.claude/launch.json` has `swelter-dev` (SWELTER_DEV_LOGIN=1) for the demo government account "jordan".
- Oct 25 later: theme follows the hazard (`data-hazard` on <html>: warm blacks + crimson for heat, blue-blacks + blue for cold; Ask panel and its suggestions follow). 0.25× playback. "Find residents" filter in the panel (occupation, age, no car / no AC or no reliable heat / lives alone / low income / asthma-COPD) dims non-matching dots and reports matches, danger hours and how many are at elevated risk now.
- `/api/why` now tries Gemini first (GEMINI_API_KEY, model GEMINI_WHY_MODEL default gemini-3.5-flash-lite), then Claude, under an 8 s budget (SWELTER_WHY_TIMEOUT) before falling back to the offline text; answers are cached per scenario+resident and report their latency. Benchmark (`uv run --env-file .env python tools/why_latency.py`, Oct 25): flash-lite p50 1.25 s / p95 2.9 s, 1 error in 12; flash p50 9.2 s / p95 24 s with 503s, so only flash-lite is used, with one retry. In the running app 12 of 12 clicks answered by Gemini, p50 1.1 s, max 1.8 s; repeat clicks 2 ms from cache.
