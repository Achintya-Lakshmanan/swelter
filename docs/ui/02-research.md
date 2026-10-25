# 02 · Research: real-time simulator and live-map UIs

Captured Oct 25 2026 at 1440×900 and 390×844 with Python Playwright + Chrome (`docs/ui/img/research/`).
**Not captured:** Flightradar24 and MarineTraffic served Cloudflare bot challenges, and NOAA HeatRisk returned
403 to the scripted browser. Bot checks weren't bypassed; principles from those sites are left out rather than
quoted from memory.

Sites captured: Windy, Ventusky, earth.nullschool, Zoom Earth, Watch Duty, deck.gl (showcase + trips example),
kepler.gl (NYC trips demo), NWS radar, weather.gov hazards, Nextstrain, NASA FIRMS, AirNow Fire & Smoke.

---

## The principles, ranked by how much they would change Swelter

### 1. The map is the page; chrome floats at the edges
**Evidence:** Windy ([desktop](img/research/windy-desktop.png)), Ventusky
([desktop](img/research/ventusky-desktop.png)) and nullschool ([desktop](img/research/nullschool-desktop.png))
run the map edge to edge, with every control as a small object pinned to a corner. nullschool goes furthest: one
"earth ≡" button bottom-left and nothing else. Watch Duty and Nextstrain spend a fixed sidebar on the list, which
works for lists but makes the map a panel.
**For Swelter:** drop the two-row header and the bordered right column. The map runs full-bleed under a thin top
bar. The scenario controls become one compact cluster top-left, the compare readout is a floating card on the
right, and the timebar is a floating strip at the bottom. Target: map ≥ 80% of the 1440×900 screen (today 45%).

