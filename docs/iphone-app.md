# ChillySOS for iPhone: how to run it, what's real, what's missing

Everyone signs in with Auth0. Residents see the city's cooling and warming sites with how busy each one is, and can
ask volunteers for help. Responders get a pop-up when someone asks ("Kayla asked for help"), accept it, navigate
there and close it out. The plan is in `docs/iphone-app-plan.md`.

## Run it

```bash
SWELTER_DEV_LOGIN=1 uv run --env-file .env server.py   # API + web demo on http://127.0.0.1:8000 (keys from .env)
cd ios && xcodegen generate && open Swelter.xcodeproj   # run the ChillySOS scheme on any iPhone simulator
```

The simulator reaches the Mac at 127.0.0.1. For a real phone, run the server with `HOST=0.0.0.0` and build with
`SWELTER_API_BASE=http://<laptop LAN IP>:8000` (or the deployed URL). Put a simulator in North Philadelphia with
`xcrun simctl location booted set 39.9937,-75.1330`; put a connected phone there with
`xcrun devicectl device simulate location start --device <id> --latitude 39.995527 --longitude=-75.148007`
(Kayla's block; `... simulate location clear --device <id>` undoes it).

`SWELTER_DEV_LOGIN=1` adds two demo accounts to the sign-in screen, for a demo with no Auth0 tenant (or as a
backup if the venue Wi-Fi blocks Auth0). Never set it in production.

Off-season demo: Settings › Replay a record day replays a real recorded day (heat, smoke, flood or cold) on the
phone's real clock. The date is the record day's month and day in the current year (Jul 22, 2026 for the record
heat day), so the city's posted site hours apply for that weekday. A dark banner on every screen shows the simulated
date and the real time. Conditions are that day's recorded reading at the current hour, for all 24 hours
(`app/data/replay_hours.json`). The simulation itself covers 6 AM to 10 PM: outside that, crowd forecasts say "No
forecast this hour" and the responder risk layer is empty with a note, instead of showing another hour's numbers.

## Sign-in and accounts

- Auth0 Universal Login on the phone and on the planner web page. The server reads the role from the token:
  **government** with the `view:planner` permission (the planner web page only), **volunteer** (responder) with
  `respond:requests`, **resident** otherwise. The app never decides roles. Tenant setup, step by step:
  [auth0-setup.md](auth0-setup.md).
- A volunteer can ask for help too: account menu › "I need help: switch to resident view"; Settings › "Switch back
  to volunteer view". Their own request never shows in their own queue.
- First sign-in asks for a name. Residents can add a home address (geocoded, must be in Philadelphia) and anything
  a helper should know (65+, lives alone, no AC, …), which pre-fills help requests. Responders see only the
  resident's first name until they accept; the exact address and callback number appear after accepting.
- Where the app measures from: the phone's location if it is in Philadelphia, otherwise the saved home address
  (the map shows a Home pin and says so), otherwise City Hall.
- Demo accounts (`SWELTER_DEV_LOGIN=1`):
  - **Kayla**, resident. Her profile comes from the simulator's resident #1484 on the record heat day: 75+,
    retired, Fairhill (census tract 175), lives alone, no AC, home at Warnock Village. In the simulation she never
    hears the warning and spends 9 AM to 10 PM at extreme danger at home (119 °F heat index at 3 PM).
  - **Marisol Rivera**, responder. A made-up volunteer, no real organisation.
  - **Demo**, government (planner web page only: the "Try the demo" button).

## Voice (ElevenLabs)

With `ELEVENLABS_API_KEY` set, three things are spoken, through `POST /api/speak` (audio cached by text in
`data/tts/`, so a repeated line costs nothing). Without the key, the phone falls back to its built-in voice and the
web page to the browser's.

- **Hourly check-in (resident).** Once per clock hour while the current reading is at danger or worse, by the
  simulator's own bands (`forecast.BANDS`, the stricter set for 65+ or a medical device), a sheet asks "Are you
  okay?" and says it out loud: the time, the reading, the danger level, and "your home has no AC" when that's in the
  profile. "I'm OK" answers with a tip; "I need help", or no answer within the wait set in Settings (2, 5 or 10
  min), sends a "Check on someone" request with a note saying which happened. It works while the app is open (no
  push notifications); a deadline that passed while the app was closed sends on return. Settings › Voice
  check-ins turns it off, sets the wait, and has "Try a check-in now".
- **Request updates (resident).** "Your request is sent", "Marisol Rivera accepted your request and is on the way",
  "… closed your request: checked, they're OK". Settings › Read updates aloud.
- **"Why?" on the web simulator.** ▶ Listen reads the resident's explanation, with diary IDs and 24-hour times
  rewritten for speech.

`/api/speak` has no sign-in (the web demo has none), so set a monthly credit limit on the key.

## Demo script (one phone + the laptop)

Setup: the server runs on a reachable host (Vultr, or the laptop's LAN IP set as `SWELTER_API_BASE`) with
`SWELTER_DEV_LOGIN=1`. The phone is Kayla; the iOS Simulator on the laptop is Marisol (put it in North Philly with
`xcrun simctl location booted set 39.9812,-75.1554`). On both, Settings › Replay a record day › Heat: Record. The
app follows the real clock, so the risk layer and crowd forecasts show between 6 AM and 10 PM.

1. **Web simulator, record heat day.** Open `/?hazard=heat&level=extreme&resident=1484&hour=15`: Jul 22, 2011,
   119 °F heat index, with Kayla's card open (75+, Fairhill, lives alone, no AC, missed the warning, 17 dangerous
   hours, at home all afternoon). Her day is a real ATUS diary.
2. **Phone: sign in as Kayla.** The phone isn't in Philadelphia, so the app uses her home: the Home pin in Fairhill,
   the heatwave card, the nearest open cooling sites with walk times from her block and how busy each is.
3. **Kayla asks for help.** Get help › Check on someone. Her flags (65+, lives alone, no AC) are already filled in.
   Send.
4. **Laptop: Marisol's phone pops up "Kayla asked for help"** within 5 seconds, with the need, her risk flags and
   the distance, location rounded to ~200 m. Accept.
5. **Marisol sees the exact address** (2801 N Warnock St), the nearest cooling site with room, and Navigate.
6. **Kayla's phone now says "Help is on the way · Marisol Rivera accepted"**, and says it out loud. Marisol closes
   it out as "Moved to a site", and Kayla's status shows Done.

Voice check-in variant of steps 3–4 (on the record heat day any hour but 3–7 AM, or any time on the winter
storm day): Settings › Voice check-ins › Ask a volunteer after 2 min, then Try a check-in now. The phone asks Kayla if
she's okay; don't answer. After 2 minutes Marisol gets "Kayla asked for help" with the note "No answer to the 3 PM
check-in".

Reset between runs: stop the server, delete `data/swelter.db`, start it again.

## Where every number comes from

| On screen | Source | Live? |
|---|---|---|
| Alerts (heat, winter storm, flood, air quality) | NWS `api.weather.gov` active alerts at City Hall | live, 2 min cache |
| Temperature, heat index, wind chill | NWS observation at PHL (KPHL) | live, 5 min |
| Next hours | NWS hourly forecast, gridpoint PHI/50,81 | live, 15 min |
| AQI | Open-Meteo air-quality model (CAMS), labelled as a model | live, 10 min |
| Sites, hours, open now, water, accessibility, services | City of Philadelphia `Warming_Cooling_Sites_PUBLICVIEW` ArcGIS layer (87 sites) | live, 10 min |
| Crowd level, 1st choice | A responder's report, shown for 2 h | real people |
| Crowd level, 2nd choice | Phones with crowd counting on (geofence enter/exit, 15-min buckets, daily random token, shown only once 5+ phones counted) | real phones |
| Crowd level, 3rd choice | ChillySOS simulation of the closest real day on record, relative to the site's own busiest hour ("Quiet / Busy / Peak hour"), labelled simulated | simulation |
| Walk times, addresses | Apple Maps (MapKit ETA, reverse geocoding) | live |
| Responder risk layer | ChillySOS simulation: simulated residents at danger level or worse per ~350 m cell, labelled synthetic | simulation |
| Replay conditions | NOAA ISD hourly at PHL; EPA AQS PM2.5 NowCast for smoke; every hour of the record day (`scripts/replay_hours.py`) | recorded |
| Help requests, claims, outcomes | What residents and responders do in the app; nothing is seeded | real people |

## Data we don't have (shown honestly or left out)

- **Live occupancy.** No city source counts people at sites. Crowd levels need responder reports or 5+ phones;
  until then the app shows the labelled simulation forecast, or "No crowd data".
- **Capacity.** The city layer lists capacity for only 9 of 87 sites, so phone counts become a level only there.
  Elsewhere the app shows the phone count without a level.
- **Amenities.** Water station, accessibility and facilities are blank for most sites. The app shows only what the
  city wrote; the design's AC, charging and step-free icons were dropped.
- **Site phone numbers.** There is no field for them. "Call the site" appears only when the city's free-text
  services field contains a number.
- **Philadelphia's own declarations** (Heat Health Emergency, Code Blue, Code Red). These have no public API, so
  the app uses NWS alerts. NWS Frost and Freeze advisories are crop alerts and don't switch the app to cold mode.
- **EPA monitor AQI.** AirNow needs an API key. The app uses Open-Meteo's model and says so.
- **Free SEPTA to cooling sites.** There is no source, so the design's chip was dropped. It would need an admin
  switch.
- **Responder location and ETA.** Not tracked by design, so the resident's status shows who accepted and when,
  with no "9 min away". The responder's phone isn't shared either.
- **Flood depth.** Not in the NWS hourly forecast. Flood days are replay-only (real 3-hour rain at PHL).

## Sponsor tech

| Sponsor | What it does here | Turn it on |
|---|---|---|
| **Auth0** | Sign-in for residents and responders: Universal Login with PKCE from the app (`ios/Swelter/Core/Auth0Login.swift`, no SDK; token kept in the Keychain); the server checks RS256 tokens against the tenant's JWKS and reads the responder role (`backend/auth.py`) | Create a Native app and an API (identifier e.g. `https://api.swelter.app`). Allowed callback: `app.swelter.Swelter://<domain>/ios/app.swelter.Swelter/callback`. Set `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_AUDIENCE`. On the API, enable RBAC and "Add Permissions in the Access Token", add a `respond:requests` permission, and give it to responders (directly or through a Responder role) |
| **Tiger Data** (Timescale) | Presence pings, requests and site reports in Postgres (`presence` a hypertable), and the simulation tables the Ask chat queries (schema `sim`, `resident_hours` a hypertable) | Set `DATABASE_URL` to the Tiger Cloud connection string and run with `--extra tiger`. Unset = SQLite at `data/swelter.db` and `data/simulation.db` |
| **ElevenLabs** | Spoken hourly check-ins, request updates, "Listen" on alerts and on the web "Why?" explainer; audio cached in `data/tts/` | `ELEVENLABS_API_KEY` (optional `ELEVENLABS_VOICE_ID`) |
| **Gemini** | The planner page's Ask chat: question → one read-only SQL query over the simulation tables → answer with its SQL and rows (`backend/ask.py`) | `GEMINI_API_KEY` (optional `GEMINI_SQL_MODEL`, default `gemini-3.5-flash`) |
| **Vultr** | Hosting the planner page and the phone API over HTTPS (Caddy, Let's Encrypt) | On a fresh Ubuntu 24.04 instance with the `~/.ssh/swelter_vultr` key: `deploy/vultr.sh <IP> chillysos.us` → `https://chillysos.us/` (and `https://<ip-with-dashes>.sslip.io/`). Then add those URLs to the Auth0 planner app's callback, logout and web-origin lists. (A `Dockerfile` is also there, untested) |
| **GoDaddy** | Domain for the API and demo | Point an A record (e.g. `api.<domain>`) at the Vultr IP; put TLS in front (Caddy or Vultr load balancer), then set `SWELTER_API_BASE=https://api.<domain>` in `ios/project.yml` |
| **Claude** | The web demo's "Why?" explainer (unchanged) | `ANTHROPIC_API_KEY` |

All keys go in `.env` (template: `.env.example`); run with `uv run --env-file .env server.py`. Every
feature turns off cleanly without its key, and `/api/config` reports which ones are on.

## API

See the docstring at the top of `backend/api.py`. A help request returns a random `secret` that only the
requester's phone holds. Responders see a request's location rounded to ~200 m until they
accept it; then they get the exact point, note and callback number.

## Not verified yet

- Auth0 against a real tenant (no tenant on the dev machine). The demo-account path was tested end to end in the
  simulator: Kayla's request → Marisol's pop-up → accept → exact address; Kayla's status shows Marisol accepted.
- Tiger Data and Gemini with real keys. (ElevenLabs is tested with a real key.)
- The Docker image (Docker isn't installed on the dev machine).
- Geofence crowd counting on a real phone. The simulator can't walk into a site; the server side was tested by
  posting enter events.
