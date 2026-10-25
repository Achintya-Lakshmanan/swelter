"""Sign-in with Auth0 for three kinds of account. The iPhone app (residents, volunteers) and the planner web page
(government) log in through Auth0 Universal Login (PKCE) and send the access token; this checks it against the
tenant's JWKS.

Roles are decided by the organiser, not the app, through Auth0 RBAC permissions on the API:
  government  AUTH0_GOVERNMENT_ROLE (default view:planner), or an email in SWELTER_GOVERNMENT: the planner web page
  responder   AUTH0_RESPONDER_ROLE (default respond:requests), or an email in SWELTER_RESPONDERS: the volunteer view
  resident    everyone else who signs in: the resident view
Government wins if an account has both.

Env: AUTH0_DOMAIN (e.g. swelter.us.auth0.com), AUTH0_CLIENT_ID (the native iPhone app), AUTH0_WEB_CLIENT_ID (the
single-page app for the planner page), AUTH0_AUDIENCE (the API identifier, e.g. https://api.swelter.app).
SWELTER_DEV_LOGIN=1 adds the three demo accounts (header X-Demo-Account) for a local build or a demo without a
tenant. Never set it in production.
"""
import os

DOMAIN = os.environ.get("AUTH0_DOMAIN", "").strip().rstrip("/")
CLIENT_ID = os.environ.get("AUTH0_CLIENT_ID", "")
WEB_CLIENT_ID = os.environ.get("AUTH0_WEB_CLIENT_ID", "")
AUDIENCE = os.environ.get("AUTH0_AUDIENCE", "")
ROLE = os.environ.get("AUTH0_RESPONDER_ROLE", "respond:requests")
GOV_ROLE = os.environ.get("AUTH0_GOVERNMENT_ROLE", "view:planner")


def _emails(var):
    return {e.strip().lower() for e in os.environ.get(var, "").split(",") if e.strip()}


RESPONDERS, GOVERNMENT = _emails("SWELTER_RESPONDERS"), _emails("SWELTER_GOVERNMENT")
DEV = os.environ.get("SWELTER_DEV_LOGIN") == "1"
CLAIMS = "https://swelter.app/"  # namespace for custom claims an Auth0 Action may add (name, email, roles)

# Kayla is the simulator's resident #1484 (backend/forecast.demo_resident); Marisol Rivera and Jordan Ellis are
# made up.
DEMO_ACCOUNTS = {
    "kayla": {"role": "resident", "name": "Kayla", "about": "Resident · Fairhill, North Philadelphia"},
    "marisol": {"role": "responder", "name": "Marisol Rivera", "about": "Responder · volunteer"},
    "jordan": {"role": "government", "name": "Jordan Ellis", "about": "Government · city emergency planner"},
}
_jwks = None


def config():
    return {"enabled": bool(DOMAIN), "domain": DOMAIN or None, "client_id": CLIENT_ID or None,
            "web_client_id": WEB_CLIENT_ID or None, "audience": AUDIENCE or None,
            "demo_accounts": [{"id": k} | v for k, v in DEMO_ACCOUNTS.items()] if DEV else []}


class AuthError(Exception):
    pass


def user(headers):
    """→ {sub, role, name, email, demo} for the signed-in caller, None if no credentials, AuthError if bad ones."""
    demo = headers.get("X-Demo-Account")
    if demo:
        a = DEMO_ACCOUNTS.get(demo)
        if not (DEV and a):
            raise AuthError("demo accounts are off on this server")
        return {"sub": f"demo|{demo}", "role": a["role"], "name": a["name"], "email": None, "demo": True}
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    if not DOMAIN:
        raise AuthError("sign-in is not configured on this server (set AUTH0_DOMAIN)")
    import jwt  # PyJWT

    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"https://{DOMAIN}/.well-known/jwks.json", cache_keys=True)
    token = auth[7:]
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        c = jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE or [CLIENT_ID, WEB_CLIENT_ID],
                       issuer=f"https://{DOMAIN}/")
    except Exception as e:
        raise AuthError(f"invalid token: {e}")
    email = (c.get(CLAIMS + "email") or c.get("email") or "").lower() or None
    granted = set(c.get("permissions", [])) | set(c.get(CLAIMS + "roles", []))
    role = ("government" if GOV_ROLE in granted or (email and email in GOVERNMENT) else
            "responder" if ROLE in granted or (email and email in RESPONDERS) else "resident")
    return {"sub": c["sub"], "role": role, "name": c.get(CLAIMS + "name") or c.get("name") or c.get("nickname"),
            "email": email, "demo": False}


def required(headers):
    u = user(headers)
    if not u:
        raise AuthError("sign in first")
    return u
