# Auth0 setup: three kinds of account

ChillySOS has one Auth0 tenant, one API and two applications. The server reads each person's role from their access
token (`backend/auth.py`):

| Account | Auth0 permission (on the API) | Where they sign in | What they get |
| --- | --- | --- | --- |
| Resident | none | iPhone app | Resident view: map, open sites, Get help, voice check-ins |
| Volunteer | `respond:requests` | iPhone app | Volunteer view: request pop-ups, queue, sites board. "I need help" in the account menu switches to the resident view; Settings switches back |
| Government | `view:planner` | Planner web page (`http://localhost:8000/`) | The simulator: hazards, interventions, compare panel, "Why?" |

A government account that signs in on the phone is pointed to the web page; a resident or volunteer who signs in
on the web page is told to use the app. If an account has both permissions, government wins.

The code is done; these steps are the tenant configuration, which only you can do (it needs your Auth0 account).
Nothing needs rebuilding afterwards: the app and the page read the tenant settings from the server's `/api/config`.

## 1. Tenant

Sign up at [auth0.com](https://auth0.com) (the free plan is enough) and create a tenant. Its domain looks like
`swelter.us.auth0.com`.

## 2. API

Applications › APIs › **Create API**.

- Name `ChillySOS API`, identifier `https://api.swelter.app`, signing algorithm RS256.
- **Settings** tab, RBAC settings: turn on **Enable RBAC** and **Add Permissions in the Access Token**. Save.
- **Permissions** tab: add `respond:requests` ("Answer help requests") and `view:planner` ("Use the planner page").

## 3. Applications

Applications › Applications › **Create Application**, twice.

**ChillySOS iPhone** (type: Native)
- Allowed Callback URLs and Allowed Logout URLs:
  `app.swelter.Swelter://YOUR_DOMAIN/ios/app.swelter.Swelter/callback`
- Copy the Client ID.

**ChillySOS planner** (type: Single Page Application)
- Allowed Callback URLs and Allowed Logout URLs: `http://localhost:8000/, http://127.0.0.1:8000/`
- Allowed Web Origins: `http://localhost:8000, http://127.0.0.1:8000`
- Add your `https://` address too if you deploy (Vultr + a GoDaddy domain). Browsers only allow the sign-in code
  on `https://` or localhost, so the planner page can't sign in from `http://<laptop LAN IP>:8000`.
- Copy the Client ID.

On each application's **Connections** tab, make sure **Username-Password-Authentication** is on. If a sign-in fails
with "not authorized to access resource server", open the API's **Application Access** (or Machine to Machine /
User Access) settings and allow both applications.

## 4. Roles and the three users

User Management › Roles › **Create Role**:
- `Volunteer`, with permission `respond:requests` from ChillySOS API
- `Government`, with permission `view:planner` from ChillySOS API

User Management › Users › **Create User** (connection Username-Password-Authentication), three times, with
addresses and passwords you choose:
- a resident: no role
- a volunteer: assign the `Volunteer` role (the user's Roles tab)
- a planner: assign the `Government` role

## 5. Names on screen (optional)

Access tokens don't carry a name by default, so the phone asks for one on first sign-in and the web page shows
"Planner". To send the name and email, add a post-login Action (Actions › Library › Create Action, trigger Login /
Post Login), deploy it, and drag it into the Login flow:

```js
exports.onExecutePostLogin = async (event, api) => {
  api.accessToken.setCustomClaim("https://swelter.app/name", event.user.name);
  api.accessToken.setCustomClaim("https://swelter.app/email", event.user.email);
};
```

With the email in the token you can also grant roles by list instead of RBAC: `SWELTER_RESPONDERS` and
`SWELTER_GOVERNMENT` in `.env` (comma-separated emails).

## 6. `.env`, then restart

```
AUTH0_DOMAIN=swelter.us.auth0.com
AUTH0_CLIENT_ID=<ChillySOS iPhone client ID>
AUTH0_WEB_CLIENT_ID=<ChillySOS planner client ID>
AUTH0_AUDIENCE=https://api.swelter.app
```

```bash
HOST=0.0.0.0 SWELTER_DEV_LOGIN=1 uv run --env-file .env server.py
```

Keep `SWELTER_DEV_LOGIN=1` for the demo if you want the demo accounts as a backup (Kayla and Marisol on the phone,
Jordan Ellis on the web page); drop it to show only Auth0.

## Check

- Phone › Sign in › resident: resident view. Sign out, sign in as the volunteer: volunteer view. Sign in as the
  planner: "Use the planner on the web". The app always shows the Auth0 login form (`prompt=login`), so one phone
  can switch between the accounts.
- `http://localhost:8000/` › Sign in with Auth0 › planner: the simulator, with "Planner · Government" and Sign out
  in the top bar. The resident or volunteer: "This page is for government accounts".
