/* Swelter front end: replays precomputed runs on a deck.gl map. Only /api/why is live. */
(() => {
  const HAZARD_COLOR = { heat: "#f2994a", smoke: "#9b8d7a", flood: "#4c8dff", cold: "#7fc8ff" };
  const LEVEL_RGB = [[47, 143, 122], [242, 201, 76], [242, 153, 74], [235, 77, 91]];
  const LEVEL_NAME = ["Safe", "Caution", "Danger", "Extreme"];
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
    t: 6, playing: true, speed: 0.25, selected: null, group: null,
  };
  let M, roads = [], water = [], deckOverlay, map, run, baseRun, frame = 0, lastTs = 0;
  const runCache = new Map();
  const jitter = [];

  const sid = (iv = state.iv) => `${state.hazard}_${state.level}_${iv}`;

  async function loadRun(id) {
    if (!runCache.has(id)) runCache.set(id, fetch(`data/runs/${id}.json`).then((r) => r.json()).then(decode));
    return runCache.get(id);
  }
  function decode(r) {
    const n = r.steps.length, H = M.hours.length;
    r.place = new Uint16Array(n * H); r.act = new Uint8Array(n * H); r.why = new Uint8Array(n * H);
    r.lvl = new Uint8Array(n * H);
    for (let i = 0; i < n; i++) for (let h = 0; h < H; h++) {
      const s = r.steps[i][h], k = i * H + h;
      r.place[k] = Math.floor(s / 1000); r.act[k] = Math.floor((s % 1000) / 40); r.why[k] = s % 40;
      r.lvl[k] = +r.levels[i][h];
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
      b.onclick = () => onPick(key);
      el.appendChild(b);
    }
  }
  function renderControls() {
    const hz = M.hazards[state.hazard];
    document.documentElement.style.setProperty("--hz", HAZARD_COLOR[state.hazard]);
    seg($("#hazard-seg"), Object.entries(M.hazards).map(([k, v]) => [k, v.label]), state.hazard, (k) => {
      state.hazard = k; if (!M.hazards[k].interventions[state.iv]) state.iv = "none"; update();
    });
    seg($("#level-seg"), Object.entries(hz.levels).map(([k, v]) => [k, v.label.split(" — ")[0]]), state.level, (k) => { state.level = k; update(); });
    [...$("#level-seg").children].forEach((b, i) => { const v = Object.values(hz.levels)[i]; b.title = `${v.label.split(" — ")[1]} · ${v.note}`; });
    seg($("#iv-seg"), Object.entries(hz.interventions).map(([k, v]) => [k, v.label]), state.iv, (k) => { state.iv = k; update(); });
  }

  async function update() {
    renderControls();
    const [r, b] = await Promise.all([loadRun(sid()), loadRun(sid("none"))]);
    run = r; baseRun = b;
    renderBadge(); renderSpark(); renderCompare(); renderMatrix(); renderProvenance();
    if (state.selected !== null) renderInspector();
    // warm the cache for the other interventions at this level
    Object.keys(M.hazards[state.hazard].interventions).forEach((iv) => loadRun(sid(iv)));
    redraw();
  }

  function renderBadge() {
    const hz = M.hazards[state.hazard], iv = hz.interventions[state.iv], lv = hz.levels[state.level];
    $("#iv-badge").innerHTML = `<b>${hz.label} · ${lv.label} · ${iv.label}</b>` +
      `<span class="muted">Real hourly record for ${lv.label.split(" — ")[1]}: ${lv.note}. ` +
      `${iv.desc || "Baseline: no city response beyond today's normal services."}</span>`;
    $("#history").textContent = hz.history;
    $("#history-eyebrow").textContent = `${hz.label} · compare`;
  }

  // ---------- spark line (hazard intensity over the day) ----------
  function renderSpark() {
    const svg = $("#spark"), w = 1000, h = 30, I = run.intensity;
    const lo = Math.min(...I), hi = Math.max(...I), span = hi - lo || 1;
    const cold = state.hazard === "cold";
    const pts = I.map((v, i) => [(i / (I.length - 1)) * w, h - 3 - ((cold ? hi - v : v - lo) / span) * (h - 6)]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.innerHTML = `<path d="${d} L ${w} ${h} L 0 ${h} Z" fill="${HAZARD_COLOR[state.hazard]}" opacity=".18"/>` +
      `<path d="${d}" fill="none" stroke="${HAZARD_COLOR[state.hazard]}" stroke-width="2" vector-effect="non-scaling-stroke"/>` +
      `<line id="spark-now" y1="0" y2="${h}" stroke="#fff" stroke-width="1" vector-effect="non-scaling-stroke"/>` +
      `<text id="spark-val" y="11" font-size="11" fill="#e8ecf2" font-family="JetBrains Mono"></text>`;
  }
  function intensityAt(t) {
    const I = run.intensity, x = Math.min(Math.max(t - 6, 0), I.length - 1), i = Math.floor(x), f = x - i;
    return I[i] + (I[Math.min(i + 1, I.length - 1)] - I[i]) * f;
  }

  // ---------- compare panel ----------
  function renderCompare() {
    const hz = M.hazards[state.hazard];
    const G = run.summary.groups, B = baseRun.summary.groups;
    const max = Math.max(...hz.groups.map((g) => Math.max(B[g]?.danger_hours || 0, G[g]?.danger_hours || 0)), 0.5);
    const isBase = state.iv === "none";
    $("#compare-sub").textContent = isBase
      ? "Doing nothing. Pick an intervention to compare."
      : `${hz.interventions[state.iv].label} vs. doing nothing`;
    $("#compare-bars").innerHTML = hz.groups.map((g) => {
      const b = B[g]?.danger_hours ?? 0, v = G[g]?.danger_hours ?? 0;
      const pct = b > 0 ? Math.round(((v - b) / b) * 100) : 0;
      const delta = isBase ? "" : `<span class="delta ${pct < 0 ? "good" : pct > 0 ? "bad" : ""}">${pct > 0 ? "+" : ""}${pct}%</span>`;
      return `<div class="bar-row ${state.group === g ? "on" : ""}" data-g="${g}">
        <div class="bar-label"><span>${M.groups[g]} <span class="muted">· ${G[g]?.n ?? 0}</span></span>${delta}</div>
        ${isBase ? "" : `<div class="bar-track"><div class="bar-fill base" style="width:${(b / max) * 100}%"></div></div>`}
        <div class="bar-track"><div class="bar-fill iv" style="width:${(v / max) * 100}%"></div></div>
        <div class="bar-nums"><span>${isBase ? "" : "nothing " + b.toFixed(1) + " h"}</span><span>${v.toFixed(1)} h${isBase ? "" : " with it"}</span></div>
      </div>`;
    }).join("");
    document.querySelectorAll(".bar-row").forEach((el) => el.onclick = () => {
      state.group = state.group === el.dataset.g ? null : el.dataset.g; renderCompare(); redraw();
    });
    const a = run.summary.all.all, ab = baseRun.summary.all.all;
    const pctAny = (x) => Math.round(x.share_any_danger * 100);
    $("#kpis").innerHTML = `
      <div class="kpi"><div class="v">${pctAny(a)}%</div><div class="l">residents with ≥1 dangerous hour${isBase ? "" : ` (was ${pctAny(ab)}%)`}</div></div>
      <div class="kpi"><div class="v">${a.danger_hours.toFixed(2)}</div><div class="l">dangerous hours per resident${isBase ? "" : ` (was ${ab.danger_hours.toFixed(2)})`}</div></div>`;
  }

  async function renderMatrix() {
    const hz = M.hazards[state.hazard], ivs = Object.keys(hz.interventions);
    const runs = await Promise.all(ivs.map((iv) => loadRun(sid(iv))));
    const head = ivs.map((iv) => `<th>${hz.interventions[iv].label.replace("Do nothing", "Nothing")}</th>`).join("");
    const rows = hz.groups.map((g) => {
      const vals = runs.map((r) => r.summary.groups[g]?.danger_hours ?? 0), best = Math.min(...vals);
      return `<tr><td>${M.groups[g]}</td>${vals.map((v, i) =>
        `<td class="${v === best && v < vals[0] ? "best" : ""} ${ivs[i] === state.iv ? "cur" : ""}">${v.toFixed(1)}</td>`).join("")}</tr>`;
    }).join("");
    $("#matrix").innerHTML = `<table><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table>
      <p class="hint">Refuges are the city's real designated sites at their posted hours. Green = best option for that group.</p>`;
  }

  function renderProvenance() {
    const v = run.verifier, pct = ((v.rejected / v.drafts) * 100).toFixed(1);
    const types = new Set(M.residents.map((r) => r.type)).size;
    $("#provenance").innerHTML = `
      <div><b>${M.residents.length.toLocaleString()}</b> synthetic residents · <b>${types}</b> persona types, from <b>ACS 2024</b>, <b>RECS 2020</b> and <b>CDC PLACES</b></div>
      <div>Each resident's weekday is a real <b>ATUS</b> diary; the hazard is the real hourly record for <b>${M.hazards[state.hazard].levels[state.level].label.split(" — ")[1]}</b></div>
      <div><b>${M.places.length.toLocaleString()}</b> real places (OpenStreetMap + ${M.refuges.length} city cooling / warming sites), FEMA 2023 flood zones</div>
      <div>Planner: <b>${run.planner === "rules" ? "rule-based (offline)" : "Claude + rules fallback"}</b> · choices limited to a fixed schema</div>
      <div>Plausibility verifier rejected <b>${v.rejected}</b> of ${v.drafts.toLocaleString()} drafted days (${pct}%) and regenerated them</div>
      <div>Exposure is computed deterministically: hazard × time outdoors × AC/heat/filtration where they are</div>`;
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
      case "smoke": { const a = Math.max(0, Math.min(1, (I - 50) / 350)); return [150, 130, 105, 12 + 85 * a + 8 * uhi]; }
      case "flood": return flood ? [60, 130, 255, flood * Math.min(150, 30 + 45 * I)] : [0, 0, 0, 0];
      case "cold": { const v = I - wind, a = Math.max(0, Math.min(1, (32 - v) / 50)); return [120, 190, 255, 8 + 55 * a + (wind ? 35 : 0)]; }
    }
  }

  function layers() {
    const t = state.t, I = intensityAt(t), n = M.residents.length;
    const sel = state.selected, grp = state.group;
    // the city's real cooling / warming network; "on" when this scenario opens it, labelled with who is there now
    const kind = state.hazard === "cold" ? "warming" : "cooling";
    const open = state.iv === "refuge" || (state.hazard === "heat" && state.iv === "transit") || state.iv === "outreach";
    const here = new Map(), H = M.hours.length, h = Math.min(Math.floor(t - 6), H - 1);
    for (let i = 0; i < n; i++) if (M.activities[run.act[i * H + h]] === "refuge") here.set(run.place[i * H + h], (here.get(run.place[i * H + h]) || 0) + 1);
    const sites = M.refuges.filter((s) => state.hazard === "flood" || s[kind]).map((s) => {
      const idx = M.placeIndex[s.id];
      return { label: s.name, pos: [s.lon, s.lat], on: open, count: here.get(idx) || 0 };
    });
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
        id: "sites", data: sites, getPosition: (d) => d.pos, stroked: true, filled: true,
        radiusMinPixels: 4, lineWidthMinPixels: 1.5,
        getFillColor: (d) => (d.on ? [90, 209, 230, 60] : [255, 255, 255, 10]),
        getLineColor: (d) => (d.on ? [90, 209, 230, 255] : [139, 149, 167, 150]),
        getRadius: (d) => (d.on ? 120 + 25 * Math.sqrt(d.count) : 90),
        updateTriggers: { getRadius: frame, getFillColor: state.hazard + state.iv, getLineColor: state.hazard + state.iv },
      }),
      new deck.TextLayer({
        id: "site-labels", data: sites.filter((s) => s.count > 0), getPosition: (d) => d.pos,
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
    const now = document.getElementById("spark-now"), val = document.getElementById("spark-val");
    if (now) { now.setAttribute("x1", x); now.setAttribute("x2", x); }
    if (val) {
      const I = intensityAt(state.t);
      val.setAttribute("x", Math.min(x + 6, 880));
      val.textContent = `${I.toFixed(state.hazard === "flood" ? 1 : 0)} ${M.hazards[state.hazard].unit}`;
    }
    const h = Math.min(Math.floor(state.t - 6), 16), counts = run.summary.hourly_levels[h];
    $("#legend").innerHTML = counts.map((c, l) => `<span><i style="background:rgb(${LEVEL_RGB[l]})"></i>${LEVEL_NAME[l]} <b>${c}</b></span>`).join("");
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
    const dh = rows.filter((d) => d.lvl >= 2).length, bdh = base.filter((d) => d.lvl >= 2).length;
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
      ${state.iv !== "none" ? `<div class="tl-label"><span>If the city did nothing</span><span>${bdh} dangerous h</span></div>${timeline(base)}` : ""}
      <div class="tl-label"><span>${state.iv === "none" ? "Their day" : "With " + M.hazards[state.hazard].interventions[state.iv].label}</span><span>${dh} dangerous h</span></div>
      ${timeline(rows)}
      <div class="tl-hours">${M.hours.map((h) => `<span>${h % 3 === 0 ? ((h + 11) % 12) + 1 : ""}</span>`).join("")}</div>
      <div class="steps">${rows.map((d) => `<div class="step"><span class="h">${((d.hour + 11) % 12) + 1}${d.hour < 12 ? "a" : "p"}</span>
        <span><span style="color:rgb(${LEVEL_RGB[d.lvl]})">●</span> ${ACT[d.act][0]} · ${d.place}<div class="why">${d.why}</div></span></div>`).join("")}</div>
      <div class="why-box">
        <button class="why-btn" id="why-btn">Why did ${r.name} do this?</button>
        <div id="why-out"></div>
      </div>`;
    document.querySelectorAll(".timeline .cell").forEach((c) => c.classList.toggle("now", +c.dataset.h === nowH));
    $("#why-btn").onclick = () => explain(i);
  }

  // The resident whose day changed most under this intervention (or the most exposed one at baseline).
  function featured() {
    const H = M.hours.length, n = M.residents.length, grp = state.group;
    const dh = (r, i) => { let c = 0; for (let h = 0; h < H; h++) if (r.lvl[i * H + h] >= 2) c++; return c; };
    let best = -1, score = -1, seen = (featured.seen ||= new Set());
    for (let i = 0; i < n; i++) {
      if (grp && !M.residents[i].groups.includes(grp)) continue;
      const sc = (state.iv === "none" ? dh(run, i) : dh(baseRun, i) - dh(run, i)) - (seen.has(i) ? 100 : 0);
      if (sc > score) { score = sc; best = i; }
    }
    if (best < 0) return;
    seen.add(best);
    state.selected = best;
    const k = best * H + Math.min(Math.floor(state.t - 6), H - 1), p = M.places[run.place[k]];
    map.flyTo({ center: [p[4], p[3]], zoom: 14.2, duration: 900 });
    renderInspector(); redraw();
  }

  async function explain(i) {
    const btn = $("#why-btn"), out = $("#why-out");
    btn.disabled = true; btn.textContent = "Asking…";
    try {
      const res = await fetch("api/why", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: sid(), resident: i }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || res.status);
      out.innerHTML = `<div class="why-text"></div><div class="why-src"><span>${j.source === "offline" ? "Offline explanation from the planner's reason codes" : "Live explanation · " + j.source}</span><button id="speak">▶ Listen</button></div>`;
      out.querySelector(".why-text").textContent = j.text;
      $("#speak").onclick = () => speak(j.text);
    } catch (e) {
      out.innerHTML = `<div class="why-text muted">Explainer unavailable (${e.message}). Is server.py running?</div>`;
    }
    btn.disabled = false; btn.textContent = `Why did ${M.residents[i].name} do this?`;
  }
  function speak(text) {
    if (!("speechSynthesis" in window)) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text); u.rate = 1.02;
    speechSynthesis.speak(u);
  }

  // ---------- modals ----------
  function openModal(html) { $("#modal-body").innerHTML = html; $("#modal").showModal(); }
  async function showValidation() {
    let v = null;
    try { v = await fetch("data/validation.json").then((r) => (r.ok ? r.json() : null)); } catch (e) { /* not built yet */ }
    if (!v) return openModal(`<h2>Validation</h2><p>Validation data not built yet. Run <code>python3 scripts/validate.py</code>.</p>`);
    openModal(renderValidation(v));
  }
  function renderValidation(v) {
    // Diverging bars around zero: real (gray) vs simulated (orange) hot-day change per category.
    const w = 760, h = 300, padL = 40, padR = 20, top = 34, bot = 40, rows = v.rows;
    const ext = Math.max(5, ...rows.flatMap((r) => [Math.abs(r.real), Math.abs(r.sim)])) * 1.15;
    const y = (x) => top + ((ext - x) / (2 * ext)) * (h - top - bot);
    const bw = (w - padL - padR) / rows.length;
    const bar = (x0, val, fill) => {
      const y0 = y(Math.max(val, 0)), hh = Math.max(1.5, Math.abs(y(val) - y(0)));
      return `<rect x="${x0}" y="${y0}" width="${bw * 0.28}" height="${hh}" fill="${fill}" rx="3"/>
        <text x="${x0 + bw * 0.14}" y="${val >= 0 ? y0 - 4 : y0 + hh + 12}" text-anchor="middle" font-size="10.5" fill="#c3cad6" font-family="JetBrains Mono">${val > 0 ? "+" : ""}${val.toFixed(1)}</text>`;
    };
    const bars = rows.map((r, i) => {
      const x0 = padL + i * bw + bw * 0.2;
      return bar(x0, r.real, "#8b95a7") + bar(x0 + bw * 0.31, r.sim, "#f2994a") +
        `<text x="${x0 + bw * 0.3}" y="${h - 12}" text-anchor="middle" font-size="12" fill="#c3cad6">${r.label}</text>`;
    }).join("");
    const cal = (v.calibration || []).map((c) => `<tr><td>${c.version}</td><td style="font-family:var(--mono)">${c.mae_pp.toFixed(1)} pp</td></tr>`).join("");
    return `<h2>Validation: do simulated residents react to heat like real Philadelphians?</h2>
      <p>${v.description}</p>
      <svg viewBox="0 0 ${w} ${h}" width="100%" role="img" aria-label="Real vs simulated hot-day change by category">
        <line x1="${padL}" x2="${w - padR}" y1="${y(0)}" y2="${y(0)}" stroke="#3a4352"/>
        ${bars}
        <text x="${padL}" y="16" font-size="12" fill="#8b95a7">${v.y_label}</text>
        <rect x="${w - 320}" y="6" width="10" height="10" fill="#8b95a7"/><text x="${w - 305}" y="15" font-size="12" fill="#c3cad6">Real (${v.real_source_short})</text>
        <rect x="${w - 100}" y="6" width="10" height="10" fill="#f2994a"/><text x="${w - 85}" y="15" font-size="12" fill="#c3cad6">Simulated</text>
      </svg>
      <p><b style="font-size:20px;font-family:var(--mono)">${v.error_label}</b></p>
      ${cal ? `<p style="margin-bottom:6px"><b>Calibration log</b></p><table>${cal}</table>` : ""}
      <p class="muted">${v.notes}</p>`;
  }
  function showMethods() {
    const row = ([k, v]) => `<tr><td><code>${k}</code></td><td>${typeof v.value === "object" ? JSON.stringify(v.value) : v.value}</td><td>${v.source}</td></tr>`;
    const lv = Object.entries(M.hazards).map(([, h]) => `<tr><td>${h.label}</td>${Object.values(h.levels).map((l) => `<td>${l.label.split(" — ")[1]}</td>`).join("")}</tr>`).join("");
    openModal(`<h2>Methods</h2>
      <p><b>Hazard days are real.</b> Each level replays one real day, hour by hour: the median event day, the 95th-percentile event day and the worst day on record. Heat index and wind chill come from NOAA hourly observations at PHL (2010–2024); rain is the trailing 3-hour total at PHL; smoke is the EPA PM2.5 NowCast AQI averaged over Philadelphia County monitors (2010–2025), counting only May–September days at AQI 101 or worse with a NOAA satellite-mapped smoke plume over the city (22 days; this drops winter inversions and July 4 fireworks).</p>
      <table><tr><th></th><th>Typical</th><th>Severe</th><th>Record</th></tr>${lv}</table>
      <p><b>World.</b> ${M.places.length.toLocaleString()} real places from OpenStreetMap plus the city's ${M.refuges.length} open cooling / warming sites and their posted hours (City of Philadelphia open data). Flood zones are FEMA's 2023 map; local heat is the city's 2023 Heat Exposure Index.</p>
      <p><b>People.</b> ${M.residents.length.toLocaleString()} synthetic adults sampled from ${new Set(M.residents.map((r) => r.tract)).size} Census tracts: age, employment and occupation, college enrollment, poverty, cars and living alone come from ACS 2024 tract tables; AC and heating access from EIA RECS 2020 (Pennsylvania, by poverty); asthma / COPD from CDC PLACES tract estimates. Unhoused residents are placed in Kensington and Center City and oversampled.</p>
      <p><b>Days are real.</b> Each housed resident's ordinary weekday is a real American Time Use Survey diary (2018–2024) from a respondent with the same role and age group, Philadelphia metro first, then other Northeast metro areas (summer diaries for heat, smoke and flood; winter diaries for cold). No survey covers unsheltered days, so theirs is a schedule around meal programs and library hours.</p>
      <p><b>Behavior.</b> Hazard rules change the diary day (warnings, avoiding outdoor time, refuges, flood driving). Their free parameters are fit to Philadelphia hot-day mobility (Google, 2020–21) and checked on 2022. Every hour stays inside a fixed list of activities and real places; a plausibility verifier rejects impossible days. The same schema constrains Claude when it plans instead of the rules.</p>
      <p><b>Exposure.</b> Deterministic: hourly hazard × share of the hour outdoors × the indoor environment where the resident is (AC, heat, HEPA, flood zone). Danger thresholds follow NWS heat index, EPA AQI and wind-chill categories, tightened for older adults, people with asthma / COPD and unhoused residents.</p>
      <p><b>Data sources</b></p><table>${Object.entries(M.sources).map(row).join("")}</table>
      <p><b>Still assumed</b> (no dataset found): indoor temperatures and filtration by home type, the Heat Exposure Index → °F scale (1 unit = 1°F), flood-zone weights, riverfront wind, warning awareness (~55%) and refuge travel limits. Plus:</p>
      <table>${Object.entries(M.assumptions).map(row).join("")}</table>
      <p class="muted">Generated ${M.generated}. All data public.</p>`);
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
    M = await fetch("data/meta.json").then((r) => r.json());
    M.placeIndex = Object.fromEntries(M.places.map((p, i) => [p[0], i]));
    const g = M.grid.step / 2;
    for (const c of M.grid.cells) c.poly = [[c[1] - g, c[0] - g], [c[1] + g, c[0] - g], [c[1] + g, c[0] + g], [c[1] - g, c[0] + g]];
    for (let i = 0; i < M.residents.length; i++) {
      const a = Math.sin(i * 12.9898) * 43758.5453, b = Math.sin(i * 78.233) * 12345.6789;
      jitter.push([((a - Math.floor(a)) - 0.5) * 0.0007, ((b - Math.floor(b)) - 0.5) * 0.0005]);
    }
    [roads, water] = await Promise.all([fetch("data/roads.json").then((r) => r.json()), fetch("data/waterways.json").then((r) => r.json())]);

    $("#ticks").innerHTML = [6, 9, 12, 15, 18, 21].map((h) => `<span>${fmtHour(h).replace(":00", "")}</span>`).join("");
    $("#time").oninput = (e) => { state.t = +e.target.value; redraw(); };
    $("#play").onclick = () => { state.playing = !state.playing; $("#play").classList.toggle("playing", state.playing); };
    $("#play").classList.add("playing");
    $("#speed").onchange = (e) => { state.speed = +e.target.value; };
    $("#btn-feature").onclick = featured;
    window.swelter = { state, select: (i) => { state.selected = i; renderInspector(); redraw(); }, featured,
      get run() { return run; }, residentPos };
    $("#insp-close").onclick = () => { state.selected = null; $("#inspector").hidden = true; redraw(); };
    $("#btn-methods").onclick = showMethods;
    $("#btn-validate").onclick = showValidation;
    $("#modal-close").onclick = () => $("#modal").close();
    document.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
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
    requestAnimationFrame(tick);
  }
  init();
})();
