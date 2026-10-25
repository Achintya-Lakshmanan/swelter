/* Sign-in for the planner page, which is for government accounts. Auth0 Universal Login with PKCE, no SDK; the
   server decides the role (backend/auth.py). Residents and volunteers use the iPhone app. With SWELTER_DEV_LOGIN=1
   the server also offers a demo government account. main.js starts once swelterAuth.ready resolves. */
(() => {
  const KEY = "swelter.auth", PKCE = "swelter.pkce";
  const read = (k) => { try { return JSON.parse(sessionStorage.getItem(k)); } catch (e) { return null; } };
  const write = (k, v) => { try { v ? sessionStorage.setItem(k, JSON.stringify(v)) : sessionStorage.removeItem(k); } catch (e) { /* private mode */ } };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const ROLE = { government: "Government", responder: "Volunteer", resident: "Resident" };
  let cfg = null, session = read(KEY);

  const headers = () => (session?.token ? { Authorization: `Bearer ${session.token}` }
    : session?.demo ? { "X-Demo-Account": session.demo } : {});
  const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const random = (n) => b64url(crypto.getRandomValues(new Uint8Array(n)));
  const redirectUri = () => location.origin + location.pathname;
  const webAuth0 = () => cfg?.auth0?.enabled && cfg.auth0.web_client_id;

  async function login() {
    if (!crypto.subtle) return gate({ error: "Sign-in needs https or localhost (the browser only allows it on a secure page)." });
    const a = cfg.auth0, verifier = random(32), state = random(16);
    const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
    write(PKCE, { verifier, state, search: location.search });  // keeps deep links (?hazard=…&resident=…) across the redirect
    const p = new URLSearchParams({
      response_type: "code", client_id: a.web_client_id, redirect_uri: redirectUri(), scope: "openid profile email",
      code_challenge: challenge, code_challenge_method: "S256", state, prompt: "login",
    });
    if (a.audience) p.set("audience", a.audience);
    location.assign(`https://${a.domain}/authorize?${p}`);
  }

  async function finishLogin(q) {
    const saved = read(PKCE);
    write(PKCE, null);
    history.replaceState(null, "", location.pathname + (saved?.search || ""));
    if (q.get("error")) throw new Error(q.get("error_description") || q.get("error"));
    if (!saved || saved.state !== q.get("state")) throw new Error("The sign-in response didn't match. Try again.");
    const res = await fetch(`https://${cfg.auth0.domain}/oauth/token`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ grant_type: "authorization_code", client_id: cfg.auth0.web_client_id,
        code_verifier: saved.verifier, code: q.get("code"), redirect_uri: redirectUri() }),
    });
    const t = await res.json();
    if (!t.access_token) throw new Error(t.error_description || "Auth0 didn't return a token.");
    session = { token: t.access_token, exp: Date.now() + (t.expires_in || 3600) * 1000 };
    write(KEY, session);
  }

  function signOut() {
    const viaAuth0 = !!session?.token;
    session = null;
    write(KEY, null);
    if (viaAuth0 && webAuth0()) {
      location.assign(`https://${cfg.auth0.domain}/v2/logout?${new URLSearchParams({ client_id: cfg.auth0.web_client_id, returnTo: redirectUri() })}`);
    } else location.reload();
  }

  async function me() {
    const r = await fetch("api/me", { headers: headers() });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
    return j;
  }

  /** The sign-in screen over the page: Auth0, demo government account, or "this page isn't for your account". */
  function gate({ error, user } = {}) {
    let el = document.getElementById("gate");
    if (!el) { el = document.createElement("div"); el.id = "gate"; el.className = "gate"; document.body.append(el); }
    const demos = (cfg?.auth0?.demo_accounts || []).filter((d) => d.role === "government");
    const who = user ? `${esc(user.name || user.profile?.name || "This account")} · ${ROLE[user.role] || user.role}` : "";
    el.innerHTML = `<div class="gate-card" role="dialog" aria-labelledby="gate-title">
      <span class="logo" aria-hidden="true"></span>
      <h2 id="gate-title">ChillySOS planner</h2>
      <p class="muted">For city emergency planners. Residents and volunteers use the ChillySOS iPhone app.</p>
      ${user ? `<p class="gate-msg">Signed in as <b>${who}</b>. This page is for government accounts; open the iPhone app instead.</p>
        <button class="gate-btn" id="gate-out">Sign out</button>` : `
        ${webAuth0() ? `<button class="gate-btn" id="gate-auth0">Sign in with Auth0</button>`
          : `<p class="gate-msg">Auth0 isn't set up on this server (AUTH0_DOMAIN and AUTH0_WEB_CLIENT_ID in .env).</p>`}
        ${demos.map((d) => `<button class="gate-demo" data-id="${esc(d.id)}"><b>${esc(d.name)}</b><span>${esc(d.about)} · demo</span></button>`).join("")}`}
      ${error ? `<p class="gate-err">${esc(error)}</p>` : ""}
    </div>`;
    el.querySelector("#gate-auth0")?.addEventListener("click", login);
    el.querySelector("#gate-out")?.addEventListener("click", signOut);
    el.querySelectorAll(".gate-demo").forEach((b) => b.addEventListener("click", () => {
      session = { demo: b.dataset.id };
      write(KEY, session);
      location.reload();
    }));
  }

  function chip(u) {
    const bar = document.querySelector(".top-actions");
    if (!bar) return;
    bar.insertAdjacentHTML("afterbegin", `<span class="who" title="${esc(u.demo ? "Demo account" : "Signed in with Auth0")}">${esc(u.name || "Planner")} · Government</span>
      <button class="ghost" id="btn-signout">Sign out</button>`);
    document.getElementById("btn-signout").onclick = signOut;
  }

  window.swelterAuth = {
    headers, signOut,
    ready: new Promise((resolve) => {
      (async () => {
        try { cfg = await fetch("api/config").then((r) => r.json()); } catch (e) { return gate({ error: "Can't reach the ChillySOS server." }); }
        const q = new URLSearchParams(location.search);
        if (q.has("state") && (q.has("code") || q.has("error"))) {
          try { await finishLogin(q); } catch (e) { return gate({ error: e.message }); }
        }
        if (session?.exp && session.exp < Date.now()) { session = null; write(KEY, null); }
        if (!session) return gate();
        let u;
        try { u = await me(); } catch (e) { session = null; write(KEY, null); return gate({ error: e.message }); }
        if (u.role !== "government") return gate({ user: u });
        chip(u);
        resolve(u);
      })();
    }),
  };
})();
