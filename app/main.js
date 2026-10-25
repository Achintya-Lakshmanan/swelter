/* Swelter front end: replays precomputed runs on a deck.gl map. Only /api/why is live. */
(() => {
  const HAZARD_COLOR = { heat: "#f2994a", cold: "#7fc8ff" };
  const LEVEL_RGB = [[47, 143, 122], [242, 201, 76], [242, 153, 74], [235, 77, 91]];
  const LEVEL_NAME = ["Lower predicted risk", "", "Elevated predicted risk", ""];
  const ACT = {
    sleep: ["Sleep", "z"], home: ["Home", "⌂"], commute: ["Travel", "→"], work_indoor: ["Work", "W"],
    work_outdoor: ["Work outside", "⚒"], class: ["Class", "C"], errand: ["Errand", "$"],
    leisure_indoor: ["Out (indoors)", "◆"], leisure_outdoor: ["Outside", "☀"], exercise_outdoor: ["Exercise", "↗"],
    public_indoor: ["Library / rec", "L"], refuge: ["Refuge", "✚"], outdoors_unsheltered: ["Unsheltered", "!"],
  };
  const ROLE = {
    office: "office worker", service: "retail / food worker", healthcare: "healthcare worker",
    outdoor: "outdoor worker", student: "student", retired: "retired", not_employed: "not employed", unhoused: "unhoused",
  };
  const $ = (s) => document.querySelector(s);
  const fmtHour = (t) => {
    const h = Math.floor(t), m = Math.floor((t - h) * 60);
    const hh = ((h + 11) % 12) + 1;
    return `${hh}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
  };

  const state = {
    hazard: "heat", level: "severe", iv: "none",
    // speed is clock hours per real second: 1× = 15 min/s, so a 20-minute trip takes 1.3 s on screen
    t: 6, playing: true, speed: 0.25, selected: null, group: null, siteBudget: 3,
  };
  let modelData, updateVersion = 0;
  let M, roads = [], water = [], deckOverlay, map, run, baseRun, frame = 0, lastTs = 0;
  const runCache = new Map();
  const jitter = [];

  const sid = (iv = state.iv) => `${state.hazard}_${state.level}_${iv}`;

  async function loadRun(id) {
    if (!runCache.has(id)) runCache.set(id, fetch(`data/runs/${id}.json?v=20k`).then((r) => r.json()).then(decode));
    return runCache.get(id);
  }
  function decode(r) {
    const n = r.steps.length, H = M.hours.length;
    r.place = new Uint16Array(n * H); r.act = new Uint8Array(n * H); r.why = new Uint8Array(n * H);
    r.lvl = new Uint8Array(n * H);
    for (let i = 0; i < n; i++) for (let h = 0; h < H; h++) {
      const s = r.steps[i][h], k = i * H + h;
      r.place[k] = Math.floor(s / 1000); r.act[k] = Math.floor((s % 1000) / 40); r.why[k] = s % 40;
      r.lvl[k] = modelData.models[r.hazard].rankings[r.level].risk_milli[i][h] >= 500 ? 2 : 0;
    }
    // trips: [depart, arrive, fromPlace, toPlace] in clock hours. Departures are the diary respondent's real minute
    // (or early in the hour for moves the hazard rules added); travel time follows the planner's walk/car/transit speeds.
    r.trips = [];
    for (let i = 0; i < n; i++) {
      const trips = [];
      let free = M.hours[0];
      for (let h = 1; h < H; h++) {
        const k = i * H + h;
        if (r.place[k] === r.place[k - 1]) continue;
        const dep = Math.max(free, r.dep && r.dep[i][h] >= 0 ? M.hours[0] + r.dep[i][h] / 60 : M.hours[0] + h);
        const arr = dep + travelMinutes(M.residents[i], M.places[r.place[k - 1]], M.places[r.place[k]]) / 60;
        trips.push([dep, arr, r.place[k - 1], r.place[k]]);
        free = arr;
      }
      r.trips.push(trips);
    }
    return r;
  }
  // same speeds as plan.travel(): walk under 1.2 km, otherwise car or SEPTA
  function travelMinutes(res, a, b) {
    const km = Math.hypot((a[3] - b[3]) * 111.32, (a[4] - b[4]) * 85.3);
    const older = res.age === "65-74" || res.age === "75+";
    if (km < 1.2) return Math.max(3, (60 * km) / (older ? 3.2 : 4.5));
    return Math.min(90, res.car ? (60 * km) / 25 + 4 : (60 * km) / 13 + 8);
  }

  // ---------- controls ----------
  function seg(el, items, current, onPick) {
    el.innerHTML = "";
    for (const [key, label] of items) {
      const b = document.createElement("button");
      b.textContent = label; b.className = key === current ? "on" : "";
      b.setAttribute("aria-pressed", key === current);
      b.onclick = () => onPick(key);
      el.appendChild(b);
    }
  }
  function renderControls() {
    const hz = M.hazards[state.hazard];
    document.documentElement.style.setProperty("--hz", HAZARD_COLOR[state.hazard]);
    seg($("#hazard-seg"), Object.entries(M.hazards).map(([k, v]) => [k, v.label]), state.hazard, (k) => {
      state.hazard = k; state.group = null; if (!M.hazards[k].interventions[state.iv]) state.iv = "none"; update();
    });
    seg($("#level-seg"), Object.entries(hz.levels).map(([k, v]) => [k, v.label.split(" — ")[0]]), state.level, (k) => { state.level = k; update(); });
    [...$("#level-seg").children].forEach((b, i) => { const v = Object.values(hz.levels)[i]; b.title = `${v.label.split(" — ")[1]} · ${v.note}`; });
    seg($("#iv-seg"), Object.entries(hz.interventions).map(([k, v]) => [k, v.label]), state.iv, (k) => { state.iv = k; update(); });
  }

  function planningSummary() {
    const result = modelData.models[state.hazard].rankings[state.level];
    const count = Math.min(state.siteBudget, result.sites.length);
    const masks = state.iv === "refuge" ? result.coverage_masks[String(count)] : null;
    const H = M.hours.length, n = M.residents.length;
    const groups = Object.fromEntries(M.hazards[state.hazard].groups.map(g => [g, { n: 0, risk: 0, covered: 0 }]));
    let risk = 0, covered = 0, reachablePeople = 0;
    const hourly = M.hours.map(hour => ({hour, risk:0, covered:0}));
    const people = M.residents.map((r,i) => {
      let total = 0, reachable = 0, atRiskReachable = false;
      for(let h=0;h<H;h++) {
        const p = result.risk_milli[i][h] / 1000, c = masks?.[i]?.[h] === "1" ? p : 0;
        total += p; reachable += c; hourly[h].risk += p; hourly[h].covered += c;
        if (c > 0 && p >= .5) atRiskReachable = true;
      }
      risk += total; covered += reachable; if(atRiskReachable) reachablePeople++;
      for(const g of r.groups) if(groups[g]) { groups[g].n++; groups[g].risk += total; groups[g].covered += reachable; }
      return {risk:total, covered:reachable, masks:masks?.[i] || "0".repeat(H)};
    });
    return {result, groups, people, hourly, risk, covered, reachablePeople, n};
  }

  async function update() {
    const version = ++updateVersion;
    renderControls();
    // The only stored replay loaded is the standard-city routine, never an old response run.
    const r = await loadRun(sid("none"));
    if (version !== updateVersion) return;
    run = r; baseRun = r;
    renderBadge(); renderSpark(); renderCompare();
    document.dispatchEvent(new CustomEvent("swelter:scenario", { detail: { hazard: state.hazard, level: state.level, iv: state.iv } }));
    if (state.selected !== null) renderInspector();
    redraw();
  }

  function renderBadge() {
    const hz = M.hazards[state.hazard], iv = hz.interventions[state.iv], lv = hz.levels[state.level];
    $("#iv-badge").innerHTML = `<b>${hz.label} · ${lv.label} · ${iv.label}</b>` +
      `<span class="muted">Real hourly record for ${lv.label.split(" — ")[1]}: ${lv.note}. ` +
      `${iv.desc || "Standard city: baseline routines with no model-selected sites opened."}</span>`;
    $("#history-eyebrow").textContent = `${hz.label} · compare`;
  }

  // ---------- spark line (hazard intensity over the day) ----------
  function renderSpark() {
    const svg = $("#spark"), w = 1000, h = 30, I = run.intensity;
    const lo = Math.min(...I), hi = Math.max(...I), span = hi - lo || 1;
    const cold = state.hazard === "cold";
    // Hour i starts at 6+i on the same 6 AM–11 PM scale as the slider and the playhead; the last hour runs to the end.
    const pts = I.map((v, i) => [(i / 16.99) * w, h - 3 - ((cold ? hi - v : v - lo) / span) * (h - 6)]);
    pts.push([w, pts[pts.length - 1][1]]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.innerHTML = `<path d="${d} L ${w} ${h} L 0 ${h} Z" fill="${HAZARD_COLOR[state.hazard]}" opacity=".18"/>` +
      `<path d="${d}" fill="none" stroke="${HAZARD_COLOR[state.hazard]}" stroke-width="2" vector-effect="non-scaling-stroke"/>` +
      `<line id="spark-now" y1="0" y2="${h}" stroke="#fff" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
  }
  // short hazard reading under the clock
  const READOUT = {
    heat: (v) => `${Math.round(v)}°F heat index`,
    cold: (v) => `${Math.round(v)}°F wind chill`.replace("-", "−"),
  };
  function intensityAt(t) {
    const I = run.intensity, x = Math.min(Math.max(t - 6, 0), I.length - 1), i = Math.floor(x), f = x - i;
    return I[i] + (I[Math.min(i + 1, I.length - 1)] - I[i]) * f;
  }

  // ---------- compare panel ----------
  function renderCompare() {
    const s = planningSummary(), isOpen = state.iv === "refuge";
    $("#compare-title").textContent = "Predicted risk and site access";
    $("#compare-sub").textContent = isOpen ? "ML-selected sites · coverage compared with Standard city" : "Standard city · ML-predicted baseline exposure";
    const model = modelData.models[state.hazard];
    const note = $("#compare-note");
    note.hidden = !model.weaker_unseen_days?.includes(state.level);
    note.textContent = "Limited generalization: this unseen weather-day test did not beat constant-risk predictions. Explore this stored scenario only.";
    const maximum = Math.max(.5,...Object.values(s.groups).map(g=>g.risk / (g.n || 1)));
    $("#compare-bars").innerHTML = Object.entries(s.groups).map(([g,v]) => {
      const total = v.risk/(v.n||1), outside = (v.risk-v.covered)/(v.n||1);
      return '<div class="bar-row '+(state.group===g?'on':'')+'" role="button" tabindex="0" aria-pressed="'+(state.group===g)+'" data-g="'+g+'"><div class="bar-label"><span>'+M.groups[g]+' <span class="muted">· '+v.n+'</span></span></div><div class="bar-track"><div class="bar-fill base" style="width:'+total/maximum*100+'%"></div></div>'+(isOpen?'<div class="bar-track"><div class="bar-fill iv" style="width:'+outside/maximum*100+'%"></div></div>':'')+'<div class="bar-nums"><span>baseline '+total.toFixed(1)+' h/person</span><span>'+(isOpen?outside.toFixed(1)+' outside coverage':'')+'</span></div></div>';
    }).join("");
    document.querySelectorAll(".bar-row").forEach(el=>{
      el.onclick=()=>{state.group=state.group===el.dataset.g?null:el.dataset.g;renderCompare();redraw();};
      el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click();}};
    });
  }

  // ---------- map ----------
  const WANDER = { leisure_outdoor: 0.00035, exercise_outdoor: 0.0012, outdoors_unsheltered: 0.00025, work_outdoor: 0.0003 };
  function residentPos(i, t) {
    const H = M.hours.length, j = jitter[i];
    let at = M.places[run.place[i * H]];
    for (const [t0, t1, a, b] of run.trips[i]) {
      if (t < t0) break;
      if (t < t1) {  // on the way
        let s = (t - t0) / (t1 - t0); s = s * s * (3 - 2 * s);
        const p = M.places[a], q = M.places[b];
        return [p[4] + (q[4] - p[4]) * s + j[0], p[3] + (q[3] - p[3]) * s + j[1]];
      }
      at = M.places[b];
    }
    // people outdoors don't stand still: a slow loop around where they are (bigger for exercise)
    const h = Math.min(Math.max(Math.floor(t - 6), 0), H - 1), w = WANDER[M.activities[run.act[i * H + h]]] || 0;
    const ph = t * 9 + i * 2.39;
    return [at[4] + j[0] + w * Math.cos(ph) * 1.3, at[3] + j[1] + w * Math.sin(ph * 1.13)];
  }
  const levelAt = (i, t) => run.lvl[i * M.hours.length + Math.min(Math.floor(t - 6), M.hours.length - 1)];

  function overlayColor(cell, I) {
    const [, , uhi, flood, wind] = cell;
    switch (state.hazard) {
      case "heat": {
        // overall heat sets the strength; the city's Heat Exposure Index offset (-4..+4 °F) shows where it's worst
        const a = Math.max(0, Math.min(1, (I - 84) / 26)), u = (uhi + 4) / 8;
        return [240, 140 - 100 * u, 60 - 40 * u, a * (10 + 120 * u * u)];
      }
      case "cold": { const v = I - wind, a = Math.max(0, Math.min(1, (32 - v) / 50)); return [120, 190, 255, 8 + 55 * a + (wind ? 35 : 0)]; }
    }
  }

  function layers() {
    const t = state.t, I = intensityAt(t), n = M.residents.length;
    const sel = state.selected, grp = state.group;
    const sites = []; // Standard city opens none; only the ML priority layer shows open sites.
    const prioritySites = window.swelterShelters?.sites || [];
    return [
      new deck.SolidPolygonLayer({
        id: "overlay", data: M.grid.cells, getPolygon: (c) => c.poly,
        getFillColor: (c) => overlayColor(c, I), updateTriggers: { getFillColor: [state.hazard, Math.round(I * 4)] },
      }),
      new deck.PathLayer({
        id: "water", data: water, getPath: (d) => d.p, getColor: [70, 140, 230, 150],
        getWidth: (d) => (d.c === "river" ? 40 : 12), widthMinPixels: 1,
      }),
      new deck.PathLayer({
        id: "roads", data: roads, getPath: (d) => d.p, getColor: [180, 190, 210, 40],
        getWidth: (d) => (d.c === "primary" || d.c === "trunk" ? 14 : 7), widthMinPixels: 0.6,
      }),
      new deck.ScatterplotLayer({
        id: "sites", data: window.swelterShelters?.active ? [] : sites, getPosition: (d) => d.pos, stroked: true, filled: true,
        radiusMinPixels: 4, lineWidthMinPixels: 1.5,
        getFillColor: (d) => (d.on ? [90, 209, 230, 60] : [255, 255, 255, 10]),
        getLineColor: (d) => (d.on ? [90, 209, 230, 255] : [139, 149, 167, 150]),
        getRadius: (d) => (d.on ? 120 + 25 * Math.sqrt(d.count) : 90),
        updateTriggers: { getRadius: frame, getFillColor: state.hazard + state.iv, getLineColor: state.hazard + state.iv },
      }),
      new deck.TextLayer({
        id: "site-labels", data: window.swelterShelters?.active ? [] : sites.filter((s) => s.count > 0), getPosition: (d) => d.pos,
        getText: (d) => `${d.label} · ${d.count}`, getSize: 12,
        getColor: [210, 245, 252, 255], getPixelOffset: [0, -18],
        fontFamily: "Inter, sans-serif", fontWeight: 600, outlineWidth: 3, outlineColor: [11, 14, 19, 230],
        fontSettings: { sdf: true }, updateTriggers: { getText: frame },
      }),
      new deck.ScatterplotLayer({
        id: "residents", data: { length: n }, pickable: true,
        getPosition: (_, { index }) => residentPos(index, t),
        getRadius: (_, { index }) => (index === sel ? 70 : 32), radiusMinPixels: 2.8, radiusMaxPixels: 10,
        getFillColor: (_, { index }) => {
          const l = levelAt(index, t), c = LEVEL_RGB[l];
          const dim = grp && !M.residents[index].groups.includes(grp);
          const a = dim ? 25 : l === 0 ? 150 : 235;
          return [c[0], c[1], c[2], a];
        },
        stroked: true, lineWidthMinPixels: 1,
        getLineColor: (_, { index }) => (index === sel ? [255, 255, 255, 255] : [0, 0, 0, 0]),
        updateTriggers: { getPosition: frame, getFillColor: [frame, grp], getRadius: sel, getLineColor: sel },
        onClick: (info) => { state.selected = info.index; renderInspector(); redraw(); },
        onHover: (info) => showTip(info),
      }),
      new deck.ScatterplotLayer({
        id: "shelter-priorities", data: prioritySites, pickable: true,
        getPosition: (s) => [s.lon, s.lat], getRadius: 140, radiusMinPixels: 13, radiusMaxPixels: 24,
        stroked: true, lineWidthMinPixels: 2,
        getFillColor: (s) => s.id === window.swelterShelters?.selected ? [240, 241, 241, 255] : [139, 207, 195, 255],
        getLineColor: [16, 19, 20, 255], updateTriggers: { getFillColor: window.swelterShelters?.selected },
        onClick: ({ object }) => { if (object) window.swelterShelters.select(object.id); },
      }),
      new deck.TextLayer({
        id: "shelter-priority-ranks", data: prioritySites,
        getPosition: (s) => [s.lon, s.lat], getText: (s) => String(s.rank),
        getColor: [16, 19, 20, 255], getSize: 13, fontWeight: 700,
        fontFamily: "Inter, sans-serif",
      }),
    ];
  }
  function redraw() {
    if (!deckOverlay || !run) return;
    frame++;
    deckOverlay.setProps({ layers: layers() });
    updateHud();
  }

  function showTip(info) {
    const tip = $("#tooltip");
    if (info.index < 0 || info.index == null) { tip.hidden = true; return; }
    const i = info.index, r = M.residents[i], k = i * M.hours.length + Math.min(Math.floor(state.t - 6), 16);
    const p = M.places[run.place[k]], l = run.lvl[k];
    tip.hidden = false;
    tip.style.left = info.x + 12 + "px"; tip.style.top = info.y + 12 + "px";
    tip.innerHTML = `<b>${r.name}</b>, ${r.age} · ${ROLE[r.role]}<br>${ACT[M.activities[run.act[k]]][0]} · ${p[2] || p[1]}<br>` +
      `<span style="color:rgb(${LEVEL_RGB[l]})">● ${LEVEL_NAME[l]}</span>`;
  }

  function updateHud() {
    $("#clock").textContent = fmtHour(state.t);
    $("#time").value = state.t;
    const x = ((state.t - 6) / 16.99) * 1000;
    const now = document.getElementById("spark-now");
    if (now) { now.setAttribute("x1", x); now.setAttribute("x2", x); }
    $("#readout").textContent = READOUT[state.hazard](intensityAt(state.t));
    const h = Math.min(Math.floor(state.t - 6), 16), counts = [0,0,0,0];
    for(let i=0;i<M.residents.length;i++) counts[run.lvl[i*M.hours.length+h]]++;
    $("#legend").innerHTML = counts.map((c, l) => LEVEL_NAME[l] ? `<span><i style="background:rgb(${LEVEL_RGB[l]})"></i>${LEVEL_NAME[l]} <b>${c}</b></span>` : "").join("");
    if (state.selected !== null) {
      document.querySelectorAll(".timeline .cell").forEach((el) => el.classList.toggle("now", +el.dataset.h === h));
    }
  }

  // ---------- inspector ----------
  function dayRows(r, i) {
    const H = M.hours.length, reasons = Object.keys(M.reasons);
    return M.hours.map((hour, h) => {
      const k = i * H + h, p = M.places[r.place[k]];
      return { hour, act: M.activities[r.act[k]], why: M.reasons[reasons[r.why[k]]], place: p[2] || p[1], kind: p[1], lvl: r.lvl[k] };
    });
  }
  function timeline(rows) {
    return `<div class="timeline">${rows.map((d, h) => {
      const c = LEVEL_RGB[d.lvl];
      return `<div class="cell" data-h="${h}" title="${d.hour}:00 · ${ACT[d.act][0]} · ${d.place} — ${d.why}"
        style="background:rgba(${c},${d.lvl ? 0.9 : 0.35});color:${d.lvl ? "#0b0e13" : "#e8ecf2"}">${ACT[d.act][1]}</div>`;
    }).join("")}</div>`;
  }
  function renderInspector() {
    const i = state.selected, r = M.residents[i], el = $("#inspector");
    el.hidden = false;
    const rows = dayRows(run, i), base = dayRows(baseRun, i);
    const personal = planningSummary().people[i];
    const flags = run.flags[i];
    const groups = r.groups.filter((g) => M.hazards[state.hazard].groups.includes(g) || g === "driver" || g === "no_car");
    const traits = r.role === "unhoused" ? [r.respiratory ? "asthma/COPD" : null].filter(Boolean) : [
      r.car ? "has a car" : "no car", r.ac ? "has AC" : "no AC", r.alone ? "lives alone" : null,
      r.respiratory ? "asthma/COPD" : null, r.flood_zone ? "flood-prone block" : null, !r.heat ? "no reliable heat" : null,
      r.poverty ? "low income" : null,
    ].filter(Boolean);
    const hue = ["#f2994a", "#5ad1e6", "#a78bfa", "#5fd3a5", "#f2c94c"][i % 5];
    const nowH = Math.min(Math.floor(state.t - 6), 16);
    $("#insp-body").innerHTML = `
      <div class="persona-head">
        <div class="avatar" style="background:${hue}">${r.name[0]}</div>
        <div><div class="persona-name">${r.name}, ${r.age}</div>
        <div class="persona-sub">${ROLE[r.role]} · ${r.tract_name}</div></div>
      </div>
      <div class="chips">${groups.map((g) => `<span class="chip hot">${M.groups[g]}</span>`).join("")}
        ${traits.map((t) => `<span class="chip">${t}</span>`).join("")}
        <span class="chip">${flags & 1 ? "heard the warning" : "missed the warning"}</span></div>
      <div class="trace">Traces to <b>${r.source}</b><ul>${Object.entries(r.trace)
        .filter(([k]) => k !== (state.hazard === "cold" ? "day_summer" : "day_winter")).map(([, t]) => `<li>${t}</li>`).join("")}</ul></div>
      <p class="hint">Baseline routine; opening sites does not assume this resident attends.</p>
      <div class="tl-label"><span>ML-predicted risk</span><span>${personal.risk.toFixed(1)} expected h · ${personal.covered.toFixed(1)} within reach</span></div>
      ${timeline(rows)}
      <div class="tl-hours">${M.hours.map((h) => `<span>${h % 3 === 0 ? ((h + 11) % 12) + 1 : ""}</span>`).join("")}</div>
      <div class="steps">${rows.map((d) => `<div class="step"><span class="h">${((d.hour + 11) % 12) + 1}${d.hour < 12 ? "a" : "p"}</span>
        <span><span style="color:rgb(${LEVEL_RGB[d.lvl]})">●</span> ${ACT[d.act][0]} · ${d.place}<div class="why">${d.why}</div></span></div>`).join("")}</div>
      `;
    document.querySelectorAll(".timeline .cell").forEach((c) => c.classList.toggle("now", +c.dataset.h === nowH));
  }

  // ---------- modals ----------
  function openModal(html) { $("#modal-body").innerHTML = html; $("#modal").showModal(); }
  function showValidation() {
    openModal('<h2>Trained-model evaluation</h2><p>Held-out diary groups; targets are simulated baseline danger, not observed health or shelter outcomes.</p><table><tr><th>Model</th><th>Daily MAE</th><th>Danger recall</th><th>Brier</th><th>Constant baseline</th></tr>'+Object.entries(modelData.models).map(([hz,m])=>'<tr><td>'+M.hazards[hz].label+'</td><td>'+m.metrics.daily_hours_mae+' h/person</td><td>'+Math.round(m.metrics.danger_recall*100)+'%</td><td>'+m.metrics.brier+'</td><td>'+m.metrics.constant_baseline_brier+'</td></tr>').join('')+'</table><p>The typical cold-day unseen-weather fold did not beat the constant-risk baseline. Geography is not independently held out. Only three historical days per hazard are available.</p>');
  }
  function showMethods() {
    openModal('<h2>Methods</h2><p>Two trained random forests predict baseline dangerous-exposure probability per resident-hour. The map shows baseline routines with ML risk labels; selected sites do not automatically change resident behavior.</p><p>Real inputs: NOAA weather, city cooling/warming facilities and posted hours, city heat maps. ACS, RECS, CDC PLACES and ATUS inform synthetic residents and routines. Unhoused schedules are assumed and oversampled.</p><p>Standard city opens no model-selected sites. Open sites selects the top 1, 3 or 5 facilities using trained-model probabilities and a greedy coverage objective. Old precomputed intervention outcomes are not loaded.</p><p>Priority weights: '+modelData.policy.weights+'. Distance discount: '+modelData.policy.proximity+'. Reach: '+modelData.policy.reach_m+'. Candidate facilities must be open in the relevant hour.</p><p>Risk-hours sum danger probabilities. Within-reach risk is access opportunity, not prevented exposure. Capacity, route safety, attendance and current facility conditions are unverified.</p>');
  }

  // ---------- loop ----------
  function tick(ts) {
    const dt = lastTs ? Math.min((ts - lastTs) / 1000, 0.1) : 0;
    lastTs = ts;
    if (state.playing && run) {
      state.t += dt * state.speed;
      if (state.t >= 22.99) state.t = 6;
      redraw();
    }
    requestAnimationFrame(tick);
  }

  async function init() {
    [M, modelData] = await Promise.all([fetch("data/meta.json?v=20k").then(r=>r.json()), fetch("data/shelter_models.json?v=20k").then(r=>{if(!r.ok) throw Error("Model results unavailable");return r.json();})]);
    M.hazards = Object.fromEntries(["heat", "cold"].map(hz=>[hz, {...M.hazards[hz], interventions: {
      none: {label:"Standard city", desc:"Baseline routines with no model-selected sites opened."},
      refuge: {label:hz==='heat'?"Open cooling sites":"Open warming sites", desc:"Trained-model risk predictions select sites; metrics measure potential access, not guaranteed exposure reduction."}
    }}]));
    M.placeIndex = Object.fromEntries(M.places.map((p, i) => [p[0], i]));
    const g = M.grid.step / 2;
    for (const c of M.grid.cells) c.poly = [[c[1] - g, c[0] - g], [c[1] + g, c[0] - g], [c[1] + g, c[0] + g], [c[1] - g, c[0] + g]];
    for (let i = 0; i < M.residents.length; i++) {
      const a = Math.sin(i * 12.9898) * 43758.5453, b = Math.sin(i * 78.233) * 12345.6789;
      jitter.push([((a - Math.floor(a)) - 0.5) * 0.0007, ((b - Math.floor(b)) - 0.5) * 0.0005]);
    }
    // deep links from the About page: ?hazard=smoke&level=extreme&iv=n95 (and &resident=, &hour= below)
    const q = new URLSearchParams(location.search);
    if (M.hazards[q.get("hazard")]) state.hazard = q.get("hazard");
    if (M.hazards[state.hazard].levels[q.get("level")]) state.level = q.get("level");
    if (M.hazards[state.hazard].interventions[q.get("iv")]) state.iv = q.get("iv");
    [roads, water] = await Promise.all([fetch("data/roads.json").then((r) => r.json()), fetch("data/waterways.json").then((r) => r.json())]);

    // Each label sits at its own time on the slider's 6 AM–11 PM scale (not spread evenly edge to edge).
    $("#ticks").innerHTML = [6, 9, 12, 15, 18, 21].map((h) => `<span style="left:${((h - 6) / 16.99) * 100}%">${fmtHour(h).replace(":00", "")}</span>`).join("");
    $("#time").oninput = (e) => { state.t = +e.target.value; redraw(); };
    $("#play").onclick = () => {
      state.playing = !state.playing;
      $("#play").classList.toggle("playing", state.playing);
      $("#play").setAttribute("aria-label", state.playing ? "Pause" : "Play");
    };
    $("#play").classList.add("playing");
    $("#speed").onchange = (e) => { state.speed = +e.target.value; };
    window.swelter = { state, select: (i) => { state.selected = i; renderInspector(); redraw(); },
      get run() { return run; }, get models() { return modelData; }, get meta() { return M; }, summary: planningSummary,
      setResponse: (iv)=>{if(iv==='none'||iv==='refuge'){state.iv=iv;update();}}, setBudget: (n)=>{if([1,3,5].includes(n)){state.siteBudget=n;update();}}, residentPos, refreshMap: redraw,
      focusSite: (lon, lat) => map.flyTo({ center: [lon, lat], zoom: 14.2, duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 600 }) };
    $("#insp-close").onclick = () => { state.selected = null; $("#inspector").hidden = true; redraw(); };
    $("#btn-methods").onclick = showMethods;
    $("#btn-validate").onclick = showValidation;
    $("#modal-close").onclick = () => $("#modal").close();
    document.addEventListener("keydown", (e) => {
      if (e.defaultPrevented || e.target.closest("button, select, a, [role=button], dialog") || (e.target.tagName === "INPUT" && e.target.type !== "range")) return;
      if (e.code === "Space") { e.preventDefault(); $("#play").click(); }
    });

    const fallbackStyle = { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b0e13" } }] };
    map = new maplibregl.Map({
      container: "map",
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      bounds: [[-75.215, 39.935], [-75.12, 40.03]], fitBoundsOptions: { padding: { top: 70, bottom: 90, left: 10, right: 10 } },
      attributionControl: { compact: true },
    });
    map.on("error", (e) => { if (!map.isStyleLoaded() && String(e.error?.message || "").match(/style|fetch/i)) map.setStyle(fallbackStyle); });
    deckOverlay = new deck.MapboxOverlay({ interleaved: false, layers: [], getCursor: ({ isHovering }) => (isHovering ? "pointer" : "grab") });
    map.addControl(deckOverlay);

    await update();
    // ?resident=1484 opens the inspector on one resident (the phone demo's Kayla) at the hour given by ?hour=
    const rid = parseInt(q.get("resident"), 10);
    if (rid >= 0 && rid < M.residents.length) {
      const h = parseInt(q.get("hour"), 10);
      if (h >= 6 && h <= 22) { state.t = h; $("#time").value = h; state.playing = false; $("#play").classList.remove("playing"); }
      window.swelter.select(rid);
    }
    requestAnimationFrame(tick);
  }
  // Government accounts only (auth.js).
  swelterAuth.ready.then(init).catch(e=>{ $("#compare-sub").textContent="Unable to load model data: "+e.message+". Reload to retry."; $("#compare-sub").setAttribute("role","alert"); });
})();
