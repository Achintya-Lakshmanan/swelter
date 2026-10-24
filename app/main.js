/* Swelter front end: replays precomputed runs on a deck.gl map. Only /api/why is live. */
(() => {
  const HAZARD_COLOR = { heat: "#f2994a", smoke: "#9b8d7a", flood: "#4c8dff", cold: "#7fc8ff" };
  const LEVEL_RGB = [[47, 143, 122], [242, 201, 76], [242, 153, 74], [235, 77, 91]];
  const LEVEL_NAME = ["Safe", "Caution", "Danger", "Extreme"];
  const REFUGE_NAME = { heat: "Cooling center", smoke: "Clean-air center", flood: "Shelter", cold: "Warming center" };
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
    hazard: "heat", level: "severe", iv: "none", site: "huntingpark",
    t: 6, playing: true, speed: 0.5, selected: null, group: null,
  };
  let M, roads = [], water = [], deckOverlay, map, run, baseRun, frame = 0, lastTs = 0;
  const runCache = new Map();
  const jitter = [];

  const sid = (iv = state.iv) =>
    `${state.hazard}_${state.level}_${iv}${iv === "refuge" ? "_" + state.site : ""}`;

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
    return r;
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
    seg($("#level-seg"), Object.entries(hz.levels).map(([k, v]) => [k, v.label]), state.level, (k) => { state.level = k; update(); });
    seg($("#iv-seg"), Object.entries(hz.interventions).map(([k, v]) => [k, v.label]), state.iv, (k) => { state.iv = k; update(); });
    const ss = $("#site-select");
    ss.hidden = state.iv !== "refuge";
    ss.innerHTML = Object.entries(M.sites).map(([k, v]) => `<option value="${k}" ${k === state.site ? "selected" : ""}>${v.label}</option>`).join("");
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
    const hz = M.hazards[state.hazard], iv = hz.interventions[state.iv];
    const site = state.iv === "refuge" ? ` Site: <b style="display:inline">${M.sites[state.site].label}</b>.` : "";
    $("#iv-badge").innerHTML = `<b>${hz.label} · ${hz.levels[state.level].label} · ${iv.label}</b>` +
      `<span class="muted">${iv.desc ? iv.desc.replace(/ at the chosen site\.?/, ".") : "Baseline: no city response beyond today's normal services."}${site}</span>`;
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
      <p class="hint">Refuge column uses ${M.sites[state.site].label}. Green = best option for that group.</p>`;
  }

  function renderProvenance() {
    const v = run.verifier, pct = ((v.rejected / v.drafts) * 100).toFixed(1);
    const types = new Set(M.residents.map((r) => r.type)).size;
    $("#provenance").innerHTML = `
      <div><b>${M.residents.length.toLocaleString()}</b> synthetic residents · <b>${types}</b> persona types, drawn from <b>ACS 2024</b> tract data</div>
      <div><b>${M.places.length.toLocaleString()}</b> real places from OpenStreetMap</div>
      <div>Planner: <b>${run.planner === "rules" ? "rule-based (offline)" : "Claude + rules fallback"}</b> · choices limited to a fixed schema</div>
      <div>Plausibility verifier rejected <b>${v.rejected}</b> of ${v.drafts.toLocaleString()} drafted days (${pct}%) and regenerated them</div>
      <div>Exposure is computed deterministically: hazard × time outdoors × AC/heat/filtration where they are</div>`;
  }

  // ---------- map ----------
  function residentPos(i, t) {
    const H = M.hours.length, x = Math.min(Math.max(t - 6, 0), H - 0.001), h = Math.floor(x), f = x - h;
    const k = i * H + h, cur = M.places[run.place[k]], prev = h > 0 ? M.places[run.place[k - 1]] : cur;
    const commute = M.activities[run.act[k]] === "commute";
    const dur = commute ? 0.85 : 0.25;
    let s = Math.min(1, f / dur); s = s * s * (3 - 2 * s);
    const j = jitter[i];
    return [prev[4] + (cur[4] - prev[4]) * s + j[0], prev[3] + (cur[3] - prev[3]) * s + j[1]];
  }
  const levelAt = (i, t) => run.lvl[i * M.hours.length + Math.min(Math.floor(t - 6), M.hours.length - 1)];

  function overlayColor(cell, I) {
    const [, , uhi, flood, wind] = cell;
    switch (state.hazard) {
      case "heat": {
        // overall heat sets the strength; the heat-island offset (-3..+4 °F) shows where it's worst
        const a = Math.max(0, Math.min(1, (I - 84) / 26)), u = (uhi + 3) / 7;
        return [240, 140 - 100 * u, 60 - 40 * u, a * (10 + 120 * u * u)];
      }
      case "smoke": { const a = Math.max(0, Math.min(1, (I - 50) / 350)); return [150, 130, 105, 12 + 85 * a + 8 * uhi]; }
      case "flood": return flood ? [60, 130, 255, Math.min(140, 18 + 38 * I)] : [0, 0, 0, 0];
      case "cold": { const v = I - wind, a = Math.max(0, Math.min(1, (32 - v) / 50)); return [120, 190, 255, 8 + 55 * a + (wind ? 35 : 0)]; }
    }
  }

  function layers() {
    const t = state.t, I = intensityAt(t), n = M.residents.length;
    const sel = state.selected, grp = state.group;
    const refugeIds = state.iv === "refuge" ? [state.site] : [];
    const sites = Object.entries(M.sites).map(([k, s]) => {
      const p = M.placeById[s.place_id];
      return { key: k, label: s.label.split(" (")[0], pos: [p[4], p[3]], on: refugeIds.includes(k) };
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
        getRadius: (d) => (d.on ? 260 : 140), radiusMinPixels: 6, lineWidthMinPixels: 2,
        getFillColor: (d) => (d.on ? [90, 209, 230, 60] : [255, 255, 255, 10]),
        getLineColor: (d) => (d.on ? [90, 209, 230, 255] : [139, 149, 167, 150]),
        updateTriggers: { getRadius: state.site + state.iv, getFillColor: state.site + state.iv, getLineColor: state.site + state.iv },
      }),
      new deck.TextLayer({
        id: "site-labels", data: sites.filter((s) => s.on || state.iv === "refuge"), getPosition: (d) => d.pos,
        getText: (d) => (d.on ? `${REFUGE_NAME[state.hazard]} · ${d.label}` : d.label), getSize: (d) => (d.on ? 13 : 11),
        getColor: (d) => (d.on ? [210, 245, 252, 255] : [139, 149, 167, 200]), getPixelOffset: [0, -20],
        fontFamily: "Inter, sans-serif", fontWeight: 600, outlineWidth: 3, outlineColor: [11, 14, 19, 230],
        fontSettings: { sdf: true }, updateTriggers: { getText: state.hazard + state.site, getColor: state.site, getSize: state.site },
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
      <div class="trace">Traces to <b>${r.source}</b><ul>${Object.values(r.trace).map((t) => `<li>${t}</li>`).join("")}</ul></div>
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
    const a = M.assumptions;
    openModal(`<h2>Methods</h2>
      <p><b>World.</b> ${M.places.length.toLocaleString()} real places in Center City, University City and North Philadelphia from OpenStreetMap (Overpass), plus roads and waterways. Flood-prone = within ~220 m of a river/creek or at a documented Ida flood spot (I-676). Heat-island offset = fewer parks nearby → hotter; riverside → cooler.</p>
      <p><b>People.</b> ${M.residents.length.toLocaleString()} synthetic residents sampled from ${new Set(M.residents.map((r) => r.tract)).size} Census tracts (ACS 2024 5-year via Census Reporter): age, college enrollment, vehicle access, 65+ living alone, poverty, outdoor-heavy occupations. 60 unsheltered residents are placed in Kensington and Center City (oversampled; group averages are per person).</p>
      <p><b>Behavior.</b> Each hour's activity comes from a fixed list and each place from a fixed set of real map places. Generated offline in batch, either by the rule planner (ATUS-style day templates + hazard behavior rules) or by Claude constrained by a JSON schema of enums. A plausibility verifier rejects impossible days (closed places, trips that don't fit in an hour, unhoused "at home") and regenerates them.</p>
      <p><b>Exposure.</b> Deterministic: hourly hazard intensity × share of the hour outdoors × the indoor environment where the resident is (AC, heat, HEPA, flood-prone ground floor). Danger thresholds follow NWS heat index, EPA AQI and wind-chill categories, tightened for older adults, people with asthma/COPD and unhoused residents.</p>
      <p><b>Assumptions not yet tied to a dataset:</b></p>
      <table>${Object.entries(a).map(([k, v]) => `<tr><td><code>${k}</code></td><td>${v.value}</td><td>${v.source}</td></tr>`).join("")}</table>
      <p class="muted">Generated ${M.generated}. All data public; no IRB dependency.</p>`);
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
    M.placeById = Object.fromEntries(M.places.map((p) => [p[0], p]));
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
    $("#site-select").onchange = (e) => { state.site = e.target.value; update(); };
    $("#btn-feature").onclick = featured;
    window.swelter = { state, select: (i) => { state.selected = i; renderInspector(); redraw(); }, featured };
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
