// Showcase page. The text ships with the current numbers; this refreshes them from the same stored runs the map
// replays, then starts the motion layer.
(async function () {
  const $ = (s) => document.querySelector(s);
  const get = (p) => fetch(p).then((r) => r.json());
  const run = (hz, iv) => get(`data/runs/${hz}_extreme_${iv}.json`);
  const minus = (s) => s.replace("-", "−");
  const PEAK = {
    heat: (v) => [`${Math.round(Math.max(...v))}°F heat index`, `peak heat index ${Math.round(Math.max(...v))}°F`],
    smoke: (v) => [`AQI ${Math.round(Math.max(...v))}`, `peak air quality index ${Math.round(Math.max(...v))}`],
    flood: (v) => [`${Math.max(...v).toFixed(1)} in of rain in 3 h`, `${Math.max(...v).toFixed(1)} inches of rain in three hours`],
    cold: (v) => [minus(`${Math.round(Math.min(...v))}°F wind chill`), minus(`wind chill down to ${Math.round(Math.min(...v))}°F`)],
  };
  // [hazard, group, intervention, how the caption names them]
  const WINS = [
    ["cold", "unhoused", "outreach", "unhoused residents on the record cold day, with outreach to 24-hour sites"],
    ["smoke", "unhoused", "n95", "unhoused residents on the record smoke day, with an N95 giveaway"],
    ["cold", "outdoor_worker", "alert", "outdoor workers on the record cold day, with an early Code Blue"],
    ["heat", "unhoused", "refuge", "unhoused residents on the record heat day, with cooling sites open"],
    ["heat", "outdoor_worker", "alert", "outdoor workers on the record heat day, with an early heat alert"],
  ];
  const longDate = (d) => new Date(`${d}T12:00`).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  const notes = {};

  try {
    const [M, V] = await Promise.all([get("data/meta.json"), get("data/validation.json")]);
    const hz = Object.keys(M.hazards);
    const ivs = { heat: ["none", "refuge", "transit", "alert"], smoke: ["none", "n95"], flood: ["none", "refuge"], cold: ["none", "outreach", "alert"] };
    const R = {};
    await Promise.all(hz.flatMap((h) => ivs[h].map(async (iv) => { R[`${h}_${iv}`] = await run(h, iv); })));
    const dh = (h, iv, g) => R[`${h}_${iv}`].summary.groups[g].danger_hours;

    document.querySelectorAll('[data-n="residents"]').forEach((el) => { el.textContent = M.residents.length.toLocaleString("en-US"); });
    $("#record-list").innerHTML = hz.map((h) => {
      const lv = M.hazards[h].levels.extreme, v = R[`${h}_none`].intensity;
      notes[h] = `Opens the live map at ${longDate(lv.date)}, ${PEAK[h](v)[1]}, with nothing done yet.`;
      return `<li><b>${{ heat: "Heat", smoke: "Smoke", flood: "Flood", cold: "Cold" }[h]}</b> <span>${lv.label.split(" — ")[1]}</span> <span>${PEAK[h](v)[0]}</span></li>`;
    }).join("");
    $("#noac-base").textContent = dh("heat", "none", "no_ac").toFixed(1);
    $("#noac-refuge").textContent = dh("heat", "refuge", "no_ac").toFixed(1);
    $("#noac-transit").textContent = dh("heat", "transit", "no_ac").toFixed(1);
    $("#flood-base").textContent = dh("flood", "none", "flood_zone").toFixed(1);
    $("#flood-refuge").textContent = dh("flood", "refuge", "flood_zone").toFixed(1);
    $("#mae").textContent = V.mae_pp;
    $("#ledger").innerHTML = WINS.map(([h, g, iv, cap]) => {
      const [w, d] = (dh(h, "none", g) - dh(h, iv, g)).toFixed(1).split(".");
      return `<li><span class="whole"><span>${w}</span></span><span class="dec"><span>.${d}</span></span><span class="cap">hours fewer for ${cap}</span></li>`;
    }).join("");
  } catch (e) {
    console.warn("Showcase numbers not refreshed; keeping the ones in the page.", e);
  }

  // a decorative loop stops when the reader asks for less motion; the poster frame stays
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) document.querySelectorAll("video").forEach((v) => { v.removeAttribute("autoplay"); v.pause(); });

  // the closing sentence: pick a hazard, open its record day on the map
  const sel = $("#ask-hazard");
  sel.onchange = () => { if (notes[sel.value]) $("#ask-note").textContent = notes[sel.value]; };

  // entrances, once each
  const targets = [...document.querySelectorAll("[data-reveal], .shutter, .claim-pic, .rows li")];
  document.querySelectorAll(".stack [data-reveal]").forEach((el, i) => el.style.setProperty("--i", i));
  document.querySelectorAll(".rows li").forEach((el, i) => el.style.setProperty("--i", i));
  if (!("IntersectionObserver" in window)) targets.forEach((el) => el.classList.add("is-in"));
  else {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.1 });
    targets.forEach((el) => io.observe(el));
  }

  // the cropped wordmark fills the content box exactly
  const mark = $(".wordmark");
  const fit = () => {
    mark.style.fontSize = "";
    const avail = mark.parentElement.clientWidth - parseFloat(getComputedStyle(mark.parentElement).paddingLeft) * 2;
    mark.style.fontSize = `${(parseFloat(getComputedStyle(mark).fontSize) * avail) / mark.scrollWidth}px`;
  };
  document.fonts.ready.then(fit);
  addEventListener("resize", fit);

  // the source names light up one at a time
  const names = [...document.querySelectorAll(".names span:not(.lead-in)")];
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches && names.length) {
    let k = 0;
    names[0].classList.add("lit");
    setInterval(() => { names[k].classList.remove("lit"); k = (k + 1) % names.length; names[k].classList.add("lit"); }, 2000);
  }
})();
