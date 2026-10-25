/* Ask: planners question the simulation in plain English. The server has Gemini write one read-only SQL query over
   the simulation tables (Tiger Data or local SQLite), runs it and answers from the rows (backend/ask.py). Each answer
   shows its SQL and rows. Starts after sign-in (auth.js); government accounts only. */
(() => {
  const PRESETS = [
    "Which groups are most at risk on the record heat day compared with a typical hot day?",
    "At what hour does heat risk peak on the record day, and what are at-risk people doing then?",
    "Which census tracts have the most residents in danger in this scenario?",
    "If we open 1, 3 or 5 sites, how much of the predicted risk is within reach?",
    "Which sites reach the most at-risk residents without cars?",
    "Compare outdoor workers and office workers in the record winter storm.",
    "How many older adults living alone are in danger on each winter storm day?",
  ];
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const history = [];
  let busy = false;

  function mount() {
    $(".top-actions").insertAdjacentHTML("afterbegin", `<button class="ghost ask-open" id="btn-ask" aria-expanded="false" aria-controls="ask">Ask</button>`);
    document.body.insertAdjacentHTML("beforeend", `
      <aside class="ask" id="ask" hidden aria-label="Ask the simulation">
        <header class="ask-head">
          <div><h2>Ask the simulation</h2><p class="muted">Gemini writes SQL over every resident-hour; you see the query and rows.</p></div>
          <button class="close" id="ask-close" aria-label="Close">×</button>
        </header>
        <div class="ask-log" id="ask-log" aria-live="polite"></div>
        <div class="ask-presets" id="ask-presets"></div>
        <form class="ask-form" id="ask-form">
          <input id="ask-input" maxlength="500" autocomplete="off" placeholder="Ask about residents, hours, tracts or sites…" aria-label="Question">
          <button class="ask-send" type="submit">Ask</button>
        </form>
      </aside>`);
    $("#btn-ask").onclick = () => toggle();
    $("#ask-close").onclick = () => toggle(false);
    $("#ask-form").onsubmit = (e) => { e.preventDefault(); send($("#ask-input").value); };
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#ask").hidden && !document.querySelector("dialog[open]")) toggle(false); });
    presets();
  }

  function toggle(open = $("#ask").hidden) {
    $("#ask").hidden = !open;
    $("#btn-ask").setAttribute("aria-expanded", open);
    if (open) $("#ask-input").focus(); else $("#btn-ask").focus();
  }

  // Before the first question the suggestions are the main content; afterwards a compact row above the input.
  function presets() {
    const asked = new Set(history.map((h) => h.question));
    const left = PRESETS.filter((p) => !asked.has(p));
    $("#ask-presets").className = history.length ? "ask-presets compact" : "ask-presets";
    $("#ask-presets").innerHTML = (history.length ? "" : `<p class="ask-label">Try one of these</p>`)
      + left.slice(0, history.length ? 3 : 7).map((p) => `<button type="button" class="ask-chip">${esc(p)}</button>`).join("");
    $("#ask-presets").querySelectorAll(".ask-chip").forEach((b) => (b.onclick = () => send(b.textContent)));
  }

  function table(cols, rows) {
    if (!cols.length) return "";
    const cell = (v) => esc(typeof v === "number" ? v.toLocaleString() : v === true ? "yes" : v === false ? "no" : v);
    return `<div class="ask-table"><table><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>${rows.slice(0, 25)
      .map((r) => `<tr>${r.map((v) => `<td>${cell(v)}</td>`).join("")}</tr>`).join("")}</table></div>`;
  }

  async function send(text) {
    const question = text.trim();
    if (!question || busy) return;
    busy = true;
    $("#ask-input").value = "";
    $("#ask-presets").innerHTML = "";
    const log = $("#ask-log");
    log.insertAdjacentHTML("beforeend", `<div class="ask-q">${esc(question)}</div><div class="ask-a pending">Writing a query…</div>`);
    const out = log.lastElementChild;
    log.scrollTop = log.scrollHeight;
    const s = window.swelter?.state;
    try {
      const res = await fetch("api/ask", {
        method: "POST", headers: { "Content-Type": "application/json", ...swelterAuth.headers() },
        body: JSON.stringify({ question, history: history.slice(-3),
          scenario: s && { hazard: s.hazard, level: s.level, iv: s.iv, budget: s.siteBudget } }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || `HTTP ${res.status}`);
      history.push({ question, sql: j.sql });
      const n = j.row_count ?? j.rows.length;
      out.classList.remove("pending");
      out.innerHTML = `<p></p><div class="ask-meta">${esc(j.model)} · ${esc(j.engine)}${j.sql ? ` · ${n.toLocaleString()} row${n === 1 ? "" : "s"}${j.truncated ? "+" : ""}` : ""}</div>
        ${j.sql ? `<details><summary>SQL and data</summary><pre>${esc(j.sql)}</pre>${table(j.columns, j.rows)}
          ${n > 25 ? `<p class="muted">First 25 of ${n.toLocaleString()} rows.</p>` : ""}</details>` : ""}`;
      $("p", out).textContent = j.answer;
    } catch (e) {
      out.classList.remove("pending");
      out.classList.add("err");
      out.textContent = `Couldn't answer: ${e.message}`;
    }
    busy = false;
    presets();
    log.scrollTop = log.scrollHeight;
  }

  swelterAuth.ready.then(mount);
})();
