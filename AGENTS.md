# Agent handoff: Swelter

Read this first, then `README.md` (how to run, the data pipeline, which file does what) and `CLAUDE.md` (product
brief and design rules). This file is the current state and the open work; keep it up to date when you finish
something.

Last updated: Oct 24 2026, late evening (HackPSU 2026, Sat 2pm → Sun 2pm; feature freeze Sun 10am, last 2 hours for
the demo video and slides).

## What it is, in one paragraph

Swelter is a disaster what-if simulator for Philadelphia. A planner picks a hazard (heatwave, wildfire smoke, flash
flood, winter storm), a severity (each one a real day on record) and a city response. The map replays that day
(6 AM–10 PM) for 1,560 synthetic residents built from Census tracts and real time-use diaries, coloured by exposure.
A compare panel shows dangerous hours per group against doing nothing; clicking a resident shows their day and a
live "why" explanation. All 48 runs (4 hazards × 3 levels × 4 responses) are precomputed; only `/api/why` is live.

## Run it

```bash
uv run server.py            # http://localhost:8000 (map) and /about.html (showcase page)
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

## Open work, roughly in priority order

1. **LLM planner has never run against the real API** (no key on the dev machine). With a key:
   `uv run scripts/simulate.py --planner llm --only heat_severe`, check the verifier reject rate, then decide
   whether to regenerate all 48 runs. Runs currently use the rule planner.
2. **Live "why" with a key**: check `/api/why` answers with Claude and stays grounded in the resident's facts.
3. **Research track export**: CSV of a run (one row per resident per hour) plus a short methods note download.
   Not built yet.
4. **Sponsor prizes** (see CLAUDE.md): ElevenLabs spoken "why", Vultr hosting, GoDaddy demo domain. None started.
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
