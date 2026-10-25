/* PREVIEW: the finding line, peak-hour jump and hazard ramp, built on window.swelter (no changes to main.js data). */
(() => {
  const $ = (s) => document.querySelector(s);
  const fmt = (n, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const hourLabel = (h) => `${((h + 11) % 12) + 1} ${h < 12 ? "AM" : "PM"}`;

  function render() {
    const app = window.swelter;
    if (!app?.run) return;
    const st = app.state, M = app.meta, s = app.summary(), hz = M.hazards[st.hazard];
    const day = hz.levels[st.level].label.split(" — ")[1];
    const groups = Object.entries(s.groups).map(([g, v]) => ({ g, per: v.risk / (v.n || 1), ...v })).sort((a, b) => b.per - a.per);
    const top = groups[0];
    const sites = st.iv === "refuge" ? Math.min(st.siteBudget, s.result.sites.length) : 0;
    const share = s.risk ? s.covered / s.risk : 0;
    const f = $("#finding");
    if (st.iv === "refuge") {
      f.innerHTML = `${sites} ${st.hazard === "heat" ? "cooling" : "warming"} site${sites === 1 ? "" : "s"} reach <b>${fmt(share * 100)}%</b> of predicted danger on ${day}.`;
      $("#finding-sub").innerHTML = `${fmt(s.covered)} of ${fmt(s.risk)} risk-hours. Reachable risk is not prevented exposure: attendance, capacity and routes are unverified.`;
    } else {
      f.innerHTML = `${M.groups[top.g]} face <b>${fmt(top.per, 1)} h</b> of predicted danger each on ${day}.`;
      $("#finding-sub").innerHTML = `${fmt(s.risk)} predicted risk-hours across ${fmt(s.n)} synthetic residents. <button class="link" id="try-sites">Open ${st.siteBudget} ${st.hazard === "heat" ? "cooling" : "warming"} sites</button>`;
      $("#try-sites").onclick = () => app.setResponse("refuge");
    }
    // peak hour of the real day
    const I = app.run.intensity, cold = st.hazard === "cold";
    let pk = 0; I.forEach((v, i) => { if (cold ? v < I[pk] : v > I[pk]) pk = i; });
    const b = $("#peak");
    b.textContent = `Peak ${hourLabel(M.hours[pk])}`;
    b.onclick = () => { st.t = M.hours[pk] + 0.01; app.refreshMap(); };
    // stepped ramp for the hazard field, with today's range marked
    const lo = Math.min(...I), hi = Math.max(...I);
    $("#ramp").innerHTML = `<span class="ramp-label">${cold ? "Wind chill" : "Heat index"} today</span>` +
      `<span class="ramp-steps">${[0, 1, 2, 3, 4].map((k) => `<i style="opacity:${0.2 + k * 0.2}"></i>`).join("")}</span>` +
      `<span class="ramp-range">${fmt(cold ? hi : lo)}–${fmt(cold ? lo : hi)}°F</span>`;
    document.documentElement.dataset.hazard = st.hazard;
  }
  document.addEventListener("swelter:scenario", () => requestAnimationFrame(render));
})();