### 2. One timeline, bottom-centre, with the current time as a labelled flag
**Evidence:** All four weather sites put time at the bottom edge: Windy's day strip with an orange "8 AM" flag
riding the playhead, Ventusky's hour scale with a white "9 AM" bubble on the knob plus big Play / Previous / Next
buttons, Zoom Earth's compact "▶ 25 Oct 9:07 AM" pod with steppers, and NWS radar's frame counter "20 / 20" with
transport buttons ([radar](img/research/nws-radar-desktop.png)). In each, the time readout lives *on* the
playhead, so the eye never leaves the track.
**For Swelter:** keep the intensity spark (it's better than any of them, since it shows *why* the hour matters)
but put the clock on a flag that rides the playhead ("2:30 PM · 104°F") instead of in a fixed box at the left.
Add one-tap jumps to the peak hour ("Peak 3 PM") and ±1 h steppers. Ventusky shows that big, labelled transport
buttons are what first-timers find.

### 3. Legend = the colour ramp itself, with the unit, docked by the timeline
**Evidence:** Windy docks a continuous "kt 0 5 10 20 30 40 60" bar right under the timeline. Ventusky stacks a
vertical °F ramp at the right edge with the unit on top. Zoom Earth puts a compact "°F −20…120" ramp bottom-left.
NWS radar's dBZ ramp sits directly under its transport controls. None uses dot-and-label legends for continuous
fields; dots are kept for categories (Watch Duty's fire icons, behind a "Legend" button).
**For Swelter:** two legends, each where it's read:
(a) a continuous ramp for the hazard field (heat index °F / wind chill °F) attached to the timebar, with today's
value marked on it;
(b) a two-swatch category key for resident dots ("Elevated predicted risk · 123 now"), set as live counts, since
those counts are the story.

### 4. Colour lives on the data; chrome is grey
**Evidence:** kepler.gl ([desktop](img/research/kepler-desktop.png)) and the deck.gl trips example
([desktop](img/research/deckgl-trips-desktop.png)): a near-black basemap with roads at ~10% grey, and all the
saturation goes into the data (electric blue taxis, orange/teal trips). The panels are flat dark grey with no
accent except one green "Add" button. The weather sites fail here in a useful way: Windy's purple field + red
menu + orange premium button + rainbow icons compete with the data.
**For Swelter:** basemap dimmer than today (roads to ~6% alpha), lower-risk residents a quiet cool grey, elevated
risk the one hot colour (heat: amber→red, cold: ice→white-blue), sites a distinct white ring with a number. UI
accent only on the primary action. No teal on data.

### 5. Motion is the data moving, never the interface
**Evidence:** nullschool's whole identity is thousands of short wind streaks advected across the globe, with no
UI animation at all. Windy and Ventusky add a particles toggle ("particles animation", "Wind Animation: Normal")
over the colour field. deck.gl's trips layer conveys "live" with fading trails behind moving vehicles.
**For Swelter:** we already move 1,560 residents along real diary trips. Make that legible: a short fading trail
behind travelling residents (TripsLayer-style, last ~10 clock-minutes), a soft pulse on dots the instant they
cross into elevated risk, and no entrance animations on panels. Under `prefers-reduced-motion`: start paused,
no trails, no pulse.

### 6. Onboard with state, not a modal
**Evidence (counter-examples):** AirNow ([desktop](img/research/airnow-desktop.png)) and FIRMS
([desktop](img/research/firms-desktop.png)) open with a modal over a greyed map. FIRMS stacks two. Windy and Zoom
Earth open straight onto the live field with the current value large (Windy's "30°"), so the page explains
itself. Nextstrain ([desktop](img/research/nextstrain-desktop.png)) uses its first line as a sentence title
("Genomic epidemiology of SARS-CoV-2 with subsampling focused globally over the past 6 months"), so the
dataset is described in words before you read the chart.
**For Swelter:** no splash modal. The first frame is the dangerous hour, already moving, with a sentence title
over the map ("Jul 20 2019 · the 12th-hottest day since 2010 · 1,560 residents of North & Center City") and the
finding underneath. A dismissible one-line hint ("Click any dot to see their day") instead of a tour.

### 7. Tell the limitation once, plainly, where the decision is made
**Evidence:** FIRMS's first words are "Do not use for the preservation of life or property", with accuracy
limits listed. It's heavy-handed as a modal, but honest. Nextstrain puts its data caveat (GISAID updates on hold)
in a full-width notice right under the title, in plain language with a link.
**For Swelter:** keep every disclosure, but place each one where it applies rather than hiding it in Methods:
"Reachable risk is not prevented exposure" sits *on* the coverage figure, the cold-day model failure is a notice
under the title when that day is selected (it already appears in the panel; make it read as part of the result),
and data credits stay in the footer of every page.

### 8. Numbers: large, tabular, unit smaller and grey
**Evidence:** Windy's "30°" next to a small unit and 4-day mini-forecast. The deck.gl trips panel sets "10.0K /
3.9K / 897.2K" big with small labels above. Watch Duty's list puts "Acres: **1,099** Containment: –": the label
quiet, the figure bold. None uses monospace; all use proportional faces with tabular figures.
**For Swelter:** drop JetBrains Mono. One face with `font-variant-numeric: tabular-nums`. Three numeric sizes:
the finding figure (40–56px), the clock (24px), table figures (13–14px). Units as a smaller grey suffix ("10.8
h"), and thousands separators always.

### 9. The inspector is a sheet with a header that identifies, then the data
**Evidence:** Watch Duty's incident rows (name → address → two key figures → status line), kepler's dataset card
(name + "97,986 rows"), and Watch Duty mobile's bottom sheet with a grab handle
([mobile](img/research/watchduty-mobile.png)).
**For Swelter:** the resident inspector becomes a right-docked sheet on desktop and a bottom sheet on the phone.
Order: name, age, role, tract → the 17-hour risk strip (large) → "Why did Priya do this?" live explanation button →
hour list → data trace (collapsed, "Where this resident comes from"). Nothing scrolls before the strip.

### 10. Mobile: map full-height, everything else in one bottom sheet
**Evidence:** Windy mobile ([mobile](img/research/windy-mobile.png)): map, a right-edge icon column, and a
timeline + legend glued to the bottom. Watch Duty mobile: map with a search bottom sheet. Neither stacks controls
above the map.
**For Swelter:** on a phone the map takes the screen, the scenario is one row of three compact selects, and the
timebar + compare live in a bottom sheet with two snap points (peek: clock + finding; open: groups + sites).

---

## Per-dimension summary

| Dimension | Best evidence | Swelter move |
|---|---|---|
| Time scrubber & playback | Ventusky's labelled knob + big transport; Windy's flag on the playhead | Clock flag on the playhead, spark kept, Peak and ±1 h jumps |
| Legends & colour scales | Windy/NWS ramp docked to the timeline; Ventusky vertical °F ramp | Continuous hazard ramp on the timebar; live-count category key |
| HUD density over full-bleed map | nullschool (one button) ↔ Windy (busy) | Three floating objects only: scenario, readout, timebar |
| Dark basemap treatment | kepler, deck.gl trips | Dimmer roads, data saturated, chrome neutral |
| Motion that says "live" | nullschool streaks, deck.gl trails | Fading trip trails, risk-crossing pulse; reduced-motion = paused |
| Inspector / detail panel | Watch Duty rows and sheet | Identity → risk strip → why → hours → trace |
| Typography of numbers | Windy "30°", deck.gl stat block | One face, tabular figures, unit as grey suffix |
| First-time onboarding | Windy/Zoom Earth (state = explanation), Nextstrain sentence title; AirNow/FIRMS modals (don't) | Open on the peak hour, sentence title, one-line hint |

---

## Reference design languages (awesome-design-md)

Reviewed `spacex.md`, `x.ai.md`, `linear.app.md`, `vercel.md`, `nvidia.md`, `runwayml.md`.

### Pick 1 · **Runway** (`runwayml.md`) for the landing page
Runway's site is "a cinematic reel": full-bleed footage *is* the UI, there's a single typeface throughout,
zero shadows, no gradients in the interface ("the only colour comes from photography"), cool slate neutrals
(`#767d88`), small 4–8px radii, and display type at weight 400–600 with tight leading. That's the right posture for
a landing page whose hero is our own replay (`heat-day-wide.mp4` or a live map loop): serious, cinematic, and the
colour comes from the simulation, not the chrome.
**Adapted:** its uppercase tracked labels are dropped (taste-skill house rule). abcNormal is replaced by a Google
face (Phase 3 chooses it). Its light editorial sections become dark tone steps, so the landing page and
simulator share one ground.

### Pick 2 · **Linear** (`linear.app.md`) for the simulator
Linear is the closest match for a dark working surface: a near-black canvas (`#010102`) with a **four-step surface
ladder** carrying hierarchy without shadows, ink `#f7f8f8` / muted `#d0d6e0` / subtle `#8a8f98`, aggressive
negative tracking on display, a 4px spacing base, and "product UI dominates". Its surface ladder maps directly to
map → floating cards → hover → selected.
**Adapted:** Linear's lavender accent is dropped (violet is a banned tell and would fight the heat palette). The
accent role goes to the hazard: amber for heat, ice-blue for cold, used on data and the one primary action only.
Its 12px card radius drops to 6–8px to sit with Runway.

### Why not the others
- **SpaceX:** right mood (black, cinematic, mission-serious), but its system is uppercase D-DIN with eyebrow
  microtext and ghost pill buttons, three banned tells at once. We borrow the mood through Runway instead.
- **x.ai:** strong near-black restraint, but its signature is a monospace uppercase caption face and violet/sunset
  gradient accents, both banned.
- **Vercel:** a light canvas with a mesh gradient; wrong ground for a night map.
- **NVIDIA:** alternates black and paper-white chapters with a saturated green on every CTA; too loud and
  corporate, and green would read as "safe" on a risk map.
