# ChillySOS for iPhone: plan

Status: plan, Oct 24 2026 (night). Design mockups live on the design canvas linked from AGENTS.md.

## The idea

The simulator answers a planner's question before a bad day: *which response protects whom?* The iPhone app is the
same city on the day itself, for two kinds of people:

- **Residents** open a map of the city's cooling and warming sites (the same 31 real sites the simulator uses), see
  which are open, how far they are and how crowded they are right now, and can ask for help when they can't get there.
- **Responders** (vetted volunteers and outreach workers) see where people are asking for help, which sites are filling
  up, and where the simulator expects danger to concentrate, then claim a request and close it out.

Phones feed the crowd picture back in, anonymously and only with consent. That closes the loop: plan with ChillySOS,
act with the app, and feed what really happened back into the next simulation.

## Who uses it

| Person | What they need in the moment |
|---|---|
| Older adult living alone, no AC | The nearest open site, how to get there, someone to call if they can't |
| Outdoor worker | Where to cool off on a break, today's danger hours |
| Neighbour or family member | Ask for a check on someone else |
| Unhoused resident (often via an outreach worker's phone) | A site with room tonight, water |
| Volunteer on duty | Requests near them, what each person needs, how to hand off to 911 |
| Site lead | Report "nearly full" so the app redirects people |

## Resident mode

1. **Map home.** Your location, every site as a pin coloured by state (open and quiet / busy / nearly full / closed).
   A hazard banner on top ("Heat Health Emergency · heat index 108°F until 8 PM"). A bottom sheet lists the nearest
   open sites: walk time, crowd level, closing time. Free SEPTA to cooling sites is shown when that response is on.
2. **Site detail.** Name, address, hours, what's there (water, AC, accessible, pets, charging), crowd now, and a
   "usually busy" chart for today. Buttons: directions (hands off to Apple Maps, walk or transit), call the site.
3. **Get help.** One screen, big targets. What do you need: a ride to a cool place, water or supplies, someone to check
   on me or on someone else, I can't get out (flood, snow). Who: how many people, 65+, mobility or medical device,
   pets. Where: your approximate location (shown) and an optional callback number. A permanent "Life-threatening?
   Call 911" button above everything, and the app never promises a response time.
4. **Request status.** Sent → a volunteer accepted → on the way → done, with a cancel button and the 911 button.
5. **Privacy and settings.** One switch, off by default: "Help count crowds at cooling sites". Language (English and
   Spanish at launch), text size follows the phone.

No account for residents. Nothing about a resident is stored beyond an open help request.

## Responder mode

Entered with an invite code from a partner organisation (for the hackathon, a code we hand out).

1. **Duty map.** On-duty switch. Open help requests as pins coloured by urgency (waiting time × vulnerability flags),
   sites coloured by capacity, and a ChillySOS risk layer: where today's simulated run puts dangerous exposure, by
   hour. Filters by need type.
2. **Request queue.** The same requests as a list, most urgent first: need, people and flags, distance, minutes
   waiting.
3. **Request detail.** Approximate area only (a ~200 m circle) until you claim it; the exact point and callback
   number appear once you claim. Buttons: claim, navigate, call, mark done with an outcome (moved to a site, delivered
   water, checked and fine, handed to 911), or release it back.
4. **Sites board.** Every site's crowd level and closing time; nearly-full sites suggest the nearest one with room.
   Site leads can set "nearly full" or "full" directly.

## Crowd data from phones

What we collect, and only from residents who switch it on:

- **Site presence.** The app watches geofences around the nearest 20 sites (iOS allows 20 monitored regions) and sends
  `{site, enter|exit, 15-min time bucket, today's random token}`. No coordinates, no device id; the token rotates
  daily so visits can't be linked across days. Occupancy = enters − exits in the last 4 hours, decayed.
- **Optional street density** (later, not MVP). Phones report a coarse grid cell (~250 m) every 15 minutes while
  outdoors; the server shows a cell only when at least 10 phones are in it, and only after a 15-minute delay.

How a site's crowd level is decided, best source first:

1. A site lead's report (manual, expires after 2 hours).
2. Phone presence, scaled by app adoption and compared to the site's capacity, shown only as quiet / busy / nearly
   full, and only when at least 5 phones contributed.
3. ChillySOS's forecast for today: the simulated arrivals per site per hour on the matching real day. Labelled "usually".

## How it connects to ChillySOS

- Same sites, same hours, same hazard thresholds (`app/data/meta.json`, `scripts/swelter/hazards.py`).
- The risk layer in responder mode is the simulated dangerous-exposure grid for today's hazard level.
- Forecast crowding comes from simulated refuge arrivals per hour.
- After an event, real presence counts and help requests become a validation set for the simulator: did people go
  where it predicted?

## Architecture

- **iOS app:** SwiftUI, MapKit for SwiftUI, Core Location (when-in-use for the map; "always" asked only when a
  resident turns on crowd counting, for geofences). iOS 17+. One app, two modes.
- **Backend:** extend `server.py` (it already serves the data) with a small JSON API and SQLite.
  `GET /api/sites` (sites + hours + live crowd level), `POST /api/presence`, `POST /api/requests`,
  `GET /api/requests` (responders), `POST /api/requests/{id}/claim|done|release`, `POST /api/sites/{id}/report`,
  `GET /api/risk?hour=` (ChillySOS grid).
- **Later:** APNs push for alerts and request status; Tiger Data (Timescale) for the presence time series (sponsor
  prize); hosting on Vultr.

## Hackathon scope (feature freeze Sun 10am)

Build now:

- Backend endpoints with SQLite, seeded with the 31 sites and ChillySOS's forecast crowding for the record heat day.
- Resident mode: map, site sheet, get help, request status.
- Responder mode: invite code, duty map with requests and sites, queue, claim / navigate / done.
- Demo mode: replay the record heat day with simulated residents standing in for phones (clearly labelled
  "simulated"), so crowding and requests appear without real users. Run it in the iOS Simulator.

Cut for now: real geofencing in the background, street density grid, push notifications, accounts, Spanish copy
review, real responder vetting.

## Risks and how we handle them

| Risk | Mitigation |
|---|---|
| Location data from vulnerable people | Opt-in, no coordinates for presence, daily tokens, k-thresholds, nothing kept after a request closes |
| Someone poses as a volunteer to find vulnerable people | Invite codes from partner orgs, approximate area until claimed, one active claim per responder, every claim logged |
| People rely on the app instead of 911 | 911 button on every help screen; no promised response time; medical flags show 911 guidance first |
| Too few users for real crowd counts | Fall back to site-lead reports and ChillySOS's forecast, always labelled |
| Battery | Region monitoring only (no continuous GPS) |

## Demo script (90 seconds)

1. Resident: the record heat day banner; nearest open site is busy, the next one is quiet; open it, directions.
2. Resident: "Check on someone": an 81-year-old neighbour with no AC, two blocks away. Send.
3. Responder: the request appears on the duty map next to the ChillySOS risk layer; claim it, navigate, mark "moved to
   cooling site".
4. Back in ChillySOS: the same site's forecast against what the app recorded.

## Open decisions for the team

- App name (ChillySOS, or a resident-facing name like "Cool Spots Philly").
- Which partner organisations would vet responders (for the pitch).
- Whether residents' help requests need a phone number (callback) or stay fully anonymous.
- Street density grid: in for the pitch only, or built?
