"""Sign-in with Auth0 for residents and responders. The iPhone app logs in through Auth0 Universal Login (PKCE) and
sends the access token; this checks it against the tenant's JWKS.

Who is a responder is decided by the organiser, not the app: the token must carry AUTH0_RESPONDER_ROLE (default
respond:requests, granted to a user through Auth0 RBAC), or the account's email must be in SWELTER_RESPONDERS.
Everyone else who signs in is a resident.

Env: AUTH0_DOMAIN (e.g. swelter.us.auth0.com), AUTH0_CLIENT_ID (the native app), AUTH0_AUDIENCE (the API identifier,
e.g. https://api.swelter.app). SWELTER_DEV_LOGIN=1 adds the two demo accounts (header X-Demo-Account) for a local
build or a demo without a tenant. Never set it in production.
"""
import os

DOMAIN = os.environ.get("AUTH0_DOMAIN", "").strip().rstrip("/")
CLIENT_ID = os.environ.get("AUTH0_CLIENT_ID", "")
AUDIENCE = os.environ.get("AUTH0_AUDIENCE", "")
ROLE = os.environ.get("AUTH0_RESPONDER_ROLE", "respond:requests")
RESPONDERS = {e.strip().lower() for e in os.environ.get("SWELTER_RESPONDERS", "").split(",") if e.strip()}
DEV = os.environ.get("SWELTER_DEV_LOGIN") == "1"
CLAIMS = "https://swelter.app/"  # namespace for custom claims an Auth0 Action may add (name, email, roles)

# Kayla is the simulator's resident #1484 (backend/forecast.demo_resident); Marisol Rivera is a made-up volunteer.
DEMO_ACCOUNTS = {
    "kayla": {"role": "resident", "name": "Kayla", "about": "Resident · Fairhill, North Philadelphia"},
    "marisol": {"role": "responder", "name": "Marisol Rivera", "about": "Responder · volunteer"},
}
_jwks = None


def config():
    return {"enabled": bool(DOMAIN), "domain": DOMAIN or None, "client_id": CLIENT_ID or None,
            "audience": AUDIENCE or None,
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
        c = jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE or CLIENT_ID, issuer=f"https://{DOMAIN}/")
    except Exception as e:
        raise AuthError(f"invalid token: {e}")
    email = (c.get(CLAIMS + "email") or c.get("email") or "").lower() or None
    granted = set(c.get("permissions", [])) | set(c.get(CLAIMS + "roles", []))
    role = "responder" if ROLE in granted or (email and email in RESPONDERS) else "resident"
    return {"sub": c["sub"], "role": role, "name": c.get(CLAIMS + "name") or c.get("name") or c.get("nickname"),
            "email": email, "demo": False}


def required(headers):
    u = user(headers)
    if not u:
        raise AuthError("sign in first")
    return u
