# ChillySOS

**Winner: Best Use of Vultr, HackPSU Fall 2026**

Live at **[chillysos.us](https://chillysos.us)**

When extreme heat or a winter storm hits Philadelphia, three groups need different answers on the same day:

- **City planners** need to know where to send help first.
- **Residents** need to know where to find it.
- **Volunteers** need to know who needs them.

ChillySOS connects those three decisions. City planners get a web dashboard, and residents and volunteers get an iPhone app. Both use one server.

The dashboard replays a real recorded heat or cold day for 20,000 simulated Philadelphians and shows who is in danger, hour by hour. It also ranks the city's real cooling and warming sites by how much of that danger each one can reach. The iPhone app shows residents which sites are open and how busy they are, and connects them to a nearby volunteer with one tap.

Everything the simulation uses comes from public data. The residents are simulated people, but each one's traits come from the real statistics of a Philadelphia census tract, and each one's day is a real recorded day from the U.S. time-use survey.

## Features

### Planning dashboard (web, for government accounts)

**Sign-in.** The dashboard sits behind Auth0 sign-in, and only government accounts can open it. A **Try the demo** button signs in as the demo government account; it appears only while the server runs with `SWELTER_DEV_LOGIN=1`.

**Scenario bar.** Every choice switches instantly, because all runs are precomputed:

- **Hazard:** Heatwave or Winter storm.
- **Day:** each option is a real day recorded at Philadelphia International Airport.

  | Day | Heatwave | Winter storm |
  |---|---|---|
  | Typical | Jul 19, 2020 | Jan 27, 2022 |
  | Severe | Jul 20, 2019 | Jan 2, 2018 |
  | Record | Jul 22, 2011 (119 °F heat index) | Jan 7, 2014 |

- **City response:** Standard city, or Open cooling/warming sites. With sites open, a budget of 1, 3 or 5 sites picks the top-ranked real city sites.

**Map replay.**

- 20,000 simulated residents move through the day from 6 AM to 10 PM over a MapLibre basemap.
- Green dots are at lower predicted risk; dots in the hazard's color are at elevated risk.
- Each move leaves at the minute recorded in that resident's real diary, and travels at walking, driving or SEPTA speed depending on distance, age and car ownership.
- Short trips the hourly plan leaves out (a grocery run, lunch out) also come from the diary and are drawn on the map. Risk scoring stays hourly.
- Open sites show as numbered rings, in rank order.

**Playback.** Play and pause, a time slider with the day's heat index or wind chill drawn behind it, and speeds from 0.25× to 4×. At 1×, one simulated hour takes 4 seconds. The map opens at 11 AM; add `?t=` to the URL to open at another hour.

**Headline finding.** Large text over the map states the day's most important number, for example "Unhoused residents: 10.2 h of predicted danger per person on Jul 20, 2019", with a link to open sites.

**Site coverage.** With sites open, the side panel shows:

- predicted risk-hours within reach of the chosen sites
- risk left outside their reach
- how many residents at risk can reach a site
- each of those broken down by group and by hour

The groups depend on the hazard:

- **Heat:** older adults living alone, outdoor workers, homes without AC, students and unhoused residents.
- **Cold:** older adults living alone, homes without reliable heat, unhoused residents, outdoor workers and residents without a car.

**Find residents.** Filters the map by occupation, age group, no car, no AC or heat, living alone, low income, or asthma/COPD. Everyone else dims, and the panel reports how many match, their danger hours, and how many are at elevated risk right now.

**Resident inspector.** Click any dot to see that resident's:

- profile and predicted danger hours
- 17-hour strip of the day
- hour-by-hour activities
- data trace: the census figures and the survey diary (with its ID) behind them

A **Why?** button asks Gemini 3.5 Flash-Lite to explain that resident's day from their stored facts. Answers usually arrive in about a second and are cached. Claude is the fallback, then an offline summary if neither answers within 8 seconds.

**Ask.** A chat with Gemini over the whole simulation. When a question needs numbers, Gemini writes read-only SQL; it can run up to 4 queries per answer. Each answer shows the queries it ran and the rows they returned.

**Theme.** The whole page takes the hazard's colors: pepper red on warm black for heat, ice blue on navy for cold.

### iPhone app (for residents and volunteers)

Built with SwiftUI and MapKit. Auth0 decides each account's role.

**Residents**

- See the city's live cooling and warming sites on a map, which ones are open now, walking time from Apple Maps, and how busy each one is.
- Ask for help with one tap. The request is pre-filled from their profile (65+, lives alone, no AC, and so on).
- Get an hourly **"Are you okay?"** check-in while the weather is at danger level, read aloud. If there is no answer within 2, 5 or 10 minutes (set in Settings), the app sends a help request.
- Hear request updates spoken aloud: sent, accepted, on the way, closed.

**Volunteers**

- Get a pop-up, read aloud, when someone nearby asks for help. They see the resident's first name and a location rounded to about 200 m.
- Accept the request to see the exact address and callback number, navigate there, and close it out ("Moved to a site", "Checked, they're OK", and so on).
- See a risk map of where the simulation predicts people are in danger at the current hour.
- Report how busy a site is.

**Both**

- **Crowd levels** use the best source available: a volunteer's report from the last 2 hours, then phones counted at the site (only once 5 or more are counted), then the simulation's forecast, labeled as simulated.
- **Live conditions:** National Weather Service alerts, the airport's current reading and hourly forecast, and an air-quality model.
- **Replay a record day** (Settings) runs a real recorded heat, smoke, flood or cold day on the phone's own clock, for demos outside the season.

## How the simulation works

1. **Places.** 5,460 OpenStreetMap places plus the city's 31 cooling and warming sites with their posted hours, FEMA 2023 flood zones, and the city's Heat Exposure Index.
2. **Residents.** Each simulated resident gets a home in a census tract, picked by population. Age, job, living alone, poverty and car ownership come from that tract's ACS 2024 figures. AC and heating come from EIA RECS 2020 by income, and asthma/COPD from CDC PLACES. Every trait records the statistic that set it.
3. **Routines.** Each resident's weekday is a real Bureau of Labor Statistics American Time Use Survey diary from 2018–2024. Diaries are matched on job and age, and drawn from the Philadelphia metro first, then other Northeast metros. Lockdown months are excluded.
4. **Plans.** A rule planner turns each diary into 17 hourly steps (activity and place from fixed lists) and applies hazard behavior: warned residents cancel or shift outdoor plans, and vulnerable residents may stay in. A verifier rejects impossible days.
5. **Exposure.** A deterministic formula: hazard level × time outdoors × AC, heat or filtration at the location, scored against NWS heat-index and wind-chill danger bands.
6. **Behavior check.** The behavior parameters were fit to Google mobility data for Philadelphia in 2020–21. On held-out 2022 hot days, the simulation's change in activity is off by **0.6 percentage points** on average.
7. **Risk models.** Two random forests, one for heat and one for cold, each trained on 1,020,000 resident-hours. Train and test are split by diary, so no routine appears in both. Each model predicts each resident's chance of danger at each hour.

   | Model | Brier score | Constant baseline |
   |---|---|---|
   | Heat | 0.024 | 0.070 |
   | Cold | 0.016 | 0.046 |

8. **Site ranking.** A greedy optimizer ranks real sites by the predicted risk each can reach during its open hours.

Every scenario uses the same residents and the same random draws, so differences between scenarios come from the hazard and the response.

## Built with

| Part | Technology |
|---|---|
| Dashboard | Vanilla JavaScript, MapLibre GL, deck.gl (vendored) |
| Server | Python (`server.py`, `backend/`) |
| iPhone app | Swift, SwiftUI, MapKit, XcodeGen |
| Models | scikit-learn random forests (training only; the server serves precomputed results) |
| Database | **Tiger Data** (TimescaleDB): 2,040,000 resident-hours as a hypertable, plus the phone's site-presence pings. Falls back to SQLite. |
| AI | **Gemini** 3.5 Flash (Ask, with a `run_sql` tool) and Flash-Lite ("Why?"); Claude as fallback |
| Voice | **ElevenLabs** for check-ins, alerts and request updates, cached by text |
| Sign-in | **Auth0** Universal Login with PKCE on web and iPhone; roles from token permissions |
| Hosting | **Vultr** (Ubuntu 24.04), Caddy with automatic HTTPS, systemd; domain chillysos.us |

## Run it locally

```bash
SWELTER_DEV_LOGIN=1 uv run --env-file .env server.py
```

Open http://localhost:8000. `.env` holds the keys; see `.env.example`. Every feature turns off cleanly without its key, and `/api/config` reports which ones are on.

- **iPhone app:** `cd ios && xcodegen generate && open Swelter.xcodeproj`. Setup, data sources and gaps are in [docs/iphone-app.md](docs/iphone-app.md).
- **Auth0 setup:** [docs/auth0-setup.md](docs/auth0-setup.md).
- **Load the database by hand** (otherwise it loads on the first Ask question): `uv run --env-file .env --extra tiger scripts/load_sql.py`.

## Deploy

```bash
deploy/vultr.sh <server IP> chillysos.us
```

The script does the following on a fresh Ubuntu 24.04 Vultr instance:

1. Installs Caddy and uv.
2. Copies the code and `.env` to the server.
3. Sets up a systemd service.
4. Gets HTTPS certificates for the domain (with `www` redirected to it) and for an `sslip.io` name.
5. Opens only ports 22, 80 and 443, then waits until the site answers.

Run it again to push new code; the server keeps its databases.

## Rebuild the data

```bash
python3 scripts/fetch_osm.py          # OpenStreetMap places and roads
python3 scripts/fetch_extra.py        # waterways, ACS 2024 tract statistics
python3 scripts/fetch_real.py         # city layers, CDC PLACES, RECS, NOAA, EPA (~400 MB into data/raw/)
python3 scripts/atus.py               # time-use diaries -> hourly days
python3 scripts/derive_inputs.py      # real hazard days, rates, sites
python3 scripts/validate.py           # fit behavior on 2020-21 mobility, test on 2022
python3 scripts/simulate.py --residents 19940   # 19,940 housed + 60 unhoused residents, all runs (~5 min)
uv run --extra ml python scripts/train_shelters.py   # heat and cold risk models, site rankings
uv run scripts/micro_trips.py         # short trips for the map
python3 scripts/replay_hours.py       # every hour of the record days, for the iPhone app
```

The time-use files must be downloaded by hand, because BLS blocks scripted downloads. From https://www.bls.gov/tus/data.htm, save `atusact-0324.zip`, `atusrost-0324.zip`, and the per-year `atusresp-YYYY.zip` and `atuscps-YYYY.zip` for 2018–2024 into `data/raw/atus/`. The multi-year respondent and CPS files are corrupt on BLS's server.

## Data sources

| What | Source |
|---|---|
| Hazard days | NOAA hourly weather at Philadelphia International Airport, 2010–2024 (heat index, wind chill); EPA AQS PM2.5 with NOAA satellite smoke plumes for smoke days |
| People | ACS 2024 5-year census tracts; EIA RECS 2020 (Pennsylvania); CDC PLACES 2024 release |
| Routines | BLS American Time Use Survey weekday diaries, 2018–2024 |
| Places | OpenStreetMap; City of Philadelphia cooling and warming sites |
| Flood and heat | FEMA 2023 flood zones; City of Philadelphia Heat Exposure Index |
| Behavior check | Google Community Mobility Reports (Philadelphia County) with NOAA daily highs |
| Live (iPhone) | NWS alerts and forecasts, Open-Meteo air quality, the city's live site layer, Apple Maps |

## Repository

| Path | What |
|---|---|
| `app/` | Dashboard: `main.js` (map and panels), `auth.js` (sign-in), `ask.js` (Ask chat), `hud.js` (headline finding), `shelters.js` (site ranking), `brand/` (logo and icons) |
| `app/data/` | Precomputed runs, short trips, model results, metadata |
| `server.py`, `backend/` | Web server and API: sign-in checks, Ask and its SQL guard, live feeds, crowd levels, voice |
| `scripts/`, `scripts/swelter/` | Data pipeline, residents, planner, verifier, exposure, validation, model training |
| `ios/` | iPhone app |
| `deploy/vultr.sh` | One-command deploy |
| `tests/` | Model and coverage tests |

## Limits

- Residents are simulated, so counts are simulation counts. Unhoused residents are oversampled so the group shows up.
- The risk models are checked against the simulation, not against hospital or mortality records.
- "Within reach" means a resident is near an open site during its hours. It is not harm prevented. Site capacity and walking routes are not modeled.
- Some inputs are assumptions, listed in the app: indoor temperatures and filtration, how the Heat Exposure Index maps to degrees, flood-zone weights, riverfront wind, how many residents hear a warning, how far they will travel to a site, and the daily schedule of unhoused residents.
