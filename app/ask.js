/* Ask: a chat with Gemini about the simulation. Gemini answers from the conversation and runs read-only SQL over the
   simulation tables (Tiger Data or local SQLite) only when it needs data (backend/ask.py). Each answer shows the
   queries it ran and their rows. Starts after sign-in (auth.js); government accounts only. */
(() => {
  // Suggestions follow the hazard picked in the scenario bar (the whole page takes its theme too).
  const PRESETS = {
    any: [
      "What can you tell me, and how were these residents built?",
      "Which census tracts have the most residents in danger in this scenario?",
      "If we open 1, 3 or 5 sites, how much of the predicted risk is within reach?",
    ],
    heat: [
      "Which groups are most at risk on the record heat day compared with a typical hot day?",
      "At what hour does heat risk peak on the record day, and what are at-risk people doing then?",
      "Which cooling sites reach the most at-risk residents without cars?",
      "How do outdoor workers compare with office workers on the severe heat day?",
    ],
    cold: [
      "Compare outdoor workers and office workers in the record winter storm.",
      "How many older adults living alone are in danger on each winter storm day?",
      "Which warming sites reach the most residents without reliable heat?",
      "At what hour is cold risk worst on the record winter storm day, and where are people then?",
    ],
  };
  const presetList = () => [...PRESETS[window.swelter?.state.hazard === "cold" ? "cold" : "heat"], ...PRESETS.any];
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const history = [];
  let busy = false;

  function mount() {
    $(".top-actions").insertAdjacentHTML("afterbegin", `<button class="ghost ask-open" id="btn-ask" aria-expanded="false" aria-controls="ask">Ask</button>`);
    document.body.insertAdjacentHTML("beforeend", `
      <aside class="ask" id="ask" hidden aria-label="Ask the simulation">
        <header class="ask-head">
          <div><h2>Ask the simulation</h2><p class="muted">Chat with Gemini. When it needs numbers it queries every resident-hour, and shows you each query.</p></div>
          <button class="close" id="ask-close" aria-label="Close">×</button>
        </header>
        <div class="ask-log" id="ask-log" aria-live="polite"></div>
        <div class="ask-presets" id="ask-presets"></div>
        <form class="ask-form" id="ask-form">
          <input id="ask-input" maxlength="500" autocomplete="off" placeholder="Ask anything about the simulation…" aria-label="Message">
          <button class="ask-send" type="submit">Send</button>
        </form>
      </aside>`);
    $("#btn-ask").onclick = () => toggle();
    $("#ask-close").onclick = () => toggle(false);
    $("#ask-form").onsubmit = (e) => { e.preventDefault(); send($("#ask-input").value); };
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#ask").hidden && !document.querySelector("dialog[open]")) toggle(false); });
    presets();
    document.addEventListener("swelter:scenario", presets);
  }

  function toggle(open = $("#ask").hidden) {
    $("#ask").hidden = !open;
    $("#btn-ask").setAttribute("aria-expanded", open);
    if (open) $("#ask-input").focus(); else $("#btn-ask").focus();
  }

  // Before the first question the suggestions are the main content; afterwards a compact row above the input.
  function presets() {
    const asked = new Set(history.map((h) => h.question));
    const left = presetList().filter((p) => !asked.has(p));
    $("#ask-presets").className = history.length ? "ask-presets compact" : "ask-presets";
    $("#ask-presets").innerHTML = (history.length ? "" : `<p class="ask-label">Try one of these</p>`)
      + left.slice(0, history.length ? 3 : 8).map((p) => `<button type="button" class="ask-chip">${esc(p)}</button>`).join("");
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
    log.insertAdjacentHTML("beforeend", `<div class="ask-q">${esc(question)}</div><div class="ask-a pending">Thinking…</div>`);
    const out = log.lastElementChild;
    log.scrollTop = log.scrollHeight;
    const s = window.swelter?.state;
    try {
      const res = await fetch("api/ask", {
        method: "POST", headers: { "Content-Type": "application/json", ...swelterAuth.headers() },
        body: JSON.stringify({ question, history: history.slice(-8),
          scenario: s && { hazard: s.hazard, level: s.level, iv: s.iv, budget: s.siteBudget } }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || `HTTP ${res.status}`);
      const qs = j.queries || [];
      history.push({ question, answer: j.answer, sql: qs.map((q) => q.sql) });
      out.classList.remove("pending");
      out.innerHTML = `<p></p><div class="ask-meta">${esc(j.model)}${qs.length ? ` · ${qs.length} ${qs.length === 1 ? "query" : "queries"} on ${esc(j.engine)}` : " · no query needed"}</div>
        ${qs.map((q, k) => {
          const n = q.row_count ?? 0;
          return `<details><summary>${qs.length > 1 ? `Query ${k + 1}: ` : "SQL and data: "}${esc(q.purpose || (q.error ? "failed, retried" : `${n.toLocaleString()} row${n === 1 ? "" : "s"}`))}</summary>
            <pre>${esc(q.sql)}</pre>${q.error ? `<p class="muted">${esc(q.error)}</p>` : table(q.columns, q.rows)}
            ${n > 25 ? `<p class="muted">First 25 of ${n.toLocaleString()} rows${q.truncated ? "+" : ""}.</p>` : ""}</details>`;
        }).join("")}`;
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
